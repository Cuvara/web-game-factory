"""Running the critic: write the brief, run the command, check the verdict - visual QA's
plumbing (scripts/wgf_visualqa/judge.py), for units instead of states.

    brief     <workdir>/<stem>-<n>.brief.md
    judge     the configured argv, cwd <workdir>, an allowlisted environment
              (wgflib.agentenv), one owned process tree (wgflib.procs)
    isolation the Factory's guarded paths and the staged frames are fingerprinted around it;
              a critic that changed either is refused, and the guarded paths are restored
    verdict   coerced only where meaning cannot change (rubric.coerce), then checked strictly
              (rubric.problems); a malformed one goes back with every error, up to
              `repair_rounds` times, then once more from scratch (MAX_JUDGE_RUNS), then fails
"""

import os

from wgflib import agentenv, isolation, procs

from wgf_review.verdict import from_output

from .brief import PROMPT, PROMPT_STDOUT, render_brief
from .rubric import coerce, load_verdict, problems
from .units import sha256_of

__all__ = ["Outcome", "run_judge", "MAX_JUDGE_RUNS"]

MAX_JUDGE_RUNS = 2
_REPLY_CHARS = 200_000


class Outcome:
    def __init__(self):
        self.verdict = None
        self.failure = None
        self.runs = []
        self.repairs = 0
        self.coercions = []


def _snapshot(frames_dir, guarded):
    frames = {}
    for root, _dirs, files in os.walk(frames_dir):
        for name in files:
            path = os.path.join(root, name)
            frames[path] = sha256_of(path)
    return frames, isolation.take_guarded(guarded)


def _process_failure(result, settings):
    if result.error is not None:
        return {"code": "judge-not-started", "retryable": False,
                "message": f"critic command could not start: {result.error}"}
    if result.cancelled:
        return {"code": "cancelled", "retryable": False,
                "message": "level design critique cancelled; the critic's process tree was ended"}
    if result.timed_out:
        return {"code": "judge-timeout", "retryable": True,
                "message": f"critic timed out after {settings.timeout:.0f}s"}
    if result.idle_timed_out:
        return {"code": "judge-idle-timeout", "retryable": True,
                "message": f"critic produced no output for {settings.idle_timeout:.0f}s"}
    if result.returncode != 0:
        return {"code": "judge-crashed", "retryable": True,
                "message": f"critic command exited {result.returncode}"}
    return None


def _reply(verdict_path, stdout):
    text = None
    if os.path.isfile(verdict_path):
        try:
            with open(verdict_path, encoding="utf-8", errors="replace") as handle:
                text = handle.read(_REPLY_CHARS + 1)
        except OSError:
            text = None
    if not (text or "").strip() and stdout:
        text = stdout[-_REPLY_CHARS:]
    if not (text or "").strip():
        return None
    return text[:_REPLY_CHARS]


def run_judge(settings, rubric, workdir, units, frames_dir, *, title_id, commit, guarded=(),
              logger=None, stem="critic"):
    """Judge staged `units`. Never raises for the critic's own failure."""
    moments = [m["id"] for m in rubric["moments"]]
    outcome = Outcome()
    to_stdout = settings.verdict_from == "stdout"
    problem, repair, fresh, run = None, None, 0, 0
    while True:
        run += 1
        kind = "repair" if repair else "fresh"
        if kind == "fresh":
            fresh += 1
        else:
            outcome.repairs += 1
        verdict_path = os.path.join(workdir, f"{stem}-{run}.verdict.json")
        brief_path = os.path.join(workdir, f"{stem}-{run}.brief.md")
        log_path = os.path.join(workdir, f"{stem}-{run}.log")
        for stale in (verdict_path, log_path):
            if os.path.exists(stale):
                os.remove(stale)
        with open(brief_path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(render_brief(title_id=title_id, commit=commit, units=units,
                                      rubric=rubric, frames_dir=frames_dir,
                                      verdict_path=verdict_path, to_stdout=to_stdout,
                                      previous_problem=problem, repair=repair))
        values = {"frames_dir": frames_dir, "brief": brief_path, "verdict": verdict_path}
        values["prompt"] = (PROMPT_STDOUT if to_stdout else PROMPT).format(**values)
        argv = [part.format(**values) for part in settings.argv]
        env = agentenv.scrubbed(settings.env_passthrough)
        env.update({"WGF_LEVELDESIGN_FRAMES": frames_dir, "WGF_LEVELDESIGN_BRIEF": brief_path,
                    "WGF_LEVELDESIGN_VERDICT": verdict_path})
        before = _snapshot(frames_dir, guarded)
        if logger is not None:
            logger.info("level-design critic", argv0=os.path.basename(argv[0]), run=run,
                        kind=kind, units=len(units))
        result = procs.run(argv, cwd=workdir, env=env, timeout=settings.timeout,
                           idle_timeout=settings.idle_timeout, log_path=log_path,
                           heartbeat_seconds=15.0)
        after = _snapshot(frames_dir, guarded)
        record = {"run": run, "kind": kind, "argv0": os.path.basename(argv[0]),
                  "exit_code": result.returncode, "status": result.status, "log": log_path}
        outcome.runs.append(record)
        changed = sorted(p for p in set(before[0]) | set(after[0])
                         if before[0].get(p) != after[0].get(p))
        violations = isolation.diff(before[1], after[1])
        if changed or violations:
            restored, failures = (isolation.restore_guarded(before[1], guarded)
                                  if violations else (True, []))
            listed = [os.path.relpath(p, workdir) for p in changed[:5]] + [
                v["path"] for v in violations[:5]]
            outcome.failure = {"code": "judge-isolation-violation", "retryable": False,
                               "message": "the critic changed what it may only read: "
                                          + ", ".join(listed)
                                          + ("" if restored else "; RESTORING FAILED: "
                                             + "; ".join(failures[:5]))}
            break
        failure = _process_failure(result, settings)
        if failure is not None:
            failure["output_tail"] = result.tail(20)
            outcome.failure = failure
            break
        if to_stdout:
            extracted = from_output(result.stdout)
            if extracted is not None:
                with open(verdict_path, "w", encoding="utf-8") as handle:
                    handle.write(extracted)
        data, problem = load_verdict(verdict_path)
        errors = [problem] if problem else []
        coercions = []
        if not errors:
            data, coercions = coerce(data, rubric, units)
            errors = problems(data, rubric, units, moments)
        if not errors:
            outcome.verdict, outcome.coercions = data, coercions
            break
        problem = "; ".join(errors)
        record["problem"] = problem
        if logger is not None:
            logger.warning("level-design critic verdict malformed", run=run, problem=problem)
        reply = _reply(verdict_path, result.stdout if to_stdout else None)
        if reply is not None and outcome.repairs < settings.repair_rounds:
            repair = {"reply": reply, "problems": errors}
        elif fresh < MAX_JUDGE_RUNS:
            repair = None
        else:
            break
    if outcome.verdict is None and outcome.failure is None:
        outcome.failure = {"code": "malformed-verdict", "retryable": False,
                           "message": f"the critic's verdict was malformed after {fresh} fresh "
                                      f"attempt(s) and {outcome.repairs} repair round(s); "
                                      f"last: {problem}"}
    return outcome

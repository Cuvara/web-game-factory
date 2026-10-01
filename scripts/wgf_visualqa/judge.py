"""Running the judge: stage the frames, write the brief, run the command, check the verdict.

Shared by the step and scripts/wgf-visualqa.py (the judge outside a run), so a person sees
exactly what a run's judge saw.

    stage     copy every frame into <workdir>/frames/<viewport>/<frame-id>.png, each checked
              against the sha256 the playability-report recorded: the judge reads copies in
              a directory that holds nothing else, never the run's evidence or a checkout
    brief     <workdir>/brief-<n>.md
    judge     the configured argv, cwd <workdir>, an allowlisted environment
              (wgflib.agentenv), one owned process tree (wgflib.procs)
    isolation the Factory's guarded paths and the staged frames are fingerprinted around it;
              a judge that changed either is refused, and the guarded paths are restored
    verdict   parsed strictly (rubric.parse). A malformed one is asked for once more, with
              the reason in the brief; the second malformed verdict ends the judging.
"""

import hashlib
import os
import shutil
import time

from wgflib import agentenv, isolation, procs

from wgf_review.verdict import from_output

from .brief import PROMPT, PROMPT_STDOUT, frame_state, render_brief
from .rubric import parse

__all__ = ["FrameError", "Outcome", "stage_frames", "run_judge", "MAX_JUDGE_RUNS"]

# One retry of a malformed verdict; then the step fails. A judge that cannot write the shape
# twice will not on a third try, and every try is paid for.
MAX_JUDGE_RUNS = 2


class FrameError(Exception):
    """A frame to judge is missing (`missing`) or not what was recorded (`changed`)."""

    def __init__(self, kind, message):
        super().__init__(message)
        self.kind = kind


def sha256_of(path):
    with open(path, "rb") as handle:
        return "sha256:" + hashlib.sha256(handle.read()).hexdigest()


def png_size(path):
    """(width, height) from a PNG's IHDR, or None."""
    try:
        with open(path, "rb") as handle:
            head = handle.read(24)
    except OSError:
        return None
    if head[:8] != b"\x89PNG\r\n\x1a\n" or head[12:16] != b"IHDR":
        return None
    return int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big")


def stage_frames(entries, workdir):
    """Copy `entries` - [{project, id, source, sha256 (optional), viewport (optional)}] -
    into <workdir>/frames. Returns the frames as the brief and the report describe them."""
    frames_dir = os.path.join(workdir, "frames")
    shutil.rmtree(frames_dir, ignore_errors=True)
    staged = []
    for entry in entries:
        source = entry["source"]
        if not os.path.isfile(source):
            raise FrameError("missing", f"frame {entry['project']}/{entry['id']} is not at "
                                        f"{source}")
        digest = sha256_of(source)
        if entry.get("sha256") and entry["sha256"] != digest:
            raise FrameError("changed", f"frame {entry['project']}/{entry['id']} at {source} "
                                        f"is not the frame the playability step recorded "
                                        f"({entry['sha256']}, now {digest})")
        target = os.path.join(frames_dir, entry["project"], entry["id"] + ".png")
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copyfile(source, target)
        state, description = frame_state(entry["id"])
        staged.append({"key": f"{entry['project']}/{entry['id']}", "project": entry["project"],
                       "id": entry["id"], "state": state, "description": description,
                       "viewport": entry.get("viewport"), "size": png_size(target),
                       "file": target, "sha256": digest,
                       "path": entry.get("path") or source})
    return frames_dir, staged


class Outcome:
    """What judging produced. `verdict` is the parsed verdict, or None with `failure`
    ({code, message, retryable})."""

    def __init__(self):
        self.verdict = None
        self.failure = None
        self.runs = []          # per judge invocation: {exit_code, status, problem, ...}
        self.verdict_path = None
        self.brief_path = None
        self.duration_s = 0.0


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
                "message": f"judge command could not start: {result.error}"}
    if result.cancelled:
        return {"code": "cancelled", "retryable": False,
                "message": "visual QA cancelled; the judge's process tree was ended"}
    if result.timed_out:
        return {"code": "judge-timeout", "retryable": True,
                "message": f"judge timed out after {settings.timeout:.0f}s; its process tree "
                           f"was ended"}
    if result.idle_timed_out:
        return {"code": "judge-idle-timeout", "retryable": True,
                "message": f"judge produced no output for {settings.idle_timeout:.0f}s; its "
                           f"process tree was ended"}
    if result.returncode != 0:
        return {"code": "judge-crashed", "retryable": True,
                "message": f"judge command exited {result.returncode}"}
    return None


def run_judge(settings, rubric, workdir, frames, frames_dir, *, title_id, commit, design=None,
              manifest=None, quality=None, guarded=(), logger=None, stem="judge"):
    """Judge staged `frames`. Never raises for the judge's own failure."""
    outcome = Outcome()
    keys = [f["key"] for f in frames]
    to_stdout = settings.verdict_from == "stdout"
    problem = None
    began = time.monotonic()
    for run in range(1, MAX_JUDGE_RUNS + 1):
        verdict_path = os.path.join(workdir, f"{stem}-{run}.verdict.json")
        brief_path = os.path.join(workdir, f"{stem}-{run}.brief.md")
        log_path = os.path.join(workdir, f"{stem}-{run}.log")
        for stale in (verdict_path, log_path):
            if os.path.exists(stale):
                os.remove(stale)
        with open(brief_path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(render_brief(
                title_id=title_id, commit=commit, frames=frames, rubric=rubric, design=design,
                manifest=manifest, quality=quality, verdict_path=verdict_path,
                to_stdout=to_stdout, previous_problem=problem))
        outcome.verdict_path, outcome.brief_path = verdict_path, brief_path
        values = {"frames_dir": frames_dir, "brief": brief_path, "verdict": verdict_path}
        values["prompt"] = (PROMPT_STDOUT if to_stdout else PROMPT).format(**values)
        argv = [part.format(**values) for part in settings.argv]
        env = agentenv.scrubbed(settings.env_passthrough)
        env.update({"WGF_VISUALQA_FRAMES": frames_dir, "WGF_VISUALQA_BRIEF": brief_path,
                    "WGF_VISUALQA_VERDICT": verdict_path})
        before = _snapshot(frames_dir, guarded)
        if logger is not None:
            logger.info("visual-qa judge", argv0=os.path.basename(argv[0]), run=run,
                        frames=len(frames), timeout_s=settings.timeout)
        result = procs.run(argv, cwd=workdir, env=env, timeout=settings.timeout,
                           idle_timeout=settings.idle_timeout, log_path=log_path,
                           heartbeat_seconds=15.0)
        after = _snapshot(frames_dir, guarded)
        record = {"run": run, "argv0": os.path.basename(argv[0]),
                  "exit_code": result.returncode, "status": result.status, "log": log_path}
        outcome.runs.append(record)
        changed_frames = sorted(p for p in set(before[0]) | set(after[0])
                                if before[0].get(p) != after[0].get(p))
        violations = isolation.diff(before[1], after[1])
        if changed_frames or violations:
            restored, problems = (isolation.restore_guarded(before[1], guarded)
                                  if violations else (True, []))
            listed = [os.path.relpath(p, workdir) for p in changed_frames[:5]] + [
                v["path"] for v in violations[:5]]
            outcome.failure = {
                "code": "judge-isolation-violation", "retryable": False,
                "message": f"the judge changed what it may only read: {', '.join(listed)}"
                           + ("" if restored else "; RESTORING FAILED: "
                              + "; ".join(problems[:5]))}
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
        verdict, problem = parse(verdict_path, rubric, keys)
        if verdict is None and to_stdout and problem.startswith("no "):
            problem = "the judge's output ends with no JSON verdict"
        if verdict is not None:
            outcome.verdict = verdict
            break
        record["problem"] = problem
        if logger is not None:
            logger.warning("visual-qa judge verdict malformed", run=run, problem=problem)
    if outcome.verdict is None and outcome.failure is None:
        outcome.failure = {"code": "malformed-verdict", "retryable": False,
                           "message": f"the judge's verdict was malformed {MAX_JUDGE_RUNS} "
                                      f"times; last: {problem}"}
    outcome.duration_s = time.monotonic() - began
    return outcome

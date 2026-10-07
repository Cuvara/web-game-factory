"""The paired judgement: the accepted frame and the candidate frame of the same state, side by
side, judged per visual-qa rubric dimension as better, same or worse.

A judge that scores one build at a time scored the environment 4 for the accepted build and
4 for the build a person found much worse (2026-10-05): an absolute score is the wrong
question once a build has been accepted. This asks the right one - compared with what was
accepted, is this better, the same, or worse? - with the judge visual QA already uses
(factory.visualqa.judge, wgf_visualqa.settings):

    pairs(spec, accepted, candidate)   the frames both builds captured for the same state,
                                       per viewport, in core/reference/accepted-baseline.yaml
                                       `paired.states` order, at most `max_pairs` per viewport
    stage(pairs, workdir)              copies, checked against their recorded sha256, into
                                       <workdir>/pairs/<viewport>/<state>/{accepted,
                                       candidate}.png - the judge reads nothing else
    judge(settings, rubric, spec, staged, workdir, ...)
                                       {status, judge, dimensions: {id: {verdict, reason}},
                                        pairs, problem}

    kind: command   the configured argv (placeholders {frames_dir}, {brief}, {verdict},
                    {prompt}), an allowlisted environment, one owned process tree
                    (wgflib.procs), the staged frames and the Factory's guarded paths
                    fingerprinted around it - a judge that changed either is refused. Its
                    verdict: {"dimensions": {"<rubric dimension>": {"verdict": "better" |
                    "same" | "worse", "reason": "..."}}} for every rubric dimension.
    kind: baseline  no agent (golden runs): each pair's similarity
                    (wgf_visualqa.baseline.similarity); a pair below the bar makes the
                    `paired.baseline_dimensions` worse, else they are the same. A mechanical
                    judge cannot tell better from different, so it never answers better.
    kind: none      UNMEASURED: nothing judged, which is never a pass.

Fewer than `min_pairs` pairs on every viewport: UNMEASURED, with the reason.
"""

import json
import os
import shutil
import time

from wgflib import agentenv, isolation, procs

__all__ = ["pairs", "stage", "judge", "parse_verdict", "PairError", "PROMPT"]

PROMPT = (
    "You compare two builds of one web game: the build a person ACCEPTED and a CANDIDATE that "
    "would replace it. Read {brief} in full, then look at every pair of PNG frames under "
    "{frames_dir} it lists (accepted.png and candidate.png of the same state). You are "
    "READ-ONLY: write your verdict, and nothing else, as one JSON object to {verdict}, "
    "exactly in the shape the brief gives."
)
PROMPT_STDOUT = (
    "You compare two builds of one web game: the build a person ACCEPTED and a CANDIDATE that "
    "would replace it. Read {brief} in full, then look at every pair of PNG frames under "
    "{frames_dir} it lists (accepted.png and candidate.png of the same state). You are "
    "READ-ONLY: do not create, edit or delete any file. End your answer with your verdict as "
    "one JSON object, exactly in the shape the brief gives."
)
MAX_RUNS = 2


class PairError(Exception):
    """A frame to pair is missing or not what its report recorded."""


def _sha256(path):
    import hashlib
    with open(path, "rb") as handle:
        return "sha256:" + hashlib.sha256(handle.read()).hexdigest()


def pairs(spec, accepted, candidate):
    """[{project, state, accepted: frame, candidate: frame}]. A frame is {project, id,
    source (absolute path), sha256}."""
    rules = spec.get("paired") or {}
    order = list(rules.get("states") or [])
    limit = int(rules.get("max_pairs") or len(order) or 1)
    index_a = {(f.get("project"), f.get("id")): f for f in accepted or []}
    index_c = {(f.get("project"), f.get("id")): f for f in candidate or []}
    projects = sorted({p for p, _ in index_a} & {p for p, _ in index_c})
    out = []
    for project in projects:
        taken = 0
        for state in order:
            a, c = index_a.get((project, state)), index_c.get((project, state))
            if a and c and taken < limit:
                out.append({"project": project, "state": state, "accepted": a,
                            "candidate": c})
                taken += 1
    return out


def stage(found, workdir):
    root = os.path.join(workdir, "pairs")
    shutil.rmtree(root, ignore_errors=True)
    staged = []
    for pair in found:
        entry = {"project": pair["project"], "state": pair["state"]}
        for side in ("accepted", "candidate"):
            frame = pair[side]
            source = frame.get("source")
            if not source or not os.path.isfile(source):
                raise PairError(f"the {side} frame {pair['project']}/{pair['state']} is not "
                                f"at {source}")
            digest = _sha256(source)
            if frame.get("sha256") and frame["sha256"] != digest:
                raise PairError(f"the {side} frame {pair['project']}/{pair['state']} at "
                                f"{source} is not the frame its report recorded")
            target = os.path.join(root, pair["project"], pair["state"], side + ".png")
            os.makedirs(os.path.dirname(target), exist_ok=True)
            shutil.copyfile(source, target)
            entry[side] = {"file": target, "sha256": digest,
                           "path": frame.get("path") or source}
        staged.append(entry)
    return root, staged


def _dimensions(rubric):
    return list((rubric or {}).get("dimensions") or {})


def render_brief(rubric, staged, frames_dir, verdict_path, title_id, accepted_commit,
                 candidate_commit, problem=None, to_stdout=False):
    dims = (rubric or {}).get("dimensions") or {}
    out = [f"# Paired visual judgement: {title_id}\n",
           f"The ACCEPTED build (`{str(accepted_commit)[:12]}`) is the build a person played "
           "and accepted. The CANDIDATE build "
           f"(`{str(candidate_commit)[:12]}`) would replace it. For each state below you see "
           "the accepted frame and the candidate frame of the same moment of play, on the "
           "same viewport. Judge the candidate AGAINST the accepted build, not against an "
           "ideal: for each dimension, is the candidate better, the same, or worse?\n",
           "A difference is not an improvement. Worse means a player who saw the accepted "
           "build would find the candidate poorer on that dimension: less finished, harder "
           "to read, a poorer sense of place, plainer UI, a less deliberate frame, less "
           "coherent, or development output left on screen. Same means no difference a "
           "player would notice. Better only when the candidate is plainly better.\n",
           f"## Pairs (under `{frames_dir}`)\n"]
    for entry in staged:
        rel = os.path.relpath(os.path.dirname(entry["accepted"]["file"]), frames_dir)
        out.append(f"- `{rel}/accepted.png` vs `{rel}/candidate.png` - {entry['project']}, "
                   f"state `{entry['state']}`")
    out.append("\n## Dimensions (core/reference/visual-qa-rubric.yaml)\n")
    for dim_id, dim in dims.items():
        out.append(f"- `{dim_id}`: {(dim or {}).get('question') or dim_id}")
    shape = {"dimensions": {d: {"verdict": "same", "reason": "..."} for d in dims}}
    out.append("\n## Verdict\n")
    out.append(("End your answer with one JSON object" if to_stdout else
                f"Write one JSON object to `{verdict_path}`")
               + ", with every dimension above, each verdict one of `better`, `same`, "
                 "`worse`, and a reason naming the pair(s) that show it:\n")
    out.append("```json\n" + json.dumps(shape, indent=2) + "\n```\n")
    if problem:
        out.append(f"Your previous verdict could not be used: {problem}. Write the full "
                   "verdict again.\n")
    return "\n".join(out)


def parse_verdict(data, rubric, verdicts=("better", "same", "worse")):
    """({dimension: {verdict, reason}}, problem)."""
    if not isinstance(data, dict) or not isinstance(data.get("dimensions"), dict):
        return None, "the verdict must be an object with `dimensions`"
    out, missing, bad = {}, [], []
    for dim in _dimensions(rubric):
        item = data["dimensions"].get(dim)
        if not isinstance(item, dict):
            missing.append(dim)
            continue
        verdict = str(item.get("verdict") or "").strip().lower()
        if verdict not in verdicts:
            bad.append(f"{dim}: {item.get('verdict')!r}")
            continue
        out[dim] = {"verdict": verdict, "reason": str(item.get("reason") or "")[:600]}
    if missing or bad:
        return None, "; ".join(
            ([f"missing dimension(s): {', '.join(missing)}"] if missing else [])
            + ([f"verdict not one of {', '.join(verdicts)}: {', '.join(bad)}"] if bad else []))
    return out, None


def _baseline(rubric, spec, staged, bar):
    from wgf_assets.raster import RasterError, decode_png
    from wgf_visualqa.baseline import signature, similarity
    rules = spec.get("paired") or {}
    reading = list(rules.get("baseline_dimensions") or [])
    compared = []
    for entry in staged:
        try:
            with open(entry["accepted"]["file"], "rb") as handle:
                a = signature(decode_png(handle.read()))
            with open(entry["candidate"]["file"], "rb") as handle:
                c = signature(decode_png(handle.read()))
        except (OSError, RasterError) as exc:
            return None, f"a paired frame cannot be decoded: {exc}", compared
        score, parts = similarity(a, c)
        compared.append({"project": entry["project"], "state": entry["state"],
                         "similarity": score, "parts": parts})
    below = [c for c in compared if c["similarity"] < bar]
    dims = {}
    for dim in _dimensions(rubric):
        if dim in reading and below:
            dims[dim] = {"verdict": "worse", "reason": "below the similarity bar "
                         f"{bar:g}: " + ", ".join(f"{c['project']}/{c['state']} "
                                                  f"{c['similarity']:g}" for c in below[:6])}
        else:
            dims[dim] = {"verdict": "same", "reason": (
                "every pair at or above the similarity bar" if dim in reading else
                "not read by the mechanical judge: it cannot tell better from different")}
    return dims, None, compared


def judge(settings, rubric, spec, staged, frames_dir, workdir, *, title_id, accepted_commit,
          candidate_commit, guarded=(), logger=None):
    rules = spec.get("paired") or {}
    out = {"status": None, "judge": getattr(settings, "kind", None), "dimensions": {},
           "pairs": [{"project": e["project"], "state": e["state"],
                      "accepted": {"path": e["accepted"]["path"],
                                   "sha256": e["accepted"]["sha256"]},
                      "candidate": {"path": e["candidate"]["path"],
                                    "sha256": e["candidate"]["sha256"]}} for e in staged],
           "problem": None}
    per_project = {}
    for e in staged:
        per_project[e["project"]] = per_project.get(e["project"], 0) + 1
    if max(per_project.values() or [0]) < int(rules.get("min_pairs") or 1):
        out["status"] = "UNMEASURED"
        out["problem"] = (f"{len(staged)} pair(s) of the same state on both builds, fewer than "
                          f"{rules.get('min_pairs')} on every viewport: nothing to compare")
        return out
    kind = getattr(settings, "kind", "none")
    if kind == "none":
        out["status"] = "UNMEASURED"
        out["problem"] = "no judge configured (factory.visualqa.judge.kind: none)"
        return out
    if kind == "baseline":
        from wgf_visualqa.baseline import MIN_SIMILARITY
        bar = float(settings.min_similarity or MIN_SIMILARITY)
        dims, problem, compared = _baseline(rubric, spec, staged, bar)
        out["comparisons"] = compared
        if problem:
            out["status"], out["problem"] = "UNMEASURED", problem
            return out
        out["dimensions"] = dims
        out["status"] = "FAIL" if any(d["verdict"] == "worse" for d in dims.values()) \
            else "PASS"
        return out

    from wgf_review.verdict import from_output
    from wgf_visualqa.judge import _process_failure, _snapshot
    to_stdout = getattr(settings, "verdict_from", "file") == "stdout"
    problem = None
    for run in range(1, MAX_RUNS + 1):
        verdict_path = os.path.join(workdir, f"paired-{run}.verdict.json")
        brief_path = os.path.join(workdir, f"paired-{run}.brief.md")
        log_path = os.path.join(workdir, f"paired-{run}.log")
        for stale in (verdict_path, log_path):
            if os.path.exists(stale):
                os.remove(stale)
        with open(brief_path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(render_brief(rubric, staged, frames_dir, verdict_path, title_id,
                                      accepted_commit, candidate_commit, problem, to_stdout))
        values = {"frames_dir": frames_dir, "brief": brief_path, "verdict": verdict_path}
        values["prompt"] = (PROMPT_STDOUT if to_stdout else PROMPT).format(**values)
        argv = [part.format(**values) for part in settings.argv]
        env = agentenv.scrubbed(settings.env_passthrough)
        env.update({"WGF_VISUALQA_FRAMES": frames_dir, "WGF_VISUALQA_BRIEF": brief_path,
                    "WGF_VISUALQA_VERDICT": verdict_path})
        before = _snapshot(frames_dir, guarded)
        if logger is not None:
            logger.info("paired judge", argv0=os.path.basename(argv[0]), run=run,
                        pairs=len(staged))
        started = time.monotonic()
        result = procs.run(argv, cwd=workdir, env=env, timeout=settings.timeout,
                           idle_timeout=settings.idle_timeout, log_path=log_path,
                           heartbeat_seconds=15.0)
        after = _snapshot(frames_dir, guarded)
        changed = sorted(p for p in set(before[0]) | set(after[0])
                         if before[0].get(p) != after[0].get(p))
        violations = isolation.diff(before[1], after[1])
        if changed or violations:
            if violations:
                isolation.restore_guarded(before[1], guarded)
            out["status"] = "BLOCKED"
            out["problem"] = ("the paired judge changed what it may only read: "
                              + ", ".join([os.path.relpath(p, workdir) for p in changed[:5]]
                                          + [v["path"] for v in violations[:5]]))
            return out
        failure = _process_failure(result, settings)
        if failure is not None:
            out["status"] = "BLOCKED" if not failure.get("retryable") else "UNMEASURED"
            out["problem"] = failure["message"]
            return out
        if to_stdout:
            extracted = from_output(result.stdout)
            if extracted is not None:
                with open(verdict_path, "w", encoding="utf-8") as handle:
                    handle.write(extracted)
        try:
            with open(verdict_path, encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError) as exc:
            data, problem = None, f"no readable verdict at {verdict_path}: {exc}"
        if data is not None:
            dims, problem = parse_verdict(data, rubric, tuple(rules.get("verdicts")
                                                              or ("better", "same", "worse")))
            if dims is not None:
                out["dimensions"] = dims
                out["duration_s"] = round(time.monotonic() - started, 1)
                out["status"] = "FAIL" if any(d["verdict"] == "worse"
                                              for d in dims.values()) else "PASS"
                return out
    out["status"] = "UNMEASURED"
    out["problem"] = f"the paired judge's verdict was unusable after {MAX_RUNS} runs: {problem}"
    return out

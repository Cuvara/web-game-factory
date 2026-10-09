"""The golden loop's before/after record: did a real check fail, get routed back, and pass on a
newer commit? Read only from what the run left behind.

A golden run with a defect (harness.GoldenRun(defect=...), run.py --defect) has the replay
developer plant a known defect into the greybox build (replay_developer.DEFECTS) and leave it
out once a brief names the defect's check failed. This module reads, from the run store and
the game repository's history:

    every playability-report greybox-playability produced, in production order - its commit,
    verdict, and the defect's check per project (viewport) with the frames the check cites,
    resolved under the run directory, checked to exist and digested;
    the replay developer's own record of what it did at that commit
    (docs/development/report.json `replay.defect`, read with `git show <commit>:`);
    how often greybox and greybox-playability were visited, and how the run ended.

The loop is CLOSED only when all of these hold:

    the first report FAILS, with the check FAIL on every project, each citing frames that
    exist, on a commit whose developer record says `planted`;
    the last report PASSES, with the check PASS (measured - never UNMEASURED, SKIPPED,
    BLOCKED or absent) on every project, on a commit whose developer record says
    `repaired`;
    the passing commit is a different, later commit descending from the failing one;
    greybox was visited at least twice.

`write` copies the cited frames of the first and the last report into the evidence directory
(golden-loop/<n>-<commit>/<project>/<frame>.png) and writes golden-loop-<game>.json there. A
replay is not an agent: the record says so, and so does every developer record it quotes.
"""

import hashlib
import json
import os
import shutil

from wgflib import procs
from wgflib.workflow.model import ArtifactRef

from golden import replay_developer

PLAYED_BY = "greybox-playability"
DEVELOPED_BY = "greybox"
PLAYABILITY_REPORT = "playability-report"
PROJECTS = ("desktop", "mobile")
FORMAT = 1


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 16), b""):
            digest.update(block)
    return "sha256:" + digest.hexdigest()


def _git(repo, *args):
    result = procs.run(["git", "-C", repo, *args], timeout=60)
    return result


def developer_record(repo, commit):
    """report.json `replay.defect` as committed at `commit`, or None."""
    if not commit or not os.path.isdir(repo):
        return None
    shown = _git(repo, "show", f"{commit}:{replay_developer.REPORT_PATH}")
    if not shown.ok:
        return None
    try:
        report = json.loads(shown.stdout)
    except ValueError:
        return None
    return ((report or {}).get("replay") or {}).get("defect")


def descends(repo, older, newer):
    """True when `newer` is a different commit with `older` among its ancestors."""
    if not older or not newer or older == newer or not os.path.isdir(repo):
        return False
    return _git(repo, "merge-base", "--is-ancestor", older, newer).ok


def _reports(state):
    refs = [ref for versions in (state.artifacts or {}).values() for ref in versions
            if ref.type == PLAYABILITY_REPORT and ref.produced_by == PLAYED_BY]
    return sorted(refs, key=ArtifactRef.order)


def _version(store, state, ref, number, check, repo):
    run_dir = store.run_dir(state.run_id)
    report = store.read_artifact(state.run_id, ref)
    frame_paths = {(f.get("project"), f.get("id")): f.get("path")
                   for f in report.get("frames") or []}
    viewports = {p.get("id"): p.get("viewport") for p in report.get("projects") or []}
    per_project = {}
    for entry in report.get("checks") or []:
        if entry.get("id") != check:
            continue
        project = entry.get("project")
        frames = []
        for frame_id in entry.get("frames") or []:
            relative = frame_paths.get((project, frame_id))
            absolute = os.path.join(run_dir, *relative.split("/")) if relative else None
            exists = bool(absolute and os.path.isfile(absolute))
            frames.append({"id": frame_id, "path": relative, "exists": exists,
                           "sha256": _sha256(absolute) if exists else None})
        per_project[project] = {
            "status": entry.get("status"), "required": entry.get("required"),
            "summary": entry.get("summary"), "measured": entry.get("measured"),
            "expected": entry.get("expected"), "viewport": viewports.get(project),
            "frames": frames,
        }
    defect = developer_record(repo, report.get("commit"))
    return {
        "version": number,
        "artifact": f"{ref.id}@v{ref.version}",
        "content_hash": ref.content_hash,
        "commit": report.get("commit"),
        "verdict": report.get("verdict"),
        "measurement_class": report.get("measurement_class"),
        "failed_checks": report.get("failed_checks"),
        "check_status": {p: (per_project.get(p) or {}).get("status") for p in PROJECTS},
        "check": per_project,
        "developer": ({k: defect.get(k) for k in ("status", "reason", "label", "iteration",
                                                   "failures_named", "repair")}
                      if isinstance(defect, dict) else None),
    }


def _failed_with_evidence(version):
    """FAIL, with the check FAIL on every project, each citing frames that all exist."""
    return version["verdict"] == "FAIL" and all(
        version["check_status"][p] == "FAIL" and version["check"][p]["frames"]
        and all(f["exists"] for f in version["check"][p]["frames"])
        for p in PROJECTS)


def record(store, state, repo, defect, repair=True):
    """The loop's record: {"closed", "reasons", "versions", "before", "after", ...}."""
    spec = replay_developer.DEFECTS[defect]
    check = spec["check"]
    versions = [_version(store, state, ref, number, check, repo)
                for number, ref in enumerate(_reports(state), 1)]
    greybox = state.steps.get(DEVELOPED_BY)
    played = state.steps.get(PLAYED_BY)
    first = versions[0] if versions else None
    last = versions[-1] if len(versions) > 1 else None
    reasons = []
    if first is None:
        reasons.append(f"{PLAYED_BY} produced no playability-report")
    else:
        if not _failed_with_evidence(first):
            reasons.append(f"report v1 ({(first['commit'] or '')[:12]}) is not a FAIL with "
                           f"{check} FAIL on {', '.join(PROJECTS)} citing frames that exist: "
                           f"verdict {first['verdict']}, {first['check_status']}")
        if (first["developer"] or {}).get("status") != "planted":
            reasons.append(f"the developer record at v1 is not `planted`: {first['developer']}")
    if last is None:
        reasons.append(f"{PLAYED_BY} produced no second report: nothing was re-played")
    else:
        if last["verdict"] != "PASS" or any(last["check_status"][p] != "PASS" for p in PROJECTS):
            reasons.append(f"report v{last['version']} ({(last['commit'] or '')[:12]}) is not a "
                           f"PASS with {check} PASS measured on {', '.join(PROJECTS)}: verdict "
                           f"{last['verdict']}, {last['check_status']}")
        if (last["developer"] or {}).get("status") != "repaired":
            reasons.append(f"the developer record at v{last['version']} is not `repaired`: "
                           f"{last['developer']}")
        if first is not None and not descends(repo, first["commit"], last["commit"]):
            reasons.append(f"the passing commit {last['commit']} is not a newer commit "
                           f"descending from the failing {first['commit']}")
    if not greybox or greybox.visits < 2:
        reasons.append(f"{DEVELOPED_BY} was visited {greybox.visits if greybox else 0} time(s): "
                       f"no failure was routed back to it")

    def side(version):
        if version is None:
            return None
        return {"commit": version["commit"], "artifact": version["artifact"],
                "verdict": version["verdict"],
                "developer": (version["developer"] or {}).get("status"),
                "projects": {p: {"status": (version["check"].get(p) or {}).get("status"),
                                 "viewport": (version["check"].get(p) or {}).get("viewport"),
                                 "summary": (version["check"].get(p) or {}).get("summary"),
                                 "frames": (version["check"].get(p) or {}).get("frames") or []}
                             for p in PROJECTS}}

    return {
        "format": FORMAT,
        "kind": "golden-loop",
        "defect": defect,
        "defect_summary": spec["summary"],
        "check": check,
        "repair": bool(repair),
        "developer": replay_developer.REPLAY_LABEL,
        "label": replay_developer.DEFECT_LABEL,
        "run_id": state.run_id,
        "run_status": state.status,
        "run_message": state.message,
        "blocked_reason": state.blocked_reason,
        "visits": {DEVELOPED_BY: greybox.visits if greybox else 0,
                   PLAYED_BY: played.visits if played else 0},
        "versions": versions,
        "before": side(first),
        "after": side(last),
        "closed": not reasons,
        "reasons": reasons,
    }


def write(loop_record, run_dir, evidence_dir, key):
    """Copy the first and the last report's cited frames into <evidence_dir>/golden-loop/ and
    write <evidence_dir>/golden-loop-<key>.json. Each copied frame's `evidence` path is
    relative to evidence_dir; a copy that fails leaves it None. Returns the JSON's path."""
    target = os.path.join(evidence_dir, "golden-loop")
    wanted = [v for v in (loop_record["versions"][:1] + loop_record["versions"][1:][-1:])]
    for version in wanted:
        folder = f"v{version['version']}-{(version['commit'] or 'none')[:12]}"
        for project, entry in version["check"].items():
            for frame in entry["frames"]:
                frame["evidence"] = None
                if not frame["exists"]:
                    continue
                destination = os.path.join(target, folder, project or "_",
                                           f"{frame['id']}.png")
                try:
                    os.makedirs(os.path.dirname(destination), exist_ok=True)
                    shutil.copyfile(os.path.join(run_dir, *frame["path"].split("/")),
                                    destination)
                except OSError:
                    continue
                frame["evidence"] = os.path.relpath(destination,
                                                    evidence_dir).replace(os.sep, "/")
    os.makedirs(evidence_dir, exist_ok=True)
    path = os.path.join(evidence_dir, f"golden-loop-{key}.json")
    loop_record["path"] = path
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(loop_record, handle, indent=2, sort_keys=True, default=str)
        handle.write("\n")
    return path

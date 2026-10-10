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

THE DEVELOP STAGE (`stage="develop"`, run.py --defect-stage develop). The defect is planted
in the first production develop visit instead, so the reports read are playability's, the
step routed back to is develop - through triage, which turns the failed check into findings
and routes them to the specialist that owns them - and `after` is the report of the visit
that repaired it (the first later report whose developer record says `repaired`). That
route exercises the run's finding ledger, and the loop is closed only when the ledger says
so too, for each project's finding `playability-report:<check>@<project>`:

    a triage-report detected it and assigned it to its owner, and develop was entered for
    that owner (route `triage.<owner>`);
    the newest ledger (the quality-report's, else the newest triage-report's) holds it
    verified or closed, through `implemented`, with `fix.commit` the repairing commit, and
    `verification` verdict `passed`, `before` the failing commit's FAIL and `after` the
    repairing commit's PASS of the same scenario id `<check>@<project>`, the comparison the
    same scenario, and every frame either measurement cites on disk with its sha256;
    the quality-report's `open` does not list it.

The record copies those ledger records in (`ledger`), with the quality-report's assessment
lines (`assessment`): a view of the evidence that decides nothing.
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
# Per defect stage (replay_developer.STAGES): (the develop step, the step that plays it).
STEPS = {None: (DEVELOPED_BY, PLAYED_BY), "greybox": (DEVELOPED_BY, PLAYED_BY),
         "develop": ("develop", "playability")}
TRIAGE_REPORT = "triage-report"
QUALITY_REPORT = "quality-report"
DONE = ("verified", "closed")


def evidence_key(game_key, stage=None):
    """The evidence file's key: `<game>` for the greybox stage (as before), else
    `<game>-<stage>`."""
    return game_key if stage in (None, "greybox") else f"{game_key}-{stage}"


def finding_id(check, project):
    """The finding triage normalizes a failed playability check into (wgf_triage.findings)."""
    return f"{PLAYABILITY_REPORT}:{check}@{project}"


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


def _reports(state, played_by=PLAYED_BY):
    refs = [ref for versions in (state.artifacts or {}).values() for ref in versions
            if ref.type == PLAYABILITY_REPORT and ref.produced_by == played_by]
    return sorted(refs, key=ArtifactRef.order)


def _of_type(state, kind):
    refs = [ref for versions in (state.artifacts or {}).values() for ref in versions
            if ref.type == kind]
    return sorted(refs, key=ArtifactRef.order)


def _bare(digest):
    return str(digest or "").split(":", 1)[-1].lower()


def _frames_on_disk(run_dir, measurement):
    """[{id, path, sha256, exists, matches}] for each frame a ledger measurement cites."""
    out = []
    for frame in (measurement or {}).get("frames") or []:
        relative = frame.get("path")
        absolute = (os.path.join(run_dir, *relative.split("/"))
                    if relative and not os.path.isabs(relative) else relative)
        exists = bool(absolute and os.path.isfile(absolute))
        actual = _sha256(absolute) if exists else None
        out.append({"id": frame.get("id"), "path": relative, "sha256": frame.get("sha256"),
                    "exists": exists,
                    "matches": bool(exists and frame.get("sha256")
                                    and _bare(actual) == _bare(frame.get("sha256")))})
    return out


def ledger_view(store, state, check, before_commit=None, after_commit=None):
    """What the run's finding ledger says of the defect's findings, one per project: the
    records copied from every triage-report and from the newest quality-report, and the
    reasons the ledger does not show the repair verified (empty when it does)."""
    run_dir = store.run_dir(state.run_id)
    ids = [finding_id(check, p) for p in PROJECTS]
    triage = []
    for ref in _of_type(state, TRIAGE_REPORT):
        content = store.read_artifact(state.run_id, ref)
        by_id = {r.get("id"): r for r in content.get("lifecycle") or []
                 if isinstance(r, dict)}
        triage.append({"artifact": f"{ref.id}@v{ref.version}", "seq": ref.seq,
                       "produced_by": ref.produced_by,
                       "selected": {k: (content.get("selected") or {}).get(k)
                                    for k in ("label", "owner", "findings")},
                       "records": {fid: by_id[fid] for fid in ids if fid in by_id}})
    quality = None
    assessment = None
    qrefs = _of_type(state, QUALITY_REPORT)
    if qrefs:
        content = store.read_artifact(state.run_id, qrefs[-1])
        block = content.get("ledger") or {}
        by_id = {r.get("id"): r for r in block.get("lifecycle") or [] if isinstance(r, dict)}
        quality = {"artifact": f"{qrefs[-1].id}@v{qrefs[-1].version}", "seq": qrefs[-1].seq,
                   "open": list(block.get("open") or []),
                   "awaiting": list(block.get("awaiting") or []),
                   "records": {fid: by_id[fid] for fid in ids if fid in by_id}}
        assessment = [{k: d.get(k) for k in ("id", "status", "basis", "reason", "classes")}
                      for d in (content.get("assessment") or {}).get("dimensions") or []
                      if isinstance(d, dict)]
    reasons = []
    owners = set()
    develop = state.steps.get("develop")
    for fid in ids:
        seen = [t["records"][fid] for t in triage if fid in t["records"]]
        statuses = [h.get("status") for r in seen[-1:] for h in r.get("history") or []]
        if not seen:
            reasons.append(f"no triage-report records {fid}")
            continue
        if "detected" not in statuses or "assigned" not in statuses:
            reasons.append(f"the triage-report never took {fid} through detected -> "
                           f"assigned: {statuses}")
        owner = seen[-1].get("owner")
        owners.add(owner)
        if not develop or not (develop.route_visits or {}).get(f"triage.{owner}"):
            reasons.append(f"develop was never entered for {fid}'s owner {owner!r} "
                           f"(route triage.{owner}): {develop and develop.route_visits}")
        final = (quality or {}).get("records", {}).get(fid) if quality else None
        final = final or seen[-1]
        history = [h.get("status") for h in final.get("history") or []]
        verification = final.get("verification") or {}
        if final.get("status") not in DONE:
            reasons.append(f"the ledger holds {fid} {final.get('status')}, not verified or "
                           f"closed (verification {verification.get('verdict')})")
            continue
        if "implemented" not in history or "verified" not in history:
            reasons.append(f"{fid} reached {final.get('status')} without implemented -> "
                           f"verified: {history}")
        if after_commit and (final.get("fix") or {}).get("commit") != after_commit:
            reasons.append(f"{fid}'s fix commit is {(final.get('fix') or {}).get('commit')}, "
                           f"not the repairing commit {after_commit}")
        if verification.get("verdict") != "passed":
            reasons.append(f"{fid}'s verification verdict is {verification.get('verdict')}")
        project = fid.rsplit("@", 1)[-1]
        scenario_id = f"{check}@{project}"
        for side, commit, status in (("before", before_commit, "FAIL"),
                                     ("after", after_commit, "PASS")):
            measurement = verification.get(side) or {}
            if commit and measurement.get("commit") != commit:
                reasons.append(f"{fid}'s verification.{side} is commit "
                               f"{measurement.get('commit')}, not {commit}")
            if measurement.get("status") != status:
                reasons.append(f"{fid}'s verification.{side} is {measurement.get('status')}, "
                               f"not {status}")
            if ((measurement.get("scenario") or {}).get("id")) != scenario_id:
                reasons.append(f"{fid}'s verification.{side} scenario is "
                               f"{(measurement.get('scenario') or {}).get('id')}, not "
                               f"{scenario_id}")
            frames = _frames_on_disk(run_dir, measurement)
            if not frames or not all(f["exists"] and f["matches"] for f in frames):
                reasons.append(f"{fid}'s verification.{side} frames are not all on disk with "
                               f"their sha256: {frames}")
        if not (verification.get("comparison") or {}).get("same_scenario"):
            reasons.append(f"{fid}'s comparison is not the same scenario: "
                           f"{(verification.get('comparison') or {}).get('note')}")
        if quality and fid in quality["open"]:
            reasons.append(f"the quality-report lists {fid} open")
    if quality is None:
        reasons.append("no quality-report: nothing advanced the ledger after the repair")
    final_records = {}
    for fid in ids:
        record = ((quality or {}).get("records") or {}).get(fid)
        if record is None:
            record = next((t["records"][fid] for t in reversed(triage)
                           if fid in t["records"]), None)
        if record is not None:
            verification = record.get("verification") or {}
            record = dict(record, frames_on_disk={
                side: _frames_on_disk(run_dir, verification.get(side))
                for side in ("before", "after")})
        final_records[fid] = record
    return {"ids": ids, "owners": sorted(o for o in owners if o), "triage": triage,
            "quality": quality, "final": final_records, "assessment": assessment,
            "verified": not reasons, "reasons": reasons}


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
        "developer": ({**{k: defect.get(k) for k in ("status", "reason", "label", "iteration",
                                                      "failures_named", "repair")},
                       **{k: defect[k] for k in ("stage", "specialist", "findings_named")
                          if k in defect}}
                      if isinstance(defect, dict) else None),
    }


def _failed_with_evidence(version):
    """FAIL, with the check FAIL on every project, each citing frames that all exist."""
    return version["verdict"] == "FAIL" and all(
        version["check_status"][p] == "FAIL" and version["check"][p]["frames"]
        and all(f["exists"] for f in version["check"][p]["frames"])
        for p in PROJECTS)


def record(store, state, repo, defect, repair=True, stage=None):
    """The loop's record: {"closed", "reasons", "versions", "before", "after", ...}.
    `stage` (replay_developer.STAGES; None = the defect's own phase, greybox) says which
    develop step the defect was planted in, and so which reports are read."""
    spec = replay_developer.DEFECTS[defect]
    check = spec["check"]
    if stage not in STEPS:
        raise ValueError(f"unknown defect stage {stage!r}")
    DEVELOPED_BY, PLAYED_BY = STEPS[stage]  # noqa: N806 - the module's names, per stage
    versions = [_version(store, state, ref, number, check, repo)
                for number, ref in enumerate(_reports(state, PLAYED_BY), 1)]
    greybox = state.steps.get(DEVELOPED_BY)
    played = state.steps.get(PLAYED_BY)
    first = versions[0] if versions else None
    last = versions[-1] if len(versions) > 1 else None
    if stage == "develop" and len(versions) > 1:
        # The report of the visit that repaired it: later develop visits (another
        # specialist's) may be played again after it.
        last = next((v for v in versions[1:]
                     if (v["developer"] or {}).get("status") == "repaired"), last)
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
    ledger = None
    if stage == "develop":
        ledger = ledger_view(store, state, check, before_commit=first and first["commit"],
                             after_commit=last and last["commit"])
        reasons.extend("ledger: " + r for r in ledger["reasons"])

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

    extra = {}
    if stage is not None:
        extra = {"stage": stage, "steps": {"developed_by": DEVELOPED_BY, "played_by": PLAYED_BY},
                 "route_visits": {DEVELOPED_BY: dict(greybox.route_visits) if greybox else {}}}
    if ledger is not None:
        extra["ledger"] = ledger
        extra["assessment"] = ledger.pop("assessment")
    return {
        **extra,
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


def control_held(loop_record):
    """(held, reasons) for a negative control's record: it held only when the record has
    versions and every one FAILs, with the defect's check FAIL on every project, on a commit
    whose developer record says `planted`. `closed: false` alone is not enough - a record
    that could not be read is `closed: false` too, and must never count as the control."""
    reasons = []
    versions = (loop_record or {}).get("versions") or []
    if not versions:
        reasons.append("the record has no playability report: nothing shows the defect "
                       "failing - " + "; ".join((loop_record or {}).get("reasons") or []))
    for version in versions:
        label = f"report v{version.get('version')} ({(version.get('commit') or '')[:12]})"
        if version.get("verdict") != "FAIL":
            reasons.append(f"{label} is {version.get('verdict')}, not FAIL")
        statuses = version.get("check_status") or {}
        if any(statuses.get(p) != "FAIL" for p in PROJECTS):
            reasons.append(f"{label}: the check is not FAIL on every project: {statuses}")
        if ((version.get("developer") or {}).get("status")) != "planted":
            reasons.append(f"{label}: the developer record is not `planted`: "
                           f"{version.get('developer')}")
    if (loop_record or {}).get("closed"):
        reasons.append("the record says the loop closed")
    return not reasons, reasons


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

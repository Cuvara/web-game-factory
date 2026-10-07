"""A person's playtest notes against a build, as blocking quality findings.

A person who played a build is the strongest evidence the Factory gets, and until now it
reached a run only as G4's `iterate --findings`: a person who played the current build
outside G4 (the 2026-10-05 playtest that found both games worse than their accepted builds)
had nowhere to put what they saw. `scripts/wgf-playtest.py` files it into a run:

    <run>/playtest/<sha256[:16]>.json     the notes as filed: a list of quality-finding
                                          `request`s (the G4 shape), or {"findings": [...],
                                          "measures": {"<id>": "<metric id>"}}
    <run>/playtest/notes.jsonl            one line per act, append-only:
        {"kind": "file", "file", "sha256", "build", "filed_at", "filed_by", "note"}
        {"kind": "confirm", "id", "build", "confirmed_at", "confirmed_by", "note"}

`findings(run_dir, rules, candidate_commit, metric_results)` reads them back - refusing a
file that no longer hashes to its line, and any act not filed by a person - and returns each
finding with its status:

    open       it holds the build when its severity is in `playtest.blocking_severities`
    closed     a person confirmed it fixed (`confirm`), or the metric it names (`measures`,
               a core/reference/accepted-baseline.yaml metric id) PASSes on every viewport on
               a build newer than the one it was filed against

A finding never closes because a build is newer: only a re-measurement or a person does it.
"""

import hashlib
import json
import os

__all__ = ["NOTES", "DIRECTORY", "PlaytestError", "read_acts", "findings", "file_notes",
           "confirm", "finding_id"]

DIRECTORY = "playtest"
NOTES = "notes.jsonl"


class PlaytestError(ValueError):
    """The run's playtest notes cannot be trusted or read."""


def finding_id(request_id):
    from wgf_triage.findings import finding_id as make
    return make("baseline-regression-report", f"playtest:{request_id}")


def read_acts(run_dir):
    path = os.path.join(run_dir or "", DIRECTORY, NOTES)
    if not run_dir or not os.path.isfile(path):
        return []
    acts = []
    with open(path, encoding="utf-8") as handle:
        for number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                act = json.loads(line)
            except ValueError as exc:
                raise PlaytestError(f"{path}:{number} is not JSON: {exc}")
            if not isinstance(act, dict):
                raise PlaytestError(f"{path}:{number} is not an object")
            acts.append(act)
    return acts


def _requests(raw):
    data = json.loads(raw.decode("utf-8"))
    if isinstance(data, dict):
        return list(data.get("findings") or []), dict(data.get("measures") or {})
    return list(data or []), {}


def _load_file(run_dir, act):
    relative = str(act.get("file") or "")
    if not relative.startswith(DIRECTORY + "/") or ".." in relative.split("/"):
        raise PlaytestError(f"playtest file {relative!r} is not under {DIRECTORY}/")
    path = os.path.join(run_dir, *relative.split("/"))
    try:
        with open(path, "rb") as handle:
            raw = handle.read()
    except OSError as exc:
        raise PlaytestError(f"playtest notes {relative} cannot be read: {exc}")
    digest = "sha256:" + hashlib.sha256(raw).hexdigest()
    if digest != act.get("sha256"):
        raise PlaytestError(f"playtest notes {relative} no longer hash to what was filed "
                            f"({act.get('sha256')}, now {digest})")
    try:
        return _requests(raw)
    except ValueError as exc:
        raise PlaytestError(f"playtest notes {relative} are not JSON: {exc}")


def _same(a, b):
    return bool(a and b) and (a.startswith(b) or b.startswith(a)) and min(len(a), len(b)) >= 7


def findings(run_dir, rules, candidate_commit, metric_results=()):
    """[{request, id, status, severity, blocking, filed, closed_by}]. Raises PlaytestError."""
    blocking = set((rules or {}).get("blocking_severities") or ("blocker", "major"))
    acts = read_acts(run_dir)
    out, confirmed = {}, {}
    for act in acts:
        if act.get("kind") == "confirm":
            if act.get("confirmed_by") != "human":
                raise PlaytestError(f"a confirmation of {act.get('id')} was not given by a "
                                    "person: only a person closes a person's finding")
            confirmed[act.get("id")] = act
    for act in acts:
        if act.get("kind") != "file":
            continue
        if act.get("filed_by") != "human":
            raise PlaytestError(f"playtest notes {act.get('file')} were not filed by a person")
        requests, measures = _load_file(run_dir, act)
        for index, request in enumerate(requests, 1):
            if not isinstance(request, dict):
                raise PlaytestError(f"playtest notes {act.get('file')}: finding {index} is not "
                                    "an object")
            rid = request.get("id") or f"{str(act.get('sha256'))[7:15]}-{index}"
            fid = finding_id(rid)
            entry = {"id": fid, "request": request, "severity": request.get("severity")
                     or "major", "filed": {"file": act.get("file"), "sha256": act.get("sha256"),
                                           "build": act.get("build"),
                                           "filed_at": act.get("filed_at")},
                     "measures": measures.get(rid) or request.get("measures"),
                     "status": "open", "closed_by": None}
            out[fid] = entry
    for fid, entry in out.items():
        if fid in confirmed:
            act = confirmed[fid]
            entry["status"] = "closed"
            entry["closed_by"] = {"kind": "confirmed", "at": act.get("confirmed_at"),
                                  "build": act.get("build"), "note": act.get("note")}
            continue
        metric = entry.get("measures")
        filed_on = entry["filed"].get("build")
        if metric and candidate_commit and not _same(filed_on, candidate_commit):
            own = [r for r in metric_results or ()
                   if r.get("id") == metric or r.get("metric") == metric]
            if own and all(r.get("status") == "PASS" for r in own):
                entry["status"] = "closed"
                entry["closed_by"] = {"kind": "re-measured", "metric": metric,
                                      "build": candidate_commit}
    for entry in out.values():
        entry["blocking"] = entry["status"] == "open" and entry["severity"] in blocking
    return list(out.values())


def _append(run_dir, act):
    folder = os.path.join(run_dir, DIRECTORY)
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, NOTES), "a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(act, sort_keys=True) + "\n")


def file_notes(run_dir, raw, *, build, filed_at, filed_by, note=None):
    """Store `raw` (the notes file's bytes) in the run and record the act. Returns the act."""
    digest = hashlib.sha256(raw).hexdigest()
    relative = f"{DIRECTORY}/{digest[:16]}.json"
    target = os.path.join(run_dir, *relative.split("/"))
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "wb") as handle:
        handle.write(raw)
    act = {"kind": "file", "file": relative, "sha256": "sha256:" + digest, "build": build,
           "filed_at": filed_at, "filed_by": filed_by, "note": note}
    _append(run_dir, act)
    return act


def confirm(run_dir, fid, *, build, confirmed_at, confirmed_by, note=None):
    act = {"kind": "confirm", "id": fid, "build": build, "confirmed_at": confirmed_at,
           "confirmed_by": confirmed_by, "note": note}
    _append(run_dir, act)
    return act

"""Find the build a person accepted for a title, and the reports that measured it.

    find(title_id, *, store, exclude_run=None, titles_dir=None, config=None)
        the accepted build, or None: {commit, shipped_commit, source, decision, run_id,
        run_dir, reports: {type: {path, artifact_id, content_hash, commit, pinned_by}},
        problems}

Where it is looked for (core/reference/accepted-baseline.yaml `locate`):

    factory.baseline.accepted   {commit, run (optional)}: a person names the accepted build.
                                The reports are those of `run` that describe the commit.
    G4 pass decision-records    every run in the project's run store (artifacts named
                                decision-record-*), and workspace/titles/<id>/decisions/:
                                the newest record of gate G4, decision `pass`, decided by a
                                person (decided_by.mode human), whose title is this one.

The accepted (development) commit is the decision's pinned prototype-report's; the shipped
commit is its qa-report's. A report type the decision pinned is taken by that pin (artifact id
and content hash); another is the newest of its type in the decision's run that describes the
accepted commit (`pinned_by: commit`). A pinned report whose content no longer hashes to the
pin is refused - a problem, never silently replaced.

Reads files only: no git, no process.
"""

import glob
import json
import os

from wgflib.hashing import content_hash

__all__ = ["find", "LocateError"]


class LocateError(ValueError):
    """A baseline is named but cannot be resolved (config naming a run that is not there)."""


def _load(path):
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _state(run_dir):
    return _load(os.path.join(run_dir, "state.json")) or {}


def _entries(run_dir):
    """[(artifact type, entry)] of a run's artifact index (state.json `artifacts`)."""
    out = []
    for _name, versions in (_state(run_dir).get("artifacts") or {}).items():
        for entry in versions or []:
            if isinstance(entry, dict) and entry.get("location"):
                out.append((entry.get("type"), entry))
    return out


def _title_of(record):
    return ((record or {}).get("provenance") or {}).get("title_id")


def _is_acceptance(record, title_id, rules):
    if not isinstance(record, dict):
        return False
    decided = record.get("decided_by") or {}
    return (record.get("gate_id") == rules.get("gate", "G4")
            and record.get("decision") == rules.get("decision", "pass")
            and decided.get("mode") == rules.get("decided_by", "human")
            and _title_of(record) == title_id)


def _decisions(title_id, store, exclude_run, titles_dir, rules):
    """[(decided_at, record, run_dir or None, path)] of every acceptance found."""
    found = []
    if store and os.path.isdir(store):
        for run_dir in sorted(glob.glob(os.path.join(store, "*"))):
            if not os.path.isdir(run_dir) or os.path.basename(run_dir) == exclude_run:
                continue
            for kind, entry in _entries(run_dir):
                if kind != "decision-record":
                    continue
                path = os.path.join(run_dir, entry["location"])
                record = _load(path)
                if _is_acceptance(record, title_id, rules):
                    found.append((str(record.get("decided_at") or ""), record, run_dir, path))
    if titles_dir:
        for path in sorted(glob.glob(os.path.join(titles_dir, title_id, "decisions",
                                                  "*.json"))):
            record = _load(path)
            if _is_acceptance(record, title_id, rules):
                found.append((str(record.get("decided_at") or ""), record, None, path))
    return found


def _by_pin(run_dirs, pin):
    """(path, content) of the artifact `pin` names, whose content hashes to it."""
    for run_dir in run_dirs:
        for kind, entry in _entries(run_dir):
            if kind != pin.get("artifact_type") or \
                    entry.get("content_hash") != pin.get("content_hash"):
                continue
            path = os.path.join(run_dir, entry["location"])
            content = _load(path)
            if content and (content.get("provenance") or {}).get("artifact_id") == \
                    pin.get("artifact_id"):
                return path, content
    return None, None


def _commit_of(kind, report):
    if kind in ("prototype-report", "qa-report", "sdk-report"):
        return (report.get("build_ref") or {}).get("commit_sha")
    if kind == "verification-report":
        return (report.get("commit") or {}).get("sha")
    commit = report.get("commit")
    return commit if isinstance(commit, str) else None


def _same(a, b):
    return bool(a and b) and (a.startswith(b) or b.startswith(a)) and min(len(a), len(b)) >= 7


def _newest_of(run_dir, kind, commit):
    best = None
    for found_kind, entry in _entries(run_dir):
        if found_kind != kind:
            continue
        path = os.path.join(run_dir, entry["location"])
        content = _load(path)
        if content and _same(_commit_of(kind, content), commit):
            seq = entry.get("seq") or 0
            if best is None or seq > best[0]:
                best = (seq, path, content)
    return (best[1], best[2]) if best else (None, None)


def _report_entry(kind, path, content, pinned_by):
    provenance = content.get("provenance") or {}
    return {"artifact_type": kind, "path": path,
            "artifact_id": provenance.get("artifact_id"),
            "content_hash": provenance.get("content_hash"),
            "commit": _commit_of(kind, content), "pinned_by": pinned_by}


def find(title_id, *, store, rules, exclude_run=None, titles_dir=None, config=None):
    """The accepted build of `title_id`, or None. Raises LocateError when a person named one
    (factory.baseline.accepted) that cannot be resolved."""
    named = ((config or {}).get("accepted") or {}) if isinstance(config, dict) else {}
    wanted = list(rules.get("reports") or [])
    problems = []
    if named:
        commit = named.get("commit")
        if not isinstance(commit, str) or len(commit) < 7:
            raise LocateError("factory.baseline.accepted.commit must name the accepted commit")
        run_dir = os.path.join(store, named["run"]) if named.get("run") else None
        if run_dir and not os.path.isdir(run_dir):
            raise LocateError(f"factory.baseline.accepted.run {named['run']} is not in the "
                              f"run store {store}")
        reports = {}
        for kind in wanted:
            path, content = _newest_of(run_dir, kind, commit) if run_dir else (None, None)
            if content:
                reports[kind] = _report_entry(kind, path, content, "commit")
        return {"commit": commit, "shipped_commit": None, "source": "config",
                "decision": None, "run_id": named.get("run"), "run_dir": run_dir,
                "reports": reports, "problems": problems}

    found = _decisions(title_id, store, exclude_run, titles_dir, rules)
    if not found:
        return None
    found.sort(key=lambda item: item[0])
    decided_at, record, run_dir, record_path = found[-1]
    runs = [run_dir] if run_dir else []
    if store and os.path.isdir(store):
        runs += [d for d in sorted(glob.glob(os.path.join(store, "*")))
                 if os.path.isdir(d) and d not in runs
                 and os.path.basename(d) != exclude_run]
    pins = {p.get("artifact_type"): p for p in record.get("subject") or []
            if isinstance(p, dict)}
    pins.update({p.get("artifact_type"): p for p in
                 (record.get("provenance") or {}).get("inputs") or []
                 if isinstance(p, dict) and p.get("artifact_type") not in pins})
    resolved = {}
    for kind in ("prototype-report", "qa-report"):
        if kind in pins:
            path, content = _by_pin(runs, pins[kind])
            if content is not None:
                resolved[kind] = (path, content)
            else:
                problems.append(f"the decision pins {kind} {pins[kind].get('artifact_id')}, "
                                "which no run in the store holds with that content hash")
    proto = (resolved.get("prototype-report") or (None, {}))[1]
    commit = _commit_of("prototype-report", proto) if proto else None
    shipped = _commit_of("qa-report", (resolved.get("qa-report") or (None, {}))[1] or {})
    reports = {}
    for kind in wanted:
        if kind in pins:
            path, content = _by_pin(runs, pins[kind])
            if content is None:
                problems.append(f"the decision pins {kind} {pins[kind].get('artifact_id')}, "
                                "which no run in the store holds with that content hash")
                continue
            if content_hash(content) != pins[kind].get("content_hash"):
                problems.append(f"{kind} {pins[kind].get('artifact_id')} no longer hashes to "
                                "the decision's pin")
                continue
            reports[kind] = _report_entry(kind, path, content, "decision")
        elif commit and run_dir:
            path, content = _newest_of(run_dir, kind, commit)
            if content:
                reports[kind] = _report_entry(kind, path, content, "commit")
    provenance = record.get("provenance") or {}
    return {"commit": commit, "shipped_commit": shipped,
            "source": "run-store" if run_dir else "workspace",
            "decision": {"artifact_id": provenance.get("artifact_id"),
                         "content_hash": provenance.get("content_hash"),
                         "decided_at": decided_at, "decision": record.get("decision"),
                         "decided_by": (record.get("decided_by") or {}).get("mode"),
                         "path": record_path},
            "run_id": os.path.basename(run_dir) if run_dir else None, "run_dir": run_dir,
            "reports": reports, "problems": problems}

"""From checks to artifacts: the verification-report, and the qa-report derived from it.

The verification-report is the evidence: every check, its status, what was run and what was
seen. The qa-report is the G5 summary the rest of the workflow reads - suites, blocking
defects, performance - and is computed from the same checks, so the two cannot disagree.
"""

import re

from wgflib.hashing import content_hash

from .model import BLOCKED, FAIL, PASS, STATUSES, WARNING, verdict_of

__all__ = ["build_verification_report", "build_qa_report", "platform_readiness",
           "SCHEMA_VERSION", "ROLE"]

SCHEMA_VERSION = "1.0.0"
ROLE = "qa"
EXTERNAL_APPROVAL_NOTE = ("Local, deterministic checks only. Whether a portal accepts the "
                          "build is decided by its own review, which this report does not "
                          "claim.")

# check id (or prefix) -> qa-report suite name
SUITES = (
    ("code.lint", "lint"),
    ("code.typecheck", "typecheck"),
    ("code.unit", "unit"),
    ("code.integration", "integration"),
    ("build.", "build"),
    ("gameplay.", "smoke"),
    ("policy.runtime-facts", "performance"),
    ("policy.assertions:", "platform-validation"),
    ("platform.", "platform-validation"),
)
PERF_ASSERTION = re.compile(r"(fps|time_to_interactive|bundle|size|perf)", re.I)


def _slug(text):
    slug = re.sub(r"[^a-z0-9]+", "-", str(text or "").lower()).strip("-")
    return slug or "untitled"


def provenance(artifact_type, title_id, produced_at, sequence, inputs):
    return {
        "artifact_id": f"wgf:{artifact_type}:{_slug(title_id)}:"
                       f"{produced_at[:10].replace('-', '')}-{min(max(sequence, 1), 99):02d}",
        "artifact_type": artifact_type,
        "schema_version": SCHEMA_VERSION,
        "title_id": title_id,
        "produced_by": {"role": ROLE, "actor": "automation"},
        "produced_at": produced_at,
        "inputs": list(inputs),
        "content_hash": "",
        "status": "draft",
    }


def _seal(artifact):
    artifact["provenance"]["content_hash"] = content_hash(artifact)
    return artifact


def platform_readiness(session, checks):
    """Per platform: its own checks, plus every required check that is not per-platform."""
    shared = [c for c in checks if c.platform_id is None and c.required]
    readiness = []
    for platform in (session.platforms if session else []):
        pid = platform["id"]
        own = [c for c in checks if c.platform_id == pid]
        relevant = own + shared
        failing = [c.id for c in relevant if c.status == FAIL and (c.required or c in own)]
        blocked = [c.id for c in relevant if c.status == BLOCKED and (c.required or c in own)]
        if failing:
            state = "not-ready"
        elif blocked or not own:
            state = "unverified"
        else:
            state = "ready"
        readiness.append({
            "platform_id": pid,
            "profile": str(platform.get("profile") or pid),
            "role": platform.get("role", "required"),
            "readiness": state,
            "checks": [c.id for c in own],
            "blocking_checks": failing + blocked,
            "warnings": [c.id for c in own if c.status == WARNING],
            "external_approval": "not-claimed",
            "note": EXTERNAL_APPROVAL_NOTE,
        })
    return readiness


def build_verification_report(*, title_id, checks, session, pinned, produced_at, sequence,
                              release_id=None):
    counts = {status: sum(c.status == status for c in checks) for status in STATUSES}
    artifact = session.build_artifact if session else None
    report = {
        "provenance": provenance("verification-report", title_id, produced_at, sequence, pinned),
        "title_id": title_id,
        "commit": {
            "sha": session.commit if session else None,
            "dirty": session.dirty if session else None,
        },
        "build_artifact": ({"status": "built", **artifact} if artifact
                           else {"status": "not-built"}),
        "gameplay_driver": ((session.gameplay_driver if session else None)
                            or {"id": "none", "note": "no browser run: see gameplay checks"}),
        "checks": [c.to_dict() for c in checks],
        "summary": {"total": len(checks), **counts},
        "failed_checks": [c.id for c in checks if c.status == FAIL],
        "blocked_checks": [c.id for c in checks if c.status == BLOCKED],
        "warning_checks": [c.id for c in checks if c.status == WARNING],
        "platform_readiness": platform_readiness(session, checks),
        "verdict": verdict_of(checks),
    }
    if release_id:
        report["release_id"] = release_id
    if session and session.root:
        report["commit"]["repository"] = session.root
    return _seal(report)


def _suites(checks, session):
    suites = {}
    for check in checks:
        name = next((suite for prefix, suite in SUITES if check.id == prefix
                     or (prefix.endswith((".", ":")) and check.id.startswith(prefix))), None)
        if name is None:
            continue
        entry = suites.setdefault(name, {"name": name, "passed": 0, "failed": 0, "skipped": 0})
        if check.counts:
            for key in ("passed", "failed", "skipped"):
                entry[key] += check.counts.get(key, 0)
        elif check.status in (PASS, WARNING):
            entry["passed"] += 1
        elif check.status == FAIL:
            entry["failed"] += 1
        else:
            entry["skipped"] += 1
    counts = getattr(getattr(session, "gameplay", None), "counts", None)
    if counts:
        suites["e2e"] = {"name": "e2e", **{k: counts.get(k, 0) for k in
                                           ("passed", "failed", "skipped")}}
    if not suites:
        suites["build"] = {"name": "build", "passed": 0, "failed": 0,
                           "skipped": sum(c.status == BLOCKED for c in checks) or 1}
    return list(suites.values())


def _defects(checks):
    defects = []
    for check in checks:
        if not check.blocking:
            continue
        repro = next((e.command for e in check.evidence if e.command), None)
        repro = (f"Run `{repro}` in the game repository at the verified commit."
                 if repro else f"Re-run the {check.id} verification check: "
                               + "; ".join(e.summary for e in check.evidence[:3]))
        defects.append({
            "id": "vr-" + re.sub(r"[^a-z0-9-]+", "-", check.id),
            "severity": "blocker" if check.status == FAIL else "critical",
            "summary": f"{check.title}: {check.status} - {check.message}"[:500],
            "repro": repro,
            **({"platform_id": check.platform_id} if check.platform_id else {}),
        })
    return defects


def _perf_results(session):
    facts = (getattr(session, "runtime_facts", None) or {}).get("package") or {}
    perf = facts.get("perf") or {}
    if not perf:
        return [{"device_class": "not-measured", "fps": 0, "within_budget": False,
                 "note": "runtime facts were not measured, so no budget can be said to hold"}]
    breached = [r["criterion_id"] for results in session.assertions.values() for r in results
                if r.get("breached") and r.get("severity") == "blocking"
                and PERF_ASSERTION.search(r.get("criterion_id", ""))]
    result = {
        "device_class": "lowend-android-proxy",
        "fps": perf.get("lowend_android_fps", 0),
        "within_budget": not breached,
        "note": "CPU-throttled desktop proxy, not a device measurement"
                + (f"; breached: {', '.join(breached)}" if breached else ""),
    }
    if "time_to_interactive_s" in perf:
        result["time_to_interactive_s"] = perf["time_to_interactive_s"]
    if isinstance(facts.get("size_mb"), (int, float)):
        result["bundle_mb"] = facts["size_mb"]
    elif session.build_artifact:
        result["bundle_mb"] = round(session.build_artifact["bytes"] / 1024 / 1024, 3)
    return [result]


def build_qa_report(*, title_id, release_id, checks, session, verification, produced_at,
                    sequence, pinned):
    defects = _defects(checks)
    perf = _perf_results(session)
    commit = (session.commit if session else None) or "unknown"
    build_ref = {"commit_sha": commit}
    if session and session.build_artifact:
        build_ref["artifact_hash"] = session.build_artifact["content_hash"]

    pins = list(pinned) + [{
        "artifact_id": verification["provenance"]["artifact_id"],
        "artifact_type": "verification-report",
        "content_hash": verification["provenance"]["content_hash"],
    }]
    qa = {
        "provenance": provenance("qa-report", title_id, produced_at, sequence, pins),
        "title_id": title_id,
        "release_id": release_id,
        "build_ref": build_ref,
        "suites": _suites(checks, session),
        "blocking_defects": defects,
        "perf_results": perf,
        "verdict": "pass" if not defects and all(p["within_budget"] for p in perf) else "fail",
    }
    seen = getattr(session, "gameplay", None)
    if seen is not None and seen.browsers:
        qa["browser_matrix"] = [
            {k: b[k] for k in ("browser", "platform", "result", "note") if k in b}
            for b in seen.browsers]
    platform_checks = []
    for entry in verification["platform_readiness"]:
        result = {"ready": "pass", "not-ready": "fail"}.get(entry["readiness"], "not-tested")
        platform_checks.append({"platform_id": entry["platform_id"], "result": result,
                                "checks": entry["checks"], "note": entry["note"]})
    if platform_checks:
        qa["platform_checks"] = platform_checks
    return _seal(qa)

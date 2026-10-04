"""The run's finding ledger: every finding's lifecycle, closed only on a re-measurement.

    detected -> classified -> assigned -> implemented -> verified -> closed

Each triage-report carries the whole ledger (`lifecycle`) forward from the one before it, so
the newest is the run's ledger and a finding survives every visit. `advance` moves it on
from what this triage can see - never from what a specialist says it did:

    implemented  the prototype-report's `specialist` block lists the finding: the owner's
                 visit built a change for it (the visit's commit and run-local seq); or a
                 gate routed it straight to a step that makes its artifact again
                 (production-quality's and visual-qa's `assets`), and that step has run
                 since the report (`handed`: the asset-manifest is the fix)
    verified     the producer that raised it has a report newer than that visit, the report
                 no longer fails the finding's id, and nothing that was passing before the
                 fix fails on a build at or after it (a regression keeps it `implemented`,
                 `verification.verdict: regressed`, the regressions named)
    closed       verified, and every gate the run holds a report of has measured a build at
                 or after the fix
    verified     also with no recorded fix: the raising producer measured a newer build than
    (no fix)     the one it was detected on, and no longer fails it (its group was still
                 pending, or another visit's change fixed it); the history says no fix was
                 recorded. A person's G4 finding is verified so by a later G4 decision that
                 does not send it back again
    reopened     a raising producer still fails it after the fix, or fails a verified or
                 closed finding again: back to `classified`, said so in its history

A G4 finding is re-measured by the person: the next G4 decision after the fix verifies it,
unless that decision is `iterate` naming the same finding again.

`detected` and `classified` happen when a finding is first normalized (findings.py reads the
producer; the routing data classifies it), `assigned` when a triage selects its group.
"""

__all__ = ["advance", "unresolved", "OPEN", "DONE"]

OPEN = ("detected", "classified", "assigned", "implemented")
DONE = ("verified", "closed")


def unresolved(lifecycle, severities, producers=None):
    """The ledger's records of a severity in `severities` that are still OPEN - neither
    verified nor closed - optionally only those raised by one of `producers`."""
    return [r for r in lifecycle or [] if isinstance(r, dict)
            and r.get("status") in OPEN and r.get("severity") in severities
            and (producers is None or (r.get("source") or {}).get("producer") in producers)]


def _event(record, status, at, by=None, build=None, note=None):
    record["status"] = status
    record["history"].append({"status": status, "at": at, "by": by, "build": build,
                              "note": note})


def _new(finding, at, routing_version, seq):
    source = finding.get("source") or {}
    record = {
        "id": finding["id"], "dimension": finding["dimension"],
        "severity": finding["severity"], "owner": finding["owner"],
        "route": finding["route"], "status": "detected",
        "summary": finding.get("summary") or finding["id"], "source": source,
        "build": finding.get("build") or {"commit": None, "digest": None},
        "evidence_refs": list(finding.get("evidence_refs") or []),
        "task": finding.get("task"), "fix": None, "verification": None,
        "detected_seq": seq, "history": []}
    for key, target in (("bar", "expected"), ("measured", "observed")):
        if key in finding:
            record[target] = finding[key]
    _event(record, "detected", at, by=source.get("artifact_id") or source.get("producer"),
           build=record["build"].get("commit"))
    _event(record, "classified", at, by=f"specialist-routing {routing_version}",
           note=f"{finding['dimension']} -> {finding['owner']} ({finding['route']})")
    return record


def _observe(record, finding):
    """The record as last measured: the newest build, value and evidence."""
    record["build"] = finding.get("build") or record.get("build")
    record["severity"] = finding.get("severity") or record["severity"]
    record["summary"] = finding.get("summary") or record["summary"]
    record["source"] = finding.get("source") or record["source"]
    record["evidence_refs"] = list(finding.get("evidence_refs") or [])
    if "bar" in finding:
        record["expected"] = finding["bar"]
    if "measured" in finding:
        record["observed"] = finding["measured"]
    if finding.get("task"):
        record["task"] = finding["task"]


def advance(previous, *, at, current, failing, seqs, reports, proto, proto_seq, decision,
            decision_seq, human_ids, selected, triage_id, routing_version, build_of,
            handed=None):
    """The ledger after this triage.

    previous     the previous triage-report's `lifecycle` (or [])
    current      the findings this triage normalized of the current build (fresh), or []
    failing      {producer: {finding ids its newest report fails}}, for every producer
                 the run holds a report of
    seqs         {producer: run-local seq of its newest report}
    reports      {producer: its newest report}
    proto        the newest prototype-report, proto_seq its seq
    decision     the newest decision-record, decision_seq its seq, human_ids the ids of
                 the typed findings it carries
    selected     the group this triage routes (or None)
    build_of     producer -> {"commit", "digest"} of its newest report
    handed       [(finding, {"specialist", "artifact_id", "seq"})]: findings a gate routed
                 straight to a step that has run since (the assets step's asset-manifest),
                 so no triage routed them
    """
    records = {}
    for record in previous or []:
        if isinstance(record, dict) and record.get("id"):
            records[record["id"]] = dict(record, history=list(record.get("history") or []))

    # implemented: the owner's visit, from the prototype-report it produced.
    block = (proto or {}).get("specialist") if isinstance(proto, dict) else None
    proto_id = ((proto or {}).get("provenance") or {}).get("artifact_id")
    commit = ((proto or {}).get("build_ref") or {}).get("commit_sha")
    if isinstance(block, dict):
        for fid in block.get("findings") or []:
            record = records.get(fid)
            if record and record["status"] in ("classified", "assigned") and not (
                    (record.get("fix") or {}).get("prototype_report") == proto_id):
                record["fix"] = {"specialist": block.get("role"), "commit": commit,
                                 "prototype_report": proto_id, "seq": proto_seq}
                _event(record, "implemented", at, by=proto_id, build=commit,
                       note=f"{block.get('role')} visit {(proto or {}).get('iteration')}")

    # verified / still failing / regressed: only the raising producer's re-measurement.
    for record in records.values():
        fix = record.get("fix") or {}
        if record["status"] != "implemented" or fix.get("seq") is None:
            continue
        producer = (record.get("source") or {}).get("producer")
        after = fix["seq"]
        if producer == "decision-record":
            if decision is None or decision_seq <= after:
                continue
            still = decision.get("decision") == "iterate" and record["id"] in human_ids
            measured_by = {"producer": producer,
                           "artifact_id": ((decision.get("provenance") or {})
                                           .get("artifact_id")),
                           "content_hash": None, "build": {"commit": commit, "digest": None},
                           "observed": decision.get("decision")}
        else:
            if producer not in failing or (seqs.get(producer) or -1) <= after:
                continue
            still = record["id"] in failing[producer]
            report = reports.get(producer) or {}
            measured_by = {"producer": producer,
                           "artifact_id": (report.get("provenance") or {}).get("artifact_id"),
                           "content_hash": (report.get("provenance") or {}).get("content_hash"),
                           "build": build_of(producer),
                           "observed": "fails" if still else "passes"}
        measured = sorted(p for p, s in seqs.items() if (s or -1) > after)
        if still:
            record["verification"] = dict(measured_by, verdict="still-failing",
                                          regressions=[], gates_measured=measured)
            _event(record, "classified", at, by=measured_by["artifact_id"],
                   build=measured_by["build"].get("commit"),
                   note="reopened: the raising gate still fails it after the fix")
            record["fix"] = None
            continue
        # A regression: a failure first detected on a build at or after this fix.
        regressions = sorted(
            fid for p, ids in failing.items() if (seqs.get(p) or -1) > after for fid in ids
            if fid != record["id"] and (fid not in records
                                        or (records[fid].get("detected_seq") or -1) > after
                                        or records[fid]["status"] in DONE))
        if regressions:
            record["verification"] = dict(measured_by, verdict="regressed",
                                          regressions=regressions, gates_measured=measured)
            record["history"].append({
                "status": "implemented", "at": at, "by": measured_by["artifact_id"],
                "build": measured_by["build"].get("commit"),
                "note": "not verified: the build carrying the fix fails what passed before: "
                        + ", ".join(regressions[:6])})
            continue
        record["verification"] = dict(measured_by, verdict="passed", regressions=[],
                                      gates_measured=measured)
        _event(record, "verified", at, by=measured_by["artifact_id"],
               build=measured_by["build"].get("commit"),
               note=f"{producer} re-measured a build at or after the fix: no longer fails")

    # verified with no recorded fix: the raising producer measured a newer build than the
    # one it was detected on, and it no longer fails there.
    for record in records.values():
        if record["status"] not in ("detected", "classified", "assigned") or record.get("fix"):
            continue
        producer = (record.get("source") or {}).get("producer")
        detected = record.get("detected_seq")
        if producer == "decision-record":
            raised_by = (record.get("source") or {}).get("artifact_id")
            decided = (decision or {}).get("provenance") or {}
            if decision is None or not raised_by or decided.get("artifact_id") == raised_by \
                    or (decision.get("decision") == "iterate" and record["id"] in human_ids):
                continue
            measured_by = {"producer": producer, "artifact_id": decided.get("artifact_id"),
                           "content_hash": None, "build": {"commit": commit, "digest": None},
                           "observed": decision.get("decision")}
            measured = []
        else:
            if producer not in failing or detected is None \
                    or (seqs.get(producer) or -1) <= detected \
                    or record["id"] in failing[producer]:
                continue
            report = reports.get(producer) or {}
            measured_by = {"producer": producer,
                           "artifact_id": (report.get("provenance") or {}).get("artifact_id"),
                           "content_hash": (report.get("provenance") or {}).get("content_hash"),
                           "build": build_of(producer), "observed": "passes"}
            measured = sorted(p for p, s in seqs.items() if (s or -1) > detected)
        record["verification"] = dict(measured_by, verdict="passed", regressions=[],
                                      gates_measured=measured)
        _event(record, "verified", at, by=measured_by["artifact_id"],
               build=measured_by["build"].get("commit"),
               note=f"{producer} measured a newer build than it was detected on: no longer "
                    f"fails (no fix was recorded for it)")

    # handed: a gate sent these straight to another step, which has run since: recorded,
    # and implemented by that step's artifact, so the gates' re-measurement verifies them.
    for finding, made in handed or []:
        record = records.get(finding["id"])
        if record is None:
            seq = seqs.get((finding.get("source") or {}).get("producer"))
            record = records[finding["id"]] = _new(finding, at, routing_version, seq)
        elif record["status"] in DONE:
            _observe(record, finding)
            record["fix"] = None
            _event(record, "classified", at,
                   by=(finding.get("source") or {}).get("artifact_id"),
                   build=(finding.get("build") or {}).get("commit"),
                   note="reopened: failing again after it was " + record["status"])
        if record["status"] in ("detected", "classified"):
            _event(record, "assigned", at, by=(finding.get("source") or {}).get("artifact_id"),
                   note=f"routed `{finding.get('route')}` straight from "
                        f"{(finding.get('source') or {}).get('step') or 'its gate'}")
        if record["status"] == "assigned" and not (
                (record.get("fix") or {}).get("artifact_id") == made.get("artifact_id")):
            record["fix"] = {"specialist": made.get("specialist"), "commit": None,
                             "prototype_report": None, "artifact_id": made.get("artifact_id"),
                             "seq": made.get("seq")}
            _event(record, "implemented", at, by=made.get("artifact_id"),
                   note=f"made again by the {made.get('specialist')} step")

    # closed: verified, and every gate the run holds has measured the fix's build (with no
    # recorded fix, a newer build than the one it was detected on).
    for record in records.values():
        fix = record.get("fix") or {}
        after = fix.get("seq") if fix else record.get("detected_seq")
        if record["status"] != "verified" or after is None:
            continue
        gates = [p for p in seqs if p != "decision-record"]
        if all((seqs.get(p) or -1) > after for p in gates):
            _event(record, "closed", at, by=triage_id,
                   build=fix.get("commit") or (record.get("build") or {}).get("commit"),
                   note="every gate of the run measured the build carrying the fix: "
                        + ", ".join(sorted(gates)))

    # detected / classified, or re-observed, or reopened.
    for finding in current:
        record = records.get(finding["id"])
        if record is None:
            seq = seqs.get((finding.get("source") or {}).get("producer"))
            records[finding["id"]] = _new(finding, at, routing_version, seq)
            continue
        _observe(record, finding)
        if record["status"] in DONE:
            record["fix"] = None
            _event(record, "classified", at,
                   by=(finding.get("source") or {}).get("artifact_id"),
                   build=(finding.get("build") or {}).get("commit"),
                   note="reopened: failing again after it was " + record["status"])

    # assigned: the group this triage routes.
    for fid in (selected or {}).get("findings") or []:
        record = records.get(fid)
        if record and record["status"] in ("detected", "classified"):
            _event(record, "assigned", at, by=triage_id,
                   note=f"to {(selected or {}).get('owner')} (route "
                        f"{(selected or {}).get('label')})")

    return sorted(records.values(), key=lambda r: (r.get("detected_seq") or 0, r["id"]))

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

A producer that lists its checks one by one (measurement.CHECKED: playability,
production-quality, listing-validation) re-measures a finding only by measuring the SAME check
on the SAME project again (measurement.state). "The newest report does not fail it" is not
enough there, and never verifies:

    unmeasured   the check is listed but measured nothing - BLOCKED, SKIPPED (not
                 applicable), WARNING, or `measured.unmeasured`: the finding stays open,
                 `verification.verdict: unmeasured`
    missing      the report no longer lists the check for that project (removed, or played
                 only on another viewport): stays open, `verification.verdict: missing`,
                 named in its history - a check that disappears is reported, never fixed
    same-build   (playability) the pass was measured on the commit the failure was: a
                 re-play of the same build, not a repair - stays open

A regression of a fix is a failure of a check that was measured passing before it: the
record keeps a `baseline` when it is assigned (or implemented) - per producer, the report
then newest, its commit, the checks it passed (for a producer that lists them) and the
findings it failed. A failure after the fix is a regression only when its check passed in
that baseline, or the finding was verified before; a producer or check that had never
measured before the fix (a gate running for the first time) raises a new finding, not a
regression of the fix. A record with no baseline (a ledger older than triage-report 1.3.0)
keeps the old rule: any failure first detected at or after the fix.

Every history entry an artifact caused names it by id AND by `content_hash` and run-local
`seq` where known: two reports of one producer can share an artifact id (greybox and
develop playability), and the hash and seq say which one it was. A verification keeps
`samples`: every later report of the raising producer that measured the same check passing
again (a single sample of a check known to flip is weak evidence; the count lets a reader
grade it).

A verified finding of such a producer carries both measurements: `verification.before` (the
last report that failed it: commit, status, scenario, bot version, frames - kept on the
record as `failed_measurement`), `verification.after` (the report that passed it) and
`verification.comparison`, which names every way the two differ (another bot version, other
settings, viewport or policy): the comparison is then weaker, and says so.

`detected` and `classified` happen when a finding is first normalized (findings.py reads the
producer; the routing data classifies it), `assigned` when a triage selects its group.
"""

import re

from . import measurement as measurements

__all__ = ["advance", "unresolved", "OPEN", "DONE", "HELD"]

OPEN = ("detected", "classified", "assigned", "implemented")
DONE = ("verified", "closed")
# The verdicts of a re-measurement that measured nothing of the finding: it stays open.
HELD = ("unmeasured", "missing", "same-build")
# The passing re-measurements a verification keeps (the newest).
MAX_SAMPLES = 20
_HELD_NOTE = {
    "unmeasured": "not verified: {producer} lists {check} but measured nothing ({status})",
    "missing": "not verified: {producer} no longer reports {check} - a check that "
               "disappears is not a fix",
    "same-build": "not verified: {producer} passed {check} on the commit it failed on "
                  "({commit}) - a re-play of the same build, not a repair",
}


def unresolved(lifecycle, severities, producers=None):
    """The ledger's records of a severity in `severities` that are still OPEN - neither
    verified nor closed - optionally only those raised by one of `producers`."""
    return [r for r in lifecycle or [] if isinstance(r, dict)
            and r.get("status") in OPEN and r.get("severity") in severities
            and (producers is None or (r.get("source") or {}).get("producer") in producers)]


def _event(record, status, at, by=None, build=None, note=None, content_hash=None, seq=None):
    record["status"] = status
    entry = {"status": status, "at": at, "by": by, "build": build, "note": note}
    if content_hash:
        entry["content_hash"] = content_hash
    if seq is not None:
        entry["seq"] = seq
    record["history"].append(entry)


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
    if finding.get("measurement"):
        record["failed_measurement"] = finding["measurement"]
    _event(record, "detected", at, by=source.get("artifact_id") or source.get("producer"),
           build=record["build"].get("commit"), content_hash=source.get("content_hash"),
           seq=seq)
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
    if finding.get("measurement"):
        record["failed_measurement"] = finding["measurement"]


def _where(record):
    source = record.get("source") or {}
    return (f"{source.get('check')}"
            + (f"@{source.get('project')}" if source.get("project") else ""))


def _before(record):
    """The measurement that last failed the finding: kept on the record, else what the record
    says of it (a ledger older than this rule)."""
    if isinstance(record.get("failed_measurement"), dict):
        return record["failed_measurement"]
    source = record.get("source") or {}
    return {"producer": source.get("producer"), "artifact_id": source.get("artifact_id"),
            "content_hash": source.get("content_hash"),
            "commit": (record.get("build") or {}).get("commit"), "check": source.get("check"),
            "project": source.get("project"), "status": "FAIL", "scenario": None, "frames": []}


def _remeasured(record, producer, report, failing, measured_by, routing=None):
    """For a producer that lists its checks: (kind, after) - what its newest report measured
    of the finding's check (measurement.state), with the measurement; a held kind
    (`unmeasured`, `missing`, `same-build`) verifies nothing. (None, None) for any other
    producer: its rule is the newest report not failing the finding's id."""
    kind = measurements.state(producer, report, record["id"], record.get("source"),
                              failing.get(producer) or set(), routing)
    if kind is None:
        return None, None
    check = measurements.check_of(producer, report, record.get("source"))
    after = measurements.of_check(producer, report, check or {},
                                  commit=(measured_by.get("build") or {}).get("commit"),
                                  artifact_id=measured_by.get("artifact_id"),
                                  content_hash=measured_by.get("content_hash"),
                                  seq=measured_by.get("seq"))
    if check is None:
        after.update(check=(record.get("source") or {}).get("check"),
                     project=(record.get("source") or {}).get("project"))
    if kind == "pass" and producer == "playability-report":
        before = _before(record).get("commit")
        if before and after.get("commit") == before:
            kind = "same-build"
    return kind, after


def _hold(record, kind, measured_by, after, gates_measured, at):
    """The re-measurement measured nothing of the finding: it stays as it is, and says why
    (once per report)."""
    previous = record.get("verification") or {}
    record["verification"] = dict(measured_by, verdict=kind, regressions=[],
                                  gates_measured=gates_measured, observed=after.get("status"),
                                  before=_before(record), after=after)
    if previous.get("verdict") == kind and previous.get("artifact_id") == measured_by.get(
            "artifact_id"):
        return
    source = record.get("source") or {}
    _note(record, at, measured_by, _HELD_NOTE[kind].format(
        producer=source.get("producer"), check=_where(record), status=after.get("status"),
        commit=(after.get("commit") or "")[:12]))


def _note(record, at, measured_by, note):
    """A history entry that keeps the status: what a measurement said of it."""
    entry = {"status": record["status"], "at": at, "by": measured_by.get("artifact_id"),
             "build": (measured_by.get("build") or {}).get("commit"), "note": note}
    if measured_by.get("content_hash"):
        entry["content_hash"] = measured_by["content_hash"]
    if measured_by.get("seq") is not None:
        entry["seq"] = measured_by["seq"]
    record["history"].append(entry)


_PART = re.compile(r"^([^:]+:[^/@]+)(?:/[^@]*)?(@.*)?$")


def _check_key(fid):
    """`<producer>:<check>[@<project>]` of a finding id: a split check's route part left out
    (the check passed means every part of it passed)."""
    found = _PART.match(str(fid))
    return (found.group(1) + (found.group(2) or "")) if found else str(fid)


def _baseline(failing, seqs, reports, build_of, before=None):
    """What the gates had measured: per producer, its newest report (only those older than
    `before`, a run-local seq, when given), its commit, the checks it passed (a producer
    that lists them) and the findings it failed."""
    from .findings import finding_id
    out = {}
    for producer, ids in (failing or {}).items():
        seq = seqs.get(producer)
        if producer == "decision-record" or seq is None or (before is not None
                                                            and seq >= before):
            continue
        report = reports.get(producer) or {}
        provenance = report.get("provenance") or {}
        entry = {"artifact_id": provenance.get("artifact_id"),
                 "content_hash": provenance.get("content_hash"), "seq": seq,
                 "commit": (build_of(producer) or {}).get("commit"),
                 "failing": sorted(ids)}
        if producer in measurements.CHECKED:
            entry["passing"] = sorted({
                finding_id(producer, c.get("id"), measurements.project_of(producer, c))
                for c in report.get("checks") or []
                if isinstance(c, dict) and c.get("status") == "PASS"
                and not (isinstance(c.get("measured"), dict) and c["measured"].get("unmeasured"))})
        out[producer] = entry
    return out


def _regressed(fid, producer, record, records, after):
    """Whether `fid`, failing on a build at or after the fix, is a regression of it: its
    check passed before the fix (the record's baseline), or it was verified before. A
    failure the ledger already held before the fix is not one; nor is one of a producer or
    check that had never measured before the fix."""
    if fid == record["id"]:
        return False
    known = records.get(fid)
    if known is not None and known.get("status") in DONE:
        return True
    if known is not None and (known.get("detected_seq") or -1) <= after:
        return False
    baseline = record.get("baseline")
    if not isinstance(baseline, dict):
        return True  # a ledger older than the baseline: the old rule
    seen = baseline.get(producer)
    if not isinstance(seen, dict):
        return False  # the producer had not measured before the fix: a new finding
    if producer in measurements.CHECKED:
        return _check_key(fid) in set(seen.get("passing") or ())
    return fid not in set(seen.get("failing") or ())


def _sample(measured_by, status="PASS"):
    return {"artifact_id": measured_by.get("artifact_id"),
            "content_hash": measured_by.get("content_hash"), "seq": measured_by.get("seq"),
            "commit": (measured_by.get("build") or {}).get("commit"), "status": status}


def _evidence(record, after):
    """verification's before/after pair and how they compare."""
    before = _before(record)
    return {"before": before, "after": after,
            "comparison": measurements.compare(before, after)}


def advance(previous, *, at, current, failing, seqs, reports, proto, proto_seq, decision,
            decision_seq, human_ids, selected, triage_id, routing_version, build_of,
            handed=None, routing=None):
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
    routing      the routing.Routing whose split rules re-split a check (measurement.state);
                 the shipped data when None
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
                if "baseline" not in record:
                    record["baseline"] = _baseline(failing, seqs, reports, build_of,
                                                   before=proto_seq)
                _event(record, "implemented", at, by=proto_id, build=commit,
                       note=f"{block.get('role')} visit {(proto or {}).get('iteration')}",
                       content_hash=((proto or {}).get("provenance") or {}).get("content_hash"),
                       seq=proto_seq)

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
                           "observed": decision.get("decision"), "seq": decision_seq}
        else:
            if producer not in failing or (seqs.get(producer) or -1) <= after:
                continue
            still = record["id"] in failing[producer]
            report = reports.get(producer) or {}
            measured_by = {"producer": producer,
                           "artifact_id": (report.get("provenance") or {}).get("artifact_id"),
                           "content_hash": (report.get("provenance") or {}).get("content_hash"),
                           "build": build_of(producer),
                           "observed": "fails" if still else "passes",
                           "seq": seqs.get(producer)}
        measured = sorted(p for p, s in seqs.items() if (s or -1) > after)
        kind, remeasured = (None, None) if producer == "decision-record" else _remeasured(
            record, producer, reports.get(producer), failing, measured_by, routing)
        if kind == "fail" and not still:
            still = True
            measured_by["observed"] = "fails"
        if kind in HELD:
            _hold(record, kind, measured_by, remeasured, measured, at)
            continue
        if still:
            if remeasured is not None:
                record["failed_measurement"] = remeasured
            record["verification"] = dict(measured_by, verdict="still-failing",
                                          regressions=[], gates_measured=measured)
            _event(record, "classified", at, by=measured_by["artifact_id"],
                   build=measured_by["build"].get("commit"),
                   note="reopened: the raising gate still fails it after the fix",
                   content_hash=measured_by.get("content_hash"), seq=measured_by.get("seq"))
            record["fix"] = None
            continue
        # A regression: a check measured passing before this fix fails at or after it.
        regressions = sorted(
            fid for p, ids in failing.items() if (seqs.get(p) or -1) > after for fid in ids
            if _regressed(fid, p, record, records, after))
        if regressions:
            record["verification"] = dict(measured_by, verdict="regressed",
                                          regressions=regressions, gates_measured=measured,
                                          **(_evidence(record, remeasured) if remeasured
                                             else {}))
            _note(record, at, measured_by,
                  "not verified: the build carrying the fix fails what passed before: "
                  + ", ".join(regressions[:6]))
            continue
        record["verification"] = dict(measured_by, verdict="passed", regressions=[],
                                      gates_measured=measured, samples=[_sample(measured_by)],
                                      **(_evidence(record, remeasured) if remeasured else {}))
        _event(record, "verified", at, by=measured_by["artifact_id"],
               build=measured_by["build"].get("commit"),
               note=f"{producer} re-measured a build at or after the fix: no longer fails"
                    + (f" ({record['verification']['comparison']['note']})"
                       if remeasured else ""),
               content_hash=measured_by.get("content_hash"), seq=measured_by.get("seq"))

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
                           "observed": decision.get("decision"), "seq": decision_seq}
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
                           "build": build_of(producer), "observed": "passes",
                           "seq": seqs.get(producer)}
            measured = sorted(p for p, s in seqs.items() if (s or -1) > detected)
        remeasured = None
        if producer != "decision-record":
            kind, remeasured = _remeasured(record, producer, reports.get(producer), failing,
                                           measured_by, routing)
            if kind == "fail":
                continue  # the whole check still fails, in a report that is not failing
            if kind in HELD:
                _hold(record, kind, measured_by, remeasured, measured, at)
                continue
        record["verification"] = dict(measured_by, verdict="passed", regressions=[],
                                      gates_measured=measured, samples=[_sample(measured_by)],
                                      **(_evidence(record, remeasured) if remeasured else {}))
        _event(record, "verified", at, by=measured_by["artifact_id"],
               build=measured_by["build"].get("commit"),
               note=f"{producer} measured a newer build than it was detected on: no longer "
                    f"fails (no fix was recorded for it)"
                    + (f" ({record['verification']['comparison']['note']})"
                       if remeasured else ""),
               content_hash=measured_by.get("content_hash"), seq=measured_by.get("seq"))

    # samples: every later report of the raising producer that measures the verified
    # finding's check passing again - how many times the pass was seen, never a status.
    for record in records.values():
        verification = record.get("verification") or {}
        samples = verification.get("samples")
        producer = (record.get("source") or {}).get("producer")
        if record["status"] not in DONE or not isinstance(samples, list) \
                or producer == "decision-record" or producer not in failing:
            continue
        seq = seqs.get(producer)
        last = max((x.get("seq") or -1 for x in samples), default=-1)
        if seq is None or seq <= last or record["id"] in failing[producer]:
            continue
        report = reports.get(producer) or {}
        if measurements.state(producer, report, record["id"], record.get("source"),
                              failing[producer], routing) not in (None, "pass"):
            continue
        provenance = report.get("provenance") or {}
        samples.append(_sample({"artifact_id": provenance.get("artifact_id"),
                                "content_hash": provenance.get("content_hash"), "seq": seq,
                                "build": build_of(producer)}))
        del samples[:-MAX_SAMPLES]

    # reopened: a done finding whose raising producer's newest report - newer than every
    # measurement the record holds - fails it again. Triage reopens it from `current` as
    # well; the quality gate and release advance the ledger with no findings of their own
    # (current=[]), so without this a closed record would sit beside the report failing it.
    for record in records.values():
        producer = (record.get("source") or {}).get("producer")
        if record["status"] not in DONE or producer == "decision-record"                 or producer not in failing or record["id"] not in failing[producer]:
            continue
        verification = record.get("verification") or {}
        held = [verification.get("seq")] + [x.get("seq") for x in
                                            verification.get("samples") or []
                                            if isinstance(x, dict)]
        held += [h.get("seq") for h in record.get("history") or [] if isinstance(h, dict)]
        last = max((x for x in held if isinstance(x, int)), default=-1)
        seq = seqs.get(producer)
        if seq is None or seq <= last:
            continue
        report = reports.get(producer) or {}
        provenance = report.get("provenance") or {}
        record["fix"] = None
        _event(record, "classified", at, by=provenance.get("artifact_id"),
               build=build_of(producer).get("commit"),
               note="reopened: failing again after it was " + record["status"],
               content_hash=provenance.get("content_hash"), seq=seq)

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
            record["baseline"] = _baseline(failing, seqs, reports, build_of)
            _event(record, "assigned", at, by=(finding.get("source") or {}).get("artifact_id"),
                   note=f"routed `{finding.get('route')}` straight from "
                        f"{(finding.get('source') or {}).get('step') or 'its gate'}",
                   content_hash=(finding.get("source") or {}).get("content_hash"))
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
                   note="reopened: failing again after it was " + record["status"],
                   content_hash=(finding.get("source") or {}).get("content_hash"))

    # assigned: the group this triage routes.
    for fid in (selected or {}).get("findings") or []:
        record = records.get(fid)
        if record and record["status"] in ("detected", "classified"):
            record["baseline"] = _baseline(failing, seqs, reports, build_of)
            _event(record, "assigned", at, by=triage_id,
                   note=f"to {(selected or {}).get('owner')} (route "
                        f"{(selected or {}).get('label')})")

    return sorted(records.values(), key=lambda r: (r.get("detected_seq") or 0, r["id"]))

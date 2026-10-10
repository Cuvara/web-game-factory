"""The run's finding ledger, advanced on the newest reports by any step that sees them.

Triage advances the ledger when it runs (step.py). After the last specialist fix nothing
sends the build back to triage, so the gate that sees every report on the build - the
quality gate - and the release step advance it themselves, with `remeasure`: the same
lifecycle rules (lifecycle.py) on the same evidence, so a finding is verified or closed only
by the raising producer's re-measurement of a newer build, never by a specialist's report.

    previous     the newest ledger in the run: the triage-report's `lifecycle`, or the
                 quality-report's `ledger.lifecycle` when that report is newer
    failing      every newest gate report, normalized (findings.py) when it fails
    decision     the newest decision-record (G4's iterate or pass)

Which findings hold a build back is reference data: specialist-routing.yaml
`ledger.blocking_severities`. Nothing here names a step.
"""

import os

from wgflib import paths
from wgflib.yamllite import load_file

from . import findings as normalizer
from . import lifecycle as lifecycles
from .routing import Routing

__all__ = ["GATE_REPORTS", "LEDGER_INPUTS", "normalize_reports", "previous_lifecycle",
           "remeasure", "blocking", "blocking_severities", "build_of_report", "failing_report"]

# The reports a build is judged by, in the order they are read.
GATE_REPORTS = ("playability-report", "production-quality-report", "visual-qa-report",
                "content-sufficiency-report", "review-report", "qa-report",
                "listing-validation-report", "quality-report")
# What a step that advances the ledger reads besides the gate reports.
LEDGER_INPUTS = ("triage-report", "prototype-report", "decision-record", "game-design",
                 "verification-report")
RUBRIC_PATH = os.path.join(paths.REFERENCE, "visual-qa-rubric.yaml")
_FAILING = {"playability-report": ("FAIL",), "production-quality-report": ("FAIL",),
            "visual-qa-report": ("FAIL",), "content-sufficiency-report": ("FAIL",),
            "review-report": ("request-changes",),
            "qa-report": ("fail",), "listing-validation-report": ("FAIL",),
            "quality-report": ("FAIL",)}


def failing_report(kind, report):
    return isinstance(report, dict) and report.get("verdict") in _FAILING.get(kind, ())


def seq_of(refs, artifact_type):
    ref = (refs or {}).get(artifact_type)
    return (getattr(ref, "seq", None) or 0) if ref is not None else -1


def build_of_report(report, commit, verification):
    """The build a report measured: its own commit (the sdk commit for review of sdk and
    for verification), else the build's; and the bundle digest verification recorded for
    that commit, when it built it."""
    report = report or {}
    measured = (report.get("commit") or report.get("reviewed_commit")
                or (report.get("build_ref") or {}).get("commit_sha")
                or (report.get("build") or {}).get("commit") or commit)
    digest = None
    if isinstance(verification, dict) and measured and \
            (verification.get("commit") or {}).get("sha") == measured:
        digest = (verification.get("build_artifact") or {}).get("content_hash")
    return {"commit": measured, "digest": digest}


def normalize_reports(reports, refs, routing, *, dimension_3d, commit, verification,
                      rubric=None):
    """{kind: [findings]} for every report in `reports` ({kind: report}): its findings when
    it fails, [] when it passes; each finding carries the build its report measured."""
    if rubric is None:
        rubric = load_file(RUBRIC_PATH) if os.path.isfile(RUBRIC_PATH) else {}
    normalized = {}
    for kind, report in reports.items():
        if report is None:
            continue
        normalized[kind] = (normalizer.normalize(
            kind, report, routing, ref=(refs or {}).get(kind), dimension_3d=dimension_3d,
            playability=reports.get("playability-report"), rubric=rubric)
            if failing_report(kind, report) else [])
        for finding in normalized[kind]:
            finding["build"] = build_of_report(report, commit, verification)
    return normalized


def previous_lifecycle(refs, load):
    """The newest ledger in the run: the triage-report's, or the quality-report's when that
    report is newer and carries one."""
    triage = load("triage-report") if "triage-report" in (refs or {}) else None
    quality = load("quality-report") if "quality-report" in (refs or {}) else None
    own = ((quality or {}).get("ledger") or {}).get("lifecycle") \
        if isinstance(quality, dict) else None
    if own is not None and seq_of(refs, "quality-report") > seq_of(refs, "triage-report"):
        return own
    return (triage or {}).get("lifecycle") or [] if isinstance(triage, dict) else []


def blocking_severities(routing):
    """specialist-routing.yaml `ledger.blocking_severities`: the severities of a finding that
    holds a build back until it is verified."""
    ledger = (routing.data or {}).get("ledger") or {}
    return tuple(ledger.get("blocking_severities") or ())


def blocking(lifecycle, routing, producers=None):
    """The ledger's records that hold the build back: of a blocking severity, still open."""
    return lifecycles.unresolved(lifecycle, blocking_severities(routing), producers)


def _human_ids(decision, run_dir):
    """The ids of the typed findings an iterate decision names (None when they cannot be
    read: every finding of a person stays as it is)."""
    from .step import read_typed_findings
    try:
        requests = read_typed_findings((decision or {}).get("rationale"), run_dir)
    except ValueError:
        return None
    return {normalizer.finding_id("decision-record", r.get("id") or f"g4-{n}")
            for n, r in enumerate(requests, 1)}


def remeasure(refs, load, *, at, by, routing=None, run_dir=None, current=None):
    """The run's ledger advanced on the newest reports: [records].

    `refs` are the newest artifact refs per type (each with its run-local `seq`), `load`
    reads one by type. `current` ({kind: (report, seq)}) is a report the caller is producing
    now - the quality gate's own - read as the newest of its kind. Nothing new is detected
    here: only triage detects and assigns; this verifies, regresses, reopens and closes."""
    routing = routing or Routing.load()
    refs = dict(refs or {})
    loaded = {}

    def get(kind):
        if kind not in loaded:
            loaded[kind] = load(kind) if kind in refs else None
        return loaded[kind]

    design = get("game-design") or {}
    dimension_3d = (design.get("engine") or {}).get("dimension") == "3d"
    proto = get("prototype-report")
    commit = ((proto or {}).get("build_ref") or {}).get("commit_sha")
    verification = get("verification-report")
    reports = {kind: get(kind) for kind in GATE_REPORTS}
    seqs = {kind: seq_of(refs, kind) for kind in GATE_REPORTS if reports.get(kind)}
    previous = previous_lifecycle(refs, get)
    for kind, (report, seq) in (current or {}).items():
        reports[kind], seqs[kind] = report, seq
    reports = {k: v for k, v in reports.items() if isinstance(v, dict)}
    normalized = normalize_reports(reports, refs, routing, dimension_3d=dimension_3d,
                                   commit=commit, verification=verification)
    decision = get("decision-record")
    human = set()
    if isinstance(decision, dict) and decision.get("decision") == "iterate":
        human = _human_ids(decision, run_dir)
        if human is None:  # unreadable: nothing of a person's is verified on it
            human = {r.get("id") for r in previous or [] if isinstance(r, dict)}

    def build_of(kind):
        return build_of_report(reports.get(kind), commit, verification)

    return lifecycles.advance(
        previous, at=at, current=[],
        failing={kind: {f["id"] for f in items} for kind, items in normalized.items()},
        seqs=seqs, reports=reports, proto=proto, proto_seq=seq_of(refs, "prototype-report"),
        decision=decision if isinstance(decision, dict) else None,
        decision_seq=seq_of(refs, "decision-record"), human_ids=human, selected=None,
        triage_id=by, routing_version=routing.version, build_of=build_of, routing=routing)

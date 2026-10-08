"""The quality-gate step: one build, every quality dimension, held to the Factory's floor.

    playability-report, production-quality-report, visual-qa-report,
    content-sufficiency-report, qa-report, verification-report, prototype-report,
    game-design [+ sdk-report, review-report, asset-manifest, title-strategy,
    listing-validation-report, triage-report, decision-record]
      -> the build: the verified commit, the development commit it sits on, the bundle digest
      -> every report checked to be about that build (stale evidence BLOCKS)
      -> the contract: core/reference/quality-floor.yaml (universal floor, genre family or its
         nearest ancestor, 3D), the bars of core/reference/quality-benchmark.yaml and the
         visual-qa rubric - the copies the run pinned when it started
      -> scoring.score: every criterion, every dimension against its floor, typed findings
         with their lifecycle against the run's previous quality-report, regression, the
         scorecard (one line per discipline, the hard blockers listed on their own) and the
         release decision
      -> the gates the run's workflow lacks that the Factory now requires before this one
         (`context.missing_gates`, an old run resumed): named, and never a release
      -> the lesson candidates specialist visits reported (prototype-report
         `specialist.lesson_candidates`, triage-report `lesson_candidates`): surfaced to the
         person deciding G4, who promotes one to core/reference/lessons.yaml or not
      -> the run's finding ledger (wgf_triage.ledger.remeasure), advanced on every report
         of this build and this report itself: a finding a specialist fixed is verified or
         regressed here, by the producer that raised it, though no triage runs after the
         last fix
      -> quality-report

    PASS      every dimension at or above its floor (the store DEFERRED to the listing), and
              no blocking finding of the ledger raised by a gate is open             SUCCESS
    FAIL      a dimension below its floor                                    FAILED, not
              retryable, routed by the findings that hold it there: design-gap, assets,
              develop (listing once the listing is measured)
    BLOCKED   evidence about another build, a pinned reference edited after the start, or a
              contract that cannot be read; or every dimension holds its floor while a
              blocking finding (specialist-routing.yaml `ledger.blocking_severities`) a gate
              raised is still open on the ledger - nothing has verified it on a newer build

It plays nothing and touches no checkout: it reads what the producing steps recorded about
the same build. A run at tier mvp is a development build: PASS means its floor holds, and the
release decision says `development`, never release.
"""

import datetime

from wgflib import provenance
from wgflib.workflow import ArtifactOutput, StepResult, WorkflowStep
from wgflib.workflow import references as pinned_references
from wgflib.yamllite import YamlError, load as load_yaml

from . import scoring

__all__ = ["QualityGateStep", "REQUIRED_INPUTS", "OPTIONAL_INPUTS", "FLOOR", "BENCHMARK",
           "RUBRIC", "load_contract", "advance_ledger", "missing_gates", "lesson_candidates"]

REQUIRED_INPUTS = ("playability-report", "production-quality-report", "visual-qa-report",
                   "content-sufficiency-report", "qa-report", "verification-report",
                   "prototype-report", "game-design")
OPTIONAL_INPUTS = ("sdk-report", "review-report", "asset-manifest", "title-strategy",
                   "listing-validation-report", "triage-report", "decision-record")
FLOOR = "core/reference/quality-floor.yaml"
BENCHMARK = "core/reference/quality-benchmark.yaml"
RUBRIC = "core/reference/visual-qa-rubric.yaml"


def _utc_now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_contract(environment=None, run_dir=None):
    """(contract, benchmark record) from the run's pinned references (or the live files for a
    run that pinned none). Raises PinError, YamlError or scoring.ContractError."""
    texts, record, pinned = {}, {}, True
    for key, path in (("floor", FLOOR), ("quality_benchmark", BENCHMARK),
                      ("visual_qa_rubric", RUBRIC)):
        text, digest, was_pinned = pinned_references.read(path, environment, run_dir)
        data = load_yaml(text)
        texts[key] = data
        pinned = pinned and was_pinned
        record[key] = {"path": path, "version": str((data or {}).get("version") or "unknown"),
                       "sha256": digest}
    record["pinned"] = pinned
    spec = scoring.contract(texts["floor"], texts["quality_benchmark"],
                            texts["visual_qa_rubric"])
    return spec, record


def advance_ledger(inputs, report, run_dir=None):
    """(the run's finding ledger advanced on this build's reports and `report` - the
    quality-report being produced - as the `ledger` block, the open blocking findings a gate
    raised). Raises wgf_triage.RoutingError when the routing data is unusable."""
    from wgf_triage import ledger as ledgers
    from wgf_triage.routing import Routing
    routing = Routing.load()
    refs = dict(getattr(inputs, "refs", {}) or {})
    newest = max([getattr(r, "seq", None) or 0 for r in refs.values()] or [0]) + 1
    lifecycle = ledgers.remeasure(
        refs, inputs.load, at=report["provenance"]["produced_at"],
        by=report["provenance"]["artifact_id"], routing=routing, run_dir=run_dir,
        current={"quality-report": (report, newest)})
    held = ledgers.blocking(lifecycle, routing, producers=ledgers.GATE_REPORTS)
    waiting = [r for r in ledgers.blocking(lifecycle, routing) if r not in held]
    block = {"blocking_severities": list(ledgers.blocking_severities(routing)),
             "open": [r["id"] for r in held],
             "awaiting": [r["id"] for r in waiting],
             "lifecycle": lifecycle}
    return block, held


def _family_of_node():
    """[(family, node)] for each ancestor of a genre node, nearest first: the families the
    genre models assign to the node's parent, grandparent... (core/reference/genre-models.yaml
    `nodes`, core/reference/research-vocabulary.yaml `parent`)."""
    try:
        from wgf_design.content import _owners, _parents, _slug, load_vocabulary
        from wgflib import genre_models
    except ImportError:
        return None

    def walk(node):
        owners = _owners(genre_models.load())
        parents = _parents(load_vocabulary())
        current = parents.get(_slug(node))
        seen = set()
        while current and current not in seen:
            seen.add(current)
            if current in owners:
                yield owners[current], current
            current = parents.get(current)
    return walk


def _render(design):
    try:
        from wgf_assets.requirements import game_dimension
    except ImportError:
        return None
    try:
        return game_dimension(design)
    except Exception:  # noqa: BLE001 - a design the asset reader cannot read is 2D by default
        return None


def missing_gates(context):
    """[{"step", "stage", "type"}]: the gates the Factory's quality policy requires before this
    step that the run's workflow does not have (an old run resumed under a newer Factory, or a
    workflow from elsewhere) - the engine's `missing_gates`, [] when it says none."""
    gates = getattr(context, "missing_gates", None)
    if not isinstance(gates, (list, tuple)):
        return []
    out = []
    for gate in gates:
        if isinstance(gate, dict) and gate.get("step"):
            out.append({"step": str(gate["step"]), "stage": gate.get("stage"),
                        "type": gate.get("type")})
        elif isinstance(gate, str):
            out.append({"step": gate, "stage": None, "type": None})
    return out


def lesson_candidates(loaded):
    """The lesson candidates specialist visits reported, deduplicated by summary: the newest
    prototype-report's `specialist.lesson_candidates` and the triage-report's
    `lesson_candidates` (every visit the triage collected). A candidate is surfaced, never
    applied: a person promotes it to core/reference/lessons.yaml with its check and test."""
    found, seen = [], set()
    sources = []
    prototype = loaded.get("prototype-report") or {}
    specialist = prototype.get("specialist") if isinstance(prototype, dict) else None
    if isinstance(specialist, dict):
        sources += [dict(c, role=c.get("role") or specialist.get("role"))
                    for c in specialist.get("lesson_candidates") or [] if isinstance(c, dict)]
    triage = loaded.get("triage-report") or {}
    if isinstance(triage, dict):
        sources += [c for c in triage.get("lesson_candidates") or [] if isinstance(c, dict)]
    for candidate in sources:
        key = " ".join(str(candidate.get("summary") or "").lower().split())
        if not key or key in seen:
            continue
        seen.add(key)
        found.append(candidate)
    return found


class QualityGateStep(WorkflowStep):
    type = "quality-gate"
    clock = staticmethod(_utc_now)

    def execute(self, inputs, context):
        missing = [t for t in REQUIRED_INPUTS if t not in inputs]
        if missing:
            return StepResult.waiting_for_input(
                f"quality-gate needs {', '.join(missing)} in the run: the build has not been "
                "judged on every side yet")
        loaded = {t: inputs.load(t) for t in REQUIRED_INPUTS + OPTIONAL_INPUTS if t in inputs}
        refs = {t: inputs.refs[t] for t in loaded if t in inputs.refs}
        design = loaded["game-design"]
        title_id = design.get("title_id") or (loaded.get("prototype-report") or {}).get("title_id")
        build = scoring.build_identity(loaded)
        tier = scoring.tier_of(design, loaded.get("title-strategy"))
        environment = getattr(context, "environment", None) or {}
        run_dir = getattr(context, "run_dir", None)

        try:
            spec, record = load_contract(environment, run_dir)
        except (pinned_references.PinError, YamlError, scoring.ContractError, OSError) as exc:
            return self._blocked(context, inputs, title_id, build, tier, None, None,
                                 f"the quality contract cannot be read ({exc}): nothing is "
                                 "held to it, and no bar is defaulted in code")
        render = _render(design)
        criteria, summary = scoring.derive(spec, design, render=render,
                                           family_of_node=_family_of_node())
        entries = scoring.evidence(spec, loaded, refs, build)
        stale = [e for e in entries if e["status"] == "stale"]
        if stale:
            return self._blocked(
                context, inputs, title_id, build, tier, record, summary,
                "evidence from another build: " + "; ".join(
                    f"{e['artifact_type']} describes {str(e['commit'])[:12]}, the build's "
                    f"{e['of']} commit is {str(e['expected_commit'])[:12]}" for e in stale)
                + ". Run the producing steps on this build; a score is never computed from "
                  "another build's reports.", entries=entries)
        previous = self._previous(context)
        try:
            result = scoring.score(spec, criteria, loaded, refs, tier, build,
                                   previous=previous, evidence_entries=entries,
                                   render=summary.get("render") or render)
        except scoring.ContractError as exc:
            return self._blocked(context, inputs, title_id, build, tier, record, summary,
                                 f"the quality contract is malformed ({exc})", entries=entries)
        result["missing_gates"] = missing_gates(context)
        result["lesson_candidates"] = lesson_candidates(loaded)
        if result["missing_gates"]:
            names = ", ".join(g["step"] for g in result["missing_gates"])
            decision = result["release_decision"]
            decision["reasons"].insert(0, (
                f"this run's workflow lacks gate(s) the Factory now requires before this one: "
                f"{names} - their evidence does not exist, so this build is never a release; "
                f"start a new run, or a person decides G4 knowing they did not run"))
            if decision["decision"] == "release":
                decision["decision"] = "not-release"
        return self._finish(context, inputs, title_id, build, tier, record, summary, entries,
                            result, previous)

    @staticmethod
    def _previous(context):
        """The quality-report this step produced last in the run, or None."""
        import json
        import os
        run_dir = getattr(context, "run_dir", None)
        for ref in getattr(context, "previous_outputs", None) or []:
            if getattr(ref, "type", None) != "quality-report" or not run_dir:
                continue
            try:
                with open(os.path.join(run_dir, ref.location), encoding="utf-8") as handle:
                    loaded = json.load(handle)
            except (OSError, ValueError):
                return None
            return loaded if isinstance(loaded, dict) else None
        return None

    def _report(self, context, inputs, title_id, build, tier, record, summary, entries,
                result, previous, blocked, seal=True):
        now = self.clock()
        record = record or {key: {"path": path, "version": "unknown",
                                  "sha256": "sha256:" + "0" * 64}
                            for key, path in (("floor", FLOOR),
                                              ("quality_benchmark", BENCHMARK),
                                              ("visual_qa_rubric", RUBRIC))}
        record.setdefault("pinned", False)
        summary = summary or {"universal": 0, "family": None, "genre": None,
                              "resolved_by": "none", "render": None}
        previous_record = None
        if previous:
            previous_record = {
                "artifact_id": (previous.get("provenance") or {}).get("artifact_id"),
                "commit": (previous.get("build") or {}).get("commit"),
                "benchmark_version": ((previous.get("benchmark") or {}).get("floor") or {})
                .get("version")}
        regression = dict((result or {}).get("regression") or
                          {"below_floor": [], "dropped": [], "regressed_criteria": []})
        regression["benchmark_version"] = record["floor"]["version"]
        regression["previous"] = previous_record
        report = {
            "provenance": provenance.build(
                "quality-report",
                artifact_id=provenance.artifact_id("quality-report", title_id, now,
                                                   getattr(context, "execution", 1)),
                produced_by=provenance.producer("qa"), produced_at=now,
                inputs=provenance.pin_inputs(inputs), title_id=title_id),
            "title_id": title_id,
            "build": {"commit": build.get("commit"),
                      "development_commit": build.get("development_commit"),
                      "digest": build.get("digest")},
            "quality_tier": tier if tier in ("mvp", "release") else None,
            "benchmark": record,
            "contract": summary,
            "evidence": entries or [],
            "dimensions": (result or {}).get("dimensions") or [],
            "criteria": (result or {}).get("criteria") or [],
            "findings": (result or {}).get("findings") or [],
            "regression": regression,
            "overall_score": (result or {}).get("overall_score"),
            "release_decision": (result or {}).get("release_decision") or {
                "decision": "not-release", "reasons": [blocked] if blocked else []},
            "failed": (result or {}).get("failed") or [],
            "routes": (result or {}).get("routes") or [],
            "deferred": (result or {}).get("deferred") or [],
            "blocked_reason": blocked,
            "verdict": "BLOCKED" if blocked else (result or {}).get("verdict"),
        }
        for key in ("scorecard", "missing_gates", "lesson_candidates"):
            value = (result or {}).get(key)
            if value:
                report[key] = value
        if blocked and "missing_gates" not in report:
            gates = missing_gates(context)
            if gates:
                report["missing_gates"] = gates
        return provenance.seal(report) if seal else report

    def _blocked(self, context, inputs, title_id, build, tier, record, summary, reason,
                 entries=None):
        report = self._report(context, inputs, title_id, build, tier, record, summary,
                              entries, None, None, reason)
        output = ArtifactOutput("quality-report", report,
                                metadata={"verdict": "BLOCKED", "commit": build.get("commit")})
        context.logger.warning("quality-gate blocked", reason=reason)
        return StepResult("BLOCKED", artifacts=[output], message=reason)

    def _finish(self, context, inputs, title_id, build, tier, record, summary, entries,
                result, previous):
        report = self._report(context, inputs, title_id, build, tier, record, summary,
                              entries, result, previous, None, seal=False)
        try:
            report["ledger"], held = advance_ledger(inputs, report,
                                                    getattr(context, "run_dir", None))
        except Exception as exc:  # noqa: BLE001 - an unreadable ledger never passes a build
            held = None
            reason = (f"the run's finding ledger cannot be advanced ({exc}): no finding can "
                      "be shown verified on this build")
        else:
            reason = None
            if held:
                reason = (f"{len(held)} blocking finding(s) of the run's ledger are still open "
                          "- no re-measurement of a newer build has verified them: "
                          + "; ".join(f"{r['id']} ({r['status']})" for r in held[:6])
                          + ". The producer that raised each must measure it passing on a "
                            "newer build.")
        if reason and report["verdict"] == "PASS":
            report["verdict"] = "BLOCKED"
            report["blocked_reason"] = reason
            report["release_decision"] = {"decision": "not-release", "reasons": [reason]}
            report = provenance.seal(report)
            output = ArtifactOutput("quality-report", report, metadata={
                "verdict": "BLOCKED", "commit": build.get("commit")})
            context.logger.warning("quality-gate blocked", reason=reason)
            return StepResult("BLOCKED", artifacts=[output], message=reason)
        report = provenance.seal(report)
        decision = report["release_decision"]["decision"]
        verdict = report["verdict"]
        output = ArtifactOutput("quality-report", report, metadata={
            "verdict": verdict, "decision": decision, "failed": report["failed"],
            "routes": report["routes"], "commit": build.get("commit"),
            "benchmark": record["floor"]["version"]})
        scores = ", ".join(f"{d['id']} {d['score'] if d['score'] is not None else '-'}"
                           for d in report["dimensions"])
        if verdict == "FAIL":
            route = report["routes"][0]
            context.logger.error("quality below the floor", failed=report["failed"],
                                 route=route)
            reasons = "; ".join(report["release_decision"]["reasons"][:5])
            return StepResult("FAILED", route=route, artifacts=[output], retryable=False,
                              error=f"QUALITY REGRESSION: {', '.join(report['failed'])} below "
                                    f"the floor of quality-floor "
                                    f"{record['floor']['version']} (route {route}): {reasons}")
        return StepResult.success([output], message=(
            f"{str(build.get('commit'))[:12]} holds the quality floor at tier "
            f"{tier or 'none (mvp)'}: decision {decision}; {scores}"))

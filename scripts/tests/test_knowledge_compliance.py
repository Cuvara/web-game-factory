"""Knowledge compliance (scripts/wgf_quality/compliance.py): the quality-report's `compliance`
section holds a build to the rules of its run's knowledge-contract.

  * levels       a blocking or required rule FAILED or UNMEASURED blocks the release; a
                 recommended one is a warning; an experimental one is reported only
  * exceptions   a person's exception is honoured only while it is active, and is always
                 shown; automation's is refused
  * evidence     every check is cited by its producer's artifact id, content hash and commit
  * the gate     the accepted build satisfies every applicable rule and is a release; a
                 regressed one is not-release on the named rules; a run started before the
                 knowledge model gets advisory compliance that never changes its decision; a
                 run that recorded its knowledge but has no contract here is never skipped
  * firewall     positive/negative pairs on the real producers' judgement of real lessons:
                 L11 (a collider larger than the body it draws), L27 (a time-out loss with no
                 sound), L26 (a HUD card over the ball) - replayed on the 2026-10 validation
                 games' own evidence where it exists
  * generalize   a rule learned on game A catches game B: L27 from the 3D game's silent
                 time-out on a synthetic game; a touch-target rule learned on a 2D button at
                 42 px on a 3D HUD
  * rendering    the section for a person (markdown, terminal, G4) says what the JSON says
  * triage       guards from the run's contract with their level; an excepted finding is
                 held, never routed
  * release      the contract and the compliance ship under release/<id>/

    python -m unittest scripts.tests.test_knowledge_compliance
"""

import copy
import datetime
import gzip
import json
import os
import shutil
import sys
import tempfile
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
for _path in (SCRIPTS, HERE):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import test_quality_gate as gate_fixture  # noqa: E402
from browser_qa_fixture import healthy_records  # noqa: E402
from wgf_knowledge import model as knowledge_model  # noqa: E402
from wgf_knowledge import resolve as resolver  # noqa: E402
from wgf_knowledge import versions as knowledge_versions  # noqa: E402
from wgf_playability import realism  # noqa: E402
from wgf_production import checks as production_checks  # noqa: E402
from wgf_quality import compliance, registry  # noqa: E402
from wgf_quality.step import QualityGateStep  # noqa: E402
from wgf_verification import browser_qa  # noqa: E402
from wgflib import gate_evidence, provenance  # noqa: E402
from wgflib.workflow.contracts import ArtifactContracts  # noqa: E402
from wgflib.workflow.model import StepOutcome  # noqa: E402
from wgflib.yamllite import load_file  # noqa: E402

DATA = registry.load(ROOT)
CHECKS, _ = registry.classify(DATA["tiers"], ROOT)
TIERS = DATA["tiers"]
WORKFLOW = load_file(os.path.join(ROOT, "core", "workflows", "new-game.workflow.yaml"))
CLOCK = "2026-10-08T12:00:00Z"
NOW = datetime.datetime(2026, 10, 8, 12, tzinfo=datetime.timezone.utc)
CONTRACT_ID = provenance.artifact_id("knowledge-contract", "demo", CLOCK, 1)
CONTRACT_HASH = "sha256:" + "c" * 64
REAL = os.path.join(HERE, "fixtures", "real", "play-realism")
BQA = os.path.join(HERE, "fixtures", "browser-qa")
BQA_CONTRACT = browser_qa.load_contract()
RULES = realism.load_rules()
RELEASE = realism.strength_for(RULES, "release")
D2 = {"engine": {"dimension": "2d"}}


def digest(name):
    return "sha256:" + format(abs(hash(name)) % (16 ** 12), "012x").rjust(64, "0")


def contract_for(family="arcade", render="2d", platforms=("yandex",), tier="release",
                 lessons=None, checks=None, exceptions=()):
    """The knowledge-contract the knowledge step makes for these facets: the real resolver
    over the Factory's lessons (or `lessons`), check tiers and new-game workflow."""
    facets = resolver.facets(family=family, render=render, platforms=platforms, tier=tier)
    found = knowledge_versions.collect(root=ROOT, workflow=WORKFLOW, platforms=platforms)
    body = resolver.resolve(lessons or DATA["lessons"], checks or CHECKS, TIERS, facets,
                            workflow=WORKFLOW, exceptions=exceptions, now=NOW, versions=found,
                            vocabulary=knowledge_model.vocabulary(ROOT))
    return dict(body, versions=found, title_id="demo",
                provenance={"artifact_id": CONTRACT_ID})


def rule(rule_id, level, *held):
    """A contract rule held by `held`: (check, tier, producer)."""
    return {"id": rule_id, "title": rule_id, "level": level, "category": "gameplay",
            "status": "gap" if level == "experimental" and not held else "enforced",
            "lifecycle": "active",
            "checks": [{"check": c, "tier": t, "source": c.split(":")[0], "producer": p,
                        "steps": []} for c, t, p in held],
            "tests": {"catches": [], "passes": [], "generalizes": []},
            "why_applicable": ["global"]}


def synthetic(*rules, exceptions=()):
    return {"rules": list(rules), "facets": resolver.facets(platforms=["yandex"],
                                                            tier="release"),
            "versions": {}, "regression_suite": [], "not_applicable": [], "experimental": [],
            "exceptions": list(exceptions)}


def play_report(**statuses):
    return {"commit": gate_fixture.DEV, "verdict": "PASS",
            "checks": [{"id": cid.replace("__", "."), "status": status}
                       for cid, status in statuses.items()]}


def exception(rule_id, *, mode="human", created=CLOCK, expires="2026-10-20T00:00:00Z",
              reason="the publisher accepted this for the soft launch, see ticket 41",
              scope=None):
    return {"rule_id": rule_id, "reason": reason, "scope": scope or {},
            "approved_by": {"identifier": "duy", "mode": mode},
            "created_at": created, "expires_at": expires}


def evaluate(contract, reports, tier="release", **kw):
    kw.setdefault("now", NOW)
    kw.setdefault("lessons", DATA["lessons"])
    return compliance.evaluate(contract, TIERS, reports, tier=tier, **kw)


def by_id(section):
    return {r["id"]: r for r in section["rules"]}


# --------------------------------------------------------------------------- a full build


def complete_build(family="arcade"):
    """test_quality_gate's release build, carrying every check the applicable rules name:
    each producer reports every check of its sources, passing."""
    docs = gate_fixture.release_build(family=family)
    docs["game-design"]["engine"] = {"dimension": "2d"}
    play = docs["playability-report"]
    reported = {(c["id"], c.get("project")) for c in play["checks"]}
    for check_id, entry in sorted(CHECKS.items()):
        source, _, name = check_id.partition(":")
        if source not in ("playability", "play-realism"):
            continue
        for project in gate_fixture.VIEWPORTS:
            if (name, project) not in reported:
                play["checks"].append(gate_fixture._check(name, project=project))
    verification = docs["verification-report"]
    verification["checks"] = [{"id": "browser.run", "status": "PASS"}]
    for check_id in sorted(CHECKS):
        source, _, name = check_id.partition(":")
        if source == "browser-qa":
            for viewport in ("desktop-standard", "mobile"):
                verification["checks"].append({"id": f"{name}:{viewport}", "status": "PASS"})
    docs["game-design"]["consistency"] = {
        "status": "pass", "rule_results": [
            {"criterion_id": c.partition(":")[2], "breached": False}
            for c in sorted(CHECKS) if c.startswith("design-consistency:")]}
    for index, (kind, content) in enumerate(sorted(docs.items()), start=1):
        content["provenance"] = {"artifact_id": provenance.artifact_id(kind, "demo", CLOCK,
                                                                       index)}
    return docs


class _Log:
    def __getattr__(self, name):
        return lambda *a, **k: None


def granted(record, decided_by="duy", nonce="resume-1", corroborated=True):
    """The operator events a person's `wgf resume <run> --except ...` records: the grant,
    then the engine's WORKFLOW_RESUMED of the same resume."""
    events = [{"event": compliance.EXCEPTION_EVENT,
               "data": {"decided_by": decided_by, "decided_at": CLOCK,
                        "resume_nonce": nonce, "exception": record}}]
    if corroborated:
        events.append({"event": "WORKFLOW_RESUMED", "data": {"resume_nonce": nonce}})
    return events


def run_gate(test, docs, run_params=None, events=(), hashes=True):
    """The real quality-gate step on `docs`, at a fixed clock; the report schema-checked."""
    base = tempfile.mkdtemp(prefix="wgf-compliance-")
    test.addCleanup(shutil.rmtree, base, ignore_errors=True)

    class Inputs:
        refs = {k: types.SimpleNamespace(
            content_hash=(CONTRACT_HASH if k == "knowledge-contract" else digest(k))
            if hashes else None, seq=0) for k in docs}

        def __contains__(self, k):
            return k in docs

        def load(self, k):
            return docs[k]

    context = types.SimpleNamespace(config={}, run_dir=base, logger=_Log(), visit=1,
                                    attempt=1, execution=1, previous_outputs=[],
                                    environment=run_params or {}, params={},
                                    read_events=lambda: list(events))
    step = QualityGateStep(types.SimpleNamespace(params={}, id="quality-gate"))
    step.clock = staticmethod(lambda: CLOCK)
    result = step.execute(Inputs(), context)
    for artifact in result.artifacts:
        test.assertEqual(ArtifactContracts()("quality-report", artifact.content), [])
    return result, result.artifacts[0].content


# ------------------------------------------------------------------------------- levels


class Levels(unittest.TestCase):
    def test_a_blocking_failure_blocks(self):
        section = evaluate(synthetic(rule("L5", "blocking", (
            "playability:content.units_reachable", "hard", "playability-report"))),
            {"playability-report": play_report(content__units_reachable="FAIL")})
        self.assertEqual(by_id(section)["L5"]["status"], "FAILED")
        self.assertTrue(by_id(section)["L5"]["blocks"])
        self.assertEqual(section["verdict"], "RELEASE_BLOCKED")
        self.assertTrue(section["holds_release"])
        self.assertEqual(section["blocking"], ["L5"])
        self.assertEqual(section["routes"], ["develop"])

    def test_a_required_failure_blocks(self):
        section = evaluate(synthetic(rule("L2", "required", (
            "playability:depth.ramp", "quality", "playability-report"))),
            {"playability-report": play_report(depth__ramp="FAIL")})
        self.assertEqual(section["verdict"], "RELEASE_BLOCKED")
        self.assertEqual(section["blocking"], ["L2"])
        self.assertEqual(section["counts"]["by_level"]["required"]["failed"], 1)

    def test_a_warning_is_never_a_pass(self):
        # What a producer reports without holding it - unmeasured, or not held at this tier.
        section = evaluate(synthetic(rule("L2", "required", (
            "playability:depth.ramp", "quality", "playability-report"))),
            {"playability-report": play_report(depth__ramp="WARNING")})
        check = by_id(section)["L2"]["checks"][0]
        self.assertEqual(check["status"], "UNMEASURED")
        self.assertIn("WARNING", check["note"])
        self.assertTrue(section["holds_release"])

    def test_a_clear_rate_with_no_accepted_build_does_not_concern_a_new_game(self):
        # In its producer's words: a game with no accepted build has no clear rate to fall
        # from. A clear rate unmeasured for any other reason is UNMEASURED.
        contract = synthetic(rule("L23", "required", (
            "play-realism:naive.clear_rate", "quality", "playability-report")))
        report = play_report(naive__clear_rate="WARNING")
        report["checks"][0]["measured"] = {"unmeasured": "no-accepted-build"}
        section = evaluate(contract, {"playability-report": report})
        self.assertEqual(by_id(section)["L23"]["status"], "NOT_APPLICABLE")
        report["checks"][0]["measured"] = {"unmeasured": "not-reported"}
        section = evaluate(contract, {"playability-report": report})
        self.assertEqual(by_id(section)["L23"]["status"], "UNMEASURED")

    def test_recommended_is_a_warning_and_never_blocks(self):
        section = evaluate(synthetic(rule("R1", "recommended", (
            "browser-qa:browser.safe-margins", "advisory", "verification-report"))),
            {"verification-report": {"checks": [
                {"id": "browser.safe-margins:mobile", "status": "FAIL"}]}})
        self.assertEqual(by_id(section)["R1"]["status"], "FAILED")
        self.assertFalse(by_id(section)["R1"]["blocks"])
        self.assertEqual(section["warnings"], ["R1"])
        self.assertEqual(section["verdict"], "PASS")
        self.assertFalse(section["holds_release"])

    def test_experimental_is_reported_only(self):
        section = evaluate(synthetic(
            rule("L8", "experimental"),
            rule("C1", "experimental", ("playability:depth.ramp", "quality",
                                        "playability-report"))),
            {"playability-report": play_report(depth__ramp="FAIL")})
        rules = by_id(section)
        self.assertEqual(rules["L8"]["status"], "NOT_ENFORCED")
        self.assertEqual(rules["C1"]["status"], "FAILED")
        self.assertFalse(rules["C1"]["blocks"])
        self.assertEqual(section["verdict"], "PASS")
        self.assertEqual(section["counts"]["by_level"]["experimental"]["not_enforced"], 1)

    def test_an_unmeasured_blocking_rule_blocks(self):
        contract = synthetic(rule("L5", "blocking", (
            "playability:content.units_reachable", "hard", "playability-report")))
        # The report does not carry the check; and no report at all.
        for reports in ({"playability-report": play_report(start__playable="PASS")}, {}):
            section = evaluate(contract, reports)
            self.assertEqual(by_id(section)["L5"]["status"], "UNMEASURED", reports)
            self.assertEqual(section["verdict"], "RELEASE_BLOCKED")
        # Reported as skipped, blocked or unmeasured: still never a pass.
        for raw in ("SKIPPED", "BLOCKED", "UNMEASURED"):
            section = evaluate(contract, {"playability-report": play_report(
                content__units_reachable=raw)})
            self.assertEqual(by_id(section)["L5"]["status"], "UNMEASURED", raw)
            self.assertIn(raw, by_id(section)["L5"]["checks"][0]["note"])

    def test_stale_evidence_is_unmeasured(self):
        contract = synthetic(rule("L5", "blocking", (
            "playability:content.units_reachable", "hard", "playability-report")))
        entries = [{"artifact_type": "playability-report", "artifact_id": "p", "status": "stale",
                    "commit": "f" * 40, "content_hash": digest("p")}]
        section = evaluate(contract, {"playability-report": play_report(
            content__units_reachable="PASS")}, entries=entries)
        self.assertEqual(by_id(section)["L5"]["status"], "UNMEASURED")
        self.assertIn("another build", by_id(section)["L5"]["checks"][0]["note"])

    def test_a_check_its_producer_reports_only_where_it_applies_is_not_applicable(self):
        # L11's physics checks are reported for a 2D board only; on a 3D build they are not
        # applicable - and the rule's other checks (the review's gate-gaming flags) still hold.
        contract = contract_for(render="3d")
        l11 = next(r for r in contract["rules"] if r["id"] == "L11")
        section = evaluate(dict(contract, rules=[l11]), {
            "playability-report": play_report(start__playable="PASS",
                                              runtime__console_errors="PASS"),
            "review-report": {"reviewed_commit": gate_fixture.SHIP, "verdict": "approve",
                              "blockers": []}})
        statuses = {c["check"]: c["status"] for c in by_id(section)["L11"]["checks"]}
        self.assertEqual(statuses["play-realism:physics.collider_size"], "NOT_APPLICABLE")
        self.assertEqual(statuses["gate-gaming:play-area-change"], "PASS")
        self.assertEqual(by_id(section)["L11"]["status"], "SATISFIED")


# --------------------------------------------------------------------------- exceptions


class Exceptions(unittest.TestCase):
    CONTRACT = synthetic(rule("L7", "required", (
        "playability:start.playable", "hard", "playability-report")))
    FAILING = {"playability-report": play_report(start__playable="FAIL")}

    def test_an_active_exception_is_honoured_and_shown(self):
        section = evaluate(self.CONTRACT, self.FAILING, exceptions=[exception("L7")])
        l7 = by_id(section)["L7"]
        self.assertEqual(l7["status"], "EXCEPTED")
        self.assertEqual(l7["measured_status"], "FAILED")
        self.assertFalse(l7["blocks"])
        self.assertEqual(section["verdict"], "PASS")
        self.assertEqual([(e["rule_id"], e["status"]) for e in section["exceptions"]],
                         [("L7", "honoured")])
        self.assertIn("EXCEPTED", "\n".join(compliance.render_lines(section)))

    def test_an_exception_past_its_expiry_is_not_honoured_and_is_shown(self):
        later = datetime.datetime(2026, 10, 21, tzinfo=datetime.timezone.utc)
        section = evaluate(self.CONTRACT, self.FAILING, exceptions=[exception("L7")],
                           now=later)
        self.assertEqual(by_id(section)["L7"]["status"], "FAILED")
        self.assertEqual(section["verdict"], "RELEASE_BLOCKED")
        self.assertEqual(section["exceptions"][0]["status"], "expired")

    def test_automation_cannot_except_a_rule(self):
        section = evaluate(self.CONTRACT, self.FAILING,
                           exceptions=[exception("L7", mode="automation")])
        self.assertEqual(by_id(section)["L7"]["status"], "FAILED")
        self.assertEqual(section["exceptions"][0]["status"], "refused")
        self.assertTrue(any("unauthorized" in p for p in section["exceptions"][0]["problems"]))

    def test_an_exception_never_covers_more_than_its_scope(self):
        # Scoped to another check of the rule: the failing one is not excepted.
        scoped = exception("L7", scope={"checks": ["playability:win.reachable"]})
        section = evaluate(self.CONTRACT, self.FAILING, exceptions=[scoped])
        self.assertEqual(by_id(section)["L7"]["status"], "FAILED")
        # Scoped to a platform the run targets only in part: refused.
        partial = exception("L7", scope={"platforms": ["y8"]})
        contract = dict(self.CONTRACT, facets=resolver.facets(platforms=["yandex", "y8"]))
        section = evaluate(contract, self.FAILING, exceptions=[partial])
        self.assertEqual(section["exceptions"][0]["status"], "refused")
        self.assertEqual(by_id(section)["L7"]["status"], "FAILED")

    def test_an_exception_of_a_rule_that_never_blocks_is_refused(self):
        contract = synthetic(rule("L8", "experimental"))
        section = evaluate(contract, {}, exceptions=[exception("L8")])
        self.assertEqual(section["exceptions"][0]["status"], "refused")

    def test_a_viewport_scoped_exception_covers_only_those_viewports(self):
        contract = synthetic(rule("L25", "required", (
            "browser-qa:browser.context-menu", "quality", "verification-report")))
        report = {"verification-report": {"checks": [
            {"id": "browser.context-menu:mobile", "status": "FAIL"},
            {"id": "browser.context-menu:desktop-standard", "status": "PASS"}]}}
        mobile = exception("L25", scope={"viewports": ["mobile"]})
        self.assertEqual(by_id(evaluate(contract, report, exceptions=[mobile]))["L25"]["status"],
                         "EXCEPTED")
        report["verification-report"]["checks"][1]["status"] = "FAIL"
        self.assertEqual(by_id(evaluate(contract, report, exceptions=[mobile]))["L25"]["status"],
                         "FAILED")


# ----------------------------------------------------------------------------- the gate


class Gate(unittest.TestCase):
    def with_contract(self, docs, **kw):
        docs = dict(docs)
        docs["knowledge-contract"] = contract_for(**kw)
        return docs

    def test_the_accepted_build_satisfies_every_applicable_rule(self):
        result, report = run_gate(self, self.with_contract(complete_build()))
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
        self.assertEqual(report["release_decision"]["decision"], "release")
        section = report["compliance"]
        self.assertEqual((section["mode"], section["verdict"]), ("enforcing", "PASS"))
        self.assertFalse(section["contract"]["retroactive"])
        self.assertEqual(section["contract"], {"artifact_id": CONTRACT_ID,
                                               "content_hash": CONTRACT_HASH,
                                               "retroactive": False})
        for entry in section["rules"]:
            if entry["level"] in compliance.BLOCKING_LEVELS:
                self.assertIn(entry["status"], ("SATISFIED", "NOT_APPLICABLE"), entry)
        self.assertGreater(section["counts"]["by_level"]["blocking"]["satisfied"], 0)
        self.assertGreater(section["counts"]["by_level"]["required"]["satisfied"], 0)
        self.assertEqual(section["versions"]["lessons"]["version"], "2.0.0")
        self.assertTrue(section["regression"]["suite"])

    def test_every_satisfied_check_cites_its_evidence_by_hash_and_commit(self):
        _, report = run_gate(self, self.with_contract(complete_build()))
        cited = 0
        for entry in report["compliance"]["rules"]:
            for check in entry["checks"]:
                if check["status"] != "PASS":
                    continue
                evidence = check["evidence"]
                self.assertTrue(evidence["artifact_id"] or evidence.get("self"), check)
                if evidence["artifact_type"] in ("game-design", "asset-manifest"):
                    # Not tied to a commit of the build: its currency is unknown, said so.
                    self.assertIsNone(evidence["current"])
                    self.assertIn("currency is unknown", check["note"])
                else:
                    self.assertTrue(evidence["current"])
                if evidence.get("self"):
                    self.assertEqual(evidence["artifact_id"],
                                     report["provenance"]["artifact_id"])
                    continue
                self.assertRegex(evidence["content_hash"], r"^sha256:[0-9a-f]{64}$")
                if evidence["artifact_type"] in ("playability-report", "verification-report",
                                                 "review-report"):
                    self.assertIn(evidence["commit"], (gate_fixture.DEV, gate_fixture.SHIP))
                cited += 1
        self.assertGreater(cited, 20)

    def test_a_regressed_build_is_release_blocked_on_the_named_rules(self):
        docs = complete_build()
        for check in docs["verification-report"]["checks"]:
            if check["id"] == "browser.ui-covers-play:mobile":
                check["status"] = "FAIL"
        result, report = run_gate(self, self.with_contract(docs))
        self.assertEqual(result.outcome, StepOutcome.FAILED)
        self.assertEqual(result.route, "develop")
        self.assertEqual(report["verdict"], "FAIL")
        self.assertEqual(report["release_decision"]["decision"], "not-release")
        self.assertEqual(report["compliance"]["blocking"], ["L26"])
        self.assertTrue(report["release_decision"]["reasons"][0].startswith("KNOWLEDGE"))
        self.assertIn("L26", report["release_decision"]["reasons"][0])
        self.assertIn("KNOWLEDGE", result.error)
        # Release refuses it, naming the rule.
        from wgf_release import lineage
        refs = {"quality-report": types.SimpleNamespace(content_hash=digest("q"))}
        codes = [r.code for r in lineage.quality_refusals(refs, {"quality-report": report})]
        self.assertIn("knowledge-not-satisfied", codes)

    def test_a_required_rules_check_missing_from_its_report_is_unmeasured_and_blocks(self):
        docs = complete_build()
        play = docs["playability-report"]
        play["checks"] = [c for c in play["checks"] if c["id"] != "depth.ramp"]
        result, report = run_gate(self, self.with_contract(docs))
        self.assertEqual(report["release_decision"]["decision"], "not-release")
        l2 = next(r for r in report["compliance"]["rules"] if r["id"] == "L2")
        self.assertEqual(l2["status"], "UNMEASURED")
        self.assertIn("L2", report["compliance"]["blocking"])

    def test_a_pre_knowledge_run_gets_advisory_compliance_that_never_changes_its_decision(self):
        docs = complete_build()
        play = docs["playability-report"]
        play["checks"] = [c for c in play["checks"] if c["id"] != "depth.ramp"]
        result, report = run_gate(self, docs)
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
        self.assertEqual(report["release_decision"]["decision"], "release")
        section = report["compliance"]
        self.assertEqual(section["mode"], "advisory")
        self.assertTrue(section["contract"]["retroactive"])
        self.assertIn("pre-knowledge", section["advisory_reason"])
        self.assertEqual(section["verdict"], "RELEASE_BLOCKED")  # shown, held to nothing
        self.assertFalse(section["holds_release"])
        self.assertIn("L2", section["blocking"])

    def test_a_run_that_recorded_its_knowledge_without_a_contract_here_is_blocked(self):
        params = {"quality": {"tier": "release", "knowledge": {
            "lessons": "lessons@2.0.0", "check-tiers": "check-tiers@1.2.0"}}}
        result, report = run_gate(self, complete_build(), run_params=params)
        self.assertEqual(result.outcome, StepOutcome.FAILED)
        self.assertEqual(report["release_decision"]["decision"], "not-release")
        self.assertIn("no knowledge-contract reaches", report["compliance"]["contract_missing"])
        self.assertTrue(report["compliance"]["holds_release"])

    def test_a_development_build_is_advisory(self):
        docs = gate_fixture.release_build(tier="mvp")
        docs["knowledge-contract"] = contract_for(tier="mvp")
        result, report = run_gate(self, docs)
        self.assertEqual(report["release_decision"]["decision"], "development")
        self.assertEqual(report["compliance"]["mode"], "advisory")
        self.assertFalse(report["compliance"]["holds_release"])
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)

    def test_a_persons_exception_granted_on_the_run_is_honoured_by_the_gate(self):
        docs = complete_build()
        for check in docs["verification-report"]["checks"]:
            if check["id"] == "browser.ui-covers-play:mobile":
                check["status"] = "FAIL"
        result, report = run_gate(self, self.with_contract(docs),
                                  events=granted(exception("L26")))
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
        l26 = next(r for r in report["compliance"]["rules"] if r["id"] == "L26")
        self.assertEqual(l26["status"], "EXCEPTED")
        self.assertEqual(report["compliance"]["exceptions"][0]["status"], "honoured")

    def test_a_forged_exception_event_excepts_nothing(self):
        docs = complete_build()
        for check in docs["verification-report"]["checks"]:
            if check["id"] == "browser.ui-covers-play:mobile":
                check["status"] = "FAIL"
        forged = {
            "automation": granted(exception("L26"), decided_by="automation"),
            "nobody": granted(exception("L26"), decided_by=None),
            "someone else": granted(exception("L26"), decided_by="mallory"),
            "a lone line": granted(exception("L26"), corroborated=False),
            "the old flat shape": [{"event": compliance.EXCEPTION_EVENT,
                                    "exception": exception("L26"), "decided_by": "duy"}],
        }
        for label, events in forged.items():
            with self.subTest(label):
                result, report = run_gate(self, self.with_contract(docs), events=events)
                self.assertEqual(report["release_decision"]["decision"], "not-release")
                entry = report["compliance"]["exceptions"][0]
                self.assertEqual(entry["status"], "refused")
                self.assertTrue(any("unverified" in p or "unauthorized" in p
                                    for p in entry["problems"]), entry)

    def test_a_release_class_run_is_enforced_whatever_tier_its_design_states(self):
        docs = gate_fixture.release_build(tier="mvp")
        docs["knowledge-contract"] = contract_for(tier="mvp")
        params = {"quality": {"tier": "release", "class": "release"}}
        result, report = run_gate(self, docs, run_params=params)
        section = report["compliance"]
        self.assertEqual(section["mode"], "enforcing")
        self.assertTrue(section["holds_release"])  # the mvp fixture lacks most checks
        self.assertEqual(report["release_decision"]["decision"], "not-release")
        # The contract's own tier says release: enforced too.
        docs["knowledge-contract"] = contract_for(tier="release")
        _, report = run_gate(self, docs)
        self.assertEqual(report["compliance"]["mode"], "enforcing")

    def test_release_refuses_a_development_report_in_a_release_class_run(self):
        from wgf_release import lineage
        docs = gate_fixture.release_build(tier="mvp")
        _, report = run_gate(self, docs)
        self.assertEqual(report["release_decision"]["decision"], "development")
        refs = {"quality-report": types.SimpleNamespace(content_hash=digest("q"))}
        codes = [r.code for r in lineage.quality_refusals(refs, {"quality-report": report},
                                                          run_class="release")]
        self.assertIn("quality-development-in-release-run", codes)
        codes = [r.code for r in lineage.quality_refusals(refs, {"quality-report": report},
                                                          run_class="development")]
        self.assertNotIn("quality-development-in-release-run", codes)

    def test_g4_shows_the_compliance(self):
        docs = complete_build()
        docs["playability-report"]["checks"] = [
            c for c in docs["playability-report"]["checks"] if c["id"] != "depth.ramp"]
        _, report = run_gate(self, self.with_contract(docs))
        lines = "\n".join(gate_evidence.render(gate_evidence.summarize(
            {"quality-report": report})))
        self.assertIn("knowledge compliance: RELEASE_BLOCKED (enforcing, holds the release)",
                      lines)
        self.assertIn("! L2 (required) UNMEASURED: playability:depth.ramp", lines)
        self.assertIn("lessons 2.0.0", lines)


# ----------------------------------------------------------------------------- firewall


def realism_report(frames, project_checks=()):
    """A playability-report whose physics checks the real realism judge made of `frames`,
    on both viewports."""
    checks = []
    for project in ("desktop", "mobile"):
        records = {"win": {"sampled": {"frames": frames, "viewport": [1280, 720]}}}
        checks += realism.judge(records, D2, RULES, project, RELEASE)
    return {"commit": gate_fixture.DEV, "verdict": "PASS", "checks": checks + list(project_checks)}


def body_ball(drawn, body, collider):
    """Frames of a ball drawn `drawn` px across (a glow), its opaque body `body` px across
    (None: not reported), colliding `collider` px across."""
    frames = []
    for i in range(5):
        y = 300 - i
        sample = ["ball", "projectile", 1, 600 - drawn / 2, y - drawn / 2, drawn, drawn, "ball",
                  "asset", ["circle", 600 - collider / 2, y - collider / 2, collider, collider],
                  [600 - body / 2, y - body / 2, body, body] if body is not None else None,
                  True if body is not None else None]
        frames.append([sample])
    return frames


def verification(checks):
    return {"commit": {"sha": gate_fixture.SHIP}, "verdict": "PASS",
            "checks": [{"id": "browser.run", "status": "PASS"}] + [c.to_dict() for c in checks]}


def bqa_fixture(name):
    with open(os.path.join(BQA, name), encoding="utf-8") as handle:
        return json.load(handle)


def bqa_judge(records, fixture=None, action_audio=("pause", "launch")):
    fixture = fixture or {}
    return browser_qa.judge(records, BQA_CONTRACT, klass=fixture.get("klass", "release"),
                            action_audio=list(fixture.get("action_audio") or action_audio),
                            bundle=fixture.get("bundle"))


def sound_at_every_loss(records):
    """The fix: a one-shot sound starts the moment each run is lost."""
    records = copy.deepcopy(records)

    def losses(node, out):
        if isinstance(node, dict):
            for move in node.get("transitions") or []:
                if isinstance(move, dict) and move.get("state") == "lost":
                    out.append(move.get("t"))
            for value in node.values():
                losses(value, out)
        elif isinstance(node, list):
            for value in node:
                losses(value, out)
        return out

    for record in records.values():
        times = [t for t in losses(record, []) if isinstance(t, (int, float))]
        for part in record.values():
            runs = ((part or {}).get("watch") or {}).get("runs") if isinstance(part, dict) \
                else None
            for run in (runs or {}).values():
                run.setdefault("sounds", []).extend(
                    {"t": t + 40, "kind": "buffer", "url": None, "loop": False,
                     "duration": 0.6, "context": "running", "loop_now": False} for t in times)
    return records


def uncover(records):
    records = copy.deepcopy(records)
    for record in records.values():
        for frame in (record.get("viewport") or {}).get("cover") or []:
            for entity in frame:
                entity["share"], entity["by"] = 0, None
    return records


def cover_the_ball(records):
    records = copy.deepcopy(records)
    for vid in ("tablet", "mobile"):
        for frame in records[vid]["viewport"]["cover"]:
            for entity in frame:
                if entity.get("role") == "projectile":
                    entity["share"], entity["by"] = 0.9, "div#objective-card"
    return records


def real_rule(rule_id, render="2d"):
    contract = contract_for(render=render)
    return dict(contract, rules=[r for r in contract["rules"] if r["id"] == rule_id])


class RegressionFirewall(unittest.TestCase):
    """Positive/negative pairs: each real lesson's rule FAILS the build that showed it and is
    SATISFIED by the fixed one - judged by the real producers on the same records."""

    def steel_gaps(self, commit, variant, units=("w3-l7", "w4-l7")):
        """The playability-report checks the realism judge makes of the 2D game's steel-gap
        levels at `commit`, with naive.clear_rate of `variant` against the accepted r1
        rates, gated as the step gates them (realism.gate_clearance)."""
        import test_play_realism as pr
        content = pr.real(f"content-2d-{commit}.json")
        content = dict(content, play_geometry={
            "grid": {"key": "rows", "solid": "S",
                     "cell": ["tuning.bricks.brick_width_px", "tuning.bricks.brick_height_px"]},
            "body": {"radius": "tuning.ball-rebound.ball_radius_px"}})
        layout = realism.judge_layouts(content, RULES, RELEASE)
        levels = pr.real("clear-rates-2d-steel-gaps.json")["levels"]
        accepted = {u: levels[u]["r1_ref11"] for u in units}
        runs = [pr.naive_run(model, u, asked=u, won=i < cell["won"])
                for u in units for model, cell in levels[u][variant].items()
                for i in range(cell["n"])]
        rate = [c for c in realism.judge(pr.naive(*runs), D2, RULES, "desktop", RELEASE, (),
                                         {"units": accepted}) if c["id"] == "naive.clear_rate"]
        checks = realism.gate_clearance(layout + rate, RELEASE)
        return {"commit": gate_fixture.DEV, "verdict": "PASS", "checks": checks}

    def test_L23_the_steel_gaps_fix_is_satisfied_and_the_r20_head_fails(self):
        """M1: the fix keeps one-cell steel lanes (level.clearance fails as a proxy) but
        clears them as often as the accepted build, so the producer makes the clearance
        advisory - covered by the clear rate. 894b4b8 clears w4-l7 far less often."""
        contract = real_rule("L23")
        fixed = self.steel_gaps("03f88ad", "fixed")
        clearance = next(c for c in fixed["checks"] if c["id"] == "level.clearance")
        self.assertEqual((clearance["status"], clearance["measured"]["gate"]["w3-l7"]),
                         ("WARNING", "advisory"))
        section = evaluate(contract, {"playability-report": fixed})
        l23 = by_id(section)["L23"]
        self.assertEqual(l23["status"], "SATISFIED", l23)
        held = {c["check"]: c for c in l23["checks"]}
        self.assertIn("advisory", held["play-realism:level.clearance"]["note"])
        self.assertFalse(section["holds_release"])
        head = evaluate(contract, {"playability-report": self.steel_gaps("894b4b8",
                                                                         "main_894b4b8")})
        self.assertEqual(by_id(head)["L23"]["status"], "FAILED")
        self.assertEqual({c["check"]: c["status"] for c in by_id(head)["L23"]["checks"]}[
            "play-realism:naive.clear_rate"], "FAIL")

    def test_a_blocked_playability_report_never_makes_a_realism_rule_not_applicable(self):
        contract = contract_for()
        rules = [r for r in contract["rules"] if r["id"] in ("L13", "L14", "L23")]
        blocked = {"commit": gate_fixture.DEV, "verdict": "BLOCKED", "checks": [],
                   "blocked_reason": "the bot produced no records"}
        read = {"checks": [{"id": "content.data_present", "status": "PASS"}]}
        section = evaluate(dict(contract, rules=rules), {
            "playability-report": blocked, "content-sufficiency-report": read})
        for rule_id in ("L13", "L14", "L23"):
            self.assertEqual(by_id(section)[rule_id]["status"], "UNMEASURED", rule_id)
        self.assertTrue(section["holds_release"])

    def test_L11_cannot_be_switched_off_by_reporting_no_moving_body(self):
        """A 2D design that moves a body: physics reported for nothing is UNMEASURED, so the
        review's flags alone never satisfy L11. A design with no moving body: not
        applicable."""
        l11 = real_rule("L11")
        review = {"reviewed_commit": gate_fixture.SHIP, "verdict": "approve", "blockers": []}
        silent = play_report(runtime__console_errors="PASS", start__playable="PASS")
        moving = {"build_spec": {"assets": [{"id": "ball", "role": "projectile"}]}}
        section = evaluate(l11, {"playability-report": silent, "review-report": review,
                                 "game-design": moving})
        self.assertEqual(by_id(section)["L11"]["status"], "UNMEASURED")
        still = {"build_spec": {"assets": [{"id": "tile", "role": "target"}]}}
        section = evaluate(l11, {"playability-report": silent, "review-report": review,
                                 "game-design": still})
        self.assertEqual(by_id(section)["L11"]["status"], "SATISFIED")

    def test_L11_a_collider_larger_than_its_drawn_body(self):
        contract = real_rule("L11")
        review = {"reviewed_commit": gate_fixture.SHIP, "verdict": "approve", "blockers": []}
        # Drawn as a 30.8 px glow with no body reported, colliding 21.7 px: 1.42 x.
        regressed = evaluate(contract, {"playability-report": realism_report(
            body_ball(30.8, None, 21.7)), "review-report": review})
        l11 = by_id(regressed)["L11"]
        self.assertEqual(l11["status"], "FAILED")
        self.assertEqual({c["check"]: c["status"] for c in l11["checks"]}[
            "play-realism:physics.collider_size"], "FAIL")
        self.assertTrue(regressed["holds_release"])
        # The fix: the probe reports the opaque body, exactly the collider - 1.0 x.
        fixed = evaluate(contract, {"playability-report": realism_report(
            body_ball(30.8, 21.7, 21.7)), "review-report": review})
        self.assertEqual(by_id(fixed)["L11"]["status"], "SATISFIED")
        self.assertEqual(fixed["verdict"], "PASS")

    def test_L11_the_regressed_2d_head_against_the_accepted_build(self):
        """The 2026-10 2D game's own frames: 68a12b7 turns at an undrawn ceiling, 96f5cea does
        not."""
        def report(name, visit):
            with gzip.open(os.path.join(REAL, name), "rb") as handle:
                projects = json.loads(handle.read().decode("utf-8"))["visits"][visit]["projects"]
            checks = []
            for project, record in projects.items():
                checks += [c for c in realism.judge({"win": record}, D2, RULES, project, RELEASE)
                           if c["id"] == "physics.undrawn_collision"]
            return {"commit": gate_fixture.DEV, "verdict": "PASS", "checks": checks}

        held = dict(real_rule("L11"))
        held["rules"] = [dict(held["rules"][0], checks=[
            c for c in held["rules"][0]["checks"]
            if c["check"] == "play-realism:physics.undrawn_collision"])]
        head = evaluate(held, {"playability-report": report("physics-2d-head-run.json.gz",
                                                            "10-1")})
        self.assertEqual(by_id(head)["L11"]["status"], "FAILED")
        accepted = evaluate(held, {"playability-report": report("physics-2d-r1-run.json.gz",
                                                                "17-1")})
        self.assertEqual(by_id(accepted)["L11"]["status"], "SATISFIED")

    def test_L27_a_time_out_loss_with_no_sound(self):
        """The 3D game loses on its clock in silence (its last sound 3.8 s earlier)."""
        fixture = bqa_fixture("sky-marble-c340631.json")
        contract = real_rule("L27", render="3d")
        silent = evaluate(contract, {"verification-report": verification(
            bqa_judge(fixture["records"], fixture))})
        l27 = by_id(silent)["L27"]
        self.assertEqual(l27["status"], "FAILED")
        self.assertEqual([c["check"] for c in l27["checks"] if c["status"] == "FAIL"],
                         ["browser-qa:browser.audio-events"])
        heard = evaluate(contract, {"verification-report": verification(
            bqa_judge(sound_at_every_loss(fixture["records"]), fixture))})
        self.assertEqual(by_id(heard)["L27"]["status"], "SATISFIED")

    def test_L26_a_hud_card_over_the_ball_on_touch_layouts(self):
        """The 2D game's objective card covers the ball on tablet and mobile."""
        fixture = bqa_fixture("brick-breaker-worlds-894b4b8.json")
        contract = real_rule("L26")
        covered = evaluate(contract, {"verification-report": verification(
            bqa_judge(fixture["records"], fixture))})
        l26 = by_id(covered)["L26"]
        self.assertEqual(l26["status"], "FAILED")
        self.assertEqual([c["check"] for c in l26["checks"] if c["status"] == "FAIL"],
                         ["browser-qa:browser.ui-covers-play"])
        clear = evaluate(contract, {"verification-report": verification(
            bqa_judge(uncover(fixture["records"]), fixture))})
        self.assertEqual(by_id(clear)["L26"]["status"], "SATISFIED")


# ------------------------------------------------------------------------- generalization


TOUCH_LESSON = {
    "id": "T1", "title": "A touch control smaller than a fingertip passed every layout check",
    "category": "ui_ux", "problem": "Players missed a 42 px pause button on a phone.",
    "root_cause": "The layout checks measured overlap, not the size of a target.",
    "lesson": "A control a player taps is at least the design's touch target on every side.",
    "scope": "global", "status": "enforced", "lifecycle": "active",
    "introduced": {"version": "2.8.0", "date": "2026-10-08"},
    "checks": ["production-quality:ui.targets"],
    "tests": {"catches": [], "passes": [], "generalizes": []}}


def touch_report(size, state="playing", label="PAUSE"):
    """A production-quality-report whose ui.targets the real check measured on a control of
    `size` px, against a design asking 48 px touch targets."""
    rules = load_file(os.path.join(ROOT, "core", "reference", "production-quality.yaml"))
    design = {"build_spec": {"responsive": {"min_touch_target_px": 48}}}
    tests = {"mobile": {"ui": {state: {"elements": [
        {"tag": "button", "text": label, "box": [300, 20, size, size]}]}}}}
    check = production_checks.ui_targets("mobile", tests, design, rules)
    return {"commit": gate_fixture.DEV, "verdict": "PASS", "checks": [check]}


class Generalization(unittest.TestCase):
    def test_L27_learned_on_the_3d_game_catches_another_game(self):
        """Learned from the 3D game's silent time-out (A); B is another game - the healthy
        synthetic records - that goes silent when it is lost."""
        contract = real_rule("L27")
        b = healthy_records(BQA_CONTRACT)
        self.assertEqual(by_id(evaluate(contract, {"verification-report": verification(
            bqa_judge(b))}))["L27"]["status"], "SATISFIED")
        for record in b.values():
            runs = (((record.get("outcomes") or {}).get("watch") or {}).get("runs") or {})
            if "lose" in runs:
                runs["lose"]["sounds"] = []
        self.assertEqual(by_id(evaluate(contract, {"verification-report": verification(
            bqa_judge(b))}))["L27"]["status"], "FAILED")

    def test_L26_learned_on_the_2d_game_catches_another_game(self):
        contract = real_rule("L26")
        b = healthy_records(BQA_CONTRACT)
        self.assertEqual(by_id(evaluate(contract, {"verification-report": verification(
            bqa_judge(b))}))["L26"]["status"], "SATISFIED")
        self.assertEqual(by_id(evaluate(contract, {"verification-report": verification(
            bqa_judge(cover_the_ball(b)))}))["L26"]["status"], "FAILED")

    def test_a_touch_target_rule_learned_on_a_2d_button_catches_a_3d_hud(self):
        lessons = dict(DATA["lessons"], lessons=[TOUCH_LESSON])
        contract = contract_for(render="3d", lessons=lessons)
        self.assertEqual([(r["id"], r["level"]) for r in contract["rules"]],
                         [("T1", "required")])
        # A, where it was learned: a 2D pause button at 42 px. B: a 3D HUD's boost control.
        for label in ("PAUSE", "BOOST"):
            small = evaluate(contract, {"production-quality-report": touch_report(42,
                                                                                  label=label)})
            self.assertEqual(by_id(small)["T1"]["status"], "FAILED", label)
            self.assertTrue(small["holds_release"])
            fine = evaluate(contract, {"production-quality-report": touch_report(48,
                                                                                 label=label)})
            self.assertEqual(by_id(fine)["T1"]["status"], "SATISFIED", label)


# ----------------------------------------------------------------------------- rendering


class Rendering(unittest.TestCase):
    def section(self):
        contract = contract_for()
        docs = complete_build()
        docs["playability-report"]["checks"] = [
            c for c in docs["playability-report"]["checks"] if c["id"] != "depth.ramp"]
        candidates = [{"summary": "A sound cue the design names is never checked for a "
                                  "time-out", "proposed_check": "browser-qa:browser.audio-events"}]
        return evaluate(contract, docs, exceptions=[exception("L26")], candidates=candidates)

    def test_the_report_counts_by_level_and_lists_exceptions_and_new_lessons(self):
        section = self.section()
        md = compliance.render_markdown(section)
        for heading in ("## Versions", "## Rules by level", "## Every applicable rule",
                        "## Exceptions", "## Not applicable to this run", "## Regression",
                        "## Lessons applied", "## New lesson candidates"):
            self.assertIn(heading, md)
        self.assertIn("lessons 2.0.0", md)
        self.assertIn("L26: **honoured**", md)
        self.assertIn("time-out", md)
        self.assertIn("| L2 | required |", md)
        self.assertIn("**Verdict: RELEASE_BLOCKED** (enforcing)", md)

    def test_report_md_and_json_agree(self):
        section = self.section()
        md = compliance.render_markdown(section)
        for level, row in section["counts"]["by_level"].items():
            self.assertIn(f"| {level} | {row['applicable']} | {row['satisfied']} | "
                          f"{row['failed']} | {row['unmeasured']} | {row['excepted']} | "
                          f"{row['not_applicable']} | {row['not_enforced']} |", md)
        for entry in section["rules"]:
            self.assertIn(f"| {entry['id']} | {entry['level']} |", md)
        for entry in section["not_applicable"]:
            self.assertIn(f"- {entry['id']}: ", md)
        lines = compliance.render_lines(section)
        self.assertEqual(lines[0], f"Knowledge compliance: {section['verdict']} "
                                   f"({section['mode']})")
        summary = compliance.summary(section)
        self.assertEqual(summary["blocking"], section["blocking"])
        json.dumps(section)  # the machine form is plain JSON


class Report(unittest.TestCase):
    """`wgf knowledge report <run>`: the newest quality-report's compliance, for a person."""

    def run_cli(self, report, *argv):
        import contextlib
        import io
        from unittest import mock
        from wgf_knowledge import cli
        ref = types.SimpleNamespace(id="quality-report", version=3)
        state = types.SimpleNamespace(run_id="run-1",
                                      latest_of_type=lambda kind: ref if report else None)
        store = types.SimpleNamespace(load=lambda run: state,
                                      read_artifact=lambda run, r: report)
        fake = lambda **kw: types.SimpleNamespace(store=store)  # noqa: E731
        out, err = io.StringIO(), io.StringIO()
        with mock.patch("wgflib.workflow.api.WorkflowAPI", fake),                 contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(["report", "run-1", *argv])
        return code, out.getvalue(), err.getvalue()

    def test_the_report_renders_and_exits_by_its_verdict(self):
        docs = complete_build()
        docs["playability-report"]["checks"] = [
            c for c in docs["playability-report"]["checks"] if c["id"] != "depth.ramp"]
        _, blocked = run_gate(self, dict(docs, **{"knowledge-contract": contract_for()}))
        code, text, _ = self.run_cli(blocked)
        self.assertEqual(code, 1)
        self.assertIn("Knowledge compliance: RELEASE_BLOCKED (enforcing)", text)
        code, md, _ = self.run_cli(blocked, "--md")
        self.assertIn("# Knowledge compliance", md)
        code, raw, _ = self.run_cli(blocked, "--json")
        self.assertEqual(json.loads(raw)["blocking"], blocked["compliance"]["blocking"])
        _, passed = run_gate(self, dict(complete_build(),
                                        **{"knowledge-contract": contract_for()}))
        self.assertEqual(self.run_cli(passed)[0], 0)
        code, _, err = self.run_cli(None)
        self.assertEqual(code, 2)
        self.assertIn("no quality-report", err)


# -------------------------------------------------------------------------------- triage


class Triage(unittest.TestCase):
    def finding(self, producer, check, project=None):
        return {"id": f"{producer}:{check}", "source": {"producer": producer, "check": check,
                                                        "project": project}}

    def test_triage_guards_from_the_runs_contract_not_the_live_file(self):
        from wgf_triage.step import _guard
        found = [self.finding("playability-report", "physics.collider_size"),
                 self.finding("qa-report", "browser.context-menu:mobile")]
        # The run's contract holds L25 but not L11 (as if L11 did not apply to it).
        contract = contract_for()
        contract["rules"] = [r for r in contract["rules"] if r["id"] != "L11"]
        _guard(found, None, contract)
        self.assertNotIn("guarded_by", found[0])
        self.assertEqual([(g["lesson"], g["level"]) for g in found[1]["guarded_by"]],
                         [("L25", "required")])
        # Without a contract (a pre-knowledge run), the pinned lessons, as before.
        found = [self.finding("playability-report", "physics.collider_size")]
        _guard(found, None, None)
        self.assertEqual(found[0]["guarded_by"][0]["lesson"], "L11")

    def test_an_excepted_finding_is_held_never_routed(self):
        from wgf_triage.step import _excepted, _guard
        contract = contract_for(exceptions=[exception("L25", scope={"viewports": ["mobile"]})])
        self.assertEqual([e["rule_id"] for e in contract["exceptions"]], ["L25"])
        docs = {"knowledge-contract": contract}

        class Inputs:
            refs = {}

            def __contains__(self, k):
                return k in docs

            def load(self, k):
                return docs[k]

        found = [self.finding("qa-report", "browser.context-menu", project="mobile"),
                 self.finding("qa-report", "browser.context-menu", project="tablet")]
        found[1]["id"] += ":tablet"
        _guard(found, None, contract)
        held = _excepted(found, Inputs(), None, now=NOW)
        self.assertEqual([f["id"] for f, _ in held], [found[0]["id"]])
        self.assertEqual(found[0]["excepted"]["rule_id"], "L25")
        self.assertNotIn("excepted", found[1])
        self.assertIn("excepted for this run by duy", held[0][1])

    def test_a_finding_two_rules_hold_is_held_only_when_both_are_excepted(self):
        from wgf_triage.step import _excepted
        contract = contract_for(exceptions=[exception("L24")])
        self.assertEqual([e["rule_id"] for e in contract["exceptions"]], ["L24"])
        docs = {"knowledge-contract": contract}

        class Inputs:
            refs = {}

            def __contains__(self, k):
                return k in docs

            def load(self, k):
                return docs[k]

        def finding():
            return dict(self.finding("qa-report", "browser.console-errors", project="mobile"),
                        guarded_by=[{"lesson": "L24", "check":
                                     "browser-qa:browser.console-errors", "level": "required"},
                                    {"lesson": "L99", "check":
                                     "browser-qa:browser.console-errors", "level": "blocking"}])
        found = [finding()]
        self.assertEqual(_excepted(found, Inputs(), None, now=NOW), [])
        self.assertNotIn("excepted", found[0])
        # The same finding held by L24 alone is excepted.
        alone = dict(finding(), guarded_by=finding()["guarded_by"][:1])
        self.assertEqual(len(_excepted([alone], Inputs(), None, now=NOW)), 1)


# ------------------------------------------------------------------------- fixture world


class FixtureWorld(unittest.TestCase):
    """The quality-consistency suite's world (fixtures/quality/world.py) records what the
    real steps record of a release-quality build, so once the knowledge step makes its
    runs' contracts, every genre still satisfies every rule that applies to it: compliance
    is held by fixture data, never by weakening a level."""

    def test_every_genre_satisfies_every_applicable_rule(self):
        sys.path.insert(0, os.path.join(HERE, "fixtures", "quality"))
        import test_quality_consistency as consistency
        for genre in consistency.GENRES:
            with self.subTest(genre=genre):
                case = consistency.MultiGenreConsistency()
                case.setUp()
                try:
                    api = case.api(case.world(genre))
                    state = case.to_g4(api)
                    section = case.newest(api, state, "quality-report")["compliance"]
                finally:
                    case.doCleanups()
                self.assertEqual(section["verdict"], "PASS",
                                 "\n".join(compliance.render_lines(section)))
                self.assertEqual(section["blocking"], [])
                self.assertEqual(section["counts"]["total"]["unmeasured"], 0)
                self.assertGreaterEqual(section["counts"]["by_level"]["required"]["satisfied"],
                                        14)


# ------------------------------------------------------------------------------- release


class Release(unittest.TestCase):
    def test_the_contract_and_compliance_ship_with_the_release(self):
        from wgf_release.step import COMPLIANCE_FILE, COMPLIANCE_REPORT, \
            KNOWLEDGE_CONTRACT_FILE, ReleaseStep
        root = tempfile.mkdtemp(prefix="wgf-compliance-release-")
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        _, report = run_gate(self, dict(complete_build(), **{
            "knowledge-contract": contract_for()}))
        loaded = {"knowledge-contract": contract_for(), "quality-report": report}
        inputs = types.SimpleNamespace(refs={"knowledge-contract": types.SimpleNamespace(
            content_hash=CONTRACT_HASH)})
        step = ReleaseStep.__new__(ReleaseStep)
        shipped = step._ship_knowledge(root, "r1", loaded, inputs)
        self.assertEqual(shipped["contract"], {"artifact_id": CONTRACT_ID,
                                               "content_hash": CONTRACT_HASH,
                                               "path": KNOWLEDGE_CONTRACT_FILE})
        self.assertEqual(shipped["compliance"]["verdict"], "PASS")
        directory = os.path.join(root, "release", "r1")
        for name in (KNOWLEDGE_CONTRACT_FILE, COMPLIANCE_FILE, COMPLIANCE_REPORT):
            self.assertTrue(os.path.isfile(os.path.join(directory, name)), name)
        with open(os.path.join(directory, COMPLIANCE_FILE), encoding="utf-8") as handle:
            self.assertEqual(json.load(handle), report["compliance"])

    def test_release_refuses_compliance_judged_on_another_contract(self):
        from wgf_release import lineage
        _, report = run_gate(self, dict(complete_build(), **{
            "knowledge-contract": contract_for()}))
        refs = {"quality-report": types.SimpleNamespace(content_hash=digest("q")),
                "knowledge-contract": types.SimpleNamespace(content_hash="sha256:" + "d" * 64)}
        codes = [r.code for r in lineage.quality_refusals(refs, {"quality-report": report})]
        self.assertIn("stale-knowledge-compliance", codes)


if __name__ == "__main__":
    unittest.main()

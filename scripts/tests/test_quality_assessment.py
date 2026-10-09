"""The quality assessment (scripts/wgf_quality/assessment.py, docs/quality-assessment.md).

The quality-report's `assessment` reads the evidence the quality gate already read as three
separate questions - design validity, runtime correctness, player-facing quality - each PASS,
FAIL, INCONCLUSIVE or NOT_SUPPORTED with its checks and their measurement class. It decides
nothing.

FIXTURES: the producer reports below are fixtures, built the way the producing steps write
them about one build (scripts/tests/test_quality_gate.py `release_build`); they are not
produced by the real steps. The quality-report the real gate makes from them - the section
under test - is validated against core/artifacts/quality-report.schema.json on every run.
The same section over reports the real gates produced through the engine is held in
scripts/tests/test_quality_consistency.py (QUALITY).

    python -m unittest scripts.tests.test_quality_assessment
"""

import copy
import hashlib
import os
import shutil
import sys
import tempfile
import types
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
for _path in (SCRIPTS, HERE):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import test_quality_gate as gate_fixtures  # noqa: E402
from wgf_quality import assessment, registry  # noqa: E402
from wgf_quality.step import QualityGateStep  # noqa: E402
from wgflib import gate_evidence, paths  # noqa: E402
from wgflib.workflow.contracts import ArtifactContracts  # noqa: E402
from wgflib.workflow.model import StepOutcome  # noqa: E402
from wgflib.yamllite import load_file  # noqa: E402

_check = gate_fixtures._check
VIEWPORTS = gate_fixtures.VIEWPORTS
DEV, SHIP = gate_fixtures.DEV, gate_fixtures.SHIP


def _hash(text):
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def complete_build(tier="release"):
    """FIXTURE: release_build with every check the design and runtime families hold reported
    and passing (the content contract, every unit reached, the depth checks)."""
    docs = gate_fixtures.release_build(tier=tier)
    play = docs["playability-report"]["checks"]
    for check_id in ("content.units_reachable", "entities.projectile", "depth.ramp",
                     "depth.session_length", "depth.stall"):
        play += [_check(check_id, project=p) for p in VIEWPORTS]
    docs["content-sufficiency-report"]["checks"] += [
        _check(c) for c in ("content.contract", "content.data_present",
                            "content.introductions_one_at_a_time")]
    docs["visual-qa-report"].update(judge={"kind": "command"}, judge_runs=1, judge_repairs=0)
    docs["review-report"]["reviewer"] = {"kind": "command"}
    return docs


def dims(report):
    return {d["id"]: d for d in report["assessment"]["dimensions"]}


def check_of(dimension, check_id):
    return next(c for c in dimension["checks"] if c["check"] == check_id)


def set_status(docs, artifact_type, check_id, status):
    for check in docs[artifact_type]["checks"]:
        if check["id"] == check_id:
            check["status"] = status
    return docs


def g4_decision(decision, docs, about="this-build", mode="human"):
    """FIXTURE: a G4 decision-record pinning this build's playability-report by its content
    hash (as the run's G4 checkpoint pins its required artifacts), or another one's."""
    pinned = _hash("playability-report") if about == "this-build" else _hash("earlier")
    return {"provenance": {"artifact_id": "wgf:decision-record:demo:20261009-01"},
            "gate_id": "G4", "machine": "title", "transition": "prototype-review -> production",
            "subject": [{"artifact_id": "wgf:playability-report:demo:20261009-01",
                         "artifact_type": "playability-report", "content_hash": pinned}],
            "decision": decision, "decided_by": {"role": "portfolio-owner", "mode": mode,
                                                 "identifier": "a-person"},
            "decided_at": "2026-10-09T00:00:00Z", "rationale": "played it on a phone"}


class _Log:
    def __getattr__(self, name):
        return lambda *a, **k: None


class _Base(unittest.TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp(prefix="wgf-assessment-")
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)

    def run_step(self, docs):
        """The real quality gate over `docs`; each input's ref carries a content hash."""
        class Inputs:
            refs = {k: types.SimpleNamespace(content_hash=_hash(k), seq=0) for k in docs}

            def __contains__(self, k):
                return k in docs

            def load(self, k):
                return docs[k]

        context = types.SimpleNamespace(config={}, run_dir=self.base, logger=_Log(), visit=1,
                                        attempt=1, execution=1, previous_outputs=[],
                                        environment={})
        result = QualityGateStep(types.SimpleNamespace(params={}, id="quality-gate")).execute(
            Inputs(), context)
        for artifact in result.artifacts:
            self.assertEqual(ArtifactContracts()("quality-report", artifact.content), [])
        return result

    def report(self, docs):
        return self.run_step(docs).artifacts[0].content


class Classification(_Base):
    def test_a_complete_build_holds_design_and_runtime_and_player_facing_waits_for_a_person(self):
        report = self.report(complete_build())
        view = dims(report)
        self.assertEqual(report["verdict"], "PASS")
        self.assertEqual(view["design_validity"]["status"], "PASS", view["design_validity"])
        self.assertEqual(view["runtime_correctness"]["status"], "PASS",
                         view["runtime_correctness"]["reason"])
        self.assertEqual(view["player_facing"]["status"], "INCONCLUSIVE")
        self.assertIn("no person has judged this build", view["player_facing"]["reason"])
        # Every automated check of player-facing quality is a supporting proxy.
        self.assertTrue(view["player_facing"]["checks"])
        self.assertEqual({c["role"] for c in view["player_facing"]["checks"]}, {"supporting"})
        self.assertFalse(report["assessment"]["decides"])

    def test_each_check_carries_its_measurement_class(self):
        report = self.report(complete_build())
        view = dims(report)
        runtime = view["runtime_correctness"]
        self.assertEqual(check_of(runtime, "playability:win.reachable")["class"],
                         "self-reported")
        self.assertEqual(check_of(runtime, "playability:page.errors")["class"], "deterministic")
        self.assertEqual(check_of(runtime, "playability:act.acknowledged")["class"],
                         "deterministic")
        visual = check_of(view["player_facing"], "quality-floor:floor.visual_mean")
        self.assertEqual((visual["class"], visual["judge_runs"]), ("ai-judged", 1))
        self.assertEqual(check_of(view["design_validity"],
                                  "quality-floor:floor.review_approved")["class"], "ai-judged")
        # A criterion of the report itself cites the producers' reports it read.
        approved = check_of(view["design_validity"], "quality-floor:floor.review_approved")
        self.assertEqual(approved["evidence"]["artifact_type"], "quality-report")
        self.assertEqual(approved["evidence"]["artifact_id"],
                         report["provenance"]["artifact_id"])
        self.assertIn("review-report", {c["artifact_type"] for c in approved["cites"]})
        # Producer checks cite the producer's report by id, hash and commit.
        errors = check_of(runtime, "playability:page.errors")
        self.assertEqual((errors["evidence"]["content_hash"], errors["evidence"]["commit"]),
                         (_hash("playability-report"), DEV))
        self.assertIn("self-reported", runtime["classes"])

    def test_a_held_check_that_failed_fails_its_dimension(self):
        docs = set_status(complete_build(), "playability-report", "page.errors", "FAIL")
        view = dims(self.report(docs))
        self.assertEqual(view["runtime_correctness"]["status"], "FAIL")
        self.assertIn("playability:page.errors", view["runtime_correctness"]["reason"])
        self.assertEqual(view["design_validity"]["status"], "PASS")

    def test_a_failed_design_rule_fails_design_validity(self):
        docs = complete_build()
        docs["game-design"]["consistency"] = {
            "status": "fail", "evaluated_at": "2026-10-09T00:00:00Z",
            "rule_results": [{"criterion_id": "scope_fits_session_count", "breached": True},
                             {"criterion_id": "asset_cost_within_scope", "breached": False}]}
        view = dims(self.report(docs))
        self.assertEqual(view["design_validity"]["status"], "FAIL")
        self.assertEqual(check_of(view["design_validity"],
                                  "design-consistency:scope_fits_session_count")["status"],
                         "FAIL")
        # A rule the design step did not evaluate is listed as not reported, never counted.
        self.assertIn("design-consistency:brief_commitments_met",
                      [n["check"] for n in view["design_validity"]["not_reported"]])

    def test_a_check_that_measured_nothing_is_inconclusive_never_pass(self):
        for status in ("SKIPPED", "BLOCKED", "UNMEASURED", "WARNING"):
            with self.subTest(status=status):
                docs = set_status(complete_build(), "playability-report", "restart.works",
                                  status)
                view = dims(self.report(docs))
                runtime = view["runtime_correctness"]
                self.assertEqual(runtime["status"], "INCONCLUSIVE")
                self.assertIn("playability:restart.works", runtime["reason"])
                self.assertIsNone(runtime["basis"]["strength"])
        docs = complete_build()
        docs["playability-report"]["checks"] = [
            c for c in docs["playability-report"]["checks"] if c["id"] != "start.playable"]
        runtime = dims(self.report(docs))["runtime_correctness"]
        self.assertEqual(runtime["status"], "INCONCLUSIVE")
        self.assertEqual(check_of(runtime, "playability:start.playable")["status"],
                         "UNMEASURED")

    def test_a_missing_optional_report_leaves_its_checks_unmeasured(self):
        docs = complete_build()
        del docs["review-report"]
        view = dims(self.report(docs))
        self.assertEqual(view["design_validity"]["status"], "INCONCLUSIVE")
        self.assertEqual(check_of(view["runtime_correctness"],
                                  "gate-gaming:play-area-change")["status"], "UNMEASURED")

    def test_a_pass_resting_on_the_games_word_or_one_judgment_says_so(self):
        view = dims(self.report(complete_build()))
        basis = view["runtime_correctness"]["basis"]
        self.assertEqual(basis["strength"], "qualified")
        self.assertGreater(basis["by_class"]["self-reported"], 0)
        self.assertIn("game's own report", basis["why"])
        judges = view["player_facing"]["judges"]
        self.assertEqual([(j["artifact_type"], j["kind"], j["runs"]) for j in judges],
                         [("visual-qa-report", "command", 1)])

    def test_a_major_judge_finding_of_a_passing_report_is_listed_unresolved(self):
        # Tier mvp: the floor does not hold a major visual finding there, so the gate and
        # visual-qa pass the build - and the finding is still listed, deciding nothing.
        docs = complete_build(tier="mvp")
        docs["visual-qa-report"]["findings"] = [
            {"id": "card-covers-ball", "severity": "major", "category": "ui",
             "summary": "the objective card covers the ball", "route": "develop"},
            {"id": "tiny-shadow", "severity": "minor", "category": "composition",
             "summary": "a shadow is clipped", "route": "assets"}]
        with_view = self.report(docs)
        self.assertEqual(with_view["verdict"], "PASS")
        self.assertEqual(docs["visual-qa-report"]["verdict"], "PASS")
        unresolved = dims(with_view)["player_facing"]["unresolved"]
        self.assertEqual([(u["id"], u["severity"], u["report_verdict"]) for u in unresolved],
                         [("card-covers-ball", "major", "PASS")])
        with mock.patch("wgf_quality.step.assessment_of", return_value=None):
            without = self.report(docs)
        self.assertEqual(with_view["release_decision"], without["release_decision"])
        lines = "\n".join(gate_evidence.render(gate_evidence.summarize(
            {"quality-report": with_view})))
        self.assertIn("unresolved major finding card-covers-ball on a PASS visual-qa-report",
                      lines)

    def test_stale_evidence_is_never_assessed_as_current(self):
        docs = complete_build()
        report = self.report(docs)
        self.assertNotIn("assessment", self.report(
            dict(docs, **{"playability-report": dict(docs["playability-report"],
                                                     commit="f" * 40)})))
        self.assertIn("assessment", report)


class PlayerFacing(_Base):
    """Player-facing quality is never PASS from automation alone."""

    def test_every_proxy_passing_is_still_inconclusive(self):
        view = dims(self.report(complete_build()))
        proxies = [c for c in view["player_facing"]["checks"] if c["holds"]]
        self.assertTrue(proxies)
        self.assertEqual(view["player_facing"]["status"], "INCONCLUSIVE")
        self.assertEqual(view["player_facing"]["human"], [])

    def test_a_persons_g4_pass_on_this_build_passes_it(self):
        docs = complete_build()
        docs["decision-record"] = g4_decision("pass", docs)
        player = dims(self.report(docs))["player_facing"]
        self.assertEqual(player["status"], "PASS")
        self.assertEqual(player["human"][0]["about"], "this-build")
        self.assertEqual(player["classes"]["human"], 1)
        self.assertEqual(player["basis"]["strength"], "person")

    def test_a_persons_iterate_on_this_build_fails_it(self):
        docs = complete_build()
        docs["decision-record"] = g4_decision("iterate", docs)
        self.assertEqual(dims(self.report(docs))["player_facing"]["status"], "FAIL")

    def test_a_decision_on_an_earlier_build_decides_nothing(self):
        docs = complete_build()
        docs["decision-record"] = g4_decision("pass", docs, about="earlier-build")
        player = dims(self.report(docs))["player_facing"]
        self.assertEqual(player["status"], "INCONCLUSIVE")
        self.assertEqual((player["human"][0]["about"], player["human"][0]["verdict"]),
                         ("earlier-build", None))

    def test_a_decision_that_is_not_a_persons_is_never_human_evidence(self):
        docs = complete_build()
        docs["decision-record"] = g4_decision("pass", docs, mode="auto-approved")
        player = dims(self.report(docs))["player_facing"]
        self.assertEqual((player["status"], player["human"]), ("INCONCLUSIVE", []))
        docs["decision-record"] = dict(g4_decision("pass", docs), gate_id="G3")
        self.assertEqual(dims(self.report(docs))["player_facing"]["status"], "INCONCLUSIVE")

    def test_a_failed_proxy_fails_it_whatever_a_person_said(self):
        docs = set_status(complete_build(), "playability-report", "frames.readable", "FAIL")
        docs["decision-record"] = g4_decision("pass", docs)
        self.assertEqual(dims(self.report(docs))["player_facing"]["status"], "FAIL")


class NotSupported(unittest.TestCase):
    """A dimension no held check applies to says so (evaluate over a narrowed mapping)."""

    def setUp(self):
        data = registry.load(paths.ROOT)
        self.tiers = data["tiers"]
        self.checks, _ = registry.classify(self.tiers, paths.ROOT)
        self.mapping = load_file(os.path.join(paths.ROOT, *assessment.MAPPING_FILE.split("/")))

    def narrowed(self, families):
        mapping = copy.deepcopy(self.mapping)
        mapping["families"] = [f for f in mapping["families"] if f["id"] in families]
        return mapping

    def test_no_check_applies(self):
        mapping = self.narrowed({"design-rules"})
        section = assessment.evaluate(mapping, self.tiers, self.checks,
                                      {"game-design": {"title_id": "demo"}})
        view = {d["id"]: d for d in section["dimensions"]}
        self.assertEqual(view["design_validity"]["status"], "NOT_SUPPORTED")
        self.assertEqual(view["runtime_correctness"]["status"], "NOT_SUPPORTED")
        self.assertEqual(view["player_facing"]["status"], "NOT_SUPPORTED")

    def test_only_advisory_checks_apply(self):
        mapping = self.narrowed({"design-rules"})
        design = {"title_id": "demo", "consistency": {"rule_results": [
            {"criterion_id": "first_reward_within_first_session", "breached": False}]}}
        section = assessment.evaluate(mapping, self.tiers, self.checks, {"game-design": design})
        dim = section["dimensions"][0]
        self.assertEqual(dim["status"], "NOT_SUPPORTED")
        self.assertEqual([(c["check"], c["role"], c["status"]) for c in dim["checks"]],
                         [("design-consistency:first_reward_within_first_session",
                           "supporting", "PASS")])

    def test_an_unreadable_mapping_is_inconclusive_everywhere(self):
        section = assessment.evaluate(None, self.tiers, self.checks, {},
                                      problem="cannot be read")
        self.assertEqual({d["status"] for d in section["dimensions"]}, {"INCONCLUSIVE"})
        self.assertEqual(section["problem"], "cannot be read")


class DecidesNothing(_Base):
    """The release decision, the verdict, the floor and every other section are identical
    with and without the assessment."""

    VARIANTS = {
        "release": lambda: complete_build(),
        "mobile-40": lambda: gate_fixtures.mobile_40(complete_build()),
        "mvp": lambda: complete_build(tier="mvp"),
        "unmeasured": lambda: set_status(complete_build(), "playability-report",
                                         "restart.works", "SKIPPED"),
        "person-iterated": lambda: dict(complete_build(), **{
            "decision-record": g4_decision("iterate", complete_build())}),
    }

    def test_the_release_decision_is_the_same_without_the_section(self):
        for name, make in self.VARIANTS.items():
            with self.subTest(variant=name):
                with_view = self.run_step(make())
                with mock.patch("wgf_quality.step.assessment_of", return_value=None):
                    without = self.run_step(make())
                a, b = with_view.artifacts[0].content, without.artifacts[0].content
                self.assertIn("assessment", a)
                self.assertNotIn("assessment", b)
                self.assertEqual((with_view.outcome, with_view.route),
                                 (without.outcome, without.route))
                for key in ("verdict", "release_decision", "failed", "routes", "dimensions",
                            "criteria", "findings", "scorecard", "deferred",
                            "blocked_reason"):
                    self.assertEqual(a.get(key), b.get(key), key)
                strip = lambda c: {k: v for k, v in (c or {}).items()  # noqa: E731
                                   if k != "evaluated_by"}
                self.assertEqual(strip(a.get("compliance"))["verdict"],
                                 strip(b.get("compliance"))["verdict"])


class GateSummary(_Base):
    def test_g4_shows_the_three_dimensions_as_stated(self):
        report = self.report(complete_build())
        lines = gate_evidence.render(gate_evidence.summarize({"quality-report": report}))
        text = "\n".join(lines)
        self.assertIn("assessment (a view over the evidence above - it decides nothing)", text)
        player = next(line for line in lines if "Player-facing quality" in line)
        self.assertIn("INCONCLUSIVE", player)
        self.assertNotIn("PASS", player)
        runtime = next(line for line in lines if "Runtime correctness" in line)
        self.assertIn("PASS (qualified)", runtime)
        self.assertIn("self-reported", runtime)

    def test_not_supported_and_inconclusive_are_never_shown_as_a_pass(self):
        report = self.report(complete_build())
        for dim in report["assessment"]["dimensions"]:
            dim["status"] = "NOT_SUPPORTED" if dim["id"] == "design_validity" else "INCONCLUSIVE"
            dim["basis"]["strength"] = None
        lines = gate_evidence.render(gate_evidence.summarize({"quality-report": report}))
        rows = [line for line in lines if any(
            label in line for label in ("Design validity", "Runtime correctness",
                                        "Player-facing quality"))]
        self.assertEqual(len(rows), 3)
        for row in rows:
            self.assertNotIn("PASS", row)
        self.assertIn("NOT_SUPPORTED", rows[0])


class Coverage(unittest.TestCase):
    """check-integrity holds the mapping to check-tiers.yaml and the floor."""

    def setUp(self):
        data = registry.load(paths.ROOT)
        self.tiers = data["tiers"]
        self.checks, _ = registry.classify(self.tiers, paths.ROOT)
        self.mapping = load_file(os.path.join(paths.ROOT, *assessment.MAPPING_FILE.split("/")))
        self.floor = load_file(os.path.join(paths.REFERENCE, "quality-floor.yaml"))

    def problems(self, mapping):
        return assessment.problems(mapping, self.tiers, self.checks, self.floor, paths.ROOT)

    def family(self, mapping, fid):
        return next(f for f in mapping["families"] if f["id"] == fid)

    def test_the_shipped_mapping_covers_every_declared_check(self):
        self.assertEqual(self.problems(self.mapping), [])
        self.assertEqual(registry.assessment_problems(self.tiers, self.checks, paths.ROOT), [])

    def test_a_check_no_family_names_fails(self):
        mapping = copy.deepcopy(self.mapping)
        self.family(mapping, "oracle-states")["checks"].remove("playability:win.reachable")
        self.assertTrue(any("playability:win.reachable" in p and "no family names it" in p
                            for p in self.problems(mapping)))

    def test_a_check_check_tiers_does_not_declare_fails(self):
        mapping = copy.deepcopy(self.mapping)
        self.family(mapping, "oracle-states")["checks"].append("playability:fun.measured")
        self.assertTrue(any("playability:fun.measured" in p for p in self.problems(mapping)))

    def test_a_source_neither_mapped_nor_excluded_fails(self):
        mapping = copy.deepcopy(self.mapping)
        del mapping["excluded"]["quality-dimension"]
        self.assertTrue(any("quality-dimension" in p and "neither" in p
                            for p in self.problems(mapping)))

    def test_a_floor_verdict_criterion_no_family_places_fails(self):
        mapping = copy.deepcopy(self.mapping)
        self.family(mapping, "qa-and-verify")["checks"].remove("quality-floor:floor.qa_pass")
        self.assertTrue(any("floor.qa_pass" in p for p in self.problems(mapping)))

    def test_a_check_in_two_families_fails(self):
        mapping = copy.deepcopy(self.mapping)
        self.family(mapping, "pacing-proxies")["checks"].append("playability:win.reachable")
        self.assertTrue(any("in families" in p for p in self.problems(mapping)))

    def test_an_ai_judged_family_names_its_judge_and_no_family_is_human(self):
        mapping = copy.deepcopy(self.mapping)
        del self.family(mapping, "visual-judge")["judge"]
        self.family(mapping, "oracle-states")["class"] = "human"
        found = self.problems(mapping)
        self.assertTrue(any("visual-judge" in p and "judge" in p for p in found))
        self.assertTrue(any("oracle-states" in p and "human" in p for p in found))

    def test_player_facing_must_require_a_person(self):
        mapping = copy.deepcopy(self.mapping)
        mapping["dimensions"]["player_facing"]["requires"] = "automation"
        self.assertTrue(any("player_facing" in p for p in self.problems(mapping)))

    def test_every_family_says_what_it_cannot_justify(self):
        mapping = copy.deepcopy(self.mapping)
        self.family(mapping, "visual-judge")["cannot_justify"] = ""
        self.assertTrue(any("cannot_justify" in p for p in self.problems(mapping)))


if __name__ == "__main__":
    unittest.main()

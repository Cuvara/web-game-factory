"""The quality scorecard (WS-9): one line per discipline, hard blockers apart, no average past one.

The quality gate scores every criterion of core/reference/quality-floor.yaml; the scorecard
reads the same results per discipline a person judges a game by - gameplay, game feel, level
design, 2D art, 3D art, UI/UX, audio, performance, technical integrity, accessibility and
readability, platform compliance, publishing readiness - and lists every hard blocker on its
own. These tests hold:

  * the release fixture scores every applicable line, the art line of the other rendering
    dimension is NOT_APPLICABLE, the store is DEFERRED and a line nothing measures is
    UNMEASURED (a gap, never a pass);
  * a build that scores high everywhere with ONE blocker below its minimum fails: its line
    is BELOW_FLOOR whatever its mean, the blocker is listed apart, and the overall score -
    high - decides nothing;
  * a line's own `min_score` holds the build though its floor dimension passes;
  * the scorecard data is validated: every floor dimension on exactly one line per rendering
    dimension, and a criterion's `scorecard` names a line;
  * a floor from before the scorecard (pinned by an old run) produces no scorecard, and the
    gate scores it as before.

    python -m unittest scripts.tests.test_quality_scorecard
"""

import copy
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
for _path in (SCRIPTS, HERE):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import test_quality_gate as qg  # noqa: E402
from wgf_quality import scoring  # noqa: E402
from wgf_quality.step import load_contract  # noqa: E402
from wgflib import gate_evidence  # noqa: E402
from wgflib.workflow.model import StepOutcome  # noqa: E402

LINES = ["gameplay", "feel", "level_design", "art_2d", "art_3d", "ui_ux", "audio",
         "performance", "browser", "technical", "accessibility", "platform_compliance",
         "publishing_readiness"]


def _score(docs, spec=None, render="2d", family="arcade", tier="release", previous=None):
    spec = spec or load_contract()[0]
    criteria, summary = scoring.derive(spec, {"genre": {"family": family}}, render=render)
    return scoring.score(spec, criteria, docs, {}, tier, scoring.build_identity(docs),
                         previous=previous, render=render)


def _line(result, line_id):
    return next(line for line in result["scorecard"]["lines"] if line["id"] == line_id)


class Scorecard(unittest.TestCase):
    def test_the_shipped_scorecard_has_every_requested_line(self):
        spec, _ = load_contract()
        self.assertEqual(list(spec["floor"]["scorecard"]), LINES)

    def test_a_release_build_scores_every_line_it_can_be_measured_on(self):
        result = _score(qg.release_build())
        self.assertEqual(result["verdict"], "PASS")
        card = result["scorecard"]
        self.assertEqual(card["render"], "2d")
        self.assertEqual(card["hard_blockers"], [])
        status = {line["id"]: line["status"] for line in card["lines"]}
        for line_id in ("gameplay", "feel", "level_design", "art_2d", "ui_ux", "audio",
                        "performance", "technical", "platform_compliance"):
            self.assertEqual(status[line_id], "PASS", line_id)
            self.assertEqual(_line(result, line_id)["score"], 100.0, line_id)
        self.assertEqual(status["art_3d"], "NOT_APPLICABLE")
        self.assertEqual(status["publishing_readiness"], "DEFERRED")
        # An arcade 2D game: no criterion of the floor measures accessibility for it. That is
        # reported as a gap in the Factory's measurement - never a pass.
        self.assertEqual(status["accessibility"], "UNMEASURED")
        self.assertIn("never a pass", _line(result, "accessibility")["reason"])
        # Criteria that name their own line are read there, not in their dimension's.
        self.assertIn("floor.performance", _line(result, "performance")["criteria"])
        self.assertIn("floor.controls", _line(result, "feel")["criteria"])
        self.assertNotIn("floor.performance", _line(result, "technical")["criteria"])

    def test_a_high_average_with_one_blocker_fails(self):
        docs = qg.release_build()
        # Everything else holds; restart fails on mobile only - one blocker, a sliver of the
        # build's measurements.
        for check in docs["playability-report"]["checks"]:
            if check["id"] == "restart.works" and check.get("project") == "mobile":
                check["status"] = "FAIL"
        result = _score(docs)
        gameplay = _line(result, "gameplay")
        self.assertEqual(gameplay["status"], "BELOW_FLOOR")
        self.assertGreaterEqual(gameplay["score"], 75.0)   # its own mean is above any floor
        self.assertIn("floor.core_loop", gameplay["blockers"])
        self.assertIn("no score on this or any other line lifts them", gameplay["reason"])
        self.assertGreater(result["overall_score"], 90.0)  # and the build's overall is high
        blocked = {b["criterion"]: b for b in result["scorecard"]["hard_blockers"]}
        self.assertIn("floor.core_loop", blocked)
        self.assertEqual((blocked["floor.core_loop"]["line"], blocked["floor.core_loop"]["status"]),
                         ("gameplay", "FAIL"))
        self.assertEqual(result["verdict"], "FAIL")
        self.assertEqual(result["release_decision"]["decision"], "not-release")
        # Every other line still holds: one blocker is enough.
        for line in result["scorecard"]["lines"]:
            if line["id"] not in ("gameplay", "feel"):
                self.assertNotEqual(line["status"], "BELOW_FLOOR", line)

    def test_an_unmeasured_blocker_is_a_hard_blocker_never_a_pass(self):
        docs = qg.release_build()
        del docs["qa-report"]["perf_results"]
        result = _score(docs)
        performance = _line(result, "performance")
        self.assertEqual(performance["status"], "BELOW_FLOOR")
        self.assertIn("floor.performance", performance["blockers"])
        self.assertEqual({b["criterion"]: b["status"]
                          for b in result["scorecard"]["hard_blockers"]}["floor.performance"],
                         "UNMEASURED")
        self.assertEqual(result["verdict"], "FAIL")

    def test_a_lines_own_floor_holds_the_build_though_its_dimension_passes(self):
        spec = copy.deepcopy(load_contract()[0])
        spec["floor"]["scorecard"]["feel"]["min_score"] = {"release": 99}
        docs = qg.release_build()
        # Minor visual findings over the release maximum: a warning, scored in `polish`.
        docs["visual-qa-report"]["findings"] = [
            {"id": f"m{i}", "severity": "minor", "category": "ui", "summary": "a nit",
             "route": "develop"} for i in range(9)]
        result = _score(docs, spec=spec)
        polish = next(d for d in result["dimensions"] if d["id"] == "polish")
        self.assertEqual(polish["status"], "PASS")
        feel = _line(result, "feel")
        self.assertEqual(feel["status"], "BELOW_FLOOR")
        self.assertEqual(feel["blockers"], [])
        self.assertEqual(result["verdict"], "FAIL")
        self.assertEqual(result["routes"], ["develop"])
        self.assertTrue(any(r.startswith("scorecard feel below its floor")
                            for r in result["release_decision"]["reasons"]))

    def test_a_3d_game_is_scored_on_3d_art_and_its_readability(self):
        result = _score(qg.release_build(family="racing"), render="3d", family="racing")
        self.assertEqual(_line(result, "art_2d")["status"], "NOT_APPLICABLE")
        art = _line(result, "art_3d")
        self.assertEqual(art["status"], "PASS")
        self.assertIn("render.environment", art["criteria"])
        access = _line(result, "accessibility")
        self.assertEqual(access["status"], "PASS")
        self.assertIn("render.spatial_readability", access["criteria"])
        self.assertIn("genre.course_readable", access["criteria"])

    def test_every_criterion_is_on_exactly_one_line(self):
        spec, _ = load_contract()
        for render in ("2d", "3d"):
            for family in list(spec["floor"]["genres"]):
                criteria, _ = scoring.derive(spec, {"genre": {"family": family}},
                                             render=render)
                result = _score(qg.release_build(family=family), render=render, family=family)
                placed = [c for line in result["scorecard"]["lines"] for c in line["criteria"]]
                applied = [r["id"] for r in result["criteria"]]
                self.assertEqual(sorted(placed), sorted(applied), (render, family))

    def test_a_dimension_on_no_line_is_refused(self):
        spec, _ = load_contract()
        floor = copy.deepcopy(spec["floor"])
        floor["scorecard"]["audio"]["dimensions"] = []
        with self.assertRaises(scoring.ContractError) as caught:
            scoring.contract(floor, {}, {})
        self.assertIn("'audio' feeds 0 lines", str(caught.exception))

    def test_a_dimension_on_two_lines_is_refused(self):
        spec, _ = load_contract()
        floor = copy.deepcopy(spec["floor"])
        floor["scorecard"]["feel"]["dimensions"].append("gameplay")
        with self.assertRaises(scoring.ContractError):
            scoring.contract(floor, {}, {})

    def test_a_criterion_naming_no_line_is_refused(self):
        spec, _ = load_contract()
        floor = copy.deepcopy(spec["floor"])
        floor["universal"][0]["scorecard"] = "vibes"
        with self.assertRaises(scoring.ContractError) as caught:
            scoring.contract(floor, {}, {})
        self.assertIn("vibes", str(caught.exception))

    def test_a_floor_from_before_the_scorecard_scores_as_before(self):
        spec = copy.deepcopy(load_contract()[0])
        del spec["floor"]["scorecard"]
        result = _score(qg.release_build(), spec=spec)
        self.assertIsNone(result["scorecard"])
        self.assertEqual(result["verdict"], "PASS")


BROWSER_IDS = ("loads", "canvas", "ready", "menus", "load-time", "first-interaction",
               "page-errors", "console-errors", "webgl-context", "context-menu", "win", "lose",
               "restart", "pause-resume", "hidden-pause", "overflow", "clipping", "ui-overlap",
               "ui-covers-play")
ONCE_IDS = ("audio-clips", "audio-events", "audio-loops", "audio-mute", "audio-hidden",
            "audio-loudness", "frame-stability", "memory-growth", "oversized-textures")
ADVISORY_IDS = ("safe-margins", "button-states", "asset-weight")
REALISM_IDS = ("physics.undrawn_collision", "physics.collider_size", "naive.setbacks",
               "naive.pace", "naive.unit_duration", "naive.clear_rate", "level.geometry",
               "level.unit_length", "runtime.console_errors", "runtime.webgl_context")


def _with_browser_and_realism(docs):
    """The release build with a browser-QA verification (browser-qa.yaml, every viewport) and
    the play-realism checks a release-tier bot reports, all passing."""
    checks = [qg._check("browser.run")]
    for cid in BROWSER_IDS:
        checks += [qg._check(f"browser.{cid}:{vp}") for vp in ("desktop-wide", "mobile")]
    checks += [qg._check(f"browser.{cid}") for cid in ONCE_IDS]
    checks += [qg._check(f"browser.{cid}:mobile", required=False) for cid in ADVISORY_IDS]
    docs["verification-report"]["checks"] = checks
    docs["playability-report"]["checks"] += [qg._check(cid, project="desktop")
                                             for cid in REALISM_IDS]
    return docs


def _set(report, check_id, status, **extra):
    for check in report["checks"]:
        if check["id"] == check_id:
            check["status"] = status
            check.update(extra)
            return
    raise AssertionError(check_id)


class BrowserQAAndPlayRealism(unittest.TestCase):
    """Browser QA (browser-qa.yaml) and play realism (play-realism.yaml) on the scorecard:
    each check is on the line of the discipline that owns it, and a failure there holds the
    build whatever the other lines score."""

    def test_a_build_passing_both_scores_every_line_they_feed(self):
        result = _score(_with_browser_and_realism(qg.release_build()))
        self.assertEqual(result["verdict"], "PASS")
        status = {line["id"]: line["status"] for line in result["scorecard"]["lines"]}
        for line_id in ("browser", "performance", "ui_ux", "audio", "feel", "level_design",
                        "gameplay"):
            self.assertEqual(status[line_id], "PASS", line_id)
        self.assertIn("floor.browser_boot", _line(result, "browser")["criteria"])
        self.assertIn("floor.browser_session", _line(result, "browser")["criteria"])
        self.assertIn("floor.runtime_console", _line(result, "browser")["criteria"])
        self.assertIn("floor.browser_performance", _line(result, "performance")["criteria"])
        self.assertIn("floor.webgl_context", _line(result, "performance")["criteria"])
        self.assertIn("floor.browser_layout", _line(result, "ui_ux")["criteria"])
        self.assertIn("floor.browser_audio", _line(result, "audio")["criteria"])
        self.assertIn("floor.physics_drawn", _line(result, "feel")["criteria"])
        self.assertIn("floor.naive_challenge", _line(result, "level_design")["criteria"])
        self.assertIn("floor.level_geometry", _line(result, "level_design")["criteria"])

    def test_a_context_menu_on_one_viewport_holds_the_browser_line(self):
        docs = _with_browser_and_realism(qg.release_build())
        _set(docs["verification-report"], "browser.context-menu:mobile", "FAIL")
        result = _score(docs)
        self.assertEqual(_line(result, "browser")["status"], "BELOW_FLOOR")
        self.assertIn("floor.browser_boot", _line(result, "browser")["blockers"])
        self.assertEqual(result["verdict"], "FAIL")

    def test_a_silent_loss_holds_the_audio_line(self):
        docs = _with_browser_and_realism(qg.release_build())
        _set(docs["verification-report"], "browser.audio-events", "FAIL")
        result = _score(docs)
        self.assertEqual(_line(result, "audio")["status"], "BELOW_FLOOR")
        self.assertIn("floor.browser_audio", _line(result, "audio")["blockers"])

    def test_unstable_frames_hold_the_performance_line(self):
        docs = _with_browser_and_realism(qg.release_build())
        _set(docs["verification-report"], "browser.frame-stability", "FAIL")
        result = _score(docs)
        self.assertEqual(_line(result, "performance")["status"], "BELOW_FLOOR")
        self.assertIn("floor.browser_performance", _line(result, "performance")["blockers"])

    def test_advisory_browser_checks_are_findings_never_a_blocker(self):
        docs = _with_browser_and_realism(qg.release_build())
        _set(docs["verification-report"], "browser.button-states:mobile", "WARNING")
        result = _score(docs)
        self.assertEqual(result["verdict"], "PASS")
        self.assertNotIn("floor.browser_ui_advisory", _line(result, "ui_ux")["blockers"])

    def test_a_unit_held_forward_through_holds_level_design(self):
        docs = _with_browser_and_realism(qg.release_build())
        _set(docs["playability-report"], "naive.pace", "FAIL")
        result = _score(docs)
        self.assertEqual(_line(result, "level_design")["status"], "BELOW_FLOOR")
        self.assertIn("floor.naive_challenge", _line(result, "level_design")["blockers"])

    def test_a_turn_at_nothing_drawn_holds_game_feel(self):
        docs = _with_browser_and_realism(qg.release_build())
        _set(docs["playability-report"], "physics.undrawn_collision", "FAIL")
        result = _score(docs)
        self.assertEqual(_line(result, "feel")["status"], "BELOW_FLOOR")
        self.assertIn("floor.physics_drawn", _line(result, "feel")["blockers"])

    def test_an_unmeasured_clear_rate_alone_is_not_held(self):
        # No accepted build: naive.clear_rate is reported unmeasured and not required - never
        # a pass, never a blocker (play-realism.yaml clear_rate); the other naive checks count.
        docs = _with_browser_and_realism(qg.release_build())
        _set(docs["playability-report"], "naive.clear_rate", "WARNING", required=False)
        result = _score(docs)
        self.assertEqual(_line(result, "level_design")["status"], "PASS")

    def test_below_the_release_class_an_optional_failure_is_the_producers_warning(self):
        # A run below the release class (tier mvp over a release-tier design): play realism
        # and browser QA report their quality checks optional - a failure is a WARNING, an
        # unmeasured check a note. The floor counts their passes and is not held by them.
        docs = _with_browser_and_realism(qg.release_build())
        for report in (docs["verification-report"], docs["playability-report"]):
            for check in report["checks"]:
                if check["id"].startswith(("browser.", "physics.", "naive.", "level.",
                                           "runtime.")):
                    check["required"] = False
        _set(docs["verification-report"], "browser.audio-events", "WARNING")
        _set(docs["playability-report"], "physics.collider_size", "WARNING")
        result = _score(docs)
        self.assertEqual(result["verdict"], "PASS")
        self.assertIn("floor.physics_drawn", _line(result, "feel")["criteria"])

    def test_checks_all_optional_and_none_passed_do_not_apply(self):
        # A 3D build reports no screen turns, and its collider unmeasured below the release
        # class: physics_drawn has nothing the producer holds - it does not apply, rather
        # than blocking as UNMEASURED.
        docs = _with_browser_and_realism(qg.release_build())
        docs["playability-report"]["checks"] = [
            c for c in docs["playability-report"]["checks"]
            if c["id"] != "physics.undrawn_collision"]
        _set(docs["playability-report"], "physics.collider_size", "WARNING", required=False)
        result = _score(docs)
        self.assertEqual(result["verdict"], "PASS")
        self.assertNotIn("floor.physics_drawn", _line(result, "feel")["criteria"])

    def test_at_the_release_class_an_unmeasured_held_check_blocks(self):
        # The same collider unmeasured at the release class is held (quality-policy
        # skipped_checks): a required FAIL, and the line is below its floor.
        docs = _with_browser_and_realism(qg.release_build())
        _set(docs["playability-report"], "physics.collider_size", "FAIL")
        result = _score(docs)
        self.assertEqual(_line(result, "feel")["status"], "BELOW_FLOOR")

    def test_a_build_without_browser_qa_or_realism_is_not_scored_on_them(self):
        result = _score(qg.release_build())
        self.assertNotIn("floor.browser_boot", _line(result, "browser")["criteria"])
        self.assertNotIn("floor.physics_drawn", _line(result, "feel")["criteria"])


class ThroughTheStep(unittest.TestCase):
    """The step writes the scorecard into a schema-valid quality-report; G4 shows it."""

    def gate(self):
        gate = qg.Gate("test_a_build_holding_every_floor_at_release_is_a_release")
        gate.setUp()
        self.addCleanup(gate.doCleanups)
        return gate

    def test_the_report_carries_the_scorecard_and_g4_shows_its_blockers(self):
        docs = qg.release_build()
        for check in docs["playability-report"]["checks"]:
            if check["id"] == "restart.works" and check.get("project") == "mobile":
                check["status"] = "FAIL"
        result = self.gate().run_step(docs)   # validates the report against its schema
        self.assertEqual(result.outcome, StepOutcome.FAILED)
        report = result.artifacts[0].content
        # The core loop's restart and the arcade contract's replay both read restart.works.
        self.assertEqual([b["criterion"] for b in report["scorecard"]["hard_blockers"]],
                         ["floor.core_loop", "genre.replay"])
        lines = "\n".join(gate_evidence.render(gate_evidence.summarize(
            {"quality-report": report})))
        self.assertIn("scorecard:", lines)
        self.assertIn("! hard blocker floor.core_loop (gameplay, FAIL): no score lifts it", lines)

    def test_missing_gates_are_named_and_the_build_is_never_a_release(self):
        gate = self.gate()
        result = gate.run_step(qg.release_build(), environment={})
        self.assertEqual(result.artifacts[0].content["release_decision"]["decision"], "release")
        # The same build, judged in a run whose workflow lacks two gates the Factory now
        # requires before this one.
        import types
        from wgf_quality.step import QualityGateStep

        docs = qg.release_build()

        class Inputs:
            refs = {k: types.SimpleNamespace(content_hash=None, seq=0) for k in docs}

            def __contains__(self, k):
                return k in docs

            def load(self, k):
                return docs[k]

        class Log:
            def __getattr__(self, name):
                return lambda *a, **k: None

        context = types.SimpleNamespace(
            config={}, run_dir=gate.base, logger=Log(), visit=1, attempt=1, execution=1,
            previous_outputs=[], environment={},
            missing_gates=[{"step": "content-sufficiency", "stage": "title:prototype",
                            "type": "content-sufficiency"},
                           {"step": "accepted-baseline", "stage": None, "type": None}])
        result = QualityGateStep(types.SimpleNamespace(params={}, id="quality-gate")).execute(
            Inputs(), context)
        report = result.artifacts[0].content
        from wgflib.workflow.contracts import ArtifactContracts
        self.assertEqual(ArtifactContracts()("quality-report", report), [])
        self.assertEqual([g["step"] for g in report["missing_gates"]],
                         ["content-sufficiency", "accepted-baseline"])
        self.assertEqual(report["release_decision"]["decision"], "not-release")
        self.assertIn("lacks gate(s)", report["release_decision"]["reasons"][0])
        lines = "\n".join(gate_evidence.render(gate_evidence.summarize(
            {"quality-report": report})))
        self.assertIn("MISSING GATES", lines)
        self.assertIn("content-sufficiency, accepted-baseline", lines)


if __name__ == "__main__":
    unittest.main()

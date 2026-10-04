"""WS-12: every new-game run inherits the quality policy, and no entry point bypasses it.

core/reference/quality-policy.yaml, applied by scripts/wgflib/workflow/quality.py through the
engine; docs/new-game-quality-inheritance.md lists every entry point. Each test here closes
one BYPASS that document names, on the shipped new-game definition:

  * a run records its tier, class and the policy and benchmark versions at start, and the
    snapshot is corroborated like every param;
  * `wgf new-game --run` after a re-plan runs every step after it again, not only the gates
    (it used to skip init..verify and re-ask G4 on the old build);
  * `wgf develop --run` then `wgf resume --from prototype-review` (or `--from verify`) does
    not put the new build in front of G4 without playability, production-quality, visual-qa
    and review having passed it: the run stops BLOCKED at the quality floor;
  * a fresh `wgf release` does not draft from nothing;
  * tier mvp, a weakening configuration (at start or at a later resume) and a workflow the
    Factory does not ship make a run development - every artifact and the final status say
    so, never release - and a development run is never submitted;
  * a mock run stays allowed and is reported development.

"Non-production" engines here run the shipped definition with the placeholder steps but
WITHOUT the run's `mock` param, so the policy holds them exactly as a real run.
"""

import os
import shutil
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

import wgf  # noqa: E402
from wgflib import provenance  # noqa: E402
from wgflib.workflow import integrity, mock, quality  # noqa: E402
from wgflib.workflow.api import RunRequest, WorkflowAPI  # noqa: E402
from wgflib.workflow.config import ConfigError, FactoryConfig  # noqa: E402
from wgflib.workflow.engine import EngineError  # noqa: E402
from wgflib.workflow.events import Events  # noqa: E402
from wgflib.workflow.model import RunStatus, StepStatus  # noqa: E402

GATES = {"auto_approve": ["G2", "G3", "G5"]}
FLOOR_STEPS = ("playability", "production-quality", "visual-qa", "content-sufficiency",
               "review", "sdk-review", "verify")
# The placeholder runs below build nothing, but a run is refused before it starts when the
# configured design author cannot meet its tier (preflight); the agent author can.
AUTHOR = {"author": "agent"}


class _PlaceholderAPI(WorkflowAPI):
    """WorkflowAPI with the placeholder steps registered for every run, mock or not: a run
    started without --mock is held to the policy exactly as a real one."""

    def registry(self, use_mock, load_modules=True):
        return super().registry(True, load_modules=False)


class _Case(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.mkdtemp(prefix="wgf-ws12-")
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)
        self.store_dir = os.path.join(self.scratch, "store")

    def api(self, extra=None, workflow=None):
        data = {"storage": {"fsync": False}, "checkpoints": dict(GATES), "design": dict(AUTHOR)}
        for key, value in (extra or {}).items():
            data[key] = value
        return _PlaceholderAPI(config=FactoryConfig(data), store_dir=self.store_dir,
                               workflow=workflow)

    def to_g4(self, api=None, **request):
        api = api or self.api()
        state = api.run(RunRequest(**request))
        self.assertEqual((state.status, state.cursor), (RunStatus.WAITING, "prototype-review"),
                         state.message)
        return api, state

    def decide(self, api, run_id, choice="pass"):
        return api.run(RunRequest(resume=run_id, decision=choice, decided_by="human",
                                  note="WS-12 test"))

    @staticmethod
    def executed(state, since=0):
        return [entry["step"] for entry in state.trail[since:]]

    def events(self, api, run_id, name):
        return [e for e in api.store.read_events(run_id) if e["event"] == name]


class Snapshot(_Case):
    def test_a_new_run_records_tier_class_and_versions(self):
        api, state = self.to_g4()
        taken = state.params["quality"]
        policy = quality.load_policy()
        self.assertEqual((taken["tier"], taken["class"]), ("release", "release"))
        self.assertEqual(taken["policy"], policy["version"])
        self.assertTrue(taken["benchmark"].startswith("quality-benchmark@"))
        for step_id in ("content-sufficiency", "quality-gate"):
            self.assertIn(step_id, taken["required_steps"])
        # content-sufficiency (WS-4) and quality-gate (WS-7) are in the workflow and
        # enforced: nothing is pending.
        self.assertEqual(taken["pending"], [])
        started = self.events(api, state.run_id, Events.WORKFLOW_STARTED)[0]
        self.assertEqual(started["data"]["params"]["quality"], taken)

    def test_an_edited_class_is_refused(self):
        api, state = self.to_g4(self.api({"strategy": {"quality_tier": "mvp"}}))
        self.assertEqual(state.params["quality"]["class"], "development")
        edited = api.store.load(state.run_id)
        edited.params["quality"] = dict(edited.params["quality"], **{"class": "release"})
        edited.params["quality"].pop("reasons", None)
        api.store.save(edited)
        with self.assertRaisesRegex(EngineError, "params.quality"):
            self.decide(api, state.run_id)

    def test_steps_read_the_tier_the_run_started_with(self):
        self.assertEqual(quality.run_tier({"quality": {"tier": "mvp"}}), "mvp")
        self.assertIsNone(quality.run_tier({}))
        self.assertEqual(quality.run_tier(None, "release"), "release")

    def test_an_unknown_tier_starts_no_run(self):
        with self.assertRaises(ConfigError):
            self.api({"strategy": {"quality_tier": "gold"}}).run(RunRequest())


class ReleaseReady(_Case):
    def test_a_full_production_run_is_release_ready(self):
        api, run = self.to_g4()
        state = self.decide(api, run.run_id)
        self.assertEqual(state.status, RunStatus.COMPLETED, state.message)
        report = api.quality(state)
        self.assertEqual(report["class"], "release")
        self.assertTrue(report["release_ready"])
        self.assertEqual(report["not_yet_enforced"], [])
        self.assertEqual({r.quality for refs in state.artifacts.values() for r in refs},
                         {"release"})
        text = wgf.render_quality(report)
        self.assertIn("Quality: release-ready (tier release", text)
        self.assertNotIn("not enforced", text)  # quality-gate is in the workflow (WS-7)

    def test_a_run_waiting_at_g4_is_not_release_ready(self):
        api, state = self.to_g4()
        report = api.quality(state)
        self.assertEqual(report["class"], "release")
        self.assertFalse(report["release_ready"])


class ReplanRunsTheStepsAfterIt(_Case):
    def test_new_game_run_after_a_replan_rebuilds_and_reverifies(self):
        """The per-platform agent's finding: after `wgf tech-plan --run X --force`,
        `wgf new-game --run X` skipped init..verify and asked G4 again on the old build."""
        api, run = self.to_g4()
        old_qa = run.latest_of_type("qa-report")
        state = api.run(RunRequest(run_id=run.run_id, scope="tech-plan", force=True))
        mark = len(state.trail)
        state = api.run(RunRequest(run_id=run.run_id, scope="new-game"))
        self.assertEqual((state.status, state.cursor), (RunStatus.WAITING, "prototype-review"),
                         state.message)
        again = self.executed(state, mark)
        for step_id in ("tech-plan-review", "init", "greybox", "greybox-playability", "assets",
                        "develop") + FLOOR_STEPS:
            self.assertIn(step_id, again, step_id)
        self.assertGreater(state.latest_of_type("qa-report").version, old_qa.version)
        consumed = state.steps["prototype-review"].consumed
        newest = state.latest_of_type("qa-report")
        self.assertIn(f"{newest.id}@v{newest.version}", consumed)

    def test_nothing_redone_is_still_skipped(self):
        api, run = self.to_g4()
        state = self.decide(api, run.run_id)
        mark = len(state.trail)
        state = api.run(RunRequest(run_id=run.run_id, scope="plan"))
        self.assertEqual(self.executed(state, mark), [])


class FloorAtTheGate(_Case):
    def _new_build_without_its_checks(self):
        api, run = self.to_g4()
        state = api.run(RunRequest(run_id=run.run_id, scope="develop", force=True))
        self.assertEqual(self.executed(state)[-1], "develop")
        return api, state

    def test_g4_run_by_name_after_a_new_build_stops_at_the_floor(self):
        """`wgf develop --run X --force`, then `wgf prototype-review --run X`: G4 used to be
        asked again with the old build's reports in front of the person."""
        api, state = self._new_build_without_its_checks()
        state = api.run(RunRequest(run_id=state.run_id, scope="prototype-review"))
        self.assertEqual(state.status, RunStatus.BLOCKED)
        self.assertEqual(state.blocked_reason["kind"], quality.FLOOR)
        self.assertEqual(state.blocked_reason["step"], "prototype-review")
        problems = " ".join(state.blocked_reason["problems"])
        for step_id in FLOOR_STEPS:
            self.assertIn(step_id, problems)
        self.assertEqual(state.steps["prototype-review"].status, StepStatus.BLOCKED)
        self.assertIsNone(api.pending(state))
        self.assertFalse(api.quality(state)["release_ready"])
        # The way on runs the checks: the whole workflow again, skipping only what is current.
        mark = len(state.trail)
        state = api.run(RunRequest(run_id=state.run_id, scope="new-game"))
        self.assertEqual((state.status, state.cursor), (RunStatus.WAITING, "prototype-review"),
                         state.message)
        again = self.executed(state, mark)
        for step_id in FLOOR_STEPS:
            self.assertIn(step_id, again)
        self.assertNotIn("design", again)

    def test_verify_alone_on_a_new_build_does_not_reach_g4(self):
        api, state = self._new_build_without_its_checks()
        state = api.run(RunRequest(run_id=state.run_id, scope="verify"))
        self.assertEqual(self.executed(state)[-1], "verify")
        state = api.run(RunRequest(run_id=state.run_id, scope="prototype-review"))
        self.assertEqual(state.status, RunStatus.BLOCKED)
        problems = " ".join(state.blocked_reason["problems"])
        for step_id in ("playability", "production-quality", "visual-qa",
                        "content-sufficiency", "review", "sdk-review", "quality-gate"):
            self.assertIn(step_id, problems)
        # verify ran on the new build: it is not a problem (the quality gate after it is).
        self.assertFalse([p for p in state.blocked_reason["problems"]
                          if p.startswith("verify ")])
        self.assertNotIn("release", self.executed(state))

    def test_a_failed_latest_check_is_not_current(self):
        api, run = self.to_g4()
        state = api.store.load(run.run_id)
        definition = api.definition_for(state)
        self.assertIsNone(quality.current(state, definition, "visual-qa"))
        state.steps["visual-qa"].status = StepStatus.FAILED
        self.assertIn("FAILED", quality.current(state, definition, "visual-qa"))

    def test_a_fresh_release_slice_does_not_draft(self):
        api = self.api()
        state = api.run(RunRequest(scope="release"))
        self.assertEqual(state.status, RunStatus.BLOCKED)
        self.assertEqual(state.blocked_reason["kind"], quality.FLOOR)
        self.assertIsNone(state.latest_artifact("release-manifest"))


class DevelopmentNeverRelease(_Case):
    def _released(self, api):
        api, run = self.to_g4(api)
        state = self.decide(api, run.run_id)
        self.assertEqual(state.status, RunStatus.COMPLETED, state.message)
        return api, state

    def assertDevelopment(self, api, state, why):
        report = api.quality(state)
        self.assertEqual(report["class"], "development")
        self.assertFalse(report["release_ready"])
        self.assertTrue(any(why in r for r in report["reasons"]), report["reasons"])
        self.assertIn("development - never a release", wgf.render_quality(report))

    def test_tier_mvp_marks_the_run_and_every_artifact(self):
        api, state = self._released(self.api({"strategy": {"quality_tier": "mvp"}}))
        self.assertDevelopment(api, state, "quality tier mvp")
        self.assertEqual({r.quality for refs in state.artifacts.values() for r in refs},
                         {"development"})

    def test_a_weakening_configuration_at_start(self):
        api, state = self._released(self.api({"release": {"allow_unreviewed": True}}))
        self.assertDevelopment(api, state, "allow_unreviewed")

    def test_a_weakening_configuration_on_a_later_resume_downgrades_the_run(self):
        api, run = self.to_g4()
        self.assertEqual(api.quality(run)["class"], "release")
        later = self.api({"visualqa": {"judge": {"kind": "baseline"}}})
        state = self.decide(later, run.run_id)
        self.assertEqual(state.status, RunStatus.COMPLETED, state.message)
        downgraded = self.events(later, run.run_id, Events.QUALITY_DOWNGRADED)
        self.assertEqual(len(downgraded), 1)
        self.assertDevelopment(later, state, "baseline")
        # Written after the downgrade: development. Before it: release.
        self.assertEqual(state.latest_of_type("release-manifest").quality, "development")
        self.assertEqual(state.latest_of_type("qa-report").quality, "release")
        # Restoring the configuration does not raise the class back.
        state = api.run(RunRequest(run_id=run.run_id, scope="release", force=True))
        self.assertEqual(api.quality(state)["class"], "development")

    def test_a_development_run_is_never_submitted(self):
        api, state = self._released(self.api({"strategy": {"quality_tier": "mvp"},
                                              "publish": {"mode": "live"}}))
        state = api.run(RunRequest(run_id=state.run_id, scope="publish"))
        self.assertEqual((state.status, state.cursor), (RunStatus.WAITING, "publish-review"),
                         state.message)
        state = api.run(RunRequest(resume=state.run_id, decision="publish",
                                   decided_by="human"))
        self.assertEqual(state.status, RunStatus.BLOCKED)
        self.assertEqual(state.blocked_reason["kind"], quality.FLOOR)
        self.assertIn("release-class", " ".join(state.blocked_reason["problems"]))
        self.assertEqual(state.steps["submit"].executions, 0)

    def test_a_development_run_may_rehearse_a_dry_run_submit(self):
        api, state = self._released(self.api({"strategy": {"quality_tier": "mvp"}}))
        state = api.run(RunRequest(run_id=state.run_id, scope="publish"))
        state = api.run(RunRequest(resume=state.run_id, decision="publish",
                                   decided_by="human"))
        self.assertEqual(state.status, RunStatus.COMPLETED, state.message)

    def test_a_release_run_reaches_submit(self):
        api, state = self._released(self.api({"publish": {"mode": "live"}}))
        state = api.run(RunRequest(run_id=state.run_id, scope="publish"))
        state = api.run(RunRequest(resume=state.run_id, decision="publish",
                                   decided_by="human"))
        self.assertEqual(state.status, RunStatus.COMPLETED, state.message)
        self.assertGreater(state.steps["submit"].executions, 0)

    def test_a_workflow_the_factory_does_not_ship_is_development(self):
        source = os.path.join(SCRIPTS, "..", "core", "workflows", "new-game.workflow.yaml")
        folder = os.path.join(self.scratch, "flows")
        os.makedirs(folder)
        with open(source, encoding="utf-8") as handle:
            text = handle.read()
        path = os.path.join(folder, "new-game.workflow.yaml")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        api = self.api(workflow=path)
        state = api.run(RunRequest())
        self.assertEqual(state.params["quality"]["class"], "development")
        self.assertTrue(any("not from the Factory" in r
                            for r in state.params["quality"]["reasons"]))


class _DesignModuleAPI(_PlaceholderAPI):
    """Placeholders, except strategy and design: the real wgf_strategy (which commits the
    run's tier) and wgf_design (whose configured author the preflight reads). The run is
    refused before anything executes."""

    def registry(self, use_mock, load_modules=True):
        registry = super().registry(use_mock, load_modules)
        import wgf_design
        import wgf_strategy
        wgf_design.register(registry)
        wgf_strategy.register(registry)
        return registry


class Preflight(_Case):
    """A run the configuration cannot take to its tier is refused before it starts."""

    def api(self, extra=None, workflow=None):
        api = super().api(extra, workflow)
        return _DesignModuleAPI(config=api.config, store_dir=self.store_dir)

    def test_the_built_in_design_author_at_release_tier_starts_no_run(self):
        for author in (None, "archetype", "genre-seed"):
            api = self.api()
            api.config.data["design"] = {"author": author} if author else {}
            with self.assertRaisesRegex(ConfigError, "design.author") as raised:
                api.run(RunRequest(idea="a merge puzzle"))
            self.assertIn("quality_tier to mvp", str(raised.exception))
            self.assertIn("agent", str(raised.exception))
            self.assertEqual(api.runs(), [], author)
            self.assertTrue(api.preflight()["refused"], author)

    def test_mvp_tier_or_the_agent_author_or_a_slice_without_design_starts(self):
        api = self.api({"strategy": {"quality_tier": "mvp"}})
        api.config.data["design"] = {}
        state = api.run(RunRequest())
        self.assertEqual(state.params["quality"]["class"], "development")
        api = self.api()
        self.assertEqual(api.preflight()["refused"], [])
        api.config.data["design"] = {}
        state = api.run(RunRequest(scope="verify"))
        self.assertNotEqual(state.status, RunStatus.FAILED)

    def test_a_mock_run_is_not_refused(self):
        api = WorkflowAPI(config=FactoryConfig({"storage": {"fsync": False}}),
                          store_dir=self.store_dir)
        state = api.run(RunRequest(mock=True))
        self.assertEqual(state.cursor, "prototype-review")

    def test_a_placeholder_design_step_reads_no_author(self):
        api = _PlaceholderAPI(config=FactoryConfig({"storage": {"fsync": False},
                                                    "checkpoints": dict(GATES)}),
                              store_dir=self.store_dir)
        state = api.run(RunRequest())
        self.assertEqual(state.cursor, "prototype-review", state.message)


class _ShortfallTechPlan(mock.MockTechPlanStep):
    """The placeholder tech plan, with a develop budget capped below the plan's need."""

    def execute(self, inputs, context):
        result = super().execute(inputs, context)
        for output in result.artifacts:
            if output.type == "tech-plan":
                output.content.setdefault("dev_plan", {})["develop_budget"] = {
                    "sessions": 23, "cost": 115.0,
                    "basis": {"build_hours": 60.0, "tasks": ["CONTENT-001"],
                              "session_task_hours": 3.0, "rework_sessions": 3,
                              "session_cost": 5.0},
                    "cap": {"max_sessions": 12, "max_cost": 60},
                    "shortfall": {"sessions": 11, "cost": 55.0}}
                provenance.seal(output.content)
        return result


class _ShortfallAPI(_PlaceholderAPI):
    def registry(self, use_mock, load_modules=True):
        registry = super().registry(use_mock, load_modules)
        registry.register(_ShortfallTechPlan.type, _ShortfallTechPlan)
        return registry


class PlannedShortfallWaitsForAPerson(_Case):
    """WS-3 records a develop budget capped below the release plan's need as a planned
    shortfall shown at G3; G3 auto- or timeout-approved would put it in front of nobody."""

    def shortfall_api(self, checkpoints):
        data = {"storage": {"fsync": False}, "checkpoints": checkpoints,
                "design": dict(AUTHOR)}
        return _ShortfallAPI(config=FactoryConfig(data), store_dir=self.store_dir)

    def test_auto_approve_does_not_approve_a_g3_with_a_shortfall(self):
        api = self.shortfall_api({"auto_approve": ["G2", "G3"]})
        state = api.run(RunRequest())
        self.assertEqual((state.status, state.cursor), (RunStatus.WAITING, "tech-plan-review"),
                         state.message)
        self.assertIn("planned shortfall", state.steps["tech-plan-review"].message)
        pending = api.pending(state)
        self.assertEqual(pending["gate"], "G3")
        self.assertTrue(pending["held_for_person"])
        self.assertIn("Held:   G3 waits for a person", wgf.render_status(
            state, api.definition_for(state), pending=pending))
        # Automation answering it is refused; a person's approval passes it.
        state = api.run(RunRequest(resume=state.run_id, decision="approve",
                                   decided_by="automation"))
        self.assertEqual((state.status, state.cursor), (RunStatus.WAITING, "tech-plan-review"))
        state = api.run(RunRequest(resume=state.run_id, decision="approve",
                                   decided_by="human", note="cap accepted"))
        self.assertEqual(state.cursor, "prototype-review", state.message)
        self.assertEqual(state.decisions["tech-plan-review"]["decided_by"], "human")

    def test_a_timeout_window_does_not_approve_it_either(self):
        api = self.shortfall_api({"auto_approve": ["G2"], "timeout_auto_approve": {"G3": "1s"}})
        state = api.run(RunRequest())
        self.assertEqual(state.cursor, "tech-plan-review")
        self.assertIsNone(api.pending(state)["timeout"])
        time.sleep(1.2)
        state = api.run(RunRequest(resume=state.run_id))
        self.assertEqual((state.status, state.cursor), (RunStatus.WAITING, "tech-plan-review"))
        self.assertNotIn("tech-plan-review", state.decisions)

    def test_without_a_shortfall_g3_still_auto_approves(self):
        api, state = self.to_g4()
        self.assertEqual(state.steps["tech-plan-review"].status, StepStatus.SUCCESS)
        self.assertEqual(state.steps["tech-plan-review"].executions, 1)
        self.assertNotIn("tech-plan-review", state.decisions)  # nobody was asked


class ForceAsksAgain(_Case):
    def test_forcing_g4_asks_again(self):
        """`--force` re-executes a gate; it never marks one passed without a person."""
        api, run = self.to_g4()
        state = self.decide(api, run.run_id)
        self.assertEqual(state.status, RunStatus.COMPLETED, state.message)
        state = api.run(RunRequest(run_id=run.run_id, scope="prototype-review", force=True))
        self.assertEqual((state.status, state.cursor), (RunStatus.WAITING, "prototype-review"))
        self.assertEqual(api.pending(state)["gate"], "G4")
        with self.assertRaisesRegex(EngineError, "prototype-review is WAITING"):
            api.run(RunRequest(run_id=run.run_id, scope="release", force=True))


class MockStaysAllowed(_Case):
    def test_a_mock_run_runs_and_is_development(self):
        api = WorkflowAPI(config=FactoryConfig({"storage": {"fsync": False}}),
                          store_dir=self.store_dir)
        run = api.run(RunRequest(mock=True))
        self.assertEqual((run.status, run.cursor), (RunStatus.WAITING, "prototype-review"))
        state = self.decide(api, run.run_id)
        self.assertEqual(state.status, RunStatus.COMPLETED, state.message)
        report = api.quality(state)
        self.assertEqual(report["class"], "development")
        self.assertFalse(report["release_ready"])
        self.assertTrue(any("mock" in r for r in report["reasons"]))

    def test_a_mock_slice_is_not_held_to_the_floor(self):
        api = WorkflowAPI(config=FactoryConfig({"storage": {"fsync": False}}),
                          store_dir=self.store_dir)
        state = api.run(RunRequest(mock=True, scope="release"))
        self.assertNotEqual(state.blocked_reason and state.blocked_reason.get("kind"),
                            quality.FLOOR)


class LegacyRuns(_Case):
    def test_a_run_without_a_snapshot_is_development_and_held_to_the_current_floor(self):
        params = {}
        klass, reasons = quality.run_class(params, [])
        self.assertEqual(klass, "development")
        self.assertIn("no quality snapshot", reasons[0])
        held = quality.effective(params, quality.load_policy())
        self.assertIn("visual-qa", held["required_steps"])

    def test_a_pending_step_the_current_policy_enforces_is_enforced(self):
        policy = quality.load_policy()
        taken = {"required_steps": ["content-sufficiency"], "pending": ["content-sufficiency"]}
        current = dict(policy, pending=[])
        held = quality.effective({"quality": dict(taken, tier="release", **{"class": "release"})},
                                 current)
        self.assertEqual(held["pending"], [])
        self.assertIn("content-sufficiency", held["required_steps"])


if __name__ == "__main__":
    unittest.main()

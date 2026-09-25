"""The strategy module (scripts/wgf_strategy): opportunity in, draft title-strategy out.

  Planner          the domain rules, as a pure function: platforms, monetization, scope,
                   criteria, risks and assumptions, and the refusals
  StepUnit         `execute` with a fake inputs and context: each StepResult it can return
  ThroughEngine    registered from config and run in the real new-game workflow, with the
                   other steps as placeholders: it stops at strategy-review (G2), design
                   consumes its output after approval, and a rejection blocks the run
  Schema           emitted artifacts validate with ajv against title-strategy.schema.json

Deterministic and offline: fixed clock, profiles from core/reference/platforms/, no network.
The ajv test uses the cached npx packages CLAUDE.md names and skips if they cannot run
(or with WGF_SKIP_AJV=1).

Run from the web-game-factory repository root:

    python -m unittest discover scripts/tests
"""

import copy
import datetime
import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
sys.path.insert(0, SCRIPTS)

from wgf_strategy import Policy, StrategyRefused, StrategyStep, plan_strategy  # noqa: E402
from wgf_strategy.profiles import load_profiles  # noqa: E402
from wgflib import paths  # noqa: E402
from wgflib.guards import GuardContext, evaluate_guard  # noqa: E402
from wgflib.hashing import content_hash  # noqa: E402
from wgflib.workflow.api import RunRequest, WorkflowAPI  # noqa: E402
from wgflib.workflow.config import FactoryConfig  # noqa: E402
from wgflib.workflow.contracts import ArtifactContracts  # noqa: E402
from wgflib.workflow.definition import StepDefinition, load_definition  # noqa: E402
from wgflib.workflow.model import ArtifactRef, RunStatus, StepOutcome, StepStatus  # noqa: E402
from wgflib.workflow.step import StepInputs  # noqa: E402

OPPORTUNITY = os.path.join(paths.OPPORTUNITIES, "opp-001", "opportunity.json")
FIXED = datetime.datetime(2026, 9, 1, 10, 0, 0, tzinfo=datetime.timezone.utc)
PROFILES = load_profiles()

# Every placeholder step except strategy, so the real module runs inside new-game.
PLACEHOLDERS = textwrap.dedent('''
    from wgflib.workflow import mock


    def register(registry):
        for step_class in mock.MOCK_STEPS:
            if step_class.type != "strategy":
                registry.register(step_class.type, step_class)
''')


def opportunity(**changes):
    with open(OPPORTUNITY, encoding="utf-8") as handle:
        body = json.load(handle)
    for dotted, value in changes.items():
        target = body
        keys = dotted.split("__")
        for key in keys[:-1]:
            target = target.setdefault(key, {})
        target[keys[-1]] = value
    return body


def plan(opp=None, policy=None, profiles=None):
    return plan_strategy(opp or opportunity(), PROFILES if profiles is None else profiles,
                         "neon-drift", policy)


# -- the planner -------------------------------------------------------------------------


class Planner(unittest.TestCase):
    def test_every_requested_decision_is_made(self):
        body = plan()
        concept, scope = body["concept"], body["production_scope"]
        self.assertTrue(concept["gameplay_direction"])
        self.assertEqual(concept["control_scheme"], "one-touch")
        self.assertTrue(concept["replayability"].startswith("Score chase"))
        self.assertEqual(body["audience"]["type"], "casual")
        self.assertEqual(body["session"]["target_seconds"], 210)
        self.assertEqual(body["monetization"]["class"], "rewarded-led")
        self.assertEqual(scope["technical_complexity"], "medium")  # audio sync
        self.assertEqual(scope["asset_complexity"], "low")
        self.assertEqual(scope["estimate_days"], 11)
        self.assertEqual(body["timebox_days"], 11)
        for key in ("mvp", "out_of_scope", "prototype_must_prove", "success_criteria",
                    "kill_criteria", "risks", "assumptions"):
            self.assertTrue(body[key], key)

    def test_one_required_platform_chosen_by_audience_fit(self):
        body = plan()
        roles = {p["id"]: p["role"] for p in body["platform_set"]}
        self.assertEqual(roles, {"yandex": "required", "crazygames": "optional"})
        for entry in body["platform_set"]:
            self.assertEqual(entry["profile_version"], PROFILES[entry["id"]]["version"])

        # The same concept for a US audience: CrazyGames fits better and becomes primary.
        us = plan(opportunity(audience__regions=["us", "gb"]))
        roles = {p["id"]: p["role"] for p in us["platform_set"]}
        self.assertEqual(roles, {"yandex": "optional", "crazygames": "required"})

    def test_sdk_requirements_and_constraints_come_from_the_profiles(self):
        compat = {c["id"]: c for c in plan()["platform_compatibility"]}
        yandex = compat["yandex"]
        self.assertEqual(yandex["sdk"]["id"], "yandex")
        for feature in ("init", "loading-progress", "rewarded", "interstitial", "cloud-save"):
            self.assertIn(feature, yandex["sdk"]["features"])
        self.assertIn("Locales required: ru", yandex["constraints"])
        self.assertIn("Bundle at most 100 MB", yandex["constraints"])

        standalone = plan(opportunity(candidate_platforms=["generic-web"],
                                      monetization_hypothesis={"primary": "none"}))
        self.assertEqual(standalone["platform_compatibility"][0]["sdk"],
                         {"id": "none", "features": []})
        self.assertEqual(standalone["monetization"], {"class": "none", "placements": []})

    def test_a_platform_that_cannot_carry_the_monetization_is_left_out(self):
        body = plan(opportunity(candidate_platforms=["gamevui", "yandex"]))
        self.assertEqual([p["id"] for p in body["platform_set"]], ["yandex"])
        gamevui = next(c for c in body["platform_compatibility"] if c["id"] == "gamevui")
        self.assertFalse(gamevui["compatible"])
        self.assertTrue(any("rewarded" in issue for issue in gamevui["issues"]))
        self.assertTrue(any("gamevui" in item for item in body["out_of_scope"]))

    def test_unsupported_monetization_is_reclassified_not_ignored(self):
        body = plan(opportunity(candidate_platforms=["crazygames", "poki"],
                                monetization_hypothesis={"primary": "iap",
                                                         "secondary": ["rewarded"]}))
        self.assertEqual(body["monetization"]["class"], "rewarded-led")
        self.assertTrue(any("reclassified" in r["description"] for r in body["risks"]))

    def test_unknown_platforms_are_recorded_and_dropped(self):
        body = plan(opportunity(candidate_platforms=["nowhere", "yandex"]))
        self.assertEqual([p["id"] for p in body["platform_set"]], ["yandex"])
        self.assertFalse(body["platform_compatibility"][0]["compatible"])

    def test_platform_sprawl_is_capped(self):
        body = plan(opportunity(candidate_platforms=["yandex", "crazygames", "poki"]),
                    Policy(max_platforms=2))
        self.assertEqual(len(body["platform_set"]), 2)
        self.assertEqual(sum(p["role"] == "required" for p in body["platform_set"]), 1)
        self.assertTrue(any(i.startswith("Platforms beyond the set") for i in body["out_of_scope"]))

    def test_scope_is_fitted_to_the_timebox_not_the_other_way_round(self):
        body = plan(opportunity(estimates={"dev_speed_days": 19, "scope_complexity": "l",
                                           "session_seconds": 900}))
        self.assertEqual(body["timebox_days"], 14)
        self.assertEqual(body["production_scope"]["estimate_days"], 19)
        self.assertEqual(body["session"]["target_seconds"], 300)
        decisions = " ".join(body["production_scope"]["scope_decisions"])
        self.assertIn("timebox is held at 14", decisions)
        self.assertIn("Target session cut", decisions)

        small = plan(opportunity(estimates={"dev_speed_days": 3}))
        self.assertEqual(small["timebox_days"], 7)

    def test_rapid_production_bias(self):
        body = plan()
        scope = body["production_scope"]
        self.assertLessEqual(scope["asset_budget"]["max_unique_assets"], 30)
        self.assertTrue(any("SDK adapter" in s for s in scope["reusable_systems"]))
        self.assertTrue(any("One control scheme" in d for d in scope["scope_decisions"]))
        excluded = " ".join(body["out_of_scope"])
        for word in ("Multiplayer", "Metagame", "IAP", "second mode"):
            self.assertIn(word, excluded)
        self.assertLessEqual(body["session"]["target_seconds"], 300)

    def test_a_concept_that_needs_an_excluded_system_keeps_it_and_says_so(self):
        body = plan(opportunity(concept__core_mechanic="online multiplayer 3d physics brawls"))
        self.assertNotIn("Multiplayer", " ".join(body["out_of_scope"]))
        self.assertEqual(body["production_scope"]["technical_complexity"], "high")
        high = [r for r in body["risks"] if r["severity"] == "high" and r["origin"] == "strategy"]
        self.assertTrue(high)

    def test_opportunity_risks_are_carried_and_high_ones_must_be_proved(self):
        body = plan()
        carried = [r for r in body["risks"] if r["origin"] == "opportunity"]
        self.assertEqual(len(carried), 2)
        self.assertTrue(any("Audio latency" in p for p in body["prototype_must_prove"]))

    def test_assumptions_are_hypotheses_that_name_their_refutation(self):
        for assumption in plan()["assumptions"]:
            self.assertIn(assumption["tier"], ("hypothesis", "derived"))
            self.assertTrue(assumption["invalidated_by"])

    def test_kill_criteria_are_measurable_expressions(self):
        body = plan()
        for criterion in body["kill_criteria"] + body["success_criteria"]:
            self.assertEqual(set(criterion["when"]), {"left", "op", "right"})
            self.assertTrue(criterion["rationale"])

    def test_refusals(self):
        cases = {
            "xl scope": opportunity(estimates={"scope_complexity": "xl"}),
            "too long": opportunity(estimates={"dev_speed_days": 30}),
            "rejected": opportunity(state="rejected"),
            "no concept": opportunity(concept={"genre": "arcade"}),
            "no profiles": opportunity(candidate_platforms=["nowhere"]),
        }
        for name, opp in cases.items():
            with self.subTest(name), self.assertRaises(StrategyRefused):
                plan(opp)
        with self.assertRaises(StrategyRefused):
            Policy(bogus=1)
        with self.assertRaises(StrategyRefused):
            Policy(target_timebox_days=30)

    def test_deterministic(self):
        self.assertEqual(plan(), plan())
        self.assertEqual(json.dumps(plan(), sort_keys=True), json.dumps(plan(), sort_keys=True))


# -- the step ----------------------------------------------------------------------------


class FakeLogger:
    def __init__(self):
        self.records = []

    def __getattr__(self, level):
        return lambda message, **fields: self.records.append((level, message, fields))


class FakeContext:
    def __init__(self, project_id="neon-drift", execution=1, visit=1):
        self.project_id = project_id
        self.execution = execution
        self.visit = visit
        self.run_id = "run-1"
        self.current_step = "strategy"
        self.logger = FakeLogger()

    @property
    def idempotency_key(self):
        return f"{self.run_id}:{self.current_step}:{self.visit}"


def fake_inputs(body=None, schema_version="1.0.0"):
    if body is None:
        return StepInputs({}, lambda ref: None, ["opportunity"])
    ref = ArtifactRef(id="opportunity", type="opportunity", version=1, location="x",
                      checksum="x", content_hash=body["provenance"]["content_hash"],
                      schema_version=schema_version)
    return StepInputs({"opportunity": ref}, lambda _ref: copy.deepcopy(body), [])


def step(params=None):
    definition = StepDefinition.__new__(StepDefinition)
    definition.id, definition.type = "strategy", "strategy"
    definition.params = params or {}
    definition.inputs, definition.outputs = ["opportunity"], ["title-strategy"]
    instance = StrategyStep(definition)
    instance.clock = lambda: FIXED
    return instance


class StepUnit(unittest.TestCase):
    def test_success_emits_a_contract_valid_draft(self):
        result = step().execute(fake_inputs(opportunity()), FakeContext())
        self.assertEqual(result.outcome, StepOutcome.SUCCESS)
        (output,) = result.artifacts
        artifact = output.content
        self.assertEqual(output.type, "title-strategy")
        self.assertEqual(ArtifactContracts()("title-strategy", artifact), [])
        provenance = artifact["provenance"]
        self.assertEqual(provenance["status"], "draft")  # G2 decides, not the step
        self.assertEqual(provenance["artifact_id"], "wgf:title-strategy:neon-drift:20260901-01")
        self.assertEqual(provenance["inputs"][0]["content_hash"],
                         opportunity()["provenance"]["content_hash"])
        self.assertEqual(provenance["content_hash"], content_hash(artifact))
        self.assertEqual(output.metadata["required_platform"], "yandex")

    def test_title_id_falls_back_to_the_opportunity(self):
        result = step().execute(fake_inputs(opportunity(title_id=None)), FakeContext(None))
        self.assertEqual(result.artifacts[0].content["title_id"], "neon-drift")

    def test_missing_opportunity_waits(self):
        result = step().execute(fake_inputs(), FakeContext())
        self.assertEqual(result.outcome, StepOutcome.WAITING_FOR_INPUT)

    def test_an_unreadable_major_version_is_refused(self):
        result = step().execute(fake_inputs(opportunity(), "2.0.0"), FakeContext())
        self.assertEqual((result.outcome, result.retryable), (StepOutcome.FAILED, False))

    def test_a_refused_plan_is_a_permanent_failure(self):
        opp = opportunity(estimates={"scope_complexity": "xl"})
        result = step().execute(fake_inputs(opp), FakeContext())
        self.assertEqual((result.outcome, result.retryable), (StepOutcome.FAILED, False))
        self.assertIn("rapid-production envelope", result.error)
        self.assertEqual(result.artifacts, [])

    def test_bad_policy_params_are_a_permanent_failure(self):
        result = step({"max_platforms": "many"}).execute(fake_inputs(opportunity()),
                                                        FakeContext())
        self.assertEqual((result.outcome, result.retryable), (StepOutcome.FAILED, False))

    def test_policy_params_apply(self):
        opp = opportunity(estimates={"dev_speed_days": 12})
        result = step({"target_timebox_days": 10}).execute(fake_inputs(opp), FakeContext())
        self.assertEqual(result.artifacts[0].content["timebox_days"], 10)

    def test_re_execution_with_the_same_key_is_idempotent(self):
        first = step().execute(fake_inputs(opportunity()), FakeContext())
        second = step().execute(fake_inputs(opportunity()), FakeContext())
        self.assertEqual(first.artifacts[0].content, second.artifacts[0].content)

    def test_g2_predicates_are_green(self):
        artifact = step().execute(fake_inputs(opportunity()), FakeContext()).artifacts[0].content

        class Entity:
            def artifact(self, artifact_type):
                assert artifact_type == "title-strategy"
                return artifact

        context = GuardContext(Entity())
        for guard in ("kill_criteria_defined", "timebox_set"):
            self.assertIs(evaluate_guard(guard, context).value, True, guard)


# -- through the engine ------------------------------------------------------------------


class ThroughEngine(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.mkdtemp(prefix="wgf-strategy-")
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)
        modules = os.path.join(self.scratch, "modules")
        os.makedirs(modules)
        with open(os.path.join(modules, "wgf_test_placeholders.py"), "w") as handle:
            handle.write(PLACEHOLDERS)
        sys.path.insert(0, modules)
        self.addCleanup(sys.path.remove, modules)
        self.addCleanup(sys.modules.pop, "wgf_test_placeholders", None)
        patcher = mock.patch.object(StrategyStep, "clock", staticmethod(lambda: FIXED))
        patcher.start()
        self.addCleanup(patcher.stop)

    def api(self, auto_approve=()):
        config = FactoryConfig({
            "steps": {"modules": ["wgf_test_placeholders", "wgf_strategy"]},
            "checkpoints": {"auto_approve": list(auto_approve)},
            "storage": {"fsync": False},
            "execution": {"delay_seconds": 0},
        })
        return WorkflowAPI(config=config, store_dir=os.path.join(self.scratch, "store"))

    def test_the_real_module_is_the_one_that_runs(self):
        registry = self.api().registry(use_mock=False)
        self.assertIs(registry.resolve("strategy"), StrategyStep)
        self.assertIsNot(registry.resolve("design"), StrategyStep)

    def test_strategy_stops_at_g2_and_design_consumes_it_after_approval(self):
        api = self.api()
        state = api.run(RunRequest(project_id="neon-drift"))
        self.assertEqual(state.status, RunStatus.WAITING)
        self.assertEqual(state.steps["strategy-review"].status, StepStatus.WAITING)
        self.assertNotIn("design", [t["step"] for t in state.trail])  # never bypassed

        ref = state.latest_artifact("title-strategy")
        artifact = api.store.read_artifact(state.run_id, ref)
        self.assertEqual(ArtifactContracts()("title-strategy", artifact), [])
        self.assertEqual(artifact["provenance"]["status"], "draft")
        self.assertEqual(ref.schema_version, "1.1.0")
        self.assertEqual(state.steps["strategy"].consumed, ["opportunity@v1"])

        final = api.run(RunRequest(resume=state.run_id, decision="approve"))
        self.assertEqual(final.status, RunStatus.WAITING)  # G3, after the tech plan
        final = api.run(RunRequest(resume=state.run_id, decision="approve"))
        self.assertEqual(final.status, RunStatus.COMPLETED)
        self.assertEqual(final.steps["design"].consumed, ["title-strategy@v1"])
        design = api.store.read_artifact(final.run_id, final.latest_artifact("game-design"))
        pinned = {i["artifact_type"]: i["content_hash"] for i in design["provenance"]["inputs"]}
        self.assertEqual(pinned["title-strategy"], artifact["provenance"]["content_hash"])

    def test_a_rejected_strategy_blocks_the_run_before_design(self):
        api = self.api()
        state = api.run(RunRequest(project_id="neon-drift"))
        final = api.run(RunRequest(resume=state.run_id, decision="reject"))
        self.assertEqual(final.status, RunStatus.BLOCKED)
        self.assertNotIn("design", [t["step"] for t in final.trail])

    def test_plan_group_needs_an_opportunity(self):
        state = self.api().run(RunRequest(scope="plan", project_id="neon-drift"))
        self.assertEqual(state.status, RunStatus.WAITING)
        self.assertEqual(state.steps["strategy"].status, StepStatus.WAITING)

    def test_a_configured_auto_approval_is_the_only_way_past_g2(self):
        final = self.api(auto_approve=["G2", "G3"]).run(RunRequest(project_id="neon-drift"))
        self.assertEqual(final.status, RunStatus.COMPLETED)

    def test_the_workflow_still_declares_the_checkpoint_after_strategy(self):
        definition = load_definition("new-game")
        ids = definition.step_ids
        review = next(s for s in definition.steps if s.id == "strategy-review")
        self.assertEqual(ids[ids.index("strategy") + 1], "strategy-review")
        self.assertEqual(review.params["gate"], "G2")


# -- schema ------------------------------------------------------------------------------


class Schema(unittest.TestCase):
    AJV = ["npx", "--yes", "-p", "ajv-cli@5", "-p", "ajv-formats@2", "ajv", "validate",
           "-s", "core/artifacts/title-strategy.schema.json",
           "-r", "core/artifacts/shared/*.schema.json",
           "-c", "ajv-formats", "--spec=draft2020", "--strict=false"]

    def test_emitted_artifacts_validate_with_ajv(self):
        if os.environ.get("WGF_SKIP_AJV") == "1" or not shutil.which("npx"):
            self.skipTest("ajv unavailable (npx missing or WGF_SKIP_AJV set)")
        scratch = tempfile.mkdtemp(prefix="wgf-strategy-ajv-")
        self.addCleanup(shutil.rmtree, scratch, ignore_errors=True)
        variants = {
            "default": opportunity(),
            "capped": opportunity(estimates={"dev_speed_days": 19, "session_seconds": 900}),
            "standalone": opportunity(candidate_platforms=["generic-web"],
                                      monetization_hypothesis={"primary": "none"}),
            "reclassified": opportunity(candidate_platforms=["crazygames", "gamevui", "x"],
                                        monetization_hypothesis={"primary": "iap"}),
            "complex": opportunity(concept__core_mechanic="online multiplayer 3d brawls"),
        }
        command = list(self.AJV)
        for name, opp in variants.items():
            result = step().execute(fake_inputs(opp), FakeContext())
            self.assertEqual(result.outcome, StepOutcome.SUCCESS, name)
            path = os.path.join(scratch, f"{name}.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(result.artifacts[0].content, handle)
            command += ["-d", path]
        try:
            run = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=180)
        except (OSError, subprocess.TimeoutExpired) as exc:
            self.skipTest(f"ajv could not run: {exc}")
        output = run.stdout + run.stderr
        if " valid" not in output and " invalid" not in output:
            self.skipTest(f"ajv could not run: {output.strip()[-200:]}")
        self.assertEqual(run.returncode, 0, output)
        self.assertEqual(output.count(" valid"), len(variants), output)


if __name__ == "__main__":
    unittest.main()

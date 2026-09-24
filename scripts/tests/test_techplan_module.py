"""The tech-plan module (scripts/wgf_techplan): game-design + title-strategy -> tech-plan.

Offline and deterministic: the designs come from the real design module (both engines) and
from the asset fixtures, the strategy is the worked example, the profiles are core's.

    python -m unittest discover scripts/tests

Full JSON Schema validation runs through wgflib.jsonschema_lite when it is present, and
through ajv when WGF_AJV=1 (needs npx).
"""

import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, HERE)

import wgf_techplan  # noqa: E402
from wgf_design.step import DesignStep  # noqa: E402
from wgf_techplan import (ENGINE_FOR_DIMENSION, EngineError, TechPlanStep,  # noqa: E402
                          select_engine)
from wgflib import guards, paths  # noqa: E402
from wgflib.hashing import content_hash  # noqa: E402
from wgflib.workflow import ArtifactOutput, StepResult, WorkflowStep  # noqa: E402
from wgflib.workflow.api import RunRequest, WorkflowAPI  # noqa: E402
from wgflib.workflow.checkpoint import irreversible_gates  # noqa: E402
from wgflib.workflow.config import FactoryConfig  # noqa: E402
from wgflib.workflow.contracts import ArtifactContracts  # noqa: E402
from wgflib.workflow.definition import load_definition  # noqa: E402
from wgflib.workflow.model import ArtifactRef, RunStatus, StepOutcome, StepStatus  # noqa: E402
from wgflib.workflow.step import StepInputs  # noqa: E402
from wgflib.yamllite import load_file  # noqa: E402

NOW = "2026-09-24T09:00:00Z"
STRATEGY_PATH = os.path.join(paths.TITLES, "neon-drift", "title-strategy.json")
ASSET_FIXTURES = os.path.join(HERE, "fixtures", "assets")


def load_json(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def rehash(artifact):
    artifact["provenance"]["content_hash"] = ""
    artifact["provenance"]["content_hash"] = content_hash(artifact)
    return artifact


def strategy():
    return load_json(STRATEGY_PATH)


class _Definition:
    def __init__(self, step_id, step_type, inputs, outputs, params=None):
        self.id, self.type, self.inputs, self.outputs = step_id, step_type, inputs, outputs
        self.params = params or {}


class Logger:
    def __init__(self):
        self.lines = []

    def __getattr__(self, level):
        return lambda message, **fields: self.lines.append((level, message, fields))


class Context:
    def __init__(self, config=None, project_id="neon-drift", execution=1):
        self.config = config or {}
        self.project_id = project_id
        self.execution = execution
        self.logger = Logger()


def designed(engine):
    """A game-design from the real design module, drawn for `engine`."""
    class Fixed(DesignStep):
        clock = staticmethod(lambda: NOW)

    step = Fixed(_Definition("design", "design", ["title-strategy"], ["game-design"],
                             {"engine": engine}))
    result = step.execute(inputs(**{"title-strategy": strategy()}), Context())
    assert result.outcome == StepOutcome.SUCCESS, result.error
    return result.artifacts[0].content


def fixture_design(name):
    """An asset-fixture design (no `engine` block), made a pipeline input of neon-drift."""
    design = load_json(os.path.join(ASSET_FIXTURES, name))
    design["title_id"] = "neon-drift"
    sequence = "01" if "2d" in name else "02"
    design["provenance"] = {"artifact_id": f"wgf:game-design:neon-drift:20260924-{sequence}",
                            "artifact_type": "game-design", "schema_version": "1.0.0",
                            "title_id": "neon-drift",
                            "produced_by": {"role": "game-designer", "actor": "automation"},
                            "produced_at": NOW, "inputs": [], "content_hash": "",
                            "status": "draft"}
    return rehash(design)


def inputs(**artifacts):
    refs = {}
    for artifact_type, content in artifacts.items():
        if content is None:
            continue
        refs[artifact_type] = ArtifactRef(
            id=artifact_type, type=artifact_type, version=1, location="mem", checksum="-",
            content_hash=content["provenance"]["content_hash"],
            schema_version=content["provenance"].get("schema_version", "1.0.0"))
    missing = [t for t, c in artifacts.items() if c is None]
    return StepInputs(refs, lambda ref: copy.deepcopy(artifacts[ref.type]), missing)


class Fixed(TechPlanStep):
    clock = staticmethod(lambda: NOW)


def plan(design, strat=None, config=None, context=None):
    step = Fixed(_Definition("tech-plan", "tech-plan", ["game-design", "title-strategy"],
                             ["tech-plan"]))
    strat = strategy() if strat is None else strat
    return step.execute(inputs(**{"game-design": design, "title-strategy": strat}),
                        context or Context(config))


class Entity:
    def __init__(self, **artifacts):
        self.artifacts = artifacts

    def artifact(self, artifact_type):
        return self.artifacts[artifact_type]


# -- engine selection ----------------------------------------------------------------------


class EngineFromTheDesign(unittest.TestCase):
    def test_a_2d_design_gets_pixijs_and_a_3d_design_gets_threejs(self):
        for engine in ("pixijs", "threejs"):
            with self.subTest(engine):
                result = plan(designed(engine))
                self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
                artifact = result.artifacts[0].content
                self.assertEqual(artifact["engine"]["type"], engine)
                self.assertEqual(artifact["repo_params"]["game_config"]["engine"],
                                 {"type": engine})
                self.assertEqual(result.artifacts[0].metadata["engine_source"],
                                 "design.engine.type")

    def test_the_asset_fixtures_resolve_by_their_asset_kinds(self):
        for name, engine in (("design-2d.json", "pixijs"), ("design-3d.json", "threejs")):
            with self.subTest(name):
                result = plan(fixture_design(name))
                self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
                artifact = result.artifacts[0].content
                self.assertEqual(artifact["engine"]["type"], engine)
                self.assertEqual(result.artifacts[0].metadata["engine_source"], "design assets")
                self.assertIn("declares no engine", artifact["engine"]["rationale"])
                self.assertEqual(ArtifactContracts()("tech-plan", artifact), [])

    def test_the_renderer_is_the_designs_choice_not_the_modules(self):
        # Same strategy, same everything, only the design's declared engine differs.
        design = designed("pixijs")
        design["engine"].update(type="threejs", dimension="3d")
        self.assertEqual(plan(rehash(design)).artifacts[0].content["engine"]["type"], "threejs")

    def test_only_the_dimension_mapping_is_known_here(self):
        self.assertEqual(ENGINE_FOR_DIMENSION, {"2d": "pixijs", "3d": "threejs"})
        self.assertEqual(select_engine({"engine": {"dimension": "3d"}}, {})[0], "threejs")

    def test_a_design_that_contradicts_itself_or_says_nothing_is_refused(self):
        cases = {
            "contradiction": {"engine": {"type": "pixijs", "dimension": "3d"}},
            "unknown engine": {"engine": {"type": "babylon"}},
            "nothing": {"asset_requirements": [{"kind": "sfx"}]},
        }
        for name, design in cases.items():
            with self.subTest(name):
                with self.assertRaises(EngineError):
                    select_engine(design, {"sfx": "any"})
        design = designed("pixijs")
        design["engine"]["dimension"] = "3d"
        result = plan(rehash(design))
        self.assertEqual((result.outcome, result.retryable), (StepOutcome.FAILED, False))


# -- the plan ------------------------------------------------------------------------------


class ThePlan(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.design = designed("threejs")
        cls.result = plan(cls.design)
        cls.artifact = cls.result.artifacts[0].content

    def test_meets_the_engine_contract_and_provenance_reproduces(self):
        self.assertEqual(ArtifactContracts()("tech-plan", self.artifact), [])
        provenance = self.artifact["provenance"]
        self.assertEqual(provenance["content_hash"], content_hash(self.artifact))
        self.assertEqual(provenance["produced_by"]["role"], "architect")
        self.assertEqual({i["artifact_type"] for i in provenance["inputs"]},
                         {"game-design", "title-strategy"})
        self.assertEqual(provenance["artifact_id"], "wgf:tech-plan:neon-drift:20260924-01")

    def test_is_deterministic(self):
        again = plan(copy.deepcopy(self.design)).artifacts[0].content
        self.assertEqual(again["provenance"]["content_hash"],
                         self.artifact["provenance"]["content_hash"])

    def test_platforms_are_pinned_to_the_profiles_required_first(self):
        platforms = self.artifact["repo_params"]["game_config"]["platforms"]
        self.assertEqual(platforms[0]["role"], "required")
        for entry in platforms:
            profile = load_file(os.path.join(paths.PLATFORMS, f"{entry['id']}.yaml"))
            self.assertEqual(entry["profile"], f"{entry['id']}@{profile['version']}")
        pinned = {p["id"] for p in strategy()["platform_set"]}
        self.assertEqual({p["id"] for p in platforms}, pinned)

    def test_bundle_budget_is_the_tightest_required_limit(self):
        required = [p for p in strategy()["platform_set"] if p["role"] == "required"]
        limits = [load_file(os.path.join(paths.PLATFORMS, f"{p['id']}.yaml"))
                  ["requirements"]["max_bundle_mb"] for p in required]
        self.assertEqual(self.artifact["perf_budgets"]["max_bundle_mb"], min(limits))

    def test_monetization_is_the_designs_ad_kinds(self):
        kinds = {p["kind"] for p in self.design["monetization"]["placements"]}
        declared = self.artifact["repo_params"]["game_config"]["monetization"]
        self.assertEqual(set(declared["ad_kinds"]), kinds - {"iap"})
        self.assertEqual(declared["iap"], "iap" in kinds)

    def test_every_task_is_verifiable_and_every_mvp_feature_has_one(self):
        tasks = self.artifact["dev_plan"]["tasks"]
        ids = {t["id"] for t in tasks}
        for task in tasks:
            self.assertTrue(task["acceptance_criteria"], task["id"])
            self.assertTrue(set(task.get("dependencies") or []) <= ids, task["id"])
        mvp = [f for f in self.design["features"] if f["tier"] == "mvp"]
        m1 = [t for t in tasks if t["milestone"] == "M1" and t["id"].startswith("GAME-")]
        self.assertEqual(len(m1), len(mvp))
        self.assertFalse(any("weekly" in t["title"].lower() for t in tasks))  # optional tier

    def test_the_g3_guards_read_what_they_need(self):
        entity = Entity(**{"tech-plan": self.artifact, "title-strategy": strategy()})
        context = guards.GuardContext(entity, config={"overrun_tolerance": 1.5})
        self.assertIs(guards.evaluate_guard("engine_selected", context).value, True)
        fits = guards.evaluate_guard("plan_fits_timebox", context)
        self.assertIsNotNone(fits.value, fits.reason)
        self.assertEqual(self.result.artifacts[0].metadata["fits_timebox"], fits.value)

    def test_an_overrun_is_reported_not_fitted(self):
        strat = strategy()
        strat["timebox_days"] = 2
        result = plan(self.design, strat=rehash(strat))
        self.assertEqual(result.outcome, StepOutcome.SUCCESS)
        artifact = result.artifacts[0].content
        self.assertEqual(artifact["dev_plan"]["est_days"], self.artifact["dev_plan"]["est_days"])
        self.assertFalse(result.artifacts[0].metadata["fits_timebox"])
        self.assertTrue(any(r["severity"] == "high" for r in artifact["technical_risks"]))

    def test_estimates_are_configurable(self):
        slow = plan(self.design, config={"techplan": {"estimates": {"hours_per_day": 3}}})
        self.assertGreater(slow.artifacts[0].content["dev_plan"]["est_days"],
                           self.artifact["dev_plan"]["est_days"])


# -- outcomes ------------------------------------------------------------------------------


class Outcomes(unittest.TestCase):
    def test_missing_inputs_wait(self):
        step = Fixed(_Definition("tech-plan", "tech-plan", [], ["tech-plan"]))
        result = step.execute(inputs(**{"game-design": None, "title-strategy": None}), Context())
        self.assertEqual(result.outcome, StepOutcome.WAITING_FOR_INPUT)

    def test_a_moved_profile_pin_blocks(self):
        strat = strategy()
        strat["platform_set"][0]["profile_version"] = "9.9.9"
        result = plan(designed("pixijs"), strat=rehash(strat))
        self.assertEqual(result.outcome, StepOutcome.BLOCKED)
        self.assertIn("re-pin", result.error or result.message)

    def test_a_design_that_did_not_leave_title_design_fails(self):
        design = designed("pixijs")
        design["consistency"]["status"] = "fail"
        result = plan(rehash(design))
        self.assertEqual((result.outcome, result.retryable), (StepOutcome.FAILED, False))

    def test_a_design_for_another_title_fails(self):
        design = designed("pixijs")
        design["title_id"] = "other-title"
        result = plan(rehash(design), context=Context(project_id=None))
        self.assertEqual((result.outcome, result.retryable), (StepOutcome.FAILED, False))

    def test_bad_settings_block(self):
        result = plan(designed("pixijs"), config={"techplan": {"estimates": {"nope": 1}}})
        self.assertEqual(result.outcome, StepOutcome.BLOCKED)


# -- G3 through the engine -----------------------------------------------------------------

G3_WORKFLOW = """
workflow:
  id: techplan-contract
  version: 1
  steps:
    - id: seed
      type: test.seed-plan-inputs
      outputs: [title-strategy, game-design]
    - id: tech-plan
      type: tech-plan
      inputs: [game-design, title-strategy]
      outputs: [tech-plan]
    - id: tech-plan-review
      type: human-checkpoint
      with:
        gate: G3
        prompt: Approve the plan?
        choices: [approve, reject]
      next: $end
"""


class SeedStep(WorkflowStep):
    type = "test.seed-plan-inputs"
    design = None

    def execute(self, inputs, context):
        return StepResult.success([ArtifactOutput("title-strategy", strategy()),
                                   ArtifactOutput("game-design", SeedStep.design)])


class ThroughTheEngine(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        SeedStep.design = designed("threejs")

    def setUp(self):
        self.scratch = tempfile.mkdtemp(prefix="wgf-techplan-")
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)
        self.workflow = os.path.join(self.scratch, "techplan-contract.workflow.yaml")
        with open(self.workflow, "w", encoding="utf-8") as handle:
            handle.write(G3_WORKFLOW)

    def api(self, auto_approve=()):
        class Api(WorkflowAPI):
            def registry(self, use_mock):
                registry = super().registry(use_mock)
                assert registry.resolve("tech-plan") is TechPlanStep  # from the module list
                registry.register(SeedStep.type, SeedStep)
                return registry

        config = FactoryConfig({"steps": {"modules": ["wgf_techplan"]},
                                "checkpoints": {"auto_approve": list(auto_approve)},
                                "storage": {"fsync": False}})
        return Api(config=config, store_dir=os.path.join(self.scratch, "store"),
                   workflow=self.workflow)

    def test_the_plan_waits_at_g3_unless_the_installation_auto_approves_it(self):
        api = self.api()
        state = api.run(RunRequest(project_id="neon-drift"))
        self.assertEqual(state.status, RunStatus.WAITING)
        self.assertEqual(state.steps["tech-plan-review"].status, StepStatus.WAITING)
        ref = state.latest_artifact("tech-plan")
        self.assertEqual(ref.metadata["engine"], "threejs")
        self.assertEqual(sorted(state.steps["tech-plan"].consumed),
                         ["game-design@v1", "title-strategy@v1"])
        final = api.run(RunRequest(resume=state.run_id, decision="approve"))
        self.assertEqual(final.status, RunStatus.COMPLETED)
        self.assertEqual(final.decisions["tech-plan-review"]["decided_by"], "human")

        auto = self.api(auto_approve=["G3"]).run(RunRequest(project_id="neon-drift"))
        self.assertEqual(auto.status, RunStatus.COMPLETED)

    def test_a_rejected_plan_blocks(self):
        api = self.api()
        state = api.run(RunRequest(project_id="neon-drift"))
        final = api.run(RunRequest(resume=state.run_id, decision="reject"))
        self.assertEqual(final.status, RunStatus.BLOCKED)

    def test_g3_is_reversible(self):
        self.assertNotIn("G3", irreversible_gates())

    def test_the_shipped_workflow_plans_and_gates_before_init(self):
        definition = load_definition("new-game")
        ids = definition.step_ids
        self.assertLess(ids.index("design"), ids.index("tech-plan"))
        self.assertEqual(ids[ids.index("tech-plan") + 1], "tech-plan-review")
        self.assertEqual(ids[ids.index("tech-plan-review") + 1], "init")
        self.assertEqual(definition.step("tech-plan-review").params["gate"], "G3")
        self.assertIn("tech-plan", definition.step("init").inputs)
        self.assertEqual(set(definition.step("tech-plan").inputs),
                         {"game-design", "title-strategy"})

    def test_the_module_registers_by_config(self):
        self.assertEqual(wgf_techplan.register.__module__, "wgf_techplan")


# -- full schema validation ----------------------------------------------------------------


def _jsonschema_lite():
    try:
        from wgflib import jsonschema_lite  # Team C's validator, when merged
    except ImportError:
        return None
    return jsonschema_lite


class Schema(unittest.TestCase):
    def artifacts(self):
        return [plan(designed(e)).artifacts[0].content for e in ("pixijs", "threejs")] + \
               [plan(fixture_design(n)).artifacts[0].content
                for n in ("design-2d.json", "design-3d.json")]

    @unittest.skipIf(_jsonschema_lite() is None, "wgflib.jsonschema_lite is not available")
    def test_validates_with_jsonschema_lite(self):
        from wgflib.workflow.contracts import ArtifactContracts
        validate = ArtifactContracts()  # full draft 2020-12 validation via jsonschema_lite
        for artifact in self.artifacts():
            errors = validate("tech-plan", artifact)
            self.assertFalse(errors, errors)

    @unittest.skipUnless(os.environ.get("WGF_AJV") and shutil.which("npx"),
                         "set WGF_AJV=1 to validate with ajv (needs npx)")
    def test_validates_with_ajv(self):
        scratch = tempfile.mkdtemp(prefix="wgf-techplan-ajv-")
        self.addCleanup(shutil.rmtree, scratch, ignore_errors=True)
        files = []
        for index, artifact in enumerate(self.artifacts()):
            path = os.path.join(scratch, f"tech-plan-{index}.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(artifact, handle)
            files += ["-d", path]
        completed = subprocess.run(
            ["npx", "--yes", "-p", "ajv-cli@5", "-p", "ajv-formats@2", "ajv", "validate",
             "-s", "core/artifacts/tech-plan.schema.json",
             "-r", "core/artifacts/shared/*.schema.json", "-c", "ajv-formats",
             "--spec=draft2020", "--strict=false", *files],
            cwd=ROOT, capture_output=True, text=True, check=False)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)


if __name__ == "__main__":
    unittest.main()

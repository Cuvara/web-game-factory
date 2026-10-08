"""K2: a new-game run is held to the Factory knowledge it started under, through its contract.

core/reference/quality-policy.yaml rule 8, scripts/wgflib/workflow/quality.py (the snapshot),
scripts/wgflib/workflow/api.py (no run without its knowledge), new-game.workflow.yaml 17 (the
pins and the `knowledge-contract` step), scripts/wgf_knowledge/step.py. These tests hold:

  * CONTEXT. A run records the lessons and check-tiers versions and the Factory's version
    and commit when it starts, comparable across runs; `wgf status` reports them.
  * NO RUN WITHOUT IT. A knowledge file that is missing, versionless or not shaped as
    knowledge refuses the run before it is created.
  * THE CONTRACT. After design and before tech-plan the run resolves the rules that apply to
    its design and strategy - by level, with the steps that validate them and the regression
    suite - from its pinned knowledge; G3 is decided on it, and a mock new-game reaches G4
    with it.
  * IT STOPS. A run that cannot make its contract (a validator its workflow lacks, a pinned
    copy edited since the start, knowledge the run did not pin) is BLOCKED at the step and
    nothing after it runs.
  * OLD RUNS. A run started before the knowledge model is advisory: its knowledge step makes
    the contract it can and never blocks it, and no required step is added to it.

    python -m unittest scripts.tests.test_knowledge_run
"""

import json
import os
import re
import shutil
import sys
import tempfile
import unittest
from unittest import mock as patch

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

import wgf_knowledge  # noqa: E402
from wgf_knowledge import model, versions  # noqa: E402
from wgflib.workflow import mock, quality, references  # noqa: E402
from wgflib.workflow.api import RunRequest, WorkflowAPI  # noqa: E402
from wgflib.workflow.config import ConfigError, FactoryConfig  # noqa: E402
from wgflib.workflow.definition import load_definition  # noqa: E402
from wgflib.workflow.events import Events  # noqa: E402
from wgflib.workflow.model import RunStatus  # noqa: E402
from wgflib.yamllite import load_file  # noqa: E402

SHIPPED = os.path.join(ROOT, "core", "workflows", "new-game.workflow.yaml")
STEP = "knowledge-contract"
GATES = {"auto_approve": ["G2", "G3", "G5"]}
# A run is refused before it starts when the configured design author cannot meet its tier
# (quality-policy preflight); the agent author can. The placeholders build nothing.
AUTHOR = {"author": "agent"}
# The pins new-game 16 had: the knowledge files themselves, nothing they are read with.
PINS_16 = ["core/reference/quality-floor.yaml", "core/reference/quality-benchmark.yaml",
           "core/reference/visual-qa-rubric.yaml", "core/reference/visual-quality.yaml",
           "core/reference/play-realism.yaml", "core/reference/browser-qa.yaml",
           "core/reference/check-tiers.yaml", "core/reference/lessons.yaml"]


class Design2D(mock.MockDesignStep):
    """The mock design, drawn for 2D."""

    def customize(self, body, artifact_type, context, entry):
        body["engine"] = {"type": "pixijs", "dimension": "2d",
                          "rationale": "A 2D arcade loop reads at once on a phone."}


class StrategyYandex(mock.MockStrategyStep):
    """The mock strategy, targeting Yandex Games alone."""

    def customize(self, body, artifact_type, context, entry):
        body["platform_set"] = [p for p in body["platform_set"] if p.get("id") == "yandex"]


class KnowledgeAPI(WorkflowAPI):
    """The placeholder steps for every run, mock or not - so a run started without --mock is
    held to the policy exactly as a real one - with the REAL knowledge step."""

    extra_steps = ()

    def registry(self, use_mock, load_modules=True):
        registry = super().registry(True, load_modules=False)
        wgf_knowledge.register(registry)
        for cls in self.extra_steps:
            registry.register(cls.type, cls)
        return registry


class Arcade2DYandexAPI(KnowledgeAPI):
    extra_steps = (Design2D, StrategyYandex)


def workflow_text(pins=None, drop_steps=(), version=None, g3_inputs=None):
    """The shipped new-game text with its pinned_references replaced, steps removed, the
    version changed or G3's inputs replaced: a definition from elsewhere or from before."""
    with open(SHIPPED, encoding="utf-8") as handle:
        text = handle.read()
    if pins is not None:
        block = "\n".join(f"    - {p}" for p in pins) + "\n"
        text = re.sub(r"(?m)(^  pinned_references:\n)(?:^    (?:- .*|#.*)\n)+",
                      lambda m: m.group(1) + block, text)
    for step_id in drop_steps:
        text = re.sub(r"(?ms)^    - id: " + re.escape(step_id) + r"\n.*?(?=^    - id: |\Z)",
                      "", text)
        # The route budgets keyed by it, and its place in a group.
        text = re.sub(r"(?m)^ +" + re.escape(step_id) + r"\.[a-z-]+: \d+\n", "", text)
        text = text.replace(f", {step_id}, ", ", ")
    if version is not None:
        text = re.sub(r"(?m)^  version: \d+$", f"  version: {version}", text)
    if g3_inputs is not None:
        text = text.replace("inputs: [game-design, tech-plan, knowledge-contract]",
                            f"inputs: [{', '.join(g3_inputs)}]")
    return text


def write_workflow(folder, text):
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "new-game.workflow.yaml")
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    return path


class _Case(unittest.TestCase):
    api_class = KnowledgeAPI

    def setUp(self):
        self.scratch = tempfile.mkdtemp(prefix="wgf-k2-")
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)
        self.store_dir = os.path.join(self.scratch, "store")

    def api(self, extra=None, workflow=None, api_class=None, **kwargs):
        data = {"storage": {"fsync": False}, "checkpoints": dict(GATES),
                "design": dict(AUTHOR)}
        data.update(extra or {})
        return (api_class or self.api_class)(config=FactoryConfig(data),
                                             store_dir=self.store_dir, workflow=workflow,
                                             **kwargs)

    def to_g4(self, api=None, **request):
        api = api or self.api()
        state = api.run(RunRequest(**request))
        self.assertEqual((state.status, state.cursor), (RunStatus.WAITING, "prototype-review"),
                         state.message)
        return api, state

    @staticmethod
    def executed(state):
        return [entry["step"] for entry in state.trail]

    def contract(self, api, state):
        ref = state.latest_of_type("knowledge-contract")
        self.assertIsNotNone(ref, "the run made no knowledge-contract")
        return api.store.read_artifact(state.run_id, ref)

    def runs(self):
        folder = os.path.join(self.store_dir, "workflows")
        return os.listdir(folder) if os.path.isdir(folder) else []


class Context(_Case):
    def test_the_run_records_factory_lessons_and_check_tiers_versions(self):
        api, state = self.to_g4()
        taken = state.params["quality"]
        lessons = load_file(os.path.join(ROOT, "core", "reference", "lessons.yaml"))
        tiers = load_file(os.path.join(ROOT, "core", "reference", "check-tiers.yaml"))
        self.assertEqual(taken["knowledge"], {
            "check-tiers": f"check-tiers@{tiers['version']}",
            "lessons": f"lessons@{lessons['version']}"})
        with open(os.path.join(ROOT, "VERSION"), encoding="utf-8") as handle:
            self.assertEqual(taken["factory"]["version"], handle.read().strip())
        commit = taken["factory"]["commit"]
        self.assertTrue(commit is None or re.fullmatch(r"[0-9a-f]{40}", commit), commit)
        # Corroborated like every param: recorded in WORKFLOW_STARTED.
        started = [e for e in api.store.read_events(state.run_id)
                   if e["event"] == Events.WORKFLOW_STARTED][0]
        self.assertEqual(started["data"]["params"]["quality"]["knowledge"], taken["knowledge"])
        # Reported by status, and comparable: a second run on the same Factory records the
        # same versions, so two generations differ exactly where their knowledge does.
        report = api.quality(state)
        self.assertEqual((report["knowledge"], report["factory"]),
                         (taken["knowledge"], taken["factory"]))
        import wgf
        self.assertIn(f"Knowledge: {taken['knowledge']['check-tiers']}, "
                      f"{taken['knowledge']['lessons']}", wgf.render_quality(report))
        _, second = self.to_g4(api)
        self.assertEqual(second.params["quality"]["knowledge"], taken["knowledge"])
        self.assertEqual(second.params["quality"]["factory"], taken["factory"])

    def test_the_contract_records_what_the_run_pinned(self):
        api, state = self.to_g4()
        found = self.contract(api, state)["versions"]
        pins = state.params[references.PARAM]
        self.assertEqual(found["lessons"]["sha256"], pins["core/reference/lessons.yaml"])
        self.assertEqual(found["check_tiers"]["sha256"], pins["core/reference/check-tiers.yaml"])
        self.assertEqual(found["factory"], state.params["quality"]["factory"])
        with open(SHIPPED, "rb") as handle:
            digest = references.digest(handle.read())
        # The workflow is not pinned: the contract records the file that named its validators.
        self.assertEqual(found["workflow"], {"id": "new-game",
                                             "version": load_definition("new-game").version,
                                             "sha256": digest})
        self.assertNotIn("advisory", self.contract(api, state))
        self.assertEqual(f"lessons@{found['lessons']['version']}",
                         state.params["quality"]["knowledge"]["lessons"])
        for platform in ("yandex", "crazygames"):
            self.assertIn(f"core/reference/platforms/{platform}.yaml", pins)
            self.assertTrue(found["platform_profiles"][platform].startswith(f"{platform}@"))


class NoRunWithoutKnowledge(_Case):
    def _refused(self, expected):
        with self.assertRaisesRegex(ConfigError, expected):
            self.api().run(RunRequest())
        self.assertEqual(self.runs(), [], "a run was created")

    def test_no_run_is_created_when_lessons_is_unreadable(self):
        policy = dict(quality.load_policy(),
                      knowledge=["core/reference/no-such-lessons.yaml",
                                 "core/reference/check-tiers.yaml"])
        with patch.patch.object(quality, "load_policy", return_value=policy):
            self._refused("no-such-lessons.yaml cannot be read")

    def _fake_root(self, lessons_text):
        root = os.path.join(self.scratch, "factory")
        os.makedirs(os.path.join(root, "core", "reference"))
        shutil.copy(os.path.join(ROOT, "core", "reference", "check-tiers.yaml"),
                    os.path.join(root, "core", "reference", "check-tiers.yaml"))
        with open(os.path.join(root, "core", "reference", "lessons.yaml"), "w",
                  encoding="utf-8", newline="\n") as handle:
            handle.write(lessons_text)
        return root

    def test_no_run_is_created_when_lessons_has_no_version(self):
        root = self._fake_root("lessons:\n  - id: L1\n    title: t\n")
        with patch.patch.object(versions, "_root", return_value=root):
            self._refused("has no version")

    def test_no_run_is_created_when_lessons_is_not_knowledge(self):
        root = self._fake_root("version: 2.0.0\nlessons: none\n")
        with patch.patch.object(versions, "_root", return_value=root):
            self._refused("no `lessons` list")

    def test_a_policy_without_versions_for_its_knowledge_starts_no_run(self):
        policy = quality.load_policy()
        with self.assertRaisesRegex(quality.PolicyError, "check-tiers"):
            quality.snapshot(policy, {}, load_definition("new-game"),
                             knowledge={"lessons": "lessons@2.0.0"})


class TheContract(_Case):
    def test_a_new_game_writes_a_knowledge_contract_before_tech_plan(self):
        api, state = self.to_g4()
        steps = self.executed(state)
        self.assertLess(steps.index("design"), steps.index(STEP))
        self.assertLess(steps.index(STEP), steps.index("tech-plan"))
        contract = self.contract(api, state)
        self.assertTrue(contract["rules"])
        self.assertEqual(contract["missing_validators"], [])
        # G3 is decided on it: its decision-record pins the contract by hash.
        # The newest decision-record is G3's: G4 has not been decided.
        record = api.store.read_artifact(state.run_id, state.latest_of_type("decision-record"))
        self.assertEqual(record["gate_id"], "G3")
        pinned = {i.get("artifact_type") for i in record["provenance"]["inputs"]}
        self.assertIn("knowledge-contract", pinned)

    def test_the_contract_lists_the_applicable_rules_validators_and_suite_for_a_2d_arcade_yandex_release_run(self):
        api, state = self.to_g4(self.api(api_class=Arcade2DYandexAPI))
        contract = self.contract(api, state)
        self.assertEqual(contract["facets"]["family"], "arcade")
        self.assertEqual(contract["facets"]["render"], "2d")
        self.assertEqual(contract["facets"]["platforms"], ["yandex"])
        self.assertEqual(contract["facets"]["tier"], "release")
        by_level = {}
        for rule in contract["rules"]:
            by_level.setdefault(rule["level"], []).append(rule["id"])
        lessons = load_file(os.path.join(ROOT, "core", "reference", "lessons.yaml"))
        scoped_3d = [l["id"] for l in lessons["lessons"]
                     if (model.scope_of(l) or {}).get("render") == ["3d"]]
        excluded = {e["id"]: e["why_not"] for e in contract["not_applicable"]}
        for lesson_id in scoped_3d:
            self.assertIn(lesson_id, excluded)
            self.assertIn("render 2d", excluded[lesson_id])
        for lesson_id in ("L6", "L19"):  # process lessons: never in a run
            self.assertIn("process", excluded[lesson_id])
        self.assertTrue(by_level.get("blocking"))
        self.assertTrue(by_level.get("required"))
        self.assertIn("L23", by_level["required"])
        self.assertEqual(contract["counts"]["blocking"], len(by_level["blocking"]))
        workflow = load_definition("new-game")
        self.assertTrue(contract["required_validators"])
        self.assertTrue(set(contract["required_validators"]) <= set(workflow.step_ids))
        for step_id in ("playability", "verify", "quality-gate"):
            self.assertIn(step_id, contract["required_validators"])
        l23 = next(r for r in contract["rules"] if r["id"] == "L23")
        for test in l23["tests"]["catches"]:
            self.assertIn(test, contract["regression_suite"])
        self.assertTrue(contract["constraints"]["genre"].endswith("#arcade"))
        self.assertEqual([c.split("@")[0] for c in contract["constraints"]["platforms"]],
                         ["yandex"])

    def test_a_mock_new_game_reaches_g4_with_the_knowledge_step(self):
        api = WorkflowAPI(config=FactoryConfig({"storage": {"fsync": False}}),
                          store_dir=self.store_dir)
        state = api.run(RunRequest(mock=True))
        self.assertEqual((state.status, state.cursor), (RunStatus.WAITING, "prototype-review"),
                         state.message)
        self.assertIn(STEP, self.executed(state))
        self.assertIn("knowledge", state.params["quality"])
        contract = self.contract(api, state)
        self.assertTrue(contract["rules"])

    def test_knowledge_follows_design_and_precedes_tech_plan_and_never_continues_on_failure(self):
        workflow = load_definition("new-game")
        ids = workflow.step_ids
        self.assertEqual(ids[ids.index("design") + 1], STEP)
        self.assertEqual(ids[ids.index(STEP) + 1], "tech-plan")
        step = workflow.step(STEP)
        self.assertEqual((step.type, step.stage), ("knowledge", "title:design"))
        self.assertEqual(step.outputs, ["knowledge-contract"])
        # No route out of a failure or a block: unrouted, they stop the run.
        raw = load_file(SHIPPED)["workflow"]
        spec = next(s for s in raw["steps"] if s["id"] == STEP)
        self.assertNotIn("on", spec)
        self.assertNotIn("next", spec)
        self.assertIn("knowledge-contract", next(
            s for s in raw["steps"] if s["id"] == "tech-plan-review")["inputs"])
        self.assertIn(STEP, raw["groups"]["plan"])


class ItStops(_Case):
    def assertStopped(self, state, expected):
        self.assertEqual((state.status, state.cursor), (RunStatus.BLOCKED, STEP), state.message)
        self.assertRegex(state.message or "", expected)
        steps = self.executed(state)
        last = len(steps) - 1 - steps[::-1].index(STEP)
        self.assertNotIn("tech-plan", steps[last:])

    def test_the_knowledge_step_blocks_when_a_required_validator_is_missing(self):
        # A workflow from elsewhere that drops a step validating blocking and required rules.
        path = write_workflow(os.path.join(self.scratch, "elsewhere"),
                              workflow_text(drop_steps=("content-sufficiency",)))
        api = self.api(workflow=path)
        state = api.run(RunRequest())
        self.assertStopped(state, r"no step of the run's workflow validates .*content-sufficiency")
        self.assertIsNone(state.latest_of_type("knowledge-contract"))

    def test_an_edit_to_the_pinned_lessons_blocks_and_never_applies(self):
        api, state = self.to_g4()
        before = self.contract(api, state)
        pinned = os.path.join(api.store.run_dir(state.run_id), references.DIRECTORY,
                              "core", "reference", "lessons.yaml")
        with open(pinned, "a", encoding="utf-8", newline="\n") as handle:
            handle.write("\n# edited after the run started\n")
        state = api.run(RunRequest(resume=state.run_id, from_step=STEP, decided_by="human"))
        self.assertStopped(state, "edited after the start")
        self.assertEqual(self.contract(api, state)["provenance"]["content_hash"],
                         before["provenance"]["content_hash"])

    def test_a_run_that_did_not_pin_its_knowledge_is_blocked(self):
        path = write_workflow(os.path.join(self.scratch, "elsewhere"),
                              workflow_text(pins=PINS_16))
        state = self.api(workflow=path).run(RunRequest())
        self.assertStopped(state, "did not pin")

    def test_a_blocked_step_is_reported_with_its_reason(self):
        path = write_workflow(os.path.join(self.scratch, "elsewhere"),
                              workflow_text(pins=PINS_16))
        api = self.api(workflow=path)
        state = api.run(RunRequest())
        blocked = [e for e in api.store.read_events(state.run_id)
                   if e["event"] == Events.STEP_BLOCKED and e.get("step_id") == STEP]
        self.assertTrue(blocked)


class OldRuns(_Case):
    """A run started before the knowledge model: no params.quality.knowledge."""

    def _old_policy(self):
        policy = dict(quality.load_policy())
        policy["knowledge"] = []
        return policy

    def _start_old(self, text):
        path = write_workflow(os.path.join(self.scratch, "before"), text)
        api = self.api(workflow=path)
        with patch.patch.object(quality, "load_policy", return_value=self._old_policy()):
            state = api.run(RunRequest())
        self.assertNotIn("knowledge", state.params["quality"])
        return api, state

    def test_an_old_run_is_not_given_a_required_step(self):
        self.assertNotIn(STEP, quality.load_policy()["required_steps"])
        definition = load_definition("new-game")
        held = quality.effective({}, quality.load_policy())
        old = load_definition(write_workflow(
            os.path.join(self.scratch, "before"),
            workflow_text(pins=PINS_16, drop_steps=(STEP,), version=16,
                          g3_inputs=("game-design", "tech-plan"))))
        self.assertEqual(quality.lacking(old, held), [])
        self.assertEqual(quality.missing_gates(old, held, definition.step("quality-gate"),
                                               definition), [])

    def test_an_old_run_at_g3_makes_an_advisory_contract_and_goes_on(self):
        api, state = self._start_old(workflow_text(
            pins=PINS_16, drop_steps=(STEP,), version=16, g3_inputs=("game-design", "tech-plan")))
        # gates.yaml 1.7.0 decides G3 on the contract, which this run never made: it waits
        # for it, as G4 waited for the quality-report in 1.6.0, rather than passing without.
        self.assertEqual((state.status, state.cursor), (RunStatus.WAITING, "tech-plan-review"),
                         state.message)
        self.assertIn("knowledge-contract", state.message)
        # Resumed under the shipped definition from its knowledge step: the contract is made
        # from what the run holds - advisory - and the run goes on.
        state = self.api().run(RunRequest(resume=state.run_id, from_step=STEP,
                                          decided_by="human"))
        self.assertEqual((state.status, state.cursor), (RunStatus.WAITING, "prototype-review"),
                         state.message)
        contract = self.contract(api, state)
        self.assertTrue(contract["rules"])
        entry = next(e for e in reversed(state.trail) if e["step"] == STEP)
        self.assertEqual(entry["outcome"], "SUCCESS")
        self.assertIn("ADVISORY", state.steps[STEP].message or "")
        self.assertNotIn("knowledge", state.params["quality"])

    def test_an_old_run_is_never_blocked_by_its_knowledge_step(self):
        # What blocks a new run - pins it never made, a validator its workflow lacks - is
        # reported in an old run's contract message, never a stop.
        api, state = self._start_old(workflow_text(pins=PINS_16,
                                                   drop_steps=("content-sufficiency",)))
        self.assertNotEqual(state.status, RunStatus.BLOCKED, state.message)
        self.assertIn(STEP, self.executed(state))
        message = state.steps[STEP].message or ""
        self.assertIn("ADVISORY", message)
        self.assertIn("content-sufficiency", message)
        # The contract says so: advisory, with what would have stopped a new run.
        advisory = self.contract(api, state)["advisory"]
        self.assertIn("never enforced", advisory["reason"])
        problems = " ".join(advisory["problems"])
        self.assertIn("did not pin", problems)
        self.assertIn("content-sufficiency", problems)

    def test_an_old_run_that_pinned_lessons_1x_gets_a_contract_of_the_same_schema(self):
        # Workflow 16 pinned lessons.yaml 1.x: no category, lifecycle or scope, tests a flat
        # list. The advisory contract fills what the model would derive, and is one schema.
        lessons_1x = (b"version: 1.0.0\nstatuses: [enforced, partial, gap, process]\n"
                      b"lessons:\n"
                      b"  - id: L2\n    title: A ramp check decided noise\n"
                      b"    lesson: A measurement at the edge of its bar is noise.\n"
                      b"    status: enforced\n    checks: [playability:depth.ramp]\n"
                      b"    tests:\n      - scripts/tests/test_playability.py::test_x\n"
                      b"  - id: L9\n    title: A release bar nothing holds yet\n"
                      b"    lesson: Nothing measures it.\n    status: gap\n"
                      b"    gap: no check yet\n")
        collect = references.collect

        def older(relpaths, root=None):
            found = collect(relpaths, root)
            if "core/reference/lessons.yaml" in found:
                found["core/reference/lessons.yaml"] = lessons_1x
            return found

        with patch.patch.object(references, "collect", side_effect=older):
            api, state = self._start_old(workflow_text(pins=PINS_16))
        self.assertNotEqual(state.status, RunStatus.BLOCKED, state.message)
        contract = self.contract(api, state)
        rules = {r["id"]: r for r in contract["rules"]}
        self.assertEqual(rules["L2"]["lifecycle"], "active")
        self.assertEqual(rules["L9"]["lifecycle"], "candidate")
        self.assertEqual(contract["versions"]["lessons"]["version"], "1.0.0")


class Step(unittest.TestCase):
    def test_the_module_registers_the_knowledge_step(self):
        from wgflib.workflow.step import StepRegistry
        registry = wgf_knowledge.register(StepRegistry())
        self.assertEqual(registry.resolve("knowledge").__module__, "wgf_knowledge.step")
        modules = load_file(os.path.join(ROOT, "workspace", "config", "factory.yaml"))[
            "factory"]["steps"]["modules"]
        self.assertIn("wgf_knowledge", modules)

    def test_every_new_game_step_type_has_a_placeholder_and_its_fixture(self):
        self.assertIn("knowledge", {cls.type for cls in mock.MOCK_STEPS})
        with open(os.path.join(mock.FIXTURES, "knowledge-contract.json"), encoding="utf-8") as h:
            fixture = json.load(h)
        self.assertTrue(fixture["rules"])
        self.assertEqual(fixture["missing_validators"], [])


if __name__ == "__main__":
    unittest.main()

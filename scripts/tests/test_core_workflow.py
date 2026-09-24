"""Core v1 acceptance: the workflow engine's behaviour, one named scenario per test class.

This is the WORKFLOW category of the Core Acceptance Suite (`wgf test-core`, mapping in
core_suite.py). Small in-memory definitions and scripted steps, reusing the doubles from
test_workflow_engine.py, so each scenario states exactly the behaviour it pins:

    HappyPath, Failure, Retry, Resume, Pause, Cancel (between steps and mid child process),
    HumanGate, MaxVisits, VerifyDevelopLoop, StaleRunResume, ConcurrentRunLock, Determinism,
    plus the input-contract boundary, continue_in, liveness and `wgf test-core` itself.

Run from the web-game-factory repository root:

    python3 -m unittest discover scripts/tests
"""

import contextlib
import datetime
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
for _path in (SCRIPTS, HERE):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import wgf  # noqa: E402
from test_workflow_engine import CHECKPOINT, LINEAR, LOOP, EngineCase  # noqa: E402
from wgflib import procs  # noqa: E402
from wgflib.workflow.config import FactoryConfig  # noqa: E402
from wgflib.workflow.engine import EngineError  # noqa: E402
from wgflib.workflow.events import Events  # noqa: E402
from wgflib.workflow.model import (  # noqa: E402
    ArtifactOutput,
    Liveness,
    RunState,
    RunStatus,
    StepOutcome,
    StepResult,
    StepState,
    StepStatus,
    derive_liveness,
)
from wgflib.workflow.store import RunLocked, RunStore  # noqa: E402

DEAD_PID = 999999999  # above any pid_max: never a live process


def defects():
    return StepResult(StepOutcome.FAILED, route="fail", retryable=False, error="defects")


class HappyPath(EngineCase):
    def test_every_step_runs_once_in_order_and_the_run_completes(self):
        state = self.engine(LINEAR).start()
        self.assertEqual(state.status, RunStatus.COMPLETED)
        self.assertEqual(self.script.executed(), ["a", "b", "c"])
        self.assertEqual([s.executions for s in state.steps.values()], [1, 1, 1])
        self.assertEqual(self.store.load(state.run_id).to_dict(), state.to_dict())
        self.assertEqual(self.names()[-1], Events.WORKFLOW_COMPLETED)
        self.assertFalse(self.store.is_held(state.run_id))


class Failure(EngineCase):
    def test_a_non_retryable_failure_fails_the_run_at_that_step(self):
        self.script.set("b", StepResult.failed("bad input", retryable=False))
        state = self.engine(LINEAR).start()
        self.assertEqual(state.status, RunStatus.FAILED)
        self.assertEqual((state.cursor, state.steps["b"].status), ("b", StepStatus.FAILED))
        self.assertNotIn("c", state.steps)
        self.assertFalse(self.store.is_held(state.run_id))

    def test_a_step_class_that_cannot_be_constructed_fails_cleanly(self):
        engine = self.engine(LINEAR)

        def broken(_definition):
            raise TypeError("constructor exploded")

        engine.registry.register("b", broken)
        state = engine.start()
        self.assertEqual(state.status, RunStatus.FAILED)
        self.assertIn("could not be constructed", state.steps["b"].error)
        self.assertEqual(state.steps["b"].executions, 1)  # not retried


class Retry(EngineCase):
    def test_retryable_failures_are_retried_with_backoff_then_succeed(self):
        self.script.set("b", StepResult.failed("flaky"), RuntimeError("boom"))
        state = self.engine(LINEAR).start()
        self.assertEqual(state.status, RunStatus.COMPLETED)
        self.assertEqual(state.steps["b"].executions, 3)
        self.assertEqual(self.sleeps, [1.0, 2.0])
        self.assertEqual(self.names(Events.STEP_RETRIED), [Events.STEP_RETRIED] * 2)

    def test_retries_are_bounded(self):
        self.script.set("b", *[StepResult.failed("down")] * 10)
        state = self.engine(LINEAR).start()
        self.assertEqual(state.status, RunStatus.FAILED)
        self.assertEqual(self.script.executed().count("b"), 3)


class Resume(EngineCase):
    def test_resume_continues_at_the_failed_step_and_reruns_nothing_that_succeeded(self):
        self.script.set("b", *[StepResult.failed("down")] * 3)
        engine = self.engine(LINEAR)
        failed = engine.start()
        self.script.calls.clear()
        state = engine.resume(failed.run_id)
        self.assertEqual(state.status, RunStatus.COMPLETED)
        self.assertEqual(self.script.executed(), ["b", "c"])
        self.assertEqual(state.steps["a"].executions, 1)

    def test_resume_clears_a_pause_request_its_dead_driver_never_honoured(self):
        self.script.set("b", StepResult.blocked("stop"))
        engine = self.engine(LINEAR)
        run = engine.start()
        self.store.request(run.run_id, "pause")  # asked of a driver that then went away
        state = engine.resume(run.run_id)
        self.assertNotEqual(state.status, RunStatus.PAUSED)
        self.assertFalse(self.store.requested(run.run_id, "pause"))


class Pause(EngineCase):
    def test_pause_stops_at_the_next_boundary_and_resume_continues(self):
        engine = self.engine(LINEAR)

        def a(inputs, context):
            engine.request_pause(context.run_id)
            return StepResult.success([ArtifactOutput("art-a", {"x": 1})])

        self.script.set("a", a)
        state = engine.start()
        self.assertEqual((state.status, state.cursor), (RunStatus.PAUSED, "b"))
        self.assertEqual(engine.resume(state.run_id).status, RunStatus.COMPLETED)
        self.assertEqual(self.script.executed(), ["a", "b", "c"])

    def test_pausing_a_crashed_run_takes_effect_at_once_under_the_lock(self):
        engine = self.engine(LINEAR)
        run = engine.start(scope="a")
        state = self.store.load(run.run_id)
        state.status = RunStatus.RUNNING
        self.store.save(state)
        self.assertEqual(engine.request_pause(run.run_id).status, RunStatus.PAUSED)
        self.assertFalse(self.store.is_held(run.run_id))


class Cancel(EngineCase):
    def test_cancel_between_steps(self):
        engine = self.engine(LINEAR)

        def a(inputs, context):
            engine.request_cancel(context.run_id)
            return StepResult.success([ArtifactOutput("art-a", {"x": 1})])

        self.script.set("a", a)
        state = engine.start()
        self.assertEqual(state.status, RunStatus.CANCELLED)
        self.assertEqual(self.script.executed(), ["a"])
        with self.assertRaises(EngineError):
            engine.resume(state.run_id)

    @unittest.skipUnless(os.name == "posix" and shutil.which("sleep"), "needs POSIX sleep")
    def test_cancel_terminates_a_running_child_process_and_is_not_retried(self):
        engine = self.engine(LINEAR)
        seen = {}

        def a(inputs, context):
            result = procs.run(["sleep", "30"], heartbeat_seconds=0.2, grace_seconds=1)
            seen["status"], seen["pid"] = result.status, result.pid
            return StepResult.failed(f"child ended: {result.status}")  # retryable

        self.script.set("a", a)
        errors = []

        def canceller():
            deadline = time.monotonic() + 15
            while not procs.live_groups() and time.monotonic() < deadline:
                time.sleep(0.02)
            try:
                engine.request_cancel("run-1")
            except Exception as exc:  # pragma: no cover - reported below
                errors.append(exc)

        thread = threading.Thread(target=canceller)
        began = time.monotonic()
        thread.start()
        state = engine.start()
        thread.join(10)
        self.assertEqual(errors, [])
        self.assertLess(time.monotonic() - began, 15)
        self.assertEqual(state.status, RunStatus.CANCELLED)
        self.assertEqual(self.store.load("run-1").status, RunStatus.CANCELLED)
        self.assertEqual(seen["status"], "cancelled")
        self.assertEqual(self.script.executed(), ["a"])  # never retried
        self.assertNotIn(Events.STEP_RETRIED, self.names())
        self.assertNotIn(Events.WORKFLOW_FAILED, self.names())
        self.assertEqual(state.steps["a"].message, "cancelled while running")
        self.assertIsNone(state.steps["a"].pid)
        self.assertFalse(self.store.requested("run-1", "cancel"))
        self.assertFalse(procs._alive(seen["pid"]))
        kinds = [e["data"]["kind"] for e in self.events if e["event"] == Events.STEP_PROGRESS]
        self.assertIn("cancelled", kinds)


class HumanGate(EngineCase):
    def test_waits_for_a_decision_then_continues(self):
        engine = self.engine(CHECKPOINT.replace("GATE", "G2"))
        run = engine.start()
        self.assertEqual((run.status, run.cursor), (RunStatus.WAITING, "review"))
        state = engine.resume(run.run_id, decision="approve", note="looks right")
        self.assertEqual(state.status, RunStatus.COMPLETED)
        self.assertEqual(state.decisions["review"]["decision"], "approve")

    def test_a_decision_answers_one_visit_and_is_not_replayed_on_the_next(self):
        engine = self.engine(CHECKPOINT.replace("GATE", "G2"))
        run = engine.start()
        state = engine.resume(run.run_id, decision="rework")
        self.assertEqual(state.status, RunStatus.WAITING)  # asked again, not auto-reworked
        self.assertEqual(state.decisions["review"]["visit"], 1)
        self.assertEqual(state.steps["review"].visits, 2)
        state = engine.resume(run.run_id, decision="approve")
        self.assertEqual(state.status, RunStatus.COMPLETED)
        self.assertEqual(state.decisions["review"]["visit"], 2)
        self.assertEqual(self.script.executed(), ["strategy", "strategy", "design"])

    def test_an_irreversible_gate_refuses_automation(self):
        engine = self.engine(CHECKPOINT.replace("GATE", "G6"))
        run = engine.start(params={"auto_approve": ["G6"]})
        self.assertEqual(run.status, RunStatus.WAITING)
        state = engine.resume(run.run_id, decision="approve", decided_by="automation")
        self.assertEqual(state.status, RunStatus.WAITING)

    def test_a_rejected_gate_cannot_be_stepped_over_by_naming_a_later_step(self):
        engine = self.engine(CHECKPOINT.replace("GATE", "G2"))
        run = engine.start()
        state = engine.resume(run.run_id, decision="reject")
        self.assertEqual(state.status, RunStatus.BLOCKED)
        with self.assertRaisesRegex(EngineError, "review is BLOCKED"):
            engine.continue_in(run.run_id, "design")
        with self.assertRaisesRegex(EngineError, "review is BLOCKED"):
            engine.resume(run.run_id, from_step="design")
        self.assertNotIn("design", self.script.executed())

    def test_a_pending_irreversible_gate_cannot_be_stepped_over(self):
        engine = self.engine(CHECKPOINT.replace("GATE", "G4"))
        run = engine.start()
        self.assertEqual(run.status, RunStatus.WAITING)
        with self.assertRaisesRegex(EngineError, "review is WAITING"):
            engine.continue_in(run.run_id, "design")
        self.assertNotIn("design", self.script.executed())

    def test_a_gate_this_run_never_reached_cannot_be_stepped_over(self):
        engine = self.engine(CHECKPOINT.replace("GATE", "G3"))
        run = engine.start(scope="strategy")
        self.assertEqual(run.status, RunStatus.COMPLETED)
        with self.assertRaisesRegex(EngineError, r"gate G3\) has not been passed"):
            engine.continue_in(run.run_id, "design")

    def test_an_approved_gate_lets_a_later_step_run_again(self):
        engine = self.engine(CHECKPOINT.replace("GATE", "G2"))
        run = engine.start()
        engine.resume(run.run_id, decision="approve")
        state = engine.continue_in(run.run_id, "design", force=True)
        self.assertEqual(state.status, RunStatus.COMPLETED)
        self.assertEqual(self.script.executed().count("design"), 2)


class MaxVisits(EngineCase):
    def test_a_loop_blocks_at_its_limit_instead_of_spinning(self):
        self.script.set("verify", *[defects()] * 50)
        engine = self.engine(LOOP)
        state = engine.start()
        self.assertEqual(state.status, RunStatus.BLOCKED)
        self.assertIn("loop limit", state.message)
        self.assertEqual(self.script.executed().count("develop"), 3)
        self.assertEqual(len(state.trail), 6)  # bounded: 3 x (develop, verify)

    def test_a_cycle_through_completed_steps_is_bounded_even_when_skipping(self):
        cycle = """
workflow:
  id: cycle
  version: 1
  defaults:
    retry: {max_attempts: 1}
    max_visits: 2
  steps:
    - id: a
      type: a
      next: b
    - id: b
      type: b
      next: a
"""
        engine = self.engine(cycle)
        state = engine.start()
        self.assertEqual(state.status, RunStatus.BLOCKED)
        executed = len(self.script.calls)
        # continue_in skips completed steps; a cycle of them must still terminate.
        again = engine.continue_in(state.run_id, None)
        self.assertEqual(again.status, RunStatus.BLOCKED)
        self.assertIn("loop limit", again.message)
        self.assertLessEqual(len(self.script.calls) - executed, 4)


class VerifyDevelopLoop(EngineCase):
    def test_a_failed_verification_routes_back_to_development_then_passes(self):
        self.script.set("verify", defects())
        state = self.engine(LOOP).start()
        self.assertEqual(state.status, RunStatus.COMPLETED)
        self.assertEqual(self.script.executed(),
                         ["develop", "verify", "develop", "verify", "release"])
        self.assertEqual(state.latest_artifact("build").version, 2)
        self.assertEqual(state.steps["verify"].consumed, ["build@v2"])

    def test_the_loop_blocks_at_max_visits_and_resume_grants_a_fresh_budget(self):
        self.script.set("verify", *[defects()] * 3)
        engine = self.engine(LOOP)
        state = engine.start()
        self.assertEqual(state.status, RunStatus.BLOCKED)
        self.assertEqual(state.cursor, "develop")
        resumed = engine.resume(state.run_id)
        self.assertEqual(resumed.status, RunStatus.COMPLETED)
        self.assertEqual(resumed.steps["develop"].visits, 4)


class StaleRunResume(EngineCase):
    def crashed_run(self):
        engine = self.engine(LINEAR)
        run = engine.start(scope="a")
        state = self.store.load(run.run_id)
        state.status, state.cursor, state.scope = RunStatus.RUNNING, "b", ["a", "b", "c"]
        step = state.step("b")
        step.status, step.visits, step.attempts = StepStatus.RUNNING, 1, 1
        step.started_at = step.last_activity_at = "2026-01-01T00:00:00.000Z"
        step.pid = DEAD_PID
        self.store.save(state)
        with open(os.path.join(self.store.run_dir(run.run_id), "lock"), "w") as handle:
            handle.write(f"{DEAD_PID}\n")  # its driver died holding the lock
        return engine, run.run_id

    def test_a_crashed_run_reads_as_stale(self):
        _engine, run_id = self.crashed_run()
        state = self.store.load(run_id)
        live = derive_liveness(state, self.store.lock_owner(run_id), utc(2026, 1, 1, 0, 0, 5))
        self.assertEqual(live["liveness"], Liveness.STALE)

    def test_resume_takes_over_the_dead_lock_and_reruns_only_the_interrupted_step(self):
        engine, run_id = self.crashed_run()
        self.script.calls.clear()
        state = engine.resume(run_id)
        self.assertEqual(state.status, RunStatus.COMPLETED)
        self.assertEqual(self.script.executed(), ["b", "c"])
        self.assertEqual(state.steps["a"].executions, 1)
        self.assertFalse(os.path.exists(os.path.join(self.store.run_dir(run_id), "lock")))

    def test_a_crash_after_a_step_succeeded_does_not_execute_it_again(self):
        # The driver recorded b's SUCCESS, then died before the cursor moved on.
        engine = self.engine(LINEAR)
        run = engine.start(scope="a")
        engine.continue_in(run.run_id, "b")
        state = self.store.load(run.run_id)
        self.assertEqual(state.steps["b"].status, StepStatus.SUCCESS)
        state.status, state.cursor, state.scope, state.exit = (
            RunStatus.RUNNING, "b", ["a", "b", "c"], None)
        self.store.save(state)
        with open(os.path.join(self.store.run_dir(run.run_id), "lock"), "w") as handle:
            handle.write(f"{DEAD_PID}\n")
        self.script.calls.clear()
        state = engine.resume(run.run_id)
        self.assertEqual(state.status, RunStatus.COMPLETED)
        self.assertEqual(self.script.executed(), ["c"])
        self.assertEqual(state.steps["b"].executions, 1)


class ConcurrentRunLock(EngineCase):
    def blocked_run(self):
        self.script.set("b", StepResult.blocked("stop"))
        engine = self.engine(LINEAR)
        return engine, engine.start()

    @unittest.skipUnless(shutil.which("sleep"), "needs sleep")
    def test_a_run_driven_by_another_live_process_is_refused(self):
        engine, run = self.blocked_run()
        other = subprocess.Popen(["sleep", "30"])
        self.addCleanup(other.wait)
        self.addCleanup(other.kill)
        lock = os.path.join(self.store.run_dir(run.run_id), "lock")
        with open(lock, "w") as handle:
            handle.write(f"{other.pid}\n")
        before = self.store.load(run.run_id).to_dict()
        with self.assertRaises(RunLocked):
            engine.resume(run.run_id)
        with self.assertRaises(RunLocked):
            engine.continue_in(run.run_id, "b")
        self.assertEqual(self.store.load(run.run_id).to_dict(), before)
        with open(lock) as handle:
            self.assertEqual(handle.read().strip(), str(other.pid))  # never removed

    def test_a_second_driver_in_the_same_process_is_refused(self):
        engine = self.engine(LINEAR)
        running, go, caught = threading.Event(), threading.Event(), []

        def b(inputs, context):
            running.set()
            go.wait(10)
            return StepResult.success([ArtifactOutput("art-b", {"x": 1})])

        self.script.set("b", b)

        def intruder():
            running.wait(10)
            try:
                engine.resume("run-1")
            except RunLocked as exc:
                caught.append(exc)
            finally:
                go.set()

        thread = threading.Thread(target=intruder)
        thread.start()
        state = engine.start()
        thread.join(10)
        self.assertEqual(len(caught), 1)
        self.assertEqual(state.status, RunStatus.COMPLETED)
        self.assertEqual(self.script.executed(), ["a", "b", "c"])


class Determinism(unittest.TestCase):
    """Two identical runs, fixed clock and run id: identical state and identical events."""

    DEFINITION = """
workflow:
  id: determinism
  version: 1
  defaults:
    retry: {max_attempts: 3, backoff: exponential, delay_seconds: 1}
    max_visits: 3
  steps:
    - id: develop
      type: develop
      outputs: [build]
    - id: verify
      type: verify
      inputs: [build]
      outputs: [report]
      on: {fail: develop}
    - id: review
      type: human-checkpoint
      with: {gate: G2}
    - id: release
      type: release
      inputs: [report]
"""

    def run_once(self):
        case = EngineCase("run")
        case.setUp()
        self.addCleanup(case.doCleanups)
        case.script.set("develop", StepResult.failed("flaky"))  # a retry
        case.script.set("verify", defects())                   # a loop
        state = case.engine(self.DEFINITION).start(params={"auto_approve": ["G2"]})
        return state.to_dict(), case.events, case.store.read_events(state.run_id)

    def test_identical_runs_produce_identical_state_and_event_sequences(self):
        first_state, first_events, first_log = self.run_once()
        second_state, second_events, second_log = self.run_once()
        self.assertEqual(first_state["status"], RunStatus.COMPLETED)
        self.assertEqual(first_state, second_state)
        self.assertEqual(first_events, second_events)
        self.assertEqual(first_log, second_log)
        self.assertEqual(first_log, first_events)


class InputContracts(EngineCase):
    """An input is checked at the boundary before the step that consumes it runs."""

    def engine_with(self, validator):
        engine = self.engine(LINEAR)
        engine.artifact_validator = validator
        return engine

    def test_an_input_that_fails_its_contract_fails_the_step_non_retryably(self):
        def validator(artifact_type, content):
            # Outputs are accepted when produced; the contract "changes" before b runs.
            if artifact_type == "art-a" and validator.strict:
                return ["art-a: missing required title"]
            return []

        validator.strict = False
        engine = self.engine_with(validator)
        self.script.set("c", StepResult.blocked("stop"))
        run = engine.start()
        validator.strict = True
        state = engine.resume(run.run_id, from_step="b")
        self.assertEqual(state.status, RunStatus.FAILED)
        error = state.steps["b"].error
        for fragment in ("art-a@v1", "produced by a", "missing required title"):
            self.assertIn(fragment, error)
        self.assertEqual(state.steps["b"].executions, 2)  # 1 before, 1 now: not retried
        self.assertEqual(self.script.executed().count("b"), 1)  # the step never ran again

    def test_a_tampered_input_is_a_clean_failure_naming_it(self):
        self.script.set("c", StepResult.blocked("stop"))
        engine = self.engine(LINEAR)
        run = engine.start()
        ref = run.latest_artifact("art-b")
        path = os.path.join(self.store.run_dir(run.run_id), *ref.location.split("/"))
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({"edited": True}, handle)
        state = engine.resume(run.run_id)
        self.assertEqual(state.status, RunStatus.FAILED)
        self.assertIn("art-b@v1", state.steps["c"].error)
        self.assertIn("changed on disk", state.steps["c"].error)

    def test_a_missing_input_file_is_a_clean_failure_naming_it(self):
        self.script.set("c", StepResult.blocked("stop"))
        engine = self.engine(LINEAR)
        run = engine.start()
        ref = run.latest_artifact("art-b")
        os.remove(os.path.join(self.store.run_dir(run.run_id), *ref.location.split("/")))
        state = engine.resume(run.run_id)
        self.assertEqual(state.status, RunStatus.FAILED)
        self.assertIn("art-b@v1", state.steps["c"].error)
        self.assertIn("missing", state.steps["c"].error)

    def test_a_validator_that_raises_is_reported_not_propagated(self):
        def validator(artifact_type, content):
            raise RuntimeError("schema store offline")

        state = self.engine_with(validator).start()
        self.assertEqual(state.status, RunStatus.FAILED)
        self.assertIn("contract check itself failed", state.steps["a"].error)


class ContinueIn(EngineCase):
    def test_continue_in_skips_completed_steps_and_refuses_running_or_cancelled(self):
        engine = self.engine(LINEAR)
        run = engine.start(scope="middle")
        self.script.calls.clear()
        state = engine.continue_in(run.run_id, None)
        self.assertEqual(self.script.executed(), ["a"])
        self.assertEqual(state.status, RunStatus.COMPLETED)

        crashed = self.store.load(run.run_id)
        crashed.status = RunStatus.RUNNING
        self.store.save(crashed)
        with self.assertRaises(EngineError):
            engine.continue_in(run.run_id, "b")
        self.assertFalse(self.store.is_held(run.run_id))  # refused, and the lock let go

    def test_newest_artifact_of_a_type_is_by_production_order_not_timestamp(self):
        engine = self.engine(LINEAR)

        def a(inputs, context):
            return StepResult.success([ArtifactOutput("art-a", {"n": 1}, name="first"),
                                       ArtifactOutput("art-a", {"n": 2}, name="second")])

        seen = {}

        def b(inputs, context):
            seen["a"] = inputs.load("art-a")
            return StepResult.success([ArtifactOutput("art-b", {"x": 1})])

        self.script.set("a", a)
        self.script.set("b", b)
        engine.clock = lambda: "2026-01-01T00:00:00.000Z"  # every write in the same ms
        state = engine.start()
        self.assertEqual(state.status, RunStatus.COMPLETED)
        self.assertEqual(seen["a"], {"n": 2})
        self.assertEqual([state.latest_artifact(i).seq for i in ("first", "second")], [1, 2])


def utc(*parts):
    return datetime.datetime(*parts, tzinfo=datetime.timezone.utc)


class LivenessDerivation(unittest.TestCase):
    """derive_liveness is pure: state, lock owner and a clock in; a dict out."""

    def state(self, status=RunStatus.RUNNING, step_status=StepStatus.RUNNING,
              activity="2026-01-01T00:00:00.000Z"):
        state = RunState(run_id="r1", workflow_id="w", workflow_version=1, status=status,
                         cursor="build", scope=["build"],
                         updated_at="2026-01-01T00:00:00.000Z")
        state.steps["build"] = StepState(
            status=step_status, attempts=2, visits=1, started_at="2026-01-01T00:00:00.000Z",
            last_activity_at=activity, pid=4242, last_event="heartbeat")
        return state

    def test_running_hung_and_stale(self):
        state = self.state(activity="2026-01-01T00:04:00.000Z")
        live = derive_liveness(state, 77, utc(2026, 1, 1, 0, 5, 0), 300)
        self.assertEqual(live["liveness"], Liveness.RUNNING)
        self.assertEqual((live["step"], live["attempt"], live["pid"], live["driver_pid"]),
                         ("build", 2, 4242, 77))
        self.assertEqual(live["elapsed_seconds"], 300.0)
        self.assertEqual(live["idle_seconds"], 60.0)
        self.assertEqual(live["last_event"], "heartbeat")

        self.assertEqual(derive_liveness(state, 77, utc(2026, 1, 1, 0, 9, 1), 300)["liveness"],
                         Liveness.HUNG)
        self.assertEqual(derive_liveness(state, 77, utc(2026, 1, 1, 0, 9, 1), 600)["liveness"],
                         Liveness.RUNNING)
        self.assertEqual(derive_liveness(state, None, utc(2026, 1, 1, 0, 4, 1))["liveness"],
                         Liveness.STALE)

    def test_waiting_and_terminal_states_name_themselves(self):
        for status in (RunStatus.WAITING, RunStatus.PAUSED, RunStatus.BLOCKED,
                       RunStatus.FAILED, RunStatus.COMPLETED, RunStatus.CANCELLED,
                       RunStatus.PENDING):
            with self.subTest(status):
                live = derive_liveness(self.state(status=status, step_status=StepStatus.FAILED),
                                       None, utc(2026, 1, 2))
                self.assertEqual(live["liveness"], status.lower())
                self.assertIn(live["liveness"], Liveness.ALL)

    def test_a_finished_run_reports_its_last_step(self):
        state = self.state(status=RunStatus.COMPLETED, step_status=StepStatus.SUCCESS)
        state.cursor = None
        state.steps["build"].duration_ms = 1500
        state.trail.append({"step": "build"})
        live = derive_liveness(state, None, utc(2026, 1, 2))
        self.assertEqual((live["step"], live["elapsed_seconds"]), ("build", 1.5))

    def test_threshold_comes_from_config(self):
        self.assertEqual(FactoryConfig().hung_after_seconds, 300)
        config = FactoryConfig({"execution": {"hung_after_seconds": 42}})
        self.assertEqual(config.hung_after_seconds, 42)
        self.assertEqual(FactoryConfig({"execution": {"hung_after_seconds": -1}})
                         .hung_after_seconds, 300)


class StatusCommand(unittest.TestCase):
    """`wgf status` shows the current step's liveness, as text and as --json."""

    def setUp(self):
        self.scratch = tempfile.mkdtemp(prefix="wgf-core-status-")
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)
        self.store_dir = os.path.join(self.scratch, "store")
        self.config = os.path.join(self.scratch, "factory.yaml")
        with open(self.config, "w", encoding="utf-8") as handle:
            handle.write("factory:\n  storage:\n    fsync: false\n"
                         "  execution:\n    hung_after_seconds: 60\n")

    def wgf(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = wgf.main([*args, "--store", self.store_dir, "--config", self.config])
        return code, out.getvalue(), err.getvalue()

    def crash(self, activity):
        code, _, _ = self.wgf("develop", "--mock", "--quiet")
        self.assertEqual(code, 0)
        store = RunStore(self.store_dir, fsync=False)
        state = store.latest()
        step = state.step("develop")
        state.status, state.cursor = RunStatus.RUNNING, "develop"
        step.status, step.pid, step.last_event = StepStatus.RUNNING, 4242, "heartbeat"
        step.started_at = step.last_activity_at = activity
        state.updated_at = activity
        store.save(state)
        return store, state.run_id

    def test_stale_run_text_and_json(self):
        store, run_id = self.crash("2026-01-01T00:00:00.000Z")
        code, out, _ = self.wgf("status", run_id)
        self.assertEqual(code, 0)
        self.assertIn("Status: RUNNING", out)
        self.assertIn("Step:     develop", out)
        self.assertIn("Liveness: stale", out)
        self.assertIn("child pid 4242", out)
        self.assertIn(f"--resume {run_id}", out)

        code, out, _ = self.wgf("status", run_id, "--json")
        live = json.loads(out)["liveness"]
        for key in ("run_id", "step", "attempt", "status", "started_at", "last_activity_at",
                    "pid", "last_event", "elapsed_seconds", "liveness"):
            self.assertIn(key, live)
        self.assertEqual((live["liveness"], live["hung_after_seconds"]), ("stale", 60))
        self.assertEqual(RunState.from_dict(json.loads(out)).run_id, run_id)

    def test_hung_run_uses_the_configured_threshold(self):
        store, run_id = self.crash("2026-01-01T00:00:00.000Z")
        store.acquire(run_id)  # this process plays the live driver
        self.addCleanup(store.release, run_id)
        code, out, _ = self.wgf("status", run_id)
        self.assertIn("Liveness: hung", out)
        self.assertIn("hung_after_seconds", out)

    def test_a_running_run(self):
        now = datetime.datetime.now(datetime.timezone.utc)
        stamp = now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"
        store, run_id = self.crash(stamp)
        store.acquire(run_id)
        self.addCleanup(store.release, run_id)
        _, out, _ = self.wgf("status", run_id, "--json")
        self.assertEqual(json.loads(out)["liveness"]["liveness"], "running")
        self.assertEqual(json.loads(out)["liveness"]["driver_pid"], os.getpid())


class TestCoreCommand(unittest.TestCase):
    """`wgf test-core` over a fake suite: every result, the counts and the exit code."""

    def setUp(self):
        self.tests_dir = tempfile.mkdtemp(prefix="wgf-core-suite-")
        self.addCleanup(shutil.rmtree, self.tests_dir, ignore_errors=True)
        self.tag = f"t{os.getpid()}_{id(self)}"
        bodies = {
            "passing": "    def test_a(self): pass\n    def test_b(self): pass\n",
            "failing": "    def test_a(self): self.fail('no')\n    def test_b(self): pass\n",
            "skipping": "    @unittest.skip('later')\n    def test_a(self): pass\n",
            "empty": "    pass\n",
        }
        for name, body in bodies.items():
            with open(os.path.join(self.tests_dir, f"{self.tag}_{name}.py"), "w") as handle:
                handle.write(f"import unittest\n\nclass T(unittest.TestCase):\n{body}")
        self.addCleanup(self.forget)

    def forget(self):
        for name in list(sys.modules):
            if name.startswith(self.tag):
                del sys.modules[name]
        if self.tests_dir in sys.path:
            sys.path.remove(self.tests_dir)

    def suite(self):
        t = self.tag
        return {"GOOD": [f"{t}_passing"], "BAD": [f"{t}_failing", f"{t}_passing"],
                "LATER": [f"{t}_skipping"], "NOTHING": [f"{t}_empty"],
                "ABSENT": [f"{t}_passing", f"{t}_not_written_yet"]}

    def test_results_and_counts(self):
        rows = {r["category"]: r for r in wgf.run_core_suite(self.suite(), self.tests_dir)}
        self.assertEqual({k: r["result"] for k, r in rows.items()},
                         {"GOOD": "PASS", "BAD": "FAIL", "LATER": "SKIP", "NOTHING": "SKIP",
                          "ABSENT": "MISSING"})
        bad = rows["BAD"]
        self.assertEqual((bad["tests"], bad["passed"], bad["failed"]), (4, 3, 1))
        self.assertEqual(rows["ABSENT"]["missing"], [f"{self.tag}_not_written_yet"])
        self.assertEqual(rows["LATER"]["skipped"], 1)
        table = wgf.render_core_table(list(rows.values()))
        self.assertIn("FAILED", table)
        self.assertIn("MISSING", table)

    def test_only_and_unknown_category(self):
        rows = wgf.run_core_suite(self.suite(), self.tests_dir, only=["good"])
        self.assertEqual([(r["category"], r["result"]) for r in rows], [("GOOD", "PASS")])
        with self.assertRaises(ValueError):
            wgf.run_core_suite(self.suite(), self.tests_dir, only=["NOPE"])

    def test_the_shipped_mapping_names_every_category(self):
        suite = wgf.load_core_suite()
        self.assertEqual(list(suite), ["WORKFLOW", "AGENTS", "CONTRACTS", "VERIFY", "RELEASE",
                                       "2D GOLDEN", "3D GOLDEN", "PROCESS CLEANUP", "SECURITY"])
        self.assertIn("test_core_workflow", suite["WORKFLOW"])
        self.assertIn("test_core_persistence", suite["WORKFLOW"])

    def test_exit_code_is_non_zero_when_anything_fails_or_is_missing(self):
        original = wgf.load_core_suite
        suite = self.suite()
        wgf.load_core_suite = lambda: suite
        original_run = wgf.run_core_suite
        wgf.run_core_suite = lambda s, only=None: original_run(s, self.tests_dir, only)
        try:
            for only, code in ((["GOOD"], 0), (["LATER"], 0), (["BAD"], 1), (["ABSENT"], 1)):
                with self.subTest(only):
                    out = io.StringIO()
                    args = ["test-core", "--json"] + [a for o in only for a in ("--only", o)]
                    with contextlib.redirect_stdout(out):
                        self.assertEqual(wgf.main(args), code)
                    self.assertEqual(json.loads(out.getvalue())["ok"], code == 0)
        finally:
            wgf.load_core_suite = original
            wgf.run_core_suite = original_run


if __name__ == "__main__":
    unittest.main()

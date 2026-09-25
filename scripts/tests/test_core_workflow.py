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
import re
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
from test_workflow_engine import (  # noqa: E402
    CHECKPOINT, LINEAR, LOOP, EngineCase)
from wgflib import procs  # noqa: E402
from wgflib.workflow import checkpoint, integrity  # noqa: E402
from wgflib.workflow.api import RunRequest, WorkflowAPI, ended_by_decision  # noqa: E402
from wgflib.workflow.config import ConfigError, FactoryConfig  # noqa: E402
from wgflib.workflow.engine import EngineError, WorkflowEngine  # noqa: E402
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
from wgflib.workflow.step import WorkflowStep  # noqa: E402
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

    def test_an_approval_does_not_cover_work_redone_after_it(self):
        engine = self.engine(CHECKPOINT.replace("GATE", "G3"))
        run = engine.start()
        engine.resume(run.run_id, decision="approve")
        engine.continue_in(run.run_id, "strategy", force=True)  # new, unreviewed strategy
        with self.assertRaisesRegex(EngineError, "strategy has since replaced"):
            engine.continue_in(run.run_id, "design", force=True)

    def test_a_whole_run_continued_after_upstream_work_is_redone_asks_the_gate_again(self):
        engine = self.engine(CHECKPOINT.replace("GATE", "G3"))
        run = engine.start()
        engine.resume(run.run_id, decision="approve")
        engine.continue_in(run.run_id, "strategy", force=True)
        self.script.calls.clear()
        state = engine.continue_in(run.run_id, "gated")  # skip mode over the whole workflow
        self.assertEqual((state.status, state.cursor), (RunStatus.WAITING, "review"))
        self.assertNotIn("design", self.script.executed())

    def test_a_checkpoint_without_a_named_gate_still_gates(self):
        engine = self.engine(CHECKPOINT.replace("{gate: GATE, ", "{"))
        run = engine.start(scope="strategy")
        with self.assertRaisesRegex(EngineError, "gate checkpoint\\) has not been passed"):
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


    def test_a_crash_after_the_last_step_succeeded_completes_on_resume(self):
        engine = self.engine(LINEAR)
        run = engine.start()
        state = self.store.load(run.run_id)
        self.assertEqual(state.status, RunStatus.COMPLETED)
        state.status, state.cursor, state.exit = RunStatus.RUNNING, "c", None
        self.store.save(state)
        with open(os.path.join(self.store.run_dir(run.run_id), "lock"), "w") as handle:
            handle.write(f"{DEAD_PID}\n")
        self.script.calls.clear()
        state = engine.resume(run.run_id)
        self.assertEqual((state.status, state.cursor), (RunStatus.COMPLETED, None))
        self.assertEqual(self.script.executed(), [])
        on_disk = self.store.load(run.run_id)
        self.assertEqual(on_disk.status, RunStatus.COMPLETED)
        self.assertFalse(os.path.exists(os.path.join(self.store.run_dir(run.run_id), "lock")))


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
      outputs: [report, title-strategy]
      on: {fail: develop}
    - id: review
      type: human-checkpoint
      inputs: [title-strategy]       # what G2 is decided on (gates.yaml)
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
        self.assertIn(f"wgf resume {run_id}", out)

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
    """`wgf test-core` over a fake suite: every result, the counts, the skips and the exit
    code - with and without --strict."""

    def setUp(self):
        self.tests_dir = tempfile.mkdtemp(prefix="wgf-core-suite-")
        self.addCleanup(shutil.rmtree, self.tests_dir, ignore_errors=True)
        self.tag = f"t{os.getpid()}_{id(self)}"
        bodies = {
            "passing": "    def test_a(self): pass\n    def test_b(self): pass\n",
            "failing": "    def test_a(self): self.fail('no')\n    def test_b(self): pass\n",
            "skipping": "    @unittest.skip('later')\n    def test_a(self): pass\n",
            "empty": "    pass\n",
            # One test ran and passed, three skipped for two reasons: the category is PASS,
            # and the run is still incomplete.
            "partial": ("    def test_a(self): pass\n"
                        "    @unittest.skip('set WGF_X=1')\n    def test_b(self): pass\n"
                        "    @unittest.skip('set WGF_X=1')\n    def test_c(self): pass\n"
                        "    def test_d(self): self.skipTest('no npx')\n"),
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
                "ABSENT": [f"{t}_passing", f"{t}_not_written_yet"],
                "PARTIAL": [f"{t}_partial", f"{t}_passing"]}

    def test_results_and_counts(self):
        rows = {r["category"]: r for r in wgf.run_core_suite(self.suite(), self.tests_dir)}
        self.assertEqual({k: r["result"] for k, r in rows.items()},
                         {"GOOD": "PASS", "BAD": "FAIL", "LATER": "SKIP", "NOTHING": "SKIP",
                          "ABSENT": "MISSING", "PARTIAL": "PASS"})
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

    def main(self, *argv):
        """(exit code, stdout) of `wgf test-core ...` over the fake suite."""
        suite = self.suite()
        original, original_run = wgf.load_core_suite, wgf.run_core_suite
        wgf.load_core_suite = lambda: suite
        wgf.run_core_suite = lambda s, only=None: original_run(s, self.tests_dir, only)
        try:
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = wgf.main(["test-core", *argv])
            return code, out.getvalue()
        finally:
            wgf.load_core_suite, wgf.run_core_suite = original, original_run

    @staticmethod
    def only(*categories):
        return [a for c in categories for a in ("--only", c)]

    def test_exit_code_is_non_zero_when_anything_fails_or_is_missing(self):
        for only, code in ((["GOOD"], 0), (["LATER"], 0), (["PARTIAL"], 0), (["BAD"], 1),
                           (["ABSENT"], 1)):
            with self.subTest(only):
                got, out = self.main("--json", *self.only(*only))
                self.assertEqual(got, code)
                self.assertEqual(json.loads(out)["ok"], code == 0)

    def test_strict_fails_a_skipped_category_with_its_own_exit_code(self):
        # 4 is not 1: skipped is "not proved here", failed is "broken". FAIL still wins. A
        # PASS category with opt-in tests skipped (PARTIAL) was proved; it is listed, not failed.
        self.assertNotEqual(wgf.EXIT_INCOMPLETE, wgf.EXIT_FAILED)
        for only, code in ((["GOOD"], 0), (["LATER"], 4), (["NOTHING"], 4), (["PARTIAL"], 0),
                           (["GOOD", "LATER"], 4), (["BAD", "LATER"], 1), (["ABSENT"], 1)):
            with self.subTest(only):
                got, out = self.main("--strict", "--json", *self.only(*only))
                self.assertEqual(got, code)
                report = json.loads(out)
                self.assertEqual((report["ok"], report["strict"]), (code == 0, True))

    def test_a_skip_never_reads_as_a_bare_ok(self):
        code, out = self.main(*self.only("GOOD"))
        self.assertEqual(code, 0)
        self.assertEqual(out.strip().splitlines()[-1], "Core Acceptance Suite: OK (2 tests)")
        self.assertNotIn("Skipped tests", out)

        code, out = self.main(*self.only("GOOD", "LATER", "PARTIAL"))
        self.assertEqual(code, 0)
        summary = out.strip().splitlines()[-1]
        self.assertTrue(summary.startswith("Core Acceptance Suite: OK (INCOMPLETE"), summary)
        self.assertIn("skipped: LATER", summary)
        self.assertIn("3 tests skipped in PASS categories", summary)

        code, out = self.main("--strict", *self.only("GOOD", "LATER"))
        self.assertEqual(code, 4)
        summary = out.strip().splitlines()[-1]
        self.assertTrue(summary.startswith("Core Acceptance Suite: INCOMPLETE ("), summary)
        self.assertIn("--strict", summary)
        self.assertNotIn("OK", summary)

        code, out = self.main("--strict", *self.only("BAD", "LATER"))
        self.assertEqual(code, 1)
        # Failure details follow the table; the summary line is still the table's last.
        self.assertIn("Core Acceptance Suite: FAILED (", out)
        self.assertNotIn("Core Acceptance Suite: OK", out)
        self.assertNotIn("Core Acceptance Suite: INCOMPLETE", out)

    def test_skipped_tests_are_listed_by_category_and_reason(self):
        rows = {r["category"]: r for r in wgf.run_core_suite(self.suite(), self.tests_dir,
                                                              only=["PARTIAL", "LATER"])}
        partial = rows["PARTIAL"]
        self.assertEqual((partial["result"], partial["tests"], partial["passed"],
                          partial["skipped"]), ("PASS", 6, 3, 3))
        t = self.tag
        self.assertEqual(sorted((s["id"], s["reason"]) for s in partial["skips"]),
                         [(f"{t}_partial.T.test_b", "set WGF_X=1"),
                          (f"{t}_partial.T.test_c", "set WGF_X=1"),
                          (f"{t}_partial.T.test_d", "no npx")])
        self.assertEqual(rows["LATER"]["skips"],
                         [{"id": f"{t}_skipping.T.test_a", "reason": "later"}])
        lines = wgf.render_core_skips(list(rows.values()))
        self.assertIn("[PARTIAL] 3 skipped", lines)
        self.assertIn("  set WGF_X=1 (2)", lines)
        self.assertIn("  no npx (1)", lines)
        self.assertIn(f"    {t}_partial.T.test_d", lines)
        self.assertIn("[LATER] 1 skipped", lines)
        # Each id sits under its own reason.
        reason = lines.index("  no npx (1)")
        self.assertEqual(lines[reason + 1], f"    {t}_partial.T.test_d")

        code, out = self.main(*self.only("PARTIAL"))
        self.assertIn("Skipped tests, by category and reason:", out)
        self.assertIn(f"{t}_partial.T.test_b", out)

    def test_json_names_every_skip_and_what_was_incomplete(self):
        code, out = self.main("--json", *self.only("GOOD", "LATER", "PARTIAL"))
        report = json.loads(out)
        self.assertEqual(code, 0)
        self.assertEqual((report["complete"], report["skipped_categories"],
                          report["skipped_in_pass"], report["strict"]),
                         (False, ["LATER"], 3, False))
        by_category = {r["category"]: r for r in report["categories"]}
        self.assertEqual(len(by_category["PARTIAL"]["skips"]), 3)
        self.assertEqual(by_category["GOOD"]["skips"], [])
        code, out = self.main("--json", *self.only("GOOD"))
        self.assertEqual((json.loads(out)["complete"], json.loads(out)["skipped_categories"]),
                         (True, []))

    def test_a_class_skipped_in_set_up_class_is_listed(self):
        with open(os.path.join(self.tests_dir, f"{self.tag}_classwide.py"), "w") as handle:
            handle.write("import unittest\n\nclass T(unittest.TestCase):\n"
                         "    @classmethod\n    def setUpClass(cls):\n"
                         "        raise unittest.SkipTest('pinned template unavailable')\n"
                         "    def test_a(self): pass\n    def test_b(self): pass\n")
        rows = wgf.run_core_suite({"WHOLE": [f"{self.tag}_classwide", f"{self.tag}_passing"]},
                                  self.tests_dir)
        self.assertEqual(rows[0]["result"], "PASS")
        self.assertEqual([s["reason"] for s in rows[0]["skips"]],
                         ["pinned template unavailable"])
        self.assertFalse(wgf.core_completeness(rows)["complete"])
        # Listed as incomplete, but the category itself ran: --strict does not fail it.
        self.assertEqual(wgf.core_exit_code(rows, strict=True), wgf.EXIT_OK)
        self.assertEqual(wgf.core_exit_code(rows + [dict(rows[0], category="GONE",
                                                         result="SKIP")], strict=True),
                         wgf.EXIT_INCOMPLETE)

# -- run params, --from past a gate, cancel during backoff, visit inflation --------------


GROUPED = CHECKPOINT.replace("  version: 1\n", "  version: 1\n  groups:\n"
                             "    plan: [strategy, review, design]\n", 1)


class RunParamsIntegrity(EngineCase):
    """state.params decide mock vs real and which gates approve themselves; resume reads
    them from state.json, so they are corroborated against WORKFLOW_STARTED first."""

    def gated(self, gate="G3"):
        return self.engine(CHECKPOINT.replace("GATE", gate))

    def edit_params(self, run_id, **changes):
        state = self.store.load(run_id)
        for key, value in changes.items():
            if value is None:
                state.params.pop(key, None)
            else:
                state.params[key] = value
        self.store.save(state)

    def rewrite_started(self, run_id, change):
        """Rewrite events.jsonl with `change(record)` applied to WORKFLOW_STARTED; a
        change returning None drops the event."""
        path = os.path.join(self.store.run_dir(run_id), "events.jsonl")
        records = self.store.read_events(run_id)
        with open(path, "w", encoding="utf-8") as handle:
            for record in records:
                if record["event"] == Events.WORKFLOW_STARTED:
                    record = change(record)
                if record is not None:
                    handle.write(json.dumps(record, sort_keys=True) + "\n")

    def make_legacy(self, run_id):
        """What a run created before params were recorded looks like."""
        def strip(record):
            record["data"].pop("params")
            return record
        self.rewrite_started(run_id, strip)

    def test_workflow_started_records_the_params(self):
        params = {"mock": True, "mock_plan": {"strategy": ["success"]}, "auto_approve": ["G2"]}
        run = self.gated().start(params=params)
        started = [e for e in self.store.read_events(run.run_id)
                   if e["event"] == Events.WORKFLOW_STARTED]
        self.assertEqual(len(started), 1)
        self.assertEqual(started[0]["data"]["params"], params)

    def test_untouched_params_resume_normally(self):
        engine = self.gated()
        run = engine.start(params={"auto_approve": ["G2"]})
        self.assertEqual(run.status, RunStatus.WAITING)  # G3 is not in auto_approve
        state = engine.resume(run.run_id, decision="approve")
        self.assertEqual(state.status, RunStatus.COMPLETED)

    def test_params_edited_in_state_json_are_refused_before_anything_runs(self):
        edits = {
            "auto-approve added": {"auto_approve": ["G3"]},
            "real run turned mock": {"mock": True},
            "mock plan injected": {"mock_plan": {"design": ["success"]}},
            "unknown param added": {"extra": 1},
        }
        for label, change in edits.items():
            with self.subTest(label):
                engine = self.gated()
                run = engine.start()
                self.edit_params(run.run_id, **change)
                before = self.store.load(run.run_id).to_dict()
                calls = list(self.script.calls)
                key = next(iter(change))
                with self.assertRaisesRegex(EngineError, rf"params\.{key} .* started with"):
                    engine.resume(run.run_id, decision="approve")
                with self.assertRaisesRegex(EngineError, rf"params\.{key}"):
                    engine.continue_in(run.run_id, "design")
                self.assertEqual(self.store.load(run.run_id).to_dict(), before)
                self.assertEqual(self.script.calls, calls)
                self.assertFalse(self.store.is_held(run.run_id))

    def test_removing_or_changing_a_recorded_param_is_refused(self):
        for label, change in (("mock removed", {"mock": None}),
                              ("auto_approve narrowed", {"auto_approve": []})):
            with self.subTest(label):
                engine = self.gated()
                run = engine.start(params={"mock": True, "auto_approve": ["G2"]})
                self.edit_params(run.run_id, **change)
                with self.assertRaisesRegex(EngineError, "started with"):
                    engine.resume(run.run_id, decision="approve")

    def test_a_second_start_event_with_other_params_is_refused(self):
        engine = self.gated()
        run = engine.start()
        path = os.path.join(self.store.run_dir(run.run_id), "events.jsonl")
        forged = dict(self.store.read_events(run.run_id)[0])
        forged["data"] = dict(forged["data"], params={"auto_approve": ["G3"]})
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(forged) + "\n")
        with self.assertRaisesRegex(EngineError, "different params"):
            engine.resume(run.run_id, decision="approve")

    def test_a_legacy_run_without_guarded_params_is_accepted(self):
        engine = self.gated()
        run = engine.start()
        self.make_legacy(run.run_id)
        state = engine.resume(run.run_id, decision="approve")
        self.assertEqual(state.status, RunStatus.COMPLETED)

    def test_a_legacy_run_with_no_start_event_at_all_is_accepted_when_plain(self):
        engine = self.gated()
        run = engine.start()
        self.rewrite_started(run.run_id, lambda record: None)
        state = engine.resume(run.run_id, decision="approve")
        self.assertEqual(state.status, RunStatus.COMPLETED)

    def test_a_legacy_run_with_falsy_guarded_params_is_accepted(self):
        engine = self.gated()
        run = engine.start(params={"mock": False, "auto_approve": []})
        self.make_legacy(run.run_id)
        self.assertEqual(engine.resume(run.run_id, decision="approve").status,
                         RunStatus.COMPLETED)

    def test_a_legacy_run_claiming_mock_or_auto_approve_is_refused_fail_closed(self):
        for params in ({"mock": True}, {"auto_approve": ["G3"]},
                       {"mock": True, "mock_plan": {"design": ["success"]}}):
            with self.subTest(params):
                engine = self.gated()
                run = engine.start(params=params)
                if params.get("auto_approve"):
                    self.assertEqual(run.status, RunStatus.COMPLETED)
                    continue  # auto-approved to the end; checked on a waiting run below
                self.make_legacy(run.run_id)
                with self.assertRaisesRegex(EngineError, "Start a new run") as caught:
                    engine.resume(run.run_id, decision="approve")
                for key in params:
                    self.assertIn(key, str(caught.exception))
                # The advice works: without the unverifiable params it resumes, gated.
                for key in params:
                    self.edit_params(run.run_id, **{key: None})
                state = engine.resume(run.run_id, decision="approve")
                self.assertEqual(state.status, RunStatus.COMPLETED)
                self.assertEqual(state.decisions["review"]["decided_by"], "human")

    def test_a_legacy_run_given_auto_approve_by_an_edit_is_refused(self):
        engine = self.gated()
        run = engine.start()
        self.make_legacy(run.run_id)
        self.edit_params(run.run_id, auto_approve=["G3"])
        with self.assertRaisesRegex(EngineError, "auto_approve .*Start a new run"):
            engine.resume(run.run_id)
        self.assertEqual(self.store.load(run.run_id).status, RunStatus.WAITING)


class FromPastAGate(EngineCase):
    """A fresh run's explicit --from must not step over a gate inside its scope: a fresh
    run has passed none. The narrow form of plan item P0-7, as decided by the lead."""

    def test_from_past_a_gate_is_refused_and_creates_nothing(self):
        engine = self.engine(CHECKPOINT.replace("GATE", "G2"))
        with self.assertRaisesRegex(EngineError, r"step over review \(gate G2\)") as caught:
            engine.start(start_at="design")
        self.assertIn("--resume <run-id> --from design", str(caught.exception))
        self.assertEqual(self.store.list_runs(), [])
        self.assertEqual(self.script.executed(), [])

    def test_from_before_every_gate_is_allowed(self):
        engine = self.engine(CHECKPOINT.replace("GATE", "G2"))
        run = engine.start(start_at="strategy")
        self.assertEqual((run.status, run.cursor), (RunStatus.WAITING, "review"))

    def test_from_past_a_gate_inside_a_group_is_refused(self):
        engine = self.engine(GROUPED.replace("GATE", "G2"))
        with self.assertRaisesRegex(EngineError, r"gate G2"):
            engine.start(scope="plan", start_at="design")
        self.assertEqual(self.store.list_runs(), [])

    def test_a_checkpoint_without_a_named_gate_is_still_a_gate(self):
        engine = self.engine(CHECKPOINT.replace("{gate: GATE, ", "{"))
        with self.assertRaisesRegex(EngineError, r"gate checkpoint"):
            engine.start(start_at="design")

    def test_a_fresh_single_step_run_is_unaffected(self):
        engine = self.engine(CHECKPOINT.replace("GATE", "G2"))
        self.assertEqual(engine.start(scope="design").status, RunStatus.COMPLETED)
        self.assertEqual(engine.start(scope="design", start_at="design").status,
                         RunStatus.COMPLETED)


class FromPastAGateThroughTheCli(unittest.TestCase):
    """The same refusal on the shipped new-game workflow, through `wgf`."""

    def setUp(self):
        self.scratch = tempfile.mkdtemp(prefix="wgf-core-from-")
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)
        self.store_dir = os.path.join(self.scratch, "store")
        self.config = os.path.join(self.scratch, "factory.yaml")
        with open(self.config, "w", encoding="utf-8") as handle:
            handle.write("factory:\n  storage:\n    fsync: false\n")

    def wgf(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = wgf.main([*args, "--store", self.store_dir, "--config", self.config])
        return code, out.getvalue(), err.getvalue()

    def runs(self):
        return RunStore(self.store_dir, fsync=False).list_runs()

    def test_new_game_from_design_is_refused(self):
        code, _, err = self.wgf("new-game", "--mock", "--from", "design", "--quiet")
        self.assertEqual(code, 2)
        self.assertIn("strategy-review (gate G2)", err)
        self.assertEqual(self.runs(), [])

    def test_new_game_from_init_names_both_gates(self):
        code, _, err = self.wgf("new-game", "--mock", "--from", "init", "--quiet")
        self.assertEqual(code, 2)
        self.assertIn("gate G2", err)
        self.assertIn("gate G3", err)

    def test_plan_from_design_is_refused(self):
        code, _, err = self.wgf("plan", "--mock", "--from", "design", "--quiet")
        self.assertEqual(code, 2)
        self.assertIn("gate G2", err)
        self.assertEqual(self.runs(), [])

    def test_new_game_from_strategy_is_allowed(self):
        code, _, err = self.wgf("new-game", "--mock", "--from", "strategy", "--quiet")
        self.assertEqual(code, 3, err)  # runs to G4, which waits for a person
        (state,) = self.runs()
        self.assertEqual((state.status, state.cursor), (RunStatus.WAITING, "prototype-review"))
        self.assertNotIn("research", state.steps)

    def test_a_fresh_single_step_command_is_unaffected(self):
        code, _, err = self.wgf("verify", "--mock", "--quiet")
        self.assertEqual(code, 0, err)


BACKOFF = LINEAR.replace("delay_seconds: 1}", "delay_seconds: 7}")


class CancelDuringBackoff(EngineCase):
    """The backoff sleeps under the run's lock; a cancel must not wait for it to end."""

    def cancelling_sleep(self, run_id, after):
        def sleep(seconds):
            self.sleeps.append(seconds)
            if len(self.sleeps) == after:
                self.store.request(run_id, "cancel")
        return sleep

    def test_a_cancel_during_backoff_ends_the_run_without_the_next_attempt(self):
        engine = self.engine(BACKOFF)
        engine.sleep = self.cancelling_sleep("run-1", after=2)
        self.script.set("b", StepResult.failed("flaky"))
        state = engine.start()
        self.assertEqual(state.status, RunStatus.CANCELLED)
        self.assertEqual(self.script.executed(), ["a", "b"])        # no second attempt
        self.assertEqual(self.sleeps, [2.0, 2.0])                    # noticed within a slice
        on_disk = self.store.load("run-1")
        self.assertEqual(on_disk.status, RunStatus.CANCELLED)
        self.assertEqual(on_disk.steps["b"].executions, 1)
        self.assertEqual(on_disk.steps["b"].attempts, 1)
        self.assertEqual(on_disk.steps["b"].status, StepStatus.FAILED)
        started = [e for e in self.store.read_events("run-1")
                   if e["event"] == Events.STEP_STARTED and e.get("step_id") == "b"]
        self.assertEqual(len(started), 1)
        self.assertFalse(self.store.requested("run-1", "cancel"))
        self.assertFalse(self.store.is_held("run-1"))

    def test_a_cancel_arriving_with_the_failure_skips_the_backoff(self):
        engine = self.engine(BACKOFF)

        def b(inputs, context):
            self.store.request(context.run_id, "cancel")
            return StepResult.failed("flaky")  # retryable, but cancelled while running

        self.script.set("b", b)
        state = engine.start()
        self.assertEqual(state.status, RunStatus.CANCELLED)
        self.assertEqual(self.sleeps, [])

    def test_an_uncancelled_backoff_sleeps_its_whole_delay_in_bounded_slices(self):
        self.script.set("b", StepResult.failed("flaky"))
        state = self.engine(BACKOFF).start()
        self.assertEqual(state.status, RunStatus.COMPLETED)
        self.assertEqual(sum(self.sleeps), 7.0)
        self.assertTrue(all(0 < s <= 2.0 for s in self.sleeps), self.sleeps)


class Crash(BaseException):
    """A simulated process death: nothing in the engine catches it."""


class VisitInflation(EngineCase):
    """A crash between counting a visit and moving the cursor must not cost a visit."""

    def test_a_crash_while_following_a_route_does_not_burn_a_visit(self):
        engine = self.engine(LINEAR)
        real_save, fired = self.store.save, []

        def save(state):
            # The first save that puts the cursor on b: the driver dies right there.
            if state.cursor == "b" and not fired:
                fired.append(True)
                raise Crash("killed while following a's route to b")
            return real_save(state)

        self.store.save = save
        with self.assertRaises(Crash):
            engine.start()
        self.store.save = real_save

        on_disk = self.store.load("run-1")
        self.assertEqual((on_disk.cursor, on_disk.steps["a"].status), ("a", StepStatus.SUCCESS))
        self.assertEqual(on_disk.step("b").visits, 0)  # nothing half-counted on disk

        with open(os.path.join(self.store.run_dir("run-1"), "lock"), "w") as handle:
            handle.write(f"{DEAD_PID}\n")
        self.script.calls.clear()
        state = self.engine(LINEAR).resume("run-1")
        self.assertEqual(state.status, RunStatus.COMPLETED)
        self.assertEqual(self.script.executed(), ["b", "c"])
        self.assertEqual(state.steps["a"].executions, 1)
        self.assertEqual(state.steps["b"].visits, 1)


# -- G4: the prototype review, between verify and release (M4a) ------------------------------


class _MockNewGame(unittest.TestCase):
    """The shipped new-game workflow, mock steps, in process: WorkflowAPI as `wgf` builds it."""

    def setUp(self):
        self.scratch = tempfile.mkdtemp(prefix="wgf-core-g4-")
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)
        self.store_dir = os.path.join(self.scratch, "store")

    def api(self, checkpoints=None, clock=None):
        data = {"storage": {"fsync": False}}
        if checkpoints is not None:
            data["checkpoints"] = checkpoints
        return WorkflowAPI(config=FactoryConfig(data), store_dir=self.store_dir, clock=clock)

    def start(self, api=None, **request):
        api = api or self.api()
        return api, api.run(RunRequest(mock=True, **request))

    @staticmethod
    def executed(state):
        return [entry["step"] for entry in state.trail]


class PrototypeReviewGate(_MockNewGame):
    """G4 `prototype-review`: after verify PASS, before release; only a person decides it."""

    EVIDENCE = ("qa-report", "verification-report", "prototype-report")

    def test_a_mock_new_game_stops_at_g4_after_verify_and_before_release(self):
        api, state = self.start()
        self.assertEqual((state.status, state.cursor), (RunStatus.WAITING, "prototype-review"))
        executed = self.executed(state)
        self.assertEqual(executed[-2:], ["verify", "prototype-review"])
        self.assertNotIn("release", executed)
        self.assertIsNone(state.latest_artifact("release-manifest"))
        # G2 and G3 are reversible and a mock run approves them itself; G4 it never does.
        self.assertEqual(state.steps["strategy-review"].status, StepStatus.SUCCESS)
        self.assertEqual(state.steps["tech-plan-review"].status, StepStatus.SUCCESS)
        pending = api.pending(state)
        self.assertEqual((pending["gate"], pending["choices"]), ("G4", ["pass", "iterate", "kill"]))
        self.assertIsNone(pending["timeout"])

    def test_g4_consumes_the_evidence_verify_produced(self):
        _, state = self.start()
        consumed = set(state.steps["prototype-review"].consumed)
        for artifact_type in self.EVIDENCE:
            ref = state.latest_of_type(artifact_type)
            self.assertIn(f"{ref.id}@v{ref.version}", consumed)
        self.assertEqual(state.latest_of_type("qa-report").produced_by, "verify")

    def test_pass_releases(self):
        api, run = self.start()
        state = api.run(RunRequest(resume=run.run_id, decision="pass", note="criteria hold",
                                   decided_by="human"))
        self.assertEqual(state.status, RunStatus.COMPLETED, state.message)
        self.assertEqual(self.executed(state)[-2:], ["prototype-review", "release"])
        self.assertIsNotNone(state.latest_artifact("release-manifest"))
        self.assertEqual(state.decisions["prototype-review"]["decision"], "pass")
        recorded = [e for e in api.store.read_events(run.run_id)
                    if e["event"] == Events.DECISION_RECORDED
                    and e.get("step_id") == "prototype-review"]
        self.assertEqual([e["data"]["decided_by"] for e in recorded], ["human"])
        self.assertIsNone(ended_by_decision(state))
        self.assertEqual(wgf.exit_code(state), wgf.EXIT_OK)

    def test_automation_cannot_answer_g4(self):
        api, run = self.start()
        for choice in ("pass", "kill", "iterate"):
            state = api.run(RunRequest(resume=run.run_id, decision=choice,
                                       decided_by="automation"))
            self.assertEqual((state.status, state.cursor),
                             (RunStatus.WAITING, "prototype-review"), choice)
        self.assertNotIn("release", self.executed(state))
        self.assertNotIn("develop", self.executed(state)[-3:])

    def test_iterate_goes_back_to_develop_and_asks_again(self):
        api, run = self.start()
        first_qa = run.latest_of_type("qa-report")
        state = api.run(RunRequest(resume=run.run_id, decision="iterate", decided_by="human",
                                   note="the core loop is unclear"))
        self.assertEqual((state.status, state.cursor), (RunStatus.WAITING, "prototype-review"))
        executed = self.executed(state)
        at = executed.index("prototype-review")
        # waited, answered iterate, the loop, and waiting again
        self.assertEqual(executed[at:], ["prototype-review", "prototype-review", "develop",
                                         "review", "sdk", "sdk-review", "verify",
                                         "prototype-review"])
        self.assertEqual(state.steps["prototype-review"].visits, 2)
        # The iterate answered visit 1; visit 2 needs a decision of its own.
        self.assertEqual(state.decisions["prototype-review"]["visit"], 1)
        # The lineage stands: new evidence is a new version, the old one is kept.
        newest = state.latest_of_type("qa-report")
        self.assertEqual(newest.version, first_qa.version + 1)
        self.assertEqual(integrity.state_problems(state, api.definition_for(state)), [])
        # Release is still impossible: G4's last answer did not pass it.
        with self.assertRaisesRegex(EngineError, "prototype-review is WAITING"):
            api.run(RunRequest(run_id=run.run_id, scope="release"))
        state = api.run(RunRequest(resume=run.run_id, decision="pass", decided_by="human"))
        self.assertEqual(state.status, RunStatus.COMPLETED, state.message)
        release_consumed = state.steps["release"].consumed
        self.assertIn(f"{newest.id}@v{newest.version}", release_consumed)

    def test_kill_ends_the_run_auditably_and_releases_nothing(self):
        api, run = self.start()
        state = api.run(RunRequest(resume=run.run_id, decision="kill", decided_by="human",
                                   note="kill criterion K1 breached"))
        self.assertEqual(state.status, RunStatus.COMPLETED)
        self.assertEqual(state.exit, {"step": "prototype-review", "route": "kill",
                                      "outcome": StepOutcome.BLOCKED, "next": "$end"})
        self.assertIn("killed at prototype-review (G4)", state.message)
        self.assertEqual(state.steps["prototype-review"].status, StepStatus.BLOCKED)
        self.assertNotIn("release", self.executed(state))
        self.assertIsNone(state.latest_artifact("release-manifest"))
        ended = ended_by_decision(state)
        self.assertEqual((ended["decision"], ended["decided_by"]), ("kill", "human"))
        events = api.store.read_events(run.run_id)
        names = [e["event"] for e in events]
        self.assertIn(Events.DECISION_RECORDED, names)
        self.assertIn(Events.STEP_BLOCKED, names)
        completed = [e for e in events if e["event"] == Events.WORKFLOW_COMPLETED][-1]
        self.assertEqual(completed["data"]["exit"]["route"], "kill")
        self.assertTrue(integrity.decision_on_record(events, "prototype-review",
                                                     state.decisions["prototype-review"]))
        # A kill is a legitimate end, not a failure: exit 0, and the status says so.
        self.assertEqual(wgf.exit_code(state), wgf.EXIT_OK)
        self.assertEqual(wgf.status_exit_code(state), wgf.EXIT_OK)
        rendered = wgf.render_status(state, api.definition_for(state))
        self.assertIn("Ended:  kill at G4 (prototype-review), decided by human", rendered)
        # And final: nothing in this run can start again, release least of all.
        for scope in ("release", "develop", "new-game"):
            with self.assertRaisesRegex(EngineError, "cannot be continued"):
                api.run(RunRequest(run_id=run.run_id, scope=scope))
        with self.assertRaisesRegex(EngineError, "only .* runs can be resumed"):
            api.run(RunRequest(resume=run.run_id, from_step="release"))

    def test_resume_at_g4_without_a_decision_keeps_waiting(self):
        api, run = self.start()
        since = run.steps["prototype-review"].waiting_since
        self.assertIsNotNone(since)
        state = api.run(RunRequest(resume=run.run_id))
        self.assertEqual((state.status, state.cursor), (RunStatus.WAITING, "prototype-review"))
        self.assertEqual(state.steps["prototype-review"].visits, 1)
        self.assertEqual(state.steps["prototype-review"].waiting_since, since)
        self.assertEqual(self.executed(state).count("verify"), 1)
        state = api.run(RunRequest(resume=run.run_id, decision="pass", decided_by="human"))
        self.assertEqual(state.status, RunStatus.COMPLETED, state.message)

    def test_verification_rerun_after_a_pass_asks_g4_again(self):
        # Release fails after the pass; the person reruns verification: the pass covered the
        # old evidence only, so G4 waits for a new decision before release can run again.
        api, run = self.start(mock_plan={"release": ["fatal"]})
        state = api.run(RunRequest(resume=run.run_id, decision="pass", decided_by="human"))
        self.assertEqual((state.status, state.cursor), (RunStatus.FAILED, "release"))
        state = api.run(RunRequest(resume=run.run_id, from_step="verify"))
        self.assertEqual((state.status, state.cursor), (RunStatus.WAITING, "prototype-review"))
        self.assertEqual(state.steps["prototype-review"].visits, 2)
        self.assertEqual(self.executed(state).count("release"), 1)

    def test_verification_rerun_after_a_completed_release_supersedes_the_pass(self):
        api, run = self.start()
        api.run(RunRequest(resume=run.run_id, decision="pass", decided_by="human"))
        api.run(RunRequest(run_id=run.run_id, scope="verify", force=True))
        with self.assertRaisesRegex(EngineError, "prototype-review \\(gate G4\\) approved work "
                                                 "that verify has since replaced"):
            api.run(RunRequest(run_id=run.run_id, scope="release", force=True))
        # The whole workflow continued in skip mode reaches G4 and asks again.
        state = api.run(RunRequest(run_id=run.run_id, scope="new-game"))
        self.assertEqual((state.status, state.cursor), (RunStatus.WAITING, "prototype-review"))

    def test_release_run_past_an_unanswered_g4_is_refused(self):
        api, run = self.start()
        with self.assertRaisesRegex(EngineError, "prototype-review is WAITING"):
            api.run(RunRequest(run_id=run.run_id, scope="release"))
        state = api.store.load(run.run_id)
        self.assertNotIn("release", self.executed(state))

    def test_a_new_run_from_release_is_refused(self):
        with self.assertRaisesRegex(EngineError, "prototype-review \\(gate G4\\)"):
            self.start(from_step="release")
        self.assertEqual(RunStore(self.store_dir, fsync=False).list_runs(), [])

    def test_g4_is_never_auto_approved_even_when_configured(self):
        api = self.api(checkpoints={"auto_approve": ["G2", "G3", "G4"]})
        _, state = self.start(api, hold_gates=True)
        self.assertEqual((state.status, state.cursor), (RunStatus.WAITING, "prototype-review"))


class GateAnsweredWithoutPassing(EngineCase):
    """A gate whose last answer sent work back is answered, not passed."""

    def test_a_later_step_is_refused_after_a_backward_answer(self):
        engine = self.engine(CHECKPOINT.replace("GATE", "G4"))
        run = engine.start()
        self.script.set("strategy", StepResult.blocked("rework needs a person"))
        state = engine.resume(run.run_id, decision="rework")
        self.assertEqual(state.status, RunStatus.BLOCKED)
        self.assertEqual(state.steps["review"].status, StepStatus.SUCCESS)
        with self.assertRaisesRegex(EngineError, "was last answered 'rework', which does "
                                                 "not pass it"):
            engine.continue_in(run.run_id, "design")
        self.assertNotIn("design", self.script.executed())
        self.assertEqual(engine.gates_passed(state), [])

    def test_a_run_stopped_past_a_gate_it_never_had_is_not_resumed_past_it(self):
        # Started before the gate was in the workflow, and failed after where it now sits.
        legacy = ("workflow:\n  id: gated\n  version: 1\n  steps:\n"
                  "    - id: strategy\n      type: strategy\n"
                  "    - id: design\n      type: design\n")
        self.script.set("design", StepResult.failed("boom", retryable=False))
        run = self.engine(legacy).start()
        self.assertEqual((run.status, run.cursor), (RunStatus.FAILED, "design"))
        engine = self.engine(CHECKPOINT.replace("GATE", "G4"))
        with self.assertRaisesRegex(EngineError, "review \\(gate G4\\) has not been passed"):
            engine.resume(run.run_id)
        self.assertEqual(self.script.executed(), ["strategy", "design"])

    def test_gates_passed_names_passed_current_gates(self):
        engine = self.engine(CHECKPOINT.replace("GATE", "G2"))
        run = engine.start()
        state = engine.resume(run.run_id, decision="approve")
        self.assertEqual(engine.gates_passed(state), ["G2"])
        engine.continue_in(run.run_id, "strategy", force=True)
        self.assertEqual(engine.gates_passed(self.store.load(run.run_id)), [])

    def test_a_gate_waits_for_input_until_the_run_holds_what_it_is_decided_on(self):
        text = ("workflow:\n  id: gated\n  version: 1\n  steps:\n"
                "    - id: strategy\n      type: strategy\n      outputs: [qa-report]\n"
                "    - id: review\n      type: human-checkpoint\n"
                "      inputs: [qa-report, verification-report, prototype-report]\n"
                "      with: {gate: G4, choices: [pass, iterate, kill]}\n"
                "    - id: design\n      type: design\n")
        engine = self.engine(text)
        run = engine.start()
        self.assertEqual(run.status, RunStatus.WAITING)
        self.assertEqual(run.trail[-1]["outcome"], StepOutcome.WAITING_FOR_INPUT)
        self.assertIn("verification-report, prototype-report", run.steps["review"].message)
        # A decision does not stand in for missing evidence.
        state = engine.resume(run.run_id, decision="pass")
        self.assertEqual(state.trail[-1]["outcome"], StepOutcome.WAITING_FOR_INPUT)
        self.assertNotIn("design", self.script.executed())

    def test_the_shipped_gates_are_decided_on_what_gates_yaml_requires(self):
        from wgflib.workflow.definition import load_definition
        definition = load_definition("new-game")
        gates = {step.params.get("gate"): step for step in definition.steps
                 if step.type == checkpoint.HumanCheckpointStep.type}
        self.assertEqual(set(gates), {"G2", "G3", "G4"})
        for gate, step in gates.items():
            required = checkpoint.required_artifacts(gate)
            self.assertTrue(required, gate)
            self.assertEqual([t for t in required if t not in step.inputs], [], gate)
            upstream = definition.step_ids[:definition.step_ids.index(step.id)]
            produced = {t for s in upstream for t in definition.step(s).outputs}
            self.assertEqual([t for t in required if t not in produced], [], gate)
        self.assertEqual(checkpoint.required_artifacts("G4"),
                         ["qa-report", "verification-report", "prototype-report",
                          "title-strategy", "game-design"])
        self.assertNotIn("asset-manifest", checkpoint.required_artifacts("G3"))
        ids = definition.step_ids
        self.assertEqual(ids[ids.index("verify") + 1], "prototype-review")
        self.assertEqual(ids[ids.index("prototype-review") + 1], "release")
        g4 = definition.step("prototype-review")
        self.assertEqual(g4.on, {"iterate": "develop", "kill": "$end"})
        self.assertEqual(definition.step("design").on, {"descope": "$fail"})


class DesignDescope(_MockNewGame):
    def test_a_failed_descope_is_routed_to_fail_explicitly(self):
        from wgflib.workflow.definition import load_definition
        from wgflib.workflow.step import StepRegistry
        definition = load_definition("new-game")
        registry = StepRegistry()
        checkpoint.register(registry)
        from wgflib.workflow import mock as mocks
        mocks.register(registry)

        class Descope(WorkflowStep):
            def execute(self, inputs, context):
                return StepResult("FAILED", route="descope", retryable=False,
                                  error="design consistency failed on R1: cut scope, do not "
                                        "relax the rules")

        registry.register("design", Descope)
        engine = WorkflowEngine(definition, registry, RunStore(self.store_dir, fsync=False),
                                artifact_validator=None)
        state = engine.start(scope="plan", params={"mock": True, "auto_approve": ["G2"]})
        self.assertEqual(state.status, RunStatus.FAILED)
        self.assertIn("cut scope", state.message)
        transition = [e for e in engine.store.read_events(state.run_id)
                      if e["event"] == Events.TRANSITION and e.get("step_id") == "design"][-1]
        self.assertEqual((transition["data"]["route"], transition["data"]["kind"]),
                         ("descope", "abort"))
        self.assertNotIn("tech-plan", self.executed(state))


# -- timeout auto-approval (M4b) --------------------------------------------------------------


class FrozenClock:
    """The engine clock, set by the test: every call returns `now` until it is moved."""

    def __init__(self, start="2026-03-01T00:00:00.000Z"):
        self.now = datetime.datetime.fromisoformat(start.replace("Z", "+00:00"))

    def __call__(self):
        return checkpoint.stamp(self.now)

    def advance(self, seconds):
        self.now += datetime.timedelta(seconds=seconds)


class TimeoutApproval(EngineCase):
    """factory.checkpoints.timeout_auto_approve, as the run's params carry it: a reversible
    gate approves itself on the first resume at or after waiting_since + window."""

    WINDOW = 600

    def setUp(self):
        super().setUp()
        self.clock = FrozenClock()

    def gated(self, gate="G2"):
        return self.engine(CHECKPOINT.replace("GATE", gate))

    def waiting(self, gate="G2", windows=None):
        engine = self.gated(gate)
        params = {"timeout_auto_approve": windows if windows is not None
                  else {gate: self.WINDOW}}
        run = engine.start(params=params)
        self.assertEqual((run.status, run.cursor), (RunStatus.WAITING, "review"))
        return engine, run

    def decisions(self, run_id):
        return [e for e in self.store.read_events(run_id)
                if e["event"] == Events.DECISION_RECORDED]

    def test_the_wait_is_recorded_from_the_engine_clock(self):
        engine, run = self.waiting()
        self.assertEqual(run.steps["review"].waiting_since, "2026-03-01T00:00:00.000Z")
        waited = [e for e in self.store.read_events(run.run_id)
                  if e["event"] == Events.STEP_WAITING][-1]
        self.assertEqual(waited["data"]["waiting_since"], "2026-03-01T00:00:00.000Z")
        self.assertEqual(waited["data"]["visit"], 1)

    def test_before_the_window_it_keeps_waiting_and_keeps_its_start(self):
        engine, run = self.waiting()
        self.clock.advance(self.WINDOW - 1)
        state = engine.resume(run.run_id)
        self.assertEqual((state.status, state.cursor), (RunStatus.WAITING, "review"))
        self.assertEqual(state.steps["review"].waiting_since, "2026-03-01T00:00:00.000Z")
        self.assertEqual(self.decisions(run.run_id), [])
        self.assertIn("approves itself on the first `wgf resume` at or after "
                      "2026-03-01T00:10:00.000Z", state.steps["review"].message)

    def test_exactly_at_the_window_it_approves(self):
        engine, run = self.waiting()
        self.clock.advance(self.WINDOW)
        state = engine.resume(run.run_id)
        self.assertEqual(state.status, RunStatus.COMPLETED, state.message)
        self.assertIn("design", self.script.executed())

    def test_after_the_window_it_approves_and_the_approval_is_on_record(self):
        engine, run = self.waiting()
        self.clock.advance(self.WINDOW * 10)
        state = engine.resume(run.run_id)
        self.assertEqual(state.status, RunStatus.COMPLETED, state.message)
        entry = state.decisions["review"]
        self.assertEqual((entry["decision"], entry["decided_by"], entry["mode"], entry["visit"]),
                         ("approve", "automation", "timeout", 1))
        self.assertIn("unanswered since 2026-03-01T00:00:00.000Z", entry["note"])
        (recorded,) = self.decisions(run.run_id)
        self.assertEqual(recorded["data"], entry)
        self.assertTrue(integrity.decision_on_record(self.store.read_events(run.run_id),
                                                     "review", entry))
        review = [t for t in state.trail if t["step"] == "review"]
        self.assertEqual((review[-1]["outcome"], review[-1]["route"]),
                         (StepOutcome.SUCCESS, "approve"))
        self.assertEqual(integrity.state_problems(state, engine.definition), [])

    def test_disabled_it_waits_for_ever(self):
        engine, run = self.waiting(windows={})
        self.clock.advance(365 * 86400)
        self.assertEqual(engine.resume(run.run_id).status, RunStatus.WAITING)
        self.assertEqual(self.decisions(run.run_id), [])

    def test_an_irreversible_or_unknown_gate_never_times_out(self):
        for gate in ("G4", "G6", "G7", "G9", "g2"):
            with self.subTest(gate):
                engine, run = self.waiting(gate=gate)
                self.clock.advance(self.WINDOW * 10)
                self.assertEqual(engine.resume(run.run_id).status, RunStatus.WAITING)
                self.assertEqual(self.decisions(run.run_id), [])

    def test_a_timeout_is_measured_per_visit(self):
        engine, run = self.waiting()
        self.clock.advance(60)
        state = engine.resume(run.run_id, decision="rework")  # visit 2 begins now
        self.assertEqual(state.steps["review"].visits, 2)
        self.assertEqual(state.steps["review"].waiting_since, checkpoint.stamp(self.clock.now))
        self.clock.advance(self.WINDOW - 60)  # the first visit's window has run out
        self.assertEqual(engine.resume(run.run_id).status, RunStatus.WAITING)
        self.clock.advance(60)
        self.assertEqual(engine.resume(run.run_id).status, RunStatus.COMPLETED)

    def test_upstream_work_redone_restarts_the_wait(self):
        engine, run = self.waiting()
        self.clock.advance(self.WINDOW - 10)
        engine.continue_in(run.run_id, "strategy", force=True)  # a new strategy
        self.clock.advance(20)  # past the old wait's window
        state = engine.continue_in(run.run_id, "gated")
        self.assertEqual((state.status, state.cursor), (RunStatus.WAITING, "review"))
        self.assertEqual(state.steps["review"].waiting_since, checkpoint.stamp(self.clock.now))
        self.assertEqual(self.decisions(run.run_id), [])
        self.clock.advance(self.WINDOW)
        self.assertEqual(engine.resume(run.run_id).status, RunStatus.COMPLETED)

    def test_a_wait_upstream_work_overtook_is_not_relied_on(self):
        # The same visit, with a success upstream after the wait began (a state the engine
        # avoids by entering the gate again; checked anyway): the wait does not count.
        engine, run = self.waiting()
        state = self.store.load(run.run_id)
        self.assertEqual(integrity.waiting_since(state, engine.definition, "review",
                                                 self.store.read_events(run.run_id)),
                         "2026-03-01T00:00:00.000Z")
        state.trail.append({"step": "strategy", "visit": 1, "attempt": 1,
                            "outcome": StepOutcome.SUCCESS, "route": "success",
                            "consumed": [], "at": "2026-03-01T00:00:00.000Z"})
        self.assertIsNone(integrity.waiting_since(state, engine.definition, "review",
                                                  self.store.read_events(run.run_id)))

    def test_a_backdated_wait_in_state_json_approves_nothing(self):
        engine, run = self.waiting()
        state = self.store.load(run.run_id)
        state.steps["review"].waiting_since = "2020-01-01T00:00:00.000Z"
        self.store.save(state)
        self.clock.advance(60)
        state = engine.resume(run.run_id)
        self.assertEqual(state.status, RunStatus.WAITING)
        self.assertEqual(self.decisions(run.run_id), [])
        # The wait starts again, from now.
        self.assertEqual(state.steps["review"].waiting_since, checkpoint.stamp(self.clock.now))

    def test_windows_added_to_state_json_are_refused(self):
        engine = self.gated()
        run = engine.start()
        state = self.store.load(run.run_id)
        state.params["timeout_auto_approve"] = {"G2": 1}
        self.store.save(state)
        with self.assertRaisesRegex(EngineError, "timeout_auto_approve"):
            engine.resume(run.run_id)


class TimeoutApprovalThroughTheApi(_MockNewGame):
    """The installation config snapshotted into the run; status reports, resume applies."""

    def test_windows_are_snapshotted_into_the_run_params(self):
        api = self.api(checkpoints={"timeout_auto_approve": {"G2": "48h", "G3": "30m"}})
        _, state = self.start(api, hold_gates=True)
        self.assertEqual(state.params["timeout_auto_approve"], {"G2": 172800, "G3": 1800})
        started = [e for e in api.store.read_events(state.run_id)
                   if e["event"] == Events.WORKFLOW_STARTED][0]
        self.assertEqual(started["data"]["params"]["timeout_auto_approve"],
                         {"G2": 172800, "G3": 1800})

    def test_a_run_without_windows_never_times_out(self):
        clock = FrozenClock()
        api = self.api(clock=clock)
        _, state = self.start(api, hold_gates=True)
        self.assertNotIn("timeout_auto_approve", state.params)
        clock.advance(365 * 86400)
        state = api.run(RunRequest(resume=state.run_id))
        self.assertEqual((state.status, state.cursor), (RunStatus.WAITING, "strategy-review"))

    def test_an_irreversible_or_unknown_gate_in_the_config_is_refused(self):
        for windows, named in (({"G2": "48h", "G4": "48h"}, "G4 (irreversible"),
                               ({"G6": "1d"}, "G6 (irreversible"),
                               ({"G9": "1h"}, "G9 (not a gate"),
                               ({"g2": "1h"}, "g2 (not a gate")):
            with self.subTest(windows):
                api = self.api(checkpoints={"timeout_auto_approve": windows})
                with self.assertRaisesRegex(ConfigError, re.escape(named)):
                    self.start(api)
                self.assertEqual(api.runs(), [])

    def test_a_bad_window_is_refused(self):
        for value in ("0h", "-1h", "1.5h", "soon", True, 0, [1]):
            with self.subTest(value):
                api = self.api(checkpoints={"timeout_auto_approve": {"G2": value}})
                with self.assertRaises(ConfigError):
                    self.start(api)

    def test_status_reports_and_only_resume_approves(self):
        clock = FrozenClock()
        api = self.api(checkpoints={"timeout_auto_approve": {"G2": "10m"}}, clock=clock)
        _, run = self.start(api, hold_gates=True)
        self.assertEqual(run.cursor, "strategy-review")
        state_file = os.path.join(api.store.run_dir(run.run_id), "state.json")
        events_file = os.path.join(api.store.run_dir(run.run_id), "events.jsonl")

        def snapshot():
            with open(state_file, "rb") as a, open(events_file, "rb") as b:
                return a.read(), b.read()

        before = snapshot()
        early = clock.now + datetime.timedelta(seconds=599)
        due = clock.now + datetime.timedelta(seconds=600)
        pending = api.pending(api.store.load(run.run_id), now=early)
        self.assertEqual(pending["timeout"]["eligible"], False)
        self.assertEqual(pending["timeout"]["eligible_at"], checkpoint.stamp(due))
        (waiting_state, waiting_pending), = api.waiting(now=due)
        self.assertEqual(waiting_pending["timeout"]["eligible"], True)
        self.assertIn("eligible for timeout approval since " + checkpoint.stamp(due),
                      wgf.render_timeout(waiting_pending["timeout"], run.run_id))
        self.assertEqual(snapshot(), before)  # looking changed nothing
        self.assertEqual(waiting_state.status, RunStatus.WAITING)

        # The engine agrees with what status said, at both instants.
        clock.now = early
        state = api.run(RunRequest(resume=run.run_id))
        self.assertEqual((state.status, state.cursor), (RunStatus.WAITING, "strategy-review"))
        clock.now = due
        state = api.run(RunRequest(resume=run.run_id))
        self.assertEqual(state.steps["strategy-review"].status, StepStatus.SUCCESS)
        self.assertEqual(state.decisions["strategy-review"]["mode"], "timeout")
        self.assertEqual((state.status, state.cursor), (RunStatus.WAITING, "tech-plan-review"))
        pending = api.pending(state, now=due + datetime.timedelta(days=30))
        self.assertIsNone(pending["timeout"])  # G3 has no window

    def test_status_and_runs_through_the_cli_report_without_approving(self):
        config = os.path.join(self.scratch, "factory.yaml")
        with open(config, "w", encoding="utf-8") as handle:
            handle.write("factory:\n  storage:\n    fsync: false\n  checkpoints:\n"
                         "    timeout_auto_approve: {G2: 1s}\n")

        def run(*args):
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = wgf.main([*args, "--store", self.store_dir, "--config", config])
            return code, out.getvalue(), err.getvalue()

        code, _, err = run("new-game", "--mock", "--hold-gates", "--quiet")
        self.assertEqual(code, wgf.EXIT_WAITING, err)
        (state,) = RunStore(self.store_dir, fsync=False).list_runs()
        time.sleep(1.2)
        for _ in range(2):  # looking twice changes nothing
            code, out, _ = run("status", state.run_id)
            self.assertEqual(code, wgf.EXIT_WAITING)
            self.assertIn("Timeout: G2 eligible for timeout approval since", out)
            code, out, _ = run("runs", "--waiting")
            self.assertIn("eligible for timeout approval since", out)
        self.assertEqual(RunStore(self.store_dir, fsync=False).load(state.run_id).decisions, {})
        code, out, _ = run("resume", state.run_id, "--quiet")
        after = RunStore(self.store_dir, fsync=False).load(state.run_id)
        self.assertEqual(after.decisions["strategy-review"]["mode"], "timeout")
        self.assertEqual(after.cursor, "tech-plan-review")


# -- M3: output liveness, the hung-child watchdog's params ------------------------------------

class OutputLiveness(unittest.TestCase):
    """A heartbeat shows the driver is alive, not that the child is working: a step whose
    child has written nothing for hung_output_seconds reads hung ("output") even while
    heartbeats keep arriving. derive_liveness stays pure."""

    def state(self, output="2026-01-01T00:00:00.000Z", beat="2026-01-01T00:09:55.000Z",
              pid=4242):
        state = RunState(run_id="r1", workflow_id="w", workflow_version=1,
                         status=RunStatus.RUNNING, cursor="build", scope=["build"],
                         updated_at="2026-01-01T00:09:55.000Z")
        state.steps["build"] = StepState(
            status=StepStatus.RUNNING, attempts=1, visits=1,
            started_at="2026-01-01T00:00:00.000Z", last_activity_at=beat, pid=pid,
            last_event="heartbeat", last_output_at=output, last_heartbeat_at=beat)
        return state

    NOW = utc(2026, 1, 1, 0, 10, 0)

    def test_a_silent_child_with_a_live_driver_reads_hung_output(self):
        live = derive_liveness(self.state(), 77, self.NOW, 300, 120)
        self.assertEqual((live["liveness"], live["hung_reason"]),
                         (Liveness.HUNG, Liveness.OUTPUT))
        self.assertEqual(live["idle_seconds"], 5.0)            # the driver is not idle
        self.assertEqual(live["output_idle_seconds"], 600.0)   # the child is
        self.assertEqual(live["last_output_at"], "2026-01-01T00:00:00.000Z")
        self.assertEqual(live["last_heartbeat_at"], "2026-01-01T00:09:55.000Z")
        self.assertEqual(live["hung_output_seconds"], 120)
        # Under the threshold it is running; the default threshold (900 s) is not met yet.
        self.assertEqual(derive_liveness(self.state(), 77, self.NOW, 300, 601)["liveness"],
                         Liveness.RUNNING)
        self.assertEqual(derive_liveness(self.state(), 77, self.NOW, 300)["liveness"],
                         Liveness.RUNNING)

    def test_a_chatty_child_stays_running(self):
        state = self.state(output="2026-01-01T00:09:58.000Z")
        live = derive_liveness(state, 77, self.NOW, 300, 120)
        self.assertEqual((live["liveness"], live["hung_reason"]), (Liveness.RUNNING, None))

    def test_no_child_or_no_heartbeat_is_never_output_hung(self):
        # Between children (pid None) the step is Factory code; with heartbeats off there is
        # nothing that says the driver is alive while the child is quiet.
        self.assertEqual(derive_liveness(self.state(pid=None), 77, self.NOW, 300, 1)["liveness"],
                         Liveness.RUNNING)
        state = self.state()
        state.steps["build"].last_heartbeat_at = None
        self.assertEqual(derive_liveness(state, 77, self.NOW, 300, 1)["liveness"],
                         Liveness.RUNNING)

    def test_a_silent_driver_is_hung_for_the_driver_and_stale_wins(self):
        live = derive_liveness(self.state(), 77, utc(2026, 1, 1, 0, 20, 0), 300, 120)
        self.assertEqual((live["liveness"], live["hung_reason"]),
                         (Liveness.HUNG, Liveness.DRIVER))
        live = derive_liveness(self.state(), None, self.NOW, 300, 120)
        self.assertEqual((live["liveness"], live["hung_reason"]), (Liveness.STALE, None))

    def test_state_written_before_the_new_fields_derives_as_before(self):
        old = {"status": StepStatus.RUNNING, "attempts": 2, "executions": 2, "visits": 1,
               "loop_base": 0, "started_at": "2026-01-01T00:00:00.000Z",
               "last_activity_at": "2026-01-01T00:04:00.000Z", "pid": 4242,
               "last_event": "heartbeat", "outputs": [], "consumed": []}
        step = StepState.from_dict(old)
        self.assertIsNone(step.last_output_at)
        self.assertIsNone(step.last_heartbeat_at)
        self.assertIn("last_output_at", step.to_dict())
        state = RunState(run_id="r1", workflow_id="w", workflow_version=1,
                         status=RunStatus.RUNNING, cursor="build", scope=["build"],
                         updated_at="2026-01-01T00:00:00.000Z", steps={"build": step})
        # The same answers LivenessDerivation gets, whatever the output threshold.
        for output in (1, 900):
            self.assertEqual(derive_liveness(state, 77, utc(2026, 1, 1, 0, 5, 0), 300,
                                             output)["liveness"], Liveness.RUNNING)
            live = derive_liveness(state, 77, utc(2026, 1, 1, 0, 9, 1), 300, output)
            self.assertEqual((live["liveness"], live["hung_reason"]),
                             (Liveness.HUNG, Liveness.DRIVER))
        self.assertIsNone(live["last_output_at"])

    def test_status_text_names_the_case_and_wgf_cancel(self):
        output = wgf.render_liveness(derive_liveness(self.state(), 77, self.NOW, 300, 120))
        text = "\n".join(output)
        self.assertIn("Liveness: hung", text)
        self.assertIn("hung_output_seconds", text)
        self.assertIn("child pid 4242", text)
        self.assertIn("heartbeats arriving", text)
        self.assertIn("wgf cancel r1", text)
        driver = "\n".join(wgf.render_liveness(
            derive_liveness(self.state(), 77, utc(2026, 1, 1, 0, 20, 0), 300, 120)))
        self.assertIn("hung_after_seconds", driver)
        self.assertIn("not even a heartbeat", driver)
        self.assertIn("wgf cancel r1", driver)
        self.assertNotIn("may be stuck. `wgf cancel", driver)

    def test_config_keys(self):
        self.assertEqual(FactoryConfig().hung_output_seconds, 900)
        self.assertEqual(FactoryConfig().on_hung, "none")
        config = FactoryConfig({"execution": {"hung_output_seconds": 42, "on_hung": "cancel"}})
        self.assertEqual((config.hung_output_seconds, config.on_hung), (42, "cancel"))
        for bad in (0, -5, True, "soon"):
            self.assertEqual(FactoryConfig({"execution": {"hung_output_seconds": bad}})
                             .hung_output_seconds, 900)
        for bad in ("kill", "Cancel", 1, True):
            with self.subTest(bad), self.assertRaises(ConfigError):
                FactoryConfig({"execution": {"on_hung": bad}}).on_hung


class WatchdogParams(EngineCase):
    """on_hung is snapshotted into the run's params at start and corroborated on resume, like
    auto_approve: a resume keeps the policy the run started with, and an edit is refused."""

    WATCH = {"on_hung": "cancel", "hung_output_seconds": 900}

    def edit_params(self, run_id, **changes):
        state = self.store.load(run_id)
        for key, value in changes.items():
            if value is None:
                state.params.pop(key, None)
            else:
                state.params[key] = value
        self.store.save(state)

    def waiting_run(self, params):
        engine = self.engine(CHECKPOINT.replace("GATE", "G3"))
        run = engine.start(params=dict(params))
        self.assertEqual(run.status, RunStatus.WAITING)
        return engine, run.run_id

    def test_untouched_policy_resumes(self):
        engine, run_id = self.waiting_run(self.WATCH)
        state = engine.resume(run_id, decision="approve")
        self.assertEqual(state.status, RunStatus.COMPLETED)
        self.assertEqual(state.params, self.WATCH)

    def test_an_edited_policy_is_refused_before_anything_runs(self):
        edits = {
            "watchdog removed": {"on_hung": None, "hung_output_seconds": None},
            "watchdog turned off": {"on_hung": "none"},
            "threshold raised": {"hung_output_seconds": 86400},
        }
        for label, change in edits.items():
            with self.subTest(label):
                engine, run_id = self.waiting_run(self.WATCH)
                self.edit_params(run_id, **change)
                self.script.calls.clear()
                with self.assertRaises(EngineError) as caught:
                    engine.resume(run_id, decision="approve")
                self.assertIn("params.", str(caught.exception))
                self.assertEqual(self.script.executed(), [])
        engine, run_id = self.waiting_run({})
        self.edit_params(run_id, on_hung="cancel", hung_output_seconds=1)
        with self.assertRaises(EngineError):
            engine.resume(run_id, decision="approve")

    def test_a_malformed_policy_is_refused(self):
        for params in ({"on_hung": "kill", "hung_output_seconds": 5},
                       {"on_hung": "cancel"},
                       {"on_hung": "cancel", "hung_output_seconds": 0},
                       {"on_hung": "cancel", "hung_output_seconds": "5"}):
            with self.subTest(params):
                engine, run_id = self.waiting_run(params)
                with self.assertRaises(EngineError) as caught:
                    engine.resume(run_id, decision="approve")
                self.assertIn("params.", str(caught.exception))

    def test_the_api_snapshots_the_policy_and_refuses_an_unknown_one(self):
        scratch = tempfile.mkdtemp(prefix="wgf-core-watch-")
        self.addCleanup(shutil.rmtree, scratch, ignore_errors=True)

        def api(execution):
            return WorkflowAPI(config=FactoryConfig({"storage": {"fsync": False},
                                                     "execution": execution}),
                               store_dir=os.path.join(scratch, "store"))

        state = api({"on_hung": "cancel", "hung_output_seconds": 120}).run(
            RunRequest(scope="develop", mock=True))
        self.assertEqual((state.params["on_hung"], state.params["hung_output_seconds"]),
                         ("cancel", 120))
        started = next(e for e in RunStore(os.path.join(scratch, "store"), fsync=False)
                       .read_events(state.run_id) if e["event"] == Events.WORKFLOW_STARTED)
        self.assertEqual(started["data"]["params"]["on_hung"], "cancel")
        state = api({}).run(RunRequest(scope="develop", mock=True))
        self.assertNotIn("on_hung", state.params)  # `none`: params as they always were
        with self.assertRaises(ConfigError):
            api({"on_hung": "kill"}).run(RunRequest(scope="develop", mock=True))


if __name__ == "__main__":
    unittest.main()

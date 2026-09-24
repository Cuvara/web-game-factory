"""The workflow engine: walks a definition, executes steps, persists state, routes results.

    definition -> resolve step -> execute (with retry) -> persist -> route -> next step

It knows nothing about research, games, platforms or agents. It knows steps by type, results
by outcome, and the order of work only through the definition. Every decision that looks
like business logic - "a failed verification goes back to development" - is a line in a
workflow file, and a test that fails if it ever moves in here is the point of
scripts/tests/test_workflow_engine.py.

Invariants the engine keeps:

  * State is saved before and after every execution, so a crash at any point leaves a run
    that `resume` continues from the step that was interrupted.
  * A step that succeeded is not executed again by `resume`. It is executed again only when
    the definition routes back to it (a loop) or the caller explicitly asks (`--from`).
  * A FAILED step is retried per its policy; no other outcome is retried.
  * Revisiting a step is bounded by `max_visits`; exceeding it blocks the run rather than
    looping forever.
  * Artifacts go to the store; state holds only references to them. An execution's
    artifact references, its step status and its trail entry are saved in one write, and
    the events describing them are emitted after it, so a crash never leaves state (or the
    log) naming an artifact the other does not.
  * A cancel request stops the run as CANCELLED, whether it arrives between steps or while
    a step runs; a step interrupted by it is never retried.
  * An input artifact is re-checked (checksum, and contract when a validator is set) before
    the step that consumes it runs; one that fails is a non-retryable FAILED naming it.
  * With a validator set, an output whose provenance carries `inputs` must pin exactly the
    versions the step consumed (contracts.check_lineage): a stale pin, or a pin of an
    artifact of a consumed type the step was not given, is a non-retryable FAILED and
    nothing is written.
"""

import contextlib
import copy
import datetime
import json
import re
import secrets
import time

from .. import procs
from ..hashing import CanonicalizationError, content_hash
from .context import StepLogger, WorkflowContext
from .contracts import check_lineage
from .definition import END, FAIL
from .events import EventBus, Events
from .model import (
    ArtifactRef,
    RunState,
    RunStatus,
    StepOutcome,
    StepResult,
    StepStatus,
)
from .runtime import LocalRuntime, Task
from .step import RegistryError, StepInputs
from .store import ARTIFACT_ID, RunLocked, StoreError

__all__ = ["WorkflowEngine", "EngineError", "utc_now", "check_decision"]


class EngineError(RuntimeError):
    """The engine was asked to do something the run's state does not allow."""


# A decision is a choice label, typed by a person or sent by automation. It is persisted and
# echoed into logs and status, so it is refused unless it is a plain token.
_DECISION = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}")
_DECIDER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:@-]{0,127}")
_NOTE_LIMIT = 4000


def check_decision(decision, decided_by="human", note=None):
    if not isinstance(decision, str) or not _DECISION.fullmatch(decision):
        raise EngineError(f"decision {decision!r} is not a plain choice label "
                          f"(letters, numbers, - _ . :; at most 64 characters)")
    if not isinstance(decided_by, str) or not _DECIDER.fullmatch(decided_by):
        raise EngineError(f"decided_by {decided_by!r} is not a plain identifier")
    if note is not None and (not isinstance(note, str) or "\x00" in note
                             or len(note) > _NOTE_LIMIT):
        raise EngineError(f"note must be text without NUL, at most {_NOTE_LIMIT} characters")


def utc_now():
    now = datetime.datetime.now(datetime.timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def default_run_id(workflow_id):
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"{workflow_id}-{stamp}-{secrets.token_hex(3)}"


_STEP_STATUS = {
    StepOutcome.SUCCESS: StepStatus.SUCCESS,
    StepOutcome.FAILED: StepStatus.FAILED,
    StepOutcome.BLOCKED: StepStatus.BLOCKED,
    StepOutcome.WAITING_FOR_INPUT: StepStatus.WAITING,
    StepOutcome.WAITING_FOR_HUMAN: StepStatus.WAITING,
}

_STEP_EVENT = {
    StepOutcome.SUCCESS: Events.STEP_COMPLETED,
    StepOutcome.FAILED: Events.STEP_FAILED,
    StepOutcome.BLOCKED: Events.STEP_BLOCKED,
    StepOutcome.WAITING_FOR_INPUT: Events.STEP_WAITING,
    StepOutcome.WAITING_FOR_HUMAN: Events.STEP_WAITING,
}


class WorkflowEngine:
    def __init__(self, definition, registry, store, *, runtime=None, config=None,
                 clock=utc_now, sleep=time.sleep, monotonic=time.monotonic,
                 run_id_factory=default_run_id, subscribers=(), artifact_validator=None):
        self.definition = definition
        self.registry = registry
        self.store = store
        self.runtime = runtime or LocalRuntime()
        self.config = dict(config or {})
        self.clock = clock
        self.sleep = sleep
        self.monotonic = monotonic
        self.run_id_factory = run_id_factory
        # (artifact_type, content) -> [problems]. Optional so the engine stays testable
        # without core/; the API always supplies contracts.ArtifactContracts.
        self.artifact_validator = artifact_validator
        self.bus = EventBus(clock)
        self.bus.subscribe(self._persist_event)
        for subscriber in subscribers:
            self.bus.subscribe(subscriber)

    # -- public API ---------------------------------------------------------------------

    def start(self, scope=None, start_at=None, project_id=None, params=None):
        """Create a run over `scope` (a workflow, group or step id) and drive it."""
        scope_ids = self.definition.resolve_scope(scope)
        if start_at is None:
            start_at = (
                self.definition.start if self.definition.start in scope_ids else scope_ids[0]
            )
        elif start_at not in scope_ids:
            raise EngineError(f"--from {start_at!r} is not in scope {scope_ids}")
        if scope in (None, self.definition.id) and start_at != self.definition.start:
            # `--from` on the whole workflow runs from there to the end, not the whole list.
            scope_ids = scope_ids[scope_ids.index(start_at):]
        self._require_implementations(scope_ids)

        now = self.clock()
        state = RunState(
            run_id=self.run_id_factory(self.definition.id),
            workflow_id=self.definition.id,
            workflow_version=self.definition.version,
            workflow_source=self.definition.source,
            status=RunStatus.PENDING,
            cursor=start_at,
            scope=scope_ids,
            project_id=project_id,
            created_at=now,
            updated_at=now,
            params=dict(params or {}),
        )
        self.store.create(state)
        self._emit(state, Events.WORKFLOW_STARTED, data={"scope": scope_ids, "start": start_at})
        self._enter(state, start_at, check_loop=False)
        return self._drive(state)

    def resume(self, run_id, from_step=None, decision=None, decided_by="human", note=None):
        """Continue a run from where it stopped.

        `from_step` moves the cursor first (re-running that step and everything after it).
        `decision` answers a step that is WAITING, typically a human checkpoint.
        """
        if decision is not None:
            check_decision(decision, decided_by, note)
        with self._holding(run_id):
            state = self._prepare_resume(run_id, from_step, decision, decided_by, note)
        return self._drive(state, held=True)

    def _prepare_resume(self, run_id, from_step, decision, decided_by, note):
        state = self.store.load(run_id)
        if state.workflow_id != self.definition.id:
            raise EngineError(
                f"run {run_id} belongs to workflow {state.workflow_id}, not {self.definition.id}"
            )
        if state.status not in RunStatus.RESUMABLE:
            raise EngineError(
                f"run {run_id} is {state.status}; only "
                f"{', '.join(RunStatus.RESUMABLE)} runs can be resumed"
            )
        data = {"from_status": state.status}
        # Resuming is the answer to a pause; one requested of a driver that then died must
        # not immediately pause the run it was just asked to continue.
        self.store.clear_request(run_id, "pause")
        for step_state in state.steps.values():
            step_state.loop_base = step_state.visits  # a resume is a fresh loop budget
        if state.workflow_version != self.definition.version:
            data["definition_version"] = self.definition.version
            data["note"] = "resuming under a newer workflow definition"

        if from_step is not None:
            if not self.definition.has_step(from_step):
                raise EngineError(f"workflow {self.definition.id} has no step {from_step!r}")
            if from_step not in state.scope:
                state.scope = self._widen_scope(state.scope, from_step)
            state.cursor = from_step
            self._enter(state, from_step, check_loop=False)
            data["from_step"] = from_step
        elif state.cursor is None:
            raise EngineError(f"run {run_id} has no step left to run")
        else:
            current = state.step(state.cursor)
            if current.status in (StepStatus.SUCCESS, StepStatus.SKIPPED):
                # Stopped at the loop limit before the next visit could begin; resuming is
                # the human saying "one more pass".
                self._enter(state, state.cursor, check_loop=False)
            current.attempts = 0  # a resume is a fresh attempt budget, not a continuation

        self._require_implementations(state.scope)

        if decision is not None:
            self.record_decision(state, state.cursor, decision, decided_by, note)

        self._emit(state, Events.WORKFLOW_RESUMED, data=data)
        return state

    def continue_in(self, run_id, scope, force=False):
        """Run `scope` inside an existing run, reusing what the run already produced.

        Steps in `scope` that already succeeded are skipped (STEP_SKIPPED) unless `force`,
        which is what keeps `wgf init --run <id>` from scaffolding a second repository.
        """
        with self._holding(run_id):
            state = self._prepare_continue(run_id, scope, force)
        return self._drive(state, skip_completed=not force, enter_first=True, held=True)

    def _prepare_continue(self, run_id, scope, force):
        state = self.store.load(run_id)
        if state.workflow_id != self.definition.id:
            raise EngineError(
                f"run {run_id} belongs to workflow {state.workflow_id}, not {self.definition.id}"
            )
        if state.status == RunStatus.RUNNING:
            raise EngineError(f"run {run_id} is RUNNING; resume it instead")
        if state.status == RunStatus.CANCELLED:
            raise EngineError(f"run {run_id} was cancelled")
        scope_ids = self.definition.resolve_scope(scope)
        self._require_implementations(scope_ids)
        for step_state in state.steps.values():
            step_state.loop_base = step_state.visits  # an explicit command: a fresh budget
        previous = state.status
        state.scope = scope_ids
        state.cursor = scope_ids[0]
        state.exit = None
        state.message = None
        self._emit(state, Events.WORKFLOW_RESUMED,
                   data={"from_status": previous, "scope": scope_ids, "force": force})
        return state

    def record_decision(self, state, step_id, decision, decided_by="human", note=None):
        check_decision(decision, decided_by, note)
        step = state.step(step_id)
        entry = {
            "decision": decision,
            "decided_by": decided_by,
            "decided_at": self.clock(),
            "visit": step.visits,
        }
        if note:
            entry["note"] = note
        state.decisions[step_id] = entry
        self._save(state)
        self._emit(state, Events.DECISION_RECORDED, step_id=step_id, data=entry)

    def request_pause(self, run_id):
        """Pause at the next step boundary; at once if nothing is driving the run."""
        state = self.store.load(run_id)
        if state.status != RunStatus.RUNNING:
            raise EngineError(f"run {run_id} is {state.status}, not RUNNING; nothing to pause")
        # Change state directly only while holding the lock, so a driver that starts in
        # between cannot have its state overwritten; if one holds it, ask it instead.
        try:
            self.store.acquire(run_id)
        except RunLocked:
            self.store.request(run_id, "pause")
            return state
        try:
            state = self.store.load(run_id)
            if state.status != RunStatus.RUNNING:
                raise EngineError(
                    f"run {run_id} is {state.status}, not RUNNING; nothing to pause")
            state.status = RunStatus.PAUSED
            state.message = "paused on request"
            self._save(state)
            self._emit(state, Events.WORKFLOW_PAUSED, status=state.status,
                       data={"reason": "requested", "next_step": state.cursor})
            return state
        finally:
            self.store.release(run_id)

    def request_cancel(self, run_id):
        """Cancel now if nothing is driving the run, else as soon as the driver notices.

        A driven run notices between steps, and also while a step runs: a child process the
        step started through wgflib.procs is terminated, tree and all, and the step that was
        waiting on it is not retried.
        """
        state = self.store.load(run_id)
        if state.status in RunStatus.TERMINAL:
            raise EngineError(f"run {run_id} is already {state.status}")
        try:
            self.store.acquire(run_id)
        except RunLocked:
            self.store.request(run_id, "cancel")
            return state
        try:
            state = self.store.load(run_id)
            if state.status in RunStatus.TERMINAL:
                raise EngineError(f"run {run_id} is already {state.status}")
            state.status = RunStatus.CANCELLED
            self._save(state)
            self._emit(state, Events.WORKFLOW_CANCELLED)
            return state
        finally:
            self.store.release(run_id)

    # -- the loop -----------------------------------------------------------------------

    @contextlib.contextmanager
    def _holding(self, run_id):
        """Hold the run's lock while preparing it; released only if preparation fails.

        On success the lock stays taken and `_drive(held=True)` releases it when the run
        stops, so nothing can change the run in between.
        """
        self.store.acquire(run_id)
        try:
            yield
        except BaseException:
            self.store.release(run_id)
            raise

    def _drive(self, state, skip_completed=False, enter_first=False, held=False):
        """Execute from the cursor until the run stops.

        With `skip_completed`, a step that already succeeded in this run is skipped when it
        is reached by ordinary success progression. A step reached by an explicit route (a
        verification failure sending work back to development) always executes: that is a
        loop, and skipping it would defeat it. A step is skipped at most once per drive: a
        cycle of `next:` edges through completed steps would otherwise spin forever without
        executing anything, and so without ever meeting the loop limit.

        `held` means the caller already holds the run's lock (resume, continue_in).
        """
        if not held:
            self.store.acquire(state.run_id)
        skip = skip_completed
        # The cursor step must begin a new visit before it executes when `needs_enter`;
        # `check` applies the loop limit to that entry. Only a drive's first entry (resume
        # --from, continue_in) is exempt - every later one, including an entry deferred
        # past a skip, counts against max_visits, so no path through the graph is unbounded.
        needs_enter, check = enter_first, False
        skipped = set()
        try:
            self.store.mark_latest(state.run_id)
            state.status = RunStatus.RUNNING
            state.message = None
            self._save(state)
            while True:
                if self._honour_requests(state):
                    return state

                step_id = state.cursor
                step_def = self.definition.step(step_id)
                step_state = state.step(step_id)

                if skip and step_state.status == StepStatus.SUCCESS and step_id not in skipped:
                    skipped.add(step_id)
                    self._emit(state, Events.STEP_SKIPPED, step_id=step_id,
                               data={"reason": "already completed in this run"})
                    target = self.definition.success_target(step_def)
                    if self._follow(state, step_def, "success", StepOutcome.SUCCESS,
                                    ("goto", target) if target != END else ("end", END),
                                    enter=False):
                        return state
                    needs_enter, check = True, True
                    continue
                if step_state.visits == 0 or needs_enter:
                    if not self._enter(state, step_id, check_loop=check):
                        self._loop_limit(state, step_id)
                        return state
                needs_enter = False

                result = self._execute_visit(state, step_def)
                if self._honour_cancel(state):
                    return state
                skip = (skip_completed and result.outcome == StepOutcome.SUCCESS
                        and not self._explicitly_routed(step_def, result))
                route = self._route(step_def, result)
                # Entering resets a step to PENDING; do not, if it is about to be skipped.
                enter = not (skip and route[0] == "goto"
                             and state.step(route[1]).status == StepStatus.SUCCESS)
                if self._follow(state, step_def, result.routing_key, result.outcome, route,
                                message=result.message or result.error, enter=enter):
                    return state
                needs_enter, check = not enter, True
        finally:
            self.store.release(state.run_id)

    def _cancel_requested(self, state):
        return self.store.requested(state.run_id, "cancel")

    def _honour_cancel(self, state):
        if not self._cancel_requested(state):
            return False
        self.store.clear_request(state.run_id, "cancel")
        state.status = RunStatus.CANCELLED
        state.message = "cancelled on request"
        self._save(state)
        self._emit(state, Events.WORKFLOW_CANCELLED, step_id=state.cursor)
        return True

    def _honour_requests(self, state):
        if self._honour_cancel(state):
            return True
        if self.store.requested(state.run_id, "pause"):
            self.store.clear_request(state.run_id, "pause")
            state.status = RunStatus.PAUSED
            state.message = "paused on request"
            self._save(state)
            self._emit(state, Events.WORKFLOW_PAUSED, status=state.status,
                       data={"reason": "requested", "next_step": state.cursor})
            return True
        return False

    def _enter(self, state, step_id, check_loop=True):
        """Begin a new visit to `step_id`. Returns False if the loop limit forbids it."""
        step_def = self.definition.step(step_id)
        step_state = state.step(step_id)
        if check_loop and step_state.visits - step_state.loop_base >= step_def.max_visits:
            return False
        step_state.visits += 1
        step_state.attempts = 0
        step_state.status = StepStatus.PENDING
        step_state.error = None
        step_state.message = None
        self._save(state)
        return True

    def _execute_visit(self, state, step_def):
        """Execute the cursor step, retrying FAILED results per the step's policy."""
        step_state = state.step(step_def.id)
        policy = step_def.retry
        while True:
            step_state.attempts += 1
            step_state.executions += 1
            attempt = step_state.attempts
            if attempt > 1:
                delay = policy.delay_before(attempt)
                self._emit(state, Events.STEP_RETRIED, step_id=step_def.id, attempt=attempt,
                           data={"delay_seconds": delay, "max_attempts": policy.max_attempts})
                if delay:
                    self.sleep(delay)

            step_state.status = StepStatus.RUNNING
            step_state.started_at = self.clock()
            step_state.finished_at = None
            self._save(state)
            self._emit(state, Events.STEP_STARTED, step_id=step_def.id, attempt=attempt,
                       status=StepStatus.RUNNING, data={"type": step_def.type,
                                                        "visit": step_state.visits})

            began = self.monotonic()
            result = self._run_once(state, step_def, step_state)
            duration_ms = int(round((self.monotonic() - began) * 1000))

            refs, artifact_events = [], []
            if result.artifacts:
                try:
                    refs, artifact_events = self._persist_artifacts(state, step_def, result)
                except _ContractViolation as exc:
                    result = StepResult(StepOutcome.FAILED, error=str(exc), retryable=False)
                except (OSError, StoreError) as exc:
                    # Nothing was recorded; any file already written is an unrecorded
                    # orphan that the next attempt overwrites.
                    result = StepResult(StepOutcome.FAILED,
                                        error=f"could not persist artifacts: {exc}")
            cancelled = self._cancel_requested(state)
            if cancelled and result.outcome != StepOutcome.SUCCESS:
                result = StepResult(
                    result.outcome, route=result.route, message="cancelled while running",
                    error=result.error, retryable=False, data=result.data)
            if result.outcome == StepOutcome.SUCCESS:
                missing = [t for t in step_def.outputs if t not in {r.type for r in refs}]
                if missing:
                    result = StepResult(
                        StepOutcome.FAILED, retryable=False,
                        error=f"succeeded without producing declared output(s): "
                              f"{', '.join(missing)}",
                    )

            step_state.status = _STEP_STATUS[result.outcome]
            step_state.finished_at = self.clock()
            step_state.duration_ms = duration_ms
            step_state.last_route = result.routing_key
            step_state.message = result.message
            step_state.error = result.error
            if refs:
                step_state.outputs = [f"{ref.id}@v{ref.version}" for ref in refs]
            state.trail.append({
                "step": step_def.id,
                "visit": step_state.visits,
                "attempt": attempt,
                "outcome": result.outcome,
                "route": result.routing_key,
                "consumed": list(step_state.consumed),
                "at": step_state.finished_at,
                "duration_ms": duration_ms,
            })

            will_retry = (
                result.outcome == StepOutcome.FAILED
                and result.retryable
                and attempt < policy.max_attempts
                and not cancelled
            )
            # One save covers the artifact refs, the step's status and the trail entry; the
            # events that describe them follow it.
            self._save(state)
            for event, fields in artifact_events:
                self._emit(state, event, step_id=step_def.id, **fields)
            self._emit(
                state, _STEP_EVENT[result.outcome], step_id=step_def.id, attempt=attempt,
                status=step_state.status, duration_ms=duration_ms, error=result.error,
                data=_compact({"route": result.route, "message": result.message,
                               "result": _jsonable(result.data) or None,
                               "will_retry": will_retry if result.outcome == "FAILED" else None,
                               "outputs": step_state.outputs if refs else None}),
            )
            if not will_retry:
                return result

    def _run_once(self, state, step_def, step_state):
        try:
            step = self.registry.create(step_def)
        except RegistryError as exc:
            return StepResult(StepOutcome.FAILED, error=str(exc), retryable=False)
        except Exception as exc:  # a step class whose constructor raises
            return StepResult(StepOutcome.FAILED, retryable=False,
                              error=f"step {step_def.id!r}: could not be constructed: "
                                    f"{type(exc).__name__}: {exc}")

        refs, missing = {}, []
        for artifact_type in step_def.inputs:
            ref = state.latest_of_type(artifact_type)
            if ref is None:
                missing.append(artifact_type)
            else:
                refs[artifact_type] = ref
        step_state.consumed = [f"{ref.id}@v{ref.version}" for ref in refs.values()]
        loaded, problem = self._check_inputs(state, refs)
        if problem:
            return StepResult(StepOutcome.FAILED, error=problem, retryable=False)
        inputs = StepInputs(refs, lambda ref: copy.deepcopy(loaded[(ref.id, ref.version)])
                            if (ref.id, ref.version) in loaded
                            else self.store.read_artifact(state.run_id, ref), missing)

        decision = state.decisions.get(step_def.id)
        if decision and decision.get("visit") != step_state.visits:
            decision = None  # a decision answers one visit, not every later loop through

        base = {"workflow_id": state.workflow_id, "run_id": state.run_id,
                "step_id": step_def.id, "attempt": step_state.attempts}
        context = WorkflowContext(
            workflow_id=state.workflow_id,
            workflow_version=state.workflow_version,
            run_id=state.run_id,
            project_id=state.project_id,
            step_id=step_def.id,
            step_type=step_def.type,
            attempt=step_state.attempts,
            visit=step_state.visits,
            execution=step_state.executions,
            config=self.config,
            environment=dict(state.params),
            params=dict(step_def.params),
            decision=decision,
            previous_outputs=[
                ref for ref in (state.latest_artifact(o.split("@")[0]) for o in step_state.outputs)
                if ref is not None
            ],
            logger=StepLogger(self.bus.emit, base),
            emit=self.bus.emit,
            run_dir=self.store.run_dir(state.run_id),
            mock=bool(state.params.get("mock")),
            progress=self._progress_recorder(state, step_def, step_state),
            should_stop=lambda: self.store.requested(state.run_id, "cancel"),
        )
        step_state.pid = None
        step_state.last_event = "started"
        step_state.last_activity_at = self.clock()
        try:
            # Any process the step starts through wgflib.procs reports to this step and is
            # terminated, tree and all, by a cancel request.
            with procs.bound(context.progress, context.should_stop):
                return self.runtime.run(Task(step, inputs, context))
        finally:
            step_state.pid = None

    # Liveness is saved at most this often from heartbeats and output; lifecycle events
    # (spawned, exited, timeout, cancelled, ...) are saved at once.
    PROGRESS_SAVE_SECONDS = 5.0

    def _progress_recorder(self, state, step_def, step_state):
        last_saved = {"at": None}

        def record(kind, **data):
            now = self.monotonic()
            step_state.last_activity_at = self.clock()
            step_state.last_event = kind
            if kind == "spawned" and data.get("pid"):
                step_state.pid = data.get("pid")
            elif kind == "exited":
                step_state.pid = None
            lifecycle = kind not in ("heartbeat", "output")
            if lifecycle or last_saved["at"] is None or (
                    now - last_saved["at"] >= self.PROGRESS_SAVE_SECONDS):
                last_saved["at"] = now
                self._save(state)
                self._emit(state, Events.STEP_PROGRESS, step_id=step_def.id,
                           attempt=step_state.attempts,
                           data=_compact({"kind": kind, **_jsonable(data)}))

        return record

    def _validate(self, artifact_type, content):
        """The validator's problems, with a validator that raises reported as one."""
        if self.artifact_validator is None:
            return []
        try:
            return list(self.artifact_validator(artifact_type, content) or [])
        except Exception as exc:
            return [f"{artifact_type}: the contract check itself failed: "
                    f"{type(exc).__name__}: {exc}"]

    def _lineage(self, state, step_def, step_state, output):
        """check_lineage against the refs this execution consumed, when a validator is set
        and the output declares its lineage (`provenance.inputs` is a list).

        On top of check_lineage: a pin of a type the step declares as an input but was not
        given (an optional input absent on this visit) names an artifact the step never
        saw. Pins of types the step does not take at all - claims, lineage carried forward
        from further upstream - are left alone, as check_lineage leaves them."""
        if self.artifact_validator is None or not isinstance(output.content, dict):
            return []
        provenance = output.content.get("provenance")
        if not isinstance(provenance, dict) or not isinstance(provenance.get("inputs"), list):
            return []
        consumed = []
        for name in step_state.consumed or []:
            artifact_id, _, version = name.rpartition("@v")
            ref = next((r for r in state.artifacts.get(artifact_id) or []
                        if str(r.version) == version), None)
            if ref is None:
                return [f"lineage: consumed {name} is not in the run's state"]
            consumed.append(ref)
        try:
            problems = check_lineage(output.content, consumed)
        except Exception as exc:
            return [f"lineage: the check itself failed: {type(exc).__name__}: {exc}"]
        given = {ref.type for ref in consumed}
        for index, pin in enumerate(provenance["inputs"]):
            pinned_type = pin.get("artifact_type") if isinstance(pin, dict) else None
            if pinned_type in step_def.inputs and pinned_type not in given:
                problems.append(
                    f"lineage: /provenance/inputs/{index}: pins {pinned_type} at "
                    f"{pin.get('content_hash')}, which this step did not consume (the run "
                    f"held none when it ran)")
        return problems

    def _check_inputs(self, state, refs):
        """Read and check every resolved input before the step sees it.

        Returns ({(id, version): content}, None), or (partial, problem) naming the first
        input that is missing, changed on disk since it was recorded, or fails its contract.
        """
        loaded = {}
        for artifact_type, ref in refs.items():
            label = (f"input {artifact_type} ({ref.id}@v{ref.version}, produced by "
                     f"{ref.produced_by or 'unknown step'})")
            try:
                content = self.store.read_artifact(state.run_id, ref)
            except StoreError as exc:
                return loaded, f"{label} cannot be used: {exc}"
            problems = self._validate(ref.type, content)
            if problems:
                return loaded, f"{label} fails its contract: " + "; ".join(problems)
            loaded[(ref.id, ref.version)] = content
        return loaded, None

    def _persist_artifacts(self, state, step_def, result):
        """Check every output against its contract, then write them all - or record none.

        Returns (refs, events). The refs are appended to `state` in memory only; the caller
        saves them together with the step's status, then emits the events. Until that save,
        a written file is an orphan nothing refers to, and the version it occupies is
        reused - the file replaced - by the next execution, so version numbers stay
        deterministic: always one more than the versions state has recorded.
        """
        for output in result.artifacts:
            if step_def.outputs and output.type not in step_def.outputs:
                raise _ContractViolation(
                    f"produced {output.type!r}, which step {step_def.id!r} does not declare "
                    f"in outputs {step_def.outputs}"
                )
            if not isinstance(output.artifact_id, str) or not ARTIFACT_ID.fullmatch(
                    output.artifact_id):
                raise _ContractViolation(
                    f"artifact id {output.artifact_id!r} is not kebab-case"
                )
            try:
                json.dumps(output.content)
                json.dumps(output.metadata)
            except (TypeError, ValueError) as exc:
                raise _ContractViolation(
                    f"artifact {output.artifact_id!r} is not JSON-serializable: {exc}")
            problems = self._validate(output.type, output.content)
            if problems:
                raise _ContractViolation("invalid artifact: " + "; ".join(problems))
            problems = self._lineage(state, step_def, state.step(step_def.id), output)
            if problems:
                raise _ContractViolation(
                    f"{output.type} {output.artifact_id!r} does not pin what step "
                    f"{step_def.id!r} consumed: " + "; ".join(problems))

        planned, events = [], []
        seq = state.next_artifact_seq()
        pending = {}
        for output in result.artifacts:
            artifact_id = output.artifact_id
            version = len(state.artifacts.get(artifact_id) or []) + pending.get(artifact_id, 0) + 1
            pending[artifact_id] = pending.get(artifact_id, 0) + 1
            if self.store.has_artifact_file(state.run_id, artifact_id, version):
                events.append((Events.STEP_LOG, {
                    "level": "warning",
                    "message": "replaced an unrecorded artifact file left by an interrupted "
                               "execution",
                    "data": {"artifact": f"{artifact_id}@v{version}"},
                }))
            location, checksum = self.store.write_artifact(
                state.run_id, artifact_id, version, output.content
            )
            digest = schema_version = None
            provenance = (output.content.get("provenance")
                          if isinstance(output.content, dict) else None)
            if isinstance(provenance, dict):
                schema_version = provenance.get("schema_version")
                try:
                    digest = content_hash(output.content)
                except CanonicalizationError:
                    digest = None
            ref = ArtifactRef(
                id=artifact_id, type=output.type, version=version, location=location,
                checksum=checksum, produced_by=step_def.id, created_at=self.clock(),
                content_hash=digest, schema_version=schema_version,
                metadata=dict(output.metadata) if output.metadata else None,
                seq=seq,
            )
            seq += 1
            planned.append(ref)
            events.append((Events.ARTIFACT_CREATED if version == 1 else Events.ARTIFACT_UPDATED,
                           {"data": ref.to_dict()}))

        # Every file is written; only now does state learn of them.
        for ref in planned:
            state.artifacts.setdefault(ref.id, []).append(ref)
        return planned, events

    # -- routing ------------------------------------------------------------------------

    @staticmethod
    def _explicitly_routed(step_def, result):
        return (result.route in step_def.on) or (result.outcome.lower() in step_def.on)

    def _route(self, step_def, result):
        """(kind, target): goto a step, end, abort, block, or wait. Pure."""
        outcome_key = result.outcome.lower()
        target = None
        if result.route and result.route in step_def.on:
            target = step_def.on[result.route]
        elif outcome_key in step_def.on:
            target = step_def.on[outcome_key]

        if target is None:
            if result.outcome == StepOutcome.SUCCESS:
                target = self.definition.success_target(step_def)
            elif result.outcome == StepOutcome.FAILED:
                return ("abort", FAIL)
            elif result.outcome == StepOutcome.BLOCKED:
                return ("block", None)
            else:
                return ("wait", None)

        if target == END:
            return ("end", END)
        if target == FAIL:
            return ("abort", FAIL)
        return ("goto", target)

    def _follow(self, state, step_def, key, outcome, route, message=None, enter=True):
        """Apply a routing decision to the run. Returns True when the run should stop."""
        kind, target = route
        self._emit(state, Events.TRANSITION, step_id=step_def.id,
                   data=_compact({"route": key, "outcome": outcome, "kind": kind,
                                  "to": target}))

        if kind == "goto" and target not in state.scope:
            state.cursor = None
            state.exit = {"step": step_def.id, "route": key, "outcome": outcome, "next": target}
            return self._finish(state, RunStatus.COMPLETED, Events.WORKFLOW_COMPLETED,
                                f"left scope after {step_def.id} ({key}); next would be {target}")
        if kind == "goto":
            if enter and not self._enter(state, target):
                return self._loop_limit(state, target)
            state.cursor = target
            self._save(state)
            return False
        if kind == "end":
            state.cursor = None
            state.exit = {"step": step_def.id, "route": key, "outcome": outcome, "next": END}
            return self._finish(state, RunStatus.COMPLETED, Events.WORKFLOW_COMPLETED, None)
        if kind == "abort":
            return self._finish(state, RunStatus.FAILED, Events.WORKFLOW_FAILED,
                                message or f"{step_def.id} failed")
        if kind == "block":
            return self._finish(state, RunStatus.BLOCKED, Events.WORKFLOW_BLOCKED,
                                message or f"{step_def.id} is blocked")
        return self._finish(state, RunStatus.WAITING, Events.WORKFLOW_PAUSED,
                            message or f"{step_def.id} is waiting", reason=key)

    def _loop_limit(self, state, target):
        state.cursor = target
        limit = self.definition.step(target).max_visits
        return self._finish(
            state, RunStatus.BLOCKED, Events.WORKFLOW_BLOCKED,
            f"loop limit: {target} has been entered {limit} time(s) since the run "
            f"last started or resumed (max_visits={limit}). Resume to allow more.",
        )

    def _finish(self, state, status, event, message, reason=None):
        state.status = status
        state.message = message
        self._save(state)
        self._emit(state, event, status=status, step_id=state.cursor,
                   data=_compact({"message": message, "reason": reason, "exit": state.exit}))
        return True

    # -- plumbing -----------------------------------------------------------------------

    def _require_implementations(self, step_ids):
        missing = self.registry.missing_for(self.definition, step_ids)
        if missing:
            raise RegistryError(
                f"no implementation registered for step type(s) {', '.join(missing)}. "
                f"Real step modules are listed under factory.steps.modules; "
                f"use --mock to run the placeholder implementations."
            )

    def _widen_scope(self, scope, step_id):
        ids = self.definition.step_ids
        wanted = set(scope) | {step_id}
        return [i for i in ids if i in wanted]

    def _save(self, state):
        state.updated_at = self.clock()
        self.store.save(state)

    def _emit(self, state, event, **fields):
        return self.bus.emit(event, workflow_id=state.workflow_id, run_id=state.run_id,
                             **fields)

    def _persist_event(self, record):
        if record.get("run_id") and self.store.exists(record["run_id"]):
            self.store.append_event(record)


class _ContractViolation(Exception):
    pass


def _jsonable(value):
    """`value` if it survives JSON, else a note saying it did not. Events must persist."""
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return {"unserializable": type(value).__name__}


def _compact(mapping):
    return {key: value for key, value in mapping.items() if value is not None} or None

"""What a step can see about the run it is part of.

The context is read-mostly and carries no business logic: identifiers, the step's
configuration, the human decisions recorded against it, and a logger. Artifacts reach a step
through `inputs`, not through the context, so that what a step consumed is exactly what the
definition says it consumes.
"""

__all__ = ["WorkflowContext", "StepLogger"]


class StepLogger:
    """Structured logging for a step. Every call becomes a STEP_LOG event."""

    def __init__(self, emit, base):
        self._emit = emit
        self._base = base

    def _log(self, level, message, fields):
        fields = {key: value for key, value in fields.items() if value is not None}
        self._emit("STEP_LOG", level=level, message=message, data=fields or None, **self._base)

    def debug(self, message, **fields):
        self._log("debug", message, fields)

    def info(self, message, **fields):
        self._log("info", message, fields)

    def warning(self, message, **fields):
        self._log("warning", message, fields)

    def error(self, message, **fields):
        self._log("error", message, fields)


class WorkflowContext:
    """Per-execution context handed to a step.

    `idempotency_key` is stable across attempts, resumes and crashes for the same visit to
    the same step - `<run_id>:<step_id>:<visit>`. A step with a side effect outside the run
    directory (creating a repository, say) should key that effect on it, so that
    re-executing after a crash finds the thing it already made instead of making another.

    `previous_outputs` are the refs this step produced on its last successful execution in
    this run, for the same reason.

    `now` is the engine's clock at this execution, and `waiting_since` when the current
    visit first returned a WAITING outcome (None if it has not, or if work upstream has
    succeeded again since). A step that waits for something with a deadline - a checkpoint's
    timeout - measures it with these, never with its own clock. `record_decision(decision,
    decided_by, note=None, mode=None)` records a decision on this step's current visit the
    way a person's is recorded: in state and as a DECISION_RECORDED event.

    `gates_passed` lists the gates (a checkpoint's `with: gate`) this run has passed and
    whose approval no later upstream work has superseded, in definition order.
    """

    def __init__(self, *, workflow_id, workflow_version, run_id, project_id, step_id,
                 step_type, attempt, visit, execution, config, environment, params,
                 decision, previous_outputs, logger, emit, run_dir, mock,
                 progress=None, should_stop=None, now=None, waiting_since=None,
                 record_decision=None, gates_passed=()):
        self.workflow_id = workflow_id
        self.workflow_version = workflow_version
        self.run_id = run_id
        self.project_id = project_id
        self.current_step = step_id
        self.step_type = step_type
        self.attempt = attempt
        self.visit = visit
        self.execution = execution
        self.config = config
        self.environment = environment
        self.params = params
        self.decision = decision
        self.previous_outputs = previous_outputs
        self.logger = logger
        self._emit = emit
        self.run_dir = run_dir
        self.mock = mock
        self._progress = progress
        self._should_stop = should_stop
        self.now = now
        self.waiting_since = waiting_since
        self._record_decision = record_decision
        self.gates_passed = list(gates_passed or ())

    def record_decision(self, decision, decided_by="automation", note=None, mode=None):
        """Record `decision` on this step's current visit; returns the recorded entry.
        Raises RuntimeError when the engine gave this context no way to record one."""
        if self._record_decision is None:
            raise RuntimeError("this context cannot record a decision")
        entry = self._record_decision(decision, decided_by, note, mode)
        self.decision = entry
        return entry

    @property
    def idempotency_key(self):
        return f"{self.run_id}:{self.current_step}:{self.visit}"

    def emit(self, event, **fields):
        """Emit a custom event on the run's bus, tagged with this step."""
        fields.setdefault("step_id", self.current_step)
        return self._emit(event, workflow_id=self.workflow_id, run_id=self.run_id, **fields)

    def progress(self, kind, **data):
        """Report liveness: a child process spawned, is still working (`heartbeat`), exited.

        The engine records the latest one on the step's state (`pid`, `last_activity_at`,
        `last_event`, and `last_output_at` / `last_heartbeat_at`, kept apart because a
        heartbeat shows the driver is alive, not that the child is doing anything) so
        `wgf status` can tell a working step from a hung one. Cheap to call often;
        persisting is throttled by the engine, not here. `should_stop` also turns true when
        the run's hung-child watchdog (`on_hung: cancel`) fires.
        """
        if self._progress is not None:
            self._progress(kind, **data)

    def should_stop(self):
        """True once someone has asked this run to cancel. A long-running step polls it."""
        return bool(self._should_stop()) if self._should_stop is not None else False

    def process_hooks(self):
        """Keyword arguments for wgflib.procs.run that tie a child process to this step:
        its lifecycle feeds `progress`, and a cancel request terminates its tree."""
        return {"on_event": self.progress, "should_stop": self.should_stop}

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
    """

    def __init__(self, *, workflow_id, workflow_version, run_id, project_id, step_id,
                 step_type, attempt, visit, execution, config, environment, params,
                 decision, previous_outputs, logger, emit, run_dir, mock):
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

    @property
    def idempotency_key(self):
        return f"{self.run_id}:{self.current_step}:{self.visit}"

    def emit(self, event, **fields):
        """Emit a custom event on the run's bus, tagged with this step."""
        fields.setdefault("step_id", self.current_step)
        return self._emit(event, workflow_id=self.workflow_id, run_id=self.run_id, **fields)

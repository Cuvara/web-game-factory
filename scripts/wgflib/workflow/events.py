"""Workflow events: the one channel through which the engine says what it is doing.

The engine emits; subscribers decide what that means. The run store appends every event to
`events.jsonl` (which doubles as the structured log), the CLI prints progress from the same
stream, and a UI or monitor can subscribe later without the engine changing.

Every event is a flat JSON-able dict:

    {"format": 1, "ts": ..., "event": "STEP_FAILED", "workflow_id": ..., "run_id": ..., "step_id": ...,
     "attempt": 2, "status": "FAILED", "duration_ms": 12, "error": "...", "data": {...}}

Keys that do not apply are omitted rather than null.
"""

__all__ = ["Events", "EventBus", "EVENT_FORMAT"]

# Bumped if a field is removed or changes meaning. Adding a field or an event is not a
# format change; consumers must ignore what they do not know.
EVENT_FORMAT = 1


class Events:
    WORKFLOW_STARTED = "WORKFLOW_STARTED"
    WORKFLOW_RESUMED = "WORKFLOW_RESUMED"
    WORKFLOW_PAUSED = "WORKFLOW_PAUSED"
    WORKFLOW_BLOCKED = "WORKFLOW_BLOCKED"
    WORKFLOW_COMPLETED = "WORKFLOW_COMPLETED"
    WORKFLOW_FAILED = "WORKFLOW_FAILED"
    WORKFLOW_CANCELLED = "WORKFLOW_CANCELLED"

    STEP_STARTED = "STEP_STARTED"
    STEP_COMPLETED = "STEP_COMPLETED"
    STEP_FAILED = "STEP_FAILED"
    STEP_RETRIED = "STEP_RETRIED"
    STEP_SKIPPED = "STEP_SKIPPED"
    STEP_WAITING = "STEP_WAITING"
    STEP_BLOCKED = "STEP_BLOCKED"
    STEP_LOG = "STEP_LOG"

    TRANSITION = "TRANSITION"
    DECISION_RECORDED = "DECISION_RECORDED"

    ARTIFACT_CREATED = "ARTIFACT_CREATED"
    ARTIFACT_UPDATED = "ARTIFACT_UPDATED"

    @classmethod
    def all(cls):
        return sorted(value for key, value in vars(cls).items()
                      if key.isupper() and isinstance(value, str))


class EventBus:
    """Synchronous fan-out. A subscriber that raises does not stop the run or the others.

    Subscribers are called in registration order, so the store (registered first) has
    persisted an event before anything prints it.
    """

    def __init__(self, clock):
        self._clock = clock
        self._subscribers = []
        self.errors = []

    def subscribe(self, callback):
        self._subscribers.append(callback)
        return callback

    def emit(self, event, **fields):
        record = {"format": EVENT_FORMAT, "ts": self._clock(), "event": event}
        record.update({key: value for key, value in fields.items() if value is not None})
        for callback in list(self._subscribers):
            try:
                callback(record)
            except Exception as exc:  # observability must never take the run down
                self.errors.append(f"{getattr(callback, '__name__', callback)}: {exc}")
        return record

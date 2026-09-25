"""The workflow kernel's vocabulary: statuses, step results, artifact references, run state.

Everything here is plain data with a `to_dict`/`from_dict` pair, because the run state is the
only thing that survives a crash and must mean the same thing when it is read back by a
later version of the engine. Nothing in this module knows what a step does.

Three status vocabularies, deliberately distinct:

    StepOutcome     what one execution of a step reports            (returned by a step)
    StepStatus      where a step stands inside a run                (persisted per step)
    RunStatus       where the whole run stands                      (persisted per run)

A step does not set its own StepStatus and never sets the RunStatus; it reports an outcome
and the engine decides what that means, from the workflow definition.
"""

import dataclasses
import datetime
from dataclasses import dataclass, field

__all__ = [
    "StepOutcome",
    "StepStatus",
    "RunStatus",
    "StepResult",
    "ArtifactRef",
    "ArtifactOutput",
    "StepState",
    "RunState",
    "STATE_FORMAT",
    "Liveness",
    "derive_liveness",
    "parse_timestamp",
    "format_timestamp",
    "DEFAULT_HUNG_OUTPUT_SECONDS",
]

# Bumped when the persisted shape of RunState changes incompatibly. A run written under an
# older format is refused rather than half-read.
STATE_FORMAT = 1


class StepOutcome:
    """What a single execution of a step reports back to the engine."""

    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    WAITING_FOR_INPUT = "WAITING_FOR_INPUT"
    WAITING_FOR_HUMAN = "WAITING_FOR_HUMAN"

    ALL = (SUCCESS, FAILED, BLOCKED, WAITING_FOR_INPUT, WAITING_FOR_HUMAN)
    WAITING = (WAITING_FOR_INPUT, WAITING_FOR_HUMAN)


class StepStatus:
    """Where a step stands inside a run."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
    WAITING = "WAITING"
    BLOCKED = "BLOCKED"

    ALL = (PENDING, RUNNING, SUCCESS, FAILED, SKIPPED, WAITING, BLOCKED)


class RunStatus:
    """Where a whole run stands."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    WAITING = "WAITING"
    PAUSED = "PAUSED"
    FAILED = "FAILED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    BLOCKED = "BLOCKED"

    ALL = (PENDING, RUNNING, WAITING, PAUSED, FAILED, COMPLETED, CANCELLED, BLOCKED)
    # A run in one of these can be resumed. RUNNING is included because a run that is
    # RUNNING on disk with no process behind it is a crashed run, and resuming is the only
    # way out of that; the store's lock is what prevents two live processes.
    RESUMABLE = (PENDING, RUNNING, WAITING, PAUSED, FAILED, BLOCKED)
    TERMINAL = (COMPLETED, CANCELLED)


def _fields(cls, data):
    names = {f.name for f in dataclasses.fields(cls)}
    return {key: value for key, value in data.items() if key in names}


@dataclass
class ArtifactRef:
    """A pointer to an artifact the run holds. State carries these, never the content.

    `version` counts productions of this artifact id within the run (1, 2, ... - a
    develop/verify loop produces several). `schema_version` is the contract version the
    content claims (`provenance.schema_version`), which is what a consumer checks for
    compatibility. `metadata` is small, step-supplied, and never the content.

    `location` is relative to the run directory, so a run directory can be moved or archived
    whole. `checksum` is the digest of the file's bytes; `content_hash` is the Factory's
    canonical digest (provenance.schema.json#/$defs/hash) when the artifact carries
    provenance, which is what a gate would pin.

    `seq` orders every artifact the run holds by production, across ids. It is what
    "the newest artifact of a type" means; timestamps cannot, because two artifacts can be
    written in the same millisecond and a wall clock can step backwards. Refs written before
    `seq` existed have none and sort before every ref that has one, then by `created_at`.
    """

    id: str
    type: str
    version: int
    location: str
    checksum: str
    produced_by: str = None
    created_at: str = None
    content_hash: str = None
    schema_version: str = None
    metadata: dict = None
    seq: int = None

    def to_dict(self):
        return {k: v for k, v in dataclasses.asdict(self).items() if v is not None}

    def order(self):
        return (self.seq if self.seq is not None else -1, self.created_at or "")

    @classmethod
    def from_dict(cls, data):
        return cls(**_fields(cls, data))


@dataclass
class ArtifactOutput:
    """An artifact a step wants persisted. The engine writes it and hands back a ref.

    `name` identifies the artifact within the run; producing the same name again is a new
    version of the same artifact, not a second artifact. It must be kebab-case, because it
    becomes a directory name.
    """

    type: str
    content: object
    name: str = None
    metadata: dict = None

    @property
    def artifact_id(self):
        return self.name or self.type


@dataclass
class StepResult:
    """What a step returns. `outcome` is one of StepOutcome.

    `route` is an optional label the workflow definition can branch on. A verification step
    that ran and found defects returns FAILED with route "fail" and retryable=False: it is a
    result, so retrying cannot change it, and a definition that routes "fail" back to
    development loops while one that does not simply fails the run. When `route` is absent
    the engine routes on the outcome itself.

    `retryable` only matters for FAILED: a failure the step knows will recur (bad input, a
    refused precondition) says so and skips the remaining attempts.
    """

    outcome: str
    route: str = None
    artifacts: list = field(default_factory=list)
    message: str = None
    error: str = None
    retryable: bool = True
    data: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.outcome not in StepOutcome.ALL:
            raise ValueError(
                f"unknown step outcome {self.outcome!r}; expected one of "
                f"{', '.join(StepOutcome.ALL)}"
            )

    @classmethod
    def success(cls, artifacts=None, route=None, message=None, **data):
        return cls(StepOutcome.SUCCESS, route=route, artifacts=list(artifacts or []),
                   message=message, data=data)

    @classmethod
    def failed(cls, error, retryable=True, **data):
        return cls(StepOutcome.FAILED, error=error, retryable=retryable, data=data)

    @classmethod
    def blocked(cls, message, **data):
        return cls(StepOutcome.BLOCKED, message=message, data=data)

    @classmethod
    def waiting_for_input(cls, message, **data):
        return cls(StepOutcome.WAITING_FOR_INPUT, message=message, data=data)

    @classmethod
    def waiting_for_human(cls, message, **data):
        return cls(StepOutcome.WAITING_FOR_HUMAN, message=message, data=data)

    @property
    def routing_key(self):
        """The key the definition's `on:` map is consulted with."""
        return self.route or self.outcome.lower()


@dataclass
class StepState:
    """One step's persisted position in a run.

    `attempts` counts executions in the current visit and resets when the step is entered
    again (a verify-fail loop re-enters develop) or resumed; `executions` counts every
    execution in the run and never resets. `visits` counts entries; the loop limit is
    measured against `visits - loop_base`, and a resume raises `loop_base` to `visits` so
    that a person resuming a loop-blocked run grants every step a fresh budget.

    `route_visits` counts entries per route - the label or outcome that routed into the
    step (`fail`, `request-changes`, `success`, ...) - over the whole run, and `route_base`
    is each route's count when the budget was last reset, exactly as `loop_base` is for
    `visits`: a step's `max_visits_by_route` is measured against the difference. Entries
    with no route (a run's first step, `--from`, a resume's "one more pass" at a step
    limit) are counted in `visits` only. `entered_by` is the route of the current visit.
    State written before these existed has none of them, and reads as {} / None.
    """

    status: str = StepStatus.PENDING
    attempts: int = 0
    executions: int = 0
    visits: int = 0
    loop_base: int = 0
    route_visits: dict = field(default_factory=dict)
    route_base: dict = field(default_factory=dict)
    entered_by: str = None
    started_at: str = None
    finished_at: str = None
    duration_ms: int = None
    last_route: str = None
    message: str = None
    error: str = None
    outputs: list = field(default_factory=list)
    consumed: list = field(default_factory=list)
    # Liveness of the current execution, from WorkflowContext.progress: the child process
    # the step is waiting on, when anything last showed signs of life (heartbeats included:
    # the driver is alive), and what that was. `last_output_at` is when the step's children
    # last wrote anything - or a lifecycle event happened (started, spawned, exited, ...) -
    # which a heartbeat alone never moves forward; `last_heartbeat_at` is the last heartbeat.
    # State written before these two existed has neither, and derives as it always did.
    pid: int = None
    last_activity_at: str = None
    last_event: str = None
    last_output_at: str = None
    last_heartbeat_at: str = None
    # When the current visit first returned a WAITING outcome, from the engine's clock. Kept
    # across resumes of the same visit, cleared when the step is entered again; corroborated
    # by the STEP_WAITING event that recorded it before anything relies on it
    # (integrity.waiting_since_on_record). A checkpoint's timeout is measured from it.
    waiting_since: str = None

    def to_dict(self):
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, data):
        return cls(**_fields(cls, data))


@dataclass
class RunState:
    """Everything needed to resume a run, and nothing that can be derived from elsewhere.

    `cursor` is the step the run will execute next (None once the run has left its scope).
    `scope` is the set of step ids this run may execute - the whole workflow for
    `new-game`, a group for `plan`, a single step for `verify`. A transition to a step
    outside the scope ends the run; `exit` records where it would have gone.

    `blocked_reason` says, as data, why the engine itself stopped the run BLOCKED - today
    only `{"kind": "loop-limit", "step", "route", "scope": "step"|"route", "limit",
    "entered", "from"}` - and is None otherwise. What resume does with a blocked run is
    decided from it, never from the wording of `message`.
    """

    run_id: str
    workflow_id: str
    workflow_version: object
    status: str
    cursor: object
    scope: list
    project_id: str = None
    workflow_source: str = None
    created_at: str = None
    updated_at: str = None
    steps: dict = field(default_factory=dict)
    artifacts: dict = field(default_factory=dict)
    decisions: dict = field(default_factory=dict)
    trail: list = field(default_factory=list)
    params: dict = field(default_factory=dict)
    exit: dict = None
    message: str = None
    blocked_reason: dict = None
    format: int = STATE_FORMAT

    def step(self, step_id):
        if step_id not in self.steps:
            self.steps[step_id] = StepState()
        return self.steps[step_id]

    def latest_artifact(self, artifact_id):
        """The newest ArtifactRef with that id, or None."""
        versions = self.artifacts.get(artifact_id) or []
        return versions[-1] if versions else None

    def latest_of_type(self, artifact_type):
        """The newest ArtifactRef of that type across every artifact id, or None."""
        found = [
            versions[-1]
            for versions in self.artifacts.values()
            if versions and versions[-1].type == artifact_type
        ]
        return max(found, key=ArtifactRef.order) if found else None

    def next_artifact_seq(self):
        return 1 + max((ref.seq or 0 for versions in self.artifacts.values()
                        for ref in versions), default=0)

    def to_dict(self):
        data = {
            "format": self.format,
            "run_id": self.run_id,
            "workflow_id": self.workflow_id,
            "workflow_version": self.workflow_version,
            "workflow_source": self.workflow_source,
            "project_id": self.project_id,
            "status": self.status,
            "cursor": self.cursor,
            "scope": list(self.scope),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "message": self.message,
            "blocked_reason": self.blocked_reason,
            "exit": self.exit,
            "params": self.params,
            "steps": {key: value.to_dict() for key, value in self.steps.items()},
            "artifacts": {
                key: [ref.to_dict() for ref in versions]
                for key, versions in self.artifacts.items()
            },
            "decisions": self.decisions,
            "trail": self.trail,
        }
        return data

    @classmethod
    def from_dict(cls, data):
        if data.get("format") != STATE_FORMAT:
            raise ValueError(
                f"run state format {data.get('format')!r} is not {STATE_FORMAT}; this engine "
                f"cannot resume it"
            )
        state = cls(**_fields(cls, {
            key: value for key, value in data.items() if key not in ("steps", "artifacts")
        }))
        state.steps = {
            key: StepState.from_dict(value) for key, value in (data.get("steps") or {}).items()
        }
        state.artifacts = {
            key: [ArtifactRef.from_dict(ref) for ref in versions]
            for key, versions in (data.get("artifacts") or {}).items()
        }
        return state


# -- liveness ---------------------------------------------------------------------------------


class Liveness:
    """What `wgf status` says about whether a run is actually making progress.

    Derived, never stored: from the run's status, whether a live process holds its lock,
    and how long ago anything last showed signs of life.
    """

    RUNNING = "running"      # RUNNING, lock held, activity within the threshold
    HUNG = "hung"            # RUNNING, lock held, and one of HUNG_REASONS
    STALE = "stale"          # RUNNING on disk, nobody holds the lock: the driver crashed
    PENDING = "pending"
    WAITING = "waiting"
    PAUSED = "paused"
    BLOCKED = "blocked"
    FAILED = "failed"
    COMPLETED = "completed"
    CANCELLED = "cancelled"

    ALL = (RUNNING, HUNG, STALE, PENDING, WAITING, PAUSED, BLOCKED, FAILED, COMPLETED,
           CANCELLED)

    # Why a run reads HUNG. DRIVER: nothing at all - not even a heartbeat - for longer than
    # hung_after_seconds; the Factory process itself has stopped reporting. OUTPUT: the
    # driver's heartbeats keep arriving, but the child it waits on has written nothing for
    # longer than hung_output_seconds.
    DRIVER = "driver"
    OUTPUT = "output"
    HUNG_REASONS = (DRIVER, OUTPUT)


# factory.execution.hung_output_seconds when the configuration does not say. Above every idle
# timeout a shipped module uses or recommends (the reviewer's 600 s default, the developer's
# documented 900 s): a child that module policy still lets be quiet does not read as hung.
DEFAULT_HUNG_OUTPUT_SECONDS = 900


def parse_timestamp(value):
    """An engine timestamp (`2026-01-01T00:00:00.000Z`) as an aware datetime, or None."""
    if not isinstance(value, str) or not value:
        return None
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.timezone.utc)
    return parsed


def format_timestamp(moment):
    """An aware datetime as an engine timestamp (UTC, milliseconds, `Z`)."""
    moment = moment.astimezone(datetime.timezone.utc)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


def _current_step(state):
    """(step id, StepState) the status is about: the cursor, else the last step executed."""
    if state.cursor and state.cursor in state.steps:
        return state.cursor, state.steps[state.cursor]
    for entry in reversed(state.trail or []):
        step_id = entry.get("step")
        if step_id in state.steps:
            return step_id, state.steps[step_id]
    return state.cursor, None


def derive_liveness(state, lock_owner, now, hung_after_seconds=300,
                    hung_output_seconds=DEFAULT_HUNG_OUTPUT_SECONDS):
    """Pure: a dict describing the current (or last) step and the run's liveness.

    `lock_owner` is the pid of the live process holding the run's lock, or None.
    `now` is an aware datetime. Nothing here reads a clock, a file or a process.

    A RUNNING run with a live driver is HUNG when (`hung_reason`):
      * "driver" - nothing, not even a heartbeat, for longer than `hung_after_seconds`; or
      * "output" - the step is waiting on a child (`pid`), heartbeats say the driver is
        alive, and neither the child's output nor a lifecycle event has moved
        `last_output_at` for longer than `hung_output_seconds`.
    A step whose state predates `last_output_at` (or that runs with heartbeats off) can
    only be hung for the first reason.
    """
    step_id, step = _current_step(state)
    started = parse_timestamp(step.started_at) if step else None
    stamps = [parse_timestamp(value) for value in (
        step.last_activity_at if step else None,
        step.started_at if step else None,
        state.updated_at,
    )]
    stamps = [stamp for stamp in stamps if stamp is not None]
    last_activity = max(stamps) if stamps else None
    idle = (now - last_activity).total_seconds() if last_activity else None

    last_output = parse_timestamp(step.last_output_at) if step else None
    last_beat = parse_timestamp(step.last_heartbeat_at) if step else None
    output_idle = (now - last_output).total_seconds() if last_output else None

    reason = None
    if state.status == RunStatus.RUNNING:
        if lock_owner is None:
            liveness = Liveness.STALE
        elif idle is not None and idle > hung_after_seconds:
            liveness, reason = Liveness.HUNG, Liveness.DRIVER
        elif (step is not None and step.status == StepStatus.RUNNING and step.pid
              and last_beat is not None and output_idle is not None
              and output_idle > hung_output_seconds):
            liveness, reason = Liveness.HUNG, Liveness.OUTPUT
        else:
            liveness = Liveness.RUNNING
    else:
        liveness = str(state.status).lower()  # the waiting and terminal states name themselves

    if step is not None and step.status == StepStatus.RUNNING and started is not None:
        elapsed = (now - started).total_seconds()
    elif step is not None and step.duration_ms is not None:
        elapsed = step.duration_ms / 1000.0
    else:
        elapsed = None

    return {
        "run_id": state.run_id,
        "run_status": state.status,
        "liveness": liveness,
        "hung_reason": reason,
        "driver_pid": lock_owner,
        "step": step_id,
        "attempt": step.attempts if step else None,
        "visit": step.visits if step else None,
        "status": step.status if step else None,
        "started_at": step.started_at if step else None,
        "last_activity_at": format_timestamp(last_activity) if last_activity else None,
        "last_output_at": format_timestamp(last_output) if last_output else None,
        "last_heartbeat_at": format_timestamp(last_beat) if last_beat else None,
        "pid": step.pid if step else None,
        "last_event": step.last_event if step else None,
        "elapsed_seconds": round(elapsed, 3) if elapsed is not None else None,
        "idle_seconds": round(idle, 3) if idle is not None else None,
        "output_idle_seconds": round(output_idle, 3) if output_idle is not None else None,
        "hung_after_seconds": hung_after_seconds,
        "hung_output_seconds": hung_output_seconds,
    }

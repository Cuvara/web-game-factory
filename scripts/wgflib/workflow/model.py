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

    def to_dict(self):
        return {k: v for k, v in dataclasses.asdict(self).items() if v is not None}

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
    """

    status: str = StepStatus.PENDING
    attempts: int = 0
    executions: int = 0
    visits: int = 0
    loop_base: int = 0
    started_at: str = None
    finished_at: str = None
    duration_ms: int = None
    last_route: str = None
    message: str = None
    error: str = None
    outputs: list = field(default_factory=list)
    consumed: list = field(default_factory=list)
    # Liveness of the current execution, from WorkflowContext.progress: the child process
    # the step is waiting on, when anything last showed signs of life, and what that was.
    pid: int = None
    last_activity_at: str = None
    last_event: str = None

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
        return max(found, key=lambda ref: ref.created_at or "") if found else None

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

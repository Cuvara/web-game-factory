"""The workflow API: the one place that assembles an engine. The CLI is a thin shell over it.

    CLI  ->  WorkflowAPI  ->  WorkflowEngine  ->  WorkflowDefinition  ->  steps

Every `wgf` command that runs work goes through `WorkflowAPI.run`, differing only in the
scope it names. That is the whole of the "command design" rule: no command has an
orchestration of its own to drift from the others.
"""

import datetime
import os

from .. import paths, procs
from . import checkpoint, mock
from .config import load_config
from .definition import WORKFLOWS, load_definition
from .engine import WorkflowEngine
from .contracts import ArtifactContracts
from .model import derive_liveness
from .runtime import create_runtime
from .step import StepRegistry
from .store import RunStore

__all__ = ["WorkflowAPI", "RunRequest"]


def _no_sleep(_seconds):
    """Mock steps fail instantly; waiting out a backoff in a mock run teaches nothing."""


def _factory_owned(environ):
    return any(entry.startswith(f"{procs.TAG_ENV}=".encode())
               or entry.startswith(f"{procs.LINEAGE_ENV}=".encode())
               for entry in environ.split(b"\0"))


def spawned_by_a_step(environ=None, proc="/proc", pid=None):
    """True when this process runs inside a tree a Factory step started - a developer or
    reviewer agent calling `wgf ... --decision approve` on its own run, say.

    Every child wgflib.procs starts carries WGF_PROC_TAG in its environment. A process
    that dropped it from its own environment is still found through its ancestors', which
    it cannot rewrite (Linux: /proc/<pid>/environ). A descendant that detached itself *and*
    cleared its environment is not; see docs/agent-lifecycle.md."""
    environ = os.environ if environ is None else environ
    if environ.get(procs.TAG_ENV) or environ.get(procs.LINEAGE_ENV):
        return True
    pid = os.getpid() if pid is None else pid
    seen = set()
    while pid and pid > 1 and pid not in seen:
        seen.add(pid)
        try:
            with open(os.path.join(proc, str(pid), "stat"), encoding="utf-8",
                      errors="replace") as handle:
                parent = int(handle.read().rsplit(")", 1)[1].split()[1])
        except (OSError, ValueError, IndexError):
            return False
        if parent <= 1:
            return False
        try:
            with open(os.path.join(proc, str(parent), "environ"), "rb") as handle:
                if _factory_owned(handle.read()):
                    return True
        except OSError:
            pass  # not ours to read (another user): keep walking
        pid = parent
    return False


def default_decider():
    """Who a decision given on this command line is recorded as. `automation` when the
    command runs inside a step's process tree: G4, G6 and G7 then refuse it."""
    return "automation" if spawned_by_a_step() else "human"


def checkpoint_gates(definition):
    """Gates named by the definition's human-checkpoint steps."""
    return {
        step.params["gate"] for step in definition.steps
        if step.type == checkpoint.HumanCheckpointStep.type and step.params.get("gate")
    }


class RunRequest:
    """What a run command asked for. Every field is optional."""

    def __init__(self, scope=None, mock=False, mock_plan=None, resume=None, from_step=None,
                 run_id=None, force=False, decision=None, note=None, project_id=None,
                 hold_gates=False, decided_by=None):
        self.scope = scope
        self.mock = mock
        self.mock_plan = mock_plan
        self.resume = resume
        self.from_step = from_step
        self.run_id = run_id
        self.force = force
        self.decision = decision
        self.note = note
        self.project_id = project_id
        self.hold_gates = hold_gates
        # None: default_decider() - "human", unless the command runs inside a step's tree.
        self.decided_by = decided_by


class WorkflowAPI:
    def __init__(self, config=None, config_path=None, store_dir=None, workflow=None,
                 workflow_dirs=(), subscribers=(), clock=None, sleep=None,
                 run_id_factory=None):
        self.config = config or load_config(config_path)
        self.store = RunStore(store_dir or self.config.storage_directory(),
                              fsync=self.config.fsync)
        self.workflow_ref = workflow or self.config.default_workflow
        # A workflow given by path makes its directory searchable, so that resuming a run
        # of it later can find it again by id.
        self.workflow_dirs = [WORKFLOWS] + list(workflow_dirs)
        if self.workflow_ref and self.workflow_ref.endswith(".yaml"):
            self.workflow_dirs.append(os.path.dirname(os.path.abspath(self.workflow_ref)))
        self.subscribers = list(subscribers)
        self._overrides = {
            key: value
            for key, value in (("clock", clock), ("sleep", sleep),
                               ("run_id_factory", run_id_factory))
            if value is not None
        }

    # -- assembly -----------------------------------------------------------------------

    def definition_for(self, state):
        """The definition a run was started from: by id, else by the path it recorded."""
        try:
            return self.definition(state.workflow_id)
        except FileNotFoundError:
            if not state.workflow_source:
                raise
            return self.definition(os.path.join(paths.ROOT, state.workflow_source))

    def definition(self, workflow_ref=None):
        return load_definition(
            workflow_ref or self.workflow_ref,
            base_retry=self.config.retry_policy(),
            base_max_visits=self.config.max_visits,
            search=tuple(self.workflow_dirs),
        )

    def registry(self, use_mock):
        registry = StepRegistry()
        checkpoint.register(registry)
        registry.load_modules(self.config.step_modules)
        if use_mock:
            mock.register(registry)  # registered last, so mocks replace real modules
        return registry

    def engine(self, use_mock, workflow_ref=None):
        overrides = dict(self._overrides)
        if use_mock:
            overrides.setdefault("sleep", _no_sleep)
        definition = (workflow_ref if hasattr(workflow_ref, "steps")
                      else self.definition(workflow_ref))
        return WorkflowEngine(
            definition,
            self.registry(use_mock),
            self.store,
            runtime=create_runtime(self.config.runtime),
            config=self.config.data,
            subscribers=self.subscribers,
            artifact_validator=ArtifactContracts(untyped=definition.untyped_artifacts),
            **overrides,
        )

    # -- operations ---------------------------------------------------------------------

    def run(self, request):
        """Start, resume or continue a run. Returns the RunState it ended in."""
        if request.resume or request.run_id:
            run_id = request.resume or request.run_id
            existing = self.store.load(run_id)
            engine = self.engine(bool(existing.params.get("mock")), self.definition_for(existing))
            if request.resume:
                decided_by = request.decided_by or default_decider()
                return engine.resume(run_id, from_step=request.from_step,
                                     decision=request.decision, decided_by=decided_by,
                                     note=request.note)
            return engine.continue_in(run_id, request.scope, force=request.force)

        params = {}
        if request.mock:
            params["mock"] = True
            if request.mock_plan:
                params["mock_plan"] = request.mock_plan
        engine = self.engine(request.mock)
        auto = set(self.config.auto_approve)
        if request.mock and not request.hold_gates:
            # Only the gates this workflow actually checkpoints, and only reversible ones:
            # a mock run approves its own checkpoints, never a gate it does not contain.
            auto |= checkpoint_gates(engine.definition) - checkpoint.irreversible_gates()
        if auto:
            params["auto_approve"] = sorted(auto)  # the checkpoint refuses irreversible ones

        scope = request.scope
        if scope == engine.definition.id:
            scope = None
        return engine.start(scope=scope, start_at=request.from_step,
                            project_id=request.project_id, params=params)

    def status(self, run_id=None):
        """(state, definition) for a run, or the latest run when no id is given."""
        state = self.store.load(run_id) if run_id else self.store.latest()
        if state is None:
            return None, None
        return state, self.definition_for(state)

    def liveness(self, state, now=None):
        """derive_liveness for `state`, against the lock as it is right now."""
        now = now or datetime.datetime.now(datetime.timezone.utc)
        return derive_liveness(state, self.store.lock_owner(state.run_id), now,
                               self.config.hung_after_seconds)

    def events(self, run_id=None, problems=None):
        """(state, events). Unreadable event lines are skipped and added to `problems`."""
        state = self.store.load(run_id) if run_id else self.store.latest()
        return ((state, self.store.read_events(state.run_id, problems)) if state
                else (None, []))

    def runs(self, problems=None):
        return self.store.list_runs(problems)

    def pause(self, run_id):
        state = self.store.load(run_id)
        engine = self.engine(bool(state.params.get("mock")), self.definition_for(state))
        return engine.request_pause(run_id)

    def cancel(self, run_id):
        state = self.store.load(run_id)
        engine = self.engine(bool(state.params.get("mock")), self.definition_for(state))
        return engine.request_cancel(run_id)

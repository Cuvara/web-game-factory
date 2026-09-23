"""The workflow API: the one place that assembles an engine. The CLI is a thin shell over it.

    CLI  ->  WorkflowAPI  ->  WorkflowEngine  ->  WorkflowDefinition  ->  steps

Every `wgf` command that runs work goes through `WorkflowAPI.run`, differing only in the
scope it names. That is the whole of the "command design" rule: no command has an
orchestration of its own to drift from the others.
"""

import os

from .. import paths
from ..machine import load_gates
from . import checkpoint, mock
from .config import load_config
from .definition import WORKFLOWS, load_definition
from .engine import WorkflowEngine
from .model import RunStatus
from .runtime import create_runtime
from .step import StepRegistry
from .store import RunStore

__all__ = ["WorkflowAPI", "RunRequest"]


def _no_sleep(_seconds):
    """Mock steps fail instantly; waiting out a backoff in a mock run teaches nothing."""


class RunRequest:
    """What a run command asked for. Every field is optional."""

    def __init__(self, scope=None, mock=False, mock_plan=None, resume=None, from_step=None,
                 run_id=None, force=False, decision=None, note=None, project_id=None,
                 hold_gates=False):
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
                return engine.resume(run_id, from_step=request.from_step,
                                     decision=request.decision, note=request.note)
            return engine.continue_in(run_id, request.scope, force=request.force)

        params = {}
        if request.mock:
            params["mock"] = True
            if request.mock_plan:
                params["mock_plan"] = request.mock_plan
        auto = list(self.config.auto_approve)
        if request.mock and not request.hold_gates:
            reversible = set(load_gates()) - checkpoint.irreversible_gates()
            auto = sorted(set(auto) | reversible)
        if auto:
            params["auto_approve"] = auto  # irreversible gates are refused by the checkpoint

        engine = self.engine(request.mock)
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

    def events(self, run_id=None):
        state = self.store.load(run_id) if run_id else self.store.latest()
        return (state, self.store.read_events(state.run_id)) if state else (None, [])

    def runs(self):
        return self.store.list_runs()

    def pause(self, run_id):
        state = self.store.load(run_id)
        if state.status != RunStatus.RUNNING:
            raise ValueError(f"run {run_id} is {state.status}, not RUNNING; nothing to pause")
        self.store.request(run_id, "pause")

    def cancel(self, run_id):
        state = self.store.load(run_id)
        engine = self.engine(bool(state.params.get("mock")), self.definition_for(state))
        return engine.request_cancel(run_id)

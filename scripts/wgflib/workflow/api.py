"""The workflow API: the one place that assembles an engine. The CLI is a thin shell over it.

    CLI  ->  WorkflowAPI  ->  WorkflowEngine  ->  WorkflowDefinition  ->  steps

Every `wgf` command that runs work goes through `WorkflowAPI.run`, differing only in the
scope it names. That is the whole of the "command design" rule: no command has an
orchestration of its own to drift from the others.
"""

import datetime
import importlib
import os
import re
import unicodedata

from .. import budget, gate_evidence, paths, procs
from . import checkpoint, integrity, mock, quality
from .config import ConfigError, load_config
from .definition import WORKFLOWS, load_definition
from .engine import EngineError, WorkflowEngine
from .events import Events
from .contracts import ArtifactContracts
from .model import RunStatus, StepOutcome, StepStatus, derive_liveness
from .runtime import create_runtime
from .step import StepRegistry
from .store import RunStore, StoreError

__all__ = ["WorkflowAPI", "RunRequest", "pending_decision", "missing_inputs",
           "timeout_windows", "ended_by_decision", "canonical_idea", "IDEA_MAX_LENGTH",
           "IDEA_STEP_TYPE"]

# The game idea a person may give a new run (`wgf new-game "..."`). It is the brief the run
# is anchored to: recorded once in the run's params, where resume corroborates it against
# WORKFLOW_STARTED, and read by the step of this type, which carries it into its artifacts.
IDEA_MAX_LENGTH = 500
IDEA_STEP_TYPE = "research"
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")


def canonical_idea(text):
    """The one canonical form of a game idea: NFC, trimmed, whitespace runs as one space.

    Nothing else is changed - not case, not punctuation, not wording: the idea is the
    person's, and every step downstream reads exactly this string. Raises ValueError for an
    idea that is empty, carries control characters, or is longer than IDEA_MAX_LENGTH.
    """
    if not isinstance(text, str):
        raise ValueError("the game idea must be text")
    idea = " ".join(unicodedata.normalize("NFC", text).split())
    if not idea:
        raise ValueError("the game idea is empty; give it as one quoted argument, or none "
                         "for a blank market scan")
    if _CONTROL.search(idea):
        raise ValueError("the game idea contains control characters")
    if len(idea) > IDEA_MAX_LENGTH:
        raise ValueError(f"the game idea is {len(idea)} characters; the limit is "
                         f"{IDEA_MAX_LENGTH}")
    return idea


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


def timeout_windows(config):
    """factory.checkpoints.timeout_auto_approve as {gate: seconds}, checked against gates.yaml.

    Fail closed: a gate gates.yaml does not define, or an irreversible one (G4, G6, G7),
    listed there is refused with a ConfigError - a run is not started under a configuration
    that asks for something the Factory will never do."""
    windows = config.timeout_auto_approve
    known = checkpoint.known_gates()
    refused = []
    for gate in sorted(windows):
        if gate not in known:
            refused.append(f"{gate} (not a gate core/lifecycle/gates.yaml defines)")
        elif checkpoint.is_irreversible(gate):
            refused.append(f"{gate} (irreversible: only a person decides it)")
    if refused:
        raise ConfigError(
            "factory.checkpoints.timeout_auto_approve lists " + ", ".join(refused)
            + "; remove it - no run starts under this configuration")
    return windows


def ended_by_decision(state):
    """{"step", "decision", "decided_by", "decided_at", "note", "mode"} when the run ended
    because a decision stopped it - a checkpoint answered with a stopping choice (G4's
    kill, a reject) routed to `$end` - else None. Read-only."""
    ended = state.exit or {}
    if (state.status != RunStatus.COMPLETED or ended.get("next") != "$end"
            or ended.get("outcome") in (None, StepOutcome.SUCCESS)):
        return None
    step_id = ended.get("step")
    entry = (state.decisions or {}).get(step_id)
    step = (state.steps or {}).get(step_id)
    if (not isinstance(entry, dict) or step is None or entry.get("visit") != step.visits
            or entry.get("decision") != ended.get("route")):
        return None
    return {"step": step_id, **{key: entry.get(key) for key in (
        "decision", "decided_by", "decided_at", "note", "mode")}}


def _utc(now):
    return now or datetime.datetime.now(datetime.timezone.utc)


def pending_decision(state, definition=None, events=(), now=None):
    """What a run is waiting for a person to decide, or None.

    A run waits for a decision when it is WAITING at a step that asked for a person
    (WAITING_FOR_HUMAN) - a human checkpoint above all - rather than for missing data
    (WAITING_FOR_INPUT). Returns {"step", "gate", "choices", "prompt", "timeout"}; gate,
    choices and prompt are None when neither the definition nor the step's last
    STEP_WAITING event says. `timeout` is None, or - for a gate the run lets approve itself
    on a timeout - {"gate", "window_seconds", "waiting_since", "eligible_at", "eligible"},
    judged at `now` (an aware datetime; default the wall clock) from the same corroborated
    waiting_since the engine uses. Read-only: it answers nothing, and an eligible gate is
    approved only by the next `wgf resume`.
    """
    if state.status != RunStatus.WAITING or not state.cursor:
        return None
    step = state.steps.get(state.cursor)
    if step is None or step.status != StepStatus.WAITING:
        return None
    step_def = None
    if definition is not None and definition.has_step(state.cursor):
        step_def = definition.step(state.cursor)
    last = next((entry.get("outcome") for entry in reversed(state.trail)
                 if entry.get("step") == state.cursor), None)
    is_checkpoint = (step_def is not None
                     and step_def.type == checkpoint.HumanCheckpointStep.type)
    if last != StepOutcome.WAITING_FOR_HUMAN and not (last is None and is_checkpoint):
        return None
    info = {"step": state.cursor, "gate": None, "choices": None, "prompt": step.message}
    if is_checkpoint:
        params = step_def.params or {}
        info["gate"] = params.get("gate")
        info["choices"] = list(params.get("choices") or ["approve", "reject"])
    for event in reversed(list(events or ())):
        if event.get("event") == Events.STEP_WAITING and event.get("step_id") == state.cursor:
            result = (event.get("data") or {}).get("result") or {}
            if isinstance(result, dict):
                if info["gate"] is None and isinstance(result.get("gate"), str):
                    info["gate"] = result["gate"]
                if info["choices"] is None and isinstance(result.get("choices"), list):
                    info["choices"] = [str(c) for c in result["choices"]]
            break
    info["timeout"] = None
    gate = info["gate"]
    window = checkpoint.timeout_window(gate, state.params if isinstance(state.params, dict)
                                       else {})
    if window is not None and is_checkpoint:
        since = integrity.waiting_since(state, definition, state.cursor, list(events or ()))
        due = checkpoint.timeout_due(gate, state.params, since)
        info["timeout"] = {
            "gate": gate, "window_seconds": window, "waiting_since": since,
            "eligible_at": checkpoint.stamp(due) if due else None,
            "eligible": bool(due and _utc(now) >= due),
        }
    return info


def missing_inputs(state, definition):
    """The input types the run's cursor step declares and the run does not hold."""
    if not state.cursor or not definition.has_step(state.cursor):
        return []
    return [t for t in definition.step(state.cursor).inputs if state.latest_of_type(t) is None]


class RunRequest:
    """What a run command asked for. Every field is optional."""

    def __init__(self, scope=None, mock=False, mock_plan=None, resume=None, from_step=None,
                 run_id=None, force=False, decision=None, note=None, project_id=None,
                 hold_gates=False, decided_by=None, budget_sessions=None, budget_cost=None,
                 idea=None, exceptions=None):
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
        # With resume: raise the run's developer-session budget (wgflib.budget) to these.
        self.budget_sessions = budget_sessions
        self.budget_cost = budget_cost
        # A new run's game idea (canonical_idea); None is the blank market scan.
        self.idea = idea
        # With resume: knowledge exceptions a person grants the run (wgf resume --except),
        # each a partial knowledge-exception record ({rule_id, reason, expires_at, scope,
        # approved_by?}); completed, checked and recorded by the knowledge module.
        self.exceptions = list(exceptions or [])


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

    def registry(self, use_mock, load_modules=True):
        registry = StepRegistry()
        checkpoint.register(registry)
        if load_modules:
            registry.load_modules(self.config.step_modules)
        if use_mock:
            mock.register(registry)  # registered last, so mocks replace real modules
        return registry

    def quality_policy(self):
        """core/reference/quality-policy.yaml (wgflib.workflow.quality). Fail closed: no run
        is started or driven without it."""
        try:
            return quality.load_policy()
        except quality.PolicyError as exc:
            raise ConfigError(f"the quality policy cannot be read: {exc}; no run is started "
                              f"or driven without it")

    def quality(self, state):
        """quality.report for `state`: its tier, class, why, and whether it is release-ready.
        A policy or definition that cannot be read costs the readiness, never the run."""
        events = self.store.read_events(state.run_id, [])
        try:
            definition = self.definition_for(state)
            policy = quality.load_policy()
        except (OSError, ValueError):
            klass, reasons = quality.run_class(state.params, events)
            return {"class": klass, "reasons": reasons, "release_ready": False}
        return quality.report(state, definition, events, policy)

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
            quality_policy=self.quality_policy(),
            **overrides,
        )

    # The knowledge module (scripts/wgf_knowledge) lives outside the kernel too: the kernel
    # records only that a run's knowledge was read and which versions (quality policy rule 8),
    # and a person's exception as an operator event. What the files mean, and whether an
    # exception may be granted, is the module's - imported by name, only when needed, and a
    # missing module refuses the run rather than starting it unheld.
    KNOWLEDGE_VERSIONS = "wgf_knowledge.versions"
    KNOWLEDGE_EXCEPTIONS = "wgf_knowledge.exceptions"

    def _knowledge_module(self, name, why):
        try:
            return importlib.import_module(name)
        except ImportError as exc:
            raise ConfigError(f"{why}: the knowledge module {name} cannot be imported ({exc})")

    def _knowledge_snapshot(self, policy):
        """(knowledge versions, factory identity) a new run records (quality policy rule 8).
        Refused - a ConfigError, no run is created - when a knowledge file the policy lists
        is missing, unreadable, versionless or not shaped as knowledge."""
        if not policy.get("knowledge"):
            return None, None
        versions = self._knowledge_module(self.KNOWLEDGE_VERSIONS,
                                          "no run is started without its knowledge")
        try:
            versions.knowledge()
            found = quality.knowledge_versions(policy)
        except (ValueError, quality.PolicyError) as exc:
            raise ConfigError(f"the Factory's knowledge cannot be read: {exc}; no run is "
                              f"started without the lessons and check tiers it is held to "
                              f"(core/reference/quality-policy.yaml rule 8)")
        return found, versions.factory()

    def _exception_events(self, existing, request, decided_by):
        """[(event, data)] for the knowledge exceptions `request` grants `existing`: a
        person's act, refused to automation and refused whole when any record does not
        hold (wgf_knowledge.exceptions.grant)."""
        if not request.exceptions:
            return []
        if decided_by == "automation":
            raise EngineError(
                "knowledge exception refused: this command runs inside a Factory step's "
                "process tree (decided_by automation). An exception is a person's act, "
                "granted from outside the run; an agent never excepts a rule it is held to.")
        module = self._knowledge_module(self.KNOWLEDGE_EXCEPTIONS,
                                        "knowledge exception refused")
        clock = self._overrides.get("clock")
        try:
            granted = module.grant(existing, self.store.run_dir(existing.run_id),
                                   request.exceptions, decided_by,
                                   now=clock() if clock else None,
                                   read_artifact=lambda ref: self.store.read_artifact(
                                       existing.run_id, ref))
        except module.ExceptionRefused as exc:
            raise EngineError(f"knowledge exception refused: {exc}")
        return [(module.EVENT, data) for data in granted]

    # The lifecycle bridge lives outside the kernel (it reads workspace/ and runs
    # wgf-state.py's rules), so the kernel names it only here, and imports it only for a
    # run that was started with lifecycle_sync on.
    LIFECYCLE_BRIDGE = "wgflib.lifecycle_bridge"

    def _attach_lifecycle(self, engine, params):
        """Subscribe the lifecycle bridge to `engine` when the run's params (as it started)
        say so. It reports through the engine's bus and never affects the run's outcome."""
        if not (isinstance(params, dict) and params.get("lifecycle_sync") is True):
            return engine
        bridge = importlib.import_module(self.LIFECYCLE_BRIDGE).LifecycleBridge(
            self.store, self.config.lifecycle_titles_directory())
        engine.bus.subscribe(bridge.subscriber(engine.bus.emit))
        return engine

    def control_engine(self, state):
        """An engine for pause and cancel, which touch only the store and the definition.

        No step module is imported, no runtime or artifact contracts are built: one broken
        module in factory.steps.modules must not take away the way to stop a run.
        """
        return WorkflowEngine(
            self.definition_for(state),
            self.registry(False, load_modules=False),
            self.store,
            config=self.config.data,
            subscribers=self.subscribers,
            **{k: v for k, v in self._overrides.items() if k == "clock"},
        )

    # -- operations ---------------------------------------------------------------------

    def run(self, request):
        """Start, resume or continue a run. Returns the RunState it ended in."""
        if request.resume or request.run_id:
            run_id = request.resume or request.run_id
            existing = self.store.load(run_id)
            engine = self.engine(bool(existing.params.get("mock")), self.definition_for(existing))
            # From the params the run carries; the engine refuses to drive a state.json whose
            # params differ from the ones it started with, so an edit cannot add or drop it.
            self._attach_lifecycle(engine, existing.params)
            raising = request.budget_sessions is not None or request.budget_cost is not None
            if raising and not request.resume:
                raise EngineError("a budget is raised with resume: wgf resume <run-id> "
                                  "--budget-sessions N | --budget-cost X")
            if request.exceptions and not request.resume:
                raise EngineError("a knowledge exception is granted with resume: wgf resume "
                                  "<run-id> --except RULE --reason TEXT --expires DATE")
            if request.resume:
                decided_by = request.decided_by or default_decider()
                operator_events = []
                events = self.store.read_events(run_id)
                held = budget.base(existing.params, events)
                configured = self.config.develop_budget
                if held is None and configured is not None and decided_by != "automation":
                    # A run started without a budget takes the one its project configures
                    # now (the autonomous profile copied in mid-run): its developer may be a
                    # paid, unattended agent by now, and a run with no budget is one the
                    # develop step refuses to start such an agent for. A person's act,
                    # recorded like a raise - never an edit of the run's params.
                    operator_events.append((budget.ADOPTED_EVENT, {"budget": configured}))
                    held = configured
                if raising:
                    # A person's act, recorded as an event the develop step reads; never
                    # an edit of the snapshot (which params corroboration refuses).
                    if decided_by == "automation":
                        raise EngineError(
                            "budget raise refused: this command runs inside a Factory step's "
                            "process tree (decided_by automation), and an agent does not "
                            "raise its own budget. A person raises it, from outside the run.")
                    try:
                        raised = budget.check_raise(held, request.budget_sessions,
                                                    request.budget_cost)
                    except budget.BudgetError as exc:
                        raise EngineError(f"budget raise refused: {exc}")
                    operator_events.append((budget.RAISED_EVENT, raised))
                # A person's knowledge exception, recorded the same way: an operator event
                # the knowledge step and the quality gate read, corroborated by this
                # resume's nonce - never an edit of the run's params or contract.
                operator_events += self._exception_events(existing, request, decided_by)
                return engine.resume(run_id, from_step=request.from_step,
                                     decision=request.decision, decided_by=decided_by,
                                     note=request.note, operator_events=operator_events)
            return engine.continue_in(run_id, request.scope, force=request.force)

        params = {}
        if request.mock:
            params["mock"] = True
            if request.mock_plan:
                params["mock_plan"] = request.mock_plan
        engine = self.engine(request.mock)
        if request.idea is not None:
            idea = canonical_idea(request.idea)
            self._refuse_idea_without_reader(engine.definition, request)
            # Recorded only when given, so a run without one keeps the params it always had.
            params["idea"] = idea
        auto = set(self.config.auto_approve)
        if request.mock and not request.hold_gates:
            # Only the gates this workflow actually checkpoints, and only reversible ones:
            # a mock run approves its own checkpoints, never a gate it does not contain.
            auto |= checkpoint_gates(engine.definition) - checkpoint.irreversible_gates()
        if auto:
            params["auto_approve"] = sorted(auto)  # the checkpoint refuses irreversible ones
        # Snapshotted like auto_approve: the run keeps the windows it started under, and a
        # resume corroborates them against WORKFLOW_STARTED (integrity.params_problems).
        windows = timeout_windows(self.config)
        if windows:
            params["timeout_auto_approve"] = dict(sorted(windows.items()))
        # The hung-child watchdog, snapshotted the same way: a resume keeps the policy the
        # run started under, and an edit of it in state.json is refused. `none` - the
        # default - records nothing, so runs without a watchdog carry the params they
        # always did.
        if self.config.on_hung != "none":
            params["on_hung"] = self.config.on_hung
            params["hung_output_seconds"] = self.config.hung_output_seconds
        # The lifecycle bridge, snapshotted the same way and recorded only when on: a run
        # syncs its gate decisions into workspace/titles for its whole life, or never.
        if self.config.lifecycle_sync:
            params["lifecycle_sync"] = True
            self._attach_lifecycle(engine, params)
        # The developer-session budget (factory.develop.budget), snapshotted the same way:
        # a resume keeps the budget the run started with - raised only by a person's
        # BUDGET_RAISED event - and no budget records nothing (a later resume adopts one
        # configured by then: BUDGET_ADOPTED, above).
        develop_budget = self.config.develop_budget
        if develop_budget is not None:
            params[budget.PARAM] = develop_budget
        # The quality policy, snapshotted the same way: the tier the run builds to, its class
        # (release or development) and why, and the policy and benchmark versions it started
        # under. Every step that budgets or judges content reads the tier from here, never
        # from a configuration changed since; a later configuration only lowers the class
        # (QUALITY_DOWNGRADED, recorded by the engine when a drive begins).
        # The knowledge the run is held to (rule 8): its versions and the Factory's own,
        # recorded the same way; a run whose knowledge cannot be read is never created.
        knowledge, factory = self._knowledge_snapshot(engine.quality_policy)
        try:
            params[quality.PARAM] = quality.snapshot(engine.quality_policy, self.config.data,
                                                     engine.definition, mock=request.mock,
                                                     factory=factory, knowledge=knowledge)
            # A run the configuration cannot take to its tier is not started at all - the
            # way a timeout window on an irreversible gate is refused - rather than failing
            # hours later at the step that cannot meet it.
            refused = quality.preflight_refusals(
                engine.quality_policy, self.config.data, engine.definition,
                self._new_run_steps(engine.definition, request), mock=request.mock,
                implementation=self._implementation(engine.registry, engine.definition))
        except quality.PolicyError as exc:
            raise ConfigError(str(exc))
        if refused:
            raise ConfigError(
                f"no run is started: at quality tier {params[quality.PARAM]['tier']} "
                + "; ".join(refused) + " (core/reference/quality-policy.yaml preflight)")

        scope = request.scope
        if scope == engine.definition.id:
            scope = None
        return engine.start(scope=scope, start_at=request.from_step,
                            project_id=request.project_id, params=params)

    @staticmethod
    def _new_run_steps(definition, request):
        """The step ids a new run of `request` would execute: its scope from --from on."""
        scope = None if request.scope == definition.id else request.scope
        ids = definition.resolve_scope(scope)
        if request.from_step in ids:
            ids = ids[ids.index(request.from_step):]
        return ids

    @staticmethod
    def _implementation(registry, definition):
        """step id -> the module implementing it in `registry`, or None."""
        def module_of(step_id):
            if not step_id or not definition.has_step(step_id):
                return None
            try:
                factory = registry.resolve(definition.step(step_id).type)
            except Exception:
                return None
            return getattr(factory, "__module__", None)
        return module_of

    def preflight(self, workflow_ref=None):
        """What a new, non-mock run of the whole workflow would be under the configuration
        now: {"tier", "class", "reasons", "refused"}. Read-only; `wgf where` reports it."""
        policy = self.quality_policy()
        definition = self.definition(workflow_ref)
        try:
            taken = quality.snapshot(policy, self.config.data, definition)
        except quality.PolicyError as exc:
            return {"tier": None, "class": quality.DEVELOPMENT, "reasons": [],
                    "refused": [f"{exc} (core/reference/quality-policy.yaml rule 8)"]}
        try:
            registry = self.registry(False)
        except Exception:  # a module that cannot be imported: the run would say so itself
            registry = self.registry(False, load_modules=False)
        return {"tier": taken["tier"], "class": taken["class"],
                "reasons": taken.get("reasons") or [],
                "refused": quality.preflight_refusals(
                    policy, self.config.data, definition, definition.step_ids,
                    implementation=self._implementation(registry, definition))}

    @staticmethod
    def _refuse_idea_without_reader(definition, request):
        """An idea is read by the research step; a run that never executes one would carry
        it silently and build something else. Refused, never ignored."""
        scope = None if request.scope == definition.id else request.scope
        ids = definition.resolve_scope(scope)
        if request.from_step in ids:
            ids = ids[ids.index(request.from_step):]
        if not any(definition.step(s).type == IDEA_STEP_TYPE for s in ids):
            raise EngineError(
                f"a game idea is read by the {IDEA_STEP_TYPE} step, and this run "
                f"({request.scope or definition.id}"
                f"{' --from ' + request.from_step if request.from_step else ''}) does not "
                f"run one; start at {IDEA_STEP_TYPE}, or give no idea")

    def status(self, run_id=None):
        """(state, definition) for a run, or the latest run when no id is given."""
        state = self.store.load(run_id) if run_id else self.store.latest()
        if state is None:
            return None, None
        return state, self.definition_for(state)

    def liveness(self, state, now=None):
        """derive_liveness for `state`, against the lock as it is right now. The output
        threshold is the one the run's watchdog was started with, when it has one, so
        status and the watchdog agree; otherwise the configured one."""
        now = now or datetime.datetime.now(datetime.timezone.utc)
        params = state.params if isinstance(state.params, dict) else {}
        output = params.get("hung_output_seconds")
        if isinstance(output, bool) or not isinstance(output, (int, float)) or output <= 0:
            output = self.config.hung_output_seconds
        return derive_liveness(state, self.store.lock_owner(state.run_id), now,
                               self.config.hung_after_seconds, output)

    def events(self, run_id=None, problems=None):
        """(state, events). Unreadable event lines are skipped and added to `problems`."""
        state = self.store.load(run_id) if run_id else self.store.latest()
        return ((state, self.store.read_events(state.run_id, problems)) if state
                else (None, []))

    def runs(self, problems=None):
        return self.store.list_runs(problems)

    def pending(self, state, now=None):
        """pending_decision for `state`, against its definition and its recorded events.
        A definition that can no longer be found costs the gate and choices, not the run."""
        if state.status != RunStatus.WAITING:
            return None
        try:
            definition = self.definition_for(state)
        except (OSError, ValueError):
            definition = None
        info = pending_decision(state, definition, self.store.read_events(state.run_id, []),
                                now=now)
        if info is not None and definition is not None and definition.has_step(info["step"]):
            # Only when there is some: a pending decision's JSON keeps the shape it had
            # before for every checkpoint whose inputs carry no evidence fields.
            evidence = self._evidence(state, definition.step(info["step"]).inputs)
            if evidence:
                info["evidence"] = evidence
            held = self._held(state, definition.step(info["step"]).inputs, info.get("gate"))
            if held:
                # gates.yaml hold_for_person_when: this decision is a person's, so no
                # timeout will approve it - say so instead of an eligibility it lacks.
                info["held_for_person"] = held
                info["timeout"] = None
        return info

    def _held(self, state, inputs, gate):
        """checkpoint.hold_for_person over the run's newest artifact of each input type."""
        if not gate:
            return []
        refs = {t: state.latest_of_type(t) for t in inputs or ()}
        refs = {t: r for t, r in refs.items() if r is not None}

        class _Inputs:
            def __init__(self, store, run_id):
                self.refs, self._store, self._run_id = refs, store, run_id

            def load(self, artifact_type):
                return self._store.read_artifact(self._run_id, self.refs[artifact_type])

        return checkpoint.hold_for_person(gate, _Inputs(self.store, state.run_id))

    def _evidence(self, state, inputs):
        """gate_evidence.summarize over the newest artifact of each of the waiting step's
        input types. An artifact that cannot be read is left out, never guessed."""
        found = {}
        for artifact_type in inputs or ():
            ref = state.latest_of_type(artifact_type)
            if ref is None:
                continue
            try:
                found[artifact_type] = self.store.read_artifact(state.run_id, ref)
            except (StoreError, OSError, ValueError):
                continue
        return gate_evidence.summarize(found)

    def waiting(self, problems=None, now=None):
        """[(state, pending)] for every run waiting for a decision, oldest first."""
        found = []
        for state in self.store.list_runs(problems):
            info = self.pending(state, now=now)
            if info is not None:
                found.append((state, info))
        return found

    def latest_run_holding(self, artifact_types, workflow_id, exclude=None):
        """The run of `workflow_id` a slice missing `artifact_types` most likely belongs in:
        of the runs a slice could still run inside (not RUNNING, not CANCELLED), the one
        holding the most of those types, the most recently updated on a tie. Not all: a
        step's inputs include ones only a later loop produces (develop's qa-report). None
        when no run holds any of them."""
        best, best_key = None, None
        for state in self.store.list_runs():
            if (state.run_id == exclude or state.workflow_id != workflow_id
                    or state.status in (RunStatus.RUNNING, RunStatus.CANCELLED)):
                continue
            held = sum(state.latest_of_type(t) is not None for t in artifact_types)
            key = (held, state.updated_at or state.created_at or "", state.run_id)
            if held and (best_key is None or key > best_key):
                best, best_key = state, key
        return best

    def pause(self, run_id):
        return self.control_engine(self.store.load(run_id)).request_pause(run_id)

    def cancel(self, run_id):
        return self.control_engine(self.store.load(run_id)).request_cancel(run_id)

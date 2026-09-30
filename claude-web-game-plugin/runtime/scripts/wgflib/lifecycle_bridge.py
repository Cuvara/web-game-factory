"""The lifecycle bridge: a workflow run's gate decisions, carried into the title's lifecycle.

The two tiers stay separate by default. A workflow run (wgflib/workflow) executes steps and
its checkpoints emit decision-records into the run store; the lifecycle cursor
(workspace/titles/<id>/state.json) moves only through wgf-state.py. With
`factory.lifecycle.sync: true` - off by default, snapshotted into the run's params when it
starts (`lifecycle_sync`), so an edit of state.json can neither turn it on nor off - each
decision-record a run persists is also:

  1. appended to the title's `decisions/` directory, as a new file, never over an existing
     one (`<gate>-<yyyymmdd>T<hhmmssmmm>Z-<nn>.json`, which sorts after the hand-written
     `<gate>-<yyyymmdd>.json` of the same day, so "the newest file is the current one" holds);
  2. used to move the title's cursor along the edge the record authorizes - by wgf-state.py's
     own functions (choose_transition, check_guards, check_decision_record, advance), so
     every guard and gate rule that applies to a person running wgf-state.py applies here:
     an UNKNOWN guard blocks, G4/G6/G7 need `mode: human`, a stale subject is refused.

Only when the run names a title (its project id, else the title the record names) that
already has a cursor. The bridge never creates a title, never moves a cursor that is not at
the edge's source state, and never syncs a mock run - a placeholder decision on placeholder
evidence is not a decision about a real title. It moves only through gate edges; every other
transition is still wgf-state.py's.

Guards read the title's instance data, and - for the artifact types the run holds - the
run's newest version of them, because that is what the gate was decided on. The evidence
guards (ci_green, verify_suite_green, playable_build) read the run's qa-report and
verification-report (guards.RunEvidence).

Whatever goes wrong - a guard that is RED or UNKNOWN, a cursor elsewhere, an unreadable
file - is reported as a STEP_LOG warning on the run, and never changes the run's outcome:
the workflow decided; the lifecycle declined to follow, and says why.
"""

import copy
import importlib.util
import json
import os
import re

from . import paths
from .guards import GuardContext, RunEvidence
from .machine import MachineError, load_machine
from .workflow.decisions import ARTIFACT_TYPE, CHOICES
from .workflow.events import Events
from .workflow.model import ArtifactRef
from .workspace import Entity, WorkspaceError, load_portfolio_config

__all__ = ["LifecycleBridge", "SyncResult", "wgf_state", "PARAM"]

# The run param the bridge obeys (api.run snapshots factory.lifecycle.sync into it).
PARAM = "lifecycle_sync"

# decision-record `decision` -> the machine event it authorizes, from the one table.
_EVENTS = {decision: event for decision, event in CHOICES.values() if event}

_module = None


def wgf_state():
    """scripts/wgf-state.py as a module: the bridge moves a cursor with exactly the code a
    person moving it by hand runs, not a copy of it."""
    global _module
    if _module is None:
        path = os.path.join(paths.SCRIPTS, "wgf-state.py")
        spec = importlib.util.spec_from_file_location("wgf_state_cli", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _module = module
    return _module


class SyncResult:
    """What the bridge did: `level` info or warning, a message, and what it wrote."""

    def __init__(self, level, message, record_path=None, moved=None):
        self.level = level
        self.message = message
        self.record_path = record_path
        self.moved = moved

    @property
    def ok(self):
        return self.level == "info"

    def data(self):
        return {key: value for key, value in (
            ("decision_record", self.record_path), ("moved", self.moved)) if value}

    def __repr__(self):
        return f"<SyncResult {self.level}: {self.message}>"


class _RunBackedEntity(Entity):
    """A title whose guards read the run's newest artifact of a type the run holds - what
    the gate was decided on - and the title's own instance data for everything else."""

    def __init__(self, entity_id, directory, state, run_artifacts):
        super().__init__(entity_id, directory, state)
        self._run = dict(run_artifacts or {})

    def has(self, artifact_type):
        return artifact_type in self._run or super().has(artifact_type)

    def artifact(self, artifact_type):
        if artifact_type in self._run:
            return copy.deepcopy(self._run[artifact_type])
        return super().artifact(artifact_type)


def _stamp(decided_at):
    digits = re.sub(r"[^0-9]", "", str(decided_at or ""))
    date, clock = digits[:8], (digits[8:17] or "0").ljust(9, "0")
    return f"{date}T{clock}Z" if len(date) == 8 else "00000000T000000000Z"


def _atomic_write(path, payload):
    temporary = f"{path}.{os.getpid()}.tmp"
    with open(temporary, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


class LifecycleBridge:
    def __init__(self, store, titles_dir=None, portfolio_config=None):
        self.store = store
        self.titles_dir = titles_dir or paths.TITLES
        self._portfolio = portfolio_config

    # -- the event subscriber -----------------------------------------------------------

    def subscriber(self, emit):
        """An EventBus subscriber syncing each decision-record a run persists; `emit` is
        the bus's emit, used for the STEP_LOG it reports with."""

        def on_event(record):
            if record.get("event") not in (Events.ARTIFACT_CREATED, Events.ARTIFACT_UPDATED):
                return
            data = record.get("data") or {}
            if data.get("type") != ARTIFACT_TYPE or not record.get("run_id"):
                return
            try:
                result = self.on_record(record["run_id"], data)
            except Exception as exc:  # never the run's problem
                result = SyncResult("warning", f"lifecycle sync failed: "
                                               f"{type(exc).__name__}: {exc}")
            if result is not None:
                emit(Events.STEP_LOG, workflow_id=record.get("workflow_id"),
                     run_id=record["run_id"], step_id=record.get("step_id"),
                     level=result.level, message=result.message,
                     data=dict(result.data(), bridge="lifecycle") or None)

        return on_event

    def on_record(self, run_id, ref_data):
        """Sync one persisted decision-record of run `run_id`; None when the run does not
        sync (its params were not started with lifecycle_sync)."""
        state = self.store.load(run_id)
        params = state.params if isinstance(state.params, dict) else {}
        if params.get(PARAM) is not True:
            return None
        if params.get("mock"):
            return SyncResult("warning", "lifecycle not synced: a mock run's decisions are "
                                         "about placeholder artifacts, not a title")
        record = self.store.read_artifact(run_id, ArtifactRef.from_dict(ref_data))
        run_artifacts = {}
        for artifact_type in sorted({ref.type for versions in state.artifacts.values()
                                     for ref in versions} - {ARTIFACT_TYPE}):
            ref = state.latest_of_type(artifact_type)
            run_artifacts[artifact_type] = self.store.read_artifact(run_id, ref)
        evidence = RunEvidence.of_run(self.store, state)
        title = state.project_id or (record.get("provenance") or {}).get("title_id")
        return self.sync(record, title, run_artifacts=run_artifacts, evidence=evidence)

    # -- the sync ----------------------------------------------------------------------

    def sync(self, record, title_id, run_artifacts=None, evidence=None):
        """Append `record` to the title's decisions and move its cursor. A SyncResult."""
        if not title_id:
            return SyncResult("info", "lifecycle not synced: the run names no title")
        try:
            directory = paths.checkout_path(self.titles_dir, title_id)
        except ValueError as exc:
            return SyncResult("warning", f"lifecycle not synced: {exc}")
        state_path = os.path.join(directory, "state.json")
        if not os.path.isfile(state_path):
            return SyncResult("info", f"lifecycle not synced: title {title_id} has no "
                                      f"lifecycle cursor ({paths.display(state_path)})")
        with open(state_path, encoding="utf-8") as handle:
            cursor = json.load(handle)

        relative = self._append(directory, record)
        entity = _RunBackedEntity(title_id, directory, cursor, run_artifacts)
        gate = record.get("gate_id")
        try:
            moved = self._advance(entity, record, relative, evidence)
        except (wgf_state().Refused, MachineError, WorkspaceError, KeyError,
                ValueError) as exc:
            return SyncResult("warning", f"lifecycle: {gate} recorded at "
                                         f"{relative} but title {title_id} was not moved: "
                                         f"{exc}", record_path=relative)
        return SyncResult("info", f"lifecycle: title {title_id} {moved} through {gate} "
                                  f"({relative})", record_path=relative, moved=moved)

    def _append(self, directory, record):
        """Write `record` as a new file under decisions/; never over an existing one."""
        folder = os.path.join(directory, "decisions")
        os.makedirs(folder, exist_ok=True)
        stem = f"{record.get('gate_id') or 'G0'}-{_stamp(record.get('decided_at'))}"
        payload = json.dumps(record, indent=2, ensure_ascii=False) + "\n"
        for number in range(1, 100):
            name = f"{stem}-{number:02d}.json"
            try:
                handle = os.open(os.path.join(folder, name),
                                 os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
            except FileExistsError:
                continue
            with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as out:
                out.write(payload)
                out.flush()
                os.fsync(out.fileno())
            return f"decisions/{name}"
        raise OSError(f"{folder}: no free name for {stem}")

    def _advance(self, entity, record, relative, evidence):
        cli = wgf_state()
        machine = load_machine(entity.machine)
        if record.get("machine") != machine.name:
            raise cli.Refused(f"the record is for the {record.get('machine')} machine; the "
                              f"cursor is a {machine.name}")
        source, _, target = (record.get("transition") or "").partition("->")
        source, target = source.strip(), target.strip()
        event = _EVENTS.get(record.get("decision"))
        if event is None:
            raise cli.Refused(f"decision {record.get('decision')!r} authorizes no edge")
        current = entity.state.get("current_state")
        if current != source:
            raise cli.Refused(f"the cursor is at {machine.name}:{current}, but the decision "
                              f"authorizes {source} -> {target}; move it there with "
                              f"wgf-state.py first")
        if machine.is_terminal(current):
            raise cli.Refused(f"{machine.name}:{current} is terminal; nothing leaves it")
        context = GuardContext(entity, config=self._portfolio_config(), evidence=evidence)
        transition = cli.choose_transition(machine, current, event, target, context)
        problems = cli.check_guards(transition, context)
        if problems:
            raise cli.Refused(f"{transition.label} is blocked: " + "; ".join(problems))
        if transition.gate:
            cli.check_decision_record(entity, transition, relative)
        updated = cli.advance(entity, machine, transition, relative, record.get("rationale"),
                              record.get("decided_at") or cli.now_iso())
        _atomic_write(entity.state_path, json.dumps(updated, indent=2, ensure_ascii=False)
                      + "\n")
        return f"{transition.source} -> {transition.target}"

    def _portfolio_config(self):
        if self._portfolio is None:
            try:
                self._portfolio = load_portfolio_config()
            except WorkspaceError:
                self._portfolio = {}
        return self._portfolio

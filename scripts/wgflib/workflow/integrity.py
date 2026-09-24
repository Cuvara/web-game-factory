"""Is a run's persisted state one this engine could have written? Checked before it is driven.

`state.json` is a file anyone with the run directory can edit. Nothing local can make that
impossible, and nothing here pretends to: there is no key, so a writer who rewrites
state.json, the artifact files and events.jsonl consistently is not detected. What this
does catch is every *inconsistent* edit - by hand, by a crashed tool, or by an agent that
found the file - before the engine acts on it:

  * shape: a status, cursor, counter or reference the engine never writes (an unknown
    status, a cursor naming no step, negative or non-integer visits, loop_base > visits);
  * artifact references: every version of an id is at its canonical location
    `artifacts/<id>/v<n>.json`, numbered 1..n in order, of one type. A ref whose location
    points at another version's file - replaying an old passing qa-report as the newest -
    is refused here, and a ref whose checksum does not match its file is refused when it is
    read (store.read_artifact);
  * lineage inside the run: every `outputs`/`consumed` entry of a step names a version
    state records, so deleting the newest (failing) report's ref to expose the passing one
    before it is refused;
  * decisions: each is a plain label for a visit the step has had. And a decision is only
    *used* when events.jsonl holds the DECISION_RECORDED event the engine emitted with it
    (`decision_on_record`), so a decision injected into state.json alone answers nothing:
    the checkpoint waits for a person again.

Problems are reported as strings; the engine refuses to resume or continue a run that has
any. Nothing here names a step type, a gate or a route.
"""

from .events import Events
from .model import RunStatus, StepStatus

__all__ = ["state_problems", "decision_on_record"]

_COUNTERS = ("attempts", "executions", "visits", "loop_base")
_DECISION_KEYS = ("decision", "decided_by", "decided_at", "visit", "note")


def _count(value):
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def state_problems(state, definition):
    """Every inconsistency between `state` and what the engine writes. [] when none."""
    # Imported here: engine imports this module, and check_decision lives in the engine.
    from .engine import EngineError, check_decision
    from .store import ARTIFACT_ID

    problems = []
    if state.status not in RunStatus.ALL:
        problems.append(f"status {state.status!r} is not a run status")
    if state.cursor is not None and not (isinstance(state.cursor, str)
                                         and definition.has_step(state.cursor)):
        problems.append(f"cursor {state.cursor!r} is not a step of workflow {definition.id}")
    if not isinstance(state.scope, list) or not all(isinstance(s, str) for s in state.scope):
        problems.append("scope is not a list of step ids")
    if not isinstance(state.params, dict):
        problems.append("params is not a mapping")

    for step_id, step in (state.steps or {}).items():
        where = f"steps.{step_id}"
        if step.status not in StepStatus.ALL:
            problems.append(f"{where}.status {step.status!r} is not a step status")
        for name in _COUNTERS:
            if not _count(getattr(step, name)):
                problems.append(f"{where}.{name} {getattr(step, name)!r} is not a count")
        if _count(step.visits) and _count(step.loop_base) and step.loop_base > step.visits:
            problems.append(f"{where}.loop_base {step.loop_base} exceeds its visits "
                            f"{step.visits}")
        for name in ("outputs", "consumed"):
            value = getattr(step, name)
            if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
                problems.append(f"{where}.{name} is not a list of references")

    seqs = []
    for artifact_id, versions in (state.artifacts or {}).items():
        where = f"artifacts.{artifact_id}"
        if not isinstance(artifact_id, str) or not ARTIFACT_ID.fullmatch(artifact_id):
            problems.append(f"{where}: {artifact_id!r} is not an artifact id")
            continue
        types = set()
        for index, ref in enumerate(versions, 1):
            if ref.id != artifact_id:
                problems.append(f"{where} v{index}: names artifact {ref.id!r}")
            if ref.version != index or isinstance(ref.version, bool):
                problems.append(f"{where}: version {ref.version!r} where {index} belongs")
            expected = f"artifacts/{artifact_id}/v{index}.json"
            if ref.location != expected:
                problems.append(f"{where} v{index}: location {ref.location!r} is not "
                                f"{expected}")
            if not isinstance(ref.checksum, str) or not ref.checksum.startswith("sha256:"):
                problems.append(f"{where} v{index}: checksum {ref.checksum!r} is not a digest")
            types.add(ref.type)
            if ref.seq is not None:
                seqs.append(ref.seq)
        if len(types) > 1:
            problems.append(f"{where}: versions of one artifact have different types "
                            f"({', '.join(sorted(map(str, types)))})")
    if len(seqs) != len(set(seqs)) or not all(_count(s) for s in seqs):
        problems.append("artifact seq numbers are not unique counts")

    # What a step produced or consumed is recorded in the same save as the refs; a
    # reference to a version state no longer holds is a ref deleted after the fact - the
    # shape of rolling a failed verification back to the passing one before it.
    recorded = {f"{ref.id}@v{ref.version}" for versions in (state.artifacts or {}).values()
                for ref in versions}
    for step_id, step in (state.steps or {}).items():
        for name in ("outputs", "consumed"):
            for reference in getattr(step, name) or []:
                if isinstance(reference, str) and reference not in recorded:
                    problems.append(f"steps.{step_id}.{name} names {reference}, which state "
                                    f"does not record")

    if not isinstance(state.decisions, dict):
        problems.append("decisions is not a mapping")
    else:
        for step_id, entry in state.decisions.items():
            where = f"decisions.{step_id}"
            if not isinstance(entry, dict):
                problems.append(f"{where} is not a decision")
                continue
            try:
                check_decision(entry.get("decision"), entry.get("decided_by"),
                               entry.get("note"))
            except EngineError as exc:
                problems.append(f"{where}: {exc}")
            step = (state.steps or {}).get(step_id)
            visit = entry.get("visit")
            if not _count(visit) or step is None or not _count(step.visits) \
                    or visit > step.visits:
                problems.append(f"{where}: visit {visit!r} is not a visit {step_id} has had")
    return problems


def decision_on_record(events, step_id, entry):
    """True when `events` hold the DECISION_RECORDED the engine emitted with `entry`."""
    wanted = {key: entry.get(key) for key in _DECISION_KEYS if entry.get(key) is not None}
    for event in events:
        if event.get("event") != Events.DECISION_RECORDED or event.get("step_id") != step_id:
            continue
        data = event.get("data") or {}
        recorded = {key: data.get(key) for key in _DECISION_KEYS if data.get(key) is not None}
        if recorded == wanted:
            return True
    return False

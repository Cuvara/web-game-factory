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

  * a wait's start: `waiting_since` on a step starts a checkpoint's timeout, so it is only
    *used* when events.jsonl holds the STEP_WAITING event that recorded it for that visit
    (`waiting_since`), and only while no step upstream of it has succeeded again since -
    backdating it in state.json alone approves nothing.

  * run params: `mock`, `mock_plan`, `auto_approve` and `timeout_auto_approve` decide which
    implementations run and which gates approve themselves, and they are read from
    state.json on every resume. The
    engine records the params in the WORKFLOW_STARTED event too, and `params_problems`
    refuses a state whose params differ from that record - so turning a real run into a
    mock one, or adding G3 to `auto_approve`, by editing state.json alone is refused. The
    same holds for every other param - `on_hung` and `hung_output_seconds`, the hung-child
    watchdog a run snapshots at start, among them - and their shape is checked here too.
    `lifecycle_sync` (factory.lifecycle.sync, snapshotted the same way) decides whether the
    run's gate decisions are written into workspace/titles, so it can be neither turned on
    nor off by an edit. `develop_budget` (factory.develop.budget, wgflib.budget) is the
    run's developer-session budget: raised only by a person's BUDGET_RAISED event, never by
    editing the snapshot.

  * route-scoped visits: `route_visits` / `route_base` are counts per route, a base never
    above its count, and together never more entries than `visits`; `blocked_reason` is
    None or the structured reason the engine writes.

Problems are reported as strings; the engine refuses to resume or continue a run that has
any. Nothing here names a step type, a gate or a route.
"""

from .. import budget
from .config import ON_HUNG
from .events import Events
from .model import RunStatus, StepOutcome, StepStatus, parse_timestamp

__all__ = ["state_problems", "params_problems", "decision_on_record", "GUARDED_PARAMS",
           "waiting_since"]

# The params whose value weakens what a run proves: a mock run's artifacts are placeholders,
# and an auto-approved gate was decided by nobody. A run created before the params were
# recorded in WORKFLOW_STARTED has nothing to corroborate them with, so it is refused while
# any of these is set (see params_problems).
# `lifecycle_sync` is here for the other direction: it lets a run write into workspace/, so
# it is never taken on the word of an edited state.json either.
GUARDED_PARAMS = ("mock", "mock_plan", "auto_approve", "timeout_auto_approve",
                  "lifecycle_sync")

_COUNTERS = ("attempts", "executions", "visits", "loop_base")
_DECISION_KEYS = ("decision", "decided_by", "decided_at", "visit", "note", "mode")


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
    else:
        windows = state.params.get("timeout_auto_approve")
        if windows is not None and not (
                isinstance(windows, dict)
                and all(isinstance(g, str) and _count(v) and v > 0 for g, v in windows.items())):
            problems.append("params.timeout_auto_approve is not a mapping of gate ids to "
                            "positive seconds")
        sync = state.params.get("lifecycle_sync")
        if sync is not None and sync is not True:
            problems.append(f"params.lifecycle_sync {sync!r} is not true (a run that does not "
                            f"sync records no lifecycle_sync at all)")
        on_hung = state.params.get("on_hung")
        if on_hung is not None and on_hung not in ON_HUNG:
            problems.append(f"params.on_hung {on_hung!r} is not one of {', '.join(ON_HUNG)}")
        output = state.params.get("hung_output_seconds")
        if output is not None and (isinstance(output, bool)
                                   or not isinstance(output, (int, float)) or output <= 0):
            problems.append(f"params.hung_output_seconds {output!r} is not a positive number "
                            f"of seconds")
        if on_hung == "cancel" and output is None:
            problems.append("params.on_hung is cancel without params.hung_output_seconds")
        if budget.PARAM in state.params:
            problems += budget.shape_problems(state.params[budget.PARAM],
                                              f"params.{budget.PARAM}")
    problems += _blocked_reason_problems(state, definition)

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
        if step.waiting_since is not None and parse_timestamp(step.waiting_since) is None:
            problems.append(f"{where}.waiting_since {step.waiting_since!r} is not a timestamp")
        problems += _route_problems(where, step)

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
                               entry.get("note"), entry.get("mode"))
            except EngineError as exc:
                problems.append(f"{where}: {exc}")
            step = (state.steps or {}).get(step_id)
            visit = entry.get("visit")
            if not _count(visit) or step is None or not _count(step.visits) \
                    or visit > step.visits:
                problems.append(f"{where}: visit {visit!r} is not a visit {step_id} has had")
    return problems


def _route_counts(value):
    return isinstance(value, dict) and all(
        isinstance(route, str) and route and _count(count) for route, count in value.items())


def _route_problems(where, step):
    problems = []
    visits, base = step.route_visits, step.route_base
    for name, value in (("route_visits", visits), ("route_base", base)):
        if not _route_counts(value):
            problems.append(f"{where}.{name} is not a mapping of routes to counts")
    if problems:
        return problems
    for route, count in base.items():
        if count > visits.get(route, 0):
            problems.append(f"{where}.route_base.{route} {count} exceeds its route_visits "
                            f"{visits.get(route, 0)}")
    if _count(step.visits) and sum(visits.values()) > step.visits:
        problems.append(f"{where}.route_visits count {sum(visits.values())} entries, more "
                        f"than its visits {step.visits}")
    if step.entered_by is not None and (not isinstance(step.entered_by, str)
                                        or step.entered_by not in visits):
        problems.append(f"{where}.entered_by {step.entered_by!r} is not a route it was "
                        f"entered through")
    return problems


def _blocked_reason_problems(state, definition):
    reason = state.blocked_reason
    if reason is None:
        return []
    if not isinstance(reason, dict) or not isinstance(reason.get("kind"), str):
        return ["blocked_reason is not a structured reason"]
    problems = []
    if state.status != RunStatus.BLOCKED:
        problems.append(f"blocked_reason is set on a run that is {state.status}")
    step_id = reason.get("step")
    if not (isinstance(step_id, str) and definition.has_step(step_id)):
        problems.append(f"blocked_reason.step {step_id!r} is not a step of workflow "
                        f"{definition.id}")
    elif step_id != state.cursor:
        problems.append(f"blocked_reason.step {step_id!r} is not the run's cursor")
    route = reason.get("route")
    if route is not None and not isinstance(route, str):
        problems.append(f"blocked_reason.route {route!r} is not a route")
    return problems


def params_problems(state, events):
    """Does state.json carry the params the run was started with? [] when it does.

    The first WORKFLOW_STARTED event records `data.params`; state.params must equal it. A
    run started before the params were recorded - no WORKFLOW_STARTED, or one without a
    `params` key - is legacy: accepted only while no GUARDED_PARAMS value is set, because
    such a value is exactly what an edit would add and nothing can vouch for it. Deleting
    `params` from the event to pass as legacy therefore gains nothing but a real, fully
    gated run.
    """
    params = state.params if isinstance(state.params, dict) else {}
    started = [e for e in events if e.get("event") == Events.WORKFLOW_STARTED]
    recorded = None
    if started:
        data = started[0].get("data")
        if isinstance(data, dict) and "params" in data:
            recorded = data["params"]
    if recorded is None:
        claimed = [key for key in GUARDED_PARAMS if params.get(key)]
        if not claimed:
            return []
        return [
            f"params {', '.join(claimed)} are set in state.json but the run's event log "
            f"has no WORKFLOW_STARTED record of its params to corroborate them (a run "
            f"created before params were recorded, or an edited state.json). Start a new "
            f"run; or, if you know this state.json is untouched, remove "
            f"{', '.join(claimed)} from its params to resume it as a real, fully gated run"]
    problems = []
    # A replayed log line repeats the event exactly and is harmless; a second start that
    # records other params is not.
    if any((e.get("data") or {}).get("params") != recorded for e in started[1:]
           if isinstance(e.get("data"), dict)):
        problems.append("events.jsonl holds WORKFLOW_STARTED events with different params")
    if not isinstance(recorded, dict):
        problems.append("WORKFLOW_STARTED records params that are not a mapping")
        return problems
    for key in sorted(set(params) | set(recorded)):
        if params.get(key) != recorded.get(key) or (key in params) != (key in recorded):
            problems.append(f"params.{key} is {params.get(key)!r} in state.json but the run "
                            f"was started with {recorded.get(key)!r}")
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


def _waiting_on_record(events, step_id, visit, since):
    for event in events:
        if event.get("event") != Events.STEP_WAITING or event.get("step_id") != step_id:
            continue
        data = event.get("data") or {}
        if data.get("waiting_since") == since and data.get("visit") == visit:
            return True
    return False


def waiting_since(state, definition, step_id, events):
    """When `step_id`'s current visit started waiting, if that can be relied on; else None.

    The engine records `waiting_since` in state and in the STEP_WAITING event of the same
    visit. It is None here when state holds none, when no such event corroborates it (an
    edit of state.json), or when a step before `step_id` in the definition has succeeded
    since: whatever the wait was for has been replaced, so the wait starts again. Pure: the
    engine and `wgf status` both ask it, so a resume and a status never disagree on it.
    """
    step = (state.steps or {}).get(step_id)
    since = getattr(step, "waiting_since", None)
    moment = parse_timestamp(since)
    if moment is None or not _waiting_on_record(events, step_id, step.visits, since):
        return None
    # The trail entry of the execution that began the wait (the engine takes waiting_since
    # from its `at`); order in the trail, not timestamps, says what happened after it.
    trail = state.trail or []
    began = next((i for i, entry in enumerate(trail)
                  if entry.get("step") == step_id and entry.get("visit") == step.visits
                  and entry.get("outcome") in StepOutcome.WAITING
                  and entry.get("at") == since), None)
    if began is None:
        return None
    ids = list(definition.step_ids) if definition is not None else []
    upstream = set(ids[:ids.index(step_id)]) if step_id in ids else set()
    if any(entry.get("step") in upstream and entry.get("outcome") == StepOutcome.SUCCESS
           for entry in trail[began + 1:]):
        return None
    return since

"""A run's budget for developer agent sessions: `factory.develop.budget`, as a run holds it.

Loop limits bound how often work may go round; they reset whenever a person resumes. This
bounds what a whole run may spend on unattended developer sessions, and nothing resets it:

    factory:
      develop:
        budget:
          max_sessions: 12          # developer sessions (command developer executions) per run
          max_cost: 60              # summed cost the sessions reported, in the unit they report
          cost_from:
            jsonl_key: <key>        # the number to read from the last JSON line holding it

Every key is optional, and no `budget` at all is no budget - the behaviour before it
existed. The installation's value is snapshotted into the run's params when the run starts
(`develop_budget`, recorded in WORKFLOW_STARTED like every param, so an edit of state.json
is refused on resume); a later config change does not reach a running run.

Raising a budget is a person's act, recorded as a BUDGET_RAISED event (`wgf resume <run>
--budget-sessions N | --budget-cost X`), never an edit. The effective limit is the largest of
the snapshot and every raise a person recorded; a raise recorded by automation - an agent
inside the run's own process tree - counts for nothing. Nor does a raise the engine's own
resume record does not corroborate: the engine writes each raise with a `resume_nonce` and
the WORKFLOW_RESUMED right after it with the same one, so a BUDGET_RAISED line appended to
events.jsonl by anything else is ignored. A developer session that edits the event log is
caught by the develop step (wgf_develop/budget.py), which records the raises it forged
(`TAMPERED`) so they never count either. The log has no hash chain; the run directory being
outside every agent's checkout and write scope is the containment.

This module is shared plumbing: config.py validates with it, api.py snapshots and raises
with it, integrity.py checks the snapshot's shape with it, and wgf_develop enforces it. It
names no provider: which key holds a session's cost is installation config.
"""

import re

__all__ = ["PARAM", "RAISED_EVENT", "RESUMED_EVENT", "TAMPERED", "LIMITS", "BudgetError",
           "parse", "shape_problems", "effective", "check_raise", "forged_raises"]

# The run param the snapshot is recorded under, and the event a person's raise is.
PARAM = "develop_budget"
RAISED_EVENT = "BUDGET_RAISED"
RESUMED_EVENT = "WORKFLOW_RESUMED"
# The STEP_LOG `budget` marker the develop step records when a session edited the event
# log: `data.forged` lists the resume nonces of the raises it wrote, never honoured.
TAMPERED = "event-log-tampered"
LIMITS = ("max_sessions", "max_cost")
_KEYS = LIMITS + ("cost_from",)
_JSONL_KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_.-]{0,63}")


class BudgetError(ValueError):
    """A budget value wgf will not act on."""


def _is_count(value):
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _is_amount(value):
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and value > 0 and value == value and value != float("inf"))


def shape_problems(value, where="develop_budget"):
    """Every way `value` is not a budget this module writes. [] when it is one."""
    if not isinstance(value, dict):
        return [f"{where} is not a mapping"]
    problems = []
    unknown = sorted(set(value) - set(_KEYS))
    if unknown:
        problems.append(f"{where} has unknown key(s) {', '.join(map(str, unknown))}")
    if "max_sessions" in value and not _is_count(value["max_sessions"]):
        problems.append(f"{where}.max_sessions {value['max_sessions']!r} is not a positive "
                        f"whole number")
    if "max_cost" in value and not _is_amount(value["max_cost"]):
        problems.append(f"{where}.max_cost {value['max_cost']!r} is not a positive number")
    if "cost_from" in value:
        source = value["cost_from"]
        if (not isinstance(source, dict) or set(source) != {"jsonl_key"}
                or not isinstance(source.get("jsonl_key"), str)
                or not _JSONL_KEY.fullmatch(source["jsonl_key"])):
            problems.append(f"{where}.cost_from must be {{jsonl_key: <key>}}, a plain JSON "
                            f"key")
    if "max_cost" in value and "cost_from" not in value:
        problems.append(f"{where}.max_cost needs cost_from: without it no session's cost is "
                        f"ever read, and the limit could never be reached")
    return problems


def parse(raw):
    """factory.develop.budget as the snapshot a run records, or None for no budget.
    Fail closed: anything that is not a budget raises BudgetError."""
    if raw is None or raw == {}:
        return None
    problems = shape_problems(raw, "factory.develop.budget")
    if problems:
        raise BudgetError("; ".join(problems))
    return {key: (dict(raw[key]) if key == "cost_from" else raw[key])
            for key in _KEYS if key in raw}


def check_raise(snapshot, max_sessions=None, max_cost=None):
    """The BUDGET_RAISED data for a raise, or BudgetError. A raise names a limit the run
    has (there is nothing to raise in a run started without one) with a positive value."""
    if max_sessions is None and max_cost is None:
        raise BudgetError("a budget raise names --budget-sessions or --budget-cost")
    data = {}
    for name, value, valid in (("max_sessions", max_sessions, _is_count),
                               ("max_cost", max_cost, _is_amount)):
        if value is None:
            continue
        if not valid(value):
            raise BudgetError(f"{name} {value!r} is not a positive "
                              f"{'whole number' if name == 'max_sessions' else 'number'}")
        if not isinstance(snapshot, dict) or name not in snapshot:
            raise BudgetError(f"this run was started without a {name} budget "
                              f"(factory.develop.budget.{name}); there is nothing to raise")
        data[name] = value
    return data


def effective(params, events):
    """{"max_sessions", "max_cost", "cost_from", "raises"} in force for a run: the snapshot
    in its params, raised by every BUDGET_RAISED event a person recorded. A limit only ever
    goes up: a raise below the snapshot changes nothing. None when the run has no budget."""
    snapshot = (params or {}).get(PARAM) if isinstance(params, dict) else None
    if not isinstance(snapshot, dict) or shape_problems(snapshot):
        return None
    limits = {name: snapshot.get(name) for name in LIMITS}
    raises = []
    events = [e for e in events or () if isinstance(e, dict)]
    forged = set()
    for event in events:
        data = event.get("data")
        if (event.get("event") == "STEP_LOG" and isinstance(data, dict)
                and data.get("budget") == TAMPERED and isinstance(data.get("forged"), list)):
            forged |= {n for n in data["forged"] if isinstance(n, str)}
    for index, event in enumerate(events):
        if event.get("event") != RAISED_EVENT:
            continue
        data = event.get("data") or {}
        if not isinstance(data, dict) or data.get("decided_by") in (None, "automation"):
            continue  # an agent does not raise its own budget
        if not _corroborated(events, index, data.get("resume_nonce")) \
                or data.get("resume_nonce") in forged:
            continue  # not written by a person's resume
        applied = {}
        for name, valid in (("max_sessions", _is_count), ("max_cost", _is_amount)):
            value = data.get(name)
            if limits[name] is not None and valid(value):
                applied[name] = value
                limits[name] = max(limits[name], value)
        if applied:
            raises.append(dict(applied, decided_by=data.get("decided_by"),
                               decided_at=data.get("decided_at")))
    return dict(limits, cost_from=snapshot.get("cost_from"), raises=raises)


def _corroborated(events, index, nonce):
    """Whether the raise at `events[index]` is part of an engine-recorded resume: the next
    event that is not another operator event of the same resume is WORKFLOW_RESUMED with
    the same `resume_nonce`."""
    if not isinstance(nonce, str) or not nonce:
        return False
    for event in events[index + 1:]:
        data = event.get("data") if isinstance(event.get("data"), dict) else {}
        if event.get("event") == RESUMED_EVENT:
            return data.get("resume_nonce") == nonce
        if data.get("resume_nonce") != nonce:
            return False
    return False


def forged_raises(before, after):
    """Problems, and the forged raises' nonces, when the event log `after` a developer
    session is not `before` plus lines the Factory itself writes during a step: an edited
    or truncated prefix, or an appended BUDGET_RAISED / WORKFLOW_RESUMED (a resume cannot
    happen while the step holds the run). ([], set()) when the log is intact."""
    before, after = list(before or ()), list(after or ())
    problems, nonces = [], set()
    if after[:len(before)] != before:
        problems.append("events recorded before the session were changed or removed")
    for event in after[len(before):]:
        if not isinstance(event, dict):
            continue
        name = event.get("event")
        if name in (RAISED_EVENT, RESUMED_EVENT):
            problems.append(f"a {name} event was appended while the step ran")
            nonce = (event.get("data") or {}).get("resume_nonce") \
                if isinstance(event.get("data"), dict) else None
            if isinstance(nonce, str):
                nonces.add(nonce)
    return problems, nonces

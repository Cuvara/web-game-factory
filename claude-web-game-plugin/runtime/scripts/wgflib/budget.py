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

Every key is optional. The installation's value is snapshotted into the run's params when
the run starts (`develop_budget`, recorded in WORKFLOW_STARTED like every param, so an edit
of state.json is refused on resume); a later change to a budget the run has does not reach
it.

A run started with no budget at all - the shipped, supervised config, whose developer is a
person - is not left without one when its project later configures a paid one (the
autonomous profile copied in mid-run): the first resume by a person that finds
`factory.develop.budget` set records it as a BUDGET_ADOPTED operator event, corroborated
like a raise, and from then on it is the run's budget exactly as a snapshot would be. The
develop step never starts a command developer while the run has no budget (wgf_develop).

Raising a budget is a person's act, recorded as a BUDGET_RAISED event (`wgf resume <run>
--budget-sessions N | --budget-cost X`), never an edit. The effective limit is the largest of
the snapshot and every raise a person recorded; a raise recorded by automation - an agent
inside the run's own process tree - counts for nothing. The engine writes each raise with a
`resume_nonce` and the WORKFLOW_RESUMED right after it with the same one; a raise counts only
when that resume corroborates it, so a lone BUDGET_RAISED line counts for nothing.

What keeps a whole forged pair - or a truncated log that forgets sessions - out: while a
drive holds the run, the engine is the log's only writer, and after every step it puts back
anything another process wrote there (RunStore.seal_events, EVENT_LOG_RESTORED) and fails
that step. That covers every step that runs a developer's or an agent's code - develop and
its checks, review, sdk, verify, release. *Residual:* the log has no hash chain or secret. A
process that edits the run directory while no driver holds the run - one that escaped its
step's process tree - is outside this; the run directory lying outside every agent's
checkout and write scope, and an OS sandbox around the developer, are the containment.

This module is shared plumbing: config.py validates with it, api.py snapshots and raises
with it, integrity.py checks the snapshot's shape with it, and wgf_develop enforces it. It
names no provider: which key holds a session's cost is installation config.
"""

import re

__all__ = ["PARAM", "RAISED_EVENT", "ADOPTED_EVENT", "RESUMED_EVENT", "LIMITS",
           "BudgetError", "parse", "shape_problems", "base", "adopted", "effective",
           "check_raise"]

# The run param the snapshot is recorded under, the event a person's raise is, and the event
# a resume records when a run started without a budget takes the one now configured.
PARAM = "develop_budget"
RAISED_EVENT = "BUDGET_RAISED"
ADOPTED_EVENT = "BUDGET_ADOPTED"
RESUMED_EVENT = "WORKFLOW_RESUMED"
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
        if not isinstance(snapshot, dict):
            raise BudgetError("this run has no budget (factory.develop.budget); set one in "
                              "the project's config and resume - the resume adopts it")
        if name not in snapshot:
            raise BudgetError(f"this run was started without a {name} budget "
                              f"(factory.develop.budget.{name}); there is nothing to raise")
        data[name] = value
    return data


def _by_a_person(events, index):
    """The data of `events[index]` when a person's resume recorded it, else None: an agent
    does not set its own budget, and a lone line appended to the log is no one's act."""
    data = events[index].get("data") or {}
    if not isinstance(data, dict) or data.get("decided_by") in (None, "automation"):
        return None
    if not _corroborated(events, index, data.get("resume_nonce")):
        return None
    return data


def adopted(events):
    """The budget the first BUDGET_ADOPTED event a person's resume recorded carries, or
    None. Only the first counts: a run takes a budget once, and a person changes it after
    that only by a raise."""
    events = [e for e in events or () if isinstance(e, dict)]
    for index, event in enumerate(events):
        if event.get("event") != ADOPTED_EVENT:
            continue
        data = _by_a_person(events, index)
        value = (data or {}).get("budget")
        if isinstance(value, dict) and value and not shape_problems(value):
            return value
    return None


def base(params, events):
    """The budget a run holds before any raise: the snapshot in its params, else the one a
    person's resume adopted for it, else None."""
    snapshot = (params or {}).get(PARAM) if isinstance(params, dict) else None
    if snapshot is not None:
        return snapshot if isinstance(snapshot, dict) and not shape_problems(snapshot) else None
    return adopted(events)


def effective(params, events):
    """{"max_sessions", "max_cost", "cost_from", "raises", "source"} in force for a run: the
    snapshot in its params (or the budget a resume adopted, `source` "adopted"), raised by
    every BUDGET_RAISED event a person recorded. A limit only ever goes up: a raise below
    the snapshot changes nothing. None when the run has no budget."""
    events = [e for e in events or () if isinstance(e, dict)]
    snapshot = base(params, events)
    if snapshot is None:
        return None
    has_snapshot = isinstance(params, dict) and params.get(PARAM) is not None
    limits = {name: snapshot.get(name) for name in LIMITS}
    raises = []
    for index, event in enumerate(events):
        if event.get("event") != RAISED_EVENT:
            continue
        data = _by_a_person(events, index)
        if data is None:
            continue  # an agent's, or not written by a person's resume
        applied = {}
        for name, valid in (("max_sessions", _is_count), ("max_cost", _is_amount)):
            value = data.get(name)
            if limits[name] is not None and valid(value):
                applied[name] = value
                limits[name] = max(limits[name], value)
        if applied:
            raises.append(dict(applied, decided_by=data.get("decided_by"),
                               decided_at=data.get("decided_at")))
    return dict(limits, cost_from=snapshot.get("cost_from"), raises=raises,
                source="snapshot" if has_snapshot else "adopted")


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


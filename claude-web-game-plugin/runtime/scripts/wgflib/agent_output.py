"""What an agent session printed: its text, and the usage it reported - one reader for every
agent step.

Why this is shared plumbing (a core change, stated): until now only developer sessions were
metered (wgf_develop.budget reads a stream-json transcript). Every other agent - the design
author, the reviewer, the asset and model authors, the judges, the copywriter - ran with plain
text output, because their consumers parse the reply from stdout ("the last JSON object
printed", an SVG, a draft) and a JSON envelope around that reply would have failed them as
malformed. So their cost was never recorded and a game's cost was an estimate
(docs/monetization/p0-execution-plan.md, P0-05).

`read(stdout)` accepts all three shapes an agent host prints:

    text          the reply itself                       -> text as printed, usage None
    json          one result object at exit              -> its reply text, its usage
    stream-json   one JSON object per line, ending with  -> the result line's reply, usage
                  the result object

A result object is a JSON object with `"type": "result"`; its reply is the string under
`result`, its cost the number under `total_cost_usd`. A reply that is not a string, or output
that holds no result object, leaves the text exactly as printed: a consumer that worked on
plain text keeps working on it, byte for byte.

`note(logger, role, output)` records one session as a STEP_LOG event (`budget: agent-cost`)
in the run's event log - the same append-only log the developer budget is counted from, so a
resume or a crash never forgets a session. A session whose host reported no cost (text
output, a killed process, a host without the field) is recorded with `cost: null` and
`known: false`: counted as a session, never guessed. `summarize(events)` reads the log back:
sessions and known cost per role, developer sessions included, nothing counted twice.
"""

import json
import math

__all__ = ["AgentOutput", "read", "note", "summarize", "AGENT_COST", "RESULT_TYPE",
           "REPLY_KEY", "COST_KEY"]

AGENT_COST = "agent-cost"
DEVELOPER_SESSION = "developer-session"
DEVELOPER_COST = "developer-cost"

RESULT_TYPE = "result"
REPLY_KEY = "result"
COST_KEY = "total_cost_usd"


class AgentOutput:
    """`text`: the reply a consumer parses. `usage`: what the host reported, or None.
    `structured`: whether a result object was found."""

    __slots__ = ("text", "usage", "structured")

    def __init__(self, text, usage=None, structured=False):
        self.text = text
        self.usage = usage
        self.structured = structured

    @property
    def cost(self):
        return (self.usage or {}).get("cost")

    def __repr__(self):
        return f"AgentOutput(structured={self.structured}, usage={self.usage!r})"


def _amount(value):
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and value >= 0)


def _result_object(text):
    """The host's result object in `text`, or None: the whole output when it is one JSON
    object, else the last line that is one - whatever was printed before it (a wrapper's
    progress line, a stream's earlier events)."""
    stripped = text.strip()
    if stripped.startswith("{"):
        try:
            whole = json.loads(stripped)
        except ValueError:
            whole = None
        if isinstance(whole, dict):
            return whole if whole.get("type") == RESULT_TYPE else None
    for line in reversed(stripped.splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if isinstance(record, dict) and record.get("type") == RESULT_TYPE:
            return record
    return None


def _usage(record):
    usage = {"cost": record[COST_KEY] if _amount(record.get(COST_KEY)) else None}
    for key in ("duration_ms", "num_turns"):
        if _amount(record.get(key)):
            usage[key] = record[key]
    models = record.get("modelUsage")
    if isinstance(models, dict) and models:
        usage["models"] = sorted(str(name) for name in models)
    if record.get("is_error") is True:
        usage["is_error"] = True
    return usage


def read(stdout):
    """The reply and the usage in what an agent printed (see the module docstring)."""
    text = stdout if isinstance(stdout, str) else ""
    record = _result_object(text)
    if record is None:
        return AgentOutput(text)
    reply = record.get(REPLY_KEY)
    return AgentOutput(reply if isinstance(reply, str) else text, _usage(record), True)


def note(logger, role, output, **fields):
    """Record one agent session in the run's event log. No logger, nothing recorded."""
    if logger is None:
        return None
    usage = (output.usage if isinstance(output, AgentOutput) else None) or {}
    cost = usage.get("cost")
    known = _amount(cost)
    logger.info("agent session cost" if known else "agent session cost unknown",
                budget=AGENT_COST, role=str(role), cost=cost if known else None,
                known=known, structured=bool(getattr(output, "structured", False)),
                duration_ms=usage.get("duration_ms"), num_turns=usage.get("num_turns"),
                models=usage.get("models"), **fields)
    return cost if known else None


def summarize(events):
    """Sessions and recorded cost per role from a run's events.

    {"total_cost", "sessions", "unknown_cost_sessions", "by_role": {role: {sessions, cost,
    unknown}}}. A developer session counts once, from its `developer-session` event; its
    `developer-cost` event adds the cost (or an unknown) without adding a session. A cost that
    is not a non-negative finite number lowers nothing and counts as unknown."""
    roles = {}

    def slot(role):
        return roles.setdefault(role, {"sessions": 0, "cost": 0.0, "unknown": 0})

    for event in events or ():
        if not isinstance(event, dict) or event.get("event") != "STEP_LOG":
            continue
        data = event.get("data")
        if not isinstance(data, dict):
            continue
        kind = data.get("budget")
        if kind == DEVELOPER_SESSION:
            slot("developer")["sessions"] += 1
        elif kind in (DEVELOPER_COST, AGENT_COST):
            entry = slot("developer" if kind == DEVELOPER_COST else str(data.get("role")))
            if kind == AGENT_COST:
                entry["sessions"] += 1
            if _amount(data.get("cost")):
                entry["cost"] += data["cost"]
            else:
                entry["unknown"] += 1
    for entry in roles.values():
        entry["cost"] = round(entry["cost"], 6)
    return {"total_cost": round(sum(e["cost"] for e in roles.values()), 6),
            "sessions": sum(e["sessions"] for e in roles.values()),
            "unknown_cost_sessions": sum(e["unknown"] for e in roles.values()),
            "by_role": dict(sorted(roles.items()))}

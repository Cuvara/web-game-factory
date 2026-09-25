"""The run's developer-session budget, enforced before every command developer session.

A `command` developer is a paid agent session per attempt; loop limits bound the passes
before a person looks, and a person resuming refills them. This bounds the run: `factory.develop.budget`
(wgflib.budget), snapshotted into the run's params when it started, raised only by a
person's BUDGET_RAISED event.

Everything is counted from the run's event log, never from memory or state.json, so neither
a resume nor a crash gives a session back:

    STEP_LOG  data.budget = "developer-session"   emitted - and read back from events.jsonl -
                                                  before the developer is spawned; a session
                                                  that cannot be recorded is not started
    STEP_LOG  data.budget = "event-log-tampered"  after it, when the session edited the log:
                                                  the step fails, and the raises it forged
                                                  (data.forged) never count
    STEP_LOG  data.budget = "developer-cost"      after it, when `cost_from` is configured:
                                                  the cost it reported, or null (unknown)

A session's cost is the number under `cost_from.jsonl_key` in the LAST JSON object line of
its transcript (`<run_dir>/develop/<visit>-<attempt>.log`) that holds that key, read only
from what this session appended. A session with no readable cost (killed, timed out, a host
that does not report one) is counted as a session and reported as unknown, never guessed,
and never a failure: the agent host's own per-session flag remains the bound on a single
session's spend. Handoff developers are people, not sessions: nothing is counted for them.
"""

import json
import os
import secrets

from wgflib import budget as run_budget

__all__ = ["Budget", "SESSION", "COST", "read_cost", "transcript_path"]

SESSION = "developer-session"
COST = "developer-cost"


def transcript_path(context):
    """Where the command developer's transcript for this execution goes, or None."""
    run_dir = getattr(context, "run_dir", None)
    if not run_dir:
        return None
    return os.path.join(run_dir, "develop", f"{context.visit}-{context.attempt}.log")


def _size(path):
    try:
        return os.path.getsize(path) if path else 0
    except OSError:
        return 0


def read_cost(path, key, offset=0):
    """The number under `key` in the last JSON object line of `path` past `offset` that
    holds it, or None. Lines may carry the transcript's `[stdout] ` / `[stderr] ` prefix."""
    if not path or not key:
        return None
    try:
        with open(path, "rb") as handle:
            handle.seek(offset)
            text = handle.read().decode("utf-8", errors="replace")
    except OSError:
        return None
    found = None
    for line in text.splitlines():
        line = line.strip()
        for prefix in ("[stdout] ", "[stderr] "):
            if line.startswith(prefix):
                line = line[len(prefix):].strip()
                break
        if not line.startswith("{"):
            continue
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if not isinstance(record, dict) or key not in record:
            continue
        value = record[key]
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0 \
                and value == value and value != float("inf"):
            found = value
        else:
            found = None  # the last line holding the key says what the session reported
    return found


class Budget:
    """The budget in force for this execution, and what the run has spent of it."""

    def __init__(self, limits, events):
        self.limits = limits  # wgflib.budget.effective(), or None: no budget
        self.sessions = 0
        self.cost = 0.0
        self.unknown = 0
        for event in events:
            data = event.get("data") if event.get("event") == "STEP_LOG" else None
            if not isinstance(data, dict):
                continue
            if data.get("budget") == SESSION:
                self.sessions += 1
            elif data.get("budget") == COST:
                value = data.get("cost")
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    self.cost += value
                else:
                    self.unknown += 1

    @classmethod
    def load(cls, context):
        """From the run's params (the snapshot) and its events (sessions, costs, raises)."""
        params = getattr(context, "environment", None) or {}
        reader = getattr(context, "read_events", None)
        events = list(reader()) if callable(reader) else []
        return cls(run_budget.effective(params if isinstance(params, dict) else {}, events),
                   events)

    @property
    def active(self):
        return bool(self.limits) and any(self.limits.get(n) is not None
                                         for n in run_budget.LIMITS)

    @property
    def cost_key(self):
        source = (self.limits or {}).get("cost_from") or {}
        return source.get("jsonl_key")

    def exhausted(self, run_id):
        """The BLOCKED message when another session would exceed the budget, else None."""
        if not self.active:
            return None
        max_sessions = self.limits.get("max_sessions")
        how = (f" A person raises it with: wgf resume {run_id} --budget-sessions N"
               f" (or --budget-cost X); an agent cannot.")
        if max_sessions is not None and self.sessions >= max_sessions:
            return (f"budget exhausted: {self.sessions} developer sessions used of "
                    f"{max_sessions} (factory.develop.budget.max_sessions"
                    f"{', raised' if self.limits.get('raises') else ''}). No agent was "
                    f"started.{how}")
        max_cost = self.limits.get("max_cost")
        if max_cost is not None and self.cost >= max_cost:
            unknown = (f"; {self.unknown} session(s) reported no readable cost and are not "
                       f"in that sum" if self.unknown else "")
            return (f"budget exhausted: developer cost {self.cost:g} recorded of {max_cost:g} "
                    f"(factory.develop.budget.max_cost) over {self.sessions} session(s)"
                    f"{unknown}. No agent was started.{how}")
        return None

    def summary(self):
        limits = self.limits or {}
        return {"sessions": self.sessions, "max_sessions": limits.get("max_sessions"),
                "cost": round(self.cost, 6), "max_cost": limits.get("max_cost"),
                "unknown_cost_sessions": self.unknown}

    def begin(self, context):
        """Record the session about to start, durably, before it is spawned.

        Returns (record, problem): `record` to hand to `finish`, or a BLOCKED `problem`
        when the session could not be shown to be on record (the event log could not be
        written or read back) - a session nobody can count is not started."""
        path = transcript_path(context)
        record = {"nonce": secrets.token_hex(8), "session": self.sessions + 1,
                  "transcript": path, "offset": _size(path)}
        context.logger.info(
            "developer session", budget=SESSION, session=record["session"],
            visit=context.visit, attempt=context.attempt, nonce=record["nonce"],
            max_sessions=(self.limits or {}).get("max_sessions"))
        if self.active:
            reader = getattr(context, "read_events", None)
            events = list(reader()) if callable(reader) else []
            record["events"] = events  # what `audit` compares the log against afterwards
            if not any(((e.get("data") or {}).get("nonce") == record["nonce"]
                        and (e.get("data") or {}).get("budget") == SESSION) for e in events):
                return record, (
                    "the developer session could not be recorded in the run's event log, so "
                    "it could not be counted against the run's budget; no agent was started. "
                    "Check that the run directory is writable, then resume.")
        return record, None

    def audit(self, context, record):
        """A FAILED message when the event log was edited while the session ran - its
        earlier lines changed, or a budget raise or resume appended - else None. The raises
        such an edit wrote are recorded as forged, so no later visit honours them either."""
        before = record.get("events")
        reader = getattr(context, "read_events", None)
        if before is None or not callable(reader):
            return None
        problems, forged = run_budget.forged_raises(before, list(reader()))
        if not problems:
            return None
        context.logger.error("run event log edited during a developer session",
                             budget=run_budget.TAMPERED, forged=sorted(forged),
                             session=record["session"], problems=problems)
        return ("the run's event log was edited while the developer session ran ("
                + "; ".join(problems) + "). The run's budget cannot be trusted from it; any "
                "raise it wrote is recorded as forged and ignored. A person should inspect "
                "the run before resuming it.")

    def finish(self, context, record):
        """Record what the session cost, when the installation says where to read it."""
        key = self.cost_key
        if not key:
            return None
        cost = read_cost(record["transcript"], key, record["offset"])
        context.logger.info(
            "developer session cost" if cost is not None else
            "developer session cost unknown", budget=COST, session=record["session"],
            nonce=record["nonce"], cost=cost, key=key, known=cost is not None,
            transcript=record["transcript"])
        if cost is None:
            context.logger.warning(
                "developer session reported no readable cost; counted as a session, not in "
                "the cost total (the agent host's own per-session limit is the bound here)",
                session=record["session"], key=key, transcript=record["transcript"])
        return cost

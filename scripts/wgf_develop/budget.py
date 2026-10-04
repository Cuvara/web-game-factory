"""The run's developer-session budget, enforced before every command developer session.

A `command` developer is a paid agent session per attempt; loop limits bound the passes
before a person looks, and a person resuming refills them. This bounds the run:
`factory.develop.budget` (wgflib.budget), snapshotted into the run's params when it started
(or adopted by a person's resume, BUDGET_ADOPTED, when it started with none), raised only by
a person's BUDGET_RAISED event. A run with no budget never starts a command developer
(`missing`): an unattended paid agent with no bound is what this exists to prevent.

The budget is derived from the plan, and the installation caps it. The approved tech plan
records what its own tasks need (tech-plan 1.1.0 `dev_plan.develop_budget`: sessions and cost
from the hours of every task the run's quality tier builds before G4, wgf_techplan.budget);
the limit in force is the lower of that and the run's `factory.develop.budget`, raised by a
person's BUDGET_RAISED above either. A cap below the plan's need was reported at G3 as a
planned shortfall. A run whose tech plan records no budget (tech-plan 1.0.0, or no tech plan)
is held to the configured budget alone, as before. A run with no configured budget still never
starts a command developer: the plan says what the build needs, the installation's budget is
its consent to spend.

Running out is never success: develop returns BLOCKED naming what the plan needed, and that
the run's quality tier is not achieved within the budget.

Everything is counted from the run's event log, never from memory or state.json, so neither
a resume nor a crash gives a session back:

    STEP_LOG  data.budget = "developer-session"   emitted - and read back from events.jsonl -
                                                  before the developer is spawned; a session
                                                  that cannot be recorded is not started
    STEP_LOG  data.budget = "developer-cost"      after it, when `cost_from` is configured:
                                                  the cost it reported, or null (unknown)

A session's cost is the number under `cost_from.jsonl_key` in the LAST JSON object line of
its transcript (`<run_dir>/<step>/<visit>-<attempt>.log`, `<step>` being `develop` or
`greybox`) that holds that key, read only from what this session appended. A session with
no readable cost (killed, timed out, a host that does not report one) is counted as a
session and reported as unknown, never guessed, and never a failure: the agent host's own
per-session flag remains the bound on a single session's spend. Handoff developers are
people, not sessions: nothing is counted for them.

The log is the engine's to keep: while it drives the run, anything another process writes to
events.jsonl - a forged raise, a "refund" cost line, a truncation - is put back after the
step that ran it, and the step fails (wgflib.workflow.store, seal_events). A recorded cost
that is not a non-negative finite number lowers nothing.
"""

import json
import os
import secrets

from wgflib import budget as run_budget

__all__ = ["Budget", "SESSION", "COST", "read_cost", "transcript_path", "with_plan"]

SESSION = "developer-session"
COST = "developer-cost"


def transcript_path(context):
    """Where the command developer's transcript for this execution goes, or None."""
    run_dir = getattr(context, "run_dir", None)
    if not run_dir:
        return None
    # Keyed by step: a workflow runs develop as more than one step (greybox, develop), and
    # each step's visits count from 1 - one directory would interleave their transcripts.
    step = getattr(context, "current_step", None) or "develop"
    return os.path.join(run_dir, step, f"{context.visit}-{context.attempt}.log")


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


def _planned(tech_plan):
    """The tech plan's derived develop budget, or None (tech-plan 1.0.0, or no tech plan)."""
    plan = ((tech_plan or {}).get("dev_plan") or {})
    planned = plan.get("develop_budget")
    if not isinstance(planned, dict):
        return None
    scope = plan.get("build_scope") if isinstance(plan.get("build_scope"), dict) else {}
    return dict(planned, quality_tier=scope.get("quality_tier"))


def _count(value):
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _amount(value):
    return (isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0
            and value == value and value != float("inf"))


def with_plan(limits, snapshot, planned):
    """`limits` (wgflib.budget.effective) with the plan's need applied: each limit is the lower
    of the installation's snapshot and the plan's, then raised by every raise a person
    recorded. A limit the installation does not set is the plan's - except max_cost, which
    is only applied when the installation says where a session's cost is read."""
    if not limits or not planned:
        return limits
    limits = dict(limits)
    snapshot = snapshot or {}
    for name, key, valid in (("max_sessions", "sessions", _count),
                             ("max_cost", "cost", _amount)):
        need = planned.get(key)
        if not valid(need):
            continue
        if name == "max_cost" and not limits.get("cost_from"):
            continue
        configured = snapshot.get(name)
        capped = need if configured is None else min(configured, need)
        raised = [r[name] for r in limits.get("raises") or [] if r.get(name) is not None]
        limits[name] = max([capped] + raised)
    limits["planned"] = {"sessions": planned.get("sessions"), "cost": planned.get("cost"),
                         "quality_tier": planned.get("quality_tier"),
                         "shortfall": planned.get("shortfall")}
    return limits


class Budget:
    """The budget in force for this execution, and what the run has spent of it."""

    def __init__(self, limits, events):
        self.limits = limits  # wgflib.budget.effective() with the plan's need, or None
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
                # A cost is a non-negative, finite number (read_cost reports nothing else).
                # Anything else - a negative "refund" above all - lowers nothing.
                if (isinstance(value, (int, float)) and not isinstance(value, bool)
                        and value >= 0 and value == value and value != float("inf")):
                    self.cost += value
                else:
                    self.unknown += 1

    @classmethod
    def load(cls, context, tech_plan=None):
        """From the run's params (the snapshot), its events (sessions, costs, raises) and the
        approved tech plan's derived need."""
        params = getattr(context, "environment", None) or {}
        params = params if isinstance(params, dict) else {}
        reader = getattr(context, "read_events", None)
        events = list(reader()) if callable(reader) else []
        limits = run_budget.effective(params, events)
        return cls(with_plan(limits, run_budget.base(params, events), _planned(tech_plan)),
                   events)

    @property
    def active(self):
        return bool(self.limits) and any(self.limits.get(n) is not None
                                         for n in run_budget.LIMITS)

    @property
    def cost_key(self):
        source = (self.limits or {}).get("cost_from") or {}
        return source.get("jsonl_key")

    def missing(self, run_id):
        """The BLOCKED message when the run has no budget at all, else None. Asked only for
        a command developer: a handoff developer is a person, and costs no session."""
        if self.active:
            return None
        return ("no developer-session budget: this run has none, so no command developer "
                "(a paid, unattended agent session) is started. Set factory.develop.budget "
                "- max_sessions, and max_cost with cost_from - in the project's "
                "workspace/config/factory.yaml (the autonomous profile sets one), then run: "
                f"wgf resume {run_id} - the resume records it for this run (BUDGET_ADOPTED). "
                "Or set factory.develop.developer.kind: handoff. No agent was started.")

    def exhausted(self, run_id):
        """The BLOCKED message when another session would exceed the budget, else None."""
        if not self.active:
            return None
        max_sessions = self.limits.get("max_sessions")
        how = (f" A person raises it with: wgf resume {run_id} --budget-sessions N"
               f" (or --budget-cost X); an agent cannot.")
        planned = self.limits.get("planned") or {}
        if planned:
            how = (f" The tech plan derived {planned.get('sessions')} sessions"
                   + (f" (cost {planned['cost']:g})" if _amount(planned.get("cost")) else "")
                   + f" for the {planned.get('quality_tier') or 'mvp'} tier"
                   + (f", above the installation's cap - a planned shortfall reported at G3"
                      if planned.get("shortfall") else "")
                   + ": the build is not finished and its quality tier is not achieved within "
                     "this budget." + how)
        if max_sessions is not None and self.sessions >= max_sessions:
            source = ("the lower of factory.develop.budget.max_sessions and the tech plan's "
                      "develop_budget" if planned else "factory.develop.budget.max_sessions")
            return (f"budget exhausted: {self.sessions} developer sessions used of "
                    f"{max_sessions} ({source}"
                    f"{', raised' if self.limits.get('raises') else ''}). No agent was "
                    f"started.{how}")
        max_cost = self.limits.get("max_cost")
        if max_cost is not None and self.cost >= max_cost:
            unknown = (f"; {self.unknown} session(s) reported no readable cost and are not "
                       f"in that sum" if self.unknown else "")
            return (f"budget exhausted: developer cost {self.cost:g} recorded of {max_cost:g} "
                    f"({'the lower of factory.develop.budget.max_cost and the tech plan cost' if planned else 'factory.develop.budget.max_cost'})"
                    f" over {self.sessions} session(s)"
                    f"{unknown}. No agent was started.{how}")
        return None

    def summary(self):
        limits = self.limits or {}
        summary = {"sessions": self.sessions, "max_sessions": limits.get("max_sessions"),
                   "cost": round(self.cost, 6), "max_cost": limits.get("max_cost"),
                   "unknown_cost_sessions": self.unknown}
        planned = limits.get("planned")
        if planned:
            summary["planned_sessions"] = planned.get("sessions")
            summary["planned_cost"] = planned.get("cost")
            summary["quality_tier"] = planned.get("quality_tier")
            if planned.get("shortfall"):
                summary["planned_shortfall"] = planned["shortfall"]
        return summary

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
            if not any(((e.get("data") or {}).get("nonce") == record["nonce"]
                        and (e.get("data") or {}).get("budget") == SESSION) for e in events):
                return record, (
                    "the developer session could not be recorded in the run's event log, so "
                    "it could not be counted against the run's budget; no agent was started. "
                    "Check that the run directory is writable, then resume.")
        return record, None

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

"""The run's quality tier as the plan builds it, and the developer budget derived from the plan.

A run states a quality tier (title-strategy 1.5.0 `concept.content_model.quality_tier`, the
design's own `build_spec.content.quality_tier` over it). What a tier builds before G4 is data,
core/reference/quality-benchmark.yaml `tiers[].builds`: the design tiers whose features and
content units get tasks the developer builds, and the plan phases the developer's brief
carries. In `new-game` the step after G4 is the store listing and then release, so at
`release` the post-mvp features and units are built before G4 or never.

The develop budget is derived from the same tasks, under quality-benchmark `develop`:

    build hours  the est_hours of every task in a phase the tier builds (CORE, GAME, CONTENT)
    sessions     ceil(build hours / session_task_hours) + rework_sessions
    cost         sessions x session_cost

The installation may cap it lower (`factory.develop.budget`, the run's snapshot and any raise
a person recorded). A cap below the plan's need is a planned shortfall: the plan records it,
G3 sees it as a high-severity risk, and the develop step enforces the cap from the first
session - never a mid-run surprise.
"""

import math
import os

from wgflib import budget as run_budget
from wgflib import paths
from wgflib.yamllite import load_file

__all__ = ["BENCHMARK_PATH", "DEFAULT_TIER", "load_benchmark", "quality_tier", "builds",
           "derive_budget", "BudgetBasisError"]

BENCHMARK_PATH = os.path.join(paths.REFERENCE, "quality-benchmark.yaml")
# A run whose strategy and design state no tier (title-strategy before 1.5.0) is planned as
# it always was: the MVP, and the plan's later milestones after G4.
DEFAULT_TIER = "mvp"
_MVP_BUILDS = {"design_tiers": ["mvp"], "plan_phases": ["prototype"]}


class BudgetBasisError(ValueError):
    """quality-benchmark.yaml does not state what the budget is derived from."""


def load_benchmark(path=None):
    return load_file(path or BENCHMARK_PATH) or {}


def quality_tier(design, strategy):
    """(tier, where it was stated): the design's `build_spec.content.quality_tier`, else the
    strategy's `concept.content_model.quality_tier`, else DEFAULT_TIER."""
    content = ((design or {}).get("build_spec") or {}).get("content")
    stated = content.get("quality_tier") if isinstance(content, dict) else None
    if isinstance(stated, str) and stated:
        return stated, "game-design build_spec.content.quality_tier"
    committed = (((strategy or {}).get("concept") or {}).get("content_model") or {})
    if isinstance(committed.get("quality_tier"), str) and committed["quality_tier"]:
        return committed["quality_tier"], "title-strategy concept.content_model.quality_tier"
    return DEFAULT_TIER, "no tier stated by the design or the strategy: mvp"


def builds(tier, benchmark):
    """{"design_tiers", "plan_phases"} a run at `tier` builds before G4, from the benchmark."""
    for entry in (benchmark or {}).get("tiers") or []:
        if isinstance(entry, dict) and entry.get("id") == tier:
            spec = entry.get("builds")
            if isinstance(spec, dict) and spec.get("design_tiers") and spec.get("plan_phases"):
                return {"design_tiers": [str(t) for t in spec["design_tiers"]],
                        "plan_phases": [str(p) for p in spec["plan_phases"]]}
    if tier == DEFAULT_TIER:
        return dict(_MVP_BUILDS)
    raise BudgetBasisError(f"core/reference/quality-benchmark.yaml states no tiers[].builds "
                           f"for quality tier {tier!r}")


def _value(block, key):
    entry = (block or {}).get(key)
    value = entry.get("value") if isinstance(entry, dict) else None
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
        raise BudgetBasisError(f"core/reference/quality-benchmark.yaml develop.{key}.value "
                               f"is not a number >= 0")
    return value, (entry.get("basis") if isinstance(entry, dict) else None)


def derive_budget(dev_plan, plan_phases, benchmark, cap=None, content_unit_hours=None):
    """dev_plan.develop_budget: what the plan's own tasks need, its basis, the installation's
    cap and the shortfall when the cap is below the need.

    `cap` is the run's budget in force (wgflib.budget.effective), or None: no cap - and then
    no command developer starts at all (wgf_develop.budget.missing), which is the
    installation's consent to spend, not this plan's."""
    block = (benchmark or {}).get("develop") or {}
    per_session, per_session_basis = _value(block, "session_task_hours")
    rework, rework_basis = _value(block, "rework_sessions")
    cost_each, cost_basis = _value(block, "session_cost")
    if per_session <= 0:
        raise BudgetBasisError("quality-benchmark develop.session_task_hours must be > 0")
    tasks = [t for t in dev_plan.get("tasks") or [] if t.get("phase") in plan_phases]
    hours = round(sum(float(t.get("est_hours") or 0) for t in tasks), 2)
    content = [t for t in tasks if str(t.get("id", "")).startswith("CONTENT-")]
    build_sessions = math.ceil(hours / per_session) if hours else 0
    sessions = int(build_sessions + math.ceil(rework))
    cost = round(sessions * cost_each, 2)
    budget = {
        "sessions": sessions,
        "cost": cost,
        "basis": {
            "build_hours": hours,
            "tasks": [t.get("id") for t in tasks],
            "content_tasks": len(content),
            "content_hours": round(sum(float(t.get("est_hours") or 0) for t in content), 2),
            "content_unit_hours": content_unit_hours,
            "session_task_hours": per_session,
            "build_sessions": build_sessions,
            "rework_sessions": rework,
            "session_cost": cost_each,
            "calibration": {"session_task_hours": per_session_basis,
                            "rework_sessions": rework_basis,
                            "session_cost": cost_basis},
            "source": "core/reference/quality-benchmark.yaml develop "
                      f"{(benchmark or {}).get('version')}",
            "formula": "sessions = ceil(build_hours / session_task_hours) + rework_sessions; "
                       "cost = sessions x session_cost",
        },
        "cap": None,
        "shortfall": None,
    }
    if cap:
        limits = {name: cap.get(name) for name in run_budget.LIMITS
                  if cap.get(name) is not None}
        budget["cap"] = dict(limits, source="factory.develop.budget")
        shortfall = {}
        if limits.get("max_sessions") is not None and limits["max_sessions"] < sessions:
            shortfall["sessions"] = sessions - limits["max_sessions"]
        if (limits.get("max_cost") is not None and cap.get("cost_from")
                and limits["max_cost"] < cost):
            shortfall["cost"] = round(cost - limits["max_cost"], 2)
        budget["shortfall"] = shortfall or None
    return budget

"""The tech-plan module: game-design + title-strategy in, tech-plan out.

    game-design ──► engine (the design's declared renderer) ─┐
    title-strategy ─► pinned platforms + budgets ─────────────┼─► repo_params.game_config
                                                              └─► dev_plan ─► tech-plan

Deterministic and offline: it reads its two inputs and core/reference, and returns one
artifact. It is a minimal, honest planner - it maps what the design and strategy already
decided onto the tech-plan contract and estimates with a documented heuristic. It does not
research engines or invent architecture. See docs/techplan-module.md.

Registered from workspace/config/factory.yaml (`factory.steps.modules: [wgf_techplan]`) and
configured by the optional `factory.techplan` section there.
"""

from .devplan import Estimates, build_dev_plan
from .selection import (
    ENGINE_FOR_DIMENSION,
    EngineError,
    PlatformError,
    select_engine,
    pin_platforms,
)
from .step import TechPlanStep, TechPlanSettings, SettingsError

__all__ = [
    "ENGINE_FOR_DIMENSION",
    "EngineError",
    "Estimates",
    "PlatformError",
    "SettingsError",
    "TechPlanSettings",
    "TechPlanStep",
    "build_dev_plan",
    "pin_platforms",
    "register",
    "select_engine",
]


def register(registry):
    registry.register(TechPlanStep.type, TechPlanStep)
    return registry

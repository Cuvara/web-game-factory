"""The strategy module: turns a researched opportunity into a title strategy.

Registered from workspace/config/factory.yaml (`factory.steps.modules`). See
docs/workflow-module-contract.md for the contract and core/lifecycle/stages/strategy.md for
the procedure this implements.
"""

from .planner import Policy, StrategyRefused, plan_strategy
from .step import StrategyStep

__all__ = ["Policy", "StrategyRefused", "StrategyStep", "plan_strategy", "register"]


def register(registry):
    registry.register(StrategyStep.type, StrategyStep)

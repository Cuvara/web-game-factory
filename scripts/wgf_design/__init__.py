"""The design module: turns a title-strategy into a production-oriented game-design.

Registered from workspace/config/factory.yaml (`factory.steps.modules: [wgf_design]`) as the
`design` step type. See docs/workflow-module-contract.md for what a module owes the engine,
and core/lifecycle/stages/design.md for the procedure this implements.

    authors.py      who writes the creative draft; `archetype` is built in, others register
    agent.py        the opt-in `agent` author: an agent host improves the archetype draft
    archetypes.py   genre shapes the built-in author fits to a strategy
    identity.py     visual identity kits - a committed look, never a default one
    platforms.py    pinned platform profiles as binding constraints, and SDK touchpoints
    compose.py      draft -> game-design body; the "buildable without guessing" check
    consistency.py  core/reference/design-consistency-rules.yaml, the exit guard
    step.py         the WorkflowStep
"""

from .authors import AuthorError, DesignAuthor, register_author
from .agent import AgentAuthor, AgentRunFailed
from .step import DesignStep, register

__all__ = ["AgentAuthor", "AgentRunFailed", "AuthorError", "DesignAuthor", "DesignStep",
           "register", "register_author"]

"""Discovery: the `research` step of the new-game workflow.

A market scan that decides what kind of web game to build. It reads the factory's platform
profiles, evidence snapshots captured from the web and - when enabled - pages fetched live,
turns them into tiered claims, screens a catalog of game archetypes against every target
portal, and emits a `research-report` plus the one `opportunity` it carries forward.

Enable it in workspace/config/factory.yaml:

    factory:
      steps:
        modules: [wgf_discovery]

See step.py for settings and outcomes, evidence.py for what counts as evidence, and
analysis.py for how claims become a selection.
"""

from .step import ResearchStep

__all__ = ["ResearchStep", "register"]


def register(registry):
    registry.register(ResearchStep.type, ResearchStep)
    return registry

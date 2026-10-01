"""The visual-qa module: a vision judge reads a production build's frames against a rubric.

Registers the `visual-qa` step type. Declared in workspace/config/factory.yaml:

    factory:
      steps:
        modules: [wgf_visualqa]

It runs after the production build has been played (`playability`): it hands a judge - an
agent able to read images, configured under `factory.visualqa.judge` like the reviewer -
every frame the bot captured, desktop and mobile, with a brief that lists each frame's state
and viewport, core/reference/visual-qa-rubric.yaml, the design's visual identity and the
asset roles. The judge scores and lists findings; the step decides:

    PASS     no blocker, every rubric dimension at or above the pass bar   SUCCESS
    FAIL     otherwise: FAILED, route `assets` when any failure is an asset's, else
             `develop`, not retryable - the workflow routes it back
    BLOCKED  no judge configured (never a silent pass), or no frames to judge

See step.py and docs/visual-qa-module.md.
"""

from .step import VisualQAStep

__all__ = ["VisualQAStep", "register"]


def register(registry):
    registry.register(VisualQAStep.type, VisualQAStep)
    return registry

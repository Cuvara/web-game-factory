"""The playability module: a built game is played from outside before it is called playable.

Registers the `playability` step type. Declared in workspace/config/factory.yaml:

    factory:
      steps:
        modules: [wgf_playability]

It runs after `develop` commits a build: it clones that commit, builds it, and plays it on a
desktop and a mobile viewport with real input through the game's play probe
(core/artifacts/shared/play-probe.schema.json), holding what it sees to the design's
experience contract and core/reference/visual-quality.yaml - the objective on screen, no
failure before the grace, every action visibly acknowledged, a reachable win (or rising
objective) and loss, a working retry, readable entities, lit frames. A failed check routes
the build back to develop with the frames that show it. See step.py.
"""

from .step import PlayabilityStep

__all__ = ["PlayabilityStep", "register"]


def register(registry):
    registry.register(PlayabilityStep.type, PlayabilityStep)
    return registry

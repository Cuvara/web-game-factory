"""The development module: builds the playable game inside the title's game repository.

Registers the `develop` step type. Declared in workspace/config/factory.yaml:

    factory:
      steps:
        modules: [wgf_develop]

The module owns development; the engine owns orchestration. It reads the game design, the
asset manifest, the scaffold record and the title strategy, turns them into a development
brief, hands the brief to a developer, then checks what came back - template conformance,
typecheck, lint, tests, build and the browser smoke suite - and commits it in the game
repository. Its output is the `prototype-report` the G4 review starts from.

It writes game source only in the game repository, never here: this repository holds no
game code. It never pushes, never creates a repository and never implements a platform
SDK - the template's platform abstraction is the seam, and the integration module fills it.
See docs/development-module.md.
"""

from .step import DevelopStep

__all__ = ["DevelopStep", "register"]


def register(registry):
    registry.register(DevelopStep.type, DevelopStep)
    return registry

"""The production-quality module: a build is held to production art and production UI.

Registers the `production-quality` step type. Declared in workspace/config/factory.yaml:

    factory:
      steps:
        modules: [wgf_production]

It runs after `playability` and reads that step's raw records (playability-report
`records_dir`) rather than playing the build again: every mvp asset delivered, not a
placeholder and passing its own quality checks; fetched by the page during play; drawing the
entities a player must recognise, none of them an engine primitive unless the design's
visual_identity.primitive_style allows it; and the UI measured on each screen state - target
size, overlap, text contrast and size, controls not in the browser's default style, the
win/lose/retry screens seen. A failure routes to `assets` or `develop`. See step.py and
docs/production-quality-module.md.
"""

from .step import ProductionQualityStep

__all__ = ["ProductionQualityStep", "register"]


def register(registry):
    registry.register(ProductionQualityStep.type, ProductionQualityStep)
    return registry

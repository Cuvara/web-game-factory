"""The content-sufficiency module: the built game carries the content its quality tier asks for.

Registers the `content-sufficiency` step type. Declared in workspace/config/factory.yaml:

    factory:
      steps:
        modules: [wgf_sufficiency]

It runs after `visual-qa` and reads the playability step's raw records (playability-report
`records_dir`) and the content data file of the commit it played, rather than playing the
build again: the units the build ships and reaches, the elements and their combinations the
probe shows in each, structural variety and near-identical units, groups that bring something
new, difficulty that asks for new skills, objective kinds, climax units with art of their
own, gated unlocks, designed play, and every design commitment present in the build - against
core/reference/quality-benchmark.yaml at the design's quality tier. A failure routes to
`design-gap` (the design is short of the tier) or `develop` (the build is short of the
design), with typed findings. See audit.py, step.py and docs/content-sufficiency-module.md.
"""

from .step import ContentSufficiencyStep

__all__ = ["ContentSufficiencyStep", "register"]


def register(registry):
    registry.register(ContentSufficiencyStep.type, ContentSufficiencyStep)
    return registry

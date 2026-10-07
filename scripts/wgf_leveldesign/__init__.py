"""The level-design module: a level critic reads every sampled unit's frames against a rubric,
and the oracle's safe and greedy policies show whether an optional risk exists and pays.

Registers the `level-design` step type. Declared in workspace/config/factory.yaml:

    factory:
      steps:
        modules: [wgf_leveldesign]

It runs after the production build has been played (`playability`, with `survey` and `risk`)
and its content counted: it hands a critic - an agent able to read images, configured under
`factory.leveldesign.judge` like visual QA's judge, or the deterministic `baseline` - three
frames of every sampled unit (start, middle, end) with core/reference/level-design-rubric.yaml
and the design's own words for each unit, and holds the bot's risk record to
core/reference/risk-reward.yaml. The step decides:

    PASS      every sampled unit at or above the rubric's bars on every dimension, every
              moment captured, greedy earning more at a higher failure rate     SUCCESS
    FAIL      at a strict tier (quality-policy skipped_checks, the release tier): any of them
              failed or measured nothing                         FAILED, route `design-gap`
              when a failure routes there, else `develop`, not retryable
    WARNING   below that tier: the same shortfalls, reported and not held      SUCCESS
    SKIPPED   below that tier, nothing judged (no judge configured)           SUCCESS
    BLOCKED   at a strict tier, no judge configured; a frame no longer on disk or not the one
              recorded; a rubric the run pinned that was edited after the start

See step.py and docs/level-design-critic.md.
"""

from .step import LevelDesignStep

__all__ = ["LevelDesignStep", "register"]


def register(registry):
    registry.register(LevelDesignStep.type, LevelDesignStep)
    return registry

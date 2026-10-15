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
core/reference/risk-reward.yaml. Its checks are ADVISORY as shipped (core/reference/
check-tiers.yaml 1.8.0): no pinned template implements the probe's play.policy and no critic is
configured by default. Unless the installation holds the build to them
(factory.leveldesign.hold), a strict tier is treated like any other. The step decides:

    PASS      every sampled unit at or above the rubric's bars on every dimension, every
              moment captured, greedy earning more at a higher failure rate     SUCCESS
    WARNING   not held: any shortfall, reported and not held                   SUCCESS
    SKIPPED   not held: nothing judged (no judge configured, no play.policy, a critic that
              could not judge)                                                 SUCCESS
    FAIL      held at a strict tier (quality-policy skipped_checks, the release tier): any
              of them failed or measured nothing                 FAILED, route `design-gap`
              when a failure routes there, else `develop`, not retryable
    BLOCKED   held at a strict tier: no judge configured, a frame no longer on disk; at any
              tier, a rubric the run pinned that was edited after the start

See step.py and docs/level-design-critic.md.
"""

from .step import LevelDesignStep

__all__ = ["LevelDesignStep", "register"]


def register(registry):
    registry.register(LevelDesignStep.type, LevelDesignStep)
    return registry

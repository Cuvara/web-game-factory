"""The review module: an independent reviewer for every development commit.

Registers the `review` step type. Declared in workspace/config/factory.yaml:

    factory:
      steps:
        modules: [wgf_review]

The step runs after `develop` has committed. It hands the reviewer the commit to review and
a path - outside the game checkout - to write its verdict to, then checks two things the
reviewer does not get to assert: that the checkout is exactly as it was before the review
(the reviewer is read-only, and that is enforced by fingerprinting, not requested), and
that the verdict is well-formed and names the commit that was reviewed.

    approve            SUCCESS, the run continues
    request-changes    FAILED, route `request-changes`, not retryable: the workflow file
                       routes it back to develop, whose next brief carries the blockers.
                       Unrouted, it fails the run - a rejected build never continues.

The reviewer is configured, never named here: `factory.review.reviewer` is `none` (the
step records a skipped review, never an approval) or `command` (an argv the installation
supplies, typically an agent host's non-interactive mode). See docs/review-module.md.
"""

from .step import ReviewStep

__all__ = ["ReviewStep", "register"]


def register(registry):
    registry.register(ReviewStep.type, ReviewStep)
    return registry

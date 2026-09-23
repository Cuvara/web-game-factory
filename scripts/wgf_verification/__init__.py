"""The verification module: the `verify` workflow step.

Declared in workspace/config/factory.yaml:

    factory:
      steps:
        modules: [wgf_verification]

Determines whether a build is technically ready for release - build, code, gameplay,
platform, assets, policy - and returns a verification-report (every check with its
evidence) and the qa-report derived from it. See docs/verification-module.md.
"""

from .step import VerifyStep

__all__ = ["VerifyStep", "register"]


def register(registry):
    registry.register(VerifyStep.type, VerifyStep)
    return registry

"""The SDK module: platform integration evidence for a game build.

Registered from workspace/config/factory.yaml (`factory.steps.modules: [wgf_sdk]`) as the
`sdk` step type. It prepares, per targeted platform, which SDK features the build must
integrate (from the pinned platform profiles and the game's own game.config.yaml), runs the
game repository's SDK conformance suite against mocked portal SDKs, and writes the
sdk-report. It never publishes: publishing belongs to the game repository's release
pipeline, behind G5 and G6.

    plan.py      what each platform requires of the build, from profile + game.config
    evidence.py  running the conformance suite, and reading its report
    step.py      the WorkflowStep
"""

from .step import SdkStep, register

__all__ = ["SdkStep", "register"]

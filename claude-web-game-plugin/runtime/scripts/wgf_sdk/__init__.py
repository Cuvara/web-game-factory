"""The SDK module: the template's platform SDK integrated into a game, and the evidence.

Registered from workspace/config/factory.yaml (`factory.steps.modules: [wgf_sdk]`) as the
`sdk` step type. It integrates what the game-design needs into the game (the gameplay
layer, the develop step's seam and main.ts wired to the template's `Platform`), derives per
targeted platform which SDK features the build must have (from the pinned platform
profiles and the game's own game.config.yaml), runs the integration's own mock suite and
the game repository's SDK conformance suite against mocked portal SDKs, and writes the
sdk-report. It writes no SDK and never publishes: publishing belongs to the game
repository's release pipeline, behind G5 and G6.

    plan.py         what each platform requires of the build, from profile + game.config
    evidence.py     running the conformance suite, and reading its report
    design.py       what the game-design needs: placements, moments, features
    inspect_sdk.py  the SDK revision the game repository carries
    integrate.py    the files and patches written into the game repository
    integration.py  the integration phase
    runner.py       the integration's own suite, typecheck and git state
    step.py         the WorkflowStep: both phases, one report
    game/           the TypeScript the integration phase writes into a game
    e2e.py, e2e/    browser e2e over a real template revision (not part of unittest)
"""

from .step import SdkStep, register

__all__ = ["SdkStep", "register"]

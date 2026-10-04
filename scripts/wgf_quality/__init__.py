"""The quality-gate module: one build held to the Factory's quality contract.

Registers the `quality-gate` step type. Declared in workspace/config/factory.yaml:

    factory:
      steps:
        modules: [wgf_quality]

It runs after verify and before G4, and reads the reports the producing steps wrote about
the same build - playability, production-quality, visual-qa, content-sufficiency, verify,
review, sdk - rather than measuring anything again. It scores every quality dimension against
core/reference/quality-floor.yaml (the universal floor, the genre family's contract, the 3D
contract) and the release bars of core/reference/quality-benchmark.yaml at the run's quality
tier, as the run pinned them when it started. A dimension below its floor fails the step,
routed by the owner of the findings that hold it there. See scoring.py, step.py and
docs/quality-gate-module.md.
"""

from .step import QualityGateStep

__all__ = ["QualityGateStep", "register"]


def register(registry):
    registry.register(QualityGateStep.type, QualityGateStep)
    return registry

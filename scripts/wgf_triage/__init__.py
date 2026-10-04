"""The triage module: a quality finding becomes routed, role-specific work.

Registers the `triage` step type. Declared in workspace/config/factory.yaml:

    factory:
      steps:
        modules: [wgf_triage]

The gates that judge a build, and G4's iterate, route to `triage`. It normalizes the current
build's failures into quality findings (core/artifacts/shared/quality-finding.schema.json,
findings.py), groups them by the specialist that owns each dimension
(core/reference/specialist-routing.yaml, routing.py), and returns one group's route label:
`design`, `assets`, or a specialist's role id, which the workflow maps to develop. The
develop visit it routes is that specialist's. See step.py and docs/specialist-routing.md.
"""

from .findings import NormalizeError, finding_id, from_requests, normalize
from .routing import Routing, RoutingError
from .step import FINDINGS_MARKER, NEXT_SPECIALIST, TriageStep, read_typed_findings

__all__ = ["TriageStep", "Routing", "RoutingError", "normalize", "from_requests",
           "finding_id", "NormalizeError", "NEXT_SPECIALIST", "FINDINGS_MARKER",
           "read_typed_findings", "register"]


def register(registry):
    registry.register(TriageStep.type, TriageStep)
    return registry

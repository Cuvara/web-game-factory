"""The release module: the `release` workflow step (stage release:draft).

Declared in workspace/config/factory.yaml:

    factory:
      steps:
        modules: [wgf_release]

Prepares a draft release from a verified commit: refuses unless the newest qa-report in the
run passed, pins the newest evidence, and names the same commit as every upstream report
and the checkout's clean HEAD; then runs the game repository's own `release:package` and
`release:manifest`, audits every package, and returns a schema-valid release-manifest in
state `draft`. Never pushes, tags, publishes or contacts a portal. See
docs/release-module.md.
"""

from .step import ReleaseStep

__all__ = ["ReleaseStep", "register"]


def register(registry):
    registry.register(ReleaseStep.type, ReleaseStep)
    return registry

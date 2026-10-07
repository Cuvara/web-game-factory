"""The accepted-baseline module: a build a person accepted is the bar the next build of the
same game must not fall below.

Registers the `accepted-baseline` and `baseline-regression` step types. Declared in
workspace/config/factory.yaml:

    factory:
      steps:
        modules: [wgf_baseline]

`accepted-baseline` finds the newest G4 `pass` a person gave for the title (or the commit
factory.baseline.accepted names) and pins the accepted build into the run: its commit, its
reports and its frames. `baseline-regression` holds each later build to it: how much of the
accepted build it replaced (above core/reference/accepted-baseline.yaml's maximum a person
decides), the same bot's metrics within tolerance, a paired judgement of the same states, and
the playtest notes a person filed (scripts/wgf-playtest.py). See step.py and
docs/accepted-baseline.md.
"""

from .step import AcceptedBaselineStep, BaselineRegressionStep, register

__all__ = ["AcceptedBaselineStep", "BaselineRegressionStep", "register"]

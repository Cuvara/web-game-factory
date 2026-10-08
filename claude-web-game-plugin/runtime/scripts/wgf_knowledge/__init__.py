"""The Factory's knowledge: lessons as rules with a scope and an enforcement level.

    model     the knowledge model of core/reference/lessons.yaml 2.0.0: levels derived from
              check tiers, scope and its vocabularies, lifecycle, exceptions, and what
              check-integrity holds of all of them
    resolve   the applicability resolver: the rules that apply to a run's facets, with why,
              and the excluded ones with why not
    versions  the versions of everything a run's knowledge is judged by
    cli       `wgf knowledge` (validate, show, resolve, contract, table)
    step      the `knowledge` step: the run's knowledge-contract, after design, before
              tech-plan; a run that cannot make it stops
    exceptions
              a person's exception, granted on `wgf resume --except` as an operator event

Pure reads of data files: no process, no network. Nothing here names a game, a step or a
family; the scope vocabularies are read from the reference files that define them.
See docs/knowledge-enforcement.md.
"""

__all__ = ["register"]


def register(registry):
    """Registers the `knowledge` step type (step.py): the run's knowledge-contract, made
    after design and before tech-plan. Declared in workspace/config/factory.yaml."""
    from .step import KnowledgeStep
    registry.register(KnowledgeStep.type, KnowledgeStep)
    return registry

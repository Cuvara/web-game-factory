"""The Factory's knowledge: lessons as rules with a scope and an enforcement level.

    model     the knowledge model of core/reference/lessons.yaml 2.0.0: levels derived from
              check tiers, scope and its vocabularies, lifecycle, exceptions, and what
              check-integrity holds of all of them
    resolve   the applicability resolver: the rules that apply to a run's facets, with why,
              and the excluded ones with why not
    versions  the versions of everything a run's knowledge is judged by
    cli       `wgf knowledge` (validate, show, resolve, contract, table)

Pure reads of data files: no process, no network. Nothing here names a game, a step or a
family; the scope vocabularies are read from the reference files that define them.
See docs/knowledge-enforcement.md.
"""

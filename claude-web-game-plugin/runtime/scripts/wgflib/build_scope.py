"""What a run builds before G4, read one way by the step that plans it and every step that
judges it.

A run states a quality tier (title-strategy 1.5.0 `concept.content_model.quality_tier`, the
design's own `build_spec.content.quality_tier` over it). What a tier builds is data:
core/reference/quality-benchmark.yaml `tiers[].builds` - the design tiers whose features and
content units the tech plan plans and the developer builds (`design_tiers`), and the plan
phases the developer's brief carries (`plan_phases`). The tech plan records it as
`dev_plan.build_scope`; a judging step that has no tech plan among its inputs reads the same
rule here, so "the design's units" a playability bot, a content audit or a verification check
holds a build to are exactly the units the run built:

    quality_tier(design, strategy, run)   (tier, where it was stated)
    builds(tier)                          {"design_tiers", "plan_phases"} at the tier
    design_tiers(design, strategy, run)   the design tiers the run builds
    in_scope(entry, tiers)                whether a tiered design entry is built
    units(design, ...)                    the design's content units the run builds, in order

At `mvp` that is the MVP units; at `release` the MVP and the post-mvp units. An `optional`
unit is never built, and an id the design does not list is never a unit of it.
"""

import os

from wgflib import paths
from wgflib.yamllite import load_file

__all__ = ["BENCHMARK_PATH", "DEFAULT_TIER", "MVP_BUILDS", "BuildScopeError", "load_benchmark",
           "quality_tier", "builds", "design_tiers", "in_scope", "units"]

BENCHMARK_PATH = os.path.join(paths.REFERENCE, "quality-benchmark.yaml")
# A run whose strategy and design state no tier (title-strategy before 1.5.0) is planned as
# it always was: the MVP, and the plan's later milestones after G4.
DEFAULT_TIER = "mvp"
MVP_BUILDS = {"design_tiers": ["mvp"], "plan_phases": ["prototype"]}


class BuildScopeError(ValueError):
    """quality-benchmark.yaml does not state what a tier builds."""


def load_benchmark(path=None):
    return load_file(path or BENCHMARK_PATH) or {}


def quality_tier(design, strategy=None, run=None):
    """(tier, where it was stated): the design's `build_spec.content.quality_tier`, else the
    strategy's `concept.content_model.quality_tier`, else `run` (the run's own quality tier,
    for a step without the strategy among its inputs), else DEFAULT_TIER."""
    content = ((design or {}).get("build_spec") or {}).get("content")
    stated = content.get("quality_tier") if isinstance(content, dict) else None
    if isinstance(stated, str) and stated:
        return stated, "game-design build_spec.content.quality_tier"
    committed = (((strategy or {}).get("concept") or {}).get("content_model") or {})
    if isinstance(committed.get("quality_tier"), str) and committed["quality_tier"]:
        return committed["quality_tier"], "title-strategy concept.content_model.quality_tier"
    if isinstance(run, str) and run:
        return run, "the run's quality tier"
    return DEFAULT_TIER, "no tier stated by the design or the strategy: mvp"


def builds(tier, benchmark=None):
    """{"design_tiers", "plan_phases"} a run at `tier` builds before G4, from the benchmark."""
    benchmark = load_benchmark() if benchmark is None else benchmark
    for entry in (benchmark or {}).get("tiers") or []:
        if isinstance(entry, dict) and entry.get("id") == tier:
            spec = entry.get("builds")
            if isinstance(spec, dict) and spec.get("design_tiers") and spec.get("plan_phases"):
                return {"design_tiers": [str(t) for t in spec["design_tiers"]],
                        "plan_phases": [str(p) for p in spec["plan_phases"]]}
    if tier == DEFAULT_TIER:
        return {key: list(value) for key, value in MVP_BUILDS.items()}
    raise BuildScopeError(f"core/reference/quality-benchmark.yaml states no tiers[].builds "
                          f"for quality tier {tier!r}")


def design_tiers(design, strategy=None, run=None, benchmark=None):
    """The design tiers the run builds, as a tuple (quality_tier, then builds)."""
    tier, _where = quality_tier(design, strategy, run)
    return tuple(builds(tier, benchmark)["design_tiers"])


def in_scope(entry, tiers):
    """Whether a design entry (a unit, a feature) of these `tiers` is built: an untiered entry
    is MVP."""
    return (entry.get("tier") or "mvp") in tiers


def units(design, tiers=None, strategy=None, run=None, benchmark=None):
    """The design's content units the run builds, in play order: of `tiers` (else the run's,
    design_tiers). The order is `build_spec.progression.unit_sequence` where it names the unit,
    then the unit's own `index`. A design that tiers none of its units into the scope is held
    to every unit it lists, never to none."""
    if tiers is None:
        tiers = design_tiers(design, strategy, run, benchmark)
    spec = (design or {}).get("build_spec") or {}
    content = spec.get("content") if isinstance(spec.get("content"), dict) else {}
    listed = [u for u in content.get("units") or [] if isinstance(u, dict)]
    built = [u for u in listed if in_scope(u, tiers)] or listed
    sequence = list(((spec.get("progression") or {}).get("unit_sequence")) or [])

    def place(unit):
        uid = unit.get("id")
        index = unit.get("index") if isinstance(unit.get("index"), int) else 10 ** 6
        return (sequence.index(uid) if uid in sequence else len(sequence), index, str(uid))
    return sorted(built, key=place)

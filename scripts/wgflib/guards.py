"""Compute the guards the lifecycle machines name.

core/lifecycle/*.machine.yaml declares each guard as one line of pseudo-expression - that is
the specification, and it stays in core because core must remain readable by a provider that
cannot execute anything. This module is the computation, and it lives in scripts/ for the
same reason.

The rule the whole module is built around, stated once in every generated command and
enforced here:

    A guard that cannot be evaluated is a blocker to report, not one to assume.

So a guard returns one of three things, never two. GREEN and RED are answers. UNKNOWN is the
honest third case - the data is not here, the game repository is not reachable, or only a
human can say - and it carries the reason. Nothing collapses UNKNOWN into RED, because
"we checked and it failed" and "we could not check" lead to different actions.

Guards whose answer lives in the game repository (ci_green, playable_build, the release and
publication guards) are UNKNOWN from the Factory side until a repository is supplied. That is
not a gap to paper over: the Factory deliberately holds no game source, and the two guards
that do have implementations name them - web-game-template's ci.yml and verify.yml.
"""

import datetime
import glob
import json
import os

from . import paths
from .criteria import Unevaluable, evaluate
from .hashing import CanonicalizationError, content_hash
from .workspace import WorkspaceError, all_title_states, load_scoring_model

__all__ = ["Verdict", "GuardContext", "evaluate_guard", "known_guards"]

# Pre-live, non-terminal title states count against the WIP cap: work in flight is work the
# portfolio owner has to clear gates for. `live` does not - a live title iterates on its own.
WIP_STATES = (
    "concept", "strategy", "design", "tech-plan", "scaffolding",
    "prototype", "prototype-review", "production", "releasing",
)


class Verdict:
    """GREEN, RED or UNKNOWN, with the reason and whatever was measured to get there."""

    __slots__ = ("value", "reason", "measurements")

    def __init__(self, value, reason="", measurements=None):
        self.value = value
        self.reason = reason
        self.measurements = measurements or {}

    @property
    def symbol(self):
        return {True: "GREEN", False: "RED"}.get(self.value, "UNKNOWN")

    def __bool__(self):
        # Deliberately not overloaded to treat UNKNOWN as False. Callers must look at
        # `.value` and handle the third case; making `if verdict:` work would make forgetting
        # to handle it the easy path.
        raise TypeError("check Verdict.value explicitly; UNKNOWN is not False")

    def __repr__(self):
        return f"<{self.symbol} {self.reason}>"


def green(reason="", **measurements):
    return Verdict(True, reason, measurements)


def red(reason, **measurements):
    return Verdict(False, reason, measurements)


def unknown(reason, **measurements):
    return Verdict(None, reason, measurements)


class GuardContext:
    """What a guard is allowed to read."""

    def __init__(self, entity, config=None, now=None, game_repo=None):
        self.entity = entity
        self.config = config or {}
        self.now = now or datetime.datetime.now(datetime.timezone.utc)
        self.game_repo = game_repo

    @property
    def overrun_tolerance(self):
        return self.config.get("overrun_tolerance", 1.5)

    def scoring_model(self):
        model_id = self.config.get("default_scoring_model", "portfolio-default")
        return load_scoring_model(model_id)


REGISTRY = {}


def guard(name):
    def register(function):
        REGISTRY[name] = function
        return function

    return register


def known_guards():
    return sorted(REGISTRY)


def evaluate_guard(name, context):
    """Evaluate one guard by name. Never raises for missing data - that is UNKNOWN."""
    implementation = REGISTRY.get(name)
    if implementation is None:
        return unknown(f"no computation is registered for guard {name!r}")
    try:
        return implementation(context)
    except WorkspaceError as exc:
        return unknown(str(exc))
    except (Unevaluable, CanonicalizationError) as exc:
        return unknown(str(exc))


def _parse_time(value):
    if not isinstance(value, str):
        return None
    try:
        return datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


# --------------------------------------------------------------------- portfolio


@guard("scored_completely")
def scored_completely(context):
    evaluation = context.entity.artifact("evaluation")
    model = context.scoring_model()
    wanted = {dimension["id"] for dimension in model.get("dimensions") or []}
    present = {entry["dimension_id"] for entry in evaluation.get("dimensions") or []}
    missing = sorted(wanted - present)
    if missing:
        return red(f"not scored: {', '.join(missing)}", missing=missing)
    return green(f"all {len(wanted)} dimensions scored")


@guard("above_shortlist_threshold")
def above_shortlist_threshold(context):
    evaluation = context.entity.artifact("evaluation")
    model = context.scoring_model()
    aggregate = evaluation.get("aggregate")
    threshold = model.get("shortlist_threshold")
    if aggregate is None or threshold is None:
        return unknown("evaluation.aggregate or scoring_model.shortlist_threshold is absent")
    return Verdict(
        aggregate >= threshold,
        f"aggregate {aggregate} vs threshold {threshold}",
        {"aggregate": aggregate, "shortlist_threshold": threshold},
    )


@guard("evidence_coverage_met")
def evidence_coverage_met(context):
    evaluation = context.entity.artifact("evaluation")
    model = context.scoring_model()
    coverage = evaluation.get("evidence_coverage")
    floor = (model.get("evidence_policy") or {}).get("min_coverage")
    if coverage is None or floor is None:
        return unknown("evidence_coverage or evidence_policy.min_coverage is absent")
    return Verdict(
        coverage >= floor,
        f"coverage {coverage} vs floor {floor}",
        {"evidence_coverage": coverage, "min_coverage": floor},
    )


@guard("no_veto_fired")
def no_veto_fired(context):
    """`evaluation.vetoes_fired` is typed as criterionResult[], so it records every veto that
    was *evaluated*, each carrying `breached`. Emptiness is therefore not the question - the
    schema's own note says the vetoes are "recorded by id even when empty, so a rejection is
    always explainable in one sentence", which only works if the ones that held are there too.
    """
    evaluation = context.entity.artifact("evaluation")
    evaluated = evaluation.get("vetoes_fired") or []
    if not evaluated:
        return unknown("evaluation.vetoes_fired is empty; no veto was recorded as evaluated")

    fired = [entry.get("criterion_id", "?") for entry in evaluated if entry.get("breached")]
    if fired:
        return red(f"vetoes fired: {', '.join(fired)}", vetoes=fired)
    return green(f"{len(evaluated)} vetoes evaluated, none fired")


@guard("wip_available")
def wip_available(context):
    cap = context.config.get("max_concurrent_titles")
    if cap is None:
        return unknown("workspace/config/portfolio.yaml has no max_concurrent_titles")
    in_flight = [
        title_id
        for title_id, state in all_title_states()
        if state.get("current_state") in WIP_STATES
    ]
    return Verdict(
        len(in_flight) < cap,
        f"{len(in_flight)} of {cap} in flight" + (f": {', '.join(in_flight)}" if in_flight else ""),
        {"in_flight": in_flight, "max_concurrent_titles": cap},
    )


@guard("evidence_fresh")
def evidence_fresh(context):
    model = context.scoring_model()
    ttl = model.get("evidence_ttl_days")
    if ttl is None:
        return unknown("scoring model has no evidence_ttl_days")

    newest = None
    for path in sorted(glob.glob(os.path.join(paths.CLAIMS, "*.json"))):
        with open(path, encoding="utf-8") as handle:
            claim = json.load(handle)
        for evidence in claim.get("evidence") or []:
            observed = _parse_time(evidence.get("observed_at"))
            if observed and (newest is None or observed > newest):
                newest = observed

    if newest is None:
        return unknown("no dated evidence found under workspace/claims/")
    age = (context.now - newest).days
    return Verdict(
        age <= ttl,
        f"newest evidence is {age} days old, ttl {ttl}",
        {"age_days": age, "evidence_ttl_days": ttl},
    )


# ------------------------------------------------------------------------- title


@guard("kill_criteria_defined")
def kill_criteria_defined(context):
    strategy = context.entity.artifact("title-strategy")
    criteria = strategy.get("kill_criteria") or []
    if not criteria:
        return red("title-strategy.kill_criteria is empty")
    malformed = [c.get("id", "?") for c in criteria if not isinstance(c.get("when"), dict)]
    if malformed:
        return red(f"not criteria-expressions: {', '.join(malformed)}")
    return green(f"{len(criteria)} kill criteria defined")


@guard("timebox_set")
def timebox_set(context):
    strategy = context.entity.artifact("title-strategy")
    timebox = strategy.get("timebox_days")
    platforms = strategy.get("platform_set") or []
    if not timebox:
        return red("title-strategy.timebox_days is not set")
    if not platforms:
        return red("title-strategy.platform_set is empty")
    return green(f"{timebox} days, {len(platforms)} platform(s)", timebox_days=timebox)


@guard("design_consistent")
def design_consistent(context):
    design = context.entity.artifact("game-design")
    consistency = design.get("consistency") or {}
    status = consistency.get("status")
    if status is None:
        return unknown("game-design.consistency has not been evaluated")
    breached = [
        result["criterion_id"]
        for result in consistency.get("rule_results") or []
        if result.get("breached")
    ]
    if status == "pass":
        return green(f"{len(consistency.get('rule_results') or [])} rules evaluated, none blocking")
    return red(f"consistency {status}; breached: {', '.join(breached) or 'unrecorded'}")


@guard("plan_fits_timebox")
def plan_fits_timebox(context):
    plan = context.entity.artifact("tech-plan")
    strategy = context.entity.artifact("title-strategy")
    milestones = ((plan.get("dev_plan") or {}).get("milestones")) or []
    estimates = [m.get("est_days") for m in milestones]
    if not milestones or any(value is None for value in estimates):
        return unknown("tech-plan.dev_plan.milestones[].est_days is incomplete")
    total = sum(estimates)
    budget = strategy.get("timebox_days")
    if budget is None:
        return unknown("title-strategy.timebox_days is not set")
    allowed = budget * context.overrun_tolerance
    return Verdict(
        total <= allowed,
        f"{total} estimated days vs {allowed} allowed ({budget} x {context.overrun_tolerance})",
        {"est_days_total": total, "allowed_days": allowed},
    )


@guard("engine_selected")
def engine_selected(context):
    plan = context.entity.artifact("tech-plan")
    engine = plan.get("engine") or {}
    kind = engine.get("type")
    if kind not in ("pixijs", "threejs"):
        return red(f"engine.type is {kind!r}; PixiJS for 2D, Three.js for 3D, nothing else")
    if not (engine.get("rationale") or "").strip():
        return red(f"{kind} selected with no written rationale")
    return green(f"{kind} with a rationale", engine=kind)


@guard("asset_manifest_present")
def asset_manifest_present(context):
    manifest = context.entity.artifact("asset-manifest")
    items = manifest.get("items") or []
    if not items:
        return red("asset-manifest has no items")
    incomplete = [
        item.get("id", "?")
        for item in items
        if not item.get("source") or item.get("est_cost") is None
    ]
    if incomplete:
        return red(f"{len(incomplete)} item(s) lack a source or an estimate")
    return green(f"{len(items)} items, all sourced and estimated")


@guard("kill_criteria_not_breached")
def kill_criteria_not_breached(context):
    report = context.entity.artifact("prototype-report")
    results = report.get("kill_criteria_eval") or []
    if not results:
        return unknown("prototype-report.kill_criteria_eval is empty; nothing was checked")

    strategy = context.entity.maybe("title-strategy") or {}
    declared = {c.get("id") for c in strategy.get("kill_criteria") or []}
    checked = {result.get("criterion_id") for result in results}
    unchecked = sorted(declared - checked)
    if unchecked:
        # Silence on a criterion is not a pass on it.
        return unknown(f"kill criteria not evaluated: {', '.join(unchecked)}")

    breached = [r["criterion_id"] for r in results if r.get("breached")]
    if breached:
        return red(f"breached: {', '.join(breached)}", breached=breached)
    return green(f"{len(results)} criteria evaluated, none breached")


@guard("iterations_remaining")
def iterations_remaining(context):
    strategy = context.entity.maybe("title-strategy") or {}
    limit = strategy.get("max_prototype_iterations")
    if limit is None:
        limit = (context.config.get("default_max_prototype_iterations")
                 or _machine_policy_default())
    if limit is None:
        return unknown("no max_prototype_iterations in strategy, config or machine policy")
    used = context.entity.visits("prototype")
    return Verdict(
        used < limit,
        f"{used} of {limit} prototype iterations used",
        {"iterations_used": used, "max_prototype_iterations": limit},
    )


def _machine_policy_default():
    from .machine import load_machine

    policy = load_machine("title").data.get("policy") or {}
    return policy.get("default_max_prototype_iterations")


@guard("within_timebox_tolerance")
def within_timebox_tolerance(context):
    strategy = context.entity.artifact("title-strategy")
    budget = strategy.get("timebox_days")
    if budget is None:
        return unknown("title-strategy.timebox_days is not set")

    history = context.entity.state.get("history") or []
    started = _parse_time(history[0]["entered_at"]) if history else None
    if started is None:
        return unknown("state history has no start time")

    outcome = context.entity.state.get("outcome") or {}
    elapsed = outcome.get("elapsed_days")
    if elapsed is None:
        elapsed = (context.now - started).days
    allowed = budget * context.overrun_tolerance
    return Verdict(
        elapsed <= allowed,
        f"{elapsed} days elapsed vs {allowed} allowed",
        {"elapsed_days": elapsed, "allowed_days": allowed},
    )


@guard("inputs_fresh")
def inputs_fresh(context):
    """Every pinned input still hashes to the value recorded when it was consumed.

    This is the staleness detection the provenance chain exists for, and it is the same
    computation `wgf-hash.py --check` performs - one guard, one implementation.
    """
    from .hashing import content_hash as _  # noqa: F401  (documented dependency)

    index = {}
    artifacts = []
    for path in sorted(glob.glob(os.path.join(paths.WORKSPACE, "**", "*.json"), recursive=True)):
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        if isinstance(data, dict) and isinstance(data.get("provenance"), dict):
            artifacts.append((path, data))
            index[data["provenance"].get("artifact_id")] = data

    stale = []
    for path, data in artifacts:
        for ref in _refs(data):
            target = index.get(ref.get("artifact_id"))
            if target is None:
                continue
            if ref.get("content_hash") != content_hash(target):
                stale.append(f"{paths.display(path)} -> {ref['artifact_id']}")

    if stale:
        return red(f"{len(stale)} stale pin(s): {'; '.join(stale[:3])}", stale=stale)
    return green(f"{len(artifacts)} artifacts, every pin reproduces")


def _refs(data):
    provenance = data.get("provenance") or {}
    body = {key: value for key, value in data.items() if key != "provenance"}
    yield from _walk_refs(provenance.get("inputs") or [])
    yield from _walk_refs(body)


def _walk_refs(value):
    if isinstance(value, dict):
        if "artifact_id" in value and "content_hash" in value:
            yield value
        for item in value.values():
            yield from _walk_refs(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_refs(item)


@guard("campaign_budget_approved")
def campaign_budget_approved(context):
    records = context.entity.decision_for("G7")
    if not records:
        return unknown(
            "no G7 decision-record exists. G7 spends money and never auto-approves; only "
            "the portfolio owner can answer this"
        )
    with_ceiling = [r for r in records if r.get("spend_ceiling_usd") is not None]
    if not with_ceiling:
        return red("a G7 decision-record exists but names no spend_ceiling_usd")
    newest = with_ceiling[-1]
    return green(
        f"ceiling {newest['spend_ceiling_usd']} USD approved by {newest.get('decided_by', {}).get('role')}",
        spend_ceiling_usd=newest["spend_ceiling_usd"],
    )


@guard("below_sunset_floor")
def below_sunset_floor(context):
    strategy = context.entity.artifact("title-strategy")
    floor = strategy.get("sunset_floor")
    if not floor:
        return unknown("title-strategy has no sunset_floor to compare against")

    reviews = sorted(glob.glob(os.path.join(context.entity.directory, "reviews", "*.json")))
    if not reviews:
        return unknown("no performance reviews recorded yet")

    consecutive = floor.get("consecutive_reviews", 2)
    recent = reviews[-consecutive:]
    if len(recent) < consecutive:
        return red(f"only {len(recent)} review(s); {consecutive} consecutive are required")

    breaches = []
    for path in recent:
        with open(path, encoding="utf-8") as handle:
            review = json.load(handle)
        try:
            breaches.append(evaluate(floor["when"], review).value)
        except Unevaluable as exc:
            return unknown(f"{paths.display(path)}: {exc}")
    return Verdict(
        all(breaches),
        f"{sum(breaches)} of {len(breaches)} recent reviews below the floor",
    )


# --------------------------------------------- guards whose answer is not in workspace/

def _in_the_game_repository(what, workflow=None):
    def implementation(context):
        if context.game_repo is None:
            detail = f" It is implemented by {workflow}." if workflow else ""
            return unknown(
                f"{what} is answered in the game repository, which the Factory does not "
                f"hold.{detail} Supply --game-repo to evaluate it."
            )
        return unknown(
            f"{what}: reading it from {context.game_repo} is not wired up yet"
        )

    return implementation


for _name, _what, _workflow in (
    ("ci_green", "CI on the named commit", "web-game-template/.github/workflows/ci.yml"),
    ("verify_suite_green", "the verify suite",
     "web-game-template/.github/workflows/verify.yml"),
    ("repo_created", "whether the game repository exists", None),
    ("playable_build", "whether a playable build exists", None),
    ("content_complete", "content and asset completeness", None),
    ("perf_budgets_met", "performance against the tech plan's budgets", None),
    ("no_blocking_defects", "the QA report's blocking defects", None),
    ("candidate_frozen", "whether the release manifest is frozen", None),
    ("store_metadata_complete", "store metadata and required locales", None),
    ("all_targeted_validated", "per-platform validation state", None),
    ("required_all_live", "per-platform publication state", None),
    ("none_permanently_rejected", "per-platform publication state", None),
    ("package_shaped_to_profile", "the built package against the pinned profile", None),
    ("assertions_pass", "the platform profile's blocking assertions", None),
    ("metadata_and_locales_present", "per-platform metadata and locales", None),
):
    REGISTRY[_name] = _in_the_game_repository(_what, _workflow)


@guard("platform_constraints_satisfied")
def platform_constraints_satisfied(context):
    """Deliberately UNKNOWN.

    The guard reads "every binding requirement in each targeted platform profile is
    addressed in the design", but a profile does not enumerate which of its requirements are
    binding, so there is no set to check the design against. Returning GREEN here would
    assert something nothing computed. The design records
    `platform_constraints_applied[]` for a reader; judging its completeness is the reviewer's.
    """
    design = context.entity.maybe("game-design") or {}
    applied = design.get("platform_constraints_applied") or []
    covered = sorted({entry.get("platform_id") for entry in applied})
    return unknown(
        "platform profiles do not enumerate which requirements are binding, so this cannot "
        f"be computed. The design records constraints for: {', '.join(covered) or 'none'}",
        platforms_addressed=covered,
    )


@guard("publish_authorized")
def publish_authorized(context):
    records = context.entity.decision_for("G6")
    if not records:
        return unknown(
            "no G6 decision-record exists. Publication is public, cached and indexed; it "
            "never auto-approves"
        )
    return green(f"authorized by {records[-1].get('decided_by', {}).get('role')}")

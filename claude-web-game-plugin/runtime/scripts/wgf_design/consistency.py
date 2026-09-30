"""Evaluate core/reference/design-consistency-rules.yaml against a design: the exit guard.

The rules are written against a projection, not the raw artifact:

    monetization.placements   the placement KINDS (the artifact holds objects)
    audience.*                the title strategy's audience
    asset_manifest.*          estimated from build_spec assets and audio, because at design
                              time the manifest does not exist yet - the assets step
                              produces it and the same rule is re-read against it at G3
    platform.*                one REQUIRED platform profile at a time; capabilities.ads
                              includes `iap` when the profile's capabilities.iap is true
    concept.*                 the ruleset's `concept_terms` found in the strategy's concept
                              and in the design's own statement of its game (concept_view)

A rule that reads `platform.*` is evaluated once per required platform and is breached if it
is breached on any of them. A platform whose profile holds no value for the rule (no ads,
so no interstitial interval) makes the rule inapplicable there, not passed. Anything else
that cannot be evaluated is recorded as BREACHED: "the rule held" and "the rule could not be
checked" are opposite conclusions and only one is safe to act on (see wgflib/criteria.py).
"""

import os
import re

from wgflib import paths
from wgflib.criteria import MISSING, Unevaluable, evaluate_named, resolve
from wgflib.yamllite import load_file

__all__ = ["RULES_PATH", "load_rules", "projection", "concept_view", "evaluate"]

RULES_PATH = os.path.join(paths.REFERENCE, "design-consistency-rules.yaml")


def load_rules(path=None):
    return load_file(path or RULES_PATH)


def _paths(expression):
    if isinstance(expression, dict):
        for key in ("all_of", "any_of"):
            for branch in expression.get(key) or []:
                yield from _paths(branch)
        if "not" in expression:
            yield from _paths(expression["not"])
        for key in ("left", "right_path"):
            if key in expression:
                yield expression[key]


# Features every design carries whatever the game is: they state no core mechanic.
_GENERIC_FEATURES = ("game-flow", "telemetry", "platform-integration", "localization")
# Acceptance lines the author folds in from the strategy MVP (authors.py): the strategy's
# words, not the design's, so they cannot show the design carries a mechanic.
_FROM_STRATEGY = "Strategy MVP:"


def _terms_in(text, concept_terms):
    text = text.lower()
    found = set()
    for mechanic, words in concept_terms.items():
        for word in words:
            if re.search(r"(?<![a-z0-9])" + re.escape(str(word).lower()) + r"(?![a-z0-9])", text):
                found.add(mechanic)
                break
    return found


def _strategy_concept(strategy):
    concept = strategy.get("concept") or {}
    return " ".join(str(p) for p in (strategy.get("one_liner"), concept.get("core_mechanic"),
                                     concept.get("core_loop")) if p)


def _strategy_all(strategy):
    parts = [_strategy_concept(strategy), (strategy.get("concept") or {}).get("gameplay_direction") or ""]
    parts += [str(item) for item in strategy.get("mvp") or []]
    parts += [str(item) for item in strategy.get("prototype_must_prove") or []]
    return " ".join(parts)


def _design_own(design):
    """The design's own statement of its game: core loop, the MVP mechanics it defines, the
    MVP controls. Features copied from the strategy MVP and generic features are left out."""
    parts = [design.get("core_loop") or ""]
    for feature in design.get("features") or []:
        fid = feature.get("id", "")
        if (feature.get("tier") != "mvp" or fid in _GENERIC_FEATURES
                or fid.startswith(("strategy-", "monetization-"))):
            continue
        parts += [feature.get("name", ""), feature.get("description", "")]
        parts += [a for a in feature.get("acceptance") or [] if not str(a).startswith(_FROM_STRATEGY)]
    for action in ((design.get("build_spec") or {}).get("controls") or {}).get("actions") or []:
        if action.get("tier") == "mvp":
            parts += [action.get("action", ""), action.get("touch", "")]
    return " ".join(str(p) for p in parts)


def concept_view(design, strategy, concept_terms):
    """`uncarried`: mechanics the strategy's concept names that the design's own text does not.
    `foreign`: mechanics the design's own text names that the strategy nowhere does."""
    wanted = _terms_in(_strategy_concept(strategy), concept_terms)
    named = _terms_in(_strategy_all(strategy), concept_terms)
    designed = _terms_in(_design_own(design), concept_terms)
    return {"strategy_terms": sorted(wanted), "design_terms": sorted(designed),
            "uncarried": sorted(wanted - designed), "foreign": sorted(designed - named)}


def projection(design, strategy, platform=None, concept_terms=None):
    spec = design.get("build_spec") or {}
    cost = sum(item.get("est_cost", 0) for item in (spec.get("assets") or []) + (spec.get("audio") or []))
    return {
        "monetization": {"placements": sorted({p["kind"] for p in design["monetization"]["placements"]})},
        "session": design.get("session") or {},
        "retention": design.get("retention") or {},
        "scope": design.get("scope") or {},
        "audience": strategy.get("audience") or {},
        "asset_manifest": {"total_est_cost": cost},
        "platform": _platform_view(platform),
        "concept": concept_view(design, strategy, concept_terms or {}),
    }


def _platform_view(platform):
    """The profile, with `iap` counted as an offered placement when the platform sells."""
    if platform is None:
        return {}
    view = dict(platform.profile)
    view["capabilities"] = dict(view.get("capabilities") or {}, ads=platform.placements)
    return view


def _evaluate_once(rule, context):
    try:
        return evaluate_named(rule, context)
    except Unevaluable as exc:
        return {"criterion_id": rule["id"], "measured": None, "breached": True,
                "note": f"could not be evaluated, recorded as breached: {exc}"}


def _measured(value):
    if isinstance(value, dict):
        # criterionResult.measured is a scalar or an array; a multi-path reading becomes a
        # list of "path=value" strings so nothing is dropped.
        return [f"{k}={v}" for k, v in sorted(value.items())]
    return value


def evaluate(design, strategy, platforms, evaluated_at, rules=None):
    """Return the `consistency` block for `design`."""
    ruleset = rules or load_rules()
    terms = ruleset.get("concept_terms") or {}
    required = [p for p in platforms if p.required]
    results = []
    blocking_breached = []

    for rule in ruleset["rules"]:
        reads_platform = any(p.startswith("platform.") for p in _paths(rule["when"]))
        if not reads_platform:
            result = _evaluate_once(rule, projection(design, strategy, concept_terms=terms))
        else:
            per_platform, notes, breached = [], [], False
            for platform in required:
                context = projection(design, strategy, platform, concept_terms=terms)
                absent = [p for p in _paths(rule["when"])
                          if p.startswith("platform.") and resolve(p, context) in (MISSING, None)]
                if absent:
                    notes.append(f"{platform.id}: not applicable ({', '.join(absent)} unset)")
                    continue
                outcome = _evaluate_once(rule, context)
                per_platform.append(outcome)
                if outcome["breached"]:
                    breached = True
                    notes.append(f"{platform.id}: breached" + (f" ({outcome['note']})" if outcome.get("note") else ""))
                else:
                    notes.append(f"{platform.id}: held")
            if not required:
                notes.append("no required platform")
            chosen = next((o for o in per_platform if o["breached"]), per_platform[0] if per_platform else None)
            result = {"criterion_id": rule["id"],
                      "measured": chosen["measured"] if chosen else None,
                      "breached": breached,
                      "note": "; ".join(notes)}
        result["measured"] = _measured(result.get("measured"))
        if result.get("note") is None:
            result.pop("note", None)
        results.append(result)
        if result["breached"] and rule.get("severity") == "blocking":
            blocking_breached.append(rule["id"])

    warnings = [r["criterion_id"] for r, rule in zip(results, ruleset["rules"])
                if r["breached"] and rule.get("severity") != "blocking"]
    block = {
        "status": "fail" if blocking_breached else "pass",
        "evaluated_at": evaluated_at,
        "ruleset_version": str(ruleset.get("version")),
        "rule_results": results,
        # Set at G3 by a person, never here: a warning acknowledged by its author is a comment.
        "warnings_acknowledged": False,
    }
    return block, blocking_breached, warnings

"""Feature evaluation: no feature the brief, the strategy or the genre names drops silently.

A brief asked for "an endless mode for replay" and the design tiered it `optional` with no
word; another asked for "a time-trial mode" and the design never listed one. Neither is a
mechanic, so the consistency rules could not see either (docs/quality-gap-audit-2026-10.md,
finding 6, WS-5). This module holds a design to core/reference/feature-catalogue.yaml:

    features.brief_accounted        every catalogue feature the brief names is a feature with
                                    `catalogue`, `source: brief` and an evaluation
    features.strategy_accounted     the same for one the title strategy names (one-liner,
                                    concept, MVP, prototype_must_prove, out_of_scope)
    features.family_evaluated       every feature the catalogue marks `expected` for the
                                    design's genre family is evaluated - included, deferred or
                                    cut with a reason, never added blindly
    features.decisions_coherent     an `include` is mvp or post-mvp, a `later` or `cut` is
                                    optional; a cut is in scope.tiers.out_of_scope; a feature
                                    from the brief, the strategy or the catalogue carries an
                                    evaluation; a `catalogue` id is one the catalogue holds
    features.platform_supported     an included feature resting on a platform capability with
                                    no local fallback is supported by every required platform,
                                    and evaluation.platform_support says what the profiles say

Recognising a feature is phrase matching against the catalogue's `terms`: a brief that names
a feature the catalogue has no entry for is not seen, and the answer is a catalogue entry, not
a looser match. The built-in author's evaluations (`evaluate_for_author`) are the honest
default it can give - `include` where its archetype builds the feature, `cut` where the
strategy or the platforms rule it out, `later` otherwise - and the agent author is handed
the same candidates (`candidates`) to decide for itself.
"""

import os
import re

from wgflib import paths
from wgflib.yamllite import load_file

__all__ = ["CATALOGUE_PATH", "RULES", "load_catalogue", "catalogue_record", "named",
           "first_named", "candidates", "platform_support", "check", "evaluate_for_author",
           "cut_list"]

CATALOGUE_PATH = os.path.join(paths.REFERENCE, "feature-catalogue.yaml")

RULES = (
    ("features.brief_accounted",
     "every catalogue feature the brief names is a feature with catalogue, source brief and an "
     "evaluation (include, later or cut, with a reason)"),
    ("features.strategy_accounted",
     "every catalogue feature the title strategy names is a feature with catalogue, source "
     "strategy (or brief) and an evaluation"),
    ("features.family_evaluated",
     "every catalogue feature marked expected for the design's genre family is evaluated"),
    ("features.decisions_coherent",
     "include is tiered mvp or post-mvp, later and cut are optional, a cut is in "
     "scope.tiers.out_of_scope, a brief/strategy/catalogue feature carries an evaluation"),
    ("features.platform_supported",
     "an included feature that needs a platform capability with no fallback is supported by "
     "every required platform, and platform_support states the profiles' answer"),
)

INCLUDED_TIERS = ("mvp", "post-mvp")
# Features every design carries whatever the game is, and the ones copied from the strategy
# MVP or a monetization touchpoint: never the feature a catalogue entry stands for
# (platform-integration's "cloud save" is the SDK wiring, not the feature).
GENERIC_FEATURES = ("game-flow", "telemetry", "platform-integration", "localization")
_NEVER_HOLDERS = ("monetization-", "strategy-")
_EVALUATED_SOURCES = ("brief", "strategy", "catalogue")


def load_catalogue(path=None):
    return load_file(path or CATALOGUE_PATH)


def catalogue_record(catalogue):
    return {"id": "feature-catalogue", "version": str(catalogue.get("version"))}


def _entries(catalogue):
    return [e for e in (catalogue or {}).get("features") or [] if isinstance(e, dict)]


def _normal(text):
    return re.sub(r"\s+", " ", str(text or "").lower().replace("-", " ").replace("_", " "))


def _positions(text, catalogue):
    """{catalogue id: (where its first term occurs, the term)} for every feature `text` names."""
    text = _normal(text)
    found = {}
    for entry in _entries(catalogue):
        for term in entry.get("terms") or []:
            match = re.search(r"(?<![a-z0-9])" + re.escape(_normal(term)) + r"(?![a-z0-9])", text)
            if match and (entry["id"] not in found or match.start() < found[entry["id"]][0]):
                found[entry["id"]] = (match.start(), str(term))
    return found


def named(text, catalogue):
    """{catalogue id: the term that named it} for every catalogue feature `text` names."""
    return {fid: term for fid, (_at, term) in _positions(text, catalogue).items()}


def first_named(text, catalogue):
    """The catalogue id `text` names first, or None. An exclusion excludes the feature it
    names first: "Leaderboards beyond the personal best" cuts the leaderboard and keeps the
    personal best."""
    found = _positions(text, catalogue)
    return min(found, key=lambda fid: found[fid][0]) if found else None


def _strategy_text(strategy):
    concept = strategy.get("concept") or {}
    parts = [strategy.get("one_liner"), concept.get("core_mechanic"), concept.get("core_loop"),
             concept.get("gameplay_direction")]
    parts += [str(item) for item in strategy.get("mvp") or []]
    parts += [str(item) for item in strategy.get("prototype_must_prove") or []]
    parts += [str(item) for item in strategy.get("out_of_scope") or []]
    return " ".join(str(p) for p in parts if p)


def candidates(strategy, family, catalogue, brief=None):
    """The catalogue features a design must evaluate, in catalogue order:
    [{id, name, source, why}] - `source` brief, strategy or catalogue (the family expects it),
    the first that applies."""
    strategy = strategy or {}
    brief = brief if brief is not None else strategy.get("brief")
    by_brief = named(brief or "", catalogue)
    by_strategy = named(_strategy_text(strategy), catalogue)
    out = []
    for entry in _entries(catalogue):
        fid = entry["id"]
        if fid in by_brief:
            source, why = "brief", f"the brief names it ({by_brief[fid]!r})"
        elif fid in by_strategy:
            source, why = "strategy", f"the title strategy names it ({by_strategy[fid]!r})"
        elif family and (entry.get("families") or {}).get(family) == "expected":
            source, why = "catalogue", f"the {family} family expects it"
        else:
            continue
        out.append({"id": fid, "name": entry.get("name") or fid, "source": source, "why": why})
    return out


def _supports(platform, capability):
    value = platform.get("capabilities", capability)
    return bool(value) and value != "none"


def platform_support(entry, platforms):
    """all | some | local | none for `entry` across the required platforms."""
    need = entry.get("platform") or {}
    capability = need.get("capability")
    required = [p for p in platforms or [] if p.required]
    if not capability or not required:
        return "all"
    supported = [p for p in required if _supports(p, capability)]
    if len(supported) == len(required):
        return "all"
    if supported:
        return "some"
    return "local" if need.get("fallback") == "local" else "none"


def _blocks(entry, platforms):
    """The required platforms an included `entry` cannot run on: it needs a capability they
    lack and has no local fallback."""
    need = entry.get("platform") or {}
    if not need.get("capability") or need.get("fallback") == "local":
        return []
    return [p.id for p in platforms or [] if p.required and not _supports(p, need["capability"])]


def _result(rule_id, measured, problems, note):
    return {"criterion_id": rule_id, "measured": measured, "breached": bool(problems),
            "note": note if not problems else "; ".join(problems[:4])}


def check(design, strategy=None, platforms=(), catalogue=None):
    """(problems, rule_results). Problems are what an author that repairs is shown, and what
    fails the step; the results go into the design's consistency block."""
    catalogue = catalogue or load_catalogue()
    strategy = strategy or {}
    entries = {e["id"]: e for e in _entries(catalogue)}
    features = [f for f in design.get("features") or [] if isinstance(f, dict)]
    by_catalogue = {}
    for feature in features:
        if feature.get("catalogue"):
            by_catalogue.setdefault(feature["catalogue"], []).append(feature)
    family = (design.get("genre") or {}).get("family")
    wanted = candidates(strategy, family, catalogue, design.get("brief") or strategy.get("brief"))

    found = {rule_id: [] for rule_id, _ in RULES}
    rule_of = {"brief": "features.brief_accounted", "strategy": "features.strategy_accounted",
               "catalogue": "features.family_evaluated"}
    for want in wanted:
        carried = [f for f in by_catalogue.get(want["id"], []) if f.get("evaluation")]
        rule_id = rule_of[want["source"]]
        if not carried:
            found[rule_id].append(
                f"features: {want['why']} - {want['name']!r} (catalogue {want['id']}) - and no "
                f"feature evaluates it: list it with catalogue: {want['id']}, source: "
                f"{want['source']} and an evaluation - include it (tier mvp or post-mvp), defer "
                f"it (later) or cut it, with the reason")
            continue
        if want["source"] in ("brief", "strategy"):
            allowed = ("brief",) if want["source"] == "brief" else ("brief", "strategy")
            if not any(f.get("source") in allowed for f in carried):
                found[rule_id].append(
                    f"features.{carried[0].get('id')}: {want['why']}, so its source is "
                    f"{' or '.join(allowed)}, not {carried[0].get('source') or 'unset'}")

    out_of_scope = " ".join(_normal(o.get("item")) for o in
                            ((design.get("scope") or {}).get("tiers") or {}).get("out_of_scope")
                            or [] if isinstance(o, dict))
    coherent = found["features.decisions_coherent"]
    supported = found["features.platform_supported"]
    for feature in features:
        fid = feature.get("id")
        evaluation = feature.get("evaluation")
        if feature.get("catalogue") and feature["catalogue"] not in entries:
            coherent.append(f"features.{fid}: catalogue {feature['catalogue']!r} is not a "
                            f"feature of core/reference/feature-catalogue.yaml")
        if not isinstance(evaluation, dict):
            if feature.get("source") in _EVALUATED_SOURCES:
                coherent.append(f"features.{fid}: source {feature['source']} but no "
                                f"evaluation - a feature someone asked for is included, "
                                f"deferred or cut with a reason")
            continue
        decision, tier = evaluation.get("decision"), feature.get("tier")
        if decision == "include" and tier not in INCLUDED_TIERS:
            coherent.append(f"features.{fid}: decision include but tier {tier} - an included "
                            f"feature is mvp or post-mvp; optional is `later`")
        if decision in ("later", "cut") and tier in INCLUDED_TIERS:
            coherent.append(f"features.{fid}: decision {decision} but tier {tier} - a deferred "
                            f"or cut feature is optional, or it is built")
        if decision == "cut" and _normal(feature.get("name")) not in out_of_scope:
            coherent.append(f"features.{fid}: cut but not in scope.tiers.out_of_scope - list "
                            f"{feature.get('name')!r} there with the reason")
        entry = entries.get(feature.get("catalogue"))
        if entry is None:
            continue
        expected = platform_support(entry, platforms)
        stated = evaluation.get("platform_support")
        if stated is not None and stated != expected:
            supported.append(f"features.{fid}: platform_support {stated} but the required "
                             f"platforms' profiles say {expected}")
        lacking = _blocks(entry, platforms)
        if decision == "include" and lacking:
            capability = entry["platform"]["capability"]
            supported.append(f"features.{fid}: included, but {', '.join(lacking)} (required) "
                             f"has no {capability} and the feature has no local fallback - "
                             f"cut it or defer it (later), with that reason")

    measured = {
        "features.brief_accounted": sorted(w["id"] for w in wanted if w["source"] == "brief"),
        "features.strategy_accounted": sorted(w["id"] for w in wanted
                                              if w["source"] == "strategy"),
        "features.family_evaluated": sorted(w["id"] for w in wanted
                                            if w["source"] == "catalogue"),
        "features.decisions_coherent": len([f for f in features if f.get("evaluation")]),
        "features.platform_supported": sorted(
            f["id"] for f in features
            if (f.get("evaluation") or {}).get("decision") == "include" and f.get("catalogue")),
    }
    notes = {
        "features.brief_accounted": "catalogue features the brief names, each evaluated",
        "features.strategy_accounted": "catalogue features the strategy names, each evaluated",
        "features.family_evaluated": (f"catalogue features the {family} family expects, each "
                                      f"evaluated" if family else
                                      "no genre family: nothing is expected"),
        "features.decisions_coherent": "evaluated features, decisions agree with tiers",
        "features.platform_supported": "included catalogue features, each supported",
    }
    problems, results = [], []
    for rule_id, _meaning in RULES:
        problems += found[rule_id]
        results.append(_result(rule_id, measured[rule_id], found[rule_id], notes[rule_id]))
    return problems, results


def cut_list(design):
    """The features the design evaluated and did not include: [(name, decision, reason)]."""
    return [(f.get("name") or f.get("id"), f["evaluation"]["decision"],
             f["evaluation"].get("reason") or "")
            for f in design.get("features") or []
            if isinstance(f, dict) and isinstance(f.get("evaluation"), dict)
            and f["evaluation"].get("decision") in ("cut", "later")]


# -- the built-in author --------------------------------------------------------------------

def _matches(entry, text):
    return bool(named(text, {"features": [entry]}))


def _evaluation(entry, platforms, decision, reason):
    return {"player_value": entry.get("player_value", "medium"),
            "cost_h": entry.get("cost_h", 0),
            "platform_support": platform_support(entry, platforms),
            "monetization_impact": entry.get("monetization_impact", "none"),
            "qa_cost": entry.get("qa_cost", "medium"),
            "decision": decision, "reason": reason}


def evaluate_for_author(features, strategy, family, platforms, exclusions=(), catalogue=None):
    """Evaluate every candidate (`candidates`) on a draft's `features`, in place: the built-in
    author's, and the starting draft of an agent's revision. A cut reaches
    scope.tiers.out_of_scope through compose.finalize.

    A candidate one of the features already builds (its name or description names it;
    generic, strategy-MVP and monetization features never stand for one) is that feature:
    `include` if tiered mvp or post-mvp, `later` if optional. Otherwise a new optional entry
    records it: `cut` when the strategy excludes it (the `exclusions` entry, (item, why),
    that names it first) or it cannot run on a required platform, `later` when only a
    designer can decide it. Nothing is added to the game because a list has it."""
    catalogue = catalogue or load_catalogue()
    entries = {e["id"]: e for e in _entries(catalogue)}
    taken = {f["id"] for f in features}
    for want in candidates(strategy, family, catalogue):
        entry = entries[want["id"]]
        why = want["why"][0].upper() + want["why"][1:]
        if any(f.get("catalogue") == want["id"] for f in features):
            continue
        holder = next((f for f in features
                       if f.get("id") not in GENERIC_FEATURES
                       and not str(f.get("id")).startswith(_NEVER_HOLDERS)
                       and not f.get("catalogue")
                       and _matches(entry, " ".join([f.get("name", ""),
                                                     f.get("description", "")]))), None)
        lacking = _blocks(entry, platforms)
        if holder is not None:
            built = holder["tier"] in INCLUDED_TIERS
            holder["catalogue"] = want["id"]
            holder["source"] = want["source"] if want["source"] != "catalogue" else "design"
            holder["evaluation"] = _evaluation(
                entry, platforms, "include" if built else "later",
                f"{why}; the design builds it as {holder['name']!r} "
                f"({holder['tier']})." if built else
                f"{why}; the design lists it as {holder['name']!r} but "
                f"commits to nothing (optional): a candidate for production after G4.")
            continue
        exclusion = next(((item, why) for item, why in exclusions or ()
                          if first_named(item, catalogue) == want["id"]), None)
        if exclusion:
            decision = "cut"
            reason = (f"{why}, and the title strategy excludes it "
                      f"({exclusion[0]}: {exclusion[1]}).")
        elif lacking:
            decision = "cut"
            reason = (f"{why}, but {', '.join(lacking)} (required) offers "
                      f"no {entry['platform']['capability']} and it has no local fallback.")
        else:
            decision = "later"
            reason = (f"{why}. Not designed yet: at about {entry.get('cost_h', 0)} h it is "
                      f"deferred, not dropped - a designer (the agent author), a superseding "
                      f"strategy or production after G4 decides it.")
        fid = want["id"] if want["id"] not in taken else f"catalogue-{want['id']}"
        taken.add(fid)
        features.append({"id": fid, "name": entry["name"], "tier": "optional",
                         "description": entry.get("description") or entry["name"],
                         "source": want["source"], "catalogue": want["id"],
                         "evaluation": _evaluation(entry, platforms, decision, reason)})

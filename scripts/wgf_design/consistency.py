"""Evaluate core/reference/design-consistency-rules.yaml against a design: the exit guard.

The rules are written against a projection, not the raw artifact:

    monetization.placements   the placement KINDS (the artifact holds objects)
    audience.*                the title strategy's audience
    asset_manifest.*          estimated from build_spec assets and audio, because at design
                              time the manifest does not exist yet - the assets step
                              produces it and the same rule is re-read against it at G3
    platform.*                one REQUIRED platform profile at a time; capabilities.ads
                              includes `iap` when the profile's capabilities.iap is true
    concept.*                 the brief, the strategy and the design as mechanic ids of
                              core/reference/mechanic-lexicon.yaml (concept_view): what the
                              brief and strategy imply against what the design builds - its
                              build_spec mechanics, the content units that use them and the
                              controls that drive them - and the pillars they realize
    commitments.*             the counts, structure and modes the brief and the strategy state
                              (core/reference/brief-commitments.yaml) and those the design
                              does not plan (wgf_design/commitments.py)
    adopted.*                 game-design.existing_content - what an adopted repository
                              already ships - and what the design plans fewer of
                              (wgf_design/existing.py)
    knowledge.*               the design's decision trace (`knowledge_applied`) against the
                              Factory knowledge the author was given and the results of every
                              rule evaluated before it (wgf_design/knowledge.py trace_view): a
                              rule reading `knowledge.` is evaluated after the rules listed
                              before it, so the ruleset lists it last
    introductions.*           what each content unit debuts - the elements, mechanics and
                              introductions no earlier unit named - and every unit after the
                              opening one that debuts more than one (content.introductions_view)

A rule that reads `platform.*` is evaluated once per required platform and is breached if it
is breached on any of them. A platform whose profile holds no value for the rule (no ads,
so no interstitial interval) makes the rule inapplicable there, not passed. Anything else
that cannot be evaluated is recorded as BREACHED: "the rule held" and "the rule could not be
checked" are opposite conclusions and only one is safe to act on (see wgflib/criteria.py).
"""

import os

from wgflib import mechanics, paths

from . import commitments as brief_commitments
from . import content as content_rules
from . import existing
from wgflib.criteria import MISSING, Unevaluable, evaluate_named, resolve
from wgflib.yamllite import load_file

__all__ = ["RULES_PATH", "load_rules", "load_lexicon", "load_commitments", "projection",
           "concept_view", "evaluate", "breach_problems"]

RULES_PATH = os.path.join(paths.REFERENCE, "design-consistency-rules.yaml")
# The same file relative to the Factory root: what a run pins (wgflib.workflow.references).
RULES_FILE = "core/reference/design-consistency-rules.yaml"


def load_rules(path=None):
    return load_file(path or RULES_PATH)


def load_lexicon(ruleset=None):
    """The mechanic lexicon the ruleset pins (`lexicon: {id, version}`). A lexicon at another
    version is refused: the words decide what is foreign, so changing them is a ruleset change
    and is recorded as one."""
    ruleset = ruleset if ruleset is not None else load_rules()
    pin = ruleset.get("lexicon")
    if not isinstance(pin, dict):
        return {}
    lexicon = mechanics.load(os.path.join(paths.REFERENCE, f"{pin.get('id')}.yaml"))
    if str(lexicon.get("version")) != str(pin.get("version")):
        raise ValueError(f"design-consistency-rules pins {pin.get('id')} {pin.get('version')}, "
                         f"the file is {lexicon.get('version')}: bump the ruleset with it")
    return lexicon


def load_commitments(ruleset=None):
    """The brief-commitments vocabulary the ruleset pins (`commitments: {id, version}`),
    refused at another version like the lexicon. {} when the ruleset pins none."""
    ruleset = ruleset if ruleset is not None else load_rules()
    pin = ruleset.get("commitments")
    if not isinstance(pin, dict):
        return {}
    data = brief_commitments.load(os.path.join(paths.REFERENCE, f"{pin.get('id')}.yaml"))
    if str(data.get("version")) != str(pin.get("version")):
        raise ValueError(f"design-consistency-rules pins {pin.get('id')} {pin.get('version')}, "
                         f"the file is {data.get('version')}: bump the ruleset with it")
    return data


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


def _strategy_concept(strategy):
    concept = strategy.get("concept") or {}
    return " ".join(str(p) for p in (strategy.get("one_liner"), concept.get("core_mechanic"),
                                     concept.get("core_loop")) if p)


def _strategy_all(strategy):
    """Everything the brief and the strategy say the game is: what a design may build."""
    concept = strategy.get("concept") or {}
    parts = [str(strategy.get("brief") or ""), _strategy_concept(strategy),
             concept.get("gameplay_direction") or ""]
    model = concept.get("content_model") or {}
    parts += [str(model.get(k) or "") for k in ("unit_kind", "progression", "family")]
    parts += [str(item) for item in strategy.get("mvp") or []]
    parts += [str(item) for item in strategy.get("prototype_must_prove") or []]
    return " ".join(parts)


def _mvp(items):
    return [i for i in items or [] if isinstance(i, dict) and i.get("tier") == "mvp"]


def concept_view(design, strategy, lexicon=None):
    """The brief, the strategy and the design as mechanic ids (core/reference/mechanic-lexicon.yaml).

    `implied`    the ids the brief and the strategy name anywhere: what the design may build.
    `uncarried`  defining and detail ids the strategy's concept (one-liner, core mechanic,
                 core loop) names that no MVP mechanic (its name, description or rules) or
                 MVP control of the design builds.
    `foreign`    defining ids of the design's core mechanics - an MVP mechanic a content unit
                 uses, a control drives or the design calls `core`; every MVP mechanic when the
                 design lists no content - and of its MVP controls, that nothing implies; plus
                 `<id> (unrecognised)` for a mechanic a control drives that the lexicon does not
                 know and whose own words the brief and strategy never use. A paraphrase is the
                 same id and never foreign; a renamed mechanic is still the id it is, or it is
                 unrecognised.
    `pillars_asked` / `pillars_unrealized`  the lexicon pillars the brief, the strategy or the
                 design's pillars name, and those no MVP mechanic a content unit uses builds a
                 `realized_by` id of."""
    lexicon = lexicon if lexicon is not None else mechanics.load()
    spec = design.get("build_spec") or {}
    built = _mvp(spec.get("mechanics"))
    actions = _mvp((spec.get("controls") or {}).get("actions"))
    units = [u for u in (spec.get("content") or {}).get("units") or [] if isinstance(u, dict)]
    used = {m for u in units for m in u.get("mechanics") or []}
    driven = {a.get("mechanic") for a in actions if a.get("mechanic")}
    # What a mechanic IS (its id and name; its description when they name nothing) decides
    # foreign. What it BUILDS - the same plus its description and rules, its specification -
    # decides what it carries and which pillar it realizes: "each gate adds time to the
    # clock" builds a clock into the gates.
    ids = {m.get("id"): mechanics.mechanic_ids(m, lexicon) for m in built}
    builds = {m.get("id"): ids[m.get("id")] | mechanics.ids_in(
        " ".join([str(m.get("description") or "")] + [str(r) for r in m.get("rules") or []]),
        lexicon) for m in built}

    def is_core(m):
        return (not units or m.get("id") in used or m.get("id") in driven
                or m.get("progression_role") == "core")

    allowed_text = _strategy_all(strategy)
    implied = mechanics.ids_in(allowed_text, lexicon)
    wanted = {i for i in mechanics.ids_in(_strategy_concept(strategy), lexicon)
              if mechanics.kind(i, lexicon) != "generic"}
    carried = set().union(*builds.values()) if builds else set()
    for action in actions:
        carried |= mechanics.ids_in(f"{action.get('action', '')} {action.get('touch', '')}",
                                    lexicon)

    core_ids = set()
    for m in built:
        if is_core(m):
            core_ids |= ids[m.get("id")]
    for action in actions:
        core_ids |= mechanics.ids_in(action.get("action", ""), lexicon)
    foreign = sorted(i for i in core_ids - implied if mechanics.kind(i, lexicon) == "defining")
    words = mechanics.stems(allowed_text)
    for m in built:
        own = mechanics.stems(f"{m.get('id', '')} {m.get('name', '')}")
        if m.get("id") in driven and not ids[m.get("id")] and not own & words:
            foreign.append(f"{m.get('id')} (unrecognised)")

    pillars = lexicon.get("pillars") or {}
    pillar_text = " ".join([allowed_text] + [str(p) for p in design.get("pillars") or []])
    asked = sorted(pid for pid, entry in pillars.items()
                   if mechanics.phrases_in(pillar_text, (entry or {}).get("phrases")))
    in_play = set()
    for m in built:
        if not units or m.get("id") in used:
            in_play |= builds[m.get("id")]
    unrealized = [pid for pid in asked
                  if not in_play & set((pillars[pid] or {}).get("realized_by") or [])]

    return {"strategy_terms": sorted(wanted), "design_terms": sorted(carried | core_ids),
            "implied": sorted(implied),
            "uncarried": sorted(wanted - carried),
            "foreign": foreign,
            "pillars_asked": asked, "pillars_unrealized": unrealized}


def projection(design, strategy, platform=None, lexicon=None, concept=None, stated=None,
               trace=None):
    spec = design.get("build_spec") or {}
    cost = sum(item.get("est_cost", 0) for item in (spec.get("assets") or []) + (spec.get("audio") or []))
    return {
        "monetization": {"placements": sorted({p["kind"] for p in design["monetization"]["placements"]})},
        "session": design.get("session") or {},
        "retention": design.get("retention") or {},
        "scope": design.get("scope") or {},
        "genre": design.get("genre") or {},
        "audience": strategy.get("audience") or {},
        "asset_manifest": {"total_est_cost": cost},
        "platform": _platform_view(platform),
        "concept": concept if concept is not None else concept_view(design, strategy, lexicon),
        "commitments": stated if stated is not None else brief_commitments.view(design, strategy),
        "adopted": existing.floor_view(design),
        "introductions": content_rules.introductions_view(design),
        "knowledge": trace if trace is not None else {"present": False, "problems": []},
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


def evaluate(design, strategy, platforms, evaluated_at, rules=None, knowledge=None):
    """Return the `consistency` block for `design`. `knowledge`: the Factory knowledge the
    author was given (wgf_design/knowledge.py provisional), which the design's decision
    trace is held against; None when it could not be read."""
    ruleset = rules or load_rules()
    concept = concept_view(design, strategy, load_lexicon(ruleset))
    vocabulary = load_commitments(ruleset)
    stated = (brief_commitments.view(design, strategy, vocabulary) if vocabulary
              else {"stated": [], "unmet": [], "deferred": []})
    required = [p for p in platforms if p.required]
    results = []
    blocking_breached = []

    for rule in ruleset["rules"]:
        reads_platform = any(p.startswith("platform.") for p in _paths(rule["when"]))
        trace = None
        if any(p.startswith("knowledge.") for p in _paths(rule["when"])):
            # The trace is judged on the results of every rule evaluated before it.
            from . import knowledge as design_knowledge
            trace = design_knowledge.trace_view(design, knowledge, results)
        if not reads_platform:
            result = _evaluate_once(rule, projection(design, strategy, concept=concept,
                                                     stated=stated, trace=trace))
        else:
            per_platform, notes, breached = [], [], False
            for platform in required:
                context = projection(design, strategy, platform, concept=concept,
                                     stated=stated)
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
        if rule["id"] == "brief_commitments_met" and stated["stated"]                 and not result["breached"] and not result.get("note"):
            # What was held, so a pass says what the brief committed to - and, at a tier the
            # counts do not bind, what the release must still plan.
            result["note"] = "stated: " + "; ".join(stated["stated"]) + (
                f". Not binding at tier {stated.get('tier') or 'unstated'}, owed by the "
                f"release: " + "; ".join(stated["deferred"]) if stated.get("deferred") else "")
        if rule["id"] == "content.introductions_one_at_a_time" and not result["breached"] \
                and not result.get("note"):
            view = content_rules.introductions_view(design)
            result["note"] = (f"{view['units']} unit(s); after the opening one, none debuts more "
                              "than one element" if view["units"] else
                              "the design lists no content units: nothing debuts, the rule holds")
        if trace is not None and not result.get("note"):
            result["note"] = ("no decision trace (knowledge_applied): nothing claimed, nothing "
                              "to contradict" if not trace["present"] else
                              f"{trace['entries']} trace entr(ies), {len(trace['applied'])} "
                              f"applied" + (f"; contradicted: {', '.join(trace['contradicted'])}"
                                            if trace["contradicted"] else ""))
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


def breach_problems(block, blocking, rules=None):
    """The blocking breaches in `block`, as problems an author that repairs its draft can act
    on: the rule's label, what was measured against what, and that the answer is to cut scope.

    A breach is the one invalid-design class the author was never shown (the step failed on it
    immediately), so an agent author could not fix a design whose only fault was three assets
    too many - the run died at `descope` with the fix one round away."""
    ruleset = rules or load_rules()
    labels = {rule["id"]: rule.get("label") or rule["id"] for rule in ruleset["rules"]}
    problems = []
    for result in block.get("rule_results") or []:
        rule_id = result["criterion_id"]
        if rule_id not in blocking:
            continue
        measured = result.get("measured")
        if isinstance(measured, (list, tuple)):
            measured = ", ".join(str(m) for m in measured)
        detail = f": measured {measured}" if measured else ""
        note = f" ({result['note']})" if result.get("note") else ""
        problems.append(f"consistency {rule_id} - {labels.get(rule_id, rule_id)}{detail}{note}. "
                        f"Cut scope to hold the rule; never relax the rule.")
    return problems

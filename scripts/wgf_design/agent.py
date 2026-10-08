"""The `agent` design author: an agent host writes the design draft; the module judges it.

Opt-in. An installation selects it in workspace/config/factory.yaml:

    factory:
      design:
        author: agent
        agent:
          argv: [...]                # the host's non-interactive command; placeholders below
          timeout_seconds: 1800      # wall clock
          idle_timeout_seconds: 600  # no output for this long ends the attempt
          draft_from: file           # file: the agent edits {draft}, seeded with the
                                     # starting (or, on a repair, the previous) draft
                                     # stdout: it prints the draft JSON last

`argv` placeholders, substituted per element and never re-formatted: {request} (the request
JSON: strategy, resolved platforms, title id, and the starting draft - the built-in
archetype's draft as a schema-shaped starting point for a first design, or, when the run
already holds a game-design, that design to revise, with the strategy's change since it in
`revision`: revision.py; on a design-gap repair, the gaps first, then the instructions, with the
previous design - the one the gaps were found in - and the strategy as files of their own,
named by path; on a repair round of a gap visit, the validation problems before the gaps), {draft}
(where to write the draft JSON), {prompt} (a
one-paragraph instruction), and {request_rule} / {draft_rule}: the same paths as a host
permission rule names them, `//` and the POSIX form (`//c/Users/...` on Windows;
wgflib.permpath) - `Edit({draft_rule})` restricts the agent's writes to the draft on every
host OS. The older `Edit(/{draft})` is read as `Edit({draft_rule})`.

The agent only writes a DRAFT. Everything after it is the design module's, unchanged: platform
absorption and tier derivation (`finalize`), the buildability check and the consistency rules,
including the `descope` route. An agent cannot mark its own homework, and nothing here
relaxes a check to let its draft through.

The host runs with the allowlisted agent environment (wgflib.agentenv), exactly as the
developer and the reviewer do: nothing of the Factory's own environment beyond the
allowlist and `factory.agents.env_passthrough` (where the host's credential is named).

Outcomes: a draft whose shape is wrong (not JSON, a missing section) is an `AuthorError` -
not retryable, the same draft would come back. A draft that is well-shaped but makes an
invalid design - a value the game-design schema does not allow, a state machine buildability
refuses - is shown to the agent with exactly those problems and the previous draft, and
asked again (the design step's `MAX_REPAIR_ROUNDS`); every round is judged like the first,
and one still invalid after the last fails the step, not retryably. The request names the
schema (`schema`) so the agent can keep to it in the first place. A host that fails, times out or goes silent
raises `AgentRunFailed`, which the engine retries like any other transient failure. Not
configured is an `AuthorError`.

A draft left unchanged is an `AuthorError` - except on a design-gap visit, which is judged
against the design the gaps were found in, never against the draft a round (or a resumed
execution) was seeded with: a repair round's draft already answers the gaps, so one returned
as it was goes back to the step's checks. A gap visit fails as unchanged only when its draft
equals that design and some gap is neither answered nor marked answered: the agent may name a
gap the design already answers, or one made obsolete since it was raised, in the draft's
top-level `gaps_answered` (id and reason); the list is removed before the step judges the
draft and kept, per visit, in `<visit>-gaps-answered.json`.
"""

import copy
import json
import os

from wgflib import agentenv, genre_models, paths, permpath, procs, quality_bar

from . import commitments as brief_commitments
from . import content as content_rules
from . import features as feature_check
from . import identity
from .authors import (ArchetypeAuthor, AuthorError, DesignAuthor, register_author,
                      split_reason)
from .depth import load_rules as load_depth_rules
from .experience import load_rules
from .revision import as_draft

__all__ = ["AgentAuthor", "AgentRunFailed", "REQUIRED_KEYS", "BUILD_SPEC_KEYS",
           "check_shape"]

# Exactly what the built-in author returns, so `finalize` and `buildability` never meet a
# shape they index into blindly.
REQUIRED_KEYS = ("fantasy", "core_loop", "genre", "pillars", "engine", "features", "scope",
                 "session", "retention", "monetization", "progression", "difficulty",
                 "controls", "ux", "art_direction", "audio_direction", "build_spec",
                 "open_questions")
BUILD_SPEC_KEYS = ("mechanics", "content", "controls", "player_goals", "progression",
                   "difficulty", "mastery", "game_states", "screens", "hud", "menus",
                   "tutorial", "rewards", "failure", "session_flow",
                   "monetization_touchpoints", "assets", "audio", "responsive",
                   "visual_identity", "experience")

# What the agent is asked to do. The content is the design: a game is the units a player
# plays, not a loop and the word "harder".
_DESIGN = (
    "You are the game designer for this title. Read the request at {request}: the approved "
    "strategy, the platform profiles, the genre model the content is held to, and a starting "
    "draft in exactly the shape required. Design the game. State its genre family and ending, "
    "and the full build_spec.content list: every unit with purpose, objective, the mechanics "
    "it uses and introduces, difficulty values on the family's axes, duration, success and "
    "failure in the player's words, and acceptance a bot can check; the progression model, "
    "the difficulty axes and the mastery statement. Improve the core loop, feel, onboarding, "
    "rewards, failure feedback, audio and visual identity. Never add a monetization placement "
    "or a platform the strategy did not approve; mechanics and content the strategy's "
    "concept, content_model and MVP name are yours to specify in full."
)
PROMPT = (
    _DESIGN
    + " {draft} already holds the starting draft (when you are asked again, your previous "
      "draft): edit that file in place, a section at a time, so it stays one valid JSON "
      "object of the required shape. Do not print the draft."
)
PROMPT_STDOUT = (
    _DESIGN + " End your answer with the complete draft as one JSON object."
)

# Appended when the strategy carries a brief - the person's own game idea. The brief is
# read from the request, never formatted into the prompt: it is the person's text.
PROMPT_BRIEF = (
    " The strategy carries the person's game idea as `brief` (also the request's `brief`): "
    "design the game it describes - its mechanic, fantasy, controls and dimension - and "
    "treat the starting draft as a schema-shaped starting point, not as the game."
)
# Appended instead of PROMPT_BRIEF when the design is a revision: the starting draft IS the game.
PROMPT_BRIEF_REVISION = (
    " The strategy carries the person's game idea as `brief` (also the request's `brief`):"
    " the starting draft is the design already made for it - revise it, do not replace it."
)
# Appended when the run already holds a game-design (a re-entry): the starting draft is that
# design, and only what the strategy's change requires may change (revision.py).
PROMPT_REVISION = (
    " This is a REVISION. The starting draft is this run's game-design version {version},"
    " already made for this title; the request's `revision.strategy_delta` lists"
    " what changed in the strategy since that design (each changed field's before and after;"
    " when `found` is false, compare the design with the strategy yourself). Change the design"
    " exactly as far as that delta requires - new content counts, units, levels, worlds,"
    " mechanics, features or placements the strategy now states - and keep everything the"
    " change does not require you to change: the identity, palette, fonts and typography,"
    " assets, controls and UI stay exactly as they are (add a palette token or an asset only"
    " for something new the delta introduces), so nothing already built or drawn has to be"
    " made again. Every new entry is held to the same checks as the rest: tier it, give an"
    " mvp entry its delivered_by, and specify every new content unit in full."
)
# Appended always: what the module checks the draft against, so the agent is not left to
# discover the consistency rules by failing them. It changes no rule.
PROMPT_CONCEPT = (
    " The module then holds the draft to the strategy's `concept`: every mechanic its "
    "core_mechanic and core_loop state must appear in your core_loop, MVP features or MVP "
    "controls, and you may add no mechanic the strategy's concept, content_model or MVP does "
    "not state."
)
# Appended always: the content bars, by rule id, so the units are written against the same
# measure the check applies. The genre family, its axes and its variety bars are in the
# request's `genre_model` and `content_rules`; the craft guide is `content_craft`.
PROMPT_CONTENT = (
    " build_spec.content is checked against the genre model by these rules, each of which "
    "names the field to change: " + ", ".join(rule_id for rule_id, _ in content_rules.RULES)
    + ". The unit kind, the generation mode, the progression and difficulty models and the "
      "ending must be ones the family allows; the MVP carries at least its units.min_mvp "
      "units and the design its units.min_total at any tier; no unit outruns the session "
      "profile and the first one is half a unit at most; every mechanic a unit asks for is "
      "introduced by that unit or an earlier one and used again after it; consecutive units "
      "change the family's variety dimensions rather than only a number; difficulty escalates "
      "on the axes the family says escalate, dips only for a breather and recovers; every "
      "unit says how it is won and lost in its own terms; and no two units accept nearly the "
      "same thing. scope.content_units and scope.content_unit_kind say what "
      "build_spec.content says. The craft guide is the request's `content_craft`."
      " At the quality tier the request's `content_rules.tier` names (the strategy's"
      " concept.content_model.quality_tier) the content_rules.tier rules also hold the units"
      " to the strategy's content budget and the quality benchmark's bars at that tier, the"
      " larger of the two: declare the elements in build_spec.content.elements and name them"
      " in each unit's `elements`, give each unit its `structure`, `objective_kind` and - where"
      " the family has groups (genre_model.budget.group_kind) - its `group`, close each group"
      " with a `climax` unit where the family names a milestone (its own drawing in the unit's"
      " `art`), and score secondary goals in"
      " build_spec.content.secondary_goals. A design short of its tier fails; it is never"
      " passed at a lower tier than the strategy committed to."
)
# Put FIRST when a report named gaps in the design: what this visit must act on. The gaps are
# also in their own small file and are the request's first key, so an agent that pages a large
# request meets them before anything else.
PROMPT_GAPS = (
    "This visit repairs {count} design gap(s) the build found in this game's design. They are"
    " listed, each with its id and the field it names, in {gaps} (also the request's first"
    " key, `gaps`): questions the developer could not answer from the design, or bars it fell"
    " short of (observed vs bar). {previous} holds the design they were found in (the"
    " request's `previous_design`); {draft} is the file you edit. Answer each gap at the field"
    " it names - a number, a rule, a unit, a state - and change nothing else: this is the same"
    " game, specified further. A gap the design as it stands already answers, or one made"
    " obsolete since it was raised, is not edited: name it in the draft's top-level"
    " `gaps_answered` list as {{\"id\": ..., \"reason\": ...}}, the reason saying where the"
    " design answers it or why it no longer applies; the module removes the list before it"
    " judges the design. The rest of the request at {request} is reference (the strategy is"
    " in its own file, named by the request's `strategy`); it is large, so search it rather"
    " than page through it. What follows is how the design is judged."
)
# Put FIRST instead when a gap visit's draft answered the gaps but the module found it
# invalid: that round is a validation repair. Found live (2026-10-05, a 3D run): with the gaps
# first and the problems last, an agent resumed on such a draft saw every gap answered, edited
# nothing, and the content-rule problems were never fixed.
PROMPT_GAPS_REPAIR = (
    "This round repairs the draft at {draft}: it is this visit's answer to {count} design"
    " gap(s) (listed in {gaps}), and the module found it invalid for the reasons in the"
    " request's first key, `repair.problems`. Fix each of those problems first, at the field"
    " it names, and keep every gap's answer: a draft that answers the gaps but is invalid is"
    " not done, and left as it is it fails the same checks again. {previous} holds the design"
    " the gaps were found in (the request's `previous_design`). The rest of the request at"
    " {request} is reference; search it rather than page through it. What follows is how the"
    " design is judged."
)

# Appended always: the finished design is a game-design artifact, validated against its schema.
PROMPT_SCHEMA = (
    " The finished design is validated against the JSON Schema the request names as `schema`:"
    " use only the enum values it allows, and keep every key it requires."
)
# Appended always: the production art and UI the module requires (presentation.py), so a draft
# states how the finished game looks instead of leaving the developer to draw cubes. The bars
# are in the request's `production_art`, read from core/reference/experience-rules.yaml.
PROMPT_ART = (
    " State the finished game's look, not just its rules: every MVP asset in"
    " build_spec.assets has a `role` (what it is to the player: player, threat, goal, target,"
    " projectile, collectible, hazard, environment, background, prop, ui, vfx, icon, font) and"
    " a `dimension` (2d or 3d), and every entity-role asset a `readability` line - what a"
    " first-time player must recognise in it, and at what size or distance. Every thing your"
    " mechanics name that the player must see (the character they control, what threatens it,"
    " what it aims at, what flies) has an MVP asset of that role; in a 3D game the characters"
    " are 3D models. visual_identity.ui gives font_px (body, hud, heading), min_target_px, the"
    " button's fill and text as palette tokens that contrast, its radius, and the surface"
    " token, within the request's `production_art` bars. Set visual_identity.primitive_style"
    " (with a reason) only when the art direction itself is geometric - a character is never"
    " a cube for convenience. The craft guide is the request's `craft`."
    " The request's `quality_bar` lists frames of finished games: open them - the level of"
    " finish (a composed frame, one visual language, designed typography and UI) is the bar"
    " your art direction must make reachable; their style is not this game's."
)
# Appended to a first design: the archetype's kit is a placeholder, so the agent chooses one.
# A revision keeps the identity it already has and is offered no kits.
PROMPT_ART_KIT = (
    " The starting draft's visual identity was picked from a fixed set by a digest of the"
    " title id, not from the idea: choose from the request's `identity_kits` the one that"
    " best fits this game's idea, subjects and genre, and make visual_identity that kit -"
    " keep its typography exactly as listed there (those faces are already chosen to set"
    " every locale in scope, and the asset step can deliver them), shape language, motion"
    " and ui rules - adapted to the game: add palette tokens for the colours its subjects"
    " need (each piece, character or object a player tells apart by colour gets a token), and"
    " rewrite art_direction and every asset's description and readability to follow it."
)
# Appended always: why a player comes back (depth.py), so a draft states more than one loop.
# The bars are the request's `depth`, read from core/reference/design-depth.yaml.
PROMPT_DEPTH = (
    " State why a player plays longer and returns, in build_spec.depth: the meta_loop above"
    " the run and what it persists (more than a score), a goal_ladder with short, mid and long"
    " goals, a content_schedule of piece, obstacle, power-up, zone or event types introduced"
    " over play (at_s, after_runs), the first_session (target_s equal to"
    " session.first_session_seconds, and the beat it ends on) and the return_hooks. Tier every"
    " entry honestly: an mvp or post-mvp entry names in delivered_by the feature, mechanic,"
    " progression step, reward or hud id that builds it, an mvp entry only an mvp one, and"
    " depth the strategy excludes is optional. The bars are the request's `depth`; the craft"
    " guide is the request's `depth_craft`."
)
# Appended always: the features the brief, the strategy and the genre family name
# (features.py, core/reference/feature-catalogue.yaml), so none is dropped silently and none
# is added because a list has it. The candidates are the request's `feature_candidates`.
PROMPT_FEATURES = (
    " Evaluate every feature in the request's `feature_candidates` (the brief or the strategy"
    " names it, or the genre family expects it): list it in `features` with `catalogue` (its"
    " id), `source` (as given) and an `evaluation` - player_value, cost_h, platform_support"
    " (as given), monetization_impact, qa_cost, and a decision with its reason: `include`"
    " (tier mvp or post-mvp, built), `later` (tier optional, deferred) or `cut` (tier"
    " optional, never). A feature the person's brief asks for is built unless you state why"
    " not; a feature only the family expects is included only where it earns its cost, and"
    " never one a required platform cannot run (platform_support none). The catalogue is the"
    " request's `feature_catalogue`."
)
# Appended always: the counts the brief and strategy state and, for an adopted repository,
# what it already ships (consistency rules brief_commitments_met, existing_content_floor_kept).
PROMPT_COMMITMENTS = (
    " The request's `commitments.stated` are the counts, structure and modes the brief and the"
    " strategy state (\"4 themed worlds\" is at least 4 groups, \"boss levels\" at least two"
    " climax units, a named mode is a feature you include): the units not tiered optional"
    " plan at least each one, or the design fails. `commitments.existing_content`, when"
    " present, is what the repository this run adopts already ships, counted at its commit:"
    " plan no fewer units, groups, climax units or elements than it - you improve that game,"
    " never shrink it. When its `status` is `unmeasured`, the repository ships no content"
    " data file and its content lives in source code: read that code in the checkout, keep"
    " every unit it ships under its own id, and plan at least as much; the shipped build is"
    " counted through the play probe before any developer change and held to."
)
# Appended when the run adopts a repository whose shipped units the run's last design does not
# plan (a first design, or a person moved the checkout): the starting units ARE the game.
PROMPT_ADOPTION = (
    " This repository already ships a game, and this design ADOPTS it. The starting draft's"
    " build_spec.content.units are the units it ships at commit {commit} (the request's"
    " `adoption`; every shipped unit in full, layout included, is in {units}). EXTEND and"
    " improve them: keep every shipped unit under its own id ({ids}), complete what each"
    " lacks, and add units beside them where the brief, the strategy or the tier asks for"
    " more. Never replace a shipped unit with a new one, rename it, plan a different set"
    " of units, or reuse a shipped id for another unit (another objective, structure,"
    " elements, mechanics or difficulty): the design fails when a shipped unit id is missing"
    " from it, and develop refuses a design that rewrites the shipped units under their ids."
)
# Appended to PROMPT_ADOPTION when the floor derives groups or climax units the shipped units
# do not state (existing.derive): what the floor counts is handed over, never left to infer.
PROMPT_ADOPTION_DERIVED = (
    " The floor counts what it derives of the shipped units (the request's"
    " `adoption.derived`): {derived}. Each starting unit already carries the `group` and"
    " climax `purpose` that count gives it, and build_spec.content.groups declares each of"
    " those group ids: keep them - name and theme each group, never drop a group or a unit's"
    " membership - or the design plans fewer groups or climax units than the floor and fails."
)
# Appended when the step asks again: the previous draft and exactly what made it invalid.
PROMPT_REPAIR = (
    " Your previous draft (the request's `repair.previous_draft`) was invalid for the reasons"
    " in `repair.problems`. Return the complete draft again with exactly those fixed and"
    " nothing else changed."
)

# What a revision keeps unless the strategy's change requires it - named in the request.
KEEP = ("identity", "palette", "fonts", "assets", "controls", "ui")

DEFAULTS = {"argv": [], "timeout_seconds": 1800, "idle_timeout_seconds": 600,
            "draft_from": "file"}
# The order a gap's keys are written in: what to find and change first.
_GAP_KEYS = ("id", "field", "question", "severity", "observed", "bar", "assumed", "unit",
             "finding")
_MAX_BYTES = 4 * 1024 * 1024


def _derived_summary(derived):
    """One line of what the floor derives of the shipped units (existing.adoption_derived),
    or "" when it derives no group and no climax unit."""
    derived = derived or {}
    parts = []
    groups = derived.get("groups") or {}
    if groups:
        parts.append(f"{len(groups)} group(s) by {derived.get('groups_measured_by')}: "
                     + "; ".join(f"{g} = {', '.join(ids)}" for g, ids in groups.items()))
    climax = derived.get("climax_unit_ids") or []
    if climax:
        parts.append(f"{len(climax)} climax unit(s) by {derived.get('climax_measured_by')}: "
                     + ", ".join(climax))
    return "; and ".join(parts)


def _tier_request(design, strategy):
    """What the content check holds the units to at the run's quality tier: the tier, where
    it is stated, the strategy's content budget and the quality benchmark's content bars at
    the tier, as `{section: {key: value}}`. Empty bars at a tier the benchmark states none for."""
    tier, where = content_rules.quality_tier(design, strategy)
    bars = {}
    if tier is not None:
        for (section, key), value in sorted(
                content_rules.tier_bars(content_rules.load_benchmark(), tier).items()):
            bars.setdefault(section, {})[key] = value
    budget = (((strategy or {}).get("concept") or {}).get("content_model") or {}).get("budget")
    return {"quality_tier": tier, "where": where, "budget": budget or None,
            "benchmark": bars,
            "rules": list(content_rules.TIER_RULES)}


def _feature_candidates(strategy, family, platforms):
    catalogue = feature_check.load_catalogue()
    entries = {e["id"]: e for e in catalogue.get("features") or []}
    out = []
    for want in feature_check.candidates(strategy, family, catalogue):
        entry = entries[want["id"]]
        out.append(dict(want, description=entry.get("description"),
                        platform_support=feature_check.platform_support(entry, platforms),
                        estimate={key: entry.get(key) for key in (
                            "player_value", "cost_h", "monetization_impact", "qa_cost")}))
    return out


def gap_entries(gaps):
    """The gaps as the agent is given them: each with an id (its own, else `gap-<n>`) and its
    field first, then what was observed against which bar, then everything else it carried."""
    out = []
    for number, gap in enumerate(gaps, 1):
        gap = dict(gap) if isinstance(gap, dict) else {"question": str(gap)}
        gap.setdefault("id", f"gap-{number}")
        entry = {key: gap[key] for key in _GAP_KEYS if gap.get(key) is not None}
        entry.update({key: value for key, value in gap.items() if key not in entry})
        out.append(entry)
    return out


class AgentRunFailed(RuntimeError):
    """The agent host failed, timed out or went silent. Retryable."""


def _provisional_knowledge(starting, strategy):
    """The Factory's rules that may apply to the design about to be written: resolved over
    what is known before it (the family, the strategy's platforms; 2D/3D and tier are
    undetermined, which never excludes a rule). Provisional - the run's knowledge-contract,
    made after design, is what the build is held to. None when the knowledge cannot be read
    (the knowledge step, not this one, stops a run for it)."""
    try:
        from wgf_knowledge import resolve as resolver
        from wgf_quality import registry
        data = registry.load()
        checks, _ = registry.classify(data["tiers"])
        family = ((starting or {}).get("genre") or {}).get("family")
        facets = resolver.facets_from({"genre": {"family": family}}, strategy)
        body = resolver.resolve(data["lessons"], checks, data["tiers"], facets)
    except Exception:  # noqa: BLE001 - guidance only; nothing is decided here
        return None
    return {"provisional": True,
            "rules": [{"id": r["id"], "level": r["level"], "category": r.get("category"),
                       "lesson": " ".join(str(r.get("lesson") or "").split())}
                      for r in body["rules"]]}


def _last_json_object(text):
    """The last top-level JSON object in `text` (bare or in a ```json fence), or None."""
    decoder = json.JSONDecoder()
    found = None
    index = 0
    while True:
        start = text.find("{", index)
        if start < 0:
            return found
        try:
            value, end = decoder.raw_decode(text, start)
        except ValueError:
            index = start + 1
            continue
        if isinstance(value, dict):
            found = value
        index = end


def _kits(locales):
    """Every identity kit the agent may choose from, each with its faces already swapped for
    the covering alternates the design's locales need (identity.cover) - the same rule the
    archetype author applies, so a chosen kit's typography can set every locale in scope."""
    from .presentation import load_font_coverage
    coverage = load_font_coverage()
    out = {}
    for kit_id, kit in identity.KITS.items():
        look = {key: copy.deepcopy(kit.get(key)) for key in (
            "concept", "palette", "typography", "shape_language", "motion", "texture",
            "avoid", "ui")}
        look, _swapped = identity.cover(look, list(locales or []), coverage)
        out[kit_id] = look
    return out


def check_shape(draft):
    """Problems with the draft's shape - before `finalize` indexes into it."""
    if not isinstance(draft, dict):
        return ["the draft is not a JSON object"]
    problems = [f"missing {key!r}" for key in REQUIRED_KEYS if key not in draft]
    spec = draft.get("build_spec")
    if "build_spec" in draft and not isinstance(spec, dict):
        problems.append("build_spec is not an object")
    elif isinstance(spec, dict):
        problems += [f"build_spec is missing {key!r}" for key in BUILD_SPEC_KEYS
                     if key not in spec]
    if "scope" in draft and not isinstance(draft["scope"], dict):
        problems.append("scope is not an object")
    if "engine" in draft and not isinstance(draft["engine"], dict):
        problems.append("engine is not an object")
    if "features" in draft and not isinstance(draft["features"], list):
        problems.append("features is not a list")
    return problems


class AgentAuthor(DesignAuthor):
    name = "agent"
    actor = "ai"
    # The design step shows it what made its draft invalid and asks again (step.py).
    repairs = True
    # Re-entered in a new visit, it revises the run's previous game-design instead of
    # starting again (revision.py; the step passes it as brief['revision']).
    revises = True

    def draft(self, brief):
        settings = dict(DEFAULTS)
        settings.update(((brief.get("config") or {}).get("design") or {}).get("agent") or {})
        argv = settings.get("argv") or []
        if not isinstance(argv, list) or not argv or not all(isinstance(a, str) for a in argv):
            raise AuthorError("factory.design.agent.argv is not configured (a non-empty list "
                              "of strings); the agent author has nothing to run")
        if settings.get("draft_from") not in ("file", "stdout"):
            raise AuthorError("factory.design.agent.draft_from must be file or stdout")
        run_dir = brief.get("run_dir")
        if not run_dir:
            raise AuthorError("the design step gave the agent author no run directory")

        directory = os.path.join(run_dir, "design")
        repair = brief.get("repair") or {}
        stem = f"{brief.get('visit', 1)}-{brief.get('attempt', 1)}" + (
            "-gaps" if brief.get("gaps") else "") + (
            f"-repair{repair['round']}" if repair else "")
        request_path = os.path.join(directory, f"{stem}.request.json")
        draft_path = os.path.join(directory, f"{stem}.draft.json")
        log_path = os.path.join(directory, f"{stem}.log")
        os.makedirs(directory, exist_ok=True)
        for stale in (draft_path, log_path):
            if os.path.exists(stale):
                os.remove(stale)

        gaps = gap_entries(brief.get("gaps") or [])
        previous = brief.get("previous_design")
        if gaps and not isinstance(previous, dict):
            raise AuthorError("the design step passed design gaps without the design they were "
                              "found in (brief['previous_design']): there is nothing to repair")
        # A re-entry (a new visit after the strategy changed) starts from the run's previous
        # game-design and revises it - on every repair round too, so the request always names
        # the base the draft came from. Design gaps carry their own base and take precedence.
        revision = None if gaps else brief.get("revision")
        if gaps:
            # Repairing a design that was built: start from it, not from a fresh draft, so
            # answering a gap cannot quietly redesign the game around it.
            starting = {key: value for key, value in copy.deepcopy(previous).items()
                        if key not in ("provenance", "consistency")}
        elif revision:
            starting = as_draft(revision["design"], brief.get("strategy"))
            # A feature the changed strategy now names starts evaluated (deferred, or cut
            # where the strategy or platforms rule it out), as in a first design.
            if isinstance(starting.get("features"), list):
                feature_check.evaluate_for_author(
                    starting["features"], brief.get("strategy") or {},
                    (starting.get("genre") or {}).get("family"), brief.get("platforms") or [],
                    [split_reason(e) for e in (brief.get("strategy") or {}).get("out_of_scope")
                     or []])
        else:
            # The built-in author's draft is the starting point: the exact shape the module
            # requires, already inside the strategy's scope. The agent improves it.
            starting = ArchetypeAuthor(starting_point=True).draft(brief)
        adoption = None if gaps else brief.get("adoption")
        adopted_path = os.path.join(directory, f"{stem}.adopted-units.json")
        if adoption:
            # The shipped units are the starting units: the design extends the game the
            # repository ships, never a game of other content (step.py `_adoption`).
            spec = starting.setdefault("build_spec", {})
            content_spec = spec.get("content") if isinstance(spec.get("content"), dict) else {}
            content_spec["units"] = copy.deepcopy(adoption.get("units") or [])
            # The groups the adopted units carry (existing.adoption_units: a group the floor
            # derives is written into each unit) are the groups the design declares; a
            # starting group no adopted unit is in is another game's.
            used = []
            for unit in content_spec["units"]:
                if isinstance(unit, dict) and unit.get("group") and unit["group"] not in used:
                    used.append(unit["group"])
            if used:
                declared = {g.get("id"): g for g in content_spec.get("groups") or []
                            if isinstance(g, dict) and g.get("id")}
                content_spec["groups"] = [declared.get(g) or {"id": g, "name": g}
                                          for g in used]
            spec["content"] = content_spec
            with open(adopted_path, "w", encoding="utf-8", newline="\n") as handle:
                json.dump({"commit": adoption.get("commit"), "path": adoption.get("path"),
                           "units": adoption.get("shipped_units") or adoption.get("units")},
                          handle, indent=2, ensure_ascii=False, default=str)
        idea = (brief.get("strategy") or {}).get("brief")
        rules = load_rules()
        models = genre_models.load()
        genre = starting.get("genre") if isinstance(starting.get("genre"), dict) else {}
        family = (models.get("families") or {}).get(genre.get("family")) or {}
        profile_name = genre.get("session_profile") or "standard"
        request = {}
        gaps_path = os.path.join(directory, f"{stem}.gaps.json")
        strategy_path = os.path.join(directory, f"{stem}.strategy.json")
        previous_path = os.path.join(directory, f"{stem}.previous.json")
        if gaps:
            # What this visit must act on comes first and small; the bulk is reference. The
            # design the gaps were found in (the base every round is judged against) and the
            # strategy are files of their own, named, not copied in. On a repair round the
            # problems come first: the draft file already holds this visit's gap answers.
            if repair:
                request["repair"] = {"problems": repair.get("problems") or [],
                                     "previous_draft": draft_path}
            request.update({
                "gaps": gaps,
                "gaps_file": gaps_path,
                "instructions": (PROMPT_GAPS_REPAIR if repair else PROMPT_GAPS).format(
                    count=len(gaps), gaps=gaps_path, draft=draft_path, previous=previous_path,
                    request=request_path),
                "draft": draft_path,
                "previous_design": previous_path})
            with open(previous_path, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(starting, handle, indent=2, ensure_ascii=False, default=str)
            with open(strategy_path, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(brief.get("strategy"), handle, indent=2, ensure_ascii=False,
                          default=str)
            with open(gaps_path, "w", encoding="utf-8", newline="\n") as handle:
                json.dump({"gaps": gaps, "draft": draft_path, "request": request_path,
                           "instructions": request["instructions"]},
                          handle, indent=2, ensure_ascii=False, default=str)
        request.update({"title_id": brief.get("title_id"),
                       "strategy": strategy_path if gaps else brief.get("strategy"),
                       "platforms": [{"id": p.id, "role": p.role, "version": p.version,
                                      "profile": p.profile} for p in brief.get("platforms") or []],
                       "required_keys": list(REQUIRED_KEYS),
                       "required_build_spec_keys": list(BUILD_SPEC_KEYS),
                       # What the finished design is validated against: every enum value and
                       # required key. Shared definitions are beside it, under shared/.
                       "schema": os.path.join(paths.ARTIFACTS, "game-design.schema.json"),
                       # The bars the production art and UI are held to (presentation.py), and
                       # the craft guide they come from.
                       "production_art": {key: rules.get(key) for key in ("production_art", "ui")},
                       "craft": os.path.join(paths.CORE, "craft", "production-art-and-ui.md"),
                       # The bars depth is held to (depth.py), and the craft guide behind them.
                       "depth": load_depth_rules(),
                       "depth_craft": os.path.join(paths.CORE, "craft",
                                                   "retention-and-progression.md"),
                       # Frames of finished games.
                       "quality_bar": quality_bar.frames(),
                       "quality_bar_qualities": quality_bar.qualities(),
                       # The genre family the content is held to, exactly as content.py reads it -
                       # its unit kinds, models, ending, axes, win and lose shape, unit counts,
                       # variety dimensions and mastery model. `seed` is the built-in author's own
                       # starting design and is left out: the agent designs, it does not copy.
                       "genre_model": {key: value for key, value in family.items()
                                       if key != "seed"},
                       # What the content check measures, and the bars it measures against.
                       "content_rules": {
                           "rules": [{"id": rule_id, "meaning": meaning}
                                     for rule_id, meaning in content_rules.RULES],
                           "variety": dict(models.get("variety") or {},
                                           **(family.get("variety") or {})),
                           "session_profile": dict(
                               (models.get("session_profiles") or {}).get(profile_name) or {},
                               name=profile_name),
                           # The quality tier and what it asks for (content.tier_*): the
                           # strategy's budget and the benchmark's bars at the tier.
                           "tier": _tier_request(starting, brief.get("strategy")),
                       },
                       "content_craft": os.path.join(paths.CORE, "craft",
                                                     "content-and-level-design.md"),
                       # The features the design must evaluate (features.py), with what the
                       # catalogue and the required platforms say of each.
                       "feature_catalogue": feature_check.CATALOGUE_PATH,
                       "feature_candidates": _feature_candidates(
                           brief.get("strategy") or {}, genre.get("family"),
                           brief.get("platforms") or []),
                       # What the brief and strategy count, and what an adopted repository
                       # already ships (commitments.py, existing.py).
                       "commitments": {
                           "stated": brief_commitments.view(
                               {}, brief.get("strategy") or {})["stated"],
                           "existing_content": brief.get("existing_content")}})
        if not gaps:
            # On a gap repair the starting draft is the draft file itself.
            request["starting_draft"] = starting
        if adoption:
            request["adoption"] = {
                "commit": adoption.get("commit"), "path": adoption.get("path"),
                "unit_ids": adoption.get("unit_ids"), "units_file": adopted_path,
                "rewritten": adoption.get("rewritten") or [],
                "supersedes": adoption.get("supersedes"),
                # What the floor derives of the shipped units (existing.derive): the groups
                # with their unit ids and the climax units, each by its method.
                "derived": adoption.get("derived"),
                "rule": "Every unit id the repository ships stays in the design under its "
                        "own id; extend and improve the shipped units, never replace them."}
        if revision:
            # The identity is kept, so no other look is offered.
            request["revision"] = {"revises_version": revision.get("version"),
                                   "revises": revision.get("artifact_id"),
                                   "strategy_delta": revision.get("strategy_delta"),
                                   "keep": list(KEEP)}
        elif not gaps:
            # The committed looks to choose from. A gap repair keeps the identity it has.
            request["identity_kits"] = _kits((starting.get("scope") or {}).get("locales"))
        if idea:
            request["brief"] = idea
        if repair and not gaps:
            request["repair"] = {"problems": repair.get("problems") or [],
                                 "previous_draft": repair.get("previous_draft")}
        constraints = ((brief.get("strategy") or {}).get("research") or {}).get(
            "design_constraints")
        if isinstance(constraints, dict) and constraints:
            # The content shape research coded for this cell, with its tiers and claims: the
            # family, what one unit is, the progression, the difficulty shape and the axes.
            request["design_constraints"] = constraints
        knowledge = _provisional_knowledge(starting, brief.get("strategy"))
        if knowledge:
            request["knowledge"] = knowledge
        with open(request_path, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(request, handle, indent=2, ensure_ascii=False, default=str)

        try:
            env = agentenv.scrubbed(agentenv.passthrough(brief.get("config")))
        except ValueError as exc:
            raise AuthorError(str(exc)) from exc
        values = {"request": request_path, "draft": draft_path}
        stdout_mode = settings["draft_from"] == "stdout"
        seed = None
        if not stdout_mode:
            # The agent edits the draft in place rather than reproducing all of it: a full
            # design is tens of kilobytes, more than a host reliably emits in one reply.
            seed = json.dumps((repair.get("previous_draft") if repair else None) or starting,
                              indent=2, ensure_ascii=False, default=str) + "\n"
            with open(draft_path, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(seed)
        values["prompt"] = (request["instructions"] + " " if gaps else "") + (
            PROMPT_STDOUT if stdout_mode else PROMPT).format(**values)
        if idea:
            values["prompt"] += PROMPT_BRIEF_REVISION if revision else PROMPT_BRIEF
        if revision:
            values["prompt"] += PROMPT_REVISION.format(version=revision.get("version"))
        values["prompt"] += PROMPT_CONCEPT + PROMPT_SCHEMA + PROMPT_ART
        if not revision and not gaps:
            values["prompt"] += PROMPT_ART_KIT
        values["prompt"] += (PROMPT_DEPTH + PROMPT_CONTENT + PROMPT_FEATURES
                             + PROMPT_COMMITMENTS)
        if adoption:
            ids = [str(i) for i in adoption.get("unit_ids") or []]
            values["prompt"] += PROMPT_ADOPTION.format(
                commit=str(adoption.get("commit") or "")[:12], units=adopted_path,
                ids=", ".join(ids[:16]) + (f" and {len(ids) - 16} more" if len(ids) > 16
                                           else ""))
            derived = _derived_summary(adoption.get("derived"))
            if derived:
                values["prompt"] += PROMPT_ADOPTION_DERIVED.format(derived=derived)
        if repair:
            values["prompt"] += PROMPT_REPAIR
        try:
            command = permpath.format_argv(argv, values, ("request", "draft"))
        except (KeyError, IndexError, ValueError) as exc:
            raise AuthorError(f"factory.design.agent.argv has a placeholder this author does "
                              f"not provide ({exc}); use {{request}}, {{draft}}, {{prompt}}, "
                              f"{{draft_rule}}, and double any literal brace") from exc
        result = procs.run(command, cwd=directory, env=env,
                           timeout=settings.get("timeout_seconds"),
                           idle_timeout=settings.get("idle_timeout_seconds"),
                           log_path=log_path, heartbeat_seconds=15.0)
        if not result.ok:
            raise AgentRunFailed(
                f"the design agent {os.path.basename(command[0])} ended {result.status} "
                f"(exit {result.returncode}); log: {log_path}")

        if stdout_mode:
            draft = _last_json_object(result.stdout or "")
            if draft is None:
                raise AuthorError("the design agent printed no JSON object")
        else:
            if not os.path.isfile(draft_path):
                raise AuthorError(f"the design agent wrote no draft at {draft_path}")
            if os.path.getsize(draft_path) > _MAX_BYTES:
                raise AuthorError("the design draft is larger than 4 MiB")
            try:
                with open(draft_path, encoding="utf-8") as handle:
                    text = handle.read()
                draft = json.loads(text)
            except (OSError, UnicodeDecodeError, ValueError) as exc:
                raise AuthorError(f"the design draft is not readable JSON: {exc}") from exc
            # A revision of a design whose strategy did not change may stand as it was.
            unchanged_ok = bool(adoption) or (
                bool(revision) and not repair and
                (revision.get("strategy_delta") or {}).get("unchanged") is True)
            if text == seed and not unchanged_ok and not gaps:
                raise AuthorError(f"the design agent left the draft at {draft_path} "
                                  f"unchanged")
        if gaps and isinstance(draft, dict):
            # A gap visit is judged against the design the gaps were found in, never against
            # the draft a round was seeded with: a repair round's (or a resumed visit's) draft
            # already answers the gaps, and one left as it is goes back to the step's checks,
            # which name its problems again.
            marked = self._gaps_answered(draft, gaps, directory, brief.get("visit", 1))
            unanswered = [g for g in gaps if g["id"] not in marked]
            if unanswered and draft == json.loads(json.dumps(starting, default=str)):
                raise AuthorError(
                    f"the design agent left the draft at {draft_path} unchanged, so "
                    + (f"none of the {len(gaps)} design gap(s) it was given is answered: "
                       if len(unanswered) == len(gaps) else
                       f"{len(unanswered)} of the {len(gaps)} design gap(s) it was given are "
                       f"neither answered nor marked answered with a reason: ")
                    + "; ".join(f"{g['id']} at {g.get('field')}" for g in unanswered[:12])
                    + (f"; and {len(unanswered) - 12} more" if len(unanswered) > 12 else "")
                    + f" (gaps: {gaps_path}; log: {log_path})")
        problems = check_shape(draft)
        if problems:
            hint = (" - in stdout mode this is usually a reply cut by the host's output limit; "
                    "use draft_from: file" if stdout_mode else "")
            raise AuthorError("the design draft does not have the required shape: "
                              + "; ".join(problems[:8]) + hint)
        return draft

    @staticmethod
    def _gaps_answered(draft, gaps, directory, visit):
        """The gap ids the agent marked answered without an edit - the draft's top-level
        `gaps_answered`, each with an id and a reason - removed from the draft and kept, with
        the earlier rounds' marks of this visit, in `<visit>-gaps-answered.json`: the evidence,
        and what a later round's draft is judged with. A mark without a reason, or for a gap
        this visit was not given, does not count. The step's checks still judge the draft."""
        ids = {g["id"] for g in gaps}
        path = os.path.join(directory, f"{visit}-gaps-answered.json")
        kept = {}
        try:
            with open(path, encoding="utf-8") as handle:
                loaded = json.load(handle)
            kept = {k: v for k, v in (loaded.get("answered") or {}).items() if k in ids}
        except (OSError, ValueError, AttributeError):
            pass
        marks = draft.pop("gaps_answered", None)
        for mark in marks if isinstance(marks, list) else []:
            if (isinstance(mark, dict) and mark.get("id") in ids
                    and isinstance(mark.get("reason"), str) and mark["reason"].strip()):
                kept[mark["id"]] = mark["reason"].strip()
        if marks is not None:
            with open(path, "w", encoding="utf-8", newline="\n") as handle:
                json.dump({"answered": kept}, handle, indent=2, ensure_ascii=False)
        return kept


register_author(AgentAuthor.name, AgentAuthor)

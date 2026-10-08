"""Design authors: whatever writes the creative content of a design.

An author turns a brief (strategy, resolved platform profiles, step parameters) into a DRAFT:
the game-design body without provenance, consistency, derived scope tiers, SDK touchpoints or
platform constraints. The module owns everything after the draft - platform absorption,
tier derivation, the buildability check and the consistency rules - so every author is held
to the same exit guard and none can mark its own homework.

`archetype` is the built-in author: offline and deterministic. It fits a genre archetype to
the strategy - session first, then scope - and never invents monetization or scope the
strategy did not approve. An author that delegates to an agent host registers itself from
its own module:

    from wgf_design import register_author
    register_author("agent", AgentAuthor)

and an installation selects it in workspace/config/factory.yaml:

    factory:
      design:
        author: agent

A workflow step may also pin one with `with: {author: <name>}`. Names only - never a path.

The brief the step hands an author:

    title_id, strategy, platforms, params, config, run_dir, visit, attempt
    repair          {round, problems, previous_draft} - the composed design was invalid and
                    this author `repairs`; the same author is asked again
    gaps            [{field, question, ...}] - the gaps a prototype-report named in the design
                    (`design_gaps`), to be answered at their own fields
    previous_design the game-design those gaps were found in; the draft starts from it

`gaps` and `previous_design` are the repair-a-shipped-design path and only the `agent` author
can answer them: a deterministic author cannot invent the answer to a question about its own
design, so `archetype` and `genre-seed` refuse the brief rather than silently ignore it.
"""

import copy
import re
from collections import namedtuple

from wgflib import genre_models
from wgflib import template_contract as contract

from . import archetypes, identity, presentation
from . import depth as depth_check
from . import features as feature_check
from .platforms import supported_placements, tightest_interval

__all__ = ["DesignAuthor", "ArchetypeAuthor", "AUTHORS", "Resolved", "register_author",
           "resolve_author", "AuthorError"]

TIER_ORDER = ("mvp", "post-mvp", "optional")

PLACEMENTS_BY_CLASS = {
    "rewarded-led": ["rewarded", "interstitial"],
    "interstitial-led": ["interstitial"],
    "mixed-ads": ["rewarded", "interstitial", "banner"],
    "iap-led": ["iap"],
    "hybrid": ["rewarded", "iap"],
    "none": [],
}

STOP = {"with", "that", "this", "than", "from", "into", "only", "beyond", "more", "less", "any",
        "one", "the", "and", "for", "per", "not", "all", "its", "their", "layer", "specific",
        "multiple", "game", "games", "player", "players", "same", "every", "each", "short"}


class AuthorError(Exception):
    """The author cannot write a design from this brief. Not retryable."""


# What designs this strategy, and everything that comes with it: the archetype's id and its
# whole shape (`archetype`, including its `genre`, `content`, `difficulty_axes` and `mastery`),
# its experience contract, its depth plan, why it was chosen, and the research-applied entries
# the choice produced. `archetype` is a hand-written entry of archetypes.ARCHETYPES or one the
# genre seed author synthesized from a family's model - the rest of the author reads one shape.
Resolved = namedtuple("Resolved", "archetype_id archetype experience depth why applied")

# The brief keys only an agent author can act on (see the module docstring).
GAPS_NEED_AGENT = ("design gaps need the agent author; configure factory.design.author: agent")


class DesignAuthor:
    """Interface. `draft(brief)` returns a draft dict; see the module docstring."""

    name = None

    def draft(self, brief):  # pragma: no cover - interface
        raise NotImplementedError


AUTHORS = {}


def register_author(name, factory):
    AUTHORS[name] = factory


def resolve_author(name):
    factory = AUTHORS.get(name)
    if factory is None:
        raise AuthorError(f"no design author {name!r}; registered: {', '.join(sorted(AUTHORS))}")
    return factory()


# -- helpers -----------------------------------------------------------------------------

def slug(text, limit=5):
    words = re.findall(r"[a-z0-9]+", text.lower())
    return "-".join(words[:limit]) or "item"


def _stems(text):
    words = re.findall(r"[a-z]+", text.lower())
    return {w.rstrip("s") for w in words if len(w) >= 4 and w not in STOP}


def split_reason(entry):
    """'Leaderboards - they add backend' -> ('Leaderboards', 'they add backend')."""
    for separator in (" — ", " -- ", " - ", ": "):
        if separator in entry:
            item, why = entry.split(separator, 1)
            return item.strip(), why.strip()
    return entry.strip(), "Excluded by the title strategy, approved at G2."


class Exclusions:
    """The strategy's out_of_scope list, matched against candidate features by shared stems."""

    def __init__(self, entries):
        self.entries = [split_reason(e) for e in entries]
        self._stems = [(_stems(item), item, why) for item, why in self.entries]

    def match(self, text, ignore=()):
        """The first exclusion sharing a stem with `text`, not counting the stems in `ignore`."""
        stems = _stems(text) - set(ignore)
        for item_stems, item, why in self._stems:
            if stems & item_stems:
                return item, why
        return None

    def mentions(self, *words):
        text = " ".join(item.lower() for item, _ in self.entries)
        return any(word in text for word in words)


# -- the built-in author -----------------------------------------------------------------

def research_of(strategy):
    """The Research V2 handoff the strategy carries, or None."""
    research = (strategy or {}).get("research")
    return research if isinstance(research, dict) and research.get("research_version") == 2 \
        else None


def usable(research, fv, facet):
    """How a research facet may drive a design decision: "evidence" when research observed or
    derived it, "proposal" when it is the one axis the opportunity proposes to change (a
    hypothesis the title exists to test), else None - and the design decides it by default."""
    fv = fv or {}
    if fv.get("tier") in ("observed", "derived") and fv.get("value") not in (None, [], ""):
        return "evidence"
    intent = (research or {}).get("changed_axis") or {}
    if intent.get("facet") == facet and fv.get("value") not in (None, [], ""):
        return "proposal"
    return None


def research_art(research):
    """{tone, palette, rendering} research supports or proposes, for the kit."""
    out = {}
    for key in ("tone", "palette", "rendering"):
        fv = ((research or {}).get("art") or {}).get(key) or {}
        if usable(research, fv, f"art_{key}") and isinstance(fv.get("value"), str):
            out[key] = fv["value"]
    return out


def _subsets_clause(locales):
    """' (subsets: latin, cyrillic - en, ru)': what the font files must cover, stated so the
    asset step's coverage check and whoever builds the files read the same thing."""
    coverage = presentation.load_font_coverage()
    subsets = []
    for locale in locales or []:
        for subset in (presentation.locale_subsets(locale, coverage) or [])[:1]:
            if subset not in subsets:
                subsets.append(subset)
    return (f" (subsets: {', '.join(subsets)} - {', '.join(locales)})" if subsets else "")


# A concept's `design_archetype` naming no catalog archetype: only the agent author can
# design it (the discovery step's concepts file, core/craft/research-evidence.md).
AGENT_ONLY = "agent"


class ArchetypeAuthor(DesignAuthor):
    name = "archetype"

    def __init__(self, starting_point=False):
        # True when another author (the agent) only takes this draft as its starting point:
        # then a concept only the agent can design is not refused, the agent designs it.
        self.starting_point = starting_point

    def _resolve(self, brief):
        """`Resolved` for this brief: which archetype designs the strategy, and its shape.

        One order, so the same strategy always resolves the same way:

            1. the archetype the workflow step pinned (`with: {archetype: <id>}`);
            2. the design archetype research's capability catalog declares buildable;
            3. the genre family that catalog names instead (`capability.genre_model`) - the
               genre seed author synthesizes the archetype from the family's own model;
            4. the strategy's own words (archetypes.select).

        A concept whose `design_archetype` is `agent` is none of those: only the agent author
        can design it, and picking a catalog archetype by keyword instead designs another game
        (F09). It is refused here, unless this draft is only the agent's starting point.
        """
        strategy = brief["strategy"]
        params = brief.get("params") or {}
        research = research_of(strategy)
        capability = (research or {}).get("capability") or {}
        pinned = params.get("archetype")
        applied = []
        if not pinned and not self.starting_point and \
                capability.get("design_archetype") == AGENT_ONLY:
            raise AuthorError(
                f"research selected concept {capability.get('catalog_entry')!r}, which "
                f"only the agent design author can design (design_archetype: agent), and "
                f"the configured author is archetype. Set `design: {{author: agent}}` "
                f"with a `design.agent` host in workspace/config/factory.yaml (or copy the "
                f"autonomous profile: docs/autonomous-runs.md), then resume")
        if not pinned and capability.get("buildable") and \
                capability.get("design_archetype") in archetypes.ARCHETYPES:
            archetype_id = capability["design_archetype"]
            why = (f"research's capability catalog builds this opportunity with it "
                   f"(entry {capability.get('catalog_entry')})")
            applied.append({"field": "archetype", "source": "research",
                            "detail": f"{archetype_id}: {capability.get('reason')}"})
        else:
            models = genre_models.load()
            families = models.get("families") or {}
            family = capability.get("genre_model") if not pinned else None
            if family in families:
                from .seed import GenreSeedAuthor
                return GenreSeedAuthor(starting_point=self.starting_point).synthesize(
                    family, models, strategy, families[family])
            archetype_id, why = archetypes.select(strategy, pinned)
            if research is not None:
                applied.append({"field": "archetype", "source": "default",
                                "detail": f"{archetype_id}: {why} (research named "
                                          f"no buildable design archetype)"})
        return Resolved(archetype_id, archetypes.ARCHETYPES[archetype_id],
                        archetypes.EXPERIENCE[archetype_id], archetypes.DEPTH[archetype_id],
                        why, applied)

    def draft(self, brief):
        if brief.get("gaps"):
            raise AuthorError(GAPS_NEED_AGENT)
        strategy = brief["strategy"]
        platforms = brief["platforms"]
        params = brief.get("params") or {}
        title_id = brief["title_id"]

        research = research_of(strategy)
        try:
            resolved = self._resolve(brief)
            archetype_id, why_archetype, applied = (resolved.archetype_id, resolved.why,
                                                    list(resolved.applied))
            a = resolved.archetype
            affinity = a["identity_affinity"]
            art = research_art(research)
            kit_id, basis, matched = identity.pick(title_id, affinity, params.get("identity"), art)
            look = identity.look(kit_id)
        except KeyError as exc:
            raise AuthorError(str(exc.args[0])) from None
        if research is not None:
            art_refs = sorted({c for k in ("tone", "palette", "rendering")
                               for c in ((research["art"].get(k) or {}).get("claim_refs") or [])
                               if (research["art"].get(k) or {}).get("tier") in ("observed",
                                                                                 "derived")})
            applied.append({"field": "art_direction", "source": "research" if basis == "research"
                            else "default",
                            "detail": (f"identity kit {kit_id} matches research's "
                                       f"{', '.join(matched)}" if basis == "research" else
                                       f"identity kit {kit_id} by {basis}: research supports no "
                                       f"art tone, palette or rendering for this cell")})
            if basis == "research" and art_refs:
                applied[-1]["claim_refs"] = art_refs
        exclusions = Exclusions(strategy.get("out_of_scope") or [])
        out_of_scope = [{"item": item, "why_excluded": why} for item, why in exclusions.entries]
        open_questions = list(strategy.get("prototype_must_prove") or [])

        # 1. Engine. Dimensionality is the archetype's unless the step pins it.
        # The 2D default is the 2D default: a second 2D engine is pinned by the step, never
        # inferred from an archetype.
        engine_type = params.get("engine") or ("threejs" if a["dimension"] == "3d" else "pixijs")
        if engine_type not in contract.ENGINES:
            raise AuthorError(f"engine {engine_type!r}: the template carries "
                              f"{', '.join(contract.ENGINES)}, nothing else")
        dimension = "3d" if engine_type == "threejs" else "2d"
        orientation = params.get("orientation") or a["orientation"]
        resolution = {"width": 720, "height": 1280} if orientation == "portrait" else {"width": 1280, "height": 720}
        engine = {
            "type": engine_type,
            "dimension": dimension,
            "rationale": (
                f"The play happens on a flat plane: a {a['label'].lower()} needs no depth to read, and 2D "
                "with procedural vector art keeps the first load small on portal traffic, where time to first "
                "play decides whether the player stays."
                + (" The plan pins Phaser rather than the 2D default because this game leans on the engine's "
                   "own scene manager, input, tweens and arcade physics; the tech plan states which."
                   if engine_type == "phaserjs" else "") if dimension == "2d" else
                f"Depth is part of the mechanic: a {a['label'].lower()} is read through a chase camera in "
                "space. Three.js with low-poly procedural geometry and vertex colours keeps the load budget "
                "close to a 2D title; textures and PBR materials are deliberately excluded."),
            "design_resolution": resolution,
            "camera": a["camera"],
        }

        # 2. Session first. Everything else is fitted to it.
        session_intent = strategy.get("session") or {}
        target = session_intent["target_seconds"]
        first = session_intent.get("first_session_seconds") or min(target, 180)
        audience = strategy.get("audience") or {}
        time_to_first_play = {"casual": 5, "midcore": 8, "core": 10}.get(audience.get("type"), 6)
        measured = next((b for b in (research or {}).get("benchmarks") or []
                         if b.get("facet") == "time_to_first_play_seconds"), None)
        if measured and measured["median"] < time_to_first_play:
            time_to_first_play = max(1, int(measured["median"]))
            applied.append({"field": "build_spec.time_to_first_play_s", "source": "research",
                            "detail": f"{time_to_first_play} s: the median of {measured['n']} "
                                      f"comparable games beats the audience default",
                            "claim_refs": [measured["claim"]]})
        time_to_first_reward = min(a["first_reward_s"], max(5, int(first * 0.5)))
        rewarded = next((b for b in (research or {}).get("benchmarks") or []
                         if b.get("facet") == "time_to_first_reward_seconds"), None)
        if rewarded and rewarded["median"] < time_to_first_reward:
            # The strategy's prototype_must_prove holds the title to this bar.
            time_to_first_reward = max(1, int(rewarded["median"]))
            applied.append({"field": "build_spec.time_to_first_reward_s", "source": "research",
                            "detail": f"{time_to_first_reward} s: the median of "
                                      f"{rewarded['n']} comparable games",
                            "claim_refs": [rewarded["claim"]]})
        run = a["run_seconds"]
        units_per_session = max(1, round(target / run))
        is_level = a["structure"] == "level"
        unit_word = "level" if is_level else "run"

        # 3. Monetization - only what the strategy approved, only where required platforms allow it.
        monetization = strategy.get("monetization") or {}
        wanted = monetization.get("placements") or PLACEMENTS_BY_CLASS.get(monetization.get("class"), [])
        allowed = supported_placements(platforms)
        kinds = []
        for kind in wanted:
            if kind in allowed:
                kinds.append(kind)
            else:
                out_of_scope.append({"item": f"{kind} placement",
                                     "why_excluded": "The strategy lists it, but a required platform does not "
                                                     "offer it (platform profile capabilities)."})
                open_questions.append(f"The strategy wanted a {kind} placement that a required platform cannot "
                                      "serve. Is the revenue model still sound without it?")
        cooldown = max(tightest_interval(platforms) or 0, 90)
        by_kind = {k: [p.id for p in platforms if k in p.placements] for k in kinds}
        fail_state = "level-fail" if is_level else "fail"
        touchpoints = []
        for index, kind in enumerate(kinds):
            tier = "mvp" if index == 0 else "post-mvp"
            if kind == "rewarded":
                touchpoints.append({
                    "id": "rewarded-continue", "kind": "rewarded", "tier": tier, "state": fail_state,
                    "trigger": ("On failing a level, offer five extra moves once per attempt" if is_level else
                                "On a run-ending failure after at least 20 s of play, offer one continue per run"),
                    "player_value": ("Five more moves on the same board, goals kept" if is_level else
                                     "Continue from the point of failure, keeping score and streak"),
                    "platforms": by_kind[kind],
                    "when_unavailable": "The continue button is not shown; retry is the primary action. Never a disabled button.",
                })
            elif kind == "interstitial":
                touchpoints.append({
                    "id": "interstitial-between", "kind": "interstitial", "tier": tier, "state": fail_state,
                    "trigger": (f"When the player leaves the result card (Retry or Menu), at most once every "
                                f"{cooldown}s, never in the first {unit_word} of a session and never inside play"),
                    "player_value": "None - a pure interruption, priced as such and held to the tightest platform cadence",
                    "cooldown_s": cooldown, "platforms": by_kind[kind],
                    "when_unavailable": "Proceed immediately; no placeholder, no countdown.",
                })
            elif kind == "banner":
                touchpoints.append({
                    "id": "banner-title", "kind": "banner", "tier": tier, "state": "title",
                    "trigger": "Title screen only; never over play or the result card",
                    "player_value": "None - it occupies a reserved slot that never overlaps controls",
                    "platforms": by_kind[kind],
                    "when_unavailable": "The layout collapses the reserved slot.",
                })
            elif kind == "iap":
                touchpoints.append({
                    "id": "iap-remove-ads", "kind": "iap", "tier": tier, "state": "title",
                    "trigger": "A 'remove ads' item on the title screen",
                    "player_value": "No interstitials, permanently",
                    "platforms": by_kind[kind],
                    "when_unavailable": "The item is not shown on platforms without purchases.",
                })
        has_rewarded = any(t["kind"] == "rewarded" for t in touchpoints)

        session = {
            "time_to_first_play_s": time_to_first_play,
            "time_to_first_reward_s": time_to_first_reward,
            "first_session_seconds": first,
            "target_seconds": target,
            "structure": (
                f"A {unit_word} lasts about {run}s. A session is {units_per_session} "
                f"{unit_word}{'s' if units_per_session != 1 else ''} back to back, each starting within "
                f"{'two seconds' if is_level else 'a second'} of the last ending. The first session drops "
                "straight into play with no menu; later sessions open on the title screen with the best score "
                "visible. The session ends at a natural stopping point rather than being cut off."),
            "reward_moments_per_session": units_per_session,
            "end_condition": ("The player clears a level set boundary or fails the same level three times."
                              if is_level else
                              "The player sets a new personal best, or three runs pass without improvement."),
        }

        # 4. Scope fitted to the session: the content block is what the game carries, so
        # scope counts exactly what it lists (content.scope_count_agrees). A procedural
        # design is counted by the units a session meets, since no list can be exhaustive.
        content = copy.deepcopy(a["content"])
        # Not a family: the session profile the content is held to. A casual audience playing
        # in short bursts gets shorter units and one difficulty axis raised at a time.
        session_profile = ("casual" if audience.get("type") == "casual" and target <= 300
                           else "standard")
        models = genre_models.load()
        family_block = (models.get("families") or {}).get(a["genre"]["family"]) or {}
        generation = content.get("generation") or {}
        listed = content.get("units") or []
        content_units = (generation.get("expected_units") if generation.get("mode") == "procedural"
                         else len(listed))
        content_unit_kind = content["unit_kind"]
        kinds_word = content_unit_kind + ("" if content_unit_kind.endswith("s") else "s")
        locales = []
        for p in sorted(platforms, key=lambda p: not p.required):
            for locale in p.get("requirements", "locales_required", default=[]):
                if locale not in locales:
                    locales.append(locale)
        if "en" not in locales:
            locales.append("en")
        # Every face must set every locale in scope: a kit face that cannot is swapped for
        # its covering alternate (identity.ALTERNATES), never left to a system fallback.
        look, _swapped = identity.cover(look, locales, presentation.load_font_coverage())
        terminal = {
            "skill-only": f"Progression is the personal best. The loop is deliberately open, bounded by "
                          f"{content_units} {kinds_word} - there is no content treadmill to feed.",
            "linear-levels": f"Ends after level {content_units}: the set is complete, and replaying for stars "
                             "is the deliberate loop after that.",
            "unlock-track": f"Ends when all {content_units} {kinds_word} are unlocked; after that the "
                            "loop is chasing best times.",
        }.get(a["progression_model"], "Loops deliberately on score.")

        # 5. Retention hooks that fit the session and the exclusions.
        hooks = []
        for hook in a["retention_hooks"]:
            if hook == "daily_quest" and (target <= 120 or exclusions.mentions("daily", "quest", "metagame")):
                continue
            if hook == "leaderboard" and (exclusions.mentions("leaderboard") or
                                          not all(p.get("capabilities", "leaderboards") for p in platforms if p.required)):
                continue
            if exclusions.mentions(hook.replace("_", " ")):
                continue
            hooks.append(hook)
        targets = {}
        for criterion in strategy.get("success_criteria") or []:
            when = criterion.get("when") or {}
            for key in ("d1", "d7", "d30"):
                if when.get("left") == f"{key}_retention" and isinstance(when.get("right"), (int, float)):
                    targets[key] = when["right"]
        retention = {"hooks": hooks or ["none"], "return_reason": a["return_reason"],
                     "progression_loop": terminal}
        if targets:
            retention["targets"] = targets

        # 6. Features, tiered. The strategy's MVP is MVP; the archetype supplies the rest, minus exclusions.
        features = []
        deferred = {}  # candidate feature id -> the strategy exclusion that removed it
        for mechanic in a["mechanics"]:
            excluded = exclusions.match(mechanic["name"] + " " + mechanic["description"]) \
                if mechanic["tier"] != "mvp" else None
            if excluded:
                deferred[mechanic["id"]] = excluded[0]
                continue
            features.append({"id": mechanic["id"], "name": mechanic["name"], "tier": mechanic["tier"],
                             "description": mechanic["description"], "acceptance": list(mechanic["rules"])})
        features.append({
            "id": "game-flow", "name": "Game flow", "tier": "mvp",
            "description": "Boot, loading, title, play, pause and the result card, wired as build_spec.game_states.",
            "acceptance": [f"First session reaches play within {time_to_first_play}s of load on a mid-range phone.",
                           f"Retry from the result card starts a new {unit_word} within "
                           f"{'2' if is_level else '1'}s.",
                           "Pause on tab hidden; resume only on player input."],
        })
        metrics, seen = [], set()
        for criterion in (strategy.get("kill_criteria") or []) + (strategy.get("success_criteria") or []):
            left = (criterion.get("when") or {}).get("left")
            if left and left not in seen:
                seen.add(left)
                metrics.append((left, criterion["id"]))
        if metrics:
            features.append({
                "id": "telemetry", "name": "Kill and success criteria telemetry", "tier": "mvp",
                "description": "Emit the measurements the strategy's criteria read, so G4 is decided on data.",
                "acceptance": [f"Records `{metric}` for criterion {cid}." for metric, cid in metrics],
            })
        features.append({
            "id": "platform-integration", "name": "Platform integration", "tier": "mvp",
            "description": "Platform SDK init, loading progress, ads, cloud save and the other build_spec.sdk_touchpoints, "
                           "through the template's platform abstraction.",
            "acceptance": ["Each required touchpoint fires at its stated moment in a local platform-SDK mock.",
                           "No portal SDK is called directly from game code."],
        })
        features.append({
            "id": "localization", "name": "Localization", "tier": "mvp",
            "description": f"UI strings in {', '.join(locales)}, kept under 40 strings to make human translation cheap.",
            "acceptance": [f"Every UI string resolves in {', '.join(locales)}; no hard-coded text."],
        })
        for touchpoint in touchpoints:
            features.append({
                "id": f"monetization-{touchpoint['id']}", "name": f"{touchpoint['kind'].capitalize()} placement",
                "tier": touchpoint["tier"], "description": touchpoint["trigger"],
                "acceptance": [f"Offered only in state {touchpoint['state']}.", touchpoint["when_unavailable"]],
            })
        # The strategy's MVP is binding. An item an existing feature already covers is folded into
        # that feature's acceptance, so the implementer gets one feature, not two that overlap.
        # "Covers" is two shared significant words, or every significant word of the item (a
        # one-word item such as "Localization: en, ru" can never share two, and made a second
        # Localization feature - and a second plan task - beside the first).
        taken = {f["id"] for f in features}
        for item in strategy.get("mvp") or []:
            stems = _stems(item)
            covering = max(features, key=lambda f: len(stems & _stems(f["name"] + " " + f["description"])),
                           default=None)
            shared = stems & _stems(covering["name"] + " " + covering["description"]) if covering else set()
            if covering and (len(shared) >= 2 or (stems and shared == stems)):
                covering["acceptance"] = covering.get("acceptance", []) + [f"Strategy MVP: {item}."]
                if covering["tier"] != "mvp":
                    # The strategy outranks the archetype: promote, and keep the spec in step.
                    covering["tier"] = "mvp"
                    for touchpoint in touchpoints:
                        if covering["id"] == f"monetization-{touchpoint['id']}":
                            touchpoint["tier"] = "mvp"
                continue
            feature_id = "strategy-" + slug(item, 4)
            if feature_id in taken:
                continue
            taken.add(feature_id)
            features.append({"id": feature_id, "name": item, "tier": "mvp",
                             "description": f"Committed in the title strategy MVP: {item}.",
                             "acceptance": [f"Demonstrable in the prototype build: {item}.",
                                            "Covered by at least one smoke-test step."]})
        # The features depth rests on are matched without the words that name the core game
        # itself (its MVP mechanics): the strategy approved "track" and "level" as the game, so
        # an exclusion of music tracks or a level editor does not remove a stage map.
        depth_plan = resolved.depth
        depth_features = {f["id"] for f in depth_plan["features"]}
        core = _stems(" ".join(" ".join([m["name"], m["description"]] + list(m["rules"]))
                               for m in a["mechanics"] if m["tier"] == "mvp"))
        for tier, pool in (("post-mvp", a["post_mvp"] + depth_plan["features"]),
                           ("optional", a["optional"])):
            for candidate in pool:
                excluded = exclusions.match(candidate["name"] + " " + candidate["description"],
                                            core if candidate["id"] in depth_features else ())
                if excluded:
                    deferred[candidate["id"]] = excluded[0]
                    continue
                if candidate["id"] in taken:
                    continue
                taken.add(candidate["id"])
                features.append({"id": candidate["id"], "name": candidate["name"], "tier": tier,
                                 "description": candidate["description"]})
        # Every feature the brief or strategy names, and every one the genre family expects
        # (core/reference/feature-catalogue.yaml), evaluated rather than dropped or added: an
        # archetype feature that builds it is marked so; the rest are deferred or cut with a
        # reason (features.py).
        feature_check.evaluate_for_author(
            features, strategy, (a.get("genre") or {}).get("family"), platforms,
            exclusions.entries)
        features.sort(key=lambda f: TIER_ORDER.index(f["tier"]))

        # 7. The build spec.
        spec = self._build_spec(a, look, engine, orientation, resolution, is_level, touchpoints,
                                time_to_first_play, time_to_first_reward, run, target, audience,
                                exclusions, features, resolved.experience, locales)

        # The content, the axes it is measured on, and what getting better means. The genre
        # family (core/reference/genre-models.yaml) says which axes exist and what they mean;
        # the design declares the ones it uses and the units carry every number.
        genre = dict(a["genre"], session_profile=session_profile)
        spec["content"] = content
        spec["difficulty"]["axes"] = self._axes(a, family_block)
        spec["mastery"] = copy.deepcopy(a["mastery"])

        spec["depth"], optional = self._depth(depth_plan, features, spec, session, deferred)
        if optional:
            open_questions.append(
                "Depth the strategy excludes is stated as optional, not built: "
                + "; ".join(optional) + ". A superseding strategy admits it, or production "
                "adds it after G4.")

        for adopted in ((research or {}).get("patterns") or {}).get("adopt") or []:
            open_questions.append(
                f"Research: {adopted['numerator']} of {adopted['denominator']} comparable games "
                f"show {adopted['pattern']} - adopt it, or say why not (a co-occurrence, not "
                f"a proven effect).")
        if research is not None and ((research.get("patterns") or {}).get("adopt")):
            applied.append({"field": "open_questions", "source": "research",
                            "detail": "the patterns comparable games share, put to G3 as "
                                      "questions rather than built in unasked",
                            "claim_refs": sorted({p["claim"] for p in
                                                  research["patterns"]["adopt"]})})
        open_questions.insert(0, f"Archetype '{archetype_id}' was chosen because the {why_archetype}. "
                                 "Confirm at G3 that the loop is the one the strategy meant.")

        mvp_actions = [x for x in spec["controls"]["actions"] if x["tier"] == "mvp"]
        fantasy, art_direction = a["fantasy"], f"{look['concept']} Identity kit '{kit_id}'. {look['shape_language']}"
        if research is not None:
            statement = research["fantasy"].get("statement")
            theme = research["theme"]["theme"]
            setting = research["theme"]["setting"]
            context = ", ".join(x["label"].split(" (")[0] for x, facet in
                                ((theme, "theme"), (setting, "setting"))
                                if usable(research, x, facet) and x.get("label"))
            proposed = any(usable(research, x, f) == "proposal" for x, f in
                           ((theme, "theme"), (setting, "setting")))
            if statement:
                fantasy = (f"{statement}" + (f", in a {context.lower()} world" if context else "")
                           + f". In play: {a['fantasy']}")
                applied.append({"field": "fantasy", "source": "research",
                                "detail": f"research fantasy: {statement}",
                                "claim_refs": sorted(set(
                                    (research["fantasy"]["player"].get("claim_refs") or [])
                                    + (research["fantasy"]["emotional"].get("claim_refs") or [])))})
            else:
                applied.append({"field": "fantasy", "source": "default",
                                "detail": "the archetype's fantasy: research coded no player "
                                          "fantasy for this cell"})
            if context:
                art_direction = f"Theme from research: {context}. " + art_direction
                applied.append({"field": "theme", "source": "research",
                                "detail": (f"the opportunity's proposed theme - the hypothesis "
                                           f"this title tests, not an observation: {context}"
                                           if proposed else
                                           f"theme carried into fantasy and art direction: "
                                           f"{context}"),
                                "claim_refs": sorted(set((theme.get("claim_refs") or [])
                                                         + (setting.get("claim_refs") or [])))})
            else:
                applied.append({"field": "theme", "source": "default",
                                "detail": "no theme: research coded none for this cell, and none "
                                          "is invented"})
            if basis == "research":
                art_direction = (f"Research art direction ({', '.join(matched)}). "
                                 + art_direction)
        # The content shape: research's `design_constraints` when the opportunity carries them,
        # the genre family's own model otherwise. Either way it is recorded, with the claims.
        constraints = (research or {}).get("design_constraints")
        constraints = constraints if isinstance(constraints, dict) and constraints else None
        source = "research" if constraints else "default"
        refs = sorted({ref for value in (constraints or {}).values() if isinstance(value, dict)
                       for ref in (value.get("claim_refs") or []) if ref})
        mvp_units = [u for u in listed if u.get("tier") == "mvp"]
        axis_ids = [axis["id"] for axis in spec["difficulty"]["axes"]]
        for field, detail in (
                ("genre.family",
                 f"{genre['family']}: the {family_block.get('label', genre['family'])} content "
                 f"model, {'the shape research coded for this cell' if constraints else
                           'the family this design shape belongs to'}; play is "
                 f"{genre['ending']} on a {session_profile} session"),
                ("build_spec.content",
                 f"{len(listed)} {content_unit_kind} unit(s), {generation.get('mode')} "
                 f"generation, {len(mvp_units)} of them in the MVP"),
                ("build_spec.difficulty.axes",
                 f"difficulty moves on {', '.join(axis_ids)}")):
            entry = {"field": field, "source": source, "detail": detail}
            if constraints and refs:
                entry["claim_refs"] = refs
            applied.append(entry)
        out = {
            "fantasy": fantasy,
            "core_loop": a["core_loop"],
            "genre": genre,
            "pillars": list(a["pillars"]),
            "engine": engine,
            "features": features,
            "scope": {
                "content_units": content_units,
                "content_unit_kind": content_unit_kind,
                "locales": locales,
                "asset_budget": params.get("asset_budget", 400),
                "progression_terminal": terminal,
                "out_of_scope": out_of_scope,
            },
            "session": session,
            "retention": retention,
            "monetization": {
                "economy": ("One purchase, no currency." if "iap" in kinds else
                            "No currency. " + ("The rewarded continue is the only economic action."
                                               if has_rewarded else "Ads are the only revenue.")),
                "currencies": [],
            },
            "progression": f"{a['progression_model'].replace('-', ' ').capitalize()}: " + "; ".join(
                f"{s['unlock_condition']} -> {s['grants']}" for s in spec["progression"]["steps"]) + ".",
            "difficulty": " ".join(f"{c['at']}: {c['description']}" for c in spec["difficulty"]["curve"])
                          + f" Assist: {spec['difficulty']['assist']}",
            "controls": " ".join(f"{x['action']}: {x['touch']} (touch)"
                                 + ("" if x["keyboard"].startswith("Not bound") else f", {x['keyboard']} (keyboard)")
                                 + "." for x in mvp_actions),
            "ux": {
                "onboarding": f"{spec['tutorial']['approach'].replace('-', ' ').capitalize()}. "
                              + spec["tutorial"].get("rationale", ""),
                "screens": [s["id"] for s in spec["screens"]],
                "accessibility": ("Every audio cue has a visual counterpart, so the game plays muted - which also "
                                  "covers the large share of portal traffic that plays with sound off. Colour is "
                                  "never the only signal. Text is at least 16 CSS px at the design resolution. A "
                                  "reduced-motion setting (and prefers-reduced-motion) disables shake and flashes."),
            },
            "art_direction": art_direction,
            "audio_direction": "Library music loop plus short library SFX, all compressed and loaded after first "
                               "play so audio never delays time to first play. Every cue has a visual twin.",
            "build_spec": spec,
            "open_questions": open_questions,
        }
        if research is not None:
            carried = {k: v for k, v in research.items() if k != "applied"}
            out["research"] = dict(carried, applied=applied)
        return out

    # -----------------------------------------------------------------------------------

    @staticmethod
    def _axes(a, family_block):
        """`build_spec.difficulty.axes`: the axes this design uses, declared from its genre
        family's own definitions. The declaration only - every value lives on a content unit,
        so there is exactly one place a difficulty number is written."""
        declared = list(a.get("difficulty_axes") or [])
        axes = []
        for axis in family_block.get("axes") or []:
            if axis.get("id") not in declared:
                continue
            entry = {"id": axis["id"], "range": list(axis.get("range") or [0, 1]),
                     "relief_allowed": True}
            if axis.get("description"):
                entry["description"] = str(axis["description"])
            axes.append(entry)
        return axes

    def _build_spec(self, a, look, engine, orientation, resolution, is_level, touchpoints,
                    time_to_first_play, time_to_first_reward, run, target, audience, exclusions,
                    features, ex, locales=()):
        fail_state = "level-fail" if is_level else "fail"
        # Decided first: whether keyboard bindings exist decides what the states may name.
        no_desktop = exclusions.mentions("desktop", "keyboard")
        tiers = {f["id"]: f["tier"] for f in features}
        states = [
            {"id": "boot", "tier": "mvp", "initial": True,
             "description": "Platform SDK init, language, saved progress.",
             "exits": [{"to": "loading", "on": "SDK init resolved or timed out (3 s)"}]},
            {"id": "loading", "tier": "mvp",
             "description": "Load the first-play asset group only; audio and later content stream afterwards.",
             "exits": [{"to": "play", "on": "First-play assets ready and this is the player's first session"},
                       {"to": "title", "on": "First-play assets ready and the player has played before"}]},
            {"id": "title", "tier": "mvp", "description": "Title, best score, play button.",
             "exits": [{"to": "play", "on": "Play pressed"}]},
            {"id": "play", "tier": "mvp", "description": "Gameplay with HUD.",
             "exits": [{"to": "pause", "on": "Pause pressed or tab hidden" if no_desktop
                        else "Pause pressed, Esc, or tab hidden"},
                       {"to": fail_state, "on": a["failure_condition"]}]
                      + ([{"to": "level-complete", "on": "All goal counters reach zero"}] if is_level else [])},
            {"id": "pause", "tier": "mvp", "description": "Play frozen, audio paused, pause menu shown.",
             "exits": [{"to": "play", "on": "Resume pressed"}, {"to": "title", "on": "Quit pressed"}]},
            {"id": fail_state, "tier": "mvp", "description": "Result card: score, best, retry, optional continue.",
             "exits": [{"to": "play", "on": "Retry pressed, or a continue was granted"},
                       {"to": "title", "on": "Menu pressed"}]},
        ]
        if is_level:
            states.append({"id": "level-complete", "tier": "mvp", "description": "Stars, score, next level.",
                           "exits": [{"to": "play", "on": "Next pressed"}, {"to": "title", "on": "Menu pressed"}]})
        states.append({"id": "settings", "tier": "post-mvp", "description": "Music and SFX volume, language, reduced motion.",
                       "exits": [{"to": "title", "on": "Back pressed"}]})
        states[2]["exits"].append({"to": "settings", "on": "Settings pressed"})

        rewarded = next((t for t in touchpoints if t["kind"] == "rewarded"), None)
        hud = [dict(h, **({"metric": ex["hud_metrics"][h["id"]]} if h["id"] in ex["hud_metrics"] else {}))
               for h in a["hud"]]
        used = {h["anchor"] for h in hud}
        pause_anchor = next(x for x in ("top-left", "top-right", "bottom-right") if x not in used)
        hud.append({"id": "pause-button", "tier": "mvp", "shows": "Pause button", "anchor": pause_anchor,
                    "updates_on": "Static", "feedback": "Press state within one frame"})

        screens = [
            {"id": "loading", "tier": "mvp", "state": "loading", "purpose": "Show honest progress while the first-play group loads.",
             "elements": ["Wordmark in the display face", "Progress bar driven by the loader, reported to the platform"],
             "layout": "Wordmark centred, progress bar in the lower third."},
            {"id": "title", "tier": "mvp", "state": "title", "purpose": "One obvious action: play.",
             "elements": ["Wordmark", "Best score", "Play button (primary)", "Sound toggle"],
             "actions": [{"label": "Play", "goes_to": "play"}],
             "layout": "Play button in the thumb zone of the lower third; best score directly above it."},
            {"id": "play", "tier": "mvp", "state": "play", "purpose": "Gameplay; only the HUD overlays it.",
             # A first session starts here, not at the title: the objective is on this screen.
             "elements": [f"Objective line until the first success: {ex['goal']}"]
                         + [h["shows"] for h in hud if h["tier"] == "mvp"],
             "actions": [{"label": "Pause", "goes_to": "pause"}],
             "layout": "HUD inside the safe area; nothing interactive in the play area except the game itself."},
            {"id": "pause", "tier": "mvp", "state": "pause", "purpose": "Stop without losing the run.",
             "elements": ["Dimmed frozen play behind", "Pause menu"],
             "actions": [{"label": "Resume", "goes_to": "play"}, {"label": "Quit", "goes_to": "title"}],
             "layout": "Menu centred; Resume is the largest target."},
            {"id": "result", "tier": "mvp", "state": fail_state, "purpose": "Show the outcome and make retrying the easiest thing to do.",
             "elements": ["Score of this " + ("attempt" if is_level else "run"), "Best score, with a new-best burst",
                          "Retry button (primary)"] + (["Continue button with ad glyph (when offered)"] if rewarded else [])
                         + ["Menu button"],
             "actions": [{"label": "Retry", "goes_to": "play"}, {"label": "Menu", "goes_to": "title"}]
                        + ([{"label": "Continue", "goes_to": "play"}] if rewarded else []),
             "layout": "Card slides up over dimmed play; Retry in the thumb zone, Continue above it, Menu small in a corner."},
        ]
        if is_level:
            screens.append({"id": "level-complete", "tier": "mvp", "state": "level-complete",
                            "purpose": "Celebrate, then move on.",
                            "elements": ["Stars stamped one by one", "Score", "Next button (primary)", "Menu button"],
                            "actions": [{"label": "Next", "goes_to": "play"}, {"label": "Menu", "goes_to": "title"}],
                            "layout": "Stars across the top third; Next in the thumb zone."})
        screens.append({"id": "settings", "tier": "post-mvp", "state": "settings",
                        "purpose": "Volume, language, reduced motion.",
                        "elements": ["Music volume", "SFX volume", "Language", "Reduced motion toggle", "Back"],
                        "actions": [{"label": "Back", "goes_to": "title"}],
                        "layout": "Single column list."})

        menus = [
            {"id": "title-menu", "tier": "mvp", "screen": "title", "items": [
                {"label": "Play", "action": "Enter play"},
                {"label": "Sound on/off", "action": "Toggle master mute; remembered", "tier": "mvp"},
                {"label": "Settings", "action": "Open settings", "tier": "post-mvp"}]},
            {"id": "pause-menu", "tier": "mvp", "screen": "pause", "items": [
                {"label": "Resume", "action": "Return to play"},
                {"label": "Restart", "action": "Start a new " + ("attempt" if is_level else "run")},
                {"label": "Sound on/off", "action": "Toggle master mute"},
                {"label": "Quit", "action": "Return to title; progress already saved"}]},
            {"id": "result-menu", "tier": "mvp", "screen": "result", "items": [
                {"label": "Retry", "action": "Start again immediately"}]
                + ([{"label": "Continue", "action": f"Show rewarded ad ({rewarded['id']}); on reward, resume"}] if rewarded else [])
                + [{"label": "Menu", "action": "Return to title"}]},
        ]

        actions = [dict(x) for x in a["actions"]]
        actions.append({"id": "pause", "action": "Pause", "tier": "mvp", "touch": "Pause button",
                        "mouse": "Pause button", "keyboard": "Esc or P", "gamepad": "Start"})
        if no_desktop:
            for action in actions:
                action["keyboard"] = "Not bound: desktop-specific controls are out of scope (title strategy)"
                action.pop("gamepad", None)
        device = audience.get("device")
        primary = {"mobile": "touch", "desktop": "touch-and-mouse", "both": "any"}.get(device, "any")

        ui = look["ui"]
        button = ui["button"]
        faces = identity.families(look["typography"])
        assets = [self._asset_in(dict(x), engine["dimension"]) for x in a["assets"]] + [
            {"id": "ui-kit", "type": "ui", "tier": "mvp",
             "description": "Buttons, panels and the result card, drawn in the identity kit",
             "count": 1, "source_preference": "procedural", "est_cost": 0, "spec": "9-slice panels, button states: idle, pressed, disabled",
             "role": "ui", "dimension": "2d",
             "readability": (f"Buttons filled {button['fill']} with {button['text']} labels at "
                             f"{ui['min_target_px']} px or larger, panels in {ui['surface']}: the primary "
                             "action (Play, Retry) is the largest, brightest target on its screen, and "
                             "no button looks like a browser default")},
            {"id": "icons", "type": "icon", "tier": "mvp", "description": "Play, pause, retry, menu, sound, ad glyph",
             "count": 6, "source_preference": "library", "est_cost": 10, "spec": "Single-colour SVG, 48px grid",
             "role": "icon", "dimension": "2d",
             "readability": "Each glyph recognisable without its label at 24 px inside a 48 px target; "
                            "pause and retry never confused"},
            {"id": "fonts", "type": "font", "tier": "mvp",
             "description": f"{look['typography']['display']} and {look['typography']['body']}"
                            + (f", numerals in {look['typography']['numeric']}"
                               if look["typography"].get("numeric") else ""),
             "count": len(faces), "source_preference": "library", "est_cost": 0,
             "spec": ("Files: " + "; ".join(f"{f} ({identity.font_source(f)})" for f in faces)
                      + ". SIL Open Font License 1.1, its OFL.txt shipped beside the files. "
                        "WOFF2 (TTF accepted), subset to the locales in scope"
                      + _subsets_clause(locales) + ", bundled under "
                        "public/assets and loaded through the runtime asset manifest with "
                        "@font-face; awaited (document.fonts.load) before the first UI frame."),
             "role": "font", "dimension": "2d",
             "readability": ("Every UI and HUD string is set in " + " / ".join(faces)
                             + ": the computed font-family of each button and HUD element "
                               "resolves to the bundled face and document.fonts.check passes "
                               "before the title screen; no system fallback is ever shown")},
            {"id": "wordmark", "type": "ui", "tier": "mvp", "description": "Title wordmark in the display face",
             "count": 1, "source_preference": "procedural", "est_cost": 0, "spec": "SVG",
             "role": "ui", "dimension": "2d",
             "readability": "The title in the display face, legible at 240 px wide on the loading and title screens"},
        ]
        audio = [dict(x) for x in a["audio"]] + [
            {"id": "ui-tap", "type": "ui", "tier": "mvp", "description": "Button press", "trigger": "Any button",
             "loop": False, "source_preference": "library", "est_cost": 5},
            {"id": "ui-fanfare", "type": "ui", "tier": "mvp", "description": "New best / level clear sting",
             "trigger": "New best or level clear", "loop": False, "source_preference": "library", "est_cost": 5},
        ]
        if engine["dimension"] == "2d":
            wrong = ("On desktop or a landscape phone the game plays in a centred portrait column with the ground "
                     "colour and texture filling the sides; a rotate prompt appears only if the column would be "
                     "narrower than 360 CSS px." if orientation == "portrait" else
                     "On a portrait phone the playfield letterboxes; a rotate prompt appears only if it would be "
                     "shorter than 320 CSS px.")
        else:
            wrong = ("On a portrait phone the camera widens its field of view to keep the next target in frame; "
                     "a rotate prompt appears only below 320 CSS px of height.")
        responsive = {
            "orientation": orientation,
            "design_resolution": resolution,
            "scale_mode": "expand" if engine["dimension"] == "2d" else "fill",
            "layouts": [
                {"id": "phone", "when": "shorter side < 600 CSS px",
                 "arrangement": "HUD at the top edge inside the safe area; primary buttons in the lower third for thumb reach."},
                {"id": "tablet", "when": "shorter side 600-900 CSS px",
                 "arrangement": "Same as phone, UI scaled by min(1.25, shorter side / 600)."},
                {"id": "desktop", "when": "width >= 1024 CSS px and pointer: fine",
                 "arrangement": "Playfield at design aspect, centred; HUD moves into the margins"
                                + ("." if no_desktop else "; keyboard hints shown on buttons.")},
            ],
            "min_touch_target_px": 48,
            "safe_area": "All HUD and buttons inset by env(safe-area-inset-*); nothing interactive within 16 CSS px of an edge.",
            "wrong_orientation": wrong,
            "resize": "Re-layout on resize and orientation change without restarting; a mid-play orientation change pauses.",
            "max_pixel_ratio": 2,
        }

        session_flow = [
            {"beat": "Load", "at_s": 0, "description": "Loading screen with real progress; only first-play assets."},
            {"beat": "First input", "at_s": time_to_first_play,
             "description": "First session: straight into play, tutorial steps inline."},
            {"beat": "First reward", "at_s": time_to_first_reward,
             "description": "The opening difficulty guarantees a reward before the first failure."},
            {"beat": "First failure", "at_s": time_to_first_play + run,
             "description": "Result card; retry is the obvious action" + ("; the continue offer appears from here." if rewarded else ".")},
            {"beat": "Retry loop", "description": "Retry, improve, fail again; difficulty assist kicks in if the player is stuck."},
            {"beat": "Natural stop", "at_s": target,
             "description": "A new best or a plateau; the result card shows the best so the player leaves on a high."},
        ]
        return {
            "mechanics": [dict(m, rules=list(m["rules"]), tier=tiers[m["id"]]) for m in a["mechanics"]
                          if m["id"] in tiers],
            "controls": {
                "primary_input": primary, "actions": actions,
                "pause": ("Pause button" + ("" if no_desktop else ", Esc or P")
                          + "; automatic on tab hidden and before any ad. Resume needs player input."),
                "notes": ("Desktop plays through the touch scheme: pointer events make a click a tap. No keyboard "
                          "or gamepad bindings, because the strategy excludes desktop-specific controls."
                          if no_desktop else
                          "Keyboard and mouse bindings are MVP on every platform: portal traffic includes desktop "
                          "even for a mobile-first title."),
            },
            "player_goals": dict(a["goals"]),
            "progression": {
                "model": a["progression_model"],
                "steps": [dict(s) for s in a["progression_steps"]],
                "persistence": "Personal best and unlocks; cloud save where the platform offers it, local storage otherwise.",
            },
            "difficulty": {"model": a["difficulty_model"], "curve": [dict(c) for c in a["curve"]], "assist": a["assist"]},
            "game_states": states,
            "screens": screens,
            "hud": hud,
            "menus": menus,
            "tutorial": dict(a["tutorial"], skippable=False, shown_once=True,
                             steps=[dict(s) for s in a["tutorial"]["steps"]]),
            "rewards": [dict(r) for r in a["rewards"]],
            "failure": dict({
                "condition": a["failure_condition"],
                "feedback": a["failure_feedback"],
                "retry": {"path": "Retry on the result card" + ("." if no_desktop else "; on desktop also Space or Enter."),
                          "time_to_retry_s": 2 if is_level else 1,
                          "keeps": "Personal best, unlocks and settings."},
            }, **({"continue_offer": rewarded["id"]} if rewarded else {})),
            "session_flow": session_flow,
            "monetization_touchpoints": touchpoints,
            "sdk_touchpoints": [],  # filled from the platform profiles by the module
            "assets": assets,
            "audio": audio,
            "responsive": responsive,
            "visual_identity": look,
            "experience": self._experience(ex, actions, time_to_first_play, time_to_first_reward,
                                           2 if is_level else 1),
        }

    @staticmethod
    def _depth(plan, features, spec, session, deferred):
        """build_spec.depth from the archetype's plan. An entry resting on a feature the strategy
        excludes is tiered optional with the exclusion named: deferred depth stays visible and
        is never claimed. Returns (depth, the deferred entries in words)."""
        known = depth_check.deliverers({"features": features, "build_spec": spec})
        optional = []

        def fitted(entry, text_key, label):
            entry = dict(entry)
            by = entry.get("delivered_by")
            if entry["tier"] != "optional" and by and by not in known:
                why = deferred.get(by)
                entry["tier"] = "optional"
                entry.pop("delivered_by")
                entry[text_key] = (f"{entry[text_key].rstrip('.')} (optional: the strategy excludes "
                                   f"'{why}')." if why else entry[text_key])
                optional.append(f"{label} ({why or by})")
            return entry

        meta = plan["meta"]
        meta_loop = fitted({k: v for k, v in meta.items() if k != "persists"}, "statement",
                           "the meta loop")
        meta_loop["persists"] = [fitted(p, "what", p["what"]) for p in meta["persists"]]
        depth = {
            "meta_loop": meta_loop,
            "goal_ladder": [fitted(g, "goal", g["goal"].rstrip(".")) for g in plan["goals"]],
            "content_schedule": [fitted(c, "rule", c["name"]) for c in plan["content"]],
            "first_session": {"target_s": session["first_session_seconds"],
                              "ends_on": plan["first_session_ends_on"], "tier": "mvp"},
            "return_hooks": [fitted(h, "statement", h["statement"].rstrip(".")) for h in plan["hooks"]],
        }
        return depth, list(dict.fromkeys(optional))

    @staticmethod
    def _asset_in(asset, dimension):
        """An archetype's world asset made in the engine's dimension: a pinned engine of the
        other dimension draws its characters as what that engine draws, never a sprite standing
        in a 3D scene (or a model flattened into a 2D one). UI, icons and fonts stay 2D."""
        if asset.get("dimension") in (None, dimension) or asset.get("role") in ("ui", "icon", "font"):
            return asset
        if dimension == "3d" and asset["type"] in ("sprite", "spritesheet"):
            asset.update(type="model", spec="Low-poly GLB built from a model spec, flat-shaded in "
                                            "the palette; the readability line is its brief")
        elif dimension == "2d" and asset["type"] == "model":
            asset.update(type="sprite", spec="Vector sprite in the palette; the readability line "
                                             "is its brief")
        asset["dimension"] = dimension
        return asset

    @staticmethod
    def _experience(ex, actions, time_to_first_play, time_to_first_reward, time_to_retry):
        """build_spec.experience from the archetype's contract and the session numbers."""
        acknowledged = []
        for action in actions:
            if action["tier"] != "mvp":
                continue
            if action["id"] == "pause":
                entry = {"visual": "Play freezes and the pause menu appears over it.",
                         "audio": "UI tap"}
            else:
                entry = ex["actions"][action["id"]]
            acknowledged.append(dict({"action": action["id"], "max_ack_ms": 100}, **entry))
        experience = {
            "goal": {"statement": ex["goal"], "metric": ex["goal_metric"], "shown_on": "play"},
            "lose": dict(ex["lose"]),
            "actions": acknowledged,
            "onboarding": {"teaches": list(ex["teaches"]), "grace": dict(ex["grace"]),
                           "reveals_answer": False},
            "first_30s": {"first_frame_s": 2, "playable_s": time_to_first_play,
                          "first_success_s": time_to_first_reward, "retry_s": time_to_retry},
        }
        if "win" in ex:
            experience["win"] = dict(ex["win"])
        return experience


register_author(ArchetypeAuthor.name, ArchetypeAuthor)

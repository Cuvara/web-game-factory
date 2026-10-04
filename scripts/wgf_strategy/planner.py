"""Opportunity -> title strategy. Pure, deterministic, and biased hard toward small titles.

`plan_strategy(opportunity, profiles, title_id, policy)` returns the body of a
title-strategy artifact (everything but provenance) or raises StrategyRefused. It reads
nothing but its arguments, the versioned genre models (core/reference/genre-models.yaml) and
the quality benchmark (core/reference/quality-benchmark.yaml), so the same opportunity and
profiles always produce the same strategy - which is what makes it
testable, and what lets a G2 reviewer re-derive it.

What it decides, following core/lifecycle/stages/strategy.md:

  platforms     every candidate checked against its profile; incompatible ones recorded
                and left out; exactly one `required`, the best fit for the audience
  monetization  the research hypothesis, reclassified when no platform can carry it, and
                placements cut to what the required platform supports
  scope         estimate -> timebox (7-14 days, refused beyond 21), one control scheme, a
                capped asset budget, reusable template systems, named exclusions
  content       the genre family the design will be held to, and its content shape: what one
                unit is, how many the MVP carries, the progression and difficulty models and
                the axes difficulty moves on - from research's `design_constraints` when it
                coded them, else the family's own default. An opportunity that resolves to no
                family (nothing before Research V2 did) commits to no content model, and the
                concept reads as it always has.
  budget        the content the run's quality tier commits to (factory.strategy.quality_tier,
                default release): at `release`, units, groups and distinct elements from the
                larger of the genre model's and the quality benchmark's bars, in the family's
                own unit, group and element kinds, with why that volume is enough; at `mvp`,
                the prototype's units. At `release` the `content` exclusion narrows to a
                second mode: the budget's groups are content sets the title commits to.
  brief         what the person's idea asks of the game, read through the brief intents of
                core/reference/mechanic-lexicon.yaml: hand-designed content makes the content
                shape authored and the text say so, a mode or the unlocks the brief names stay
                in scope. The strategy's own statements are then checked against the brief
                and the content model (`contradictions`), and a strategy that still
                contradicts them is refused rather than handed to G2 - "difficulty comes from
                one data-driven ramp, not hand-built levels" for a brief that asks for
                hand-designed courses was boilerplate, not a decision.
  bet terms     prototype_must_prove, success and kill criteria as criteria-expressions
  honesty       risks carried from the opportunity plus the ones this plan introduces,
                and the assumptions it takes on without checking

  research      a Research V2 opportunity (`opportunity.research`) is carried whole into
                `research` - theme, fantasy, art, gameplay, audience, competitors,
                benchmarks, patterns, monetization evidence, production, buildability and
                the claims behind them - and decides what it has evidence for: the control
                scheme it observed, a session target from measured run lengths, the
                audience type. Where it has nothing, the default is used and `applied` says
                so; nothing unknown is filled in.

It does not approve anything. The result is a draft that waits at G2.
"""

import math
import re

from wgflib import genre_models, mechanics

__all__ = ["Policy", "StrategyRefused", "plan_strategy", "contradictions", "brief_intents",
           "PLANNABLE_STATES", "QUALITY_TIERS", "DEFAULT_QUALITY_TIER",
           "resolve_quality_tier"]

PLANNABLE_STATES = ("discovered", "scored", "shortlisted", "approved", "promoted")

SCOPE_DAYS = {"xs": 5, "s": 9, "m": 14, "l": 21, "xl": 35}
SCOPE_ORDER = ("xs", "s", "m", "l", "xl")
LEVELS = ("low", "medium", "high")
ASSET_CAP = {"low": 30, "medium": 60, "high": 120}

MONETIZATION_CLASS = {
    "rewarded": "rewarded-led",
    "interstitial": "interstitial-led",
    "banner": "mixed-ads",
    "iap": "iap-led",
    "none": "none",
}
PLACEMENTS = ("rewarded", "interstitial", "banner", "iap")

# The research vocabulary's progression codes (core/reference/research-vocabulary.yaml) in the
# genre model's own progression models (core/reference/genre-models.yaml). One table, here:
# research says what carries across runs, the genre model says which models a family allows.
PROGRESSION_MODEL = {
    "level-sequence": "linear-levels",
    "unlock-track": "unlock-track",
    "collection": "unlock-track",
    "meta-currency": "meta-currency",
    "upgrades": "meta-currency",
    "prestige": "meta-currency",
    "best-score": "skill-only",
    "none": "skill-only",
}

# Concept keywords that raise technical cost. One category counts once.
TECH_SIGNALS = (
    ("networking", 2, ("multiplayer", "online", "pvp", "co-op", "coop", "real-time versus")),
    ("3d", 1, ("3d",)),
    ("physics", 1, ("physics", "ragdoll", "destruction")),
    ("audio-sync", 1, ("rhythm", "beat", "music")),
    ("procedural", 1, ("procedural", "generated")),
)

CONTROL_SCHEMES = (
    ("one-touch", ("one-touch", "one touch", "one-tap", "one tap", "single tap")),
    ("swipe", ("swipe",)),
    ("drag", ("drag", "slingshot", "pull back")),
    ("keyboard", ("keyboard", "wasd", "arrow keys")),
    ("point-and-click", ("click", "point and", "aim")),
    ("tap", ("tap", "touch")),
)

# (key, exclusion, keywords meaning the concept itself depends on it)
EXCLUSIONS = (
    ("multiplayer", "Multiplayer and any online play — networking multiplies the test surface "
                    "and needs a server nobody has budgeted",
     ("multiplayer", "online", "pvp", "co-op", "coop")),
    ("metagame", "Metagame layers: daily quests, battle pass, login rewards — retention systems "
                 "are validated after the core loop is, not before", ("quest", "daily", "battle pass")),
    ("customization", "Character or skin customization and a cosmetics shop",
     ("skin", "customiz", "cosmetic", "dress-up", "dress up")),
    ("editor", "Level editor or user-generated content", ("editor", "user-generated", "ugc")),
    ("narrative", "Story, cutscenes and dialogue — text multiplies localization cost",
     ("story", "narrative", "cutscene", "dialogue")),
    ("leaderboards", "Leaderboards beyond a personal best", ("leaderboard",)),
    ("content", "A second mode or content set — one proves the loop; more is content, not "
                "validation", ()),
)

# The `content` exclusion on a release-tier strategy: its budget's groups are content sets
# the strategy has just committed to, so only a second mode stays excluded.
RELEASE_CONTENT_EXCLUSION = ("A second mode; the release's content is the budget in "
                             "concept.content_model.budget, and nothing beyond it")

# The run's quality tier (factory.strategy.quality_tier). `release`: the content budget is
# what a published title carries (core/reference/quality-benchmark.yaml). `mvp`: the
# prototype's units only, for a run that stops at G4. Default release - new-game ends in a
# drafted release, and an MVP-sized release was judged "a demo, not a game"
# (docs/quality-gap-audit-2026-10.md, finding 1).
QUALITY_TIERS = ("mvp", "release")
DEFAULT_QUALITY_TIER = "release"


class StrategyRefused(ValueError):
    """The opportunity cannot become a rapid-production title as it stands."""


class Policy:
    """The envelope a strategy must fit. Overridable per workflow step (`with:`)."""

    FIELDS = {
        "min_timebox_days": 7,
        "target_timebox_days": 14,
        "max_timebox_days": 21,
        "max_platforms": 3,
        "default_session_seconds": 180,
        "min_session_seconds": 60,
        "max_session_seconds": 300,
        # Design's depth bar (core/reference/design-depth.yaml first_session.min_s, held equal
        # by test_strategy): a first session shorter is refused at design, after G2.
        "min_first_session_seconds": 120,
        "sessions_per_day_target": 3,
        "max_prototype_iterations": 2,
    }

    def __init__(self, **overrides):
        unknown = sorted(set(overrides) - set(self.FIELDS))
        if unknown:
            raise StrategyRefused(f"unknown strategy policy keys: {', '.join(unknown)}")
        for key, default in self.FIELDS.items():
            value = overrides.get(key, default)
            if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
                raise StrategyRefused(f"strategy policy {key} must be a positive number")
            setattr(self, key, value)
        if not (self.min_timebox_days <= self.target_timebox_days <= self.max_timebox_days):
            raise StrategyRefused("strategy policy needs min <= target <= max timebox days")

    @classmethod
    def from_params(cls, params):
        return cls(**dict(params or {}))


# -- helpers ------------------------------------------------------------------------------


def _text(*parts):
    return " ".join(p for p in parts if isinstance(p, str)).lower()


def _has(text, keywords):
    return any(re.search(r"(?<![a-z0-9])" + re.escape(k), text) for k in keywords)


def _sentence(value):
    value = (value or "").strip().rstrip(".")
    return value[:1].upper() + value[1:] if value else value


def operator_platforms(value):
    """A person's choice of target platforms (`with: {platforms: [...]}` or
    factory.strategy.platforms): a non-empty list of distinct platform ids, the first the
    required one. It replaces the opportunity's candidate list and the fit ranking - never
    the compatibility checks, and never G2, which still approves the strategy. None: no
    choice made."""
    if value is None:
        return None
    if not isinstance(value, list) or not value or \
            not all(isinstance(v, str) and v.strip() for v in value):
        raise StrategyRefused("strategy platforms must be a non-empty list of platform ids")
    ids = [v.strip() for v in value]
    if len(set(ids)) != len(ids):
        raise StrategyRefused(f"strategy platforms repeat an id: {', '.join(ids)}")
    return ids


def _placement_supported(profile, placement):
    capabilities = profile.get("capabilities") or {}
    ads = profile.get("ads") or {}
    if placement == "rewarded":
        return bool(ads.get("rewarded_available"))
    if placement == "interstitial":
        return "interstitial" in (capabilities.get("ads") or [])
    if placement == "banner":
        return bool(ads.get("banner_available"))
    if placement == "iap":
        return bool(capabilities.get("iap"))
    return placement == "none"


# -- the plan -----------------------------------------------------------------------------


def _known(fv):
    return isinstance(fv, dict) and fv.get("tier") in ("observed", "derived") \
        and fv.get("value") not in (None, [], "")


def _first(value):
    """A facet value's first entry: research codes `many` facets as a list."""
    if isinstance(value, list):
        return value[0] if value else None
    return value


def _family_for(families, *nodes):
    """The genre family whose `nodes` list one of `nodes`, or None. The opportunity's cell
    carries both its genre node and the vocabulary family it sits under, so no tree walk is
    needed here; a node no family lists resolves to nothing, and nothing is assumed."""
    for node in nodes:
        if not isinstance(node, str) or not node:
            continue
        for fid in sorted(families):
            if node in (families[fid].get("nodes") or []):
                return fid
    return None


def _plural(unit_kind):
    return f"{unit_kind}s"


def resolve_quality_tier(value):
    """The run's quality tier: `value` checked, or the default when None."""
    if value is None:
        return DEFAULT_QUALITY_TIER
    if value not in QUALITY_TIERS:
        raise StrategyRefused(f"quality_tier must be one of {', '.join(QUALITY_TIERS)}, "
                              f"not {value!r}")
    return value


def _bar(block, key, tier):
    """A quality-benchmark bar's value at `tier`, or None when the bar states none."""
    entry = (block or {}).get(key)
    value = entry.get(tier) if isinstance(entry, dict) else None
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None
def brief_intents(brief, lexicon=None):
    """The ids of the lexicon's `brief_intents` whose phrases `brief` contains."""
    lexicon = lexicon if lexicon is not None else mechanics.load()
    return {iid for iid, entry in (lexicon.get("brief_intents") or {}).items()
            if mechanics.phrases_in(brief or "", (entry or {}).get("phrases"))}


def _brief_unit(brief, intent):
    """The brief's own word for a unit of content - the first of the intent's `units` it
    uses - or `level`."""
    text = mechanics.normalize(brief)
    found = []
    for word in intent.get("units") or []:
        match = re.search(r"(?<![a-z0-9])" + re.escape(str(word)) + r"s?(?![a-z0-9])", text)
        if match:
            found.append((match.start(), str(word)))
    return min(found)[1] if found else "level"


def _statements(body):
    """The strategy's own statements, by field: what it says the game is and is not. The
    brief, and the assumptions that quote it, are the person's words and are not checked."""
    concept = body.get("concept") or {}
    scope = body.get("production_scope") or {}
    out = [("one_liner", body.get("one_liner")),
           ("concept.gameplay_direction", concept.get("gameplay_direction")),
           ("concept.replayability", concept.get("replayability"))]
    for field in ("mvp", "out_of_scope", "prototype_must_prove"):
        out += [(field, item) for item in body.get(field) or []]
    for field in ("reusable_systems", "scope_decisions"):
        out += [(f"production_scope.{field}", item) for item in scope.get(field) or []]
    return [(field, str(text)) for field, text in out if text]


def contradictions(body, lexicon=None):
    """The strategy statements that contradict what the brief, or the content model, asks.

    An intent is active when the brief names one of its phrases, or when it names a
    `difficulty_shape` and the content model resolved to it. A statement that contains one of
    an active intent's `contradicted_by` phrases is a contradiction."""
    lexicon = lexicon if lexicon is not None else mechanics.load()
    intents = lexicon.get("brief_intents") or {}
    sources = {iid: "the brief" for iid in brief_intents(body.get("brief"), lexicon)}
    model = (body.get("concept") or {}).get("content_model") or {}
    for iid, entry in intents.items():
        shape = (entry or {}).get("difficulty_shape")
        if shape and model.get("difficulty_shape") == shape:
            sources.setdefault(iid, f"the content model ({shape})")
    found = []
    for iid in sorted(sources):
        phrases = (intents[iid] or {}).get("contradicted_by")
        for field, text in _statements(body):
            for phrase in sorted(mechanics.phrases_in(text, phrases)):
                found.append(f"{field} says \"{text}\" ({phrase}), which contradicts "
                             f"{sources[iid]} ({iid})")
    return found


class _Plan:
    def __init__(self, opportunity, profiles, title_id, policy, vocabulary=None,
                 tier=DEFAULT_QUALITY_TIER, benchmark=None):
        self.opp = opportunity
        self.tier = tier
        self.benchmark = benchmark or {}
        research = opportunity.get("research")
        self.research = research if isinstance(research, dict) and \
            research.get("research_version") == 2 else None
        self.vocabulary = vocabulary or {}
        self.applied = []
        self.profiles = profiles
        self.title_id = title_id
        self.policy = policy
        self.concept = opportunity.get("concept") or {}
        self.audience = opportunity.get("audience") or {}
        self.estimates = opportunity.get("estimates") or {}
        self.text = _text(self.concept.get("genre"), self.concept.get("subgenre"),
                          self.concept.get("core_mechanic"), self.concept.get("core_loop"))
        # What the person's idea asks of the game (core/reference/mechanic-lexicon.yaml
        # brief_intents): read from the brief alone, and never from the catalog's words.
        self.lexicon = mechanics.load()
        self.intent_entries = self.lexicon.get("brief_intents") or {}
        self.intents = brief_intents(opportunity.get("brief"), self.lexicon)
        self.risks = []
        self.assumptions = []
        self.decisions = []
        self.operator = None
        # Set by content(): the content shape the title commits to, or None when no genre
        # family covers the opportunity.
        self.content_model = None
        self.idea_concept = None
        self._content_total = 0

    def risk(self, description, severity, mitigation=None, origin="strategy", claims=None):
        entry = {"description": description, "severity": severity, "origin": origin}
        if mitigation:
            entry["mitigation"] = mitigation
        if claims:
            entry["claim_refs"] = list(claims)
        self.risks.append(entry)

    def apply(self, field, source, detail, claims=None):
        entry = {"field": field, "source": source, "detail": detail}
        if claims:
            entry["claim_refs"] = sorted(set(claims))
        self.applied.append(entry)

    def assume(self, statement, invalidated_by, tier="hypothesis"):
        self.assumptions.append(
            {"statement": statement, "tier": tier, "invalidated_by": invalidated_by})

    # -- checks ---------------------------------------------------------------------------

    def check_opportunity(self):
        state = self.opp.get("state")
        if state not in PLANNABLE_STATES:
            raise StrategyRefused(
                f"opportunity {self.opp.get('id')} is {state!r}; strategy plans only "
                f"{', '.join(PLANNABLE_STATES)}")
        for key in ("genre", "core_mechanic", "core_loop"):
            if not self.concept.get(key):
                raise StrategyRefused(f"opportunity concept has no {key}; nothing to plan")
        if not self.opp.get("candidate_platforms"):
            raise StrategyRefused("opportunity names no candidate platforms")

    # -- scope ----------------------------------------------------------------------------

    def scope(self):
        days = self.estimates.get("dev_speed_days")
        scope = self.estimates.get("scope_complexity")
        if scope not in SCOPE_DAYS:
            scope = None
        if not isinstance(days, (int, float)) or days <= 0:
            days = SCOPE_DAYS[scope or "m"]
            self.assume(f"With no research estimate, a {scope or 'm'}-scope title takes about "
                        f"{days} days", "tech-plan milestones summing past the timebox "
                        "(guard plan_fits_timebox)")
        if scope is None:
            scope = next((s for s in SCOPE_ORDER if days <= SCOPE_DAYS[s]), "xl")

        policy = self.policy
        if scope == "xl" or days > policy.max_timebox_days:
            raise StrategyRefused(
                f"estimated {days} days at scope {scope!r} is outside the rapid-production "
                f"envelope (max {policy.max_timebox_days} days); re-scope the opportunity "
                f"rather than commit to it")

        if days > policy.target_timebox_days:
            timebox = policy.target_timebox_days
            self.decisions.append(
                f"Estimate of {days:g} days exceeds the {timebox}-day target: the timebox is "
                f"held at {timebox} and the MVP is limited to the core loop — design cuts to "
                f"fit, the timebox does not stretch")
            self.risk(f"Scope estimate ({days:g} days) is above the {timebox}-day timebox",
                      "medium", "Design must cut content, not the core loop; G3 checks the "
                                "plan against the timebox (plan_fits_timebox)")
        else:
            timebox = max(policy.min_timebox_days, int(math.ceil(days)))
        self.assume(f"The research estimate of {days:g} development days holds for the MVP "
                    f"as scoped here", "tech-plan milestones summing past the timebox "
                    "(guard plan_fits_timebox)")

        tech_points = {"xs": 0, "s": 0, "m": 1, "l": 2}[scope]
        signals = []
        for name, weight, keywords in TECH_SIGNALS:
            if _has(self.text, keywords):
                tech_points += weight
                signals.append(name)
        self.tech_signals = signals

        cost = self.estimates.get("asset_cost_usd")
        if isinstance(cost, (int, float)):
            asset_points = 0 if cost <= 500 else 1 if cost <= 2000 else 2
        else:
            asset_points = {"xs": 0, "s": 0, "m": 1, "l": 2}[scope]
        if "3d" in signals:
            asset_points += 1

        self.scope_complexity = scope
        self.estimate_days = days
        self.timebox = timebox
        self.technical_points = tech_points
        self.asset_complexity = LEVELS[min(asset_points, 2)]
        self.asset_cost = cost if isinstance(cost, (int, float)) else None

        if "networking" in signals:
            self.risk("The concept depends on online play, which multiplies test surface and "
                      "needs server infrastructure", "high",
                      "Prototype must prove the loop works against a simulated opponent "
                      "before any networking is built")

    def technical_complexity(self, monetization_class):
        points = self.technical_points + (1 if monetization_class in ("iap-led", "hybrid")
                                          else 0)
        return "low" if points == 0 else "medium" if points <= 2 else "high"

    # -- controls, session ----------------------------------------------------------------

    def controls(self):
        text = _text(self.concept.get("core_mechanic"), self.concept.get("core_loop"))
        self.control_scheme = next(
            (scheme for scheme, keywords in CONTROL_SCHEMES if _has(text, keywords)), "tap")
        observed = ((self.research or {}).get("cell") or {}).get("controls")
        scheme = (self.vocabulary.get("control_schemes") or {}).get(
            (observed or {}).get("value")) if _known(observed) else None
        if scheme:
            self.control_scheme = scheme
            self.apply("concept.control_scheme", "research",
                       f"{scheme}: the control comparable games were coded with "
                       f"({observed.get('label') or observed['value']})",
                       observed.get("claim_refs"))
        elif self.research is not None:
            self.apply("concept.control_scheme", "default",
                       f"{self.control_scheme}: read from the concept's wording; research "
                       f"coded no control scheme for this cell")
        if self.control_scheme == "keyboard" and self.audience.get("device") in (None, "mobile",
                                                                                 "both"):
            self.risk("Keyboard controls do not exist on the mobile share of the audience",
                      "high", "Map the mechanic to a touch scheme in design, or narrow the "
                              "audience to desktop at G2")
        self.decisions.append(
            f"One control scheme ({self.control_scheme}); no alternative or desktop-specific "
            f"input")

    def session(self):
        policy = self.policy
        target = self.estimates.get("session_seconds")
        measured = next((b for b in (self.research or {}).get("benchmarks") or []
                         if b.get("facet") == "run_seconds"), None)
        if measured:
            target = measured["median"]
            self.apply("session.target_seconds", "research",
                       f"median run of {measured['n']} comparable games: "
                       f"{measured['median']:g} s (range {measured['min']:g}-"
                       f"{measured['max']:g})", [measured["claim"]])
        elif self.research is not None:
            self.apply("session.target_seconds", "default",
                       "no comparable game's run length was measured; the catalog estimate "
                       "or the policy default is used")
        if not isinstance(target, (int, float)) or target <= 0:
            target = policy.default_session_seconds
            self.assume(f"A {target}-second session suits this loop (no research estimate)",
                        "median_session_seconds in the prototype playtest")
        if target > policy.max_session_seconds:
            self.decisions.append(
                f"Target session cut from {target:g}s to {policy.max_session_seconds}s: short "
                f"sessions keep content needs small and fit portal play patterns")
            target = policy.max_session_seconds
        target = max(policy.min_session_seconds, int(round(target)))
        first = max(policy.min_session_seconds, policy.min_first_session_seconds,
                    int(round(target * 0.75 / 10.0)) * 10)
        if first > target:
            self.decisions.append(
                f"Target session raised from {target}s to {first}s: a first session must "
                f"last {policy.min_first_session_seconds}s to show the loop more than once")
            target = first
        self.session_body = {
            "first_session_seconds": min(first, target),
            "target_seconds": target,
            "sessions_per_day_target": policy.sessions_per_day_target,
        }
        self.assume(f"Players sustain a {target}-second session",
                    "median_session_seconds in the prototype playtest or first performance "
                    "review")

    # -- content --------------------------------------------------------------------------

    def content(self):
        """`concept.content_model`: the content shape the design is held to. None when no
        genre family resolves - then the concept keeps the wording it had before genre models
        existed, because nothing here knows what a unit of this game is."""
        self.content_model = None
        self.idea_concept = None
        self._content_total = 0
        research = self.research or {}
        constraints = research.get("design_constraints")
        constraints = constraints if isinstance(constraints, dict) else {}
        cell = research.get("cell") or {}
        families = genre_models.load().get("families") or {}
        refs = set()
        family, source = None, "default"
        declared = constraints.get("family")
        if isinstance(declared, dict) and declared.get("value") in families:
            family, source = declared["value"], "research"
            refs.update(declared.get("claim_refs") or [])
        if family is None:
            model_id = (research.get("capability") or {}).get("genre_model")
            if isinstance(model_id, str) and model_id in families:
                family = model_id
        if family is None:
            family = _family_for(families,
                                 (cell.get("genre") or {}).get("value"),
                                 (cell.get("family") or {}).get("value"))
        if family is None:
            if self.research is not None:
                self.apply("concept.content_model", "default",
                           "none: no genre family covers this opportunity's genre node, so "
                           "the strategy commits to no content shape and design states one")
            return
        model = families[family]
        units = model.get("units") or {}
        kinds = list(model.get("unit_kinds") or []) or ["level"]
        allowed = list(model.get("progression_models") or []) or ["linear-levels"]

        def coded(key):
            """What research coded for `key`, or None. An unknown facet stays unknown: the
            family's default is used, and `applied` says a default decided it."""
            value = constraints.get(key)
            if isinstance(value, dict) and value.get("tier") in ("observed", "derived") \
                    and value.get("value") not in (None, [], ""):
                refs.update(value.get("claim_refs") or [])
                return value["value"]
            return None

        unit_kind = _first(coded("unit_kind"))
        if unit_kind not in kinds:
            unit_kind = kinds[0]
        researched = coded("progression")
        researched = researched if isinstance(researched, list) else [researched]
        progression = next((PROGRESSION_MODEL[v] for v in researched
                            if v in PROGRESSION_MODEL and PROGRESSION_MODEL[v] in allowed),
                           allowed[0])
        shape = _first(coded("difficulty_shape"))
        if not isinstance(shape, str):
            shape = (model.get("difficulty_models") or ["level-authored"])[0]
        for iid in sorted(self.intents):
            asked = (self.intent_entries.get(iid) or {}).get("difficulty_shape")
            if asked and asked != shape and asked in (model.get("difficulty_models") or []):
                shape = asked
                self.apply("concept.content_model", "brief",
                           f"{shape} difficulty: the brief asks for it ({iid}), and the "
                           f"{family} family allows it")
        axes = coded("difficulty_axes")
        if not isinstance(axes, list) or not axes:
            axes = [a["id"] for a in model.get("axes") or [] if isinstance(a, dict)
                    and a.get("id")]
        # On a genre-model entry (no hand-coded design archetype), the catalog entry is a
        # capability - the family the Factory can build - and the person's idea is the game:
        # the concept is read from the brief, the family's loop says what a session of it
        # is, and the family's content model bounds what it must list. The catalog's own
        # concept wording would otherwise replace the idea with the seed's game.
        brief = self.opp.get("brief")
        capability = research.get("capability") or {}
        if brief and not capability.get("design_archetype") and model.get("loop"):
            self.idea_concept = {
                "core_mechanic": brief,
                "core_loop": str(model["loop"]),
                "one_liner": brief if brief.rstrip().endswith((".", "!", "?")) else f"{brief}.",
            }
            self.apply("concept", "brief",
                       f"the idea is the concept: research named no design archetype, so the "
                       f"{family} family's model bounds the content and the brief says what "
                       f"the game is")
        self.content_model = {
            "family": family,
            "unit_kind": unit_kind,
            "progression": progression,
            "difficulty_shape": shape,
            "difficulty_axes": list(axes),
            "min_units": int(units.get("min_mvp") or 1),
            "source": source,
            "quality_tier": self.tier,
        }
        self.content_model["budget"] = self._budget(model, genre_models.load())
        self._content_total = self.content_model["budget"]["units"]
        if self.research is not None:
            detail = (f"{family} ({model.get('label', family)}): "
                      f"{self.content_model['min_units']} {_plural(unit_kind)} in the MVP, "
                      f"progression {progression}, {shape} difficulty on "
                      f"{', '.join(self.content_model['difficulty_axes'])}")
            if self.content_model["source"] == "research":
                self.apply("concept.content_model", "research",
                           f"{detail} - the shape research coded for this cell",
                           sorted(refs))
            else:
                self.apply("concept.content_model", "default",
                           f"{detail} - the genre model's default; research coded no content "
                           f"shape for this cell")

    def _budget(self, model, models):
        """`concept.content_model.budget`: the content the title commits to at its quality
        tier, counted in the family's own unit, group and element kinds. At `release` every
        quantity is the larger of the genre model's bar and the quality benchmark's; at `mvp`
        it is the prototype's units and nothing more. `basis` records both numbers behind
        each quantity; the justification is written by body(), once the session and the
        platforms are known."""
        units = model.get("units") or {}
        shape = model.get("budget") or {}
        min_mvp = int(units.get("min_mvp") or 1)
        references = [f"genre-models@{models.get('version')}"]
        if self.tier == "mvp":
            return {"units": min_mvp, "references": references,
                    "basis": [{"quantity": "units", "genre_model": min_mvp, "value": min_mvp}]}

        content = self.benchmark.get("content") or {}
        references.append(f"quality-benchmark@{self.benchmark.get('version')}")
        family_total = int(units.get("min_total") or min_mvp)
        bench_total = _bar(content.get("units"), "min_total", self.tier)
        total = max(family_total, int(bench_total or 0), min_mvp)
        basis = [{"quantity": "units", "genre_model": family_total}]
        if bench_total is not None:
            basis[0]["benchmark"] = int(bench_total)
        budget = {"units": total, "references": references, "basis": basis}

        group_kind = shape.get("group_kind")
        groups = _bar(content.get("units"), "min_groups", self.tier)
        per_group = _bar(content.get("units"), "min_units_per_group", self.tier)
        if isinstance(group_kind, str) and group_kind and groups:
            groups, per_group = int(groups), int(per_group or 1)
            total = max(total, groups * per_group)
            budget["groups"] = {"kind": group_kind, "count": groups,
                                "min_units_per_group": per_group}
            basis.append({"quantity": "groups", "benchmark": groups, "value": groups})
            basis.append({"quantity": "min_units_per_group", "benchmark": per_group,
                          "value": per_group})
        budget["units"] = basis[0]["value"] = total

        elements = content.get("elements")
        distinct = _bar(elements, "min_distinct", self.tier)
        if distinct:
            budget["elements"] = {"count": int(distinct),
                                  "kinds": [str(k) for k in shape.get("element_kinds") or []]}
            intro = _bar(elements, "min_introduction_points", self.tier)
            if intro:
                budget["elements"]["min_introduction_points"] = int(intro)
            basis.append({"quantity": "elements", "benchmark": int(distinct),
                          "value": int(distinct)})
        designed = _bar(content.get("units"), "min_total_designed_s", self.tier)
        if designed:
            budget["designed_play_s"] = int(designed)
            basis.append({"quantity": "designed_play_s", "benchmark": int(designed),
                          "value": int(designed)})
        return budget

    def _justify(self, platform_names):
        """Why the budget's volume is enough, per the five things a G2 reviewer weighs. Each
        line is derived from the numbers the budget and the plan already hold."""
        content = self.content_model
        budget = content["budget"]
        kind, kinds = content["unit_kind"], _plural(content["unit_kind"])
        units = budget["units"]
        target = self.session_body["target_seconds"]
        per_day = self.session_body["sessions_per_day_target"]
        portals = (" and ".join([", ".join(platform_names[:-1]), platform_names[-1]])
                   if len(platform_names) > 1 else "".join(platform_names))
        if self.tier == "mvp":
            return {
                "session_length": (
                    f"The {units} MVP {kinds} only have to show the loop more than once in a "
                    f"{target}-second session; volume is not what a tier-mvp run tests."),
                "progression_structure": (
                    f"{content['progression']} over {units} {kinds}: enough to see the "
                    f"difficulty move, not a progression a player finishes."),
                "mechanics": "The core loop's own elements; no element budget at tier mvp.",
                "replayability": self._replayability(),
                "platform_expectations": (
                    f"A tier-mvp build is evidence for G4, not a release for {portals}; "
                    f"publishing it needs a new strategy at tier release."),
            }
        designed = budget.get("designed_play_s") or 0
        sessions = int(math.ceil(designed / float(target))) if designed else 0
        lines = {
            "session_length": (
                f"{units} {kinds} carry at least {designed} s of designed play, {sessions} "
                f"or more full {target}-second sessions of new {kinds}, the floor measured on "
                f"releases a person judged shippable; at {per_day:g} sessions a day the "
                f"replay system, not new {kinds}, carries the days after."
                if designed else
                f"{units} {kinds} at a {target}-second session."),
        }
        groups = budget.get("groups")
        if groups:
            lines["progression_structure"] = (
                f"{content['progression']}: {groups['count']} {groups['kind']}s of at least "
                f"{groups['min_units_per_group']} {kinds} each, each {groups['kind']} gated "
                f"behind the last, so there is always a next {groups['kind']} in view and "
                f"each one is a themed set rather than more of one list.")
        else:
            lines["progression_structure"] = (
                f"{content['progression']}: one sequence of {units} {kinds}; this family has "
                f"no group above the {kind}, so progression is the sequence itself and the "
                f"record kept per {kind}.")
        elements = budget.get("elements")
        if elements:
            named = ", ".join(elements["kinds"]) or "distinct elements"
            intro = elements.get("min_introduction_points")
            lines["mechanics"] = (
                f"At least {elements['count']} distinct elements ({named}) across the "
                f"{kinds}" + (f", introduced at {intro} or more points" if intro else "")
                + f", so later {kinds} change what the player does, not only a number.")
        else:
            lines["mechanics"] = "The quality benchmark states no element bar at this tier."
        lines["replayability"] = (
            f"{self._replayability()}; each {kind} keeps its own best result to replay for.")
        lines["platform_expectations"] = (
            f"{portals} list finished games beside this one: a release with "
            f"{units} {kinds} and new elements in later ones reads as a game, where the "
            f"{content['min_units']}-{kind} prototype would read as a demo.")
        return lines

    # -- platforms and monetization -------------------------------------------------------

    def platforms(self):
        hypothesis = self.opp.get("monetization_hypothesis") or {}
        primary = hypothesis.get("primary") or "none"
        secondary = [p for p in hypothesis.get("secondary") or [] if p in PLACEMENTS]

        candidates = []
        compatibility = {}
        source = self.operator if self.operator is not None else \
            self.opp.get("candidate_platforms") or []
        if self.operator is not None:
            missing = [p for p in self.operator if p not in self.profiles]
            if missing:
                raise StrategyRefused(f"the chosen platforms {', '.join(missing)} have no "
                                      f"platform profile in core/reference/platforms/")
            if len(self.operator) > int(self.policy.max_platforms):
                raise StrategyRefused(f"{len(self.operator)} platforms chosen, policy "
                                      f"max_platforms is {int(self.policy.max_platforms)}: "
                                      f"raise max_platforms deliberately or choose fewer")
            proposed = self.opp.get("candidate_platforms") or []
            self.decisions.append(
                f"Platforms chosen by a person, required first: {', '.join(self.operator)} "
                f"(the opportunity proposed {', '.join(proposed) or 'none'})")
        for platform_id in source:
            if platform_id in compatibility:
                continue
            profile = self.profiles.get(platform_id)
            if profile is None:
                compatibility[platform_id] = {
                    "id": platform_id, "profile_version": None, "compatible": False,
                    "issues": ["no platform profile in core/reference/platforms/"]}
                self.risk(f"Candidate platform {platform_id!r} has no profile and was left "
                          f"out", "low", "Add a profile before considering it again")
                continue
            candidates.append(platform_id)
        if not candidates:
            raise StrategyRefused("none of the candidate platforms has a platform profile")

        def carriers(placement):
            return [p for p in candidates if _placement_supported(self.profiles[p], placement)]

        if primary != "none" and not carriers(primary):
            fallback = next((p for p in secondary + ["rewarded", "interstitial"]
                             if p != primary and carriers(p)), "none")
            self.risk(f"The research monetization hypothesis ({primary}) is unsupported on "
                      f"every candidate platform; reclassified to {fallback}", "medium",
                      "G2 reviewer confirms the reclassified model still funds the title")
            self.decisions.append(f"Monetization reclassified from {primary} to {fallback}: "
                                  f"no candidate platform can carry {primary}")
            primary = fallback
        self.primary_placement = primary

        compatible = []
        for platform_id in candidates:
            profile = self.profiles[platform_id]
            issues = []
            if profile.get("status") != "verified":
                issues.append("profile figures are unverified")
            ok = primary == "none" or _placement_supported(profile, primary)
            if not ok:
                issues.append(f"no {primary} placements: the primary monetization is "
                              f"unsupported")
            for placement in secondary:
                if placement != primary and not _placement_supported(profile, placement):
                    issues.append(f"no {placement} placements: dropped on this platform")
            compatibility[platform_id] = {"id": platform_id,
                                          "profile_version": str(profile.get("version")),
                                          "compatible": ok, "issues": issues}
            if ok:
                compatible.append(platform_id)
        if not compatible:
            raise StrategyRefused(f"no candidate platform supports {primary} monetization")

        order = {p: i for i, p in enumerate(candidates)}
        if self.operator is not None:
            # A person's order stands: the fit ranking is the strategy's own guess at what a
            # person would choose, and here a person chose.
            ranked = [p for p in candidates if p in compatible]
            if ranked[0] != candidates[0]:
                self.risk(f"The platform chosen as required ({candidates[0]}) cannot carry "
                          f"{primary} monetization; {ranked[0]} is required instead", "high",
                          "G2 reviewer confirms the required platform")
        else:
            ranked = sorted(compatible, key=lambda p: (-self._fit(p, secondary), order[p]))
        required = ranked[0]
        chosen = ranked[:max(1, int(self.policy.max_platforms))]
        dropped = [p for p in ranked if p not in chosen]
        self.required = required
        self.chosen = [p for p in candidates if p in chosen]
        self.dropped = dropped

        placements = [primary] if primary != "none" else []
        placements += [p for p in secondary if p not in placements
                       and _placement_supported(self.profiles[required], p)]
        self.placements = placements
        cls = MONETIZATION_CLASS[primary]
        if cls == "rewarded-led" and "iap" in placements:
            cls = "hybrid"
        self.monetization = {"class": cls, "placements": placements}
        rationale = hypothesis.get("rationale")
        observed = [p for p in ((self.research or {}).get("monetization") or {}).get(
            "placements") or [] if p.get("numerator")]
        if observed:
            seen = "; ".join(f"{p['trigger']} in {p['numerator']} of {p['denominator']}"
                             for p in observed[:4])
            rationale = ((rationale + " ") if rationale else "") + \
                f"Comparable games offer placements at: {seen}."
            self.apply("monetization.rationale", "research",
                       f"placement moments comparable games use: {seen}",
                       [p["claim"] for p in observed])
        elif self.research is not None:
            self.apply("monetization.rationale", "default",
                       "no comparable game's placements were coded; the shape's own "
                       "hypothesis stands")
        if rationale:
            self.monetization["rationale"] = rationale
        if primary != "none":
            self.assume(f"{_sentence(primary)} placements monetize this loop the way research "
                        f"expects", f"{primary} opt-in or fill rate in the first performance "
                                    f"review")

        for platform_id in candidates:
            entry = compatibility[platform_id]
            entry["sdk"] = self._sdk(self.profiles[platform_id])
            entry["constraints"] = self._constraints(self.profiles[platform_id])
            if platform_id in dropped:
                entry["issues"].append(f"left out: at most {int(self.policy.max_platforms)} "
                                       f"platforms per title")
        self.compatibility = list(compatibility.values())

        for platform_id in self.chosen:
            profile = self.profiles[platform_id]
            if profile.get("status") != "verified":
                self.assume(f"The {profile.get('name', platform_id)} profile "
                            f"(v{profile.get('version')}) matches the portal's current rules",
                            "a validation failure or rejection citing a rule the profile does "
                            "not state")
        required_profile = self.profiles[required]
        interval = (required_profile.get("ads") or {}).get("interstitial_min_interval_s")
        target = self.session_body["target_seconds"]
        if isinstance(interval, (int, float)) and target < interval:
            # Design's consistency rule `interstitial_interval_fits_session` blocks a session
            # shorter than a required platform's interstitial interval; a strategy that set
            # one would be approved at G2 and then refused at design.
            name = required_profile.get("name", required)
            if interval <= self.policy.max_session_seconds:
                raised = int(math.ceil(interval))
                self.session_body["target_seconds"] = raised
                self.decisions.append(
                    f"Target session raised from {target}s to {raised}s: {name}'s "
                    f"interstitial interval is {interval:g}s, and a shorter session cannot "
                    f"hold the ad model")
                for entry in self.assumptions:
                    if entry["statement"] == f"Players sustain a {target}-second session":
                        entry["statement"] = f"Players sustain a {raised}-second session"
            else:
                self.risk(f"The {target}s session is shorter than {name}'s {interval:g}s "
                          f"interstitial interval: at most one interstitial per session",
                          "high", "Lengthen the session in design or choose another "
                          "required platform at G2")
        locales = self._locales()
        if [locale for locale in locales if locale != "en"]:
            self.risk(f"Required locales {', '.join(locales)} must be localized by a person, "
                      f"not machine-translated", "medium",
                      "Keep in-game text to a short string table")

    def _fit(self, platform_id, secondary):
        profile = self.profiles[platform_id]
        regions = set(self.audience.get("regions") or [])
        primary_regions = set((profile.get("audience") or {}).get("primary_regions") or [])
        mix = (profile.get("audience") or {}).get("device_mix") or {}
        device = self.audience.get("device") or "both"
        device_fit = 0.5 if device == "both" else float(mix.get(device) or 0)
        supported = sum(1 for p in secondary if _placement_supported(profile, p))
        return 2 * len(regions & primary_regions) + device_fit + 0.25 * supported

    def _sdk(self, profile):
        capabilities = profile.get("capabilities") or {}
        requirements = profile.get("requirements") or {}
        has_ads = bool(capabilities.get("ads"))
        if not has_ads and requirements.get("loading_api") != "required":
            return {"id": "none", "features": []}
        features = ["init"]
        if requirements.get("loading_api") == "required":
            features.append("loading-progress")
        if has_ads:
            features.append("gameplay-start-stop")
        for placement in self.placements:
            if _placement_supported(profile, placement):
                features.append(placement)
        if has_ads and self.placements:
            features.append("pause-audio-during-ads")
        if capabilities.get("cloud_saves"):
            features.append("cloud-save")
        return {"id": profile["id"], "features": features}

    def _constraints(self, profile):
        requirements = profile.get("requirements") or {}
        ads = profile.get("ads") or {}
        constraints = []
        if requirements.get("locales_required"):
            constraints.append(f"Locales required: {', '.join(requirements['locales_required'])}")
        if requirements.get("max_bundle_mb"):
            constraints.append(f"Bundle at most {requirements['max_bundle_mb']} MB")
        if "interstitial" in self.placements and ads.get("interstitial_min_interval_s"):
            constraints.append(
                f"Interstitials at least {ads['interstitial_min_interval_s']}s apart")
        if requirements.get("loading_api") == "required":
            constraints.append("Loading progress reported through the SDK")
        if requirements.get("https_only"):
            constraints.append("HTTPS only")
        if requirements.get("external_requests") == "restricted":
            constraints.append("External requests only to declared domains")
        if requirements.get("no_external_links"):
            constraints.append("No external links")
        return constraints

    def _locales(self):
        locales = []
        for platform_id in self.chosen:
            for locale in (self.profiles[platform_id].get("requirements") or {}).get(
                    "locales_required") or []:
                if locale not in locales:
                    locales.append(locale)
        return locales

    def _bundle_mb(self):
        sizes = [(self.profiles[p].get("requirements") or {}).get("max_bundle_mb")
                 for p in self.chosen]
        sizes = [s for s in sizes if isinstance(s, (int, float))]
        return min(sizes) if sizes else None

    # -- the artifact body ----------------------------------------------------------------

    def body(self):
        concept = dict(self.concept)
        if getattr(self, "idea_concept", None):
            concept.update({k: v for k, v in self.idea_concept.items() if k != "one_liner"})
        opp = self.opp
        required_profile = self.profiles[self.required]
        genre = concept.get("subgenre") or concept.get("genre")
        mobile = self.audience.get("device") in (None, "mobile", "both")

        replay = self._replayability()
        content = self.content_model
        # Hand-designed content the brief asks for, with no genre family to shape it: said in
        # the brief's own unit, never as one generated ramp.
        authored = next((self.intent_entries[i] for i in sorted(self.intents)
                         if (self.intent_entries.get(i) or {}).get("difficulty_shape")), None)
        brief_unit = _brief_unit(opp.get("brief"), authored) if authored else None
        authored_model = content is not None and any(
            content["difficulty_shape"] == (e or {}).get("difficulty_shape")
            for e in self.intent_entries.values())
        if content is None and authored:
            content_direction = (f"Content: hand-designed {_plural(brief_unit)}, as the brief "
                                 f"asks, with difficulty authored per {brief_unit}.")
        elif content is None:
            content_direction = ("Difficulty comes from one data-driven ramp, not hand-built "
                                 "levels.")
        else:
            units = _plural(content["unit_kind"])
            axes = ", ".join(content["difficulty_axes"])
            content_direction = (
                f"Content: {content['min_units']} specified {units} in the prototype, "
                f"{self._content_total} in the release, difficulty authored per unit on "
                f"{axes}; progression {content['progression']}; "
                f"{content['difficulty_shape']} ramp.")
        concept_body = {
            "genre": concept["genre"],
            "core_mechanic": concept["core_mechanic"],
            "core_loop": concept["core_loop"],
            "gameplay_direction": (
                f"{_sentence(genre)} built on {concept['core_mechanic']}. A session is a short "
                f"run: {concept['core_loop']}. {content_direction}"),
            "control_scheme": self.control_scheme,
            "replayability": replay,
        }
        if concept.get("subgenre"):
            concept_body["subgenre"] = concept["subgenre"]
        if content is not None:
            content["budget"]["justification"] = self._justify(
                [self.profiles[p].get("name", p) for p in self.chosen])
            concept_body["content_model"] = content

        platform_set = []
        for platform_id in self.chosen:
            profile = self.profiles[platform_id]
            name = profile.get("name", platform_id)
            if platform_id == self.required and self.operator is not None:
                rationale = (f"Primary: chosen first by a person among {', '.join(self.operator)}"
                             f"; the title is not shippable without it.")
            elif platform_id == self.required:
                rationale = (f"Primary: best audience fit among compatible candidates"
                             f"{self._fit_reason(profile)}; the title is not shippable "
                             f"without it.")
            else:
                rationale = (f"Secondary: {name} is compatible from the same build; not "
                             f"required to ship.")
            platform_set.append({"id": platform_id, "profile_version":
                                 str(profile.get("version")),
                                 "role": "required" if platform_id == self.required
                                 else "optional", "rationale": rationale})

        audience_type = self.audience.get("type")
        if audience_type:
            if self.research is not None:
                player = (self.research.get("audience") or {}).get("player_type") or {}
                self.apply("audience.type", "research",
                           f"{audience_type}: {player.get('label') or player.get('value')}",
                           player.get("claim_refs"))
        else:
            audience_type = "casual"
            self.assume("The audience type is casual: research found no evidence for it, and "
                        "casual retention targets are the least demanding",
                        "platform analytics after launch")
            if self.research is not None:
                self.apply("audience.type", "default",
                           "casual: research coded no player type for this cell; it was "
                           "not assumed there, only here, as the planning default")
        device = self.audience.get("device")
        if not device:
            device = "both"
            self.assume("The audience plays on phone and desktop: no device split was "
                        "researched for it", "platform analytics device split after launch")
            if self.research is not None:
                self.apply("audience.device", "default",
                           "both: research recorded no device for this cell")
        elif self.research is not None:
            source = (self.research.get("audience") or {}).get("device") or {}
            self.apply("audience.device", "research",
                       f"{device}: {source.get('label') or source.get('source')} "
                       f"({source.get('tier')})", source.get("claim_refs"))
        audience = {"type": audience_type, "device": device}
        if self.audience.get("regions"):
            audience["regions"] = list(self.audience["regions"])
        audience["player_description"] = (
            f"A {audience['type']} player on {'a phone' if audience['device'] == 'mobile' else 'a desktop browser' if audience['device'] == 'desktop' else 'phone or desktop'}"
            f" who wants to be playing within seconds, in sessions of about "
            f"{self.session_body['target_seconds'] // 60 or 1} minute"
            f"{'s' if self.session_body['target_seconds'] >= 120 else ''}.")

        mvp = [
            f"Core loop: {concept['core_loop']}",
            (f"The brief, built in full: {concept['core_mechanic']}"
             if getattr(self, "idea_concept", None) else
             f"A single {self.control_scheme} control: {concept['core_mechanic']}"),
            (f"Hand-designed {_plural(brief_unit)}, as the brief asks, with difficulty "
             f"authored per {brief_unit}" if authored else
             "One content set with a data-driven difficulty ramp") if content is None else
            f"{content['min_units']} designed {_plural(content['unit_kind'])} with authored "
            f"difficulty on {', '.join(content['difficulty_axes'])}",
            "Score and personal best, persisted"
            + (" through the platform's cloud save" if "cloud-save" in
               self._sdk(required_profile)["features"] else " locally"),
        ]
        if "rewarded" in self.placements:
            mvp.append("A rewarded placement at a natural moment in the loop "
                       "(continue or bonus), never forced")
        if "interstitial" in self.placements:
            mvp.append("Interstitials between sessions only, never inside one")
        sdk = self._sdk(required_profile)
        if sdk["id"] != "none":
            mvp.append(f"{required_profile.get('name', self.required)} SDK: "
                       f"{', '.join(sdk['features'])}")
        locales = self._locales()
        if locales:
            mvp.append(f"Localization: {', '.join(locales)}")

        out_of_scope = []
        # The brief is part of the concept here: what it asks for is not excluded under it.
        asked = _text(self.text, opp.get("brief"))
        kept = {k for i in self.intents
                for k in (self.intent_entries.get(i) or {}).get("keeps_in_scope") or []}
        reworded = {}
        for i in sorted(self.intents):
            reworded.update((self.intent_entries.get(i) or {}).get("replaces_exclusion") or {})
        # A release-tier budget commits to content sets (its groups): "a second content
        # set" is no longer excluded, only a second mode is.
        if content is not None and content["quality_tier"] == "release" \
                and "content" not in reworded and "content" not in kept:
            reworded["content"] = RELEASE_CONTENT_EXCLUSION
            self.decisions.append(f"Exclusion narrowed to the release budget (content): "
                                  f"\"{RELEASE_CONTENT_EXCLUSION}\"")
        for key, exclusion, keywords in EXCLUSIONS:
            exclusion = reworded.get(key, exclusion)
            if (keywords and _has(asked, keywords)) or key in kept:
                self.risk(f"The concept depends on something rapid production would exclude "
                          f"({key}); it stays in scope and carries the cost", "medium",
                          "Design keeps the smallest version of it that serves the core loop")
                continue
            out_of_scope.append(exclusion)
        if self.monetization["class"] not in ("iap-led", "hybrid"):
            out_of_scope.append("An IAP economy or premium currency")
        if audience["device"] == "mobile":
            out_of_scope.append("A desktop-specific control scheme")
        if self.dropped:
            out_of_scope.append(f"Platforms beyond the set: {', '.join(self.dropped)} — "
                                f"platform sprawl multiplies compliance work")
        incompatible = [c["id"] for c in self.compatibility if not c["compatible"]]
        if incompatible:
            out_of_scope.append(f"Incompatible candidate platforms: {', '.join(incompatible)} "
                                f"(see platform_compatibility)")

        bundle = self._bundle_mb()
        must_prove = [
            f"A first-time player understands the {self.control_scheme} control without "
            f"instruction",
            f"The core loop produces an unforced desire to retry within one "
            f"{self.session_body['target_seconds']}-second session",
        ]
        for risk in opp.get("risks") or []:
            if risk.get("severity") == "high" and risk.get("description"):
                must_prove.append(f"This risk is contained: {_sentence(risk['description'])}")
        if "rewarded" in self.placements:
            must_prove.append("The rewarded placement reads as a favour rather than an "
                              "interruption")
        if mobile:
            must_prove.append("It holds 30 fps on a mid-range mobile browser"
                              + (f" inside a {bundle:g} MB bundle" if bundle else ""))
        for benchmark in (self.research or {}).get("benchmarks") or []:
            if benchmark.get("facet") == "time_to_first_reward_seconds":
                must_prove.append(
                    f"The first reward arrives within {benchmark['median']:g} s, the median of "
                    f"{benchmark['n']} comparable games")
                self.apply("prototype_must_prove", "research",
                           "first-reward bar from measured comparable games",
                           [benchmark["claim"]])

        retention = {"casual": 0.25, "midcore": 0.3, "core": 0.35}[audience["type"]]
        success = [
            {"id": "d1_retention", "label": "D1 retention",
             "when": {"left": "d1_retention", "op": "gte", "right": retention},
             "rationale": "Below this a short-session title without a metagame has no path to "
                          "sustained portal traffic.", "severity": "blocking"},
            {"id": "session_length", "label": "Median session near target",
             "when": {"left": "median_session_seconds", "op": "gte",
                      "right": self.session_body["first_session_seconds"]},
             "rationale": "Shorter than this and the placements the monetization model counts "
                          "on never get a chance to show.", "severity": "warning"},
        ]
        kill = [
            {"id": "control_not_understood", "label": "First-time players do not understand "
             "the control", "when": {"left": "first_time_understood_share", "op": "lt",
                                      "right": 0.6},
             "rationale": "The title is scoped around one control scheme and no tutorial. If "
                          "that scheme needs teaching, the scope assumption is wrong.",
             "severity": "blocking"},
            {"id": "no_retry_pull", "label": "Players do not retry unprompted",
             "when": {"left": "unprompted_retry_share", "op": "lt", "right": 0.5},
             "rationale": "Replay is the retention system here, in place of content. Without "
                          "immediate retry there is neither retention nor an ad moment.",
             "severity": "blocking"},
            {"id": "prototype_overran", "label": "The prototype consumed most of the timebox",
             "when": {"left": "prototype_elapsed_days", "op": "gt",
                      "right": int(math.ceil(self.timebox * 0.6))},
             "rationale": "A prototype that needs more than 60% of the timebox is evidence the "
                          "scope does not fit it, and production would overrun by more.",
             "severity": "blocking"},
        ]
        if mobile:
            kill.append({
                "id": "mobile_performance_floor", "label": "Unplayable on mid-range mobile",
                "when": {"left": "midrange_mobile_fps", "op": "lt", "right": 30},
                "rationale": "Most portal traffic for this audience is mobile; below 30 fps a "
                             "reaction-driven loop reads as the game's fault, not the "
                             "player's.", "severity": "blocking"})

        for risk in opp.get("risks") or []:
            if not risk.get("description"):
                continue
            high = risk.get("severity") == "high"
            self.risk(risk["description"], risk.get("severity") or "medium",
                      "Named in prototype_must_prove; answered before production" if high
                      else "Tracked into design", origin="opportunity",
                      claims=risk.get("claim_refs"))
        self.assume(f"The audience research describes ({audience['type']}, "
                    f"{audience['device']}) is the audience {required_profile.get('name', self.required)} "
                    f"delivers", "platform analytics device and region split after launch",
                    tier="derived")

        tech = self.technical_complexity(self.monetization["class"])
        systems = [
            "Template boot flow: loading, menu, play, result",
            "Template platform SDK adapter: one interface, one implementation per platform",
            f"Input handler for the {self.control_scheme} scheme only",
            "Score and personal-best persistence",
            (f"Content as data: every designed {(content or {}).get('unit_kind') or brief_unit}"
             f" with its difficulty values" if authored or authored_model
             else "Data-driven difficulty ramp"),
        ]
        if self.placements:
            systems.append("Ad-break service honouring the strictest interstitial interval, "
                           "pausing audio and input")
        if [locale for locale in locales if locale != "en"]:
            systems.append("Localization string table")
        cap = ASSET_CAP[self.asset_complexity]
        if content is not None:
            budget = content["budget"]
            committed = [f"{budget['units']} {_plural(content['unit_kind'])}"]
            if budget.get("groups"):
                committed.append(f"{budget['groups']['count']} "
                                 f"{budget['groups']['kind']}s")
            if budget.get("elements"):
                committed.append(f"{budget['elements']['count']} distinct elements")
            self.decisions.append(
                f"Quality tier {self.tier}: the content budget is "
                f"{', '.join(committed)} (concept.content_model.budget)"
                + (", the larger of the genre model's and the quality benchmark's bars"
                   if self.tier == "release" else ", the MVP only: this run is not a release"))
            if self.tier == "release":
                self.assume(
                    f"The release content budget ({', '.join(committed)}) can be built "
                    f"inside the {self.timebox}-day timebox",
                    "tech-plan milestones summing past the timebox (guard plan_fits_timebox)")
        else:
            self.decisions.append(
                f"Quality tier {self.tier}: no genre family covers the concept, so no "
                f"content budget is committed here; design states the content shape")
        decisions = list(self.decisions) + [
            f"One required platform ({self.required}); every other platform is optional",
            f"Replay comes from a system ({replay.split(':')[0].lower()}), not from more "
            f"content",
            f"Asset budget capped at {cap} unique assets ({self.asset_complexity} asset "
            f"complexity)",
        ]
        production = {
            "scope_complexity": self.scope_complexity,
            "technical_complexity": tech,
            "asset_complexity": self.asset_complexity,
            "estimate_days": self.estimate_days,
            "asset_budget": {"max_unique_assets": cap},
            "reusable_systems": systems,
            "scope_decisions": decisions,
        }
        if self.asset_cost is not None:
            production["asset_budget"]["estimated_cost_usd"] = self.asset_cost
        if tech == "high":
            self.risk(f"High technical complexity ({', '.join(self.tech_signals) or 'scope'}) "
                      f"in a {self.timebox}-day timebox", "high",
                      "Prototype the riskiest system first; G4 kills on prototype_overran")

        claims = opp.get("claim_refs") or []
        brief = opp.get("brief")
        if brief and getattr(self, "idea_concept", None):
            self.assume(
                f"The brief (\"{brief}\") is the concept: the {genre} shape research "
                f"selected names no design archetype, so the family's content model bounds "
                f"the design and the design states the idea's mechanics in full",
                "the design cannot state the idea's mechanics within the family's model and "
                "the timebox; then the shape is a capability gap, not this title")
        elif brief:
            # The person's idea is recorded as `brief` and here, never folded into the
            # one-liner: design fits its archetype to the concept research selected as
            # buildable, and the brief's words must not re-pick it.
            self.assume(
                f"The brief (\"{brief}\") can be built on the {genre} shape research selected: "
                f"{concept['core_mechanic']}",
                "design cannot realise the brief's mechanic within this shape and timebox; "
                "the prototype then plays as the shape, not as the brief")
        research_note = ""
        if self.research is not None:
            research_note = (f" Research ({self.research['origin']}): "
                             f"{self.research.get('summary', '').rstrip('.')}.")
            claims = sorted(self.research["basis"]["claim_refs"]) or claims
        why = (f"{opp.get('title', opp.get('id'))} offers {(concept.get('fantasy') or concept['core_loop']).rstrip('.')}.{research_note} "
               f"The opportunity rests on {opp.get('hypothesis') or 'an unstated hypothesis'}"
               + (f" and cites {', '.join(claims)}" if claims else ", with no claims cited")
               + f". {required_profile.get('name', self.required)} is primary"
               + f"{self._fit_reason(required_profile)}.")

        body = {
            "title_id": self.title_id,
            "opportunity_id": opp["id"],
            "one_liner": (self.idea_concept["one_liner"] if getattr(self, "idea_concept", None)
                          else f"A {genre} game where the player uses {concept['core_mechanic']}."),
            "why_this_opportunity": why,
            "platform_set": platform_set,
            "audience": audience,
            "monetization": self.monetization,
            "session": self.session_body,
            "timebox_days": self.timebox,
            "mvp": mvp,
            "out_of_scope": out_of_scope,
            "prototype_must_prove": must_prove,
            "success_criteria": success,
            "kill_criteria": kill,
            "sunset_floor": {"metric": "d1_retention", "value": round(retention / 2, 3),
                             "consecutive_reviews": 2},
            "max_prototype_iterations": int(self.policy.max_prototype_iterations),
            "rollback_threshold": "critical",
            "concept": concept_body,
            "production_scope": production,
            "platform_compatibility": self.compatibility,
            "risks": self.risks,
            "assumptions": self.assumptions,
        }
        if brief:
            body["brief"] = brief
        if self.research is not None:
            body["research"] = self.handoff()
        return body

    def handoff(self):
        """The research carried to design. Every facet keeps its tier and claims; an unknown
        facet stays unknown, and `design_constraints` - the content shape, in the genre model's
        vocabulary - is carried whole beside the buildability it belongs to."""
        r = self.research
        cell = r.get("cell") or {}

        def fv(name):
            value = cell.get(name)
            if isinstance(value, dict):
                return value
            return {"value": None, "tier": "unknown", "source": "unknown",
                    "reason": f"research recorded no {name}"}

        player, emotional = fv("player_fantasy"), fv("emotional_fantasy")
        intent = r.get("changed_axis") or {}
        statement = None
        if _known(player) or (intent.get("facet") == "player_fantasy" and player.get("value")):
            statement = player.get("label", player["value"]).split(" (")[0]
            if _known(emotional):
                statement += " - " + emotional.get("label", emotional["value"]).split(" (")[0].lower()
        out = {
            "research_version": 2,
            "report_id": r["report_id"],
            "opportunity_id": self.opp["id"],
            "origin": r["origin"],
            "summary": r.get("summary", ""),
            "theme": {"theme": fv("theme"), "setting": fv("setting")},
            "fantasy": {"player": player, "emotional": emotional},
            "art": {k: fv(f"art_{k}") for k in ("dimension", "rendering", "tone", "palette")},
            "gameplay": {k: fv(k) for k in ("genre", "mechanics", "gameplay_steps", "controls",
                                            "core_loop", "progression", "difficulty_shape",
                                            "retention_hooks")},
            "audience": r["audience"],
            "competitors": r["competitors"],
            "benchmarks": r["benchmarks"],
            "patterns": r["patterns"],
            "monetization": r["monetization"],
            "production": r["production"],
            "capability": r["capability"],
            "market": r.get("market") or [],
            "risks": r.get("risks") or [],
            "confidence": r["confidence"],
            "claim_refs": sorted(set(r.get("claim_refs") or [])),
            "applied": list(self.applied),
        }
        out["art"]["camera"] = fv("camera")
        if isinstance(r.get("design_constraints"), dict):
            out["design_constraints"] = r["design_constraints"]
        if intent:
            out["changed_axis"] = intent
        if statement:
            out["fantasy"]["statement"] = statement
        return out

    def _fit_reason(self, profile):
        regions = sorted(set(self.audience.get("regions") or [])
                         & set((profile.get("audience") or {}).get("primary_regions") or []))
        parts = []
        if regions:
            parts.append(f"audience regions {', '.join(regions)}")
        if self.primary_placement != "none":
            parts.append(f"supports {self.primary_placement} placements")
        return f" ({'; '.join(parts)})" if parts else ""

    def _replayability(self):
        loop = _text(self.concept.get("core_loop"), self.concept.get("core_mechanic"))
        if _has(loop, ("procedural", "random", "endless", "generated")):
            return ("Procedural variation: every run differs, so replay needs no new content")
        if _has(loop, ("personal best", "high score", "score", "combo", "best")):
            return ("Score chase: short runs, a personal best to beat, and immediate retry")
        return ("Mastery ramp: short levels on one difficulty curve, each with a best result "
                "to improve on")


def plan_strategy(opportunity, profiles, title_id, policy=None, vocabulary=None,
                  platforms=None, quality_tier=None, benchmark=None):
    """The body of a title-strategy for `opportunity`. Raises StrategyRefused.
    `vocabulary` maps research codes onto strategy terms: {"control_schemes": {control id:
    scheme}} (the research vocabulary's `control_scheme` attributes). `platforms` is a
    person's choice of target platform ids, first = required (see operator_platforms); None
    ranks the opportunity's candidates. `quality_tier` is the run's tier (mvp | release; None
    = release); `benchmark` is core/reference/quality-benchmark.yaml, read when None."""
    if not isinstance(opportunity, dict):
        raise StrategyRefused("opportunity content is not a JSON object")
    tier = resolve_quality_tier(quality_tier)
    if benchmark is None:
        from .profiles import load_benchmark
        benchmark = load_benchmark()
    plan = _Plan(opportunity, profiles, title_id, policy or Policy(), vocabulary,
                 tier=tier, benchmark=benchmark)
    plan.operator = operator_platforms(platforms)
    plan.check_opportunity()
    plan.scope()
    plan.controls()
    plan.session()
    plan.content()
    plan.platforms()
    body = plan.body()
    found = contradictions(body, plan.lexicon)
    if found:
        raise StrategyRefused("the strategy contradicts what the brief or its content model "
                              "asks: " + "; ".join(found))
    return body

"""Content: every unit of play the design commits to, held to its genre family.

A design that states one level, a difficulty curve and the word "more" is not a game.
`build_spec.content` (game-design 1.9.0) lists every unit the player meets - level, wave,
track, lap, encounter, scenario, shift, round, map or run-segment - each with its purpose,
objective, mechanics, difficulty on the family's named axes, duration, success, failure and
acceptance. `check` holds that list to core/reference/genre-models.yaml, by reference and by
number:

  * the game names a family, and the family is resolved the same way every time: the design's
    own `genre`, the strategy's research, the genre node walked up the research vocabulary's
    tree, then the concept's words;
  * the unit kind, the generation mode, the progression model, the difficulty model and the
    ending are ones that family allows;
  * the MVP carries at least the family's `units.min_mvp` units and the release its
    `min_total`, and those units fit the session profile;
  * every mechanic a unit asks for exists, is introduced before it is relied on, and is used
    again after the unit that teaches it;
  * consecutive units differ on the family's variety dimensions, and a run of units that
    change only a number is refused;
  * difficulty moves on the family's declared axes, escalates on the ones it says escalate
    over the units the tier ships (the MVP at tier mvp; every release unit, in order, above
    it - where the MVP, a prefix the session profile lets raise only so many axes, still
    climbs and never regresses), dips only as far as relief allows and recovers, and raises no
    more axes at once than the session profile permits, with a breather inside every
    `relief_every_units`;
  * objectives vary, every unit says how it is won and lost in its own words, and its
    acceptance lines are specific enough to tell two units apart;
  * `scope.content_units` agrees with the list, and mastery is stated in hud metrics a player
    can read.

At a quality tier (game-design 1.12.0 `build_spec.content.quality_tier`, else the strategy's
`concept.content_model.quality_tier`) the content is also held to what a title of that tier
carries: the strategy's content budget and core/reference/quality-benchmark.yaml's `content`
bars at that tier, the larger of the two, counted on declared fields - a unit's mechanics and
`elements`, its `structure`, `objective_kind` and `group`, the design's `secondary_goals` -
so the count is mechanical, not interpretive (rules content.tier_*):

  * distinct elements, each used in more than one unit, arriving at enough introduction
    points and still arriving late;
  * units whose set of elements no other unit has, distinct structure kinds and few repeated
    layouts;
  * objective kinds (a scored secondary goal counts as one) and no objective kind on most
    units;
  * groups where the family has them (genre-models `budget.group_kind`), each one introducing
    something and closed by its milestone where the family names one (`budget.milestone`);
  * total designed play, and difficulty that asks for different skills over every unit of
    the release - axes that escalate, units that change more than numbers, relief.

A generated design (parametric, procedural) is held on what it can state: elements, structure
kinds, objective kinds, groups and designed play. The tier `mvp` has no benchmark bars, so a
run that stops at G4 is held to the family's bars alone. A design short of its tier names what
is short and by how much.

A design that names no family at all - written before 1.9.0 - is not failed: the family does
not resolve, one warning is recorded, and no bar is applied. Everything else is blocking.

The problems are what the design step shows an author that can repair its draft, and what
fails a design that keeps them. Each one names the field to change and carries its rule id.
core/craft/core-loop-and-difficulty.md is the prose behind the bars.
"""

import os
import re

from wgflib import paths
from wgflib.yamllite import load_file

from . import layouts as geometry_of

__all__ = ["MODELS_PATH", "VOCABULARY_PATH", "BENCHMARK_PATH", "RULES", "TIER_RULES",
           "MASTERY_MODELS", "load_models", "load_vocabulary", "load_benchmark",
           "family_of_node", "resolve_family", "profile_of", "units_of", "quality_tier",
           "tier_bars", "check", "content_model_record", "unit_debuts",
           "introduction_breaches", "introductions_view", "undeclared_units"]

MODELS_PATH = os.path.join(paths.REFERENCE, "genre-models.yaml")
BENCHMARK_PATH = os.path.join(paths.REFERENCE, "quality-benchmark.yaml")
# game-design 1.12.0 build_spec.content.quality_tier, lowest first.
QUALITY_TIERS = ("mvp", "release")
VOCABULARY_PATH = os.path.join(paths.REFERENCE, "research-vocabulary.yaml")

# game-design 1.9.0 build_spec.mastery.model.
MASTERY_MODELS = ("execution", "planning", "reading", "optimisation", "routing")

# The rules, in evaluation order: the id a criterionResult carries, and what it means in one
# line. The agent author is shown this table, so a draft is written against the same bars the
# check applies.
RULES = (
    ("content.model_resolves",
     "The game names a genre family, or one resolves from the strategy's research or concept"),
    ("content.block_present",
     "A resolved family means genre, build_spec.content and - when the family asks - mastery"),
    ("content.unit_kind_allowed",
     "build_spec.content.unit_kind is one of the family's unit kinds"),
    ("content.generation_allowed",
     "build_spec.content.generation.mode is one the family allows"),
    ("content.progression_model_allowed",
     "build_spec.progression.model is one the family allows"),
    ("content.difficulty_model_allowed",
     "build_spec.difficulty.model is one the family allows"),
    ("content.ending_matches_model",
     "genre.ending is one the family allows, and a finite game states build_spec.experience.win"),
    ("content.unit_count_mvp",
     "The MVP carries at least the family's units.min_mvp units"),
    ("content.unit_count_total",
     "The design carries at least the family's units.min_total units at any tier"),
    ("content.units_fit_session",
     "No unit outruns the session profile, the MVP fits the session, and the first unit is short"),
    ("content.ids_unique_index_monotone",
     "Unit ids are unique and their index runs 1, 2, 3 in list order"),
    ("content.mechanics_resolve",
     "Every mechanic a unit asks for or introduces is a build_spec.mechanics id of the right tier"),
    ("content.mechanics_introduced_before_use",
     "A mechanic is taught by its unit or an earlier one before a unit relies on it"),
    ("content.mvp_mechanics_reused",
     "Every MVP mechanic is used again in units after the one that introduces it"),
    ("content.consecutive_units_differ",
     "Each unit changes the family's variety dimensions, and few in a row change only numbers"),
    ("content.axes_declared",
     "Every difficulty value is on a declared axis, in range, and every escalating axis is set"),
    ("content.axes_monotone_with_relief",
     "Escalating axes rise over the units the tier ships, dip only for relief, and recover"),
    ("content.objectives_vary",
     "The MVP units do not all ask the player for the same thing"),
    ("content.win_lose_stated",
     "Every unit states testably how it is won and how it is lost, and they differ"),
    ("content.acceptance_specific",
     "Every unit has acceptance lines, specific to it and not near-duplicates of another's"),
    ("content.scope_count_agrees",
     "scope.content_units and scope.content_unit_kind say what build_spec.content says"),
    ("content.mastery_stated",
     "Mastery is a model, a sentence and hud metrics the MVP shows"),
    ("content.tier_stated",
     "The content's quality tier is the strategy's, or higher"),
    ("content.tier_elements",
     "At its tier the content has the distinct elements the budget commits to, each used again"),
    ("content.tier_introductions",
     "At its tier new elements arrive at enough points, and the last arrives late"),
    ("content.tier_combinations",
     "At its tier most units combine elements no other unit combines"),
    ("content.tier_structure",
     "At its tier the units have enough structure kinds and few repeated layouts"),
    ("content.tier_objectives",
     "At its tier there are enough objective kinds and no one kind on most units"),
    ("content.tier_groups",
     "At its tier units come in groups, each introducing something and closed by a milestone"),
    ("content.tier_designed_play",
     "At its tier the units carry the designed play the budget commits to"),
    ("content.tier_difficulty",
     "At its tier difficulty asks for different skills over every unit, not only bigger numbers"),
)

# The rules a quality tier adds. Without a tier, or at a tier the benchmark states no bar
# for, each holds and says so.
TIER_RULES = tuple(rule_id for rule_id, _ in RULES if rule_id.startswith("content.tier_"))

# Rules that cannot be read at all without build_spec.content.
_NEEDS_CONTENT = frozenset((
    "content.unit_kind_allowed", "content.generation_allowed", "content.unit_count_mvp",
    "content.unit_count_total", "content.units_fit_session",
    "content.ids_unique_index_monotone", "content.mechanics_resolve",
    "content.mechanics_introduced_before_use", "content.mvp_mechanics_reused",
    "content.consecutive_units_differ", "content.axes_declared",
    "content.axes_monotone_with_relief", "content.objectives_vary",
    "content.win_lose_stated", "content.acceptance_specific", "content.scope_count_agrees",
)) | (frozenset(TIER_RULES) - {"content.tier_stated"})

# Words that carry no meaning in an acceptance line or an objective, dropped before two of
# them are compared.
_STOP = {"the", "a", "an", "of", "in", "on", "to", "is", "and", "or", "at", "by", "for",
         "with", "it", "its", "this", "that"}
# A success or failure that says nothing a developer could build or a tester could check.
_GENERIC_OUTCOME = ("win", "wins", "lose", "loses", "won", "lost", "fail", "fails", "success",
                    "failure", "game over", "you win", "you lose", "complete the level",
                    "the player fails", "the player wins", "the player loses",
                    "the level is complete")
# An acceptance line that accepts anything. Matched anywhere in the line.
_GENERIC_ACCEPTANCE = ("level is playable", "works as designed", "plays well", "is fun")

_VOCABULARIES = {}


def load_models(path=None):
    """core/reference/genre-models.yaml: the families and the bars."""
    return load_file(path or MODELS_PATH)


def load_vocabulary(path=None):
    """core/reference/research-vocabulary.yaml: the genre tree a node is walked up.

    Cached per (path, mtime) - a family is resolved once per rule and the tree is data, not
    code - and re-read when the file changes.
    """
    key = path or VOCABULARY_PATH
    stamp = os.stat(key).st_mtime_ns
    hit = _VOCABULARIES.get(key)
    if hit is None or hit[0] != stamp:
        hit = (stamp, load_file(key))
        _VOCABULARIES[key] = hit
    return hit[1]


def load_benchmark(path=None):
    """core/reference/quality-benchmark.yaml: what a title of each quality tier carries."""
    return load_file(path or BENCHMARK_PATH)


def quality_tier(design, strategy):
    """(tier, where it was stated) the content is held to, or (None, why not): the design's
    own `build_spec.content.quality_tier`, else the strategy's
    `concept.content_model.quality_tier`."""
    content = ((design or {}).get("build_spec") or {}).get("content")
    stated = content.get("quality_tier") if isinstance(content, dict) else None
    if stated in QUALITY_TIERS:
        return stated, "build_spec.content.quality_tier"
    committed = (((strategy or {}).get("concept") or {}).get("content_model") or {})
    if committed.get("quality_tier") in QUALITY_TIERS:
        return committed["quality_tier"], "the strategy's concept.content_model.quality_tier"
    return None, "neither the design nor the strategy states a quality tier"


def tier_bars(benchmark, tier):
    """{(section, key): value} - every quality-benchmark `content` bar stated at `tier`."""
    bars = {}
    for section, block in ((benchmark or {}).get("content") or {}).items():
        for key, entry in (block or {}).items():
            value = entry.get(tier) if isinstance(entry, dict) and tier else None
            if _number(value) is not None:
                bars[(section, key)] = value
    return bars


def _tokens(text):
    """The words of `text` that carry meaning: lowercase, punctuation stripped, stop words out."""
    return {word for word in re.findall(r"[a-z0-9]+", str(text or "").lower())
            if word not in _STOP}


def _norm(text):
    """`text` as one lowercase space-separated run of words: two statements that say the same
    thing in the same words normalize to the same string."""
    return " ".join(re.findall(r"[a-z0-9]+", str(text or "").lower()))


def _slug(text):
    return _norm(text).replace(" ", "-")


def _kind(text):
    """A content-unit kind, leniently: lowercase, spaces to hyphens, plural to singular."""
    slug = _slug(text)
    return slug[:-1] if slug.endswith("s") else slug


def _jaccard(left, right):
    if not left or not right:
        return 0.0
    return len(left & right) / float(len(left | right))


def _number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _owners(models):
    """{genre node: family id} - every node a family claims."""
    owners = {}
    for family_id, family in sorted((models.get("families") or {}).items()):
        for node in family.get("nodes") or []:
            owners.setdefault(str(node), family_id)
    return owners


def _parents(vocabulary):
    return {str(entry.get("id")): entry.get("parent")
            for entry in (vocabulary.get("genres") or []) if isinstance(entry, dict)
            and entry.get("id")}


def family_of_node(node, models, vocabulary=None):
    """The family that claims `node` or its nearest listed ancestor, walking `parent` up the
    research vocabulary's genre tree. None when no family covers it - a capability gap, which
    research keeps as such rather than forcing into a family that does not fit."""
    if not node:
        return None
    owners = _owners(models)
    parents = _parents(vocabulary if vocabulary is not None else load_vocabulary())
    current, seen = _slug(node), set()
    while current and current not in seen:
        if current in owners:
            return owners[current]
        seen.add(current)
        current = parents.get(current)
    return None


def _research(strategy):
    """The Research V2 handoff the strategy carries, or None (as authors.research_of reads it)."""
    research = (strategy or {}).get("research")
    return research if isinstance(research, dict) and research.get("research_version") == 2 \
        else None


def _facet(value):
    """A facetValue's value, a bare string, or the first of a list."""
    if isinstance(value, dict):
        value = value.get("value")
    if isinstance(value, (list, tuple)):
        value = value[0] if value else None
    return value if isinstance(value, str) and value.strip() else None


def _family_from_words(text, models, vocabulary=None):
    """A family named by the words of `text`: the whole phrase as a genre node, then each word,
    then a family's own label."""
    if not text:
        return None, None
    slug = _slug(text)
    if not slug:
        return None, None
    family = family_of_node(slug, models, vocabulary)
    if family:
        return family, f"{text!r} is the genre node {slug!r}"
    for word in slug.split("-"):
        family = family_of_node(word, models, vocabulary)
        if family:
            return family, f"{text!r} names the genre node {word!r}"
    words = set(slug.split("-"))
    for family_id, family_def in sorted((models.get("families") or {}).items()):
        label = set(_slug(family_def.get("label")).split("-"))
        shared = {w for w in label & words if len(w) > 3}
        if shared:
            return family_id, f"{text!r} names the family {family_def.get('label')!r}"
    return None, None


def resolve_family(strategy, design, models, vocabulary=None):
    """(family id, why) for this design, or (None, why not).

    One order, so the same design always resolves to the same family: what the design says,
    what the strategy's research decided, the genre node walked up the vocabulary's tree, then
    the concept's words. A design that names a family core/reference/genre-models.yaml does
    not define is not resolved by it.
    """
    families = models.get("families") or {}
    genre = (design or {}).get("genre")
    genre = genre if isinstance(genre, dict) else {}
    named = genre.get("family")
    if named in families:
        return named, "the design names it (genre.family)"
    node = genre.get("node")
    family = family_of_node(node, models, vocabulary)
    if family:
        return family, f"the design's genre.node {node!r} belongs to it"

    research = _research(strategy)
    pinned = ((research or {}).get("capability") or {}).get("genre_model")
    if pinned in families:
        return pinned, "research's capability catalog builds this opportunity with it " \
                       "(capability.genre_model)"
    committed = ((strategy or {}).get("concept") or {}).get("content_model") or {}
    if committed.get("family") in families:
        return committed["family"], "the strategy commits to it (concept.content_model.family)"
    for where in ("gameplay", "cell"):
        node = _facet(((research or {}).get(where) or {}).get("genre"))
        family = family_of_node(node, models, vocabulary)
        if family:
            return family, f"research's {where}.genre {node!r} belongs to it"
    concept = (strategy or {}).get("concept") or {}
    for key in ("subgenre", "genre"):
        family, why = _family_from_words(concept.get(key), models, vocabulary)
        if family:
            return family, f"the strategy's concept.{key} resolves to it: {why}"
    return None, ("neither the design's genre, the strategy's research nor its concept names a "
                  "family of core/reference/genre-models.yaml")


def profile_of(design, models):
    """The session profile the design is held to: `casual` tightens how long a unit runs and
    how many axes one unit may raise; `standard` is the default. Not a family."""
    genre = (design or {}).get("genre")
    name = (genre or {}).get("session_profile") if isinstance(genre, dict) else None
    profiles = models.get("session_profiles") or {}
    return dict(profiles.get(name or "standard") or profiles.get("standard") or {})


def _listed(design):
    content = ((design or {}).get("build_spec") or {}).get("content")
    units = (content or {}).get("units") if isinstance(content, dict) else None
    return [unit for unit in (units or []) if isinstance(unit, dict)]


def units_of(design, tier=None):
    """The content units in `index` order, optionally one tier only."""
    units = _listed(design)
    if tier is not None:
        units = [unit for unit in units if unit.get("tier") == tier]
    return sorted(units, key=lambda unit: unit.get("index") if isinstance(unit.get("index"), int)
                  else 10 ** 6)


def content_model_record(models, family):
    """What the design was checked against, for `consistency.content_model`."""
    return {"id": family, "version": str(models.get("version"))}


class _Design:
    """One design, read the way every rule reads it."""

    def __init__(self, design, strategy, models, family, why, benchmark=None):
        self.design = design or {}
        self.strategy = strategy or {}
        self.models = models
        self.family = family
        self.why = why
        self.fam = (models.get("families") or {}).get(family) or {}
        self.label = self.fam.get("label") or family
        self.spec = self.design.get("build_spec") or {}
        genre = self.design.get("genre")
        self.genre = genre if isinstance(genre, dict) else {}
        content = self.spec.get("content")
        self.content = content if isinstance(content, dict) else {}
        self.generation = self.content.get("generation") or {}
        self.mode = self.generation.get("mode")
        self.units_listed = _listed(self.design)
        self.units = units_of(self.design)
        self.mvp_units = units_of(self.design, "mvp")
        self.profile_name = self.genre.get("session_profile") or "standard"
        self.profile = profile_of(self.design, models)
        self.mechanics = {m.get("id"): m.get("tier") for m in (self.spec.get("mechanics") or [])
                          if isinstance(m, dict) and m.get("id")}
        self.scheduled = {c.get("id") for c in ((self.spec.get("depth") or {})
                                                .get("content_schedule") or [])
                          if isinstance(c, dict) and c.get("id")}
        self.fam_axes = {a.get("id"): a for a in (self.fam.get("axes") or []) if a.get("id")}
        self.declared = {a.get("id"): a for a in ((self.spec.get("difficulty") or {})
                                                  .get("axes") or [])
                         if isinstance(a, dict) and a.get("id") and a.get("range")}
        mastery = self.spec.get("mastery")
        self.mastery = mastery if isinstance(mastery, dict) else None
        self.units_bars = self.fam.get("units") or {}
        # The quality tier, its bars and the strategy's budget (content.tier_*).
        self.tier, self.tier_where = quality_tier(self.design, self.strategy)
        self.tier_bars = tier_bars(benchmark, self.tier)
        committed = (self.strategy.get("concept") or {}).get("content_model") or {}
        budget = committed.get("budget")
        self.budget = budget if isinstance(budget, dict) else {}
        self.shape = self.fam.get("budget") or {}
        self.authored = self.mode == "authored"
        self.release_units = [unit for unit in self.units if unit.get("tier") != "optional"]
        self.catalogue = {e.get("id"): e for e in (self.content.get("elements") or [])
                          if isinstance(e, dict) and e.get("id")}

    def tbar(self, section, key):
        """A quality-benchmark content bar at this design's tier, or None."""
        return self.tier_bars.get((section, key))

    def committed(self, *path):
        """A number the strategy's content budget commits to, or None."""
        value = self.budget
        for key in path:
            value = value.get(key) if isinstance(value, dict) else None
        return _number(value)

    def floor(self, bar, *path):
        """The larger of a benchmark bar and the budget's number, or None when neither is."""
        values = [v for v in (bar, self.committed(*path) if path else None) if v is not None]
        return max(values) if values else None

    def basis(self, section, key, *path):
        """Where a tier floor comes from, for a finding: the benchmark's bar and the budget's."""
        parts = []
        bar = self.tbar(section, key)
        if bar is not None:
            parts.append(f"quality-benchmark content.{section}.{key} {bar:g}")
        committed = self.committed(*path) if path else None
        if committed is not None:
            parts.append(f"the strategy's budget.{'.'.join(path)} {committed:g}")
        return ", ".join(parts) or "no bar"

    def elements_of(self, unit):
        """A unit's set of elements: its mechanics and the content elements it names."""
        return frozenset(str(e) for e in list(unit.get("mechanics") or [])
                         + list(unit.get("elements") or []))

    def objective_kind(self, unit):
        """The unit's objective kind: its `objective_kind`, else its objective's words with
        the numbers taken out - "clear 12 bricks" and "clear 14 bricks" are one kind."""
        kind = unit.get("objective_kind")
        if isinstance(kind, str) and kind:
            return kind
        return " ".join(w for w in _norm(unit.get("objective")).split() if not w.isdigit())

    def bar(self, key):
        """A variety bar: the family's, else the ruleset's."""
        local = self.fam.get("variety") or {}
        if key in local:
            return local[key]
        return (self.models.get("variety") or {}).get(key)

    def dimensions(self):
        return {str(d) for d in ((self.fam.get("variety") or {}).get("dimensions") or [])}

    def axis(self, axis_id):
        return self.declared.get(axis_id) or self.fam_axes.get(axis_id)

    def value(self, unit, axis_id):
        return _number((unit.get("difficulty") or {}).get(axis_id))

    def raised(self, previous, unit):
        """The axes `unit` takes strictly higher than `previous` does."""
        keys = set(previous.get("difficulty") or {}) | set(unit.get("difficulty") or {})
        out = []
        for key in sorted(keys):
            before, after = self.value(previous, key), self.value(unit, key)
            if before is not None and after is not None and after > before:
                out.append(key)
        return out

    def where(self, unit, field=None):
        at = f"build_spec.content.units[{unit.get('id')}]"
        return f"{at}.{field}" if field else at


# -- the rules ---------------------------------------------------------------------------
# Each takes the read design and returns (problems, measured, note). `breached` is whether
# there are problems; `check` prefixes each problem with the rule id.


def _model_resolves(d):
    return [], d.family, f"{d.label}: {d.why}"


def _block_present(d):
    problems = []
    if not isinstance(d.design.get("genre"), dict):
        problems.append(f"genre is missing: this design is a {d.label} game ({d.why}) - state "
                        f"genre.family {d.family!r}, its node, its session_profile and whether "
                        f"play ends")
    else:
        if d.genre.get("family") != d.family:
            problems.append(f"genre.family is {d.genre.get('family')!r} but this design resolves "
                            f"to {d.family!r} ({d.why}): name the family the content is held to")
        if not d.genre.get("ending"):
            allowed = " or ".join(d.fam.get("ending") or [])
            problems.append(f"genre.ending is missing: say whether play ends ({allowed})")
    if not d.content or not d.units_listed:
        kinds = ", ".join(d.fam.get("unit_kinds") or [])
        minimum = d.units_bars.get("min_mvp")
        problems.append(f"build_spec.content is missing: list the {minimum} or more {kinds} the "
                        f"MVP player meets, each with its purpose, objective, mechanics, "
                        f"difficulty, expected_duration_s, success, failure and acceptance")
    if (d.fam.get("mastery") or {}).get("statement_required") and d.mastery is None:
        problems.append("build_spec.mastery is missing: state what getting better at this game "
                        "means and the hud metrics it shows up in")
    return problems, bool(d.content), f"genre, build_spec.content and mastery for a {d.label} game"


def _unit_kind_allowed(d):
    allowed = [str(k) for k in d.fam.get("unit_kinds") or []]
    kind = d.content.get("unit_kind")
    problems = []
    if kind not in allowed:
        problems.append(f"build_spec.content.unit_kind is {kind!r}; one unit of a {d.label} game "
                        f"is a {' or a '.join(allowed)}")
    return problems, kind, f"{d.label} units: {', '.join(allowed)}"


def _generation_allowed(d):
    allowed = [str(m) for m in d.units_bars.get("generation") or []]
    problems = []
    if d.mode not in allowed:
        problems.append(f"build_spec.content.generation.mode is {d.mode!r}; a {d.label} game's "
                        f"content is {', '.join(allowed)}")
    return problems, d.mode, f"{d.label} generation: {', '.join(allowed)}"


def _progression_model_allowed(d):
    allowed = [str(m) for m in d.fam.get("progression_models") or []]
    model = (d.spec.get("progression") or {}).get("model")
    problems = []
    if model not in allowed:
        problems.append(f"build_spec.progression.model is {model!r}; a {d.label} game progresses "
                        f"by {', '.join(allowed)}")
    return problems, model, f"{d.label} progression: {', '.join(allowed)}"


def _difficulty_model_allowed(d):
    allowed = [str(m) for m in d.fam.get("difficulty_models") or []]
    model = (d.spec.get("difficulty") or {}).get("model")
    problems = []
    if model not in allowed:
        problems.append(f"build_spec.difficulty.model is {model!r}; a {d.label} game's difficulty "
                        f"is {', '.join(allowed)}")
    return problems, model, f"{d.label} difficulty: {', '.join(allowed)}"


def _ending_matches_model(d):
    allowed = [str(e) for e in d.fam.get("ending") or []]
    ending = d.genre.get("ending")
    problems = []
    if ending and ending not in allowed:
        problems.append(f"genre.ending is {ending!r}; a {d.label} game ends "
                        f"{' or '.join(allowed)}")
    if ending == "finite" and not ((d.spec.get("experience") or {}).get("win")):
        problems.append("genre.ending is 'finite' but build_spec.experience.win is missing: a game "
                        "that can be finished says how it is won")
    return problems, ending, f"{d.label} ending: {', '.join(allowed)}"


def _unit_count_mvp(d):
    minimum = d.units_bars.get("min_mvp") or 0
    problems = []
    if d.mode == "procedural":
        expected = d.generation.get("expected_units")
        measured = expected
        if not isinstance(expected, int) or expected < minimum:
            problems.append(f"build_spec.content.generation.expected_units is {expected!r}; a "
                            f"procedural {d.label} game's session meets at least {minimum} "
                            f"distinct units")
        if not d.units_listed:
            problems.append("build_spec.content.units is empty: a procedural design still lists "
                            "the units it commits to as examples - at least one")
    else:
        measured = len(d.mvp_units)
        if measured < minimum:
            problems.append(f"build_spec.content lists {measured} mvp unit(s); a {d.label} "
                            f"prototype carries {minimum}: a one-unit prototype cannot show a "
                            f"curve, and is not what G4 judges")
    return problems, measured, f"{d.label} MVP units: {minimum}"


def _unit_count_total(d):
    family = d.units_bars.get("min_total") or 0
    # At a quality tier the release carries the larger of the family's bar, the benchmark's
    # and the strategy's budget, counted over the units it ships (not `optional` ones).
    tiered = d.floor(d.tbar("units", "min_total"), "units")
    minimum = max(family, int(tiered or 0))
    scope_units = (d.design.get("scope") or {}).get("content_units")
    if d.mode == "authored":
        measured = len(d.release_units) if tiered is not None else len(d.units_listed)
        where = "build_spec.content.units"
    else:
        expected = d.generation.get("expected_units")
        measured = expected if isinstance(expected, int) else scope_units
        where = "build_spec.content.generation.expected_units (or scope.content_units)"
    problems = []
    if not isinstance(measured, int) or measured < minimum:
        if tiered is not None and minimum > family:
            problems.append(f"{where} says {measured!r} unit(s); a {d.tier}-tier {d.label} "
                            f"release carries {minimum} ({d.basis('units', 'min_total', 'units')})"
                            f": {minimum - (measured or 0)} short - add the units, tiered "
                            f"post-mvp where the prototype does not need them")
        else:
            problems.append(f"{where} says {measured!r} unit(s) at any tier; a {d.label} "
                            f"release carries {minimum}: tier the rest post-mvp, but say they "
                            f"exist")
    note = f"{d.label} units at any tier: {minimum}"
    if tiered is not None:
        note += f" at tier {d.tier} ({d.basis('units', 'min_total', 'units')})"
    return problems, measured, note


def _units_fit_session(d):
    problems = []
    longest = _number(d.profile.get("max_unit_s"))
    for unit in d.units:
        duration = _number(unit.get("expected_duration_s"))
        if duration is not None and longest is not None and duration > longest:
            problems.append(f"{d.where(unit, 'expected_duration_s')} is {duration:g} s; a "
                            f"{d.profile_name} session's longest unit is {longest:g} s")
    counted = [u for u in d.mvp_units if u.get("purpose") != "bonus"]
    total = sum(_number(u.get("expected_duration_s")) or 0 for u in counted)
    target = _number((d.design.get("session") or {}).get("target_seconds"))
    if target and total > 3 * target:
        problems.append(f"the {len(counted)} MVP units run {total:g} s against a "
                        f"{target:g} s session: a first-time player never sees most of them - "
                        f"shorten them or tier some post-mvp")
    if d.mvp_units and longest is not None:
        first = d.mvp_units[0]
        duration = _number(first.get("expected_duration_s"))
        if duration is not None and duration > longest / 2.0:
            problems.append(f"{d.where(first, 'expected_duration_s')} is {duration:g} s and it is "
                            f"the first unit a player meets; the first one runs at most "
                            f"{longest / 2.0:g} s")
    return problems, total, f"{len(counted)} MVP unit(s), longest {longest} s"


def _ids_unique_index_monotone(d):
    problems, seen = [], set()
    for unit in d.units_listed:
        unit_id = unit.get("id")
        if unit_id in seen:
            problems.append(f"build_spec.content.units has two units with the id {unit_id!r}")
        seen.add(unit_id)
    indexes = [unit.get("index") for unit in d.units_listed]
    if indexes and indexes[0] != 1:
        problems.append(f"build_spec.content.units[{d.units_listed[0].get('id')}].index is "
                        f"{indexes[0]!r}; the sequence starts at 1")
    for position in range(1, len(indexes)):
        before, after = indexes[position - 1], indexes[position]
        if not (isinstance(before, int) and isinstance(after, int) and after > before):
            problems.append(f"{d.where(d.units_listed[position], 'index')} is {after!r} after "
                            f"{before!r}: index runs 1, 2, 3 in the order the units are listed")
    return problems, indexes, f"{len(indexes)} unit(s) listed"


def _mechanics_resolve(d):
    problems = []
    for unit in d.units:
        for mechanic in unit.get("mechanics") or []:
            if mechanic not in d.mechanics:
                problems.append(f"{d.where(unit, 'mechanics')} names {mechanic!r}, not a "
                                f"build_spec.mechanics id")
            elif unit.get("tier") == "mvp" and d.mechanics[mechanic] != "mvp":
                problems.append(f"{d.where(unit)} is mvp but asks for {mechanic!r}, which is "
                                f"{d.mechanics[mechanic]}: the MVP does not build it - tier the "
                                f"mechanic mvp, or the unit {d.mechanics[mechanic]}")
        for mechanic in unit.get("introduces") or []:
            if mechanic not in d.mechanics and mechanic not in d.scheduled                     and mechanic not in d.catalogue:
                problems.append(f"{d.where(unit, 'introduces')} names {mechanic!r}, not a "
                                f"build_spec.mechanics, build_spec.content.elements or "
                                f"build_spec.depth.content_schedule id")
        for element in unit.get("elements") or []:
            if element not in d.catalogue:
                problems.append(f"{d.where(unit, 'elements')} names {element!r}, not a "
                                f"build_spec.content.elements id")
    return problems, len(d.mechanics), f"{len(d.mechanics)} mechanic(s) to resolve against"


def _mechanics_introduced_before_use(d):
    problems = []
    if not d.mvp_units:
        return problems, 0, "no mvp unit"
    opening = set(d.mvp_units[0].get("mechanics") or [])
    introduced = set()
    for unit in d.mvp_units:
        here = set(unit.get("introduces") or [])
        for mechanic in unit.get("mechanics") or []:
            if d.mechanics.get(mechanic) != "mvp":
                continue
            if mechanic in introduced or mechanic in here or mechanic in opening:
                continue
            problems.append(f"{d.where(unit)} asks for {mechanic!r}, which no unit up to here "
                            f"introduces: name it in this unit's introduces, or in an earlier "
                            f"unit's")
        introduced |= here
    return problems, len(introduced), f"{len(introduced)} mechanic(s) introduced over the MVP"


def _mvp_mechanics_reused(d):
    problems = []
    reuse = d.bar("mechanic_reuse_min_units") or 0
    minimum = d.units_bars.get("min_mvp") or 0
    units, count = d.mvp_units, len(d.mvp_units)
    first_at = {}
    for position, unit in enumerate(units):
        for mechanic in list(unit.get("introduces") or []) + list(unit.get("mechanics") or []):
            first_at.setdefault(mechanic, position)
    for mechanic, position in sorted(first_at.items()):
        if d.mechanics.get(mechanic) != "mvp":
            continue
        after = [u for u in units[position + 1:] if mechanic in (u.get("mechanics") or [])]
        room = count - 1 - position
        if room == 0:
            if count != minimum:
                problems.append(f"build_spec.mechanics {mechanic!r} is introduced by the last MVP "
                                f"unit and never asked for again: introduce it earlier, or add a "
                                f"unit that uses it")
            continue
        need = min(reuse, room)
        if len(after) < need:
            problems.append(f"build_spec.mechanics {mechanic!r} is asked for by {len(after)} MVP "
                            f"unit(s) after the one that introduces it; the bar is {need}: a "
                            f"mechanic taught once and dropped is a tutorial, not content")
    return problems, len(first_at), f"reuse bar {reuse} unit(s) after the introduction"


def _consecutive_units_differ(d):
    problems = []
    dimensions = d.dimensions()
    minimum = d.bar("min_dimensions_changed_between_units") or 0
    most = d.bar("max_consecutive_scaling_only_units")
    run, longest = 0, 0
    for position in range(1, len(d.mvp_units)):
        previous, unit = d.mvp_units[position - 1], d.mvp_units[position]
        changed = {str(x) for x in unit.get("variation_from_previous") or []} & dimensions
        if len(changed) < minimum:
            named = ", ".join(sorted(changed)) or "nothing"
            problems.append(f"{d.where(unit, 'variation_from_previous')} changes {named} of the "
                            f"family's variety dimensions; the bar is {minimum} of "
                            f"{', '.join(sorted(dimensions))}")
        scaling = (not unit.get("introduces")
                   and _norm(unit.get("objective")) == _norm(previous.get("objective"))
                   and set(unit.get("mechanics") or []) == set(previous.get("mechanics") or []))
        run = run + 1 if scaling else 0
        longest = max(longest, run)
        if most is not None and run > most:
            problems.append(f"{d.where(unit)} is unit {run} in a row that changes only its "
                            f"numbers - no new mechanic, the same objective, the same mechanics; "
                            f"at most {most} may follow one another")
    return problems, longest, f"longest run of scaling-only units; the bar is {most}"


def _axes_declared(d):
    problems = []
    for unit in d.units:
        for axis_id, raw in sorted((unit.get("difficulty") or {}).items()):
            axis = d.axis(axis_id)
            if axis is None:
                problems.append(f"{d.where(unit, 'difficulty')} names the axis {axis_id!r}, which "
                                f"is neither a {d.label} axis "
                                f"({', '.join(sorted(d.fam_axes))}) nor declared in "
                                f"build_spec.difficulty.axes with a range")
                continue
            value = _number(raw)
            low, high = (axis.get("range") or [0, 1])[:2]
            if value is None or not (low <= value <= high):
                problems.append(f"{d.where(unit, 'difficulty')}.{axis_id} is {raw!r}, outside the "
                                f"axis's range {low:g}..{high:g}")
    for axis_id, axis in sorted(d.fam_axes.items()):
        if not axis.get("escalates"):
            continue
        for unit in d.mvp_units:
            if d.value(unit, axis_id) is None:
                problems.append(f"{d.where(unit, 'difficulty')} has no value for {axis_id!r}, an "
                                f"axis a {d.label} game escalates on: every MVP unit states it "
                                f"({axis.get('description')})")
    return problems, sorted(set(d.fam_axes) | set(d.declared)), \
        f"{d.label} axes: {', '.join(sorted(d.fam_axes))}"


def _escalation(d, units, where):
    """The escalation problems of `units` read in order: every escalating axis ends at least
    `min_axis_rise` higher than it starts, and a dip is a breather - no deeper than
    `relief_dip_max` and recovered within `relief_recovery_units`. `where` names the units in
    a finding ("MVP", "release")."""
    problems = []
    dip_max = d.bar("relief_dip_max")
    recovery = d.bar("relief_recovery_units") or 0
    rise = d.bar("min_axis_rise") or 0
    for axis_id, axis in sorted(d.fam_axes.items()):
        if not axis.get("escalates"):
            continue
        series = [(unit, d.value(unit, axis_id)) for unit in units
                  if d.value(unit, axis_id) is not None]
        if len(series) < 2:
            continue
        first, last = series[0][1], series[-1][1]
        if last <= first:
            problems.append(f"difficulty {axis_id!r} is {first:g} on the first {where} unit and "
                            f"{last:g} on the last; an axis a {d.label} game escalates on ends "
                            f"higher than it starts")
        elif last - first < rise - 1e-9:
            problems.append(f"difficulty {axis_id!r} rises only {last - first:g} over the "
                            f"{where} units ({first:g} to {last:g}); an axis a {d.label} game "
                            f"escalates on rises at least {rise:g} of its range by the last "
                            f"{where} unit - a nudge is not a curve")
        for position in range(1, len(series)):
            unit, value = series[position]
            before = series[position - 1][1]
            if value >= before:
                continue
            if dip_max is not None and before - value > dip_max * before:
                problems.append(f"{d.where(unit, 'difficulty')}.{axis_id} drops from {before:g} "
                                f"to {value:g}; a breather dips at most "
                                f"{dip_max * 100:g}% of the previous value")
            window = [v for _, v in series[position + 1:position + 1 + recovery]]
            if not any(v >= before for v in window):
                problems.append(f"{d.where(unit, 'difficulty')}.{axis_id} dips to {value:g} from "
                                f"{before:g} and is not back to {before:g} within {recovery} "
                                f"unit(s): a dip that is never recovered is a flat curve")
    return problems


def _mvp_climbs(d):
    """The MVP of a design above tier mvp: a prefix of the release, which escalates over the
    release (`_escalation`). A session profile raises `max_axes_raised_per_unit` axes per unit,
    so a short MVP cannot raise every escalating axis - but it climbs: no escalating axis ends
    the MVP lower than it starts, and at least one rises by `min_axis_rise`."""
    units = d.mvp_units
    rise = d.bar("min_axis_rise") or 0
    problems, best = [], None
    for axis_id, axis in sorted(d.fam_axes.items()):
        if not axis.get("escalates"):
            continue
        series = [v for v in (d.value(unit, axis_id) for unit in units) if v is not None]
        if len(series) < 2:
            continue
        first, last = series[0], series[-1]
        best = last - first if best is None else max(best, last - first)
        if last < first:
            problems.append(f"difficulty {axis_id!r} is {first:g} on the first MVP unit and "
                            f"{last:g} on the last; the prototype is the start of the release's "
                            f"curve and an axis a {d.label} game escalates on does not end it "
                            f"lower than it starts")
    if best is not None and best < rise - 1e-9:
        problems.append(f"no escalating axis rises {rise:g} of its range over the MVP units (the "
                        f"most is {best:g}); the prototype raises at least one of the axes a "
                        f"{d.label} game escalates on - a flat prototype tests no curve")
    return problems


def _axes_monotone_with_relief(d):
    units = d.mvp_units
    # Above tier mvp the design ships every release unit: escalation is judged over all of
    # them, in order (as content.tier_difficulty reads them), and the MVP only has to climb.
    # At tier mvp - or with nothing past the prototype - the MVP is what ships.
    shipped = d.tier in QUALITY_TIERS[1:] and len(d.release_units) > len(units)
    if shipped:
        problems = _escalation(d, d.release_units, "release") + _mvp_climbs(d)
    else:
        problems = _escalation(d, units, "MVP")
    cap = d.profile.get("max_axes_raised_per_unit")
    for position in range(1, len(units)):
        unit = units[position]
        if unit.get("purpose") == "climax":
            continue
        raised = d.raised(units[position - 1], unit)
        if cap is not None and len(raised) > cap:
            problems.append(f"{d.where(unit, 'difficulty')} raises {len(raised)} axes at once "
                            f"({', '.join(raised)}); a {d.profile_name} session raises {cap} per "
                            f"unit unless the unit's purpose is 'climax'")
    every = d.profile.get("relief_every_units")
    run = 0
    for position, unit in enumerate(units):
        raised = d.raised(units[position - 1], unit) if position else []
        run = 0 if (unit.get("purpose") == "breather" or not raised) else run + 1
        if every is not None and run > every:
            problems.append(f"{d.where(unit)} is MVP unit {run} in a row that raises an axis; "
                            f"a {d.profile_name} session gets a breather - a 'breather' purpose, "
                            f"or a unit that raises nothing - every {every} units")
    note = f"{d.profile_name} profile: {cap} axes per unit, relief every {every}"
    if shipped:
        note += f"; escalation over the {len(d.release_units)} release unit(s)"
    return problems, len(units), note


def _objectives_vary(d):
    units = d.mvp_units
    if not units:
        return [], 0, "no mvp unit"
    objectives = [_norm(unit.get("objective")) for unit in units]
    distinct = len(set(objectives))
    share = distinct / float(len(units))
    bar = 1.0 - (d.bar("max_identical_objectives_ratio") or 0)
    problems = []
    if share < bar - 1e-9:
        problems.append(f"the {len(units)} MVP units ask the player for {distinct} distinct "
                        f"thing(s) ({share:.0%}); the bar is {bar:.0%}: give the units different "
                        f"objectives, not the same one at higher numbers")
    return problems, distinct, f"{distinct} distinct objective(s) over {len(units)} MVP unit(s)"


def _win_lose_stated(d):
    problems = []
    for unit in d.units:
        success, failure = _norm(unit.get("success")), _norm(unit.get("failure"))
        for field, text in (("success", success), ("failure", failure)):
            if not text:
                problems.append(f"{d.where(unit, field)} is missing: say how this unit is "
                                f"{'won' if field == 'success' else 'lost'}, testably")
            elif text in _GENERIC_OUTCOME:
                problems.append(f"{d.where(unit, field)} is {unit.get(field)!r}, which no "
                                f"developer could build and no tester could check")
        if success and success == failure:
            problems.append(f"{d.where(unit)} states the same thing as its success and its "
                            f"failure: {unit.get('success')!r}")
    if (d.fam.get("win") or {}).get("per_unit") and d.units:
        distinct = len({_norm(unit.get("success")) for unit in d.units})
        if distinct < len(d.units) / 2.0 and not ((d.spec.get("experience") or {}).get("win")):
            problems.append(f"a {d.label} game is won per unit, but the {len(d.units)} units "
                            f"state {distinct} distinct success condition(s) and "
                            f"build_spec.experience.win states no overall win: say what each unit "
                            f"asks for in its own terms")
    return problems, len(d.units), f"{d.label} win per unit: " \
                                   f"{bool((d.fam.get('win') or {}).get('per_unit'))}"


def _acceptance_specific(d):
    problems = []
    minimum = d.bar("acceptance_min_items") or 0
    most = d.bar("acceptance_max_similarity")
    lines = []
    for unit in d.units:
        acceptance = [str(line) for line in unit.get("acceptance") or []]
        if len(acceptance) < minimum:
            problems.append(f"{d.where(unit, 'acceptance')} has {len(acceptance)} line(s); the "
                            f"bar is {minimum}: say what must be true of this unit when it is "
                            f"built")
        for line in acceptance:
            normalized = _norm(line)
            generic = next((g for g in _GENERIC_ACCEPTANCE if g in normalized), None)
            if generic:
                problems.append(f"{d.where(unit, 'acceptance')} says {line!r}; {generic!r} "
                                f"accepts anything - name the number, the state or the thing the "
                                f"player sees")
            lines.append((unit.get("id"), line, _tokens(line)))
    worst, pair = 0.0, None
    for left in range(len(lines)):
        for right in range(left + 1, len(lines)):
            similarity = _jaccard(lines[left][2], lines[right][2])
            if similarity > worst:
                worst, pair = similarity, (lines[left], lines[right])
    if pair and most is not None and worst >= most:
        problems.append(f"units[{pair[0][0]}] and units[{pair[1][0]}] accept nearly the same "
                        f"thing ({worst:.0%} alike): {pair[0][1]!r} / {pair[1][1]!r} - two units "
                        f"a tester cannot tell apart are one unit")
    return problems, round(worst, 3), f"the most alike acceptance lines; the bar is {most}"


def _scope_count_agrees(d):
    problems = []
    scope = d.design.get("scope") or {}
    listed = len(d.units_listed)
    if d.mode == "procedural":
        wanted, why = d.generation.get("expected_units"), \
            "build_spec.content.generation.expected_units"
    else:
        wanted, why = listed, "the units build_spec.content lists"
    counted = scope.get("content_units")
    if counted != wanted:
        problems.append(f"scope.content_units is {counted!r} but {why} says {wanted!r}: one "
                        f"number, in both places")
    kind = scope.get("content_unit_kind")
    if kind and _kind(kind) not in (_kind(d.content.get("unit_kind")), _kind(d.label)):
        problems.append(f"scope.content_unit_kind is {kind!r} but build_spec.content.unit_kind is "
                        f"{d.content.get('unit_kind')!r}")
    return problems, counted, f"{listed} unit(s) listed, mode {d.mode}"


def _mastery_stated(d):
    required = bool((d.fam.get("mastery") or {}).get("statement_required"))
    if not required:
        return [], False, f"a {d.label} game need not state mastery"
    problems = []
    if d.mastery is None:
        problems.append(f"build_spec.mastery is required of a {d.label} game: state the model "
                        f"({', '.join(MASTERY_MODELS)}), what a better player does differently in "
                        f"one sentence, and the hud metrics the improvement shows in")
        return problems, None, "mastery is required"
    if d.mastery.get("model") not in MASTERY_MODELS:
        problems.append(f"build_spec.mastery.model is {d.mastery.get('model')!r}; it is one of "
                        f"{', '.join(MASTERY_MODELS)}")
    if not str(d.mastery.get("statement") or "").strip():
        problems.append("build_spec.mastery.statement is missing: one sentence on what a better "
                        "player does differently")
    shown = set()
    for element in d.spec.get("hud") or []:
        if isinstance(element, dict) and element.get("tier") == "mvp":
            shown |= {element.get("id"), element.get("metric")}
    shown.discard(None)
    signals = [str(s) for s in d.mastery.get("signals") or []]
    if not signals:
        problems.append("build_spec.mastery.signals is empty: name the hud metrics a player reads "
                        "their improvement from")
    for signal in signals:
        if signal not in shown:
            problems.append(f"build_spec.mastery.signals names {signal!r}, which no mvp "
                            f"build_spec.hud element shows by id or metric: a mastery signal a "
                            f"player cannot see is not one")
    return problems, signals, f"{len(shown)} mvp hud id(s) and metric(s) to read mastery from"


# -- the quality tier (game-design 1.12.0) -----------------------------------------------
# Each holds, and says so, when the design has no tier or the tier has no bar for it. Every
# number comes from core/reference/quality-benchmark.yaml at the tier or the strategy's
# content budget, the larger of the two; the family's genre model says what a group, an
# element and a milestone are.


def _no_tier(d, what):
    if d.tier is None:
        return f"no quality tier, so no {what} bar: {d.tier_where}"
    return f"tier {d.tier} states no {what} bar"


def _generated(d, what):
    return f"{d.mode} content: {what} is read on the built content, not the representative units"


def _ids(units, most=6):
    named = [str(u.get("id")) for u in units[:most]]
    return ", ".join(named) + (f" and {len(units) - most} more" if len(units) > most else "")


def _first_appearances(d):
    """[(unit, new elements)] in order: what each unit is the first to use or introduce."""
    seen, out = set(), []
    for unit in d.release_units:
        here = set(d.elements_of(unit)) | {str(e) for e in unit.get("introduces") or []}
        new = sorted(here - seen)
        seen |= here
        out.append((unit, new))
    return out


def _tier_stated(d):
    committed = ((d.strategy.get("concept") or {}).get("content_model") or {}).get(
        "quality_tier")
    stated = d.content.get("quality_tier")
    problems = []
    if committed in QUALITY_TIERS and stated in QUALITY_TIERS and \
            QUALITY_TIERS.index(stated) < QUALITY_TIERS.index(committed):
        problems.append(f"build_spec.content.quality_tier is {stated!r} but the strategy commits "
                        f"to {committed!r} (concept.content_model.quality_tier): design the "
                        f"content the strategy approved at G2, or change the strategy")
    return problems, d.tier, f"tier {d.tier}: {d.tier_where}" if d.tier else _no_tier(d, "tier")


def _tier_elements(d):
    floor = d.floor(d.tbar("elements", "min_distinct"), "elements", "count")
    reuse = d.tbar("elements", "min_units_per_element")
    if floor is None and reuse is None:
        return [], None, _no_tier(d, "element")
    used = {}
    for unit in d.release_units:
        for element in d.elements_of(unit):
            used.setdefault(element, []).append(unit)
    problems = []
    kinds = ", ".join(str(k) for k in d.shape.get("element_kinds") or []) or "elements"
    if floor is not None and len(used) < floor:
        problems.append(
            f"the {len(d.release_units)} units use {len(used)} distinct element(s) "
            f"({', '.join(sorted(used)) or 'none'}); a {d.tier}-tier {d.label} release carries "
            f"{floor:g} ({d.basis('elements', 'min_distinct', 'elements', 'count')}): "
            f"{int(floor) - len(used)} short - declare more of the family's element kinds "
            f"({kinds}) in build_spec.content.elements and name them in the units' elements; a "
            f"number-only change (speed, count, width) is never an element")
    if reuse is not None and d.authored:
        once = sorted(e for e, units in used.items() if len(units) < reuse)
        if once:
            problems.append(f"the element(s) {', '.join(once)} appear in fewer than {reuse:g} "
                            f"units (quality-benchmark content.elements.min_units_per_element): "
                            f"an element used once is a gimmick - use it again, in a new "
                            f"combination")
    return problems, len(used), f"{len(used)} distinct element(s); the floor is {floor}"


def _tier_introductions(d):
    floor = d.floor(d.tbar("elements", "min_introduction_points"),
                    "elements", "min_introduction_points")
    late = d.tbar("elements", "last_introduction_min_position")
    if floor is None and late is None:
        return [], None, _no_tier(d, "introduction")
    if not d.authored:
        return [], None, _generated(d, "the order elements arrive in")
    points = [(position, unit) for position, (unit, new) in
              enumerate(_first_appearances(d), 1) if new]
    count, total = len(points), len(d.release_units)
    problems = []
    if floor is not None and count < floor:
        basis = d.basis("elements", "min_introduction_points",
                        "elements", "min_introduction_points")
        problems.append(f"new elements first appear in {count} unit(s) "
                        f"({_ids([u for _, u in points])}); a {d.tier}-tier {d.label} release "
                        f"introduces something new at {floor:g} points ({basis}): "
                        f"{int(floor) - count} short - spread the elements over the units, "
                        f"each introduced by one unit and reused after it")
    last = points[-1][0] / float(total) if points and total else 0.0
    if late is not None and points and last < late - 1e-9:
        problems.append(f"the last new element arrives in {points[-1][1].get('id')} "
                        f"({points[-1][0]} of {total}, {last:.0%} of the way); a {d.tier}-tier "
                        f"release still introduces something at {late:.0%} or later "
                        f"(quality-benchmark content.elements.last_introduction_min_position): "
                        f"hold an element back for the final third")
    return problems, count, f"{count} introduction point(s), the last at {last:.0%}"


def _tier_combinations(d):
    ratio = d.tbar("combinations", "min_distinct_ratio")
    if ratio is None:
        return [], None, _no_tier(d, "combination")
    if not d.authored:
        return [], None, _generated(d, "the combination of elements per unit")
    sets = [d.elements_of(unit) for unit in d.release_units]
    counts = {}
    for combo in sets:
        counts[combo] = counts.get(combo, 0) + 1
    unique = sum(1 for combo in sets if counts[combo] == 1)
    share = unique / float(len(sets)) if sets else 0.0
    problems = []
    if share < ratio - 1e-9:
        shared, times = max(counts.items(), key=lambda item: (item[1], sorted(item[0])))
        problems.append(f"{unique} of the {len(sets)} units ({share:.0%}) combine elements no "
                        f"other unit combines; a {d.tier}-tier release has {ratio:.0%} "
                        f"(quality-benchmark content.combinations.min_distinct_ratio) - "
                        f"{times} units use exactly {', '.join(sorted(shared))}: give units "
                        f"their own mix of elements, not the same set at higher numbers")
    return problems, round(share, 3), f"{share:.0%} of units combine their own elements"


def _near_identical():
    """content-sufficiency.yaml `layout.near_identical_similarity`: how alike two units'
    geometry must be to be one unit (the build is judged by the same number)."""
    rules = load_file(os.path.join(paths.REFERENCE, "content-sufficiency.yaml"))
    value = (rules.get("layout") or {}).get("near_identical_similarity")
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else 1.0


def _tier_structure(d):
    kinds_bar = d.tbar("structure", "min_structure_kinds")
    repeat_bar = d.tbar("structure", "max_repeated_layout_ratio")
    if kinds_bar is None and repeat_bar is None:
        return [], None, _no_tier(d, "structure")
    units = d.release_units
    problems = []
    missing = [unit for unit in units if not unit.get("structure")]
    kinds = sorted({str(unit.get("structure")) for unit in units if unit.get("structure")})
    if kinds_bar is not None:
        if missing:
            problems.append(f"{_ids(missing)} state no structure: name each unit's structural "
                            f"kind in its `structure` (static-field, moving-field, "
                            f"path-with-turns, arena, climax...)")
        if len(kinds) < kinds_bar:
            problems.append(f"the units are built {len(kinds)} way(s) "
                            f"({', '.join(kinds) or 'none stated'}); a {d.tier}-tier "
                            f"{d.label} release has {kinds_bar:g} structure kinds "
                            f"(quality-benchmark content.structure.min_structure_kinds): "
                            f"{int(kinds_bar) - len(kinds)} short - a moving field, a path, an "
                            f"arena or a climax is a different unit to play, not a bigger one")
    if repeat_bar is not None and d.authored and units:
        # One rule with the content-sufficiency step (wgf_design/layouts.py): units are
        # compared on the geometry their `parameters` carry (their outermost lists, container
        # names dropped), never on the names of tuning scalars; and two units with one
        # structure, one set of elements and the same parameter values are one unit whatever
        # their geometry says - never looser than comparing them on that alone.
        view = [{"id": unit.get("id"), "structure": unit.get("structure"),
                 "combo": d.elements_of(unit), "objective_kind": d.objective_kind(unit),
                 "geometry": geometry_of.design_geometry(unit.get("parameters")),
                 "identity": geometry_of.design_identity(
                     unit.get("structure"), d.elements_of(unit), unit.get("parameters"))}
                for unit in units]
        found = geometry_of.repetition(view, _near_identical())
        repeated = [unit for unit in units if unit.get("id") in set(found["repeated"])]
        share = len(repeated) / float(len(units))
        if share > repeat_bar + 1e-9:
            problems.append(f"{len(repeated)} of the {len(units)} units ({share:.0%}) repeat "
                            f"another unit's layout - identical geometry, or the same "
                            f"structure, elements and objective kind with geometry nearly "
                            f"alike ({_ids(repeated)}); a {d.tier}-tier release repeats at "
                            f"most {repeat_bar:.0%} (quality-benchmark "
                            f"content.structure.max_repeated_layout_ratio)")
    return problems, len(kinds), f"{len(kinds)} structure kind(s): {', '.join(kinds)}"


def _tier_objectives(d):
    kinds_bar = d.tbar("objectives", "min_kinds")
    identical = d.tbar("objectives", "max_identical_ratio")
    if kinds_bar is None and identical is None:
        return [], None, _no_tier(d, "objective")
    units = d.release_units
    primary = [d.objective_kind(unit) for unit in units]
    secondary = sorted({str(g.get("kind")) for g in d.content.get("secondary_goals") or []
                        if isinstance(g, dict) and g.get("kind")})
    kinds = len(set(primary)) + len(secondary)
    problems = []
    if kinds_bar is not None and kinds < kinds_bar:
        problems.append(f"the units ask for {len(set(primary))} kind(s) of objective and the "
                        f"design scores {len(secondary)} secondary goal(s); a {d.tier}-tier "
                        f"release has {kinds_bar:g} objective kinds (quality-benchmark "
                        f"content.objectives.min_kinds): give units different objective_kind "
                        f"values, or score a secondary goal (stars, collectibles, par) in "
                        f"build_spec.content.secondary_goals")
    if identical is not None and d.authored and units:
        common = max(sorted(set(primary)), key=primary.count)
        share = primary.count(common) / float(len(units))
        if share > identical + 1e-9:
            problems.append(f"{primary.count(common)} of the {len(units)} units ({share:.0%}) "
                            f"ask for the same kind of thing ({common!r}); a {d.tier}-tier "
                            f"release asks for one kind in at most {identical:.0%} of its units "
                            f"(quality-benchmark content.objectives.max_identical_ratio)")
    return problems, kinds, f"{kinds} objective kind(s), {len(secondary)} of them secondary"


def _tier_groups(d):
    group_kind = d.shape.get("group_kind")
    count = d.floor(d.tbar("units", "min_groups"), "groups", "count")
    per = d.floor(d.tbar("units", "min_units_per_group"), "groups", "min_units_per_group")
    if count is None and per is None:
        return [], None, _no_tier(d, "group")
    if not group_kind:
        return [], None, (f"a {d.label} game has no group above the unit: its units are one "
                          f"sequence (genre-models budget.group_kind)")
    units = d.release_units
    problems = []
    declared = {g.get("id") for g in d.content.get("groups") or [] if isinstance(g, dict)}
    missing = [unit for unit in units if not unit.get("group")]
    if missing:
        problems.append(f"{_ids(missing)} name no group: a {d.label} release presents its units "
                        f"in {group_kind}s - name each unit's {group_kind} in `group`")
    order, members = [], {}
    for unit in units:
        group = unit.get("group")
        if not group:
            continue
        if group not in members:
            order.append(group)
        members.setdefault(group, []).append(unit)
    if declared:
        stray = [g for g in order if g not in declared]
        if stray:
            problems.append(f"the group(s) {', '.join(stray)} are not build_spec.content.groups "
                            f"ids")
    if count is not None and len(order) < count:
        basis = d.basis("units", "min_groups", "groups", "count")
        problems.append(f"the units come in {len(order)} {group_kind}(s); a {d.tier}-tier "
                        f"{d.label} release has {count:g} ({basis}): "
                        f"{int(count) - len(order)} short - content arrives in themed sets, "
                        f"not one list")
    if per is not None:
        thin = [f"{g} ({len(members[g])})" for g in order if len(members[g]) < per]
        if thin:
            basis = d.basis("units", "min_units_per_group", "groups", "min_units_per_group")
            problems.append(f"the {group_kind}(s) {', '.join(thin)} hold fewer than {per:g} "
                            f"units ({basis})")
    if d.authored:
        runs, previous = [], None
        for unit in units:
            group = unit.get("group")
            if group and group != previous:
                runs.append(group)
            previous = group or previous
        split = sorted({g for g in runs if runs.count(g) > 1})
        if split:
            problems.append(f"the {group_kind}(s) {', '.join(split)} are split by another "
                            f"{group_kind}: a group's units run one after another")
        new_in = {}
        for unit, new in _first_appearances(d):
            if new and unit.get("group"):
                new_in.setdefault(unit.get("group"), []).extend(new)
        idle = [g for g in order if not new_in.get(g)]
        if idle:
            problems.append(f"the {group_kind}(s) {', '.join(idle)} introduce no element: each "
                            f"{group_kind} brings something the player has not met (a new "
                            f"element in build_spec.content.elements, first used there)")
    milestone = d.shape.get("milestone")
    climax = d.tbar("difficulty", "min_climax_per_group")
    if milestone and climax is not None:
        unclosed = [g for g in order
                    if sum(1 for u in members[g] if u.get("purpose") == "climax") < climax]
        if unclosed:
            problems.append(f"the {group_kind}(s) {', '.join(unclosed)} have no milestone: a "
                            f"{d.label} {group_kind} closes with {milestone} - a unit of "
                            f"purpose 'climax' (quality-benchmark "
                            f"content.difficulty.min_climax_per_group {climax:g})")
    return problems, len(order), f"{len(order)} {group_kind}(s): " + ", ".join(
        f"{g} ({len(members[g])})" for g in order)


def _tier_designed_play(d):
    floor = d.floor(d.tbar("units", "min_total_designed_s"), "designed_play_s")
    if floor is None:
        return [], None, _no_tier(d, "designed-play")
    durations = [_number(u.get("expected_duration_s")) or 0 for u in d.release_units]
    if d.authored:
        total, how = sum(durations), f"the {len(durations)} units"
    else:
        many = d.generation.get("expected_units") or \
            (d.design.get("scope") or {}).get("content_units") or len(durations)
        mean = sum(durations) / float(len(durations)) if durations else 0
        total, how = mean * many, f"{many} {d.mode} units at the listed units' mean {mean:g} s"
    problems = []
    if total < floor - 1e-9:
        basis = d.basis("units", "min_total_designed_s", "designed_play_s")
        problems.append(f"{how} carry {total:g} s of designed play; a {d.tier}-tier {d.label} "
                        f"release carries {floor:g} s ({basis}): {floor - total:g} s short - "
                        f"more units, not longer ones")
    return problems, round(total, 1), f"{total:g} s designed; the floor is {floor:g} s"


def _tier_difficulty(d):
    axes_bar = d.tbar("difficulty", "min_escalating_axes")
    every = d.tbar("difficulty", "relief_every_units")
    if axes_bar is None and every is None:
        return [], None, _no_tier(d, "difficulty")
    if not d.authored:
        return [], None, _generated(d, "difficulty over the units")
    units = d.release_units
    problems = []
    rising = []
    if units:
        first, last = units[0], units[-1]
        keys = set(first.get("difficulty") or {}) | set(last.get("difficulty") or {})
        for axis_id in sorted(keys):
            before, after = d.value(first, axis_id), d.value(last, axis_id)
            if before is not None and after is not None and after > before:
                rising.append(axis_id)
    if axes_bar is not None and len(rising) < axes_bar:
        problems.append(f"difficulty escalates on {len(rising)} axis/axes over the release "
                        f"({', '.join(rising) or 'none'}, first unit to last); a {d.tier}-tier "
                        f"release escalates on {axes_bar:g} (quality-benchmark "
                        f"content.difficulty.min_escalating_axes): one axis turned up is one "
                        f"skill tested harder, not new ones asked for")
    dimensions = d.dimensions()
    minimum = d.bar("min_dimensions_changed_between_units") or 0
    most = d.bar("max_consecutive_scaling_only_units")
    run, flat = 0, []
    for position in range(1, len(units)):
        previous, unit = units[position - 1], units[position]
        if unit.get("tier") != "mvp" or previous.get("tier") != "mvp":
            # The MVP's own pairs are content.consecutive_units_differ's.
            changed = {str(x) for x in unit.get("variation_from_previous") or []} & dimensions
            if len(changed) < minimum:
                flat.append(unit)
        scaling = (not unit.get("introduces")
                   and d.objective_kind(unit) == d.objective_kind(previous)
                   and d.elements_of(unit) == d.elements_of(previous)
                   and unit.get("structure") == previous.get("structure"))
        run = run + 1 if scaling else 0
        if most is not None and run == most + 1:
            problems.append(f"{d.where(unit)} ends a run of {run} units that change only their "
                            f"numbers - the same objective kind, elements and structure as the "
                            f"unit before; at most {most} may follow one another: a new skill "
                            f"is asked for by a new element, structure or objective")
    if flat:
        problems.append(f"{_ids(flat)} change fewer than {minimum} of the family's variety "
                        f"dimensions ({', '.join(sorted(dimensions))}) in "
                        f"variation_from_previous")
    if every is not None:
        run = 0
        for position, unit in enumerate(units):
            raised = d.raised(units[position - 1], unit) if position else []
            run = 0 if (unit.get("purpose") == "breather" or not raised) else run + 1
            if run == int(every) + 1:
                problems.append(f"{d.where(unit)} is unit {run} in a row that raises an axis; a "
                                f"{d.tier}-tier release gets relief - a 'breather' unit, or one "
                                f"that raises nothing - every {every:g} units (quality-benchmark "
                                f"content.difficulty.relief_every_units)")
    return problems, rising, f"{len(rising)} axis/axes escalate over {len(units)} unit(s)"


_CHECKS = {
    "content.model_resolves": _model_resolves,
    "content.block_present": _block_present,
    "content.unit_kind_allowed": _unit_kind_allowed,
    "content.generation_allowed": _generation_allowed,
    "content.progression_model_allowed": _progression_model_allowed,
    "content.difficulty_model_allowed": _difficulty_model_allowed,
    "content.ending_matches_model": _ending_matches_model,
    "content.unit_count_mvp": _unit_count_mvp,
    "content.unit_count_total": _unit_count_total,
    "content.units_fit_session": _units_fit_session,
    "content.ids_unique_index_monotone": _ids_unique_index_monotone,
    "content.mechanics_resolve": _mechanics_resolve,
    "content.mechanics_introduced_before_use": _mechanics_introduced_before_use,
    "content.mvp_mechanics_reused": _mvp_mechanics_reused,
    "content.consecutive_units_differ": _consecutive_units_differ,
    "content.axes_declared": _axes_declared,
    "content.axes_monotone_with_relief": _axes_monotone_with_relief,
    "content.objectives_vary": _objectives_vary,
    "content.win_lose_stated": _win_lose_stated,
    "content.acceptance_specific": _acceptance_specific,
    "content.scope_count_agrees": _scope_count_agrees,
    "content.mastery_stated": _mastery_stated,
    "content.tier_stated": _tier_stated,
    "content.tier_elements": _tier_elements,
    "content.tier_introductions": _tier_introductions,
    "content.tier_combinations": _tier_combinations,
    "content.tier_structure": _tier_structure,
    "content.tier_objectives": _tier_objectives,
    "content.tier_groups": _tier_groups,
    "content.tier_designed_play": _tier_designed_play,
    "content.tier_difficulty": _tier_difficulty,
}

assert set(_CHECKS) == {rule_id for rule_id, _ in RULES}
assert _NEEDS_CONTENT <= set(_CHECKS)


def _result(rule_id, measured, breached, note):
    return {"criterion_id": rule_id, "measured": measured, "breached": breached, "note": note}


# -- introductions one at a time (design-consistency content.introductions_one_at_a_time) --
# The same count on the design (here, through consistency.projection `introductions`) and on
# the built content data file (wgf_sufficiency.audit). What a unit DEBUTS is what it says
# it introduces: its `introduces`, less anything an earlier unit (in index order) already
# named. An element and the mechanic it stands for (an armored brick, armored bricks) are one
# introduction, which a unit's `introduces` states once - so where a unit states its
# introductions, they are what is counted; content.mechanics_introduced_before_use already
# holds a unit's mechanics to the introductions before it. A unit that states no
# `introduces` at all is counted by what it shows: every element and mechanic no earlier
# unit named. After the opening unit, a unit debuts at most one: every new element is first
# met on its own and practised before it is combined with another new one.


def unit_debuts(units):
    """[(unit, [what it debuts])] over `units` in the order given. A unit that states
    `introduces` (a list, even empty) debuts what it lists that no earlier unit named; one
    that does not debuts every element and mechanic it names that no earlier unit named. A
    unit that names none of the three debuts nothing it can be held to (None, not [])."""
    seen, out = set(), []
    for unit in units:
        if not isinstance(unit, dict):
            continue
        named = [str(x) for key in ("elements", "mechanics", "introduces")
                 for x in (unit.get(key) or []) if isinstance(unit.get(key), list)]
        stated = isinstance(unit.get("introduces"), list)
        declared = stated or any(isinstance(unit.get(key), list) and unit.get(key)
                                 for key in ("elements", "mechanics"))
        if stated:
            new = sorted(set(map(str, unit["introduces"])) - seen)
        else:
            new = sorted(set(named) - seen)
        seen |= set(named)
        out.append((unit, new if declared else None))
    return out


def introduction_breaches(units, at=lambda unit: str(unit.get("id"))):
    """["<where> debuts a, b"] for every unit after the opening one that debuts more than one
    element the player has not met. `units` in play (index) order."""
    out = []
    for position, (unit, new) in enumerate(unit_debuts(units)):
        if position and new and len(new) > 1:
            out.append(f"{at(unit)} debuts {len(new)} elements at once: {', '.join(new)}")
    return out


def undeclared_units(units):
    """The ids of the units that name no element, mechanic or introduction. What such a unit
    puts in front of the player is unknown, so what the units after it debut - and which unit
    opens play - cannot be counted: the count is UNMEASURED, never a pass (a unit naming
    nothing is never silently skipped, which would let the next unit 'debut' what it met
    there, or take the opener's exemption)."""
    return [str(u.get("id")) for u, new in unit_debuts(units) if new is None]


def introductions_view(design):
    """consistency.projection `introductions`: {"units": n, "over_one": [breach],
    "debuts": {unit id: [new]}, "undeclared": [unit id]} over the design's units not tiered
    optional, in index order. A design with no units holds the rule and says so (`units` 0).
    A unit that names nothing makes the count unmeasured, which the rule - like every rule
    that cannot be checked - records as a breach naming the units to complete."""
    units = [u for u in units_of(design) if u.get("tier") != "optional"]
    debuts = unit_debuts(units)
    undeclared = undeclared_units(units)
    over_one = [] if undeclared else introduction_breaches(
        units, at=lambda u: f"build_spec.content.units[{u.get('id')}]")
    if undeclared:
        over_one = [f"build_spec.content.units[{', '.join(undeclared[:8])}"
                    + (f" and {len(undeclared) - 8} more" if len(undeclared) > 8 else "")
                    + "] name no element, mechanic or introduction: what each unit debuts "
                    "cannot be counted (unmeasured, never a pass) - name each unit's elements "
                    "and mechanics"]
    return {"units": len(units), "over_one": over_one, "undeclared": undeclared,
            "debuts": {str(u.get("id")): new for u, new in debuts if new}}


def check(design, strategy=None, models=None, vocabulary=None, benchmark=None):
    """(problems, results) for the design's content.

    `problems` are strings an author can repair, each naming the field to change and prefixed
    with its rule id. `results` is one criterionResult per rule, recorded on the design's
    `consistency.rule_results` beside the consistency ruleset's own.

    A design that names no family and whose strategy names none either is a design written
    before game-design 1.9.0: one warning, no problems, no bars applied. `benchmark` is
    core/reference/quality-benchmark.yaml, read when None; its bars apply only at a quality
    tier (`quality_tier`).
    """
    models = models or load_models()
    if vocabulary is None:
        vocabulary = load_vocabulary()
    families = models.get("families") or {}
    genre = design.get("genre") if isinstance(design, dict) else None
    named = (genre or {}).get("family") if isinstance(genre, dict) else None
    if named is not None and named not in families:
        # Nothing else can be read: every bar comes from the family, and this one is not one.
        problem = (f"genre.family is {named!r}, which core/reference/genre-models.yaml does not "
                   f"define: use one of {', '.join(sorted(families))}")
        results = [_result("content.model_resolves", named, True, problem)]
        results += [_result(rule_id, None, True,
                            f"not checked: the genre family {named!r} is unknown")
                    for rule_id, _ in RULES[1:]]
        return [f"[content.model_resolves] {problem}"], results

    family, why = resolve_family(strategy, design, models, vocabulary)
    if family is None:
        return [], [_result("content.model_resolves", None, False,
                            f"no genre family, so no content bar is applied: {why}")]

    if benchmark is None and quality_tier(design, strategy)[0] is not None:
        benchmark = load_benchmark()
    d = _Design(design, strategy, models, family, why, benchmark)
    problems, results = [], []
    for rule_id, _meaning in RULES:
        if rule_id in _NEEDS_CONTENT and not d.content:
            results.append(_result(rule_id, None, True,
                                   "not checked: build_spec.content is missing"))
            continue
        found, measured, note = _CHECKS[rule_id](d)
        results.append(_result(rule_id, measured, bool(found),
                               "; ".join(found) if found else note))
        problems += [f"[{rule_id}] {problem}" for problem in found]
    return problems, results

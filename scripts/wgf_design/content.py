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
  * difficulty moves on the family's declared axes, escalates on the ones it says escalate,
    dips only as far as relief allows and recovers, and raises no more axes at once than the
    session profile permits, with a breather inside every `relief_every_units`;
  * objectives vary, every unit says how it is won and lost in its own words, and its
    acceptance lines are specific enough to tell two units apart;
  * `scope.content_units` agrees with the list, and mastery is stated in hud metrics a player
    can read.

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

__all__ = ["MODELS_PATH", "VOCABULARY_PATH", "RULES", "MASTERY_MODELS", "load_models",
           "load_vocabulary", "family_of_node", "resolve_family", "profile_of", "units_of",
           "check", "content_model_record"]

MODELS_PATH = os.path.join(paths.REFERENCE, "genre-models.yaml")
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
     "Escalating axes end higher than they start, dip only for relief, and recover"),
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
)

# Rules that cannot be read at all without build_spec.content.
_NEEDS_CONTENT = frozenset((
    "content.unit_kind_allowed", "content.generation_allowed", "content.unit_count_mvp",
    "content.unit_count_total", "content.units_fit_session",
    "content.ids_unique_index_monotone", "content.mechanics_resolve",
    "content.mechanics_introduced_before_use", "content.mvp_mechanics_reused",
    "content.consecutive_units_differ", "content.axes_declared",
    "content.axes_monotone_with_relief", "content.objectives_vary",
    "content.win_lose_stated", "content.acceptance_specific", "content.scope_count_agrees",
))

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

    def __init__(self, design, strategy, models, family, why):
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
    minimum = d.units_bars.get("min_total") or 0
    scope_units = (d.design.get("scope") or {}).get("content_units")
    if d.mode == "authored":
        measured = len(d.units_listed)
        where = "build_spec.content.units"
    else:
        expected = d.generation.get("expected_units")
        measured = expected if isinstance(expected, int) else scope_units
        where = "build_spec.content.generation.expected_units (or scope.content_units)"
    problems = []
    if not isinstance(measured, int) or measured < minimum:
        problems.append(f"{where} says {measured!r} unit(s) at any tier; a {d.label} release "
                        f"carries {minimum}: tier the rest post-mvp, but say they exist")
    return problems, measured, f"{d.label} units at any tier: {minimum}"


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
            if mechanic not in d.mechanics and mechanic not in d.scheduled:
                problems.append(f"{d.where(unit, 'introduces')} names {mechanic!r}, not a "
                                f"build_spec.mechanics or build_spec.depth.content_schedule id")
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


def _axes_monotone_with_relief(d):
    problems = []
    units = d.mvp_units
    dip_max = d.bar("relief_dip_max")
    recovery = d.bar("relief_recovery_units") or 0
    for axis_id, axis in sorted(d.fam_axes.items()):
        if not axis.get("escalates"):
            continue
        series = [(unit, d.value(unit, axis_id)) for unit in units
                  if d.value(unit, axis_id) is not None]
        if len(series) < 2:
            continue
        first, last = series[0][1], series[-1][1]
        if last <= first:
            problems.append(f"difficulty {axis_id!r} is {first:g} on the first MVP unit and "
                            f"{last:g} on the last; an axis a {d.label} game escalates on ends "
                            f"higher than it starts")
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
    return problems, len(units), f"{d.profile_name} profile: {cap} axes per unit, relief every " \
                                 f"{every}"


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
}

assert set(_CHECKS) == {rule_id for rule_id, _ in RULES}
assert _NEEDS_CONTENT <= set(_CHECKS)


def _result(rule_id, measured, breached, note):
    return {"criterion_id": rule_id, "measured": measured, "breached": breached, "note": note}


def check(design, strategy=None, models=None, vocabulary=None):
    """(problems, results) for the design's content.

    `problems` are strings an author can repair, each naming the field to change and prefixed
    with its rule id. `results` is one criterionResult per rule, recorded on the design's
    `consistency.rule_results` beside the consistency ruleset's own.

    A design that names no family and whose strategy names none either is a design written
    before game-design 1.9.0: one warning, no problems, no bars applied.
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

    d = _Design(design, strategy, models, family, why)
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

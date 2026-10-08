"""The genre seed author: a design synthesized from a genre family's own model.

A hand-written design archetype (archetypes.py) carries one game. There are more genres than
archetypes, and a new genre is not a new code path: core/reference/genre-models.yaml states,
per family, the shape of a game of that family and - in its `seed` block - a complete starting
design for one. This author turns that block into the same `Resolved` shape the built-in
author produces, so everything after the draft is unchanged:

    seed.archetype   the archetype: loop, pillars, mechanics, controls, hud, assets, audio
    seed.experience  the experience contract (build_spec.experience)
    seed.depth       the depth plan (build_spec.depth)
    seed.units       how the content list is written: the arc of unit purposes, the objective,
                     success, failure and acceptance templates, the order mechanics are
                     introduced in, the variety dimensions cycled between units, and the
                     starting value and step of every difficulty axis

The units are generated, deterministically, against exactly the bars content.py applies:
`units.min_mvp` + 1 MVP units and `units.min_total` in all, each inside the session profile,
each changing a variety dimension, each raising at most `max_axes_raised_per_unit` axes with a
breather inside every `relief_every_units`, and each stating success, failure and acceptance in
numbers no other unit states. Nothing here branches on a family id.

It is selected three ways: research's capability catalog naming a `genre_model` instead of a
design archetype (authors.ArchetypeAuthor._resolve delegates here), `factory.design.author:
genre-seed`, or a workflow step's `with: {author: genre-seed}`. Its output is the design of
record when no agent author is configured, and the starting draft the agent author improves.

The brief's `gaps` (see authors.py) are refused: a deterministic author cannot answer a
question about a design it did not write.
"""

import copy
import re

from wgflib import genre_models

from . import content as content_rules
from .inherit import session_profile_name
from .authors import ArchetypeAuthor, AuthorError, Resolved, register_author

__all__ = ["GenreSeedAuthor", "seed_units", "purposes_for", "NUMBERS", "PLACEHOLDERS",
           "SESSION_BUDGET"]

# How long a unit runs against the archetype's own run length, by what the unit is for. A unit
# that teaches is shorter than one that tests, and the climax is the longest.
PURPOSE_SCALE = {"teach": 0.6, "test": 0.9, "twist": 1.0, "breather": 0.7, "climax": 1.25,
                 "bonus": 1.0}
# The MVP units together run at most this many sessions' worth: a prototype whose content a
# first-time player never reaches most of is built for a player who does not exist
# (content.units_fit_session uses 3; this leaves headroom).
SESSION_BUDGET = 2.4
# What a better player does differently, per mastery model (core/reference/genre-models.yaml
# `mastery.model`). The family picks the model; the sentence names this game's own signal.
MASTERY_STATEMENTS = {
    "execution": "A better player makes the same inputs cleanly under more pressure, so "
                 "{signal} climbs where it used to stall.",
    "planning": "A better player commits to a plan before acting and spends for the {kind} "
                "after this one, so {signal} holds as the pressure rises.",
    "reading": "A better player reads the whole {kind} before acting and sees two steps of "
               "consequence, so {signal} improves without guessing.",
    "optimisation": "A better player shaves the margin already in the {kind} instead of taking "
                    "more risk, so {signal} moves every time it is replayed.",
    "routing": "A better player chooses the order to meet things in, so {signal} improves "
               "without needing faster hands.",
}
# The shortest a designed unit may be, so a scaled-down session never asks for a 0 s unit.
MIN_UNIT_S = 5

# What a `seed.units` template may ask for, and what each one means. One symbol per meaning:
# a `{k}` that means seconds in one template and kinds of enemy in the next is how a wave came
# to ask the player to hold off "4 enemies of 54 kinds".
#
#   unit    the unit's id
#   s       seconds the unit is designed to take (its own duration)
#   count   how many things it sends, holds or asks for
#   kinds   distinct kinds of thing in play at once
#   few     a small number the player counts at a glance
#   budget  a spend or limit it allows: moves, gold, cash, flips
#   level   a tier or level number
#
# Each number rises with the unit's index from a start by a step, capped - the scale a family
# counts in is the family's own (`seed.units.numbers`), because 24 is a move budget, 180 is a
# gold budget and neither is the other. A quantity the seed already pins (three gems, ten base
# lives) belongs in the template as a literal, never as a placeholder that would rise past it.
NUMBERS = {
    "count": {"start": 6, "step": 3, "max": 30},
    "kinds": {"start": 2, "step": 1, "max": 4},
    "few": {"start": 2, "step": 1, "max": 5},
    "budget": {"start": 20, "step": 4, "max": 200},
    "level": {"start": 1, "step": 1, "max": 4},
}
PLACEHOLDERS = ("unit", "s") + tuple(sorted(NUMBERS))
_PLACEHOLDER = re.compile(r"\{([a-z_]+)\}")


def _scales(seed_units_block):
    """The scale this family counts in per placeholder: its own `numbers`, over the defaults."""
    stated = seed_units_block.get("numbers") or {}
    scales = {}
    for name, default in NUMBERS.items():
        given = stated.get(name) if isinstance(stated.get(name), dict) else {}
        scales[name] = {key: given.get(key, default[key]) for key in ("start", "step", "max")}
    return scales


def _check_templates(family, seed_units_block):
    """Every placeholder the family's templates use is one this author knows how to fill.

    A template asking for something undefined is a design nobody can read - "4 enemies of 54
    kinds" - so it is refused here by name rather than rendered as whatever was to hand.
    """
    unknown = {}
    for key in ("objective_templates", "acceptance_templates"):
        for template in seed_units_block.get(key) or []:
            for name in _PLACEHOLDER.findall(str(template)):
                if name not in PLACEHOLDERS:
                    unknown.setdefault(name, f"{key}: {template}")
    for key in ("success_template", "failure_template"):
        for name in _PLACEHOLDER.findall(str(seed_units_block.get(key) or "")):
            if name not in PLACEHOLDERS:
                unknown.setdefault(name, f"{key}: {seed_units_block[key]}")
    if unknown:
        named = "; ".join(f"{{{name}}} in {where}" for name, where in sorted(unknown.items()))
        raise AuthorError(
            f"the {family.get('label')} genre model's seed templates ask for a placeholder "
            f"this author cannot fill ({named}); the vocabulary is "
            f"{', '.join('{' + name + '}' for name in PLACEHOLDERS)}")


def _bar(family, models, key):
    """A variety bar: the family's own, else the ruleset's (as content.py reads them)."""
    local = family.get("variety") or {}
    if key in local:
        return local[key]
    return (models.get("variety") or {}).get(key)


def _profile_name(strategy):
    """`casual` tightens how long a unit runs and how many axes one unit may raise. Not a
    family: the same game is designed either way (inherit.session_profile_name)."""
    return session_profile_name(strategy)


def purposes_for(arc, count, relief_every):
    """What each of `count` units is for, from the family's `unit_arc`.

    The arc's first entry opens and its last closes, whatever the count; the middle is cycled.
    A breather is forced wherever the session profile's `relief_every_units` would otherwise be
    passed, including by the closing unit - a curve that only ever rises has no shape, and the
    check (content.axes_monotone_with_relief) refuses it.
    """
    arc = [str(p) for p in arc or []] or ["teach", "test", "climax"]
    if count <= 1:
        return [arc[0]]
    body = arc[1:-1] or [arc[0]]
    purposes = [arc[0]]
    run = 0
    for index in range(1, count - 1):
        purpose = body[(index - 1) % len(body)]
        # The unit before the last must leave room for the last one to raise something.
        ceiling = (relief_every - 1) if (relief_every and index == count - 2) else relief_every
        if ceiling is not None and purpose != "breather" and run + 1 > max(ceiling, 1):
            purpose = "breather"
        purposes.append(purpose)
        run = 0 if purpose == "breather" else run + 1
    purposes.append(arc[-1])
    return purposes


def _difficulty(family, axis_profile, purposes, profile):
    """One difficulty reading per unit, on the family's axes.

    Every axis starts at its `axis_profile` start and only ever climbs: a unit raises at most
    the session profile's `max_axes_raised_per_unit` axes, taken in turn; a `breather` dips the
    axis standing highest and the unit after it puts that axis back above where it was, so
    relief is relief and not a flat curve; a `climax` raises every escalating axis at once,
    which is what makes the last unit higher than the first on all of them.
    """
    axes = [a for a in family.get("axes") or [] if a.get("id") in axis_profile]
    escalating = [a["id"] for a in axes if a.get("escalates")]
    rotation = escalating + [a["id"] for a in axes if not a.get("escalates")]
    if not rotation:
        return [{} for _ in purposes]
    low = {a["id"]: (a.get("range") or [0, 1])[0] for a in axes}
    high = {a["id"]: (a.get("range") or [0, 1])[1] for a in axes}

    def step(axis_id):
        return float((axis_profile.get(axis_id) or {}).get("step") or 0.1)

    def start(axis_id):
        return float((axis_profile.get(axis_id) or {}).get("start") or low[axis_id])

    cap = int(profile.get("max_axes_raised_per_unit") or 1)
    ceiling = {axis_id: high[axis_id] - 0.05 for axis_id in rotation}
    base = {axis_id: round(start(axis_id), 3) for axis_id in rotation}
    rows, cursor, dipped = [dict(base)], 0, None
    for purpose in purposes[1:]:
        if purpose == "breather":
            dipped = max(escalating or rotation, key=lambda axis_id: base[axis_id])
            row = dict(base)
            # A dip, not a regression: shallower than `relief_dip_max` of the value before it.
            row[dipped] = round(max(low[dipped], base[dipped] * 0.75), 3)
            rows.append(row)
            continue
        if dipped is not None and purpose != "climax":
            # The one axis the breather dipped, put back above where it was - and nothing else,
            # so the unit still raises only one axis against the breather before it.
            base[dipped] = round(min(ceiling[dipped], base[dipped] + step(dipped)), 3)
            dipped = None
            rows.append(dict(base))
            continue
        raising = escalating if purpose == "climax" else \
            [rotation[(cursor + offset) % len(rotation)] for offset in range(cap)]
        if purpose != "climax":
            cursor += cap
        for axis_id in raising or rotation[:1]:
            base[axis_id] = round(min(ceiling[axis_id], base[axis_id] + step(axis_id)), 3)
        dipped = None
        rows.append(dict(base))
    return rows


def _durations(purposes, mvp_count, run_seconds, profile, strategy):
    """How long each unit is designed to take: the archetype's own run length scaled by what
    the unit is for, inside the session profile's longest unit, with the first unit at most
    half of one, and the MVP units together inside the session they are played in. Every unit
    gets its own number, so no two units accept the same thing."""
    longest = float(profile.get("max_unit_s") or run_seconds or 60)
    target = ((strategy or {}).get("session") or {}).get("target_seconds")
    weight = sum(PURPOSE_SCALE.get(p, 1.0) for p in purposes[:mvp_count]) or 1.0
    unit_base = min(float(run_seconds or longest), longest)
    if isinstance(target, (int, float)) and target > 0:
        unit_base = min(unit_base, SESSION_BUDGET * float(target) / weight)
    out, seen = [], set()
    for index, purpose in enumerate(purposes):
        value = int(max(MIN_UNIT_S, round(unit_base * PURPOSE_SCALE.get(purpose, 1.0))))
        value = min(value, int(longest))
        if index == 0:
            value = min(value, max(MIN_UNIT_S, int(longest // 2)))
        while value in seen and value > MIN_UNIT_S:
            value -= 1
        while value in seen:
            value += 1
        seen.add(value)
        out.append(value)
    return out


# Where a mechanic may be introduced (core/craft/content-and-level-design.md "Introduce, then
# reuse": during a teach, a breather or the opening of a twist - never on a peak), most
# preferred first. A `test` unit takes one only when those run out.
INTRODUCE_IN = ("teach", "breather", "twist", "test")


def _introductions(introduce_order, mechanics, purposes, mvp_count, busy=()):
    """Which unit teaches which mechanic: the family's `introduce_order`, one mechanic per
    unit. The opening unit, where play begins, takes the first; every later MVP unit that may
    introduce one (INTRODUCE_IN, never the climax, never the last MVP unit - a mechanic
    taught there is never asked for again) takes the next, the preferred purposes first, in
    play order - so no unit after the opener debuts two never-seen mechanics at once
    (design-consistency content.introductions_one_at_a_time) and the opener is not piled
    up. Only when the MVP has fewer such units than mechanics does the opener take the
    excess: the MVP's unit count is the family's (`units.min_mvp` + 1), and a mechanic of the
    MVP is taught inside it. `busy`: positions that already debut something else (a content
    element a release lays out): never given a mechanic too. Mechanics accumulate, so a unit
    asks for everything taught up to and including it."""
    order = [m for m in introduce_order or [] if m in mechanics]
    order += [m for m in mechanics if m not in order]
    last = max(1, mvp_count - 1)
    slots = [i for i in range(1, last) if purposes[i] in INTRODUCE_IN and i not in busy]
    slots.sort(key=lambda i: (INTRODUCE_IN.index(purposes[i]), i))
    slots = sorted(slots[:max(0, len(order) - 1)])
    opening = max(1, len(order) - len(slots))
    chunks = {0: order[:opening]}
    for rank, position in enumerate(slots):
        chunks[position] = order[opening + rank:opening + rank + 1]
    return chunks


def _objective_choices(count, mvp_count, templates):
    """Which objective template each unit uses: the templates in turn, except that the last MVP
    unit asks for something neither the opening unit nor the one before it asked for. A climax
    that restates the opening objective at higher numbers is the scaling the variety bars exist
    to refuse (content.objectives_vary, content.consecutive_units_differ)."""
    chosen = []
    for index in range(count):
        pick = index % templates
        if templates > 2 and index == mvp_count - 1 and chosen:
            taken = {chosen[0], chosen[-1]}
            pick = next((c for c in range(templates - 1, -1, -1) if c not in taken), pick)
        chosen.append(pick)
    return chosen


def _variation(index, introduces, cycle, dimensions):
    """The variety dimensions this unit changes against the one before it: one from the
    family's `variation_cycle`, plus `introduces` when it really does introduce something."""
    if index == 0:
        return []
    body = [d for d in cycle if d in dimensions and d != "introduces"]
    body = body or sorted(d for d in dimensions if d != "introduces") or sorted(dimensions)
    picks = [body[(index - 1) % len(body)]] if body else []
    if introduces and "introduces" in dimensions:
        picks.insert(0, "introduces")
    return picks


def _too_alike(units, bar):
    """The first pair of acceptance lines at or above `bar` (token-set Jaccard), as
    content.acceptance_specific measures it, or None. A generator that produced two units a
    tester cannot tell apart has a defect, and says so instead of shipping them."""
    # Measured exactly as content.acceptance_specific measures it, stop words and all: a
    # looser measure here would let through what the check then refuses.
    lines = [(unit["id"], line, content_rules._tokens(line))
             for unit in units for line in unit["acceptance"]]
    for left in range(len(lines)):
        for right in range(left + 1, len(lines)):
            a, b = lines[left][2], lines[right][2]
            if not a or not b:
                continue
            if len(a & b) / float(len(a | b)) >= bar:
                return lines[left], lines[right]
    return None


def seed_units(family, seed_units_block, strategy, mechanics, profile, run_seconds=60,
               unit_kind="level", models=None):
    """The content units a game of this family carries: `units.min_mvp` + 1 in the MVP and
    `units.min_total` in all, generated from the family's `seed.units` block.

    `family` is the family block, `mechanics` its MVP mechanic ids in declaration order,
    `profile` the session-profile bars. Returns the units in index order.
    """
    models = models or genre_models.load()
    bars = family.get("units") or {}
    min_mvp = int(bars.get("min_mvp") or 1)
    mvp_count = min_mvp + 1
    total = max(int(bars.get("min_total") or mvp_count), mvp_count)
    arc = seed_units_block.get("unit_arc") or []
    purposes = purposes_for(arc, mvp_count, profile.get("relief_every_units"))
    tail = [str(p) for p in arc] or ["test"]
    purposes += [tail[(index - mvp_count) % len(tail)] for index in range(mvp_count, total)]
    if total > mvp_count:
        # The release closes the way the MVP does: on the arc's last purpose, never on a
        # breather's dip that no later unit recovers (content.axes_monotone_with_relief reads
        # every release unit above tier mvp).
        purposes[-1] = tail[-1]

    axis_profile = seed_units_block.get("axis_profile") or {}
    readings = _difficulty(family, axis_profile, purposes, profile)
    durations = _durations(purposes, mvp_count, run_seconds, profile, strategy)
    chunks = _introductions(seed_units_block.get("introduce_order"), list(mechanics),
                            purposes, mvp_count)
    dimensions = {str(d) for d in (family.get("variety") or {}).get("dimensions") or []}
    cycle = [str(d) for d in seed_units_block.get("variation_cycle") or []]
    objectives = list(seed_units_block.get("objective_templates") or []) or ["Clear {unit}"]
    acceptance = list(seed_units_block.get("acceptance_templates") or []) or ["{unit} is built"]
    success_template = str(seed_units_block.get("success_template") or "")
    failure_template = str(seed_units_block.get("failure_template") or "")
    wanted = max(int(_bar(family, models, "acceptance_min_items") or 2), 2)
    _check_templates(family, seed_units_block)
    scales = _scales(seed_units_block)
    asked = _objective_choices(len(purposes), mvp_count, len(objectives))
    prefix = re.sub(r"[^a-z]", "", str(unit_kind).lower())[:1] or "u"

    units, taught, elapsed = [], [], 0
    for index, purpose in enumerate(purposes):
        number = index + 1
        unit_id = f"{prefix}-{number:02d}"
        mvp = index < mvp_count
        introduces = list(chunks.get(index) or []) if mvp else []
        taught += [m for m in introduces if m not in taught]
        asks = list(taught) if taught else list(mechanics[:1])
        duration = durations[index]
        elapsed += duration
        reading = readings[index]
        values = {"unit": unit_id, "s": duration}
        for name, scale in scales.items():
            values[name] = min(scale["max"], scale["start"] + scale["step"] * index)
        # Every acceptance line ends in this unit's own numbers - where it sits, how hard it
        # is, how long it runs, and how far into the set it is reached. Three of them are
        # unique to this unit by construction, which is what tells two units apart
        # (content.acceptance_specific): a tester reading one line knows which unit it is.
        hardness = int(round(100.0 * sum(reading.values()) / max(1, len(reading))))
        mark = (f" (unit {number} of {total}, difficulty {hardness}%, {duration} s, "
                f"{elapsed} s in)")
        units.append({
            "id": unit_id,
            "index": number,
            "tier": "mvp" if mvp else "post-mvp",
            "purpose": purpose if mvp else "bonus",
            "objective": objectives[asked[index]].format_map(values),
            "mechanics": asks,
            "difficulty": dict(reading),
            "expected_duration_s": duration,
            "success": success_template.format_map(values),
            "failure": failure_template.format_map(values),
            "acceptance": [acceptance[(index + offset) % len(acceptance)].format_map(values)
                           + mark for offset in range(wanted)],
            "variation_from_previous": _variation(index, introduces, cycle, dimensions),
            "parameters": {"index": number, "duration_s": duration},
        })
        if introduces:
            units[-1]["introduces"] = introduces
    pair = _too_alike(units, _bar(family, models, "acceptance_max_similarity") or 0.8)
    if pair:
        raise AuthorError(
            f"the {family.get('label')} genre model's acceptance templates produce two lines a "
            f"tester cannot tell apart ({pair[0][0]} / {pair[1][0]}): {pair[0][1]!r} / "
            f"{pair[1][1]!r} - give the templates a number that changes per unit")
    return units


class GenreSeedAuthor(ArchetypeAuthor):
    """Designs from a genre family's model rather than from a hand-written archetype."""

    name = "genre-seed"

    def _resolve(self, brief):
        strategy = brief["strategy"]
        models = genre_models.load()
        family_id, why = content_rules.resolve_family(strategy, None, models)
        if not family_id:
            raise AuthorError(
                f"the genre seed author designs from a genre family and none resolves: {why}")
        return self.synthesize(family_id, models, strategy,
                               (models.get("families") or {})[family_id])

    @staticmethod
    def refuse_an_idea(family_id, strategy):
        """Raise when the strategy's concept is the person's own idea.

        The seed is one game per family - the slide-and-clear grid, the lane defense - and it
        is the whole of what this author can design. A catalog entry that names only a family
        is a capability, and the strategy then carries the idea as the concept; designing the
        seed would describe a different game, which the consistency rules refuse a step
        later. Say it here, and name the author that can."""
        brief = strategy.get("brief")
        concept = (strategy.get("concept") or {}).get("core_mechanic") or ""
        if brief and concept.strip() == str(brief).strip():
            raise AuthorError(
                f"this title's concept is the person's idea, and the {family_id} family's seed "
                f"is one particular game of that family: designing it would describe a "
                f"different game. An idea needs the agent author "
                f"(factory.design.author: agent); the seed designs a title whose concept "
                f"research took from the catalog.")

    def synthesize(self, family_id, models, strategy, entry):
        """`Resolved` for a game of family `family_id`, built from the family's `seed` block.
        As the agent author's starting point the seed is only the required shape, which the
        agent rewrites into the person's idea - so an idea is refused only when the seed would
        be the design."""
        if not self.starting_point:
            self.refuse_an_idea(family_id, strategy)
        seed = entry.get("seed")
        if not isinstance(seed, dict) or not isinstance(seed.get("archetype"), dict):
            raise AuthorError(f"core/reference/genre-models.yaml family {family_id!r} carries no "
                              f"`seed` block: the genre seed author has nothing to design from")
        a = copy.deepcopy(seed["archetype"])
        profile_name = _profile_name(strategy)
        profile = dict((models.get("session_profiles") or {}).get(profile_name)
                       or (models.get("session_profiles") or {}).get("standard") or {})
        endings = [str(e) for e in entry.get("ending") or []] or ["endless"]
        wants_win = isinstance(seed.get("experience"), dict) and "win" in seed["experience"]
        ending = "finite" if wants_win and "finite" in endings else \
            ("endless" if "endless" in endings else endings[0])
        a["genre"] = {"family": family_id,
                      "node": (entry.get("nodes") or [family_id])[0],
                      "ending": ending}
        a["difficulty_axes"] = [axis["id"] for axis in entry.get("axes") or []
                                if axis.get("id")]
        kinds = [str(k) for k in entry.get("unit_kinds") or []] or ["level"]
        kind = a.get("content_unit_kind") if a.get("content_unit_kind") in kinds else kinds[0]
        order = [m for m in (seed.get("units") or {}).get("introduce_order") or []]
        mechanics = [m["id"] for m in a.get("mechanics") or [] if m.get("tier") == "mvp"]
        for mechanic in a.get("mechanics") or []:
            # The verbs the first unit teaches are what every unit uses; the rest are taught by
            # a unit and reused after it; a mechanic the MVP does not build is a variation.
            if mechanic.get("tier") != "mvp":
                role = "variation"
            elif mechanic.get("id") in order[:2]:
                role = "core"
            else:
                role = "introduced"
            mechanic.setdefault("progression_role", role)
        units = seed_units(entry, seed.get("units") or {}, strategy, mechanics, profile,
                           run_seconds=a.get("run_seconds") or 60, unit_kind=kind, models=models)
        modes = [str(m) for m in (entry.get("units") or {}).get("generation") or []]
        mode = "authored" if "authored" in modes else (modes[0] if modes else "authored")
        generation = {"mode": mode}
        if mode != "authored":
            generation["expected_units"] = len(units)
        a["content"] = {"unit_kind": kind, "generation": generation, "units": units}
        a["content_units"] = len(units)
        a["content_unit_kind"] = kind
        a["mastery"] = self._mastery(entry, seed, kind)
        label = entry.get("label") or family_id
        why = (f"strategy is designed from the {label} genre model "
               f"(core/reference/genre-models.yaml), which carries no hand-written design "
               f"archetype")
        applied = [{"field": "archetype", "source": "research",
                    "detail": f"{a.get('id')}: the {label} genre model's seed design, "
                              f"{len(units)} {kind} unit(s) on a {profile_name} session"}]
        return Resolved(str(a.get("id") or family_id), a,
                        copy.deepcopy(seed.get("experience") or {}),
                        copy.deepcopy(seed.get("depth") or {}), why, applied)

    @staticmethod
    def _mastery(entry, seed, kind):
        """What getting better means: the family's model, a sentence naming this game's own
        signal, and the hud metrics a player reads it from (`build_spec.mastery`)."""
        mastery = entry.get("mastery") or {}
        model = str(mastery.get("model") or "execution")
        shown = {h.get("id") for h in (seed.get("archetype") or {}).get("hud") or []
                 if h.get("tier") == "mvp"}
        metrics = (seed.get("experience") or {}).get("hud_metrics") or {}
        signals = [str(metric) for element, metric in sorted(metrics.items())
                   if element in shown][:3]
        signals = signals or sorted(str(x) for x in shown)[:3]
        statement = MASTERY_STATEMENTS.get(model, MASTERY_STATEMENTS["execution"]).format(
            signal=signals[0] if signals else "the score", kind=str(kind).replace("-", " "))
        return {"model": model, "statement": statement, "signals": signals}


register_author(GenreSeedAuthor.name, GenreSeedAuthor)

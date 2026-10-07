"""Release-tier designs for the quality-consistency suite, made by the design module itself.

The genre seed author (scripts/wgf_design/seed.py) designs one game per genre family, sized
for the MVP tier: the built-in authors never write release-tier content. A release-tier
design is an agent author's work, and this suite runs no agent. `ReleaseSeedAuthor` stands
in for one: it takes the family's seed and lays the content out the way a release carries it
- groups of four units, each group introducing two elements, mixing older ones back in, and
closing on a climax with its own art; three structure kinds and a climax arena; four
objective kinds and a scored secondary goal; difficulty that rises within a group, dips at
the start of the next, and rises on every escalating axis at the climax.

What the design keeps across a reload is the seed's own meta loop: stage progress for most
families, a best for some. The probe measures stage progress by the unit reached
(core/reference/design-depth.yaml `playability.persists.probe_measures`), so nothing is added
to make persistence measurable. `UnreportedPersistenceAuthor` keeps the same content with a
meta loop the probe cannot report, for the anti-gaming case.

Nothing here judges the result. The design step does - the same step a real run calls, with
every rule of core/reference/design-consistency-rules.yaml and the content.tier_* bars of
core/reference/quality-benchmark.yaml at the release tier - and the suite fails if it
refuses the design.
"""

import copy
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.dirname(os.path.dirname(HERE))
SCRIPTS = os.path.dirname(TESTS)
for _path in (SCRIPTS, TESTS):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from wgf_design import register_author  # noqa: E402
from wgf_design import seed as seeding  # noqa: E402
from wgf_design.authors import Resolved  # noqa: E402
from wgf_design.beats import META_PERSISTED as META_SYSTEMS  # noqa: E402

AUTHOR = "release-seed-fixture"
AUTHOR_UNREPORTED = "release-unreported-persistence-fixture"
UNITS_PER_GROUP = 4
# Per slot of a group: what the unit is for, how it is built and what it asks for.
SLOT_PURPOSE = ("teach", "test", "twist", "climax")
SLOT_STRUCTURE = ("static-field", "moving-field", "path-with-turns", "climax-arena")
SLOT_OBJECTIVE = ("clear-the-field", "survive-the-timer", "reach-the-exit", "beat-the-finale")
# Per slot: the signature moment the unit is built around (game-design 1.15.0), and the
# decision the player makes there most often.
SLOT_MOMENT = ("clear-burst", "chain-rise", None, "finale-break")
SLOT_DECISION = ("take the near target now or line up the far one",
                 "keep the chain going or bank what it has paid",
                 "use the new rule against the old threat or avoid it",
                 "commit to the opening the phase change makes or wait it out")
# What the release's units are compared with: three fixture teardown records the strategy's
# research carries (test data, never evidence - the design's references note says so).
TEARDOWNS = ("game-fixture-leader-a", "game-fixture-leader-b", "game-fixture-leader-c")
# The market's designed play for a finite release (quality-benchmark design.designed_play).
FINITE_DESIGNED_S = 1800


def group_count(entry):
    """Groups of four, enough for the larger of the benchmark's 12 units and the family's own
    release total."""
    total = max(12, int((entry.get("units") or {}).get("min_total") or 0))
    return max(3, -(-total // UNITS_PER_GROUP))


def element_ids(family_id, groups):
    """Two elements per group: what the group introduces."""
    return [f"{family_id}-element-{n + 1}" for n in range(2 * groups)]


def _purposes(groups):
    out = []
    for group in range(groups):
        for slot, purpose in enumerate(SLOT_PURPOSE):
            out.append("breather" if slot == 0 and group else purpose)
    return out


def _elements(family_id, groups):
    """Per unit: the elements it is made of. A group's first unit brings its first new
    element with an older one, its second both new ones, its third the second new one with
    an older one, and its climax both new ones with a third older one. The first group has
    nothing older: its own starter piece plays that part."""
    ids = element_ids(family_id, groups)
    starter = f"{family_id}-starter"
    out = []
    for group in range(groups):
        new = ids[2 * group:2 * group + 2]
        if not group:
            out += [[new[0]], [new[0], new[1]], [new[1], starter], [new[0], new[1], starter]]
            continue
        old = [starter] + ids[:2 * group]
        a, b, c = (old[(2 * group + k) % len(old)] for k in (0, 1, 2))
        out += [[new[0], a], [new[0], new[1]], [new[1], b], [new[0], new[1], c]]
    return out


def release_units(family_id, entry, strategy, mechanics, profile, run_seconds, kind, models,
                  groups=None, roles=None, finite=False):
    """The release's units: seed_units' own construction over a release-length arc."""
    block = (entry.get("seed") or {}).get("units") or {}
    groups = groups or group_count(entry)
    purposes = _purposes(groups)
    total = len(purposes)
    mvp_count = int((entry.get("units") or {}).get("min_mvp") or 1) + 1
    # The MVP never ends on a breather: its dip would have no unit to recover in.
    while mvp_count < total and purposes[mvp_count - 1] == "breather":
        mvp_count += 1
    axis_profile = block.get("axis_profile") or {}
    readings = seeding._difficulty(entry, axis_profile, purposes, profile)
    durations = seeding._durations(purposes, mvp_count, run_seconds, profile, strategy)
    chunks = _one_at_a_time(seeding._introductions(block.get("introduce_order"),
                                                   list(mechanics), purposes, mvp_count),
                            purposes, roles or {})
    dimensions = {str(d) for d in (entry.get("variety") or {}).get("dimensions") or []}
    cycle = [str(d) for d in block.get("variation_cycle") or []]
    objectives = list(block.get("objective_templates") or []) or ["Clear {unit}"]
    acceptance = list(block.get("acceptance_templates") or []) or ["{unit} is built"]
    success_template = str(block.get("success_template") or "")
    failure_template = str(block.get("failure_template") or "")
    wanted = max(int(seeding._bar(entry, models, "acceptance_min_items") or 2), 2)
    scales = seeding._scales(block)
    asked = seeding._objective_choices(total, mvp_count, len(objectives))
    prefix = re.sub(r"[^a-z]", "", str(kind).lower())[:1] or "u"
    elements = _elements(family_id, groups)

    units, taught, elapsed = [], [], 0
    for index, purpose in enumerate(purposes):
        number = index + 1
        group, slot = divmod(index, UNITS_PER_GROUP)
        unit_id = f"{prefix}-{number:02d}"
        introduces = list(chunks.get(index) or [])
        taught += [m for m in introduces if m not in taught]
        asks = list(taught) if taught else list(mechanics[:1])
        duration = durations[index]
        elapsed += duration
        reading = readings[index]
        values = {"unit": unit_id, "s": duration}
        for name, scale in scales.items():
            values[name] = min(scale["max"], scale["start"] + scale["step"] * index)
        hardness = int(round(100.0 * sum(reading.values()) / max(1, len(reading))))
        mark = (f" (unit {number} of {total}, the {purpose} of group {group + 1}, difficulty "
                f"{hardness}%, {duration} s, {elapsed} s in)")
        unit = {
            "id": unit_id,
            "index": number,
            "tier": "mvp" if index < mvp_count else "post-mvp",
            "purpose": purpose,
            "objective": objectives[asked[index]].format_map(values),
            "objective_kind": SLOT_OBJECTIVE[slot],
            "group": f"g{group + 1}",
            "structure": SLOT_STRUCTURE[slot],
            "elements": list(elements[index]),
            "mechanics": asks,
            "difficulty": dict(reading),
            "expected_duration_s": duration,
            "success": success_template.format_map(values),
            "failure": failure_template.format_map(values),
            "acceptance": [acceptance[(index + offset) % len(acceptance)].format_map(values)
                           + mark for offset in range(wanted)],
            "variation_from_previous": seeding._variation(index, introduces, cycle,
                                                          dimensions),
            "parameters": {"layout": [f"{unit_id}-row-{row}-{(number * 7 + row * 3) % 11}"
                                      for row in range(4)],
                           "spawns": [number * 3 + slot, group * 5 + 1]},
        }
        if introduces:
            unit["introduces"] = introduces
        if purpose == "climax":
            unit["art"] = [f"finale-{group + 1}"]
        unit["beat"] = {
            "claim": f"A first-time player meets {unit_id} as a {purpose} and clears it within "
                     f"{3 if purpose == 'climax' else 2} attempts",
            "test": f"The bot's traversal and the probe record the attempts at {unit_id}; more "
                    f"than the claim falsifies it",
            "decision": {"choice": SLOT_DECISION[slot], "every_s": 3 + slot % 2}}
        if SLOT_MOMENT[slot]:
            unit["beat"]["signature_moment"] = SLOT_MOMENT[slot]
        if purpose == "twist":
            unit["beat"]["risk_reward"] = {"line": "the narrow route past the new threat",
                                           "payoff": "a star and the time it saves"}
        if purpose == "climax":
            unit["beat"]["climax"] = {
                "change": "phase-change", "phases": 2,
                "description": f"Halfway through {unit_id} the field turns over and the "
                               f"group's two new elements trade roles"}
        units.append(unit)
    if finite:
        _stretch(units, profile)
    return units, groups


def _one_at_a_time(chunks, purposes, roles):
    """The seed's introductions, one mechanic per unit (quality-benchmark design.beats): the
    first unit keeps the core verb and one more, and each later mechanic arrives alone, in the
    next teach, breather or twist unit."""
    order = [m for position in sorted(chunks) for m in chunks[position]]
    core = [m for m in order if roles.get(m) == "core"]
    rest = [m for m in order if m not in core]
    eligible = [i for i, purpose in enumerate(purposes) if purpose in ("teach", "breather",
                                                                       "twist")]
    out = {eligible[0]: core + rest[:1]}
    for position, mechanic in zip(eligible[1:], rest[1:]):
        out[position] = [mechanic]
    return out


def _stretch(units, profile):
    """A finite release carries the market's designed play: every unit after the first grows
    toward the session profile's longest unit, never past it, until the total holds (the first
    stays short; the caller adds a group when the cap is reached first)."""
    longest = int(profile.get("max_unit_s") or 0)
    grown = units[1:]
    while grown and longest:
        short = FINITE_DESIGNED_S - sum(u["expected_duration_s"] for u in units)
        room = [u for u in grown if u["expected_duration_s"] < longest]
        if short <= 0 or not room:
            break
        each = -(-short // len(room))
        for unit in room:
            unit["expected_duration_s"] = min(longest, unit["expected_duration_s"] + each)
    seen = set()
    for unit in units:
        value = unit["expected_duration_s"]
        while value in seen and value > 1:
            value -= 1
        seen.add(value)
        unit["expected_duration_s"] = value
        unit["acceptance"] = [re.sub(r", \d+ s, ", f", {value} s, ", line)
                              for line in unit["acceptance"]]


class ReleaseSeedAuthor(seeding.GenreSeedAuthor):
    """The family's seed, its content laid out for the release tier (see the module doc)."""

    name = AUTHOR
    unreported_persistence = False

    def synthesize(self, family_id, models, strategy, entry):
        resolved = super().synthesize(family_id, models, strategy, entry)
        a = copy.deepcopy(resolved.archetype)
        profile_name = seeding._profile_name(strategy)
        profile = dict((models.get("session_profiles") or {}).get(profile_name)
                       or (models.get("session_profiles") or {}).get("standard") or {})
        mechanics = [m["id"] for m in a.get("mechanics") or [] if m.get("tier") == "mvp"]
        kind = a["content"]["unit_kind"]
        roles = {m["id"]: m.get("progression_role") for m in a.get("mechanics") or []}
        finite = (a.get("genre") or {}).get("ending") == "finite"
        groups = group_count(entry)
        while True:
            # A finite release carries the market's designed play: more groups, not longer
            # units, until it holds.
            units, groups = release_units(family_id, entry, strategy, mechanics, profile,
                                          a.get("run_seconds") or 60, kind, models,
                                          groups=groups, roles=roles, finite=finite)
            if not finite or groups >= 12 or \
                    sum(u["expected_duration_s"] for u in units) >= FINITE_DESIGNED_S:
                break
            groups += 1
        content = a["content"]
        content["units"] = units
        content["quality_tier"] = "release"
        content["groups"] = [{"id": f"g{n + 1}", "name": f"Group {n + 1}"}
                             for n in range(groups)]
        kinds = [str(k) for k in (entry.get("budget") or {}).get("element_kinds") or []] \
            or ["element"]
        used = []
        for unit in units:
            used += [e for e in unit["elements"] if e not in used]
        content["elements"] = [{"id": e, "kind": kinds[n % len(kinds)],
                                "description": f"The {kinds[n % len(kinds)]} {e} changes what "
                                               f"the player must do where it appears"}
                               for n, e in enumerate(used)]
        content["secondary_goals"] = [{"id": "stars", "kind": "stars",
                                       "description": "Up to three stars per unit for a "
                                                      "clean clear"}]
        content["signature_moments"] = [
            {"id": "clear-burst", "kind": "end-of-unit-payoff",
             "description": "The last target bursts and the stars count up one by one",
             "trigger": "clearing a unit, once per unit"},
            {"id": "chain-rise", "kind": "combo-escalation",
             "description": "Each link of a chain raises the pitch and the multiplier",
             "trigger": "three or more scores within two seconds"},
            {"id": "finale-break", "kind": "rare-spectacle",
             "description": "The finale's field breaks apart into its second phase",
             "trigger": "the climax's phase change, once per group"}]
        persisted = sorted({str(p.get("kind")) for p in (resolved.depth.get("meta") or {})
                            .get("persists") or [] if isinstance(p, dict)})
        declined = next(k for k in ("currency", "cosmetics", "upgrades") if k not in persisted)
        content["meta_systems"] = [
            {"system": kind, "decision": "include",
             "why": f"The {kind} the player keeps between sessions is the reason to return"}
            for kind in persisted if kind in META_SYSTEMS] + [
            {"system": declined, "decision": "decline",
             "why": f"A {declined} system would sit between the player and the next unit for "
                    f"no gain"}]
        a["content_units"] = len(units)
        depth = copy.deepcopy(resolved.depth)
        if self.unreported_persistence:
            # Every MVP entry the seed keeps becomes cosmetics: a kind no probe measure
            # reports, delivered by no HUD metric.
            for entry in (depth.get("meta") or {}).get("persists") or []:
                if entry.get("tier") == "mvp":
                    entry["kind"] = "cosmetics"
        return Resolved(resolved.archetype_id, a, resolved.experience, depth,
                        resolved.why, resolved.applied)

    def draft(self, brief):
        """The seed's draft, compared with the teardowns the strategy's research carries."""
        out = super().draft(brief)
        research = (brief.get("strategy") or {}).get("research") or {}
        games = [c for c in research.get("competitors") or []
                 if isinstance(c, dict) and c.get("depth") == "teardown"]
        ids = [c["game"] for c in games]
        out["references"] = {
            "status": "grounded" if ids else "unknown",
            "teardowns": [{"game": c["game"], "name": c["name"]} for c in games],
            "dimensions": [
                {"dimension": dimension, "games": ids,
                 "observed": f"FIXTURE: the fixture leaders' {dimension.replace('_', ' ')}",
                 "design": f"FIXTURE: build_spec.content answers their "
                           f"{dimension.replace('_', ' ')}"}
                for dimension in ("core_verbs", "signature_moments", "set_pieces_per_group",
                                  "content_duration", "meta_systems")] if ids else []}
        if not ids:
            out["references"]["reason"] = "the research carries no teardown record"
        return out


class UnreportedPersistenceAuthor(ReleaseSeedAuthor):
    """The same release-tier content, with a meta loop whose MVP entries are a kind the probe
    reports nothing of."""

    name = AUTHOR_UNREPORTED
    unreported_persistence = True


register_author(AUTHOR, ReleaseSeedAuthor)
register_author(AUTHOR_UNREPORTED, UnreportedPersistenceAuthor)


def design(family_id, unreported_persistence=False):
    """(the game-design the real design step writes for family `family_id` at the release
    tier, the step result)."""
    import test_design_module as design_tests
    import test_design_seed as seeds
    strategy = seeds.strategy_for(family_id)
    # A release's units are played over many sessions, not one: a standard session profile
    # (core/reference/genre-models.yaml), whose longest unit lets the release's units carry
    # the market's designed play for a finite game without tripling the suite's content.
    strategy["session"] = dict(strategy["session"], target_seconds=600)
    strategy["research"]["competitors"] = [
        {"game": game, "name": f"Fixture leader {game[-1].upper()}", "role": "teardown",
         "depth": "teardown", "fixture": True, "claim_refs": []} for game in TEARDOWNS]
    result = seeds.design_for(family_id, strategy=design_tests.rehash(strategy),
                              author=AUTHOR_UNREPORTED if unreported_persistence else AUTHOR)
    return (result.artifacts[0].content if result.artifacts else None), result

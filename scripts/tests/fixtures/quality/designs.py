"""Release-tier designs for the quality-consistency suite, made by the design module itself.

The genre seed author (scripts/wgf_design/seed.py) designs one game per genre family, sized
for the MVP tier: the built-in authors never write release-tier content. A release-tier
design is an agent author's work, and this suite runs no agent. `ReleaseSeedAuthor` stands
in for one: it takes the family's seed and lays the content out the way a release carries it
- groups of four units, each group introducing two elements, mixing older ones back in, and
closing on a climax with its own art; three structure kinds and a climax arena; four
objective kinds and a scored secondary goal; difficulty that rises within a group, dips at
the start of the next, and rises on every escalating axis at the climax.

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

AUTHOR = "release-seed-fixture"
AUTHOR_SEED_PERSISTENCE = "release-seed-persistence-fixture"
UNITS_PER_GROUP = 4
# Per slot of a group: what the unit is for, how it is built and what it asks for.
SLOT_PURPOSE = ("teach", "test", "twist", "climax")
SLOT_STRUCTURE = ("static-field", "moving-field", "path-with-turns", "climax-arena")
SLOT_OBJECTIVE = ("clear-the-field", "survive-the-timer", "reach-the-exit", "beat-the-finale")


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


def release_units(family_id, entry, strategy, mechanics, profile, run_seconds, kind, models):
    """The release's units: seed_units' own construction over a release-length arc."""
    block = (entry.get("seed") or {}).get("units") or {}
    groups = group_count(entry)
    purposes = _purposes(groups)
    total = len(purposes)
    mvp_count = int((entry.get("units") or {}).get("min_mvp") or 1) + 1
    # The MVP never ends on a breather: its dip would have no unit to recover in.
    while mvp_count < total and purposes[mvp_count - 1] == "breather":
        mvp_count += 1
    axis_profile = block.get("axis_profile") or {}
    readings = seeding._difficulty(entry, axis_profile, purposes, profile)
    durations = seeding._durations(purposes, mvp_count, run_seconds, profile, strategy)
    chunks = seeding._introductions(block.get("introduce_order"), list(mechanics), purposes,
                                    mvp_count)
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
        introduces = list(chunks.get(index) or []) if index < mvp_count else []
        taught += [m for m in introduces if m not in taught]
        asks = list(taught) if taught else list(mechanics[:1])
        duration = durations[index]
        elapsed += duration
        reading = readings[index]
        values = {"unit": unit_id, "s": duration}
        for name, scale in scales.items():
            values[name] = min(scale["max"], scale["start"] + scale["step"] * index)
        hardness = int(round(100.0 * sum(reading.values()) / max(1, len(reading))))
        mark = (f" (unit {number} of {total}, difficulty {hardness}%, {duration} s, "
                f"{elapsed} s in)")
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
        units.append(unit)
    return units, groups


class ReleaseSeedAuthor(seeding.GenreSeedAuthor):
    """The family's seed, its content laid out for the release tier (see the module doc)."""

    name = AUTHOR
    measurable_persistence = True

    def synthesize(self, family_id, models, strategy, entry):
        resolved = super().synthesize(family_id, models, strategy, entry)
        a = copy.deepcopy(resolved.archetype)
        profile_name = seeding._profile_name(strategy)
        profile = dict((models.get("session_profiles") or {}).get(profile_name)
                       or (models.get("session_profiles") or {}).get("standard") or {})
        mechanics = [m["id"] for m in a.get("mechanics") or [] if m.get("tier") == "mvp"]
        kind = a["content"]["unit_kind"]
        units, groups = release_units(family_id, entry, strategy, mechanics, profile,
                                      a.get("run_seconds") or 60, kind, models)
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
        a["content_units"] = len(units)
        depth = copy.deepcopy(resolved.depth)
        if self.measurable_persistence:
            # What a release keeps across a reload must be something the probe reports:
            # playability measures a persisted HUD metric or a best score
            # (wgf_playability.analysis.persisted_metrics), never a progression step's id.
            persists = (depth.get("meta") or {}).get("persists") or []
            if not any(p.get("kind") == "best-score" and p.get("tier") == "mvp"
                       for p in persists):
                anchor = next((p.get("delivered_by") for p in persists
                               if p.get("tier") == "mvp" and p.get("delivered_by")), None)
                persists.append({"kind": "best-score", "what": "The best result on each unit",
                                 "tier": "mvp", "delivered_by": anchor})
        return Resolved(resolved.archetype_id, a, resolved.experience, depth,
                        resolved.why, resolved.applied)


class SeedPersistenceAuthor(ReleaseSeedAuthor):
    """The same release-tier content, with the seed's own meta loop: what it keeps across a
    reload is named by a progression step, which no probe metric reports."""

    name = AUTHOR_SEED_PERSISTENCE
    measurable_persistence = False


register_author(AUTHOR, ReleaseSeedAuthor)
register_author(AUTHOR_SEED_PERSISTENCE, SeedPersistenceAuthor)


def design(family_id, measurable_persistence=True):
    """(the game-design the real design step writes for family `family_id` at the release
    tier, the step result)."""
    import test_design_seed as seeds
    result = seeds.design_for(family_id, author=AUTHOR if measurable_persistence
                              else AUTHOR_SEED_PERSISTENCE)
    return (result.artifacts[0].content if result.artifacts else None), result

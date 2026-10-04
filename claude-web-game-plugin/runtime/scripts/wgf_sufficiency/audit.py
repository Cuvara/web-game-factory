"""Measuring the content of a BUILT game against the bars of its quality tier.

`audit(design, strategy, data, records)` holds three things to each other:

  * the design's commitments - its content units at the run's quality tier, their elements,
    groups, structures, objective kinds, climax art and durations (game-design 1.12.0);
  * the build's content data file (`public/content/units.json`, the copy the playability
    step kept of the commit it played) - which units the build ships and how each is laid out;
  * what the play probe reported while the playability bot played the build - the units it
    traversed in order and the units its survey entered directly through the probe's unit
    link, with the entity kinds and assets drawn in each, the difficulty in force and how long
    the oracle took (records `traverse` and `survey`, bot.spec.ts).

It counts, on the build, every `content` and `progression` quantity of
core/reference/quality-benchmark.yaml at the design's tier (the larger of it and the genre
family's bar, core/reference/genre-models.yaml), and how each is measured comes from
core/reference/content-sufficiency.yaml. No bar is written here, and nothing branches on a
family or a game.

Every quantity is measured twice, on two views of the same units: the BUILD (the data file and
what the probe showed) and the DESIGN (what it declares). A check fails on the build; its
route says who must act. When the design's own declaration is short of the same bar, the
design must grow (route `design-gap`); otherwise the build is short of a design that meets the
bar (route `develop`).

A check is SKIPPED only when nothing it measures is claimed: no content contract (except at
the release tier, where that is itself a failure), generated content where a unit list would
be counted, or a tier that states no bar for it. A skip is never a pass.
"""

import hashlib
import json
import os
import re

from wgflib import genre_models, paths
from wgflib.yamllite import load_file

from wgf_design.content import quality_tier

__all__ = ["RULES_PATH", "BENCHMARK_PATH", "load_rules", "load_benchmark", "owed_units",
           "built_unlocks",
           "observations", "layout_of", "similarity", "audit", "CHECK_ORDER"]

RULES_PATH = os.path.join(paths.REFERENCE, "content-sufficiency.yaml")
BENCHMARK_PATH = os.path.join(paths.REFERENCE, "quality-benchmark.yaml")

CHECK_ORDER = ("content.contract", "content.data_present", "content.units_shipped",
               "content.units_reachable", "content.entity_kinds", "content.elements",
               "content.combinations", "content.structure", "content.groups",
               "content.difficulty", "content.objectives", "content.climax",
               "content.progression", "content.playtime", "content.drift")

_WORD = re.compile(r"[a-z]+")
_STOP = {"the", "a", "an", "and", "or", "to", "of", "in", "on", "you", "your", "all", "every",
         "each", "with", "before", "without", "at", "by", "for", "its", "it", "is", "as"}


def load_rules(path=None):
    """core/reference/content-sufficiency.yaml."""
    return load_file(path or RULES_PATH)


def load_benchmark(path=None):
    """core/reference/quality-benchmark.yaml."""
    return load_file(path or BENCHMARK_PATH)


def _number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _ids(items, most=6):
    items = [str(i) for i in items]
    return ", ".join(items[:most]) + (f" and {len(items) - most} more" if len(items) > most
                                      else "")


# -- what the design commits to -------------------------------------------------------------

def owed_units(design, tier):
    """The design's content units the build owes at `tier`, in play order: at `release` every
    unit that is not `optional`; otherwise the MVP units (all listed units when none is
    tiered). The order is `build_spec.progression.unit_sequence`, then `index`."""
    spec = (design or {}).get("build_spec") or {}
    content = spec.get("content") if isinstance(spec.get("content"), dict) else {}
    listed = [u for u in content.get("units") or [] if isinstance(u, dict)]
    if tier == "release":
        units = [u for u in listed if u.get("tier") != "optional"]
    else:
        units = [u for u in listed if u.get("tier") == "mvp"] or listed
    sequence = list(((spec.get("progression") or {}).get("unit_sequence")) or [])

    def place(unit):
        uid = unit.get("id")
        index = unit.get("index") if isinstance(unit.get("index"), int) else 10 ** 6
        return (sequence.index(uid) if uid in sequence else len(sequence), index, str(uid))
    return sorted(units, key=place)


# -- what the probe showed ------------------------------------------------------------------

def _snapshots(records):
    """Every probe snapshot with entities a record kept (first session samples, act)."""
    out = []
    for record in records.values():
        first = record.get("first-session") or {}
        out += [s for s in first.get("samples") or [] if isinstance(s, dict)]
        for acted in (record.get("act") or {}).get("acted") or []:
            if isinstance(acted, dict):
                out += [s for s in (acted.get("before"), acted.get("after")) if isinstance(s, dict)]
    return out


def observations(records, rules):
    """What the probe showed of each unit, over every viewport's records:

    {unit id: {entered, via, kinds, content_kinds, assets, difficulty, won, duration_ms}},
    plus the kinds the player and the interface are drawn as, how many entities of a content
    role carried no kind, and whether a survey ran (and entered anything)."""
    probe = rules.get("probe") or {}
    kind_roles = set(probe.get("kind_roles") or [])
    not_content = set(probe.get("not_content_roles") or [])
    units, player_kinds = {}, set()
    unkinded = seen = 0
    survey = {"ran": False, "entered": 0, "asked": 0, "reason": None}

    def unit(uid):
        return units.setdefault(uid, {"entered": False, "via": set(), "kinds": set(),
                                      "content_kinds": set(), "assets": set(),
                                      "difficulty": {}, "won": False, "duration_ms": None})

    for snapshot in _snapshots(records):
        for entity in snapshot.get("entities") or []:
            if not isinstance(entity, dict):
                continue
            if entity.get("role") in not_content and entity.get("kind"):
                player_kinds.add(str(entity["kind"]))
            if entity.get("role") in kind_roles:
                seen += 1
                if not entity.get("kind"):
                    unkinded += 1
    for record in records.values():
        for visit in (record.get("survey") or {}).get("visits") or []:
            if not isinstance(visit, dict):
                continue
            for role, kinds in (visit.get("kinds_by_role") or {}).items():
                if role in not_content:
                    player_kinds.update(str(k) for k in kinds or [])
    for record in records.values():
        traverse = record.get("traverse") or {}
        for played in traverse.get("per_unit") or []:
            if not isinstance(played, dict) or not played.get("unit_id"):
                continue
            entry = unit(played["unit_id"])
            entry["entered"] = True
            entry["via"].add("traverse")
            entry["kinds"].update(str(k) for k in played.get("kinds") or [])
            entry["difficulty"].update({k: v for k, v in (played.get("difficulty") or {}).items()
                                        if _number(v) is not None})
            if played.get("won"):
                entry["won"] = True
        survey_record = record.get("survey") or {}
        if survey_record.get("applies"):
            survey["ran"] = True
        elif survey_record and not survey["reason"]:
            survey["reason"] = survey_record.get("reason")
        for visit in survey_record.get("visits") or []:
            if not isinstance(visit, dict) or not visit.get("asked"):
                continue
            survey["asked"] += 1
            entry = unit(visit["asked"])
            seen += int(visit.get("content_entities") or 0)
            unkinded += int(visit.get("unkinded") or 0)
            if not visit.get("entered"):
                continue
            survey["entered"] += 1
            entry["entered"] = True
            entry["via"].add("survey")
            for role, kinds in (visit.get("kinds_by_role") or {}).items():
                entry["kinds"].update(str(k) for k in kinds or [])
            for role, assets in (visit.get("assets_by_role") or {}).items():
                if role not in not_content:
                    entry["assets"].update(str(a) for a in assets or [])
            entry["difficulty"].update({k: v for k, v in (visit.get("difficulty") or {}).items()
                                        if _number(v) is not None})
            if visit.get("won"):
                entry["won"] = True
                took = _number(visit.get("duration_ms"))
                if took is not None and (entry["duration_ms"] is None
                                         or took < entry["duration_ms"]):
                    entry["duration_ms"] = took
    for entry in units.values():
        entry["content_kinds"] = entry["kinds"] - player_kinds
    return {"units": units, "player_kinds": player_kinds, "unkinded": unkinded,
            "kind_role_entities": seen, "survey": survey}


# -- layouts --------------------------------------------------------------------------------

def layout_of(unit, rules):
    """The unit's layout: its content data beyond the descriptive keys, as {path: value} of
    its leaves (array positions kept: a grid's row 3 is not its row 4; a number outside any
    list counts only where it sits, so two units that differ only in a tuning number have
    one layout)."""
    skip = set((rules.get("layout") or {}).get("descriptive_keys") or [])
    leaves = {}

    def walk(path, value):
        if isinstance(value, dict):
            for key in sorted(value):
                walk(f"{path}.{key}" if path else str(key), value[key])
        elif isinstance(value, list):
            for position, item in enumerate(value):
                walk(f"{path}[{position}]", item)
        elif _number(value) is not None and "[" not in path:
            # A tuning number (a speed, a count) is the same layout at another difficulty:
            # only where it sits counts. A number inside a list - a cell, a position - is the
            # layout itself.
            leaves[path] = "#number"
        else:
            leaves[path] = json.dumps(value, sort_keys=True)
    for key in sorted(unit or {}):
        if key not in skip:
            walk(str(key), unit[key])
    return leaves


def similarity(first, second):
    """Jaccard similarity of two layouts' (path, value) leaves; two empty layouts are 1.0."""
    a, b = set(first.items()), set(second.items())
    if not a and not b:
        return 1.0
    return len(a & b) / float(len(a | b))


def _signature(leaves):
    return hashlib.sha256(json.dumps(sorted(leaves.items())).encode("utf-8")).hexdigest()[:16]


# -- one view of the units: the build's, or the design's -------------------------------------

def _objective_kind(unit):
    if unit.get("objective_kind"):
        return str(unit["objective_kind"])
    words = [w for w in _WORD.findall(str(unit.get("objective") or "").lower()) if w not in _STOP]
    return " ".join(words[:4]) or "-"


def _view_unit(design_unit, built=None, seen=None, rules=None):
    """One unit as a view sees it. The design view has only the design unit; the build view
    reads the data file's unit first and the probe's observation of it."""
    if built is None:
        combo = set(map(str, design_unit.get("mechanics") or [])) | set(
            map(str, design_unit.get("elements") or []))
        source = design_unit.get("parameters") if isinstance(design_unit.get("parameters"),
                                                             dict) else {}
        layout = layout_of({"parameters": source}, rules) if source else {}
        difficulty = dict(design_unit.get("difficulty") or {})
        unit = design_unit
    else:
        combo = set(map(str, built.get("mechanics") or design_unit.get("mechanics") or []))
        if seen and seen.get("entered"):
            combo |= {f"kind:{k}" for k in seen["content_kinds"]}
        else:
            combo |= set(map(str, built.get("elements") or []))
        layout = layout_of(built, rules)
        difficulty = dict(design_unit.get("difficulty") or {})
        difficulty.update({k: v for k, v in (built.get("difficulty") or {}).items()
                           if _number(v) is not None})
        if seen:
            difficulty.update(seen["difficulty"])
        unit = dict(design_unit, **{k: v for k, v in built.items()
                                    if k in ("group", "structure", "objective_kind", "purpose",
                                             "art", "expected_duration_s", "objective")})
    return {"id": design_unit.get("id"), "group": unit.get("group"),
            "structure": unit.get("structure"), "objective_kind": _objective_kind(unit),
            "purpose": unit.get("purpose"), "art": [str(a) for a in unit.get("art") or []],
            "combo": frozenset(combo), "layout": layout,
            "difficulty": difficulty,
            "duration": _number(unit.get("expected_duration_s")) or 0,
            "assets": set(seen["assets"]) if seen else set(),
            "introduces": list(design_unit.get("introduces") or [])}


def _first_appearances(view):
    seen, out = set(), []
    for unit in view:
        new = sorted(unit["combo"] - seen)
        seen |= unit["combo"]
        out.append((unit, new))
    return out


def _repeated(view, threshold):
    """The units that repeat another: the same structure, combination and objective kind, and
    a layout at least `threshold` alike (or identical)."""
    out = set()
    for i, a in enumerate(view):
        for b in view[i + 1:]:
            same_layout = _signature(a["layout"]) == _signature(b["layout"])
            alike = (a["structure"] == b["structure"] and a["combo"] == b["combo"]
                     and a["objective_kind"] == b["objective_kind"]
                     and similarity(a["layout"], b["layout"]) >= threshold)
            if (same_layout and a["layout"]) or alike:
                out.update((a["id"], b["id"]))
    return [u["id"] for u in view if u["id"] in out]


# -- the bars -------------------------------------------------------------------------------

class Bars:
    """The bars a build of this design is held to at its tier: quality-benchmark's at the tier,
    and the genre family's where it states the same quantity (the larger applies)."""

    def __init__(self, design, tier, benchmark, models):
        self.tier = tier
        self.family = genre_models.for_design(design, models) or {}
        self.models = models or {}
        self.benchmark = benchmark or {}

    def get(self, section, key, block="content"):
        entry = ((self.benchmark.get(block) or {}).get(section) or {}).get(key)
        return _number(entry.get(self.tier)) if isinstance(entry, dict) and self.tier else None

    def progression(self, key):
        entry = (self.benchmark.get("progression") or {}).get(key)
        return _number(entry.get(self.tier)) if isinstance(entry, dict) and self.tier else None

    def units(self):
        """(the least units the build ships, where it comes from)."""
        units = self.family.get("units") or {}
        family = _number(units.get("min_total" if self.tier == "release" else "min_mvp"))
        bench = self.get("units", "min_total")
        candidates = [(v, w) for v, w in (
            (bench, "quality-benchmark content.units.min_total"),
            (family, "genre-models units." + ("min_total" if self.tier == "release"
                                              else "min_mvp"))) if v is not None]
        return max(candidates) if candidates else (None, None)

    def variety(self, key):
        local = self.family.get("variety") or {}
        return local.get(key) if key in local else (self.models.get("variety") or {}).get(key)

    def shape(self):
        return self.family.get("budget") or {}


# -- the checks -----------------------------------------------------------------------------

def _check(cid, status, summary, measured=None, expected=None, evidence=None, route=None):
    entry = {"id": cid, "status": status, "required": status != "WARNING", "summary": summary}
    if measured is not None:
        entry["measured"] = measured
    if expected is not None:
        entry["expected"] = expected
    if evidence:
        entry["evidence"] = list(evidence)
    if route:
        entry["route"] = route
    return entry


def _skip(cid, why):
    return _check(cid, "SKIPPED", why)


def _elements_problems(view, bars):
    problems = []
    floor = bars.get("elements", "min_distinct")
    used = {}
    for unit in view:
        for element in unit["combo"]:
            used.setdefault(element, []).append(unit)
    if floor is not None and len(used) < floor:
        problems.append(f"{len(used)} distinct element(s) across {len(view)} units; the bar is "
                        f"{floor:g} (quality-benchmark content.elements.min_distinct)")
    reuse = bars.get("elements", "min_units_per_element")
    if reuse is not None:
        # An element only climax units use is that climax's own set piece, not a gimmick.
        once = sorted(e for e, units in used.items() if len(units) < reuse
                      and not all(u["purpose"] == "climax" for u in units))
        if once:
            problems.append(f"used in fewer than {reuse:g} units: {_ids(once)} "
                            f"(content.elements.min_units_per_element)")
    points = [(position, unit) for position, (unit, new) in
              enumerate(_first_appearances(view), 1) if new]
    want = bars.get("elements", "min_introduction_points")
    if want is not None and len(points) < want:
        problems.append(f"new elements arrive at {len(points)} point(s); the bar is {want:g} "
                        f"(content.elements.min_introduction_points)")
    late = bars.get("elements", "last_introduction_min_position")
    if late is not None and points and view:
        last = points[-1][0] / float(len(view))
        if last < late - 1e-9:
            problems.append(f"the last new element arrives in {points[-1][1]['id']} ({last:.0%} "
                            f"of the way); the bar is {late:.0%} "
                            f"(content.elements.last_introduction_min_position)")
    return problems, {"distinct": len(used), "introduction_points": len(points)}


def _combinations_problems(view, bars):
    ratio = bars.get("combinations", "min_distinct_ratio")
    counts = {}
    for unit in view:
        counts[unit["combo"]] = counts.get(unit["combo"], 0) + 1
    unique = sum(1 for unit in view if counts[unit["combo"]] == 1)
    share = round(unique / float(len(view)), 3) if view else 0.0
    problems = []
    if ratio is not None and share < ratio - 1e-9:
        problems.append(f"{unique} of {len(view)} units ({share:.0%}) combine elements no other "
                        f"unit combines; the bar is {ratio:.0%} "
                        f"(content.combinations.min_distinct_ratio)")
    return problems, {"distinct_ratio": share}


def _structure_problems(view, bars, threshold):
    kinds = sorted({str(u["structure"]) for u in view if u["structure"]})
    problems = []
    floor = bars.get("structure", "min_structure_kinds")
    if floor is not None and len(kinds) < floor:
        problems.append(f"{len(kinds)} structure kind(s) ({_ids(kinds) or 'none stated'}); the "
                        f"bar is {floor:g} (content.structure.min_structure_kinds)")
    repeated = _repeated(view, threshold)
    share = round(len(repeated) / float(len(view)), 3) if view else 0.0
    most = bars.get("structure", "max_repeated_layout_ratio")
    if most is not None and share > most + 1e-9:
        problems.append(f"{len(repeated)} of {len(view)} units ({share:.0%}) are near-identical "
                        f"to another - the same structure, elements and objective kind, and a "
                        f"layout at least {threshold:.0%} alike ({_ids(repeated)}); the bar is "
                        f"at most {most:.0%} (content.structure.max_repeated_layout_ratio)")
    return problems, {"structure_kinds": kinds, "repeated": repeated, "repeated_ratio": share}


def _groups_problems(view, bars):
    group_kind = bars.shape().get("group_kind")
    order, members = [], {}
    for unit in view:
        if unit["group"] and unit["group"] not in members:
            order.append(unit["group"])
        if unit["group"]:
            members.setdefault(unit["group"], []).append(unit)
    problems = []
    unnamed = [u["id"] for u in view if not u["group"]]
    if unnamed:
        problems.append(f"{_ids(unnamed)} belong to no {group_kind}")
    count = bars.get("units", "min_groups")
    if count is not None and len(order) < count:
        problems.append(f"{len(order)} {group_kind}(s); the bar is {count:g} "
                        f"(content.units.min_groups)")
    per = bars.get("units", "min_units_per_group")
    thin = [f"{g} ({len(members[g])})" for g in order if per is not None and len(members[g]) < per]
    if thin:
        problems.append(f"{group_kind}(s) with fewer than {per:g} units: {', '.join(thin)} "
                        f"(content.units.min_units_per_group)")
    seen, idle = set(), []
    for group in order:
        here = set().union(*(u["combo"] for u in members[group]))
        if seen and not (here - seen):
            idle.append(group)
        seen |= here
    if idle:
        problems.append(f"the {group_kind}(s) {', '.join(idle)} bring no element the player has "
                        f"not met: the same elements as before, with only cosmetic change")
    return problems, {"groups": {g: len(members[g]) for g in order}, "idle": idle}


def _difficulty_problems(view, bars):
    problems = []
    rising = []
    if view:
        first, last = view[0]["difficulty"], view[-1]["difficulty"]
        for axis in sorted(set(first) & set(last)):
            if _number(first[axis]) is not None and _number(last[axis]) is not None \
                    and last[axis] > first[axis]:
                rising.append(axis)
    want = bars.get("difficulty", "min_escalating_axes")
    if want is not None and len(rising) < want:
        problems.append(f"difficulty escalates on {len(rising)} axis/axes ({_ids(rising) or 'none'})"
                        f"; the bar is {want:g} (content.difficulty.min_escalating_axes)")
    most = _number(bars.variety("max_consecutive_scaling_only_units"))
    run, longest, flat = 0, 0, []
    for previous, unit in zip(view, view[1:]):
        scaling = (unit["combo"] == previous["combo"] and unit["structure"] == previous["structure"]
                   and unit["objective_kind"] == previous["objective_kind"])
        run = run + 1 if scaling else 0
        longest = max(longest, run)
        if most is not None and run == most + 1:
            flat.append(unit["id"])
    if flat and most is not None:
        problems.append(f"{_ids(flat)} end runs of more than {most:g} units that change only "
                        f"their numbers - the same elements, structure and objective kind as the "
                        f"unit before: a harder unit asks for a new skill, not a bigger number "
                        f"(genre-models variety.max_consecutive_scaling_only_units)")
    every = bars.get("difficulty", "relief_every_units")
    if every is not None:
        run = 0
        for previous, unit in zip(view, view[1:]):
            raised = [a for a, v in unit["difficulty"].items() if _number(v) is not None
                      and _number(previous["difficulty"].get(a)) is not None
                      and v > previous["difficulty"][a]]
            run = 0 if (unit["purpose"] == "breather" or not raised) else run + 1
            if run == int(every) + 1:
                problems.append(f"{unit['id']} is unit {run} in a row that raises an axis; relief "
                                f"comes every {every:g} units (content.difficulty."
                                f"relief_every_units)")
    return problems, {"escalating_axes": rising, "longest_scaling_run": longest}


def _objectives_problems(view, bars, secondary):
    primary = [u["objective_kind"] for u in view]
    kinds = len(set(primary)) + len(secondary)
    problems = []
    want = bars.get("objectives", "min_kinds")
    if want is not None and kinds < want:
        problems.append(f"{len(set(primary))} objective kind(s) and {len(secondary)} secondary "
                        f"goal(s); the bar is {want:g} (content.objectives.min_kinds)")
    most = bars.get("objectives", "max_identical_ratio")
    share = 0.0
    if primary:
        common = max(sorted(set(primary)), key=primary.count)
        share = round(primary.count(common) / float(len(primary)), 3)
        if most is not None and share > most + 1e-9:
            problems.append(f"{primary.count(common)} of {len(primary)} units ({share:.0%}) ask "
                            f"for {common!r}; the bar is at most {most:.0%} "
                            f"(content.objectives.max_identical_ratio)")
    return problems, {"kinds": kinds, "identical_ratio": share}


def _climax_problems(view, bars, built):
    milestone = bars.shape().get("milestone")
    per = bars.get("difficulty", "min_climax_per_group")
    distinct = (((bars.benchmark.get("presentation") or {}).get("assets") or {})
                .get("distinct_climax_art") or {})
    distinct = isinstance(distinct, dict) and distinct.get(bars.tier) is True
    climax = [u for u in view if u["purpose"] == "climax"]
    problems = []
    if milestone and per is not None:
        groups = []
        for unit in view:
            if unit["group"] and unit["group"] not in groups:
                groups.append(unit["group"])
        unclosed = [g for g in groups
                    if sum(1 for u in climax if u["group"] == g) < per]
        if unclosed:
            problems.append(f"the group(s) {', '.join(unclosed)} close with no climax unit "
                            f"({milestone}; content.difficulty.min_climax_per_group {per:g})")
    if distinct and len(climax) > 1:
        bare = [u["id"] for u in climax if not u["art"]]
        if bare:
            problems.append(f"climax unit(s) {_ids(bare)} name no art of their own "
                            f"(presentation.assets.distinct_climax_art)")
        owners = {}
        for unit in climax:
            for art in unit["art"]:
                owners.setdefault(art, []).append(unit["id"])
        shared = {a: ids for a, ids in owners.items() if len(ids) > 1}
        if shared:
            problems.append("climax units share art: " + "; ".join(
                f"{a} draws {', '.join(ids)}" for a, ids in sorted(shared.items()))
                + " (presentation.assets.distinct_climax_art)")
        if built:
            drawn = [u for u in climax if u["assets"]]
            same = [(a["id"], b["id"]) for i, a in enumerate(drawn) for b in drawn[i + 1:]
                    if a["assets"] == b["assets"]]
            if same:
                problems.append("the build draws climax units with the same assets: " + "; ".join(
                    f"{a} and {b}" for a, b in same[:4])
                    + " (presentation.assets.distinct_climax_art)")
    return problems, {"climax_units": [u["id"] for u in climax]}


def _playtime_problems(view, bars):
    total = round(sum(u["duration"] for u in view), 1)
    floor = bars.get("units", "min_total_designed_s")
    problems = []
    if floor is not None and total < floor - 1e-9:
        problems.append(f"{total:g} s of designed play across {len(view)} units; the bar is "
                        f"{floor:g} s (content.units.min_total_designed_s)")
    return problems, {"designed_s": total}


# -- the audit ------------------------------------------------------------------------------

def audit(design, strategy, data, records, rules=None, benchmark=None, models=None,
          data_problem=None):
    """{tier, mode, checks, findings, metrics} for one build.

    `data` is the build's content data file (or None, with `data_problem` saying why), and
    `records` the playability bot's records per viewport ({project: {test: record}})."""
    rules = load_rules() if rules is None else rules
    benchmark = load_benchmark() if benchmark is None else benchmark
    models = genre_models.load() if models is None else models
    tier, tier_where = quality_tier(design, strategy)
    spec = (design or {}).get("build_spec") or {}
    content = spec.get("content") if isinstance(spec.get("content"), dict) else None
    mode = ((content or {}).get("generation") or {}).get("mode") if content else None
    bars = Bars(design, tier, benchmark, models)
    seen = observations(records or {}, rules)
    checks = []
    add = checks.append
    out = {"tier": tier, "tier_where": tier_where, "mode": mode, "checks": checks,
           "metrics": {}}

    if content is None:
        if tier == "release":
            add(_check("content.contract", "FAIL",
                       "the design states no content units (build_spec.content), so nothing "
                       "about a release-tier build's content can be counted", route="design-gap"))
        else:
            add(_skip("content.contract", "the design states no content units "
                                          "(build_spec.content): nothing to count"))
        for cid in CHECK_ORDER[1:]:
            add(_skip(cid, "the design states no content units"))
        return _finish(out, rules)
    add(_check("content.contract", "PASS", f"the design states its content ({mode or 'no mode'}"
                                           f", tier {tier or 'none'}: {tier_where})"))

    # Entity kinds: the probe names what is on screen, or no element can be counted on it.
    kinds_ok = seen["unkinded"] == 0 and (seen["kind_role_entities"] > 0 or any(
        u["kinds"] for u in seen["units"].values()))
    kinds_status = "PASS" if kinds_ok else ("FAIL" if mode == "authored" else "WARNING")
    add(_check("content.entity_kinds", kinds_status,
               (f"every content entity the probe reported carries its kind "
                f"({seen['kind_role_entities']} seen)") if kinds_ok else
               (f"{seen['unkinded']} of {seen['kind_role_entities']} entities of a content role "
                f"({', '.join((rules.get('probe') or {}).get('kind_roles') or [])}) carry no "
                f"`kind`: the build does not say which element is on screen, so element "
                f"variety cannot be counted on it (play-probe entities[].kind)"),
               measured={"unkinded": seen["unkinded"],
                         "entities": seen["kind_role_entities"]},
               expected="entities[].kind on every entity of a content role"))

    if mode != "authored":
        for cid in CHECK_ORDER[1:]:
            if cid != "content.entity_kinds":
                add(_skip(cid, f"content is {mode or 'not authored'}: the units listed are "
                               f"representative, so no unit list is counted on the build"))
        return _finish(out, rules, order=True)

    owed = owed_units(design, tier)
    built_units = {}
    if data is None:
        add(_check("content.data_present", "FAIL",
                   f"the build ships no content data: {data_problem or 'absent'}",
                   expected="public/content/units.json with every unit the design owes",
                   route="develop"))
    else:
        built_units = {u.get("id"): u for u in data.get("units") or [] if isinstance(u, dict)}
        add(_check("content.data_present", "PASS",
                   f"the build ships {len(built_units)} unit(s) in its content data"))
    shipped = [u for u in owed if u.get("id") in built_units]
    missing = [u.get("id") for u in owed if u.get("id") not in built_units]

    # Units shipped: every unit the design owes, and at least the tier's count.
    floor, where = bars.units()
    problems, design_problems = [], []
    if missing:
        problems.append(f"the build ships {len(shipped)} of the {len(owed)} units the design "
                        f"owes at tier {tier or 'mvp'}; missing: {_ids(missing)}")
    if floor is not None and len(shipped) < floor:
        problems.append(f"{len(shipped)} unit(s) shipped; the bar is {floor:g} ({where})")
    if floor is not None and len(owed) < floor:
        design_problems.append(f"the design owes {len(owed)} unit(s); the bar is {floor:g} "
                               f"({where})")
    add(_judged("content.units_shipped", problems, design_problems,
                f"the build ships all {len(owed)} unit(s) the design owes",
                measured={"owed": len(owed), "shipped": len(shipped), "missing": missing},
                expected=f">= {floor:g} units ({where}), every design unit present"
                if floor is not None else "every design unit present"))

    # Reachable: every shipped unit was entered while the bot played or surveyed.
    unreached = [u.get("id") for u in shipped
                 if not (seen["units"].get(u.get("id")) or {}).get("entered")]
    survey = seen["survey"]
    why = ("" if not unreached else
           f"; the survey entered none of the {survey['asked']} unit(s) it asked for through "
           f"the probe's unit link (?wgf-unit=<id>), so the build does not honour it"
           if survey["ran"] and not survey["entered"] else
           f"; no survey ran ({survey['reason'] or 'the playability records carry none'}), so "
           f"only the units the traverse played in order were seen" if not survey["ran"] else "")
    add(_check("content.units_reachable", "FAIL" if unreached else "PASS",
               (f"{len(unreached)} of {len(shipped)} shipped unit(s) were never entered: "
                f"{_ids(unreached)}{why}") if unreached else
               f"all {len(shipped)} shipped unit(s) were entered "
               f"({sum(1 for u in shipped if 'traverse' in seen['units'][u.get('id')]['via'])} in "
               f"play order, the rest through the survey)",
               measured={"unreached": unreached, "survey": survey},
               expected="every shipped unit reported by the probe while played or surveyed",
               route="develop" if unreached else None))

    threshold = _number((rules.get("layout") or {}).get("near_identical_similarity")) or 1.0
    build_view = [_view_unit(u, built_units[u.get("id")], seen["units"].get(u.get("id")), rules)
                  for u in shipped]
    design_view = [_view_unit(u, rules=rules) for u in owed]
    secondary = sorted({str(g.get("kind")) for g in (content.get("secondary_goals") or [])
                        if isinstance(g, dict) and g.get("kind")})
    families = (("content.elements", lambda v, b: _elements_problems(v, bars),
                 (("elements", "min_distinct"), ("elements", "min_introduction_points"))),
                ("content.combinations", lambda v, b: _combinations_problems(v, bars),
                 (("combinations", "min_distinct_ratio"),)),
                ("content.structure", lambda v, b: _structure_problems(v, bars, threshold),
                 (("structure", "min_structure_kinds"),
                  ("structure", "max_repeated_layout_ratio"))),
                ("content.groups", lambda v, b: _groups_problems(v, bars),
                 (("units", "min_groups"), ("units", "min_units_per_group"))),
                ("content.difficulty", lambda v, b: _difficulty_problems(v, bars),
                 (("difficulty", "min_escalating_axes"), ("difficulty", "relief_every_units"))),
                ("content.objectives", lambda v, b: _objectives_problems(v, bars, secondary),
                 (("objectives", "min_kinds"), ("objectives", "max_identical_ratio"))),
                ("content.climax", lambda v, b: _climax_problems(v, bars, b),
                 (("difficulty", "min_climax_per_group"),)),
                ("content.playtime", lambda v, b: _playtime_problems(v, bars),
                 (("units", "min_total_designed_s"),)))
    for cid, measure, keys in families:
        if all(bars.get(section, key) is None for section, key in keys):
            add(_skip(cid, f"tier {tier or 'none'} ({tier_where}) states no "
                           + " or ".join(f"content.{s}.{k}" for s, k in keys) + " bar"))
            continue
        if cid == "content.groups" and not bars.shape().get("group_kind"):
            add(_skip(cid, "the genre family has no group above the unit "
                           "(genre-models budget.group_kind)"))
            continue
        problems, measured = measure(build_view, True)
        design_problems, declared = measure(design_view, False)
        out["metrics"][cid] = {"build": _plain(measured), "design": _plain(declared)}
        stated = {f"content.{s}.{k}": bars.get(s, k) for s, k in keys
                  if bars.get(s, k) is not None}
        add(_judged(cid, problems, design_problems,
                    f"the build meets the tier's {cid.split('.', 1)[1]} bars",
                    measured={"build": _plain(measured), "design": _plain(declared)},
                    expected=stated))

    # Progression: gated unlocks between groups, counted on the BUILT content - the gates
    # the build's data file states to content it ships - never on the design's steps.
    want = bars.progression("min_gated_unlocks")
    if want is None:
        add(_skip("content.progression", f"tier {tier or 'none'} states no "
                                         f"progression.min_gated_unlocks bar"))
    else:
        owed_tiers = ("mvp", "post-mvp") if tier == "release" else ("mvp",)
        declared = [s for s in (spec.get("progression") or {}).get("steps") or []
                    if isinstance(s, dict) and s.get("tier") in owed_tiers]
        gates, void = built_unlocks(data, shipped, built_units)
        problems = []
        if len(gates) < want:
            problems.append(
                (f"the build gates {len(gates)} unlock(s) of the content it ships; the bar is "
                 f"{want:g} (progression.min_gated_unlocks)")
                + ("" if gates or void else
                   ": its content data states none (public/content/units.json `unlocks`, or a "
                   "unit's `unlock`), so the units are a flat list")
                + (f"; {len(void)} stated unlock(s) open nothing the build ships or say not "
                   f"what opens them: {_ids(void)}" if void else ""))
        design_problems = ([f"the design states {len(declared)} progression step(s) at the tier"]
                           if len(declared) < want else [])
        add(_judged("content.progression", problems, design_problems,
                    f"the build gates {len(gates)} unlock(s): {_ids(gates)}",
                    measured={"build": len(gates), "gates": gates, "void": void,
                              "design": len(declared)},
                    expected=f">= {want:g} gated unlocks in the build's content data"))

    # Drift: every design commitment of a shipped unit is the build's.
    drift = []
    for unit in shipped:
        built = built_units[unit.get("id")]
        for field in ("index", "objective"):
            if field in built and built.get(field) != unit.get(field):
                drift.append(f"{unit.get('id')}.{field}: design {unit.get(field)!r}, build "
                             f"{built.get(field)!r}")
        lacking = sorted(set(map(str, unit.get("mechanics") or []))
                         - set(map(str, built.get("mechanics") or [])))
        if lacking:
            drift.append(f"{unit.get('id')}.mechanics: the build lacks {', '.join(lacking)}")
        for field in ("group", "structure", "objective_kind", "purpose"):
            if field in built and unit.get(field) is not None and built.get(field) != unit.get(field):
                drift.append(f"{unit.get('id')}.{field}: design {unit.get(field)!r}, build "
                             f"{built.get(field)!r}")
        for field in ("elements", "art"):
            if field in built:
                gone = sorted(set(map(str, unit.get(field) or []))
                              - set(map(str, built.get(field) or [])))
                if gone:
                    drift.append(f"{unit.get('id')}.{field}: the build lacks {', '.join(gone)}")
    add(_check("content.drift", "FAIL" if drift else "PASS",
               ("the build departs from the design: " + "; ".join(drift[:6])
                + (f" and {len(drift) - 6} more" if len(drift) > 6 else "")) if drift else
               "every shipped unit carries the design's commitments",
               measured={"drift": drift[:40]}, route="develop" if drift else None))
    return _finish(out, rules, order=True)


def built_unlocks(data, shipped, built_units):
    """([gate], [void]): the gated unlocks the build's content data states - `unlocks`
    entries ({opens, after | condition}) and units carrying `unlock` - that open a unit the
    build ships or a group one of them belongs to, behind a stated condition. An entry that
    opens nothing shipped, or states no condition, is void: a gate to no content is not
    progression."""
    units = {u.get("id") for u in shipped if u.get("id")}
    groups = {b.get("group") or u.get("group") for u in shipped
              for b in [built_units.get(u.get("id")) or {}]} - {None}
    gates, void = [], []
    for n, entry in enumerate((data or {}).get("unlocks") or [], 1):
        if not isinstance(entry, dict):
            void.append(f"unlocks[{n}]")
            continue
        opens = entry.get("opens")
        label = str(entry.get("id") or opens or f"unlocks[{n}]")
        if isinstance(opens, str) and (opens in units or opens in groups)                 and (entry.get("after") or entry.get("condition")):
            gates.append(label)
        else:
            void.append(label)
    for unit_id, unit in built_units.items():
        if unit.get("unlock") and unit_id in units:
            gates.append(str(unit_id))
    return gates, void


def _plain(value):
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, (set, frozenset, tuple)):
        return sorted(_plain(v) for v in value)
    if isinstance(value, float):
        return round(value, 4)
    return value


def _judged(cid, problems, design_problems, ok, measured=None, expected=None):
    """A by-design check: FAIL on the build's problems, routed `design-gap` when the design is
    short of the same bar and `develop` otherwise."""
    if not problems:
        return _check(cid, "PASS", ok, measured=measured, expected=expected)
    route = "design-gap" if design_problems else "develop"
    summary = "; ".join(problems[:4])
    if design_problems:
        summary += " - and the design itself is short: " + "; ".join(design_problems[:3])
    return _check(cid, "FAIL", summary, measured=measured, expected=expected, route=route,
                  evidence=design_problems[:6] or None)


def _finish(out, rules, order=False):
    if order:
        position = {cid: i for i, cid in enumerate(CHECK_ORDER)}
        out["checks"].sort(key=lambda c: position.get(c["id"], len(position)))
    table = rules.get("checks") or {}
    findings = []
    for check in out["checks"]:
        if check["status"] not in ("FAIL", "WARNING"):
            continue
        meta = table.get(check["id"]) or {}
        route = check.get("route") or (meta.get("route") if meta.get("route") in
                                       ("develop", "design-gap") else "develop")
        check["route"] = route
        finding = {
            "id": f"content-sufficiency:{check['id']}",
            "check": check["id"],
            "dimension": meta.get("dimension") or "content",
            "severity": (meta.get("severity") or "major") if check["status"] == "FAIL"
            else "minor",
            "summary": check["summary"],
            "observed": check.get("measured"),
            "bar": check.get("expected"),
            "owner": "game-design" if route == "design-gap" else (meta.get("owner")
                                                                  or "level-design"),
            "route": route,
            "evidence": list(check.get("evidence") or []),
        }
        if route == "design-gap":
            finding["design_gap"] = {
                "field": meta.get("design_field") or "build_spec.content",
                "question": (f"The built content falls short of its tier's bar "
                             f"({check['id']}): {check['summary']}. What does the design add "
                             f"so its units meet it?"),
                "assumed": None,
                "severity": "blocking"}
        findings.append(finding)
    out["findings"] = findings
    return out

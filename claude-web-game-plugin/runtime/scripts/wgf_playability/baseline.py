"""The baseline comparison: a candidate build held to the build a person accepted.

A run that adopts an existing game (factory.init.adopt_existing) starts from a build someone
already shipped and accepted - by default the commit the adopted checkout ships, or the one a
person names in factory.init.accepted_baseline; the design records it as
`existing_content.source.commit`. Every other gate judges a build against bars and against the
design. None of them compared a build with the accepted one, and the 2026-10-05 loops made
their gates pass while making both accepted games worse (K6 retro H1, H4, H6, H7): the 3D
courses cut from 234-440 m to 38-124 m corridors, the first course cleared by holding forward
in 5.8 s against a 24 s par; the 2D paddle, capsules, opener and speed curve changed.

The playability step plays the accepted commit with the same bot and the same settings as the
candidate (step.py), and this module compares the two recordings, quantity by quantity, unit
by unit, against core/reference/baseline-compare.yaml:

    play_settings(settings, accepted_ids, realism_rules, sufficiency)
                              the bot's settings for both plays: the accepted units surveyed
                              and sampled by naive play, every unit and policy played as often
                              as a clear rate is compared
    profile(records, content, source, frames_dir, rules, env_bars)
                              what one build measured: per unit (declared, reached, extent, par,
                              geometry, elements, drawn kinds, difficulty, naive clears, the
                              oracle's clear time), its tuning, the start, each action's
                              acknowledgement, the frame rate and the drawn size of each role
    compare(accepted, candidate, rules, realism_rules, changes, strength)
                              the `baseline.*` checks
    accepted_changes(config)  a person's recorded reasons for changing accepted content
                              (factory.init.accepted_changes)

and two advisory measurements (1.1.0; check-tiers `advisory`, never required, not in `IDS`):

    source_rewrite(git, accepted, candidate, rules, content_path)
                              baseline.source_rewrite: the share of accepted units replaced, of
                              accepted files rewritten and of accepted lines deleted between
                              the two commits, read from git (GitReader, measure_rewrite)
    frame_metrics(accepted, candidate, rules)
                              baseline.frame_metrics: each compared frame's mean luminance and
                              contrast against the accepted build's (frame_profile)

Every quantity is measured the same way on both builds, from what the bot recorded or the
content data file each commit ships; a quantity one of them does not report is unmeasured,
never a pass. A change to accepted content is a failure unless a person recorded why
(`accepted_changes`); then it is listed as an accepted change, never hidden. Nothing here names
a game, an engine or a family.
"""

import copy
import json
import math
import os
import statistics

from wgflib import paths
from wgflib.yamllite import load_file

from wgf_design import layouts

from .analysis import _check, _attempts, changed_fraction
from .realism import Strength, layout_length, _is_path

__all__ = ["RULES_PATH", "RULES_REF", "IDS", "load_rules", "accepted_of", "play_settings",
           "profile", "compare", "accepted_changes", "NO_BASELINE", "ACCEPTED_NONE",
           "ACCEPTED_UNMEASURED", "UNDETERMINED",
           "UNREPORTED", "DEGRADED", "NOT_PLAYED", "UNIT_SCOPED", "strength_for", "identical",
           "degraded_records", "ADVISORY_IDS", "GitReader", "RewriteError",
           "measure_rewrite", "source_rewrite", "frame_profile", "frame_metrics"]

RULES_PATH = os.path.join(paths.REFERENCE, "baseline-compare.yaml")
RULES_REF = "core/reference/baseline-compare.yaml"
# The checks, in report order.
IDS = ("baseline.units_kept", "baseline.unit_content", "baseline.unit_extent",
       "baseline.tuning", "baseline.difficulty_order", "baseline.unit_kinds",
       "baseline.clear_time", "baseline.clear_rate", "baseline.entity_size",
       "baseline.responsiveness")
# The checks compared unit by unit, on the accepted units the candidate still ships.
UNIT_BY_UNIT = ("baseline.unit_content", "baseline.unit_extent", "baseline.difficulty_order",
                "baseline.unit_kinds")
# The checks whose items name a unit: a person's recorded change of one names the unit (or
# `*` with the quantity it changes on every unit, e.g. total.extent) - never the whole check.
UNIT_SCOPED = ("baseline.units_kept",) + UNIT_BY_UNIT + ("baseline.clear_time",
                                                         "baseline.clear_rate")
# `measured.unmeasured` values.
NO_BASELINE = "no-accepted-baseline"        # the run adopted nothing: nothing to compare with
ACCEPTED_NONE = "accepted-declares-none"    # the accepted build carries none of this quantity
ACCEPTED_UNMEASURED = "accepted-unmeasured"  # the accepted build does not report it (its probe
                                            # or data predates the contract): nothing to hold
                                            # the candidate to - reported, not held
UNDETERMINED = "undetermined"               # measured on both, and the measurements cannot
                                            # decide (two lower bounds)
UNREPORTED = "not-reported"                 # one build does not report what the check reads
DEGRADED = "environment-degraded"           # every attempt of a recording read was degraded
NOT_PLAYED = "accepted-not-played"          # the accepted commit could not be built or played
_TIMING = {"baseline.clear_time": ("naive", "survey"), "baseline.clear_rate": ("naive",),
           "baseline.responsiveness": ("first-session", "win", "act")}


def load_rules(path=None):
    return load_file(path or RULES_PATH)


def strength_for(rules, tier, held=None):
    """A measured regression holds the build at every tier `enforce.fail_required_at` names
    (`all`: every tier, and a run that states none)."""
    enforced = ((rules or {}).get("enforce") or {}).get("fail_required_at")
    required = enforced == "all" or (isinstance(enforced, list) and tier in enforced)
    return Strength(tier, required, held)


def _number(value):
    return (float(value) if isinstance(value, (int, float)) and not isinstance(value, bool)
            else None)


def _beyond(delta, tolerance):
    """Whether a difference is beyond a tolerance, read at the precision the values are
    stated in: 0.87 - 0.82 is 0.050000000000000044 in floating point, and a move of exactly
    the tolerance is within it."""
    return round(delta, 9) > tolerance


# -- which build was accepted ------------------------------------------------------------------

def accepted_of(design):
    """{commit, by, unit_ids} of the accepted build the run holds candidates to: the commit
    the design's existing-content floor was counted at (`existing_content.source.commit`) -
    the adopted checkout's shipped commit, or the one factory.init.accepted_baseline names -
    and the unit ids the floor recorded. None when the run adopted nothing."""
    floor = (design or {}).get("existing_content")
    if not isinstance(floor, dict):
        return None
    source = floor.get("source") or {}
    commit = str(source.get("commit") or "")
    if not commit:
        return None
    return {"commit": commit,
            "by": source.get("baseline") or "the adopted checkout's shipped commit",
            "unit_ids": [str(u) for u in floor.get("unit_ids") or []],
            "floor_method": source.get("method")}


def identical(a, b):
    a, b = str(a or ""), str(b or "")
    return bool(a and b) and (a.startswith(b) or b.startswith(a))


def accepted_changes(config):
    """(changes, invalid): a person's recorded reasons for changing accepted content, from
    factory.init.accepted_changes - entries {check, unit?, quantity?, reason, decided_by}. An
    entry without a check, a reason or who decided is invalid and waives nothing; so is one of
    a unit-scoped check (UNIT_SCOPED) that names no unit, or names `*` without the quantity it
    changes on every unit - a check named alone would waive every accepted unit of it."""
    section = {}
    if config is not None:
        section = (config.section("init") if hasattr(config, "section")
                   else (config.get("init") if isinstance(config, dict) else None)) or {}
    out, invalid = [], []
    for entry in section.get("accepted_changes") or []:
        if (isinstance(entry, dict) and str(entry.get("check") or "").startswith("baseline.")
                and str(entry.get("reason") or "").strip()
                and str(entry.get("decided_by") or "").strip()
                and (str(entry["check"]) not in UNIT_SCOPED
                     or (str(entry.get("unit") or "").strip() not in ("", "*"))
                     or (str(entry.get("unit") or "").strip() == "*"
                         and str(entry.get("quantity") or "").strip() not in ("", "*")))):
            out.append({"check": str(entry["check"]), "unit": str(entry.get("unit") or "*"),
                        "quantity": str(entry.get("quantity") or "*"),
                        "reason": str(entry["reason"]).strip(),
                        "decided_by": str(entry["decided_by"]).strip()})
        else:
            invalid.append(entry)
    return out, invalid


def _waived(changes, check, unit, quantity):
    for change in changes or []:
        if (change["check"] == check and change["unit"] in ("*", str(unit))
                and change["quantity"] in ("*", str(quantity))):
            return change
    return None


# -- the bot's settings for both plays -----------------------------------------------------------

def _spread(ids, count):
    """`count` - 1 ids beside the first, spread evenly to the last (the naive sample)."""
    if len(ids) < 2 or count < 2:
        return []
    picks = []
    for position in range(1, count):
        index = round(position * (len(ids) - 1) / (count - 1))
        if index > 0 and ids[index] not in picks:
            picks.append(ids[index])
    return picks


def play_settings(settings, accepted_ids, realism_rules, sufficiency):
    """The settings both builds are played with (a copy of `settings`): every accepted unit is
    surveyed through the unit link (the content contract's survey window and viewports), naive
    play samples the accepted units - the middle and last beside the opening, as
    play-realism.yaml `naive.units` asks - and every naive unit and policy is played
    `clear_rate.runs` times, so clear rates can be compared."""
    out = copy.deepcopy(settings)
    ids = [str(u) for u in accepted_ids or [] if u]
    survey = (sufficiency or {}).get("survey") or {}
    listed = list(out.get("survey_units") or [])
    if ids:
        out["survey_units"] = listed + [u for u in ids if u not in listed]
        out["survey_projects"] = list(out.get("survey_projects") or survey.get("projects") or [])
        out["survey_unit_ms"] = int(out.get("survey_unit_ms") or (survey.get("unit_s") or 0) * 1000)
        out["survey_ms"] = int(out.get("survey_ms") or (survey.get("total_s") or 0) * 1000)
        naive = (realism_rules or {}).get("naive") or {}
        out["naive_units"] = _spread(ids, int(naive.get("units") or 1))
    runs = int(((realism_rules or {}).get("clear_rate") or {}).get("runs") or 1)
    out["naive_repeats"] = max(int(out.get("naive_repeats") or 1), runs)
    return out


# -- one build's measurements ---------------------------------------------------------------------

def _flatten(node, prefix=""):
    out = {}
    if isinstance(node, dict):
        for key in sorted(node, key=str):
            out.update(_flatten(node[key], f"{prefix}.{key}" if prefix else str(key)))
    elif isinstance(node, list):
        out[prefix] = json.dumps(node, sort_keys=True)
    else:
        out[prefix] = node
    return out


def _scalars(node, prefix=""):
    """Every value of a layout outside a list, by dotted key."""
    out = {}
    if isinstance(node, dict):
        for key in sorted(node, key=str):
            value = node[key]
            name = f"{prefix}.{key}" if prefix else str(key)
            if isinstance(value, dict):
                out.update(_scalars(value, name))
            elif not isinstance(value, list):
                out[name] = value
    return out


def _cells(layout, empty):
    """Solid cells of every list of strings in a layout (a grid's rows): every character that
    is not one of `empty`. None when the layout holds no such list."""
    found, total = False, 0
    stack = [layout]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            stack.extend(node.values())
        elif isinstance(node, list):
            if node and all(isinstance(r, str) for r in node):
                found = True
                total += sum(1 for row in node for ch in row if ch not in empty)
            else:
                stack.extend(node)
    return total if found else None


def _extent(layout, rules):
    """{value, unit, kind}: a path layout's centre-line length, else a grid's solid cells."""
    ext = rules.get("extent") or {}
    if _is_path(layout):
        return {"value": round(layout_length(layout), 2), "unit": "length", "kind": "path"}
    cells = _cells(layout, set(ext.get("grid_empty") or []))
    if cells is not None:
        return {"value": cells, "unit": "cells", "kind": "grid"}
    return None


def _par(unit, layout, rules):
    for key in (rules.get("par_keys") or []):
        for holder in (layout, unit, (unit or {}).get("parameters")):
            value = _number((holder or {}).get(key)) if isinstance(holder, dict) else None
            if value and value > 0:
                return value
    return None


def _health_bad(record, env_bars):
    """True when every attempt of `record` was degraded (its last one is), so a timing read off
    it measures the host, not the build."""
    if not isinstance(record, dict) or not env_bars:
        return False
    attempts = _attempts(record, env_bars)
    return bool(attempts) and bool(attempts[-1]["degraded"])


def degraded_records(records, env_bars):
    """["project:test", ...] of every recording in {project: {test: record}} whose attempts
    were all degraded: a play that measured its host there, to be made again, never kept."""
    return sorted(f"{project}:{name}" for project, found in (records or {}).items()
                  for name, record in (found or {}).items() if _health_bad(record, env_bars))


def _median(values):
    values = [v for v in values if v is not None]
    return round(statistics.median(values), 2) if values else None


def profile(records, content, source=None, frames_dir=None, rules=None, env_bars=None,
            unit_key="layout", ack=None, kind_roles=None, not_content_roles=None):
    """What one build measured, read from one viewport's bot records ({test: record}) and the
    content data file the commit ships (`content`, with its layout source `source`)."""
    rules = rules or load_rules()
    content = content if isinstance(content, dict) else None
    units, order = {}, []

    def unit(uid):
        uid = str(uid)
        if uid not in units:
            units[uid] = {"declared": False, "reached": False}
        return units[uid]

    data_units = [u for u in (content or {}).get("units") or [] if isinstance(u, dict)
                  and u.get("id")]
    for index, u in enumerate(sorted(data_units, key=lambda u: (
            u.get("index") if isinstance(u.get("index"), (int, float)) else 10 ** 6))):
        uid = str(u["id"])
        entry = unit(uid)
        order.append(uid)
        layout = u.get(unit_key)
        if source and isinstance(source.get(uid), dict):
            layout = source[uid] if not isinstance(layout, dict) else {**layout, **source[uid]}
        entry.update(declared=True, index=index)
        extent = _extent(layout, rules) if layout is not None else None
        if extent:
            entry["extent"] = extent
        par = _par(u, layout, rules)
        if par:
            entry["par_s"] = par
        geometry = layouts.geometry(u, {"layout": {"unit_key": unit_key}},
                                    (source or {}).get(uid))
        if geometry:
            entry["geometry"] = [list(s) for s in geometry]
        # The unit's own tuning: every value of its layout outside a list (a width, a descent
        # interval, a par), by dotted key - geometry sequences are compared on their own.
        scalars = {k: v for k, v in (_scalars(layout) if isinstance(layout, dict) else {}).items()
                   if k.split(".")[-1] not in (rules.get("par_keys") or [])}  # par: unit_extent's
        if scalars:
            entry["layout_values"] = scalars
        if isinstance(u.get("elements"), list):
            entry["elements"] = sorted({str(e) for e in u["elements"]})
        if isinstance(u.get("difficulty"), dict):
            entry["difficulty"] = {str(k): v for k, v in u["difficulty"].items()
                                   if _number(v) is not None}

    survey = records.get("survey") or {}
    not_content = set(not_content_roles or [])
    for visit in survey.get("visits") or []:
        if not isinstance(visit, dict) or not visit.get("asked"):
            continue
        entry = unit(visit["asked"])
        # Asked for through the unit link: whether it could be entered is measured.
        entry["asked"] = True
        if not visit.get("entered"):
            continue
        entry["reached"] = entry["entered"] = True
        kinds = sorted({str(k) for role, found in (visit.get("kinds_by_role") or {}).items()
                        if role not in not_content for k in found or []})
        drawn, unkinded = visit.get("content_entities") or 0, visit.get("unkinded") or 0
        if not (drawn and unkinded >= drawn):
            # A probe that names no kind of anything it draws reports no kinds: unmeasured,
            # never an empty set another build's kinds would be "added" to.
            entry["kinds"] = kinds
        if visit.get("difficulty") and "difficulty" not in entry:
            entry["probe_difficulty"] = {str(k): v for k, v in visit["difficulty"].items()
                                         if _number(v) is not None}
        if visit.get("won") and _number(visit.get("duration_ms")) is not None:
            entry["oracle_s"] = round(visit["duration_ms"] / 1000.0, 2)
        elif not visit.get("lost"):
            entry["oracle_lower_s"] = round((survey.get("unit_ms") or 0) / 1000.0, 2) or None
    for played in (records.get("traverse") or {}).get("per_unit") or []:
        if isinstance(played, dict) and played.get("unit_id"):
            unit(played["unit_id"])["reached"] = True

    naive = records.get("naive") or {}
    opening = {"unit": None, "policies": {}}
    for run in naive.get("runs") or []:
        if not isinstance(run, dict):
            continue
        entered = run.get("entered") if run.get("entered") is not None else bool(
            run.get("unit_id")) and (run.get("played_ms") or 0) > 0
        if not entered:
            continue
        asked = run.get("asked")
        target = opening if asked in (None, "") else None
        if target is None:
            if str(run.get("unit_id")) != str(asked):
                continue
            entry = unit(asked)
            entry["reached"] = True
            target = entry.setdefault("naive_runs", {"policies": {}})
        else:
            opening["unit"] = opening["unit"] or run.get("unit_id")
        cell = target["policies"].setdefault(str(run.get("policy")), {
            "won": 0, "n": 0, "fastest_s": None, "uncleared_s": []})
        cell["n"] += 1
        if run.get("won") and _number(run.get("clear_ms")) is not None:
            cell["won"] += 1
            seconds = round(run["clear_ms"] / 1000.0, 2)
            if cell["fastest_s"] is None or seconds < cell["fastest_s"]:
                cell["fastest_s"] = seconds
        else:
            cell["uncleared_s"].append(round((run.get("played_ms") or 0) / 1000.0, 2))
        if _number(run.get("par_s")):
            target["par_s"] = run["par_s"]
    for holder in [opening] + [u.get("naive_runs") for u in units.values() if u.get("naive_runs")]:
        for cell in holder["policies"].values():
            cell["uncleared_min_s"] = min(cell.pop("uncleared_s")) if cell.get("uncleared_s") \
                else cell.pop("uncleared_s", None) or None
    if opening["unit"] and str(opening["unit"]) in units:
        units[str(opening["unit"])]["reached"] = True

    first = records.get("first-session") or {}
    playing, observer = first.get("playingMs"), first.get("observerMs") or 0
    # Timed from the page's first byte: the wait for it is the local server's and the
    # browser's, never the game's boot (measured: 2301 ms of 2801 on one candidate's start).
    first_health = (first.get("health") if isinstance(first.get("health"), dict) else
                    ((first.get("attempts") or [{}])[-1] or {}).get("health")) or {}
    ttfb = _number((first_health.get("nav") or {}).get("ttfb_ms")) or 0
    responsiveness = {"start_ms": (round(playing - observer - ttfb)
                                   if _number(playing) is not None else None)}
    acknowledged = {}
    act = records.get("act") or {}
    bars = ack or {}
    for entry in act.get("acted") or []:
        if not isinstance(entry, dict) or not entry.get("action"):
            continue
        name = str(entry["action"])
        fraction = None
        if frames_dir:
            try:
                fraction = changed_fraction(os.path.join(frames_dir, f"act-{name}-before.png"),
                                            os.path.join(frames_dir, f"act-{name}-after.png"),
                                            bars.get("min_pixel_delta", 24))
            except Exception:  # an unreadable frame measures nothing  # noqa: BLE001
                fraction = None
        if fraction is not None:
            acknowledged[name] = max(acknowledged.get(name, 0.0), round(fraction, 4))
    responsiveness["acknowledged"] = acknowledged or None
    win = records.get("win") or {}
    health = (win.get("health") if isinstance(win.get("health"), dict) else
              ((win.get("attempts") or [{}])[-1] or {}).get("health"))
    frames = (health or {}).get("frames") or {}
    worker = (health or {}).get("worker") or {}
    if _number(frames.get("count")) and _number(worker.get("elapsed_ms")):
        responsiveness["fps"] = round(frames["count"] / (worker["elapsed_ms"] / 1000.0), 1)
        responsiveness["frame_gap_max_ms"] = frames.get("gap_max_ms")

    sizes = {}
    sampled = (win.get("sampled") or {}).get("frames") or []
    for frame in sampled:
        for sample in frame or []:
            if isinstance(sample, list) and len(sample) >= 7 and sample[2]:
                w, h = _number(sample[5]), _number(sample[6])
                if w and h:
                    sizes.setdefault(str(sample[1]), []).append((w, h))
    roles = set(rules.get("entity_size", {}).get("roles") or [])
    entity_size = {role: [_median([w for w, _h in found]), _median([h for _w, h in found])]
                   for role, found in sorted(sizes.items()) if role in roles}

    degraded = {name: _health_bad(records.get(name), env_bars)
                for name in ("first-session", "act", "win", "naive", "survey")}
    return {"units": units, "order": order, "opening": opening,
            "content": content is not None,
            "tuning": _flatten((content or {}).get("tuning")) if isinstance(
                (content or {}).get("tuning"), dict) else None,
            "responsiveness": responsiveness, "entity_size": entity_size or None,
            "degraded": degraded, "survey_ran": bool(survey.get("applies")),
            "naive_ran": bool(naive.get("applies"))}


# -- the comparison ------------------------------------------------------------------------------

def _result(cid, project, strength, items, quantity_note, expected, unmeasured_why=None,
            accepted_none=False, degraded=False, waived=None, extra=None,
            accepted_unmeasured=None):
    """One check from its items. FAIL on any regression; BLOCKED when a recording it reads was
    degraded; PASS when something was compared and nothing regressed. Otherwise unmeasured -
    never a pass: not held when the accepted build has none of the quantity (`accepted_none`,
    NOT_APPLICABLE to the quality gate), does not report it (`accepted_unmeasured`: the
    accepted build cannot be measured on it - a WARNING the assessment reads as inconclusive),
    or both builds were measured and cannot decide it (two lower bounds); held as
    quality-policy.yaml skipped_checks says when it is the candidate that does not report it."""
    regressed = [i for i in items if i["verdict"] == "regressed"]
    decided = [i for i in items if i["verdict"] in ("kept", "regressed", "accepted-change")]
    measured = {"items": items[:120], "omitted": max(0, len(items) - 120),
                "regressed": len(regressed), "compared": len(decided)}
    if waived:
        measured["accepted_changes"] = waived
    if extra:
        measured.update(extra)
    if regressed:
        worst = regressed[0]
        return _check(cid, project, False,
                      f"QUALITY REGRESSION against the accepted build: {len(regressed)} "
                      f"{quantity_note} worse beyond tolerance - {worst['summary']}"
                      + (f" (and {len(regressed) - 1} more)" if len(regressed) > 1 else ""),
                      required=strength.fail_required, measured=measured, expected=expected)
    if degraded:
        # A recording either build made on a degraded host measured the host, not the build:
        # what it would have decided is unmeasured - never a pass, and never a regression
        # (an accepted play slowed by the host makes any candidate look faster).
        measured.update(unmeasured=DEGRADED, reason=f"every attempt of the {degraded} "
                        "recording of one of the builds was made on a degraded host")
        return _check(cid, project, False,
                      f"unmeasured: the {degraded} recording of one of the builds was made on a "
                      "degraded host - measured again on a quiet host, never passed",
                      required=True, measured=measured, expected=expected, blocked=True)
    unreported = [i for i in items if i["verdict"] == UNREPORTED]
    if unreported:
        # The accepted build reports something for an accepted unit, role or action that the
        # candidate no longer declares or measures: what was compared beside it never carries
        # the check to a pass (review of 43c4554, M1).
        why = strength.held(cid)
        measured.update(unmeasured=UNREPORTED, reason=unreported[0]["summary"],
                        not_reported=len(unreported))
        return _check(cid, project, False,
                      f"unmeasured on the candidate: {len(unreported)} quantity(ies) the "
                      f"accepted build reports are not reported - {unreported[0]['summary']}"
                      + (f" (and {len(unreported) - 1} more)" if len(unreported) > 1 else "")
                      + (f"; {len(decided)} compared, none worse" if decided else "")
                      + (f" - {why}" if why else ""),
                      required=bool(why), measured=measured, expected=expected)
    undetermined = [i for i in items if i["verdict"] == UNDETERMINED]
    if decided and undetermined:
        # Some of the comparison decided nothing: a WARNING naming it, never a pass.
        measured.update(unmeasured=UNDETERMINED, reason=unmeasured_why,
                        undetermined=len(undetermined))
        return _check(cid, project, False,
                      f"{len(decided)} {quantity_note} compared with the accepted build, none "
                      f"worse beyond tolerance; {len(undetermined)} undetermined - "
                      f"{undetermined[0]['summary']}", required=False, measured=measured,
                      expected=expected)
    if decided:
        return _check(cid, project, True,
                      f"{len(decided)} {quantity_note} compared with the accepted build: none "
                      "worse beyond tolerance"
                      + (f"; {len(waived)} changed with a person's recorded reason"
                         if waived else ""),
                      required=strength.fail_required, measured=measured, expected=expected)
    if accepted_none:
        measured.update(unmeasured=ACCEPTED_NONE, reason=unmeasured_why)
        return _check(cid, project, False, "unmeasured: " + unmeasured_why, required=False,
                      measured=measured, expected=expected)
    if accepted_unmeasured:
        measured.update(unmeasured=ACCEPTED_UNMEASURED, reason=accepted_unmeasured)
        return _check(cid, project, False,
                      "unmeasured on the accepted build: " + accepted_unmeasured
                      + " - nothing to hold the candidate to (name an accepted build that "
                      "reports it to compare)", required=False, measured=measured,
                      expected=expected)
    if any(i["verdict"] == "undetermined" for i in items):
        measured.update(unmeasured=UNDETERMINED, reason=unmeasured_why)
        return _check(cid, project, False,
                      f"undetermined: measured on both builds, and no measurement decides - "
                      f"{next(i['summary'] for i in items if i['verdict'] == 'undetermined')}",
                      required=False, measured=measured, expected=expected)
    why = strength.held(cid)
    measured.update(unmeasured=UNREPORTED, reason=unmeasured_why)
    return _check(cid, project, False,
                  "unmeasured: " + unmeasured_why + (f" - {why}" if why else ""),
                  required=bool(why), measured=measured, expected=expected)


def _item(verdict, summary, changes=None, check=None, unit=None, quantity=None, **values):
    item = {"verdict": verdict, "summary": summary}
    if unit is not None:
        item["unit"] = unit
    if quantity is not None:
        item["quantity"] = quantity
    item.update(values)
    if verdict in ("regressed", UNREPORTED) and changes is not None:
        change = _waived(changes, check, unit, quantity)
        if change:
            item["verdict"] = "accepted-change"
            item["reason"] = change["reason"]
            item["decided_by"] = change["decided_by"]
    return item


def _accepted_ids(accepted):
    units = accepted.get("units") or {}
    declared = [u for u in accepted.get("order") or [] if units.get(u, {}).get("declared")]
    if declared:
        return declared, "the accepted build's content data file"
    reached = [u for u, e in units.items() if e.get("reached")]
    return reached, "the units the play probe reached on the accepted build"


def compare(accepted, candidate, rules=None, realism_rules=None, changes=None, strength=None,
            project="desktop", difficulty_tolerance=None):
    """The baseline.* checks of `candidate` against `accepted` (two profile()s)."""
    rules = rules or load_rules()
    strength = strength or Strength(None, True, None)
    out = []
    ids, how = _accepted_ids(accepted)
    a_units, c_units = accepted.get("units") or {}, candidate.get("units") or {}

    def finish(cid, items, note, expected, why, **kw):
        waived = [{"unit": i.get("unit"), "quantity": i.get("quantity"), "reason": i["reason"],
                   "decided_by": i["decided_by"]} for i in items
                  if i["verdict"] == "accepted-change"]
        if cid in UNIT_BY_UNIT and ids and not kept_ids and not items:
            # Nothing accepted is left to compare unit by unit: units_kept fails for it.
            items = [_item("undetermined", f"none of the {len(ids)} accepted unit(s) is shipped "
                           "under its id (baseline.units_kept fails), so nothing is compared "
                           "unit by unit")]
            kw["accepted_none"] = False
            kw.pop("accepted_unmeasured", None)
        out.append(_result(cid, project, strength, items, note, expected, why,
                           waived=waived, **kw))

    kept_ids = [u for u in ids if (c_units.get(u) or {}).get("declared")
                or (c_units.get(u) or {}).get("reached")]

    def missing(uid, check, quantity, what, accepted_value=None, declared=True):
        """What the accepted build declares or reports for an accepted unit and the candidate
        does not: a regression when the candidate still declares the unit in its data and
        dropped it there (`declared`: the quantity is the data's), else not reported - held
        as an unmeasured check is, never left out of a pass."""
        if declared and (c_units.get(uid) or {}).get("declared"):
            return _item("regressed", f"{uid}: {what} no longer declared", changes, check,
                         uid, quantity, accepted=accepted_value, candidate=None)
        return _item(UNREPORTED, f"{uid}: {what} not reported by the candidate", changes,
                     check, uid, quantity, accepted=accepted_value, candidate=None)
    # units_kept: every accepted unit still shipped, under its own id.
    items = []
    for uid in ids:
        entry = c_units.get(uid) or {}
        kept = entry.get("declared") or entry.get("reached")
        summary = (f"{uid}: shipped" if kept else
                   f"{uid}: gone from the candidate (removed or renamed)")
        if (kept and entry.get("asked") and not entry.get("reached")
                and (a_units.get(uid) or {}).get("entered")):
            # Declared, and the survey asked for it and could not enter it - where it entered
            # it on the accepted build: shipped in the data, not in the game.
            kept = False
            summary = (f"{uid}: declared, but the survey could not enter it (it entered it on "
                       "the accepted build)")
        items.append(_item("kept" if kept else "regressed", summary, changes,
                           "baseline.units_kept", uid, "present"))
    finish("baseline.units_kept", items, "accepted unit(s)",
           "every accepted unit shipped under its own id",
           "the accepted build reports no unit - no content data file, and its play probe "
           "reached none - so which units it shipped cannot be read",
           accepted_unmeasured=None if ids else (
               "it ships no content data file and its play probe reported no content unit, so "
               "which units it shipped cannot be read"))

    content_rules = rules.get("unit_content") or {}
    min_similarity = float(content_rules.get("min_similarity", 1.0))
    items = []
    for uid in kept_ids:
        a, c = a_units.get(uid) or {}, c_units.get(uid) or {}
        if a.get("geometry") and not c.get("geometry"):
            items.append(missing(uid, "baseline.unit_content", "layout", "its layout"))
        if a.get("geometry") and c.get("geometry"):
            sim = round(layouts.similarity([tuple(s) for s in a["geometry"]],
                                           [tuple(s) for s in c["geometry"]]), 3)
            same = (sim >= min_similarity and
                    sorted(map(tuple, a["geometry"])) == sorted(map(tuple, c["geometry"]))
                    if min_similarity >= 1.0 else sim >= min_similarity)
            items.append(_item("kept" if same else "regressed",
                               f"{uid}: layout {'unchanged' if same else 'changed'} "
                               f"(similarity {sim})", changes, "baseline.unit_content", uid,
                               "layout", accepted=None, candidate=None, similarity=sim))
        if isinstance(a.get("layout_values"), dict) and not c.get("declared"):
            items.append(missing(uid, "baseline.unit_content", "layout.*",
                                 "its layout's own values", sorted(a["layout_values"])))
        elif isinstance(a.get("layout_values"), dict):
            # A key the candidate no longer declares (its block deleted, a code default in
            # its place) is a change like any other value.
            values = c.get("layout_values") if isinstance(c.get("layout_values"), dict) else {}
            for key, value in sorted(a["layout_values"].items()):
                now = values.get(key)
                av, cv = _number(value), _number(now)
                same = (av is not None and cv is not None and av == cv) or value == now
                if not same:
                    items.append(_item("regressed", f"{uid}: layout {key} {value} -> {now}",
                                       changes, "baseline.unit_content", uid, f"layout.{key}",
                                       accepted=value, candidate=now))
        if isinstance(a.get("elements"), list) and not isinstance(c.get("elements"), list):
            items.append(missing(uid, "baseline.unit_content", "elements", "its elements",
                                 a["elements"]))
        if isinstance(a.get("elements"), list) and isinstance(c.get("elements"), list):
            gone = sorted(set(a["elements"]) - set(c["elements"]))
            added = sorted(set(c["elements"]) - set(a["elements"]))
            changed = gone or added
            items.append(_item("regressed" if changed else "kept",
                               f"{uid}: elements " + ("unchanged" if not changed else
                                                      f"changed (gone {gone}, added {added})"),
                               changes, "baseline.unit_content", uid, "elements",
                               accepted=a["elements"], candidate=c["elements"]))
    finish("baseline.unit_content", items, "layout/element comparison(s)",
           f"each accepted unit's declared layout identical (similarity >= {min_similarity}) and "
           "its declared elements the same set, unless a person recorded why",
           "the accepted build declares no layout or elements for its units (no content data "
           "file, or none in it)", accepted_none=accepted.get("content") and not any(
               a_units.get(u, {}).get("geometry") or a_units.get(u, {}).get("elements")
               for u in ids),
           accepted_unmeasured=None if accepted.get("content") else
           "it ships no content data file, so its units' layouts and elements are not declared")

    ext_rules = rules.get("unit_extent") or {}
    min_ratio = float(ext_rules.get("min_ratio", 1.0))
    min_par = float(ext_rules.get("min_par_ratio", 1.0))
    items = []
    for uid in kept_ids:
        a, c = a_units.get(uid) or {}, c_units.get(uid) or {}
        ae, ce = a.get("extent"), c.get("extent")
        if ae and ae["value"] and not ce:
            items.append(missing(uid, "baseline.unit_extent", "extent", "its extent",
                                 ae["value"]))
        elif ae and ce and ae["unit"] != ce["unit"] and ae["value"]:
            items.append(_item("regressed", f"{uid}: extent measured in {ae['unit']} on the "
                               f"accepted build, in {ce['unit']} now (another layout kind)",
                               changes, "baseline.unit_extent", uid, "extent",
                               accepted=ae["value"], candidate=ce["value"]))
        if ae and ce and ae["unit"] == ce["unit"] and ae["value"]:
            ratio = round(ce["value"] / float(ae["value"]), 3)
            items.append(_item("regressed" if ratio < min_ratio else "kept",
                               f"{uid}: {ae['unit']} {ae['value']} -> {ce['value']} "
                               f"({ratio} x)", changes, "baseline.unit_extent", uid, "extent",
                               accepted=ae["value"], candidate=ce["value"], ratio=ratio,
                               measure=ae["unit"]))
        if a.get("par_s") and not c.get("par_s"):
            items.append(missing(uid, "baseline.unit_extent", "par_s", "its par", a["par_s"]))
        if a.get("par_s") and c.get("par_s"):
            ratio = round(c["par_s"] / float(a["par_s"]), 3)
            items.append(_item("regressed" if ratio < min_par else "kept",
                               f"{uid}: par {a['par_s']} s -> {c['par_s']} s ({ratio} x)",
                               changes, "baseline.unit_extent", uid, "par_s",
                               accepted=a["par_s"], candidate=c["par_s"], ratio=ratio))
    # The whole game's extent and par, whatever its units are called: a candidate that
    # renamed every unit and cut each of them is still measured (units_kept names the ids).
    for quantity, bar, read in (("extent", min_ratio,
                                 lambda e: (e.get("extent") or {}).get("value")),
                                ("par_s", min_par, lambda e: e.get("par_s"))):
        kinds = {(e.get("extent") or {}).get("unit") for e in list(a_units.values())
                 + list(c_units.values()) if e.get("declared") and e.get("extent")}
        if quantity == "extent" and len(kinds) != 1:
            continue
        # A unit whose change a person recorded is left out of both totals.
        waived = {i.get("unit") for i in items if i.get("quantity") == quantity
                  and i["verdict"] == "accepted-change"}
        a_total = sum(read(e) or 0 for u, e in a_units.items()
                      if e.get("declared") and u not in waived)
        c_total = sum(read(e) or 0 for u, e in c_units.items()
                      if e.get("declared") and u not in waived)
        if a_total and c_total:
            ratio = round(c_total / float(a_total), 3)
            items.append(_item("regressed" if ratio < bar else "kept",
                               f"all units: total {quantity} {round(a_total, 1)} -> "
                               f"{round(c_total, 1)} ({ratio} x)", changes,
                               "baseline.unit_extent", "*", f"total.{quantity}",
                               accepted=round(a_total, 2), candidate=round(c_total, 2),
                               ratio=ratio))
    finish("baseline.unit_extent", items, "unit size/par comparison(s)",
           f"each accepted unit's extent (path length, or solid cells of a grid) >= {min_ratio} x "
           f"and its par >= {min_par} x the accepted build's",
           "no accepted unit's extent or par is declared on both builds",
           accepted_none=accepted.get("content") and not any(
               a_units.get(u, {}).get("extent") or a_units.get(u, {}).get("par_s") for u in ids),
           accepted_unmeasured=None if accepted.get("content") else
           "it ships no content data file, so its units' extents and pars are not declared")

    tol = float((rules.get("tuning") or {}).get("max_relative_change", 0.0))
    items = []
    a_tuning, c_tuning = accepted.get("tuning"), candidate.get("tuning")
    if isinstance(a_tuning, dict) and isinstance(c_tuning, dict):
        for key, value in sorted(a_tuning.items()):
            if key not in c_tuning:
                items.append(_item("regressed", f"tuning {key} = {value} is gone", changes,
                                   "baseline.tuning", "*", key, accepted=value, candidate=None))
                continue
            now = c_tuning[key]
            av, cv = _number(value), _number(now)
            if av is not None and cv is not None:
                moved = abs(cv - av) > tol * max(abs(av), 1e-9)
            else:
                moved = value != now
            items.append(_item("regressed" if moved else "kept",
                               f"tuning {key}: {value} -> {now}", changes, "baseline.tuning",
                               "*", key, accepted=value, candidate=now))
    finish("baseline.tuning", items, "accepted tuning value(s)",
           f"every accepted tuning value kept (relative change <= {tol})",
           "the accepted build ships no content data file to read tuning from"
           if not accepted.get("content") else
           ("the candidate ships no tuning block" if isinstance(a_tuning, dict) else
            "the accepted build declares no tuning"),
           accepted_none=accepted.get("content") and not isinstance(a_tuning, dict),
           accepted_unmeasured=None if accepted.get("content") else
           "it ships no content data file, so its tuning is not declared")

    tol_d = float(difficulty_tolerance if difficulty_tolerance is not None else
                  (rules.get("difficulty_order") or {}).get("tolerance", 0.0))
    items = []

    def difficulty(entry):
        return entry.get("difficulty") or entry.get("probe_difficulty") or {}

    axes = sorted({k for u in kept_ids for k in difficulty(a_units.get(u) or {})})
    for axis in axes:
        both = [u for u in kept_ids if _number(difficulty(a_units[u]).get(axis)) is not None
                and _number(difficulty(c_units.get(u) or {}).get(axis)) is not None]
        for uid in kept_ids:
            av = _number(difficulty(a_units[uid]).get(axis))
            if av is not None and uid not in both:
                # The data's own value dropped where the unit is still declared: a change.
                items.append(missing(uid, "baseline.difficulty_order", axis,
                                     f"difficulty.{axis}", av, declared=axis in (
                                         a_units[uid].get("difficulty") or {})))
        for uid in both:
            av = float(difficulty(a_units[uid])[axis])
            cv = float(difficulty(c_units[uid])[axis])
            if _beyond(abs(cv - av), tol_d):
                items.append(_item("regressed", f"{uid}: difficulty.{axis} {av} -> {cv}",
                                   changes, "baseline.difficulty_order", uid, axis,
                                   accepted=av, candidate=cv))
        inverted = []
        for i, first in enumerate(both):
            for second in both[i + 1:]:
                a1, a2 = (float(difficulty(a_units[u])[axis]) for u in (first, second))
                c1, c2 = (float(difficulty(c_units[u])[axis]) for u in (first, second))
                if ((_beyond(a2 - a1, tol_d) and _beyond(c1 - c2, tol_d))
                        or (_beyond(a1 - a2, tol_d) and _beyond(c2 - c1, tol_d))):
                    inverted.append([first, second])
        items.append(_item("regressed" if inverted else "kept",
                           f"difficulty.{axis}: {len(inverted)} pair(s) of accepted units now in "
                           f"the opposite order" + (f" ({inverted[0][0]} / {inverted[0][1]})"
                                                    if inverted else ""),
                           changes, "baseline.difficulty_order", "*", f"{axis}.order",
                           pairs=len(both) * (len(both) - 1) // 2, inverted=inverted[:12]))
    finish("baseline.difficulty_order", items, "difficulty comparison(s)",
           f"each accepted unit's difficulty within {tol_d} of the accepted value on every axis, "
           "and no pair of accepted units in the opposite order",
           "no accepted unit reports a difficulty value on both builds (the content data or the "
           "probe's metrics.difficulty)",
           accepted_unmeasured=None if any(difficulty(a_units.get(u) or {}) for u in ids)
           else "neither its content data nor its probe states a difficulty for any unit")

    items = []
    for uid in kept_ids:
        a, c = a_units.get(uid) or {}, c_units.get(uid) or {}
        if isinstance(a.get("kinds"), list) and not isinstance(c.get("kinds"), list):
            items.append(missing(uid, "baseline.unit_kinds", "kinds", "its drawn kinds",
                                 a["kinds"], declared=False))
        if isinstance(a.get("kinds"), list) and isinstance(c.get("kinds"), list):
            gone = sorted(set(a["kinds"]) - set(c["kinds"]))
            added = sorted(set(c["kinds"]) - set(a["kinds"]))
            items.append(_item("regressed" if gone or added else "kept",
                               f"{uid}: drawn kinds " + ("unchanged" if not (gone or added) else
                                                         f"changed (gone {gone}, added {added})"),
                               changes, "baseline.unit_kinds", uid, "kinds",
                               accepted=a["kinds"], candidate=c["kinds"]))
    finish("baseline.unit_kinds", items, "unit(s) whose drawn kinds were",
           "each accepted unit draws the same content kinds (the probe's entities[].kind, "
           "surveyed through the unit link)",
           "no accepted unit was surveyed on both builds (the probe's unit link and entity kinds)",
           accepted_unmeasured=None if any(isinstance(a_units.get(u, {}).get("kinds"), list)
                                           for u in ids) else
           "its probe entered no unit through the unit link with entity kinds named")

    out.append(_clear_time(accepted, candidate, kept_ids, rules, changes, strength, project))
    out.append(_clear_rate(accepted, candidate, kept_ids, realism_rules or {}, changes,
                           strength, project))

    size = rules.get("entity_size") or {}
    max_change = float(size.get("max_change", 0.0))
    items = []
    a_size, c_size = accepted.get("entity_size") or {}, candidate.get("entity_size") or {}
    if _degraded(accepted, candidate, "win"):
        a_size = {}
    for role in sorted(a_size):
        if None in a_size[role]:
            continue
        if role not in c_size or None in c_size[role]:
            # A readable role the accepted build drew that the candidate no longer reports
            # (renamed, or not sampled): never left out of a pass.
            items.append(_item(UNREPORTED, f"{role}: drawn {a_size[role]} px on the accepted "
                               "build, not sampled on the candidate", changes,
                               "baseline.entity_size", "*", role, accepted=a_size[role],
                               candidate=None))
            continue
        ratios = [round(c / float(a), 3) for a, c in zip(a_size[role], c_size[role]) if a]
        moved = any(abs(r - 1.0) > max_change for r in ratios)
        items.append(_item("regressed" if moved else "kept",
                           f"{role}: drawn {a_size[role]} -> {c_size[role]} px ({ratios} x)",
                           changes, "baseline.entity_size", "*", role,
                           accepted=a_size[role], candidate=c_size[role], ratio=ratios))
    finish("baseline.entity_size", items, "role size(s)",
           f"the median drawn size of each role within {max_change} of the accepted build's, on "
           "each axis",
           "no role's drawn size was sampled on both builds (the win test's per-frame entities)",
           degraded=_degraded(accepted, candidate, "win"),
           accepted_unmeasured=None if accepted.get("entity_size") else
           "its win test sampled no readable role's drawn size")

    out.append(_responsiveness(accepted, candidate, rules, changes, strength, project))
    return out


def _played(profile):
    """Whether naive play or the survey timed any unit on a build."""
    holders = [profile.get("opening") or {}] + [u.get("naive_runs") or {} for u in
                                                (profile.get("units") or {}).values()]
    if any(cell.get("n") for h in holders for cell in (h.get("policies") or {}).values()):
        return True
    return any(u.get("oracle_s") is not None or u.get("oracle_lower_s")
               for u in (profile.get("units") or {}).values())


def _degraded(accepted, candidate, *names):
    """The names among `names` whose recording was degraded on either build, joined; empty
    when none was."""
    return ", ".join(n for n in names if any((p.get("degraded") or {}).get(n)
                                             for p in (accepted, candidate)))


def _shrink(a_fast, a_lower, c_fast, c_lower, bar):
    """(verdict, ratio, note) of a clear time against the accepted one, lower bounds kept:
    regressed only when the candidate's clear is shorter than `bar` x the accepted build's
    whatever the unknown part of a lower bound is."""
    if c_fast is not None and a_fast is not None:
        ratio = round(c_fast / a_fast, 3) if a_fast else None
        return ("regressed" if ratio is not None and ratio < bar else "kept"), ratio, "both cleared"
    if c_fast is not None and a_lower:
        ratio = round(c_fast / a_lower, 3)
        # The accepted build was not cleared in a_lower s: its clear is later still, so the
        # true ratio is at most this.
        return ("regressed" if ratio < bar else "undetermined"), ratio, \
            "the accepted build not cleared: ratio at most"
    if c_fast is None and c_lower and a_fast:
        ratio = round(c_lower / a_fast, 3)
        return ("kept" if ratio >= bar else "undetermined"), ratio, \
            "the candidate not cleared: ratio at least"
    if c_fast is None and a_fast is None and c_lower and a_lower:
        return "undetermined", None, "neither build cleared it"
    return "unmeasured", None, "not played on both builds"


def _clear_time(accepted, candidate, kept_ids, rules, changes, strength, project):
    bar = float((rules.get("clear_time") or {}).get("min_ratio", 1.0))
    items = []
    pairs = [("opening", accepted.get("opening") or {}, candidate.get("opening") or {})]
    for uid in kept_ids:
        a = (accepted["units"].get(uid) or {}).get("naive_runs")
        c = (candidate["units"].get(uid) or {}).get("naive_runs")
        if a or c:
            pairs.append((uid, a or {}, c or {}))
    naive_bad = _degraded(accepted, candidate, "naive")
    survey_bad = _degraded(accepted, candidate, "survey")
    for name, a, c in ([] if naive_bad else pairs):
        for policy in sorted(set(a.get("policies") or {}) - set(c.get("policies") or {})):
            items.append(_item(UNREPORTED, f"{name}, naive {policy}: played on the accepted "
                               "build, not entered by naive play on the candidate", changes,
                               "baseline.clear_time", name, f"naive.{policy}",
                               accepted=a["policies"][policy], candidate=None))
        for policy in sorted(set(a.get("policies") or {}) & set(c.get("policies") or {})):
            ac, cc = a["policies"][policy], c["policies"][policy]
            verdict, ratio, note = _shrink(ac.get("fastest_s"), ac.get("uncleared_min_s"),
                                           cc.get("fastest_s"), cc.get("uncleared_min_s"), bar)
            label = name if name != "opening" else (
                f"the opening unit ({a.get('unit') or '?'} -> {c.get('unit') or '?'})")
            summary = (f"{label}, naive {policy}: fastest clear "
                       f"{ac.get('fastest_s') or ('>= ' + str(ac.get('uncleared_min_s')))} s -> "
                       f"{cc.get('fastest_s') or ('>= ' + str(cc.get('uncleared_min_s')))} s"
                       + (f" ({note} {ratio} x)" if ratio is not None else f" ({note})"))
            items.append(_item(verdict, summary, changes, "baseline.clear_time", name,
                               f"naive.{policy}", accepted=ac, candidate=cc, ratio=ratio))
    for uid in ([] if survey_bad else kept_ids):
        a, c = accepted["units"].get(uid) or {}, candidate["units"].get(uid) or {}
        if (a.get("oracle_s") is not None or a.get("oracle_lower_s")) and c.get("asked") \
                and not c.get("reached"):
            items.append(_item(UNREPORTED, f"{uid}, oracle: timed on the accepted build, not "
                               "entered by the survey on the candidate", changes,
                               "baseline.clear_time", uid, "oracle",
                               accepted=a.get("oracle_s"), candidate=None))
            continue
        if not (a.get("reached") and c.get("reached")):
            continue
        if a.get("oracle_s") is None and c.get("oracle_s") is None:
            continue
        verdict, ratio, note = _shrink(a.get("oracle_s"), a.get("oracle_lower_s"),
                                       c.get("oracle_s"), c.get("oracle_lower_s"), bar)
        was = a.get("oracle_s") or f">= {a.get('oracle_lower_s')}"
        now = c.get("oracle_s") or f">= {c.get('oracle_lower_s')}"
        items.append(_item(verdict, f"{uid}, oracle: clear {was} s -> {now} s"
                           + (f" ({note} {ratio} x)" if ratio is not None else f" ({note})"),
                           changes, "baseline.clear_time", uid, "oracle",
                           accepted=a.get("oracle_s"), candidate=c.get("oracle_s"), ratio=ratio))
    waived = [{"unit": i.get("unit"), "quantity": i.get("quantity"), "reason": i["reason"],
               "decided_by": i["decided_by"]} for i in items if i["verdict"] == "accepted-change"]
    return _result("baseline.clear_time", project, strength, items, "clear time(s)",
                   f"each unit's fastest naive clear (per policy) and the oracle's clear >= {bar} "
                   "x the accepted build's; a build not cleared in its run is a lower bound",
                   "no unit was played on both builds (naive play, the survey)",
                   waived=waived, degraded=", ".join(n for n in (naive_bad, survey_bad) if n),
                   accepted_unmeasured=None if _played(accepted) else
                   "naive play and the survey timed no unit on it")


def _clear_rate(accepted, candidate, kept_ids, realism_rules, changes, strength, project):
    """A clear rate above the accepted band: the unit got easier beyond chance - the other side
    of play-realism's naive.clear_rate (which holds the fall), with its bars."""
    bars = realism_rules.get("clear_rate") or {}
    min_runs = int(bars.get("min_runs") or 1)
    min_rise = float(bars.get("min_drop") or 0)
    min_z = float(bars.get("min_z") or 0)
    items = []
    pairs = [("opening", accepted.get("opening") or {}, candidate.get("opening") or {})]
    for uid in kept_ids:
        pairs.append((uid, (accepted["units"].get(uid) or {}).get("naive_runs") or {},
                      (candidate["units"].get(uid) or {}).get("naive_runs") or {}))
    naive_bad = _degraded(accepted, candidate, "naive")
    for name, a, c in ([] if naive_bad else pairs):
        for policy in sorted(set(a.get("policies") or {}) - set(c.get("policies") or {})):
            if a["policies"][policy]["n"] >= min_runs:
                items.append(_item(UNREPORTED, f"{name}, naive {policy}: run "
                                   f"{a['policies'][policy]['n']} times on the accepted build, "
                                   "never on the candidate", changes, "baseline.clear_rate",
                                   name, f"naive.{policy}", accepted=[
                                       a["policies"][policy]["won"], a["policies"][policy]["n"]],
                                   candidate=None))
        for policy in sorted(set(a.get("policies") or {}) & set(c.get("policies") or {})):
            ac, cc = a["policies"][policy], c["policies"][policy]
            if ac["n"] >= min_runs and cc["n"] < min_runs:
                items.append(_item(UNREPORTED, f"{name}, naive {policy}: run {ac['n']} times on "
                                   f"the accepted build, {cc['n']} on the candidate (< "
                                   f"{min_runs})", changes, "baseline.clear_rate", name,
                                   f"naive.{policy}", accepted=[ac["won"], ac["n"]],
                                   candidate=[cc["won"], cc["n"]]))
                continue
            if ac["n"] < min_runs or cc["n"] < min_runs:
                continue
            p0, p1 = ac["won"] / ac["n"], cc["won"] / cc["n"]
            pooled = (ac["won"] + cc["won"]) / float(ac["n"] + cc["n"])
            spread = math.sqrt(pooled * (1 - pooled) * (1.0 / ac["n"] + 1.0 / cc["n"]))
            z = (p1 - p0) / spread if spread > 0 else (math.inf if p1 > p0 else 0.0)
            rise = round(p1 - p0, 3)
            easier = rise >= min_rise and z >= min_z
            items.append(_item("regressed" if easier else "kept",
                               f"{name}, naive {policy}: clear rate {round(p0, 3)} -> "
                               f"{round(p1, 3)} (z {round(z, 2) if math.isfinite(z) else 'inf'})",
                               changes, "baseline.clear_rate", name, f"naive.{policy}",
                               accepted=[ac["won"], ac["n"]], candidate=[cc["won"], cc["n"]],
                               rise=rise, z=round(z, 2) if math.isfinite(z) else None))
    waived = [{"unit": i.get("unit"), "quantity": i.get("quantity"), "reason": i["reason"],
               "decided_by": i["decided_by"]} for i in items if i["verdict"] == "accepted-change"]
    return _result("baseline.clear_rate", project, strength, items,
                   "unit/player-model clear rate(s)",
                   {"max_rise": min_rise, "min_z": min_z, "min_runs": min_runs,
                    "from": "play-realism.yaml clear_rate"},
                   f"no unit and player model was played at least {min_runs} times on both builds",
                   waived=waived, degraded=naive_bad,
                   accepted_unmeasured=None if any(
                       cell["n"] >= min_runs for _n, a, _c in pairs
                       for cell in (a.get("policies") or {}).values()) else
                   f"naive play entered no unit {min_runs} times on it")


def _responsiveness(accepted, candidate, rules, changes, strength, project):
    bars = rules.get("responsiveness") or {}
    items = []
    a, c = accepted.get("responsiveness") or {}, candidate.get("responsiveness") or {}
    start_ratio = float(bars.get("max_start_ratio", 1.0))
    start_slack = float(bars.get("start_slack_ms", 0))
    if not _degraded(accepted, candidate, "first-session") and \
            _number(a.get("start_ms")) is not None and _number(c.get("start_ms")) is not None:
        limit = max(a["start_ms"] * start_ratio, a["start_ms"] + start_slack)
        items.append(_item("regressed" if c["start_ms"] > limit else "kept",
                           f"play begins {a['start_ms']} -> {c['start_ms']} ms after the page's "
                           f"first byte (limit {round(limit)})", changes,
                           "baseline.responsiveness", "*",
                           "start_ms", accepted=a["start_ms"], candidate=c["start_ms"]))
    elif not _degraded(accepted, candidate, "first-session") and \
            _number(a.get("start_ms")) is not None:
        items.append(_item(UNREPORTED, f"play began {a['start_ms']} ms after the page's first "
                           "byte on the accepted build; the candidate's start was not measured",
                           changes, "baseline.responsiveness", "*", "start_ms",
                           accepted=a["start_ms"], candidate=None))
    ack_bar = float(bars.get("min_ack_fraction", 0.0))
    if not _degraded(accepted, candidate, "act"):
        for action, fraction in sorted((a.get("acknowledged") or {}).items()):
            now = (c.get("acknowledged") or {}).get(action)
            if fraction < ack_bar:
                continue
            if now is None:
                items.append(_item(UNREPORTED, f"action {action}: acknowledged on the "
                                   "accepted build, not pressed by the act test on the candidate",
                                   changes, "baseline.responsiveness", "*", f"ack.{action}",
                                   accepted=fraction, candidate=None))
                continue
            items.append(_item("regressed" if now < ack_bar else "kept",
                               f"action {action}: {fraction} -> {now} of the frame changed within "
                               "the acknowledgement window", changes, "baseline.responsiveness",
                               "*", f"ack.{action}", accepted=fraction, candidate=now))
    fps_ratio = float(bars.get("min_fps_ratio", 1.0))
    if not _degraded(accepted, candidate, "win") and \
            _number(a.get("fps")) and _number(c.get("fps")) is not None:
        ratio = round(c["fps"] / a["fps"], 3)
        items.append(_item("regressed" if ratio < fps_ratio else "kept",
                           f"frames per second while the oracle plays {a['fps']} -> {c['fps']} "
                           f"({ratio} x)", changes, "baseline.responsiveness", "*", "fps",
                           accepted=a["fps"], candidate=c["fps"], ratio=ratio))
    elif not _degraded(accepted, candidate, "win") and _number(a.get("fps")):
        # No frame counted on the candidate in the win test (review n1): not reported.
        items.append(_item(UNREPORTED, f"frames per second while the oracle plays {a['fps']} "
                           "on the accepted build; no frame rate measured on the candidate",
                           changes, "baseline.responsiveness", "*", "fps", accepted=a["fps"],
                           candidate=None))
    degraded = _degraded(accepted, candidate, "first-session", "act", "win")
    waived = [{"unit": i.get("unit"), "quantity": i.get("quantity"), "reason": i["reason"],
               "decided_by": i["decided_by"]} for i in items if i["verdict"] == "accepted-change"]
    return _result("baseline.responsiveness", project, strength, items, "timing(s)",
                   f"start <= max({start_ratio} x, + {start_slack} ms) the accepted build's; every "
                   f"action the accepted build acknowledged still changes >= {ack_bar} of the "
                   f"frame; frame rate >= {fps_ratio} x",
                   "neither the start, the actions' acknowledgement nor the frame rate was "
                   "measured on both builds", degraded=degraded, waived=waived,
                   accepted_unmeasured=None if (_number(a.get("start_ms")) is not None
                                                or a.get("acknowledged") or a.get("fps")) else
                   "neither its start, its actions' acknowledgement nor its frame rate was "
                   "recorded")


# -- advisory measurements (baseline-compare.yaml 1.1.0) -----------------------------------------
#
# Two more quantities of the candidate against the accepted build, reported and never held
# (check-tiers.yaml `advisory`): their bars are not calibrated against builds measured with this
# step, so a WARNING beyond them is information for the person at G4, not a defect sent to
# develop. Both are always `required: false` whatever the run's tier (`ADVISORY`): a change
# beyond a bar is a WARNING, an unmeasured one a WARNING saying why, never a pass. Neither is in
# `IDS`, which floor.accepted_baseline and a blocked comparison enumerate.

ADVISORY_IDS = ("baseline.source_rewrite", "baseline.frame_metrics")
ADVISORY = Strength(None, False, None)
REWRITE_QUANTITIES = ("units_replaced_share", "files_rewritten_share", "lines_deleted_share")
# The empty tree: `git diff --numstat <EMPTY_TREE> <commit>` counts every text file's lines.
EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
_HELD_PREFIX = "QUALITY REGRESSION against the accepted build"


class RewriteError(RuntimeError):
    """The repository cannot answer: a commit is missing, or git failed."""


class GitReader:
    """Commit reads of a checkout the Factory cloned itself: through wgflib.procs, with
    gitsafe-hardened argv, and only commands that run nothing the repository defines
    (`cat-file`; `diff --numstat` with renames, external diffs and textconv off). `run(argv)`
    replaces the process call (tests)."""

    def __init__(self, root, run=None, timeout=300):
        self.root = root
        self._run = run
        self.timeout = timeout

    def _git(self, *args):
        from wgflib import gitsafe, procs
        argv = gitsafe.hardened(list(args), self.root, drivers=())
        if self._run is not None:
            return self._run(argv)
        return procs.run(argv, cwd=self.root, env=gitsafe.safe_env(), timeout=self.timeout,
                         heartbeat_seconds=0, grace_seconds=1.0, poll_seconds=0.02)

    def has_commit(self, sha):
        return bool(sha) and self._git("cat-file", "-e", f"{sha}^{{commit}}").ok

    def file_at(self, sha, path):
        done = self._git("cat-file", "blob", f"{sha}:{path}")
        return done.stdout if done.ok else None

    def numstat(self, a, b, roots):
        done = self._git("diff", "--numstat", "--no-renames", "--no-ext-diff", "--no-textconv",
                         a, b, "--", *roots)
        if not done.ok:
            raise RewriteError(f"git diff --numstat {a[:12]} {b[:12]} failed: "
                               f"{done.tail(5).strip()}")
        out = {}
        for line in (done.stdout or "").splitlines():
            parts = line.split("\t", 2)
            if len(parts) != 3 or parts[0] == "-" or parts[1] == "-":
                continue  # a binary file: no lines to count
            try:
                out[parts[2]] = (int(parts[0]), int(parts[1]))
            except ValueError:
                continue
        return out

    def line_counts(self, sha, roots):
        return {path: added for path, (added, _deleted)
                in self.numstat(EMPTY_TREE, sha, roots).items()}


def _content_units(text):
    if text is None:
        return None
    try:
        data = json.loads(text)
    except ValueError:
        return None
    units = data.get("units") if isinstance(data, dict) else None
    if not isinstance(units, list):
        return None
    return {str(u.get("id")): u for u in units if isinstance(u, dict) and u.get("id")}


def _altered(old, new):
    """Whether `new` drops or alters anything `old` had: a key it adds is an extension."""
    if isinstance(old, dict):
        if not isinstance(new, dict):
            return True
        return any(key not in new or _altered(value, new[key]) for key, value in old.items())
    if isinstance(old, list):
        if not isinstance(new, list) or len(new) < len(old):
            return True
        return any(_altered(a, b) for a, b in zip(old, new))
    if isinstance(old, bool) or isinstance(new, bool):
        return old is not new
    if isinstance(old, (int, float)) and isinstance(new, (int, float)):
        return float(old) != float(new)
    return old != new


def _ratio(part, whole):
    return round(part / float(whole), 4) if whole else None


def measure_rewrite(git, accepted, candidate, rules, content_path):
    """How much of the accepted commit the candidate commit replaced, read from git objects,
    never a working tree: {units_*, files_*, lines_*, the three shares, unmeasured}.

        units  the accepted content data file's units the candidate removed or altered (a key
               the accepted unit had is gone or holds another value; a key added is an
               extension)
        files  the accepted text files under `roots` the candidate deleted, or rewrote:
               deleted lines >= `file_rewritten_share` of the file's accepted lines
        lines  the accepted lines under `roots` the candidate deleted (renames off: a moved
               file is a deleted one)

    Shares are of what the accepted commit shipped; a quantity it does not ship is None and
    named in `unmeasured`, never 0. RewriteError when the repository cannot answer."""
    rules = rules or {}
    roots = [str(r) for r in rules.get("roots") or ["src"]]
    rewritten_at = float(rules.get("file_rewritten_share", 0.5))
    for sha, what in ((accepted, "accepted"), (candidate, "candidate")):
        if not sha or not git.has_commit(sha):
            raise RewriteError(f"the {what} commit {str(sha or '')[:12] or '(none)'} is not in "
                               "the checkout")
    out = {"roots": roots, "content_path": content_path, "unmeasured": []}
    before = _content_units(git.file_at(accepted, content_path))
    if before is None:
        out.update(units_accepted=None, units_removed=[], units_changed=[],
                   units_replaced_share=None)
        out["unmeasured"].append(f"units: the accepted commit ships no readable {content_path}")
    else:
        after = _content_units(git.file_at(candidate, content_path)) or {}
        removed = sorted(u for u in before if u not in after)
        changed = sorted(u for u in before if u in after and _altered(before[u], after[u]))
        out.update(units_accepted=len(before), units_removed=removed[:40],
                   units_changed=changed[:40],
                   units_replaced_share=_ratio(len(removed) + len(changed), len(before)))
    lines = git.line_counts(accepted, roots)
    stat = git.numstat(accepted, candidate, roots)
    deleted, rewritten = 0, []
    for path, count in sorted(lines.items()):
        gone = min((stat.get(path) or (0, 0))[1], count)
        deleted += gone
        if count and gone / float(count) >= rewritten_at:
            rewritten.append({"path": path, "lines": count, "deleted": gone})
    if not lines:
        out["unmeasured"].append("files: the accepted commit ships no text file under "
                                 + ", ".join(roots))
    rewritten.sort(key=lambda f: (-f["deleted"], f["path"]))
    total = sum(lines.values())
    out.update(files_accepted=len(lines), files_rewritten=len(rewritten),
               files_rewritten_share=_ratio(len(rewritten), len(lines)),
               rewritten_files=rewritten[:20], lines_accepted=total, lines_deleted=deleted,
               lines_deleted_share=_ratio(deleted, total))
    return out


def _advisory(cid, project, items, note, expected, why, **kw):
    """One advisory check from its items (_result, never required): a change beyond its bar
    is a WARNING whose summary says it is not held."""
    found = _result(cid, project, ADVISORY, items, note, expected, why, **kw)
    if found["summary"].startswith(_HELD_PREFIX):
        found["summary"] = ("ADVISORY, not held - beyond the advisory bar against the accepted "
                            "build" + found["summary"][len(_HELD_PREFIX):])
    found["measured"]["advisory"] = True
    return found


def _waivers(items):
    return [{"unit": i.get("unit"), "quantity": i.get("quantity"), "reason": i["reason"],
             "decided_by": i["decided_by"]} for i in items if i["verdict"] == "accepted-change"]


def source_rewrite(git, accepted, candidate, rules, content_path, changes=None,
                   project="desktop"):
    """baseline.source_rewrite (advisory): the share of accepted units replaced, of accepted
    files rewritten and of accepted lines deleted, each against `source_rewrite.maximum`."""
    section = (rules or {}).get("source_rewrite") or {}
    maximum = section.get("maximum") or {}
    expected = {q: f"<= {maximum[q]}" for q in REWRITE_QUANTITIES if maximum.get(q) is not None}
    cid = "baseline.source_rewrite"
    try:
        measured = measure_rewrite(git, accepted, candidate, section, content_path)
    except (RewriteError, OSError) as exc:
        return _check(cid, project, False,
                      f"unmeasured: the replacement of the accepted build could not be read "
                      f"from git ({exc}) - advisory, not held", required=False,
                      measured={"unmeasured": UNREPORTED, "reason": str(exc)[:300],
                                "advisory": True}, expected=expected)
    items = []
    for quantity in REWRITE_QUANTITIES:
        value, bar = measured.get(quantity), maximum.get(quantity)
        if value is None or bar is None:
            continue
        items.append(_item("regressed" if _beyond(value - float(bar), 0.0) else "kept",
                           f"{quantity} {value} (advisory maximum {bar})", changes, cid, "*",
                           quantity, accepted=None, candidate=value, maximum=bar))
    unmeasured = "; ".join(measured["unmeasured"])
    return _advisory(cid, project, items, "replacement share(s)", expected,
                     unmeasured or "no quantity has a maximum", waived=_waivers(items),
                     extra={"rewrite": measured},
                     accepted_unmeasured=None if items else
                     (unmeasured or "no quantity has a maximum"))


def frame_profile(frames_dir, frame_ids, lit_luminance=64):
    """{frame id: {mean_luminance, contrast}} of the frames of `frame_ids` a build captured
    (analysis.frame_stats, the numbers frames.readable reports). A frame missing or unreadable
    is left out, never zero."""
    from .analysis import frame_stats
    out = {}
    for fid in frame_ids or []:
        path = os.path.join(frames_dir or "", f"{fid}.png")
        if not frames_dir or not os.path.isfile(path):
            continue
        try:
            mean, contrast, _lit = frame_stats(path, lit_luminance)
        except Exception:  # an unreadable frame measures nothing  # noqa: BLE001
            continue
        out[str(fid)] = {"mean_luminance": mean, "contrast": contrast}
    return out


def frame_metrics(accepted, candidate, rules, changes=None, project="desktop", degraded=None,
                  not_played=None):
    """baseline.frame_metrics (advisory): for each compared frame both builds captured, the
    candidate's mean luminance and contrast against the accepted build's, within
    `frame_metrics.max_luminance_delta` / `max_contrast_delta` either way. `accepted`,
    `candidate`: frame_profile()s."""
    section = (rules or {}).get("frame_metrics") or {}
    bars = {"mean_luminance": float(section.get("max_luminance_delta", 0)),
            "contrast": float(section.get("max_contrast_delta", 0))}
    expected = {"max_luminance_delta": bars["mean_luminance"],
                "max_contrast_delta": bars["contrast"],
                "frames": list(section.get("frames") or [])}
    cid = "baseline.frame_metrics"
    if not_played or degraded:
        why = (f"the accepted build could not be played ({not_played})" if not_played else
               f"the {degraded} recording of one of the builds was made on a degraded host")
        return _check(cid, project, False, f"unmeasured: {why} - advisory, not held",
                      required=False, expected=expected,
                      measured={"unmeasured": NOT_PLAYED if not_played else DEGRADED,
                                "reason": why[:300], "advisory": True})
    items = []
    for fid in sorted(accepted or {}):
        a, c = accepted[fid], (candidate or {}).get(fid)
        if c is None:
            items.append(_item(UNREPORTED, f"{fid}: captured on the accepted build, not on the "
                               "candidate", changes, cid, fid, "frame", accepted=a,
                               candidate=None))
            continue
        for quantity, bar in bars.items():
            av, cv = _number(a.get(quantity)), _number(c.get(quantity))
            if av is None or cv is None:
                continue
            delta = round(cv - av, 2)
            items.append(_item("regressed" if _beyond(abs(delta), bar) else "kept",
                               f"{fid}: {quantity} {av} -> {cv} ({delta:+}; at most {bar} "
                               "either way)", changes, cid, fid, quantity, accepted=av,
                               candidate=cv, delta=delta))
    return _advisory(cid, project, items, "frame quantity(ies)", expected,
                     "no compared frame was captured on both builds", waived=_waivers(items),
                     accepted_unmeasured=None if accepted else
                     "it captured none of the compared frames")

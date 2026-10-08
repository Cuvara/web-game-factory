"""Play realism: what moves turns where something is drawn, a build played by someone who is not
perfect, level geometry that can be played, and a console without errors.

Checks beside analysis.judge, every bar in core/reference/play-realism.yaml:

    physics.undrawn_collision  every turn or stop of a mover (a ball, a shot) happens at a
                               drawn surface: another entity's drawn box, or an edge of the
                               probe's playfield - never at a wall the simulation has and the
                               screen does not (2D)
    physics.collider_size  the drawn box over the body that collides, per axis, for every
                           entity that reports its `collider`
    naive.setbacks         falls, deaths and respawns per minute of jittered play in the
                           opening unit
    naive.drift            how far across its path the player strays under jittered input
    naive.alignment        the angle between the camera's forward and the control's forward
    naive.pace             time to clear a unit under naive input over the unit's par
    naive.unit_duration    the fastest naive clear of a unit against the tier's minimum
    naive.clear_rate       per unit and player model, the clear rate against the accepted
                           build's
    level.geometry         bends of a declared path layout: not tighter than the width
                           allows, no open inner edge on a tight one
    level.unit_length      a path unit's length over its width, and its crossing time at top
                           speed against its par and the tier's minimum
    level.clearance        the moving body fits the passages a grid layout's solid rows leave
    runtime.console_errors console.error from the game's own origin while it is played
    runtime.webgl_context  a WebGL context lost while it is played

The physics, naive and runtime checks read the bot's records (bot.spec.ts: the win test's
per-frame samples, the naive test, every test's console); the level checks read the content
data file and layout source of the commit played (content-sufficiency.yaml `layout`, the one
layouts contract wgf_design.layouts reads). Every field they read is optional in the probe: a
build that does not report one is UNMEASURED - never a pass - and held as
quality-policy.yaml `skipped_checks` says for the run's tier (`Strength.held`). A measured FAIL
holds the build back at the tiers play-realism.yaml `enforce` names. Nothing here names a
game, an engine or a family.
"""

import math
import os
import re
import statistics

from wgflib import paths
from wgflib.yamllite import load_file

from .analysis import _check

__all__ = ["RULES_PATH", "UNREPORTED", "Strength", "load_rules", "strength_for", "judge",
           "judge_layouts", "judge_runtime", "turns", "layout_length", "naive_units",
           "clear_rates", "compare_clear_rates", "path_layouts", "grid_rows", "resolve"]

RULES_PATH = os.path.join(paths.REFERENCE, "play-realism.yaml")
# `measured.unmeasured` of a check whose data the build does not report (never a pass).
UNREPORTED = "not-reported"
# The ids naive play is judged on, in the order they are reported.
NAIVE_IDS = ("naive.setbacks", "naive.drift", "naive.alignment", "naive.pace",
             "naive.unit_duration")


def load_rules(path=None):
    return load_file(path or RULES_PATH)


class Strength:
    """How a check here is held at the run's quality tier: `fail_required` - a measured FAIL
    holds the build back (play-realism.yaml `enforce`); `held(cid)` - why an unmeasured check
    is not passed (quality-policy.yaml skipped_checks), or None when it is a WARNING."""

    def __init__(self, tier=None, fail_required=False, held=None):
        self.tier = tier
        self.fail_required = bool(fail_required)
        self._held = held

    def held(self, cid):
        return self._held(cid) if callable(self._held) else None


def strength_for(rules, tier, held=None):
    enforced = ((rules or {}).get("enforce") or {}).get("fail_required_at") or []
    return Strength(tier, tier in enforced, held)


def _measured_check(cid, project, ok, summary, strength, **kw):
    return _check(cid, project, ok, summary, required=strength.fail_required, **kw)


def _unmeasured(cid, project, strength, summary, measured=None, expected=None):
    """A check whose data the build does not report: never a pass. Required - a FAIL that
    sends the build back for the probe field - where quality-policy.yaml holds a skipped
    check as not passed; else a WARNING saying the game cannot be checked."""
    why = strength.held(cid)
    measured = dict(measured or {})
    measured.update(unmeasured=UNREPORTED, reason=summary)
    return _check(cid, project, False,
                  "unmeasured: " + summary + (f" - {why}" if why else ""),
                  required=bool(why), measured=measured, expected=expected)


def _percentile(values, share):
    ordered = sorted(values)
    if not ordered:
        return None
    index = min(len(ordered) - 1, max(0, math.ceil(share * len(ordered)) - 1))
    return ordered[index]


def _dimension(design):
    return str(((design or {}).get("engine") or {}).get("dimension") or "2d").lower()


def _number(value):
    return (float(value) if isinstance(value, (int, float)) and not isinstance(value, bool)
            else None)


def _tiered(value, tier):
    if isinstance(value, dict):
        return value.get(tier) if value.get(tier) is not None else value.get("default")
    return value


# -- physics.undrawn_collision: turns and stops at drawn surfaces ----------------------------

def _box(x, y, w, h):
    return (float(x), float(y), float(x) + float(w), float(y) + float(h))


def _mover_box(sample):
    """The box a mover collides with: its collider when the probe reports one, else its drawn
    box (larger, so lenient)."""
    collider = sample[9] if len(sample) > 9 else None
    if isinstance(collider, (list, tuple)) and len(collider) >= 5:
        return _box(*collider[1:5]), True
    return _box(*sample[3:7]), False


def turns(frames, roles, rules):
    """Every reversal and stop of a mover of `roles` in the per-frame samples:
    [{frame, id, axis (0 x, 1 y), sign (the way it was moving), speed, box, collider, kind}]."""
    min_speed = float(rules.get("min_speed_px", 1.0))
    stop_speed = float(rules.get("stop_speed_px", 0.25))
    stop_frames = int(rules.get("stop_frames", 3))
    max_step = float(rules.get("max_step_px", 120))
    tracks = {}
    for index, entities in enumerate(frames or []):
        for sample in entities or []:
            if len(sample) < 7 or sample[1] not in roles or not sample[2]:
                continue
            # A composite is several things drawn as one box (bolts in flight): its centre
            # jumps as its parts come and go, and is no body's path.
            if len(sample) > 8 and sample[8] == "composite":
                continue
            box, collider = _mover_box(sample)
            centre = ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)
            tracks.setdefault(sample[0], []).append((index, centre, box, collider))
    events = []
    for eid, track in tracks.items():
        # Velocities between consecutive frames, broken where a frame is missing or a jump is a
        # respawn rather than travel.
        steps = []
        for (i, a, _ba, _ca), (j, b, _bb, _cb) in zip(track, track[1:]):
            v = (b[0] - a[0], b[1] - a[1])
            steps.append(None if j != i + 1 or math.hypot(*v) > max_step else (i, v))
        for k in range(1, len(steps)):
            prev, cur = steps[k - 1], steps[k]
            if prev is None or cur is None:
                continue
            index, v1 = cur[0], prev[1]
            _i, _centre, box, collider = track[k]
            v2 = cur[1]
            turned = False
            for axis in (0, 1):
                if (abs(v1[axis]) >= min_speed and abs(v2[axis]) >= min_speed
                        and v1[axis] * v2[axis] < 0):
                    events.append({"frame": index, "id": eid, "axis": axis,
                                   "sign": 1 if v1[axis] > 0 else -1, "speed": abs(v1[axis]),
                                   "box": box, "collider": collider, "kind": "reversal"})
                    turned = True
            if turned or math.hypot(*v1) < min_speed or math.hypot(*v2) >= stop_speed:
                continue
            after = steps[k:k + stop_frames]
            if len(after) == stop_frames and all(s is not None and math.hypot(*s[1]) < stop_speed
                                                 for s in after):
                axis = 0 if abs(v1[0]) >= abs(v1[1]) else 1
                events.append({"frame": index, "id": eid, "axis": axis,
                               "sign": 1 if v1[axis] > 0 else -1, "speed": abs(v1[axis]),
                               "box": box, "collider": collider, "kind": "stop"})
    events.sort(key=lambda e: (e["frame"], e["id"], e["axis"]))
    return events


def _moving(frames, index, axis, min_speed, mover):
    """The ids of drawn entities that moved along `axis` into or out of frame `index`: a
    surface that moves can carry or push a mover (a ball resting on a paddle turns with it)."""
    def boxes(i):
        if i < 0 or i >= len(frames):
            return {}
        return {s[0]: _box(*s[3:7]) for s in frames[i] or []
                if len(s) >= 7 and s[2] and s[0] != mover and s[1] != "ui"}
    before, now, after = boxes(index - 1), boxes(index), boxes(index + 1)
    moved = set()
    for sid, box in now.items():
        for other in (before.get(sid), after.get(sid)):
            if other and abs(other[axis] - box[axis]) >= min_speed:
                moved.add(sid)
    return moved


def _touches(a, b, tol):
    return not (a[0] - tol > b[2] or b[0] - tol > a[2] or a[1] - tol > b[3] or b[1] - tol > a[3])


def _explained(event, surfaces, playfield, tolerance, carriers=()):
    """(what explains the turn - a surface id or `playfield` - or None, and the gap to the
    nearest drawn face ahead of the mover, px). A surface explains it when its face toward the
    mover lies between the mover's centre and its leading edge plus the tolerance, and the two
    overlap across the other axis; or when it is touching the mover and itself moving along the
    axis (it carries or pushes it)."""
    box, axis, sign = event["box"], event["axis"], event["sign"]
    tol = tolerance + event["speed"]
    other = 1 - axis
    lo, hi = box[axis], box[axis + 2]
    centre = (lo + hi) / 2
    nearest = None
    for sid, surface in surfaces:
        if sid in carriers and _touches(box, surface, tolerance):
            return sid, 0.0
        # Inside something drawn (a gap in a composite row of bricks, a hit the frame drew
        # mid-overlap): in contact with it, wherever its parts are.
        if _touches(box, surface, -tolerance):
            return sid, 0.0
        if surface[other] - tol > box[other + 2] or surface[other + 2] + tol < box[other]:
            continue
        face = surface[axis + 2] if sign < 0 else surface[axis]
        gap = (lo - face) if sign < 0 else (face - hi)
        if (sign < 0 and lo - tol <= face <= centre) or (sign > 0 and centre <= face <= hi + tol):
            return sid, round(max(gap, 0.0), 1)
        if gap >= 0 and (nearest is None or gap < nearest):
            nearest = gap
    if playfield is not None:
        edge = playfield[axis] if sign < 0 else playfield[axis + 2]
        gap = (lo - edge) if sign < 0 else (edge - hi)
        if gap <= tol:
            return "playfield", round(max(gap, 0.0), 1)
        if nearest is None or gap < nearest:
            nearest = gap
    return None, (round(nearest, 1) if nearest is not None else None)


def _physics_checks(records, design, rules, project, strength):
    bars = rules.get("physics") or {}
    if _dimension(design) not in [str(d).lower() for d in bars.get("dimensions") or []]:
        # A 3D build's screen positions are projections of a moving camera: not judged here.
        return []
    win = records.get("win") or {}
    sampled = win.get("sampled") or {}
    frames = sampled.get("frames") or []
    roles = set(bars.get("roles") or [])
    checks = []
    movers = {s[0] for f in frames for s in f or [] if len(s) >= 7 and s[1] in roles and s[2]
              and not (len(s) > 8 and s[8] == "composite")}
    expected = {"tolerance_px": bars.get("tolerance_px"), "roles": sorted(roles)}
    if not frames:
        checks.append(_unmeasured("physics.undrawn_collision", project, strength,
                                  "the win test sampled no rendered frame", expected=expected))
    elif movers:
        playfields = sampled.get("playfields") or []
        events = turns(frames, roles, bars)
        unexplained, explained = [], 0
        # One contact can turn a mover on both axes (a paddle that sends the ball back at an
        # angle): a turn is explained when any turn of the same mover in the same frame is.
        contacts = {}
        for event in events:
            index = event["frame"]
            # What was drawn in the frame of the turn and the one before it: a brick the hit
            # breaks is gone from the frame that shows the ball turned.
            surfaces = [(s[0], _box(*s[3:7])) for f in (frames[index - 1] if index else [],
                                                       frames[index] or [])
                        for s in f or []
                        if len(s) >= 7 and s[2] and s[0] != event["id"] and s[1] != "ui"]
            carriers = _moving(frames, index, event["axis"],
                               float(bars.get("min_speed_px", 1.0)), event["id"])
            pf = playfields[index] if index < len(playfields) else None
            pf = _box(pf["x"], pf["y"], pf["w"], pf["h"]) if isinstance(pf, dict) else None
            by, gap = _explained(event, surfaces, pf, float(bars.get("tolerance_px", 6)),
                                 carriers)
            contacts.setdefault((index, event["id"]), []).append((event, by, gap, pf))
        for (index, _eid), group in sorted(contacts.items()):
            if any(by for _e, by, _g, _p in group):
                explained += len(group)
                continue
            for event, _by, gap, pf in group:
                box = event["box"]
                unexplained.append({"frame": index, "id": event["id"], "kind": event["kind"],
                                    "axis": "xy"[event["axis"]],
                                    "moving": ("-" if event["sign"] < 0 else "+") + "xy"[event["axis"]],
                                    "at": [round((box[0] + box[2]) / 2, 1),
                                           round((box[1] + box[3]) / 2, 1)],
                                    "gap_ahead_px": gap, "collider": event["collider"],
                                    "playfield": pf is not None})
        measured = {"turns": len(events), "explained": explained, "unexplained": unexplained[:12],
                    "playfield_reported": any(isinstance(p, dict) for p in playfields),
                    "collider_reported": any(e["collider"] for e in events)}
        if not events:
            checks.append(_measured_check("physics.undrawn_collision", project, True,
                                          f"no {', '.join(sorted(roles))} turned or stopped in "
                                          f"{len(frames)} sampled frames", strength,
                                          measured=measured, expected=expected))
        elif not unexplained:
            checks.append(_measured_check("physics.undrawn_collision", project, True,
                                          f"all {len(events)} turns and stops of a "
                                          f"{'/'.join(sorted(roles))} were at a drawn surface",
                                          strength, measured=measured, expected=expected))
        elif any(u["playfield"] or u["gap_ahead_px"] is not None for u in unexplained):
            # With the playfield reported, a turn at neither it nor an entity is at nothing
            # drawn. Without it, a turn short of a drawn entity still ahead of the mover is
            # inside the board - its edges enclose everything drawn in play - so no edge
            # explains it either.
            first = next(u for u in unexplained
                         if u["playfield"] or u["gap_ahead_px"] is not None)
            checks.append(_measured_check(
                "physics.undrawn_collision", project, False,
                f"{len(unexplained)} of {len(events)} turns happened where nothing is drawn: "
                f"{first['id']} turned moving {first['moving']} at {first['at']} (frame "
                f"{first['frame']}), the nearest drawn face ahead "
                + (f"{first['gap_ahead_px']} px away" if first["gap_ahead_px"] is not None
                   else "nowhere")
                + " - a wall the simulation has and the screen does not",
                strength, measured=measured, expected=expected, frames=["play-2s"]))
        else:
            first = unexplained[0]
            checks.append(_unmeasured(
                "physics.undrawn_collision", project, strength,
                f"{len(unexplained)} of {len(events)} turns are at no drawn entity (first: "
                f"{first['id']} moving {first['moving']} at {first['at']}, frame "
                f"{first['frame']}), and the probe reports no playfield, so a board edge it does "
                "not report may explain them", measured=measured, expected=expected))

    # physics.collider_size: what is drawn over the collider, per axis, per entity reporting
    # one - its opaque BODY when the probe reports one (a solid disc inside a glow), else its
    # whole drawn box. A collider is never passed without something drawn to hold it to: a
    # halo declared without a body, an empty body or a body outside the drawn box fails.
    ratios, sources, broken = {}, {}, {}
    slack = 1.0
    for entities in frames:
        for s in entities or []:
            collider = s[9] if len(s) > 9 else None
            if not (isinstance(collider, (list, tuple)) and len(collider) >= 5 and s[2]):
                continue
            cw, ch = float(collider[3]), float(collider[4])
            if cw <= 0 or ch <= 0:
                continue
            body = s[10] if len(s) > 10 else None
            halo = s[11] if len(s) > 11 else None
            drawn = _box(*s[3:7])
            if isinstance(body, (list, tuple)) and len(body) >= 4:
                bw, bh = float(body[2]), float(body[3])
                inner = _box(*body[:4])
                if bw <= 0 or bh <= 0:
                    broken.setdefault(s[0], "its reported body is empty")
                    continue
                if (inner[0] < drawn[0] - slack or inner[1] < drawn[1] - slack
                        or inner[2] > drawn[2] + slack or inner[3] > drawn[3] + slack):
                    broken.setdefault(s[0], "its reported body lies outside its drawn box")
                    continue
                ratios.setdefault(s[0], []).append((bw / cw, bh / ch))
                sources.setdefault(s[0], set()).add("body")
            elif halo is True:
                broken.setdefault(s[0], "it declares a halo but reports no body inside it")
            else:
                ratios.setdefault(s[0], []).append((float(s[5]) / cw, float(s[6]) / ch))
                sources.setdefault(s[0], set()).add("sprite")
    hi = float(bars.get("max_drawn_to_collider", 1.3))
    lo = float(bars.get("min_drawn_to_collider", 0.77))
    size_expected = {"drawn_to_collider": f"{lo} - {hi} per axis",
                     "judged_on": "the reported body, else the whole drawn box"}
    if frames and not ratios and not broken and movers:
        checks.append(_unmeasured(
            "physics.collider_size", project, strength,
            "the probe reports no entities[].collider, so what collides cannot be held to "
            "what is drawn", expected=size_expected))
    elif ratios or broken:
        per = {eid: [round(statistics.median(r[0] for r in rs), 2),
                   round(statistics.median(r[1] for r in rs), 2)] for eid, rs in ratios.items()}
        off = {eid: r for eid, r in per.items() if max(r) > hi or min(r) < lo}
        problems = ([f"{eid} {r[0]}x{r[1]} ({'/'.join(sorted(sources[eid]))})"
                     for eid, r in sorted(off.items())[:5]]
                    + [f"{eid}: {why}" for eid, why in sorted(broken.items())[:5]])
        checks.append(_measured_check(
            "physics.collider_size", project, not off and not broken,
            (f"drawn size over collider is within {lo}-{hi} for {len(per)} entities"
             if not problems else "drawn size over collider out of bounds: " + "; ".join(problems)),
            strength, measured={"ratios": dict(sorted(per.items())[:20]),
                                "judged_on": {e: sorted(v) for e, v in sorted(sources.items())[:20]},
                                "out_of_bounds": sorted(off), "no_drawn_body": dict(sorted(broken.items()))},
            expected=size_expected))
    return checks


# -- naive.*: the build played by someone who is not perfect ---------------------------------

def _angle(a, b):
    """Degrees between two ground-plane directions, or None for a zero vector."""
    try:
        ax, az, bx, bz = float(a[0]), float(a[1]), float(b[0]), float(b[1])
    except (TypeError, ValueError, IndexError):
        return None
    na, nb = math.hypot(ax, az), math.hypot(bx, bz)
    if na == 0 or nb == 0:
        return None
    cos = max(-1.0, min(1.0, (ax * bx + az * bz) / (na * nb)))
    return math.degrees(math.acos(cos))


def _par_of(run, design_units):
    """(par seconds, where it came from) for a naive run's unit: the probe's content.par_s,
    else the design unit's parameters.par_s, else its parameters.time_target."""
    if _number(run.get("par_s")) and run["par_s"] > 0:
        return float(run["par_s"]), "probe content.par_s"
    unit = next((u for u in design_units if u.get("id") == run.get("unit_id")), None)
    parameters = (unit or {}).get("parameters") or {}
    for key in ("par_s", "time_target"):
        value = _number(parameters.get(key))
        if value and value > 0:
            return value, f"design parameters.{key}"
    return None, None


def _entered(run):
    if run.get("entered") is not None:
        return bool(run["entered"])
    # A record from before `entered` was written: a unit it reported and time it played.
    return bool(run.get("unit_id")) and (run.get("played_ms") or 0) > 0


def _opening(runs):
    """The runs of the opening unit: the first session's (no unit asked for), else the
    first unit played."""
    first = [r for r in runs if r.get("asked") in (None, "")]
    if first:
        return first
    unit = runs[0].get("unit_id") if runs else None
    return [r for r in runs if r.get("unit_id") == unit]


def _drift_shares(run):
    """Per-sample |offset| / half_width of one run (the probe's `track`), else the run's own
    `drift_mean_share` as one value (a record that kept only the mean)."""
    shares = [abs(float(t["offset"])) / float(t["half_width"])
              for s in run.get("samples") or [] for t in [s.get("track")]
              if isinstance(t, dict) and _number(t.get("offset")) is not None
              and _number(t.get("half_width")) and t["half_width"] > 0]
    if shares:
        return shares
    mean = _number(run.get("drift_mean_share"))
    return [mean] if mean is not None else []


def clear_rates(runs):
    """{unit id: {policy: {won, n}}} over the naive runs that entered their unit."""
    out = {}
    for run in runs:
        if not _entered(run) or not run.get("unit_id"):
            continue
        cell = out.setdefault(str(run["unit_id"]), {}).setdefault(str(run.get("policy")),
                                                                  {"won": 0, "n": 0})
        cell["n"] += 1
        cell["won"] += 1 if run.get("won") else 0
    return out


def _accepted_rates(accepted):
    """The accepted build's {unit: {policy: {won, n}}}: from its naive record (`runs`) or a
    rates table (`units`); None when there is none."""
    if not isinstance(accepted, dict):
        return None
    if isinstance(accepted.get("units"), dict):
        return {str(u): {str(p): {"won": int(c.get("won") or 0), "n": int(c.get("n") or 0)}
                         for p, c in (cells or {}).items() if isinstance(c, dict)}
                for u, cells in accepted["units"].items() if isinstance(cells, dict)}
    if isinstance(accepted.get("runs"), list):
        return clear_rates([r for r in accepted["runs"] if isinstance(r, dict)])
    return None


def compare_clear_rates(current, accepted, bars):
    """[{unit, policy, current, accepted, drop, z, regressed}] for every unit and policy both
    builds ran at least `min_runs` times; a regression is a drop of at least `min_drop` that a
    one-sided two-proportion z of at least `min_z` says is not chance."""
    min_runs = int(bars.get("min_runs") or 1)
    min_drop = float(bars.get("min_drop") or 0)
    min_z = float(bars.get("min_z") or 0)
    out = []
    for unit, cells in sorted((current or {}).items()):
        for policy, cell in sorted(cells.items()):
            base = ((accepted or {}).get(unit) or {}).get(policy)
            if not base or cell["n"] < min_runs or base["n"] < min_runs:
                continue
            p1, p0 = cell["won"] / cell["n"], base["won"] / base["n"]
            pooled = (cell["won"] + base["won"]) / float(cell["n"] + base["n"])
            spread = math.sqrt(pooled * (1 - pooled) * (1.0 / cell["n"] + 1.0 / base["n"]))
            z = (p0 - p1) / spread if spread > 0 else (math.inf if p0 > p1 else 0.0)
            drop = p0 - p1
            out.append({"unit": unit, "policy": policy, "current": round(p1, 3),
                        "accepted": round(p0, 3), "n": [cell["n"], base["n"]],
                        "drop": round(drop, 3), "z": round(z, 2) if math.isfinite(z) else None,
                        "regressed": drop >= min_drop and z >= min_z})
    return out


def _naive_checks(records, design, rules, project, strength, design_units, accepted=None):
    bars = rules.get("naive") or {}
    naive = records.get("naive")
    dimension = _dimension(design)
    expect_drift = dimension in [str(d).lower() for d in
                                 (bars.get("drift") or {}).get("dimensions") or []]
    expect_view = dimension in [str(d).lower() for d in
                                (bars.get("alignment") or {}).get("dimensions") or []]
    ids = [c for c in NAIVE_IDS if (c != "naive.drift" or expect_drift)
           and (c != "naive.alignment" or expect_view)]
    if naive is None:
        if project in (bars.get("projects") or []):
            return [_unmeasured(cid, project, strength,
                                "the bot wrote no naive-play record on this viewport")
                    for cid in ids]
        return []
    if not naive.get("applies"):
        # Played on other viewports only (play-realism.yaml naive.projects): judged there.
        return []
    runs = [r for r in naive.get("runs") or [] if isinstance(r, dict) and _entered(r)]
    if not runs:
        why = "; ".join(sorted({str(r.get("reason")) for r in naive.get("runs") or []
                                if isinstance(r, dict) and r.get("reason")}))[:200]
        return [_unmeasured(cid, project, strength,
                            "naive play never entered a unit" + (f": {why}" if why else ""))
                for cid in ids]
    jitter = [r for r in runs if r.get("policy") == "jitter"] or runs
    opening = _opening(jitter)
    checks = []

    # Setbacks per minute in the opening unit: the probe's count, else every loss as a lower
    # bound. Every unit's rate is reported.
    setbacks = bars.get("setbacks") or {}
    bar = float(setbacks.get("max_per_min", 6.0))
    least = int(setbacks.get("min_count", 1))

    def rate_of(group):
        minutes = sum(max(0, r.get("played_ms") or 0) for r in group) / 60000.0
        counted = [r for r in group if _number(r.get("setbacks_first")) is not None
                   and _number(r.get("setbacks_last")) is not None]
        total = (sum(r["setbacks_last"] - r["setbacks_first"] for r in counted)
                 if counted and len(counted) == len(group) else None)
        losses = sum(int(r.get("losses") or 0) for r in group)
        return minutes, total, losses

    per_unit = {}
    for run in jitter:
        per_unit.setdefault(str(run.get("unit_id")), []).append(run)
    reported = {}
    for unit, group in per_unit.items():
        minutes, total, losses = rate_of(group)
        reported[unit] = {"played_s": round(minutes * 60, 1), "setbacks": total,
                          "losses": losses,
                          "per_min": (round(total / minutes, 2) if total is not None and minutes
                                      else None)}
    minutes, total, losses = rate_of(opening)
    expected = f"<= {bar} per minute of jittered play in the opening unit"
    measured = {"opening": str(opening[0].get("unit_id")), "units": reported}
    if minutes <= 0:
        checks.append(_unmeasured("naive.setbacks", project, strength,
                                  "no time was played in the opening unit under the jitter policy",
                                  measured=measured, expected=expected))
    elif total is not None:
        rate = round(total / minutes, 2)
        enough = total >= least
        measured.update(per_min=rate, setbacks=total)
        checks.append(_measured_check(
            "naive.setbacks", project, rate <= bar or not enough,
            f"{total} setbacks in {round(minutes * 60)} s of jittered play in the opening unit: "
            f"{rate} a minute"
            + ("" if enough or rate <= bar else f" (fewer than {least}: too few to be a rate)"),
            strength, measured=measured, expected=expected))
    else:
        rate = round(losses / minutes, 2)
        measured.update(per_min_lower_bound=rate, losses=losses)
        if rate > bar and losses >= least:
            checks.append(_measured_check(
                "naive.setbacks", project, False,
                f"{losses} losses in {round(minutes * 60)} s of jittered play in the opening unit "
                f"({rate} a minute), before any fall that does not end play",
                strength, measured=measured, expected=expected))
        else:
            checks.append(_unmeasured(
                "naive.setbacks", project, strength,
                f"the probe reports no `setbacks`, so only losses were counted ({losses} in "
                f"{round(minutes * 60)} s): a fall that does not end play is not seen",
                measured=measured, expected=expected))

    # Drift: |offset| / half_width under jitter in the opening unit, time-weighted.
    drift = bars.get("drift") or {}
    bar = float(drift.get("max_mean_share", 0.8))
    expected = f"mean |offset| / half_width <= {bar} under jittered play in the opening unit"
    weighted, weight, every = 0.0, 0.0, []
    for run in opening:
        shares = _drift_shares(run)
        if shares:
            w = max(1.0, float(run.get("played_ms") or 0))
            weighted += w * (sum(shares) / len(shares))
            weight += w
            every += shares
    if weight:
        mean = round(weighted / weight, 3)
        checks.append(_measured_check(
            "naive.drift", project, mean <= bar,
            f"under jittered input the player kept {mean} of the half width from the centre "
            f"line on average in the opening unit (p90 {round(_percentile(every, 0.9), 3)})",
            strength, measured={"mean_share": mean, "p90": round(_percentile(every, 0.9), 3),
                                "samples": len(every)}, expected=expected))
    elif expect_drift:
        checks.append(_unmeasured("naive.drift", project, strength,
                                  "the probe reports no `track`, so where the player is across "
                                  "its path cannot be read", expected=expected))

    # Alignment: camera forward vs control forward, every policy's samples.
    bar = float((bars.get("alignment") or {}).get("max_p90_deg", 30))
    expected = f"90th percentile <= {bar} degrees"
    angles = [a for r in runs for s in r.get("samples") or []
              for v in [s.get("view")] if isinstance(v, dict)
              for a in [_angle(v.get("camera_forward"), v.get("control_forward"))] if a is not None]
    if angles:
        p90 = round(_percentile(angles, 0.9), 1)
        checks.append(_measured_check(
            "naive.alignment", project, p90 <= bar,
            f"the forward control moved the player {p90} degrees off the camera's forward nine "
            f"samples in ten (max {round(max(angles), 1)})", strength,
            measured={"p90_deg": p90, "max_deg": round(max(angles), 1), "samples": len(angles)},
            expected=expected))
    elif expect_view:
        checks.append(_unmeasured("naive.alignment", project, strength,
                                  "the probe reports no `view`, so whether screen-up moves the "
                                  "player forward cannot be read", expected=expected))

    # Pace: time to clear under naive play over par.
    bar = float(bars.get("min_clear_to_par", 0.5))
    expected = f">= {bar} x the unit's par"
    timed, no_par = [], []
    for r in runs:
        won = r.get("won") and _number(r.get("clear_ms")) is not None
        par, source = _par_of(r, design_units)
        if par is None:
            if won:
                no_par.append(r.get("unit_id"))
            continue
        if won:
            timed.append({"unit": r.get("unit_id"), "policy": r.get("policy"),
                          "clear_s": round(r["clear_ms"] / 1000.0, 2), "par_s": par,
                          "ratio": round(r["clear_ms"] / 1000.0 / par, 3), "par_from": source})
        elif (r.get("played_ms") or 0) / 1000.0 >= bar * par:
            # Still short of the end after the bar's share of par: its clear will be later
            # still, so the ratio is at least this - measured, as a lower bound.
            timed.append({"unit": r.get("unit_id"), "policy": r.get("policy"),
                          "clear_s": None, "played_s": round(r["played_ms"] / 1000.0, 2),
                          "par_s": par, "ratio": round(r["played_ms"] / 1000.0 / par, 3),
                          "par_from": source, "lower_bound": True})
    if not timed:
        reason = ("naive play cleared units, but neither the probe (content.par_s) nor the design "
                  "(parameters.par_s / time_target) states their par: " + ", ".join(
                      sorted({str(u) for u in no_par})) if no_par else
                  f"naive play cleared no unit within {bars.get('run_s')} s and played none "
                  "for the bar's share of a known par, so nothing was timed against a par")
        checks.append(_unmeasured("naive.pace", project, strength, reason,
                                  measured={"runs": len(runs)}, expected=expected))
    else:
        fast = [c for c in timed if c["ratio"] < bar]
        worst = min(timed, key=lambda c: c["ratio"])
        bounds = sum(1 for c in timed if c.get("lower_bound"))
        checks.append(_measured_check(
            "naive.pace", project, not fast,
            (f"naive play took at least {worst['ratio']} x par on {len(timed)} unit run(s)"
             + (f" (still short of the end on {bounds} of them: a lower bound)" if bounds else "")
             if not fast else
             f"naive play ({worst['policy']}) cleared {worst['unit']} in {worst['clear_s']} s, "
             f"{worst['ratio']} x its {worst['par_s']} s par: the unit is over before it asks "
             "anything, or its par means nothing"),
            strength, measured={"timed": timed, "too_fast": sorted({str(c["unit"]) for c in fast})},
            expected=expected))

    # Unit duration: the fastest naive clear of each unit against the tier's minimum.
    least_s = _number(_tiered(bars.get("min_unit_s"), strength.tier))
    if least_s is not None:
        expected = f">= {least_s} s for the fastest naive clear of a unit"
        fastest = {}
        for r in runs:
            unit = str(r.get("unit_id"))
            if r.get("won") and _number(r.get("clear_ms")) is not None:
                seconds = r["clear_ms"] / 1000.0
                if unit not in fastest or fastest[unit][0] is None or seconds < fastest[unit][0]:
                    fastest[unit] = (seconds, r.get("policy"))
            else:
                fastest.setdefault(unit, (None, None))
        lasted = {u: max((r.get("played_ms") or 0) / 1000.0 for r in runs
                         if str(r.get("unit_id")) == u) for u in fastest}
        short = {u: round(s, 2) for u, (s, _p) in fastest.items() if s is not None and s < least_s}
        undecided = [u for u, (s, _p) in fastest.items() if s is None and lasted[u] < least_s]
        measured = {"fastest_s": {u: (round(s, 2) if s is not None else None)
                                  for u, (s, _p) in sorted(fastest.items())},
                    "uncleared_played_s": {u: round(lasted[u], 1) for u, (s, _p) in fastest.items()
                                           if s is None}}
        if short:
            unit = min(short, key=short.get)
            checks.append(_measured_check(
                "naive.unit_duration", project, False,
                f"{unit} was cleared by naive play in {short[unit]} s ({fastest[unit][1]}): a "
                f"unit at tier {strength.tier or 'unknown'} lasts at least {least_s} s",
                strength, measured=measured, expected=expected))
        elif undecided and len(undecided) == len(fastest):
            checks.append(_unmeasured(
                "naive.unit_duration", project, strength,
                f"no unit was cleared and none was played {least_s} s: "
                + ", ".join(sorted(undecided)[:5]), measured=measured, expected=expected))
        else:
            checks.append(_measured_check(
                "naive.unit_duration", project, True,
                f"every naive clear took at least {least_s} s"
                + ("" if all(s is not None for s, _p in fastest.values()) else
                   " (units not cleared lasted at least the run: a lower bound)"),
                strength, measured=measured, expected=expected))

    # Clear rate against the accepted build, per unit and player model.
    checks.append(_clear_rate_check(runs, accepted, rules, project, strength))
    return checks


def _clear_rate_check(runs, accepted, rules, project, strength):
    bars = rules.get("clear_rate") or {}
    current = clear_rates(runs)
    base = _accepted_rates(accepted)
    expected = {"min_drop": bars.get("min_drop"), "min_z": bars.get("min_z"),
                "min_runs": bars.get("min_runs")}
    if base is None:
        # Nothing to compare: reported, never a pass, and never held against the build -
        # a game with no accepted build has no clear rate to fall from.
        return _check("naive.clear_rate", project, False,
                      "unmeasured: no accepted build's clear rates to compare with (the step's "
                      "`with: accepted_play`)", required=False,
                      measured={"unmeasured": "no-accepted-build", "rates": current},
                      expected=expected)
    compared = compare_clear_rates(current, base, bars)
    measured = {"rates": current, "compared": compared}
    if not compared:
        return _unmeasured("naive.clear_rate", project, strength,
                           f"no unit was run at least {bars.get('min_runs')} times on both this "
                           "build and the accepted one", measured=measured, expected=expected)
    regressed = [c for c in compared if c["regressed"]]
    if regressed:
        worst = max(regressed, key=lambda c: c["drop"])
        return _measured_check(
            "naive.clear_rate", project, False,
            f"{len(regressed)} unit/player-model pair(s) clear less often than on the accepted "
            f"build: {worst['unit']} ({worst['policy']}) {worst['current']} against "
            f"{worst['accepted']} (z {worst['z']})", strength, measured=measured,
            expected=expected)
    return _measured_check(
        "naive.clear_rate", project, True,
        f"{len(compared)} unit/player-model pair(s) clear as often as on the accepted build",
        strength, measured=measured, expected=expected)


def judge(records, design, rules, project, strength=None, design_units=(), accepted=None):
    """The physics, naive and runtime checks for one viewport's records."""
    strength = strength or Strength()
    return (_physics_checks(records, design, rules, project, strength)
            + _naive_checks(records, design, rules, project, strength, list(design_units),
                            accepted)
            + judge_runtime(records, rules, project, strength))


def naive_units(units, count):
    """The unit ids naive play samples beside the opening one: the middle and last of the
    design units the build carries (by index), up to `count` - 1 of them."""
    ids = [u.get("id") for u in sorted(units, key=lambda u: (u.get("index") or 0))
           if isinstance(u, dict) and u.get("id")]
    if len(ids) < 2 or count < 2:
        return []
    picks = []
    for position in range(1, count):
        index = round(position * (len(ids) - 1) / (count - 1))
        if index > 0 and ids[index] not in picks:
            picks.append(ids[index])
    return picks


# -- runtime.*: the console while the build is played ----------------------------------------

def judge_runtime(records, rules, project, strength):
    """runtime.console_errors and runtime.webgl_context over every record of one viewport.
    Records from a bot that captured no console are not judged (old records)."""
    bars = rules.get("runtime") or {}
    seen = [r for r in records.values() if isinstance(r, dict) and "console" in r]
    if not seen:
        if records:
            return [_unmeasured(cid, project, strength,
                                "the bot recorded no console for this viewport")
                    for cid in ("runtime.console_errors", "runtime.webgl_context")]
        return []
    ignore = [re.compile(re.escape(str(p)), re.I) for p in bars.get("ignore") or []]
    counted, ignored, foreign = {}, 0, 0
    lost = 0
    for record in seen:
        console = record.get("console") or {}
        lost += int(console.get("webgl_lost") or 0)
        for entry in console.get("errors") or []:
            if not isinstance(entry, dict):
                continue
            text = str(entry.get("text") or "")
            if not entry.get("same_origin"):
                foreign += 1
            elif any(p.search(text) for p in ignore):
                ignored += 1
            else:
                counted[text] = counted.get(text, 0) + 1
    cap = int(bars.get("max_messages") or 20)
    top = sorted(counted.items(), key=lambda kv: (-kv[1], kv[0]))[:cap]
    checks = [_measured_check(
        "runtime.console_errors", project, not counted,
        "no console error from the game's origin while it was played" if not counted else
        f"{sum(counted.values())} console error(s) from the game's origin "
        f"({len(counted)} distinct): {top[0][0][:200]}", strength,
        measured={"errors": [{"text": t[:300], "count": n} for t, n in top],
                  "ignored_network": ignored, "foreign": foreign, "records": len(seen)},
        expected="no console.error from the game's own origin")]
    checks.append(_measured_check(
        "runtime.webgl_context", project, not lost,
        "no WebGL context was lost while it was played" if not lost else
        f"a WebGL context was lost {lost} time(s) while it was played", strength,
        measured={"webgl_lost": lost, "records": len(seen)},
        expected="no webglcontextlost event"))
    return checks


# -- level.*: the geometry a build declares --------------------------------------------------

def resolve(value, data):
    """A number from a `play_geometry` entry: the number itself, or the value at a dotted path
    into the content data file ("tuning.steering.max_speed"); None when neither."""
    number = _number(value)
    if number is not None:
        return number
    if not isinstance(value, str) or not value:
        return None
    node = data
    for part in value.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return _number(node)


def _inner_railed(rails):
    return rails is True or str(rails).lower() in ("inside", "inner", "both")


def layout_length(layout):
    """The centre-line length of a path layout's segments, in its own units."""
    total = 0.0
    for segment in layout.get("segments") or []:
        if not isinstance(segment, dict):
            continue
        kind = segment.get("t")
        if kind == "turn":
            total += (abs(float(segment.get("deg") or 0)) / 360.0 * 2 * math.pi
                      * float(segment.get("r") or 0))
        elif kind == "jump":
            total += float(segment.get("gap") or 0)
        else:
            total += float(segment.get("len") or 0)
    return total


def _is_path(layout):
    return (isinstance(layout, dict) and isinstance(layout.get("segments"), list)
            and any(isinstance(s, dict) and s.get("t") for s in layout["segments"]))


def path_layouts(content, source=None, key="layout"):
    """{unit id: path layout} from the content data file's units (their `key` entry) and the
    layout source ({unit id: layout}), the source's entry where a unit has both."""
    found = {}
    for unit in (content or {}).get("units") or []:
        if isinstance(unit, dict) and unit.get("id") and _is_path(unit.get(key)):
            found[str(unit["id"])] = unit[key]
    for uid, layout in (source or {}).items():
        if _is_path(layout):
            found[str(uid)] = layout
    return found


def grid_rows(layout):
    """{key: rows} of every list of two or more equal-length strings (three cells or more) in
    a unit's layout: what reads as a grid of cells."""
    out = {}
    if not isinstance(layout, dict):
        return out
    for key, value in layout.items():
        if (isinstance(value, list) and len(value) >= 2 and all(isinstance(r, str) for r in value)
                and len({len(r) for r in value}) == 1 and len(value[0]) >= 3):
            out[str(key)] = value
    return out


def _unit_par(uid, layout, data_units, designed):
    par = _number(layout.get("par_s")) if isinstance(layout, dict) else None
    if par:
        return par
    for source in (data_units.get(uid), designed.get(uid)):
        parameters = (source or {}).get("parameters") or {}
        for key in ("par_s", "time_target"):
            value = _number(parameters.get(key))
            if value and value > 0:
                return value
    return None


def judge_layouts(content, rules, strength=None, source=None, design_units=(), project="build",
                  unit_key="layout"):
    """level.geometry, level.unit_length and level.clearance over the content data file the
    played commit ships (`content`) and its layout source (`source`: {unit id: layout}).
    [] when the build ships no content data file, or declares no geometry these read."""
    strength = strength or Strength()
    if not isinstance(content, dict):
        return []
    return (_path_checks(content, rules, strength, source, design_units, project, unit_key)
            + _clearance_checks(content, rules, strength, source, project, unit_key))


def _path_checks(content, rules, strength, source, design_units, project, unit_key):
    layouts = path_layouts(content, source, unit_key)
    if not layouts:
        return []
    bars = rules.get("geometry") or {}
    declared = (content.get("play_geometry") or {}) if isinstance(content.get("play_geometry"),
                                                                  dict) else {}
    data_units = {str(u.get("id")): u for u in content.get("units") or [] if isinstance(u, dict)}
    designed = {str(u.get("id")): u for u in design_units if isinstance(u, dict)}
    hard = float(bars.get("min_radius_to_width", 1.0))
    tight = float(bars.get("tight_radius_to_width", 1.5))
    min_lw = float(bars.get("min_length_to_width", 20))
    min_tp = float(bars.get("min_traverse_to_par", 0.5))
    min_s = _number(_tiered(bars.get("min_traverse_s"), strength.tier))
    bends, judged_bends, lengths, short, no_speed = [], 0, [], [], []
    for uid, layout in sorted(layouts.items()):
        width = _number(layout.get("width"))
        for position, segment in enumerate(layout.get("segments") or []):
            if not isinstance(segment, dict) or segment.get("t") != "turn":
                continue
            w = _number(segment.get("w")) or width
            r = _number(segment.get("r"))
            if not w or r is None or w <= 0:
                continue
            judged_bends += 1
            ratio = round(r / w, 2)
            railed = _inner_railed(segment.get("rails"))
            problem = ("tighter than the width allows" if ratio < hard else
                       "tight with an open inner edge" if ratio < tight and not railed else None)
            if problem:
                bends.append({"unit": uid, "segment": position, "deg": segment.get("deg"),
                              "r": r, "width": w, "radius_to_width": ratio,
                              "inner_edge": "railed" if railed else "open", "problem": problem})
        length = layout_length(layout)
        entry = {"unit": uid, "length": round(length, 1)}
        problems = []
        if width and width > 0:
            entry["length_to_width"] = round(length / width, 1)
            if entry["length_to_width"] < min_lw:
                problems.append(f"length {entry['length_to_width']} x its width")
        speed = _number(layout.get("top_speed")) or resolve(declared.get("top_speed"), content)
        par = _unit_par(uid, layout, data_units, designed)
        if speed and speed > 0:
            traverse = length / speed
            entry["traverse_s"] = round(traverse, 2)
            if min_s is not None and traverse < min_s:
                problems.append(f"crossed in {entry['traverse_s']} s at top speed")
            if par:
                entry["traverse_to_par"] = round(traverse / par, 2)
                if entry["traverse_to_par"] < min_tp:
                    problems.append(f"crossed at top speed in {entry['traverse_to_par']} x its "
                                    f"{par} s par")
        else:
            no_speed.append(uid)
        lengths.append(entry)
        if problems:
            short.append({**entry, "problems": problems})
    checks = []
    expected = {"min_radius_to_width": hard, "tight_radius_to_width": tight}
    if not judged_bends:
        checks.append(_measured_check("level.geometry", project, True,
                                      f"{len(layouts)} path layouts declare no bend", strength,
                                      measured={"bends": 0}, expected=expected))
    else:
        first = bends[0] if bends else None
        checks.append(_measured_check(
            "level.geometry", project, not bends,
            (f"all {judged_bends} bends are at least {hard} x the width, and every one under "
             f"{tight} x has a railed inner edge" if not bends else
             f"{len(bends)} of {judged_bends} bends cannot be played: {first['unit']} segment "
             f"{first['segment']} turns {first['deg']} degrees at r {first['r']} on a width of "
             f"{first['width']} ({first['radius_to_width']} x), {first['problem']}"),
            strength, measured={"bends": judged_bends, "failing": bends[:20]},
            expected=expected))
    expected = {"min_length_to_width": min_lw, "min_traverse_to_par": min_tp,
                "min_traverse_s": min_s}
    measured = {"units": lengths[:40], "short": [s["unit"] for s in short]}
    if short:
        first = short[0]
        checks.append(_measured_check(
            "level.unit_length", project, False,
            f"{len(short)} of {len(lengths)} units are too short: {first['unit']} - "
            + "; ".join(first["problems"]), strength, measured=measured, expected=expected))
    elif no_speed:
        measured["no_top_speed"] = no_speed[:40]
        checks.append(_unmeasured(
            "level.unit_length", project, strength,
            f"{len(lengths)} layouts are long enough for their width, but {len(no_speed)} state "
            "no top speed (a layout's `top_speed`, or the data file's "
            "`play_geometry.top_speed`), so how fast they are crossed is not known",
            measured=measured, expected=expected))
    else:
        checks.append(_measured_check(
            "level.unit_length", project, True,
            f"{len(lengths)} layouts are long enough for their width, and none is crossed at "
            "top speed in less than the bars allow", strength, measured=measured,
            expected=expected))
    return checks


def _passages(row, solid):
    """The runs of non-solid cells of one row, as cell counts, bounded by solids and the
    board's edges."""
    runs, n = [], 0
    for cell in row:
        if cell in solid:
            if n:
                runs.append(n)
            n = 0
        else:
            n += 1
    if n:
        runs.append(n)
    return runs


def _clearance_checks(content, rules, strength, source, project, unit_key):
    bars = rules.get("clearance") or {}
    units = {}
    for unit in content.get("units") or []:
        if isinstance(unit, dict) and unit.get("id") and isinstance(unit.get(unit_key), dict):
            units[str(unit["id"])] = unit[unit_key]
    for uid, layout in (source or {}).items():
        if isinstance(layout, dict):
            units.setdefault(str(uid), layout)
    grids = {uid: grid_rows(layout) for uid, layout in units.items()}
    grids = {uid: g for uid, g in grids.items() if g}
    if not grids:
        return []
    declared = content.get("play_geometry") if isinstance(content.get("play_geometry"),
                                                          dict) else {}
    grid = declared.get("grid") if isinstance(declared.get("grid"), dict) else None
    body = declared.get("body") if isinstance(declared.get("body"), dict) else {}
    bar = float(bars.get("min_widest_to_body", 2.0))
    expected = {"min_widest_to_body": bar}
    cell = (grid or {}).get("cell")
    cell_w = resolve(cell[0], content) if isinstance(cell, list) and cell else resolve(cell,
                                                                                       content)
    diameter = (resolve(body.get("diameter"), content)
                or (2 * resolve(body.get("radius"), content)
                    if resolve(body.get("radius"), content) else None))
    solid = set(str((grid or {}).get("solid") or ""))
    if not grid or not cell_w or not diameter or not solid:
        missing = [name for name, ok in (("play_geometry.grid", grid), ("grid.cell", cell_w),
                                         ("grid.solid", solid), ("body", diameter)) if not ok]
        summary = (f"{len(grids)} units lay out what reads as a grid of cells, but the content data "
                   f"file does not declare {', '.join(missing)}, so whether the moving body fits "
                   "its passages cannot be read")
        if not grid:
            # Undeclared, the grid is only a guess from the data's shape: reported, never a
            # pass, but not held against the build at any tier. A declared grid that is
            # incomplete is the build's own contract, and is held like any unmeasured check.
            return [_check("level.clearance", project, False, "unmeasured: " + summary,
                           required=False, measured={"unmeasured": UNREPORTED, "reason": summary,
                                                     "grid_units": sorted(grids)[:20]},
                           expected=expected)]
        return [_unmeasured("level.clearance", project, strength, summary,
                            measured={"grid_units": sorted(grids)[:20]}, expected=expected)]
    key = str(grid.get("key") or "")
    rows_judged, failing, closed, shares = 0, [], [], []
    for uid in sorted(units):
        rows = (units[uid] or {}).get(key) if key else None
        if not isinstance(rows, list):
            continue
        for index, row in enumerate(rows):
            if not isinstance(row, str) or not any(c in solid for c in row):
                continue
            rows_judged += 1
            widths = [n * cell_w for n in _passages(row, solid)]
            widest = max(widths) if widths else 0.0
            share = round(sum(max(0.0, w - diameter) for w in widths) / (len(row) * cell_w), 3)
            shares.append(share)
            ratio = round(widest / diameter, 2)
            narrow = [w for w in widths if w < diameter]
            if narrow:
                closed.append({"unit": uid, "row": index, "cells": row,
                               "closed_passages": len(narrow)})
            if ratio < bar:
                failing.append({"unit": uid, "row": index, "cells": row,
                                "widest_px": widest, "body_px": diameter,
                                "widest_to_body": ratio, "passage_share": share})
    measured = {"rows": rows_judged, "body": diameter, "cell": cell_w,
                "failing": failing[:20], "closed": closed[:20],
                "passage_share_min": min(shares) if shares else None}
    if not rows_judged:
        return [_measured_check("level.clearance", project, True,
                                f"no row of the {len(grids)} grid units holds a solid cell",
                                strength, measured=measured, expected=expected)]
    if failing:
        first = failing[0]
        units_failing = sorted({f["unit"] for f in failing})
        return [_measured_check(
            "level.clearance", project, False,
            f"{len(failing)} solid row(s) in {len(units_failing)} unit(s) leave the body too "
            f"little room: {first['unit']} row {first['row']} '{first['cells']}' - widest "
            f"passage {first['widest_px']} for a body {first['body_px']} across "
            f"({first['widest_to_body']} x, under {bar} x)", strength, measured=measured,
            expected=expected)]
    return [_measured_check(
        "level.clearance", project, True,
        f"every one of {rows_judged} solid rows leaves a passage at least {bar} x the body",
        strength, measured=measured, expected=expected)]


# -- level.clearance against the clear rate: a proxy blocks only where the measure is missing --

def gate_clearance(checks, strength=None):
    """`checks` with level.clearance held as play-realism.yaml `clearance.gate` says: its
    failing units BLOCK (at the tiers `enforce` names) only where no per-unit clear rate
    against the accepted build was measured for that unit. Where naive.clear_rate measured
    the unit and it passed, the clearance finding is advisory - reported, not blocking;
    where the clear rate failed, both are reported and the clear rate is what blocks."""
    strength = strength or Strength()
    clearance = next((c for c in checks if c.get("id") == "level.clearance"), None)
    if clearance is None or clearance.get("status") not in ("FAIL", "WARNING"):
        return checks
    failing = (clearance.get("measured") or {}).get("failing") or []
    if not failing:
        return checks
    measured, regressed = set(), set()
    for check in checks:
        if check.get("id") != "naive.clear_rate":
            continue
        for entry in (check.get("measured") or {}).get("compared") or []:
            measured.add(str(entry.get("unit")))
            if entry.get("regressed"):
                regressed.add(str(entry.get("unit")))
    gate = {}
    for item in failing:
        unit = str(item.get("unit"))
        gate[unit] = ("clear-rate-failed" if unit in regressed else
                      "advisory" if unit in measured else "quality-gate")
    blocking = sorted(u for u, g in gate.items() if g == "quality-gate")
    required = strength.fail_required and bool(blocking)
    clearance["measured"] = dict(clearance.get("measured") or {}, gate=gate)
    clearance["required"] = required
    clearance["status"] = "FAIL" if required else "WARNING"
    note = []
    if blocking:
        note.append(f"blocking for {', '.join(blocking)} (no clear rate measured against the "
                    "accepted build)")
    advisory = sorted(u for u, g in gate.items() if g == "advisory")
    if advisory:
        note.append(f"advisory for {', '.join(advisory)} (clear rate at the accepted build's)")
    failed = sorted(u for u, g in gate.items() if g == "clear-rate-failed")
    if failed:
        note.append(f"{', '.join(failed)} also fail naive.clear_rate, which blocks")
    clearance["summary"] = clearance["summary"] + " - " + "; ".join(note)
    return checks

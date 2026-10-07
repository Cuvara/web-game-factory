"""Play realism: what moves turns where something is drawn, a build played by someone who is not
perfect, and level geometry that can be driven.

Three groups of checks beside analysis.judge, every bar in core/reference/play-realism.yaml:

    physics.undrawn_collision  every turn or stop of a mover (a ball, a shot) happens at a
                               drawn surface: another entity's drawn box, or an edge of the
                               probe's playfield - never at a wall the simulation has and the
                               screen does not
    physics.collider_size  the drawn box over the body that collides, per axis, for every
                           entity that reports its `collider`
    naive.setbacks         falls, deaths and respawns per minute under jittered input
    naive.drift            how far across its path the player strays under jittered input
    naive.alignment        the angle between the camera's forward and the control's forward
    naive.pace             time to clear a unit under naive input over the unit's par
    level.geometry         bends of the geometry the build declares (public/content/layouts.json):
                           not tighter than the width allows, no open inner edge on a tight one
    level.unit_length      a unit's length over its width, and its crossing time at top speed
                           against its par and the tier's minimum

The physics and naive checks read the bot's records (bot.spec.ts: the win test's per-frame
samples, the naive test); the level checks read the layout file of the commit played. Every
field they read is optional in the probe: a build that does not report one is UNMEASURED - never
a pass - at the status `unmeasured` gives for the run's quality tier, with the reason. Nothing
here names a game, an engine or a family.
"""

import math
import os
import statistics

from wgflib import paths
from wgflib.yamllite import load_file

from .analysis import _check

__all__ = ["RULES_PATH", "LAYOUTS_DATA", "load_rules", "judge", "judge_layouts", "turns",
           "layout_length", "naive_units"]

RULES_PATH = os.path.join(paths.REFERENCE, "play-realism.yaml")
# The path geometry a build may declare (wgf-layouts/1, docs/template-contract.md), copied
# beside the bot's records by the step so the lint reads exactly the commit played.
LAYOUTS_DATA = "public/content/layouts.json"
LAYOUTS_SCHEMA = "wgf-layouts/1"


def load_rules(path=None):
    return load_file(path or RULES_PATH)


def _unmeasured(cid, project, rules, tier, summary, measured=None, expected=None):
    """A check whose data the build does not report: the tier's `unmeasured` status, never a
    pass. `fail` holds the build back; `warning` says the game cannot be checked."""
    table = rules.get("unmeasured") or {}
    status = str(table.get(tier) or table.get("default") or "warning").lower()
    measured = dict(measured or {})
    measured.update(unmeasured=True, reason=summary)
    return _check(cid, project, False, "unmeasured: " + summary, required=status == "fail",
                  measured=measured, expected=expected)


def _percentile(values, share):
    ordered = sorted(values)
    if not ordered:
        return None
    index = min(len(ordered) - 1, max(0, math.ceil(share * len(ordered)) - 1))
    return ordered[index]


# -- physics.undrawn_collision: turns and stops at drawn surfaces --------------------------------------

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
    [{frame, id, axis (0 x, 1 y), sign (the way it was moving), speed, box, collider}]."""
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
            _i, centre, box, collider = track[k]
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
            after = [s for s in steps[k:k + stop_frames]]
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


def _physics_checks(records, design, rules, project, tier):
    bars = rules.get("physics") or {}
    win = records.get("win") or {}
    sampled = win.get("sampled") or {}
    frames = sampled.get("frames") or []
    roles = set(bars.get("roles") or [])
    checks = []
    movers = {s[0] for f in frames for s in f or [] if len(s) >= 7 and s[1] in roles and s[2]
              and not (len(s) > 8 and s[8] == "composite")}
    dimension = str(((design or {}).get("engine") or {}).get("dimension") or "2d").lower()
    expected = {"tolerance_px": bars.get("tolerance_px"), "roles": sorted(roles)}
    if not frames:
        checks.append(_unmeasured("physics.undrawn_collision", project, rules, tier,
                                  "the win test sampled no rendered frame", expected=expected))
    elif not movers:
        # Nothing of a judged role moved: nothing turns, so there is nothing to place.
        pass
    elif dimension not in [str(d).lower() for d in bars.get("dimensions") or []]:
        checks.append(_unmeasured(
            "physics.undrawn_collision", project, rules, tier,
            f"a {dimension} build's screen positions are projections of a moving camera, so a "
            "turn on screen is not a turn in the world (play-realism.yaml physics.dimensions)",
            measured={"dimension": dimension}, expected=expected))
    else:
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
        frames_of = ["play-2s"]
        if not events:
            checks.append(_check("physics.undrawn_collision", project, True,
                                 f"no {', '.join(sorted(roles))} turned or stopped in "
                                 f"{len(frames)} sampled frames", measured=measured,
                                 expected=expected))
        elif not unexplained:
            checks.append(_check("physics.undrawn_collision", project, True,
                                 f"all {len(events)} turns and stops of a "
                                 f"{'/'.join(sorted(roles))} were at a drawn surface",
                                 measured=measured, expected=expected))
        elif any(u["playfield"] or u["gap_ahead_px"] is not None for u in unexplained):
            # With the playfield reported, a turn at neither it nor an entity is at nothing
            # drawn. Without it, a turn short of a drawn entity still ahead of the mover is
            # inside the board - its edges enclose everything drawn in play - so no edge
            # explains it either.
            first = next(u for u in unexplained
                         if u["playfield"] or u["gap_ahead_px"] is not None)
            checks.append(_check(
                "physics.undrawn_collision", project, False,
                f"{len(unexplained)} of {len(events)} turns happened where nothing is drawn: "
                f"{first['id']} turned moving {first['moving']} at {first['at']} (frame "
                f"{first['frame']}), the nearest drawn face ahead "
                + (f"{first['gap_ahead_px']} px away" if first["gap_ahead_px"] is not None
                   else "nowhere")
                + " - a wall the simulation has and the screen does not",
                measured=measured, expected=expected, frames=frames_of))
        else:
            first = unexplained[0]
            checks.append(_unmeasured(
                "physics.undrawn_collision", project, rules, tier,
                f"{len(unexplained)} of {len(events)} turns are at no drawn entity (first: "
                f"{first['id']} moving {first['moving']} at {first['at']}, frame "
                f"{first['frame']}), and the probe reports no playfield, so a board edge it does "
                "not report may explain them", measured=measured, expected=expected))

    # physics.collider_size: drawn box over collider, per axis, per entity reporting one.
    ratios = {}
    for entities in frames:
        for s in entities or []:
            collider = s[9] if len(s) > 9 else None
            if not (isinstance(collider, (list, tuple)) and len(collider) >= 5 and s[2]):
                continue
            cw, ch = float(collider[3]), float(collider[4])
            if cw <= 0 or ch <= 0:
                continue
            ratios.setdefault(s[0], []).append((float(s[5]) / cw, float(s[6]) / ch))
    hi = float(bars.get("max_drawn_to_collider", 1.3))
    lo = float(bars.get("min_drawn_to_collider", 0.77))
    size_expected = {"drawn_to_collider": f"{lo} - {hi} per axis"}
    if not frames:
        pass
    elif not ratios:
        if movers:
            checks.append(_unmeasured(
                "physics.collider_size", project, rules, tier,
                "the probe reports no entities[].collider, so what collides cannot be held to "
                "what is drawn", expected=size_expected))
    else:
        per = {eid: [round(statistics.median(r[0] for r in rs), 2),
                     round(statistics.median(r[1] for r in rs), 2)] for eid, rs in ratios.items()}
        off = {eid: r for eid, r in per.items() if max(r) > hi or min(r) < lo}
        checks.append(_check(
            "physics.collider_size", project, not off,
            (f"drawn size over collider is within {lo}-{hi} for {len(per)} entities" if not off
             else "drawn size over collider out of bounds: " + ", ".join(
                 f"{eid} {r[0]}x{r[1]}" for eid, r in sorted(off.items())[:5])),
            measured={"ratios": dict(sorted(per.items())[:20]), "out_of_bounds": sorted(off)},
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
    else the design unit's parameters.time_target."""
    if isinstance(run.get("par_s"), (int, float)) and run["par_s"] > 0:
        return float(run["par_s"]), "probe content.par_s"
    unit = next((u for u in design_units if u.get("id") == run.get("unit_id")), None)
    target = ((unit or {}).get("parameters") or {}).get("time_target")
    if isinstance(target, (int, float)) and not isinstance(target, bool) and target > 0:
        return float(target), "design parameters.time_target"
    return None, None


def _naive_checks(records, design, rules, project, tier, design_units):
    bars = rules.get("naive") or {}
    naive = records.get("naive")
    if naive is None:
        if project in (bars.get("projects") or []):
            return [_unmeasured(cid, project, rules, tier,
                                "the bot wrote no naive-play record on this viewport")
                    for cid in ("naive.setbacks", "naive.drift", "naive.alignment", "naive.pace")]
        return []
    if not naive.get("applies"):
        # Played on other viewports only (play-realism.yaml naive.projects): judged there.
        return []
    runs = [r for r in naive.get("runs") or [] if isinstance(r, dict) and r.get("entered")]
    if not runs:
        return [_unmeasured(cid, project, rules, tier,
                            "naive play never entered a unit: "
                            + "; ".join(sorted({str(r.get("reason")) for r in naive.get("runs") or []
                                               if r.get("reason")}))[:200])
                for cid in ("naive.setbacks", "naive.drift", "naive.alignment", "naive.pace")]
    jitter = [r for r in runs if r.get("policy") == "jitter"] or runs
    checks = []

    # Setbacks per minute: the probe's count, else every loss as a lower bound.
    minutes = sum(max(0, r.get("played_ms") or 0) for r in jitter) / 60000.0
    counted = [r for r in jitter if isinstance(r.get("setbacks_first"), (int, float))
               and isinstance(r.get("setbacks_last"), (int, float))]
    losses = sum(int(r.get("losses") or 0) for r in jitter)
    bar = float(bars.get("max_setbacks_per_min", 3.0))
    per_run = [{"unit": r.get("unit_id"), "policy": r.get("policy"),
                "played_s": round((r.get("played_ms") or 0) / 1000.0, 1),
                "setbacks": (r["setbacks_last"] - r["setbacks_first"]) if r in counted else None,
                "losses": r.get("losses") or 0} for r in jitter]
    expected = f"<= {bar} per minute of jittered play"
    if minutes <= 0:
        checks.append(_unmeasured("naive.setbacks", project, rules, tier,
                                  "no time was played under the jitter policy", expected=expected))
    elif counted and len(counted) == len(jitter):
        total = sum(r["setbacks_last"] - r["setbacks_first"] for r in counted)
        rate = round(total / minutes, 2)
        # One fall in a short sample is not a rate: a FAIL needs at least `min_setbacks`.
        enough = total >= int(bars.get("min_setbacks", 1))
        checks.append(_check("naive.setbacks", project, rate <= bar or not enough,
                             f"{total} setbacks in {round(minutes * 60)} s of jittered play: "
                             f"{rate} a minute"
                             + ("" if enough or rate <= bar else
                                f" (fewer than {bars.get('min_setbacks')}: too few to be a rate)"),
                             measured={"per_min": rate, "setbacks": total, "runs": per_run},
                             expected=expected))
    else:
        rate = round(losses / minutes, 2)
        if rate > bar and losses >= int(bars.get("min_setbacks", 1)):
            checks.append(_check("naive.setbacks", project, False,
                                 f"{losses} losses in {round(minutes * 60)} s of jittered play "
                                 f"({rate} a minute), before any fall that does not end play",
                                 measured={"per_min": rate, "source": "losses", "runs": per_run},
                                 expected=expected))
        else:
            checks.append(_unmeasured(
                "naive.setbacks", project, rules, tier,
                f"the probe reports no `setbacks`, so only losses were counted ({losses} in "
                f"{round(minutes * 60)} s): a fall that does not end play is not seen",
                measured={"per_min_lower_bound": rate, "runs": per_run}, expected=expected))

    # Drift: |offset| / half_width under the jitter policy.
    shares = [abs(float(t["offset"])) / float(t["half_width"])
              for r in jitter for s in r.get("samples") or []
              for t in [s.get("track")] if isinstance(t, dict)
              and isinstance(t.get("offset"), (int, float))
              and isinstance(t.get("half_width"), (int, float)) and t["half_width"] > 0]
    bar = float(bars.get("max_drift_p90", 0.9))
    expected = f"90th percentile of |offset| / half_width <= {bar}"
    if not shares:
        checks.append(_unmeasured("naive.drift", project, rules, tier,
                                  "the probe reports no `track`, so where the player is across "
                                  "its path cannot be read", expected=expected))
    else:
        p90 = round(_percentile(shares, 0.9), 3)
        checks.append(_check("naive.drift", project, p90 <= bar,
                             f"under jittered input the player kept within {p90} of the half "
                             f"width nine samples in ten (max {round(max(shares), 3)})",
                             measured={"p90": p90, "max": round(max(shares), 3),
                                       "samples": len(shares)}, expected=expected))

    # Alignment: camera forward vs control forward, every policy's samples.
    angles = [a for r in runs for s in r.get("samples") or []
              for v in [s.get("view")] if isinstance(v, dict)
              for a in [_angle(v.get("camera_forward"), v.get("control_forward"))] if a is not None]
    bar = float(bars.get("max_alignment_deg", 30))
    expected = f"90th percentile <= {bar} degrees"
    if not angles:
        checks.append(_unmeasured("naive.alignment", project, rules, tier,
                                  "the probe reports no `view`, so whether screen-up moves the "
                                  "player forward cannot be read", expected=expected))
    else:
        p90 = round(_percentile(angles, 0.9), 1)
        checks.append(_check("naive.alignment", project, p90 <= bar,
                             f"the forward control moved the player {p90} degrees off the "
                             f"camera's forward nine samples in ten (max {round(max(angles), 1)})",
                             measured={"p90_deg": p90, "max_deg": round(max(angles), 1),
                                       "samples": len(angles)}, expected=expected))

    # Pace: time to clear under naive play over par.
    bar = float(bars.get("min_clear_to_par", 0.5))
    expected = f">= {bar} x the unit's par"
    cleared, no_par = [], []
    for r in runs:
        won = r.get("won") and isinstance(r.get("clear_ms"), (int, float))
        par, source = _par_of(r, design_units)
        if par is None:
            if won:
                no_par.append(r.get("unit_id"))
            continue
        if won:
            cleared.append({"unit": r.get("unit_id"), "policy": r.get("policy"),
                            "clear_s": round(r["clear_ms"] / 1000.0, 2), "par_s": par,
                            "ratio": round(r["clear_ms"] / 1000.0 / par, 3), "par_from": source})
        elif (r.get("played_ms") or 0) / 1000.0 >= bar * par:
            # Still short of the end after the bar's share of par: its clear will be later
            # still, so the ratio is at least this - measured, as a lower bound.
            cleared.append({"unit": r.get("unit_id"), "policy": r.get("policy"),
                            "clear_s": None, "played_s": round(r["played_ms"] / 1000.0, 2),
                            "par_s": par, "ratio": round(r["played_ms"] / 1000.0 / par, 3),
                            "par_from": source, "lower_bound": True})
    if not cleared:
        reason = ("naive play cleared units, but neither the probe (content.par_s) nor the design "
                  "(parameters.time_target) states their par: " + ", ".join(
                      sorted({str(u) for u in no_par})) if no_par else
                  f"naive play cleared no unit within {bars.get('run_s')} s and played none "
                  "for the bar's share of a known par, so nothing was timed against a par")
        checks.append(_unmeasured("naive.pace", project, rules, tier, reason,
                                  measured={"runs": len(runs)}, expected=expected))
    else:
        fast = [c for c in cleared if c["ratio"] < bar]
        worst = min(cleared, key=lambda c: c["ratio"])
        checks.append(_check(
            "naive.pace", project, not fast,
            (f"naive play took at least {worst['ratio']} x par on {len(cleared)} unit run(s)"
             + (" (still short of the end on " + str(sum(1 for c in cleared if c.get("lower_bound")))
                + " of them: a lower bound)" if any(c.get("lower_bound") for c in cleared) else "")
             if not fast else
             f"naive play ({worst['policy']}) cleared {worst['unit']} in {worst['clear_s']} s, "
             f"{worst['ratio']} x its {worst['par_s']} s par: the unit is over before it asks "
             "anything, or its par means nothing"),
            measured={"cleared": cleared, "too_fast": [c["unit"] for c in fast]},
            expected=expected))
    return checks


def judge(records, design, rules, project, tier=None, design_units=()):
    """The physics and naive checks for one viewport's records."""
    return (_physics_checks(records, design, rules, project, tier)
            + _naive_checks(records, design, rules, project, tier, list(design_units)))


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


# -- level.*: the geometry a build declares --------------------------------------------------

def _inner_railed(rails):
    return rails is True or str(rails).lower() in ("inside", "inner", "both")


def layout_length(layout):
    """The centre-line length of a layout's segments, in its own units."""
    total = 0.0
    for segment in layout.get("segments") or []:
        if not isinstance(segment, dict):
            continue
        kind = segment.get("t")
        if kind == "turn":
            total += abs(float(segment.get("deg") or 0)) / 360.0 * 2 * math.pi * float(segment.get("r") or 0)
        elif kind == "jump":
            total += float(segment.get("gap") or 0)
        else:
            total += float(segment.get("len") or 0)
    return total


def _tiered(value, tier):
    if isinstance(value, dict):
        return value.get(tier) if value.get(tier) is not None else value.get("default")
    return value


def judge_layouts(layouts, rules, tier=None, content=None, design_units=(), project="build"):
    """level.geometry and level.unit_length over the layout file the played commit ships
    (wgf-layouts/1). None: the build declares no geometry, and nothing is judged."""
    if layouts is None:
        return []
    bars = rules.get("geometry") or {}
    if not isinstance(layouts, dict) or layouts.get("schema") != LAYOUTS_SCHEMA \
            or not isinstance(layouts.get("layouts"), dict):
        reason = (f"public/content/layouts.json is not {LAYOUTS_SCHEMA} (a `layouts` object by "
                  "unit id)")
        return [_unmeasured("level.geometry", project, rules, tier, reason),
                _unmeasured("level.unit_length", project, rules, tier, reason)]
    data_units = {u.get("id"): u for u in ((content or {}).get("units") or [])
                  if isinstance(u, dict)}
    designed = {u.get("id"): u for u in design_units if isinstance(u, dict)}
    hard = float(bars.get("min_radius_to_width", 1.0))
    tight = float(bars.get("tight_radius_to_width", 1.5))
    bends, judged_bends = [], 0
    lengths, short = [], []
    min_lw = float(bars.get("min_length_to_width", 20))
    min_tp = float(bars.get("min_traverse_to_par", 0.5))
    min_s = _tiered(bars.get("min_traverse_s"), tier)
    min_s = float(min_s) if min_s is not None else None
    unmeasured_time = []
    for uid, layout in sorted(layouts["layouts"].items()):
        if not isinstance(layout, dict):
            continue
        width = layout.get("width")
        for position, segment in enumerate(layout.get("segments") or []):
            if not isinstance(segment, dict) or segment.get("t") != "turn":
                continue
            w = segment.get("w", width)
            r = segment.get("r")
            if not isinstance(w, (int, float)) or not isinstance(r, (int, float)) or w <= 0:
                continue
            judged_bends += 1
            ratio = round(float(r) / float(w), 2)
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
        if isinstance(width, (int, float)) and width > 0:
            entry["length_to_width"] = round(length / width, 1)
            if entry["length_to_width"] < min_lw:
                problems.append(f"length {entry['length_to_width']} x its width")
        speed = layout.get("top_speed")
        par = layout.get("par_s")
        if not isinstance(par, (int, float)):
            for source in (data_units.get(uid), designed.get(uid)):
                target = ((source or {}).get("parameters") or {}).get("time_target")
                if isinstance(target, (int, float)) and not isinstance(target, bool):
                    par = target
                    break
        if isinstance(speed, (int, float)) and speed > 0:
            traverse = length / speed
            entry["traverse_s"] = round(traverse, 2)
            if min_s is not None and traverse < min_s:
                problems.append(f"crossed in {entry['traverse_s']} s at top speed")
            if isinstance(par, (int, float)) and par > 0:
                entry["traverse_to_par"] = round(traverse / par, 2)
                if entry["traverse_to_par"] < min_tp:
                    problems.append(f"crossed at top speed in {entry['traverse_to_par']} x its "
                                    f"{par} s par")
        else:
            unmeasured_time.append(uid)
        lengths.append(entry)
        if problems:
            short.append({**entry, "problems": problems})
    checks = []
    expected = {"min_radius_to_width": hard, "tight_radius_to_width": tight}
    if not judged_bends:
        checks.append(_check("level.geometry", project, True,
                             f"{len(layouts['layouts'])} layouts declare no bend",
                             measured={"bends": 0}, expected=expected))
    else:
        first = bends[0] if bends else None
        checks.append(_check(
            "level.geometry", project, not bends,
            (f"all {judged_bends} bends are at least {hard} x the width, and every one under "
             f"{tight} x has a railed inner edge" if not bends else
             f"{len(bends)} of {judged_bends} bends cannot be driven: {first['unit']} segment "
             f"{first['segment']} turns {first['deg']} degrees at r {first['r']} on a width of "
             f"{first['width']} ({first['radius_to_width']} x), {first['problem']}"),
            measured={"bends": judged_bends, "failing": bends[:20]}, expected=expected))
    expected = {"min_length_to_width": min_lw, "min_traverse_to_par": min_tp,
                "min_traverse_s": min_s}
    if not lengths:
        checks.append(_unmeasured("level.unit_length", project, rules, tier,
                                  "layouts.json declares no layout", expected=expected))
    else:
        measured = {"units": lengths[:40], "short": [s["unit"] for s in short]}
        if unmeasured_time:
            measured["no_top_speed"] = unmeasured_time[:40]
        first = short[0] if short else None
        checks.append(_check(
            "level.unit_length", project, not short,
            (f"{len(lengths)} layouts are long enough for their width"
             + ("" if not unmeasured_time else
                f"; {len(unmeasured_time)} state no top_speed, so their crossing time is "
                "unmeasured")) if not short else
            f"{len(short)} of {len(lengths)} units are too short: {first['unit']} - "
            + "; ".join(first["problems"]),
            measured=measured, expected=expected))
    return checks

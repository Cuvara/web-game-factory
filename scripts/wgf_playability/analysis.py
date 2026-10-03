"""Judging what the playability bot recorded: the checks, against the design and the bars.

`judge(records, frames_dir, design, rules, experience_rules)` turns one viewport's bot records
(bot.spec.ts: first-session, act, win, lose) and its frames into checks. Every check states
what was measured and against which bar: the design's experience contract
(`build_spec.experience`), core/reference/experience-rules.yaml and
core/reference/visual-quality.yaml. Nothing here trusts the game's own account of what it
showed: acknowledgement is a frame difference, visibility is drawn bounds sampled every frame,
readability is the frame's own pixels.
"""

import json
import os
import re
import statistics

from wgflib import jsonschema_lite, paths

from wgf_assets.raster import RasterError, decode_png

__all__ = ["judge", "frame_stats", "changed_fraction", "objective_seen", "PROBE_SCHEMA"]

PROBE_SCHEMA = os.path.join(paths.ARTIFACTS, "shared", "play-probe.schema.json")
_WORD = re.compile(r"[a-z0-9]+")
_STOP = {"the", "a", "an", "and", "or", "to", "of", "in", "on", "you", "your", "as", "is",
         "it", "for", "every", "can", "how", "with", "before", "out", "at", "by", "be"}
_STEP = 4  # sample every 4th pixel in each direction: the bars are about the whole frame


def _luma(r, g, b):
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _sample(image):
    px, width = image.pixels, image.width
    return [_luma(px[i], px[i + 1], px[i + 2])
            for y in range(0, image.height, _STEP)
            for i in range(y * width * 4, (y + 1) * width * 4, 4 * _STEP)]


def frame_stats(path, lit_luminance=64):
    """(mean luminance, contrast as its standard deviation - both 0-255 - and the share of
    pixels at or above `lit_luminance`) of a PNG frame."""
    with open(path, "rb") as handle:
        values = _sample(decode_png(handle.read()))
    lit = sum(1 for v in values if v >= lit_luminance) / max(1, len(values))
    return (round(statistics.fmean(values), 2), round(statistics.pstdev(values), 2),
            round(lit, 4))


def changed_fraction(before_path, after_path, min_delta):
    """Share of sampled pixels whose luminance changed by at least `min_delta`."""
    with open(before_path, "rb") as a, open(after_path, "rb") as b:
        first, second = decode_png(a.read()), decode_png(b.read())
    if (first.width, first.height) != (second.width, second.height):
        return 1.0
    x, y = _sample(first), _sample(second)
    # Four decimals: never exponent notation, which the artifact hash refuses (wgflib.hashing).
    return round(sum(1 for p, q in zip(x, y) if abs(p - q) >= min_delta) / max(1, len(x)), 4)


def objective_seen(statement, texts):
    """Share of the objective's content words present in the text shown during play."""
    wanted = [w for w in _WORD.findall((statement or "").lower()) if w not in _STOP]
    if not wanted:
        return 0.0
    shown = set(_WORD.findall(" ".join(texts or []).lower()))
    return round(sum(1 for w in wanted if w in shown) / len(wanted), 3)


def _check(cid, project, ok, summary, required=True, measured=None, expected=None, frames=None,
           blocked=False):
    entry = {"id": cid, "project": project, "required": required, "summary": summary,
             "status": "BLOCKED" if blocked else ("PASS" if ok else ("FAIL" if required else "WARNING"))}
    if measured is not None:
        entry["measured"] = measured
    if expected is not None:
        entry["expected"] = expected
    if frames:
        entry["frames"] = list(frames)
    return entry


def judge(records, frames_dir, design, rules, experience_rules, project):
    """Checks (dicts per playability-report.schema.json) for one viewport."""
    ex = ((design or {}).get("build_spec") or {}).get("experience") or {}
    first = records.get("first-session") or {}
    act = records.get("act") or {}
    win = records.get("win") or {}
    lose = records.get("lose") or {}
    checks = []
    add = checks.append

    # The probe: present, and of the shape the schema states, with the contract's metrics.
    samples = [s for s in first.get("samples") or [] if isinstance(s, dict)]
    present = bool(samples) and not any("error" in s for s in samples)
    add(_check("probe.present", project, present,
               "window.__wgf__.play.snapshot() answered while the game started"
               if present else "no play probe: window.__wgf__.play.snapshot() is absent or "
               "threw, so the build cannot be played from outside",
               measured=(samples[0].get("error") if samples and "error" in samples[0] else None)))
    if not present:
        return checks
    with open(PROBE_SCHEMA, encoding="utf-8") as handle:
        validator = jsonschema_lite.Validator(json.load(handle))
    snapshots = samples + [x for a in act.get("acted") or [] for x in (a.get("before"), a.get("after"))
                           if isinstance(x, dict)]
    problems = []
    for snapshot in snapshots[:12]:
        problems += [str(p) for p in validator.iter_errors(snapshot)][:3]
    names = [n for n in ((ex.get("goal") or {}).get("metric"), (ex.get("win") or {}).get("metric"),
                         (ex.get("lose") or {}).get("metric")) if n]
    missing = sorted({n for n in names if n not in (samples[-1].get("metrics") or {})})
    add(_check("probe.valid", project, not problems and not missing,
               ("snapshots match the play-probe schema and carry the contract's metrics"
                if not problems and not missing else
                "; ".join(problems[:3] + ([f"metrics missing: {', '.join(missing)}"] if missing else []))),
               measured={"schema_problems": problems[:5], "missing_metrics": missing}))

    # Starting: playable within the budget, and the objective on screen.
    budget = ex.get("first_30s") or {}
    playable_bar = (budget.get("playable_s") or
                    (experience_rules.get("first_30s") or {}).get("max_playable_s", 10)) * 1000
    # The bot's own title-screen measurement ran inside the wall clock; a player spends none.
    playing = first.get("playingMs")
    observer = first.get("observerMs") or 0
    if playing is not None:
        playing = max(playing - observer, 0)
    add(_check("start.playable", project, playing is not None and playing <= playable_bar,
               (f"play began {playing} ms after navigation"
                + (f" ({observer} ms the bot spent measuring the title screen left out)"
                   if observer else "")) if playing is not None else
               "play never began", measured=playing, expected=f"<= {playable_bar} ms"))
    seen = objective_seen((ex.get("goal") or {}).get("statement"), first.get("texts"))
    add(_check("start.objective", project, seen >= 0.6,
               f"{int(seen * 100)}% of the objective's words were on screen in the first 3 s of play",
               measured=seen, expected=">= 0.6 of the words of build_spec.experience.goal.statement",
               frames=[f for f in first.get("frames") or [] if "1s" in f]))

    # No failure before the grace: the player had no input at all.
    lost_at = first.get("lostAtMs")
    idle = (rules.get("_idle_ms") or 10000)
    add(_check("idle.grace", project, lost_at is None,
               (f"with no input, play was lost after {lost_at} ms" if lost_at is not None else
                f"with no input for {idle} ms, play was not lost"),
               measured=lost_at, expected=f"not lost within {idle} ms without input"))

    # Every action visibly acknowledged.
    ack = rules.get("acknowledgement") or {}
    acted = act.get("acted") or []
    unacknowledged, measured = [], {}
    for entry in acted:
        before = os.path.join(frames_dir, f"act-{entry['action']}-before.png")
        after = os.path.join(frames_dir, f"act-{entry['action']}-after.png")
        try:
            fraction = changed_fraction(before, after, ack.get("min_pixel_delta", 24))
        except (OSError, RasterError):
            fraction = 0.0
        measured[entry["action"]] = fraction
        if fraction < ack.get("min_changed_fraction", 0.002):
            unacknowledged.append(entry["action"])
    add(_check("act.acknowledged", project, bool(acted) and not unacknowledged,
               ("no input was offered during play" if not acted else
                f"no visible change after {', '.join(unacknowledged)}" if unacknowledged else
                f"every action changed the frame: {measured}"),
               measured=measured, expected=f">= {ack.get('min_changed_fraction', 0.002)} of pixels"))

    # A win (or, with none, the objective's metric rising) under good play.
    series = [p for p in win.get("series") or [] if p.get("value") is not None]
    if "win" in ex:
        ok = win.get("reached") == "won"
        summary = (f"good play reached `won` after {win.get('inputs')} inputs" if ok else
                   f"good play did not reach `won` (ended {win.get('reached') or 'still playing'})")
    else:
        rising = len(series) > 1 and series[-1]["value"] > series[0]["value"]
        ok = rising
        summary = (f"good play raised {ex.get('goal', {}).get('metric')} from "
                   f"{series[0]['value'] if series else None} to {series[-1]['value'] if series else None}")
    add(_check("win.reachable", project, ok, summary,
               measured={"reached": win.get("reached"), "inputs": win.get("inputs")}))

    add(_check("lose.reachable", project, lose.get("reached") == "lost",
               f"bad play ended {lose.get('reached') or 'without reaching lost'}",
               measured=lose.get("reached"), frames=[f for f in lose.get("frames") or []]))

    restart = lose.get("restart") or {}
    retry_bar = ((budget.get("retry_s") or (experience_rules.get("first_30s") or {})
                  .get("max_retry_s", 3)) * 1000) + 1000
    goal_metric = (ex.get("goal") or {}).get("metric")
    reset = (restart.get("metrics") or {}).get(goal_metric) == ((lose.get("initial") or {}).get(goal_metric))
    ok = bool(restart.get("clicked")) and restart.get("playingMs") is not None \
        and restart["playingMs"] <= retry_bar and reset
    add(_check("restart.works", project, ok,
               (f"retry ({restart.get('clicked')}) returned to play in {restart.get('playingMs')} ms"
                + ("" if reset else f"; {goal_metric} did not reset")) if restart.get("clicked") else
               "no retry was offered after play ended",
               measured=restart.get("playingMs"), expected=f"<= {retry_bar} ms, {goal_metric} reset",
               blocked=lose.get("reached") != "lost" and not restart))

    # What the player must see is drawn, on screen, and large enough.
    ent = rules.get("entities") or {}
    readable = set(ent.get("readable_roles") or [])
    sampled = win.get("sampled") or {}
    frames = sampled.get("frames") or []
    vw, vh = (sampled.get("viewport") or [1, 1])
    area = float(vw * vh) or 1.0
    # Size is judged per entity at its largest on screen - a wall rushing at the player is
    # read up close, not where it spawned on the horizon - and per role as the median of
    # those: most of a role's entities must, at some point, be drawn large enough to read.
    # Only entities seen through their whole time on screen count (gone before the sample
    # ended): one still on the horizon when sampling stopped never had its close-up. A role
    # none of whose entities left (a static attacker) is judged on all of them.
    by_role, runs, largest, last_seen = {}, {}, {}, {}
    for index, entities in enumerate(frames):
        for sample in entities:
            # [id, role, visible, x, y, w, h] and, from bots that record them, asset, render.
            eid, role, visible, x, y, w, h = sample[:7]
            if role not in readable:
                continue
            last_seen[(role, eid)] = index
            on = visible and x + w > 0 and y + h > 0 and x < vw and y < vh
            stats = by_role.setdefault(role, {"samples": 0, "visible": 0, "areas": []})
            stats["samples"] += 1
            stats["visible"] += 1 if on else 0
            if on:
                key = (role, eid)
                largest[key] = max(largest.get(key, 0.0), w * h / area)
            if role == "projectile":
                # In flight: drawn, and moved since the previous frame. A ball that sits at
                # its origin and is snapped back before it travels is never seen to fly.
                run = runs.setdefault(eid, {"current": 0, "longest": 0, "at": None})
                moved = run["at"] is not None and abs(x - run["at"][0]) + abs(y - run["at"][1]) > 1.5
                run["current"] = run["current"] + 1 if on and moved else 0
                run["longest"] = max(run["longest"], run["current"])
                run["at"] = (x, y) if on else None
    final = len(frames) - 1
    for role in by_role:
        sizes = {k: v for k, v in largest.items() if k[0] == role}
        left = [v for k, v in sizes.items() if last_seen[k] < final]
        by_role[role]["areas"] = left or list(sizes.values())
    small, hidden = [], []
    for role, stats in by_role.items():
        share = stats["visible"] / max(1, stats["samples"])
        size = statistics.median(stats["areas"]) if stats["areas"] else 0.0
        stats.update(visible_share=round(share, 3), median_area=round(size, 4))
        del stats["areas"]
        if share < ent.get("min_visible_share", 0.5) and role != "projectile":
            hidden.append(role)
        if size < ent.get("min_area_fraction", 0.002) and role != "projectile":
            small.append(role)
    shown = bool(by_role)
    add(_check("entities.visible", project, shown and not small and not hidden,
               ("no entity of a readable role (" + ", ".join(sorted(readable)) + ") was reported"
                if not shown else
                "; ".join(([f"too small to read: {', '.join(small)}"] if small else [])
                          + ([f"not visible: {', '.join(hidden)}"] if hidden else []))
                or "player, threats and goals are drawn on screen and large enough"),
               measured=by_role, expected={"min_area_fraction": ent.get("min_area_fraction"),
                                           "min_visible_share": ent.get("min_visible_share")}))
    if "projectile" in by_role:
        longest = max((r["longest"] for r in runs.values()), default=0)
        add(_check("entities.projectile", project, longest >= ent.get("min_projectile_frames", 3),
                   f"a projectile was seen in flight for at most {longest} consecutive frames",
                   measured=longest, expected=f">= {ent.get('min_projectile_frames', 3)} frames"))

    # Frames a player can read.
    bars = rules.get("frames") or {}
    stats_by_frame = {}
    for fid in ("first-session-1s", "play-2s"):
        path = os.path.join(frames_dir, f"{fid}.png")
        if os.path.isfile(path):
            stats_by_frame[fid] = frame_stats(path, bars.get("lit_luminance", 64))
    dark = [f for f, (_m, _c, lit) in stats_by_frame.items() if lit < bars.get("min_lit_share", 0.015)]
    washed = [f for f, (mean, _c, _l) in stats_by_frame.items()
              if mean > bars.get("max_mean_luminance", 225)]
    flat = [f for f, (_m, contrast, _l) in stats_by_frame.items() if contrast < bars.get("min_contrast", 18)]
    add(_check("frames.readable", project, bool(stats_by_frame) and not dark and not washed and not flat,
               ("no frame was captured during play" if not stats_by_frame else
                "; ".join([f"{f}: {round(stats_by_frame[f][2] * 100, 2)}% of pixels lit" for f in dark]
                          + [f"{f}: mean luminance {stats_by_frame[f][0]}" for f in washed]
                          + [f"{f}: contrast {stats_by_frame[f][1]}" for f in flat])
                or "frames during play are lit and have contrast"),
               measured={f: {"mean_luminance": m, "contrast": c, "lit_share": lit}
                         for f, (m, c, lit) in stats_by_frame.items()},
               expected={"lit_share": f">= {bars.get('min_lit_share')} at luminance >= {bars.get('lit_luminance')}",
                         "mean_luminance": f"<= {bars.get('max_mean_luminance')}",
                         "contrast": f">= {bars.get('min_contrast')}"},
               frames=list(stats_by_frame)))

    errors = sorted({e for r in (first, act, win, lose) for e in r.get("errors") or []})
    add(_check("page.errors", project, not errors,
               "no page errors" if not errors else f"{len(errors)} page error(s): {errors[0]}",
               measured=errors[:5]))
    return checks

"""Judging what the playability bot recorded: the checks, against the design and the bars.

`judge(records, frames_dir, design, rules, experience_rules, project, qa)` turns one viewport's
bot records (bot.spec.ts: first-session, act, win, lose, pause, traverse, persist, session,
ramp) and its frames into checks. Every check states what was measured and against which bar:
the design's experience contract (`build_spec.experience`), core/reference/experience-rules.yaml,
core/reference/visual-quality.yaml, and - for the content, difficulty and depth checks -
core/reference/design-depth.yaml's `playability` block merged with the genre family's `qa`
block (core/reference/genre-models.yaml, through wgflib.genre_models). No bar is ever written
here. Nothing here trusts the game's own account of what it showed: acknowledgement is a frame
difference, visibility is drawn bounds sampled every frame, readability is the frame's own
pixels, and a unit was reached only if the probe said so while the bot played into it.

A check is SKIPPED only when the design does not claim what it measures - no content contract,
generated content where a unit sequence would be traversed, no declared difficulty axes, nothing
persisted at the mvp tier. A skip is never a pass: the step lists it in `skipped_checks` and
names it in its summary. A thing the design does claim and the probe cannot show is a FAIL.
"""

import json
import math
import os
import re
import statistics

from wgflib import build_scope, genre_models, jsonschema_lite, paths

from wgf_assets.raster import RasterError, decode_png

__all__ = ["judge", "frame_stats", "changed_fraction", "objective_seen", "PROBE_SCHEMA",
           "content_units", "persisted_metrics", "persisted_measures", "UNIT_REACHED",
           "time_ramp", "thirds_of", "environment_health", "EVIDENCE", "RETRIED_RECORDS",
           "ENVIRONMENT_DEGRADED", "SAMPLE_CUT"]

PROBE_SCHEMA = os.path.join(paths.ARTIFACTS, "shared", "play-probe.schema.json")
_WORD = re.compile(r"[a-z0-9]+")
_STOP = {"the", "a", "an", "and", "or", "to", "of", "in", "on", "you", "your", "as", "is",
         "it", "for", "every", "can", "how", "with", "before", "out", "at", "by", "be"}
_STEP = 4  # sample every 4th pixel in each direction: the bars are about the whole frame
# The traverse stop reasons that cut the traversal short rather than let it end: the bot ran
# out of units it was asked for, or out of window. The unit in play when it stopped was not
# played to its end, so nothing about that unit's completion was decided. (bot.spec.ts also
# stops on `lost twice` and `play never began`, which are ends, not cuts.)
_CUT_SHORT = ("max units", "window")


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
           blocked=False, skipped=False, truncated=False):
    """One check. `skipped` says the design does not claim what the check measures, so there
    was nothing to measure: never a pass, and listed in the report's `skipped_checks`.
    `truncated` says the bot's window for it was cut to fit the time budget."""
    status = ("SKIPPED" if skipped else "BLOCKED" if blocked else
              "PASS" if ok else ("FAIL" if required else "WARNING"))
    entry = {"id": cid, "project": project, "required": required, "summary": summary,
             "status": status}
    if truncated:
        measured = (dict(measured) if isinstance(measured, dict)
                    else ({} if measured is None else {"value": measured}))
        measured["truncated"] = True
    if measured is not None:
        entry["measured"] = measured
    if expected is not None:
        entry["expected"] = expected
    if frames:
        entry["frames"] = list(frames)
    return entry


# -- the content contract: what the design says the player meets, and in what order ---------

# The design's content units, read the one way every step reads them (wgflib.genre_models).
content_units = genre_models.units_of


def _designed(units, played):
    """The designed unit a traversed one is, by id, else by index."""
    return next((u for u in units if u.get("id") == played.get("unit_id")
                 or u.get("index") == played.get("index")), None)


def _share(part, whole):
    return round(part / whole, 3) if whole else 0.0


def _kinds_reported(traverse):
    """Every entity kind the probe reported during the traversal. Empty: the build reports
    none - `entities[].kind` is optional in the probe, so that is unmeasured, not a defect."""
    seen = set()
    for row in traverse.get("snapshots") or []:
        seen.update(row.get("kinds") or [])
    for unit in traverse.get("per_unit") or []:
        seen.update(unit.get("kinds") or [])
    return seen


def _skips(project, ids, reason):
    return [_check(cid, project, False, reason, skipped=True) for cid in ids]


def _cut_unit(traverse, played, truncated=False):
    """The traversed unit the traverse stopped inside, cut short, or None: the last one, when
    the traverse stopped short (_CUT_SHORT, or a window the budget cut) and the bot neither saw
    it completed nor entered a later unit. Whatever it had not shown yet by then was not seen."""
    if not played or not (traverse.get("stopped") in _CUT_SHORT or truncated):
        return None
    last = played[-1]
    left = any(isinstance(t, dict) and t.get("from") == last.get("index")
               for t in traverse.get("transitions") or [])
    return None if last.get("won") or left else last


# -- the measurement's own validity: the host the bot played on ------------------------------

# Why a check was not judged although its recording was made: every attempt of the recording
# ran on a degraded host (visual-quality.yaml `environment`), or the unit a negative rests on
# was cut short by the traverse (`sample`). Either is `measured.unmeasured`; never a pass.
ENVIRONMENT_DEGRADED = "environment-degraded"
SAMPLE_CUT = "sample-cut"

# The recordings each timing-sensitive check is read from. These are the recordings the bot
# makes again when the host was degraded while it made them (bot.spec.ts `finish`): a stall
# turns a fast start slow, a winning oracle into a losing one, and a traverse short.
EVIDENCE = {
    "start.playable": ("first-session",),
    "start.objective": ("first-session",),
    "idle.grace": ("first-session",),
    "win.reachable": ("win",),
    "entities.visible": ("win",),
    "entities.projectile": ("win",),
    "lose.reachable": ("lose",),
    "restart.works": ("lose",),
    "content.units_reachable": ("traverse",),
    "content.objective_shown": ("traverse",),
    "content.win_lose_per_unit": ("traverse", "lose"),
    "content.variety": ("traverse",),
    "difficulty.axes_progress": ("traverse",),
}
RETRIED_RECORDS = tuple(sorted({r for records in EVIDENCE.values() for r in records}))


def environment_health(health, bars):
    """(degraded, reasons) of one attempt's `health` (bot.spec.ts) against
    visual-quality.yaml `environment`: None when the attempt recorded no health (a record made
    before 1.1.0), so nothing is claimed about its host. Only what the game cannot cause is
    read: the bot's own timer, the page's worker timer, the local server's wait. The page's
    frame gaps are the game's own and never make a host degraded."""
    if not isinstance(health, dict) or not bars:
        return None, []
    reasons, read = [], False
    longest, share = bars.get("max_stall_ms"), bars.get("max_stalled_share")
    for name in ("bot", "worker"):
        beat = health.get(name)
        if not isinstance(beat, dict):
            continue
        read = True
        lag, stalled, elapsed = (beat.get("max_lag_ms"), beat.get("stalled_ms"),
                                 beat.get("elapsed_ms"))
        if isinstance(lag, (int, float)) and isinstance(longest, (int, float)) and lag >= longest:
            reasons.append(f"the {name} timer stalled {round(lag)} ms at once (>= {longest})")
        if (isinstance(stalled, (int, float)) and isinstance(elapsed, (int, float)) and elapsed > 0
                and isinstance(share, (int, float)) and stalled / elapsed >= share):
            reasons.append(f"the {name} timer lost {round(stalled)} ms of {round(elapsed)} ms to "
                           f"stalls (>= {share})")
    wait = (health.get("nav") or {}).get("server_wait_max_ms")
    bar = bars.get("max_server_wait_ms")
    if isinstance(wait, (int, float)) and isinstance(bar, (int, float)) and wait >= bar:
        reasons.append(f"the local server took {round(wait)} ms to start answering a request "
                       f"(>= {bar})")
    # Nothing the game cannot cause was read: nothing is claimed about the host either way.
    if not read and not isinstance(wait, (int, float)):
        return None, []
    return bool(reasons), reasons


def _attempts(record, bars):
    """Every attempt the bot made of a recording, re-judged here: [{attempt, degraded,
    reasons}], the last being the one the record holds. Empty for a record without health."""
    out = []
    for entry in record.get("attempts") or []:
        if isinstance(entry, dict):
            degraded, reasons = environment_health(entry.get("health"), bars)
            out.append({"attempt": entry.get("attempt"), "degraded": degraded, "reasons": reasons})
    if not out and isinstance(record.get("health"), dict):
        degraded, reasons = environment_health(record["health"], bars)
        out.append({"attempt": 1, "degraded": degraded, "reasons": reasons})
    return out


def _environment(checks, records, bars, held):
    """Each timing-sensitive check, as the host its recordings were made on allows: judged
    as it is when the attempt it reads was healthy (with the degraded attempts before it in
    `measured.environment`); unmeasured - `environment-degraded`, never a pass - when every
    attempt of a recording it reads was degraded: BLOCKED where an unmeasured check is not
    passed (`held`, quality-policy.yaml skipped_checks), else a WARNING. A record without
    health (made before visual-quality.yaml 1.1.0) is judged as it always was."""
    for check in checks:
        names = [n for n in EVIDENCE.get(check["id"], ()) if isinstance(records.get(n), dict)]
        if not names or check["status"] == "SKIPPED":
            continue
        seen, bad = {}, []
        for name in names:
            attempts = _attempts(records[name], bars)
            if len(attempts) > 1 or any(a["degraded"] for a in attempts):
                seen[name] = attempts
            if attempts and attempts[-1]["degraded"]:
                bad.append(name)
        if not seen:
            continue
        measured = check.get("measured")
        measured = (dict(measured) if isinstance(measured, dict)
                    else {} if measured is None else {"value": measured})
        measured["environment"] = seen
        check["measured"] = measured
        if not bad:
            continue
        why = (held or {}).get(check["id"])
        reasons = sorted({r for n in bad for r in seen[n][-1]["reasons"]})
        measured.update(unmeasured=ENVIRONMENT_DEGRADED, judged_as=check["status"])
        check.update(
            status="BLOCKED" if why else "WARNING", required=bool(why),
            summary=(f"not judged: the host was degraded on every attempt of the "
                     f"{', '.join(bad)} recording ({len(seen[bad[0]])} attempt(s); "
                     f"{'; '.join(reasons[:3])}); what it read: {check['summary']}"
                     + (f"; {why}" if why else "")))
    return checks


# -- the time ramp: which run promises one ---------------------------------------------------

def time_ramp(design, qa, tiers=None):
    """Where the design promises a time ramp - the longer one run lasts, the more it asks -
    and so the run the bot reads the oracle's input rate on; None when it promises none.

    Only a family whose `qa` states `endless_window_s` promises a time ramp. The run is the
    session itself when the play is endless (`genre.ending` `endless`, or content that is not
    authored): `{"run": "session"}`. Otherwise it is a run of a mode the design includes - a
    feature whose `catalogue` (or id) is one of design-depth.yaml
    `playability.ramp.mode_features`, not deferred or cut, at a tier of `tiers` (the design
    tiers this build carries; mvp and post-mvp when None): `{"run": "mode", "mode": ...,
    "feature": ...}`, which the bot enters through the probe's `play.mode`. An authored-unit
    design with no such mode ramps between its units, which difficulty.axes_progress judges:
    None.
    """
    design = design or {}
    if not isinstance(((qa or {}).get("genre") or {}).get("endless_window_s"), (int, float)):
        return None
    _content, mode, _units = content_units(design)
    if (design.get("genre") or {}).get("ending") == "endless" or mode != "authored":
        return {"run": "session"}
    bars = (qa or {}).get("ramp") or {}
    wanted = set(bars.get("mode_features") or [])
    built = set(tiers) if tiers is not None else {"mvp", "post-mvp"}
    if not isinstance(bars.get("mode"), str):
        return None
    for feature in design.get("features") or []:
        if not isinstance(feature, dict):
            continue
        if not ({feature.get("catalogue"), feature.get("id")} & wanted):
            continue
        decision = (feature.get("evaluation") or {}).get("decision")
        if (feature.get("tier") or "mvp") in built and decision in (None, "include"):
            return {"run": "mode", "mode": bars["mode"], "feature": feature.get("id")}
    return None


def thirds_of(run):
    """The oracle's inputs per third of one recorded run, or None when it has none."""
    thirds = (run or {}).get("oracle_inputs_per_third") or []
    return thirds if len(thirds) == 3 else None


def _ended_read(snapshot, entry):
    """A traverse snapshot shows its unit ended: `won`, or progress risen to its target."""
    if snapshot.get("state") == "won":
        return True
    progress = snapshot.get("progress") or {}
    target, value = progress.get("target"), progress.get("value")
    if not isinstance(target, (int, float)) or target <= 0 or not isinstance(value, (int, float)):
        return False
    return value >= target and (entry is None or entry < target)


def transition_timing(transition, snapshots=()):
    """How long the GAME took to move on from a finished unit, apart from the bot's latency.

    The bot reads the game by polling, so the game moved on somewhere between the last read
    that still showed the finished unit and the first read that showed the next one. What is
    the game's: the time it sat ended before it offered an advance (`unoffered_ms` - the
    unit's first ended read), and the time it stayed in the finished unit after the bot's
    first input was delivered (`last_old_ms` - `acted_ms`), or after the end when the game
    advances by itself. What is the bot's: its reaction and click (`offered_ms` ->
    `acted_ms`), its own pause, and the round-trip of the read that saw the next unit.
    `game_ms` is the lower bound the game is judged on - the game was observed not to have
    moved on for that long; `game_max_ms` the upper bound (the whole interval less the bot's
    reaction and click). The end is the first `won` read, else the first at the progress
    target: a target met before the game declared `won` ended at `won`. A record from a bot
    before these fields (only `since_end_ms`) is timed from its snapshots: from the unit's
    first ended read to its last read, which still includes the bot's clicks in between;
    without snapshots covering the transition, from `since_end_ms` as recorded.
    """
    at = transition.get("at_ms")
    ended = transition.get("ended_ms")
    if isinstance(ended, (int, float)) and isinstance(at, (int, float)):
        unoffered, offered = transition.get("unoffered_ms"), transition.get("offered_ms")
        acted, last = transition.get("acted_ms"), transition.get("last_old_ms")
        offer_wait = max(0, unoffered - ended) if isinstance(unoffered, (int, float)) else 0
        since = acted if isinstance(acted, (int, float)) else ended
        move_wait = max(0, last - since) if isinstance(last, (int, float)) else 0
        bot = (acted - offered if isinstance(acted, (int, float)) and isinstance(offered, (int, float))
               else 0)
        return {"game_ms": offer_wait + move_wait, "game_max_ms": max(0, at - ended - bot),
                "basis": "recorder"}
    frm = transition.get("from")
    if isinstance(at, (int, float)) and snapshots:
        reads = [r for r in snapshots if isinstance(r, dict) and isinstance(r.get("ms"), (int, float))]
        if any(r["ms"] == at and r.get("unit_index") == transition.get("to") for r in reads):
            # The finished unit's reads: the run of reads in it that ends at this transition.
            stay = []
            for read in reversed([r for r in reads if r["ms"] < at]):
                if read.get("unit_index") != frm:
                    break
                stay.append(read)
            stay.reverse()
            if stay:
                entry = (stay[0].get("progress") or {}).get("value")
                won = transition.get("how") == "won"
                first = next((r["ms"] for r in stay
                              if (r.get("state") == "won" if won else _ended_read(r, entry))), None)
                if first is not None:
                    return {"game_ms": max(0, stay[-1]["ms"] - first), "game_max_ms": at - first,
                            "basis": "snapshots"}
    raw = transition.get("since_end_ms")
    return {"game_ms": raw, "game_max_ms": raw, "basis": "since_end_ms"}


RAMP_BARS = ("samples", "noise_z", "min_inputs_per_third", "stall_max_s")


def ramp_verdict(samples, bars):
    """The time ramp judged on the bot's samples (design-depth.yaml `playability.ramp`, 1.4.0):
    a dict with `verdict` - `pass`, `fail` or `unmeasured` - its `reason`, and what it was
    read from (`per_sample`, `pooled`, `band`, `stalled`, `clean`, `planned`).

    Each sample is one fresh run the oracle played (bot.spec.ts `playSample`): its
    `oracle_inputs_per_third` and its `longest_idle_ms` - the longest stretch in play with no
    oracle input and no progress. A sample whose idle stretch is over `stall_max_s` stalled:
    that is depth.stall's finding, and its counts, which the stall deflates, are left out.
    The clean samples' thirds are pooled. With n = first + last, a difference within
    `noise_z` x sqrt(n) is noise (under an unchanging rate the split is Binomial(n, 1/2)):

      fail        one clean sample's own fall beyond its own band (its first third holding at
                  least `min_inputs_per_third`), or the pooled fall beyond the pooled band -
                  decided on whatever was sampled, however few
      unmeasured  no clean sample, the pooled first thirds under `min_inputs_per_third`, fewer
                  clean samples than `samples`, or a pooled difference inside the band
      pass        `samples` clean samples whose pooled last thirds exceed the first by more
                  than the band

    A rate that does not change never passes: its difference stays inside the band. Never
    defaulted in code: a bar the file does not state leaves the ramp unmeasured.
    """
    missing = [k for k in RAMP_BARS if not isinstance(bars.get(k), (int, float))]
    rows = []
    for number, sample in enumerate(samples or [], start=1):
        if not isinstance(sample, dict):
            continue
        idle = sample.get("longest_idle_ms")
        rows.append({"sample": number, "duration_ms": sample.get("duration_ms"),
                     "thirds": thirds_of(sample), "longest_idle_ms": idle,
                     "idle_at_ms": sample.get("idle_at_ms"), "ended": sample.get("ended")})
    out = {"per_sample": rows, "planned": bars.get("samples")}
    if missing:
        return dict(out, verdict="unmeasured",
                    reason="design-depth.yaml playability.ramp states no "
                           + ", ".join(missing))
    z, minimum, planned = bars["noise_z"], bars["min_inputs_per_third"], int(bars["samples"])
    stall_ms = bars["stall_max_s"] * 1000
    for row in rows:
        row["stalled"] = (isinstance(row["longest_idle_ms"], (int, float))
                          and row["longest_idle_ms"] > stall_ms)
    stalled = [r["sample"] for r in rows if r["stalled"]]
    clean = [r for r in rows if not r["stalled"] and r["thirds"]]
    pooled = [sum(r["thirds"][i] for r in clean) for i in range(3)]
    first, last = pooled[0], pooled[2]
    band = z * math.sqrt(first + last)
    out.update(stalled=stalled, clean=len(clean), pooled=pooled, band=round(band, 2))
    falls = [r for r in clean if r["thirds"][0] >= minimum
             and r["thirds"][0] - r["thirds"][2] > z * math.sqrt(r["thirds"][0] + r["thirds"][2])]
    left_out = (f" ({len(stalled)} stalled sample(s) left out: depth.stall)" if stalled else "")
    if falls:
        row = falls[0]
        return dict(out, verdict="fail",
                    reason=(f"sample {row['sample']}: the oracle acted {row['thirds'][2]} times "
                            f"in the last third and {row['thirds'][0]} in the first "
                            f"{row['thirds']}, a fall beyond the noise band of "
                            f"{z * math.sqrt(row['thirds'][0] + row['thirds'][2]):.1f}: the "
                            "game asks for less as it goes"))
    if not clean:
        return dict(out, verdict="unmeasured",
                    reason=("every sample stalled" + left_out if stalled
                            else "no sample was played to read the input rate on"))
    if first < minimum:
        return dict(out, verdict="unmeasured",
                    reason=(f"the first thirds of {len(clean)} sample(s) hold {first} oracle "
                            f"input(s), fewer than the {minimum} a rate is compared on"
                            + left_out))
    if first - last > band:
        return dict(out, verdict="fail",
                    reason=(f"over {len(clean)} sample(s) the oracle acted {last} times in the "
                            f"last thirds and {first} in the first {pooled}, a fall beyond the "
                            f"noise band of {band:.1f}: the game asks for less as it goes"
                            + left_out))
    if len(clean) < planned:
        return dict(out, verdict="unmeasured",
                    reason=(f"{len(clean)} clean sample(s) of the {planned} the ramp is judged "
                            f"on" + left_out))
    if last - first > band:
        return dict(out, verdict="pass",
                    reason=(f"over {len(clean)} samples the oracle acted {last} times in the "
                            f"last thirds and {first} in the first {pooled}, a rise beyond the "
                            f"noise band of {band:.1f}"))
    return dict(out, verdict="unmeasured",
                reason=(f"over {len(clean)} samples the last thirds hold {last} oracle inputs "
                        f"and the first {first} {pooled}: a difference inside the noise band "
                        f"of {band:.1f} ({z} x sqrt {first + last}), so neither a ramp nor a "
                        "fall is shown" + left_out))


def _content_checks(ctx):
    """content.units_reachable, content.objective_shown, content.win_lose_per_unit."""
    project, units, mode = ctx["project"], ctx["units"], ctx["mode"]
    built = ctx["built_units"]
    bars = ctx["qa"].get("content") or {}
    ids = ("content.units_reachable", "content.objective_shown", "content.win_lose_per_unit")
    if ctx["content"] is None:
        return _skips(project, ids,
                      "the design states no content units (build_spec.content), so there is "
                      "no unit sequence to play through")
    if mode != "authored":
        return _skips(project, ids,
                      f"content is generated ({mode or 'no mode stated'}): the units listed are "
                      "representative, not a sequence the build traverses in order")
    traverse = ctx["records"].get("traverse") or {}
    played = [u for u in traverse.get("per_unit") or [] if isinstance(u, dict)]
    transitions = [t for t in traverse.get("transitions") or [] if isinstance(t, dict)]
    reached = [u.get("index") for u in played if u.get("index")]
    want = min(len(units), int(bars.get("min_units_traversed") or 1))
    order = list(range(1, want + 1))
    grace = bars.get("transition_grace_ms")
    in_order = reached[:want] == order
    # Earned: the unit left was finished (`won` or its progress target) before the next was
    # entered, and the GAME moved on within the grace - the bot's own reaction, click and
    # polling are not the game's (transition_timing).
    snapshots = traverse.get("snapshots") or []
    timed = [{**t, **transition_timing(t, snapshots)}
             for t in transitions]
    unearned = []
    for t in timed:
        if (t.get("to") or 0) > want:
            continue
        if t.get("how") not in ("won", "progress"):
            unearned.append(f"{t.get('from')}->{t.get('to')} (the unit left was {t.get('how')}, "
                            "not won or at its progress target)")
        elif t.get("game_ms") is None or t["game_ms"] > grace:
            unearned.append(f"{t.get('from')}->{t.get('to')} ({t.get('how')}, the game moved on "
                            f"{t.get('game_ms')} ms after it ended, {t.get('basis')}; raw "
                            f"{t.get('since_end_ms')} ms with the bot's latency)")
    out = [_check("content.units_reachable", project, in_order and not unearned,
                  (f"units {order} were played in the design's order, each entered within "
                   f"{grace} ms of the game finishing the previous one" if in_order and not unearned else
                   f"units reached: {reached or 'none'}; the design's first {want} are {order}"
                   if not in_order else
                   "a unit was entered without the previous one being completed: "
                   + "; ".join(unearned[:3])),
                  measured={"units_reached": reached, "transitions": timed[:12],
                            "stopped": traverse.get("stopped")},
                  expected=f"units {order} in order, each entered after the previous one reached "
                           f"`won` or its progress target, the game moving on within {grace} ms "
                           f"(game_ms; the bot's reaction and click excluded)",
                  frames=[f"unit-{i}-1s" for i in order], truncated=ctx["truncated"].get("traverse"))]

    bar = bars.get("objective_min_share")
    shares = {}
    for unit in played:
        designed = _designed(built, unit)
        if designed:
            shares[designed.get("id")] = objective_seen(designed.get("objective"),
                                                        unit.get("objective_texts"))
    unseen = sorted(uid for uid, value in shares.items() if value < bar)
    out.append(_check("content.objective_shown", project, bool(shares) and not unseen,
                      ("no unit was played, so no objective could be read" if not shares else
                       f"the objective was not on screen in: {', '.join(unseen)}" if unseen else
                       f"every played unit showed its objective: {shares}"),
                      measured=shares,
                      expected=f">= {bar} of the words of each unit's `objective`"))

    lose = ctx["records"].get("lose") or {}
    # A family whose success is a time target (qa.time_target_axis): a unit is only completed
    # when the time the probe reports is inside the target the unit's own parameters state.
    timed = (ctx["qa"].get("genre") or {}).get("time_target_axis")
    # A unit is judged on completion only once the traverse LEFT it: a later unit was entered,
    # it was won, or it failed. The bot is asked for a bounded number of units inside a bounded
    # window, so the unit in play when it stopped is normally mid-attempt - counting that as
    # "never completed" judges the bot's budget, not the build.
    cut = traverse.get("stopped") in _CUT_SHORT or bool(ctx["truncated"].get("traverse"))
    unwon, in_progress = [], []
    for unit in played:
        designed = _designed(built, unit)
        if not designed or not designed.get("success"):
            continue
        advanced = any(t.get("from") == unit.get("index") for t in transitions)
        if not (unit.get("won") or advanced):
            if cut and not unit.get("lost"):
                in_progress.append(designed.get("id"))
                continue
            unwon.append(designed.get("id"))
            continue
        target = (designed.get("parameters") or {}).get("time_target") if timed else None
        if isinstance(target, (int, float)):
            took = (unit.get("metrics") or {}).get("time")
            if not isinstance(took, (int, float)) or took > target:
                unwon.append(f"{designed.get('id')} (time {took}, target {target})")
    failing = {u.get("id") for u in built if u.get("failure")}
    lost_in = ((lose.get("contentAtEnd") or lose.get("initialContent") or {}) or {}).get("unit_id")
    lost_ok = lose.get("reached") == "lost" and (lost_in in failing if failing else True)
    still = (f"; still in play when the traverse stopped ({traverse.get('stopped')}), so its "
             f"completion was not judged: {', '.join(in_progress)}" if in_progress else "")
    out.append(_check("content.win_lose_per_unit", project, not unwon and lost_ok,
                      ("; ".join(
                          ([f"played but never completed: {', '.join(unwon)}"] if unwon else [])
                          + ([] if lost_ok else
                             [f"bad play ended {lose.get('reached') or 'without a loss'}"
                              f" in unit {lost_in or 'the probe did not say which'}; the design "
                              f"states a failure for {', '.join(sorted(failing)) or 'no unit'}"]))
                       or "every unit the traverse left was completed, and bad play failed a "
                          "unit that states a failure") + still,
                      measured={"not_completed": unwon, "in_progress": in_progress,
                                "stopped": traverse.get("stopped"), "lost_in_unit": lost_in,
                                "lose_reached": lose.get("reached")}))
    return out


def _designed_id(units, played):
    return (_designed(units, played) or {}).get("id") or played.get("unit_id") or played.get("asked")


def _off_design(design, units, played, axes, tolerance, seen=()):
    """Every `<unit> <axis>: the build reports X, the design states Y` past `tolerance`, for
    the played units (traverse `per_unit`, or survey visits) not already in `seen`."""
    off = []
    for unit in played:
        designed = _designed(units, unit) or {}
        if designed.get("id") in seen:
            continue
        for axis in axes:
            want = (designed.get("difficulty") or {}).get(axis["id"])
            got = (unit.get("difficulty") or {}).get(axis["id"])
            if not (isinstance(want, (int, float)) and isinstance(got, (int, float))):
                continue
            if abs(got - want) > tolerance:
                off.append(f"{designed.get('id') or unit.get('unit_id')} "
                           f"{axis['id']}: the build reports {got}, the design states "
                           f"{want}")
    return off


def _designed_series(units, played, axis):
    """The design's own values on `axis` for the played units, in play order; None when the
    design states none for one of them."""
    series = [((_designed(units, u) or {}).get("difficulty") or {}).get(axis) for u in played]
    if not series or not all(isinstance(v, (int, float)) for v in series):
        return None
    return series


def _held(axis, values, rise, dip):
    """The series holds or dips for relief on at least `rise` of its steps."""
    pairs = list(zip(values, values[1:]))
    held = sum(1 for a, b in pairs if b >= a or (a - b) <= dip * abs(a or 1))
    share = _share(held, len(pairs))
    if share < rise:
        return [f"{axis}: only {share} of its steps held or dipped for relief"]
    return []


def _release_curve(ctx):
    """Above tier mvp, the release units the design ships and the survey's visits to them -
    the curve content.axes_monotone_with_relief judges the design on - else None.

    The tier is the design's own (wgf_design.content.quality_tier), read the way the design
    rule reads it: above `mvp` and with units past the prototype, escalation is a property of
    every release unit in order. At tier mvp - or with nothing past the prototype - None, and
    the MVP traversed is what ships."""
    from wgf_design.content import QUALITY_TIERS, quality_tier, units_of

    tier = quality_tier(ctx["design"], None)[0]
    shipped = [u for u in units_of(ctx["design"]) if u.get("tier") != "optional"]
    if tier not in QUALITY_TIERS[1:] or len(shipped) <= len(ctx["units"]):
        return None
    survey = ctx["records"].get("survey") or {}
    visits = [dict(v, unit_id=v.get("asked")) for v in survey.get("visits") or []
              if isinstance(v, dict) and v.get("entered")]
    return {"tier": tier, "units": shipped, "visits": visits,
            "surveyed": bool(survey.get("applies")), "reason": survey.get("reason")}


def _release_escalation(release, present, measured, rise, dip):
    """Every escalating axis the build reports rises over the release units, in the design's
    order, when the survey entered every one of them; else the release curve is reported as
    not judged here, never as passed (content-sufficiency counts what the survey reached)."""
    by_id = {v.get("asked"): v for v in release["visits"]}
    missing = [u.get("id") for u in release["units"] if u.get("id") not in by_id]
    if missing:
        measured["release_partial"] = {
            "units": len(release["units"]), "entered": len(release["units"]) - len(missing),
            "reason": (release["reason"] or "no survey ran") if not release["surveyed"] else
            f"the survey did not enter {', '.join(str(m) for m in missing[:4])}"}
        return []
    problems, series = [], {}
    for axis in present:
        values = [(by_id[u.get("id")].get("difficulty") or {}).get(axis["id"])
                  for u in release["units"]]
        values = [v for v in values if isinstance(v, (int, float))]
        series[axis["id"]] = values
        if len(values) < 2:
            continue
        problems += [f"release {p}" for p in _held(axis["id"], values, rise, dip)]
        if values[-1] <= values[0]:
            problems.append(f"{axis['id']}: ended the release at {values[-1]}, started it at "
                            f"{values[0]}")
    measured["release"] = series
    return problems


def _difficulty_checks(ctx):
    """difficulty.axes_progress: the build carries the design's difficulty, and it moves.

    Authored content is judged twice. First the build against the design: every traversed
    unit's `metrics.difficulty.<axis>` is the value the design authored for that unit, within
    `genre-models.yaml implementation.difficulty_tolerance` - the number the developer was told
    to write the unit data to. Then the series across the units actually traversed: it holds or
    dips for relief, never falls away. The rise across the whole set (the last unit above the
    first) is the design's curve, so it is asked only when every MVP unit was traversed; a
    capped or cut traversal reports `partial` and is not held to a curve it never saw. The
    design's own curve is the design step's business, not the bot's.

    The rise is judged the way content.axes_monotone_with_relief judges the design, at the
    design's quality tier. At tier mvp every escalating axis rises over the MVP traversed. Above
    it the design escalates over every release unit and its MVP, a prefix, may hold an axis
    flat: the build is held to the rise on the MVP only where the design's own values for the
    traversed units rise (or state none), and to the design's values everywhere. When the
    survey entered every release unit, those visits are compared to the design too, and every
    reported escalating axis must end the release above where it started it.
    """
    project, axes, units = ctx["project"], ctx["axes"], ctx["units"]
    built = ctx["built_units"]
    bars = ctx["qa"].get("difficulty") or {}
    if not axes:
        return _skips(project, ("difficulty.axes_progress",),
                      "the design declares no difficulty axes of a genre family "
                      "(genre.family + build_spec.difficulty.axes), so no axis can be judged")
    escalating = [a for a in axes if a.get("escalates")]
    if not escalating:
        return _skips(project, ("difficulty.axes_progress",),
                      "no axis of this genre family escalates, so nothing is designed to rise")
    traverse = ctx["records"].get("traverse") or {}
    played = [u for u in traverse.get("per_unit") or [] if isinstance(u, dict)]
    windows = [w for w in (ctx["records"].get("session") or {}).get("windows") or []
               if isinstance(w, dict)]
    reported = set()
    for unit in played:
        reported.update((unit.get("difficulty") or {}).keys())
    for window in windows:
        reported.update((window.get("difficulty") or {}).keys())
    absent_required = sorted(a["id"] for a in escalating
                             if a.get("probe") == "required" and a["id"] not in reported)
    if absent_required:
        return [_check("difficulty.axes_progress", project, False,
                       "the genre model requires the build to report "
                       + ", ".join(f"metrics.difficulty.{a}" for a in absent_required)
                       + ": the probe reports none of them, so the ramp cannot be measured",
                       measured={"reported": sorted(reported), "absent": absent_required},
                       expected="metrics.difficulty.<axis> for every axis marked "
                                "`probe: required`")]
    present = [a for a in escalating if a["id"] in reported]
    if not present:
        return [_check("difficulty.axes_progress", project, False,
                       "no escalating axis of this family is reported by the probe, and each of "
                       "them is optional (" + ", ".join(a["id"] for a in escalating) + ")",
                       required=False, measured={"reported": sorted(reported)})]
    authored = ctx["mode"] == "authored" and len(played) > 1
    problems, measured = [], {}
    if authored:
        rise = bars.get("min_rise_share")
        dip = bars.get("relief_dip_max")
        ordered = sorted(played, key=lambda u: u.get("index") or 0)
        traversed = {u.get("unit_id") for u in ordered} | {u.get("index") for u in ordered}
        partial = any(u.get("id") not in traversed and u.get("index") not in traversed
                      for u in units)
        if partial:
            measured["partial"] = True
        # The build against the design, unit by unit and axis by axis.
        tolerance = genre_models.implementation().get("difficulty_tolerance")
        measured["difficulty_tolerance"] = tolerance
        matched = isinstance(tolerance, (int, float))
        release = _release_curve(ctx)
        if release:
            measured["quality_tier"] = release["tier"]
        off = []
        if matched:
            off = _off_design(ctx["design"], built, ordered, axes, tolerance)
            if release:
                off += _off_design(ctx["design"], release["units"], release["visits"], axes,
                                   tolerance, seen={_designed_id(built, u) for u in ordered})
        if off:
            measured["off_design"] = off
            problems += off[:6]
        flat = []
        for axis in present:
            values = [(u.get("difficulty") or {}).get(axis["id"]) for u in ordered]
            values = [v for v in values if isinstance(v, (int, float))]
            measured[axis["id"]] = values
            if len(values) < 2:
                problems.append(f"{axis['id']}: only one unit reported it")
                continue
            problems += _held(axis["id"], values, rise, dip)
            if partial:
                continue
            # Above tier mvp the design ships every release unit and escalates over all of them
            # (content.axes_monotone_with_relief); its MVP, a prefix of that curve, may hold an
            # escalating axis flat. The build is held to the rise wherever the design's own
            # values for the units traversed rise - or state none - and, where they hold, to
            # those values (off_design above), never below its start.
            designed = _designed_series(built, ordered, axis["id"])
            holds = (release is not None and matched and designed is not None
                     and designed[-1] <= designed[0])
            if holds:
                flat.append(axis["id"])
                if values[-1] < values[0] - tolerance:
                    problems.append(f"{axis['id']}: ended at {values[-1]}, started at "
                                    f"{values[0]}")
            elif values[-1] <= values[0]:
                problems.append(f"{axis['id']}: ended at {values[-1]}, started at {values[0]}")
        if flat:
            measured["held_by_design"] = flat
        if release:
            problems += _release_escalation(release, present, measured, rise, dip)
        expected = ((f"each traversed unit within {tolerance} of the design's value for it on "
                     f"every declared axis" if matched else
                     "genre-models states no implementation.difficulty_tolerance, so the build "
                     "was not compared to the design's unit values")
                    + f"; >= {bars.get('min_rise_share')} of consecutive units non-decreasing or "
                      f"dipping at most {bars.get('relief_dip_max')}"
                    + ("; the traversal stopped short of the design's units, so no rise across "
                       "the set is asked of it" if partial else
                       ", and the last above the first where the design's own units rise"
                       + (" (the MVP of a release design may hold an axis flat; the rise is "
                          "judged over every release unit the survey entered)"
                          if release else "")))
    else:
        for axis in present:
            series = [(w.get("difficulty") or {}).get(axis["id"]) for w in windows]
            series = [v for v in series if isinstance(v, (int, float))]
            measured[axis["id"]] = series
            if len(series) < 2:
                problems.append(f"{axis['id']}: fewer than two {bars.get('endless_window_s')} s "
                                f"windows reported it")
            elif series[-1] <= series[0]:
                problems.append(f"{axis['id']}: the last window is {series[-1]}, the first "
                                f"{series[0]}")
        expected = (f"the last {bars.get('endless_window_s')} s window above the first, on every "
                    "escalating axis")
    optional_absent = sorted(a["id"] for a in escalating if a["id"] not in reported)
    if optional_absent:
        measured["absent_optional"] = optional_absent
    return [_check("difficulty.axes_progress", project, not problems,
                   ((("the build carries the design's difficulty, and it holds or rises on "
                      if authored else "difficulty rose on ")
                     + ", ".join(a["id"] for a in present)
                     + (f"; not reported: {', '.join(optional_absent)}" if optional_absent else "")
                     + ("; the traversal stopped short of the design's units, so the rise across "
                        "the set was not judged" if measured.get("partial") else "")
                     + (f"; held flat by the design's own MVP: {', '.join(measured['held_by_design'])}"
                        if measured.get("held_by_design") else "")
                     + (f"; the release curve was not judged here "
                        f"({measured['release_partial']['reason']})"
                        if measured.get("release_partial") else ""))
                    if not problems else "; ".join(problems[:4])),
                   measured=measured, expected=expected,
                   truncated=ctx["truncated"].get("traverse" if authored else "session"))]


def _variety_check(ctx):
    """content.variety: consecutive units differ, or a new kind arrives on the schedule.

    Required of a family whose `qa.min_new_kinds_per_unit` is at least 1 - there, variety is a
    new thing on screen, which the probe can show. A family that asks for none varies in what
    entity kinds cannot carry, so the share is measured and reported as a warning with its
    reason, never as a failure read from a vocabulary that cannot express it.
    """
    project, units, mode = ctx["project"], ctx["units"], ctx["mode"]
    built = ctx["built_units"]
    bars = ctx["qa"].get("variety") or {}
    genre = ctx["qa"].get("genre") or {}
    traverse = ctx["records"].get("traverse") or {}
    kinds_reported = _kinds_reported(traverse)
    # At a tier where an unmeasured check is not passed (core/reference/quality-policy.yaml
    # rule 5, `kinds_required`), a probe that names no kind while a content unit is in play
    # fails: the play-probe schema requires `kind` of every content-role entity then, so the
    # omission is the build's, not the bot's.
    omitted = (f"the probe reports no `entities[].kind` while a content unit is in play, so "
               f"element variety cannot be counted on the build; the play probe requires the "
               f"`kind` of every content-role entity then (threat, goal, target, projectile, "
               f"collectible, hazard), and {ctx.get('kinds_required')}")
    schedule = [e for e in (ctx["depth"].get("content_schedule") or [])
                if isinstance(e, dict) and e.get("tier") == "mvp"
                and isinstance(e.get("at_s"), (int, float))]
    if ctx["content"] is None and not schedule:
        return _skips(project, ("content.variety",),
                      "the design claims no content units and no in-run content schedule, so "
                      "no variety is promised")
    if mode == "authored":
        played = sorted([u for u in traverse.get("per_unit") or [] if isinstance(u, dict)],
                        key=lambda u: u.get("index") or 0)
        if len(played) < 2:
            return [_check("content.variety", project, False,
                           f"only {len(played)} unit(s) were played, so no two consecutive units "
                           "could be compared", measured={"units_played": len(played)})]
        # The unit in play when the traverse stopped short (its window, its unit count) was
        # seen only up to the cut, however far the bot played on in it (bot.spec.ts, `sample`
        # in visual-quality.yaml): what it showed counts, what it did not show yet decides
        # nothing - a negative there would be decided by where the cut fell.
        cut = _cut_unit(traverse, played, ctx["truncated"].get("traverse"))
        changed, pairs, open_pairs = 0, 0, []
        for first, second in zip(played, played[1:]):
            a, b = _designed(built, first) or {}, _designed(built, second) or {}
            if (set(first.get("kinds") or []) != set(second.get("kinds") or [])
                    or set(a.get("mechanics") or []) != set(b.get("mechanics") or [])):
                changed += 1
            elif second is cut:
                open_pairs.append(f"{first.get('index')}->{second.get('index')}")
                continue
            pairs += 1
        share = _share(changed, pairs)
        bar = bars.get("min_changed_pairs_share")
        want_new = int(genre.get("min_new_kinds_per_unit") or 0)
        new_short, open_units, seen = [], [], set(played[0].get("kinds") or [])
        for unit in played[1:]:
            fresh = set(unit.get("kinds") or []) - seen
            if len(fresh) < want_new:
                if unit is cut:
                    open_units.append(f"unit {unit.get('index')}: {len(fresh)} new kind(s) in "
                                      f"the {unit.get('duration_ms')} ms seen before the "
                                      f"traverse stopped ({traverse.get('stopped')})")
                else:
                    new_short.append(f"unit {unit.get('index')}: {len(fresh)} new kind(s)")
            seen |= set(unit.get("kinds") or [])
        # Decided only on as many units as the traverse is held to (content.units_reachable's
        # N): a cut unit that already showed its new kinds is one of them, one that did not
        # yet is not.
        want_units = min(len(units), int((ctx["qa"].get("content") or {})
                                         .get("min_units_traversed") or 1))
        decided = len(played) - (1 if open_units else 0)
        if not kinds_reported and ctx.get("kinds_required"):
            return [_check("content.variety", project, False, omitted, required=True,
                           measured={"changed_pairs_share": share, "kinds_reported": [],
                                     "units_played": len(played)},
                           expected=f">= {bar} of consecutive unit pairs changed, and >= "
                                    f"{want_new} new entity kind(s) per unit, read from "
                                    "`entities[].kind`",
                           truncated=ctx["truncated"].get("traverse"))]
        measurable = bool(kinds_reported) or want_new == 0
        problems = ([f"only {share} of consecutive units change their kinds or mechanics"]
                    if pairs and share < bar else [])
        if want_new and measurable:
            problems += new_short
        cut_note = {}
        if open_units or open_pairs:
            cut_note = {"unmeasured_units": open_units, "unmeasured_pairs": open_pairs,
                        "stopped": traverse.get("stopped"),
                        **({"extended_ms": traverse["extended_ms"]}
                           if traverse.get("extended_ms") else {})}
        if (not problems and measurable and want_new >= 1 and open_units
                and decided < want_units):
            # Nothing the traverse saw whole falls short, and what it cut short is too much
            # of what it is held to: unmeasured, never a pass - and never a failure read off
            # the cut. Held like any unmeasured check (quality-policy.yaml skipped_checks).
            held = ((ctx.get("unmeasured_held") or {}).get("content.variety")
                    or ctx.get("kinds_required"))
            return [_check(
                "content.variety", project, False,
                f"not judged: {'; '.join(open_units)} - the traverse saw {decided} unit(s) "
                f"whole of the {want_units} it is held to, and a new kind that had not arrived "
                "by the cut decides nothing" + (f"; {held}" if held else ""),
                required=bool(held), blocked=bool(held),
                measured={"changed_pairs_share": share, "kinds_reported": sorted(kinds_reported),
                          "new_kinds_short": new_short, "unmeasured": SAMPLE_CUT, **cut_note},
                expected=f">= {bar} of consecutive unit pairs changed, and >= {want_new} new "
                         f"entity kind(s) per unit, over at least {want_units} units",
                truncated=ctx["truncated"].get("traverse"))]
        # What a probe can show of variety is entity kinds. A family that asks for a new kind
        # in each unit (qa.min_new_kinds_per_unit >= 1) is held to that; one that does not
        # varies in what kinds cannot carry - the layout, the rules, the objective - and its
        # share is reported, not enforced. Unmeasurable is not a pass either: the probe reports
        # no kinds, so the bar was not met or missed - it was not read.
        required = want_new >= 1 and measurable
        reason = (None if required else
                  "the probe reports no `entities[].kind`, so the new kind(s) each unit of this "
                  "family must introduce could not be measured" if not measurable else
                  "variety is not visible in entity kinds for this family (layout, rules, "
                  "objectives)")
        return [_check("content.variety", project, not problems and measurable,
                       ("the probe reports no `entities[].kind`, so the "
                        f"{want_new} new kind(s) each unit must introduce could not be measured"
                        if not measurable and not problems else
                        "; ".join(problems[:4]) + (f"; {reason}" if reason else "") if problems else
                        f"{share} of consecutive units change their kinds or mechanics, and each "
                        f"introduces at least {want_new} new kind(s)"
                        + (f" (not judged, cut short by the traverse: {'; '.join(open_units)})"
                           if open_units else "")),
                       required=required,
                       measured={"changed_pairs_share": share,
                                 "kinds_reported": sorted(kinds_reported),
                                 "new_kinds_short": new_short,
                                 **({"reason": reason} if reason else {}), **cut_note},
                       expected=f">= {bar} of consecutive unit pairs changed, and >= {want_new} "
                                "new entity kind(s) per unit",
                       truncated=ctx["truncated"].get("traverse"))]
    # Generated content: the first new thing arrives when the content schedule says it does.
    arrives = min(e["at_s"] for e in schedule)
    slack = bars.get("first_new_kind_slack_s")
    bar_ms = (arrives + slack) * 1000
    rows = [r for r in traverse.get("snapshots") or [] if isinstance(r, dict)]
    in_unit = any(isinstance(r.get("unit_id"), str) for r in rows)
    if not kinds_reported and in_unit and ctx.get("kinds_required"):
        return [_check("content.variety", project, False, omitted, required=True,
                       measured={"snapshots": len(rows), "kinds_reported": []},
                       expected=f"a kind not on screen at the start, by {bar_ms / 1000} s, "
                                "read from `entities[].kind`")]
    if not kinds_reported:
        return [_check("content.variety", project, False,
                       "the probe reports no `entities[].kind`, so the arrival of a new kind of "
                       f"content (the schedule's first is at {arrives} s) could not be measured",
                       required=False,
                       measured={"snapshots": len(rows), "kinds_reported": []},
                       expected=f"a kind not on screen at the start, by {bar_ms / 1000} s")]
    opening = set(rows[0].get("kinds") or []) if rows else set()
    first_new = next((r.get("ms") for r in rows if set(r.get("kinds") or []) - opening), None)
    return [_check("content.variety", project, first_new is not None and first_new <= bar_ms,
                   (f"the first new kind of content arrived {first_new} ms into play"
                    if first_new is not None else
                    "no kind of content arrived that was not on screen at the start"),
                   measured={"first_new_kind_ms": first_new, "opening_kinds": sorted(opening),
                             "kinds_reported": sorted(kinds_reported)},
                   expected=f"<= {bar_ms} ms (the schedule's first in-run arrival at {arrives} s "
                            f"plus {slack} s)",
                   truncated=ctx["truncated"].get("traverse"))]


# A probe measure that is not a metric: the content block's unit reached.
UNIT_REACHED = "content.unit_index"


def persisted_measures(design, measures=None):
    """(metric names, unit reached) the probe would report for what the design says persists
    at MVP: the metric names, and whether an entry is measured by the unit reached
    (`content.unit_index`).

    By reference, never by matching words: a persisted entry's `delivered_by` names a HUD
    element, and that element names the metric. Otherwise its kind's probe measure
    (core/reference/design-depth.yaml `playability.persists.probe_measures`): a persisted
    best is the probe schema's own recommended `best`, stage progress the unit reached.
    """
    if measures is None:
        measures = {"best-score": "best"}
    spec = (design or {}).get("build_spec") or {}
    hud = {h.get("id"): h.get("metric") for h in spec.get("hud") or []
           if isinstance(h, dict) and h.get("id")}
    names, unit = set(), False
    depth = spec.get("depth") or {}
    for entry in ((depth.get("meta_loop") or {}).get("persists") or []):
        if not isinstance(entry, dict) or entry.get("tier") != "mvp":
            continue
        metric = hud.get(entry.get("delivered_by")) or measures.get(entry.get("kind"))
        if metric == UNIT_REACHED:
            unit = True
        elif metric:
            names.add(metric)
    return names, unit


def persisted_metrics(design, measures=None):
    """The metric names the probe would report for what the design says persists at MVP
    (persisted_measures, without the unit reached)."""
    return persisted_measures(design, measures)[0]


def _depth_checks(ctx):
    """progression.persists, depth.session_length, depth.ramp."""
    project, qa, depth = ctx["project"], ctx["qa"], ctx["depth"]
    genre = qa.get("genre") or {}
    records = ctx["records"]
    out = []

    # What survives a reload.
    persist = records.get("persist") or {}
    names, unit = persisted_measures(
        ctx["design"], (qa.get("persists") or {}).get("probe_measures"))
    if not names and not unit:
        out += _skips(project, ("progression.persists",),
                      "the design's meta loop persists nothing at the mvp tier the probe "
                      "reports (build_spec.depth.meta_loop.persists: no HUD metric, no kind "
                      "in design-depth.yaml playability.persists.probe_measures)")
    else:
        before, after = persist.get("before") or {}, persist.get("after") or {}
        resumed = persist.get("after_resumed") or {}
        measured, lost = {}, []
        for name in sorted(names):
            was = (before.get("metrics") or {}).get(name)
            if was is None:
                continue
            now = (after.get("metrics") or {}).get(name)
            if now is None:
                now = (resumed.get("metrics") or {}).get(name)
            measured[name] = {"before": was, "after": now}
            if now != was:
                lost.append(name)
        was_index = ((before.get("content") or {}) or {}).get("unit_index")
        if was_index is not None:
            now_index = ((resumed.get("content") or after.get("content") or {}) or {}) \
                .get("unit_index")
            if now_index != was_index:
                lost.append(UNIT_REACHED)
            # Stage progress is shown only past the first unit: a build that saves nothing
            # starts at unit 1 too.
            if now_index != was_index or not unit or was_index > 1:
                measured[UNIT_REACHED] = {"before": was_index, "after": now_index}
        if genre.get("checkpoint"):
            lose = records.get("lose") or {}
            at_loss = ((lose.get("contentAtEnd") or {}) or {}).get("progress") or {}
            back = (((lose.get("restart") or {}).get("content") or {}) or {}).get("progress") or {}
            measured["checkpoint"] = {"at_loss": at_loss.get("value"),
                                      "after_retry": back.get("value")}
            if not at_loss or back.get("value") != at_loss.get("value"):
                lost.append("checkpoint")
        required = ctx["mode"] in (qa.get("persists") or {}).get("required_generations", [])
        wanted = sorted(names) + ([UNIT_REACHED] if unit else [])
        out.append(_check("progression.persists", project, bool(measured) and not lost,
                          ("the probe reports none of what the design says persists "
                           f"({', '.join(wanted)})"
                           + (f": the bot reached no unit past the first before the reload "
                              f"(content.unit_index {was_index}), so the unit reached was not "
                              f"shown to survive" if unit and was_index is not None else "")
                           if not measured else
                           f"lost across a reload: {', '.join(lost)}" if lost else
                           f"survived a reload: {', '.join(sorted(measured))}"),
                          required=required, measured=measured,
                          expected="equal before and after `location.reload()`, read before any "
                                   "input",
                          frames=["persist-after-reload"]))

    # The first session's length.
    session = records.get("session") or {}
    bars = qa.get("session_length") or {}
    first = depth.get("first_session") or {}
    target = first.get("target_s")
    if not isinstance(target, (int, float)) or target <= 0:
        out += _skips(project, ("depth.session_length",),
                      "the design states no first-session length "
                      "(build_spec.depth.first_session.target_s)")
    else:
        want = bars.get("min_share") * target * 1000
        length = session.get("length_ms")
        truncated = bool(ctx["truncated"].get("session"))
        short = length is None or length < want
        required = ctx["mode"] == "authored" and not (truncated and short)
        out.append(_check("depth.session_length", project, not short,
                          (f"one oracle session with instant retries lasted {length} ms"
                           if length is not None else "no session was played")
                          + (f"; the bot's window was cut to {session.get('target_ms')} ms to fit "
                             "the time budget" if truncated else "")
                          + (f"; the designed closing beat ({first.get('ends_on')}) arrived at "
                             f"{session.get('beat_at_ms')} ms"
                             if session.get("beat_at_ms") is not None else ""),
                          required=required,
                          measured={"length_ms": length, "beat_at_ms": session.get("beat_at_ms"),
                                    "ended_on": session.get("ended_on"),
                                    "runs": len(session.get("runs") or [])},
                          expected=f">= {want} ms ({bars.get('min_share')} of the designed "
                                   f"{target} s first session)",
                          truncated=truncated))

    # The ramp: bad play ends quickly, and good play is asked for more as it goes.
    bars = qa.get("ramp") or {}
    if not depth:
        out += _skips(project, ("depth.ramp",),
                      "the design states no depth contract (build_spec.depth), so no run length "
                      "or session shape is claimed")
        return out
    played = [u for u in (records.get("traverse") or {}).get("per_unit") or []
              if isinstance(u, dict)]
    durations = [(_designed(ctx["units"], u) or {}).get("expected_duration_s") for u in played]
    durations = [d for d in durations if isinstance(d, (int, float))]
    run_s = max(durations) if durations else ((ctx["design"].get("session") or {})
                                             .get("target_seconds"))
    lose = records.get("lose") or {}
    ended = lose.get("endedAtMs")
    problems, measured = [], {"bad_play_ended_ms": ended, "run_length_s": run_s}
    if not isinstance(run_s, (int, float)) or run_s <= 0:
        out += _skips(project, ("depth.ramp",),
                      "the design states neither a unit duration nor a session length to hold a "
                      "run to")
        return out
    cap = bars.get("bad_play_max_multiplier") * run_s * 1000
    if ended is None or ended > cap:
        problems.append(f"bad play ended after {ended} ms, over {cap} ms "
                        f"({bars.get('bad_play_max_multiplier')} x a {run_s} s run)")
    # The input rate across a run's thirds is a time ramp: the longer one run lasts, the more
    # it asks. It is read only on the play that promises one (time_ramp): the session's play
    # when it is endless, else the endless mode the bot entered through the probe - and on
    # `samples` fresh runs of it, pooled (ramp_verdict), never on one. A unit-authored design
    # without such a mode ramps between units - which difficulty.axes_progress judges - so
    # its longest session run's rate is recorded, not held: one unit is not a time ramp.
    ramp = time_ramp(ctx["design"], qa, ctx.get("ramp_tiers"))
    timed = ramp is not None
    minimum = bars.get("min_inputs_per_third")
    unmeasured = verdict = None
    on_mode = bool(ramp and ramp["run"] == "mode")
    record = records.get("ramp") or {}
    samples = [s for s in record.get("samples") or [] if isinstance(s, dict)]
    if ramp is None:
        measured["reason"] = ("no time ramp: the genre family's `qa` states no endless_window_s, "
                              "or the design is unit-authored and includes no endless mode "
                              "(design-depth.yaml playability.ramp.mode_features)")
        runs = [r for r in (records.get("session") or {}).get("runs") or []
                if isinstance(r, dict)]
        longest = max(runs, key=lambda r: r.get("duration_ms") or 0) if runs else None
        thirds = thirds_of(longest)
        if thirds:
            measured["oracle_inputs_per_third"] = thirds
        played_on = "samples"
    else:
        measured["ramp_run"] = ramp["run"]
        played_on = (f"{ramp['mode']}-mode samples" if on_mode else "samples of the endless play")
        if on_mode:
            measured.update(mode=ramp["mode"], feature=ramp["feature"],
                            mode_entered=bool(record.get("entered")))
        if on_mode and not record.get("entered"):
            unmeasured = (f"the design includes the {ramp['mode']} mode ({ramp['feature']}), "
                          "whose run the time ramp is read on, and the bot could not enter it: "
                          + (record.get("reason") or "no ramp record")
                          + " (the probe's optional play.mode.enter, docs/template-contract.md)")
        else:
            verdict = ramp_verdict(samples, bars)
            measured.update(samples=verdict["per_sample"], planned_samples=verdict["planned"])
            for key, name in (("pooled", "pooled_inputs_per_third"), ("band", "noise_band"),
                              ("stalled", "stalled_samples")):
                if key in verdict:
                    measured[name] = verdict[key]
            if record.get("reason") and len(samples) < (bars.get("samples") or 0):
                measured["sampling_stopped"] = record["reason"]
            if record.get("extended_ms"):
                measured["extended_ms"] = record["extended_ms"]
            if verdict["verdict"] == "fail":
                problems.append(verdict["reason"])
            elif verdict["verdict"] == "unmeasured":
                unmeasured = verdict["reason"] + (
                    f" (sampling stopped: {record['reason']})"
                    if measured.get("sampling_stopped") else "")
    if unmeasured:
        measured["unmeasured"] = unmeasured
    expected = (f"a bad run inside {cap} ms"
                + (f", and over {bars.get('samples')} fresh runs of the "
                   f"{ramp['mode'] + ' mode' if on_mode else 'endless play'}, pooled (at least {minimum} oracle inputs in the first thirds), the "
                   f"last thirds' inputs above the first thirds' by more than "
                   f"{bars.get('noise_z')} x sqrt(first + last), and no run's own fall beyond "
                   "its band; a difference inside the band is extended, then unmeasured"
                   if timed else ""))
    if problems:
        ok, required = False, timed
        summary = "; ".join(problems[:3])
    elif unmeasured:
        # Not measured is not passed: a WARNING with its reason, a FAIL at a tier whose
        # skipped checks are not passed (quality-policy.yaml skipped_checks, `ramp_required`).
        ok, required = False, bool(ctx.get("ramp_required"))
        summary = (f"bad play ended in {ended} ms, but the time ramp was not measured: "
                   f"{unmeasured}"
                   + (f"; {ctx['ramp_required']}" if ctx.get("ramp_required") else ""))
    else:
        ok, required = True, timed
        summary = (f"bad play ended in {ended} ms"
                   + (f", and the oracle's input rate rose across the {played_on}: "
                      f"{verdict['reason']}" if timed else
                      f"; the oracle's input rate per third of its longest run was "
                      f"{measured['oracle_inputs_per_third']}"
                      if measured.get("oracle_inputs_per_third") else ""))
    out.append(_check("depth.ramp", project, ok, summary,
                      required=required, measured=measured, expected=expected,
                      truncated=ctx["truncated"].get("ramp")))
    if timed and samples:
        out.append(_stall_check(project, samples, bars, played_on,
                                ctx["truncated"].get("ramp")))
    return out


def _stall_check(project, samples, bars, played_on, truncated):
    """depth.stall: no ramp sample went longer than `stall_max_s` in play with no oracle input
    and no progress. Its own finding, so a game that stops being playable - a ball trapped
    where no input can free it - is classified as that, routed to gameplay, instead of
    deflating the ramp's last third and reading as a game that asks for less."""
    bar = bars.get("stall_max_s")
    idle = [(n, s.get("longest_idle_ms"), s.get("idle_at_ms"))
            for n, s in enumerate(samples, start=1)]
    known = [(n, ms, at) for n, ms, at in idle if isinstance(ms, (int, float))]
    measured = {"longest_idle_ms": [ms for _n, ms, _at in idle], "stall_max_s": bar}
    expected = (f"in every ramp sample, no stretch in play over {bar} s with no oracle input and "
                "no change in the goal metric, the unit's progress or the unit reached")
    if not isinstance(bar, (int, float)) or not known:
        measured["unmeasured"] = ("design-depth.yaml playability.ramp states no stall_max_s"
                                  if not isinstance(bar, (int, float)) else
                                  "the samples record no idle stretch")
        return _check("depth.stall", project, False,
                      f"no stall was measured: {measured['unmeasured']}", required=False,
                      measured=measured, expected=expected, truncated=truncated)
    over = [(n, ms, at) for n, ms, at in known if ms > bar * 1000]
    worst = max(known, key=lambda k: k[1])
    if over:
        summary = "; ".join(
            f"ramp sample {n} ({played_on}) went {ms / 1000:.1f} s in play with no oracle input "
            f"and no progress (from {at} ms into it), over the {bar} s bar: play stopped"
            for n, ms, at in over[:3])
    else:
        summary = (f"the longest stretch with no oracle input and no progress in any of "
                   f"{len(known)} sample(s) was {worst[1] / 1000:.1f} s (sample {worst[0]}), "
                   f"inside the {bar} s bar")
    return _check("depth.stall", project, not over, summary, required=True, measured=measured,
                  expected=expected, truncated=truncated)


def judge(records, frames_dir, design, rules, experience_rules, project, qa=None,
          kinds_required=None, scope_tiers=None, ramp_required=None, ramp_tiers=None,
          unmeasured_held=None):
    """Checks (dicts per playability-report.schema.json) for one viewport.

    `qa` is the merged bars (wgflib.genre_models.qa_of): core/reference/design-depth.yaml's
    `playability` block with the genre family's `qa` overrides. Loaded from the reference files
    when not given.

    `kinds_required`, when set, is why entity kinds the probe omits while a content unit is in
    play fail content.variety instead of leaving it unmeasured (the run's tier holds an
    unmeasured check not passed: core/reference/quality-policy.yaml rule 5). None keeps the
    unmeasured check a WARNING with its reason.

    `scope_tiers` are the design tiers the run builds (wgflib.build_scope.design_tiers: the
    MVP at tier mvp, the MVP and post-mvp at release); else the design's own tier's. A unit of
    them is a design unit wherever the build is held to one - the id the probe reports, the
    unit a traversed one is - while the traverse and its curve stay the MVP's. An id the
    design does not list, or lists outside the scope, is never one.
    `ramp_required` is the same for a time ramp the bot could not measure (depth.ramp);
    `ramp_tiers` are the design tiers this build carries, which decide whether an included
    endless mode is owed by it (time_ramp).
    `unmeasured_held` maps a check id to why it is not passed when it measured nothing (the
    same rule, per check): a check whose recordings were all made on a degraded host
    (`environment-degraded`), or content.variety on a unit the traverse cut short
    (`sample-cut`), is then BLOCKED rather than a WARNING. Never a pass either way.
    """
    spec = ((design or {}).get("build_spec") or {})
    ex = spec.get("experience") or {}
    first = records.get("first-session") or {}
    act = records.get("act") or {}
    win = records.get("win") or {}
    lose = records.get("lose") or {}
    content, mode, units = content_units(design)
    if scope_tiers is None:
        try:
            scope_tiers = build_scope.design_tiers(design)
        except build_scope.BuildScopeError:
            scope_tiers = None
    built = content_units(design, tuple(scope_tiers))[2] if scope_tiers else units
    ctx = {"project": project, "records": records, "design": design or {}, "content": content,
           "mode": mode, "units": units, "built_units": built, "depth": spec.get("depth") or {},
           "qa": qa if qa is not None else genre_models.qa_of(design),
           "axes": genre_models.axes_of(design),
           "family": genre_models.for_design(design) or {},
           "truncated": rules.get("_truncated") or {},
           "kinds_required": kinds_required, "ramp_required": ramp_required,
           "ramp_tiers": ramp_tiers, "unmeasured_held": unmeasured_held or {}}
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
    # A design that authors its content units is played unit by unit, so the probe must say
    # which unit the player is in, by the design's own id. Generated content has no such
    # sequence, and the probe is not asked for one.
    content_gaps = []
    if mode == "authored":
        playing = [s for s in snapshots if s.get("state") == "playing"]
        if not playing or any(not isinstance(s.get("content"), dict) for s in playing):
            content_gaps.append(
                "the design authors content units but the probe reports no `content` while "
                "playing, so no unit can be located")
        reported = {(s.get("content") or {}).get("unit_id") for s in playing
                    if isinstance(s.get("content"), dict)}
        reported |= {r.get("unit_id") for r in
                     (records.get("traverse") or {}).get("snapshots") or []}
        unknown = sorted(uid for uid in reported if uid and uid not in {u.get("id") for u in ctx["built_units"]})
        if unknown:
            content_gaps.append("content.unit_id is not a design unit: " + ", ".join(unknown[:3]))
    add(_check("probe.valid", project, not problems and not missing and not content_gaps,
               ("snapshots match the play-probe schema and carry the contract's metrics"
                if not problems and not missing and not content_gaps else
                "; ".join(problems[:3]
                          + ([f"metrics missing: {', '.join(missing)}"] if missing else [])
                          + content_gaps)),
               measured={"schema_problems": problems[:5], "missing_metrics": missing,
                         "content_problems": content_gaps}))

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
    shape = ((ctx["family"].get("win") or {}).get("shape"))
    if "win" in ex:
        # Never degraded to "the metric rose": a design that states a win is held to it.
        ok = win.get("reached") == "won"
        summary = (f"good play reached `won` after {win.get('inputs')} inputs" if ok else
                   f"good play did not reach `won` (ended {win.get('reached') or 'still playing'})")
    elif shape and shape != "best-score":
        ok = False
        summary = (f"the genre family wins by `{shape}`, not by a best score, and the design "
                   "states no build_spec.experience.win: there is nothing for good play to reach")
    else:
        rising = len(series) > 1 and series[-1]["value"] > series[0]["value"]
        ok = rising
        summary = (f"good play raised {ex.get('goal', {}).get('metric')} from "
                   f"{series[0]['value'] if series else None} to {series[-1]['value'] if series else None}")
    add(_check("win.reachable", project, ok, summary,
               measured={"reached": win.get("reached"), "inputs": win.get("inputs"),
                         "genre_win_shape": shape}))

    # A family that names the resource bad play drains: the loss is seen in that number, not
    # taken on the game's word.
    resource = (ctx["qa"].get("genre") or {}).get("resource_metric")  # noqa: E501
    drain, drained = None, True
    if resource:
        values = [(s.get("metrics") or {}).get(resource)
                  for s in lose.get("series") or [] if isinstance(s, dict)]
        values = [v for v in values if isinstance(v, (int, float))]
        drain = {"metric": resource, "first": values[0] if values else None,
                 "lowest": min(values) if values else None, "samples": len(values)}
        drained = bool(values) and min(values) < values[0]
    lost_ok = lose.get("reached") == "lost" and drained
    genre_qa = ctx["qa"].get("genre") or {}
    add(_check("lose.reachable", project, lost_ok,
               "this genre family has no failure state (qa.failure_state), so play cannot be lost"
               if genre_qa.get("failure_state") is False else
               f"bad play ended {lose.get('reached') or 'without reaching lost'}"
               + ("" if drained else
                  f", but {resource} never fell under the anti-oracle: a loss the player cannot "
                  "see coming in the number the design names"),
               measured={"reached": lose.get("reached"), **({"resource": drain} if resource else {})},
               frames=[f for f in lose.get("frames") or []],
               skipped=genre_qa.get("failure_state") is False))

    restart = lose.get("restart") or {}
    retry_bar = ((budget.get("retry_s") or (experience_rules.get("first_30s") or {})
                  .get("max_retry_s", 3)) * 1000) + 1000
    goal_metric = (ex.get("goal") or {}).get("metric")
    reset = (restart.get("metrics") or {}).get(goal_metric) == ((lose.get("initial") or {}).get(goal_metric))
    ok = bool(restart.get("clicked")) and restart.get("playingMs") is not None \
        and restart["playingMs"] <= retry_bar and reset
    # A family whose unit can be restarted from inside it (qa.reset_in_unit): the restart
    # pressed mid-unit returns to play with the unit's own progress back at the start.
    mid_note = ""
    mid = lose.get("resetInUnit") if genre_qa.get("reset_in_unit") else None
    if mid is not None:
        was = ((mid.get("before") or {}).get("progress") or {}).get("value")
        now = ((mid.get("after") or {}).get("progress") or {}).get("value")
        mid_ok = (bool(mid.get("clicked")) and mid.get("playingMs") is not None
                  and now is not None and (now == 0 or (was is not None and now < was)))
        ok = ok and mid_ok
        if mid_ok:
            mid_note = ("; a restart inside the unit returned to play with its progress at "
                        f"{now}")
        elif not mid.get("clicked"):
            mid_note = ("; no reset was offered DURING play: this family resets inside a "
                        "unit, so the probe must list an input named reset, retry or restart "
                        "while playing, and it must return the unit to its start state")
        else:
            mid_note = ("; a restart inside the unit did not return to a clean unit "
                        f"(progress {was} -> {now}, retry {mid.get('clicked')}): progress "
                        "rises from 0 to its target, so a reset reads 0 again")
    # Nothing offered a retry because play never ended: this check waits on lose.reachable, and
    # says so rather than reporting a build defect it could not reach.
    no_loss = lose.get("reached") != "lost" and not restart
    add(_check("restart.works", project, ok,
               ("no loss to retry from: bad play never reached `lost` (see lose.reachable), so "
                "no result screen offered a retry" if no_loss else
                (f"retry ({restart.get('clicked')}) returned to play in {restart.get('playingMs')} ms"
                 + ("" if reset else f"; {goal_metric} did not reset")) if restart.get("clicked") else
                "no retry was offered after play ended") + mid_note,
               measured={"playingMs": restart.get("playingMs"), "reset": reset,
                         **({"reason": "no loss to retry from"} if no_loss else {}),
                         **({"reset_in_unit": mid} if mid is not None else {})},
               expected=f"<= {retry_bar} ms, {goal_metric} reset",
               blocked=no_loss))

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

    # The content contract: the units the design claims, the ramp on its axes, the variety
    # between them, what persists, and the session the design designed.
    checks += _content_checks(ctx)
    checks += _difficulty_checks(ctx)
    checks += _variety_check(ctx)
    checks += _depth_checks(ctx)

    errors = sorted({e for r in records.values() if isinstance(r, dict)
                     for e in r.get("errors") or []})
    add(_check("page.errors", project, not errors,
               "no page errors" if not errors else f"{len(errors)} page error(s): {errors[0]}",
               measured=errors[:5]))
    # Last: whether the host could measure what the timing-sensitive checks read.
    return _environment(checks, records, rules.get("environment") or {}, unmeasured_held)

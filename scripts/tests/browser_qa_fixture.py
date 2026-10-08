"""Browser-QA records as the spec writes them (scripts/wgf_verification/browser_qa.spec.ts):
a healthy game at every viewport, for tests to break one thing at a time.

    healthy_records(contract)  -> {viewport id: {viewport, outcomes, perf?, clips?}}
    write_records(out, records)    the files the spec would have written under WGF_BQA_OUT
"""

import copy
import json
import os

ORIGIN = "http://localhost:4173"
HEALTH = {"bot": {"max_lag_ms": 12, "stalled_ms": 0, "ticks": 400, "elapsed_ms": 20000},
          "worker": {"max_lag_ms": 8, "stalled_ms": 0, "ticks": 380, "elapsed_ms": 19000},
          "worker_error": None,
          "nav": {"ttfb_ms": 5, "server_wait_max_ms": 40, "requests": 30, "pages": 1}}
DEGRADED = {"bot": {"max_lag_ms": 3200, "stalled_ms": 5200, "ticks": 300, "elapsed_ms": 20000},
            "worker": {"max_lag_ms": 2900, "stalled_ms": 4800, "ticks": 280, "elapsed_ms": 19000},
            "worker_error": None,
            "nav": {"ttfb_ms": 5, "server_wait_max_ms": 2600, "requests": 30, "pages": 1}}


def _layout(state, w, h):
    return {"state": state, "viewport": [w, h], "scroll": [w, h], "body_scroll": [w, h],
            "controls": [{"tag": "button", "text": "PAUSE", "box": [w - 60, 12, 44, 44],
                          "disabled": False}],
            "texts": [{"text": "SCORE 120", "box": [16, 16, 120, 24]}],
            "canvases": [{"box": [0, 0, w, h], "share": 1}]}


def _sounds(*times, url=ORIGIN + "/assets/audio/sfx-tap.wav", loop=False, duration=0.2):
    return [{"t": t, "kind": "buffer", "url": url, "loop": loop, "duration": duration,
             "context": "running", "loop_now": loop} for t in times]


def _attempt(health):
    return [{"attempt": 1, "degraded": False, "reasons": [], "health": health}]


def viewport_record(v, audio=False):
    w, h = v["width"], v["height"]
    music = _sounds(450, url=ORIGIN + "/assets/audio/music-play.ogg", loop=True, duration=60.0)
    record = {
        "viewport": dict(v),
        "started": {"probe": True, "first_snapshot_ms": 420, "ready_ms": 420, "interactive_ms": 430,
                    "playing_ms": 900, "tti_ms": 400, "states": ["title", "playing"],
                    "began": ["play"]},
        "layouts": [_layout("title", w, h), _layout("playing", w, h)],
        "cover": [[{"id": "ball", "role": "projectile", "kind": "ball", "box": [w / 2, h / 2, 20, 20],
                    "share": 0, "by": None}]] * 3,
        "context_menu": {"probed": True, "how": "long-press" if v.get("touch") else "right-click",
                         "at": [w / 2, h / 2], "events": [] if v.get("touch") else
                         [{"t": 5000, "prevented": True, "target": "canvas"}]},
        "pause": {"tried": True, "how": "input:pause", "declared": True, "paused": True,
                  "resumed": True, "layout": _layout("paused", w, h)},
        "hidden": {"tried": True, "state_hidden": ["paused", "paused"], "still": True,
                   "audio_before": {"music": "music-play", "playing": True, "level": 0.04, "muted": False},
                   "audio_hidden": {"music": "music-play", "playing": False, "level": 0.0, "muted": True},
                   "state_after": "playing", "resumed_by": "input:resume"},
        "played": {"inputs": [{"t": 5200, "action": "pause"}], "transitions": []},
        "watch": {"page_errors": [], "console": [], "failed_requests": [],
                  "runs": {"main": {"sounds": music + _sounds(5230), "context_lost": [],
                                    "context_menus": [], "rejections": [], "origin": ORIGIN}}},
        "control_states": {"measured": True, "controls": [
            {"text": "PLAY", "disabled": False, "rest": {"background-color": "rgb(1, 1, 1)"},
             **({} if v.get("touch") else {"hover": {"background-color": "rgb(2, 2, 2)"},
                                           "pressed": {"background-color": "rgb(3, 3, 3)"}})}]},
        "frames": ["title", "playing"],
        "health": HEALTH,
        "attempts": _attempt(HEALTH),
    }
    if audio:
        record["mute"] = {"tried": True, "how": "input:sound",
                          "before": {"music": "music-play", "playing": True, "level": 0.04},
                          "muted": {"music": "music-play", "playing": False, "level": 0.0, "muted": True},
                          "unmuted": {"music": "music-play", "playing": True, "level": 0.035}}
    return record


def outcomes_record(v):
    return {
        "viewport": dict(v),
        "win_started": {"probe": True, "playing_ms": 900, "states": ["title", "playing"]},
        "win": {"reached": "won", "window_ms": 90000},
        "lose_started": {"probe": True, "playing_ms": 800, "states": ["title", "playing"]},
        "lose": {"reached": "lost", "window_ms": 60000},
        "restart": {"how": "input:retry", "reached": "playing", "window_ms": 10000, "took_ms": 300},
        "played": {"win": {"inputs": [{"t": 1000, "action": "launch"}, {"t": 2000, "action": "steer"}],
                           "transitions": [{"t": 900, "state": "playing"}, {"t": 30000, "state": "won"}]},
                   "lose": {"inputs": [{"t": 1000, "action": "steer"}],
                            "transitions": [{"t": 800, "state": "playing"}, {"t": 20000, "state": "lost"},
                                            {"t": 20400, "state": "playing"}]}},
        "layouts": [_layout("won", v["width"], v["height"]), _layout("lost", v["width"], v["height"])],
        "watch": {"page_errors": [], "console": [], "failed_requests": [],
                  "runs": {"win": {"sounds": _sounds(1050, 30400), "origin": ORIGIN, "context_lost": [],
                                   "rejections": []},
                           "lose": {"sounds": _sounds(20900), "origin": ORIGIN, "context_lost": [],
                                    "rejections": []}}},
        "frames": [],
    }


def perf_record(v):
    deltas = [16.7] * 400 + [20.0] * 20
    return {"viewport": dict(v), "started": {"ready_ms": 420},
            "renderer": "ANGLE (NVIDIA, NVIDIA GeForce RTX 5060 Direct3D11 vs_5_0 ps_5_0, D3D11)",
            "frames": {"sample_ms": 8000, "deltas": deltas},
            "memory": {"session_ms": 45000, "series": [{"ms": 0, "mb": 5.0}, {"ms": 45000, "mb": 6.5}]},
            "played": {"inputs": [], "transitions": []},
            "watch": {"page_errors": [], "console": [], "failed_requests": [],
                      "runs": {"perf": {"sounds": [], "origin": ORIGIN, "context_lost": [],
                                        "rejections": []}}},
            "health": HEALTH, "attempts": _attempt(HEALTH)}


def clips_record(v):
    def clip(cid, kind, level, loop=False, peak=-3.0):
        return {"id": cid, "url": f"audio/{cid}.{'ogg' if kind == 'music' else 'wav'}",
                "type": kind, "role": None, "loop": loop, "status": 200, "bytes": 20000,
                "duration_s": 60.0 if kind == "music" else 0.3, "channels": 1,
                "sample_rate": 44100, "peak_dbfs": peak, "rms_dbfs": level - 3,
                "blocks_db": [level] * 6 + [-90.0] * 2}
    return {"viewport": dict(v), "clips": {"manifest": 200, "clips": [
        clip("music-play", "music", -20.0, loop=True), clip("sfx-tap", "sfx", -14.0),
        clip("sfx-hit", "sfx", -12.0), clip("sfx-lose", "sfx", -16.0)]}}


def healthy_records(contract):
    records = {}
    for v in contract["viewports"]:
        vid = v["id"]
        entry = {"viewport": viewport_record(v, audio=vid == contract["audio_viewport"]),
                 "outcomes": outcomes_record(v)}
        if vid == contract["perf_viewport"]:
            entry["perf"] = perf_record(v)
        if vid == contract["audio_viewport"]:
            entry["clips"] = clips_record(v)
        records[vid] = entry
    return copy.deepcopy(records)


def write_records(out, records):
    for vid, entry in records.items():
        os.makedirs(os.path.join(out, vid), exist_ok=True)
        for name, record in entry.items():
            with open(os.path.join(out, vid, f"{name}.json"), "w", encoding="utf-8") as handle:
                json.dump(record, handle)

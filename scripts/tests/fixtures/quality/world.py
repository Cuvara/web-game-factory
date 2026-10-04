"""A virtual game for the quality-consistency suite: a build, what the bot records of it, and
the steps that stand in for agents.

The suite runs the shipped new-game workflow through the real engine. Every step that judges
a build is the real module - playability's judgement (scripts/wgf_playability/analysis.py),
production-quality, visual-qa, content-sufficiency, quality-gate and triage - and every step
that would call an agent or a toolchain is a fixture here:

    design       the release-tier design the real design step wrote (designs.py)
    init         a scaffold-record naming a checkout directory (nothing is cloned)
    assets       an asset manifest made from the design's assets and audio
    develop      the developer: it builds the game the design describes, with the scenario's
                 degradations in it, and a specialist visit removes the ones it owns
    playability  the real step, with only its bot replaced: instead of cloning, building and
                 playing in a browser it writes the records and frames the bot writes, from
                 the build - and the real analysis judges them
    review       a reviewer that approves the commit it is shown
    verify       qa-report and verification-report of the sdk commit, with the build's
                 measured frame rate
    release      the real release step's refusals (wgf_release.lineage.evidence_refusals); a
                 draft manifest only when none applies
    visual-qa    the real step with a command judge (judge.py) that reads the frames

A build is a dict: the design's units as built, the degradations still in it, the art state.
Its commit is a digest of it, so a build that changes gets a new commit and one that does
not keeps its own. Nothing here is a game: no name, no family is special-cased.
"""

import copy
import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.dirname(os.path.dirname(HERE))
SCRIPTS = os.path.dirname(TESTS)
for _path in (SCRIPTS, TESTS):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from wgf_assets.raster import Image, encode_png  # noqa: E402
from wgf_develop import specialist as specialists  # noqa: E402
from wgf_playability.step import PlayabilityStep  # noqa: E402
from wgf_release.lineage import BLOCKED, evidence_refusals  # noqa: E402
from wgflib import genre_models, provenance  # noqa: E402
from wgflib.workflow import mock  # noqa: E402
from wgflib.workflow.model import ArtifactOutput, StepResult  # noqa: E402

JUDGE = os.path.join(HERE, "judge.py")

# The bot's viewports (scripts/wgf_playability/step.py PROJECTS) and the scale frames are
# written at: every judge scales boxes by the frame's width over the viewport's.
VIEWPORTS = {"desktop": (1280, 720), "mobile": (393, 851)}
FRAME_SCALE = 0.125
BACKGROUND = (22, 32, 64)
ENTITY = (244, 204, 84)
ACCENT = (90, 220, 160)
HUD = (236, 236, 244)
MAGENTA = (255, 0, 255)
WHITE, NAVY = [255, 255, 255, 1], [20, 30, 60]
ENTITY_ROLES = ("player", "threat", "goal", "target", "projectile", "collectible", "hazard")
CONTENT_ROLES = ("threat", "goal", "target", "projectile", "collectible", "hazard")
SFX_IN_A_RELEASE = 10

# The degradations, each a defect a build can carry. `art` defects live in the assets, and
# only the assets step can take them out; the others live in the build, and a develop visit
# by the specialist that owns them does. `owner` is the specialist-routing label triage is
# expected to route to (core/reference/specialist-routing.yaml): the tests assert it, this
# fixture only uses it to decide which visit fixes what.
DEFECTS = {
    "remove-content": {"where": "build"},
    "reduce-variety": {"where": "build"},
    "broken-mobile-layout": {"where": "build"},
    "severe-visual-defect": {"where": "build"},
    "remove-progression": {"where": "build"},
    "placeholder-assets": {"where": "art"},
    "broken-win-lose": {"where": "build"},
    "performance-regression": {"where": "build"},
    "duplicate-level": {"where": "build"},
    "thin-audio": {"where": "art"},
    "kinds-omitted": {"where": "build"},
    "flat-progression": {"where": "build"},
}


def digest(value):
    return hashlib.sha1(json.dumps(value, sort_keys=True).encode("utf-8")).hexdigest()


def _box(role, slot, viewport):
    """Where an entity of `role` is drawn on a viewport: CSS px [x, y, w, h]."""
    w, h = viewport
    size = 0.12 * min(w, h)
    columns = {"player": 0.15, "threat": 0.45, "goal": 0.75, "target": 0.6,
               "projectile": 0.3, "collectible": 0.85, "hazard": 0.55}
    x = columns.get(role, 0.5) * w + slot * size * 0.3
    y = (0.45 if role == "player" else 0.3) * h + slot * size * 0.5
    return [round(x, 1), round(y, 1), round(size, 1), round(size, 1)]


class World:
    """One scenario's virtual game: the design, the degradations, the fixes, every build."""

    def __init__(self, scenario, design, checkout):
        self.scenario = scenario
        self.design = design
        self.checkout = checkout
        self.family = design["genre"]["family"]
        self.dimension = (design.get("engine") or {}).get("dimension") or "2d"
        self.builds = {}
        # The defects the next build carries; the art state the assets step leaves.
        self.defects = set(scenario.get("defects") or [])
        self.art_defects = {d for d in self.defects if DEFECTS[d]["where"] == "art"}
        # What a specialist's visit does: {owner label: {"fixes": [...], "breaks": [...]}}.
        self.fixes = copy.deepcopy(scenario.get("fixes") or {})
        self.visits = []
        self.spec = design["build_spec"]
        self.units = [u for u in self.spec["content"]["units"] if u.get("tier") != "optional"]
        self.qa = genre_models.qa_of(design)

    # -- the developer ------------------------------------------------------------------------

    def develop(self, phase, label):
        """A develop visit: the build it makes. A specialist (`label`) removes the defects the
        scenario's fix map gives it - and adds what that fix breaks."""
        if label:
            self.apply(label)
        return self.build(phase)

    def remake_assets(self):
        """The assets step re-entered: the art the scenario's fix map gives `assets` is made
        again (and whatever that breaks)."""
        self.apply("assets")

    def apply(self, label):
        plan = self.fixes.get(label) or {}
        for defect in plan.get("fixes") or []:
            self.defects.discard(defect)
            self.art_defects.discard(defect)
        for defect in plan.get("breaks") or []:
            self.defects.add(defect)
            if DEFECTS[defect]["where"] == "art":
                self.art_defects.add(defect)
        plan["visits"] = plan.get("visits", 0) + 1
        self.fixes[label] = plan
        self.visits.append(label)

    def build(self, phase):
        # The degradations are the production build's: the greybox is the loop in primitives,
        # before any of what they take away exists.
        active = sorted(d for d in self.defects if DEFECTS[d]["where"] == "build")             if phase == "production" else []
        self.count = getattr(self, "count", 0) + 1
        body = {"family": self.family, "phase": phase, "defects": active,
                "design": self.design["provenance"]["content_hash"],
                "art": sorted(self.art_defects), "build": self.count}
        commit = (digest(body) * 2)[:40]
        build = dict(body, commit=commit)
        self.builds[commit] = build
        return build

    def sdk_commit(self, dev_commit):
        return (digest(["sdk", dev_commit]) * 2)[:40]

    def build_of(self, commit):
        return self.builds.get(commit)

    # -- what the build ships -----------------------------------------------------------------

    def built_units(self, build):
        """The content data file's units: the design's, as the build shipped them."""
        out = []
        units = list(self.units)
        if "remove-content" in build["defects"]:
            units = units[:len(units) - max(4, len(units) // 3)]
        for unit in units:
            entry = {k: copy.deepcopy(unit[k]) for k in (
                "id", "index", "tier", "objective", "mechanics", "difficulty",
                "expected_duration_s", "success", "failure", "group", "structure",
                "objective_kind", "purpose", "elements") if k in unit}
            if unit.get("art"):
                entry["art"] = list(unit["art"])
            entry["layout"] = copy.deepcopy(unit.get("parameters") or {})
            if "reduce-variety" in build["defects"]:
                entry["elements"] = list(self.units[0]["elements"][:1])
            out.append(entry)
        if "duplicate-level" in build["defects"]:
            # Two units of the second group are the same level: one ships the other's layout.
            pairs = [(i - 1, i) for i in range(1, len(out))
                     if out[i].get("group") == "g2" and out[i - 1].get("group") == "g2"
                     and out[i].get("purpose") != "climax"
                     and out[i - 1].get("purpose") != "climax"]
            a, b = pairs[-1]
            out[b]["layout"] = copy.deepcopy(out[a]["layout"])
        return out

    def content_data(self, build):
        units = self.built_units(build)
        data = {"schema": "wgf-content/1", "unit_kind": self.spec["content"]["unit_kind"],
                "generation": {"mode": "authored"}, "units": units}
        if not {"remove-progression", "flat-progression"} & set(build["defects"]):
            groups = [g["id"] for g in self.spec["content"].get("groups") or []]
            data["unlocks"] = [{"opens": later, "after": earlier,
                                "condition": f"clear the {earlier} climax"}
                               for earlier, later in zip(groups, groups[1:])]
        return data

    def unit_kinds(self, build, unit):
        """The entity kinds the probe reports inside `unit`."""
        built = {u["id"]: u for u in self.built_units(build)}.get(unit["id"])
        if built is None:
            return []
        kinds = list(built.get("elements") or [])
        if unit.get("purpose") == "climax" and "reduce-variety" not in build["defects"]:
            kinds += [f"{a}-boss" for a in unit.get("art") or []]
        return kinds

    # -- the asset manifest -------------------------------------------------------------------

    def manifest_items(self):
        placeholder = "placeholder-assets" in self.art_defects
        items = []
        for asset in self.spec.get("assets") or []:
            fmt = {"model": "glb", "font": "woff2"}.get(asset["type"], "png")
            folder = "models" if asset["type"] == "model" else "sprites"
            item = {"id": asset["id"], "label": asset["id"].replace("-", " ").title(),
                    "type": asset["type"], "dimension": self.dimension, "source": "procedural",
                    "est_cost": 0, "est_hours": 1, "status": "integrated",
                    "license": "LicenseRef-generated", "license_status": "generated",
                    "scope_tier": "mvp" if asset.get("tier") == "mvp" else "production",
                    "role": asset.get("role") or "prop",
                    "placeholder": placeholder and asset.get("role") == "player",
                    "production_ready": not (placeholder and asset.get("role") == "player"),
                    "quality": {"verdict": "pass", "checks": []},
                    "files": [{"path": f"public/assets/{folder}/{asset['id']}.{fmt}",
                               "format": fmt, "bytes": 2048,
                               "content_hash": "sha256:" + hashlib.sha256(
                                   asset["id"].encode()).hexdigest()}]}
            items.append(item)
        sounds = [a for a in self.spec.get("audio") or [] if a.get("type") in ("music", "sfx")]
        wanted_sfx = 3 if "thin-audio" in self.art_defects else SFX_IN_A_RELEASE
        sfx = [a["id"] for a in sounds if a["type"] == "sfx"]
        n = 0
        while len(sfx) < wanted_sfx:
            n += 1
            sfx.append(f"sfx-variant-{n}")
        sfx = sfx[:wanted_sfx]
        music = [a["id"] for a in sounds if a["type"] == "music"] or ["music-main"]
        for sound_id, sound_type in [(m, "music") for m in music] + [(s, "sfx") for s in sfx]:
            items.append({"id": sound_id, "label": sound_id, "type": sound_type,
                          "dimension": self.dimension, "source": "procedural", "est_cost": 0,
                          "est_hours": 1, "status": "integrated",
                          "license": "LicenseRef-generated", "license_status": "generated",
                          "scope_tier": "mvp", "placeholder": False, "production_ready": True,
                          "quality": {"verdict": "pass", "checks": []},
                          "files": [{"path": f"public/assets/audio/{sound_id}.ogg",
                                     "format": "ogg", "bytes": 4096,
                                     "content_hash": "sha256:" + hashlib.sha256(
                                         sound_id.encode()).hexdigest()}]})
        return items

    def runtime_assets(self, items):
        assets = {}
        for item in items:
            files = item.get("files") or []
            if not files:
                continue
            path = files[0]["path"][len("public/assets/"):]
            assets[item["id"]] = {"type": item["type"], "url": path}
        return {"format": "wgf-runtime-assets", "version": 1, "assets": assets, "atlases": {}}

    def entity_assets(self):
        """{role: [asset id]} of the design's mvp assets an entity is drawn with."""
        out = {}
        for asset in self.spec.get("assets") or []:
            if asset.get("tier") == "mvp" and asset.get("role") in ENTITY_ROLES:
                out.setdefault(asset["role"], []).append(asset["id"])
        return out

    # -- what the bot records -----------------------------------------------------------------

    def metrics(self, unit=None, **overrides):
        ex = self.spec.get("experience") or {}
        names = {(ex.get(k) or {}).get("metric") for k in ("goal", "win", "lose")}
        names |= {h.get("metric") for h in self.spec.get("hud") or []}
        for action in ex.get("actions") or []:
            names |= set(action.get("updates") or [])
        names.add("best")
        resource = (self.qa.get("genre") or {}).get("resource_metric")
        if resource:
            names.add(resource)
        out = {n: 0 for n in sorted(n for n in names if n)}
        lose_metric = (ex.get("lose") or {}).get("metric")
        if lose_metric:
            out[lose_metric] = 3
        if resource:
            out[resource] = 100
        out["best"] = 120
        if unit is not None:
            out["unit"] = unit["index"]
            for axis, value in (unit.get("difficulty") or {}).items():
                out[f"difficulty.{axis}"] = value
        out.update(overrides)
        return out

    def content(self, unit, value=0, target=3):
        if unit is None:
            return {"unit_id": None, "unit_index": 0, "unit_count": len(self.units),
                    "unit_kind": self.spec["content"]["unit_kind"]}
        return {"unit_id": unit["id"], "unit_index": unit["index"],
                "unit_count": len(self.units), "unit_kind": self.spec["content"]["unit_kind"],
                "objective": unit["objective"],
                "progress": {"metric": "progress", "value": value, "target": target}}

    def entities(self, build, project, unit, render="asset"):
        viewport = VIEWPORTS[project]
        kinds = self.unit_kinds(build, unit) if unit else []
        out = []
        for role, assets in sorted(self.entity_assets().items()):
            for slot, asset_id in enumerate(assets):
                x, y, w, h = _box(role, slot, viewport)
                entity = {"id": f"{asset_id}-{slot}", "role": role, "x": x, "y": y, "w": w,
                          "h": h, "visible": True, "asset": asset_id, "render": render}
                if role in CONTENT_ROLES and "kinds-omitted" not in build["defects"]:
                    entity["kind"] = (kinds[slot % len(kinds)] if kinds else f"{asset_id}")
                if role == "player":
                    entity["kind"] = "pilot"
                out.append(entity)
        return out

    def inputs(self, project):
        w, h = VIEWPORTS[project]
        return [{"action": a["id"], "input": {"type": "pointer", "x": round(w * 0.5),
                                              "y": round(h * 0.6)}}
                for a in (self.spec.get("controls") or {}).get("actions") or []]

    def snapshot(self, build, project, state="playing", unit=None, metrics=None, value=0):
        unit = unit if unit is not None else (self.units[0] if state == "playing" else None)
        snap = {"state": state, "metrics": metrics or self.metrics(unit),
                "content": self.content(unit, value=value),
                "entities": self.entities(build, project, unit) if state == "playing" else [],
                "inputs": self.inputs(project) if state == "playing" else [],
                "assets_loaded": sorted(a for ids in self.entity_assets().values() for a in ids),
                "audio": {"music": self.music_id(), "playing": state == "playing",
                          "level": 0.06 if state == "playing" else 0.0,
                          "muted": state != "playing"}}
        return snap

    def music_id(self):
        music = [a["id"] for a in self.spec.get("audio") or [] if a.get("type") == "music"]
        return music[0] if music else "music-main"

    def screens(self, build, project):
        viewport = VIEWPORTS[project]
        broken = project == "mobile" and "broken-mobile-layout" in build["defects"]

        def button(text, box):
            return {"tag": "button", "role": None, "text": text, "box": box, "font_px": 20,
                    "font_weight": 700, "color": WHITE, "background": NAVY,
                    "ua_default": False, "ua_differs": ["background-color", "color"]}

        w, h = viewport
        size = 30 if broken else 64
        retry = button("Retry", [round(w * 0.4), round(h * 0.6), size * 2, size])
        play = button("Play", [round(w * 0.4), round(h * 0.55), size * 2, size])
        pause = button("Pause", [round(w * 0.85), round(h * 0.02), size, size])
        texts = [{"text": "Score 3", "box": [10, 10, 140, 28], "font_px": 22,
                  "font_weight": 700, "color": WHITE, "background": NAVY}]
        overlaps = ([{"a": 0, "text": 0, "kind": "text", "area_px": 900}] if broken else [])

        def screen(name, elements=(), entities=None):
            entry = {"probe_state": name, "frame": f"state-{name}", "viewport": list(viewport),
                     "elements": list(elements), "texts": copy.deepcopy(texts),
                     "overlaps": copy.deepcopy(overlaps) if elements else [],
                     "probe_ui": []}
            if entities is not None:
                entry["entities"] = entities
            return entry

        playing = screen("playing", [pause], self.entities(build, project, self.units[0]))
        out = {"title": screen("title", [play]), "playing": playing,
               "lost": screen("lost", [retry]), "retry": screen("retry", [pause])}
        if "win" in (self.spec.get("experience") or {}):
            out["won"] = screen("won", [retry])
        return out

    def records(self, build, project, items):
        """{test: record} for one viewport, as bot.spec.ts writes them."""
        ex = self.spec.get("experience") or {}
        genre = self.qa.get("genre") or {}
        first_unit = self.units[0]
        runtime = self.runtime_assets(items)
        requests = [{"url": "/assets/assets.json", "status": 200}] + [
            {"url": "/assets/" + entry["url"], "status": 200}
            for entry in runtime["assets"].values()]
        common = {"asset_requests": requests, "runtime_assets": runtime, "errors": [],
                  "audio": [{"state": "playing", "playing": True, "level": 0.06,
                             "music": self.music_id()}] * 3,
                  "audio_unfocused": [{"state": "playing", "level": 0.0}]}
        screens = self.screens(build, project)
        goal = (ex.get("goal") or {}).get("metric")
        broken = "broken-win-lose" in build["defects"]

        playing = self.snapshot(build, project, "playing", first_unit)
        first = dict(common, firstSnapshotMs=200, playingMs=900, observerMs=0,
                     samples=[self.snapshot(build, project, "title"), playing],
                     texts=[ex.get("goal", {}).get("statement") or "", first_unit["objective"]],
                     lostAtMs=None, frames=["first-session-1s", "play-2s"],
                     assets_loaded=playing["assets_loaded"],
                     ui={k: v for k, v in screens.items() if k in ("title", "playing")})
        acted = []
        for action in ex.get("actions") or []:
            acted.append({"action": action["action"], "before": copy.deepcopy(playing),
                          "after": copy.deepcopy(playing)})
        act = dict(common, acted=acted)

        frames = []
        for step in range(30):
            row = []
            for e in playing["entities"]:
                x = e["x"] + (step * 4 if e["role"] == "projectile" else 0)
                row.append([e["id"], e["role"], 1, x, e["y"], e["w"], e["h"], e["asset"],
                            e["render"]])
            frames.append(row)
        sampled = {"frames": frames, "viewport": list(VIEWPORTS[project])}
        win = dict(common, sampled=sampled, inputs=12,
                   reached=None if broken else ("won" if "win" in ex else None),
                   series=[{"ms": 0, "value": 0, "state": "playing"},
                           {"ms": 900, "value": 0 if broken else 7, "state": "playing"}],
                   ui={k: v for k, v in screens.items() if k == "won"})
        resource = genre.get("resource_metric")
        initial = self.metrics(first_unit)
        lose_series = [{"ms": 0, "metrics": dict(initial)}]
        if resource:
            lose_series.append({"ms": 900, "metrics": dict(initial, **{resource: 40})})
        end_content = self.content(first_unit, value=1)
        lose = dict(common, reached=None if broken else "lost", initial=initial,
                    series=lose_series, endedAtMs=4000, contentAtEnd=end_content,
                    initialContent=self.content(first_unit),
                    restart={"clicked": "button", "playingMs": 300,
                             "metrics": dict(initial), "content": copy.deepcopy(end_content)},
                    frames=["end-lost"],
                    ui={k: v for k, v in screens.items() if k in ("lost", "retry")})
        if genre.get("reset_in_unit"):
            lose["resetInUnit"] = {"clicked": "reset", "playingMs": 250,
                                   "before": {"progress": {"value": 2}},
                                   "after": {"progress": {"value": 0}}}
        pause = dict(common, reached="paused")
        out = {"first-session": first, "act": act, "win": win, "lose": lose, "pause": pause}

        # The content: the first units played in order, every unit surveyed (desktop only).
        bars = self.qa.get("content") or {}
        want = min(len(self.units), int(bars.get("min_units_traversed") or 1))
        played = self.units[:want + 1]
        per_unit, transitions = [], []
        for n, unit in enumerate(played):
            per_unit.append({"unit_id": unit["id"], "index": unit["index"],
                             "kinds": self.unit_kinds(build, unit) + ["pilot"],
                             "difficulty": dict(unit.get("difficulty") or {}),
                             "won": n < want, "lost": False,
                             "objective_texts": [unit["objective"]],
                             "metrics": self.metrics(unit)})
            if n:
                transitions.append({"from": played[n - 1]["index"], "to": unit["index"],
                                    "how": "won", "since_end_ms": 400})
        out["traverse"] = {"applies": True, "per_unit": per_unit, "transitions": transitions,
                           "stopped": "max units",
                           "snapshots": [{"ms": 1000 * n, "unit_id": u["unit_id"],
                                          "kinds": u["kinds"]} for n, u in enumerate(per_unit)]}

        before = self.snapshot(build, project, "title", None, metrics=self.metrics(None))
        before["content"] = dict(self.content(None), unit_index=2)
        after = copy.deepcopy(before)
        if "remove-progression" in build["defects"]:
            after["metrics"] = {k: 0 for k in after["metrics"]}
            after["content"]["unit_index"] = 1
        out["persist"] = {"before": before, "after": after}

        depth = self.spec.get("depth") or {}
        target_s = (depth.get("first_session") or {}).get("target_s") or 180
        windows = []
        axes = [a["id"] for a in genre_models.axes_of(self.design)]
        for n in range(4):
            windows.append({"ms": n * 30000,
                            "difficulty": {a: round(0.1 + 0.1 * n, 2) for a in axes}})
        out["session"] = {"length_ms": int(target_s * 1000), "target_ms": int(target_s * 1000),
                          "beat_at_ms": int(target_s * 900), "ended_on": "beat",
                          "windows": windows,
                          "runs": [{"duration_ms": int(target_s * 1000),
                                    "oracle_inputs_per_third": [10, 12, 14]}]}
        if project == "desktop":
            data = {u["id"]: u for u in self.built_units(build)}
            visits = []
            for unit in self.units:
                inside = unit["id"] in data
                kinds = self.unit_kinds(build, unit) if inside else []
                assets = [a for ids in self.entity_assets().values() for a in ids
                          if a not in self.entity_assets().get("player", [])]
                if unit.get("art") and "reduce-variety" not in build["defects"]:
                    assets = assets + list(unit["art"])
                visits.append({
                    "asked": unit["id"], "entered": inside,
                    "reported": [unit["id"]] if inside else [],
                    "index": unit["index"] if inside else None,
                    "kinds_by_role": ({"threat": kinds, "player": ["pilot"]} if inside else {}),
                    "assets_by_role": ({"threat": assets,
                                        "player": self.entity_assets().get("player", [])}
                                       if inside else {}),
                    "content_entities": len(kinds) if inside else 0,
                    "unkinded": (len(kinds) if "kinds-omitted" in build["defects"] else 0)
                    if inside else 0,
                    "difficulty": dict(unit.get("difficulty") or {}) if inside else {},
                    "won": inside, "lost": False,
                    "duration_ms": int(unit.get("expected_duration_s", 30) * 700)
                    if inside else None,
                    "playing_ms": 800})
            out["survey"] = {"applies": True, "visits": visits}
        return out

    # -- frames -------------------------------------------------------------------------------

    def paint(self, path, build, project, kind="play", extra=None):
        """A frame of `project`: the scene, the entities at their boxes, the HUD; `extra`
        is one more box (CSS px) painted in the accent colour - an action's acknowledgement."""
        vw, vh = VIEWPORTS[project]
        w, h = max(8, int(vw * FRAME_SCALE)), max(8, int(vh * FRAME_SCALE))
        scale = w / float(vw)
        pixels = bytearray(bytes([*BACKGROUND, 255]) * (w * h))

        def fill(box, colour):
            x0, y0 = int(box[0] * scale), int(box[1] * scale)
            x1, y1 = int((box[0] + box[2]) * scale) + 1, int((box[1] + box[3]) * scale) + 1
            for y in range(max(0, y0), min(h, y1)):
                for x in range(max(0, x0), min(w, x1)):
                    i = (y * w + x) * 4
                    pixels[i:i + 3] = bytes(colour)

        fill([0, 0, vw, vh * 0.06], HUD)
        if kind in ("play", "state-playing", "state-retry"):
            for e in self.entities(build, project, self.units[0]):
                fill([e["x"], e["y"], e["w"], e["h"]], ENTITY)
        else:
            fill([vw * 0.3, vh * 0.35, vw * 0.4, vh * 0.3], ACCENT)
        if extra:
            fill(extra, ACCENT)
        if "severe-visual-defect" in build["defects"] and kind != "act-before":
            # A third of the play area cut off by a band the renderer never drew into.
            fill([0, vh * 0.55, vw, vh * 0.45], (0, 0, 0))
            fill([vw * 0.05, vh * 0.6, vw * 0.9, vh * 0.05], MAGENTA)
        with open(path, "wb") as handle:
            handle.write(encode_png(Image(w, h, bytes(pixels))))

    def write_frames(self, directory, build, project):
        os.makedirs(directory, exist_ok=True)

        def frame(name, kind="play", extra=None):
            self.paint(os.path.join(directory, f"{name}.png"), build, project, kind, extra)

        frame("first-session-1s")
        frame("play-2s")
        vw, vh = VIEWPORTS[project]
        for action in (self.spec.get("experience") or {}).get("actions") or []:
            frame(f"act-{action['action']}-before", "act-before")
            frame(f"act-{action['action']}-after", "play", [vw * 0.4, vh * 0.4, vw * 0.2, vh * 0.2])
        for state in self.screens(build, project):
            frame(f"state-{state}", f"state-{state}")
        frame("end-lost", "end")


# -- the fixture steps -----------------------------------------------------------------------

def _seal(step, artifact_type, body, inputs, context, role, also=()):
    """`body` as an artifact of the run, with provenance as the placeholder steps build it;
    `also` pins artifacts this step produced first ([(type, sealed content)])."""
    slug = context.project_id or mock.FIXTURE_SLUG
    epoch = (context.environment or {}).get("mock_epoch") or mock.DEFAULT_EPOCH
    pins = provenance.pin_inputs(inputs)
    for other_type, other in also:
        pins.append(provenance.pin(other_type, other,
                                   other["provenance"]["content_hash"]))
    artifact = {"provenance": provenance.build(
        artifact_type,
        artifact_id=provenance.artifact_id(artifact_type, slug, epoch, min(context.execution, 99)),
        produced_by=provenance.producer(role), produced_at=epoch,
        inputs=pins, title_id=slug)}
    artifact.update(body)
    return ArtifactOutput(artifact_type, provenance.seal(artifact))


def _fixture_body(artifact_type, context):
    slug = context.project_id or mock.FIXTURE_SLUG
    with open(os.path.join(mock.FIXTURES, f"{artifact_type}.json"), encoding="utf-8") as handle:
        return json.loads(handle.read().replace(mock.FIXTURE_SLUG, slug))


class _Fixture(mock.MockStep):
    world = None

    def __init__(self, definition, world=None):
        super().__init__(definition)
        self.world = world


class FixtureDesignStep(_Fixture):
    """The release-tier design the real design step wrote for the scenario's family."""
    type, role = "design", "game-designer"

    def execute(self, inputs, context):
        body = copy.deepcopy(self.world.design)
        body.pop("provenance", None)
        body["title_id"] = context.project_id or mock.FIXTURE_SLUG
        return StepResult.success([_seal(self, "game-design", body, inputs, context,
                                         self.role)], message="design (fixture)")


class FixtureInitStep(mock.MockInitStep):
    world = None

    def __init__(self, definition, world=None):
        super().__init__(definition)
        self.world = world

    def customize(self, body, artifact_type, context, entry):
        super().customize(body, artifact_type, context, entry)
        if artifact_type == "scaffold-record":
            body["repository"]["local_path"] = self.world.checkout


class FixtureAssetsStep(_Fixture):
    """The asset manifest of the design's assets and audio. Re-entered (a gate or triage
    routed `assets`), the art defects are made again."""
    type, role = "assets", "asset"

    def execute(self, inputs, context):
        if context.visit > 1:
            self.world.remake_assets()
        items = self.world.manifest_items()
        body = {"title_id": context.project_id or mock.FIXTURE_SLUG, "items": items,
                "total_est_cost": 0, "total_est_hours": float(len(items)), "complete": True}
        return StepResult.success([_seal(self, "asset-manifest", body, inputs, context,
                                         self.role)], message="assets (fixture)")


class FixtureDevelopStep(_Fixture):
    """The developer: the build the design describes, the scenario's defects in it. Entered
    by triage as a specialist (wgf_develop.specialist.resolve, the real reader), it removes
    the defects that specialist owns in the scenario's fix map, records the visit in the
    prototype-report's `specialist` block, and returns `next-specialist` while the triage
    that routed it has groups pending - as the real develop step does."""
    type, role = "develop", "gameplay"

    def execute(self, inputs, context):
        phase = (self.params or {}).get("phase") or "production"
        spec, problem = specialists.resolve(context, inputs, phase)
        if problem:
            return StepResult.failed(problem, retryable=False)
        build = self.world.develop(phase, spec["role"] if spec else None)
        body = _fixture_body("prototype-report", context)
        body["build_ref"]["commit_sha"] = build["commit"]
        body["iteration"] = context.visit
        if spec:
            body["specialist"] = {"role": spec["role"],
                                  "findings": [f["id"] for f in spec["findings"]],
                                  "pending": list(spec["pending"]),
                                  "triage_report": spec["triage_report"],
                                  "source": spec["source"], "sessions": 1, "cost_usd": 3.5}
        artifact = _seal(self, "prototype-report", body, inputs, context, self.role)
        if spec and spec["pending"]:
            return StepResult.success([artifact], route=specialists.NEXT_SPECIALIST,
                                      message=f"{spec['role']} visit (fixture)")
        return StepResult.success([artifact], message=f"{phase} build {build['commit'][:12]}")


class FixturePlayabilityStep(PlayabilityStep):
    """The real playability step with the bot replaced: nothing is cloned, built or played;
    the records and frames are written from the build, and the step judges them as it judges
    a real bot's."""

    world = None

    def __init__(self, definition, world=None):
        super().__init__(definition)
        self.world = world
        self._commit = None

    def execute(self, inputs, context):
        prototype = inputs.load("prototype-report") if "prototype-report" in inputs else {}
        self._commit = ((prototype or {}).get("build_ref") or {}).get("commit_sha")
        self._manifest = inputs.load("asset-manifest") if "asset-manifest" in inputs else None
        return super().execute(inputs, context)

    def _prepare(self, located, commit, repo, logs, context):
        return None

    def _keep_content_data(self, repo, out):
        build = self.world.build_of(self._commit)
        target = os.path.join(out, "content", "units.json")
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w", encoding="utf-8") as handle:
            json.dump(self.world.content_data(build), handle)

    def _play(self, repo, out, logs, settings, context, bot_total_s=0, survey_s=0):
        build = self.world.build_of(self._commit)
        items = self.world.manifest_items()
        for project in VIEWPORTS:
            directory = os.path.join(out, project)
            os.makedirs(directory, exist_ok=True)
            for name, record in self.world.records(build, project, items).items():
                if name == "survey" and not settings.get("survey_units"):
                    record = {"applies": False, "reason": "no survey was asked for",
                              "visits": []}
                with open(os.path.join(directory, f"{name}.json"), "w",
                          encoding="utf-8") as handle:
                    json.dump(record, handle)
            self.world.write_frames(os.path.join(directory, "frames"), build, project)
        return None


class FixtureReviewStep(mock.MockReviewStep):
    """A reviewer that ran and approved the commit it was shown (reviewer kind `command`):
    the code review is not what this suite measures."""

    def customize(self, body, artifact_type, context, entry):
        super().customize(body, artifact_type, context, entry)
        if artifact_type == "review-report":
            body["reviewer"] = {"kind": "command", "argv0": "fixture-reviewer", "exit_code": 0,
                                "status": "ok", "killed_pids": []}
            body["notes"] = "Fixture reviewer: approves the commit it is shown."


class FixtureSDKStep(_Fixture):
    type, role = "sdk", "sdk"

    def execute(self, inputs, context):
        prototype = inputs.load("prototype-report")
        dev = prototype["build_ref"]["commit_sha"]
        body = _fixture_body("sdk-report", context)
        body["build_ref"] = {"commit_sha": self.world.sdk_commit(dev), "base_commit_sha": dev}
        return StepResult.success([_seal(self, "sdk-report", body, inputs, context,
                                         self.role)], message="sdk (fixture)")


class FixtureVerifyStep(_Fixture):
    """qa-report and verification-report of the sdk commit, with the frame rate the build
    runs at: a build carrying `performance-regression` runs at 24 fps against a 60 fps
    budget."""
    type, role = "verify", "qa"

    def execute(self, inputs, context):
        sdk = inputs.load("sdk-report")
        prototype = inputs.load("prototype-report")
        ship = sdk["build_ref"]["commit_sha"]
        build = self.world.build_of(prototype["build_ref"]["commit_sha"]) or {"defects": []}
        slow = "performance-regression" in build["defects"]
        qa = _fixture_body("qa-report", context)
        qa["build_ref"] = {"commit_sha": ship}
        qa["evidence_status"] = "PASS_MOCK"
        qa["workflow"] = {"run_id": context.run_id, "step_id": self.id, "visit": context.visit}
        qa["perf_results"] = [{"device_class": "mid-range-mobile", "fps": 24 if slow else 60,
                               "within_budget": not slow}]
        vr = _fixture_body("verification-report", context)
        vr["commit"] = {"sha": ship, "dirty": False}
        vr["build_artifact"] = {"status": "built",
                                "content_hash": "sha256:" + hashlib.sha256(
                                    ship.encode()).hexdigest()}
        vr["evidence_status"] = "PASS_MOCK"
        vr["platform_readiness"] = [{"platform_id": "yandex", "profile": "yandex@1.2.0",
                                     "role": "required", "readiness": "ready",
                                     "checks": ["build.build"], "blocking_checks": [],
                                     "external_approval": "not-claimed",
                                     "evidence_status": "PASS_MOCK"}]
        verification = _seal(self, "verification-report", vr, inputs, context, self.role)
        report = _seal(self, "qa-report", qa, inputs, context, self.role,
                       also=[("verification-report", verification.content)])
        return StepResult.success([verification, report], message="verify (fixture)")


class FixtureListingStep(mock.MockStoreListingStep):
    """The placeholder store package, of the build the run verified."""

    def execute(self, inputs, context):
        qa = inputs.load("qa-report") if "qa-report" in inputs else {}
        self._commit = ((qa or {}).get("build_ref") or {}).get("commit_sha")
        return super().execute(inputs, context)

    def customize(self, body, artifact_type, context, entry):
        super().customize(body, artifact_type, context, entry)
        if artifact_type == "store-listing" and self._commit:
            body["commit"] = self._commit


class FixtureListingValidationStep(mock.MockListingValidationStep):
    """The placeholder validation, of exactly the listing the run holds."""

    def execute(self, inputs, context):
        ref = inputs.refs.get("store-listing")
        self._pinned = getattr(ref, "content_hash", None)
        return super().execute(inputs, context)

    def customize(self, body, artifact_type, context, entry):
        super().customize(body, artifact_type, context, entry)
        if artifact_type == "listing-validation-report" and self._pinned:
            body.setdefault("listing", {})["content_hash"] = self._pinned


class FixtureReleaseStep(_Fixture):
    """The release step's refusals, as the real step decides them
    (wgf_release.lineage.evidence_refusals, with its defaults: G4 required, both production
    reports, the validated listing and the quality report). No refusal: a draft manifest.
    Packaging is not this suite's concern."""
    type, role = "release", "release"

    def execute(self, inputs, context):
        loaded = {t: inputs.load(t) for t in sorted(inputs.refs)}
        refusals = evidence_refusals(
            inputs.refs, loaded, context.run_id,
            gates_passed=getattr(context, "gates_passed", None) or (),
            required_gates=(self.params or {}).get("required_gates", ["G4"]),
            required_quality=(self.params or {}).get("required_quality", True))
        self.world.refusals = [r.to_dict() for r in refusals]
        if refusals:
            blocked = all(r.kind == BLOCKED for r in refusals)
            text = "release refused: " + "; ".join(f"[{r.code}] {r.message}" for r in refusals)
            if blocked:
                return StepResult.blocked(text)
            return StepResult.failed(text, retryable=False)
        return super().execute(inputs, context)


def register(registry, world):
    """Replace every step that would call an agent or a toolchain with its fixture."""
    from wgf_production import register as production
    from wgf_quality import register as quality_gate
    from wgf_sufficiency import register as sufficiency
    from wgf_triage import register as triage
    from wgf_visualqa import register as visualqa
    mock.register(registry)
    for module in (production, quality_gate, sufficiency, triage, visualqa):
        module(registry)
    for cls in (FixtureReviewStep, FixtureListingStep, FixtureListingValidationStep):
        registry.register(cls.type, cls)
    for cls in (FixtureDesignStep, FixtureInitStep, FixtureAssetsStep, FixtureDevelopStep,
                FixtureSDKStep, FixtureVerifyStep, FixtureReleaseStep, FixturePlayabilityStep):
        registry.register(cls.type, (lambda c: (lambda d: c(d, world)))(cls))
    return registry

"""The production-quality step (scripts/wgf_production): what the playability bot recorded,
held to production art and production UI.

The bot (scripts/wgf_playability/bot.spec.ts) records; checks.judge decides. These tests write
records as the bot does - entity samples with asset and render, the requests for files under
/assets/, the DOM UI measured on each screen state - for a production build and for each way
a build falls short: a greybox (entities drawn as primitives from no asset), a placeholder
asset in the manifest, tiny browser-default buttons, text that cannot be read, a missing
result screen. And the step's routing: an asset problem goes back to `assets`, everything
else to `develop`; no records is BLOCKED.

    python -m unittest scripts.tests.test_production_quality
"""

import copy
import json
import os
import shutil
import sys
import tempfile
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
sys.path.insert(0, SCRIPTS)

from wgf_assets.raster import Image, encode_png  # noqa: E402
from wgf_production import checks as judging  # noqa: E402
from wgf_production.step import ProductionQualityStep, load_rules  # noqa: E402
from wgflib.workflow.contracts import ArtifactContracts  # noqa: E402
from wgflib.workflow.model import StepOutcome  # noqa: E402

COMMIT = "c" * 40

DESIGN = {"title_id": "demo", "build_spec": {
    "assets": [
        {"id": "keeper", "type": "sprite", "tier": "mvp", "role": "player", "description": "x",
         "count": 1, "source_preference": "library", "est_cost": 0},
        {"id": "striker", "type": "sprite", "tier": "mvp", "role": "threat", "description": "x",
         "count": 1, "source_preference": "library", "est_cost": 0},
        {"id": "confetti", "type": "vfx", "tier": "post-mvp", "role": "vfx", "description": "x",
         "count": 1, "source_preference": "procedural", "est_cost": 0},
    ],
    "visual_identity": {"concept": "x", "palette": [], "typography": {"display": "x", "body": "x"},
                        "shape_language": "x", "motion": "x", "avoid": ["x"]},
    "experience": {"goal": {"statement": "Save eight shots.", "metric": "saves", "shown_on": "play"},
                   "win": {"condition": "Eight saves.", "metric": "saves"},
                   "lose": {"condition": "No lives.", "metric": "lives"}},
}}


def item(asset_id, role, **extra):
    base = {"id": asset_id, "type": "sprite", "source": "library", "est_cost": 0, "est_hours": 0,
            "status": "integrated", "scope_tier": "mvp", "role": role, "placeholder": False,
            "quality": {"verdict": "pass", "checks": []},
            "files": [{"path": f"public/assets/sprites/{asset_id}.svg", "format": "svg", "bytes": 1,
                       "content_hash": "sha256:" + "0" * 64}]}
    base.update(extra)
    return base


MANIFEST = {"title_id": "demo", "items": [item("keeper", "player"), item("striker", "threat")],
            "total_est_cost": 0, "total_est_hours": 0, "complete": True}

RUNTIME = {"format": "wgf-runtime-assets", "version": 1,
           "assets": {"keeper": {"type": "sprite", "url": "sprites/keeper.svg"},
                      "striker": {"type": "sprite", "atlas": "main", "frame": "striker"}},
           "atlases": {"main": {"url": "atlases/main.png", "data": "atlases/main.json"}}}

REQUESTS = [{"url": "/assets/assets.json", "status": 200},
            {"url": "/assets/sprites/keeper.svg", "status": 200},
            {"url": "/assets/atlases/main.png", "status": 200},
            {"url": "/assets/atlases/main.json", "status": 200}]

WHITE, NAVY = [255, 255, 255, 1], [20, 30, 60]


def button(text, box, **extra):
    base = {"tag": "button", "role": None, "text": text, "box": box, "font_px": 20,
            "font_weight": 700, "color": WHITE, "background": NAVY, "ua_default": False,
            "ua_differs": ["background-color", "color"]}
    base.update(extra)
    return base


def screen(name, elements=(), texts=None, overlaps=(), viewport=(393, 851)):
    return {"probe_state": name, "frame": f"state-{name}", "viewport": list(viewport),
            "elements": list(elements),
            "texts": [{"text": "Saves 3", "box": [10, 10, 120, 28], "font_px": 22,
                       "font_weight": 700, "color": WHITE, "background": NAVY}]
            if texts is None else texts,
            "overlaps": list(overlaps), "probe_ui": []}


def entities(asset=True, render="asset"):
    return [{"id": "keeper", "role": "player", "x": 100, "y": 100, "w": 60, "h": 80, "visible": True,
             "asset": "keeper" if asset else None, "render": render},
            {"id": "striker", "role": "threat", "x": 150, "y": 40, "w": 60, "h": 80, "visible": True,
             "asset": "striker" if asset else None, "render": render}]


FRAMES = None


def setUpModule():
    """A state frame as the bot captures one: navy, with the two sprites drawn at their boxes."""
    global FRAMES
    FRAMES = tempfile.mkdtemp(prefix="wgf-pq-frames-")
    write_frame(FRAMES, "state-playing", sprites=True)


def tearDownModule():
    shutil.rmtree(FRAMES, ignore_errors=True)


def write_frame(directory, name, sprites, size=(393, 851)):
    w, h = size
    image = Image(w, h, bytes([20, 30, 60, 255]) * (w * h))
    if sprites:
        for e in entities():
            for y in range(e["y"], e["y"] + e["h"]):
                for x in range(e["x"], e["x"] + e["w"]):
                    i = (y * w + x) * 4
                    image.pixels[i:i + 3] = bytes([240, 200, 80])
    with open(os.path.join(directory, f"{name}.png"), "wb") as handle:
        handle.write(encode_png(image))


def records(asset=True, render="asset", ui=None):
    snap = {"state": "playing", "metrics": {"saves": 0, "lives": 3}, "entities": entities(asset, render),
            "inputs": [], "assets_loaded": ["keeper", "striker"] if asset else []}
    sampled = {"frames": [[[e["id"], e["role"], 1, e["x"], e["y"], e["w"], e["h"], e["asset"], e["render"]]
                           for e in snap["entities"]]] * 3, "viewport": [393, 851]}
    retry = button("Retry", [140, 500, 120, 48])
    ui = ui or {"title": screen("title", [button("Play", [140, 400, 120, 48])]),
                "playing": dict(screen("playing"), entities=entities(asset, render)),
                "won": screen("won", [retry]), "lost": screen("lost", [retry]),
                "retry": screen("retry")}
    common = {"asset_requests": REQUESTS if asset else [{"url": "/assets/assets.json", "status": 200}],
              "runtime_assets": RUNTIME, "errors": [], "frames": []}
    return {
        "first-session": dict(common, samples=[snap], assets_loaded=snap["assets_loaded"],
                              ui={k: v for k, v in ui.items() if k in ("title", "playing")}),
        "win": dict(common, sampled=sampled, reached="won",
                    ui={k: v for k, v in ui.items() if k == "won"}),
        "lose": dict(common, reached="lost", ui={k: v for k, v in ui.items() if k in ("lost", "retry")}),
    }


class Judge(unittest.TestCase):
    def setUp(self):
        self.rules = load_rules()

    def judge(self, recs, manifest=MANIFEST, design=DESIGN, frames=None):
        return judging.judge(recs, manifest, design, self.rules,
                             frames or {"desktop": FRAMES, "mobile": FRAMES})

    @staticmethod
    def failed(checks):
        return sorted(f"{c.get('project') + ':' if c.get('project') else ''}{c['id']}"
                      for c in checks if c["required"] and c["status"] == "FAIL")

    def test_a_production_build_passes(self):
        checks = self.judge({"desktop": records(), "mobile": records()})
        self.assertEqual(self.failed(checks), [], [c for c in checks if c["status"] != "PASS"])
        self.assertIn("mobile", {c.get("project") for c in checks if c["id"] == "ui.targets"})
        self.assertNotIn("desktop", {c.get("project") for c in checks if c["id"] == "ui.targets"})

    def test_a_greybox_fails_assets_used_and_no_primitives(self):
        checks = self.judge({"desktop": records(asset=False, render="primitive")})
        failed = self.failed(checks)
        for cid in ("desktop:assets.used", "desktop:scene.no_primitives", "assets.loaded"):
            self.assertIn(cid, failed)
        self.assertNotIn("assets.present", failed)
        self.assertTrue(all(c["route"] == "develop" for c in checks if c["status"] == "FAIL"))
        used = next(c for c in checks if c["id"] == "assets.used")
        self.assertEqual(used["assets"], ["keeper", "striker"])

    def test_a_probe_without_render_cannot_show_it_draws_no_primitive(self):
        recs = records()
        for e in recs["first-session"]["samples"][0]["entities"]:
            del e["asset"], e["render"]
        recs["win"]["sampled"]["frames"] = [[s[:7] for s in f] for f in recs["win"]["sampled"]["frames"]]
        failed = self.failed(self.judge({"desktop": recs}))
        self.assertIn("desktop:scene.no_primitives", failed)
        self.assertIn("desktop:assets.used", failed)

    def test_primitive_style_exempts_primitives_and_records_it(self):
        design = copy.deepcopy(DESIGN)
        design["build_spec"]["visual_identity"]["primitive_style"] = {
            "reason": "an abstract neon arena: every shape is a glowing primitive"}
        checks = self.judge({"desktop": records(asset=False, render="primitive")}, design=design)
        scene = next(c for c in checks if c["id"] == "scene.no_primitives")
        self.assertFalse(scene["required"])
        self.assertTrue(scene["measured"]["exempt"])
        self.assertIn("exempt", scene["summary"])
        self.assertNotIn("desktop:scene.no_primitives", self.failed(checks))
        self.assertNotIn("desktop:assets.used", self.failed(checks))

    def test_a_placeholder_in_the_manifest_routes_to_assets(self):
        manifest = copy.deepcopy(MANIFEST)
        manifest["items"][0]["placeholder"] = True
        checks = self.judge({"desktop": records()}, manifest=manifest)
        present = next(c for c in checks if c["id"] == "assets.present")
        self.assertEqual((present["status"], present["route"], present["assets"]),
                         ("FAIL", "assets", ["keeper"]))

    def test_a_missing_or_failing_asset(self):
        manifest = copy.deepcopy(MANIFEST)
        manifest["items"] = [manifest["items"][0]]
        manifest["items"][0]["quality"]["verdict"] = "fail"
        present = next(c for c in self.judge({"desktop": records()}, manifest=manifest)
                       if c["id"] == "assets.present")
        self.assertEqual(present["assets"], ["keeper", "striker"])
        self.assertEqual(present["measured"]["missing"], ["striker"])
        self.assertEqual(present["measured"]["quality_not_pass"], ["keeper"])

    def test_an_asset_never_fetched(self):
        recs = records()
        for r in recs.values():
            r["asset_requests"] = [q for q in REQUESTS if "atlases" not in q["url"]]
        loaded = next(c for c in self.judge({"desktop": recs}) if c["id"] == "assets.loaded")
        self.assertEqual((loaded["status"], loaded["route"], loaded["assets"]),
                         ("FAIL", "develop", ["striker"]))

    def test_the_asset_runtime_chain_of_a_production_build(self):
        chain = next(c for c in self.judge({"desktop": records(), "mobile": records()})
                     if c["id"] == "assets.runtime")
        self.assertEqual(chain["status"], "PASS", chain)
        keeper = chain["measured"]["keeper"]
        self.assertEqual([keeper[k] for k in judging.CHAIN], [True] * 5)
        self.assertGreater(keeper["visible_measured"]["box_not_background"], 0.9)

    def test_a_drawing_of_a_counted_requirement_renders_the_requirement(self):
        # Tower Merge Rush: `pieces` has six drawings, runtime assets `pieces-1..6` listed as
        # its entry's `variants`; the probe names the drawing it drew (`pieces-3`).
        def drawn_as(value, variant):
            if isinstance(value, dict):
                if value.get("asset") == "keeper":
                    value["asset"] = variant
                for v in value.values():
                    drawn_as(v, variant)
            elif isinstance(value, list):
                if len(value) >= 9 and value[7] == "keeper":
                    value[7] = variant
                for v in value:
                    drawn_as(v, variant)
            return value

        runtime = copy.deepcopy(RUNTIME)
        runtime["assets"]["keeper"]["variants"] = ["keeper", "keeper-2"]
        runtime["assets"]["keeper-2"] = {"type": "sprite", "url": "sprites/keeper-2.svg"}
        per_view = []
        for _ in range(2):
            rec = drawn_as(records(), "keeper-2")
            for test in rec.values():
                if isinstance(test, dict) and "runtime_assets" in test:
                    test["runtime_assets"] = runtime
            per_view.append(rec)
        chain = next(c for c in self.judge({"desktop": per_view[0], "mobile": per_view[1]})
                     if c["id"] == "assets.runtime")
        self.assertEqual(chain["status"], "PASS", chain["summary"])
        self.assertTrue(chain["measured"]["keeper"]["rendered"])

    def test_an_asset_drawn_where_the_frame_shows_only_background_is_not_visible(self):
        blank = tempfile.mkdtemp(prefix="wgf-pq-blank-")
        self.addCleanup(shutil.rmtree, blank, ignore_errors=True)
        write_frame(blank, "state-playing", sprites=False)
        chain = next(c for c in self.judge({"desktop": records()}, frames={"desktop": blank})
                     if c["id"] == "assets.runtime")
        self.assertEqual((chain["status"], chain["route"]), ("FAIL", "develop"))
        self.assertEqual(chain["measured"]["keeper"]["failed_at"], "visible")

    def test_a_transient_asset_seen_only_in_a_glimpse_of_play_is_rendered_and_visible(self):
        # A pickup or a shot exists for a second: no state frame holds it, the bot's glimpse
        # of play (Watch.glimpse) does, with the snapshot of that moment.
        recs = records()
        keep = lambda es: [e for e in es if e["id"] != "striker"]  # noqa: E731
        recs["first-session"]["samples"][0]["entities"] = keep(recs["first-session"]["samples"][0]["entities"])
        recs["first-session"]["ui"]["playing"]["entities"] = keep(recs["first-session"]["ui"]["playing"]["entities"])
        recs["win"]["sampled"]["frames"] = [[x for x in f if x[0] != "striker"]
                                         for f in recs["win"]["sampled"]["frames"]]
        hidden = next(c for c in self.judge({"desktop": copy.deepcopy(recs)}) if c["id"] == "assets.runtime")
        self.assertEqual(hidden["measured"]["striker"]["failed_at"], "rendered")
        recs["win"]["ui"]["glimpse-striker"] = dict(screen("playing"), glimpse=True,
                                                    entities=entities())
        chain = next(c for c in self.judge({"desktop": recs}) if c["id"] == "assets.runtime")
        self.assertTrue(chain["measured"]["striker"]["rendered"], chain["measured"]["striker"])
        self.assertTrue(chain["measured"]["striker"]["visible"], chain["measured"]["striker"])

    @staticmethod
    def later_level_records():
        """Records of a build whose striker first appears after the opening level: no test
        that starts on a fresh save ever sees it drawn."""
        recs = records()
        keep = lambda es: [e for e in es if e["id"] != "striker"]  # noqa: E731
        recs["first-session"]["samples"][0]["entities"] = keep(recs["first-session"]["samples"][0]["entities"])
        recs["first-session"]["ui"]["playing"]["entities"] = keep(recs["first-session"]["ui"]["playing"]["entities"])
        recs["win"]["sampled"]["frames"] = [[x for x in f if x[0] != "striker"]
                                         for f in recs["win"]["sampled"]["frames"]]
        return recs

    def showcase(self, recs, frame):
        """The bot's showcase record: the game staged the striker's level on request."""
        recs["showcase"] = {"applies": True, "declared": ["striker"],
                            "visits": [{"target": "striker", "staged": True, "reported_drawn": True,
                                        "captured": True, "frame": frame}],
                            "asset_requests": REQUESTS, "runtime_assets": RUNTIME, "errors": [],
                            "ui": {"showcase-striker": dict(screen("playing"), frame=frame,
                                                            showcase=True, target="striker",
                                                            entities=entities())}}
        return recs

    def test_a_later_level_asset_is_credited_from_the_state_the_game_showcases(self):
        # Brick Breaker Worlds, 2026-10-04: boss, embers and laser-bolt exist only in later
        # levels, and every bot test starts on level 1. The probe's showcase stages the state
        # where the asset is drawn; its frame is what credits it.
        frames = tempfile.mkdtemp(prefix="wgf-pq-showcase-")
        self.addCleanup(shutil.rmtree, frames, ignore_errors=True)
        write_frame(frames, "state-showcase-striker", sprites=True)
        chain = next(c for c in self.judge({"desktop": self.showcase(self.later_level_records(),
                                                                     "state-showcase-striker")},
                                           frames={"desktop": frames}) if c["id"] == "assets.runtime")
        self.assertEqual(chain["status"], "PASS", chain["summary"])
        striker = chain["measured"]["striker"]
        self.assertTrue(striker["rendered"] and striker["visible"] and striker["showcase"], striker)
        self.assertGreater(striker["visible_measured"]["largest_area_fraction"], 0)

    def test_a_showcased_asset_the_frame_does_not_show_is_not_credited(self):
        # The probe names the striker in the staged state, but the frame is bare background:
        # an asset listed and not drawn still fails at rendered.
        frames = tempfile.mkdtemp(prefix="wgf-pq-showcase-")
        self.addCleanup(shutil.rmtree, frames, ignore_errors=True)
        write_frame(frames, "state-showcase-striker", sprites=False)
        recs = self.showcase(self.later_level_records(), "state-showcase-striker")
        chain = next(c for c in self.judge({"desktop": recs}, frames={"desktop": frames})
                     if c["id"] == "assets.runtime")
        self.assertEqual(chain["status"], "FAIL")
        self.assertEqual(chain["measured"]["striker"]["failed_at"], "rendered")
        self.assertNotIn("showcase", chain["measured"]["striker"])
        # And a staged state whose frame was never written credits nothing either.
        recs = self.showcase(self.later_level_records(), "state-showcase-missing")
        chain = next(c for c in self.judge({"desktop": recs}, frames={"desktop": frames})
                     if c["id"] == "assets.runtime")
        self.assertEqual(chain["measured"]["striker"]["failed_at"], "rendered")

    def test_a_game_without_a_showcase_is_judged_as_before(self):
        before = self.judge({"desktop": self.later_level_records()})
        recs = self.later_level_records()
        recs["showcase"] = {"applies": False, "reason": "the probe declares no showcase (play.showcase)"}
        after = self.judge({"desktop": recs})
        self.assertEqual(before, after)
        chain = next(c for c in after if c["id"] == "assets.runtime")
        self.assertEqual(chain["measured"]["striker"]["failed_at"], "rendered")

    def test_the_showcase_record_is_read_from_the_records_dir(self):
        from wgf_production.step import load_records
        directory = tempfile.mkdtemp(prefix="wgf-pq-records-")
        self.addCleanup(shutil.rmtree, directory, ignore_errors=True)
        os.makedirs(os.path.join(directory, "desktop"))
        for name in ("win", "showcase"):
            with open(os.path.join(directory, "desktop", f"{name}.json"), "w", encoding="utf-8") as h:
                json.dump({"applies": True}, h)
        found, _frames = load_records(directory, ["desktop"])
        self.assertEqual(sorted(found["desktop"]), ["showcase", "win"])

    def test_the_chain_stops_at_the_first_broken_link(self):
        greybox = next(c for c in self.judge({"desktop": records(asset=False, render="primitive")})
                       if c["id"] == "assets.runtime")
        self.assertEqual(greybox["measured"]["striker"]["failed_at"], "loaded")
        manifest = copy.deepcopy(MANIFEST)
        manifest["items"][0]["placeholder"] = True
        chain = next(c for c in self.judge({"desktop": records()}, manifest=manifest)
                     if c["id"] == "assets.runtime")
        self.assertEqual((chain["measured"]["keeper"]["failed_at"], chain["route"]), ("exists", "assets"))
        runtime = copy.deepcopy(records())
        for r in runtime.values():
            r["runtime_assets"] = {"assets": {"keeper": RUNTIME["assets"]["keeper"]}}
        chain = next(c for c in self.judge({"desktop": runtime}) if c["id"] == "assets.runtime")
        self.assertEqual(chain["measured"]["striker"]["failed_at"], "referenced")

    def test_default_styled_tiny_buttons_fail_styled_and_targets(self):
        tiny = button("Retry", [180, 500, 30, 20], ua_default=True, ua_differs=[], font_px=13.33,
                      font_weight=400, color=[0, 0, 0, 1], background=[239, 239, 239])
        ui = {"title": screen("title", [tiny]), "playing": screen("playing"),
              "won": screen("won", [tiny]), "lost": screen("lost", [tiny]), "retry": screen("retry")}
        checks = self.judge({"desktop": records(ui=ui), "mobile": records(ui=ui)})
        failed = self.failed(checks)
        for cid in ("mobile:ui.targets", "mobile:ui.styled", "desktop:ui.styled"):
            self.assertIn(cid, failed)
        self.assertNotIn("desktop:ui.targets", failed)
        self.assertTrue(all(c["route"] == "develop" for c in checks if c["status"] == "FAIL"))

    def test_a_design_target_raises_the_bar(self):
        design = copy.deepcopy(DESIGN)
        design["build_spec"]["visual_identity"]["ui"] = {"min_target_px": 56}
        targets = next(c for c in self.judge({"mobile": records()}, design=design)
                       if c["id"] == "ui.targets")
        self.assertEqual(targets["status"], "FAIL")
        self.assertIn("56", targets["expected"])

    def test_low_contrast_and_tiny_text(self):
        grey = [{"text": "Saves 3", "box": [10, 10, 120, 28], "font_px": 10, "font_weight": 400,
                 "color": [90, 90, 110, 1], "background": NAVY}]
        ui = {name: screen(name, texts=grey) for name in ("playing", "won", "lost", "retry")}
        text = next(c for c in self.judge({"desktop": records(ui=ui)}) if c["id"] == "ui.text")
        self.assertEqual(text["status"], "FAIL")
        self.assertTrue(text["measured"]["low_contrast"] and text["measured"]["too_small"])

    def test_an_icon_control_named_only_by_its_aria_label_is_not_text(self):
        # The pause button: an SVG icon, aria-label "Pause", no drawn text. The bot records
        # its name for the reports, and says the text is not drawn.
        icon = button("Pause", [1212, 10, 52, 52], font_px=16, font_weight=400,
                      color=[38, 33, 28, 1], background=[60, 52, 44], text_drawn=False)
        ui = {name: screen(name, [icon]) for name in ("playing", "won", "lost", "retry")}
        text = next(c for c in self.judge({"desktop": records(ui=ui)}) if c["id"] == "ui.text")
        self.assertNotIn("Pause", " ".join(text["measured"].get("low_contrast") or []))
        # The same control with drawn text is measured, and fails.
        drawn = dict(icon, text_drawn=True)
        ui = {name: screen(name, [drawn]) for name in ("playing", "won", "lost", "retry")}
        text = next(c for c in self.judge({"desktop": records(ui=ui)}) if c["id"] == "ui.text")
        self.assertEqual(text["status"], "FAIL")
        self.assertIn("'Pause'", " ".join(text["measured"]["low_contrast"]))

    def test_large_text_needs_only_three_to_one(self):
        self.assertEqual(judging.contrast_ratio([255, 255, 255], [0, 0, 0]), 21.0)
        mid = [{"text": "GOAL", "box": [10, 10, 200, 40], "font_px": 32, "font_weight": 700,
                "color": [130, 130, 130, 1], "background": [20, 20, 20]}]
        ui = {name: screen(name, texts=mid) for name in ("won", "lost", "retry")}
        text = next(c for c in self.judge({"desktop": records(ui=ui)}) if c["id"] == "ui.text")
        self.assertEqual(text["status"], "PASS", text)

    def test_text_over_the_canvas_is_read_against_the_frame(self):
        base = tempfile.mkdtemp(prefix="wgf-pq-")
        self.addCleanup(shutil.rmtree, base, ignore_errors=True)
        # A 2x frame: dark navy, so white text over the canvas reads; dark grey text does not.
        image = Image(200, 100, bytes([20, 30, 60, 255]) * (200 * 100))
        for name in ("won", "lost", "retry"):
            with open(os.path.join(base, f"state-{name}.png"), "wb") as handle:
                handle.write(encode_png(image))
        for color, expected in (([255, 255, 255, 1], "PASS"), ([40, 40, 60, 1], "FAIL")):
            texts = [{"text": "Saves", "box": [5, 5, 40, 12], "font_px": 14, "font_weight": 400,
                      "color": color, "background": None}]
            ui = {n: screen(n, texts=texts, viewport=(100, 50)) for n in ("won", "lost", "retry")}
            text = next(c for c in self.judge({"desktop": records(ui=ui)}, frames={"desktop": base})
                        if c["id"] == "ui.text")
            self.assertEqual(text["status"], expected, text)

    def test_overlapping_controls(self):
        a, b = button("Retry", [100, 500, 120, 48]), button("Menu", [150, 510, 120, 48])
        ui = {n: screen(n, [a, b], overlaps=[{"kind": "interactive", "a": 0, "b": 1, "area_px": 2660},
                                             {"kind": "text", "a": 0, "text": 0, "area_px": 4}])
              for n in ("won", "lost", "retry")}
        overlap = next(c for c in self.judge({"desktop": records(ui=ui)}) if c["id"] == "ui.overlap")
        self.assertEqual(overlap["status"], "FAIL")
        self.assertEqual(len(overlap["measured"]), 3)  # the 4 px text touch is under the bar

    def test_a_result_screen_never_seen(self):
        ui = {"playing": screen("playing"), "lost": screen("lost")}
        states = next(c for c in self.judge({"desktop": records(ui=ui)}) if c["id"] == "ui.states")
        self.assertEqual(states["status"], "FAIL")
        self.assertIn("won", states["summary"])
        self.assertIn("retry", states["summary"])


class TheStep(unittest.TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp(prefix="wgf-pq-step-")
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)

    def write_records(self, by_project, records_dir="playability/1-1/out"):
        for project, recs in by_project.items():
            os.makedirs(os.path.join(self.base, records_dir, project, "frames"), exist_ok=True)
            shutil.copy(os.path.join(FRAMES, "state-playing.png"),
                        os.path.join(self.base, records_dir, project, "frames"))
            for name, record in recs.items():
                with open(os.path.join(self.base, records_dir, project, f"{name}.json"), "w") as h:
                    json.dump(record, h)
        return records_dir

    def run_step(self, docs):
        class Inputs:
            refs = {k: types.SimpleNamespace(content_hash=None) for k in docs}

            def __contains__(self, k):
                return k in docs

            def load(self, k):
                return docs[k]

        class Log:
            def __getattr__(self, name):
                return lambda *a, **k: None

        context = types.SimpleNamespace(config={}, run_dir=self.base, logger=Log(), visit=1,
                                        attempt=1, execution=1)
        result = ProductionQualityStep(types.SimpleNamespace(params={}, id="production-quality")
                                       ).execute(Inputs(), context)
        for artifact in result.artifacts:
            self.assertEqual(ArtifactContracts()("production-quality-report", artifact.content), [])
        return result

    def docs(self, records_dir, manifest=MANIFEST, verdict="PASS"):
        play = {"title_id": "demo", "commit": COMMIT, "verdict": verdict, "records_dir": records_dir,
                "projects": [{"id": "desktop", "ran": True}, {"id": "mobile", "ran": True}]}
        return {"playability-report": play, "asset-manifest": manifest, "game-design": DESIGN,
                "scaffold-record": {"title_id": "demo"}}

    def test_nothing_to_judge_waits_for_input(self):
        self.assertEqual(self.run_step({}).outcome, StepOutcome.WAITING_FOR_INPUT)

    def test_a_production_build_succeeds(self):
        d = self.write_records({"desktop": records(), "mobile": records()})
        result = self.run_step(self.docs(d))
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
        self.assertEqual(result.artifacts[0].content["verdict"], "PASS")

    def test_a_greybox_routes_to_develop(self):
        d = self.write_records({"desktop": records(asset=False, render="primitive"),
                                "mobile": records(asset=False, render="primitive")})
        result = self.run_step(self.docs(d))
        report = result.artifacts[0].content
        self.assertEqual((result.outcome, result.route, result.retryable),
                         (StepOutcome.FAILED, "develop", False))
        self.assertEqual(report["routes"], ["develop"])
        self.assertIn("desktop:assets.used", report["failed"])
        self.assertIn("mobile:scene.no_primitives", report["failed"])

    def test_a_placeholder_routes_to_assets_before_develop(self):
        manifest = copy.deepcopy(MANIFEST)
        manifest["items"][1]["placeholder"] = True
        d = self.write_records({"desktop": records(asset=False, render="primitive")})
        result = self.run_step(self.docs(d, manifest))
        report = result.artifacts[0].content
        self.assertEqual(result.route, "assets")
        self.assertEqual(report["routes"], ["assets", "develop"])
        self.assertIn("assets.present", report["failed"])

    def test_no_records_dir_is_blocked(self):
        result = self.run_step(self.docs(None))
        self.assertEqual(result.outcome, StepOutcome.BLOCKED)
        self.assertEqual(result.artifacts[0].content["verdict"], "BLOCKED")
        self.assertIn("records_dir", result.message)

    def test_records_missing_on_disk_is_blocked(self):
        result = self.run_step(self.docs("playability/9-9/out"))
        self.assertEqual(result.outcome, StepOutcome.BLOCKED)

    def test_a_blocked_playability_is_blocked(self):
        d = self.write_records({"desktop": records()})
        result = self.run_step(self.docs(d, verdict="BLOCKED"))
        self.assertEqual(result.outcome, StepOutcome.BLOCKED)

    def test_records_from_a_bot_without_request_capture_are_blocked(self):
        recs = records()
        for r in recs.values():
            del r["asset_requests"]
        d = self.write_records({"desktop": recs})
        result = self.run_step(self.docs(d))
        self.assertEqual(result.outcome, StepOutcome.BLOCKED)
        self.assertIn("asset requests", result.message)


class TheMock(unittest.TestCase):
    def run_mock(self, plan):
        from wgflib.workflow import mock

        class Log:
            def __getattr__(self, name):
                return lambda *a, **k: None

        step = mock.MockProductionQualityStep(types.SimpleNamespace(
            params={}, id="production-quality", outputs=["production-quality-report"]))
        context = types.SimpleNamespace(environment={"mock_plan": {"production-quality": plan}},
                                        execution=1, project_id="demo", logger=Log(), run_id="r")
        inputs = types.SimpleNamespace(refs={}, missing=None)
        return step.execute(inputs, context)

    def test_the_mock_passes_and_fails_both_ways(self):
        for plan, outcome, route in ((["success"], StepOutcome.SUCCESS, None),
                                     (["fail"], StepOutcome.FAILED, "develop"),
                                     (["fail-assets"], StepOutcome.FAILED, "assets")):
            result = self.run_mock(plan)
            self.assertEqual((result.outcome, result.route), (outcome, route))
            report = result.artifacts[0].content
            self.assertEqual(ArtifactContracts()("production-quality-report", report), [])
            self.assertEqual(report["routes"], [route] if route else [])


if __name__ == "__main__":
    unittest.main()

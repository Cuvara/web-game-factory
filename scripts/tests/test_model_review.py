"""3D models an author has looked at: renders, self-review, set mode, silhouettes, and the two
shapes that lift the silhouette ceiling (extrude, lathe).

docs/blender-pipeline.md ("Renders and self-review", "Set mode", "Quality"). Layers, kept
apart so nothing claims more than it ran:

  * no Blender - the silhouette measure on synthetic GLBs and on the reference game's own
    library (the pinned golden ports' Blender builds); extrude and lathe validation; the
    render job (rig, views, the game's camera); the author's repair, review and set rounds
    with a FIXTURE author and a FAKE Blender that builds synthetic GLBs and "renders" flat
    PNGs, both run through wgflib.procs exactly like the real ones;
  * real Blender - WGF_BLENDER_TEST=1: extrude and lathe built twice, byte-identical, and a
    real render of built models and their set.

    python -m unittest scripts/tests/test_model_review.py
    WGF_BLENDER_TEST=1 WGF_BLENDER=/path/to/blender-4.5/blender python -m unittest ...
"""

import json
import os
import shutil
import stat
import struct
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, HERE)

import glb_synth  # noqa: E402
import test_model_author as base  # noqa: E402
from testenv import enabled  # noqa: E402
from wgf_assets import blender, gltf, model_author, model_quality, modelspec  # noqa: E402
from wgf_assets import render as render_mod  # noqa: E402
from wgf_assets.policy import load_policy  # noqa: E402
from wgflib import template  # noqa: E402

LOOK = base.LOOK
KEEPER_REQ = base.KEEPER_REQ
CRATE_REQ = {"id": "crate", "type": "model", "role": "prop", "dimension": "3d",
             "description": "a supply crate", "readability": "a crate"}
MATS = [{"id": "kit", "hex": "#ff7a1a"}, {"id": "dark", "hex": "#1d2b53"}]


def part(shape, size, at, material="kit", **extra):
    return dict({"id": f"{shape}-{len(at)}-{at[0]}-{at[1]}-{at[2]}", "shape": shape,
                 "size": list(size), "translation": list(at), "material": material}, **extra)


def check(quality, check_id):
    return next(c for c in quality["checks"] if c["id"] == check_id)


def assess(data, role="player", look=LOOK):
    return model_quality.assess(data, role=role, visual_identity=look)


# -- the silhouette --------------------------------------------------------------------------

class Silhouette(unittest.TestCase):
    # A hull with a canopy and a fin inside its outline: what an author who never saw a
    # render made, and what read as "an orange brick" in the game.
    BRICK = [part("box", (0.5, 0.3, 1.5), (0, 0, 0)),
             part("sphere", (0.25, 0.15, 0.4), (0, 0.2, 0.1), "dark"),
             part("cylinder", (0.2, 0.2, 0.2), (0, 0, -0.8), "dark")]
    # The same hull with wings that stand out of it.
    WINGED = BRICK + [part("box", (0.7, 0.05, 0.5), (0.6, 0, -0.2)),
                      part("box", (0.7, 0.05, 0.5), (-0.6, 0, -0.2))]

    def test_a_box_with_bumps_fails_for_a_player_and_a_threat(self):
        data = glb_synth.build(self.BRICK, MATS)
        outline = model_quality.analyse(data)["silhouette"]
        self.assertGreater(outline["dominance"], 0.6)
        for role in ("player", "threat"):
            quality = assess(data, role)["quality"]
            self.assertEqual(check(quality, "model.silhouette")["status"], "fail", role)
            self.assertIn("box with bumps", check(quality, "model.silhouette")["summary"])
            self.assertEqual(quality["verdict"], "fail")
            # It is composed, so the primitive check alone would have passed it.
            self.assertFalse(quality["primitive_only"])

    def test_the_same_hull_with_wings_passes(self):
        data = glb_synth.build(self.WINGED, MATS)
        quality = assess(data)["quality"]
        self.assertEqual(check(quality, "model.silhouette")["status"], "pass",
                         check(quality, "model.silhouette"))
        self.assertEqual(quality["verdict"], "pass")

    def test_roles_and_art_direction_decide_whether_it_is_judged(self):
        data = glb_synth.build(self.BRICK, MATS)
        for role in ("prop", "environment", "hazard", None):
            self.assertEqual(check(assess(data, role)["quality"], "model.silhouette")["status"],
                             "pass", role)
        styled = dict(LOOK, primitive_style={"reason": "geometric"})
        self.assertEqual(check(assess(data, "player", styled)["quality"],
                               "model.silhouette")["status"], "pass")

    def test_one_mesh_is_measured_by_the_largest_rectangle(self):
        # A modelled single mesh (another tool's export) has one part: its own boxiness
        # decides, not the part share that is trivially 1.
        box = glb_synth.build([part("box", (1, 1, 1), (0, 0, 0))], MATS)
        outline = model_quality.analyse(box)["silhouette"]
        self.assertEqual(outline["dominance"], 1.0)
        self.assertEqual(outline["views"]["front"]["block"], 1.0)
        cross = glb_synth.build([part("box", (1.5, 0.3, 0.3), (0, 0, 0)),
                                 part("box", (0.3, 1.5, 0.3), (0, 0, 0))], MATS)
        self.assertLess(model_quality.analyse(cross)["silhouette"]["dominance"], 0.6)

    def test_a_flat_view_is_not_an_outline(self):
        tile = glb_synth.build([part("plane", (4, 0, 4), (0, 0, 0))], MATS)
        outline = model_quality.analyse(tile)["silhouette"]
        self.assertIsNone(outline["views"]["front"])
        self.assertIsNone(outline["views"]["side"])
        self.assertIsNotNone(outline["views"]["top"])

    def test_the_committed_box_hull_fixture_fails(self):
        # hover-car.glb: a box hull, a sphere canopy and a fan - Blender-built.
        with open(os.path.join(base.MODELS, "hover-car.glb"), "rb") as handle:
            data = handle.read()
        quality = assess(data)["quality"]
        self.assertEqual(check(quality, "model.silhouette")["status"], "fail")

    def test_a_rotated_part_is_measured_by_its_vertices_not_its_box(self):
        # A sphere of 1 m turned 45 degrees about y: the corners of its local box would
        # stand 1.41 m apart, and a fitted model of rotated rocks read as missing its fit
        # (the live set author's asteroid, 6.42 m for 6 m, which it "fixed" by fudging fit).
        turned = modelspec.euler_to_quaternion([0, 45, 0])
        data = glb_synth.build([part("sphere", (1, 1, 1), (0, 0, 0), rotation=turned)], MATS)
        dims = gltf.inspect(data).summary["dimensions"]
        self.assertLess(dims[0], 1.01)
        self.assertGreater(dims[0], 0.95)

    def test_the_bars_are_the_reference_files(self):
        bars = model_quality.load_bars()
        self.assertEqual(bars["silhouette_roles"], ["player", "threat"])
        self.assertEqual(bars["max_dominance"], 0.6)


class RoundBody(unittest.TestCase):
    """A ball, a marble, an orb: its outline is the disk, with nothing to stand out of it
    (val-3d, 2026-10-03: a marble game's player was refused by model.primitive and
    model.silhouette three rounds running, and the author bent it into a drum). Passed only
    when the requirement names a round body AND the outline is a disk in every view AND it is
    composed or modelled; the passing check names the rule."""

    MARBLE_REQ = {"id": "marble", "role": "player",
                  "description": "The player's glass marble: a coral sphere with a cream "
                                 "swirl band",
                  "readability": "a coral marble with a cream band", "spec": "low-poly GLB"}
    # A shell and an equatorial band: two different pieces, the outline still a disk.
    MARBLE = [part("sphere", (1, 1, 1), (0, 0, 0)),
              part("cylinder", (1.04, 0.16, 1.04), (0, 0, 0), "dark")]

    def judged(self, parts, requirement, role="player"):
        data = glb_synth.build(parts, MATS)
        return model_quality.assess(data, role=role, visual_identity=LOOK,
                                    requirement=requirement)["quality"]

    def test_a_composed_marble_passes_and_says_why(self):
        quality = self.judged(self.MARBLE, self.MARBLE_REQ)
        for check_id in ("model.primitive", "model.silhouette"):
            found = check(quality, check_id)
            self.assertEqual(found["status"], "pass", found)
            self.assertIn("a round body: the requirement names a marble", found["summary"])
            self.assertIn("models.round_body", found["summary"])
        self.assertFalse(quality["primitive_only"])
        self.assertEqual(quality["verdict"], "pass", quality["checks"])

    def test_a_lone_sphere_is_still_a_placeholder(self):
        quality = self.judged([part("sphere", (1, 1, 1), (0, 0, 0))], self.MARBLE_REQ)
        self.assertEqual(check(quality, "model.primitive")["status"], "fail")
        self.assertEqual(check(quality, "model.silhouette")["status"], "fail")
        self.assertTrue(quality["primitive_only"])
        self.assertEqual(quality["verdict"], "fail")

    def test_a_blob_goalkeeper_is_not_a_round_body(self):
        quality = self.judged(self.MARBLE, KEEPER_REQ)
        self.assertEqual(check(quality, "model.silhouette")["status"], "fail")
        self.assertIn("box with bumps", check(quality, "model.silhouette")["summary"])
        self.assertEqual(quality["verdict"], "fail")

    def test_a_disk_outline_needs_a_requirement_that_names_a_round_body(self):
        drone = {"id": "drone", "role": "threat", "description": "a scout drone",
                 "readability": "a hovering drone"}
        quality = self.judged(self.MARBLE, drone, role="threat")
        self.assertEqual(check(quality, "model.silhouette")["status"], "fail")
        # A word inside another word is not the word.
        orbital = dict(drone, description="an orbital scout drone, marbled hull")
        quality = self.judged(self.MARBLE, orbital, role="threat")
        self.assertEqual(check(quality, "model.silhouette")["status"], "fail")

    def test_a_round_requirement_with_a_drum_outline_fails(self):
        # What the refused author made of the marble: a cylinder with rims.
        drum = [part("cylinder", (1, 1, 1), (0, 0, 0)),
                part("cylinder", (1.05, 0.12, 1.05), (0, 0.45, 0), "dark"),
                part("cylinder", (1.05, 0.12, 1.05), (0, -0.45, 0), "dark")]
        quality = self.judged(drum, self.MARBLE_REQ)
        self.assertEqual(check(quality, "model.silhouette")["status"], "fail")
        found, why = model_quality.round_body(
            self.MARBLE_REQ, model_quality.analyse(glb_synth.build(drum, MATS))["pieces"],
            model_quality.analyse(glb_synth.build(drum, MATS))["silhouette"])
        self.assertIsNone(found)
        self.assertIn("not a disk", why)

    def test_a_plural_names_it_too(self):
        req = dict(self.MARBLE_REQ, description="one of the marbles", readability="",
                   spec="")
        quality = self.judged(self.MARBLE, req)
        self.assertEqual(check(quality, "model.silhouette")["status"], "pass")

    def test_the_rule_is_the_reference_file(self):
        rule = model_quality.load_bars()["round_body"]
        self.assertEqual(rule["words"],
                         ["ball", "marble", "sphere", "orb", "bubble", "globe", "planet"])
        self.assertEqual((rule["min_fill"], rule["max_fill"], rule["max_aspect"],
                          rule["min_parts"]), (0.7, 0.86, 1.18, 2))
        self.assertEqual(model_quality.DEFAULT_BARS["round_body"], rule)


class ReferenceLibrary(unittest.TestCase):
    """The calibration: the 3D reference game's library - hand-iterated specs built by the
    pinned Blender, read from the pinned golden ports - passes for the roles it plays."""

    @classmethod
    def setUpClass(cls):
        try:
            ports = template.golden_ports_checkout()
        except template.TemplateError as exc:
            raise unittest.SkipTest(f"pinned golden ports unavailable: {exc}")
        cls.library = os.path.join(ports, "examples", "neon-drift-arena", "wgf-golden",
                                   "library", "models")
        if not os.path.isdir(cls.library):
            raise unittest.SkipTest(f"no reference library at {cls.library}")

    def judge(self, name, role):
        with open(os.path.join(self.library, f"{name}.glb"), "rb") as handle:
            data = handle.read()
        return model_quality.assess(data, role=role, visual_identity=LOOK)

    def test_the_reference_models_pass_the_silhouette_even_as_a_player(self):
        for name in ("craft", "wall", "arena-skyline", "arena-track"):
            judged = self.judge(name, "player")
            outline = judged["geometry"]["silhouette"]
            self.assertLessEqual(outline["dominance"], 0.6, (name, outline))
            self.assertEqual(check(judged["quality"], "model.silhouette")["status"], "pass",
                             name)

    def test_the_reference_craft_is_far_from_the_bar(self):
        outline = self.judge("craft", "player")["geometry"]["silhouette"]
        self.assertLess(outline["dominance"], 0.4)


# -- extrude and lathe -----------------------------------------------------------------------

WING = {"id": "wing", "shape": "extrude", "outline": [[0, 0.3], [0.9, -0.25], [0.9, -0.4],
                                                      [0, -0.35]],
        "size": [0.6, 0.04, 0.6], "position": [0.45, 0, -0.1], "bevel": 0.01, "mirror": "x",
        "material": "kit"}
NOZZLE = {"id": "nozzle", "shape": "lathe", "profile": [[0.6, 0], [1, 0.4], [0.8, 1], [0, 1]],
          "segments": 12, "size": [0.2, 0.3, 0.2], "position": [0, 0, -0.6],
          "rotation": [-90, 0, 0], "material": "kit"}
SHAPED = {"parts": [{"id": "hull", "shape": "box", "size": [0.4, 0.2, 1.0],
                     "material": "kit"}, WING, NOZZLE],
          "materials": [{"id": "kit", "color": "#ff7a1a"}], "fit": {"size": 1.5, "axis": "z"}}


class ExtrudeAndLathe(unittest.TestCase):
    def problems(self, **changes):
        return modelspec.validate({"parts": [{**WING, **changes}],
                                   "materials": [{"id": "kit"}]})

    def test_the_shaped_spec_is_valid_for_the_schema_and_the_rules(self):
        self.assertEqual(modelspec.validate(SHAPED), [])
        self.assertEqual(model_author._schema_problems(SHAPED), [])

    def test_an_outline_must_be_a_simple_polygon(self):
        self.assertEqual(self.problems(), [])
        crossing = self.problems(outline=[[0, 0], [1, 1], [1, 0], [0, 1]])
        self.assertTrue(any("crosses itself" in p for p in crossing), crossing)
        self.assertTrue(self.problems(outline=[[0, 0], [1, 0]]))
        self.assertTrue(self.problems(outline=[[0, 0], [1, 0], [2, 0]]))  # no area
        self.assertTrue(self.problems(outline=[[0, 0], [0, 0], [1, 1]]))
        concave = self.problems(outline=[[0, 0], [2, 0], [2, 2], [1, 1], [0, 2]])
        self.assertEqual(concave, [])

    def test_a_profile_is_a_line_swept_round_y(self):
        def problems(**changes):
            return modelspec.validate({"parts": [{**NOZZLE, **changes}],
                                       "materials": [{"id": "kit"}]})
        self.assertEqual(problems(), [])
        self.assertTrue(problems(profile=[[1, 0]]))
        self.assertTrue(problems(profile=[[-1, 0], [1, 1]]))
        self.assertTrue(problems(profile=[[1, 0], [1, 0]]))
        self.assertTrue(problems(profile=[[1, 0], [0, 0.5], [1, 1]]))  # axis mid-line
        self.assertTrue(problems(profile=[[1, 0], [2, 0]]))             # no height
        self.assertTrue(problems(profile=[[0, 0], [0, 1]]))             # no radius
        self.assertTrue(problems(profile=[[1, 0], [2, 1], [2, 0], [1, 1]]))  # crossing

    def test_each_field_belongs_to_its_shape(self):
        both = modelspec.validate({"parts": [{"id": "a", "shape": "box",
                                              "outline": WING["outline"]},
                                             {"id": "b", "shape": "extrude"},
                                             {"id": "c", "shape": "lathe"}]})
        self.assertTrue(any("only on a extrude" in p for p in both), both)
        self.assertTrue(any("an extrude needs one" in p or "a extrude needs one" in p
                            for p in both), both)
        self.assertTrue(any("a lathe needs one" in p for p in both), both)
        self.assertTrue(modelspec.validate({"parts": [dict(NOZZLE, bevel=0.01)]}))

    def test_a_mirrored_outline_is_reflected(self):
        expanded = {p["id"]: p for p in modelspec.expand_parts([WING])}
        twin = expanded["wing-mirror"]
        self.assertEqual(twin["outline"], [[-p[0] + 0.0, p[1]] for p in reversed(WING["outline"])])
        self.assertEqual(twin["position"][0], -WING["position"][0])
        resolved, _ = modelspec.resolve(SHAPED, "ship")
        by_id = {p["id"]: p for p in resolved["parts"]}
        self.assertEqual(by_id["nozzle"]["profile"], [[float(a), float(b)]
                                                       for a, b in NOZZLE["profile"]])
        self.assertIn("outline", by_id["wing-mirror"])
        self.assertNotIn("outline", by_id["hull"])


# -- the render job --------------------------------------------------------------------------

NEON = {"palette": [{"hex": "#0B0B12", "token": "ground"}, {"hex": "#16162A"},
                    {"hex": "#EDEBFF"},
                    {"hex": "#FF2E88", "token": "signal", "role": "The one accent: the player"},
                    {"hex": "#2EF2FF"},
                    {"hex": "#FFB020", "token": "danger", "role": "Warnings; never decorative"}]}


class RenderJob(unittest.TestCase):
    def test_the_rig_comes_from_the_palette(self):
        background, rig = render_mod.rig(NEON)
        self.assertEqual([round(c * 255) for c in background], [11, 11, 18])
        self.assertEqual(rig["ground"], background)
        # The rim light is the player's accent, never the danger colour; the key stays white.
        self.assertEqual([round(c * 255) for c in rig["rim"]["color"]], [255, 46, 136])
        unnamed = {"palette": [{"hex": "#0B0B12"}, {"hex": "#808080"}, {"hex": "#2EF2FF"}]}
        self.assertEqual([round(c * 255) for c in render_mod.rig(unnamed)[1]["rim"]["color"]],
                         [46, 242, 255])  # else the most vivid
        self.assertEqual(rig["key"]["color"], [1.0, 1.0, 1.0])
        self.assertEqual(rig["key"]["direction"], [4.0, 9.0, 7.0])
        fallback, _ = render_mod.rig({})
        self.assertEqual(len(fallback), 3)

    def test_the_game_camera(self):
        chase = "Third-person chase camera, slightly high, locked behind the ship"
        behind, _up = render_mod.game_direction(chase, "player")
        ahead, _up = render_mod.game_direction(chase, "threat")
        self.assertLess(behind[2], 0)   # the player is seen from behind
        self.assertGreater(ahead[2], 0)  # what comes at it, from the front
        self.assertEqual(render_mod.game_direction("Top-down camera", "player")[1],
                         [0.0, 0.0, 1.0])
        self.assertIsNone(render_mod.game_direction(None))
        self.assertIsNone(render_mod.game_direction("first-person cockpit", "player"))

    def test_the_views_and_the_gameplay_size(self):
        names = [v["name"] for v in render_mod.views("player", "readable at 80 px wide",
                                                      "chase camera")]
        self.assertEqual(names, list(render_mod.VIEW_ORDER))
        gameplay = render_mod.views("player", "readable at 80 px wide", "chase camera")[-1]
        self.assertEqual(gameplay["pixels"], 89)  # 80 px at 90% of the tile
        self.assertEqual(render_mod.gameplay_pixels("a crate"), render_mod.GAMEPLAY_PIXELS)
        self.assertEqual(render_mod.gameplay_pixels("at 4000 px"), 384)
        # Without a game camera the gameplay size is the three-quarter view's.
        plain = render_mod.views("prop", None, None)
        self.assertEqual([v["name"] for v in plain], ["three-quarter", "side", "top",
                                                      "gameplay"])
        self.assertEqual(plain[-1]["direction"], plain[0]["direction"])

    def test_a_set_lineup_only_for_several_models(self):
        one = render_mod.job([{"id": "a", "glb": "a.glb"}], "/tmp/x", identity=NEON)
        self.assertNotIn("set", one)
        two = render_mod.job([{"id": "a", "glb": "a.glb"}, {"id": "b", "glb": "b.glb"}],
                             "/tmp/x", identity=NEON, camera="chase camera")
        self.assertEqual([v["name"] for v in two["set"]["views"]], ["three-quarter", "game"])
        self.assertEqual(two["models"][1]["sheet"], "/tmp/x/b.sheet.png")

    def test_no_blender_is_a_render_error(self):
        with self.assertRaises(render_mod.RenderError):
            render_mod.render(None, [], out_dir=tempfile.gettempdir())


# -- the author: renders, review rounds, set mode ----------------------------------------------

RENDER_BRANCH = r'''
if "--job" in opts:
    import os
    from wgf_assets import encoders
    if os.path.exists({no_render!r}):
        sys.exit(3)
    job = json.load(open(opts["--job"]))
    report = {{"ok": True, "engine": "FAKE", "models": {{}}}}
    for m in job["models"]:
        views = {{}}
        for v in m["views"]:
            px = v.get("pixels") or job["tile"]
            path = os.path.join(m["dir"], m["id"] + "." + v["name"] + ".png")
            open(path, "wb").write(encoders.png(px, px, (200, 40, 80), border=False))
            views[v["name"]] = {{"path": path, "coverage": 0.2, "fill": 0.5, "pixels": px}}
        open(m["sheet"], "wb").write(encoders.png(64, 16, (10, 10, 20), border=False))
        report["models"][m["id"]] = {{"sheet": m["sheet"], "views": views}}
    if job.get("set"):
        open(job["set"]["out"], "wb").write(encoders.png(32, 16, (10, 10, 20), border=False))
        report["set"] = {{"path": job["set"]["out"], "order": [m["id"] for m in job["models"]]}}
    json.dump(report, open(opts["--report"], "w"))
    sys.exit(0)
'''
_OPTS = 'opts = dict(zip(args[args.index("--") + 1::2], args[args.index("--") + 2::2]))\n'

# The fixture author. argv: MODE, {request}, {spec}, {dir}, {prompt}. It logs what it was
# asked and answers by mode and by what the request asks for (author, repair, review).
AUTHOR = r'''#!{python}
import json, os, sys
mode, request_path, spec_path, work_dir, prompt = sys.argv[1:6]
request = json.load(open(request_path))
keeper = json.load(open({keeper!r}))
box = {box!r}
stage = request.get("stage") or ("review" if "review" in request else
                                 "repair" if "repair" in request else "author")
renders = request.get("renders") or (request.get("review") or {{}}).get("renders") or {{}}
sheets = [r["sheet"] for r in renders.values() if isinstance(r, dict) and "sheet" in r] \
    if "assets" in request else ([renders["sheet"]] if renders.get("sheet") else [])
with open({log!r}, "a") as log:
    log.write(json.dumps({{"mode": mode, "stage": stage, "prompt": prompt,
                          "assets": [a["id"] for a in request.get("assets") or []],
                          "problems": sorted((request.get("problems") or {{}})),
                          "sheets_exist": [os.path.isfile(s) for s in sheets],
                          "set": request.get("set"),
                          "set_exists": bool(request.get("set")) and os.path.isfile(request["set"]),
                          "design": [request.get("camera"), request.get("art_direction")],
                          "craft": request.get("craft")}}) + "\n")
revised = dict(keeper, parts=keeper["parts"] + [
    {{"id": "visor", "shape": "box", "size": [0.3, 0.06, 0.05], "position": [0, 1.65, 0.12],
      "material": "gloves"}}])

def out(spec):
    if mode.endswith("-file"):
        json.dump(spec, open(spec_path, "w"))
    else:
        print("the spec:")
        print(json.dumps(spec))

if mode.startswith("set"):
    if stage == "author":
        first = {{"keeper": json.loads(box) if mode.startswith("set-repair") else keeper,
                  "crate": json.loads(box)}}
        if mode.startswith("set-missing"):
            del first["crate"]
        if mode.startswith("set-never"):
            first["keeper"] = json.loads(box)
        answer = first
    elif stage == "repair":
        answer = {{k: (json.loads(box) if mode.startswith("set-never") else
                      keeper if k == "keeper" else json.loads(box))
                  for k in request["problems"]}}
    else:
        answer = {{}}
    if mode.endswith("-file"):
        for asset_id, spec in answer.items():
            json.dump(spec, open(request["spec_paths"][asset_id], "w"))
        print("\n".join(f"{{k}}: reads" for k in request.get("spec_paths", {{}})))
    else:
        print("keeper: reads\ncrate: reads")
        print(json.dumps({{"models": answer}}))
    sys.exit(0)

if stage == "author":
    out(json.loads(box) if mode.startswith("box") else keeper)
elif stage == "repair":
    out(keeper)
elif mode.startswith("accept"):
    if not mode.endswith("-file"):
        out(keeper)
    print("keeper: reads - a keeper in gloves")
elif mode.startswith("revise"):
    out(revised)
elif mode.startswith("break"):
    out(json.loads(box))
'''


class AuthorCase(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.mkdtemp(prefix="wgf-model-review-")
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)
        fake = base.FAKE_BLENDER.format(python=sys.executable, tests=HERE, scripts=SCRIPTS)
        branch = RENDER_BRANCH.format(no_render=os.path.join(self.scratch, "no-render"))
        self.assertIn(_OPTS, fake)
        self.blender = self.script("blender", fake.replace(_OPTS, _OPTS + branch))
        self.log = os.path.join(self.scratch, "author.log")
        self.author = self.script("author", AUTHOR.format(
            python=sys.executable, log=self.log,
            keeper=os.path.join(base.MODELS, "keeper.model.json"),
            box=json.dumps(base.BOX_SPEC)))
        self.out = os.path.join(self.scratch, "out")
        self.context = {"run_dir": os.path.join(self.scratch, "run"),
                        "design": {"camera": "Third-person chase camera, slightly high",
                                   "art_direction": "a bright pitch"}}

    def script(self, name, text):
        path = os.path.join(self.scratch, name)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)
        return path

    def settings(self, mode, **extra):
        spec_from = "file" if mode.endswith("-file") else "stdout"
        return dict({"kind": "command", "spec_from": spec_from,
                     "argv": [self.author, mode, "{request}", "{spec}", "{dir}", "{prompt}"],
                     "blender": {"executable": self.blender}}, **extra)

    def calls(self):
        if not os.path.exists(self.log):
            return []
        with open(self.log, encoding="utf-8") as handle:
            return [json.loads(line) for line in handle]


class ReviewRounds(AuthorCase):
    def produce(self, mode, requirement=KEEPER_REQ, **extra):
        return model_author.produce_model(requirement, LOOK, self.out,
                                          self.settings(mode, **extra), self.context)

    def test_an_author_that_judges_its_renders_readable_keeps_its_spec(self):
        for mode in ("accept", "accept-file"):
            with self.subTest(mode=mode):
                result = self.produce(mode)
                self.assertEqual(result["rounds"], 2)
                self.assertEqual(result["review"]["reads"], True)
                self.assertIn("keeper in gloves", result["review"]["note"] or "")
                self.assertEqual(len(result["spec"]["parts"]), len(base.keeper_spec()["parts"]))
                self.assertTrue(os.path.isfile(result["renders"]["sheet"]))
                self.assertIn("Self-reviewed from renders", result["notes"])
        review = [c for c in self.calls() if c["stage"] == "review"]
        self.assertEqual(len(review), 2)
        self.assertTrue(all(c["sheets_exist"] == [True] for c in review), review)
        self.assertEqual(review[0]["design"], ["Third-person chase camera, slightly high",
                                               "a bright pitch"])

    def test_a_revision_from_the_renders_becomes_the_model(self):
        result = self.produce("revise")
        self.assertIn("visor", [p["id"] for p in result["spec"]["parts"]])
        self.assertFalse(result["review"]["reads"])
        self.assertEqual(result["quality"]["verdict"], "pass")
        self.assertEqual([h["stage"] for h in result["history"]], ["author", "review"])

    def test_a_revision_that_breaks_a_check_is_dropped(self):
        result = self.produce("break", max_repair_rounds=0)
        self.assertEqual(len(result["spec"]["parts"]), len(base.keeper_spec()["parts"]))
        self.assertIn("dropped", result["notes"])
        self.assertEqual(result["quality"]["verdict"], "pass")

    def test_a_broken_revision_is_repaired_while_repairs_remain(self):
        result = self.produce("break", max_repair_rounds=1)
        self.assertEqual([c["stage"] for c in self.calls()], ["author", "review", "repair"])
        self.assertEqual(result["quality"]["verdict"], "pass")

    def test_a_repair_round_shows_the_renders_of_what_was_refused(self):
        result = self.produce("box", review_rounds=0)
        first, second = self.calls()
        self.assertEqual(second["stage"], "repair")
        self.assertEqual(second["sheets_exist"], [True])
        self.assertIn("open them", second["prompt"])
        self.assertIsNone(result["review"])

    def test_without_renders_there_is_no_review(self):
        open(os.path.join(self.scratch, "no-render"), "w").close()
        result = self.produce("accept")
        self.assertEqual(result["rounds"], 1)
        self.assertIsNone(result["review"])
        self.assertIsNone(result["renders"])
        self.assertIn("Not rendered", result["notes"])

    def test_review_rounds_zero_and_render_disabled(self):
        self.assertEqual(self.produce("accept", review_rounds=0)["rounds"], 1)
        result = self.produce("accept", render={"enabled": False})
        self.assertEqual(result["rounds"], 1)
        self.assertIsNone(result["renders"])

    def test_the_prompts_name_the_new_shapes_and_the_craft(self):
        self.produce("accept")
        first = self.calls()[0]
        self.assertIn("extruded outlines and lathed profiles", first["prompt"])
        self.assertTrue(first["craft"][-1].endswith("art-direction.md"))
        for path in first["craft"]:
            self.assertTrue(os.path.isfile(path), path)


class SetMode(AuthorCase):
    def produce(self, mode, **extra):
        return model_author.produce_models([KEEPER_REQ, CRATE_REQ], LOOK, self.out,
                                           self.settings(mode, **extra), self.context)

    def test_one_session_authors_and_reviews_the_whole_set(self):
        made = self.produce("set")
        self.assertEqual(sorted(made["results"]), ["crate", "keeper"])
        self.assertEqual(made["errors"], {})
        self.assertEqual(made["rounds"], 2)
        self.assertTrue(os.path.isfile(made["set_render"]))
        author, review = self.calls()
        self.assertEqual(author["assets"], ["keeper", "crate"])
        self.assertIn('{"models": {"<asset id>": <spec>, ...}}', author["prompt"])
        self.assertEqual(review["stage"], "review")
        self.assertEqual(review["sheets_exist"], [True, True])
        self.assertTrue(review["set_exists"])
        for result in made["results"].values():
            self.assertTrue(result["review"]["reads"])
            self.assertTrue(os.path.isfile(result["files"][0]))
        self.assertTrue(os.path.isfile(os.path.join(self.scratch, "run", "set", "keeper",
                                                    "accepted.model.json")))

    def test_a_refused_model_is_repaired_inside_the_set(self):
        made = self.produce("set-repair")
        self.assertEqual(sorted(made["results"]), ["crate", "keeper"])
        stages = [(c["stage"], c["problems"]) for c in self.calls()]
        self.assertEqual(stages, [("author", []), ("repair", ["keeper"]), ("review", [])])
        self.assertEqual(made["results"]["keeper"]["quality"]["verdict"], "pass")

    def test_unchanged_spec_files_are_the_authors_acceptance(self):
        made = self.produce("set-file")
        self.assertEqual(made["rounds"], 2)
        self.assertTrue(all(r["review"]["reads"] for r in made["results"].values()))

    def test_a_model_left_out_is_a_problem_to_repair(self):
        made = self.produce("set-missing")
        self.assertEqual(sorted(made["results"]), ["crate", "keeper"])
        self.assertEqual(self.calls()[1]["problems"], ["crate"])

    def test_a_model_that_never_passes_is_an_error_beside_the_rest(self):
        made = self.produce("set-never", max_repair_rounds=1)
        self.assertEqual(sorted(made["results"]), ["crate"])
        self.assertIn("keeper", made["errors"])
        self.assertTrue(any("model.primitive" in p for p in made["errors"]["keeper"].problems))

    def test_duplicate_ids_are_refused(self):
        with self.assertRaises(model_author.ModelAuthorError):
            model_author.produce_models([KEEPER_REQ, KEEPER_REQ], LOOK, self.out,
                                        self.settings("set"), self.context)
        self.assertEqual(model_author.produce_models([], LOOK, self.out, self.settings("set"),
                                                     self.context)["results"], {})


# -- real Blender ----------------------------------------------------------------------------

def _png_size(path):
    with open(path, "rb") as handle:
        head = handle.read(24)
    return struct.unpack(">II", head[16:24])


class RealBlender(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.info, reason = base._real_blender()
        if cls.info is None:
            raise unittest.SkipTest(reason)

    def setUp(self):
        self.scratch = tempfile.mkdtemp(prefix="wgf-model-review-real-")
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)

    def test_extrude_and_lathe_build_reproducibly_and_read_as_wings(self):
        data, _report, _key = blender.build_model(self.info, SHAPED, "ship")
        self.assertEqual(blender.build_model(self.info, SHAPED, "ship")[0], data)
        inspection = gltf.inspect(data, name="ship.glb")
        self.assertEqual([f for f in inspection.findings if f[1] == "error"], [])
        self.assertAlmostEqual(inspection.summary["dimensions"][2], 1.5, places=3)
        geometry = model_quality.analyse(data)
        shapes = {p["node"]: p["shape"] for p in geometry["pieces"]}
        self.assertIsNone(shapes["wing"])       # an extrude is modelled, not a primitive
        self.assertIsNone(shapes["nozzle"])
        document, _ = gltf.load(data)
        nodes = {n["name"]: n for n in document["nodes"]}
        self.assertAlmostEqual(nodes["wing-mirror"]["translation"][0],
                               -nodes["wing"]["translation"][0], places=5)
        # Swept wings stand out of the hull: the silhouette passes for a player.
        quality = model_quality.assess(data, role="player", visual_identity=LOOK)["quality"]
        self.assertEqual(check(quality, "model.silhouette")["status"], "pass")

    def test_a_textured_extrude_has_uvs(self):
        spec = {"parts": [{k: v for k, v in WING.items() if k != "mirror"}],
                "materials": [{"id": "kit", "color": "#ff7a1a",
                               "texture": {"pattern": "stripes", "color2": "#1d2b53"}}]}
        data, _report, _key = blender.build_model(self.info, spec, "fin")
        document, _ = gltf.load(data)
        attributes = document["meshes"][0]["primitives"][0]["attributes"]
        self.assertIn("TEXCOORD_0", attributes)
        self.assertEqual(blender.build_model(self.info, spec, "fin")[0], data)

    def test_models_and_their_set_render_to_contact_sheets(self):
        paths = {}
        for asset_id, spec in (("ship", SHAPED), ("keeper", base.keeper_spec())):
            data, _r, _k = blender.build_model(self.info, spec, asset_id)
            paths[asset_id] = os.path.join(self.scratch, f"{asset_id}.glb")
            with open(paths[asset_id], "wb") as handle:
                handle.write(data)
        out = os.path.join(self.scratch, "renders")
        report = render_mod.render(
            self.info, [{"id": "ship", "glb": paths["ship"], "role": "player",
                         "readability": "a ship readable at 80 px wide"},
                        {"id": "keeper", "glb": paths["keeper"], "role": "threat"}],
            out_dir=out, identity=LOOK, camera="chase camera, slightly high",
            settings={"samples": 4, "tile": 128})
        ship = report["models"]["ship"]
        self.assertEqual(sorted(ship["views"]), sorted(render_mod.VIEW_ORDER))
        self.assertEqual(ship["views"]["gameplay"]["pixels"], 89)
        for view in ship["views"].values():
            self.assertTrue(os.path.isfile(view["path"]))
            self.assertGreater(view["coverage"], 0.02, view)  # the model is in the frame
        width, height = _png_size(ship["sheet"])
        self.assertGreater(width, 5 * 128)
        self.assertGreater(height, 128)
        self.assertTrue(os.path.isfile(report["set"]["path"]))
        self.assertEqual(report["set"]["order"], ["ship", "keeper"])


if __name__ == "__main__":
    unittest.main()

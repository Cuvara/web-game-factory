"""3D production quality: recognising a primitive in a GLB, and the model author.

docs/blender-pipeline.md ("Quality" and "The model author"). Three layers, kept apart so
nothing claims more than it ran:

  * no Blender - primitive detection and the quality verdict on synthetic GLBs (glb_synth.py)
    and the committed Blender-built fixture; the model author with a FIXTURE author command
    and a FAKE Blender (an executable answering `--version` and writing a synthetic GLB of the
    resolved spec's parts), both run through wgflib.procs exactly like the real ones;
  * real Blender - WGF_BLENDER_TEST=1, the pinned series found through the usual discovery
    (WGF_BLENDER or PATH): the fixture author's specs built by the real Blender and judged.

    python -m unittest scripts/tests/test_model_author.py
    WGF_BLENDER_TEST=1 WGF_BLENDER=/path/to/blender-4.5/blender python -m unittest ...
"""

import copy
import json
import os
import shutil
import stat
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, HERE)

import glb_synth  # noqa: E402
from testenv import enabled  # noqa: E402
from wgf_assets import blender, encoders, gltf, model_author, model_quality, modelspec  # noqa: E402
from wgf_assets.policy import load_policy  # noqa: E402
from wgflib.workflow.contracts import ArtifactContracts  # noqa: E402

MODELS = os.path.join(HERE, "fixtures", "models")
LOOK = {"palette": [{"token": "kit", "hex": "#ff7a1a", "role": "keeper kit"},
                    {"token": "night", "hex": "#1d2b53", "role": "shorts, background"},
                    {"token": "grass", "hex": "#39d353", "role": "gloves, pitch"}]}
STYLED = dict(LOOK, primitive_style={"reason": "an abstract neon look built from solids"})
KEEPER_REQ = {"id": "keeper", "type": "model", "role": "player", "dimension": "3d",
              "description": "The goalkeeper the player controls",
              "readability": "a goalkeeper in gloves, readable at 60 px tall"}


def keeper_spec():
    with open(os.path.join(MODELS, "keeper.model.json"), encoding="utf-8") as handle:
        return json.load(handle)


BOX_SPEC = {"parts": [{"id": "body", "shape": "box", "size": [1, 1, 1], "material": "kit"}],
            "materials": [{"id": "kit", "color": "#ff7a1a"}]}


def piece(shape, size=(1, 1, 1), at=(0, 0, 0), material="kit", **extra):
    return dict({"id": f"{shape}-{len(at)}-{at[0]}-{at[1]}-{at[2]}", "shape": shape,
                 "size": list(size), "translation": list(at), "material": material}, **extra)


MATERIALS = [{"id": "kit", "hex": "#ff7a1a"}, {"id": "grey", "hex": "#808080"}]


def synth(*parts, materials=MATERIALS, **kwargs):
    return glb_synth.build(list(parts), materials, **kwargs)


def check(quality, check_id):
    return next(c for c in quality["checks"] if c["id"] == check_id)


# -- primitive detection on synthetic GLBs ---------------------------------------------------

class PrimitiveDetection(unittest.TestCase):
    def shapes(self, data):
        return [p["shape"] for p in model_quality.analyse(data)["pieces"]]

    def test_each_primitive_is_recognised(self):
        for shape, size in (("box", (1, 2, 0.5)), ("sphere", (1, 1, 1)),
                            ("sphere", (0.4, 1.2, 0.8)), ("cylinder", (0.5, 2, 0.5)),
                            ("cone", (1, 1.5, 1)), ("capsule", (0.4, 1.8, 0.4)),
                            ("plane", (3, 0, 2))):
            with self.subTest(shape=shape, size=size):
                self.assertEqual(self.shapes(synth(piece(shape, size))), [shape])

    def test_a_rotated_node_does_not_hide_a_primitive(self):
        # Shapes are judged in the mesh's own axes: a wheel turned on its side is a cylinder.
        wheel = piece("cylinder", (0.6, 0.3, 0.6), rotation=[0, 0, 0.7071068, 0.7071068])
        self.assertEqual(self.shapes(synth(wheel)), ["cylinder"])

    def test_modelling_matches_no_primitive(self):
        tapered = piece("box", (1, 1, 1), taper=[1.4, 0.8])
        cone_cut = piece("cylinder", (1, 1, 1), taper=[0.5, 0.5])  # a frustum
        self.assertEqual(self.shapes(synth(tapered)), [None])
        self.assertEqual(self.shapes(synth(cone_cut)), [None])

    def test_one_box_is_primitive_only(self):
        quality = model_quality.assess(synth(piece("box")), role="player",
                                       visual_identity=LOOK)["quality"]
        self.assertTrue(quality["primitive_only"])
        self.assertEqual((quality["parts"], quality["triangles"]), (1, 12))
        self.assertEqual(quality["verdict"], "fail")
        self.assertEqual(check(quality, "model.primitive")["status"], "fail")
        self.assertEqual(check(quality, "model.normals")["status"], "pass")

    def test_one_sphere_is_primitive_only(self):
        quality = model_quality.assess(synth(piece("sphere", (0.3, 0.3, 0.3))),
                                       role="projectile", visual_identity=LOOK)["quality"]
        self.assertTrue(quality["primitive_only"])
        self.assertEqual(quality["verdict"], "fail")

    def test_a_composite_is_not_primitive_only(self):
        keeper = synth(piece("box", (0.5, 0.6, 0.3), (0, 1.0, 0)),
                       piece("sphere", (0.26, 0.3, 0.26), (0, 1.5, 0)),
                       piece("capsule", (0.13, 0.55, 0.13), (0.35, 1.0, 0)),
                       piece("capsule", (0.13, 0.55, 0.13), (-0.35, 1.0, 0)),
                       piece("sphere", (0.18, 0.18, 0.12), (0.4, 0.7, 0), material="grey"),
                       piece("capsule", (0.16, 0.6, 0.16), (0.12, 0.3, 0)))
        quality = model_quality.assess(keeper, role="player", visual_identity=LOOK)["quality"]
        self.assertFalse(quality["primitive_only"])
        self.assertEqual(quality["parts"], 6)
        self.assertEqual(quality["verdict"], "pass", quality["checks"])

    def test_copies_or_too_few_primitives_are_not_a_composition(self):
        cubes = [piece("box", (1, 1, 1), (0, y, 0)) for y in (0, 1.2, 2.4)]
        self.assertTrue(model_quality.assess(synth(*cubes))["quality"]["primitive_only"])
        pair = [piece("box", (1, 1, 1)), piece("sphere", (1, 1, 1), (0, 1.5, 0))]
        self.assertTrue(model_quality.assess(synth(*pair))["quality"]["primitive_only"])
        one_modelled = pair + [piece("box", (1, 1, 1), (0, 3, 0), taper=[0.5, 0.5])]
        self.assertFalse(model_quality.assess(synth(*one_modelled))["quality"]
                         ["primitive_only"])

    def test_the_role_and_the_art_direction_decide_the_verdict(self):
        data = synth(piece("box"))
        for role, look, verdict in (("player", LOOK, "fail"), ("threat", LOOK, "fail"),
                                    ("prop", LOOK, "pass"), ("environment", LOOK, "pass"),
                                    ("player", STYLED, "pass"), (None, LOOK, "pass")):
            with self.subTest(role=role, styled=look is STYLED):
                quality = model_quality.assess(data, role=role, visual_identity=look)["quality"]
                self.assertTrue(quality["primitive_only"])
                self.assertEqual(quality["verdict"], verdict)

    def test_the_placeholder_box_is_a_primitive(self):
        # The procedural stand-in the real run shipped as its goalkeeper: one box. It now
        # carries flat normals (it lights correctly as a stand-in) and is still refused as
        # a player.
        quality = model_quality.assess(encoders.glb("keeper", (90, 90, 90)), role="player",
                                       visual_identity=LOOK)["quality"]
        self.assertTrue(quality["primitive_only"])
        self.assertEqual(check(quality, "model.normals")["status"], "pass")
        self.assertEqual(check(quality, "model.primitive")["status"], "fail")
        self.assertEqual(check(quality, "model.palette")["status"], "fail")
        self.assertEqual(quality["verdict"], "fail")

    def test_the_palette(self):
        off = [{"id": "kit", "hex": "#00aaff"}]
        quality = model_quality.assess(synth(piece("box"), materials=off), role="prop",
                                       visual_identity=LOOK)["quality"]
        self.assertEqual(check(quality, "model.palette")["status"], "fail")
        near = [{"id": "kit", "hex": "#f0802a"}]  # a shade of the kit colour
        quality = model_quality.assess(synth(piece("box"), materials=near), role="prop",
                                       visual_identity=LOOK)["quality"]
        self.assertEqual(check(quality, "model.palette")["status"], "pass")
        self.assertEqual(check(model_quality.assess(synth(piece("box")))["quality"],
                               "model.palette")["status"], "skipped")

    def test_the_spec_part_count_and_fit_are_held_to_the_file(self):
        data = synth(piece("box", (1, 2, 1)), piece("sphere", (1, 1, 1), (0, 1.5, 0)))
        spec = {"parts": [{"id": "a", "shape": "box"}, {"id": "b", "shape": "sphere"},
                          {"id": "c", "shape": "cone", "mirror": "x"}],
                "fit": {"size": 5, "axis": "y"}}
        quality = model_quality.assess(data, spec=spec)["quality"]
        self.assertEqual(check(quality, "model.parts")["status"], "fail")
        self.assertIn("4 parts", check(quality, "model.parts")["summary"])
        self.assertEqual(check(quality, "model.bounds")["status"], "fail")

    def test_the_committed_blender_build_is_composed(self):
        with open(os.path.join(MODELS, "hover-car.glb"), "rb") as handle:
            geometry = model_quality.analyse(handle.read())
        self.assertEqual(sorted(p["shape"] for p in geometry["pieces"]),
                         ["box", "cylinder", "sphere"])
        self.assertTrue(geometry["normals"])
        self.assertFalse(model_quality.primitive_only(geometry["pieces"],
                                                      model_quality.load_bars()))

    def test_lods_and_collision_proxies_are_not_pieces(self):
        data = synth(piece("box"), piece("sphere", (1, 1, 1), (0, 2, 0)))

        def add(document):
            document["nodes"].append({"name": "model_collision", "mesh": 0})
            document["nodes"].append({"name": "model_LOD1", "mesh": 1})
            document["nodes"][0]["children"] += [3, 4]
        document, binary = gltf.load(data)
        add(document)
        data = glb_synth.pack(document, binary)
        self.assertEqual(len(model_quality.analyse(data)["pieces"]), 2)

    def test_the_bars_are_the_reference_files(self):
        bars = model_quality.load_bars()
        self.assertEqual(set(bars), set(model_quality.DEFAULT_BARS))
        self.assertEqual(bars, model_quality.DEFAULT_BARS)

    def test_the_quality_block_is_the_manifests(self):
        schema = ArtifactContracts().schemas["asset-manifest"]
        block = schema["properties"]["items"]["items"]["properties"]["quality"]
        quality = model_quality.assess(synth(piece("box")), role="player",
                                       author="author:command")["quality"]
        self.assertEqual(set(quality) - set(block["properties"]), set())
        from wgflib.jsonschema_lite import Validator
        self.assertEqual(list(Validator(block).iter_errors(quality)), [])

    def test_an_unreadable_file_fails_without_raising(self):
        quality = model_quality.assess(b"not a glb", role="player")["quality"]
        self.assertEqual(quality["verdict"], "fail")
        self.assertIsNone(quality["primitive_only"])


# -- the model author, with a fixture author and a fake Blender -------------------------------

FAKE_BLENDER = r'''#!{python}
# A stand-in for Blender, written by test_model_author.py: answers --version, and "builds"
# the resolved spec's parts as a synthetic GLB (glb_synth) - each part its primitive with
# normals, placed as a node, with the fit and the base-centre pivot applied. Taper and bevel
# are not modelled; a mirror arrives expanded.
import json, sys
sys.path.insert(0, {tests!r})
sys.path.insert(0, {scripts!r})
import glb_synth
from wgf_assets import gltf
args = sys.argv[1:]
if "--version" in args:
    print("Blender 4.5.14 LTS")
    sys.exit(0)
opts = dict(zip(args[args.index("--") + 1::2], args[args.index("--") + 2::2]))
spec = json.load(open(opts["--spec"]))
parts = spec["parts"]
data = glb_synth.build(parts, spec["materials"], name=spec["asset_id"])
if spec["fit"]:
    dims = gltf.inspect(data).summary["dimensions"]
    scale = spec["fit"]["size"] / (max(dims) if spec["fit"]["axis"] == "max"
                                   else dims["xyz".index(spec["fit"]["axis"])])
    parts = [dict(p, size=[v * scale for v in p["size"]],
                  translation=[v * scale for v in p["translation"]]) for p in parts]
    data = glb_synth.build(parts, spec["materials"], name=spec["asset_id"])
if spec["pivot"] == "base-center":
    bounds = gltf.inspect(data).summary["bounds"]
    document, binary = gltf.load(data)
    document["nodes"][0]["translation"] = [-(bounds["min"][0] + bounds["max"][0]) / 2,
                                           -bounds["min"][1],
                                           -(bounds["min"][2] + bounds["max"][2]) / 2]
    data = glb_synth.pack(document, binary)
open(opts["--out"], "wb").write(data)
json.dump({{"ok": True, "blender": "fake", "exporter": "9.9.9"}}, open(opts["--report"], "w"))
'''

# The fixture author: reads the request, writes a spec by MODE. `repair` writes an invalid
# spec first and the keeper once the request carries the problems.
FIXTURE_AUTHOR = r'''#!{python}
import json, sys
mode, request_path, spec_path = sys.argv[1:4]
request = json.load(open(request_path))
with open({log!r}, "a") as log:
    log.write(json.dumps({{"mode": mode, "asset": request["asset"],
                          "repair": request.get("repair"),
                          "craft": request.get("craft"),
                          "notes": request.get("notes"),
                          "frames": request.get("frames"),
                          "palette": request["palette"]}}) + "\n")
keeper = json.load(open({keeper!r}))
box = {box!r}
if mode == "crash":
    sys.exit(4)
if mode == "silent":
    sys.exit(0)
if mode == "keeper":
    spec = keeper
elif mode == "box":
    spec = json.loads(box)
elif mode == "repair":
    spec = keeper if request.get("repair") else dict(keeper, parts=keeper["parts"] + [
        {{"id": "cap", "shape": "hat", "material": "nope"}}])
elif mode == "stdout":
    print("Here is the spec:")
    print(json.dumps(keeper))
    sys.exit(0)
json.dump(spec, open(spec_path, "w"))
'''


class ModelAuthor(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.mkdtemp(prefix="wgf-model-author-")
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)
        self.blender = self.script("blender", FAKE_BLENDER.format(python=sys.executable,
                                                                  tests=HERE, scripts=SCRIPTS))
        self.log = os.path.join(self.scratch, "author.log")
        self.author = self.script("author", FIXTURE_AUTHOR.format(
            python=sys.executable, log=self.log, keeper=os.path.join(MODELS, "keeper.model.json"),
            box=json.dumps(BOX_SPEC)))
        self.out = os.path.join(self.scratch, "public", "assets", "models")

    def script(self, name, text):
        path = os.path.join(self.scratch, name)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)
        return path

    def settings(self, mode, **extra):
        # Repair rounds only: the review rounds over renders are test_model_review.py's.
        return dict({"kind": "command", "argv": [self.author, mode, "{request}", "{spec}"],
                     "blender": {"executable": self.blender}, "review_rounds": 0}, **extra)

    def produce(self, mode, requirement=KEEPER_REQ, look=LOOK, **extra):
        return model_author.produce_model(requirement, look, self.out, self.settings(mode, **extra),
                                          {"run_dir": os.path.join(self.scratch, "run")})

    def calls(self):
        if not os.path.exists(self.log):
            return []
        with open(self.log, encoding="utf-8") as handle:
            return [json.loads(line) for line in handle]

    def test_a_multi_part_keeper_passes(self):
        result = self.produce("keeper")
        self.assertEqual(result["files"], [os.path.join(self.out, "keeper.glb")])
        self.assertTrue(os.path.isfile(result["files"][0]))
        quality = result["quality"]
        self.assertEqual(quality["verdict"], "pass", quality["checks"])
        self.assertFalse(quality["primitive_only"])
        self.assertEqual(quality["parts"], 12)  # 8 parts, 4 of them mirrored
        self.assertEqual(quality["author"], "author:command")
        self.assertFalse(result["placeholder"])
        self.assertEqual(result["license"], "LicenseRef-factory-generated")
        self.assertEqual(result["rounds"], 1)
        (call,) = self.calls()
        self.assertEqual(call["asset"]["role"], "player")
        self.assertIn("gloves", call["asset"]["readability"])
        self.assertEqual(call["palette"], LOOK["palette"])
        self.assertIsNone(call["repair"])
        # The modeller is pointed at the 3D craft playbooks, which exist.
        self.assertTrue(call["craft"][0].endswith("production-art-3d.md"))
        for path in call["craft"]:
            self.assertTrue(os.path.isfile(path), path)

    def test_a_gates_feedback_reaches_the_request_with_its_frames(self):
        frame = os.path.join(self.scratch, "run", "playability", "desktop", "play-2s.png")
        requirement = dict(KEEPER_REQ, feedback={
            "notes": ["blocker assets finding `flat`: the keeper is a grey box"],
            "frames": [frame]})
        self.produce("keeper", requirement=requirement)
        (call,) = self.calls()
        self.assertEqual(call["notes"], ["blocker assets finding `flat`: the keeper is a grey box"])
        self.assertEqual(call["frames"], [frame])
        self.assertIn("Open every PNG in the request's `frames`", model_author.PROMPT_NOTES)
        # Without feedback the request carries neither.
        self.produce("keeper")
        self.assertIsNone(self.calls()[1]["notes"])

    def test_a_single_box_fails_for_a_readable_role(self):
        with self.assertRaises(model_author.ModelAuthorError) as raised:
            self.produce("box")
        self.assertFalse(raised.exception.retryable)
        self.assertTrue(any("model.primitive" in p for p in raised.exception.problems))
        calls = self.calls()
        self.assertEqual(len(calls), 1 + model_author.MAX_REPAIR_ROUNDS)
        self.assertTrue(any("model.primitive" in p for p in calls[1]["repair"]["problems"]))
        self.assertFalse(os.path.exists(os.path.join(self.out, "keeper.glb")))

    def test_a_single_box_passes_for_a_prop_and_under_primitive_style(self):
        crate = dict(KEEPER_REQ, id="crate", role="prop", description="a crate")
        result = self.produce("box", requirement=crate)
        self.assertTrue(result["quality"]["primitive_only"])
        self.assertEqual(result["quality"]["verdict"], "pass")
        styled = self.produce("box", look=STYLED)
        self.assertTrue(styled["quality"]["primitive_only"])
        self.assertEqual(styled["quality"]["verdict"], "pass")

    def test_an_invalid_spec_is_shown_back_and_repaired(self):
        result = self.produce("repair")
        self.assertEqual(result["rounds"], 2)
        self.assertEqual(result["quality"]["verdict"], "pass")
        first, second = self.calls()
        self.assertIsNone(first["repair"])
        problems = second["repair"]["problems"]
        self.assertTrue(any("hat" in p for p in problems), problems)
        self.assertTrue(any("nope" in p for p in problems), problems)
        self.assertEqual(result["history"][0]["problems"], problems)
        run = os.path.join(self.scratch, "run", "keeper")
        self.assertTrue(os.path.isfile(os.path.join(run, "round1.request.json")))
        self.assertTrue(os.path.isfile(os.path.join(run, "accepted.model.json")))

    def test_a_spec_on_stdout(self):
        result = self.produce("stdout", spec_from="stdout")
        self.assertEqual(result["quality"]["verdict"], "pass")

    def test_no_spec_is_a_repair_problem_and_a_failing_host_is_retryable(self):
        with self.assertRaises(model_author.ModelAuthorError) as raised:
            self.produce("silent", max_repair_rounds=0)
        self.assertIn("wrote no spec", str(raised.exception))
        with self.assertRaises(model_author.ModelAuthorError) as raised:
            self.produce("crash")
        self.assertTrue(raised.exception.retryable)

    def test_not_configured_or_no_blender_is_refused_before_the_author_runs(self):
        with self.assertRaises(model_author.ModelAuthorError):
            model_author.produce_model(KEEPER_REQ, LOOK, self.out, {"argv": []}, {})
        with self.assertRaises(model_author.ModelAuthorError):
            model_author.produce_model(KEEPER_REQ, LOOK, self.out,
                                       dict(self.settings("keeper"), kind="svg"), {})
        missing = dict(self.settings("keeper"),
                       blender={"executable": os.path.join(self.scratch, "no-blender")})
        with self.assertRaises(model_author.ModelAuthorError) as raised:
            model_author.produce_model(KEEPER_REQ, LOOK, self.out, missing,
                                       {"run_dir": self.scratch})
        self.assertIn("Blender", str(raised.exception))
        self.assertEqual(self.calls(), [])

    def test_the_requirements_declarations_are_held_to_the_model(self):
        # The requirement declares a clip the keeper spec does not build.
        with_clip = dict(KEEPER_REQ, model={"animations": [{"name": "dive"}]})
        with self.assertRaises(model_author.ModelAuthorError) as raised:
            self.produce("keeper", requirement=with_clip, max_repair_rounds=0)
        self.assertTrue(any("dive" in p for p in raised.exception.problems))

    def test_a_requirement_object_is_accepted(self):
        from wgf_assets.requirements import Requirement
        req = Requirement({"id": "keeper", "kind": "model", "label": "the keeper",
                           "role": "player"})
        self.assertEqual(model_author._requirement(req)["role"], "player")
        self.assertEqual(model_author._requirement(req)["description"], "the keeper")


# -- the model spec's shaping fields ----------------------------------------------------------

class ShapingFields(unittest.TestCase):
    def test_the_keeper_fixture_is_valid_and_mirrors_expand(self):
        spec = keeper_spec()
        self.assertEqual(modelspec.validate(spec), [])
        self.assertEqual(model_author._schema_problems(spec), [])
        resolved, _ = modelspec.resolve(spec, "keeper")
        by_id = {p["id"]: p for p in resolved["parts"]}
        self.assertEqual(len(by_id), 12)
        self.assertEqual(by_id["glove-mirror"]["parent"], "arm-mirror")
        self.assertEqual(by_id["arm-mirror"]["translation"][0], -by_id["arm"]["translation"][0])
        # Rz(25) mirrored is Rz(-25): the quaternion's z flips.
        self.assertAlmostEqual(by_id["arm-mirror"]["rotation"][2], -by_id["arm"]["rotation"][2])
        self.assertEqual(by_id["torso"]["taper"], [1.2, 1.0])
        self.assertEqual(by_id["torso"]["bevel"], 0.04)
        self.assertTrue(by_id["leg"]["smooth"])  # capsules are smooth by default

    def test_a_spec_without_them_resolves_as_before(self):
        spec = {"parts": [{"id": "a", "shape": "box"}]}
        resolved, _ = modelspec.resolve(spec, "x")
        self.assertEqual(set(resolved["parts"][0]),
                         {"id", "shape", "size", "segments", "translation", "rotation", "parent",
                          "material", "smooth"})

    def test_what_they_mean_together_is_checked(self):
        def problems(**part):
            return modelspec.validate({"parts": [dict({"id": "a", "shape": "box"}, **part)]})
        self.assertEqual(problems(taper=[0.5, 1.5], bevel=0.1), [])
        self.assertTrue(problems(taper=[5, 1]))
        self.assertTrue(problems(taper=[1, 1], shape="plane", size=[1, 0, 1]))
        self.assertTrue(problems(bevel=0.1, shape="sphere"))
        self.assertTrue(problems(bevel=0.5))  # over a third of 1 m
        self.assertTrue(problems(mirror="y"))
        twin = modelspec.validate({"parts": [{"id": "a", "shape": "box", "mirror": "x"},
                                             {"id": "a-mirror", "shape": "box"}]})
        self.assertTrue(any("mirror" in p for p in twin))
        track = {"parts": [{"id": "a", "shape": "box", "mirror": "x"}],
                 "animations": [{"name": "wave", "duration": 1, "tracks": [
                     {"part": "a-mirror", "path": "translation",
                      "keys": [{"t": 0, "value": [0, 0, 0]}, {"t": 1, "value": [0, 1, 0]}]}]}]}
        self.assertEqual(modelspec.validate(track), [])

    def test_mirroring_a_rotation_reflects_it(self):
        # M R M with M = diag(-1, 1, 1), for R = Rx Ry Rz, is Rx(a) Ry(-b) Rz(-c).
        self.assertEqual(modelspec.mirror_euler([10, 20, 30]), [10, -20, -30])


# -- real Blender ----------------------------------------------------------------------------

def _real_blender():
    if not enabled("WGF_BLENDER_TEST"):
        return None, "WGF_BLENDER_TEST=1 runs the real Blender builds"
    info = blender.discover()
    pin = load_policy().toolchains["blender"]
    if info.version is None:
        return None, blender.missing_message(info, pin)
    refusal = blender.check_pin(info, pin)
    return (None, refusal) if refusal else (info, None)


class RealBlenderAuthor(ModelAuthor):
    """The fixture author's specs, built by the pinned Blender and judged."""

    @classmethod
    def setUpClass(cls):
        cls.info, reason = _real_blender()
        if cls.info is None:
            raise unittest.SkipTest(reason)

    def setUp(self):
        super().setUp()
        self.blender = self.info.executable

    def test_the_keeper_is_shaped_deterministic_and_recognised(self):
        data, report, _key = blender.build_model(self.info, keeper_spec(), "keeper")
        self.assertEqual(blender.build_model(self.info, keeper_spec(), "keeper")[0], data)
        geometry = model_quality.analyse(data)
        shapes = {p["node"]: p["shape"] for p in geometry["pieces"]}
        # Bevelled and tapered parts are modelled; plain ones are still recognised.
        self.assertIsNone(shapes["torso"])
        self.assertIsNone(shapes["boot-mirror"])
        self.assertEqual(shapes["leg"], "capsule")
        self.assertEqual(shapes["head"], "sphere")
        self.assertEqual(shapes["neck"], "cylinder")
        summary = gltf.inspect(data).summary
        self.assertAlmostEqual(summary["dimensions"][1], 1.8, places=3)
        # The mirror stands across X = 0 from its part.
        document, _ = gltf.load(data)
        nodes = {n["name"]: n for n in document["nodes"]}
        self.assertAlmostEqual(nodes["arm-mirror"]["translation"][0],
                               -nodes["arm"]["translation"][0], places=5)

    def test_a_single_box_from_blender_is_primitive_only(self):
        data, _report, _key = blender.build_model(self.info, copy.deepcopy(BOX_SPEC), "box")
        quality = model_quality.assess(data, role="player", visual_identity=LOOK)["quality"]
        self.assertTrue(quality["primitive_only"])
        self.assertEqual(check(quality, "model.normals")["status"], "pass")
        self.assertEqual(quality["verdict"], "fail")


if __name__ == "__main__":
    unittest.main()

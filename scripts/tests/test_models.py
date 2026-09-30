"""3D models: the model spec, the GLB inspector, the Blender build tool, and the assets step
around them. docs/blender-pipeline.md.

Three layers of test, kept apart so nothing claims more than it ran:

  * no Blender at all - spec validation and resolution, the GLB inspector against crafted and
    procedural files, discovery, pinning, command and environment construction, stamping,
    and the assets step with a FAKE Blender: a small executable that answers `--version` and
    writes a GLB, run through wgflib.procs exactly like the real one. These always run.
  * the runtime - GLBs loaded by the pinned template's own three.js GLTFLoader in Node
    (threejs_runtime.py). Runs when node and the pinned template's dependencies are there;
    skips with the reason otherwise.
  * real Blender - WGF_BLENDER_TEST=1, with the pinned series found through the usual
    discovery (WGF_BLENDER or PATH). Builds real models, checks them, builds them twice, and
    rebuilds the committed fixture byte for byte. Skips, saying so, without it.

    python -m unittest scripts/tests/test_models.py
    WGF_BLENDER_TEST=1 WGF_BLENDER=/path/to/blender-4.5/blender python -m unittest ...
"""

import copy
import json
import os
import shutil
import stat
import struct
import sys
import tempfile
import textwrap
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, HERE)

from test_assets import AssetsCase, ajv, with_provenance  # noqa: E402
from testenv import enabled  # noqa: E402
import threejs_runtime  # noqa: E402
from wgf_assets import blender, encoders, formats, gltf, modelspec  # noqa: E402
from wgf_assets import runtime  # noqa: E402
from wgf_assets.policy import load_policy  # noqa: E402
from wgf_assets.requirements import RequirementError, inspect as inspect_requirements  # noqa: E402
from wgflib.workflow.contracts import ArtifactContracts  # noqa: E402

MODELS = os.path.join(HERE, "fixtures", "models")


def model_fixture(name):
    with open(os.path.join(MODELS, name), encoding="utf-8") as handle:
        return json.load(handle)


def read_bytes(path):
    with open(path, "rb") as handle:
        return handle.read()


def pack(document, binary=b""):
    """A GLB from a document and BIN bytes, as a test builds a broken one."""
    text = json.dumps(document, separators=(",", ":")).encode("utf-8")
    text += b" " * (-len(text) % 4)
    body = struct.pack("<I", len(text)) + b"JSON" + text
    if binary:
        binary += b"\0" * (-len(binary) % 4)
        body += struct.pack("<I", len(binary)) + b"BIN\x00" + binary
    return b"glTF" + struct.pack("<II", 2, 12 + len(body)) + body


def box(**kwargs):
    return encoders.glb("box", (120, 80, 40), **kwargs)


def edit(data, change):
    """`data` with `change(document)` applied to its JSON."""
    document, binary = gltf.load(data)
    change(document)
    return pack(document, binary or b"")


def codes(findings):
    return [(code, severity) for code, severity, _message in findings]


CAR = {
    "parts": [
        {"id": "body", "shape": "box", "size": [1, 0.5, 2], "position": [0, 0.5, 0],
         "material": "paint"},
        {"id": "wheel", "shape": "cylinder", "size": [0.4, 0.2, 0.4],
         "position": [0.55, 0.2, 0.6], "rotation": [0, 0, 90], "material": "tyre"},
    ],
    "materials": [{"id": "paint", "color": "#ff3366",
                   "texture": {"pattern": "checker", "size": 64}},
                  {"id": "tyre", "color": "#222222"}],
    "animations": [{"name": "idle", "duration": 1, "tracks": [
        {"part": "body", "path": "translation",
         "keys": [{"t": 0, "value": [0, 0.5, 0]}, {"t": 0.5, "value": [0, 0.6, 0]},
                  {"t": 1, "value": [0, 0.5, 0]}]}]}],
    "collision": {"shape": "box"},
}


# -- the model spec -------------------------------------------------------------------------

class Spec(unittest.TestCase):
    def test_a_valid_spec_has_no_problems_and_resolves(self):
        self.assertEqual(modelspec.validate(CAR), [])
        resolved, textures = modelspec.resolve(CAR, "car")
        self.assertEqual([p["id"] for p in resolved["parts"]], ["body", "wheel"])
        self.assertEqual(list(textures), ["car-paint.png"])
        png = formats.sniff(textures["car-paint.png"])
        self.assertEqual((png.format, png.width, png.height), ("png", 64, 64))
        # A textured material carries its colour in the texture, not twice.
        self.assertEqual(resolved["materials"][0]["color"], [1.0, 1.0, 1.0, 1.0])
        # sRGB #222222 is linear 0.0159...
        self.assertAlmostEqual(resolved["materials"][1]["color"][0], 0.015996, places=5)

    def test_resolution_is_deterministic_and_the_hash_ignores_key_order(self):
        self.assertEqual(modelspec.resolve(CAR, "car"), modelspec.resolve(CAR, "car"))
        shuffled = json.loads(json.dumps(CAR, sort_keys=True))
        self.assertEqual(modelspec.spec_hash(CAR), modelspec.spec_hash(shuffled))
        changed = copy.deepcopy(CAR)
        changed["parts"][0]["size"][0] = 1.1
        self.assertNotEqual(modelspec.spec_hash(CAR), modelspec.spec_hash(changed))

    def test_euler_degrees_become_threejs_xyz_quaternions(self):
        x, y, z, w = modelspec.euler_to_quaternion([0, 90, 0])
        self.assertAlmostEqual(y, 0.7071068, places=6)
        self.assertAlmostEqual(w, 0.7071068, places=6)
        self.assertEqual(modelspec.euler_to_quaternion([0, 0, 0]), [0.0, 0.0, 0.0, 1.0])

    def test_parents_come_before_children(self):
        spec = {"parts": [{"id": "hand", "shape": "box", "parent": "arm"},
                          {"id": "arm", "shape": "box", "parent": "torso"},
                          {"id": "torso", "shape": "box"}]}
        resolved, _ = modelspec.resolve(spec, "bot")
        self.assertEqual([p["id"] for p in resolved["parts"]], ["torso", "arm", "hand"])

    def test_tracks_are_held_to_the_clip_ends(self):
        spec = {"parts": [{"id": "a", "shape": "box"}], "animations": [{
            "name": "nod", "duration": 2, "tracks": [{"part": "a", "path": "rotation", "keys": [
                {"t": 0.5, "value": [0, 0, 0]}, {"t": 1, "value": [30, 0, 0]}]}]}]}
        track = modelspec.resolve(spec, "x")[0]["animations"][0]["tracks"][0]
        self.assertEqual(track["times"], [0.0, 0.5, 1.0, 2.0])
        self.assertEqual(track["values"][0], track["values"][1])
        self.assertEqual(track["values"][-1], track["values"][-2])

    def test_what_the_spec_means_together_is_checked(self):
        cases = {
            "duplicate part id": {"parts": [{"id": "a", "shape": "box"},
                                            {"id": "a", "shape": "box"}]},
            "no material 'x'": {"parts": [{"id": "a", "shape": "box", "material": "x"}]},
            "parent chain is a cycle": {"parts": [{"id": "a", "shape": "box", "parent": "b"},
                                                  {"id": "b", "shape": "box", "parent": "a"}]},
            "shape: one of": {"parts": [{"id": "a", "shape": "torus"}]},
            "size: [x, y, z], non-negative": {"parts": [{"id": "a", "shape": "box",
                                                         "size": [1, 0, 1]}]},
            "times must increase": {"parts": [{"id": "a", "shape": "box"}], "animations": [{
                "name": "n", "duration": 1, "tracks": [{"part": "a", "path": "scale", "keys": [
                    {"t": 0.5, "value": [1, 1, 1]}, {"t": 0.2, "value": [2, 2, 2]}]}]}]},
            "after the clip's duration": {"parts": [{"id": "a", "shape": "box"}], "animations": [{
                "name": "n", "duration": 1, "tracks": [{"part": "a", "path": "scale", "keys": [
                    {"t": 0, "value": [1, 1, 1]}, {"t": 2, "value": [2, 2, 2]}]}]}]},
            "180 degrees or more": {"parts": [{"id": "a", "shape": "box"}], "animations": [{
                "name": "spin", "duration": 1, "tracks": [{"part": "a", "path": "rotation",
                                                           "keys": [{"t": 0, "value": [0, 0, 0]},
                                                                    {"t": 1, "value": [0, 360, 0]}]
                                                           }]}]},
            "never changes": {"parts": [{"id": "a", "shape": "box"}], "animations": [{
                "name": "hold", "duration": 1, "tracks": [{"part": "a", "path": "scale", "keys": [
                    {"t": 0, "value": [1, 2, 1]}]}]}]},
            "an animated model has one level": {
                "parts": [{"id": "a", "shape": "box"}], "lods": [0.5],
                "animations": [{"name": "n", "duration": 1, "tracks": [
                    {"part": "a", "path": "scale", "keys": [{"t": 0, "value": [1, 1, 1]},
                                                            {"t": 1, "value": [2, 2, 2]}]}]}]},
            "decreasing ratios": {"parts": [{"id": "a", "shape": "box"}], "lods": [0.5, 0.7]},
            "collision.shape": {"parts": [{"id": "a", "shape": "box"}],
                                "collision": {"shape": "mesh"}},
            "texture.size": {"parts": [{"id": "a", "shape": "box"}], "materials": [
                {"id": "m", "texture": {"pattern": "checker", "size": 100}}]},
            "budget.max_triangles": {"parts": [{"id": "a", "shape": "box"}],
                                     "budget": {"max_triangles": 0}},
        }
        for expected, spec in cases.items():
            with self.subTest(expected):
                problems = modelspec.validate(spec)
                self.assertTrue(any(expected in p for p in problems), problems)

    def test_a_plane_may_be_flat_and_an_expectation_needs_no_parts(self):
        self.assertEqual(modelspec.validate({"parts": [{"id": "g", "shape": "plane",
                                                        "size": [10, 0, 10]}]}), [])
        expectation = {"animations": [{"name": "run"}], "lods": 2, "collision": {"shape": "box"}}
        self.assertEqual(modelspec.validate(expectation), [])
        self.assertFalse(modelspec.buildable(expectation))
        with self.assertRaises(modelspec.ModelSpecError):
            modelspec.resolve(expectation, "x")

    def test_expectations_combine_the_spec_and_the_policy(self):
        kind = load_policy().kind("model")
        expect = modelspec.expectations({"animations": [{"name": "run", "duration": 0.5}],
                                         "lods": [0.5, 0.25], "budget": {"max_triangles": 99}},
                                        kind)
        self.assertEqual(expect["clips"], {"run": 0.5})
        self.assertEqual(expect["lods"], 2)
        self.assertEqual(expect["max_triangles"], 99)
        self.assertTrue(expect["budget_declared"]["max_triangles"])
        self.assertEqual(expect["max_texture_edge"], kind.max_texture_edge)
        self.assertFalse(expect["budget_declared"]["max_texture_edge"])

    def test_the_schema_and_the_design_contract_accept_it(self):
        contracts = ArtifactContracts()
        design = model_fixture("design-models.json")
        artifact = with_provenance(design, "game-design", design["title_id"])
        self.assertEqual(contracts.problems("game-design", artifact), [])
        design["asset_requirements"][0]["model"]["parts"][0]["shape"] = "torus"
        artifact = with_provenance(design, "game-design", design["title_id"])
        self.assertTrue(any("/model/parts/0/shape" in p
                            for p in contracts.problems("game-design", artifact)))


class Requirements(unittest.TestCase):
    def design(self, requirements):
        return {"title_id": "t", "asset_requirements": requirements}

    def test_the_designs_engine_decides_the_dimension(self):
        # A Three.js design with no 3D-only requirement and a flat art direction is still 3D:
        # its derived baseline is an environment and a player model, not a background image.
        design = {"title_id": "t", "engine": {"type": "threejs", "dimension": "3d",
                                              "rationale": "depth is the mechanic"},
                  "art_direction": "Neon signage, flat and bright."}
        reqs, dimension = inspect_requirements(design, load_policy())
        self.assertEqual(dimension, "3d")
        self.assertIn("model-player", [r.id for r in reqs])
        design["engine"] = {"type": "pixijs", "dimension": "2d", "rationale": "flat"}
        design["art_direction"] = "low-poly 3d look"
        self.assertEqual(inspect_requirements(design, load_policy())[1], "2d")

    def test_an_invalid_spec_fails_the_requirement_list(self):
        with self.assertRaises(RequirementError) as caught:
            inspect_requirements(self.design([{"id": "car", "kind": "model", "model": {
                "parts": [{"id": "a", "shape": "box", "material": "nope"}]}}]), load_policy())
        self.assertIn("asset 'car': model.parts[0].material", str(caught.exception))

    def test_a_spec_is_only_for_glb_kinds(self):
        with self.assertRaises(RequirementError) as caught:
            inspect_requirements(self.design([{"id": "hero", "kind": "sprite", "model": {}}]),
                                 load_policy())
        self.assertIn("model is for model, environment, animation", str(caught.exception))

    def test_a_part_may_not_take_the_assets_name(self):
        with self.assertRaises(RequirementError) as caught:
            inspect_requirements(self.design([{"id": "car", "kind": "model", "model": {
                "parts": [{"id": "car", "shape": "box"}]}}]), load_policy())
        self.assertIn("may not share the asset's id", str(caught.exception))


# -- the GLB inspector ----------------------------------------------------------------------

class Inspector(unittest.TestCase):
    def test_procedural_placeholders_are_clean_and_measured(self):
        for shape, animated, triangles, dims in (("box", False, 12, [1.0, 1.0, 1.0]),
                                                 ("box", True, 12, [1.0, 1.0, 1.0]),
                                                 ("environment", False, 14, [20.0, 2.0, 20.0])):
            with self.subTest(shape=shape, animated=animated):
                result = gltf.inspect(box(shape=shape, animated=animated), kind="environment")
                self.assertEqual(result.findings, [])
                self.assertEqual(result.summary["triangles"], triangles)
                self.assertEqual(result.summary["dimensions"], dims)
                self.assertEqual(result.summary["bounds"]["min"][1], 0.0)
                self.assertEqual(len(result.summary["animations"]), int(animated))

    def test_unreadable_files(self):
        data = box()
        for label, broken in (("truncated", data[:-8]), ("not glTF", b"hello"),
                              ("wrong length", data[:8] + struct.pack("<I", 7) + data[12:]),
                              ("glTF 1.0", edit(data, lambda d: d["asset"].update(version="1.0")))):
            with self.subTest(label):
                result = gltf.inspect(broken)
                self.assertEqual(codes(result.findings), [("model-invalid", "error")])
                self.assertIsNone(result.summary)

    def test_broken_references_and_ranges(self):
        cases = {
            "mesh index": lambda d: d["nodes"][0].update(mesh=7),
            "scene node": lambda d: d["scenes"][0]["nodes"].append(9),
            "material": lambda d: d["meshes"][0]["primitives"][0].update(material=3),
            "accessor range": lambda d: d["accessors"][0].update(count=10_000),
            "bufferView range": lambda d: d["bufferViews"][0].update(byteLength=1 << 20),
            "no scene": lambda d: d.pop("scenes"),
        }
        for label, change in cases.items():
            with self.subTest(label):
                result = gltf.inspect(edit(box(), change))
                self.assertIn(("model-invalid", "error"), codes(result.findings))

    def test_a_node_with_two_parents_or_a_cycle(self):
        def two_parents(d):
            d["nodes"].append({"name": "a", "children": [0]})
            d["nodes"].append({"name": "b", "children": [0]})
            d["scenes"][0]["nodes"] = [1, 2]

        def cycle(d):
            d["nodes"].append({"name": "a", "children": [2]})
            d["nodes"].append({"name": "b", "children": [1]})

        for change in (two_parents, cycle):
            with self.subTest(change.__name__):
                self.assertIn(("model-invalid", "error"),
                              codes(gltf.inspect(edit(box(), change)).findings))

    def test_external_references_are_errors_in_a_shipped_model(self):
        external_buffer = edit(box(), lambda d: d["buffers"].append(
            {"uri": "extra.bin", "byteLength": 4}))
        self.assertIn(("model-external-reference", "error"),
                      codes(gltf.inspect(external_buffer).findings))
        external_image = edit(box(), lambda d: d.update(images=[{"uri": "../tex/wood.png"}]))
        self.assertIn(("model-external-reference", "error"),
                      codes(gltf.inspect(external_image).findings))

    def test_extensions_the_runtime_cannot_read_or_needs_a_decoder_for(self):
        unknown = edit(box(), lambda d: d.update(extensionsUsed=["VENDOR_magic"],
                                                 extensionsRequired=["VENDOR_magic"]))
        self.assertIn(("model-unsupported-extension", "error"),
                      codes(gltf.inspect(unknown).findings))
        draco = edit(box(), lambda d: d.update(
            extensionsUsed=["KHR_draco_mesh_compression"],
            extensionsRequired=["KHR_draco_mesh_compression"]))
        findings = gltf.inspect(draco).findings
        self.assertEqual(codes(findings), [("model-needs-decoder", "warning")])
        self.assertIn("DRACOLoader", findings[0][2])

    def test_transforms(self):
        cases = {
            ("model-transform", "error"): [
                lambda d: d["nodes"][0].update(scale=[1, 0, 1]),
                lambda d: d["nodes"][0].update(rotation=[0, 0, 0, 2]),
                lambda d: d["nodes"][0].update(translation=[0, "x", 0]),
                lambda d: d["nodes"][0].update(matrix=[1] * 16, scale=[1, 1, 1]),
            ],
            ("model-transform", "warning"): [lambda d: d["nodes"][0].update(scale=[-1, 1, 1])],
        }
        for expected, changes in cases.items():
            for change in changes:
                with self.subTest(expected):
                    self.assertIn(expected, codes(gltf.inspect(edit(box(), change)).findings))

    def test_scale_that_reads_as_the_wrong_unit(self):
        huge = edit(box(), lambda d: d["nodes"][0].update(scale=[300, 300, 300]))
        tiny = edit(box(), lambda d: d["nodes"][0].update(scale=[0.001, 0.001, 0.001]))
        for data in (huge, tiny):
            self.assertIn(("model-scale", "warning"), codes(gltf.inspect(data).findings))
        self.assertEqual(gltf.inspect(huge, kind="environment").findings, [])

    def test_animation_problems(self):
        def rename(name):
            return lambda d: d["animations"][0].update(name=name)

        def duplicate(d):
            d["animations"].append(copy.deepcopy(d["animations"][0]))

        def short_output(d):
            d["accessors"][d["animations"][0]["samplers"][0]["output"]]["count"] = 1

        cases = [(rename(""), ("animation-invalid", "warning")),
                 (duplicate, ("animation-invalid", "error")),
                 (short_output, ("animation-invalid", "error")),
                 (lambda d: d["animations"][0]["channels"][0]["target"].update(path="colour"),
                  ("animation-invalid", "error"))]
        for change, expected in cases:
            with self.subTest(expected):
                self.assertIn(expected,
                              codes(gltf.inspect(edit(box(animated=True), change)).findings))

    def test_lods_and_collision_are_found_by_convention(self):
        def add_roles(d):
            d["nodes"][0]["name"] = "crate_LOD0"
            d["nodes"].append({"name": "crate_LOD1", "mesh": 0})
            d["nodes"].append({"name": "UCX_crate", "mesh": 0})
            d["scenes"][0]["nodes"] += [1, 2]

        summary = gltf.inspect(edit(box(), add_roles)).summary
        self.assertEqual([(l["level"], l["node"]) for l in summary["lods"]],
                         [(0, "crate_LOD0"), (1, "crate_LOD1")])
        self.assertEqual(summary["collision"]["node"], "UCX_crate")
        self.assertEqual(summary["triangles"], 12)  # LOD1 and the proxy are not the model

    def test_an_embedded_texture_is_measured(self):
        image = encoders.png(100, 64, (1, 2, 3))

        def embed(d):
            d["bufferViews"].append({"buffer": 0, "byteOffset": d["buffers"][0]["byteLength"],
                                     "byteLength": len(image)})
            d["buffers"][0]["byteLength"] += len(image)
            d["images"] = [{"bufferView": len(d["bufferViews"]) - 1, "mimeType": "image/png"}]

        document, binary = gltf.load(box())
        embed(document)
        result = gltf.inspect(pack(document, binary + image))
        self.assertEqual(result.summary["textures"], [{"format": "png", "width": 100,
                                                       "height": 64}])
        self.assertIn(("not-power-of-two", "warning"), codes(result.findings))

    def test_expectations(self):
        summary = gltf.inspect(box(animated=True)).summary
        policy = load_policy().kind("model")

        def check(spec, data=None):
            return codes(gltf.check_expectations(summary, modelspec.expectations(spec, policy),
                                                 data))

        self.assertEqual(check({"animations": [{"name": "box", "duration": 1}]}), [])
        self.assertIn(("animation-missing", "error"), check({"animations": [{"name": "run"}]}))
        self.assertIn(("animation-invalid", "warning"),
                      check({"animations": [{"name": "box", "duration": 3}]}))
        self.assertIn(("lod-missing", "error"), check({"lods": 1}))
        self.assertIn(("collision-missing", "error"), check({"collision": {"shape": "box"}}))
        self.assertIn(("model-scale", "error"), check({"fit": {"size": 2, "axis": "y"}}))
        self.assertEqual(check({"fit": {"size": 1, "axis": "y"}}), [])
        self.assertIn(("model-over-budget", "error"), check({"budget": {"max_triangles": 10}}))
        self.assertIn(("too-large", "error"), check({"budget": {"max_bytes": 10}}, b"x" * 11))
        off_centre = dict(summary, bounds={"min": [0.4, 0.2, 0], "max": [1.4, 1.2, 1]})
        self.assertIn(("model-pivot", "warning"), codes(gltf.check_expectations(
            off_centre, modelspec.expectations({"pivot": "base-center"}, policy))))
        heavy = dict(summary, triangles=30_000)
        self.assertIn(("model-over-budget", "warning"), codes(gltf.check_expectations(
            heavy, modelspec.expectations({}, policy))))
        self.assertIn(("texture-too-large", "warning"), codes(gltf.check_expectations(
            dict(summary, textures=[{"format": "png", "width": 4096, "height": 4096}]),
            modelspec.expectations({}, policy))))

    def test_measurements_survive_the_artifact_hash(self):
        # A bound of 3e-05 m printed with 6 decimals is "3e-05", which the canonical hash
        # refuses; the summary must never hold a number like that.
        from wgflib.hashing import stable_stringify
        nudged = edit(box(animated=True),
                      lambda d: d["nodes"][0].update(translation=[0.00003, 0.0000123, 0]))
        summary = gltf.inspect(nudged).summary
        stable_stringify(summary)
        self.assertEqual(summary["bounds"]["min"][0], -0.5)

    def test_lod_levels_must_reduce(self):
        summary = {"triangles": 100, "lods": [{"level": 0, "node": "a", "triangles": 100},
                                              {"level": 1, "node": "b", "triangles": 120}]}
        self.assertIn(("lod-invalid", "warning"), codes(gltf.check_expectations(
            summary, modelspec.expectations({"lods": 1}))))


# -- the Blender layer, without Blender -----------------------------------------------------

FAKE_BLENDER = r'''#!{python}
# A stand-in for Blender: answers --version, and "builds" a box GLB named after the asset
# with one clip per spec clip and, when asked, a collision proxy - enough for the step to
# meet a spec without LODs or a fit. Written by test_models.py.
import json, struct, sys
sys.path.insert(0, {scripts!r})
from wgf_assets import encoders, gltf
args = sys.argv[1:]
with open({log!r}, "a") as log:
    log.write(json.dumps(args) + "\n")
if "--version" in args:
    print({version_line!r})
    print("\tbuild date: fake")
    sys.exit(0)
opts = dict(zip(args[args.index("--") + 1::2], args[args.index("--") + 2::2]))
spec = json.load(open(opts["--spec"]))
if {mode!r} == "crash":
    sys.exit(9)
if {mode!r} == "fail":
    json.dump({{"ok": False, "error": "RuntimeError: exporter exploded"}}, open(opts["--report"], "w"))
    sys.exit(3)
document, binary = gltf.load(encoders.glb(spec["asset_id"], (200, 100, 50),
                                          animated=bool(spec["animations"])))
if spec["animations"]:
    template = document["animations"][0]
    document["animations"] = [dict(template, name=clip["name"]) for clip in spec["animations"]]
if spec["collision"]:
    document["nodes"].append({{"name": spec["asset_id"] + "_collision", "mesh": 0,
                              "extras": {{"wgf_role": "collision",
                                         "wgf_shape": spec["collision"]["shape"]}}}})
    document["scenes"][0]["nodes"].append(len(document["nodes"]) - 1)
text = json.dumps(document, separators=(",", ":")).encode()
text += b" " * (-len(text) % 4)
body = struct.pack("<I", len(text)) + b"JSON" + text
body += struct.pack("<I", len(binary)) + b"BIN\x00" + binary
open(opts["--out"], "wb").write(b"glTF" + struct.pack("<II", 2, 12 + len(body)) + body)
json.dump({{"ok": True, "blender": "fake", "exporter": "9.9.9",
            "export_options_unsupported": ["export_gone"]}}, open(opts["--report"], "w"))
'''


class FakeBlender:
    def __init__(self, directory, version_line="Blender 4.5.14 LTS", mode="ok"):
        self.path = os.path.join(directory, "blender")
        self.log = os.path.join(directory, "blender.log")
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write(FAKE_BLENDER.format(python=sys.executable, scripts=SCRIPTS, log=self.log,
                                             version_line=version_line, mode=mode))
        os.chmod(self.path, os.stat(self.path).st_mode | stat.S_IEXEC)

    def calls(self):
        if not os.path.exists(self.log):
            return []
        with open(self.log, encoding="utf-8") as handle:
            return [json.loads(line) for line in handle]

    def builds(self):
        return [c for c in self.calls() if "--version" not in c]


class BlenderLayer(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.mkdtemp(prefix="wgf-blender-test-")
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)
        self.pin = load_policy().toolchains["blender"]

    def test_version_parsing(self):
        self.assertEqual(blender.parse_version("Blender 4.5.14 LTS\n\tbuild date"), (4, 5, 14))
        self.assertEqual(blender.parse_version("Blender 5.0\n"), (5, 0, 0))
        self.assertIsNone(blender.parse_version("command not found"))

    def test_discovery_order_config_then_env_then_path(self):
        fake = FakeBlender(self.scratch)
        info = blender.discover(fake.path, environ={"PATH": ""})
        self.assertEqual((info.source, info.version), ("config", (4, 5, 14)))
        info = blender.discover(None, environ={"WGF_BLENDER": fake.path, "PATH": ""})
        self.assertEqual((info.source, info.raw), ("env", "Blender 4.5.14 LTS"))
        info = blender.discover(None, environ={"PATH": self.scratch})
        self.assertEqual(info.source, "path")
        self.assertEqual(blender.check_pin(info, self.pin), None)

    def test_missing_blender_says_what_to_do(self):
        info = blender.discover(None, environ={"PATH": self.scratch})
        self.assertIsNone(info.executable)
        message = blender.missing_message(info, self.pin)
        for needle in ("blender is not on PATH", "Blender 4.5.x", "WGF_BLENDER",
                       "factory.assets.placeholders.blender.executable"):
            self.assertIn(needle, message)
        info = blender.discover(os.path.join(self.scratch, "nope"), environ={"PATH": ""})
        self.assertIn("is not an executable file", info.error)

    def test_the_series_is_pinned(self):
        other = blender.discover(FakeBlender(self.scratch, "Blender 5.0.1").path,
                                 environ={"PATH": ""})
        refusal = blender.check_pin(other, self.pin)
        self.assertIn("not the pinned series 4.5", refusal)
        self.assertIn("allow_unpinned", refusal)
        self.assertIsNone(blender.check_pin(other, self.pin, allow_unpinned=True))
        old = blender.BlenderInfo("/x/blender", "path", (3, 6, 0))
        self.assertIn("older than 4.2", blender.check_pin(old, self.pin, allow_unpinned=True))

    def test_command_and_environment(self):
        argv = blender.build_command("/opt/blender", spec="s.json", textures="t", out="o.glb",
                                     report="r.json", version=(4, 5, 14))
        self.assertEqual(argv[:5], ["/opt/blender", "--background", "--factory-startup",
                                    "-noaudio", "--offline-mode"])
        self.assertEqual(argv[argv.index("--python-exit-code") + 1], "3")
        self.assertEqual(argv[argv.index("--python") + 1], blender.SCRIPT)
        self.assertEqual(argv[argv.index("--") + 1:],
                         ["--spec", "s.json", "--textures", "t", "--out", "o.glb",
                          "--report", "r.json"])
        os.environ["WGF_SECRET_FOR_TEST"] = "leak"
        self.addCleanup(os.environ.pop, "WGF_SECRET_FOR_TEST", None)
        env = blender.build_environment(self.scratch)
        self.assertNotIn("WGF_SECRET_FOR_TEST", env)
        self.assertTrue(env["HOME"].startswith(self.scratch))
        self.assertTrue(env["BLENDER_USER_CONFIG"].startswith(self.scratch))
        self.assertEqual(env["PYTHONNOUSERSITE"], "1")

    def test_the_generation_key_follows_everything_that_changes_the_bytes(self):
        resolved, textures = modelspec.resolve(CAR, "car")
        key = blender.generation_key(resolved, textures, "4.5")
        self.assertEqual(key, blender.generation_key(resolved, textures, "4.5"))
        self.assertNotEqual(key, blender.generation_key(resolved, textures, "5.0"))
        self.assertNotEqual(key, blender.generation_key(resolved, {"car-paint.png": b"x"}, "4.5"))
        moved = copy.deepcopy(resolved)
        moved["parts"][0]["translation"][0] = 0.1
        self.assertNotEqual(key, blender.generation_key(moved, textures, "4.5"))

    def test_stamp_round_trip_keeps_the_geometry(self):
        data = box(animated=True)
        stamped = blender.stamp(data, {"key": "sha256:" + "0" * 64, "blender": "4.5.14"})
        self.assertEqual(blender.read_stamp(stamped)["blender"], "4.5.14")
        self.assertIsNone(blender.read_stamp(data))
        self.assertEqual(gltf.load(stamped)[1], gltf.load(data)[1])
        self.assertEqual(gltf.inspect(stamped).findings, [])
        self.assertEqual(formats.sniff(stamped).format, "glb")

    def test_a_build_runs_the_script_through_the_owned_process(self):
        fake = FakeBlender(self.scratch)
        info = blender.discover(fake.path, environ={"PATH": ""})
        data, report, key = blender.build_model(info, CAR, "car", series="4.5")
        self.assertEqual(blender.read_stamp(data)["key"], key)
        self.assertEqual(blender.read_stamp(data)["exporter"], "9.9.9")
        self.assertEqual(report["export_options_unsupported"], ["export_gone"])
        build = fake.builds()[0]
        self.assertIn("--factory-startup", build)
        spec_path = build[build.index("--spec") + 1]
        self.assertFalse(os.path.exists(spec_path), "the scratch directory is removed")

    def test_failed_builds_raise_with_the_reason(self):
        for mode, needle in (("fail", "exporter exploded"), ("crash", "exited")):
            with self.subTest(mode):
                directory = os.path.join(self.scratch, mode)
                os.makedirs(directory)
                info = blender.discover(FakeBlender(directory, mode=mode).path,
                                        environ={"PATH": ""})
                with self.assertRaises(blender.BlenderError) as caught:
                    blender.build_model(info, CAR, "car")
                self.assertIn(needle, str(caught.exception))


# -- the assets step, with a fake Blender ---------------------------------------------------

def models_design(**overrides):
    """fixtures/models/design-models.json as a sealed game-design; `overrides` by item id."""
    body = model_fixture("design-models.json")
    for req in body["asset_requirements"]:
        req.update(overrides.get(req["id"], {}))
    return with_provenance(body, "game-design", body["title_id"])


class Pipeline(AssetsCase):
    def setUp(self):
        super().setUp()
        self.tools = tempfile.mkdtemp(prefix="wgf-fake-blender-")
        self.addCleanup(shutil.rmtree, self.tools, ignore_errors=True)
        self.fake = FakeBlender(self.tools)

    @staticmethod
    def models_design(**overrides):
        return models_design(**overrides)

    def blender_settings(self, **extra):
        return {"backends": ["procedural"], "blender": dict({"executable": self.fake.path},
                                                            **extra)}

    def test_a_spec_is_built_into_a_final_production_ready_model(self):
        manifest = self.manifest(self.models_design(), placeholders=self.blender_settings())
        item = self.items(manifest)["hover-car"]
        self.assertEqual((item["status"], item["source"], item["placeholder"]),
                         ("delivered", "procedural", False))
        self.assertTrue(item["production_ready"])
        self.assertEqual(item["files"][0]["path"], "public/assets/models/hover-car.glb")
        generation = item["model"]["generation"]
        self.assertEqual((generation["tool"], generation["version"], generation["pinned"],
                          generation["reused"]), ("blender", "4.5.14", True, False))
        self.assertEqual(item["origin"], {"kind": "generated", "generator": "blender 4.5.14"})
        self.assertEqual([c["name"] for c in item["model"]["animations"]], ["hover", "spin"])
        self.assertEqual(item["model"]["collision"]["node"], "hover-car_collision")
        self.assertEqual(self.codes(manifest, "hover-car"), [])
        backends = {b["id"]: b for b in manifest["generation"]["backends"]}
        self.assertEqual(backends["blender"]["used"], 1)
        self.assertEqual(ArtifactContracts().problems("asset-manifest", manifest), [])

    def test_a_model_the_build_did_not_meet_is_not_production_ready(self):
        spec = model_fixture("design-models.json")["asset_requirements"][0]["model"]
        spec.pop("animations")
        spec["lods"] = 1  # the fake builds no LODs
        design = self.models_design(**{"hover-car": {"model": spec}})
        manifest = self.manifest(design, placeholders=self.blender_settings())
        item = self.items(manifest)["hover-car"]
        self.assertIn(("lod-missing", "error"), self.codes(manifest, "hover-car"))
        self.assertFalse(item["production_ready"])

    def test_the_runtime_manifest_carries_each_models_lookups(self):
        manifest = self.manifest(self.models_design(), placeholders=self.blender_settings())
        document = json.loads(self.read(runtime.RUNTIME_PATH))
        self.assertEqual(manifest["runtime_manifest"]["path"], runtime.RUNTIME_PATH)
        assets = document["assets"]
        car = assets["hover-car"]
        self.assertEqual((car["type"], car["url"], car["format"]),
                         ("model", "models/hover-car.glb", "glb"))
        self.assertEqual(car["model"]["clips"], ["hover", "spin"])
        self.assertEqual(car["model"]["collision"],
                         {"node": "hover-car_collision", "shape": "box"})
        self.assertEqual(car["model"]["triangles"],
                         self.items(manifest)["hover-car"]["model"]["triangles"])
        self.assertTrue(assets["crate"]["placeholder"])
        self.assertIn("model", assets["arena"])
        # The fixture checkout holds unrelated files (unused-file warnings); nothing may be an
        # error - the schema, every url, size and hash, and the GLBs' formats.
        self.assertEqual([p for p in runtime.validate(self.root) if p["severity"] == "error"],
                         [])

    def test_a_rerun_without_blender_reuses_the_committed_build(self):
        self.manifest(self.models_design(), placeholders=self.blender_settings())
        before = self.read("public/assets/models/hover-car.glb")
        builds = len(self.fake.builds())
        missing = os.path.join(self.tools, "gone")
        manifest = self.manifest(self.models_design(),
                                 placeholders=self.blender_settings(executable=missing))
        item = self.items(manifest)["hover-car"]
        self.assertEqual(self.read("public/assets/models/hover-car.glb"), before)
        self.assertTrue(item["model"]["generation"]["reused"])
        self.assertTrue(item["production_ready"])
        self.assertEqual(len(self.fake.builds()), builds)
        note = {b["id"]: b for b in manifest["generation"]["backends"]}["blender"]["note"]
        self.assertTrue(note.startswith("reuse-only: Blender not available"), note)

    def test_a_changed_spec_without_blender_falls_back_and_says_so(self):
        self.manifest(self.models_design(), placeholders=self.blender_settings())
        spec = model_fixture("design-models.json")["asset_requirements"][0]["model"]
        spec["parts"][0]["size"] = [1.5, 0.4, 2.5]
        design = self.models_design(**{"hover-car": {"model": spec}})
        missing = os.path.join(self.tools, "gone")
        manifest = self.manifest(design, placeholders=self.blender_settings(executable=missing))
        item = self.items(manifest)["hover-car"]
        self.assertTrue(item["placeholder"])
        self.assertEqual(item["files"][0]["path"],
                         "public/assets/models/hover-car.placeholder.glb")
        self.assertIn(("model-spec-unbuilt", "warning"), self.codes(manifest, "hover-car"))
        result, _ = self.run_step(design, placeholders=self.blender_settings(
            executable=missing, required=True), strict=True)
        self.assertEqual(result.outcome, "FAILED")
        self.assertIn("model-spec-unbuilt", result.error)

    def test_a_failed_build_falls_back_and_says_why(self):
        broken = FakeBlender(os.path.join(self.tools), mode="fail")
        manifest = self.manifest(self.models_design(),
                                 placeholders=self.blender_settings(executable=broken.path))
        issues = {i["code"]: i for i in manifest["issues"] if i.get("item_id") == "hover-car"}
        self.assertIn("exporter exploded", issues["generation-failed"]["message"])
        self.assertIn("its build failed", issues["model-spec-unbuilt"]["message"])
        self.assertTrue(self.items(manifest)["hover-car"]["placeholder"])

    def test_another_blender_series_is_refused_unless_allowed(self):
        other = FakeBlender(os.path.join(self.tools), "Blender 5.0.1")
        manifest = self.manifest(self.models_design(),
                                 placeholders=self.blender_settings(executable=other.path))
        self.assertIn(("model-spec-unbuilt", "warning"), self.codes(manifest, "hover-car"))
        self.assertIn("not the pinned series",
                      {b["id"]: b for b in manifest["generation"]["backends"]}["blender"]["note"])
        manifest = self.manifest(self.models_design(), placeholders=self.blender_settings(
            executable=other.path, allow_unpinned=True))
        generation = self.items(manifest)["hover-car"]["model"]["generation"]
        self.assertEqual((generation["version"], generation["pinned"]), ("5.0.1", False))

    def test_a_purchased_model_gets_a_built_stand_in_not_a_final_file(self):
        design = self.models_design(**{"hover-car": {"source": "purchased"}})
        manifest = self.manifest(design, placeholders=self.blender_settings())
        item = self.items(manifest)["hover-car"]
        self.assertEqual((item["status"], item["placeholder"]), ("in-progress", True))
        self.assertTrue(item["files"][0]["path"].endswith("hover-car.placeholder.glb"))
        self.assertIn(("placeholder", "info"), self.codes(manifest, "hover-car"))

    def test_blender_joins_only_when_a_design_describes_a_model(self):
        manifest = self.manifest(self.design("design-3d.json"))
        self.assertNotIn("blender", [b["id"] for b in manifest["generation"]["backends"]])
        manifest = self.manifest(self.models_design(), placeholders=self.blender_settings())
        self.assertEqual(manifest["generation"]["backends"][0]["id"], "blender")

    def test_an_existing_model_is_held_to_what_the_spec_declares(self):
        design = self.design("design-3d.json", requirements=[
            {"id": "barrel", "kind": "model", "existing": {
                "path": "public/assets/models/barrel.glb", "license": "CC0-1.0",
                "source_url": "https://example.invalid/barrel"},
             "model": {"animations": [{"name": "roll"}], "collision": {"shape": "box"}}}])
        manifest = self.manifest(design)
        item = self.items(manifest)["barrel"]
        self.assertIn(("animation-missing", "error"), self.codes(manifest, "barrel"))
        self.assertIn(("collision-missing", "error"), self.codes(manifest, "barrel"))
        self.assertEqual(item["status"], "sourced")
        self.assertFalse(item["production_ready"])

    def test_a_broken_existing_glb_is_reported_in_detail(self):
        os.makedirs(os.path.join(self.root, "public/assets/models"), exist_ok=True)
        with open(os.path.join(self.root, "public/assets/models/odd.glb"), "wb") as handle:
            handle.write(edit(box(), lambda d: d["nodes"][0].update(scale=[0, 1, 1])))
        design = self.design("design-3d.json", requirements=[
            {"id": "odd", "kind": "model", "existing": {
                "path": "public/assets/models/odd.glb", "license": "CC0-1.0",
                "source_url": "https://example.invalid/odd"}}])
        manifest = self.manifest(design)
        self.assertIn(("model-transform", "error"), self.codes(manifest, "odd"))
        self.assertFalse(self.items(manifest)["odd"]["production_ready"])

    def test_the_manifest_validates_under_ajv(self):
        if not enabled("WGF_AJV"):
            self.skipTest("WGF_AJV=1 runs ajv (needs npx)")
        manifest = self.manifest(self.models_design(), placeholders=self.blender_settings())
        for artifact_type, content in (("asset-manifest", manifest),
                                       ("game-design", self.models_design())):
            path = os.path.join(self.scratch, f"{artifact_type}.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(content, handle)
            ajv(artifact_type, path, self)


# -- the runtime: the template's own three.js -----------------------------------------------

class Runtime(unittest.TestCase):
    def probe(self, files):
        results, reason = threejs_runtime.probe(files)
        if results is None:
            self.skipTest(reason)
        for result in results:
            self.assertTrue(result["ok"], result.get("error"))
        return results

    def test_procedural_placeholders_load_and_animate_in_threejs(self):
        scratch = tempfile.mkdtemp(prefix="wgf-runtime-")
        self.addCleanup(shutil.rmtree, scratch, ignore_errors=True)
        files = []
        for name, kwargs in (("model", {}), ("environment", {"shape": "environment"}),
                             ("animation", {"animated": True})):
            path = os.path.join(scratch, f"{name}.glb")
            with open(path, "wb") as handle:
                handle.write(blender.stamp(box(**kwargs), {"key": "sha256:" + "0" * 64}))
            files.append(path)
        results = self.probe(files)
        for path, result in zip(files, results):
            summary = gltf.inspect(read_bytes(path), kind="environment").summary
            self.assertEqual(result["triangles"], summary["triangles"])
            for got, want in zip(result["dimensions"], summary["dimensions"]):
                self.assertAlmostEqual(got, want, places=4)
        self.assertEqual(results[2]["clips"][0]["name"], "box")
        self.assertTrue(results[2]["clips"][0]["moved"])

    def test_the_committed_blender_fixture_loads_as_a_game_would(self):
        path = os.path.join(MODELS, "hover-car.glb")
        result = self.probe([path])[0]
        summary = gltf.inspect(read_bytes(path)).summary
        self.assertEqual(result["root"], "hover-car")
        self.assertEqual(result["root_user_data"]["wgf_asset"], "hover-car")
        self.assertEqual(result["triangles"], summary["triangles"])
        self.assertEqual(result["materials"], ["MeshStandardMaterial"])
        self.assertGreaterEqual(result["textured"], 1)
        # Clip order is the exporter's; a game looks clips up by name.
        self.assertEqual(sorted((c["name"], c["resolved"], c["moved"]) for c in result["clips"]),
                         [("hover", True, True), ("spin", True, True)])
        proxy = result["collision"][0]
        self.assertEqual((proxy["name"], proxy["userData"]["wgf_shape"]),
                         ("hover-car_collision", "box"))
        self.assertAlmostEqual(result["min_y"], 0.0, places=5)


# -- real Blender ---------------------------------------------------------------------------

def _real_blender():
    if not enabled("WGF_BLENDER_TEST"):
        return None, "WGF_BLENDER_TEST=1 runs the real Blender builds"
    info = blender.discover()
    pin = load_policy().toolchains["blender"]
    if info.version is None:
        return None, blender.missing_message(info, pin)
    refusal = blender.check_pin(info, pin)
    if refusal:
        return None, refusal
    return info, None


class RealBlender(AssetsCase):
    @classmethod
    def setUpClass(cls):
        cls.info, reason = _real_blender()
        if cls.info is None:
            raise unittest.SkipTest(reason)

    def build(self, spec, asset_id, kind="model"):
        data, report, key = blender.build_model(self.info, spec, asset_id)
        inspection = gltf.inspect(data, name=asset_id, kind=kind)
        expect = modelspec.expectations(spec, load_policy().kind(kind))
        findings = inspection.findings + gltf.check_expectations(inspection.summary, expect,
                                                                  data, name=asset_id)
        self.assertEqual(findings, [])
        self.assertTrue(report["ok"])
        self.assertEqual(blender.read_stamp(data)["key"], key)
        return data, inspection.summary
    def test_the_committed_fixture_is_rebuilt_byte_for_byte(self):
        spec = model_fixture("design-models.json")["asset_requirements"][0]["model"]
        data, _summary = self.build(spec, "hover-car")
        with open(os.path.join(MODELS, "hover-car.glb"), "rb") as handle:
            committed = handle.read()
        self.assertEqual(data, committed, textwrap.dedent("""
            A build of the fixture spec no longer reproduces fixtures/models/hover-car.glb.
            If the build script or the spec changed on purpose, rebuild the fixture with the
            pinned Blender:
              python3 scripts/wgf-model.py build <the spec> --id hover-car \\
                -o scripts/tests/fixtures/models/hover-car.glb
            (the spec is asset_requirements[0].model of fixtures/models/design-models.json).
            Otherwise the output is not reproducible on this machine."""))

    def test_every_shape_every_track_and_the_fit(self):
        spec = {
            "fit": {"size": 3, "axis": "x"}, "pivot": "center",
            "parts": [
                {"id": "a", "shape": "box", "material": "m"},
                {"id": "b", "shape": "cylinder", "position": [1.2, 0, 0], "material": "m"},
                {"id": "c", "shape": "cone", "position": [2.4, 0, 0], "segments": 8},
                {"id": "d", "shape": "sphere", "position": [0, 1.2, 0], "parent": "a",
                 "material": "glass"},
                {"id": "e", "shape": "icosphere", "position": [1.2, 1.2, 0], "segments": 32},
                {"id": "f", "shape": "plane", "size": [3, 0, 1], "position": [1.2, -0.6, 0]},
            ],
            "materials": [{"id": "m", "color": "#3366ff", "metallic": 0.5, "roughness": 0.3,
                           "emissive": "#110000", "emissive_strength": 3},
                          {"id": "glass", "color": "#ffffff", "opacity": 0.4,
                           "texture": {"pattern": "stripes", "size": 32, "repeat": 4}}],
            "animations": [
                {"name": "walk", "duration": 1, "tracks": [
                    {"part": "a", "path": "translation", "keys": [
                        {"t": 0, "value": [0, 0, 0]}, {"t": 1, "value": [0, 0, 1]}]},
                    {"part": "d", "path": "scale", "keys": [
                        {"t": 0, "value": [1, 1, 1]}, {"t": 0.5, "value": [1.5, 1.5, 1.5]},
                        {"t": 1, "value": [1, 1, 1]}]}]},
                {"name": "blink", "duration": 0.5, "interpolation": "step", "tracks": [
                    {"part": "e", "path": "rotation", "keys": [
                        {"t": 0, "value": [0, 0, 0]}, {"t": 0.25, "value": [0, 90, 0]}]}]},
            ],
            "collision": {"shape": "box"},
        }
        data, summary = self.build(spec, "kit")
        self.assertAlmostEqual(summary["dimensions"][0], 3.0, places=3)
        centre = [(a + b) / 2 for a, b in zip(summary["bounds"]["min"], summary["bounds"]["max"])]
        for value in centre:
            self.assertAlmostEqual(value, 0.0, places=3)
        self.assertEqual({c["name"]: c["duration"] for c in summary["animations"]},
                         {"walk": 1.0, "blink": 0.5})
        document, _ = gltf.load(data)
        blink = next(a for a in document["animations"] if a["name"] == "blink")
        self.assertEqual({s["interpolation"] for s in blink["samplers"]}, {"STEP"})
        # #110000 x 3 stays under 1 in linear light, so the exporter folds the strength into
        # emissiveFactor instead of reaching for KHR_materials_emissive_strength.
        metal = next(m for m in document["materials"] if m["name"] == "m")
        self.assertGreater(metal["emissiveFactor"][0], 0)
        self.assertEqual(metal["pbrMetallicRoughness"]["metallicFactor"], 0.5)
        glass = next(m for m in document["materials"] if m["name"] == "glass")
        self.assertEqual(glass.get("alphaMode"), "BLEND")
        self.assertEqual(blender.build_model(self.info, spec, "kit")[0], data)

    def test_lods_and_a_convex_proxy_are_deterministic_and_light(self):
        spec = {"parts": [
            {"id": "core", "shape": "icosphere", "size": [1, 0.8, 1.2], "segments": 32,
             "material": "stone"},
            {"id": "cap", "shape": "sphere", "size": [0.6, 0.4, 0.6], "position": [0.2, 0.4, 0],
             "segments": 24, "material": "stone"}],
            "materials": [{"id": "stone", "color": "#888877",
                           "texture": {"pattern": "checker", "size": 128, "repeat": 3}}],
            "fit": {"size": 1.5}, "lods": [0.5, 0.2], "collision": {"shape": "convex"}}
        data, summary = self.build(spec, "rock")
        levels = {l["level"]: l["triangles"] for l in summary["lods"]}
        self.assertLessEqual(levels[1], summary["triangles"] * 0.5)
        self.assertLessEqual(levels[2], summary["triangles"] * 0.2)
        self.assertGreater(levels[2], 0)
        self.assertLessEqual(summary["collision"]["triangles"], gltf.MAX_COLLISION_TRIANGLES)
        for _ in range(2):
            self.assertEqual(blender.build_model(self.info, spec, "rock")[0], data)

    def test_the_step_builds_then_reuses(self):
        settings = {"backends": ["procedural"],
                    "blender": {"executable": self.info.executable, "required": True}}
        manifest = self.manifest(models_design(), placeholders=settings, strict=True)
        item = self.items(manifest)["hover-car"]
        self.assertTrue(item["production_ready"])
        self.assertFalse(item["model"]["generation"]["reused"])
        self.assertEqual(ArtifactContracts().problems("asset-manifest", manifest), [])
        with open(os.path.join(MODELS, "hover-car.glb"), "rb") as handle:
            self.assertEqual(self.read(item["files"][0]["path"]), handle.read())
        again = self.manifest(models_design(), placeholders=settings, strict=True)
        self.assertTrue(self.items(again)["hover-car"]["model"]["generation"]["reused"])
        self.assertEqual(again["runtime_manifest"], manifest["runtime_manifest"])

if __name__ == "__main__":
    unittest.main()

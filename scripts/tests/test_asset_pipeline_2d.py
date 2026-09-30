"""The 2D asset pipeline: PNG codec, atlas packing, the runtime manifest and its validator,
the `wgf-assets.py` CLI, and how the assets, develop and verify steps use them.

Deterministic and offline, standard library only - like the pipeline itself.

    python -m unittest scripts.tests.test_asset_pipeline_2d
"""

import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, HERE)

import test_assets as base  # noqa: E402
from wgf_assets import atlas, encoders, formats, raster, runtime  # noqa: E402
from wgf_assets.pipeline import AssetPipeline, AssetStore  # noqa: E402
from wgf_assets.placeholders import build_backends  # noqa: E402
from wgf_assets.policy import load_policy  # noqa: E402
from wgf_assets.requirements import RequirementError, inspect  # noqa: E402
from wgflib import jsonschema_lite as js  # noqa: E402

CLI = os.path.join(SCRIPTS, "wgf-assets.py")


# -- PNG construction helpers --------------------------------------------------------------

def _chunk(kind, body):
    return (struct.pack(">I", len(body)) + kind + body
            + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF))


def _paeth(a, b, c):
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    return a if pa <= pb and pa <= pc else (b if pb <= pc else c)


def _filter(line, previous, method, bpp):
    out = bytearray()
    for i, value in enumerate(line):
        left = line[i - bpp] if i >= bpp else 0
        up = previous[i]
        upper_left = previous[i - bpp] if i >= bpp else 0
        predictor = {0: 0, 1: left, 2: up, 3: (left + up) >> 1,
                     4: _paeth(left, up, upper_left)}[method]
        out.append((value - predictor) & 0xFF)
    return bytes(out)


def make_png(width, height, rows, *, colour=6, depth=8, plte=None, trns=None, methods=(0,),
             interlace=0):
    """PNG bytes from raw scanline bytes (unfiltered), filtering row i with methods[i % n]."""
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[colour]
    bpp = max(1, channels * depth // 8)
    stride = (width * channels * depth + 7) // 8
    raw, previous = bytearray(), bytes(stride)
    for index, line in enumerate(rows):
        method = methods[index % len(methods)]
        raw.append(method)
        raw += _filter(line, previous, method, bpp)
        previous = line
    body = _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, depth, colour, 0, 0,
                                       interlace))
    if plte:
        body += _chunk(b"PLTE", plte)
    if trns is not None:
        body += _chunk(b"tRNS", trns)
    return (raster.PNG_SIGNATURE + body + _chunk(b"IDAT", zlib.compress(bytes(raw)))
            + _chunk(b"IEND", b""))


def solid(width, height, rgba):
    return raster.Image(width, height, bytes(rgba) * (width * height))


def pixel(image, x, y):
    o = (y * image.width + x) * 4
    return tuple(image.pixels[o:o + 4])


# -- raster ----------------------------------------------------------------------------------

class Raster(unittest.TestCase):
    def test_rgba_round_trips_and_encoding_is_deterministic(self):
        image = raster.Image(3, 2, bytes(range(24)))
        data = raster.encode_png(image)
        self.assertEqual(raster.decode_png(data).pixels, image.pixels)
        self.assertEqual(raster.encode_png(image), data)
        self.assertEqual(formats.sniff(data), formats.Detected("png", 3, 2))

    def test_every_filter_decodes(self):
        rows = [bytes((x * 7 + y * 31) & 0xFF for x in range(4 * 5)) for y in range(6)]
        expected = b"".join(rows)
        for method in range(5):
            with self.subTest(filter=method):
                data = make_png(5, 6, rows, methods=(method,))
                self.assertEqual(bytes(raster.decode_png(data).pixels), expected)
        mixed = make_png(5, 6, rows, methods=(0, 1, 2, 3, 4))
        self.assertEqual(bytes(raster.decode_png(mixed).pixels), expected)

    def test_palette_with_transparency(self):
        plte = bytes((255, 0, 0, 0, 255, 0))
        data = make_png(2, 1, [bytes((0, 1))], colour=3, plte=plte, trns=bytes((0,)))
        image = raster.decode_png(data)
        self.assertEqual(pixel(image, 0, 0), (255, 0, 0, 0))
        self.assertEqual(pixel(image, 1, 0), (0, 255, 0, 255))
        self.assertTrue(raster.png_header(data).has_alpha)

    def test_low_bit_depth_grey_and_grey_alpha_and_rgb(self):
        grey = make_png(4, 1, [bytes((0b00011011,))], colour=0, depth=2)
        self.assertEqual([pixel(raster.decode_png(grey), x, 0)[0] for x in range(4)],
                         [0, 85, 170, 255])
        self.assertFalse(raster.png_header(grey).has_alpha)
        grey_alpha = make_png(1, 1, [bytes((10, 20))], colour=4)
        self.assertEqual(pixel(raster.decode_png(grey_alpha), 0, 0), (10, 10, 10, 20))
        keyed = make_png(2, 1, [bytes((1, 2, 3, 4, 5, 6))], colour=2,
                         trns=struct.pack(">HHH", 1, 2, 3))
        image = raster.decode_png(keyed)
        self.assertEqual(pixel(image, 0, 0), (1, 2, 3, 0))
        self.assertEqual(pixel(image, 1, 0), (4, 5, 6, 255))

    def test_sixteen_bit_keeps_the_high_byte(self):
        data = make_png(1, 1, [bytes((0x12, 0x34, 0x56, 0x78, 0x9A, 0xBC, 0xDE, 0xF0))],
                        colour=6, depth=16)
        self.assertEqual(pixel(raster.decode_png(data), 0, 0), (0x12, 0x56, 0x9A, 0xDE))

    def test_interlaced_and_truncated_are_refused_with_a_fix(self):
        interlaced = make_png(1, 1, [bytes(4)], interlace=1)
        with self.assertRaisesRegex(raster.RasterError, "re-save it without interlacing"):
            raster.decode_png(interlaced)
        good = raster.encode_png(solid(4, 4, (1, 2, 3, 4)))
        with self.assertRaisesRegex(raster.RasterError, "truncated"):
            raster.decode_png(good[:40])
        with self.assertRaises(raster.RasterError):
            raster.decode_png(b"GIF89a....")

    def test_alpha_bounds(self):
        image = solid(8, 8, (0, 0, 0, 0))
        self.assertIsNone(raster.alpha_bounds(image))
        for x, y in ((2, 3), (5, 6)):
            o = (y * 8 + x) * 4
            image.pixels[o:o + 4] = bytes((9, 9, 9, 255))
        self.assertEqual(raster.alpha_bounds(image), (2, 3, 4, 4))


# -- atlas packing -----------------------------------------------------------------------------

def _sprites():
    colours = [(200, 0, 0, 255), (0, 200, 0, 255), (0, 0, 200, 255), (200, 200, 0, 255),
               (0, 200, 200, 255)]
    sizes = [(30, 20), (16, 16), (40, 12), (8, 30), (16, 16)]
    return [(f"frame-{i}", solid(w, h, c))
            for i, ((w, h), c) in enumerate(zip(sizes, colours))]


class Packing(unittest.TestCase):
    def test_frames_fit_do_not_overlap_and_carry_their_pixels(self):
        sprites = _sprites()
        image, frames = atlas.pack(sprites)
        self.assertTrue(formats.is_power_of_two(image.width))
        self.assertTrue(formats.is_power_of_two(image.height))
        rects = []
        for name, source in sprites:
            rect = frames[name]["frame"]
            self.assertEqual((rect["w"], rect["h"]), (source.width, source.height))
            self.assertLessEqual(rect["x"] + rect["w"], image.width)
            self.assertLessEqual(rect["y"] + rect["h"], image.height)
            self.assertEqual(image.crop(rect["x"], rect["y"], rect["w"], rect["h"]).pixels,
                             source.pixels)
            rects.append((rect["x"], rect["y"], rect["x"] + rect["w"], rect["y"] + rect["h"]))
        for i, a in enumerate(rects):
            for b in rects[i + 1:]:
                self.assertFalse(a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3],
                                 f"{a} overlaps {b}")
        self.assertEqual(check_problems(frames, image), [])

    def test_input_order_does_not_change_a_byte(self):
        sprites = _sprites()
        first = atlas.pack(sprites)
        second = atlas.pack(list(reversed(sprites)))
        self.assertEqual(first[0].pixels, second[0].pixels)
        self.assertEqual(first[1], second[1])
        doc = atlas.atlas_document(first[1], "a.png", (first[0].width, first[0].height))
        self.assertEqual(doc, atlas.atlas_document(second[1], "a.png",
                                                   (second[0].width, second[0].height)))
        self.assertNotIn(b"time", doc.lower().replace(b"runtime", b""))

    def test_extrusion_repeats_edge_pixels(self):
        image, frames = atlas.pack([("a", solid(4, 4, (10, 20, 30, 255)))],
                                   {"extrude": 2, "padding": 0})
        rect = frames["a"]["frame"]
        self.assertEqual((rect["x"], rect["y"]), (2, 2))
        self.assertEqual(pixel(image, 0, 0), (10, 20, 30, 255))
        self.assertEqual(pixel(image, rect["x"] + 5, rect["y"] + 5), (10, 20, 30, 255))

    def test_trim_records_the_source_offset(self):
        sprite = solid(10, 10, (0, 0, 0, 0))
        for y in range(3, 6):
            for x in range(2, 8):
                o = (y * 10 + x) * 4
                sprite.pixels[o:o + 4] = bytes((1, 1, 1, 255))
        _image, frames = atlas.pack([("t", sprite)], {"trim": True})
        record = frames["t"]
        self.assertTrue(record["trimmed"])
        self.assertEqual(record["spriteSourceSize"], {"x": 2, "y": 3, "w": 6, "h": 3})
        self.assertEqual(record["sourceSize"], {"w": 10, "h": 10})

    def test_overflow_and_duplicates_fail_with_what_to_do(self):
        with self.assertRaisesRegex(atlas.AtlasError, "split the group"):
            atlas.pack([(f"s{i}", solid(64, 64, (1, 1, 1, 255))) for i in range(5)],
                       {"max_size": 128})
        with self.assertRaisesRegex(atlas.AtlasError, "duplicate frame name"):
            atlas.pack([("a", solid(1, 1, (0, 0, 0, 0))), ("a", solid(1, 1, (0, 0, 0, 0)))])
        with self.assertRaisesRegex(atlas.AtlasError, "non-negative"):
            atlas.pack(_sprites(), {"padding": -1})

    def test_non_power_of_two_packs_tighter(self):
        image, _ = atlas.pack(_sprites(), {"power_of_two": False})
        pot, _ = atlas.pack(_sprites())
        self.assertLessEqual(image.width * image.height, pot.width * pot.height)

    def test_natural_frame_order(self):
        self.assertEqual(atlas.frame_order(["run-10", "run-2", "run-1"]),
                         ["run-1", "run-2", "run-10"])


def check_problems(frames, image):
    return atlas.check_document({"frames": frames}, (image.width, image.height))


class AtlasDocuments(unittest.TestCase):
    def frame(self, x, y, w, h):
        return {"frame": {"x": x, "y": y, "w": w, "h": h}}

    def test_out_of_bounds_missing_animation_frames_and_size_mismatch(self):
        document = {"frames": {"a": self.frame(0, 0, 8, 8), "b": self.frame(6, 0, 4, 4)},
                    "animations": {"walk": ["a", "c"]},
                    "meta": {"size": {"w": 16, "h": 16}}}
        problems = atlas.check_document(document, (8, 8))
        joined = " | ".join(problems)
        self.assertIn("meta.size 16x16 does not match", joined)
        self.assertIn("frame 'b'", joined)
        self.assertIn("animation 'walk' names missing frame(s): c", joined)
        self.assertNotIn("frame 'a'", joined)

    def test_empty_and_malformed(self):
        self.assertIn("no frames", atlas.check_document({"meta": {}})[0])
        self.assertIn("no frames", atlas.check_document({"frames": {}})[0])
        self.assertIn("no valid frame", atlas.check_document(
            {"frames": {"a": {"frame": {"x": 0, "y": 0, "w": 0, "h": 4}}}})[0])

    def test_json_array_shape_is_read(self):
        document = {"frames": [dict(self.frame(0, 0, 2, 2), filename="x"),
                               dict(self.frame(2, 0, 2, 2), filename="x")]}
        self.assertIn("listed twice", atlas.check_document(document, (4, 2))[0])
        self.assertEqual(atlas.frames_of(document), ["x", "x"])

    def test_placeholder_sheets_are_valid_atlases(self):
        doc = json.loads(encoders.atlas_json("s.png", 8, 8, 12, "s"))
        self.assertEqual(atlas.check_document(doc, (96, 8)), [])
        self.assertEqual(atlas.frames_of(doc)[-3:], ["s-9", "s-10", "s-11"])


# -- formats -------------------------------------------------------------------------------

class Formats(unittest.TestCase):
    def test_avif_is_not_mistaken_for_m4a(self):
        avif = (struct.pack(">I", 28) + b"ftypavif" + b"\x00\x00\x00\x00" + b"avifmif1miaf"
                + struct.pack(">I", 20) + b"ispe" + b"\x00" * 4 + struct.pack(">II", 64, 32))
        self.assertEqual(formats.sniff(avif), formats.Detected("avif", 64, 32))
        m4a = struct.pack(">I", 24) + b"ftypM4A " + b"\x00" * 12
        self.assertEqual(formats.sniff(m4a).format, "m4a")

    def test_svg_size_from_attributes_or_viewbox(self):
        self.assertEqual(formats.sniff(b'<svg width="24px" height="12"></svg>'),
                         formats.Detected("svg", 24, 12))
        self.assertEqual(formats.sniff(b'<svg viewBox="0 0 48 16"></svg>'),
                         formats.Detected("svg", 48, 16))
        self.assertEqual(formats.sniff(b'<svg width="50%"></svg>'),
                         formats.Detected("svg", None, None))

    def test_svg_hazards(self):
        clean = (b'<svg xmlns="http://www.w3.org/2000/svg"><defs><linearGradient id="g"/>'
                 b'</defs><rect fill="url(#g)"/><use href="#g"/>'
                 b'<image href="data:image/png;base64,AA"/></svg>')
        self.assertEqual(formats.svg_hazards(clean), [])
        for snippet, expected in (
                (b"<script>alert(1)</script>", "script"),
                (b'<rect onclick="x()"/>', "event-handler"),
                (b'<a href="javascript:x()"/>', "javascript:"),
                (b"<foreignObject/>", "foreignObject"),
                (b'<!DOCTYPE svg [<!ENTITY x "y">]>', "DOCTYPE"),
                (b'<image xlink:href="https://cdn.example/x.png"/>', "href to another file"),
                (b'<image href="sprite.png"/>', "href to another file"),
                (b"<style>@import 'x.css';</style>", "@import"),
                (b'<rect style="fill:url(/x.svg#a)"/>', "url() reference")):
            with self.subTest(expected):
                hazards = formats.svg_hazards(b"<svg>" + snippet + b"</svg>")
                self.assertTrue(any(expected in h for h in hazards), hazards)


# -- requirements ----------------------------------------------------------------------------

class Requirements2D(base.AssetsCase):
    def refused(self, requirements, pattern):
        with self.assertRaisesRegex(RequirementError, pattern):
            inspect(self.design(requirements=requirements), self.policy)

    def test_new_fields_are_validated(self):
        self.refused([{"id": "bg", "kind": "background", "atlas": "hud"}],
                     "a background cannot join an atlas")
        self.refused([{"id": "a", "kind": "sprite", "atlas": "Bad Group"}], "kebab-case")
        self.refused([{"id": "a", "kind": "sprite", "scale": 5}], "scale must be")
        self.refused([{"id": "a", "kind": "sprite", "width": 2048, "scale": 3}],
                     "exceeds 4096")
        self.refused([{"id": "a", "kind": "sprite", "animations": {"x": {}}}],
                     "spritesheet only")
        self.refused([{"id": "s", "kind": "spritesheet", "frames": 4,
                       "animations": {"run": {"frames": [0, 4]}}}], "beyond the sheet")
        self.refused([{"id": "s", "kind": "spritesheet",
                       "animations": {"run": {"fps": 0}}}], "fps must be")
        self.refused([{"id": "s", "kind": "spritesheet",
                       "animations": {"run": {"loop": "yes"}}}], "loop must be")
        self.refused([{"id": "t", "kind": "tileset", "width": 100, "tile_width": 32}],
                     "does not divide")
        self.refused([{"id": "a", "kind": "sprite", "tile_width": 16}], "tileset only")

    def test_scale_multiplies_pixels_and_animation_specs_resolve(self):
        reqs, _ = inspect(self.design(requirements=[
            {"id": "s", "kind": "spritesheet", "frames": 3, "width": 10, "height": 20,
             "scale": 2, "animations": {"a": {"frames": [2, "s-0"], "fps": 8, "loop": False}}}]),
            self.policy)
        req = reqs[0]
        self.assertEqual(req.pixel_size(), (20, 40))
        self.assertEqual(req.animation_specs(["s-0", "s-1", "s-2"]),
                         {"a": {"frames": ["s-2", "s-0"], "fps": 8, "loop": False}})


# -- the pipeline, through the step ------------------------------------------------------------

REQUIREMENTS = [
    {"id": "background-main", "kind": "background", "source": "procedural"},
    {"id": "coin", "kind": "sprite", "atlas": "hud", "width": 32, "height": 32,
     "source": "procedural"},
    {"id": "button-play", "kind": "ui", "atlas": "hud", "width": 96, "height": 40,
     "source": "procedural"},
    {"id": "star", "kind": "icon", "atlas": "hud", "width": 24, "height": 24,
     "source": "procedural"},
    {"id": "hero-run", "kind": "spritesheet", "frames": 6, "width": 24, "height": 24,
     "scale": 2, "source": "procedural",
     "animations": {"run": {"frames": [0, 1, 2, 3], "fps": 10},
                    "idle": {"frames": [4, 5], "loop": False}}},
    {"id": "grass", "kind": "tileset", "width": 128, "height": 64, "tile_width": 16,
     "tile_height": 16, "source": "procedural"},
    {"id": "tap", "kind": "sfx", "source": "procedural"},
    {"id": "font-main", "kind": "font", "source": "procedural"},
]


def _registry():
    registry = js.Registry()
    registry.add_directory(os.path.join(ROOT, "core", "artifacts"))
    return registry


class EmptyCheckout(base.AssetsCase):
    """A game checkout with nothing in public/assets yet."""

    def setUp(self):
        super().setUp()
        self.root = os.path.join(self.scratch, "game")
        os.makedirs(self.root)


class Pipeline2D(EmptyCheckout):
    def build(self, requirements=REQUIREMENTS, **params):
        return self.manifest(self.design(requirements=requirements), **params)

    def runtime_doc(self):
        return json.loads(self.read(runtime.RUNTIME_PATH))

    def test_atlas_groups_are_packed_and_their_sources_kept_out_of_public(self):
        manifest = self.build()
        items = self.items(manifest)
        for member in ("coin", "button-play", "star"):
            item = items[member]
            self.assertEqual(item["atlas"], {"id": "hud", "frame": member})
            self.assertTrue(item["files"][0]["path"].startswith("src/assets/"), item["files"])
            self.assertIn("texture-atlas", item["optimization"]["applied"])
            self.assertNotIn("texture-atlas", item["optimization"]["deferred"])
        self.assertEqual([a["id"] for a in manifest["atlases"]], ["hud"])
        self.assertEqual(manifest["atlases"][0]["members"], ["button-play", "coin", "star"])
        png, document = (self.read(f["path"]) for f in manifest["atlases"][0]["files"])
        image = raster.decode_png(png)
        parsed = json.loads(document)
        self.assertEqual(parsed["meta"]["image"], "hud.png")
        self.assertEqual(parsed["meta"]["app"], "wgf-assets")
        self.assertEqual(atlas.check_document(parsed, (image.width, image.height)), [])
        coin = raster.decode_png(self.read(items["coin"]["files"][0]["path"]))
        rect = parsed["frames"]["coin"]["frame"]
        self.assertEqual(image.crop(rect["x"], rect["y"], rect["w"], rect["h"]).pixels,
                         coin.pixels)

    def test_the_runtime_manifest_describes_every_loadable_asset(self):
        manifest = self.build()
        doc = self.runtime_doc()
        self.assertEqual(manifest["runtime_manifest"]["path"], runtime.RUNTIME_PATH)
        self.assertEqual(manifest["runtime_manifest"]["content_hash"],
                         "sha256:" + hashlib.sha256(self.read(runtime.RUNTIME_PATH)).hexdigest())
        self.assertEqual(list(js.Validator(runtime.load_schema()).iter_errors(doc)), [])
        assets = doc["assets"]
        self.assertEqual(sorted(assets), sorted(r["id"] for r in REQUIREMENTS))
        self.assertEqual(assets["coin"], {"atlas": "hud", "frame": "coin", "width": 32,
                                          "height": 32, "placeholder": True,
                                          "type": "sprite"})
        sheet = assets["hero-run"]
        self.assertEqual((sheet["width"], sheet["height"], sheet["scale"]), (288, 48, 2))
        self.assertEqual(sheet["frames"], [f"hero-run-{i}" for i in range(6)])
        self.assertEqual(sheet["animations"]["run"],
                         {"frames": ["hero-run-0", "hero-run-1", "hero-run-2", "hero-run-3"],
                          "fps": 10, "loop": True})
        self.assertEqual(sheet["animations"]["idle"]["loop"], False)
        self.assertEqual(sheet["data"], "sprites/hero-run.placeholder.atlas.json")
        grass = assets["grass"]
        self.assertEqual((grass["tile_width"], grass["columns"], grass["rows"]), (16, 8, 4))
        self.assertEqual(assets["font-main"]["type"], "font")
        self.assertIn("system-ui", assets["font-main"]["family"])
        self.assertEqual(doc["atlases"]["hud"]["frames"], ["button-play", "coin", "star"])
        for url in doc["files"]:
            self.assertFalse(url.startswith(("/", "..")), url)
        self.assertNotIn(self.root, self.read(runtime.RUNTIME_PATH).decode())
        # Bundle size counts what ships: the atlas, not its members' sources.
        self.assertEqual(runtime.validate(self.root), [])

    def test_the_same_design_gives_the_same_bytes_anywhere(self):
        self.build()
        first = {p: self.read(p) for p in (runtime.RUNTIME_PATH, "public/assets/atlases/hud.png",
                                           "public/assets/atlases/hud.json")}
        other = os.path.join(self.scratch, "elsewhere")
        os.makedirs(other)
        self.manifest(self.design(requirements=list(reversed(REQUIREMENTS))), root=other)
        for relative, data in first.items():
            with open(os.path.join(other, relative), "rb") as handle:
                self.assertEqual(handle.read(), data, relative)
        result, _ = self.run_step(self.design(requirements=REQUIREMENTS))
        self.assertEqual(result.artifacts[0].metadata["writes"]["created"], 0)
        self.assertEqual(result.artifacts[0].metadata["writes"]["updated"], 0)

    def test_stale_placeholders_and_atlases_are_pruned_and_nothing_else(self):
        self.build()
        keep = os.path.join(self.root, "public", "assets", "sprites", "hand-made.png")
        with open(keep, "wb") as handle:
            handle.write(raster.encode_png(solid(2, 2, (1, 2, 3, 255))))
        renamed = [dict(r, id="gem", atlas="pickups") if r["id"] == "coin" else r
                   for r in REQUIREMENTS]
        result, _ = self.run_step(self.design(requirements=renamed))
        self.assertEqual(result.outcome, "SUCCESS", result.error)
        self.assertGreaterEqual(result.artifacts[0].metadata["writes"]["removed"], 1)
        self.assertFalse(os.path.exists(os.path.join(self.root, "src/assets/sprites/"
                                                                "coin.placeholder.png")))
        self.assertTrue(os.path.exists(os.path.join(self.root, "src/assets/sprites/"
                                                               "gem.placeholder.png")))
        self.assertTrue(os.path.exists(os.path.join(self.root,
                                                    "public/assets/atlases/pickups.png")))
        self.assertTrue(os.path.exists(keep))
        self.assertEqual(sorted(self.runtime_doc()["atlases"]), ["hud", "pickups"])
        result, _ = self.run_step(self.design(requirements=renamed), prune=False)
        self.assertNotIn("removed", result.artifacts[0].metadata["writes"])

    @unittest.skipUnless(base.enabled("WGF_AJV"), "WGF_AJV=1 runs ajv (needs npx)")
    def test_ajv_agrees(self):
        manifest = self.build()
        path = os.path.join(self.scratch, "asset-manifest.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(manifest, handle)
        base.ajv("asset-manifest", path, self)
        done = subprocess.run(
            ["npx", "--yes", "-p", "ajv-cli@5", "-p", "ajv-formats@2", "ajv", "validate",
             "-s", "core/artifacts/shared/runtime-assets.schema.json", "-c", "ajv-formats",
             "--spec=draft2020", "--strict=false",
             "-d", os.path.join(self.root, *runtime.RUNTIME_PATH.split("/"))],
            cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)

    def test_the_manifest_matches_its_schema(self):
        manifest = self.build()
        schema = json.load(open(os.path.join(ROOT, "core", "artifacts",
                                             "asset-manifest.schema.json")))
        errors = list(js.Validator(schema, _registry()).iter_errors(manifest))
        self.assertEqual(errors, [])

    def test_an_atlas_that_cannot_fit_is_an_error_on_each_member(self):
        policy = load_policy()
        policy.atlas_options = dict(policy.atlas_options, max_size=64)
        reqs, _ = inspect(self.design(requirements=[
            {"id": f"big-{i}", "kind": "sprite", "atlas": "g", "width": 60, "height": 60}
            for i in range(3)]), policy)
        pipeline = AssetPipeline(policy, AssetStore(self.root),
                                 build_backends(["procedural"], {}))
        result = pipeline.run(reqs)
        overflow = [i for i in result.issues if i["code"] == "atlas-overflow"]
        self.assertEqual(sorted(i["item_id"] for i in overflow), ["big-0", "big-1", "big-2"])
        self.assertEqual(result.atlases, [])
        self.assertFalse(any(i.get("production_ready") for i in result.items))

    def test_mixed_scales_in_one_atlas_are_refused(self):
        manifest = self.build([
            {"id": "a", "kind": "sprite", "atlas": "g"},
            {"id": "b", "kind": "sprite", "atlas": "g", "scale": 2}])
        self.assertIn(("invalid-atlas", "error"), self.codes(manifest, "a"))
        self.assertNotIn("atlases", manifest)

    def write(self, relative, data):
        path = os.path.join(self.root, relative)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as handle:
            handle.write(data)

    def existing(self, **fields):
        return dict({"license": "CC0-1.0", "source_url": "https://example.test/pack"},
                    **fields)

    def test_an_existing_spritesheet_needs_a_matching_atlas(self):
        sheet = encoders.png(32, 8, (9, 9, 9), frames=4)
        self.write("public/assets/sprites/walk.png", sheet)
        manifest = self.build([{"id": "walk", "kind": "spritesheet",
                                "existing": self.existing(path="public/assets/sprites/walk.png")}],
                              placeholders={"enabled": False})
        self.assertIn(("invalid-atlas", "error"), self.codes(manifest, "walk"))

        self.write("public/assets/sprites/walk.atlas.json",
                   encoders.atlas_json("other.png", 8, 8, 4, "walk"))
        manifest = self.build([{"id": "walk", "kind": "spritesheet",
                                "existing": self.existing(path="public/assets/sprites/walk.png")}],
                              placeholders={"enabled": False})
        messages = [i["message"] for i in manifest["issues"] if i["code"] == "invalid-atlas"]
        self.assertTrue(any("meta.image is 'other.png'" in m for m in messages), messages)

        self.write("public/assets/sprites/walk.atlas.json",
                   encoders.atlas_json("walk.png", 8, 8, 4, "walk"))
        manifest = self.build([{"id": "walk", "kind": "spritesheet",
                                "existing": self.existing(path="public/assets/sprites/walk.png")}])
        item = self.items(manifest)["walk"]
        self.assertEqual(item["status"], "delivered")
        self.assertEqual([f["path"] for f in item["files"]],
                         ["public/assets/sprites/walk.png",
                          "public/assets/sprites/walk.atlas.json"])
        self.assertEqual(self.runtime_doc()["assets"]["walk"]["frames"],
                         [f"walk-{i}" for i in range(4)])
        self.assertEqual(runtime.validate(self.root), [])

    def test_a_library_sheet_is_renamed_with_its_atlas_image(self):
        manifest = self.manifest(self.design(), libraries=[base.LIBRARY])
        item = self.items(manifest)["player-run"]
        atlas_path = item["files"][1]["path"]
        document = json.loads(self.read(atlas_path))
        self.assertEqual(document["meta"]["image"], item["files"][0]["path"].rsplit("/", 1)[1])
        self.assertEqual([i for i in runtime.validate(self.root) if i["severity"] == "error"],
                         [])

    def test_unsafe_svg_transparency_and_duplicate_paths(self):
        self.write("public/assets/icons/bad.svg",
                   b'<svg width="16" height="16"><script>x()</script></svg>')
        self.write("public/assets/sprites/photo.jpg",
                   b"\xff\xd8\xff\xc0\x00\x11\x08\x00\x10\x00\x10\x03" + b"\x00" * 16)
        self.write("public/assets/backgrounds/sky-alpha.png",
                   raster.encode_png(solid(4, 4, (0, 0, 0, 255))))
        manifest = self.build([
            {"id": "bad", "kind": "icon",
             "existing": self.existing(path="public/assets/icons/bad.svg")},
            {"id": "photo", "kind": "sprite",
             "existing": self.existing(path="public/assets/sprites/photo.jpg")},
            {"id": "sky", "kind": "background",
             "existing": self.existing(path="public/assets/backgrounds/sky-alpha.png")},
            {"id": "sky-copy", "kind": "background",
             "existing": self.existing(path="public/assets/backgrounds/sky-alpha.png")}])
        self.assertIn(("unsafe-svg", "error"), self.codes(manifest, "bad"))
        self.assertFalse(self.items(manifest)["bad"].get("production_ready"))
        self.assertIn(("transparency-mismatch", "warning"), self.codes(manifest, "photo"))
        self.assertIn(("transparency-mismatch", "info"), self.codes(manifest, "sky"))
        self.assertIn(("duplicate-path", "error"), self.codes(manifest, "sky-copy"))

    def test_oversized_textures_and_wrong_dimensions(self):
        self.write("public/assets/backgrounds/huge.png",
                   encoders.png(2100, 8, (1, 1, 1), border=False))
        self.write("public/assets/tilesets/odd.png", encoders.png(40, 32, (1, 1, 1)))
        manifest = self.build([
            {"id": "huge", "kind": "background", "width": 1024, "height": 8,
             "existing": self.existing(path="public/assets/backgrounds/huge.png")},
            {"id": "odd", "kind": "tileset", "width": 64, "height": 32, "tile_width": 16,
             "tile_height": 16,
             "existing": self.existing(path="public/assets/tilesets/odd.png")}])
        self.assertIn(("texture-too-large", "warning"), self.codes(manifest, "huge"))
        self.assertIn(("dimension-mismatch", "warning"), self.codes(manifest, "huge"))
        self.assertIn(("invalid-tileset", "error"), self.codes(manifest, "odd"))

    def test_runtime_manifest_can_be_switched_off(self):
        manifest = self.build(runtime_manifest=False)
        self.assertNotIn("runtime_manifest", manifest)
        self.assertFalse(os.path.exists(os.path.join(self.root, *runtime.RUNTIME_PATH.split("/"))))


# -- the runtime validator ---------------------------------------------------------------------

class RuntimeValidation(EmptyCheckout):
    def setUp(self):
        super().setUp()
        self.manifest(self.design(requirements=REQUIREMENTS))
        self.path = os.path.join(self.root, *runtime.RUNTIME_PATH.split("/"))
        self.assertEqual(runtime.validate(self.root), [])

    def doc(self):
        with open(self.path, encoding="utf-8") as handle:
            return json.load(handle)

    def save(self, document):
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump(document, handle)

    def codes(self, severity=None):
        return sorted({i["code"] for i in runtime.validate(self.root)
                       if severity is None or i["severity"] == severity})

    def test_a_missing_file_and_a_changed_file(self):
        os.remove(os.path.join(self.root, "public/assets/audio/tap.placeholder.wav"))
        with open(os.path.join(self.root, "public/assets/atlases/hud.png"), "ab") as handle:
            handle.write(b"\x00")
        issues = runtime.validate(self.root)
        self.assertIn(("missing-file", "tap"), [(i["code"], i.get("asset_id")) for i in issues])
        self.assertIn("hash-mismatch", self.codes("error"))

    def test_duplicate_ids_are_caught_before_json_drops_one(self):
        text = open(self.path, encoding="utf-8").read()
        text = text.replace('"assets": {', '"assets": {\n    "tap": {"type": "sfx"},', 1)
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write(text)
        self.assertEqual(self.codes(), ["duplicate-id"])

    def test_urls_may_not_escape_public_or_name_another_origin(self):
        for url in ("../../package.json", "https://cdn.example/x.png", "/abs.png"):
            with self.subTest(url):
                document = self.doc()
                document["assets"]["tap"]["url"] = url
                self.save(document)
                self.assertIn("invalid-reference", self.codes("error"))

    def test_broken_atlas_and_animation_references(self):
        document = self.doc()
        document["assets"]["coin"]["frame"] = "nope"
        document["assets"]["star"]["atlas"] = "missing-atlas"
        document["assets"]["hero-run"]["animations"]["run"]["frames"].append("hero-run-99")
        self.save(document)
        issues = runtime.validate(self.root)
        by = {(i["code"], i.get("asset_id")) for i in issues}
        self.assertIn(("missing-frame", "coin"), by)
        self.assertIn(("invalid-reference", "star"), by)
        self.assertIn(("missing-frame", "hero-run"), by)

    def test_schema_violations(self):
        document = self.doc()
        del document["format"]
        document["assets"]["Bad_ID"] = {"type": "sprite", "url": "x.png"}
        self.save(document)
        self.assertIn("invalid-manifest", self.codes("error"))

    def test_unused_files_and_a_missing_manifest(self):
        with open(os.path.join(self.root, "public/assets/stray.png"), "wb") as handle:
            handle.write(raster.encode_png(solid(1, 1, (0, 0, 0, 0))))
        self.assertEqual(self.codes("warning"), ["unused-file"])
        self.assertEqual(runtime.validate(self.root, unused=False), [])
        os.remove(self.path)
        self.assertEqual(self.codes(), ["missing-manifest"])

    def test_a_tileset_that_does_not_divide(self):
        document = self.doc()
        document["assets"]["grass"]["tile_width"] = 48
        self.save(document)
        self.assertIn("invalid-tileset", self.codes("error"))


# -- the CLI ---------------------------------------------------------------------------------

def run_cli(*args, cwd=None):
    return subprocess.run([sys.executable, CLI, *args], capture_output=True, text=True,
                          cwd=cwd, timeout=120)


class Cli(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.mkdtemp(prefix="wgf-assets-cli-")
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)
        self.game = os.path.join(self.scratch, "game")
        os.makedirs(self.game)
        self.design = os.path.join(self.scratch, "design.json")
        with open(self.design, "w", encoding="utf-8") as handle:
            json.dump({"title_id": "cli-game", "asset_requirements": REQUIREMENTS}, handle)

    def test_build_then_validate(self):
        built = run_cli("build", "--design", self.design, "--root", self.game, "--json")
        self.assertEqual(built.returncode, 0, built.stderr)
        payload = json.loads(built.stdout)
        self.assertEqual(payload["runtime_manifest"]["path"], runtime.RUNTIME_PATH)
        self.assertEqual([a["id"] for a in payload["atlases"]], ["hud"])
        checked = run_cli("validate", self.game, "--json")
        self.assertEqual(checked.returncode, 0, checked.stdout)
        self.assertTrue(json.loads(checked.stdout)["ok"])
        again = run_cli("build", "--design", self.design, "--root", self.game, "--json")
        self.assertEqual(json.loads(again.stdout)["writes"]["created"], 0)

        with open(os.path.join(self.game, "public/assets/stray.txt"), "w") as handle:
            handle.write("x")
        self.assertEqual(run_cli("validate", self.game).returncode, 0)
        self.assertEqual(run_cli("validate", self.game, "--strict").returncode, 1)
        os.remove(os.path.join(self.game, "public/assets/atlases/hud.png"))
        failed = run_cli("validate", self.game)
        self.assertEqual(failed.returncode, 1)
        self.assertIn("missing-file", failed.stdout)

    def test_usage_errors_exit_2(self):
        self.assertEqual(run_cli("validate", os.path.join(self.scratch, "nope")).returncode, 2)
        with open(self.design, "w", encoding="utf-8") as handle:
            json.dump({"asset_requirements": [{"id": "a", "kind": "nonsense"}]}, handle)
        result = run_cli("build", "--design", self.design, "--root", self.game)
        self.assertEqual(result.returncode, 2)
        self.assertIn("unknown asset kind", result.stderr)

    def test_pack_is_deterministic_and_order_free(self):
        frames = os.path.join(self.scratch, "frames")
        os.makedirs(frames)
        for index, (name, image) in enumerate(_sprites()):
            with open(os.path.join(frames, f"{name}.png"), "wb") as handle:
                handle.write(raster.encode_png(image))
        out_a, out_b = (os.path.join(self.scratch, n, "atlas") for n in ("a", "b"))
        first = run_cli("pack", out_a, frames, "--animation", "all=frame-", "--json")
        self.assertEqual(first.returncode, 0, first.stderr)
        files = sorted(os.path.join(frames, n) for n in os.listdir(frames))
        second = run_cli("pack", out_b, *reversed(files), "--animation", "all=frame-")
        self.assertEqual(second.returncode, 0, second.stderr)
        for ext in (".png", ".json"):
            with open(out_a + ext, "rb") as a, open(out_b + ext, "rb") as b:
                self.assertEqual(a.read(), b.read(), ext)
        document = json.load(open(out_a + ".json"))
        self.assertEqual(document["animations"]["all"], [f"frame-{i}" for i in range(5)])
        self.assertEqual(json.loads(first.stdout)["frames"], [f"frame-{i}" for i in range(5)])
        overflow = run_cli("pack", out_a, frames, "--max-size", "16")
        self.assertEqual(overflow.returncode, 1)
        self.assertIn("split the group", overflow.stderr)

    def test_inspect(self):
        svg = os.path.join(self.scratch, "x.svg")
        with open(svg, "wb") as handle:
            handle.write(b'<svg width="4" height="4" onload="x()"></svg>')
        png = os.path.join(self.scratch, "x.png")
        with open(png, "wb") as handle:
            handle.write(raster.encode_png(solid(3, 5, (0, 0, 0, 255))))
        result = run_cli("inspect", svg, png, "--json")
        self.assertEqual(result.returncode, 1)
        reports = json.loads(result.stdout)
        self.assertEqual(reports[0]["format"], "svg")
        self.assertTrue(reports[0]["svg_hazards"])
        self.assertEqual((reports[1]["width"], reports[1]["height"], reports[1]["alpha"]),
                         (3, 5, True))


# -- develop and verify use it -----------------------------------------------------------------

class Consumers(EmptyCheckout):
    def test_the_develop_brief_points_at_the_runtime_manifest(self):
        from wgf_develop import brief as briefs
        design = self.design(requirements=REQUIREMENTS)
        manifest = self.manifest(design)
        brief = briefs.build_brief(title_id="fixture", engine="pixijs", iteration=1, key="k",
                                   baseline=None, design=design, assets=manifest,
                                   scaffold=None)
        self.assertEqual(brief["runtime_assets"], runtime.RUNTIME_PATH)
        text = briefs.render_markdown(brief)
        self.assertIn(f"`{runtime.RUNTIME_PATH}`", text)
        self.assertIn("never write an asset path in source", text)

    def test_the_verify_check_fails_broken_references_and_warns_on_stale_ones(self):
        from wgf_verification.checks import assets as checks

        class Session:
            root = self.root

            def exists(self, *parts):
                return os.path.exists(os.path.join(self.root, *parts))

        self.manifest(self.design(requirements=REQUIREMENTS))
        self.assertEqual(checks._runtime(Session()).status, "PASS")
        with open(os.path.join(self.root, "public/assets/atlases/hud.png"), "ab") as handle:
            handle.write(b"\x00")
        stale = checks._runtime(Session())
        self.assertEqual((stale.status, stale.required), ("WARNING", False))
        os.remove(os.path.join(self.root, "public/assets/atlases/hud.json"))
        self.assertEqual(checks._runtime(Session()).status, "FAIL")
        os.remove(os.path.join(self.root, *runtime.RUNTIME_PATH.split("/")))
        self.assertEqual(checks._runtime(Session()).status, "WARNING")


if __name__ == "__main__":
    unittest.main()

"""Mechanical checks for defects that were first caught only by eye (quality monitor, 2026-10-01).

    font.coverage        a delivered font's cmap sets every locale in the design's scope
                         (wgf_assets/quality.py; bundled fonts with no Cyrillic for `ru`)
    variants.distinct    a counted requirement's drawings differ by silhouette, not colour
                         (wgf_assets/quality.py, pipeline.py; two tower levels that look alike)
    scene.contrast       each readable entity stands out from a ring around its box in the
                         state frames (wgf_production/checks.py; dark barriers on a dark floor)
    pieces count         the drop-merge archetype draws one piece per level its rules reach
                         (wgf_design/archetypes.py; a fixed 6 against rules that reach 10)

The design-side coverage check is in test_design_presentation.FontCoverage. Fonts, drawings
and frames here are synthesised; the real files these checks were demonstrated on are named
in docs/assets-module.md and docs/production-quality-module.md.

    python -m unittest scripts/tests/test_quality_mechanical.py
"""

import ctypes
import os
import shutil
import struct
import sys
import tempfile
import unittest
import zlib
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

from wgf_assets import quality  # noqa: E402
from wgf_assets.raster import Image, encode_png  # noqa: E402
from wgf_design import archetypes  # noqa: E402
from wgf_production import checks as production  # noqa: E402
from wgflib.yamllite import load_file  # noqa: E402

LATIN = [ord(c) for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789 .,!?"]
CYRILLIC = list(range(0x0410, 0x0450)) + [0x0401, 0x0451]


# -- fonts ------------------------------------------------------------------------------------

def _cmap4(codes):
    """A format 4 subtable mapping each code to glyph index+1 (one segment per code)."""
    codes = sorted(set(codes)) + [0xFFFF]
    seg = len(codes)
    ends = starts = codes
    deltas = [(i + 1 - c) & 0xFFFF for i, c in enumerate(codes[:-1])] + [1]
    body = struct.pack(f">{seg}H", *ends) + b"\0\0" + struct.pack(f">{seg}H", *starts)
    body += struct.pack(f">{seg}H", *deltas) + struct.pack(f">{seg}H", *([0] * seg))
    header = struct.pack(">HHHHHHH", 4, 14 + len(body), 0, seg * 2, 0, 0, 0)
    return header + body


def _cmap12(codes):
    groups = [(c, c, i + 1) for i, c in enumerate(sorted(set(codes)))]
    body = b"".join(struct.pack(">III", *g) for g in groups)
    return struct.pack(">HHIII", 12, 0, 16 + len(body), 0, len(groups)) + body


def cmap_table(codes, fmt=4):
    sub = _cmap4(codes) if fmt == 4 else _cmap12(codes)
    platform = (3, 1) if fmt == 4 else (3, 10)
    return struct.pack(">HHHHI", 0, 1, platform[0], platform[1], 12) + sub


def sfnt_tables(codes, fmt=4, glyphs=200):
    return {"cmap": cmap_table(codes, fmt), "name": b"\0" * 8, "glyf": b"\0" * 8,
            "loca": b"\0" * 8, "maxp": struct.pack(">IH", 0x00005000, glyphs),
            "head": b"\0" * 54}


def ttf(codes, fmt=4):
    tables = sfnt_tables(codes, fmt)
    tags = sorted(tables)
    out = struct.pack(">IHHHH", 0x00010000, len(tags), 0, 0, 0)
    offset = 12 + 16 * len(tags)
    directory, body = b"", b""
    for tag in tags:
        data = tables[tag]
        directory += struct.pack(">4sIII", tag.encode(), 0, offset + len(body), len(data))
        body += data + b"\0" * (-len(data) % 4)
    return out + directory + body


def woff(codes):
    tables = sfnt_tables(codes)
    tags = sorted(tables)
    offset = 44 + 20 * len(tags)
    directory, body = b"", b""
    for tag in tags:
        data = tables[tag]
        packed = zlib.compress(data)
        if len(packed) >= len(data):
            packed = data
        directory += struct.pack(">4sIIII", tag.encode(), offset + len(body), len(packed),
                                 len(data), 0)
        body += packed + b"\0" * (-len(packed) % 4)
    total = offset + len(body)
    header = struct.pack(">4s4sIHHI", b"wOFF", b"\x00\x01\x00\x00", total, len(tags), 0, 0)
    header += struct.pack(">HHIIIII", 1, 0, 0, 0, 0, 0, 0)
    return header + directory + body


def _brotli_encoder():
    for name in ("libbrotlienc.so.1", "libbrotlienc.so", "libbrotlienc.1.dylib",
                 "libbrotlienc.dylib"):
        try:
            return ctypes.CDLL(name)
        except OSError:
            continue
    return None


ENCODER = _brotli_encoder()
WOFF2_INDEX = {"cmap": 0, "head": 1, "maxp": 4, "name": 5, "glyf": 10, "loca": 11}


def base128(value):
    out = [value & 0x7F]
    value >>= 7
    while value:
        out.insert(0, 0x80 | (value & 0x7F))
        value >>= 7
    return bytes(out)


def woff2(codes):
    """A WOFF2 with every table null-transformed (glyf/loca transform version 3)."""
    tables = sfnt_tables(codes)
    order = sorted(tables, key=lambda t: WOFF2_INDEX[t])
    directory, stream = b"", b""
    for tag in order:
        index = WOFF2_INDEX[tag]
        version = 3 if tag in ("glyf", "loca") else 0
        directory += bytes([index | (version << 6)]) + base128(len(tables[tag]))
        stream += tables[tag]
    out = ctypes.create_string_buffer(len(stream) + 1024)
    size = ctypes.c_size_t(len(out))
    ENCODER.BrotliEncoderCompress.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                              ctypes.c_size_t, ctypes.c_char_p,
                                              ctypes.POINTER(ctypes.c_size_t), ctypes.c_char_p]
    assert ENCODER.BrotliEncoderCompress(11, 22, 0, len(stream), stream, ctypes.byref(size), out)
    compressed = out.raw[:size.value]
    body = directory + compressed
    total = 48 + len(body)
    header = struct.pack(">4s4sIHHIIHHIIIII", b"wOF2", b"\x00\x01\x00\x00", total, len(order), 0,
                         12 + 16 * len(order) + len(stream), len(compressed), 1, 0, 0, 0, 0, 0, 0)
    return header + body


class FontCoverage(unittest.TestCase):
    def coverage(self, data, locales):
        judged = quality.font_quality(data, locales=locales)
        return judged["verdict"], next((c for c in judged["checks"]
                                        if c["id"] == "font.coverage"), None)

    def test_a_latin_ttf_sets_en_and_not_ru(self):
        data = ttf(LATIN)
        self.assertEqual(self.coverage(data, ["en"])[0], "pass")
        verdict, check = self.coverage(data, ["en", "ru"])
        self.assertEqual(verdict, "fail")
        self.assertEqual(check["status"], "fail")
        self.assertIn("ru: 66 of 66 required characters have no glyph", check["summary"])
        self.assertIn("cyrillic not covered", check["summary"])

    def test_a_cyrillic_ttf_sets_ru(self):
        for fmt in (4, 12):
            with self.subTest(fmt=fmt):
                self.assertEqual(self.coverage(ttf(LATIN + CYRILLIC, fmt), ["ru", "en"])[0],
                                 "pass")

    def test_one_missing_letter_fails(self):
        verdict, check = self.coverage(ttf(LATIN + [c for c in CYRILLIC if c != 0x0451]), ["ru"])
        self.assertEqual(verdict, "fail")
        self.assertIn("1 of 66", check["summary"])
        self.assertIn("ё", check["summary"])

    def test_locale_subtags_and_unlisted_locales(self):
        self.assertEqual(self.coverage(ttf(LATIN), ["en-US"])[0], "pass")
        verdict, check = self.coverage(ttf(LATIN), ["xx"])
        self.assertEqual((verdict, check["status"]), ("pass", "skipped"))
        self.assertIn("no character table for xx", check["summary"])

    def test_without_locales_coverage_is_not_read(self):
        self.assertIsNone(self.coverage(ttf(LATIN), [])[1])

    def test_woff_tables_are_inflated(self):
        self.assertEqual(self.coverage(woff(LATIN), ["en"])[0], "pass")
        self.assertEqual(self.coverage(woff(LATIN), ["ru"])[0], "fail")
        self.assertEqual(self.coverage(woff(LATIN + CYRILLIC), ["ru"])[0], "pass")

    @unittest.skipUnless(ENCODER, "no system Brotli encoder (libbrotlienc) to build a WOFF2")
    def test_woff2_is_read_with_the_system_decoder(self):
        self.assertEqual(self.coverage(woff2(LATIN), ["en"])[0], "pass")
        self.assertEqual(self.coverage(woff2(LATIN), ["en", "ru"])[0], "fail")
        self.assertEqual(self.coverage(woff2(LATIN + CYRILLIC), ["ru"])[0], "pass")

    def test_woff2_without_a_decoder_is_unchecked_never_passed(self):
        data = woff2(LATIN) if ENCODER else None
        if data is None:
            self.skipTest("no system Brotli encoder (libbrotlienc) to build a WOFF2")
        with mock.patch.object(quality, "_BROTLI_LIBRARIES", ("no-such-brotli.so",)):
            verdict, check = self.coverage(data, ["ru"])
        self.assertEqual(check["status"], "skipped")
        self.assertIn("coverage unchecked for ru", check["summary"])
        self.assertIn("no Brotli decoder", check["summary"])

    def test_bars_read_the_reference_table(self):
        bars = quality.load_bars()
        self.assertEqual(len(bars.locale_chars("ru")), 66)
        self.assertEqual(bars.locale("pt-BR")["subsets"], ["latin"])
        self.assertEqual(quality.expand_chars(["A..C", "xy"]), ["A", "B", "C", "x", "y"])


# -- variants -------------------------------------------------------------------------------

def tower(level, fill="#FF48B0", roof="#0078BF", scale=None, numeral=None):
    """A tower drawing: a body and a roof growing with the level, and the level's numeral."""
    k = scale if scale is not None else 0.4 + 0.075 * level
    w, h = 120 * k, 150 * k
    x, y = 96 - w / 2, 184 - h
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 192 192">'
            f'<path d="M{x} {y}h{w}v{h}h-{w}Z" fill="{fill}" stroke="#1C1A17"/>'
            f'<path d="M{x - 8} {y}L96 {y - 30 * k}L{x + w + 8} {y}Z" fill="{roof}"/>'
            f'<circle cx="96" cy="{y + h / 2}" r="{10 * k}" fill="#FFD23F"/>'
            f'<text x="96" y="{y + h / 2}">{numeral or level}</text></svg>').encode()


def blob_png(size, box, colour=(240, 200, 80)):
    w, h = size
    image = Image(w, h)
    for y in range(box[1], box[1] + box[3]):
        for x in range(box[0], box[0] + box[2]):
            image.pixels[(y * w + x) * 4:(y * w + x) * 4 + 4] = bytes(list(colour) + [255])
    return encode_png(image)


class VariantsDistinct(unittest.TestCase):
    def test_towers_that_grow_pass(self):
        check, measured = quality.variants_distinct(
            [(f"pieces-{n}", tower(n), "svg") for n in range(1, 9)])
        self.assertEqual(check["status"], "pass", check)
        self.assertEqual(len(measured["pairs"]), 28)
        self.assertGreaterEqual(measured["closest"], measured["bar"])

    def test_a_recolour_with_another_numeral_fails(self):
        drawings = [("pieces-1", tower(1), "svg"), ("pieces-2", tower(2), "svg"),
                    ("pieces-3", tower(2, fill="#F040A8", roof="#1080C0", numeral=3), "svg")]
        check, measured = quality.variants_distinct(drawings)
        self.assertEqual(check["status"], "fail")
        self.assertEqual(measured["pairs"]["pieces-2~pieces-3"], 0.0)
        self.assertIn("pieces-2 and pieces-3 differ by 0.00", check["summary"])

    def test_transforms_are_applied(self):
        base = tower(4, scale=0.7)
        moved = base.replace(b'<path d=', b'<g transform="translate(40 0) scale(0.6)"><path d=', 1) \
            .replace(b"</svg>", b"</g></svg>")
        check, _ = quality.variants_distinct([("a", base, "svg"), ("b", moved, "svg")])
        self.assertEqual(check["status"], "pass", check)

    def test_backdrops_are_told_apart_by_their_motif_not_their_sky(self):
        def backdrop(motif, sky="#0B0B12"):
            return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 720 1280">'
                    f'<rect width="720" height="1280" fill="{sky}"/>'
                    f'<rect width="720" height="1280" fill="#9B6BFF" opacity="0.1"/>'
                    f'{motif}</svg>').encode()
        moon = '<circle cx="520" cy="300" r="120" fill="#161630"/>'
        skyline = '<path d="M0 1000h120v-200h100v120h140v-260h120v180h240v160H0Z" fill="#14112A"/>'
        check, _ = quality.variants_distinct(
            [("world-1", backdrop(moon), "svg"), ("world-2", backdrop(skyline), "svg")])
        self.assertEqual(check["status"], "pass", check)
        # The same motif under another sky is still a recolour.
        check, _ = quality.variants_distinct(
            [("world-1", backdrop(moon), "svg"), ("world-2", backdrop(moon, "#200A0A"), "svg")])
        self.assertEqual(check["status"], "fail", check)

    def test_png_silhouettes(self):
        a = blob_png((64, 64), (8, 8, 20, 40))
        b = blob_png((64, 64), (8, 8, 20, 40), colour=(40, 120, 220))
        c = blob_png((64, 64), (20, 30, 40, 30))
        self.assertEqual(quality.variants_distinct([("a", a, "png"), ("b", b, "png")])[0]["status"],
                         "fail")
        self.assertEqual(quality.variants_distinct([("a", a, "png"), ("c", c, "png")])[0]["status"],
                         "pass")

    def test_one_drawing_is_not_judged(self):
        self.assertIsNone(quality.variants_distinct([("a", tower(1), "svg")]))


# -- the assets step: an author whose variants are recolours ------------------------------

class AuthorVariants(unittest.TestCase):
    def setUp(self):
        import test_assets_production as production_tests
        self.tests = production_tests
        self.case = production_tests.ProductionCase("run")
        self.case.setUp()
        self.addCleanup(self.case.tearDown)

    def run_author(self, mode):
        tests = self.tests
        design = tests.production_design([tests.spec_asset("tile", "sprite", "target", count=3,
                                                           spec="readable at 96px")])
        manifest, _ = self.case.run_prod(design, author=self.case.author(mode))
        return self.case.items(manifest)["tile"], self.case.calls()

    def test_recoloured_variants_are_sent_back_and_never_delivered(self):
        item, calls = self.run_author("same-variants")
        self.assertTrue(item.get("placeholder"), item)
        repairs = [c for c in calls if c.get("repair")]
        self.assertTrue(repairs)
        self.assertIn("variants.distinct: tile-2 has the silhouette of tile-1",
                      " ".join(repairs[0]["repair"]["problems"]))
        self.assertEqual(repairs[0]["siblings"][0]["variant"], "tile-1")

    def test_a_repaired_variant_is_delivered_and_the_set_judged(self):
        item, _calls = self.run_author("same-then-good")
        self.assertFalse(item.get("placeholder"), item)
        self.assertEqual(item["quality"]["verdict"], "pass", item["quality"])
        distinct = [c for c in item["quality"]["checks"] if c["id"] == "variants.distinct"]
        self.assertEqual([c["status"] for c in distinct], ["pass"])


    def test_a_library_short_of_the_count_fails_the_set(self):
        tests = self.tests
        design = tests.production_design([tests.spec_asset("tile", "sprite", "target", count=3,
                                                           spec="readable at 96px")])
        manifest, _ = self.case.run_prod(design, libraries=[tests.MAPPED])
        item = self.case.items(manifest)["tile"]
        self.assertEqual(item["source"], "library")
        self.assertEqual(item["quality"]["verdict"], "fail")
        count = next(c for c in item["quality"]["checks"] if c["id"] == "variants.count")
        self.assertIn("2 of the 3 drawings", count["summary"])
        short = [i for i in manifest.get("issues") or item.get("issues") or []
                 if i["code"] == "variants-short"]
        self.assertTrue(short)
        self.assertEqual(short[0]["severity"], "error")
        self.assertFalse(item.get("production_ready"))


# -- the production gate: entity local contrast --------------------------------------------

def frame(directory, name, entity_colour, size=(200, 300), ground=(20, 26, 48)):
    w, h = size
    image = Image(w, h, bytes(list(ground) + [255]) * (w * h))
    for x0, y0, bw, bh in ((60, 100, 40, 30), (80, 220, 50, 40)):
        for y in range(y0, y0 + bh):
            for x in range(x0, x0 + bw):
                image.pixels[(y * w + x) * 4:(y * w + x) * 4 + 3] = bytes(entity_colour)
    with open(os.path.join(directory, f"{name}.png"), "wb") as handle:
        handle.write(encode_png(image))


def contrast_records(threat_box=(60, 100, 40, 30)):
    entities = [{"id": "wall-1", "role": "threat", "asset": "barrier", "render": "asset",
                 "visible": True, "x": threat_box[0], "y": threat_box[1], "w": threat_box[2],
                 "h": threat_box[3]},
                {"id": "craft", "role": "player", "asset": "craft", "render": "asset",
                 "visible": True, "x": 80, "y": 220, "w": 50, "h": 40}]
    return {"first-session": {"ui": {"playing": {"probe_state": "playing", "frame": "state-playing",
                                                 "viewport": [200, 300], "entities": entities}}}}


class SceneContrast(unittest.TestCase):
    def setUp(self):
        self.rules = load_file(os.path.join(os.path.dirname(os.path.dirname(HERE)), "core",
                                            "reference", "production-quality.yaml"))
        self.dir = tempfile.mkdtemp(prefix="wgf-contrast-")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)

    def check(self, colour, records=None):
        frame(self.dir, "state-playing", colour)
        return production.scene_contrast("mobile", records or contrast_records(), self.rules,
                                         production._Frames(self.dir))

    def test_bright_entities_on_a_dark_floor_pass(self):
        result = self.check((240, 200, 80))
        self.assertEqual(result["status"], "PASS", result)
        self.assertGreater(result["measured"]["threat"]["ratio"], 3)

    def test_dark_entities_on_a_dark_floor_fail(self):
        result = self.check((70, 40, 110))  # purple barrier, navy floor
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["route"], "develop")
        self.assertIn("threat at best", result["summary"])
        self.assertEqual(sorted(result["assets"]), ["barrier", "craft"])
        self.assertLess(result["measured"]["threat"]["ratio"], 3)

    def test_boxes_too_small_to_judge_are_a_warning(self):
        records = contrast_records(threat_box=(60, 100, 8, 8))
        records["first-session"]["ui"]["playing"]["entities"].pop()
        result = self.check((70, 40, 110), records)
        self.assertEqual((result["status"], result["required"]), ("WARNING", False))
        self.assertIn("threat only below 12 px", result["summary"])

    def test_the_judge_runs_it_per_viewport(self):
        frame(self.dir, "state-playing", (70, 40, 110))
        ids = [(c["id"], c.get("project")) for c in production.judge(
            {"mobile": contrast_records()}, {"items": []}, {}, self.rules, {"mobile": self.dir})]
        self.assertIn(("scene.contrast", "mobile"), ids)


# -- the drop-merge archetype's piece count -------------------------------------------------

class PiecesFromRules(unittest.TestCase):
    def test_the_rules_reach_level_ten(self):
        self.assertEqual(archetypes.drop_merge_top_level(7, 4, 4), 10)

    def test_the_search_is_not_a_formula(self):
        # The ramp never reaches 3 before a 3-column track fills: the top is 4, not 3 + 3 - 1.
        self.assertEqual(archetypes.drop_merge_top_level(3, 4, 3), 4)
        self.assertEqual(archetypes.drop_merge_top_level(5, 4, 4), 8)
        self.assertEqual(archetypes.drop_merge_top_level(4, 4, 1), 4)

    def test_the_pieces_requirement_counts_every_reachable_level(self):
        a = archetypes.ARCHETYPES["drop-merge"]
        params = {}
        for mechanic in a["mechanics"]:
            params.update(mechanic.get("parameters") or {})
        pieces = next(x for x in a["assets"] if x["id"] == "pieces")
        self.assertEqual(pieces["count"], archetypes.drop_merge_top_level(
            params["columns"], params["merges_per_level_up"], params["max_drop_level"]))
        self.assertEqual(pieces["count"], 10)
        self.assertIn("1-10", pieces["description"])


if __name__ == "__main__":
    unittest.main()

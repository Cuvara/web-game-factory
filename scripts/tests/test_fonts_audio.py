"""Fonts and audio an unattended run can make: the Factory font library, the composer, the
standard-library Vorbis encoder, and their place in the asset pipeline.

    python -m unittest scripts/tests/test_fonts_audio.py

Offline and deterministic. A browser decode of the Vorbis output was checked by hand (see
docs/assets-module.md, "Fonts and audio"); here the bitstream is checked structurally - page
CRCs, headers, granule positions, exact length - and the transform and floor against
independent implementations of the specification.
"""

import copy
import math
import os
import random
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
sys.path.insert(0, SCRIPTS)

from wgf_assets import audiofile, fontlib, quality, runtime  # noqa: E402
from wgf_assets.pipeline import AssetPipeline, AssetStore  # noqa: E402
from wgf_assets.placeholders import build_backends  # noqa: E402
from wgf_assets.policy import load_policy  # noqa: E402
from wgf_assets.requirements import inspect  # noqa: E402
from wgf_assets.sound import measure, music, sfx, style, vorbis  # noqa: E402
from wgf_assets.sound.producer import AudioProducer, cue_kind, wav_bytes  # noqa: E402
from wgf_design import identity, presentation  # noqa: E402
from wgf_production import checks as production_checks  # noqa: E402


def _design(kit="paper-diorama", audio_direction="Bright, playful loop", locales=("en", "ru"),
            music_entries=None):
    _kit, look = identity.choose("t", [], pinned=kit)
    look = dict(look, typography=dict(look["typography"]))
    look, _ = identity.cover(look, list(locales), presentation.load_font_coverage())
    families = identity.families(look["typography"])
    entries = music_entries if music_entries is not None else [
        {"id": "music-loop", "type": "music", "tier": "mvp", "loop": True,
         "description": "Play loop of at least 30 s, seamless", "trigger": "Run start"},
    ]
    return {
        "title_id": "test-title",
        "fantasy": "A test game.",
        "audio_direction": audio_direction,
        "art_direction": f"Identity kit '{kit}'.",
        "scope": {"locales": list(locales)},
        "engine": {"dimension": "2d"},
        "build_spec": {
            "visual_identity": look,
            "assets": [{"id": "fonts", "type": "font", "tier": "mvp", "role": "font",
                        "dimension": "2d", "count": len(families),
                        "description": " and ".join(families)}],
            "audio": entries + [
                {"id": "ui-tap", "type": "ui", "tier": "mvp", "description": "UI tap",
                 "trigger": "Any button"},
                {"id": "sfx-merge", "type": "sfx", "tier": "mvp",
                 "description": "Merge pop, pitched per cascade step", "trigger": "Merge"},
                {"id": "sfx-game-over", "type": "sfx", "tier": "mvp",
                 "description": "Game-over sting", "trigger": "Run ends"},
            ],
        },
    }


class TheFontLibrary(unittest.TestCase):
    def test_holds_every_face_a_kit_can_name(self):
        self.assertEqual(fontlib.check(), [])
        library = fontlib.load()
        for family in fontlib.kit_faces():
            entry = library.family(family)
            self.assertIsNotNone(entry, family)
            self.assertEqual(entry["license"], "OFL-1.1")
            self.assertTrue(os.path.isfile(library.path(entry, "license_file")))
            self.assertIn(fontlib.SOURCE_COMMIT, entry["source_url"])

    def test_faces_parse(self):
        self.assertEqual(fontlib.parse_face("Fraunces (800, soft)"), ("Fraunces", 800))
        self.assertEqual(fontlib.parse_face("Archivo Black, tabular"), ("Archivo Black", 400))
        self.assertEqual(fontlib.parse_face(""), (None, None))

    def test_every_kit_covered_for_its_locales(self):
        library = fontlib.load()
        for kit in identity.KITS:
            for locales in (["en"], ["en", "ru"]):
                design = _design(kit, locales=locales)
                look = design["build_spec"]["visual_identity"]
                self.assertEqual(presentation.font_library(design, library), [], kit)
                producer = fontlib.FontProducer(library, look["typography"], locales)
                req = _requirements(design)["fonts"]
                try:
                    made = producer.produce(req)
                except fontlib.ProducerError as exc:  # a kit that cannot set ru at all
                    self.assertIn("ru", locales, f"{kit}: {exc}")
                    continue
                for entry in made["files"]:
                    judged = quality.font_quality(entry["data"], locales=locales)
                    covered = [c for c in judged["checks"] if c["id"] == "font.coverage"]
                    self.assertNotEqual(judged["verdict"], "fail",
                                        f"{kit} {entry['family']}: {judged['checks']}")
                    self.assertTrue(covered)

    def test_unknown_family_is_a_design_problem_and_refused(self):
        design = _design()
        design["build_spec"]["visual_identity"]["typography"]["display"] = "Comic Sans (700)"
        problems = presentation.font_library(design, fontlib.load())
        self.assertTrue(any("Comic Sans" in p for p in problems))
        producer = fontlib.FontProducer(fontlib.load(),
                                        design["build_spec"]["visual_identity"]["typography"])
        with self.assertRaises(fontlib.ProducerError):
            producer.produce(_requirements(design)["fonts"])

    def test_a_file_per_weight_count_is_met_by_one_file_per_family(self):
        # F23: an agent's design counted 3 font files (Playfair Display; Commissioner 500
        # and 700) for 2 families; the producer refused, and the fonts stayed a placeholder.
        design = _design()
        typography = design["build_spec"]["visual_identity"]["typography"]
        families = identity.families(typography)
        design["build_spec"]["assets"][0]["count"] = len(families) + 1
        made = fontlib.FontProducer(fontlib.load(), typography, ["en"]).produce(
            _requirements(design)["fonts"])
        self.assertEqual([f["family"] for f in made["files"]], families)
        self.assertIn("one file per family", made["notes"])

    def test_a_refusal_is_a_warning_in_the_step_log(self):
        design = _design(locales=("en",))
        design["build_spec"]["visual_identity"]["typography"]["display"] = "Comic Sans (700)"
        design["build_spec"]["audio"] = []
        warnings = []

        class Logger:
            def info(self, *_a, **_k):
                pass

            def warning(self, message, **fields):
                warnings.append((message, fields))

        root = tempfile.mkdtemp(prefix="wgf-font-refusal-")
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        policy = load_policy()
        requirements, _dim = inspect(copy.deepcopy(design), policy)
        producer = fontlib.FontProducer(fontlib.load(),
                                        design["build_spec"]["visual_identity"]["typography"],
                                        ["en"])
        AssetPipeline(policy, AssetStore(root), build_backends([], {}), title_id="t",
                      producers=[producer], locales=["en"], logger=Logger()).run(
            [r for r in requirements if r.id == "fonts"])
        refused = [f for m, f in warnings if m == "producer refused"]
        self.assertEqual(len(refused), 1, warnings)
        self.assertEqual((refused[0]["asset"], refused[0]["producer"]), ("fonts", "font-library"))
        self.assertIn("Comic Sans", refused[0]["reason"])


class TheVorbisEncoder(unittest.TestCase):
    def test_mdct_matches_the_definition(self):
        rng = random.Random(3)
        n = 64
        x = [rng.uniform(-1, 1) for _ in range(n)]
        fast = vorbis._Mdct(n).forward(x)
        for k in range(n // 2):
            slow = sum(x[i] * math.cos(2 * math.pi / n * (i + 0.5 + n / 4) * (k + 0.5))
                       for i in range(n))
            self.assertAlmostEqual(fast[k], slow, places=9)

    def test_huffman_codes_are_complete_prefix_codes(self):
        for counts in ([5], [1, 1], [100, 1, 1, 1, 50, 7], list(range(1, 300))):
            lengths = vorbis.huffman_lengths(counts)
            if len(counts) > 1:
                self.assertAlmostEqual(sum(2.0 ** -l for l in lengths), 1.0)
                words = vorbis.codewords(lengths)
                seen = {(w, l) for w, l in words}
                self.assertEqual(len(seen), len(words))

    def test_floor_matches_an_independent_decode(self):
        floor = vorbis._Floor(vorbis.HALF)
        rng = random.Random(7)
        for _ in range(300):
            wanted = [rng.randint(0, 127) for _ in floor.xs]
            vals, curve = floor.encode(wanted)
            self.assertEqual(curve, _decode_floor(floor.xs, vals, vorbis.HALF))
            self.assertTrue(all(0 <= v < vorbis.RANGE for v in vals))

    def test_stream_structure_length_and_determinism(self):
        rate = 22050
        n = vorbis.HALF * 40
        left = [0.3 * math.sin(2 * math.pi * 440 * i / rate) for i in range(n)]
        right = [0.2 * math.sin(2 * math.pi * 660 * i / rate) for i in range(n)]
        data = vorbis.encode([left, right], rate, loop=True)
        info = audiofile.read(data)  # raises on a bad CRC or header
        self.assertEqual((info.codec, info.channels, info.sample_rate, info.frames),
                         ("vorbis", 2, rate, n))
        self.assertEqual(data, vorbis.encode([left, right], rate, loop=True))
        mono = vorbis.encode([left], rate)
        self.assertEqual(audiofile.read(mono).channels, 1)
        silent = vorbis.encode([[0.0] * n], rate)
        self.assertEqual(audiofile.read(silent).frames, n)


class TheComposer(unittest.TestCase):
    def test_designs_get_different_music(self):
        toy = style.brief_for(_design("paper-diorama", "Bright, playful loop"), title_id="a")
        neon = style.brief_for(_design("neon-night", "Flight loop, intensity rises with "
                                                     "speed"), title_id="b")
        self.assertEqual(toy.style, "toybox")
        self.assertEqual(neon.style, "synthwave")
        self.assertNotEqual((toy.mode, toy.tempo), (neon.mode, neon.tempo))
        for kit in identity.KITS:
            brief = style.brief_for(_design(kit), title_id=kit)
            self.assertIn(brief.style, style.STYLES)
            lo, hi = style.STYLES[brief.style]["tempo"]
            self.assertTrue(lo - 1 <= brief.tempo <= hi + 1)

    def test_a_cue_is_a_seamless_loop_of_whole_blocks_at_its_level(self):
        rate = 22050
        song = music.Song(style.brief_for(_design("neon-night"), title_id="x"))
        left, right, info = music.render_cue(song, "title", 12, rate)
        self.assertEqual(len(left) % 512, 0)
        self.assertGreaterEqual(len(left) / rate, 12)
        stats = measure.stats([left, right], rate, loop=True, loudness=False)
        self.assertLessEqual(stats["peak_dbfs"], -0.99)
        self.assertAlmostEqual(stats["rms_dbfs"], music.TARGET_RMS["title"], delta=2.5)
        self.assertLessEqual(stats["seam"]["ratio"], 8)

    def test_every_cue_kind_meets_both_seam_bars(self):
        # goalkeeper-royale, 2026-10-02: the intensity layer's turnaround riser swelled into
        # a bar 0 with no downbeat crash, and the rendered seam's edges differed 6.46 dB
        # (bar 6). A base or layer cue cannot move its loop point (it stays in lock-step
        # with the main cue), so its arrangement has to land the turnaround.
        rate = 22050
        for title in ("x", "goalkeeper-royale"):
            song = music.Song(style.brief_for(_design("neon-night"), title_id=title))
            for kind in ("main", "base", "layer"):
                left, right, _ = music.render_cue(song, kind, 12, rate)
                seam = measure.seam([left, right], rate)
                with self.subTest(title=title, kind=kind, seam=seam):
                    self.assertLessEqual(seam["ratio"], 8)
                    self.assertLessEqual(seam["edge_db"], 6)

    def test_a_variation_recomposes_the_song_for_a_re_entry(self):
        # A gate that sends a composed cue back must get different art (the assets step's
        # re-entry contract): the composer offsets its seed by the variation, every cue
        # moving together. The font library hands over fixed files and says so.
        from wgf_assets import fontlib
        from wgf_assets.sound.producer import AudioProducer
        design = _design("neon-night")
        same = AudioProducer(design, "x", encoder="wav")
        again = AudioProducer(design, "x", encoder="wav")
        varied = AudioProducer(design, "x", encoder="wav", variation=1)
        self.assertTrue(AudioProducer.varies)
        self.assertFalse(fontlib.FontProducer.varies)
        self.assertEqual(same.brief.seed, again.brief.seed)
        self.assertNotEqual(same.brief.seed, varied.brief.seed)
        rate = 22050
        a = music.render_cue(same.song, "layer", 8, rate)[0]
        b = music.render_cue(varied.song, "layer", 8, rate)[0]
        self.assertNotEqual(a[:4096], b[:4096])

    def test_sfx_roles_and_bounds(self):
        song = music.Song(style.brief_for(_design(), title_id="x"))
        self.assertEqual(sfx.role({"merge", "cascade"}, {"sfx", "merge"}), "pop")
        self.assertEqual(sfx.role({"sfx", "game-over", "sting"}, {"sfx", "game-over"}),
                         "game-over")
        rendered = {}
        for name, _words in sfx.RECIPES:
            loop = name == "engine"
            out, info = sfx.render_sfx({name}, song, 22050, loop=loop, primary={name})
            self.assertEqual(info["recipe"], name)
            stats = measure.stats([out], 22050, loop=loop, loudness=False)
            self.assertLessEqual(stats["duration_s"], 6)
            self.assertAlmostEqual(stats["peak_dbfs"], -1.0, delta=0.05)
            if loop:
                self.assertLessEqual(stats["seam"]["ratio"], 8)
            rendered[name] = out
        self.assertEqual(len({tuple(v[:200]) for v in rendered.values()}), len(rendered))

    def test_cue_kinds(self):
        design = _design(music_entries=[
            {"id": "music-drive", "type": "music", "description": "Flight loop, 60 s"},
            {"id": "music-drive-layer", "type": "music",
             "description": "Intensity layer of the flight loop"},
            {"id": "music-title", "type": "music", "description": "Calmer title variant"}])
        reqs = _requirements(design)
        ids = ["music-drive", "music-drive-layer", "music-title"]
        self.assertEqual([cue_kind(reqs[i], ids) for i in ids], ["main", "layer", "title"])

    def test_wav_bytes(self):
        data = wav_bytes([[0.0, 0.5, -0.5, 1.0]], 22050)
        info = audiofile.read(data)
        self.assertEqual((info.channels, info.sample_rate, info.frames), (1, 22050, 4))


class ThePipeline(unittest.TestCase):
    """Fonts and audio delivered as final, licensed, judged assets - what production-quality's
    assets.present accepts."""

    @classmethod
    def setUpClass(cls):
        cls.root = tempfile.mkdtemp(prefix="wgf-fonts-audio-")
        cls.design = _design()
        policy = load_policy()
        requirements, _dim = inspect(cls.design, policy)
        producers = [fontlib.FontProducer(fontlib.load(),
                                          cls.design["build_spec"]["visual_identity"]["typography"],
                                          cls.design["scope"]["locales"]),
                     AudioProducer(cls.design, "test-title")]
        pipeline = AssetPipeline(policy, AssetStore(cls.root), build_backends([], {}),
                                 title_id="test-title", producers=producers,
                                 locales=cls.design["scope"]["locales"])
        cls.result = pipeline.run(requirements)
        cls.items = {i["id"]: i for i in cls.result.items}

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.root, ignore_errors=True)

    def test_every_item_final_and_passing(self):
        for asset_id in ("fonts", "music-loop", "ui-tap", "sfx-merge", "sfx-game-over"):
            item = self.items[asset_id]
            self.assertFalse(item.get("placeholder"), asset_id)
            self.assertEqual(item["status"], "delivered", asset_id)
            self.assertEqual(item["quality"]["verdict"], "pass", (asset_id, item["quality"]))
            self.assertTrue(item["production_ready"], (asset_id, item.get("issues")))
        self.assertEqual(self.items["fonts"]["license"], "OFL-1.1")
        self.assertEqual(self.items["music-loop"]["files"][0]["format"], "ogg")
        checks = {c["id"] for c in self.items["music-loop"]["quality"]["checks"]}
        self.assertIn("audio.rendered-level", checks)
        self.assertIn("audio.rendered-seam", checks)

    def test_production_quality_accepts_them(self):
        manifest = {"items": self.result.items}
        wanted = production_checks.required_assets(manifest, self.design, {})
        check = production_checks.assets_present(wanted)
        self.assertEqual(check["status"], "PASS", check)

    def test_runtime_manifest_names_each_face(self):
        import json
        with open(os.path.join(self.root, runtime.RUNTIME_PATH), encoding="utf-8") as handle:
            document = json.load(handle)
        faces = [document["assets"][v] for v in document["assets"]["fonts"]["variants"]]
        typography = self.design["build_spec"]["visual_identity"]["typography"]
        self.assertEqual([f["family"] for f in faces], identity.families(typography))
        self.assertTrue(all(f.get("weight") for f in faces))
        problems = runtime.validate(self.root)
        self.assertEqual([p for p in problems if p["severity"] != "info"], [], problems)
        licences = [n for n in os.listdir(os.path.join(self.root, "public/assets/fonts"))
                    if n.startswith("LICENSE-")]
        self.assertEqual(len(licences), len(faces))


def _requirements(design):
    reqs, _dim = inspect(copy.deepcopy(design), load_policy())
    return {r.id: r for r in reqs}


def _decode_floor(xs, vals, half, mult=2, rng=128):
    """Vorbis I 7.2.4 written out again, independently of the encoder's own copy."""
    n = len(xs)

    def low(i):
        return max((j for j in range(i) if xs[j] < xs[i]), key=lambda j: xs[j])

    def high(i):
        return min((j for j in range(i) if xs[j] > xs[i]), key=lambda j: xs[j])

    def point(x0, y0, x1, y1, x):
        off = abs(y1 - y0) * (x - x0) // (x1 - x0)
        return y0 - off if y1 < y0 else y0 + off

    final, flag = [0] * n, [False] * n
    final[0], final[1] = vals[0], vals[1]
    flag[0] = flag[1] = True
    for i in range(2, n):
        lo, hi = low(i), high(i)
        p = point(xs[lo], final[lo], xs[hi], final[hi], xs[i])
        val, hr, lr = vals[i], rng - p, p
        room = min(hr, lr) * 2
        if val:
            flag[lo] = flag[hi] = flag[i] = True
            if val >= room:
                final[i] = val - lr + p if hr > lr else p - val + hr - 1
            else:
                final[i] = p - (val + 1) // 2 if val % 2 else p + val // 2
        else:
            final[i] = p
    curve = [None] * half

    def line(x0, y0, x1, y1):
        dy, adx = y1 - y0, x1 - x0
        base = int(dy / adx)
        sy = base - 1 if dy < 0 else base + 1
        ady = abs(dy) - abs(base) * adx
        y, err = y0, 0
        curve[x0] = y
        for x in range(x0 + 1, x1):
            err += ady
            if err >= adx:
                err -= adx
                y += sy
            else:
                y += base
            curve[x] = y

    order = sorted(range(n), key=lambda j: xs[j])
    lx, ly = 0, final[order[0]] * mult
    hx = 0
    for j in order[1:]:
        if flag[j]:
            line(lx, ly, xs[j], final[j] * mult)
            lx, ly, hx = xs[j], final[j] * mult, xs[j]
    return curve


if __name__ == "__main__":
    unittest.main()

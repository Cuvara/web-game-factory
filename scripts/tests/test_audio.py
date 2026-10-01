"""Audio as a production asset: build_spec.audio into the work list, the audio quality checks,
library import of WAV and Ogg with their licence, the runtime manifest's `audio` block, and
the production gate's audio.plays.

Every file is synthesized here with the standard library (a WAV through `wave`, an Ogg Opus
or Vorbis container with real page CRCs, MPEG audio frame headers): nothing is decoded that
this pipeline could not decode itself, and nothing touches the network.

    python -m unittest discover scripts/tests -p test_audio.py
"""

import io
import json
import math
import os
import struct
import sys
import tempfile
import unittest
import wave

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

from test_assets import AssetsCase  # noqa: E402
from wgf_assets import audiofile, quality, runtime  # noqa: E402
from wgf_assets.policy import load_policy  # noqa: E402
from wgf_assets.requirements import audio_duration, inspect  # noqa: E402
from wgf_production import checks as production  # noqa: E402
from wgflib import jsonschema_lite  # noqa: E402
from wgflib.yamllite import load_file  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(HERE))
RULES = load_file(os.path.join(ROOT, "core", "reference", "production-quality.yaml"))


def errors(document, schema):
    return [str(e) for e in jsonschema_lite.Validator(schema).iter_errors(document)]


# -- synthesized files -------------------------------------------------------------------------

def wav(seconds=1.0, *, freq=441.0, amp=0.5, rate=44100, channels=1, width=2, cut=0.0):
    """A sine WAV. `freq` 441 Hz completes whole cycles in any multiple of 1/441 s, so a 1 s
    file loops without a seam; `cut` drops that share of a cycle from the end (a seam)."""
    frames = int(seconds * rate) - int(cut * rate / freq)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(width)
        handle.setframerate(rate)
        peak = (1 << (8 * width - 1)) - 1
        data = bytearray()
        for i in range(frames):
            value = int(amp * peak * math.sin(2 * math.pi * freq * i / rate))
            data += value.to_bytes(width, "little", signed=True) * channels
        handle.writeframes(bytes(data))
    return buffer.getvalue()


def _page(serial, sequence, granule, flags, packets):
    lacing = []
    for packet in packets:
        size = len(packet)
        while size >= 255:
            lacing.append(255)
            size -= 255
        lacing.append(size)
    header = (b"OggS" + bytes([0, flags]) + struct.pack("<qIII", granule, serial, sequence, 0)
              + bytes([len(lacing)]) + bytes(lacing))
    page = bytearray(header + b"".join(packets))
    page[22:26] = struct.pack("<I", audiofile._ogg_crc(page))
    return bytes(page)


def ogg_opus(seconds=40.0, preskip=4152, channels=2):
    """An Ogg Opus container: OpusHead, OpusTags, audio pages ending at the granule that the
    end trim reads (the packets are filler: nothing here decodes Opus)."""
    head = b"OpusHead" + bytes([1, channels]) + struct.pack("<HIhB", preskip, 48000, 0, 0)
    tags = b"OpusTags" + struct.pack("<I", 4) + b"test" + struct.pack("<I", 0)
    total = preskip + int(seconds * 48000)
    pages = [_page(7, 0, 0, 0x02, [head]), _page(7, 1, 0, 0, [tags])]
    pages.append(_page(7, 2, total // 2, 0, [b"\xfc" * 60] * 20))
    pages.append(_page(7, 3, total, 0x04, [b"\xfc" * 60] * 20))
    return b"".join(pages)


def ogg_vorbis(seconds=0.5, rate=44100):
    ident = b"\x01vorbis" + struct.pack("<IBIiii", 0, 1, rate, 0, 96000, 0) + b"\xb8\x01"
    return _page(9, 0, 0, 0x02, [ident]) + _page(9, 1, int(seconds * rate), 0x04, [b"\0" * 40])


def mp3(frames=100):
    """MPEG-1 Layer III, 128 kb/s, 44.1 kHz, stereo: frames of 417 bytes, 1152 samples each."""
    header = bytes([0xFF, 0xFB, 0x90, 0x00])
    return (header + b"\0" * 413) * frames


# -- reading --------------------------------------------------------------------------------------

class Reading(unittest.TestCase):
    def test_a_wav_is_decoded_and_measured(self):
        info = audiofile.read(wav(1.0, amp=0.5))
        self.assertEqual((info.format, info.codec, info.channels, info.sample_rate),
                         ("wav", "pcm", 1, 44100))
        self.assertAlmostEqual(info.duration_s, 1.0, places=3)
        levels = audiofile.levels(info, 1.0)
        self.assertAlmostEqual(levels["rms_dbfs"], 20 * math.log10(0.5 / math.sqrt(2)), delta=0.2)
        self.assertAlmostEqual(levels["peak_dbfs"], 20 * math.log10(0.5), delta=0.1)

    def test_a_seamless_loop_and_a_cut_one(self):
        whole = audiofile.seam(audiofile.read(wav(1.0)))
        cut = audiofile.seam(audiofile.read(wav(1.0, cut=0.25)))
        self.assertLess(whole["ratio"], 2)
        self.assertGreater(cut["ratio"], 8)

    def test_float_and_24_bit_wavs(self):
        info = audiofile.read(wav(0.2, width=3, channels=2))
        self.assertEqual((info.channels, info.notes), (2, ["24-bit PCM"]))
        samples = struct.pack("<" + "f" * 4410, *[0.25] * 4410)
        fmt = struct.pack("<HHIIHH", 3, 1, 44100, 44100 * 4, 4, 32)
        body = b"WAVE" + b"fmt " + struct.pack("<I", 16) + fmt + b"data" + \
            struct.pack("<I", len(samples)) + samples
        info = audiofile.read(b"RIFF" + struct.pack("<I", len(body)) + body)
        self.assertEqual(info.codec, "float")
        self.assertAlmostEqual(audiofile.levels(info)["rms_dbfs"], 20 * math.log10(0.25), delta=0.01)

    def test_ogg_opus_duration_is_the_end_trim_less_the_pre_skip(self):
        info = audiofile.read(ogg_opus(40.0, preskip=4152))
        self.assertEqual((info.format, info.codec, info.channels, info.sample_rate),
                         ("ogg", "opus", 2, 48000))
        self.assertAlmostEqual(info.duration_s, 40.0, places=4)
        self.assertIsNone(info.samples)

    def test_ogg_vorbis_header(self):
        info = audiofile.read(ogg_vorbis(0.5))
        self.assertEqual((info.codec, info.channels, info.sample_rate), ("vorbis", 1, 44100))
        self.assertAlmostEqual(info.duration_s, 0.5, places=3)

    def test_a_corrupt_ogg_page_is_refused(self):
        data = bytearray(ogg_opus(5.0))
        data[-5] ^= 0xFF
        with self.assertRaisesRegex(audiofile.AudioError, "CRC"):
            audiofile.read(bytes(data))

    def test_mp3_frames_are_counted(self):
        info = audiofile.read(b"ID3" + bytes([4, 0, 0, 0, 0, 0, 0]) + mp3(100))
        self.assertEqual((info.format, info.channels, info.sample_rate), ("mp3", 2, 44100))
        self.assertAlmostEqual(info.duration_s, 100 * 1152 / 44100, places=3)

    def test_not_audio(self):
        with self.assertRaises(audiofile.AudioError):
            audiofile.read(b"\x89PNG\r\n\x1a\n" + b"\0" * 64)


# -- quality --------------------------------------------------------------------------------------

def check(judged, check_id):
    return next(c for c in judged["checks"] if c["id"] == check_id)


class AudioQuality(unittest.TestCase):
    def setUp(self):
        self.bars = quality.load_bars()

    def judge(self, data, **kw):
        kw.setdefault("kind", "sfx")
        kw.setdefault("license_ok", True)
        kw.setdefault("max_bytes", 262144)
        return quality.audio_quality(data, bars=self.bars, **kw)

    def test_bars_are_read_from_the_reference(self):
        audio = self.bars.audio
        self.assertEqual((audio.window_s, audio.min_rms_dbfs, audio.music_min_s, audio.sfx_max_s),
                         (2.0, -45.0, 30.0, 6.0))

    def test_a_good_one_shot_passes(self):
        judged = self.judge(wav(0.4))
        self.assertEqual(judged["verdict"], "pass", judged)
        self.assertEqual({c["id"] for c in judged["checks"]},
                         {"audio.decodes", "audio.duration", "audio.not-silent", "audio.size",
                          "audio.licence"})

    def test_silence_fails(self):
        judged = self.judge(wav(0.4, amp=0.001))
        self.assertEqual(check(judged, "audio.not-silent")["status"], "fail")

    def test_music_must_be_long_enough_and_meet_itself(self):
        short = self.judge(wav(2.0), kind="music", loop=True, max_bytes=4194304)
        self.assertEqual(check(short, "audio.duration")["status"], "fail")
        self.assertEqual(check(short, "audio.loop-seam")["status"], "pass")
        stated = self.judge(wav(2.0), kind="sfx", loop=True, min_duration_s=3)
        self.assertEqual(check(stated, "audio.duration")["status"], "fail")
        seam = self.judge(wav(1.0, cut=0.25), kind="sfx", loop=True)
        self.assertEqual(check(seam, "audio.loop-seam")["status"], "fail")

    def test_a_one_shot_that_is_really_music_fails(self):
        judged = self.judge(wav(8.0, rate=8000), max_bytes=None)
        self.assertEqual(check(judged, "audio.duration")["status"], "fail")

    def test_size_and_licence(self):
        judged = self.judge(wav(0.4), max_bytes=1000, license_ok=False)
        self.assertEqual(check(judged, "audio.size")["status"], "fail")
        self.assertEqual(check(judged, "audio.licence")["status"], "fail")
        self.assertEqual(judged["verdict"], "fail")

    def test_compressed_music_is_judged_by_its_headers(self):
        judged = self.judge(ogg_opus(64.0), kind="music", loop=True, max_bytes=4194304)
        self.assertEqual(judged["verdict"], "pass", judged)
        self.assertEqual(check(judged, "audio.not-silent")["status"], "skipped")
        self.assertEqual(check(judged, "audio.loop-seam")["status"], "skipped")
        self.assertIn("audio.plays", check(judged, "audio.not-silent")["summary"])

    def test_an_unreadable_file_fails_to_decode(self):
        judged = self.judge(b"RIFF\0\0\0\0WAVEjunk")
        self.assertEqual(judged["verdict"], "fail")
        self.assertEqual(judged["checks"][0]["id"], "audio.decodes")


# -- requirements -----------------------------------------------------------------------------------

AUDIO = [
    {"id": "music-loop", "type": "music", "tier": "mvp", "description": "Play loop of at least 60 s",
     "trigger": "Run start", "loop": True, "source_preference": "library", "est_cost": 40},
    {"id": "sfx-hit", "type": "sfx", "tier": "mvp", "description": "Impact", "trigger": "Crash",
     "loop": False, "source_preference": "library", "est_cost": 5},
    {"id": "ui-tap", "type": "ui", "tier": "mvp", "description": "Button press",
     "trigger": "Any button", "loop": False, "source_preference": "library", "est_cost": 5},
    {"id": "amb-wind", "type": "ambience", "tier": "post-mvp", "description": "Wind bed",
     "trigger": "Always", "loop": True, "source_preference": "procedural", "est_cost": 0},
]


class Bridge(unittest.TestCase):
    def setUp(self):
        self.policy = load_policy()

    def test_build_spec_audio_joins_the_work_list(self):
        design = {"build_spec": {"assets": [
            {"id": "hero", "type": "sprite", "tier": "mvp", "description": "Hero", "role": "player",
             "count": 1, "source_preference": "procedural", "est_cost": 0, "spec": "64px"}],
            "audio": AUDIO}}
        reqs = {r.id: r for r in inspect(design, self.policy)[0]}
        self.assertEqual(set(reqs), {"hero", "music-loop", "sfx-hit", "ui-tap", "amb-wind"})
        music = reqs["music-loop"]
        self.assertEqual((music.kind, music.manifest_type, music.loop, music.min_duration_s,
                          music.trigger, music.scope_tier), ("music", "music", True, 60.0,
                                                             "Run start", "mvp"))
        self.assertEqual((reqs["ui-tap"].kind, reqs["ui-tap"].role), ("sfx", "ui"))
        self.assertEqual(reqs["amb-wind"].kind, "music")
        self.assertFalse(reqs["amb-wind"].generate_now(), "post-mvp waits for G4")
        self.assertTrue(reqs["sfx-hit"].generate_now())
        self.assertFalse(reqs["sfx-hit"].placeholder_only)

    def test_audio_is_bridged_beside_a_legacy_list_too(self):
        design = {"asset_requirements": [{"id": "bg", "kind": "background"}],
                  "build_spec": {"audio": AUDIO[:2]}}
        ids = [r.id for r in inspect(design, self.policy)[0]]
        self.assertEqual(ids, ["bg", "music-loop", "sfx-hit"])

    def test_an_id_an_asset_already_uses_is_not_repeated(self):
        design = {"build_spec": {"assets": [
            {"id": "sfx-hit", "type": "sprite", "tier": "mvp", "description": "x", "role": "vfx",
             "count": 1, "source_preference": "procedural", "est_cost": 0}],
            "audio": AUDIO[1:2]}}
        reqs = inspect(design, self.policy)[0]
        self.assertEqual([(r.id, r.kind) for r in reqs], [("sfx-hit", "vfx")])

    def test_stated_lengths(self):
        self.assertEqual(audio_duration("a 60 s loop"), 60.0)
        self.assertEqual(audio_duration("0.5 sec whoosh"), 0.5)
        self.assertEqual(audio_duration("at least 30 seconds"), 30.0)
        self.assertIsNone(audio_duration("Driving loop"))


# -- the pipeline: a library of audio, imported with its licence ----------------------------------

class LibraryAudio(AssetsCase):
    def library(self, items, files):
        directory = tempfile.mkdtemp(prefix="wgf-audio-lib-", dir=self.scratch)
        for relative, data in files.items():
            path = os.path.join(directory, relative)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as handle:
                handle.write(data)
        with open(os.path.join(directory, "library.json"), "w") as handle:
            json.dump({"library": {"id": "audio-lib"}, "items": items}, handle)
        return directory

    def audio_design(self):
        return self.design(requirements=[{"id": "bg", "kind": "background"}],
                           build_spec={"audio": AUDIO[:3]})

    def test_music_and_sfx_are_imported_judged_and_listed_for_the_runtime(self):
        lib = self.library(
            [{"requirement": "music-loop", "files": ["audio/loop.ogg"], "license": "CC0-1.0",
              "source": "https://example.invalid/loop", "author": "Composer"},
             {"requirement": "sfx-hit", "files": ["audio/hit.wav"], "license": "CC0-1.0",
              "source": "studio session 4", "author": "Foley"},
             {"requirement": "ui-tap", "files": ["audio/tap.wav"], "license": "CC0-1.0",
              "author": "Foley"}],
            {"audio/loop.ogg": ogg_opus(64.0), "audio/hit.wav": wav(0.5),
             "audio/tap.wav": wav(0.08, freq=1200)})
        manifest = self.manifest(self.audio_design(), libraries=[lib])
        items = self.items(manifest)
        music, hit, tap = items["music-loop"], items["sfx-hit"], items["ui-tap"]
        for item in (music, hit, tap):
            self.assertEqual((item["status"], item["source"], item["license"]),
                             ("delivered", "library", "CC0-1.0"), item)
            self.assertEqual(item["quality"]["verdict"], "pass", item["quality"])
            self.assertTrue(item["production_ready"])
        self.assertEqual(music["type"], "music")
        self.assertEqual(music["files"][0]["path"], "public/assets/audio/music-loop.ogg")
        self.assertEqual(tap["role"], "ui")
        self.assertIn("audio.loop-seam", {c["id"] for c in music["quality"]["checks"]})
        with open(os.path.join(self.root, runtime.RUNTIME_PATH)) as handle:
            document = json.load(handle)
        entry = document["assets"]["music-loop"]
        self.assertEqual(entry["type"], "music")
        self.assertEqual(entry["url"], "audio/music-loop.ogg")
        self.assertEqual(entry["audio"], {"loop": True, "duration_s": 64.0, "channels": 2,
                                          "sample_rate": 48000})
        self.assertEqual(document["assets"]["sfx-hit"]["audio"]["loop"], False)
        self.assertEqual(errors(document, runtime.load_schema()), [])
        problems = [i for i in runtime.validate(self.root) if i["severity"] == "error"]
        self.assertEqual(problems, [])

    def test_a_short_music_file_fails_its_quality_and_is_not_production_ready(self):
        lib = self.library(
            [{"requirement": "music-loop", "files": ["audio/loop.ogg"], "license": "CC0-1.0",
              "author": "Composer"}],
            {"audio/loop.ogg": ogg_opus(12.0)})
        manifest = self.manifest(self.audio_design(), libraries=[lib])
        music = self.items(manifest)["music-loop"]
        self.assertEqual(music["quality"]["verdict"], "fail")
        self.assertFalse(music["production_ready"])
        self.assertIn(("quality-failed", "error"), self.codes(manifest, "music-loop"))

    def test_without_a_library_the_audio_is_a_placeholder_never_judged(self):
        manifest = self.manifest(self.audio_design())
        music = self.items(manifest)["music-loop"]
        self.assertTrue(music["placeholder"])
        self.assertEqual(music["quality"]["verdict"], "skipped")


# -- production: audio.plays -------------------------------------------------------------------------

def records(levels=(0.1, 0.12), muted=(0.0, 0.0), music="music-loop", probe=True,
            fetched=True):
    samples = [{"ms": 100 * i, "state": "playing", "music": music, "playing": True,
                "level": level, "muted": False} for i, level in enumerate(levels)]
    return {"desktop": {"first-session": {
        "audio": samples if probe else [],
        "audio_unfocused": [{"ms": 700, "level": level, "muted": True, "playing": False}
                            for level in muted],
        "asset_requests": [{"url": "/assets/audio/music-loop.ogg", "status": 200}] if fetched else [],
        "runtime_assets": {"assets": {"music-loop": {"type": "music", "url": "audio/music-loop.ogg"}}},
    }}}


MANIFEST = {"items": [{"id": "music-loop", "type": "music", "status": "delivered",
                       "scope_tier": "mvp", "placeholder": False,
                       "files": [{"path": "public/assets/audio/music-loop.ogg"}]}]}
DESIGN = {"build_spec": {"audio": AUDIO[:1]}}


class AudioPlays(unittest.TestCase):
    def judge(self, recs, manifest=MANIFEST, design=DESIGN):
        return production.audio_plays(recs, manifest, design, RULES)

    def test_heard_and_silent_when_muted(self):
        result = self.judge(records())
        self.assertEqual(result["status"], "PASS", result)
        self.assertEqual(result["measured"]["music_heard"], ["music-loop"])
        self.assertEqual(result["expected"], {"min_level": 0.005, "max_muted_level": 0.001})

    def test_no_music_in_the_design_is_no_check(self):
        self.assertIsNone(self.judge(records(), manifest={"items": []}, design={}))

    def test_a_probe_without_audio_routes_develop(self):
        result = self.judge(records(probe=False))
        self.assertEqual((result["status"], result["route"]), ("FAIL", "develop"))
        self.assertIn("no `audio`", result["summary"])

    def test_too_quiet_unfetched_or_leaking_through_the_mute(self):
        quiet = self.judge(records(levels=(0.001, 0.002)))
        self.assertEqual((quiet["status"], quiet["route"]), ("FAIL", "develop"))
        unfetched = self.judge(records(fetched=False))
        self.assertIn("never fetched", unfetched["summary"])
        leaking = self.judge(records(muted=(0.0, 0.05)))
        self.assertEqual(leaking["status"], "FAIL")
        self.assertIn("unfocused", leaking["summary"])

    def test_music_that_was_never_delivered_routes_assets(self):
        manifest = {"items": [dict(MANIFEST["items"][0], placeholder=True)]}
        result = self.judge(records(), manifest=manifest)
        self.assertEqual((result["status"], result["route"]), ("FAIL", "assets"))

    def test_judge_reports_it_beside_the_asset_checks(self):
        found = production.judge(records(), MANIFEST, DESIGN, RULES, {})
        self.assertIn("audio.plays", [c["id"] for c in found])
        schema_path = os.path.join(ROOT, "core", "artifacts", "production-quality-report.schema.json")
        with open(schema_path) as handle:
            item_schema = json.load(handle)["properties"]["checks"]["items"]
        audio = next(c for c in found if c["id"] == "audio.plays")
        self.assertEqual(errors(audio, item_schema), [])


class ProbeSchema(unittest.TestCase):
    def test_the_audio_field_is_additive(self):
        with open(os.path.join(ROOT, "core", "artifacts", "shared", "play-probe.schema.json")) as h:
            schema = json.load(h)
        base = {"state": "playing", "metrics": {}, "entities": [], "inputs": []}
        self.assertEqual(errors(base, schema), [])
        with_audio = dict(base, audio={"music": "music-loop", "playing": True, "level": 0.12,
                                       "muted": False})
        self.assertEqual(errors(with_audio, schema), [])
        bad = dict(base, audio={"music": None, "playing": True, "level": -1})
        self.assertNotEqual(errors(bad, schema), [])


if __name__ == "__main__":
    unittest.main()

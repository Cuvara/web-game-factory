"""The audio producer: a design's music and sound effects, composed and rendered here.

    producer = AudioProducer(design, title_id)
    producer.supports(req)  -> a `music` or `sfx` requirement
    producer.produce(req)   -> {files, license, origin, notes, metadata, author, done}

One song per design (style.brief_for -> music.Song): each music requirement is a cue of it -
`title` for a title/menu/calm variant, `layer` for an intensity layer (then the loop it
layers is rendered as `base`, and both have the same bars), `ambience` for an ambience
entry, `main` otherwise - lasting at least the duration its description states (60 s for a
main loop, 30 s for anything else, when none is stated). Music is 44.1 kHz stereo, a
seamless loop, encoded as Ogg Vorbis by the standard-library encoder (vorbis.py); sound
effects are 44.1 kHz mono 16-bit WAV (sfx.py). Everything is made here from the design's
words, so the licence is the Factory's own (LicenseRef-factory-generated) and nothing is
sourced from anyone else.

`WGF_AUDIO_ENCODER=wav` ships music as 16-bit WAV instead of Vorbis (bigger; for a host
whose decoder is in doubt). The measured stats of the rendered PCM (duration, RMS, peak,
loudness, seam) go to the manifest item's generation record, since an Ogg file is not
decoded by the asset quality checks.
"""

import array
import hashlib
import os
import re
import struct

from ..fontlib import ProducerError
from ..policy import GENERATED_LICENSE
from . import measure, music, sfx, style, vorbis

__all__ = ["AudioProducer", "ProducerError", "wav_bytes", "cue_kind"]

RATE = 44100
GENERATOR = "wgf-composer"


def _words(text):
    return set(re.findall(r"[a-z][a-z0-9-]*", (text or "").lower()))


def _id_words(asset_id):
    parts = [p for p in (asset_id or "").lower().split("-") if p]
    words = set(parts)
    words.update("-".join(parts[i:i + 2]) for i in range(len(parts) - 1))
    return words


def cue_kind(req, companions=()):
    """main | layer | title | ambience for a music requirement."""
    words = _id_words(req.id) | _words(req.description) | _words(req.label)
    if req.design_type == "ambience" or "ambience" in words or "ambient" in words:
        return "ambience"
    if words & {"layer", "intensity-layer", "stem"} and any(c != req.id for c in companions):
        return "layer"
    if words & {"title", "menu", "lobby", "calm", "calmer", "pause", "results", "intro"}:
        return "title"
    return "main"


def wav_bytes(channels, rate, *, seed=0):
    """16-bit PCM WAV of float channels, with TPDF dither (seeded: same input, same bytes)."""
    n = len(channels[0])
    state = (seed * 2654435761 + 12345) & 0xFFFFFFFF
    frames = array.array("h", bytes(2 * n * len(channels)))
    k = 0
    for i in range(n):
        for c in channels:
            state = (1103515245 * state + 12345) & 0x7FFFFFFF
            d1 = state / 0x7FFFFFFF
            state = (1103515245 * state + 12345) & 0x7FFFFFFF
            d2 = state / 0x7FFFFFFF
            v = int(round(c[i] * 32767.0 + (d1 - d2)))
            frames[k] = 32767 if v > 32767 else (-32768 if v < -32768 else v)
            k += 1
    if array.array("h", [1]).tobytes() != b"\x01\x00":
        frames.byteswap()
    data = frames.tobytes()
    ch = len(channels)
    fmt = struct.pack("<HHIIHH", 1, ch, rate, rate * ch * 2, ch * 2, 16)
    body = b"WAVE" + b"fmt " + struct.pack("<I", len(fmt)) + fmt + b"data" + \
        struct.pack("<I", len(data)) + data
    return b"RIFF" + struct.pack("<I", len(body)) + body


class AudioProducer:
    id = "composer"
    source = "procedural"

    def __init__(self, design, title_id=None, *, encoder=None, logger=None):
        self.design = design or {}
        self.brief = style.brief_for(self.design, title_id=title_id)
        self.song = music.Song(self.brief)
        self.encoder = (encoder or os.environ.get("WGF_AUDIO_ENCODER") or "vorbis").lower()
        self.logger = logger
        spec = self.design.get("build_spec") if isinstance(
            self.design.get("build_spec"), dict) else {}
        self.music_ids = [a.get("id") for a in spec.get("audio") or []
                          if isinstance(a, dict) and a.get("type") in ("music", "ambience")]
        self._bars = {}

    def supports(self, req):
        return req.kind in ("music", "sfx")

    def _log(self, message, **fields):
        if self.logger:
            self.logger.info(message, **fields)

    def produce(self, req):
        if req.kind == "music":
            return self._music(req)
        return self._sfx(req)

    def _common(self, req, made, fmt, info, stats, done):
        brief = self.brief.describe()
        return {
            "files": [{"data": made, "format": fmt}],
            "license": GENERATED_LICENSE,
            "origin": {"kind": "generated", "generator": GENERATOR},
            "author": f"builtin:{self.id}",
            "done": done,
            "notes": (f"Composed for this design: {brief['summary']}; {brief['key']} "
                      f"{brief['mode']}, {info.get('tempo_bpm', brief['tempo_bpm'])} BPM. "
                      + (f"{info['kind']} cue, {info['bars']} bars, {info['seconds']} s, "
                         f"a seamless loop." if req.kind == "music" else
                         f"'{info['recipe']}' effect on the {info['instrument']} voice, "
                         f"{info['seconds']} s.")),
            "metadata": {"producer": self.id, "brief": brief, "cue": info,
                         "measured": stats},
        }

    def _music(self, req):
        kind = cue_kind(req, self.music_ids)
        seconds = float(req.min_duration_s or (60.0 if kind == "main" else 30.0))
        bars = None
        if kind == "layer":
            base = self._companion(req)
            if base is not None:
                bars = self._bars.get(base) or music.plan(
                    self.song, self._seconds_of(base), RATE)[0]
        elif kind == "main" and any(cue_kind(_Fake(i, self.design), self.music_ids) == "layer"
                                    for i in self.music_ids if i != req.id):
            kind = "base"
        self._log("composing", asset=req.id, cue=kind, seconds=seconds)
        left, right, info = music.render_cue(self.song, kind, seconds, RATE, bars=bars)
        self._bars[req.id] = info["bars"]
        stats = measure.stats([left, right], RATE, loop=True)
        stats["bands"] = measure.bands([left, right], RATE)
        if self.encoder == "wav":
            return self._common(req, wav_bytes([left, right], RATE, seed=self.brief.seed),
                                "wav", info, stats, [])
        try:
            data = vorbis.encode([left, right], RATE, loop=True, smr_db=25.0,
                                 comment=f"TITLE={req.id}")
        except vorbis.VorbisError as exc:
            self._log("vorbis failed; shipping WAV", asset=req.id, problem=str(exc))
            return self._common(req, wav_bytes([left, right], RATE, seed=self.brief.seed),
                                "wav", info, stats, [])
        return self._common(req, data, "ogg", info, stats, ["audio-transcode"])

    def _companion(self, req):
        """The loop a layer layers: the music id it names without '-layer', else the first
        main cue."""
        stem = re.sub(r"-?(intensity-)?layer$", "", req.id)
        if stem in self.music_ids and stem != req.id:
            return stem
        for other in self.music_ids:
            if other != req.id and cue_kind(_Fake(other, self.design), self.music_ids) == "main":
                return other
        return None

    def _seconds_of(self, asset_id):
        entry = _entry(self.design, asset_id) or {}
        from ..requirements import audio_duration
        return float(audio_duration(entry.get("description")) or 60.0)

    def _sfx(self, req):
        words = _id_words(req.id) | _words(req.description) | _words(req.label) | \
            _words(req.trigger)
        seed = int.from_bytes(hashlib.sha256(req.id.encode()).digest()[:2], "big")
        samples, info = sfx.render_sfx(words, self.song, RATE, loop=req.loop, seed=seed,
                                       primary=_id_words(req.id))
        stats = measure.stats([samples], RATE, loop=req.loop, loudness=False)
        return self._common(req, wav_bytes([samples], RATE, seed=seed), "wav", info, stats, [])


def _entry(design, asset_id):
    spec = design.get("build_spec") if isinstance(design.get("build_spec"), dict) else {}
    for a in spec.get("audio") or []:
        if isinstance(a, dict) and a.get("id") == asset_id:
            return a
    return None


class _Fake:
    """Enough of a Requirement for cue_kind, from a build_spec.audio entry."""

    def __init__(self, asset_id, design):
        entry = _entry(design, asset_id) or {}
        self.id = asset_id
        self.description = entry.get("description")
        self.label = entry.get("description")
        self.design_type = entry.get("type")

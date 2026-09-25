"""Byte-exact encoders for placeholder assets: PNG, WAV, GLB and glTF material JSON.

Standard library only, and deterministic: the same arguments always give the same bytes,
which is what makes a re-executed step find the files it wrote before instead of rewriting
them. Nothing here is meant to look good; it is meant to be a valid file of the right shape,
size and format, so the game can load it and the pipeline can check it.
"""

import json
import math
import struct
import zlib

__all__ = ["png", "wav", "glb", "material_json", "atlas_json", "colour_for"]


def colour_for(key):
    """A stable, mid-saturation RGB colour for a string, so placeholders are tellable apart."""
    digest = zlib.crc32(key.encode("utf-8"))
    hue = (digest % 360) / 360.0
    # HSV -> RGB at s=0.55, v=0.85: bright enough to read against a dark or light scene.
    s, v = 0.55, 0.85
    i = int(hue * 6)
    f = hue * 6 - i
    p, q, t = v * (1 - s), v * (1 - f * s), v * (1 - (1 - f) * s)
    r, g, b = [(v, t, p), (q, v, p), (p, v, t), (p, q, v), (t, p, v), (v, p, q)][i % 6]
    return int(r * 255), int(g * 255), int(b * 255)


def _chunk(kind, data):
    body = kind + data
    return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)


def png(width, height, colour, *, checker=0, frames=1, border=True):
    """An RGBA PNG: a solid `colour`, a darker 1px border per frame, and optionally a
    `checker`-pixel checkerboard (textures, so tiling and mip seams are visible)."""
    r, g, b = colour
    dark = (r // 2, g // 2, b // 2, 255)
    light = (r, g, b, 255)
    alt = (min(255, r + 40), min(255, g + 40), min(255, b + 40), 255)
    frame_w = max(1, width // max(1, frames))
    # A row depends only on whether it is a border row and on its checker parity, so build
    # each distinct row once: a 960x540 background would otherwise be half a million
    # Python-level pixel writes.
    cache = {}
    rows = []
    for y in range(height):
        edge = border and (y == 0 or y == height - 1)
        parity = (y // checker) % 2 if checker else 0
        key = (edge, parity)
        if key not in cache:
            row = bytearray([0])  # filter type 0 (None) per scanline
            for x in range(width):
                fx = x % frame_w
                if edge or (border and (fx == 0 or fx == frame_w - 1)):
                    pixel = dark
                elif checker and ((x // checker) + parity) % 2:
                    pixel = alt
                else:
                    pixel = light
                row.extend(pixel)
            cache[key] = bytes(row)
        rows.append(cache[key])
    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", header)
            + _chunk(b"IDAT", zlib.compress(b"".join(rows), 9)) + _chunk(b"IEND", b""))


def wav(seconds, frequency, *, rate=8000):
    """Mono 8-bit PCM: a sine tone with a linear fade out, so it is audibly a placeholder."""
    count = max(1, int(seconds * rate))
    samples = bytearray()
    for n in range(count):
        envelope = 1.0 - n / count
        value = math.sin(2 * math.pi * frequency * n / rate) * envelope * 0.5
        samples.append(int(round(128 + value * 127)) & 0xFF)
    return _riff(bytes(samples), rate)



# -- shaped procedural audio ---------------------------------------------------------------
#
# A small jsfxr-style synthesiser: one oscillator (square, saw, sine or noise), an
# attack/sustain/decay envelope, a pitch slide, vibrato and one arpeggio step, rendered mono
# 8-bit PCM. Deterministic - noise comes from a seeded LCG, never from `random` - so the same
# request always yields the same bytes and a golden run's package digests reproduce. Still a
# placeholder: shaped so a playtest can hear a reward from a failure, not final audio.

SYNTH_RATE = 22050

# duration_s, wave, start_hz, end_hz, attack_s, sustain_s, vibrato (hz, depth), arp (at_s, x),
# lowpass (0 = off; 0..1, lower is darker), volume
SFX_PRESETS = {
    "blip":    dict(wave="square", start=880, end=880, dur=0.09, attack=0.002, sustain=0.03),
    "ui":      dict(wave="square", start=1320, end=990, dur=0.06, attack=0.001, sustain=0.01,
                    volume=0.35),
    "jump":    dict(wave="square", start=300, end=720, dur=0.2, attack=0.005, sustain=0.05),
    "coin":    dict(wave="square", start=988, end=988, dur=0.22, attack=0.002, sustain=0.06,
                    arp=(0.06, 4 / 3)),
    "powerup": dict(wave="square", start=392, end=1175, dur=0.5, attack=0.01, sustain=0.2,
                    vibrato=(12.0, 0.03)),
    "hit":     dict(wave="noise", start=900, end=120, dur=0.22, attack=0.001, sustain=0.02,
                    lowpass=0.35),
    "whoosh":  dict(wave="noise", start=300, end=1400, dur=0.32, attack=0.12, sustain=0.05,
                    lowpass=0.12, volume=0.5),
    "lose":    dict(wave="saw", start=440, end=110, dur=0.7, attack=0.01, sustain=0.25,
                    vibrato=(6.0, 0.05)),
}


def _lcg(seed):
    state = (seed * 2654435761 + 1) & 0xFFFFFFFF
    while True:
        state = (1103515245 * state + 12345) & 0x7FFFFFFF
        yield state / 0x3FFFFFFF - 1.0


def _pcm8(values):
    return bytes(max(0, min(255, int(round(128 + v * 127)))) for v in values)


def _riff(data, rate):
    fmt = struct.pack("<HHIIHH", 1, 1, rate, rate, 1, 8)
    body = b"WAVE" + b"fmt " + struct.pack("<I", len(fmt)) + fmt
    body += b"data" + struct.pack("<I", len(data)) + data
    if len(data) % 2:
        body += b"\x00"
    return b"RIFF" + struct.pack("<I", len(body)) + body


def _oscillator(wave, phase):
    if wave == "square":
        return 1.0 if phase < 0.5 else -1.0
    if wave == "saw":
        return 2.0 * phase - 1.0
    return math.sin(2 * math.pi * phase)


def synth(preset, variant=0, *, rate=SYNTH_RATE):
    """One shaped sound effect as a WAV. `variant` detunes it slightly (at most about 7%),
    so two requests on the same preset never produce the same bytes."""
    p = SFX_PRESETS[preset]
    detune = 1.0 + ((variant % 15) - 7) * 0.01
    count = max(1, int(p["dur"] * rate))
    attack = max(1, int(p.get("attack", 0.0) * rate))
    sustain = int(p.get("sustain", 0.0) * rate)
    vibrato_hz, vibrato_depth = p.get("vibrato", (0.0, 0.0))
    arp_at, arp_x = p.get("arp", (None, 1.0))
    lowpass = p.get("lowpass", 0.0)
    volume = p.get("volume", 0.45)
    noise = _lcg(variant + 1)
    phase, smoothed, held, values = 0.0, 0.0, 0.0, []
    for n in range(count):
        t = n / rate
        progress = n / count
        freq = (p["start"] * (p["end"] / p["start"]) ** progress) * detune
        if arp_at is not None and t >= arp_at:
            freq *= arp_x
        if vibrato_depth:
            freq *= 1.0 + vibrato_depth * math.sin(2 * math.pi * vibrato_hz * t)
        phase += freq / rate
        if p["wave"] == "noise":
            # Noise is held and re-sampled at the slid frequency: a falling "pitch" reads
            # as a thud, a rising one as a whoosh.
            if n == 0 or phase >= 1.0:
                held = next(noise)
            sample = held
        else:
            sample = _oscillator(p["wave"], phase % 1.0)
        phase %= 1.0
        if lowpass:
            smoothed += lowpass * (sample - smoothed)
            sample = smoothed
        if n < attack:
            envelope = n / attack
        elif n < attack + sustain:
            envelope = 1.0
        else:
            envelope = max(0.0, 1.0 - (n - attack - sustain) / max(1, count - attack - sustain))
        values.append(sample * envelope * volume)
    return _riff(_pcm8(values), rate)


# Four chords (root offsets in semitones from A2) under an arpeggio: i - VI - III - VII.
_PROGRESSION = ((0, (0, 3, 7)), (-4, (0, 4, 7)), (3, (0, 4, 7)), (-2, (0, 4, 7)))


def music_loop(variant=0, *, rate=SYNTH_RATE, seconds=8.0, bpm=120):
    """A short, seamless placeholder loop: a square bass and an eighth-note arpeggio over
    four chords. `variant` transposes it (0-4 semitones) so two music items differ."""
    count = int(seconds * rate)
    per_chord = count // len(_PROGRESSION)
    eighth = int(rate * 60 / bpm / 2)
    shift = variant % 5
    values = []
    bass_phase = arp_phase = 0.0
    for n in range(count):
        index = min(len(_PROGRESSION) - 1, n // per_chord)
        root, chord = _PROGRESSION[index]
        step = (n % per_chord) // eighth
        note = root + shift + chord[step % len(chord)] + 12 * (1 + (step // len(chord)) % 2)
        bass_hz = 110.0 * 2 ** ((root + shift) / 12)
        arp_hz = 110.0 * 2 ** (note / 12)
        bass_phase = (bass_phase + bass_hz / rate) % 1.0
        arp_phase = (arp_phase + arp_hz / rate) % 1.0
        in_note = (n % eighth) / eighth
        arp_env = max(0.0, 1.0 - in_note * 1.6)
        bass = (1.0 if bass_phase < 0.5 else -1.0) * 0.18
        arp = (1.0 if arp_phase < 0.25 else -1.0) * 0.16 * arp_env
        values.append(bass + arp)
    return _riff(_pcm8(values), rate)


# -- glTF ----------------------------------------------------------------------------------

def _box(sx, sy, sz, ox=0.0, oy=0.0, oz=0.0):
    positions = []
    for x in (-sx, sx):
        for y in (-sy, sy):
            for z in (-sz, sz):
                positions.append((x / 2 + ox, y / 2 + oy, z / 2 + oz))
    # Two triangles per face, indices into the 8 corners above (x-major, then y, then z).
    faces = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    indices = []
    for a, b, c, d in faces:
        indices += [a, b, c, a, c, d]
    return positions, indices


def _plane(size):
    h = size / 2
    return [(-h, 0.0, -h), (h, 0.0, -h), (h, 0.0, h), (-h, 0.0, h)], [0, 2, 1, 0, 3, 2]


def glb(name, colour, *, shape="box", animated=False, generator="wgf-assets"):
    """A binary glTF 2.0 file: one box (a model), a ground plane plus a box (an environment),
    or a box with a one-second translation clip (an animation)."""
    meshes_src = [_box(1.0, 1.0, 1.0, oy=0.5)]
    if shape == "environment":
        meshes_src = [_plane(20.0), _box(2.0, 2.0, 2.0, ox=3.0, oy=1.0)]

    binary = bytearray()
    views, accessors, meshes, nodes = [], [], [], []

    def add_view(data, target):
        while len(binary) % 4:
            binary.append(0)
        views.append({"buffer": 0, "byteOffset": len(binary), "byteLength": len(data),
                      **({"target": target} if target else {})})
        binary.extend(data)
        return len(views) - 1

    r, g, b = (c / 255 for c in colour)
    material = {"name": f"{name}-material", "pbrMetallicRoughness": {
        "baseColorFactor": [round(r, 4), round(g, 4), round(b, 4), 1],
        "metallicFactor": 0, "roughnessFactor": 1}}

    for index, (positions, indices) in enumerate(meshes_src):
        pos_bytes = b"".join(struct.pack("<fff", *p) for p in positions)
        idx_bytes = b"".join(struct.pack("<H", i) for i in indices)
        pos_view = add_view(pos_bytes, 34962)
        idx_view = add_view(idx_bytes, 34963)
        accessors.append({
            "bufferView": pos_view, "componentType": 5126, "count": len(positions),
            "type": "VEC3",
            "min": [min(p[k] for p in positions) for k in range(3)],
            "max": [max(p[k] for p in positions) for k in range(3)],
        })
        accessors.append({"bufferView": idx_view, "componentType": 5123,
                          "count": len(indices), "type": "SCALAR"})
        meshes.append({"name": f"{name}-{index}", "primitives": [{
            "attributes": {"POSITION": len(accessors) - 2}, "indices": len(accessors) - 1,
            "material": 0}]})
        nodes.append({"name": f"{name}-{index}", "mesh": index})

    document = {
        "asset": {"version": "2.0", "generator": generator},
        "scene": 0,
        "scenes": [{"name": name, "nodes": list(range(len(nodes)))}],
        "nodes": nodes,
        "meshes": meshes,
        "materials": [material],
        "accessors": accessors,
        "bufferViews": views,
    }

    if animated:
        times = struct.pack("<ff", 0.0, 1.0)
        moves = struct.pack("<ffffff", 0.0, 0.0, 0.0, 0.0, 1.0, 0.0)
        t_view = add_view(times, None)
        accessors.append({"bufferView": t_view, "componentType": 5126, "count": 2,
                          "type": "SCALAR", "min": [0.0], "max": [1.0]})
        m_view = add_view(moves, None)
        accessors.append({"bufferView": m_view, "componentType": 5126, "count": 2,
                          "type": "VEC3"})
        document["animations"] = [{
            "name": name,
            "samplers": [{"input": len(accessors) - 2, "output": len(accessors) - 1,
                          "interpolation": "LINEAR"}],
            "channels": [{"sampler": 0, "target": {"node": 0, "path": "translation"}}],
        }]

    while len(binary) % 4:
        binary.append(0)
    document["buffers"] = [{"byteLength": len(binary)}]

    text = json.dumps(document, separators=(",", ":"), sort_keys=True).encode("utf-8")
    text += b" " * (-len(text) % 4)
    total = 12 + 8 + len(text) + 8 + len(binary)
    return (b"glTF" + struct.pack("<II", 2, total)
            + struct.pack("<I", len(text)) + b"JSON" + text
            + struct.pack("<I", len(binary)) + b"BIN\x00" + bytes(binary))


def material_json(name, colour):
    """A glTF 2.0 material object as JSON: what a 3D loader needs to build a PBR material."""
    r, g, b = (c / 255 for c in colour)
    return (json.dumps({
        "name": name,
        "pbrMetallicRoughness": {
            "baseColorFactor": [round(r, 4), round(g, 4), round(b, 4), 1],
            "metallicFactor": 0,
            "roughnessFactor": 1,
        },
    }, indent=2, sort_keys=True) + "\n").encode("utf-8")


def atlas_json(image_name, frame_w, frame_h, frames, prefix):
    """A texture-atlas descriptor in the widely read `frames` / `meta` shape."""
    return (json.dumps({
        "frames": {
            f"{prefix}-{i}": {
                "frame": {"x": i * frame_w, "y": 0, "w": frame_w, "h": frame_h},
                "rotated": False, "trimmed": False,
                "sourceSize": {"w": frame_w, "h": frame_h},
                "spriteSourceSize": {"x": 0, "y": 0, "w": frame_w, "h": frame_h},
            }
            for i in range(frames)
        },
        "animations": {prefix: [f"{prefix}-{i}" for i in range(frames)]},
        "meta": {"image": image_name, "format": "RGBA8888",
                 "size": {"w": frame_w * frames, "h": frame_h}, "scale": "1"},
    }, indent=2, sort_keys=True) + "\n").encode("utf-8")

"""Sound effects composed per design: each cue's role from its words, its pitch from the song.

    samples, info = render_sfx(req_words, song, rate=44100, loop=False, seed=...)

A cue's id, description and trigger say what it is ("UI tap", "merge pop, pitched per
cascade step", "game-over sting; the music ducks under it", "engine hum loop"); `role` picks
the first recipe whose words match (RECIPES, in order). Every tonal recipe plays in the
song's key on the song's instruments - a toybox game's reward is a marimba-and-bell chime in
its key, a synthwave game's a saw-brass stab - so the effects sit with the music. Mono,
normalised to -1 dBFS peak, the tail faded; a looping cue (an engine) is built from partials
that complete whole cycles in the loop, so it repeats without a click.
"""

import math

from . import dsp
from .voices import Voices

__all__ = ["RECIPES", "role", "render_sfx"]

# (recipe, words) - the first match wins; "blip" when none does.
RECIPES = (
    ("engine", {"engine", "hum", "motor", "drone", "thruster", "idle"}),
    ("game-over", {"game-over", "gameover", "lose", "lost", "fail", "failure", "death", "die",
                   "dead", "defeat"}),
    ("fanfare", {"fanfare", "best", "record", "victory", "win", "levelup", "level-up",
                 "complete", "cleared", "unlock"}),
    ("hit", {"hit", "impact", "hurt", "crash", "explode", "explosion", "damage", "collide",
             "collision", "break", "smash"}),
    ("near-miss", {"near-miss", "near", "graze", "zing"}),
    ("whoosh", {"whoosh", "swipe", "pass", "dash", "swoosh", "slide", "fly", "throw", "lane"}),
    ("combo", {"combo", "cascade", "chain", "streak", "stinger", "multiplier"}),
    ("reward", {"reward", "chime", "bonus", "gift", "granted", "prize", "coin-shower"}),
    ("coin", {"coin", "collect", "pickup", "pick", "gem", "star", "point", "points", "score"}),
    ("pop", {"merge", "pop", "match", "combine", "bubble", "fuse", "join"}),
    ("drop", {"drop", "thud", "land", "landing", "thunk", "place", "plop", "fall"}),
    ("jump", {"jump", "bounce", "hop", "spring", "boost", "launch"}),
    ("powerup", {"powerup", "power", "upgrade", "charge", "shield"}),
    ("error", {"error", "denied", "invalid", "wrong", "blocked", "cannot"}),
    ("tick", {"tick", "countdown", "timer", "beep", "warning", "alarm", "low-time"}),
    ("tap", {"tap", "click", "button", "ui", "menu", "select", "toggle", "confirm", "back",
             "press"}),
)


def role(words, primary=()):
    """The recipe for a cue: by its id's words first ("sfx-merge" is a pop even when its
    description mentions a cascade), then by every word it has."""
    for group in (set(primary), set(words)):
        for name, cues in RECIPES:
            if group & cues:
                return name
    return "blip"


def _scale_note(song, degree, octave):
    """MIDI note of scale `degree` (0 = tonic) in `octave` (4 = the octave of middle C)."""
    scale = song.scale
    o, idx = divmod(degree, len(scale))
    return 12 * (octave + 1 + o) + song.root + scale[idx]


def _mono(stereo):
    left, right = stereo
    return [(a + b) * 0.5 for a, b in zip(left, right)]


def _place(dest, src, at_s, rate, gain=1.0):
    dsp.mix_into(dest, src, int(at_s * rate), gain)


def _room(mono, rate, seconds=1.2, wet=0.25):
    left, right = dsp.reverb(mono, mono, rate, seconds=seconds, wet=wet, damp=0.5, combs=4)
    return [a + (l + r) * 0.5 for a, l, r in zip(mono, left, right)]


def render_sfx(words, song, rate=44100, *, loop=False, seed=0, primary=()):
    """(samples, info): one mono effect for a cue described by `words` (`primary`: the
    words of its id, which decide first)."""
    recipe = role(words, primary)
    if loop and recipe == "blip":
        recipe = "engine"
    voices = Voices(rate, dsp.Rng(song.brief.seed * 31 + seed))
    style = song.brief.style
    tonal = {"synthwave": "saw", "electro": "saw", "chiptune": "chip", "toybox": "mallet",
             "lofi": "epiano", "adventure": "pluck"}[style]
    out = globals()["_" + recipe.replace("-", "_")](voices, song, rate, tonal)
    if not loop:
        # Trim the silent tail (below -60 dBFS), keep 30 ms after it, fade the last 15 ms.
        level = max((abs(v) for v in out), default=0.0)
        floor = level * 0.001
        end = len(out)
        while end > 1 and abs(out[end - 1]) < floor:
            end -= 1
        out = out[:min(len(out), end + int(0.03 * rate))]
        out = dsp.fade(out, rate, fade_out=0.015)
    out = dsp.dc_block(out, rate) if not loop else out
    top = max((abs(v) for v in out), default=0.0)
    if top > 0:
        g = 10 ** (-1.0 / 20.0) / top
        out = [v * g for v in out]
    return out, {"recipe": recipe, "instrument": tonal, "seconds": round(len(out) / rate, 4)}


# -- recipes ------------------------------------------------------------------------------------

def _tone(voices, kind, midi, dur, vel=1.0):
    if kind == "saw":
        return _mono(voices.note("saw_lead", midi, dur, vel))
    if kind == "chip":
        return _mono(voices.note("chip_lead", midi, dur, vel, duty=0.25))
    if kind == "epiano":
        return _mono(voices.note("epiano", midi, dur, vel))
    if kind == "pluck":
        return _mono(voices.note("pluck", midi, dur, vel, 0.6))
    return _mono(voices.note("mallet", midi, vel, max(0.3, dur)))


def _tap(voices, song, rate, tonal):
    out = [0.0] * int(0.16 * rate)
    note = _scale_note(song, 4, 6)
    if tonal == "chip":
        _place(out, _mono(voices.note("chip_lead", note, 0.05, 0.9, duty=0.5)), 0, rate)
    elif tonal in ("mallet", "pluck"):
        _place(out, _mono(voices.note("woodblock", 1.0, pitch=dsp.midi_hz(note - 12))), 0, rate)
        _place(out, _mono(voices.note("mallet", note, 0.5, 0.12)), 0, rate, 0.6)
    else:
        n = int(0.07 * rate)
        blip = dsp.biquad(dsp.osc("square", dsp.midi_hz(note), n, rate), "lowpass", 3000, rate)
        _place(out, dsp.mul(blip, dsp.hit(n, rate, decay=0.05, peak=0.5)), 0, rate)
        tick = dsp.mul(dsp.biquad(voices.rng.noise(int(0.02 * rate), rate), "highpass", 4000,
                                  rate), dsp.hit(int(0.02 * rate), rate, decay=0.008))
        _place(out, tick, 0, rate, 0.4)
    return out


def _blip(voices, song, rate, tonal):
    out = [0.0] * int(0.25 * rate)
    _place(out, _tone(voices, tonal, _scale_note(song, 0, 5), 0.12), 0, rate)
    return out


def _drop(voices, song, rate, tonal):
    """A soft, pitched thunk: a sine thump falling an octave over a low noise puff."""
    out = [0.0] * int(0.5 * rate)
    root = dsp.midi_hz(_scale_note(song, 0, 2))
    n = int(0.4 * rate)
    thump = dsp.mul(dsp.osc("sine", root * 2.0, n, rate, to=root, glide=0.12),
                    dsp.hit(n, rate, attack=0.002, decay=0.3))
    _place(out, thump, 0, rate)
    puff = dsp.mul(dsp.biquad(voices.rng.noise(int(0.12 * rate), rate), "lowpass", 600, rate),
                   dsp.hit(int(0.12 * rate), rate, attack=0.003, decay=0.08, peak=0.6))
    _place(out, puff, 0, rate)
    if tonal in ("mallet", "pluck"):
        _place(out, _mono(voices.note("woodblock", 0.6, pitch=root * 6)), 0.005, rate, 0.3)
    return out


def _pop(voices, song, rate, tonal):
    """A bubble pop that rises, then a note on the tonic - the game pitches it per step."""
    out = [0.0] * int(0.45 * rate)
    note = _scale_note(song, 0, 5)
    n = int(0.09 * rate)
    f = dsp.midi_hz(note)
    bubble = dsp.mul(dsp.osc("sine", f * 0.6, n, rate, to=f * 1.6, glide=0.07),
                     dsp.envelope(n, rate, a=0.004, d=0.05, s=0.2, r=0.02, peak=0.9))
    _place(out, bubble, 0, rate)
    click = dsp.mul(dsp.biquad(voices.rng.noise(int(0.015 * rate), rate), "bandpass", 3000,
                               rate, q=1.5), dsp.hit(int(0.015 * rate), rate, decay=0.006))
    _place(out, click, 0, rate, 0.5)
    _place(out, _tone(voices, tonal, note + 12, 0.15, 0.8), 0.04, rate, 0.7)
    return out


def _combo(voices, song, rate, tonal):
    """A rising arpeggio up the tonic chord, an octave and a sparkle on top."""
    out = [0.0] * int(1.2 * rate)
    for k, degree in enumerate((0, 2, 4, 7)):
        note = _scale_note(song, degree, 5)
        _place(out, _tone(voices, tonal, note, 0.16, 0.7 + 0.1 * k), k * 0.08, rate)
    _place(out, _mono(voices.note("bell", _scale_note(song, 7, 6), 0.8, 0.7)), 0.32, rate, 0.6)
    return _room(out, rate, 1.0, 0.2)


def _reward(voices, song, rate, tonal):
    """A chime: a bell fifth to octave over the tonic chord, with shimmer."""
    out = [0.0] * int(1.7 * rate)
    for k, degree in enumerate((4, 7, 9)):
        _place(out, _mono(voices.note("bell", _scale_note(song, degree, 6), 0.9, 1.2)),
               k * 0.11, rate)
    chord = [_scale_note(song, d, 5) for d in (0, 2, 4)]
    for m in chord:
        _place(out, _tone(voices, tonal, m, 0.5, 0.45), 0.22, rate, 0.5)
    return _room(out, rate, 1.4, 0.25)


def _coin(voices, song, rate, tonal):
    out = [0.0] * int(0.4 * rate)
    a, b = _scale_note(song, 4, 6), _scale_note(song, 7, 6)
    for k, note in enumerate((a, b)):
        n = int((0.07 if k == 0 else 0.25) * rate)
        wave = dsp.osc("square" if tonal in ("chip", "saw") else "triangle", dsp.midi_hz(note),
                       n, rate)
        env = dsp.envelope(n, rate, a=0.002, d=0.06, s=0.6, r=0.08, peak=0.45)
        _place(out, dsp.mul(wave, env), k * 0.07, rate)
    return out


def _fanfare(voices, song, rate, tonal):
    """Stabs climbing to the tonic chord, held, with a sparkle run and a crash."""
    out = [0.0] * int(2.0 * rate)
    steps = ((0, 0.12, (0, 2, 4)), (0.16, 0.12, (3, 5, 7)), (0.32, 0.12, (4, 6, 8)),
             (0.5, 1.0, (7, 9, 11, 14)))
    for at, length, degrees in steps:
        notes = tuple(_scale_note(song, d, 4) for d in degrees)
        if tonal in ("saw", "pluck"):
            _place(out, _mono(voices.note("brass", notes, length, 1.0)), at, rate)
        else:
            for m in notes:
                _place(out, _tone(voices, tonal, m + 12, length, 0.8), at, rate, 0.6)
    for k, d in enumerate((7, 9, 11, 14)):
        _place(out, _mono(voices.note("bell", _scale_note(song, d, 6), 0.7, 0.8)),
               0.5 + k * 0.06, rate, 0.5)
    _place(out, _mono(voices.note("crash", 0.5)), 0.5, rate, 0.6)
    return _room(out, rate, 1.6, 0.25)


def _game_over(voices, song, rate, tonal):
    """A falling line - fifth, third, tonic in the minor - the last note bending down."""
    out = [0.0] * int(2.2 * rate)
    root = song.root
    line = [(0.0, 0.22, 7), (0.24, 0.22, 3), (0.48, 1.0, 0)]
    for at, length, interval in line:
        note = 12 * 5 + root + interval
        if at < 0.48:
            _place(out, _tone(voices, tonal, note, length, 0.9), at, rate)
    n = int(1.5 * rate)
    f = dsp.midi_hz(12 * 4 + root)
    bend = dsp.osc("saw" if tonal in ("saw", "chip") else "triangle", f, n, rate)
    held = int(0.4 * rate)
    falling = dsp.osc("saw" if tonal in ("saw", "chip") else "triangle", f, n - held, rate,
                      to=f * 2 ** (-14 / 12.0), glide=0.8)
    bend = bend[:held] + falling
    bend = dsp.biquad(bend, "lowpass", 1400, rate)
    bend = dsp.mul(bend, dsp.envelope(n, rate, a=0.05, d=0.3, s=0.8, r=0.3, hold=1.1,
                                      peak=0.35))
    _place(out, bend, 0.48, rate)
    return _room(out, rate, 2.0, 0.3)


def _hit(voices, song, rate, tonal):
    """An impact: a noise crack, a sub drop, a short metallic ring."""
    out = [0.0] * int(1.4 * rate)
    n = int(0.6 * rate)
    crack = dsp.mul(dsp.biquad(voices.rng.noise(n, rate), "lowpass", 2600, rate, to=400,
                               sweep=0.4), dsp.hit(n, rate, attack=0.001, decay=0.5))
    _place(out, crack, 0, rate)
    _place(out, _mono(voices.note("kick", 1.0, pitch=110.0, low=32.0, decay=0.7, click=0.6)), 0,
           rate)
    ring = [0.0] * int(0.8 * rate)
    for ratio, amp in ((1.0, 0.3), (2.76, 0.18), (5.4, 0.1)):
        m = len(ring)
        part = dsp.mul(dsp.osc("sine", 380 * ratio, m, rate), dsp.hit(m, rate, decay=0.5,
                                                                       peak=amp))
        ring = [a + b for a, b in zip(ring, part)]
    _place(out, ring, 0.005, rate, 0.6)
    return out


def _whoosh(voices, song, rate, tonal):
    out = [0.0] * int(0.65 * rate)
    n = int(0.6 * rate)
    noise = voices.rng.noise(n, rate)
    rise = int(0.18 * rate)

    def curve(i):
        if i < rise:
            return 500 * (2600 / 500) ** (i / rise)
        return 2600 * (700 / 2600) ** min(1.0, (i - rise) / (n - rise))

    sig = dsp.biquad(noise, "bandpass", 500, rate, q=1.6, curve=curve)
    env = [(i / rise) if i < rise else math.exp(-5.0 * (i - rise) / (n - rise)) for i in range(n)]
    _place(out, dsp.mul(sig, env), 0, rate)
    return out


def _near_miss(voices, song, rate, tonal):
    out = _whoosh(voices, song, rate, tonal)
    out += [0.0] * int(0.3 * rate)
    n = int(0.5 * rate)
    zing = dsp.osc("saw", 1800, n, rate, to=700, glide=0.45)
    zing = dsp.mul(dsp.biquad(zing, "lowpass", 4000, rate), dsp.hit(n, rate, attack=0.01,
                                                                     decay=0.45, peak=0.35))
    _place(out, zing, 0.06, rate)
    return _room(out, rate, 0.8, 0.22)


def _jump(voices, song, rate, tonal):
    out = [0.0] * int(0.3 * rate)
    n = int(0.22 * rate)
    f = dsp.midi_hz(_scale_note(song, 0, 4))
    wave = dsp.osc("square" if tonal == "chip" else "triangle", f, n, rate, to=f * 2.5,
                   glide=0.18)
    _place(out, dsp.mul(wave, dsp.envelope(n, rate, a=0.005, d=0.1, s=0.5, r=0.06, peak=0.5)),
           0, rate)
    return out


def _powerup(voices, song, rate, tonal):
    out = [0.0] * int(0.9 * rate)
    for k, degree in enumerate((0, 2, 4, 7, 9, 11, 14)):
        _place(out, _tone(voices, tonal, _scale_note(song, degree, 5), 0.1, 0.8), k * 0.05,
               rate)
    return _room(out, rate, 0.8, 0.18)


def _error(voices, song, rate, tonal):
    out = [0.0] * int(0.4 * rate)
    note = 12 * 3 + song.root + 6  # a tritone above the low tonic: wrong on purpose
    for k in range(2):
        n = int(0.12 * rate)
        wave = dsp.biquad(dsp.osc("square", dsp.midi_hz(note), n, rate), "lowpass", 1800, rate)
        _place(out, dsp.mul(wave, dsp.envelope(n, rate, a=0.003, d=0.05, s=0.7, r=0.03,
                                               peak=0.5)), k * 0.15, rate)
    return out


def _tick(voices, song, rate, tonal):
    out = [0.0] * int(0.12 * rate)
    n = int(0.06 * rate)
    wave = dsp.osc("sine", dsp.midi_hz(_scale_note(song, 4, 6)), n, rate)
    _place(out, dsp.mul(wave, dsp.hit(n, rate, decay=0.05, peak=0.6)), 0, rate)
    return out


def _engine(voices, song, rate, tonal):
    """A 2 s seamless hum: partials on multiples of 0.5 Hz (whole cycles in the loop), a
    7.5 Hz throb, band-limited noise looped at a quarter of the loop."""
    length = 2.0
    n = int(length * rate)
    base = round(dsp.midi_hz(_scale_note(song, 0, 1)) * 2) / 2.0  # tonic, ~30-60 Hz
    out = [0.0] * n
    two_pi = 2 * math.pi
    for mult, amp in ((1, 0.5), (2, 0.35), (3, 0.18), (4, 0.12), (6, 0.06)):
        f = base * mult
        w = two_pi * f / rate
        out = [o + amp * math.sin(w * i) for i, o in enumerate(out)]
    detune = base + 0.5
    w = two_pi * detune / rate
    out = [o + 0.25 * math.sin(w * i) for i, o in enumerate(out)]
    throb = [1.0 + 0.2 * math.sin(two_pi * 7.5 * i / rate) for i in range(n)]
    out = [o * t for o, t in zip(out, throb)]
    quarter = n // 4
    noise = voices.rng.noise(quarter, rate)
    # Smooth the noise loop's own seam: a 5 ms crossfade of its end into its start.
    fade = int(0.005 * rate)
    for i in range(fade):
        k = i / fade
        noise[i] = noise[i] * k + noise[quarter - fade + i] * (1 - k)
    noise = noise * 4
    # Filter circularly: run once to warm the filter, keep the second pass.
    filtered = dsp.biquad(noise + noise, "bandpass", 700, rate, q=0.9)[n:]
    out = [o + 0.18 * v for o, v in zip(out, filtered)]
    return out

"""Music composed as code: a song from a brief, arranged per cue, rendered as a seamless loop.

    song = Song(brief)                                  key, mode, progressions, a hook
    left, right, info = render_cue(song, "main", seconds=60, rate=44100)

One `Song` per design: every music cue of a game is an arrangement of the same piece, so the
title variant is recognisably the play loop calmed down, and an intensity layer starts and
stays in lock-step with its base. What a cue kind plays:

    main      the whole arrangement: drums, bass, chords/pads, arpeggio, the hook in its
              middle sections, crashes and risers at section changes
    base      main without the layer's parts (when the design has an intensity layer)
    layer     the intensity parts only - arpeggio, lead, open hats, claps, crashes, risers -
              the same bars and length as the base
    title     the progression and the hook on bells over pads, a slow arpeggio and a sub,
              a soft kick in its second half; no snare
    ambience  pads and sparse bells, no rhythm

The song is 8-bar sections (A, A', B, A'' with a breakdown) of a 4-chord progression; the
hook is a 2-bar motif - a rhythm and a contour in scale steps - re-fitted to each chord, its
strong beats on chord tones. The loop is a whole number of bars and of 512-sample blocks (the
tempo moves by a fraction of a percent to make it so); note tails, reverbs, echoes and the
compressor all run over the loop's own end before its start, so the seam is continuous.
"""

import math

from . import dsp
from .style import KEYS
from .voices import Voices

__all__ = ["Song", "render_cue", "plan", "MODES", "CUE_KINDS"]

MODES = {
    "ionian": [0, 2, 4, 5, 7, 9, 11],
    "mixolydian": [0, 2, 4, 5, 7, 9, 10],
    "dorian": [0, 2, 3, 5, 7, 9, 10],
    "aeolian": [0, 2, 3, 5, 7, 8, 10],
    "phrygian": [0, 1, 3, 5, 7, 8, 10],
    "harmonic": [0, 2, 3, 5, 7, 8, 11],
}
# Progressions as scale degrees (0 = the tonic chord), one chord per bar.
PROGRESSIONS = {
    "major": [[0, 4, 5, 3], [0, 5, 3, 4], [5, 3, 0, 4], [0, 3, 5, 4], [3, 0, 4, 5],
              [0, 3, 1, 4]],
    "minor": [[0, 5, 2, 6], [0, 3, 5, 4], [0, 6, 5, 6], [5, 6, 0, 0], [0, 5, 3, 4],
              [0, 3, 6, 2]],
    "phrygian": [[0, 1, 0, 6], [0, 1, 6, 0], [0, 6, 5, 1]],
}
CUE_KINDS = ("main", "base", "layer", "title", "ambience")
TAIL_S = 4.0
LEAD_IN = 0.125  # beats of the bar before the downbeat that open the file (render_cue)
LAYER_PARTS = {"arp", "lead", "open", "clap", "crash", "riser", "fill", "sparkle"}
# One-bar rhythms for the hook: (beat, length in beats).
RHYTHMS = [
    [(0, 1), (1, 0.5), (1.5, 0.5), (2, 1.5), (3.5, 0.5)],
    [(0, 0.5), (0.5, 0.5), (1, 1), (2, 0.5), (2.5, 0.5), (3, 1)],
    [(0, 1.5), (1.5, 0.5), (2, 1), (3, 1)],
    [(0, 0.75), (0.75, 0.75), (1.5, 0.5), (2, 2)],
    [(0.5, 0.5), (1, 0.5), (1.5, 1), (2.5, 0.5), (3, 1)],
    [(0, 1), (1, 1), (2, 0.5), (2.5, 0.5), (3, 1)],
]
CADENCE = [(0, 1), (1, 3)]


class Song:
    def __init__(self, brief):
        self.brief = brief
        self.rng = dsp.Rng(brief.seed)
        self.style = brief.spec
        self.mode = brief.mode
        self.scale = MODES[self.mode]
        self.root = brief.root
        family = "phrygian" if self.mode == "phrygian" else (
            "major" if self.mode in ("ionian", "mixolydian") else "minor")
        table = PROGRESSIONS[family]
        first = self.rng.randrange(len(table))
        second = (first + 1 + self.rng.randrange(len(table) - 1)) % len(table)
        self.prog_a = [self._fix(d) for d in table[first]]
        self.prog_b = [self._fix(d) for d in table[second]]
        self.rhythm_a = RHYTHMS[self.rng.randrange(len(RHYTHMS))]
        self.rhythm_b = RHYTHMS[self.rng.randrange(len(RHYTHMS))]
        steps = [-2, -1, -1, 1, 1, 2, 0, 3, -3]
        self.contour = [self.rng.choice(steps) for _ in range(16)]
        self.sevenths = bool(self.style.get("sevenths"))

    def _fix(self, degree):
        # A diminished chord on the leading tone of harmonic minor reads as a mistake in this
        # music: take the dominant instead.
        return 4 if degree == 6 and self.mode == "harmonic" else degree

    # -- harmony -------------------------------------------------------------------------------

    def chord_pcs(self, degree, seventh=False):
        """Pitch classes of the diatonic chord on `degree` (root first)."""
        scale = self.scale
        out = []
        for step in (0, 2, 4) + ((6,) if seventh else ()):
            d = degree + step
            octave, idx = divmod(d, 7)
            out.append((self.root + scale[idx] + 12 * octave) % 12)
        return out

    def voicing(self, degree, floor, spread=False, seventh=None):
        pcs = self.chord_pcs(degree, self.sevenths if seventh is None else seventh)
        notes = []
        for pc in pcs:
            n = floor + ((pc - floor) % 12)
            notes.append(n)
        notes.sort()
        if spread and len(notes) >= 3:
            notes[1] += 12
            notes.sort()
        return notes

    def bass(self, degree, floor=33):
        pc = self.chord_pcs(degree)[0]
        return floor + ((pc - floor) % 12)

    def scale_notes(self, lo, hi):
        return [m for m in range(lo, hi + 1) if (m - self.root) % 12 in self.scale]

    def chord_tones(self, degree, lo, hi):
        pcs = set(self.chord_pcs(degree, False))
        return [m for m in range(lo, hi + 1) if m % 12 in pcs]

    # -- the song --------------------------------------------------------------------------------

    def bar_plan(self, bars):
        """[(degree, section index, bar in section)] for `bars` bars: A A' B A'' ..."""
        out = []
        for i in range(bars):
            section, inside = divmod(i, 8)
            prog = self.prog_b if section % 4 == 2 else self.prog_a
            out.append((prog[inside % 4], section, inside))
        return out

    def melody(self, bars, register=None):
        """{bar: [(beat, length, midi)]}: the hook, fitted to each bar's chord."""
        lo, hi = register or self.style["register"]
        plan = self.bar_plan(bars)
        notes = self.scale_notes(lo - 12, hi + 12)
        out = {}
        prev = None
        for i, (degree, section, inside) in enumerate(plan):
            phrase_bar = inside % 2
            rhythm = self.rhythm_a if phrase_bar == 0 else self.rhythm_b
            if inside == 7:
                rhythm = CADENCE
            if phrase_bar == 0 or prev is None:
                tones = self.chord_tones(degree, lo, hi)
                center = (lo + hi) // 2 if prev is None else prev
                prev = min(tones, key=lambda m: (abs(m - center), m))
                start = 0
            else:
                start = len(self.rhythm_a)
            line = []
            for k, (beat, length) in enumerate(rhythm):
                if k or phrase_bar:
                    # The same contour every phrase - that is what makes it a hook - varied in
                    # the third phrase of each section.
                    step = self.contour[(start + k + (3 if inside in (4, 5) else 0))
                                        % len(self.contour)]
                    idx = min(range(len(notes)), key=lambda j: abs(notes[j] - prev))
                    idx = max(0, min(len(notes) - 1, idx + step))
                    candidate = notes[idx]
                else:
                    candidate = prev
                if beat in (0, 2) or length >= 1.5 or inside == 7:
                    tones = self.chord_tones(degree, lo - 12, hi + 12)
                    candidate = min(tones, key=lambda m: (abs(m - candidate), m))
                while candidate > hi:
                    candidate -= 12
                while candidate < lo:
                    candidate += 12
                line.append((beat, length, candidate))
                prev = candidate
            out[i] = line
        return out


def plan(song, seconds, rate):
    """(bars, tempo, frames): a whole number of 8-bar sections lasting at least `seconds`,
    the tempo nudged so the loop is a whole number of 512-sample blocks."""
    bar_s = 4 * 60.0 / song.brief.tempo
    bars = 8 * max(1, math.ceil(seconds / (8 * bar_s) - 1e-9))
    frames = int(round(bars * bar_s * rate / 512.0)) * 512
    tempo = bars * 4 * 60.0 * rate / frames
    return bars, tempo, frames


class _Score:
    """Events on buses: (seconds, bus, voice, args, kwargs, gain, pan)."""

    def __init__(self):
        self.events = []
        self.kicks = []

    def add(self, t, bus, voice, *args, gain=1.0, pan=0.0, **kwargs):
        self.events.append((t, bus, voice, args, kwargs, gain, pan))


def _swung(pos, swing, eighths):
    if not swing:
        return pos
    unit = 0.5 if eighths else 0.25
    k = pos / unit
    if abs(k - round(k)) > 1e-6 or int(round(k)) % 2 == 0:
        return pos
    return pos + swing * unit


def _q(vel):
    return round(max(0.05, min(1.2, vel)) * 20) / 20.0


def compose(song, kind, bars, tempo):
    """The score of one cue."""
    style = song.style
    kit = style["kit"]
    beat = 60.0 / tempo
    bar_s = 4 * beat
    swing = song.brief.swing
    eighths = swing >= 0.1
    rng = dsp.Rng(song.brief.seed + {"main": 1, "base": 1, "layer": 1, "title": 2,
                                     "ambience": 3}[kind])
    human = style["kit"] in ("toy", "soft", "tom")
    score = _Score()
    plan_ = song.bar_plan(bars)
    hook = song.melody(bars)

    def at(i, pos):
        t = i * bar_s + _swung(pos, swing, eighths) * beat
        if human:
            t += (rng.random() - 0.5) * 0.006
        return max(0.0, t)

    def want(part):
        if kind == "layer":
            return part in LAYER_PARTS
        if kind == "base":
            return part not in LAYER_PARTS
        return True

    last = bars - 1
    for i, (degree, section, inside) in enumerate(plan_):
        sec4 = section % 4
        breakdown = kind in ("main", "base", "layer") and sec4 == 3 and inside < 4
        peak = sec4 in (1, 2)
        t_bar = i * bar_s
        if kind in ("title", "ambience"):
            _title_bar(song, score, kind, i, degree, inside, bars, at, beat, hook)
            continue
        # -- drums
        if not breakdown:
            _drums(score, kit, i, at, want, peak, rng)
        else:
            for p in (0, 2):
                score.kicks.append(at(i, p))
        # Bar 0's downbeat included: the loop is circular, and the turnaround riser over the
        # last two beats leads into exactly this crash. Without it a cue whose parts hold the
        # riser but no kick (the layer) ends loud and starts near-silent, and its seam fails
        # the rendered-seam edge bar (goalkeeper-royale's music-tension-layer, 6.46 dB).
        if inside == 0 and want("crash"):
            score.add(at(i, 0), "drums", "crash", _q(0.7 if not breakdown else 0.5))
        if inside == 7 and want("riser"):
            # The last bar's riser is the loop's turnaround: at full velocity, so the pickup
            # before the downbeat - where the file's seam falls (LEAD_IN) - is not a dip.
            score.add(t_bar, "drums", "riser", round(bar_s, 3), 1.0 if i == last else 0.7)
        if i == last and want("fill"):
            for k, p in enumerate((2, 2.5, 3, 3.5)):
                score.add(at(i, p), "drums", "tom", 0.8, 190 - k * 30)
            # An open hat on the last thirty-second - the pickup itself, LEAD_IN before the
            # downbeat, where the file's seam falls - rings into the downbeat. A fill that
            # stopped at the toms left that pickup a gap, the rendered seam's edges 6 dB
            # apart on every seed (goalkeeper-royale's layer); a tom there decays before
            # the pickup, and a hat a sixteenth earlier lands before the seam, not in it.
            score.add(at(i, 4 - LEAD_IN), "drums", "hat", 0.6, open_=True)
        # -- bass
        if want("bass"):
            _bass(song, score, style["bass"], i, degree, at, beat, breakdown, peak,
                  plan_[(i + 1) % bars][0])
        # -- chords and pads
        if want("chords"):
            _chords(song, score, style, i, degree, at, beat, breakdown)
        # -- arpeggio
        if style.get("arp") and want("arp"):
            _arp(song, score, style, i, degree, at, beat, breakdown)
        # -- the hook
        if want("lead") and sec4 in (1, 2) and style.get("lead"):
            prev = None
            for b, length, midi in hook[i]:
                lead = style["lead"]
                if lead in ("saw_lead", "pulse_lead"):
                    glide = prev if prev is not None and abs(prev - midi) <= 3 else None
                    score.add(at(i, b), "music", lead, midi, round(length * beat * 0.95, 3),
                              1.0, glide)
                    if style.get("echo"):
                        score.add(at(i, b), "echo", lead, midi, round(length * beat * 0.9, 3),
                                  0.4)
                elif lead == "pluck":
                    score.add(at(i, b), "music", "pluck", midi, round(length * beat, 3), 1.0,
                              0.6)
                elif lead == "mallet":
                    score.add(at(i, b), "music", "mallet", midi, 1.0, 0.5)
                else:
                    score.add(at(i, b), "music", lead, midi, round(length * beat * 0.92, 3),
                              1.0)
                    if style.get("echo"):
                        score.add(at(i, b), "echo", lead, midi, round(length * beat * 0.9, 3),
                                  0.35)
                prev = midi
        # -- sparkle on section starts
        if want("sparkle") and inside == 0:
            tones = song.chord_tones(degree, 76, 96)
            sparkle = style.get("sparkle") or "bell"
            for k, m in enumerate(tones[:3]):
                if sparkle == "chip_lead":
                    score.add(at(i, k * 0.25), "echo", "chip_lead", m, 0.2, 0.6)
                else:
                    score.add(at(i, k * 0.5), "echo", "bell", m, 0.45, 1.6)
    return score


def _drums(score, kit, i, at, want, peak, rng):
    def kick(pos, vel=1.0, **kw):
        if want("kick"):
            score.add(at(i, pos), "drums", "kick", _q(vel), **kw)
        score.kicks.append(at(i, pos))

    if kit == "four":
        for p in range(4):
            kick(p, 1.0, pitch=120, low=42, decay=0.42, click=0.35)
        if want("snare"):
            for p in (1, 3):
                score.add(at(i, p), "drums", "snare", 0.7, tone=175, decay=0.16, bright=1900)
                score.add(at(i, p), "gated", "snare", 0.9)
        if want("hats"):
            for k in range(16):
                score.add(at(i, k / 4), "drums", "hat", 0.55 if k % 4 == 2 else 0.28)
        if want("open") and peak:
            for p in (0.5, 1.5, 2.5, 3.5):
                score.add(at(i, p), "drums", "hat", 0.5, open_=True)
        if want("clap") and peak:
            for p in (1, 3):
                score.add(at(i, p), "gated", "clap", 0.6)
    elif kit == "chip":
        for p in (0, 1.5, 2) if peak else (0, 2):
            kick(p, 0.9, pitch=190, low=55, decay=0.16, click=0.1)
        if want("snare"):
            for p in (1, 3):
                score.add(at(i, p), "drums", "chipnoise", 0.9, decay=0.12, tone=3000.0)
        if want("hats"):
            for k in range(8):
                score.add(at(i, k / 2), "drums", "chipnoise", 0.45 if k % 2 else 0.3,
                          decay=0.03, tone=11000.0)
        if want("open") and peak:
            for p in (0.5, 2.5):
                score.add(at(i, p), "drums", "chipnoise", 0.4, decay=0.15, tone=9000.0)
    elif kit == "toy":
        for p in ((0, 2, 2.5) if peak else (0, 2)):
            kick(p, 0.85 if p != 2.5 else 0.6, pitch=110, low=48, decay=0.3, click=0.25)
        if want("snare"):
            for p in (1, 3):
                score.add(at(i, p), "drums", "snare", 0.45, tone=220, decay=0.12,
                          bright=2600)
        if want("hats"):
            for k in range(8):
                score.add(at(i, k / 2), "drums", "shaker", _q(0.55 if k % 2 else 0.8))
        if want("clap") and peak:
            for p in (1, 3):
                score.add(at(i, p), "gated", "clap", 0.45)
        if want("open"):
            score.add(at(i, 3.5), "drums", "woodblock", 0.7, pitch=1400.0)
            if peak:
                score.add(at(i, 1.75), "drums", "woodblock", 0.5, pitch=1100.0)
    elif kit == "soft":
        for p in (0, 2.5) if not peak else (0, 1.75, 2.5):
            kick(p, 0.75, pitch=95, low=44, decay=0.35, click=0.1)
        if want("snare"):
            for p in (1, 3):
                score.add(at(i, p), "drums", "snare", 0.4, tone=160, decay=0.2, bright=1400)
        if want("hats"):
            for k in range(8):
                score.add(at(i, k / 2), "drums", "hat", _q(0.32 if k % 2 else 0.22),
                          tone=6000.0)
        if want("open") and peak:
            score.add(at(i, 3.5), "drums", "hat", 0.3, open_=True, tone=6000.0)
    elif kit == "tom":
        for p in (0, 2):
            kick(p, 0.95, pitch=90, low=40, decay=0.55, click=0.2)
        if want("snare"):
            score.add(at(i, 3), "drums", "snare", 0.55, tone=150, decay=0.25, bright=1600)
        if want("hats"):
            for k in range(8):
                score.add(at(i, k / 2), "drums", "shaker", 0.35 if k % 2 else 0.5)
        if want("open"):
            for k, p in enumerate((1.5, 3.5) if peak else (3.5,)):
                score.add(at(i, p), "drums", "tom", 0.7, 160 - 25 * k)
    else:  # electro
        for p in range(4):
            kick(p, 1.0, pitch=160, low=48, decay=0.3, click=0.7)
        if want("snare"):
            for p in (1, 3):
                score.add(at(i, p), "drums", "clap", 0.8)
        if want("hats"):
            for k in range(16):
                score.add(at(i, k / 4), "drums", "hat", 0.5 if k % 2 else 0.22, tone=9000.0)
        if want("open") and peak:
            for p in (0.5, 1.5, 2.5, 3.5):
                score.add(at(i, p), "drums", "hat", 0.45, open_=True, tone=8000.0)


def _bass(song, score, voice, i, degree, at, beat, breakdown, peak, next_degree):
    root = song.bass(degree, 33 if voice in ("saw_bass", "chip_bass") else 36)
    fifth = song.voicing(degree, root, seventh=False)[2] if len(song.voicing(
        degree, root, seventh=False)) > 2 else root + 7
    if breakdown:
        score.add(at(i, 0), "music", voice, root, round(3.8 * beat, 3), 0.8)
        return
    if voice == "saw_bass":
        step = 0.25 if peak and song.style["kit"] == "electro" else 0.5
        p = 0.0
        while p < 4 - 1e-9:
            up = (round(p * 2) % 4 == 3) if step == 0.5 else (round(p * 4) % 4 == 2)
            score.add(at(i, p), "music", "saw_bass", root + (12 if up else 0),
                      round(step * beat * 0.85, 3), 0.8 if up else 1.0, 700.0)
            p += step
    elif voice == "chip_bass":
        for k in range(8):
            score.add(at(i, k / 2), "music", "chip_bass", root + (12 if k % 2 else 0),
                      round(0.45 * beat, 3), 1.0)
    elif voice == "pluck_bass":
        approach = song.bass(next_degree, 36)
        for pos, length, note, vel in ((0, 1, root, 1.0), (1.5, 0.5, fifth, 0.8),
                                       (2, 1, root, 0.95), (3, 0.5, fifth, 0.75),
                                       (3.5, 0.5, approach + (1 if approach < root else -1)
                                        if peak else root + 12, 0.7)):
            score.add(at(i, pos), "music", "pluck_bass", note, round(length * beat * 0.9, 3),
                      _q(vel))
    else:  # upright
        approach = song.bass(next_degree, 36)
        for pos, length, note in ((0, 1.5, root), (1.5, 1.0, fifth),
                                  (3, 1.0, approach - 1 if approach > root else approach + 2)):
            score.add(at(i, pos), "music", "upright", note, round(length * beat * 0.95, 3), 0.9)


def _chords(song, score, style, i, degree, at, beat, breakdown):
    chords = style.get("chords")
    pad = style.get("pad")
    if chords == "pad":
        score.add(at(i, 0), "music", "pad", tuple(song.voicing(degree, 57, True)),
                  round(3.95 * beat, 3), 0.8 if breakdown else 1.0,
                  1500.0 if breakdown else 3200.0)
    elif chords == "mallet":
        notes = song.voicing(degree, 60)
        pattern = ((0, 0.9), (1.5, 0.6), (2.5, 0.7), (3, 0.5)) if not breakdown else ((0, 0.8),)
        for pos, vel in pattern:
            for k, m in enumerate(notes):
                score.add(at(i, pos), "music", "mallet", m, _q(vel), 0.5,
                          pan=(k - 1) * 0.35)
    elif chords == "epiano":
        notes = song.voicing(degree, 57)
        for pos, length, vel in ((0, 1.5, 0.9), (2.5, 1.5, 0.7)):
            for m in notes:
                score.add(at(i, pos), "music", "epiano", m, round(length * beat, 3), _q(vel))
    elif chords == "brass":
        notes = song.voicing(degree, 55)
        for pos, length in ((0, 0.5), (1.5, 0.5)) if not breakdown else ((0, 2.0),):
            score.add(at(i, pos), "music", "brass", tuple(notes), round(length * beat, 3), 0.9)
    if pad:
        score.add(at(i, 0), "music", pad, tuple(song.voicing(degree, 55, True)),
                  round(3.95 * beat, 3), 0.9)


def _arp(song, score, style, i, degree, at, beat, breakdown):
    arp = style["arp"]
    if arp == "pluck":
        tones = song.voicing(degree, 62)
        for k in range(8):
            m = tones[[0, 2, 1, 2][k % 4] % len(tones)]
            score.add(at(i, k / 2), "music", "pluck", m, round(0.45 * beat, 3),
                      0.6 if k % 2 else 0.8, 0.7, pan=0.25)
        return
    wave = "pulse" if arp == "pulse" else "square"
    tones = song.voicing(degree, 69 if arp == "square" else 72)
    order = [0, 1, 2, 1, 0, 2, 1, 2] if arp == "square" else [0, 1, 2, 3, 2, 1, 2, 3]
    for k in range(16):
        idx = order[k % 8]
        m = tones[idx % len(tones)] + (12 if idx >= len(tones) or (arp == "square" and
                                                                    k % 8 >= 4) else 0)
        vel = 0.55 if breakdown else 0.9
        cutoff = 1400.0 if breakdown else 2600.0
        if wave == "pulse":
            score.add(at(i, k / 4), "music", "chip_lead", m, round(0.2 * beat, 3), 0.5,
                      duty=0.125)
        else:
            score.add(at(i, k / 4), "echo", "arp", m, vel, 0.2, cutoff)
            score.add(at(i, k / 4), "music", "arp", m, _q(vel * 0.75), 0.2, cutoff)


def _title_bar(song, score, kind, i, degree, inside, bars, at, beat, hook):
    style = song.style
    chord = tuple(song.voicing(degree, 57, True))
    if style.get("chords") == "pad":
        score.add(at(i, 0), "music", "pad", chord, round(3.95 * beat, 3), 0.9, 2200.0)
    else:
        score.add(at(i, 0), "music", "soft_pad", chord, round(3.95 * beat, 3), 1.0)
    if kind == "ambience":
        if inside % 2 == 0:
            for b, _length, midi in hook[i][:2]:
                score.add(at(i, b), "echo", "bell", midi, 0.35, 2.0)
        return
    root = song.bass(degree, 33)
    if style["bass"] == "saw_bass":
        score.add(at(i, 0), "music", "saw_bass", root, round(3.6 * beat, 3), 0.5, 300.0)
    else:
        score.add(at(i, 0), "music", "upright", root + 12, round(3.6 * beat, 3), 0.5)
    tones = song.voicing(degree, 69)
    for k in range(8):
        m = tones[[0, 1, 2, 1][k % 4] % len(tones)] + (12 if k >= 4 else 0)
        if style.get("arp") == "pulse":
            score.add(at(i, k / 2), "echo", "chip_lead", m, round(0.3 * beat, 3), 0.45,
                      duty=0.125)
        elif style.get("chords") == "mallet" or style.get("arp") is None:
            score.add(at(i, k / 2), "echo", "mallet", m, 0.55, 0.4)
        else:
            score.add(at(i, k / 2), "echo", "arp", m, 0.8, 0.3, 3400.0)
    if i >= bars // 2:
        score.add(at(i, 0), "drums", "kick", 0.5, pitch=100, low=40, decay=0.5, click=0.1)
        score.kicks.append(at(i, 0))
        for b, length, midi in hook[i]:
            if length >= 1:
                score.add(at(i, b), "echo", "bell", midi, 0.35, 1.6)
    if i == bars - 1:
        # The loop's turnaround: a soft swell over its last two beats into the downbeat it
        # returns to, so the end leads into the start rather than trailing off before it.
        score.add(at(i, 2), "drums", "riser", round(2 * beat, 3), 0.6)


def _duck(n, rate, times, floor=0.55, release=0.16):
    gain = [1.0] * n
    rel = math.exp(-1.0 / (release * rate / 3.0))
    span = int(release * rate * 2)
    for t in times:
        start = int(t * rate)
        level = floor
        for j in range(span):
            k = (start + j) % n
            if level < gain[k]:
                gain[k] = level
            level = 1.0 + (level - 1.0) * rel
    return gain


def _wrap(buf, frames):
    """Fold everything past `frames` onto the start: the loop's own tail rings into it."""
    tail = buf[frames:]
    head = buf[:frames]
    for start in range(0, len(tail), frames):
        part = tail[start:start + frames]
        head[:len(part)] = [a + b for a, b in zip(head[:len(part)], part)]
    return head


def _prewarm(fn, left, right, frames, rate, seconds=TAIL_S):
    """Run a stateful effect over the loop's last `seconds` then the loop; keep the loop."""
    pre = min(frames, int(seconds * rate))
    out_l, out_r = fn(left[frames - pre:] + left, right[frames - pre:] + right)
    return out_l[pre:], out_r[pre:]


TARGET_RMS = {"main": -16.0, "base": -16.0, "layer": -18.0, "title": -18.0, "ambience": -20.0}


def render_cue(song, kind, seconds, rate=44100, *, bars=None):
    """(left, right, info) of one music cue: a seamless stereo loop."""
    if kind not in CUE_KINDS:
        raise ValueError(kind)
    if bars is None:
        bars, tempo, frames = plan(song, seconds, rate)
    else:
        bar_s = 4 * 60.0 / song.brief.tempo
        frames = int(round(bars * bar_s * rate / 512.0)) * 512
        tempo = bars * 4 * 60.0 * rate / frames
    score = compose(song, kind, bars, tempo)
    voices = Voices(rate, dsp.Rng(song.brief.seed + 101))
    total = frames + int(TAIL_S * rate)
    buses = {name: ([0.0] * total, [0.0] * total)
             for name in ("drums", "music", "echo", "gated")}
    for t, bus, voice, args, kwargs, gain, pan in score.events:
        left, right = voices.note(voice, *args, pan=pan, **kwargs)
        offset = int(round(t * rate)) % frames
        dsp.mix_into(buses[bus][0], left, offset, gain)
        dsp.mix_into(buses[bus][1], right, offset, gain)
    for name in buses:
        buses[name] = (_wrap(buses[name][0], frames), _wrap(buses[name][1], frames))
    style = song.style
    beat = 60.0 / tempo
    if score.kicks and kind != "layer":
        duck = _duck(frames, rate, score.kicks, floor=0.5 if style["kit"] in (
            "four", "electro") else 0.8)
        music = buses["music"]
        buses["music"] = (dsp.mul(music[0], duck), dsp.mul(music[1], duck))
    out_l = [0.0] * frames
    out_r = [0.0] * frames

    def add(pair, gain=1.0):
        out_l[:] = [a + b * gain for a, b in zip(out_l, pair[0])]
        out_r[:] = [a + b * gain for a, b in zip(out_r, pair[1])]

    add(buses["drums"], 0.85)
    add(buses["music"])
    hall_in = ([a + b * 0.6 for a, b in zip(buses["music"][0], buses["echo"][0])],
               [a + b * 0.6 for a, b in zip(buses["music"][1], buses["echo"][1])])
    hall = _prewarm(lambda l, r: dsp.reverb(l, r, rate, seconds=style["hall"],
                                            wet=style["hall_wet"], damp=0.6),
                    hall_in[0], hall_in[1], frames, rate)
    add(hall)
    if any(buses["echo"][0]):
        echo = _prewarm(lambda l, r: dsp.pingpong(l, r, rate, time=0.75 * beat, feedback=0.42,
                                                  wet=0.35), buses["echo"][0],
                        buses["echo"][1], frames, rate)
        add(echo)
        add(buses["echo"], 0.5)
    if any(buses["gated"][0]):
        gated = _prewarm(lambda l, r: dsp.reverb(l, r, rate, seconds=0.55, wet=0.6, damp=0.3,
                                                 size=0.5, predelay=0.008, combs=4),
                         buses["gated"][0], buses["gated"][1], frames, rate, seconds=1.0)
        add(gated)
        add(buses["gated"], 0.5)
    out_l = dsp.dc_block(out_l, rate)
    out_r = dsp.dc_block(out_r, rate)
    out_l, out_r = _prewarm(lambda l, r: dsp.compress(l, r, rate, threshold=-18.0, ratio=2.5,
                                                      knee=8.0), out_l, out_r, frames, rate,
                            seconds=1.0)
    target = 10 ** (TARGET_RMS[kind] / 20.0)
    level = dsp.rms(out_l, out_r)
    if level > 0:
        g = target / level
        out_l = [v * g for v in out_l]
        out_r = [v * g for v in out_r]
    out_l, out_r = dsp.limit(out_l, out_r, rate, ceiling_db=-1.0)
    # The file starts a pickup before the downbeat (LEAD_IN of a beat): the loop is circular,
    # so nothing changes but where the seam falls - inside a sustained moment rather than on
    # the downbeat's attack, which would be a level step at the seam. Every cue of a song
    # shares the offset, so stems stay in lock-step.
    lead = int(round(LEAD_IN * beat * rate))
    if lead and kind not in ("base", "layer"):
        # A cue that plays alone may move its loop point a few milliseconds to where the
        # waveform steps least, as a loop point is chosen by hand.
        def step(k):
            return max(abs(out_l[k] - out_l[k - 1]), abs(out_r[k] - out_r[k - 1]))
        target = frames - lead
        best = min(range(target - 256, target + 257), key=lambda k: (step(k), abs(k - target)))
        lead = frames - best
    if lead:
        out_l = out_l[frames - lead:] + out_l[:frames - lead]
        out_r = out_r[frames - lead:] + out_r[:frames - lead]
    info = {"kind": kind, "bars": bars, "tempo_bpm": round(tempo, 3), "frames": frames,
            "lead_in_s": round(lead / rate, 4),
            "seconds": round(frames / rate, 3), "key": KEYS[song.root], "mode": song.mode,
            "progressions": [song.prog_a, song.prog_b], "events": len(score.events),
            "distinct_notes": len(voices.cache)}
    return out_l, out_r, info

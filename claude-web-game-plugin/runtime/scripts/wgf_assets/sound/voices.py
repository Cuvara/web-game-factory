"""The instruments: one function per sound, each returning (left, right) lists for one note.

A port, to plain Python, of the instrument set the reference games' scores were rendered
with (a Web Audio studio: drums, basses, keys, mallets, bells, leads, pads, arps, brass),
plus a plucked string (Karplus-Strong) and chip voices. Every note is rendered once per
distinct (instrument, pitch, length, velocity, options) and cached: a 32-bar loop repeats
the same few hundred notes, and a per-sample oscillator is the expensive part.
"""

import math

from . import dsp

__all__ = ["Voices"]


def _pan(mono, pan):
    """Equal-power pan of a mono note; pan -1 (left) .. 1 (right)."""
    angle = (pan + 1.0) * math.pi / 4.0
    gl, gr = math.cos(angle), math.sin(angle)
    return [v * gl for v in mono], [v * gr for v in mono]


def _sum(*signals):
    n = max(len(s) for s in signals)
    out = [0.0] * n
    for s in signals:
        m = len(s)
        out[:m] = [a + b for a, b in zip(out[:m], s)]
    return out


class Voices:
    def __init__(self, rate, rng):
        self.rate = rate
        self.rng = rng
        self.cache = {}

    def note(self, name, *args, pan=0.0, **kwargs):
        """(left, right) of one note of instrument `name`, cached."""
        key = (name, args, tuple(sorted(kwargs.items())), round(pan, 3))
        hit = self.cache.get(key)
        if hit is None:
            made = getattr(self, "_" + name)(*args, **kwargs)
            if isinstance(made, tuple):
                hit = made if pan == 0 else (
                    [v * (1 - max(0, pan)) for v in made[0]],
                    [v * (1 + min(0, pan)) for v in made[1]])
            else:
                hit = _pan(made, pan)
            self.cache[key] = hit
        return hit

    def n(self, seconds):
        return max(1, int(seconds * self.rate))

    # -- drums ---------------------------------------------------------------------------------

    def _kick(self, vel=1.0, pitch=150.0, low=46.0, decay=0.38, click=0.5):
        r = self.rate
        n = self.n(decay + 0.05)
        body = dsp.osc("sine", pitch, n, r, to=low, glide=0.11)
        out = dsp.mul(body, dsp.hit(n, r, decay=decay, peak=1.1 * vel))
        c_n = self.n(0.03)
        tick = dsp.biquad(self.rng.noise(c_n, r), "highpass", 2500, r)
        tick = dsp.mul(tick, dsp.hit(c_n, r, decay=0.012, peak=click * vel))
        dsp.mix_into(out, tick, 0)
        return out

    def _snare(self, vel=1.0, tone=185.0, decay=0.18, bright=2200.0):
        r = self.rate
        n = self.n(decay + 0.08)
        hiss = dsp.biquad(dsp.biquad(self.rng.noise(n, r), "highpass", 900, r),
                          "bandpass", bright, r, q=0.8)
        out = dsp.mul(hiss, dsp.hit(n, r, decay=decay, peak=1.5 * vel))
        b_n = self.n(0.12)
        body = dsp.osc("triangle", tone, b_n, r, to=tone * 0.8, glide=0.08)
        dsp.mix_into(out, dsp.mul(body, dsp.hit(b_n, r, decay=0.09, peak=0.55 * vel)), 0)
        return out

    def _clap(self, vel=1.0):
        r = self.rate
        n = self.n(0.3)
        env = [0.0] * n
        for k in range(3):
            start = int(k * 0.011 * r)
            burst = dsp.hit(n - start, r, decay=0.012 if k < 2 else 0.12, peak=0.8 * vel)
            dsp.mix_into(env, burst, start)
        sig = dsp.biquad(self.rng.noise(n, r), "bandpass", 1300, r, q=1.1)
        return dsp.mul(sig, env)

    def _hat(self, vel=1.0, open_=False, tone=7000.0):
        r = self.rate
        decay = 0.28 if open_ else 0.04
        n = self.n(decay + 0.04)
        sig = dsp.biquad(dsp.biquad(self.rng.noise(n, r), "highpass", tone, r, q=0.9),
                         "peaking", 10000, r, q=1.0, gain_db=4.0)
        return dsp.mul(sig, dsp.hit(n, r, decay=decay, peak=0.5 * vel))

    def _shaker(self, vel=1.0):
        r = self.rate
        n = self.n(0.09)
        sig = dsp.biquad(self.rng.noise(n, r), "bandpass", 6500, r, q=1.4)
        env = dsp.envelope(n, r, a=0.012, d=0.05, s=0.0, r=0.01, peak=0.5 * vel)
        return dsp.mul(sig, env)

    def _tom(self, vel=1.0, pitch=140.0):
        r = self.rate
        n = self.n(0.36)
        body = dsp.osc("sine", pitch, n, r, to=pitch * 0.6, glide=0.3)
        return dsp.mul(body, dsp.hit(n, r, decay=0.32, peak=0.8 * vel))

    def _crash(self, vel=1.0):
        r = self.rate
        n = self.n(1.9)
        sig = dsp.biquad(dsp.biquad(self.rng.noise(n, r), "highpass", 4500, r),
                         "peaking", 7000, r, q=0.7, gain_db=3.0)
        return dsp.mul(sig, dsp.hit(n, r, attack=0.002, decay=1.8, peak=0.3 * vel))

    def _riser(self, seconds, vel=1.0):
        r = self.rate
        n = self.n(seconds)
        sig = dsp.biquad(self.rng.noise(n, r), "bandpass", 400, r, q=2.5, to=7000, sweep=seconds)
        env = [0.35 * vel * (i / n) ** 2 for i in range(n)]
        return dsp.mul(sig, env)

    def _woodblock(self, vel=1.0, pitch=1200.0):
        r = self.rate
        n = self.n(0.09)
        body = dsp.biquad(dsp.osc("sine", pitch, n, r, to=pitch * 0.9, glide=0.05), "bandpass",
                          pitch, r, q=4)
        click = dsp.mul(self.rng.noise(n, r), dsp.hit(n, r, decay=0.004, peak=0.3))
        return dsp.mul(_sum(body, click), dsp.hit(n, r, decay=0.07, peak=0.8 * vel))

    def _chipnoise(self, vel=1.0, decay=0.08, tone=4000.0):
        """An NES-style noise hit: stepped white noise, sample-and-hold at `tone` Hz."""
        r = self.rate
        n = self.n(decay + 0.02)
        hold = max(1, int(r / tone))
        src = self.rng.noise(n // hold + 2, r)
        sig = [src[i // hold] for i in range(n)]
        return dsp.mul(sig, dsp.hit(n, r, decay=decay, peak=0.5 * vel))

    # -- bass -----------------------------------------------------------------------------------

    def _pluck_bass(self, midi, dur, vel=1.0):
        r = self.rate
        f = dsp.midi_hz(midi)
        n = self.n(dur + 0.12)
        tri = dsp.biquad(dsp.osc("triangle", f, n, r), "lowpass", 2200, r, q=2.0, to=380,
                         sweep=0.16)
        sub = dsp.osc("sine", f, n, r)
        env = dsp.envelope(n, r, a=0.004, d=0.18, s=0.45, r=0.08, hold=dur, peak=0.7 * vel)
        return dsp.mul(_sum(tri, sub), env)

    def _saw_bass(self, midi, dur, vel=1.0, cutoff=900.0):
        r = self.rate
        f = dsp.midi_hz(midi)
        n = self.n(dur + 0.08)
        saws = _sum(dsp.osc("saw", f, n, r, cents=-7), dsp.osc("saw", f, n, r, cents=7))
        saws = dsp.biquad(saws, "lowpass", cutoff * 2.6, r, q=3.0, to=cutoff, sweep=0.09)
        env = dsp.envelope(n, r, a=0.004, d=0.12, s=0.7, r=0.05, hold=dur, peak=0.5 * vel)
        sub = dsp.mul(dsp.osc("sine", f / 2, n, r),
                      dsp.envelope(n, r, a=0.004, d=0.1, s=0.8, r=0.05, hold=dur, peak=0.45 * vel))
        return _sum(dsp.mul(saws, env), sub)

    def _chip_bass(self, midi, dur, vel=1.0):
        r = self.rate
        n = self.n(dur + 0.03)
        tri = dsp.osc("triangle", dsp.midi_hz(midi), n, r)
        return dsp.mul(tri, dsp.envelope(n, r, a=0.002, d=0.05, s=0.9, r=0.02, hold=dur,
                                         peak=0.55 * vel))

    def _upright(self, midi, dur, vel=1.0):
        """A round acoustic-style bass: plucked string through a low-pass, sine body."""
        r = self.rate
        f = dsp.midi_hz(midi)
        n = self.n(dur + 0.15)
        string = self._ks(f, n, damping=0.996, bright=0.35)
        body = dsp.osc("sine", f, n, r)
        sig = dsp.biquad(_sum(dsp.scale(string, 0.8), dsp.scale(body, 0.6)), "lowpass", 900, r)
        return dsp.mul(sig, dsp.envelope(n, r, a=0.003, d=0.4, s=0.35, r=0.1, hold=dur,
                                         peak=0.8 * vel))

    # -- keys, mallets, plucks --------------------------------------------------------------------

    def _ks(self, freq, n, damping=0.995, bright=0.5):
        """Karplus-Strong plucked string of `n` samples."""
        period = max(2, int(round(self.rate / freq)))
        buf = dsp.onepole_lowpass(self.rng.noise(period, self.rate), 2000 + 9000 * bright,
                                  self.rate)
        out = [0.0] * n
        for i in range(n):
            j = i % period
            v = buf[j]
            out[i] = v
            buf[j] = damping * 0.5 * (v + buf[(j + 1) % period])
        return out

    def _pluck(self, midi, dur, vel=1.0, bright=0.5):
        r = self.rate
        n = self.n(min(dur + 0.4, 2.0))
        sig = self._ks(dsp.midi_hz(midi), n, damping=0.996, bright=bright)
        return dsp.mul(sig, dsp.envelope(n, r, a=0.002, d=0.6, s=0.5, r=0.2,
                                         hold=min(dur, n / r), peak=0.6 * vel))

    def _epiano(self, midi, dur, vel=1.0):
        """Two-operator FM whose index falls as the note rings, plus the tine's bell."""
        r = self.rate
        f = dsp.midi_hz(midi)
        n = self.n(dur + 0.4)
        out = [0.0] * n
        w = dsp.TWO_PI * f / r
        idx0, idx1 = 2.2 * vel, 0.25
        decay = math.exp(-1.0 / (0.25 * r))
        index = idx0
        sin = math.sin
        for i in range(n):
            out[i] = sin(w * i + index * sin(w * i))
            index = idx1 + (index - idx1) * decay
        env = dsp.envelope(n, r, a=0.003, d=0.9, s=0.25, r=0.35, hold=dur, peak=0.3 * vel)
        out = dsp.mul(out, env)
        b_n = self.n(0.12)
        bell = dsp.mul(dsp.osc("sine", f * 14, b_n, r), dsp.hit(b_n, r, decay=0.08,
                                                                 peak=0.035 * vel))
        dsp.mix_into(out, bell, 0)
        return out

    def _mallet(self, midi, vel=1.0, decay=0.45):
        r = self.rate
        f = dsp.midi_hz(midi)
        n = self.n(decay + 0.05)
        out = dsp.mul(dsp.osc("sine", f, n, r), dsp.hit(n, r, decay=decay, peak=0.45 * vel))
        dsp.mix_into(out, dsp.mul(dsp.osc("sine", f * 3.99, n, r),
                                  dsp.hit(n, r, decay=decay * 0.25, peak=0.16 * vel)), 0)
        dsp.mix_into(out, dsp.mul(dsp.osc("sine", f * 9.9, n, r),
                                  dsp.hit(n, r, decay=decay * 0.08, peak=0.05 * vel)), 0)
        return out

    def _bell(self, midi, vel=1.0, decay=1.4):
        r = self.rate
        f = dsp.midi_hz(midi)
        n = self.n(decay + 0.05)
        out = [0.0] * n
        for ratio, amp, life in ((1, 0.5, 1), (2.76, 0.22, 0.6), (5.4, 0.12, 0.35),
                                 (8.93, 0.06, 0.2)):
            if f * ratio >= r * 0.45:
                continue
            m = self.n(decay * life + 0.02)
            part = dsp.mul(dsp.osc("sine", f * ratio, m, r),
                           dsp.hit(m, r, decay=decay * life, peak=amp * vel * 0.5))
            dsp.mix_into(out, part, 0)
        return out

    # -- leads ----------------------------------------------------------------------------------

    def _pulse_lead(self, midi, dur, vel=1.0, glide_from=None, duty=0.25):
        r = self.rate
        f = dsp.midi_hz(midi)
        n = self.n(dur + 0.12)
        start = dsp.midi_hz(glide_from) if glide_from else f
        vib = (5.6, 22.0 if dur > 0.4 else 0.0, 0.1)
        wave = dsp.osc("pulse", start, n, r, to=f, glide=0.06 if glide_from else 0.0,
                       duty=duty, vibrato=vib)
        wave = dsp.biquad(wave, "lowpass", 3400, r, q=0.9)
        env = dsp.envelope(n, r, a=0.012, d=0.12, s=0.75, r=0.09, hold=dur, peak=0.2 * vel)
        body = dsp.mul(dsp.osc("sine", f, n, r),
                       dsp.envelope(n, r, a=0.015, d=0.1, s=0.8, r=0.08, hold=dur, peak=0.12 * vel))
        return _sum(dsp.mul(wave, env), body)

    def _chip_lead(self, midi, dur, vel=1.0, duty=0.25):
        r = self.rate
        n = self.n(dur + 0.03)
        wave = dsp.osc("pulse", dsp.midi_hz(midi), n, r, duty=duty,
                       vibrato=(6.0, 18.0 if dur > 0.3 else 0.0, 0.12))
        return dsp.mul(wave, dsp.envelope(n, r, a=0.003, d=0.08, s=0.7, r=0.03, hold=dur,
                                          peak=0.22 * vel))

    def _saw_lead(self, midi, dur, vel=1.0, glide_from=None):
        r = self.rate
        f = dsp.midi_hz(midi)
        n = self.n(dur + 0.3)
        vib = (5.2, 18.0 if dur > 0.5 else 0.0, 0.15)
        start = dsp.midi_hz(glide_from) if glide_from else f
        g = 0.07 if glide_from else 0.0
        a = dsp.osc("saw", start, n, r, to=f, glide=g, cents=-6, vibrato=vib)
        b = dsp.osc("saw", start * 2, n, r, to=f * 2, glide=g, cents=5, vibrato=vib)
        a = dsp.biquad(a, "lowpass", 3800, r, q=1.4)
        b = dsp.biquad(b, "lowpass", 3800, r, q=1.4)
        env = dsp.envelope(n, r, a=0.02, d=0.2, s=0.8, r=0.25, hold=dur, peak=0.13 * vel)
        left, right = _pan(dsp.mul(a, env), -0.15)
        l2, r2 = _pan(dsp.mul(b, env), 0.15)
        return _sum(left, l2), _sum(right, r2)

    def _whistle(self, midi, dur, vel=1.0):
        """A soft flute-like lead: sine with breath noise and delayed vibrato."""
        r = self.rate
        f = dsp.midi_hz(midi)
        n = self.n(dur + 0.15)
        tone = dsp.osc("sine", f, n, r, vibrato=(5.0, 14.0, 0.18))
        tone2 = dsp.osc("sine", f * 2, n, r)
        breath = dsp.biquad(self.rng.noise(n, r), "bandpass", f * 2, r, q=6)
        sig = _sum(tone, dsp.scale(tone2, 0.12), dsp.scale(breath, 0.25))
        return dsp.mul(sig, dsp.envelope(n, r, a=0.05, d=0.1, s=0.85, r=0.12, hold=dur,
                                         peak=0.22 * vel))

    # -- pads, arps, stabs ----------------------------------------------------------------------

    def _pad(self, notes, dur, vel=1.0, cutoff=1600.0):
        """Five detuned saws per note, spread across the stereo field, a slow filter swell."""
        r = self.rate
        n = self.n(dur + 0.9)
        left, right = [0.0] * n, [0.0] * n
        for midi in notes:
            for k, cents in enumerate((-14, -6, 0, 6, 14)):
                wave = dsp.osc("saw", dsp.midi_hz(midi), n, r, cents=cents,
                               phase=(k * 0.21 + midi * 0.13) % 1.0)
                pan = (k - 2) * 0.32
                ang = (pan + 1.0) * math.pi / 4.0
                gl, gr = math.cos(ang), math.sin(ang)
                left = [a + v * gl for a, v in zip(left, wave)]
                right = [b + v * gr for b, v in zip(right, wave)]
        swell = min(dur, 1.2) * r

        def curve(i):
            if i < swell:
                return cutoff * (0.45 + 0.55 * i / swell)
            return cutoff * (1.0 - 0.3 * min(1.0, (i - swell) / max(1.0, n - swell)))

        left = dsp.biquad(left, "lowpass", cutoff * 0.45, r, q=0.8, curve=curve)
        right = dsp.biquad(right, "lowpass", cutoff * 0.45, r, q=0.8, curve=curve)
        env = dsp.envelope(n, r, a=0.45, d=0.6, s=0.85, r=0.9, hold=dur, peak=0.07 * vel)
        return dsp.mul(left, env), dsp.mul(right, env)

    def _soft_pad(self, notes, dur, vel=1.0, cutoff=1400.0):
        r = self.rate
        n = self.n(dur + 0.7)
        left, right = [0.0] * n, [0.0] * n
        for midi in notes:
            a = dsp.osc("triangle", dsp.midi_hz(midi), n, r, cents=-5)
            b = dsp.osc("triangle", dsp.midi_hz(midi), n, r, cents=5, phase=0.37)
            left = [x + v * 0.85 + w * 0.3 for x, v, w in zip(left, a, b)]
            right = [x + w * 0.85 + v * 0.3 for x, v, w in zip(right, a, b)]
        left = dsp.biquad(left, "lowpass", cutoff, r, q=0.6)
        right = dsp.biquad(right, "lowpass", cutoff, r, q=0.6)
        env = dsp.envelope(n, r, a=0.3, d=0.5, s=0.8, r=0.7, hold=dur, peak=0.07 * vel)
        return dsp.mul(left, env), dsp.mul(right, env)

    def _arp(self, midi, vel=1.0, decay=0.22, cutoff=2600.0, wave="square"):
        r = self.rate
        n = self.n(decay + 0.02)
        sig = dsp.osc(wave, dsp.midi_hz(midi), n, r)
        sig = dsp.biquad(sig, "lowpass", cutoff * 1.8, r, q=4.0, to=cutoff * 0.35, sweep=decay)
        return dsp.mul(sig, dsp.hit(n, r, attack=0.002, decay=decay, peak=0.16 * vel))

    def _brass(self, notes, dur, vel=1.0):
        r = self.rate
        n = self.n(dur + 0.25)
        sig = [0.0] * n
        for midi in notes:
            for cents in (-4, 4):
                sig = [a + b for a, b in zip(sig, dsp.osc("saw", dsp.midi_hz(midi), n, r,
                                                          cents=cents))]
        attack = int(0.05 * r)

        def curve(i):
            if i < attack:
                return 500 + 3100 * i / attack
            return 1500 + 2100 * math.exp(-(i - attack) / (0.15 * r))

        sig = dsp.biquad(sig, "lowpass", 500, r, q=1.6, curve=curve)
        return dsp.mul(sig, dsp.envelope(n, r, a=0.02, d=0.25, s=0.7, r=0.18, hold=dur,
                                         peak=0.11 * vel))

    def _organ(self, notes, dur, vel=1.0):
        """Soft drawbar chords (sines at 1, 2, 3 x) - warm comping for slow styles."""
        r = self.rate
        n = self.n(dur + 0.2)
        sig = [0.0] * n
        for midi in notes:
            f = dsp.midi_hz(midi)
            for mult, amp in ((1, 1.0), (2, 0.45), (3, 0.2)):
                if f * mult < r * 0.45:
                    wave = dsp.osc("sine", f * mult, n, r)
                    sig = [a + b * amp for a, b in zip(sig, wave)]
        return dsp.mul(sig, dsp.envelope(n, r, a=0.04, d=0.2, s=0.9, r=0.15, hold=dur,
                                         peak=0.06 * vel))

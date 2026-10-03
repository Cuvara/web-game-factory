"""Signal processing for the composer, in plain Python lists of floats.

Per-sample loops are slow in Python, so everything that can be is computed a block at a time
with list comprehensions: feedback delays, damped combs and all-passes run in blocks of
their own delay length (each block depends only on the one before it), compressors and
limiters work on 64-sample blocks with interpolated gain. Oscillators and biquads are
per-sample - they are run once per distinct note and cached by the caller.

Everything is deterministic: noise comes from a seeded `random.Random`.
"""

import math
import random

__all__ = ["midi_hz", "Rng", "osc", "noise", "envelope", "hit", "biquad", "mul", "scale",
           "mix_into", "reverb", "pingpong", "compress", "limit", "peak", "rms", "silence",
           "onepole_lowpass", "fade", "dc_block"]

TWO_PI = 2.0 * math.pi


def midi_hz(midi):
    return 440.0 * 2.0 ** ((midi - 69) / 12.0)


class Rng(random.Random):
    """A seeded generator; `noise_bank` is a few seconds of white noise to slice from."""

    def __init__(self, seed):
        super().__init__(seed)
        self._bank = None

    def bank(self, rate):
        if self._bank is None:
            self._bank = [self.random() * 2.0 - 1.0 for _ in range(int(rate * 3))]
        return self._bank

    def noise(self, n, rate):
        bank = self.bank(rate)
        if n >= len(bank):
            return [self.random() * 2.0 - 1.0 for _ in range(n)]
        start = self.randrange(0, len(bank) - n)
        return bank[start:start + n]


def silence(n):
    return [0.0] * n


def noise(n, rng, rate=44100):
    return rng.noise(n, rate)


def _blep(t, dt):
    if t < dt:
        t /= dt
        return t + t - t * t - 1.0
    if t > 1.0 - dt:
        t = (t - 1.0) / dt
        return t * t + t + t + 1.0
    return 0.0


def osc(wave, freq, n, rate, *, to=None, glide=0.0, cents=0.0, phase=0.0, duty=0.5,
        vibrato=None):
    """`n` samples of an oscillator. `to`: glide exponentially to that frequency over
    `glide` seconds. `vibrato`: (rate Hz, depth cents, delay s). Band-limited saw/square
    (PolyBLEP); the triangle is naive (its harmonics fall as 1/k^2)."""
    f = freq * 2.0 ** (cents / 1200.0)
    ratio = 1.0
    glide_n = 0
    if to and glide > 0:
        glide_n = max(1, int(glide * rate))
        ratio = (to * 2.0 ** (cents / 1200.0) / f) ** (1.0 / glide_n)
    out = [0.0] * n
    p = phase % 1.0
    inv = 1.0 / rate
    sin = math.sin
    if vibrato:
        v_rate, v_depth, v_delay = vibrato
        v_start = int(v_delay * rate)
        v_ramp = max(1, int(0.25 * rate))
    else:
        v_start = n + 1
    for i in range(n):
        fi = f
        if i >= v_start:
            depth = v_depth * min(1.0, (i - v_start) / v_ramp)
            fi = f * 2.0 ** (depth * sin(TWO_PI * v_rate * i * inv) / 1200.0)
        dt = fi * inv
        if wave == "sine":
            v = sin(TWO_PI * p)
        elif wave == "saw":
            v = 2.0 * p - 1.0 - _blep(p, dt)
        elif wave == "square" or wave == "pulse":
            v = (1.0 if p < duty else -1.0) + _blep(p, dt) - _blep((p - duty) % 1.0, dt)
        elif wave == "triangle":
            v = 4.0 * abs(p - 0.5) - 1.0
        else:
            raise ValueError(wave)
        out[i] = v
        p += dt
        if p >= 1.0:
            p -= 1.0
        if i < glide_n:
            f *= ratio
    return out


def envelope(n, rate, *, a=0.005, d=0.1, s=0.6, r=0.15, hold=None, peak=1.0):
    """ADSR over `n` samples: attack, decay to sustain, held until `hold` seconds (default:
    n minus the release), then released (exponential, ~-60 dB over r)."""
    out = [0.0] * n
    a_n = max(1, int(a * rate))
    d_n = max(1, int(d * rate))
    r_n = max(1, int(r * rate))
    hold_n = int(hold * rate) if hold is not None else max(a_n, n - r_n)
    level = 0.0
    d_coef = math.exp(-1.0 / (d_n / 3.0))
    r_coef = math.exp(-6.9 / r_n)
    sustain = s * peak
    for i in range(n):
        if i < hold_n:
            if i < a_n:
                level = peak * (i + 1) / a_n
            else:
                level = sustain + (level - sustain) * d_coef
        else:
            level *= r_coef
        out[i] = level
    return out


def hit(n, rate, *, attack=0.001, decay=0.2, peak=1.0):
    """A percussive envelope: linear attack, exponential decay to -60 dB over `decay`."""
    out = [0.0] * n
    a_n = max(1, int(attack * rate))
    coef = math.exp(-6.9 / max(1, decay * rate))
    level = peak
    for i in range(n):
        if i < a_n:
            out[i] = peak * (i + 1) / a_n
        else:
            level *= coef
            out[i] = level
    return out


def mul(a, b):
    return [x * y for x, y in zip(a, b)]


def scale(a, g):
    return [x * g for x in a]


def fade(a, rate, *, fade_in=0.0, fade_out=0.0):
    out = list(a)
    n = len(out)
    fi = min(n, int(fade_in * rate))
    fo = min(n, int(fade_out * rate))
    for i in range(fi):
        out[i] *= i / fi
    for i in range(fo):
        out[n - 1 - i] *= i / fo
    return out


def _coefficients(kind, freq, q, rate, gain_db):
    freq = min(max(freq, 10.0), rate * 0.49)
    w = TWO_PI * freq / rate
    cw, sw = math.cos(w), math.sin(w)
    alpha = sw / (2.0 * max(q, 1e-3))
    amp = 10.0 ** (gain_db / 40.0)
    if kind == "lowpass":
        b0 = b2 = (1.0 - cw) / 2.0
        b1 = 1.0 - cw
        a0, a1, a2 = 1.0 + alpha, -2.0 * cw, 1.0 - alpha
    elif kind == "highpass":
        b0 = b2 = (1.0 + cw) / 2.0
        b1 = -(1.0 + cw)
        a0, a1, a2 = 1.0 + alpha, -2.0 * cw, 1.0 - alpha
    elif kind == "bandpass":
        b0, b1, b2 = alpha, 0.0, -alpha
        a0, a1, a2 = 1.0 + alpha, -2.0 * cw, 1.0 - alpha
    elif kind == "peaking":
        b0, b1, b2 = 1.0 + alpha * amp, -2.0 * cw, 1.0 - alpha * amp
        a0, a1, a2 = 1.0 + alpha / amp, -2.0 * cw, 1.0 - alpha / amp
    elif kind in ("lowshelf", "highshelf"):
        sq = 2.0 * math.sqrt(amp) * alpha
        if kind == "lowshelf":
            b0 = amp * ((amp + 1) - (amp - 1) * cw + sq)
            b1 = 2 * amp * ((amp - 1) - (amp + 1) * cw)
            b2 = amp * ((amp + 1) - (amp - 1) * cw - sq)
            a0 = (amp + 1) + (amp - 1) * cw + sq
            a1 = -2 * ((amp - 1) + (amp + 1) * cw)
            a2 = (amp + 1) + (amp - 1) * cw - sq
        else:
            b0 = amp * ((amp + 1) + (amp - 1) * cw + sq)
            b1 = -2 * amp * ((amp - 1) + (amp + 1) * cw)
            b2 = amp * ((amp + 1) + (amp - 1) * cw - sq)
            a0 = (amp + 1) - (amp - 1) * cw + sq
            a1 = 2 * ((amp - 1) - (amp + 1) * cw)
            a2 = (amp + 1) - (amp - 1) * cw - sq
    else:
        raise ValueError(kind)
    return b0 / a0, b1 / a0, b2 / a0, a1 / a0, a2 / a0


def biquad(x, kind, freq, rate, *, q=0.707, gain_db=0.0, to=None, sweep=0.0, curve=None):
    """RBJ biquad. `to`: the cutoff moves exponentially to `to` over `sweep` seconds (then
    holds); `curve`: a callable i -> cutoff Hz evaluated every 32 samples instead."""
    n = len(x)
    out = [0.0] * n
    b0, b1, b2, a1, a2 = _coefficients(kind, freq, q, rate, gain_db)
    x1 = x2 = y1 = y2 = 0.0
    moving = curve is not None or (to is not None and sweep > 0)
    sweep_n = int(sweep * rate) if to is not None else 0
    step = 32
    for start in range(0, n, step):
        if moving:
            if curve is not None:
                f = curve(start)
            else:
                t = min(1.0, start / sweep_n) if sweep_n else 1.0
                f = freq * (to / freq) ** t
            b0, b1, b2, a1, a2 = _coefficients(kind, f, q, rate, gain_db)
        for i in range(start, min(n, start + step)):
            xi = x[i]
            yi = b0 * xi + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2
            x2, x1 = x1, xi
            y2, y1 = y1, yi
            out[i] = yi
    return out


def onepole_lowpass(x, freq, rate):
    k = 1.0 - math.exp(-TWO_PI * freq / rate)
    out = [0.0] * len(x)
    y = 0.0
    for i, v in enumerate(x):
        y += k * (v - y)
        out[i] = y
    return out


def dc_block(x, rate, freq=25.0):
    r = math.exp(-TWO_PI * freq / rate)
    out = [0.0] * len(x)
    xp = yp = 0.0
    for i, v in enumerate(x):
        yp = v - xp + r * yp
        xp = v
        out[i] = yp
    return out


def mix_into(dest, src, offset, gain=1.0):
    """Add `src` x gain into `dest` from `offset`, clipped to dest's length; a negative
    offset drops the head. Returns the number of samples that fell off the end."""
    n = len(dest)
    if offset < 0:
        src = src[-offset:]
        offset = 0
    end = min(n, offset + len(src))
    if end <= offset:
        return len(src)
    count = end - offset
    if gain == 1.0:
        dest[offset:end] = [a + b for a, b in zip(dest[offset:end], src)]
    else:
        dest[offset:end] = [a + b * gain for a, b in zip(dest[offset:end], src)]
    return len(src) - count


def peak(*channels):
    return max((max(abs(min(c, default=0.0)), abs(max(c, default=0.0))) for c in channels),
               default=0.0)


def rms(*channels):
    total = sum(math.fsum(v * v for v in c) for c in channels)
    count = sum(len(c) for c in channels)
    return math.sqrt(total / count) if count else 0.0


# -- effects (block-wise) ------------------------------------------------------------------------

def _comb(x, delay, feedback, damp):
    """y[n] = x[n] + feedback * (damp * y[n-D] + (1-damp) * y[n-D-1])."""
    n = len(x)
    y = list(x[:delay]) + [0.0] * (n - delay)
    a, b = feedback * damp, feedback * (1.0 - damp)
    for start in range(delay, n, delay):
        end = min(n, start + delay)
        prev = y[start - delay:end - delay]
        prev2 = y[start - delay - 1:end - delay - 1] if start - delay - 1 >= 0 else \
            [0.0] + y[start - delay:end - delay - 1]
        y[start:end] = [xi + a * p + b * q for xi, p, q in zip(x[start:end], prev, prev2)]
    return y


def _allpass(x, delay, g):
    """y[n] = -g x[n] + x[n-D] + g y[n-D]."""
    n = len(x)
    y = [-g * v for v in x[:delay]] + [0.0] * (n - delay)
    for start in range(delay, n, delay):
        end = min(n, start + delay)
        y[start:end] = [-g * xi + xd + g * yd for xi, xd, yd in
                        zip(x[start:end], x[start - delay:end - delay], y[start - delay:end - delay])]
    return y


_COMBS = (1116, 1188, 1277, 1356, 1422, 1491, 1557, 1617)
_ALLPASSES = (556, 441, 341, 225)


def reverb(left, right, rate, *, seconds=2.0, size=1.0, damp=0.55, wet=0.3, predelay=0.012,
           spread=23, combs=6):
    """A Schroeder/Freeverb-style stereo reverb: parallel damped combs into series
    all-passes. Returns (left, right) wet signals scaled by `wet`."""
    mono = [(a + b) * 0.5 for a, b in zip(left, right)]
    pre = int(predelay * rate)
    if pre:
        mono = [0.0] * pre + mono[:len(mono) - pre]
    factor = rate / 44100.0 * size
    outs = []
    for side in (0, spread):
        acc = [0.0] * len(mono)
        for base in _COMBS[:combs]:
            d = max(8, int((base + side) * factor))
            fb = 10.0 ** (-3.0 * d / (seconds * rate))
            y = _comb(mono, d, fb, damp)
            acc = [s + v for s, v in zip(acc, y)]
        for base in _ALLPASSES:
            d = max(4, int((base + side) * factor))
            acc = _allpass(acc, d, 0.5)
        g = wet / combs
        outs.append([v * g for v in acc])
    return outs[0], outs[1]


def pingpong(left, right, rate, *, time=0.375, feedback=0.4, wet=0.25, damp=0.7):
    """A ping-pong delay: taps alternate left and right, softened in the loop."""
    d = max(2, int(time * rate))
    mono = [(a + b) * 0.5 for a, b in zip(left, right)]
    n = len(mono)
    out_l = [0.0] * n
    out_r = [0.0] * n
    a, b = feedback * damp, feedback * (1.0 - damp)
    # L[n] = x[n-D] + fb*R[n-D] ; R[n] = fb*L[n-D]   (the first tap on the left)
    for start in range(d, n, d):
        end = min(n, start + d)
        xs = mono[start - d:end - d]
        r_prev = out_r[start - d:end - d]
        r_prev2 = out_r[start - d - 1:end - d - 1] if start - d - 1 >= 0 else [0.0] + r_prev[:-1]
        l_prev = out_l[start - d:end - d]
        l_prev2 = out_l[start - d - 1:end - d - 1] if start - d - 1 >= 0 else [0.0] + l_prev[:-1]
        out_l[start:end] = [x + a * p + b * q for x, p, q in zip(xs, r_prev, r_prev2)]
        out_r[start:end] = [a * p + b * q for p, q in zip(l_prev, l_prev2)]
    return [v * wet for v in out_l], [v * wet for v in out_r]


def _gain_curve(gains, block, n):
    out = [0.0] * n
    ramp = [i / block for i in range(block)]
    for k in range(len(gains)):
        start = k * block
        end = min(n, start + block)
        g0 = gains[k]
        g1 = gains[k + 1] if k + 1 < len(gains) else g0
        dg = g1 - g0
        out[start:end] = [g0 + dg * r for r in ramp[:end - start]]
    return out


def compress(left, right, rate, *, threshold=-18.0, ratio=3.0, knee=6.0, attack=0.012,
             release=0.22, makeup=0.0, block=64):
    """A glue compressor on block peaks (stereo-linked). Returns (left, right)."""
    n = len(left)
    blocks = (n + block - 1) // block
    att = math.exp(-block / (attack * rate))
    rel = math.exp(-block / (release * rate))
    env = 0.0
    gains = []
    for k in range(blocks):
        s, e = k * block, min(n, k * block + block)
        level = max(max(map(abs, left[s:e]), default=0.0), max(map(abs, right[s:e]), default=0.0))
        coef = att if level > env else rel
        env = level + (env - level) * coef
        db = 20.0 * math.log10(env) if env > 1e-9 else -180.0
        over = db - threshold
        if over <= -knee / 2:
            red = 0.0
        elif over >= knee / 2:
            red = over * (1.0 - 1.0 / ratio)
        else:
            red = (1.0 - 1.0 / ratio) * (over + knee / 2) ** 2 / (2 * knee)
        gains.append(10.0 ** ((makeup - red) / 20.0))
    curve = _gain_curve(gains, block, n)
    return [a * g for a, g in zip(left, curve)], [b * g for b, g in zip(right, curve)]


def limit(left, right, rate, *, ceiling_db=-1.0, release=0.08, block=32):
    """A look-ahead brick-wall limiter on block peaks; a final scale guarantees the ceiling."""
    ceiling = 10.0 ** (ceiling_db / 20.0)
    n = len(left)
    blocks = (n + block - 1) // block
    peaks = []
    for k in range(blocks):
        s, e = k * block, min(n, k * block + block)
        peaks.append(max(max(map(abs, left[s:e]), default=0.0),
                         max(map(abs, right[s:e]), default=0.0)))
    rel = math.exp(-block / (release * rate))
    need = [min(1.0, ceiling / p) if p > 0 else 1.0 for p in peaks]
    gains = [1.0] * blocks
    g = 1.0
    for k in range(blocks):
        target = min(need[max(0, k - 1):k + 2])
        g = target if target < g else target + (g - target) * rel
        gains[k] = g
    curve = _gain_curve(gains, block, n)
    left = [a * c for a, c in zip(left, curve)]
    right = [b * c for b, c in zip(right, curve)]
    top = peak(left, right)
    if top > ceiling:
        left = [a * ceiling / top for a in left]
        right = [b * ceiling / top for b in right]
    return left, right

"""Measuring rendered audio: what the producer records and the tests assert.

    stats(channels, rate, loop=False) -> {duration_s, sample_rate, channels, rms_dbfs,
        peak_dbfs, crest_db, lufs, loudest_s_dbfs, quietest_s_dbfs, seam: {...}, bands}

`lufs` is the integrated loudness of ITU-R BS.1770-4 (K-weighting, 400 ms blocks with 75 %
overlap, the -70 LUFS absolute and -10 LU relative gates). `seam` is how a loop's end meets
its start: the end-to-start step against the typical step between neighbouring samples
(the same measure as audiofile.seam). `bands` is the energy share in six octave-ish bands,
a coarse timbre fingerprint two tracks can be told apart by (`distance`).
"""

import math

__all__ = ["stats", "lufs", "seam", "bands", "distance"]

BAND_EDGES = (20, 150, 400, 1000, 2500, 6000, 16000)


def _db(value):
    return round(20.0 * math.log10(value), 2) if value > 0 else None


def _biquad(x, b, a):
    b0, b1, b2 = b
    _a0, a1, a2 = a
    out = [0.0] * len(x)
    x1 = x2 = y1 = y2 = 0.0
    for i, v in enumerate(x):
        y = b0 * v + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2
        x2, x1, y2, y1 = x1, v, y1, y
        out[i] = y
    return out


def _k_weight(x, rate):
    f0, gain, q = 1681.974450955533, 3.999843853973347, 0.7071752369554196
    k = math.tan(math.pi * f0 / rate)
    vh = 10 ** (gain / 20.0)
    vb = vh ** 0.4996667741545416
    a0 = 1 + k / q + k * k
    stage1 = _biquad(x, ((vh + vb * k / q + k * k) / a0, 2 * (k * k - vh) / a0,
                         (vh - vb * k / q + k * k) / a0),
                     (1.0, 2 * (k * k - 1) / a0, (1 - k / q + k * k) / a0))
    f0, q = 38.13547087602444, 0.5003270373238773
    k = math.tan(math.pi * f0 / rate)
    a0 = 1 + k / q + k * k
    return _biquad(stage1, (1.0, -2.0, 1.0),
                   (1.0, 2 * (k * k - 1) / a0, (1 - k / q + k * k) / a0))


def lufs(channels, rate):
    """Integrated loudness (LUFS), or None for silence or < 400 ms."""
    weighted = [_k_weight(list(c), rate) for c in channels]
    n = len(weighted[0])
    block, hop = int(0.4 * rate), int(0.1 * rate)
    if n < block:
        return None
    powers = []
    squares = [[v * v for v in c] for c in weighted]
    prefix = []
    for sq in squares:
        acc, run = [0.0], 0.0
        for v in sq:
            run += v
            acc.append(run)
        prefix.append(acc)
    for start in range(0, n - block + 1, hop):
        z = sum((p[start + block] - p[start]) / block for p in prefix)
        powers.append(z)
    gated = [z for z in powers if z > 0 and -0.691 + 10 * math.log10(z) > -70.0]
    if not gated:
        return None
    relative = -0.691 + 10 * math.log10(sum(gated) / len(gated)) - 10.0
    kept = [z for z in gated if -0.691 + 10 * math.log10(z) > relative]
    return round(-0.691 + 10 * math.log10(sum(kept) / len(kept)), 2) if kept else None


def seam(channels, rate, edge_ms=50):
    n = len(channels[0])
    if n < 4:
        return None
    edge = max(2, min(n // 4, int(edge_ms / 1000.0 * rate)))
    jump = steps = head = tail = 0.0
    count = 0
    stride = max(1, n // 400_000)
    for c in channels:
        jump = max(jump, abs(c[-1] - c[0]))
        for i in range(stride, n, stride):
            steps += abs(c[i] - c[i - 1])
            count += 1
        head += math.fsum(v * v for v in c[:edge])
        tail += math.fsum(v * v for v in c[n - edge:])
    typical = steps / count if count else 0.0
    ratio = jump / typical if typical > 0 else (0.0 if jump == 0 else math.inf)
    edge_db = abs(10 * math.log10(max(head, 1e-18) / max(tail, 1e-18)))
    return {"jump": round(jump, 5), "typical_step": round(typical, 5),
            "ratio": round(ratio, 2), "edge_db": round(edge_db, 2)}


def bands(channels, rate):
    """Energy share per band (BAND_EDGES), from a mono fold, summing to 1."""
    from .dsp import biquad
    mono = [sum(v) / len(channels) for v in zip(*channels)]
    stride = max(1, len(mono) // (rate * 20))  # at most ~20 s of it
    if stride > 1:
        mono = mono[:rate * 20]
    shares = []
    for lo, hi in zip(BAND_EDGES, BAND_EDGES[1:]):
        if hi >= rate / 2:
            hi = rate / 2 * 0.95
        part = biquad(biquad(mono, "highpass", lo, rate), "lowpass", hi, rate)
        shares.append(math.fsum(v * v for v in part))
    total = sum(shares) or 1.0
    return [round(s / total, 4) for s in shares]


def distance(a, b):
    """Cosine distance of two band profiles: 0 identical timbre, 1 nothing in common."""
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return round(1.0 - dot / (na * nb), 4) if na and nb else 1.0


def stats(channels, rate, *, loop=False, loudness=True):
    n = len(channels[0])
    total = sum(math.fsum(v * v for v in c) for c in channels)
    rms = math.sqrt(total / (n * len(channels))) if n else 0.0
    peak = max(max(abs(min(c)), abs(max(c))) for c in channels) if n else 0.0
    window = rate
    windows = []
    for start in range(0, max(1, n - window + 1), window):
        acc = sum(math.fsum(v * v for v in c[start:start + window]) for c in channels)
        windows.append(math.sqrt(acc / (min(window, n - start) * len(channels))))
    out = {"duration_s": round(n / rate, 4), "sample_rate": rate, "channels": len(channels),
           "rms_dbfs": _db(rms), "peak_dbfs": _db(peak),
           "crest_db": round(_db(peak) - _db(rms), 2) if rms and peak else None,
           "loudest_s_dbfs": _db(max(windows)) if windows and n >= window else None,
           "quietest_s_dbfs": _db(min(windows)) if windows and n >= window else None}
    if loudness:
        out["lufs"] = lufs(channels, rate)
    if loop:
        out["seam"] = seam(channels, rate)
    return out

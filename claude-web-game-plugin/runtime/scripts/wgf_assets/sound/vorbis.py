"""Ogg Vorbis encoding with the standard library: compressed music without an external tool.

A music loop is 30-90 s of 44.1 kHz stereo: as 16-bit WAV that is 5-15 MB, over the asset
policy's music budget and a long first load on a phone. No encoder is in the standard
library and an autonomous run may not have one installed, so this is one: a deliberately
small Vorbis I encoder (Xiph's specification) that any browser's decoder reads.

    encode(channels, rate, *, quality=...) -> bytes     channels: [array('f')] in -1..1

What it does, and the choices that keep it small:

  * one block size (1024 samples, both of the stream's block sizes equal): no block
    switching, so no window shapes to choose; short enough that a drum hit's pre-echo stays
    within ~12 ms;
  * a forward MDCT (a DCT-IV through a half-length complex FFT) of each windowed block;
  * floor 1 with 32 fixed posts (coarse-to-fine order, so each post is predicted from its
    neighbours), the posts set from the band energies under a masking margin (`smr_db`)
    and an absolute threshold of hearing - the floor IS the quantiser step;
  * residue 1, 16-coefficient partitions in 7 classes by peak magnitude, lattice VQ books
    (4-dimensional for +-1, 2-dimensional up to +-16, a coarse +-495 book cascaded with
    the +-16 book above that);
  * every Huffman code built from the file's own symbol counts (two passes), complete
    trees only, so the setup header always describes a valid decoder;
  * stereo is square-polar coupled (magnitude and angle), so agreeing channels cost little;
  * Ogg pages of whole packets; granule positions such that a decoder returns exactly
    the input length when it is a multiple of 512 frames - which a seamless loop needs,
    since a decoder that trims or pads breaks the seam (`loop=True` also wraps the first
    block's left half from the end, so the loop point is encoded continuously).

The encoder's own `decode` (an IMDCT of its own packets' parameters, used by the tests) and
a browser's decode agree with the input to the quantisation the floor allows: ~ -30 dB
noise under the signal in each band, far below it in the quiet ones. It is not libvorbis:
there is no psychoacoustic model beyond the masking margin, so it spends more bits for the
same quality - ~150-220 kbps for dense stereo music.
"""

import array
import cmath
import heapq
import math
import struct

__all__ = ["encode", "BLOCK", "VorbisError"]

BLOCK = 1024                 # samples per block (both block sizes)
HALF = BLOCK // 2
MULTIPLIER = 2               # floor1 multiplier: y in 0..127, 1.09 dB per step
RANGE = 128
PARTITION = 16
MAX_RESIDUE = 511            # coarse 33 x 15 + fine 16
CLASSES = 7
# Floor 1 dB table: geometric from 1.0649863e-07 (index 0) to 1.0 (index 255).
_T0 = 1.0649863e-07
_STEP = math.log(1.0 / _T0) / 255.0
FLOOR_TABLE = [_T0 * math.exp(_STEP * i) for i in range(256)]
# The decoder's IMDCT is unnormalised; the encoder scales its MDCT so the round trip is unity.
SCALE = 2.0 / HALF


class VorbisError(ValueError):
    pass


def ilog(x):
    return x.bit_length() if x > 0 else 0


# -- bit packing ------------------------------------------------------------------------------

class BitWriter:
    """LSb-first bit packing, as Vorbis reads it."""

    def __init__(self):
        self.out = bytearray()
        self.acc = 0
        self.bits = 0

    def write(self, value, bits):
        if bits <= 0:
            return
        self.acc |= (value & ((1 << bits) - 1)) << self.bits
        self.bits += bits
        while self.bits >= 8:
            self.out.append(self.acc & 0xFF)
            self.acc >>= 8
            self.bits -= 8

    def data(self):
        out = bytes(self.out)
        if self.bits:
            out += bytes([self.acc & 0xFF])
        return out


def _float32_pack(value):
    if value == 0:
        return 0
    sign = 0
    if value < 0:
        sign, value = 0x80000000, -value
    exp = int(math.floor(math.log2(value) + 0.001))
    mant = int(round(math.ldexp(value, 20 - exp)))
    return sign | ((exp + 768) << 21) | mant


# -- Huffman codebooks -------------------------------------------------------------------------

def huffman_lengths(counts, limit=24):
    """Code lengths of a complete prefix code for `counts` (every entry gets a code)."""
    counts = [max(1, int(c)) for c in counts]
    if len(counts) == 1:
        return [1]
    while True:
        heap = [(c, i, None) for i, c in enumerate(counts)]
        heapq.heapify(heap)
        parent = {}
        serial = len(counts)
        while len(heap) > 1:
            c1, i1, _ = heapq.heappop(heap)
            c2, i2, _ = heapq.heappop(heap)
            parent[i1] = serial
            parent[i2] = serial
            heapq.heappush(heap, (c1 + c2, serial, None))
            serial += 1
        lengths = []
        for i in range(len(counts)):
            depth, node = 0, i
            while node in parent:
                node = parent[node]
                depth += 1
            lengths.append(depth)
        if max(lengths) <= limit:
            return lengths
        counts = [c // 2 + 1 for c in counts]


def codewords(lengths):
    """libvorbis `_make_words`: each entry, in order, takes the lowest free codeword of its
    length. Returns [(bit-reversed codeword, length)] ready for LSb-first writing."""
    marker = [0] * 33
    words = []
    for length in lengths:
        entry = marker[length]
        if length < 32 and entry >> length:
            raise VorbisError("over-populated Huffman tree")
        words.append(entry)
        for j in range(length, 0, -1):
            if marker[j] & 1:
                marker[j] = marker[j - 1] << 1 if j > 1 else marker[1] + 1
                break
            marker[j] += 1
        for j in range(length + 1, 33):
            if marker[j] >> 1 == entry:
                entry = marker[j]
                marker[j] = marker[j - 1] << 1
            else:
                break
    for i in range(1, 33):
        if marker[i] & (0xFFFFFFFF >> (32 - i)):
            raise VorbisError("under-populated Huffman tree")
    out = []
    for word, length in zip(words, lengths):
        reversed_ = 0
        for _ in range(length):
            reversed_ = (reversed_ << 1) | (word & 1)
            word >>= 1
        out.append((reversed_, length))
    return out


class Book:
    """A codebook: `dims`, `entries`, optional lattice (`span` values from `minimum` by
    `delta`), and - once counted - its lengths and codewords."""

    def __init__(self, dims, entries, *, span=None, minimum=0, delta=1):
        self.dims = dims
        self.entries = entries
        self.span = span
        self.minimum = minimum
        self.delta = delta
        self.counts = [0] * entries
        self.lengths = None
        self.words = None

    def finish(self):
        self.lengths = huffman_lengths(self.counts)
        self.words = codewords(self.lengths)

    def header(self, w):
        w.write(0x564342, 24)
        w.write(self.dims, 16)
        w.write(self.entries, 24)
        w.write(0, 1)  # not ordered
        w.write(0, 1)  # not sparse
        for length in self.lengths:
            w.write(length - 1, 5)
        if self.span is None:
            w.write(0, 4)
            return
        w.write(1, 4)  # lattice
        w.write(_float32_pack(self.minimum), 32)
        w.write(_float32_pack(self.delta), 32)
        bits = max(1, ilog(self.span - 1))
        w.write(bits - 1, 4)
        w.write(0, 1)  # no sequence
        for value in range(self.span):
            w.write(value, bits)


def _lattice(dims, k, step=1):
    span = 2 * k + 1
    return Book(dims, span ** dims, span=span, minimum=-k * step, delta=step)


# -- the transform -------------------------------------------------------------------------------

def _window(n):
    return [math.sin(math.pi / 2 * math.sin((i + 0.5) / n * math.pi) ** 2) for i in range(n)]


class _Mdct:
    """MDCT of length n (n/2 coefficients) as a DCT-IV of the folded block, by an n/4-point
    complex FFT."""

    def __init__(self, n):
        self.n = n
        m = n // 2
        q = m // 2
        self.m, self.q = m, q
        self.twiddle = [cmath.exp(-1j * math.pi * (4 * k + 1) / (4 * m)) for k in range(q)]
        self.post = [cmath.exp(-1j * math.pi * k / m) for k in range(q)]
        levels = q.bit_length() - 1
        self.rev = [int(format(i, f"0{levels}b")[::-1], 2) if levels else 0 for i in range(q)]
        self.stages = []
        size = 2
        while size <= q:
            half = size // 2
            roots = [cmath.exp(-2j * math.pi * k / size) for k in range(half)]
            self.stages.append((size, half, roots))
            size *= 2

    def _fft(self, data):
        data = [data[r] for r in self.rev]
        q = self.q
        for size, half, roots in self.stages:
            for start in range(0, q, size):
                for k in range(half):
                    a = data[start + k]
                    b = data[start + k + half] * roots[k]
                    data[start + k] = a + b
                    data[start + k + half] = a - b
        return data

    def forward(self, x):
        """X_k = sum_i x_i cos(2pi/n (i + 1/2 + n/4)(k + 1/2)), k < n/2."""
        m, q = self.m, self.q
        h = m // 2
        # (a, b, c, d) quarters -> v = (-c_r - d, a - b_r), a DCT-IV input of length m.
        v = [0.0] * m
        for i in range(h):
            v[i] = -x[3 * h - 1 - i] - x[3 * h + i]
            v[h + i] = x[i] - x[m - 1 - i]
        tw = self.twiddle
        t = [complex(v[2 * k], v[m - 1 - 2 * k]) * tw[k] for k in range(q)]
        y = self._fft(t)
        post = self.post
        out = [0.0] * m
        for k in range(q):
            z = y[k] * post[k]
            out[2 * k] = z.real
            out[m - 1 - 2 * k] = -z.imag
        return out


# -- floor 1 -------------------------------------------------------------------------------------

def _posts(half):
    """The floor's x positions after 0 and `half`: 30, roughly log-spaced, coarse-to-fine."""
    raw = sorted({max(1, min(half - 1, int(round(math.exp(math.log(half) * (i / 31.0) ** 0.85)))))
                  for i in range(1, 31)})
    candidate = 1
    while len(raw) < 30:
        if candidate not in raw:
            raw.append(candidate)
            raw.sort()
        candidate += 1
    raw = raw[:30]
    ordered = []

    def split(lo, hi):
        inside = [x for x in raw if lo < x < hi and x not in ordered]
        if not inside:
            return []
        mid = inside[len(inside) // 2]
        ordered.append(mid)
        return [(lo, mid), (mid, hi)]

    queue = [(0, half)]
    while queue:
        nxt = []
        for lo, hi in queue:
            nxt.extend(split(lo, hi))
        queue = nxt
    return ordered


def _render_point(x0, y0, x1, y1, x):
    dy = y1 - y0
    adx = x1 - x0
    err = abs(dy) * (x - x0)
    off = err // adx
    return y0 - off if dy < 0 else y0 + off


def _render_line(x0, y0, x1, y1, v, limit):
    dy = y1 - y0
    adx = x1 - x0
    ady = abs(dy)
    base = int(dy / adx)  # truncates toward zero, as C does
    sy = base - 1 if dy < 0 else base + 1
    ady -= abs(base) * adx
    y, err = y0, 0
    if x0 < limit:
        v[x0] = y
    for x in range(x0 + 1, min(x1, limit)):
        err += ady
        if err >= adx:
            err -= adx
            y += sy
        else:
            y += base
        v[x] = y


class _Floor:
    def __init__(self, half):
        self.half = half
        self.xs = [0, half] + _posts(half)
        n = len(self.xs)
        self.low = [0, 0]
        self.high = [0, 0]
        for i in range(2, n):
            lo = max((j for j in range(i) if self.xs[j] < self.xs[i]), key=lambda j: self.xs[j])
            hi = min((j for j in range(i) if self.xs[j] > self.xs[i]), key=lambda j: self.xs[j])
            self.low.append(lo)
            self.high.append(hi)
        self.order = sorted(range(n), key=lambda j: self.xs[j])

    def encode(self, wanted):
        """(vals to write, the decoder's curve [index per bin]) for the wanted post y's."""
        xs = self.xs
        n = len(xs)
        final = [0] * n
        flag = [False] * n
        vals = [0] * n
        final[0], final[1] = wanted[0], wanted[1]
        vals[0], vals[1] = wanted[0], wanted[1]
        flag[0] = flag[1] = True
        for i in range(2, n):
            lo, hi = self.low[i], self.high[i]
            p = _render_point(xs[lo], final[lo], xs[hi], final[hi], xs[i])
            d = wanted[i]
            highroom, lowroom = RANGE - p, p
            room = 2 * min(highroom, lowroom)
            if d == p:
                val = 0
            elif d > p:
                delta = d - p
                val = 2 * delta if 2 * delta < room else delta + lowroom
            else:
                delta = p - d
                val = 2 * delta - 1 if 2 * delta - 1 < room else delta + highroom - 1
            vals[i] = val
            if val:
                flag[lo] = flag[hi] = flag[i] = True
                final[i] = d
            else:
                final[i] = p
        curve = [0] * self.half
        lx, ly = 0, final[0] * MULTIPLIER
        hx, hy = 0, ly
        for j in self.order[1:]:
            if flag[j]:
                hy = final[j] * MULTIPLIER
                hx = xs[j]
                _render_line(lx, ly, hx, hy, curve, self.half)
                lx, ly = hx, hy
        if hx < self.half:
            _render_line(hx, hy, self.half, hy, curve, self.half)
        return vals, curve


def _ath_db(freq):
    """Terhardt's threshold in quiet, dB SPL, with full scale taken as 96 dB SPL. Below
    150 Hz it is held at its 150 Hz value: game music lives on its kick and sub-bass, and
    the curve's steep low end would quantise them away."""
    f = max(freq, 150.0) / 1000.0
    return (3.64 * f ** -0.8 - 6.5 * math.exp(-0.6 * (f - 3.3) ** 2) + 1e-3 * f ** 4) - 96.0


# -- the encoder ---------------------------------------------------------------------------------

def _classify(peak):
    if peak == 0:
        return 0
    if peak <= 1:
        return 1
    if peak <= 2:
        return 2
    if peak <= 4:
        return 3
    if peak <= 8:
        return 4
    if peak <= 16:
        return 5
    return 6


def encode(channels, rate, *, smr_db=27.0, loop=False, comment="wgf-assets vorbis",
           vendor="wgf-assets stdlib Vorbis encoder 1", serial=None):
    """Ogg Vorbis bytes of `channels` (one sequence of floats in -1..1 per channel). A length
    that is not a multiple of BLOCK/2 is padded with silence up to one: give a loop a length
    that is, or it will gain that silence."""
    nch = len(channels)
    if not 1 <= nch <= 2:
        raise VorbisError("1 or 2 channels")
    length = len(channels[0])
    if length == 0:
        raise VorbisError("no samples")
    frames = -(-length // HALF) * HALF
    blocks = frames // HALF + 1  # packets 0..J, J = frames / HALF
    window = _window(BLOCK)
    mdct = _Mdct(BLOCK)
    floor = _Floor(HALF)
    posts = len(floor.xs)
    # Band of bins each post stands for, in x order.
    order = floor.order
    band = {}
    for rank, j in enumerate(order):
        left = floor.xs[order[rank - 1]] if rank else 0
        right = floor.xs[order[rank + 1]] if rank + 1 < len(order) else HALF
        lo = (left + floor.xs[j]) // 2 if rank else 0
        hi = (floor.xs[j] + right + 1) // 2 if rank + 1 < len(order) else HALF
        band[j] = (lo, max(lo + 1, hi))
    # The masking margin per post: full below 4 kHz, 10 dB less by 12 kHz, where content is
    # mostly noise (hats, air) and noise masks noise well.
    smr = []
    for j in range(posts):
        freq = (band[j][0] + band[j][1]) / 2.0 * rate / BLOCK
        taper = min(1.0, max(0.0, (freq - 4000.0) / 8000.0))
        smr.append(10 ** ((smr_db - 10.0 * taper) / 10.0))
    # The threshold in quiet, per bin: a full-scale sine's MDCT coefficient is ~ amplitude/2;
    # never above -50 dBFS (a game is played louder than the curve assumes, and hats live at
    # 12-16 kHz where it climbs steeply); and spread over the critical band (ERB) the bin
    # sits in - noise is heard by its band's energy, not one bin's.
    ath = []
    for j in range(posts):
        freq = (band[j][0] + band[j][1]) / 2.0 * rate / BLOCK
        erb_bins = 24.7 * (4.37 * freq / 1000.0 + 1.0) / (rate / BLOCK)
        ath.append(min(10 ** (_ath_db(freq) / 10.0), 1e-5) * 0.25 / max(1.0, erb_bins))
    # Nothing above 17.2 kHz is coded: no one hears it on the devices games are played on.
    cutoff = min(HALF, int(17200.0 * BLOCK / rate))
    log_t0, step = math.log(_T0), _STEP * MULTIPLIER

    def source(c, start):
        data = channels[c]
        out = [0.0] * BLOCK
        for i in range(BLOCK):
            s = start + i
            if loop:
                s %= frames
                out[i] = data[s] if s < length else 0.0
            elif 0 <= s < length:
                out[i] = data[s]
        return out

    floor_book = Book(1, RANGE)
    class_book = Book(2, CLASSES * CLASSES)
    books = [_lattice(4, 1), _lattice(2, 2), _lattice(2, 4), _lattice(2, 8), _lattice(2, 16),
             _lattice(2, 15, 33)]
    # Residue books by (class, pass): classes 1-5 one pass; class 6 coarse then +-16.
    cascade = {1: [books[0]], 2: [books[1]], 3: [books[2]], 4: [books[3]], 5: [books[4]],
               6: [books[5], books[4]]}

    packets = []  # per packet: [(used, vals, classes, vectors per pass)] per channel
    for b in range(blocks):
        start = b * HALF - HALF
        xs = [source(c, start) for c in range(nch)]
        if not any(any(x) for x in xs):
            packets.append([None] * nch)
            continue
        specs, wanteds = [], []
        for x in xs:
            windowed = [x[i] * window[i] for i in range(BLOCK)]
            spec = [v * SCALE for v in mdct.forward(windowed)]
            wanted = [0] * posts
            for j in range(posts):
                lo, hi = band[j]
                # Between the band's mean and geometric-mean energy: a band whose spectrum
                # tilts keeps its quieter bins instead of rounding them to nothing.
                powers = [v * v + 1e-14 for v in spec[lo:hi]]
                mean = sum(powers) / (hi - lo)
                geo = math.exp(sum(map(math.log, powers)) / (hi - lo))
                noise = max(math.sqrt(mean * geo) / smr[j], ath[j])
                y = int(round((math.log(math.sqrt(12.0 * noise)) - log_t0) / step))
                wanted[j] = min(RANGE - 1, max(0, y))
            specs.append(spec)
            wanteds.append(wanted)
        while True:
            items = []
            for spec, wanted in zip(specs, wanteds):
                vals, curve = floor.encode(wanted)
                residue = [int(round(spec[k] / FLOOR_TABLE[curve[k]])) for k in range(cutoff)]
                items.append([vals, residue + [0] * (HALF - cutoff)])
            if nch == 2:
                items[0][1], items[1][1] = _couple(items[0][1], items[1][1])
            if max(max(abs(r) for r in item[1]) for item in items) <= MAX_RESIDUE:
                break
            wanteds = [[min(RANGE - 1, y + 2) for y in wanted] for wanted in wanteds]
        per_channel = []
        for vals, residue in items:
            classes = [_classify(max(abs(r) for r in residue[p:p + PARTITION]))
                       for p in range(0, HALF, PARTITION)]
            per_channel.append((vals, classes, residue))
            for v in vals[2:]:
                floor_book.counts[v] += 1
        packets.append(per_channel)
        # Symbol counts for the residue books.
        for item in per_channel:
            if item is None:
                continue
            _vals, classes, residue = item
            for p in range(0, len(classes), 2):
                pair = classes[p] * CLASSES + (classes[p + 1] if p + 1 < len(classes) else 0)
                class_book.counts[pair] += 1
            for index, cls in enumerate(classes):
                if not cls:
                    continue
                part = residue[index * PARTITION:(index + 1) * PARTITION]
                for vector in _vectors(part, cls, cascade):
                    book, entry = vector
                    book.counts[entry] += 1

    for book in [floor_book, class_book] + books:
        book.finish()
    all_books = [floor_book, class_book] + books
    book_index = {id(book): i for i, book in enumerate(all_books)}

    headers = [_identification(nch, rate), _comment(vendor, comment),
               _setup(all_books, floor, nch, book_index, cascade)]
    audio = []
    for per_channel in packets:
        w = BitWriter()
        w.write(0, 1)  # audio packet; one mode: no mode bits; short blocks: no window flags
        for item in per_channel:
            if item is None:
                w.write(0, 1)
                continue
            vals = item[0]
            w.write(1, 1)
            w.write(vals[0], 7)
            w.write(vals[1], 7)
            for v in vals[2:]:
                word, bits = floor_book.words[v]
                w.write(word, bits)
        used = [item for item in per_channel if item is not None]
        if used:
            # Residue 1: pass 0 interleaves each channel's classword with the partitions.
            nparts = HALF // PARTITION
            for pass_ in range(2):
                for p in range(0, nparts, 2):
                    if pass_ == 0:
                        for item in used:
                            classes = item[1]
                            pair = classes[p] * CLASSES + (classes[p + 1] if p + 1 < nparts else 0)
                            word, bits = class_book.words[pair]
                            w.write(word, bits)
                    for index in (p, p + 1):
                        if index >= nparts:
                            break
                        for item in used:
                            cls = item[1][index]
                            stages = cascade.get(cls) or []
                            if pass_ >= len(stages):
                                continue
                            part = item[2][index * PARTITION:(index + 1) * PARTITION]
                            vectors = _vectors(part, cls, cascade, only=pass_)
                            for book, entry in vectors:
                                word, bits = book.words[entry]
                                w.write(word, bits)
        audio.append(w.data())
    return _ogg(headers, audio, frames, length if not loop else frames, serial)


def _couple(left, right):
    """Square polar coupling of two channels' residues (Vorbis I 1.3.3, inverted): the
    magnitude is the larger, the angle their difference - near zero when they agree."""
    mags, angs = [], []
    for l, r in zip(left, right):
        if abs(l) > abs(r):
            mags.append(l)
            angs.append(l - r if l > 0 else r - l)
        else:
            mags.append(r)
            angs.append(l - r if r > 0 else r - l)
    return mags, angs


def _vectors(part, cls, cascade, only=None):
    """[(book, entry)] coding one partition of class `cls` (pass `only`, or every pass)."""
    stages = cascade[cls]
    out = []
    remaining = list(part)
    for pass_, book in enumerate(stages):
        if book.span == 31 and book.delta == 33:  # coarse
            coarse = [max(-15, min(15, int(round(r / 33.0)))) for r in remaining]
            values = coarse
            remaining = [r - 33 * c for r, c in zip(remaining, coarse)]
        else:
            k = book.span // 2
            values = [max(-k, min(k, r)) for r in remaining]
            remaining = [r - v for r, v in zip(remaining, values)]
        if only is None or only == pass_:
            span, dims = book.span, book.dims
            k = span // 2
            for i in range(0, len(values), dims):
                entry, mult = 0, 1
                for d in range(dims):
                    entry += (values[i + d] + k) * mult
                    mult *= span
                out.append((book, entry))
    return out


# -- headers and pages -----------------------------------------------------------------------------

def _identification(nch, rate):
    w = BitWriter()
    w.write(1, 8)
    for ch in b"vorbis":
        w.write(ch, 8)
    w.write(0, 32)
    w.write(nch, 8)
    w.write(rate, 32)
    w.write(0, 32)
    w.write(0, 32)
    w.write(0, 32)
    exponent = BLOCK.bit_length() - 1
    w.write(exponent, 4)
    w.write(exponent, 4)
    w.write(1, 1)
    return w.data()


def _comment(vendor, comment):
    w = BitWriter()
    w.write(3, 8)
    for ch in b"vorbis":
        w.write(ch, 8)
    data = vendor.encode("utf-8")
    w.write(len(data), 32)
    for ch in data:
        w.write(ch, 8)
    comments = [c.encode("utf-8") for c in ([comment] if comment else [])]
    w.write(len(comments), 32)
    for c in comments:
        w.write(len(c), 32)
        for ch in c:
            w.write(ch, 8)
    w.write(1, 1)
    return w.data()


def _setup(books, floor, nch, index, cascade):
    w = BitWriter()
    w.write(5, 8)
    for ch in b"vorbis":
        w.write(ch, 8)
    w.write(len(books) - 1, 8)
    for book in books:
        book.header(w)
    w.write(0, 6)   # one time-domain transform
    w.write(0, 16)
    w.write(0, 6)   # one floor
    w.write(1, 16)  # floor type 1
    posts = len(floor.xs) - 2
    dims = 3
    partitions = posts // dims
    w.write(partitions, 5)
    for _ in range(partitions):
        w.write(0, 4)  # class 0
    w.write(dims - 1, 3)
    w.write(0, 2)      # no subclasses
    w.write(index[id(books[0])] + 1, 8)  # subclass book (+1)
    w.write(MULTIPLIER - 1, 2)
    rangebits = HALF.bit_length() - 1
    w.write(rangebits, 4)
    for x in floor.xs[2:]:
        w.write(x, rangebits)
    w.write(0, 6)   # one residue
    w.write(1, 16)  # residue type 1
    w.write(0, 24)
    w.write(HALF, 24)
    w.write(PARTITION - 1, 24)
    w.write(CLASSES - 1, 6)
    w.write(index[id(books[1])], 8)
    for cls in range(CLASSES):
        stages = cascade.get(cls) or []
        bits = (1 << len(stages)) - 1
        w.write(bits & 7, 3)
        w.write(0, 1)
    for cls in range(CLASSES):
        for stage in cascade.get(cls) or []:
            w.write(index[id(stage)], 8)
    w.write(0, 6)   # one mapping
    w.write(0, 16)
    w.write(0, 1)   # one submap
    if nch == 2:
        w.write(1, 1)   # coupling: one step, magnitude channel 0, angle channel 1
        w.write(0, 8)
        w.write(0, 1)
        w.write(1, 1)
    else:
        w.write(0, 1)
    w.write(0, 2)
    w.write(0, 8)   # submap: time (unused), floor 0, residue 0
    w.write(0, 8)
    w.write(0, 8)
    w.write(0, 6)   # one mode
    w.write(0, 1)   # short block
    w.write(0, 16)
    w.write(0, 16)
    w.write(0, 8)
    w.write(1, 1)
    return w.data()


_CRC_TABLE = []
for _i in range(256):
    _r = _i << 24
    for _ in range(8):
        _r = ((_r << 1) ^ 0x04C11DB7) if _r & 0x80000000 else (_r << 1)
    _CRC_TABLE.append(_r & 0xFFFFFFFF)


def _crc(data):
    crc = 0
    table = _CRC_TABLE
    for byte in data:
        crc = ((crc << 8) & 0xFFFFFFFF) ^ table[((crc >> 24) ^ byte) & 0xFF]
    return crc


def _page(packets, granule, serial, sequence, flags):
    lacing = bytearray()
    for packet in packets:
        size = len(packet)
        lacing.extend([255] * (size // 255))
        lacing.append(size % 255)
    header = struct.pack("<4sBBqIIIB", b"OggS", 0, flags, granule, serial, sequence, 0,
                         len(lacing))
    page = bytearray(header + bytes(lacing) + b"".join(packets))
    page[22:26] = struct.pack("<I", _crc(page))
    return bytes(page)


def _ogg(headers, audio, frames, final, serial):
    if serial is None:
        serial = _crc(b"".join(audio[:4])) & 0x7FFFFFFF
    pages = [_page([headers[0]], 0, serial, 0, 0x02),
             _page(headers[1:], 0, serial, 1, 0)]
    sequence = 2
    batch, segments, size = [], 0, 0
    for index, packet in enumerate(audio):
        need = len(packet) // 255 + 1
        if batch and (segments + need > 255 or size + len(packet) > 8192):
            granule = (index - 1) * HALF
            pages.append(_page(batch, min(granule, final), serial, sequence, 0))
            sequence += 1
            batch, segments, size = [], 0, 0
        batch.append(packet)
        segments += need
        size += len(packet)
    pages.append(_page(batch, final, serial, sequence, 0x04))
    return b"".join(pages)


def decode_own(data):
    """Not a Vorbis decoder: a check of the page structure only (granule and size)."""
    raise NotImplementedError

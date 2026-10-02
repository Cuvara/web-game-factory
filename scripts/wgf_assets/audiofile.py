"""Reading audio files with the standard library: what quality.audio_quality judges.

    read(data) -> AudioInfo     the container's own account of the file: format, codec,
                                channels, sample rate, duration - and, for WAV, the samples

WAV is decoded: `wave` reads integer PCM (8, 16, 24 and 32 bit); 32-bit IEEE float, which
`wave` refuses, is read from the RIFF chunks directly. Ogg (Vorbis or Opus) and MP3 are not
decoded - the standard library has no codec - but their headers are read and checked: Ogg
page structure and CRCs, the codec identification header, and the duration from the last
page's granule position (less the Opus pre-skip); MP3 frame headers (after any ID3v2 tag),
counted frame by frame, or the Xing/Info header's frame count when one is present. A file
none of these can read raises AudioError with the reason.

`levels(info, window_s)` and `seam(info, edge_ms)` measure decoded samples (WAV only):
RMS and peak per window, and how the last frames meet the first ones when the file loops.
"""

import array
import io
import math
import struct
import sys
import wave

__all__ = ["AudioError", "AudioInfo", "read", "levels", "seam", "dbfs"]

MAX_DECODE_FRAMES = 48000 * 60 * 6  # longer WAVs are judged by their header only


class AudioError(ValueError):
    """The file is not audio this module can read, and why."""


class AudioInfo:
    def __init__(self, fmt, codec, channels, sample_rate, duration_s, *, frames=None,
                 samples=None, notes=None):
        self.format = fmt              # wav | ogg | mp3
        self.codec = codec             # pcm | float | vorbis | opus | mp3
        self.channels = channels
        self.sample_rate = sample_rate
        self.duration_s = duration_s
        self.frames = frames
        self.samples = samples         # WAV: [array of floats in -1..1 per channel], or None
        self.notes = notes or []

    def summary(self):
        return (f"{self.format} ({self.codec}), {self.channels} ch, {self.sample_rate} Hz, "
                f"{self.duration_s:.3f} s")


def dbfs(value):
    return 20 * math.log10(value) if value > 0 else -math.inf


def read(data):
    data = bytes(data)
    if data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        return _wav(data)
    if data[:4] == b"OggS":
        return _ogg(data)
    if data[:3] == b"ID3" or (len(data) > 1 and data[0] == 0xFF and data[1] & 0xE0 == 0xE0):
        return _mp3(data)
    raise AudioError("not a WAV, Ogg or MP3 file")


# -- WAV ---------------------------------------------------------------------------------------

def _chunks(data):
    """{chunk id: (offset, size)} of a RIFF/WAVE file's top-level chunks."""
    out, offset = {}, 12
    while offset + 8 <= len(data):
        cid, size = struct.unpack("<4sI", data[offset:offset + 8])
        out.setdefault(cid, (offset + 8, size))
        offset += 8 + size + (size & 1)
    return out


def _wav(data):
    chunks = _chunks(data)
    if b"fmt " not in chunks or b"data" not in chunks:
        raise AudioError("a WAV file without a fmt or data chunk")
    offset, size = chunks[b"fmt "]
    if size < 16:
        raise AudioError("a WAV fmt chunk shorter than 16 bytes")
    tag, channels, rate, _byte_rate, block, bits = struct.unpack("<HHIIHH",
                                                                 data[offset:offset + 16])
    if tag == 0xFFFE and size >= 40:
        tag = struct.unpack("<H", data[offset + 24:offset + 26])[0]
    if channels < 1 or rate < 1 or block < 1:
        raise AudioError(f"a WAV header with {channels} channel(s) at {rate} Hz")
    d_offset, d_size = chunks[b"data"]
    d_size = min(d_size, len(data) - d_offset)
    frames = d_size // block
    duration = frames / rate
    if tag == 3 and bits == 32:
        codec = "float"
        decode = frames <= MAX_DECODE_FRAMES
        samples = None
        if decode:
            values = array.array("f")
            values.frombytes(data[d_offset:d_offset + frames * block])
            if sys.byteorder == "big":
                values.byteswap()
            samples = [values[c::channels] for c in range(channels)]
        return AudioInfo("wav", codec, channels, rate, duration, frames=frames, samples=samples)
    if tag != 1:
        raise AudioError(f"WAV format tag {tag} is neither PCM nor 32-bit float")
    try:
        with wave.open(io.BytesIO(data)) as handle:
            channels, width = handle.getnchannels(), handle.getsampwidth()
            rate, frames = handle.getframerate(), handle.getnframes()
            raw = handle.readframes(min(frames, MAX_DECODE_FRAMES))
    except (wave.Error, EOFError) as exc:
        raise AudioError(f"wave cannot read it: {exc}")
    duration = frames / rate
    samples = _pcm(raw, width, channels) if frames <= MAX_DECODE_FRAMES else None
    return AudioInfo("wav", "pcm", channels, rate, duration, frames=frames, samples=samples,
                     notes=[f"{8 * width}-bit PCM"])


def _pcm(raw, width, channels):
    """[array of floats per channel] from interleaved little-endian PCM."""
    if width == 1:
        values = [(b - 128) / 128.0 for b in raw]
    elif width == 2:
        ints = array.array("h")
        ints.frombytes(raw[:len(raw) - len(raw) % 2])
        if sys.byteorder == "big":
            ints.byteswap()
        values = [v / 32768.0 for v in ints]
    elif width == 3:
        values = [int.from_bytes(raw[i:i + 3], "little", signed=True) / 8388608.0
                  for i in range(0, len(raw) - 2, 3)]
    elif width == 4:
        ints = array.array("i")
        ints.frombytes(raw[:len(raw) - len(raw) % 4])
        if sys.byteorder == "big":
            ints.byteswap()
        values = [v / 2147483648.0 for v in ints]
    else:
        raise AudioError(f"{8 * width}-bit PCM")
    return [array.array("f", values[c::channels]) for c in range(channels)]


def levels(info, window_s=1.0):
    """{rms_dbfs, peak_dbfs, loudest_dbfs, quietest_dbfs, windows} over the decoded samples:
    the whole file's RMS and peak, and the loudest and quietest `window_s` window (a file
    shorter than one window is one window). None when the samples were not decoded."""
    if not info.samples:
        return None
    n = len(info.samples[0])
    if n == 0:
        return {"rms_dbfs": -math.inf, "peak_dbfs": -math.inf, "loudest_dbfs": -math.inf,
                "quietest_dbfs": -math.inf, "windows": 0}
    size = max(1, min(n, int(window_s * info.sample_rate)))
    # Long files are sampled every few frames: an RMS over a second does not need them all.
    stride = max(1, n // 2_000_000)
    windows, total, counted, peak = [], 0.0, 0, 0.0
    for start in range(0, n - size + 1 if n >= size else 1, size):
        acc, count = 0.0, 0
        for channel in info.samples:
            part = channel[start:start + size:stride]
            acc += math.fsum(v * v for v in part)
            count += len(part)
            peak = max(peak, max((abs(v) for v in part), default=0.0))
        windows.append(math.sqrt(acc / count) if count else 0.0)
        total += acc
        counted += count
    rms = math.sqrt(total / counted) if counted else 0.0
    return {"rms_dbfs": dbfs(rms), "peak_dbfs": dbfs(peak), "loudest_dbfs": dbfs(max(windows)),
            "quietest_dbfs": dbfs(min(windows)), "windows": len(windows)}


def seam(info, edge_ms=50):
    """How a looping file's end meets its start: {jump, typical_step, ratio, edge_db}.
    `jump` is the largest step from the last frame to the first over the channels;
    `typical_step` the mean absolute step between neighbouring frames; `edge_db` the level
    difference between the last and the first `edge_ms`. None when not decoded."""
    if not info.samples or len(info.samples[0]) < 4:
        return None
    n = len(info.samples[0])
    edge = max(2, min(n // 4, int(edge_ms / 1000.0 * info.sample_rate)))
    stride = max(1, n // 400_000)
    jump, steps, count, head, tail = 0.0, 0.0, 0, 0.0, 0.0
    for channel in info.samples:
        jump = max(jump, abs(channel[-1] - channel[0]))
        for i in range(stride, n, stride):
            steps += abs(channel[i] - channel[i - 1])
            count += 1
        head += math.fsum(v * v for v in channel[:edge])
        tail += math.fsum(v * v for v in channel[n - edge:])
    typical = steps / count if count else 0.0
    ratio = jump / typical if typical > 0 else (0.0 if jump == 0 else math.inf)
    edge_db = abs(dbfs(math.sqrt(head / edge) or 1e-9) - dbfs(math.sqrt(tail / edge) or 1e-9))
    return {"jump": jump, "typical_step": typical, "ratio": ratio, "edge_db": edge_db}


# -- Ogg -----------------------------------------------------------------------------------------

def _crc_table():
    table = []
    for i in range(256):
        r = i << 24
        for _ in range(8):
            r = ((r << 1) ^ 0x04C11DB7) if r & 0x80000000 else (r << 1)
        table.append(r & 0xFFFFFFFF)
    return table


_CRC = _crc_table()


def _ogg_crc(page):
    crc = 0
    for byte in page:
        crc = ((crc << 8) & 0xFFFFFFFF) ^ _CRC[((crc >> 24) ^ byte) & 0xFF]
    return crc


def _ogg(data):
    offset, pages, first_packet, serial, last_granule = 0, 0, None, None, None
    bad_crc = 0
    while offset < len(data):
        if data[offset:offset + 4] != b"OggS":
            raise AudioError(f"Ogg page {pages} does not start with OggS (byte {offset})")
        if offset + 27 > len(data):
            raise AudioError("a truncated Ogg page header")
        flags = data[offset + 5]
        granule, page_serial, _seq, crc, segments = struct.unpack(
            "<qIIIB", data[offset + 6:offset + 27])
        lacing = data[offset + 27:offset + 27 + segments]
        body = sum(lacing)
        end = offset + 27 + segments + body
        if end > len(data):
            raise AudioError(f"Ogg page {pages} is truncated")
        page = bytearray(data[offset:end])
        page[22:26] = b"\0\0\0\0"
        if _ogg_crc(page) != crc:
            bad_crc += 1
        if pages == 0:
            if not flags & 0x02:
                raise AudioError("the first Ogg page is not a beginning-of-stream page")
            serial = page_serial
            first_packet = data[offset + 27 + segments:end]
        if page_serial == serial and granule >= 0:
            last_granule = granule
        pages += 1
        offset = end
    if bad_crc:
        raise AudioError(f"{bad_crc} of {pages} Ogg page(s) fail their CRC")
    packet = first_packet or b""
    if packet[:7] == b"\x01vorbis" and len(packet) >= 16:
        channels = packet[11]
        rate = struct.unpack("<I", packet[12:16])[0]
        if not channels or not rate:
            raise AudioError("a Vorbis header with no channels or no sample rate")
        duration = (last_granule or 0) / rate
        return AudioInfo("ogg", "vorbis", channels, rate, duration, frames=last_granule,
                         notes=[f"{pages} pages"])
    if packet[:8] == b"OpusHead" and len(packet) >= 19:
        channels = packet[9]
        preskip = struct.unpack("<H", packet[10:12])[0]
        input_rate = struct.unpack("<I", packet[12:16])[0]
        if not channels:
            raise AudioError("an Opus header with no channels")
        frames = max(0, (last_granule or 0) - preskip)
        return AudioInfo("ogg", "opus", channels, 48000, frames / 48000.0, frames=frames,
                         notes=[f"{pages} pages", f"pre-skip {preskip}",
                                f"input rate {input_rate} Hz"])
    raise AudioError("an Ogg stream that is neither Vorbis nor Opus")


# -- MP3 ------------------------------------------------------------------------------------------

_BITRATES = {  # (MPEG-1?, layer) -> kbps by index
    (True, 3): [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320],
    (False, 3): [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160],
    (True, 2): [0, 32, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 384],
    (True, 1): [0, 32, 64, 96, 128, 160, 192, 224, 256, 288, 320, 352, 384, 416, 448],
}
_RATES = {3: (44100, 48000, 32000), 2: (22050, 24000, 16000), 0: (11025, 12000, 8000)}


def _mp3_header(data, offset):
    """(frame length, samples per frame, sample rate, channels) of the frame at `offset`, or
    None when no valid frame header is there."""
    if offset + 4 > len(data) or data[offset] != 0xFF or data[offset + 1] & 0xE0 != 0xE0:
        return None
    b1, b2, b3 = data[offset + 1], data[offset + 2], data[offset + 3]
    version = (b1 >> 3) & 3          # 3 = MPEG-1, 2 = MPEG-2, 0 = MPEG-2.5, 1 reserved
    layer = 4 - ((b1 >> 1) & 3)      # 1, 2, 3 (4 = reserved)
    rate_index, bitrate_index = (b2 >> 2) & 3, (b2 >> 4) & 15
    if version == 1 or layer == 4 or rate_index == 3 or bitrate_index in (0, 15):
        return None
    mpeg1 = version == 3
    table = _BITRATES.get((mpeg1, layer)) or _BITRATES[(False, 3)]
    bitrate = table[bitrate_index] * 1000
    rate = _RATES[version][rate_index]
    padding = (b2 >> 1) & 1
    channels = 1 if (b3 >> 6) == 3 else 2
    if layer == 1:
        return (12 * bitrate // rate + padding) * 4, 384, rate, channels
    per_frame = 1152 if (layer == 2 or mpeg1) else 576
    return per_frame // 8 * bitrate // rate + padding, per_frame, rate, channels


def _mp3(data):
    offset = 0
    if data[:3] == b"ID3" and len(data) >= 10:
        size = 0
        for byte in data[6:10]:
            size = (size << 7) | (byte & 0x7F)
        offset = 10 + size + (10 if data[5] & 0x10 else 0)
    while offset < len(data) - 4 and _mp3_header(data, offset) is None:
        offset += 1
        if offset > 65536:
            break
    first = _mp3_header(data, offset)
    if first is None:
        raise AudioError("no MPEG audio frame header")
    length, per_frame, rate, channels = first
    # A Xing/Info header (VBR, or LAME's gapless record) states the frame count.
    for side in (32, 17, 9, 21, 13):
        tag = data[offset + 4 + side:offset + 8 + side]
        if tag in (b"Xing", b"Info"):
            flags = struct.unpack(">I", data[offset + 8 + side:offset + 12 + side])[0]
            if flags & 1:
                count = struct.unpack(">I", data[offset + 12 + side:offset + 16 + side])[0]
                return AudioInfo("mp3", "mp3", channels, rate, count * per_frame / rate,
                                 frames=count * per_frame, notes=[f"{count} frames (Xing)"])
    frames, position = 0, offset
    while True:
        header = _mp3_header(data, position)
        if header is None or header[0] <= 0:
            break
        frames += 1
        position += header[0]
    if frames < 2:
        raise AudioError("fewer than two consecutive MPEG audio frames")
    return AudioInfo("mp3", "mp3", channels, rate, frames * per_frame / rate,
                     frames=frames * per_frame, notes=[f"{frames} frames"])

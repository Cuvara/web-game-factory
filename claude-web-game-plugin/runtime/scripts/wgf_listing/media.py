"""What a listing file is, read from its bytes: format, dimensions, duration.

Standard library only, like the rest of the Factory. Images go through the asset pipeline's
sniffers (wgf_assets.formats: PNG, JPEG, WebP, GIF); video containers are read here -
enough of WebM's EBML and MP4's box structure to answer the questions validation asks (how
long, how large) without an encoder on the machine:

    describe(path)  -> {"format", "width", "height", "bytes", "duration_s"} (None where the
                       file does not say)

A file nothing here recognises is `format: "unknown"`; validation then fails it, never
guesses.
"""

import os
import struct

from wgf_assets import formats

__all__ = ["describe", "webm_info", "mp4_info", "sha256_of", "IMAGE_FORMATS", "VIDEO_FORMATS"]

IMAGE_FORMATS = ("png", "jpg", "webp", "gif")
VIDEO_FORMATS = ("webm", "mp4")
_FORMAT_NAMES = {"jpeg": "jpg"}


def sha256_of(path):
    import hashlib
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


# -- WebM / Matroska (EBML) ---------------------------------------------------------------

def _vint(data, index):
    """(value, length) of the EBML variable-size integer at `index`; the id form keeps the
    marker bit (callers that want the id use _vint_id)."""
    if index >= len(data):
        raise ValueError("truncated EBML")
    first = data[index]
    if first == 0:
        raise ValueError("invalid EBML vint")
    length = 1
    mask = 0x80
    while not first & mask:
        mask >>= 1
        length += 1
    if index + length > len(data):
        raise ValueError("truncated EBML")
    value = first & (mask - 1)
    for k in range(1, length):
        value = (value << 8) | data[index + k]
    unknown = value == (1 << (7 * length)) - 1
    return (None if unknown else value), length


def _vint_id(data, index):
    first = data[index]
    length = 1
    mask = 0x80
    while not first & mask:
        mask >>= 1
        length += 1
        if length > 4:
            raise ValueError("invalid EBML id")
    return int.from_bytes(data[index:index + length], "big"), length


_EBML_HEADER, _SEGMENT, _INFO, _TRACKS = 0x1A45DFA3, 0x18538067, 0x1549A966, 0x1654AE6B
_TIMECODE_SCALE, _DURATION = 0x2AD7B1, 0x4489
_TRACK_ENTRY, _VIDEO, _PIXEL_W, _PIXEL_H, _CODEC_ID, _TRACK_TYPE = (0xAE, 0xE0, 0xB0, 0xBA,
                                                                       0x86, 0x83)
_CLUSTER = 0x1F43B675
_MASTERS = {_SEGMENT, _INFO, _TRACKS, _TRACK_ENTRY, _VIDEO}


def _float(body):
    if len(body) == 4:
        return struct.unpack(">f", body)[0]
    if len(body) == 8:
        return struct.unpack(">d", body)[0]
    return None


def webm_info(data):
    """{"width", "height", "duration_s", "codec"} from a WebM/Matroska file's header
    elements, each None when absent. Raises ValueError for bytes that are not EBML."""
    index = 0
    eid, n = _vint_id(data, 0)
    if eid != _EBML_HEADER:
        raise ValueError("not an EBML file")
    size, m = _vint(data, n)
    index = n + m + (size or 0)
    out = {"width": None, "height": None, "duration_s": None, "codec": None}
    scale = 1_000_000
    duration = None

    def walk(start, end, depth):
        nonlocal scale, duration
        pos = start
        while pos < end and pos < len(data):
            try:
                eid, n = _vint_id(data, pos)
                size, m = _vint(data, pos + n)
            except ValueError:
                return
            body_start = pos + n + m
            body_end = len(data) if size is None else min(body_start + size, len(data))
            if eid == _CLUSTER:
                return  # media data follows; nothing more to read
            if eid in _MASTERS:
                walk(body_start, body_end, depth + 1)
            else:
                body = data[body_start:body_end]
                if eid == _TIMECODE_SCALE:
                    scale = int.from_bytes(body, "big") or scale
                elif eid == _DURATION:
                    duration = _float(body)
                elif eid == _PIXEL_W:
                    out["width"] = int.from_bytes(body, "big")
                elif eid == _PIXEL_H:
                    out["height"] = int.from_bytes(body, "big")
                elif eid == _CODEC_ID and out["codec"] is None:
                    out["codec"] = body.decode("ascii", "replace")
            if size is None:
                # Unknown-sized master (a live-written Segment): its children follow directly.
                pos = body_start
                continue
            pos = body_end
    walk(index, len(data), 0)
    if duration is not None:
        out["duration_s"] = round(duration * scale / 1e9, 3)
    return out


# -- MP4 / ISO BMFF -----------------------------------------------------------------------

def mp4_info(data):
    """{"width", "height", "duration_s", "codec"} from an MP4's moov box. Raises ValueError
    for bytes without an ftyp/moov structure."""
    out = {"width": None, "height": None, "duration_s": None, "codec": None}
    if len(data) < 12 or data[4:8] not in (b"ftyp", b"moov", b"free", b"mdat", b"wide"):
        raise ValueError("not an ISO BMFF file")

    def boxes(start, end):
        pos = start
        while pos + 8 <= end:
            size = struct.unpack(">I", data[pos:pos + 4])[0]
            kind = data[pos + 4:pos + 8]
            header = 8
            if size == 1:
                size = struct.unpack(">Q", data[pos + 8:pos + 16])[0]
                header = 16
            elif size == 0:
                size = end - pos
            if size < header:
                return
            yield kind, pos + header, min(pos + size, end)
            pos += size

    for kind, start, end in boxes(0, len(data)):
        if kind != b"moov":
            continue
        for inner, s, e in boxes(start, end):
            if inner == b"mvhd":
                version = data[s]
                if version == 1:
                    scale = struct.unpack(">I", data[s + 20:s + 24])[0]
                    duration = struct.unpack(">Q", data[s + 24:s + 32])[0]
                else:
                    scale = struct.unpack(">I", data[s + 12:s + 16])[0]
                    duration = struct.unpack(">I", data[s + 16:s + 20])[0]
                if scale:
                    out["duration_s"] = round(duration / scale, 3)
            elif inner == b"trak":
                for t, ts, te in boxes(s, e):
                    if t == b"tkhd":
                        version = data[ts]
                        # version/flags, times, track id, reserved, duration, then 16 bytes of
                        # layer/group/volume and a 36-byte matrix: width at 76 (v0) / 88 (v1).
                        offset = ts + (88 if version == 1 else 76)
                        width = struct.unpack(">I", data[offset:offset + 4])[0] >> 16
                        height = struct.unpack(">I", data[offset + 4:offset + 8])[0] >> 16
                        if width and height and out["width"] is None:
                            out["width"], out["height"] = width, height
                    elif t == b"mdia" and out["codec"] is None:
                        out["codec"] = _mp4_codec(data, boxes, ts, te)
    return out


def _mp4_codec(data, boxes, start, end):
    """The first sample entry's four-character code under mdia/minf/stbl/stsd."""
    for kind, s, e in boxes(start, end):
        if kind != b"minf":
            continue
        for k2, s2, e2 in boxes(s, e):
            if k2 != b"stbl":
                continue
            for k3, s3, e3 in boxes(s2, e2):
                if k3 == b"stsd" and e3 - s3 >= 16:
                    return data[s3 + 12:s3 + 16].decode("ascii", "replace")
    return None


# -- the one entry point ------------------------------------------------------------------

def describe(path):
    """{"format", "width", "height", "bytes", "duration_s", "codec"} of the file at `path`."""
    size = os.path.getsize(path)
    with open(path, "rb") as handle:
        data = handle.read()
    out = {"format": "unknown", "width": None, "height": None, "bytes": size,
           "duration_s": None, "codec": None}
    detected = formats.sniff(data)
    if detected is not None and detected.format in ("png", "jpeg", "webp", "gif"):
        out.update(format=_FORMAT_NAMES.get(detected.format, detected.format),
                   width=detected.width, height=detected.height)
        return out
    if data[:4] == b"\x1a\x45\xdf\xa3":
        try:
            info = webm_info(data)
        except ValueError:
            return out
        out.update(format="webm", **info)
        return out
    if len(data) >= 12 and data[4:8] == b"ftyp":
        try:
            info = mp4_info(data)
        except (ValueError, struct.error):
            return out
        out.update(format="mp4", **info)
        return out
    if data[:1] == b"{":
        out["format"] = "json"
    return out

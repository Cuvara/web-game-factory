"""Lossless optimization the pipeline can do itself, and a record of what it cannot.

In place, standard library only, and only lossless: re-deflating PNG image data at maximum
compression, dropping PNG metadata chunks, minifying JSON and glTF, and stripping comments
and metadata from SVG. Each step is kept only when it makes the file smaller, and each is
deterministic, so optimizing an already-optimized file changes nothing.

Everything lossy or tool-dependent - atlasing, WebP, KTX2, Draco or Meshopt, audio
transcoding, font subsetting - is recorded as `deferred` on the manifest item, from the
policy's `optimize` list, for the game repository's build to do.
"""

import json
import re
import struct
import zlib

__all__ = ["optimize"]

# Ancillary PNG chunks that carry no pixels: text, timestamps, EXIF, colour-profile metadata
# a browser ignores for sRGB content. Critical chunks and transparency (tRNS) are kept.
_PNG_DROP = {b"tEXt", b"zTXt", b"iTXt", b"tIME", b"eXIf", b"pHYs", b"iCCP", b"sPLT", b"hIST"}


def _png_chunks(data):
    index = 8
    while index + 12 <= len(data):
        length = struct.unpack(">I", data[index:index + 4])[0]
        kind = data[index + 4:index + 8]
        body = data[index + 8:index + 8 + length]
        yield kind, body
        index += 12 + length
        if kind == b"IEND":
            return


def _chunk(kind, body):
    return (struct.pack(">I", len(body)) + kind + body
            + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF))


def _png(data):
    applied = []
    chunks = list(_png_chunks(data))
    kept = [(k, b) for k, b in chunks if k not in _PNG_DROP]
    if len(kept) != len(chunks):
        applied.append("png-strip-metadata")
    idat = b"".join(b for k, b in kept if k == b"IDAT")
    try:
        recompressed = zlib.compress(zlib.decompress(idat), 9)
    except zlib.error:
        return data, []
    if len(recompressed) < len(idat):
        applied.append("png-recompress")
    else:
        recompressed = idat
    out = bytearray(data[:8])
    wrote_idat = False
    for kind, body in kept:
        if kind == b"IDAT":
            if not wrote_idat:
                out += _chunk(b"IDAT", recompressed)
                wrote_idat = True
            continue
        out += _chunk(kind, body)
    out = bytes(out)
    if len(out) >= len(data):
        return data, []
    return out, applied


def _json(data):
    try:
        document = json.loads(data.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError):
        return data, []
    out = json.dumps(document, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return (out, ["json-minify"]) if len(out) < len(data) else (data, [])


_SVG_NOISE = [
    re.compile(rb"<!--.*?-->", re.S),
    re.compile(rb"<metadata\b.*?</metadata>", re.S),
    re.compile(rb">\s+<"),
]


def _svg(data):
    out = _SVG_NOISE[0].sub(b"", data)
    out = _SVG_NOISE[1].sub(b"", out)
    out = _SVG_NOISE[2].sub(b"><", out).strip()
    return (out, ["svg-strip"]) if len(out) < len(data) else (data, [])


_OPTIMIZERS = {"png": _png, "json": _json, "gltf": _json, "svg": _svg}


def optimize(data, fmt):
    """(bytes, [applied step names]). Unchanged bytes and [] when nothing helps."""
    optimizer = _OPTIMIZERS.get(fmt)
    return optimizer(data) if optimizer else (data, [])

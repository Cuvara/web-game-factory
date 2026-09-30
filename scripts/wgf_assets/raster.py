"""PNG in and out, standard library only: what atlas packing and pixel checks need.

`decode_png(data)` returns an `Image` of 8-bit RGBA pixels from any non-interlaced PNG -
greyscale, RGB, palette, greyscale+alpha or RGBA, at any bit depth - so an atlas can take a
library sprite as readily as a generated one. `encode_png(image)` writes RGBA8 with filter 0
and zlib level 9: the same pixels always give the same bytes on one zlib build, which is
what lets a re-executed step find the atlas it wrote before.

`png_header(data)` reads only the header and the chunk types, for the cheap questions a
validator asks of every file (does it carry an alpha channel? is it interlaced?) without
inflating the pixels.

Interlaced (Adam7) PNGs are refused rather than decoded: they are rare in game art, larger
than their non-interlaced twin, and supporting them would double this module for no build a
player sees. The message says how to fix the file.
"""

import struct
import zlib
from collections import namedtuple

__all__ = ["Image", "RasterError", "PngHeader", "png_header", "decode_png", "encode_png",
           "alpha_bounds"]

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
PngHeader = namedtuple("PngHeader", "width height bit_depth colour_type interlaced has_alpha")

# colour type -> channels
_CHANNELS = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}


class RasterError(ValueError):
    """The bytes are not a PNG this module can read, with what to do about it."""


class Image:
    """8-bit RGBA pixels, row-major, no padding."""

    __slots__ = ("width", "height", "pixels")

    def __init__(self, width, height, pixels=None):
        self.width, self.height = int(width), int(height)
        self.pixels = bytearray(pixels) if pixels is not None else bytearray(
            self.width * self.height * 4)
        if len(self.pixels) != self.width * self.height * 4:
            raise RasterError(f"{len(self.pixels)} bytes is not {self.width}x{self.height} RGBA")

    def row(self, y):
        stride = self.width * 4
        return self.pixels[y * stride:(y + 1) * stride]

    def crop(self, x, y, width, height):
        out = Image(width, height)
        stride, out_stride = self.width * 4, width * 4
        for row in range(height):
            start = (y + row) * stride + x * 4
            out.pixels[row * out_stride:(row + 1) * out_stride] = \
                self.pixels[start:start + out_stride]
        return out


def _chunks(data):
    if data[:8] != PNG_SIGNATURE:
        raise RasterError("not a PNG: bad signature")
    index = 8
    while index + 12 <= len(data):
        length = struct.unpack(">I", data[index:index + 4])[0]
        kind = data[index + 4:index + 8]
        body = data[index + 8:index + 8 + length]
        if len(body) != length:
            raise RasterError("truncated PNG: a chunk runs past the end of the file")
        yield kind, body
        index += 12 + length
        if kind == b"IEND":
            return
    raise RasterError("truncated PNG: no IEND chunk")


def png_header(data):
    """The header, and whether the image can carry transparency. RasterError if not a PNG."""
    header = None
    trns = False
    for kind, body in _chunks(data):
        if kind == b"IHDR":
            if len(body) != 13:
                raise RasterError("malformed IHDR chunk")
            width, height, depth, colour, _c, _f, interlace = struct.unpack(">IIBBBBB", body)
            header = (width, height, depth, colour, interlace)
        elif kind == b"tRNS":
            trns = True
        elif kind == b"IDAT":
            break
    if header is None:
        raise RasterError("PNG has no IHDR chunk")
    width, height, depth, colour, interlace = header
    if colour not in _CHANNELS:
        raise RasterError(f"PNG colour type {colour} is not defined")
    return PngHeader(width, height, depth, colour, bool(interlace),
                     colour in (4, 6) or trns)


def _paeth(a, b, c):
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    return b if pb <= pc else c


def _unfilter(raw, height, stride, bpp):
    """The filtered scanlines of `raw` as a list of bytearrays, one per row."""
    rows = []
    previous = bytearray(stride)
    index = 0
    for _ in range(height):
        if index + 1 + stride > len(raw):
            raise RasterError("truncated PNG: image data is shorter than the header says")
        method = raw[index]
        line = bytearray(raw[index + 1:index + 1 + stride])
        index += 1 + stride
        if method == 0:
            pass
        elif method == 1:
            for i in range(bpp, stride):
                line[i] = (line[i] + line[i - bpp]) & 0xFF
        elif method == 2:
            line = bytearray((a + b) & 0xFF for a, b in zip(line, previous))
        elif method == 3:
            for i in range(stride):
                left = line[i - bpp] if i >= bpp else 0
                line[i] = (line[i] + ((left + previous[i]) >> 1)) & 0xFF
        elif method == 4:
            for i in range(stride):
                left = line[i - bpp] if i >= bpp else 0
                upper_left = previous[i - bpp] if i >= bpp else 0
                line[i] = (line[i] + _paeth(left, previous[i], upper_left)) & 0xFF
        else:
            raise RasterError(f"PNG scanline filter {method} is not defined")
        rows.append(line)
        previous = line
    return rows


def _samples(line, depth, count):
    """`count` unsigned samples of `depth` bits from a scanline, as 0..255 bytes-worth ints
    (16-bit samples keep their high byte)."""
    if depth == 8:
        return line[:count]
    if depth == 16:
        return line[0:count * 2:2]
    out = bytearray(count)
    mask = (1 << depth) - 1
    per_byte = 8 // depth
    for i in range(count):
        byte = line[i // per_byte]
        shift = 8 - depth * (i % per_byte + 1)
        out[i] = (byte >> shift) & mask
    return out


def decode_png(data):
    """An RGBA8 `Image` of a non-interlaced PNG. RasterError, with a fix, otherwise."""
    width = height = depth = colour = None
    palette = b""
    trns = b""
    idat = []
    for kind, body in _chunks(data):
        if kind == b"IHDR":
            width, height, depth, colour, _c, _f, interlace = struct.unpack(">IIBBBBB", body)
            if interlace:
                raise RasterError("interlaced (Adam7) PNG; re-save it without interlacing")
        elif kind == b"PLTE":
            palette = body
        elif kind == b"tRNS":
            trns = body
        elif kind == b"IDAT":
            idat.append(body)
    if width is None:
        raise RasterError("PNG has no IHDR chunk")
    if colour not in _CHANNELS or depth not in (1, 2, 4, 8, 16):
        raise RasterError(f"PNG colour type {colour} at bit depth {depth} is not supported")
    if not width or not height:
        raise RasterError("PNG has a zero dimension")
    try:
        raw = zlib.decompress(b"".join(idat))
    except zlib.error as exc:
        raise RasterError(f"PNG image data does not inflate: {exc}")

    channels = _CHANNELS[colour]
    bits = channels * depth
    stride = (width * bits + 7) // 8
    bpp = max(1, bits // 8)
    rows = _unfilter(raw, height, stride, bpp)

    image = Image(width, height)
    out = image.pixels
    scale = {1: 255, 2: 85, 4: 17, 8: 1, 16: 1}[depth]
    key = None
    if trns and colour == 0 and len(trns) >= 2:
        key = struct.unpack(">H", trns[:2])[0]
    elif trns and colour == 2 and len(trns) >= 6:
        key = struct.unpack(">HHH", trns[:6])

    for y, line in enumerate(rows):
        base = y * width * 4
        if colour == 6 and depth == 8:
            out[base:base + width * 4] = line[:width * 4]
            continue
        samples = _samples(line, depth, width * channels)
        if colour == 3:
            for x in range(width):
                index = samples[x]
                if index * 3 + 2 >= len(palette):
                    raise RasterError(f"PNG palette index {index} is out of range")
                o = base + x * 4
                out[o:o + 3] = palette[index * 3:index * 3 + 3]
                out[o + 3] = trns[index] if index < len(trns) else 255
            continue
        # The colour key is compared against the stored sample, before any scaling.
        keyed = None
        if key is not None:
            keyed = _samples(line, depth, width * channels) if depth != 16 else [
                struct.unpack(">H", line[i:i + 2])[0] for i in range(0, width * channels * 2, 2)]
        for x in range(width):
            o = base + x * 4
            if colour == 0:
                g = samples[x] * scale
                out[o:o + 4] = bytes((g, g, g, 255))
                if keyed is not None and keyed[x] == key:
                    out[o + 3] = 0
            elif colour == 4:
                g = samples[x * 2] * scale
                out[o:o + 4] = bytes((g, g, g, samples[x * 2 + 1] * scale))
            elif colour == 2:
                s = x * 3
                out[o:o + 4] = bytes((samples[s], samples[s + 1], samples[s + 2], 255))
                if keyed is not None and tuple(keyed[s:s + 3]) == key:
                    out[o + 3] = 0
            else:  # colour 6 at 16 bits
                s = x * 4
                out[o:o + 4] = samples[s:s + 4]
    return image


def _chunk(kind, body):
    return (struct.pack(">I", len(body)) + kind + body
            + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF))


def encode_png(image):
    """RGBA8 PNG bytes of `image`: filter 0 on every row, zlib level 9, no ancillary chunks."""
    stride = image.width * 4
    raw = bytearray()
    for y in range(image.height):
        raw.append(0)
        raw += image.pixels[y * stride:(y + 1) * stride]
    header = struct.pack(">IIBBBBB", image.width, image.height, 8, 6, 0, 0, 0)
    return (PNG_SIGNATURE + _chunk(b"IHDR", header)
            + _chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + _chunk(b"IEND", b""))


def alpha_bounds(image):
    """(x, y, width, height) of the pixels with non-zero alpha, or None if all transparent."""
    top = bottom = None
    left, right = image.width, -1
    for y in range(image.height):
        alpha = bytes(image.row(y)[3::4])
        stripped = alpha.lstrip(b"\x00")
        if not stripped:
            continue
        if top is None:
            top = y
        bottom = y
        left = min(left, len(alpha) - len(stripped))
        right = max(right, len(alpha.rstrip(b"\x00")) - 1)
    if top is None:
        return None
    return left, top, right - left + 1, bottom - top + 1

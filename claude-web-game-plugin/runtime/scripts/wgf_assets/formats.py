"""What a file actually is, read from its bytes rather than trusted from its name.

A `.png` that is really a JPEG loads in a browser and fails in a texture compressor; a
`.glb` truncated by a bad download loads nowhere. Both are cheap to catch here and expensive
to catch in a portal review, so every delivered file is sniffed and the result compared with
its extension and with the formats its kind allows.

`sniff(data)` returns a `Detected(format, width, height)` or None. Dimensions are read where
the header gives them cheaply (PNG, JPEG, GIF, WebP, KTX2); None elsewhere.
"""

import json
import struct
from collections import namedtuple

__all__ = ["Detected", "sniff", "format_for_extension", "EXTENSIONS", "is_power_of_two"]

Detected = namedtuple("Detected", "format width height")

# Extension -> canonical format name. The name is what asset-policy.yaml lists.
EXTENSIONS = {
    "png": "png", "jpg": "jpeg", "jpeg": "jpeg", "webp": "webp", "gif": "gif", "svg": "svg",
    "ktx2": "ktx2", "glb": "glb", "gltf": "gltf", "json": "json",
    "ogg": "ogg", "oga": "ogg", "mp3": "mp3", "m4a": "m4a", "aac": "m4a", "wav": "wav",
    "woff2": "woff2", "woff": "woff", "ttf": "ttf", "otf": "otf",
}

# Extension a generated file of a format gets.
FORMAT_EXTENSION = {"jpeg": "jpg"}


def format_for_extension(path):
    ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""
    return EXTENSIONS.get(ext)


def is_power_of_two(n):
    return bool(n) and n & (n - 1) == 0


def _png(data):
    if data[:8] != b"\x89PNG\r\n\x1a\n" or len(data) < 33 or data[12:16] != b"IHDR":
        return None
    width, height = struct.unpack(">II", data[16:24])
    if not data.rstrip(b"\x00").endswith(b"IEND\xaeB`\x82"):
        return None  # truncated: no IEND chunk at the end
    return Detected("png", width, height)


def _jpeg(data):
    if data[:3] != b"\xff\xd8\xff":
        return None
    index = 2
    while index + 9 < len(data):
        if data[index] != 0xFF:
            index += 1
            continue
        marker = data[index + 1]
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            index += 2
            continue
        length = struct.unpack(">H", data[index + 2:index + 4])[0]
        # SOF0..SOF15 carry the frame size, except DHT (C4), JPG (C8) and DAC (CC).
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            height, width = struct.unpack(">HH", data[index + 5:index + 9])
            return Detected("jpeg", width, height)
        index += 2 + length
    return Detected("jpeg", None, None)


def _webp(data):
    if data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        return None
    chunk = data[12:16]
    width = height = None
    if chunk == b"VP8X" and len(data) >= 30:
        width = 1 + int.from_bytes(data[24:27], "little")
        height = 1 + int.from_bytes(data[27:30], "little")
    elif chunk == b"VP8 " and len(data) >= 30:
        width = struct.unpack("<H", data[26:28])[0] & 0x3FFF
        height = struct.unpack("<H", data[28:30])[0] & 0x3FFF
    elif chunk == b"VP8L" and len(data) >= 25:
        bits = int.from_bytes(data[21:25], "little")
        width, height = (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
    return Detected("webp", width, height)


def _ktx2(data):
    if data[:12] != b"\xabKTX 20\xbb\r\n\x1a\n" or len(data) < 28:
        return None
    width, height = struct.unpack("<II", data[20:28])
    return Detected("ktx2", width, height)


def _gltf_document(document):
    return isinstance(document, dict) and (document.get("asset") or {}).get("version") == "2.0"


def _glb(data):
    if data[:4] != b"glTF" or len(data) < 20:
        return None
    version, length = struct.unpack("<II", data[4:12])
    if version != 2 or length != len(data):
        return None
    chunk_length, chunk_type = struct.unpack("<I4s", data[12:20])
    if chunk_type != b"JSON" or 20 + chunk_length > len(data):
        return None
    try:
        document = json.loads(data[20:20 + chunk_length].decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    return Detected("glb", None, None) if _gltf_document(document) else None


def _text(data):
    head = data.lstrip(b"\xef\xbb\xbf \t\r\n")
    if head[:1] in (b"{", b"["):
        try:
            document = json.loads(data.decode("utf-8-sig"))
        except (UnicodeDecodeError, ValueError):
            return None
        return Detected("gltf" if _gltf_document(document) else "json", None, None)
    if head[:5] == b"<?xml" or head[:4] == b"<svg" or head[:4] == b"<!--":
        if b"<svg" in data[:4096] and data.rstrip().endswith(b"</svg>"):
            return Detected("svg", None, None)
    return None


def _audio_and_fonts(data):
    if data[:4] == b"OggS":
        return Detected("ogg", None, None)
    if data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        return Detected("wav", None, None)
    if data[4:8] == b"ftyp":
        return Detected("m4a", None, None)
    if data[:3] == b"ID3" or (len(data) > 1 and data[0] == 0xFF and data[1] & 0xE0 == 0xE0):
        return Detected("mp3", None, None)
    if data[:4] == b"wOF2":
        return Detected("woff2", None, None)
    if data[:4] == b"wOFF":
        return Detected("woff", None, None)
    if data[:4] == b"OTTO":
        return Detected("otf", None, None)
    if data[:4] in (b"\x00\x01\x00\x00", b"true"):
        return Detected("ttf", None, None)
    return None


def _gif(data):
    if data[:6] not in (b"GIF87a", b"GIF89a") or len(data) < 10:
        return None
    width, height = struct.unpack("<HH", data[6:10])
    return Detected("gif", width, height)


_SNIFFERS = (_png, _jpeg, _webp, _gif, _ktx2, _glb, _audio_and_fonts, _text)


def sniff(data):
    """The format `data` really is, or None when it is nothing this pipeline recognises."""
    if not data:
        return None
    for sniffer in _SNIFFERS:
        found = sniffer(data)
        if found:
            return found
    return None

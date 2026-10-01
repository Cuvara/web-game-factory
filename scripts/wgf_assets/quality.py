"""Is a delivered 2D file production art, or a stand-in? The manifest item's `quality`.

core/reference/asset-quality.yaml holds the bars. Two readers, both standard library only and
both offline:

    svg_quality(data, ...)     parsed with xml.etree after a size bound, with any DOCTYPE or
                               ENTITY refused before parsing (no entity expansion, no external
                               entity is ever resolved). Checks:
        svg.well-formed        parses; the root is <svg> with a usable viewBox
        svg.safe               no script, event handler, foreignObject, embedded raster
                               (<image>), or reference to another file
        svg.not-primitive      more drawing elements than the role's bar, and not one plain
                               rect/circle/ellipse (allowed by visual_identity.primitive_style)
        svg.palette            the colours used are near the design's palette, or the root
                               says why not (data-wgf-off-palette="<reason>")
        svg.dimensions         the declared size within the edge limit and the spec's aspect
    font_quality(data, locales=...)  a TTF/OTF/WOFF/WOFF2: tables, glyphs, and font.coverage -
                               the cmap maps each locale's characters (fonts.locales)
    variants_distinct(drawings)  variants.distinct: a counted requirement's drawings differ by
                               silhouette (a grid mask per drawing, 1 - IoU per pair)
    raster_quality(data, ...)  a PNG decoded through wgf_assets.raster:
        raster.decodes         a PNG this pipeline can read
        raster.not-flat        more than one flat colour
        raster.alpha           a cut-out kind carries alpha and some transparent pixels
    audio_quality(data, ...)   a WAV decoded, an Ogg or MP3 read by its headers (audiofile):
        audio.decodes          a file the reader can open: WAV samples, Ogg pages and CRCs
                               with a Vorbis/Opus header, MP3 frames
        audio.duration         music (and any loop) at least the design's or the bar's
                               length; a one-shot no longer than the bar
        audio.not-silent       the loudest window (one bar long) above the RMS floor (WAV;
                               a compressed file is measured at runtime by audio.plays)
        audio.loop-seam        a loop's last frames meet its first: the jump is a few
                               typical sample steps and the level does not leap (WAV)
        audio.size             within the asset policy's max_bytes for the kind
        audio.licence          the licence is recorded and permitted

Each returns the asset-manifest `quality` object: {verdict, checks, primitive_only, parts,
colors, author}. `problems(quality)` is the list an author is shown when it is asked again.
"""

import os
import re
import xml.etree.ElementTree as ET

from wgflib import paths
from wgflib.yamllite import load_file

from . import audiofile, raster

__all__ = ["load_bars", "svg_quality", "raster_quality", "font_quality", "font_format",
           "audio_quality", "skipped", "problems", "parse_palette", "BARS_PATH", "QualityBars",
           "font_cmap", "expand_chars", "CoverageUnchecked", "silhouette", "variants_distinct"]

BARS_PATH = os.path.join(paths.REFERENCE, "asset-quality.yaml")

DRAWING = {"rect", "circle", "ellipse", "line", "polyline", "polygon", "path", "text", "use"}
PRIMITIVES = {"rect", "circle", "ellipse"}
# Containers whose children are not drawn where they stand.
NOT_DRAWN = {"defs", "clipPath", "mask", "pattern", "symbol", "marker", "metadata", "title",
             "desc", "linearGradient", "radialGradient", "filter", "style"}
COLOUR_ATTRS = ("fill", "stroke", "stop-color", "flood-color", "lighting-color", "color")
_HREF = re.compile(r"^\s*(#|$)")
_HEX = re.compile(r"^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")
_RGB = re.compile(r"^rgba?\(\s*([0-9.]+%?)\s*[, ]\s*([0-9.]+%?)\s*[, ]\s*([0-9.]+%?)")
_NAMED = {"black": (0, 0, 0), "white": (255, 255, 255), "red": (255, 0, 0),
          "green": (0, 128, 0), "blue": (0, 0, 255), "yellow": (255, 255, 0),
          "gray": (128, 128, 128), "grey": (128, 128, 128), "orange": (255, 165, 0),
          "purple": (128, 0, 128), "cyan": (0, 255, 255), "magenta": (255, 0, 255),
          "pink": (255, 192, 203), "brown": (165, 42, 42), "silver": (192, 192, 192),
          "lime": (0, 255, 0), "navy": (0, 0, 128), "teal": (0, 128, 128),
          "maroon": (128, 0, 0), "olive": (128, 128, 0), "gold": (255, 215, 0)}
_NO_COLOUR = {"none", "transparent", "currentcolor", "inherit", "context-fill",
              "context-stroke", ""}
_UNSAFE_TAGS = {"script": "a <script> element", "foreignObject": "a <foreignObject> element",
                "image": "an embedded raster (<image>)", "iframe": "an <iframe>",
                "video": "a <video>", "audio": "an <audio>"}


class QualityBars:
    def __init__(self, data):
        svg = data.get("svg") or {}
        palette = svg.get("palette") or {}
        rast = data.get("raster") or {}
        self.version = str(data.get("version") or "0.0.0")
        self.svg_max_bytes = int(svg.get("max_bytes") or 262144)
        self.max_edge = int(svg.get("max_edge") or 4096)
        self.min_shapes = {str(k): int(v) for k, v in (svg.get("min_shapes") or {}).items()}
        self.tolerance = float(palette.get("tolerance") or 60)
        self.neutrals = bool(palette.get("neutrals", True))
        self.max_off_share = float(palette.get("max_off_palette_share") or 0)
        self.min_reason = int(palette.get("min_reason_length") or 12)
        self.aspect_tolerance = float(svg.get("aspect_tolerance") or 0.1)
        self.min_distinct = int(rast.get("min_distinct_colors") or 2)
        self.min_transparent = float(rast.get("min_transparent_share") or 0)
        self.max_pixels = int(rast.get("max_pixels") or 4194304)
        fonts = data.get("fonts") or {}
        self.locales = {str(k): v for k, v in (fonts.get("locales") or {}).items()
                        if isinstance(v, dict)}
        self.families = {str(k): list(v or []) for k, v in (fonts.get("families") or {}).items()}
        variants = data.get("variants") or {}
        self.variant_grid = int(variants.get("grid") or 32)
        self.min_silhouette_distance = float(variants.get("min_silhouette_distance") or 0)
        self.png_background_delta = int(variants.get("png_background_delta") or 24)
        self.audio = AudioBars(data.get("audio") or {})

    def locale(self, locale):
        """The `fonts.locales` entry of a locale, matched by its language subtag; None when
        the table does not know it."""
        text = str(locale or "").strip()
        return self.locales.get(text) or self.locales.get(text.replace("_", "-").split("-")[0].lower())

    def locale_chars(self, locale):
        """The characters a font must map to set `locale`, or None when it is not listed."""
        entry = self.locale(locale)
        return None if entry is None else expand_chars(entry.get("chars"))

    def shapes_for(self, role):
        return self.min_shapes.get(role or "", self.min_shapes.get("default", 3))

    def summary(self, role):
        """What an author is told it will be held to."""
        return {"min_shapes": self.shapes_for(role),
                "palette_tolerance_rgb": self.tolerance,
                "neutral_greys_allowed": self.neutrals,
                "max_off_palette_share": self.max_off_share,
                "max_bytes": self.svg_max_bytes, "max_edge": self.max_edge,
                "off_palette_marker": "data-wgf-off-palette=\"<reason>\" on the root <svg>"}


class AudioBars:
    def __init__(self, data):
        seam = data.get("loop_seam") or {}
        self.window_s = float(data.get("window_s") or 2.0)
        self.min_rms_dbfs = float(data.get("min_rms_dbfs") if data.get("min_rms_dbfs")
                                  is not None else -45)
        self.music_min_s = float((data.get("music") or {}).get("min_duration_s") or 30)
        self.loop_min_s = float((data.get("loop") or {}).get("min_duration_s") or 1)
        self.sfx_max_s = float((data.get("sfx") or {}).get("max_duration_s") or 6)
        self.seam_ratio = float(seam.get("max_step_ratio") or 8)
        self.seam_edge_db = float(seam.get("max_edge_db") or 6)
        self.seam_edge_ms = float(seam.get("edge_ms") or 50)


def load_bars(path=None):
    return QualityBars(load_file(path or BARS_PATH) or {})


# -- colour --------------------------------------------------------------------------------

def parse_colour(value):
    """(r, g, b) of a CSS colour value, None for none/url()/unknown."""
    text = (value or "").strip().lower()
    if text in _NO_COLOUR or text.startswith("url("):
        return None
    match = _HEX.match(text)
    if match:
        digits = match.group(1)
        if len(digits) == 3:
            digits = "".join(c * 2 for c in digits)
        return tuple(int(digits[i:i + 2], 16) for i in (0, 2, 4))
    match = _RGB.match(text)
    if match:
        out = []
        for part in match.groups():
            number = float(part.rstrip("%"))
            out.append(round(number * 2.55) if part.endswith("%") else round(number))
        return tuple(max(0, min(255, c)) for c in out)
    return _NAMED.get(text)


def parse_palette(palette):
    """[(token, (r, g, b))] of build_spec.visual_identity.palette, skipping bad entries."""
    out = []
    for entry in palette or []:
        if isinstance(entry, dict):
            rgb = parse_colour(entry.get("hex"))
            if rgb is not None:
                out.append((entry.get("token") or entry.get("hex"), rgb))
    return out


def _distance(a, b):
    return sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5


def _neutral(rgb):
    return max(rgb) - min(rgb) <= 12


def _hex(rgb):
    return "#%02x%02x%02x" % rgb


# -- results -------------------------------------------------------------------------------

def _check(checks, check_id, ok, summary, skipped_=False):
    checks.append({"id": check_id, "status": "skipped" if skipped_ else (
        "pass" if ok else "fail"), "summary": summary})


def _result(checks, author, *, primitive_only=None, parts=None, colors=None):
    verdict = "fail" if any(c["status"] == "fail" for c in checks) else "pass"
    return {"verdict": verdict, "checks": checks, "primitive_only": primitive_only,
            "parts": parts, "colors": colors, "author": author}


def skipped(author, summary):
    """The quality of a file nobody judged: a placeholder, or a kind with no 2D check."""
    return {"verdict": "skipped", "checks": [{"id": "quality", "status": "skipped",
                                              "summary": summary}],
            "primitive_only": None, "parts": None, "colors": None, "author": author}


def problems(quality):
    """The failed checks, as sentences an author can act on."""
    return [f"{c['id']}: {c['summary']}" for c in (quality or {}).get("checks") or []
            if c["status"] == "fail"]


# -- SVG -----------------------------------------------------------------------------------

def _local(tag):
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _style_colours(style):
    found = []
    for declaration in (style or "").split(";"):
        if ":" in declaration:
            key, value = declaration.split(":", 1)
            if key.strip().lower() in COLOUR_ATTRS:
                found.append(value.strip())
    return found


def _walk(element, drawn=True):
    """(element, drawn?) for the element and its descendants, depth first."""
    name = _local(element.tag)
    here = drawn and name not in NOT_DRAWN
    yield element, here
    for child in element:
        yield from _walk(child, here)


def _viewbox(root):
    raw = root.get("viewBox") or root.get("viewbox")
    if not raw:
        return None
    try:
        parts = [float(p) for p in re.split(r"[\s,]+", raw.strip()) if p]
    except ValueError:
        return None
    if len(parts) != 4 or parts[2] <= 0 or parts[3] <= 0:
        return None
    return parts


def _length(value):
    match = re.match(r"^\s*([0-9]+(?:\.[0-9]+)?)\s*(px)?\s*$", value or "")
    return float(match.group(1)) if match else None


def svg_quality(data, *, role=None, palette=(), bars=None, spec_size=None,
                primitive_style=False, author=None):
    """The `quality` object of an SVG file. `palette` is parse_palette()'s list; `spec_size`
    the requirement's (width, height) when the design states one."""
    bars = bars or load_bars()
    checks = []
    if len(data) > bars.svg_max_bytes:
        _check(checks, "svg.well-formed", False,
               f"{len(data)} bytes; the bar is {bars.svg_max_bytes} - not parsed")
        return _result(checks, author)
    if re.search(rb"<!\s*(DOCTYPE|ENTITY)", data, re.I):
        _check(checks, "svg.well-formed", False,
               "declares a DOCTYPE or ENTITY; refused before parsing")
        return _result(checks, author)
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        _check(checks, "svg.well-formed", False, f"not well-formed XML: {exc}")
        return _result(checks, author)
    if _local(root.tag) != "svg":
        _check(checks, "svg.well-formed", False, f"the root element is <{_local(root.tag)}>, "
                                                 f"not <svg>")
        return _result(checks, author)
    viewbox = _viewbox(root)
    _check(checks, "svg.well-formed", viewbox is not None,
           "well-formed <svg> with a viewBox" if viewbox else
           "no usable viewBox (four numbers, positive width and height): it cannot scale")

    unsafe, shapes, colours = [], [], set()
    for element, drawn in _walk(root):
        name = _local(element.tag)
        if name in _UNSAFE_TAGS:
            unsafe.append(_UNSAFE_TAGS[name])
        for key, value in element.attrib.items():
            attr = _local(key).lower()
            if attr.startswith("on"):
                unsafe.append(f"an event handler ({attr})")
            if attr == "href" and not _HREF.match(value or ""):
                unsafe.append(f"a reference to {value[:60]!r}")
            if "javascript:" in (value or "").lower():
                unsafe.append("a javascript: URL")
            if re.search(r"url\(\s*['\"]?\s*(?!#)", value or "") and attr != "href":
                unsafe.append(f"a url() to another resource in {attr}")
            if attr in COLOUR_ATTRS:
                colours.add(value)
            elif attr == "style":
                colours.update(_style_colours(value))
        if name == "style" and element.text:
            if re.search(r"@import|url\(\s*['\"]?\s*(?!#)", element.text):
                unsafe.append("a stylesheet that fetches another resource")
            for match in re.finditer(r"(?:fill|stroke|stop-color|color)\s*:\s*([^;}]+)",
                                     element.text):
                colours.add(match.group(1).strip())
        if drawn and name in DRAWING:
            shapes.append(name)
    _check(checks, "svg.safe", not unsafe,
           "no script, handler, embedded raster or external reference" if not unsafe else
           "contains " + "; ".join(sorted(set(unsafe))[:5]))

    parts = len(shapes)
    primitive_only = parts == 0 or (parts == 1 and shapes[0] in PRIMITIVES)
    needed = bars.shapes_for(role)
    if primitive_style:
        _check(checks, "svg.not-primitive", parts > 0,
               f"{parts} drawing element(s); primitives allowed by "
               f"visual_identity.primitive_style" if parts else "draws nothing")
    elif primitive_only and needed > 0:
        _check(checks, "svg.not-primitive", False,
               "draws nothing" if parts == 0 else
               f"one plain <{shapes[0]}> - a stand-in, not a drawing of the {role or 'asset'}")
    else:
        _check(checks, "svg.not-primitive", parts >= needed,
               f"{parts} drawing element(s); the bar for {role or 'this role'} is {needed}")

    rgb = {}
    for value in colours:
        parsed = parse_colour(value)
        if parsed is not None:
            rgb[_hex(parsed)] = parsed
    marker = (root.get("data-wgf-off-palette") or "").strip()
    if not palette:
        _check(checks, "svg.palette", True, "the design states no palette", skipped_=True)
    else:
        off = sorted(h for h, c in rgb.items()
                     if not (bars.neutrals and _neutral(c))
                     and min(_distance(c, p) for _t, p in palette) > bars.tolerance)
        share = len(off) / len(rgb) if rgb else 0.0
        if share <= bars.max_off_share:
            _check(checks, "svg.palette", True,
                   f"{len(rgb)} colour(s), {len(off)} off the palette")
        elif len(marker) >= bars.min_reason:
            _check(checks, "svg.palette", True,
                   f"{len(off)} of {len(rgb)} colour(s) off the palette, marked: {marker[:120]}")
        else:
            tokens = ", ".join(f"{t} {_hex(c)}" for t, c in palette)
            _check(checks, "svg.palette", False,
                   f"{len(off)} of {len(rgb)} colour(s) are off the palette "
                   f"({', '.join(off[:6])}); use the palette ({tokens}) or state why on the "
                   f"root element as data-wgf-off-palette")

    width, height = _length(root.get("width")), _length(root.get("height"))
    if (width is None or height is None) and viewbox:
        width, height = viewbox[2], viewbox[3]
    if width is None or height is None:
        _check(checks, "svg.dimensions", False, "no size: neither width/height nor a viewBox")
    elif max(width, height) > bars.max_edge:
        _check(checks, "svg.dimensions", False,
               f"{width:g}x{height:g} exceeds the {bars.max_edge} px edge")
    elif spec_size and all(spec_size):
        want = spec_size[0] / spec_size[1]
        got = width / height
        ok = abs(got - want) / want <= bars.aspect_tolerance
        _check(checks, "svg.dimensions", ok,
               f"{width:g}x{height:g}, aspect {got:.2f}; the spec's {spec_size[0]}x"
               f"{spec_size[1]} is {want:.2f}")
    else:
        _check(checks, "svg.dimensions", True, f"{width:g}x{height:g}")
    return _result(checks, author, primitive_only=primitive_only, parts=parts,
                   colors=len(rgb))


# -- raster --------------------------------------------------------------------------------

def raster_quality(data, *, needs_alpha=False, bars=None, author=None):
    """The `quality` object of a PNG file."""
    bars = bars or load_bars()
    checks = []
    try:
        header = raster.png_header(data)
    except raster.RasterError as exc:
        _check(checks, "raster.decodes", False, f"not a PNG this pipeline reads: {exc}")
        return _result(checks, author)
    if header.width * header.height > bars.max_pixels:
        _check(checks, "raster.decodes", True,
               f"{header.width}x{header.height}; too large to sample, judged by its header")
        _check(checks, "raster.alpha", header.has_alpha or not needs_alpha,
               "has an alpha channel" if header.has_alpha else "no alpha channel")
        return _result(checks, author)
    try:
        image = raster.decode_png(data)
    except raster.RasterError as exc:
        _check(checks, "raster.decodes", False, f"cannot be decoded: {exc}")
        return _result(checks, author)
    _check(checks, "raster.decodes", True, f"{image.width}x{image.height} PNG")
    pixels = image.pixels
    total = image.width * image.height
    distinct, transparent = set(), 0
    for index in range(0, len(pixels), 4):
        alpha = pixels[index + 3]
        if alpha < 16:
            transparent += 1
            continue
        if len(distinct) < 4096:
            distinct.add(bytes(pixels[index:index + 3]))
    _check(checks, "raster.not-flat", len(distinct) >= bars.min_distinct,
           f"{len(distinct)}{'+' if len(distinct) >= 4096 else ''} distinct opaque colour(s); "
           f"the bar is {bars.min_distinct}")
    if needs_alpha:
        share = transparent / total if total else 0.0
        ok = header.has_alpha and share >= bars.min_transparent
        _check(checks, "raster.alpha", ok,
               f"alpha {'present' if header.has_alpha else 'absent'}, {share:.1%} transparent"
               + (f"; a cut-out needs at least {bars.min_transparent:.0%} transparent"
                  if bars.min_transparent else "; a cut-out needs an alpha channel"))
    flat_rect = len(distinct) <= 1 and transparent == 0
    return _result(checks, author, primitive_only=flat_rect, parts=None,
                   colors=min(len(distinct), 4096))


# -- fonts ------------------------------------------------------------------------------------

_SFNT = {b"\x00\x01\x00\x00": "ttf", b"true": "ttf", b"OTTO": "otf"}
# WOFF2 known-table indices this reader needs (the WOFF2 specification's table of 63 tags).
_WOFF2_CMAP, _WOFF2_GLYF, _WOFF2_LOCA = 0, 10, 11
_BROTLI_LIBRARIES = ("libbrotlidec.so.1", "libbrotlidec.so", "libbrotlidec.1.dylib",
                     "libbrotlidec.dylib", "brotlidec.dll", "libbrotlidec.dll")


class CoverageUnchecked(Exception):
    """The font's character map cannot be read here; the reason is the message."""


def font_format(data):
    """ttf | otf | woff | woff2 from the file's signature, else None."""
    head = bytes(data[:4])
    if head in _SFNT:
        return _SFNT[head]
    return {b"wOFF": "woff", b"wOF2": "woff2"}.get(head)


def expand_chars(items):
    """The characters of a `fonts.locales[].chars` list: "X..Y" is a range, else literal."""
    out = []
    for item in items or []:
        item = str(item)
        if len(item) == 4 and item[1:3] == "..":
            out.extend(chr(c) for c in range(ord(item[0]), ord(item[3]) + 1))
        else:
            out.extend(item)
    return list(dict.fromkeys(out))


def _brotli_decompress(data, size):
    """Brotli-decompress `data` (at most `size` bytes out) with the system decoder through
    ctypes, or raise CoverageUnchecked. dlopen only: nothing is spawned."""
    import ctypes
    lib = None
    for name in _BROTLI_LIBRARIES:
        try:
            lib = ctypes.CDLL(name)
            break
        except OSError:
            continue
    if lib is None:
        raise CoverageUnchecked("WOFF2 tables are Brotli-compressed and no Brotli decoder "
                                "(libbrotlidec) can be loaded on this machine")
    decode = lib.BrotliDecoderDecompress
    decode.argtypes = [ctypes.c_size_t, ctypes.c_char_p, ctypes.POINTER(ctypes.c_size_t),
                       ctypes.c_char_p]
    decode.restype = ctypes.c_int
    out = ctypes.create_string_buffer(max(1, size))
    out_size = ctypes.c_size_t(size)
    if decode(len(data), bytes(data), ctypes.byref(out_size), out) != 1:
        raise CoverageUnchecked("the WOFF2 table data does not Brotli-decode")
    return out.raw[:out_size.value]


def _base128(data, pos):
    value = 0
    for i in range(5):
        byte = data[pos + i]
        if i == 0 and byte == 0x80:
            raise ValueError("UIntBase128 with a leading zero")
        value = (value << 7) | (byte & 0x7F)
        if not byte & 0x80:
            return value, pos + i + 1
    raise ValueError("UIntBase128 longer than 5 bytes")


def _cmap_table(data, fmt):
    """The raw `cmap` table of a font file."""
    import struct
    import zlib
    if fmt in ("ttf", "otf"):
        (num_tables,) = struct.unpack(">H", data[4:6])
        for i in range(num_tables):
            tag, _sum, offset, length = struct.unpack(">4sIII", data[12 + 16 * i:28 + 16 * i])
            if tag == b"cmap":
                return bytes(data[offset:offset + length])
        raise CoverageUnchecked("the font has no cmap table")
    if fmt == "woff":
        (num_tables,) = struct.unpack(">H", data[12:14])
        for i in range(num_tables):
            tag, offset, comp, orig, _sum = struct.unpack(">4sIIII", data[44 + 20 * i:64 + 20 * i])
            if tag == b"cmap":
                raw = bytes(data[offset:offset + comp])
                return zlib.decompress(raw) if comp < orig else raw
        raise CoverageUnchecked("the font has no cmap table")
    # WOFF2: a 48-byte header, a variable-length table directory, one Brotli stream holding
    # every table back to back in directory order. cmap is never transformed.
    flavor = bytes(data[4:8])
    if flavor == b"ttcf":
        raise CoverageUnchecked("a WOFF2 font collection is not read")
    num_tables, = struct.unpack(">H", data[12:14])
    compressed, = struct.unpack(">I", data[20:24])
    pos, offset, cmap = 48, 0, None
    for _ in range(num_tables):
        flags = data[pos]
        pos += 1
        index, version = flags & 0x3F, flags >> 6
        if index == 63:
            pos += 4
        orig, pos = _base128(data, pos)
        transformed = (version == 0) if index in (_WOFF2_GLYF, _WOFF2_LOCA) else (version != 0)
        length = orig
        if transformed:
            length, pos = _base128(data, pos)
        if index == _WOFF2_CMAP:
            cmap = (offset, length)
        offset += length
    if cmap is None:
        raise CoverageUnchecked("the font has no cmap table")
    tables = _brotli_decompress(bytes(data[pos:pos + compressed]), offset)
    return tables[cmap[0]:cmap[0] + cmap[1]]


def font_cmap(data):
    """{codepoint} the font maps to a glyph, from its Unicode cmap subtables (formats 4 and
    12, and 0/6 for completeness). Raises CoverageUnchecked when it cannot be read here."""
    import struct
    import zlib
    fmt = font_format(data)
    if fmt is None:
        raise CoverageUnchecked("not a TTF, OTF, WOFF or WOFF2 file")
    try:
        table = _cmap_table(data, fmt)
        _version, count = struct.unpack(">HH", table[:4])
        offsets = set()
        for i in range(count):
            platform, encoding, offset = struct.unpack(">HHI", table[4 + 8 * i:12 + 8 * i])
            if platform == 0 or (platform == 3 and encoding in (1, 10)):
                offsets.add(offset)
        mapped = set()
        for offset in sorted(offsets):
            (sub,) = struct.unpack(">H", table[offset:offset + 2])
            if sub == 4:
                (seg2,) = struct.unpack(">H", table[offset + 6:offset + 8])
                seg = seg2 // 2
                ends = struct.unpack(f">{seg}H", table[offset + 14:offset + 14 + seg2])
                base = offset + 16 + seg2
                starts = struct.unpack(f">{seg}H", table[base:base + seg2])
                deltas = struct.unpack(f">{seg}h", table[base + seg2:base + 2 * seg2])
                ranges_at = base + 2 * seg2
                ranges = struct.unpack(f">{seg}H", table[ranges_at:ranges_at + seg2])
                for k in range(seg):
                    for code in range(starts[k], ends[k] + 1):
                        if code == 0xFFFF:
                            continue
                        if ranges[k] == 0:
                            glyph = (code + deltas[k]) & 0xFFFF
                        else:
                            at = ranges_at + 2 * k + ranges[k] + 2 * (code - starts[k])
                            (glyph,) = struct.unpack(">H", table[at:at + 2])
                            if glyph:
                                glyph = (glyph + deltas[k]) & 0xFFFF
                        if glyph:
                            mapped.add(code)
            elif sub == 12:
                (groups,) = struct.unpack(">I", table[offset + 12:offset + 16])
                for g in range(groups):
                    start, end, glyph = struct.unpack(
                        ">III", table[offset + 16 + 12 * g:offset + 28 + 12 * g])
                    if end - start > 0x30000:
                        raise CoverageUnchecked("an implausible cmap group")
                    mapped.update(range(start + (1 if glyph == 0 else 0), end + 1))
            elif sub == 0:
                glyphs = table[offset + 6:offset + 262]
                mapped.update(code for code, glyph in enumerate(glyphs) if glyph)
            elif sub == 6:
                first, n = struct.unpack(">HH", table[offset + 6:offset + 10])
                glyphs = struct.unpack(f">{n}H", table[offset + 10:offset + 10 + 2 * n])
                mapped.update(first + k for k, glyph in enumerate(glyphs) if glyph)
    except zlib.error as exc:
        raise CoverageUnchecked(f"the WOFF table data does not decompress: {exc}") from None
    except (struct.error, ValueError, IndexError) as exc:
        raise CoverageUnchecked(f"the cmap table cannot be read: {exc}") from None
    if not mapped:
        raise CoverageUnchecked("the font has no Unicode cmap subtable")
    return mapped


def _coverage_check(checks, data, locales, bars):
    """font.coverage: the cmap maps every character each locale in scope needs."""
    if not locales:
        return
    try:
        mapped = font_cmap(data)
    except CoverageUnchecked as exc:
        _check(checks, "font.coverage", True,
               f"coverage unchecked for {', '.join(locales)}: {exc}", skipped_=True)
        return
    missing, unknown, covered = {}, [], []
    for locale in locales:
        chars = bars.locale_chars(locale)
        if chars is None:
            unknown.append(locale)
            continue
        lacking = [c for c in chars if ord(c) not in mapped]
        if lacking:
            missing[locale] = lacking
        else:
            covered.append(locale)
    parts = []
    if missing:
        parts.append("; ".join(
            f"{locale}: {len(lack)} of {len(bars.locale_chars(locale))} required characters "
            f"have no glyph ({''.join(lack[:12])}{'...' if len(lack) > 12 else ''}) - "
            f"{'/'.join((bars.locale(locale) or {}).get('subsets') or [])} not covered"
            for locale, lack in missing.items()))
    if covered:
        parts.append(f"covers {', '.join(covered)}")
    if unknown:
        parts.append(f"no character table for {', '.join(unknown)} (not judged)")
    summary = f"{len(mapped)} mapped characters; " + "; ".join(parts)
    if not missing and not covered:
        _check(checks, "font.coverage", True, summary, skipped_=True)
    else:
        _check(checks, "font.coverage", not missing, summary)


def font_quality(data, *, locales=(), bars=None, author=None):
    """The `quality` object of a font file: a real font a browser can load, not a stub, that
    can set every locale in the design's scope.

    TTF/OTF: the table directory is read and must hold `cmap`, `name` and outlines (`glyf`
    with `loca`, `CFF `/`CFF2`, or colour glyphs), with at least 60 glyphs (`maxp`). WOFF/WOFF2:
    the header's signature, flavour, table count and sizes are checked (the tables are
    compressed; a browser decompresses them). With `locales`, `font.coverage` reads the cmap
    (asset-quality.yaml `fonts.locales`): it fails when a locale's characters have no glyph,
    and is `skipped` ("coverage unchecked") when the cmap cannot be read here - a WOFF2 on a
    machine without the Brotli decoder. The licence is the asset policy's to judge."""
    import struct
    bars = bars or load_bars()
    locales = [str(x) for x in locales or [] if x]
    checks = []
    fmt = font_format(data)
    _check(checks, "font.format", fmt is not None,
           f"{fmt} font" if fmt else "not a TTF, OTF, WOFF or WOFF2 file")
    if fmt is None:
        return _result(checks, author)
    if fmt in ("ttf", "otf"):
        try:
            (num_tables,) = struct.unpack(">H", data[4:6])
            tables = {}
            for i in range(num_tables):
                tag, _sum, offset, length = struct.unpack(">4sIII", data[12 + 16 * i:28 + 16 * i])
                tables[tag.decode("latin-1")] = (offset, length)
        except struct.error:
            _check(checks, "font.tables", False, "the table directory is truncated")
            return _result(checks, author)
        outlines = ("glyf" in tables and "loca" in tables) or any(
            t in tables for t in ("CFF ", "CFF2", "CBDT", "sbix", "SVG "))
        missing = [t for t in ("cmap", "name") if t not in tables]
        _check(checks, "font.tables", not missing and outlines,
               f"{num_tables} tables" + (f"; missing {', '.join(missing)}" if missing else "")
               + ("" if outlines else "; no glyph outlines"))
        glyphs = None
        if "maxp" in tables:
            offset, _length = tables["maxp"]
            try:
                (glyphs,) = struct.unpack(">H", data[offset + 4:offset + 6])
            except struct.error:
                glyphs = None
        _check(checks, "font.glyphs", bool(glyphs and glyphs >= 60),
               f"{glyphs} glyphs" if glyphs is not None else "no maxp table: glyph count unknown")
        _coverage_check(checks, data, locales, bars)
        return _result(checks, author, parts=glyphs)
    try:
        # WOFF and WOFF2 share the leading fields: signature, flavour, length, numTables.
        _sig, flavor, length, num_tables = struct.unpack(">4s4sIH", data[:14])
    except struct.error:
        _check(checks, "font.header", False, "the header is truncated")
        return _result(checks, author)
    ok = flavor in (b"\x00\x01\x00\x00", b"OTTO", b"true") and length == len(data) and num_tables >= 6
    _check(checks, "font.header", ok,
           f"flavour {flavor!r}, {num_tables} tables, declared {length} bytes of {len(data)}")
    if ok:
        _coverage_check(checks, data, locales, bars)
    return _result(checks, author)



# -- audio ------------------------------------------------------------------------------------

def audio_quality(data, *, kind, loop=False, min_duration_s=None, max_bytes=None,
                  license_ok=None, bars=None, author=None):
    """The `quality` object of an audio file (sfx or music). `loop` and `min_duration_s` come
    from the design's build_spec.audio entry; `max_bytes` from the asset policy's kind;
    `license_ok` is whether the licence is recorded and permitted (None: not known here)."""
    bars = (bars or load_bars()).audio
    checks = []
    try:
        info = audiofile.read(data)
    except audiofile.AudioError as exc:
        _check(checks, "audio.decodes", False, f"not audio this pipeline reads: {exc}")
        return _result(checks, author)
    decoded = info.samples is not None
    _check(checks, "audio.decodes", info.duration_s > 0,
           info.summary() + ("; samples decoded" if decoded else
                             "; headers read (no codec in the standard library)")
           if info.duration_s > 0 else f"{info.summary()}: no audio in it")

    duration = info.duration_s
    if kind == "music" or loop:
        floor = max(float(min_duration_s or 0),
                    bars.music_min_s if kind == "music" else bars.loop_min_s)
        _check(checks, "audio.duration", duration >= floor,
               f"{duration:.2f} s; a {'music' if kind == 'music' else 'looping'} asset needs "
               f"at least {floor:g} s")
    else:
        floor = float(min_duration_s or 0)
        ok = floor <= duration <= max(bars.sfx_max_s, floor)
        _check(checks, "audio.duration", ok,
               f"{duration:.2f} s; a one-shot is at most {max(bars.sfx_max_s, floor):g} s"
               + (f" and at least {floor:g} s" if floor else ""))

    measured = audiofile.levels(info, bars.window_s) if decoded else None
    if measured is None:
        _check(checks, "audio.not-silent", True,
               f"{info.format} ({info.codec}) is not decoded here; its level is measured in "
               f"the running game (production check audio.plays)", skipped_=True)
    else:
        loud = measured["loudest_dbfs"]
        _check(checks, "audio.not-silent", loud >= bars.min_rms_dbfs,
               f"loudest {bars.window_s:g} s window {loud:.1f} dBFS RMS (peak "
               f"{measured['peak_dbfs']:.1f} dBFS); the floor is {bars.min_rms_dbfs:g} dBFS")

    if loop:
        joined = audiofile.seam(info, bars.seam_edge_ms) if decoded else None
        if joined is None:
            _check(checks, "audio.loop-seam", True,
                   f"{info.format} ({info.codec}) is not decoded here; its seam is the "
                   f"encoder's (an Ogg Opus end trim, an Info/LAME gapless record)",
                   skipped_=True)
        else:
            ok = joined["ratio"] <= bars.seam_ratio and joined["edge_db"] <= bars.seam_edge_db
            _check(checks, "audio.loop-seam", ok,
                   f"end-to-start jump {joined['jump']:.4f} = {joined['ratio']:.1f}x the "
                   f"typical step (bar {bars.seam_ratio:g}x); level across the seam differs "
                   f"{joined['edge_db']:.1f} dB (bar {bars.seam_edge_db:g} dB)")

    if max_bytes:
        _check(checks, "audio.size", len(data) <= max_bytes,
               f"{len(data)} bytes; the {kind} budget is {max_bytes}")
    if license_ok is not None:
        _check(checks, "audio.licence", bool(license_ok),
               "licence recorded and permitted" if license_ok else
               "no permitted licence recorded: it cannot ship")
    return _result(checks, author, parts=info.channels)


# -- variants -----------------------------------------------------------------------------------

_NUMBER = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")
_TRANSFORM = re.compile(r"(matrix|translate|scale|rotate|skewX|skewY)\s*\(([^)]*)\)")
_PATH_TOKEN = re.compile(r"[MmLlHhVvCcSsQqTtAaZz]|[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")
_PATH_ARGS = {"M": 2, "L": 2, "H": 1, "V": 1, "C": 6, "S": 4, "Q": 4, "T": 2, "A": 7, "Z": 0}


def _numbers(text):
    return [float(n) for n in _NUMBER.findall(text or "")]


def _multiply(m, n):
    a, b, c, d, e, f = m
    a2, b2, c2, d2, e2, f2 = n
    return (a * a2 + c * b2, b * a2 + d * b2, a * c2 + c * d2, b * c2 + d * d2,
            a * e2 + c * f2 + e, b * e2 + d * f2 + f)


def _transform(text):
    """The affine matrix (a, b, c, d, e, f) of an SVG transform attribute."""
    import math
    matrix = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    for name, args in _TRANSFORM.findall(text or ""):
        v = _numbers(args)
        step = None
        if name == "matrix" and len(v) == 6:
            step = tuple(v)
        elif name == "translate" and v:
            step = (1, 0, 0, 1, v[0], v[1] if len(v) > 1 else 0)
        elif name == "scale" and v:
            step = (v[0], 0, 0, v[1] if len(v) > 1 else v[0], 0, 0)
        elif name == "rotate" and v:
            r = math.radians(v[0])
            step = (math.cos(r), math.sin(r), -math.sin(r), math.cos(r), 0, 0)
            if len(v) == 3:
                step = _multiply(_multiply((1, 0, 0, 1, v[1], v[2]), step), (1, 0, 0, 1, -v[1], -v[2]))
        elif name in ("skewX", "skewY") and v:
            t = math.tan(math.radians(v[0]))
            step = (1, 0, t, 1, 0, 0) if name == "skewX" else (1, t, 0, 1, 0, 0)
        if step:
            matrix = _multiply(matrix, step)
    return matrix


def _path_points(d):
    """The subpaths of SVG path data as point lists: segment ends and curve control points
    (the curve lies inside their hull), absolute coordinates."""
    tokens = _PATH_TOKEN.findall(d or "")
    subpaths, points = [], []
    x = y = sx = sy = 0.0
    command, i = None, 0
    while i < len(tokens):
        if tokens[i].isalpha():
            command = tokens[i]
            i += 1
            if command in "Zz":
                if points:
                    subpaths.append(points)
                points, x, y = [], sx, sy
                continue
        if command is None:
            break
        upper = command.upper()
        count = _PATH_ARGS[upper]
        args = tokens[i:i + count]
        if len(args) < count or any(a.isalpha() for a in args):
            break
        i += count
        v = [float(a) for a in args]
        rel = command.islower()
        if upper == "H":
            x = x + v[0] if rel else v[0]
            points.append((x, y))
            continue
        if upper == "V":
            y = y + v[0] if rel else v[0]
            points.append((x, y))
            continue
        if upper == "A":
            v = v[5:7]
        pairs = [(v[k] + (x if rel else 0), v[k + 1] + (y if rel else 0)) for k in range(0, len(v), 2)]
        if upper == "M":
            if points:
                subpaths.append(points)
            points = []
            sx, sy = pairs[0]
            command = "l" if rel else "L"
        points.extend(pairs)
        x, y = pairs[-1]
    if points:
        subpaths.append(points)
    return subpaths


def _attr(element, name, inherited):
    style = element.get("style") or ""
    for declaration in style.split(";"):
        if ":" in declaration:
            key, value = declaration.split(":", 1)
            if key.strip() == name:
                return value.strip()
    return element.get(name, inherited)


def _shapes(element, matrix, fill, drawn, out):
    """[(polygon points in canvas units, filled?)] of the drawn shapes under `element`."""
    import math
    name = _local(element.tag)
    if name in NOT_DRAWN or not drawn:
        return
    if (_attr(element, "display", "") == "none" or _attr(element, "visibility", "") == "hidden"
            or _attr(element, "opacity", "1") in ("0", "0.0")):
        return
    matrix = _multiply(matrix, _transform(element.get("transform")))
    fill = _attr(element, "fill", fill)
    num = lambda key: float((_numbers(element.get(key)) or [0])[0])  # noqa: E731
    polys = []
    if name == "rect":
        x, y, w, h = num("x"), num("y"), num("width"), num("height")
        if w > 0 and h > 0:
            polys.append([(x, y), (x + w, y), (x + w, y + h), (x, y + h)])
    elif name in ("circle", "ellipse"):
        cx, cy = num("cx"), num("cy")
        rx = num("r") if name == "circle" else num("rx")
        ry = num("r") if name == "circle" else num("ry")
        if rx > 0 and ry > 0:
            polys.append([(cx + rx * math.cos(k * math.pi / 12), cy + ry * math.sin(k * math.pi / 12))
                          for k in range(24)])
    elif name == "line":
        out.append(([_apply(matrix, (num("x1"), num("y1"))), _apply(matrix, (num("x2"), num("y2")))],
                    False))
    elif name in ("polyline", "polygon"):
        v = _numbers(element.get("points"))
        polys.append(list(zip(v[0::2], v[1::2])))
    elif name == "path":
        polys.extend(_path_points(element.get("d")))
    filled = (fill or "black").strip().lower() not in ("none", "transparent")
    for poly in polys:
        if len(poly) >= 2:
            out.append(([_apply(matrix, p) for p in poly], filled and len(poly) >= 3))
    for child in element:
        _shapes(child, matrix, fill, True, out)


def _apply(m, p):
    return (m[0] * p[0] + m[2] * p[1] + m[4], m[1] * p[0] + m[3] * p[1] + m[5])


def _inside(x, y, poly):
    inside, j = False, len(poly) - 1
    for i in range(len(poly)):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi:
            inside = not inside
        j = i
    return inside


def _svg_silhouette(data, grid):
    if len(data) > 1048576 or re.search(rb"<!\s*(DOCTYPE|ENTITY)", data, re.I):
        return None
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        return None
    box = _viewbox(root)
    if box is None:
        w, h = _length(root.get("width")), _length(root.get("height"))
        if not w or not h:
            return None
        box = [0.0, 0.0, w, h]
    shapes = []
    for child in root:
        _shapes(child, (1.0, 0.0, 0.0, 1.0, 0.0, 0.0), _attr(root, "fill", None), True, shapes)
    cell_w, cell_h = box[2] / grid, box[3] / grid
    mask = set()
    for poly, filled in shapes:
        xs, ys = [p[0] for p in poly], [p[1] for p in poly]
        c0 = max(0, int((min(xs) - box[0]) / cell_w))
        c1 = min(grid - 1, int((max(xs) - box[0]) / cell_w))
        r0 = max(0, int((min(ys) - box[1]) / cell_h))
        r1 = min(grid - 1, int((max(ys) - box[1]) / cell_h))
        if filled:
            for r in range(r0, r1 + 1):
                for c in range(c0, c1 + 1):
                    if (r, c) not in mask and _inside(box[0] + (c + 0.5) * cell_w,
                                                      box[1] + (r + 0.5) * cell_h, poly):
                        mask.add((r, c))
        else:
            for (ax, ay), (bx, by) in zip(poly, poly[1:]):
                steps = max(1, int(max(abs(bx - ax) / cell_w, abs(by - ay) / cell_h) * 2))
                for k in range(steps + 1):
                    px, py = ax + (bx - ax) * k / steps, ay + (by - ay) * k / steps
                    c, r = int((px - box[0]) / cell_w), int((py - box[1]) / cell_h)
                    if 0 <= r < grid and 0 <= c < grid:
                        mask.add((r, c))
    return frozenset(mask)


def _png_silhouette(data, grid, delta):
    try:
        image = raster.decode_png(data)
    except raster.RasterError:
        return None
    px, w, h = image.pixels, image.width, image.height
    if not w or not h:
        return None
    alpha = any(px[i + 3] < 16 for i in range(3, len(px), 4 * max(1, (w * h) // 4096)))
    corner = px[0:3]
    mask = set()
    for r in range(grid):
        for c in range(grid):
            x, y = min(w - 1, int((c + 0.5) * w / grid)), min(h - 1, int((r + 0.5) * h / grid))
            i = (y * w + x) * 4
            if alpha:
                on = px[i + 3] >= 16
            else:
                on = max(abs(px[i + k] - corner[k]) for k in range(3)) >= delta
            if on:
                mask.add((r, c))
    return frozenset(mask)


def silhouette(data, fmt, bars=None):
    """The drawing's silhouette: the set of (row, col) cells of a grid x grid mask over its
    canvas that it covers, or None when it cannot be read."""
    bars = bars or load_bars()
    if fmt == "svg":
        return _svg_silhouette(data, bars.variant_grid)
    if fmt == "png":
        return _png_silhouette(data, bars.variant_grid, bars.png_background_delta)
    return None


def variants_distinct(drawings, bars=None):
    """The `variants.distinct` check of a counted requirement's drawings [(id, bytes, fmt)]:
    every pair's silhouettes differ by at least the bar (1 - IoU of their masks). A recolour,
    or a copy with only its numeral changed, is the same silhouette. Returns a check entry
    with `measured` {pairs: {"a~b": distance}, closest}, or None with fewer than 2 drawings."""
    bars = bars or load_bars()
    masks, unread = [], []
    for vid, data, fmt in drawings:
        mask = silhouette(data, fmt, bars)
        (unread.append(vid) if mask is None else masks.append((vid, mask)))
    if len(masks) + len(unread) < 2:
        return None
    pairs, same = {}, []
    for i in range(len(masks)):
        for j in range(i + 1, len(masks)):
            (a, ma), (b, mb) = masks[i], masks[j]
            union = len(ma | mb)
            distance = round(1 - len(ma & mb) / union, 3) if union else 0.0
            pairs[f"{a}~{b}"] = distance
            if distance < bars.min_silhouette_distance:
                same.append((distance, a, b))
    bar = bars.min_silhouette_distance
    closest = min(pairs.items(), key=lambda kv: kv[1]) if pairs else None
    if same:
        same.sort()
        summary = (f"{len(same)} pair(s) of drawings share a silhouette: "
                   + ", ".join(f"{a} and {b} differ by {d:.2f}" for d, a, b in same[:6])
                   + f"; the bar is {bar:.2f} (1 - IoU of their {bars.variant_grid}x"
                     f"{bars.variant_grid} masks) - draw each variant as its own shape and "
                     "size, never a recolour or a changed numeral")
    elif unread:
        summary = f"cannot read the silhouette of {', '.join(unread)}"
    else:
        summary = (f"{len(masks)} drawings, every pair differs; the closest, "
                   f"{closest[0].replace('~', ' and ')}, by {closest[1]:.2f} (bar {bar:.2f})")
    entry = {"id": "variants.distinct", "status": "fail" if (same or unread) else "pass",
             "summary": summary}
    return entry, {"pairs": pairs, "closest": closest[1] if closest else None, "bar": bar}

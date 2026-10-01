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
    raster_quality(data, ...)  a PNG decoded through wgf_assets.raster:
        raster.decodes         a PNG this pipeline can read
        raster.not-flat        more than one flat colour
        raster.alpha           a cut-out kind carries alpha and some transparent pixels

Each returns the asset-manifest `quality` object: {verdict, checks, primitive_only, parts,
colors, author}. `problems(quality)` is the list an author is shown when it is asked again.
"""

import os
import re
import xml.etree.ElementTree as ET

from wgflib import paths
from wgflib.yamllite import load_file

from . import raster

__all__ = ["load_bars", "svg_quality", "raster_quality", "font_quality", "font_format", "skipped", "problems",
           "parse_palette", "BARS_PATH", "QualityBars"]

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


def font_format(data):
    """ttf | otf | woff | woff2 from the file's signature, else None."""
    head = bytes(data[:4])
    if head in _SFNT:
        return _SFNT[head]
    return {b"wOFF": "woff", b"wOF2": "woff2"}.get(head)


def font_quality(data, *, author=None):
    """The `quality` object of a font file: a real font a browser can load, not a stub.

    TTF/OTF: the table directory is read and must hold `cmap`, `name` and outlines (`glyf`
    with `loca`, `CFF `/`CFF2`, or colour glyphs), with at least 60 glyphs (`maxp`). WOFF/WOFF2:
    the header's signature, flavour, table count and sizes are checked (the tables are
    compressed; a browser decompresses them). The licence is the asset policy's to judge."""
    import struct
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
    return _result(checks, author)


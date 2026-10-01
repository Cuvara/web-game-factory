"""A stand-in 2D asset author for the tests: argv <mode> <request> <output>.

It reads the request the assets step wrote, appends it to calls.jsonl beside the request
(what the tests assert on), and writes an SVG at <output> as its mode says:

    good            a recognisable multi-shape drawing in the request's palette colours; each
                    variant of a counted requirement smaller than the one before
    same-variants   the good drawing at one size for every variant: the variants differ by
                    colour only (rotated palette), every time
    same-then-good  the same-variants drawing first; the good one once asked to repair
    rect-then-good  one plain rect first; the good drawing once asked to repair
    rect            one plain rect, every time
    script          a good drawing with a <script> in it
    off-palette     a multi-shape drawing in colours the palette does not have
    fail            exits 3 without writing anything
"""

import json
import os
import sys

mode, request_path, output = sys.argv[1:4]
with open(request_path, encoding="utf-8") as handle:
    request = json.load(handle)
with open(os.path.join(os.path.dirname(request_path), "calls.jsonl"), "a",
          encoding="utf-8") as handle:
    handle.write(json.dumps(request, sort_keys=True) + "\n")

if mode == "fail":
    print("author crashed", file=sys.stderr)
    sys.exit(3)

palette = [entry["hex"] for entry in request.get("palette") or []] or ["#FF2E88", "#2EF2FF",
                                                                       "#16162A"]
asset = request["asset"]
width = asset.get("width") or 96
height = asset.get("height") or 96


def good(colours, k=None):
    if k is None:
        k = 1.0 - 0.2 * ((asset.get("variant_index") or 1) - 1)
    a, b, c = (colours * 3)[:3]
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
            f'viewBox="0 0 {width} {height}">'
            f'<title>{asset["id"]}</title>'
            f'<ellipse cx="{width / 2}" cy="{height * 0.6}" rx="{width * 0.35 * k}" '
            f'ry="{height * 0.3 * k}" fill="{a}"/>'
            f'<circle cx="{width / 2}" cy="{height * 0.3}" r="{width * 0.18 * k}" fill="{b}"/>'
            f'<path d="M {width * 0.3} {height * 0.8} L {width / 2} {height * 0.95} '
            f'L {width * 0.7} {height * 0.8} Z" fill="{c}"/>'
            f'<circle cx="{width * 0.45}" cy="{height * 0.28}" r="{width * 0.03}" '
            f'fill="#000000"/>'
            f'</svg>')


rect = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}">'
        f'<rect width="{width}" height="{height}" fill="{palette[0]}"/></svg>')

if mode == "good":
    svg = good(palette)
elif mode == "same-variants":
    shift = (asset.get("variant_index") or 1) - 1
    svg = good(palette[shift:] + palette[:shift], k=1.0)
elif mode == "same-then-good":
    shift = (asset.get("variant_index") or 1) - 1
    svg = good(palette) if request.get("repair") else good(palette[shift:] + palette[:shift], k=1.0)
elif mode == "rect-then-good":
    svg = good(palette) if request.get("repair") else rect
elif mode == "rect":
    svg = rect
elif mode == "script":
    svg = good(palette).replace("</svg>", "<script>alert(1)</script></svg>")
elif mode == "off-palette":
    svg = good(["#13A10E", "#8B4513", "#4B0082"])
else:
    sys.exit(f"unknown mode {mode}")
with open(output, "w", encoding="utf-8") as handle:
    handle.write(svg)

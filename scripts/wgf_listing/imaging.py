"""Pixel work the listing needs, standard library only, on wgf_assets.raster's RGBA images.

    resize(image, width, height)        box-filter downscale / bilinear upscale
    fit(image, width, height, mode)     cover (fill and centre-crop) or contain (letterbox
                                        over `background`)
    crop_center(image, width, height)   the largest centred region of that aspect
    fill(width, height, rgba)           a flat image
    composite(under, over, x, y)        alpha-blend `over` onto `under`
    read_png(path) / write_png(path, image)
    frame_stats(path) / changed_fraction(a, b, min_delta)   the playability bars, reused

Everything here is deterministic: the same pixels give the same bytes (raster.encode_png),
which is what lets a re-executed step find a rendition it wrote before.
"""

import os

from wgf_assets.raster import Image, RasterError, decode_png, encode_png
from wgf_playability.analysis import changed_fraction, frame_stats

__all__ = ["Image", "RasterError", "read_png", "write_png", "resize", "fit", "crop_center",
           "fill", "composite", "frame_stats", "changed_fraction", "parse_hex", "aspect_of"]


def read_png(path):
    with open(path, "rb") as handle:
        return decode_png(handle.read())


def write_png(path, image):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    data = encode_png(image)
    with open(path, "wb") as handle:
        handle.write(data)
    return data


def parse_hex(value, default=(0, 0, 0, 255)):
    """`#rgb` / `#rrggbb` / `#rrggbbaa` -> (r, g, b, a); `default` for anything else."""
    text = str(value or "").strip().lstrip("#")
    if len(text) == 3:
        text = "".join(c * 2 for c in text)
    if len(text) not in (6, 8):
        return default
    try:
        r, g, b = int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16)
        a = int(text[6:8], 16) if len(text) == 8 else 255
    except ValueError:
        return default
    return (r, g, b, a)


def aspect_of(width, height):
    """`w:h` reduced, e.g. 1920x1080 -> "16:9"."""
    from math import gcd
    g = gcd(int(width), int(height)) or 1
    return f"{int(width) // g}:{int(height) // g}"


def fill(width, height, rgba):
    image = Image(width, height)
    row = bytes(rgba) * width
    stride = width * 4
    for y in range(height):
        image.pixels[y * stride:(y + 1) * stride] = row
    return image


def resize(image, width, height):
    """Resample to width x height. Downscaling averages every source pixel inside each
    destination cell (a box filter: no aliasing on fine art); upscaling is bilinear."""
    width, height = int(width), int(height)
    if (width, height) == (image.width, image.height):
        return Image(image.width, image.height, image.pixels)
    if width <= image.width and height <= image.height:
        return _box_down(image, width, height)
    # Mixed or up: resample each axis separately so a box filter still applies where the
    # image shrinks.
    mid = image
    if width < image.width:
        mid = _box_down(mid, width, mid.height)
    if height < mid.height:
        mid = _box_down(mid, mid.width, height)
    return _bilinear(mid, width, height)


def _box_down(image, width, height):
    out = Image(width, height)
    src, sw, sh = image.pixels, image.width, image.height
    out_px = out.pixels
    xs = [(x * sw) // width for x in range(width + 1)]
    ys = [(y * sh) // height for y in range(height + 1)]
    for y in range(height):
        y0, y1 = ys[y], max(ys[y + 1], ys[y] + 1)
        for x in range(width):
            x0, x1 = xs[x], max(xs[x + 1], xs[x] + 1)
            r = g = b = a = 0
            count = (y1 - y0) * (x1 - x0)
            for yy in range(y0, y1):
                base = (yy * sw + x0) * 4
                chunk = src[base:base + (x1 - x0) * 4]
                r += sum(chunk[0::4])
                g += sum(chunk[1::4])
                b += sum(chunk[2::4])
                a += sum(chunk[3::4])
            o = (y * width + x) * 4
            out_px[o] = (r + count // 2) // count
            out_px[o + 1] = (g + count // 2) // count
            out_px[o + 2] = (b + count // 2) // count
            out_px[o + 3] = (a + count // 2) // count
    return out


def _bilinear(image, width, height):
    out = Image(width, height)
    src, sw, sh = image.pixels, image.width, image.height
    out_px = out.pixels
    for y in range(height):
        fy = (y + 0.5) * sh / height - 0.5
        y0 = min(max(int(fy), 0), sh - 1)
        y1 = min(y0 + 1, sh - 1)
        wy = min(max(fy - y0, 0.0), 1.0)
        for x in range(width):
            fx = (x + 0.5) * sw / width - 0.5
            x0 = min(max(int(fx), 0), sw - 1)
            x1 = min(x0 + 1, sw - 1)
            wx = min(max(fx - x0, 0.0), 1.0)
            o = (y * width + x) * 4
            p00, p01 = (y0 * sw + x0) * 4, (y0 * sw + x1) * 4
            p10, p11 = (y1 * sw + x0) * 4, (y1 * sw + x1) * 4
            for c in range(4):
                top = src[p00 + c] * (1 - wx) + src[p01 + c] * wx
                bottom = src[p10 + c] * (1 - wx) + src[p11 + c] * wx
                out_px[o + c] = int(round(top * (1 - wy) + bottom * wy))
    return out


def crop_center(image, width, height):
    """The largest centred region of `image` with the aspect of width:height, uncropped in
    size (callers resize afterwards)."""
    target = width / height
    current = image.width / image.height
    if abs(target - current) < 1e-9:
        return Image(image.width, image.height, image.pixels)
    if current > target:  # too wide
        new_w = max(1, int(round(image.height * target)))
        x = (image.width - new_w) // 2
        return image.crop(x, 0, new_w, image.height)
    new_h = max(1, int(round(image.width / target)))
    y = (image.height - new_h) // 2
    return image.crop(0, y, image.width, new_h)


def fit(image, width, height, mode="cover", background=(0, 0, 0, 255)):
    """`cover`: scale to fill width x height and centre-crop the overflow. `contain`: scale
    to fit inside and centre over `background`."""
    width, height = int(width), int(height)
    if mode == "cover":
        return resize(crop_center(image, width, height), width, height)
    if mode != "contain":
        raise ValueError(f"unknown fit mode {mode!r}")
    scale = min(width / image.width, height / image.height)
    inner_w = max(1, int(round(image.width * scale)))
    inner_h = max(1, int(round(image.height * scale)))
    inner = resize(image, inner_w, inner_h)
    canvas = fill(width, height, background)
    return composite(canvas, inner, (width - inner_w) // 2, (height - inner_h) // 2)


def composite(under, over, x, y):
    """Alpha-blend `over` onto a copy of `under` with its top-left at (x, y)."""
    out = Image(under.width, under.height, under.pixels)
    for row in range(over.height):
        ty = y + row
        if ty < 0 or ty >= under.height:
            continue
        src = over.row(row)
        for col in range(over.width):
            tx = x + col
            if tx < 0 or tx >= under.width:
                continue
            a = src[col * 4 + 3]
            if a == 0:
                continue
            o = (ty * under.width + tx) * 4
            if a == 255:
                out.pixels[o:o + 4] = src[col * 4:col * 4 + 4]
                continue
            alpha = a / 255.0
            for c in range(3):
                out.pixels[o + c] = int(round(src[col * 4 + c] * alpha
                                              + out.pixels[o + c] * (1 - alpha)))
            out.pixels[o + 3] = max(out.pixels[o + 3], a)
    return out

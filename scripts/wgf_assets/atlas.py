"""Texture atlases: deterministic packing, and checking an atlas someone else wrote.

Packing takes named RGBA images and returns one atlas image plus its descriptor in the
TexturePacker "JSON Hash" shape - `frames` keyed by name, `animations`, `meta` - which PixiJS
(`Assets.load` of the .json, `Spritesheet`) and Phaser (`load.atlas`) both read unchanged.

Determinism is the point, not a side effect:

  * frames are placed in a fixed order - height, then width, descending, then name - never
    in the order a directory listing happened to return them;
  * the atlas size is chosen by trying candidate widths in a fixed order and keeping the
    smallest area (ties: the squarer, then the narrower);
  * the descriptor is written with sorted keys and carries no timestamp and no path beyond
    the image's own file name.

The same frames therefore give the same bytes, and a re-executed step reuses the atlas it
wrote. Shelf packing is used rather than MaxRects: at the sprite counts of a portal game the
difference is a few percent of atlas area, and shelf packing is simple enough to be obviously
deterministic.

`extrude` repeats each frame's edge pixels outward so linear filtering never samples a
neighbour (seams in tiles and scaled sprites); `padding` is transparent space between cells;
`trim` crops fully transparent borders and records the offset in `spriteSourceSize`, which
both engines honour.

`check_document(document, image_size)` validates any atlas descriptor: frames present and
well formed, inside the image, animations naming frames that exist.
"""

import json
import re

from .raster import Image, alpha_bounds

__all__ = ["AtlasError", "pack", "atlas_document", "check_document", "frame_order",
           "frames_of", "DEFAULT_OPTIONS", "GENERATOR"]

GENERATOR = "wgf-assets"
DEFAULT_OPTIONS = {"max_size": 2048, "padding": 2, "extrude": 1, "power_of_two": True,
                   "trim": False}


class AtlasError(ValueError):
    """The frames cannot be packed as asked, with what to change."""


def _next_pow2(n):
    size = 1
    while size < n:
        size <<= 1
    return size


def _natural_key(name):
    return [int(part) if part.isdigit() else part for part in re.split(r"(\d+)", name)]


def frame_order(names):
    """Frame names in natural order: `run-2` before `run-10`."""
    return sorted(names, key=_natural_key)


def _shelf(cells, width):
    """{name: (x, y)} and the used height for cells [(name, w, h)] on shelves `width` wide,
    or None when a cell is wider than the atlas."""
    x = y = shelf_h = 0
    placed = {}
    for name, w, h in cells:
        if w > width:
            return None, None
        if x + w > width:
            y += shelf_h
            x = shelf_h = 0
        placed[name] = (x, y)
        x += w
        shelf_h = max(shelf_h, h)
    return placed, y + shelf_h


def _options(options):
    merged = dict(DEFAULT_OPTIONS)
    merged.update({k: v for k, v in (options or {}).items() if v is not None})
    for key in ("max_size", "padding", "extrude"):
        value = merged[key]
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise AtlasError(f"atlas option {key} must be a non-negative integer")
    if merged["max_size"] < 1:
        raise AtlasError("atlas option max_size must be at least 1")
    return merged


def pack(sprites, options=None):
    """(atlas Image, {name: frame record}) for sprites [(name, Image)].

    Raises AtlasError for duplicate names, no sprites, or frames that cannot fit in
    max_size x max_size."""
    opts = _options(options)
    if not sprites:
        raise AtlasError("nothing to pack")
    names = [name for name, _ in sprites]
    duplicates = sorted({n for n in names if names.count(n) > 1})
    if duplicates:
        raise AtlasError(f"duplicate frame name(s): {', '.join(duplicates)}")

    pad, ext = opts["padding"], opts["extrude"]
    prepared = {}
    for name, image in sprites:
        source = (0, 0, image.width, image.height)
        if opts["trim"]:
            bounds = alpha_bounds(image)
            if bounds is None:  # fully transparent: keep one pixel so the frame exists
                bounds = (0, 0, 1, 1)
            source = bounds
        prepared[name] = (image, source)

    cells = sorted(((name, src[2] + 2 * ext + pad, src[3] + 2 * ext + pad)
                    for name, (_img, src) in prepared.items()),
                   key=lambda c: (-c[2], -c[1], c[0]))
    widest = max(w for _, w, _ in cells)
    area = sum(w * h for _, w, h in cells)
    max_size = opts["max_size"]

    best = None
    width = _next_pow2(max(widest, 1)) if opts["power_of_two"] else max(widest, 1)
    candidates = []
    if opts["power_of_two"]:
        while width <= max_size:
            candidates.append(width)
            width <<= 1
    else:
        # Every width from the widest cell to the atlas limit, in steps that keep the search
        # short; the order is fixed, so the choice is too.
        step = max(1, (max_size - width) // 64)
        candidates = list(range(width, max_size + 1, step))
        if candidates[-1] != max_size and max_size >= width:
            candidates.append(max_size)
    for candidate in candidates:
        placed, used = _shelf(cells, candidate)
        if placed is None:
            continue
        height = _next_pow2(used) if opts["power_of_two"] else used
        if height > max_size:
            continue
        key = (candidate * height, max(candidate, height), candidate)
        if best is None or key < best[0]:
            best = (key, candidate, height, placed)
    if best is None:
        raise AtlasError(
            f"{len(cells)} frame(s), {area} px² with padding, do not fit in "
            f"{max_size}x{max_size}; split the group into two atlases or raise max_size")
    _key, atlas_w, atlas_h, placed = best

    atlas = Image(atlas_w, atlas_h)
    frames = {}
    for name in sorted(prepared):
        image, (sx, sy, sw, sh) = prepared[name]
        cx, cy = placed[name]
        fx, fy = cx + ext, cy + ext
        _blit(atlas, image, sx, sy, sw, sh, fx, fy, ext)
        frames[name] = {
            "frame": {"x": fx, "y": fy, "w": sw, "h": sh},
            "rotated": False,
            "trimmed": (sw, sh) != (image.width, image.height),
            "spriteSourceSize": {"x": sx, "y": sy, "w": sw, "h": sh},
            "sourceSize": {"w": image.width, "h": image.height},
        }
    return atlas, frames


def _blit(atlas, image, sx, sy, sw, sh, dx, dy, extrude):
    """Copy the (sx, sy, sw, sh) rectangle of image to (dx, dy), repeating its edge pixels
    `extrude` times outward."""
    a_stride, i_stride = atlas.width * 4, image.width * 4
    rows = []
    for row in range(sh):
        start = (sy + row) * i_stride + sx * 4
        line = bytes(image.pixels[start:start + sw * 4])
        if extrude:
            line = line[:4] * extrude + line + line[-4:] * extrude
        rows.append(line)
    if extrude:
        rows = [rows[0]] * extrude + rows + [rows[-1]] * extrude
    x0, y0 = dx - extrude, dy - extrude
    for offset, line in enumerate(rows):
        start = (y0 + offset) * a_stride + x0 * 4
        atlas.pixels[start:start + len(line)] = line


def atlas_document(frames, image_name, size, *, animations=None, scale=1):
    """The descriptor bytes: JSON Hash, sorted keys, a trailing newline, nothing
    run-specific."""
    document = {
        "frames": frames,
        "meta": {"app": GENERATOR, "version": "1", "image": image_name,
                 "format": "RGBA8888", "size": {"w": size[0], "h": size[1]},
                 "scale": str(scale)},
    }
    if animations:
        document["animations"] = {name: list(seq) for name, seq in animations.items()}
    return (json.dumps(document, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _rect(value, keys):
    return isinstance(value, dict) and all(
        isinstance(value.get(k), int) and not isinstance(value.get(k), bool) and value[k] >= 0
        for k in keys)


def check_document(document, image_size=None):
    """[problem message] for an atlas descriptor. `image_size` (w, h), when known, bounds
    every frame. Accepts JSON Hash (`frames` an object) and JSON Array (`frames` a list of
    objects with `filename`)."""
    problems = []
    if not isinstance(document, dict):
        return ["the atlas is not a JSON object"]
    raw = document.get("frames")
    if isinstance(raw, list):
        frames = {}
        for index, entry in enumerate(raw):
            name = entry.get("filename") if isinstance(entry, dict) else None
            if not isinstance(name, str) or not name:
                problems.append(f"frames[{index}] has no filename")
                continue
            if name in frames:
                problems.append(f"frame {name!r} is listed twice")
            frames[name] = entry
    elif isinstance(raw, dict):
        frames = raw
    else:
        return ["no frames: the atlas has no `frames` object or list"]
    if not frames:
        problems.append("no frames: `frames` is empty")

    meta_size = (document.get("meta") or {}).get("size") if isinstance(
        document.get("meta"), dict) else None
    if image_size is None and _rect(meta_size, ("w", "h")):
        image_size = (meta_size["w"], meta_size["h"])
    elif image_size is not None and _rect(meta_size, ("w", "h")) and (
            meta_size["w"], meta_size["h"]) != tuple(image_size):
        problems.append(f"meta.size {meta_size['w']}x{meta_size['h']} does not match the "
                        f"image, {image_size[0]}x{image_size[1]}")

    for name in frame_order(frames):
        entry = frames[name]
        rect = entry.get("frame") if isinstance(entry, dict) else None
        if not _rect(rect, ("x", "y", "w", "h")) or not rect["w"] or not rect["h"]:
            problems.append(f"frame {name!r} has no valid frame {{x, y, w, h}}")
            continue
        w, h = (rect["h"], rect["w"]) if entry.get("rotated") else (rect["w"], rect["h"])
        if image_size and (rect["x"] + w > image_size[0] or rect["y"] + h > image_size[1]):
            problems.append(f"frame {name!r} ({rect['x']},{rect['y']} {w}x{h}) lies outside "
                            f"the {image_size[0]}x{image_size[1]} image")

    animations = document.get("animations")
    if animations is not None:
        if not isinstance(animations, dict):
            problems.append("`animations` is not an object")
        else:
            for anim in sorted(animations):
                sequence = animations[anim]
                if not isinstance(sequence, list) or not sequence:
                    problems.append(f"animation {anim!r} lists no frames")
                    continue
                missing = [f for f in sequence if f not in frames]
                if missing:
                    problems.append(f"animation {anim!r} names missing frame(s): "
                                    f"{', '.join(map(str, missing[:5]))}")
    return problems


def frames_of(document):
    """Frame names of an atlas descriptor, in natural order."""
    raw = (document or {}).get("frames") if isinstance(document, dict) else None
    if isinstance(raw, dict):
        return frame_order(raw)
    if isinstance(raw, list):
        return frame_order(e["filename"] for e in raw
                           if isinstance(e, dict) and isinstance(e.get("filename"), str))
    return []

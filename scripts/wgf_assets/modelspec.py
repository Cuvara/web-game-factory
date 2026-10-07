"""A 3D model described as data: what a design writes, what Blender builds, what is checked.

`game_design.asset_requirements[].model` (core/artifacts/shared/model-spec.schema.json) is
one object with two uses:

  * a **build spec**, when it has `parts`: primitives, materials, animation clips, LOD
    ratios and a collision proxy, built headless by the `blender` backend (blender.py);
  * an **expectation**, always: whatever it declares - clip names, LOD count, a collision
    proxy, a fitted size, a triangle budget - is checked against the delivered GLB,
    whichever source it came from (gltf.py), so a purchased model with a renamed clip fails
    the same way a generated one would.

Coordinates are glTF's, which are three.js's: metres, +Y up, a model faces +Z. Rotations are
Euler degrees in three.js's default XYZ order. The conversion to Blender's Z-up frame is the
build script's business and nobody else's; the exporter converts back.

`resolve()` turns a validated spec into what the build script reads: quaternions instead of
Euler angles, linear colours instead of sRGB hex, defaults filled in, parents before
children, and each texture as PNG bytes made here - so the texture bytes are this module's,
not an image encoder's inside Blender. Everything is deterministic; `spec_hash()` is the
canonical hash a generated file records and a rebuild is keyed on.
"""

import hashlib
import json
import math
import re
import struct
import zlib

from . import encoders

__all__ = ["ModelSpecError", "validate", "buildable", "resolve", "spec_hash", "expectations",
           "expand_parts", "SHAPES", "PATHS", "FIT_TOLERANCE", "MIRROR_SUFFIX"]

SHAPES = ("box", "cylinder", "cone", "sphere", "icosphere", "plane", "capsule", "extrude",
          "lathe")
# Shapes with sharp edges to bevel, and shapes smooth-shaded unless the part says otherwise.
BEVEL_SHAPES = ("box", "cylinder", "cone", "extrude")
SMOOTH_SHAPES = ("sphere", "icosphere", "capsule")
MIRRORS = ("x",)
MIRROR_SUFFIX = "-mirror"
TAPER = (0, 4)
PATHS = ("translation", "rotation", "scale")
PIVOTS = ("base-center", "center", "origin")
FIT_AXES = ("x", "y", "z", "max")
COLLISION_SHAPES = ("box", "convex")
PATTERNS = ("checker", "stripes")
INTERPOLATIONS = ("linear", "step")

MAX_PARTS = 64
# An extrude's outline and a lathe's profile: at most this many [a, b] points.
MAX_OUTLINE = 64
MAX_CLIPS = 16
MAX_KEYS = 256
MAX_LODS = 3
SEGMENTS = (3, 64)
TEXTURE_EDGE = (16, 2048)
# Relative tolerance on the fitted size. The build fits the real geometry exactly; this only
# absorbs the float32 round trip through the GLB.
FIT_TOLERANCE = 1e-3

_ID = re.compile(r"^[a-z][a-z0-9-]*$")
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


class ModelSpecError(ValueError):
    """A model spec that cannot be built or checked as written."""


def _num(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _vec(value, n=3):
    return isinstance(value, list) and len(value) == n and all(_num(v) for v in value)


def _points(value, low=2):
    return (isinstance(value, list) and low <= len(value) <= MAX_OUTLINE
            and all(_vec(p, 2) for p in value))


def _cross(o, a, b):
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def _segments_meet(a, b, c, d):
    """True when segment ab touches segment cd (collinear overlaps included)."""
    def on(p, q, r):
        return (min(p[0], r[0]) - 1e-12 <= q[0] <= max(p[0], r[0]) + 1e-12
                and min(p[1], r[1]) - 1e-12 <= q[1] <= max(p[1], r[1]) + 1e-12)
    d1, d2, d3, d4 = _cross(c, d, a), _cross(c, d, b), _cross(a, b, c), _cross(a, b, d)
    if ((d1 > 0) != (d2 > 0) and d1 != 0 and d2 != 0
            and (d3 > 0) != (d4 > 0) and d3 != 0 and d4 != 0):
        return True
    return ((d1 == 0 and on(c, a, d)) or (d2 == 0 and on(c, b, d))
            or (d3 == 0 and on(a, c, b)) or (d4 == 0 and on(a, d, b)))


def _crossing(points, closed):
    """The first pair of non-adjacent edges that meet, as indices, or None."""
    edges = [(i, (i + 1) % len(points)) for i in range(len(points) if closed
                                                         else len(points) - 1)]
    for x, (a, b) in enumerate(edges):
        for c, d in edges[x + 1:]:
            if len({a, b, c, d}) < 4:
                continue  # neighbours share a vertex by construction
            if _segments_meet(points[a], points[b], points[c], points[d]):
                return a, c
    return None


def outline_problems(outline):
    """What is wrong with an extrude's `outline` ([[x, z], ...], a closed polygon), as text."""
    if not _points(outline, 3):
        return [f"[[x, z], ...] - 3 to {MAX_OUTLINE} points"]
    if any(outline[i] == outline[(i + 1) % len(outline)] for i in range(len(outline))):
        return ["two consecutive points are the same"]
    area = sum(outline[i][0] * outline[(i + 1) % len(outline)][1]
               - outline[(i + 1) % len(outline)][0] * outline[i][1]
               for i in range(len(outline))) / 2
    span = max(max(p[k] for p in outline) - min(p[k] for p in outline) for k in (0, 1))
    if span <= 0:
        return ["the outline encloses no area"]
    crossing = _crossing(outline, closed=True)
    if crossing:
        return [f"the outline crosses itself (edges from points {crossing[0]} and "
                f"{crossing[1]}); list the points in order around the shape"]
    if abs(area) <= 1e-6 * span * span:
        return ["the outline encloses no area"]
    return []


def profile_problems(profile):
    """What is wrong with a lathe's `profile` ([[radius, y], ...], an open line), as text."""
    if not _points(profile, 2):
        return [f"[[radius, y], ...] - 2 to {MAX_OUTLINE} points"]
    if any(p[0] < 0 for p in profile):
        return ["a radius is negative"]
    if any(profile[i] == profile[i + 1] for i in range(len(profile) - 1)):
        return ["two consecutive points are the same"]
    if max(p[0] for p in profile) <= 0:
        return ["every radius is 0: the profile sweeps nothing"]
    if max(p[1] for p in profile) - min(p[1] for p in profile) <= 0:
        return ["every point is at one height: use a cylinder or a plane"]
    if any(p[0] == 0 for p in profile[1:-1]):
        return ["only the first and last points may sit on the axis (radius 0)"]
    crossing = _crossing(profile, closed=False)
    if crossing:
        return [f"the profile crosses itself (segments from points {crossing[0]} and "
                f"{crossing[1]})"]
    return []


def mirror_euler(degrees):
    """The rotation of a part mirrored across X = 0, as XYZ Euler degrees.

    Reflection M = diag(-1, 1, 1): M Rx(a) Ry(b) Rz(c) M = Rx(a) Ry(-b) Rz(-c)."""
    x, y, z = degrees
    return [x, -y + 0.0, -z + 0.0]


def expand_parts(parts):
    """The parts with every `mirror` written out: each mirrored part is followed by
    `<id>-mirror`, placed and turned across X = 0 of its parent, whose parent is the
    parent's mirror when the parent is mirrored too. The primitives and a lathe are symmetric
    across X, so mirroring the placement mirrors them; an extrude's outline is reflected too
    (x negated, the order reversed so it still runs the same way round). Assumes
    `validate()` passed."""
    mirrored = {p["id"] for p in parts if isinstance(p, dict) and p.get("mirror")}
    out = []
    for part in parts:
        copy = {k: v for k, v in part.items() if k != "mirror"}
        out.append(copy)
        if not part.get("mirror"):
            continue
        twin = dict(copy, id=part["id"] + MIRROR_SUFFIX)
        position = list(part.get("position", [0, 0, 0]))
        twin["position"] = [-position[0] + 0.0, position[1], position[2]]
        if "rotation" in part:
            twin["rotation"] = mirror_euler(part["rotation"])
        if "outline" in part:
            twin["outline"] = [[-p[0] + 0.0, p[1]] for p in reversed(part["outline"])]
        if part.get("parent") in mirrored:
            twin["parent"] = part["parent"] + MIRROR_SUFFIX
        out.append(twin)
    return out


def buildable(spec):
    """True when the spec describes geometry, not only expectations."""
    return isinstance(spec, dict) and bool(spec.get("parts"))


def validate(spec):
    """Every problem with `spec`, as strings; [] when it is valid.

    The JSON Schema says what the fields are; this says what they mean together: ids unique,
    parents and materials that exist, no parent cycle, keys inside their clip, LOD ratios
    that actually reduce, and no LODs on an animated model (its LOD1+ would be static)."""
    if not isinstance(spec, dict):
        return ["model must be an object"]
    problems = []
    add = problems.append

    materials = spec.get("materials") or []
    material_ids = set()
    for index, material in enumerate(materials):
        where = f"materials[{index}]"
        if not isinstance(material, dict) or not _ID.match(str(material.get("id") or "")):
            add(f"{where}: id must be kebab-case")
            continue
        if material["id"] in material_ids:
            add(f"{where}: duplicate material id {material['id']!r}")
        material_ids.add(material["id"])
        for key in ("color", "emissive"):
            if key in material and not _HEX.match(str(material[key])):
                add(f"{where}.{key}: expected #rrggbb")
        for key in ("metallic", "roughness", "opacity"):
            if key in material and not (_num(material[key]) and 0 <= material[key] <= 1):
                add(f"{where}.{key}: expected a number in 0..1")
        if "emissive_strength" in material and not (
                _num(material["emissive_strength"]) and 0 <= material["emissive_strength"] <= 100):
            add(f"{where}.emissive_strength: expected a number in 0..100")
        texture = material.get("texture")
        if texture is not None:
            if not isinstance(texture, dict) or texture.get("pattern") not in PATTERNS:
                add(f"{where}.texture.pattern: one of {', '.join(PATTERNS)}")
            else:
                size = texture.get("size", 128)
                if not (isinstance(size, int) and TEXTURE_EDGE[0] <= size <= TEXTURE_EDGE[1]
                        and size & (size - 1) == 0):
                    add(f"{where}.texture.size: a power of two in "
                        f"{TEXTURE_EDGE[0]}..{TEXTURE_EDGE[1]}")
                if "color2" in texture and not _HEX.match(str(texture["color2"])):
                    add(f"{where}.texture.color2: expected #rrggbb")
                repeat = texture.get("repeat", 1)
                if not (_num(repeat) and 1 <= repeat <= 64):
                    add(f"{where}.texture.repeat: expected a number in 1..64")

    parts = spec.get("parts") or []
    part_ids, parents = set(), {}
    mirror_ids = {f"{p['id']}{MIRROR_SUFFIX}" for p in parts
                  if isinstance(p, dict) and p.get("mirror") and isinstance(p.get("id"), str)}
    if len(parts) + len(mirror_ids) > MAX_PARTS:
        add(f"parts: at most {MAX_PARTS}, mirrors included")
    for index, part in enumerate(parts):
        where = f"parts[{index}]"
        if not isinstance(part, dict) or not _ID.match(str(part.get("id") or "")):
            add(f"{where}: id must be kebab-case")
            continue
        pid = part["id"]
        if pid in part_ids:
            add(f"{where}: duplicate part id {pid!r}")
        part_ids.add(pid)
        if part.get("shape") not in SHAPES:
            add(f"{where}.shape: one of {', '.join(SHAPES)}")
        size = part.get("size", [1, 1, 1])
        if not (_vec(size) and all(v >= 0 for v in size)
                and sum(1 for v in size if v > 0) >= (2 if part.get("shape") == "plane" else 3)):
            add(f"{where}.size: [x, y, z], non-negative, zero only on a plane's y")
        for key in ("position", "rotation"):
            if key in part and not _vec(part[key]):
                add(f"{where}.{key}: expected [x, y, z]")
        segments = part.get("segments", 16)
        if not (isinstance(segments, int) and SEGMENTS[0] <= segments <= SEGMENTS[1]):
            add(f"{where}.segments: an integer in {SEGMENTS[0]}..{SEGMENTS[1]}")
        shape = part.get("shape")
        for key, owner, check in (("outline", "extrude", outline_problems),
                                  ("profile", "lathe", profile_problems)):
            if key in part and shape != owner:
                add(f"{where}.{key}: only on a {owner}")
            elif shape == owner and key not in part:
                add(f"{where}.{key}: a {owner} needs one")
            elif shape == owner:
                problems.extend(f"{where}.{key}: {p}" for p in check(part[key]))
        if part.get("material") is not None and part["material"] not in material_ids:
            add(f"{where}.material: no material {part['material']!r}")
        if pid in mirror_ids:
            add(f"{where}: id {pid!r} is the name of another part's mirror")
        if "mirror" in part and part["mirror"] not in MIRRORS:
            add(f"{where}.mirror: one of {', '.join(MIRRORS)}")
        if "taper" in part:
            taper = part["taper"]
            if not (_vec(taper, 2) and all(TAPER[0] <= v <= TAPER[1] for v in taper)):
                add(f"{where}.taper: [x, z], each in {TAPER[0]}..{TAPER[1]}")
            elif part.get("shape") == "plane":
                add(f"{where}.taper: a plane has no height to taper")
        if "bevel" in part:
            bevel = part["bevel"]
            if part.get("shape") not in BEVEL_SHAPES:
                add(f"{where}.bevel: only on {', '.join(BEVEL_SHAPES)} (the others have no "
                    f"sharp edge)")
            elif not (_num(bevel) and bevel > 0):
                add(f"{where}.bevel: a positive number of metres")
            elif _vec(size) and min(size) > 0 and bevel > min(size) / 3 + 1e-12:
                add(f"{where}.bevel: at most a third of the part's smallest side "
                    f"({min(size) / 3:.4g} m)")
        if part.get("parent") is not None:
            parents[pid] = part["parent"]
    all_ids = part_ids | {i for i in mirror_ids if i[:-len(MIRROR_SUFFIX)] in part_ids}
    for child, parent in parents.items():
        if parent not in part_ids:
            add(f"part {child!r}: parent {parent!r} is not a part")
            continue
        seen, node = {child}, parent
        while node in parents:
            if node in seen:
                add(f"part {child!r}: parent chain is a cycle")
                break
            seen.add(node)
            node = parents[node]

    pivot = spec.get("pivot", "base-center")
    if pivot not in PIVOTS:
        add(f"pivot: one of {', '.join(PIVOTS)}")
    fit = spec.get("fit")
    if fit is not None:
        if not isinstance(fit, dict) or not (_num(fit.get("size")) and fit["size"] > 0):
            add("fit.size: a positive number of metres")
        elif fit.get("axis", "max") not in FIT_AXES:
            add(f"fit.axis: one of {', '.join(FIT_AXES)}")

    animations = spec.get("animations") or []
    if len(animations) > MAX_CLIPS:
        add(f"animations: at most {MAX_CLIPS}")
    clip_names = set()
    for index, clip in enumerate(animations):
        where = f"animations[{index}]"
        if not isinstance(clip, dict) or not isinstance(clip.get("name"), str) or not clip["name"]:
            add(f"{where}: name is required")
            continue
        if clip["name"] in clip_names:
            add(f"{where}: duplicate clip {clip['name']!r}")
        clip_names.add(clip["name"])
        duration = clip.get("duration")
        if duration is not None and not (_num(duration) and 0 < duration <= 60):
            add(f"{where}.duration: seconds in (0, 60]")
        if clip.get("interpolation", "linear") not in INTERPOLATIONS:
            add(f"{where}.interpolation: one of {', '.join(INTERPOLATIONS)}")
        tracks = clip.get("tracks")
        if tracks is None:
            continue  # an expectation only: the clip must exist in the GLB
        if not isinstance(tracks, list) or not tracks:
            add(f"{where}.tracks: at least one track")
            continue
        for t_index, track in enumerate(tracks):
            t_where = f"{where}.tracks[{t_index}]"
            if not isinstance(track, dict):
                add(f"{t_where}: expected an object")
                continue
            if track.get("part") not in all_ids:
                add(f"{t_where}.part: no part {track.get('part')!r}")
            if track.get("path") not in PATHS:
                add(f"{t_where}.path: one of {', '.join(PATHS)}")
            keys = track.get("keys")
            if not isinstance(keys, list) or not 1 <= len(keys) <= MAX_KEYS:
                add(f"{t_where}.keys: 1..{MAX_KEYS} keys")
                continue
            last = -1.0
            for k_index, key in enumerate(keys):
                if not (isinstance(key, dict) and _num(key.get("t")) and _vec(key.get("value"))):
                    add(f"{t_where}.keys[{k_index}]: {{t: seconds, value: [x, y, z]}}")
                    continue
                if key["t"] < 0 or key["t"] <= last and k_index:
                    add(f"{t_where}.keys[{k_index}].t: times must increase from 0")
                if duration is not None and key["t"] > duration + 1e-9:
                    add(f"{t_where}.keys[{k_index}].t: after the clip's duration")
                if (track.get("path") == "rotation" and k_index
                        and _vec(keys[k_index - 1].get("value"))
                        and max(abs(a - b) for a, b in zip(key["value"],
                                                           keys[k_index - 1]["value"])) >= 180):
                    # Keys become quaternions, and a runtime slerps the short way round: a
                    # 0 -> 360 pair is no motion at all.
                    add(f"{t_where}.keys[{k_index}]: a rotation step of 180 degrees or more "
                        f"on one axis; split it into smaller steps")
                last = key["t"]
        if duration is None:
            add(f"{where}.duration: required when the clip has tracks")
        for t_index, track in enumerate(tracks):
            if (isinstance(track, dict) and isinstance(track.get("keys"), list)
                    and len({json.dumps(k.get("value")) for k in track["keys"]
                             if isinstance(k, dict)}) == 1):
                # The glTF exporter drops a channel whose value never changes - even one held
                # away from the rest pose - so a held track would silently not exist.
                add(f"{where}.tracks[{t_index}]: its value never changes; the exporter drops "
                    f"constant channels, so key a change or remove the track")

    lods = spec.get("lods")
    if lods is not None:
        if isinstance(lods, int) and not isinstance(lods, bool):
            if not 0 <= lods <= MAX_LODS:
                add(f"lods: 0..{MAX_LODS} levels beyond LOD0")
        elif not (isinstance(lods, list) and len(lods) <= MAX_LODS
                  and all(_num(r) and 0 < r < 1 for r in lods)
                  and all(a > b for a, b in zip(lods, lods[1:]))):
            add(f"lods: up to {MAX_LODS} decreasing ratios in (0, 1)")
        elif parts and lods and any(c.get("tracks") for c in animations if isinstance(c, dict)):
            add("lods: an animated model has one level - LOD1+ would be static meshes")

    collision = spec.get("collision")
    if collision is not None and not (isinstance(collision, dict)
                                      and collision.get("shape") in COLLISION_SHAPES):
        add(f"collision.shape: one of {', '.join(COLLISION_SHAPES)}")

    budget = spec.get("budget") or {}
    for key in ("max_triangles", "max_texture_edge", "max_bytes"):
        if key in budget and not (isinstance(budget[key], int) and budget[key] > 0):
            add(f"budget.{key}: a positive integer")

    fps = spec.get("fps", 30)
    if not (isinstance(fps, int) and 1 <= fps <= 120):
        add("fps: an integer in 1..120")
    return problems


def spec_hash(spec):
    """sha256 of the canonical JSON of `spec`: the key a generated file records."""
    text = json.dumps(spec, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _srgb_to_linear(channel):
    c = channel / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _hex(value):
    value = value.lstrip("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def _linear(value):
    return [round(_srgb_to_linear(c), 6) for c in _hex(value)]


def euler_to_quaternion(degrees):
    """three.js Quaternion.setFromEuler, order XYZ; [x, y, z, w] as glTF stores it."""
    x, y, z = (math.radians(v) / 2 for v in degrees)
    c1, c2, c3 = math.cos(x), math.cos(y), math.cos(z)
    s1, s2, s3 = math.sin(x), math.sin(y), math.sin(z)
    quat = [s1 * c2 * c3 + c1 * s2 * s3,
            c1 * s2 * c3 - s1 * c2 * s3,
            c1 * c2 * s3 + s1 * s2 * c3,
            c1 * c2 * c3 - s1 * s2 * s3]
    return [round(v, 9) + 0.0 for v in quat]


def _texture_png(material):
    texture = material["texture"]
    size = texture.get("size", 128)
    colour = _hex(material.get("color", "#cccccc"))
    alt = _hex(texture.get("color2", "#333333"))
    if texture["pattern"] == "checker":
        return encoders.png(size, size, colour, checker=max(1, size // 8), border=False, alt=alt)
    # stripes: a checker one cell tall is a horizontal stripe per row pair
    cell = max(1, size // 8)
    rows = []
    for y in range(size):
        pixel = bytes((*(colour if (y // cell) % 2 == 0 else alt), 255))
        rows.append(b"\x00" + pixel * size)
    header = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + encoders._chunk(b"IHDR", header)
            + encoders._chunk(b"IDAT", zlib.compress(b"".join(rows), 9))
            + encoders._chunk(b"IEND", b""))


def _lod_ratios(lods):
    if isinstance(lods, int) and not isinstance(lods, bool):
        return [round(0.5 ** (n + 1), 6) for n in range(lods)]
    return list(lods or [])


def resolve(spec, asset_id):
    """(resolved spec for the build script, {texture file name: PNG bytes}).

    Raises ModelSpecError when the spec is invalid or not buildable."""
    problems = validate(spec)
    if problems:
        raise ModelSpecError("; ".join(problems))
    if not buildable(spec):
        raise ModelSpecError("the model spec has no parts to build")

    textures = {}
    materials = []
    for material in spec.get("materials") or []:
        entry = {
            "id": material["id"],
            "color": _linear(material.get("color", "#cccccc")) + [float(material.get("opacity", 1))],
            "metallic": float(material.get("metallic", 0)),
            "roughness": float(material.get("roughness", 0.8)),
            "emissive": _linear(material.get("emissive", "#000000")),
            "emissive_strength": float(material.get("emissive_strength", 1)),
        }
        if material.get("texture"):
            name = f"{asset_id}-{material['id']}.png"
            textures[name] = _texture_png(material)
            entry["texture"] = {"file": name, "repeat": float(material["texture"].get("repeat", 1))}
            # The texture carries the colour; the factor must not tint it twice.
            entry["color"] = [1.0, 1.0, 1.0, entry["color"][3]]
        materials.append(entry)

    expanded = expand_parts(spec["parts"])
    by_id = {p["id"]: p for p in expanded}
    ordered, placed = [], set()

    def place(part):
        if part["id"] in placed:
            return
        if part.get("parent"):
            place(by_id[part["parent"]])
        placed.add(part["id"])
        ordered.append(part)

    for part in expanded:
        place(part)

    parts = [{
        "id": p["id"],
        "shape": p["shape"],
        "size": [float(v) for v in p.get("size", [1, 1, 1])],
        "segments": int(p.get("segments", 16)),
        "translation": [float(v) for v in p.get("position", [0, 0, 0])],
        "rotation": euler_to_quaternion(p.get("rotation", [0, 0, 0])),
        "parent": p.get("parent"),
        "material": p.get("material"),
        "smooth": bool(p.get("smooth", p["shape"] in SMOOTH_SHAPES)),
        # Only when set, so a spec without them resolves exactly as before these existed.
        **({"taper": [float(v) for v in p["taper"]]} if "taper" in p else {}),
        **({"bevel": float(p["bevel"])} if "bevel" in p else {}),
        **({"outline": [[float(a), float(b)] for a, b in p["outline"]]}
           if "outline" in p else {}),
        **({"profile": [[float(a), float(b)] for a, b in p["profile"]]}
           if "profile" in p else {}),
    } for p in ordered]

    animations = []
    for clip in spec.get("animations") or []:
        if not clip.get("tracks"):
            continue
        tracks = []
        for track in clip["tracks"]:
            values = [k["value"] for k in track["keys"]]
            if track["path"] == "rotation":
                values = [euler_to_quaternion(v) for v in values]
            times = [float(k["t"]) for k in track["keys"]]
            values = [[float(x) for x in v] for v in values]
            # Hold the first and last value to the clip's ends: a glTF clip lasts until its
            # last key, so without this `duration` would be whatever the longest track says.
            if times[0] > 0:
                times, values = [0.0] + times, [values[0]] + values
            if times[-1] < clip["duration"]:
                times, values = times + [float(clip["duration"])], values + [values[-1]]
            tracks.append({"part": track["part"], "path": track["path"],
                           "times": times, "values": values})
        animations.append({"name": clip["name"], "duration": float(clip["duration"]),
                           "interpolation": clip.get("interpolation", "linear"),
                           "tracks": tracks})

    fit = spec.get("fit")
    resolved = {
        "format": 1,
        "asset_id": asset_id,
        "fps": int(spec.get("fps", 30)),
        "pivot": spec.get("pivot", "base-center"),
        "fit": ({"size": float(fit["size"]), "axis": fit.get("axis", "max")} if fit else None),
        "materials": materials,
        "parts": parts,
        "animations": animations,
        "lods": _lod_ratios(spec.get("lods")),
        "collision": ({"shape": spec["collision"]["shape"]} if spec.get("collision") else None),
    }
    return resolved, textures


def expectations(spec, kind_policy=None):
    """What a delivered GLB must show, from a spec (buildable or not) and the kind's policy.

    {clips: {name: duration or None}, lods: int or None, collision: shape or None,
     fit: {size, axis} or None, pivot, max_triangles, max_texture_edge,
     budget_declared: {key: bool}, nodes: [name or family*], materials: [name]}

    `nodes` and `materials` are the spec's `contract`: the names game code looks up."""
    spec = spec if isinstance(spec, dict) else {}
    budget = spec.get("budget") or {}
    contract = spec.get("contract") if isinstance(spec.get("contract"), dict) else {}
    clips = {}
    for clip in spec.get("animations") or []:
        if isinstance(clip, dict) and clip.get("name"):
            clips[clip["name"]] = clip.get("duration")
    lods = spec.get("lods")
    lod_count = (lods if isinstance(lods, int) and not isinstance(lods, bool)
                 else len(lods) if isinstance(lods, list) else None)
    policy_triangles = getattr(kind_policy, "max_triangles", None)
    policy_edge = getattr(kind_policy, "max_texture_edge", None)
    return {
        "clips": clips,
        "lods": lod_count or None,
        "collision": (spec.get("collision") or {}).get("shape"),
        "fit": spec.get("fit"),
        "pivot": spec.get("pivot") if "pivot" in spec else ("base-center" if buildable(spec)
                                                            else None),
        "max_triangles": budget.get("max_triangles") or policy_triangles,
        "max_texture_edge": budget.get("max_texture_edge") or policy_edge,
        "max_bytes": budget.get("max_bytes"),
        "budget_declared": {k: k in budget for k in ("max_triangles", "max_texture_edge",
                                                     "max_bytes")},
        "nodes": [n for n in contract.get("nodes") or [] if isinstance(n, str) and n],
        "materials": [m for m in contract.get("materials") or [] if isinstance(m, str) and m],
    }

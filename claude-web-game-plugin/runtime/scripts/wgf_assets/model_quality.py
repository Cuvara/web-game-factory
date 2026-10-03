"""Is a GLB a model, or a primitive standing in for one? Measured from the file, no Blender.

`gltf.inspect` says whether a GLB loads and what it holds. This says whether it is production
art: how many pieces it is made of, whether each piece is an unmodified box, sphere,
cylinder, cone, capsule or plane, whether it has normals and a colour of the game's palette,
and - from those and the requirement's role - a verdict. The result is the asset-manifest
item's `quality` block (core/artifacts/asset-manifest.schema.json); the bars are the `models`
section of core/reference/asset-quality.yaml.

    quality = assess(data, role="player", visual_identity=design_look, spec=model_spec)
    quality["quality"]          {verdict, checks, primitive_only, parts, triangles, colors, author}
    quality["geometry"]         the pieces, each with the primitive it matched (or None)

How a primitive is recognised. The visual model (LOD0, collision proxies excluded, as
`gltf.inspect` counts it) is split into connected pieces - triangles sharing a vertex
position, so UV seams do not split a piece - per mesh instance, in the mesh's own axes.
Each piece is normalised to its bounding box and tested against the surfaces of the
primitives, every vertex within `shape_tolerance` of the piece's size:

    box        8 distinct positions, every one a corner of the bounding box
    plane      flat on one axis, 4 distinct positions at the corners
    sphere     every vertex on the ellipsoid inscribed in the box (UV and ico spheres)
    cylinder   along one axis, vertices only at its two ends, each on the inscribed ellipse
    cone       the same, with one end a single apex
    capsule    a cylinder wall between two hemispheres, along the longest axis

A bevel, a taper, a dent - any modelling - matches none of them. `primitive_only` is true when
every piece matched and they are not composed: fewer than `min_composed_parts` pieces, or
fewer than `min_distinct_pieces` different (shape, proportions). A keeper of a torso, head,
arms, gloves and legs is composed of primitives; one cube, or three equal cubes, is not.

Standard library only.
"""

import math
import os
import re
import struct

from wgflib import paths, yamllite

from . import gltf, modelspec

__all__ = ["QUALITY_PATH", "DEFAULT_BARS", "load_bars", "analyse", "classify",
           "primitive_only", "round_body", "assess", "palette_colours"]

QUALITY_PATH = os.path.join(paths.REFERENCE, "asset-quality.yaml")
DEFAULT_BARS = {
    "readable_roles": ["player", "threat", "goal", "target", "projectile", "collectible",
                       "hazard"],
    "shape_tolerance": 0.02,
    "min_composed_parts": 3,
    "min_distinct_pieces": 2,
    "require_normals": True,
    "palette_distance": 48,
    "silhouette_roles": ["player", "threat"],
    "max_dominance": 0.6,
    "round_body": {"words": ["ball", "marble", "sphere", "orb", "bubble", "globe", "planet"],
                   "min_fill": 0.62, "max_fill": 0.86, "max_aspect": 1.18, "min_parts": 2,
                   "visible_reach": 0.9, "min_shown": 0.1, "min_shown_views": 2},
    "min_contrast_share": {"player": 0.5, "collectible": 0.4, "threat": 0.25, "hazard": 0.25},
}
_COMPONENT = {5120: ("b", 1), 5121: ("B", 1), 5122: ("h", 2), 5123: ("H", 2),
              5125: ("I", 4), 5126: ("f", 4)}
_TYPE = gltf.TYPE_COUNT


def load_bars(path=None):
    """The `models` bars of core/reference/asset-quality.yaml, over the defaults."""
    bars = dict(DEFAULT_BARS)
    path = path or QUALITY_PATH
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as handle:
            document = yamllite.load(handle.read()) or {}
        bars.update((document.get("models") or {}))
    return bars


# -- reading the geometry -------------------------------------------------------------------

def _read(doc, binary, index):
    """An accessor's elements as tuples, or None when it cannot be read as plain numbers
    (sparse, normalised integers, an external buffer)."""
    accessor = doc["accessors"][index]
    if "sparse" in accessor or "bufferView" not in accessor or binary is None:
        return None
    if accessor.get("componentType") not in _COMPONENT or accessor.get("type") not in _TYPE:
        return None
    if accessor.get("normalized"):
        return None
    view = doc["bufferViews"][accessor["bufferView"]]
    if view.get("buffer") != 0:
        return None
    code, size = _COMPONENT[accessor["componentType"]]
    width = _TYPE[accessor["type"]]
    stride = view.get("byteStride") or size * width
    start = (view.get("byteOffset") or 0) + (accessor.get("byteOffset") or 0)
    fmt = "<" + code * width
    count = accessor.get("count", 0)
    if start + stride * max(0, count - 1) + size * width > len(binary):
        return None
    return [struct.unpack_from(fmt, binary, start + i * stride) for i in range(count)]


def _triangles(prim, count, indices):
    mode = prim.get("mode", 4)
    order = indices if indices is not None else list(range(count))
    if mode == 4:
        return [tuple(order[i:i + 3]) for i in range(0, len(order) - 2, 3)]
    if mode == 5:
        return [(order[i], order[i + 1], order[i + 2]) if i % 2 == 0
                else (order[i + 1], order[i], order[i + 2]) for i in range(len(order) - 2)]
    if mode == 6:
        return [(order[0], order[i], order[i + 1]) for i in range(1, len(order) - 1)]
    return []


def _pieces(positions, triangles):
    """Connected pieces: (distinct positions, triangle count, the triangles), joined through
    shared triangles. Positions are welded by value, so a UV or normal seam does not split a
    piece."""
    key_of = [tuple(round(c, 5) for c in p) for p in positions]
    parent = {}

    def find(k):
        root = k
        while parent.get(root, root) != root:
            root = parent[root]
        while parent.get(k, k) != root:
            parent[k], k = root, parent[k]
        return root

    for tri in triangles:
        if any(i >= len(key_of) for i in tri):
            continue
        a = find(key_of[tri[0]])
        for i in tri[1:]:
            b = find(key_of[i])
            if a != b:
                parent[b] = a
    groups, faces = {}, {}
    for tri in triangles:
        if any(i >= len(key_of) for i in tri):
            continue
        root = find(key_of[tri[0]])
        faces.setdefault(root, []).append(tri)
        for i in tri:
            groups.setdefault(root, set()).add(key_of[i])
    return [(sorted(groups[r]), len(faces[r]), faces[r]) for r in sorted(groups)]


def _near(value, target, tol):
    return abs(value - target) <= tol


def classify(points, tolerance=0.02):
    """The primitive `points` (distinct positions of one piece) lie on, or None."""
    if len(points) < 4:
        return None
    lo = [min(p[k] for p in points) for k in range(3)]
    hi = [max(p[k] for p in points) for k in range(3)]
    ext = [hi[k] - lo[k] for k in range(3)]
    largest = max(ext)
    if largest <= 1e-9:
        return None
    centre = [(hi[k] + lo[k]) / 2 for k in range(3)]
    flat = [k for k in range(3) if ext[k] <= largest * 1e-4]
    tol = tolerance

    def corner(p, axes):
        return all(_near(p[k], lo[k], tol * ext[k]) or _near(p[k], hi[k], tol * ext[k])
                   for k in axes)

    if len(flat) == 1:
        axes = [k for k in range(3) if k not in flat]
        return "plane" if len(points) == 4 and all(corner(p, axes) for p in points) else None
    if flat:
        return None
    if len(points) == 8 and all(corner(p, range(3)) for p in points):
        return "box"
    # Normalised to the unit ball's box: [-1, 1] on each axis.
    unit = [tuple((p[k] - centre[k]) * 2 / ext[k] for k in range(3)) for p in points]
    if len(points) >= 6 and all(_near(math.sqrt(sum(c * c for c in u)), 1, 2 * tol)
                                for u in unit):
        return "sphere"
    for axis in range(3):
        others = [k for k in range(3) if k != axis]
        ends = {}
        ok = True
        for u in unit:
            if _near(u[axis], -1, 2 * tol):
                end = -1
            elif _near(u[axis], 1, 2 * tol):
                end = 1
            else:
                ok = False
                break
            radius = math.sqrt(sum(u[k] * u[k] for k in others))
            if _near(radius, 1, 2 * tol):
                ends.setdefault(end, set()).add("ring")
            elif _near(radius, 0, 2 * tol):
                ends.setdefault(end, set()).add("centre")
            else:
                ok = False
                break
        if not ok or len(ends) != 2:
            continue
        rings = [end for end, kinds in ends.items() if "ring" in kinds]
        if len(rings) == 2:
            return "cylinder"
        if len(rings) == 1:
            return "cone"
    # A capsule along its longest axis: cross-section radius 1 after normalising the other
    # two axes; the caps' radius is the smaller of theirs, which sets the axis's scale.
    axis = max(range(3), key=lambda k: ext[k])
    others = [k for k in range(3) if k != axis]
    cap = min(ext[k] for k in others) / 2
    if cap <= 0:
        return None
    half = ext[axis] / 2 / cap
    if half < 1 + tol:
        return None
    wall = half - 1
    sides = set()
    for p, u in zip(points, unit):
        t = (p[axis] - centre[axis]) / cap
        radial = [u[k] for k in others]
        sides.add(t > 0)
        if abs(t) <= wall + 2 * tol:
            if _near(math.sqrt(sum(r * r for r in radial)), 1, 2 * tol):
                continue
        # On a cap: the hemisphere around the wall's end, radial axes scaled by their own
        # extent, the axis by the cap radius.
        dz = abs(t) - wall
        if dz < -2 * tol or not _near(math.sqrt(sum(r * r for r in radial) + dz * dz), 1,
                                      3 * tol):
            return None
    return "capsule" if len(sides) == 2 else None


def analyse(data, *, tolerance=0.02, name="model"):
    """The visual model's pieces, mesh instances, normals and materials; None when the file
    cannot be read or its geometry cannot be decoded (compressed, quantised)."""
    try:
        doc, binary = gltf.load(data)
    except gltf.GltfError:
        return None
    nodes = doc.get("nodes") or []
    scenes = doc.get("scenes") or []
    scene = doc.get("scene", 0)
    if not scenes or not 0 <= scene < len(scenes):
        return None
    meshes = doc.get("meshes") or []
    materials = doc.get("materials") or []
    pieces, mesh_nodes, used_materials = [], 0, set()
    normals = True
    decoded = True
    # The roles as gltf.inspect assigns them: a collision subtree, a LOD level, or neither.
    stack = [(r, (None, None), gltf.IDENTITY)
             for r in reversed(scenes[scene].get("nodes") or [])]
    seen = set()
    world = []  # the visual model's triangles in model space, for the silhouette
    faces = []  # the same triangles by piece, for what each piece shows (round_body)
    surface = {}  # material index (-1: none) -> visible surface area, for the contrast
    while stack:
        index, inherited, parent_matrix = stack.pop()
        if index in seen or not 0 <= index < len(nodes):
            return None
        seen.add(index)
        node = nodes[index]
        own = gltf._role(node)
        role = own if own[0] == "collision" or (own[0] == "lod"
                                                and inherited[0] != "collision") else inherited
        matrix = gltf._multiply(parent_matrix, gltf._trs(node))
        for child in reversed(node.get("children") or []):
            stack.append((child, role, matrix))
        visual = role[0] is None or (role[0] == "lod" and not role[1])
        if not visual or "mesh" not in node or not 0 <= node["mesh"] < len(meshes):
            continue
        mesh_nodes += 1
        for prim in meshes[node["mesh"]].get("primitives") or []:
            attributes = prim.get("attributes") or {}
            if "NORMAL" not in attributes:
                normals = False
            if isinstance(prim.get("material"), int):
                used_materials.add(prim["material"])
            positions = _read(doc, binary, attributes["POSITION"]) \
                if "POSITION" in attributes else None
            indices = _read(doc, binary, prim["indices"]) if "indices" in prim else None
            if positions is None or ("indices" in prim and indices is None):
                decoded = False
                continue
            flat_indices = [i[0] for i in indices] if indices is not None else None
            prim_triangles = _triangles(prim, len(positions), flat_indices)
            placed = [gltf._apply(matrix, p) for p in positions]
            material = prim.get("material") if isinstance(prim.get("material"), int) else -1
            surface[material] = surface.get(material, 0.0) + sum(
                _area(*(placed[i] for i in tri)) for tri in prim_triangles
                if all(i < len(placed) for i in tri))
            world.extend((index, tuple(placed[i] for i in tri)) for tri in prim_triangles
                         if all(i < len(placed) for i in tri))
            for points, triangles, own in _pieces(positions, prim_triangles):
                lo = [min(p[k] for p in points) for k in range(3)]
                hi = [max(p[k] for p in points) for k in range(3)]
                faces.extend((len(pieces), tuple(placed[i] for i in tri)) for tri in own)
                pieces.append({"node": node.get("name") or f"nodes[{index}]",
                               "shape": classify(points, tolerance),
                               "vertices": len(points), "triangles": triangles,
                               "dimensions": [round(hi[k] - lo[k], 4) + 0.0 for k in range(3)],
                               "_placed": [gltf._apply(matrix, p) for p in points]})
    colours = []
    for i in sorted(used_materials):
        if i >= len(materials):
            continue
        pbr = materials[i].get("pbrMetallicRoughness") or {}
        factor = pbr.get("baseColorFactor") or [1, 1, 1, 1]
        emissive = list(materials[i].get("emissiveFactor") or [0, 0, 0])[:3]
        strength = ((materials[i].get("extensions") or {}).get(
            "KHR_materials_emissive_strength") or {}).get("emissiveStrength", 1.0)
        colours.append({"name": materials[i].get("name") or f"material-{i}",
                        "color": _srgb_hex(factor[:3]),
                        "emissive": _srgb_hex([min(1.0, c * float(strength))
                                               for c in emissive]),
                        "area": round(surface.get(i, 0.0), 6),
                        "textured": isinstance(pbr.get("baseColorTexture"), dict)})
    _reach(pieces)
    if decoded:
        _shown(pieces, faces)
    return {"pieces": pieces, "mesh_nodes": mesh_nodes, "normals": normals and mesh_nodes > 0,
            "decoded": decoded, "materials": colours,
            "silhouette": silhouette(world) if decoded and world else None}


def _reach(pieces):
    """Each piece's `reach`: its farthest vertex from the centre of the whole model's
    bounding box, in model space - a part of a ball that never reaches its surface is hidden
    inside it (round_body)."""
    placed = [p.pop("_placed") for p in pieces]
    points = [q for group in placed for q in group]
    if not points:
        return
    centre = [(min(q[k] for q in points) + max(q[k] for q in points)) / 2.0 for k in range(3)]
    for piece, group in zip(pieces, placed):
        piece["reach"] = round(max(math.dist(q, centre) for q in group), 4) if group else 0.0


def _shown(pieces, faces, grid=None):
    """Each piece's `shown`: per silhouette view, the share of the outline where that piece
    is the nearest surface to the camera - from the view's front or its back, the larger -
    or None for an edge-on view. A depth buffer on the outline grid, sampled at cell centres:
    a band sunk inside a shell is behind it in every cell, a speck on the surface covers a
    few (round_body)."""
    grid = grid or SILHOUETTE_GRID
    for piece in pieces:
        piece["shown"] = {name: None for name, _u, _v in SILHOUETTE_VIEWS}
    if not faces:
        return
    for name, u_axis, v_axis in SILHOUETTE_VIEWS:
        d_axis = 3 - u_axis - v_axis
        us = [p[u_axis] for _i, tri in faces for p in tri]
        vs = [p[v_axis] for _i, tri in faces for p in tri]
        lo_u, lo_v = min(us), min(vs)
        extent_u, extent_v = max(us) - lo_u, max(vs) - lo_v
        longest = max(extent_u, extent_v)
        if longest <= 1e-9 or min(extent_u, extent_v) < longest * _FLAT_VIEW:
            continue
        cell = longest / grid
        width = max(1, min(grid, int(math.ceil(extent_u / cell - 1e-9))))
        height = max(1, min(grid, int(math.ceil(extent_v / cell - 1e-9))))
        near, far = {}, {}
        for index, tri in faces:
            flat = [((p[u_axis] - lo_u) / cell, (p[v_axis] - lo_v) / cell, p[d_axis])
                    for p in tri]
            (ax, ay, ad), (bx, by, bd), (cx, cy, cd) = flat
            det = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
            if abs(det) <= 1e-12:
                continue        # edge-on in this view: its neighbours cover what it would
            first = max(0, int(math.floor(min(ax, bx, cx) - 0.5)))
            last = min(width - 1, int(math.ceil(max(ax, bx, cx) - 0.5)))
            low = max(0, int(math.floor(min(ay, by, cy) - 0.5)))
            high = min(height - 1, int(math.ceil(max(ay, by, cy) - 0.5)))
            for row in range(low, high + 1):
                y = row + 0.5
                for col in range(first, last + 1):
                    x = col + 0.5
                    w0 = ((by - cy) * (x - cx) + (cx - bx) * (y - cy)) / det
                    w1 = ((cy - ay) * (x - cx) + (ax - cx) * (y - cy)) / det
                    w2 = 1.0 - w0 - w1
                    if w0 < -1e-9 or w1 < -1e-9 or w2 < -1e-9:
                        continue
                    depth = w0 * ad + w1 * bd + w2 * cd
                    key = row * width + col
                    if key not in near or depth < near[key][0]:
                        near[key] = (depth, index)
                    if key not in far or depth > far[key][0]:
                        far[key] = (depth, index)
        if not near:
            continue
        counts = [{}, {}]
        for side, buffer in enumerate((near, far)):
            for _depth, index in buffer.values():
                counts[side][index] = counts[side].get(index, 0) + 1
        for index, piece in enumerate(pieces):
            piece["shown"][name] = round(max(c.get(index, 0) for c in counts)
                                         / float(len(near)), 3)


def _area(a, b, c):
    u = [b[k] - a[k] for k in range(3)]
    v = [c[k] - a[k] for k in range(3)]
    cross = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])
    return 0.5 * math.sqrt(sum(x * x for x in cross))


def _luminance(hex_colour):
    """WCAG relative luminance of an sRGB hex colour."""
    def channel(c):
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (channel(x / 255.0) for x in _rgb(hex_colour))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(a, b):
    la, lb = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def background_colour(visual_identity):
    """The colour the game draws its scene on: the palette entry whose token or role names
    the background or ground, else the darkest."""
    palette = [e for e in (visual_identity or {}).get("palette") or [] if isinstance(e, dict)
               and isinstance(e.get("hex"), str) and len(e["hex"]) == 7]
    for entry in palette:
        words = f"{entry.get('token', '')} {entry.get('role', '')}".lower()
        if any(w in words for w in ("background", "ground", "backdrop", "sky")):
            return entry["hex"]
    return min((e["hex"] for e in palette), key=_luminance, default=None)


def contrast_share(materials, background):
    """The share of the visible surface whose colour - base or emissive, the brighter -
    stands off `background` by at least 3:1; None when there is no surface to measure."""
    total = sum(m.get("area") or 0.0 for m in materials if not m.get("textured"))
    if not total or not background:
        return None
    standing = 0.0
    for m in materials:
        if m.get("textured"):
            continue
        best = max(contrast_ratio(m["color"], background),
                   contrast_ratio(m.get("emissive") or "#000000", background)
                   if (m.get("emissive") or "#000000") != "#000000" else 1.0)
        if best >= 3.0:
            standing += m.get("area") or 0.0
    return standing / total


# -- the silhouette ---------------------------------------------------------------------------

# The three orthographic views a silhouette is read from, as the two model-space axes each
# projects onto (glTF: x right, y up, z the model's front).
SILHOUETTE_VIEWS = (("front", 0, 1), ("side", 2, 1), ("top", 0, 2))
SILHOUETTE_GRID = 64
# A view in which the model is this flat (its shorter projected side under this fraction of
# the longer) shows an edge, not a silhouette - a floor tile from the front - and is skipped.
_FLAT_VIEW = 0.03


def _band_span(tri, row):
    """[lo, hi] of the triangle `tri` (2D, cell units) clipped to the band row <= v <= row+1,
    or None: a conservative cover of the row - a sliver thinner than a cell still counts."""
    poly = list(tri)
    for bound, keep_above in ((row, True), (row + 1, False)):
        out = []
        for i, a in enumerate(poly):
            b = poly[(i + 1) % len(poly)]
            a_in = a[1] >= bound if keep_above else a[1] <= bound
            b_in = b[1] >= bound if keep_above else b[1] <= bound
            if a_in:
                out.append(a)
            if a_in != b_in and a[1] != b[1]:
                t = (bound - a[1]) / (b[1] - a[1])
                out.append((a[0] + t * (b[0] - a[0]), bound))
        poly = out
        if not poly:
            return None
    xs = [p[0] for p in poly]
    return min(xs), max(xs)


def _view_masks(triangles, u_axis, v_axis, grid):
    """(width, height, {node: set of covered cells}) of the outline projected onto the two
    axes, on a grid whose longer side has `grid` square cells; None when edge-on."""
    us = [p[u_axis] for _node, tri in triangles for p in tri]
    vs = [p[v_axis] for _node, tri in triangles for p in tri]
    lo_u, lo_v = min(us), min(vs)
    extent_u, extent_v = max(us) - lo_u, max(vs) - lo_v
    longest = max(extent_u, extent_v)
    if longest <= 1e-9 or min(extent_u, extent_v) < longest * _FLAT_VIEW:
        return None
    cell = longest / grid
    width = max(1, min(grid, int(math.ceil(extent_u / cell - 1e-9))))
    height = max(1, min(grid, int(math.ceil(extent_v / cell - 1e-9))))
    masks = {}
    for node, tri in triangles:
        mask = masks.setdefault(node, set())
        flat = [((p[u_axis] - lo_u) / cell, (p[v_axis] - lo_v) / cell) for p in tri]
        low = max(0, int(math.floor(min(p[1] for p in flat))))
        high = min(height - 1, int(math.floor(max(p[1] for p in flat))))
        for row in range(low, high + 1):
            span = _band_span(flat, row)
            if span is None:
                continue
            first = max(0, int(math.floor(span[0])))
            last = min(width - 1, int(math.floor(span[1])))
            mask.update(range(row * width + first, row * width + last + 1))
    return width, height, masks


def _largest_rectangle(cells, width, height):
    """Cells in the largest all-covered axis-aligned rectangle (histogram method)."""
    best = 0
    heights = [0] * width
    for row in range(height):
        base = row * width
        heights = [h + 1 if base + i in cells else 0 for i, h in enumerate(heights)]
        stack = []
        for i, h in enumerate(heights + [0]):
            start = i
            while stack and stack[-1][1] >= h:
                start, top = stack.pop()
                best = max(best, top * (i - start))
            stack.append((start, h))
    return best


def silhouette(triangles, grid=SILHOUETTE_GRID):
    """The model's outline seen from the front, the side and the top, measured per view
    (each 0..1):

        fill       the outline's share of its bounding rectangle
        aspect     that rectangle's longer side over its shorter (1 or more)
        block      the largest rectangle inside the outline, over the outline
        part       the largest single part's outline, over the outline
        dominance  `part` when the model has several parts; `block` when it is one mesh (a
                   modelled mesh from another tool, whose parts are not nodes)

    `triangles` are (node, (p0, p1, p2)) in model space. A box with bumps - one hull with
    small parts that stay inside its outline - is dominated by one component in every view;
    a ship whose wings, tail and engines stand out, a figure with arms and legs, a rock
    cluster, is not in at least one. {views: {front, side, top: {...} or None}, dominance,
    view}: the most distinctive view's dominance (the smallest), and which view that is."""
    several = len({node for node, _tri in triangles}) > 1
    views = {}
    for name, u_axis, v_axis in SILHOUETTE_VIEWS:
        measured = _view_masks(triangles, u_axis, v_axis, grid) if triangles else None
        if measured is None:
            views[name] = None
            continue
        width, height, masks = measured
        union = set().union(*masks.values())
        if not union:
            views[name] = None
            continue
        measures = {
            "fill": round(len(union) / float(width * height), 3),
            "aspect": round(max(width, height) / float(min(width, height)), 3),
            "block": round(_largest_rectangle(union, width, height) / float(len(union)), 3),
            "part": round(max(len(m) for m in masks.values()) / float(len(union)), 3),
        }
        measures["dominance"] = measures["part" if several else "block"]
        views[name] = measures
    judged = {k: v["dominance"] for k, v in views.items() if v is not None}
    if not judged:
        return {"views": views, "dominance": None, "view": None, "grid": grid}
    view = min(judged, key=lambda k: (judged[k], k))
    return {"views": views, "dominance": judged[view], "view": view, "grid": grid}


def _srgb_hex(linear):
    out = []
    for c in linear:
        c = min(1.0, max(0.0, float(c)))
        s = c * 12.92 if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055
        out.append(int(round(s * 255)))
    return "#" + "".join(f"{v:02x}" for v in out)


def _rgb(hex_colour):
    value = hex_colour.lstrip("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def palette_colours(visual_identity):
    """The palette's hex colours, from a visual_identity (palette [{token, hex, role}]) or a
    plain list of hex strings."""
    palette = visual_identity.get("palette") if isinstance(visual_identity, dict) \
        else visual_identity
    out = []
    for entry in palette or []:
        value = entry.get("hex") if isinstance(entry, dict) else entry
        if isinstance(value, str) and len(value) == 7 and value.startswith("#"):
            out.append(value.lower())
    return out


def primitive_only(pieces, bars=None):
    """True when every piece is an unmodified primitive and they are not composed; None when
    there is nothing to judge."""
    bars = bars or DEFAULT_BARS
    if not pieces:
        return None
    if any(p["shape"] is None for p in pieces):
        return False
    largest = max(max(p["dimensions"]) for p in pieces) or 1.0
    signatures = {(p["shape"], tuple(sorted(round(d / largest, 2) for d in p["dimensions"])))
                  for p in pieces}
    composed = (len(pieces) >= int(bars.get("min_composed_parts", 3))
                and len(signatures) >= int(bars.get("min_distinct_pieces", 2)))
    return not composed


def _requirement_text(requirement):
    if requirement is None:
        return ""
    get = requirement.get if isinstance(requirement, dict) \
        else (lambda key: getattr(requirement, key, None))
    return " ".join(str(get(key)) for key in ("description", "readability", "spec")
                    if isinstance(get(key), str))


def round_body(requirement, pieces, outline, bars=None):
    """(word, reason) when the model is a round body (asset-quality.yaml `models.round_body`):
    its requirement names one, its outline is a disk in all three views and it is composed or
    modelled; (None, why not) otherwise. Every condition is required."""
    bars = bars or DEFAULT_BARS
    rule = bars.get("round_body") if isinstance(bars.get("round_body"), dict) else None
    if not rule:
        return None, "no round_body rule"
    text = _requirement_text(requirement).lower()
    word = next((w for w in rule.get("words") or []
                 if re.search(r"(?<![a-z0-9])" + re.escape(str(w).lower()) + r"(e?s)?(?![a-z0-9])",
                              text)), None)
    if word is None:
        return None, "the requirement names no round body"
    named = f"the requirement names a {word}, but"
    views = (outline or {}).get("views") or {}
    lo, hi = float(rule.get("min_fill", 0.7)), float(rule.get("max_fill", 0.86))
    longest = float(rule.get("max_aspect", 1.18))
    measured = [v for v in views.values() if v is not None]
    if len(measured) < 3 or len(views) < 3:
        return None, f"{named} the outline is not measured in all three views"
    off = [f"{name} (fill {float(v.get('fill', 0)):.2f}, aspect {float(v.get('aspect', 99)):.2f})"
           for name, v in sorted(views.items())
           if not (lo <= float(v.get("fill", 0)) <= hi and float(v.get("aspect", 99)) <= longest)]
    if off:
        return None, (f"{named} its outline is not a disk in the {', '.join(off)} view(s); a "
                      f"round body's outline fills {lo:g}-{hi:g} of its rectangle and is at "
                      f"most {longest:g} to 1 in every view: keep it round - every part inside "
                      f"the ball's disk, nothing widening or stretching it")
    if not pieces:
        return None, f"{named} it has no pieces"
    # Only a piece that reaches the ball's surface shows: a band or core sunk inside the shell
    # composes nothing a player sees.
    outer = max(float(p.get("reach", 0.0)) for p in pieces) or 1.0
    share = float(rule.get("visible_reach", 0.9))
    visible = [p for p in pieces if float(p.get("reach", outer)) >= share * outer]
    largest = max(max(p["dimensions"]) for p in visible) or 1.0
    signatures = {(p["shape"], tuple(sorted(round(d / largest, 2) for d in p["dimensions"])))
                  for p in visible}
    need = int(rule.get("min_parts", 2))
    if len(visible) < need or len(signatures) < 2:
        hidden = len(pieces) - len(visible)
        return None, (f"{named} " + (f"{hidden} of its {len(pieces)} pieces are hidden inside "
                                     f"it (reaching under {share:g} of its radius) and "
                                     if hidden else "")
                      + f"a lone shell (or copies of one piece) is what shows: compose it of at "
                        f"least {need} different pieces on its surface - a shell and a swirl "
                        f"band, a core showing through a rim")
    # Reaching the surface is not showing on it: two specks on a plain shell reach it too.
    # A second piece must be the nearest surface over a real share of the outline.
    least = float(rule.get("min_shown", 0.1))
    views_needed = int(rule.get("min_shown_views", 2))
    shows = ""
    if any(isinstance(p.get("shown"), dict) for p in pieces):
        def share_in(p, name):
            return float((p.get("shown") or {}).get(name) or 0.0)

        def signature(p):
            return p["shape"], tuple(sorted(round(d / largest, 2) for d in p["dimensions"]))

        names = sorted(views)
        shell = max(visible, key=lambda p: sum(share_in(p, n) for n in names))
        others = [p for p in visible if p is not shell and signature(p) != signature(shell)]
        best = max(others, default=None, key=lambda p: (
            sum(share_in(p, n) >= least for n in names), sum(share_in(p, n) for n in names)))
        showing = [n for n in names if best is not None and share_in(best, n) >= least]
        if len(showing) < views_needed:
            lacking = [f"{n} ({share_in(best, n) if best is not None else 0.0:.0%})"
                       for n in names if n not in showing]
            return None, (f"{named} only its shell shows: no second piece covers {least:.0%} "
                          f"of the outline in {views_needed} of the three views - the "
                          f"{', '.join(lacking)} view(s) show no second piece (its share of "
                          f"the outline in brackets). Put the band or swirl ON the surface, "
                          f"raised above the shell and in a contrasting colour - not sunk "
                          f"inside it, not shrunk to specks")
        shows = (f", the {best['node']} piece covering "
                 + ", ".join(f"{share_in(best, n):.0%} of the {n}" for n in showing)
                 + " outline")
    fills = [float(v["fill"]) for v in measured]
    return word, (f"a round body: the requirement names a {word}, its outline is a disk in "
                  f"every view (fill {min(fills):.2f}-{max(fills):.2f}) and {len(visible)} "
                  f"different pieces show on its surface{shows} (asset-quality.yaml "
                  f"models.round_body)")


# -- the verdict ----------------------------------------------------------------------------

def assess(data, *, role=None, visual_identity=None, spec=None, kind="model", name="model",
           bars=None, policy=None, author=None, inspection=None, requirement=None):
    """{quality, geometry, findings}: the manifest `quality` block for a GLB, the geometry it
    was judged on, and the inspector's and the spec's findings [(code, severity, message)].

    `spec` is the model spec (buildable or an expectation): its declared fit, clips, budget
    and part count are held against the file. `policy` is the asset policy (for the kind's
    budgets; optional). `requirement` is the design's asset requirement (description,
    readability, spec): what tells a round body from a blob (`round_body`)."""
    bars = dict(DEFAULT_BARS, **(bars or load_bars()))
    inspection = inspection or gltf.inspect(data, name=name, kind=kind)
    kind_policy = policy.kind(kind) if policy is not None else None
    findings = list(inspection.findings)
    findings += gltf.check_expectations(inspection.summary,
                                        modelspec.expectations(spec, kind_policy), data,
                                        name=name)
    summary = inspection.summary
    geometry = analyse(data, tolerance=float(bars["shape_tolerance"]), name=name) \
        if summary is not None else None
    checks = []

    def check(check_id, status, text):
        checks.append({"id": check_id, "status": status, "summary": text})

    errors = [f for f in findings if f[1] == "error"]
    check("model.valid", "fail" if errors else "pass",
          f"{len(errors)} error(s): " + "; ".join(m for _c, _s, m in errors[:3]) if errors
          else "loads: structure, references, transforms and declarations hold")

    pieces = (geometry or {}).get("pieces") or []
    mesh_nodes = (geometry or {}).get("mesh_nodes") or 0
    expected_parts = len(modelspec.expand_parts(spec["parts"])) \
        if modelspec.buildable(spec) and not modelspec.validate(spec) else None
    if geometry is None:
        check("model.parts", "fail", "the geometry could not be read")
    elif expected_parts and mesh_nodes < expected_parts:
        check("model.parts", "fail",
              f"{mesh_nodes} mesh node(s); the spec builds {expected_parts} parts")
    else:
        check("model.parts", "pass" if pieces else "fail",
              f"{len(pieces)} piece(s) in {mesh_nodes} mesh node(s)"
              + (f"; the spec builds {expected_parts}" if expected_parts else ""))

    triangles = (summary or {}).get("triangles")
    over = [f for f in findings if f[0] == "model-over-budget" and f[1] == "error"]
    if not triangles:
        check("model.triangles", "fail", "no visible triangles")
    elif over:
        check("model.triangles", "fail", over[0][2])
    else:
        check("model.triangles", "pass", f"{triangles} triangles")

    if geometry is None:
        check("model.normals", "fail", "the geometry could not be read")
    elif geometry["normals"]:
        check("model.normals", "pass", "every visible primitive carries vertex normals")
    else:
        check("model.normals", "fail" if bars.get("require_normals", True) else "pass",
              "a visible primitive has no NORMAL attribute: three.js shades it by guesswork")

    palette = palette_colours(visual_identity or {})
    used = (geometry or {}).get("materials") or []
    if not palette:
        check("model.palette", "skipped", "the design states no palette")
    elif not used:
        check("model.palette", "fail", "no material: the runtime's default grey")
    else:
        limit = float(bars["palette_distance"])
        matched = sorted({m["color"] for m in used
                          if not m["textured"] and any(
                              math.dist(_rgb(m["color"]), _rgb(p)) <= limit for p in palette)})
        if matched:
            check("model.palette", "pass", f"palette colours {', '.join(matched)}")
        elif any(m["textured"] for m in used):
            check("model.palette", "skipped",
                  "textured materials; their colours are not decoded here")
        else:
            check("model.palette", "fail",
                  f"no material colour within {limit:g} of the palette "
                  f"({', '.join(m['color'] for m in used)} vs {', '.join(palette)})")

    dims = (summary or {}).get("dimensions")
    scale = [f for f in findings if f[0] in ("model-scale",) and f[1] == "error"]
    if not dims:
        check("model.bounds", "fail", "no bounding box")
    elif scale:
        check("model.bounds", "fail", scale[0][2])
    else:
        fit = (spec or {}).get("fit") if isinstance(spec, dict) else None
        check("model.bounds", "pass",
              f"{dims} m" + (f", fitted to {fit['size']:g} m along {fit.get('axis', 'max')}"
                             if fit else ""))

    only = primitive_only(pieces, bars) if geometry is not None and geometry["decoded"] \
        else None
    readable = role in (bars.get("readable_roles") or [])
    styled = bool((visual_identity or {}).get("primitive_style")) \
        if isinstance(visual_identity, dict) else False
    shapes = sorted({p["shape"] or "modelled" for p in pieces})
    outline = (geometry or {}).get("silhouette")
    ball, ball_reason = round_body(requirement, pieces, outline, bars) \
        if geometry is not None and geometry["decoded"] else (None, "")
    if ball and only:
        only = False     # composed, by the round-body rule: not a primitive standing in
    if only is None:
        check("model.primitive", "skipped" if geometry is not None else "fail",
              "the geometry could not be decoded (compressed or quantised)"
              if geometry is not None else "the geometry could not be read")
    elif ball:
        check("model.primitive", "pass", f"{len(pieces)} pieces ({', '.join(shapes)}); "
                                         f"{ball_reason}")
    elif not only:
        check("model.primitive", "pass",
              f"{len(pieces)} pieces ({', '.join(shapes)}): modelled or composed")
    elif not readable:
        check("model.primitive", "pass",
              f"primitive only ({', '.join(shapes)}); allowed for role {role or 'unset'}")
    elif styled:
        check("model.primitive", "pass",
              f"primitive only ({', '.join(shapes)}); the visual identity states "
              f"primitive_style")
    else:
        check("model.primitive", "fail",
              f"primitive only ({len(pieces)} piece(s): {', '.join(shapes)}) for the readable "
              f"role {role}: a primitive standing in for a {role} is a placeholder")

    silhouette_roles = bars.get("silhouette_roles") or []
    limit = bars.get("max_dominance")
    if outline is None or outline.get("dominance") is None:
        check("model.silhouette", "skipped",
              "no outline to measure (the geometry is unread, compressed or flat)")
    else:
        share, view = outline["dominance"], outline["view"]
        text = (f"one component covers {share:.0%} of the {view} outline, the most distinctive "
                f"view")
        if role not in silhouette_roles or limit is None:
            check("model.silhouette", "pass", f"{text}; not judged for role {role or 'unset'}")
        elif styled:
            check("model.silhouette", "pass", f"{text}; the visual identity states "
                                              f"primitive_style")
        elif share > float(limit) and ball:
            check("model.silhouette", "pass", f"{text}; {ball_reason}")
        elif share > float(limit) and ball_reason.startswith("the requirement names a"):
            check("model.silhouette", "fail",
                  f"{text}, over {float(limit):.0%}; not passed as a round body: {ball_reason}")
        elif share > float(limit):
            check("model.silhouette", "fail",
                  f"{text}, over {float(limit):.0%}: a box with bumps - the parts a player "
                  f"recognises a {role} by (wings, limbs, fins, engines, a gap) must stand out "
                  f"of the main body's outline in at least one view")
        else:
            check("model.silhouette", "pass", f"{text} (at most {float(limit):.0%})")

    floors = bars.get("min_contrast_share") if isinstance(bars.get("min_contrast_share"),
                                                         dict) else {}
    contrast_roles = list(floors)
    floor = floors.get(role)
    background = background_colour(visual_identity)
    share = contrast_share(used, background) if used else None
    if share is None:
        check("model.contrast", "skipped",
              "no untextured surface or no background colour to measure against")
    else:
        text = (f"{share:.0%} of the visible surface stands off the background {background} "
                f"by 3:1 or more (base or emissive colour)")
        if role not in contrast_roles:
            check("model.contrast", "pass", f"{text}; not judged for role {role or 'unset'}")
        elif share < float(floor):
            check("model.contrast", "fail",
                  f"{text}, under {float(floor):.0%}: a dark model on a dark scene vanishes at "
                  f"gameplay distance - give the body a light or saturated palette colour, or "
                  f"emissive trim that outlines it")
        else:
            check("model.contrast", "pass", f"{text} (at least {float(floor):.0%})")

    verdict ="fail" if any(c["status"] == "fail" for c in checks) else "pass"
    quality = {"verdict": verdict, "checks": checks, "primitive_only": only,
               "parts": len(pieces) if geometry is not None else None,
               "triangles": triangles if summary is not None else None,
               "colors": len({m["color"] for m in used}) if geometry is not None else None}
    if author is not None:
        quality["author"] = author
    return {"quality": quality, "geometry": geometry, "findings": findings,
            "summary": summary}

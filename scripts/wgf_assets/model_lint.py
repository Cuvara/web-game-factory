"""Model craft lint: what a careful modeller never ships, measured from the GLB and its spec.

`model_quality.assess` says whether a GLB is a model at all - composed, normals, palette,
silhouette, contrast. A model can pass all of that and still be badly made: a lantern
hanging in the air beside its arch, a swirl band sunk inside the marble's shell where no
camera ever sees it, two faces of different colours on one plane flickering in the game, a
lantern glowing like a neon sign in a cut-paper world, a gem stretched into a needle. These
are deterministic, so they are measured here, before any judge looks at the renders
(core/reference/model-review-rubric.yaml, `lint`):

    floating    a part (or a group of parts) that touches nothing of the main body: two parts
                touch when the gap between their bounds is at most `min_gap` of the smaller
                one's size
    hidden      a part that is the nearest surface nowhere on the outline, from any of the
                six axis views (front/back, both sides, top/bottom) - inside another part
    coplanar    faces of two parts, of different materials, on one plane, facing the same
                way (not down: an underside) and overlapping: they fight for depth
                (z-fighting) in the game
    emissive    more of the surface glowing, or glowing harder, than the visual identity
                allows: a lit identity (cut paper, clay, toy) against a neon one
    aspect      a role whose model must read compact (a collectible) stretched along one
                axis: longest over middle dimension above the role's limit
    bevel       a chunky box or cylinder (its smallest side `min_size` of the model) with no
                bevel, unless the identity asks for crisp edges
    smooth      smooth shading across too few segments: a blotchy, not a faceted, surface

    findings = lint(geometry, spec=..., role=..., visual_identity=..., rules=load_rules())
    findings = [{"code": "lint.floating", "severity": "error", "message": ..., "parts": [...]}]

`geometry` is `model_quality.analyse(...)` output (its `nodes`, `materials`, `_faces` and
`silhouette`). Standard library only.
"""

import math
import os
import re

from wgflib import paths, yamllite

__all__ = ["RUBRIC_PATH", "DEFAULT_RULES", "load_rubric", "load_rules", "lint",
           "identity_light", "ROUND_SHAPES"]

RUBRIC_PATH = os.path.join(paths.REFERENCE, "model-review-rubric.yaml")
# Used only when the reference file lacks a key; the file is the bar.
DEFAULT_RULES = {
    "floating": {"min_gap": 0.05, "severity": "error",
                 "exempt_roles": ["environment", "background", "vfx"]},
    "hidden": {"min_shown": 0.0, "severity": "error"},
    "coplanar": {"plane_tolerance": 0.0001, "min_overlap": 0.0001, "down_facing": 0.7,
                 "severity": "error"},
    "emissive": {"severity": "error", "exempt_roles": ["background", "vfx"],
                 "lit": {"max_share": 0.25, "max_strength": 2.0},
                 "neon": {"max_share": 0.7, "max_strength": 10.0},
                 "neon_words": ["neon", "glow", "synthwave", "cyber", "laser", "luminous",
                                "tron", "arcade glow"]},
    "aspect": {"severity": "error", "max_elongation": {"collectible": 2.0}},
    "bevel": {"severity": "warning", "shapes": ["box", "cylinder"], "min_size": 0.1,
              "crisp_words": ["crisp edge", "crisp edges", "hard edge", "hard edges",
                              "sharp edge", "sharp edges", "razor"]},
    "smooth": {"severity": "warning", "min_segments": 8},
}
# Shapes that are round in at least one direction: smooth shading across them is a choice.
ROUND_SHAPES = ("sphere", "capsule", "cylinder", "cone", "lathe")


def load_rubric(path=None):
    """The whole rubric document (judge dimensions and lint rules)."""
    path = path or RUBRIC_PATH
    with open(path, encoding="utf-8") as handle:
        return yamllite.load(handle.read()) or {}


def load_rules(path=None):
    """The `lint` section of the rubric over the defaults (each rule merged key by key)."""
    rules = {k: dict(v) for k, v in DEFAULT_RULES.items()}
    path = path or RUBRIC_PATH
    if os.path.isfile(path):
        document = load_rubric(path)
        for key, value in ((document.get("lint") or {}).items()):
            if isinstance(value, dict):
                rules[key] = dict(rules.get(key) or {}, **value)
    return rules


def _identity_text(visual_identity, keys=("concept", "shape_language", "texture", "motion")):
    look = visual_identity if isinstance(visual_identity, dict) else {}
    return " ".join(str(look.get(k)) for k in keys if isinstance(look.get(k), str)).lower()


def identity_light(visual_identity, rules=None):
    """"neon" when the identity's own words (never its `avoid` list) ask for glow, else
    "lit": a lit identity lights its models and keeps emissive to small accents."""
    rule = (rules or DEFAULT_RULES).get("emissive") or {}
    text = _identity_text(visual_identity)
    avoided = " ".join(str(a) for a in ((visual_identity or {}).get("avoid") or [])
                       if isinstance(visual_identity, dict)).lower()
    for word in rule.get("neon_words") or []:
        word = str(word).lower()
        if re.search(r"(?<![a-z])" + re.escape(word), text) and word not in avoided:
            return "neon"
    return "lit"


def _gap(a, b):
    return math.sqrt(sum(max(0.0, b["min"][k] - a["max"][k], a["min"][k] - b["max"][k]) ** 2
                         for k in range(3)))


def _extent(nodes):
    lo = [min(n["min"][k] for n in nodes) for k in range(3)]
    hi = [max(n["max"][k] for n in nodes) for k in range(3)]
    return [hi[k] - lo[k] for k in range(3)]


def _volume(node):
    return max(1e-12, math.prod(max(1e-6, node["max"][k] - node["min"][k]) for k in range(3)))


def _floating(nodes, rule, role):
    if role in (rule.get("exempt_roles") or []) or len(nodes) < 2:
        return []
    share = float(rule.get("min_gap", 0.05))
    sizes = [max(n["max"][k] - n["min"][k] for k in range(3)) for n in nodes]
    parent = list(range(len(nodes)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(nodes)):
        for j in range(i + 1, len(nodes)):
            if _gap(nodes[i], nodes[j]) <= share * min(sizes[i], sizes[j]):
                parent[find(j)] = find(i)
    groups = {}
    for i in range(len(nodes)):
        groups.setdefault(find(i), []).append(i)
    if len(groups) < 2:
        return []
    main = max(groups.values(), key=lambda g: (sum(_volume(nodes[i]) for i in g), -min(g)))
    out = []
    for group in sorted((g for g in groups.values() if g is not main), key=min):
        gap = min(_gap(nodes[i], nodes[j]) for i in group for j in main)
        size = max(sizes[i] for i in group)
        names = sorted(nodes[i]["name"] for i in group)
        out.append({"code": "lint.floating", "severity": rule.get("severity", "error"),
                    "parts": names,
                    "message": f"{', '.join(names)} touch(es) nothing of the main body: "
                               f"{gap:.3g} m from it, {gap / size:.0%} of its own {size:.3g} m "
                               f"(a part is attached within {share:.0%} of its size). Attach it - "
                               f"overlap it into the part that carries it (a flag into its "
                               f"pole, a lantern onto a hook) - or remove it"})
    return out


# The axis views a hidden part is looked for from, as (u, v, depth) axes; each is read from
# both its sides (front and back, left and right, top and bottom).
_VIEWS = ((0, 1, 2), (2, 1, 0), (0, 2, 1))
_FINE = 16


def _seen_closely(name, node, faces, largest):
    """True when the part `name` is the nearest surface in at least one cell of a fine grid
    laid over its own footprint, from any of the six axis directions. The silhouette grid
    is the whole model's: a lane line or a pylon thinner than one of its cells falls between
    its samples, so a part that grid never saw is looked at again at its own scale. A tie in
    depth (a face flush with another) counts as seen - that is the coplanar rule's."""
    tie = 1e-6 * largest
    for u_axis, v_axis, d_axis in _VIEWS:
        lo_u, hi_u = node["min"][u_axis], node["max"][u_axis]
        lo_v, hi_v = node["min"][v_axis], node["max"][v_axis]
        if hi_u - lo_u <= tie or hi_v - lo_v <= tie:
            continue   # edge-on from this axis
        # Cells of the part's own proportions: _FINE across each side, so a line thinner
        # than any square cell is still sampled across its width.
        cell_u, cell_v = (hi_u - lo_u) / _FINE, (hi_v - lo_v) / _FINE
        width = height = _FINE
        near, far = {}, {}
        for owner, _material, tri in faces:
            us = [p[u_axis] for p in tri]
            vs = [p[v_axis] for p in tri]
            if max(us) < lo_u or min(us) > hi_u or max(vs) < lo_v or min(vs) > hi_v:
                continue
            flat = [((p[u_axis] - lo_u) / cell_u, (p[v_axis] - lo_v) / cell_v, p[d_axis])
                    for p in tri]
            (ax, ay, ad), (bx, by, bd), (cx, cy, cd) = flat
            det = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
            if abs(det) <= 1e-9:
                continue
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
                    for buffer, better in ((near, depth < near.get(key, (math.inf,))[0]
                                            - tie), (far, depth > far.get(key, (-math.inf,))[0]
                                                     + tie)):
                        held = buffer.get(key)
                        if better:
                            buffer[key] = (depth, {owner})
                        elif held is not None and abs(depth - held[0]) <= tie:
                            held[1].add(owner)
        if any(name in owners for buffer in (near, far) for _d, owners in buffer.values()):
            return True
    return False


def _hidden(nodes, faces, rule):
    least = float(rule.get("min_shown", 0.0))
    largest = max(_extent(nodes)) or 1.0
    out = []
    for node in nodes:
        shown = node.get("shown") or {}
        if not shown or max(shown.values()) > least:
            continue   # unmeasured (flat or undecoded), or seen on the model's own grid
        if least <= 0.0 and _seen_closely(node["name"], node, faces, largest):
            continue
        out.append({"code": "lint.hidden", "severity": rule.get("severity", "error"),
                    "parts": [node["name"]],
                    "message": f"{node['name']} is not the nearest surface anywhere from the "
                               f"front, back, sides, top or bottom: it is inside another part "
                               f"and no player sees it. Raise it through the surface it is "
                               f"sunk in, or remove it"})
    return out


def _plane(tri):
    a, b, c = tri
    u = [b[k] - a[k] for k in range(3)]
    v = [c[k] - a[k] for k in range(3)]
    n = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])
    length = math.sqrt(sum(x * x for x in n))
    if length <= 1e-12:
        return None
    n = tuple(x / length for x in n)
    return n, sum(n[k] * a[k] for k in range(3))


def _basis(n):
    helper = (1.0, 0.0, 0.0) if abs(n[0]) < 0.9 else (0.0, 1.0, 0.0)
    u = (n[1] * helper[2] - n[2] * helper[1], n[2] * helper[0] - n[0] * helper[2],
         n[0] * helper[1] - n[1] * helper[0])
    length = math.sqrt(sum(x * x for x in u))
    u = tuple(x / length for x in u)
    v = (n[1] * u[2] - n[2] * u[1], n[2] * u[0] - n[0] * u[2], n[0] * u[1] - n[1] * u[0])
    return u, v


def _overlap_2d(t1, t2, depth):
    """True when two 2D triangles overlap by more than `depth` along every separating axis."""
    for tri in (t1, t2):
        for i in range(3):
            a, b = tri[i], tri[(i + 1) % 3]
            axis = (b[1] - a[1], a[0] - b[0])
            length = math.hypot(*axis)
            if length <= 1e-12:
                return False
            axis = (axis[0] / length, axis[1] / length)
            p1 = [p[0] * axis[0] + p[1] * axis[1] for p in t1]
            p2 = [p[0] * axis[0] + p[1] * axis[1] for p in t2]
            if min(max(p1), max(p2)) - max(min(p1), min(p2)) <= depth:
                return False
    return True


def _coplanar(faces, nodes, rule):
    if not faces:
        return []
    largest = max(_extent(nodes)) or 1.0
    tolerance = float(rule.get("plane_tolerance", 1e-4)) * largest
    depth = float(rule.get("min_overlap", 1e-4)) * largest
    planes = []
    for name, material, tri in faces:
        plane = _plane(tri)
        if plane is not None:
            planes.append((name, material, tri, plane))
    buckets = {}
    for entry in planes:
        n, _d = entry[3]
        key = tuple(round(x, 2) for x in n)
        buckets.setdefault(key, []).append(entry)
    fighting = {}
    for group in buckets.values():
        group.sort(key=lambda e: e[3][1])
        for i, (name_a, mat_a, tri_a, (n_a, d_a)) in enumerate(group):
            for name_b, mat_b, tri_b, (n_b, d_b) in group[i + 1:]:
                if d_b - d_a > tolerance:
                    break
                if name_a == name_b or mat_a == mat_b:
                    continue
                pair = tuple(sorted((name_a, name_b)))
                if pair in fighting:
                    continue
                if sum(n_a[k] * n_b[k] for k in range(3)) < 0.9999:
                    continue
                if n_a[1] < -float(rule.get("down_facing", 0.7)):
                    continue   # an underside: no game camera above the play sees it
                u, v = _basis(n_a)
                flat_a = [(sum(p[k] * u[k] for k in range(3)), sum(p[k] * v[k] for k in range(3)))
                          for p in tri_a]
                flat_b = [(sum(p[k] * u[k] for k in range(3)), sum(p[k] * v[k] for k in range(3)))
                          for p in tri_b]
                if _overlap_2d(flat_a, flat_b, depth):
                    fighting[pair] = {name_a: mat_a, name_b: mat_b}
    return [{"code": "lint.coplanar", "severity": rule.get("severity", "error"),
             "parts": list(pair),
             "message": f"{pair[0]} ({materials[pair[0]]}) and {pair[1]} "
                        f"({materials[pair[1]]}) have overlapping faces on one plane, facing the same way, "
                        f"in different materials: they flicker (z-fight) in the game. Raise "
                        f"one part's face above the other's, or inset it"}
            for pair, materials in sorted(fighting.items())]


def _emissive(geometry, rule, visual_identity, role):
    if role in (rule.get("exempt_roles") or []):
        return []
    light = identity_light(visual_identity, {"emissive": rule})
    limits = rule.get(light) or {}
    # Emissive is a factor of its own, read whether or not the base colour is textured.
    materials = list(geometry.get("materials") or [])
    total = sum(m.get("area") or 0.0 for m in materials)
    glowing = [m for m in materials if (m.get("emissive") or "#000000") != "#000000"]
    out = []
    if not total or not glowing:
        return out
    share = sum(m.get("area") or 0.0 for m in glowing) / total
    most = float(limits.get("max_share", 1.0))
    if share > most:
        out.append({"code": "lint.emissive", "severity": rule.get("severity", "error"),
                    "parts": sorted(m["name"] for m in glowing),
                    "message": f"{share:.0%} of the surface glows ({', '.join(sorted(m['name'] for m in glowing))}); "
                               f"a {light} visual identity keeps emissive to {most:.0%} - "
                               f"small accents (a lamp, a rim, an eye). Light the body with "
                               f"its base colour and keep the glow for the detail"})
    hardest = max(glowing, key=lambda m: float(m.get("emissive_strength") or 0.0))
    strength = float(hardest.get("emissive_strength") or 0.0)
    limit = float(limits.get("max_strength", 100.0))
    if strength > limit:
        out.append({"code": "lint.emissive", "severity": rule.get("severity", "error"),
                    "parts": [hardest["name"]],
                    "message": f"material {hardest['name']} glows at strength {strength:g}; "
                               f"a {light} visual identity allows at most {limit:g}"})
    return out


def _aspect(geometry, rule, role):
    limit = (rule.get("max_elongation") or {}).get(role)
    nodes = geometry.get("nodes") or []
    if limit is None or not nodes:
        return []
    dims = sorted(_extent(nodes), reverse=True)
    if dims[1] <= 1e-9:
        return []
    elongation = dims[0] / dims[1]
    if elongation <= float(limit):
        return []
    return [{"code": "lint.aspect", "severity": rule.get("severity", "error"), "parts": [],
             "message": f"the model is {elongation:.2f} times as long as it is wide "
                        f"({dims[0]:.3g} m by {dims[1]:.3g} m); a {role} reads as a compact "
                        f"shape at gameplay size - at most {float(limit):g} to 1. A needle "
                        f"or a sliver reads as a line: make it stockier"}]


def _spec_parts(spec):
    from . import modelspec
    if not isinstance(spec, dict) or not modelspec.buildable(spec):
        return []
    try:
        return modelspec.expand_parts(spec["parts"])
    except (KeyError, TypeError, ValueError):
        return []


def _bevel(spec, nodes, rule, visual_identity):
    text = _identity_text(visual_identity)
    if any(str(w).lower() in text for w in rule.get("crisp_words") or []):
        return []
    parts = _spec_parts(spec)
    if not parts or not nodes:
        return []
    largest = max(_extent(nodes)) or 1.0
    by_name = {n["name"]: n for n in nodes}
    bare = []
    for part in parts:
        node = by_name.get(part.get("id"))
        if part.get("shape") not in (rule.get("shapes") or []) or part.get("bevel") or not node:
            continue
        # A chunky part - its smallest side a real share of the model - shows its edges; a
        # trim strip or a panel is too thin for a bevel to read.
        size = min(node["max"][k] - node["min"][k] for k in range(3))
        if size >= float(rule.get("min_size", 0.1)) * largest:
            bare.append(part["id"])
    if not bare:
        return []
    return [{"code": "lint.bevel", "severity": rule.get("severity", "warning"), "parts": bare,
             "message": f"{', '.join(bare)}: large {'/'.join(rule.get('shapes') or [])} "
                        f"part(s) with no bevel read as untouched primitives; a small `bevel` "
                        f"catches the key light on their edges"}]


def _smooth(spec, rule):
    from . import modelspec
    least = int(rule.get("min_segments", 8))
    blotchy = []
    for part in _spec_parts(spec):
        shape = part.get("shape")
        if shape not in ROUND_SHAPES:
            continue
        smooth = part.get("smooth", shape in modelspec.SMOOTH_SHAPES)
        if smooth and int(part.get("segments", 16)) < least:
            blotchy.append(part["id"])
    if not blotchy:
        return []
    return [{"code": "lint.smooth", "severity": rule.get("severity", "warning"),
             "parts": blotchy,
             "message": f"{', '.join(blotchy)}: smooth shading across fewer than {least} "
                        f"segments smears the light into blotches; give it {least} or more "
                        f"segments, or flat-shade it (`smooth: false`) for a faceted look"}]


def lint(geometry, *, spec=None, role=None, visual_identity=None, rules=None):
    """The craft findings of one model, most severe first. [] when the geometry was not
    decoded (nothing to measure is never a pass the caller may report as one)."""
    rules = rules or load_rules()
    if not geometry or not geometry.get("decoded") or not geometry.get("nodes"):
        return []
    nodes = geometry["nodes"]
    findings = []
    findings += _floating(nodes, rules.get("floating") or {}, role)
    findings += _hidden(nodes, geometry.get("_faces") or [], rules.get("hidden") or {})
    findings += _coplanar(geometry.get("_faces") or [], nodes, rules.get("coplanar") or {})
    findings += _emissive(geometry, rules.get("emissive") or {}, visual_identity, role)
    findings += _aspect(geometry, rules.get("aspect") or {}, role)
    findings += _bevel(spec, nodes, rules.get("bevel") or {}, visual_identity)
    findings += _smooth(spec, rules.get("smooth") or {})
    order = {"error": 0, "warning": 1, "info": 2}
    return sorted(findings, key=lambda f: order.get(f["severity"], 3))

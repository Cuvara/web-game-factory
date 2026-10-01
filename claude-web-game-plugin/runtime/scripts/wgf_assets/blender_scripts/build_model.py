"""Build one GLB from a resolved model spec. Runs INSIDE Blender, never in the Factory's Python.

    blender --background --factory-startup -noaudio --python-exit-code 3 \
        --python build_model.py -- --spec resolved.json --textures DIR --out model.glb \
        --report report.json

`resolved.json` is `wgf_assets.modelspec.resolve()` output: glTF coordinates (metres, +Y up),
quaternions, linear colours, parents before children, textures as PNG files in DIR. This
script converts to Blender's Z-up frame, builds, and lets the glTF exporter convert back.

What it makes, as glTF nodes (every name deterministic, custom properties exported as node
`extras`, which three.js's GLTFLoader puts on `object.userData`):

    <asset>                 root, identity; extras {wgf_asset, wgf_format}
      <part> ...            one mesh node per spec part, in the spec's hierarchy
      <asset>_LOD0          only with LODs: an empty holding the parts; extras {wgf_lod: 0}
      <asset>_LOD<n>        one joined mesh per ratio, decimated by vertex clustering (the
                            collapse decimator is not deterministic); extras {wgf_lod: n}
      <asset>_collision     only with a collision proxy; no material;
                            extras {wgf_role: collision, wgf_shape, wgf_center, wgf_half_extents}

Fit and pivot are applied to the real geometry: scale into the vertices and positions, never
a scale left on a node, so every node's scale is 1 at rest.

Deterministic by construction: factory settings, no user preferences or add-ons, no random
input, names from the spec, and the exporter options fixed below. Only the Blender version
can change the bytes, which is why the Factory pins it (core/reference/asset-policy.yaml).

On any failure the report says why and Blender exits 3; the report is always written.
"""

import json
import math
import os
import sys
import traceback

import bmesh
import bpy
from mathutils import Matrix, Quaternion, Vector

FORMAT = 1


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    options = {}
    for key, value in zip(argv[::2], argv[1::2]):
        options[key.lstrip("-")] = value
    for required in ("spec", "out", "report"):
        if required not in options:
            raise SystemExit(f"build_model.py: --{required} is required")
    return options


# glTF (x, y, z) -> Blender (x, -z, y), and back.
def to_blender(v):
    return Vector((v[0], -v[2], v[1]))


def to_gltf(v):
    return [v[0] + 0.0, v[2] + 0.0, -v[1] + 0.0]


def size_to_blender(s):
    return Vector((s[0], s[2], s[1]))


def quat_to_blender(q):
    x, y, z, w = q
    return Quaternion((w, x, -z, y))


def reset_scene(fps):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    for collection in (bpy.data.objects, bpy.data.meshes, bpy.data.materials, bpy.data.images,
                       bpy.data.actions):
        for block in list(collection):
            collection.remove(block)
    scene = bpy.context.scene
    scene.render.fps = fps
    scene.render.fps_base = 1.0
    scene.frame_start = 0
    scene.frame_current = 0
    return scene


def unit_primitive(bm, shape, segments):
    """A primitive centred on the origin, fitted to the unit cube (Blender frame)."""
    if shape == "box":
        bmesh.ops.create_cube(bm, size=1.0, calc_uvs=True)
    elif shape in ("cylinder", "cone"):
        bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=segments,
                              radius1=0.5, radius2=0.5 if shape == "cylinder" else 0.0,
                              depth=1.0, calc_uvs=True)
    elif shape == "sphere":
        bmesh.ops.create_uvsphere(bm, u_segments=segments, v_segments=max(3, segments // 2),
                                  radius=0.5, calc_uvs=True)
    elif shape == "icosphere":
        subdivisions = max(1, min(4, int(round(math.log2(max(4, segments) / 4))) + 1))
        bmesh.ops.create_icosphere(bm, subdivisions=subdivisions, radius=0.5, calc_uvs=True)
    elif shape == "plane":
        bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=0.5, calc_uvs=True)
    else:
        raise ValueError(f"unknown shape {shape!r}")
    # Normalise whatever the operator made to exactly the unit box, so `size` means size.
    lo = Vector([min(v.co[i] for v in bm.verts) for i in range(3)])
    hi = Vector([max(v.co[i] for v in bm.verts) for i in range(3)])
    extent = hi - lo
    centre = (hi + lo) / 2
    bmesh.ops.translate(bm, vec=-centre, verts=bm.verts)
    bmesh.ops.scale(bm, vec=Vector([1.0 / e if e > 1e-12 else 1.0 for e in extent]),
                    verts=bm.verts)


def canonical(bm):
    """Put vertices and faces in an order that depends only on the geometry.

    Some bmesh primitives come out in a face order that changes from run to run (pointer-keyed
    hashing inside the operators); the exporter's vertex de-duplication hides that in the
    vertex buffer but not in the index buffer, so the GLB bytes would change with it."""
    # BMesh sequences sort by a numeric key: rank each element by its geometric key first.
    bm.verts.index_update()
    order = sorted(bm.verts, key=lambda v: (round(v.co.x, 6), round(v.co.y, 6),
                                            round(v.co.z, 6)))
    rank = {v.index: i for i, v in enumerate(order)}
    bm.verts.sort(key=lambda v: rank[v.index])
    bm.verts.index_update()

    def face_key(face):
        ids = [loop.vert.index for loop in face.loops]
        start = ids.index(min(ids))
        return tuple(ids[start:] + ids[:start])

    bm.faces.index_update()
    order = sorted(bm.faces, key=face_key)
    rank = {f.index: i for i, f in enumerate(order)}
    bm.faces.sort(key=lambda f: rank[f.index])
    bm.faces.index_update()


def capsule(bm, size, segments):
    """A capsule standing along Blender Z, fitted to `size` (Blender frame): a UV sphere of an
    odd ring count - so no ring sits on the equator - whose halves are pushed apart into a
    straight-walled middle. Caps are hemispheres of the smaller of the x and y radii."""
    sx, sy, height = size
    radius = min(sx, sy, height) / 2
    bmesh.ops.create_uvsphere(bm, u_segments=segments,
                              v_segments=max(3, segments // 2) | 1, radius=0.5, calc_uvs=True)
    # Without an equator ring the widest ring is narrower than the sphere: measure it, so
    # `size` is the bounding size.
    width = [max(v.co[i] for v in bm.verts) - min(v.co[i] for v in bm.verts) for i in (0, 1)]
    shift = height / 2 - radius
    for vert in bm.verts:
        x, y, z = vert.co
        vert.co = Vector((x * sx / width[0], y * sy / width[1],
                          z * 2 * radius + (shift if z > 0 else -shift if z < 0 else 0.0)))


def taper(bm, factors):
    """Scale each vertex's x and y (glTF x and z) linearly with its height: 1 at the bottom,
    `factors` at the top. Pure arithmetic on the vertices, so deterministic."""
    low = min(v.co.z for v in bm.verts)
    high = max(v.co.z for v in bm.verts)
    span = high - low
    if span <= 1e-12:
        return
    fx, fy = factors[0], factors[1]  # glTF [x, z] are Blender x, y
    for vert in bm.verts:
        t = (vert.co.z - low) / span
        vert.co = Vector((vert.co.x * (1 + (fx - 1) * t), vert.co.y * (1 + (fy - 1) * t),
                          vert.co.z))


def bevel(bm, offset):
    """Round the sharp edges (faces meeting at 30 degrees or more) off with two segments.
    The input order is made canonical first, so the operator sees the same mesh every run."""
    canonical(bm)
    bm.edges.index_update()
    edges = sorted((e for e in bm.edges
                    if e.is_manifold and e.calc_face_angle(0.0) >= math.radians(30)),
                   key=lambda e: tuple(sorted((e.verts[0].index, e.verts[1].index))))
    if edges:
        bmesh.ops.bevel(bm, geom=edges, offset=offset, offset_type="OFFSET", segments=2,
                        profile=0.5, affect="EDGES", clamp_overlap=True)


def make_mesh(part, repeat):
    bm = bmesh.new()
    if part["shape"] == "capsule":
        capsule(bm, size_to_blender(part["size"]), part["segments"])
    else:
        unit_primitive(bm, part["shape"], part["segments"])
        bmesh.ops.scale(bm, vec=size_to_blender(part["size"]), verts=bm.verts)
    if part.get("taper"):
        taper(bm, part["taper"])
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-6)
    if part.get("bevel"):
        bevel(bm, part["bevel"])
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    # Triangulate here, with fixed methods: left to the exporter, quads are tessellated in an
    # order that varies from run to run, and the GLB with it.
    bmesh.ops.triangulate(bm, faces=bm.faces, quad_method="FIXED", ngon_method="EAR_CLIP")
    canonical(bm)
    for face in bm.faces:
        face.smooth = part["smooth"]
    uv = bm.loops.layers.uv.active
    if uv is not None and repeat != 1:
        for face in bm.faces:
            for loop in face.loops:
                loop[uv].uv = loop[uv].uv * repeat
    mesh = bpy.data.meshes.new(part["id"])
    bm.to_mesh(mesh)
    bm.free()
    return mesh


def make_material(spec, texture_dir):
    material = bpy.data.materials.new(spec["id"])
    material.use_nodes = True
    nodes = material.node_tree.nodes
    bsdf = nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = spec["color"]
    bsdf.inputs["Metallic"].default_value = spec["metallic"]
    bsdf.inputs["Roughness"].default_value = spec["roughness"]
    bsdf.inputs["Alpha"].default_value = spec["color"][3]
    if any(c > 0 for c in spec["emissive"]):
        name = "Emission Color" if "Emission Color" in bsdf.inputs else "Emission"
        bsdf.inputs[name].default_value = list(spec["emissive"]) + [1.0]
        bsdf.inputs["Emission Strength"].default_value = spec["emissive_strength"]
    if spec["color"][3] < 1.0:
        if hasattr(material, "surface_render_method"):
            material.surface_render_method = "BLENDED"
        if hasattr(material, "blend_method"):
            material.blend_method = "BLEND"
    texture = spec.get("texture")
    if texture:
        image = bpy.data.images.load(os.path.join(texture_dir, texture["file"]))
        image.name = os.path.splitext(texture["file"])[0]
        image.pack()
        node = nodes.new("ShaderNodeTexImage")
        node.image = image
        node.interpolation = "Linear"
        material.node_tree.links.new(node.outputs["Color"], bsdf.inputs["Base Color"])
    return material


def new_object(name, data=None, parent=None, props=None):
    obj = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(obj)
    obj.rotation_mode = "QUATERNION"
    if parent is not None:
        obj.parent = parent
    for key, value in (props or {}).items():
        obj[key] = value
    return obj


def world_vertices(objects):
    bpy.context.view_layer.update()
    points = []
    for obj in objects:
        matrix = obj.matrix_world
        points.extend(matrix @ v.co for v in obj.data.vertices)
    return points


def bounds(points):
    lo = Vector([min(p[i] for p in points) for i in range(3)])
    hi = Vector([max(p[i] for p in points) for i in range(3)])
    return lo, hi


def fit_and_pivot(spec, parts, top_level):
    """Scale and offset (Blender frame) applied to the geometry. Returns (scale, offset)."""
    scale = 1.0
    fit = spec.get("fit")
    if fit:
        lo, hi = bounds(world_vertices(parts.values()))
        extent = hi - lo
        # glTF x, y, z are Blender x, z, y.
        axis = {"x": extent.x, "y": extent.z, "z": extent.y, "max": max(extent)}[fit["axis"]]
        if axis > 1e-12:
            scale = fit["size"] / axis
    if scale != 1.0:
        for obj in parts.values():
            obj.data.transform(Matrix.Scale(scale, 4))
            obj.location = obj.location * scale
    offset = Vector((0.0, 0.0, 0.0))
    if spec["pivot"] != "origin":
        lo, hi = bounds(world_vertices(parts.values()))
        centre = (lo + hi) / 2
        offset = Vector((-centre.x, -centre.y,
                         -lo.z if spec["pivot"] == "base-center" else -centre.z))
        for obj in top_level:
            obj.location = obj.location + offset
    return scale, offset


def animate(spec, parts, top_level, scale, offset):
    """One NLA track per clip on every object it moves; the exporter's NLA_TRACKS mode merges
    tracks of the same name across objects into one glTF animation."""
    fps = spec["fps"]
    rest = {pid: (obj.location.copy(), obj.rotation_quaternion.copy(), obj.scale.copy())
            for pid, obj in parts.items()}
    preferences = bpy.context.preferences.edit
    for clip in spec["animations"]:
        preferences.keyframe_new_interpolation_type = (
            "CONSTANT" if clip["interpolation"] == "step" else "LINEAR")
        by_part = {}
        for track in clip["tracks"]:
            by_part.setdefault(track["part"], []).append(track)
        for pid, tracks in by_part.items():
            obj = parts[pid]
            data = obj.animation_data or obj.animation_data_create()
            data.action = None
            for track in tracks:
                for t, value in zip(track["times"], track["values"]):
                    frame = t * fps
                    if track["path"] == "translation":
                        location = to_blender(value) * scale
                        if obj in top_level:
                            location = location + offset
                        obj.location = location
                        obj.keyframe_insert("location", frame=frame)
                    elif track["path"] == "rotation":
                        obj.rotation_quaternion = quat_to_blender(value)
                        obj.keyframe_insert("rotation_quaternion", frame=frame)
                    else:
                        obj.scale = size_to_blender(value)
                        obj.keyframe_insert("scale", frame=frame)
            action = data.action
            action.name = f"{clip['name']}.{pid}"
            nla = data.nla_tracks.new()
            nla.name = clip["name"]
            nla.strips.new(clip["name"], 0, action)
            # Muted, so no clip poses the rest transform the exporter writes; the exporter
            # unmutes each track while it exports it, and restores the mute afterwards.
            nla.mute = True
            data.action = None
        for pid, (location, rotation, size) in rest.items():
            parts[pid].location, parts[pid].rotation_quaternion, parts[pid].scale = (
                location, rotation, size)


def triangle_soup(objects):
    """(triangles, materials): every object's triangles in root space, each as
    (positions, uvs, material index, smooth), in a fixed order; materials remapped."""
    triangles, materials = [], []
    for obj in objects:
        bm = bmesh.new()
        bm.from_mesh(obj.data)
        bmesh.ops.transform(bm, matrix=obj.matrix_world, verts=bm.verts)
        bmesh.ops.triangulate(bm, faces=bm.faces, quad_method="FIXED", ngon_method="EAR_CLIP")
        canonical(bm)
        remap = []
        for material in obj.data.materials:
            if material not in materials:
                materials.append(material)
            remap.append(materials.index(material))
        uv = bm.loops.layers.uv.active
        for face in bm.faces:
            loops = list(face.loops)
            triangles.append((
                tuple(tuple(loop.vert.co) for loop in loops),
                tuple(tuple(loop[uv].uv) if uv is not None else (0.0, 0.0) for loop in loops),
                remap[face.material_index] if remap else 0,
                face.smooth))
        bm.free()
    return triangles, materials


def cluster(triangles, cell, origin):
    """Vertex clustering: every vertex snaps to its grid cell; triangles that collapse or
    repeat are dropped. Pure arithmetic in a fixed order, so the same input and cell always
    give the same output - which Blender's collapse decimation does not."""
    def key(p):
        return tuple(int(math.floor((p[k] - origin[k]) / cell)) for k in range(3))

    sums, seen_points = {}, set()
    for positions, _uvs, _m, _s in triangles:
        for p in positions:
            rounded = tuple(round(c, 6) for c in p)
            if rounded in seen_points:
                continue
            seen_points.add(rounded)
            total = sums.setdefault(key(p), [0.0, 0.0, 0.0, 0])
            total[0] += p[0]
            total[1] += p[1]
            total[2] += p[2]
            total[3] += 1
    out, seen = [], set()
    for positions, uvs, material, smooth in triangles:
        keys = [key(p) for p in positions]
        if len(set(keys)) < 3:
            continue
        start = keys.index(min(keys))
        canon = tuple(keys[start:] + keys[:start])
        if canon in seen:
            continue
        seen.add(canon)
        out.append((keys, uvs, material, smooth))
    centres = {k: (v[0] / v[3], v[1] / v[3], v[2] / v[3]) for k, v in sums.items()}
    return out, centres


def decimate(triangles, ratio):
    """The clustering whose triangle count is closest to, and not above, ratio x input."""
    target = max(1, int(len(triangles) * ratio))
    points = [p for t in triangles for p in t[0]]
    lo_corner = [min(p[k] for p in points) for k in range(3)]
    hi_corner = [max(p[k] for p in points) for k in range(3)]
    diagonal = math.sqrt(sum((hi_corner[k] - lo_corner[k]) ** 2 for k in range(3))) or 1.0
    origin = [c - diagonal * 1e-3 for c in lo_corner]
    small, large = diagonal * 1e-5, diagonal
    best = None
    for _ in range(32):
        cell = math.sqrt(small * large)
        result = cluster(triangles, cell, origin)
        if len(result[0]) > target:
            small = cell
        else:
            best, large = result, cell
    return best or cluster(triangles, large, origin)


def lod_mesh(name, triangles, materials, ratio):
    faces, centres = decimate(triangles, ratio)
    order = sorted({k for keys, _u, _m, _s in faces for k in keys})
    index = {k: i for i, k in enumerate(order)}
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata([centres[k] for k in order], [],
                     [[index[k] for k in keys] for keys, _u, _m, _s in faces])
    for material in materials:
        mesh.materials.append(material)
    uv_layer = mesh.uv_layers.new(name="UVMap")
    for polygon, (_keys, uvs, material, smooth) in zip(mesh.polygons, faces):
        polygon.material_index = material
        polygon.use_smooth = smooth
        for loop_index, uv in zip(polygon.loop_indices, uvs):
            uv_layer.data[loop_index].uv = uv
    mesh.update()
    return mesh


def make_lods(spec, root, parts, top_level):
    asset = spec["asset_id"]
    group = new_object(f"{asset}_LOD0", None, root, {"wgf_lod": 0})
    for obj in top_level:
        obj.parent = group
    bpy.context.view_layer.update()
    triangles, materials = triangle_soup(parts.values())
    made = []
    for level, ratio in enumerate(spec["lods"], start=1):
        name = f"{asset}_LOD{level}"
        mesh = lod_mesh(name, triangles, materials, ratio)
        new_object(name, mesh, root, {"wgf_lod": level})
        made.append({"level": level, "ratio": ratio, "triangles": len(mesh.polygons)})
    return made


# A physics engine wants a convex proxy of tens of vertices, not the visual mesh's hundreds.
MAX_HULL_POINTS = 64


def hull_points(points):
    """At most MAX_HULL_POINTS points whose hull approximates the points': the vertex
    clusters of the finest grid that yields few enough. Deterministic, like cluster()."""
    unique = sorted({tuple(round(c, 6) for c in p) for p in points})
    if len(unique) <= MAX_HULL_POINTS:
        return unique
    lo = [min(p[k] for p in unique) for k in range(3)]
    hi = [max(p[k] for p in unique) for k in range(3)]
    diagonal = math.sqrt(sum((hi[k] - lo[k]) ** 2 for k in range(3))) or 1.0
    origin = [c - diagonal * 1e-3 for c in lo]

    def clusters(cell):
        groups = {}
        for p in unique:
            key = tuple(int(math.floor((p[k] - origin[k]) / cell)) for k in range(3))
            groups.setdefault(key, []).append(p)
        # The member farthest from the grid centre keeps the hull from shrinking inward.
        centre = [(lo[k] + hi[k]) / 2 for k in range(3)]
        return [max(members, key=lambda q: (sum((q[k] - centre[k]) ** 2 for k in range(3)), q))
                for _key, members in sorted(groups.items())]

    small, large, best = diagonal * 1e-4, diagonal, None
    for _ in range(32):
        cell = math.sqrt(small * large)
        chosen = clusters(cell)
        if len(chosen) > MAX_HULL_POINTS:
            small = cell
        else:
            best, large = chosen, cell
    return best or clusters(large)


def make_collision(spec, root, parts):
    asset = spec["asset_id"]
    shape = spec["collision"]["shape"]
    points = world_vertices(parts.values())
    bm = bmesh.new()
    lo, hi = bounds(points)
    if shape == "box":
        bmesh.ops.create_cube(bm, size=1.0)
        bmesh.ops.scale(bm, vec=hi - lo, verts=bm.verts)
        bmesh.ops.translate(bm, vec=(hi + lo) / 2, verts=bm.verts)
    else:
        for point in hull_points(points):
            bm.verts.new(point)
        bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-6)
        hull = bmesh.ops.convex_hull(bm, input=bm.verts)
        inside = [g for g in dict.fromkeys(hull["geom_interior"] + hull["geom_unused"])
                  if isinstance(g, bmesh.types.BMVert)]
        bmesh.ops.delete(bm, geom=inside, context="VERTS")
    bmesh.ops.triangulate(bm, faces=bm.faces, quad_method="FIXED", ngon_method="EAR_CLIP")
    canonical(bm)
    mesh = bpy.data.meshes.new(f"{asset}_collision")
    bm.to_mesh(mesh)
    bm.free()
    centre = to_gltf((hi + lo) / 2)
    half = (hi - lo) / 2
    props = {"wgf_role": "collision", "wgf_shape": shape,
             "wgf_center": [round(v, 6) + 0.0 for v in centre],
             "wgf_half_extents": [round(v, 6) + 0.0 for v in (half.x, half.z, half.y)]}
    new_object(f"{asset}_collision", mesh, root, props)
    return {"shape": shape, "triangles": len(mesh.polygons)}


EXPORT_OPTIONS = {
    "export_format": "GLB",
    "use_selection": False,
    "export_extras": True,
    "export_yup": True,
    "export_apply": True,
    "export_texcoords": True,
    "export_normals": True,
    "export_tangents": False,
    "export_materials": "EXPORT",
    "export_image_format": "AUTO",
    "export_cameras": False,
    "export_lights": False,
    "export_skins": False,
    "export_morph": False,
    "export_animation_mode": "NLA_TRACKS",
    "export_force_sampling": False,
    "export_optimize_animation_size": False,
    # A channel that holds one value for the whole clip is still part of the clip.
    # Default: a channel that never changes is not exported. modelspec rejects a clip that
    # moves nothing, so no declared clip can vanish this way.
    "export_optimize_animation_keep_anim_object": False,
    "export_anim_slide_to_zero": False,
    "export_draco_mesh_compression_enable": False,
    "export_use_gltfpack": False,
    "export_unused_images": False,
    "export_unused_textures": False,
    "export_copyright": "",
    "will_save_settings": False,
}


def export(path, animated):
    options = dict(EXPORT_OPTIONS, export_animations=animated, filepath=path)
    known = {p.identifier for p in bpy.ops.export_scene.gltf.get_rna_type().properties}
    used = {k: v for k, v in options.items() if k in known}
    dropped = sorted(k for k in options if k not in known)
    result = bpy.ops.export_scene.gltf(**used)
    if "FINISHED" not in result:
        raise RuntimeError(f"glTF export returned {result}")
    return sorted(k for k in used if k != "filepath"), dropped


def exporter_version():
    import addon_utils
    for module in addon_utils.modules():
        if module.__name__ == "io_scene_gltf2":
            return ".".join(str(v) for v in module.bl_info.get("version", ()))
    return None


def build(spec, texture_dir, out):
    reset_scene(spec["fps"])
    asset = spec["asset_id"]
    root = new_object(asset, None, None, {"wgf_asset": asset, "wgf_format": FORMAT})
    materials = {m["id"]: make_material(m, texture_dir) for m in spec["materials"]}
    repeats = {m["id"]: (m.get("texture") or {}).get("repeat", 1.0) for m in spec["materials"]}

    parts, top_level = {}, []
    for part in spec["parts"]:
        mesh = make_mesh(part, repeats.get(part["material"], 1.0))
        if part["material"]:
            mesh.materials.append(materials[part["material"]])
        parent = parts[part["parent"]] if part["parent"] else root
        obj = new_object(part["id"], mesh, parent)
        obj.location = to_blender(part["translation"])
        obj.rotation_quaternion = quat_to_blender(part["rotation"])
        parts[part["id"]] = obj
        if not part["parent"]:
            top_level.append(obj)

    scale, offset = fit_and_pivot(spec, parts, top_level)
    if spec["animations"]:
        animate(spec, parts, top_level, scale, offset)
    lods = make_lods(spec, root, parts, top_level) if spec["lods"] else []
    collision = make_collision(spec, root, parts) if spec["collision"] else None
    lo, hi = bounds(world_vertices(parts.values()))
    used, dropped = export(out, bool(spec["animations"]))
    return {
        "fit": {"scale": round(scale, 9), "offset": [round(v, 9) for v in to_gltf(offset)]},
        "bounds": {"min": [round(v, 6) for v in to_gltf(Vector((lo.x, hi.y, lo.z)))],
                   "max": [round(v, 6) for v in to_gltf(Vector((hi.x, lo.y, hi.z)))]},
        "lods": lods,
        "collision": collision,
        "export_options": used,
        "export_options_unsupported": dropped,
    }


def main():
    options = parse_args()
    report = {"format": FORMAT, "ok": False, "blender": bpy.app.version_string,
              "exporter": None}
    try:
        report["exporter"] = exporter_version()
        with open(options["spec"], encoding="utf-8") as handle:
            spec = json.load(handle)
        if spec.get("format") != FORMAT:
            raise ValueError(f"resolved spec format {spec.get('format')!r}; this script reads "
                             f"{FORMAT}")
        report.update(build(spec, options.get("textures") or ".", options["out"]))
        report["ok"] = True
    except Exception as exc:  # the report is the interface: say what went wrong
        report["error"] = f"{type(exc).__name__}: {exc}"
        report["traceback"] = traceback.format_exc()[-4000:]
    with open(options["report"], "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, sort_keys=True)
    if not report["ok"]:
        sys.exit(3)


if __name__ == "__main__":
    main()

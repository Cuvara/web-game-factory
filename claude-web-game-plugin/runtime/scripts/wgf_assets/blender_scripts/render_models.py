"""Render GLBs to PNG contact sheets. Runs INSIDE Blender, never in the Factory's Python.

    blender --background --factory-startup -noaudio --python-exit-code 3 \
        --python render_models.py -- --job job.json --report report.json

`job.json` is `wgf_assets.render.job()` output: the models (each a GLB and its views), the
optional set lineup, the light rig, the background, the engines to try and the sample count.
Everything is glTF's frame (metres, +Y up, a model faces +Z); the importer and this script
convert to Blender's.

For every model it renders each view - a perspective camera on the view's direction, fitted
so the model's bounding box fills `margin` of the frame - to `<dir>/<id>.<view>.png` with a
transparent film, measures the alpha mask (how much of the frame the model covers, how much
of its own bounding rectangle its outline fills), and composes the views side by side on
the background into `<id>.sheet.png`. A view with `pixels` smaller than the sheet's tile
(the gameplay-size view) is rendered at that size and enlarged without smoothing, so the
sheet shows the pixels a player gets. The set lineup puts every model side by side at its
real size, on the floor, and renders it from the set's views stacked into one image.

With a `context` in the job, each model is also rendered IN CONTEXT to `<id>.context.png`:
standing on a ground plane of the play surface's colour, the player's model (when the job
names one, and the model is not the player) beside it at its real size, under the same rig,
from the game's camera, over the backdrop colour - what a player sees of it, which the model
judge reads (core/reference/model-review-rubric.yaml, `camera_view`).

Collision proxies and LOD1+ levels are hidden: they are not what a player sees. The render
is deterministic in its settings (fixed samples, a fixed seed, no denoiser, no motion blur,
the Standard view transform so the palette's colours come out as authored); the PNG bytes
are evidence for a reader, not a build output, and are not hashed.

The report is always written; on a failure it says why and Blender exits 3.
"""

import json
import math
import os
import sys
import traceback

import bpy
import numpy
from mathutils import Matrix, Vector

FORMAT = 1


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    options = dict(zip((k.lstrip("-") for k in argv[::2]), argv[1::2]))
    for required in ("job", "report"):
        if required not in options:
            raise SystemExit(f"render_models.py: --{required} is required")
    return options


def to_blender(v):
    return Vector((v[0], -v[2], v[1]))


def srgb_to_linear(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def linear(rgb):
    return [srgb_to_linear(c) for c in rgb]


# -- the scene ----------------------------------------------------------------------------------

def reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    settings = scene.view_settings
    settings.view_transform = "Standard"
    settings.look = "None"
    settings.exposure = 0.0
    settings.gamma = 1.0
    scene.render.film_transparent = True
    scene.render.use_motion_blur = False
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.image_settings.color_depth = "8"
    return scene


def world(scene, rig, background):
    """A hemisphere ambient (ground colour below the horizon, sky above) that lights the
    models, while a camera ray sees the flat background colour."""
    scene.world = bpy.data.worlds.new("rig")
    scene.world.use_nodes = True
    nodes, links = scene.world.node_tree.nodes, scene.world.node_tree.links
    for node in list(nodes):
        nodes.remove(node)
    coords = nodes.new("ShaderNodeTexCoord")
    split = nodes.new("ShaderNodeSeparateXYZ")
    ramp = nodes.new("ShaderNodeMapRange")
    ramp.inputs["From Min"].default_value = -1.0
    ramp.inputs["From Max"].default_value = 1.0
    mix = nodes.new("ShaderNodeMix")
    mix.data_type = "RGBA"
    mix.inputs["A"].default_value = linear(rig["ground"]) + [1.0]
    mix.inputs["B"].default_value = linear(rig["sky"]) + [1.0]
    ambient = nodes.new("ShaderNodeBackground")
    ambient.inputs["Strength"].default_value = rig["ambient"]
    flat = nodes.new("ShaderNodeBackground")
    flat.inputs["Color"].default_value = linear(background) + [1.0]
    path = nodes.new("ShaderNodeLightPath")
    choose = nodes.new("ShaderNodeMixShader")
    out = nodes.new("ShaderNodeOutputWorld")
    links.new(coords.outputs["Generated"], split.inputs["Vector"])
    links.new(split.outputs["Z"], ramp.inputs["Value"])
    links.new(ramp.outputs["Result"], mix.inputs["Factor"])
    links.new(mix.outputs["Result"], ambient.inputs["Color"])
    links.new(path.outputs["Is Camera Ray"], choose.inputs["Fac"])
    links.new(ambient.outputs["Background"], choose.inputs[1])
    links.new(flat.outputs["Background"], choose.inputs[2])
    links.new(choose.outputs["Shader"], out.inputs["Surface"])


def sun(name, light):
    data = bpy.data.lights.new(name, "SUN")
    data.color = linear(light["color"])
    data.energy = light["strength"]
    data.angle = math.radians(2.0)
    obj = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(obj)
    # A sun shines along its local -Z: from where the rig puts it, toward the model.
    obj.rotation_euler = (-to_blender(light["direction"])).to_track_quat("-Z", "Y").to_euler()
    return obj


def engine(scene, names, samples):
    """The first engine of `names` this Blender has, configured deterministically."""
    available = {item.identifier for item in
                 bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items}
    for name in names:
        if name not in available:
            continue
        scene.render.engine = name
        if name.startswith("BLENDER_EEVEE"):
            scene.eevee.taa_render_samples = samples
        elif name == "CYCLES":
            scene.cycles.device = "CPU"
            scene.cycles.samples = samples
            scene.cycles.seed = 0
            scene.cycles.use_animated_seed = False
            scene.cycles.use_denoising = False
        elif name == "BLENDER_WORKBENCH":
            shading = scene.display.shading
            shading.light = "STUDIO"
            shading.color_type = "MATERIAL"
        return name
    raise RuntimeError(f"none of the render engines {names} exists in this Blender")


# -- the models ---------------------------------------------------------------------------------

def hidden(obj):
    """A collision proxy or a LOD level above 0: not what a player sees."""
    if obj.get("wgf_role") == "collision" or obj.name.endswith("_collision"):
        return True
    lod = obj.get("wgf_lod")
    return isinstance(lod, int) and lod > 0


def import_model(path):
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=path)
    objects = [o for o in bpy.data.objects if o not in before]
    roots = [o for o in objects if o.parent is None or o.parent not in objects]
    visible = []
    for obj in objects:
        node, hide = obj, False
        while node is not None:
            if hidden(node):
                hide = True
                break
            node = node.parent
        obj.hide_render = hide
        if not hide and obj.type == "MESH":
            visible.append(obj)
    return {"objects": objects, "roots": roots, "meshes": visible}


def bounds(meshes):
    bpy.context.view_layer.update()
    points = [obj.matrix_world @ Vector(corner) for obj in meshes for corner in obj.bound_box]
    if not points:
        return Vector((0, 0, 0)), Vector((0, 0, 0))
    lo = Vector([min(p[i] for p in points) for i in range(3)])
    hi = Vector([max(p[i] for p in points) for i in range(3)])
    return lo, hi


def vertices(meshes, limit=40000):
    """The meshes' vertices in world space (every n-th past `limit`): what framing fits."""
    bpy.context.view_layer.update()
    points = [obj.matrix_world @ v.co for obj in meshes for v in obj.data.vertices]
    step = max(1, len(points) // limit)
    return points[::step]


def place_camera(camera, lo, hi, view, aspect, points=None):
    """Aim along the view's direction at the box's centre, at the distance that fits the
    points (the vertices; else the box's eight corners) inside `margin` of the frame - exact
    for a perspective camera."""
    centre = (lo + hi) / 2
    direction = to_blender(view["direction"]).normalized()
    forward = -direction
    up_hint = to_blender(view.get("up") or [0, 1, 0])
    right = forward.cross(up_hint)
    if right.length < 1e-6:
        right = forward.cross(Vector((0, 1, 0)))
    right.normalize()
    up = right.cross(forward).normalized()
    fov = math.radians(view.get("fov", 30.0))
    camera.data.type = "PERSP"
    camera.data.sensor_fit = "VERTICAL"
    camera.data.angle = fov
    tan_v = math.tan(fov / 2) * view.get("margin", 0.86)
    tan_h = tan_v * aspect
    corners = ([p - centre for p in points] if points else
               [Vector((x, y, z)) - centre for x in (lo.x, hi.x) for y in (lo.y, hi.y)
                for z in (lo.z, hi.z)])
    distance = 1e-3
    for p in corners:
        depth_offset = p.dot(forward)
        distance = max(distance,
                       abs(p.dot(right)) / tan_h - depth_offset,
                       abs(p.dot(up)) / tan_v - depth_offset,
                       -depth_offset + 1e-3)
    camera.location = centre - forward * distance
    # Centre the projected outline with the lens shift (in units of the frame's larger side),
    # so a model whose bulk is off its box centre is not pushed to an edge.
    full_v = math.tan(fov / 2)
    full_h = full_v * aspect
    xs = [p.dot(right) / ((distance + p.dot(forward)) * full_h) for p in corners]
    ys = [p.dot(up) / ((distance + p.dot(forward)) * full_v) for p in corners]
    larger = max(aspect, 1.0)
    camera.data.shift_x = (min(xs) + max(xs)) / 4 * (aspect / larger)
    camera.data.shift_y = (min(ys) + max(ys)) / 4 / larger
    basis = Matrix((right, up, -forward)).transposed()
    camera.rotation_euler = basis.to_euler()
    camera.data.clip_start = max(1e-3, distance / 1000)
    camera.data.clip_end = distance * 10 + (hi - lo).length * 4


def render(scene, camera, path, width, height):
    scene.camera = camera
    scene.render.resolution_x = width
    scene.render.resolution_y = height
    scene.render.filepath = path
    bpy.ops.render.render(write_still=True)
    return read(path)


def read(path):
    image = bpy.data.images.load(path, check_existing=False)
    width, height = image.size
    pixels = numpy.empty(width * height * 4, dtype=numpy.float32)
    image.pixels.foreach_get(pixels)
    bpy.data.images.remove(image)
    return pixels.reshape(height, width, 4)  # rows bottom to top, straight alpha


def measure(pixels):
    """{coverage: share of the frame the model covers, fill: share of its own bounding
    rectangle} from the alpha mask."""
    mask = pixels[:, :, 3] > 0.5
    covered = int(mask.sum())
    if not covered:
        return {"coverage": 0.0, "fill": None}
    rows = numpy.where(mask.any(axis=1))[0]
    cols = numpy.where(mask.any(axis=0))[0]
    box = (rows[-1] - rows[0] + 1) * (cols[-1] - cols[0] + 1)
    return {"coverage": round(covered / mask.size, 4), "fill": round(covered / box, 4)}


def enlarge(pixels, size):
    """Nearest-neighbour enlargement to size x size: the gameplay-size pixels, made visible."""
    height, width = pixels.shape[:2]
    rows = (numpy.arange(size) * height // size).clip(0, height - 1)
    cols = (numpy.arange(size) * width // size).clip(0, width - 1)
    return pixels[rows][:, cols]


def compose(tiles, background, path, gutter=6):
    """Tiles (each h x w x 4, straight alpha) side by side over the background colour."""
    height = max(t.shape[0] for t in tiles)
    width = sum(t.shape[1] for t in tiles) + gutter * (len(tiles) + 1)
    total = height + 2 * gutter
    canvas = numpy.empty((total, width, 4), dtype=numpy.float32)
    canvas[:, :, :3] = numpy.array([background[0] * 0.55, background[1] * 0.55,
                                    background[2] * 0.55 + 0.04], dtype=numpy.float32)
    canvas[:, :, 3] = 1.0
    x = gutter
    bg = numpy.array(background, dtype=numpy.float32)
    for tile in tiles:
        h, w = tile.shape[:2]
        alpha = tile[:, :, 3:4]
        y = gutter + (height - h) // 2
        canvas[y:y + h, x:x + w, :3] = tile[:, :, :3] * alpha + bg * (1 - alpha)
        x += w + gutter
    save(canvas, path)


def stack(images, path):
    width = max(i.shape[1] for i in images)
    canvas = numpy.concatenate([numpy.pad(i, ((0, 0), (0, width - i.shape[1]), (0, 0)))
                                for i in reversed(images)], axis=0)
    save(canvas, path)


def save(canvas, path):
    height, width = canvas.shape[:2]
    image = bpy.data.images.new(os.path.basename(path), width, height, alpha=True)
    image.pixels.foreach_set(numpy.ascontiguousarray(canvas, dtype=numpy.float32).ravel())
    image.filepath_raw = path
    image.file_format = "PNG"
    image.save()
    bpy.data.images.remove(image)


def ground(colour, size, height):
    """A square plane of the play surface's colour, `size` metres across, at Blender z
    `height` - what the game's camera sees behind a model standing on the play."""
    mesh = bpy.data.meshes.new("context-ground")
    half = size / 2.0
    mesh.from_pydata([(-half, -half, height), (half, -half, height), (half, half, height),
                      (-half, half, height)], [], [(0, 1, 2, 3)])
    material = bpy.data.materials.new("context-ground")
    material.use_nodes = True
    shader = material.node_tree.nodes.get("Principled BSDF")
    shader.inputs["Base Color"].default_value = linear(colour) + [1.0]
    shader.inputs["Roughness"].default_value = 0.9
    mesh.materials.append(material)
    obj = bpy.data.objects.new("context-ground", mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def flatten(pixels, background):
    alpha = pixels[:, :, 3:4]
    out = pixels.copy()
    out[:, :, :3] = pixels[:, :, :3] * alpha + numpy.array(background, numpy.float32) * (1 - alpha)
    out[:, :, 3] = 1.0
    return out


# -- the job ------------------------------------------------------------------------------------

def in_context(scene, camera, model, player, context, path, tile):
    """The model on the play surface beside the player, from the game's camera, flattened
    over the backdrop: `path`, and how much of the frame the model covers."""
    lo, hi = bounds(model["meshes"])
    beside = player is not None and model["spec"]["id"] != player["spec"]["id"]
    moved = []
    if beside:
        p_lo, p_hi = bounds(player["meshes"])
        width = (hi.x - lo.x) / 2 + (p_hi.x - p_lo.x) / 2
        gap = 0.25 * max(hi.x - lo.x, p_hi.x - p_lo.x, 0.1)
        shift = Vector(((lo.x + hi.x) / 2 - (p_lo.x + p_hi.x) / 2 - width - gap,
                        (lo.y + hi.y) / 2 - (p_lo.y + p_hi.y) / 2, lo.z - p_lo.z))
        for root in player["roots"]:
            moved.append((root, root.location.copy()))
            root.location = root.location + shift
    isolate_for_context(model, player if beside else None)
    meshes = model["meshes"] + (player["meshes"] if beside else [])
    box_lo, box_hi = bounds(meshes)
    span = max((box_hi - box_lo).length, 0.5)
    plane = ground(context["surface"], span * 40.0, lo.z - 1e-3 * span)
    view = dict(context["view"], margin=context["view"].get("margin", 0.7))
    place_camera(camera, box_lo, box_hi, view, 1.0, vertices(meshes))
    camera.data.clip_end = max(camera.data.clip_end, span * 80.0)
    pixels = render(scene, camera, path, tile, tile)
    save(flatten(pixels, context["backdrop"]), path)
    bpy.data.objects.remove(plane, do_unlink=True)
    for root, location in moved:
        root.location = location
    return {"path": path, "beside": model_id(player) if beside else None}


def model_id(model):
    return model["spec"]["id"]


def isolate_for_context(model, player):
    for obj in bpy.data.objects:
        if obj.type in ("MESH", "EMPTY") and obj.name != "context-ground":
            obj.hide_render = True
    for group in [model] + ([player] if player else []):
        for obj in group["objects"]:
            node, hide = obj, False
            while node is not None:
                if hidden(node):
                    hide = True
                    break
                node = node.parent
            obj.hide_render = hide


def run(job):
    scene = reset()
    used = engine(scene, job["engines"], job["samples"])
    world(scene, job["rig"], job["background"])
    for name in ("key", "rim"):
        if job["rig"].get(name):
            sun(name, job["rig"][name])
    camera = bpy.data.objects.new("camera", bpy.data.cameras.new("camera"))
    scene.collection.objects.link(camera)
    tile = job["tile"]
    background = job["background"]

    models = []
    for spec in job["models"]:
        model = import_model(spec["glb"])
        model.update(spec=spec)
        models.append(model)
    context = job.get("context")
    player = None
    if context and context.get("player"):
        player = import_model(context["player"])
        player.update(spec={"id": context.get("player_id") or "player"})
    own_hidden = {id(m): {o.name: o.hide_render for o in m["objects"]}
                  for m in models + ([player] if player else [])}

    def isolate(keep, also=()):
        for model in models + ([player] if player else []):
            for obj in model["objects"]:
                shown = keep is None and model is not player or model is keep \
                    or model in also
                obj.hide_render = own_hidden[id(model)][obj.name] if shown else True

    report = {"engine": used, "models": {}}
    for model in models:
        spec = model["spec"]
        isolate(model)
        lo, hi = bounds(model["meshes"])
        points = vertices(model["meshes"])
        os.makedirs(spec["dir"], exist_ok=True)
        views, tiles = {}, []
        for view in spec["views"]:
            pixels_size = int(view.get("pixels") or tile)
            path = os.path.join(spec["dir"], f"{spec['id']}.{view['name']}.png")
            place_camera(camera, lo, hi, view, 1.0, points)
            pixels = render(scene, camera, path, pixels_size, pixels_size)
            views[view["name"]] = dict(measure(pixels), path=path, pixels=pixels_size)
            tiles.append(pixels if pixels_size == tile else enlarge(pixels, tile))
        compose(tiles, background, spec["sheet"])
        report["models"][spec["id"]] = {"sheet": spec["sheet"], "views": views,
                                        "bounds": {"min": list(lo), "max": list(hi)}}
        if context:
            path = os.path.join(spec["dir"], f"{spec['id']}.context.png")
            report["models"][spec["id"]]["context"] = in_context(
                scene, camera, model, player, context, path, tile)

    lineup = job.get("set")
    if lineup and models:
        isolate(None)
        gap = lineup.get("gap", 0.35)
        x = 0.0
        for model in models:
            lo, hi = bounds(model["meshes"])
            shift = Vector((x - lo.x, 0.0, -lo.z))
            for root in model["roots"]:
                root.location = root.location + shift
            x += (hi.x - lo.x) + gap * max(0.5, hi.z - lo.z)
        meshes = [m for model in models for m in model["meshes"]]
        lo, hi = bounds(meshes)
        everything = vertices(meshes)
        width = int(lineup.get("width") or tile * 2)
        height = int(lineup.get("height") or tile)
        images = []
        for view in lineup["views"]:
            path = os.path.splitext(lineup["out"])[0] + f".{view['name']}.png"
            place_camera(camera, lo, hi, view, width / height, everything)
            images.append(flatten(render(scene, camera, path, width, height), background))
        stack(images, lineup["out"])
        report["set"] = {"path": lineup["out"], "order": [m["spec"]["id"] for m in models]}
    return report


def main():
    options = parse_args()
    report = {"format": FORMAT, "ok": False, "blender": bpy.app.version_string}
    try:
        with open(options["job"], encoding="utf-8") as handle:
            job = json.load(handle)
        if job.get("format") != FORMAT:
            raise ValueError(f"render job format {job.get('format')!r}; this script reads "
                             f"{FORMAT}")
        report.update(run(job))
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

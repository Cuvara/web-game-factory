"""What a GLB (or .gltf) actually contains, and what is wrong with it, without Blender.

`formats.sniff` says a file is a GLB: magic, version, length, a JSON chunk declaring glTF 2.0.
This reads the rest - every index, every buffer range, the node tree, transforms, meshes,
materials, embedded images, animations and skins - because a file can pass the sniff and
still load as an empty scene, a model 100x too big, or a clip lookup that returns nothing.

    inspection = inspect(data, name="public/assets/models/car.glb")
    inspection.findings   [(code, severity, message)]   codes are asset-manifest issue codes
    inspection.summary    the manifest item's `model` block (None when unreadable)

    check_expectations(inspection.summary, expectations(spec, kind_policy), data_bytes)
                          the spec's declared clips, LODs, collision proxy, fitted size,
                          pivot and budgets, checked against what the file holds

Roles are read the way the build script writes them and the way hand-made assets usually
name them: node `extras.wgf_role == "collision"` or a name ending `_collision` (or starting
`UCX_`/`COL_`) is a collision proxy; `extras.wgf_lod = n` or a name ending `_LOD<n>` is a
level of detail. Only LOD0 and nodes outside those subtrees count as the visual model -
triangles, bounds and dimensions are the visual model's, at rest.

Standard library only; one pass over the JSON plus the POSITION ranges it needs.
"""

import base64
import json
import math
import re
import struct

from . import formats

__all__ = ["GltfError", "Inspection", "inspect", "check_expectations", "load",
           "SUPPORTED_EXTENSIONS", "DECODER_EXTENSIONS"]

# What three.js's GLTFLoader (r170, the pinned template's) reads with no extra setup.
SUPPORTED_EXTENSIONS = frozenset({
    "KHR_materials_emissive_strength", "KHR_materials_unlit", "KHR_materials_clearcoat",
    "KHR_materials_ior", "KHR_materials_specular", "KHR_materials_transmission",
    "KHR_materials_volume", "KHR_materials_iridescence", "KHR_materials_sheen",
    "KHR_materials_anisotropy", "KHR_materials_dispersion", "KHR_materials_bump",
    "KHR_texture_transform", "KHR_mesh_quantization", "KHR_lights_punctual",
    "EXT_mesh_gpu_instancing", "EXT_texture_webp", "EXT_texture_avif",
    "EXT_materials_bump", "KHR_animation_pointer",
})
# Loadable only when the game configures a decoder - payload that counts against the bundle.
DECODER_EXTENSIONS = {
    "KHR_draco_mesh_compression": "DRACOLoader",
    "KHR_texture_basisu": "KTX2Loader",
    "EXT_meshopt_compression": "MeshoptDecoder",
}

COMPONENT_SIZE = {5120: 1, 5121: 1, 5122: 2, 5123: 2, 5125: 4, 5126: 4}
TYPE_COUNT = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT2": 4, "MAT3": 9, "MAT4": 16}
TARGET_PATHS = {"translation", "rotation", "scale", "weights", "pointer"}
LOD_NAME = re.compile(r"_LOD(\d+)$", re.I)
COLLISION_NAME = re.compile(r"(_collision$|^UCX_|^COL_)", re.I)
# A visual model bigger than this is almost always authored in the wrong unit.
MAX_EXTENT = {"environment": 2000.0}
DEFAULT_MAX_EXTENT = 200.0
MIN_EXTENT = 0.005
# A collision proxy heavier than this is a visual mesh in disguise.
MAX_COLLISION_TRIANGLES = 256


class GltfError(ValueError):
    """The bytes are not a glTF 2.0 document this module can read at all."""


def load(data):
    """(document, bin chunk bytes or None) from GLB or .gltf JSON bytes."""
    if data[:4] == b"glTF":
        if len(data) < 20:
            raise GltfError("GLB shorter than its header")
        version, length = struct.unpack("<II", data[4:12])
        if version != 2:
            raise GltfError(f"GLB container version {version}; expected 2")
        if length != len(data):
            raise GltfError(f"GLB header says {length} bytes; the file has {len(data)}")
        offset, document, binary = 12, None, None
        while offset + 8 <= len(data):
            chunk_length, chunk_type = struct.unpack("<I4s", data[offset:offset + 8])
            body = data[offset + 8:offset + 8 + chunk_length]
            if len(body) != chunk_length:
                raise GltfError("GLB chunk runs past the end of the file")
            if chunk_type == b"JSON" and document is None:
                try:
                    document = json.loads(body.decode("utf-8"))
                except (UnicodeDecodeError, ValueError) as exc:
                    raise GltfError(f"GLB JSON chunk is not JSON: {exc}")
            elif chunk_type == b"BIN\x00" and binary is None:
                binary = body
            offset += 8 + chunk_length
        if document is None:
            raise GltfError("GLB has no JSON chunk")
    else:
        try:
            document = json.loads(data.decode("utf-8-sig"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise GltfError(f"not GLB and not glTF JSON: {exc}")
        binary = None
    if not isinstance(document, dict) or (document.get("asset") or {}).get("version") != "2.0":
        raise GltfError("asset.version is not \"2.0\"")
    return document, binary


def node_names(data):
    """The names of a glTF's nodes, in document order (unnamed nodes skipped); [] when the
    bytes are not a glTF this module reads. What game code that composes a model by node
    name looks up (three.js `getObjectByName`)."""
    try:
        document, _binary = load(data)
    except GltfError:
        return []
    return [node["name"] for node in document.get("nodes") or []
            if isinstance(node, dict) and isinstance(node.get("name"), str) and node["name"]]


# -- small matrix helpers (column-major 4x4, as glTF stores them) -----------------------------

IDENTITY = (1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0)


def _multiply(a, b):
    return tuple(sum(a[k * 4 + r] * b[c * 4 + k] for k in range(4))
                 for c in range(4) for r in range(4))


def _trs(node):
    if "matrix" in node:
        return tuple(float(v) for v in node["matrix"])
    tx, ty, tz = node.get("translation", (0, 0, 0))
    x, y, z, w = node.get("rotation", (0, 0, 0, 1))
    sx, sy, sz = node.get("scale", (1, 1, 1))
    rot = (1 - 2 * (y * y + z * z), 2 * (x * y + z * w), 2 * (x * z - y * w),
           2 * (x * y - z * w), 1 - 2 * (x * x + z * z), 2 * (y * z + x * w),
           2 * (x * z + y * w), 2 * (y * z - x * w), 1 - 2 * (x * x + y * y))
    return (rot[0] * sx, rot[1] * sx, rot[2] * sx, 0.0,
            rot[3] * sy, rot[4] * sy, rot[5] * sy, 0.0,
            rot[6] * sz, rot[7] * sz, rot[8] * sz, 0.0,
            float(tx), float(ty), float(tz), 1.0)


def _apply(m, p):
    return tuple(m[r] * p[0] + m[4 + r] * p[1] + m[8 + r] * p[2] + m[12 + r] for r in range(3))


def _decimal(value):
    """A measurement as the manifest stores it: 4 decimals (0.1 mm, 0.1 ms).

    Not 6: the artifact hash (wgflib.hashing) refuses any float Python would print in
    exponent form, which round(x, 6) produces for anything under 1e-4 (5e-05)."""
    return round(value, 4) + 0.0


def _finite(values):
    return all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
               for v in values)


class Inspection:
    def __init__(self):
        self.findings = []
        self.summary = None
        self.document = None

    def add(self, code, severity, message):
        self.findings.append((code, severity, message))

    @property
    def errors(self):
        return [f for f in self.findings if f[1] == "error"]


def _ref(doc, key, index):
    items = doc.get(key)
    return isinstance(index, int) and not isinstance(index, bool) and isinstance(items, list) \
        and 0 <= index < len(items)


def _check_refs(doc, out, name):
    """Every index points at something. Returns False when the document is too broken to walk."""
    bad = []

    def need(key, index, where):
        if not _ref(doc, key, index):
            bad.append(f"{where} -> {key}[{index}]")

    for i, scene in enumerate(doc.get("scenes") or []):
        for n in scene.get("nodes") or []:
            need("nodes", n, f"scenes[{i}]")
    if "scene" in doc:
        need("scenes", doc["scene"], "scene")
    for i, node in enumerate(doc.get("nodes") or []):
        for c in node.get("children") or []:
            need("nodes", c, f"nodes[{i}].children")
        for key in ("mesh", "skin", "camera"):
            if key in node:
                need(f"{key}es" if key == "mesh" else f"{key}s", node[key], f"nodes[{i}].{key}")
    for i, mesh in enumerate(doc.get("meshes") or []):
        for j, prim in enumerate(mesh.get("primitives") or []):
            where = f"meshes[{i}].primitives[{j}]"
            for attr, acc in (prim.get("attributes") or {}).items():
                need("accessors", acc, f"{where}.{attr}")
            if "indices" in prim:
                need("accessors", prim["indices"], f"{where}.indices")
            if "material" in prim:
                need("materials", prim["material"], f"{where}.material")
            if "POSITION" not in (prim.get("attributes") or {}):
                bad.append(f"{where} has no POSITION")
    for i, material in enumerate(doc.get("materials") or []):
        pbr = material.get("pbrMetallicRoughness") or {}
        slots = [pbr.get("baseColorTexture"), pbr.get("metallicRoughnessTexture"),
                 material.get("normalTexture"), material.get("occlusionTexture"),
                 material.get("emissiveTexture")]
        for slot in slots:
            if isinstance(slot, dict):
                need("textures", slot.get("index"), f"materials[{i}]")
    for i, texture in enumerate(doc.get("textures") or []):
        if "source" in texture:
            need("images", texture["source"], f"textures[{i}].source")
        if "sampler" in texture:
            need("samplers", texture["sampler"], f"textures[{i}].sampler")
    for i, accessor in enumerate(doc.get("accessors") or []):
        if "bufferView" in accessor:
            need("bufferViews", accessor["bufferView"], f"accessors[{i}]")
    for i, view in enumerate(doc.get("bufferViews") or []):
        need("buffers", view.get("buffer"), f"bufferViews[{i}]")
    for i, image in enumerate(doc.get("images") or []):
        if "bufferView" in image:
            need("bufferViews", image["bufferView"], f"images[{i}]")
    for i, skin in enumerate(doc.get("skins") or []):
        for j in skin.get("joints") or []:
            need("nodes", j, f"skins[{i}].joints")
        if "inverseBindMatrices" in skin:
            need("accessors", skin["inverseBindMatrices"], f"skins[{i}].inverseBindMatrices")
        if "skeleton" in skin:
            need("nodes", skin["skeleton"], f"skins[{i}].skeleton")
    for i, anim in enumerate(doc.get("animations") or []):
        samplers = anim.get("samplers") or []
        for j, sampler in enumerate(samplers):
            need("accessors", sampler.get("input"), f"animations[{i}].samplers[{j}].input")
            need("accessors", sampler.get("output"), f"animations[{i}].samplers[{j}].output")
        for j, channel in enumerate(anim.get("channels") or []):
            if not (isinstance(channel.get("sampler"), int)
                    and 0 <= channel["sampler"] < len(samplers)):
                bad.append(f"animations[{i}].channels[{j}] -> sampler {channel.get('sampler')}")
            target = channel.get("target") or {}
            if "node" in target:
                need("nodes", target["node"], f"animations[{i}].channels[{j}].target")
    for problem in bad[:10]:
        out.add("model-invalid", "error", f"{name}: broken reference: {problem}")
    if len(bad) > 10:
        out.add("model-invalid", "error", f"{name}: ... and {len(bad) - 10} more broken references")
    return not bad


def _check_buffers(doc, binary, out, name):
    buffers = doc.get("buffers") or []
    lengths = []
    for i, buffer in enumerate(buffers):
        uri = buffer.get("uri")
        length = buffer.get("byteLength")
        if not isinstance(length, int) or length < 0:
            out.add("model-invalid", "error", f"{name}: buffers[{i}] has no valid byteLength")
            lengths.append(0)
            continue
        if uri is None:
            if i != 0 or binary is None:
                out.add("model-invalid", "error",
                        f"{name}: buffers[{i}] has no uri and no GLB BIN chunk")
            elif len(binary) < length:
                out.add("model-invalid", "error",
                        f"{name}: BIN chunk is {len(binary)} bytes; buffers[0] needs {length}")
        elif uri.startswith("data:"):
            out.add("too-large", "warning",
                    f"{name}: buffers[{i}] is a base64 data URI (+33% size); export GLB")
        else:
            out.add("model-external-reference", "error",
                    f"{name}: buffers[{i}] references external file {uri!r}, which no manifest "
                    f"item carries; export a self-contained GLB")
        lengths.append(length)
    for i, view in enumerate(doc.get("bufferViews") or []):
        b = view.get("buffer")
        end = (view.get("byteOffset") or 0) + (view.get("byteLength") or 0)
        if isinstance(b, int) and 0 <= b < len(lengths) and end > lengths[b]:
            out.add("model-invalid", "error",
                    f"{name}: bufferViews[{i}] ends at {end}, past buffers[{b}] "
                    f"({lengths[b]} bytes)")
    views = doc.get("bufferViews") or []
    for i, accessor in enumerate(doc.get("accessors") or []):
        count = accessor.get("count")
        ctype, atype = accessor.get("componentType"), accessor.get("type")
        if not isinstance(count, int) or count < 0 or ctype not in COMPONENT_SIZE \
                or atype not in TYPE_COUNT:
            out.add("model-invalid", "error",
                    f"{name}: accessors[{i}] has an invalid count, componentType or type")
            continue
        v = accessor.get("bufferView")
        if not isinstance(v, int) or not 0 <= v < len(views) or count == 0:
            continue
        view = views[v]
        element = COMPONENT_SIZE[ctype] * TYPE_COUNT[atype]
        stride = view.get("byteStride") or element
        need = (accessor.get("byteOffset") or 0) + stride * (count - 1) + element
        if need > (view.get("byteLength") or 0):
            out.add("model-invalid", "error",
                    f"{name}: accessors[{i}] reads {need} bytes of a {view.get('byteLength')}-byte "
                    f"bufferView")


def _view_bytes(doc, binary, view_index):
    view = doc["bufferViews"][view_index]
    if view.get("buffer") != 0 or binary is None:
        return None
    start = view.get("byteOffset") or 0
    return binary[start:start + (view.get("byteLength") or 0)]


def _positions(doc, binary, accessor_index):
    """The float positions of a POSITION accessor, or None when they cannot be read plainly
    (not float, sparse, no buffer view, or out of range)."""
    accessor = doc["accessors"][accessor_index]
    if accessor.get("componentType") != 5126 or "bufferView" not in accessor \
            or "sparse" in accessor or binary is None:
        return None
    data = _view_bytes(doc, binary, accessor["bufferView"])
    if data is None:
        return None
    stride = doc["bufferViews"][accessor["bufferView"]].get("byteStride") or 12
    offset = accessor.get("byteOffset") or 0
    count = accessor.get("count", 0)
    if count and offset + (count - 1) * stride + 12 > len(data):
        return None
    points = [struct.unpack_from("<fff", data, offset + i * stride) for i in range(count)]
    return points if points and _finite([c for p in points for c in p]) else None


def _positions_range(doc, binary, accessor_index):
    """(min, max) of a POSITION accessor: its declared min/max, else read from the buffer."""
    accessor = doc["accessors"][accessor_index]
    lo, hi = accessor.get("min"), accessor.get("max")
    if isinstance(lo, list) and isinstance(hi, list) and len(lo) == 3 and len(hi) == 3 \
            and _finite(lo + hi):
        return lo, hi
    points = _positions(doc, binary, accessor_index)
    if not points:
        return None
    return ([min(p[k] for p in points) for k in range(3)],
            [max(p[k] for p in points) for k in range(3)])


def _primitive_triangles(doc, prim):
    mode = prim.get("mode", 4)
    if "indices" in prim:
        count = doc["accessors"][prim["indices"]].get("count", 0)
    else:
        count = doc["accessors"][prim["attributes"]["POSITION"]].get("count", 0)
    if mode == 4:
        return count // 3
    if mode in (5, 6):
        return max(0, count - 2)
    return 0


def _images(doc, binary, out, name):
    textures = []
    for i, image in enumerate(doc.get("images") or []):
        uri = image.get("uri")
        data = None
        if uri is not None:
            if uri.startswith("data:"):
                try:
                    data = base64.b64decode(uri.split(",", 1)[1])
                except (IndexError, ValueError):
                    out.add("model-invalid", "error", f"{name}: images[{i}] data URI is corrupt")
                    continue
                out.add("too-large", "warning",
                        f"{name}: images[{i}] is a base64 data URI (+33% size)")
            else:
                out.add("model-external-reference", "error",
                        f"{name}: images[{i}] references external file {uri!r}, which no "
                        f"manifest item carries; embed it in the GLB")
                continue
        elif "bufferView" in image:
            data = _view_bytes(doc, binary, image["bufferView"])
        if not data:
            out.add("model-invalid", "error", f"{name}: images[{i}] has no data")
            continue
        found = formats.sniff(data)
        if found is None or found.format not in ("png", "jpeg", "webp", "ktx2"):
            out.add("model-invalid", "error",
                    f"{name}: images[{i}] is not a PNG, JPEG, WebP or KTX2 image")
            continue
        mime = image.get("mimeType")
        expected = {"png": "image/png", "jpeg": "image/jpeg", "webp": "image/webp",
                    "ktx2": "image/ktx2"}[found.format]
        if mime and mime != expected:
            out.add("model-invalid", "warning",
                    f"{name}: images[{i}] declares {mime} but is {found.format}")
        entry = {"format": found.format}
        if found.width:
            entry["width"], entry["height"] = found.width, found.height
            if not (formats.is_power_of_two(found.width)
                    and formats.is_power_of_two(found.height)):
                out.add("not-power-of-two", "warning",
                        f"{name}: images[{i}] is {found.width}x{found.height}; mipmaps and GPU "
                        f"compression want powers of two")
        textures.append(entry)
    return textures


def _tree(doc, out, name):
    """(parent of each node, scene roots) - or None when the hierarchy is not a forest."""
    nodes = doc.get("nodes") or []
    parent = [None] * len(nodes)
    ok = True
    for i, node in enumerate(nodes):
        for c in node.get("children") or []:
            if parent[c] is not None:
                out.add("model-invalid", "error",
                        f"{name}: nodes[{c}] has two parents ({parent[c]} and {i})")
                ok = False
            parent[c] = i
    for i in range(len(nodes)):
        seen, node = set(), i
        while node is not None:
            if node in seen:
                out.add("model-invalid", "error", f"{name}: the node hierarchy has a cycle at "
                                                   f"nodes[{i}]")
                return None
            seen.add(node)
            node = parent[node]
    if not ok:
        return None
    scene_index = doc.get("scene", 0)
    scenes = doc.get("scenes") or []
    if not scenes:
        out.add("model-invalid", "error", f"{name}: no scene: a loader shows nothing")
        return None
    roots = list(scenes[scene_index].get("nodes") or []) if 0 <= scene_index < len(scenes) else []
    for r in roots:
        if parent[r] is not None:
            out.add("model-invalid", "error",
                    f"{name}: scene root nodes[{r}] is also a child of nodes[{parent[r]}]")
            return None
    if not roots:
        out.add("model-invalid", "error", f"{name}: the default scene has no nodes")
        return None
    return parent, roots


def _transforms(doc, out, name):
    for i, node in enumerate(doc.get("nodes") or []):
        label = node.get("name") or f"nodes[{i}]"
        if "matrix" in node:
            m = node["matrix"]
            if not (isinstance(m, list) and len(m) == 16 and _finite(m)):
                out.add("model-transform", "error", f"{name}: {label}: matrix is not 16 numbers")
            elif any(k in node for k in ("translation", "rotation", "scale")):
                out.add("model-transform", "error",
                        f"{name}: {label}: has both a matrix and TRS")
            continue
        t, r, s = node.get("translation"), node.get("rotation"), node.get("scale")
        if t is not None and not (isinstance(t, list) and len(t) == 3 and _finite(t)):
            out.add("model-transform", "error", f"{name}: {label}: invalid translation")
        if r is not None:
            if not (isinstance(r, list) and len(r) == 4 and _finite(r)):
                out.add("model-transform", "error", f"{name}: {label}: invalid rotation")
            elif abs(math.sqrt(sum(v * v for v in r)) - 1) > 1e-3:
                out.add("model-transform", "error",
                        f"{name}: {label}: rotation is not a unit quaternion")
        if s is not None:
            if not (isinstance(s, list) and len(s) == 3 and _finite(s)):
                out.add("model-transform", "error", f"{name}: {label}: invalid scale")
            elif any(v == 0 for v in s):
                out.add("model-transform", "error",
                        f"{name}: {label}: zero scale collapses it to nothing")
            elif any(v < 0 for v in s):
                out.add("model-transform", "warning",
                        f"{name}: {label}: negative scale mirrors it and flips its faces")


def _animations(doc, out, name):
    clips, names = [], {}
    accessors = doc.get("accessors") or []
    nodes = doc.get("nodes") or []
    for i, anim in enumerate(doc.get("animations") or []):
        clip_name = anim.get("name")
        label = clip_name or f"animations[{i}]"
        if not clip_name:
            out.add("animation-invalid", "warning",
                    f"{name}: {label} has no name; code cannot look it up")
        elif clip_name in names:
            out.add("animation-invalid", "error",
                    f"{name}: two animations named {clip_name!r}; a lookup by name gets one")
        names.setdefault(clip_name, i)
        samplers = anim.get("samplers") or []
        channels = anim.get("channels") or []
        if not channels:
            out.add("animation-invalid", "error", f"{name}: {label} has no channels")
        duration, targets = 0.0, set()
        for j, channel in enumerate(channels):
            target = channel.get("target") or {}
            path = target.get("path")
            if path not in TARGET_PATHS:
                out.add("animation-invalid", "error",
                        f"{name}: {label} channel {j} targets unknown path {path!r}")
            key = (target.get("node"), path)
            if key in targets:
                out.add("animation-invalid", "error",
                        f"{name}: {label} animates {key} twice")
            targets.add(key)
            if path == "weights" and isinstance(target.get("node"), int):
                mesh = nodes[target["node"]].get("mesh")
                if mesh is None or not any(p.get("targets") for p in
                                           doc["meshes"][mesh].get("primitives") or []):
                    out.add("animation-invalid", "error",
                            f"{name}: {label} animates weights of a node with no morph targets")
            sampler = samplers[channel["sampler"]]
            inp, outp = accessors[sampler["input"]], accessors[sampler["output"]]
            if inp.get("type") != "SCALAR" or inp.get("componentType") != 5126:
                out.add("animation-invalid", "error",
                        f"{name}: {label} channel {j}: input is not float seconds")
                continue
            interpolation = sampler.get("interpolation", "LINEAR")
            factor = 3 if interpolation == "CUBICSPLINE" else 1
            if path in ("translation", "rotation", "scale") and \
                    outp.get("count") != inp.get("count", 0) * factor:
                out.add("animation-invalid", "error",
                        f"{name}: {label} channel {j}: {outp.get('count')} outputs for "
                        f"{inp.get('count')} keys ({interpolation})")
            high = inp.get("max")
            if isinstance(high, list) and high and _finite(high):
                duration = max(duration, float(high[0]))
            else:
                out.add("animation-invalid", "warning",
                        f"{name}: {label} channel {j}: input has no max; duration unknown")
        clips.append({"name": clip_name or f"animation-{i}", "duration": _decimal(duration),
                      "channels": len(channels)})
    return clips


def _skins(doc, out, name):
    accessors = doc.get("accessors") or []
    for i, skin in enumerate(doc.get("skins") or []):
        joints = skin.get("joints") or []
        if not joints:
            out.add("model-invalid", "error", f"{name}: skins[{i}] has no joints")
        ibm = skin.get("inverseBindMatrices")
        if isinstance(ibm, int) and accessors[ibm].get("count") != len(joints):
            out.add("model-invalid", "error",
                    f"{name}: skins[{i}] has {len(joints)} joints and "
                    f"{accessors[ibm].get('count')} inverse bind matrices")
    for i, node in enumerate(doc.get("nodes") or []):
        if "skin" in node and "mesh" in node:
            for prim in doc["meshes"][node["mesh"]].get("primitives") or []:
                attrs = prim.get("attributes") or {}
                if "JOINTS_0" not in attrs or "WEIGHTS_0" not in attrs:
                    out.add("model-invalid", "error",
                            f"{name}: nodes[{i}] is skinned but its mesh has no "
                            f"JOINTS_0/WEIGHTS_0")
                    break
    return len(doc.get("skins") or [])


def _role(node):
    extras = node.get("extras") if isinstance(node.get("extras"), dict) else {}
    if extras.get("wgf_role") == "collision" or COLLISION_NAME.search(node.get("name") or ""):
        return "collision", None
    lod = extras.get("wgf_lod")
    if isinstance(lod, int) and not isinstance(lod, bool):
        return "lod", lod
    match = LOD_NAME.search(node.get("name") or "")
    if match:
        return "lod", int(match.group(1))
    return None, None


def inspect(data, *, name="model", kind=None):
    """An Inspection of GLB/glTF bytes. Never raises for the file's own problems."""
    out = Inspection()
    try:
        doc, binary = load(data)
    except GltfError as exc:
        out.add("model-invalid", "error", f"{name}: {exc}")
        return out
    out.document = doc

    used = list(doc.get("extensionsUsed") or [])
    required = list(doc.get("extensionsRequired") or [])
    for ext in required:
        if ext in DECODER_EXTENSIONS:
            out.add("model-needs-decoder", "warning",
                    f"{name}: requires {ext}; the game must configure three.js "
                    f"{DECODER_EXTENSIONS[ext]} and ship its decoder files")
        elif ext not in SUPPORTED_EXTENSIONS:
            out.add("model-unsupported-extension", "error",
                    f"{name}: requires {ext}, which the runtime's GLTFLoader cannot read")
    if not _check_refs(doc, out, name):
        return out
    _check_buffers(doc, binary, out, name)
    tree = _tree(doc, out, name)
    _transforms(doc, out, name)
    textures = _images(doc, binary, out, name)
    clips = _animations(doc, out, name)
    skins = _skins(doc, out, name)
    if tree is None or any(code == "model-transform" and sev == "error"
                           for code, sev, _ in out.findings):
        return out
    parent, roots = tree
    nodes = doc.get("nodes") or []

    # Walk from the scene roots: world matrix, and the role each subtree inherits.
    world, role_of = {}, {}
    stack = [(r, IDENTITY, (None, None)) for r in reversed(roots)]
    order = []
    while stack:
        index, parent_matrix, inherited = stack.pop()
        node = nodes[index]
        matrix = _multiply(parent_matrix, _trs(node))
        own = _role(node)
        role = own if own[0] == "collision" or (own[0] == "lod" and inherited[0] != "collision") \
            else inherited
        world[index], role_of[index] = matrix, role
        order.append(index)
        for child in reversed(node.get("children") or []):
            stack.append((child, matrix, role))

    lo, hi = [math.inf] * 3, [-math.inf] * 3
    triangles = vertices = 0
    lods, collision = {}, None
    for index in order:
        node = nodes[index]
        role, level = role_of[index]
        if role == "lod" and (_role(node)[0] == "lod"):
            lods.setdefault(level, {"level": level, "node": node.get("name") or f"nodes[{index}]",
                                    "triangles": 0})
        if role == "collision" and _role(node)[0] == "collision" and collision is None:
            extras = node.get("extras") if isinstance(node.get("extras"), dict) else {}
            collision = {"node": node.get("name") or f"nodes[{index}]",
                         "shape": extras.get("wgf_shape") or "mesh", "triangles": 0}
        if "mesh" not in node:
            continue
        mesh_tris = sum(_primitive_triangles(doc, p)
                        for p in doc["meshes"][node["mesh"]].get("primitives") or [])
        if role == "collision":
            if collision is not None:
                collision["triangles"] += mesh_tris
            continue
        if role == "lod" and level:
            lods[level]["triangles"] += mesh_tris
            continue
        if role == "lod":
            lods[0]["triangles"] += mesh_tris
        triangles += mesh_tris
        for prim in doc["meshes"][node["mesh"]].get("primitives") or []:
            position = prim["attributes"]["POSITION"]
            vertices += doc["accessors"][position].get("count", 0)
            # The vertices themselves, placed: the corners of a rotated part's local box
            # stand outside the part, so a box-of-boxes is larger than the model - a fitted
            # model with rotated parts would read as missing its fit.
            points = _positions(doc, binary, position)
            if points is None:
                rng = _positions_range(doc, binary, position)
                if rng is None:
                    continue
                (x0, y0, z0), (x1, y1, z1) = rng
                points = [(x, y, z) for x in (x0, x1) for y in (y0, y1) for z in (z0, z1)]
            for corner in points:
                p = _apply(world[index], corner)
                for k in range(3):
                    lo[k], hi[k] = min(lo[k], p[k]), max(hi[k], p[k])

    if triangles == 0:
        out.add("model-invalid", "error", f"{name}: no visible triangles at rest")
    summary = {
        "triangles": triangles,
        "vertices": vertices,
        "nodes": len(nodes),
        "meshes": len(doc.get("meshes") or []),
        "materials": [m.get("name") or f"material-{i}"
                      for i, m in enumerate(doc.get("materials") or [])],
        "textures": textures,
        "animations": clips,
        "lods": [lods[k] for k in sorted(lods)],
        "skins": skins,
        "extensions_used": used,
        "extensions_required": required,
    }
    if collision:
        summary["collision"] = collision
    if triangles and all(math.isfinite(v) for v in lo + hi):
        summary["bounds"] = {"min": [_decimal(v) for v in lo], "max": [_decimal(v) for v in hi]}
        summary["dimensions"] = [_decimal(hi[k] - lo[k]) for k in range(3)]
        largest = max(summary["dimensions"])
        limit = MAX_EXTENT.get(kind, DEFAULT_MAX_EXTENT)
        if largest > limit:
            out.add("model-scale", "warning",
                    f"{name}: {largest:g} m across; over {limit:g} m usually means it was "
                    f"authored in centimetres")
        elif largest < MIN_EXTENT:
            out.add("model-scale", "warning",
                    f"{name}: {largest:g} m across; under {MIN_EXTENT:g} m usually means a "
                    f"unit mistake")
    out.summary = summary
    return out


def check_expectations(summary, expect, data=None, *, name="model"):
    """[(code, severity, message)]: what the spec declared that the file does not hold.

    A limit the design declared (spec `budget`) is an error; one only the policy sets is a
    warning, like the policy's max_bytes."""
    findings = []
    if summary is None:
        return findings
    add = findings.append
    have = {c["name"]: c for c in summary.get("animations") or []}
    for clip, duration in (expect.get("clips") or {}).items():
        if clip not in have:
            add(("animation-missing", "error",
                 f"{name}: declared clip {clip!r} is not in the file (has: "
                 f"{', '.join(sorted(have)) or 'none'})"))
        elif duration is not None and abs(have[clip]["duration"] - duration) > 1e-3:
            add(("animation-invalid", "warning",
                 f"{name}: clip {clip!r} lasts {have[clip]['duration']:g}s; declared "
                 f"{duration:g}s"))
    want_lods = expect.get("lods")
    if want_lods:
        levels = {l["level"]: l for l in summary.get("lods") or []}
        for level in range(1, want_lods + 1):
            if level not in levels:
                add(("lod-missing", "error", f"{name}: declared LOD{level} is not in the file"))
        previous = summary.get("triangles")
        for level in sorted(k for k in levels if k > 0):
            if previous is not None and levels[level]["triangles"] >= previous:
                add(("lod-invalid", "warning",
                     f"{name}: LOD{level} has {levels[level]['triangles']} triangles, no fewer "
                     f"than the level before ({previous})"))
            previous = levels[level]["triangles"]
    collision = summary.get("collision")
    if collision and collision.get("triangles", 0) > MAX_COLLISION_TRIANGLES:
        add(("model-over-budget", "warning",
             f"{name}: collision proxy {collision['node']} has {collision['triangles']} "
             f"triangles; a physics proxy wants a box or a hull of at most "
             f"{MAX_COLLISION_TRIANGLES}"))
    if expect.get("collision") and not summary.get("collision"):
        add(("collision-missing", "error",
             f"{name}: a {expect['collision']} collision proxy is declared and the file has "
             f"none (a node named *_collision or with extras.wgf_role = collision)"))
    fit, dims = expect.get("fit"), summary.get("dimensions")
    if fit and dims:
        axis = fit.get("axis", "max")
        actual = max(dims) if axis == "max" else dims["xyz".index(axis)]
        if abs(actual - fit["size"]) > max(1e-4, fit["size"] * 1e-3):
            add(("model-scale", "error",
                 f"{name}: {actual:g} m along {axis}; the spec fits it to {fit['size']:g} m"))
    bounds = summary.get("bounds")
    pivot = expect.get("pivot")
    if pivot in ("base-center", "center") and bounds and dims:
        tolerance = max(1e-4, max(dims) * 1e-3)
        centre = [(bounds["min"][k] + bounds["max"][k]) / 2 for k in range(3)]
        off = [abs(centre[0]), abs(bounds["min"][1] if pivot == "base-center" else centre[1]),
               abs(centre[2])]
        if max(off) > tolerance:
            add(("model-pivot", "warning",
                 f"{name}: pivot is not at the {pivot} (off by {max(off):.4g} m); placement "
                 f"and rotation will be wrong"))
    declared = expect.get("budget_declared") or {}
    limit = expect.get("max_triangles")
    if limit and summary.get("triangles", 0) > limit:
        add(("model-over-budget", "error" if declared.get("max_triangles") else "warning",
             f"{name}: {summary['triangles']} triangles; budget {limit}"))
    edge = expect.get("max_texture_edge")
    if edge:
        for texture in summary.get("textures") or []:
            if max(texture.get("width") or 0, texture.get("height") or 0) > edge:
                add(("texture-too-large",
                     "error" if declared.get("max_texture_edge") else "warning",
                     f"{name}: a {texture['width']}x{texture['height']} texture; the budget is "
                     f"{edge} px on the long edge"))
    max_bytes = expect.get("max_bytes")
    if max_bytes and data is not None and len(data) > max_bytes:
        add(("too-large", "error", f"{name}: {len(data)} bytes; the spec's budget is {max_bytes}"))
    return findings

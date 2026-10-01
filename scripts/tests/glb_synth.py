"""Synthetic GLBs for tests: primitives with normals, placed as nodes, in pure Python.

Not a model builder - Blender is (wgf_assets/blender.py). This makes the files a test needs
to hold the GLB quality inspection to known geometry: one box, one sphere, a composite of
several primitives, a tapered (modelled) box; and it is what the fake Blender of
test_model_author.py writes for a resolved model spec, so the step's process layer runs
without Blender.

    data = build([{"id": "body", "shape": "box", "size": [1, 2, 1]}], name="thing")

A part: id, shape (box | sphere | cylinder | cone | capsule | plane), size [x, y, z],
translation [x, y, z], rotation [x, y, z, w], parent (a part id), material (a material id),
taper [x, z] (scales the top, as the model spec's does). Materials: id and `color`, linear
RGBA (what modelspec.resolve writes) or `hex`.
"""

import json
import math
import struct


def _srgb_to_linear(channel):
    c = channel / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _box(sx, sy, sz):
    faces = [((1, 0, 0), (0, 1, 0), (0, 0, 1)), ((-1, 0, 0), (0, 0, 1), (0, 1, 0)),
             ((0, 1, 0), (0, 0, 1), (1, 0, 0)), ((0, -1, 0), (1, 0, 0), (0, 0, 1)),
             ((0, 0, 1), (1, 0, 0), (0, 1, 0)), ((0, 0, -1), (0, 1, 0), (1, 0, 0))]
    positions, normals, indices = [], [], []
    for n, u, v in faces:
        base = len(positions)
        for a, b in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
            p = [n[k] * 0.5 + u[k] * a * 0.5 + v[k] * b * 0.5 for k in range(3)]
            positions.append((p[0] * sx, p[1] * sy, p[2] * sz))
            normals.append(n)
        indices += [base, base + 1, base + 2, base, base + 2, base + 3]
    return positions, normals, indices


def _sphere(sx, sy, sz, segments=12, rings=6):
    positions, normals, indices = [], [], []
    for r in range(rings + 1):
        phi = math.pi * r / rings
        for s in range(segments + 1):
            theta = 2 * math.pi * s / segments
            n = (math.sin(phi) * math.cos(theta), math.cos(phi), math.sin(phi) * math.sin(theta))
            positions.append((n[0] * sx / 2, n[1] * sy / 2, n[2] * sz / 2))
            normals.append(n)
    for r in range(rings):
        for s in range(segments):
            a = r * (segments + 1) + s
            b = a + segments + 1
            indices += [a, b, a + 1, a + 1, b, b + 1]
    return positions, normals, indices


def _cylinder(sx, sy, sz, segments=12, top=1.0):
    positions, normals, indices = [], [], []
    ring = [(math.cos(2 * math.pi * s / segments), math.sin(2 * math.pi * s / segments))
            for s in range(segments)]
    for s, (c, d) in enumerate(ring):  # the wall
        for y, scale in ((-0.5, 1.0), (0.5, top)):
            positions.append((c * sx / 2 * scale, y * sy, d * sz / 2 * scale))
            normals.append((c, 0.0, d))
    for s in range(segments):
        a, b = 2 * s, 2 * ((s + 1) % segments)
        indices += [a, a + 1, b, b, a + 1, b + 1]
    for y, scale, ny in ((-0.5, 1.0, -1.0), (0.5, top, 1.0)):  # the caps, as fans
        centre = len(positions)
        positions.append((0.0, y * sy, 0.0))
        normals.append((0.0, ny, 0.0))
        for c, d in ring:
            positions.append((c * sx / 2 * scale, y * sy, d * sz / 2 * scale))
            normals.append((0.0, ny, 0.0))
        for s in range(segments):
            indices += [centre, centre + 1 + s, centre + 1 + (s + 1) % segments]
    return positions, normals, indices


def _capsule(sx, sy, sz, segments=12, rings=7):
    radius = min(sx, sz) / 2
    shift = sy / 2 - radius
    positions, normals, indices = _sphere(sx, 2 * radius, sz, segments, rings)
    positions = [(x, y + (shift if y > 0 else -shift), z) for x, y, z in positions]
    return positions, normals, indices


def _plane(sx, _sy, sz):
    positions = [(-sx / 2, 0, -sz / 2), (sx / 2, 0, -sz / 2), (sx / 2, 0, sz / 2),
                 (-sx / 2, 0, sz / 2)]
    return positions, [(0, 1, 0)] * 4, [0, 2, 1, 0, 3, 2]


SHAPES = {"box": _box, "sphere": _sphere, "icosphere": _sphere, "cylinder": _cylinder,
          "cone": lambda x, y, z: _cylinder(x, y, z, top=0.0), "capsule": _capsule,
          "plane": _plane}


def geometry(shape, size, taper=None):
    positions, normals, indices = SHAPES[shape](*size)
    if taper:
        low = min(p[1] for p in positions)
        span = (max(p[1] for p in positions) - low) or 1.0
        positions = [(x * (1 + (taper[0] - 1) * (y - low) / span), y,
                      z * (1 + (taper[1] - 1) * (y - low) / span)) for x, y, z in positions]
    return positions, normals, indices


def build(parts, materials=(), *, name="model", normals=True):
    """GLB bytes: a root node `name` holding one node per part, in the parts' hierarchy."""
    binary = bytearray()
    views, accessors, meshes = [], [], []

    def view(data, target):
        while len(binary) % 4:
            binary.append(0)
        views.append({"buffer": 0, "byteOffset": len(binary), "byteLength": len(data),
                      "target": target})
        binary.extend(data)
        return len(views) - 1

    material_index = {}
    gltf_materials = []
    for material in materials:
        color = material.get("color")
        if color is None:
            value = material.get("hex", "#cccccc").lstrip("#")
            color = [_srgb_to_linear(int(value[i:i + 2], 16)) for i in (0, 2, 4)] + [1.0]
        material_index[material["id"]] = len(gltf_materials)
        gltf_materials.append({"name": material["id"], "pbrMetallicRoughness": {
            "baseColorFactor": [round(c, 6) for c in color], "metallicFactor": 0,
            "roughnessFactor": 0.8}})

    nodes = [{"name": name, "children": []}]
    node_of = {}
    for part in parts:
        positions, part_normals, indices = geometry(part["shape"], part.get("size", [1, 1, 1]),
                                                    part.get("taper"))
        attributes = {}
        accessors.append({"bufferView": view(b"".join(struct.pack("<fff", *p)
                                                      for p in positions), 34962),
                          "componentType": 5126, "count": len(positions), "type": "VEC3",
                          "min": [min(p[k] for p in positions) for k in range(3)],
                          "max": [max(p[k] for p in positions) for k in range(3)]})
        attributes["POSITION"] = len(accessors) - 1
        if normals:
            accessors.append({"bufferView": view(b"".join(struct.pack("<fff", *n)
                                                          for n in part_normals), 34962),
                              "componentType": 5126, "count": len(part_normals),
                              "type": "VEC3"})
            attributes["NORMAL"] = len(accessors) - 1
        accessors.append({"bufferView": view(b"".join(struct.pack("<H", i) for i in indices),
                                             34963),
                          "componentType": 5123, "count": len(indices), "type": "SCALAR"})
        primitive = {"attributes": attributes, "indices": len(accessors) - 1}
        if part.get("material") in material_index:
            primitive["material"] = material_index[part["material"]]
        meshes.append({"name": part["id"], "primitives": [primitive]})
        node = {"name": part["id"], "mesh": len(meshes) - 1}
        if any(part.get("translation", [0, 0, 0])):
            node["translation"] = list(part["translation"])
        rotation = part.get("rotation", [0, 0, 0, 1])
        if list(rotation) != [0, 0, 0, 1]:
            node["rotation"] = list(rotation)
        node_of[part["id"]] = len(nodes)
        nodes.append(node)
        parent = node_of.get(part.get("parent"), 0)
        nodes[parent].setdefault("children", []).append(node_of[part["id"]])
    document = {"asset": {"version": "2.0", "generator": "glb_synth"}, "scene": 0,
                "scenes": [{"nodes": [0]}], "nodes": nodes, "meshes": meshes,
                "accessors": accessors, "bufferViews": views,
                "buffers": [{"byteLength": len(binary)}]}
    if gltf_materials:
        document["materials"] = gltf_materials
    return pack(document, bytes(binary))


def pack(document, binary):
    """GLB bytes from a glTF document and its BIN chunk."""
    text = json.dumps(document, separators=(",", ":")).encode("utf-8")
    text += b" " * (-len(text) % 4)
    binary = bytes(binary) + b"\0" * (-len(binary) % 4)
    body = struct.pack("<I", len(text)) + b"JSON" + text
    body += struct.pack("<I", len(binary)) + b"BIN\x00" + binary
    return b"glTF" + struct.pack("<II", 2, 12 + len(body)) + body

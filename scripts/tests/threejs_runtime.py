"""Load GLBs with the runtime's own three.js GLTFLoader, in Node, and report what a game sees.

The loader is the pinned template's (`@wgf/three-framework` -> three r170), read from the
pinned checkout with its node_modules (pinned_template.with_dependencies). Nothing is
reimplemented: GLTFLoader parses the file, AnimationMixer plays each clip, THREE.LOD is built
from the nodes the asset marks, exactly as a game would.

Three browser facilities are shimmed, because Node has no DOM: `self` is the global object
(GLTFLoader reads `self.URL`), `createImageBitmap` returns an
object with the PNG/JPEG header's size (the pixels are not decoded - image decoding is the
browser's, not the asset's), and `fetch` of a `blob:` URL is answered from node:buffer's
resolveObjectURL. Everything else is three.js itself.

    results, reason = probe([path, ...])   # one dict per file, or (None, why it cannot run)

The script is embedded here, not a tracked .mjs: the Factory tracks no JavaScript source
(test_core_template.TheFactoryContainsNoGameSource).
"""

import json
import os
import shutil
import subprocess

import pinned_template

__all__ = ["probe"]

PROBE = r"""
import { createRequire } from 'node:module';
import { readFileSync } from 'node:fs';
import { resolveObjectURL } from 'node:buffer';
import { pathToFileURL } from 'node:url';
import path from 'node:path';

const [anchor, ...files] = process.argv.slice(1);
const require = createRequire(anchor);
// three's exports hide package.json; its main entry lives in build/.
const threeDir = path.resolve(path.dirname(require.resolve('three')), '..');
const THREE = await import(pathToFileURL(path.join(threeDir, 'build/three.module.js')).href);
const { GLTFLoader } = await import(
  pathToFileURL(path.join(threeDir, 'examples/jsm/loaders/GLTFLoader.js')).href);

globalThis.self = globalThis;  // GLTFLoader reads self.URL, as in a browser or worker
const realFetch = globalThis.fetch;
globalThis.fetch = async (url, init) => {
  if (String(url).startsWith('blob:')) {
    const blob = resolveObjectURL(String(url));
    if (!blob) throw new Error(`unresolvable ${url}`);
    return new Response(blob);
  }
  return realFetch(url, init);
};
globalThis.createImageBitmap = async (blob) => {
  const bytes = new Uint8Array(await blob.arrayBuffer());
  const view = new DataView(bytes.buffer);
  let width = 0, height = 0;
  if (bytes[0] === 0x89 && bytes[1] === 0x50) {
    width = view.getUint32(16); height = view.getUint32(20);
  }
  return { width, height, close() {} };
};

const loader = new GLTFLoader();
const out = [];
for (const file of files) {
  const entry = { file };
  try {
    const buffer = readFileSync(file);
    const gltf = await loader.parseAsync(
      buffer.buffer.slice(buffer.byteOffset, buffer.byteOffset + buffer.byteLength), '');
    const scene = gltf.scene;
    scene.updateMatrixWorld(true);
    const visual = [], collision = [], lods = [];
    let root = null;
    const walk = (object, hidden) => {
      const data = object.userData || {};
      if (data.wgf_asset && !root) root = object;
      let skip = hidden;
      if (data.wgf_role === 'collision') { collision.push(object); skip = true; }
      if (Number.isInteger(data.wgf_lod)) { lods.push(object); if (data.wgf_lod > 0) skip = true; }
      if (object.isMesh && !skip) visual.push(object);
      for (const child of object.children) walk(child, skip);
    };
    walk(scene, false);
    const box = new THREE.Box3();
    let triangles = 0;
    const materials = new Set();
    let textured = 0;
    for (const mesh of visual) {
      box.expandByObject(mesh);
      const geometry = mesh.geometry;
      triangles += (geometry.index ? geometry.index.count : geometry.attributes.position.count) / 3;
      for (const material of [].concat(mesh.material)) {
        materials.add(material.type);
        if (material.map) textured += 1;
      }
    }
    const size = box.getSize(new THREE.Vector3());
    const lod = new THREE.LOD();
    for (const node of lods.sort((a, b) => a.userData.wgf_lod - b.userData.wgf_lod)) {
      lod.addLevel(node.clone(), node.userData.wgf_lod * 10);
    }
    const clips = [];
    for (const clip of gltf.animations) {
      const mixer = new THREE.AnimationMixer(scene);
      const targets = clip.tracks.map((t) => scene.getObjectByName(t.name.split('.')[0]));
      const before = targets.map((o) => o && [...o.position.toArray(), ...o.quaternion.toArray(),
                                              ...o.scale.toArray()]);
      mixer.clipAction(clip).play();
      mixer.update(clip.duration / 2);
      const after = targets.map((o) => o && [...o.position.toArray(), ...o.quaternion.toArray(),
                                             ...o.scale.toArray()]);
      const moved = before.some((b, i) => b && b.some((v, k) => Math.abs(v - after[i][k]) > 1e-6));
      mixer.stopAllAction();
      mixer.uncacheRoot(scene);
      clips.push({ name: clip.name, duration: clip.duration, tracks: clip.tracks.length,
                   resolved: targets.every(Boolean), moved });
      // Put the pose back for the next clip.
      targets.forEach((o, i) => {
        if (!o) return;
        o.position.fromArray(before[i].slice(0, 3));
        o.quaternion.fromArray(before[i].slice(3, 7));
        o.scale.fromArray(before[i].slice(7, 10));
      });
    }
    Object.assign(entry, {
      ok: true,
      root: root ? root.name : null,
      root_user_data: root ? root.userData : null,
      meshes: visual.length,
      triangles,
      dimensions: triangles ? [size.x, size.y, size.z] : null,
      min_y: triangles ? box.min.y : null,
      materials: [...materials].sort(),
      textured,
      collision: collision.map((o) => ({ name: o.name, userData: o.userData,
                                         mesh: !!o.isMesh })),
      lod_levels: lod.levels.length,
      clips,
    });
  } catch (error) {
    Object.assign(entry, { ok: false, error: String(error && error.stack || error) });
  }
  out.push(entry);
}
process.stdout.write(JSON.stringify(out));
"""


def probe(files, timeout=120):
    """(results, None) or (None, reason). `results` is one dict per file."""
    node = shutil.which("node")
    if node is None:
        return None, "node is not on PATH"
    checkout, reason = pinned_template.with_dependencies()
    if checkout is None:
        return None, reason
    anchor = os.path.join(checkout, "packages", "three-framework", "package.json")
    if not os.path.isfile(anchor):
        return None, f"the pinned template has no three-framework package ({anchor})"
    try:
        result = subprocess.run([node, "--input-type=module", "-e", PROBE, anchor,
                                 *[os.path.abspath(f) for f in files]],
                                capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, f"node could not run the probe: {exc}"
    if result.returncode != 0:
        return None, f"the three.js probe failed: {result.stderr.strip()[-2000:]}"
    return json.loads(result.stdout), None

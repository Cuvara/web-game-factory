"""The runtime asset manifest: what the game loads, and a check that it can load it.

`build(entries, atlases, store, title_id)` turns the pipeline's results into
`public/assets/assets.json` - the one file game code reads to find its assets, so no asset
path is ever written in source. The shape is core/artifacts/shared/runtime-assets.schema.json:

    {"format": "wgf-runtime-assets", "version": 1, "title_id": "...",
     "assets":  {"<id>": {"type": "sprite", "url": "sprites/hero.png", ...}
                 "<id>": {"type": "ui", "atlas": "hud", "frame": "<id>", ...}},
     "atlases": {"hud": {"url": "atlases/hud.png", "data": "atlases/hud.json", ...}},
     "files":   {"sprites/hero.png": {"bytes": 1234, "hash": "sha256:..."}}}

URLs are relative to the manifest itself. The bytes are deterministic: sorted keys, no
timestamps, no absolute paths, no dependence on directory order.

`validate(root)` checks a game repository against its runtime manifest without the Factory's
own records - the same check a developer, a CI job or the verify step can run:

    schema          the document matches the schema; ids and URLs are well formed
    references      every url/data names a file under public/, listed in `files`, that
                    exists, has the recorded size and hash, and is the format it claims
    atlases         member assets name an atlas that exists and a frame it has; every
                    frame lies inside the image; animations name frames that exist
    spritesheets    the descriptor matches its image; declared frames exist
    tilesets        the image divides into its tiles
    images          SVG is safe; texture edges within the policy's limits
    unused          files under public/assets the manifest does not reference (warning)

Each problem is {code, severity, message, asset_id?, path?}; nothing is printed or raised.
"""

import hashlib
import json
import os
import posixpath
import re

from wgflib import jsonschema_lite, paths

from . import formats
from .atlas import check_document

__all__ = ["RUNTIME_PATH", "FORMAT", "build", "validate", "load_schema", "url_for"]

RUNTIME_PATH = "public/assets/assets.json"
PUBLIC = "public"
FORMAT = "wgf-runtime-assets"
SCHEMA_PATH = os.path.join(paths.ROOT, "core", "artifacts", "shared",
                           "runtime-assets.schema.json")
DEFAULT_MAX_EDGE, DEFAULT_WARN_EDGE = 4096, 2048
IGNORED = {".gitkeep", ".DS_Store", "Thumbs.db"}
_SCHEME = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")


def url_for(relative):
    """The URL of a repository-relative path, relative to public/assets/assets.json; None
    when the file is not under public/ and so is never served."""
    if not relative.startswith(PUBLIC + "/"):
        return None
    return posixpath.relpath(relative, posixpath.dirname(RUNTIME_PATH))


def _sha(data):
    return "sha256:" + hashlib.sha256(data).hexdigest()


def build(entries, atlases, title_id=None):
    """(bytes of the runtime manifest). `entries` {id: (entry dict, [(path, data)])};
    `atlases` {id: (atlas dict, [(path, data)])}. Paths are repository-relative."""
    files, assets, packed = {}, {}, {}
    for collection, target in ((entries, assets), (atlases, packed)):
        for key in sorted(collection):
            record, payload = collection[key]
            target[key] = {k: v for k, v in record.items() if v is not None}
            for relative, data in payload:
                url = url_for(relative)
                if url is not None:
                    files[url] = {"bytes": len(data), "hash": _sha(data)}
    document = {"format": FORMAT, "version": 1, "assets": assets, "atlases": packed,
                "files": files}
    if title_id:
        document["title_id"] = title_id
    return (json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
            ).encode("utf-8")


def load_schema():
    with open(SCHEMA_PATH, encoding="utf-8") as handle:
        return json.load(handle)


# -- validation ------------------------------------------------------------------------------

class _Report:
    def __init__(self):
        self.issues = []

    def add(self, code, severity, message, *, asset_id=None, path=None):
        issue = {"code": code, "severity": severity, "message": message}
        if asset_id:
            issue["asset_id"] = asset_id
        if path:
            issue["path"] = path
        self.issues.append(issue)


def _reject_duplicates(pairs):
    seen = {}
    for key, value in pairs:
        if key in seen:
            raise ValueError(f"duplicate key {key!r}")
        seen[key] = value
    return seen


def _resolve(root, url):
    """(repository-relative path, absolute path) of a manifest url, or (None, reason)."""
    if not isinstance(url, str) or not url or "\\" in url or url.startswith("/") or \
            _SCHEME.match(url) or "?" in url or "#" in url:
        return None, "is not a relative URL"
    joined = posixpath.normpath(posixpath.join(posixpath.dirname(RUNTIME_PATH), url))
    if joined != PUBLIC and not joined.startswith(PUBLIC + "/"):
        return None, "leaves public/, which is all a build serves"
    absolute = os.path.realpath(os.path.join(root, *joined.split("/")))
    public = os.path.realpath(os.path.join(root, PUBLIC))
    if os.path.commonpath([public, absolute]) != public:
        return None, "resolves outside public/ through a link"
    return joined, absolute


def validate(root, *, max_edge=DEFAULT_MAX_EDGE, warn_edge=DEFAULT_WARN_EDGE,
             unused=True):
    """[issue] for the runtime manifest of the game repository at `root`."""
    report = _Report()
    manifest_path = os.path.join(root, *RUNTIME_PATH.split("/"))
    if not os.path.isfile(manifest_path):
        report.add("missing-manifest", "error",
                   f"{RUNTIME_PATH} does not exist; run the assets step (or "
                   f"`wgf-assets.py build`) to write it", path=RUNTIME_PATH)
        return report.issues
    with open(manifest_path, "rb") as handle:
        raw = handle.read()
    try:
        document = json.loads(raw.decode("utf-8"), object_pairs_hook=_reject_duplicates)
    except (UnicodeDecodeError, ValueError) as exc:
        code = "duplicate-id" if "duplicate key" in str(exc) else "invalid-manifest"
        report.add(code, "error", f"{RUNTIME_PATH}: {exc}", path=RUNTIME_PATH)
        return report.issues

    validator = jsonschema_lite.Validator(load_schema())
    schema_errors = list(validator.iter_errors(document))
    for error in schema_errors[:50]:
        report.add("invalid-manifest", "error", f"{RUNTIME_PATH}: {error}", path=RUNTIME_PATH)
    if not isinstance(document, dict) or schema_errors and not all(
            isinstance(document.get(k), dict) for k in ("assets", "atlases", "files")):
        return report.issues

    files = document.get("files") or {}
    checked = {}   # url -> (Detected or None, data) of files that exist and match

    def load(url, *, owner, field):
        if not isinstance(url, str):
            report.add("invalid-reference", "error", f"{owner}: no {field}", asset_id=owner)
            return None, None
        if url in checked:
            return checked[url]
        relative, absolute = _resolve(root, url)
        result = (None, None)
        if relative is None:
            report.add("invalid-reference", "error", f"{owner}: {field} {url!r} {absolute}",
                       asset_id=owner)
        elif not os.path.isfile(absolute):
            report.add("missing-file", "error", f"{owner}: {field} {url!r} -> {relative} "
                                                f"does not exist", asset_id=owner,
                       path=relative)
        else:
            with open(absolute, "rb") as handle:
                data = handle.read()
            record = files.get(url)
            if record is None:
                report.add("unlisted-file", "error",
                           f"{owner}: {url!r} is not in `files`, so its hash is unknown",
                           asset_id=owner, path=relative)
            elif record.get("hash") != _sha(data) or record.get("bytes") != len(data):
                report.add("hash-mismatch", "error",
                           f"{owner}: {relative} changed since the manifest was written "
                           f"(rebuild it)", asset_id=owner, path=relative)
            found = formats.sniff(data)
            declared = formats.format_for_extension(relative)
            if found is None:
                report.add("invalid-format", "error",
                           f"{owner}: {relative} is not a recognisable file", asset_id=owner,
                           path=relative)
            elif declared and found.format != declared and \
                    {found.format, declared} != {"gltf", "json"}:
                report.add("invalid-format", "error",
                           f"{owner}: {relative} is named .{declared} but is {found.format}",
                           asset_id=owner, path=relative)
            else:
                _image_checks(report, owner, relative, data, found, max_edge, warn_edge)
            result = (found, data)
        checked[url] = result
        return result

    atlases = document.get("atlases") or {}
    atlas_frames = {}
    for atlas_id in sorted(atlases):
        atlas = atlases[atlas_id]
        if not isinstance(atlas, dict):
            continue
        found, _ = load(atlas.get("url"), owner=atlas_id, field="url")
        _, data = load(atlas.get("data"), owner=atlas_id, field="data")
        frames = _descriptor(report, atlas_id, atlas.get("data"), data, found,
                             atlas.get("url"))
        atlas_frames[atlas_id] = frames
        if frames is not None and sorted(frames) != sorted(atlas.get("frames") or []):
            report.add("invalid-atlas", "error",
                       f"atlas {atlas_id}: `frames` does not match its descriptor",
                       asset_id=atlas_id)
        if found and found.width and (found.width, found.height) != (
                atlas.get("width"), atlas.get("height")):
            report.add("dimension-mismatch", "error",
                       f"atlas {atlas_id}: recorded {atlas.get('width')}x"
                       f"{atlas.get('height')}, image is {found.width}x{found.height}",
                       asset_id=atlas_id)

    for asset_id in sorted(document.get("assets") or {}):
        asset = document["assets"][asset_id]
        if not isinstance(asset, dict):
            continue
        _check_asset(report, asset_id, asset, load, atlases, atlas_frames)

    for url in sorted(set(files) - set(checked)):
        report.add("unlisted-file", "warning",
                   f"`files` lists {url!r}, which no asset or atlas references", path=url)

    if unused:
        referenced = {_resolve(root, url)[0] for url in checked} | {
            _resolve(root, url)[0] for url in files if isinstance(url, str)}
        base = os.path.join(root, PUBLIC, "assets")
        for directory, dirs, names in os.walk(base):
            dirs.sort()
            for name in sorted(names):
                if name in IGNORED or name.startswith(".wgf-asset-"):
                    continue
                relative = os.path.relpath(os.path.join(directory, name), root).replace(
                    os.sep, "/")
                if relative != RUNTIME_PATH and relative not in referenced:
                    report.add("unused-file", "warning",
                               f"{relative} is shipped but not in the runtime manifest; "
                               f"register it or delete it", path=relative)
    return report.issues


def _image_checks(report, owner, relative, data, found, max_edge, warn_edge):
    if found.format == "svg":
        for hazard in formats.svg_hazards(data):
            report.add("unsafe-svg", "error", f"{owner}: {relative} contains {hazard}",
                       asset_id=owner, path=relative)
    edge = max(found.width or 0, found.height or 0)
    if edge > max_edge:
        report.add("texture-too-large", "error",
                   f"{owner}: {relative} is {found.width}x{found.height}; many mobile GPUs "
                   f"refuse textures over {max_edge} px", asset_id=owner, path=relative)
    elif edge > warn_edge:
        report.add("texture-too-large", "warning",
                   f"{owner}: {relative} is {found.width}x{found.height}; over {warn_edge} px "
                   f"costs memory low-end phones lack", asset_id=owner, path=relative)


def _descriptor(report, owner, url, data, image, image_url=None):
    """Frame names of an atlas descriptor, checked against its image; None if unreadable."""
    if data is None:
        return None
    try:
        document = json.loads(data.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError) as exc:
        report.add("invalid-atlas", "error", f"{owner}: {url} is not JSON: {exc}",
                   asset_id=owner)
        return None
    size = (image.width, image.height) if image and image.width else None
    for problem in check_document(document, size):
        report.add("invalid-atlas", "error", f"{owner}: {url}: {problem}", asset_id=owner)
    meta = document.get("meta") if isinstance(document, dict) else None
    named = meta.get("image") if isinstance(meta, dict) else None
    if isinstance(named, str) and isinstance(image_url, str) and \
            posixpath.normpath(posixpath.join(posixpath.dirname(url), named)) != \
            posixpath.normpath(image_url):
        report.add("invalid-atlas", "error",
                   f"{owner}: {url}: meta.image {named!r} is not {image_url!r}; a loader "
                   f"following meta.image fetches the wrong file", asset_id=owner)
    raw = document.get("frames") if isinstance(document, dict) else None
    if isinstance(raw, dict):
        return list(raw)
    if isinstance(raw, list):
        return [e.get("filename") for e in raw if isinstance(e, dict)]
    return None


def _check_asset(report, asset_id, asset, load, atlases, atlas_frames):
    if asset.get("atlas") is not None:
        atlas_id = asset["atlas"]
        if atlas_id not in atlases:
            report.add("invalid-reference", "error",
                       f"{asset_id}: atlas {atlas_id!r} is not in `atlases`",
                       asset_id=asset_id)
        elif atlas_frames.get(atlas_id) is not None and \
                asset.get("frame") not in atlas_frames[atlas_id]:
            report.add("missing-frame", "error",
                       f"{asset_id}: atlas {atlas_id} has no frame {asset.get('frame')!r}",
                       asset_id=asset_id)
        return
    url = asset.get("url")
    if url is None:
        if asset.get("type") == "font" and asset.get("family"):
            return  # a named fallback stack, nothing to load
        report.add("invalid-reference", "error", f"{asset_id}: no url and no atlas",
                   asset_id=asset_id)
        return
    found, _ = load(url, owner=asset_id, field="url")
    if found and asset.get("format") and found.format != asset["format"]:
        report.add("invalid-format", "error",
                   f"{asset_id}: recorded as {asset['format']}, file is {found.format}",
                   asset_id=asset_id)
    if found and found.width and asset.get("width") and (found.width, found.height) != (
            asset.get("width"), asset.get("height")):
        report.add("dimension-mismatch", "error",
                   f"{asset_id}: recorded {asset.get('width')}x{asset.get('height')}, file "
                   f"is {found.width}x{found.height}", asset_id=asset_id)
    if asset.get("data") is not None:
        _, data = load(asset["data"], owner=asset_id, field="data")
        frames = _descriptor(report, asset_id, asset["data"], data, found, url)
        if frames is not None:
            missing = [f for f in asset.get("frames") or [] if f not in frames]
            if missing:
                report.add("missing-frame", "error",
                           f"{asset_id}: frame(s) not in {asset['data']}: "
                           f"{', '.join(missing[:5])}", asset_id=asset_id)
    declared = set(asset.get("frames") or [])
    animations = asset.get("animations") if isinstance(asset.get("animations"), dict) else {}
    for name in sorted(animations):
        sequence = (animations[name] or {}).get("frames") if isinstance(
            animations[name], dict) else None
        missing = [f for f in sequence or [] if f not in declared]
        if missing:
            report.add("missing-frame", "error",
                       f"{asset_id}: animation {name!r} names frame(s) the sheet lacks: "
                       f"{', '.join(missing[:5])}", asset_id=asset_id)
    if asset.get("tile_width") and found and found.width:
        tw, th = asset["tile_width"], asset.get("tile_height") or asset["tile_width"]
        if found.width % tw or found.height % th:
            report.add("invalid-tileset", "error",
                       f"{asset_id}: {found.width}x{found.height} does not divide into "
                       f"{tw}x{th} tiles", asset_id=asset_id)

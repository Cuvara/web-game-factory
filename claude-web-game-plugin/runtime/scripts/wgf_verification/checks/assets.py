"""Assets: what the manifest promises is in the repository, in a format a browser loads,
referenced by paths that exist, loaded without failures, and licensed.

The link between a manifest item and a file is the file's stem: item `player-ship` is
`player-ship.png`, `player-ship.webp`, ... anywhere under the asset roots. The asset
manifest has no path field, and the id is the one name both sides already share.
"""

import os
import re

from ..model import FAIL, PASS, WARNING, Check, Evidence

__all__ = ["check_assets", "ASSET_ROOTS", "FORMATS"]

ASSET_ROOTS = ("public", "src/assets", "assets")
SOURCE_ROOTS = ("src",)

# Formats every target browser loads without a plugin or a transcoder the template lacks.
FORMATS = {
    "image": {"png", "jpg", "jpeg", "webp", "avif", "gif", "svg"},
    "audio": {"mp3", "ogg", "m4a", "aac", "wav", "webm", "opus"},
    "font": {"woff2", "woff", "ttf", "otf"},
    "model": {"glb", "gltf", "bin", "ktx2", "drc"},
    "data": {"json", "atlas", "fnt", "xml", "txt", "csv"},
    "video": {"mp4", "webm"},
}
BY_TYPE = {
    "sprite": FORMATS["image"], "spritesheet": FORMATS["image"] | {"json", "atlas"},
    "texture": FORMATS["image"] | {"ktx2", "basis"}, "ui": FORMATS["image"],
    "icon": FORMATS["image"] | {"ico"}, "screenshot": FORMATS["image"],
    "sfx": FORMATS["audio"], "music": FORMATS["audio"], "font": FORMATS["font"],
    "model": FORMATS["model"], "animation": FORMATS["model"] | {"json"},
    "vfx": FORMATS["image"] | {"json"},
}
ALLOWED = set().union(*FORMATS.values()) | {"ico", "basis", "html", "webmanifest", "md"}
IGNORED = {".gitkeep", ".DS_Store", "Thumbs.db"}
NEEDS_LICENSE = ("purchased", "library")

_REFERENCE = re.compile(
    r"""["'`]((?:\.{1,2}/|/)?(?:[\w.-]+/)*[\w.-]+\.(?:png|jpe?g|webp|avif|gif|svg|mp3|ogg|m4a|"""
    r"""aac|wav|opus|woff2?|ttf|otf|glb|gltf|ktx2|basis|mp4|webm|atlas|fnt))["'`]""", re.I)
_SOURCE_EXT = (".ts", ".tsx", ".js", ".mjs", ".jsx", ".css", ".html", ".vue")


def _asset_files(session):
    files = []
    for root in ASSET_ROOTS:
        files += [f for f in session.walk(root) if f.rsplit("/", 1)[-1] not in IGNORED]
    return files


def _stem(path):
    name = path.rsplit("/", 1)[-1]
    return name.split(".", 1)[0]


def _ext(path):
    name = path.rsplit("/", 1)[-1]
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


def check_assets(session):
    manifest = session.inputs.get("asset-manifest")
    files = _asset_files(session)
    items = [i for i in (manifest or {}).get("items") or [] if i.get("status") != "cut"]
    out = [_manifest(manifest, items), _missing(manifest, items, files),
           _formats(items, files), _paths(session), _loading(session), _licenses(manifest, items)]
    return [session.record(check) for check in out]


def _manifest(manifest, items):
    title = "Asset manifest complete"
    if manifest is None:
        return Check("assets.manifest", "assets", title, WARNING, required=False,
                     message="no asset-manifest in this run; manifest checks are skipped",
                     evidence=[Evidence("observation", "asset-manifest input is missing")])
    pending = [f"{i['id']} ({i.get('status')})" for i in items if i.get("status") != "integrated"]
    evidence = [Evidence("artifact", f"{len(items)} non-cut item(s), complete = "
                                     f"{manifest.get('complete')}")]
    if pending or not manifest.get("complete"):
        return Check("assets.manifest", "assets", title, WARNING, required=False,
                     message="not integrated yet: " + (", ".join(pending) or
                                                       "manifest says complete = false"),
                     evidence=evidence)
    return Check("assets.manifest", "assets", title, PASS, required=False,
                 message="every non-cut item is integrated", evidence=evidence)


def _missing(manifest, items, files):
    title = "Integrated assets are present"
    if manifest is None:
        return Check("assets.missing", "assets", title, WARNING, required=False,
                     message="no asset-manifest to check against",
                     evidence=[Evidence("observation", "asset-manifest input is missing")])
    stems = {}
    for path in files:
        stems.setdefault(_stem(path), []).append(path)
    integrated = [i for i in items if i.get("status") == "integrated"]
    missing = [i["id"] for i in integrated if i["id"] not in stems]
    evidence = [Evidence("file", f"{len(files)} file(s) under {', '.join(ASSET_ROOTS)}; "
                                 f"{len(integrated)} integrated item(s) in the manifest")]
    if missing:
        evidence.append(Evidence("observation", "no file named after: " + ", ".join(missing)))
        return Check("assets.missing", "assets", title, FAIL,
                     message=f"{len(missing)} integrated asset(s) have no file: "
                             + ", ".join(missing), evidence=evidence)
    return Check("assets.missing", "assets", title, PASS,
                 message=f"all {len(integrated)} integrated asset(s) found", evidence=evidence)


def _formats(items, files):
    title = "Asset formats are supported"
    unsupported = [f for f in files if _ext(f) not in ALLOWED]
    by_id = {i["id"]: i for i in items}
    mismatched = []
    for path in files:
        item = by_id.get(_stem(path))
        allowed = BY_TYPE.get((item or {}).get("type"))
        if item and allowed and _ext(path) not in allowed:
            mismatched.append(f"{path} is .{_ext(path)} but {item['id']} is a {item['type']}")
    evidence = [Evidence("file", f"{len(files)} asset file(s) inspected")]
    problems = [f"unsupported format: {f}" for f in unsupported] + mismatched
    if problems:
        evidence.append(Evidence("observation", "; ".join(problems[:25])))
        return Check("assets.formats", "assets", title, FAIL,
                     message=f"{len(problems)} asset(s) in a format the game cannot rely on",
                     evidence=evidence)
    return Check("assets.formats", "assets", title, PASS,
                 message="every asset is in a browser-loadable format", evidence=evidence)


def _paths(session):
    """Asset paths written in source resolve to a file, before any bundler is involved."""
    title = "Asset paths in source resolve"
    broken, count = [], 0
    for root in SOURCE_ROOTS + ("index.html",):
        candidates = session.walk(root) if os.path.isdir(session.path(root)) else (
            [root] if session.exists(root) else [])
        for rel in candidates:
            if not rel.endswith(_SOURCE_EXT):
                continue
            with open(session.path(rel), encoding="utf-8", errors="replace") as handle:
                text = handle.read()
            for ref in _REFERENCE.findall(text):
                # A bare file name is joined to a base path at runtime; only a path with a
                # directory in it can be resolved without guessing that base.
                if "://" in ref or "/" not in ref:
                    continue
                count += 1
                if not _resolves(session, rel, ref):
                    broken.append(f"{rel} -> {ref}")
    evidence = [Evidence("file", f"{count} asset path literal(s) in src/ and index.html")]
    if broken:
        evidence.append(Evidence("observation", "unresolved: " + "; ".join(broken[:25]),
                                 data={"unresolved": broken}))
        return Check("assets.paths", "assets", title, FAIL,
                     message=f"{len(broken)} asset path(s) point at nothing", evidence=evidence)
    return Check("assets.paths", "assets", title, PASS,
                 message=f"{count} asset path(s), all resolve", evidence=evidence)


def _resolves(session, source, ref):
    if ref.startswith(("./", "../")):
        here = os.path.dirname(session.path(source))
        if os.path.exists(os.path.normpath(os.path.join(here, ref))):
            return True
    bare = ref.lstrip("./")
    # Vite serves public/ at the site root; a bare relative path is resolved against it too.
    return any(os.path.exists(session.path(base, bare)) for base in ("public", ""))


def _loading(session):
    title = "Assets load without failures"
    seen = session.gameplay
    if seen is None or seen.failed_requests is None:
        driver = (session.gameplay_driver or {}).get("id", "no browser driver")
        return Check("assets.loading", "assets", title, WARNING, required=False,
                     message=f"{driver} did not record network failures; bundle references "
                             f"are checked statically by build.asset-resolution",
                     evidence=[Evidence("observation", "failed requests not observed"),
                               Evidence("reference", "see build.asset-resolution",
                                        check_ref="build.asset-resolution")])
    if seen.failed_requests:
        return Check("assets.loading", "assets", title, FAIL,
                     message=f"{len(seen.failed_requests)} request(s) failed while playing",
                     evidence=[Evidence("observation", "failed: " + "; ".join(
                         str(r) for r in seen.failed_requests[:25]))])
    return Check("assets.loading", "assets", title, PASS,
                 message="no failed requests while playing",
                 evidence=[Evidence("observation", f"{seen.driver} recorded no failed requests")])


def _licenses(manifest, items):
    title = "Sourced assets are licensed"
    if manifest is None:
        return Check("policy.asset-licenses", "policy", title, WARNING, required=False,
                     message="no asset-manifest to check licences against",
                     evidence=[Evidence("observation", "asset-manifest input is missing")])
    unlicensed = [i["id"] for i in items if i.get("status") == "integrated"
                  and i.get("source") in NEEDS_LICENSE and not i.get("license")]
    evidence = [Evidence("artifact", f"{sum(i.get('source') in NEEDS_LICENSE for i in items)} "
                                     f"purchased or library item(s) in the manifest")]
    if unlicensed:
        return Check("policy.asset-licenses", "policy", title, FAIL,
                     message="integrated without a recorded licence: " + ", ".join(unlicensed),
                     evidence=evidence)
    return Check("policy.asset-licenses", "policy", title, PASS,
                 message="every integrated purchased or library asset has a licence",
                 evidence=evidence)

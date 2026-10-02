"""The asset pipeline: classified requirements in, manifest items and issues out.

For each requirement, in order:

    existing file named by the design  -> validate, check licence and origin
        | missing or invalid
    library.json mapping (id, role)    -> the files a library maps to the requirement,
        |                                 licensed and with an origin
    library search (source library or unset) -> first candidate that is licensed, has an
        | nothing usable                       origin and validates; the rest are recorded
    author (2D: an SVG per drawing)    -> validated and judged (quality.py); a rejected file
        |                                 is shown its problems and asked again
    model author (3D, when installed)  -> wgf_assets.model_author.produce_model
        | not configured, or failed
    placeholder backends, in order     -> first that is available and returns a valid file
        | all failed or disabled
    missing                            -> status planned, an error issue for mvp/prototype

A derived baseline requirement (the design listed no assets) skips straight to the
placeholder backends: nobody designed it, so nothing is imported or authored for it.

Every delivered item gets a `quality` (quality.py): an SVG or PNG is judged against
core/reference/asset-quality.yaml (and a sound file - WAV decoded, Ogg or MP3 by its headers -
against its `audio` bars: length, level, loop seam, size, licence); a placeholder is `skipped`, never judged; a failed
verdict is a `quality-failed` issue and keeps the item from being production-ready.

Every file the pipeline writes goes under the asset root (a game repository checkout) at
`public/assets/<kind directory>/`, the template's static-asset convention, and is written
only when its bytes differ from what is there: a re-executed step reuses what it made.
Placeholders are named `<id>.placeholder.<ext>` so a stand-in is never mistaken for art.

Then, for the whole set:

    atlas groups      requirements naming the same `atlas` are packed, deterministically,
                      into public/assets/atlases/<group>.png + .json; their own PNGs go to
                      src/assets/<kind directory>/ - kept as source, never served twice
    runtime manifest  public/assets/assets.json: every loadable asset by id, with its URL or
                      its atlas frame, sizes, scale, frames and animations (runtime.py); a
                      GLB also carries its clip names, LOD and collision nodes (`model`)
    prune             placeholders and packed atlases this pipeline wrote earlier that
                      nothing references any more are removed; nothing else is touched

The licence rule is enforced here, not requested: an asset whose licence is unknown or
restricted, or that has no recorded origin, is never `delivered` and never
`production_ready`. It can be used to prototype - it is on disk and in the manifest - but it
cannot become a production asset without someone recording what it is.
"""

import hashlib
import json
import os
import tempfile
from collections import namedtuple

from wgflib import paths

from . import atlas as atlases_mod
from . import formats, gltf, modelspec, quality as quality_mod, raster, runtime
from .author import AUTHOR_CRAFT, AuthorError, AuthorRunFailed
from .library import LibraryError, match_all, search_all
from .optimize import optimize as optimize_bytes
from .placeholders import BackendError
from .policy import GENERATED_LICENSE

__all__ = ["AssetPipeline", "AssetStore", "PipelineResult", "validate_file", "asset_path",
           "ASSET_DIR", "SOURCE_DIR"]

ASSET_DIR = "public/assets"
# Where the source image of an atlas member goes: in the repository, out of the build (Vite
# bundles src/ only through imports), so the atlas is the one copy that ships.
SOURCE_DIR = "src/assets"
MODEL_FORMATS = ("glb", "gltf")
LOAD_BEARING_TIERS = ("mvp", "prototype")
ORIGIN_KEYS = ("source_url", "author", "vendor", "attribution", "license_url", "evidence")
# What the author backend has written, so a re-executed step reuses a file whose request is
# unchanged instead of asking again. In the repository, out of the build.
LEDGER_PATH = f"{SOURCE_DIR}/authored.json"
LEDGER_FORMAT = "wgf-authored-assets"
SOURCES = ("library", "procedural", "ai-generated", "purchased", "commissioned")
AUDIO_KINDS = ("sfx", "music")


def _is_audio(blob):
    head = bytes(blob[:12])
    return (head[:4] == b"OggS" or (head[:4] == b"RIFF" and head[8:12] == b"WAVE")
            or head[:3] == b"ID3" or (len(head) > 1 and head[0] == 0xFF
                                      and head[1] & 0xE0 == 0xE0))


def file_hash(data):
    return "sha256:" + hashlib.sha256(data).hexdigest()


def asset_path(req, ext, *, final=False, suffix=""):
    """Where a generated file of `req` goes when it is served as itself (not packed into an
    atlas): `<id>.<ext>` for a final file, `<id>.placeholder.<ext>` for a stand-in."""
    stem = req.id if final else f"{req.id}.placeholder"
    return f"{ASSET_DIR}/{req.policy.directory}/{stem}{suffix}.{ext}"


def _rename_atlas_image(data, image_path):
    """Atlas bytes whose meta.image names `image_path`'s file; unchanged when it already
    does or has no meta.image. Re-serialised with sorted keys, so the result is stable."""
    try:
        document = json.loads(data.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError):
        return data
    meta = document.get("meta") if isinstance(document, dict) else None
    name = image_path.rsplit("/", 1)[-1]
    if not isinstance(meta, dict) or "image" not in meta or meta["image"] == name:
        return data
    meta["image"] = name
    return (json.dumps(document, indent=2, sort_keys=True) + "\n").encode("utf-8")


class StoreError(ValueError):
    pass


class AssetStore:
    """Files under the asset root. Paths are repository-relative with forward slashes, and
    none may leave the root."""

    def __init__(self, root):
        self.root = os.path.abspath(root)
        self.writes = {"created": 0, "updated": 0, "reused": 0}
        self.removed = []

    def resolve(self, relative):
        if not relative or os.path.isabs(relative) or "\\" in relative:
            raise StoreError(f"{relative!r} is not a repository-relative path")
        path = os.path.realpath(os.path.join(self.root, relative))
        root = os.path.realpath(self.root)
        if os.path.commonpath([root, path]) != root:
            raise StoreError(f"{relative!r} leaves the asset root")
        return path

    def read(self, relative):
        path = self.resolve(relative)
        if not os.path.isfile(path):
            return None
        with open(path, "rb") as handle:
            return handle.read()

    def write(self, relative, data):
        path = self.resolve(relative)
        if os.path.isfile(path):
            with open(path, "rb") as handle:
                if handle.read() == data:
                    self.writes["reused"] += 1
                    return "reused"
            outcome = "updated"
        else:
            outcome = "created"
        os.makedirs(os.path.dirname(path), exist_ok=True)
        fd, temp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".wgf-asset-")
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
            os.chmod(temp, 0o644)  # mkstemp makes 0600; an asset is not a secret
            os.replace(temp, path)
        except BaseException:
            if os.path.exists(temp):
                os.unlink(temp)
            raise
        self.writes[outcome] += 1
        return outcome

    def remove(self, relative):
        path = self.resolve(relative)
        if os.path.isfile(path):
            os.unlink(path)
            self.removed.append(relative)

    def walk(self, relative):
        """Repository-relative paths of every file under `relative`, sorted."""
        base = self.resolve(relative)
        found = []
        for directory, dirs, names in os.walk(base):
            dirs.sort()
            for name in sorted(names):
                full = os.path.join(directory, name)
                found.append(os.path.relpath(full, self.root).replace(os.sep, "/"))
        return found


def validate_file(kind, relative, data, *, companion=False, policy=None):
    """(Detected or None, [(code, severity, message)]) for one file of an asset kind.
    `policy` supplies the texture-edge limits; without one the defaults apply."""
    problems = []
    found = formats.sniff(data)
    declared = formats.format_for_extension(relative)
    if found is None:
        problems.append(("invalid-format", "error",
                         f"{relative} is not a recognisable {declared or 'asset'} file"))
        return None, problems
    if declared and found.format != declared and {found.format, declared} != {"gltf", "json"}:
        problems.append(("invalid-format", "error",
                         f"{relative} is named .{declared} but its content is {found.format}"))
        return None, problems

    allowed = [kind.companion] if companion else kind.formats
    if found.format not in allowed and not (found.format == "gltf" and "json" in allowed):
        problems.append(("format-not-allowed", "error",
                         f"{relative} is {found.format}; {kind.kind} accepts "
                         f"{', '.join(allowed)}"))
    if found.format in ("json", "gltf"):
        document = json.loads(data.decode("utf-8-sig"))
        if companion and not (isinstance(document, dict) and document.get("frames")):
            problems.append(("invalid-format", "error", f"{relative} is not an atlas: no frames"))
        if kind.kind == "material" and not (
                isinstance(document, dict) and isinstance(document.get("pbrMetallicRoughness"),
                                                          dict)):
            problems.append(("invalid-format", "error",
                             f"{relative} is not a glTF material: no pbrMetallicRoughness"))
    if kind.max_bytes and len(data) > kind.max_bytes and not companion:
        problems.append(("too-large", "warning",
                         f"{relative} is {len(data)} bytes; {kind.kind} budget is "
                         f"{kind.max_bytes}"))
    if kind.power_of_two and found.width and found.height and not (
            formats.is_power_of_two(found.width) and formats.is_power_of_two(found.height)):
        problems.append(("not-power-of-two", "warning",
                         f"{relative} is {found.width}x{found.height}; GPU texture "
                         f"compression and mipmaps want powers of two"))
    if found.format in MODEL_FORMATS and not companion:
        # A GLB that sniffs as glTF 2.0 can still be an empty scene, a broken index or a file
        # that pulls textures from somewhere no manifest records: read all of it.
        problems.extend(gltf.inspect(data, name=relative, kind=kind.kind).findings)
    if found.format == "svg":
        for hazard in formats.svg_hazards(data):
            problems.append(("unsafe-svg", "error", f"{relative} contains {hazard}"))
    max_edge = policy.max_texture_edge if policy else runtime.DEFAULT_MAX_EDGE
    warn_edge = policy.warn_texture_edge if policy else runtime.DEFAULT_WARN_EDGE
    edge = max(found.width or 0, found.height or 0)
    if edge > max_edge:
        problems.append(("texture-too-large", "error",
                         f"{relative} is {found.width}x{found.height}; many mobile GPUs refuse "
                         f"textures over {max_edge} px"))
    elif edge > warn_edge:
        problems.append(("texture-too-large", "warning",
                         f"{relative} is {found.width}x{found.height}; over {warn_edge} px "
                         f"costs memory low-end phones lack"))
    if not companion and found.format in formats.IMAGE_FORMATS:
        problems.extend(_transparency(kind, relative, data, found))
    return found, problems


def _transparency(kind, relative, data, found):
    """What a file's alpha says against what its kind assumes."""
    expects = getattr(kind, "transparency", "any")
    if expects == "any":
        return []
    has_alpha = found.format in formats.ALPHA_FORMATS
    if found.format == "png":
        try:
            has_alpha = raster.png_header(data).has_alpha
        except raster.RasterError:
            return []
    if expects == "required" and not has_alpha:
        return [("transparency-mismatch", "warning",
                 f"{relative} has no alpha channel; a {kind.kind} is drawn over the scene and "
                 f"will show a solid rectangle")]
    if expects == "opaque" and found.format == "png" and has_alpha:
        return [("transparency-mismatch", "info",
                 f"{relative} carries an alpha channel a {kind.kind} does not use; an opaque "
                 f"PNG, JPEG or WebP is smaller")]
    return []


_Stored = namedtuple("_Stored", "relative data found applied saved")


class PipelineResult:
    def __init__(self):
        self.items = []
        self.issues = []
        self.backends = []
        self.bytes_total = 0
        self.atlases = []           # asset-manifest `atlases` records
        self.runtime_manifest = None  # {path, bytes, content_hash}
        self.removed = []           # stale pipeline-owned files pruned


class _Item:
    """A manifest item under construction, and the issues raised against it."""

    def __init__(self, req):
        self.req = req
        self.issues = []
        self.data = {
            "id": req.id,
            "label": req.label,
            "type": req.manifest_type,
            "dimension": req.dimension,
            "source": req.source or "procedural",
            "status": "planned",
            "scope_tier": req.scope_tier,
            "platforms": req.platforms or None,
            "notes": req.notes,
            "scale": req.scale if req.scale != 1 else None,
            "role": req.role,
        }
        self.payload = []  # [(repository-relative path, bytes)] of the files, as recorded
        self.generation = None  # a generating backend's `model.generation` block
        self.faces = None   # {runtime id: {family, weight}} of a font producer's files
        self.variants = []  # runtime ids of the drawings, when the requirement has a count
        self.short = None   # (supplied, wanted) when a library supplies fewer drawings
        self.quality_author = None  # what made it, for quality.author
        self.quality = None  # set when the backend judged it already
    def issue(self, code, severity, message):
        self.issues.append({"item_id": self.req.id, "code": code, "severity": severity,
                            "message": message})

    def has_errors(self):
        return any(i["severity"] == "error" for i in self.issues)

    def finish(self):
        kind = self.req.policy
        data = self.data
        delivered_final = data["status"] == "delivered"
        data["est_cost"] = kind.cost_for(data["source"])
        data["est_hours"] = 0.5 if delivered_final else kind.est_hours
        if data["status"] != "planned":
            data["production_ready"] = bool(
                delivered_final and not data.get("placeholder") and not self.has_errors()
                and data.get("license_status") in ("verified", "generated")
                and (data.get("quality") or {}).get("verdict") != "fail")
        if self.issues:
            data["issues"] = sorted({i["code"] for i in self.issues})
        order = ["id", "label", "type", "role", "dimension", "source", "est_cost",
                 "est_hours", "status", "license", "license_status", "usage_constraints",
                 "origin", "placeholder", "production_ready", "quality", "files", "atlas",
                 "scale", "reference", "model", "optimization", "scope_tier", "platforms",
                 "notes", "issues"]
        return {key: data[key] for key in order if data.get(key) is not None}


class AssetPipeline:
    def __init__(self, policy, store, backends, libraries=(), *, logger=None,
                 placeholders=True, optimize=True, runtime_manifest=True, prune=True,
                 title_id=None, author=None, model_author=None, palette=(), identity=None,
                 bars=None, rebuild=None, work_dir=None, settings=None, context=None,
                 locales=(), producers=()):
        self.policy = policy
        self.store = store
        self.backends = backends  # [(id, backend or None, note)]
        self.libraries = list(libraries)
        self.logger = logger
        self.placeholders = placeholders
        self.optimize = optimize
        self.runtime_manifest = runtime_manifest
        self.prune = prune
        self.title_id = title_id
        # The 2D author (author.py), or None; the 3D model author's produce_model, or None.
        self.author = author
        self.model_author = model_author
        self.identity = dict(identity or {})
        self.palette = quality_mod.parse_palette(self.identity.get("palette"))
        if palette:
            self.palette = list(palette)
        self.primitive_style = bool(self.identity.get("primitive_style"))
        self.bars = bars or quality_mod.load_bars()
        # The design's scope.locales: a delivered font must set each of them.
        self.locales = [str(x) for x in locales or [] if x]
        # Producers that make a kind's final asset from the design itself, tried after the
        # libraries and authors and before any placeholder: the font library
        # (fontlib.FontProducer), the composer (sound.producer.AudioProducer).
        self.producers = list(producers or [])
        # {requirement id: [finding]}: what a re-entry was sent back for; only these are
        # rebuilt, and the findings reach the author.
        self.rebuild = dict(rebuild or {})
        self.work_dir = work_dir
        self.settings = dict(settings or {})
        self.context = context
        self._ledger = None
        self._ledger_dirty = False
        self._hashes = {}
        self._paths = {}
        self._available = None
        self._used = {}
        # A backend that reuses what is already in the checkout (blender) needs to read it.
        for _id, backend, _note in self.backends:
            if backend is not None and hasattr(backend, "bind"):
                backend.bind(store, policy)

    def _log(self, message, **fields):
        if self.logger:
            self.logger.info(message, **fields)

    # -- backends ------------------------------------------------------------------------

    def _probe(self):
        if self._available is not None:
            return self._available
        self._available, self._report = [], []
        for backend_id, backend, note in self.backends:
            available = False
            if backend is not None:
                try:
                    available, note = backend.probe()
                except Exception as exc:  # an optional backend's bug is its own problem
                    available, note = False, f"probe failed: {exc}"
            if available:
                self._available.append(backend)
            entry = {"id": backend_id, "available": bool(available)}
            if note:
                entry["note"] = str(note)
            self._report.append(entry)
            self._log("placeholder backend", backend=backend_id, available=available,
                      note=note)
        return self._available

    def close(self):
        for _id, backend, _note in self.backends:
            if backend is not None:
                try:
                    backend.close()
                except Exception:
                    pass

    # -- the run ---------------------------------------------------------------------------

    def run(self, requirements):
        result = PipelineResult()
        built = []
        try:
            for req in requirements:
                item = self._process(req)
                self._judge(item)
                built.append(item)
        finally:
            self.close()
        self._write_ledger()
        packed = self._pack_atlases(built, result)
        entries = {}
        if self.runtime_manifest:
            for item in built:
                made = self._runtime_entry(item, packed)
                if made is not None:
                    entries[item.req.id] = made
                    entries.update(self._variant_entries(item, made[0]))
        for item in built:
            result.issues.extend(item.issues)
            result.items.append(item.finish())
        if self.runtime_manifest:
            document = runtime.build(entries, packed, self.title_id)
            self.store.write(runtime.RUNTIME_PATH, document)
            result.runtime_manifest = {"path": runtime.RUNTIME_PATH, "bytes": len(document),
                                       "content_hash": file_hash(document)}
        if self.prune:
            self._prune(built, result)
        if self._available is not None:
            for entry in self._report:
                entry["used"] = self._used.get(entry["id"], 0)
            result.backends = self._report
        else:
            result.backends = [{"id": b_id, "available": False, "used": 0,
                                "note": "not needed: nothing was generated"}
                               for b_id, _b, _n in self.backends]
        # What ships: every file under public/, each counted once - an atlas member's own
        # source image does not ship; its atlas does.
        shipped = {}
        for record in [f for i in result.items for f in i.get("files", [])] + [
                f for a in result.atlases for f in a["files"]]:
            if record["path"].startswith(runtime.PUBLIC + "/"):
                shipped[record["path"]] = record["bytes"]
        if result.runtime_manifest:
            shipped[result.runtime_manifest["path"]] = result.runtime_manifest["bytes"]
        result.bytes_total = sum(shipped.values())
        return result

    def _process(self, req):
        item = _Item(req)
        if req.existing:
            if self._existing(req, item):
                return item
        elif not req.generate_now():
            item.data["notes"] = req.notes or "Future tier: recorded, not produced."
            return item
        if not req.placeholder_only:
            # Sent back by a report with an author to ask: the library would hand over the
            # same file again, so the author is asked instead.
            redo = req.id in self.rebuild and self.author is not None
            if self.libraries and not redo:
                if self._mapped_library(req, item):
                    return item
                if req.source in (None, "library") and self._library(req, item):
                    return item
            if self.author is not None and self._authorable(req):
                if self._authored(req, item):
                    return item
            if self.model_author is not None and req.dimension == "3d" \
                    and req.policy.dimension in ("3d", "any") and req.kind in (
                        "model", "environment", "animation"):
                if self._model_authored(req, item):
                    return item
            for producer in self.producers:
                if producer.supports(req) and self._produced(producer, req, item):
                    return item
        if self.placeholders and self._placeholder(req, item):
            self._check_spec_built(req, item)
            return item
        severity = "error" if req.scope_tier in LOAD_BEARING_TIERS else "warning"
        item.issue("missing", severity,
                   f"{req.id}: no file, no usable library asset, and no placeholder generated")
        return item

    # -- sources -------------------------------------------------------------------------

    def _existing(self, req, item):
        """A file the design already chose. True when it is usable as delivered/sourced."""
        existing = req.existing
        relative = existing["path"]
        tier_severity = "error" if req.scope_tier in LOAD_BEARING_TIERS else "warning"
        try:
            data = self.store.read(relative)
        except StoreError as exc:
            item.issue("missing", tier_severity, f"{req.id}: {exc}")
            return False
        if data is None:
            item.issue("missing", tier_severity, f"{req.id}: {relative} does not exist")
            return False
        found, problems = validate_file(req.policy, relative, data, policy=self.policy)
        for code, severity, message in problems:
            item.issue(code, severity, f"{req.id}: {message}")
        if found is None or any(code in ("invalid-format", "format-not-allowed")
                                for code, _, _ in problems):
            return False

        # The design's own file is recorded, not rewritten: optimizing it in place would
        # change bytes someone else owns. What it still needs is deferred to the build.
        stored = [_Stored(relative, data, found, [], 0)]
        if req.policy.companion:
            companion = self._existing_companion(req, item, relative, found)
            if companion is None:
                return False
            stored.append(companion)

        origin = {"kind": "external"}
        for key in ORIGIN_KEYS:
            if existing.get(key):
                origin[key] = existing[key]
        item.data["source"] = req.source or "library"
        item.data["origin"] = origin
        verdict = self._license(item, existing.get("license"),
                                existing.get("usage_constraints") or ())
        self._check_clearance(item, verdict, origin)
        self._record_files(item, stored)
        item.data["optimization"] = {"applied": [], "deferred": list(req.policy.optimize)}
        cleared = verdict.status in ("verified", "generated") and not item.has_errors()
        item.data["status"] = "delivered" if cleared else "sourced"
        return True

    def _existing_companion(self, req, item, relative, found):
        """The atlas beside an existing spritesheet: `existing.atlas`, else
        `<stem>.atlas.json`, else `<stem>.json`. None (with an error) when absent or bad."""
        stem = relative.rsplit(".", 1)[0]
        named = req.existing.get("atlas")
        candidates = [named] if named else [f"{stem}.atlas.json", f"{stem}.json"]
        for candidate in candidates:
            try:
                data = self.store.read(candidate)
            except StoreError as exc:
                item.issue("invalid-atlas", "error", f"{req.id}: {exc}")
                return None
            if data is None:
                continue
            a_found, problems = validate_file(req.policy, candidate, data, companion=True)
            problems += [("invalid-atlas", "error", message) for message in
                         self._atlas_problems(data, found, candidate, relative)]
            for code, severity, message in problems:
                item.issue(code, severity, f"{req.id}: {message}")
            if a_found is None or any(sev == "error" for _, sev, _ in problems):
                return None
            return _Stored(candidate, data, a_found, [], 0)
        item.issue("invalid-atlas", "error",
                   f"{req.id}: a spritesheet needs its atlas beside it ("
                   f"{' or '.join(candidates)}); set existing.atlas to name it")
        return None

    @staticmethod
    def _atlas_problems(data, image, relative, image_path=None):
        try:
            document = json.loads(data.decode("utf-8-sig"))
        except (UnicodeDecodeError, ValueError):
            return [f"{relative} is not JSON"]
        size = (image.width, image.height) if image and image.width else None
        problems = [f"{relative}: {p}" for p in atlases_mod.check_document(document, size)]
        named = (document.get("meta") or {}).get("image") if isinstance(
            document.get("meta"), dict) else None
        if image_path and isinstance(named, str) and named != image_path.rsplit("/", 1)[-1]:
            problems.append(f"{relative}: meta.image is {named!r} but the image is "
                            f"{image_path.rsplit('/', 1)[-1]!r}; a loader following "
                            f"meta.image would fetch a file that is not there")
        return problems

    def _library(self, req, item):
        for entry in search_all(self.libraries, req):
            reason, payload = self._library_candidate(req, entry)
            if reason:
                item.issue("library-candidate-rejected", "info",
                           f"{req.id}: passed over {entry.qualified_id}: {reason}")
                continue
            fmt = payload[0][1]
            base = f"{self._directory(req, fmt)}/{req.id}"
            names = [f"{base}.{formats.FORMAT_EXTENSION.get(fmt, fmt)}", f"{base}.atlas.json"]
            if len(payload) > 1:
                # The image is renamed to the asset id; its atlas must name the new file, or
                # a loader that follows meta.image fetches something that is not there.
                payload[1] = (_rename_atlas_image(payload[1][0], names[0]), payload[1][1])
            stored = [self._store(name, data, kind)
                      for name, (data, kind) in zip(names, payload)]
            origin = {"kind": "library", "library_id": entry.qualified_id}
            for key in ORIGIN_KEYS:
                if getattr(entry, key):
                    origin[key] = getattr(entry, key)
            item.data["source"] = "library"
            item.data["origin"] = origin
            verdict = self._license(item, entry.license, entry.usage_constraints)
            self._check_clearance(item, verdict, origin)
            self._record_files(item, stored)
            item.data["optimization"] = self._optimization(req, stored)
            item.data["status"] = "delivered"
            self._log("library asset", asset=req.id, library_id=entry.qualified_id)
            return True
        return False

    def _library_candidate(self, req, entry):
        """(why it cannot be used, None), or (None, [(bytes, format), ...])."""
        verdict = self.policy.classify_license(entry.license)
        if verdict.status not in ("verified", "generated"):
            return (verdict.reason if verdict.status == "unknown" else
                    f"{entry.license} is restricted ({verdict.reason})"), None
        if not any((entry.source_url, entry.author, entry.vendor, entry.evidence)):
            return "no source_url, author, vendor or evidence recorded", None
        try:
            path = entry.absolute_path()
            with open(path, "rb") as handle:
                data = handle.read()
        except (OSError, LibraryError) as exc:
            return f"unreadable: {exc}", None
        found, problems = validate_file(req.policy, entry.path, data, policy=self.policy)
        errors = [message for _, severity, message in problems if severity == "error"]
        if found is None or errors:
            return "; ".join(errors) or "invalid file", None
        payload = [(data, found.format)]
        if req.policy.companion:
            atlas_path = os.path.splitext(path)[0] + ".atlas.json"
            if not os.path.isfile(atlas_path):
                return (f"{req.kind} needs an atlas beside it "
                        f"({os.path.basename(atlas_path)})"), None
            with open(atlas_path, "rb") as handle:
                atlas = handle.read()
            a_found, a_problems = validate_file(req.policy, atlas_path, atlas, companion=True)
            a_errors = [message for _, severity, message in a_problems if severity == "error"]
            a_errors += self._atlas_problems(atlas, found, os.path.basename(atlas_path))
            if a_found is None or a_errors:
                return "; ".join(a_errors) or "invalid atlas", None
            payload.append((atlas, "json"))
        return None, payload

    def _placeholder(self, req, item):
        failures = []
        for backend in self._probe():
            if not backend.supports(req):
                continue
            try:
                generated = backend.generate(req)
            except BackendError as exc:
                failures.append(f"{backend.id}: {exc}")
                continue
            except Exception as exc:  # an optional backend must never break the pipeline
                failures.append(f"{backend.id}: {type(exc).__name__}: {exc}")
                continue

            # Validate everything before writing anything: a half-written placeholder set
            # (an image without its atlas) is worse than none.
            checked, problems = [], []
            primary = primary_path = None
            directory = self._directory(req, generated.files[0].format
                                        if generated.files else None)
            stem = req.id if generated.final else f"{req.id}.placeholder"
            for gen in generated.files:
                ext = formats.FORMAT_EXTENSION.get(gen.format, gen.format)
                relative = f"{directory}/{stem}{gen.suffix}.{ext}"
                found, file_problems = validate_file(req.policy, relative, gen.data,
                                                     companion=bool(gen.suffix),
                                                     policy=self.policy)
                errors = [m for _, severity, m in file_problems if severity == "error"]
                if gen.suffix and found is not None:
                    errors += self._atlas_problems(gen.data, primary, relative, primary_path)
                elif found is not None:
                    primary, primary_path = found, relative
                if found is None or errors:
                    problems.extend(errors or [f"{relative} is invalid"])
                checked.append((relative, gen))
            if problems or not (checked or generated.reference):
                failures.append(f"{backend.id}: produced nothing usable: "
                                f"{'; '.join(problems) or 'no files'}")
                continue

            stored = [self._store(relative, gen.data, gen.format) for relative, gen in checked]
            self._used[backend.id] = self._used.get(backend.id, 0) + 1
            item.data["origin"] = {"kind": "generated", "generator": generated.generator}
            item.data["placeholder"] = not generated.final
            item.generation = generated.metadata
            if generated.final:
                # Built from the design's own spec: this is the asset, not a stand-in for it.
                item.data["source"] = "procedural"
            verdict = self._license(item, generated.license)
            if verdict.status != "generated":
                self._check_clearance(item, verdict, item.data["origin"], placeholder=True)
            if stored:
                self._record_files(item, stored)
                item.data["optimization"] = self._optimization(req, stored)
            if generated.reference:
                item.data["reference"] = generated.reference
            if generated.notes:
                item.data["notes"] = " ".join(filter(None, [item.data.get("notes"),
                                                            generated.notes]))
            item.data["status"] = "delivered" if generated.final else "in-progress"
            if failures:
                item.issue("generation-failed", "info",
                           f"{req.id}: fell back to {backend.id}: " + " | ".join(failures))
            if not generated.final:
                item.issue("placeholder", "info",
                           f"{req.id}: placeholder from {backend.id}; the final asset is still "
                           f"owed")
            self._log("placeholder", asset=req.id, backend=backend.id)
            return True
        if failures:
            item.issue("generation-failed", "warning", f"{req.id}: " + " | ".join(failures))
        return False

    def _produced(self, producer, req, item):
        """A producer's files for `req` (one per drawing or face when it counts several),
        or False with the reason recorded as an info issue."""
        from .fontlib import ProducerError
        try:
            made = producer.produce(req)
        except ProducerError as exc:
            item.issue("generation-failed", "info", f"{req.id}: {producer.id}: {exc}")
            return False
        files = made.get("files") or []
        if not files:
            return False
        names = self._variant_paths(req, files[0]["format"], len(files))
        errors = []
        for (_vid, relative), entry in zip(names, files):
            found, problems = validate_file(req.policy, relative, entry["data"],
                                            policy=self.policy)
            bad = [m for _, sev, m in problems if sev == "error"]
            if found is None or bad:
                errors.extend(bad or [f"{relative} is invalid"])
        if errors:
            item.issue("generation-failed", "warning",
                       f"{req.id}: {producer.id} made files the policy refuses: "
                       + "; ".join(errors[:4]))
            return False
        stored = [self._store(relative, entry["data"], entry["format"])
                  for (_vid, relative), entry in zip(names, files)]
        directory = self._directory(req, files[0]["format"])
        for name, data in made.get("extra") or []:
            # Companion files that ship beside the asset (a font's OFL.txt).
            self.store.write(f"{directory}/{name}", data)
        item.variants = [vid for vid, _ in names] if len(names) > 1 else []
        faces = {vid: {k: entry[k] for k in ("family", "weight") if entry.get(k)}
                 for (vid, _relative), entry in zip(names, files)}
        if any(faces.values()):
            item.faces = faces
        origin = dict(made.get("origin") or {"kind": "generated", "generator": producer.id})
        item.data["source"] = getattr(producer, "source", "procedural")
        item.data["origin"] = origin
        item.data["placeholder"] = False
        item.quality_author = made.get("author") or f"builtin:{producer.id}"
        verdict = self._license(item, made.get("license"))
        if verdict.status != "generated":
            self._check_clearance(item, verdict, origin)
        self._record_files(item, stored)
        optimization = self._optimization(req, stored)
        done = set(made.get("done") or []) & set(req.policy.optimize)
        if done:
            optimization["applied"] = list(optimization["applied"]) + sorted(done)
            optimization["deferred"] = [s for s in optimization["deferred"] if s not in done]
        item.data["optimization"] = optimization
        item.generation = made.get("metadata")
        item.data["notes"] = " ".join(filter(None, [req.notes, made.get("notes")]))
        item.data["status"] = "delivered"
        self._log("produced", asset=req.id, producer=producer.id, files=len(stored))
        return True

    # -- library.json, author, model author -------------------------------------------------

    def _variant_paths(self, req, fmt, n_files):
        """[(runtime id, repository-relative path)] for `n_files` files of `req`."""
        ids = req.variant_ids()
        if n_files > 1 and not ids:
            ids = [req.id] + [f"{req.id}-{n}" for n in range(2, n_files + 1)]
        ids = ids[:n_files] if ids else [req.id]
        ext = formats.FORMAT_EXTENSION.get(fmt, fmt)
        directory = self._directory(req, fmt)
        return [(vid, f"{directory}/{vid}.{ext}") for vid in ids]

    def _mapped_library(self, req, item):
        """Files a library.json maps to the requirement (by id, then role)."""
        for entry in match_all(self.libraries, req):
            verdict = self.policy.classify_license(entry.license)
            if verdict.status not in ("verified", "generated"):
                item.issue("library-candidate-rejected", "info",
                           f"{req.id}: passed over {entry.qualified_id}: "
                           f"{verdict.reason or entry.license + ' is restricted'}")
                continue
            if not any((entry.source_url, entry.author, entry.vendor, entry.evidence)):
                item.issue("library-candidate-rejected", "info",
                           f"{req.id}: passed over {entry.qualified_id}: no source, author, "
                           f"vendor or evidence recorded")
                continue
            try:
                found_files = entry.absolute_paths()
                blobs = []
                for relative, path in found_files:
                    with open(path, "rb") as handle:
                        blobs.append((relative, handle.read()))
            except (OSError, LibraryError) as exc:
                item.issue("library-candidate-rejected", "info",
                           f"{req.id}: passed over {entry.qualified_id}: unreadable: {exc}")
                continue
            if not blobs:
                continue
            wanted = max(1, req.count)
            blobs = blobs[:wanted]
            checked, errors = [], []
            for relative, data in blobs:
                found, problems = validate_file(req.policy, relative, data, policy=self.policy)
                bad = [m for _, sev, m in problems if sev == "error"]
                if found is None or bad:
                    errors.extend(bad or [f"{relative} is invalid"])
                checked.append((data, found))
            if errors:
                item.issue("library-candidate-rejected", "info",
                           f"{req.id}: passed over {entry.qualified_id}: "
                           + "; ".join(errors[:4]))
                continue
            names = self._variant_paths(req, checked[0][1].format, len(checked))
            stored = [self._store(path, data, found.format)
                      for (vid, path), (data, found) in zip(names, checked)]
            item.variants = [vid for vid, _ in names] if len(names) > 1 else []
            item.short = (len(names), wanted) if len(names) < wanted else None
            if item.short:
                # Each counted drawing is one the game shows (a tower level, an enemy kind):
                # a short set leaves some undrawn, so a load-bearing one fails its quality.
                item.issue("variants-short",
                           "error" if req.scope_tier in LOAD_BEARING_TIERS else "warning",
                           f"{req.id}: {entry.qualified_id} supplies {len(names)} of the "
                           f"{wanted} drawings the design asks for")
            origin = {"kind": "library", "library_id": entry.qualified_id}
            for key in ORIGIN_KEYS:
                if getattr(entry, key, None):
                    origin[key] = getattr(entry, key)
            item.data["source"] = "library"
            item.data["origin"] = origin
            item.data["placeholder"] = False
            item.quality_author = f"library:{entry.qualified_id}"
            verdict = self._license(item, entry.license, entry.usage_constraints)
            self._check_clearance(item, verdict, origin)
            self._record_files(item, stored)
            item.data["optimization"] = self._optimization(req, stored)
            item.data["status"] = "delivered"
            self._log("library asset", asset=req.id, library_id=entry.qualified_id)
            return True
        return False

    @staticmethod
    def _authorable(req):
        """A 2D kind that may be delivered as SVG, outside an atlas (atlases pack PNG)."""
        return (req.dimension == "2d" and "svg" in req.policy.formats and not req.atlas
                and not req.policy.companion)

    def _judge_svg(self, req, relative, data):
        """([problem], quality) of one SVG for `req`."""
        found, file_problems = validate_file(req.policy, relative, data, policy=self.policy)
        problems = [m for _, sev, m in file_problems if sev == "error"]
        if found is None:
            problems = problems or [f"{relative} is not an SVG document"]
        elif found.format != "svg":
            problems.append(f"{relative} is {found.format}, not SVG")
        judged = quality_mod.svg_quality(
            data, role=req.role, palette=self.palette, bars=self.bars,
            spec_size=(req.width, req.height) if req.width and req.height else None,
            primitive_style=self.primitive_style,
            author=self.author.label if self.author else None)
        return problems + quality_mod.problems(judged), judged

    def _author_key(self, req, vid, n):
        """What an authored file was made from: a changed description, palette, bar or
        author re-asks; nothing else does."""
        basis = {"id": req.id, "variant": vid, "n": n, "type": req.design_type or req.kind,
                 "kind": req.kind, "role": req.role, "description": req.description,
                 "readability": req.readability, "spec": req.spec, "count": req.count,
                 "size": [req.width, req.height],
                 "palette": [[t, list(c)] for t, c in self.palette],
                 "primitive_style": self.primitive_style, "bars": self.bars.version,
                 "author": self.author.label if self.author else None}
        text = json.dumps(basis, sort_keys=True, separators=(",", ":"), default=str)
        return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()

    def _ledger_entries(self):
        if self._ledger is None:
            self._ledger = {}
            try:
                raw = self.store.read(LEDGER_PATH)
            except StoreError:
                raw = None
            if raw:
                try:
                    document = json.loads(raw.decode("utf-8"))
                    if document.get("format") == LEDGER_FORMAT:
                        self._ledger = dict(document.get("files") or {})
                except (UnicodeDecodeError, ValueError, AttributeError):
                    self._ledger = {}
        return self._ledger

    def _write_ledger(self):
        if not self._ledger_dirty:
            return
        document = {"format": LEDGER_FORMAT, "version": 1, "files": self._ledger}
        self.store.write(LEDGER_PATH, (json.dumps(document, indent=2, sort_keys=True)
                                       + "\n").encode("utf-8"))

    def _reusable(self, relative, key):
        record = self._ledger_entries().get(relative)
        if not isinstance(record, dict) or record.get("key") != key:
            return None
        try:
            data = self.store.read(relative)
        except StoreError:
            return None
        if data is None or file_hash(data) != record.get("hash"):
            return None
        return data

    def _author_request(self, req, vid, n, relative, notes, repair):
        identity = self.identity
        request = {
            "title_id": self.title_id,
            "asset": {"id": req.id, "variant": vid, "variant_index": n,
                      "count": req.count, "type": req.design_type or req.kind,
                      "kind": req.kind, "role": req.role, "dimension": req.dimension,
                      "tier": req.design_tier or req.scope_tier,
                      "description": req.description or req.label,
                      "readability": req.readability, "spec": req.spec,
                      "width": req.width, "height": req.height,
                      "transparency": req.policy.transparency},
            "palette": [{"token": e.get("token"), "hex": e.get("hex"), "role": e.get("role")}
                        for e in identity.get("palette") or [] if isinstance(e, dict)],
            "visual_identity": {k: identity.get(k) for k in (
                "concept", "shape_language", "texture", "avoid", "primitive_style")
                if identity.get(k) is not None},
            "quality_bars": self.bars.summary(req.role),
            "format": "svg",
            "destination": relative,
            # The playbooks the drawing follows: silhouettes, palette, the style kit.
            "craft": [os.path.join(paths.CORE, "craft", name) for name in AUTHOR_CRAFT],
        }
        if notes:
            request["notes"] = list(notes)
        if repair:
            request["repair"] = repair
        return request

    def _same_as(self, vid, data, siblings):
        """Problems when `data` has the silhouette of an accepted sibling variant."""
        out = []
        for other, other_data in siblings:
            found = quality_mod.variants_distinct([(other, other_data, "svg"), (vid, data, "svg")],
                                                  self.bars)
            if found and found[0]["status"] == "fail":
                distance = next(iter(found[1]["pairs"].values()), 0.0)
                out.append(f"variants.distinct: {vid} has the silhouette of {other} (they "
                           f"differ by {distance:.2f}; the bar is {found[1]['bar']:.2f}) - draw "
                           f"this variant as its own shape and size, never a recolour of "
                           f"{other} or the same drawing with another numeral")
        return out

    def _ask_author(self, req, vid, n, relative, notes, siblings=()):
        """(bytes, quality, problems): the first file that passes, or None and why not.
        `siblings`: [(variant id, bytes)] already accepted for the same requirement; a file
        with one's silhouette is sent back like any failed check."""
        work = os.path.join(self.work_dir or tempfile.gettempdir(), "author")
        repair, judged, problems = None, None, []
        for round_ in range(self.author.repair_rounds + 1):
            stem = f"{vid}-{round_}"
            output = os.path.join(work, f"{stem}.svg")
            request = self._author_request(req, vid, n, relative, notes, repair)
            if siblings:
                request["siblings"] = [{"variant": other, "destination":
                                        f"{self._directory(req, 'svg')}/{other}.svg"}
                                       for other, _data in siblings]
            try:
                data = self.author.write(request, output, work, stem)
            except (AuthorRunFailed, AuthorError) as exc:
                return None, judged, [str(exc)]
            problems, judged = self._judge_svg(req, relative, data)
            problems = list(problems) + self._same_as(vid, data, siblings)
            self._log("authored", asset=vid, round=round_, problems=len(problems))
            if not problems:
                return data, judged, []
            kept = os.path.join(work, f"{stem}.rejected.svg")
            os.replace(output, kept)
            repair = {"round": round_ + 1, "problems": problems[:40], "previous": kept}
        return None, judged, problems

    def _authored(self, req, item):
        ids = req.variant_ids() or [req.id]
        notes = self.rebuild.get(req.id)
        stored, judged_all = [], []
        for n, vid in enumerate(ids, 1):
            relative = f"{self._directory(req, 'svg')}/{vid}.svg"
            key = self._author_key(req, vid, n)
            data = None if notes else self._reusable(relative, key)
            judged = None
            siblings = [(other, entry.data) for other, entry in zip(ids, stored)]
            if data is not None:
                problems, judged = self._judge_svg(req, relative, data)
                if problems or self._same_as(vid, data, siblings):
                    data = None
            if data is None:
                data, judged, problems = self._ask_author(req, vid, n, relative, notes,
                                                          siblings)
                if data is None:
                    rounds = self.author.repair_rounds
                    item.issue("author-rejected", "warning",
                               f"{vid}: the author's file was not accepted after {rounds} "
                               f"repair round(s): " + "; ".join(problems[:6]))
                    return False
            entry = self._store(relative, data, "svg")
            stored.append(entry)
            judged_all.append((vid, judged))
            record = {"key": key, "hash": file_hash(entry.data), "author": self.author.label}
            if self._ledger_entries().get(relative) != record:
                self._ledger_entries()[relative] = record
                self._ledger_dirty = True
        item.variants = ids if len(ids) > 1 else []
        item.data["source"] = "ai-generated"
        item.data["origin"] = {"kind": "generated", "generator": self.author.label}
        item.data["placeholder"] = False
        item.quality_author = self.author.label
        item.quality = _merge_quality(judged_all, self.author.label)
        self._license(item, GENERATED_LICENSE)
        self._record_files(item, stored)
        item.data["optimization"] = self._optimization(req, stored)
        item.data["status"] = "delivered"
        if notes:
            item.data["notes"] = " ".join(filter(None, [
                item.data.get("notes"), f"Rebuilt for {len(notes)} finding(s)."]))
        return True

    def _model_authored(self, req, item):
        """A 3D requirement through wgf_assets.model_author.produce_model."""
        out_dir = os.path.join(self.work_dir or tempfile.gettempdir(), "models", req.id)
        os.makedirs(out_dir, exist_ok=True)
        requirement = {"id": req.id, "kind": req.kind, "type": req.design_type or req.kind,
                       "role": req.role, "dimension": req.dimension,
                       "description": req.description or req.label,
                       "readability": req.readability, "spec": req.spec, "count": req.count,
                       "tier": req.design_tier or req.scope_tier, "model": req.model,
                       "notes": self.rebuild.get(req.id)}
        try:
            made = self.model_author(requirement, self.identity, out_dir,
                                     (self.settings or {}).get("model_author") or {},
                                     self.context)
        except Exception as exc:  # ModelAuthorError, or a bug: never breaks the pipeline
            label = "" if type(exc).__name__ == "ModelAuthorError" else \
                f"{type(exc).__name__}: "
            item.issue("generation-failed", "warning", f"{req.id}: model author: {label}{exc}")
            return False
        files = [f for f in (made or {}).get("files") or [] if isinstance(f, str)]
        checked, errors = [], []
        for path in files:
            try:
                with open(path, "rb") as handle:
                    data = handle.read()
            except OSError as exc:
                errors.append(f"{path}: {exc}")
                continue
            found, problems = validate_file(req.policy, os.path.basename(path), data,
                                            policy=self.policy)
            bad = [m for _, sev, m in problems if sev == "error"]
            if found is None or bad:
                errors.extend(bad or [f"{os.path.basename(path)} is invalid"])
            checked.append((data, found))
        if errors or not checked:
            item.issue("generation-failed", "warning",
                       f"{req.id}: model author produced nothing usable: "
                       + ("; ".join(errors[:4]) or "no files"))
            return False
        names = self._variant_paths(req, checked[0][1].format, len(checked))
        stored = [self._store(path, data, found.format)
                  for (vid, path), (data, found) in zip(names, checked)]
        item.variants = [vid for vid, _ in names] if len(names) > 1 else []
        source = made.get("source") if made.get("source") in SOURCES else "ai-generated"
        generator = str(made.get("source") or "model-author")
        item.data["source"] = source
        item.data["origin"] = {"kind": "generated", "generator": generator}
        item.data["placeholder"] = bool(made.get("placeholder"))
        quality = made.get("quality")
        if isinstance(quality, dict) and quality.get("verdict"):
            item.quality = quality
        item.quality_author = (quality or {}).get("author") if isinstance(quality, dict) \
            else None
        verdict = self._license(item, made.get("license") or GENERATED_LICENSE)
        if verdict.status != "generated":
            self._check_clearance(item, verdict, item.data["origin"],
                                  placeholder=item.data["placeholder"])
        self._record_files(item, stored)
        item.data["optimization"] = self._optimization(req, stored)
        if made.get("notes"):
            item.data["notes"] = " ".join(filter(None, [item.data.get("notes"),
                                                        str(made["notes"])]))
        item.data["status"] = "in-progress" if item.data["placeholder"] else "delivered"
        if item.data["placeholder"]:
            item.issue("placeholder", "info",
                       f"{req.id}: placeholder from the model author; the final asset is "
                       f"still owed")
        return True

    # -- quality -------------------------------------------------------------------------

    def _judge(self, item):
        """Set item.data["quality"]; a failed verdict is an issue."""
        data, req = item.data, item.req
        if data["status"] in ("planned", "cut"):
            return
        generator = (data.get("origin") or {}).get("generator")
        if item.quality is not None:
            judged = item.quality
        elif data.get("placeholder"):
            judged = quality_mod.skipped(
                "placeholder", "a placeholder is not judged; the final asset is still owed")
        elif not item.payload:
            judged = quality_mod.skipped(
                f"builtin:{generator}" if generator else None,
                "no file to judge" + (f": {data.get('reference')}" if data.get("reference")
                                      else ""))
        else:
            author = item.quality_author or (f"builtin:{generator}" if generator else
                                             (f"library:{data['origin'].get('library_id')}"
                                              if (data.get("origin") or {}).get("library_id")
                                              else "existing"))
            files = self._image_files(item)
            fonts = [(relative, blob) for relative, blob in item.payload
                     if quality_mod.font_format(blob)]
            models = [(relative, blob) for relative, blob in item.payload
                      if bytes(blob[:4]) == b"glTF"]
            sounds = [(relative, blob) for relative, blob in item.payload
                      if req.kind in AUDIO_KINDS and _is_audio(blob)]
            if sounds:
                licensed = data.get("license_status") in ("verified", "generated")
                judged = _merge_quality(
                    [(relative, quality_mod.audio_quality(
                        blob, kind=req.kind, loop=req.loop, min_duration_s=req.min_duration_s,
                        max_bytes=req.policy.max_bytes, license_ok=licensed, bars=self.bars,
                        author=author)) for relative, blob in sounds], author)
                judged = self._rendered_checks(item, judged)
            elif fonts and not files:
                judged = _merge_quality([(relative, quality_mod.font_quality(
                    blob, locales=self.locales, bars=self.bars, author=author))
                                         for relative, blob in fonts], author)
            elif models and not files:
                # A GLB from a library (or the repository) is judged like a built one: the
                # model inspection - parts, normals, palette, primitive_only for its role.
                from . import model_quality
                judged = _merge_quality(
                    [(relative, model_quality.assess(
                        blob, role=req.role, visual_identity=self.identity,
                        spec=req.model, kind=req.kind or "model", name=req.id,
                        policy=self.policy, author=author)["quality"])
                     for relative, blob in models], author)
            elif not files:
                fmt = data["files"][0]["format"] if data.get("files") else "?"
                judged = quality_mod.skipped(author, f"no 2D quality check for {fmt}; "
                                                     f"a GLB is judged by its model inspection")
            else:
                results = []
                for vid, relative, blob, fmt in files:
                    if fmt == "svg":
                        results.append((vid, quality_mod.svg_quality(
                            blob, role=req.role, palette=self.palette, bars=self.bars,
                            spec_size=(req.width, req.height) if req.width and req.height
                            else None, primitive_style=self.primitive_style, author=author)))
                    else:
                        results.append((vid, quality_mod.raster_quality(
                            blob, needs_alpha=req.policy.transparency == "required",
                            bars=self.bars, author=author)))
                judged = _merge_quality(results, author)
        if item.variants and item.payload and not data.get("placeholder") \
                and judged.get("verdict") != "skipped":
            # A counted requirement's drawings are told apart by shape: a recolour or a
            # changed numeral is the same drawing (asset-quality.yaml `variants`). Whoever
            # judged the files one by one (an author's own loop included), the set is
            # judged here.
            files = self._image_files(item)
            distinct = quality_mod.variants_distinct(
                [(vid, blob, fmt) for vid, _relative, blob, fmt in files], self.bars) \
                if len(files) > 1 else None
            if distinct:
                checks = [c for c in judged.get("checks") or [] if c["id"] != "variants.distinct"]
                judged = dict(judged, checks=checks + [distinct[0]])
                if distinct[0]["status"] == "fail":
                    judged["verdict"] = "fail"
        if item.short and judged.get("verdict") != "skipped":
            supplied, wanted = item.short
            judged = dict(judged, verdict="fail", checks=list(judged.get("checks") or []) + [
                {"id": "variants.count", "status": "fail",
                 "summary": f"{supplied} of the {wanted} drawings the design counts were "
                            f"delivered: drawings {supplied + 1}-{wanted} are missing"}])
        data["quality"] = judged
        if judged["verdict"] == "fail":
            severity = "error" if req.scope_tier in LOAD_BEARING_TIERS else "warning"
            item.issue("quality-failed", severity,
                       f"{req.id}: " + "; ".join(quality_mod.problems(judged)[:4]))

    def _rendered_checks(self, item, judged):
        """A producer that measured its own PCM before encoding (sound.producer) adds what
        the standard library cannot read back from an Ogg file: the level and the seam."""
        measured = ((item.generation or {}).get("measured") or {}) if isinstance(
            item.generation, dict) else {}
        if not measured:
            return judged
        bars = self.bars.audio
        checks = list(judged.get("checks") or [])
        loudest = measured.get("loudest_s_dbfs")
        rms = measured.get("rms_dbfs")
        level = loudest if loudest is not None else rms
        if level is not None:
            checks.append({"id": "audio.rendered-level",
                           "status": "pass" if level >= bars.min_rms_dbfs else "fail",
                           "summary": f"measured before encoding: RMS {rms} dBFS, peak "
                                      f"{measured.get('peak_dbfs')} dBFS"
                                      + (f", loudness {measured['lufs']} LUFS"
                                         if measured.get("lufs") is not None else "")
                                      + f"; floor {bars.min_rms_dbfs:g} dBFS"})
        seam = measured.get("seam")
        if seam and item.req.loop:
            ok = seam["ratio"] <= bars.seam_ratio and seam["edge_db"] <= bars.seam_edge_db
            checks.append({"id": "audio.rendered-seam", "status": "pass" if ok else "fail",
                           "summary": f"measured before encoding: end-to-start jump "
                                      f"{seam['ratio']}x the typical step (bar "
                                      f"{bars.seam_ratio:g}x), edges differ {seam['edge_db']}"
                                      f" dB (bar {bars.seam_edge_db:g} dB)"})
        verdict = "fail" if any(c["status"] == "fail" for c in checks) else judged["verdict"]
        return dict(judged, checks=checks, verdict=verdict)

    def _image_files(self, item):
        """[(runtime id, path, bytes, format)] of the SVG/PNG drawings of an item (not an
        atlas descriptor)."""
        out = []
        ids = item.variants or [item.req.id]
        drawings = [(p, b) for p, b in item.payload if not p.endswith(".json")]
        for vid, (relative, blob) in zip(ids + [item.req.id] * len(drawings), drawings):
            found = formats.sniff(blob)
            if found is not None and found.format in ("svg", "png"):
                out.append((vid, relative, blob, found.format))
        return out

    # -- licence, provenance, files --------------------------------------------------------

    def _license(self, item, license_id, extra_constraints=()):
        verdict = self.policy.classify_license(license_id)
        item.data["license"] = license_id or None
        item.data["license_status"] = verdict.status
        constraints = list(dict.fromkeys(list(verdict.constraints) + list(extra_constraints)))
        item.data["usage_constraints"] = constraints or None
        return verdict

    def _check_clearance(self, item, verdict, origin, *, placeholder=False):
        """The licence and provenance issues of an asset the Factory did not make itself."""
        rid = item.req.id
        severity = "warning" if placeholder else "error"
        if verdict.status == "unknown":
            item.issue("license-unknown", severity,
                       f"{rid}: {verdict.reason}; usable to prototype, never production-ready")
        elif verdict.status == "restricted":
            item.issue("license-restricted", severity,
                       f"{rid}: {item.data['license']} is restricted ({verdict.reason})")
        if origin["kind"] != "generated" and not any(
                origin.get(key) for key in ("source_url", "author", "vendor", "evidence")):
            item.issue("provenance-missing", "error",
                       f"{rid}: no source_url, author, vendor or evidence recorded")
        if "attribution" in (item.data.get("usage_constraints") or []) and not origin.get(
                "attribution"):
            item.issue("provenance-missing", "warning",
                       f"{rid}: {item.data['license']} requires attribution and none is "
                       f"recorded")

    def _check_spec_built(self, req, item):
        """A design that described its model and got a stand-in box has to hear about it."""
        if not modelspec.buildable(req.model):
            return
        generator = (item.data.get("origin") or {}).get("generator") or ""
        if generator.startswith("blender"):
            return
        blender = next((b for b_id, b, _n in self.backends if b_id == "blender"), None)
        required = bool(getattr(blender, "required", False))
        if blender is None:
            reason = "the blender backend is not available"
        else:
            reason = (getattr(blender, "refusal", None)
                      or "its build failed; see this item's generation-failed issue")
        stand_in = generator or "a placeholder"
        item.issue("model-spec-unbuilt", "error" if required else "warning",
                   f"{req.id}: its model spec was not built ({reason}); {stand_in} stands in, "
                   f"without the declared parts, clips, LODs or collision proxy")

    def _model(self, item, entry):
        """The `model` block of a GLB item, and the spec's expectations checked against it."""
        req = item.req
        inspection = gltf.inspect(entry.data, name=entry.relative, kind=req.kind)
        if inspection.summary is None:
            return  # validate_file already recorded why
        block = dict(inspection.summary)
        if item.generation:
            block["generation"] = item.generation
        item.data["model"] = block
        generator = (item.data.get("origin") or {}).get("generator") or ""
        if item.data.get("placeholder") and not generator.startswith("blender"):
            # A stand-in box is not held to the design's clips, LODs or budgets: the
            # placeholder and model-spec-unbuilt issues already say it is not the asset.
            return
        expect = modelspec.expectations(req.model, req.policy)
        for code, severity, message in gltf.check_expectations(block, expect, entry.data,
                                                               name=entry.relative):
            item.issue(code, severity, f"{req.id}: {message}")

    def _directory(self, req, fmt):
        """public/assets/<dir>, or src/assets/<dir> for an atlas member the packer can read."""
        base = SOURCE_DIR if req.atlas and fmt == "png" else ASSET_DIR
        return f"{base}/{req.policy.directory}"

    def _record_files(self, item, stored):
        item.payload = [(entry.relative, entry.data) for entry in stored]
        req = item.req
        if stored and stored[0].found is not None and stored[0].found.format in MODEL_FORMATS:
            self._model(item, stored[0])
        for entry in stored:
            owner = self._paths.setdefault(entry.relative, req.id)
            if owner != req.id:
                item.issue("duplicate-path", "error",
                           f"{req.id}: {entry.relative} is already the file of {owner}; two "
                           f"assets cannot share one file")
        image = stored[0].found if stored else None
        if image is not None and image.width and req.kind not in ("spritesheet", "animation"):
            if req.width or req.height:
                expected = req.pixel_size()
                if (image.width, image.height) != expected:
                    item.issue("dimension-mismatch", "warning",
                               f"{req.id}: {stored[0].relative} is {image.width}x{image.height}"
                               f"; the design asks {expected[0]}x{expected[1]} "
                               f"({req.scale}x of {req.size()[0]}x{req.size()[1]})")
            if req.policy.tiles:
                tw, th = (edge * int(req.scale) for edge in req.tile_size())
                if image.width % tw or image.height % th:
                    item.issue("invalid-tileset", "error",
                               f"{req.id}: {image.width}x{image.height} does not divide into "
                               f"{tw}x{th} tiles")
        files = []
        for entry in stored:
            digest = file_hash(entry.data)
            record = {"path": entry.relative, "format": entry.found.format,
                      "bytes": len(entry.data), "content_hash": digest}
            if entry.found.width:
                record["width"], record["height"] = entry.found.width, entry.found.height
            files.append(record)
            first = self._hashes.setdefault(digest, item.req.id)
            if first != item.req.id:
                item.issue("duplicate-content", "warning",
                           f"{entry.relative} is byte-identical to a file of {first}; "
                           f"ship one copy")
        item.data["files"] = files

    def _store(self, relative, data, fmt):
        """Optimize (when enabled) and write. The bytes actually written."""
        original = len(data)
        applied = []
        if self.optimize:
            data, applied = optimize_bytes(data, fmt)
        self.store.write(relative, data)
        return _Stored(relative, data, formats.sniff(data), applied, original - len(data))

    @staticmethod
    def _optimization(req, stored):
        applied = []
        for entry in stored:
            applied.extend(step for step in entry.applied if step not in applied)
        block = {"applied": applied, "deferred": list(req.policy.optimize)}
        saved = sum(entry.saved for entry in stored)
        if saved > 0:
            block["bytes_saved"] = saved
        return block

    # -- atlas groups ----------------------------------------------------------------------

    def _pack_atlases(self, built, result):
        """{group: (runtime atlas record, [(path, bytes)])} of the groups that packed."""
        groups = {}
        for item in built:
            if item.req.atlas and item.data["status"] != "planned" and item.payload:
                groups.setdefault(item.req.atlas, []).append(item)
        packed = {}
        directory = f"{ASSET_DIR}/{self.policy.atlas_directory}"
        for group in sorted(groups):
            members = []
            for item in sorted(groups[group], key=lambda i: i.req.id):
                relative, data = item.payload[0]
                try:
                    members.append((item, raster.decode_png(data)))
                except raster.RasterError as exc:
                    item.issue("invalid-atlas", "error",
                               f"{item.req.id}: {relative} cannot join atlas {group}: {exc}; "
                               f"supply a PNG")
            scales = sorted({item.req.scale for item, _ in members})
            if len(scales) > 1:
                for item, _ in members:
                    item.issue("invalid-atlas", "error",
                               f"{item.req.id}: atlas {group} mixes scales "
                               f"{', '.join(f'{s}x' for s in scales)}; one atlas, one scale")
                continue
            if not members:
                continue
            try:
                image, frames = atlases_mod.pack([(item.req.id, img) for item, img in members],
                                                 self.policy.atlas_options)
            except atlases_mod.AtlasError as exc:
                for item, _ in members:
                    item.issue("atlas-overflow", "error", f"{item.req.id}: atlas {group}: {exc}")
                continue
            png_path = f"{directory}/{group}.png"
            json_path = f"{directory}/{group}.json"
            png = raster.encode_png(image)
            document = atlases_mod.atlas_document(frames, f"{group}.png",
                                                  (image.width, image.height),
                                                  scale=scales[0])
            self.store.write(png_path, png)
            self.store.write(json_path, document)
            files = [{"path": png_path, "format": "png", "bytes": len(png),
                      "content_hash": file_hash(png), "width": image.width,
                      "height": image.height},
                     {"path": json_path, "format": "json", "bytes": len(document),
                      "content_hash": file_hash(document)}]
            result.atlases.append({"id": group, "files": files,
                                   "members": [item.req.id for item, _ in members]})
            packed[group] = ({"url": runtime.url_for(png_path),
                              "data": runtime.url_for(json_path),
                              "width": image.width, "height": image.height,
                              "scale": scales[0], "frames": sorted(frames)},
                             [(png_path, png), (json_path, document)])
            for item, _ in members:
                item.data["atlas"] = {"id": group, "frame": item.req.id}
                block = item.data.setdefault("optimization", {"applied": [], "deferred": []})
                if "texture-atlas" not in block["applied"]:
                    block["applied"].append("texture-atlas")
                block["deferred"] = [d for d in block["deferred"] if d != "texture-atlas"]
                if item.payload[0][0].startswith(runtime.PUBLIC + "/"):
                    item.issue("atlas-source-served", "warning",
                               f"{item.req.id}: {item.payload[0][0]} is packed into atlas "
                               f"{group} and also served on its own; move it under "
                               f"{SOURCE_DIR}/ so it ships once")
            self._log("atlas", atlas=group, frames=len(frames),
                      size=f"{image.width}x{image.height}")
        return packed

    # -- the runtime manifest ----------------------------------------------------------------

    def _runtime_entry(self, item, packed):
        """(entry, payload) for the runtime manifest, or None when nothing loads."""
        data, req = item.data, item.req
        if data["status"] in ("planned", "cut"):
            return None
        entry = {"type": data["type"], "scale": req.scale if req.scale != 1 else None,
                 "placeholder": True if data.get("placeholder") else None,
                 "role": req.role}
        atlas = data.get("atlas")
        if atlas and atlas["id"] in packed:
            image = data["files"][0]
            entry.update({"atlas": atlas["id"], "frame": atlas["frame"],
                          "width": image.get("width"), "height": image.get("height")})
            return entry, []
        if not item.payload:
            if data.get("reference") and data["type"] == "font":
                entry["family"] = data["reference"]
                return entry, []
            return None
        relative, blob = item.payload[0]
        url = runtime.url_for(relative)
        if url is None or req.atlas:
            if not item.has_errors():
                item.issue("not-served", "warning",
                           f"{req.id}: {relative} is outside public/, so the runtime manifest "
                           f"cannot list it; move it under {ASSET_DIR}/ or import it in code")
            return None
        record = data["files"][0]
        entry.update({"url": url, "format": record["format"], "width": record.get("width"),
                      "height": record.get("height")})
        if data.get("model"):
            entry["model"] = self._runtime_model(data["model"])
        if req.kind in AUDIO_KINDS and _is_audio(blob):
            entry["audio"] = _runtime_audio(blob, req)
        payload = [(relative, blob)]
        if data["type"] == "font":
            entry["family"] = req.id
            if item.faces:
                entry.update(item.faces.get(item.variants[0] if item.variants else req.id)
                             or {})
        if req.policy.tiles and record.get("width"):
            tw, th = (edge * int(req.scale) for edge in req.tile_size())
            entry.update({"tile_width": tw, "tile_height": th,
                          "columns": max(1, record["width"] // tw),
                          "rows": max(1, record["height"] // th)})
        if len(item.payload) > 1 and item.payload[1][0].endswith(".json"):
            atlas_path, atlas_blob = item.payload[1]
            entry["data"] = runtime.url_for(atlas_path)
            payload.append((atlas_path, atlas_blob))
            try:
                document = json.loads(atlas_blob.decode("utf-8-sig"))
            except (UnicodeDecodeError, ValueError):
                document = {}
            names = atlases_mod.frames_of(document)
            entry["frames"] = names
            entry["animations"] = self._animations(item, document, names)
        return entry, payload

    def _variant_entries(self, item, entry):
        """{variant id: (entry, payload)}: one runtime entry per drawing of a counted
        requirement; the requirement's own entry is the first drawing and lists them."""
        if not item.variants or "url" not in entry:
            return {}
        out = {}
        files = item.data.get("files") or []
        for vid, record, (relative, blob) in zip(item.variants, files, item.payload):
            url = runtime.url_for(relative)
            if url is None:
                continue
            variant = {k: v for k, v in entry.items()
                       if k not in ("url", "width", "height", "variants", "model")}
            variant.update({"url": url, "format": record["format"],
                            "width": record.get("width"), "height": record.get("height")})
            if item.faces and item.faces.get(vid):
                variant.update(item.faces[vid])
            out[vid] = (variant, [(relative, blob)])
        entry["variants"] = list(item.variants)
        return out

    @staticmethod
    def _runtime_model(model):
        """What a 3D loader looks things up by: clip names, LOD and collision nodes."""
        block = {"clips": sorted(c["name"] for c in model.get("animations") or []),
                 "lods": [{"level": l["level"], "node": l["node"]}
                          for l in model.get("lods") or []],
                 "triangles": model.get("triangles")}
        if model.get("dimensions"):
            block["dimensions"] = model["dimensions"]
        if model.get("collision"):
            block["collision"] = {"node": model["collision"]["node"],
                                  "shape": model["collision"]["shape"]}
        return block

    @staticmethod
    def _animations(item, document, names):
        req = item.req
        declared = document.get("animations") if isinstance(document, dict) else None
        if req.animations is None and isinstance(declared, dict) and declared:
            specs = {name: {"frames": list(seq), "fps": 12, "loop": True}
                     for name, seq in sorted(declared.items()) if isinstance(seq, list)}
        else:
            specs = req.animation_specs(names)
        for name, spec in sorted(specs.items()):
            missing = [str(f) for f in spec["frames"] if f not in names]
            if missing:
                item.issue("invalid-atlas", "error",
                           f"{req.id}: animation {name!r} names frame(s) the sheet lacks: "
                           f"{', '.join(missing[:5])}")
        return specs

    # -- pruning -----------------------------------------------------------------------------

    def _prune(self, built, result):
        """Remove placeholders and packed atlases this pipeline wrote before that nothing
        references now - a renamed asset or a delivered final must not leave its stand-in
        shipping. Only files the pipeline's own naming marks as its own are candidates."""
        live = {path for item in built for path, _ in item.payload}
        live |= {f["path"] for a in result.atlases for f in a["files"]}
        stale = []
        for base in (ASSET_DIR, SOURCE_DIR):
            try:
                found = self.store.walk(base)
            except StoreError:
                continue
            for relative in found:
                name = relative.rsplit("/", 1)[-1]
                if relative in live:
                    continue
                if ".placeholder." in name:
                    stale.append(relative)
        atlas_dir = f"{ASSET_DIR}/{self.policy.atlas_directory}"
        try:
            candidates = [p for p in self.store.walk(atlas_dir) if p.endswith(".json")]
        except StoreError:
            candidates = []
        for relative in candidates:
            if relative in live:
                continue
            try:
                meta = json.loads(self.store.read(relative).decode("utf-8")).get("meta") or {}
            except (UnicodeDecodeError, ValueError, AttributeError):
                continue
            if meta.get("app") != atlases_mod.GENERATOR:
                continue
            stale.append(relative)
            image = f"{atlas_dir}/{meta.get('image')}"
            if isinstance(meta.get("image"), str) and "/" not in meta["image"] \
                    and image not in live:
                stale.append(image)
        for relative in sorted(set(stale)):
            self.store.remove(relative)
            self._log("pruned", path=relative)
        result.removed = list(self.store.removed)


def _runtime_audio(blob, req):
    """What a game's audio loader wants without decoding: length, channels, rate, looping."""
    from . import audiofile
    block = {"loop": bool(req.loop)}
    try:
        info = audiofile.read(blob)
    except audiofile.AudioError:
        return block
    block.update({"duration_s": round(info.duration_s, 4), "channels": info.channels,
                  "sample_rate": info.sample_rate})
    return block


def _merge_quality(results, author):
    """One `quality` object from [(drawing id, quality)]: the worst verdict, every check
    (named by drawing when there are several), the fewest parts, the most colours."""
    results = [(vid, q) for vid, q in results if q]
    if not results:
        return quality_mod.skipped(author, "nothing to judge")
    if len(results) == 1:
        merged = dict(results[0][1])
        merged["author"] = author
        return merged
    checks = []
    for vid, judged in results:
        for check in judged["checks"]:
            checks.append({"id": check["id"], "status": check["status"],
                           "summary": f"{vid}: {check['summary']}"})
    verdicts = {q["verdict"] for _v, q in results}
    verdict = "fail" if "fail" in verdicts else ("pass" if "pass" in verdicts else "skipped")
    parts = [q.get("parts") for _v, q in results if q.get("parts") is not None]
    colours = [q.get("colors") for _v, q in results if q.get("colors") is not None]
    prims = [q.get("primitive_only") for _v, q in results if q.get("primitive_only") is not None]
    return {"verdict": verdict, "checks": checks,
            "primitive_only": any(prims) if prims else None,
            "parts": min(parts) if parts else None,
            "colors": max(colours) if colours else None, "author": author}

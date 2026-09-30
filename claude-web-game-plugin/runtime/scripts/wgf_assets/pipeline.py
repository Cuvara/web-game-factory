"""The asset pipeline: classified requirements in, manifest items and issues out.

For each requirement, in order:

    existing file named by the design  -> validate, check licence and origin
        | missing or invalid
    library search (source library or unset) -> first candidate that is licensed, has an
        | nothing usable                       origin and validates; the rest are recorded
    placeholder backends, in order     -> first that is available and returns a valid file
        | all failed or disabled
    missing                            -> status planned, an error issue for mvp/prototype

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

from . import atlas as atlases_mod
from . import formats, gltf, modelspec, raster, runtime
from .library import LibraryError, search_all
from .optimize import optimize as optimize_bytes
from .placeholders import BackendError

__all__ = ["AssetPipeline", "AssetStore", "PipelineResult", "validate_file", "asset_path",
           "ASSET_DIR", "SOURCE_DIR"]

ASSET_DIR = "public/assets"
# Where the source image of an atlas member goes: in the repository, out of the build (Vite
# bundles src/ only through imports), so the atlas is the one copy that ships.
SOURCE_DIR = "src/assets"
MODEL_FORMATS = ("glb", "gltf")
LOAD_BEARING_TIERS = ("mvp", "prototype")
ORIGIN_KEYS = ("source_url", "author", "vendor", "attribution", "license_url", "evidence")


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
        }
        self.payload = []  # [(repository-relative path, bytes)] of the files, as recorded
        self.generation = None  # a generating backend's `model.generation` block

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
                and data.get("license_status") in ("verified", "generated"))
        if self.issues:
            data["issues"] = sorted({i["code"] for i in self.issues})
        order = ["id", "label", "type", "dimension", "source", "est_cost", "est_hours",
                 "status", "license", "license_status", "usage_constraints", "origin",
                 "placeholder", "production_ready", "files", "atlas", "scale", "reference",
                 "model", "optimization", "scope_tier", "platforms", "notes", "issues"]
        return {key: data[key] for key in order if data.get(key) is not None}


class AssetPipeline:
    def __init__(self, policy, store, backends, libraries=(), *, logger=None,
                 placeholders=True, optimize=True, runtime_manifest=True, prune=True,
                 title_id=None):
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
                built.append(self._process(req))
        finally:
            self.close()
        packed = self._pack_atlases(built, result)
        entries = {}
        if self.runtime_manifest:
            for item in built:
                made = self._runtime_entry(item, packed)
                if made is not None:
                    entries[item.req.id] = made
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
        if req.source in (None, "library") and self.libraries and self._library(req, item):
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
                 "placeholder": True if data.get("placeholder") else None}
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
        payload = [(relative, blob)]
        if data["type"] == "font":
            entry["family"] = req.id
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

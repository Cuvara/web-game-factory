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

from . import formats
from .library import LibraryError, search_all
from .optimize import optimize as optimize_bytes
from .placeholders import BackendError

__all__ = ["AssetPipeline", "AssetStore", "PipelineResult", "validate_file", "ASSET_DIR"]

ASSET_DIR = "public/assets"
LOAD_BEARING_TIERS = ("mvp", "prototype")
ORIGIN_KEYS = ("source_url", "author", "vendor", "attribution", "license_url", "evidence")


def file_hash(data):
    return "sha256:" + hashlib.sha256(data).hexdigest()


class StoreError(ValueError):
    pass


class AssetStore:
    """Files under the asset root. Paths are repository-relative with forward slashes, and
    none may leave the root."""

    def __init__(self, root):
        self.root = os.path.abspath(root)
        self.writes = {"created": 0, "updated": 0, "reused": 0}

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


def validate_file(kind, relative, data, *, companion=False):
    """(Detected or None, [(code, severity, message)]) for one file of an asset kind."""
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
    return found, problems


_Stored = namedtuple("_Stored", "relative data found applied saved")


class PipelineResult:
    def __init__(self):
        self.items = []
        self.issues = []
        self.backends = []
        self.bytes_total = 0


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
        }

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
                 "placeholder", "production_ready", "files", "reference", "optimization",
                 "scope_tier", "platforms", "notes", "issues"]
        return {key: data[key] for key in order if data.get(key) is not None}


class AssetPipeline:
    def __init__(self, policy, store, backends, libraries=(), *, logger=None,
                 placeholders=True, optimize=True):
        self.policy = policy
        self.store = store
        self.backends = backends  # [(id, backend or None, note)]
        self.libraries = list(libraries)
        self.logger = logger
        self.placeholders = placeholders
        self.optimize = optimize
        self._hashes = {}
        self._available = None
        self._used = {}

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
        try:
            for req in requirements:
                item = self._process(req)
                result.issues.extend(item.issues)
                result.items.append(item.finish())
        finally:
            self.close()
        if self._available is not None:
            for entry in self._report:
                entry["used"] = self._used.get(entry["id"], 0)
            result.backends = self._report
        else:
            result.backends = [{"id": b_id, "available": False, "used": 0,
                                "note": "not needed: nothing was generated"}
                               for b_id, _b, _n in self.backends]
        result.bytes_total = sum(f["bytes"] for i in result.items for f in i.get("files", []))
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
        found, problems = validate_file(req.policy, relative, data)
        for code, severity, message in problems:
            item.issue(code, severity, f"{req.id}: {message}")
        if found is None or any(code in ("invalid-format", "format-not-allowed")
                                for code, _, _ in problems):
            return False

        origin = {"kind": "external"}
        for key in ORIGIN_KEYS:
            if existing.get(key):
                origin[key] = existing[key]
        item.data["source"] = req.source or "library"
        item.data["origin"] = origin
        verdict = self._license(item, existing.get("license"),
                                existing.get("usage_constraints") or ())
        self._check_clearance(item, verdict, origin)
        # The design's own file is recorded, not rewritten: optimizing it in place would
        # change bytes someone else owns. What it still needs is deferred to the build.
        self._record_files(item, [_Stored(relative, data, found, [], 0)])
        item.data["optimization"] = {"applied": [], "deferred": list(req.policy.optimize)}
        cleared = verdict.status in ("verified", "generated") and not item.has_errors()
        item.data["status"] = "delivered" if cleared else "sourced"
        return True

    def _library(self, req, item):
        for entry in search_all(self.libraries, req):
            reason, payload = self._library_candidate(req, entry)
            if reason:
                item.issue("library-candidate-rejected", "info",
                           f"{req.id}: passed over {entry.qualified_id}: {reason}")
                continue
            fmt = payload[0][1]
            base = f"{ASSET_DIR}/{req.policy.directory}/{req.id}"
            names = [f"{base}.{formats.FORMAT_EXTENSION.get(fmt, fmt)}", f"{base}.atlas.json"]
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
        found, problems = validate_file(req.policy, entry.path, data)
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
            for gen in generated.files:
                ext = formats.FORMAT_EXTENSION.get(gen.format, gen.format)
                relative = (f"{ASSET_DIR}/{req.policy.directory}/{req.id}.placeholder"
                            f"{gen.suffix}.{ext}")
                found, file_problems = validate_file(req.policy, relative, gen.data,
                                                     companion=bool(gen.suffix))
                errors = [m for _, severity, m in file_problems if severity == "error"]
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
            item.data["placeholder"] = True
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
            item.data["status"] = "in-progress"
            if failures:
                item.issue("generation-failed", "info",
                           f"{req.id}: fell back to {backend.id}: " + " | ".join(failures))
            item.issue("placeholder", "info",
                       f"{req.id}: placeholder from {backend.id}; the final asset is still owed")
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

    def _record_files(self, item, stored):
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

"""Blender as an offline build tool: find it, pin it, run it headless, and a backend on top.

Blender never reaches a browser. It turns a model spec (modelspec.py) into a GLB, the file a
game's three.js GLTFLoader reads; everything after the export - validation, the manifest, the
runtime index - is standard-library Python that does not need Blender at all.

Discovery, in order, never a hard-coded install path:

    1. `executable` in factory.assets.placeholders.blender (workspace/config/factory.yaml)
    2. $WGF_BLENDER
    3. `blender` on PATH

The version is read from `blender --version` and held to the series pinned in
core/reference/asset-policy.yaml (`toolchains.blender`): the same spec under another
Blender series can export different bytes, and a Factory where two machines build two
different "same" assets cannot say which one it shipped. Another series is refused unless the
installation opts in with `allow_unpinned: true`, and then every file it makes says so.

The build runs as

    blender --background --factory-startup -noaudio [--offline-mode] --python-exit-code 3 \
        --python blender_scripts/build_model.py -- --spec S --textures D --out O --report R

through wgflib.procs (owned process tree, timeout, heartbeat), with an environment of its
own: no user preferences, add-ons or startup file, and HOME and Blender's user directories
pointing into the build's scratch directory, so nothing on the machine leaks into the bytes.

A build is keyed: sha256 over the resolved spec, its textures, the build script and the
Blender series. The key is stamped into the GLB (`asset.extras.wgf.key`). When the file
already in the game repository carries the key the spec would produce, it is reused and
Blender is not started - which is what lets a CI runner without Blender, or a re-executed
step, keep a committed model instead of degrading it to a placeholder box.
"""

import hashlib
import json
import os
import re
import shutil
import struct
import tempfile

from wgflib import procs

from . import gltf, modelspec
from .placeholders import BackendError, Generated, GeneratedFile, PlaceholderBackend
from .policy import GENERATED_LICENSE

__all__ = ["BACKEND_ID", "BlenderBackend", "BlenderInfo", "BlenderError", "discover",
           "build_command", "build_environment", "build_model", "generation_key", "stamp",
           "read_stamp", "parse_version", "SCRIPT", "ENV_VAR"]

BACKEND_ID = "blender"
ENV_VAR = "WGF_BLENDER"
HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "blender_scripts", "build_model.py")
DEFAULT_TIMEOUT = 300
VERSION_TIMEOUT = 60
# The oldest Blender the build script is written against (bmesh calc_uvs, the exporter
# options it names). Below it nothing runs, pinned or not.
MINIMUM = (4, 2)
_VERSION = re.compile(r"Blender\s+(\d+)\.(\d+)(?:\.(\d+))?")
_ENV_ALLOW = ("PATH", "SYSTEMROOT", "TMPDIR", "TEMP", "TMP")


class BlenderError(RuntimeError):
    """Blender is missing, unpinned, or a build failed. The message says what to do."""


class BlenderInfo:
    def __init__(self, executable, source, version=None, raw=None, error=None):
        self.executable = executable
        self.source = source      # config | env | path | None
        self.version = version    # (major, minor, patch) or None
        self.raw = raw            # the version line, e.g. "Blender 4.5.14 LTS"
        self.error = error

    @property
    def series(self):
        return f"{self.version[0]}.{self.version[1]}" if self.version else None

    @property
    def version_string(self):
        return ".".join(str(v) for v in self.version) if self.version else None

    def to_dict(self):
        return {"executable": self.executable, "source": self.source,
                "version": self.version_string, "raw": self.raw, "error": self.error}


def parse_version(text):
    """(major, minor, patch) from `blender --version` output, or None."""
    match = _VERSION.search(text or "")
    if not match:
        return None
    return int(match.group(1)), int(match.group(2)), int(match.group(3) or 0)


def _locate(configured=None, environ=None):
    environ = os.environ if environ is None else environ
    search = environ.get("PATH")
    for source, candidate in (("config", configured), ("env", environ.get(ENV_VAR))):
        if candidate:
            candidate = os.path.expanduser(str(candidate))
            found = shutil.which(candidate, path=search) or (
                candidate if os.path.isfile(candidate) and os.access(candidate, os.X_OK)
                else None)
            if not found:
                return None, source, f"{candidate!r} (from {source}) is not an executable file"
            return found, source, None
    found = shutil.which("blender", path=search)
    if found:
        return found, "path", None
    return None, None, "blender is not on PATH"


def discover(configured=None, *, environ=None, runner=None):
    """A BlenderInfo: where Blender is and which version, or why it is not usable."""
    executable, source, problem = _locate(configured, environ)
    if executable is None:
        return BlenderInfo(None, source, error=problem)
    runner = runner or procs.run
    result = runner([executable, "--version"], timeout=VERSION_TIMEOUT, heartbeat_seconds=0,
                    env=build_environment(None))
    if not result.ok:
        return BlenderInfo(executable, source,
                           error=f"`{executable} --version` failed: {result.tail(5) or result.status}")
    version = parse_version(result.stdout)
    if version is None:
        return BlenderInfo(executable, source,
                           error=f"`{executable} --version` printed no Blender version")
    line = next((l.strip() for l in result.stdout.splitlines() if l.strip().startswith("Blender")),
                None)
    return BlenderInfo(executable, source, version, line)


def check_pin(info, pin, *, allow_unpinned=False):
    """None when `info` may build under `pin` ({series, tested}); else the refusal, actionable."""
    if info.version is None:
        return info.error or "Blender version unknown"
    if info.version[:2] < MINIMUM:
        return (f"Blender {info.version_string} at {info.executable} is older than "
                f"{MINIMUM[0]}.{MINIMUM[1]}, the oldest the build script supports")
    series = str((pin or {}).get("series") or "")
    if series and info.series != series and not allow_unpinned:
        return (f"Blender {info.version_string} at {info.executable} is not the pinned series "
                f"{series} (core/reference/asset-policy.yaml toolchains.blender, tested "
                f"{(pin or {}).get('tested', '?')}); install Blender {series}.x and point "
                f"{ENV_VAR} or factory.assets.placeholders.blender.executable at it, or set "
                f"allow_unpinned: true to build unreproducibly")
    return None


def missing_message(info, pin):
    series = str((pin or {}).get("series") or "the pinned")
    return (f"Blender not available: {info.error}. Install Blender {series}.x "
            f"(https://www.blender.org/download/lts/) and put it on PATH, set {ENV_VAR}, or set "
            f"factory.assets.placeholders.blender.executable")


def build_environment(scratch):
    """The child environment: the allowlist, and user directories inside `scratch`."""
    env = {k: os.environ[k] for k in _ENV_ALLOW if k in os.environ}
    env["LANG"] = env["LC_ALL"] = "C.UTF-8"
    env["PYTHONNOUSERSITE"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    if scratch:
        home = os.path.join(scratch, "home")
        os.makedirs(home, exist_ok=True)
        env["HOME"] = home
        for name in ("BLENDER_USER_RESOURCES", "BLENDER_USER_CONFIG", "BLENDER_USER_SCRIPTS",
                     "BLENDER_USER_DATAFILES", "BLENDER_USER_EXTENSIONS"):
            env[name] = os.path.join(home, name.lower())
    return env


def build_command(executable, *, spec, textures, out, report, version=None, script=SCRIPT):
    """argv for one headless build. `--offline-mode` exists from 4.2 on."""
    argv = [executable, "--background", "--factory-startup", "-noaudio"]
    if version is None or tuple(version[:2]) >= (4, 2):
        argv.append("--offline-mode")
    argv += ["--python-exit-code", "3", "--python", script, "--",
             "--spec", spec, "--textures", textures, "--out", out, "--report", report]
    return argv


def _script_bytes(script=SCRIPT):
    with open(script, "rb") as handle:
        return handle.read()


def generation_key(resolved, textures, series, script=SCRIPT):
    """What a build depends on, hashed: the resolved spec, texture bytes, script, series."""
    digest = hashlib.sha256()
    digest.update(json.dumps(resolved, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    for name in sorted(textures):
        digest.update(name.encode("utf-8") + b"\0" + hashlib.sha256(textures[name]).digest())
    digest.update(hashlib.sha256(_script_bytes(script)).digest())
    digest.update(f"blender-{series}".encode("utf-8"))
    return "sha256:" + digest.hexdigest()


def stamp(data, meta, *, step_clips=()):
    """The GLB with `asset.extras.wgf = meta`. The BIN chunk is kept byte for byte.

    `step_clips` names clips the spec declared `step`: the exporter samples NLA tracks at every
    frame and writes them LINEAR whatever the keys were, so their samplers are set to STEP
    here - exact, because a stepped value only changes on a sampled frame."""
    document, binary = gltf.load(data)
    if data[:4] != b"glTF":
        raise BlenderError("stamp() needs a GLB")
    for animation in document.get("animations") or []:
        if animation.get("name") in step_clips:
            for sampler in animation.get("samplers") or []:
                sampler["interpolation"] = "STEP"
    asset = document.setdefault("asset", {})
    extras = asset.get("extras") if isinstance(asset.get("extras"), dict) else {}
    extras["wgf"] = meta
    asset["extras"] = extras
    text = json.dumps(document, separators=(",", ":"), sort_keys=True).encode("utf-8")
    text += b" " * (-len(text) % 4)
    chunks = struct.pack("<I", len(text)) + b"JSON" + text
    if binary is not None:
        chunks += struct.pack("<I", len(binary)) + b"BIN\x00" + binary
    return b"glTF" + struct.pack("<II", 2, 12 + len(chunks)) + chunks


def read_stamp(data):
    """`asset.extras.wgf` of a GLB, or None."""
    try:
        document, _binary = gltf.load(data)
    except gltf.GltfError:
        return None
    extras = (document.get("asset") or {}).get("extras")
    meta = extras.get("wgf") if isinstance(extras, dict) else None
    return meta if isinstance(meta, dict) else None


def build_model(info, spec, asset_id, *, timeout=DEFAULT_TIMEOUT, series=None, runner=None,
                on_event=None, keep=None):
    """(GLB bytes, report, key) for `spec`. Raises BlenderError with the reason."""
    try:
        resolved, textures = modelspec.resolve(spec, asset_id)
    except modelspec.ModelSpecError as exc:
        raise BlenderError(f"model spec: {exc}")
    if any(p["id"] == asset_id for p in resolved["parts"]):
        raise BlenderError(f"model spec: a part may not share the asset's id {asset_id!r}")
    key = generation_key(resolved, textures, series or info.series)
    runner = runner or procs.run
    scratch = keep or tempfile.mkdtemp(prefix="wgf-blender-")
    try:
        texture_dir = os.path.join(scratch, "textures")
        os.makedirs(texture_dir, exist_ok=True)
        for name, data in textures.items():
            with open(os.path.join(texture_dir, name), "wb") as handle:
                handle.write(data)
        spec_path = os.path.join(scratch, "spec.json")
        with open(spec_path, "w", encoding="utf-8") as handle:
            json.dump(resolved, handle, sort_keys=True, indent=1)
        out = os.path.join(scratch, f"{asset_id}.glb")
        report_path = os.path.join(scratch, "report.json")
        argv = build_command(info.executable, spec=spec_path, textures=texture_dir, out=out,
                             report=report_path, version=info.version)
        result = runner(argv, timeout=timeout, env=build_environment(scratch), on_event=on_event,
                        cwd=scratch)
        report = None
        if os.path.isfile(report_path):
            with open(report_path, encoding="utf-8") as handle:
                report = json.load(handle)
        if report is not None and not report.get("ok"):
            raise BlenderError(f"Blender build of {asset_id!r} failed: {report.get('error')}")
        if not result.ok:
            raise BlenderError(f"Blender exited {result.status}/{result.returncode} building "
                               f"{asset_id!r}: {result.tail(8)}")
        if report is None or not os.path.isfile(out):
            raise BlenderError(f"Blender reported success for {asset_id!r} but wrote no "
                               f"{'report' if report is None else 'GLB'}")
        with open(out, "rb") as handle:
            data = handle.read()
    finally:
        if keep is None:
            shutil.rmtree(scratch, ignore_errors=True)
    meta = {"generator": "wgf-assets/blender", "key": key,
            "spec_hash": modelspec.spec_hash(spec), "blender": info.version_string,
            "exporter": report.get("exporter"), "format": 1}
    step = {c["name"] for c in resolved["animations"] if c["interpolation"] == "step"}
    return stamp(data, meta, step_clips=step), report, key


class BlenderBackend(PlaceholderBackend):
    """Builds 3D kinds whose requirement carries a buildable `model` spec.

    Settings (factory.assets.placeholders.blender):
        executable       path or name of the Blender binary (else $WGF_BLENDER, else PATH)
        timeout_seconds  per build (default 300)
        allow_unpinned   build with a Blender outside the pinned series (default false)
        required         a spec that Blender could not build is an error, not a warning
    """

    id = BACKEND_ID
    kinds = frozenset({"model", "environment", "animation"})

    def __init__(self, settings=None, *, runner=None, environ=None):
        settings = dict(settings or {})
        self.executable = settings.get("executable")
        self.timeout = float(settings.get("timeout_seconds") or DEFAULT_TIMEOUT)
        self.allow_unpinned = bool(settings.get("allow_unpinned"))
        self.required = bool(settings.get("required"))
        self.runner = runner
        self.environ = environ
        self.store = None
        self.pin = {}
        self.info = None
        self.refusal = None

    def bind(self, store, policy):
        self.store = store
        self.pin = dict((getattr(policy, "toolchains", None) or {}).get("blender") or {})

    def supports(self, req):
        return (req.kind in self.kinds and req.dimension == "3d"
                and modelspec.buildable(getattr(req, "model", None)))

    def probe(self):
        self.info = discover(self.executable, environ=self.environ, runner=self.runner)
        if self.info.executable is None or self.info.version is None:
            self.refusal = missing_message(self.info, self.pin)
        else:
            self.refusal = check_pin(self.info, self.pin, allow_unpinned=self.allow_unpinned)
        if self.refusal:
            # Still available to reuse a committed build whose key matches: that needs no
            # Blender at all. Anything else falls through to the next backend, with why.
            return True, f"reuse-only: {self.refusal}"
        return True, f"Blender {self.info.version_string} ({self.info.source}: " \
                     f"{self.info.executable})"

    def _series(self):
        if self.info is not None and self.info.version is not None and not self.refusal:
            return self.info.series
        return str(self.pin.get("series") or "")

    def generate(self, req):
        from .pipeline import asset_path  # the pipeline imports the backends, not vice versa
        final = req.source in (None, "procedural")
        try:
            resolved, textures = modelspec.resolve(req.model, req.id)
        except modelspec.ModelSpecError as exc:
            raise BackendError(f"model spec: {exc}")
        series = self._series()
        key = generation_key(resolved, textures, series)
        relative = asset_path(req, "glb", final=final)
        existing = self.store.read(relative) if self.store is not None else None
        if existing is not None and (read_stamp(existing) or {}).get("key") == key:
            meta = read_stamp(existing)
            return Generated([GeneratedFile("glb", existing)],
                             generator=f"blender {meta.get('blender')}",
                             license=GENERATED_LICENSE, final=final,
                             notes="Reused: the committed build's key matches the spec.",
                             metadata=self._metadata(meta, reused=True))
        if self.refusal:
            raise BackendError(self.refusal)
        try:
            data, report, key = build_model(self.info, req.model, req.id, timeout=self.timeout,
                                            series=series, runner=self.runner)
        except BlenderError as exc:
            raise BackendError(str(exc))
        return Generated([GeneratedFile("glb", data)],
                         generator=f"blender {self.info.version_string}",
                         license=GENERATED_LICENSE, final=final,
                         metadata=self._metadata(read_stamp(data), reused=False, report=report))

    def _metadata(self, meta, *, reused, report=None):
        pinned_series = str(self.pin.get("series") or "")
        version = (meta or {}).get("blender") or ""
        block = {
            "tool": "blender",
            "version": version,
            "exporter": (meta or {}).get("exporter"),
            "pinned": bool(pinned_series) and version.startswith(pinned_series + "."),
            "key": (meta or {}).get("key"),
            "spec_hash": (meta or {}).get("spec_hash"),
            "reused": reused,
        }
        if report and report.get("export_options_unsupported"):
            block["export_options_unsupported"] = list(report["export_options_unsupported"])
        return {k: v for k, v in block.items() if v is not None}

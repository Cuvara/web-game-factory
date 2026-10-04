"""The store listing module (scripts/wgf_listing): unit, step, validation, engine contract,
release integration, failure and retry.

Offline and deterministic: the browser capture is a fake runner that writes synthetic
frames, a synthetic WebM and the branding images the step asks for, in the shape
capture.mjs writes (capture.json). The real capture against a real build runs in the golden
runs (WGF_GOLDEN=1) and, on a machine with a built game, in RealBuild below
(WGF_LISTING_REPO=<checkout with dist/ and node_modules>).
"""

import copy
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import textwrap
import types
import unittest
import unittest.mock

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, HERE)

from wgf_assets.raster import Image, encode_png  # noqa: E402
from wgf_listing import (ListingValidationStep, StoreListingStep, copywriter, facts as facts_mod,  # noqa: E402
                         grounding, imaging, media, package as pkg, platforms, register)
from wgf_listing.capture import BundleServer, CaptureFailure  # noqa: E402
from wgf_listing.validation import validate  # noqa: E402
from wgf_release.step import ReleaseStep, bundle_digest  # noqa: E402
from wgflib import provenance  # noqa: E402
from wgflib.hashing import content_hash  # noqa: E402
from wgflib.workflow import StepOutcome, StepRegistry, mock  # noqa: E402
from wgflib.workflow.contracts import ArtifactContracts  # noqa: E402
from wgflib.workflow.definition import StepDefinition  # noqa: E402
from wgflib.workflow.model import ArtifactRef  # noqa: E402
from wgflib.yamllite import load_file  # noqa: E402
from testenv import enabled  # noqa: E402

import test_release_module as release_tests  # noqa: E402

REFERENCE = os.path.join(HERE, "fixtures", "listing", "reference-small.yaml")
FIXTURES = os.path.join(SCRIPTS, "wgflib", "workflow", "fixtures")
NOW = "2026-10-02T10:00:00Z"
CONTRACTS = ArtifactContracts()
HAS_GIT = shutil.which("git") is not None


# -- synthetic media ----------------------------------------------------------------------

def rich_png(path, width, height, seed=0):
    """A frame with a gradient and a block whose place depends on `seed`: lit, with
    contrast, and distinct from another seed's."""
    image = Image(width, height)
    px = image.pixels
    bx = (seed * 37) % max(1, width - width // 3)
    by = (seed * 53) % max(1, height - height // 3)
    for y in range(height):
        for x in range(width):
            o = (y * width + x) * 4
            inside = bx <= x < bx + width // 3 and by <= y < by + height // 3
            px[o] = 245 if inside else (x * 120) // max(1, width) + 30
            px[o + 1] = 245 if inside else (y * 90) // max(1, height) + 40
            px[o + 2] = 235 if inside else 100
            px[o + 3] = 255
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(encode_png(image))
    return path


def dark_png(path, width, height):
    image = Image(width, height)
    for o in range(0, len(image.pixels), 4):
        image.pixels[o:o + 4] = bytes((4, 4, 6, 255))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(encode_png(image))
    return path


def _vint(n):
    if n < 0x7F:
        return bytes([0x80 | n])
    if n < 0x3FFF:
        return struct.pack(">H", 0x4000 | n)
    return struct.pack(">I", 0x10000000 | n)


def _el(eid, body):
    return eid + _vint(len(body)) + body


def make_webm(path, duration_s=12.0, width=160, height=90, codec=b"V_VP8"):
    """A minimal WebM: EBML header, Segment(Info(TimecodeScale, Duration), Tracks(...))."""
    header = _el(b"\x1a\x45\xdf\xa3", _el(b"\x42\x82", b"webm"))
    info = _el(b"\x15\x49\xa9\x66", _el(b"\x2a\xd7\xb1", struct.pack(">I", 1_000_000))
               + _el(b"\x44\x89", struct.pack(">d", duration_s * 1000)))
    video = _el(b"\xe0", _el(b"\xb0", struct.pack(">H", width)) + _el(b"\xba", struct.pack(">H", height)))
    track = _el(b"\xae", _el(b"\x86", codec) + _el(b"\x83", b"\x01") + video)
    tracks = _el(b"\x16\x54\xae\x6b", track)
    cluster = _el(b"\x1f\x43\xb6\x75", b"\x00" * 64)
    segment = _el(b"\x18\x53\x80\x67", info + tracks + cluster)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(header + segment)
    return path


def make_mp4(path, duration_s=10.0, width=640, height=360):
    def box(kind, body):
        return struct.pack(">I", 8 + len(body)) + kind + body
    ftyp = box(b"ftyp", b"isom" + struct.pack(">I", 512) + b"isomiso2avc1mp41")
    mvhd = box(b"mvhd", b"\x00" * 4 + struct.pack(">IIII", 0, 0, 1000, int(duration_s * 1000)) + b"\x00" * 80)
    tkhd = box(b"tkhd", b"\x00" * 4 + b"\x00" * 72 + struct.pack(">II", width << 16, height << 16))
    stsd = box(b"stsd", b"\x00" * 4 + struct.pack(">I", 1) + box(b"avc1", b"\x00" * 78))
    stbl = box(b"stbl", stsd)
    minf = box(b"minf", stbl)
    mdia = box(b"mdia", minf)
    trak = box(b"trak", tkhd + mdia)
    moov = box(b"moov", mvhd + trak)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(ftyp + moov + box(b"mdat", b"\x00" * 16))
    return path


# -- fixtures ---------------------------------------------------------------------------

def fixture(name):
    with open(os.path.join(FIXTURES, f"{name}.json"), encoding="utf-8") as handle:
        return json.load(handle)


def seal(artifact_type, body, inputs=(), schema_version=None, title_id="fixture-game", seq=1):
    artifact = {"provenance": provenance.build(
        artifact_type, artifact_id=provenance.artifact_id(artifact_type, title_id, NOW, seq),
        produced_by=provenance.producer("qa"), produced_at=NOW, inputs=list(inputs),
        title_id=title_id, **({"schema_version": schema_version} if schema_version else {}))}
    artifact.update(copy.deepcopy(body))
    return provenance.seal(artifact)


DESIGN = fixture("game-design")
DESIGN.update({
    "title_id": "fixture-game",
    "engine": {"type": "pixijs", "dimension": "2d", "rationale": "flat play",
               "design_resolution": {"width": 720, "height": 1280}, "camera": "fixed"},
    "research": {"gameplay": {"genre": {"value": "rhythm", "label": "Rhythm", "tier": "derived",
                                        "source": "corpus"}}},
})
DESIGN["build_spec"] = {
    "mechanics": [{"id": "lane-switch", "name": "Lane switch", "tier": "mvp",
                   "description": "One tap switches lanes on the beat.", "rules": ["a"]},
                  {"id": "combo", "name": "Combo", "tier": "mvp",
                   "description": "Consecutive hits on the beat raise the combo multiplier.", "rules": ["b"]},
                  {"id": "gate-miss", "name": "A missed gate ends the run", "tier": "mvp",
                   "description": "Missing a gate ends the run; retry is one tap away.", "rules": ["c"]}],
    "controls": {"primary_input": "touch", "actions": [
        {"id": "switch", "action": "Switch lanes", "tier": "mvp", "mechanic": "lane-switch",
         "touch": "Tap anywhere", "mouse": "Click anywhere", "keyboard": "Space"}]},
    "experience": {"goal": {"statement": "Tap on the beat to switch lanes and keep the combo alive.",
                            "metric": "combo", "shown_on": "play"},
                   "lose": {"condition": "A gate is missed.", "metric": "lives"},
                   "actions": [], "onboarding": {"teaches": ["switch"], "grace": {"seconds": 5}},
                   "first_30s": {}},
    "visual_identity": {"concept": "Flat neon vectors on dark ground.",
                        "palette": [{"token": "night", "hex": "#101018", "role": "Background"},
                                    {"token": "neon", "hex": "#ff48b0", "role": "Primary: the player"},
                                    {"token": "chalk", "hex": "#f4ede1", "role": "Text and outlines"}],
                        "typography": {"display": "Rubik Mono One", "body": "Manrope"}},
    "responsive": {"orientation": "portrait"},
    "sdk_touchpoints": [{"id": "sdk-init", "capability": "init", "tier": "mvp", "state": "boot",
                         "when": "boot", "platforms": ["generic-web"]}],
}
DESIGN["features"] = [{"id": "lane-switch", "name": "Lane switch", "tier": "mvp", "description": "One tap switches lanes."},
                      {"id": "best-score", "name": "Personal best, saved locally", "tier": "mvp"}]
DESIGN["scope"]["locales"] = ["en", "ru"]
DESIGN["session"]["target_seconds"] = 240


class Inputs:
    def __init__(self, artifacts, missing=()):
        self.contents = dict(artifacts)
        self.refs = {t: ArtifactRef(id=t, type=t, version=1, location=f"artifacts/{t}/v1.json",
                                    checksum="sha256:" + "0" * 64, produced_by="upstream", created_at=NOW,
                                    content_hash=c["provenance"]["content_hash"],
                                    schema_version=c["provenance"]["schema_version"])
                     for t, c in self.contents.items()}
        self.missing = list(missing)

    def __contains__(self, artifact_type):
        return artifact_type in self.refs

    def load(self, artifact_type):
        return self.contents[artifact_type]


class Logger:
    def __init__(self):
        self.records = []

    def _log(self, level):
        def log(message, **fields):
            self.records.append((level, message, fields))
        return log

    def __getattr__(self, level):
        return self._log(level)


class Context:
    def __init__(self, run_dir, config=None, step="store-listing", gates_passed=("G4",), visit=1,
                 entered_by=None):
        self.run_dir = run_dir
        self.config = config or {}
        self.gates_passed = list(gates_passed)
        self.run_id, self.workflow_id, self.current_step = "run-1", "new-game", step
        self.visit = self.execution = visit
        self.attempt = 1
        self.project_id = "fixture-game"
        self.environment = {}
        self.logger = Logger()
        self.entered_by = entered_by

    def process_hooks(self):
        return {}


class GameBuild:
    """A committed game repository with a built bundle under dist/ (index.html, locale
    strings), as verification leaves it."""

    def __init__(self, scratch, strings=None):
        self.root = os.path.join(scratch, "fixture-game")
        os.makedirs(os.path.join(self.root, "dist", "locales"))
        with open(os.path.join(self.root, "dist", "index.html"), "w", encoding="utf-8") as handle:
            handle.write("<!doctype html><title>Fixture Game</title>\n")
        if strings is None:
            strings = {"en": {"title.heading": "Fixture Game", "hud.objective": "Tap on the beat to switch lanes."},
                       "ru": {"title.heading": "Fixture Game",
                              "title.rules": "Нажимайте в такт, чтобы менять полосу и держать комбо."}}
        for locale, values in strings.items():
            with open(os.path.join(self.root, "dist", "locales", f"{locale}.json"), "w", encoding="utf-8") as handle:
                json.dump(values, handle, ensure_ascii=False)
        with open(os.path.join(self.root, "game.config.yaml"), "w", encoding="utf-8") as handle:
            handle.write("game:\n  id: fixture-game\n  name: Fixture Game\n  version: 0.1.0\n"
                         "build:\n  output: dist\n"
                         "platforms:\n  - { id: generic-web, profile: generic-web@1.1.0, role: required }\n")
        with open(os.path.join(self.root, ".gitignore"), "w") as handle:
            handle.write("node_modules/\n")
        with open(os.path.join(self.root, "package.json"), "w") as handle:
            json.dump({"name": "fixture-game", "version": "0.1.0"}, handle)
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=self.root, check=True)
        subprocess.run(["git", "-c", "user.name=T", "-c", "user.email=t@example.invalid", "-c",
                        "commit.gpgsign=false", "add", "-A"], cwd=self.root, check=True)
        subprocess.run(["git", "-c", "user.name=T", "-c", "user.email=t@example.invalid", "-c",
                        "commit.gpgsign=false", "commit", "-q", "-m", "build"], cwd=self.root, check=True)
        self.head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.root, capture_output=True,
                                   text=True, check=True).stdout.strip()

    def evidence(self, commit=None, qa_verdict="pass", verdict="PASS", bundle_hash=None, platforms=None,
                 design=None):
        commit = commit or self.head
        scaffold = seal("scaffold-record", {
            "title_id": "fixture-game",
            "repository": {"owner": "example", "name": "fixture-game", "local_path": self.root},
            "template": {"repository": "example/web-game-template", "commit_sha": "a" * 40},
            "game_config": {"path": "game.config.yaml", "platforms": platforms or [
                {"id": "generic-web", "profile": "generic-web@1.1.0", "role": "required"}]},
            "outcome": "created"}, schema_version="1.0.0")
        vr = seal("verification-report", {
            "title_id": "fixture-game", "commit": {"sha": commit, "dirty": False},
            "build_artifact": {"status": "built", "path": "dist",
                               "content_hash": bundle_hash or bundle_digest(self.root, "dist"), "files": 3, "bytes": 100},
            "gameplay_driver": {"id": "none"},
            "checks": [{"id": "build.build", "category": "build", "title": "Production build", "status": "PASS",
                        "required": True, "message": "fixture",
                        "evidence": [{"kind": "observation", "summary": "fixture build"}]}],
            "summary": {"total": 1, "PASS": 1, "FAIL": 0, "BLOCKED": 0, "WARNING": 0},
            "failed_checks": [], "blocked_checks": [], "warning_checks": [], "platform_readiness": [],
            "verdict": verdict, "evidence_status": "PASS_MOCK"}, schema_version="1.1.0")
        qa = seal("qa-report", {
            "title_id": "fixture-game", "release_id": "r1", "build_ref": {"commit_sha": commit},
            "suites": [{"name": "lint", "passed": 1, "failed": 0}], "blocking_defects": [],
            "perf_results": [{"device_class": "desktop", "fps": 60, "within_budget": True}],
            "verdict": qa_verdict, "evidence_status": "PASS_MOCK"}, schema_version="1.1.0")
        return {"qa-report": qa, "verification-report": vr,
                "game-design": seal("game-design", DESIGN if design is None else design),
                "scaffold-record": scaffold}


class FakeCapture:
    """capture.run_capture's contract, without a browser: synthetic frames per scene and
    viewport, a synthetic recording, the branding images the job asks for. `plan` makes
    attempt N behave: "ok" (default), "few" (two indistinct play frames), "dark", "blocked",
    "crash", "no-trailer"; "few-showcase" is "few" with three distinct frames of states the
    probe's showcase staged, "few-showcase-same" with showcase frames that are dark or the same
    as play."""

    def __init__(self, plan=None):
        self.plan = list(plan or [])
        self.calls = []

    def __call__(self, job, *, checkout, node, timeout, config, hooks, log_path, script=None):
        self.calls.append(job)
        out = job["out"]
        os.makedirs(out, exist_ok=True)
        if job.get("branding"):
            made = []
            for shot in job["branding"]["shots"]:
                path = rich_png(os.path.join(out, "branding", f"{shot['id']}.png"), shot["width"],
                                shot["height"], seed=len(made) + 11)
                made.append({"id": shot["id"], "file": path, "width": shot["width"], "height": shot["height"],
                             "source": shot["source"]})
            return {"browser": "fake", "viewports": [], "trailer": None, "branding": made, "derived": [],
                    "errors": [], "network_guard": "none"}
        if job.get("derive"):
            return {"browser": "fake", "viewports": [], "trailer": None, "branding": [], "derived": [],
                    "errors": ["no encoder in the fake"], "network_guard": "none"}
        attempt = len([c for c in self.calls if c.get("viewports")])
        behaviour = self.plan[attempt - 1] if attempt - 1 < len(self.plan) else "ok"
        if behaviour == "blocked":
            raise CaptureFailure("blocked", "no browser to capture the build in here (fake)")
        if behaviour == "crash":
            raise CaptureFailure("failed", "the capture crashed (fake)")
        viewports = []
        for index, viewport in enumerate(job["viewports"]):
            shots = []
            for s_index, scene in enumerate(job["scenes"]):
                if isinstance(scene["state"], list):
                    continue  # no result screen reached
                if behaviour.startswith("few"):
                    # Every play frame the same (indistinct); only the title differs.
                    seed = 200 + index if scene["id"] == "title" else 100 + index
                else:
                    seed = index * 10 + s_index
                path = os.path.join(out, viewport["id"], f"{scene['id']}.png")
                if behaviour == "dark":
                    dark_png(path, viewport["width"], viewport["height"])
                else:
                    rich_png(path, viewport["width"], viewport["height"], seed=seed)
                shots.append({"scene": scene["id"], "file": path, "state": scene["state"],
                              "excluded": False, "elapsed_ms": 1000 * s_index})
            if behaviour.startswith("few-showcase"):
                for t_index, target in enumerate(("boss", "embers", "laser-bolt")):
                    path = os.path.join(out, viewport["id"], f"showcase-{target}.png")
                    if behaviour == "few-showcase-same" and t_index == 0:
                        dark_png(path, viewport["width"], viewport["height"])
                    else:
                        seed = 100 + index if behaviour == "few-showcase-same" else 300 + t_index * 7 + index
                        rich_png(path, viewport["width"], viewport["height"], seed=seed)
                    shots.append({"scene": f"showcase-{target}", "file": path, "state": "playing",
                                  "excluded": False, "showcase": True, "target": target})
            viewports.append({"id": viewport["id"], "width": viewport["width"], "height": viewport["height"],
                              "mobile": bool(viewport.get("mobile")), "ran": True, "errors": [],
                              "shots": shots, "start": {"playingMs": 1200}, "play": {"playedMs": 15000, "inputs": 40}})
        trailer = None
        if job.get("trailer", {}).get("enabled") and behaviour != "no-trailer":
            spec = job["trailer"]
            raw = make_webm(os.path.join(out, "trailer", "trailer.webm"), 12.0, spec["width"], spec["height"])
            trailer = {"enabled": True, "raw": raw, "file": raw, "leading_ms": 1900, "played_ms": 12000,
                       "reached": None, "inputs": 60, "trimmed": True, "derived": [], "errors": [],
                       "width": spec["width"], "height": spec["height"]}
        elif job.get("trailer", {}).get("enabled"):
            trailer = {"enabled": True, "raw": None, "file": None, "leading_ms": None, "played_ms": None,
                       "reached": None, "inputs": 0, "trimmed": False, "derived": [],
                       "errors": ["recording failed (fake)"], "width": 0, "height": 0}
        report = {"browser": "fake chromium", "viewports": viewports, "trailer": trailer, "branding": [],
                  "derived": [], "ffmpeg": None, "errors": [], "network_guard": "none", "exit_code": 0}
        with open(os.path.join(out, "capture.json"), "w", encoding="utf-8") as handle:
            json.dump(report, handle)
        return report


def listing_step(fake, **params):
    params.setdefault("required_gates", ["G4"])
    params.setdefault("reference", REFERENCE)
    definition = StepDefinition({"id": "store-listing", "type": "store-listing",
                                 "inputs": ["qa-report", "verification-report", "game-design", "scaffold-record"],
                                 "outputs": ["store-listing"], "with": params}, retry=None, max_visits=None)
    step = StoreListingStep(definition)
    step.capture_runner = staticmethod(fake)
    step.clock = staticmethod(lambda: NOW)
    return step


def validation_step(**params):
    params.setdefault("reference", REFERENCE)
    definition = StepDefinition({"id": "listing-validation", "type": "listing-validation",
                                 "inputs": ["store-listing"], "outputs": ["listing-validation-report"],
                                 "with": params}, retry=None, max_visits=None)
    step = ListingValidationStep(definition)
    step.clock = staticmethod(lambda: NOW)
    return step


class ListingCase(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.mkdtemp(prefix="wgf-listing-")
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)
        self.run_dir = os.path.join(self.scratch, "run")
        os.makedirs(self.run_dir)
        self.game = GameBuild(self.scratch)
        self.reference = load_file(REFERENCE)

    def context(self, **kw):
        return Context(self.run_dir, **kw)

    def image_sizes_unstated(self):
        """The real profiles, with their image sizes and formats left unstated: this case's
        masters are fixture-small (reference-small.yaml), so a portal's real 512 px icon would
        be above every master. For tests about locales, copy and age ratings, not images."""
        real = platforms.load_profile

        def load(platform_id, directory=None):
            profile = copy.deepcopy(real(platform_id, directory))
            block = profile.get("store_listing") or {}
            for image in [block.get("icon")] + list(block.get("covers") or []):
                if isinstance(image, dict):
                    image.update(sizes=None, formats=None)
            if isinstance(block.get("screenshots"), dict):
                block["screenshots"]["formats"] = None
            return profile

        patcher = unittest.mock.patch.object(platforms, "load_profile", load)
        patcher.start()
        self.addCleanup(patcher.stop)

    def capture(self, fake=None, artifacts=None, context=None, **params):
        fake = fake or FakeCapture()
        step = listing_step(fake, repo_dir=self.game.root, **params)
        result = step.execute(Inputs(artifacts or self.game.evidence()), context or self.context())
        return result, fake

    def listing_of(self, result):
        self.assertTrue(result.artifacts, result.message or result.error)
        listing = result.artifacts[0].content
        self.assertEqual(CONTRACTS.problems("store-listing", listing), [])
        return listing

    def validate(self, listing, design=DESIGN, **params):
        artifacts = {"store-listing": listing, "game-design": seal("game-design", design)}
        result = validation_step(**params).execute(Inputs(artifacts), self.context(step="listing-validation"))
        report = result.artifacts[0].content
        self.assertEqual(CONTRACTS.problems("listing-validation-report", report), [])
        return result, report


# -- unit: imaging and media ------------------------------------------------------------------

class Imaging(unittest.TestCase):
    def test_resize_fit_and_aspect(self):
        base = os.path.join(tempfile.mkdtemp(prefix="wgf-img-"), "f.png")
        rich_png(base, 320, 180, seed=3)
        image = imaging.read_png(base)
        self.assertEqual((imaging.resize(image, 64, 36).width, imaging.resize(image, 64, 36).height), (64, 36))
        cover = imaging.fit(image, 50, 50, "cover")
        self.assertEqual((cover.width, cover.height), (50, 50))
        contain = imaging.fit(image, 100, 100, "contain", (1, 2, 3, 255))
        self.assertEqual((contain.width, contain.height), (100, 100))
        self.assertEqual(tuple(contain.pixels[:4]), (1, 2, 3, 255))  # letterbox
        up = imaging.resize(image, 640, 360)
        self.assertEqual((up.width, up.height), (640, 360))
        self.assertEqual(imaging.aspect_of(1920, 1080), "16:9")
        self.assertEqual(imaging.parse_hex("#ff48b0"), (255, 72, 176, 255))
        self.assertEqual(imaging.parse_hex("junk", (0, 0, 0, 0)), (0, 0, 0, 0))

    def test_media_describes_png_webm_and_mp4(self):
        base = tempfile.mkdtemp(prefix="wgf-media-")
        png = rich_png(os.path.join(base, "a.png"), 40, 20)
        self.assertEqual({k: media.describe(png)[k] for k in ("format", "width", "height")},
                         {"format": "png", "width": 40, "height": 20})
        webm = make_webm(os.path.join(base, "t.webm"), 12.5, 160, 90)
        info = media.describe(webm)
        self.assertEqual((info["format"], info["width"], info["height"], info["duration_s"], info["codec"]),
                         ("webm", 160, 90, 12.5, "V_VP8"))
        mp4 = make_mp4(os.path.join(base, "t.mp4"), 9.0, 640, 360)
        info = media.describe(mp4)
        self.assertEqual((info["format"], info["width"], info["height"], info["duration_s"], info["codec"]),
                         ("mp4", 640, 360, 9.0, "avc1"))
        with open(os.path.join(base, "junk.bin"), "wb") as handle:
            handle.write(b"\x00\x01junk")
        self.assertEqual(media.describe(os.path.join(base, "junk.bin"))["format"], "unknown")


# -- unit: facts, copy, grounding ------------------------------------------------------------

class Facts(unittest.TestCase):
    def test_facts_come_with_their_sources(self):
        strings = {"en": {"title.heading": "Fixture Game"}, "ru": {"title.rules": "Правила"}}
        facts = facts_mod.extract(DESIGN, strings=strings, scaffold={"game_config": {"platforms": [{"id": "poki"}]}},
                                  sdk_report={"platforms": [{"features": [{"feature": "leaderboards", "status": "working"}]}]})
        self.assertEqual(facts["title"], "Fixture Game")
        self.assertEqual(facts["sources"]["title"], "bundle locales/en.json#title.heading")
        self.assertEqual(facts["genre"], ["rhythm", "arcade"])
        self.assertEqual(facts["objective"], DESIGN["build_spec"]["experience"]["goal"]["statement"])
        self.assertEqual([m["id"] for m in facts["mechanics"]], ["lane-switch", "combo", "gate-miss"])
        self.assertEqual(facts["controls"]["touch"], ["Tap anywhere"])
        self.assertEqual(facts["controls"]["gamepad"], [])
        self.assertEqual(facts["platforms"], ["poki"])
        self.assertIn("leaderboards", facts["capabilities"])
        self.assertTrue(facts["endless"])
        self.assertEqual(facts["engine"], {"type": "pixijs", "dimension": "2d"})
        self.assertEqual(facts["orientation"], "portrait")
        for fact in ("objective", "core_loop", "mechanic:combo", "controls:touch", "genre", "engine"):
            self.assertIn(fact, facts["sources"], fact)

    def test_a_bare_design_yields_a_title_and_nothing_invented(self):
        facts = facts_mod.extract({"title_id": "bare-game", "scope": {}, "session": {}})
        self.assertEqual(facts["title"], "Bare Game")
        self.assertIsNone(facts["objective"])
        self.assertEqual(facts["mechanics"], [])
        self.assertEqual(facts["genre"], [])


class Copy(unittest.TestCase):
    def setUp(self):
        self.reference = load_file(REFERENCE)
        self.facts = facts_mod.extract(DESIGN, strings={
            "en": {"title.heading": "Fixture Game"},
            "ru": {"title.heading": "Fixture Game", "hud.objective": "Нажимайте в такт, чтобы менять полосу."}})

    def test_the_template_writer_stays_within_bounds_and_leads_with_the_verb(self):
        copies, writer = copywriter.write_copy(self.facts, ["en", "ru", "vi"], self.reference)
        self.assertEqual(writer, {"kind": "template", "required": "template"})
        en = copies["en"]
        self.assertTrue(en["short_description"].startswith("Tap on the beat to switch lanes"))
        self.assertLessEqual(len(en["short_description"]), 160)
        self.assertLessEqual(len(en["long_description"]), 2000)
        self.assertGreaterEqual(len(en["features"]), 3)
        self.assertTrue(all(b["source"] for b in en["features"]))
        self.assertIn("rhythm", en["tags"])
        self.assertIn("single-player", en["tags"])
        self.assertIn("2d", en["tags"])
        self.assertEqual(en["categories"], ["Arcade"])
        self.assertIn("Touch: Tap anywhere", en["controls"])
        # ru comes from the game's own strings; vi has none and no agent: a missing deliverable.
        self.assertTrue(copies["ru"]["short_description"].startswith("Нажимайте"))
        self.assertEqual(copies["ru"]["features"][0]["source"], "string:ru:hud.objective")
        self.assertIsNone(copies["vi"])

    def test_the_template_copy_is_grounded(self):
        copies, _ = copywriter.write_copy(self.facts, ["en", "ru"], self.reference)
        for locale, text in copies.items():
            problems = [p for p in grounding.check(text, self.facts, self.reference["claims"], locale=locale)
                        if p["severity"] == "error"]
            self.assertEqual(problems, [], locale)

    def test_a_locale_is_written_from_the_games_own_keys_not_only_the_template_ones(self):
        # Sky Marble (2026-10-04): the game names its strings `game.title` and
        # `play.objective`; ru was read from the build and then not written, so yandex
        # (which requires ru) got no copy at all.
        facts = facts_mod.extract(DESIGN, strings={
            "en": {"game.title": "Fixture Game", "play.objective": "Tap on the beat to switch lanes and keep the combo alive.",
                   "title.course": "Course {n}"},
            "ru": {"game.title": "Фикстура", "play.objective": "Нажимайте в такт, чтобы менять полосу.",
                   "title.course": "Трасса {n}"}})
        copies, _ = copywriter.write_copy(facts, ["en", "ru"], self.reference)
        ru = copies["ru"]
        self.assertEqual(ru["title"], "Фикстура")
        self.assertEqual(ru["short_description"], "Нажимайте в такт, чтобы менять полосу.")
        self.assertEqual([b["source"] for b in ru["features"]], ["string:ru:play.objective"])
        self.assertEqual(ru["categories"], ["Arcade"])
        problems = [p for p in grounding.check(ru, facts, self.reference["claims"], locale="ru")
                    if p["severity"] == "error"]
        self.assertEqual(problems, [])

    def test_the_objective_key_is_the_one_whose_english_is_the_design_objective(self):
        objective = DESIGN["build_spec"]["experience"]["goal"]["statement"]
        facts = facts_mod.extract(DESIGN, strings={
            "en": {"intro.line": objective, "menu.play": "Play"},
            "ru": {"intro.line": "Нажимайте в такт, чтобы менять полосу.", "menu.play": "Играть"}})
        copies, _ = copywriter.write_copy(facts, ["ru"], self.reference)
        self.assertEqual(copies["ru"]["features"][0]["source"], "string:ru:intro.line")

    def test_a_locale_whose_strings_hold_no_title_or_objective_is_never_invented(self):
        facts = facts_mod.extract(DESIGN, strings={
            "en": {"menu.play": "Play"}, "ru": {"menu.play": "Играть", "clear.time": "Время {t} с"}})
        copies, _ = copywriter.write_copy(facts, ["en", "ru", "tr"], self.reference)
        self.assertIsNone(copies["ru"])
        self.assertIsNone(copies["tr"])

    def test_fit_text_cuts_at_a_sentence_then_a_word_never_inside_one(self):
        text = "Drop the piece. Merge equal neighbours into one. Keep the columns clear."
        self.assertEqual(copywriter.fit_text(text, 40), "Drop the piece.")
        self.assertEqual(copywriter.fit_text("supercalifragilistic expialidocious words", 25),
                         "supercalifragilistic")
        self.assertEqual(copywriter.fit_text(text, 1000), text)
        self.assertEqual(copywriter.fit_list(["a", "A", "b", "c"], 2), ["a", "b"])
        self.assertEqual(copywriter.fit_list(["Puzzle", "Zzz"], 5, allowed=["puzzle"]), ["Puzzle"])


def _courses_design(units=6):
    design = copy.deepcopy(DESIGN)
    design["scope"]["content_units"] = units
    design["scope"]["content_unit_kind"] = "courses"
    return design


# Sky Marble (2026-10-04): the design planned six courses, the build ships twelve in three
# tiers; the copy said "six sky courses" and "one input and no buttons" beside a pause button.
TWELVE = {"en": {**{f"course.{n}": f"Course Name {n}" for n in range(1, 13)},
                 "title.course": "Course {n}", "courses.back": "Back", "clear.next": "Next course",
                 "title.heading": "Fixture Game", "hud.objective": "Tap on the beat to switch lanes."},
          "ru": {**{f"course.{n}": f"Трасса {n}" for n in range(1, 13)},
                 "title.course": "Трасса {n}", "courses.back": "Назад", "clear.next": "Следующая трасса",
                 "title.heading": "Fixture Game", "hud.objective": "Нажимайте в такт, чтобы менять полосу."}}


class BuildFacts(unittest.TestCase):
    def test_the_build_count_wins_over_the_design_and_the_conflict_is_recorded(self):
        report = {"scope_deltas": [{"item": "Courses 7-12", "direction": "added", "reason": "Twelve authored."},
                                   {"item": "nothing", "direction": "sideways"}]}
        facts = facts_mod.extract(_courses_design(6), strings=TWELVE, prototype_report=report)
        self.assertEqual(facts["content_units"], 12)
        self.assertEqual(facts["content_unit_names"][:2], ["Course Name 1", "Course Name 2"])
        self.assertEqual(facts["sources"]["content_units"], "bundle locales/en.json#course.1..12")
        self.assertEqual(facts["conflicts"], [{"fact": "content_units", "design": 6, "build": 12,
                                               "source": "bundle locales/en.json#course.1..12"}])
        self.assertEqual(facts["scope_deltas"], [{"item": "Courses 7-12", "direction": "added",
                                                  "reason": "Twelve authored."}])

    def test_without_numbered_strings_the_design_count_stands(self):
        facts = facts_mod.extract(_courses_design(6), strings={"en": {"course.1": "Only one"}})
        self.assertEqual(facts["content_units"], 6)
        self.assertEqual(facts["conflicts"], [])

    def test_a_count_the_build_contradicts_is_refused_in_any_locale(self):
        facts = facts_mod.extract(_courses_design(6), strings=TWELVE)
        bad = {"title": "Fixture Game", "short_description": "Six floating sky courses to roll.",
               "long_description": "There is one input and no buttons. Ten gems per course; the last two "
                                   "courses ask for stars. Twelve courses in all.",
               "features": [], "tags": []}
        found = [p["message"] for p in grounding.check(bad, facts, [], locale="en")
                 if p["code"] == "contradicted-claim"]
        self.assertEqual(len(found), 1, found)
        self.assertIn("'Six floating sky courses'", found[0])
        # A pause button makes "no buttons" false.
        facts["controls"]["touch"] = ["Pause button"]
        found = [p["message"] for p in grounding.check(bad, facts, [], locale="en")
                 if p["code"] == "contradicted-claim"]
        self.assertEqual(len(found), 2, found)
        ru = {"title": "Fixture Game", "short_description": "Всего шесть небесных трасс.",
              "long_description": "Десять кристаллов на каждой трассе.", "features": [], "tags": []}
        found = [p["message"] for p in grounding.check(ru, facts, [], locale="ru")
                 if p["code"] == "contradicted-claim"]
        self.assertEqual(len(found), 1, found)
        self.assertIn("шесть небесных трасс", found[0])

    def test_the_template_writer_leaves_out_what_the_build_contradicts(self):
        design = _courses_design(6)
        design["build_spec"]["mechanics"][0]["description"] = ("Six sky courses of lanes to clear. "
                                                               "One tap switches lanes on the beat.")
        facts = facts_mod.extract(design, strings=TWELVE)
        reference = load_file(REFERENCE)
        copies, _ = copywriter.write_copy(facts, ["en"], reference)
        text = json.dumps(copies["en"])
        self.assertNotIn("Six sky courses", text)
        self.assertIn("One tap switches lanes on the beat", copies["en"]["long_description"])
        self.assertEqual([p for p in grounding.check(copies["en"], facts, reference["claims"], locale="en")
                          if p["code"] == "contradicted-claim"], [])


class Grounding(unittest.TestCase):
    def setUp(self):
        self.reference = load_file(REFERENCE)
        self.facts = facts_mod.extract(DESIGN)
        self.text = {"title": "Fixture Game", "short_description": "Tap on the beat.",
                     "long_description": "Tap on the beat to switch lanes.", "features": [], "tags": []}

    def check(self, **fields):
        text = {**self.text, **fields}
        return grounding.check(text, self.facts, self.reference["claims"], locale="en")

    def test_an_unbacked_capability_claim_is_an_error(self):
        problems = self.check(long_description="Play online multiplayer with friends and climb the leaderboards.")
        codes = sorted((p["code"], p["message"].split("says ")[1].split(",")[0]) for p in problems)
        self.assertEqual(codes, [("unbacked-claim", "'leaderboards'"), ("unbacked-claim", "'online multiplayer'")])

    def test_a_backed_claim_passes(self):
        facts = dict(self.facts, capabilities=["leaderboards"])
        problems = grounding.check({**self.text, "long_description": "Climb the leaderboards."}, facts,
                                   self.reference["claims"])
        self.assertEqual(problems, [])
        # The design is endless (no win), so `endless` is backed; 3D is not.
        self.assertEqual(grounding.check({**self.text, "promo": ["An endless run"]}, self.facts,
                                         self.reference["claims"]), [])
        self.assertEqual([p["code"] for p in grounding.check({**self.text, "promo": ["Now in 3D"]}, self.facts,
                                                             self.reference["claims"])], ["unbacked-claim"])

    def test_forbidden_words_and_rating_words(self):
        problems = self.check(promo=["The award-winning, addictive hit"])
        self.assertEqual(sorted(p["code"] for p in problems), ["forbidden-claim", "rating-word"])
        self.assertEqual([p["severity"] for p in problems if p["code"] == "rating-word"], ["warning"])

    def test_a_bullet_needs_a_fact_it_shares_words_with(self):
        problems = self.check(features=[{"text": "Fly a spaceship", "source": "mechanic:lane-switch"},
                                        {"text": "One tap switches lanes", "source": "mechanic:lane-switch"},
                                        {"text": "Anything", "source": "mechanic:nope"}])
        self.assertEqual([p["code"] for p in problems], ["bullet-unrelated", "bullet-without-source"])


# -- unit: platforms and the package ---------------------------------------------------------

class Platforms(unittest.TestCase):
    def setUp(self):
        self.reference = load_file(REFERENCE)

    def test_requirements_mark_what_a_profile_leaves_null_as_unknown(self):
        poki = platforms.requirements(platforms.load_profile("poki"), self.reference)
        by_id = {r["id"]: r for r in poki}
        self.assertFalse(by_id["text:title"]["known"])
        self.assertIsNone(by_id["text:title"]["max_chars"])
        self.assertTrue(by_id["screenshots"]["known"])
        self.assertEqual(by_id["screenshots"]["min"], 3)
        self.assertEqual(by_id["locale:en"]["required"], True)
        gd = {r["id"]: r for r in platforms.requirements(platforms.load_profile("gamedistribution"), self.reference)}
        self.assertEqual(gd["image:icon"]["sizes"], [(512, 512)])
        self.assertTrue(gd["image:icon"]["known"])
        self.assertEqual(platforms.spec_status(platforms.load_profile("generic-web")), "verified")
        self.assertEqual(platforms.spec_status({}), "absent")

    def test_a_profile_without_a_block_falls_back_to_the_coarse_fields(self):
        profile = {"metadata_requirements": {"screenshots_min": 2, "icon_required": True,
                                             "descriptions_locales": ["vi"]}}
        reqs = {r["id"]: r for r in platforms.requirements(profile, self.reference)}
        self.assertEqual(reqs["screenshots"]["min"], 2)
        self.assertTrue(reqs["image:icon"]["required"])
        self.assertFalse(reqs["image:icon"]["known"])
        self.assertIn("locale:vi", reqs)
        self.assertFalse(reqs["video"]["known"])

    def test_targets_come_from_the_scaffold_record(self):
        scaffold = {"game_config": {"platforms": [{"id": "poki", "profile": "poki@1.1.0", "role": "required"},
                                                  {"id": "yandex", "profile": "yandex@1.2.0", "role": "optional"}]}}
        self.assertEqual(platforms.targets(scaffold), [("poki", "required", "1.1.0"), ("yandex", "optional", "1.2.0")])
        self.assertEqual(platforms.targets(scaffold, ["yandex"]), [("yandex", "optional", "1.2.0")])
        self.assertEqual(platforms.locales_for(platforms.load_profile("yandex")), ["ru"])
        self.assertIsNotNone(platforms.block_hash(platforms.load_profile("poki")))
        self.assertIsNone(platforms.block_hash({}))


class Selection(unittest.TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp(prefix="wgf-select-")
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)
        self.reference = load_file(REFERENCE)

    def shot(self, scene, seed, state="playing", viewport="landscape", dark=False):
        path = os.path.join(self.base, viewport, f"{scene}.png")
        (dark_png(path, 320, 180) if dark else rich_png(path, 320, 180, seed=seed))
        return {"scene": scene, "file": path, "state": state, "excluded": state in ("loading", "other"),
                "viewport": viewport}

    def test_play_leads_excluded_dark_and_indistinct_frames_are_dropped(self):
        shots = [self.shot("title", 1, "title"), self.shot("play-early", 2), self.shot("play-mid", 3),
                 self.shot("play-late", 3), self.shot("result", 5, "loading"),
                 self.shot("play-early", 7, viewport="portrait", dark=True)]
        chosen, dropped = pkg.select_screenshots(shots, self.reference)
        self.assertEqual([c["scene"] for c in chosen], ["play-mid", "play-early", "title"])
        reasons = sorted(d["reason"].split(":")[0] for d in dropped)
        self.assertEqual(reasons, ["indistinct from play-mid (landscape)", "state loading is excluded", "too dark"])

    def test_showcase_frames_fill_in_for_play_that_does_not_change(self):
        # Three play frames of one dark board (the same seed) and the states the probe's
        # showcase staged: the showcase frames are the screenshots play could not give.
        shots = [self.shot("play-early", 4), self.shot("play-mid", 4), self.shot("play-late", 4),
                 self.shot("showcase-boss", 11), self.shot("showcase-embers", 23),
                 self.shot("showcase-laser-bolt", 37)]
        chosen, dropped = pkg.select_screenshots(shots, self.reference)
        self.assertEqual([c["scene"] for c in chosen],
                         ["play-mid", "showcase-boss", "showcase-embers", "showcase-laser-bolt"])
        self.assertEqual(sorted(d["reason"] for d in dropped),
                         ["indistinct from play-mid (landscape)"] * 2)

    def test_a_showcase_frame_meets_the_same_bars(self):
        shots = [self.shot("play-mid", 4), self.shot("showcase-boss", 4),
                 self.shot("showcase-embers", 0, dark=True), self.shot("showcase-laser-bolt", 0, state="loading")]
        chosen, dropped = pkg.select_screenshots(shots, self.reference)
        self.assertEqual([c["scene"] for c in chosen], ["play-mid"])
        reasons = sorted(d["reason"].split(":")[0] for d in dropped)
        self.assertEqual(reasons, ["indistinct from play-mid (landscape)", "state loading is excluded", "too dark"])

    def test_showcase_ranks_after_play_the_player_acted_in_and_before_the_rest(self):
        shots = [self.shot("title", 1, "title"), self.shot("result", 2, "won"), self.shot("play-early", 3),
                 self.shot("showcase-boss", 5), self.shot("play-late", 7), self.shot("play-mid", 9)]
        chosen, _ = pkg.select_screenshots(shots, self.reference)
        self.assertEqual([c["scene"] for c in chosen],
                         ["play-mid", "play-late", "showcase-boss", "play-early", "result", "title"])

    def test_the_maximum_holds(self):
        shots = [self.shot(f"play-mid", s, viewport=f"v{s}") for s in range(12)]
        chosen, _ = pkg.select_screenshots(shots, self.reference, maximum=4)
        self.assertEqual(len(chosen), 4)


class Rendition(unittest.TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp(prefix="wgf-render-")
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)
        self.run_dir = os.path.join(self.base, "run")
        self.reference = load_file(REFERENCE)
        masters = []
        for family, (w, h, rid) in {"icon": (96, 96, "icon-1024"), "thumbnail": (128, 72, "thumbnail-16x9"),
                                    "promo": (192, 108, "promo-1920x1080")}.items():
            path = rich_png(os.path.join(self.run_dir, "p", "branding", f"{rid}.png"), w, h, seed=len(masters))
            masters.append({"id": rid, "family": family, "path": path, "width": w, "height": h})
        shots = [{"id": f"landscape-0{i}-play", "path": rich_png(os.path.join(self.run_dir, "p", "screenshots", f"s{i}.png"), 320, 180, seed=i),
                  "viewport": "landscape", "width": 320, "height": 180} for i in range(1, 4)]
        trailer = make_webm(os.path.join(self.run_dir, "p", "trailer", "trailer.webm"), 12, 160, 90)
        self.canonical = {"masters": masters, "screenshots": shots,
                          "trailer": {"status": "recorded", "container": "webm", "path": trailer, "derived": []}}
        self.copies = {"en": {"title": "Fixture Game", "short_description": "Tap on the beat. " * 6,
                              "long_description": "Long. " * 40, "features": [{"text": "A", "source": "objective"}],
                              "tags": ["rhythm", "arcade", "zzz"], "categories": ["Arcade"], "promo": ["P" * 50]}}

    def render(self, profile, platform_id="test", age_rating=None, browser_formats=()):
        reqs = platforms.requirements(profile, self.reference)
        entry, derive = pkg.render_platform({"platform_id": platform_id, "profile_version": "1.1.0", "role": "required",
                                             "spec_status": platforms.spec_status(profile)}, reqs,
                                            canonical=self.canonical, copies=self.copies,
                                            out_dir=os.path.join(self.run_dir, "p", "platforms", platform_id),
                                            run_dir=self.run_dir, reference=self.reference,
                                            browser_formats=browser_formats, age_rating=age_rating)
        return entry, derive

    def test_images_are_rendered_at_the_sizes_asked_and_never_upscaled(self):
        profile = {"store_listing": {"status": "unverified",
                                     "icon": {"id": "icon", "required": True, "sizes": [{"width": 48, "height": 48}, {"width": 500, "height": 500}]},
                                     "covers": [{"id": "wide", "required": True, "aspect": "16:9", "sizes": None, "source": "thumbnail"}],
                                     "screenshots": {"required": True, "min": 2, "max": 2, "sizes": [{"width": 160, "height": 90}]},
                                     "video": {"required": True, "formats": ["webm"]},
                                     "short_description": {"required": True, "max_chars": 30},
                                     "tags": {"required": True, "max": 2, "allowed": ["rhythm", "arcade"]},
                                     "locales": ["en"]}}
        entry, derive = self.render(profile)
        ids = {f["id"]: f for f in entry["files"]}
        self.assertEqual((ids["icon-48x48"]["width"], ids["icon-48x48"]["height"]), (48, 48))
        self.assertEqual((ids["wide-128x72"]["width"], ids["wide-128x72"]["height"]), (128, 72))
        self.assertEqual(sorted(k for k in ids if k.startswith("screenshot")), ["screenshot-01", "screenshot-02"])
        self.assertEqual((ids["screenshot-01"]["width"], ids["screenshot-01"]["height"]), (160, 90))
        self.assertEqual(ids["trailer"]["format"], "webm")
        self.assertEqual([u["code"] for u in entry["unmet"]], ["size-above-master"])
        self.assertLessEqual(len(entry["text"]["en"]["short_description"]), 30)
        self.assertEqual(entry["text"]["en"]["tags"], ["rhythm", "arcade"])
        self.assertEqual(derive, [])

    def test_what_the_package_cannot_make_is_unmet_never_silent(self):
        profile = {"store_listing": {"status": "unverified", "locales": ["ru"],
                                     "icon": {"id": "icon", "required": True, "formats": ["jpg"]},
                                     "video": {"required": True, "formats": ["mp4"]},
                                     "age_rating": {"required": True}}}
        entry, derive = self.render(profile)
        codes = sorted(u["code"] for u in entry["unmet"])
        self.assertEqual(codes, ["age-rating-missing", "format-unavailable", "locale-missing",
                                 "video-format-unavailable"])
        self.assertEqual(entry["text"], {})
        # With the browser's encoders, a jpg is a derive job for the browser, not an unmet.
        entry, derive = self.render(profile, browser_formats=("jpg", "webp"), age_rating={"default": "3+"})
        self.assertEqual([d["format"] for d in derive], ["jpg"])
        self.assertNotIn("format-unavailable", [u["code"] for u in entry["unmet"]])

    def test_an_age_rating_comes_from_configuration_or_is_missing(self):
        profile = {"store_listing": {"status": "unverified", "locales": ["en"], "age_rating": {"required": True}}}
        entry, _ = self.render(profile)
        self.assertIn("age-rating-missing", [u["code"] for u in entry["unmet"]])
        entry, _ = self.render(profile, age_rating={"test": "12+"})
        self.assertEqual(entry["text"]["en"]["age_rating"], "12+")
        self.assertEqual(entry["age_rating"], "12+")
        self.assertNotIn("age-rating-missing", [u["code"] for u in entry["unmet"]])

    def test_the_configured_age_rating_reaches_the_rendition_without_copy(self):
        # Sky Marble: `factory.listing.age_rating: {default: 12+}` was set, and yandex still
        # reported it missing because it was only written into copy that did not exist.
        profile = {"store_listing": {"status": "unverified", "locales": ["ru"], "age_rating": {"required": True}}}
        entry, _ = self.render(profile, platform_id="yandex", age_rating={"default": "12+"})
        self.assertEqual(entry["text"], {})
        self.assertEqual(entry["age_rating"], "12+")
        self.assertEqual([u["code"] for u in entry["unmet"]], ["locale-missing"])


# -- the step --------------------------------------------------------------------------------

@unittest.skipUnless(HAS_GIT, "git is not installed")
class TheStep(ListingCase):
    def test_a_verified_build_yields_a_complete_package(self):
        result, fake = self.capture()
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error or result.message)
        listing = self.listing_of(result)
        self.assertEqual(listing["status"], "complete", listing["problems"])
        self.assertEqual(listing["commit"], self.game.head)
        self.assertEqual(listing["build"]["bundle_hash"], bundle_digest(self.game.root, "dist"))
        self.assertEqual(listing["branding"]["method"], "browser-composed")
        self.assertEqual(sorted(i["id"] for i in listing["branding"]["items"]),
                         ["icon-1024", "icon-256", "icon-512", "logo-wordmark", "promo-1920x1080",
                          "thumbnail-16x9", "thumbnail-1x1", "thumbnail-4x3"])
        # Portrait first for a portrait design; play frames lead, the title last.
        self.assertEqual([v["id"] for v in fake.calls[0]["viewports"]], ["portrait", "landscape"])
        self.assertEqual(listing["screenshots"][0]["scene"], "play-mid")
        self.assertEqual(len(listing["screenshots"]), 8)
        self.assertEqual(listing["trailer"]["status"], "recorded")
        self.assertEqual((listing["trailer"]["container"], listing["trailer"]["duration_s"],
                          listing["trailer"]["trimmed"]), ("webm", 12.0, True))
        self.assertEqual(sorted(listing["copy"]["locales"]), ["en", "ru"])
        self.assertEqual(listing["copy"]["grounding"]["problems"], [])
        self.assertEqual([p["platform_id"] for p in listing["platforms"]], ["generic-web"])
        self.assertEqual(listing["platforms"][0]["unmet"], [])
        # Every file the listing names is on disk under the run directory with its hash.
        for record in listing["branding"]["items"] + listing["screenshots"] + listing["platforms"][0]["files"]:
            path = os.path.join(self.run_dir, *record["path"].split("/"))
            self.assertTrue(os.path.isfile(path), record["path"])
            self.assertEqual(media.sha256_of(path), record["sha256"])
        package = os.path.join(self.run_dir, *listing["package_dir"].split("/"))
        self.assertTrue(os.path.isfile(os.path.join(package, "listing.json")))
        self.assertTrue(os.path.isfile(os.path.join(package, "copy", "en.json")))
        self.assertTrue(os.path.isfile(os.path.join(package, "platforms", "generic-web", "listing.json")))
        # The checkout is untouched.
        status = subprocess.run(["git", "status", "--porcelain"], cwd=self.game.root, capture_output=True, text=True)
        self.assertEqual(status.stdout.strip(), "")

    def test_too_few_usable_frames_retries_with_a_longer_window_then_says_so(self):
        # One viewport whose play frames never change: two distinct frames (title, play),
        # below the minimum of three, on every attempt.
        one = {"listing": {"capture": {"viewports": [{"id": "landscape", "width": 320, "height": 180}]}}}
        result, fake = self.capture(FakeCapture(plan=["few", "few", "few"]), context=self.context(config=one))
        self.assertEqual(result.outcome, StepOutcome.SUCCESS)
        attempts = [c for c in fake.calls if c.get("viewports")]
        self.assertEqual(len(attempts), 3)  # retries: 2
        self.assertLess(attempts[0]["settings"]["play_ms"], attempts[2]["settings"]["play_ms"])
        listing = self.listing_of(result)
        self.assertEqual(listing["capture"]["attempts"], 3)
        self.assertEqual(len(listing["screenshots"]), 2)
        self.assertEqual(listing["status"], "incomplete")
        self.assertIn("screenshots-insufficient", [p["code"] for p in listing["problems"]])

    def test_showcase_frames_make_up_for_play_frames_that_never_change(self):
        one = {"listing": {"capture": {"viewports": [{"id": "landscape", "width": 320, "height": 180}]}}}
        result, fake = self.capture(FakeCapture(plan=["few-showcase"]), context=self.context(config=one))
        self.assertEqual(result.outcome, StepOutcome.SUCCESS)
        self.assertEqual(len([c for c in fake.calls if c.get("viewports")]), 1)  # no retry needed
        listing = self.listing_of(result)
        scenes = [s["scene"] for s in listing["screenshots"]]
        self.assertEqual(scenes, ["play-mid", "showcase-boss", "showcase-embers", "showcase-laser-bolt", "title"])
        self.assertNotIn("screenshots-insufficient", [p["code"] for p in listing["problems"]])

    def test_showcase_frames_below_the_bars_do_not_count(self):
        one = {"listing": {"capture": {"viewports": [{"id": "landscape", "width": 320, "height": 180}]}}}
        result, fake = self.capture(FakeCapture(plan=["few-showcase-same"] * 3), context=self.context(config=one))
        listing = self.listing_of(result)
        self.assertEqual(len([c for c in fake.calls if c.get("viewports")]), 3)
        self.assertEqual([s["scene"] for s in listing["screenshots"]], ["play-mid", "title"])
        self.assertIn("screenshots-insufficient", [p["code"] for p in listing["problems"]])

    def test_dark_frames_make_the_package_incomplete_not_a_lie(self):
        result, _ = self.capture(FakeCapture(plan=["dark", "dark", "dark"]))
        self.assertEqual(result.outcome, StepOutcome.SUCCESS)
        listing = self.listing_of(result)
        self.assertEqual(listing["status"], "incomplete")
        self.assertIn("screenshots-insufficient", [p["code"] for p in listing["problems"]])
        self.assertIn("incomplete", result.message)

    def test_no_recording_falls_back_to_a_labelled_frame_sequence(self):
        result, _ = self.capture(FakeCapture(plan=["no-trailer"]))
        listing = self.listing_of(result)
        self.assertEqual(listing["trailer"]["status"], "fallback")
        self.assertTrue(listing["trailer"]["frames"])
        self.assertTrue(os.path.isfile(os.path.join(self.run_dir, *listing["trailer"]["storyboard"].split("/"))))
        self.assertIn("trailer-fallback", [p["code"] for p in listing["problems"]])
        self.assertEqual(listing["status"], "complete")  # no platform requires a video

    def test_no_browser_blocks_with_the_listing_as_evidence(self):
        result, _ = self.capture(FakeCapture(plan=["blocked"]))
        self.assertEqual(result.outcome, StepOutcome.BLOCKED)
        listing = self.listing_of(result)
        self.assertEqual(listing["status"], "blocked")
        self.assertIn("no browser", result.message)

    def test_a_crashed_capture_is_a_retryable_failure(self):
        result, _ = self.capture(FakeCapture(plan=["crash"]))
        self.assertEqual(result.outcome, StepOutcome.FAILED)
        self.assertTrue(result.retryable)

    def test_capture_kind_none_blocks_never_a_silent_pass(self):
        result, fake = self.capture(context=self.context(config={"listing": {"capture": {"kind": "none"}}}))
        self.assertEqual(result.outcome, StepOutcome.BLOCKED)
        self.assertEqual(fake.calls, [])
        self.assertIn("never a silent pass", result.message.replace("would be a silent pass", "never a silent pass"))

    def test_the_gate_the_checkout_and_the_bundle_are_checked(self):
        result, fake = self.capture(context=self.context(gates_passed=()))
        self.assertEqual(result.outcome, StepOutcome.BLOCKED)
        self.assertIn("G4", result.message)
        self.assertEqual(fake.calls, [])
        # Another commit than HEAD.
        result, _ = self.capture(artifacts=self.game.evidence(commit="b" * 40))
        self.assertEqual(result.outcome, StepOutcome.BLOCKED)
        self.assertIn("moved after verification", result.message)
        # A bundle that is not the verified one.
        result, _ = self.capture(artifacts=self.game.evidence(bundle_hash="sha256:" + "f" * 64))
        self.assertEqual(result.outcome, StepOutcome.BLOCKED)
        self.assertIn("not the bundle that was verified", result.message)

    def test_a_failed_verification_is_refused_for_good(self):
        result, _ = self.capture(artifacts=self.game.evidence(qa_verdict="fail", verdict="FAIL"))
        self.assertEqual(result.outcome, StepOutcome.FAILED)
        self.assertFalse(result.retryable)
        self.assertEqual(result.artifacts, [])

    def test_missing_inputs_wait(self):
        step = listing_step(FakeCapture(), repo_dir=self.game.root)
        result = step.execute(Inputs({}, missing=["qa-report"]), self.context())
        self.assertEqual(result.outcome, StepOutcome.WAITING_FOR_INPUT)

    def test_a_platform_requiring_an_age_rating_gets_the_configured_one(self):
        self.image_sizes_unstated()
        platforms_ = [{"id": "yandex", "profile": "yandex@1.2.0", "role": "required"}]
        result, _ = self.capture(artifacts=self.game.evidence(platforms=platforms_))
        listing = self.listing_of(result)
        self.assertEqual(listing["status"], "incomplete")
        self.assertIn("age-rating-missing", [p["code"] for p in listing["problems"]])
        result, _ = self.capture(artifacts=self.game.evidence(platforms=platforms_),
                                 context=self.context(config={"listing": {"age_rating": {"yandex": "0+"}}}))
        listing = self.listing_of(result)
        self.assertEqual(listing["status"], "complete", listing["problems"])
        self.assertEqual(listing["platforms"][0]["text"]["ru"]["age_rating"], "0+")
        self.assertEqual(listing["platforms"][0]["locales_required"], ["ru"])

    def test_a_command_writer_whose_text_is_ungrounded_is_asked_once_then_replaced(self):
        writer = os.path.join(self.scratch, "writer.py")
        with open(writer, "w", encoding="utf-8") as handle:
            handle.write(textwrap.dedent('''\
                import json, sys
                out = sys.argv[1]
                json.dump({"title": "Fixture Game", "short_description": "Award-winning online multiplayer!",
                           "long_description": "Climb the leaderboards with friends." * 5,
                           "features": [{"text": "Tap on the beat", "source": "objective"}],
                           "tags": ["rhythm"], "categories": ["Arcade"], "promo": []}, open(out, "w"))
            '''))
        config = {"listing": {"writer": {"kind": "command", "argv": [sys.executable, writer, "{output}"],
                                         "timeout_seconds": 60}}}
        result, _ = self.capture(context=self.context(config=config))
        listing = self.listing_of(result)
        self.assertEqual(listing["copy"]["writer"]["kind"], "command")
        self.assertTrue(listing["copy"]["writer"]["fallback"])
        self.assertEqual(listing["copy"]["writer"]["runs"], 2 * 2)  # two locales, two tries each
        self.assertNotIn("multiplayer", listing["copy"]["locales"]["en"]["short_description"].lower())
        self.assertEqual(listing["copy"]["grounding"]["problems"], [])


# -- validation --------------------------------------------------------------------------

@unittest.skipUnless(HAS_GIT, "git is not installed")
class Validation(ListingCase):
    def test_a_complete_listing_passes_and_names_what_is_unknown(self):
        result, _ = self.capture()
        listing = self.listing_of(result)
        outcome, report = self.validate(listing)
        self.assertEqual(outcome.outcome, StepOutcome.SUCCESS, outcome.error)
        self.assertEqual(report["verdict"], "PASS")
        self.assertEqual(report["failed"], [])
        self.assertEqual(report["sections"]["screenshots"], "PASS")
        self.assertEqual(report["sections"]["grounding"], "PASS")
        self.assertEqual(report["platform_requirements"][0]["status"], "PASS")
        # generic-web states no title limit: UNKNOWN, listed, not a pass of that limit.
        self.assertIn("platforms.generic-web.text:title", report["unknown"])
        self.assertEqual([c["status"] for c in report["checks"] if c["id"] == "platforms.generic-web.text:title"],
                         ["UNKNOWN"])
        package = os.path.join(self.run_dir, *listing["package_dir"].split("/"))
        self.assertTrue(os.path.isfile(os.path.join(package, "validation.json")))

    def test_a_screenshot_that_changed_fails_and_routes_back_to_the_listing(self):
        result, _ = self.capture()
        listing = self.listing_of(result)
        shot = listing["screenshots"][0]
        dark_png(os.path.join(self.run_dir, *shot["path"].split("/")), shot["width"], shot["height"])
        outcome, report = self.validate(listing)
        self.assertEqual(outcome.outcome, StepOutcome.FAILED)
        self.assertEqual(outcome.route, "listing")
        self.assertFalse(outcome.retryable)
        self.assertEqual(report["verdict"], "FAIL")
        self.assertEqual(report["routes"], ["listing"])
        self.assertTrue(any(f.startswith(f"screenshots.{shot['id']}") for f in report["failed"]), report["failed"])

    def test_an_unbacked_claim_in_the_copy_fails_grounding(self):
        result, _ = self.capture()
        listing = self.listing_of(result)
        listing["copy"]["locales"]["en"]["promo"] = ["Online multiplayer with friends"]
        listing["provenance"]["content_hash"] = content_hash(listing)
        outcome, report = self.validate(listing)
        self.assertEqual(report["verdict"], "FAIL")
        self.assertEqual(report["sections"]["grounding"], "FAIL")
        self.assertIn("grounding.en", report["failed"])

    def test_a_game_with_its_own_ru_keys_gets_a_grounded_yandex_rendition_and_passes(self):
        self.image_sizes_unstated()
        self.game = GameBuild(os.path.join(self.scratch, "own-keys"), strings={
            "en": {"game.title": "Fixture Game", "play.objective": "Tap on the beat to switch lanes and keep the combo alive."},
            "ru": {"game.title": "Fixture Game", "play.objective": "Нажимайте в такт, чтобы менять полосу."}})
        platforms_ = [{"id": "yandex", "profile": "yandex@1.2.0", "role": "optional"}]
        result, _ = self.capture(artifacts=self.game.evidence(platforms=platforms_),
                                 context=self.context(config={"listing": {"age_rating": {"default": "12+"}}}))
        listing = self.listing_of(result)
        self.assertEqual(listing["status"], "complete", listing["problems"])
        self.assertEqual(sorted(listing["copy"]["locales"]), ["en", "ru"])
        yandex = listing["platforms"][0]
        self.assertEqual(sorted(yandex["text"]), ["ru"])
        self.assertEqual(yandex["text"]["ru"]["short_description"], "Нажимайте в такт, чтобы менять полосу.")
        self.assertEqual(yandex["text"]["ru"]["categories"], ["Arcade"])
        self.assertEqual(yandex["text"]["ru"]["age_rating"], "12+")
        self.assertEqual(yandex["age_rating"], "12+")
        outcome, report = self.validate(listing)
        self.assertEqual(report["failed"], [], [c for c in report["checks"] if c["status"] == "FAIL"])
        self.assertEqual(report["verdict"], "PASS")
        self.assertEqual(report["platform_requirements"][0]["status"], "PASS")

    def test_a_required_locale_the_game_lacks_blocks_once_for_a_person_never_loops(self):
        # Without ru strings the texts and categories of yandex are empty; that is the
        # locale's gap, which rewriting cannot close: BLOCKED naming it, not FAIL back to the
        # listing until the loop limit.
        self.game = GameBuild(os.path.join(self.scratch, "en-only"), strings={
            "en": {"title.heading": "Fixture Game", "hud.objective": "Tap on the beat to switch lanes."}})
        platforms_ = [{"id": "yandex", "profile": "yandex@1.2.0", "role": "required"}]
        result, _ = self.capture(artifacts=self.game.evidence(platforms=platforms_),
                                 context=self.context(config={"listing": {"age_rating": {"default": "12+"}}}))
        listing = self.listing_of(result)
        self.assertEqual(listing["platforms"][0]["age_rating"], "12+")
        outcome, report = self.validate(listing)
        self.assertEqual(outcome.outcome, StepOutcome.BLOCKED)
        self.assertEqual(report["verdict"], "BLOCKED")
        self.assertNotIn("platforms.yandex.age_rating", report["failed"])
        self.assertIn("platforms.yandex.locale:ru", report["failed"])
        self.assertIn("platforms.yandex.list:categories", report["failed"])
        failed = [c for c in report["checks"] if c["status"] == "FAIL"]
        self.assertTrue(all(c["fix"] == "configure" for c in failed), failed)
        categories = next(c for c in failed if c["id"] == "platforms.yandex.list:categories")
        self.assertIn("no copy in required locale ru", categories["summary"])

    def test_a_person_can_supply_the_copy_and_it_is_still_grounded(self):
        supplied_dir = os.path.join(self.scratch, "listing-copy")
        os.makedirs(supplied_dir)
        ru = {"title": "Fixture Game", "short_description": "Нажимайте в такт, чтобы менять полосу.",
              "long_description": "Нажимайте в такт, чтобы менять полосу и держать комбо.",
              "features": [{"text": "Нажимайте в такт, чтобы менять полосу", "source": "string:ru:title.rules"}],
              "tags": ["rhythm", "arcade", "casual"], "categories": ["Arcade"]}
        with open(os.path.join(supplied_dir, "ru.json"), "w", encoding="utf-8") as handle:
            json.dump(ru, handle, ensure_ascii=False)
        config = {"listing": {"copy_dir": supplied_dir}}
        result, _ = self.capture(context=self.context(config=config))
        listing = self.listing_of(result)
        self.assertEqual(listing["copy"]["locales"]["ru"]["long_description"], ru["long_description"])
        self.assertEqual(list(listing["copy"]["supplied"]), ["ru"])
        outcome, report = self.validate(listing)
        self.assertEqual(report["verdict"], "PASS", [c for c in report["checks"] if c["status"] == "FAIL"])
        # A person's text the build contradicts is refused - and is the person's to fix.
        ru["long_description"] = "Нажимайте в такт. Всего двадцать уровней и нет кнопок."
        ru["features"].append({"text": "Онлайн-рейтинг", "source": "nowhere"})
        with open(os.path.join(supplied_dir, "ru.json"), "w", encoding="utf-8") as handle:
            json.dump(ru, handle, ensure_ascii=False)
        result, _ = self.capture(context=self.context(config=config))
        listing = self.listing_of(result)
        outcome, report = self.validate(listing)
        self.assertEqual(outcome.outcome, StepOutcome.BLOCKED)
        grounding_ru = next(c for c in report["checks"] if c["id"] == "grounding.ru")
        self.assertEqual((grounding_ru["status"], grounding_ru["fix"]), ("FAIL", "configure"))
        self.assertIn("supplied", grounding_ru["summary"])

    def test_a_supplied_file_that_is_not_copy_is_a_problem_never_used(self):
        supplied_dir = os.path.join(self.scratch, "listing-copy")
        os.makedirs(supplied_dir)
        with open(os.path.join(supplied_dir, "ru.json"), "w", encoding="utf-8") as handle:
            json.dump({"title": "X", "blurb": "?"}, handle)
        result, _ = self.capture(context=self.context(config={"listing": {"copy_dir": supplied_dir}}))
        listing = self.listing_of(result)
        self.assertNotIn("supplied", listing["copy"])
        self.assertIn("copy-supplied-invalid", [p["code"] for p in listing["problems"]])
        self.assertTrue(listing["copy"]["locales"]["ru"]["short_description"].startswith("Нажимайте"))

    def test_scope_deltas_come_from_the_report_of_this_build_only(self):
        step = listing_step(FakeCapture(), repo_dir=self.game.root)
        context = self.context()
        report = {"build_ref": {"commit_sha": self.game.head}, "scope_deltas": []}
        self.assertIs(step._report_of_this_build(report, self.game.root, self.game.head, context), report)
        other = {"build_ref": {"commit_sha": "b" * 40}, "scope_deltas": []}
        self.assertIsNone(step._report_of_this_build(other, self.game.root, self.game.head, context))
        self.assertIsNone(step._report_of_this_build(None, self.game.root, self.game.head, context))

    def test_only_a_person_can_fix_it_blocks(self):
        self.image_sizes_unstated()
        platforms_ = [{"id": "yandex", "profile": "yandex@1.2.0", "role": "required"}]
        result, _ = self.capture(artifacts=self.game.evidence(platforms=platforms_))
        listing = self.listing_of(result)
        outcome, report = self.validate(listing)
        self.assertEqual(outcome.outcome, StepOutcome.BLOCKED)
        self.assertEqual(report["verdict"], "BLOCKED")
        self.assertEqual(report["failed"], ["platforms.yandex.age_rating"])
        self.assertIn("age rating", report["blocked_reason"])
        self.assertEqual(report["platform_requirements"][0]["status"], "FAIL")

    def test_a_blocked_listing_blocks_validation(self):
        result, _ = self.capture(FakeCapture(plan=["blocked"]))
        listing = self.listing_of(result)
        outcome, report = self.validate(listing)
        self.assertEqual(outcome.outcome, StepOutcome.BLOCKED)
        self.assertEqual(report["verdict"], "BLOCKED")

    def test_a_video_the_platform_requires_cannot_be_a_fallback(self):
        result, _ = self.capture(FakeCapture(plan=["no-trailer"]))
        listing = self.listing_of(result)
        reference = load_file(REFERENCE)
        profiles = {"generic-web": {"store_listing": {"status": "verified", "locales": ["en"],
                                                      "video": {"required": True, "formats": ["webm"]}}}}
        checks, _ = validate(listing, self.run_dir, reference, profiles, listing["facts"])
        video = next(c for c in checks if c["id"] == "video.trailer")
        self.assertEqual((video["status"], video["fix"]), ("FAIL", "configure"))


class MasterChoice(unittest.TestCase):
    MASTERS = [{"id": "thumbnail-16x9", "family": "thumbnail", "width": 1280, "height": 720},
               {"id": "thumbnail-1x1", "family": "thumbnail", "width": 1024, "height": 1024},
               {"id": "thumbnail-2x3", "family": "thumbnail", "width": 1200, "height": 1800}]

    def test_an_aspect_no_master_has_is_cut_from_the_nearest_not_the_largest(self):
        req = {"source": "thumbnail", "sizes": [(800, 470)]}
        self.assertEqual(pkg._master_for(req, self.MASTERS)["id"], "thumbnail-16x9")

    def test_an_exact_aspect_wins(self):
        req = {"source": "thumbnail", "aspect": "2:3", "sizes": [(800, 1200)]}
        self.assertEqual(pkg._master_for(req, self.MASTERS)["id"], "thumbnail-2x3")


class PlatformVideoBounds(unittest.TestCase):
    """A platform's stated video bounds are checked against the included trailer, not only
    its format: a profile saying 20 s maximum must not pass a 30 s recording."""

    def setUp(self):
        self.run_dir = tempfile.mkdtemp(prefix="wgf-video-")
        self.addCleanup(shutil.rmtree, self.run_dir, ignore_errors=True)
        path = make_webm(os.path.join(self.run_dir, "p", "trailer.webm"), duration_s=30.0,
                         width=1280, height=720)
        self.made = [{"id": "trailer", "path": "p/trailer.webm", "sha256": media.sha256_of(path)}]

    def problems(self, **bounds):
        from wgf_listing.validation import _video_problems
        return _video_problems(self.made, bounds, self.run_dir, {})

    def test_bounds_the_recording_meets_pass(self):
        self.assertEqual(self.problems(max_seconds=30, max_mb=50, min_width=1280, aspect="16:9"), [])

    def test_each_bound_the_recording_misses_is_named(self):
        problems = self.problems(max_seconds=20, min_height=1080, aspect="2:3")
        self.assertEqual(len(problems), 3)
        self.assertIn("30.0 s > 20 s", problems[0])
        self.assertIn("720 px high < 1080", problems[1])
        self.assertIn("is not 2:3", problems[2])

    def test_null_bounds_are_not_checked(self):
        self.assertEqual(self.problems(max_seconds=None, min_height=None, aspect=None), [])

    def test_a_changed_file_is_a_problem(self):
        self.made[0]["sha256"] = "sha256:" + "0" * 64
        self.assertEqual(self.problems(), ["trailer missing or changed"])


# -- the mock, the engine and the release ----------------------------------------------------

class TheMock(unittest.TestCase):
    def test_mock_listing_and_validation_shapes(self):
        registry = mock.register(StepRegistry())
        for step_type in ("store-listing", "listing-validation"):
            self.assertIsNotNone(registry.resolve(step_type))

        class Inputs:
            refs, missing = {}, []

            def __contains__(self, k):
                return False

            def load(self, k):
                return None

        class Log:
            def __getattr__(self, name):
                return lambda *a, **k: None
        ctx = types.SimpleNamespace(environment={"mock_plan": {"listing-validation": ["fail", "blocked", "pass"]}},
                                    execution=1, visit=1, attempt=1, project_id="demo", logger=Log(),
                                    previous_outputs=[])
        step = mock.MockListingValidationStep(StepDefinition({"id": "listing-validation", "type": "listing-validation",
                                                              "outputs": ["listing-validation-report"]}, retry=None, max_visits=None))
        first = step.execute(Inputs(), ctx)
        self.assertEqual((first.outcome, first.route, first.retryable), (StepOutcome.FAILED, "listing", False))
        self.assertEqual(first.artifacts[0].content["verdict"], "FAIL")
        ctx.execution = 2
        second = step.execute(Inputs(), ctx)
        self.assertEqual(second.outcome, StepOutcome.BLOCKED)
        ctx.execution = 3
        third = step.execute(Inputs(), ctx)
        self.assertEqual(third.outcome, StepOutcome.SUCCESS)
        for result in (first, second, third):
            self.assertEqual(CONTRACTS.problems("listing-validation-report", result.artifacts[0].content), [])
        listing = mock.MockStoreListingStep(StepDefinition({"id": "store-listing", "type": "store-listing",
                                                            "outputs": ["store-listing"]}, retry=None, max_visits=None))
        ctx.environment = {"mock_plan": {"store-listing": ["incomplete"]}}
        ctx.execution = 1
        result = listing.execute(Inputs(), ctx)
        self.assertEqual(result.outcome, StepOutcome.SUCCESS)
        self.assertEqual(result.artifacts[0].content["status"], "incomplete")
        self.assertEqual(CONTRACTS.problems("store-listing", result.artifacts[0].content), [])


@unittest.skipUnless(HAS_GIT, "git is not installed")
class ThroughTheEngine(ListingCase):
    """evidence (scripted) -> store-listing (real, fake capture) -> listing-validation (real),
    the way factory.yaml wires the module in."""

    def test_both_steps_run_in_a_workflow_and_persist_their_artifacts(self):
        from wgflib.workflow import ArtifactOutput, StepResult, WorkflowStep
        from wgflib.workflow.api import RunRequest, WorkflowAPI
        from wgflib.workflow.config import FactoryConfig
        from wgflib.workflow.model import RunStatus
        game = self.game
        fake = FakeCapture()

        class Evidence(WorkflowStep):
            type = "test.evidence"

            def execute(self, inputs, context):
                # The engine validates every artifact: the shipped mock design, which is
                # schema-valid, stands in for the test's partial one.
                evidence = game.evidence(design=fixture("game-design"))
                return StepResult.success([ArtifactOutput(t, a) for t, a in evidence.items()])

        class Listing(StoreListingStep):
            capture_runner = staticmethod(fake)
            clock = staticmethod(lambda: NOW)

        module = type(sys)("wgf_listing_engine_fakes")

        def register_fakes(registry):
            registry.register(Evidence.type, Evidence)
            registry.register(Listing.type, Listing)
            registry.register(ListingValidationStep.type, ListingValidationStep)
        module.register = register_fakes
        sys.modules[module.__name__] = module
        self.addCleanup(sys.modules.pop, module.__name__, None)
        path = os.path.join(self.scratch, "listing-flow.workflow.yaml")
        with open(path, "w") as handle:
            handle.write(textwrap.dedent("""\
                workflow:
                  id: listing-flow
                  version: 1
                  start: evidence
                  steps:
                    - id: evidence
                      type: test.evidence
                      stage: release:qa
                      outputs: [qa-report, verification-report, game-design, scaffold-record]
                    - id: store-listing
                      type: store-listing
                      stage: release:store-listing
                      inputs: [qa-report, verification-report, game-design, scaffold-record, listing-validation-report]
                      outputs: [store-listing]
                      with:
                        repo_dir: %s
                        required_gates: []
                        reference: %s
                    - id: listing-validation
                      type: listing-validation
                      stage: release:store-listing
                      inputs: [store-listing, game-design]
                      outputs: [listing-validation-report]
                      with:
                        reference: %s
                      on:
                        listing: store-listing
                      next: $end
                """ % (json.dumps(game.root), json.dumps(REFERENCE), json.dumps(REFERENCE))))
        # An MVP-tier run: the template writer writes (store-listing.yaml `writer`); at the
        # release tier the copywriter agent must (test_listing_build).
        config = FactoryConfig({"steps": {"modules": [module.__name__]}, "storage": {"fsync": False},
                                "strategy": {"quality_tier": "mvp"}})
        api = WorkflowAPI(config=config, store_dir=os.path.join(self.scratch, "store"), workflow=path)
        state = api.run(RunRequest(project_id="fixture-game"))
        self.assertEqual(state.status, RunStatus.COMPLETED, state.message)
        self.assertEqual([e["step"] for e in state.trail], ["evidence", "store-listing", "listing-validation"])
        listing_ref = state.latest_of_type("store-listing")
        report_ref = state.latest_of_type("listing-validation-report")
        listing = api.store.read_artifact(state.run_id, listing_ref)
        report = api.store.read_artifact(state.run_id, report_ref)
        self.assertEqual(listing["status"], "complete", listing["problems"])
        self.assertEqual(report["verdict"], "PASS", report["failed"])
        self.assertEqual(report["listing"]["content_hash"], listing_ref.content_hash)
        run_dir = api.store.run_dir(state.run_id)
        self.assertTrue(os.path.isdir(os.path.join(run_dir, *listing["package_dir"].split("/"))))


@unittest.skipUnless(HAS_GIT, "git is not installed")
class ReleaseIntegration(unittest.TestCase):
    """The release step ships the validated listing, and refuses without one."""

    def setUp(self):
        self.scratch = tempfile.mkdtemp(prefix="wgf-listing-release-")
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)
        self.game = release_tests.GameRepository(self.scratch)
        self.run_dir = os.path.join(self.scratch, "run")
        os.makedirs(self.run_dir)

    def listing(self, commit=None, status="complete", verdict="PASS", with_report=True):
        body = fixture("store-listing")
        body.update(title_id="fixture-game", commit=commit or self.game.head, status=status,
                    package_dir="store-listing/1-1/package")
        body["platforms"] = [{"platform_id": "generic-web", "profile_version": "1.1.0", "role": "required",
                              "spec_status": "verified", "dir": "store-listing/1-1/package/platforms/generic-web",
                              "listing": "store-listing/1-1/package/platforms/generic-web/listing.json",
                              "files": [], "text": {"en": body["copy"]["locales"]["en"]}, "locales_required": ["en"],
                              "unmet": []}]
        package = os.path.join(self.run_dir, "store-listing", "1-1", "package")
        os.makedirs(os.path.join(package, "platforms", "generic-web"), exist_ok=True)
        icon = rich_png(os.path.join(package, "platforms", "generic-web", "icon-96x96.png"), 96, 96)
        shot = rich_png(os.path.join(package, "platforms", "generic-web", "screenshot-01.png"), 320, 180, seed=2)
        body["platforms"][0]["files"] = [
            pkg.file_record("icon-96x96", icon, self.run_dir, kind="icon", requirement="icon"),
            pkg.file_record("screenshot-01", shot, self.run_dir, kind="screenshot", requirement="screenshots")]
        listing = release_tests.seal("store-listing", body, schema_version="1.0.0")
        if not with_report:
            return {"store-listing": listing}
        report = fixture("listing-validation-report")
        report.update(title_id="fixture-game", commit=listing["commit"], verdict=verdict,
                      listing={"artifact_id": listing["provenance"]["artifact_id"],
                               "content_hash": listing["provenance"]["content_hash"], "status": status},
                      failed=["x"] if verdict != "PASS" else [], routes=["listing"] if verdict == "FAIL" else [])
        return {"store-listing": listing,
                "listing-validation-report": release_tests.seal("listing-validation-report", report,
                                                                schema_version="1.0.0")}

    def release(self, extra=None, required_listing=True, **params):
        params.setdefault("repo_dir", self.game.root)
        params["required_listing"] = required_listing
        step = release_tests.step(**params)
        step.environ = self.game.environ()
        step.clock = staticmethod(lambda: release_tests.NOW)
        artifacts = dict(self.game.evidence())
        artifacts.update(extra or {})
        context = release_tests.Context()
        context.run_dir = self.run_dir
        return step.execute(release_tests.Inputs(artifacts), context)

    def codes(self, result):
        return {r["code"] for r in result.data.get("refusals", [])}

    def test_a_validated_listing_ships_beside_the_packages(self):
        result = self.release(self.listing())
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error or result.message)
        manifest = result.artifacts[0].content
        self.assertEqual(release_tests.CONTRACTS.problems("release-manifest", manifest), [])
        self.assertEqual(sorted(manifest["store_metadata"]), ["generic-web"])
        entry = manifest["store_metadata"]["generic-web"]
        self.assertEqual(entry["title"], "Mock Title")
        self.assertEqual(entry["locales_included"], ["en"])
        self.assertEqual(entry["icon"], "listing/platforms/generic-web/icon-96x96.png")
        self.assertEqual(entry["screenshots"], ["listing/platforms/generic-web/screenshot-01.png"])
        self.assertIn("en", entry["descriptions"])
        self.assertEqual(manifest["evidence"]["store_listing"]["validation"]["verdict"], "PASS")
        self.assertTrue(os.path.isfile(self.game.path("release", "r1", "listing", "platforms", "generic-web",
                                                      "icon-96x96.png")))
        self.assertIn("listing shipped", result.message)

    def test_no_listing_blocks_when_required_and_passes_when_the_workflow_says_otherwise(self):
        result = self.release()
        self.assertEqual(result.outcome, StepOutcome.BLOCKED)
        self.assertIn("no-store-listing", self.codes(result))
        result = self.release(required_listing=False)
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error or result.message)
        self.assertNotIn("store_metadata", result.artifacts[0].content)
        self.assertIn("no store listing", result.message)

    def test_a_listing_of_another_commit_an_incomplete_one_and_an_unvalidated_one_are_refused(self):
        result = self.release(self.listing(commit="d" * 40))
        self.assertEqual(result.outcome, StepOutcome.FAILED)
        self.assertIn("listing-commit-mismatch", self.codes(result))
        result = self.release(self.listing(status="incomplete"))
        self.assertIn("listing-incomplete", self.codes(result))
        result = self.release(self.listing(with_report=False))
        self.assertEqual(result.outcome, StepOutcome.BLOCKED)
        self.assertIn("listing-not-validated", self.codes(result))
        result = self.release(self.listing(verdict="FAIL"))
        self.assertIn("listing-not-passed", self.codes(result))
        # A report of another listing (hash) is stale.
        extra = self.listing()
        extra["listing-validation-report"]["listing"]["content_hash"] = "sha256:" + "1" * 64
        extra["listing-validation-report"]["provenance"]["content_hash"] = content_hash(extra["listing-validation-report"])
        result = self.release(extra)
        self.assertIn("listing-not-validated", self.codes(result))


class Registration(unittest.TestCase):
    def test_the_module_registers_both_types(self):
        registry = register(StepRegistry())
        self.assertIs(registry.resolve("store-listing"), StoreListingStep)
        self.assertIs(registry.resolve("listing-validation"), ListingValidationStep)


class Server(unittest.TestCase):
    def test_the_bundle_server_serves_the_bundle_and_the_scratch_directory_only(self):
        import urllib.request
        base = tempfile.mkdtemp(prefix="wgf-server-")
        self.addCleanup(shutil.rmtree, base, ignore_errors=True)
        dist, extra = os.path.join(base, "dist"), os.path.join(base, "extra")
        os.makedirs(os.path.join(dist, "assets"))
        os.makedirs(extra)
        with open(os.path.join(dist, "index.html"), "w") as handle:
            handle.write("<!doctype html>hi")
        with open(os.path.join(dist, "assets", "a.js"), "w") as handle:
            handle.write("export const a = 1;")
        with open(os.path.join(extra, "brand.html"), "w") as handle:
            handle.write("<b>brand</b>")
        with open(os.path.join(base, "secret.txt"), "w") as handle:
            handle.write("no")
        with BundleServer(dist, extra) as server:
            def get(path):
                try:
                    with urllib.request.urlopen(server.url + path, timeout=5) as response:
                        return response.status, response.headers.get("Content-Type"), response.read()
                except urllib.error.HTTPError as exc:
                    exc.close()
                    return exc.code, None, b""
            self.assertEqual(get("/")[0], 200)
            status, mime, _ = get("/assets/a.js")
            self.assertEqual((status, mime), (200, "text/javascript; charset=utf-8"))
            self.assertEqual(get("/__wgf-listing__/brand.html")[2], b"<b>brand</b>")
            self.assertEqual(get("/../secret.txt")[0], 404)
            self.assertEqual(get("/__wgf-listing__/../secret.txt")[0], 404)
            self.assertEqual(get("/nope.png")[0], 404)


@unittest.skipUnless(enabled("WGF_LISTING_BROWSER") and os.environ.get("WGF_LISTING_REPO"),
                     "set WGF_LISTING_BROWSER=1 and WGF_LISTING_REPO=<game checkout with dist/ and "
                     "node_modules/> to capture a real build in the game's own Chromium")
class RealBuild(unittest.TestCase):
    """The real capture against a real built game: screenshots of real play, a recording,
    browser-composed branding. Needs a checkout a run built (its dist/ is served) whose
    node_modules hold Playwright and whose Chromium is installed."""

    def test_the_real_capture_yields_play_frames_and_a_recording(self):
        from wgf_listing import capture
        repo = os.environ["WGF_LISTING_REPO"]
        out = tempfile.mkdtemp(prefix="wgf-listing-real-")
        self.addCleanup(shutil.rmtree, out, ignore_errors=True)
        reference = load_file(os.path.join(ROOT, "core", "reference", "store-listing.yaml"))
        with BundleServer(os.path.join(repo, "dist")) as server:
            job = {"base_url": server.url, "out": out,
                   "viewports": [{"id": "landscape", "width": 1280, "height": 720, "mobile": False}],
                   "scenes": reference["capture"]["scenes"],
                   "settings": {"play_ms": 12000, "excluded_states": reference["capture"]["excluded_states"]},
                   "trailer": {"enabled": True, "seconds": 8, "width": 640, "height": 360},
                   "branding": None, "derive": []}
            report = capture.run_capture(job, checkout=repo, timeout=600)
        shots = [s for v in report["viewports"] for s in v["shots"]]
        self.assertTrue(any(s["state"] == "playing" for s in shots), report)
        chosen, _ = pkg.select_screenshots([{**s, "viewport": "landscape"} for s in shots], reference)
        self.assertGreaterEqual(len(chosen), 2)
        self.assertTrue(report["trailer"] and report["trailer"]["file"], report["trailer"])
        info = media.describe(report["trailer"]["file"])
        self.assertEqual(info["format"], "webm")
        self.assertGreater(info["duration_s"] or 0, 3)


if __name__ == "__main__":
    unittest.main()

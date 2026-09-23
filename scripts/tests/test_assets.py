"""The ASSETS module: game design in, asset manifest and files out.

Fixtures are in fixtures/assets/: two designs (2D and 3D), a small asset library with
licensed, unlicensed and restricted entries, a game repository checkout holding files a
design already chose (some valid, some broken), and a fake 2D asset MCP server.

Deterministic and offline: the only process started is the fake MCP server, run with this
interpreter. The ajv check on emitted artifacts runs when WGF_AJV=1 (it needs npx).

    python -m unittest discover scripts/tests
"""

import copy
import datetime
import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
sys.path.insert(0, SCRIPTS)

from wgf_assets import encoders, formats  # noqa: E402
from wgf_assets.mcp import McpClient, McpError, McpPlaceholderBackend  # noqa: E402
from wgf_assets.optimize import optimize  # noqa: E402
from wgf_assets.placeholders import build_backends  # noqa: E402
from wgf_assets.policy import load_policy  # noqa: E402
from wgf_assets.requirements import RequirementError, inspect  # noqa: E402
from wgf_assets.step import AssetsStep  # noqa: E402
from wgflib.hashing import content_hash  # noqa: E402
from wgflib.workflow.api import RunRequest, WorkflowAPI  # noqa: E402
from wgflib.workflow.config import FactoryConfig  # noqa: E402
from wgflib.workflow.contracts import ArtifactContracts  # noqa: E402
from wgflib.workflow.model import RunStatus, StepStatus  # noqa: E402
from wgflib.workflow.step import StepInputs  # noqa: E402

FIXTURES = os.path.join(HERE, "fixtures", "assets")
LIBRARY = os.path.join(FIXTURES, "library")
REPO = os.path.join(FIXTURES, "repo")
FAKE_MCP = os.path.join(FIXTURES, "fake_mcp_server.py")
EPOCH = "2026-09-01T00:00:00Z"


def fixture(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as handle:
        return json.load(handle)


def with_provenance(body, artifact_type, slug, epoch=EPOCH):
    artifact = {"provenance": {
        "artifact_id": f"wgf:{artifact_type}:{slug}:{epoch[:10].replace('-', '')}-01",
        "artifact_type": artifact_type,
        "schema_version": "1.0.0",
        "title_id": slug,
        "produced_by": {"role": "game-designer", "actor": "automation"},
        "produced_at": epoch,
        "inputs": [],
        "content_hash": "",
        "status": "draft",
    }}
    artifact.update(copy.deepcopy(body))
    artifact["provenance"]["content_hash"] = content_hash(artifact)
    return artifact


class FakeRef:
    def __init__(self, content, schema_version="1.0.0"):
        self.schema_version = schema_version
        self.content_hash = content["provenance"]["content_hash"]


class Log:
    def __init__(self):
        self.records = []

    def _log(self, level):
        return lambda message, **fields: self.records.append((level, message, fields))

    def __getattr__(self, level):
        return self._log(level)


class FakeContext:
    def __init__(self, params=None, config=None, execution=1):
        self.params = dict(params or {})
        self.config = dict(config or {})
        self.project_id = "fixture"
        self.execution = execution
        self.logger = Log()


class Definition:
    id = "assets"
    params = {}


def inputs_for(design=None, scaffold=None, schema_version="1.0.0"):
    contents, refs = {}, {}
    for kind, body in (("game-design", design), ("scaffold-record", scaffold)):
        if body is not None:
            contents[kind] = body
            refs[kind] = FakeRef(body, schema_version)
    missing = [k for k in ("game-design", "scaffold-record") if k not in contents]
    return StepInputs(refs, lambda ref: next(c for k, c in contents.items()
                                             if refs[k] is ref), missing)


class AssetsCase(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.mkdtemp(prefix="wgf-assets-")
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)
        self.root = os.path.join(self.scratch, "repo")
        shutil.copytree(REPO, self.root)
        self.policy = load_policy()
        original = AssetsStep.__dict__["clock"]
        AssetsStep.clock = staticmethod(
            lambda: datetime.datetime(2026, 9, 1, tzinfo=datetime.timezone.utc))
        self.addCleanup(setattr, AssetsStep, "clock", original)

    def design(self, name="design-2d.json", requirements=None, **changes):
        body = fixture(name)
        if requirements is not None:
            body["asset_requirements"] = requirements
        body.update(changes)
        return with_provenance(body, "game-design", body["title_id"])

    def run_step(self, design, *, scaffold=None, schema_version="1.0.0", **params):
        params.setdefault("root", self.root)
        params.setdefault("placeholders", {"backends": ["procedural"]})
        context = FakeContext(params)
        result = AssetsStep(Definition()).execute(
            inputs_for(design, scaffold, schema_version), context)
        return result, context

    def manifest(self, design, **params):
        result, _ = self.run_step(design, **params)
        self.assertEqual(result.outcome, "SUCCESS", result.error)
        return result.artifacts[0].content

    @staticmethod
    def items(manifest):
        return {item["id"]: item for item in manifest["items"]}

    @staticmethod
    def codes(manifest, item_id=None):
        return [(i["code"], i["severity"]) for i in manifest["issues"]
                if item_id is None or i.get("item_id") == item_id]

    def read(self, relative):
        with open(os.path.join(self.root, relative), "rb") as handle:
            return handle.read()


# -- inspect and classify ---------------------------------------------------------------

class Requirements(AssetsCase):
    def test_explicit_requirements_are_classified(self):
        reqs, dimension = inspect(self.design(), self.policy)
        self.assertEqual(dimension, "2d")
        by_id = {r.id: r for r in reqs}
        self.assertEqual(by_id["player-run"].manifest_type, "spritesheet")
        self.assertEqual(by_id["tap"].dimension, "2d")  # audio takes the game's dimension
        self.assertEqual(by_id["seasonal-skin"].scope_tier, "future")

    def test_3d_is_inferred_from_the_kinds(self):
        reqs, dimension = inspect(self.design("design-3d.json"), self.policy)
        self.assertEqual(dimension, "3d")
        dims = {r.id: r.dimension for r in reqs}
        self.assertEqual(dims["land"], "3d")  # audio takes the game's dimension
        self.assertEqual(dims["hud"], "2d")  # UI is a 2D overlay whatever the renderer

    def test_a_design_without_requirements_gets_a_derived_baseline(self):
        design = self.design()
        del design["asset_requirements"]
        reqs, _ = inspect(design, self.policy)
        kinds = sorted({r.kind for r in reqs})
        self.assertEqual(kinds, ["background", "font", "icon", "music", "sfx", "ui", "vfx"])
        self.assertTrue(all(r.derived and r.notes.startswith("Derived baseline") for r in reqs))
        # One UI item per screen the design names.
        screens = design["ux"]["screens"]
        self.assertEqual(sum(1 for r in reqs if r.kind == "ui"), len(screens))

    def test_duplicate_ids_are_refused(self):
        with self.assertRaisesRegex(RequirementError, "'coin': duplicate id"):
            inspect(self.design(requirements=[
                {"id": "coin", "kind": "sprite"}, {"id": "coin", "kind": "icon"}]),
                self.policy)

    def test_unknown_kind_bad_id_and_oversize_are_all_reported(self):
        with self.assertRaises(RequirementError) as caught:
            inspect(self.design(requirements=[
                {"id": "a", "kind": "hologram"},
                {"id": "Bad_Id", "kind": "sprite"},
                {"id": "huge", "kind": "background", "width": 9000},
            ]), self.policy)
        message = str(caught.exception)
        self.assertIn("unknown asset kind 'hologram'", message)
        self.assertIn("kebab-case", message)
        self.assertIn("width must be an integer", message)


# -- formats, encoders, licences ---------------------------------------------------------

class Formats(AssetsCase):
    def test_every_placeholder_encoder_output_is_recognised(self):
        colour = (10, 20, 30)
        cases = {
            "png": encoders.png(16, 8, colour), "wav": encoders.wav(0.05, 440),
            "glb": encoders.glb("x", colour), "json": encoders.material_json("m", colour),
        }
        for fmt, data in cases.items():
            self.assertEqual(formats.sniff(data).format, fmt)
        self.assertEqual(formats.sniff(cases["png"])[1:], (16, 8))
        animated = encoders.glb("x", colour, animated=True)
        document = json.loads(animated[20:20 + int.from_bytes(animated[12:16], "little")])
        self.assertEqual(document["animations"][0]["channels"][0]["target"]["path"],
                         "translation")

    def test_encoders_are_deterministic(self):
        self.assertEqual(encoders.glb("a", (1, 2, 3), shape="environment"),
                         encoders.glb("a", (1, 2, 3), shape="environment"))
        self.assertEqual(encoders.png(33, 17, (1, 2, 3), checker=4),
                         encoders.png(33, 17, (1, 2, 3), checker=4))

    def test_truncated_and_mislabelled_files_are_not_recognised_as_what_they_claim(self):
        self.assertIsNone(formats.sniff(encoders.glb("x", (1, 1, 1))[:40]))
        self.assertIsNone(formats.sniff(encoders.png(4, 4, (1, 1, 1))[:30]))
        self.assertEqual(formats.sniff(self.read("public/assets/backgrounds/sky.png")).format,
                         "jpeg")

    def test_license_classification(self):
        classify = self.policy.classify_license
        self.assertEqual(classify("CC0-1.0").status, "verified")
        self.assertEqual(classify("CC-BY-4.0").constraints, ["attribution"])
        self.assertEqual(classify("CC-BY-NC-4.0").status, "restricted")
        self.assertEqual(classify("LicenseRef-factory-generated").status, "generated")
        self.assertEqual(classify("cc0-1.0").status, "unknown")  # loosely typed is unchecked
        self.assertEqual(classify(None).status, "unknown")

    def test_lossless_optimization(self):
        png = encoders.png(8, 8, (1, 2, 3))
        with_text = png[:33] + self._chunk(b"tEXt", b"Comment\x00made by hand") + png[33:]
        out, applied = optimize(with_text, "png")
        self.assertEqual(out, png)
        self.assertEqual(applied, ["png-strip-metadata"])
        self.assertEqual(optimize(out, "png"), (out, []))  # idempotent
        self.assertEqual(optimize(b'{\n  "a": 1\n}\n', "json"), (b'{"a":1}', ["json-minify"]))

    @staticmethod
    def _chunk(kind, body):
        import struct
        import zlib
        return (struct.pack(">I", len(body)) + kind + body
                + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF))


# -- the pipeline, 2D and 3D -------------------------------------------------------------

class TwoD(AssetsCase):
    def test_every_2d_kind_gets_a_valid_placeholder(self):
        manifest = self.manifest(self.design())
        items = self.items(manifest)
        self.assertEqual(
            {i: items[i]["type"] for i in ("player", "player-run", "night-sky", "hud",
                                           "app-icon", "spark", "title-font", "tap", "theme")},
            {"player": "sprite", "player-run": "spritesheet", "night-sky": "background",
             "hud": "ui", "app-icon": "icon", "spark": "vfx", "title-font": "font",
             "tap": "sfx", "theme": "music"})
        for item in manifest["items"]:
            if item["id"] == "seasonal-skin":
                continue
            self.assertEqual(item["status"], "in-progress", item["id"])
            self.assertTrue(item["placeholder"])
            self.assertFalse(item["production_ready"])
            self.assertEqual(item["license_status"], "generated")
            self.assertEqual(item["origin"], {"kind": "generated", "generator": "procedural"})
            for file in item.get("files", []):
                self.assertTrue(file["path"].startswith("public/assets/"))
                self.assertIn(".placeholder", file["path"])
                data = self.read(file["path"])
                self.assertEqual(formats.sniff(data).format, file["format"])
                self.assertEqual(file["bytes"], len(data))

        self.assertEqual((items["player"]["files"][0]["width"],
                          items["player"]["files"][0]["height"]), (48, 48))
        sheet = items["player-run"]["files"]
        self.assertEqual([f["format"] for f in sheet], ["png", "json"])
        atlas = json.loads(self.read(sheet[1]["path"]))
        self.assertEqual(len(atlas["frames"]), 6)
        self.assertEqual(sheet[0]["width"], 6 * 64)
        self.assertNotIn("files", items["title-font"])
        self.assertIn("sans-serif", items["title-font"]["reference"])
        self.assertEqual(items["tap"]["files"][0]["format"], "wav")
        self.assertIn("audio-transcode", items["tap"]["optimization"]["deferred"])

        self.assertEqual(manifest["pipeline"]["audio_format"], ["ogg", "m4a"])
        self.assertIn("2d", manifest["pipeline"])
        self.assertNotIn("3d", manifest["pipeline"])
        self.assertFalse(manifest["complete"])

    def test_future_tier_is_recorded_not_produced(self):
        item = self.items(self.manifest(self.design()))["seasonal-skin"]
        self.assertEqual(item["status"], "planned")
        self.assertNotIn("files", item)
        self.assertNotIn("production_ready", item)

    def test_cost_and_hours_follow_the_policy(self):
        manifest = self.manifest(self.design())
        items = self.items(manifest)
        self.assertEqual(items["theme"]["source"], "purchased")
        self.assertEqual(items["theme"]["est_cost"], 40)
        self.assertEqual(manifest["total_est_cost"],
                         sum(i["est_cost"] for i in manifest["items"]))
        self.assertEqual(manifest["budget"], 400)

    def test_over_budget_is_a_warning(self):
        design = self.design(requirements=[
            {"id": f"hero-{n}", "kind": "spritesheet", "source": "commissioned"}
            for n in range(3)])
        manifest = self.manifest(design)
        self.assertIn(("over-budget", "warning"), self.codes(manifest))


class ThreeD(AssetsCase):
    def test_every_3d_kind_gets_a_valid_placeholder(self):
        manifest = self.manifest(self.design("design-3d.json"))
        items = self.items(manifest)
        expected = {"runner": ("model", "glb"), "crate": ("model", "glb"),
                    "ground": ("texture", "png"), "paint": ("material", "json"),
                    "runner-jump": ("animation", "glb"), "canyon": ("environment", "glb")}
        for item_id, (kind, fmt) in expected.items():
            item = items[item_id]
            self.assertEqual((item["type"], item["dimension"]), (kind, "3d"))
            self.assertEqual(item["files"][0]["format"], fmt)
            self.assertEqual(formats.sniff(self.read(item["files"][0]["path"])).format, fmt)

        ground = items["ground"]["files"][0]
        self.assertTrue(formats.is_power_of_two(ground["width"]))
        material = json.loads(self.read(items["paint"]["files"][0]["path"]))
        self.assertIn("baseColorFactor", material["pbrMetallicRoughness"])
        glb = self.read(items["canyon"]["files"][0]["path"])
        document = json.loads(glb[20:20 + int.from_bytes(glb[12:16], "little")])
        self.assertEqual(len(document["meshes"]), 2)  # ground plane and a prop
        self.assertIn("mesh-compression", items["runner"]["optimization"]["deferred"])

        pipeline = manifest["pipeline"]
        self.assertEqual(pipeline["mesh_compression"], ["draco", "meshopt"])
        self.assertEqual(pipeline["texture_compression"], ["ktx2-etc1s", "ktx2-uastc"])
        self.assertIn("3d", pipeline)

    def test_existing_3d_model_is_accepted_and_a_truncated_one_is_not(self):
        design = self.design("design-3d.json", requirements=[
            {"id": "barrel", "kind": "model", "existing": {
                "path": "public/assets/models/barrel.glb", "license": "CC0-1.0",
                "source_url": "https://example.invalid/barrel"}},
            {"id": "crate", "kind": "model", "existing": {
                "path": "public/assets/models/crate.glb", "license": "CC0-1.0",
                "source_url": "https://example.invalid/crate"}},
            {"id": "odd", "kind": "texture", "existing": {
                "path": "public/assets/textures/odd.png", "license": "CC0-1.0",
                "source_url": "https://example.invalid/odd"}},
        ])
        manifest = self.manifest(design)
        items = self.items(manifest)
        self.assertEqual(items["barrel"]["status"], "delivered")
        self.assertTrue(items["barrel"]["production_ready"])
        self.assertIn(("invalid-format", "error"), self.codes(manifest, "crate"))
        self.assertTrue(items["crate"]["placeholder"])  # fell back so work is not blocked
        self.assertIn(("not-power-of-two", "warning"), self.codes(manifest, "odd"))
        self.assertEqual(items["odd"]["status"], "delivered")


# -- library search, provenance, licensing -------------------------------------------------

class Library(AssetsCase):
    def test_first_licensed_candidate_wins_and_the_rest_are_recorded(self):
        manifest = self.manifest(self.design(), libraries=[LIBRARY])
        coin = self.items(manifest)["coin"]
        self.assertEqual(coin["status"], "delivered")
        self.assertEqual(coin["source"], "library")
        self.assertTrue(coin["production_ready"])
        self.assertEqual(coin["license"], "CC0-1.0")
        self.assertEqual(coin["origin"], {"kind": "library", "library_id": "fixture-lib:gold-coin",
                                          "source_url": "https://example.invalid/coin",
                                          "author": "Kind Artist"})
        self.assertEqual(coin["files"][0]["path"], "public/assets/sprites/coin.png")
        rejected = [i["message"] for i in manifest["issues"]
                    if i["code"] == "library-candidate-rejected"]
        self.assertTrue(any("coin-nc" in m and "restricted" in m for m in rejected), rejected)

    def test_an_unlicensed_library_asset_is_never_picked(self):
        manifest = self.manifest(self.design(), libraries=[LIBRARY])
        player = self.items(manifest)["player"]  # matches lantern-gem by tag
        self.assertTrue(player["placeholder"])
        self.assertTrue(any("lantern-gem" in i["message"] and "no license" in i["message"]
                            for i in manifest["issues"]))

    def test_spritesheet_is_copied_with_its_atlas_and_attribution(self):
        manifest = self.manifest(self.design(), libraries=[LIBRARY])
        sheet = self.items(manifest)["player-run"]
        self.assertEqual([f["path"] for f in sheet["files"]],
                         ["public/assets/sprites/player-run.png",
                          "public/assets/sprites/player-run.atlas.json"])
        self.assertEqual(sheet["usage_constraints"], ["attribution"])
        self.assertIn("Sheet Maker", sheet["origin"]["attribution"])
        self.assertTrue(sheet["production_ready"])

    def test_a_missing_library_is_logged_not_fatal(self):
        result, context = self.run_step(self.design(),
                                        libraries=[os.path.join(self.scratch, "nope")])
        self.assertEqual(result.outcome, "SUCCESS")
        self.assertTrue(any(r[1] == "asset library unavailable" for r in context.logger.records))


class Licensing(AssetsCase):
    def existing(self, item_id, path, **origin):
        return {"id": item_id, "kind": "sprite", "existing": {"path": path, **origin}}

    def test_unknown_license_never_becomes_production(self):
        manifest = self.manifest(self.design(requirements=[
            self.existing("boss", "public/assets/sprites/boss.png",
                          source_url="https://example.invalid/boss"),
            self.existing("boss-typo", "public/assets/sprites/boss.png",
                          license="CC0", source_url="https://example.invalid/boss"),
        ]))
        for item_id in ("boss", "boss-typo"):
            item = self.items(manifest)[item_id]
            self.assertEqual(item["license_status"], "unknown")
            self.assertEqual(item["status"], "sourced")  # on disk, usable to prototype
            self.assertFalse(item["production_ready"])
            self.assertIn(("license-unknown", "error"), self.codes(manifest, item_id))

    def test_restricted_license_is_blocked(self):
        manifest = self.manifest(self.design(requirements=[
            self.existing("logo", "public/assets/sprites/logo-nc.png", license="CC-BY-NC-4.0",
                          source_url="https://example.invalid/logo")]))
        item = self.items(manifest)["logo"]
        self.assertEqual((item["license_status"], item["status"]), ("restricted", "sourced"))
        self.assertIn(("license-restricted", "error"), self.codes(manifest, "logo"))

    def test_a_license_without_provenance_is_an_assertion_nobody_can_check(self):
        manifest = self.manifest(self.design(requirements=[
            self.existing("boss", "public/assets/sprites/boss.png", license="CC0-1.0")]))
        self.assertIn(("provenance-missing", "error"), self.codes(manifest, "boss"))
        self.assertFalse(self.items(manifest)["boss"]["production_ready"])

    def test_verified_external_asset_carries_its_provenance(self):
        manifest = self.manifest(self.design(requirements=[
            self.existing("boss", "public/assets/sprites/boss.png", license="CC-BY-4.0",
                          source_url="https://example.invalid/boss", author="A. Artist",
                          attribution="Boss by A. Artist (CC BY 4.0)",
                          usage_constraints=["credit in the pause menu"])]))
        item = self.items(manifest)["boss"]
        self.assertEqual(item["status"], "delivered")
        self.assertTrue(item["production_ready"])
        self.assertEqual(item["origin"]["kind"], "external")
        self.assertEqual(item["usage_constraints"], ["attribution", "credit in the pause menu"])
        self.assertEqual(item["optimization"]["applied"], [])  # someone else's bytes

    def test_attribution_required_but_absent_is_a_warning(self):
        manifest = self.manifest(self.design(requirements=[
            self.existing("boss", "public/assets/sprites/boss.png", license="CC-BY-4.0",
                          source_url="https://example.invalid/boss")]))
        self.assertIn(("provenance-missing", "warning"), self.codes(manifest, "boss"))


# -- missing, invalid, duplicate ----------------------------------------------------------

class Missing(AssetsCase):
    def test_missing_file_falls_back_to_a_placeholder(self):
        manifest = self.manifest(self.design(requirements=[
            {"id": "ghost", "kind": "sprite", "existing": {
                "path": "public/assets/sprites/ghost.png", "license": "CC0-1.0"}}]))
        item = self.items(manifest)["ghost"]
        self.assertIn(("missing", "error"), self.codes(manifest, "ghost"))
        self.assertTrue(item["placeholder"])

    def test_nothing_to_fall_back_on_is_missing(self):
        manifest = self.manifest(
            self.design(requirements=[
                {"id": "ghost", "kind": "sprite", "scope_tier": "prototype"},
                {"id": "later", "kind": "icon", "scope_tier": "production"}]),
            placeholders={"enabled": False})
        items = self.items(manifest)
        self.assertEqual(items["ghost"]["status"], "planned")
        self.assertIn(("missing", "error"), self.codes(manifest, "ghost"))
        self.assertIn(("missing", "warning"), self.codes(manifest, "later"))

    def test_a_path_outside_the_repository_is_refused(self):
        manifest = self.manifest(self.design(requirements=[
            {"id": "escape", "kind": "sprite", "existing": {"path": "../../etc/passwd"}}]))
        self.assertIn(("missing", "error"), self.codes(manifest, "escape"))
        self.assertTrue(self.items(manifest)["escape"]["placeholder"])


class InvalidFormats(AssetsCase):
    def check(self, item_id, kind, path, code):
        manifest = self.manifest(self.design(requirements=[
            {"id": item_id, "kind": kind, "existing": {
                "path": path, "license": "CC0-1.0", "source_url": "https://example.invalid"}}]))
        self.assertIn((code, "error"), self.codes(manifest, item_id))
        item = self.items(manifest)[item_id]
        self.assertTrue(item["placeholder"])  # the broken file is never recorded as delivered
        self.assertNotEqual(item["files"][0]["path"], path) if item.get("files") else None
        return manifest

    def test_not_an_image(self):
        self.check("broken", "sprite", "public/assets/sprites/broken.png", "invalid-format")

    def test_content_does_not_match_extension(self):
        manifest = self.check("sky", "background", "public/assets/backgrounds/sky.png",
                              "invalid-format")
        self.assertTrue(any("content is jpeg" in i["message"] for i in manifest["issues"]))

    def test_format_not_allowed_for_kind(self):
        self.check("title", "font", "public/assets/fonts/title.png", "format-not-allowed")


class Duplicates(AssetsCase):
    def test_duplicate_requirement_ids_fail_the_step(self):
        result, _ = self.run_step(self.design(requirements=[
            {"id": "coin", "kind": "sprite"}, {"id": "coin", "kind": "sprite"}]))
        self.assertEqual(result.outcome, "FAILED")
        self.assertFalse(result.retryable)
        self.assertIn("duplicate id", result.error)
        self.assertEqual(result.artifacts, [])

    def test_byte_identical_assets_are_flagged(self):
        origin = {"license": "CC0-1.0", "source_url": "https://example.invalid/twin"}
        manifest = self.manifest(self.design(requirements=[
            {"id": "twin-a", "kind": "sprite", "existing": {
                "path": "public/assets/sprites/twin-a.png", **origin}},
            {"id": "twin-b", "kind": "sprite", "existing": {
                "path": "public/assets/sprites/twin-b.png", **origin}}]))
        self.assertEqual(self.codes(manifest, "twin-a"), [])
        self.assertIn(("duplicate-content", "warning"), self.codes(manifest, "twin-b"))


# -- placeholder backends, and the optional MCP ---------------------------------------------

class McpBackend(AssetsCase):
    def mcp(self, mode, **extra):
        self.log = os.path.join(self.scratch, "mcp.log")
        return {"backends": ["2d-assets-mcp", "procedural"], "2d-assets-mcp": {
            "command": [sys.executable, FAKE_MCP, mode, self.log], "tool": "generate_sprite",
            "timeout_seconds": 10, **extra}}

    def small_design(self):
        return self.design(requirements=[
            {"id": "coin", "kind": "sprite", "width": 20, "height": 12},
            {"id": "tap", "kind": "sfx"},
            {"id": "hero-run", "kind": "spritesheet"}])

    def test_generates_2d_images_when_available_and_leaves_the_rest_to_procedural(self):
        manifest = self.manifest(self.small_design(),
                                 placeholders=self.mcp("ok", license="CC0-1.0"))
        items = self.items(manifest)
        self.assertEqual(items["coin"]["origin"]["generator"], "2d-assets-mcp")
        self.assertEqual((items["coin"]["files"][0]["width"],
                          items["coin"]["files"][0]["height"]), (20, 12))
        self.assertEqual(items["coin"]["license_status"], "verified")
        self.assertEqual(items["tap"]["origin"]["generator"], "procedural")
        self.assertEqual(items["hero-run"]["origin"]["generator"], "procedural")
        self.assertEqual(manifest["generation"]["backends"], [
            {"id": "2d-assets-mcp", "available": True, "used": 1},
            {"id": "procedural", "available": True, "used": 2}])
        with open(self.log, encoding="utf-8") as handle:
            call = json.loads(handle.readline())
        self.assertEqual((call["tool"], call["kind"], call["width"]),
                         ("generate_sprite", "sprite", 20))

    def test_embedded_resource_results_are_read(self):
        manifest = self.manifest(self.small_design(), placeholders=self.mcp("resource"))
        self.assertEqual(self.items(manifest)["coin"]["origin"]["generator"], "2d-assets-mcp")

    def test_without_a_declared_license_its_output_is_unknown_not_production(self):
        manifest = self.manifest(self.small_design(), placeholders=self.mcp("ok"))
        coin = self.items(manifest)["coin"]
        self.assertEqual(coin["license_status"], "unknown")
        self.assertFalse(coin["production_ready"])
        self.assertIn(("license-unknown", "warning"), self.codes(manifest, "coin"))

    def test_unavailable_server_falls_back_to_procedural(self):
        cases = {
            "not configured": {"backends": ["2d-assets-mcp", "procedural"]},
            "not on PATH": {"backends": ["2d-assets-mcp"], "2d-assets-mcp": {
                "command": ["wgf-no-such-mcp-server"], "tool": "t"}},
            "server exited": self.mcp("exit"),
        }
        for why, placeholders in cases.items():
            with self.subTest(why):
                manifest = self.manifest(self.small_design(), placeholders=placeholders)
                self.assertEqual(self.items(manifest)["coin"]["origin"]["generator"],
                                 "procedural")
                backend = manifest["generation"]["backends"][0]
                self.assertEqual((backend["id"], backend["available"]),
                                 ("2d-assets-mcp", False))
                self.assertIn(why.split()[-1], backend["note"])

    def test_a_failing_or_lying_server_falls_back_per_asset(self):
        for mode, needle in (("error", "quota"), ("garbage", "no PNG")):
            with self.subTest(mode):
                manifest = self.manifest(self.small_design(), placeholders=self.mcp(mode))
                coin = self.items(manifest)["coin"]
                self.assertEqual(coin["origin"]["generator"], "procedural")
                failure = [i for i in manifest["issues"] if i["code"] == "generation-failed"]
                self.assertIn(needle, failure[0]["message"])

    def test_client_speaks_the_protocol_through_chatter(self):
        client = McpClient([sys.executable, FAKE_MCP, "ok"], timeout=10).start()
        try:
            result = client.call_tool("generate_sprite", {"width": 2, "height": 2})
            self.assertEqual(result["content"][0]["type"], "image")
            with self.assertRaises(McpError):
                client.request("resources/list", {})
        finally:
            client.close()

    def test_an_unregistered_backend_id_is_recorded(self):
        built = build_backends(["nonesuch"], {})
        self.assertEqual([(b_id, b is None, n) for b_id, b, n in built][0],
                         ("nonesuch", True, "no backend registered under this id"))
        self.assertEqual(built[-1][0], "procedural")

    def test_backend_is_optional_by_construction(self):
        backend = McpPlaceholderBackend({})
        self.assertEqual(backend.probe()[0], False)


# -- step outcomes, idempotency, bundle size -------------------------------------------------

class StepOutcomes(AssetsCase):
    def test_waits_for_a_game_design(self):
        result = AssetsStep(Definition()).execute(inputs_for(None), FakeContext())
        self.assertEqual(result.outcome, "WAITING_FOR_INPUT")

    def test_refuses_a_design_of_a_newer_major_schema(self):
        result, _ = self.run_step(self.design(), schema_version="2.0.0")
        self.assertEqual((result.outcome, result.retryable), ("FAILED", False))

    def test_fail_on_and_strict_fail_with_the_manifest_as_evidence(self):
        design = self.design(requirements=[
            {"id": "boss", "kind": "sprite", "existing": {
                "path": "public/assets/sprites/boss.png", "source_url": "https://x.invalid"}}])
        for params in ({"fail_on": ["license-unknown"]}, {"strict": True}):
            with self.subTest(params):
                result, _ = self.run_step(design, **params)
                self.assertEqual((result.outcome, result.retryable), ("FAILED", False))
                self.assertIn("license-unknown", result.error)
                self.assertEqual(result.artifacts[0].type, "asset-manifest")

    def test_manifest_satisfies_the_artifact_contract(self):
        result, _ = self.run_step(self.design(), libraries=[LIBRARY])
        artifact = result.artifacts[0]
        self.assertEqual(ArtifactContracts()("asset-manifest", artifact.content), [])
        provenance = artifact.content["provenance"]
        self.assertEqual(provenance["artifact_id"], "wgf:asset-manifest:lantern-hop:20260901-01")
        self.assertEqual(provenance["inputs"][0]["artifact_type"], "game-design")
        self.assertEqual(artifact.content["policy"]["id"], "asset-policy")
        self.assertEqual(artifact.metadata["items"], len(artifact.content["items"]))

    def test_re_execution_reuses_every_file(self):
        first, _ = self.run_step(self.design("design-3d.json"), libraries=[LIBRARY])
        created = first.artifacts[0].metadata["writes"]
        second, _ = self.run_step(self.design("design-3d.json"), libraries=[LIBRARY])
        writes = second.artifacts[0].metadata["writes"]
        self.assertGreater(created["created"], 0)
        self.assertEqual((writes["created"], writes["updated"]), (0, 0))
        self.assertEqual(writes["reused"], created["created"])
        self.assertEqual(first.artifacts[0].content, second.artifacts[0].content)

    def test_bundle_size_is_checked_against_the_scaffolded_platforms(self):
        scaffold = with_provenance({
            "title_id": "lantern-hop",
            "repository": {"owner": "o", "name": "lantern-hop"},
            "template": {"repository": "o/web-game-template"},
            "game_config": {"path": "game.config.yaml", "platforms": [
                {"id": "gamevui", "profile": "gamevui@1.0.0", "role": "required"}]},
            "outcome": "created"}, "scaffold-record", "lantern-hop")
        design = self.design(requirements=[
            {"id": "huge", "kind": "music", "existing": {
                "path": "public/assets/audio/huge.wav", "license": "CC0-1.0",
                "source_url": "https://example.invalid/huge"}}])
        os.makedirs(os.path.join(self.root, "public/assets/audio"))
        with open(os.path.join(self.root, "public/assets/audio/huge.wav"), "wb") as handle:
            handle.write(encoders.wav(0.01, 440)[:44] + b"\x80" * (51 * 1024 * 1024))
        manifest = self.manifest(design, scaffold=scaffold)
        self.assertIn(("over-bundle-size", "error"), self.codes(manifest))
        self.assertEqual(manifest["provenance"]["inputs"][1]["artifact_type"], "scaffold-record")


# -- through the real engine ------------------------------------------------------------------

DESIGN_MODULE = '''
import json
from wgflib.hashing import content_hash
from wgflib.workflow import ArtifactOutput, StepResult, WorkflowStep


class FixtureDesignStep(WorkflowStep):
    type = "design"

    def execute(self, inputs, context):
        with open(self.params["fixture"], encoding="utf-8") as handle:
            body = json.load(handle)
        design = {"provenance": {
            "artifact_id": "wgf:game-design:" + body["title_id"] + ":20260901-01",
            "artifact_type": "game-design", "schema_version": "1.0.0",
            "title_id": body["title_id"],
            "produced_by": {"role": "game-designer", "actor": "automation"},
            "produced_at": "2026-09-01T00:00:00Z", "inputs": [], "content_hash": "",
            "status": "draft"}}
        design.update(body)
        design["provenance"]["content_hash"] = content_hash(design)
        return StepResult.success([ArtifactOutput("game-design", design)])


def register(registry):
    registry.register(FixtureDesignStep.type, FixtureDesignStep)
'''

WORKFLOW = """
workflow:
  id: assets-contract
  version: 1
  steps:
    - id: design
      type: design
      with: {{fixture: {fixture}}}
      outputs: [game-design]
    - id: assets
      type: assets
      inputs: [game-design, scaffold-record]
      outputs: [asset-manifest]
      with: {{root: {root}, libraries: [{library}]}}
"""


class EngineContract(AssetsCase):
    def setUp(self):
        super().setUp()
        modules = os.path.join(self.scratch, "modules")
        os.makedirs(modules)
        with open(os.path.join(modules, "wgf_fixture_design.py"), "w") as handle:
            handle.write(DESIGN_MODULE)
        sys.path.insert(0, modules)
        self.addCleanup(sys.path.remove, modules)
        self.addCleanup(sys.modules.pop, "wgf_fixture_design", None)

    def run_workflow(self, fixture_name):
        workflow = os.path.join(self.scratch, "assets-contract.workflow.yaml")
        with open(workflow, "w", encoding="utf-8") as handle:
            handle.write(textwrap.dedent(WORKFLOW.format(
                fixture=os.path.join(FIXTURES, fixture_name), root=self.root, library=LIBRARY)))
        config = FactoryConfig({"steps": {"modules": ["wgf_fixture_design", "wgf_assets"]},
                                "storage": {"fsync": False}})
        api = WorkflowAPI(config=config, store_dir=os.path.join(self.scratch, "store"),
                          workflow=workflow)
        return api, api.run(RunRequest(project_id="fixture"))

    def test_the_module_plugs_into_the_engine(self):
        for fixture_name in ("design-2d.json", "design-3d.json"):
            with self.subTest(fixture_name):
                api, state = self.run_workflow(fixture_name)
                self.assertEqual(state.status, RunStatus.COMPLETED)
                self.assertEqual(state.steps["assets"].status, StepStatus.SUCCESS)
                self.assertEqual(state.steps["assets"].consumed, ["game-design@v1"])
                ref = state.latest_artifact("asset-manifest")
                manifest = api.store.read_artifact(state.run_id, ref)
                self.assertEqual(ref.schema_version, "1.1.0")
                self.assertEqual(manifest["provenance"]["inputs"][0]["content_hash"],
                                 state.latest_artifact("game-design").content_hash)
                self.write_for_ajv(fixture_name, manifest,
                                   api.store.read_artifact(
                                       state.run_id, state.latest_artifact("game-design")))

    def write_for_ajv(self, name, manifest, design):
        if os.environ.get("WGF_AJV") != "1":
            return
        for artifact_type, content in (("asset-manifest", manifest), ("game-design", design)):
            path = os.path.join(self.scratch, f"{artifact_type}-{name}")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(content, handle)
            ajv(artifact_type, path, self)


def ajv(artifact_type, path, case):
    command = ["npx", "--yes", "-p", "ajv-cli@5", "-p", "ajv-formats@2", "ajv", "validate",
               "-s", f"core/artifacts/{artifact_type}.schema.json",
               "-r", "core/artifacts/shared/*.schema.json", "-c", "ajv-formats",
               "--spec=draft2020", "--strict=false", "-d", path]
    done = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
    case.assertEqual(done.returncode, 0, done.stdout + done.stderr)


if __name__ == "__main__":
    unittest.main()

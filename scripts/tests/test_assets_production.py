"""The assets step against a production design: build_spec.assets in, judged art out.

What this covers (docs/assets-module.md, docs/production-architecture.md):

    bridge      the work list is build_spec.assets - role, dimension, description,
                readability, count, spec - and the palette of build_spec.visual_identity;
                the generic baseline only when the design lists no assets, always placeholder
    author      a command author (fixtures/assets/fake_svg_author.py, run through
                wgflib.procs) draws each 2D requirement as SVG; a rejected file is shown its
                problems and asked again, at most twice; re-execution reuses what it drew
    library     library.json maps requirement ids and roles to licensed files
    quality     svg_quality / raster_quality on good, primitive, off-palette, unsafe files
    re-entry    a production-quality-report or visual-qa-report routed to `assets` rebuilds
                only the items it names, and its findings reach the author
    3D          wgf_assets.model_author when present; placeholders when absent

Deterministic and offline: the only processes started are the fixture author, run with this
interpreter.

    python -m unittest scripts/tests/test_assets_production.py
"""

import copy
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

import test_assets as base  # noqa: E402
from wgf_assets import quality, runtime, step as step_mod  # noqa: E402
from wgf_assets.requirements import inspect  # noqa: E402
from wgf_assets.step import AssetsStep, rebuild_list  # noqa: E402
from wgflib.workflow.contracts import ArtifactContracts  # noqa: E402
from wgflib.workflow.step import StepInputs  # noqa: E402

FAKE_AUTHOR = os.path.join(base.FIXTURES, "fake_svg_author.py")
MAPPED = os.path.join(base.FIXTURES, "library-mapped")

PALETTE = [
    {"token": "ground", "hex": "#0B0B12", "role": "Background"},
    {"token": "surface", "hex": "#16162A", "role": "Panels"},
    {"token": "ink", "hex": "#EDEBFF", "role": "Text"},
    {"token": "signal", "hex": "#FF2E88", "role": "The player"},
    {"token": "cool", "hex": "#2EF2FF", "role": "Pickups"},
    {"token": "danger", "hex": "#FFB020", "role": "Warnings"},
]


def spec_asset(id_, type_, role, tier="mvp", count=1, spec=None, **extra):
    entry = {"id": id_, "type": type_, "tier": tier, "role": role, "count": count,
             "description": f"The {id_.replace('-', ' ')}",
             "readability": f"a {role} a first-time player recognises at 60 px",
             "source_preference": "procedural", "est_cost": 0}
    if spec:
        entry["spec"] = spec
    entry.update(extra)
    return entry


ASSETS = [
    spec_asset("hero", "sprite", "player", spec="96x96"),
    spec_asset("tile", "sprite", "target", count=2, spec="readable at 96px"),
    spec_asset("spike", "sprite", "threat", spec="64px"),
    spec_asset("board", "texture", "background", spec="960x540"),
    spec_asset("badge", "icon", "icon", spec="64px"),
    spec_asset("coin", "sprite", "collectible", tier="post-mvp"),
]


def production_design(assets=None, *, palette=PALETTE, engine="pixijs", **identity):
    visual = {"concept": "Neon arcade", "palette": copy.deepcopy(palette),
              "typography": {"display": "Display", "body": "Body"},
              "shape_language": "Hard chevrons", "motion": "Snappy", "avoid": ["pastels"]}
    visual.update(identity)
    body = {"title_id": "neon-test",
            "engine": {"type": engine, "dimension": "3d" if engine == "threejs" else "2d",
                       "rationale": "fixture"},
            "ux": {"screens": ["HUD"]},
            "build_spec": {"assets": copy.deepcopy(ASSETS if assets is None else assets),
                           "visual_identity": visual}}
    return base.with_provenance(body, "game-design", "neon-test")


def inputs_with(design, reports=()):
    contents, refs = {"game-design": design}, {"game-design": base.FakeRef(design, "1.6.0")}
    for kind, report in reports:
        contents[kind] = report
        refs[kind] = base.FakeRef(report)
    return StepInputs(refs, lambda ref: next(c for k, c in contents.items() if refs[k] is ref),
                      [])


def report(kind, **body):
    return base.with_provenance(dict(body), kind, "neon-test")


class ProductionCase(base.AssetsCase):
    def setUp(self):
        super().setUp()
        self.run_dir = os.path.join(self.scratch, "run")

    def author(self, mode, **extra):
        settings = {"kind": "command",
                    "argv": [sys.executable, FAKE_AUTHOR, mode, "{request}", "{output}"],
                    "timeout_seconds": 60, "idle_timeout_seconds": None}
        settings.update(extra)
        return settings

    def run_prod(self, design, reports=(), **params):
        params.setdefault("root", self.root)
        params.setdefault("placeholders", {"backends": ["procedural"]})
        context = base.FakeContext(params)
        context.run_dir = self.run_dir
        result = AssetsStep(base.Definition()).execute(inputs_with(design, reports), context)
        self.assertEqual(result.outcome, "SUCCESS", result.error)
        return result.artifacts[0].content, context

    def calls(self):
        path = os.path.join(self.run_dir, "assets", "1-1", "author", "calls.jsonl")
        if not os.path.exists(path):
            return []
        with open(path, encoding="utf-8") as handle:
            return [json.loads(line) for line in handle]

    def runtime_doc(self):
        return json.loads(self.read("public/assets/assets.json"))


# -- the requirements bridge -----------------------------------------------------------------

class Bridge(ProductionCase):
    def test_build_spec_assets_are_the_work_list(self):
        reqs, dimension = inspect(production_design(), self.policy)
        self.assertEqual(dimension, "2d")
        by_id = {r.id: r for r in reqs}
        self.assertEqual(sorted(by_id), sorted(a["id"] for a in ASSETS))
        hero = by_id["hero"]
        self.assertEqual((hero.kind, hero.role, hero.dimension), ("sprite", "player", "2d"))
        self.assertEqual((hero.width, hero.height), (96, 96))
        self.assertIn("first-time player", hero.readability)
        self.assertEqual(by_id["tile"].variant_ids(), ["tile-1", "tile-2"])
        self.assertEqual(by_id["board"].kind, "background")
        self.assertEqual(by_id["badge"].kind, "icon")
        self.assertEqual(by_id["coin"].scope_tier, "production")
        self.assertFalse(by_id["coin"].generate_now())
        self.assertFalse(any(r.placeholder_only for r in reqs))

    def test_the_dimension_is_inferred_from_type_and_engine(self):
        design = production_design([spec_asset("ship", "model", "player"),
                                    spec_asset("hud", "ui", "ui")], engine="threejs")
        reqs, dimension = inspect(design, self.policy)
        by_id = {r.id: r for r in reqs}
        self.assertEqual(dimension, "3d")
        self.assertEqual((by_id["ship"].kind, by_id["ship"].dimension), ("model", "3d"))
        self.assertEqual((by_id["hud"].kind, by_id["hud"].dimension), ("ui", "2d"))

    def test_asset_requirements_enrich_the_same_id(self):
        design = production_design()
        design["asset_requirements"] = [{"id": "hero", "kind": "sprite", "width": 48,
                                         "height": 48, "tags": ["hero"]},
                                        {"id": "sfx-tap", "kind": "sfx"}]
        reqs, _ = inspect(design, self.policy)
        by_id = {r.id: r for r in reqs}
        self.assertEqual((by_id["hero"].width, by_id["hero"].role), (48, "player"))
        self.assertIn("sfx-tap", by_id)

    def test_without_an_author_every_mvp_item_is_a_flagged_placeholder(self):
        manifest, _ = self.run_prod(production_design())
        items = self.items(manifest)
        for item_id in ("hero", "tile", "spike", "board", "badge"):
            item = items[item_id]
            self.assertTrue(item["placeholder"], item_id)
            self.assertFalse(item["production_ready"], item_id)
            self.assertEqual(item["quality"]["verdict"], "skipped")
            self.assertEqual(item["quality"]["author"], "placeholder")
            self.assertEqual(item["role"], items[item_id]["role"])
        self.assertEqual(items["coin"]["status"], "planned")
        assets = self.runtime_doc()["assets"]
        self.assertTrue(assets["hero"]["placeholder"])
        self.assertEqual(assets["hero"]["role"], "player")
        self.assertEqual(ArtifactContracts()("asset-manifest", manifest), [])

    def test_a_design_with_no_assets_gets_the_baseline_and_it_is_all_placeholder(self):
        design = production_design([])
        design["build_spec"]["assets"] = []
        manifest, _ = self.run_prod(design, author=self.author("good"),
                                    libraries=[MAPPED])
        self.assertTrue(manifest["items"])
        self.assertTrue(all(i.get("placeholder") for i in manifest["items"]
                            if i["status"] != "planned"))
        self.assertEqual(self.calls(), [])


# -- the author ------------------------------------------------------------------------------

class Author(ProductionCase):
    def test_an_author_leaves_no_placeholder_among_the_mvp_assets(self):
        manifest, _ = self.run_prod(production_design(), author=self.author("good"))
        items = self.items(manifest)
        mvp = [i for i in manifest["items"] if i["scope_tier"] == "mvp"]
        self.assertEqual(len(mvp), 5)
        for item in mvp:
            self.assertFalse(item.get("placeholder"), item["id"])
            self.assertEqual(item["source"], "ai-generated")
            self.assertEqual(item["quality"]["verdict"], "pass", item["quality"])
            self.assertEqual(item["quality"]["author"], "author:command")
            self.assertTrue(item["production_ready"], item["id"])
            self.assertEqual(item["files"][0]["format"], "svg")
        self.assertEqual(items["hero"]["files"][0]["path"], "public/assets/sprites/hero.svg")
        self.assertEqual(items["board"]["files"][0]["path"],
                         "public/assets/backgrounds/board.svg")
        self.assertGreaterEqual(items["hero"]["quality"]["parts"], 3)
        # The request carried what the drawing must be.
        first = next(c for c in self.calls() if c["asset"]["id"] == "hero")
        self.assertEqual(first["asset"]["role"], "player")
        self.assertIn("first-time player", first["asset"]["readability"])
        self.assertEqual([p["hex"] for p in first["palette"]], [p["hex"] for p in PALETTE])
        self.assertEqual(first["quality_bars"]["min_shapes"], 3)
        # Two drawings for a count of two, each its own runtime asset.
        self.assertEqual([f["path"] for f in items["tile"]["files"]],
                         ["public/assets/sprites/tile-1.svg", "public/assets/sprites/tile-2.svg"])
        assets = self.runtime_doc()["assets"]
        self.assertEqual(assets["tile"]["variants"], ["tile-1", "tile-2"])
        self.assertEqual(assets["tile-2"]["url"], "sprites/tile-2.svg")
        self.assertEqual(assets["hero"]["format"], "svg")
        self.assertEqual(assets["hero"]["role"], "player")
        self.assertNotIn("placeholder", assets["hero"])
        self.assertEqual([i for i in runtime.validate(self.root)
                          if i["severity"] == "error"], [])
        self.assertEqual(ArtifactContracts()("asset-manifest", manifest), [])

    def test_a_primitive_is_shown_its_problems_and_repaired_on_round_two(self):
        design = production_design([spec_asset("hero", "sprite", "player", spec="96x96")])
        manifest, _ = self.run_prod(design, author=self.author("rect-then-good"))
        hero = self.items(manifest)["hero"]
        self.assertEqual(hero["quality"]["verdict"], "pass")
        self.assertFalse(hero["placeholder"])
        calls = self.calls()
        self.assertEqual(len(calls), 2)
        self.assertNotIn("repair", calls[0])
        self.assertEqual(calls[1]["repair"]["round"], 1)
        self.assertTrue(any("svg.not-primitive" in p for p in calls[1]["repair"]["problems"]))
        self.assertTrue(os.path.isfile(calls[1]["repair"]["previous"]))

    def test_a_file_that_never_passes_falls_back_to_a_placeholder_that_says_why(self):
        design = production_design([spec_asset("hero", "sprite", "player")])
        manifest, _ = self.run_prod(design, author=self.author("rect"))
        hero = self.items(manifest)["hero"]
        self.assertTrue(hero["placeholder"])
        self.assertIn(("author-rejected", "warning"), self.codes(manifest, "hero"))
        self.assertEqual(len(self.calls()), 3)  # the first ask and two repair rounds

    def test_an_unsafe_or_off_palette_file_is_refused(self):
        for mode, check in (("script", "svg.safe"), ("off-palette", "svg.palette")):
            with self.subTest(mode=mode):
                design = production_design([spec_asset("hero", "sprite", "player")])
                manifest, _ = self.run_prod(design, author=self.author(mode, repair_rounds=0))
                self.assertTrue(self.items(manifest)["hero"]["placeholder"])
                message = next(i["message"] for i in manifest["issues"]
                               if i["code"] == "author-rejected")
                self.assertIn(check, message)

    def test_a_failing_host_falls_back_to_a_placeholder(self):
        design = production_design([spec_asset("hero", "sprite", "player")])
        manifest, _ = self.run_prod(design, author=self.author("fail"))
        self.assertTrue(self.items(manifest)["hero"]["placeholder"])
        self.assertIn(("author-rejected", "warning"), self.codes(manifest, "hero"))

    def test_a_misconfigured_author_fails_the_step(self):
        context = base.FakeContext({"root": self.root, "author": {"kind": "command"}})
        result = AssetsStep(base.Definition()).execute(inputs_with(production_design()),
                                                       context)
        self.assertEqual(result.outcome, "FAILED")
        self.assertIn("argv", result.error)
        for author in ({"kind": "painter"}, {"kind": "command", "argv": ["x", "{repo}"]},
                       {"kind": "command", "argv": ["x"], "repair_rounds": 9}):
            context = base.FakeContext({"root": self.root, "author": author})
            result = AssetsStep(base.Definition()).execute(
                inputs_with(production_design()), context)
            self.assertEqual(result.outcome, "FAILED", author)
            self.assertFalse(result.retryable)

    def test_re_execution_reuses_what_the_author_drew(self):
        design = production_design([spec_asset("hero", "sprite", "player")])
        first, _ = self.run_prod(design, author=self.author("good"))
        self.assertEqual(len(self.calls()), 1)
        second, _ = self.run_prod(design, author=self.author("good"))
        self.assertEqual(len(self.calls()), 1)
        self.assertEqual(self.items(first)["hero"]["files"], self.items(second)["hero"]["files"])
        ledger = json.loads(self.read("src/assets/authored.json"))
        self.assertIn("public/assets/sprites/hero.svg", ledger["files"])
        # A changed readability line is a different request: asked again.
        changed = production_design([spec_asset("hero", "sprite", "player",
                                                readability="a hero in a red cape")])
        self.run_prod(changed, author=self.author("good"))
        self.assertEqual(len(self.calls()), 2)


# -- re-entry --------------------------------------------------------------------------------

class ReEntry(ProductionCase):
    def test_only_the_items_a_report_names_are_rebuilt_with_its_findings(self):
        design = production_design()
        self.run_prod(design, author=self.author("good"))
        before = len(self.calls())
        pq = report("production-quality-report", title_id="neon-test", commit="abc",
                    measurement_class="automation-agent", verdict="fail", failed=1,
                    routes=["assets"],
                    checks=[{"id": "assets.present", "status": "FAIL", "required": True,
                             "summary": "tile-2 reads as a blob", "route": "assets",
                             "assets": ["tile-2"]},
                            {"id": "ui.targets", "status": "FAIL", "required": True,
                             "summary": "hero button too small", "route": "develop"}])
        vqa = report("visual-qa-report", title_id="neon-test", commit="abc",
                     measurement_class="automation-agent", verdict="fail", failed=1,
                     routes=["assets", "develop"],
                     findings=[{"id": "f1", "severity": "major", "category": "assets",
                                "summary": "the badge is unreadable on the HUD",
                                "route": "assets"},
                               {"id": "f2", "severity": "minor", "category": "ui",
                                "summary": "the hero overlaps the HUD", "route": "develop"}])
        manifest, context = self.run_prod(design, reports=[
            ("production-quality-report", pq), ("visual-qa-report", vqa)],
            author=self.author("good"))
        again = self.calls()[before:]
        self.assertEqual(sorted({c["asset"]["id"] for c in again}), ["badge", "tile"])
        tile_call = next(c for c in again if c["asset"]["id"] == "tile")
        self.assertIn("assets.present: tile-2 reads as a blob", tile_call["notes"])
        badge_call = next(c for c in again if c["asset"]["id"] == "badge")
        self.assertTrue(any("unreadable" in n for n in badge_call["notes"]))
        self.assertIn("Rebuilt", self.items(manifest)["tile"]["notes"])

    def test_a_report_not_routed_to_assets_names_nothing(self):
        reqs, _ = inspect(production_design(), self.policy)
        pq = {"routes": ["develop"], "checks": [{"id": "x", "status": "FAIL",
                                                 "route": "assets", "assets": ["hero"],
                                                 "summary": "s"}]}
        self.assertEqual(rebuild_list([("production-quality-report", pq)], reqs), {})


# -- the library -----------------------------------------------------------------------------

class MappedLibrary(ProductionCase):
    def test_library_json_supplies_licensed_art_by_id_and_role(self):
        manifest, _ = self.run_prod(production_design(), libraries=[MAPPED])
        items = self.items(manifest)
        hero = items["hero"]
        self.assertEqual(hero["source"], "library")
        self.assertFalse(hero["placeholder"])
        self.assertEqual(hero["license"], "CC0-1.0")
        self.assertEqual(hero["origin"]["library_id"], "fixture-mapped:hero")
        self.assertEqual(hero["origin"]["source_url"], "https://example.invalid/hero")
        self.assertEqual(hero["quality"]["verdict"], "pass")
        self.assertEqual(hero["quality"]["author"], "library:fixture-mapped:hero")
        self.assertTrue(hero["production_ready"])
        tile = items["tile"]
        self.assertEqual(tile["license"], "CC-BY-4.0")
        self.assertEqual(tile["origin"]["evidence"], "fixture pack 1, receipt 42")
        self.assertEqual(len(tile["files"]), 2)
        # By role: the PNG board, judged as a raster.
        board = items["board"]
        self.assertEqual(board["origin"]["library_id"], "fixture-mapped:role-background-4")
        self.assertEqual(board["files"][0]["format"], "png")
        self.assertEqual(board["quality"]["verdict"], "pass")
        self.assertTrue(any(c["id"] == "raster.not-flat" for c in board["quality"]["checks"]))
        # A one-rect library file is imported, judged, and not production-ready.
        spike = items["spike"]
        self.assertEqual(spike["quality"]["verdict"], "fail")
        self.assertTrue(spike["quality"]["primitive_only"])
        self.assertFalse(spike["production_ready"])
        self.assertIn(("quality-failed", "error"), self.codes(manifest, "spike"))
        self.assertEqual(ArtifactContracts()("asset-manifest", manifest), [])

    def test_an_unlicensed_mapping_is_passed_over(self):
        design = production_design([spec_asset("coin", "sprite", "collectible")])
        manifest, _ = self.run_prod(design, libraries=[MAPPED])
        coin = self.items(manifest)["coin"]
        self.assertTrue(coin["placeholder"])
        self.assertIn(("library-candidate-rejected", "info"), self.codes(manifest, "coin"))


# -- 3D --------------------------------------------------------------------------------------

class FakeModelAuthor:
    class ModelAuthorError(RuntimeError):
        pass

    def __init__(self, glb):
        self.glb = glb
        self.calls = []

    def produce_model(self, requirement, visual_identity, out_dir, settings, context):
        self.calls.append(requirement["id"])
        path = os.path.join(out_dir, f"{requirement['id']}.glb")
        with open(path, "wb") as handle:
            handle.write(self.glb)
        return {"files": [path], "source": "ai-generated", "license": None,
                "placeholder": False, "notes": "fake model author",
                "quality": {"verdict": "pass", "checks": [
                    {"id": "model.parts", "status": "pass", "summary": "5 parts"}],
                    "primitive_only": False, "parts": 5, "triangles": 12, "colors": 3,
                    "author": "author:fake"}}


class ThreeD(ProductionCase):
    def design(self):
        return production_design([spec_asset("ship", "model", "player")], engine="threejs")

    def test_without_a_model_author_a_3d_requirement_is_a_placeholder(self):
        original = step_mod._model_author
        step_mod._model_author = None
        self.addCleanup(setattr, step_mod, "_model_author", original)
        manifest, _ = self.run_prod(self.design())
        ship = self.items(manifest)["ship"]
        self.assertTrue(ship["placeholder"])
        self.assertEqual(ship["quality"]["verdict"], "skipped")

    def test_a_model_author_is_called_and_its_quality_recorded(self):
        from wgf_assets import encoders
        fake = FakeModelAuthor(encoders.glb("ship", (200, 40, 80)))
        original = step_mod._model_author
        step_mod._model_author = fake
        sys.modules["wgf_assets.model_author"] = fake
        self.addCleanup(setattr, step_mod, "_model_author", original)
        self.addCleanup(sys.modules.pop, "wgf_assets.model_author", None)
        manifest, _ = self.run_prod(self.design(),
                                    model_author={"kind": "command", "argv": ["fake"]})
        ship = self.items(manifest)["ship"]
        self.assertEqual(fake.calls, ["ship"])
        self.assertFalse(ship["placeholder"])
        self.assertEqual(ship["quality"]["author"], "author:fake")
        self.assertEqual(ship["files"][0]["path"], "public/assets/models/ship.glb")
        self.assertEqual(ArtifactContracts()("asset-manifest", manifest), [])


    def test_an_unconfigured_model_author_is_not_asked(self):
        # Installed but not configured: the next backend builds the model, and the run is
        # not told a model author failed.
        from wgf_assets import encoders
        fake = FakeModelAuthor(encoders.glb("ship", (200, 40, 80)))
        original = step_mod._model_author
        step_mod._model_author = fake
        self.addCleanup(setattr, step_mod, "_model_author", original)
        manifest, _ = self.run_prod(self.design())
        self.assertEqual(fake.calls, [])
        self.assertNotIn("generation-failed",
                         [i.get("code") for i in manifest.get("issues") or []])

# -- quality checks --------------------------------------------------------------------------

GOOD = (b'<svg xmlns="http://www.w3.org/2000/svg" width="96" height="96" viewBox="0 0 96 96">'
        b'<defs><linearGradient id="g"><stop offset="0" stop-color="#FF2E88"/>'
        b'<stop offset="1" stop-color="#16162A"/></linearGradient></defs>'
        b'<ellipse cx="48" cy="60" rx="30" ry="24" fill="url(#g)"/>'
        b'<circle cx="48" cy="28" r="16" style="fill:#EDEBFF;stroke:#0B0B12"/>'
        b'<path d="M30 80 L48 92 L66 80 Z" fill="#2EF2FF"/></svg>')


class Quality(unittest.TestCase):
    def setUp(self):
        self.palette = quality.parse_palette(PALETTE)

    def judge(self, data, **kw):
        kw.setdefault("palette", self.palette)
        kw.setdefault("role", "player")
        return quality.svg_quality(data, **kw)

    def statuses(self, judged):
        return {c["id"]: c["status"] for c in judged["checks"]}

    def test_a_good_drawing_passes(self):
        judged = self.judge(GOOD, spec_size=(96, 96))
        self.assertEqual(judged["verdict"], "pass", judged)
        self.assertEqual(judged["parts"], 3)
        self.assertFalse(judged["primitive_only"])
        self.assertEqual(judged["colors"], 5)

    def test_one_rect_is_a_primitive(self):
        judged = self.judge(b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 9 9">'
                            b'<rect width="9" height="9" fill="#FF2E88"/></svg>')
        self.assertEqual(judged["verdict"], "fail")
        self.assertTrue(judged["primitive_only"])
        self.assertEqual(self.statuses(judged)["svg.not-primitive"], "fail")
        # Unless the art direction is geometric.
        allowed = self.judge(b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 9 9">'
                             b'<rect width="9" height="9" fill="#FF2E88"/></svg>',
                             primitive_style=True)
        self.assertEqual(self.statuses(allowed)["svg.not-primitive"], "pass")

    def test_too_few_shapes_for_the_role(self):
        two = (b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 9 9">'
               b'<rect width="9" height="9" fill="#FF2E88"/><circle r="2" fill="#EDEBFF"/>'
               b'</svg>')
        self.assertEqual(self.statuses(self.judge(two))["svg.not-primitive"], "fail")
        self.assertEqual(self.statuses(self.judge(two, role="icon"))["svg.not-primitive"],
                         "pass")

    def test_off_palette_fails_unless_the_file_says_why(self):
        off = GOOD.replace(b"#FF2E88", b"#13A10E").replace(b"#2EF2FF", b"#8B4513")
        judged = self.judge(off)
        self.assertEqual(self.statuses(judged)["svg.palette"], "fail")
        marked = off.replace(b'<svg ', b'<svg data-wgf-off-palette="grass and bark are '
                                       b'natural colours" ', 1)
        self.assertEqual(self.statuses(self.judge(marked))["svg.palette"], "pass")
        # Near a palette colour is on it; greys are outlines.
        near = GOOD.replace(b"#FF2E88", b"#F0308A").replace(b"#2EF2FF", b"#777777")
        self.assertEqual(self.statuses(self.judge(near))["svg.palette"], "pass")

    def test_scripts_handlers_rasters_and_external_references_are_refused(self):
        for hazard in (b"<script>alert(1)</script>",
                       b'<circle r="3" onclick="x()" fill="#FF2E88"/>',
                       b'<image href="data:image/png;base64,AAAA" width="4" height="4"/>',
                       b'<use href="other.svg#a"/>',
                       b'<foreignObject><div/></foreignObject>'):
            with self.subTest(hazard=hazard):
                judged = self.judge(GOOD.replace(b"</svg>", hazard + b"</svg>"))
                self.assertEqual(self.statuses(judged)["svg.safe"], "fail")

    def test_doctype_malformed_and_missing_viewbox(self):
        doctype = b'<?xml version="1.0"?><!DOCTYPE svg [<!ENTITY a "x">]>' + GOOD
        self.assertEqual(self.judge(doctype)["verdict"], "fail")
        self.assertEqual(self.judge(b"<svg><rect")["verdict"], "fail")
        no_box = GOOD.replace(b' viewBox="0 0 96 96"', b"")
        self.assertEqual(self.statuses(self.judge(no_box))["svg.well-formed"], "fail")
        huge = b"<svg>" + b" " * 300000 + b"</svg>"
        self.assertEqual(self.judge(huge)["verdict"], "fail")

    def test_dimensions_follow_the_spec(self):
        self.assertEqual(self.statuses(self.judge(GOOD, spec_size=(960, 540)))[
            "svg.dimensions"], "fail")
        self.assertEqual(self.statuses(self.judge(GOOD, spec_size=(64, 64)))[
            "svg.dimensions"], "pass")

    def test_raster_checks(self):
        from wgf_assets import encoders, raster
        good = encoders.png(32, 32, (200, 40, 80), checker=8)
        self.assertEqual(quality.raster_quality(good, needs_alpha=True)["verdict"], "pass")
        flat = raster.encode_png(raster.Image(8, 8, bytes([10, 20, 30, 255]) * 64))
        judged = quality.raster_quality(flat)
        self.assertEqual(judged["verdict"], "fail")
        self.assertTrue(judged["primitive_only"])
        rgb = (b"\x89PNG\r\n\x1a\n" + raster._chunk(b"IHDR", bytes.fromhex(
            "0000000400000004" "0802000000")))
        self.assertEqual(quality.raster_quality(rgb, needs_alpha=True)["verdict"], "fail")


if __name__ == "__main__":
    unittest.main()

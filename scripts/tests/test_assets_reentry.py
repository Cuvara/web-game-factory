"""Assets re-entry scope, and distinct climax art (WS-10, docs/quality-gap-audit-2026-10.md).

    re-entry    a gate that sends one 3D model back gets that model remade and no other: the
                models it did not refuse keep their bytes and so their node names, which a
                game that composes parts by name looks up (fixtures/assets/compose-by-node-
                name). The audit's case (I-21, LEAD 22): a re-entered assets step re-asked
                the model author for every model, Blender gave the parts new node names,
                and the 3D game's part lookups broke. The remade model is handed the node
                names the game ships now; one that drops them is a warning.
    climax      core/reference/quality-benchmark.yaml presentation.assets.distinct_climax_art:
                climax units name their art (game-design build_spec.content.units[].art), no
                two share a drawing, and no climax drawing is a recolour of another's. The
                audit's case: the 2D release's four bosses were one drawing, tinted per
                world.

Deterministic and offline: the fake 2D author runs with this interpreter; the model author is
an in-process fake.

    python -m unittest scripts/tests/test_assets_reentry.py
"""

import json
import os
import struct
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

import test_assets as base  # noqa: E402
import test_assets_production as prod  # noqa: E402
from wgf_assets import climax, encoders, gltf, step as step_mod  # noqa: E402
from wgf_assets.pipeline import LEDGER_PATH  # noqa: E402
from wgflib.workflow.contracts import ArtifactContracts  # noqa: E402

COMPOSITION = os.path.join(base.FIXTURES, "compose-by-node-name", "composition.json")
MODEL_AUTHOR = {"kind": "command", "argv": ["fake"]}


def composition():
    with open(COMPOSITION, encoding="utf-8") as handle:
        return json.load(handle)["models"]


def glb_with_nodes(names, colour):
    """A GLB whose scene is one node per name, each drawing the same box."""
    document, binary = gltf.load(encoders.glb("part", colour))
    document["nodes"] = [{"name": name, "mesh": 0, "translation": [float(i), 0.0, 0.0]}
                         for i, name in enumerate(names)]
    document["scenes"] = [{"name": "model", "nodes": list(range(len(names)))}]
    text = json.dumps(document, separators=(",", ":"), sort_keys=True).encode("utf-8")
    text += b" " * (-len(text) % 4)
    binary = bytes(binary)
    total = 12 + 8 + len(text) + 8 + len(binary)
    return (b"glTF" + struct.pack("<II", 2, total) + struct.pack("<I", len(text)) + b"JSON"
            + text + struct.pack("<I", len(binary)) + b"BIN\x00" + binary)


class ComposingModelAuthor:
    """A model author as an agent behaves: its first build of a model names the parts as the
    game composes them; asked again it writes a new spec, and the parts get new names -
    unless it is handed the shipped model's names and keeps them (`keeps`)."""

    class ModelAuthorError(RuntimeError):
        pass

    def __init__(self, names, keeps=True):
        self.names = names
        self.keeps = keeps
        self.calls, self.sets, self.requirements = [], [], []
        self.asked = {}

    def produce_model(self, requirement, visual_identity, out_dir, settings, context):
        self.calls.append(requirement["id"])
        self.requirements.append(requirement)
        return self._made(requirement, out_dir)

    def produce_models(self, requirements, visual_identity, out_dir, settings, context):
        self.sets.append([r["id"] for r in requirements])
        self.requirements.extend(requirements)
        return {"results": {r["id"]: self._made(r, out_dir) for r in requirements},
                "errors": {}, "set_render": None, "rounds": 1}

    def _made(self, requirement, out_dir):
        asset_id = requirement["id"]
        visit = self.asked[asset_id] = self.asked.get(asset_id, 0) + 1
        current = requirement.get("current") or {}
        if visit == 1:
            names = self.names[asset_id]
        elif self.keeps and current.get("nodes"):
            names = current["nodes"]
        else:
            names = [f"{asset_id}-part-{i}" for i in range(len(self.names[asset_id]))]
        path = os.path.join(out_dir, f"{asset_id}.glb")
        with open(path, "wb") as handle:
            handle.write(glb_with_nodes(names, (40 * visit % 256, 120, 200)))
        return {"files": [path], "source": "ai-generated", "license": None,
                "placeholder": False, "notes": f"fake model author, visit {visit}",
                "spec": {"id": asset_id, "parts": [{"id": n} for n in names]},
                "quality": {"verdict": "pass", "checks": [
                    {"id": "model.parts", "status": "pass", "summary": "parts"}],
                    "primitive_only": False, "parts": len(names), "triangles": 12,
                    "colors": 3, "author": "author:fake"}}


def refused(*asset_ids):
    """A production-quality report that sends `asset_ids` back to the assets step."""
    return ("production-quality-report", prod.report(
        "production-quality-report", title_id="neon-test", commit="abc",
        measurement_class="automation-agent", verdict="fail", failed=1, routes=["assets"],
        checks=[{"id": "assets.present", "status": "FAIL", "required": True,
                 "summary": f"{asset_ids[0]} reads as a box from the chase camera",
                 "route": "assets", "assets": list(asset_ids)}]))


class ModelReentry(prod.ProductionCase):
    def setUp(self):
        super().setUp()
        self.names = composition()

    def install(self, fake):
        original = step_mod._model_author
        step_mod._model_author = fake
        self.addCleanup(setattr, step_mod, "_model_author", original)

    def design(self, **changes):
        assets = [prod.spec_asset("kart", "model", "player"),
                  prod.spec_asset("rival", "model", "threat"),
                  prod.spec_asset("cone", "model", "hazard")]
        for entry in assets:
            entry.update(changes.get(entry["id"], {}))
        return prod.production_design(assets, engine="threejs")

    def model(self, asset_id):
        path = os.path.join(self.root, "public", "assets", "models", f"{asset_id}.glb")
        with open(path, "rb") as handle:
            return handle.read()

    def assert_composes(self, asset_id):
        """Every node the game looks up by name in `asset_id` is there."""
        found = set(gltf.node_names(self.model(asset_id)))
        missing = [n for n in self.names[asset_id] if n not in found]
        self.assertEqual(missing, [], f"the game cannot find {missing} in {asset_id}")

    def test_only_the_refused_model_is_remade_and_the_rest_keep_their_bytes(self):
        fake = ComposingModelAuthor(self.names)
        self.install(fake)
        design = self.design()
        self.run_prod(design, model_author=MODEL_AUTHOR)
        self.assertEqual(fake.calls, ["kart", "rival", "cone"])
        before = {i: self.model(i) for i in self.names}
        for asset_id in self.names:
            self.assert_composes(asset_id)

        manifest, _ = self.run_prod(design, reports=[refused("rival")],
                                    model_author=MODEL_AUTHOR)
        # Only the model the gate refused went back to the author.
        self.assertEqual(fake.calls, ["kart", "rival", "cone", "rival"])
        for asset_id in ("kart", "cone"):
            self.assertEqual(self.model(asset_id), before[asset_id], asset_id)
        self.assertNotEqual(self.model("rival"), before["rival"])
        for asset_id in self.names:
            self.assert_composes(asset_id)
        items = self.items(manifest)
        self.assertIn("Reused", items["kart"]["notes"])
        self.assertIn("Rebuilt for 1 finding(s)", items["rival"]["notes"])
        self.assertTrue(items["kart"]["production_ready"])
        self.assertEqual(items["kart"]["quality"]["author"], "author:fake")
        # The remade model's author is told what the game ships now.
        current = fake.requirements[-1]["current"]
        self.assertEqual(current["nodes"], self.names["rival"])
        self.assertEqual([p["id"] for p in current["spec"]["parts"]], self.names["rival"])
        self.assertTrue(os.path.isfile(current["path"]))
        self.assertNotIn("model-nodes-renamed", [c for c, _ in self.codes(manifest)])
        self.assertEqual(ArtifactContracts()("asset-manifest", manifest), [])

    def test_the_audit_case_a_renaming_author_breaks_only_the_refused_model(self):
        # I-21: the re-entered step asked again for every model and every model came back
        # with new node names. Now only the refused one can, and the manifest says so.
        fake = ComposingModelAuthor(self.names, keeps=False)
        self.install(fake)
        design = self.design()
        self.run_prod(design, model_author=MODEL_AUTHOR)
        manifest, _ = self.run_prod(design, reports=[refused("rival")],
                                    model_author=MODEL_AUTHOR)
        self.assert_composes("kart")
        self.assert_composes("cone")
        self.assertIn(("model-nodes-renamed", "warning"), self.codes(manifest, "rival"))
        message = next(i["message"] for i in manifest["issues"]
                       if i["code"] == "model-nodes-renamed")
        self.assertIn("wheel-front-left", message)
        self.assertEqual(self.codes(manifest, "kart"), [])
        self.assertEqual(ArtifactContracts()("asset-manifest", manifest), [])

    def test_set_mode_hands_the_set_author_only_the_refused_model(self):
        fake = ComposingModelAuthor(self.names)
        self.install(fake)
        design = self.design()
        settings = dict(MODEL_AUTHOR, mode="set")
        self.run_prod(design, model_author=settings)
        before = self.model("kart")
        self.run_prod(design, reports=[refused("rival")], model_author=settings)
        self.assertEqual(fake.sets, [["kart", "rival", "cone"], ["rival"]])
        self.assertEqual(self.model("kart"), before)
        for asset_id in self.names:
            self.assert_composes(asset_id)

    def test_a_re_executed_step_reuses_every_model(self):
        fake = ComposingModelAuthor(self.names)
        self.install(fake)
        design = self.design()
        self.run_prod(design, model_author=MODEL_AUTHOR)
        self.run_prod(design, model_author=MODEL_AUTHOR)
        self.assertEqual(fake.calls, ["kart", "rival", "cone"])
        with open(os.path.join(self.root, *LEDGER_PATH.split("/")), encoding="utf-8") as handle:
            ledger = json.load(handle)["files"]
        self.assertEqual(ledger["public/assets/models/kart.glb"]["nodes"], self.names["kart"])

    def test_a_changed_requirement_is_asked_again(self):
        fake = ComposingModelAuthor(self.names)
        self.install(fake)
        self.run_prod(self.design(), model_author=MODEL_AUTHOR)
        self.run_prod(self.design(cone={"description": "A striped traffic cone, taller"}),
                      model_author=MODEL_AUTHOR)
        self.assertEqual(fake.calls, ["kart", "rival", "cone", "cone"])

    def test_a_model_changed_by_hand_is_not_overwritten_by_the_ledger(self):
        fake = ComposingModelAuthor(self.names)
        self.install(fake)
        design = self.design()
        self.run_prod(design, model_author=MODEL_AUTHOR)
        edited = glb_with_nodes(self.names["kart"] + ["roll-cage"], (9, 9, 9))
        with open(os.path.join(self.root, "public", "assets", "models", "kart.glb"),
                  "wb") as handle:
            handle.write(edited)
        # The file no longer has the bytes the ledger recorded: it is not "what the author
        # made", so it is not reused as that - the author is asked.
        self.run_prod(design, model_author=MODEL_AUTHOR)
        self.assertEqual(fake.calls, ["kart", "rival", "cone", "kart"])


# -- distinct climax art --------------------------------------------------------------------

def content(units):
    return {"unit_kind": "level", "generation": {"mode": "authored"}, "units": [
        {"id": f"level-{n}", "index": n, "tier": tier, "purpose": purpose,
         "objective": "Break every brick on the board", "mechanics": ["bounce"],
         "difficulty": {"speed": n}, "expected_duration_s": 60,
         "success": "Every brick is broken", "failure": "The ball is lost three times",
         "acceptance": [f"Level {n} is built as listed in the content file"],
         **({"art": art} if art is not None else {})}
        for n, (purpose, art, tier) in enumerate(units, 1)]}


class ClimaxArt(prod.ProductionCase):
    def design(self, assets, units):
        design = prod.production_design(assets)
        design["build_spec"]["content"] = content(units)
        return design

    def climax_codes(self, manifest):
        return [(i["code"], i["severity"], i.get("item_id")) for i in manifest["issues"]
                if i["code"].startswith("climax-art")]

    BOSSES = [("test", None, "mvp"), ("climax", ["boss"], "mvp"),
              ("test", None, "mvp"), ("climax", ["boss"], "post-mvp"),
              ("climax", ["boss"], "post-mvp"), ("climax", ["boss"], "post-mvp")]

    def test_the_audit_case_four_bosses_one_drawing_is_refused(self):
        assets = [prod.spec_asset("paddle", "sprite", "player", spec="96x96"),
                  prod.spec_asset("boss", "sprite", "threat", spec="96x96")]
        manifest, _ = self.run_prod(self.design(assets, self.BOSSES),
                                    author=self.author("good"))
        found = self.climax_codes(manifest)
        self.assertEqual(found, [("climax-art-shared", "error", "boss")] * 4)
        boss = self.items(manifest)["boss"]
        self.assertFalse(boss["production_ready"])
        self.assertIn("climax-art-shared", boss["issues"])
        self.assertTrue(self.items(manifest)["paddle"]["production_ready"])
        self.assertEqual(ArtifactContracts()("asset-manifest", manifest), [])

    def test_bosses_drawn_as_recolours_of_one_drawing_are_refused(self):
        # Two assets, so the design looks distinct - but the drawings are one shape.
        assets = [prod.spec_asset("boss-forest", "sprite", "threat", spec="96x96"),
                  prod.spec_asset("boss-ice", "sprite", "threat", spec="96x96")]
        units = [("climax", ["boss-forest"], "mvp"), ("climax", ["boss-ice"], "mvp")]
        manifest, _ = self.run_prod(self.design(assets, units), author=self.author("good"))
        (finding,) = [i for i in manifest["issues"] if i["code"] == "climax-art-shared"]
        self.assertEqual(finding["item_id"], "boss-ice")
        self.assertIn("same silhouette", finding["message"])
        self.assertIn("boss-forest", finding["message"])

    def test_a_counted_boss_with_a_distinct_drawing_per_climax_passes(self):
        assets = [prod.spec_asset("boss", "sprite", "threat", count=4, spec="96x96")]
        units = [("climax", [f"boss-{n}"], "mvp") for n in range(1, 5)]
        manifest, _ = self.run_prod(self.design(assets, units), author=self.author("good"))
        self.assertEqual(self.climax_codes(manifest), [])
        self.assertTrue(self.items(manifest)["boss"]["production_ready"])

    def test_a_climax_unit_naming_no_art_cannot_be_checked(self):
        assets = [prod.spec_asset("boss", "sprite", "threat", count=2, spec="96x96")]
        units = [("climax", None, "mvp"), ("climax", ["boss"], "mvp"),
                 ("climax", ["dragon"], "mvp"), ("climax", ["boss-2"], "optional")]
        manifest, _ = self.run_prod(self.design(assets, units), author=self.author("good"))
        found = [i for i in manifest["issues"] if i["code"] == "climax-art-unassigned"]
        self.assertEqual([i["severity"] for i in found], ["warning"] * 3)
        self.assertTrue(all("item_id" not in i for i in found))
        text = " | ".join(i["message"] for i in found)
        self.assertIn("level-1 names no art", text)
        self.assertIn("counted asset - name one of its variant ids", text)
        self.assertIn("dragon, which no asset or variant has", text)
        self.assertNotIn("level-4", text)  # optional: committed to nothing
        self.assertEqual(ArtifactContracts()("asset-manifest", manifest), [])

    def test_the_bar_is_the_benchmarks_and_applies_at_its_tier(self):
        self.assertIs(climax.load_bar("release"), True)
        self.assertIsNone(climax.load_bar("mvp"))
        assets = [prod.spec_asset("boss", "sprite", "threat", spec="96x96")]
        manifest, _ = self.run_prod(self.design(assets, self.BOSSES),
                                    author=self.author("good"), quality_tier="mvp")
        self.assertEqual(self.climax_codes(manifest), [])

    def test_a_design_without_content_units_is_not_checked(self):
        manifest, _ = self.run_prod(prod.production_design(), author=self.author("good"))
        self.assertEqual(self.climax_codes(manifest), [])

    def test_climax_units_in_order_shipped_tiers_only(self):
        design = {"build_spec": {"content": content([
            ("climax", ["b"], "post-mvp"), ("test", None, "mvp"), ("climax", ["a"], "mvp"),
            ("climax", ["c"], "optional")])}}
        self.assertEqual(climax.climax_units(design), [
            {"unit": "level-1", "index": 1, "art": ["b"]},
            {"unit": "level-3", "index": 3, "art": ["a"]}])


if __name__ == "__main__":
    unittest.main()

"""The production art and UI a design states (game-design 1.6.0; scripts/wgf_design/presentation.py).

A design that says nothing about how its player, threats and goals look gets a game drawn as a
cube and two spheres under browser-default buttons. The design step requires every MVP asset to
say what it is to the player and whether it is 2D or 3D, every entity asset to say what a
first-time player recognises in it, every readable role the design's own mechanics name to
have such an asset, a 3D game's characters to be models, and the UI as palette tokens and
numbers held to core/reference/experience-rules.yaml.

The regression case is the Goalkeeper Royale design a 2.5.0 run produced (fixture): its keeper,
attacker and ball were "low-poly" requirements with no role or readability, and the game built
from it drew them as primitives.

    python -m unittest scripts.tests.test_design_presentation
"""

import copy
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, HERE)

import test_design_module as design_tests  # noqa: E402
from wgf_design import archetypes, identity, presentation  # noqa: E402
from wgflib.workflow.model import StepOutcome  # noqa: E402

FIXTURE = os.path.join(HERE, "fixtures", "design", "goalkeeper-royale")


def load(name):
    with open(os.path.join(FIXTURE, name), encoding="utf-8") as handle:
        return json.load(handle)


def design_of(archetype_id, **params):
    result = design_tests.run_step(design_tests.coherent(archetype_id),
                                   params=dict(params, archetype=archetype_id))
    assert result.outcome == StepOutcome.SUCCESS, result.error
    return result.artifacts[0].content


class EveryArchetypeStatesItsProductionArt(unittest.TestCase):
    def test_each_archetype_in_each_identity_kit(self):
        for archetype_id in archetypes.ARCHETYPES:
            for kit in identity.KITS:
                with self.subTest(archetype=archetype_id, identity=kit):
                    self.assertEqual(presentation.check(design_of(archetype_id, identity=kit)), [])

    def test_every_drawn_asset_has_a_role_dimension_and_readability(self):
        for archetype_id in archetypes.ARCHETYPES:
            with self.subTest(archetype=archetype_id):
                design = design_of(archetype_id)
                roles = set()
                for asset in design["build_spec"]["assets"]:
                    self.assertIn(asset.get("role"), presentation.ENTITY_ROLES + (
                        "environment", "background", "prop", "ui", "vfx", "icon", "font"), asset["id"])
                    self.assertIn(asset.get("dimension"), ("2d", "3d"), asset["id"])
                    if asset["type"] != "font":
                        self.assertGreater(len(asset.get("readability") or ""), 30, asset["id"])
                    roles.add(asset["role"])
                # The player's world, its backdrop and its interface are all stated.
                self.assertTrue(roles & {"environment", "background"}, roles)
                self.assertTrue({"ui", "icon"} <= roles, roles)
                self.assertTrue(roles & set(presentation.readable_roles()), roles)

    def test_the_3d_archetypes_characters_are_models(self):
        for archetype_id in ("arena-dodge", "arena-3d"):
            design = design_of(archetype_id)
            player = next(a for a in design["build_spec"]["assets"] if a["role"] == "player")
            self.assertEqual((player["type"], player["dimension"]), ("model", "3d"))
            self.assertNotIn("Primitive geometry", player.get("spec") or "")

    def test_a_pinned_engine_of_the_other_dimension_redraws_the_characters(self):
        design = design_of("lane-runner", engine="threejs")
        player = next(a for a in design["build_spec"]["assets"] if a["role"] == "player")
        self.assertEqual((player["type"], player["dimension"]), ("model", "3d"))
        icons = next(a for a in design["build_spec"]["assets"] if a["role"] == "icon")
        self.assertEqual(icons["dimension"], "2d")
        self.assertEqual(presentation.check(design), [])

    def test_the_ui_is_numbers_and_palette_tokens(self):
        for kit in identity.KITS:
            ui = design_of("one-touch", identity=kit)["build_spec"]["visual_identity"]["ui"]
            self.assertGreaterEqual(ui["min_target_px"], 44)
            self.assertTrue(ui["button"]["fill"] and ui["button"]["text"] and ui["surface"])

    def test_no_archetype_claims_a_geometric_look(self):
        """primitive_style is the art direction's to claim, with a reason; no built-in archetype
        has one, so none may draw its characters as primitives in production."""
        for archetype_id in archetypes.ARCHETYPES:
            look = design_of(archetype_id)["build_spec"]["visual_identity"]
            self.assertNotIn("primitive_style", look)


class TheGoalkeeperDesign(unittest.TestCase):
    """The real design: every world asset a bare requirement, and no UI spec."""

    def setUp(self):
        self.design = load("game-design.json")
        self.problems = presentation.check(self.design)
        self.text = "\n".join(self.problems)

    def test_named_problems_before_any_asset_is_made(self):
        for asset in ("keeper", "attacker", "ball", "goal-arena-kit", "ui-kit", "icons"):
            self.assertIn(f"assets.{asset}: state its role and dimension", self.text)
        # What its own mechanics name and nothing draws.
        self.assertIn("mechanic 'goalkeeper-dive' names a player ('keeper')", self.text)
        self.assertIn("mechanic 'ai-shot' names a threat ('attacker')", self.text)
        self.assertIn("names a projectile", self.text)
        self.assertIn("names a goal ('goal line')", self.text)
        self.assertIn("visual_identity.ui is missing", self.text)
        # "shot target" is a count, not a thing on screen.
        self.assertNotIn("names a target", self.text)

    def test_a_billboard_keeper_in_a_3d_game_is_refused(self):
        spec = self.design["build_spec"]
        keeper = next(a for a in spec["assets"] if a["id"] == "keeper")
        keeper.update(type="sprite", role="player", dimension="2d",
                      readability="A keeper in gloves, 60 px tall")
        self.assertIn("assets.keeper: a player in a 3D game is a model with dimension 3d",
                      "\n".join(presentation.check(self.design)))

    def test_the_repaired_design_holds(self):
        spec = self.design["build_spec"]
        stated = {
            "keeper": ("player", "3d", "A keeper in a bright kit and big gloves, readable at 60 px "
                                       "tall from the goal-mouth camera"),
            "attacker": ("threat", "3d", "An attacker whose windup lean shows the shot's side from "
                                         "the keeper's camera"),
            "ball": ("projectile", "3d", "A white ball with a dark panel pattern, visible every "
                                         "frame of its flight against the night pitch"),
            "goal-arena-kit": ("goal", "3d", "A white goal frame and net that mark the three zones "
                                             "the keeper covers"),
            "keeper-animset": ("player", "3d", None), "attacker-animset": ("threat", "3d", None),
            "save-vfx": ("vfx", "3d", None), "concede-vfx": ("vfx", "3d", None),
            "ui-kit": ("ui", "2d", None), "icons": ("icon", "2d", None),
            "fonts": ("font", "2d", None), "wordmark": ("ui", "2d", None),
        }
        for asset in spec["assets"]:
            role, dimension, readability = stated[asset["id"]]
            asset.update(role=role, dimension=dimension)
            if readability:
                asset["readability"] = readability
        spec["visual_identity"]["ui"] = {
            "font_px": {"body": 16, "hud": 20, "heading": 32}, "min_target_px": 48,
            "button": {"fill": "signal", "text": "turf", "radius_px": 28}, "surface": "surface"}
        self.assertEqual(presentation.check(self.design), [])


class EachRule(unittest.TestCase):
    def setUp(self):
        self.design = design_of("lane-runner", identity="neon-night")
        self.spec = self.design["build_spec"]
        self.ui = self.spec["visual_identity"]["ui"]

    def problems(self):
        return "\n".join(presentation.check(self.design))

    def asset(self, asset_id):
        return next(a for a in self.spec["assets"] if a["id"] == asset_id)

    def test_an_entity_with_no_readability(self):
        del self.asset("obstacles")["readability"]
        text = self.problems()
        self.assertIn("assets.obstacles: a threat with no readability line", text)
        self.assertIn("mechanic 'obstacles' names a threat ('obstacle')", text)

    def test_a_role_the_lose_condition_names(self):
        self.spec["assets"] = [a for a in self.spec["assets"] if a["id"] != "obstacles"]
        self.assertIn(("experience.lose", "obstacle"),
                      presentation.implied_roles(self.design)["threat"])
        self.assertIn("names a threat ('obstacle'), but no MVP asset of role 'threat'",
                      self.problems())

    def test_primitive_style_waives_readability_but_not_the_ui(self):
        del self.asset("obstacles")["readability"]
        self.spec["visual_identity"]["primitive_style"] = {
            "reason": "Abstract neon geometry is the art direction: lanes, slabs and light."}
        self.ui["min_target_px"] = 40
        text = self.problems()
        self.assertNotIn("readability", text)
        self.assertIn("visual_identity.ui.min_target_px is 40; the bar is 44 CSS px", text)

    def test_a_ui_token_not_in_the_palette(self):
        self.ui["button"]["fill"] = "hot-pink"
        self.ui["surface"] = "card"
        text = self.problems()
        self.assertIn("visual_identity.ui.button.fill 'hot-pink' is not a palette token", text)
        self.assertIn("visual_identity.ui.surface 'card' is not a palette token", text)

    def test_button_text_that_does_not_read_on_its_fill(self):
        self.ui["button"]["text"] = "surface"   # #16162A on ground #0B0B12 fill
        self.ui["button"]["fill"] = "ground"
        self.assertIn("visual_identity.ui.button text 'surface' on fill 'ground'", self.problems())

    def test_small_text(self):
        self.ui["font_px"]["hud"] = 11
        self.assertIn("visual_identity.ui.font_px.hud is 11; the bar is 14 px", self.problems())

    def test_a_drawn_asset_with_no_role(self):
        del self.asset("track")["role"]
        self.assertIn("assets.track: state its role", self.problems())

    def test_the_bars_are_data(self):
        rules = copy.deepcopy(presentation.load_rules())
        rules["ui"]["min_target_px"] = 56
        self.assertTrue(any("the bar is 56" in p for p in presentation.check(self.design, rules)))


class TheStepFailsADesignThatOmitsIt(unittest.TestCase):
    def test_the_built_in_author_is_failed_by_name(self):
        saved = copy.deepcopy(archetypes.ARCHETYPES["lane-runner"]["assets"])
        for asset in archetypes.ARCHETYPES["lane-runner"]["assets"]:
            asset.pop("readability", None)
        try:
            result = design_tests.run_step(design_tests.coherent("lane-runner"),
                                           params={"archetype": "lane-runner"})
        finally:
            archetypes.ARCHETYPES["lane-runner"]["assets"] = saved
        self.assertEqual((result.outcome, result.retryable), (StepOutcome.FAILED, False))
        self.assertIn("does not state its production art and UI", result.error)
        self.assertIn("assets.player: a player with no readability line", result.error)


if __name__ == "__main__":
    unittest.main()

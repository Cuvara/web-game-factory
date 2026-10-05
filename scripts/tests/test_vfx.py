"""The visual effect contract and the art style families.

core/reference/vfx.yaml + game-design build_spec.vfx: the design states an effect per
interaction kind (scripts/wgf_design/vfx.py, consistency rule vfx_covers_interactions), the
production gate measures them in play (wgf_production.checks vfx.fires, vfx.screen_share,
vfx.celebration) from what the bot recorded (scripts/wgf_playability/bot.spec.ts), and visual
QA asks of the interaction and win frames (feedback_visible, celebration_visible).
core/reference/art-style-families.yaml: the look's family, its examples and its glow limits
(scripts/wgf_assets/style_families.py; the model author's use of it is test_model_author.py).
"""

import copy
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, HERE)

from wgf_assets import modelspec, style_families  # noqa: E402
from wgf_assets.model_author import _schema_problems  # noqa: E402
from wgf_assets.raster import Image, encode_png  # noqa: E402
from wgf_design import consistency, identity  # noqa: E402
from wgf_design import vfx as vfx_contract  # noqa: E402
from wgf_production import checks as judging  # noqa: E402
from wgf_production.step import load_rules  # noqa: E402
from wgflib import jsonschema_lite  # noqa: E402
from wgflib.yamllite import load_file  # noqa: E402

RULES = load_rules()
VFX = vfx_contract.load()
PROBE_SCHEMA = os.path.join(ROOT, "core", "artifacts", "shared", "play-probe.schema.json")
DESIGN_SCHEMA = os.path.join(ROOT, "core", "artifacts", "game-design.schema.json")


class StyleFamilies(unittest.TestCase):
    def test_every_example_is_a_valid_spec_within_its_familys_limits(self):
        data = style_families.load()
        self.assertEqual(set(data["families"]), {"neon-emissive", "lit-stylized", "toon"})
        for fid, entry in data["families"].items():
            self.assertGreaterEqual(len(entry["examples"]), 2, fid)
            for example in entry["examples"]:
                spec = example["spec"]
                problems = (_schema_problems(spec) + modelspec.validate(spec)
                            + style_families.style_problems(spec, entry))
                self.assertEqual(problems, [], f"{fid}/{example['id']}")
                self.assertTrue(modelspec.buildable(spec))

    def test_every_identity_kit_has_a_family_and_carries_it(self):
        data = style_families.load()
        self.assertEqual(set(data["kits"]), set(identity.KITS))
        for kit_id in identity.KITS:
            family = identity.look(kit_id)["style_family"]
            self.assertIn(family, data["families"])
            # A kit's own words place it in the same family as the table does.
            words = {k: v for k, v in identity.KITS[kit_id].items() if k != "style_family"}
            self.assertEqual(style_families.family(words)[0], family, kit_id)

    def test_the_schema_names_exactly_the_families(self):
        with open(DESIGN_SCHEMA, encoding="utf-8") as handle:
            schema = json.load(handle)
        look = schema["properties"]["build_spec"]["properties"]["visual_identity"]
        self.assertEqual(set(look["properties"]["style_family"]["enum"]),
                         set(style_families.load()["families"]))

    def test_the_family_is_stated_read_from_words_or_the_default(self):
        self.assertEqual(style_families.family({"style_family": "toon"})[::2], ("toon", "stated"))
        self.assertEqual(style_families.family({"concept": "Neon signage at night"})[::2],
                         ("neon-emissive", "words"))
        self.assertEqual(style_families.family({"concept": "A plain look"})[::2],
                         ("lit-stylized", "default"))

    def test_the_example_fits_the_requirement(self):
        lit = style_families.load()["families"]["lit-stylized"]
        self.assertEqual(style_families.example(lit, {"id": "marble", "role": "player"})[0], "ball")
        self.assertEqual(style_families.example(lit, {"id": "finish", "role": "goal"})[:3:2],
                         ("arch", True))
        self.assertEqual(style_families.example(lit, {"id": "tree", "role": "prop"})[:3:2],
                         ("ball", False))

    def test_glow_beyond_the_family_is_a_problem(self):
        lit = style_families.load()["families"]["lit-stylized"]
        spec = {"parts": [{"id": "drum", "shape": "cylinder", "material": "glow"},
                          {"id": "base", "shape": "box", "material": "stone"}],
                "materials": [{"id": "glow", "color": "#F2A900", "emissive": "#F2A900",
                               "emissive_strength": 3},
                              {"id": "stone", "color": "#7FB685"}]}
        problems = style_families.style_problems(spec, lit)
        self.assertTrue(any("emits at 3" in p for p in problems), problems)
        self.assertTrue(any("1 of 2 parts glow" in p for p in problems), problems)
        neon = style_families.load()["families"]["neon-emissive"]
        self.assertEqual(style_families.style_problems(spec, neon), [])


def design(tier="release", vfx=None, roles=("player", "collectible", "threat"),
           mechanics=("steer", "collect"), win=True):
    spec = {"assets": [{"id": f"{r}-art", "role": r, "tier": "mvp"} for r in roles],
            "audio": [{"id": "pickup-sfx"}],
            "mechanics": [{"id": m, "name": m, "tier": "mvp", "description": m} for m in mechanics],
            "experience": {"lose": {"condition": "fall off"}},
            "content": {"quality_tier": tier}}
    if win:
        spec["experience"]["win"] = {"condition": "reach the goal", "metric": "goal"}
    if vfx is not None:
        spec["vfx"] = vfx
    return {"build_spec": spec}


class DesignContract(unittest.TestCase):
    def test_the_kinds_a_design_implies(self):
        self.assertEqual(sorted(vfx_contract.implied(design())),
                         ["fail", "goal", "impact", "pickup", "trail"])
        self.assertEqual(sorted(vfx_contract.implied(design(roles=("player",), mechanics=(),
                                                            win=False))), ["fail"])

    def test_release_requires_an_effect_per_kind_mvp_does_not(self):
        view = vfx_contract.view(design())
        self.assertTrue(view["binds"])
        self.assertEqual(len(view["problems"]), 5, view["problems"])
        self.assertEqual(vfx_contract.view(design(tier="mvp"))["problems"], [])

    def test_the_seed_satisfies_the_contract_and_the_schema(self):
        draft = design()
        draft["build_spec"]["vfx"] = vfx_contract.seed(draft)
        self.assertEqual(vfx_contract.view(draft)["problems"], [])
        with open(DESIGN_SCHEMA, encoding="utf-8") as handle:
            schema = json.load(handle)
        block = schema["properties"]["build_spec"]["properties"]["vfx"]
        errors = list(jsonschema_lite.Validator(dict(block, **{"$defs": schema["$defs"]}))
                      .iter_errors(draft["build_spec"]["vfx"]))
        self.assertEqual(errors, [])

    def test_a_cap_above_the_ceiling_and_a_dangling_asset_are_problems(self):
        draft = design(roles=("player",), mechanics=(), win=False)
        draft["build_spec"]["vfx"] = {"effects": [
            {"id": "splash", "kind": "fail", "effect": "a splash where it fell", "tier": "mvp",
             "duration_ms": 500, "max_screen_share": 0.9, "asset": "nope", "audio": "pickup-sfx"}]}
        problems = vfx_contract.view(draft)["problems"]
        self.assertEqual(len(problems), 2, problems)
        self.assertTrue(any("above the fail ceiling 0.35" in p for p in problems))
        self.assertTrue(any("'nope'" in p for p in problems))

    def test_the_ruleset_pins_the_contract_and_the_rule_reads_it(self):
        rules = consistency.load_rules()
        self.assertEqual(str(rules["vfx"]["version"]), str(VFX["version"]))
        rule = next(r for r in rules["rules"] if r["id"] == "vfx_covers_interactions")
        self.assertEqual(rule["severity"], "blocking")
        context = consistency.projection(
            dict(design(), monetization={"placements": []}), {},
            effects=vfx_contract.view(design()))
        self.assertTrue(consistency._evaluate_once(rule, context)["breached"])
        seeded = design()
        seeded["build_spec"]["vfx"] = vfx_contract.seed(seeded)
        context["vfx"] = vfx_contract.view(seeded)
        self.assertFalse(consistency._evaluate_once(rule, context)["breached"])

    def test_the_built_in_author_states_the_effects(self):
        from test_design_module import load_strategy, run_step
        result = run_step(load_strategy())
        built = result.artifacts[0].content
        kinds = {e["kind"] for e in built["build_spec"]["vfx"]["effects"]}
        self.assertTrue(set(vfx_contract.implied(built)) <= kinds)
        self.assertIn(built["build_spec"]["visual_identity"]["style_family"],
                      style_families.load()["families"])


# -- the production gate --------------------------------------------------------------------

VIEWPORT = [400, 300]
EFFECTS = {"effects": [
    {"id": "gem-burst", "kind": "pickup", "effect": "a ring and the gem flying to the counter",
     "duration_ms": 400, "max_screen_share": 0.08, "tier": "mvp"},
    {"id": "confetti", "kind": "goal", "effect": "confetti over the goal arch",
     "duration_ms": 1200, "max_screen_share": 0.6, "tier": "mvp"}]}


def frame(directory, name, boxes=()):
    w, h = VIEWPORT
    image = Image(w, h, bytes([90, 140, 90, 255]) * (w * h))
    for x0, y0, bw, bh in boxes:
        for y in range(y0, y0 + bh):
            for x in range(x0, x0 + bw):
                i = (y * w + x) * 4
                image.pixels[i:i + 3] = bytes([250, 210, 60])
    with open(os.path.join(directory, f"{name}.png"), "wb") as handle:
        handle.write(encode_png(image))


def cover(card=None, cols=8, rows=8):
    """A cover grid with the cells whose centre lies in `card` [x, y, w, h] covered."""
    cells = ""
    for r in range(rows):
        for c in range(cols):
            x, y = (c + 0.5) * VIEWPORT[0] / cols, (r + 0.5) * VIEWPORT[1] / rows
            inside = card and card[0] <= x <= card[0] + card[2] and card[1] <= y <= card[1] + card[3]
            cells += "1" if inside else "0"
    return {"cols": cols, "rows": rows, "viewport": VIEWPORT, "cells": cells}


def win_record(share=0.05, drawn=True, after=True, card=None, events=True, goal_ms=100):
    gem = {"seen_ms": [1050, 1100, 1200] if drawn else [], "max_share": share,
           "samples": 3 if drawn else 0, "tries": 1}
    if drawn:
        gem.update(frame="vfx-gem-burst", box=[100, 100, 60, 60], frame_ms=1100)
        if after:
            gem["after"] = "vfx-gem-burst-after"
    record = {"ui": {"won": {"viewport": VIEWPORT, "elements": [], "texts": []}},
              "events": [{"seq": 1, "kind": "pickup", "vfx": None, "ms": 1000, "state": "playing"},
                         {"seq": 2, "kind": "goal", "vfx": None, "ms": 5000, "state": "won"}]
              if events else [],
              "effects": {"gem-burst": gem} if drawn or events else {},
              "celebration": {"frame": "state-won-enter", "ms": 5000 + goal_ms,
                              "ms_after_goal": goal_ms, "viewport": VIEWPORT, "cover": cover(card),
                              "entities": [{"id": "arch", "role": "goal", "x": 150, "y": 100,
                                            "w": 100, "h": 100, "visible": True},
                                           {"id": "c1", "role": "vfx", "vfx": "confetti",
                                            "x": 120, "y": 60, "w": 160, "h": 160,
                                            "visible": True}]}}
    return {"win": record}


class ProductionGate(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="wgf-vfx-")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        frame(self.dir, "state-vfx-gem-burst", [(105, 105, 50, 50)])
        frame(self.dir, "state-vfx-gem-burst-after")
        frame(self.dir, "state-won-enter", [(130, 70, 140, 140)])
        self.frames = judging._Frames(self.dir)
        self.design = {"build_spec": {"vfx": copy.deepcopy(EFFECTS)}}

    def judge(self, tests, design=None):
        design = design or self.design
        found = judging.vfx_fires("desktop", tests, design, RULES, self.frames)
        celebration = judging.vfx_celebration("desktop", tests, design, RULES)
        return {c["id"]: c for c in found + ([celebration] if celebration else [])}

    def test_an_effect_that_fires_inside_its_share_passes(self):
        found = self.judge(win_record())
        self.assertEqual(found["vfx.fires"]["status"], "PASS", found["vfx.fires"])
        self.assertEqual(found["vfx.fires"]["measured"]["gem-burst"]["basis"], "vs after")
        # The celebration is seen in the frame of the win.
        self.assertEqual(found["vfx.fires"]["measured"]["confetti"]["fired_after"], 1)
        self.assertEqual(found["vfx.screen_share"]["status"], "PASS", found["vfx.screen_share"])
        self.assertEqual(found["vfx.celebration"]["status"], "PASS", found["vfx.celebration"])

    def test_an_interaction_with_no_effect_fails(self):
        found = self.judge(win_record(drawn=False))
        self.assertEqual(found["vfx.fires"]["status"], "FAIL")
        self.assertIn("never drawn after 1 pickup event", found["vfx.fires"]["summary"])
        self.assertEqual(found["vfx.fires"]["route"], "develop")

    def test_an_effect_the_frame_does_not_show_fails(self):
        frame(self.dir, "state-vfx-gem-burst")  # the probe says drawn; the frame is plain
        found = self.judge(win_record())
        self.assertEqual(found["vfx.fires"]["status"], "FAIL")
        self.assertIn("next to nothing", found["vfx.fires"]["summary"])

    def test_without_an_after_frame_the_background_is_the_reference(self):
        found = self.judge(win_record(after=False))
        self.assertEqual(found["vfx.fires"]["measured"]["gem-burst"]["basis"], "vs background")
        self.assertEqual(found["vfx.fires"]["status"], "PASS")

    def test_an_effect_over_its_share_fails(self):
        found = self.judge(win_record(share=0.4))
        self.assertEqual(found["vfx.screen_share"]["status"], "FAIL")
        self.assertIn("covered 40%", found["vfx.screen_share"]["summary"])

    def test_a_probe_that_reports_no_effects_fails(self):
        tests = {"win": {"ui": {}}}
        found = self.judge(tests)
        self.assertEqual(found["vfx.fires"]["status"], "FAIL")
        self.assertIn("cannot be seen from outside", found["vfx.fires"]["summary"])

    def test_an_unexercised_effect_is_not_a_pass(self):
        record = win_record()
        record["win"]["events"] = [e for e in record["win"]["events"] if e["kind"] != "pickup"]
        record["win"]["effects"] = {}
        record["win"]["events"].append({"seq": 3, "kind": "fail", "ms": 9000, "state": "lost"})
        found = self.judge(record)
        self.assertEqual(found["vfx.fires"]["status"], "WARNING")
        self.assertIn("not exercised", found["vfx.fires"]["summary"])

    def test_a_result_card_over_the_celebration_is_a_failure(self):
        # Calibration: a centred card over a centred goal from the first frame of the win.
        found = self.judge(win_record(card=[100, 40, 200, 220]))
        self.assertEqual(found["vfx.celebration"]["status"], "FAIL")
        self.assertTrue(found["vfx.celebration"]["required"])
        self.assertEqual(found["vfx.celebration"]["route"], "develop")
        # A bottom sheet clear of the goal leaves it in view.
        found = self.judge(win_record(card=[0, 240, 400, 60]))
        self.assertEqual(found["vfx.celebration"]["status"], "PASS")

    def test_measured_after_the_celebration_is_not_judged(self):
        found = self.judge(win_record(card=[100, 40, 200, 220], goal_ms=5000))
        self.assertEqual(found["vfx.celebration"]["status"], "WARNING")

    def test_no_declared_effects_no_checks(self):
        self.assertEqual(self.judge(win_record(), design={"build_spec": {}}), {})

    def test_the_routing_owns_the_checks(self):
        routing = load_file(os.path.join(ROOT, "core", "reference", "specialist-routing.yaml"))
        table = routing["producers"]["production-quality-report"]["checks"]
        self.assertEqual(table["vfx."], "feel")
        self.assertEqual(table["vfx.celebration"], "ui")
        states = routing["producers"]["visual-qa-report"]["states"]
        self.assertEqual(states["feedback_visible"], "feel")
        self.assertEqual(states["celebration_visible"], "ui")


class ProbeAndRubric(unittest.TestCase):
    def test_a_snapshot_with_events_and_effects_is_a_valid_probe(self):
        with open(PROBE_SCHEMA, encoding="utf-8") as handle:
            validator = jsonschema_lite.Validator(json.load(handle))
        snapshot = {"state": "playing", "metrics": {}, "inputs": [],
                    "entities": [{"id": "fx-1", "role": "vfx", "vfx": "gem-burst", "x": 1, "y": 2,
                                  "w": 30, "h": 30, "visible": True}],
                    "events": [{"seq": 1, "kind": "pickup", "vfx": "gem-burst"}]}
        self.assertEqual(list(validator.iter_errors(snapshot)), [])
        snapshot["events"][0]["kind"] = "trail"  # a trail has no event
        self.assertTrue(list(validator.iter_errors(snapshot)))

    def test_the_rubric_asks_about_feedback_in_the_interaction_and_win_states(self):
        rubric = load_file(os.path.join(ROOT, "core", "reference", "visual-qa-rubric.yaml"))
        questions = {q["id"]: q for q in rubric["state_questions"]}
        self.assertEqual(questions["feedback_visible"]["states"], ["interaction"])
        self.assertEqual(questions["celebration_visible"]["states"], ["win"])
        self.assertIn("celebration-hidden", {b["id"] for b in rubric["blockers"]})


if __name__ == "__main__":
    unittest.main()

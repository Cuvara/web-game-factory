"""The model craft review (L15): the craft lint, the game<->asset node contract, the model
judge, and the author loop that ships only what passed all of them - or blocks.

docs/blender-pipeline.md ("Craft review"), core/reference/model-review-rubric.yaml. Layers,
kept apart so nothing claims more than it ran:

  * no Blender - the lint on synthetic GLBs and on the reference game's library; the
    contract; the judge's verdict parsing and decision, the baseline judge and a FIXTURE
    command judge; the author's craft rounds and the blocked outcome with a FIXTURE author and
    the FAKE Blender of test_model_review.py; the step BLOCKED; and the REPLAY of the 3D
    validation run's marble and bumper rounds, their committed GLBs (byte-identical to the
    pinned Blender's builds of the recorded specs) served by a fake Blender keyed on the
    resolved spec;
  * real Blender - WGF_BLENDER_TEST=1: the recorded specs rebuilt and judged, and the
    in-context render.

    python -m unittest scripts/tests/test_model_craft.py
"""

import hashlib
import json
import os
import shutil
import stat
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, HERE)

import glb_synth  # noqa: E402
import test_model_author as base  # noqa: E402
import test_model_review as review  # noqa: E402
from testenv import enabled  # noqa: E402
from wgf_assets import blender, gltf, model_author, model_judge, model_lint  # noqa: E402
from wgf_assets import model_quality, modelspec  # noqa: E402
from wgf_assets import render as render_mod  # noqa: E402
from wgflib import jsonschema_lite, paths, template  # noqa: E402

L15 = os.path.join(base.MODELS, "l15")
LOOK = base.LOOK
KEEPER_REQ = base.KEEPER_REQ
MATS = [{"id": "kit", "hex": "#ff7a1a"}, {"id": "dark", "hex": "#1d2b53"},
        {"id": "lamp", "hex": "#ffd23f", "emissive": "#ffd23f", "emissive_strength": 3}]


def part(pid, shape, size, at, material="kit", **extra):
    return dict({"id": pid, "shape": shape, "size": list(size), "translation": list(at),
                 "material": material}, **extra)


def lint(parts, role="player", look=LOOK, spec=None, materials=MATS):
    data = glb_synth.build(parts, materials)
    return model_lint.lint(model_quality.analyse(data), spec=spec, role=role,
                           visual_identity=look)


def codes(findings):
    return sorted({(f["code"], tuple(f["parts"])) for f in findings})


def check(quality, check_id):
    return next(c for c in quality["checks"] if c["id"] == check_id)


def context(asset):
    with open(os.path.join(L15, asset, "context.json"), encoding="utf-8") as handle:
        return json.load(handle)


def look_of(ctx):
    return dict(ctx["visual_identity"], palette=ctx["palette"])


def recorded(asset, n):
    with open(os.path.join(L15, asset, f"round{n}.model.json"), encoding="utf-8") as handle:
        return json.load(handle)


def committed(asset, n):
    with open(os.path.join(L15, asset, f"round{n}.glb"), "rb") as handle:
        return handle.read()


# -- the craft lint ---------------------------------------------------------------------------

BODY = part("body", "box", (1.0, 1.0, 1.0), (0, 0.5, 0))


class Floating(unittest.TestCase):
    def test_a_part_hanging_beside_the_body_floats(self):
        found = lint([BODY, part("lantern", "sphere", (0.3, 0.3, 0.3), (0.9, 0.5, 0), "dark")])
        self.assertEqual(codes(found), [("lint.floating", ("lantern",))])
        self.assertIn("touch(es) nothing of the main body", found[0]["message"])

    def test_a_part_overlapped_into_its_support_is_attached(self):
        self.assertEqual(lint([BODY, part("lantern", "sphere", (0.3, 0.3, 0.3),
                                          (0.6, 0.5, 0), "dark")]), [])

    def test_a_hairline_gap_within_the_part_s_own_size_is_seated(self):
        # 1 cm off a 0.4 m part: 2.5%, under the 5% bar (the reference craft's nose: 4%).
        self.assertEqual(lint([BODY, part("nose", "box", (0.4, 0.2, 0.4),
                                          (0, 0.5, 0.71), "dark")]), [])

    def test_a_detached_group_floats_as_one(self):
        found = lint([BODY, part("pole", "box", (0.05, 1.0, 0.05), (2.0, 0.5, 0), "dark"),
                      part("flag", "box", (0.4, 0.3, 0.02), (2.2, 0.8, 0), "kit")])
        self.assertEqual(codes(found), [("lint.floating", ("flag", "pole"))])

    def test_kits_backgrounds_and_effects_are_separate_pieces_by_design(self):
        apart = [BODY, part("rock", "box", (1, 1, 1), (3, 0.5, 0), "dark")]
        for role in ("environment", "background", "vfx"):
            self.assertEqual(lint(apart, role=role), [], role)


class Hidden(unittest.TestCase):
    def test_a_band_sunk_inside_the_shell_is_hidden(self):
        found = lint([part("shell", "sphere", (1, 1, 1), (0, 0.5, 0)),
                      part("band", "cylinder", (0.8, 0.2, 0.8), (0, 0.5, 0), "dark")])
        self.assertEqual(codes(found), [("lint.hidden", ("band",))])

    def test_a_band_raised_through_the_surface_shows(self):
        self.assertEqual(lint([part("shell", "sphere", (1, 1, 1), (0, 0.5, 0)),
                               part("band", "cylinder", (1.06, 0.2, 1.06), (0, 0.5, 0),
                                    "dark")]), [])

    def test_a_line_thinner_than_the_model_s_grid_is_still_seen(self):
        # 8 mm high and 3 cm wide on a 9 m floor: between the silhouette grid's samples,
        # seen on the part's own grid (the reference track's lane lines).
        floor = part("floor", "box", (9.0, 0.02, 9.0), (0, 0.01, 0), "dark")
        line = part("line", "box", (8.0, 0.008, 0.03), (0, 0.024, 1.3), "kit")
        self.assertEqual(lint([floor, line], role="environment"), [])


class Coplanar(unittest.TestCase):
    def test_flush_faces_of_two_materials_fight(self):
        found = lint([part("block", "box", (1, 0.4, 1), (0, 0.2, 0)),
                      part("stripe", "box", (1, 0.4, 0.2), (0, 0.2, 0), "dark")])
        self.assertIn(("lint.coplanar", ("block", "stripe")), codes(found))
        self.assertIn("z-fight", found[0]["message"])

    def test_a_raised_face_does_not(self):
        self.assertEqual(lint([part("block", "box", (1, 0.4, 1), (0, 0.2, 0)),
                               part("stripe", "box", (1.02, 0.42, 0.2), (0, 0.2, 0),
                                    "dark")]), [])

    def test_undersides_are_not_judged(self):
        # Both resting on y = 0: their bottoms share a plane no camera above sees.
        self.assertEqual(lint([part("slab", "box", (2, 0.3, 2), (0, 0.15, 0)),
                               part("trim", "box", (0.4, 0.4, 0.4), (0, 0.2, 0), "dark")]),
                         [])


class Emissive(unittest.TestCase):
    LIT = dict(LOOK, concept="Layered cut paper lit from one side",
               avoid=["Neon glow", "Photographic textures"])
    NEON = dict(LOOK, concept="A neon synthwave arena at night")

    def test_the_identity_s_own_words_decide_never_its_avoid_list(self):
        self.assertEqual(model_lint.identity_light(self.LIT), "lit")
        self.assertEqual(model_lint.identity_light(self.NEON), "neon")
        self.assertEqual(model_lint.identity_light({}), "lit")

    def test_a_glowing_drum_fails_a_lit_identity_and_passes_a_neon_one(self):
        drum = [part("drum", "cylinder", (1, 1, 1), (0, 0.5, 0), "lamp"),
                part("base", "box", (1.2, 0.2, 1.2), (0, 0.1, 0))]
        found = lint(drum, look=self.LIT)
        self.assertEqual([f["code"] for f in found], ["lint.emissive", "lint.emissive"])
        self.assertTrue(any("glows" in f["message"] for f in found))
        self.assertEqual(lint(drum, look=self.NEON), [])

    def test_a_small_lamp_is_an_accent(self):
        lamp = [part("body", "box", (1, 1, 1), (0, 0.5, 0)),
                part("lamp", "sphere", (0.15, 0.15, 0.15), (0, 1.0, 0.45), "lamp")]
        found = lint(lamp, look=self.LIT, materials=[MATS[0], dict(MATS[2],
                                                                    emissive_strength=1.5)])
        self.assertEqual(found, [])


class Aspect(unittest.TestCase):
    def test_a_needle_gem_is_refused_a_coin_is_not(self):
        needle = [part("gem", "cone", (0.2, 0.7, 0.2), (0, 0.35, 0))]
        coin = [part("disc", "cylinder", (1, 0.1, 1), (0, 0.05, 0), rotation=[0.7071068, 0, 0,
                                                                             0.7071068])]
        found = lint(needle, role="collectible")
        self.assertEqual([f["code"] for f in found], ["lint.aspect"])
        self.assertIn("3.50 times as long", found[0]["message"])
        self.assertEqual(lint(coin, role="collectible"), [])
        self.assertEqual(lint(needle, role="projectile"), [])   # not judged for the role


class Warnings(unittest.TestCase):
    def test_bevel_and_smooth_shading_are_reported_never_blocking(self):
        spec = {"parts": [{"id": "body", "shape": "box", "size": [1, 1, 1], "material": "kit"},
                          {"id": "orb", "shape": "sphere", "segments": 6, "material": "kit"}],
                "materials": [{"id": "kit", "color": "#ff7a1a"}]}
        found = lint([BODY, part("orb", "sphere", (0.5, 0.5, 0.5), (0, 1.1, 0))], spec=spec)
        self.assertEqual({(f["code"], f["severity"]) for f in found},
                         {("lint.bevel", "warning"), ("lint.smooth", "warning")})
        crisp = dict(LOOK, shape_language="flat facets with crisp edges")
        self.assertEqual([f["code"] for f in lint(
            [BODY, part("orb", "sphere", (0.5, 0.5, 0.5), (0, 1.1, 0))], spec=spec,
            look=crisp)], ["lint.smooth"])


class LintInAssess(unittest.TestCase):
    def test_an_error_fails_model_lint_and_is_named(self):
        data = glb_synth.build([BODY, part("lantern", "sphere", (0.3, 0.3, 0.3),
                                           (0.9, 0.5, 0), "dark")], MATS)
        judged = model_quality.assess(data, role="player", visual_identity=LOOK)
        self.assertEqual(check(judged["quality"], "model.lint")["status"], "fail")
        self.assertIn("lint.floating lantern", check(judged["quality"], "model.lint")["summary"])
        self.assertEqual(judged["quality"]["verdict"], "fail")
        self.assertNotIn("_faces", judged["geometry"])

    def test_primitive_style_is_not_linted(self):
        data = glb_synth.build([BODY, part("lantern", "sphere", (0.3, 0.3, 0.3),
                                           (0.9, 0.5, 0), "dark")], MATS)
        judged = model_quality.assess(data, role="player", visual_identity=base.STYLED)
        self.assertEqual(check(judged["quality"], "model.lint")["status"], "skipped")

    def test_the_rules_are_the_reference_file(self):
        with open(model_lint.RUBRIC_PATH, encoding="utf-8") as handle:
            text = handle.read()
        rules = model_lint.load_rules()
        self.assertEqual(rules["floating"]["min_gap"], 0.05)
        self.assertEqual(rules["aspect"]["max_elongation"], {"collectible": 2.0})
        self.assertIn("version: 1.0.0", text)
        self.assertEqual(set(model_lint.DEFAULT_RULES), set(rules))


class ReferenceLibrary(unittest.TestCase):
    """The calibration: the 3D reference game's library raises no finding at its roles."""

    ROLES = {"craft": "player", "wall": "hazard", "arena-track": "environment",
             "arena-skyline": "background"}

    @classmethod
    def setUpClass(cls):
        try:
            ports = template.golden_ports_checkout()
        except template.TemplateError as exc:
            raise unittest.SkipTest(f"pinned golden ports unavailable: {exc}")
        cls.library = os.path.join(ports, "examples", "neon-drift-arena", "wgf-golden",
                                   "library", "models")
        if not os.path.isdir(cls.library):
            raise unittest.SkipTest(f"no reference library at {cls.library}")

    def test_the_reference_models_are_clean(self):
        neon = {"concept": "A neon synthwave arena"}
        for name, role in self.ROLES.items():
            with open(os.path.join(self.library, f"{name}.glb"), "rb") as handle:
                data = handle.read()
            with open(os.path.join(self.library, f"{name}.model.json"), encoding="utf-8") as h:
                spec = json.load(h)
            found = model_lint.lint(model_quality.analyse(data), spec=spec, role=role,
                                    visual_identity=neon)
            self.assertEqual(found, [], name)


# -- the node contract ------------------------------------------------------------------------

class NodeContract(unittest.TestCase):
    KIT = glb_synth.build([part("straight-top", "box", (4, 0.3, 8), (0, 0.15, 0)),
                           part("gap-chunk-1", "box", (1, 0.3, 1), (0, 0.15, 5))], MATS)

    def test_names_and_families(self):
        self.assertEqual(gltf.contract_missing(self.KIT, ["straight-top", "gap-chunk-*"],
                                               ["kit"]), [])
        self.assertEqual(gltf.contract_missing(self.KIT, ["ramp-top", "rail-*"], ["glass"]),
                         ["no node 'ramp-top'", "no node of the family 'rail-*'",
                          "no material 'glass'"])

    def test_a_missing_name_fails_the_asset(self):
        spec = {"contract": {"nodes": ["straight-top", "ramp-top", "gap-chunk-*"]}}
        self.assertEqual(modelspec.validate(spec), [])
        expect = modelspec.expectations(spec)
        self.assertEqual(expect["nodes"], ["straight-top", "ramp-top", "gap-chunk-*"])
        summary = gltf.inspect(self.KIT).summary
        found = gltf.check_expectations(summary, expect, self.KIT, name="island-kit")
        self.assertEqual([(c, s) for c, s, _m in found], [("model-nodes-missing", "error")])
        self.assertIn("'ramp-top'", found[0][2])
        judged = model_quality.assess(self.KIT, role="environment", visual_identity=LOOK,
                                      spec=spec)
        self.assertEqual(check(judged["quality"], "model.valid")["status"], "fail")

    def test_the_schema_holds_the_contract(self):
        with open(os.path.join(paths.ARTIFACTS, "shared", "model-spec.schema.json"),
                  encoding="utf-8") as handle:
            validator = jsonschema_lite.Validator(json.load(handle))
        self.assertEqual(list(validator.iter_errors(
            {"contract": {"nodes": ["gap-chunk-*", "straight-top"], "materials": ["paint"]}})),
            [])
        self.assertTrue(list(validator.iter_errors({"contract": {"nodes": ["Bad Name"]}})))


# -- the judge --------------------------------------------------------------------------------

RUBRIC = model_judge.load_rubric()
DIMS = list(RUBRIC["dimensions"])


def verdict(ids, score=4, reads=True, findings=()):
    return {"models": {i: {"scores": {d: score for d in DIMS}, "reads_as": reads,
                           "findings": list(findings), "summary": f"{i} judged"}
                       for i in ids}}


class Verdict(unittest.TestCase):
    def test_strict_parsing(self):
        parsed, errors = model_judge.parse(verdict(["a"]), RUBRIC, ["a"])
        self.assertEqual(errors, [])
        broken = verdict(["a"])
        broken["models"]["a"]["scores"]["proportion"] = 7
        del broken["models"]["a"]["reads_as"]
        parsed, errors = model_judge.parse(broken, RUBRIC, ["a", "b"])
        self.assertIsNone(parsed)
        self.assertIn("models.a.scores.proportion: an integer 0..5", errors)
        self.assertIn("models.a.reads_as: true or false", errors)
        self.assertIn("models.b: missing", errors)

    def test_the_step_decides(self):
        good = model_judge.parse(verdict(["a"]), RUBRIC, ["a"])[0]["a"]
        self.assertEqual(model_judge.decide(good, RUBRIC)["status"], "pass")
        low = dict(good, scores=dict(good["scores"], attachment=2))
        decided = model_judge.decide(low, RUBRIC)
        self.assertEqual(decided["status"], "fail")
        self.assertIn("attachment scored 2 (pass bar 3)", decided["failures"])
        flat = dict(good, scores={d: 3 for d in DIMS})
        self.assertIn("mean score 3.00 (pass bar 3.5)",
                      model_judge.decide(flat, RUBRIC)["failures"])
        self.assertEqual(model_judge.decide(dict(good, reads_as=False), RUBRIC)["status"],
                         "fail")
        blocked = dict(good, findings=[{"severity": "blocker", "dimension": "attachment",
                                        "note": "the lanterns float beside the arch"}])
        decided = model_judge.decide(blocked, RUBRIC)
        self.assertEqual(decided["status"], "fail")
        self.assertIn("blocker attachment: the lanterns float beside the arch",
                      decided["notes"])

    def test_configuration_is_checked(self):
        with self.assertRaises(model_judge.JudgeError):
            model_judge.configure({"kind": "oracle"})
        with self.assertRaises(model_judge.JudgeError):
            model_judge.configure({"kind": "command", "argv": []})
        with self.assertRaises(model_judge.JudgeError):
            model_judge.configure({"kind": "baseline", "baseline_dir": "/nonexistent/dir"})
        self.assertEqual(model_judge.configure(None)["kind"], "none")


def png(path, colour, size=32):
    from wgf_assets import encoders
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(encoders.png(size, size, colour, border=False))
    return path


class BaselineJudge(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.mkdtemp(prefix="wgf-model-judge-")
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)
        self.approved = os.path.join(self.scratch, "approved")
        png(os.path.join(self.approved, "gem.three-quarter.png"), (240, 170, 0))
        png(os.path.join(self.approved, "gem.side.png"), (240, 170, 0))
        self.settings = model_judge.configure({"kind": "baseline",
                                               "baseline_dir": self.approved})

    def entry(self, colour):
        views = {v: png(os.path.join(self.scratch, "renders", f"gem.{v}.png"), colour)
                 for v in ("three-quarter", "side")}
        return {"id": "gem", "role": "collectible", "views": views}

    def test_the_approved_look_passes(self):
        outcome = model_judge.judge(self.settings, RUBRIC, [self.entry((240, 170, 0))],
                                    self.scratch)
        self.assertIsNone(outcome["error"])
        self.assertEqual(outcome["verdicts"]["gem"]["status"], "pass")
        self.assertIn("no aesthetic judgement", outcome["verdicts"]["gem"]["summary"])

    def test_a_regression_fails(self):
        outcome = model_judge.judge(self.settings, RUBRIC, [self.entry((20, 20, 200))],
                                    self.scratch)
        decided = outcome["verdicts"]["gem"]
        self.assertEqual(decided["status"], "fail")
        self.assertTrue(any("regressed" in f for f in decided["failures"]))

    def test_a_model_nobody_approved_is_an_error_never_a_pass(self):
        outcome = model_judge.judge(self.settings, RUBRIC, [dict(self.entry((240, 170, 0)),
                                                                  id="orb")], self.scratch)
        self.assertIsNone(outcome["verdicts"])
        self.assertEqual(outcome["error"]["code"], "baseline-missing")


# The fixture judge: argv MODE {brief} {verdict} {images} STATE. Counts its calls in STATE.
JUDGE = r'''#!{python}
import json, os, re, sys
mode, brief, verdict_path, images, state = sys.argv[1:6]
calls = int(open(state).read()) + 1 if os.path.exists(state) else 1
open(state, "w").write(str(calls))
text = open(brief).read()
ids = re.findall(r"^### ([a-z0-9-]+) \(", text, re.M)
dims = {dims!r}
log = os.path.join(os.path.dirname(state), "judge.log")
seen = sorted(os.path.relpath(os.path.join(r, f), images) for r, _d, fs in os.walk(images)
              for f in fs)
open(log, "a").write(json.dumps({{"call": calls, "ids": ids, "images": seen}}) + "\n")
def entry(ok):
    return {{"scores": {{d: (4 if ok else 2) for d in dims}}, "reads_as": ok,
            "findings": [] if ok else [{{"severity": "blocker", "dimension": "attachment",
                                         "note": "the visor floats off the head"}}],
            "summary": "reads" if ok else "a visor floats"}}
if mode == "touch":
    for root, _d, files in os.walk(images):
        for f in files:
            open(os.path.join(root, f), "ab").write(b"x")
if mode == "malformed" and calls == 1:
    open(verdict_path, "w").write('{{"models": {{}}}}')
    sys.exit(0)
ok = {{"pass": True, "fail": False, "fail-once": calls > 1, "malformed": True,
       "touch": True}}[mode]
json.dump({{"models": {{i: entry(ok) for i in ids}}}}, open(verdict_path, "w"))
'''

# The fixture author: argv MODE {request} {spec}. stdout specs. A craft round adds a part.
AUTHOR = r'''#!{python}
import json, sys
mode, request_path, spec_path = sys.argv[1:4]
request = json.load(open(request_path))
keeper = json.load(open({keeper!r}))
log = {log!r}
stage = ("craft" if "craft" in request else "review" if "review" in request else
         "repair" if "repair" in request else "author")
open(log, "a").write(json.dumps({{"stage": stage, "craft": request.get("craft")}}) + "\n")
spec = keeper
if stage == "craft":
    previous = request["craft"]["previous_spec"]
    n = sum(1 for p in previous["parts"] if p["id"].startswith("visor"))
    spec = dict(previous, parts=previous["parts"] + [
        {{"id": "visor-%d" % n, "shape": "box", "size": [0.3, 0.06, 0.05],
          "position": [0, 1.62, 0.12], "material": "gloves"}}])
    if mode == "craft-breaks":
        spec = {{"parts": [{{"id": "body", "shape": "box", "size": [1, 1, 1], "material": "kit"}}],
                "materials": [{{"id": "kit", "color": "#ff7a1a"}}]}}
print("reads")
print(json.dumps(spec))
'''


class CraftCase(review.AuthorCase):
    def setUp(self):
        super().setUp()
        self.author_log = os.path.join(self.scratch, "craft-author.log")
        self.craft_author = self.script("craft-author", AUTHOR.format(
            python=sys.executable, log=self.author_log,
            keeper=os.path.join(base.MODELS, "keeper.model.json")))
        self.judge_script = self.script("judge", JUDGE.format(python=sys.executable,
                                                              dims=DIMS))
        self.state = os.path.join(self.scratch, "judge.state")

    def craft_settings(self, author_mode="ok", judge_mode="pass", **extra):
        judge = {"kind": "command", "argv": [self.judge_script, judge_mode, "{brief}",
                                             "{verdict}", "{images}", self.state]}
        judge.update(extra.pop("judge", {}))
        return dict({"kind": "command", "spec_from": "stdout",
                     "argv": [self.craft_author, author_mode, "{request}", "{spec}"],
                     "blender": {"executable": self.blender}, "review_rounds": 0,
                     "judge": judge}, **extra)

    def author_calls(self):
        if not os.path.exists(self.author_log):
            return []
        with open(self.author_log, encoding="utf-8") as handle:
            return [json.loads(line) for line in handle]

    def judge_calls(self):
        path = os.path.join(self.scratch, "judge.log")
        if not os.path.exists(path):
            return []
        with open(path, encoding="utf-8") as handle:
            return [json.loads(line) for line in handle]

    def produce(self, **kwargs):
        return model_author.produce_model(KEEPER_REQ, LOOK, self.out,
                                          self.craft_settings(**kwargs), self.context)


class JudgeLoop(CraftCase):
    def test_a_passing_verdict_ships_and_is_recorded(self):
        result = self.produce()
        self.assertEqual(check(result["quality"], "model.craft")["status"], "pass")
        self.assertEqual(result["craft"]["status"], "pass")
        self.assertEqual(result["craft"]["rounds"], 0)
        self.assertIn("Judged by the command model judge: passed", result["notes"])
        calls = self.judge_calls()
        self.assertEqual(calls[0]["ids"], ["keeper"])
        self.assertIn("keeper/sheet.png", calls[0]["images"])

    def test_a_failing_verdict_goes_back_to_the_author_with_the_notes(self):
        result = self.produce(judge_mode="fail-once")
        stages = [c["stage"] for c in self.author_calls()]
        self.assertEqual(stages, ["author", "craft"])
        craft = self.author_calls()[1]["craft"]
        self.assertIn("blocker attachment: the visor floats off the head", craft["notes"])
        self.assertTrue(any("attachment scored 2" in f for f in craft["failures"]))
        self.assertTrue(os.path.isfile(craft["renders"]["sheet"]))
        self.assertIn("visor-0", [p["id"] for p in result["spec"]["parts"]])
        self.assertEqual(result["craft"]["rounds"], 1)
        self.assertEqual([h["stage"] for h in result["history"]],
                         ["author", "judge", "craft", "judge"])

    def test_spent_rounds_block_never_ship_the_last_passing_spec(self):
        with self.assertRaises(model_author.ModelAuthorError) as caught:
            self.produce(judge_mode="fail", judge={"rounds": 2})
        error = caught.exception
        self.assertTrue(error.blocked)
        self.assertIn("refused it after 2 craft round(s)", str(error))
        self.assertEqual([c["stage"] for c in self.author_calls()],
                         ["author", "craft", "craft"])
        self.assertEqual(len(self.judge_calls()), 3)
        self.assertFalse(os.path.exists(os.path.join(self.out, "keeper.glb")))
        finding = error.finding
        with open(os.path.join(paths.ARTIFACTS, "shared", "quality-finding.schema.json"),
                  encoding="utf-8") as handle:
            schema = json.load(handle)
        validator = jsonschema_lite.Validator(dict(schema["$defs"]["finding"],
                                                   **{"$defs": schema["$defs"]}))
        self.assertEqual(list(validator.iter_errors(finding)), [])
        self.assertEqual((finding["owner"], finding["route"], finding["severity"]),
                         ("environment-artist", "assets", "blocker"))
        self.assertIn("the visor floats off the head", finding["task"]["change"])

    def test_a_craft_revision_that_breaks_a_check_is_repaired_then_judged(self):
        with self.assertRaises(model_author.ModelAuthorError) as caught:
            self.produce(author_mode="craft-breaks", judge_mode="fail",
                         judge={"rounds": 1}, max_repair_rounds=0)
        self.assertTrue(caught.exception.blocked)
        self.assertIn("the judge refused it", str(caught.exception))
        self.assertEqual([c["stage"] for c in self.author_calls()],
                         ["author", "craft", "repair"])

    def test_a_malformed_verdict_goes_back_to_the_judge(self):
        result = self.produce(judge_mode="malformed")
        self.assertEqual(result["craft"]["status"], "pass")
        self.assertEqual(len(self.judge_calls()), 2)

    def test_a_judge_that_changes_an_image_is_refused(self):
        with self.assertRaises(model_author.ModelAuthorError) as caught:
            self.produce(judge_mode="touch")
        self.assertIn("changed what it may only read", str(caught.exception))
        self.assertFalse(caught.exception.blocked)

    def test_no_judge_is_skipped_never_passed(self):
        result = model_author.produce_model(
            KEEPER_REQ, LOOK, self.out, dict(self.craft_settings(), judge={"kind": "none"}),
            self.context)
        self.assertEqual(check(result["quality"], "model.craft")["status"], "skipped")
        self.assertIsNone(result["craft"])
        self.assertEqual(self.judge_calls(), [])

    def test_the_command_judge_needs_renders(self):
        open(os.path.join(self.scratch, "no-render"), "w").close()
        with self.assertRaises(model_author.ModelAuthorError) as caught:
            self.produce()
        self.assertIn("a model nobody looked at is not passed", str(caught.exception))

    def test_set_mode_judges_the_set_and_sends_back_only_the_refused(self):
        settings = dict(self.craft_settings(judge_mode="fail-once"), mode="set")
        settings["argv"] = [self.author, "set", "{request}", "{spec}", "{dir}", "{prompt}"]
        made = model_author.produce_models([KEEPER_REQ, review.CRATE_REQ], LOOK, self.out,
                                           settings, self.context)
        self.assertEqual(sorted(made["results"]), ["crate", "keeper"])
        self.assertEqual(self.judge_calls()[0]["ids"], ["keeper", "crate"])
        stages = [c["stage"] for c in self.calls()]
        self.assertEqual(stages, ["author", "author"])  # a craft round reads as an ask
        for result in made["results"].values():
            self.assertEqual(result["craft"]["rounds"], 1)


# -- the pipeline and the step ----------------------------------------------------------------

class StepBlocked(CraftCase):
    def test_a_blocked_model_ships_nothing_and_stops_the_step(self):
        from wgf_assets import pipeline as pipeline_mod

        class Item:
            def __init__(self):
                self.issues = []
                self.data = {"notes": None}
                self.req = type("R", (), {"id": "keeper"})()

            def issue(self, code, severity, message):
                self.issues.append((code, severity, message))

        item = Item()
        error = model_author.ModelAuthorError("keeper: BLOCKED - x", blocked=True,
                                              finding={"assets": ["keeper"]})
        pipeline_mod.AssetPipeline._craft_blocked(item, error)
        self.assertEqual(item.issues[0][:2], ("model-craft-blocked", "error"))
        self.assertEqual(item.craft_finding, {"assets": ["keeper"]})


# -- the replay: the 3D validation run's marble and bumper (L15) --------------------------------

REPLAY_BLENDER = r'''#!{python}
# Serves the committed GLB of each recorded spec, keyed on the resolved spec the Factory
# hands Blender: the pinned Blender's own builds of those specs, byte for byte.
import hashlib, json, shutil, sys
args = sys.argv[1:]
if "--version" in args:
    print("Blender 4.5.14 LTS")
    sys.exit(0)
opts = dict(zip(args[args.index("--") + 1::2], args[args.index("--") + 2::2]))
if "--job" in opts:
    sys.exit(3)                        # no renders: the replay judges the measured checks
table = json.load(open({table!r}))
key = hashlib.sha256(open(opts["--spec"], "rb").read()).hexdigest()
if key not in table:
    json.dump({{"ok": False, "error": "replay: an unrecorded spec"}}, open(opts["--report"], "w"))
    sys.exit(3)
shutil.copyfile(table[key], opts["--out"])
json.dump({{"ok": True, "blender": "replay", "exporter": "replay"}}, open(opts["--report"], "w"))
'''

# Answers each ask with the next recorded spec of the asset, in the run's order.
REPLAY_AUTHOR = r'''#!{python}
import json, os, sys
request_path = sys.argv[1]
asset = json.load(open(request_path))["asset"]["id"]
state = {state!r}
n = int(open(state).read()) if os.path.exists(state) else 0
open(state, "w").write(str(n + 1))
path = os.path.join({l15!r}, asset, "round%d.model.json" % n)
print(json.dumps(json.load(open(path))) if os.path.exists(path) else "no more rounds")
'''


def resolved_key(spec, asset):
    resolved, _textures = modelspec.resolve(spec, asset)
    text = json.dumps(resolved, sort_keys=True, indent=1)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class Replay(unittest.TestCase):
    """What the run shipped, and what the new pipeline makes of the same rounds."""

    def setUp(self):
        self.scratch = tempfile.mkdtemp(prefix="wgf-l15-")
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)

    def judged(self, asset, n):
        ctx = context(asset)
        return model_quality.assess(committed(asset, n), role=ctx["asset"]["role"],
                                    visual_identity=look_of(ctx), spec=recorded(asset, n),
                                    requirement=ctx["asset"], camera=ctx["camera"])

    def test_the_committed_glbs_are_the_recorded_specs_builds(self):
        for asset in ("marble", "bumper"):
            for n in (1, 2, 3):
                stamp = blender.read_stamp(committed(asset, n))
                self.assertEqual(stamp["spec_hash"], modelspec.spec_hash(recorded(asset, n)),
                                 (asset, n))

    def test_the_shipped_marble_round1_fails_the_lint_its_band_is_sunk(self):
        quality = self.judged("marble", 1)
        lint_check = check(quality["quality"], "model.lint")
        self.assertEqual(lint_check["status"], "fail")
        self.assertIn("lint.hidden swirl-band", lint_check["summary"])
        self.assertIn("lint.hidden swirl-edge", lint_check["summary"])

    def test_the_shipped_bumper_round2_fails_the_lint_dome_and_gap_are_sunk(self):
        quality = self.judged("bumper", 2)
        lint_check = check(quality["quality"], "model.lint")
        self.assertEqual(lint_check["status"], "fail")
        self.assertIn("lint.hidden dome", lint_check["summary"])
        self.assertIn("lint.hidden gap", lint_check["summary"])

    def replay(self, asset, **settings):
        table = {}
        for n in range(4):
            spec = recorded(asset, n)
            if os.path.exists(os.path.join(L15, asset, f"round{n}.glb")):
                table[resolved_key(spec, asset)] = os.path.join(L15, asset, f"round{n}.glb")
        table_path = os.path.join(self.scratch, "table.json")
        with open(table_path, "w", encoding="utf-8") as handle:
            json.dump(table, handle)
        fake = os.path.join(self.scratch, "blender")
        author = os.path.join(self.scratch, "author")
        for path, text in ((fake, REPLAY_BLENDER.format(python=sys.executable,
                                                        table=table_path)),
                           (author, REPLAY_AUTHOR.format(
                               python=sys.executable, l15=L15,
                               state=os.path.join(self.scratch, "rounds")))):
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(text)
            os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)
        ctx = context(asset)
        config = dict({"kind": "command", "spec_from": "stdout", "argv": [author, "{request}"],
                       "blender": {"executable": fake}, "max_repair_rounds": 2,
                       "review_rounds": 1}, **settings)
        return model_author.produce_model(
            ctx["asset"], look_of(ctx), os.path.join(self.scratch, "out"), config,
            {"run_dir": os.path.join(self.scratch, "run"),
             "design": {"camera": ctx["camera"], "art_direction": ctx["art_direction"]}})

    def test_the_marble_s_rounds_ship_nothing_now(self):
        # The run: round 0 refused (schema), round 1 passed and SHIPPED (its band sunk
        # inside the shell), round 2 - the author's own review revision - refused (aspect
        # 1.23), round 3 refused. Now round 1 fails the lint too: no round passes, and
        # nothing ships.
        with self.assertRaises(model_author.ModelAuthorError) as caught:
            self.replay("marble")
        self.assertFalse(caught.exception.blocked)
        self.assertTrue(any("lint.hidden" in p or "model." in p
                            for p in caught.exception.problems), caught.exception.problems)
        self.assertFalse(os.path.exists(os.path.join(self.scratch, "out", "marble.glb")))

    def test_the_bumper_s_rounds_ship_nothing_now(self):
        # The run: round 2 passed and SHIPPED (dome and gap sunk); round 3, the author's
        # review "a stack of flat discs" revision, was dropped and round 2 shipped. Now
        # round 2 fails the lint: no round passes, and nothing ships.
        with self.assertRaises(model_author.ModelAuthorError) as caught:
            self.replay("bumper")
        self.assertFalse(os.path.exists(os.path.join(self.scratch, "out", "bumper.glb")))
        problems = " ".join(caught.exception.problems)
        self.assertIn("lint.", problems)


@unittest.skipUnless(enabled("WGF_BLENDER_TEST"), "real Blender: set WGF_BLENDER_TEST=1")
class RealBlender(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.info = blender.discover(None)
        if cls.info.version is None:
            raise unittest.SkipTest("no Blender on PATH or in WGF_BLENDER")

    def test_the_recorded_specs_rebuild_to_the_committed_glbs(self):
        for asset in ("marble", "bumper"):
            for n in (1, 2, 3):
                data, _report, _key = blender.build_model(self.info, recorded(asset, n), asset)
                self.assertEqual(data, committed(asset, n), (asset, n))

    def test_the_in_context_render(self):
        scratch = tempfile.mkdtemp(prefix="wgf-l15-render-")
        self.addCleanup(shutil.rmtree, scratch, ignore_errors=True)
        ctx = context("bumper")
        entries = []
        for asset, n in (("bumper", 2), ("marble", 1)):
            path = os.path.join(scratch, f"{asset}.glb")
            with open(path, "wb") as handle:
                handle.write(committed(asset, n))
            entries.append({"id": asset, "glb": path, "role": context(asset)["asset"]["role"],
                            "readability": context(asset)["asset"]["readability"]})
        surface, _token = model_quality.surface_colour({"palette": ctx["palette"]})
        report = render_mod.render(
            self.info, entries, out_dir=scratch, identity=look_of(ctx), camera=ctx["camera"],
            lineup=False, context={"surface": surface, "player": entries[1]["glb"],
                                   "player_id": "marble",
                                   "backdrop": model_quality.background_colour(
                                       {"palette": ctx["palette"]})})
        bumper = report["models"]["bumper"]["context"]
        self.assertTrue(os.path.isfile(bumper["path"]))
        self.assertEqual(bumper["beside"], "marble")
        self.assertIsNone(report["models"]["marble"]["context"]["beside"])


if __name__ == "__main__":
    unittest.main()

"""The 2D author's `set` mode, the set preview, and the identity checks it is judged by.

What this covers (docs/assets-module.md "The set author"):

    set mode    ONE session (fixtures/assets/fake_set_author.py, run through wgflib.procs)
                draws every 2D requirement: the brief carries all of them, the whole visual
                identity, the art direction, the craft guides and the preview command; it
                writes only into the Factory's out/ directory; the Factory judges and
                delivers what passes, asks again with the problems and the contact sheet, and
                sends what never passes to a placeholder that says why
    preview     wgf_assets/preview.py as the command an author runs: the report, exit codes;
                without a checkout that installs Playwright, a review with no render and a
                warning. A real render runs when WGF_PREVIEW_CHECKOUT names a checkout with
                Playwright installed
    quality     svg.text-font (the design's faces, not a system font), svg.avoid (the
                identity's measurable avoid lines) and set.consistent (one outline, width,
                colour and soft-effect treatment per group of roles)

Deterministic and offline unless WGF_PREVIEW_CHECKOUT is set.

    python -m unittest scripts/tests/test_asset_set_author.py
"""

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

import test_assets as base  # noqa: E402
import test_assets_production as prod  # noqa: E402
from wgf_assets import preview, quality  # noqa: E402
from wgf_assets.author import AuthorError, build_author  # noqa: E402
from wgf_assets.set_author import SetAuthor  # noqa: E402
from wgf_assets.step import AssetsStep  # noqa: E402
from wgflib.workflow.contracts import ArtifactContracts  # noqa: E402

FAKE_SET = os.path.join(base.FIXTURES, "fake_set_author.py")
ENTITIES = ("hero", "tile", "spike")


def design(**identity):
    return _with_art(prod.production_design(**identity))


def _with_art(body):
    body = dict(body)
    body["art_direction"] = "Neon arcade at night: hard chevrons, one hot accent."
    body["engine"] = dict(body["engine"], design_resolution={"width": 960, "height": 540})
    return base.with_provenance({k: v for k, v in body.items() if k != "provenance"},
                                "game-design", "neon-test")


class SetCase(prod.ProductionCase):
    def set_author(self, mode, **extra):
        settings = {"kind": "command", "mode": "set",
                    "argv": [sys.executable, FAKE_SET, mode, "{request}", "{out}",
                             "{preview}"],
                    "timeout_seconds": 120, "idle_timeout_seconds": None}
        settings.update(extra)
        return settings

    def set_dir(self):
        return os.path.join(self.run_dir, "assets", "1-1", "author-set")

    def calls(self):
        path = os.path.join(self.set_dir(), "calls.jsonl")
        if not os.path.exists(path):
            return []
        with open(path, encoding="utf-8") as handle:
            return [json.loads(line) for line in handle]


class SetMode(SetCase):
    def test_one_session_draws_every_2d_requirement_from_the_whole_identity(self):
        manifest, _ = self.run_prod(design(), author=self.set_author("good"))
        items = self.items(manifest)
        calls = self.calls()
        self.assertEqual(len(calls), 1)  # one session for the whole set
        brief = calls[0]
        # Every mvp 2D requirement, with the file of each variant inside out/.
        self.assertEqual(sorted(r["id"] for r in brief["requirements"]),
                         ["badge", "board", "hero", "spike", "tile"])
        out = os.path.join(self.set_dir(), "out")
        tile = next(r for r in brief["requirements"] if r["id"] == "tile")
        self.assertEqual([f["path"] for f in tile["files"]],
                         [os.path.join(out, "tile-1.svg"), os.path.join(out, "tile-2.svg")])
        self.assertEqual(tile["role"], "target")
        self.assertIn("first-time player", tile["readability"])
        # The FULL identity - typography, motion, ui too - and the art direction.
        identity = brief["visual_identity"]
        self.assertEqual(identity["typography"], {"display": "Display", "body": "Body"})
        self.assertEqual(identity["motion"], "Snappy")
        self.assertEqual(brief["typography_faces"], ["display", "body"])
        self.assertIn("Neon arcade at night", brief["art_direction"])
        self.assertEqual(brief["design_resolution"], {"width": 960, "height": 540})
        self.assertEqual(brief["background"], "#0B0B12")  # the 'ground' token
        self.assertTrue(brief["craft"])
        for path in brief["craft"]:
            self.assertTrue(os.path.isabs(path) and os.path.isfile(path), path)
        self.assertIn("production-art-2d.md", " ".join(brief["craft"]))
        self.assertIn("game-ui-kit.md", " ".join(brief["craft"]))
        self.assertIn("outline", brief["set_bars"]["rule"])
        # Every mvp item delivered and judged, the entities against each other too.
        for item_id in ("hero", "tile", "spike", "board", "badge"):
            item = items[item_id]
            self.assertFalse(item["placeholder"], item_id)
            self.assertEqual(item["source"], "ai-generated")
            self.assertEqual(item["quality"]["verdict"], "pass", item["quality"])
            self.assertEqual(item["quality"]["author"], "author:set")
            self.assertTrue(item["production_ready"], item_id)
        for item_id in ENTITIES:
            ids = [c["id"] for c in items[item_id]["quality"]["checks"]]
            self.assertIn("set.consistent", ids, item_id)
        self.assertIn("svg.text-font", [c["id"] for c in items["hero"]["quality"]["checks"]])
        self.assertTrue(items["coin"].get("placeholder") is None or
                        items["coin"]["status"] == "planned")
        self.assertEqual([f["path"] for f in items["tile"]["files"]],
                         ["public/assets/sprites/tile-1.svg", "public/assets/sprites/tile-2.svg"])
        self.assertEqual(ArtifactContracts()("asset-manifest", manifest), [])
        # The author ran the preview it was given: every drawing judged, no render here.
        with open(os.path.join(self.set_dir(), "preview.txt"), encoding="utf-8") as handle:
            said = handle.read()
        self.assertIn("exit 0", said)
        self.assertIn("6 of 6 drawings pass", said)
        with open(os.path.join(self.set_dir(), "rounds.json"), encoding="utf-8") as handle:
            rounds = json.load(handle)
        self.assertEqual(len(rounds["rounds"]), 1)
        self.assertTrue(rounds["warnings"])  # no checkout with Playwright: judged, not seen

    def test_what_fails_is_shown_again_with_its_problems_and_the_contact_sheet(self):
        manifest, _ = self.run_prod(design(), author=self.set_author("font-then-good"))
        calls = self.calls()
        self.assertEqual(len(calls), 2)
        self.assertNotIn("repair", calls[0])
        repair = calls[1]["repair"]
        self.assertEqual(repair["round"], 1)
        self.assertIn("hero", repair["problems"])
        self.assertTrue(any("svg.text-font" in p and "arial" in p
                            for p in repair["problems"]["hero"]))
        self.assertTrue(any("set.consistent" in p for p in repair["problems"]["tile-1"]))
        self.assertIn("contact_sheet", repair)
        self.assertIn("spike", repair["passing"])
        for item_id in ("hero", "tile", "spike"):
            self.assertEqual(self.items(manifest)[item_id]["quality"]["verdict"], "pass")

    def test_a_drawing_that_never_fits_the_set_falls_back_to_a_placeholder_that_says_why(self):
        manifest, _ = self.run_prod(design(), author=self.set_author("inconsistent"))
        items = self.items(manifest)
        self.assertTrue(items["tile"]["placeholder"])
        message = next(i["message"] for i in manifest["issues"]
                       if i["code"] == "author-rejected" and i["item_id"] == "tile")
        self.assertIn("set.consistent", message)
        self.assertIn("no outline", message)
        self.assertEqual(len(self.calls()), 2)  # the first session and one repair round
        for item_id in ("hero", "spike", "board", "badge"):
            self.assertFalse(items[item_id]["placeholder"], item_id)

    def test_unwritten_files_and_a_failing_host(self):
        manifest, _ = self.run_prod(design(), author=self.set_author("partial",
                                                                     repair_rounds=0))
        items = self.items(manifest)
        self.assertFalse(items["hero"]["placeholder"])
        self.assertTrue(items["tile"]["placeholder"])
        self.assertIn("was not written", next(
            i["message"] for i in manifest["issues"]
            if i["code"] == "author-rejected" and i["item_id"] == "tile"))
        manifest, _ = self.run_prod(design(), author=self.set_author("fail"))
        for item_id in ("tile", "spike", "board", "badge"):
            self.assertTrue(self.items(manifest)[item_id]["placeholder"], item_id)

    def test_a_host_that_ends_mid_set_gets_the_repair_round(self):
        manifest, _ = self.run_prod(design(), author=self.set_author("crash-then-good"))
        calls = self.calls()
        self.assertEqual(len(calls), 2)
        self.assertIn("exit 3", calls[1]["repair"]["previous_session"])
        self.assertIn("hero", calls[1]["repair"]["passing"])
        for item_id in ("hero", "tile", "spike", "board", "badge"):
            self.assertFalse(self.items(manifest)[item_id]["placeholder"], item_id)

    def test_re_execution_reuses_the_set_without_a_session(self):
        first, _ = self.run_prod(design(), author=self.set_author("good"))
        self.assertEqual(len(self.calls()), 1)
        second, _ = self.run_prod(design(), author=self.set_author("good"))
        self.assertEqual(len(self.calls()), 1)
        self.assertEqual(self.items(first)["tile"]["files"], self.items(second)["tile"]["files"])
        # A changed requirement re-opens the set; what was accepted is seeded and marked.
        changed = prod.production_design([
            prod.spec_asset("hero", "sprite", "player", spec="96x96",
                            readability="a hero in a red cape"),
            prod.spec_asset("spike", "sprite", "threat", spec="64px")])
        self.run_prod(changed, author=self.set_author("good"))
        calls = self.calls()
        self.assertEqual(len(calls), 2)
        files = {f["variant"]: f["accepted"] for r in calls[1]["requirements"]
                 for f in r["files"]}
        self.assertEqual(files, {"hero": False, "spike": True})

    def test_set_mode_is_configured_or_refused(self):
        for author in ({"kind": "command", "mode": "gallery", "argv": ["x"]},
                       {"kind": "command", "mode": "set", "argv": ["x", "{output}"]},
                       {"kind": "command", "mode": "set", "argv": ["x"], "svg_from": "stdout"},
                       {"kind": "command", "mode": "set"}):
            context = base.FakeContext({"root": self.root, "author": author})
            result = AssetsStep(base.Definition()).execute(prod.inputs_with(design()), context)
            self.assertEqual(result.outcome, "FAILED", author)
            self.assertFalse(result.retryable)
        made = build_author({"kind": "command", "mode": "set", "argv": ["x", "{out}"]})
        self.assertIsInstance(made, SetAuthor)
        self.assertEqual(made.label, "author:set")
        with self.assertRaises(AuthorError):
            build_author({"kind": "command", "mode": "set", "argv": ["{nope}"]})


class PreviewCommand(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="wgf-preview-")
        self.addCleanup(__import__("shutil").rmtree, self.dir, ignore_errors=True)
        self.out = os.path.join(self.dir, "out")
        os.makedirs(self.out)

    def job(self, checkout=None):
        job = {"out_dir": self.out, "preview_dir": os.path.join(self.dir, "preview"),
               "checkout": checkout, "background": "#2B3A55", "surface": "#F7F1E3",
               "palette": [{"token": "ink", "hex": "#26211C"},
                           {"token": "marigold", "hex": "#F2A900"},
                           {"token": "coral", "hex": "#E4572E"}],
               "typography": {"display": "Fraunces (800)", "body": "Commissioner (500)"},
               "avoid": ["Neon glow"],
               "files": [{"id": "fruit-1", "requirement": "fruit", "role": "target",
                          "width": 96, "height": 96, "count": 2},
                         {"id": "fruit-2", "requirement": "fruit", "role": "target",
                          "width": 96, "height": 96, "count": 2}]}
        path = os.path.join(self.dir, "job.json")
        preview.write_job(path, job)
        return path, job

    def write(self, name, svg):
        with open(os.path.join(self.out, name), "w", encoding="utf-8") as handle:
            handle.write(svg)

    def fruit(self, r, glow=False):
        blur = ('<defs><filter id="g"><feGaussianBlur stdDeviation="3"/></filter></defs>'
                if glow else "")
        return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 96 96">{blur}'
                f'<circle cx="48" cy="52" r="{r}" fill="#E4572E" stroke="#26211C" '
                f'stroke-width="3"/><path d="M48 20 L52 8" stroke="#26211C" stroke-width="3"/>'
                f'<ellipse cx="40" cy="40" rx="6" ry="4" fill="#F2A900"/></svg>')

    def test_the_command_reports_problems_and_exits_as_the_set_does(self):
        path, _job = self.job()
        self.write("fruit-1.svg", self.fruit(20))
        code = self.main(path)
        self.assertEqual(code, 1)  # fruit-2 missing
        with open(os.path.join(self.dir, "preview", "report.json"), encoding="utf-8") as handle:
            report = json.load(handle)
        self.assertIn("was not written", " ".join(report["files"]["fruit-2"]["problems"]))
        self.write("fruit-2.svg", self.fruit(40, glow=True))
        with open(path, encoding="utf-8") as handle:
            result = preview.review(json.load(handle), do_render=False)
        problems = " ".join(result["files"]["fruit-2"]["problems"])
        self.assertIn("svg.avoid", problems)
        self.assertIn("Neon glow", problems)
        self.write("fruit-2.svg", self.fruit(40))
        self.assertEqual(self.main(path), 0)
        self.assertEqual(self.main(os.path.join(self.dir, "nope.json")), 2)

    @staticmethod
    def main(path):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return preview.main([path])

    def test_no_checkout_is_a_review_without_a_render(self):
        path, job = self.job(checkout=self.dir)  # no package.json there
        self.write("fruit-1.svg", self.fruit(20))
        self.write("fruit-2.svg", self.fruit(40))
        result = preview.review(job)
        self.assertTrue(result["passed"])
        self.assertIsNone(result["sheet"])
        self.assertIn("package.json", result["warnings"][0])

    @unittest.skipUnless(os.environ.get("WGF_PREVIEW_CHECKOUT"),
                         "set WGF_PREVIEW_CHECKOUT to a game checkout with Playwright installed")
    def test_a_real_render_composes_the_contact_sheet(self):
        _path, job = self.job(checkout=os.environ["WGF_PREVIEW_CHECKOUT"])
        self.write("fruit-1.svg", self.fruit(20))
        self.write("fruit-2.svg", self.fruit(40))
        result = preview.review(job)
        self.assertEqual(result["warnings"], [])
        self.assertTrue(os.path.isfile(result["sheet"]))
        with open(result["sheet"], "rb") as handle:
            self.assertEqual(handle.read(8), b"\x89PNG\r\n\x1a\n")
        self.assertEqual(sorted(result["renders"]), ["fruit-1", "fruit-2"])


class IdentityChecks(unittest.TestCase):
    TYPE = {"display": "Fraunces (800, soft)", "body": "Commissioner (500)"}

    def judge(self, body, **kw):
        svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 96 96">{body}</svg>'
        kw.setdefault("typography", self.TYPE)
        return quality.svg_quality(svg.encode(), role="ui", **kw)

    def check(self, judged, check_id):
        return next((c for c in judged["checks"] if c["id"] == check_id), None)

    def test_text_is_set_in_the_design_faces_or_fails(self):
        shapes = '<rect width="96" height="40" fill="#F2A900"/><path d="M0 0 L9 9"/>'
        for body, ok in (
                ('<text font-family="Fraunces, serif">Play</text>', True),
                ('<g font-family="\'Commissioner\'"><text>Play</text></g>', True),
                ('<style>.t{font-family:Commissioner}</style><text class="t">Play</text>',
                 True),
                ('<text>Play</text>', False),
                ('<text font-family="Arial, sans-serif">Play</text>', False),
                ('<text style="font-family: sans-serif">Play</text>', False)):
            with self.subTest(body=body):
                found = self.check(self.judge(shapes + body), "svg.text-font")
                self.assertEqual(found["status"], "pass" if ok else "fail", found)
        # No text, or no typography: the check does not apply.
        self.assertIsNone(self.check(self.judge(shapes), "svg.text-font"))
        self.assertIsNone(self.check(self.judge(shapes + "<text>x</text>", typography=None),
                                     "svg.text-font"))

    def test_the_measurable_avoid_lines(self):
        shapes = '<rect width="96" height="40" fill="#F2A900"/><path d="M0 0 L9 9"/>'
        cases = [
            (["Neon glow"], '<defs><filter id="f"><feGaussianBlur stdDeviation="2"/>'
                            '</filter></defs><circle r="9" filter="url(#f)"/>', False),
            (["Soft blurred shadows"], '<circle r="9" style="filter: drop-shadow(0 2px 4px '
                                       '#000)"/>', False),
            (["Neon glow"], '<circle r="9" fill="#E4572E"/>', True),
            (["Emoji as iconography"], '<text font-family="Fraunces">\U0001F34E</text>', False),
            (["Purple-to-blue gradients on white"],
             '<defs><linearGradient id="g"><stop stop-color="#8A2BE2"/>'
             '<stop stop-color="#1E6FD9"/></linearGradient></defs>', False),
            (["Gradients inside text"], '<text font-family="Fraunces" fill="url(#g)">A</text>',
             False),
            (["Rounded corners"], '<rect width="9" height="9" rx="3"/>', False)]
        for avoid, body, ok in cases:
            with self.subTest(avoid=avoid, body=body):
                found = self.check(self.judge(shapes + body, avoid=avoid), "svg.avoid")
                self.assertEqual(found["status"], "pass" if ok else "fail", found)
                if not ok:
                    self.assertIn(avoid[0], found["summary"])
        # A line nothing measures adds no check.
        self.assertIsNone(self.check(self.judge(shapes, avoid=["Pastels"]), "svg.avoid"))

    @staticmethod
    def entity(width=3, colour="#1C1A17", outlined=True, blur=False, view=192):
        stroke = f' stroke="{colour}" stroke-width="{width}"' if outlined else ""
        fx = ('<defs><filter id="b"><feGaussianBlur stdDeviation="2"/></filter></defs>'
              if blur else "")
        return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {view} {view}">{fx}'
                f'<rect x="20" y="40" width="80" height="60" fill="#FF48B0"{stroke}/>'
                f'<path d="M20 40 L60 10 L100 40 Z" fill="#0078BF"{stroke}/>'
                f'<circle cx="60" cy="70" r="9" fill="#F4EDE1"/></svg>').encode()

    def test_set_consistency_measures_outline_width_colour_and_effects(self):
        size = (96, 96)
        same = [(f"p-{n}", self.entity(5), "target", size) for n in range(1, 4)]
        checks, measured = quality.set_consistency(same)
        self.assertEqual({c["status"] for c in checks.values()}, {"pass"})
        self.assertEqual(measured["entities"]["p-1"]["outline_px"], 2.5)  # 5 at a 2x viewBox
        for odd, words in ((self.entity(15), "outline is 7.5px"),
                           (self.entity(5, colour="#FF48B0"), "outline colour"),
                           (self.entity(outlined=False), "no outline"),
                           (self.entity(5, blur=True), "blur")):
            with self.subTest(words=words):
                checks, _ = quality.set_consistency(same + [("odd", odd, "player", size)])
                self.assertEqual(checks["odd"]["status"], "fail", checks["odd"])
                self.assertIn(words, checks["odd"]["summary"])
                self.assertEqual(checks["p-1"]["status"], "pass")
        # The same width drawn on a 1x canvas is the same displayed outline.
        checks, _ = quality.set_consistency(
            same + [("small", self.entity(2.5, view=96), "player", size)])
        self.assertEqual(checks["small"]["status"], "pass", checks["small"])
        # Roles outside the groups, and groups of one, are not compared.
        checks, _ = quality.set_consistency([("bg", self.entity(15), "background", None),
                                             ("p", self.entity(5), "target", size)])
        self.assertEqual(checks, {})


if __name__ == "__main__":
    unittest.main()

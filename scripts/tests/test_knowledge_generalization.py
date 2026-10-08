"""A lesson learned on one game catches the same defect in another (the `generalizes` tests).

A lesson is stated so it is true of any game (core/reference/lessons.yaml). These tests are
the evidence for that claim: each replays the REAL record of the game the lesson was learned
from (game A, scripts/tests/fixtures/browser-qa/, fixtures/real/play-realism/) through the
check the lesson names, then a SYNTHETIC game B of another family, render or layout
(scripts/tests/fixtures/knowledge/), regressed and fixed, through the same check: B regressed
fails it, B fixed passes it. They are the lessons' `tests.generalizes`, run by the regression
firewall (`wgf knowledge firewall`, the Core Acceptance Suite's KNOWLEDGE category).

    python -m unittest scripts.tests.test_knowledge_generalization
"""

import copy
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
for entry in (SCRIPTS, HERE):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from browser_qa_fixture import healthy_records  # noqa: E402
from wgf_playability import realism  # noqa: E402
from wgf_verification import browser_qa  # noqa: E402
from wgflib.yamllite import load_file  # noqa: E402

FIXTURES = os.path.join(HERE, "fixtures")
CONTRACT = browser_qa.load_contract()
RULES = realism.load_rules()
RELEASE = realism.strength_for(RULES, "release")


def fixture(*parts):
    with open(os.path.join(FIXTURES, *parts), encoding="utf-8") as handle:
        return json.load(handle)


def lesson(lesson_id):
    lessons = load_file(os.path.join(ROOT, "core", "reference", "lessons.yaml"))
    return next(l for l in lessons["lessons"] if l["id"] == lesson_id)


def judged(records, klass="release", action_audio=(), bundle=None):
    checks = browser_qa.judge(records, CONTRACT, klass=klass, action_audio=list(action_audio),
                              bundle=bundle)
    return {c.id: c.status for c in checks}


def replay(name):
    """Game A: the records the browser-QA spec made of a validation game."""
    data = fixture("browser-qa", name)
    return judged(data["records"], data["klass"], data["action_audio"], data["bundle"])


def synthetic(spec, variant):
    """Game B: the healthy records with the fixture's per-viewport replacements."""
    records = healthy_records(CONTRACT)
    for vid, replace in (spec.get(variant) or {}).items():
        records[vid]["viewport"].update(copy.deepcopy(replace))
    return judged(records, spec.get("klass", "release"))


class BrowserLessons(unittest.TestCase):
    def assert_generalizes(self, spec, check_source):
        self.assertIn(spec["check"], lesson(spec["lesson"])["checks"])
        self.assertTrue(spec["check"].startswith(check_source + ":"))
        for variant in ("regressed", "fixed"):
            statuses = synthetic(spec, variant)
            for check_id, expected in spec["expect"][variant].items():
                self.assertEqual(statuses[check_id], expected, (spec["game"], variant, check_id))

    def test_L25_learned_on_A_catches_synthetic_B(self):
        """A: two canvas games opened the context menu at every viewport. B: a DOM-board
        puzzle that prevents it on its canvas but not on a long press on its board."""
        spec = fixture("knowledge", "l25-synthetic-puzzle-board.json")
        for name in ("brick-breaker-worlds-894b4b8.json", "sky-marble-c340631.json"):
            statuses = replay(name)
            for v in CONTRACT["viewports"]:
                self.assertEqual(statuses[f"browser.context-menu:{v['id']}"], "FAIL", (name, v))
        self.assert_generalizes(spec, "browser-qa")

    def test_L26_ui_covers_play_on_a_synthetic_3d_hud(self):
        """A: a 2D objective card over the ball on touch layouts. B: a 3D kart racer's lap
        board over the kart - another render, element, entity and role."""
        spec = fixture("knowledge", "l26-synthetic-3d-kart-hud.json")
        statuses = replay("brick-breaker-worlds-894b4b8.json")
        for vid in ("tablet", "mobile"):
            self.assertEqual(statuses[f"browser.ui-covers-play:{vid}"], "FAIL")
        self.assert_generalizes(spec, "browser-qa")


class LevelLessons(unittest.TestCase):
    @staticmethod
    def clearance(content):
        found = [c for c in realism.judge_layouts(content, RULES, RELEASE)
                 if c["id"] == "level.clearance"]
        return found[0]

    def test_L23_clearance_catches_a_synthetic_platformer(self):
        """A: a brick breaker's ball grew and could not thread its steel rows. B: a
        platformer's hero grew and cannot drop through its one-tile-wide shafts."""
        spec = fixture("knowledge", "l23-synthetic-platformer.json")
        self.assertIn(spec["check"], lesson("L23")["checks"])
        # Game A, its own data file and the grid its tuning declares.
        a = dict(fixture("real", "play-realism", "content-2d-894b4b8.json"), play_geometry={
            "grid": {"key": "rows", "solid": "S",
                     "cell": ["tuning.bricks.brick_width_px", "tuning.bricks.brick_height_px"]},
            "body": {"radius": "tuning.ball-rebound.ball_radius_px"}})
        self.assertEqual(self.clearance(a)["status"], "FAIL")
        # Game B, accepted and regressed.
        accepted = spec["accepted"]
        self.assertEqual(self.clearance(accepted)["status"], spec["expect"]["accepted"])
        regressed = dict(copy.deepcopy(accepted), tuning=spec["regressed_tuning"])
        result = self.clearance(regressed)
        self.assertEqual(result["status"], spec["expect"]["regressed"])
        self.assertEqual(sorted({f["unit"] for f in result["measured"]["failing"]}),
                         spec["expect"]["regressed_units"])
        # And with no clear rate measured against the accepted build, it holds the release.
        gated = [c for c in realism.gate_clearance(realism.judge_layouts(regressed, RULES,
                                                                         RELEASE), RELEASE)
                 if c["id"] == "level.clearance"][0]
        self.assertEqual(gated["status"], "FAIL")
        self.assertTrue(gated["required"])


if __name__ == "__main__":
    unittest.main()

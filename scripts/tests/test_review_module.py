"""The review module's brief (scripts/wgf_review/report.py): what the reviewer is asked.

The isolation, verdict and loop behaviour of the review step are covered in
test_core_agents and test_core_security; this covers the brief's content - the gameplay
lens and the design-fidelity section F2 added.

    python -m unittest discover scripts/tests
"""

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from wgf_review import report  # noqa: E402
from wgf_review.verdict import CONTRACT  # noqa: E402

COMMIT = "a" * 40
DESIGN = {"core_loop": "Dodge, collect, beat the best.",
          "scope": {"tiers": {"mvp": ["Lane switching"]}}}
BUILD_SPEC = {"sections": {
    "rewards": [{"id": "new-best", "feedback": "Best counter bursts; a short fanfare."}],
    "hud": [{"id": "score", "feedback": "Digits roll rather than jump"},
            {"id": "pause-button"}],
    "failure": {"condition": "Touch an obstacle.",
                "feedback": "Hit-stop for 150 ms, screen shake."},
    "tutorial": {"approach": "diegetic", "rationale": "The first rows teach it."},
}, "not_now": [], "omitted": []}
DEV_PLAN = {"milestones": [{"id": "M1"}], "tasks": [
    {"id": "CORE-001", "title": "Boot", "acceptance_criteria": ["Boots through the seam"]},
    {"id": "GAME-001", "title": "Lanes",
     "acceptance_criteria": ["One input moves one lane", "Moves take 120 ms"]}],
    "later": []}


def brief(develop_brief=None, **kwargs):
    args = dict(title_id="demo", commit=COMMIT, baseline="b" * 40, design=DESIGN,
                prototype={}, develop_brief=develop_brief, verdict_path="/tmp/v.json",
                repo="/tmp/repo")
    args.update(kwargs)
    return report.render_brief(**args)


class GameplayLens(unittest.TestCase):
    def test_every_brief_carries_the_lens(self):
        text = brief()
        self.assertIn("### Gameplay lens", text)
        for item in report.GAMEPLAY_LENS:
            self.assertIn(item, text)
        self.assertIn("On an mvp path a failure is a blocker", text)

    def test_the_lens_names_the_defects_players_feel(self):
        lens = " ".join(report.GAMEPLAY_LENS)
        for needle in ("Restart resets everything", "elapsed time", "Pause",
                       "two runs", "data", "allocation", "3 times a second",
                       "user gesture", "@game-over"):
            self.assertIn(needle, lens)

    def test_the_code_checks_and_the_verdict_contract_are_unchanged(self):
        text = brief()
        for needle in ("Defects in the game logic", "tests that assert nothing",
                       "Template rules broken", "Secrets, network calls",
                       "Style preferences are not blockers", "## Your verdict",
                       f"`commit` is `{COMMIT}`, verbatim."):
            self.assertIn(needle, text)
        self.assertEqual(set(CONTRACT), {"verdict", "commit", "blockers", "notes"})
        self.assertLess(text.index("## Look for"), text.index("### Gameplay lens"))
        self.assertLess(text.index("### Gameplay lens"), text.index("## Your verdict"))


class DesignFidelity(unittest.TestCase):
    def test_the_specified_feedback_and_tasks_are_listed(self):
        text = brief({"build_spec": BUILD_SPEC, "dev_plan": DEV_PLAN})
        self.assertIn("## What the design and plan specified", text)
        for needle in ("rewards `new-best`: Best counter bursts; a short fanfare.",
                       "hud `score`: Digits roll rather than jump",
                       "failure: Hit-stop for 150 ms, screen shake.",
                       "tutorial: diegetic - The first rows teach it.",
                       "`CORE-001` Boot: Boots through the seam",
                       "`GAME-001` Lanes: One input moves one lane; Moves take 120 ms",
                       "design-fidelity blocker"):
            self.assertIn(needle, text)
        self.assertNotIn("pause-button", text)  # a HUD element with no feedback to check
        self.assertLess(text.index("## What the design and plan specified"),
                        text.index("## Look for"))

    def test_only_the_parts_the_brief_carries_are_listed(self):
        text = brief({"build_spec": None, "dev_plan": DEV_PLAN})
        self.assertIn("Development plan tasks", text)
        self.assertNotIn("Feedback and teaching", text)
        text = brief({"build_spec": BUILD_SPEC, "dev_plan": None})
        self.assertIn("Feedback and teaching", text)
        self.assertNotIn("Development plan tasks", text)

    def test_a_brief_from_before_f1_adds_nothing(self):
        for develop_brief in (None, {}, {"review_blockers": []}):
            self.assertNotIn("## What the design and plan specified", brief(develop_brief))


if __name__ == "__main__":
    unittest.main()

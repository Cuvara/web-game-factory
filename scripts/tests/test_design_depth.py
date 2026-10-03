"""Design depth: why a player plays longer and comes back (game-design 1.7.0 build_spec.depth;
scripts/wgf_design/depth.py, bars in core/reference/design-depth.yaml).

Both reference games were single-loop arcade prototypes: drop or dodge, fail, retry, with
nothing persisted but a best score and nothing new after the first minute. The design step now
requires every design to state a meta loop that persists more than a score, a goal at every
horizon, content-variety items introduced on a schedule, a first session long enough to show
the loop more than once, and reasons to return - each tiered, an MVP entry resting only on
what the MVP builds.

The regression case is the Goalkeeper Royale design a 2.5.0 run produced (fixture): a 90-second
first session and nothing above the round.

    python -m unittest scripts.tests.test_design_depth
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
from wgf_design import archetypes, depth  # noqa: E402
from wgflib import genre_models  # noqa: E402
from wgflib.workflow.contracts import ArtifactContracts  # noqa: E402
from wgflib.workflow.model import StepOutcome  # noqa: E402

FIXTURE = os.path.join(HERE, "fixtures", "design", "goalkeeper-royale")


def deferring(archetype_id):
    """The archetype's coherent strategy with the worked example's exclusions: metagame,
    skins, leaderboards beyond the best, a level editor, more music tracks."""
    strategy = design_tests.coherent(archetype_id)
    strategy["out_of_scope"] = list(design_tests.load_strategy()["out_of_scope"])
    return design_tests.rehash(strategy)


def design_of(archetype_id, strategy=None, **params):
    result = design_tests.run_step(strategy or design_tests.coherent(archetype_id),
                                   params=dict(params, archetype=archetype_id))
    assert result.outcome == StepOutcome.SUCCESS, result.error
    return result.artifacts[0].content


class EveryArchetypeStatesItsDepth(unittest.TestCase):
    def test_each_archetype_holds(self):
        for archetype_id in archetypes.ARCHETYPES:
            with self.subTest(archetype=archetype_id):
                design = design_of(archetype_id)
                self.assertEqual(depth.check(design), [])
                self.assertEqual(ArtifactContracts()("game-design", design), [])

    def test_each_archetype_holds_under_a_strategy_that_defers_retention(self):
        """A strategy that excludes metagame, skins, leaderboards and a level editor: depth
        that rests on them is optional, named, and the design still holds."""
        for archetype_id in archetypes.ARCHETYPES:
            with self.subTest(archetype=archetype_id):
                design = design_of(archetype_id, deferring(archetype_id))
                self.assertEqual(depth.check(design), [])

    def test_the_numbers_behind_the_reference_games(self):
        rules = depth.load_rules()
        for archetype_id in ("drop-merge", "arena-dodge"):
            with self.subTest(archetype=archetype_id):
                d = design_of(archetype_id)["build_spec"]["depth"]
                kinds = {p["kind"] for p in d["meta_loop"]["persists"]}
                self.assertTrue(kinds - set(rules["meta_loop"]["score_only_kinds"]), kinds)
                self.assertGreaterEqual(len(d["content_schedule"]), 6)
                self.assertGreaterEqual(len({c["kind"] for c in d["content_schedule"]}), 3)
                self.assertEqual({g["horizon"] for g in d["goal_ladder"]}, {"short", "mid", "long"})
                self.assertGreaterEqual(len(d["return_hooks"]), 3)

    def test_the_prototype_builds_its_mvp_units_not_the_meta(self):
        """What the golden ports actually build: the run, its content units and a best score.

        The ramp within a run is MVP depth and the units of that ramp are MVP content - at
        least the genre family's `units.min_mvp` of them, each with its own difficulty
        reading. Stages, specials, coins, the garage and missions stay post-mvp: stated, not
        claimed (game-design 1.9.0 build_spec.content, core/reference/genre-models.yaml).
        """
        families = genre_models.load()["families"]
        for archetype_id in ("drop-merge", "arena-dodge"):
            with self.subTest(archetype=archetype_id):
                design = design_of(archetype_id)
                d = design["build_spec"]["depth"]
                mvp_persists = [p["kind"] for p in d["meta_loop"]["persists"]
                                if p["tier"] == "mvp"]
                self.assertEqual(mvp_persists, ["best-score"])
                self.assertNotEqual(d["meta_loop"]["tier"], "mvp")
                for item in d["content_schedule"]:
                    if item["kind"] in ("special-piece", "power-up", "pickup", "hazard",
                                        "obstacle"):
                        self.assertNotEqual(item["tier"], "mvp", item["id"])
                family = families[design["genre"]["family"]]
                units = [u for u in design["build_spec"]["content"]["units"]
                         if u["tier"] == "mvp"]
                self.assertGreaterEqual(len(units), family["units"]["min_mvp"])
                self.assertEqual(len({u["id"] for u in units}), len(units))
                for unit in units:
                    self.assertTrue(unit["difficulty"], unit["id"])

    def test_first_session_is_the_session_number(self):
        design = design_of("drop-merge")
        self.assertEqual(design["build_spec"]["depth"]["first_session"]["target_s"],
                         design["session"]["first_session_seconds"])


class TheGoalkeeperDesign(unittest.TestCase):
    """The real design: a round, a best, and a 90-second first session."""

    def setUp(self):
        with open(os.path.join(FIXTURE, "game-design.json"), encoding="utf-8") as handle:
            self.design = json.load(handle)
        self.text = "\n".join(depth.check(self.design))

    def test_named_problems(self):
        self.assertIn("build_spec.depth is missing", self.text)
        for part in depth.PARTS:
            self.assertIn(f"depth.{part} is missing", self.text)
        self.assertIn("session.first_session_seconds is 90 s; the bar is 120 s", self.text)

    def test_a_best_score_alone_is_not_a_meta_loop(self):
        spec = self.design["build_spec"]
        spec["depth"] = {"meta_loop": {"statement": "Play rounds and keep the best streak.",
                                       "tier": "mvp", "delivered_by": "score-personal-best",
                                       "persists": [{"kind": "best-score", "what": "Best streak",
                                                     "tier": "mvp"}]}}
        text = "\n".join(depth.check(self.design))
        self.assertIn("depth.meta_loop persists only best-score: a score is not a meta loop", text)


class EachRule(unittest.TestCase):
    def setUp(self):
        self.design = design_of("drop-merge")
        self.depth = self.design["build_spec"]["depth"]

    def problems(self, rules=None):
        return "\n".join(depth.check(self.design, rules))

    def entry(self, part, entry_id):
        return next(e for e in self.depth[part] if e["id"] == entry_id)

    def test_an_mvp_entry_on_a_post_mvp_feature(self):
        self.entry("content_schedule", "bomb")["tier"] = "mvp"
        self.assertIn("depth.content_schedule 'bomb' is mvp but rests on 'special-pieces', which "
                      "is post-mvp: the MVP does not build it", self.problems())

    def test_a_deliverer_that_does_not_exist(self):
        self.entry("return_hooks", "next-stage")["delivered_by"] = "world-map"
        self.assertIn("depth.return_hooks 'next-stage'.delivered_by 'world-map' is not a feature",
                      self.problems())

    def test_an_mvp_entry_that_names_nothing(self):
        del self.entry("goal_ladder", "next-cascade")["delivered_by"]
        self.assertIn("depth.goal_ladder 'next-cascade' is mvp but names nothing that delivers it",
                      self.problems())

    def test_an_optional_entry_needs_no_deliverer(self):
        entry = self.entry("return_hooks", "next-theme")
        entry["tier"] = "optional"
        del entry["delivered_by"]
        self.assertEqual(self.problems(), "")

    def test_a_missing_horizon(self):
        self.depth["goal_ladder"] = [g for g in self.depth["goal_ladder"] if g["horizon"] != "long"]
        self.assertIn("depth.goal_ladder has no long goal", self.problems())

    def test_a_short_goal_the_prototype_does_not_give(self):
        for goal in self.depth["goal_ladder"]:
            if goal["horizon"] == "short":
                goal["tier"] = "post-mvp"
        self.assertIn("depth.goal_ladder has no mvp short goal", self.problems())

    def test_too_little_content(self):
        self.depth["content_schedule"] = self.depth["content_schedule"][:2]
        self.assertIn("depth.content_schedule has 2 item(s); the bar is 4", self.problems())

    def test_content_all_at_once(self):
        for item in self.depth["content_schedule"]:
            item.pop("after_runs", None)
            item["at_s"] = 0
            item["introduced"] = "At the start"
        self.assertIn("introduces its items at 1 distinct point(s); the bar is 3", self.problems())

    def test_no_mvp_variety(self):
        for item in self.depth["content_schedule"]:
            item["tier"] = "optional"
            item.pop("delivered_by", None)
        self.assertIn("depth.content_schedule has 0 mvp item(s); the bar is 1", self.problems())

    def test_the_first_new_thing_arrives_late(self):
        for item in self.depth["content_schedule"]:
            if "at_s" in item:
                item["at_s"] += 60
        self.assertIn("depth.content_schedule's first in-run item arrives at 80 s; the bar is 60 s",
                      self.problems())

    def test_first_session_out_of_step_and_too_short(self):
        self.depth["first_session"]["target_s"] = 60
        text = self.problems()
        self.assertIn("depth.first_session.target_s is 60 s; the bar is 120 s", text)
        self.assertIn("depth.first_session.target_s is 60 s but session.first_session_seconds says",
                      text)

    def test_no_mvp_return_hook(self):
        for hook in self.depth["return_hooks"]:
            if hook["tier"] == "mvp":
                hook["tier"] = "post-mvp"
        self.assertIn("depth.return_hooks has 0 mvp hook(s); the bar is 1", self.problems())

    def test_the_bars_are_data(self):
        rules = copy.deepcopy(depth.load_rules())
        rules["content_schedule"]["min_items"] = 20
        self.assertIn("the bar is 20", self.problems(rules))


class TheStepFailsADesignWithNoDepth(unittest.TestCase):
    def test_the_built_in_author_is_failed_by_name(self):
        saved = copy.deepcopy(archetypes.DEPTH["drop-merge"])
        archetypes.DEPTH["drop-merge"]["meta"]["persists"] = [
            p for p in saved["meta"]["persists"] if p["kind"] == "best-score"]
        archetypes.DEPTH["drop-merge"]["content"] = saved["content"][:2]
        try:
            result = design_tests.run_step(design_tests.coherent("drop-merge"),
                                           params={"archetype": "drop-merge"})
        finally:
            archetypes.DEPTH["drop-merge"] = saved
        self.assertEqual((result.outcome, result.retryable), (StepOutcome.FAILED, False))
        self.assertIn("does not state why a player comes back", result.error)
        self.assertIn("a score is not a meta loop", result.error)
        self.assertIn("depth.content_schedule has 2 item(s)", result.error)

    def test_a_strategy_exclusion_makes_depth_optional_and_says_so(self):
        design = design_of("drop-merge", deferring("drop-merge"))
        hook = next(h for h in design["build_spec"]["depth"]["return_hooks"] if h["id"] == "daily-run")
        self.assertEqual(hook["tier"], "optional")
        self.assertNotIn("delivered_by", hook)
        self.assertIn("(optional: the strategy excludes 'Any metagame or daily-quest layer')",
                      hook["statement"])
        self.assertTrue(any(q.startswith("Depth the strategy excludes is stated as optional")
                            for q in design["open_questions"]))
        # Core words are the game, not an exclusion: "Multiple music tracks" keeps the stage map.
        self.assertIn("stage-map", {f["id"] for f in design["features"]})


class TheAgentAuthorIsToldTheBars(unittest.TestCase):
    def test_the_prompt_names_the_depth_fields(self):
        from wgf_design.agent import PROMPT_DEPTH
        for field in ("build_spec.depth", "meta_loop", "goal_ladder", "content_schedule",
                      "first_session", "return_hooks", "delivered_by", "depth_craft"):
            self.assertIn(field, PROMPT_DEPTH)

    def test_the_craft_guide_exists(self):
        from wgflib import paths
        self.assertTrue(os.path.isfile(os.path.join(paths.CORE, "craft",
                                                    "retention-and-progression.md")))


if __name__ == "__main__":
    unittest.main()

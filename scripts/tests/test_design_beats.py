"""The design a release is held to beyond its counts (scripts/wgf_design/beats.py).

Run from the repository root: python -m unittest scripts.tests.test_design_beats
"""

import copy
import glob
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
for _path in (SCRIPTS, HERE):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from wgf_design import beats, content  # noqa: E402
from wgflib.workflow import StepOutcome  # noqa: E402

BENCHMARK = content.load_benchmark()
TEARDOWNS = ["game-leader-a", "game-leader-b", "game-leader-c"]
DIMENSIONS = ["core_verbs", "signature_moments", "set_pieces_per_group", "content_duration",
              "meta_systems"]
# Designs the validation runs wrote, replayed when the evidence directory is on this machine.
REPLAY = os.environ.get("WGF_REPLAY_DESIGNS", "/mnt/c/Users/duycu/wgf-runs")


def _unit(index, purpose, group, introduces=(), difficulty=0.2, duration=160):
    unit = {"id": f"u{index}", "index": index, "tier": "mvp" if index <= 4 else "post-mvp",
            "purpose": purpose, "group": group, "mechanics": ["move"],
            "difficulty": {"speed": difficulty}, "expected_duration_s": duration,
            "beat": {"claim": f"a first-time player clears u{index} in two attempts",
                     "test": f"the bot's attempts at u{index} exceed two",
                     "decision": {"choice": "take the near gap or wait for the wide one",
                                  "every_s": 3}}}
    if introduces:
        unit["introduces"] = list(introduces)
    if purpose == "climax":
        unit["beat"]["climax"] = {"change": "phase-change", "phases": 2,
                                  "description": "the floor drops away halfway through"}
        unit["beat"]["signature_moment"] = "finale"
    if purpose == "twist":
        unit["beat"]["risk_reward"] = {"line": "the narrow ledge", "payoff": "a gold star"}
        unit["beat"]["signature_moment"] = "chain"
    if purpose == "test":
        unit["beat"]["signature_moment"] = "clear"
    return unit


def good_design():
    """A release-tier design that holds every design.* rule: three worlds of four, each
    teach/breather, test, twist, climax; one mechanic introduced at a time; 1920 s."""
    units, index = [], 0
    plan = [("w1", ["teach", "test", "twist", "climax"], [["move", "jump"], [], ["dash"], []]),
            ("w2", ["breather", "test", "twist", "climax"], [["grab"], [], [], []]),
            ("w3", ["breather", "test", "twist", "climax"], [["swing"], [], [], []])]
    for group, purposes, intros in plan:
        for step, (purpose, intro) in enumerate(zip(purposes, intros)):
            index += 1
            units.append(_unit(index, purpose, group, intro, difficulty=0.1 + 0.05 * step
                               + 0.1 * int(group[1])))
    return {
        "genre": {"family": "platformer", "ending": "finite"},
        "references": {
            "status": "grounded",
            "teardowns": [{"game": g, "name": g} for g in TEARDOWNS],
            "dimensions": [{"dimension": d, "games": list(TEARDOWNS),
                            "observed": f"the leaders' {d} as their records code it",
                            "design": f"this design's {d}, in build_spec.content"}
                           for d in DIMENSIONS]},
        "build_spec": {
            "mechanics": [{"id": "move", "progression_role": "core"},
                          {"id": "jump", "progression_role": "introduced"},
                          {"id": "dash", "progression_role": "introduced"},
                          {"id": "grab", "progression_role": "introduced"},
                          {"id": "swing", "progression_role": "introduced"}],
            "depth": {"meta_loop": {"persists": [{"kind": "stage-progress", "tier": "mvp"},
                                                 {"kind": "unlocks", "tier": "mvp"}]}},
            "content": {
                "quality_tier": "release", "generation": {"mode": "authored"},
                "units": units,
                "secondary_goals": [{"id": "par", "kind": "beat-par",
                                     "description": "finish under the par time",
                                     "par": {"basis": "bot-scaled", "ratio_to_bot": 1.4}}],
                "signature_moments": [
                    {"id": "clear", "kind": "end-of-unit-payoff",
                     "description": "the exit blooms and the stars count up",
                     "trigger": "reaching the exit"},
                    {"id": "chain", "kind": "combo-escalation",
                     "description": "each wall-jump in a row raises the pitch",
                     "trigger": "three wall-jumps without landing"},
                    {"id": "finale", "kind": "rare-spectacle",
                     "description": "the tower collapses behind the player",
                     "trigger": "the climax's phase change"}],
                "meta_systems": [
                    {"system": "unlocks", "decision": "include",
                     "why": "a new world to look forward to after each finale"},
                    {"system": "currency", "decision": "decline",
                     "why": "nothing to buy that a level does not already give"}]}}}


def strategy(teardowns=TEARDOWNS):
    return {"research": {"research_version": 2, "competitors": [
        {"game": g, "name": g, "role": "leader", "depth": "teardown", "claim_refs": []}
        for g in teardowns]}}


def problems(design, strat=None):
    return beats.check(design, strat if strat is not None else strategy(), BENCHMARK)


def ids(out):
    return {p.split("]")[0].strip("[") for p in out["problems"]}


def units(design):
    return design["build_spec"]["content"]["units"]


class GoodDesign(unittest.TestCase):
    def test_a_design_that_states_everything_holds_every_rule(self):
        out = problems(good_design())
        self.assertEqual(out["problems"], [])
        self.assertIsNone(out["research_gap"])
        self.assertEqual([r["criterion_id"] for r in out["results"]],
                         [rule_id for rule_id, _ in beats.RULES])
        self.assertFalse(any(r["breached"] for r in out["results"]))

    def test_the_bars_are_the_benchmark_s_and_every_1_6_0_bar_is_kept(self):
        self.assertEqual(BENCHMARK["version"], "1.7.0")
        bars = beats.design_bars(BENCHMARK, "release")
        self.assertEqual(bars[("beats", "max_mechanics_introduced_per_unit")], 1)
        self.assertEqual(bars[("references", "min_teardowns")], 3)
        self.assertEqual(bars[("designed_play", "finite_min_s")], 1800)
        self.assertEqual(bars[("par_calibration", "min_human_to_bot_ratio")], 1.25)
        # A hypothesis bar never exceeds the confidence a hypothesis claim may carry.
        for section in BENCHMARK["design"].values():
            for entry in section.values():
                if entry.get("basis") == "hypothesis":
                    self.assertLessEqual(entry["confidence"], 0.6)
                    self.assertTrue(entry.get("evidence"))
        # Never lowered: the content bars 1.6.0 stated.
        self.assertEqual(BENCHMARK["content"]["units"]["min_total_designed_s"]["release"], 300)
        self.assertEqual(BENCHMARK["content"]["units"]["min_total"]["release"], 12)


class BeatChart(unittest.TestCase):
    def test_a_teach_unit_introducing_two_mechanics_fails(self):
        design = good_design()
        units(design)[2]["purpose"] = "teach"
        units(design)[2]["introduces"] = ["dash", "grab"]
        units(design)[4].pop("introduces")
        out = problems(design)
        self.assertIn("design.one_mechanic_per_unit", ids(out))
        self.assertTrue(any("introduces 2 mechanics (dash, grab)" in p for p in out["problems"]))

    def test_the_first_unit_may_add_the_core_verb_but_not_a_second_mechanic(self):
        design = good_design()
        self.assertEqual(problems(design)["problems"], [])
        units(design)[0]["introduces"] = ["move", "jump", "dash"]
        units(design)[2].pop("introduces")
        self.assertIn("design.one_mechanic_per_unit", ids(problems(design)))

    def test_a_mechanic_introduced_on_a_climax_fails(self):
        design = good_design()
        units(design)[2].pop("introduces")
        units(design)[3]["introduces"] = ["dash"]
        out = problems(design)
        self.assertTrue(any("on a 'climax' unit" in p for p in out["problems"]),
                        out["problems"])

    def test_a_teach_unit_harder_than_the_breather_before_it_fails(self):
        design = good_design()
        units(design)[5]["purpose"] = "teach"
        units(design)[5]["difficulty"] = {"speed": 0.9}
        self.assertIn("design.teach_eases", ids(problems(design)))

    def test_a_world_without_a_twist_fails(self):
        design = good_design()
        units(design)[6]["purpose"] = "test"
        self.assertIn("design.group_arc", ids(problems(design)))

    def test_a_world_that_does_not_end_in_a_climax_fails(self):
        design = good_design()
        units(design)[11]["purpose"] = "test"
        out = problems(design)
        self.assertIn("design.group_arc", ids(out))
        self.assertTrue(any("w3 ends on u12 (test), not a climax" in p for p in out["problems"]))

    def test_a_climax_that_only_has_its_own_art_fails(self):
        design = good_design()
        units(design)[3]["beat"].pop("climax")
        units(design)[3]["art"] = ["boss-1"]
        out = problems(design)
        self.assertIn("design.climax_changes_state", ids(out))
        self.assertTrue(any("u4 are climax units that declare no change" in p
                            for p in out["problems"]))

    def test_units_without_beats_fail(self):
        design = good_design()
        for unit in units(design):
            unit.pop("beat")
        out = problems(design)
        self.assertIn("design.beat_chart_stated", ids(out))
        self.assertIn("design.risk_reward_offered", ids(out))

    def test_a_decision_once_a_minute_fails(self):
        design = good_design()
        units(design)[1]["beat"]["decision"]["every_s"] = 60
        self.assertIn("design.decision_cadence", ids(problems(design)))

    def test_signature_moments_of_every_kind_built_into_a_unit(self):
        design = good_design()
        design["build_spec"]["content"]["signature_moments"].pop()
        out = problems(design)
        self.assertIn("design.signature_moments", ids(out))
        self.assertTrue(any("0 rare-spectacle" in p for p in out["problems"]))

    def test_a_persisted_meta_system_is_justified(self):
        design = good_design()
        design["build_spec"]["content"]["meta_systems"].pop(0)
        out = problems(design)
        self.assertTrue(any("persists unlocks" in p for p in out["problems"]), out["problems"])

    def test_a_finite_release_short_of_the_market_s_designed_play_fails(self):
        design = good_design()
        for unit in units(design):
            unit["expected_duration_s"] = 25
        self.assertIn("design.designed_play_market", ids(problems(design)))
        design["genre"]["ending"] = "endless"
        self.assertNotIn("design.designed_play_market", ids(problems(design)))

    def test_a_par_scaled_from_the_bot_below_the_ratio_fails(self):
        design = good_design()
        goal = design["build_spec"]["content"]["secondary_goals"][0]
        goal["par"]["ratio_to_bot"] = 1.1
        self.assertIn("design.par_calibrated", ids(problems(design)))
        goal.pop("par")
        self.assertIn("design.par_calibrated", ids(problems(design)))
        goal["par"] = {"basis": "human-playtest"}
        self.assertNotIn("design.par_calibrated", ids(problems(design)))


class References(unittest.TestCase):
    def test_missing_references_at_release_fail(self):
        design = good_design()
        design.pop("references")
        out = problems(design)
        self.assertIn("design.references_grounded", ids(out))
        self.assertIsNone(out["research_gap"])

    def test_a_game_the_research_did_not_tear_down_is_never_a_reference(self):
        design = good_design()
        design["references"]["teardowns"][0]["game"] = "game-remembered"
        out = problems(design)
        self.assertTrue(any("game-remembered, which the research did not tear down" in p
                            for p in out["problems"]), out["problems"])

    def test_a_missing_dimension_fails(self):
        design = good_design()
        design["references"]["dimensions"].pop()
        self.assertTrue(any("no line for meta_systems" in p
                            for p in problems(design)["problems"]))

    def test_too_few_teardowns_in_the_research_routes_to_research(self):
        design = good_design()
        design["references"] = {"status": "unknown", "reason": "the corpus has none",
                                "teardowns": [], "dimensions": []}
        out = problems(design, strategy(TEARDOWNS[:1]))
        # Not the author's to repair: the design said UNKNOWN, and the run goes to research.
        self.assertEqual(out["problems"], [])
        self.assertIn("1 teardown record(s)", out["research_gap"])
        result = next(r for r in out["results"]
                      if r["criterion_id"] == "design.references_grounded")
        self.assertTrue(result["breached"])

    def test_claiming_grounded_references_without_teardowns_is_a_problem(self):
        out = problems(good_design(), strategy([]))
        self.assertIn("design.references_grounded", ids(out))
        self.assertTrue(any("say so: `references` with status 'unknown'" in p
                            for p in out["problems"]))
        self.assertTrue(out["research_gap"])

    def test_the_strategy_s_research_decides_never_the_design_s_own(self):
        design = good_design()
        design["research"] = strategy()["research"]
        out = problems(design, {"research": {"research_version": 2, "competitors": []}})
        self.assertIn("design.references_grounded", ids(out))


class Tiers(unittest.TestCase):
    def test_at_mvp_the_release_bars_are_advice_and_nothing_is_breached(self):
        design = good_design()
        design["build_spec"]["content"]["quality_tier"] = "mvp"
        design.pop("references")
        for unit in units(design):
            unit.pop("beat")
        out = problems(design, strategy([]))
        self.assertEqual(out["problems"], [])
        self.assertIsNone(out["research_gap"])
        self.assertFalse(any(r["breached"] for r in out["results"]))
        self.assertIn("design.references_grounded", out["warnings"])
        self.assertTrue(all(r["note"].startswith(("advisory at tier mvp", "tier mvp"))
                            for r in out["results"]))

    def test_no_tier_or_a_benchmark_pinned_before_1_7_0_holds_nothing(self):
        design = good_design()
        design.pop("references")
        design["build_spec"]["content"].pop("quality_tier")
        out = problems(design, {})
        self.assertEqual(out["problems"], [])
        old = copy.deepcopy(BENCHMARK)
        old.pop("design")
        old["version"] = "1.6.0"
        out = beats.check(good_design() | {"references": None}, strategy([]), old)
        self.assertEqual(out["problems"], [])
        self.assertTrue(all("1.6.0 states no design bars" in r["note"] for r in out["results"]))


class Step(unittest.TestCase):
    """Through the real design step, with the release-tier fixture author."""

    @classmethod
    def setUpClass(cls):
        import test_design_module as design_tests
        import test_design_seed as seeds
        from fixtures.quality import designs  # noqa: F401 - registers the fixture author
        cls.seeds, cls.design_tests = seeds, design_tests

    def run_family(self, competitors):
        strat = self.seeds.strategy_for("platformer")
        strat["research"]["competitors"] = competitors
        return self.seeds.design_for("platformer", strategy=self.design_tests.rehash(strat),
                                     author="release-seed-fixture")

    def test_a_release_design_without_teardowns_blocks_and_routes_to_research(self):
        result = self.run_family([])
        self.assertEqual(result.outcome, StepOutcome.BLOCKED, result.error)
        self.assertEqual(result.route, "research")
        self.assertIn("references are UNKNOWN", result.message)
        self.assertEqual(result.artifacts, [])

    def test_a_release_design_resting_on_three_teardowns_passes(self):
        result = self.run_family([
            {"game": g, "name": g, "role": "leader", "depth": "teardown", "claim_refs": []}
            for g in TEARDOWNS])
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
        design = result.artifacts[0].content
        self.assertEqual(design["references"]["status"], "grounded")
        measured = {r["criterion_id"] for r in design["consistency"]["rule_results"]}
        self.assertTrue({rule_id for rule_id, _ in beats.RULES} <= measured)

    def test_an_mvp_design_is_unchanged(self):
        result = self.seeds.design_for("platformer")
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
        design = result.artifacts[0].content
        self.assertNotIn("references", design)
        self.assertEqual(self.seeds.breached(design), [])


def _replayed():
    pattern = os.path.join(REPLAY, "val-*", "project", ".factory", "workflows", "new-game-*",
                           "artifacts", "game-design", "v*.json")
    return sorted(glob.glob(pattern))


@unittest.skipUnless(_replayed(), "the validation runs' designs are not on this machine")
class Replay(unittest.TestCase):
    """The validation runs' designs, which passed every content count at the release tier."""

    def test_every_release_design_of_the_validation_runs_fails_the_design_bars(self):
        release = 0
        for path in _replayed():
            with open(path, encoding="utf-8") as handle:
                design = json.load(handle)
            tier = ((design.get("build_spec") or {}).get("content") or {}).get("quality_tier")
            if tier != "release":
                continue
            release += 1
            with self.subTest(path=path):
                out = beats.check(design, None, BENCHMARK)
                self.assertIn("design.beat_chart_stated", ids(out))
                self.assertIn("design.climax_changes_state", ids(out))
                self.assertIn("design.designed_play_market", ids(out))
                self.assertTrue(out["research_gap"])
        self.assertGreater(release, 0)

    def test_the_six_mechanic_teach_unit_is_caught_at_release(self):
        found = [p for p in _replayed() if "new-game-20261003-081154" in p and
                 p.endswith("v3.json")]
        if not found:
            self.skipTest("the 2D validation design is not on this machine")
        with open(found[0], encoding="utf-8") as handle:
            design = json.load(handle)
        design["build_spec"]["content"]["quality_tier"] = "release"
        out = beats.check(design, None, BENCHMARK)
        self.assertTrue(any("units[w1-l1].introduces introduces 5 mechanics" in p
                            for p in out["problems"]), out["problems"])


if __name__ == "__main__":
    unittest.main()

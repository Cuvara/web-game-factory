"""The experience contract (game-design 1.5.0 build_spec.experience; scripts/wgf_design/experience.py).

A design states what a first-time player must be able to tell, and how fast: the objective and
where it is shown, how play is lost (and won), how every action is acknowledged, what the
first session teaches and its grace before failure, and the first-30-seconds budget. The design
step holds it to core/reference/experience-rules.yaml and to the rest of the build_spec, and
fails a design that breaks it - or, for an agent author, shows it the problems to repair.

The regression case is real: the Goalkeeper Royale design a 2.5.0 run produced (fixture). The
game built from it lost by itself 2.8 s after play began and never told the player its goal;
stated as that design's own contract, three problems are caught before any code is written.

    python -m unittest scripts.tests.test_design_experience
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
from wgf_design import archetypes, experience  # noqa: E402
from wgflib.workflow.contracts import ArtifactContracts  # noqa: E402
from wgflib.workflow.model import StepOutcome  # noqa: E402

FIXTURE = os.path.join(HERE, "fixtures", "design", "goalkeeper-royale")


def load(name):
    with open(os.path.join(FIXTURE, name), encoding="utf-8") as handle:
        return json.load(handle)


class EveryArchetypeStatesAContractThatHolds(unittest.TestCase):
    def test_each_built_in_archetype(self):
        contracts = ArtifactContracts()
        for archetype_id in archetypes.ARCHETYPES:
            with self.subTest(archetype=archetype_id):
                result = design_tests.run_step(design_tests.coherent(archetype_id),
                                               params={"archetype": archetype_id})
                self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
                design = result.artifacts[0].content
                ex = design["build_spec"]["experience"]
                self.assertEqual(experience.check(design), [])
                self.assertEqual(contracts("game-design", design), [])
                self.assertEqual(ex["goal"]["shown_on"], "play")
                play = next(s for s in design["build_spec"]["screens"] if s["id"] == "play")
                self.assertTrue(any(ex["goal"]["statement"] in e for e in play["elements"]),
                                "a first session starts in play: the objective is on that screen")
                shown = {h.get("metric") for h in design["build_spec"]["hud"]}
                self.assertIn(ex["goal"]["metric"], shown)

    def test_no_key_is_named_when_keyboard_is_out_of_scope(self):
        """The archetype states said "Pause pressed, Esc, or tab hidden" even when the strategy
        excluded desktop and no action had a keyboard binding - the contradiction the
        Goalkeeper design inherited."""
        strategy = design_tests.coherent("one-touch")
        strategy["out_of_scope"] = list(strategy.get("out_of_scope") or []) + [
            "Desktop-specific controls such as keyboard bindings"]
        strategy = design_tests.rehash(strategy)
        result = design_tests.run_step(strategy, params={"archetype": "one-touch"})
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
        design = result.artifacts[0].content
        play = next(s for s in design["build_spec"]["game_states"] if s["id"] == "play")
        self.assertNotIn("Esc", " ".join(e["on"] for e in play["exits"]))
        self.assertEqual(experience.check(design), [])


class TheGoalkeeperDesign(unittest.TestCase):
    """The real design, with the contract its own text states."""

    def setUp(self):
        self.design = load("game-design.json")
        self.strategy = load("title-strategy.json")
        spec = self.design["build_spec"]
        for hud in spec["hud"]:
            if hud["id"] == "lives":
                hud["metric"] = "lives"
            if hud["id"] == "score":
                hud["metric"] = "score"
        spec["experience"] = {
            # Its mechanic rules: "the round's shot target is reached" (8 saves) wins.
            "goal": {"statement": "Save the round's 8 shots before your 3 lives run out.",
                     "metric": "saves", "shown_on": "play"},
            "win": {"condition": "The round's shot target is reached without losing all lives.",
                    "metric": "saves"},
            "lose": {"condition": "A concede empties the last life.", "metric": "lives"},
            "actions": [
                {"action": "dive", "visual": "The keeper dives to the tapped zone.",
                 "max_ack_ms": 100, "updates": ["score"]},
                {"action": "pause", "visual": "The pause menu appears.", "max_ack_ms": 100},
            ],
            # Its tutorial: "The correct zone glows as the attacker leans".
            "onboarding": {"teaches": ["dive"], "grace": {"until": "first-success"},
                           "reveals_answer": True},
            "first_30s": {"first_frame_s": 2,
                          "playable_s": self.design["session"]["time_to_first_play_s"],
                          "first_success_s": 10,
                          "retry_s": spec["failure"]["retry"]["time_to_retry_s"]},
        }

    def test_three_problems_before_any_code_is_written(self):
        problems = experience.check(self.design, self.strategy)
        text = "\n".join(problems)
        self.assertEqual(len(problems), 4, text)
        # The objective's metric is on no HUD element: the player never sees 8 saves.
        self.assertIn("goal relies on metric 'saves'", text)
        self.assertIn("win relies on metric 'saves'", text)
        # The tutorial shows the answer; the strategy must prove understanding without it.
        self.assertIn("onboarding reveals the answer", text)
        # "Pause pressed, Esc, or tab hidden" with no keyboard binding anywhere.
        self.assertIn("names a key, but no MVP action has a keyboard binding", text)

    def test_the_repaired_contract_holds(self):
        spec = self.design["build_spec"]
        spec["hud"].append({"id": "saves", "tier": "mvp", "shows": "Saves this round, out of 8",
                            "anchor": "top-left", "metric": "saves"})
        spec["experience"]["onboarding"]["reveals_answer"] = False
        for state in spec["game_states"]:
            for exit_ in state.get("exits") or []:
                exit_["on"] = exit_["on"].replace("Pause pressed, Esc, or tab hidden",
                                                  "Pause pressed or tab hidden")
        self.assertEqual(experience.check(self.design, self.strategy), [])


class EachRule(unittest.TestCase):
    def setUp(self):
        result = design_tests.run_step(design_tests.coherent("lane-runner"),
                                       params={"archetype": "lane-runner"})
        self.design = result.artifacts[0].content
        self.ex = self.design["build_spec"]["experience"]

    def problems(self):
        return "\n".join(experience.check(self.design))

    def test_a_design_without_a_contract(self):
        del self.design["build_spec"]["experience"]
        self.assertIn("build_spec.experience is missing", self.problems())

    def test_an_unacknowledged_action(self):
        self.ex["actions"] = [a for a in self.ex["actions"] if a["action"] != "move-left"]
        self.assertIn("MVP action 'move-left' has no acknowledgement", self.problems())

    def test_a_slow_acknowledgement(self):
        self.ex["actions"][0]["max_ack_ms"] = 400
        self.assertIn("the bar is 100 ms", self.problems())

    def test_an_untaught_action(self):
        self.ex["onboarding"]["teaches"] = ["move-left"]
        self.assertIn("does not teach MVP action(s) move-right", self.problems())

    def test_a_grace_too_short(self):
        self.ex["onboarding"]["grace"] = {"until": "seconds", "seconds": 3}
        self.assertIn("onboarding grace is 3 s", self.problems())

    def test_an_objective_shown_after_play(self):
        self.ex["goal"]["shown_on"] = "result"
        self.assertIn("the player would meet play before the objective", self.problems())

    def test_a_budget_over_the_bars(self):
        self.ex["first_30s"]["playable_s"] = 25
        self.ex["first_30s"]["retry_s"] = 5
        text = self.problems()
        self.assertIn("first_30s.playable_s is 25 s; the bar is 10 s", text)
        self.assertIn("first_30s.retry_s is 5 s; the bar is 3 s", text)

    def test_a_budget_that_contradicts_the_session(self):
        self.ex["first_30s"]["playable_s"] = self.design["session"]["time_to_first_play_s"] + 1
        self.assertIn("but session.time_to_first_play_s says", self.problems())

    def test_a_metric_no_hud_shows(self):
        self.ex["actions"][0]["updates"] = ["combo"]
        self.assertIn("relies on metric 'combo', which no MVP hud element shows", self.problems())


class TheStepFailsADesignThatBreaksIt(unittest.TestCase):
    def test_a_broken_contract_fails_the_built_in_author_by_name(self):
        from wgf_design import authors

        original = authors.ArchetypeAuthor._experience

        def broken(ex, actions, *args):
            contract = original(ex, actions, *args)
            contract["onboarding"]["teaches"] = []
            return contract
        authors.ArchetypeAuthor._experience = staticmethod(broken)
        try:
            result = design_tests.run_step(design_tests.coherent("lane-runner"),
                                           params={"archetype": "lane-runner"})
        finally:
            authors.ArchetypeAuthor._experience = staticmethod(original)
        self.assertEqual((result.outcome, result.retryable), (StepOutcome.FAILED, False))
        self.assertIn("experience contract does not hold", result.error)
        self.assertIn("does not teach", result.error)


if __name__ == "__main__":
    unittest.main()

"""Feature evaluation (WS-5): no feature the brief, strategy or genre names drops silently.

The two validation runs each lost a feature the person's brief asked for: the 2D brief's
endless mode was tiered optional without a word, and the 3D marble brief's time trial was
never listed (docs/quality-gap-audit-2026-10.md finding 6). These tests hold the design step
to core/reference/feature-catalogue.yaml (scripts/wgf_design/features.py): those briefs now
produce evaluated features, a design that drops one fails, an evaluation agrees with its tier
and the platforms, a cut is out of scope with its reason, and G4 is shown the cut list
(wgflib.gate_evidence).

Deterministic and offline. Run from the repository root:

    python -m unittest scripts.tests.test_design_features
"""

import copy
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, HERE)

from test_design_module import rehash, run_step, variant  # noqa: E402
from test_game_idea import MARBLE  # noqa: E402
from wgf_design import authors, compose  # noqa: E402
from wgf_design import features as feature_check  # noqa: E402
from wgf_design.agent import _feature_candidates  # noqa: E402
from wgf_design.platforms import Platform  # noqa: E402
from wgflib import gate_evidence, genre_models, paths  # noqa: E402
from wgflib.workflow import checkpoint  # noqa: E402
from wgflib.workflow.contracts import ArtifactContracts  # noqa: E402
from wgflib.workflow.definition import load_definition  # noqa: E402
from wgflib.workflow.model import StepOutcome  # noqa: E402
from wgflib.yamllite import load_file  # noqa: E402

# The 2D validation run's brief (its params.idea), verbatim.
BRICKS = ("A 2D brick-breaker arcade game (PixiJS): paddle and ball with satisfying juice, 4 "
          "themed worlds of hand-designed levels with new brick types and hazards introduced "
          "per world, power-ups (multi-ball, wide paddle, laser), star rating per level, level "
          "unlocks and saved progress, boss levels, and an endless mode for replay. Desktop "
          "and mobile touch.")

CATALOGUE = feature_check.load_catalogue()


def platform(pid, role="required", **capabilities):
    return Platform(pid, role, "1.0.0", {"capabilities": dict(capabilities)})


def by_catalogue(design, cid):
    return [f for f in design["features"] if f.get("catalogue") == cid]


class TheCatalogue(unittest.TestCase):
    def test_every_entry_is_complete_and_names_every_family(self):
        families = set((genre_models.load().get("families") or {}).keys())
        self.assertTrue(families)
        ids = [e["id"] for e in CATALOGUE["features"]]
        self.assertEqual(len(ids), len(set(ids)), "duplicate catalogue ids")
        levels = {"low", "medium", "high"}
        for entry in CATALOGUE["features"]:
            with self.subTest(entry=entry["id"]):
                self.assertRegex(entry["id"], r"^[a-z0-9]+(-[a-z0-9]+)*$")
                self.assertTrue(entry.get("name") and entry.get("description"))
                self.assertTrue(entry.get("terms"))
                self.assertEqual(set(entry["families"]), families)
                self.assertLessEqual(set(entry["families"].values()),
                                     {"expected", "fits", "poor"})
                self.assertIn(entry["player_value"], levels)
                self.assertIn(entry["qa_cost"], levels)
                self.assertIn(entry["monetization_impact"], levels | {"none"})
                self.assertGreaterEqual(entry["cost_h"], 0)

    def test_platform_capabilities_are_ones_the_profiles_state(self):
        stated = set()
        for name in os.listdir(paths.PLATFORMS):
            if name.endswith(".yaml"):
                stated |= set((load_file(os.path.join(paths.PLATFORMS, name))
                               .get("capabilities") or {}).keys())
        for entry in CATALOGUE["features"]:
            need = entry.get("platform")
            if need:
                self.assertIn(need["capability"], stated, entry["id"])
                self.assertIn(need["fallback"], ("local", "none"), entry["id"])

    def test_every_family_expects_something_and_no_term_is_a_bare_generic_word(self):
        for family in genre_models.load()["families"]:
            self.assertTrue(feature_check.candidates({}, family, CATALOGUE), family)
        for entry in CATALOGUE["features"]:
            for term in entry["terms"]:
                self.assertNotIn(term, ("mode", "best", "level", "game", "play", "profile"))


class BriefFeaturesAreRecognised(unittest.TestCase):
    def test_the_marble_brief_names_its_time_trial(self):
        named = feature_check.named(MARBLE, CATALOGUE)
        self.assertIn("time-trial", named)
        self.assertEqual({"worlds", "star-rating", "unlocks", "local-save", "statistics",
                          "time-trial"} - set(named), set())

    def test_the_2d_brief_names_its_endless_mode(self):
        named = feature_check.named(BRICKS, CATALOGUE)
        self.assertEqual(named.get("endless-mode"), "endless mode")
        self.assertEqual({"worlds", "star-rating", "unlocks", "local-save"} - set(named), set())

    def test_hyphens_and_case_do_not_hide_a_feature(self):
        self.assertIn("time-trial", feature_check.named("A Time-Trial mode", CATALOGUE))
        self.assertIn("daily-challenge", feature_check.named("one DAILY-CHALLENGE", CATALOGUE))
        self.assertNotIn("leaderboard", feature_check.named("a board game", CATALOGUE))

    def test_an_exclusion_excludes_the_feature_it_names_first(self):
        text = "Leaderboards beyond the personal best"
        self.assertEqual(feature_check.first_named(text, CATALOGUE), "leaderboard")

    def test_brief_beats_strategy_beats_family(self):
        strategy = {"brief": "with an endless mode", "mvp": ["a time trial", "endless mode"]}
        sources = {c["id"]: c["source"]
                   for c in feature_check.candidates(strategy, "racing", CATALOGUE)}
        self.assertEqual(sources["endless-mode"], "brief")
        self.assertEqual(sources["time-trial"], "strategy")
        self.assertEqual(sources["statistics"], "catalogue")  # racing expects it


class TheRegressionBriefs(unittest.TestCase):
    """The built-in author, given each validation brief: the brief's mode is an evaluated
    feature in the design, and the cut list carries what was cut."""

    def design_for(self, brief):
        result = run_step(variant(brief=brief))
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
        return result.artifacts[0].content

    def assert_evaluated(self, design, cid):
        carried = by_catalogue(design, cid)
        self.assertEqual(len(carried), 1, f"{cid} is not one evaluated feature")
        feature = carried[0]
        self.assertEqual(feature["source"], "brief")
        self.assertIn(feature["evaluation"]["decision"], ("include", "later", "cut"))
        self.assertTrue(feature["evaluation"]["reason"].strip())
        return feature

    def test_marble_time_trial_is_evaluated(self):
        design = self.design_for(MARBLE)
        feature = self.assert_evaluated(design, "time-trial")
        self.assertEqual(feature["tier"], "optional")
        self.assertIn(feature["name"], design["scope"]["tiers"]["future"])
        self.assertIn("time trial", feature["evaluation"]["reason"])
        self.assertEqual(ArtifactContracts()("game-design", design), [])

    def test_bricks_endless_mode_is_evaluated(self):
        design = self.design_for(BRICKS)
        self.assert_evaluated(design, "endless-mode")
        for cid in ("worlds", "star-rating", "unlocks", "local-save"):
            self.assert_evaluated(design, cid)
        results = {r["criterion_id"]: r for r in design["consistency"]["rule_results"]}
        self.assertFalse(results["features.brief_accounted"]["breached"])
        self.assertIn("endless-mode", results["features.brief_accounted"]["measured"])
        self.assertEqual(design["consistency"]["feature_catalogue"]["id"], "feature-catalogue")

    def test_a_strategy_exclusion_is_a_cut_with_its_reason_in_out_of_scope(self):
        design = self.design_for(BRICKS)
        (leaderboard,) = by_catalogue(design, "leaderboard")
        self.assertEqual(leaderboard["evaluation"]["decision"], "cut")
        out = {o["item"]: o["why_excluded"] for o in design["scope"]["tiers"]["out_of_scope"]}
        self.assertEqual(out[leaderboard["name"]], leaderboard["evaluation"]["reason"])
        self.assertNotIn(leaderboard["name"], design["scope"]["tiers"]["future"])
        # The personal best the exclusion keeps is not cut with it.
        (stats,) = by_catalogue(design, "statistics")
        self.assertNotEqual(stats["evaluation"]["decision"], "cut")


class SilentDropsFail(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.strategy = variant(brief=MARBLE)
        result = run_step(cls.strategy)
        cls.design = result.artifacts[0].content

    def dropped(self, cid):
        design = copy.deepcopy(self.design)
        design["features"] = [f for f in design["features"] if f.get("catalogue") != cid]
        return design

    def test_dropping_the_time_trial_is_a_brief_problem(self):
        problems, results = feature_check.check(self.dropped("time-trial"), self.strategy)
        self.assertTrue(any("time-trial" in p and "brief names" in p for p in problems),
                        problems)
        breached = {r["criterion_id"] for r in results if r["breached"]}
        self.assertEqual(breached, {"features.brief_accounted"})

    def test_an_unevaluated_brief_feature_is_a_problem(self):
        design = copy.deepcopy(self.design)
        for feature in design["features"]:
            if feature.get("catalogue") == "time-trial":
                del feature["evaluation"]
        problems, _ = feature_check.check(design, self.strategy)
        self.assertTrue(any("source brief but no evaluation" in p for p in problems))
        self.assertTrue(any("catalogue time-trial" in p for p in problems))

    def test_a_brief_feature_recorded_as_the_designers_own_is_a_problem(self):
        design = copy.deepcopy(self.design)
        by_catalogue(design, "time-trial")[0]["source"] = "design"
        problems, _ = feature_check.check(design, self.strategy)
        self.assertTrue(any("its source is brief" in p for p in problems), problems)

    def test_the_design_step_fails_an_author_that_drops_it(self):
        class Dropping(authors.ArchetypeAuthor):
            name = "dropping"

            def draft(self, brief):
                draft = super().draft(brief)
                draft["features"] = [f for f in draft["features"]
                                     if f.get("catalogue") != "time-trial"]
                return draft

        authors.register_author("dropping", Dropping)
        self.addCleanup(authors.AUTHORS.pop, "dropping", None)
        result = run_step(self.strategy, params={"author": "dropping"})
        self.assertEqual(result.outcome, StepOutcome.FAILED)
        self.assertIn("does not account for the features", result.error)
        self.assertIn("time-trial", result.error)
        self.assertEqual(result.artifacts, [])


class DecisionsAgree(unittest.TestCase):
    def design(self, *features, out_of_scope=()):
        return {"features": list(features), "genre": {},
                "scope": {"tiers": {"out_of_scope": list(out_of_scope)}}}

    def feature(self, tier, decision, cid="time-trial", **evaluation):
        return {"id": "f", "name": "Time trial", "tier": tier, "description": "-",
                "source": "design", "catalogue": cid,
                "evaluation": dict({"decision": decision, "reason": "because"}, **evaluation)}

    def test_include_is_built_and_later_or_cut_is_optional(self):
        for tier, decision, bad in (("optional", "include", True), ("post-mvp", "include", False),
                                    ("mvp", "later", True), ("optional", "later", False),
                                    ("post-mvp", "cut", True)):
            with self.subTest(tier=tier, decision=decision):
                out = [{"item": "Time trial", "why_excluded": "x"}] if decision == "cut" else []
                problems, _ = feature_check.check(
                    self.design(self.feature(tier, decision), out_of_scope=out), {})
                self.assertEqual(bool(problems), bad, problems)

    def test_a_cut_must_be_out_of_scope_and_finalize_puts_it_there(self):
        problems, _ = feature_check.check(self.design(self.feature("optional", "cut")), {})
        self.assertTrue(any("not in scope.tiers.out_of_scope" in p for p in problems))
        draft = {"features": [self.feature("optional", "cut"),
                              dict(self.feature("optional", "later"), id="g", name="Endless")],
                 "scope": {"out_of_scope": []},
                 "build_spec": {"sdk_touchpoints": [], "monetization_touchpoints": []}}
        design = compose.finalize(draft, [], "demo")
        self.assertEqual(design["scope"]["tiers"]["out_of_scope"],
                         [{"item": "Time trial", "why_excluded": "because"}])
        self.assertEqual(design["scope"]["tiers"]["future"], ["Endless"])

    def test_an_unknown_catalogue_id_is_a_problem(self):
        problems, _ = feature_check.check(
            self.design(self.feature("post-mvp", "include", cid="hover-boots")), {})
        self.assertTrue(any("hover-boots" in p for p in problems))


class PlatformSupport(unittest.TestCase):
    def leaderboard(self, decision="include", tier="post-mvp", **evaluation):
        return {"features": [{"id": "lb", "name": "Leaderboard", "tier": tier,
                              "description": "-", "source": "design",
                              "catalogue": "leaderboard",
                              "evaluation": dict({"decision": decision, "reason": "r"},
                                                 **evaluation)}],
                "genre": {}, "scope": {"tiers": {"out_of_scope": [
                    {"item": "Leaderboard", "why_excluded": "r"}]}}}

    def test_support_is_computed_from_the_required_profiles(self):
        entry = {e["id"]: e for e in CATALOGUE["features"]}
        both = [platform("a", leaderboards=True), platform("b", leaderboards=False)]
        self.assertEqual(feature_check.platform_support(entry["leaderboard"], both), "some")
        self.assertEqual(feature_check.platform_support(entry["leaderboard"], both[:1]), "all")
        self.assertEqual(feature_check.platform_support(entry["leaderboard"], both[1:]), "none")
        self.assertEqual(feature_check.platform_support(entry["achievements"], both[1:]),
                         "local")
        self.assertEqual(feature_check.platform_support(entry["time-trial"], both[1:]), "all")
        optional = [platform("c", role="optional", leaderboards=False)]
        self.assertEqual(feature_check.platform_support(entry["leaderboard"],
                                                        both[:1] + optional), "all")

    def test_an_included_leaderboard_a_required_portal_lacks_is_refused(self):
        lacking = [platform("a", leaderboards=True), platform("b", leaderboards=False)]
        problems, results = feature_check.check(self.leaderboard(), {}, lacking)
        self.assertTrue(any("b (required) has no leaderboards" in p for p in problems))
        self.assertIn("features.platform_supported",
                      {r["criterion_id"] for r in results if r["breached"]})
        problems, _ = feature_check.check(self.leaderboard("cut", "optional"), {}, lacking)
        self.assertEqual(problems, [])

    def test_a_stated_support_that_contradicts_the_profiles_is_a_problem(self):
        lacking = [platform("b", leaderboards=False)]
        problems, _ = feature_check.check(
            self.leaderboard("cut", "optional", platform_support="all"), {}, lacking)
        self.assertTrue(any("profiles say none" in p for p in problems), problems)

    def test_the_built_in_author_cuts_what_no_required_portal_runs(self):
        features = []
        feature_check.evaluate_for_author(
            features, {"brief": "with a global leaderboard"}, None,
            [platform("b", leaderboards=False)], catalogue=CATALOGUE)
        (lb,) = features
        self.assertEqual((lb["catalogue"], lb["tier"], lb["evaluation"]["decision"]),
                         ("leaderboard", "optional", "cut"))
        self.assertEqual(lb["evaluation"]["platform_support"], "none")


class TheFamilyIsEvaluatedNotAdded(unittest.TestCase):
    def test_expected_features_are_evaluated_and_none_is_built_because_a_list_has_it(self):
        result = run_step(variant())
        design = result.artifacts[0].content
        family = design["genre"]["family"]
        expected = [e["id"] for e in CATALOGUE["features"]
                    if e["families"][family] == "expected"]
        self.assertTrue(expected)
        for cid in expected:
            (feature,) = by_catalogue(design, cid)
            self.assertTrue(feature["evaluation"]["reason"])
            if feature["source"] == "catalogue":
                # Proposed by the catalogue, not built by the archetype: never included.
                self.assertNotEqual(feature["evaluation"]["decision"], "include")
                self.assertEqual(feature["tier"], "optional")

    def test_the_agent_request_carries_the_candidates_with_platform_support(self):
        candidates = _feature_candidates({"brief": BRICKS}, "arcade",
                                         [platform("y", leaderboards=False)])
        by_id = {c["id"]: c for c in candidates}
        self.assertEqual(by_id["endless-mode"]["source"], "brief")
        self.assertEqual(by_id["leaderboard"]["source"], "catalogue")
        self.assertEqual(by_id["leaderboard"]["platform_support"], "none")
        self.assertIn("cost_h", by_id["endless-mode"]["estimate"])


class DailyChallengeHook(unittest.TestCase):
    def test_daily_challenge_is_a_retention_hook_the_schema_accepts(self):
        result = run_step(variant())
        design = copy.deepcopy(result.artifacts[0].content)
        design["retention"]["hooks"] = ["daily_challenge"]
        self.assertEqual(ArtifactContracts()("game-design", rehash(design)), [])
        design["retention"]["hooks"] = ["weekly_raid"]
        self.assertNotEqual(ArtifactContracts()("game-design", rehash(design)), [])


class G4ShowsTheCutList(unittest.TestCase):
    """What a waiting G4 (and G3) prints beside the kill criteria: read from the design's
    `features[].evaluation` by field (wgflib.gate_evidence), never by step type."""

    @classmethod
    def setUpClass(cls):
        cls.design = run_step(variant(brief=BRICKS)).artifacts[0].content
        inputs = {t: {} for t in checkpoint.required_artifacts("G4")}
        inputs["game-design"] = cls.design
        cls.evidence = gate_evidence.summarize(inputs)
        cls.lines = gate_evidence.render(cls.evidence)

    def test_the_cut_and_deferred_features_are_listed_with_their_reasons(self):
        (entry,) = self.evidence["features"]
        self.assertEqual(entry["artifact"], "game-design")
        (leaderboard,) = by_catalogue(self.design, "leaderboard")
        self.assertIn({"name": leaderboard["name"], "source": leaderboard["source"],
                       "reason": leaderboard["evaluation"]["reason"]}, entry["cut"])
        self.assertIn("Endless mode", [f["name"] for f in entry["later"]])
        text = "\n".join(self.lines)
        self.assertIn("features cut from the design (game-design):", text)
        self.assertIn("features deferred, not built (game-design):", text)
        self.assertIn("    - Endless mode (brief): The brief names it", text)

    def test_a_brief_feature_left_out_is_called_out(self):
        warning = [line for line in self.lines if line.startswith("  ! the brief asked for")]
        self.assertEqual(len(warning), 1)
        self.assertIn("Endless mode", warning[0])
        self.assertIn("Themed worlds", warning[0])

    def test_g4_is_decided_on_the_design_that_carries_them(self):
        self.assertIn("game-design", checkpoint.required_artifacts("G4"))
        self.assertIn("game-design",
                      load_definition("new-game").step("prototype-review").inputs)

    def test_a_design_with_nothing_left_out_shows_nothing(self):
        self.assertIsNone(gate_evidence.summarize({"game-design": {"features": [
            {"id": "a", "name": "A", "tier": "mvp", "description": "-",
             "evaluation": {"decision": "include", "reason": "r"}}]}}))


if __name__ == "__main__":
    unittest.main()

"""The strategy module (scripts/wgf_strategy): opportunity in, draft title-strategy out.

  Planner          the domain rules, as a pure function: platforms, monetization, scope,
                   criteria, risks and assumptions, and the refusals
  StepUnit         `execute` with a fake inputs and context: each StepResult it can return
  ThroughEngine    registered from config and run in the real new-game workflow, with the
                   other steps as placeholders: it stops at strategy-review (G2), design
                   consumes its output after approval, and a rejection blocks the run
  Schema           emitted artifacts validate with ajv against title-strategy.schema.json

Deterministic and offline: fixed clock, profiles from core/reference/platforms/, no network.
The ajv test uses the cached npx packages CLAUDE.md names and skips if they cannot run
(or with WGF_SKIP_AJV=1).

Run from the web-game-factory repository root:

    python -m unittest discover scripts/tests
"""

import copy
import datetime
import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
sys.path.insert(0, SCRIPTS)

from wgf_strategy import Policy, StrategyRefused, StrategyStep, plan_strategy  # noqa: E402
from wgf_strategy import planner  # noqa: E402
from wgf_strategy.profiles import load_profiles  # noqa: E402
from wgflib import paths  # noqa: E402
from wgflib.guards import GuardContext, evaluate_guard  # noqa: E402
from wgflib.hashing import content_hash  # noqa: E402
from wgflib.workflow.api import RunRequest, WorkflowAPI  # noqa: E402
from wgflib.workflow.config import FactoryConfig  # noqa: E402
from wgflib.workflow.contracts import ArtifactContracts  # noqa: E402
from wgflib.workflow.definition import StepDefinition, load_definition  # noqa: E402
from wgflib.workflow.model import ArtifactRef, RunStatus, StepOutcome, StepStatus  # noqa: E402
from wgflib.workflow.step import StepInputs  # noqa: E402

OPPORTUNITY = os.path.join(paths.OPPORTUNITIES, "opp-001", "opportunity.json")


def schema_version(artifact_type):
    """The contract's own version: a step writes it, so the test reads it rather than pinning
    a number every minor bump has to come back and edit."""
    with open(os.path.join(paths.ARTIFACTS, f"{artifact_type}.schema.json"),
              encoding="utf-8") as handle:
        return str(json.load(handle)["x-wgf"]["version"])

FIXED = datetime.datetime(2026, 9, 1, 10, 0, 0, tzinfo=datetime.timezone.utc)
PROFILES = load_profiles()

# Every placeholder step except strategy, so the real module runs inside new-game.
PLACEHOLDERS = textwrap.dedent('''
    from wgflib.workflow import mock


    def register(registry):
        for step_class in mock.MOCK_STEPS:
            if step_class.type != "strategy":
                registry.register(step_class.type, step_class)
''')


def opportunity(**changes):
    with open(OPPORTUNITY, encoding="utf-8") as handle:
        body = json.load(handle)
    for dotted, value in changes.items():
        target = body
        keys = dotted.split("__")
        for key in keys[:-1]:
            target = target.setdefault(key, {})
        target[keys[-1]] = value
    return body


def plan(opp=None, policy=None, profiles=None):
    return plan_strategy(opp or opportunity(), PROFILES if profiles is None else profiles,
                         "neon-drift", policy)


def fv(value, tier="derived", refs=("claim-fixture",), source="corpus"):
    """A research facet value, as the opportunity's cell carries one."""
    out = {"value": value, "tier": tier, "source": source}
    if tier in ("observed", "derived"):
        out["claim_refs"] = list(refs)
    return out


def research_block(constraints=None, genre="match-3", family="puzzle", genre_model=None):
    """The smallest Research V2 block the planner reads: the cell's genre and family, the
    buildability, and - when the scan coded one - the content shape design is held to."""
    block = {
        "research_version": 2, "report_id": "rr-fixture", "opportunity_id": "opp-001",
        "origin": "supply-gap", "status": "selected", "summary": "FIXTURE opportunity.",
        "cell": {"genre": fv(genre), "family": fv(family)},
        "basis": {"claim_refs": [], "evidence_backed": True, "thesis": "claim-thesis",
                  "statement": "FIXTURE"},
        "market": [], "competitors": [], "benchmarks": [], "patterns": {"adopt": []},
        "monetization": {"placements": [], "platform_support": []},
        "production": {"dimension": "2d", "complexity": "s", "tier": "hypothesis",
                       "drivers": ["FIXTURE"]},
        "capability": {"buildable": True, "missing": [], "reason": "FIXTURE",
                       "genre_model": genre_model},
        "audience": {}, "risks": [],
        "confidence": {"evidence_coverage": 0.5, "weakest_tier": "hypothesis",
                       "unknown_facets": [], "fixture_evidence": True},
        "claim_refs": [],
    }
    if constraints is not None:
        block["design_constraints"] = constraints
    return block


# -- the planner -------------------------------------------------------------------------


class Planner(unittest.TestCase):
    def test_every_requested_decision_is_made(self):
        body = plan()
        concept, scope = body["concept"], body["production_scope"]
        self.assertTrue(concept["gameplay_direction"])
        self.assertEqual(concept["control_scheme"], "one-touch")
        self.assertTrue(concept["replayability"].startswith("Score chase"))
        self.assertEqual(body["audience"]["type"], "casual")
        self.assertEqual(body["session"]["target_seconds"], 210)
        self.assertEqual(body["monetization"]["class"], "rewarded-led")
        self.assertEqual(scope["technical_complexity"], "medium")  # audio sync
        self.assertEqual(scope["asset_complexity"], "low")
        self.assertEqual(scope["estimate_days"], 11)
        self.assertEqual(body["timebox_days"], 11)
        for key in ("mvp", "out_of_scope", "prototype_must_prove", "success_criteria",
                    "kill_criteria", "risks", "assumptions"):
            self.assertTrue(body[key], key)

    def test_one_required_platform_chosen_by_audience_fit(self):
        body = plan()
        roles = {p["id"]: p["role"] for p in body["platform_set"]}
        self.assertEqual(roles, {"yandex": "required", "crazygames": "optional"})
        for entry in body["platform_set"]:
            self.assertEqual(entry["profile_version"], PROFILES[entry["id"]]["version"])

        # The same concept for a US audience: CrazyGames fits better and becomes primary.
        us = plan(opportunity(audience__regions=["us", "gb"]))
        roles = {p["id"]: p["role"] for p in us["platform_set"]}
        self.assertEqual(roles, {"yandex": "optional", "crazygames": "required"})

    def test_sdk_requirements_and_constraints_come_from_the_profiles(self):
        compat = {c["id"]: c for c in plan()["platform_compatibility"]}
        yandex = compat["yandex"]
        self.assertEqual(yandex["sdk"]["id"], "yandex")
        for feature in ("init", "loading-progress", "rewarded", "interstitial", "cloud-save"):
            self.assertIn(feature, yandex["sdk"]["features"])
        self.assertIn("Locales required: ru", yandex["constraints"])
        self.assertIn("Bundle at most 100 MB", yandex["constraints"])

        standalone = plan(opportunity(candidate_platforms=["generic-web"],
                                      monetization_hypothesis={"primary": "none"}))
        self.assertEqual(standalone["platform_compatibility"][0]["sdk"],
                         {"id": "none", "features": []})
        self.assertEqual(standalone["monetization"], {"class": "none", "placements": []})

    def test_a_platform_that_cannot_carry_the_monetization_is_left_out(self):
        body = plan(opportunity(candidate_platforms=["gamevui", "yandex"]))
        self.assertEqual([p["id"] for p in body["platform_set"]], ["yandex"])
        gamevui = next(c for c in body["platform_compatibility"] if c["id"] == "gamevui")
        self.assertFalse(gamevui["compatible"])
        self.assertTrue(any("rewarded" in issue for issue in gamevui["issues"]))
        self.assertTrue(any("gamevui" in item for item in body["out_of_scope"]))

    def test_unsupported_monetization_is_reclassified_not_ignored(self):
        body = plan(opportunity(candidate_platforms=["crazygames", "poki"],
                                monetization_hypothesis={"primary": "iap",
                                                         "secondary": ["rewarded"]}))
        self.assertEqual(body["monetization"]["class"], "rewarded-led")
        self.assertTrue(any("reclassified" in r["description"] for r in body["risks"]))

    def test_unknown_platforms_are_recorded_and_dropped(self):
        body = plan(opportunity(candidate_platforms=["nowhere", "yandex"]))
        self.assertEqual([p["id"] for p in body["platform_set"]], ["yandex"])
        self.assertFalse(body["platform_compatibility"][0]["compatible"])

    def test_a_persons_platform_choice_replaces_the_ranking(self):
        # The fit ranking makes yandex required for this audience; a person chose otherwise.
        body = plan_strategy(opportunity(), PROFILES, "neon-drift", None,
                             platforms=["crazygames", "yandex"])
        self.assertEqual([(p["id"], p["role"]) for p in body["platform_set"]],
                         [("crazygames", "required"), ("yandex", "optional")])
        required = next(p for p in body["platform_set"] if p["role"] == "required")
        self.assertIn("chosen first by a person", required["rationale"])
        self.assertTrue(any("chosen by a person" in d for d in body["production_scope"]["scope_decisions"]))

    def test_a_chosen_platform_need_not_be_a_candidate_but_must_have_a_profile(self):
        body = plan_strategy(opportunity(candidate_platforms=["yandex"]), PROFILES,
                             "neon-drift", None, platforms=["crazygames"])
        self.assertEqual([p["id"] for p in body["platform_set"]], ["crazygames"])
        with self.assertRaises(StrategyRefused):
            plan_strategy(opportunity(), PROFILES, "neon-drift", None, platforms=["nowhere"])

    def test_a_platform_choice_keeps_the_compatibility_checks_and_the_cap(self):
        # gamevui cannot carry rewarded: chosen first, it is still left out, and said so.
        body = plan_strategy(opportunity(), PROFILES, "neon-drift", None,
                             platforms=["gamevui", "yandex"])
        self.assertEqual([(p["id"], p["role"]) for p in body["platform_set"]],
                         [("yandex", "required")])
        self.assertTrue(any("gamevui" in r["description"] for r in body["risks"]))
        with self.assertRaises(StrategyRefused):
            plan_strategy(opportunity(), PROFILES, "neon-drift", Policy(max_platforms=1),
                          platforms=["yandex", "crazygames"])

    def test_a_malformed_platform_choice_is_refused(self):
        for value in ([], "yandex", ["yandex", "yandex"], [""]):
            with self.assertRaises(StrategyRefused, msg=repr(value)):
                plan_strategy(opportunity(), PROFILES, "neon-drift", None, platforms=value)

    def test_platform_sprawl_is_capped(self):
        body = plan(opportunity(candidate_platforms=["yandex", "crazygames", "poki"]),
                    Policy(max_platforms=2))
        self.assertEqual(len(body["platform_set"]), 2)
        self.assertEqual(sum(p["role"] == "required" for p in body["platform_set"]), 1)
        self.assertTrue(any(i.startswith("Platforms beyond the set") for i in body["out_of_scope"]))

    def test_scope_is_fitted_to_the_timebox_not_the_other_way_round(self):
        body = plan(opportunity(estimates={"dev_speed_days": 19, "scope_complexity": "l",
                                           "session_seconds": 900}))
        self.assertEqual(body["timebox_days"], 14)
        self.assertEqual(body["production_scope"]["estimate_days"], 19)
        self.assertEqual(body["session"]["target_seconds"], 300)
        decisions = " ".join(body["production_scope"]["scope_decisions"])
        self.assertIn("timebox is held at 14", decisions)
        self.assertIn("Target session cut", decisions)

        small = plan(opportunity(estimates={"dev_speed_days": 3}))
        self.assertEqual(small["timebox_days"], 7)

    def test_a_session_is_never_shorter_than_the_required_interstitial_interval(self):
        # Design's blocking rule `interstitial_interval_fits_session` would refuse it after G2.
        short = {"session_seconds": 90}
        us = plan(opportunity(estimates=short, audience__regions=["us", "gb"]))
        self.assertEqual(us["session"]["target_seconds"], 180)  # CrazyGames: 180s
        self.assertIn("Target session raised from 120s to 180s: CrazyGames",
                      " ".join(us["production_scope"]["scope_decisions"]))
        self.assertTrue(any(a["statement"] == "Players sustain a 180-second session"
                            for a in us["assumptions"]))
        # Yandex (60s) holds no bar above the first-session one.
        self.assertEqual(plan(opportunity(estimates=short))["session"]["target_seconds"], 120)

    def test_the_first_session_meets_the_design_depth_bar(self):
        from wgf_design.depth import load_rules
        bar = load_rules()["first_session"]["min_s"]
        self.assertEqual(Policy.FIELDS["min_first_session_seconds"], bar)
        body = plan(opportunity(estimates={"session_seconds": 60}))
        self.assertEqual(body["session"]["first_session_seconds"], bar)
        self.assertGreaterEqual(body["session"]["target_seconds"], bar)

    def test_rapid_production_bias(self):
        body = plan()
        scope = body["production_scope"]
        self.assertLessEqual(scope["asset_budget"]["max_unique_assets"], 30)
        self.assertTrue(any("SDK adapter" in s for s in scope["reusable_systems"]))
        self.assertTrue(any("One control scheme" in d for d in scope["scope_decisions"]))
        excluded = " ".join(body["out_of_scope"])
        for word in ("Multiplayer", "Metagame", "IAP", "second mode"):
            self.assertIn(word, excluded)
        self.assertLessEqual(body["session"]["target_seconds"], 300)

    def test_a_concept_that_needs_an_excluded_system_keeps_it_and_says_so(self):
        body = plan(opportunity(concept__core_mechanic="online multiplayer 3d physics brawls"))
        self.assertNotIn("Multiplayer", " ".join(body["out_of_scope"]))
        self.assertEqual(body["production_scope"]["technical_complexity"], "high")
        high = [r for r in body["risks"] if r["severity"] == "high" and r["origin"] == "strategy"]
        self.assertTrue(high)

    def test_opportunity_risks_are_carried_and_high_ones_must_be_proved(self):
        body = plan()
        carried = [r for r in body["risks"] if r["origin"] == "opportunity"]
        self.assertEqual(len(carried), 2)
        self.assertTrue(any("Audio latency" in p for p in body["prototype_must_prove"]))

    def test_assumptions_are_hypotheses_that_name_their_refutation(self):
        for assumption in plan()["assumptions"]:
            self.assertIn(assumption["tier"], ("hypothesis", "derived"))
            self.assertTrue(assumption["invalidated_by"])

    def test_kill_criteria_are_measurable_expressions(self):
        body = plan()
        for criterion in body["kill_criteria"] + body["success_criteria"]:
            self.assertEqual(set(criterion["when"]), {"left", "op", "right"})
            self.assertTrue(criterion["rationale"])

    def test_refusals(self):
        cases = {
            "xl scope": opportunity(estimates={"scope_complexity": "xl"}),
            "too long": opportunity(estimates={"dev_speed_days": 30}),
            "rejected": opportunity(state="rejected"),
            "no concept": opportunity(concept={"genre": "arcade"}),
            "no profiles": opportunity(candidate_platforms=["nowhere"]),
        }
        for name, opp in cases.items():
            with self.subTest(name), self.assertRaises(StrategyRefused):
                plan(opp)
        with self.assertRaises(StrategyRefused):
            Policy(bogus=1)
        with self.assertRaises(StrategyRefused):
            Policy(target_timebox_days=30)

    def test_deterministic(self):
        self.assertEqual(plan(), plan())
        self.assertEqual(json.dumps(plan(), sort_keys=True), json.dumps(plan(), sort_keys=True))


class ContentModel(unittest.TestCase):
    """`concept.content_model`: the content shape the title commits to, from research when it
    coded one and from the genre family's model when it did not. An opportunity that resolves
    to no family commits to nothing, and the concept reads as it did before genre models."""

    def applied(self, body, field="concept.content_model"):
        return {a["field"]: a for a in body["research"]["applied"]}[field]

    def test_content_model_from_research_constraints_with_claim_refs(self):
        constraints = {
            "family": fv("puzzle", refs=["claim-family"]),
            "unit_kind": {"value": "level", "tier": "hypothesis", "source": "catalog"},
            "progression": fv(["unlock-track"], refs=["claim-progression"]),
            "difficulty_shape": fv("sawtooth", refs=["claim-shape"]),
            "difficulty_axes": fv(["depth", "move-limit"], refs=["claim-axes"]),
            "session_band": fv("short", refs=["claim-session"]),
        }
        body = plan(opportunity(research=research_block(constraints=constraints)))
        model = dict(body["concept"]["content_model"])
        self.assertEqual(model.pop("budget")["units"], 20)
        self.assertEqual(model, {
            "family": "puzzle", "unit_kind": "level", "progression": "unlock-track",
            "difficulty_shape": "sawtooth", "difficulty_axes": ["depth", "move-limit"],
            "min_units": 6, "source": "research", "quality_tier": "release"})
        applied = self.applied(body)
        self.assertEqual(applied["source"], "research")
        for claim in ("claim-family", "claim-progression", "claim-shape", "claim-axes"):
            self.assertIn(claim, applied["claim_refs"])
        direction = body["concept"]["gameplay_direction"]
        self.assertIn("Content: 6 specified levels in the prototype, 20 in the release", direction)
        self.assertIn("difficulty authored per unit on depth, move-limit", direction)
        self.assertIn("progression unlock-track; sawtooth ramp.", direction)
        # The constraints reach design whole, claims included.
        self.assertEqual(body["research"]["design_constraints"], constraints)

    def test_content_model_default_names_the_family(self):
        body = plan(opportunity(research=research_block(genre="platformer",
                                                        family="platformer")))
        model = dict(body["concept"]["content_model"])
        model.pop("budget")
        self.assertEqual(model, {
            "family": "platformer", "unit_kind": "level", "progression": "linear-levels",
            "difficulty_shape": "level-authored",
            "difficulty_axes": ["precision", "timing", "hazard-density",
                                "spatial-complexity"],
            "min_units": 5, "source": "default", "quality_tier": "release"})
        applied = self.applied(body)
        self.assertEqual(applied["source"], "default")
        self.assertIn("Platformer", applied["detail"])
        self.assertIn("research coded no content shape", applied["detail"])
        self.assertNotIn("claim_refs", applied)

    def test_an_idea_on_a_genre_model_entry_is_the_concept(self):
        # Research named no hand-coded archetype, only the family the Factory can build: the
        # catalog entry is a capability and the person's idea is the game. The concept is read
        # from the brief, the family's loop says what a session is, and the content model
        # bounds the design; the catalog's seed wording never replaces the idea.
        idea = "A lane tower defense on a kitchen counter: four tower types and twelve waves"
        body = plan(opportunity(brief=idea,
                                research=research_block(genre="tower-defense",
                                                        family="strategy",
                                                        genre_model="strategy")))
        self.assertEqual(body["one_liner"], idea + ".")
        self.assertEqual(body["concept"]["core_mechanic"], idea)
        self.assertIn("hold the wave", body["concept"]["core_loop"])
        self.assertIn(f"The brief, built in full: {idea}", body["mvp"])
        self.assertEqual(body["brief"], idea)
        applied = next(a for a in body["research"]["applied"] if a["field"] == "concept")
        self.assertEqual(applied["source"], "brief")
        self.assertTrue(any("is the concept" in a["statement"] for a in body["assumptions"]))

    def test_an_idea_on_a_design_archetype_entry_keeps_the_catalog_concept(self):
        # A hand-coded archetype is the game research selected; the brief is recorded, never
        # folded into the concept, so its words cannot re-pick the archetype.
        research = research_block(genre="match-3", family="puzzle")
        research["capability"]["design_archetype"] = "merge-puzzle"
        body = plan(opportunity(brief="a penguin ice puzzle", research=research))
        self.assertNotIn("penguin", body["one_liner"])
        self.assertNotIn("penguin", body["concept"]["core_mechanic"])
        self.assertEqual(body["brief"], "a penguin ice puzzle")

    def test_mvp_no_longer_promises_one_ramp(self):
        # A genre-model entry: the catalog builds it from the family's model, so the MVP is a
        # number of designed units, not "one content set with a ramp".
        body = plan(opportunity(research=research_block(genre="tower-defense",
                                                        family="strategy",
                                                        genre_model="strategy")))
        content = body["concept"]["content_model"]
        self.assertEqual((content["family"], content["unit_kind"], content["min_units"]),
                         ("strategy", "wave", 4))
        self.assertNotIn("One content set with a data-driven difficulty ramp", body["mvp"])
        self.assertIn("4 designed waves with authored difficulty on decision-density, "
                      "economy-pressure, opponent-escalation, composition", body["mvp"])
        direction = body["concept"]["gameplay_direction"]
        self.assertNotIn("Difficulty comes from one data-driven ramp", direction)
        # The release number is the release-tier budget: the strategy family's min_total
        # (10) is below the quality benchmark's 12.
        self.assertIn("4 specified waves in the prototype, 12 in the release", direction)

    def test_legacy_strategy_text_unchanged_without_family(self):
        body = plan()
        self.assertNotIn("content_model", body["concept"])
        self.assertIn("Difficulty comes from one data-driven ramp, not hand-built levels.",
                      body["concept"]["gameplay_direction"])
        self.assertIn("One content set with a data-driven difficulty ramp", body["mvp"])
        self.assertNotIn("research", body)
        # Research V2, but a genre no family lists: nothing is assumed, and the text holds.
        card = plan(opportunity(research=research_block(genre="solitaire", family="card")))
        self.assertNotIn("content_model", card["concept"])
        self.assertIn("Difficulty comes from one data-driven ramp, not hand-built levels.",
                      card["concept"]["gameplay_direction"])
        self.assertIn("One content set with a data-driven difficulty ramp", card["mvp"])
        applied = self.applied(card)
        self.assertEqual(applied["source"], "default")
        self.assertTrue(applied["detail"].startswith("none: no genre family covers"))


class QualityTierBudget(unittest.TestCase):
    """WS-1 (docs/quality-gap-audit-2026-10.md): the run states its quality tier, and the
    strategy commits the content budget for it - units, groups where the family has them,
    distinct elements - from the larger of the genre model's `min_total` and the quality
    benchmark, in the family's own kinds, with the reasons that volume is enough. The cases
    are the audit's: an arcade family whose `min_total` of 6 a 12-level build cleared twice
    over, a racing family whose 6 straight courses were accepted only at 12."""

    def budget(self, family, genre, tier=None, brief=None, genre_model=None):
        opp = opportunity(research=research_block(genre=genre, family=family,
                                                  genre_model=genre_model))
        if brief:
            opp["brief"] = brief
        body = plan_strategy(opp, PROFILES, "neon-drift", None, quality_tier=tier)
        return body, body["concept"]["content_model"]

    def test_release_is_the_default_tier(self):
        _, model = self.budget("arcade", "endless-runner")
        self.assertEqual(model["quality_tier"], "release")

    def test_arcade_release_budget_is_the_benchmark_not_the_family_floor(self):
        # The 2D validation build had 12 levels and one brick kind; the family's 6 passed it.
        body, model = self.budget("arcade", "endless-runner")
        budget = model["budget"]
        self.assertEqual(budget["units"], 12)
        self.assertEqual(budget["groups"], {"kind": "world", "count": 3,
                                            "min_units_per_group": 4})
        self.assertEqual(budget["elements"]["count"], 8)
        self.assertEqual(budget["elements"]["kinds"],
                         ["obstacle kind", "target kind", "power-up"])
        self.assertEqual(budget["designed_play_s"], 300)
        units = next(b for b in budget["basis"] if b["quantity"] == "units")
        self.assertEqual(units, {"quantity": "units", "genre_model": 6, "benchmark": 12,
                                 "value": 12})
        self.assertEqual(budget["references"], ["genre-models@1.2.0",
                                                "quality-benchmark@1.2.0"])
        self.assertTrue(any(d.startswith(f"Quality tier release: the content budget is 12 "
                                         f"{model['unit_kind']}s, 3 worlds, 8 distinct "
                                         f"elements")
                            for d in body["production_scope"]["scope_decisions"]),
                        body["production_scope"]["scope_decisions"])
        self.assertTrue(any("release content budget" in a["statement"]
                            for a in body["assumptions"]))

    def test_the_larger_bar_wins(self):
        # Level puzzle: the family's 20 is above the benchmark's 12, so 20 stands.
        _, model = self.budget("puzzle", "match-3")
        units = next(b for b in model["budget"]["basis"] if b["quantity"] == "units")
        self.assertEqual((units["genre_model"], units["benchmark"], units["value"]),
                         (20, 12, 20))

    def test_racing_counts_tracks_in_cups(self):
        # The 3D validation build: 6 straight courses in one group cleared the family's 8
        # on count; the accepted release had 12 in 3 groups.
        body, model = self.budget("racing", "racing")
        budget = model["budget"]
        self.assertEqual((model["unit_kind"], budget["units"]), ("track", 12))
        self.assertEqual(budget["groups"]["kind"], "cup")
        reasons = " ".join(budget["justification"].values())
        self.assertIn("12 tracks", reasons)
        self.assertNotIn("level", reasons.replace(model["progression"], ""))
        self.assertNotIn("boss", reasons)
        # A strategy that commits to three cups no longer excludes "a second content set".
        self.assertFalse(any(s.startswith("A second mode or content set")
                             for s in body["out_of_scope"]))
        self.assertTrue(any(s.startswith("A second mode; the release's content is the "
                                         "budget") for s in body["out_of_scope"]))

    def test_a_family_without_groups_gets_none(self):
        _, model = self.budget("survival", "arena-survivor", genre_model="survival")
        budget = model["budget"]
        self.assertNotIn("groups", budget)
        self.assertEqual(budget["units"], 12)
        self.assertEqual(model["unit_kind"], "run-segment")
        self.assertIn("no group above the run-segment",
                      budget["justification"]["progression_structure"])

    def test_the_justification_covers_the_five_reasons(self):
        _, model = self.budget("platformer", "platformer")
        why = model["budget"]["justification"]
        self.assertEqual(sorted(why), ["mechanics", "platform_expectations",
                                       "progression_structure", "replayability",
                                       "session_length"])
        self.assertIn("300 s of designed play", why["session_length"])
        self.assertIn("3 worlds of at least 4 levels", why["progression_structure"])
        self.assertIn("8 distinct elements (hazard kind, enemy kind, traversal element)",
                      why["mechanics"])
        self.assertIn("Yandex Games", why["platform_expectations"])

    def test_mvp_tier_commits_the_prototype_only(self):
        body, model = self.budget("arcade", "endless-runner", tier="mvp")
        budget = model["budget"]
        self.assertEqual(model["quality_tier"], "mvp")
        self.assertEqual(budget["units"], model["min_units"])
        self.assertNotIn("groups", budget)
        self.assertNotIn("elements", budget)
        self.assertEqual(budget["references"], ["genre-models@1.2.0"])
        self.assertIn("not a release", budget["justification"]["platform_expectations"])
        kinds = model["unit_kind"] + "s"
        self.assertIn(f"3 specified {kinds} in the prototype, 3 in the release",
                      body["concept"]["gameplay_direction"])
        # At mvp there is no release budget for "a second content set" to contradict.
        self.assertTrue(any(s.startswith("A second mode or content set")
                            for s in body["out_of_scope"]))

    def test_an_unknown_tier_is_refused(self):
        with self.assertRaises(StrategyRefused):
            self.budget("arcade", "endless-runner", tier="premium")

    def test_both_tiers_validate_against_the_schema(self):
        research = research_block(genre="racing", family="racing")
        research["audience"] = {key: fv("fixture") for key in (
            "player_type", "intent", "device", "age_band", "session_behavior")}
        for tier in ("mvp", "release"):
            with self.subTest(tier):
                result = step({"quality_tier": tier}).execute(
                    fake_inputs(opportunity(research=research)), FakeContext())
                self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
                artifact = result.artifacts[0].content
                self.assertEqual(ArtifactContracts()("title-strategy", artifact), [])
                self.assertEqual(artifact["concept"]["content_model"]["quality_tier"], tier)
                self.assertEqual(result.artifacts[0].metadata["quality_tier"], tier)

    def test_the_tier_comes_from_the_project_config(self):
        context = FakeContext()
        context.config = {"strategy": {"quality_tier": "mvp"}}
        opp = opportunity(research=research_block(genre="racing", family="racing"))
        result = step().execute(fake_inputs(opp), context)
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
        self.assertEqual(result.artifacts[0].content["concept"]["content_model"]
                         ["quality_tier"], "mvp")
        result = step({"quality_tier": "gold"}).execute(fake_inputs(opp), context)
        self.assertEqual((result.outcome, result.retryable), (StepOutcome.FAILED, False))

    def test_no_family_records_the_tier_as_a_decision(self):
        body = plan()
        self.assertNotIn("content_model", body["concept"])
        self.assertTrue(any(d.startswith("Quality tier release: no genre family")
                            for d in body["production_scope"]["scope_decisions"]))


class OutOfScopeReconciled(unittest.TestCase):
    """`out_of_scope` is reconciled against the scope it sits beside. Unlocks the brief asks
    for (plugin dogfood F08) are GroundedInTheBrief's; the release budget's content sets are
    QualityTierBudget's."""

    def strategy(self, brief):
        opp = opportunity(research=research_block(genre="endless-runner", family="arcade"))
        opp["brief"] = brief
        return plan(opp)

    def test_a_brief_that_needs_an_excluded_system_keeps_it(self):
        body = self.strategy("A runner where you dress up your character in skins")
        self.assertFalse(any("cosmetics" in s for s in body["out_of_scope"]))
        self.assertTrue(any("(customization)" in r["description"] for r in body["risks"]))

    def test_no_unlock_keeps_the_exclusion_whole(self):
        body = self.strategy("A runner on a neon highway")
        self.assertIn("Character or skin customization and a cosmetics shop",
                      body["out_of_scope"])
# The live brief of validation run B (docs/handoff/2026-10-03-two-game-validation.md).
MARBLE = ("A 3D low-poly marble-roll game (Three.js): tilt/steer a marble across floating "
          "sky-island courses, ramps, moving platforms, gaps and bumpers; collect gems, beat "
          "the par time for stars; 3 themed worlds of hand-designed courses, unlocks and saved "
          "progress, a time-trial mode with personal bests. Chase camera, desktop keys and "
          "mobile touch.")
BOILERPLATE = "Difficulty comes from one data-driven ramp, not hand-built levels."


class GroundedInTheBrief(unittest.TestCase):
    """Validation finding 2 (and plugin F08): the strategy wrote fixed sentences whatever the
    brief asked. Its text now follows the brief intents of core/reference/mechanic-lexicon.yaml,
    and `contradictions` refuses a strategy whose statements still contradict them."""

    def test_a_hand_designed_brief_never_gets_the_ramp_sentence(self):
        body = plan(opportunity(brief=MARBLE))
        direction = body["concept"]["gameplay_direction"]
        self.assertNotIn("not hand-built", direction)
        self.assertNotIn(BOILERPLATE, direction)
        self.assertIn("Content: hand-designed courses, as the brief asks, with difficulty "
                      "authored per course.", direction)
        self.assertIn("Hand-designed courses, as the brief asks, with difficulty authored per "
                      "course", body["mvp"])
        self.assertNotIn("One content set with a data-driven difficulty ramp", body["mvp"])
        self.assertIn("Content as data: every designed course with its difficulty values",
                      body["production_scope"]["reusable_systems"])
        self.assertEqual(planner.contradictions(body), [])

    def test_a_hand_designed_brief_makes_the_family_content_authored(self):
        # The arcade family's default shape is a time ramp; the brief asks for hand-designed
        # courses, and the family allows authored difficulty, so the brief decides it.
        body = plan(opportunity(brief=MARBLE, research=research_block(
            genre="endless-runner", family="arcade", genre_model="arcade")))
        self.assertEqual(body["concept"]["content_model"]["difficulty_shape"], "level-authored")
        applied = [a for a in body["research"]["applied"]
                   if a["field"] == "concept.content_model" and a["source"] == "brief"]
        self.assertEqual(len(applied), 1)
        self.assertIn("authored-content", applied[0]["detail"])
        self.assertEqual(planner.contradictions(body), [])

    def test_unlocks_and_a_mode_the_brief_asks_for_are_not_excluded(self):
        body = plan(opportunity(brief=MARBLE))
        out = " ".join(body["out_of_scope"])
        self.assertNotIn("Character or skin customization and a cosmetics shop", out)
        self.assertIn("the unlocks the brief asks for are earned in play", out)
        self.assertNotIn("A second mode or content set", out)
        self.assertTrue(any("(content)" in r["description"] for r in body["risks"]))

    def test_without_a_brief_the_text_is_unchanged(self):
        body = plan()
        self.assertIn(BOILERPLATE, body["concept"]["gameplay_direction"])
        self.assertIn("Character or skin customization and a cosmetics shop", body["out_of_scope"])
        self.assertIn("Data-driven difficulty ramp", body["production_scope"]["reusable_systems"])

    def test_a_statement_that_contradicts_the_brief_is_found(self):
        body = plan(opportunity(brief=MARBLE))
        body["concept"]["gameplay_direction"] += " " + BOILERPLATE
        body["out_of_scope"].append("Character or skin customization and a cosmetics shop")
        found = planner.contradictions(body)
        # The ramp sentence carries two contradicting phrases; each is reported.
        self.assertEqual(len(found), 3, found)
        self.assertTrue(any("concept.gameplay_direction" in f and "authored-content" in f
                            for f in found), found)
        self.assertTrue(any("out_of_scope" in f and "unlocks" in f for f in found), found)

    def test_a_statement_that_contradicts_the_content_model_is_found(self):
        # No brief: a level-authored content model is enough.
        body = plan(opportunity(research=research_block(genre="tower-defense",
                                                        family="strategy",
                                                        genre_model="strategy")))
        self.assertEqual(planner.contradictions(body), [])
        body["mvp"].append("One content set with a data-driven difficulty ramp")
        found = planner.contradictions(body)
        self.assertEqual(len(found), 1, found)
        self.assertIn("the content model (level-authored)", found[0])

    def test_a_contradicting_strategy_is_refused(self):
        with mock.patch.object(planner, "contradictions",
                               return_value=["mvp says \"x\" (y), which contradicts the brief"]):
            with self.assertRaises(StrategyRefused) as caught:
                plan(opportunity(brief=MARBLE))
        self.assertIn("contradicts", str(caught.exception))


# -- the step ----------------------------------------------------------------------------


class FakeLogger:
    def __init__(self):
        self.records = []

    def __getattr__(self, level):
        return lambda message, **fields: self.records.append((level, message, fields))


class FakeContext:
    def __init__(self, project_id="neon-drift", execution=1, visit=1):
        self.project_id = project_id
        self.execution = execution
        self.visit = visit
        self.run_id = "run-1"
        self.current_step = "strategy"
        self.logger = FakeLogger()

    @property
    def idempotency_key(self):
        return f"{self.run_id}:{self.current_step}:{self.visit}"


def fake_inputs(body=None, schema_version="1.0.0"):
    if body is None:
        return StepInputs({}, lambda ref: None, ["opportunity"])
    ref = ArtifactRef(id="opportunity", type="opportunity", version=1, location="x",
                      checksum="x", content_hash=body["provenance"]["content_hash"],
                      schema_version=schema_version)
    return StepInputs({"opportunity": ref}, lambda _ref: copy.deepcopy(body), [])


def step(params=None):
    definition = StepDefinition.__new__(StepDefinition)
    definition.id, definition.type = "strategy", "strategy"
    definition.params = params or {}
    definition.inputs, definition.outputs = ["opportunity"], ["title-strategy"]
    instance = StrategyStep(definition)
    instance.clock = lambda: FIXED
    return instance


class StepUnit(unittest.TestCase):
    def test_success_emits_a_contract_valid_draft(self):
        result = step().execute(fake_inputs(opportunity()), FakeContext())
        self.assertEqual(result.outcome, StepOutcome.SUCCESS)
        (output,) = result.artifacts
        artifact = output.content
        self.assertEqual(output.type, "title-strategy")
        self.assertEqual(ArtifactContracts()("title-strategy", artifact), [])
        provenance = artifact["provenance"]
        self.assertEqual(provenance["status"], "draft")  # G2 decides, not the step
        self.assertEqual(provenance["artifact_id"], "wgf:title-strategy:neon-drift:20260901-01")
        self.assertEqual(provenance["inputs"][0]["content_hash"],
                         opportunity()["provenance"]["content_hash"])
        self.assertEqual(provenance["content_hash"], content_hash(artifact))
        self.assertEqual(output.metadata["required_platform"], "yandex")

    def test_the_platform_choice_comes_from_with_then_the_project_config(self):
        context = FakeContext()
        context.config = {"strategy": {"platforms": ["crazygames", "yandex"]}}
        result = step().execute(fake_inputs(opportunity()), context)
        self.assertEqual(result.artifacts[0].metadata["required_platform"], "crazygames")
        # `with:` wins over the configuration, and is not mistaken for a policy key.
        result = step({"platforms": ["yandex"], "max_platforms": 2}).execute(
            fake_inputs(opportunity()), context)
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
        self.assertEqual([p["id"] for p in result.artifacts[0].content["platform_set"]],
                         ["yandex"])
        # Policy comes from the configuration too: a fourth platform needs max_platforms.
        context.config = {"strategy": {"platforms": ["yandex", "crazygames", "y8", "poki"]}}
        result = step().execute(fake_inputs(opportunity()), context)
        self.assertEqual((result.outcome, result.retryable), (StepOutcome.FAILED, False))
        context.config["strategy"]["max_platforms"] = 4
        result = step().execute(fake_inputs(opportunity()), context)
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
        self.assertEqual(len(result.artifacts[0].content["platform_set"]), 4)

    def test_title_id_falls_back_to_the_opportunity(self):
        result = step().execute(fake_inputs(opportunity(title_id=None)), FakeContext(None))
        self.assertEqual(result.artifacts[0].content["title_id"], "neon-drift")

    def test_missing_opportunity_waits(self):
        result = step().execute(fake_inputs(), FakeContext())
        self.assertEqual(result.outcome, StepOutcome.WAITING_FOR_INPUT)

    def test_an_unreadable_major_version_is_refused(self):
        result = step().execute(fake_inputs(opportunity(), "2.0.0"), FakeContext())
        self.assertEqual((result.outcome, result.retryable), (StepOutcome.FAILED, False))

    def test_a_refused_plan_is_a_permanent_failure(self):
        opp = opportunity(estimates={"scope_complexity": "xl"})
        result = step().execute(fake_inputs(opp), FakeContext())
        self.assertEqual((result.outcome, result.retryable), (StepOutcome.FAILED, False))
        self.assertIn("rapid-production envelope", result.error)
        self.assertEqual(result.artifacts, [])

    def test_bad_policy_params_are_a_permanent_failure(self):
        result = step({"max_platforms": "many"}).execute(fake_inputs(opportunity()),
                                                        FakeContext())
        self.assertEqual((result.outcome, result.retryable), (StepOutcome.FAILED, False))

    def test_policy_params_apply(self):
        opp = opportunity(estimates={"dev_speed_days": 12})
        result = step({"target_timebox_days": 10}).execute(fake_inputs(opp), FakeContext())
        self.assertEqual(result.artifacts[0].content["timebox_days"], 10)

    def test_re_execution_with_the_same_key_is_idempotent(self):
        first = step().execute(fake_inputs(opportunity()), FakeContext())
        second = step().execute(fake_inputs(opportunity()), FakeContext())
        self.assertEqual(first.artifacts[0].content, second.artifacts[0].content)

    def test_g2_predicates_are_green(self):
        artifact = step().execute(fake_inputs(opportunity()), FakeContext()).artifacts[0].content

        class Entity:
            def artifact(self, artifact_type):
                assert artifact_type == "title-strategy"
                return artifact

        context = GuardContext(Entity())
        for guard in ("kill_criteria_defined", "timebox_set"):
            self.assertIs(evaluate_guard(guard, context).value, True, guard)


# -- through the engine ------------------------------------------------------------------


class ThroughEngine(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.mkdtemp(prefix="wgf-strategy-")
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)
        modules = os.path.join(self.scratch, "modules")
        os.makedirs(modules)
        with open(os.path.join(modules, "wgf_test_placeholders.py"), "w") as handle:
            handle.write(PLACEHOLDERS)
        sys.path.insert(0, modules)
        self.addCleanup(sys.path.remove, modules)
        self.addCleanup(sys.modules.pop, "wgf_test_placeholders", None)
        patcher = mock.patch.object(StrategyStep, "clock", staticmethod(lambda: FIXED))
        patcher.start()
        self.addCleanup(patcher.stop)

    def api(self, auto_approve=()):
        config = FactoryConfig({
            "steps": {"modules": ["wgf_test_placeholders", "wgf_strategy"]},
            "checkpoints": {"auto_approve": list(auto_approve)},
            "storage": {"fsync": False},
            "execution": {"delay_seconds": 0},
        })
        return WorkflowAPI(config=config, store_dir=os.path.join(self.scratch, "store"))

    def test_the_real_module_is_the_one_that_runs(self):
        registry = self.api().registry(use_mock=False)
        self.assertIs(registry.resolve("strategy"), StrategyStep)
        self.assertIsNot(registry.resolve("design"), StrategyStep)

    def test_strategy_stops_at_g2_and_design_consumes_it_after_approval(self):
        api = self.api()
        state = api.run(RunRequest(project_id="neon-drift"))
        self.assertEqual(state.status, RunStatus.WAITING)
        self.assertEqual(state.steps["strategy-review"].status, StepStatus.WAITING)
        self.assertNotIn("design", [t["step"] for t in state.trail])  # never bypassed

        ref = state.latest_artifact("title-strategy")
        artifact = api.store.read_artifact(state.run_id, ref)
        self.assertEqual(ArtifactContracts()("title-strategy", artifact), [])
        self.assertEqual(artifact["provenance"]["status"], "draft")
        self.assertEqual(ref.schema_version, schema_version("title-strategy"))
        self.assertEqual(state.steps["strategy"].consumed, ["opportunity@v1"])

        final = api.run(RunRequest(resume=state.run_id, decision="approve"))
        self.assertEqual(final.status, RunStatus.WAITING)  # G3, after the tech plan
        final = api.run(RunRequest(resume=state.run_id, decision="approve"))
        # G4 after verification: only a person passes it, then the run releases.
        self.assertEqual((final.status, final.cursor), (RunStatus.WAITING, "prototype-review"))
        final = api.run(RunRequest(resume=state.run_id, decision="pass"))
        self.assertEqual(final.status, RunStatus.COMPLETED)
        self.assertEqual(final.steps["design"].consumed, ["title-strategy@v1"])
        design = api.store.read_artifact(final.run_id, final.latest_artifact("game-design"))
        pinned = {i["artifact_type"]: i["content_hash"] for i in design["provenance"]["inputs"]}
        self.assertEqual(pinned["title-strategy"], artifact["provenance"]["content_hash"])

    def test_a_rejected_strategy_blocks_the_run_before_design(self):
        api = self.api()
        state = api.run(RunRequest(project_id="neon-drift"))
        final = api.run(RunRequest(resume=state.run_id, decision="reject"))
        self.assertEqual(final.status, RunStatus.BLOCKED)
        self.assertNotIn("design", [t["step"] for t in final.trail])

    def test_plan_group_needs_an_opportunity(self):
        state = self.api().run(RunRequest(scope="plan", project_id="neon-drift"))
        self.assertEqual(state.status, RunStatus.WAITING)
        self.assertEqual(state.steps["strategy"].status, StepStatus.WAITING)

    def test_a_configured_auto_approval_is_the_only_way_past_g2(self):
        final = self.api(auto_approve=["G2", "G3"]).run(RunRequest(project_id="neon-drift"))
        # Past G2 and G3 unattended; G4 cannot be configured away and waits for a person.
        self.assertEqual(final.steps["strategy-review"].status, StepStatus.SUCCESS)
        self.assertEqual((final.status, final.cursor), (RunStatus.WAITING, "prototype-review"))

    def test_the_workflow_still_declares_the_checkpoint_after_strategy(self):
        definition = load_definition("new-game")
        ids = definition.step_ids
        review = next(s for s in definition.steps if s.id == "strategy-review")
        self.assertEqual(ids[ids.index("strategy") + 1], "strategy-review")
        self.assertEqual(review.params["gate"], "G2")


# -- schema ------------------------------------------------------------------------------


class Schema(unittest.TestCase):
    AJV = ["npx", "--yes", "-p", "ajv-cli@5", "-p", "ajv-formats@2", "ajv", "validate",
           "-s", "core/artifacts/title-strategy.schema.json",
           "-r", "core/artifacts/shared/*.schema.json",
           "-c", "ajv-formats", "--spec=draft2020", "--strict=false"]

    def test_emitted_artifacts_validate_with_ajv(self):
        if os.environ.get("WGF_SKIP_AJV") == "1" or not shutil.which("npx"):
            self.skipTest("ajv unavailable (npx missing or WGF_SKIP_AJV set)")
        scratch = tempfile.mkdtemp(prefix="wgf-strategy-ajv-")
        self.addCleanup(shutil.rmtree, scratch, ignore_errors=True)
        variants = {
            "default": opportunity(),
            "capped": opportunity(estimates={"dev_speed_days": 19, "session_seconds": 900}),
            "standalone": opportunity(candidate_platforms=["generic-web"],
                                      monetization_hypothesis={"primary": "none"}),
            "reclassified": opportunity(candidate_platforms=["crazygames", "gamevui", "x"],
                                        monetization_hypothesis={"primary": "iap"}),
            "complex": opportunity(concept__core_mechanic="online multiplayer 3d brawls"),
        }
        command = list(self.AJV)
        for name, opp in variants.items():
            result = step().execute(fake_inputs(opp), FakeContext())
            self.assertEqual(result.outcome, StepOutcome.SUCCESS, name)
            path = os.path.join(scratch, f"{name}.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(result.artifacts[0].content, handle)
            command += ["-d", path]
        try:
            run = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=180)
        except (OSError, subprocess.TimeoutExpired) as exc:
            self.skipTest(f"ajv could not run: {exc}")
        output = run.stdout + run.stderr
        if " valid" not in output and " invalid" not in output:
            self.skipTest(f"ajv could not run: {output.strip()[-200:]}")
        self.assertEqual(run.returncode, 0, output)
        self.assertEqual(output.count(" valid"), len(variants), output)


if __name__ == "__main__":
    unittest.main()

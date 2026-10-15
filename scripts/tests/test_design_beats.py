"""The design contract beyond the counts (scripts/wgf_design/beats.py): ADVISORY.

The twelve design.* rules of core/reference/design-consistency-rules.yaml (2.6.0) read a design
against core/reference/quality-benchmark.yaml `design` (1.7.0). Every one is a warning: a
breach is reported to G3 and never refuses, repairs or routes a design.

Run from the repository root:
    python -m unittest discover -s scripts/tests -t scripts/tests -p test_design_beats.py
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

from wgf_design import beats, consistency, content  # noqa: E402
from wgflib.workflow import StepOutcome  # noqa: E402

BENCHMARK = content.load_benchmark()
TEARDOWNS = ["game-leader-a", "game-leader-b", "game-leader-c"]
DIMENSIONS = ["core_verbs", "signature_moments", "set_pieces_per_group", "content_duration",
              "meta_systems"]
# Designs the validation runs wrote, replayed when a directory of them is named. No default:
# the evidence is on one machine, and a default path there is wrong everywhere else.
REPLAY = os.environ.get("WGF_REPLAY_DESIGNS")


def _unit(index, purpose, group, introduces=(), difficulty=0.2, duration=160):
    unit = {"id": f"u{index}", "index": index, "tier": "mvp" if index <= 4 else "post-mvp",
            "purpose": purpose, "group": group, "mechanics": ["move"] + list(introduces),
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
    """A release-tier design that holds every design.* rule: three worlds of four; the opening
    unit teaches the core verb and one more mechanic, every later debut is one at a time on a
    teach, breather or twist; 1920 s."""
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


def strategy(teardowns=TEARDOWNS, fixture=False):
    return {"research": {"research_version": 2, "competitors": [
        dict({"game": g, "name": g, "role": "leader", "depth": "teardown", "claim_refs": []},
             **({"fixture": True} if fixture else {}))
        for g in teardowns]}}


def view(design, strat=None, benchmark=BENCHMARK):
    return beats.view(design, strat if strat is not None else strategy(), benchmark)


def flagged(out):
    """The rule ids whose problem list is not empty."""
    return {rule_id for rule_id, _ in beats.RULES if out[beats.short(rule_id)]}


def text(out, rule_id):
    return " | ".join(out[beats.short(rule_id)])


def units(design):
    return design["build_spec"]["content"]["units"]


class GoodDesign(unittest.TestCase):
    def test_a_design_that_states_everything_is_flagged_by_no_rule(self):
        out = view(good_design())
        self.assertEqual(flagged(out), set())
        self.assertTrue(out["binding"])
        self.assertEqual(out["tier"], "release")
        self.assertTrue(all(note.startswith("advisory") for note in out["notes"].values()))

    def test_the_bars_are_the_benchmark_s_and_every_1_6_0_bar_is_kept(self):
        self.assertEqual(BENCHMARK["version"], "1.7.0")
        bars = beats.design_bars(BENCHMARK, "release")
        self.assertEqual(bars[("beats", "opening_max_new_mechanics")], 1)
        self.assertEqual(bars[("beats", "introduce_in")], ["teach", "breather", "twist"])
        self.assertEqual(bars[("references", "min_teardowns")], 3)
        self.assertEqual(bars[("designed_play", "finite_min_s")], 1800)
        self.assertEqual(bars[("par_calibration", "min_human_to_bot_ratio")], 1.25)
        # No release has been measured against any of them: proposed or hypothesis, and a
        # hypothesis never exceeds the confidence a hypothesis claim may carry.
        for section in BENCHMARK["design"].values():
            for entry in section.values():
                self.assertIn(entry["basis"], ("proposed", "hypothesis"))
                if entry["basis"] == "hypothesis":
                    self.assertLessEqual(entry["confidence"], 0.6)
                    self.assertTrue(entry.get("evidence"))
        # Never lowered: the content bars 1.6.0 stated.
        self.assertEqual(BENCHMARK["content"]["units"]["min_total_designed_s"]["release"], 300)
        self.assertEqual(BENCHMARK["content"]["units"]["min_total"]["release"], 12)


class BeatChart(unittest.TestCase):
    def test_an_opening_unit_teaching_three_mechanics_is_flagged(self):
        # The case content.introductions_one_at_a_time exempts: the opening unit.
        design = good_design()
        units(design)[0]["introduces"] = ["move", "jump", "dash"]
        units(design)[0]["mechanics"] = ["move", "jump", "dash"]
        units(design)[2].pop("introduces")
        out = view(design)
        self.assertIn("design.introductions_placed", flagged(out))
        self.assertIn("introduces 2 mechanics beside the core verb (dash, jump)",
                      text(out, "design.introductions_placed"))

    def test_the_opening_unit_may_add_one_mechanic_to_the_core_verb(self):
        self.assertNotIn("design.introductions_placed", flagged(view(good_design())))

    def test_a_debut_on_a_climax_is_flagged(self):
        design = good_design()
        units(design)[2].pop("introduces")
        units(design)[2]["mechanics"] = ["move"]
        units(design)[3]["introduces"] = ["dash"]
        units(design)[3]["mechanics"] = ["move", "dash"]
        out = view(design)
        self.assertIn("on a 'climax' unit", text(out, "design.introductions_placed"))

    def test_how_many_a_later_unit_debuts_is_not_counted_here(self):
        # Two debuts in one later unit is content.introductions_one_at_a_time's (L29, binding)
        # alone: the advisory rule does not count it, so the two can never disagree.
        design = good_design()
        units(design)[2]["introduces"] = ["dash", "grab"]
        units(design)[2]["mechanics"] = ["move", "dash", "grab"]
        units(design)[4].pop("introduces")
        units(design)[4]["mechanics"] = ["move"]
        self.assertNotIn("design.introductions_placed", flagged(view(design)))
        view_l29 = content.introductions_view(design)
        self.assertTrue(any("u3" in line for line in view_l29["over_one"]), view_l29)

    def test_a_teach_unit_harder_than_the_breather_right_before_it_is_flagged(self):
        design = good_design()
        units(design)[5]["purpose"] = "teach"
        units(design)[5]["difficulty"] = {"speed": 0.9}
        self.assertIn("design.teach_eases", flagged(view(design)))

    def test_a_teach_unit_later_in_the_group_is_free_to_climb(self):
        # Only the unit right after a breather: the content rules require the curve to
        # recover after a dip, and a later teach unit held to the breather would break that.
        design = good_design()
        units(design)[6]["purpose"] = "teach"
        units(design)[6]["difficulty"] = {"speed": 0.9}
        self.assertNotIn("design.teach_eases", flagged(view(design)))

    def test_a_world_without_a_twist_is_flagged(self):
        design = good_design()
        units(design)[6]["purpose"] = "test"
        self.assertIn("design.group_arc", flagged(view(design)))

    def test_a_world_that_does_not_end_in_a_climax_is_flagged(self):
        design = good_design()
        units(design)[11]["purpose"] = "test"
        out = view(design)
        self.assertIn("w3 ends on u12 (test), not a climax", text(out, "design.group_arc"))

    def test_a_climax_that_only_has_its_own_art_is_flagged(self):
        design = good_design()
        units(design)[3]["beat"].pop("climax")
        units(design)[3]["art"] = ["boss-1"]
        out = view(design)
        self.assertIn("u4 are climax units that declare no change",
                      text(out, "design.climax_changes_state"))

    def test_units_without_beats_are_flagged(self):
        design = good_design()
        for unit in units(design):
            unit.pop("beat")
        out = view(design)
        self.assertIn("design.beat_chart_stated", flagged(out))
        self.assertIn("design.risk_reward_offered", flagged(out))

    def test_a_decision_once_a_minute_is_flagged(self):
        design = good_design()
        units(design)[1]["beat"]["decision"]["every_s"] = 60
        self.assertIn("design.decision_cadence", flagged(view(design)))

    def test_signature_moments_of_every_kind_built_into_a_unit(self):
        design = good_design()
        design["build_spec"]["content"]["signature_moments"].pop()
        out = view(design)
        self.assertIn("0 rare-spectacle", text(out, "design.signature_moments"))

    def test_a_persisted_meta_system_is_justified(self):
        design = good_design()
        design["build_spec"]["content"]["meta_systems"].pop(0)
        self.assertIn("persists unlocks", text(view(design), "design.meta_systems_justified"))

    def test_a_finite_release_short_of_the_market_s_designed_play_is_flagged(self):
        design = good_design()
        for unit in units(design):
            unit["expected_duration_s"] = 25
        self.assertIn("design.designed_play_market", flagged(view(design)))
        design["genre"]["ending"] = "endless"
        self.assertNotIn("design.designed_play_market", flagged(view(design)))

    def test_a_par_scaled_from_the_bot_below_the_ratio_is_flagged(self):
        design = good_design()
        goal = design["build_spec"]["content"]["secondary_goals"][0]
        goal["par"]["ratio_to_bot"] = 1.1
        self.assertIn("design.par_calibrated", flagged(view(design)))
        goal.pop("par")
        self.assertIn("design.par_calibrated", flagged(view(design)))
        goal["par"] = {"basis": "human-playtest"}
        self.assertNotIn("design.par_calibrated", flagged(view(design)))


class References(unittest.TestCase):
    def test_missing_references_are_flagged(self):
        design = good_design()
        design.pop("references")
        self.assertIn("design.references_grounded", flagged(view(design)))

    def test_a_game_the_research_did_not_tear_down_is_never_a_reference(self):
        design = good_design()
        design["references"]["teardowns"][0]["game"] = "game-remembered"
        self.assertIn("game-remembered, which the research did not tear down",
                      text(view(design), "design.references_grounded"))

    def test_a_missing_dimension_is_flagged(self):
        design = good_design()
        design["references"]["dimensions"].pop()
        self.assertIn("no line for meta_systems", text(view(design), "design.references_grounded"))

    def test_too_few_teardowns_is_unknown_never_a_pass(self):
        design = good_design()
        design["references"] = {"status": "unknown", "reason": "the corpus has none",
                                "teardowns": [], "dimensions": []}
        out = view(design, strategy(TEARDOWNS[:1]))
        self.assertTrue(text(out, "design.references_grounded").startswith("UNKNOWN"))
        self.assertIn("1 teardown record(s)", text(out, "design.references_grounded"))
        # The design said so: nothing else is asked of it.
        self.assertEqual(len(out[beats.short("design.references_grounded")]), 1)

    def test_fixture_records_are_never_evidence(self):
        out = view(good_design(), strategy(fixture=True))
        found = text(out, "design.references_grounded")
        self.assertTrue(found.startswith("UNKNOWN"), found)
        self.assertIn("fixture records, never evidence", found)

    def test_claiming_grounded_references_without_teardowns_is_flagged(self):
        out = view(good_design(), strategy([]))
        self.assertIn("references.status is not 'unknown'",
                      text(out, "design.references_grounded"))

    def test_the_strategy_s_research_decides_never_the_design_s_own(self):
        design = good_design()
        design["research"] = strategy()["research"]
        out = view(design, {"research": {"research_version": 2, "competitors": []}})
        self.assertIn("design.references_grounded", flagged(out))


class Tiers(unittest.TestCase):
    def test_at_mvp_nothing_is_flagged_and_the_notes_say_what_a_release_would_warn(self):
        design = good_design()
        design["build_spec"]["content"]["quality_tier"] = "mvp"
        design.pop("references")
        for unit in units(design):
            unit.pop("beat")
        out = view(design, strategy([]))
        self.assertEqual(flagged(out), set())
        self.assertFalse(out["binding"])
        self.assertIn("at release this would warn",
                      out["notes"][beats.short("design.references_grounded")])
        self.assertTrue(all(note.startswith("tier mvp") for note in out["notes"].values()))

    def test_no_tier_or_a_benchmark_pinned_before_1_7_0_holds_nothing(self):
        design = good_design()
        design.pop("references")
        design["build_spec"]["content"].pop("quality_tier")
        out = view(design, {})
        self.assertEqual(flagged(out), set())
        old = copy.deepcopy(BENCHMARK)
        old.pop("design")
        old["version"] = "1.6.0"
        out = view(good_design(), strategy([]), old)
        self.assertEqual(flagged(out), set())
        self.assertTrue(all("1.6.0 states no design bars" in n for n in out["notes"].values()))

    def test_an_unreadable_pinned_benchmark_is_reported_not_measured(self):
        out = view(good_design(), strategy([]), beats.Unreadable("gone"))
        self.assertEqual(flagged(out), set())
        self.assertTrue(all("not measured" in n for n in out["notes"].values()))


class Ruleset(unittest.TestCase):
    """The rules are the ruleset's, warnings, and therefore advisory in check-tiers."""

    def test_the_ruleset_lists_every_rule_as_a_warning_before_the_trace_rule(self):
        rules = consistency.load_rules()
        listed = [r for r in rules["rules"] if r["id"].startswith(beats.PREFIX)]
        self.assertEqual([r["id"] for r in listed], [rule_id for rule_id, _ in beats.RULES])
        self.assertTrue(all(r["severity"] == "warning" for r in listed))
        self.assertEqual(rules["rules"][-1]["id"], "knowledge.trace_matches_design")

    def test_check_tiers_classifies_them_advisory(self):
        from wgflib.yamllite import load_file
        tiers = load_file(os.path.join(SCRIPTS, os.pardir, "core", "reference",
                                       "check-tiers.yaml"))
        source = tiers["sources"]["design-consistency"]
        self.assertEqual(source["tier"]["map"]["warning"], "advisory")

    def test_a_release_design_that_breaches_them_still_passes_consistency(self):
        design = good_design()
        for unit in units(design):
            unit.pop("beat")
        design.pop("references")
        out = view(design)
        rules = consistency.load_rules()
        for rule in rules["rules"]:
            if not rule["id"].startswith(beats.PREFIX):
                continue
            from wgflib.criteria import evaluate_named
            result = evaluate_named(rule, {"design": out})
            self.assertEqual(result["breached"], bool(out[beats.short(rule["id"])]),
                             rule["id"])


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

    def test_a_release_design_with_no_teardowns_succeeds_with_warnings(self):
        # No teardown corpus ships, so a default release run has none: reported, never refused,
        # never routed.
        result = self.run_family([])
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
        self.assertIsNone(result.route)
        design = result.artifacts[0].content
        block = design["consistency"]
        self.assertEqual(block["status"], "pass")
        by_id = {r["criterion_id"]: r for r in block["rule_results"]}
        self.assertTrue({rule_id for rule_id, _ in beats.RULES} <= set(by_id))
        grounded = by_id["design.references_grounded"]
        self.assertTrue(grounded["breached"])
        self.assertTrue(str(grounded["measured"][0]).startswith("UNKNOWN"))
        self.assertIn("warning(s) for G3", result.message)
        # Nothing binding is breached: only warnings.
        rules = {r["id"]: r for r in consistency.load_rules()["rules"]}
        blocking = [r["criterion_id"] for r in block["rule_results"] if r.get("breached")
                    and (rules.get(r["criterion_id"]) or {}).get("severity") == "blocking"]
        self.assertEqual(blocking, [])

    def test_an_mvp_design_is_unchanged(self):
        result = self.seeds.design_for("platformer")
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
        design = result.artifacts[0].content
        self.assertNotIn("references", design)
        self.assertEqual(self.seeds.breached(design), [])
        notes = [r["note"] for r in design["consistency"]["rule_results"]
                 if r["criterion_id"].startswith(beats.PREFIX)]
        self.assertEqual(len(notes), len(beats.RULES))
        self.assertTrue(all(n.startswith(("tier mvp", "no quality tier")) for n in notes), notes)

    def test_an_unreadable_pinned_benchmark_is_never_a_refusal(self):
        class Unreadable(self.design_tests.FixedClockStep):
            @staticmethod
            def _run_benchmark(context):
                raise ValueError("the pinned copy is gone")
        result = self.design_tests.run_step(self.seeds.strategy_for("platformer"),
                                            step_class=Unreadable)
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
        notes = [r["note"] for r in result.artifacts[0].content["consistency"]["rule_results"]
                 if r["criterion_id"].startswith(beats.PREFIX)]
        self.assertTrue(all("not measured" in n for n in notes), notes)


class PromptFollower(unittest.TestCase):
    """A design that does everything PROMPT_BEATS asks still holds every rule that binds.

    The release-tier fixture author's design, annotated the way the prompt asks: a beat per
    unit, a twist where a later unit would debut something on a test, signature moments built
    into units, meta systems decided, references UNKNOWN (no teardown in the research)."""

    @classmethod
    def setUpClass(cls):
        import test_design_seed as seeds
        from fixtures.quality import designs
        from wgf_design import register_author
        from wgf_design.authors import Resolved

        class Follower(designs.ReleaseSeedAuthor):
            name = "release-prompt-follower-fixture"

            def synthesize(self, family_id, models, strategy, entry):
                resolved = super().synthesize(family_id, models, strategy, entry)
                follow(resolved.archetype["content"], resolved.depth,
                       {m["id"]: m.get("progression_role")
                        for m in resolved.archetype.get("mechanics") or []})
                return Resolved(resolved.archetype_id, resolved.archetype, resolved.experience,
                                resolved.depth, resolved.why, resolved.applied)

            def draft(self, brief):
                out = super().draft(brief)
                out["references"] = {"status": "unknown",
                                     "reason": "the research carries no teardown record",
                                     "teardowns": [], "dimensions": []}
                return out

        register_author(Follower.name, Follower)
        cls.result = seeds.design_for("platformer", author=Follower.name)

    def test_it_succeeds_and_breaches_nothing_that_binds(self):
        result = self.result
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
        block = result.artifacts[0].content["consistency"]
        self.assertEqual(block["status"], "pass")
        rules = {r["id"]: r for r in consistency.load_rules()["rules"]}
        breached = [r["criterion_id"] for r in block["rule_results"] if r.get("breached")]
        binding = [b for b in breached if (rules.get(b) or {}).get("severity") != "warning"]
        self.assertEqual(binding, [])
        # What the prompt asks for is met; what is left is what it cannot meet without
        # evidence (the references) or without growing the strategy's content budget.
        self.assertLessEqual(set(breached), {"design.references_grounded",
                                             "design.designed_play_market"}, breached)


def follow(content_block, depth, roles):
    """Annotate a release fixture's content the way PROMPT_BEATS asks."""
    units = content_block["units"]
    # The opening unit teaches the core verb and one more mechanic: each further one moves to
    # the first later teach, breather or twist unit that debuts nothing else (one debut per
    # unit after the opening one, content.introductions_one_at_a_time), and no unit before it
    # asks for it.
    opening = units[0]
    extra = [m for m in opening.get("introduces") or [] if roles.get(m) != "core"][1:]
    seen = set()
    free = []
    for position, unit in enumerate(units):
        shown = set(unit.get("elements") or []) | set(unit.get("mechanics") or [])
        if position and not (set(unit.get("elements") or []) - seen) \
                and unit["purpose"] in ("teach", "breather", "twist"):
            free.append(position)
        seen |= shown
    for mechanic, position in zip(extra, free):
        opening["introduces"].remove(mechanic)
        for unit in units[:position]:
            if mechanic in unit["mechanics"]:
                unit["mechanics"].remove(mechanic)
        units[position]["introduces"] = [mechanic]
    seen = set()
    for position, unit in enumerate(units):
        shown = set(unit.get("elements") or []) | set(unit.get("mechanics") or [])
        named = set(unit.get("introduces") or []) or shown
        new = named - seen
        seen |= shown | named
        if position and new and unit["purpose"] not in ("teach", "breather", "twist"):
            if unit["purpose"] == "test":
                unit["purpose"] = "twist"
        beat = {"claim": f"A first-time player clears {unit['id']} within two attempts",
                "test": f"The bot's attempts at {unit['id']} exceed two",
                "decision": {"choice": "take the near target now or line up the far one",
                             "every_s": 3}}
        if unit["purpose"] == "twist":
            beat["risk_reward"] = {"line": "the narrow route past the new threat",
                                   "payoff": "a star and the time it saves"}
            beat["signature_moment"] = "chain-rise"
        elif unit["purpose"] == "climax":
            beat["climax"] = {"change": "phase-change", "phases": 2,
                              "description": f"Halfway through {unit['id']} the field turns "
                                             f"over and the new elements trade roles"}
            beat["signature_moment"] = "finale-break"
        else:
            beat["signature_moment"] = "clear-burst"
        unit["beat"] = beat
    content_block["signature_moments"] = [
        {"id": "clear-burst", "kind": "end-of-unit-payoff",
         "description": "The last target bursts and the stars count up one by one",
         "trigger": "clearing a unit, once per unit"},
        {"id": "chain-rise", "kind": "combo-escalation",
         "description": "Each link of a chain raises the pitch and the multiplier",
         "trigger": "three or more scores within two seconds"},
        {"id": "finale-break", "kind": "rare-spectacle",
         "description": "The finale field breaks apart into its second phase",
         "trigger": "the climax phase change, once per group"}]
    persisted = sorted({str(p.get("kind")) for p in (depth.get("meta") or {}).get("persists")
                        or [] if isinstance(p, dict)})
    declined = next(k for k in ("currency", "cosmetics", "upgrades") if k not in persisted)
    content_block["meta_systems"] = [
        {"system": kind, "decision": "include",
         "why": f"The {kind} the player keeps between sessions is a reason to return"}
        for kind in persisted if kind in beats.META_PERSISTED] + [
        {"system": declined, "decision": "decline",
         "why": f"A {declined} system would sit between the player and the next unit"}]


def _replayed():
    if not REPLAY:
        return []
    pattern = os.path.join(REPLAY, "val-*", "project", ".factory", "workflows", "new-game-*",
                           "artifacts", "game-design", "v*.json")
    return sorted(glob.glob(pattern))


@unittest.skipUnless(_replayed(), "WGF_REPLAY_DESIGNS names no directory of validation designs")
class Replay(unittest.TestCase):
    """The validation runs' designs, which passed every content count at the release tier."""

    def test_every_release_design_of_the_validation_runs_is_warned(self):
        release = 0
        for path in _replayed():
            with open(path, encoding="utf-8") as handle:
                design = json.load(handle)
            tier = ((design.get("build_spec") or {}).get("content") or {}).get("quality_tier")
            if tier != "release":
                continue
            release += 1
            with self.subTest(path=path):
                out = beats.view(design, None, BENCHMARK)
                self.assertIn("design.beat_chart_stated", flagged(out))
                self.assertIn("design.climax_changes_state", flagged(out))
                self.assertIn("design.references_grounded", flagged(out))
        self.assertGreater(release, 0)


if __name__ == "__main__":
    unittest.main()

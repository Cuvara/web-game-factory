"""The genre seed author: a design built from a genre family's own model (scripts/wgf_design/
seed.py, the `seed` blocks of core/reference/genre-models.yaml).

There are eight families and six hand-written design archetypes, and a family without an
archetype is not a gap the Factory cannot design: research's capability catalog names a
`genre_model` and this author synthesizes the design from the family's seed block - the
archetype, the experience contract, the depth plan, and the content list generated against
exactly the bars content.py applies.

Every test runs the real design step, because the point is the whole ladder: buildability,
the experience contract, production art, depth, the consistency rules and the content check
all hold on a design nobody wrote by hand.

    python -m unittest scripts.tests.test_design_seed
"""

import copy
import itertools
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, HERE)

import test_design_module as design_tests  # noqa: E402
from wgf_design import archetypes, content, seed  # noqa: E402
from wgf_design.seed import GenreSeedAuthor  # noqa: E402
from wgflib import genre_models  # noqa: E402
from wgflib.workflow.model import StepOutcome  # noqa: E402

MODELS = genre_models.load()
FAMILIES = MODELS["families"]


def facet(value, tier="observed"):
    return {"value": value, "label": str(value), "tier": tier, "source": "catalog",
            "reason": "FIXTURE", "claim_refs": ["claim-fixture"]}


def unknown():
    """A facet research coded nothing for: the design decides it and says a default did."""
    return {"value": None, "tier": "unknown", "source": "unknown", "reason": "FIXTURE",
            "claim_refs": ["claim-fixture"]}


def research_block(family, constraints=None):
    """The Research V2 handoff a strategy for a genre-model opportunity carries: the catalog
    entry is buildable through the family's model and names no design archetype."""
    block = {
        "research_version": 2, "report_id": "rr-seed", "opportunity_id": "opp-seed",
        "origin": "supply-gap", "summary": "FIXTURE opportunity.",
        "market": [], "competitors": [], "benchmarks": [], "patterns": {"adopt": []},
        "monetization": {"placements": [], "platform_support": []},
        "production": {"dimension": "2d", "complexity": "s", "tier": "hypothesis",
                       "drivers": ["FIXTURE"]},
        "capability": {"buildable": True, "missing": [], "catalog_entry": "fixture-entry",
                       "reason": "FIXTURE", "design_archetype": None, "genre_model": family},
        "art": {"dimension": unknown(), "rendering": unknown(), "tone": unknown(),
                "palette": unknown()},
        "theme": {"theme": unknown(), "setting": unknown()},
        "fantasy": {"player": unknown(), "emotional": unknown()},
        "gameplay": {"genre": facet(FAMILIES[family]["nodes"][0]), "mechanics": unknown()},
        "audience": {"player_type": unknown(), "intent": unknown(), "device": unknown(),
                     "age_band": unknown(), "session_behavior": unknown()},
        "risks": [],
        "confidence": {"evidence_coverage": 0.5, "weakest_tier": "hypothesis",
                       "unknown_facets": [], "fixture_evidence": True},
        "claim_refs": [], "applied": [],
    }
    if constraints is not None:
        block["design_constraints"] = constraints
    return block


def strategy_for(family, constraints=None, **changes):
    """The worked-example strategy restated so its concept IS the family seed's game, the way
    a strategy for that opportunity would be: the planner writes the concept from the catalog
    entry, and the design must describe the game G2 approved (concept_mechanics_carried)."""
    a = FAMILIES[family]["seed"]["archetype"]
    mvp = [m for m in a["mechanics"] if m["tier"] == "mvp"]
    return design_tests.variant(
        one_liner=f"A {a['label'].lower()}: {a['core_loop']}",
        concept={"genre": FAMILIES[family]["nodes"][0],
                 "core_mechanic": " ".join(m["description"] for m in mvp),
                 "core_loop": a["core_loop"],
                 # What the strategy approved along with the mechanics: their names, their
                 # rules and the controls. Without them the design states mechanics the
                 # strategy nowhere does, and `design_adds_no_foreign_mechanic` is right to
                 # refuse it.
                 "gameplay_direction": " ".join(
                     [m["name"] for m in mvp] + [r for m in mvp for r in m["rules"]]
                     + [f"{x['action']} {x['touch']}" for x in a["actions"]
                        if x["tier"] == "mvp"])},
        research=research_block(family, constraints), **changes)


def design_for(family, strategy=None, **params):
    result = design_tests.run_step(strategy or strategy_for(family), params=params or None)
    return result


def units(design, tier=None):
    listed = design["build_spec"]["content"]["units"]
    return [u for u in listed if tier is None or u["tier"] == tier]


def breached(design):
    return [r["criterion_id"] for r in design["consistency"]["rule_results"]
            if r.get("breached")]


class EveryFamilySeed(unittest.TestCase):
    """The eight families, each designed through the real step."""

    @classmethod
    def setUpClass(cls):
        cls.designs = {}
        cls.results = {}
        for family in FAMILIES:
            cls.results[family] = design_for(family)

    def test_mechanics_are_introduced_one_per_unit_never_piled_into_the_opener(self):
        """core/craft "Introduce one mechanic per unit at most" and L29: after the opening
        unit each MVP unit debuts at most one mechanic, never on the climax or the last MVP
        unit; the opener takes only what the MVP has no other unit for (seed._introductions,
        which caps at the family's MVP unit count)."""
        for family in FAMILIES:
            with self.subTest(family=family):
                design = self.results[family].artifacts[0].content
                mvp = units(design, "mvp")
                mechanics = [m["id"] for m in design["build_spec"]["mechanics"]
                             if m["tier"] == "mvp"]
                slots = [u for u in mvp[1:-1] if u.get("purpose") in seed.INTRODUCE_IN]
                for unit in mvp[1:]:
                    self.assertLessEqual(len(unit.get("introduces") or []), 1, unit["id"])
                    if unit.get("introduces"):
                        self.assertNotEqual(unit.get("purpose"), "climax", unit["id"])
                self.assertFalse(mvp[-1].get("introduces"))
                self.assertEqual(len(mvp[0]["introduces"]),
                                 max(1, len(mechanics) - len(slots)))
                self.assertLessEqual(len(mvp[0]["introduces"]), 2)

    def test_every_family_seed_designs_a_valid_design_through_the_step(self):
        for family in FAMILIES:
            with self.subTest(family=family):
                result = self.results[family]
                self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
                design = result.artifacts[0].content
                self.assertEqual(design["genre"]["family"], family)
                self.assertEqual(design["build_spec"]["content"]["unit_kind"],
                                 design["scope"]["content_unit_kind"])
                self.assertEqual(breached(design), [])
                measured = {r["criterion_id"] for r in design["consistency"]["rule_results"]}
                self.assertTrue({rule_id for rule_id, _ in content.RULES} <= measured)

    def test_every_family_carries_its_minimum_content(self):
        for family, bars in ((f, FAMILIES[f]["units"]) for f in FAMILIES):
            with self.subTest(family=family):
                design = self.results[family].artifacts[0].content
                self.assertGreaterEqual(len(units(design, "mvp")), bars["min_mvp"])
                self.assertGreaterEqual(len(units(design)), bars["min_total"])
                self.assertEqual(design["scope"]["content_units"], len(units(design)))

    def test_the_design_records_the_content_it_got_from_research(self):
        for family in FAMILIES:
            with self.subTest(family=family):
                design = self.results[family].artifacts[0].content
                applied = {entry["field"]: entry for entry in design["research"]["applied"]}
                for field in ("genre.family", "build_spec.content",
                              "build_spec.difficulty.axes"):
                    self.assertIn(field, applied)
                    self.assertIn(applied[field]["source"], ("research", "default"))

    def test_mastery_is_read_from_hud_metrics_the_mvp_shows(self):
        for family in FAMILIES:
            with self.subTest(family=family):
                spec = self.results[family].artifacts[0].content["build_spec"]
                shown = {element.get("metric") or element["id"] for element in spec["hud"]
                         if element["tier"] == "mvp"}
                shown |= {element["id"] for element in spec["hud"]
                          if element["tier"] == "mvp"}
                self.assertEqual(spec["mastery"]["model"],
                                 FAMILIES[family]["mastery"]["model"])
                self.assertTrue(spec["mastery"]["signals"])
                self.assertTrue(set(spec["mastery"]["signals"]) <= shown,
                                spec["mastery"]["signals"])

    def test_acceptance_lines_stay_further_apart_than_the_bar(self):
        """The generator's own guard, measured: two units a tester cannot tell apart are one."""
        bar = MODELS["variety"]["acceptance_max_similarity"]
        for family in FAMILIES:
            with self.subTest(family=family):
                design = self.results[family].artifacts[0].content
                lines = [(u["id"], line, content._tokens(line))
                         for u in units(design) for line in u["acceptance"]]
                worst, pair = 0.0, None
                for left, right in itertools.combinations(lines, 2):
                    alike = (len(left[2] & right[2]) / float(len(left[2] | right[2]))
                             if left[2] and right[2] else 0.0)
                    if alike > worst:
                        worst, pair = alike, (left, right)
                self.assertLess(worst, bar, pair)


class TheTemplatesRenderAsSentences(unittest.TestCase):
    """The regression: one `{k}` meant seconds in one template and kinds of enemy in the next,
    so a wave asked the player to hold off "4 enemies of 54 kinds". Each placeholder now names
    one meaning, and the scale a family counts in is the family's own - 24 is a move budget,
    180 is a gold budget, and neither is the other.
    """

    def scales(self, family):
        """The numbers this family counts in: its `seed.units.numbers` over the defaults."""
        stated = (FAMILIES[family]["seed"]["units"].get("numbers") or {})
        return {name: dict(default, **(stated.get(name) or {}))
                for name, default in seed.NUMBERS.items()}

    @staticmethod
    def templates(family):
        block = FAMILIES[family]["seed"]["units"]
        return (list(block["objective_templates"]) + list(block["acceptance_templates"])
                + [block["success_template"], block["failure_template"]])

    def test_every_placeholder_is_one_the_author_can_fill(self):
        for family in FAMILIES:
            with self.subTest(family=family):
                for template in self.templates(family):
                    for name in re.findall(r"\{([a-z_]+)\}", str(template)):
                        self.assertIn(name, seed.PLACEHOLDERS, template)
                for name, scale in (FAMILIES[family]["seed"]["units"].get("numbers")
                                    or {}).items():
                    self.assertIn(name, seed.NUMBERS, family)
                    self.assertEqual(sorted(scale), ["max", "start", "step"], name)
                    self.assertLessEqual(scale["start"], scale["max"], name)
                    self.assertGreater(scale["start"], 0, name)

    def test_a_template_asking_for_something_undefined_is_refused_by_name(self):
        block = copy.deepcopy(FAMILIES["arcade"])
        block["seed"]["units"]["objective_templates"] = ["Survive {unit} for {k} s"]
        with self.assertRaises(Exception) as caught:
            GenreSeedAuthor().synthesize("arcade", MODELS, strategy_for("arcade"), block)
        self.assertIn("{k}", str(caught.exception))
        self.assertIn("placeholder", str(caught.exception))

    def test_every_unit_states_numbers_a_player_could_read(self):
        for family in FAMILIES:
            with self.subTest(family=family):
                scales = self.scales(family)
                resolved = GenreSeedAuthor().synthesize(family, MODELS, strategy_for(family),
                                                        FAMILIES[family])
                for unit in resolved.archetype["content"]["units"]:
                    index = unit["index"] - 1
                    numbers = {name: min(s["max"], s["start"] + s["step"] * index)
                               for name, s in scales.items()}
                    # Kinds of thing are a handful, and never more than the things themselves:
                    # "4 enemies of 54 kinds" is the sentence this bar exists to refuse.
                    self.assertLessEqual(numbers["kinds"], 4, unit["id"])
                    self.assertLessEqual(numbers["kinds"], numbers["count"], unit["id"])
                    self.assertLessEqual(numbers["few"], 8, unit["id"])
                    self.assertLessEqual(numbers["level"], 8, unit["id"])
                    # Nothing was left unrendered.
                    for field in ("objective", "success", "failure"):
                        self.assertNotIn("{", unit[field], (unit["id"], field))
                        self.assertNotIn("}", unit[field], (unit["id"], field))
                    for line in unit["acceptance"]:
                        self.assertNotIn("{", line, unit["id"])

    def test_the_last_mvp_unit_does_not_ask_what_the_first_asked(self):
        for family in FAMILIES:
            with self.subTest(family=family):
                resolved = GenreSeedAuthor().synthesize(family, MODELS, strategy_for(family),
                                                        FAMILIES[family])
                mvp = [u for u in resolved.archetype["content"]["units"]
                       if u["tier"] == "mvp"]
                if len(FAMILIES[family]["seed"]["units"]["objective_templates"]) <= 2:
                    self.skipTest("too few templates to choose between")
                # Compared with the unit ids taken out: the same sentence at higher numbers is
                # the scaling the variety bars refuse, whichever unit it names.
                def shape(unit):
                    return re.sub(r"[a-z]-\d\d", "{unit}", unit["objective"])
                self.assertNotEqual(shape(mvp[-1]), shape(mvp[0]), [u["objective"] for u in mvp])
                self.assertNotEqual(shape(mvp[-1]), shape(mvp[-2]),
                                    [u["objective"] for u in mvp])


class TheSeedRefusesAnIdeaItCannotDesign(unittest.TestCase):
    """A catalog entry that names only a family is a capability, and the strategy then carries
    the person's idea as the concept. The seed is one game of that family; designing it would
    describe a different game, which the consistency rules refuse. It says so up front."""

    def test_a_brief_led_concept_needs_the_agent_author(self):
        from wgf_design.authors import AuthorError
        strategy = strategy_for("simulation")
        idea = "A lemonade-stand tycoon: price, upgrades, staff and market events"
        strategy["brief"] = idea
        strategy["concept"]["core_mechanic"] = idea
        with self.assertRaises(AuthorError) as caught:
            GenreSeedAuthor()._resolve({"strategy": strategy, "platforms": [],
                                        "params": {}, "title_id": "t"})
        self.assertIn("agent author", str(caught.exception))

    def test_the_agent_authors_starting_point_takes_the_seed_for_an_idea(self):
        # /new-game with an idea in a family no archetype carries: the agent author starts
        # from the seed's shape and rewrites it into the idea, so the seed must not refuse.
        strategy = strategy_for("simulation")
        idea = "A lemonade-stand tycoon: price, upgrades, staff and market events"
        strategy["brief"] = idea
        strategy["concept"]["core_mechanic"] = idea
        resolved = GenreSeedAuthor(starting_point=True)._resolve(
            {"strategy": strategy, "platforms": [], "params": {}, "title_id": "t"})
        self.assertTrue(resolved.archetype["mechanics"])

    def test_a_catalog_concept_is_designed_as_before(self):
        strategy = strategy_for("simulation")
        strategy["brief"] = "a tycoon game"
        resolved = GenreSeedAuthor()._resolve({"strategy": strategy, "platforms": [],
                                               "params": {}, "title_id": "t"})
        self.assertTrue(resolved.archetype["mechanics"])


class TheSeedIsDeterministic(unittest.TestCase):
    def test_seed_is_deterministic(self):
        strategy = strategy_for("shooter")
        first = GenreSeedAuthor().synthesize("shooter", MODELS, strategy, FAMILIES["shooter"])
        second = GenreSeedAuthor().synthesize("shooter", MODELS, strategy, FAMILIES["shooter"])
        self.assertEqual(first.archetype, second.archetype)
        self.assertEqual(first.experience, second.experience)
        self.assertEqual(first.depth, second.depth)
        self.assertEqual(first.why, second.why)
        self.assertEqual(first.applied, second.applied)

    def test_two_runs_of_the_step_produce_the_same_artifact(self):
        strategy = strategy_for("racing")
        one = design_for("racing", strategy).artifacts[0].content
        two = design_for("racing", copy.deepcopy(strategy)).artifacts[0].content
        self.assertEqual(one["provenance"]["content_hash"], two["provenance"]["content_hash"])

    def test_the_family_model_does_not_leak_into_the_archetype_it_came_from(self):
        """`synthesize` never edits the reference data it reads."""
        before = copy.deepcopy(FAMILIES["puzzle"])
        resolved = GenreSeedAuthor().synthesize("puzzle", MODELS, strategy_for("puzzle"),
                                                FAMILIES["puzzle"])
        resolved.archetype["content"]["units"][0]["objective"] = "mutated"
        self.assertEqual(FAMILIES["puzzle"], before)


class TheUnitsFollowTheArc(unittest.TestCase):
    def test_seed_units_follow_the_arc_and_rules(self):
        for family, block in FAMILIES.items():
            with self.subTest(family=family):
                strategy = strategy_for(family)
                resolved = GenreSeedAuthor().synthesize(family, MODELS, strategy, block)
                listed = resolved.archetype["content"]["units"]
                mvp = [u for u in listed if u["tier"] == "mvp"]
                arc = block["seed"]["units"]["unit_arc"]
                profile = MODELS["session_profiles"]["casual"]

                self.assertEqual(len(mvp), block["units"]["min_mvp"] + 1)
                self.assertEqual(len(listed), max(block["units"]["min_total"], len(mvp)))
                self.assertEqual(mvp[0]["purpose"], arc[0])
                self.assertEqual(mvp[-1]["purpose"], arc[-1])
                self.assertEqual([u["index"] for u in listed],
                                 list(range(1, len(listed) + 1)))

                # Mechanics are introduced by a teaching unit and then accumulate.
                order = block["seed"]["units"]["introduce_order"]
                taught = []
                for unit in mvp:
                    if unit["purpose"] == "teach":
                        self.assertTrue(unit.get("introduces"), unit["id"])
                    taught += unit.get("introduces") or []
                    self.assertEqual(unit["mechanics"], taught)
                self.assertEqual(sorted(taught), sorted(order))

                # Every unit after the first changes a dimension the family names.
                dimensions = set(block["variety"]["dimensions"])
                self.assertEqual(mvp[0]["variation_from_previous"], [])
                for unit in mvp[1:]:
                    changed = set(unit["variation_from_previous"]) & dimensions
                    self.assertTrue(changed, unit["id"])
                    if "introduces" in unit["variation_from_previous"]:
                        self.assertTrue(unit.get("introduces"), unit["id"])

                # Durations: inside the profile, the first one short, and all distinct so no
                # two units accept the same thing.
                durations = [u["expected_duration_s"] for u in listed]
                self.assertEqual(len(set(durations)), len(durations))
                self.assertLessEqual(max(durations), profile["max_unit_s"])
                self.assertLessEqual(durations[0], profile["max_unit_s"] / 2.0)
                self.assertLessEqual(sum(u["expected_duration_s"] for u in mvp),
                                     3 * strategy["session"]["target_seconds"])

    def test_difficulty_rises_with_relief_inside_the_profile(self):
        for family, block in FAMILIES.items():
            with self.subTest(family=family):
                resolved = GenreSeedAuthor().synthesize(family, MODELS, strategy_for(family),
                                                        block)
                mvp = [u for u in resolved.archetype["content"]["units"]
                       if u["tier"] == "mvp"]
                profile = MODELS["session_profiles"]["casual"]
                cap = profile["max_axes_raised_per_unit"]
                dip = block.get("variety", {}).get("relief_dip_max",
                                                   MODELS["variety"]["relief_dip_max"])
                escalating = [a["id"] for a in block["axes"] if a.get("escalates")]
                for axis in escalating:
                    series = [u["difficulty"][axis] for u in mvp]
                    self.assertGreater(series[-1], series[0], axis)
                    for position in range(1, len(series)):
                        if series[position] < series[position - 1]:
                            self.assertLessEqual(series[position - 1] - series[position],
                                                 dip * series[position - 1])
                            recovered = series[position + 1:position + 3]
                            self.assertTrue(any(v >= series[position - 1] for v in recovered),
                                            (axis, position))
                for position in range(1, len(mvp)):
                    if mvp[position]["purpose"] == "climax":
                        continue
                    before, now = mvp[position - 1]["difficulty"], mvp[position]["difficulty"]
                    raised = [k for k in now if now[k] > before.get(k, now[k])]
                    self.assertLessEqual(len(raised), cap, (mvp[position]["id"], raised))
                breathers = [p for p, u in enumerate(mvp) if u["purpose"] == "breather"]
                run = 0
                for position, unit in enumerate(mvp):
                    before = mvp[position - 1]["difficulty"] if position else unit["difficulty"]
                    raised = [k for k in unit["difficulty"]
                              if position and unit["difficulty"][k] > before.get(k, 0)]
                    run = 0 if (unit["purpose"] == "breather" or not raised) else run + 1
                    self.assertLessEqual(run, profile["relief_every_units"],
                                         (unit["id"], breathers))

    def test_casual_profile_tightens_units(self):
        """A casual audience in short bursts gets shorter units and one axis raised at a time;
        the same family on a standard session may run longer."""
        family = "survival"      # run_seconds 180, longer than a casual unit may be
        block = FAMILIES[family]
        casual = GenreSeedAuthor().synthesize(
            family, MODELS, strategy_for(family), block).archetype["content"]["units"]
        standard = GenreSeedAuthor().synthesize(
            family, MODELS,
            strategy_for(family, audience={"type": "midcore", "device": "both",
                                           "player_description": "FIXTURE"},
                         session={"target_seconds": 900, "first_session_seconds": 600,
                                  "sessions_per_day_target": 2}),
            block).archetype["content"]["units"]
        self.assertLessEqual(max(u["expected_duration_s"] for u in casual),
                             MODELS["session_profiles"]["casual"]["max_unit_s"])
        self.assertGreater(max(u["expected_duration_s"] for u in standard),
                           MODELS["session_profiles"]["casual"]["max_unit_s"])
        result = design_for(family)
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
        self.assertEqual(result.artifacts[0].content["genre"]["session_profile"], "casual")

    def test_a_brief_with_design_gaps_is_refused(self):
        strategy = strategy_for("puzzle")
        platforms = design_tests.load_platforms(strategy, None)
        brief = {"title_id": "fixture", "strategy": strategy, "platforms": platforms,
                 "params": {}, "gaps": [{"field": "build_spec.content", "question": "which?"}]}
        for author in (archetypes and GenreSeedAuthor(), ):
            with self.assertRaises(Exception) as caught:
                author.draft(brief)
            self.assertIn("design gaps need the agent author", str(caught.exception))


class EveryArchetypeEmitsItsContent(unittest.TestCase):
    def test_every_archetype_emits_content_and_holds(self):
        for archetype_id, a in archetypes.ARCHETYPES.items():
            with self.subTest(archetype=archetype_id):
                self.assertIn(a["genre"]["family"], FAMILIES)
                self.assertTrue(a["difficulty_axes"])
                self.assertTrue(a["mastery"]["statement"])
                self.assertTrue(a["content"]["units"])
                for mechanic in a["mechanics"]:
                    self.assertIn(mechanic["progression_role"],
                                  ("core", "introduced", "variation", "mastery"))
                result = design_tests.run_step(design_tests.coherent(archetype_id),
                                               params={"archetype": archetype_id})
                self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
                design = result.artifacts[0].content
                self.assertEqual(design["genre"]["family"], a["genre"]["family"])
                self.assertEqual(design["genre"]["session_profile"], "casual")
                self.assertEqual(breached(design), [])
                problems, _results = content.check(design, design_tests.coherent(archetype_id),
                                                   MODELS)
                self.assertEqual(problems, [])

    def test_the_axes_are_declared_from_the_family_and_valued_on_the_units(self):
        for archetype_id, a in archetypes.ARCHETYPES.items():
            with self.subTest(archetype=archetype_id):
                family = FAMILIES[a["genre"]["family"]]
                result = design_tests.run_step(design_tests.coherent(archetype_id),
                                               params={"archetype": archetype_id})
                spec = result.artifacts[0].content["build_spec"]
                declared = {axis["id"]: axis for axis in spec["difficulty"]["axes"]}
                self.assertEqual(sorted(declared), sorted(a["difficulty_axes"]))
                for axis in family["axes"]:
                    if axis["id"] in declared:
                        self.assertEqual(declared[axis["id"]]["range"], list(axis["range"]))
                for unit in spec["content"]["units"]:
                    self.assertTrue(set(unit["difficulty"]) <= set(declared), unit["id"])


class TheEscalationRulesHoldTogether(unittest.TestCase):
    """content.axes_monotone_with_relief is satisfiable at every tier, with the session
    profile's `max_axes_raised_per_unit` binding the same units: the seed author's design,
    held at tier release, passes the escalation rules for every family on both profiles. A
    rule the seed cannot meet is one an agent author cannot repair its way out of either (the
    3D run of 2026-10-05 oscillated between the per-unit cap and an MVP-only rise)."""

    STANDARD = {"audience": {"type": "midcore", "device": "both",
                             "player_description": "FIXTURE"},
                "session": {"target_seconds": 900, "first_session_seconds": 600,
                            "sessions_per_day_target": 2}}
    RULES = ("content.axes_declared", "content.axes_monotone_with_relief")

    def test_every_family_seed_holds_the_escalation_rules_at_release(self):
        for family in sorted(FAMILIES):
            for profile, changes in (("casual", {}), ("standard", self.STANDARD)):
                with self.subTest(family=family, profile=profile):
                    strategy = strategy_for(family, **changes)
                    result = design_for(family, strategy)
                    self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
                    design = copy.deepcopy(result.artifacts[0].content)
                    self.assertEqual(design["genre"]["session_profile"], profile)
                    design["build_spec"]["content"]["quality_tier"] = "release"
                    listed = units(design)
                    self.assertGreater(len([u for u in listed if u["tier"] != "optional"]),
                                       len(units(design, "mvp")))
                    _problems, results = content.check(design, strategy, MODELS)
                    held = {r["criterion_id"]: r for r in results
                            if r["criterion_id"] in self.RULES}
                    self.assertEqual(sorted(held), sorted(self.RULES))
                    for rule_id, rule in held.items():
                        self.assertFalse(rule["breached"], (rule_id, rule["note"]))
                    self.assertIn("release unit(s)",
                                  held["content.axes_monotone_with_relief"]["note"])


if __name__ == "__main__":
    unittest.main()

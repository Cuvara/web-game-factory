"""The content contract: every unit of play a design commits to (game-design 1.9.0
build_spec.content; scripts/wgf_design/content.py, bars in core/reference/genre-models.yaml).

Both reference games were one screen and a ramp: a design could say "levels get harder" and
nothing in the Factory asked which levels. The design step now resolves the game's genre
family and holds its unit list to that family's bars - the unit kind, the generation mode, the
progression and difficulty models, the ending, how many units the MVP and the release carry,
how long a unit runs, which mechanics each unit asks for and when they are taught, how
difficulty moves on the family's axes, and whether two units can be told apart.

Every test builds its own design: `authored_design(family)` satisfies every rule, and each
test breaks exactly one thing and names the rule that must catch it. A design that names no
family and whose strategy names no genre is a design written before 1.9.0: one warning, no
problems, no bar applied.

    python -m unittest scripts.tests.test_design_content
"""

import copy
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, HERE)

from wgflib import criteria, jsonschema_lite  # noqa: E402
from wgf_design import consistency, content  # noqa: E402
from wgf_design import features as feature_check  # noqa: E402

MODELS = content.load_models()
VOCABULARY = content.load_vocabulary()

# Words that make one unit's acceptance line read differently from the next one's.
NOUNS = ("gap", "ramp", "turn", "drop", "gate", "ridge", "bend", "slope", "ledge", "kink",
         "chute", "spine", "notch", "crest", "hook", "loop", "fork", "wedge", "coil", "arc",
         "step", "rise", "dip", "shelf")
ACCEPTANCE = (
    "{Kind} {n} is cleared in {d} s by a competent player who reads its {noun}",
    "{Kind} {n} offers at most {k} hazards around its {noun}",
    "A bot holding one input survives {d} s of {kind} {n} and dies at the {noun}",
    "{Kind} {n} shows {k} distinct {noun} shapes before it ends",
)


# -- the fixture -------------------------------------------------------------------------

def _durations(count, max_unit_s):
    """Rising, inside the session profile, with the first unit half a unit at most."""
    out = [min(24, int(max_unit_s // 2))]
    for index in range(1, count):
        out.append(min(int(max_unit_s) - 5, 24 + 6 * index))
    return out


def _is_breather(index, count, profile):
    every = profile.get("relief_every_units")
    return bool(index and every and index % every == 0 and index != count - 1)


def _difficulty(fam, profile, count):
    """One difficulty reading per MVP unit: every escalating axis raised at least once, at most
    `max_axes_raised_per_unit` raised between consecutive units, no dip, and a breather
    whenever the profile asks for one. The last unit is the climax, which the profile's cap
    does not bind, so whatever has not been raised yet is raised there."""
    axes = fam["axes"]
    escalating = [a["id"] for a in axes if a.get("escalates")]
    cap = profile.get("max_axes_raised_per_unit") or 1
    series = [{a["id"]: round(0.15 + 0.05 * index, 2) for index, a in enumerate(axes)}]
    cursor = 0
    for index in range(1, count):
        if _is_breather(index, count, profile):
            series.append(dict(series[-1]))          # a breather raises nothing
            continue
        nxt = dict(series[-1])
        for _ in range(cap):
            axis = escalating[cursor % len(escalating)]
            cursor += 1
            nxt[axis] = round(min(0.95, nxt[axis] + 0.12), 2)
        series.append(nxt)
    if len(series) > 1:
        for axis in escalating:
            if series[-1][axis] <= series[0][axis]:
                series[-1][axis] = round(min(0.95, series[-2][axis] + 0.12), 2)
    return series


def _purpose(index, count, breather):
    if breather:
        return "breather"
    if index == 0:
        return "teach"
    if index == count - 1:
        return "climax"
    return "test" if index % 2 else "twist"


def content_body(family="arcade", n_units=None, n_total=None, profile="standard",
                 mechanics=None, signals=None, models=None):
    """The content a design of `family` must state, built so every content.* rule holds.

    `mechanics` are the MVP mechanic ids the units ask for (the fixture's own by default);
    `signals` the mvp hud ids mastery is read from (the family's by default).
    """
    models = models or MODELS
    fam = models["families"][family]
    bars = models["session_profiles"][profile]
    kind = fam["unit_kinds"][0]
    label = kind.replace("-", " ")
    count = n_units or fam["units"]["min_mvp"]
    total = n_total if n_total is not None else max(count, fam["units"]["min_total"])
    pool = list(mechanics or [f"m-{index:02d}" for index in range(1, max(2, count))])
    used = pool[:max(1, min(len(pool), count - 1))]
    dimensions = list(fam["variety"]["dimensions"])
    durations = _durations(total, bars["max_unit_s"])
    readings = _difficulty(fam, bars, count)

    units = []
    for index in range(total):
        number = index + 1
        noun = NOUNS[index % len(NOUNS)]
        mvp = index < count
        reading = readings[index] if mvp else dict(readings[-1])
        breather = mvp and _is_breather(index, count, bars)
        unit = {
            "id": f"u-{number:02d}",
            "index": number,
            "tier": "mvp" if mvp else "post-mvp",
            "purpose": _purpose(index, count, breather) if mvp else "bonus",
            "objective": f"Clear {label} {number} without losing the {noun}",
            "start_state": f"The {noun} is laid out as {label} {number} declares it",
            "end_state": f"{label.capitalize()} {number} is behind the player",
            "mechanics": list(used[:min(index + 1, len(used))]) if mvp else list(used),
            "introduces": [used[index]] if mvp and index < len(used) else [],
            "difficulty": reading,
            "expected_duration_s": durations[index],
            "success": f"The {noun} of {label} {number} is passed with its goal counter at zero",
            "failure": f"The player runs out of room at the {noun} and restarts {label} {number}",
            "acceptance": [
                ACCEPTANCE[index % len(ACCEPTANCE)].format(
                    Kind=label.capitalize(), kind=label, n=number, d=durations[index],
                    k=3 + index, noun=noun),
                ACCEPTANCE[(index + 1) % len(ACCEPTANCE)].format(
                    Kind=label.capitalize(), kind=label, n=number, d=durations[index],
                    k=4 + index, noun=noun),
            ],
            "variation_from_previous": [dimensions[index % len(dimensions)],
                                        dimensions[(index + 1) % len(dimensions)]],
            "parameters": {"seed": number},
        }
        if index == 0:
            unit["variation_from_previous"] = []
        units.append(unit)

    hud_signals = list(signals or fam["mastery"]["signals"])
    return {
        "family": family,
        "kind": kind,
        "total": total,
        "mvp": count,
        "genre": {"family": family, "node": fam["nodes"][0], "session_profile": profile,
                  "ending": fam["ending"][0]},
        "content": {"unit_kind": kind, "generation": {"mode": "authored"}, "units": units},
        "mastery": {"model": fam["mastery"]["model"],
                    "statement": "A better player reads the next unit before it arrives and "
                                 "spends fewer attempts on it.",
                    "signals": hud_signals},
        "axes": [{"id": a["id"], "range": list(a["range"]), "description": a["description"],
                  "relief_allowed": not a.get("escalates")} for a in fam["axes"]],
        "mechanics": [{"id": mid, "name": f"Mechanic {mid}", "tier": "mvp",
                       "description": f"What {mid} does", "rules": [f"{mid} is deterministic"]}
                      for mid in pool] + [
            {"id": "m-late", "name": "Later mechanic", "tier": "post-mvp",
             "description": "Production only", "rules": ["Not in the prototype"]}],
        "hud": [{"id": signal, "tier": "mvp", "shows": f"The {signal}", "anchor": "top-left",
                 "metric": signal} for signal in hud_signals],
        "progression_model": fam["progression_models"][0],
        "difficulty_model": fam["difficulty_models"][0],
    }


def authored_design(family="arcade", n_units=None, n_total=None, profile="standard",
                    models=None, **tweaks):
    """A design of `family` that holds against every content rule. Tests break one thing."""
    body = content_body(family, n_units, n_total, profile, models=models)
    fam = (models or MODELS)["families"][family]
    design = {
        "title_id": "fixture",
        "genre": body["genre"],
        "core_loop": "Play a unit, read what it asks, clear it, meet the next one.",
        "scope": {"content_units": body["total"], "content_unit_kind": body["kind"],
                  "locales": ["en"], "tiers": {"mvp": [], "prototype": [], "production": [],
                                               "out_of_scope": []}},
        "session": {"target_seconds": 180, "first_session_seconds": 300,
                    "time_to_first_play_s": 5, "time_to_first_reward_s": 10,
                    "structure": "A session is a handful of units."},
        "build_spec": {
            "mechanics": body["mechanics"],
            "content": body["content"],
            "mastery": body["mastery"],
            "hud": body["hud"],
            "progression": {"model": body["progression_model"], "steps": []},
            "difficulty": {"model": body["difficulty_model"], "axes": body["axes"],
                           "curve": [{"at": "unit 1", "description": "The opening reading"}]},
            "experience": {"goal": {"statement": "Clear the unit", "metric": body["hud"][0]["id"],
                                    "shown_on": "play"},
                           "lose": {"condition": "The unit is lost"}},
            "depth": {"content_schedule": [{"id": "c-late", "tier": "post-mvp"}]},
        },
    }
    if body["genre"]["ending"] == "finite":
        design["build_spec"]["experience"]["win"] = {
            "condition": f"Every {body['kind']} of the {fam['label'].lower()} is cleared",
            "metric": body["hud"][0]["id"]}
    design.update(copy.deepcopy(tweaks))
    return design


def strategy_for(family="arcade", via="concept", models=None):
    """A strategy that names `family`, the way each source in resolve_family's order does."""
    models = models or MODELS
    fam = models["families"][family]
    if via == "concept":
        return {"concept": {"genre": fam["nodes"][0], "core_loop": "Play a unit."}}
    if via == "subgenre":
        return {"concept": {"genre": "casual", "subgenre": fam["nodes"][-1]}}
    if via == "content_model":
        return {"concept": {"genre": "casual", "content_model": {"family": family,
                                                                 "source": "research"}}}
    if via == "capability":
        return {"research": {"research_version": 2,
                             "capability": {"buildable": True, "genre_model": family,
                                            "reason": "the catalog builds it"}}}
    if via == "gameplay":
        return {"research": {"research_version": 2, "capability": {},
                             "gameplay": {"genre": {"value": fam["nodes"][-1],
                                                    "tier": "observed"}}}}
    if via == "label":
        return {"concept": {"genre": fam["label"].split()[0].lower()}}
    raise AssertionError(via)


def units(design):
    return design["build_spec"]["content"]["units"]


def mvp(design):
    return [unit for unit in units(design) if unit["tier"] == "mvp"]


def unit(design, unit_id):
    return next(u for u in units(design) if u["id"] == unit_id)


class ContentCase(unittest.TestCase):
    """Breaks one thing in a holding design and names the rule that must catch it."""

    family = "arcade"

    def design(self, **kwargs):
        return authored_design(kwargs.pop("family", self.family), **kwargs)

    def strategy(self, via="concept", family=None):
        return strategy_for(family or self.family, via)

    def check(self, design, strategy=None, models=None):
        return content.check(design, strategy or self.strategy(), models or MODELS, VOCABULARY)

    def holds(self, design, strategy=None, models=None):
        problems, _results = self.check(design, strategy, models)
        self.assertEqual(problems, [])

    def breaches(self, design, rule_id, fragment=None, strategy=None, models=None):
        """The problems the rule produced, asserting it is among them."""
        problems, results = self.check(design, strategy, models)
        named = [p for p in problems if p.startswith(f"[{rule_id}] ")]
        self.assertTrue(named, f"{rule_id} did not breach; problems were: {problems}")
        result = next(r for r in results if r["criterion_id"] == rule_id)
        self.assertTrue(result["breached"], result)
        if fragment:
            self.assertIn(fragment, "\n".join(named))
        return named


# -- the family resolves, or the design is from before 1.9.0 -----------------------------

class TheModelResolves(ContentCase):
    def test_every_family_has_a_design_that_holds(self):
        for family in sorted(MODELS["families"]):
            with self.subTest(family=family):
                self.holds(authored_design(family), strategy_for(family))

    def test_every_family_holds_on_the_casual_profile(self):
        for family in sorted(MODELS["families"]):
            with self.subTest(family=family):
                self.holds(authored_design(family, profile="casual"), strategy_for(family))

    def test_each_source_in_turn_resolves_the_family(self):
        for via in ("concept", "subgenre", "content_model", "capability", "gameplay", "label"):
            with self.subTest(via=via):
                family, why = content.resolve_family(strategy_for("racing", via), {}, MODELS,
                                                     VOCABULARY)
                self.assertEqual(family, "racing", why)
                self.assertTrue(why)

    def test_the_design_outranks_the_strategy(self):
        family, why = content.resolve_family(strategy_for("racing"), {"genre": {"family": "puzzle"}},
                                             MODELS, VOCABULARY)
        self.assertEqual(family, "puzzle")
        self.assertIn("the design names it", why)

    def test_a_design_node_resolves_when_it_names_no_family(self):
        family, why = content.resolve_family(None, {"genre": {"node": "lane-runner"}}, MODELS,
                                             VOCABULARY)
        self.assertEqual(family, "arcade")
        self.assertIn("lane-runner", why)

    def test_legacy_design_without_family_is_one_warning_and_no_problems(self):
        """A design written before 1.9.0, under a strategy that names no genre either: the bars
        are not applied, and the one result says so."""
        for strategy in (None, {}, {"concept": {"genre": "io"}}):
            with self.subTest(strategy=strategy):
                problems, results = content.check({"build_spec": {}}, strategy, MODELS, VOCABULARY)
                self.assertEqual(problems, [])
                self.assertEqual([r["criterion_id"] for r in results],
                                 ["content.model_resolves"])
                self.assertIs(results[0]["breached"], False)
                self.assertIn("no genre family", results[0]["note"])

    def test_a_family_nothing_defines_is_a_problem_and_nothing_else_is_checked(self):
        design = self.design()
        design["genre"]["family"] = "roguelike"
        problems, results = content.check(design, None, MODELS, VOCABULARY)
        self.assertEqual(len(problems), 1)
        self.assertIn("[content.model_resolves] genre.family is 'roguelike', which "
                      "core/reference/genre-models.yaml does not define", problems[0])
        self.assertEqual(len(results), len(content.RULES))
        self.assertTrue(all(r["breached"] for r in results))
        self.assertIn("not checked", results[-1]["note"])

    def test_the_family_is_recorded_by_id_and_version(self):
        self.assertEqual(content.content_model_record(MODELS, "arcade"),
                         {"id": "arcade", "version": str(MODELS["version"])})


class TheBlockIsPresent(ContentCase):
    def test_a_resolved_family_with_no_genre_block(self):
        design = self.design()
        del design["genre"]
        self.breaches(design, "content.block_present", "genre is missing")

    def test_a_genre_that_names_a_node_but_no_family(self):
        design = self.design()
        del design["genre"]["family"]
        self.breaches(design, "content.block_present",
                      "genre.family is None but this design resolves to 'arcade'")

    def test_a_genre_that_does_not_say_whether_play_ends(self):
        design = self.design()
        del design["genre"]["ending"]
        self.breaches(design, "content.block_present", "genre.ending is missing")

    def test_no_content_block_leaves_the_unit_rules_unchecked(self):
        design = self.design()
        del design["build_spec"]["content"]
        problems, results = self.check(design)
        self.assertTrue(any(p.startswith("[content.block_present]") for p in problems))
        self.assertIn("build_spec.content is missing", "\n".join(problems))
        unchecked = [r for r in results if r["note"] == "not checked: build_spec.content is missing"]
        self.assertTrue(all(r["breached"] for r in unchecked))
        self.assertEqual({r["criterion_id"] for r in unchecked},
                         {"content.unit_kind_allowed", "content.generation_allowed",
                          "content.unit_count_mvp", "content.unit_count_total",
                          "content.units_fit_session", "content.ids_unique_index_monotone",
                          "content.mechanics_resolve",
                          "content.mechanics_introduced_before_use",
                          "content.mvp_mechanics_reused", "content.consecutive_units_differ",
                          "content.axes_declared", "content.axes_monotone_with_relief",
                          "content.objectives_vary", "content.win_lose_stated",
                          "content.acceptance_specific", "content.scope_count_agrees"})

    def test_a_family_that_requires_mastery_without_it(self):
        design = self.design()
        del design["build_spec"]["mastery"]
        self.breaches(design, "content.block_present", "build_spec.mastery is missing")


# -- what the family allows ---------------------------------------------------------------

class WhatTheFamilyAllows(ContentCase):
    def test_a_unit_kind_from_another_family(self):
        design = self.design()
        design["build_spec"]["content"]["unit_kind"] = "level"
        design["scope"]["content_unit_kind"] = "level"
        self.breaches(design, "content.unit_kind_allowed", "unit_kind is 'level'")

    def test_a_generation_mode_the_family_refuses(self):
        design = authored_design("puzzle")
        design["build_spec"]["content"]["generation"] = {"mode": "procedural",
                                                         "expected_units": 40}
        self.breaches(design, "content.generation_allowed", "generation.mode is 'procedural'",
                      strategy=strategy_for("puzzle"))

    def test_a_progression_model_the_family_refuses(self):
        design = authored_design("puzzle")
        design["build_spec"]["progression"]["model"] = "skill-only"
        self.breaches(design, "content.progression_model_allowed",
                      "build_spec.progression.model is 'skill-only'",
                      strategy=strategy_for("puzzle"))

    def test_a_difficulty_model_the_family_refuses(self):
        design = authored_design("puzzle")
        design["build_spec"]["difficulty"]["model"] = "adaptive"
        self.breaches(design, "content.difficulty_model_allowed",
                      "build_spec.difficulty.model is 'adaptive'",
                      strategy=strategy_for("puzzle"))

    def test_an_endless_puzzle(self):
        design = authored_design("puzzle")
        design["genre"]["ending"] = "endless"
        self.breaches(design, "content.ending_matches_model", "genre.ending is 'endless'",
                      strategy=strategy_for("puzzle"))

    def test_a_finite_game_that_never_says_how_it_is_won(self):
        design = authored_design("puzzle")
        del design["build_spec"]["experience"]["win"]
        self.breaches(design, "content.ending_matches_model",
                      "build_spec.experience.win is missing", strategy=strategy_for("puzzle"))

    def test_an_endless_arcade_needs_no_win(self):
        design = self.design()
        self.assertEqual(design["genre"]["ending"], "endless")
        self.assertNotIn("win", design["build_spec"]["experience"])
        self.holds(design)


# -- how much content, and how long ------------------------------------------------------

class HowMuchContent(ContentCase):
    def test_a_one_unit_prototype(self):
        design = self.design()
        for item in units(design)[1:]:
            item["tier"] = "post-mvp"
        self.breaches(design, "content.unit_count_mvp", "lists 1 mvp unit(s)")

    def test_a_procedural_design_is_counted_on_its_expected_units(self):
        design = self.design()
        design["build_spec"]["content"]["generation"] = {"mode": "procedural",
                                                         "expected_units": 2,
                                                         "parameters": {"rate": 1.5}}
        design["scope"]["content_units"] = 2
        self.breaches(design, "content.unit_count_mvp", "expected_units is 2")
        design["build_spec"]["content"]["generation"]["expected_units"] = 12
        design["scope"]["content_units"] = 12
        self.holds(design)

    def test_a_release_with_nothing_past_the_prototype(self):
        design = self.design()
        design["build_spec"]["content"]["units"] = mvp(design)
        design["scope"]["content_units"] = len(units(design))
        self.breaches(design, "content.unit_count_total", "unit(s) at any tier")

    def test_a_unit_longer_than_the_session_profile_allows(self):
        design = self.design(profile="casual")
        unit(design, "u-02")["expected_duration_s"] = 400
        self.breaches(design, "content.units_fit_session", "a casual session's longest unit is 90")

    def test_the_mvp_cannot_outrun_the_session_it_is_designed_for(self):
        design = self.design()
        design["session"]["target_seconds"] = 20
        self.breaches(design, "content.units_fit_session", "against a 20 s session")

    def test_the_first_unit_is_short(self):
        design = self.design()
        mvp(design)[0]["expected_duration_s"] = 200
        self.breaches(design, "content.units_fit_session", "the first unit a player meets")

    def test_ids_are_unique_and_the_index_runs_in_order(self):
        design = self.design()
        unit(design, "u-02")["id"] = "u-01"
        self.breaches(design, "content.ids_unique_index_monotone", "two units with the id 'u-01'")
        design = self.design()
        units(design)[1]["index"] = 1
        self.breaches(design, "content.ids_unique_index_monotone", "index runs 1, 2, 3")
        design = self.design()
        for item in units(design):
            item["index"] += 1
        self.breaches(design, "content.ids_unique_index_monotone", "the sequence starts at 1")


# -- mechanics -----------------------------------------------------------------------------

class Mechanics(ContentCase):
    family = "platformer"

    def test_a_mechanic_that_is_not_in_the_build_spec(self):
        design = self.design()
        unit(design, "u-03")["mechanics"] = ["wall-run"]
        self.breaches(design, "content.mechanics_resolve",
                      "build_spec.content.units[u-03].mechanics names 'wall-run', not a "
                      "build_spec.mechanics id")

    def test_an_mvp_unit_that_asks_for_a_post_mvp_mechanic(self):
        design = self.design()
        unit(design, "u-02")["mechanics"].append("m-late")
        self.breaches(design, "content.mechanics_resolve", "asks for 'm-late', which is post-mvp")

    def test_an_introduction_of_something_that_does_not_exist(self):
        design = self.design()
        unit(design, "u-02")["introduces"] = ["double-jump"]
        self.breaches(design, "content.mechanics_resolve",
                      "introduces names 'double-jump', not a build_spec.mechanics")

    def test_a_content_schedule_item_may_be_introduced(self):
        design = self.design()
        unit(design, "u-03")["introduces"].append("c-late")
        self.holds(design)

    def test_a_mechanic_relied_on_before_it_is_taught(self):
        design = self.design()
        last = [u["introduces"][0] for u in mvp(design) if u["introduces"]][-1]
        unit(design, "u-02")["mechanics"].append(last)
        self.breaches(design, "content.mechanics_introduced_before_use",
                      f"asks for {last!r}, which no unit up to here introduces")

    def test_a_mechanic_taught_once_and_dropped(self):
        design = self.design()
        for item in mvp(design)[2:]:
            item["mechanics"] = [m for m in item["mechanics"] if m != "m-01"] or ["m-02"]
        self.breaches(design, "content.mvp_mechanics_reused",
                      "'m-01' is asked for by 1 MVP unit(s)")

    def test_a_mechanic_introduced_by_the_last_unit_of_a_longer_prototype(self):
        design = self.design(n_units=MODELS["families"][self.family]["units"]["min_mvp"] + 1)
        last = mvp(design)[-1]
        last["introduces"] = ["m-late"]
        design["build_spec"]["mechanics"][-1]["tier"] = "mvp"
        last["mechanics"].append("m-late")
        self.breaches(design, "content.mvp_mechanics_reused",
                      "introduced by the last MVP unit and never asked for again")


# -- variety --------------------------------------------------------------------------------

class Variety(ContentCase):
    family = "strategy"

    def test_a_unit_that_declares_no_variety_dimension(self):
        design = self.design()
        unit(design, "u-03")["variation_from_previous"] = ["colour"]
        self.breaches(design, "content.consecutive_units_differ",
                      "variation_from_previous changes nothing of the family's variety dimensions")

    def test_a_run_of_units_that_change_only_their_numbers(self):
        design = self.design(n_units=6)
        first = mvp(design)[0]
        for item in mvp(design)[1:]:
            item["introduces"] = []
            item["objective"] = first["objective"]
            item["mechanics"] = list(first["mechanics"])
        problems = self.breaches(design, "content.consecutive_units_differ",
                                 "units[u-04] is unit 3 in a row that changes only its numbers")
        # The first two in a row are allowed; the third is where it breaches.
        self.assertNotIn("units[u-03] is unit", "\n".join(problems))

    def test_units_that_all_ask_for_the_same_thing(self):
        design = self.design()
        for item in mvp(design):
            item["objective"] = "Hold the lane until the wave ends"
        self.breaches(design, "content.objectives_vary", "distinct thing(s)")

    def test_two_units_a_tester_cannot_tell_apart(self):
        design = self.design()
        line = "The wave data for this unit lists eight spawns and two elites"
        unit(design, "u-02")["acceptance"] = [line, line + " today"]
        self.breaches(design, "content.acceptance_specific", "accept nearly the same thing")

    def test_acceptance_that_accepts_anything(self):
        design = self.design()
        unit(design, "u-02")["acceptance"] = ["The level is playable from start to finish",
                                             "It plays well on a phone"]
        problems = self.breaches(design, "content.acceptance_specific", "'level is playable'")
        self.assertIn("'plays well'", "\n".join(problems))

    def test_too_few_acceptance_lines(self):
        design = self.design()
        item = unit(design, "u-02")
        item["acceptance"] = item["acceptance"][:1]
        self.breaches(design, "content.acceptance_specific", "has 1 line(s); the bar is 2")


# -- difficulty -----------------------------------------------------------------------------

class Difficulty(ContentCase):
    family = "racing"

    def test_an_axis_the_family_never_declared(self):
        design = self.design()
        unit(design, "u-02")["difficulty"]["grip"] = 0.4
        self.breaches(design, "content.axes_declared", "names the axis 'grip'")

    def test_an_axis_declared_by_the_design_is_allowed(self):
        design = self.design()
        design["build_spec"]["difficulty"]["axes"].append(
            {"id": "grip", "range": [0, 1], "description": "Surface grip"})
        for item in units(design):
            item["difficulty"]["grip"] = 0.4
        self.holds(design)

    def test_a_value_outside_its_range(self):
        design = self.design()
        unit(design, "u-02")["difficulty"]["time-target"] = 1.8
        self.breaches(design, "content.axes_declared", "outside the axis's range 0..1")

    def test_an_mvp_unit_with_no_value_for_an_escalating_axis(self):
        design = self.design()
        del unit(design, "u-02")["difficulty"]["opponent-skill"]
        self.breaches(design, "content.axes_declared",
                      "has no value for 'opponent-skill', an axis a Racing / driving game "
                      "escalates on")

    def test_an_escalating_axis_that_ends_where_it_started(self):
        design = self.design()
        start = mvp(design)[0]["difficulty"]["route-complexity"]
        for item in mvp(design):
            item["difficulty"]["route-complexity"] = start
        self.breaches(design, "content.axes_monotone_with_relief",
                      "an axis a Racing / driving game escalates on ends higher than it starts")

    def test_an_escalating_axis_that_only_nudges_upward(self):
        # The live puzzle design raised depth from 0.08 to 0.16 over six levels: higher, and
        # not a curve. An escalating axis rises at least `min_axis_rise` of its range.
        design = self.design()
        start = mvp(design)[0]["difficulty"]["route-complexity"]
        for item in mvp(design)[1:]:
            item["difficulty"]["route-complexity"] = start + 0.02
        self.breaches(design, "content.axes_monotone_with_relief",
                      "rises at least 0.1 of its range by the last MVP unit")

    def test_a_dip_deeper_than_relief_allows(self):
        design = self.design()
        item = mvp(design)[1]
        item["difficulty"]["route-complexity"] = 0.02
        self.breaches(design, "content.axes_monotone_with_relief", "a breather dips at most")

    def test_a_dip_that_is_never_recovered(self):
        design = self.design(n_units=6)
        readings = [u["difficulty"]["route-complexity"] for u in mvp(design)]
        for position, item in enumerate(mvp(design)[1:], start=1):
            item["difficulty"]["route-complexity"] = round(readings[0] * 0.8, 2) \
                if position < len(readings) - 1 else readings[-1]
        problems = self.breaches(design, "content.axes_monotone_with_relief")
        self.assertIn("is not back to", "\n".join(problems))

    def test_more_axes_raised_at_once_than_the_profile_allows(self):
        design = self.design(profile="casual")
        previous, item = mvp(design)[0], mvp(design)[1]
        for axis in ("route-complexity", "opponent-skill", "time-target"):
            item["difficulty"][axis] = round(previous["difficulty"][axis] + 0.1, 2)
        self.breaches(design, "content.axes_monotone_with_relief",
                      "a casual session raises 1 per unit")

    def test_a_prototype_with_no_breather(self):
        design = self.design(profile="casual", n_units=6)
        for position, item in enumerate(mvp(design)):
            item["purpose"] = "test"
            item["difficulty"] = {axis["id"]: round(0.1 + 0.1 * position, 2)
                                  for axis in MODELS["families"]["racing"]["axes"]
                                  if axis.get("escalates")}
        problems = self.breaches(design, "content.axes_monotone_with_relief")
        self.assertIn("units[u-05] is MVP unit 4 in a row that raises an axis", "\n".join(problems))
        self.assertIn("a casual session gets a breather", "\n".join(problems))


# -- win, loss, scope and mastery -----------------------------------------------------------

class WinLoseScopeMastery(ContentCase):
    family = "shooter"

    def test_a_unit_whose_success_says_nothing(self):
        design = self.design()
        unit(design, "u-02")["success"] = "Win"
        self.breaches(design, "content.win_lose_stated",
                      "units[u-02].success is 'Win', which no developer could build")

    def test_a_unit_that_is_won_and_lost_the_same_way(self):
        design = self.design()
        item = unit(design, "u-02")
        item["failure"] = item["success"]
        self.breaches(design, "content.win_lose_stated", "states the same thing as its success")

    def test_a_unit_with_no_failure(self):
        design = self.design()
        unit(design, "u-02")["failure"] = ""
        self.breaches(design, "content.win_lose_stated", "units[u-02].failure is missing")

    def test_a_per_unit_family_whose_units_are_all_won_the_same_way(self):
        design = self.design()
        del design["build_spec"]["experience"]["win"]
        for item in units(design):
            item["success"] = "Every enemy of the wave is down"
        problems = self.breaches(design, "content.win_lose_stated")
        self.assertIn("distinct success condition(s)", "\n".join(problems))

    def test_scope_counts_what_the_content_lists(self):
        design = self.design()
        design["scope"]["content_units"] = 3
        self.breaches(design, "content.scope_count_agrees", "scope.content_units is 3")

    def test_scope_counts_the_expected_units_of_a_procedural_design(self):
        design = authored_design("survival")
        design["build_spec"]["content"]["generation"] = {"mode": "procedural",
                                                         "expected_units": 14}
        design["scope"]["content_units"] = 14
        self.holds(design, strategy_for("survival"))
        design["scope"]["content_units"] = len(units(design))
        self.breaches(design, "content.scope_count_agrees", strategy=strategy_for("survival"))

    def test_the_unit_kind_is_read_leniently(self):
        design = self.design()
        design["scope"]["content_unit_kind"] = "Waves"
        self.holds(design)
        design["scope"]["content_unit_kind"] = "tracks"
        self.breaches(design, "content.scope_count_agrees", "content_unit_kind is 'tracks'")

    def test_a_mastery_signal_no_hud_element_shows(self):
        design = self.design()
        design["build_spec"]["mastery"]["signals"] = ["flow-state"]
        self.breaches(design, "content.mastery_stated",
                      "signals names 'flow-state', which no mvp build_spec.hud element shows")

    def test_a_mastery_model_the_schema_does_not_define(self):
        design = self.design()
        design["build_spec"]["mastery"]["model"] = "vibes"
        self.breaches(design, "content.mastery_stated", "mastery.model is 'vibes'")

    def test_a_hud_element_that_is_not_mvp_does_not_show_mastery(self):
        design = self.design()
        for element in design["build_spec"]["hud"]:
            element["tier"] = "post-mvp"
        self.breaches(design, "content.mastery_stated", "no mvp build_spec.hud element shows")


# -- the bars are data ----------------------------------------------------------------------

class TheBarsAreData(ContentCase):
    def test_a_tighter_mvp_count_fails_the_same_design(self):
        models = copy.deepcopy(MODELS)
        models["families"]["arcade"]["units"]["min_mvp"] = 9
        self.breaches(self.design(), "content.unit_count_mvp", "a Arcade / action prototype "
                                                               "carries 9", models=models)

    def test_a_family_override_of_a_shared_bar_is_used(self):
        models = copy.deepcopy(MODELS)
        models["families"]["arcade"]["variety"]["acceptance_min_items"] = 4
        self.breaches(self.design(), "content.acceptance_specific", "the bar is 4", models=models)

    def test_a_family_that_does_not_require_mastery(self):
        models = copy.deepcopy(MODELS)
        models["families"]["arcade"]["mastery"]["statement_required"] = False
        design = self.design()
        del design["build_spec"]["mastery"]
        self.holds(design, models=models)


# -- the result shape -----------------------------------------------------------------------

class TheResults(ContentCase):
    @classmethod
    def setUpClass(cls):
        with open(os.path.join(ROOT, "core", "artifacts", "shared",
                               "criteria-expression.schema.json"), encoding="utf-8") as handle:
            import json
            cls.schema = json.load(handle)["$defs"]["criterionResult"]

    def results(self, design=None):
        _problems, results = self.check(design or self.design())
        return results

    def test_one_result_per_rule_in_order(self):
        self.assertEqual([r["criterion_id"] for r in self.results()],
                         [rule_id for rule_id, _ in content.RULES])

    def test_every_rule_has_a_one_line_meaning_for_the_prompt(self):
        for rule_id, meaning in content.RULES:
            self.assertTrue(rule_id.startswith("content."))
            self.assertTrue(8 < len(meaning) < 100, rule_id)

    def test_results_shape_matches_consistency_rule_results(self):
        """The same key set consistency.py records, and the criterionResult schema."""
        reference = criteria.evaluate_named(
            {"id": "scope_counted", "when": {"left": "scope.content_units", "op": "gte",
                                             "right": 1}},
            {"scope": {"content_units": 6}})
        reference["measured"] = consistency._measured(reference.get("measured"))
        validator = jsonschema_lite.Validator(self.schema)
        for result in self.results():
            self.assertEqual(set(result) - {"note"}, set(reference) - {"note"}, result)
            self.assertEqual([str(e) for e in validator.iter_errors(result)], [])

    def test_a_held_rule_records_what_it_measured(self):
        results = {r["criterion_id"]: r for r in self.results()}
        self.assertIs(results["content.model_resolves"]["breached"], False)
        self.assertEqual(results["content.model_resolves"]["measured"], "arcade")
        self.assertEqual(results["content.unit_kind_allowed"]["measured"], "run-segment")
        self.assertEqual(results["content.unit_count_mvp"]["measured"], 3)

    def test_a_breached_rule_records_the_problems_as_its_note(self):
        design = self.design()
        design["scope"]["content_units"] = 99
        results = {r["criterion_id"]: r for r in self.results(design)}
        breached = results["content.scope_count_agrees"]
        self.assertIs(breached["breached"], True)
        self.assertIn("scope.content_units is 99", breached["note"])


# -- the helpers the rest of the Factory reads ----------------------------------------------

class TheHelpers(unittest.TestCase):
    def test_units_are_returned_in_index_order_and_by_tier(self):
        design = authored_design("arcade")
        design["build_spec"]["content"]["units"].reverse()
        self.assertEqual([u["index"] for u in content.units_of(design)],
                         sorted(u["index"] for u in design["build_spec"]["content"]["units"]))
        self.assertEqual({u["tier"] for u in content.units_of(design, "mvp")}, {"mvp"})

    def test_the_session_profile_defaults_to_standard(self):
        self.assertEqual(content.profile_of({}, MODELS), MODELS["session_profiles"]["standard"])
        self.assertEqual(content.profile_of({"genre": {"session_profile": "casual"}}, MODELS),
                         MODELS["session_profiles"]["casual"])


# -- through the step -----------------------------------------------------------------------

class ScriptedAuthor:
    """The built-in author's draft with the content scripted per round: a design that names its
    family and lists nothing first, then one that states its content. `repairs` is what lets
    the step show it the problems and ask again."""

    name = "scripted-content"
    repairs = True
    actor = "automation"
    rounds = []

    def draft(self, brief):
        from wgf_design import authors
        base = authors.ArchetypeAuthor().draft(brief)
        ScriptedAuthor.rounds.append(brief.get("repair"))
        if len(ScriptedAuthor.rounds) == 1:
            return without_content(base)
        return with_content(base)


def without_content(draft):
    """`draft` with its content taken back out: the design names its family and lists nothing.
    The built-in author always states its content, so a draft that does not is made here."""
    draft["genre"] = {"family": "arcade", "node": "arcade", "session_profile": "standard",
                     "ending": "endless"}
    for key in ("content", "mastery"):
        draft["build_spec"].pop(key, None)
    return draft


def with_content(draft, family="arcade", models=None):
    """`draft` with content the family accepts, built from the draft's own mvp mechanics and
    the mvp hud elements mastery can be read from."""
    models = models or MODELS
    spec = draft["build_spec"]
    mechanics = [m["id"] for m in spec["mechanics"] if m["tier"] == "mvp"]
    signals = [h.get("metric") or h["id"] for h in spec["hud"] if h["tier"] == "mvp"]
    body = content_body(family, mechanics=mechanics, signals=signals[:2], models=models)
    draft["genre"] = body["genre"]
    spec["content"] = body["content"]
    spec["mastery"] = body["mastery"]
    spec["difficulty"] = dict(spec["difficulty"], model=body["difficulty_model"],
                              axes=body["axes"])
    spec["progression"] = dict(spec["progression"], model=body["progression_model"])
    draft["scope"] = dict(draft["scope"], content_units=body["total"],
                          content_unit_kind=body["kind"])
    return draft


class TheStep(unittest.TestCase):
    """The design step's ladder: content is checked after depth, its problems go through the
    same repair rounds, and what held is recorded on the artifact.

    The consistency ruleset is seamed down to one of its own rules: this is a test of the
    ladder and of what reaches the artifact, not of the ruleset (test_design_module covers
    that), and the one rule left is there so the content results can be compared against a
    consistency result produced the same way.
    """

    @classmethod
    def setUpClass(cls):
        import test_design_module as design_tests
        from wgf_design import authors
        from wgflib.workflow.contracts import ArtifactContracts
        from wgflib.workflow.model import StepOutcome

        rule = next(r for r in consistency.load_rules()["rules"]
                    if r["id"] == "rewarded_ads_need_reward_moments")

        class Step(design_tests.FixedClockStep):
            rules = {"version": "0.0.0-test", "concept_terms": {}, "rules": [rule]}
            content_models = MODELS

        ScriptedAuthor.rounds = []
        authors.register_author(ScriptedAuthor.name, ScriptedAuthor)
        try:
            cls.result = design_tests.run_step(
                design_tests.coherent("drop-merge"),
                params={"archetype": "drop-merge", "author": ScriptedAuthor.name},
                step_class=Step)
        finally:
            authors.AUTHORS.pop(ScriptedAuthor.name, None)
        cls.rounds = list(ScriptedAuthor.rounds)
        cls.outcomes = StepOutcome
        cls.contracts = ArtifactContracts

    def test_step_routes_content_problems_through_repair(self):
        self.assertEqual(self.result.outcome, self.outcomes.SUCCESS, self.result.error)
        self.assertEqual(len(self.rounds), 2)
        self.assertIsNone(self.rounds[0])
        shown = "\n".join(self.rounds[1]["problems"])
        self.assertIn("[content.block_present] build_spec.content is missing", shown)
        self.assertEqual(self.rounds[1]["round"], 1)

    def test_the_artifact_carries_the_content_results_after_consistencys_own(self):
        results = self.result.artifacts[0].content["consistency"]["rule_results"]
        self.assertEqual(results[0]["criterion_id"], "rewarded_ads_need_reward_moments")
        self.assertEqual([r["criterion_id"] for r in results[1:1 + len(content.RULES)]],
                         [rule_id for rule_id, _ in content.RULES])
        # Then the feature evaluation's (features.py, game-design 1.10.0).
        self.assertEqual([r["criterion_id"] for r in results[1 + len(content.RULES):]],
                         [rule_id for rule_id, _ in feature_check.RULES])
        self.assertFalse([r for r in results if r["breached"]])

    def test_the_content_results_have_consistencys_own_shape(self):
        results = self.result.artifacts[0].content["consistency"]["rule_results"]
        reference = set(results[0])
        for result in results[1:]:
            self.assertEqual(set(result) - {"note"}, reference - {"note"}, result)

    def test_the_artifact_records_the_model_it_was_checked_against(self):
        block = self.result.artifacts[0].content["consistency"]
        self.assertEqual(block["content_model"],
                         {"id": "arcade", "version": str(MODELS["version"])})

    def test_the_artifact_is_schema_valid_with_its_content_block(self):
        design = self.result.artifacts[0].content
        self.assertEqual(self.contracts()("game-design", design), [])
        self.assertEqual(len(design["build_spec"]["content"]["units"]),
                         design["scope"]["content_units"])

    def test_a_design_that_keeps_its_content_problems_fails_by_name(self):
        import test_design_module as design_tests
        from wgf_design import authors
        from wgflib.workflow.model import StepOutcome

        class Stubborn(ScriptedAuthor):
            name = "stubborn-content"
            repairs = False

            def draft(self, brief):
                return without_content(authors.ArchetypeAuthor().draft(brief))

        class Step(design_tests.FixedClockStep):
            rules = {"version": "0.0.0-test", "concept_terms": {}, "rules": []}
            content_models = MODELS

        authors.register_author(Stubborn.name, Stubborn)
        try:
            result = design_tests.run_step(
                design_tests.coherent("drop-merge"),
                params={"archetype": "drop-merge", "author": Stubborn.name}, step_class=Step)
        finally:
            authors.AUTHORS.pop(Stubborn.name, None)
        self.assertEqual((result.outcome, result.retryable), (StepOutcome.FAILED, False))
        self.assertIn("the design does not specify its content", result.error)
        self.assertIn("build_spec.content is missing", result.error)
        self.assertEqual(result.artifacts, [])


if __name__ == "__main__":
    unittest.main()

"""core/reference/genre-models.yaml: the genre families and the bars a design of each is held to.

The file is read by the design step's content check, the genre seed author, the developer
brief, the playability checks and the tech plan's content tasks, and no consumer branches on a
family id - everything a family changes is a value here. That only holds if the values are the
ones those consumers can read: nodes the research vocabulary defines, progression and
difficulty models the game-design schema allows, axes with ordered ranges, counts that are
possible, and `qa` keys from one fixed vocabulary.

A family that fails these tests is a family no consumer can use, which is worse than a
missing one, because the design step will still hold a design to it.

    python -m unittest scripts.tests.test_genre_models
"""

import json
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
sys.path.insert(0, SCRIPTS)

from wgf_design import content  # noqa: E402

MODELS = content.load_models()
VOCABULARY = content.load_vocabulary()
LOCAL_ID = re.compile(r"^[a-z][a-z0-9-]*$")

# The only `qa` keys the playability checks read (docs/playability-module.md). A key outside
# this set is a parameter nothing acts on.
QA_KEYS = {"min_units_traversed", "reset_in_unit", "checkpoint", "min_new_kinds_per_unit",
           "resource_metric", "time_target_axis", "failure_state", "endless_window_s"}
# The bars every family inherits unless it overrides one.
VARIETY_BARS = {"min_dimensions_changed_between_units", "max_consecutive_scaling_only_units",
                "mechanic_reuse_min_units", "max_identical_objectives_ratio",
                "acceptance_min_items", "acceptance_max_similarity", "relief_dip_max",
                "relief_recovery_units"}
# Genre nodes no family claims: capability gaps research keeps as such, not shapes to force
# into a family that does not fit them (the file's own header says so).
CAPABILITY_GAPS = {"io", "card", "solitaire", "board", "word", "word-search", "word-build",
                   "physics", "sports"}


def schema():
    with open(os.path.join(ROOT, "core", "artifacts", "game-design.schema.json"),
              encoding="utf-8") as handle:
        return json.load(handle)


SCHEMA = schema()
BUILD_SPEC = SCHEMA["properties"]["build_spec"]["properties"]
ENUMS = {
    "family": SCHEMA["properties"]["genre"]["properties"]["family"]["enum"],
    "ending": SCHEMA["properties"]["genre"]["properties"]["ending"]["enum"],
    "session_profile": SCHEMA["properties"]["genre"]["properties"]["session_profile"]["enum"],
    "unit_kind": BUILD_SPEC["content"]["properties"]["unit_kind"]["enum"],
    "generation": BUILD_SPEC["content"]["properties"]["generation"]["properties"]["mode"]["enum"],
    "progression": BUILD_SPEC["progression"]["properties"]["model"]["enum"],
    "difficulty": BUILD_SPEC["difficulty"]["properties"]["model"]["enum"],
    "mastery": BUILD_SPEC["mastery"]["properties"]["model"]["enum"],
}
NODES = {entry["id"]: entry for entry in VOCABULARY["genres"]}


class EveryFamily(unittest.TestCase):
    def families(self):
        return sorted(MODELS["families"].items())

    def test_the_file_is_versioned_and_has_the_shared_bars(self):
        self.assertRegex(str(MODELS["version"]), r"^\d+\.\d+\.\d+$")
        self.assertEqual(set(MODELS["variety"]), VARIETY_BARS)
        self.assertEqual(set(MODELS["session_profiles"]), set(ENUMS["session_profile"]))
        for key in ("difficulty_tolerance", "task_batch", "content_unit_hours"):
            self.assertIn(key, MODELS["implementation"])

    def test_the_families_are_the_ones_the_schema_allows(self):
        self.assertEqual(sorted(MODELS["families"]), sorted(ENUMS["family"]))

    def test_every_node_is_a_genre_node_of_the_research_vocabulary(self):
        for family_id, family in self.families():
            with self.subTest(family=family_id):
                self.assertTrue(family["nodes"], family_id)
                for node in family["nodes"]:
                    self.assertIn(node, NODES, f"{family_id} claims {node!r}, which "
                                               f"core/reference/research-vocabulary.yaml does "
                                               f"not define")

    def test_no_node_is_claimed_by_two_families(self):
        owners = {}
        for family_id, family in self.families():
            for node in family["nodes"]:
                self.assertNotIn(node, owners, f"{node!r} is claimed by {owners.get(node)!r} and "
                                               f"{family_id!r}: a node resolves to one family")
                owners[node] = family_id

    def test_a_node_resolves_to_the_family_that_claims_it(self):
        for family_id, family in self.families():
            for node in family["nodes"]:
                with self.subTest(family=family_id, node=node):
                    self.assertEqual(content.family_of_node(node, MODELS, VOCABULARY), family_id)

    def test_every_unclaimed_node_is_a_known_capability_gap(self):
        claimed = {node for family in MODELS["families"].values() for node in family["nodes"]}
        unresolved = {node for node in NODES
                      if content.family_of_node(node, MODELS, VOCABULARY) is None}
        self.assertEqual(unresolved, CAPABILITY_GAPS)
        self.assertFalse(unresolved & claimed)

    def test_the_models_a_family_allows_are_ones_the_schema_defines(self):
        for family_id, family in self.families():
            with self.subTest(family=family_id):
                for key, enum in (("unit_kinds", "unit_kind"),
                                  ("progression_models", "progression"),
                                  ("difficulty_models", "difficulty"),
                                  ("ending", "ending")):
                    self.assertTrue(family[key], f"{family_id}.{key} is empty")
                    for value in family[key]:
                        self.assertIn(value, ENUMS[enum], f"{family_id}.{key}")
                for mode in family["units"]["generation"]:
                    self.assertIn(mode, ENUMS["generation"], f"{family_id}.units.generation")
                self.assertIn(family["mastery"]["model"], ENUMS["mastery"], family_id)

    def test_axes_are_local_ids_with_ordered_ranges(self):
        for family_id, family in self.families():
            with self.subTest(family=family_id):
                seen = set()
                self.assertTrue(family["axes"], family_id)
                for axis in family["axes"]:
                    self.assertRegex(axis["id"], LOCAL_ID)
                    self.assertNotIn(axis["id"], seen, f"{family_id}: duplicate axis")
                    seen.add(axis["id"])
                    low, high = axis["range"]
                    self.assertLess(low, high, f"{family_id}.{axis['id']}.range")
                    self.assertTrue(axis.get("description"), f"{family_id}.{axis['id']}")
                    self.assertIn(axis.get("probe"), ("required", "optional"),
                                  f"{family_id}.{axis['id']}.probe")
                self.assertTrue([a for a in family["axes"] if a.get("escalates")],
                                f"{family_id}: no axis escalates, so difficulty cannot rise")

    def test_a_prototype_count_a_release_count_can_hold(self):
        for family_id, family in self.families():
            with self.subTest(family=family_id):
                units = family["units"]
                self.assertGreaterEqual(units["min_mvp"], 2, family_id)
                self.assertLessEqual(units["min_mvp"], units["min_total"], family_id)

    def test_variety_dimensions_are_named_and_include_what_a_unit_changes(self):
        for family_id, family in self.families():
            with self.subTest(family=family_id):
                dimensions = family["variety"]["dimensions"]
                self.assertGreaterEqual(len(dimensions), 4, family_id)
                self.assertEqual(len(dimensions), len(set(dimensions)), family_id)
                for dimension in dimensions:
                    self.assertRegex(dimension, r"^[a-z][a-z0-9_]*$", family_id)
                for required in ("introduces", "objective"):
                    self.assertIn(required, dimensions, family_id)
                override = set(family["variety"]) - {"dimensions"}
                self.assertTrue(override <= VARIETY_BARS,
                                f"{family_id} overrides {sorted(override - VARIETY_BARS)}, which "
                                f"is not a shared variety bar")

    def test_mastery_is_a_model_signals_and_whether_a_statement_is_required(self):
        for family_id, family in self.families():
            with self.subTest(family=family_id):
                mastery = family["mastery"]
                self.assertEqual(set(mastery), {"model", "signals", "statement_required"})
                self.assertIsInstance(mastery["statement_required"], bool)
                self.assertTrue(mastery["signals"], family_id)
                for signal in mastery["signals"]:
                    self.assertRegex(signal, LOCAL_ID, family_id)

    def test_win_and_lose_state_a_shape_and_whether_it_is_per_unit(self):
        for family_id, family in self.families():
            with self.subTest(family=family_id):
                for key in ("win", "lose"):
                    self.assertEqual(set(family[key]), {"shape", "per_unit", "description"})
                    self.assertIsInstance(family[key]["per_unit"], bool)
                    self.assertRegex(family[key]["shape"], LOCAL_ID)

    def test_qa_keys_come_from_the_fixed_vocabulary(self):
        for family_id, family in self.families():
            with self.subTest(family=family_id):
                extra = set(family["qa"]) - QA_KEYS
                self.assertFalse(extra, f"{family_id}.qa has {sorted(extra)}, which nothing reads")
                axis_ids = {a["id"] for a in family["axes"]}
                if "time_target_axis" in family["qa"]:
                    self.assertIn(family["qa"]["time_target_axis"], axis_ids, family_id)
                if "endless_window_s" in family["qa"]:
                    self.assertIn("endless", family["ending"],
                                  f"{family_id}.qa sets an endless window but the family never "
                                  f"ends endless")
                self.assertIn("min_units_traversed", family["qa"], family_id)
                self.assertLessEqual(family["qa"]["min_units_traversed"],
                                     family["units"]["min_mvp"], family_id)


class TheSessionProfiles(unittest.TestCase):
    def test_casual_is_tighter_than_standard_on_every_key(self):
        casual = MODELS["session_profiles"]["casual"]
        standard = MODELS["session_profiles"]["standard"]
        self.assertEqual(set(casual), set(standard))
        for key in sorted(casual):
            self.assertLessEqual(casual[key], standard[key],
                                 f"session_profiles.casual.{key} is looser than standard's")

    def test_a_profile_states_every_number_the_content_check_reads(self):
        for name, profile in MODELS["session_profiles"].items():
            with self.subTest(profile=name):
                self.assertEqual(set(profile), {"max_unit_s", "max_first_session_s",
                                                "relief_every_units",
                                                "max_axes_raised_per_unit"})

    def test_profile_of_defaults_to_standard(self):
        self.assertEqual(content.profile_of({}, MODELS),
                         MODELS["session_profiles"]["standard"])


class TheGenreTreeIsWalked(unittest.TestCase):
    def test_a_node_resolves_through_its_parents(self):
        for node, family in (("lane-runner", "arcade"), ("endless-runner", "arcade"),
                             ("tower-defense", "strategy"), ("match-3", "puzzle"),
                             ("parking", "racing"), ("clicker", "simulation"),
                             ("arena-survivor", "survival"), ("io", None),
                             ("solitaire", None), ("word-search", None)):
            with self.subTest(node=node):
                self.assertEqual(content.family_of_node(node, MODELS, VOCABULARY), family)

    def test_a_node_no_family_lists_resolves_through_its_nearest_listed_ancestor(self):
        """The test that the walk is a walk: a node invented under `runner` resolves to arcade
        without arcade listing it."""
        vocabulary = {"genres": list(VOCABULARY["genres"])
                      + [{"id": "stair-runner", "label": "Stair runner", "parent": "lane-runner"}]}
        self.assertEqual(content.family_of_node("stair-runner", MODELS, vocabulary), "arcade")

    def test_an_unknown_node_resolves_to_nothing(self):
        for node in (None, "", "metroidvania", "4x"):
            self.assertIsNone(content.family_of_node(node, MODELS, VOCABULARY))

    def test_the_walk_does_not_loop(self):
        vocabulary = {"genres": [{"id": "a", "parent": "b"}, {"id": "b", "parent": "a"}]}
        self.assertIsNone(content.family_of_node("a", MODELS, vocabulary))


if __name__ == "__main__":
    unittest.main()

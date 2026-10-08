"""An adoption hands the author what the floor derives of the shipped units.

Found live (2026-10-08, the 2D run new-game-20261005-002926-318384, game-design v2): the
adopted checkout ships 32 units w1-l1..w4-l8 at c86a018 with no `group` field, so the
existing-content floor counted 4 groups by the unit id prefix rule (brief-commitments.yaml
`existing_content.group.id_pattern`). The adoption handed the author the shipped units as they
are - without groups - and the design, which kept all 32 ids and even declared groups w1..w4,
put no unit in a group: it planned 0 groups and failed existing_content_floor_kept and
brief_commitments_met. The author never inferred the groups.

The lesson: whatever the floor DERIVES (groups by prefix, climax units by a term) is handed to
the author explicitly. These tests hold:

  * wgf_design/existing.py: derive() is the one reading the floor counts on and the
    adoption starts from; adoption_units() writes the derived `group` and climax `purpose`
    into each unit that does not state them, never over a stated one; adoption_derived()
    lists the groups with their unit ids and the climax units;
  * the replayed v2: its counts reproduce both breaches; the starting units the adoption now
    hands over meet the floor and the brief's counts, and so does v2 had its units carried
    the derived groups - no rule is loosened;
  * wgf_design/agent.py: the starting draft carries the groups and declares them in
    build_spec.content.groups, the request lists `adoption.derived`, the prompt says it.

Offline. Run from the repository root:

    python -m unittest scripts.tests.test_design_adopt_groups
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

import test_design_agent as agent_tests  # noqa: E402
from wgf_design import commitments, existing  # noqa: E402
from wgf_design.agent import AgentAuthor  # noqa: E402

STORE = os.path.join(HERE, "fixtures", "design", "adopt-groups-2d", "run-store.json")
WORLDS = ["w1", "w2", "w3", "w4"]
BOSSES = ["w1-l8", "w2-l8", "w3-l8", "w4-l8"]


def load_store():
    with open(STORE, encoding="utf-8") as handle:
        return json.load(handle)


def design_of(store, units, groups=None):
    """A design of the replayed v2: its tier, the floor it was held to, these units."""
    return {"existing_content": store["floor"],
            "build_spec": {"content": {
                "quality_tier": store["design_v2"]["quality_tier"],
                "groups": groups if groups is not None else store["design_v2"]["groups"],
                "units": units}}}


def counts_unmet(view):
    """The count commitments a design leaves unmet (a mode needs the design's features)."""
    return [u for u in view["unmet"] if not u.startswith("mode ")]


class TheReplayedFloor(unittest.TestCase):
    def setUp(self):
        self.store = load_store()
        self.shipped = self.store["shipped_units"]

    def test_the_shipped_units_state_no_group_and_the_floor_derives_four(self):
        self.assertFalse([u for u in self.shipped if "group" in u or "purpose" in u])
        counted = existing.measure(self.shipped)
        for q in ("units", "groups", "climax_units"):
            self.assertEqual(counted[q], self.store["floor"][q], q)
        self.assertEqual(counted["measured_by"], self.store["floor"]["measured_by"])
        self.assertEqual(existing.units_digest(self.shipped),
                         self.store["floor"]["units_digest"])

    def test_v2s_counts_reproduce_both_breaches(self):
        design = design_of(self.store, self.store["design_v2"]["units"])
        self.assertEqual(existing.floor_view(design)["short"],
                         self.store["v2_breaches"]["existing_content_floor_kept"])
        view = commitments.view(design, self.store["strategy"])
        self.assertEqual(counts_unmet(view), self.store["v2_breaches"]["brief_commitments_met"])


class TheAdoptionCarriesWhatTheFloorDerives(unittest.TestCase):
    def setUp(self):
        self.store = load_store()
        self.shipped = self.store["shipped_units"]

    def test_derive_is_what_measure_counts(self):
        found = existing.derive(self.shipped)
        self.assertEqual(sorted(set(found["groups"].values())), WORLDS)
        self.assertEqual(found["groups"]["w3-l5"], "w3")
        self.assertEqual(found["climax"], BOSSES)
        self.assertEqual(found["groups_by"], self.store["floor"]["measured_by"]["groups"])
        self.assertEqual(found["climax_by"], self.store["floor"]["measured_by"]["climax_units"])

    def test_every_starting_unit_carries_its_group_and_bosses_their_purpose(self):
        units = existing.adoption_units(self.shipped)
        self.assertEqual([u["id"] for u in units], [u["id"] for u in self.shipped])
        self.assertEqual([u["group"] for u in units], [u["id"][:2] for u in self.shipped])
        self.assertEqual([u["id"] for u in units if u.get("purpose") == "climax"], BOSSES)
        self.assertFalse([u for u in units if "purpose" in u and u["id"] not in BOSSES])
        self.assertFalse([u for u in units if "layout" in u])

    def test_the_request_lists_the_groups_with_their_units(self):
        derived = existing.adoption_derived(self.shipped)
        self.assertEqual(list(derived["groups"]), WORLDS)
        self.assertEqual(derived["groups"]["w2"], [f"w2-l{n}" for n in range(1, 9)])
        self.assertEqual(derived["climax_unit_ids"], BOSSES)
        self.assertIn("unit id prefix", derived["groups_measured_by"])

    def test_the_starting_units_meet_the_floor_and_the_briefs_counts(self):
        units = existing.adoption_units(self.shipped)
        groups = [{"id": g, "name": g} for g in WORLDS]
        design = design_of(self.store, units, groups)
        self.assertEqual(existing.floor_view(design)["short"], [])
        self.assertEqual(counts_unmet(commitments.view(design, self.store["strategy"])), [])

    def test_v2_with_the_derived_groups_meets_both_rules(self):
        groups = existing.derive(self.shipped)["groups"]
        units = [dict(u, group=groups[u["id"]]) for u in
                 copy.deepcopy(self.store["design_v2"]["units"])]
        design = design_of(self.store, units)
        self.assertEqual(existing.floor_view(design)["short"], [])
        self.assertEqual(counts_unmet(commitments.view(design, self.store["strategy"])), [])

    def test_a_stated_field_is_never_overwritten(self):
        shipped = copy.deepcopy(self.shipped)
        shipped[0]["group"] = "meadow"
        units = existing.adoption_units(shipped)
        # One unit states a group, the others do not: groups are by prefix, the stated kept.
        self.assertEqual(units[0]["group"], "meadow")
        self.assertEqual(units[1]["group"], "w1")
        # A purpose any unit states makes the field the method: nothing is derived by text.
        shipped[7]["purpose"] = "test"
        units = existing.adoption_units(shipped)
        self.assertEqual(units[7]["purpose"], "test")
        self.assertFalse([u for u in units if u.get("purpose") == "climax"])

    def test_units_with_their_groups_stated_are_handed_over_as_they_are(self):
        shipped = [dict(copy.deepcopy(u), group=f"world-{u['id'][1]}") for u in self.shipped]
        units = existing.adoption_units(shipped)
        self.assertEqual([u["group"] for u in units], [u["group"] for u in shipped])
        self.assertEqual(existing.adoption_derived(shipped)["groups_measured_by"],
                         "units[].group")

    def test_no_method_no_derivation(self):
        shipped = [{"id": "first", "objective": "Clear the board"},
                   {"id": "second", "objective": "Clear it faster"}]
        self.assertEqual(existing.adoption_units(shipped), shipped)
        derived = existing.adoption_derived(shipped)
        self.assertIsNone(derived["groups"])
        self.assertEqual(derived["climax_unit_ids"], [])


class TheAuthorIsHandedTheDerivedGroups(agent_tests.AgentCase):
    def adoption(self, shipped):
        return {"commit": "c86a018d8cdf518307ef1f31fce4e6be82b09028",
                "path": "public/content/units.json",
                "unit_ids": [u["id"] for u in shipped],
                "units": existing.adoption_units(shipped),
                "derived": existing.adoption_derived(shipped),
                "shipped_units": shipped, "missing": [u["id"] for u in shipped],
                "rewritten": [], "supersedes": None}

    def seen(self):
        with open(os.path.join(self.scratch, "run", "design", "seen-1-1.json"),
                  encoding="utf-8") as handle:
            return json.load(handle)

    def test_the_starting_draft_request_and_prompt_carry_them(self):
        shipped = load_store()["shipped_units"]
        config = self.config("revise", argv=[sys.executable, self.host, "revise",
                                             "{request}", "{draft}", "{prompt}"])
        AgentAuthor().draft(self.brief(config=config, adoption=self.adoption(shipped)))
        request = self.request_of("1-1")
        self.assertEqual(list(request["adoption"]["derived"]["groups"]), WORLDS)
        self.assertEqual(request["adoption"]["derived"]["climax_unit_ids"], BOSSES)
        content = self.seen()["starting_draft"]["build_spec"]["content"]
        self.assertEqual({u["group"] for u in content["units"]}, set(WORLDS))
        self.assertEqual([g["id"] for g in content["groups"]], WORLDS)
        self.assertEqual([u["id"] for u in content["units"] if u.get("purpose") == "climax"],
                         BOSSES)
        prompt = self.seen()["rest"][0]
        self.assertIn("adoption.derived", prompt)
        self.assertIn("4 group(s) by unit id prefix", prompt)
        self.assertIn("w4 = w4-l1, w4-l2", prompt)
        self.assertIn("4 climax unit(s)", prompt)

    def test_nothing_derived_says_nothing_more(self):
        shipped = [dict(copy.deepcopy(u), group=f"world-{u['id'][1]}", purpose="test")
                   for u in load_store()["shipped_units"]]
        config = self.config("revise", argv=[sys.executable, self.host, "revise",
                                             "{request}", "{draft}", "{prompt}"])
        AgentAuthor().draft(self.brief(config=config, adoption=self.adoption(shipped)))
        content = self.seen()["starting_draft"]["build_spec"]["content"]
        self.assertEqual([g["id"] for g in content["groups"]],
                         ["world-1", "world-2", "world-3", "world-4"])
        # Stated groups are still listed for the author; no climax unit is derived.
        self.assertIn("by units[].group", self.seen()["rest"][0])
        self.assertNotIn("climax unit(s) by", self.seen()["rest"][0])


if __name__ == "__main__":
    unittest.main()

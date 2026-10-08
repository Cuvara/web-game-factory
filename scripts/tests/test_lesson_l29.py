"""L29: after the opening unit, a unit introduces at most one element the player has not met.

The two checks that hold it, on what each producer actually reads:

    design-consistency:content.introductions_one_at_a_time   the design's build_spec.content
                                                              units (wgf_design/consistency.py
                                                              through content.introductions_view)
    content-sufficiency:content.introductions_one_at_a_time  the BUILT content data file
                                                              (wgf_sufficiency/audit.py
                                                              introductions_check)

The lesson's catches and passes tests are the two names `wgf knowledge promote` drafts for
it (scripts/tests/test_knowledge_transfer.py holds the draft equal to the shipped entry); the
rest is the person's completion. The real-game grounding is read two ways
(scripts/tests/fixtures/real/play-realism/):

  * as written - the 2D validation run's game-design v4, and the content data files the two
    games ship at 0db72b6 (2D) and 43c08e2 (3D), whose units state their elements,
    mechanics and introductions: both checks run on them unchanged and pass;
  * through a reading - the builds accepted at G4 (96f5cea, c340631) predate those lists:
    their content data keeps each unit's layout and parameters only, so those tests name a
    unit's elements the way that game's own data does (the 2D game by the tuning section
    that governs each layout symbol and layout key, the 3D game by the course features its
    parameters count). That naming is this test's, stated below; the files are unedited.

The generalization replays a synthetic game B of another family and render
(scripts/tests/fixtures/knowledge/l29-synthetic-3d-racer.json), regressed and fixed.

    python -m unittest scripts.tests.test_lesson_l29
"""

import copy
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from wgf_design import consistency, content  # noqa: E402
from wgf_quality import registry  # noqa: E402
from wgf_sufficiency import audit  # noqa: E402

CHECK = "content.introductions_one_at_a_time"
REAL = os.path.join(HERE, "fixtures", "real", "play-realism")
SYNTHETIC = os.path.join(HERE, "fixtures", "knowledge", "l29-synthetic-3d-racer.json")
# A design the real design step made (a 24-level puzzle, kept as evidence of a validation
# run): the base whose units each test replaces.
BASE_DESIGN = os.path.join(ROOT, "docs", "evidence", "2026-10-03-genre-depth", "ice-slide",
                           "artifacts", "game-design.json")
NOW = "2026-10-09T00:00:00Z"
TIERS = registry.load(ROOT)["tiers"]

# The 2D validation game (96f5cea, 32 levels): each layout symbol and each mechanic key of a
# level's layout, named by the section of the game's own `tuning` that governs it. Power-up
# capsules (M, W, L and the boss arena's m, w) are one mechanic, `power-ups`; the boss
# formation's core (B) and the `boss` key are `boss-fight`.
SYMBOLS_2D = {"#": "bricks", "A": "armored-bricks", "S": "steel-bricks", "X": "explosive-bricks",
              "M": "power-ups", "W": "power-ups", "L": "power-ups", "m": "power-ups",
              "w": "power-ups", "B": "boss-fight"}
KEYS_2D = {"boss": "boss-fight", "slides": "sliding-rows", "descend": "descending-field",
           "embers": "falling-embers"}
# The 3D validation game (c340631, 12 courses): the course features its parameters count.
FEATURES_3D = ("bumpers", "jumps", "turns", "moving_platforms", "walls", "drops", "hairpins")


def _read(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def units_2d(data):
    out = []
    for unit in data["units"]:
        layout = unit["layout"]
        symbols = {c for row in layout["rows"] for c in row if c != "."}
        unknown = symbols - set(SYMBOLS_2D)
        if unknown:
            raise AssertionError(f"{unit['id']}: symbols this reading does not name: {unknown}")
        elements = {SYMBOLS_2D[c] for c in symbols} | {KEYS_2D[k] for k in layout if k in KEYS_2D}
        out.append({"id": unit["id"], "index": unit["index"], "tier": unit.get("tier"),
                    "elements": sorted(elements)})
    return out


def units_3d(data):
    return [{"id": u["id"], "index": u["index"], "tier": u.get("tier"),
             "elements": sorted(k for k in FEATURES_3D
                                if (u.get("parameters") or {}).get(k, 0) > 0)}
            for u in data["units"]]


def design_with(units):
    design = _read(BASE_DESIGN)
    design.pop("consistency", None)
    design["build_spec"]["content"]["units"] = copy.deepcopy(units)
    return design


def design_result(design):
    """(the rule's result, the status the registry reads for the check) on `design`."""
    block, blocking, _warnings = consistency.evaluate(design, {}, [], NOW)
    design = dict(design, consistency=block)
    result = next(r for r in block["rule_results"] if r["criterion_id"] == CHECK)
    status = registry.check_status(TIERS, f"design-consistency:{CHECK}", design)[0]["status"]
    return result, status, blocking


def build_result(design_units, built_units):
    """(the check, the status the registry reads) on a build whose units.json holds
    `built_units` for a design whose units are `design_units`."""
    built = {u["id"]: u for u in built_units}
    shipped = [u for u in design_units if u["id"] in built]
    check = audit.introductions_check(shipped, built)
    report = {"verdict": "FAIL" if check["status"] == "FAIL" else "PASS", "checks": [check]}
    status = registry.check_status(TIERS, f"content-sufficiency:{CHECK}", report)[0]["status"]
    return check, status


def paced(n=6):
    """Units that each debut one element: a starter, then one new element per unit."""
    return [{"id": f"u-{i:02d}", "index": i, "tier": "mvp",
             "elements": ["starter"] + [f"e{k}" for k in range(1, i)],
             "mechanics": ["move"]} for i in range(1, n + 1)]


def doubled(n=6, at=3):
    """paced(), except unit `at` debuts two elements at once."""
    units = paced(n)
    for unit in units[at - 1:]:
        unit["elements"].append("e-surprise")
    return units


class LessonL29(unittest.TestCase):
    # -- catches: what promote drafted ------------------------------------------------------

    def test_L29_the_check_fails_the_defect(self):
        """The negative case: a design and a build whose third unit debuts two elements."""
        result, status, blocking = design_result(design_with(doubled()))
        self.assertTrue(result["breached"])
        self.assertEqual(status, "FAIL")
        self.assertIn(CHECK, blocking)
        self.assertIn("build_spec.content.units[u-03] debuts 2 elements at once: e-surprise, e2",
                      str(result["measured"]))
        check, status = build_result(doubled(), doubled())
        # the status first: a check that passes has no route, and must fail here, not err
        self.assertEqual((check["status"], status), ("FAIL", "FAIL"), check)
        self.assertEqual(check.get("route"), "design-gap")

    # -- passes -----------------------------------------------------------------------------

    def test_L29_the_check_passes_the_fixed_build(self):
        """The positive case: the same game with the second element moved to its own unit."""
        result, status, blocking = design_result(design_with(paced()))
        self.assertFalse(result["breached"])
        self.assertEqual(status, "PASS")
        self.assertNotIn(CHECK, blocking)
        check, status = build_result(paced(), paced())
        self.assertEqual((check["status"], status), ("PASS", "PASS"))

    def test_L29_the_accepted_2d_validation_game_passes(self):
        """96f5cea, accepted at G4: 32 levels, every level after the first debuts at most one
        mechanic (armored, the boss, steel, sliding rows, a descending field, explosives,
        embers - each on a level of its own)."""
        units = units_2d(_read(os.path.join(REAL, "content-2d-96f5cea.json")))
        self.assertEqual(len(units), 32)
        debuts = {u["id"]: new for u, new in content.unit_debuts(units) if new}
        self.assertEqual(debuts["w1-l8"], ["boss-fight"])
        self.assertEqual(debuts["w2-l2"], ["sliding-rows"])
        check, status = build_result(units, units)
        self.assertEqual((check["status"], status), ("PASS", "PASS"), check["summary"])
        result, status, _ = design_result(design_with(units))
        self.assertEqual((result["breached"], status), (False, "PASS"))

    def test_L29_the_2d_validation_design_passes_as_written(self):
        """The 2D validation run's design v4, unchanged: each unit after the first states at
        most one introduction. An element and the mechanic it stands for (an armored brick,
        armored bricks; the boss's shield and weak point, the boss fight) are ONE debut - the
        unit's `introduces` - never two."""
        data = _read(os.path.join(REAL, "design-2d-v4-units.json"))
        units = data["units"]
        self.assertEqual(len(units), 32)
        w1_l4 = next(u for u in units if u["id"] == "w1-l4")
        self.assertEqual(w1_l4["introduces"], ["armored-bricks"])
        self.assertIn("armored-brick", w1_l4["elements"])
        result, status, _ = design_result(design_with(units))
        self.assertEqual((result["breached"], status), (False, "PASS"), result)
        debuts = {u["id"]: new for u, new in content.unit_debuts(units) if new}
        self.assertEqual((debuts["w1-l4"], debuts["w1-l8"]), (["armored-bricks"], ["boss-fight"]))

    def test_L29_the_2d_and_3d_content_data_pass_as_written(self):
        """public/content/units.json of the 2D game at 0db72b6 and the 3D game at 43c08e2,
        unchanged: the build check passes on what they state."""
        for name, count in (("content-2d-0db72b6-units.json", 32),
                            ("content-3d-43c08e2-units.json", 16)):
            with self.subTest(name=name):
                units = sorted(_read(os.path.join(REAL, name))["units"],
                               key=lambda u: u["index"])
                self.assertEqual(len(units), count)
                check, status = build_result(units, units)
                self.assertEqual((check["status"], status), ("PASS", "PASS"), check)

    def test_L29_an_element_and_its_mechanic_are_one_debut(self):
        """A unit that states `introduces` debuts what it lists; one that states none is
        counted by every element and mechanic it shows that no earlier unit named."""
        units = paced(2)
        units[1]["elements"] = units[0]["elements"] + ["armored-brick"]
        units[1]["mechanics"] = ["move", "armored-bricks"]
        units[1]["introduces"] = ["armored-bricks"]
        self.assertFalse(design_result(design_with(units))[0]["breached"])
        self.assertEqual(build_result(units, units)[0]["status"], "PASS")
        units[1]["introduces"] = ["armored-bricks", "boss-fight"]
        self.assertTrue(design_result(design_with(units))[0]["breached"])
        self.assertEqual(build_result(units, units)[0]["status"], "FAIL")
        # no `introduces`: what it shows for the first time is what it debuts
        del units[1]["introduces"]
        self.assertTrue(design_result(design_with(units))[0]["breached"])

    def test_L29_an_empty_introduces_is_counted_by_what_the_unit_shows(self):
        """`introduces: []` states nothing: the unit is counted by the never-seen elements
        and mechanics it shows - two new elements, or two new mechanics, breach."""
        for key in ("elements", "mechanics"):
            with self.subTest(key=key):
                units = paced(3)
                units[2]["elements"] = list(units[1]["elements"])
                units[2]["introduces"] = []
                units[2][key] = list(units[2].get(key) or []) + ["new-a", "new-b"]
                result, status, _ = design_result(design_with(units))
                self.assertEqual((result["breached"], status), (True, "FAIL"), result)
                check, status = build_result(units, units)
                self.assertEqual((check["status"], status), ("FAIL", "FAIL"), check)

    def test_L29_a_build_is_held_to_its_design_whatever_introduces_it_copied(self):
        """Claimed vs actual: the build shows a never-seen element its design unit does not
        name - moved a unit early - with the design's `introduces` copied unchanged. The
        design's count is one debut; the build's is two, and it FAILs (develop)."""
        design_units = paced(4)
        design_units[2]["introduces"] = ["e2"]
        built = copy.deepcopy(design_units)
        built[2]["elements"] = built[2]["elements"] + ["e3"]
        self.assertEqual(built[2]["introduces"], ["e2"])
        result, _status, _ = design_result(design_with(design_units))
        self.assertFalse(result["breached"])
        check, status = build_result(design_units, built)
        self.assertEqual((check["status"], status), ("FAIL", "FAIL"), check)
        self.assertEqual(check.get("route"), "develop")
        self.assertIn("units.json u-03 debuts 2 elements at once: e2, e3", check["summary"])

    def test_L29_a_listed_introduction_is_trusted_on_the_design_known_limitation(self):
        """Documented, accepted: on the DESIGN a non-empty `introduces` is trusted, and new
        elements listed beside it are not counted there (a boss unit introducing the boss
        fight, whose parts are new elements). The build's comparison with its design is
        what holds a build to it - a build that adds a further new element FAILs."""
        units = paced(3)
        units[2]["elements"] = list(units[1]["elements"]) + ["boss-shield", "boss-weak-point"]
        units[2]["introduces"] = ["boss-fight"]
        self.assertFalse(design_result(design_with(units))[0]["breached"])
        built = copy.deepcopy(units)
        built[2]["elements"].append("boss-minion")
        check, _status = build_result(units, built)
        self.assertEqual(check["status"], "FAIL", check)

    def test_L29_the_accepted_3d_validation_game_passes(self):
        """c340631 (r1-forward of the build accepted at G4): 12 courses, every course after
        the first adds at most one feature (moving platforms, walls, drops, hairpins)."""
        units = units_3d(_read(os.path.join(REAL, "content-3d-c340631.json")))
        self.assertEqual(len(units), 12)
        debuts = [new for _u, new in content.unit_debuts(units)[1:] if new]
        self.assertEqual(debuts, [["moving_platforms"], ["walls"], ["drops"], ["hairpins"]])
        check, status = build_result(units, units)
        self.assertEqual((check["status"], status), ("PASS", "PASS"), check["summary"])

    # -- claimed vs actual, and what is never a pass ----------------------------------------

    def test_L29_a_compliant_design_and_a_violating_build_fail_the_build(self):
        result, _status, _ = design_result(design_with(paced()))
        self.assertFalse(result["breached"])
        check, status = build_result(paced(), doubled())
        self.assertEqual((check["status"], status), ("FAIL", "FAIL"), check)
        self.assertEqual(check.get("route"), "develop")
        self.assertIn("units.json u-03 debuts 2 elements at once", check["summary"])

    def test_L29_a_build_that_names_no_elements_is_unmeasured_never_a_pass(self):
        bare = [{"id": u["id"], "index": u["index"]} for u in paced()]
        check, status = build_result(paced(), bare)
        # read SKIPPED, which compliance holds as UNMEASURED - a blocking rule unmet
        self.assertEqual((check["status"], status), ("SKIPPED", "SKIPPED"))
        self.assertIn("never a pass", check["summary"])

    def test_L29_a_unit_naming_nothing_is_unmeasured_never_skipped(self):
        """A unit that names no element, mechanic or introduction is never skipped: skipped,
        the unit after it would 'debut' what it met there, and the opener's exemption would
        not move. The count is unmeasured - on the design a breach naming the units to
        complete (a rule that cannot be checked is never passed), on the build SKIPPED."""
        units = paced(4)
        bare = dict(units[0])
        for key in ("elements", "mechanics"):
            bare.pop(key)
        partial = [bare] + units[1:]
        # skipping it, u-02 would debut starter, e1 and move - two or more at once
        result, status, blocking = design_result(design_with(partial))
        self.assertTrue(result["breached"])
        self.assertIn("units[u-01] name no element, mechanic or introduction",
                      str(result["measured"]))
        self.assertIn("unmeasured, never a pass", str(result["measured"]))
        self.assertEqual(status, "FAIL")
        check, status = build_result(paced(4), partial)
        self.assertEqual((check["status"], status), ("SKIPPED", "SKIPPED"), check)
        self.assertEqual(check["measured"]["undeclared"], ["u-01"])
        self.assertIn("1 of 4 shipped units' (u-01)", check["summary"])
        # a later unit naming nothing is unmeasured too, not a pass
        late = paced(4)
        for key in ("elements", "mechanics"):
            late[2].pop(key)
        check, _status = build_result(paced(4), late)
        self.assertEqual(check["status"], "SKIPPED", check)

    def test_L29_a_design_without_units_holds_and_says_so(self):
        result, status, _ = design_result(design_with([]))
        self.assertFalse(result["breached"])
        self.assertIn("nothing debuts", result["note"])
        self.assertEqual(status, "PASS")

    def test_L29_the_opening_unit_is_exempt(self):
        units = paced(3)
        units[0]["elements"] += ["a", "b", "c"]
        for unit in units[1:]:
            unit["elements"] += ["a", "b", "c"]
        result, _status, _ = design_result(design_with(units))
        self.assertFalse(result["breached"])

    def test_L29_mechanics_and_introductions_count_as_elements(self):
        units = paced(3)
        units[2]["elements"] = list(units[1]["elements"])
        units[2]["introduces"] = ["dash"]
        units[2]["mechanics"] = ["move", "dash"]
        self.assertFalse(design_result(design_with(units))[0]["breached"])
        units[2]["introduces"] = ["dash", "wall-jump"]
        self.assertTrue(design_result(design_with(units))[0]["breached"])

    # -- generalizes ------------------------------------------------------------------------

    def test_L29_generalizes_to_a_synthetic_3d_racer(self):
        """Learned on a 2D puzzle-like game; caught on a 3D kart racer (another family, another
        render) - on its design and on its build - and passed once fixed."""
        data = _read(SYNTHETIC)
        result, status, _ = design_result(design_with(data["regressed"]))
        self.assertEqual((result["breached"], status), (True, "FAIL"))
        for unit in ("c-03", "c-05"):
            self.assertIn(f"units[{unit}] debuts 2 elements", str(result["measured"]))
        check, status = build_result(data["regressed"], data["regressed"])
        self.assertEqual((check["status"], status), ("FAIL", "FAIL"))
        result, status, _ = design_result(design_with(data["fixed"]))
        self.assertEqual((result["breached"], status), (False, "PASS"))
        check, status = build_result(data["fixed"], data["fixed"])
        self.assertEqual((check["status"], status), ("PASS", "PASS"))

    def test_L29_every_shipped_design_with_units_holds_it(self):
        """The designs this repository ships as fixtures and evidence that have units."""
        for path in (BASE_DESIGN,):
            with self.subTest(path=os.path.relpath(path, ROOT)):
                self.assertEqual(content.introductions_view(_read(path))["over_one"], [])


if __name__ == "__main__":
    unittest.main()

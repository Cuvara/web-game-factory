"""The content-sufficiency step (scripts/wgf_sufficiency): the BUILT game's content against the
bars of its quality tier.

The audit reads three things - the design, the content data file the played commit ships, and
what the play probe reported while the playability bot traversed the first units and surveyed
every unit through the unit link - and these tests build each of them the way the design step,
the developer and the bot write them. A varied release-tier build passes. Each way a build the
audit exists to catch falls short fails, routed to who must act (docs/quality-gap-audit-2026-10.md,
WS-4, and the audit's two validation builds):

  * 32 near-identical units                           design-gap (the design is the same unit
                                                      32 times) or develop (the build collapsed
                                                      a varied design)
  * 4 groups with the same mechanic, only cosmetic   develop (the design varies, the probe
    change                                            shows the same kinds in every group)
  * a build shipping fewer units than the design     develop
  * units unreachable                                develop
  * climax units sharing art                         design-gap (the design names one drawing)
                                                     or develop (the build draws them alike)
  * a probe without entities[].kind                  develop

    python -m unittest scripts.tests.test_content_sufficiency
"""

import copy
import json
import os
import shutil
import sys
import tempfile
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
sys.path.insert(0, SCRIPTS)

from wgf_sufficiency import audit as auditing  # noqa: E402
from wgf_sufficiency.step import ContentSufficiencyStep  # noqa: E402
from wgf_playability.step import PlayabilityStep  # noqa: E402
from wgflib.workflow.contracts import ArtifactContracts  # noqa: E402
from wgflib.workflow.model import StepOutcome  # noqa: E402

COMMIT = "c" * 40
GROUPS = ("w1", "w2", "w3", "w4")
STRUCTURES = ("static-field", "moving-field", "descending-field")
# Per group: (elements introduced, an older element mixed back in). Four units per group, the
# last a climax.
INTRODUCED = {"w1": ("e1", "e2"), "w2": ("e3", "e4"), "w3": ("e5", "e6"), "w4": ("e7", "e8")}
OLDER = {"w1": ("e1", "e2"), "w2": ("e1", "e2"), "w3": ("e1", "e3"), "w4": ("e2", "e4")}


def _unit(position, group, elements, structure, objective_kind, purpose, art=None,
          grid=None, tier="post-mvp"):
    unit = {"id": f"u-{position:02d}", "index": position, "tier": tier, "purpose": purpose,
            "objective": f"Clear unit {position} of the {group} world",
            "objective_kind": objective_kind, "group": group, "structure": structure,
            "elements": list(elements), "mechanics": ["bat"],
            "difficulty": {"speed": round(0.1 + 0.05 * position, 3),
                           "density": round(0.1 + 0.04 * position, 3)},
            "expected_duration_s": 30, "success": "Every brick is cleared before the timer",
            "failure": "The ball falls past the bat three times",
            "acceptance": [f"Unit {position} is cleared by the recorded solution",
                           f"Unit {position} shows its objective inside one second"],
            "parameters": {"grid": grid or [f"{position:02d}{group}{'x' * (position % 7)}",
                                            f"row-{position * 3}", f"{group}-{position}-bricks",
                                            f"pattern-{position % 5}-{position}"]}}
    if art:
        unit["art"] = list(art)
    return unit


def varied_units():
    """16 units in four worlds: new elements in every world, a climax closing each with its
    own boss drawing, three structures, three objective kinds, relief units."""
    units, position = [], 0
    for g_number, group in enumerate(GROUPS, 1):
        new, old = INTRODUCED[group], OLDER[group]
        plan = ((new[0], old[0]), (new[0], new[1]), (new[1], old[1]))
        for slot, elements in enumerate(plan):
            position += 1
            units.append(_unit(position, group, elements, STRUCTURES[slot],
                               ("clear-all", "survive", "reach-exit")[slot],
                               "breather" if slot == 0 and g_number > 1 else
                               ("teach" if slot == 0 else "test"),
                               tier="mvp" if position <= 6 else "post-mvp"))
        position += 1
        units.append(_unit(position, group, (new[0], new[1], f"boss{g_number}"), "boss-arena",
                           "defeat-boss", "climax", art=[f"boss-{g_number}"],
                           tier="mvp" if position <= 6 else "post-mvp"))
    return units


def design_of(units, tier="release", mode="authored", groups=GROUPS):
    return {"title_id": "demo", "provenance": {"content_hash": "sha256:" + "d" * 64},
            "genre": {"family": "arcade", "node": "arcade", "session_profile": "standard",
                      "ending": "finite"},
            "build_spec": {
                "difficulty": {"axes": [{"id": "speed", "range": [0, 1]},
                                        {"id": "density", "range": [0, 1]}]},
                "progression": {"model": "unlock-track", "steps": [
                    {"id": f"open-{g}", "tier": "mvp", "unlock_condition": f"clear the {g} climax",
                     "grants": "the next world"} for g in groups[:-1]]},
                "content": {"quality_tier": tier, "unit_kind": "level",
                            "generation": {"mode": mode},
                            "groups": [{"id": g, "name": g.upper()} for g in groups],
                            "secondary_goals": [{"id": "stars", "kind": "stars",
                                                 "description": "Three stars for a clean clear"}],
                            "units": units}}}


def data_of(units, drop=(), **overrides):
    """The content data file a developer writes from the design's table."""
    built = []
    for unit in units:
        if unit["id"] in drop:
            continue
        entry = {k: unit[k] for k in ("id", "index", "tier", "objective", "mechanics",
                                      "difficulty", "expected_duration_s", "success", "failure")}
        entry["layout"] = copy.deepcopy(unit["parameters"])
        entry.update(overrides.get(unit["id"], {}))
        built.append(entry)
    return {"schema": "wgf-content/1", "unit_kind": "level", "generation": {"mode": "authored"},
            "units": built}


def survey_of(units, traversed=3, entered=None, kinds=None, assets=None, unkinded=0):
    """A desktop traverse of the first units and a survey of every unit, as bot.spec.ts writes
    them. `kinds(unit)` / `assets(unit)` say what the probe drew in a unit."""
    kinds = kinds or (lambda u: list(u["elements"]))
    assets = assets or (lambda u: list(u.get("art") or []))
    entered = (lambda u: True) if entered is None else entered
    per_unit = [{"unit_id": u["id"], "index": u["index"], "kinds": kinds(u) + ["bat"],
                 "difficulty": dict(u["difficulty"]), "won": True} for u in units[:traversed]]
    visits = []
    for unit in units:
        inside = entered(unit)
        visits.append({
            "asked": unit["id"], "entered": inside,
            "reported": [unit["id"]] if inside else [],
            "index": unit["index"] if inside else None,
            "kinds_by_role": ({"threat": kinds(unit), "player": ["bat"]} if inside else {}),
            "assets_by_role": ({"threat": assets(unit), "player": ["bat-sprite"]}
                               if inside else {}),
            "content_entities": 6 if inside else 0, "unkinded": unkinded if inside else 0,
            "difficulty": dict(unit["difficulty"]) if inside else {},
            "won": inside, "lost": False, "duration_ms": 21000 if inside else None,
            "playing_ms": 900})
    first = {"samples": [{"state": "playing", "metrics": {}, "inputs": [], "entities": [
        {"id": "p", "role": "player", "kind": "bat", "x": 0, "y": 0, "w": 9, "h": 9,
         "visible": True}]}]}
    return {"desktop": {"first-session": first,
                        "traverse": {"applies": True, "per_unit": per_unit, "stopped": "max units"},
                        "survey": {"applies": True, "visits": visits}}}


def run(design, data, records, strategy=None):
    return auditing.audit(design, strategy, data, records)


def status(result, check):
    return next(c for c in result["checks"] if c["id"] == check)


class VariedReleaseBuild(unittest.TestCase):
    def test_a_varied_build_at_the_release_tier_passes_every_check(self):
        units = varied_units()
        result = run(design_of(units), data_of(units), survey_of(units))
        failing = [(c["id"], c["summary"]) for c in result["checks"] if c["status"] != "PASS"]
        self.assertEqual(failing, [])
        self.assertEqual(result["findings"], [])
        self.assertEqual(result["tier"], "release")
        # What was counted, on the build: the probe's kinds, not the design's ids.
        elements = result["metrics"]["content.elements"]["build"]
        self.assertGreaterEqual(elements["distinct"], 8)
        self.assertEqual(result["metrics"]["content.combinations"]["build"]["distinct_ratio"], 1.0)

    def test_every_unit_beyond_the_traverse_counts_through_the_survey(self):
        units = varied_units()
        result = run(design_of(units), data_of(units), survey_of(units, traversed=3))
        reach = status(result, "content.units_reachable")
        self.assertEqual(reach["status"], "PASS")
        self.assertIn("16 shipped unit(s)", reach["summary"])


class NearIdenticalUnits(unittest.TestCase):
    def thirty_two(self):
        units = []
        for position in range(1, 33):
            group = GROUPS[(position - 1) // 8]
            unit = _unit(position, group, ("e1",), "static-field", "clear-all", "test",
                         grid=["xxxx....xxxx", "x..x....x..x", "xxxxxxxxxxxx", "....xx....",
                               "x.x.x.x.x.x.", ".x.x.x.x.x.x", "xx..xx..xx..", "..xx..xx..xx"])
            unit["parameters"]["ball_speed"] = round(1 + 0.05 * position, 2)
            units.append(unit)
        return units

    def test_32_near_identical_units_fail_and_the_design_must_grow(self):
        units = self.thirty_two()
        result = run(design_of(units), data_of(units), survey_of(units))
        structure = status(result, "content.structure")
        self.assertEqual(structure["status"], "FAIL")
        self.assertEqual(structure["route"], "design-gap")
        self.assertEqual(structure["measured"]["build"]["repeated_ratio"], 1.0)
        for check in ("content.combinations", "content.elements", "content.groups"):
            self.assertEqual(status(result, check)["status"], "FAIL", check)
        gaps = [f for f in result["findings"] if f["route"] == "design-gap"]
        self.assertTrue(gaps)
        for finding in gaps:
            self.assertEqual(finding["owner"], "game-design")
            self.assertEqual(finding["design_gap"]["severity"], "blocking")

    def test_a_varied_design_built_as_near_identical_units_goes_back_to_develop(self):
        units = varied_units()
        same = {u["id"]: {"structure": "static-field",
                          "layout": {"grid": ["xxxx", "x..x", "xxxx"], "speed": u["index"]}}
                for u in units}
        result = run(design_of(units), data_of(units, **same),
                     survey_of(units, kinds=lambda u: ["brick"], assets=lambda u: ["brick"]))
        for check in ("content.structure", "content.combinations", "content.drift"):
            self.assertEqual(status(result, check)["status"], "FAIL", check)
            self.assertEqual(status(result, check)["route"], "develop", check)


class CosmeticGroups(unittest.TestCase):
    def test_four_groups_with_one_mechanic_and_only_cosmetic_change_fail(self):
        units = varied_units()
        # The design varies; the build draws the same brick in every world.
        result = run(design_of(units), data_of(units),
                     survey_of(units, kinds=lambda u: ["brick"]))
        groups = status(result, "content.groups")
        self.assertEqual(groups["status"], "FAIL")
        self.assertEqual(groups["route"], "develop")
        self.assertEqual(groups["measured"]["build"]["idle"], ["w2", "w3", "w4"])
        self.assertIn("cosmetic", groups["summary"])
        self.assertEqual(status(result, "content.elements")["status"], "FAIL")
        finding = next(f for f in result["findings"] if f["check"] == "content.groups")
        self.assertEqual((finding["owner"], finding["route"]), ("level-design", "develop"))


class FewerUnitsThanDesigned(unittest.TestCase):
    def test_a_build_shipping_fewer_units_than_the_design_fails_to_develop(self):
        units = varied_units()
        dropped = [u["id"] for u in units[12:]]
        result = run(design_of(units), data_of(units, drop=dropped), survey_of(units[:12]))
        shipped = status(result, "content.units_shipped")
        self.assertEqual(shipped["status"], "FAIL")
        self.assertEqual(shipped["route"], "develop")
        self.assertEqual(shipped["measured"]["missing"], dropped)

    def test_a_design_short_of_the_tier_count_is_a_design_gap(self):
        units = varied_units()[:8]
        result = run(design_of(units, groups=GROUPS[:2]), data_of(units), survey_of(units))
        shipped = status(result, "content.units_shipped")
        self.assertEqual((shipped["status"], shipped["route"]), ("FAIL", "design-gap"))


class UnreachableUnits(unittest.TestCase):
    def test_units_the_probe_never_entered_fail(self):
        units = varied_units()
        records = survey_of(units, entered=lambda u: u["index"] <= 3)
        result = run(design_of(units), data_of(units), records)
        reach = status(result, "content.units_reachable")
        self.assertEqual((reach["status"], reach["route"]), ("FAIL", "develop"))
        self.assertEqual(len(reach["measured"]["unreached"]), 13)

    def test_a_build_that_ignores_the_unit_link_is_named(self):
        units = varied_units()
        records = survey_of(units, traversed=3, entered=lambda u: False)
        result = run(design_of(units), data_of(units), records)
        reach = status(result, "content.units_reachable")
        self.assertEqual(reach["status"], "FAIL")
        self.assertIn("does not honour it", reach["summary"])

    def test_no_survey_is_unmeasured_beyond_the_traverse_not_a_pass(self):
        units = varied_units()
        records = survey_of(units)
        records["desktop"]["survey"] = {"applies": False, "reason": "no survey was asked for"}
        result = run(design_of(units), data_of(units), records)
        reach = status(result, "content.units_reachable")
        self.assertEqual(reach["status"], "FAIL")
        self.assertIn("no survey ran", reach["summary"])


class ClimaxArt(unittest.TestCase):
    def test_climax_units_sharing_one_drawing_in_the_design_are_a_design_gap(self):
        units = varied_units()
        for unit in units:
            if unit["purpose"] == "climax":
                unit["art"] = ["boss"]
        result = run(design_of(units), data_of(units), survey_of(units))
        climax = status(result, "content.climax")
        self.assertEqual((climax["status"], climax["route"]), ("FAIL", "design-gap"))
        self.assertIn("share art", climax["summary"])

    def test_a_build_drawing_every_climax_with_the_same_asset_goes_to_develop(self):
        units = varied_units()
        result = run(design_of(units), data_of(units),
                     survey_of(units, assets=lambda u: ["boss-1"] if u["purpose"] == "climax"
                               else []))
        climax = status(result, "content.climax")
        self.assertEqual((climax["status"], climax["route"]), ("FAIL", "develop"))
        self.assertIn("same assets", climax["summary"])


class EntityKinds(unittest.TestCase):
    def test_entities_without_a_kind_fail_authored_content(self):
        units = varied_units()
        result = run(design_of(units), data_of(units), survey_of(units, unkinded=2))
        kinds = status(result, "content.entity_kinds")
        self.assertEqual((kinds["status"], kinds["route"]), ("FAIL", "develop"))

    def test_the_probe_schema_requires_a_kind_while_a_unit_is_in_play(self):
        from wgflib import jsonschema_lite
        from wgf_playability.analysis import PROBE_SCHEMA
        with open(PROBE_SCHEMA, encoding="utf-8") as handle:
            validator = jsonschema_lite.Validator(json.load(handle))
        entity = {"id": "a", "role": "hazard", "x": 0, "y": 0, "w": 4, "h": 4, "visible": True}
        snapshot = {"state": "playing", "metrics": {}, "inputs": [], "entities": [entity]}
        self.assertEqual(list(validator.iter_errors(snapshot)), [])
        snapshot["content"] = {"unit_id": "u-01", "unit_index": 1, "unit_count": 16,
                               "unit_kind": "level"}
        self.assertTrue(list(validator.iter_errors(snapshot)))
        entity["kind"] = "spike"
        self.assertEqual(list(validator.iter_errors(snapshot)), [])


class Contract(unittest.TestCase):
    def test_no_content_at_the_release_tier_is_a_design_gap(self):
        design = design_of(varied_units())
        del design["build_spec"]["content"]
        design["build_spec"]["content"] = None
        result = run(design, None, {}, strategy={"concept": {"content_model": {
            "quality_tier": "release"}}})
        contract = status(result, "content.contract")
        self.assertEqual((contract["status"], contract["route"]), ("FAIL", "design-gap"))

    def test_no_content_below_the_release_tier_measures_nothing(self):
        design = design_of(varied_units(), tier="mvp")
        design["build_spec"]["content"] = None
        result = run(design, None, {})
        self.assertTrue(all(c["status"] == "SKIPPED" for c in result["checks"]))
        self.assertEqual(result["findings"], [])

    def test_generated_content_skips_the_unit_list(self):
        units = varied_units()
        result = run(design_of(units, mode="procedural"), None, survey_of(units))
        skipped = {c["id"] for c in result["checks"] if c["status"] == "SKIPPED"}
        self.assertIn("content.units_shipped", skipped)
        self.assertEqual(status(result, "content.entity_kinds")["status"], "PASS")

    def test_the_mvp_tier_holds_only_the_family_count_and_the_build_to_its_design(self):
        units = varied_units()[:4]
        for unit in units:
            unit["tier"] = "mvp"
        result = run(design_of(units, tier="mvp", groups=GROUPS[:1]), data_of(units),
                     survey_of(units))
        self.assertEqual([c["id"] for c in result["checks"] if c["status"] == "FAIL"], [])
        skipped = {c["id"] for c in result["checks"] if c["status"] == "SKIPPED"}
        self.assertIn("content.structure", skipped)


class Layouts(unittest.TestCase):
    def test_layouts_are_compared_by_path_and_value(self):
        rules = auditing.load_rules()
        a = auditing.layout_of({"id": "x", "layout": {"grid": ["ab", "cd"], "speed": 1}}, rules)
        b = auditing.layout_of({"id": "y", "layout": {"grid": ["ab", "cd"], "speed": 2}}, rules)
        c = auditing.layout_of({"id": "z", "layout": {"grid": ["cd", "ab"], "speed": 1}}, rules)
        self.assertEqual(set(a), {"layout.grid[0]", "layout.grid[1]", "layout.speed"})
        # A tuning number is the same layout at another difficulty.
        self.assertEqual(auditing.similarity(a, b), 1.0)
        self.assertAlmostEqual(auditing.similarity(a, c), 0.2)
        # A number in a list is the layout itself.
        d = auditing.layout_of({"cells": [[1, 0], [0, 1]]}, rules)
        e = auditing.layout_of({"cells": [[0, 1], [1, 0]]}, rules)
        self.assertEqual(auditing.similarity(d, e), 0.0)
        self.assertEqual(auditing.similarity({}, {}), 1.0)


class Step(unittest.TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.base, ignore_errors=True)

    def write(self, records, data, records_dir="playability/1-1/out"):
        for project, recs in records.items():
            os.makedirs(os.path.join(self.base, records_dir, project), exist_ok=True)
            for name, record in recs.items():
                with open(os.path.join(self.base, records_dir, project, f"{name}.json"), "w",
                          encoding="utf-8") as handle:
                    json.dump(record, handle)
        if data is not None:
            os.makedirs(os.path.join(self.base, records_dir, "content"), exist_ok=True)
            with open(os.path.join(self.base, records_dir, "content", "units.json"), "w",
                      encoding="utf-8") as handle:
                json.dump(data, handle)
        return records_dir

    def run_step(self, docs):
        class Inputs:
            refs = {k: types.SimpleNamespace(content_hash=None) for k in docs}

            def __contains__(self, k):
                return k in docs

            def load(self, k):
                return docs[k]

        class Log:
            def __getattr__(self, name):
                return lambda *a, **k: None

        context = types.SimpleNamespace(config={}, run_dir=self.base, logger=Log(), visit=1,
                                        attempt=1, execution=1)
        result = ContentSufficiencyStep(types.SimpleNamespace(
            params={}, id="content-sufficiency")).execute(Inputs(), context)
        for artifact in result.artifacts:
            self.assertEqual(ArtifactContracts()("content-sufficiency-report", artifact.content),
                             [])
        return result

    def docs(self, design, records_dir, verdict="PASS"):
        play = {"title_id": "demo", "commit": COMMIT, "verdict": verdict,
                "records_dir": records_dir,
                "projects": [{"id": "desktop", "ran": True}, {"id": "mobile", "ran": False}]}
        return {"playability-report": play, "game-design": design,
                "scaffold-record": {"title_id": "demo"}}

    def test_a_varied_build_succeeds(self):
        units = varied_units()
        records_dir = self.write(survey_of(units), data_of(units))
        result = self.run_step(self.docs(design_of(units), records_dir))
        self.assertEqual(result.outcome, StepOutcome.SUCCESS)
        self.assertEqual(result.artifacts[0].content["verdict"], "PASS")

    def test_a_short_build_fails_to_develop_with_typed_findings(self):
        units = varied_units()
        records_dir = self.write(survey_of(units[:12]),
                                 data_of(units, drop=[u["id"] for u in units[12:]]))
        result = self.run_step(self.docs(design_of(units), records_dir))
        self.assertEqual((result.outcome, result.route), (StepOutcome.FAILED, "develop"))
        report = result.artifacts[0].content
        self.assertIn("content.units_shipped", report["failed"])
        finding = next(f for f in report["findings"] if f["check"] == "content.units_shipped")
        for key in ("id", "dimension", "severity", "observed", "bar", "owner", "route"):
            self.assertIn(key, finding)

    def test_a_design_short_of_its_tier_routes_design_gap_first(self):
        units = NearIdenticalUnits().thirty_two()
        records_dir = self.write(survey_of(units), data_of(units))
        result = self.run_step(self.docs(design_of(units), records_dir))
        self.assertEqual((result.outcome, result.route), (StepOutcome.FAILED, "design-gap"))
        self.assertEqual(result.artifacts[0].content["routes"][0], "design-gap")

    def test_no_content_data_file_fails_authored_content(self):
        units = varied_units()
        records_dir = self.write(survey_of(units), None)
        result = self.run_step(self.docs(design_of(units), records_dir))
        report = result.artifacts[0].content
        self.assertIn("content.data_present", report["failed"])

    def test_nothing_recorded_is_blocked(self):
        result = self.run_step(self.docs(design_of(varied_units()), None))
        self.assertEqual(result.outcome, StepOutcome.BLOCKED)
        blocked = self.run_step(self.docs(design_of(varied_units()), "x", verdict="BLOCKED"))
        self.assertEqual(blocked.outcome, StepOutcome.BLOCKED)

    def test_the_mock_fails_both_ways(self):
        from wgflib.workflow import mock

        class Log:
            def __getattr__(self, name):
                return lambda *a, **k: None

        for plan, route in ((["develop"], "develop"), (["design-gap"], "design-gap"),
                            (["fail"], "develop"), (["success"], None)):
            step = mock.MockContentSufficiencyStep(types.SimpleNamespace(
                params={}, id="content-sufficiency", outputs=["content-sufficiency-report"]))
            context = types.SimpleNamespace(
                environment={"mock_plan": {"content-sufficiency": plan}}, execution=1,
                project_id="demo", logger=Log(), run_id="r")
            result = step.execute(types.SimpleNamespace(refs={}, missing=None), context)
            self.assertEqual(result.route, route)
            report = result.artifacts[0].content
            self.assertEqual(ArtifactContracts()("content-sufficiency-report", report), [])
            self.assertEqual(report["routes"], [route] if route else [])


class RoutedBack(unittest.TestCase):
    """What the two routes carry: design gaps to the design step, findings to the brief."""

    def report(self, judged_hash, routes=("design-gap",)):
        units = NearIdenticalUnits().thirty_two()
        result = run(design_of(units), data_of(units), survey_of(units))
        return {"verdict": "FAIL", "routes": list(routes), "findings": result["findings"],
                "commit": COMMIT,
                "provenance": {"inputs": [{"artifact_type": "game-design",
                                           "content_hash": judged_hash}]}}

    def test_the_design_step_reads_gaps_only_from_a_report_on_the_design_it_holds(self):
        from wgf_design.step import DesignStep
        base = tempfile.mkdtemp()
        try:
            with open(os.path.join(base, "design.json"), "w", encoding="utf-8") as handle:
                json.dump({"provenance": {"content_hash": "sha256:" + "a" * 64}}, handle)
            context = types.SimpleNamespace(run_dir=base, previous_outputs=[
                types.SimpleNamespace(type="game-design", location="design.json")])
            gaps = DesignStep._sufficiency_gaps(self.report("sha256:" + "a" * 64), context)
            self.assertTrue(gaps)
            for gap in gaps:
                self.assertEqual(gap["severity"], "blocking")
                self.assertTrue(gap["field"].startswith("build_spec."))
                self.assertIn("question", gap)
            # A report on a design since repaired is answered already.
            self.assertEqual(DesignStep._sufficiency_gaps(self.report("sha256:" + "b" * 64),
                                                          context), [])
            # A report routed to develop carries nothing for the design.
            self.assertEqual(DesignStep._sufficiency_gaps(
                self.report("sha256:" + "a" * 64, routes=("develop",)), context), [])
        finally:
            shutil.rmtree(base, ignore_errors=True)

    def test_the_develop_brief_lists_the_findings_the_build_owes(self):
        from wgf_develop import brief as briefs
        units = varied_units()
        dropped = [u["id"] for u in units[12:]]
        result = run(design_of(units), data_of(units, drop=dropped), survey_of(units[:12]))
        report = {"verdict": "FAIL", "commit": COMMIT, "findings": result["findings"]}
        made = briefs.build_brief(
            title_id="demo", engine="pixijs", iteration=2, key="k", baseline=COMMIT,
            design=design_of(units), assets=None, scaffold={"title_id": "demo"},
            sufficiency=report)
        checks = [f["check"] for f in made["sufficiency_failures"]]
        self.assertIn("content.units_shipped", checks)
        self.assertEqual(made["sufficiency_commit"], COMMIT)
        text = briefs.render_markdown(made)
        self.assertIn("what the content audit counted on the build", text)
        self.assertIn("content.units_shipped", text)


class PlayabilitySurvey(unittest.TestCase):
    def test_the_survey_asks_for_every_listed_unit_only_when_the_step_asks(self):
        units = varied_units()
        units.append(dict(units[0], id="u-99", index=99, tier="optional"))
        design = design_of(units)
        asked = PlayabilityStep._survey_settings(design, {"survey": True})
        self.assertEqual(asked["survey_units"], [u["id"] for u in units if u["tier"] != "optional"])
        self.assertEqual(asked["survey_projects"], ["desktop"])
        self.assertGreater(asked["survey_ms"], 0)
        self.assertIn("hazard", asked["kind_roles"])
        self.assertEqual(PlayabilityStep._survey_settings(design, {})["survey_units"], [])
        generated = PlayabilityStep._survey_settings(design_of(units, mode="procedural"),
                                                     {"survey": True})
        self.assertEqual(generated["survey_units"], [])

    def test_the_played_commits_content_data_is_kept_beside_the_records(self):
        base = tempfile.mkdtemp()
        try:
            repo, out = os.path.join(base, "repo"), os.path.join(base, "out")
            os.makedirs(os.path.join(repo, "public", "content"))
            with open(os.path.join(repo, "public", "content", "units.json"), "w") as handle:
                handle.write('{"units": []}')
            PlayabilityStep._keep_content_data(repo, out)
            with open(os.path.join(out, "content", "units.json")) as handle:
                self.assertEqual(json.load(handle), {"units": []})
            PlayabilityStep._keep_content_data(os.path.join(base, "none"), out)
        finally:
            shutil.rmtree(base, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()

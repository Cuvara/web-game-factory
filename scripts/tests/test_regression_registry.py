"""The regression registry (WS-9): check tiers and lessons as data, held by check-integrity.

core/reference/check-tiers.yaml classifies every check the Factory's reference files and
producer tables declare as a Hard Gate, a Quality Gate or Advisory; core/reference/lessons.yaml
names, for every lesson the validation runs taught, the check that now holds it and the test
that proves it - or says it is a gap. These tests hold:

  * the shipped registry has no problem, and its tier vocabulary is exactly the three tiers;
  * a check added to a source without a tier fails integrity (a content-sufficiency check, a
    producer check, a design rule whose severity the map does not cover), and so does a
    producer check the code never reports, and a check the floor reads that no producer
    table classifies;
  * a producer check a release blocker reads is never advisory;
  * an enforced lesson whose check or test does not exist fails, a gap that says nothing
    fails, a lesson naming a game fails, and evidence for an unknown lesson fails;
  * a finding of a lesson's check carries the lesson as `guarded_by`;
  * check-integrity reports registry problems as errors.

    python -m unittest scripts.tests.test_regression_registry
"""

import copy
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
for _path in (SCRIPTS, HERE):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from wgf_quality import registry  # noqa: E402
from wgflib.yamllite import load as load_yaml  # noqa: E402

DATA = registry.load(ROOT)
CHECKS, PROBLEMS = registry.classify(DATA["tiers"], ROOT)


def _dump(value, indent=0):
    """A minimal YAML writer for the data these tests round-trip (mappings, lists, scalars)."""
    pad = " " * indent
    if isinstance(value, dict):
        if not value:
            return pad + "{}\n"
        out = ""
        for key, item in value.items():
            if isinstance(item, (dict, list)) and item:
                out += f"{pad}{key}:\n" + _dump(item, indent + 2)
            else:
                out += f"{pad}{key}: {_scalar(item)}\n"
        return out
    if isinstance(value, list):
        out = ""
        for item in value:
            if isinstance(item, dict) and item:
                body = _dump(item, indent + 2)
                out += pad + "- " + body[indent + 2:]
            else:
                out += f"{pad}- {_scalar(item)}\n"
        return out
    return pad + _scalar(value) + "\n"


def _scalar(value):
    import json
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (dict, list)):
        return json.dumps(value)
    return json.dumps(str(value))


class Sandbox(unittest.TestCase):
    """A copy of the files the registry reads, to break one at a time."""

    FILES = ("core/reference/check-tiers.yaml", "core/reference/lessons.yaml",
             "core/reference/quality-floor.yaml", "core/reference/content-sufficiency.yaml",
             "core/reference/visual-qa-rubric.yaml", "core/reference/gate-gaming.yaml",
             "core/reference/design-consistency-rules.yaml",
             "core/reference/quality-policy.yaml", "core/workflows/new-game.workflow.yaml",
             "workspace/lessons/evidence.yaml")
    TREES = ("scripts/wgf_playability", "scripts/wgf_production", "scripts/wgf_assets",
             "scripts/tests")

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="wgf-registry-")
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        for relative in self.FILES:
            target = os.path.join(self.root, *relative.split("/"))
            os.makedirs(os.path.dirname(target), exist_ok=True)
            shutil.copyfile(os.path.join(ROOT, *relative.split("/")), target)
        for relative in self.TREES:
            source = os.path.join(ROOT, *relative.split("/"))
            for current, _dirs, files in os.walk(source):
                for name in files:
                    if not name.endswith(".py"):
                        continue
                    rel = os.path.relpath(os.path.join(current, name), ROOT)
                    target = os.path.join(self.root, rel)
                    os.makedirs(os.path.dirname(target), exist_ok=True)
                    shutil.copyfile(os.path.join(current, name), target)

    def read(self, relative):
        with open(os.path.join(self.root, *relative.split("/")), encoding="utf-8") as handle:
            return load_yaml(handle.read())

    def write(self, relative, data):
        with open(os.path.join(self.root, *relative.split("/")), "w", encoding="utf-8",
                  newline="\n") as handle:
            handle.write(_dump(data))

    def edit_text(self, relative, old, new):
        path = os.path.join(self.root, *relative.split("/"))
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
        self.assertIn(old, text)
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text.replace(old, new, 1))

    def problems(self):
        return registry.problems(self.root)


class ShippedRegistry(unittest.TestCase):
    def test_the_shipped_registry_has_no_problem(self):
        self.assertEqual(registry.problems(ROOT), [])

    def test_the_vocabulary_is_exactly_the_three_tiers(self):
        self.assertEqual(list(DATA["tiers"]["tiers"]), ["hard", "quality", "advisory"])
        self.assertEqual({e["tier"] for e in CHECKS.values()},
                         {"hard", "quality", "advisory"})

    def test_every_source_is_classified(self):
        sources = {e["source"] for e in CHECKS.values()}
        self.assertEqual(sources, set(DATA["tiers"]["sources"]))
        for name in ("quality-floor", "content-sufficiency", "playability",
                     "production-quality", "visual-qa-blocker", "gate-gaming",
                     "design-consistency", "model-review"):
            self.assertIn(name, sources)

    def test_the_floor_rule_tells_a_pass_fail_blocker_from_a_calibrated_bar(self):
        self.assertEqual(CHECKS["quality-floor:floor.core_loop"]["tier"], "hard")
        self.assertEqual(CHECKS["quality-floor:floor.visual_mean"]["tier"], "quality")
        self.assertEqual(CHECKS["quality-floor:floor.music"]["tier"], "quality")
        self.assertEqual(CHECKS["quality-floor:floor.visual_minor_findings"]["tier"],
                         "advisory")
        self.assertEqual(CHECKS["design-consistency:progression_has_an_end_or_a_loop"]["tier"],
                         "advisory")
        self.assertEqual(CHECKS["quality-dimension:ui"]["tier"], "quality")

    def test_every_lesson_is_l1_to_l22_with_a_check_or_a_gap(self):
        lessons = DATA["lessons"]["lessons"]
        self.assertEqual([l["id"] for l in lessons], [f"L{i}" for i in range(1, 23)])
        for lesson in lessons:
            if lesson["status"] in ("enforced", "partial"):
                self.assertTrue(lesson["checks"] and lesson["tests"], lesson["id"])
                for check in lesson["checks"]:
                    self.assertIn(check, CHECKS, lesson["id"])
            elif lesson["status"] == "gap":
                self.assertTrue(lesson["gap"], lesson["id"])

    def test_no_lesson_names_a_game(self):
        games = DATA["evidence"]["games"]
        self.assertTrue(games)
        with open(os.path.join(ROOT, *registry.LESSONS_FILE.split("/")),
                  encoding="utf-8") as handle:
            text = handle.read().lower()
        for game in games:
            self.assertNotIn(game.lower(), text)


class NewChecksNeedATier(Sandbox):
    def test_a_content_check_without_a_tier_fails(self):
        self.edit_text("core/reference/content-sufficiency.yaml",
                       "  content.drift: {dimension: content",
                       "  content.newcheck: {dimension: content, owner: level-design, "
                       "severity: blocker, route: develop}\n  content.drift: {dimension: content")
        problems = self.problems()
        self.assertTrue(any("'content.newcheck', which has no tier" in p for p in problems),
                        problems)

    def test_a_design_rule_whose_severity_the_map_does_not_cover_fails(self):
        self.edit_text("core/reference/design-consistency-rules.yaml",
                       "    severity: warning\n    when: { left: scope.progression_terminal",
                       "    severity: shrug\n    when: { left: scope.progression_terminal")
        problems = self.problems()
        self.assertTrue(any("progression_has_an_end_or_a_loop" in p and "'shrug'" in p
                            for p in problems), problems)

    def test_a_new_floor_criterion_is_classified_by_its_rule(self):
        floor = self.read("core/reference/quality-floor.yaml")
        new = copy.deepcopy(floor["universal"][0])
        new["id"] = "floor.new_thing"
        floor["universal"].append(new)
        self.write("core/reference/quality-floor.yaml", floor)
        checks, problems = registry.classify(self.read("core/reference/check-tiers.yaml"),
                                             self.root)
        self.assertEqual(problems, [])
        self.assertEqual(checks["quality-floor:floor.new_thing"]["tier"], "hard")

    def test_a_check_the_floor_reads_that_no_producer_table_classifies_fails(self):
        self.edit_text("core/reference/quality-floor.yaml",
                       "checks: [probe.present, start.playable,",
                       "checks: [probe.brand_new, probe.present, start.playable,")
        problems = self.problems()
        self.assertTrue(any("'probe.brand_new', which no source of that producer classifies"
                            in p for p in problems), problems)

    def test_a_producer_check_the_code_never_reports_fails(self):
        tiers = self.read("core/reference/check-tiers.yaml")
        tiers["sources"]["playability"]["checks"]["made.up_check"] = "hard"
        self.write("core/reference/check-tiers.yaml", tiers)
        problems = self.problems()
        self.assertTrue(any("'made.up_check' appears nowhere in scripts/wgf_playability" in p
                            for p in problems), problems)

    def test_an_advisory_check_a_release_blocker_reads_fails(self):
        tiers = self.read("core/reference/check-tiers.yaml")
        tiers["sources"]["playability"]["checks"]["restart.works"] = "advisory"
        self.write("core/reference/check-tiers.yaml", tiers)
        problems = self.problems()
        self.assertTrue(any("playability:restart.works is advisory" in p for p in problems),
                        problems)

    def test_a_tier_outside_the_vocabulary_fails(self):
        tiers = self.read("core/reference/check-tiers.yaml")
        tiers["sources"]["production-quality"]["checks"]["ui.text"] = "nice-to-have"
        self.write("core/reference/check-tiers.yaml", tiers)
        self.assertTrue(any("'nice-to-have'" in p for p in self.problems()))


class Lessons(Sandbox):
    def lessons(self):
        return self.read("core/reference/lessons.yaml")

    def set_lesson(self, lesson_id, **changes):
        data = self.lessons()
        for lesson in data["lessons"]:
            if lesson["id"] == lesson_id:
                lesson.update(changes)
                for key, value in list(changes.items()):
                    if value is None:
                        del lesson[key]
        self.write("core/reference/lessons.yaml", data)

    def test_an_enforced_lesson_whose_check_does_not_exist_fails(self):
        self.set_lesson("L5", checks=["playability:content.units_teleport"])
        self.assertTrue(any("L5: check 'playability:content.units_teleport' is not classified"
                            in p for p in self.problems()))

    def test_an_enforced_lesson_whose_test_does_not_exist_fails(self):
        self.set_lesson("L5", tests=["scripts/tests/test_playability.py::test_never_written"])
        self.assertTrue(any("L5: test scripts/tests/test_playability.py has no test "
                            "test_never_written" in p for p in self.problems()))

    def test_an_enforced_lesson_without_a_test_fails(self):
        self.set_lesson("L20", tests=None)
        self.assertTrue(any("L20: an enforced lesson names the test" in p
                            for p in self.problems()))

    def test_a_gap_that_says_nothing_fails(self):
        self.set_lesson("L8", gap=None)
        self.assertTrue(any("L8: a gap lesson says what is not held yet" in p
                            for p in self.problems()))

    def test_a_lesson_naming_a_game_fails(self):
        game = DATA["evidence"]["games"][0]
        self.set_lesson("L2", lesson=f"Seen in {game}: the ramp flipped.")
        self.assertTrue(any(f"L2: names the game {game!r}" in p for p in self.problems()))

    def test_evidence_for_an_unknown_lesson_fails(self):
        evidence = self.read("workspace/lessons/evidence.yaml")
        evidence["lessons"]["L99"] = {"games": [], "evidence": []}
        self.write("workspace/lessons/evidence.yaml", evidence)
        self.assertTrue(any("'L99'" in p for p in self.problems()))


class GuardedBy(unittest.TestCase):
    def test_a_finding_of_a_lessons_check_carries_the_lesson(self):
        guards = registry.guards(DATA["lessons"], DATA["tiers"], "playability-report",
                                 "content.units_reachable@desktop")
        self.assertEqual([g["lesson"] for g in guards], ["L5"])
        self.assertEqual(guards[0]["check"], "playability:content.units_reachable")
        self.assertTrue(guards[0]["tests"])

    def test_a_split_production_finding_carries_its_checks_lesson(self):
        guards = registry.guards(DATA["lessons"], DATA["tiers"], "production-quality-report",
                                 "assets.runtime/develop@mobile")
        self.assertEqual([g["lesson"] for g in guards], ["L3"])

    def test_a_check_no_lesson_names_carries_nothing(self):
        self.assertEqual(registry.guards(DATA["lessons"], DATA["tiers"],
                                         "playability-report", "probe.present"), [])
        self.assertEqual(registry.guards(DATA["lessons"], DATA["tiers"], None, "x"), [])

    def test_triage_marks_the_finding(self):
        from wgf_triage import Routing, normalize
        from wgf_triage.step import _guard
        report = {"title_id": "demo", "commit": "c" * 40, "verdict": "FAIL",
                  "checks": [{"id": "content.units_reachable", "project": "desktop",
                              "status": "FAIL", "required": True, "summary": "late"}]}
        found = normalize("playability-report", report, Routing.load())
        _guard(found)
        self.assertEqual(found[0]["guarded_by"][0]["lesson"], "L5")


class Integrity(unittest.TestCase):
    def test_check_integrity_runs_the_registry(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "check_integrity_registry", os.path.join(SCRIPTS, "check-integrity.py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        cwd = os.getcwd()
        os.chdir(ROOT)
        try:
            module.ERRORS.clear()
            checks, lessons = module.check_regression_registry()
        finally:
            os.chdir(cwd)
        self.assertEqual(module.ERRORS, [])
        self.assertGreater(len(checks), 100)
        self.assertEqual(len(lessons), 22)


if __name__ == "__main__":
    unittest.main()

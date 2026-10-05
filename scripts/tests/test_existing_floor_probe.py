"""An adopted checkout with no content data file still has a floor, measured on its build.

Live (2026-10-05, the 3D run): the adopted checkout predated the content contract - its 12
courses lived in src/game/courses.ts, there was no public/content/units.json - so
game-design.existing_content counted nothing, and the design, the content-sufficiency
regression and develop's floor check held the game to no floor at all. These tests hold:

  * wgf_design/existing.py: such a checkout's floor is recorded `status: unmeasured` at its
    commit (schema-valid), and measured through the play probe on the records of a visit
    that played exactly that commit - the units, groups, climax units and element kinds
    reached, the build's own unit count - never on another commit;
  * the playability step carries that floor in its report, and a floor once measured is the
    run's: a later visit never measures again, a re-entered design takes the earliest;
  * develop: the first greybox visit plays the adopted HEAD with no developer; until a
    content data file counts the build, a commit that deletes a shipped source file of a
    content module is refused - even for a specialist;
  * content-sufficiency: an unmeasured floor is SKIPPED (never a pass); a probe floor holds a
    build that gained a content data file to the earlier count, and a build without one is
    counted through the probe;
  * the quality gate: an unmeasured floor is an unmeasured blocker (content BELOW_FLOOR),
    and a run that adopted nothing is not held to the criterion at all.

Deterministic and offline (local git repositories in temporary directories). Run from the
repository root:

    python -m unittest scripts.tests.test_existing_floor_probe
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, HERE)

from test_brief_commitments import adopted_content, git  # noqa: E402
from test_content_sufficiency import design_of, varied_units  # noqa: E402
from test_design_module import run_step, variant  # noqa: E402
import test_develop_module as develop_tests  # noqa: E402
import test_quality_gate as quality_gate_tests  # noqa: E402
from wgf_design import existing  # noqa: E402
from wgf_develop import brief as develop_briefs  # noqa: E402
from wgf_develop import floor as content_floor  # noqa: E402
from wgf_playability.step import PlayabilityStep  # noqa: E402
from wgf_sufficiency import audit as auditing  # noqa: E402
from wgflib.workflow.contracts import ArtifactContracts  # noqa: E402
from wgflib.workflow.model import StepOutcome  # noqa: E402

SHIPPED = "c" * 40
COURSES = 12
# The shipped source the 3D game's content lived in: a content module, and one that is not.
COURSES_TS = "src/game/courses.ts"
CAMERA_TS = "src/render/camera.ts"


def unmeasured(commit=SHIPPED):
    return {"status": "unmeasured",
            "source": {"method": "probe", "path": "public/content/units.json",
                       "commit": commit},
            "ruleset": "brief-commitments@1.1.0",
            "reason": "ships no public/content/units.json"}


def records(reached=4, reported=COURSES, worlds=2, commit_kinds=("bumper", "ramp", "gem")):
    """Playability records of the adopted 3D build: the traverse reached `reached` courses of
    `worlds` worlds (ids w<world>-c<n>), the last course of each world a boss, while the
    probe stated `reported` units; entities drawn of content kinds."""
    per_world = max(1, reached // worlds)
    per_unit = []
    for index in range(reached):
        w, n = index // per_world + 1, index % per_world + 1
        objective = ("Beat the boss marble to the goal" if n == per_world
                     else f"Roll to the goal of course {n}")
        per_unit.append({"unit_id": f"w{w}-c{n}", "index": index + 1, "objective": objective,
                         "objective_texts": [objective], "kinds": list(commit_kinds[:2]),
                         "won": True})
    sample = {"state": "playing",
              "content": {"unit_id": "w1-c1", "unit_index": 1, "unit_count": reported,
                          "unit_kind": "course", "objective": "Roll to the goal of course 1"},
              "entities": [{"id": "e1", "role": "hazard", "kind": commit_kinds[-1]},
                           {"id": "p", "role": "player", "kind": "marble"}]}
    desktop = {"first-session": {"samples": [sample]},
               "traverse": {"applies": True, "per_unit": per_unit,
                            "unit_count_reported": reported, "snapshots": []}}
    return {"desktop": desktop}


class _Log:
    def __getattr__(self, name):
        return lambda *a, **k: None


class TheFloorOfACheckoutWithoutContentData(unittest.TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp(prefix="wgf-adopt-probe-")
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)
        self.strategy = variant()
        self.title = self.strategy["title_id"]
        self.checkout = os.path.join(self.base, self.title)
        os.makedirs(os.path.join(self.checkout, "src", "game"))
        with open(os.path.join(self.checkout, *COURSES_TS.split("/")), "w", encoding="utf-8",
                  newline="\n") as handle:
            handle.write("export const COURSES = [/* 12 courses */];\n")
        git(self.checkout, "init", "-q")
        git(self.checkout, "add", "-A")
        git(self.checkout, "commit", "-q", "-m", "the shipped game, before the content contract")
        self.head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.checkout,
                                   capture_output=True, text=True, check=True).stdout.strip()
        self.config = {"checkouts": self.base, "init": {"adopt_existing": True}}

    def test_no_content_data_is_an_unmeasured_floor_never_no_floor(self):
        floor, note = existing.read_floor(self.config, self.title)
        self.assertIsNotNone(floor)
        self.assertEqual(floor["status"], "unmeasured")
        self.assertEqual(floor["source"]["method"], "probe")
        self.assertEqual(floor["source"]["commit"], self.head)
        self.assertNotIn("units", floor)
        self.assertFalse(existing.measured(floor))
        self.assertIn("play probe", note)

    def test_the_design_records_the_unmeasured_floor_and_validates(self):
        result = run_step(self.strategy, config=self.config)
        design = result.artifacts[0].content
        self.assertEqual(design["existing_content"]["status"], "unmeasured")
        self.assertEqual(design["existing_content"]["source"]["commit"], self.head)
        self.assertEqual(ArtifactContracts()("game-design", design), [])


class TheProbeFloor(unittest.TestCase):
    def test_the_shipped_build_is_counted_through_the_probe(self):
        floor, note = existing.probe_floor(unmeasured(), records(), SHIPPED,
                                           report="playability-report-x", step="greybox-playability")
        self.assertEqual(floor["status"], "measured")
        self.assertEqual(floor["source"]["method"], "probe")
        self.assertEqual(floor["source"]["commit"], SHIPPED)
        self.assertEqual(floor["source"]["report"], "playability-report-x")
        # The traverse reached 4 of the 12 courses the build says it ships: 12 is the floor.
        self.assertEqual(floor["units"], COURSES)
        self.assertEqual(floor["groups"], 2)
        self.assertEqual(floor["climax_units"], 2)
        self.assertEqual(floor["elements"], 3)  # bumper, ramp, gem - never the player marble
        self.assertEqual(floor["unit_ids"], ["w1-c1", "w1-c2", "w2-c1", "w2-c2"])
        self.assertIn("content.unit_count 12", floor["measured_by"]["units"])
        self.assertIn("12 unit(s)", note)
        report = {"title_id": "demo", "existing_content": floor}
        problems = [e for e in ArtifactContracts()("playability-report", report)
                    if "existing_content" in str(e)]
        self.assertEqual(problems, [])

    def test_another_commit_is_not_the_shipped_build(self):
        floor, note = existing.probe_floor(unmeasured(), records(), "d" * 40)
        self.assertIsNone(floor)
        self.assertIn("stays unmeasured", note)

    def test_a_build_whose_probe_reports_no_unit_measures_nothing(self):
        floor, note = existing.probe_floor(unmeasured(), {"desktop": {}}, SHIPPED)
        self.assertIsNone(floor)
        self.assertIn("no content unit", note)


class ThePlayabilityStep(unittest.TestCase):
    def setUp(self):
        self.run_dir = tempfile.mkdtemp(prefix="wgf-adopt-play-")
        self.addCleanup(shutil.rmtree, self.run_dir, ignore_errors=True)
        self.context = types.SimpleNamespace(logger=_Log(), execution=1, run_dir=self.run_dir,
                                             current_step="greybox-playability")
        self.design = {"existing_content": unmeasured()}

    def write_report(self, version, floor):
        directory = os.path.join(self.run_dir, "artifacts", "playability-report")
        os.makedirs(directory, exist_ok=True)
        with open(os.path.join(directory, f"v{version}.json"), "w", encoding="utf-8") as handle:
            json.dump({"commit": floor["source"]["commit"], "existing_content": floor}, handle)

    def test_the_visit_that_plays_the_shipped_build_measures_it(self):
        floor, measuring = PlayabilityStep._floor_state(self.design, SHIPPED, self.context)
        self.assertTrue(measuring)
        self.assertEqual(floor["status"], "unmeasured")

    def test_a_visit_on_a_developer_commit_measures_nothing(self):
        _floor, measuring = PlayabilityStep._floor_state(self.design, "d" * 40, self.context)
        self.assertFalse(measuring)

    def test_a_floor_once_measured_is_carried_never_measured_again(self):
        first, _ = existing.probe_floor(unmeasured(), records(), SHIPPED, report="first")
        later, _ = existing.probe_floor(unmeasured(), records(reported=3, reached=2), SHIPPED,
                                        report="later")
        self.write_report(1, first)
        self.write_report(2, later)
        floor, measuring = PlayabilityStep._floor_state(self.design, SHIPPED, self.context)
        self.assertFalse(measuring)
        self.assertEqual((floor["units"], floor["source"]["report"]), (COURSES, "first"))
        result = PlayabilityStep(types.SimpleNamespace(params={}))._finish(
            self.context, types.SimpleNamespace(refs={}), "demo", "e" * 40, [], [], {}, None,
            [{"id": "desktop", "viewport": {"width": 1280, "height": 720}, "ran": True}],
            floor=floor)
        report = result.artifacts[0].content
        self.assertEqual(report["existing_content"]["units"], COURSES)
        self.assertEqual(report["existing_content"]["source"]["report"], "first")
        self.assertEqual(ArtifactContracts()("playability-report", report), [])

    def test_the_traverse_plays_past_the_bars_few_units_to_reach_what_ships(self):
        self.assertGreaterEqual(PlayabilityStep._probe_max_units(), COURSES)

    def test_a_reentered_design_takes_the_earliest_probe_floor(self):
        first, _ = existing.probe_floor(unmeasured(), records(), SHIPPED, report="first")
        self.write_report(3, first)
        later, _ = existing.probe_floor(unmeasured(), records(reported=2, reached=2), SHIPPED,
                                        report="later")
        self.write_report(7, later)
        self.write_report(12, dict(later, source=dict(later["source"], commit="d" * 40)))
        found = existing.run_probe_floor(self.run_dir, unmeasured())
        self.assertEqual(found["source"]["report"], "first")


class ContentModules(unittest.TestCase):
    def test_a_content_module_is_named_by_its_path(self):
        self.assertEqual(existing.content_modules(
            [COURSES_TS, CAMERA_TS, "src/levels/world-1.ts", "src/ui/minimap.ts",
             "README.md", "src/content/index.ts"]),
            [COURSES_TS, "src/levels/world-1.ts", "src/content/index.ts"])

    def test_no_visit_deletes_a_content_module_while_nothing_counts_the_build(self):
        checkout = tempfile.mkdtemp(prefix="wgf-adopt-floor-")
        self.addCleanup(shutil.rmtree, checkout, ignore_errors=True)
        git_files = types.SimpleNamespace(
            files_at=lambda commit, *roots: [f for f in (COURSES_TS, CAMERA_TS)
                                             if any(f.startswith(r + "/") for r in roots)])
        design = {"existing_content": unmeasured()}
        found, allowed = content_floor.problems(checkout, design, git_files,
                                                findings_visit=True)
        self.assertEqual(allowed, [])
        self.assertTrue(any(COURSES_TS in p and "not measured yet" in p for p in found), found)
        self.assertFalse(any(CAMERA_TS in p for p in found), found)


class AnAdoptedGameWithoutContentDataInDevelop(develop_tests.DevelopCase):
    def setUp(self):
        super().setUp()
        for relative in (COURSES_TS, CAMERA_TS):
            path = os.path.join(self.repo, *relative.split("/"))
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8", newline="\n") as handle:
                handle.write("export const shipped = true;\n")
        self.git("add", "-A")
        self.git(*develop_tests.IDENTITY, "commit", "-q", "-m", "the shipped game")
        self.shipped = self.git("rev-parse", "HEAD").strip()
        self.design = develop_tests.fixture("game-design")
        self.design["existing_content"] = unmeasured(self.shipped)

    def inputs(self, greybox=False):
        types_ = (("game-design", "scaffold-record", "title-strategy") if greybox else
                  ("game-design", "asset-manifest", "scaffold-record", "title-strategy"))
        return develop_tests.inputs_for(types=types_, overrides={"game-design": self.design})

    def step(self, runner, phase):
        step = develop_tests.step_with(runner)
        step.definition.params = {"phase": phase}
        return step

    def test_the_first_greybox_visit_plays_the_shipped_head_with_no_developer(self):
        runner = develop_tests.FakeRunner(on_develop=develop_tests.write_game)
        result = self.step(runner, "greybox").execute(
            self.inputs(greybox=True), develop_tests.context(self.command_config()))
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
        self.assertEqual(runner.developer_calls(), [])
        self.assertEqual(result.artifacts[0].content["build_ref"]["commit_sha"], self.shipped)

    def test_a_commit_that_deletes_a_shipped_content_module_is_refused(self):
        runner = develop_tests.FakeRunner(on_develop=lambda cwd: develop_tests.write_game(
            cwd, extra={COURSES_TS: None}))
        result = self.step(runner, "production").execute(
            self.inputs(), develop_tests.context(self.command_config()))
        self.assertEqual(result.outcome, StepOutcome.FAILED)
        self.assertIn("QUALITY REGRESSION", result.error)
        self.assertIn(COURSES_TS, result.error)
        self.assertEqual(self.git("rev-parse", "HEAD").strip(), self.shipped)

    def test_a_commit_that_keeps_the_content_modules_is_committed(self):
        runner = develop_tests.FakeRunner(on_develop=lambda cwd: develop_tests.write_game(
            cwd, extra={CAMERA_TS: None}))
        result = self.step(runner, "production").execute(
            self.inputs(), develop_tests.context(self.command_config()))
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
        self.assertNotEqual(self.git("rev-parse", "HEAD").strip(), self.shipped)

    def test_the_brief_states_the_unmeasured_floor(self):
        runner = develop_tests.FakeRunner(fail=("build",))
        self.step(runner, "greybox").execute(
            self.inputs(greybox=True), develop_tests.context(self.config()))
        with open(os.path.join(self.repo, develop_briefs.BRIEF_DIR, "brief.md"), encoding="utf-8") as handle:
            text = handle.read()
        self.assertIn("has not been counted yet", text)
        self.assertIn("content module", text)


class TheRegressionCheck(unittest.TestCase):
    def setUp(self):
        self.units = varied_units()
        self.design = design_of(self.units)
        self.design["existing_content"] = unmeasured()
        self.floor, _ = existing.probe_floor(unmeasured(), records(), SHIPPED, report="first")

    def test_an_unmeasured_floor_is_skipped_never_passed(self):
        check = auditing.regression_check(self.design, None, "absent", records(), None)
        self.assertEqual(check["status"], "SKIPPED")
        self.assertTrue(check["required"])
        self.assertIn("UNMEASURED FLOOR", check["summary"])

    def test_a_build_that_gains_content_data_is_held_to_the_earlier_floor(self):
        play = {"existing_content": self.floor}
        # The new content data file lists 8 courses: below the 12 the shipped build carried.
        data = {"units": [{"id": f"w{w}-c{n}"} for w in (1, 2) for n in range(1, 5)]}
        check = auditing.regression_check(self.design, data, None, records(), play)
        self.assertEqual(check["status"], "FAIL")
        self.assertIn("units: the build ships 8, 12 shipped", check["summary"])
        self.assertIn("content data file", check["summary"])
        self.assertEqual(check["expected"]["units"], COURSES)

    def test_a_build_without_content_data_is_counted_through_the_probe(self):
        play = {"existing_content": self.floor}
        check = auditing.regression_check(self.design, None, "absent", records(), play)
        self.assertEqual(check["status"], "PASS", check["summary"])
        short = records(reached=2, reported=6)
        check = auditing.regression_check(self.design, None, "absent", short, play)
        self.assertEqual(check["status"], "FAIL")
        self.assertIn("the play probe", check["summary"])

    def test_a_probe_floor_of_another_commit_is_not_this_runs(self):
        stray = dict(self.floor, source=dict(self.floor["source"], commit="d" * 40))
        check = auditing.regression_check(self.design, None, "absent", records(),
                                          {"existing_content": stray})
        self.assertEqual(check["status"], "SKIPPED")


class TheQualityGate(unittest.TestCase):
    setUp = quality_gate_tests.Gate.setUp
    run_step = quality_gate_tests.Gate.run_step
    dimension = staticmethod(quality_gate_tests.Gate.dimension)

    def test_an_unmeasured_floor_is_an_unmeasured_blocker(self):
        design = design_of(varied_units())
        design["existing_content"] = unmeasured()
        check = auditing.regression_check(design, None, "absent", records(), None)
        docs = quality_gate_tests.release_build(tier="mvp")
        docs["content-sufficiency-report"]["checks"].append(check)
        docs["content-sufficiency-report"]["skipped_checks"].append(
            {"id": check["id"], "reason": check["summary"]})
        result = self.run_step(docs)
        self.assertEqual(result.outcome, StepOutcome.FAILED)
        report = result.artifacts[0].content
        criterion = next(c for c in report["criteria"] if c["id"] == "floor.existing_content")
        self.assertEqual((criterion["status"], criterion["severity"]), ("UNMEASURED", "blocker"))
        content = self.dimension(report, "content")
        self.assertEqual(content["status"], "BELOW_FLOOR")
        self.assertIn("floor.existing_content", content["blockers_failed"])

    def test_a_run_that_adopted_nothing_is_not_held_to_it(self):
        result = self.run_step(quality_gate_tests.release_build(tier="mvp"))
        report = result.artifacts[0].content
        self.assertNotIn("floor.existing_content", [c["id"] for c in report["criteria"]])


if __name__ == "__main__":
    unittest.main()

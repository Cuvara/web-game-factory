"""The visual-qa step (scripts/wgf_visualqa): a vision judge reads the production build's frames.

The judge here is a fixture command - a Python script that writes the verdict a scenario
names - so every path the step takes is exercised without an agent host: a pass, a blocker
routed to assets, a blocker routed to develop, a dimension below the bar, a malformed
verdict retried once and then failed, a malformed verdict fixed on the retry, a verdict on
stdout, no judge (BLOCKED), a frame changed since playability recorded it, and a judge that
writes into what it may only read. The real judge's calibration run is in
docs/visual-qa-module.md.

    python -m unittest scripts.tests.test_visual_qa
"""

import hashlib
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

from wgf_assets.raster import Image, encode_png  # noqa: E402
from wgf_visualqa import rubric as rubric_mod  # noqa: E402
from wgf_visualqa.brief import frame_state  # noqa: E402
from wgf_visualqa.step import VisualQAStep  # noqa: E402
from wgflib.workflow import mock  # noqa: E402
from wgflib.workflow.contracts import ArtifactContracts  # noqa: E402
from wgflib.workflow.model import StepOutcome  # noqa: E402

RUBRIC = rubric_mod.load_rubric()
DIMENSIONS = list(RUBRIC["dimensions"])

# The fixture judge: argv [python, judge.py, scenario.json, counter, {verdict}, {frames_dir}].
# The scenario is a list of what to emit per invocation: a verdict object, the string
# "malformed" (not JSON), "stdout:<json>" (printed, no file), "touch-frame" (writes into the
# frames it may only read, then a good verdict), "touch-guard:<path>" or "exit:<n>".
JUDGE = r'''
import json, os, sys
scenario, counter, verdict, frames = sys.argv[1:5]
n = int(open(counter).read()) if os.path.exists(counter) else 0
open(counter, "w").write(str(n + 1))
plan = json.load(open(scenario))
entry = plan[min(n, len(plan) - 1)]
assert os.path.isfile(os.environ["WGF_VISUALQA_BRIEF"])
if isinstance(entry, str) and entry.startswith("exit:"):
    sys.exit(int(entry[5:]))
if entry == "malformed":
    open(verdict, "w").write("{not json")
    sys.exit(0)
if isinstance(entry, str) and entry.startswith("stdout:"):
    print("Here is my verdict.")
    print("```json\n" + entry[7:] + "\n```")
    sys.exit(0)
if isinstance(entry, str) and entry.startswith("touch-guard:"):
    open(entry[12:], "a").write("x")
    entry = plan[-1] if isinstance(plan[-1], dict) else {}
if entry == "touch-frame":
    for root, _, files in os.walk(frames):
        for name in files:
            open(os.path.join(root, name), "ab").write(b"x")
            break
    entry = plan[-1]
json.dump(entry, open(verdict, "w"))
'''


def scores(value=4, **overrides):
    out = {d: value for d in DIMENSIONS}
    out.update(overrides)
    return out


def finding(fid, severity, category, route, frame=None):
    return {"id": fid, "severity": severity, "category": category, "frame": frame,
            "summary": f"{fid} (fixture)", "route": route}


def png(path, shade):
    image = Image(16, 9, bytes([shade, shade, shade, 255]) * (16 * 9))
    with open(path, "wb") as handle:
        handle.write(encode_png(image))


def digest(path):
    with open(path, "rb") as handle:
        return "sha256:" + hashlib.sha256(handle.read()).hexdigest()


DESIGN = {"title_id": "demo", "build_spec": {
    "visual_identity": {"concept": "Floodlit night match", "shape_language": "chunky",
                        "motion": "snappy", "avoid": ["system fonts"],
                        "palette": [{"token": "pitch", "hex": "#1b5e20", "role": "ground"}],
                        "typography": {"display": "Bungee", "body": "Inter"}},
    "assets": [{"id": "keeper", "type": "model", "tier": "mvp", "count": 1,
                "description": "The goalkeeper", "source_preference": "library",
                "est_cost": 0, "role": "player",
                "readability": "a goalkeeper in gloves, readable at 60 px tall"}]}}
MANIFEST = {"items": [{"id": "keeper", "role": "player", "source": "procedural",
                       "placeholder": True, "quality": {"verdict": "fail",
                                                        "primitive_only": True}}]}


class Base(unittest.TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp(prefix="wgf-vqa-")
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)
        self.run_dir = os.path.join(self.base, "run")
        self.guard = os.path.join(self.base, "guarded")
        os.makedirs(self.guard)
        with open(os.path.join(self.guard, "rules.txt"), "w") as handle:
            handle.write("the judge's rules\n")
        frames = []
        for project in ("desktop", "mobile"):
            directory = os.path.join(self.run_dir, "playability", "1-1", "out", project,
                                     "frames")
            os.makedirs(directory)
            for index, name in enumerate(("first-session-1s", "play-2s", "end-lost")):
                path = os.path.join(directory, name + ".png")
                png(path, 40 + 60 * index)
                frames.append({"id": name, "project": project,
                               "path": os.path.relpath(path, self.run_dir), "sha256":
                               digest(path)})
        self.play = {"title_id": "demo", "commit": "c" * 40, "frames": frames, "verdict": "PASS",
                     "projects": [{"id": "desktop", "viewport": {"width": 1280, "height": 720}},
                                  {"id": "mobile", "viewport": {"width": 393, "height": 851}}]}
        self.judge = os.path.join(self.base, "judge.py")
        with open(self.judge, "w") as handle:
            handle.write(JUDGE)

    def config(self, plan, verdict_from="file", kind="command"):
        scenario = os.path.join(self.base, "scenario.json")
        with open(scenario, "w") as handle:
            json.dump(plan, handle)
        self.counter = os.path.join(self.base, "count")
        if os.path.exists(self.counter):
            os.remove(self.counter)
        return {"visualqa": {"judge": {
                    "kind": kind, "verdict_from": verdict_from, "timeout_seconds": 60,
                    "argv": [sys.executable, self.judge, scenario, self.counter, "{verdict}",
                             "{frames_dir}"] if kind == "command" else []}},
                "review": {"guarded_paths": [self.guard]}}

    def runs(self):
        with open(self.counter) as handle:
            return int(handle.read())

    def run_step(self, config, docs=None):
        if docs is None:
            docs = {"playability-report": self.play, "game-design": DESIGN,
                    "asset-manifest": MANIFEST}

        class Inputs:
            refs = {k: types.SimpleNamespace(content_hash=None) for k in docs}

            def __contains__(self, k):
                return k in docs

            def load(self, k):
                return docs[k]

        class Log:
            def __getattr__(self, name):
                return lambda *a, **k: None

        context = types.SimpleNamespace(config=config, run_dir=self.run_dir, logger=Log(),
                                        visit=1, attempt=1, execution=1)
        return VisualQAStep(types.SimpleNamespace(params={}, id="visual-qa")).execute(
            Inputs(), context)

    def report(self, result):
        self.assertEqual(len(result.artifacts), 1)
        content = result.artifacts[0].content
        self.assertEqual(ArtifactContracts()("visual-qa-report", content), [])
        return content


class TheVerdicts(Base):
    def test_a_finished_game_passes(self):
        result = self.run_step(self.config([{"scores": scores(4), "findings": [
            finding("hud-tight", "minor", "composition", "develop", "mobile/play-2s")]}]))
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
        report = self.report(result)
        self.assertEqual(report["verdict"], "PASS")
        self.assertEqual(report["failed"], [])
        self.assertEqual(report["routes"], [])
        self.assertEqual(report["judge_runs"], 1)
        self.assertEqual(report["measurement_class"], "automation-agent")
        self.assertEqual(len(report["frames"]), 6)
        self.assertEqual(report["frames"][0]["id"], "desktop/first-session-1s")
        self.assertEqual(report["frames"][0]["state"], "boot")
        self.assertEqual(report["rubric"]["sha256"], RUBRIC["sha256"])

    def test_a_primitive_character_is_a_blocker_routed_to_assets(self):
        result = self.run_step(self.config([{"scores": scores(4, art_completeness=1), "findings": [
            finding("primitive-keeper", "blocker", "assets", "assets", "desktop/play-2s"),
            finding("default-buttons", "blocker", "ui", "develop", "mobile/end-lost")]}]))
        self.assertEqual(result.outcome, StepOutcome.FAILED)
        self.assertFalse(result.retryable)
        self.assertEqual(result.route, "assets")
        report = self.report(result)
        self.assertEqual(report["verdict"], "FAIL")
        self.assertEqual(report["routes"], ["assets", "develop"])
        self.assertIn("finding:primitive-keeper", report["failed"])
        self.assertIn("score:art_completeness", report["failed"])

    def test_debug_output_is_a_blocker_routed_to_develop(self):
        result = self.run_step(self.config([{"scores": scores(4), "findings": [
            finding("fps-panel", "blocker", "debug", "develop", "desktop/play-2s"),
            finding("muddy-floor", "major", "assets", "assets")]}]))
        self.assertEqual(result.outcome, StepOutcome.FAILED)
        self.assertEqual(result.route, "develop")
        self.assertEqual(self.report(result)["routes"], ["develop"])

    def test_a_dimension_below_the_bar_fails_by_its_route(self):
        result = self.run_step(self.config([{"scores": scores(4, typography=2), "findings": []}]))
        self.assertEqual(result.outcome, StepOutcome.FAILED)
        self.assertEqual(result.route, "develop")
        self.assertEqual(self.report(result)["failed"], ["score:typography"])

    def test_the_brief_lists_frames_identity_assets_and_rubric(self):
        self.run_step(self.config([{"scores": scores(4), "findings": []}]))
        brief_path = os.path.join(self.run_dir, "visual-qa", "visual-qa-1-1",
                                  "visual-qa-1.brief.md")
        with open(brief_path) as handle:
            brief = handle.read()
        for needle in ("`desktop/play-2s`", "mobile 393x851", "Floodlit night match",
                       "primitive_style: NO", "a goalkeeper in gloves", "PLACEHOLDER",
                       "`no_debug`", "`primitive-entity`", "`browser-default-ui`"):
            self.assertIn(needle, brief)

    def test_a_verdict_on_stdout(self):
        good = json.dumps({"scores": scores(5), "findings": []})
        result = self.run_step(self.config(["stdout:" + good], verdict_from="stdout"))
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)


class TheFailures(Base):
    def test_a_malformed_verdict_is_retried_once_then_fails(self):
        result = self.run_step(self.config(["malformed"]))
        self.assertEqual(result.outcome, StepOutcome.FAILED)
        self.assertFalse(result.retryable)
        self.assertIn("malformed-verdict", result.error)
        self.assertEqual(self.runs(), 2)
        second = os.path.join(self.run_dir, "visual-qa", "visual-qa-1-1",
                              "visual-qa-2.brief.md")
        with open(second) as handle:
            self.assertIn("Your previous verdict was rejected", handle.read())

    def test_a_malformed_verdict_fixed_on_the_retry(self):
        result = self.run_step(self.config([
            "malformed", {"scores": scores(4), "findings": []}]))
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
        self.assertEqual(self.report(result)["judge_runs"], 2)

    def test_a_verdict_naming_an_unknown_frame_is_malformed(self):
        result = self.run_step(self.config([{"scores": scores(4), "findings": [
            finding("x", "minor", "ui", "develop", "desktop/play-2s.png")]}]))
        self.assertEqual(result.outcome, StepOutcome.FAILED)
        self.assertIn("is not a frame you were given", result.error)

    def test_no_judge_blocks_and_is_never_a_pass(self):
        result = self.run_step(self.config([], kind="none"))
        self.assertEqual(result.outcome, StepOutcome.BLOCKED)
        self.assertIn("visual QA needs a judge", result.message)
        report = self.report(result)
        self.assertEqual(report["verdict"], "BLOCKED")
        self.assertEqual(report["judge_runs"], 0)

    def test_a_judge_that_exits_non_zero_is_retryable(self):
        result = self.run_step(self.config(["exit:3"]))
        self.assertEqual(result.outcome, StepOutcome.FAILED)
        self.assertTrue(result.retryable)

    def test_a_frame_changed_since_playability_fails(self):
        path = os.path.join(self.run_dir, self.play["frames"][0]["path"])
        with open(path, "ab") as handle:
            handle.write(b"tampered")
        result = self.run_step(self.config([{"scores": scores(4), "findings": []}]))
        self.assertEqual(result.outcome, StepOutcome.FAILED)
        self.assertIn("not the frame the playability step recorded", result.error)

    def test_a_missing_frame_blocks(self):
        os.remove(os.path.join(self.run_dir, self.play["frames"][0]["path"]))
        result = self.run_step(self.config([{"scores": scores(4), "findings": []}]))
        self.assertEqual(result.outcome, StepOutcome.BLOCKED)

    def test_a_judge_that_writes_to_a_frame_fails(self):
        result = self.run_step(self.config(["touch-frame", {"scores": scores(5),
                                                            "findings": []}]))
        self.assertEqual(result.outcome, StepOutcome.FAILED)
        self.assertIn("judge-isolation-violation", result.error)

    def test_a_judge_that_writes_to_a_guarded_path_fails_and_is_undone(self):
        guarded = os.path.join(self.guard, "rules.txt")
        result = self.run_step(self.config(["touch-guard:" + guarded,
                                            {"scores": scores(5), "findings": []}]))
        self.assertEqual(result.outcome, StepOutcome.FAILED)
        self.assertIn("judge-isolation-violation", result.error)
        with open(guarded) as handle:
            self.assertEqual(handle.read(), "the judge's rules\n")

    def test_missing_inputs_wait(self):
        result = self.run_step(self.config([]), docs={"game-design": DESIGN})
        self.assertEqual(result.outcome, StepOutcome.WAITING_FOR_INPUT)


class TheRubric(unittest.TestCase):
    def test_the_rubric_has_its_dimensions_and_blocker_rules(self):
        for name in ("art_completeness", "character_readability", "environment", "ui_polish",
                     "typography", "composition", "consistency", "no_debug"):
            self.assertIn(name, RUBRIC["dimensions"])
        rules = {r["id"]: r for r in RUBRIC["blockers"]}
        self.assertEqual(rules["primitive-entity"]["route"], "assets")
        self.assertEqual(rules["browser-default-ui"]["route"], "develop")
        self.assertEqual(rules["debug-output"]["route"], "develop")

    def test_scores_out_of_range_or_missing_are_malformed(self):
        keys = ["desktop/play-2s"]
        self.assertIsNone(rubric_mod.parse({"scores": scores(6), "findings": []}, RUBRIC,
                                           keys)[0])
        partial = scores(4)
        partial.pop("no_debug")
        self.assertIn("missing no_debug",
                      rubric_mod.parse({"scores": partial, "findings": []}, RUBRIC, keys)[1])
        self.assertIn("keys the contract does not", rubric_mod.parse(
            {"scores": scores(4), "findings": [], "verdict": "PASS"}, RUBRIC, keys)[1])

    def test_frame_states(self):
        self.assertEqual(frame_state("act-dive-after")[0], "playing")
        self.assertIn("after the player's `dive`", frame_state("act-dive-after")[1])
        self.assertEqual(frame_state("end-won")[0], "won")


class TheMock(unittest.TestCase):
    def run_mock(self, entry):
        from wgflib.workflow import api  # noqa: F401  (registers nothing; import check)

        class Inputs:
            refs = {}
            missing = []

            def __contains__(self, k):
                return False

        class Log:
            def __getattr__(self, name):
                return lambda *a, **k: None

        context = types.SimpleNamespace(environment={"mock_plan": {"visual-qa": [entry]}},
                                        execution=1, project_id=None, logger=Log())
        step = mock.MockVisualQAStep(types.SimpleNamespace(
            params={}, id="visual-qa", outputs=["visual-qa-report"]))
        return step.execute(Inputs(), context)

    def test_mock_pass_and_routed_failures(self):
        passed = self.run_mock("success")
        self.assertEqual(passed.outcome, StepOutcome.SUCCESS)
        content = passed.artifacts[0].content
        self.assertEqual(ArtifactContracts()("visual-qa-report", content), [])
        for entry, route in (("assets", "assets"), ("develop", "develop"), ("fail", "develop")):
            result = self.run_mock(entry)
            self.assertEqual(result.outcome, StepOutcome.FAILED, entry)
            self.assertEqual(result.route, route)
            body = result.artifacts[0].content
            self.assertEqual(body["verdict"], "FAIL")
            self.assertEqual(ArtifactContracts()("visual-qa-report", body), [])


class TheHarness(Base):
    def test_the_cli_runs_the_judge_over_a_frames_directory(self):
        config = self.config([{"scores": scores(4), "findings": [
            finding("primitive-keeper", "blocker", "assets", "assets", "desktop/play-2s")]}])
        judge = config["visualqa"]["judge"]
        out = os.path.join(self.base, "out")
        frames = os.path.join(self.run_dir, "playability", "1-1", "out")
        result = subprocess.run(
            [sys.executable, os.path.join(SCRIPTS, "wgf-visualqa.py"),
             "--frames", os.path.join(frames, "desktop", "frames"),
             "--frames", "mobile=" + os.path.join(frames, "mobile", "frames"),
             "--judge-argv", json.dumps(judge["argv"]), "--out", out, "--json",
             "--config", os.path.join(self.base, "none.yaml")],
            capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 1, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data["verdict"], "FAIL")
        self.assertEqual(data["route"], "assets")
        self.assertTrue(os.path.isfile(os.path.join(out, "frames", "mobile", "play-2s.png")))


if __name__ == "__main__":
    unittest.main()

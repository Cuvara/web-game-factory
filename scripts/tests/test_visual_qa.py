"""The visual-qa step (scripts/wgf_visualqa): a vision judge reads the production build's frames.

The judge here is a fixture command - a Python script that writes the verdict a scenario
names - so every path the step takes is exercised without an agent host: a pass, a blocker
routed to assets, a blocker routed to develop, a dimension below the bar, a per-state
answer and a developer-prototype look (the lead's per-state questions), a malformed
verdict sent back in repair rounds and then a fresh attempt before it fails, a verdict
missing an answer fixed in a repair round, trivially fixable shapes coerced and recorded,
a malformed verdict fixed on the retry, a verdict on
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
from unittest import mock as patching  # noqa: E402
from wgflib.workflow import mock  # noqa: E402
from wgflib.workflow import references  # noqa: E402
from wgflib.workflow.contracts import ArtifactContracts  # noqa: E402
from wgflib.workflow.model import StepOutcome  # noqa: E402

RUBRIC = rubric_mod.load_rubric()
PINNED = "core/reference/visual-qa-rubric.yaml"
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


# The frames Base stages: their (state, viewport) pairs, as the verdict must answer them.
PAIRS = [(state, viewport) for state in ("initial", "gameplay", "loss")
         for viewport in ("desktop", "mobile")]


def answers(state, **overrides):
    out = {q["id"]: not q["fail_when"] for q in rubric_mod.questions_for(RUBRIC, state)}
    out.update(overrides)
    return out


def complete(verdict, look="finished-game"):
    verdict = dict(verdict)
    if "states" not in verdict:
        verdict["states"] = [{"state": s, "viewport": v, "answers": answers(s),
                              "comment": "fixture"} for s, v in PAIRS]
    verdict.setdefault("look", look)
    verdict.setdefault("look_reason", "fixture")
    return verdict


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

    def config(self, plan, verdict_from="file", kind="command", **judge):
        """A verdict object in `plan` without `states` gets every judged (state, viewport)
        answered the passing way, and look finished-game."""
        plan = [complete(entry) if isinstance(entry, dict) else entry for entry in plan]
        scenario = os.path.join(self.base, "scenario.json")
        with open(scenario, "w") as handle:
            json.dump(plan, handle)
        self.counter = os.path.join(self.base, "count")
        if os.path.exists(self.counter):
            os.remove(self.counter)
        return {"visualqa": {"judge": {
                    "kind": kind, "verdict_from": verdict_from, "timeout_seconds": 60,
                    "argv": [sys.executable, self.judge, scenario, self.counter, "{verdict}",
                             "{frames_dir}"] if kind == "command" else [], **judge}},
                "review": {"guarded_paths": [self.guard]}}

    def runs(self):
        with open(self.counter) as handle:
            return int(handle.read())

    def run_step(self, config, docs=None, environment=None):
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
                                        visit=1, attempt=1, execution=1,
                                        environment=environment or {})
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
        self.assertEqual(report["frames"][0]["state"], "initial")
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
                       "| loss | mobile | `mobile/end-lost` |", "No frame shows: interaction, win, retry",
                       "`outcome_understandable` (win, loss, retry only)", "developer-prototype",
                       "<true | false | null>", "<number 0-5>",
                       "`no_debug`", "`primitive-entity`", "`browser-default-ui`"):
            self.assertIn(needle, brief)

    def test_a_developer_prototype_look_fails(self):
        result = self.run_step(self.config([complete({"scores": scores(4), "findings": []},
                                                     look="developer-prototype")]))
        self.assertEqual(result.outcome, StepOutcome.FAILED)
        self.assertEqual(result.route, "assets")
        report = self.report(result)
        self.assertEqual(report["failed"], ["look:developer-prototype"])
        self.assertEqual(report["look"]["verdict"], "developer-prototype")

    def test_a_per_state_answer_fails_by_its_route(self):
        verdict = complete({"scores": scores(4), "findings": []})
        verdict["states"][1]["answers"]["buttons_polished"] = False   # mobile initial
        result = self.run_step(self.config([verdict]))
        self.assertEqual(result.outcome, StepOutcome.FAILED)
        self.assertEqual(result.route, "develop")
        report = self.report(result)
        self.assertEqual(report["failed"], ["state:mobile/initial:buttons_polished"])
        states = {(e["state"], e["viewport"]): e for e in report["states"]}
        self.assertEqual(len(report["states"]), 12)   # 6 rubric states x 2 viewports
        self.assertFalse(states[("retry", "desktop")]["captured"])
        self.assertEqual(states[("retry", "desktop")]["answers"], {})
        self.assertEqual(states[("loss", "mobile")]["frames"], ["mobile/end-lost"])

    def test_the_judges_reasons_for_its_scores_reach_the_report(self):
        reasons = {"environment": "a flat black void above the horizon"}
        result = self.run_step(self.config([{"scores": scores(4, environment=1),
                                             "score_reasons": reasons, "findings": []}]))
        self.assertEqual(result.outcome, StepOutcome.FAILED)
        report = self.report(result)
        self.assertEqual(report["score_reasons"], reasons)
        brief_path = os.path.join(self.run_dir, "visual-qa", "visual-qa-1-1",
                                  "visual-qa-1.brief.md")
        with open(brief_path) as handle:
            brief = handle.read()
        self.assertIn("`score_reasons` gives, for every dimension", brief)
        self.assertIn('"score_reasons"', brief)
        # A verdict without reasons is still well formed, and its report has none.
        result = self.run_step(self.config([{"scores": scores(4), "findings": []}]))
        self.assertNotIn("score_reasons", self.report(result))

    def test_a_verdict_on_stdout(self):
        good = json.dumps(complete({"scores": scores(5), "findings": []}))
        result = self.run_step(self.config(["stdout:" + good], verdict_from="stdout"))
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)


class ThePinnedRubric(Base):
    """WS-13 gap: visual-qa read the live rubric, not the copy new-game pins when the run
    starts, so a bar lowered mid-run reached the running build. It reads the pinned copy."""

    def pin(self, text=None):
        """Pin the shipped rubric in the run directory, as the engine does at the start;
        the environment that records it."""
        with open(rubric_mod.RUBRIC_PATH, "rb") as handle:
            shipped = handle.read()
        target = os.path.join(self.run_dir, references.DIRECTORY, *PINNED.split("/"))
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "wb") as handle:
            handle.write(shipped if text is None else text.encode("utf-8"))
        return {references.PARAM: {PINNED: references.digest(shipped)}}, target

    def lowered_live(self):
        """The live rubric with its pass bar lowered after the run started."""
        with open(rubric_mod.RUBRIC_PATH, encoding="utf-8") as handle:
            text = handle.read()
        edited = text.replace("\npass_bar: 3\n", "\npass_bar: 1\n")
        self.assertNotEqual(edited, text)
        path = os.path.join(self.base, "live-rubric.yaml")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(edited)
        return path

    def test_a_bar_lowered_mid_run_does_not_reach_the_running_build(self):
        environment, _target = self.pin()
        config = self.config([{"scores": scores(4, typography=2), "findings": []}])
        with patching.patch.object(rubric_mod, "RUBRIC_PATH", self.lowered_live()):
            held = self.run_step(config, environment=environment)
            unpinned = self.run_step(self.config([{"scores": scores(4, typography=2),
                                                   "findings": []}]))
        self.assertEqual(held.outcome, StepOutcome.FAILED)
        report = self.report(held)
        self.assertIn("score:typography", report["failed"])
        self.assertEqual((report["rubric"]["pass_bar"], report["rubric"]["sha256"]),
                         (3, RUBRIC["sha256"]))
        # A run that pinned nothing reads the live file - and is held to the edit.
        self.assertEqual(self.report(unpinned)["rubric"]["pass_bar"], 1)

    def test_a_pinned_rubric_edited_in_the_run_blocks(self):
        environment, target = self.pin()
        with open(target, "a", encoding="utf-8") as handle:
            handle.write("\n# lowered in the run\n")
        result = self.run_step(self.config([{"scores": scores(4), "findings": []}]),
                               environment=environment)
        self.assertEqual(result.outcome, StepOutcome.BLOCKED)
        self.assertIn("edited after the start", result.message)

    def test_a_configured_rubric_is_read_as_configured(self):
        environment, _target = self.pin()
        config = self.config([{"scores": scores(4, typography=2), "findings": []}])
        config["visualqa"]["rubric"] = self.lowered_live()
        result = self.run_step(config, environment=environment)
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)


class TheFailures(Base):
    def brief(self, run):
        with open(os.path.join(self.run_dir, "visual-qa", "visual-qa-1-1",
                               f"visual-qa-{run}.brief.md")) as handle:
            return handle.read()

    def test_a_malformed_verdict_is_repaired_then_retried_then_fails(self):
        # Two repair rounds (the default), then the second fresh attempt; then it fails.
        result = self.run_step(self.config(["malformed"]))
        self.assertEqual(result.outcome, StepOutcome.FAILED)
        self.assertFalse(result.retryable)
        self.assertIn("malformed-verdict", result.error)
        self.assertIn("2 fresh attempt(s) and 2 repair round(s)", result.error)
        self.assertIn("verdict file is not JSON", result.error)
        self.assertEqual(self.runs(), 4)
        for run in (2, 3):
            brief = self.brief(run)
            self.assertIn("Repair your previous verdict", brief)
            self.assertIn("{not json", brief)
            self.assertIn("verdict file is not JSON", brief)
        self.assertIn("Your previous verdict was rejected", self.brief(4))
        self.assertNotIn("Repair your previous verdict", self.brief(4))

    def test_no_repair_rounds_is_two_fresh_attempts(self):
        result = self.run_step(self.config(["malformed"], repair_rounds=0))
        self.assertEqual(result.outcome, StepOutcome.FAILED)
        self.assertIn("malformed-verdict", result.error)
        self.assertEqual(self.runs(), 2)
        self.assertIn("Your previous verdict was rejected", self.brief(2))

    def test_a_malformed_verdict_fixed_on_the_retry(self):
        result = self.run_step(self.config([
            "malformed", {"scores": scores(4), "findings": []}]))
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
        report = self.report(result)
        self.assertEqual(report["judge_runs"], 2)
        self.assertEqual(report["judge_repairs"], 1)

    def omitted(self, qid="buttons_polished", index=1):
        """A complete verdict with one answer left out, as the live judge did."""
        verdict = complete({"scores": scores(4), "findings": []})
        del verdict["states"][index]["answers"][qid]
        return verdict

    def test_an_omitted_answer_is_repaired_never_invented(self):
        result = self.run_step(self.config([self.omitted(),
                                            {"scores": scores(4), "findings": []}]))
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
        report = self.report(result)
        self.assertEqual((report["judge_runs"], report["judge_repairs"]), (2, 1))
        self.assertEqual(report["coercions"], [])
        brief = self.brief(2)
        self.assertIn("Repair your previous verdict", brief)
        self.assertIn("states[1].answers must answer exactly", brief)
        self.assertIn("(missing buttons_polished)", brief)
        # The judge's own reply is quoted back to it, verbatim.
        self.assertIn('"primitives_or_placeholders"', brief.split("## The frames")[0])
        # The whole brief follows: the shape and the questions are there to answer from.
        self.assertIn("## Your verdict", brief)

    def test_a_judge_that_never_repairs_fails_with_the_errors(self):
        result = self.run_step(self.config([self.omitted()]))
        self.assertEqual(result.outcome, StepOutcome.FAILED)
        self.assertFalse(result.retryable)
        self.assertIn("malformed-verdict", result.error)
        self.assertIn("states[1].answers must answer exactly", result.error)
        self.assertIn("(missing buttons_polished)", result.error)
        self.assertEqual(self.runs(), 4)
        self.assertEqual(result.artifacts, [])

    def test_a_one_item_list_reason_is_coerced_and_recorded(self):
        verdict = complete({"scores": scores(4), "findings": [], "score_reasons": {
            "character_readability": ["the keeper reads at a glance"],
            "environment": "a lit arena"}})
        result = self.run_step(self.config([verdict]))
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
        report = self.report(result)
        self.assertEqual(report["judge_runs"], 1)
        self.assertEqual(report["judge_repairs"], 0)
        self.assertEqual(report["score_reasons"]["character_readability"],
                         "the keeper reads at a glance")
        self.assertEqual(report["coercions"], [{
            "path": "score_reasons.character_readability", "rule": "unwrap-one-item-list",
            "from": ["the keeper reads at a glance"], "to": "the keeper reads at a glance"}])

    def test_every_error_reaches_the_repair_round_at_once(self):
        verdict = self.omitted()
        verdict["score_reasons"] = {"environment": 3}
        verdict["look"] = "pretty"
        result = self.run_step(self.config([verdict, {"scores": scores(4), "findings": []}]))
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
        brief = self.brief(2)
        for fragment in ("score_reasons.environment must be a string",
                         "states[1].answers must answer exactly", "look must be one of"):
            self.assertIn("- " + fragment, brief)

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

    FRAMES = [{"key": f"{v}/x-{s}", "state": s, "project": v} for s, v in PAIRS]

    def parse(self, verdict):
        return rubric_mod.parse(verdict, RUBRIC, self.FRAMES)

    def test_scores_out_of_range_or_missing_are_malformed(self):
        self.assertIsNone(self.parse(complete({"scores": scores(6), "findings": []}))[0])
        partial = scores(4)
        partial.pop("no_debug")
        self.assertIn("missing no_debug",
                      self.parse(complete({"scores": partial, "findings": []}))[1])
        self.assertIn("keys the contract does not", self.parse(
            complete({"scores": scores(4), "findings": [], "verdict": "PASS"}))[1])
        self.assertIsNone(self.parse(complete({"scores": scores(4), "findings": []}))[1])

    def test_score_reasons_are_optional_and_checked(self):
        verdict = complete({"scores": scores(4), "findings": [],
                            "score_reasons": {"environment": "a void"}})
        self.assertIsNone(self.parse(verdict)[1])
        verdict["score_reasons"] = {"vibes": "nice"}
        self.assertIn("dimensions the rubric does not", self.parse(verdict)[1])
        verdict["score_reasons"] = {"environment": 3}
        self.assertIn("must be a string", self.parse(verdict)[1])

    def test_assets_failures_name_the_roles_they_remake(self):
        # What the assets step remakes on re-entry is data (rebuild_roles, rebuild.groups).
        dims = RUBRIC["dimensions"]
        self.assertEqual(rubric_mod.expand_roles(RUBRIC, dims["environment"]["rebuild_roles"]),
                         ["environment", "background", "prop"])
        entities = rubric_mod.expand_roles(RUBRIC, ["entities"])
        self.assertIn("player", entities)
        self.assertIn("threat", entities)
        art = rubric_mod.expand_roles(RUBRIC, RUBRIC["look"]["rebuild_roles"])
        self.assertTrue(set(entities) < set(art))
        self.assertNotIn("ui", art)
        for name, dimension in dims.items():
            if dimension["route"] == "assets":
                self.assertTrue(dimension.get("rebuild_roles"), name)
        for question in RUBRIC["state_questions"]:
            if question["route"] == "assets":
                self.assertTrue(question.get("rebuild_roles"), question["id"])
        self.assertIn("player", RUBRIC["rebuild"]["role_words"])
        broken = dict(RUBRIC, rebuild={"groups": {"x": "player"}})
        self.assertIn("rebuild.groups", rubric_mod._check_rebuild(broken))

    def test_every_state_must_be_answered_and_only_those(self):
        verdict = complete({"scores": scores(4), "findings": []})
        verdict["states"].pop()
        self.assertIn("states is missing mobile/loss", self.parse(verdict)[1])
        verdict = complete({"scores": scores(4), "findings": []})
        verdict["states"].append({"state": "win", "viewport": "desktop",
                                  "answers": answers("win")})
        self.assertIn("which no frame shows", self.parse(verdict)[1])
        verdict = complete({"scores": scores(4), "findings": []})
        verdict["states"][0]["answers"]["buttons_polished"] = "yes"
        self.assertIn("must be true, false or null", self.parse(verdict)[1])
        verdict = complete({"scores": scores(4), "findings": []})
        del verdict["states"][2]["answers"]["objective_obvious"]
        self.assertIn("must answer exactly", self.parse(verdict)[1])
        self.assertIn("look must be one of", self.parse(
            complete({"scores": scores(4), "findings": []}, look="pretty"))[1])

    def test_primitive_style_waives_the_primitive_answer_only(self):
        verdict = complete({"scores": scores(4), "findings": []})
        verdict["states"][0]["answers"]["primitives_or_placeholders"] = True
        verdict["states"][0]["answers"]["buttons_polished"] = False
        status, failed, routes = rubric_mod.decide(verdict, RUBRIC, primitive_style=True)
        self.assertEqual(failed, ["state:desktop/initial:buttons_polished"])
        status, failed, routes = rubric_mod.decide(verdict, RUBRIC)
        self.assertEqual(routes, ["assets", "develop"])

    def test_coercion_never_changes_meaning_or_invents(self):
        verdict = complete({"scores": scores(4), "findings": [
            finding("x", " Blocker", "ASSETS", "assets ", "desktop/x-initial ")]})
        verdict["look"] = "Finished-Game"
        answers0 = verdict["states"][0]["answers"]
        answers0["Entities_Recognisable"] = answers0.pop("entities_recognisable")
        verdict["score_reasons"] = {"Environment": "a lit arena"}
        coerced, coercions = rubric_mod.coerce(verdict, RUBRIC, self.FRAMES)
        self.assertIsNone(self.parse(coerced)[1])
        self.assertEqual(coerced["findings"][0]["severity"], "blocker")
        self.assertEqual(coerced["findings"][0]["frame"], "desktop/x-initial")
        self.assertEqual(coerced["look"], "finished-game")
        self.assertIn("entities_recognisable", coerced["states"][0]["answers"])
        self.assertEqual({c["rule"] for c in coercions},
                         {"strip-whitespace", "enum-case", "key-case"})
        self.assertEqual(len(coercions), 7)
        # The input is not modified; the coercion works on a copy.
        self.assertEqual(verdict["look"], "Finished-Game")
        # What would need a guess is never coerced: a missing answer, a score or a boolean
        # written as a string, a two-item list, an unknown key.
        for breaks, fragment in (
                (lambda v: v["states"][0]["answers"].pop("buttons_polished"),
                 "must answer exactly"),
                (lambda v: v["scores"].update(environment="3"), "must be a number 0..5"),
                (lambda v: v["states"][0]["answers"].update(buttons_polished="yes"),
                 "must be true, false or null"),
                (lambda v: v.update(score_reasons={"environment": ["a", "b"]}),
                 "must be a string"),
                (lambda v: v["scores"].update(vibes=4), "dimensions the rubric does not")):
            broken = complete({"scores": scores(4), "findings": []})
            breaks(broken)
            coerced, coercions = rubric_mod.coerce(broken, RUBRIC, self.FRAMES)
            self.assertEqual(coercions, [])
            self.assertIn(fragment, self.parse(coerced)[1])

    def test_the_required_questions_are_unchanged(self):
        # Repair and coercion never relax what is asked: every state answers the same
        # questions it did before, and a verdict missing any of them is malformed.
        asked = {s: [q["id"] for q in rubric_mod.questions_for(RUBRIC, s)]
                 for s in rubric_mod.state_ids(RUBRIC)}
        self.assertEqual(asked["retry"], [
            "entities_recognisable", "primitives_or_placeholders",
            "lighting_materials_coherent", "typography_readable", "buttons_polished",
            "outcome_understandable"])
        for index, (state, _viewport) in enumerate(PAIRS):
            for qid in asked[state]:
                verdict = complete({"scores": scores(4), "findings": []})
                del verdict["states"][index]["answers"][qid]
                coerced, _ = rubric_mod.coerce(verdict, RUBRIC, self.FRAMES)
                self.assertIn(f"(missing {qid})", self.parse(coerced)[1])

    def test_repair_rounds_are_configured(self):
        from wgf_visualqa.settings import Settings, SettingsError
        self.assertEqual(Settings.resolve({}).repair_rounds, 2)
        self.assertEqual(Settings.resolve(
            {"visualqa": {"judge": {"repair_rounds": 0}}}).repair_rounds, 0)
        for bad in (-1, "2", True, 11):
            with self.assertRaises(SettingsError):
                Settings.resolve({"visualqa": {"judge": {"repair_rounds": bad}}})

    def test_frame_states(self):
        self.assertEqual(frame_state("act-dive-after")[0], "interaction")
        self.assertIn("after the player's `dive`", frame_state("act-dive-after")[1])
        self.assertEqual(frame_state("end-won")[0], "win")
        self.assertEqual(frame_state("first-session-idle-end")[0], "initial")


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


def rich(path, seed=0, shift=0, size=(64, 36)):
    """A finished-looking frame: bands of saturated colour, edges and texture, shifted by
    `shift` pixels (two plays of one game differ by where things are)."""
    width, height = size
    pixels = bytearray()
    for y in range(height):
        for x in range(width):
            band = ((x + shift) // 8 + y // 9 + seed) % 4
            r, g, b = ((240, 70, 170), (20, 120, 190), (250, 210, 60), (40, 30, 25))[band]
            if (x + y) % 5 == 0:
                r, g, b = r // 2, g // 2, b // 2
            pixels += bytes([r, g, b, 255])
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(encode_png(Image(width, height, pixels)))


class BaselineJudge(Base):
    """kind: baseline - each frame against the approved frame of its state, no agent."""

    def approve(self, states=("title", "gameplay", "game-over"), mapping=None):
        directory = os.path.join(self.base, "baseline")
        for viewport in ("desktop", "mobile"):
            for index, name in enumerate(states):
                rich(os.path.join(directory, viewport, f"{name}.png"), seed=index)
        if mapping is not None:
            with open(os.path.join(directory, "states.json"), "w") as handle:
                json.dump(mapping, handle)
        return directory

    def frames_like(self, shift=0):
        """Replace the solid fixture frames with the approved look (shifted), re-recording
        their sha256 as the playability step would."""
        seeds = {"first-session-1s": 0, "play-2s": 1, "end-lost": 2}
        for frame in self.play["frames"]:
            path = os.path.join(self.run_dir, frame["path"])
            rich(path, seed=seeds[frame["id"]], shift=shift)
            frame["sha256"] = digest(path)

    def config(self, directory, **judge):
        return {"visualqa": {"judge": {"kind": "baseline", "baseline_dir": directory, **judge}},
                "review": {"guarded_paths": [self.guard]}}

    def test_frames_that_look_like_the_approved_ones_pass(self):
        directory = self.approve()
        self.frames_like(shift=3)
        result = self.run_step(self.config(directory))
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
        report = self.report(result)
        self.assertEqual(report["verdict"], "PASS")
        self.assertEqual(report["judge"]["kind"], "baseline")
        self.assertEqual(report["look"]["verdict"], "finished-game")
        self.assertIn("not an aesthetic judgement", report["notes"])
        with open(os.path.join(self.run_dir, "visual-qa", "visual-qa-1-1", "baseline.json")) as handle:
            compared = json.load(handle)["comparisons"]
        self.assertEqual(len(compared), 6)
        self.assertTrue(all(c["passed"] and c["score"] >= 0.7 for c in compared), compared)

    def test_a_regression_to_primitives_fails_routed_to_assets(self):
        # The fixture's own frames: one flat grey each - what a build without its art draws.
        directory = self.approve()
        result = self.run_step(self.config(directory))
        self.assertEqual(result.outcome, StepOutcome.FAILED)
        self.assertEqual(result.route, "assets")
        report = self.report(result)
        self.assertEqual(report["verdict"], "FAIL")
        self.assertEqual(report["look"]["verdict"], "developer-prototype")
        blockers = [f for f in report["findings"] if f["severity"] == "blocker"]
        self.assertEqual(len(blockers), 6)
        self.assertTrue(all(f["route"] == "assets" and f["frame"] for f in blockers))
        self.assertIn("finding:baseline-regression-desktop-play-2s", report["failed"])
        gameplay = next(e for e in report["states"]
                        if (e["state"], e["viewport"]) == ("gameplay", "desktop"))
        self.assertEqual(gameplay["answers"]["primitives_or_placeholders"], True)
        self.assertEqual(gameplay["answers"]["entities_recognisable"], False)

    def test_unmatched_states_are_reported_not_passed_or_failed(self):
        # No approved loss screen; an approved retry no frame shows; a pause screen is an
        # interaction, and a name states.json maps to null is not compared.
        directory = self.approve(states=("title", "gameplay", "retry-playing", "paused",
                                         "credits"), mapping={"credits": None})
        self.frames_like()
        result = self.run_step(self.config(directory))
        report = self.report(result)
        ids = {f["id"]: f for f in report["findings"]}
        self.assertEqual(ids["no-baseline-desktop-loss"]["severity"], "minor")
        self.assertEqual(ids["baseline-unseen-mobile-retry"]["severity"], "minor")
        self.assertEqual(ids["baseline-unseen-desktop-interaction"]["severity"], "minor")
        self.assertIn("desktop/credits.png", report["notes"])
        loss = next(e for e in report["states"] if (e["state"], e["viewport"]) == ("loss", "mobile"))
        self.assertIsNone(loss["answers"]["entities_recognisable"])
        # The frames that had an approved state matched; nothing unmatched failed the build.
        self.assertEqual(report["verdict"], "PASS", report["failed"])

    def test_a_bad_baseline_configuration_fails_the_step(self):
        for judge, needle in (({"baseline_dir": None}, "baseline_dir"),
                              ({"min_similarity": 2}, "min_similarity"),
                              ({"baseline_dir": os.path.join(self.base, "nowhere")},
                               "does not exist")):
            with self.subTest(judge=judge):
                config = self.config(os.path.join(self.base, "baseline"))
                self.approve()
                config["visualqa"]["judge"].update(judge)
                result = self.run_step(config)
                self.assertEqual(result.outcome, StepOutcome.FAILED)
                self.assertFalse(result.retryable)
                self.assertIn(needle, result.error)

    def test_the_measure_tolerates_a_shift_and_not_a_flat_frame(self):
        from wgf_assets.raster import decode_png
        from wgf_visualqa import baseline

        def sig(path):
            with open(path, "rb") as handle:
                return baseline.signature(decode_png(handle.read()))
        rich(os.path.join(self.base, "a.png"))
        rich(os.path.join(self.base, "b.png"), shift=5)
        png(os.path.join(self.base, "flat.png"), 200)
        same, _ = baseline.similarity(sig(os.path.join(self.base, "a.png")),
                                      sig(os.path.join(self.base, "a.png")))
        shifted, _ = baseline.similarity(sig(os.path.join(self.base, "a.png")),
                                         sig(os.path.join(self.base, "b.png")))
        flat, parts = baseline.similarity(sig(os.path.join(self.base, "a.png")),
                                          sig(os.path.join(self.base, "flat.png")))
        self.assertEqual(same, 1.0)
        self.assertGreaterEqual(shifted, baseline.MIN_SIMILARITY)
        self.assertLess(flat, baseline.MIN_SIMILARITY)
        self.assertLess(parts["palette"], 0.2)

    def test_the_bot_screen_frames_have_states(self):
        for frame_id, state in (("state-title", "initial"), ("state-playing", "gameplay"),
                                ("state-paused", "interaction"), ("state-won", "win"),
                                ("state-lost", "loss"), ("state-retry", "retry")):
            self.assertEqual(frame_state(frame_id)[0], state, frame_id)


if __name__ == "__main__":
    unittest.main()


class TheQualityBar(unittest.TestCase):
    """Rubric 1.2.0: the bar is a game a portal would feature, not one that merely works.
    Calibrated 2026-10-02: finished reference games scored means 3.63-4.13 and looked
    `finished-game` in 6 of 6 runs; a styled greybox scored 3.13."""

    def setUp(self):
        from wgf_visualqa.rubric import load_rubric
        self.rubric = load_rubric()

    def verdict(self, score, look="finished-game", **override):
        scores = {name: score for name in self.rubric["dimensions"]}
        scores.update(override)
        return {"scores": scores, "findings": [], "states": [], "look": look}

    def test_a_plain_game_fails_on_the_look(self):
        from wgf_visualqa.rubric import decide
        verdict, failed, routes = decide(self.verdict(4, look="unremarkable"), self.rubric)
        self.assertEqual(verdict, "FAIL")
        self.assertIn("look:unremarkable", failed)
        self.assertIn("assets", routes)

    def test_all_threes_pass_no_dimension_but_fail_the_mean(self):
        from wgf_visualqa.rubric import decide
        verdict, failed, routes = decide(self.verdict(3), self.rubric)
        self.assertEqual((verdict, failed), ("FAIL", ["mean:3.00"]))
        self.assertTrue(routes)

    def test_the_references_calibrated_scores_pass(self):
        from wgf_visualqa.rubric import decide
        # The lowest-mean reference run: one dimension at 2 does not fail it alone (bar 3
        # fails it - scored 3 here), the mean of 3.63 holds.
        verdict, failed, _ = decide(self.verdict(4, composition=3, typography=3,
                                                 ui_polish=3, no_debug=5), self.rubric)
        self.assertEqual((verdict, failed), ("PASS", []))

    def test_the_judge_brief_carries_the_quality_bar(self):
        from wgf_visualqa.brief import render_brief
        text = render_brief(title_id="t", commit="c" * 12, frames=[], rubric=self.rubric,
                            design={"engine": {"type": "threejs"}})
        self.assertIn("## The quality bar", text)
        self.assertIn("3d-desktop-3-play-later.png", text)
        self.assertNotIn("2d-desktop-1-title.png", text)
        self.assertIn("`unremarkable` or `developer-prototype` fails the build", text)

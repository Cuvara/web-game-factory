"""The level-design step (scripts/wgf_leveldesign): a level critic reads every sampled unit,
and the oracle's safe and greedy policies show whether an optional risk exists and pays.

The critic here is a fixture command - a Python script that writes the verdict a scenario
names - so every rubric outcome is exercised without an agent host: designed units pass, a
dimension below the bar, a blocker, a design gap, a mean below its bar, a dimension the
frames cannot show (unmeasured: not passed at the release tier, a warning below it), a
first unit scored on its previous one (coerced), a malformed verdict repaired, no judge
(BLOCKED at release, SKIPPED below), missing moments, a changed frame, a critic writing into
its frames. The `baseline` critic is measured on synthetic entity boxes and frames. The risk
record is held to core/reference/risk-reward.yaml for every policy outcome: greedy pays and
risks, pays without risk, risks without pay, no play.policy, too few attempts, a `lower`
metric, the probe's own measures. Then the wiring: playability's settings, triage, the
quality floor, the mock step and the workflow.

    python -m unittest scripts.tests.test_level_design
"""

import hashlib
import json
import os
import shutil
import sys
import tempfile
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
sys.path.insert(0, SCRIPTS)

from wgf_assets.raster import Image, encode_png  # noqa: E402
from wgf_leveldesign import baseline, risk  # noqa: E402
from wgf_leveldesign.rubric import load_risk_rules, load_rubric  # noqa: E402
from wgf_leveldesign.step import LevelDesignStep  # noqa: E402
from wgflib.workflow.contracts import ArtifactContracts  # noqa: E402
from wgflib.workflow.model import StepOutcome  # noqa: E402
from wgflib.yamllite import load_file  # noqa: E402

RUBRIC = load_rubric()
RULES = load_risk_rules()
DIMENSIONS = list(RUBRIC["dimensions"])
UNITS = ["w1-l1", "w1-l2", "w1-l3"]
MOMENTS = [m["id"] for m in RUBRIC["moments"]]
RELEASE = {"quality": {"tier": "release"}}
MVP = {"quality": {"tier": "mvp"}}

JUDGE = r'''
import json, os, sys
scenario, counter, verdict, frames = sys.argv[1:5]
n = int(open(counter).read()) if os.path.exists(counter) else 0
open(counter, "w").write(str(n + 1))
plan = json.load(open(scenario))
entry = plan[min(n, len(plan) - 1)]
assert os.path.isfile(os.environ["WGF_LEVELDESIGN_BRIEF"])
if entry == "malformed":
    open(verdict, "w").write("{not json")
    sys.exit(0)
if entry == "touch-frame":
    for root, _, files in os.walk(frames):
        for name in files:
            open(os.path.join(root, name), "ab").write(b"x")
            break
    entry = plan[-1]
json.dump(entry, open(verdict, "w"))
'''


def scores(value=4, first=False, **overrides):
    out = {d: value for d in DIMENSIONS}
    if first:
        out["distinct_from_previous"] = None
    out.update(overrides)
    return out


def verdict(per_unit=None, findings=(), value=4):
    per_unit = per_unit or {}
    return {"units": [{"unit_id": u, "scores": per_unit.get(u) or scores(value, first=i == 0),
                       "score_reasons": {"play_space": "fixture"}, "comment": "fixture"}
                      for i, u in enumerate(UNITS)],
            "findings": list(findings)}


def png(path, shade, stripe=None):
    pixels = bytearray([shade, shade, shade, 255]) * (32 * 18)
    if stripe is not None:
        for y in range(18):
            for x in range(stripe, min(stripe + 6, 32)):
                k = (y * 32 + x) * 4
                pixels[k:k + 3] = bytes([250, 30, 30])
    with open(path, "wb") as handle:
        handle.write(encode_png(Image(32, 18, bytes(pixels))))


def digest(path):
    with open(path, "rb") as handle:
        return "sha256:" + hashlib.sha256(handle.read()).hexdigest()


def attempt(unit, policy, reward, failed=False, metric="gems", outcome="won", falls=None):
    end = {metric: reward, "falls": 1 if failed and falls is None else (falls or 0)}
    return {"unit": unit, "policy": policy, "entered": True, "policy_set": True,
            "outcome": "lost" if failed and falls is None and outcome == "lost" else outcome,
            "duration_ms": 9000, "metrics_start": {metric: 0, "falls": 0},
            "metrics_end": end, "metrics_max": dict(end)}


def risk_record(pairs, measures=None, offered=("safe", "greedy")):
    """`pairs`: {unit: ([(safe reward, failed)], [(greedy reward, failed)])}."""
    attempts = []
    for unit, (safe, greedy) in pairs.items():
        attempts += [attempt(unit, "safe", r, f) for r, f in safe]
        attempts += [attempt(unit, "greedy", r, f) for r, f in greedy]
    return {"applies": True, "declared": True, "offered": list(offered),
            "measures": measures, "units": list(pairs), "policies": ["safe", "greedy"],
            "attempts": attempts}


PAYING = risk_record({"w1-l1": ([(3, False)] * 3, [(7, False), (8, True), (9, True)]),
                      "w1-l3": ([(2, False)] * 3, [(6, True), (6, False), (5, True)])})

DESIGN = {"title_id": "demo", "build_spec": {"content": {
    "quality_tier": "release",
    "units": [{"id": u, "index": i + 1, "objective": f"Clear level {i + 1}",
               "layout": "a spiral of blocks" if i else "two rows"}
              for i, u in enumerate(UNITS)]}}}


class Base(unittest.TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp(prefix="wgf-level-")
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)
        self.run_dir = os.path.join(self.base, "run")
        self.guard = os.path.join(self.base, "guarded")
        os.makedirs(self.guard)
        with open(os.path.join(self.guard, "rules.txt"), "w") as handle:
            handle.write("the critic's rules\n")
        self.records = os.path.join(self.run_dir, "playability", "1-1", "out")
        self.desktop = os.path.join(self.records, "desktop")
        os.makedirs(os.path.join(self.desktop, "level"))
        os.makedirs(os.path.join(self.desktop, "frames"))
        self.write_survey()
        self.write_risk(PAYING)
        self.play = {"title_id": "demo", "commit": "c" * 40, "frames": [], "verdict": "PASS",
                     "records_dir": "playability/1-1/out"}
        self.judge = os.path.join(self.base, "judge.py")
        with open(self.judge, "w") as handle:
            handle.write(JUDGE)

    def write_survey(self, moments=MOMENTS, boxes=None):
        visits = []
        for index, unit in enumerate(UNITS):
            frames = []
            for m_index, moment in enumerate(moments):
                rel = f"level/{unit}-{moment}.png"
                path = os.path.join(self.desktop, *rel.split("/"))
                png(path, 30 + 10 * m_index, stripe=4 + 8 * index)
                entities = (boxes or {}).get(unit) or [
                    ["player", None, 600, 600, 80, 20],
                    ["target", "brick", 460 + 40 * index, 120, 360 - 80 * index, 200 + 100 * index]]
                frames.append({"moment": moment, "file": rel, "sha256": digest(path),
                               "at_ms": 1000 * (m_index + 1), "progress": 0.3 * m_index,
                               "entities": entities})
            visits.append({"asked": unit, "entered": True, "index": index + 1,
                           "level_frames": frames})
        with open(os.path.join(self.desktop, "survey.json"), "w") as handle:
            json.dump({"applies": True, "asked": UNITS, "visits": visits}, handle)

    def write_risk(self, record):
        path = os.path.join(self.desktop, "risk.json")
        if record is None:
            if os.path.exists(path):
                os.remove(path)
            return
        with open(path, "w") as handle:
            json.dump(record, handle)

    def config(self, plan=None, kind="command", **judge):
        scenario = os.path.join(self.base, "scenario.json")
        with open(scenario, "w") as handle:
            json.dump(plan or [], handle)
        self.counter = os.path.join(self.base, "count")
        if os.path.exists(self.counter):
            os.remove(self.counter)
        return {"leveldesign": {"judge": {
                    "kind": kind, "timeout_seconds": 60,
                    "argv": [sys.executable, self.judge, scenario, self.counter, "{verdict}",
                             "{frames_dir}"] if kind == "command" else [], **judge}},
                "review": {"guarded_paths": [self.guard]}}

    def runs(self):
        with open(self.counter) as handle:
            return int(handle.read())

    def run_step(self, config, environment=RELEASE, design=DESIGN):
        docs = {"playability-report": self.play, "game-design": design}

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
                                        environment=dict(environment or {}))
        return LevelDesignStep(types.SimpleNamespace(params={}, id="level-design")).execute(
            Inputs(), context)

    def report(self, result):
        self.assertEqual(len(result.artifacts), 1, result.error or result.message)
        content = result.artifacts[0].content
        self.assertEqual(ArtifactContracts()("level-design-report", content), [])
        return content

    def check(self, report, check_id):
        return next(c for c in report["checks"] if c["id"] == check_id)


class TheRubricOutcomes(Base):
    def test_designed_units_with_a_paying_risk_pass(self):
        result = self.run_step(self.config([verdict()]))
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
        report = self.report(result)
        self.assertEqual(report["verdict"], "PASS")
        self.assertEqual([u["unit_id"] for u in report["units"]], UNITS)
        self.assertEqual([f["moment"] for f in report["units"][0]["frames"]], MOMENTS)
        self.assertEqual({c["id"]: c["status"] for c in report["checks"]},
                         {"level.frames": "PASS", "level.critic": "PASS",
                          "risk.measured": "PASS", "risk.reward": "PASS"})
        self.assertEqual(report["mean_score"], 4)
        self.assertEqual(report["rubric"]["sha256"], RUBRIC["sha256"])
        self.assertIsNone(report["units"][0]["scores"]["distinct_from_previous"])

    def test_a_dimension_below_the_bar_fails_to_the_level_designer(self):
        bad = {"w1-l2": scores(4, play_space=1)}
        result = self.run_step(self.config([verdict(bad)]))
        self.assertEqual(result.outcome, StepOutcome.FAILED)
        self.assertEqual(result.route, "develop")
        self.assertFalse(result.retryable)
        report = self.report(result)
        self.assertEqual(report["verdict"], "FAIL")
        self.assertIn("level.critic", report["failed"])
        found = [f for f in report["findings"] if f["unit"] == "w1-l2"]
        self.assertEqual(found[0]["owner"], "level-design")
        self.assertEqual(found[0]["dimension"], "level-design")
        self.assertEqual(found[0]["observed"], 1)
        self.assertEqual(report["scores"]["play_space"], 1)

    def test_a_blocker_fails_whatever_the_scores(self):
        result = self.run_step(self.config([verdict(findings=[{
            "id": "clone-unit", "severity": "blocker", "unit": "w1-l3", "frame": "w1-l3/start",
            "dimension": "distinct_from_previous", "summary": "w1-l2 again, recoloured",
            "route": "develop"}])]))
        self.assertEqual(result.outcome, StepOutcome.FAILED)
        report = self.report(result)
        self.assertTrue(any(f["id"] == "level-design:clone-unit@w1-l3"
                            and f["severity"] == "blocker" for f in report["findings"]))

    def test_an_undesigned_unit_routes_to_design(self):
        result = self.run_step(self.config([verdict(
            {"w1-l3": scores(4, layout_identity=1)}, findings=[{
                "id": "undesigned-unit", "severity": "blocker", "unit": "w1-l3", "frame": None,
                "dimension": "layout_identity", "summary": "the design gives w1-l3 no layout",
                "route": "design-gap"}])]))
        self.assertEqual(result.outcome, StepOutcome.FAILED)
        self.assertEqual(result.route, "design-gap")
        report = self.report(result)
        self.assertEqual(report["routes"][0], "design-gap")
        gap = next(f for f in report["findings"] if f["route"] == "design-gap")
        self.assertEqual(gap["design_gap"]["field"], "build_spec.content.units[w1-l3]")

    def test_a_mean_below_its_bar_fails(self):
        result = self.run_step(self.config([verdict(value=3)]))
        self.assertEqual(result.outcome, StepOutcome.FAILED)
        report = self.report(result)
        self.assertEqual(report["mean_score"], 3)
        self.assertTrue(any(f["check"] == "level.critic:mean" for f in report["findings"]))

    def test_unmeasured_is_not_passed_at_release_and_a_warning_below(self):
        blind = {"w1-l2": scores(4, reveal=None)}
        result = self.run_step(self.config([verdict(blind)]))
        self.assertEqual(result.outcome, StepOutcome.FAILED)
        self.assertEqual(self.check(self.report(result), "level.critic")["status"], "FAIL")
        result = self.run_step(self.config([verdict(blind)]), environment=MVP)
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
        report = self.report(result)
        self.assertEqual(self.check(report, "level.critic")["status"], "SKIPPED")
        self.assertFalse(self.check(report, "level.critic")["required"])
        self.assertEqual(report["verdict"], "WARNING")

    def test_a_first_unit_scored_on_its_previous_is_coerced_to_null(self):
        first = {"w1-l1": scores(4)}
        result = self.run_step(self.config([verdict(first)]))
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
        self.assertIsNone(self.report(result)["units"][0]["scores"]["distinct_from_previous"])

    def test_a_malformed_verdict_is_repaired(self):
        result = self.run_step(self.config(["malformed", verdict()]))
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
        self.assertEqual(self.runs(), 2)
        self.assertEqual(self.report(result)["judge_runs"], 2)
        brief = open(os.path.join(self.run_dir, "level-design", "level-design-1-1",
                                  "level-design-2.brief.md")).read()
        self.assertIn("Repair your previous verdict", brief)

    def test_a_verdict_missing_a_unit_is_never_read_charitably(self):
        short = verdict()
        short["units"] = short["units"][:2]
        result = self.run_step(self.config([short], repair_rounds=0))
        self.assertEqual(result.outcome, StepOutcome.FAILED)
        self.assertIn("malformed-verdict", result.error)
        self.assertIn("lacks w1-l3", result.error)

    def test_no_judge_blocks_at_release_and_skips_below(self):
        result = self.run_step(self.config(kind="none"))
        self.assertEqual(result.outcome, StepOutcome.BLOCKED)
        report = self.report(result)
        self.assertEqual(report["verdict"], "BLOCKED")
        self.assertIn("needs a judge", report["blocked_reason"])
        self.write_risk(None)
        result = self.run_step(self.config(kind="none"), environment=MVP)
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
        report = self.report(result)
        self.assertEqual(report["verdict"], "WARNING")
        self.assertEqual(self.check(report, "level.critic")["status"], "SKIPPED")
        self.assertIn("not a pass", result.message)

    def test_missing_moments_fail_the_frames_check(self):
        self.write_survey(moments=["start"])
        result = self.run_step(self.config([verdict()]))
        self.assertEqual(result.outcome, StepOutcome.FAILED)
        report = self.report(result)
        frames = self.check(report, "level.frames")
        self.assertEqual(frames["status"], "FAIL")
        self.assertEqual(frames["measured"]["missing"]["w1-l1"], ["middle", "end"])

    def test_a_changed_frame_is_refused(self):
        with open(os.path.join(self.desktop, "level", "w1-l2-middle.png"), "ab") as handle:
            handle.write(b"tampered")
        result = self.run_step(self.config([verdict()]))
        self.assertEqual(result.outcome, StepOutcome.FAILED)
        self.assertIn("not the frame the playability bot recorded", result.error)

    def test_a_critic_that_writes_into_its_frames_is_refused(self):
        result = self.run_step(self.config(["touch-frame", verdict()]))
        self.assertEqual(result.outcome, StepOutcome.FAILED)
        self.assertIn("judge-isolation-violation", result.error)

    def test_a_design_without_units_reports_no_level_checks(self):
        self.write_survey(moments=[])
        os.remove(os.path.join(self.desktop, "survey.json"))
        result = self.run_step(self.config([verdict()]), design={"title_id": "demo",
                                                                 "build_spec": {}})
        report = self.report(result)
        self.assertEqual([c["id"] for c in report["checks"]], ["risk.measured", "risk.reward"])
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)

    def test_old_runs_are_sampled_from_the_traverse(self):
        os.remove(os.path.join(self.desktop, "survey.json"))
        frames = []
        for index in (1, 2, 3):
            path = os.path.join(self.desktop, "frames", f"unit-{index}-1s.png")
            png(path, 40, stripe=index * 5)
            frames.append({"id": f"unit-{index}-1s", "project": "desktop",
                           "path": os.path.relpath(path, self.run_dir), "sha256": digest(path)})
        self.play["frames"] = frames
        with open(os.path.join(self.desktop, "traverse.json"), "w") as handle:
            json.dump({"applies": True, "frames": [f["id"] for f in frames],
                       "per_unit": [{"unit_id": u, "index": i + 1}
                                    for i, u in enumerate(UNITS)]}, handle)
        result = self.run_step(self.config([verdict()]))
        report = self.report(result)
        self.assertEqual([u["source"] for u in report["units"]], ["traverse"] * 3)
        self.assertEqual(self.check(report, "level.frames")["status"], "FAIL")


class TheBaselineCritic(Base):
    def test_it_measures_space_and_distinctness_and_leaves_taste_unmeasured(self):
        boxes = {"w1-l1": [["player", None, 0, 700, 100, 20], ["target", "b", 0, 0, 800, 90]]}
        self.write_survey(boxes=boxes)
        result = self.run_step(self.config(kind="baseline"))
        report = self.report(result)
        first = report["units"][0]
        self.assertLess(first["measures"]["play_space"], 0.35)
        self.assertLess(first["scores"]["play_space"], RUBRIC["pass_bar"])
        self.assertIsNone(first["scores"]["reveal"])
        self.assertIsNotNone(report["units"][1]["scores"]["distinct_from_previous"])
        self.assertEqual(result.outcome, StepOutcome.FAILED)
        self.assertEqual(report["judge"]["kind"], "baseline")

    def test_approved_scores_carry_only_for_matching_frames(self):
        approved = os.path.join(self.base, "approved")
        payload = {}
        for unit in UNITS:
            os.makedirs(os.path.join(approved, unit))
            for moment in MOMENTS:
                shutil.copyfile(os.path.join(self.desktop, "level", f"{unit}-{moment}.png"),
                                os.path.join(approved, unit, f"{moment}.png"))
            payload[unit] = {"scores": {d: 5 for d in DIMENSIONS}}
        with open(os.path.join(approved, "approved.json"), "w") as handle:
            json.dump(payload, handle)
        verdict_, _measures = baseline.judge(RUBRIC, self._staged(), approved)
        self.assertEqual(verdict_["units"][0]["scores"]["reveal"], 5)
        png(os.path.join(approved, "w1-l2", "middle.png"), 250, stripe=0)
        verdict_, measures = baseline.judge(RUBRIC, self._staged(), approved)
        self.assertIsNone(verdict_["units"][1]["scores"]["reveal"])
        self.assertFalse(measures["w1-l2"]["approved_match"]["all"])

    def _staged(self):
        from wgf_leveldesign.units import sample, stage
        units, _project, _why = sample(RUBRIC, self.play, self.run_dir, DESIGN)
        stage(units, os.path.join(self.base, "stage"))
        return units

    def test_the_ladder(self):
        self.assertEqual(baseline.ladder(RUBRIC["baseline"]["play_space"], 0.11), 0)
        self.assertEqual(baseline.ladder(RUBRIC["baseline"]["play_space"], 0.4), 3)
        self.assertEqual(baseline.ladder(RUBRIC["baseline"]["play_space"], 0.9), 5)


class ThePolicyOutcomes(unittest.TestCase):
    def judge(self, record):
        return risk.judge(record, RULES)

    def test_greedy_earning_more_at_a_higher_failure_rate_pays(self):
        block, raw = self.judge(PAYING)
        self.assertEqual(raw["measured"][0], True)
        self.assertEqual(raw["reward"][0], True)
        self.assertEqual(block["reward_metric"], "gems")
        self.assertTrue(all(u["pays"] and u["risky"] for u in block["units"]))

    def test_more_reward_for_no_risk_is_not_a_risk(self):
        block, raw = self.judge(risk_record({"u": ([(3, False)] * 3, [(9, False)] * 3)}))
        self.assertFalse(raw["reward"][0])
        self.assertTrue(block["units"][0]["pays"])
        self.assertFalse(block["units"][0]["risky"])

    def test_more_risk_for_no_reward_does_not_pay(self):
        block, raw = self.judge(risk_record({"u": ([(3, False)] * 3,
                                                   [(3, True), (3, True), (3, False)])}))
        self.assertFalse(raw["reward"][0])
        self.assertFalse(block["units"][0]["pays"])
        self.assertTrue(block["units"][0]["risky"])

    def test_no_play_policy_is_unmeasured(self):
        block, raw = self.judge({"applies": True, "declared": False,
                                 "reason": "the probe declares no play.policy"})
        self.assertFalse(block["measured"])
        self.assertEqual(raw["measured"][0], False)
        self.assertIsNone(raw["reward"][0])

    def test_a_policy_the_probe_does_not_offer_is_unmeasured(self):
        _block, raw = self.judge(risk_record({"u": ([(1, False)] * 3, [(5, True)] * 3)},
                                             offered=("safe",)))
        self.assertIsNone(raw["reward"][0])

    def test_too_few_attempts_is_unmeasured(self):
        block, raw = self.judge(risk_record({"u": ([(3, False)], [(9, True)] * 3)}))
        self.assertFalse(block["units"][0]["measured"])
        self.assertIn("safe counted fewer than", block["units"][0]["reason"])
        self.assertIsNone(raw["reward"][0])

    def test_a_lower_metric_is_negated(self):
        record = {"applies": True, "declared": True, "offered": ["safe", "greedy"],
                  "attempts": []}
        for policy, times, failed in (("safe", (30, 31, 29), False), ("greedy", (20, 22, 21), True)):
            for t in times:
                record["attempts"].append({
                    "unit": "u", "policy": policy, "entered": True, "policy_set": True,
                    "outcome": "lost" if failed and t == 20 else "won",
                    "metrics_start": {"time": 0}, "metrics_end": {"time": t},
                    "metrics_max": {"time": t}})
        block, raw = self.judge(record)
        self.assertEqual(block["reward_metric"], "time")
        self.assertGreater(block["units"][0]["reward_gain"], 0)
        self.assertTrue(raw["reward"][0])

    def test_the_probes_own_measures_win(self):
        record = risk_record({"u": ([(3, False)] * 3, [(9, True)] * 3)},
                             measures={"reward": "score", "failure": ["falls"]})
        for a in record["attempts"]:
            a["metrics_end"]["score"] = 100 if a["policy"] == "safe" else 100
        block, raw = self.judge(record)
        self.assertEqual(block["reward_metric"], "score")
        self.assertFalse(block["units"][0]["pays"])

    def test_no_record_is_unmeasured(self):
        block, raw = self.judge(None)
        self.assertFalse(block["applies"])
        self.assertIsNone(raw["reward"][0])


class TheRiskInTheStep(Base):
    def test_no_play_policy_fails_at_release_and_is_skipped_below(self):
        self.write_risk({"applies": True, "declared": False, "attempts": [],
                         "reason": "the probe declares no play.policy"})
        result = self.run_step(self.config([verdict()]))
        self.assertEqual(result.outcome, StepOutcome.FAILED)
        report = self.report(result)
        self.assertEqual(self.check(report, "risk.measured")["status"], "FAIL")
        self.assertEqual(self.check(report, "risk.reward")["status"], "FAIL")
        result = self.run_step(self.config([verdict()]), environment=MVP)
        self.assertEqual(result.outcome, StepOutcome.SUCCESS)
        report = self.report(result)
        self.assertEqual(self.check(report, "risk.reward")["status"], "SKIPPED")
        self.assertEqual(report["verdict"], "WARNING")

    def test_a_risk_that_does_not_pay_fails_at_release(self):
        self.write_risk(risk_record({"w1-l1": ([(3, False)] * 3, [(3, True)] * 3)}))
        result = self.run_step(self.config([verdict()]))
        self.assertEqual(result.outcome, StepOutcome.FAILED)
        self.assertEqual(result.route, "develop")
        report = self.report(result)
        self.assertEqual(self.check(report, "risk.reward")["status"], "FAIL")
        self.assertTrue(any(f["check"] == "risk.reward" for f in report["findings"]))


class TheWiring(unittest.TestCase):
    def test_playability_asks_for_frames_and_policies(self):
        from wgf_playability.step import PlayabilityStep, RECORDS, spread
        self.assertIn("risk", RECORDS)
        settings = PlayabilityStep._risk_settings(DESIGN, {"survey": True, "risk": True}, UNITS)
        self.assertTrue(settings["level_frames"])
        self.assertEqual(settings["risk_policies"], ["safe", "greedy"])
        self.assertEqual(settings["risk_units"], spread(UNITS, RULES["play"]["units"]))
        self.assertGreater(settings["risk_ms"], 0)
        off = PlayabilityStep._risk_settings(DESIGN, {}, [])
        self.assertEqual(off["risk_units"], [])
        self.assertFalse(off["level_frames"])
        self.assertEqual(PlayabilityStep._risk_settings({}, {"risk": True}, [])["risk_units"],
                         [""])
        self.assertEqual(spread(list(range(10)), 3), [0, 4, 9])
        self.assertEqual(spread([1, 2], 3), [1, 2])

    def test_the_bot_records_level_frames_and_the_risk_test(self):
        with open(os.path.join(SCRIPTS, "wgf_playability", "bot.spec.ts"), encoding="utf-8") as h:
            bot = h.read()
        for needle in ('test("risk:', "play.policy", "level_frames", "levelMoment",
                       '"risk", {'):
            self.assertIn(needle, bot)

    def test_triage_routes_its_findings(self):
        from wgf_triage import findings as normalizer
        from wgf_triage.routing import Routing
        routing = Routing.load()
        report = {"provenance": {"artifact_id": "x"}, "verdict": "FAIL", "findings": [
            {"id": "level-design:play_space@u1", "check": "level.critic:play_space",
             "dimension": "level-design", "severity": "major", "summary": "empty",
             "owner": "level-design", "route": "develop", "unit": "u1", "frame": None},
            {"id": "level-design:undesigned-unit@u2", "check": "level.critic:undesigned-unit",
             "dimension": "level-design", "severity": "blocker", "summary": "no layout",
             "owner": "level-design", "route": "design-gap", "unit": "u2", "frame": None,
             "design_gap": {"field": "build_spec.content.units[u2]", "question": "layout?",
                            "assumed": None, "severity": "blocking"}}]}
        found = normalizer.normalize("level-design-report", report, routing)
        self.assertEqual([f["owner"] for f in found], ["level-designer", "level-designer"])
        self.assertEqual([f["route"] for f in found], ["develop", "design"])
        self.assertEqual(found[1]["task"]["design_field"], "build_spec.content.units[u2]")

    def test_the_quality_floor_reads_it_at_release(self):
        from wgf_quality.step import load_contract
        spec, _record = load_contract()
        criteria = {c["id"]: c for c in spec["floor"]["universal"]}
        self.assertEqual(criteria["floor.level_design"]["severity"], {"release": "blocker"})
        self.assertEqual(criteria["floor.risk_reward"]["evaluate"]["report"],
                         "level-design-report")
        self.assertIn("level-design-report", spec["floor"]["build_evidence"])

    def test_the_workflow_runs_it_after_content_sufficiency(self):
        data = load_file(os.path.join(ROOT, "core", "workflows", "new-game.workflow.yaml"))
        flow = data["workflow"]
        steps = [s["id"] for s in flow["steps"]]
        self.assertEqual(steps.index("level-design"), steps.index("content-sufficiency") + 1)
        step = next(s for s in flow["steps"] if s["id"] == "level-design")
        self.assertEqual(step["on"], {"develop": "triage", "design-gap": "triage"})
        self.assertIn("core/reference/level-design-rubric.yaml", flow["pinned_references"])
        self.assertIn("core/reference/risk-reward.yaml", flow["pinned_references"])
        play = next(s for s in flow["steps"] if s["id"] == "playability")
        self.assertTrue(play["with"]["risk"])
        gate = next(s for s in flow["steps"] if s["id"] == "quality-gate")
        self.assertIn("level-design-report", gate["inputs"])

    def test_the_mock_step_routes_like_the_real_one(self):
        from wgflib.workflow import mock
        self.assertIn(mock.MockLevelDesignStep, mock.MOCK_STEPS)
        body = json.load(open(os.path.join(SCRIPTS, "wgflib", "workflow", "fixtures",
                                           "level-design-report.json")))
        mock.MockLevelDesignStep.customize(mock.MockLevelDesignStep.__new__(mock.MockLevelDesignStep),
                                           body, "level-design-report", None, "design-gap")
        self.assertEqual(body["routes"], ["design-gap"])
        self.assertIn("design_gap", body["findings"][0])


if __name__ == "__main__":
    unittest.main()

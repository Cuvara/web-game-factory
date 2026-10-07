"""The accepted baseline (scripts/wgf_baseline): a build a person accepted is the bar the next
build of the same game must not fall below (workflow 16, docs/accepted-baseline.md).

Observed 2026-10-05 (factory-learning-ledger L8, L12): a run adopted the repository whose
build a person had passed at G4, wrote a new design, and rewrote the game; every absolute gate
still passed and the person found the accepted builds much better. Here:

  * locate                  the newest G4 `pass` a person gave for the title is the baseline;
                            iterate, automation and other titles are not; a pin that no
                            longer hashes is a problem, never silently replaced
  * replacement             an extension of the accepted build passes; a rewrite of its units
                            or code above the maximum waits for a person (approve | restore);
                            automation's answer is refused; approve is recorded and carried;
                            restore is FAILED route `restore`
  * metrics                 worse beyond tolerance -> FAIL + a routed finding; within -> PASS;
                            not measured by the accepted build -> SKIPPED; measured by it and
                            not by the candidate -> UNMEASURED, never a pass
  * paired judgement        `worse` on a dimension -> FAIL, routed by the rubric dimension;
                            same -> PASS; no judge -> BLOCKED, never a pass
  * playtest                a person's blocker holds the build until confirmed or re-measured
                            on a newer build; a newer build alone never closes it
  * quality gate            no baseline -> SKIPPED; a baseline its build was not measured
                            against -> BLOCKED (unmeasured); a failing report -> FAIL
  * replay                  the real reports of both validation games: the gate would have
                            failed both builds a person judged worse

    python -m unittest scripts.tests.test_accepted_baseline
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

from wgf_assets.raster import Image, encode_png  # noqa: E402
from wgf_baseline import brief as baseline_brief  # noqa: E402
from wgf_baseline import locate, metrics, paired, playtest, replacement  # noqa: E402
from wgf_baseline.step import (AcceptedBaselineStep, BaselineRegressionStep,  # noqa: E402
                               load_reference)
from wgf_quality.step import baseline_status  # noqa: E402
from wgf_triage import findings as normalizer  # noqa: E402
from wgf_triage.routing import Routing  # noqa: E402
from wgflib import provenance  # noqa: E402
from wgflib.hashing import content_hash  # noqa: E402
from wgflib.workflow.contracts import ArtifactContracts  # noqa: E402
from wgflib.workflow.model import StepOutcome  # noqa: E402
from wgflib.yamllite import load_file  # noqa: E402

REFERENCE = os.path.join(os.path.dirname(SCRIPTS), "core", "reference",
                         "accepted-baseline.yaml")
REAL = os.path.join(HERE, "fixtures", "accepted-baseline", "real-reports.json")


class _Log:
    def __getattr__(self, name):
        return lambda *a, **k: None


def spec():
    return load_file(REFERENCE)


def git(root, *args):
    return subprocess.run(["git", "-C", root, *args], check=True, capture_output=True,
                          text=True).stdout.strip()


def make_repo(root, units, files):
    os.makedirs(root, exist_ok=True)
    git(root, "init", "-q")
    git(root, "config", "user.email", "t@example.com")
    git(root, "config", "user.name", "t")
    return commit(root, units, files)


def commit(root, units, files, message="c"):
    os.makedirs(os.path.join(root, "public", "content"), exist_ok=True)
    with open(os.path.join(root, "public", "content", "units.json"), "w") as handle:
        json.dump({"units": units}, handle)
    for path, text in files.items():
        full = os.path.join(root, path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        if text is None:
            if os.path.exists(full):
                os.remove(full)
            continue
        with open(full, "w") as handle:
            handle.write(text)
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", message)
    return git(root, "rev-parse", "HEAD")


UNITS = [{"id": f"w1-l{i}", "objective": f"break {10 + i} bricks", "speed": 0.1 * i}
         for i in range(1, 9)]
CODE = {f"src/m{i}.ts": "".join(f"line {i}.{n}\n" for n in range(40)) for i in range(6)}


def png(path, rgb, size=(64, 48)):
    image = Image(*size)
    for k in range(size[0] * size[1]):
        image.pixels[4 * k:4 * k + 4] = bytes((*rgb, 255))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(encode_png(image))
    return provenance_sha(path)


def provenance_sha(path):
    import hashlib
    with open(path, "rb") as handle:
        return "sha256:" + hashlib.sha256(handle.read()).hexdigest()


def play_report(commit_sha, *, inputs=60, luminance=120.0, reached="won", areas=None,
                frames=()):
    areas = areas or {"player": 0.016, "goal": 0.005, "target": 0.24}
    checks = []
    for project in ("desktop", "mobile"):
        checks += [
            {"id": "win.reachable", "project": project, "status": "PASS",
             "measured": {"reached": reached, "inputs": inputs}},
            {"id": "frames.readable", "project": project, "status": "PASS",
             "measured": {"play-2s": {"mean_luminance": luminance, "contrast": 47.0}}},
            {"id": "entities.visible", "project": project, "status": "PASS",
             "measured": {k: {"median_area": v} for k, v in areas.items()}},
            {"id": "depth.ramp", "project": project, "status": "PASS",
             "measured": {"bad_play_ended_ms": 30000}},
            {"id": "depth.session_length", "project": project, "status": "PASS",
             "measured": {"length_ms": 150000}},
        ]
    return {"title_id": "demo", "commit": commit_sha, "verdict": "PASS", "checks": checks,
            "frames": list(frames), "provenance": {"artifact_id": "wgf:playability-report:x"}}


class Inputs:
    def __init__(self, docs):
        self.docs = docs
        self.refs = {k: types.SimpleNamespace(content_hash=None, seq=i, id=f"artifact-{k}")
                     for i, k in enumerate(docs)}

    def __contains__(self, kind):
        return kind in self.docs

    def load(self, kind):
        return self.docs[kind]

    @property
    def missing(self):
        return []


class Case(unittest.TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp(prefix="wgf-baseline-")
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)
        self.run_dir = os.path.join(self.base, "store", "run-now")
        os.makedirs(self.run_dir)
        self.repo = os.path.join(self.base, "game")
        self.accepted = make_repo(self.repo, UNITS, CODE)
        self.contracts = ArtifactContracts()

    def context(self, decision=None, judge=None):
        config = {}
        if judge == "baseline":
            os.makedirs(os.path.join(self.base, "approved"), exist_ok=True)
            config = {"visualqa": {"judge": {"kind": "baseline",
                                             "baseline_dir": os.path.join(self.base,
                                                                          "approved")}}}
        elif isinstance(judge, dict):
            config = {"visualqa": {"judge": judge}}
        return types.SimpleNamespace(config=config, run_dir=self.run_dir, logger=_Log(),
                                     visit=1, attempt=1, execution=1, environment={},
                                     decision=decision, run_id="run-now", project_id="demo",
                                     now="2026-10-05T12:00:00Z", previous_outputs=[])

    def baseline(self, frames_rgb=(30, 30, 30), **play):
        frames = []
        for project in ("desktop", "mobile"):
            for state in ("first-session-1s", "play-2s", "state-playing"):
                rel = f"accepted-baseline/x/frames/{project}/{state}.png"
                sha = png(os.path.join(self.run_dir, rel), frames_rgb)
                frames.append({"project": project, "id": state, "path": rel, "sha256": sha})
        extracted = metrics.extract(spec(), {"playability-report": play_report(
            self.accepted, **play)})
        return {"title_id": "demo", "status": "present", "reason": "accepted at G4",
                "accepted": {"commit": self.accepted, "shipped_commit": self.accepted,
                             "source": "run-store", "run_id": "run-old",
                             "decision": {"artifact_id": "wgf:decision-record:demo-g4:1",
                                          "decided_at": "2026-10-04T06:14:03Z"}},
                "reports": [], "frames": frames,
                "metrics": {k: dict(v) for k, v in extracted.items()}, "problems": [],
                "reference": {"path": "core/reference/accepted-baseline.yaml",
                              "version": "1.0.0", "sha256": "sha256:" + "0" * 64},
                "provenance": {"artifact_id": "wgf:accepted-baseline:demo:1"}}

    def candidate_frames(self, rgb):
        frames = []
        for project in ("desktop", "mobile"):
            for state in ("first-session-1s", "play-2s", "state-playing"):
                rel = f"playability/1-1/out/{project}/frames/{state}.png"
                sha = png(os.path.join(self.run_dir, rel), rgb)
                frames.append({"project": project, "id": state, "path": rel, "sha256": sha})
        return frames

    def docs(self, candidate, baseline, play=None, previous=None, design=None):
        docs = {"accepted-baseline": baseline,
                "prototype-report": {"title_id": "demo",
                                     "build_ref": {"commit_sha": candidate}},
                "scaffold-record": {"repository": {"local_path": self.repo}},
                "game-design": design or {"title_id": "demo", "engine": {"dimension": "2d"}}}
        if play is not None:
            docs["playability-report"] = play
        if previous is not None:
            docs["baseline-regression-report"] = previous
        return docs

    def run_step(self, docs, phase="production", decision=None, judge="baseline"):
        step = BaselineRegressionStep(types.SimpleNamespace(
            params={"phase": phase}, id="greybox-baseline" if phase == "greybox"
            else "baseline-regression"))
        result = step.execute(Inputs(docs), self.context(decision, judge))
        for artifact in result.artifacts or []:
            report = artifact.content
            problems = self.contracts.problems(artifact.type, report)
            self.assertEqual(problems, [], problems)
        return result


class Replacement(Case):
    def test_an_extension_of_the_accepted_build_is_within_the_maximum(self):
        units = UNITS + [{"id": "w2-l1", "objective": "new", "speed": 0.9}]
        units[0] = dict(units[0], art="sprite")   # a key added is an extension
        files = {"src/m0.ts": CODE["src/m0.ts"] + "added\n", "src/new.ts": "x\n"}
        candidate = commit(self.repo, units, files)
        measured = replacement.measure(replacement.Git(self.repo), self.accepted, candidate,
                                       spec()["replacement"])
        self.assertEqual(measured["units_removed"], [])
        self.assertEqual(measured["units_changed"], [])
        self.assertEqual(measured["lines_deleted"], 0)
        self.assertEqual(measured["exceeded"], [])

    def test_a_rewrite_of_units_and_code_exceeds_it(self):
        units = [dict(u, objective="different") for u in UNITS[:6]]
        files = {"src/m0.ts": "short\n", "src/m1.ts": None, "src/m2.ts": "short\n"}
        candidate = commit(self.repo, units, files)
        measured = replacement.measure(replacement.Git(self.repo), self.accepted, candidate,
                                       spec()["replacement"])
        self.assertEqual(measured["units_removed"], ["w1-l7", "w1-l8"])
        self.assertEqual(len(measured["units_changed"]), 6)
        self.assertEqual(measured["units_replaced_share"], 1.0)
        self.assertEqual(measured["files_rewritten"], 3)
        self.assertEqual(set(measured["exceeded"]),
                         {"units_replaced_share", "files_rewritten_share",
                          "lines_deleted_share"})

    def test_no_content_data_file_leaves_units_unmeasured_never_zero(self):
        os.remove(os.path.join(self.repo, "public", "content", "units.json"))
        git(self.repo, "commit", "-qam", "no data")
        bare = git(self.repo, "rev-parse", "HEAD")
        measured = replacement.measure(replacement.Git(self.repo), bare, bare,
                                       spec()["replacement"])
        self.assertIsNone(measured["units_replaced_share"])
        self.assertTrue(measured["unmeasured"])

    def rewrite(self):
        return commit(self.repo, [dict(u, objective="other") for u in UNITS],
                      {"src/m0.ts": None, "src/m1.ts": None})

    def test_a_replacement_waits_for_a_person(self):
        candidate = self.rewrite()
        result = self.run_step(self.docs(candidate, self.baseline()), phase="greybox")
        self.assertEqual(result.outcome, StepOutcome.WAITING_FOR_HUMAN)
        self.assertEqual(result.data["choices"], ["approve", "restore"])
        self.assertIn("never approves on a timeout", result.message)

    def test_automation_cannot_approve_a_replacement(self):
        candidate = self.rewrite()
        result = self.run_step(self.docs(candidate, self.baseline()), phase="greybox",
                               decision={"decision": "approve", "decided_by": "automation"})
        self.assertEqual(result.outcome, StepOutcome.WAITING_FOR_HUMAN)

    def test_a_persons_approval_is_recorded_and_carried(self):
        candidate = self.rewrite()
        result = self.run_step(self.docs(candidate, self.baseline()), phase="greybox",
                               decision={"decision": "approve", "decided_by": "human",
                                         "note": "new design on purpose",
                                         "decided_at": "2026-10-05T12:00:00Z"})
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.message)
        report = result.artifacts[0].content
        self.assertEqual(report["replacement"]["decision"]["choice"], "approve")
        self.assertEqual(report["verdict"], "PASS")
        # the next visit (no decision of its own) carries the approval
        again = self.run_step(self.docs(candidate, self.baseline(), previous=report),
                              phase="greybox")
        self.assertEqual(again.outcome, StepOutcome.SUCCESS)
        self.assertEqual(again.artifacts[0].content["replacement"]["decision"]["note"],
                         "new design on purpose")

    def test_restore_sends_the_build_back(self):
        candidate = self.rewrite()
        result = self.run_step(self.docs(candidate, self.baseline()), phase="greybox",
                               decision={"decision": "restore", "decided_by": "human"})
        self.assertEqual(result.outcome, StepOutcome.FAILED)
        self.assertEqual(result.route, "restore")
        finding = result.artifacts[0].content["findings"][0]
        self.assertIn("Restore what the accepted build shipped", finding["task"]["change"])

    def test_no_baseline_is_skipped_with_its_reason(self):
        none = {"status": "none", "reason": "nothing was accepted yet"}
        result = self.run_step(self.docs(self.accepted, none), phase="greybox")
        self.assertEqual(result.outcome, StepOutcome.SUCCESS)
        report = result.artifacts[0].content
        self.assertEqual(report["verdict"], "SKIPPED")
        self.assertEqual(report["skipped_reason"], "nothing was accepted yet")

    def test_a_baseline_that_cannot_be_measured_blocks(self):
        broken = dict(self.baseline(), status="unmeasured",
                      problems=["the decision pins playability-report x, which no run holds"])
        result = self.run_step(self.docs(self.accepted, broken), phase="greybox")
        self.assertEqual(result.outcome, StepOutcome.BLOCKED)
        self.assertIn("never skipped", result.message)


class Metrics(unittest.TestCase):
    def compare(self, accepted, candidate, approved=False):
        return metrics.compare(spec(), metrics.extract(spec(), {"playability-report": accepted}),
                               metrics.extract(spec(), {"playability-report": candidate}),
                               approved=approved)

    def by_id(self, results):
        return {(r["id"], r["project"]): r for r in results}

    def test_worse_beyond_tolerance_fails_within_passes(self):
        results = self.by_id(self.compare(play_report("a" * 40, inputs=60),
                                          play_report("b" * 40, inputs=6)))
        self.assertEqual(results[("win.inputs", "desktop")]["status"], "FAIL")
        self.assertEqual(results[("frame.luminance", "desktop")]["status"], "PASS")
        same = self.by_id(self.compare(play_report("a" * 40), play_report("b" * 40,
                                                                           inputs=70)))
        self.assertTrue(all(r["status"] == "PASS" for r in same.values()))

    def test_gameplay_metrics_are_read_on_desktop_the_look_on_both(self):
        results = self.by_id(self.compare(play_report("a" * 40), play_report("b" * 40)))
        self.assertIn(("frame.luminance", "mobile"), results)
        self.assertNotIn(("win.inputs", "mobile"), results)

    def test_a_role_the_candidate_lost_fails_and_an_unmeasured_metric_never_passes(self):
        candidate = play_report("b" * 40, areas={"player": 0.016, "goal": 0.005})
        candidate["checks"] = [c for c in candidate["checks"] if c["id"] != "depth.ramp"]
        results = self.by_id(self.compare(play_report("a" * 40), candidate))
        self.assertEqual(results[("entity.area.target", "desktop")]["status"], "FAIL")
        self.assertEqual(results[("bad_play.ended_ms", "desktop")]["status"], "UNMEASURED")

    def test_what_the_accepted_build_did_not_measure_is_skipped(self):
        accepted = play_report("a" * 40)
        accepted["checks"] = [c for c in accepted["checks"] if c["id"] != "depth.session_length"]
        results = self.by_id(self.compare(accepted, play_report("b" * 40)))
        self.assertEqual(results[("session.length_ms", "all")]["status"], "SKIPPED")

    def test_an_approved_replacement_waives_the_tuning_never_the_outcome(self):
        results = self.by_id(self.compare(play_report("a" * 40, inputs=60),
                                          play_report("b" * 40, inputs=6, reached="lost"),
                                          approved=True))
        self.assertEqual(results[("win.inputs", "all")]["status"], "SKIPPED")
        self.assertEqual(results[("win.outcome", "desktop")]["status"], "FAIL")


class Production(Case):
    def test_equal_or_better_passes(self):
        frames = self.candidate_frames((30, 30, 30))
        result = self.run_step(self.docs(
            self.accepted, self.baseline(),
            play=play_report(self.accepted, frames=frames)))
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.message)
        report = result.artifacts[0].content
        self.assertEqual(report["verdict"], "PASS")
        self.assertEqual(report["paired"]["status"], "PASS")

    def test_a_metric_beyond_tolerance_is_blocked_and_routed(self):
        frames = self.candidate_frames((30, 30, 30))
        result = self.run_step(self.docs(
            self.accepted, self.baseline(),
            play=play_report(self.accepted, inputs=6, luminance=184.0, frames=frames)))
        self.assertEqual(result.outcome, StepOutcome.FAILED)
        self.assertEqual(result.route, "develop")
        self.assertFalse(result.retryable)
        report = result.artifacts[0].content
        ids = {f["id"] for f in report["findings"]}
        self.assertIn("baseline-regression-report:metric:win.inputs@desktop", ids)
        luminance = next(f for f in report["findings"] if "frame.luminance" in f["id"])
        self.assertEqual(luminance["dimension"], "art-2d")   # lighting, in 2D
        # triage reads them as the baseline-regression-report producer
        routing = Routing.load()
        found = normalizer.normalize("baseline-regression-report", report, routing)
        self.assertEqual({f["id"] for f in found}, ids)

    def test_paired_worse_is_blocked_and_routed_to_its_owner(self):
        frames = self.candidate_frames((240, 240, 240))   # a different look entirely
        result = self.run_step(self.docs(
            self.accepted, self.baseline(), play=play_report(self.accepted, frames=frames)))
        self.assertEqual(result.outcome, StepOutcome.FAILED)
        self.assertEqual(result.route, "assets")   # environment, art: the rubric's route
        report = result.artifacts[0].content
        worse = {d for d, v in report["paired"]["dimensions"].items()
                 if v["verdict"] == "worse"}
        self.assertEqual(worse, {"art_completeness", "consistency", "environment"})
        self.assertIn("baseline-regression-report:paired:environment",
                      {f["id"] for f in report["findings"]})

    def test_a_command_judge_answering_worse_fails(self):
        script = os.path.join(self.base, "judge.py")
        with open(script, "w") as handle:
            handle.write("import json, sys\n"
                         "dims = ['art_completeness', 'character_readability', 'environment',"
                         " 'ui_polish', 'typography', 'composition', 'consistency', 'no_debug']\n"
                         "v = {d: {'verdict': 'same', 'reason': 'no difference'} for d in dims}\n"
                         "v['environment'] = {'verdict': 'worse', 'reason': 'the sky is gone'}\n"
                         "json.dump({'dimensions': v}, open(sys.argv[1], 'w'))\n")
        frames = self.candidate_frames((30, 30, 30))
        result = self.run_step(self.docs(
            self.accepted, self.baseline(), play=play_report(self.accepted, frames=frames)),
            judge={"kind": "command", "argv": [sys.executable, script, "{verdict}"]})
        self.assertEqual(result.outcome, StepOutcome.FAILED, result.message)
        report = result.artifacts[0].content
        self.assertEqual(report["paired"]["dimensions"]["environment"]["reason"],
                         "the sky is gone")
        finding = next(f for f in report["findings"] if f["id"].endswith("paired:environment"))
        self.assertEqual(finding["route"], "assets")
        self.assertEqual(finding["owner"], Routing.load().owner("art-2d"))

    def test_no_judge_is_blocked_never_a_pass(self):
        frames = self.candidate_frames((30, 30, 30))
        result = self.run_step(self.docs(
            self.accepted, self.baseline(), play=play_report(self.accepted, frames=frames)),
            judge=None)
        self.assertEqual(result.outcome, StepOutcome.BLOCKED)
        self.assertIn("never a pass", result.message)

    def test_a_playability_report_of_another_commit_is_not_compared(self):
        result = self.run_step(self.docs(self.accepted, self.baseline(),
                                         play=play_report("f" * 40)))
        self.assertEqual(result.outcome, StepOutcome.WAITING_FOR_INPUT)


class Playtest(Case):
    def file(self, build, requests, measures=None):
        raw = json.dumps({"findings": requests, "measures": measures or {}}).encode()
        return playtest.file_notes(self.run_dir, raw, build=build, filed_at="t",
                                   filed_by="human")

    REQUEST = {"id": "marble-falls", "dimension": "gameplay", "severity": "blocker",
               "summary": "the marble rolls off-centre and falls off",
               "task": {"change": "keep the marble on the course",
                        "acceptance": ["a person plays the first course without falling"]}}

    def run_prod(self, candidate):
        frames = self.candidate_frames((30, 30, 30))
        return self.run_step(self.docs(candidate, self.baseline(),
                                       play=play_report(candidate, frames=frames)))

    def test_a_persons_blocker_holds_until_confirmed(self):
        self.file(self.accepted, [self.REQUEST])
        held = self.run_prod(self.accepted)
        self.assertEqual(held.outcome, StepOutcome.FAILED)
        self.assertIn("baseline-regression-report:playtest:marble-falls",
                      {f["id"] for f in held.artifacts[0].content["findings"]})
        # a newer build alone does not close it
        newer = commit(self.repo, UNITS, {"src/extra.ts": "x\n"})
        self.assertEqual(self.run_prod(newer).outcome, StepOutcome.FAILED)
        playtest.confirm(self.run_dir, "baseline-regression-report:playtest:marble-falls",
                         build=newer, confirmed_at="t", confirmed_by="human")
        self.assertEqual(self.run_prod(newer).outcome, StepOutcome.SUCCESS)

    def test_a_named_metric_closes_it_on_a_newer_build_only(self):
        self.file(self.accepted, [self.REQUEST], {"marble-falls": "win.inputs"})
        self.assertEqual(self.run_prod(self.accepted).outcome, StepOutcome.FAILED)
        newer = commit(self.repo, UNITS, {"src/extra.ts": "x\n"})
        result = self.run_prod(newer)
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
        note = result.artifacts[0].content["playtest"][0]
        self.assertEqual(note["closed_by"]["kind"], "re-measured")

    def test_notes_that_no_longer_hash_or_were_not_filed_by_a_person_block(self):
        act = self.file(self.accepted, [self.REQUEST])
        with open(os.path.join(self.run_dir, *act["file"].split("/")), "a") as handle:
            handle.write(" ")
        self.assertEqual(self.run_prod(self.accepted).outcome, StepOutcome.BLOCKED)
        shutil.rmtree(os.path.join(self.run_dir, "playtest"))
        raw = json.dumps([self.REQUEST]).encode()
        playtest.file_notes(self.run_dir, raw, build=self.accepted, filed_at="t",
                            filed_by="automation")
        self.assertEqual(self.run_prod(self.accepted).outcome, StepOutcome.BLOCKED)


class Locate(unittest.TestCase):
    def setUp(self):
        self.store = tempfile.mkdtemp(prefix="wgf-locate-")
        self.addCleanup(shutil.rmtree, self.store, ignore_errors=True)

    def write_run(self, run_id, artifacts):
        """artifacts: [(name, type, content)] -> state.json and artifacts/<name>/v<n>.json"""
        run_dir = os.path.join(self.store, run_id)
        index = {}
        for seq, (name, kind, content) in enumerate(artifacts, 1):
            provenance.seal(content)
            version = len(index.get(name, [])) + 1
            location = f"artifacts/{name}/v{version}.json"
            os.makedirs(os.path.join(run_dir, "artifacts", name), exist_ok=True)
            with open(os.path.join(run_dir, location), "w") as handle:
                json.dump(content, handle)
            index.setdefault(name, []).append({
                "type": kind, "location": location, "seq": seq,
                "content_hash": content["provenance"]["content_hash"]})
        with open(os.path.join(run_dir, "state.json"), "w") as handle:
            json.dump({"artifacts": index}, handle)
        return run_dir

    @staticmethod
    def art(kind, aid, title="demo", **body):
        return dict({"provenance": {"artifact_id": aid, "artifact_type": kind,
                                    "title_id": title}}, **body)

    def decision(self, aid, decision, mode, decided_at, pins, title="demo"):
        return self.art("decision-record", aid, title=title, gate_id="G4", decision=decision,
                        decided_by={"role": "portfolio-owner", "mode": mode},
                        decided_at=decided_at, subject=pins)

    @staticmethod
    def pin(content):
        return {"artifact_type": content["provenance"]["artifact_type"],
                "artifact_id": content["provenance"]["artifact_id"],
                "content_hash": content["provenance"]["content_hash"]}

    def test_the_newest_persons_pass_is_the_baseline(self):
        rules = spec()["locate"]
        old_proto = provenance.seal(self.art("prototype-report", "p-old",
                                             build_ref={"commit_sha": "a" * 40}))
        proto = provenance.seal(self.art("prototype-report", "p-new",
                                         build_ref={"commit_sha": "b" * 40}))
        play = provenance.seal(self.art("playability-report", "play", commit="b" * 40))
        vqa = self.art("visual-qa-report", "vqa", commit="b" * 40)
        later = provenance.seal(self.art("prototype-report", "p-later",
                                         build_ref={"commit_sha": "c" * 40}))
        self.write_run("run-old", [
            ("prototype-report", "prototype-report", old_proto),
            ("prototype-report", "prototype-report", proto),
            ("playability-report", "playability-report", play),
            ("visual-qa-report", "visual-qa-report", vqa),
            ("decision-record-prototype-review", "decision-record",
             self.decision("d1", "pass", "human", "2026-10-03T00:00:00Z",
                           [self.pin(old_proto)])),
            ("decision-record-prototype-review", "decision-record",
             self.decision("d2", "pass", "human", "2026-10-04T00:00:00Z",
                           [self.pin(proto), self.pin(play)])),
            ("prototype-report", "prototype-report", later),
            # newer, but not a person's pass: never a baseline
            ("decision-record-prototype-review", "decision-record",
             self.decision("d3", "iterate", "human", "2026-10-05T00:00:00Z",
                           [self.pin(later)])),
            ("decision-record-prototype-review", "decision-record",
             self.decision("d4", "pass", "auto-approved", "2026-10-06T00:00:00Z",
                           [self.pin(later)])),
        ])
        found = locate.find("demo", store=self.store, rules=rules, exclude_run="run-now")
        self.assertEqual(found["commit"], "b" * 40)
        self.assertEqual(found["decision"]["artifact_id"], "d2")
        self.assertEqual(found["reports"]["playability-report"]["pinned_by"], "decision")
        self.assertEqual(found["reports"]["visual-qa-report"]["pinned_by"], "commit")
        self.assertEqual(found["problems"], [])
        self.assertIsNone(locate.find("other-title", store=self.store, rules=rules))

    def test_a_pin_that_no_longer_hashes_is_a_problem(self):
        proto = provenance.seal(self.art("prototype-report", "p",
                                         build_ref={"commit_sha": "b" * 40}))
        play = provenance.seal(self.art("playability-report", "play", commit="b" * 40))
        pin = self.pin(play)
        run_dir = self.write_run("run-old", [
            ("prototype-report", "prototype-report", proto),
            ("playability-report", "playability-report", play),
            ("decision-record-prototype-review", "decision-record",
             self.decision("d", "pass", "human", "2026-10-04T00:00:00Z",
                           [self.pin(proto), pin]))])
        with open(os.path.join(run_dir, "artifacts", "playability-report", "v1.json"),
                  "w") as handle:
            json.dump(dict(play, commit="edited"), handle)
        found = locate.find("demo", store=self.store, rules=spec()["locate"])
        self.assertNotIn("playability-report", found["reports"])
        self.assertTrue(found["problems"])

    def test_the_step_pins_reports_and_frames_into_the_run(self):
        frame_rel = "playability/1-1/out/desktop/frames/play-2s.png"
        old = os.path.join(self.store, "run-old")
        sha = png(os.path.join(old, frame_rel), (10, 20, 30))
        proto = provenance.seal(self.art("prototype-report", "p",
                                         build_ref={"commit_sha": "b" * 40}))
        report = play_report("b" * 40, frames=[{"project": "desktop", "id": "play-2s",
                                                 "path": frame_rel, "sha256": sha}])
        report["provenance"] = {"artifact_id": "play", "artifact_type": "playability-report",
                                "title_id": "demo"}
        provenance.seal(report)
        self.write_run("run-old", [
            ("prototype-report", "prototype-report", proto),
            ("playability-report", "playability-report", report),
            ("decision-record-prototype-review", "decision-record",
             self.decision("d", "pass", "human", "2026-10-04T00:00:00Z",
                           [self.pin(proto), self.pin(report)]))])
        run_dir = os.path.join(self.store, "run-now")
        os.makedirs(run_dir)
        context = types.SimpleNamespace(config={}, run_dir=run_dir, logger=_Log(), visit=1,
                                        attempt=1, execution=1, environment={},
                                        run_id="run-now", project_id="demo")
        step = AcceptedBaselineStep(types.SimpleNamespace(params={}, id="accepted-baseline"))
        result = step.execute(Inputs({"title-strategy": {"title_id": "demo"}}), context)
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.message)
        artifact = result.artifacts[0].content
        self.assertEqual(ArtifactContracts().problems("accepted-baseline", artifact), [])
        self.assertEqual(artifact["status"], "present")
        self.assertEqual(artifact["accepted"]["commit"], "b" * 40)
        copied = os.path.join(run_dir, artifact["frames"][0]["path"])
        self.assertEqual(provenance_sha(copied), sha)
        self.assertEqual(artifact["metrics"]["win.inputs"], {"desktop": 60})
        # a fresh title: nothing accepted, said so
        none = step.execute(Inputs({"title-strategy": {"title_id": "fresh"}}), context)
        self.assertEqual(none.artifacts[0].content["status"], "none")


class QualityGate(unittest.TestCase):
    BUILD = {"commit": "e" * 40, "development_commit": "d" * 40}

    def test_baseline_status(self):
        present = {"status": "present", "accepted": {"commit": "a" * 40}}
        report = {"commit": "d" * 40, "phase": "production", "verdict": "PASS",
                  "provenance": {"artifact_id": "r"}}
        cases = [
            ({}, "SKIPPED"),
            ({"accepted-baseline": {"status": "none", "reason": "fresh"}}, "SKIPPED"),
            ({"accepted-baseline": present}, "UNMEASURED"),
            ({"accepted-baseline": dict(present, status="unmeasured")}, "UNMEASURED"),
            ({"accepted-baseline": present,
              "baseline-regression-report": dict(report, commit="f" * 40)}, "UNMEASURED"),
            ({"accepted-baseline": present,
              "baseline-regression-report": dict(report, phase="greybox")}, "UNMEASURED"),
            ({"accepted-baseline": present,
              "baseline-regression-report": dict(report, verdict="BLOCKED")}, "UNMEASURED"),
            ({"accepted-baseline": present, "baseline-regression-report": report}, "PASS"),
            ({"accepted-baseline": present,
              "baseline-regression-report": dict(report, verdict="FAIL",
                                                 routes=["restore"])}, "FAIL"),
        ]
        for loaded, expected in cases:
            self.assertEqual(baseline_status(loaded, self.BUILD)["status"], expected, loaded)
        failing = baseline_status(cases[-1][0], self.BUILD)
        self.assertEqual(failing["routes"], ["develop"])

    def gate(self, extra):
        from test_quality_gate import Gate, release_build
        docs = release_build()
        docs.update(extra)
        gate = Gate("test_a_build_holding_every_floor_at_release_is_a_release")
        gate.base = tempfile.mkdtemp(prefix="wgf-quality-baseline-")
        self.addCleanup(shutil.rmtree, gate.base, ignore_errors=True)
        return gate.run_step(docs)

    def test_a_baseline_never_measured_on_the_build_blocks_the_release(self):
        result = self.gate({"accepted-baseline": {"status": "present",
                                                  "accepted": {"commit": "a" * 40}}})
        self.assertEqual(result.outcome, StepOutcome.BLOCKED)
        report = result.artifacts[0].content
        self.assertEqual(report["baseline"]["status"], "UNMEASURED")
        self.assertEqual(report["release_decision"]["decision"], "not-release")

    def test_a_failing_baseline_fails_the_gate_routed_through_triage(self):
        result = self.gate({
            "accepted-baseline": {"status": "present", "accepted": {"commit": "a" * 40}},
            "baseline-regression-report": {
                "commit": "d" * 40, "phase": "production", "verdict": "FAIL",
                "failed": ["baseline.paired"], "routes": ["assets"],
                "provenance": {"artifact_id": "r"}}})
        self.assertEqual(result.outcome, StepOutcome.FAILED)
        self.assertEqual(result.route, "assets")
        self.assertEqual(result.artifacts[0].content["release_decision"]["decision"],
                         "not-release")

    def test_no_baseline_changes_nothing(self):
        result = self.gate({"accepted-baseline": {"status": "none", "reason": "fresh"}})
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
        self.assertEqual(result.artifacts[0].content["baseline"]["status"], "SKIPPED")


class Replay(unittest.TestCase):
    """The real reports of both validation games (fixtures/accepted-baseline): what the gate
    would have said about the builds a person judged worse than the ones they accepted."""

    @classmethod
    def setUpClass(cls):
        with open(REAL) as handle:
            cls.real = json.load(handle)["reports"]

    def results(self, game):
        reports = self.real
        accepted = {"playability-report": reports[f"{game}-accepted-playability"],
                    "visual-qa-report": reports[f"{game}-accepted-visual-qa"]}
        candidate = {"playability-report": reports[f"{game}-candidate-playability"]}
        if f"{game}-candidate-visual-qa" in reports:
            candidate["visual-qa-report"] = reports[f"{game}-candidate-visual-qa"]
        return {(r["id"], r["project"]): r for r in metrics.compare(
            spec(), metrics.extract(spec(), accepted), metrics.extract(spec(), candidate))}

    def failed(self, results):
        return sorted(k for k, r in results.items() if r["status"] == "FAIL")

    def test_the_2d_build_a_person_judged_worse_fails(self):
        results = self.results("2d")
        self.assertEqual(results[("win.outcome", "desktop")]["status"], "FAIL")   # won -> lost
        self.assertEqual(results[("win.inputs", "desktop")]["status"], "FAIL")    # 20 -> 3
        self.assertEqual(results[("entity.area.target", "desktop")]["status"], "FAIL")  # x0.52
        self.assertEqual(results[("frame.luminance", "desktop")]["status"], "FAIL")  # +66.6
        self.assertGreaterEqual(len(self.failed(results)), 6)

    def test_the_3d_build_a_person_judged_worse_fails(self):
        results = self.results("3d")
        self.assertEqual(results[("win.inputs", "desktop")]["status"], "FAIL")       # 60 -> 6
        self.assertEqual(results[("frame.luminance", "desktop")]["status"], "FAIL")  # +61.9
        self.assertEqual(results[("entity.area.target", "desktop")]["status"], "FAIL")  # gone
        self.assertEqual(results[("entity.area.goal", "desktop")]["status"], "FAIL")    # x27.5
        self.assertEqual(results[("session.length_ms", "desktop")]["status"], "FAIL")   # x0.46
        # the judge's absolute scores moved within their noise: they alone caught nothing
        self.assertTrue(all(r["status"] == "PASS" for k, r in results.items()
                            if k[0].startswith("vqa.score.")))

    def test_the_replacements_a_person_rejected_exceed_the_maximum(self):
        # measured from the games' repositories (docs/accepted-baseline.md "Calibration"):
        # 2D 96f5cea -> 68a12b7 and 3D 64ff4c6 -> greybox:1 b6b9edb
        maximum = spec()["replacement"]["maximum"]
        rejected = {"2d": {"units_replaced_share": 1.0, "files_rewritten_share": 0.0256,
                           "lines_deleted_share": 0.1145},
                    "3d": {"units_replaced_share": None, "files_rewritten_share": 0.1897,
                           "lines_deleted_share": 0.4618}}
        improving = {"units_replaced_share": 0.0625, "files_rewritten_share": 0.0556,
                     "lines_deleted_share": 0.0842}
        for game, shares in rejected.items():
            self.assertTrue(any(v is not None and v > maximum[k] for k, v in shares.items()),
                            game)
        self.assertFalse(any(v > maximum[k] for k, v in improving.items()))

    def test_the_fixture_reports_are_the_run_stores(self):
        for key, report in self.real.items():
            self.assertTrue(report["source"].startswith(("val-2d/", "val-3d/")), key)
            self.assertRegex(report["provenance"]["content_hash"], r"^sha256:[0-9a-f]{64}$")


class Brief(unittest.TestCase):
    def test_without_approval_the_brief_says_extend(self):
        accepted = {"status": "present", "accepted": {"commit": "a" * 40, "decision": {
            "artifact_id": "d", "decided_at": "t"}}, "metrics": {"win.inputs": {"desktop": 60}},
            "reference": {"version": "1.0.0"}}
        lines = "\n".join(baseline_brief.render(baseline_brief.context(accepted)))
        self.assertIn("Extend the accepted build; do not replace it", lines)
        self.assertIn("`win.inputs`: desktop 60", lines)
        approved = baseline_brief.context(accepted, {"replacement": {"decision": {
            "choice": "approve", "decided_by": "human", "decided_at": "t2"}}})
        self.assertIn("approved replacing it", "\n".join(baseline_brief.render(approved)))
        self.assertIsNone(baseline_brief.context({"status": "none"}))


class Reference(unittest.TestCase):
    def test_every_metric_reads_a_report_and_compares_one_way(self):
        data = spec()
        for metric in data["metrics"]:
            self.assertIn(metric["compare"], ("equal", "ratio", "delta", "drop"), metric["id"])
            self.assertIn("report", metric["read"], metric["id"])
            self.assertIn("basis", metric, metric["id"])
        self.assertEqual(set(data["replacement"]["maximum"]), set(replacement.QUANTITIES))

    def test_the_paired_dimensions_are_the_rubrics(self):
        from wgf_visualqa.rubric import load_rubric
        rubric = load_rubric()
        self.assertTrue(set(spec()["paired"]["baseline_dimensions"])
                        <= set(rubric["dimensions"]))


if __name__ == "__main__":
    unittest.main()

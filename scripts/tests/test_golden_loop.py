"""GOLDEN LOOP: the Factory's closed loop on a real built game, with no LLM.

The 2D golden run (Tower Merge Rush, PixiJS) with the replay developer told to plant the
`restart-dead` defect (scripts/golden/replay_developer.py DEFECTS): the result screen's
restart button plays its click and does not restart. It passes every check the develop step
runs - typecheck, lint, unit tests, the port's own browser tests, which restart through the
window.__game hook - and fails only real play. The production workflow then has to do the
rest on its own:

    greybox builds commit A with the defect -> greybox-playability clones A, builds it, plays
    it in Chromium with real inputs and FAILS restart.works on both viewports, with frames
    -> the workflow routes `fail` back to greybox, whose brief carries that failure -> the
    replay developer, reading the brief, leaves the defect out (a scripted replay, never an
    agent's fix) -> greybox builds commit B -> greybox-playability re-plays the same check on
    B and PASSES it, measured -> the run goes on to its normal golden outcome.

And the negative control: the same run with `--no-repair` keeps planting the defect. The loop
must never report success: greybox's route budget runs out, the run stops BLOCKED with
restart.works still failing, and nothing is released.

Everything is asserted from the run store, the game repository's history and the frames on
disk - not from console output - and a before/after evidence file is written into the golden
evidence directory (golden-loop-2d.json, frames under golden-loop/; scripts/golden/loop.py).

Runs only with WGF_GOLDEN_LOOP=1 (two real golden runs: pnpm, Vite, Playwright, Chromium,
fixed port 4173 - one golden at a time on a machine). SKIPPED otherwise; a skip is never a
pass. Not part of a plain `wgf test-core`: an opt-in category (core_suite.OPT_IN), run by its
own CI job. See docs/golden-runs.md "The golden loop".
"""

import json
import os
import shutil
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
if HERE not in sys.path:
    sys.path.insert(0, HERE)  # testenv, under `python -m unittest scripts.tests.test_golden_loop`

from wgflib import procs  # noqa: E402
from wgflib.workflow.definition import load_definition  # noqa: E402

from golden import harness, loop, replay_developer  # noqa: E402
from golden.browser import sha256_file  # noqa: E402
from testenv import enabled  # noqa: E402

RUN_LOOP = enabled("WGF_GOLDEN_LOOP")
SKIP_REASON = ("the golden loop is two real golden runs (pnpm, vite, Playwright, Chromium; "
               "tens of minutes): set WGF_GOLDEN_LOOP=1 to run it. A skip is not a pass.")
GAME = "2d"
DEFECT = "restart-dead"
CHECK = replay_developer.DEFECTS[DEFECT]["check"]
PROJECTS = loop.PROJECTS
# The statuses that are a measurement. UNMEASURED, SKIPPED, BLOCKED or an absent check never
# count as the repair's PASS.
MEASURED = ("PASS", "FAIL")


def _greybox_route_limit():
    step = load_definition("new-game").step("greybox")
    return step.max_visits_by_route["greybox-playability.fail"]


class _LoopRun:
    """One golden run with the defect, kept until the class is done."""

    repair = True
    browser = True
    workdir = None
    golden = None
    summary = None
    state = None
    store = None

    @classmethod
    def start(cls):
        cls.workdir = harness.make_workdir()
        cls.golden = harness.GoldenRun(GAME, workdir=cls.workdir, defect=DEFECT,
                                    repair=cls.repair, browser=cls.browser)
        try:
            cls.summary = cls.golden.execute()
        finally:
            procs.terminate_all()
        api = cls.golden.api()
        cls.store = api.store
        cls.state = api.store.load(cls.summary["run_id"])

    @classmethod
    def stop(cls):
        if cls.workdir and not enabled("WGF_GOLDEN_KEEP"):
            shutil.rmtree(cls.workdir, ignore_errors=True)

    def explain(self):
        return (f"golden loop evidence: {os.path.join(self.workdir, 'evidence')} "
                f"(set WGF_GOLDEN_KEEP=1 to keep it)")

    # -- read straight from the run store ------------------------------------------------

    def reports(self):
        """Every greybox-playability report, in production order: (ref, content)."""
        refs = loop._reports(self.state)
        return [(ref, self.store.read_artifact(self.state.run_id, ref)) for ref in refs]

    @staticmethod
    def checks(report):
        return {c.get("project"): c for c in report.get("checks") or [] if c.get("id") == CHECK}

    def frame_files(self, report, check):
        paths = {(f.get("project"), f.get("id")): f.get("path")
                 for f in report.get("frames") or []}
        run_dir = self.store.run_dir(self.state.run_id)
        out = []
        for frame_id in check.get("frames") or []:
            relative = paths.get((check.get("project"), frame_id))
            out.append(os.path.join(run_dir, *relative.split("/")) if relative else None)
        return out

    def git_json(self, commit, path):
        shown = procs.run(["git", "-C", self.golden.repo, "show", f"{commit}:{path}"], timeout=60)
        self.assertTrue(shown.ok, f"git show {commit}:{path}: {shown.tail(400)}")
        return json.loads(shown.stdout)

    def developer_defect(self, commit):
        report = self.git_json(commit, replay_developer.REPORT_PATH)
        return (report.get("replay") or {}).get("defect")

    def assert_failed_with_frames(self, report):
        self.assertEqual(report.get("verdict"), "FAIL", self.explain())
        self.assertEqual(report.get("measurement_class"), "automation-bot")
        checks = self.checks(report)
        for project in PROJECTS:
            check = checks.get(project)
            self.assertIsNotNone(check, f"{CHECK} was not measured on {project}")
            self.assertEqual(check["status"], "FAIL", (project, check))
            self.assertTrue(check.get("required"), check)
            files = self.frame_files(report, check)
            self.assertTrue(files, f"{CHECK} on {project} cites no frame")
            for path in files:
                self.assertTrue(path and os.path.isfile(path), (project, path))
            # The dead retry's own frame: the screen the player is left on after the press.
            self.assertIn("retry-dead", check.get("frames") or [], check)
        self.assertIn(CHECK, " ".join(report.get("failed_checks") or []))

    def evidence(self):
        path = os.path.join(self.workdir, "evidence", f"golden-loop-{GAME}.json")
        self.assertTrue(os.path.isfile(path), self.explain())
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)


@unittest.skipUnless(RUN_LOOP, SKIP_REASON)
class GoldenLoop2D(_LoopRun, unittest.TestCase):
    """The defect planted, failed, routed back, repaired, re-played and passed."""

    @classmethod
    def setUpClass(cls):
        cls.start()

    @classmethod
    def tearDownClass(cls):
        cls.stop()

    def test_v1_fails_the_check_on_both_viewports_with_frames_on_commit_a(self):
        reports = self.reports()
        self.assertGreaterEqual(len(reports), 2, self.explain())
        _, first = reports[0]
        self.assert_failed_with_frames(first)
        # The report judged the commit greybox built: A is in the game's history, and the
        # developer record committed with it says the defect was planted.
        commit_a = first["commit"]
        self.assertRegex(commit_a or "", r"^[0-9a-f]{40}$")
        defect = self.developer_defect(commit_a)
        self.assertEqual(defect["status"], "planted", defect)
        self.assertEqual(defect["check"], CHECK)
        self.assertIn("not an agent's fix", defect["label"])

    def test_greybox_was_visited_twice_through_the_playability_route(self):
        greybox = self.state.steps["greybox"]
        played = self.state.steps["greybox-playability"]
        self.assertEqual(greybox.visits, 2, self.explain())
        self.assertEqual(played.visits, 2, self.explain())
        self.assertEqual(greybox.route_visits.get("greybox-playability.fail"), 1,
                         greybox.route_visits)

    def test_the_repair_visit_was_briefed_with_the_failure(self):
        _, first = self.reports()[0]
        _, last = self.reports()[-1]
        brief = self.git_json(last["commit"], "docs/development/brief.json")
        named = {(f.get("check"), f.get("project")) for f in brief.get("playability_failures")
                 or []}
        self.assertEqual({p for c, p in named if c == CHECK}, set(PROJECTS), named)
        self.assertEqual(brief.get("played_commit"), first["commit"])

    def test_v2_passes_the_same_check_measured_on_a_newer_commit_b(self):
        reports = self.reports()
        _, first = reports[0]
        _, last = reports[-1]
        self.assertEqual(len(reports), 2, [r.get("verdict") for _, r in reports])
        self.assertEqual(last.get("verdict"), "PASS", self.explain())
        checks = self.checks(last)
        for project in PROJECTS:
            check = checks.get(project)
            self.assertIsNotNone(check, f"{CHECK} absent on {project}: not a measurement")
            self.assertIn(check["status"], MEASURED, check)
            self.assertEqual(check["status"], "PASS", (project, check))
            self.assertIsNotNone((check.get("measured") or {}).get("playingMs"), check)
            self.assertTrue((check.get("measured") or {}).get("reset"), check)
        commit_a, commit_b = first["commit"], last["commit"]
        self.assertNotEqual(commit_a, commit_b)
        self.assertTrue(loop.descends(self.golden.repo, commit_a, commit_b),
                        f"{commit_b} does not descend from {commit_a}")
        defect = self.developer_defect(commit_b)
        self.assertEqual(defect["status"], "repaired", defect)
        self.assertEqual(defect["failures_named"], sorted(PROJECTS))

    def test_the_run_reaches_its_normal_golden_outcome(self):
        failed = [f"{s['step']}: {s['status']} {s['message']}"
                  for s in self.summary["steps"] if not s["reached"]]
        self.assertEqual(failed, [], self.explain())
        self.assertEqual(self.summary["run_status"], "COMPLETED", self.explain())
        self.assertTrue(self.summary["passed"], self.explain())
        self.assertTrue(self.summary["browser_passed"], self.explain())
        # The production develop visit lays the port as it is: the defect is greybox's only.
        developed = [ref for versions in self.state.artifacts.values() for ref in versions
                     if ref.type == "prototype-report" and ref.produced_by == "develop"]
        self.assertTrue(developed, self.explain())
        for ref in developed:
            report = self.store.read_artifact(self.state.run_id, ref)
            defect = self.developer_defect(report["build_ref"]["commit_sha"])
            self.assertEqual(defect["status"], "not-applied", defect)

    def test_the_before_after_evidence_file(self):
        record = self.evidence()
        self.assertTrue(record["closed"], record["reasons"])
        self.assertEqual(record["reasons"], [])
        self.assertEqual((record["defect"], record["check"]), (DEFECT, CHECK))
        before, after = record["before"], record["after"]
        reports = self.reports()
        self.assertEqual(before["commit"], reports[0][1]["commit"])
        self.assertEqual(after["commit"], reports[-1][1]["commit"])
        self.assertEqual((before["verdict"], after["verdict"]), ("FAIL", "PASS"))
        self.assertEqual((before["developer"], after["developer"]), ("planted", "repaired"))
        evidence_dir = os.path.join(self.workdir, "evidence")
        for side, status in ((before, "FAIL"), (after, "PASS")):
            for project in PROJECTS:
                entry = side["projects"][project]
                self.assertEqual(entry["status"], status)
                self.assertTrue(entry["viewport"], entry)
                self.assertTrue(entry["frames"], entry)
                for frame in entry["frames"]:
                    copied = os.path.join(evidence_dir, *frame["evidence"].split("/"))
                    self.assertTrue(os.path.isfile(copied), copied)
                    self.assertEqual(sha256_file(copied), frame["sha256"])
        self.assertEqual(record["visits"], {"greybox": 2, "greybox-playability": 2})

    def test_no_process_outlived_the_run(self):
        self.assertEqual(self.summary["leftover_processes"], [])
        self.assertFalse(procs.live_groups())


@unittest.skipUnless(RUN_LOOP, SKIP_REASON)
class GoldenLoopNoRepair2D(_LoopRun, unittest.TestCase):
    """The negative control: a developer that never repairs never closes the loop."""

    repair = False
    browser = False  # the run never reaches develop: there is no game to play from outside

    @classmethod
    def setUpClass(cls):
        cls.start()

    @classmethod
    def tearDownClass(cls):
        cls.stop()

    def test_the_run_does_not_succeed(self):
        self.assertNotEqual(self.summary["run_status"], "COMPLETED", self.explain())
        self.assertIn(self.summary["run_status"], ("BLOCKED", "FAILED"), self.explain())
        self.assertFalse(self.summary["passed"])
        for step in ("assets", "develop", "release"):
            st = self.state.steps.get(step)
            self.assertTrue(st is None or st.status != "SUCCESS", (step, st and st.status))

    def test_the_greybox_route_budget_ran_out(self):
        limit = _greybox_route_limit()
        greybox = self.state.steps["greybox"]
        self.assertEqual(greybox.visits, 1 + limit, self.explain())
        self.assertEqual(greybox.route_visits.get("greybox-playability.fail"), limit,
                         greybox.route_visits)
        if self.summary["run_status"] == "BLOCKED":
            reason = self.state.blocked_reason or {}
            self.assertEqual(reason.get("kind"), "loop-limit", reason)
            self.assertEqual(reason.get("step"), "greybox", reason)

    def test_every_report_still_fails_the_check(self):
        reports = self.reports()
        self.assertEqual(len(reports), 1 + _greybox_route_limit(), self.explain())
        for _, report in reports:
            self.assert_failed_with_frames(report)
            defect = self.developer_defect(report["commit"])
            self.assertEqual(defect["status"], "planted", defect)
            self.assertFalse(defect["repair"])
        # Later visits were briefed with the failure and planted it anyway.
        later = [self.developer_defect(r["commit"]) for _, r in reports[1:]]
        self.assertTrue(all(d["failures_named"] == sorted(PROJECTS) for d in later), later)

    def test_the_evidence_does_not_claim_a_closed_loop(self):
        record = self.evidence()
        self.assertFalse(record["closed"])
        self.assertTrue(record["reasons"])
        self.assertEqual(record["after"]["verdict"], "FAIL")

    def test_no_process_outlived_the_run(self):
        self.assertEqual(self.summary["leftover_processes"], [])
        self.assertFalse(procs.live_groups())


if __name__ == "__main__":
    unittest.main()

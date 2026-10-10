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

THE DEVELOP STAGE (`--defect-stage develop`): the same defect planted in the first PRODUCTION
develop visit instead, the greybox clean. A production failure goes through triage, so this
variant exercises the run's finding ledger on a real build:

    develop builds commit A with the defect -> playability FAILS restart.works on both
    viewports -> triage normalizes the two failures into findings
    playability-report:restart.works@desktop/@mobile and assigns them to the specialist that
    owns them (core/reference/specialist-routing.yaml) -> develop, entered as that
    specialist, is briefed with the findings -> the replay leaves the defect out -> commit B
    -> playability PASSES the same check, measured -> the gates, G4, release -> and the
    ledger (the quality-report's) holds each finding verified or closed, its fix commit B,
    its verification `passed` with the failing measurement of A and the passing one of B of
    the same scenario, the frames on disk with their sha256, and nothing open.

Its negative control (`--no-repair`) plants the defect on every develop visit: playability
fails each time, triage's `playability.fail` budget runs out and the run stops BLOCKED; the
ledger never verifies the finding.

Everything is asserted from the run store, the game repository's history and the frames on
disk - not from console output - and a before/after evidence file is written into the golden
evidence directory (golden-loop-2d.json, frames under golden-loop/; scripts/golden/loop.py).

Runs only with WGF_GOLDEN_LOOP=1 (four real golden runs: pnpm, Vite, Playwright, Chromium,
fixed port 4173 - one golden at a time on a machine). SKIPPED otherwise; a skip is never a
pass. WGF_GOLDEN_LOOP_DIR=<dir> runs each class in <dir>/<class key> - and a class whose
directory already holds a finished run's summary (a kept run.py --workdir of the same
variant) is asserted on that run instead of running again: the assertions read only the run
store, git and files, which a kept run still holds. Not part of a plain `wgf test-core`: an opt-in category (core_suite.OPT_IN), run by its
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
SKIP_REASON = ("the golden loop is four real golden runs (pnpm, vite, Playwright, Chromium; "
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


def _triage_playability_limit():
    step = load_definition("new-game").step("triage")
    return step.max_visits_by_route["playability.fail"]


def _owner_of(check):
    """The specialist core/reference/specialist-routing.yaml makes owner of a playability
    check (read through the routing data's own reader)."""
    from wgf_triage.routing import Routing
    routing = Routing.load()
    table = routing.producer("playability-report").get("checks") or {}
    return routing.owner(routing.resolve_word(table[check]))


class _LoopRun:
    """One golden run with the defect, kept until the class is done."""

    repair = True
    browser = True
    stage = None  # replay_developer.STAGES; None = the defect's own phase (greybox)
    key = None    # the class's directory under WGF_GOLDEN_LOOP_DIR
    workdir = None
    golden = None
    summary = None
    state = None
    store = None
    reused = False

    @classmethod
    def start(cls):
        root = os.environ.get("WGF_GOLDEN_LOOP_DIR")
        cls.workdir = (os.path.join(root, cls.key) if root and cls.key
                       else harness.make_workdir())
        os.makedirs(cls.workdir, exist_ok=True)
        cls.golden = harness.GoldenRun(GAME, workdir=cls.workdir, defect=DEFECT,
                                    repair=cls.repair, browser=cls.browser,
                                    defect_stage=cls.stage)
        finished = os.path.join(cls.golden.evidence_dir, f"golden-{GAME}.json")
        if root and os.path.isfile(finished):
            # A kept run of this variant: asserted as it is, never run again.
            with open(finished, encoding="utf-8") as handle:
                cls.summary = json.load(handle)
            cls.reused = True
        else:
            try:
                cls.summary = cls.golden.execute()
            finally:
                procs.terminate_all()
        api = cls.golden.api()
        cls.store = api.store
        cls.state = api.store.load(cls.summary["run_id"])

    @classmethod
    def stop(cls):
        if cls.workdir and not cls.reused and not enabled("WGF_GOLDEN_KEEP"):
            shutil.rmtree(cls.workdir, ignore_errors=True)

    def explain(self):
        return (f"golden loop evidence: {os.path.join(self.workdir, 'evidence')} "
                f"(set WGF_GOLDEN_KEEP=1 to keep it)")

    # -- read straight from the run store ------------------------------------------------

    def reports(self):
        """Every report of the step that plays the stage's build (greybox-playability, or
        playability for the develop stage), in production order: (ref, content)."""
        refs = loop._reports(self.state, loop.STEPS[self.stage][1])
        return [(ref, self.store.read_artifact(self.state.run_id, ref)) for ref in refs]

    def artifacts(self, kind):
        """Every artifact of `kind`, in production order: (ref, content)."""
        refs = loop._of_type(self.state, kind)
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
        path = os.path.join(self.workdir, "evidence",
                            f"golden-loop-{loop.evidence_key(GAME, self.stage)}.json")
        self.assertTrue(os.path.isfile(path), self.explain())
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)


@unittest.skipUnless(RUN_LOOP, SKIP_REASON)
class GoldenLoop2D(_LoopRun, unittest.TestCase):
    """The defect planted, failed, routed back, repaired, re-played and passed."""

    key = "greybox"

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
    key = "greybox-no-repair"

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


def _ids():
    return [loop.finding_id(CHECK, p) for p in PROJECTS]


def _sha_ok(run_dir, frame):
    relative = frame.get("path") or ""
    path = os.path.join(run_dir, *relative.split("/"))
    return os.path.isfile(path) and (sha256_file(path).split(":")[-1]
                                     == str(frame.get("sha256") or "").split(":")[-1])


@unittest.skipUnless(RUN_LOOP, SKIP_REASON)
class GoldenLoopDevelop2D(_LoopRun, unittest.TestCase):
    """The develop stage: planted in production, failed by playability, normalized and
    assigned by triage, repaired by the specialist visit it routed, re-played and passed -
    and verified by the run's own finding ledger."""

    stage = "develop"
    key = "develop"

    @classmethod
    def setUpClass(cls):
        cls.start()

    @classmethod
    def tearDownClass(cls):
        cls.stop()

    def pair(self):
        """(report of commit A, report of commit B): the first playability report, and the
        one that played the visit which repaired the defect."""
        reports = [r for _, r in self.reports()]
        self.assertGreaterEqual(len(reports), 2, self.explain())
        repaired = [r for r in reports[1:]
                    if (self.developer_defect(r["commit"]) or {}).get("status") == "repaired"]
        self.assertTrue(repaired, self.explain())
        return reports[0], repaired[0]

    def ledger(self):
        """The newest ledger: the quality-report's `ledger` block."""
        quality = self.artifacts("quality-report")
        self.assertTrue(quality, self.explain())
        return quality[-1][1]["ledger"]

    def test_the_greybox_is_clean(self):
        greybox = self.state.steps["greybox"]
        self.assertEqual(greybox.visits, 1, self.explain())
        played = [r for _, r in self.reports_of("greybox-playability")]
        self.assertEqual([r["verdict"] for r in played], ["PASS"])
        self.assertEqual(self.developer_defect(played[0]["commit"])["status"], "not-applied")

    def reports_of(self, step):
        refs = loop._reports(self.state, step)
        return [(ref, self.store.read_artifact(self.state.run_id, ref)) for ref in refs]

    def test_v1_fails_the_check_on_both_viewports_on_production_commit_a(self):
        first, _ = self.pair()
        self.assert_failed_with_frames(first)
        defect = self.developer_defect(first["commit"])
        self.assertEqual((defect["status"], defect["stage"], defect["phase"]),
                         ("planted", "develop", "production"), defect)
        self.assertIn("not an agent's fix", defect["label"])

    def test_triage_assigned_both_findings_to_their_owner(self):
        owner = _owner_of(CHECK)
        triaged = self.artifacts("triage-report")
        routed = [c for _, c in triaged
                  if set(_ids()) <= set((c.get("selected") or {}).get("findings") or [])]
        self.assertEqual(len(routed), 1, [(c.get("selected") or {}) for _, c in triaged])
        selected = routed[0]["selected"]
        self.assertEqual((selected["owner"], selected["label"]), (owner, owner))
        records = {r["id"]: r for r in routed[0]["lifecycle"]}
        for fid in _ids():
            record = records[fid]
            self.assertEqual(record["owner"], owner)
            self.assertEqual([h["status"] for h in record["history"]],
                             ["detected", "classified", "assigned"], record["history"])
            self.assertEqual(record["source"]["check"], CHECK)
        develop = self.state.steps["develop"]
        self.assertEqual(develop.route_visits.get(f"triage.{owner}"), 1,
                         develop.route_visits)
        self.assertEqual(self.state.steps["triage"].route_visits.get("playability.fail"), 1)

    def test_the_repair_visit_was_briefed_as_the_specialist_with_the_findings(self):
        first, last = self.pair()
        brief = self.git_json(last["commit"], "docs/development/brief.json")
        specialist = brief.get("specialist") or {}
        self.assertEqual(specialist.get("role"), _owner_of(CHECK))
        self.assertEqual(sorted(f["id"] for f in specialist.get("findings") or []), _ids())
        defect = self.developer_defect(last["commit"])
        self.assertEqual(defect["status"], "repaired", defect)
        self.assertEqual(defect["findings_named"], _ids())
        self.assertEqual(defect["failures_named"], sorted(PROJECTS))
        self.assertIn("not an agent's fix", defect["label"])
        self.assertTrue(loop.descends(self.golden.repo, first["commit"], last["commit"]))

    def test_v2_passes_the_same_check_measured_on_newer_commit_b(self):
        first, last = self.pair()
        self.assertEqual(last["verdict"], "PASS", self.explain())
        checks = self.checks(last)
        for project in PROJECTS:
            check = checks.get(project)
            self.assertIsNotNone(check, f"{CHECK} absent on {project}: not a measurement")
            self.assertEqual(check["status"], "PASS", (project, check))
            self.assertIsNotNone((check.get("measured") or {}).get("playingMs"), check)
            self.assertTrue((check.get("measured") or {}).get("reset"), check)
        self.assertNotEqual(first["commit"], last["commit"])

    def test_the_ledger_verified_the_repair_on_the_same_scenario(self):
        first, last = self.pair()
        ledger = self.ledger()
        self.assertEqual(ledger["open"], [], ledger["open"])
        records = {r["id"]: r for r in ledger["lifecycle"]}
        run_dir = self.store.run_dir(self.state.run_id)
        for fid in _ids():
            record = records[fid]
            project = fid.rsplit("@", 1)[-1]
            statuses = [h["status"] for h in record["history"]]
            self.assertIn(record["status"], ("verified", "closed"), record)
            for wanted in ("detected", "assigned", "implemented", "verified"):
                self.assertIn(wanted, statuses, statuses)
            implemented = [h for h in record["history"] if h["status"] == "implemented"]
            self.assertEqual(implemented[-1]["build"], last["commit"])
            self.assertEqual(record["fix"]["commit"], last["commit"], record["fix"])
            verification = record["verification"]
            self.assertEqual(verification["verdict"], "passed", verification)
            before, after = verification["before"], verification["after"]
            self.assertEqual((before["commit"], before["status"]), (first["commit"], "FAIL"))
            self.assertEqual((after["commit"], after["status"]), (last["commit"], "PASS"))
            self.assertEqual(before["scenario"]["id"], f"{CHECK}@{project}")
            self.assertEqual(after["scenario"]["id"], before["scenario"]["id"])
            comparison = verification["comparison"]
            self.assertTrue(comparison["same_scenario"], comparison)
            self.assertGreaterEqual(len(verification.get("samples") or []), 1)
            for side in (before, after):
                self.assertTrue(side["frames"], side)
                for frame in side["frames"]:
                    self.assertTrue(_sha_ok(run_dir, frame), frame)

    def test_the_assessment_holds_the_repair_and_does_not_pass_player_facing_quality(self):
        """Runtime correctness rests on the repaired check, measured PASS, and nothing of it
        FAILs. It is not asserted PASS: on the golden port browser QA's oracle checks
        (browser.win, .lose, .restart, the audio and context-menu checks) report WARNING -
        the design states no win, bad play does not lose within 90 s - and the assessment
        reads a WARNING as measured nothing (INCONCLUSIVE, never a pass; measured
        2026-10-09). Player-facing quality is never passed by automation."""
        quality = self.artifacts("quality-report")[-1][1]
        dimensions = {d["id"]: d for d in quality["assessment"]["dimensions"]}
        runtime = dimensions["runtime_correctness"]
        self.assertIn(runtime["status"], ("PASS", "INCONCLUSIVE"), runtime["reason"])
        checks = {c["check"]: c for c in runtime["checks"]}
        self.assertEqual(checks[f"playability:{CHECK}"]["status"], "PASS",
                         checks.get(f"playability:{CHECK}"))
        self.assertEqual([c for c in runtime["checks"] if c["status"] == "FAIL"], [])
        if runtime["status"] == "PASS":
            self.assertIn(runtime.get("basis"), ("measured", "qualified", "weak"), runtime)
        self.assertNotEqual(dimensions["player_facing"]["status"], "PASS",
                            dimensions["player_facing"])
        self.assertNotEqual(dimensions["player_facing"]["status"], "FAIL",
                            dimensions["player_facing"])

    def test_the_run_reaches_its_normal_golden_outcome(self):
        failed = [f"{s['step']}: {s['status']} {s['message']}"
                  for s in self.summary["steps"] if not s["reached"]]
        self.assertEqual(failed, [], self.explain())
        self.assertEqual(self.summary["run_status"], "COMPLETED", self.explain())
        self.assertTrue(self.summary["passed"], self.explain())
        self.assertTrue(self.summary["browser_passed"], self.explain())

    def test_the_before_after_evidence_file_carries_the_ledger(self):
        record = self.evidence()
        self.assertTrue(record["closed"], record["reasons"])
        self.assertEqual(record["reasons"], [])
        self.assertEqual((record["stage"], record["defect"], record["check"]),
                         ("develop", DEFECT, CHECK))
        first, last = self.pair()
        self.assertEqual((record["before"]["commit"], record["after"]["commit"]),
                         (first["commit"], last["commit"]))
        self.assertEqual((record["before"]["developer"], record["after"]["developer"]),
                         ("planted", "repaired"))
        self.assertTrue(record["ledger"]["verified"], record["ledger"]["reasons"])
        self.assertEqual(record["ledger"]["owners"], [_owner_of(CHECK)])
        for fid in _ids():
            final = record["ledger"]["final"][fid]
            self.assertIn(final["status"], ("verified", "closed"))
            for side in ("before", "after"):
                self.assertTrue(all(f["exists"] and f["matches"]
                                    for f in final["frames_on_disk"][side]), final)
        self.assertTrue(record["assessment"], record)
        evidence_dir = os.path.join(self.workdir, "evidence")
        for side in (record["before"], record["after"]):
            for project in PROJECTS:
                for frame in side["projects"][project]["frames"]:
                    copied = os.path.join(evidence_dir, *frame["evidence"].split("/"))
                    self.assertEqual(sha256_file(copied), frame["sha256"])

    def test_no_process_outlived_the_run(self):
        self.assertEqual(self.summary["leftover_processes"], [])
        self.assertFalse(procs.live_groups())


@unittest.skipUnless(RUN_LOOP, SKIP_REASON)
class GoldenLoopDevelopNoRepair2D(_LoopRun, unittest.TestCase):
    """The develop stage's negative control: the specialist visit never repairs, so the
    ledger never verifies the finding and the run stops at triage's playability budget."""

    stage = "develop"
    key = "develop-no-repair"
    repair = False
    browser = False  # a defective build: nothing is released to play from outside

    @classmethod
    def setUpClass(cls):
        cls.start()

    @classmethod
    def tearDownClass(cls):
        cls.stop()

    def test_the_run_stops_blocked_at_triages_playability_budget(self):
        self.assertEqual(self.summary["run_status"], "BLOCKED", self.explain())
        self.assertFalse(self.summary["passed"])
        reason = self.state.blocked_reason or {}
        self.assertEqual(reason.get("kind"), "loop-limit", reason)
        self.assertEqual(reason.get("step"), "triage", reason)
        limit = _triage_playability_limit()
        self.assertEqual(self.state.steps["triage"].route_visits.get("playability.fail"),
                         limit, self.state.steps["triage"].route_visits)
        for step in ("production-quality", "quality-gate", "release"):
            st = self.state.steps.get(step)
            self.assertTrue(st is None or st.status != "SUCCESS", (step, st and st.status))

    def test_every_report_still_fails_and_every_visit_planted_it(self):
        reports = self.reports()
        self.assertEqual(len(reports), 1 + _triage_playability_limit(), self.explain())
        for _, report in reports:
            self.assert_failed_with_frames(report)
            defect = self.developer_defect(report["commit"])
            self.assertEqual((defect["status"], defect["repair"]), ("planted", False), defect)
        later = [self.developer_defect(r["commit"]) for _, r in reports[1:]]
        self.assertTrue(all(d["findings_named"] == _ids() for d in later), later)

    def test_the_ledger_never_verifies_the_finding(self):
        triaged = self.artifacts("triage-report")
        self.assertTrue(triaged, self.explain())
        for _, content in triaged:
            for record in content.get("lifecycle") or []:
                if record.get("id") in _ids():
                    statuses = [h["status"] for h in record["history"]]
                    self.assertNotIn("verified", statuses, record["id"])
                    self.assertNotIn(record["status"], ("verified", "closed"))
        newest = {r["id"]: r for r in triaged[-1][1]["lifecycle"]}
        for fid in _ids():
            self.assertIn(fid, newest)
            self.assertEqual((newest[fid].get("verification") or {}).get("verdict"),
                             "still-failing", newest[fid].get("verification"))
        for _, content in self.artifacts("quality-report"):
            for record in (content.get("ledger") or {}).get("lifecycle") or []:
                if record.get("id") in _ids():
                    self.assertNotIn(record["status"], ("verified", "closed"))

    def test_the_evidence_does_not_claim_a_closed_loop(self):
        record = self.evidence()
        self.assertFalse(record["closed"])
        self.assertTrue(record["reasons"])
        self.assertEqual(record["after"]["verdict"], "FAIL")
        self.assertFalse(record["ledger"]["verified"])
        held, reasons = loop.control_held(record)
        self.assertTrue(held, reasons)

    def test_no_process_outlived_the_run(self):
        self.assertEqual(self.summary["leftover_processes"], [])
        self.assertFalse(procs.live_groups())


if __name__ == "__main__":
    unittest.main()

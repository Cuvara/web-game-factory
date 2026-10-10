"""The golden harness's always-on checks, for both golden games. No node, no browser.

The harness configuration, the frozen fixtures, the research -> G3 slice of the real
workflow steering to the right engine, the replay developer's mapping onto the template's
examples, the port overlays' static conformance, and the golden reviewer on a throwaway
repository. The overlays (examples/*/wgf-golden, examples/wgf-golden-shared) are read from
the pinned template checkout: the Factory holds no game source, and a pin that does not ship
them fails here.

Kept out of test_golden_2d/3d on purpose: those are the 2D/3D GOLDEN categories of
`wgf test-core`, and a category that passed only these fast checks would read as PASS
without the pipeline having run. The real runs are the WGF_GOLDEN=1 cases there.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from golden import games, harness, loop, replay_developer  # noqa: E402
from golden.testing import fast_case  # noqa: E402
from wgflib import procs  # noqa: E402

Golden2DFast = fast_case("2d")
Golden3DFast = fast_case("3d")


class GoldenTestingImports(unittest.TestCase):
    def test_it_imports_without_the_tests_directory_on_sys_path(self):
        """`python -m unittest scripts.tests.test_golden_2d` puts only the repository root
        on sys.path, not scripts/tests where testenv lives; golden.testing must find it."""
        scripts = os.path.dirname(HERE)
        code = (f"import sys; sys.path.insert(0, {scripts!r}); "
                f"assert not any(p.rstrip('/').endswith('tests') for p in sys.path), sys.path; "
                f"import golden.testing")
        done = subprocess.run([sys.executable, "-I", "-c", code], cwd=os.path.dirname(scripts),
                              capture_output=True, text=True, timeout=120)
        self.assertEqual(done.returncode, 0, done.stderr)


class GoldenLoopFast(unittest.TestCase):
    """The golden loop's machinery without a run: the defect table against the pinned port,
    the plant/repair decision read from a brief, the loud refusals, the harness argv, and
    the before/after record over a synthetic run store and a real git history."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="wgf-golden-loop-fast-")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_every_defect_anchor_occurs_exactly_once_in_the_pinned_port(self):
        if not harness.PORTS_DIR:
            self.skipTest("the golden ports commit cannot be checked out")
        for name, spec in replay_developer.DEFECTS.items():
            with self.subTest(name):
                port = replay_developer.load_port(spec["game"])
                files = dict(replay_developer.port_files(port, harness.PORTS_DIR))
                self.assertIn(spec["file"], files)
                with open(files[spec["file"]], encoding="utf-8") as handle:
                    text = handle.read()
                planted = replay_developer.apply_defect(spec, text)
                self.assertNotEqual(planted, text)
                for old, new in spec["rewrites"]:
                    self.assertEqual(text.count(old), 1)
                    self.assertEqual(planted.count(old), 0)
        # restart-dead keeps the click and drops only the restart call of the UI action.
        spec = replay_developer.DEFECTS["restart-dead"]
        self.assertEqual(spec["check"], "restart.works")
        old, new = spec["rewrites"][0]
        self.assertIn("void app.restart();", old)
        self.assertNotIn("app.restart", new)
        self.assertIn("click();", new)

    def test_a_missing_or_repeated_anchor_refuses_loudly(self):
        spec = replay_developer.DEFECTS["restart-dead"]
        old = spec["rewrites"][0][0]
        for text in ("export {};\n", old + old):
            with self.subTest(len(text)):
                with self.assertRaises(replay_developer.ReplayError) as caught:
                    replay_developer.apply_defect(spec, text)
                self.assertIn("not exactly once", str(caught.exception))

    def test_an_unknown_or_foreign_defect_is_refused(self):
        with self.assertRaises(replay_developer.ReplayError):
            replay_developer.defect_spec("no-such-defect", "2d")
        with self.assertRaises(replay_developer.ReplayError):
            replay_developer.defect_spec("restart-dead", "3d")

    def test_planted_unless_the_brief_names_the_check_then_repaired(self):
        spec = replay_developer.DEFECTS["restart-dead"]

        def decide(failures, phase="greybox", repair=True):
            brief = {"phase": phase, "iteration": 2, "played_commit": "a" * 40,
                     "playability_failures": failures}
            return replay_developer.defect_decision("restart-dead", spec, brief, repair)

        named = [{"check": "restart.works", "project": "mobile"},
                 {"check": "restart.works", "project": "desktop"}]
        other = [{"check": "win.reachable", "project": "desktop"}]
        self.assertEqual(decide([])["status"], "planted")
        self.assertEqual(decide(other)["status"], "planted")
        repaired = decide(named)
        self.assertEqual(repaired["status"], "repaired")
        self.assertEqual(repaired["failures_named"], ["desktop", "mobile"])
        self.assertIn("not an agent's fix", repaired["label"])
        kept = decide(named, repair=False)
        self.assertEqual((kept["status"], kept["repair"]), ("planted", False))
        self.assertIn("negative control", kept["reason"])
        self.assertEqual(decide([], phase="production")["status"], "not-applied")
        self.assertEqual(decide(named, phase="production")["status"], "not-applied")

    def test_the_report_records_what_the_visit_did(self):
        port = replay_developer.load_port("2d")
        spec = replay_developer.DEFECTS["restart-dead"]
        decision = replay_developer.defect_decision(
            "restart-dead", spec, {"phase": "greybox", "playability_failures": []})
        brief = {"engine": port["engine"], "mvp": [], "placements": [], "assets": [],
                 "required_systems": []}
        report = replay_developer.build_report(brief, port, [], defect=decision)
        self.assertEqual(report["replay"]["defect"]["status"], "planted")
        self.assertIn("not an AI developer", report["replay"]["developer"])
        self.assertNotIn("defect", replay_developer.build_report(brief, port, [])["replay"])

    def test_the_harness_asks_for_the_defect_only_when_told(self):
        game = games.game("2d")
        argv = harness.developer_argv(game, "python")
        self.assertNotIn("--defect", argv)
        argv = harness.developer_argv(game, "python", defect="restart-dead")
        self.assertEqual(argv[-2:], ["--defect", "restart-dead"])
        argv = harness.developer_argv(game, "python", defect="restart-dead", repair=False)
        self.assertEqual(argv[-3:], ["--defect", "restart-dead", "--no-repair"])
        with self.assertRaises(ValueError):
            harness.developer_argv(game, "python", repair=False)
        with self.assertRaises(replay_developer.ReplayError):
            harness.developer_argv(games.game("3d"), "python", defect="restart-dead")
        config = harness.build_config(game, self.tmp, harness.TEMPLATE_DIR,
                                      defect="restart-dead")
        self.assertIn("--defect", config["develop"]["developer"]["argv"])

    # -- the before/after record ---------------------------------------------------------

    def _repo(self, statuses):
        """A git repository with one commit per developer status; [sha...]."""
        repo = os.path.join(self.tmp, "repo")
        os.makedirs(repo)
        git = lambda *a: procs.run(["git", "-C", repo, *a], timeout=30)  # noqa: E731
        self.assertTrue(git("init", "-q").ok)
        git("config", "user.email", "golden@example.invalid")
        git("config", "user.name", "golden")
        commits = []
        for n, status in enumerate(statuses, 1):
            path = os.path.join(repo, *replay_developer.REPORT_PATH.split("/"))
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as handle:
                json.dump({"replay": {"defect": {"status": status, "iteration": n,
                                                 "label": replay_developer.DEFECT_LABEL,
                                                 "failures_named": [], "repair": True}}},
                          handle)
            git("add", "-A")
            git("commit", "-q", "-m", f"visit {n}")
            commits.append(git("rev-parse", "HEAD").stdout.strip())
        return repo, commits

    def _run(self, verdicts, commits, greybox_visits):
        from wgflib.workflow.model import ArtifactRef, StepState

        run_dir = os.path.join(self.tmp, "run")
        reports = {}
        refs = []
        for n, ((verdict, status), commit) in enumerate(zip(verdicts, commits), 1):
            frames, checks = [], []
            for project in loop.PROJECTS:
                rel = f"greybox-playability/{n}-1/out/{project}/frames/end-lost.png"
                path = os.path.join(run_dir, *rel.split("/"))
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "wb") as handle:
                    handle.write(f"{n}{project}".encode())
                frames.append({"project": project, "id": "end-lost", "path": rel})
                checks.append({"id": "restart.works", "project": project, "required": True,
                               "status": status, "frames": ["end-lost"]})
            reports[f"r{n}"] = {
                "commit": commit, "verdict": verdict, "checks": checks, "frames": frames,
                "measurement_class": "automation-bot",
                "projects": [{"id": p, "viewport": {"width": 1, "height": 1}}
                             for p in loop.PROJECTS],
                "failed_checks": [f"{p}:restart.works" for p in loop.PROJECTS
                                  if status == "FAIL"]}
            refs.append(ArtifactRef(id=f"r{n}", type="playability-report", version=1,
                                    location=f"r{n}.json", checksum="x", seq=n,
                                    produced_by="greybox-playability"))

        class Store:
            def run_dir(self, run_id):
                return run_dir

            def read_artifact(self, run_id, ref):
                return reports[ref.id]

        class State:
            run_id, status, message, blocked_reason = "run-1", "COMPLETED", None, None
            artifacts = {ref.id: [ref] for ref in refs}
            steps = {"greybox": StepState(visits=greybox_visits),
                     "greybox-playability": StepState(visits=len(refs))}

        return Store(), State()

    def test_a_closed_loop_is_recorded_and_its_frames_copied(self):
        repo, commits = self._repo(["planted", "repaired"])
        store, state = self._run([("FAIL", "FAIL"), ("PASS", "PASS")], commits, 2)
        record = loop.record(store, state, repo, "restart-dead")
        self.assertEqual(record["reasons"], [])
        self.assertTrue(record["closed"])
        self.assertEqual((record["before"]["commit"], record["after"]["commit"]),
                         tuple(commits))
        evidence = os.path.join(self.tmp, "evidence")
        path = loop.write(record, store.run_dir("run-1"), evidence, "2d")
        with open(path, encoding="utf-8") as handle:
            written = json.load(handle)
        for side in ("before", "after"):
            for project in loop.PROJECTS:
                frame = written[side]["projects"][project]["frames"][0]
                copied = os.path.join(evidence, *frame["evidence"].split("/"))
                self.assertTrue(os.path.isfile(copied))
                self.assertRegex(frame["sha256"], r"^sha256:[0-9a-f]{64}$")

    def test_a_loop_that_did_not_close_says_why(self):
        cases = {
            "never repaired": (["planted", "planted"], [("FAIL", "FAIL"), ("FAIL", "FAIL")], 2),
            "a pass the developer did not repair": (
                ["planted", "planted"], [("FAIL", "FAIL"), ("PASS", "PASS")], 2),
            "an unmeasured pass": (["planted", "repaired"],
                                   [("FAIL", "FAIL"), ("PASS", "UNMEASURED")], 2),
            "no failure first": (["planted", "repaired"], [("PASS", "PASS"), ("PASS", "PASS")],
                                 2),
            "never routed back": (["planted", "repaired"], [("FAIL", "FAIL"), ("PASS", "PASS")],
                                  1),
            "nothing re-played": (["planted"], [("FAIL", "FAIL")], 1),
        }
        outer = self.tmp
        for name, (statuses, verdicts, visits) in cases.items():
            with self.subTest(name):
                # A fresh directory per case (git's read-only objects outlive rmtree on
                # Windows); setUp's cleanup removes the lot.
                self.tmp = tempfile.mkdtemp(dir=outer)
                repo, commits = self._repo(statuses)
                store, state = self._run(verdicts, commits, visits)
                record = loop.record(store, state, repo, "restart-dead")
                self.assertFalse(record["closed"], name)
                self.assertTrue(record["reasons"], name)

    def test_the_same_commit_twice_is_not_a_newer_one(self):
        repo, commits = self._repo(["planted", "repaired"])
        self.assertTrue(loop.descends(repo, commits[0], commits[1]))
        self.assertFalse(loop.descends(repo, commits[1], commits[0]))
        self.assertFalse(loop.descends(repo, commits[0], commits[0]))

    # -- the develop stage: planted in production, repaired by the triaged specialist ------

    @staticmethod
    def _specialist_brief(findings, phase="production", role="ui"):
        return {"phase": phase, "iteration": 2, "played_commit": None,
                "playability_failures": [],
                "specialist": {"role": role, "triage_report": "triage-report-x",
                               "findings": findings}}

    @staticmethod
    def _finding(check="restart.works", project="desktop", producer="playability-report"):
        return {"id": f"{producer}:{check}@{project}",
                "source": {"producer": producer, "check": check, "project": project}}

    def test_the_develop_stage_plants_in_production_and_leaves_greybox_clean(self):
        spec = replay_developer.DEFECTS["restart-dead"]
        decide = replay_developer.defect_decision
        self.assertEqual(replay_developer.STAGES, {"greybox": "greybox",
                                                   "develop": "production"})
        greybox = decide("restart-dead", spec, {"phase": "greybox"}, stage="develop")
        self.assertEqual(greybox["status"], "not-applied")
        first = decide("restart-dead", spec, {"phase": "production", "iteration": 1},
                       stage="develop", prior=greybox)
        self.assertEqual(first["status"], "planted")
        self.assertEqual((first["stage"], first["specialist"], first["findings_named"]),
                         ("develop", None, []))
        self.assertIn("not an agent's fix", first["label"])
        # Without a stage the greybox default is unchanged: production is not-applied.
        self.assertEqual(decide("restart-dead", spec, {"phase": "production"})["status"],
                         "not-applied")
        self.assertNotIn("stage", decide("restart-dead", spec, {"phase": "greybox"}))
        with self.assertRaises(replay_developer.ReplayError):
            decide("restart-dead", spec, {"phase": "production"}, stage="sdk")

    def test_the_develop_stage_repairs_only_on_the_specialists_finding_of_the_check(self):
        spec = replay_developer.DEFECTS["restart-dead"]

        def decide(brief, repair=True, prior=None):
            return replay_developer.defect_decision("restart-dead", spec, brief, repair,
                                                    stage="develop", prior=prior)

        named = [self._finding(project="mobile"), self._finding(project="desktop")]
        repaired = decide(self._specialist_brief(named))
        self.assertEqual(repaired["status"], "repaired")
        self.assertEqual(repaired["failures_named"], ["desktop", "mobile"])
        self.assertEqual(repaired["findings_named"],
                         ["playability-report:restart.works@desktop",
                          "playability-report:restart.works@mobile"])
        self.assertEqual((repaired["specialist"], repaired["triage_report"]),
                         ("ui", "triage-report-x"))
        self.assertIn("ui specialist", repaired["reason"])
        # Another check, or the same check id from another producer, names nothing.
        for other in ([self._finding(check="win.reachable")],
                      [self._finding(producer="production-quality-report")], []):
            with self.subTest(other):
                self.assertEqual(decide(self._specialist_brief(other))["status"], "planted")
        # The negative control keeps planting it, briefed or not.
        kept = decide(self._specialist_brief(named), repair=False)
        self.assertEqual((kept["status"], kept["repair"]), ("planted", False))
        self.assertIn("negative control", kept["reason"])
        # A later visit that names nothing keeps the repair; the control never has one.
        later = decide(self._specialist_brief([], role="sdk"), prior=repaired)
        self.assertEqual(later["status"], "kept-repaired")
        self.assertEqual(decide({"phase": "production"}, prior=later)["status"],
                         "kept-repaired")
        self.assertEqual(decide({"phase": "production"}, repair=False,
                                prior=repaired)["status"], "planted")
        self.assertEqual(decide({"phase": "production"}, prior=kept)["status"], "planted")
        other_defect = dict(repaired, name="another-defect")
        self.assertEqual(decide({"phase": "production"}, prior=other_defect)["status"],
                         "planted")

    def test_the_prior_record_is_read_from_the_checkout(self):
        repo = os.path.join(self.tmp, "checkout")
        self.assertIsNone(replay_developer.prior_defect(repo))
        path = os.path.join(repo, *replay_developer.REPORT_PATH.split("/"))
        os.makedirs(os.path.dirname(path))
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({"replay": {"defect": {"name": "restart-dead", "status": "repaired"}}},
                      handle)
        self.assertEqual(replay_developer.prior_defect(repo)["status"], "repaired")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("not json")
        self.assertIsNone(replay_developer.prior_defect(repo))

    def test_the_harness_passes_the_stage_only_when_told(self):
        game = games.game("2d")
        argv = harness.developer_argv(game, "python", defect="restart-dead", stage="develop")
        self.assertEqual(argv[-4:], ["--defect", "restart-dead", "--defect-stage", "develop"])
        argv = harness.developer_argv(game, "python", defect="restart-dead", repair=False,
                                      stage="develop")
        self.assertEqual(argv[-3:], ["--defect-stage", "develop", "--no-repair"])
        self.assertNotIn("--defect-stage",
                         harness.developer_argv(game, "python", defect="restart-dead"))
        with self.assertRaises(ValueError):
            harness.developer_argv(game, "python", stage="develop")
        with self.assertRaises(replay_developer.ReplayError):
            harness.developer_argv(game, "python", defect="restart-dead", stage="release")
        config = harness.build_config(game, self.tmp, harness.TEMPLATE_DIR,
                                      defect="restart-dead", defect_stage="develop")
        self.assertIn("--defect-stage", config["develop"]["developer"]["argv"])
        self.assertEqual(loop.evidence_key("2d"), "2d")
        self.assertEqual(loop.evidence_key("2d", "greybox"), "2d")
        self.assertEqual(loop.evidence_key("2d", "develop"), "2d-develop")
        self.assertEqual(loop.STEPS["develop"], ("develop", "playability"))

    def _develop_run(self, verdicts, commits, ledger_status="closed", verdict="passed",
                     same_scenario=True, fix_commit=None, open_ids=(), route_visits=None):
        """A synthetic run store of the develop stage: playability reports, a triage-report
        that assigned the findings to `ui`, and a quality-report whose ledger holds them."""
        from wgflib.workflow.model import ArtifactRef, StepState

        run_dir = os.path.join(self.tmp, "run")
        contents, refs = {}, []
        seq = 0
        measurements = {}
        for n, ((report_verdict, status), commit) in enumerate(zip(verdicts, commits), 1):
            seq += 1
            frames, checks, scenarios = [], [], []
            for project in loop.PROJECTS:
                rel = f"playability/{n}-1/out/{project}/frames/end-lost.png"
                path = os.path.join(run_dir, *rel.split("/"))
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "wb") as handle:
                    handle.write(f"{n}{project}".encode())
                digest = "sha256:" + __import__("hashlib").sha256(
                    f"{n}{project}".encode()).hexdigest()
                frames.append({"project": project, "id": "end-lost", "path": rel})
                checks.append({"id": "restart.works", "project": project, "required": True,
                               "status": status, "frames": ["end-lost"],
                               "scenario": f"restart.works@{project}"})
                measurements[(n, project)] = {
                    "commit": commit, "status": status, "check": "restart.works",
                    "project": project, "seq": seq,
                    "scenario": {"id": f"restart.works@{project}", "bot_version": "1"},
                    "frames": [{"id": "end-lost", "path": rel, "sha256": digest}]}
            contents[f"p{n}"] = {
                "commit": commit, "verdict": report_verdict, "checks": checks,
                "frames": frames, "scenarios": scenarios,
                "measurement_class": "automation-bot",
                "projects": [{"id": p, "viewport": {"width": 1, "height": 1}}
                             for p in loop.PROJECTS],
                "failed_checks": [f"{p}:restart.works" for p in loop.PROJECTS
                                  if status == "FAIL"]}
            refs.append(ArtifactRef(id=f"p{n}", type="playability-report", version=1,
                                    location=f"p{n}.json", checksum="x", seq=seq,
                                    produced_by="playability"))

        def ledger_record(project, status):
            fid = loop.finding_id("restart.works", project)
            history = [{"status": s} for s in ("detected", "classified", "assigned")]
            record = {"id": fid, "owner": "ui", "status": status, "history": history,
                      "fix": None, "verification": None}
            if status in ("verified", "closed"):
                record["history"] = history + [{"status": s} for s in
                                               ("implemented", "verified", "closed")
                                               ][:2 if status == "verified" else 3]
                record["fix"] = {"specialist": "ui", "commit": fix_commit or commits[-1]}
                record["verification"] = {
                    "verdict": verdict, "before": measurements[(1, project)],
                    "after": measurements[(len(commits), project)],
                    "comparison": {"same_scenario": same_scenario, "note": "n"},
                    "samples": [{"status": "PASS"}]}
            return record

        seq += 1
        contents["t1"] = {"selected": {"label": "ui", "owner": "ui",
                                       "findings": [loop.finding_id("restart.works", p)
                                                    for p in loop.PROJECTS]},
                          "lifecycle": [ledger_record(p, "assigned") for p in loop.PROJECTS]}
        refs.append(ArtifactRef(id="t1", type="triage-report", version=1, location="t1.json",
                                checksum="x", seq=1, produced_by="triage"))
        seq += 1
        contents["q1"] = {"ledger": {"open": list(open_ids), "awaiting": [],
                                     "lifecycle": [ledger_record(p, ledger_status)
                                                   for p in loop.PROJECTS]},
                          "assessment": {"dimensions": [
                              {"id": "runtime_correctness", "status": "PASS",
                               "basis": "qualified"},
                              {"id": "player_facing", "status": "INCONCLUSIVE"}]}}
        refs.append(ArtifactRef(id="q1", type="quality-report", version=1, location="q1.json",
                                checksum="x", seq=seq, produced_by="quality-gate"))

        class Store:
            def run_dir(self, run_id):
                return run_dir

            def read_artifact(self, run_id, ref):
                return contents[ref.id]

        visits = route_visits if route_visits is not None else {"triage.ui": 1}

        class State:
            run_id, status, message, blocked_reason = "run-1", "COMPLETED", None, None
            artifacts = {ref.id: [ref] for ref in refs}
            steps = {"develop": StepState(visits=len(commits), route_visits=dict(visits)),
                     "playability": StepState(visits=len(commits))}

        return Store(), State()

    def test_a_develop_loop_closes_only_when_the_ledger_verifies_the_repair(self):
        repo, commits = self._repo(["planted", "repaired"])
        store, state = self._develop_run([("FAIL", "FAIL"), ("PASS", "PASS")], commits)
        record = loop.record(store, state, repo, "restart-dead", stage="develop")
        self.assertEqual(record["reasons"], [])
        self.assertTrue(record["closed"])
        self.assertEqual(record["stage"], "develop")
        self.assertEqual(record["visits"], {"develop": 2, "playability": 2})
        self.assertEqual(record["ledger"]["owners"], ["ui"])
        self.assertTrue(record["ledger"]["verified"])
        self.assertEqual([d["id"] for d in record["assessment"]],
                         ["runtime_correctness", "player_facing"])
        for fid in record["ledger"]["ids"]:
            final = record["ledger"]["final"][fid]
            self.assertEqual(final["status"], "closed")
            for side in ("before", "after"):
                self.assertTrue(all(f["exists"] and f["matches"]
                                    for f in final["frames_on_disk"][side]))
        evidence = os.path.join(self.tmp, "evidence")
        path = loop.write(record, store.run_dir("run-1"), evidence, "2d-develop")
        self.assertTrue(path.endswith("golden-loop-2d-develop.json"))

        cases = {
            "the ledger left it implemented": dict(ledger_status="implemented"),
            "a verification that did not pass": dict(verdict="still-failing"),
            "another scenario": dict(same_scenario=False),
            "a fix commit that is not the repair": dict(fix_commit=commits[0]),
            "listed open by the quality gate": dict(
                open_ids=[loop.finding_id("restart.works", "mobile")]),
            "never routed to its owner": dict(route_visits={}),
        }
        outer = self.tmp
        for name, kwargs in cases.items():
            with self.subTest(name):
                self.tmp = tempfile.mkdtemp(dir=outer)
                store, state = self._develop_run([("FAIL", "FAIL"), ("PASS", "PASS")],
                                                 commits, **kwargs)
                record = loop.record(store, state, repo, "restart-dead", stage="develop")
                self.assertFalse(record["closed"], name)
                self.assertTrue(any(r.startswith("ledger: ") for r in record["reasons"]),
                                record["reasons"])
        self.tmp = outer

    def test_a_frame_whose_digest_changed_does_not_verify(self):
        repo, commits = self._repo(["planted", "repaired"])
        store, state = self._develop_run([("FAIL", "FAIL"), ("PASS", "PASS")], commits)
        path = os.path.join(store.run_dir("run-1"), "playability", "2-1", "out", "mobile",
                            "frames", "end-lost.png")
        with open(path, "wb") as handle:
            handle.write(b"another frame")
        record = loop.record(store, state, repo, "restart-dead", stage="develop")
        self.assertFalse(record["closed"])
        self.assertTrue(any("sha256" in r for r in record["reasons"]), record["reasons"])

    def test_the_develop_loop_reads_the_repairing_report_not_a_later_one(self):
        repo, commits = self._repo(["planted", "repaired", "kept-repaired"])
        store, state = self._develop_run(
            [("FAIL", "FAIL"), ("PASS", "PASS"), ("PASS", "PASS")], commits,
            fix_commit=None)
        record = loop.record(store, state, repo, "restart-dead", stage="develop")
        self.assertEqual(record["after"]["commit"], commits[1])
        self.assertEqual(record["after"]["developer"], "repaired")

    # -- the negative control's exit status (run.py) -------------------------------------

    def _main_with(self, loop_record, no_repair=True):
        """run.main's exit status for a run whose summary carries `loop_record`."""
        from unittest import mock
        from golden import run as runner

        summary = {"passed": False, "browser_passed": False, "run_id": "run-1",
                   "run_status": "BLOCKED", "duration_s": 1, "steps": [],
                   "engine": {"consistent": True}, "release": None,
                   "golden_loop": loop_record}

        class Fake:
            def __init__(self, *args, **kwargs):
                self.game = games.game("2d")
                self.workdir = "w"

            def execute(self, **kwargs):
                return summary

            def cleanup(self):
                pass

        argv = ["--game", "2d", "--defect", "restart-dead", "--json"]
        if no_repair:
            argv.append("--no-repair")
        with mock.patch.object(runner.harness, "GoldenRun", Fake), \
                mock.patch("sys.stdout", new_callable=__import__("io").StringIO), \
                mock.patch("sys.stderr", new_callable=__import__("io").StringIO):
            return runner.main(argv)

    @staticmethod
    def _control_version(n, verdict="FAIL", status="FAIL", developer="planted"):
        return {"version": n, "commit": f"{n}" * 40, "verdict": verdict,
                "check_status": {p: status for p in loop.PROJECTS},
                "developer": {"status": developer, "repair": False}}

    def test_a_negative_control_never_passes_on_a_record_that_could_not_be_read(self):
        unreadable = {"kind": "golden-loop", "defect": "restart-dead", "repair": False,
                      "closed": False, "versions": [],
                      "reasons": ["the loop record could not be read: KeyError('x')"]}
        self.assertEqual(self._main_with(unreadable), 1)
        held = {"closed": False, "reasons": ["never repaired"],
                "versions": [self._control_version(n) for n in (1, 2, 3)]}
        self.assertEqual(self._main_with(held), 0)
        for name, versions in {
            "a passing report": [self._control_version(1),
                                 self._control_version(2, "PASS", "PASS")],
            "the check passing on one project": [
                self._control_version(1),
                dict(self._control_version(2), check_status={"desktop": "FAIL",
                                                             "mobile": "PASS"})],
            "a visit that did not plant it": [self._control_version(1),
                                              self._control_version(2, developer="repaired")],
            "no developer record": [dict(self._control_version(1), developer=None)],
        }.items():
            with self.subTest(name):
                self.assertEqual(self._main_with({"closed": False, "reasons": ["x"],
                                                  "versions": versions}), 1)
        self.assertEqual(loop.control_held(held), (True, []))
        ok, reasons = loop.control_held(unreadable)
        self.assertFalse(ok)
        self.assertTrue(reasons)


if __name__ == "__main__":
    unittest.main()

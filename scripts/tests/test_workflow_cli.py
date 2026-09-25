"""End to end: the `wgf` CLI, the engine, the mock steps and the file store, together.

Every test runs scripts/wgf.py as a subprocess against a temporary store, exactly as a person
would, and then reads the store back. These are the acceptance tests for the workflow
kernel: the full mock workflow, every individual command, retry, permanent failure and
resume, the human checkpoint, and the verification loop.

Deterministic and offline: mock steps only, backoff sleeps skipped in mock runs, no network.

Run from the web-game-factory repository root:

    python -m unittest discover scripts/tests
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
WGF = os.path.join(SCRIPTS, "wgf.py")
FIXTURES = os.path.join(HERE, "fixtures", "workflows")

sys.path.insert(0, SCRIPTS)

from wgflib.hashing import content_hash  # noqa: E402
from wgflib.workflow.model import RunStatus  # noqa: E402
from wgflib.workflow.store import RunStore  # noqa: E402

# A mock new-game approves G2 and G3 itself and waits at G4 (prototype-review), which only a
# person decides: its trail holds the wait and then the pass.
NEW_GAME = ["research", "strategy", "strategy-review", "design", "tech-plan", "tech-plan-review",
            "init", "assets", "develop", "review", "sdk", "sdk-review", "verify",
            "prototype-review", "prototype-review", "release"]
SCHEMATIZED = {
    "research": "opportunity",
    "strategy": "title-strategy",
    "design": "game-design",
    "tech-plan": "tech-plan",
    "assets": "asset-manifest",
    "develop": "prototype-report",
    "verify": "qa-report",
    "release": "release-manifest",
    "init": "scaffold-record",
    "sdk": "sdk-report",
}


class CliCase(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.mkdtemp(prefix="wgf-cli-")
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)
        self.store = os.path.join(self.scratch, "store")
        self.config = os.path.join(self.scratch, "factory.yaml")
        with open(self.config, "w", encoding="utf-8") as handle:
            handle.write("factory:\n  storage:\n    fsync: false\n")

    def wgf(self, *args, expect=0, env=None, cwd=ROOT, store=True):
        command = [sys.executable, WGF, *args,
                   *(("--store", self.store) if store else ()), "--config", self.config]
        env = dict(os.environ, PYTHONIOENCODING="utf-8", **(env or {}))
        done = subprocess.run(command, cwd=cwd, capture_output=True, text=True,
                              encoding="utf-8", env=env)
        if expect is not None:
            self.assertEqual(done.returncode, expect,
                             f"wgf {' '.join(args)}\n{done.stdout}\n{done.stderr}")
        return done

    def state(self, run_id=None):
        """Read the persisted state directly. `wgf status` is tested on its own; spawning it
        for every inspection only multiplies interpreter start-up (see docs/workflow-engine.md,
        Known limits)."""
        store = RunStore(self.store, fsync=False)
        state = store.load(run_id) if run_id else store.latest()
        return state.to_dict()

    def artifact(self, state, artifact_id, version=None):
        versions = state["artifacts"][artifact_id]
        ref = versions[-1] if version is None else versions[version - 1]
        path = os.path.join(self.store, "workflows", state["run_id"], *ref["location"].split("/"))
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)

    def statuses(self, state):
        return {step: entry["status"] for step, entry in state["steps"].items()}

    def pass_g4(self, run_id=None, expect=0, quiet=True):
        """A mock new-game stops at G4 (irreversible: no mock or config approves it). Answer
        it as the person at the terminal does - `wgf decide <run> pass`."""
        run_id = run_id or self.state()["run_id"]
        state = self.state(run_id)
        self.assertEqual((state["status"], state["cursor"]), ("WAITING", "prototype-review"))
        return self.wgf("decide", run_id, "pass", *(("--quiet",) if quiet else ()),
                        expect=expect)


class MockNewGame(CliCase):
    def test_runs_every_step_without_being_told_the_order(self):
        done = self.wgf("new-game", "--mock", expect=3)
        self.assertIn("pass|iterate|kill", done.stdout)
        done = self.pass_g4(quiet=False)
        self.assertIn("Workflow completed successfully.", done.stdout)
        state = self.state()
        self.assertEqual(state["status"], "COMPLETED")
        self.assertEqual([t["step"] for t in state["trail"]], NEW_GAME)
        self.assertEqual(set(self.statuses(state).values()), {"SUCCESS"})

    def test_emits_an_artifact_per_step_with_reproducible_provenance(self):
        self.wgf("new-game", "--mock", expect=3)
        self.pass_g4()
        state = self.state()
        for step, artifact_type in SCHEMATIZED.items():
            with self.subTest(step):
                artifact = self.artifact(state, artifact_type)
                provenance = artifact["provenance"]
                self.assertEqual(provenance["artifact_type"], artifact_type)
                self.assertEqual(provenance["content_hash"], content_hash(artifact))
                self.assertEqual(state["artifacts"][artifact_type][-1]["content_hash"],
                                 provenance["content_hash"])
                schema_path = os.path.join(ROOT, "core", "artifacts",
                                           f"{artifact_type}.schema.json")
                with open(schema_path, encoding="utf-8") as handle:
                    required = json.load(handle)["required"]
                self.assertEqual([k for k in required if k not in artifact], [])

    def test_downstream_artifacts_pin_their_inputs_by_hash(self):
        self.wgf("new-game", "--mock", expect=3)
        self.pass_g4()
        state = self.state()
        opportunity = self.artifact(state, "opportunity")
        strategy = self.artifact(state, "title-strategy")
        self.assertEqual(strategy["provenance"]["inputs"], [{
            "artifact_id": opportunity["provenance"]["artifact_id"],
            "artifact_type": "opportunity",
            "content_hash": opportunity["provenance"]["content_hash"],
        }])

    def test_without_mock_there_are_no_implementations(self):
        done = self.wgf("new-game", expect=2)
        self.assertIn("--mock", done.stderr)


class IndividualCommands(CliCase):
    def test_each_command_runs_only_its_slice(self):
        expected = {
            "research": ["research"],
            "plan": ["strategy", "strategy-review", "design", "tech-plan", "tech-plan-review"],
            "init": ["init"],
            "assets": ["assets"],
            "develop": ["develop"],
            "sdk": ["sdk"],
            "verify": ["verify"],
            "release": ["release"],
        }
        for command, steps in expected.items():
            with self.subTest(command):
                self.wgf(command, "--mock", "--quiet")
                state = self.state()
                self.assertEqual(state["scope"], steps)
                self.assertEqual([t["step"] for t in state["trail"]], steps)
                self.assertEqual(state["status"], "COMPLETED")

    def test_commands_chain_inside_one_run_and_do_not_redo_work(self):
        self.wgf("plan", "--mock", "--quiet")
        run_id = self.state()["run_id"]
        self.wgf("init", "--run", run_id, "--quiet")
        self.wgf("init", "--run", run_id, "--quiet")
        state = self.state(run_id)
        self.assertEqual(state["steps"]["init"]["executions"], 1)
        self.assertEqual(len(state["artifacts"]["scaffold-record"]), 1)
        events = [json.loads(line) for line in
                  self.wgf("logs", run_id, "--json").stdout.splitlines()]
        self.assertIn("STEP_SKIPPED", [e["event"] for e in events])

        # And the rest of the workflow, from where the slices left off.
        self.wgf("new-game", "--run", run_id, "--quiet", expect=3)
        self.pass_g4(run_id)
        state = self.state(run_id)
        self.assertEqual(state["status"], "COMPLETED")
        self.assertEqual(state["steps"]["strategy"]["executions"], 1)
        self.assertEqual(state["steps"]["release"]["status"], "SUCCESS")


class FailureAndResume(CliCase):
    def test_retry_then_success(self):
        self.wgf("new-game", "--mock", "--quiet", "--mock-plan", '{"develop": ["failed"]}',
                 expect=3)
        self.pass_g4()
        state = self.state()
        self.assertEqual(state["status"], "COMPLETED")
        self.assertEqual(state["steps"]["develop"]["executions"], 2)
        self.assertEqual([t["outcome"] for t in state["trail"] if t["step"] == "develop"],
                         ["FAILED", "SUCCESS"])

    def test_permanent_failure_then_resume_without_redoing_earlier_steps(self):
        done = self.wgf("new-game", "--mock", "--mock-plan",
                        '{"develop": ["failed", "failed", "failed"]}', expect=1)
        self.assertIn("Status: FAILED", done.stdout)
        state = self.state()
        self.assertEqual(state["status"], "FAILED")
        self.assertEqual(state["cursor"], "develop")
        self.assertEqual(state["steps"]["develop"]["executions"], 3)
        self.assertNotIn("sdk", state["steps"])
        events = [json.loads(l) for l in self.wgf("logs", "--json").stdout.splitlines()]
        names = [e["event"] for e in events]
        self.assertEqual(names.count("STEP_RETRIED"), 2)
        self.assertEqual(names[-1], "WORKFLOW_FAILED")

        self.wgf("new-game", "--resume", state["run_id"], "--quiet", expect=3)
        self.pass_g4(state["run_id"])
        resumed = self.state(state["run_id"])
        self.assertEqual(resumed["status"], "COMPLETED")
        for step in ("research", "strategy", "design", "init", "assets"):
            self.assertEqual(resumed["steps"][step]["executions"], 1, step)
        self.assertEqual(resumed["steps"]["develop"]["executions"], 4)

    def test_verification_failure_loops_back_to_development(self):
        self.wgf("new-game", "--mock", "--quiet", "--mock-plan", '{"verify": ["fail"]}',
                 expect=3)
        self.pass_g4()
        state = self.state()
        self.assertEqual(state["status"], "COMPLETED")
        self.assertEqual([t["step"] for t in state["trail"]][8:],
                         ["develop", "review", "sdk", "sdk-review", "verify", "develop",
                          "review", "sdk", "sdk-review", "verify", "prototype-review",
                          "prototype-review", "release"])
        self.assertEqual(self.artifact(state, "qa-report", 1)["verdict"], "fail")
        self.assertEqual(self.artifact(state, "qa-report", 2)["verdict"], "pass")
        self.assertEqual(self.artifact(state, "prototype-report", 2)["iteration"], 2)

    def test_sdk_review_requesting_changes_loops_back_to_development(self):
        # The sdk commit is reviewed too; a request for changes goes back to develop,
        # never on to verify.
        self.wgf("new-game", "--mock", "--quiet", "--mock-plan",
                 '{"sdk-review": ["request-changes"]}', expect=3)
        self.pass_g4()
        state = self.state()
        self.assertEqual(state["status"], "COMPLETED")
        self.assertEqual([t["step"] for t in state["trail"]][8:],
                         ["develop", "review", "sdk", "sdk-review", "develop", "review", "sdk",
                          "sdk-review", "verify", "prototype-review", "prototype-review",
                          "release"])
        rejected = self.artifact(state, "review-report", 2)
        self.assertEqual(rejected["verdict"], "request-changes")
        # Both mock reviews approve the commit their subject names.
        approved = self.artifact(state, "review-report", 4)
        sdk = self.artifact(state, "sdk-report", 2)
        self.assertEqual(approved["verdict"], "approve")
        self.assertEqual(approved["reviewed_commit"], sdk["build_ref"]["commit_sha"])
        develop_review = self.artifact(state, "review-report", 3)
        prototype = self.artifact(state, "prototype-report", 2)
        self.assertEqual(develop_review["reviewed_commit"],
                         prototype["build_ref"]["commit_sha"])

    def test_human_checkpoint_waits_then_resumes(self):
        done = self.wgf("new-game", "--mock", "--hold-gates", expect=3)
        self.assertIn(f"wgf decide {self.state()['run_id']} approve|reject", done.stdout)
        state = self.state()
        self.assertEqual(state["status"], "WAITING")
        self.assertEqual(state["cursor"], "strategy-review")
        self.assertNotIn("design", state["steps"])

        self.wgf("new-game", "--resume", state["run_id"], "--decision", "approve",
                 "--note", "ok", "--quiet", expect=3)
        state = self.state(state["run_id"])
        self.assertEqual(state["status"], "WAITING")
        self.assertEqual(state["cursor"], "tech-plan-review")  # G3, before the repository
        self.assertNotIn("init", state["steps"])

        self.wgf("new-game", "--resume", state["run_id"], "--decision", "approve",
                 "--note", "ok", "--quiet", expect=3)
        self.pass_g4(state["run_id"])
        state = self.state(state["run_id"])
        self.assertEqual(state["status"], "COMPLETED")
        self.assertEqual(state["decisions"]["strategy-review"]["decided_by"], "human")
        self.assertEqual(state["decisions"]["tech-plan-review"]["decided_by"], "human")

    def test_rejection_blocks_and_can_be_reconsidered(self):
        self.wgf("new-game", "--mock", "--hold-gates", "--quiet", expect=3)
        run_id = self.state()["run_id"]
        self.wgf("new-game", "--resume", run_id, "--decision", "reject", "--quiet", expect=1)
        self.assertEqual(self.state(run_id)["status"], "BLOCKED")
        self.wgf("new-game", "--resume", run_id, "--decision", "approve", "--quiet", expect=3)
        self.wgf("new-game", "--resume", run_id, "--decision", "approve", "--quiet", expect=3)
        self.pass_g4(run_id)
        self.assertEqual(self.state(run_id)["status"], "COMPLETED")


class FixtureWorkflows(CliCase):
    """The acceptance workflows in scripts/tests/fixtures/workflows."""

    def fixture(self, name):
        return os.path.join(FIXTURES, f"{name}.workflow.yaml")

    def test_verify_loop(self):
        self.wgf("verify-loop", "--workflow", self.fixture("verify-loop"), "--mock", "--quiet",
                 "--mock-plan", '{"verify": ["fail", "pass"]}')
        state = self.state()
        self.assertEqual([t["step"] for t in state["trail"]],
                         ["develop", "verify", "develop", "verify", "release"])

    def test_human_checkpoint_with_a_routed_choice(self):
        self.wgf("human-checkpoint", "--workflow", self.fixture("human-checkpoint"), "--mock",
                 "--quiet", expect=3)
        run_id = self.state()["run_id"]
        self.wgf("human-checkpoint", "--workflow", self.fixture("human-checkpoint"),
                 "--resume", run_id, "--decision", "rework", "--quiet", expect=3)
        self.wgf("human-checkpoint", "--workflow", self.fixture("human-checkpoint"),
                 "--resume", run_id, "--decision", "approve", "--quiet")
        state = self.state(run_id)
        self.assertEqual([t["step"] for t in state["trail"]],
                         ["research", "strategy", "review", "review", "strategy", "review",
                          "review", "design"])

    def test_retry_exhaustion(self):
        self.wgf("retry", "--workflow", self.fixture("retry"), "--mock", "--quiet",
                 "--mock-plan", '{"develop": ["failed", "raise", "fatal"]}', expect=1)
        state = self.state()
        self.assertEqual(state["status"], "FAILED")
        self.assertEqual(state["steps"]["develop"]["attempts"], 3)
        self.assertNotIn("release", state["steps"])


class StatusAndLogs(CliCase):
    def test_status_renders_from_state(self):
        self.wgf("new-game", "--mock", "--quiet", "--mock-plan",
                 '{"develop": ["fatal"]}', expect=1)
        run_id = self.state()["run_id"]
        for args in ((), (run_id,)):
            out = self.wgf("status", *args, expect=1).stdout  # the run's own exit code
            self.assertIn(f"Run:      {run_id}", out)
            self.assertIn("Status: FAILED", out)
            self.assertIn("develop", out)
            self.assertIn("<- next", out)
            self.assertIn(f"wgf resume {run_id}", out)

    def test_logs_are_structured(self):
        self.wgf("research", "--mock", "--quiet")
        lines = self.wgf("logs", "--json").stdout.splitlines()
        events = [json.loads(line) for line in lines]
        for event in events:
            for key in ("ts", "event", "workflow_id", "run_id"):
                self.assertIn(key, event)
        names = {e["event"] for e in events}
        self.assertTrue({"WORKFLOW_STARTED", "STEP_STARTED", "STEP_COMPLETED",
                         "ARTIFACT_CREATED", "WORKFLOW_COMPLETED"} <= names)

    def test_runs_lists_every_run(self):
        self.wgf("research", "--mock", "--quiet")
        self.wgf("verify", "--mock", "--quiet")
        self.assertEqual(len(self.wgf("runs").stdout.strip().splitlines()), 2)

    def test_status_with_no_runs(self):
        self.assertIn("no runs", self.wgf("status", expect=2).stdout)

    def test_unknown_run(self):
        self.assertIn("no run", self.wgf("status", "nope", expect=2).stderr)


class RunStatesThroughTheCli(CliCase):
    """status and logs read persisted state and events, for a run in every status."""

    def crash(self, run_id, cursor):
        """Leave a run RUNNING on disk with no process behind it, as a crash would."""
        store = RunStore(self.store, fsync=False)
        state = store.load(run_id)
        state.status, state.cursor = RunStatus.RUNNING, cursor
        store.save(state)

    def status_line(self, run_id):
        return [l for l in self.wgf("status", run_id, expect=None).stdout.splitlines()
                if l.startswith("Status:")][0]

    def test_running_paused_and_resume_after_pause(self):
        self.wgf("init", "--mock", "--quiet")
        run_id = self.state()["run_id"]
        self.crash(run_id, "init")
        self.assertEqual(self.status_line(run_id), "Status: RUNNING")

        self.assertIn("PAUSED", self.wgf("pause", run_id).stdout)
        self.assertEqual(self.status_line(run_id), "Status: PAUSED")
        self.assertIn("WORKFLOW_PAUSED", self.wgf("logs", run_id).stdout)

        self.wgf("init", "--resume", run_id, "--quiet")
        self.assertEqual(self.status_line(run_id), "Status: COMPLETED")

    def test_pause_refuses_a_run_that_is_not_running(self):
        self.wgf("research", "--mock", "--quiet")
        self.assertIn("not RUNNING", self.wgf("pause", self.state()["run_id"], expect=2).stderr)

    def test_cancelled(self):
        self.wgf("new-game", "--mock", "--hold-gates", "--quiet", expect=3)
        run_id = self.state()["run_id"]
        self.assertIn("CANCELLED", self.wgf("cancel", run_id).stdout)
        self.assertEqual(self.status_line(run_id), "Status: CANCELLED")
        self.assertIn("WORKFLOW_CANCELLED", self.wgf("logs", run_id).stdout)
        self.wgf("new-game", "--resume", run_id, expect=2)

    def test_blocked_by_the_loop_limit_then_resumed(self):
        # verify fails on every pass; new-game's develop takes two `fail` loops per start or
        # resume (max_visits_by_route), and the third blocks - on that route, as data.
        done = self.wgf("new-game", "--mock", "--quiet", "--mock-plan",
                        '{"verify": ["fail", "fail", "fail", "fail"]}', expect=1)
        self.assertIn("loop limit", done.stdout)
        state = self.state()
        self.assertEqual(state["status"], "BLOCKED")
        self.assertEqual(state["steps"]["verify"]["visits"], 3)
        self.assertEqual(state["blocked_reason"], {
            "kind": "loop-limit", "step": "develop", "route": "fail", "scope": "route",
            "limit": 2, "entered": 2, "from": "verify"})
        # Entered once from assets (success), then twice through fail.
        self.assertEqual(state["steps"]["develop"]["route_visits"], {"success": 1, "fail": 2})
        self.assertEqual(self.status_line(state["run_id"]), "Status: BLOCKED")
        self.assertIn("WORKFLOW_BLOCKED", self.wgf("logs", state["run_id"]).stdout)

        self.wgf("new-game", "--resume", state["run_id"], "--quiet", expect=3)
        self.pass_g4(state["run_id"])
        self.assertEqual(self.state(state["run_id"])["status"], "COMPLETED")

    def test_waiting(self):
        self.wgf("new-game", "--mock", "--hold-gates", "--quiet", expect=3)
        run_id = self.state()["run_id"]
        self.assertEqual(self.status_line(run_id), "Status: WAITING")
        self.assertIn("STEP_WAITING", self.wgf("logs", run_id).stdout)

    def test_resume_does_not_duplicate_successful_steps(self):
        self.wgf("new-game", "--mock", "--quiet", "--mock-plan",
                 '{"develop": ["failed", "failed", "failed"]}', expect=1)
        before = self.state()
        succeeded = lambda s: sorted(t["step"] for t in s["trail"] if t["outcome"] == "SUCCESS")
        self.assertEqual(succeeded(before),
                         sorted(["research", "strategy", "strategy-review", "design",
                                 "tech-plan", "tech-plan-review", "init", "assets"]))
        self.wgf("new-game", "--resume", before["run_id"], "--quiet", expect=3)
        self.pass_g4(before["run_id"])
        after = self.state(before["run_id"])
        self.assertEqual(succeeded(after), sorted(succeeded(before) +
                                                  ["develop", "review", "sdk", "sdk-review",
                                                   "verify", "prototype-review",
                                                   "release"]))

    def test_mock_auto_approves_only_the_workflows_own_checkpoint(self):
        self.wgf("new-game", "--mock", "--quiet", expect=3)  # G4 is never auto-approved
        self.assertEqual(self.state()["params"]["auto_approve"], ["G2", "G3"])
        self.wgf("new-game", "--mock", "--hold-gates", "--quiet", expect=3)
        self.assertNotIn("auto_approve", self.state()["params"])


class ResumeAndDecide(CliCase):
    """`wgf resume` and `wgf decide`: first-class commands over the engine's own resume."""

    def held(self):
        self.wgf("new-game", "--mock", "--hold-gates", "--quiet", expect=3)
        return self.state()["run_id"]

    def events(self, run_id):
        return [json.loads(line) for line in
                self.wgf("logs", run_id, "--json").stdout.splitlines()]

    def test_resume_continues_a_failed_run(self):
        self.wgf("new-game", "--mock", "--quiet", "--mock-plan",
                 '{"develop": ["failed", "failed", "failed"]}', expect=1)
        run_id = self.state()["run_id"]
        self.wgf("resume", run_id, "--quiet", expect=3)
        self.pass_g4(run_id)
        state = self.state(run_id)
        self.assertEqual(state["status"], "COMPLETED")
        self.assertEqual(state["steps"]["research"]["executions"], 1)

    def test_resume_from_a_step(self):
        self.wgf("new-game", "--mock", "--quiet", expect=3)
        self.pass_g4()
        run_id = self.state()["run_id"]
        # A completed run is not resumable; the engine says so, and nothing changes.
        self.assertIn("COMPLETED", self.wgf("resume", run_id, "--from", "verify",
                                            expect=2).stderr)
        self.wgf("new-game", "--mock", "--quiet", "--mock-plan",
                 '{"release": ["fatal"]}', expect=3)
        self.pass_g4(expect=1)  # release fails
        run_id = self.state()["run_id"]
        # Verification runs again, so G4's pass no longer covers it: asked again.
        self.wgf("resume", run_id, "--from", "verify", "--quiet", expect=3)
        self.pass_g4(run_id)
        state = self.state(run_id)
        self.assertEqual(state["status"], "COMPLETED")
        self.assertEqual(state["steps"]["verify"]["executions"], 2)
        self.assertEqual(state["steps"]["develop"]["executions"], 1)

    def test_decide_answers_each_checkpoint_through_the_engine(self):
        run_id = self.held()
        done = self.wgf("decide", run_id, "approve", "--note", "looks right", "--quiet",
                        expect=3)
        self.assertIn(f"wgf decide {run_id} approve|reject", done.stdout)  # G3 next
        self.assertEqual(self.state(run_id)["cursor"], "tech-plan-review")
        done = self.wgf("decide", run_id, "approve", "--quiet", expect=3)
        self.assertIn(f"wgf decide {run_id} pass|iterate|kill", done.stdout)  # G4 next
        self.pass_g4(run_id)
        state = self.state(run_id)
        self.assertEqual(state["status"], "COMPLETED")
        for step in ("strategy-review", "tech-plan-review"):
            self.assertEqual(state["decisions"][step]["decided_by"], "human")
            self.assertEqual(state["decisions"][step]["visit"], 1)
        self.assertEqual(state["decisions"]["strategy-review"]["note"], "looks right")
        recorded = [e["step_id"] for e in self.events(run_id)
                    if e["event"] == "DECISION_RECORDED"]
        self.assertEqual(recorded, ["strategy-review", "tech-plan-review", "prototype-review"])

    def test_resume_with_a_decision(self):
        run_id = self.held()
        self.wgf("resume", run_id, "--decision", "reject", "--note", "no", "--quiet", expect=1)
        self.assertEqual(self.state(run_id)["status"], "BLOCKED")

    def test_decide_refuses_a_run_that_is_not_waiting(self):
        self.wgf("new-game", "--mock", "--quiet", expect=3)
        self.pass_g4()
        run_id = self.state()["run_id"]
        before = self.state(run_id)
        err = self.wgf("decide", run_id, "approve", expect=2).stderr
        self.assertIn("not waiting for a decision", err)
        self.assertEqual(self.state(run_id), before)
        self.assertIn("no run", self.wgf("decide", "nope", "approve", expect=2).stderr)

    def test_decide_refuses_a_choice_the_checkpoint_does_not_offer(self):
        run_id = self.held()
        self.assertIn("approve, reject",
                      self.wgf("decide", run_id, "maybe", expect=2).stderr)
        self.assertEqual(self.state(run_id)["decisions"], {})

    def test_decide_refuses_a_step_waiting_for_input(self):
        self.wgf("verify", "--mock", "--quiet", "--mock-plan", '{"verify": ["waiting"]}',
                 expect=3)
        run_id = self.state()["run_id"]
        self.assertIn("for input", self.wgf("decide", run_id, "approve", expect=2).stderr)
        self.assertIn(f"Resume: wgf resume {run_id}", self.wgf("status", run_id,
                                                                expect=3).stdout)
        self.assertEqual(self.state(run_id)["decisions"], {})

    def test_decided_by_is_derived_not_given(self):
        # Inside a step's process tree the decision is automation's: a reversible gate
        # takes it, and it is recorded as such. There is no flag to say otherwise.
        run_id = self.held()
        self.wgf("decide", run_id, "approve", "--quiet", expect=3,
                 env={"WGF_PROC_TAG": "test-m11"})
        self.assertEqual(self.state(run_id)["decisions"]["strategy-review"]["decided_by"],
                         "automation")
        self.wgf("decide", run_id, "approve", "--decided-by", "human", expect=2)

    def test_an_irreversible_gate_refuses_automation_through_decide(self):
        workflow = os.path.join(self.scratch, "kill.workflow.yaml")
        with open(workflow, "w", encoding="utf-8") as handle:
            # G4 is decided on the verified evidence (gates.yaml): a mock verify makes it.
            handle.write("workflow:\n  id: kill\n  version: 1\n  steps:\n"
                         "    - id: verify\n      type: verify\n"
                         "      outputs: [prototype-report, verification-report, qa-report,"
                         " title-strategy, game-design]\n"
                         "    - id: kill-review\n      type: human-checkpoint\n"
                         "      inputs: [qa-report, verification-report, prototype-report,"
                         " title-strategy, game-design]\n"
                         "      with: {gate: G4}\n")
        self.wgf("kill", "--workflow", workflow, "--mock", "--quiet", expect=3)
        run_id = self.state()["run_id"]
        self.wgf("decide", run_id, "approve", "--workflow", workflow, "--quiet", expect=3,
                 env={"WGF_PROC_TAG": "test-m11"})
        state = self.state(run_id)
        self.assertEqual(state["status"], "WAITING")
        self.assertIn("irreversible", state["steps"]["kill-review"]["message"])
        self.wgf("decide", run_id, "approve", "--workflow", workflow, "--quiet")
        self.assertEqual(self.state(run_id)["status"], "COMPLETED")

    def test_the_old_spelling_still_works(self):
        run_id = self.held()
        self.wgf("plan", "--resume", run_id, "--decision", "approve", "--quiet", expect=3)
        self.assertEqual(self.state(run_id)["cursor"], "tech-plan-review")


class BudgetRaise(CliCase):
    """`wgf resume <run> --budget-sessions N | --budget-cost X`: a person raises the run's
    developer-session budget, recorded as a BUDGET_RAISED event (M13)."""

    def setUp(self):
        super().setUp()
        with open(self.config, "w", encoding="utf-8") as handle:
            handle.write("factory:\n  storage:\n    fsync: false\n  develop:\n    budget:\n"
                         "      max_sessions: 2\n")

    def blocked_run(self):
        self.wgf("new-game", "--mock", "--quiet", "--mock-plan",
                 '{"verify": ["fail", "fail", "fail"]}', expect=1)
        state = self.state()
        self.assertEqual(state["params"]["develop_budget"], {"max_sessions": 2})
        return state["run_id"]

    def raises(self, run_id):
        with open(os.path.join(self.store, "workflows", run_id, "events.jsonl"),
                  encoding="utf-8") as handle:
            return [json.loads(line) for line in handle if '"BUDGET_RAISED"' in line]

    def test_a_person_raises_it_with_resume(self):
        run_id = self.blocked_run()
        self.wgf("resume", run_id, "--budget-sessions", "5", "--quiet", expect=3)
        raised = self.raises(run_id)
        self.assertEqual(len(raised), 1)
        self.assertEqual((raised[0]["data"]["max_sessions"], raised[0]["data"]["decided_by"]),
                         (5, "human"))

    def test_refused_from_inside_a_step(self):
        run_id = self.blocked_run()
        done = self.wgf("resume", run_id, "--budget-sessions", "50", expect=2,
                        env={"WGF_PROC_TAG": "0123456789abcdef"})
        self.assertIn("an agent does not raise its own budget", done.stderr)
        self.assertEqual(self.raises(run_id), [])
        self.assertEqual(self.state(run_id)["status"], "BLOCKED")

    def test_refused_when_the_run_has_no_such_budget(self):
        run_id = self.blocked_run()
        done = self.wgf("resume", run_id, "--budget-cost", "10", expect=2)
        self.assertIn("nothing to raise", done.stderr)
        self.assertEqual(self.raises(run_id), [])

    def test_a_raise_is_a_positive_number(self):
        run_id = self.blocked_run()
        done = self.wgf("resume", run_id, "--budget-sessions", "0", expect=2)
        self.assertIn("not a positive", done.stderr)


class IgnoredFlagsAreRefused(CliCase):
    """A flag the command would silently drop is a usage error, before anything runs."""

    def test_new_run_flags_with_resume_or_run(self):
        self.wgf("new-game", "--mock", "--hold-gates", "--quiet", expect=3)
        run_id = self.state()["run_id"]
        before = self.state(run_id)
        for continuing in ("--resume", "--run"):
            for flags in (("--mock",), ("--mock-plan", '{"verify": ["fail"]}'),
                          ("--hold-gates",), ("--project", "p1")):
                with self.subTest(continuing, flag=flags[0]):
                    err = self.wgf("new-game", continuing, run_id, *flags, expect=2).stderr
                    self.assertIn(flags[0], err)
                    self.assertIn("new run", err)
        self.assertEqual(self.state(run_id), before)

    def test_from_with_run(self):
        self.wgf("plan", "--mock", "--quiet")
        run_id = self.state()["run_id"]
        err = self.wgf("init", "--run", run_id, "--from", "init", expect=2).stderr
        self.assertIn("--from", err)
        self.assertIn(f"wgf resume {run_id} --from", err)
        self.assertNotIn("init", self.state(run_id)["steps"])

    def test_note_without_decision(self):
        self.wgf("new-game", "--mock", "--quiet", "--mock-plan", '{"develop": ["fatal"]}',
                 expect=1)
        run_id = self.state()["run_id"]
        for args in (("new-game", "--resume", run_id, "--note", "x"),
                     ("resume", run_id, "--note", "x"),
                     ("research", "--mock", "--note", "x")):
            with self.subTest(args):
                self.assertIn("--note", self.wgf(*args, expect=2).stderr)
        self.assertEqual(self.state(run_id)["status"], "FAILED")

    def test_decision_without_resume_is_a_usage_error(self):
        self.assertIn("wgf decide", self.wgf("research", "--mock", "--decision", "approve",
                                             expect=2).stderr)


class SingleStepHints(CliCase):
    """A fresh single-step run is kept, and named the run it probably belonged in."""

    def test_names_the_latest_run_holding_the_missing_inputs(self):
        self.wgf("new-game", "--mock", "--quiet", expect=3)  # waiting at G4
        holder = self.state()["run_id"]
        done = self.wgf("develop", "--mock", "--quiet", "--mock-plan",
                        '{"develop": ["waiting"]}', expect=3)
        self.assertIn("hint: develop needs", done.stderr)
        self.assertIn(f"wgf develop --run {holder}", done.stderr)
        fresh = self.state()
        self.assertNotEqual(fresh["run_id"], holder)  # the standalone run still exists
        self.assertEqual(fresh["scope"], ["develop"])

        done = self.wgf("develop", "--mock", "--quiet", "--mock-plan",
                        '{"develop": ["blocked"]}', expect=1)
        self.assertIn(f"wgf develop --run {holder}", done.stderr)

    def test_says_so_when_no_run_holds_them(self):
        done = self.wgf("verify", "--mock", "--quiet", "--mock-plan",
                        '{"verify": ["waiting"]}', expect=3)
        self.assertIn("no other run does either", done.stderr)

    def test_no_hint_when_the_step_did_its_work_or_was_continued(self):
        self.assertNotIn("hint:", self.wgf("verify", "--mock", "--quiet").stderr)
        self.wgf("new-game", "--mock", "--quiet", "--mock-plan", '{"verify": ["waiting"]}',
                 expect=3)
        self.assertNotIn("hint:", self.wgf("resume", self.state()["run_id"], "--quiet",
                                           expect=3).stderr)  # on to G4


class StatusExitCode(CliCase):
    """`wgf status` exits as the run it shows would: 0, 1 or 3; RUNNING is 0."""

    def test_every_status(self):
        self.wgf("research", "--mock", "--quiet")
        completed = self.state()["run_id"]
        self.wgf("research", "--mock", "--quiet", "--mock-plan", '{"research": ["fatal"]}',
                 expect=1)
        failed = self.state()["run_id"]
        self.wgf("research", "--mock", "--quiet", "--mock-plan", '{"research": ["blocked"]}',
                 expect=1)
        blocked = self.state()["run_id"]
        self.wgf("new-game", "--mock", "--hold-gates", "--quiet", expect=3)
        waiting = self.state()["run_id"]
        self.wgf("new-game", "--mock", "--hold-gates", "--quiet", expect=3)
        cancelled = self.state()["run_id"]
        self.wgf("cancel", cancelled)
        self.wgf("init", "--mock", "--quiet")
        running = self.state()["run_id"]
        store = RunStore(self.store, fsync=False)
        state = store.load(running)
        state.status, state.cursor = RunStatus.RUNNING, "init"
        store.save(state)
        for run_id, code in ((completed, 0), (failed, 1), (blocked, 1), (waiting, 3),
                             (cancelled, 1), (running, 0)):
            with self.subTest(run_id=run_id):
                self.wgf("status", run_id, expect=code)
                self.wgf("status", run_id, "--json", expect=code)
        self.wgf("pause", running)
        self.wgf("status", running, expect=3)


class RunsListing(CliCase):
    def test_waiting_lists_only_runs_waiting_for_a_decision(self):
        self.assertIn("no runs waiting", self.wgf("runs", "--waiting").stdout)
        self.wgf("research", "--mock", "--quiet")
        self.wgf("verify", "--mock", "--quiet", "--mock-plan", '{"verify": ["waiting"]}',
                 expect=3)  # waiting for input, not for a decision
        self.wgf("new-game", "--mock", "--hold-gates", "--quiet", expect=3)
        held = self.state()["run_id"]
        lines = self.wgf("runs", "--waiting").stdout.strip().splitlines()
        self.assertEqual(len([l for l in lines if l.startswith("new-game-")]), 1)
        self.assertEqual(lines[0].split(), [held, "strategy-review", "G2", "approve|reject"])

        listing = json.loads(self.wgf("runs", "--waiting", "--json").stdout)
        self.assertEqual([r["run_id"] for r in listing["runs"]], [held])
        self.assertEqual(listing["runs"][0]["waiting"],
                         {"step": "strategy-review", "gate": "G2",
                          "choices": ["approve", "reject"],
                          "prompt": "Approve the title strategy before design starts?",
                          "timeout": None})

    def test_json_lists_every_run(self):
        self.wgf("research", "--mock", "--quiet")
        self.wgf("verify", "--mock", "--quiet")
        listing = json.loads(self.wgf("runs", "--json").stdout)
        self.assertEqual(len(listing["runs"]), 2)
        self.assertEqual({r["status"] for r in listing["runs"]}, {"COMPLETED"})
        self.assertEqual(listing["unreadable"], [])


class ControlWithoutStepModules(CliCase):
    """pause and cancel need the store and the definition, never a step module."""

    def test_pause_and_cancel_with_a_broken_module_configured(self):
        modules = os.path.join(self.scratch, "modules")
        os.makedirs(modules)
        sentinel = os.path.join(self.scratch, "imported")
        with open(os.path.join(modules, "wgf_m11_broken.py"), "w", encoding="utf-8") as handle:
            handle.write("import os\nopen(os.environ['WGF_M11_SENTINEL'], 'w').close()\n"
                         "raise RuntimeError('broken on purpose')\n")
        self.wgf("new-game", "--mock", "--hold-gates", "--quiet", expect=3)
        waiting = self.state()["run_id"]
        self.wgf("init", "--mock", "--quiet")
        running = self.state()["run_id"]
        store = RunStore(self.store, fsync=False)
        state = store.load(running)
        state.status, state.cursor = RunStatus.RUNNING, "init"
        store.save(state)

        with open(self.config, "w", encoding="utf-8") as handle:
            handle.write("factory:\n  storage:\n    fsync: false\n"
                         "  steps:\n    modules: [wgf_m11_broken, wgf_m11_does_not_exist]\n")
        env = {"PYTHONPATH": modules, "WGF_M11_SENTINEL": sentinel}
        self.assertIn("PAUSED", self.wgf("pause", running, env=env).stdout)
        self.assertIn("CANCELLED", self.wgf("cancel", waiting, env=env).stdout)
        self.assertEqual(self.state(running)["status"], "PAUSED")
        self.assertEqual(self.state(waiting)["status"], "CANCELLED")
        self.assertFalse(os.path.exists(sentinel), "pause/cancel imported a step module")

        # The same configuration does break a command that runs steps: the test is real.
        self.wgf("resume", running, env=env, expect=None)
        self.assertTrue(os.path.exists(sentinel))


class Environment(CliCase):
    def test_an_os_error_is_one_line_not_a_traceback(self):
        blocker = os.path.join(self.scratch, "not-a-directory")
        with open(blocker, "w", encoding="utf-8") as handle:
            handle.write("x")
        self.store = os.path.join(blocker, "store")
        done = self.wgf("research", "--mock", "--quiet", expect=1)
        self.assertNotIn("Traceback", done.stderr)
        self.assertEqual(len(done.stderr.strip().splitlines()), 1, done.stderr)
        self.assertTrue(done.stderr.startswith("wgf: "))

    def test_storage_directory_resolves_against_the_repository_root(self):
        from wgflib.workflow.config import FactoryConfig
        self.assertEqual(FactoryConfig().storage_directory(), os.path.join(ROOT, ".factory"))
        absolute = os.path.join(self.scratch, "abs")
        self.assertEqual(FactoryConfig({"storage": {"directory": absolute}})
                         .storage_directory(), absolute)

        # A relative setting, from the root, from scripts/ and from elsewhere: one store.
        relative = os.path.relpath(self.store, ROOT)
        with open(self.config, "w", encoding="utf-8") as handle:
            handle.write(f"factory:\n  storage:\n    fsync: false\n"
                         f"    directory: {json.dumps(relative)}\n")
        self.wgf("research", "--mock", "--quiet", store=False, cwd=SCRIPTS)
        run_id = self.state()["run_id"]
        for cwd in (ROOT, SCRIPTS, self.scratch):
            with self.subTest(cwd=cwd):
                self.assertIn(run_id, self.wgf("status", store=False, cwd=cwd).stdout)

    def test_store_on_the_command_line_stays_relative_to_the_working_directory(self):
        self.wgf("research", "--mock", "--quiet", "--store", "typed", store=False,
                 cwd=self.scratch)
        self.assertTrue(os.path.isdir(os.path.join(self.scratch, "typed", "workflows")))


if __name__ == "__main__":
    unittest.main()

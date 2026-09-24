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

NEW_GAME = ["research", "strategy", "strategy-review", "design", "tech-plan", "tech-plan-review",
            "init", "assets", "develop", "sdk", "verify", "release"]
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

    def wgf(self, *args, expect=0):
        command = [sys.executable, WGF, *args, "--store", self.store, "--config", self.config]
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        done = subprocess.run(command, cwd=ROOT, capture_output=True, text=True,
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


class MockNewGame(CliCase):
    def test_runs_every_step_without_being_told_the_order(self):
        done = self.wgf("new-game", "--mock")
        self.assertIn("Workflow completed successfully.", done.stdout)
        state = self.state()
        self.assertEqual(state["status"], "COMPLETED")
        self.assertEqual([t["step"] for t in state["trail"]], NEW_GAME)
        self.assertEqual(set(self.statuses(state).values()), {"SUCCESS"})

    def test_emits_an_artifact_per_step_with_reproducible_provenance(self):
        self.wgf("new-game", "--mock")
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
        self.wgf("new-game", "--mock")
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
        self.wgf("new-game", "--run", run_id, "--quiet")
        state = self.state(run_id)
        self.assertEqual(state["status"], "COMPLETED")
        self.assertEqual(state["steps"]["strategy"]["executions"], 1)
        self.assertEqual(state["steps"]["release"]["status"], "SUCCESS")


class FailureAndResume(CliCase):
    def test_retry_then_success(self):
        self.wgf("new-game", "--mock", "--quiet", "--mock-plan", '{"develop": ["failed"]}')
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

        self.wgf("new-game", "--resume", state["run_id"], "--quiet")
        resumed = self.state(state["run_id"])
        self.assertEqual(resumed["status"], "COMPLETED")
        for step in ("research", "strategy", "design", "init", "assets"):
            self.assertEqual(resumed["steps"][step]["executions"], 1, step)
        self.assertEqual(resumed["steps"]["develop"]["executions"], 4)

    def test_verification_failure_loops_back_to_development(self):
        self.wgf("new-game", "--mock", "--quiet", "--mock-plan", '{"verify": ["fail"]}')
        state = self.state()
        self.assertEqual(state["status"], "COMPLETED")
        self.assertEqual([t["step"] for t in state["trail"]][8:],
                         ["develop", "sdk", "verify", "develop", "sdk", "verify", "release"])
        self.assertEqual(self.artifact(state, "qa-report", 1)["verdict"], "fail")
        self.assertEqual(self.artifact(state, "qa-report", 2)["verdict"], "pass")
        self.assertEqual(self.artifact(state, "prototype-report", 2)["iteration"], 2)

    def test_human_checkpoint_waits_then_resumes(self):
        done = self.wgf("new-game", "--mock", "--hold-gates", expect=3)
        self.assertIn("--decision", done.stdout)
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
                 "--note", "ok", "--quiet")
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
        self.wgf("new-game", "--resume", run_id, "--decision", "approve", "--quiet")
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
            out = self.wgf("status", *args).stdout
            self.assertIn(f"Run:      {run_id}", out)
            self.assertIn("Status: FAILED", out)
            self.assertIn("develop", out)
            self.assertIn("<- next", out)
            self.assertIn(f"--resume {run_id}", out)

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
        return [l for l in self.wgf("status", run_id).stdout.splitlines()
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
        # verify fails on every pass; new-game allows 3 visits per step before blocking.
        done = self.wgf("new-game", "--mock", "--quiet", "--mock-plan",
                        '{"verify": ["fail", "fail", "fail", "fail"]}', expect=1)
        self.assertIn("loop limit", done.stdout)
        state = self.state()
        self.assertEqual(state["status"], "BLOCKED")
        self.assertEqual(state["steps"]["verify"]["visits"], 3)
        self.assertEqual(self.status_line(state["run_id"]), "Status: BLOCKED")
        self.assertIn("WORKFLOW_BLOCKED", self.wgf("logs", state["run_id"]).stdout)

        self.wgf("new-game", "--resume", state["run_id"], "--quiet")
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
        self.wgf("new-game", "--resume", before["run_id"], "--quiet")
        after = self.state(before["run_id"])
        self.assertEqual(succeeded(after), sorted(succeeded(before) +
                                                  ["develop", "sdk", "verify", "release"]))

    def test_mock_auto_approves_only_the_workflows_own_checkpoint(self):
        self.wgf("new-game", "--mock", "--quiet")
        self.assertEqual(self.state()["params"]["auto_approve"], ["G2", "G3"])
        self.wgf("new-game", "--mock", "--hold-gates", "--quiet", expect=3)
        self.assertNotIn("auto_approve", self.state()["params"])


if __name__ == "__main__":
    unittest.main()

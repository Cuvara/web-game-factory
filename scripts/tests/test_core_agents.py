"""Core Acceptance Suite, AGENTS category: the developer -> reviewer loop, end to end.

Nothing here is faked inside the Factory. The developer and the reviewer are real child
processes - small Python scripts standing in for agent hosts - the game repository is a real
git repository in a temp directory, and every run goes through the real WorkflowAPI and
WorkflowEngine on the shipped core/workflows/new-game.workflow.yaml, with the real
`develop` and `review` steps - `review` and `sdk-review`, which reads the commit the sdk
step made on top. The sdk step here is a scripted stand-in that makes a real keyed
integration commit; the other steps are the engine's placeholders. develop's toolchain
checks are configured off (conformance still runs) so the suite stays fast.

    python -m unittest scripts/tests/test_core_agents.py

The one live test runs a real agent host as the reviewer; it is skipped unless
WGF_LIVE_AGENT=1 and WGF_LIVE_REVIEWER_ARGV (a JSON argv) are set. See docs/review-module.md.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
sys.path.insert(0, SCRIPTS)

from test_develop_module import AUTHOR, IDENTITY, SCAFFOLD_FILES  # noqa: E402

import wgf_review  # noqa: E402
from wgf_develop.step import DevelopStep  # noqa: E402
from wgf_review import verdict as verdicts  # noqa: E402
from wgf_review.step import ReviewStep  # noqa: E402
from wgflib.workflow import mock  # noqa: E402
from wgflib.workflow.api import RunRequest, WorkflowAPI  # noqa: E402
from wgflib.workflow.checkpoint import register as register_checkpoint  # noqa: E402
from wgflib.workflow.config import FactoryConfig  # noqa: E402
from wgflib.workflow.contracts import ArtifactContracts  # noqa: E402
from wgflib.workflow.model import RunStatus  # noqa: E402
from wgflib.workflow.step import StepRegistry  # noqa: E402

HAS_GIT = shutil.which("git") is not None
TITLE = "demo-title"
PY = sys.executable

# The developer: implements the brief the way test_develop_module's write_game does, plus
# one file with a known bug - unless the brief carries a review blocker for it, in which
# case it fixes it. Behaviour comes from $WGF_TEST_DEV_MODE.
DEVELOPER = r'''
import json, os, sys, time
sys.path.insert(0, os.environ["WGF_TEST_TESTS_DIR"])
from test_develop_module import write_game

brief_md = sys.argv[1]
repo = os.getcwd()
mode = os.environ.get("WGF_TEST_DEV_MODE", "good")
log = os.environ["WGF_TEST_DEV_LOG"]
with open(os.path.join(os.path.dirname(brief_md), "brief.json")) as handle:
    brief = json.load(handle)
calls = []
if os.path.exists(log):
    with open(log) as handle:
        calls = [json.loads(line) for line in handle if line.strip()]
with open(log, "a") as handle:
    handle.write(json.dumps({"iteration": brief["iteration"],
                             "blockers": brief.get("review_blockers") or []}) + "\n")
print("developer working", flush=True)
if mode == "sleep":
    time.sleep(60)
if mode == "fail" or (mode == "fail-once" and not calls):
    print("developer crashed", flush=True)
    sys.exit(3)
if mode == "live-exec":
    # The live developer: the conformance scaffolding is written mechanically (the first
    # visit also plants the bug), then this process BECOMES the configured agent host, so
    # the host is the develop step's own child. The host makes the change on visit 1 and
    # fixes the reviewer's blockers on visit 2; nothing here touches score.ts after that.
    argv = json.loads(os.environ["WGF_TEST_LIVE_DEV_ARGV"])
    write_game(repo, {"src/game/score.ts": "export function score(lives: number): number {\n"
                      "  return lives - 1; // BUG: can go negative\n}\n"}
               if brief["iteration"] == 1 else None)
    sys.stdout.flush()
    os.execvp(argv[0], [part.replace("{brief}", brief_md) for part in argv])
# Fixed when a review blocker names the bug - by the scripted reviewer's id, or by its file,
# which is all a live reviewer (that picks its own ids) can be relied on to share.
blocked = [b for b in brief.get("review_blockers") or []
           if b.get("id") == "score-underflow" or b.get("file") == "src/game/score.ts"]
buggy = mode == "bug-then-fix" and brief["iteration"] == 1 and not blocked
score = ("export function score(lives: number): number {\n"
         + ("  return lives - 1; // BUG: can go negative\n" if buggy
            else "  return Math.max(0, lives - 1);\n") + "}\n")
write_game(repo, {"src/game/score.ts": score})
'''

# The reviewer: argv is [mode, repo, verdict, commit]. It reads; depending on the mode it
# also misbehaves in one specific way.
REVIEWER = r'''
import json, os, subprocess, sys, time
mode, repo, verdict_path, commit = sys.argv[1:5]

def verdict(data):
    with open(verdict_path, "w") as handle:
        json.dump(data, handle)

def bug_blockers():
    found = []
    for directory, _, files in os.walk(os.path.join(repo, "src")):
        for name in files:
            path = os.path.join(directory, name)
            with open(path, encoding="utf-8") as handle:
                for number, line in enumerate(handle, 1):
                    if "BUG:" in line:
                        found.append({"id": "score-underflow",
                                      "file": os.path.relpath(path, repo).replace(os.sep, "/"),
                                      "line": number, "severity": "blocker",
                                      "summary": "score can go negative"})
    return found

def git(*args):
    subprocess.run(["git", "-c", "user.name=R", "-c", "user.email=r@example.invalid", *args],
                   cwd=repo, check=True, capture_output=True)

print("reviewing", commit, flush=True)
approve = {"verdict": "approve", "commit": commit, "blockers": [], "notes": "ok"}
if mode == "detect":
    blockers = bug_blockers()
    verdict({"verdict": "request-changes", "commit": commit, "blockers": blockers}
            if blockers else approve)
elif mode == "approve":
    verdict(approve)
elif mode == "reject-sdk-once":
    # Requests changes to the first sdk integration commit it is shown (sdk-review), once;
    # approves everything else. The marker lives beside the verdict, outside the checkout.
    message = subprocess.run(["git", "log", "-1", "--format=%B", commit], cwd=repo,
                             check=True, capture_output=True, text=True).stdout
    marker = os.path.join(os.path.dirname(verdict_path), "sdk-rejected")
    if "Wgf-Sdk-Key:" in message and not os.path.exists(marker):
        open(marker, "w").close()
        verdict({"verdict": "request-changes", "commit": commit, "blockers": [
            {"id": "integration-reward", "file": "src/platform/gameplay.ts",
             "severity": "blocker", "summary": "the integration drops the reward"}]})
    else:
        verdict(approve)
elif mode == "always-request":
    verdict({"verdict": "request-changes", "commit": commit, "blockers": [
        {"id": "never-happy", "file": None, "summary": "try again", "severity": "major"}]})
elif mode.startswith("modify:"):
    path = os.path.join(repo, mode.split(":", 1)[1])
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a") as handle:
        handle.write("\n// reviewer was here\n")
    verdict(approve)
elif mode.startswith("outside:"):
    with open(mode.split(":", 1)[1], "a") as handle:
        handle.write("\nreviewer: was here\n")
    verdict(approve)
elif mode == "commit":
    with open(os.path.join(repo, "src/game/score.ts"), "a") as handle:
        handle.write("// quietly fixed by the reviewer\n")
    git("commit", "-q", "-am", "reviewer fix")
    verdict({**approve, "commit": commit})
elif mode == "not-json":
    with open(verdict_path, "w") as handle:
        handle.write("LGTM!")
elif mode == "approve-with-blockers":
    verdict({"verdict": "approve", "commit": commit, "blockers": [
        {"id": "x", "file": "src/main.ts", "summary": "meh", "severity": "minor"}]})
elif mode == "request-without-blockers":
    verdict({"verdict": "request-changes", "commit": commit, "blockers": []})
elif mode == "wrong-commit":
    verdict({**approve, "commit": "f" * 40})
elif mode == "extra-key":
    verdict({**approve, "score": 10})
elif mode == "print-detect":
    blockers = bug_blockers()
    data = ({"verdict": "request-changes", "commit": commit, "blockers": blockers}
            if blockers else approve)
    print("Reviewed. Verdict:\n```json\n" + json.dumps(data, indent=2) + "\n```", flush=True)
elif mode == "no-file":
    pass
elif mode == "crash":
    sys.exit(7)
elif mode == "hang-with-child":
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
    with open(os.environ["WGF_TEST_CHILD_PID"], "a") as handle:
        handle.write(f"{child.pid}\n")
    time.sleep(120)
elif mode == "silent":
    time.sleep(120)
'''


def _alive(pid):
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    try:
        with open(f"/proc/{pid}/stat") as handle:
            return handle.read().rsplit(")", 1)[1].split()[0] not in ("Z", "X")
    except OSError:
        return True


class ScriptedSdkStep(mock.MockSDKStep):
    """The sdk step's history effect, for real: one keyed integration commit on top of the
    development commit, reported the way wgf_sdk reports it. So `sdk-review` reviews a
    different commit than `review` did - the one that ships."""

    repo = None

    def execute(self, inputs, context):
        base = inputs.load("prototype-report")["build_ref"]["commit_sha"]
        path = os.path.join(self.repo, "src", "platform", "gameplay.ts")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(f"// platform integration, sdk visit {context.visit}\nexport {{}};\n")
        for args in (["add", "-A"],
                     [*IDENTITY, "commit", "-q", "-m",
                      f"sdk: integrate\n\nWgf-Sdk-Key: {context.idempotency_key}"]):
            subprocess.run(["git", *args], cwd=self.repo, check=True, capture_output=True)
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.repo, check=True,
                              capture_output=True, text=True).stdout.strip()
        self._build_ref = {"commit_sha": head, "base_commit_sha": base, "sdk_commits": [head]}
        return super().execute(inputs, context)

    def customize(self, body, artifact_type, context, entry):
        if artifact_type == "sdk-report":
            body["build_ref"] = dict(self._build_ref)


@unittest.skipUnless(HAS_GIT, "git is not installed")
class AgentLoop(unittest.TestCase):
    """The loop through the real engine. Each test is one run of new-game."""

    def setUp(self):
        self.scratch = tempfile.mkdtemp(prefix="wgf-agents-")
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)
        self.repo = os.path.join(self.scratch, "checkouts", TITLE)
        os.makedirs(self.repo)
        for relative, text in SCAFFOLD_FILES.items():
            self.write(relative, text)
        self.write(".gitignore", "node_modules/\ndist/\n")
        for args in (["init", "-q", "-b", "main"], ["add", "-A"],
                     [*IDENTITY, "commit", "-q", "-m", "scaffold"]):
            self.git(*args)
        self.developer = os.path.join(self.scratch, "developer.py")
        self.reviewer = os.path.join(self.scratch, "reviewer.py")
        for path, text in ((self.developer, DEVELOPER), (self.reviewer, REVIEWER)):
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(text)
        self.dev_log = os.path.join(self.scratch, "developer-calls.jsonl")
        self.child_pids = os.path.join(self.scratch, "child-pids")
        # The Factory paths a reviewer must not touch; a copy, so a test can try.
        self.guarded = os.path.join(self.scratch, "factory", "config")
        os.makedirs(self.guarded)
        with open(os.path.join(self.guarded, "factory.yaml"), "w") as handle:
            handle.write("factory:\n  review: {}\n")
        self.env = {"WGF_TEST_TESTS_DIR": HERE, "WGF_TEST_DEV_LOG": self.dev_log,
                    "WGF_TEST_CHILD_PID": self.child_pids, "WGF_TEST_DEV_MODE": "good"}
        saved = {k: os.environ.get(k) for k in self.env}
        os.environ.update(self.env)
        self.addCleanup(lambda: [os.environ.pop(k, None) if v is None
                                 else os.environ.__setitem__(k, v)
                                 for k, v in saved.items()])

    # -- helpers ---------------------------------------------------------------------

    def write(self, relative, text):
        path = os.path.join(self.repo, relative)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)

    def read(self, relative):
        with open(os.path.join(self.repo, relative), encoding="utf-8") as handle:
            return handle.read()

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.repo, check=True, capture_output=True,
                              text=True).stdout.strip()

    def run_workflow(self, reviewer_mode="approve", dev_mode="good", reviewer=None,
                     developer=None, develop=None, execution=None):
        os.environ["WGF_TEST_DEV_MODE"] = dev_mode
        review_cfg = {"kind": "command",
                      "argv": [PY, self.reviewer, reviewer_mode, "{repo}", "{verdict}",
                               "{commit}"],
                      "timeout_seconds": 20, "idle_timeout_seconds": 20}
        review_cfg.update(reviewer or {})
        developer_cfg = {"kind": "command", "argv": [PY, self.developer, "{brief}"],
                         "timeout_seconds": 30}
        developer_cfg.update(developer or {})
        develop_cfg = {"checkouts": os.path.join(self.scratch, "checkouts"), "author": AUTHOR,
                       "checks": [], "developer": developer_cfg}
        develop_cfg.update(develop or {})
        config = FactoryConfig({
            "storage": {"fsync": False}, "checkpoints": {"auto_approve": ["G2", "G3"]},
            "execution": {"max_attempts": 2, "backoff": "none", "delay_seconds": 0,
                          **(execution or {})},
            "develop": develop_cfg,
            "review": {"reviewer": review_cfg, "guarded_paths": [self.guarded]},
            # Agents get an allowlisted environment (wgflib.agentenv): the scripted agents'
            # own settings pass by prefix, and a live run names its host's credential in
            # WGF_LIVE_ENV_PASSTHROUGH (comma-separated).
            "agents": {"env_passthrough": ["WGF_TEST_*"] + [
                n for n in os.environ.get("WGF_LIVE_ENV_PASSTHROUGH", "").split(",") if n]},
        })

        repo = self.repo

        class Sdk(ScriptedSdkStep):
            pass

        Sdk.repo = repo

        class API(WorkflowAPI):
            def registry(self, use_mock):
                registry = StepRegistry()
                register_checkpoint(registry)
                mock.register(registry)
                registry.register("develop", DevelopStep)  # later wins over the mock
                registry.register("sdk", Sdk)
                wgf_review.register(registry)
                return registry

        self.api = API(config=config, store_dir=os.path.join(self.scratch, "store"),
                       sleep=lambda _s: None)
        self.state = self.api.run(RunRequest(project_id=TITLE))
        if (self.state.status, self.state.cursor) == (RunStatus.WAITING, "prototype-review"):
            # G4 after verification: irreversible, so no config passes it. The person
            # running the test does, as `wgf decide <run> pass` would.
            self.state = self.api.run(RunRequest(resume=self.state.run_id, decision="pass",
                                                 decided_by="human"))
        return self.state

    def trail(self, step=None):
        return [(t["step"], t["visit"], t["attempt"], t["outcome"], t["route"])
                for t in self.state.trail if step is None or t["step"] == step]

    def reports(self, artifact_type="review-report"):
        versions = []
        for refs in self.state.artifacts.values():
            versions += [r for r in refs if r.type == artifact_type]
        versions.sort(key=lambda r: r.version)
        return [self.api.store.read_artifact(self.state.run_id, r) for r in versions]

    def developer_calls(self):
        if not os.path.exists(self.dev_log):
            return []
        with open(self.dev_log) as handle:
            return [json.loads(line) for line in handle if line.strip()]

    def assert_valid(self, report):
        self.assertEqual(ArtifactContracts()("review-report", report), [])

    def assert_rejected(self, code, fragment=None):
        self.assertEqual(self.state.status, RunStatus.FAILED, self.state.message)
        self.assertEqual(self.trail("review")[-1][3], "FAILED")
        report = self.reports()[-1]
        self.assert_valid(report)
        self.assertEqual(report["verdict"], "no-verdict")
        self.assertEqual(report["failure"]["code"], code)
        if fragment:
            self.assertIn(fragment, self.state.steps["review"].error)
        self.assertNotIn("sdk", [t[0] for t in self.trail()])
        return report

    # -- 1..8: the loop ---------------------------------------------------------------

    def test_developer_reviewer_request_changes_developer_reviewer_approve(self):
        state = self.run_workflow(reviewer_mode="detect", dev_mode="bug-then-fix")
        self.assertEqual(state.status, RunStatus.COMPLETED, state.message)

        # 1-4: the developer committed a build with a known bug; the reviewer found it.
        # 5: the workflow file - not code - sent it back to develop; 6-7: fixed, approved;
        # 8: the run carried on past review to sdk, whose own commit sdk-review approved,
        # then verify, G4 and release.
        steps = [(s, v, o, r) for s, v, _a, o, r in self.trail()
                 if s in ("develop", "review", "sdk", "sdk-review", "verify", "release")]
        self.assertEqual(steps, [
            ("develop", 1, "SUCCESS", "success"),
            ("review", 1, "FAILED", "request-changes"),
            ("develop", 2, "SUCCESS", "success"),
            ("review", 2, "SUCCESS", "success"),
            ("sdk", 1, "SUCCESS", "success"),
            ("sdk-review", 1, "SUCCESS", "success"),
            ("verify", 1, "SUCCESS", "success"),
            ("release", 1, "SUCCESS", "success"),
        ])

        first, second, third = self.reports()
        prototypes = self.reports("prototype-report")
        for report in (first, second):
            self.assert_valid(report)
            self.assertTrue(report["isolation"]["intact"])
            self.assertGreater(report["isolation"]["checked_paths"], 5)
            self.assertEqual(report["reviewer"]["argv0"], os.path.basename(PY))
        self.assertEqual(first["verdict"], "request-changes")
        self.assertEqual([b["id"] for b in first["blockers"]], ["score-underflow"])
        self.assertEqual(first["blockers"][0]["file"], "src/game/score.ts")
        self.assertEqual(first["reviewed_commit"],
                         prototypes[0]["build_ref"]["commit_sha"])
        self.assertEqual(second["verdict"], "approve")
        self.assertEqual(second["blockers"], [])
        # The second review saw the second development commit, not the first.
        self.assertEqual(second["reviewed_commit"], prototypes[1]["build_ref"]["commit_sha"])
        self.assertNotEqual(first["reviewed_commit"], second["reviewed_commit"])
        self.assertEqual(second["baseline_commit"], first["reviewed_commit"])
        # sdk-review saw the sdk commit on top of it - HEAD, the commit that ships - and the
        # change it was shown is exactly the integration.
        sdk = self.reports("sdk-report")[-1]["build_ref"]
        self.assert_valid(third)
        self.assertEqual(third["verdict"], "approve")
        self.assertTrue(third["isolation"]["intact"])
        self.assertEqual(third["reviewed_commit"], sdk["commit_sha"])
        self.assertNotEqual(third["reviewed_commit"], second["reviewed_commit"])
        self.assertEqual(third["baseline_commit"], second["reviewed_commit"])
        self.assertEqual(self.git("rev-parse", "HEAD"), third["reviewed_commit"])
        self.assertIn("sdk-report", {p["artifact_type"]
                                     for p in third["provenance"]["inputs"]})
        verdicts_dir = os.path.join(self.api.store.run_dir(state.run_id), "review")
        self.assertTrue(os.path.exists(os.path.join(verdicts_dir, "review-2-1.verdict.json")))
        self.assertTrue(os.path.exists(
            os.path.join(verdicts_dir, "sdk-review-1-1.verdict.json")))

        # 5: the developer's second brief carried the reviewer's blocker.
        calls = self.developer_calls()
        self.assertEqual([c["iteration"] for c in calls], [1, 2])
        self.assertEqual(calls[0]["blockers"], [])
        self.assertEqual([b["id"] for b in calls[1]["blockers"]], ["score-underflow"])
        self.assertIn("blockers from code review", self.read("docs/development/brief.md"))
        self.assertNotIn("BUG", self.read("src/game/score.ts"))
        self.assertEqual(self.git("status", "--porcelain"), "")

    def test_an_approving_reviewer_runs_once_and_the_run_completes(self):
        state = self.run_workflow(reviewer_mode="detect")
        self.assertEqual(state.status, RunStatus.COMPLETED, state.message)
        self.assertEqual(self.trail("review"), [("review", 1, 1, "SUCCESS", "success")])
        self.assertEqual(len(self.developer_calls()), 1)
        self.assertEqual(self.reports()[0]["verdict"], "approve")
        # The developer's whole transcript is kept beside the run, outside the checkout.
        transcript = os.path.join(self.api.store.run_dir(state.run_id), "develop", "1-1.log")
        with open(transcript, encoding="utf-8") as handle:
            self.assertIn("developer working", handle.read())

    def test_a_reviewer_that_always_requests_changes_is_stopped_by_max_visits(self):
        state = self.run_workflow(reviewer_mode="always-request")
        self.assertEqual(state.status, RunStatus.BLOCKED, state.message)
        self.assertIn("loop limit", state.message)
        self.assertEqual([t[1] for t in self.trail("review")], [1, 2, 3])
        self.assertEqual(len(self.developer_calls()), 3)
        self.assertNotIn("sdk", [t[0] for t in self.trail()])

    def test_a_sandboxed_reviewer_can_answer_on_stdout(self):
        state = self.run_workflow(reviewer_mode="print-detect", dev_mode="bug-then-fix",
                                  reviewer={"verdict_from": "stdout"})
        self.assertEqual(state.status, RunStatus.COMPLETED, state.message)
        self.assertEqual([r["verdict"] for r in self.reports()],
                         ["request-changes", "approve", "approve"])

    def test_sdk_review_requesting_changes_goes_back_to_develop_never_to_verify(self):
        state = self.run_workflow(reviewer_mode="reject-sdk-once")
        self.assertEqual(state.status, RunStatus.COMPLETED, state.message)
        steps = [(s, v, o, r) for s, v, _a, o, r in self.trail()
                 if s in ("develop", "review", "sdk", "sdk-review", "verify")]
        self.assertEqual(steps, [
            ("develop", 1, "SUCCESS", "success"),
            ("review", 1, "SUCCESS", "success"),
            ("sdk", 1, "SUCCESS", "success"),
            ("sdk-review", 1, "FAILED", "request-changes"),
            ("develop", 2, "SUCCESS", "success"),
            ("review", 2, "SUCCESS", "success"),
            ("sdk", 2, "SUCCESS", "success"),
            ("sdk-review", 2, "SUCCESS", "success"),
            ("verify", 1, "SUCCESS", "success"),
        ])
        rejected = self.reports()[1]
        self.assertEqual(rejected["verdict"], "request-changes")
        # The developer's next brief led with the integration blocker: sdk-review's
        # reviewed_commit was HEAD when develop ran again.
        calls = self.developer_calls()
        self.assertEqual([b["id"] for b in calls[1]["blockers"]], ["integration-reward"])
        # The approval that the run carried on with is of the second sdk commit, HEAD.
        self.assertEqual(self.reports()[-1]["reviewed_commit"], self.git("rev-parse", "HEAD"))
        self.assertEqual(self.reports()[-1]["verdict"], "approve")

    def test_no_reviewer_is_recorded_as_skipped_never_as_approval(self):
        state = self.run_workflow(reviewer={"kind": "none", "argv": []})
        self.assertEqual(state.status, RunStatus.COMPLETED, state.message)
        report = self.reports()[0]
        self.assert_valid(report)
        self.assertEqual(report["verdict"], "skipped")
        self.assertIn("NO REVIEW HAPPENED", report["notes"])
        self.assertIn("unreviewed", state.steps["review"].message)

    # -- isolation --------------------------------------------------------------------

    def assert_isolation_violation(self, path, sensitive):
        head = self.git("rev-parse", "HEAD")
        report = self.assert_rejected("reviewer-isolation-violation", path)
        self.assertEqual(len(self.trail("review")), 1, "an isolation violation is not retried")
        violations = {v["path"]: v for v in report["isolation"]["violations"]}
        self.assertIn(path, violations)
        self.assertEqual(violations[path]["sensitive"], sensitive)
        self.assertTrue(report["isolation"]["restored"])
        self.assertFalse(report["isolation"]["intact"])
        self.assertEqual(self.git("status", "--porcelain"), "")
        self.assertEqual(self.git("rev-parse", "HEAD"), head)
        self.assertNotIn("reviewer was here", self.git("show", "HEAD", "--", path) or "")
        return report

    def test_a_reviewer_editing_source_is_rejected_and_the_file_restored(self):
        self.run_workflow(reviewer_mode="modify:src/game/app.ts")
        self.assert_isolation_violation("src/game/app.ts", sensitive=False)
        self.assertNotIn("reviewer was here", self.read("src/game/app.ts"))

    def test_a_reviewer_editing_package_json_is_rejected(self):
        self.run_workflow(reviewer_mode="modify:package.json")
        self.assert_isolation_violation("package.json", sensitive=True)
        json.loads(self.read("package.json"))  # restored: parses again

    def test_a_reviewer_adding_a_test_is_rejected_and_the_file_removed(self):
        self.run_workflow(reviewer_mode="modify:tests/unit/extra.test.ts")
        self.assert_isolation_violation("tests/unit/extra.test.ts", sensitive=True)
        self.assertFalse(os.path.exists(os.path.join(self.repo, "tests/unit/extra.test.ts")))

    def test_a_reviewer_editing_game_config_is_rejected(self):
        self.run_workflow(reviewer_mode="modify:game.config.yaml")
        self.assert_isolation_violation("game.config.yaml", sensitive=True)
        self.assertNotIn("reviewer was here", self.read("game.config.yaml"))

    def test_a_reviewer_writing_into_an_ignored_path_is_caught(self):
        self.run_workflow(reviewer_mode="modify:dist/injected.js")
        self.assert_isolation_violation("dist", sensitive=False)
        self.assertFalse(os.path.exists(os.path.join(self.repo, "dist")))

    def test_a_reviewer_committing_is_rejected_and_head_restored(self):
        self.run_workflow(reviewer_mode="commit")
        head = self.reports("prototype-report")[-1]["build_ref"]["commit_sha"]
        report = self.assert_rejected("reviewer-isolation-violation", "head-moved")
        changes = {v["change"] for v in report["isolation"]["violations"]}
        self.assertTrue({"head-moved", "ref-changed"} <= changes)
        self.assertTrue(report["isolation"]["restored"])
        self.assertEqual(self.git("rev-parse", "HEAD"), head)
        self.assertNotIn("reviewer", self.git("log", "--format=%s", "-n1"))
        self.assertNotIn("quietly fixed", self.read("src/game/score.ts"))

    def test_a_reviewer_editing_factory_config_is_rejected_and_restored(self):
        target = os.path.join(self.guarded, "factory.yaml")
        self.run_workflow(reviewer_mode=f"outside:{target}")
        report = self.assert_rejected("reviewer-isolation-violation")
        violation = next(v for v in report["isolation"]["violations"] if v["path"] == target)
        self.assertEqual(violation["scope"], "factory")
        with open(target) as handle:
            self.assertEqual(handle.read(), "factory:\n  review: {}\n")

    # -- the verdict contract -----------------------------------------------------------

    def test_malformed_verdicts_are_rejected_and_never_retried(self):
        cases = {
            "not-json": "not JSON",
            "approve-with-blockers": "approval cannot list blockers",
            "request-without-blockers": "must name at least one blocker",
            "wrong-commit": "verdict is for ffffffffffff",
            "extra-key": "keys the contract does not",
            "no-file": "no verdict file",
        }
        for mode, fragment in cases.items():
            with self.subTest(mode=mode):
                self.run_workflow(reviewer_mode=mode)
                self.assert_rejected("malformed-verdict", fragment)
                self.assertEqual(len(self.trail("review")), 1)

    # -- processes that misbehave -------------------------------------------------------

    def test_a_reviewer_timeout_is_retried_and_its_tree_is_killed(self):
        began = time.monotonic()
        self.run_workflow(reviewer_mode="hang-with-child",
                          reviewer={"timeout_seconds": 1.5, "idle_timeout_seconds": None})
        self.assertLess(time.monotonic() - began, 30)
        report = self.assert_rejected("reviewer-timeout", "timed out")
        self.assertTrue(report["timed_out"])
        self.assertEqual([t[2] for t in self.trail("review")], [1, 2])  # retried per policy
        with open(self.child_pids) as handle:
            pids = [int(line) for line in handle if line.strip()]
        self.assertEqual(len(pids), 2)
        for pid in pids:
            self.assertFalse(_alive(pid), f"grandchild {pid} outlived the review")
        # The last attempt's report names the grandchild it had to kill.
        self.assertIn(pids[-1], report["reviewer"]["killed_pids"])

    def test_a_silent_reviewer_hits_the_idle_timeout(self):
        self.run_workflow(reviewer_mode="silent",
                          reviewer={"timeout_seconds": 30, "idle_timeout_seconds": 1},
                          execution={"max_attempts": 1})
        report = self.assert_rejected("reviewer-idle-timeout", "no output")
        self.assertTrue(report["timed_out"])

    def test_a_crashing_reviewer_is_retried_then_fails_the_run(self):
        self.run_workflow(reviewer_mode="crash")
        self.assert_rejected("reviewer-crashed", "exited 7")
        self.assertEqual([t[2] for t in self.trail("review")], [1, 2])

    def test_a_developer_timeout_fails_the_step_and_is_retried(self):
        began = time.monotonic()
        state = self.run_workflow(dev_mode="sleep", developer={"timeout_seconds": 1})
        self.assertLess(time.monotonic() - began, 30)
        self.assertEqual(state.status, RunStatus.FAILED)
        self.assertEqual([(t[2], t[3]) for t in self.trail("develop")],
                         [(1, "FAILED"), (2, "FAILED")])
        self.assertIn("timed out", state.steps["develop"].error)
        self.assertEqual(self.trail("review"), [])

    def test_a_developer_failure_is_retried_and_the_loop_recovers(self):
        state = self.run_workflow(dev_mode="fail-once")
        self.assertEqual(state.status, RunStatus.COMPLETED, state.message)
        self.assertEqual([(t[2], t[3]) for t in self.trail("develop")],
                         [(1, "FAILED"), (2, "SUCCESS")])
        self.assertEqual(self.reports()[0]["verdict"], "approve")

    def test_an_exhausted_retry_budget_fails_the_run(self):
        state = self.run_workflow(dev_mode="fail")
        self.assertEqual(state.status, RunStatus.FAILED)
        self.assertEqual(len(self.trail("develop")), 2)
        self.assertIn("exited 3", state.steps["develop"].error)
        self.assertEqual(self.trail("review"), [])

    def test_an_uncommitted_build_is_not_reviewed(self):
        state = self.run_workflow(develop={"commit": False})
        self.assertEqual(state.status, RunStatus.BLOCKED, state.message)
        self.assertIn("uncommitted changes", state.message)
        self.assertEqual(self.reports(), [])


@unittest.skipUnless(os.environ.get("WGF_AJV") == "1" and shutil.which("npx") and HAS_GIT,
                     "set WGF_AJV=1 to validate with ajv (needs npx; may download ajv-cli)")
class Schema(AgentLoop):
    """Every review-report shape the loop emits, against the full JSON Schema."""

    def test_emitted_reports_validate_with_ajv(self):
        reports = []
        self.run_workflow(reviewer_mode="detect", dev_mode="bug-then-fix")
        reports += self.reports()
        self.run_workflow(reviewer_mode="modify:package.json")
        reports += self.reports()[-1:]
        self.run_workflow(reviewer={"kind": "none", "argv": []})
        reports += self.reports()[-1:]
        root = os.path.dirname(SCRIPTS)
        for index, report in enumerate(reports):
            path = os.path.join(self.scratch, f"review-report-{index}.json")
            with open(path, "w") as handle:
                json.dump(report, handle)
            completed = subprocess.run(
                ["npx", "--yes", "-p", "ajv-cli@5", "-p", "ajv-formats@2", "ajv", "validate",
                 "-s", "core/artifacts/review-report.schema.json",
                 "-r", "core/artifacts/shared/*.schema.json", "-c", "ajv-formats",
                 "--spec=draft2020", "--strict=false", "-d", path],
                cwd=root, capture_output=True, text=True)
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)


for _name in [n for n in dir(AgentLoop) if n.startswith("test_")]:
    setattr(Schema, _name, None)


class VerdictContract(unittest.TestCase):
    """The parser on its own, for the edges an engine run would be slow to reach."""

    HEAD = "a" * 40

    def parse(self, data):
        path = os.path.join(tempfile.mkdtemp(prefix="wgf-verdict-"), "v.json")
        self.addCleanup(shutil.rmtree, os.path.dirname(path), ignore_errors=True)
        with open(path, "w") as handle:
            handle.write(data if isinstance(data, str) else json.dumps(data))
        return verdicts.parse(path, self.HEAD)

    def blocker(self, **overrides):
        return {"id": "b1", "file": "src/a.ts", "summary": "s", "severity": "major",
                **overrides}

    def test_well_formed(self):
        ok, problem = self.parse({"verdict": "request-changes", "commit": self.HEAD,
                                  "blockers": [self.blocker(line=3)], "notes": "n"})
        self.assertIsNone(problem)
        self.assertEqual(ok["blockers"][0]["line"], 3)

    def test_a_verdict_is_found_at_the_end_of_output(self):
        body = json.dumps({"verdict": "approve", "commit": self.HEAD, "blockers": []})
        for text in (body, f"thinking...\n```json\n{body}\n```\n", f"log {{x}}\n{body}\n"):
            with self.subTest(text=text[:12]):
                self.assertEqual(json.loads(verdicts.from_output(text))["verdict"], "approve")
        self.assertIsNone(verdicts.from_output("LGTM, ship it"))

    def test_a_verdict_after_quoted_code_is_found(self):
        # The real acceptance run's second review quoted code (```ts) before its fenced
        # verdict; the old whole-text fence regex paired the ts block's closing fence with
        # the json block's opening one, and a valid request-changes read as "no verdict".
        verdict = {"verdict": "request-changes", "commit": self.HEAD,
                   "blockers": [self.blocker(line=356)], "notes": "a regression"}
        body = json.dumps(verdict, indent=2)
        text = ("Looking at src/game/app.ts:\n\n```ts\nvoid this.#persist();\n"
                "void this.#leaveResultCard(() => this.#returnToTitle());\n```\n\n"
                "`#leaveResultCard` checks `canShowInterstitial` - see ```inline``` too.\n\n"
                f"```json\n{body}\n```\n")
        self.assertEqual(json.loads(verdicts.from_output(text)), verdict)
        # A quoted code block alone is not a verdict, and neither is a ts block's content.
        self.assertIsNone(verdicts.from_output("```ts\nconst x = {};\n```\n"))
        # The last fenced verdict wins over an earlier one.
        earlier = json.dumps(dict(verdict, verdict="approve", blockers=[]))
        self.assertEqual(json.loads(verdicts.from_output(
            f"```json\n{earlier}\n```\nOn reflection:\n```json\n{body}\n```"))["verdict"],
            "request-changes")

    def test_refusals(self):
        base = {"verdict": "request-changes", "commit": self.HEAD}
        cases = [
            ([1, 2], "JSON object"),
            ({"verdict": "approve", "blockers": []}, "missing 'commit'"),
            ({**base, "verdict": "lgtm", "blockers": []}, "must be one of"),
            ({**base, "commit": "A" * 40, "blockers": []}, "40-character"),
            ({**base, "blockers": [self.blocker(), self.blocker()]}, "not unique"),
            ({**base, "blockers": [self.blocker(severity="nit")]}, "severity"),
            ({**base, "blockers": [self.blocker(file="/etc/passwd")]}, "relative"),
            ({**base, "blockers": [self.blocker(file="../x")]}, "relative"),
            ({**base, "blockers": [self.blocker(line=0)]}, "positive integer"),
            ({**base, "blockers": [self.blocker(extra=1)]}, "keys the contract"),
            ({**base, "blockers": [{"id": "b"}]}, "missing 'file'"),
            ({**base, "blockers": "none"}, "must be a list"),
            ({**base, "blockers": [self.blocker()], "notes": 3}, "notes"),
        ]
        for data, fragment in cases:
            with self.subTest(fragment=fragment):
                verdict, problem = self.parse(data)
                self.assertIsNone(verdict)
                self.assertIn(fragment, problem)


@unittest.skipUnless(HAS_GIT, "git is not installed")
class Registration(unittest.TestCase):
    def test_the_module_registers_by_config(self):
        registry = StepRegistry().load_modules(["wgf_review"])
        self.assertIs(registry.resolve("review"), ReviewStep)

    def test_the_workflow_routes_request_changes_back_to_develop(self):
        from wgflib.workflow.definition import load_definition

        definition = load_definition("new-game")
        ids = definition.step_ids
        review = definition.step("review")
        self.assertEqual(ids[ids.index("develop") + 1], "review")
        self.assertEqual(ids[ids.index("review") + 1], "sdk")
        self.assertEqual(ids[ids.index("sdk") + 1], "sdk-review")
        self.assertEqual(ids[ids.index("sdk-review") + 1], "verify")
        self.assertEqual(review.on, {"request-changes": "develop"})
        self.assertEqual(definition.step("sdk-review").on, {"request-changes": "develop"})
        self.assertEqual(set(review.inputs), {"prototype-report", "game-design",
                                              "scaffold-record"})
        self.assertEqual(list(review.outputs), ["review-report"])
        self.assertIn("review-report", definition.step("develop").inputs)


def keep_live_evidence(case):
    """WGF_LIVE_KEEP=<dir>: copy a live run's scratch (review logs, verdicts, the checkout)
    there before it is removed - the transcript is the evidence of a paid run."""
    keep = os.environ.get("WGF_LIVE_KEEP")
    if keep:
        case.addCleanup(shutil.copytree, case.scratch, keep, symlinks=True, dirs_exist_ok=True)


class ShippedConfig(unittest.TestCase):
    """workspace/config/factory.yaml: what this installation actually runs the loop with."""

    PATH = os.path.join(SCRIPTS, os.pardir, "workspace", "config", "factory.yaml")

    def config(self):
        from wgflib.workflow.config import load_config

        return load_config(os.path.abspath(self.PATH)).data

    def test_the_shipped_config_guards_at_least_the_module_defaults(self):
        # A narrower list in the installation config silently undid the module's default
        # (core, scripts, bin, workspace/config): a reviewer could rewrite the Factory code or
        # the gates that judge the next review.
        from wgf_review.settings import Settings as ReviewSettings

        shipped = set(ReviewSettings.resolve(self.config()).guarded_paths)
        default = set(ReviewSettings.resolve({}).guarded_paths)
        self.assertLessEqual(default, shipped, sorted(default - shipped))

    def test_the_shipped_defaults_run_no_agent_host(self):
        from wgf_develop.settings import Settings as DevelopSettings
        from wgf_review.settings import Settings as ReviewSettings

        config = self.config()
        self.assertEqual(DevelopSettings.resolve(config).developer["kind"], "handoff")
        self.assertEqual(ReviewSettings.resolve(config).kind, "none")

    def test_the_commented_agent_host_examples_are_valid_config(self):
        # The documented developer/reviewer blocks, uncommented, must load and resolve, and
        # every argv element must survive the step's placeholder substitution.
        from wgflib.yamllite import load
        from wgf_develop.settings import Settings as DevelopSettings
        from wgf_review.settings import Settings as ReviewSettings

        with open(self.PATH, encoding="utf-8") as handle:
            lines = handle.read().splitlines()

        def block(key):
            start = next(i for i, line in enumerate(lines) if line == f"    # {key}:")
            out = [f"{key}:"]
            for line in lines[start + 1:]:
                if not line.startswith("    #   "):
                    break
                out.append(line[len("    # "):])
            return load("\n".join(out))

        developer, reviewer = block("developer"), block("reviewer")
        dev = DevelopSettings.resolve({"develop": developer})
        self.assertEqual(dev.developer["kind"], "command")
        review = ReviewSettings.resolve({"review": reviewer})
        self.assertEqual((review.kind, review.verdict_from, review.idle_timeout),
                         ("command", "stdout", None))
        values = {"brief": "B", "repo": "R", "key": "K", "prompt": "P", "verdict": "V",
                  "commit": "C"}
        for argv in (dev.developer["argv"], review.argv):
            formatted = [part.format(**values) for part in argv]
            self.assertEqual(formatted[:3], ["claude", "-p", "P"])
        tools = review.argv[review.argv.index("--tools") + 1].split(",")
        self.assertFalse({"Edit", "Write", "NotebookEdit"} & set(tools))
        self.assertIn("dontAsk", review.argv)
        self.assertIn("--safe-mode", review.argv)
        # stdout verdicts need plain text; json/stream-json output would wrap the verdict.
        self.assertEqual(review.argv[review.argv.index("--output-format") + 1], "text")


    def _opt_in_block(self):
        """The commented self-playtest opt-in: `self_playtest` and a `developer` block after
        the '--- opt-in: self-playtest' marker."""
        from wgflib.yamllite import load
        with open(self.PATH, encoding="utf-8") as handle:
            lines = handle.read().splitlines()
        marker = next(i for i, line in enumerate(lines) if "--- opt-in: self-playtest" in line)
        start = next(i for i in range(marker, len(lines)) if lines[i] == "    # self_playtest: true")
        out = []
        for line in lines[start:]:
            if not line.startswith("    # "):
                break
            out.append(line[len("    # "):])
        return load("\n".join(out))

    def test_the_self_playtest_opt_in_is_valid_and_keeps_the_restrictions(self):
        from wgf_develop.settings import Settings as DevelopSettings
        from wgflib import paths
        dev = DevelopSettings.resolve({"develop": self._opt_in_block()})
        self.assertTrue(dev.self_playtest)
        self.assertEqual(dev.developer["kind"], "command")
        values = {"brief": "B", "repo": "R", "key": "K", "prompt": "P", "factory": paths.ROOT}
        argv = [part.format(**values) for part in dev.developer["argv"]]
        self.assertEqual(argv[:3], ["claude", "-p", "P"])
        self.assertIn("--strict-mcp-config", argv)  # only the listed MCP config loads
        config = argv[argv.index("--mcp-config") + 1]
        plugin = argv[argv.index("--plugin-dir") + 1]
        self.assertTrue(os.path.isfile(config), config)
        self.assertTrue(os.path.isfile(os.path.join(plugin, ".claude-plugin", "plugin.json")))
        for path in (config, plugin):  # in the guarded Factory tree, never in a checkout
            self.assertTrue(os.path.realpath(path).startswith(os.path.realpath(paths.ROOT)))
        allowed = argv[argv.index("--allowedTools") + 1].split(",")
        self.assertIn("mcp__playwright", allowed)
        self.assertIn("Edit(./**)", allowed)
        self.assertNotIn("Edit", allowed)  # edits stay scoped to the checkout
        denied = argv[argv.index("--disallowedTools") + 1].split(",")
        self.assertTrue({"WebFetch", "WebSearch", "Bash(git commit *)",
                         "Bash(git push *)"} <= set(denied))
        self.assertIn("dontAsk", argv)

    def test_the_browser_is_limited_to_the_local_preview(self):
        import json
        path = os.path.join(SCRIPTS, os.pardir, "workspace", "config",
                            "mcp-playwright-localhost.json")
        with open(path, encoding="utf-8") as handle:
            servers = json.load(handle)["mcpServers"]
        self.assertEqual(list(servers), ["playwright"])
        args = servers["playwright"]["args"]
        package = next(a for a in args if a.startswith("@playwright/mcp@"))
        version = package.rsplit("@", 1)[1]
        self.assertRegex(version, r"^\d+\.\d+\.\d+$")  # pinned exactly, never latest/^/~
        self.assertIn("--headless", args)
        self.assertIn("--isolated", args)
        origins = args[args.index("--allowed-origins") + 1].split(";")
        self.assertTrue(origins)
        for origin in origins:
            self.assertRegex(origin, r"^http://(localhost|127\.0\.0\.1):\d+$")
        # Snapshots land outside the checkout (whose hidden paths the development commit
        # refuses) and outside the Factory.
        from wgflib import paths
        output = args[args.index("--output-dir") + 1]
        self.assertTrue(os.path.isabs(output))
        self.assertFalse(os.path.realpath(output).startswith(os.path.realpath(paths.ROOT)))

    def test_the_shipped_default_still_runs_no_agent_host_and_no_playtest(self):
        from wgf_develop.settings import Settings as DevelopSettings
        dev = DevelopSettings.resolve(self.config())
        self.assertEqual(dev.developer["kind"], "handoff")
        self.assertFalse(dev.self_playtest)


@unittest.skipUnless(os.environ.get("WGF_LIVE_AGENT") == "1"
                     and os.environ.get("WGF_LIVE_REVIEWER_ARGV") and HAS_GIT,
                     "live: set WGF_LIVE_AGENT=1 and WGF_LIVE_REVIEWER_ARGV to a JSON argv")
class LiveReviewer(AgentLoop):
    """A real agent host reviews a tiny repository with a planted bug. Costs money."""

    def test_a_live_reviewer_returns_a_trusted_verdict(self):
        keep_live_evidence(self)
        argv = json.loads(os.environ["WGF_LIVE_REVIEWER_ARGV"])
        timeout = float(os.environ.get("WGF_LIVE_TIMEOUT", "900"))
        state = self.run_workflow(dev_mode="bug-then-fix",
                                  reviewer={"argv": argv, "timeout_seconds": timeout,
                                            "idle_timeout_seconds": timeout,
                                            "verdict_from": os.environ.get(
                                                "WGF_LIVE_VERDICT_FROM", "stdout")},
                                  execution={"max_attempts": 1})
        reports = self.reports()
        self.assertTrue(reports, state.message)
        for report in reports:
            self.assert_valid(report)
            self.assertTrue(report["isolation"]["intact"], report["isolation"])
            self.assertIn(report["verdict"], ("approve", "request-changes"),
                          report.get("failure"))
        # A competent reviewer finds the planted underflow, and sees the fix. It may still
        # request changes after that: the scripted game is a stub that does not meet the
        # brief (empty seam, direct SDK call), and a live host says so. The earlier "and
        # approves" asserted a pass no competent host could give, and a live reviewer's own
        # blocker id never matched the scripted developer's, so the fix was never made either
        # (both fixed at the Core v1 audit, docs/claude-capabilities.md).
        def on_score(report):
            return [b for b in report["blockers"] if b.get("file") == "src/game/score.ts"]

        self.assertEqual(reports[0]["verdict"], "request-changes")
        self.assertTrue(on_score(reports[0]), reports[0]["blockers"])
        self.assertGreater(len(reports), 1, state.message)
        for later in reports[1:]:
            self.assertEqual(on_score(later), [], later["blockers"])
        if state.status != RunStatus.COMPLETED:
            self.assertEqual(state.status, RunStatus.BLOCKED, state.message)
            self.assertIn("loop limit", state.message)
            self.assertEqual(reports[-1]["verdict"], "request-changes")


@unittest.skipUnless(os.environ.get("WGF_LIVE_AGENT") == "1"
                     and os.environ.get("WGF_LIVE_DEVELOPER_ARGV")
                     and os.environ.get("WGF_LIVE_REVIEWER_ARGV") and HAS_GIT,
                     "live: set WGF_LIVE_AGENT=1, WGF_LIVE_DEVELOPER_ARGV and "
                     "WGF_LIVE_REVIEWER_ARGV to JSON argvs")
class LiveDeveloperAndReviewer(AgentLoop):
    """A real agent host develops AND a real one reviews, through the real engine. Costs money.

    The developer argv may use {brief}; the conformance scaffolding around it is scripted
    (see DEVELOPER's live-exec mode) so only the host's own edits are under test: an edit to
    src/game/app.ts on visit 1, and the fix for the reviewer's blocker on visit 2."""

    MARKER = "live-smoke: edited by the developer agent"

    def test_live_developer_and_live_reviewer_loop(self):
        timeout = float(os.environ.get("WGF_LIVE_TIMEOUT", "900"))
        os.environ["WGF_TEST_LIVE_DEV_ARGV"] = os.environ["WGF_LIVE_DEVELOPER_ARGV"]
        self.addCleanup(os.environ.pop, "WGF_TEST_LIVE_DEV_ARGV", None)
        keep_live_evidence(self)
        state = self.run_workflow(
            dev_mode="live-exec",
            developer={"timeout_seconds": timeout, "idle_timeout_seconds": timeout},
            reviewer={"argv": json.loads(os.environ["WGF_LIVE_REVIEWER_ARGV"]),
                      "timeout_seconds": timeout, "idle_timeout_seconds": timeout,
                      "verdict_from": os.environ.get("WGF_LIVE_VERDICT_FROM", "stdout")},
            execution={"max_attempts": 1})
        reviews = self.reports()
        prototypes = self.reports("prototype-report")
        self.assertTrue(reviews, state.message)
        for report in reviews:
            self.assert_valid(report)
            self.assertTrue(report["isolation"]["intact"], report["isolation"])
            self.assertIn(report["verdict"], ("approve", "request-changes"),
                          report.get("failure"))
        # Visit 1: the host's own edit is in the commit develop made and review saw.
        first = prototypes[0]["build_ref"]["commit_sha"]
        self.assertEqual(reviews[0]["reviewed_commit"], first)
        self.assertIn(self.MARKER, self.git("show", f"{first}:src/game/app.ts"))
        # The reviewer found the planted bug; the host fixed it; the reviewer approved.
        self.assertEqual(reviews[0]["verdict"], "request-changes")
        self.assertEqual(reviews[-1]["verdict"], "approve")
        self.assertEqual(state.status, RunStatus.COMPLETED, state.message)
        last = prototypes[-1]["build_ref"]["commit_sha"]
        self.assertNotEqual(first, last)
        self.assertEqual(reviews[-1]["reviewed_commit"], last)
        self.assertNotIn("return lives - 1;", self.git("show", f"{last}:src/game/score.ts"))
        self.assertEqual(self.git("status", "--porcelain"), "")
        # Developer and reviewer are single, bounded processes: no stragglers were killed.
        for report in reviews:
            self.assertEqual(report["reviewer"]["killed_pids"], [], report["reviewer"])


# Only the live classes run the loop against a live host; do not rerun AgentLoop's tests in
# them.
for _name in [n for n in dir(AgentLoop) if n.startswith("test_")]:
    setattr(LiveReviewer, _name, None)
    setattr(LiveDeveloperAndReviewer, _name, None)


if __name__ == "__main__":
    unittest.main()

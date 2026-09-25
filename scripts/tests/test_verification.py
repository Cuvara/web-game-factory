"""The verification module (scripts/wgf_verification), tested against fixtures.

Every command the module would run - git, pnpm, node, Playwright - goes through a scripted
FakeRunner that plays the part of a game repository: a build copies a fixture bundle into
place, the e2e suite writes a fixture Playwright report, and so on. Nothing here needs a
package manager, a browser or the network.

Deterministic and offline. Run from the repository root:

    python3 -m unittest discover scripts/tests
"""

import copy
import json
import os
import shutil
import sys
import tempfile
import textwrap
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, HERE)

from test_workflow_contracts import tree_digest  # noqa: E402
from wgf_verification import VerifyStep, register  # noqa: E402
from wgf_verification.checks.code import test_counts  # noqa: E402
from wgf_verification.checks.gameplay import map_report, required_aspects  # noqa: E402
from wgf_verification.runner import CommandResult  # noqa: E402
from wgf_verification.session import VerificationSession  # noqa: E402
from wgflib.hashing import content_hash  # noqa: E402
from wgflib.workflow import StepOutcome, StepRegistry, WorkflowStep  # noqa: E402
from wgflib.workflow.api import RunRequest, WorkflowAPI  # noqa: E402
from wgflib.workflow.config import FactoryConfig  # noqa: E402
from wgflib.workflow.contracts import ArtifactContracts  # noqa: E402
from wgflib.workflow.definition import StepDefinition  # noqa: E402
from wgflib.workflow.model import ArtifactOutput, ArtifactRef, RunStatus, StepResult  # noqa: E402

FIXTURES = os.path.join(HERE, "fixtures", "verification")
MOCK_FIXTURES = os.path.join(SCRIPTS, "wgflib", "workflow", "fixtures")
WORKFLOW_PACKAGE = os.path.join(SCRIPTS, "wgflib", "workflow")
COMMIT = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
NOW = "2026-09-23T10:00:00Z"
CONTRACTS = ArtifactContracts()


def fixture(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as handle:
        return json.loads(handle.read().replace("__COMMIT__", COMMIT))


def read_json(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def with_provenance(artifact_type, body, sequence=1):
    artifact = {"provenance": {
        "artifact_id": f"wgf:{artifact_type}:fixture-game:20260901-{sequence:02d}",
        "artifact_type": artifact_type,
        "schema_version": "1.0.0",
        "title_id": "fixture-game",
        "produced_by": {"role": "qa", "actor": "automation"},
        "produced_at": "2026-09-01T00:00:00Z",
        "inputs": [],
        "content_hash": "",
        "status": "draft",
    }}
    artifact.update(copy.deepcopy(body))
    artifact["provenance"]["content_hash"] = content_hash(artifact)
    return artifact


# -- a scripted game repository -----------------------------------------------------------

def ok(stdout=""):
    return CommandResult([], exit_code=0, stdout=stdout)


def failing(stdout="", code=1):
    return CommandResult([], exit_code=code, stdout=stdout)


class FakeRunner:
    """Plays a healthy game repository unless a test overrides a command.

    Handlers are keyed by a substring of the joined command and receive (command, cwd, env).
    The first key contained in the command wins, so more specific keys come first.
    """

    def __init__(self, overrides=None):
        self.calls = []
        self.handlers = dict(overrides or {})
        for key, handler in self.defaults().items():
            self.handlers.setdefault(key, handler)

    def defaults(self):
        return {
            "rev-parse": lambda c, cwd, env: ok(COMMIT + "\n"),
            "status --porcelain": lambda c, cwd, env: ok(""),
            "install": lambda c, cwd, env: ok("Done"),
            "pnpm build": self.build,
            "run typecheck": lambda c, cwd, env: ok(),
            "run lint": lambda c, cwd, env: ok(),
            "run test:unit": lambda c, cwd, env: ok(" Test Files  7 passed (7)\n"
                                                     "      Tests  24 passed (24)\n"),
            "run test:integration": lambda c, cwd, env: ok("      Tests  3 passed (3)\n"),
            "run test:e2e": self.e2e,
            "run test:verify": self.runtime_facts,
            "collect-facts": self.collect,
            "evaluate-assertions": self.evaluate,
        }

    def run(self, command, cwd, timeout=None, env=None):
        self.calls.append(" ".join(command))
        joined = " ".join(command)
        for key, handler in self.handlers.items():
            if key in joined:
                result = handler(command, cwd, env or {})
                result.command = list(command)
                return result
        raise AssertionError(f"unexpected command: {joined}")

    def ran(self, fragment):
        return any(fragment in call for call in self.calls)

    # -- default behaviour of a healthy repository ----------------------------------------

    @staticmethod
    def build(command, cwd, env):
        shutil.copytree(os.path.join(FIXTURES, "bundle"), os.path.join(cwd, "dist"),
                        dirs_exist_ok=True)
        return ok("vite v6 building for production...\n✓ built in 1.2s")

    @staticmethod
    def e2e(command, cwd, env):
        shutil.copy(os.path.join(FIXTURES, "playwright-e2e.json"),
                    env["PLAYWRIGHT_JSON_OUTPUT_NAME"])
        return ok()

    @staticmethod
    def runtime_facts(command, cwd, env):
        os.makedirs(os.path.join(cwd, "build"), exist_ok=True)
        shutil.copy(os.path.join(FIXTURES, "runtime-facts.json"),
                    os.path.join(cwd, "build", "runtime-facts.json"))
        return ok("1 passed")

    @staticmethod
    def collect(command, cwd, env):
        out = os.path.join(cwd, command[command.index("--out") + 1])
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "w") as handle:
            json.dump({"package": {}}, handle)
        return ok()

    @staticmethod
    def evaluate(command, cwd, env, results=None):
        platform = command[command.index("--platform") + 1]
        out = os.path.join(cwd, command[command.index("--out") + 1])
        os.makedirs(os.path.dirname(out), exist_ok=True)
        data = results if results is not None else fixture(f"assertions-{platform}.json")
        with open(out, "w") as handle:
            json.dump(data, handle)
        blocking = any(r["breached"] and r["severity"] == "blocking" for r in data)
        return failing() if blocking else ok()


# -- fakes for the step's inputs and context ------------------------------------------------

class FakeLogger:
    def __init__(self):
        self.records = []

    def _log(self, level, message, **fields):
        self.records.append((level, message, fields))

    def info(self, message, **fields):
        self._log("info", message, **fields)

    debug = warning = error = info


class FakeInputs:
    def __init__(self, artifacts, missing=(), schema_version="1.0.0"):
        self.contents = {t: with_provenance(t, body) for t, body in artifacts.items()}
        self.refs = {
            t: ArtifactRef(id=t, type=t, version=1, location=f"artifacts/{t}/v1.json",
                           checksum="sha256:" + "0" * 64, produced_by="upstream",
                           created_at="2026-09-01T00:00:00Z",
                           content_hash=content["provenance"]["content_hash"],
                           schema_version=schema_version)
            for t, content in self.contents.items()}
        self.missing = list(missing)

    def __contains__(self, artifact_type):
        return artifact_type in self.refs

    def load(self, artifact_type):
        return self.contents.get(artifact_type)


class FakeContext:
    def __init__(self, config=None, execution=1):
        self.config = config or {}
        self.execution = execution
        self.visit = execution
        self.attempt = 1
        self.run_id = "run-1"
        self.current_step = "verify"
        self.idempotency_key = f"run-1:verify:{execution}"
        self.project_id = None
        self.environment = {}
        self.logger = FakeLogger()


class VerificationCase(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.mkdtemp(prefix="wgf-verify-")
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)
        self.repo = os.path.join(self.scratch, "fixture-game")
        shutil.copytree(os.path.join(FIXTURES, "game"), self.repo)
        self.runner = FakeRunner()

    def step(self, runner=None, **params):
        params.setdefault("repo_dir", self.repo)
        params = {k: v for k, v in params.items() if v is not None}
        definition = StepDefinition({
            "id": "verify", "type": "verify",
            "inputs": ["prototype-report", "sdk-report", "game-design", "scaffold-record",
                       "asset-manifest"],
            "outputs": ["verification-report", "qa-report"],
            "with": params}, retry=None, max_visits=None)
        step = VerifyStep(definition)
        runner = runner or self.runner
        step.runner_factory = lambda: runner
        step.clock = staticmethod(lambda: NOW)
        step.environ = {}
        return step

    def inputs(self, **extra):
        artifacts = {"sdk-report": fixture("inputs/sdk-report.json"),
                     "asset-manifest": fixture("inputs/asset-manifest.json")}
        artifacts.update(extra)
        return FakeInputs({k: v for k, v in artifacts.items() if v is not None})

    def verify(self, inputs=None, runner=None, **params):
        result = self.step(runner, **params).execute(inputs or self.inputs(), FakeContext())
        self.assertIsInstance(result, StepResult)
        reports = {a.type: a.content for a in result.artifacts}
        self.assertEqual(set(reports), {"verification-report", "qa-report"})
        for artifact_type, content in reports.items():
            self.assertEqual(CONTRACTS(artifact_type, content), [], artifact_type)
        return result, reports["verification-report"], reports["qa-report"]

    @staticmethod
    def check(report, check_id):
        for check in report["checks"]:
            if check["id"] == check_id:
                return check
        raise AssertionError(f"no check {check_id}: {[c['id'] for c in report['checks']]}")

    def write(self, relative, text):
        path = os.path.join(self.repo, relative)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)


# -- outcomes -------------------------------------------------------------------------------

class Outcomes(VerificationCase):
    def test_a_healthy_game_passes_with_evidence_for_every_check(self):
        result, report, qa = self.verify()

        self.assertEqual(result.outcome, StepOutcome.SUCCESS)
        self.assertIsNone(result.route)
        self.assertEqual(report["verdict"], "PASS")
        self.assertEqual(report["failed_checks"], [])
        self.assertEqual(report["blocked_checks"], [])
        self.assertEqual(report["commit"]["sha"], COMMIT)
        self.assertEqual(report["build_artifact"]["status"], "built")
        self.assertTrue(report["build_artifact"]["content_hash"].startswith("sha256:"))
        self.assertEqual(report["gameplay_driver"]["id"], "repository-playwright")
        self.assertEqual(
            {c["category"] for c in report["checks"]},
            {"source", "build", "code", "gameplay", "platform", "assets", "policy"})
        for check in report["checks"]:
            self.assertTrue(check["evidence"], check["id"])
        self.assertEqual(report["summary"]["total"], len(report["checks"]))
        self.assertEqual(sum(report["summary"][s] for s in ("PASS", "FAIL", "BLOCKED",
                                                           "WARNING")),
                         report["summary"]["total"])

        # Uncovered optional aspects are warnings, never silent passes.
        self.assertEqual(self.check(report, "gameplay.game-over")["status"], "WARNING")
        self.assertIn("gameplay.game-over", report["warning_checks"])

        self.assertEqual(qa["verdict"], "pass")
        self.assertEqual(qa["blocking_defects"], [])
        self.assertEqual(qa["build_ref"], {"commit_sha": COMMIT, "artifact_hash":
                                           report["build_artifact"]["content_hash"]})
        suites = {s["name"]: s for s in qa["suites"]}
        self.assertEqual(suites["unit"]["passed"], 24)
        self.assertEqual(suites["e2e"], {"name": "e2e", "passed": 5, "failed": 0, "skipped": 1})
        self.assertEqual(qa["perf_results"][0]["fps"], 41.5)
        self.assertTrue(qa["perf_results"][0]["within_budget"])
        self.assertEqual({b["platform"] for b in qa["browser_matrix"]}, {"desktop", "mobile"})

    def test_the_qa_report_pins_the_verification_report_it_was_computed_from(self):
        _, report, qa = self.verify()
        pins = {p["artifact_type"]: p for p in qa["provenance"]["inputs"]}
        self.assertEqual(pins["verification-report"]["content_hash"],
                         report["provenance"]["content_hash"])
        self.assertEqual(pins["sdk-report"]["content_hash"],
                         self.inputs().refs["sdk-report"].content_hash)
        self.assertEqual(report["provenance"]["artifact_id"],
                         "wgf:verification-report:fixture-game:20260923-01")

    def test_a_failing_check_returns_fail_for_the_workflow_to_route(self):
        runner = FakeRunner({"run lint": lambda c, cwd, env: failing(
            "src/game.ts\n  12:5  error  'score' is never reassigned  prefer-const\n")})
        result, report, qa = self.verify(runner=runner)

        self.assertEqual(result.outcome, StepOutcome.FAILED)
        self.assertEqual(result.route, "fail")
        self.assertFalse(result.retryable)
        self.assertIn("code.lint", result.error)
        self.assertEqual(report["verdict"], "FAIL")
        self.assertEqual(report["failed_checks"], ["code.lint"])
        lint = self.check(report, "code.lint")
        self.assertEqual(lint["evidence"][0]["exit_code"], 1)
        self.assertIn("prefer-const", lint["evidence"][0]["output_tail"])

        self.assertEqual(qa["verdict"], "fail")
        defect = qa["blocking_defects"][0]
        self.assertEqual((defect["id"], defect["severity"]), ("vr-code-lint", "blocker"))
        self.assertIn("pnpm run lint", defect["repro"])

    def test_no_checkout_blocks_and_still_reports(self):
        result, report, qa = self.verify(repo_dir=os.path.join(self.scratch, "absent"))

        self.assertEqual(result.outcome, StepOutcome.BLOCKED)
        self.assertEqual(report["verdict"], "BLOCKED")
        self.assertEqual([c["id"] for c in report["checks"]], ["source.checkout"])
        self.assertEqual(report["commit"]["sha"], None)
        self.assertEqual(report["build_artifact"], {"status": "not-built"})
        self.assertEqual(qa["verdict"], "fail")
        self.assertEqual(qa["build_ref"]["commit_sha"], "unknown")
        self.assertEqual(self.runner.calls, [])

    def test_the_checkout_is_found_from_config_and_the_scaffold_record(self):
        scaffold = read_json(os.path.join(MOCK_FIXTURES, "scaffold-record.json"))
        scaffold["repository"]["name"] = "fixture-game"
        step = self.step(repo_dir=None)
        context = FakeContext(config={"verification": {"checkouts": self.scratch}})
        result = step.execute(self.inputs(**{"scaffold-record": scaffold}), context)
        report = result.artifacts[0].content
        self.assertEqual(self.check(report, "source.checkout")["status"], "PASS")
        self.assertIn("verification.checkouts", self.check(report, "source.checkout")
                      ["evidence"][0]["summary"])

    def test_a_missing_tool_blocks_rather_than_fails(self):
        runner = FakeRunner({"install": lambda c, cwd, env: CommandResult(
            c, error="not found (pnpm)")})
        result, report, _ = self.verify(runner=runner)
        self.assertEqual(result.outcome, StepOutcome.BLOCKED)
        self.assertEqual(self.check(report, "build.install")["status"], "BLOCKED")
        self.assertEqual(self.check(report, "code.lint")["status"], "BLOCKED")
        self.assertEqual(self.check(report, "code.lint")["evidence"][0]["check_ref"],
                         "build.install")
        self.assertFalse(runner.ran("run lint"))

    def test_a_failed_build_blocks_what_depends_on_it_and_fails_the_verdict(self):
        runner = FakeRunner({"pnpm build": lambda c, cwd, env: failing(
            "error TS2307: Cannot find module './missing'")})
        result, report, _ = self.verify(runner=runner)
        self.assertEqual(result.route, "fail")
        self.assertEqual(self.check(report, "build.build")["status"], "FAIL")
        for dependent in ("build.bundle", "gameplay.boot", "policy.runtime-facts",
                          "policy.assertions:generic-web"):
            self.assertEqual(self.check(report, dependent)["status"], "BLOCKED", dependent)
        self.assertFalse(runner.ran("test:e2e"))
        self.assertEqual(report["build_artifact"], {"status": "not-built"})

    def test_a_newer_major_schema_is_refused(self):
        inputs = FakeInputs({"sdk-report": fixture("inputs/sdk-report.json")},
                            schema_version="2.0.0")
        result = self.step().execute(inputs, FakeContext())
        self.assertEqual(result.outcome, StepOutcome.FAILED)
        self.assertFalse(result.retryable)
        self.assertEqual(self.runner.calls, [])

    def test_the_same_verification_twice_produces_the_same_reports(self):
        _, first, qa_first = self.verify()
        _, second, qa_second = self.verify(runner=FakeRunner())
        self.assertEqual(first["provenance"]["content_hash"],
                         second["provenance"]["content_hash"])
        self.assertEqual(qa_first["provenance"]["content_hash"],
                         qa_second["provenance"]["content_hash"])


# -- build, code and source -------------------------------------------------------------------

class BuildAndCode(VerificationCase):
    def test_an_unresolved_bundle_reference_fails_asset_resolution(self):
        def build(command, cwd, env):
            FakeRunner.build(command, cwd, env)
            with open(os.path.join(cwd, "dist", "assets", "index-3f2a.js"), "a") as handle:
                handle.write('const boss="assets/boss.png";\n')
            return ok()

        _, report, _ = self.verify(runner=FakeRunner({"pnpm build": build}))
        check = self.check(report, "build.asset-resolution")
        self.assertEqual(check["status"], "FAIL")
        self.assertIn("assets/boss.png", json.dumps(check["evidence"]))

    def test_a_build_without_an_entry_point_fails_the_bundle(self):
        def build(command, cwd, env):
            FakeRunner.build(command, cwd, env)
            os.remove(os.path.join(cwd, "dist", "index.html"))
            return ok()

        _, report, _ = self.verify(runner=FakeRunner({"pnpm build": build}))
        self.assertEqual(self.check(report, "build.bundle")["status"], "FAIL")

    def test_a_dirty_tree_is_a_warning_and_a_stale_upstream_commit_blocks(self):
        prototype = read_json(os.path.join(MOCK_FIXTURES, "prototype-report.json"))
        runner = FakeRunner({"status --porcelain": lambda c, cwd, env: ok(" M src/main.ts\n")})
        result, report, _ = self.verify(
            inputs=self.inputs(**{"prototype-report": prototype}), runner=runner)
        # Evidence about another commit cannot vouch for this one.
        self.assertEqual(result.outcome, StepOutcome.BLOCKED)
        self.assertEqual(self.check(report, "source.clean-tree")["status"], "WARNING")
        self.assertTrue(report["commit"]["dirty"])
        upstream = self.check(report, "source.upstream-commits")
        self.assertEqual(upstream["status"], "BLOCKED")
        self.assertTrue(upstream["required"])
        self.assertIn("prototype-report", upstream["message"])

    def test_a_dirty_tree_alone_is_a_warning(self):
        runner = FakeRunner({"status --porcelain": lambda c, cwd, env: ok(" M src/main.ts\n")})
        result, report, _ = self.verify(runner=runner)
        self.assertEqual(result.outcome, StepOutcome.SUCCESS)
        self.assertEqual(self.check(report, "source.clean-tree")["status"], "WARNING")
        self.assertTrue(report["commit"]["dirty"])

    def test_a_missing_required_script_blocks(self):
        package = read_json(os.path.join(self.repo, "package.json"))
        del package["scripts"]["typecheck"]
        del package["scripts"]["test:integration"]
        self.write("package.json", json.dumps(package))
        result, report, _ = self.verify()
        self.assertEqual(self.check(report, "code.typecheck")["status"], "BLOCKED")
        # Integration is not required: its absence is a warning.
        self.assertEqual(self.check(report, "code.integration")["status"], "WARNING")
        self.assertEqual(result.outcome, StepOutcome.BLOCKED)

    def test_test_counts_are_read_from_a_vitest_summary(self):
        self.assertEqual(test_counts(" Test Files  2 passed (2)\n      Tests  1 failed | 11 "
                                     "passed | 2 skipped (14)\n"),
                         {"passed": 11, "failed": 1, "skipped": 2})
        self.assertIsNone(test_counts("no summary here"))


# -- gameplay -------------------------------------------------------------------------------

class Gameplay(VerificationCase):
    def record_session(self, **changes):
        session = fixture("gameplay-session.json")
        session.update(changes)
        self.write("build/verification/gameplay-session.json", json.dumps(session))
        return session

    def test_a_fresh_recorded_session_is_used_instead_of_the_repository_suite(self):
        self.record_session()
        design = fixture("inputs/game-design.json")
        result, report, qa = self.verify(inputs=self.inputs(**{"game-design": design}))

        self.assertEqual(result.outcome, StepOutcome.SUCCESS)
        self.assertEqual(report["gameplay_driver"]["id"], "playwright-mcp")
        self.assertFalse(self.runner.ran("test:e2e"))
        for aspect in ("boot", "start", "input", "core-loop", "progression", "game-over",
                       "restart", "responsive"):
            check = self.check(report, f"gameplay.{aspect}")
            self.assertEqual((check["status"], check["required"]), ("PASS", True), aspect)
        self.assertEqual(self.check(report, "gameplay.input")["evidence"][0]["data"]["steps"],
                         ["press ArrowLeft", "read lane from HUD"])
        self.assertEqual(self.check(report, "assets.loading")["status"], "PASS")
        self.assertEqual(qa["browser_matrix"][1]["platform"], "mobile-393x851")

    def test_a_stale_recorded_session_falls_back_to_the_repository_suite(self):
        self.record_session(commit_sha="0" * 40)
        _, report, _ = self.verify()
        self.assertEqual(report["gameplay_driver"]["id"], "repository-playwright")
        self.assertTrue(self.runner.ran("test:e2e"))
        evidence = json.dumps(self.check(report, "gameplay.game-over")["evidence"])
        self.assertIn("recorded session not used", evidence)
        self.assertIn("not the commit under test", evidence)

    def test_the_recorded_driver_can_be_required_and_then_blocks_without_a_session(self):
        result, report, _ = self.verify(browser="recorded")
        self.assertEqual(result.outcome, StepOutcome.BLOCKED)
        self.assertEqual(self.check(report, "gameplay.boot")["status"], "BLOCKED")
        self.assertFalse(self.runner.ran("test:e2e"))

    def test_a_failed_scenario_and_failed_requests_fail_the_verdict(self):
        session = fixture("gameplay-session.json")
        session["scenarios"][7] = {"aspect": "restart", "status": "FAIL",
                                   "observation": "Clicked Retry; the canvas stayed black."}
        self.record_session(scenarios=session["scenarios"],
                            failed_requests=["GET /assets/music.ogg 404"])
        design = fixture("inputs/game-design.json")
        result, report, _ = self.verify(inputs=self.inputs(**{"game-design": design}))
        self.assertEqual(result.route, "fail")
        self.assertEqual(self.check(report, "gameplay.restart")["status"], "FAIL")
        self.assertEqual(self.check(report, "assets.loading")["status"], "FAIL")
        self.assertIn("music.ogg", json.dumps(self.check(report, "assets.loading")))

    def test_console_errors_fail_boot(self):
        self.record_session(console_errors=["TypeError: cannot read 'x' of undefined"])
        result, report, _ = self.verify()
        self.assertEqual(self.check(report, "gameplay.boot")["status"], "FAIL")
        self.assertEqual(result.route, "fail")

    def test_a_designed_aspect_nobody_tested_fails_so_development_adds_the_test(self):
        design = fixture("inputs/game-design.json")
        result, report, _ = self.verify(inputs=self.inputs(**{"game-design": design}))
        self.assertEqual(result.route, "fail")
        check = self.check(report, "gameplay.game-over")
        self.assertEqual((check["status"], check["required"]), ("FAIL", True))
        self.assertIn("must provide a test", check["message"])
        # Covered by the template smoke suite: boot, loading, core loop, and mobile.
        for aspect in ("boot", "loading", "core-loop", "responsive"):
            self.assertEqual(self.check(report, f"gameplay.{aspect}")["status"], "PASS")

    def test_a_failing_e2e_test_fails_the_aspects_it_covers(self):
        broken = fixture("playwright-e2e.json")
        spec = broken["suites"][0]["specs"][0]
        spec["tests"][1] = {"projectName": "mobile", "status": "unexpected",
                            "results": [{"status": "failed", "error": {
                                "message": "\x1b[31mTimed out 15000ms waiting for "
                                           "data-ready\x1b[39m\nCall log: ..."}}]}

        def e2e(command, cwd, env):
            with open(env["PLAYWRIGHT_JSON_OUTPUT_NAME"], "w") as handle:
                json.dump(broken, handle)
            return failing()

        _, report, qa = self.verify(runner=FakeRunner({"run test:e2e": e2e}))
        responsive = self.check(report, "gameplay.responsive")
        self.assertEqual(responsive["status"], "FAIL")
        self.assertIn("Timed out 15000ms waiting for data-ready", json.dumps(responsive))
        self.assertNotIn("\\u001b", json.dumps(responsive))
        self.assertIn({"browser": "chromium", "platform": "mobile", "result": "fail"},
                      qa["browser_matrix"])

    def test_a_suite_that_never_ran_because_browsers_are_missing_blocks(self):
        runner = FakeRunner({"run test:e2e": lambda c, cwd, env: failing(
            "browserType.launch: Executable doesn't exist at /ms-playwright/chromium\n"
            "Please run: pnpm exec playwright install")})
        result, report, _ = self.verify(runner=runner)
        self.assertEqual(self.check(report, "gameplay.boot")["status"], "BLOCKED")
        self.assertEqual(result.outcome, StepOutcome.BLOCKED)

    def test_tags_map_tests_to_aspects_before_keywords(self):
        report = {"suites": [{"title": "play.spec.ts", "specs": [
            {"title": "the ship explodes", "tags": ["@game-over"],
             "tests": [{"projectName": "desktop", "status": "expected"}]},
            {"title": "retry after crash @restart",
             "tests": [{"projectName": "desktop", "status": "expected"}]},
        ]}]}
        seen = map_report(report, "report.json")
        self.assertEqual(len(seen.aspects["game-over"]), 1)
        self.assertEqual(len(seen.aspects["restart"]), 1)
        self.assertEqual(seen.aspects["boot"], [])

    def test_browser_commands_cannot_reach_a_portal(self):
        # The acceptance run's lesson: a portal build's real SDK, loaded from its CDN during
        # a browser suite, makes the game's own "no insecure requests" and the runtime facts
        # measure the portal. Browser commands run behind the refusing proxy; others do not.
        import urllib.error
        import urllib.request
        seen = {}

        def browser(command, cwd, env):
            seen["browser_env"] = dict(env or {})
            opener = urllib.request.build_opener(urllib.request.ProxyHandler(
                {"https": env["https_proxy"]} if env and "https_proxy" in env else {}))
            try:
                opener.open("https://game-cdn.poki.com/scripts/v2/poki-sdk.js", timeout=5)
                seen["portal"] = "reached"
            except urllib.error.URLError as exc:
                seen["portal"] = str(exc.reason)
            return ok()

        def script(command, cwd, env):
            seen["script_env"] = dict(env or {})
            return ok()

        runner = FakeRunner({"run test:verify": browser, "run lint": script})
        session = VerificationSession(self.repo, runner)
        session.run(session.script_command("test:verify"), "browser")
        session.run(session.script_command("lint"))
        self.assertIn("403", seen["portal"])
        self.assertEqual(seen["browser_env"]["no_proxy"], "localhost,127.0.0.1,::1")
        self.assertNotIn("https_proxy", seen["script_env"])
        self.assertEqual(session.network_refusals[0]["refused_requests"], 1)
        self.assertEqual(session.network_refusals[0]["targets"],
                         ["CONNECT game-cdn.poki.com:443"])

    def test_required_aspects_follow_the_design(self):
        session = VerificationSession(self.repo, self.runner)
        self.assertEqual(required_aspects(session), {"boot", "loading", "core-loop", "responsive"})
        design = fixture("inputs/game-design.json")
        design["monetization"]["placements"] = [{"kind": "rewarded"}]
        session.inputs = {"game-design": design}
        self.assertEqual(required_aspects(session),
                         {"boot", "loading", "core-loop", "responsive", "start", "input",
                          "game-over", "restart", "progression", "pause-resume"})
        session.params = {"gameplay": {"required": ["boot"]}}
        self.assertEqual(required_aspects(session), {"boot"})


# -- platform and policy --------------------------------------------------------------------

class PlatformAndPolicy(VerificationCase):
    def add_platform(self, entry):
        with open(os.path.join(self.repo, "game.config.yaml")) as handle:
            text = handle.read()
        text = text.replace("  - { id: generic-web, profile: generic-web@1.0.0, role: required }",
                            "  - { id: generic-web, profile: generic-web@1.0.0, role: required }"
                            "\n  " + entry)
        self.write("game.config.yaml", text)

    def test_readiness_never_claims_external_approval(self):
        _, report, qa = self.verify()
        (entry,) = report["platform_readiness"]
        self.assertEqual(entry["platform_id"], "generic-web")
        self.assertEqual(entry["readiness"], "ready")
        self.assertEqual(entry["external_approval"], "not-claimed")
        self.assertIn("does not claim", entry["note"])
        self.assertEqual(qa["platform_checks"][0]["result"], "pass")
        self.assertNotIn("approved", json.dumps(report).replace("does not claim", ""))

    def test_a_blocking_assertion_breach_fails(self):
        results = fixture("assertions-generic-web.json")
        results[0].update(measured=2, breached=True)
        runner = FakeRunner({"evaluate-assertions": lambda c, cwd, env: FakeRunner.evaluate(
            c, cwd, env, results=results)})
        result, report, _ = self.verify(runner=runner)
        check = self.check(report, "policy.assertions:generic-web")
        self.assertEqual(check["status"], "FAIL")
        self.assertIn("generic_web_https_only", check["message"])
        self.assertEqual(report["platform_readiness"][0]["readiness"], "not-ready")
        self.assertEqual(result.route, "fail")

    def test_a_warning_assertion_does_not_change_the_verdict(self):
        results = fixture("assertions-generic-web.json") + [{
            "criterion_id": "generic_web_fps", "measured": 20, "breached": True,
            "evaluated_at": NOW, "severity": "warning"}]
        runner = FakeRunner({"evaluate-assertions": lambda c, cwd, env: FakeRunner.evaluate(
            c, cwd, env, results=results)})
        result, report, _ = self.verify(runner=runner)
        self.assertEqual(self.check(report, "policy.assertions:generic-web")["status"],
                         "WARNING")
        self.assertEqual(result.outcome, StepOutcome.SUCCESS)

    def test_missing_sdk_evidence_blocks(self):
        result, report, _ = self.verify(inputs=self.inputs(**{"sdk-report": None}))
        self.assertEqual(self.check(report, "platform.sdk-init:generic-web")["status"],
                         "BLOCKED")
        self.assertEqual(report["platform_readiness"][0]["readiness"], "unverified")
        self.assertEqual(result.outcome, StepOutcome.BLOCKED)

    def test_an_optional_platform_that_is_not_ready_does_not_block_release(self):
        self.add_platform("- { id: yandex, profile: yandex@1.0.0, role: optional }")
        results = {"generic-web": fixture("assertions-generic-web.json"),
                   "yandex": [{"criterion_id": "yandex_sdk_present", "measured": "none",
                               "breached": True, "evaluated_at": NOW, "severity": "blocking"}]}
        runner = FakeRunner({"evaluate-assertions": lambda c, cwd, env: FakeRunner.evaluate(
            c, cwd, env, results=results[c[c.index("--platform") + 1]])})
        result, report, _ = self.verify(runner=runner)

        self.assertEqual(result.outcome, StepOutcome.SUCCESS)
        readiness = {r["platform_id"]: r for r in report["platform_readiness"]}
        self.assertEqual(readiness["generic-web"]["readiness"], "ready")
        self.assertEqual(readiness["yandex"]["readiness"], "not-ready")
        self.assertIn("platform.sdk-init:yandex", readiness["yandex"]["blocking_checks"])
        self.assertIn("policy.assertions:yandex", readiness["yandex"]["blocking_checks"])
        # Its profile is the Factory's own, because the fixture vendors only generic-web.
        self.assertIn("core/reference/platforms/yandex.yaml",
                      json.dumps(self.check(report, "platform.profile:yandex")))
        # ru is required by yandex and not shipped.
        self.assertIn("ru", self.check(report, "platform.requirements:yandex")["message"])

    def test_declared_ads_need_a_working_hook(self):
        design = fixture("inputs/game-design.json")
        design["monetization"]["placements"] = [
            {"kind": "rewarded", "trigger": "on miss", "player_value": "continue",
             "platforms": ["generic-web"]}]
        self.record_all_aspects()
        _, report, _ = self.verify(inputs=self.inputs(**{"game-design": design}))
        hooks = self.check(report, "platform.hooks:generic-web")
        self.assertEqual(hooks["status"], "FAIL")
        self.assertIn("rewarded ads are declared", hooks["message"])

    def test_a_profile_version_other_than_the_pinned_one_fails(self):
        with open(os.path.join(self.repo, "config/platforms/generic-web.yaml")) as handle:
            text = handle.read()
        self.write("config/platforms/generic-web.yaml",
                   text.replace("version: 1.0.0", "version: 1.1.0"))
        _, report, _ = self.verify()
        self.assertEqual(self.check(report, "platform.profile:generic-web")["status"], "FAIL")

    def test_the_fallback_path_is_the_local_boot(self):
        _, report, _ = self.verify()
        fallback = self.check(report, "platform.fallback")
        self.assertEqual(fallback["status"], "PASS")
        self.assertEqual(fallback["evidence"][0]["check_ref"], "gameplay.boot")

    def record_all_aspects(self):
        session = fixture("gameplay-session.json")
        self.write("build/verification/gameplay-session.json", json.dumps(session))


# -- assets ---------------------------------------------------------------------------------

class Assets(VerificationCase):
    def manifest(self, *items):
        body = fixture("inputs/asset-manifest.json")
        body["items"] += list(items)
        return self.inputs(**{"asset-manifest": body})

    def test_an_integrated_asset_without_a_file_is_missing(self):
        inputs = self.manifest({"id": "boss", "type": "sprite", "source": "ai-generated",
                                "est_cost": 0, "est_hours": 1, "status": "integrated"})
        _, report, _ = self.verify(inputs=inputs)
        check = self.check(report, "assets.missing")
        self.assertEqual(check["status"], "FAIL")
        self.assertIn("boss", check["message"])

    def test_unsupported_and_mismatched_formats_fail(self):
        self.write("public/assets/background.psd", "8BPS")
        self.write("src/assets/player-ship.ogg", "OggS")
        _, report, _ = self.verify()
        check = self.check(report, "assets.formats")
        self.assertEqual(check["status"], "FAIL")
        text = json.dumps(check)
        self.assertIn("background.psd", text)
        self.assertIn("player-ship is a sprite", text)

    def test_a_source_path_to_nothing_is_invalid(self):
        self.write("src/level.ts", 'export const BG = "/assets/backgrounds/night.webp";\n'
                                   'export const NAME = "night.webp";\n')
        _, report, _ = self.verify()
        check = self.check(report, "assets.paths")
        self.assertEqual(check["status"], "FAIL")
        self.assertIn("night.webp", check["message"] + json.dumps(check["evidence"]))
        self.assertEqual(len(check["evidence"][1]["data"]["unresolved"]), 1)

    def test_a_purchased_asset_needs_a_licence(self):
        self.write("public/assets/theme.ogg", "OggS")
        inputs = self.manifest({"id": "theme", "type": "music", "source": "purchased",
                                "est_cost": 20, "est_hours": 0, "status": "integrated"})
        _, report, _ = self.verify(inputs=inputs)
        self.assertEqual(self.check(report, "policy.asset-licenses")["status"], "FAIL")

    def test_an_incomplete_manifest_is_a_warning(self):
        inputs = self.manifest({"id": "boss", "type": "sprite", "source": "procedural",
                                "est_cost": 0, "est_hours": 1, "status": "in-progress"})
        result, report, _ = self.verify(inputs=inputs)
        self.assertEqual(self.check(report, "assets.manifest")["status"], "WARNING")
        self.assertEqual(result.outcome, StepOutcome.SUCCESS)

    def test_repository_playwright_does_not_observe_loading_failures(self):
        _, report, _ = self.verify()
        check = self.check(report, "assets.loading")
        self.assertEqual((check["status"], check["required"]), ("WARNING", False))


# -- through the real engine ------------------------------------------------------------------

LOOP_WORKFLOW = """
workflow:
  id: verification-loop
  version: 1
  steps:
    - id: develop
      type: test.develop
      inputs: [qa-report]
      outputs: [prototype-report, sdk-report]
    - id: verify
      type: verify
      inputs: [prototype-report, sdk-report, game-design, scaffold-record, asset-manifest]
      outputs: [verification-report, qa-report]
      with: {repo_dir: %s}
      on:
        fail: develop
    - id: release
      type: test.release
      inputs: [qa-report]
      outputs: [release-manifest]
      next: $end
"""

DEVELOP_MODULE = '''
import copy, json, os
from wgflib.hashing import content_hash
from wgflib.workflow import ArtifactOutput, StepResult, WorkflowStep

FIXTURES = %r
SEEN = []


def pins(inputs):
    # The engine checks lineage: an output pins exactly the versions its step consumed.
    return [{"artifact_id": inputs.load(t)["provenance"]["artifact_id"], "artifact_type": t,
             "content_hash": ref.content_hash} for t, ref in sorted(inputs.refs.items())]


def artifact(artifact_type, body, n, inputs=None):
    content = {"provenance": {
        "artifact_id": "wgf:%%s:fixture-game:20260901-%%02d" %% (artifact_type, n),
        "artifact_type": artifact_type, "schema_version": "1.0.0",
        "produced_by": {"role": "gameplay", "actor": "automation"},
        "produced_at": "2026-09-01T00:00:00Z",
        "inputs": pins(inputs) if inputs is not None else [], "content_hash": "",
        "status": "draft"}}
    content.update(copy.deepcopy(body))
    content["provenance"]["content_hash"] = content_hash(content)
    return ArtifactOutput(artifact_type, content)


def load(name):
    with open(os.path.join(FIXTURES, name)) as handle:
        return json.load(handle)


class Develop(WorkflowStep):
    type = "test.develop"

    def execute(self, inputs, context):
        qa = inputs.load("qa-report")
        SEEN.append(None if qa is None else [d["id"] for d in qa["blocking_defects"]])
        sdk = load("sdk-report.json")
        return StepResult.success([artifact("prototype-report", load("prototype-report.json"),
                                            context.execution, inputs),
                                   artifact("sdk-report", sdk, context.execution, inputs)])


class Release(WorkflowStep):
    type = "test.release"

    def execute(self, inputs, context):
        assert inputs.load("qa-report")["verdict"] == "pass"
        return StepResult.success([artifact("release-manifest", load("release-manifest.json"),
                                            1, inputs)])


def register(registry):
    registry.register(Develop.type, Develop)
    registry.register(Release.type, Release)
'''


class ThroughTheEngine(VerificationCase):
    """The module plugged in by configuration, the way factory.yaml declares it."""

    def setUp(self):
        super().setUp()
        self.modules = os.path.join(self.scratch, "modules")
        os.makedirs(self.modules)
        mock_sdk = fixture("inputs/sdk-report.json")
        fixtures = os.path.join(self.scratch, "fixtures")
        shutil.copytree(MOCK_FIXTURES, fixtures)
        with open(os.path.join(fixtures, "sdk-report.json"), "w") as handle:
            json.dump(mock_sdk, handle)
        # Upstream reports name the commit the fake checkout is at: stale ones block.
        prototype = read_json(os.path.join(fixtures, "prototype-report.json"))
        prototype["build_ref"]["commit_sha"] = COMMIT
        with open(os.path.join(fixtures, "prototype-report.json"), "w") as handle:
            json.dump(prototype, handle)
        with open(os.path.join(self.modules, "wgf_verification_loop_fakes.py"), "w") as handle:
            handle.write(DEVELOP_MODULE % fixtures)
        sys.path.insert(0, self.modules)
        self.addCleanup(sys.path.remove, self.modules)
        self.addCleanup(sys.modules.pop, "wgf_verification_loop_fakes", None)
        self.workflow = os.path.join(self.scratch, "verification-loop.workflow.yaml")
        with open(self.workflow, "w") as handle:
            handle.write(textwrap.dedent(LOOP_WORKFLOW % json.dumps(self.repo)))

        # The step class is resolved from config; its runner is swapped for the fake.
        self.lint = ["fail", "pass"]
        runner = FakeRunner({"run lint": self.scripted_lint})
        # From __dict__, so a staticmethod is restored as one rather than as a bare function.
        originals = (VerifyStep.__dict__["runner_factory"], VerifyStep.__dict__["clock"])
        VerifyStep.runner_factory = staticmethod(lambda: runner)
        VerifyStep.clock = staticmethod(lambda: NOW)
        self.addCleanup(self.restore, originals)

    @staticmethod
    def restore(originals):
        VerifyStep.runner_factory, VerifyStep.clock = originals

    def scripted_lint(self, command, cwd, env):
        outcome = self.lint.pop(0) if self.lint else "pass"
        return failing("1 problem") if outcome == "fail" else ok()

    def api(self):
        config = FactoryConfig({"steps": {"modules": ["wgf_verification",
                                                      "wgf_verification_loop_fakes"]},
                                "storage": {"fsync": False},
                                "execution": {"delay_seconds": 0}})
        return WorkflowAPI(config=config, store_dir=os.path.join(self.scratch, "store"),
                           workflow=self.workflow)

    def test_fail_loops_to_develop_and_pass_continues_to_release(self):
        engine_before = tree_digest(WORKFLOW_PACKAGE)
        api = self.api()
        state = api.run(RunRequest(project_id="fixture-game"))

        self.assertEqual(state.status, RunStatus.COMPLETED, state.to_dict())
        self.assertEqual([t["step"] for t in state.trail],
                         ["develop", "verify", "develop", "verify", "release"])
        self.assertEqual([t["route"] for t in state.trail if t["step"] == "verify"],
                         ["fail", "success"])

        import wgf_verification_loop_fakes as fakes
        self.assertEqual(fakes.SEEN, [None, ["vr-code-lint"]])

        stored = api.store.load(state.run_id)
        first = api.store.read_artifact(state.run_id, stored.artifacts["verification-report"][0])
        second = api.store.read_artifact(state.run_id, stored.latest_artifact(
            "verification-report"))
        self.assertEqual((first["verdict"], second["verdict"]), ("FAIL", "PASS"))
        self.assertEqual(stored.latest_artifact("verification-report").metadata["verdict"],
                         "PASS")
        self.assertIn("sdk-report@v2", stored.steps["verify"].consumed)

        self.assertEqual(tree_digest(WORKFLOW_PACKAGE), engine_before)

    def test_blocked_stops_the_run_for_a_person(self):
        shutil.rmtree(self.repo)
        api = self.api()
        state = api.run(RunRequest(project_id="fixture-game"))
        self.assertEqual(state.status, RunStatus.BLOCKED)
        stored = api.store.load(state.run_id)
        report = api.store.read_artifact(state.run_id,
                                         stored.latest_artifact("verification-report"))
        self.assertEqual(report["verdict"], "BLOCKED")

    def test_the_module_registers_the_verify_type(self):
        registry = register(StepRegistry())
        self.assertIs(registry.resolve("verify"), VerifyStep)
        self.assertTrue(issubclass(VerifyStep, WorkflowStep))


# -- the schema, with ajv when it is at hand --------------------------------------------------

@unittest.skipUnless(os.environ.get("WGF_AJV"), "set WGF_AJV=1 to validate with ajv (npx)")
class SchemaValidation(VerificationCase):
    def test_emitted_reports_validate(self):
        import subprocess

        cases = {"pass": self.verify()[1:],
                 "blocked": self.verify(repo_dir=os.path.join(self.scratch, "absent"))[1:]}
        for label, (report, qa) in cases.items():
            for artifact_type, content in (("verification-report", report), ("qa-report", qa)):
                path = os.path.join(self.scratch, f"{label}-{artifact_type}.json")
                with open(path, "w") as handle:
                    json.dump(content, handle)
                completed = subprocess.run(
                    ["npx", "--yes", "-p", "ajv-cli@5", "-p", "ajv-formats@2", "ajv", "validate",
                     "-s", f"core/artifacts/{artifact_type}.schema.json",
                     "-r", "core/artifacts/shared/*.schema.json", "-c", "ajv-formats",
                     "--spec=draft2020", "--strict=false", "-d", path],
                    cwd=ROOT, capture_output=True, text=True, check=False)
                self.assertEqual(completed.returncode, 0,
                                 f"{label} {artifact_type}: {completed.stdout}{completed.stderr}")


if __name__ == "__main__":
    unittest.main()

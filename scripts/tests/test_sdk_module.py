"""The SDK module (scripts/wgf_sdk): prototype-report in, sdk-report out.

Evidence is a real conformance report produced by web-game-template's tests/sdk suite
(fixtures/sdk-conformance.json, trimmed to the fields the module reads), so the mapping is
tested against the shape the suite actually emits. The runner is faked: nothing here runs
pnpm, reaches a portal, or publishes. One opt-in test (WGF_TEMPLATE_SDK_TEST=1) runs the real
suite in the pinned web-game-template checkout (wgflib.template), never in another revision.

Run from the repository root:

    python -m unittest discover scripts/tests
"""

import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, HERE)

from wgflib.hashing import content_hash  # noqa: E402
from wgflib.workflow.api import RunRequest, WorkflowAPI  # noqa: E402
from wgflib.workflow.config import FactoryConfig  # noqa: E402
from wgflib.workflow.contracts import ArtifactContracts  # noqa: E402
from wgflib.workflow.model import RunStatus, StepOutcome  # noqa: E402
from wgf_sdk import evidence  # noqa: E402
from wgf_sdk.plan import FEATURES, PlanError, integration_plan  # noqa: E402
from wgf_sdk.step import SdkStep  # noqa: E402
from testenv import enabled  # noqa: E402

FIXTURE = os.path.join(HERE, "fixtures", "sdk-conformance.json")
NOW = "2026-09-23T12:00:00Z"
IDENTITY = ["-c", "user.name=Test", "-c", "user.email=test@example.invalid"]


def git(repo, *args):
    """Real git in the synthetic game repository: the step establishes its commit from it."""
    return subprocess.run(["git", *IDENTITY, *args], cwd=repo, check=True,
                          capture_output=True, text=True).stdout.strip()


def commit_all(repo, message="fixture: the game as develop committed it"):
    git(repo, "add", "--all")
    git(repo, "commit", "--allow-empty", "--no-verify", "-q", "-m", message)
    return git(repo, "rev-parse", "HEAD")


def game_config(platforms, ad_kinds=("interstitial", "rewarded")):
    lines = ["game: {id: demo-game, name: Demo, version: 0.1.0}", "engine: {type: pixijs}", "platforms:"]
    for platform_id, role in platforms:
        lines.append(f"  - {{ id: {platform_id}, profile: {platform_id}@1.0.0, role: {role} }}")
    lines.append(f"monetization: {{ad_kinds: [{', '.join(ad_kinds)}], iap: false}}")
    lines.append("publishing: {enabled: false}")
    return "\n".join(lines) + "\n"


class FakeRunner(evidence.ConformanceRunner):
    calls = []
    report = None
    browser = None
    error = None

    def run(self, game_repo, browser=False):
        FakeRunner.calls.append((game_repo, browser))
        if FakeRunner.error:
            raise evidence.EvidenceError(FakeRunner.error)
        # Where the suite ran: the checkout's HEAD, as `git rev-parse HEAD` reports it.
        return evidence.ConformanceRun(copy.deepcopy(FakeRunner.report),
                                       git(game_repo, "rev-parse", "HEAD"),
                                       FakeRunner.browser if browser else None)


class FixedStep(SdkStep):
    clock = staticmethod(lambda: NOW)
    runner_factory = FakeRunner


class FakeInputs:
    def __init__(self):
        self.refs, self.missing = {}, ["prototype-report"]

    def __contains__(self, item):
        return False


class FakeLogger:
    def __getattr__(self, _):
        return lambda *a, **k: None


class FakeContext:
    def __init__(self, config=None):
        self.config, self.project_id, self.execution, self.logger = config or {}, "demo", 1, FakeLogger()


class FakeDefinition:
    def __init__(self, params):
        self.id, self.type, self.params = "sdk", "sdk", params
        self.inputs, self.outputs = ["prototype-report"], ["sdk-report"]


def load_fixture():
    with open(FIXTURE, encoding="utf-8") as handle:
        return json.load(handle)


class Case(unittest.TestCase):
    def setUp(self):
        self.repo = tempfile.mkdtemp(prefix="wgf-sdk-game-")
        self.addCleanup(shutil.rmtree, self.repo, ignore_errors=True)
        git(self.repo, "init", "-q")
        self.commit = commit_all(self.repo, "chore: initial")
        FakeRunner.calls, FakeRunner.report, FakeRunner.browser, FakeRunner.error = [], load_fixture(), None, None

    def configure(self, platforms, **kwargs):
        with open(os.path.join(self.repo, "game.config.yaml"), "w", encoding="utf-8") as handle:
            handle.write(game_config(platforms, **kwargs))
        self.commit = commit_all(self.repo)

    def run_step(self, params=None, config=None):
        params = {"game_repo": self.repo, **(params or {})}
        return FixedStep(FakeDefinition(params)).execute(FakeInputs(), FakeContext(config))

    @staticmethod
    def platform(result, platform_id):
        content = result.artifacts[0].content
        return next(p for p in content["platforms"] if p["platform_id"] == platform_id)

    @staticmethod
    def features(entry):
        return {f["feature"]: f for f in entry["features"]}


class FromRealEvidence(Case):
    def test_yandex_and_poki_required_are_working(self):
        self.configure([("yandex", "required"), ("poki", "required")])
        result = self.run_step()
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
        for platform_id in ("yandex", "poki"):
            entry = self.platform(result, platform_id)
            self.assertEqual(entry["status"], "working")
            features = self.features(entry)
            self.assertEqual([f["feature"] for f in entry["features"]], list(FEATURES))
            for name in ("init", "sdk-unavailable", "init-failure", "pause-resume", "interstitial",
                         "rewarded", "storage", "game-binding"):
                self.assertEqual(features[name]["status"], "working", (platform_id, name))
                self.assertIn(self.commit, features[name]["observed_by"])

    def test_the_report_is_schema_shaped_and_pinned(self):
        self.configure([("yandex", "required")])
        content = self.run_step().artifacts[0].content
        self.assertEqual(ArtifactContracts()("sdk-report", content), [])
        self.assertEqual(content["provenance"]["content_hash"], content_hash(content))
        # Nothing was integrated, so nothing was committed: the verified commit is the base.
        self.assertEqual(content["build_ref"], {"commit_sha": self.commit,
                                                "base_commit_sha": self.commit,
                                                "sdk_commits": []})
        self.assertEqual(content["provenance"]["produced_by"]["role"], "sdk")

    def test_ad_kinds_the_title_did_not_commit_to_are_not_required(self):
        self.configure([("yandex", "required")], ad_kinds=("interstitial",))
        features = self.features(self.platform(self.run_step(), "yandex"))
        self.assertEqual(features["interstitial"]["status"], "working")
        self.assertEqual(features["rewarded"]["status"], "not-required")

    def test_crazygames_required_fails_as_not_started(self):
        self.configure([("yandex", "required"), ("crazygames", "required")])
        result = self.run_step()
        self.assertEqual((result.outcome, result.retryable), (StepOutcome.FAILED, False))
        self.assertIn("crazygames (not-started)", result.error)
        entry = self.platform(result, "crazygames")
        self.assertEqual(entry["status"], "not-started")
        self.assertIn("No CrazyGames adapter", entry["note"])
        self.assertNotIn("working", {f["status"] for f in entry["features"]} - {"not-required"})
        # The evidence is persisted with the failure.
        self.assertEqual(ArtifactContracts()("sdk-report", result.artifacts[0].content), [])

    def test_crazygames_optional_does_not_block(self):
        self.configure([("yandex", "required"), ("crazygames", "optional")])
        result = self.run_step()
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
        self.assertIn("crazygames (not-started)", result.message)

    def test_gamevui_runs_on_generic_web_and_needs_no_portal_sdk(self):
        self.configure([("gamevui", "optional"), ("generic-web", "required")], ad_kinds=())
        result = self.run_step()
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
        entry = self.platform(result, "gamevui")
        features = self.features(entry)
        self.assertEqual(features["init"]["status"], "working")
        self.assertEqual(features["sdk-unavailable"]["status"], "not-required")
        self.assertIn("GameVui documents no SDK", entry["note"])

    def test_gamevui_required_is_not_started_because_the_template_cannot_boot_it(self):
        # createPlatform("gamevui") throws by design; a GameVui-required build fails at boot.
        self.configure([("gamevui", "required")], ad_kinds=())
        result = self.run_step()
        self.assertEqual(result.outcome, StepOutcome.FAILED)
        features = self.features(self.platform(result, "gamevui"))
        self.assertEqual(features["not-configured"]["status"], "not-started")

    def test_gamevui_with_rewarded_ads_cannot_be_working(self):
        # The profile says GameVui serves no rewarded ads and it has no SDK to request any.
        self.configure([("gamevui", "required")], ad_kinds=("rewarded",))
        result = self.run_step()
        self.assertEqual(result.outcome, StepOutcome.FAILED)
        self.assertEqual(self.features(self.platform(result, "gamevui"))["rewarded"]["status"], "not-started")


class FailurePaths(Case):
    @mock.patch.dict(os.environ, {}, clear=False)
    def test_platform_not_configured_blocks(self):
        os.environ.pop("WGF_GAME_REPO", None)
        result = FixedStep(FakeDefinition({})).execute(FakeInputs(), FakeContext())
        self.assertEqual(result.outcome, StepOutcome.BLOCKED)
        self.assertIn("platform not configured", result.message or result.error)
        self.assertEqual(FakeRunner.calls, [])

    def test_missing_game_config_blocks(self):
        result = self.run_step()
        self.assertEqual(result.outcome, StepOutcome.BLOCKED)

    def test_a_moved_profile_pin_blocks(self):
        with open(os.path.join(self.repo, "game.config.yaml"), "w", encoding="utf-8") as handle:
            handle.write(game_config([("yandex", "required")]).replace("yandex@1.0.0", "yandex@9.0.0"))
        result = self.run_step()
        self.assertEqual(result.outcome, StepOutcome.BLOCKED)
        self.assertIn("yandex@9.0.0", result.message or result.error)

    def test_a_tampered_vendored_profile_blocks(self):
        # The vendored copy must be the Factory's by content hash, not merely declare the
        # pinned version (wgf_init.profiles.pin_identity).
        from wgf_init.profiles import vendor_profiles
        self.configure([("yandex", "required")])
        vendor_profiles(self.repo, [{"id": "yandex", "profile": "yandex@1.0.0",
                                     "role": "required"}])
        self.commit = commit_all(self.repo)
        result = self.run_step()
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.message or result.error)
        with open(os.path.join(self.repo, "config", "platforms", "yandex.yaml"), "a") as handle:
            handle.write("\n# edited\n")
        self.commit = commit_all(self.repo)
        FakeRunner.calls = []
        result = self.run_step()
        self.assertEqual(result.outcome, StepOutcome.BLOCKED)
        self.assertIn("content hash", result.message or result.error)
        self.assertEqual(FakeRunner.calls, [])

    def test_a_suite_that_could_not_run_is_retryable(self):
        self.configure([("yandex", "required")])
        FakeRunner.error = "pnpm is not installed"
        result = self.run_step()
        self.assertEqual((result.outcome, result.retryable), (StepOutcome.FAILED, True))

    def test_a_failing_scenario_makes_the_feature_partial(self):
        self.configure([("yandex", "required")])
        for suite in FakeRunner.report["testResults"]:
            for test in suite["assertionResults"]:
                if test["ancestorTitles"] == ["'yandex'", "rewarded"] and "closes the ad early" in test["title"]:
                    test["status"] = "failed"
                    test["failureMessages"] = ["AssertionError: granted a reward on early close"]
        result = self.run_step()
        self.assertEqual(result.outcome, StepOutcome.FAILED)
        rewarded = self.features(self.platform(result, "yandex"))["rewarded"]
        self.assertEqual(rewarded["status"], "partial")
        self.assertIn("granted a reward on early close", rewarded["note"])

    def test_a_failing_browser_smoke_downgrades_working(self):
        self.configure([("yandex", "required")])
        FakeRunner.browser = {"passed": False, "output": "boot timed out"}
        result = self.run_step(params={"browser": True})
        self.assertEqual(result.outcome, StepOutcome.FAILED)
        self.assertEqual(self.platform(result, "yandex")["status"], "partial")
        self.assertEqual(FakeRunner.calls[-1][1], True)

    def test_a_report_file_is_read_instead_of_running(self):
        self.configure([("poki", "required")])
        result = self.run_step(params={"report": FIXTURE})
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
        self.assertEqual(FakeRunner.calls, [])

    def test_the_game_repo_can_come_from_the_environment(self):
        self.configure([("poki", "required")])
        with mock.patch.dict(os.environ, {"WGF_GAME_REPO": self.repo}):
            result = FixedStep(FakeDefinition({})).execute(FakeInputs(), FakeContext())
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)

    def test_the_game_repo_can_come_from_factory_config(self):
        self.configure([("poki", "required")])
        step = FixedStep(FakeDefinition({}))
        result = step.execute(FakeInputs(), FakeContext({"sdk": {"game_repo": self.repo}}))
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)


class ReleaseBoundary(unittest.TestCase):
    def test_the_runner_can_only_run_conformance_browser_smoke_and_rev_parse(self):
        self.assertEqual(set(evidence.COMMANDS), {"conformance", "browser", "commit"})
        text = " ".join(" ".join(c) for c in evidence.COMMANDS.values())
        for word in ("publish", "release", "package", "deploy", "push", "upload"):
            self.assertNotIn(word, text)

    def test_the_module_never_names_a_publishing_script(self):
        package = os.path.join(SCRIPTS, "wgf_sdk")
        for name in os.listdir(package):
            if name.endswith(".py"):
                with open(os.path.join(package, name), encoding="utf-8") as handle:
                    source = handle.read()
                for forbidden in ("publish:prepare", "release:package", "make-publication", "git push"):
                    self.assertNotIn(forbidden, source, name)


class Plan(unittest.TestCase):
    def test_required_features_follow_profile_and_game_config(self):
        config = {"platforms": [{"id": "yandex", "profile": "yandex@1.0.0", "role": "required"},
                                {"id": "generic-web", "profile": "generic-web@1.0.0", "role": "optional"}],
                  "monetization": {"ad_kinds": ["rewarded"]}}
        yandex, generic = integration_plan(config)
        self.assertTrue({"init", "sdk-unavailable", "pause-resume", "rewarded", "storage"} <= yandex.required)
        self.assertNotIn("interstitial", yandex.required)
        self.assertNotIn("sdk-unavailable", generic.required)

    def test_a_bare_string_platform_is_refused(self):
        with self.assertRaises(PlanError):
            integration_plan({"platforms": ["yandex"]})


CONTRACT_WORKFLOW = """
workflow:
  id: sdk-contract
  version: 1
  steps:
    - id: sdk
      type: sdk
      inputs: [prototype-report]
      outputs: [sdk-report]
      with: {{game_repo: {repo!r}, report: {report!r}}}
"""


class ThroughTheEngine(Case):
    def test_the_sdk_step_runs_from_config_and_persists_its_report(self):
        self.configure([("yandex", "required"), ("poki", "optional")])
        scratch = tempfile.mkdtemp(prefix="wgf-sdk-engine-")
        self.addCleanup(shutil.rmtree, scratch, ignore_errors=True)
        workflow = os.path.join(scratch, "sdk-contract.workflow.yaml")
        with open(workflow, "w", encoding="utf-8") as handle:
            handle.write(textwrap.dedent(CONTRACT_WORKFLOW.format(repo=self.repo, report=FIXTURE)))
        api = WorkflowAPI(config=FactoryConfig({"steps": {"modules": ["wgf_sdk"]}, "storage": {"fsync": False}}),
                          store_dir=os.path.join(scratch, "store"), workflow=workflow)
        state = api.run(RunRequest(project_id="demo-game"))
        self.assertEqual(state.status, RunStatus.COMPLETED, state.steps["sdk"].error)
        ref = api.store.load(state.run_id).latest_artifact("sdk-report")
        self.assertEqual(ref.metadata["platforms"], {"yandex": "working", "poki": "working"})


@unittest.skipUnless(shutil.which("npx"), "npx is not on PATH")
class Schema(Case):
    """Full JSON Schema validation. Offline: skipped when ajv is not in the npm cache."""

    def test_emitted_reports_validate_with_ajv(self):
        import subprocess
        paths = []
        # Outside the checkout: an untracked file in it is a change the sdk step did not make.
        out = tempfile.mkdtemp(prefix="wgf-sdk-reports-")
        self.addCleanup(shutil.rmtree, out, ignore_errors=True)
        for platforms in ([("yandex", "required"), ("poki", "optional")],
                          [("crazygames", "required"), ("gamevui", "optional")]):
            self.configure(platforms)
            path = os.path.join(out, f"report-{len(paths)}.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(self.run_step().artifacts[0].content, handle)
            paths.append(path)
        command = ["npx", "--yes", "-p", "ajv-cli@5", "-p", "ajv-formats@2", "ajv", "validate",
                   "-s", "core/artifacts/sdk-report.schema.json", "-r", "core/artifacts/shared/*.schema.json",
                   "-c", "ajv-formats", "--spec=draft2020", "--strict=false"]
        for path in paths:
            command += ["-d", path]
        done = subprocess.run(command, cwd=ROOT, env=dict(os.environ, npm_config_offline="true"),
                              capture_output=True, text=True, timeout=120)
        output = done.stdout + done.stderr
        if done.returncode != 0 and ("ENOTCACHED" in output or "could not determine executable" in output):
            self.skipTest("ajv-cli is not in the local npm cache")
        self.assertEqual(done.returncode, 0, output)


def _pinned_template():
    """(checkout, None) for the pinned web-game-template with node_modules, or (None, why).
    Only the opt-in reads it: nothing is cloned or installed otherwise."""
    if not enabled("WGF_TEMPLATE_SDK_TEST"):
        return None, "set WGF_TEMPLATE_SDK_TEST=1 to run the real suite in the pinned template"
    import pinned_template
    return pinned_template.with_dependencies()


TEMPLATE, _TEMPLATE_WHY = _pinned_template()


@unittest.skipUnless(TEMPLATE and shutil.which("pnpm"), _TEMPLATE_WHY or "pnpm is not on PATH")
class AgainstTheRealTemplate(unittest.TestCase):
    """Opt-in: runs `pnpm sdk:conformance` in the checkout of the commit pinned in
    workspace/config/template.lock.json (its own config), and nowhere else - a checkout at
    another revision is refused by wgflib.template, not tested. The suite writes only its
    report under build/, which the template ignores; no design or scaffold is given, so the
    step integrates and commits nothing."""

    def test_the_real_suite_yields_a_working_report(self):
        from wgflib import template

        pinned = template.expected_commit()
        self.assertEqual(template.head_of(TEMPLATE), pinned)
        step = type("RealClock", (SdkStep,), {"clock": staticmethod(lambda: NOW)})
        result = step(FakeDefinition({"game_repo": TEMPLATE})).execute(
            FakeInputs(), FakeContext())
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
        content = result.artifacts[0].content
        self.assertEqual(ArtifactContracts()("sdk-report", content), [])
        # The evidence is about the pinned commit, and the checkout is still at it.
        self.assertEqual(content["build_ref"]["commit_sha"], pinned)
        self.assertEqual(template.head_of(TEMPLATE), pinned)


if __name__ == "__main__":
    unittest.main()

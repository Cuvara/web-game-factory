"""Core v1 VERIFY category: a PASS is derived from evidence, never from a claim.

    valid game evidence       -> PASS
    missing evidence          -> not PASS
    failed browser test       -> FAIL
    invalid SDK evidence      -> not PASS
    wrong commit              -> refused (evidence about another commit is not used)
    PASS_MOCK                 -> never promoted to PASS, anywhere downstream

The game repository is the verification fixture; every command is scripted by the
FakeRunner of test_verification.py, which plays a healthy repository unless told otherwise.
Offline, deterministic.
"""

import copy
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

from test_verification import (COMMIT, FakeRunner, VerificationCase, failing,  # noqa: E402
                               fixture, ok)
from wgf_verification.checks.platform import live_observation, sdk_evidence_status  # noqa: E402
from wgf_verification.model import (BLOCKED, FAIL, PASS, PASS_MOCK, UNVERIFIED,  # noqa: E402
                                    WARNING, Check, Evidence, evidence_status_of,
                                    overall_evidence_status)
from wgflib.workflow import StepOutcome  # noqa: E402

LIVE = "observed on the live portal by the release manager at 2026-09-20"


def sdk_report(observed_by=None, init="not-required", commit=COMMIT, platform="generic-web",
               features=None):
    report = fixture("inputs/sdk-report.json")
    report["build_ref"]["commit_sha"] = commit
    entry = report["platforms"][0]
    entry["platform_id"] = platform
    if features is not None:
        entry["features"] = features
    for feature in entry["features"]:
        if feature["feature"] == "init":
            feature["status"] = init
        elif observed_by is not None:
            feature["observed_by"] = observed_by
    return report


def prototype_report(commit=COMMIT):
    return {"title_id": "fixture-game",
            "build_ref": {"commit_sha": commit, "url": "https://example.invalid/b"},
            "iteration": 1,
            "proved": [{"question": "Does the core loop hold attention?",
                        "verdict": "inconclusive", "evidence": "fixture"}],
            "kill_criteria_eval": [{"criterion_id": "kc-1", "breached": False, "measured": 1}],
            "playtest_sessions": [{"observer": "fixture", "player_context": "internal",
                                   "duration_s": 60, "notes": "fixture"}],
            "recommendation": {"decision": "iterate", "rationale": "fixture"}}


def playwright_report(**failures):
    """The fixture report, with the named spec titles failing."""
    report = fixture("playwright-e2e.json")
    for spec in report["suites"][0]["specs"]:
        if spec["title"] in failures:
            for test in spec["tests"]:
                test["status"] = "unexpected"
                test["results"] = [{"status": "failed",
                                    "error": {"message": failures[spec["title"]]}}]
    return report


class ValidEvidence(VerificationCase):
    def test_valid_game_evidence_passes(self):
        result, report, qa = self.verify(inputs=self.inputs(**{
            "prototype-report": prototype_report(), "sdk-report": sdk_report(LIVE)}))
        self.assertEqual(result.outcome, StepOutcome.SUCCESS)
        self.assertEqual(report["verdict"], PASS)
        self.assertEqual(report["evidence_status"], PASS)
        self.assertEqual(qa["verdict"], "pass")
        self.assertEqual(qa["evidence_status"], PASS)
        # Every PASS rests on something that was run or read, never on a report's say-so.
        for check in report["checks"]:
            if check["status"] == PASS:
                self.assertTrue(any(e["kind"] in ("command", "file", "test", "observation",
                                                  "artifact", "reference")
                                    for e in check["evidence"]), check["id"])
        e2e = [e for c in report["checks"] if c["category"] == "gameplay"
               for e in c["evidence"] if e.get("path") == "build/verification/playwright-e2e.json"]
        self.assertTrue(e2e)

    def test_the_browser_report_and_assertions_are_pinned_by_hash(self):
        _, report, _ = self.verify()
        hashes = [e for c in report["checks"] for e in c["evidence"] if e.get("content_hash")]
        paths = {e.get("path") for e in hashes}
        self.assertIn("build/verification/playwright-e2e.json", paths)
        self.assertIn("build/assertions/generic-web.json", paths)
        self.assertIn("build/runtime-facts.json", paths)

    def test_a_developer_report_saying_tests_pass_is_not_evidence(self):
        # The prototype-report claims everything works; the repository's own suite fails.
        claim = prototype_report()
        claim["integration_status"] = "working"
        runner = FakeRunner({"run test:unit": lambda c, cwd, env: failing(
            "      Tests  1 failed | 23 passed (24)\n")})
        result, report, qa = self.verify(inputs=self.inputs(**{"prototype-report": claim}),
                                         runner=runner)
        self.assertEqual(report["verdict"], FAIL)
        self.assertEqual(self.check(report, "code.unit")["status"], FAIL)
        self.assertEqual(qa["verdict"], "fail")


class MissingEvidence(VerificationCase):
    def test_no_sdk_report_is_not_pass(self):
        artifacts = {"asset-manifest": fixture("inputs/asset-manifest.json")}
        from test_verification import FakeInputs
        result, report, qa = self.verify(inputs=FakeInputs(artifacts))
        self.assertEqual(result.outcome, StepOutcome.BLOCKED)
        self.assertNotEqual(report["verdict"], PASS)
        self.assertEqual(self.check(report, "platform.sdk-init:generic-web")["status"], BLOCKED)
        self.assertEqual(report["evidence_status"], UNVERIFIED)
        self.assertEqual(qa["verdict"], "fail")

    def test_a_browser_run_that_writes_no_report_is_not_pass(self):
        runner = FakeRunner({"run test:e2e": lambda c, cwd, env: ok("")})
        result, report, _ = self.verify(runner=runner)
        self.assertNotEqual(report["verdict"], PASS)
        self.assertNotEqual(self.check(report, "gameplay.boot")["status"], PASS)

    def test_a_previous_runs_assertion_results_are_not_read(self):
        # A clean result file from an earlier run is on disk; this run's evaluator dies
        # without writing one.
        self.write("build/assertions/generic-web.json", "[]")
        runner = FakeRunner({"evaluate-assertions": lambda c, cwd, env: failing("crash", 2)})
        _, report, _ = self.verify(runner=runner)
        check = self.check(report, "policy.assertions:generic-web")
        self.assertNotEqual(check["status"], PASS)
        self.assertNotEqual(report["verdict"], PASS)

    def test_a_previous_runs_runtime_facts_are_not_read(self):
        self.write("build/runtime-facts.json", json.dumps(fixture("runtime-facts.json")))
        runner = FakeRunner({"run test:verify": lambda c, cwd, env: ok("0 passed")})
        _, report, _ = self.verify(runner=runner)
        self.assertEqual(self.check(report, "policy.runtime-facts")["status"], FAIL)
        self.assertNotEqual(report["verdict"], PASS)

    def test_an_evaluator_failing_without_a_breach_is_not_pass(self):
        def evaluate(command, cwd, env):
            FakeRunner.evaluate(command, cwd, env, results=[])
            return failing("TypeError: cannot read facts", 1)

        _, report, _ = self.verify(runner=FakeRunner({"evaluate-assertions": evaluate}))
        self.assertEqual(self.check(report, "policy.assertions:generic-web")["status"], FAIL)

    def test_a_recorded_scenario_citing_a_missing_screenshot_is_not_counted(self):
        session = fixture("gameplay-session.json")
        for scenario in session["scenarios"]:
            scenario["screenshot"] = f"build/verification/{scenario['aspect']}.png"
        self.write("build/verification/gameplay-session.json", json.dumps(session))
        # Only boot's screenshot exists.
        self.write("build/verification/boot.png", "png")
        _, report, _ = self.verify(browser="recorded")
        boot = self.check(report, "gameplay.boot")
        self.assertEqual(boot["status"], PASS)
        self.assertTrue(boot["evidence"][0]["data"]["screenshot_hash"].startswith("sha256:"))
        self.assertEqual(self.check(report, "gameplay.core-loop")["status"], FAIL)
        self.assertNotEqual(report["verdict"], PASS)


class FailedBrowserTest(VerificationCase):
    def test_a_failed_browser_test_fails_the_verification(self):
        report_body = playwright_report(**{"boots and steps the simulation":
                                           "Timed out waiting for #hud[data-ready]"})

        def e2e(command, cwd, env):
            with open(env["PLAYWRIGHT_JSON_OUTPUT_NAME"], "w") as handle:
                json.dump(report_body, handle)
            return failing("1 failed")

        result, report, qa = self.verify(runner=FakeRunner({"run test:e2e": e2e}))
        self.assertEqual(result.outcome, StepOutcome.FAILED)
        self.assertEqual(result.route, "fail")
        self.assertEqual(report["verdict"], FAIL)
        self.assertEqual(self.check(report, "gameplay.boot")["status"], FAIL)
        self.assertIn("data-ready", json.dumps(self.check(report, "gameplay.boot")["evidence"]))
        self.assertEqual(qa["evidence_status"], FAIL)

    def test_a_red_run_with_a_green_report_fails(self):
        def e2e(command, cwd, env):
            with open(env["PLAYWRIGHT_JSON_OUTPUT_NAME"], "w") as handle:
                json.dump(fixture("playwright-e2e.json"), handle)
            return failing("Error: webServer exited early", 1)

        _, report, _ = self.verify(runner=FakeRunner({"run test:e2e": e2e}))
        self.assertEqual(self.check(report, "gameplay.boot")["status"], FAIL)
        self.assertEqual(report["verdict"], FAIL)


class InvalidSdkEvidence(VerificationCase):
    def test_an_sdk_init_that_is_not_working_fails(self):
        result, report, _ = self.verify(inputs=self.inputs(**{"sdk-report": sdk_report(
            init="partial")}))
        self.assertEqual(self.check(report, "platform.sdk-init:generic-web")["status"], FAIL)
        self.assertNotEqual(report["verdict"], PASS)

    def test_an_sdk_report_without_the_platform_fails(self):
        result, report, _ = self.verify(inputs=self.inputs(**{"sdk-report": sdk_report(
            platform="some-other-platform")}))
        self.assertEqual(self.check(report, "platform.sdk-init:generic-web")["status"], FAIL)
        self.assertNotEqual(report["verdict"], PASS)

    def test_a_feature_not_started_fails_the_hooks(self):
        features = [{"feature": "init", "status": "not-required"},
                    {"feature": "loading-progress", "status": "not-started"}]
        _, report, _ = self.verify(inputs=self.inputs(**{"sdk-report": sdk_report(
            features=features)}))
        self.assertEqual(self.check(report, "platform.hooks:generic-web")["status"], FAIL)


class WrongCommit(VerificationCase):
    def test_an_sdk_report_about_another_commit_is_not_used(self):
        result, report, _ = self.verify(inputs=self.inputs(**{"sdk-report": sdk_report(
            commit="f" * 40)}))
        self.assertEqual(result.outcome, StepOutcome.BLOCKED)
        self.assertEqual(self.check(report, "platform.sdk-init:generic-web")["status"], BLOCKED)
        self.assertEqual(self.check(report, "source.upstream-commits")["status"], BLOCKED)
        self.assertNotEqual(report["verdict"], PASS)

    def test_a_prototype_report_about_another_commit_blocks(self):
        result, report, _ = self.verify(inputs=self.inputs(**{
            "prototype-report": prototype_report("e" * 40)}))
        self.assertEqual(result.outcome, StepOutcome.BLOCKED)
        self.assertIn("prototype-report", self.check(report, "source.upstream-commits")
                      ["message"])

    def test_a_recorded_session_of_another_commit_is_ignored(self):
        session = fixture("gameplay-session.json")
        session["commit_sha"] = "d" * 40
        self.write("build/verification/gameplay-session.json", json.dumps(session))
        _, report, _ = self.verify(browser="recorded")
        self.assertEqual(self.check(report, "gameplay.boot")["status"], BLOCKED)
        self.assertNotEqual(report["verdict"], PASS)


class PassMockNeverPromoted(VerificationCase):
    def test_sdk_evidence_against_a_stand_in_is_pass_mock_everywhere(self):
        result, report, qa = self.verify(inputs=self.inputs(**{"sdk-report": sdk_report(
            "SDK conformance suite (tests/sdk, fake portal SDK) @ abc: 4 scenario(s) passed")}))
        self.assertEqual(result.outcome, StepOutcome.SUCCESS)
        hooks = self.check(report, "platform.hooks:generic-web")
        self.assertEqual((hooks["status"], hooks["evidence_status"]), (PASS, PASS_MOCK))
        self.assertEqual(report["verdict"], PASS)            # routing is unaffected
        self.assertEqual(report["evidence_status"], PASS_MOCK)
        self.assertEqual(qa["evidence_status"], PASS_MOCK)
        readiness = report["platform_readiness"][0]
        self.assertEqual(readiness["evidence_status"], PASS_MOCK)
        self.assertEqual(readiness["external_approval"], "not-claimed")
        self.assertEqual(qa["platform_checks"][0]["evidence_status"], PASS_MOCK)
        self.assertEqual(result.artifacts[1].metadata["evidence_status"], PASS_MOCK)

    def test_live_wording_with_a_stand_in_is_still_mock(self):
        self.assertFalse(live_observation("live portal smoke, with the portal SDK mocked"))
        self.assertFalse(live_observation("SDK-mock suite passed; not observed on the portal"))
        self.assertFalse(live_observation(None))
        self.assertTrue(live_observation(LIVE))
        self.assertEqual(sdk_evidence_status([{"status": "working"}]), PASS_MOCK)
        self.assertEqual(sdk_evidence_status([{"status": "not-required"}]), PASS)

    def test_a_check_cannot_claim_stronger_evidence_than_its_status(self):
        evidence = [Evidence("observation", "x")]
        self.assertEqual(evidence_status_of(Check("a.b", "code", "t", FAIL, evidence=evidence,
                                                  evidence_status=PASS)), FAIL)
        self.assertEqual(evidence_status_of(Check("a.b", "code", "t", BLOCKED,
                                                  evidence=evidence, evidence_status=PASS)),
                         UNVERIFIED)
        self.assertEqual(evidence_status_of(Check("a.b", "code", "t", WARNING,
                                                  evidence=evidence, evidence_status=PASS)),
                         UNVERIFIED)
        check = Check("a.b", "code", "t", PASS, evidence=evidence, evidence_status=PASS_MOCK)
        check.status = FAIL          # a later observation fails it: the mock pass goes too
        self.assertEqual(evidence_status_of(check), FAIL)

    def test_one_mocked_required_check_makes_the_whole_verification_pass_mock(self):
        evidence = [Evidence("observation", "x")]
        checks = [Check("a.one", "code", "t", PASS, evidence=evidence),
                  Check("a.two", "code", "t", PASS, evidence=evidence,
                        evidence_status=PASS_MOCK),
                  Check("a.three", "code", "t", WARNING, required=False, evidence=evidence)]
        self.assertEqual(overall_evidence_status(checks), PASS_MOCK)
        self.assertEqual(overall_evidence_status(checks[:1] + checks[2:]), PASS)
        self.assertEqual(overall_evidence_status([]), UNVERIFIED)

    def test_a_portal_platform_is_blocked_external_without_live_evidence(self):
        # A platform whose profile has a review process: its portal QA cannot be observed
        # from a local run.
        with open(self.path_of("config/platforms/generic-web.yaml")) as handle:
            profile = handle.read()
        profile = profile.replace("id: generic-web", "id: example-portal")
        profile = profile.replace("process: none", "process: manual")
        self.write("config/platforms/example-portal.yaml", profile)
        with open(self.path_of("game.config.yaml")) as handle:
            config = handle.read()
        config = config.replace(
            "  - { id: generic-web, profile: generic-web@1.0.0, role: required }",
            "  - { id: generic-web, profile: generic-web@1.0.0, role: required }\n"
            "  - { id: example-portal, profile: example-portal@1.0.0, role: optional }")
        self.write("game.config.yaml", config)
        sdk = sdk_report("fake portal SDK")
        mocked = copy.deepcopy(sdk["platforms"][0])
        mocked["platform_id"] = "example-portal"
        sdk["platforms"].append(mocked)

        def evaluate(command, cwd, env):
            return FakeRunner.evaluate(command, cwd, env, results=[])

        _, report, qa = self.verify(inputs=self.inputs(**{"sdk-report": sdk}),
                                    runner=FakeRunner({"evaluate-assertions": evaluate}))
        portal = {p["platform_id"]: p for p in report["platform_readiness"]}
        self.assertEqual(portal["example-portal"]["portal_status"], "BLOCKED_EXTERNAL")
        self.assertEqual(portal["generic-web"]["portal_status"], "NOT_APPLICABLE")
        self.assertEqual({p["platform_id"]: p["portal_status"] for p in qa["platform_checks"]},
                         {"example-portal": "BLOCKED_EXTERNAL", "generic-web": "NOT_APPLICABLE"})

        # With live-portal evidence for every SDK feature, it is observed.
        live = copy.deepcopy(sdk)
        for entry in live["platforms"]:
            for feature in entry["features"]:
                if feature["status"] == "working":
                    feature["observed_by"] = LIVE
        _, report, _ = self.verify(inputs=self.inputs(**{"sdk-report": live}),
                                   runner=FakeRunner({"evaluate-assertions": evaluate}))
        portal = {p["platform_id"]: p for p in report["platform_readiness"]}
        self.assertEqual(portal["example-portal"]["portal_status"], PASS)
        self.assertEqual(portal["example-portal"]["external_approval"], "not-claimed")

    def path_of(self, relative):
        return os.path.join(self.repo, relative)


if __name__ == "__main__":
    unittest.main()

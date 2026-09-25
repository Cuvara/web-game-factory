"""Core v1 RELEASE category: a draft release is made only from verified evidence.

    valid release                        -> SUCCESS, schema-valid draft release-manifest
    invalid release (bad manifest)       -> refused
    artifact hashes                      -> recorded, and match the files
    commit lineage mismatch              -> refused
    release before verify                -> refused
    release after verify FAIL / BLOCKED  -> refused, also through `release --run`
    release before G4 passes             -> refused through `release --run` and `--from`;
                                            a kill ends the run, a pass releases
    release with G4 not passed/superseded -> g4-not-passed (the step's own check)
    unreviewed (skipped / absent review) -> unreviewed, unless factory.release.allow_unreviewed
    approval of another commit than the
    one shipped (develop's, not sdk's)   -> review-commit-mismatch
    stale qa-report                      -> refused
    dirty checkout                       -> refused
    sourcemap / test / secret in a zip   -> refused
    reproducibility                      -> same inputs give the same archive hashes

Real git repositories, real archives, a fake `pnpm` first on PATH. Offline. The opt-in
Template class runs the real web-game-template release scripts on a copy of the sibling
checkout when WGF_TEMPLATE_RELEASE_TEST=1 and its node_modules exist.
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
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

from test_release_module import (NOW, CONTRACTS, Context, GameRepository,  # noqa: E402
                                 Inputs, ReleaseCase, git, pin, seal, step)
from wgf_release import ReleaseStep  # noqa: E402
from testenv import enabled  # noqa: E402
from wgf_release.package import file_sha256  # noqa: E402
from wgf_release.step import bundle_digest  # noqa: E402
from wgflib import paths, provenance  # noqa: E402
from wgflib.workflow import ArtifactOutput, StepOutcome, StepResult, WorkflowStep  # noqa: E402
from wgflib.workflow import mock  # noqa: E402
from wgflib.workflow.api import RunRequest, WorkflowAPI  # noqa: E402
from wgflib.workflow.config import FactoryConfig  # noqa: E402
from wgflib.workflow.model import RunStatus  # noqa: E402


class ValidRelease(ReleaseCase):
    def test_a_valid_release_is_drafted_from_a_passing_verification(self):
        result = self.release()
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
        manifest = result.artifacts[0].content
        self.assertEqual((manifest["state"], manifest["provenance"]["status"]), ("draft", "draft"))
        self.assertEqual(manifest["commit_sha"], self.game.head)
        lineage = {e["source"]: e["commit_sha"] for e in manifest["evidence"]["commit_lineage"]}
        self.assertEqual(set(lineage), {"qa-report", "verification-report", "sdk-report",
                                        "prototype-report", "checkout"})
        self.assertEqual(set(lineage.values()), {self.game.head})
        pinned = {p["artifact_type"] for p in manifest["provenance"]["inputs"]}
        self.assertEqual(pinned, {"qa-report", "verification-report", "sdk-report",
                                  "prototype-report", "scaffold-record", "review-report"})
        self.assertEqual(manifest["evidence"]["review"]["status"], "approved")
        self.assertEqual(manifest["evidence"]["review"]["reviewed_commit"], self.game.head)
        self.assertEqual(manifest["evidence"]["bundle_hash"],
                         bundle_digest(self.game.root, "dist"))

    def test_the_manifest_is_schema_valid(self):
        manifest = self.release().artifacts[0].content
        self.assertEqual(CONTRACTS.problems("release-manifest", manifest), [])
        # The full validator is not a rubber stamp: re-sealed, so only the schema can object.
        broken = provenance.seal(dict(copy.deepcopy(manifest), state="published"))
        self.assertTrue(any("/state" in p for p in
                            CONTRACTS.problems("release-manifest", broken)))
        broken = provenance.seal(dict(copy.deepcopy(manifest), packages=[
            dict(manifest["packages"][0], checksum="md5:1")]))
        self.assertTrue(any("/packages/0/checksum" in p for p in
                            CONTRACTS.problems("release-manifest", broken)))
        # ... and neither is the contract's major version.
        broken = provenance.seal(copy.deepcopy(manifest))
        broken["provenance"]["schema_version"] = "2.0.0"
        provenance.seal(broken)
        self.assertTrue(any("/provenance/schema_version" in p for p in
                            CONTRACTS.problems("release-manifest", broken)))

    def test_package_hashes_are_recorded_and_match_the_files(self):
        manifest = self.release().artifacts[0].content
        base = self.game.path("release", "r1")
        for package in manifest["packages"]:
            self.assertEqual(package["checksum"], file_sha256(os.path.join(base, package["filename"])))
            self.assertTrue(package["content_digest"].startswith("sha256:"))
        with open(os.path.join(base, "packages.json")) as handle:
            listed = {p["filename"]: p["checksum"] for p in json.load(handle)}
        self.assertEqual(listed, {p["filename"]: p["checksum"] for p in manifest["packages"]})

    def test_a_recorded_hash_that_does_not_match_its_file_is_refused(self):
        result = self.release(flags=["wrong-checksum"])
        self.assertEqual(result.outcome, StepOutcome.FAILED)
        self.assertFalse(result.retryable)
        self.assertIn("checksum-mismatch", self.refusal_codes(result))


class InvalidRelease(ReleaseCase):
    def test_a_bad_manifest_from_the_game_repository_is_refused(self):
        result = self.release(flags=["bad-manifest"])
        self.assertEqual(result.outcome, StepOutcome.FAILED)
        self.assertFalse(result.retryable)
        self.assertIn("invalid-manifest", self.refusal_codes(result))
        self.assertIn("changelog", result.error)

    def test_no_manifest_at_all_is_refused(self):
        result = self.release(flags=["no-manifest"])
        self.assertEqual(result.outcome, StepOutcome.FAILED)
        self.assertIn("invalid-manifest", self.refusal_codes(result))

    def test_the_game_manifest_is_held_to_the_full_contract(self):
        # Both pass a structural subset of the schema (a pattern-valid artifact_type, a
        # date-time-shaped string); the full contract refuses them.
        for flag, where in (("wrong-type", "/provenance/artifact_type"),
                            ("impossible-date", "/provenance/produced_at")):
            with self.subTest(flag=flag):
                result = self.release(flags=[flag])
                self.assertEqual(result.outcome, StepOutcome.FAILED)
                self.assertFalse(result.retryable)
                self.assertIn("invalid-manifest", self.refusal_codes(result))
                self.assertIn(where, result.error)


class Lineage(ReleaseCase):
    def test_an_sdk_report_about_another_commit_is_refused(self):
        result = self.release(self.game.evidence(sdk_commit="f" * 40))
        self.assertEqual(result.outcome, StepOutcome.FAILED)
        self.assertIn("commit-lineage-mismatch", self.refusal_codes(result))
        self.assertEqual(self.game.pnpm_calls(), [], "nothing is packaged on refusal")

    def test_a_prototype_report_about_another_commit_is_refused(self):
        result = self.release(self.game.evidence(prototype_commit="e" * 40))
        self.assertIn("commit-lineage-mismatch", self.refusal_codes(result))

    def test_a_checkout_that_moved_after_verification_is_refused(self):
        evidence = self.game.evidence()
        self.game.commit("src/main.ts", "export const game = 3;\n")
        result = self.release(evidence)
        self.assertEqual(result.outcome, StepOutcome.FAILED)
        self.assertIn("commit-lineage-mismatch", self.refusal_codes(result))
        self.assertIn("HEAD", result.error)

    def test_a_bundle_changed_since_verification_is_refused(self):
        evidence = self.game.evidence()
        self.game.write("dist/assets/app.js", "console.log('patched after QA');\n")
        result = self.release(evidence)
        self.assertEqual(result.outcome, StepOutcome.BLOCKED)
        self.assertIn("bundle-not-verified", self.refusal_codes(result))


class ReviewedAndPassed(ReleaseCase):
    """Only a commit an independent review approved, behind a passed G4, is drafted."""

    def test_a_skipped_review_is_refused_and_nothing_is_packaged(self):
        result = self.release(self.game.evidence(review={"verdict": "skipped"}))
        self.assertEqual((result.outcome, result.retryable), (StepOutcome.FAILED, False))
        self.assertEqual(self.refusal_codes(result), {"unreviewed"})
        self.assertEqual(self.game.pnpm_calls(), [])

    def test_an_unreviewed_build_is_drafted_only_with_allow_unreviewed(self):
        result = self.release(self.game.evidence(review={"verdict": "skipped"}),
                              context=Context(config={"release": {"allow_unreviewed": True}}))
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
        review = result.artifacts[0].content["evidence"]["review"]
        self.assertEqual(review["status"], "skipped")
        self.assertIn("UNREVIEWED", review["note"])
        self.assertIn("allow_unreviewed", review["note"])
        self.assertIn("UNREVIEWED", result.message)

    def test_an_approval_of_the_develop_commit_does_not_release_the_sdk_commit(self):
        develop = self.game.head
        sdk = self.game.commit("src/platform/gameplay.ts", "export const sdk = 1;\n")
        evidence = self.game.evidence(commit=sdk, prototype_commit=develop, sdk_base=develop,
                                      sdk_commits=[sdk],
                                      review={"verdict": "approve", "reviewed_commit": develop})
        result = self.release(evidence)
        self.assertEqual((result.outcome, result.retryable), (StepOutcome.FAILED, False))
        self.assertIn("review-commit-mismatch", self.refusal_codes(result))
        self.assertEqual(self.game.pnpm_calls(), [])

    def test_a_review_of_an_older_sdk_report_is_refused(self):
        evidence = self.game.evidence()
        older = self.game.evidence(sdk_commit=self.game.head)["sdk-report"]
        older["platforms"][0]["status"] = "partial"
        older = seal("sdk-report", {k: v for k, v in older.items() if k != "provenance"},
                     schema_version="1.0.0")
        # The approval names the shipped commit, but pins an sdk-report the run superseded.
        evidence["review-report"] = seal(
            "review-report", {k: v for k, v in evidence["review-report"].items()
                              if k != "provenance"},
            inputs=[pin(evidence["prototype-report"]), pin(older)], schema_version="1.0.0")
        result = self.release(evidence)
        self.assertIn("review-commit-mismatch", self.refusal_codes(result))
        self.assertIn("older sdk-report", result.error)

    def test_an_approval_with_no_reviewer_behind_it_is_refused(self):
        # A --mock review approves with reviewer kind none; it is not a review.
        evidence = self.game.evidence()
        body = {k: v for k, v in evidence["review-report"].items() if k != "provenance"}
        body["reviewer"] = {"kind": "none", "argv0": None, "exit_code": None,
                            "status": None, "killed_pids": []}
        evidence["review-report"] = seal(
            "review-report", body, inputs=evidence["review-report"]["provenance"]["inputs"],
            schema_version="1.0.0")
        result = self.release(evidence, context=Context(
            config={"release": {"allow_unreviewed": True}}))
        self.assertEqual((result.outcome, result.retryable), (StepOutcome.FAILED, False))
        self.assertIn("review-not-approved", self.refusal_codes(result))

    def test_release_is_refused_until_g4_is_passed(self):
        result = self.release(context=Context(gates_passed=()))
        self.assertEqual(result.outcome, StepOutcome.BLOCKED)
        self.assertEqual(self.refusal_codes(result), {"g4-not-passed"})
        self.assertEqual(self.game.pnpm_calls(), [])
        # Another gate passed is not G4.
        result = self.release(context=Context(gates_passed=("G2", "G3")))
        self.assertEqual(self.refusal_codes(result), {"g4-not-passed"})

    def test_the_required_gates_are_the_workflow_s_and_cannot_be_loosened_from_config(self):
        context = Context(gates_passed=(), config={"release": {"required_gates": []}})
        self.assertEqual(self.refusal_codes(self.release(context=context)), {"g4-not-passed"})
        # A workflow without a G4 checkpoint says so on its release step.
        result = self.release(context=Context(gates_passed=()), required_gates=[])
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)

    def test_malformed_required_gates_are_refused(self):
        result = self.release(required_gates="G4")
        self.assertEqual((result.outcome, result.retryable), (StepOutcome.FAILED, False))
        self.assertIn("required_gates", result.error)


class BeforeAndAfterVerify(ReleaseCase):
    def test_release_before_verify_is_refused(self):
        evidence = self.game.evidence(drop=("qa-report", "verification-report"))
        result = self.release(evidence, missing=["qa-report", "verification-report"])
        self.assertEqual(result.outcome, StepOutcome.BLOCKED)
        self.assertEqual(self.refusal_codes(result), {"no-qa-report", "no-verification-report"})
        self.assertEqual(self.game.pnpm_calls(), [])

    def test_release_after_verify_failed_is_refused(self):
        result = self.release(self.game.evidence(qa_verdict="fail", verdict="FAIL",
                                                 evidence_status="FAIL"))
        self.assertEqual(result.outcome, StepOutcome.FAILED)
        self.assertFalse(result.retryable)
        self.assertTrue({"qa-not-passed", "verification-not-passed"} <= self.refusal_codes(result))
        self.assertIn("vr-code-lint", result.error)
        self.assertEqual(self.game.pnpm_calls(), [])

    def test_release_after_verify_blocked_is_refused(self):
        result = self.release(self.game.evidence(qa_verdict="fail", verdict="BLOCKED",
                                                 evidence_status="UNVERIFIED"))
        self.assertEqual(result.outcome, StepOutcome.FAILED)
        self.assertIn("verification-not-passed", self.refusal_codes(result))

    def test_unverified_evidence_is_refused_even_with_a_pass_verdict(self):
        result = self.release(self.game.evidence(evidence_status="UNVERIFIED"))
        self.assertIn("evidence-too-weak", self.refusal_codes(result))

    def test_a_verification_without_evidence_statuses_is_refused(self):
        result = self.release(self.game.evidence(evidence_status=None))
        self.assertIn("evidence-status-missing", self.refusal_codes(result))


class StaleEvidence(ReleaseCase):
    def test_a_qa_report_older_than_the_newest_prototype_report_is_refused(self):
        evidence = self.game.evidence()
        newer = dict(evidence["prototype-report"])
        body = {k: v for k, v in newer.items() if k != "provenance"}
        body["iteration"] = 2
        evidence["prototype-report"] = seal("prototype-report", body, sequence=2,
                                            schema_version="1.0.0")
        result = self.release(evidence)
        self.assertEqual(result.outcome, StepOutcome.FAILED)
        self.assertIn("stale-qa-report", self.refusal_codes(result))

    def test_a_qa_report_not_computed_from_the_newest_verification_is_refused(self):
        evidence = self.game.evidence()
        body = {k: v for k, v in evidence["verification-report"].items() if k != "provenance"}
        body["gameplay_driver"] = {"id": "playwright-mcp"}
        evidence["verification-report"] = seal("verification-report", body, sequence=2)
        result = self.release(evidence)
        self.assertIn("stale-qa-report", self.refusal_codes(result))

    def test_a_qa_report_from_another_run_is_refused(self):
        result = self.release(self.game.evidence(run_id="some-other-run"))
        self.assertIn("foreign-qa-report", self.refusal_codes(result))


class DirtyCheckout(ReleaseCase):
    def test_an_untracked_file_is_refused(self):
        self.game.write("notes.txt", "scratch\n")
        result = self.release()
        self.assertEqual(result.outcome, StepOutcome.BLOCKED)
        self.assertIn("dirty-checkout", self.refusal_codes(result))
        self.assertEqual(self.game.pnpm_calls(), [])

    def test_a_modified_tracked_file_is_refused(self):
        self.game.write("src/main.ts", "export const game = 99;\n")
        self.assertIn("dirty-checkout", self.refusal_codes(self.release()))

    def test_a_verification_of_a_dirty_tree_is_refused(self):
        result = self.release(self.game.evidence(dirty=True))
        self.assertEqual(result.outcome, StepOutcome.BLOCKED)
        self.assertIn("verified-dirty-tree", self.refusal_codes(result))

    def test_a_verification_that_could_not_tell_whether_its_tree_was_clean_is_refused(self):
        # verify records dirty=None when `git status` failed: unknown is not clean.
        result = self.release(self.game.evidence(dirty=None))
        self.assertEqual(result.outcome, StepOutcome.BLOCKED)
        self.assertIn("verified-tree-unknown", self.refusal_codes(result))


class ForbiddenContent(ReleaseCase):
    def reverify_and_release(self, flags=()):
        # A different bundle is a different verification: evidence is rebuilt over it.
        return self.release(self.game.evidence(), flags=flags)

    def test_a_sourcemap_in_a_zip_is_refused(self):
        result = self.reverify_and_release(flags=["include-maps"])
        self.assertEqual(result.outcome, StepOutcome.FAILED)
        self.assertIn("no sourcemaps", result.error)
        self.assertIn("assets/app.js.map", result.error)

    def test_a_test_file_in_a_zip_is_refused(self):
        self.game.write("dist/tests/boot.spec.js", "test('boots', () => {});\n")
        result = self.reverify_and_release()
        self.assertEqual(result.outcome, StepOutcome.FAILED)
        self.assertIn("no test files", result.error)

    def test_an_env_file_in_a_zip_is_refused(self):
        self.game.write("dist/.env.production", "API_URL=https://example.invalid\n")
        result = self.reverify_and_release()
        self.assertIn("no environment or secret files", result.error)

    def test_a_secret_in_bundle_content_is_refused(self):
        self.game.write("dist/assets/app.js",
                        'const cfg={client_secret:"s3cr3t-0123456789abcdef"};\n')
        result = self.reverify_and_release()
        self.assertEqual(result.outcome, StepOutcome.FAILED)
        self.assertIn("no secret-looking content", result.error)
        self.assertIn("credential assignment", result.error)

    def test_a_private_key_in_bundle_content_is_refused(self):
        self.game.write("dist/assets/key.txt",
                        "-----BEGIN RSA PRIVATE KEY-----\nMIIB\n-----END RSA PRIVATE KEY-----\n")
        self.assertIn("private key", self.reverify_and_release().error)

    def test_ordinary_game_code_is_not_mistaken_for_a_secret(self):
        self.game.write("dist/assets/app.js",
                        'const token=getToken();const password=input.value;'
                        'const apiKey=cfg.apiKey;fetch("/api/key-values");\n')
        self.assertEqual(self.reverify_and_release().outcome, StepOutcome.SUCCESS)


class Reproducibility(ReleaseCase):
    def packages(self, result):
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
        return {p["filename"]: (p["checksum"], p["content_digest"])
                for p in result.artifacts[0].content["packages"]}

    def test_the_same_commit_and_bundle_give_the_same_archive_hashes(self):
        first = self.packages(self.release())
        second = self.packages(self.release())
        self.assertEqual(first, second)

    def test_a_rebuild_changes_archive_bytes_but_not_their_content_digest(self):
        # What web-game-template's packaging does (adm-zip stamps each entry with the file's
        # modification time): a rebuild of identical content is the same bundle to the
        # verification, but not the same archive bytes. The manifest says so.
        first = self.packages(self.release())
        self.game.touch_bundle(1_800_000_000)
        result = self.release()
        second = self.packages(result)
        for name in first:
            self.assertNotEqual(first[name][0], second[name][0])
            self.assertEqual(first[name][1], second[name][1])
        self.assertEqual(result.artifacts[0].content["evidence"]["reproducibility"]
                         ["archive_bytes"], "timestamp-dependent")


# -- through the engine: `release --run` after a failed verification ------------------------

class ContinueIn(ReleaseCase):
    """`wgf release --run <id>` picks the newest qa-report of the run. It must not release
    from one that failed, nor from an earlier passing one that newer work superseded."""

    # G4 between verify and release, as in new-game (only for the G4 tests below).
    G4 = ("    - id: prototype-review\n"
          "      type: human-checkpoint\n"
          "      stage: title:prototype-review\n"
          "      inputs: [qa-report, verification-report, prototype-report, title-strategy,"
          " game-design]\n"
          "      with: {gate: G4, choices: [pass, iterate, kill]}\n"
          "      on: {iterate: verify, kill: $end}\n")

    def api(self, plan, g4=False):
        game = self.game

        class Verify(WorkflowStep):
            type = "test.verify"

            def execute(self, inputs, context):
                outcome = plan.pop(0) if plan else "pass"
                artifacts = game.evidence(run_id=context.run_id, **(
                    {"qa_verdict": "fail", "verdict": "FAIL", "evidence_status": "FAIL"}
                    if outcome == "fail" else {}))
                outputs = [ArtifactOutput(t, a) for t, a in artifacts.items()]
                if outcome == "fail":
                    return StepResult(StepOutcome.FAILED, route="fail", artifacts=outputs,
                                      retryable=False, error="verification FAIL")
                return StepResult.success(outputs)

        module = type(sys)("wgf_release_continue_fakes")
        def register(registry):
            registry.register(Verify.type, Verify)
            # G4 is also decided on the terms of the bet (gates.yaml): a mock plan step puts
            # a title-strategy and a game-design in the run ahead of verification.
            registry.register("test.plan", mock.MockDesignStep)

        module.register = register
        sys.modules[module.__name__] = module
        self.addCleanup(sys.modules.pop, module.__name__, None)
        originals = ReleaseStep.__dict__["environ"], ReleaseStep.__dict__["clock"]
        ReleaseStep.environ = game.environ()
        ReleaseStep.clock = staticmethod(lambda: NOW)
        self.addCleanup(lambda: setattr(ReleaseStep, "environ", originals[0])
                        or setattr(ReleaseStep, "clock", originals[1]))
        path = os.path.join(self.scratch, "continue-release.workflow.yaml")
        with open(path, "w") as handle:
            text = textwrap.dedent("""\
                workflow:
                  id: continue-release
                  version: 1
                  start: verify
                  steps:
                    - id: verify
                      type: test.verify
                      stage: release:qa
                      outputs: [prototype-report, sdk-report, scaffold-record, verification-report, qa-report, review-report]
                      on:
                        fail: $fail
                    - id: release
                      type: release
                      stage: release:draft
                      inputs: [qa-report, verification-report, sdk-report, prototype-report, scaffold-record, review-report]
                      outputs: [release-manifest]
                      with:
                        repo_dir: %s
                        required_gates: []
                      next: $end
                """ % json.dumps(game.root))
            if g4:
                text = text.replace("    - id: release\n", self.G4 + "    - id: release\n", 1)
                # With the checkpoint in the workflow, release requires G4 (its default).
                text = text.replace("                        required_gates: []\n", "", 1)
                text = text.replace("  start: verify\n", "  start: plan\n", 1).replace(
                    "    - id: verify\n",
                    "    - id: plan\n      type: test.plan\n      stage: title:design\n"
                    "      outputs: [title-strategy, game-design]\n    - id: verify\n", 1)
            handle.write(text)
        config = FactoryConfig({"steps": {"modules": ["wgf_release", module.__name__]},
                                "storage": {"fsync": False}, "execution": {"delay_seconds": 0}})
        return WorkflowAPI(config=config, store_dir=os.path.join(self.scratch, "store"),
                           workflow=path)

    def test_release_run_after_a_failed_verification_is_refused(self):
        api = self.api(["fail"])
        state = api.run(RunRequest(project_id="fixture-game"))
        self.assertEqual(state.status, RunStatus.FAILED)
        # Two layers: the engine will not start `release` past a FAILED verify at all
        # (EngineError), and the release step itself refuses a failed qa-report
        # (qa-not-passed, covered by the step-level tests in this module).
        from wgflib.workflow.engine import EngineError
        with self.assertRaisesRegex(EngineError, "verify is FAILED"):
            api.run(RunRequest(run_id=state.run_id, scope="release"))
        state = api.store.load(state.run_id)
        self.assertNotIn("release", {k for k, v in state.steps.items() if v.visits})
        self.assertIsNone(state.latest_artifact("release-manifest"))
        self.assertEqual(self.game.pnpm_calls(), [])

    def test_release_run_after_a_passing_verification_drafts(self):
        api = self.api(["pass"])
        state = api.run(RunRequest(project_id="fixture-game"))
        self.assertEqual(state.status, RunStatus.COMPLETED, state.to_dict())
        self.assertIsNotNone(api.store.load(state.run_id).latest_artifact("release-manifest"))


class BehindG4(ContinueIn):
    """Release is impossible until G4 (prototype-review) passes - through the engine, with
    the real release step behind it."""

    def assert_nothing_released(self, api, run_id):
        state = api.store.load(run_id)
        self.assertFalse(state.steps.get("release") and state.steps["release"].visits)
        self.assertIsNone(state.latest_artifact("release-manifest"))
        self.assertEqual(self.game.pnpm_calls(), [])

    def test_release_run_past_an_unanswered_g4_is_refused(self):
        from wgflib.workflow.engine import EngineError
        api = self.api(["pass"], g4=True)
        state = api.run(RunRequest(project_id="fixture-game"))
        self.assertEqual((state.status, state.cursor), (RunStatus.WAITING, "prototype-review"))
        with self.assertRaisesRegex(EngineError, "prototype-review is WAITING"):
            api.run(RunRequest(run_id=state.run_id, scope="release"))
        with self.assertRaisesRegex(EngineError, "prototype-review is WAITING"):
            api.run(RunRequest(resume=state.run_id, from_step="release"))
        self.assert_nothing_released(api, state.run_id)

    def test_automation_cannot_pass_g4_for_release(self):
        api = self.api(["pass"], g4=True)
        state = api.run(RunRequest(project_id="fixture-game"))
        state = api.run(RunRequest(resume=state.run_id, decision="pass",
                                   decided_by="automation"))
        self.assertEqual((state.status, state.cursor), (RunStatus.WAITING, "prototype-review"))
        self.assert_nothing_released(api, state.run_id)

    def test_a_killed_title_is_never_released(self):
        from wgflib.workflow.engine import EngineError
        api = self.api(["pass"], g4=True)
        state = api.run(RunRequest(project_id="fixture-game"))
        state = api.run(RunRequest(resume=state.run_id, decision="kill", decided_by="human"))
        self.assertEqual((state.status, state.exit["route"]), (RunStatus.COMPLETED, "kill"))
        with self.assertRaisesRegex(EngineError, "cannot be continued"):
            api.run(RunRequest(run_id=state.run_id, scope="release"))
        self.assert_nothing_released(api, state.run_id)

    def test_a_pass_releases(self):
        api = self.api(["pass"], g4=True)
        state = api.run(RunRequest(project_id="fixture-game"))
        state = api.run(RunRequest(resume=state.run_id, decision="pass", decided_by="human"))
        self.assertEqual(state.status, RunStatus.COMPLETED, state.message)
        self.assertIsNotNone(api.store.load(state.run_id).latest_artifact("release-manifest"))

    def test_a_fresh_release_run_holds_no_evidence_and_is_refused(self):
        api = self.api(["pass"], g4=True)
        state = api.run(RunRequest(scope="release", project_id="fixture-game"))
        self.assertEqual(state.status, RunStatus.BLOCKED, state.message)
        self.assertIn("no-qa-report", state.steps["release"].message or "")
        # The step ran - a fresh run has no gate before it in its own scope - and refused.
        self.assertIsNone(api.store.load(state.run_id).latest_artifact("release-manifest"))
        self.assertEqual(self.game.pnpm_calls(), [])


# -- opt-in: the real template's release scripts --------------------------------------------

def _pinned_template():
    if not enabled("WGF_TEMPLATE_RELEASE_TEST"):
        return None, "set WGF_TEMPLATE_RELEASE_TEST=1 to run the template's release scripts"
    sys.path.insert(0, HERE)
    import pinned_template
    return pinned_template.with_dependencies()


TEMPLATE, _TEMPLATE_WHY = _pinned_template()
TEMPLATE = TEMPLATE or ""


@unittest.skipUnless(TEMPLATE and shutil.which("pnpm") and shutil.which("node"),
                     _TEMPLATE_WHY or "pnpm/node not on PATH")
class Template(unittest.TestCase):
    """Runs the real `pnpm release:package` / `release:manifest` of a copy of the template,
    and checks the step's view of what they produce: schema-valid, audited, and
    reproducible for the same built bundle."""

    def setUp(self):
        self.scratch = tempfile.mkdtemp(prefix="wgf-template-release-")
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)
        self.root = os.path.join(self.scratch, "game")
        top = {"node_modules", ".git", "release", "build", "dist", "test-results",
               "playwright-report"}

        def ignore(directory, names):
            # Generated output only at the top: scripts/build/ and scripts/release/ are code.
            skip = top if os.path.samefile(directory, TEMPLATE) else {"node_modules", "dist"}
            return [n for n in names if n in skip]
        shutil.copytree(TEMPLATE, self.root, ignore=ignore, symlinks=True)
        # From the local store only: the sibling's node_modules existing means it has been
        # installed on this machine, so nothing is fetched.
        installed = subprocess.run(["pnpm", "install", "--offline", "--frozen-lockfile"],
                                   cwd=self.root, capture_output=True, text=True)
        if installed.returncode != 0:
            self.skipTest("offline install failed: "
                          + (installed.stdout + installed.stderr)[-600:])
        git(self.root, "init", "-q", "-b", "main")
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", "template copy")
        if not os.path.isdir(os.path.join(self.root, "dist")):
            built = subprocess.run(["pnpm", "build"], cwd=self.root, capture_output=True,
                                   text=True)
            if built.returncode != 0:
                self.skipTest("the template does not build here: "
                              + (built.stdout + built.stderr)[-600:])

    def evidence(self, head):
        game = GameRepository.__new__(GameRepository)
        game.root = self.root
        return GameRepository.evidence(game, commit=head)

    def release(self):
        head = git(self.root, "rev-parse", "HEAD")
        instance = step(repo_dir=self.root)
        instance.environ = dict(os.environ)
        instance.clock = staticmethod(lambda: NOW)
        return instance.execute(Inputs(self.evidence(head)), Context())

    def test_the_template_packages_a_valid_reproducible_draft(self):
        first = self.release()
        self.assertEqual(first.outcome, StepOutcome.SUCCESS, first.error)
        manifest = first.artifacts[0].content
        self.assertEqual(CONTRACTS.problems("release-manifest", manifest), [])
        second = self.release()
        self.assertEqual(second.outcome, StepOutcome.SUCCESS, second.error)
        self.assertEqual([p["checksum"] for p in manifest["packages"]],
                         [p["checksum"] for p in second.artifacts[0].content["packages"]])
        # adm-zip stamps each entry with the file's mtime: honest about what a rebuild does.
        self.assertEqual(manifest["evidence"]["reproducibility"]["archive_bytes"],
                         "timestamp-dependent")
        self.assertEqual(manifest["evidence"]["package_audit"]["status"], "PASS")


if __name__ == "__main__":
    unittest.main()

"""Core v1 lineage: every artifact pins what its step consumed, and every build commit the
evidence names follows one rule from develop to release.

    ENGINE (wgflib/workflow/engine.py + contracts.check_lineage)
    correct pins                                   -> accepted
    a pin of a stale version of a consumed input   -> FAILED, not retried, nothing written
    a pin of an artifact the step did not consume  -> FAILED, not retried, nothing written
    an output that declares no lineage             -> not checked
    no validator configured                        -> not checked

    COMMITS (wgf_verification/lineage.py, applied by verify and release; real git)
    develop's commit + this run's keyed sdk commit -> verify PASS, release drafts
    a human commit between develop's and sdk's    -> commit-lineage-mismatch (verify, release)
    an sdk commit keyed by another run            -> commit-lineage-mismatch
    sdk built on another commit than develop's     -> commit-lineage-mismatch
    review approved another commit                 -> commit-lineage-mismatch
    review requested changes                       -> review-not-approved
    review skipped                                 -> released, carried as `skipped`
    no git access                                  -> refused, never trusted

The rule is docs/core-contracts.md §5. Offline; git is real, pnpm is a fake on PATH.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, HERE)

from test_release_module import ReleaseCase, git  # noqa: E402
from wgf_verification.checks.build import _upstream_commits  # noqa: E402
from wgf_verification.lineage import SDK_KEY_TRAILER, lineage_problems  # noqa: E402
from wgflib.hashing import content_hash  # noqa: E402
from wgflib.workflow.contracts import ArtifactContracts  # noqa: E402
from wgflib.workflow.definition import parse_definition  # noqa: E402
from wgflib.workflow.engine import WorkflowEngine  # noqa: E402
from wgflib.workflow.model import ArtifactOutput, RunStatus, StepResult  # noqa: E402
from wgflib.workflow.step import StepRegistry, WorkflowStep  # noqa: E402
from wgflib.workflow.store import RunStore  # noqa: E402
from wgflib.yamllite import load  # noqa: E402

# -- the engine --------------------------------------------------------------------------------

WORKFLOW = textwrap.dedent("""\
    workflow:
      id: lineage
      version: 1
      untyped_artifacts: [art-a, art-b, art-c]
      steps:
        - id: a
          type: test.produce
          outputs: [art-a]
        - id: b
          type: test.consume
          inputs: [art-a, art-c]
          outputs: [art-b]
          retry: {max_attempts: 3}
    """)


def sealed(artifact_type, inputs, n):
    content = {"provenance": {"artifact_id": f"wgf:{artifact_type}:lineage:20260101-{n:02d}",
                              "artifact_type": artifact_type, "inputs": inputs,
                              "content_hash": ""},
               "n": n}
    content["provenance"]["content_hash"] = content_hash(content)
    return content


class Pins:
    """What step b pins, per test: a callable(inputs) -> provenance.inputs."""
    choose = None
    produced = []


class Produce(WorkflowStep):
    type = "test.produce"

    def execute(self, inputs, context):
        content = sealed("art-a", [], context.execution)
        Pins.produced.append(content["provenance"]["content_hash"])
        return StepResult.success([ArtifactOutput("art-a", content)])


class Consume(WorkflowStep):
    type = "test.consume"
    executions = 0

    def execute(self, inputs, context):
        Consume.executions += 1
        return StepResult.success([ArtifactOutput("art-b", sealed(
            "art-b", Pins.choose(inputs), context.execution))])


def honest(inputs):
    return [{"artifact_id": inputs.load(t)["provenance"]["artifact_id"], "artifact_type": t,
             "content_hash": ref.content_hash} for t, ref in sorted(inputs.refs.items())]


class Engine(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.mkdtemp(prefix="wgf-lineage-")
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)
        Pins.produced, Consume.executions = [], 0
        registry = StepRegistry()
        registry.register(Produce.type, Produce)
        registry.register(Consume.type, Consume)
        definition = parse_definition(load(WORKFLOW))
        self.engine = WorkflowEngine(
            definition, registry, RunStore(os.path.join(self.scratch, "store"), fsync=False),
            artifact_validator=ArtifactContracts(untyped=definition.untyped_artifacts),
            sleep=lambda _: None)

    def run_b(self, choose, twice=False):
        Pins.choose = choose
        state = self.engine.start(scope="a")
        if twice:  # a newer art-a: the one b is given
            state = self.engine.continue_in(state.run_id, "a", force=True)
            self.assertEqual(len(state.artifacts["art-a"]), 2)
        return self.engine.continue_in(state.run_id, "b")

    def test_correct_pins_are_accepted(self):
        state = self.run_b(honest, twice=True)
        self.assertEqual(state.status, RunStatus.COMPLETED, state.message)
        self.assertEqual(len(state.artifacts["art-b"]), 1)

    def test_a_pin_of_a_stale_version_is_refused_and_not_retried(self):
        def stale(inputs):
            pins = honest(inputs)
            pins[0]["content_hash"] = Pins.produced[0]  # art-a v1; b consumed v2
            return pins

        state = self.run_b(stale, twice=True)
        self.assertEqual(state.status, RunStatus.FAILED)
        self.assertIn("does not pin what step 'b' consumed", state.steps["b"].error)
        self.assertIn(f"pins art-a at {Pins.produced[0]}", state.steps["b"].error)
        self.assertEqual(Consume.executions, 1, "a lineage violation is not retried")
        self.assertNotIn("art-b", state.artifacts, "nothing is written")

    def test_a_pin_of_an_artifact_it_did_not_consume_is_refused(self):
        def extra(inputs):
            # art-c is a declared input, but the run held none when b ran.
            return honest(inputs) + [{"artifact_id": "wgf:art-c:lineage:20260101-01",
                                      "artifact_type": "art-c",
                                      "content_hash": "sha256:" + "c" * 64}]

        state = self.run_b(extra)
        self.assertEqual(state.status, RunStatus.FAILED)
        self.assertIn("art-c", state.steps["b"].error)
        self.assertIn("did not consume", state.steps["b"].error)
        self.assertNotIn("art-b", state.artifacts)

    def test_a_second_pin_of_a_consumed_type_is_refused(self):
        def doubled(inputs):
            return honest(inputs) + [dict(honest(inputs)[0], content_hash=Pins.produced[0])]

        state = self.run_b(doubled, twice=True)
        self.assertEqual(state.status, RunStatus.FAILED)
        self.assertIn("which this step did not consume", state.steps["b"].error)

    def test_a_missing_pin_is_refused(self):
        state = self.run_b(lambda inputs: [])
        self.assertEqual(state.status, RunStatus.FAILED)
        self.assertIn("does not pin consumed art-a", state.steps["b"].error)

    def test_pins_of_types_the_step_does_not_take_are_left_alone(self):
        state = self.run_b(lambda inputs: honest(inputs) + [
            {"artifact_id": "claim:c-1", "artifact_type": "claim",
             "content_hash": "sha256:" + "d" * 64}])
        self.assertEqual(state.status, RunStatus.COMPLETED, state.message)

    def test_without_a_validator_nothing_is_checked(self):
        self.engine.artifact_validator = None
        state = self.run_b(lambda inputs: [])
        self.assertEqual(state.status, RunStatus.COMPLETED, state.message)


# -- the commit lineage, with real git ---------------------------------------------------------

def sdk_commit(repo, run_id="run-1", visit=1, path="src/platform/gameplay.ts"):
    """An sdk integration commit, keyed the way wgf_sdk/commit.py keys one."""
    full = os.path.join(repo, *path.split("/"))
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "a", encoding="utf-8") as handle:
        handle.write("export const integrated = true;\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "feat(platform): integrate the platform SDK\n\n"
        f"{SDK_KEY_TRAILER}: {run_id}:sdk:{visit}")
    return git(repo, "rev-parse", "HEAD")


class GitCall:
    def __init__(self, repo):
        self.repo = repo

    def __call__(self, *args):
        done = subprocess.run(["git", *args], cwd=self.repo, capture_output=True, text=True)
        return done.returncode == 0, done.stdout


class Session:
    """The slice of a VerificationSession the upstream-commit check reads, over real git."""

    class Result:
        def __init__(self, ok, stdout):
            self.ok, self.stdout = ok, stdout

    def __init__(self, repo, inputs, commit, run_id="run-1"):
        self.repo, self.inputs, self.commit, self.run_id = repo, inputs, commit, run_id

    def run(self, command, timeout_key="script"):
        ok, out = GitCall(self.repo)(*command[1:])
        return self.Result(ok, out)

    def blocked_by(self, *args, **kwargs):  # pragma: no cover - commit is always set here
        raise AssertionError("no commit")


class CommitLineage(ReleaseCase):
    """develop commits P; review reads P; sdk commits S on P; verify and release are of S."""

    def build(self, *, intruder=False, sdk_run="run-1", review="approve", reviewed=None,
              base=None):
        self.prototype = self.game.head                       # develop's commit
        if intruder:
            self.intruder = self.game.commit("src/game/extra.ts", "export const x = 1;\n",
                                             "fix: slipped in after review")
        self.sdk = sdk_commit(self.game.root, run_id=sdk_run)
        review_arg = None if review is None else {"verdict": review,
                                                  "reviewed_commit": reviewed}
        return self.game.evidence(commit=self.sdk, prototype_commit=self.prototype,
                                  sdk_base=base or self.prototype, sdk_commits=[self.sdk],
                                  review=review_arg)

    def verify_check(self, evidence):
        session = Session(self.game.root, evidence, self.game.head)
        return _upstream_commits(session)

    def test_develop_then_a_keyed_sdk_commit_verifies_and_releases(self):
        evidence = self.build()
        self.assertEqual(self.verify_check(evidence).status, "PASS")
        result = self.release(evidence)
        self.assertEqual(result.outcome, "SUCCESS", result.error)
        manifest = result.artifacts[0].content
        lineage = {e["source"]: e["commit_sha"] for e in manifest["evidence"]["commit_lineage"]}
        self.assertEqual(lineage["sdk-report"], self.sdk)
        self.assertEqual(lineage["checkout"], self.sdk)
        self.assertEqual(lineage["sdk-report.base"], self.prototype)
        self.assertEqual(lineage["prototype-report"], self.prototype)
        self.assertEqual(manifest["evidence"]["review"]["status"], "approved")
        self.assertEqual(manifest["evidence"]["review"]["reviewed_commit"], self.prototype)

    def test_an_intruding_non_sdk_commit_is_refused_by_verify_and_release(self):
        evidence = self.build(intruder=True)
        check = self.verify_check(evidence)
        self.assertEqual(check.status, "BLOCKED")
        self.assertIn("commit-lineage-mismatch", check.message)
        self.assertIn(self.intruder[:12], check.message)
        result = self.release(evidence)
        self.assertEqual((result.outcome, result.retryable), ("FAILED", False))
        self.assertIn("commit-lineage-mismatch", self.refusal_codes(result))
        self.assertIn(self.intruder[:12], result.error)
        self.assertEqual(self.game.pnpm_calls(), [], "nothing is packaged on refusal")

    def test_an_sdk_commit_keyed_by_another_run_is_refused(self):
        evidence = self.build(sdk_run="run-0")
        self.assertEqual(self.verify_check(evidence).status, "BLOCKED")
        self.assertIn("commit-lineage-mismatch", self.refusal_codes(self.release(evidence)))

    def test_sdk_built_on_another_commit_than_develop_s_is_refused(self):
        evidence = self.build(base="e" * 40)
        self.assertEqual(self.verify_check(evidence).status, "BLOCKED")
        result = self.release(evidence)
        self.assertIn("commit-lineage-mismatch", self.refusal_codes(result))
        self.assertIn("prototype-report", result.error)

    def test_an_sdk_report_that_hides_its_commits_is_refused(self):
        evidence = self.build()
        prototype = self.prototype
        problems = lineage_problems(
            verified=self.sdk, prototype_commit=prototype, sdk_report={"build_ref": {
                "commit_sha": self.sdk, "base_commit_sha": prototype, "sdk_commits": []}},
            git=GitCall(self.game.root), run_id="run-1")
        self.assertTrue(any("lists sdk commits" in p for p in problems), problems)
        self.assertEqual(self.release(evidence).outcome, "SUCCESS")

    def test_a_reviewer_approved_commit_other_than_the_prototype_is_refused(self):
        evidence = self.build(reviewed="b" * 40)
        result = self.release(evidence)
        self.assertEqual((result.outcome, result.retryable), ("FAILED", False))
        self.assertIn("commit-lineage-mismatch", self.refusal_codes(result))
        self.assertIn("review approved", result.error)

    def test_a_review_that_requested_changes_is_refused(self):
        result = self.release(self.build(review="request-changes"))
        self.assertIn("review-not-approved", self.refusal_codes(result))

    def test_a_skipped_review_is_carried_as_skipped_never_as_approved(self):
        result = self.release(self.build(review="skipped"))
        self.assertEqual(result.outcome, "SUCCESS", result.error)
        review = result.artifacts[0].content["evidence"]["review"]
        self.assertEqual(review["status"], "skipped")
        self.assertIn("UNREVIEWED", review["note"])
        self.assertIn("UNREVIEWED", result.message)
        self.assertEqual(result.artifacts[0].metadata["review"], "skipped")

    def test_no_review_in_the_run_is_recorded_as_absent(self):
        result = self.release(self.build(review=None))
        self.assertEqual(result.outcome, "SUCCESS", result.error)
        self.assertEqual(result.artifacts[0].content["evidence"]["review"]["status"], "absent")

    def test_without_git_the_history_is_not_trusted(self):
        evidence = self.build()
        problems = lineage_problems(verified=self.sdk, prototype_commit=self.prototype,
                                    sdk_report=evidence["sdk-report"], git=None)
        self.assertTrue(any("no git access" in p for p in problems), problems)
        broken = lambda *args: (False, "")  # noqa: E731 - git that cannot read anything
        problems = lineage_problems(verified=self.sdk, prototype_commit=self.prototype,
                                    sdk_report=evidence["sdk-report"], git=broken)
        self.assertTrue(problems)

    def test_placeholder_commits_are_never_a_lineage(self):
        evidence = self.game.evidence(prototype_commit="0" * 40)
        self.assertIn("commit-unknown", self.refusal_codes(self.release(evidence)))
        evidence = self.game.evidence(sdk_commit="unknown")
        self.assertIn("commit-unknown", self.refusal_codes(self.release(evidence)))


if __name__ == "__main__":
    unittest.main()

"""The release module (scripts/wgf_release): unit, contract and engine tests.

Every game repository here is a real git repository in a temporary directory, with a real
built bundle, and `pnpm` is a fake first on PATH (fixtures/release/fake-pnpm.py) that
packages the way web-game-template's release scripts do. The step runs it through
wgflib.procs exactly as it would the real one. Offline; no node, no package manager.

The helpers here are shared with test_core_release.py.
"""

import copy
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import textwrap
import unittest
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, HERE)

from wgf_release import ReleaseStep, register  # noqa: E402
from wgf_release.package import audit_package  # noqa: E402
from wgf_release.step import bundle_digest  # noqa: E402
from wgflib.hashing import content_hash  # noqa: E402
from wgflib.workflow import StepOutcome, StepRegistry  # noqa: E402
from wgflib.workflow.contracts import ArtifactContracts  # noqa: E402
from wgflib.workflow.definition import StepDefinition  # noqa: E402
from wgflib.workflow.model import ArtifactRef  # noqa: E402

FAKE_PNPM = os.path.join(HERE, "fixtures", "release", "fake-pnpm.py")
NOW = "2026-09-24T10:00:00Z"
CONTRACTS = ArtifactContracts()

GAME_CONFIG = textwrap.dedent("""\
    game:
      id: fixture-game
      name: Fixture Game
      version: 0.1.0
    build:
      output: dist
    platforms:
      - { id: generic-web, profile: generic-web@1.0.0, role: required }
      - { id: example-portal, profile: example-portal@1.0.0, role: optional }
    """)
PACKAGE_JSON = {
    "name": "fixture-game", "version": "0.1.0", "private": True,
    "packageManager": "pnpm@9.0.0",
    "scripts": {"build": "vite build", "release:package": "node scripts/release/package.mjs",
                "release:manifest": "node scripts/release/make-manifest.mjs"},
}
GITIGNORE = "node_modules/\ndist/\nbuild/\nrelease/\n"


def git(repo, *args):
    return subprocess.run(["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                           "-c", "commit.gpgsign=false", *args], cwd=repo, check=True,
                          capture_output=True, text=True).stdout.strip()


def seal(artifact_type, body, inputs=(), sequence=1, schema_version="1.1.0"):
    artifact = {"provenance": {
        "artifact_id": f"wgf:{artifact_type}:fixture-game:20260924-{sequence:02d}",
        "artifact_type": artifact_type, "schema_version": schema_version,
        "title_id": "fixture-game",
        "produced_by": {"role": "qa", "actor": "automation"},
        "produced_at": NOW, "inputs": list(inputs), "content_hash": "", "status": "draft"}}
    artifact.update(copy.deepcopy(body))
    artifact["provenance"]["content_hash"] = content_hash(artifact)
    return artifact


def pin(artifact):
    return {"artifact_id": artifact["provenance"]["artifact_id"],
            "artifact_type": artifact["provenance"]["artifact_type"],
            "content_hash": artifact["provenance"]["content_hash"]}


APPROVE = {"verdict": "approve"}


class Inputs:
    """StepInputs over fully formed artifacts, newest per type."""

    def __init__(self, artifacts, missing=()):
        self.contents = dict(artifacts)
        self.refs = {t: ArtifactRef(id=t, type=t, version=1, location=f"artifacts/{t}/v1.json",
                                    checksum="sha256:" + "0" * 64, produced_by="upstream",
                                    created_at=NOW,
                                    content_hash=c["provenance"]["content_hash"],
                                    schema_version=c["provenance"]["schema_version"])
                     for t, c in self.contents.items()}
        self.missing = list(missing)

    def __contains__(self, artifact_type):
        return artifact_type in self.refs

    def load(self, artifact_type):
        return self.contents.get(artifact_type)


class Logger:
    def __init__(self):
        self.records = []

    def info(self, message, **fields):
        self.records.append((message, fields))

    debug = warning = error = info


class Context:
    # G4 passed, as the engine reports it once a person has passed the kill gate: every
    # release in new-game happens behind it. A test of the gate itself passes others.
    def __init__(self, config=None, run_id="run-1", visit=1, gates_passed=("G4",)):
        self.config = config or {}
        self.gates_passed = list(gates_passed)
        self.run_id = run_id
        self.workflow_id = "new-game"
        self.current_step = "release"
        self.visit = visit
        self.execution = visit
        self.attempt = 1
        self.idempotency_key = f"{run_id}:release:{visit}"
        self.project_id = "fixture-game"
        self.environment = {}
        self.logger = Logger()
        self.events = []

    def process_hooks(self):
        return {"on_event": lambda kind, **data: self.events.append(kind)}


class GameRepository:
    """A committed game repository with a built bundle, and the evidence of verifying it."""

    def __init__(self, scratch):
        self.scratch = scratch
        self.root = os.path.join(scratch, "fixture-game")
        os.makedirs(os.path.join(self.root, "dist", "assets"))
        self.write("game.config.yaml", GAME_CONFIG)
        self.write("package.json", json.dumps(PACKAGE_JSON, indent=2))
        self.write("pnpm-lock.yaml", "lockfileVersion: '9.0'\n")
        self.write(".gitignore", GITIGNORE)
        self.write("CHANGELOG.md", "# Changelog\n\n## [1.0.0] - 2026-09-23\n\nBaseline.\n")
        self.write("src/main.ts", "export const game = 1;\n")
        # The built bundle, as verification left it. Sourcemaps are in dist/ on purpose:
        # the packaging script must leave them out.
        self.write("dist/index.html", "<!doctype html><script src='assets/app.js'></script>\n")
        self.write("dist/assets/app.js", "console.log('fixture game');\n")
        self.write("dist/assets/app.js.map", '{"version":3,"sources":["../src/main.ts"]}\n')
        self.touch_bundle(1_700_000_000)
        git(self.root, "init", "-q", "-b", "main")
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", "initial")
        self.bin = os.path.join(scratch, "bin")
        os.makedirs(self.bin)
        shim = os.path.join(self.bin, "pnpm")
        shutil.copy(FAKE_PNPM, shim)
        os.chmod(shim, os.stat(shim).st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
        self.log = os.path.join(scratch, "pnpm.log")

    # -- files ----------------------------------------------------------------------------

    def path(self, *parts):
        return os.path.join(self.root, *parts)

    def write(self, relative, text):
        full = self.path(relative)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as handle:
            handle.write(text)

    def touch_bundle(self, when):
        for directory, _, files in os.walk(self.path("dist")):
            for name in files:
                os.utime(os.path.join(directory, name), (when, when))

    @property
    def head(self):
        return git(self.root, "rev-parse", "HEAD")

    def commit(self, relative, text, message="change"):
        self.write(relative, text)
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", message)
        return self.head

    def environ(self, flags=()):
        env = dict(os.environ)
        env["PATH"] = self.bin + os.pathsep + env.get("PATH", "")
        env["WGF_SCRIPTS"] = SCRIPTS
        env["FAKE_PNPM"] = ",".join(flags)
        env["FAKE_PNPM_LOG"] = self.log
        env.pop("WGF_GAME_REPO", None)
        return env

    def pnpm_calls(self):
        if not os.path.exists(self.log):
            return []
        with open(self.log) as handle:
            return [json.loads(line) for line in handle if line.strip()]

    # -- the evidence of verifying it -----------------------------------------------------

    def evidence(self, *, commit=None, qa_verdict="pass", verdict="PASS",
                 evidence_status="PASS_MOCK", dirty=False, bundle_hash=None, run_id="run-1",
                 sdk_commit=None, prototype_commit=None, platforms=None, schema_version="1.1.0",
                 drop=(), sdk_base=None, sdk_commits=None, review=APPROVE):
        """The artifacts a run holds after a verification of this repository.

        `sdk_base` (+ `sdk_commits`) makes a 1.2.0 sdk-report that integrated on that commit;
        `review` ({verdict, reviewed_commit}) is the run's newest review-report - by default
        the sdk-review's approval of the shipped (sdk, verified) commit; None: no review.
        """
        commit = commit or self.head
        prototype = seal("prototype-report", {
            "title_id": "fixture-game",
            "build_ref": {"commit_sha": prototype_commit or commit,
                          "url": "https://example.invalid/build"},
            "iteration": 1,
            "proved": [{"question": "Does the core loop hold attention?",
                        "verdict": "inconclusive", "evidence": "fixture"}],
            "kill_criteria_eval": [{"criterion_id": "kc-1", "breached": False, "measured": 1}],
            "playtest_sessions": [{"observer": "fixture", "player_context": "internal",
                                   "duration_s": 60, "notes": "fixture"}],
            "recommendation": {"decision": "iterate", "rationale": "fixture"}}, schema_version="1.0.0")
        sdk_ref = {"commit_sha": sdk_commit or commit}
        if sdk_base is not None:
            sdk_ref.update(base_commit_sha=sdk_base, sdk_commits=list(sdk_commits or []))
        sdk = seal("sdk-report", {
            "title_id": "fixture-game", "build_ref": sdk_ref,
            "platforms": [{"platform_id": "generic-web", "profile_version": "1.0.0",
                           "status": "working", "features": [
                               {"feature": "loading-progress", "status": "working",
                                "observed_by": "SDK conformance suite (fake portal SDK)"}]}]},
            schema_version="1.0.0")
        scaffold = seal("scaffold-record", {
            "title_id": "fixture-game",
            "repository": {"owner": "example", "name": "fixture-game"},
            "template": {"repository": "example/web-game-template",
                         "commit_sha": "a" * 40},
            "game_config": {"path": "game.config.yaml"}, "outcome": "created"},
            schema_version="1.0.0")
        upstream = [pin(a) for a in (prototype, sdk, scaffold)]
        readiness = platforms if platforms is not None else [
            {"platform_id": "generic-web", "profile": "generic-web@1.0.0", "role": "required",
             "readiness": "ready", "checks": ["platform.hooks:generic-web"],
             "blocking_checks": [], "external_approval": "not-claimed",
             "evidence_status": "PASS_MOCK", "portal_status": "NOT_APPLICABLE"},
            {"platform_id": "example-portal", "profile": "example-portal@1.0.0",
             "role": "optional", "readiness": "ready",
             "checks": ["platform.hooks:example-portal"], "blocking_checks": [],
             "external_approval": "not-claimed", "evidence_status": "PASS_MOCK",
             "portal_status": "BLOCKED_EXTERNAL"}]
        failed = [] if verdict == "PASS" else ["code.lint"]
        verification = seal("verification-report", {
            "title_id": "fixture-game",
            "commit": {"sha": commit, "dirty": dirty, "repository": self.root},
            "build_artifact": {"status": "built", "path": "dist",
                               "content_hash": bundle_hash or bundle_digest(self.root, "dist"),
                               "files": 3, "bytes": 100},
            "gameplay_driver": {"id": "repository-playwright"},
            "checks": [{"id": "code.lint", "category": "code", "title": "Lint",
                        "status": "PASS" if verdict == "PASS" else "FAIL", "required": True,
                        "message": "exited 0",
                        "evidence": [{"kind": "command", "summary": "`pnpm run lint` exited 0",
                                      "command": "pnpm run lint", "exit_code": 0}]}],
            "summary": {"total": 1, "PASS": int(verdict == "PASS"),
                        "FAIL": int(verdict != "PASS"), "BLOCKED": 0, "WARNING": 0},
            "failed_checks": failed, "blocked_checks": [], "warning_checks": [],
            "platform_readiness": readiness, "verdict": verdict,
            **({"evidence_status": evidence_status} if evidence_status else {}),
            "workflow": {"run_id": run_id, "step_id": "verify", "visit": 1}},
            inputs=upstream, schema_version=schema_version)
        qa = seal("qa-report", {
            "title_id": "fixture-game", "release_id": f"candidate-{commit[:12]}",
            "build_ref": {"commit_sha": commit},
            "suites": [{"name": "lint", "passed": 1, "failed": 0}],
            "blocking_defects": [] if qa_verdict == "pass" else [
                {"id": "vr-code-lint", "severity": "blocker", "summary": "Lint: FAIL",
                 "repro": "Run `pnpm run lint`."}],
            "perf_results": [{"device_class": "lowend-android-proxy", "fps": 50,
                              "within_budget": True}],
            "verdict": qa_verdict,
            **({"evidence_status": evidence_status if qa_verdict == "pass" else "FAIL"}
               if evidence_status else {}),
            "workflow": {"run_id": run_id, "step_id": "verify", "visit": 1}},
            inputs=upstream + [pin(verification)], schema_version=schema_version)
        artifacts = {"prototype-report": prototype, "sdk-report": sdk,
                     "scaffold-record": scaffold, "verification-report": verification,
                     "qa-report": qa}
        if review is not None:
            artifacts["review-report"] = review_report(prototype, sdk, **review)
        return {t: a for t, a in artifacts.items() if t not in drop}


def review_report(prototype, sdk=None, verdict="approve", reviewed_commit=None):
    """A review-report of the sdk-report's commit - what sdk-review reads - or, without an
    sdk-report, of `prototype`'s; `reviewed_commit` overrides both. It pins what it read."""
    commit = reviewed_commit or (sdk or prototype)["build_ref"]["commit_sha"]
    skipped = verdict == "skipped"
    return seal("review-report", {
        "title_id": "fixture-game", "reviewed_commit": commit, "baseline_commit": None,
        "verdict": verdict,
        "blockers": [{"id": "b-1", "file": None, "summary": "fixture blocker",
                      "severity": "blocker"}] if verdict == "request-changes" else [],
        "failure": None,
        "reviewer": {"kind": "none" if skipped else "command",
                     "argv0": None if skipped else "reviewer", "exit_code": None if skipped else 0,
                     "status": None if skipped else "exited", "killed_pids": []},
        "isolation": {"checked_paths": 0, "violations": [], "intact": True, "restored": None},
        "iteration": 1, "attempt": 1, "duration_s": 0, "timed_out": False},
        inputs=[pin(a) for a in (prototype, sdk) if a is not None], schema_version="1.0.0")


def step(**params):
    definition = StepDefinition({
        "id": "release", "type": "release",
        "inputs": ["qa-report", "verification-report", "sdk-report", "prototype-report",
                   "scaffold-record", "review-report"],
        "outputs": ["release-manifest"], "with": params}, retry=None, max_visits=None)
    return ReleaseStep(definition)


class ReleaseCase(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.mkdtemp(prefix="wgf-release-")
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)
        self.game = GameRepository(self.scratch)

    def release(self, artifacts=None, flags=(), context=None, missing=(), **params):
        params.setdefault("repo_dir", self.game.root)
        instance = step(**{k: v for k, v in params.items() if v is not None})
        instance.environ = self.game.environ(flags)
        instance.clock = staticmethod(lambda: NOW)
        artifacts = self.game.evidence() if artifacts is None else artifacts
        result = instance.execute(Inputs(artifacts, missing), context or Context())
        if result.outcome == StepOutcome.SUCCESS:
            manifest = result.artifacts[0].content
            self.assertEqual(CONTRACTS.problems("release-manifest", manifest), [])
        else:
            self.assertEqual(result.artifacts, [], "a refused release produces no manifest")
        return result

    def refusal_codes(self, result):
        return {r["code"] for r in result.data.get("refusals", [])}


# -- unit: the step on its own --------------------------------------------------------------

class Registration(unittest.TestCase):
    def test_the_module_registers_the_release_type(self):
        registry = register(StepRegistry())
        self.assertIs(registry.resolve("release"), ReleaseStep)


class Drafting(ReleaseCase):
    def test_a_verified_clean_commit_is_drafted(self):
        result = self.release()
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error or result.message)
        manifest = result.artifacts[0].content
        self.assertEqual(manifest["state"], "draft")
        self.assertEqual(manifest["release_id"], "r1")
        self.assertEqual(manifest["kind"], "initial")
        self.assertEqual(manifest["version"], "0.1.0")
        self.assertEqual(manifest["commit_sha"], self.game.head)
        self.assertIsNone(manifest["frozen_at"])
        self.assertEqual(manifest["workflow"]["run_id"], "run-1")
        self.assertEqual(manifest["template"], {
            "repository": "example/web-game-template", "commit_sha": "a" * 40,
            "version": "1.0.0", "source": "CHANGELOG.md (first release heading)"})
        self.assertEqual([p["platform_id"] for p in manifest["packages"]],
                         ["generic-web", "example-portal"])
        self.assertIn("nothing published", result.message)
        # The game repository holds the release; the run holds the same manifest.
        with open(self.game.path("release", "r1", "manifest.json")) as handle:
            on_disk = json.load(handle)
        self.assertEqual(on_disk, manifest)

    def test_both_release_scripts_run_through_the_package_manager(self):
        context = Context()
        self.release(context=context)
        calls = self.game.pnpm_calls()
        self.assertEqual(calls[0], ["run", "release:package", "--release", "r1"])
        self.assertEqual(calls[1][:4], ["run", "release:manifest", "--release", "r1"])
        self.assertIn("draft", calls[1])
        # Every child ran as an owned process tree reporting to the step.
        self.assertIn("spawned", context.events)
        self.assertIn("exited", context.events)

    def test_evidence_is_carried_never_upgraded(self):
        manifest = self.release().artifacts[0].content
        evidence = manifest["evidence"]
        self.assertEqual(evidence["status"], "PASS_MOCK")
        self.assertEqual({p["platform_id"]: (p["evidence_status"], p["portal_status"])
                          for p in evidence["platforms"]},
                         {"generic-web": ("PASS_MOCK", "NOT_APPLICABLE"),
                          "example-portal": ("PASS_MOCK", "BLOCKED_EXTERNAL")})
        self.assertTrue(all(p["external_approval"] == "not-claimed"
                            for p in evidence["platforms"]))

    def test_the_release_id_is_reused_for_the_same_commit_and_advanced_for_a_new_one(self):
        self.assertEqual(self.release().artifacts[0].content["release_id"], "r1")
        self.assertEqual(self.release().artifacts[0].content["release_id"], "r1")
        self.game.commit("src/main.ts", "export const game = 2;\n")
        second = self.release(self.game.evidence())
        self.assertEqual(second.outcome, StepOutcome.SUCCESS, second.error)
        self.assertEqual(second.artifacts[0].content["release_id"], "r2")
        self.assertEqual(second.artifacts[0].content["kind"], "content")

    def test_an_explicit_release_id_for_another_commit_is_refused(self):
        self.release()
        self.game.commit("src/main.ts", "export const game = 2;\n")
        result = self.release(self.game.evidence(), release_id="r1")
        self.assertEqual(result.outcome, StepOutcome.FAILED)
        self.assertIn("release-id-taken", self.refusal_codes(result))

    def test_the_checkout_is_found_from_the_release_config_and_the_scaffold_record(self):
        instance = step()
        instance.environ = self.game.environ()
        instance.clock = staticmethod(lambda: NOW)
        context = Context(config={"release": {"checkouts": self.scratch}})
        result = instance.execute(Inputs(self.game.evidence()), context)
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)

    def test_no_checkout_blocks(self):
        result = self.release(repo_dir=os.path.join(self.scratch, "absent"))
        self.assertEqual(result.outcome, StepOutcome.BLOCKED)
        self.assertIn("no-checkout", self.refusal_codes(result))
        self.assertEqual(self.game.pnpm_calls(), [])

    def test_a_newer_major_schema_is_refused(self):
        artifacts = self.game.evidence(schema_version="2.0.0")
        result = self.release(artifacts)
        self.assertEqual(result.outcome, StepOutcome.FAILED)
        self.assertFalse(result.retryable)

    def test_a_packaging_failure_is_not_retried(self):
        result = self.release(flags=["fail-package"])
        self.assertEqual(result.outcome, StepOutcome.FAILED)
        self.assertFalse(result.retryable)
        self.assertIn("package-failed", self.refusal_codes(result))
        self.assertIn("something broke", result.error)

    def test_a_missing_package_manager_blocks(self):
        instance = step(repo_dir=self.game.root)
        env = self.game.environ()
        env["PATH"] = os.path.join(self.scratch, "nowhere")
        instance.environ = env
        result = instance.execute(Inputs(self.game.evidence()), Context())
        # git itself is gone too: the checkout cannot be read.
        self.assertEqual(result.outcome, StepOutcome.BLOCKED)


class PackageAudit(ReleaseCase):
    def test_a_clean_archive_passes_every_rule(self):
        self.release()
        audit = audit_package(self.game.path("release", "r1", "generic-web.zip"))
        self.assertEqual(audit["findings"], [])
        self.assertTrue(audit["index_at_root"])
        self.assertEqual(audit["files"], 2)

    def test_an_archive_without_index_at_its_root_is_refused(self):
        result = self.release(flags=["nested"])
        self.assertEqual(result.outcome, StepOutcome.FAILED)
        self.assertIn("index.html at the archive root", result.error)


# -- contract: through the real engine ------------------------------------------------------

class ThroughTheEngine(ReleaseCase):
    """verify (scripted) -> release (real), the way factory.yaml wires the module in."""

    def workflow(self):
        path = os.path.join(self.scratch, "release-flow.workflow.yaml")
        with open(path, "w") as handle:
            handle.write(textwrap.dedent("""\
                workflow:
                  id: release-flow
                  version: 1
                  start: verify
                  steps:
                    - id: verify
                      type: test.verify
                      stage: release:qa
                      outputs: [prototype-report, sdk-report, scaffold-record, verification-report, qa-report, review-report]
                    - id: release
                      type: release
                      stage: release:draft
                      inputs: [qa-report, verification-report, sdk-report, prototype-report, scaffold-record, review-report]
                      outputs: [release-manifest]
                      with:
                        repo_dir: %s
                        required_gates: []    # this workflow has no G4 checkpoint
                      next: $end
                """ % json.dumps(self.game.root)))
        return path

    def test_the_release_step_runs_in_a_workflow_and_persists_its_manifest(self):
        from wgflib.workflow import ArtifactOutput, StepResult, WorkflowStep
        from wgflib.workflow.api import RunRequest, WorkflowAPI
        from wgflib.workflow.config import FactoryConfig
        from wgflib.workflow.model import RunStatus

        game = self.game

        class Verify(WorkflowStep):
            type = "test.verify"

            def execute(self, inputs, context):
                return StepResult.success([ArtifactOutput(t, a) for t, a in
                                           game.evidence(run_id=context.run_id).items()])

        module = type(sys)("wgf_release_test_verify")
        module.register = lambda registry: registry.register(Verify.type, Verify)
        sys.modules[module.__name__] = module
        self.addCleanup(sys.modules.pop, module.__name__, None)
        originals = ReleaseStep.__dict__["environ"], ReleaseStep.__dict__["clock"]
        ReleaseStep.environ = game.environ()
        ReleaseStep.clock = staticmethod(lambda: NOW)
        self.addCleanup(self._restore, originals)

        config = FactoryConfig({"steps": {"modules": ["wgf_release", module.__name__]},
                                "storage": {"fsync": False}})
        api = WorkflowAPI(config=config, store_dir=os.path.join(self.scratch, "store"),
                          workflow=self.workflow())
        state = api.run(RunRequest(project_id="fixture-game"))
        self.assertEqual(state.status, RunStatus.COMPLETED, state.to_dict())
        stored = api.store.load(state.run_id)
        ref = stored.latest_artifact("release-manifest")
        manifest = api.store.read_artifact(state.run_id, ref)
        self.assertEqual(ref.metadata["release_id"], "r1")
        self.assertEqual(manifest["workflow"]["run_id"], state.run_id)
        self.assertEqual(manifest["evidence"]["qa_report"]["content_hash"],
                         stored.latest_artifact("qa-report").content_hash)

    @staticmethod
    def _restore(originals):
        ReleaseStep.environ, ReleaseStep.clock = originals


# -- schema: ajv, when asked ----------------------------------------------------------------

@unittest.skipUnless(os.environ.get("WGF_AJV") == "1", "set WGF_AJV=1 to validate with ajv")
class Ajv(ReleaseCase):
    def test_the_drafted_manifest_validates_with_ajv(self):
        manifest = self.release().artifacts[0].content
        path = os.path.join(self.scratch, "manifest.json")
        with open(path, "w") as handle:
            json.dump(manifest, handle)
        completed = subprocess.run(
            ["npx", "--yes", "-p", "ajv-cli@5", "-p", "ajv-formats@2", "ajv", "validate",
             "-s", "core/artifacts/release-manifest.schema.json",
             "-r", "core/artifacts/shared/*.schema.json",
             "-c", "ajv-formats", "--spec=draft2020", "--strict=false", "-d", path],
            cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)


if __name__ == "__main__":
    unittest.main()

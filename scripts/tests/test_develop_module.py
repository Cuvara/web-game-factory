"""The development module (scripts/wgf_develop), against docs/workflow-module-contract.md §11.

Deterministic and offline. Game repositories are throwaway git repositories in a temp
directory - git is real, because the module's idempotency is a property of real commits -
while every other process (pnpm, the developer command) is a fake that records its argv.

    python -m unittest discover scripts/tests
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
sys.path.insert(0, SCRIPTS)

import wgf_develop  # noqa: E402
from wgf_develop import brief as briefs  # noqa: E402
from wgf_develop.checks import conformance  # noqa: E402
from wgf_develop.repository import KEY_TRAILER, GitRepo, Runner, RunResult  # noqa: E402
from wgf_develop.settings import Settings, SettingsError  # noqa: E402
from wgf_develop.step import DevelopStep  # noqa: E402
from wgflib.hashing import content_hash  # noqa: E402
from wgflib.workflow import mock  # noqa: E402
from wgflib.workflow.api import RunRequest, WorkflowAPI  # noqa: E402
from wgflib.workflow.checkpoint import register as register_checkpoint  # noqa: E402
from wgflib.workflow.config import FactoryConfig  # noqa: E402
from wgflib.workflow.contracts import ArtifactContracts  # noqa: E402
from wgflib.workflow.definition import load_definition  # noqa: E402
from wgflib.workflow.model import RunStatus, StepOutcome  # noqa: E402
from wgflib.workflow.step import StepInputs, StepRegistry  # noqa: E402

FIXTURES = mock.FIXTURES
HAS_GIT = shutil.which("git") is not None
IDENTITY = ["-c", "user.name=Test", "-c", "user.email=test@example.invalid"]
AUTHOR = {"name": "Test", "email": "test@example.invalid"}
EPOCH = "2026-09-23T00:00:00Z"
TITLE = "demo-title"


def fixture(artifact_type):
    with open(os.path.join(FIXTURES, f"{artifact_type}.json"), encoding="utf-8") as handle:
        body = json.loads(handle.read().replace("mock-title", TITLE))
    artifact = {"provenance": {
        "artifact_id": f"wgf:{artifact_type}:{TITLE}:20260101-01",
        "artifact_type": artifact_type, "schema_version": "1.0.0", "title_id": TITLE,
        "produced_by": {"role": "research", "actor": "automation"}, "produced_at": EPOCH,
        "inputs": [], "content_hash": "", "status": "draft"}}
    artifact.update(body)
    artifact["provenance"]["content_hash"] = content_hash(artifact)
    return artifact


def inputs_for(types=("game-design", "asset-manifest", "scaffold-record", "title-strategy"),
               overrides=None):
    contents = {t: fixture(t) for t in types}
    contents.update(overrides or {})
    refs = {t: SimpleNamespace(content_hash=c["provenance"]["content_hash"],
                               schema_version=c["provenance"]["schema_version"])
            for t, c in contents.items()}
    declared = ("game-design", "asset-manifest", "scaffold-record", "title-strategy",
                "qa-report")
    return StepInputs(refs, lambda ref: next(c for t, c in contents.items()
                                             if refs[t] is ref),
                      [t for t in declared if t not in contents])


class Log:
    def __init__(self):
        self.lines = []

    def __getattr__(self, level):
        return lambda message, **fields: self.lines.append((level, message, fields))


def context(config, key="run-1:develop:1", visit=1, attempt=1, decision=None):
    return SimpleNamespace(config=config, params={}, idempotency_key=key, visit=visit,
                           attempt=attempt, execution=visit, decision=decision,
                           logger=Log(), previous_outputs=[], run_id=key.split(":")[0],
                           mock=False, environment={})


# -- a conformant game, as a developer would leave it -----------------------------------------

SCAFFOLD_FILES = {
    "game.config.yaml": "game:\n  id: demo-title\nengine:\n  type: pixijs\nplatforms:\n"
                        "  - { id: generic-web, profile: generic-web@1.0.0, role: required }\n",
    "package.json": json.dumps({"name": "demo", "scripts": {
        "typecheck": "tsc", "lint": "eslint", "test": "vitest", "build": "vite build",
        "test:e2e": "playwright test", "format": "prettier --check ."},
        "dependencies": {"@wgf/game-core": "workspace:*"}}),
    "packages/game-core/src/index.ts": "export {};\n",
    "src/main.ts": 'import { BootScene } from "./game/boot-scene.js";\n',
    "src/game/boot-scene.ts": "export class BootScene {}\n",
    "src/rendering/create-renderer.ts": (
        'const a = () => import("@wgf/pixi-framework");\n'
        'const b = () => import("@wgf/three-framework");\n'),
    "src/core/i18n.ts": "// Yandex needs ru, CrazyGames en, GameVui vi.\nexport {};\n",
}


def dev_report(brief):
    return {
        "engine": brief["engine"],
        "systems": {name: "done" for name, _ in briefs.REQUIRED_SYSTEMS},
        "mvp": [{"item": item, "status": "built"} for item in brief["mvp"]],
        "placements": [{"id": f"p{i}", "kind": p["kind"], "trigger": p["trigger"]}
                       for i, p in enumerate(brief["placements"])],
        "integration_status": {"platform_sdk": "partial", "monetization": "partial",
                               "analytics": "partial", "persistence": "working"},
        "assets": [{"id": "beat-track", "status": "placeholder"}],
        "scope_deltas": [],
        "known_issues": [],
        "how_to_play": "Tap.",
    }


def write_game(root, extra=None):
    """What a developer produces: the scaffold replaced, the seam, a view, the report."""
    with open(os.path.join(root, briefs.BRIEF_DIR, "brief.json"), encoding="utf-8") as handle:
        brief = json.load(handle)
    files = {
        "src/main.ts": 'import { PulseLanes } from "./game/app.js";\n',
        "src/game/app.ts": 'import type { Game } from "@wgf/game-core";\nexport {};\n',
        "src/game/integration.ts": "export interface GameIntegration {}\n",
        "src/rendering/pixijs/view.ts": 'import { Graphics } from "pixi.js";\nexport {};\n',
        "src/platform/integration.ts": "platform.showRewarded();\n",
        briefs.REPORT_PATH: json.dumps(dev_report(brief)),
    }
    files.update(extra or {})
    for relative, text in files.items():
        path = os.path.join(root, relative)
        if text is None:
            if os.path.exists(path):
                os.remove(path)
            continue
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
    scaffold_scene = os.path.join(root, "src/game/boot-scene.ts")
    if os.path.exists(scaffold_scene):
        os.remove(scaffold_scene)


class FakeRunner(Runner):
    """Real git; scripted everything else."""

    def __init__(self, fail=(), unavailable=(), on_develop=None, develop_exit=0):
        self.calls = []
        self.fail = set(fail)
        self.unavailable = set(unavailable)
        self.on_develop = on_develop
        self.develop_exit = develop_exit

    def run(self, argv, cwd, timeout=None, env=None):
        if argv[0] == "git":
            return super().run(argv, cwd, timeout, env)
        self.calls.append(list(argv))
        if argv[0] == "pnpm":
            name = argv[2] if argv[1] == "run" else argv[1]
            if name in self.unavailable:
                return RunResult(argv, 1, "browserType.launch: Executable doesn't exist")
            return RunResult(argv, 1 if name in self.fail else 0, f"{name} output",
                             duration_s=0.1)
        if self.on_develop:
            self.on_develop(cwd)
        return RunResult(argv, self.develop_exit, "developer output")

    def developer_calls(self):
        return [c for c in self.calls if c[0] != "pnpm"]


def step_with(runner):
    class Step(DevelopStep):
        runner_factory = staticmethod(lambda: runner)
        clock = staticmethod(lambda: EPOCH)

    definition = SimpleNamespace(id="develop", type="develop", params={},
                                 outputs=["prototype-report"])
    return Step(definition)


@unittest.skipUnless(HAS_GIT, "git is not installed")
class DevelopCase(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.mkdtemp(prefix="wgf-develop-")
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)
        self.repo = os.path.join(self.scratch, TITLE)
        os.makedirs(self.repo)
        for relative, text in SCAFFOLD_FILES.items():
            path = os.path.join(self.repo, relative)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(text)
        self.git("init", "-q", "-b", "main")
        self.git("add", "-A")
        self.git(*IDENTITY, "commit", "-q", "-m", "scaffold")
        self.baseline = self.git("rev-parse", "HEAD").strip()

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.repo, check=True, capture_output=True,
                              text=True).stdout

    def config(self, **develop):
        data = {"checkouts": self.scratch, "author": AUTHOR}
        data.update(develop)
        return {"develop": data}

    def command_config(self, **extra):
        return self.config(developer={"kind": "command", "argv": ["agent", "-p", "{prompt}"]},
                           **extra)

    def commits(self):
        return self.git("log", "--format=%H").split()


class Inputs(DevelopCase):
    def test_missing_required_input_waits(self):
        result = step_with(FakeRunner()).execute(
            inputs_for(types=("game-design", "asset-manifest")), context(self.config()))
        self.assertEqual(result.outcome, StepOutcome.WAITING_FOR_INPUT)
        self.assertIn("scaffold-record", result.message)

    def test_title_strategy_is_optional(self):
        runner = FakeRunner(on_develop=write_game)
        result = step_with(runner).execute(
            inputs_for(types=("game-design", "asset-manifest", "scaffold-record")),
            context(self.command_config()))
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
        report = result.artifacts[0].content
        self.assertEqual([e["criterion_id"] for e in report["kill_criteria_eval"]],
                         ["playable_build"])

    def test_an_unreadable_major_version_is_refused(self):
        design = fixture("game-design")
        design["provenance"]["schema_version"] = "2.0.0"
        result = step_with(FakeRunner()).execute(
            inputs_for(overrides={"game-design": design}), context(self.config()))
        self.assertEqual((result.outcome, result.retryable), (StepOutcome.FAILED, False))

    def test_no_checkout_blocks(self):
        shutil.rmtree(self.repo)
        result = step_with(FakeRunner()).execute(inputs_for(), context(self.config()))
        self.assertEqual(result.outcome, StepOutcome.BLOCKED)
        self.assertIn("not checked out", result.message)

    def test_an_engine_the_template_does_not_carry_is_refused(self):
        path = os.path.join(self.repo, "game.config.yaml")
        with open(path, "w") as handle:
            handle.write("engine:\n  type: phaser\n")
        result = step_with(FakeRunner()).execute(inputs_for(), context(self.config()))
        self.assertEqual((result.outcome, result.retryable), (StepOutcome.FAILED, False))
        self.assertIn("pixijs", result.error)

    def test_bad_settings_are_not_retried(self):
        result = step_with(FakeRunner()).execute(
            inputs_for(), context(self.config(developer={"kind": "command", "argv": []})))
        self.assertEqual((result.outcome, result.retryable), (StepOutcome.FAILED, False))


class Handoff(DevelopCase):
    def test_writes_the_brief_and_waits_for_a_person(self):
        runner = FakeRunner()
        result = step_with(runner).execute(inputs_for(), context(self.config()))
        self.assertEqual(result.outcome, StepOutcome.WAITING_FOR_HUMAN)
        brief_md = os.path.join(self.repo, briefs.BRIEF_DIR, "brief.md")
        self.assertIn(brief_md, result.message)
        with open(brief_md, encoding="utf-8") as handle:
            text = handle.read()
        for needle in ("Engine: `pixijs`", "Lane switching on beat", "interface GameIntegration",
                       "Rewarded continue", "`packages`", "tutorial", "Out of scope",
                       "Audio-to-input latency"):
            self.assertIn(needle, text)
        with open(os.path.join(self.repo, briefs.BRIEF_DIR, "brief.json")) as handle:
            brief = json.load(handle)
        self.assertEqual(brief["baseline_commit"], self.baseline)
        self.assertEqual(runner.calls, [])  # nothing ran, nothing committed
        self.assertEqual(len(self.commits()), 1)

    def test_resumed_with_done_checks_and_commits(self):
        step_with(FakeRunner()).execute(inputs_for(), context(self.config()))
        write_game(self.repo)
        runner = FakeRunner()
        result = step_with(runner).execute(
            inputs_for(), context(self.config(), decision={"decision": "done"}))
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.message)
        self.assertEqual([c[:3] for c in runner.calls], [
            ["pnpm", "install", "--frozen-lockfile"], ["pnpm", "run", "typecheck"],
            ["pnpm", "run", "lint"], ["pnpm", "run", "test"], ["pnpm", "run", "build"],
            ["pnpm", "run", "test:e2e"]])
        head = self.git("log", "-1", "--format=%B")
        self.assertIn(f"{KEY_TRAILER}: run-1:develop:1", head)
        self.assertEqual(self.git("status", "--porcelain"), "")
        report = result.artifacts[0].content
        self.assertEqual(report["build_ref"]["commit_sha"], self.commits()[0])
        self.assertEqual(report["recommendation"]["decision"], "iterate")

    def test_failed_checks_wait_again_with_the_failures(self):
        step_with(FakeRunner()).execute(inputs_for(), context(self.config()))
        write_game(self.repo)
        result = step_with(FakeRunner(fail={"lint"})).execute(
            inputs_for(), context(self.config(), decision={"decision": "done"}))
        self.assertEqual(result.outcome, StepOutcome.WAITING_FOR_HUMAN)
        self.assertIn("lint", result.message)
        self.assertEqual(len(result.artifacts), 1)  # the failing report is evidence
        self.assertEqual(len(self.commits()), 1)   # nothing committed

        # The next brief carries the failure, so the fix does not start from nothing.
        step_with(FakeRunner()).execute(
            inputs_for(), context(self.config(), decision={"decision": "done"}))
        with open(os.path.join(self.repo, briefs.BRIEF_DIR, "brief.md")) as handle:
            self.assertIn("checks that failed on the previous attempt", handle.read())

    def test_a_declined_handoff_fails_without_retry(self):
        result = step_with(FakeRunner()).execute(
            inputs_for(), context(self.config(), decision={"decision": "abandon",
                                                           "note": "not fun"}))
        self.assertEqual((result.outcome, result.retryable), (StepOutcome.FAILED, False))
        self.assertIn("not fun", result.error)


class Command(DevelopCase):
    def test_runs_the_configured_developer_in_the_checkout(self):
        seen = []
        runner = FakeRunner(on_develop=lambda cwd: (seen.append(cwd), write_game(cwd)))
        result = step_with(runner).execute(inputs_for(), context(self.command_config()))
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
        self.assertEqual(seen, [self.repo])
        argv = runner.developer_calls()[0]
        self.assertEqual(argv[:2], ["agent", "-p"])
        self.assertIn(os.path.join(self.repo, briefs.BRIEF_DIR, "brief.md"), argv[2])

    def test_a_failing_developer_is_retryable(self):
        runner = FakeRunner(develop_exit=2)
        result = step_with(runner).execute(inputs_for(), context(self.command_config()))
        self.assertEqual((result.outcome, result.retryable), (StepOutcome.FAILED, True))
        self.assertEqual([c for c in runner.calls if c[0] == "pnpm"], [])

    def test_failing_checks_are_retryable_and_emit_the_report(self):
        runner = FakeRunner(fail={"test"}, on_develop=write_game)
        result = step_with(runner).execute(inputs_for(), context(self.command_config()))
        self.assertEqual((result.outcome, result.retryable), (StepOutcome.FAILED, True))
        report = result.artifacts[0].content
        self.assertTrue(report["kill_criteria_eval"][0]["breached"])
        self.assertEqual(report["proved"][-1]["verdict"], "disproved")
        self.assertIn("unit", report["recommendation"]["if_iterate_what_changes"])

    def test_install_failure_stops_the_toolchain(self):
        runner = FakeRunner(fail={"install"}, on_develop=write_game)
        step_with(runner).execute(inputs_for(), context(self.command_config()))
        self.assertEqual([c for c in runner.calls if c[0] == "pnpm"],
                         [["pnpm", "install", "--frozen-lockfile", "--prefer-offline"]])

    def test_no_browser_skips_the_smoke_suite_and_says_so(self):
        runner = FakeRunner(unavailable={"test:e2e"}, on_develop=write_game)
        result = step_with(runner).execute(inputs_for(), context(self.command_config()))
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
        report = result.artifacts[0].content
        self.assertEqual(report["proved"][-1]["verdict"], "inconclusive")
        self.assertIn("smoke skipped", report["playtest_sessions"][0]["notes"])


class Idempotency(DevelopCase):
    def test_the_same_visit_commits_once_and_develops_once(self):
        first = FakeRunner(on_develop=write_game)
        a = step_with(first).execute(inputs_for(), context(self.command_config()))
        second = FakeRunner(on_develop=write_game)
        b = step_with(second).execute(inputs_for(), context(self.command_config()))
        self.assertEqual((a.outcome, b.outcome), (StepOutcome.SUCCESS, StepOutcome.SUCCESS))
        self.assertEqual(len(first.developer_calls()), 1)
        self.assertEqual(second.developer_calls(), [])  # found the keyed commit instead
        self.assertEqual(len(self.commits()), 2)
        self.assertEqual(a.artifacts[0].content["build_ref"]["commit_sha"],
                         b.artifacts[0].content["build_ref"]["commit_sha"])
        self.assertEqual(self.git("status", "--porcelain"), "")

    def test_a_new_visit_is_a_new_commit(self):
        step_with(FakeRunner(on_develop=write_game)).execute(
            inputs_for(), context(self.command_config()))
        qa = fixture("qa-report")
        qa["verdict"] = "fail"
        qa["blocking_defects"] = [{"id": "d-1", "severity": "blocker",
                                   "summary": "Restart leaves the old run's gates on screen"}]
        qa["provenance"]["content_hash"] = content_hash(qa)
        runner = FakeRunner(on_develop=lambda cwd: write_game(cwd, {"src/game/fix.ts": "//\n"}))
        result = step_with(runner).execute(
            inputs_for(types=("game-design", "asset-manifest", "scaffold-record",
                              "title-strategy", "qa-report"), overrides={"qa-report": qa}),
            context(self.command_config(), key="run-1:develop:2", visit=2))
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
        self.assertEqual(len(self.commits()), 3)
        self.assertEqual(result.artifacts[0].content["iteration"], 2)
        with open(os.path.join(self.repo, briefs.BRIEF_DIR, "brief.md")) as handle:
            self.assertIn("Restart leaves the old run's gates on screen", handle.read())


class Conformance(DevelopCase):
    def violations(self, extra):
        step_with(FakeRunner()).execute(inputs_for(), context(self.config()))
        write_game(self.repo, extra)
        with open(os.path.join(self.repo, briefs.BRIEF_DIR, "brief.json")) as handle:
            brief = json.load(handle)
        return conformance(self.repo, brief, GitRepo(self.repo, Runner())).findings

    def test_a_conformant_game_passes(self):
        # create-renderer.ts naming both frameworks and i18n.ts naming portals are the
        # template's own, and must not count.
        self.assertEqual(self.violations({}), [])

    def test_template_and_brief_violations_are_found(self):
        report = json.loads(json.dumps(dev_report({"engine": "pixijs", "mvp": [],
                                                   "placements": []})))
        report["systems"]["tutorial"] = "partial"
        found = "\n".join(self.violations({
            "src/game/rules.ts": 'import { Sprite } from "pixi.js";\n',
            "src/game/three.ts": 'import * as THREE from "three";\n',
            "src/game/ads.ts": "window.YaGames.init(); platform.showInterstitial();\n",
            "src/game/integration.ts": "export {};\n",
            "packages/game-core/src/index.ts": "export const hacked = 1;\n",
            "package.json": json.dumps({"dependencies": {"phaser": "^3"}}),
            briefs.REPORT_PATH: json.dumps(report),
        }))
        for needle in ("src/game/rules.ts imports pixi.js outside src/rendering/pixijs/",
                       "src/game/three.ts imports three: engine is pixijs",
                       "src/game/ads.ts references a portal SDK",
                       "src/game/ads.ts calls the platform's ad API directly",
                       "does not declare GameIntegration",
                       "packages/game-core/src/index.ts is template-owned",
                       "package.json adds phaser",
                       "required system 'tutorial' is partial",
                       "MVP item not reported: 'Rewarded continue'",
                       "no rewarded placement reported"):
            self.assertIn(needle, found)

    def test_the_scaffold_scene_and_a_missing_report_are_found(self):
        found = "\n".join(self.violations({
            "src/main.ts": 'import { BootScene } from "./game/boot-scene.js";\n',
            briefs.REPORT_PATH: None,
        }))
        self.assertIn("still starts the template's BootScene", found)
        self.assertIn("report.json was not written", found)


class Settings_(unittest.TestCase):
    def test_defaults_and_ordering(self):
        settings = Settings.resolve({"develop": {"checks": ["smoke", "build", "lint"]}})
        # conformance is always on, and the list runs in dependency order.
        self.assertEqual(settings.checks, ["conformance", "lint", "build", "smoke"])
        self.assertEqual(settings.developer["kind"], "handoff")

    def test_unknown_check_and_kind_are_refused(self):
        with self.assertRaises(SettingsError):
            Settings.resolve({"develop": {"checks": ["deploy"]}})
        with self.assertRaises(SettingsError):
            Settings.resolve({"develop": {"developer": {"kind": "magic"}}})

    def test_relative_checkouts_resolve_against_the_factory_root(self):
        settings = Settings.resolve({"develop": {"checkouts": "../games"}})
        self.assertEqual(settings.checkout_for("x"),
                         os.path.normpath(os.path.join(ROOT, "..", "games", "x")))


@unittest.skipUnless(HAS_GIT, "git is not installed")
class ThroughTheEngine(unittest.TestCase):
    """§11.2: the module registered alongside the mocks, run by the real engine."""

    def setUp(self):
        self.scratch = tempfile.mkdtemp(prefix="wgf-develop-engine-")
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)
        repo = os.path.join(self.scratch, "checkouts", TITLE)
        os.makedirs(repo)
        for relative, text in SCAFFOLD_FILES.items():
            path = os.path.join(repo, relative)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(text)
        for args in (["init", "-q", "-b", "main"], ["add", "-A"],
                     [*IDENTITY, "commit", "-q", "-m", "scaffold"]):
            subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)

    def api(self):
        runner = FakeRunner(on_develop=write_game)

        class Step(DevelopStep):
            runner_factory = staticmethod(lambda: runner)

        class API(WorkflowAPI):
            def registry(self, use_mock):
                registry = StepRegistry()
                register_checkpoint(registry)
                mock.register(registry)
                registry.register("develop", Step)  # later wins over the mock
                return registry

        config = FactoryConfig({
            "storage": {"fsync": False}, "checkpoints": {"auto_approve": ["G2"]},
            "develop": {"checkouts": os.path.join(self.scratch, "checkouts"),
                        "author": AUTHOR,
                        "developer": {"kind": "command", "argv": ["agent", "{brief}"]}},
        })
        return API(config=config, store_dir=os.path.join(self.scratch, "store")), runner

    def test_the_new_game_workflow_completes_with_the_real_develop_step(self):
        api, runner = self.api()
        state = api.run(RunRequest(project_id=TITLE))
        self.assertEqual(state.status, RunStatus.COMPLETED, state.message)
        ref = state.latest_artifact("prototype-report")
        report = api.store.read_artifact(state.run_id, ref)
        self.assertEqual(ArtifactContracts()("prototype-report", report), [])
        self.assertEqual(report["provenance"]["produced_by"]["role"], "gameplay")
        pinned = {pin["artifact_type"] for pin in report["provenance"]["inputs"]}
        self.assertTrue({"game-design", "asset-manifest", "scaffold-record",
                         "title-strategy"} <= pinned)
        self.assertEqual(sorted(state.steps["develop"].consumed),
                         ["asset-manifest@v1", "game-design@v1", "scaffold-record@v1",
                          "title-strategy@v1"])
        self.assertEqual(len(runner.developer_calls()), 1)

    def test_the_module_registers_by_config(self):
        registry = StepRegistry().load_modules(["wgf_develop"])
        self.assertIs(registry.resolve("develop"), DevelopStep)

    def test_the_workflow_feeds_develop_what_it_reads(self):
        definition = load_definition("new-game")
        step = next(s for s in definition.steps if s.id == "develop")
        self.assertEqual(set(step.inputs), {"game-design", "asset-manifest", "scaffold-record",
                                            "title-strategy", "qa-report"})
        self.assertEqual(list(step.outputs), ["prototype-report"])


@unittest.skipUnless(os.environ.get("WGF_AJV") and shutil.which("npx"),
                     "set WGF_AJV=1 to validate with ajv (needs npx; may download ajv-cli)")
class Schema(DevelopCase):
    """§11.3: an emitted prototype-report against the full JSON Schema."""

    def test_the_report_validates_with_ajv(self):
        result = step_with(FakeRunner(on_develop=write_game)).execute(
            inputs_for(), context(self.command_config()))
        path = os.path.join(self.scratch, "prototype-report.json")
        with open(path, "w") as handle:
            json.dump(result.artifacts[0].content, handle)
        completed = subprocess.run(
            ["npx", "--yes", "-p", "ajv-cli@5", "-p", "ajv-formats@2", "ajv", "validate",
             "-s", "core/artifacts/prototype-report.schema.json",
             "-r", "core/artifacts/shared/*.schema.json", "-c", "ajv-formats",
             "--spec=draft2020", "--strict=false", "-d", path],
            cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)


if __name__ == "__main__":
    unittest.main()

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
from wgf_develop import seam  # noqa: E402
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
                "tech-plan", "qa-report")
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


# src/main.ts booting through the Factory's seam (wgflib.gameseam), as the brief asks.
SEAM_MAIN = (
    'import { createGameIntegration, createGamePlatform } from "./platform/integration.js";\n'
    'import { PulseLanes } from "./game/app.js";\n'
    "const platform = await createGamePlatform();\n"
    "const integration = createGameIntegration(game, platform, { audio });\n")


def write_game(root, extra=None):
    """What a developer produces: the scaffold replaced, main.ts on the seam the develop step
    provided (src/game/integration.ts, src/platform/integration.ts - not the developer's to
    write), a view, the report."""
    with open(os.path.join(root, briefs.BRIEF_DIR, "brief.json"), encoding="utf-8") as handle:
        brief = json.load(handle)
    files = {
        "src/main.ts": SEAM_MAIN,
        "src/game/app.ts": 'import type { Game } from "@wgf/game-core";\nexport {};\n',
        "src/rendering/pixijs/view.ts": 'import { Graphics } from "pixi.js";\nexport {};\n',
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


# A build_spec with an entry of every tier, nested tiers, and the two sections the brief
# leaves out, so what the brief carries and what it drops are both visible.
BUILD_SPEC = {
    "mechanics": [
        {"id": "lane-switch", "name": "Lane switching", "tier": "mvp",
         "description": "Move one lane per input.",
         "rules": ["Three lanes; the player starts in the middle one."],
         "parameters": {"lanes": 3, "move_ms": 120}},
        {"id": "dash", "name": "Dash", "tier": "post-mvp", "description": "Later.",
         "rules": ["Not now."]},
    ],
    "menus": [{"id": "title-menu", "tier": "mvp", "screen": "title", "items": [
        {"label": "Play", "action": "Enter play"},
        {"label": "Settings", "action": "Open settings", "tier": "post-mvp"}]}],
    "rewards": [{"id": "new-best", "tier": "mvp", "trigger": "Run ends above the best",
                 "grants": "New best", "feedback": "Best counter bursts; a short fanfare."}],
    "failure": {"condition": "Touch an obstacle.",
                "feedback": "Hit-stop for 150 ms, screen shake.",
                "retry": {"path": "Retry on the result card.", "time_to_retry_s": 1}},
    "difficulty": {"model": "time-ramp", "curve": [
        {"at": "0-20s", "description": "Forgiving opening.", "parameters": {"speed": 6.0}}]},
    "sdk_touchpoints": [{"id": "sdk-init", "capability": "init", "tier": "mvp",
                         "when": "At boot"}],
    "assets": [{"id": "player", "type": "sprite", "tier": "mvp", "description": "Player"}],
}

DEV_PLAN = {
    "est_days": 4,
    "milestones": [
        {"id": "M1", "label": "Playable core loop", "phase": "prototype", "est_days": 3,
         "exit_criteria": ["A stranger plays a full session"]},
        {"id": "M3", "label": "Platform hardening", "phase": "hardening", "est_days": 1,
         "exit_criteria": ["Verify suite green"]},
    ],
    "tasks": [
        {"id": "FEAT-002", "title": "Near-miss multiplier", "milestone": "M1",
         "dependencies": ["FEAT-001"], "acceptance_criteria": ["Multiplier rises on a near miss"],
         "tests": ["tests/unit/multiplier.test.ts"]},
        {"id": "FEAT-001", "title": "Lane switching", "milestone": "M1",
         "dependencies": ["CORE-001"], "acceptance_criteria": ["One input moves one lane"]},
        {"id": "CORE-001", "title": "Boot on the template", "milestone": "M1",
         "acceptance_criteria": ["The game boots through the seam"]},
        {"id": "PLAT-001", "title": "Yandex", "milestone": "M3",
         "acceptance_criteria": ["Profile assertions hold"]},
    ],
}


def with_build_spec_and_plan():
    design = fixture("game-design")
    design["build_spec"] = BUILD_SPEC
    design["provenance"]["content_hash"] = content_hash(design)
    plan = fixture("tech-plan")
    plan["dev_plan"] = DEV_PLAN
    plan["provenance"]["content_hash"] = content_hash(plan)
    return inputs_for(types=("game-design", "asset-manifest", "scaffold-record",
                             "title-strategy", "tech-plan"),
                      overrides={"game-design": design, "tech-plan": plan})


class DesignAndPlanInTheBrief(DevelopCase):
    """F1: the design's build_spec and the approved plan's tasks reach the developer."""

    def brief(self, inputs):
        result = step_with(FakeRunner()).execute(inputs, context(self.config()))
        self.assertEqual(result.outcome, StepOutcome.WAITING_FOR_HUMAN, result.error)
        with open(os.path.join(self.repo, briefs.BRIEF_DIR, "brief.json")) as handle:
            data = json.load(handle)
        with open(os.path.join(self.repo, briefs.BRIEF_DIR, "brief.md")) as handle:
            return data, handle.read()

    def test_the_mvp_build_spec_is_carried_whole(self):
        data, text = self.brief(with_build_spec_and_plan())
        sections = data["build_spec"]["sections"]
        self.assertEqual([m["id"] for m in sections["mechanics"]], ["lane-switch"])
        self.assertEqual(sections["mechanics"][0]["parameters"], {"lanes": 3, "move_ms": 120})
        self.assertEqual([i["label"] for i in sections["menus"][0]["items"]], ["Play"])
        self.assertEqual(sections["failure"], BUILD_SPEC["failure"])
        self.assertEqual(sections["difficulty"], BUILD_SPEC["difficulty"])
        self.assertNotIn("sdk_touchpoints", sections)
        self.assertNotIn("assets", sections)
        self.assertEqual(sorted(data["build_spec"]["omitted"]), ["assets", "sdk_touchpoints"])
        self.assertIn("mechanics/dash (post-mvp)", data["build_spec"]["not_now"])
        self.assertIn("menus/title-menu/items/Settings (post-mvp)",
                      data["build_spec"]["not_now"])
        for needle in ("## Build spec (MVP tier)", "Three lanes; the player starts in the middle",
                       "move_ms: 120", "Best counter bursts; a short fanfare.",
                       "Hit-stop for 150 ms, screen shake.", "time_to_retry_s: 1",
                       "speed: 6.0", "one tuning module"):
            self.assertIn(needle, text)
        self.assertNotIn("Not now.", text)          # the post-mvp mechanic's rules
        self.assertNotIn("At boot", text)           # sdk_touchpoints stay with the sdk step

    def test_the_prototype_tasks_are_carried_in_dependency_order(self):
        data, text = self.brief(with_build_spec_and_plan())
        plan = data["dev_plan"]
        self.assertEqual([t["id"] for t in plan["tasks"]], ["CORE-001", "FEAT-001", "FEAT-002"])
        self.assertEqual([m["id"] for m in plan["milestones"]], ["M1"])
        self.assertEqual(plan["later"], ["PLAT-001"])
        self.assertEqual(plan["tasks"][2]["acceptance_criteria"],
                         ["Multiplier rises on a near miss"])
        self.assertIn("## Development plan (approved at G3)", text)
        self.assertLess(text.index("### CORE-001"), text.index("### FEAT-001"))
        self.assertLess(text.index("### FEAT-001"), text.index("### FEAT-002"))
        for needle in ("Multiplier rises on a near miss", "`tests/unit/multiplier.test.ts`",
                       "A stranger plays a full session", "Tasks of later milestones (not this build): "
                       "`PLAT-001`"):
            self.assertIn(needle, text)
        self.assertNotIn("Profile assertions hold", text)

    def test_the_tech_plan_is_pinned_like_every_input(self):
        inputs = with_build_spec_and_plan()
        data, text = self.brief(inputs)
        pins = {p["artifact_type"]: p["content_hash"] for p in data["inputs"]}
        self.assertEqual(pins["tech-plan"], inputs.refs["tech-plan"].content_hash)
        self.assertIn("- Input: `tech-plan`", text)

    def test_without_either_the_brief_is_unchanged(self):
        data, text = self.brief(inputs_for())
        self.assertIsNone(data["build_spec"])   # the fixture design predates build_spec
        self.assertIsNone(data["dev_plan"])     # and the run holds no tech plan
        self.assertNotIn("## Build spec", text)
        self.assertNotIn("## Development plan", text)

    def test_an_unreadable_tech_plan_major_is_refused(self):
        plan = fixture("tech-plan")
        plan["provenance"]["schema_version"] = "2.0.0"
        result = step_with(FakeRunner()).execute(
            inputs_for(types=("game-design", "asset-manifest", "scaffold-record", "tech-plan"),
                       overrides={"tech-plan": plan}), context(self.config()))
        self.assertEqual((result.outcome, result.retryable), (StepOutcome.FAILED, False))
        self.assertIn("tech-plan", result.error)

    def test_a_cycle_keeps_the_plan_order(self):
        plan = {"dev_plan": {"milestones": [{"id": "M1", "phase": "prototype"}], "tasks": [
            {"id": "A-1", "milestone": "M1", "dependencies": ["B-1"],
             "acceptance_criteria": ["a"]},
            {"id": "B-1", "milestone": "M1", "dependencies": ["A-1"],
             "acceptance_criteria": ["b"]}]}}
        self.assertEqual([t["id"] for t in briefs.select_dev_plan(plan)["tasks"]],
                         ["A-1", "B-1"])


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

    def test_the_brief_names_what_verification_will_require(self):
        # Each acceptance run's first verification failed "no repository-playwright evidence
        # exercises progression / game-over / pause-resume": the brief never said how
        # verification recognises evidence, so every run paid a verify -> develop loop.
        from wgf_verification.checks.gameplay import required_aspects
        from wgf_verification.session import VerificationSession
        step_with(FakeRunner()).execute(inputs_for(), context(self.config()))
        with open(os.path.join(self.repo, briefs.BRIEF_DIR, "brief.json")) as handle:
            brief = json.load(handle)
        with open(os.path.join(self.repo, briefs.BRIEF_DIR, "brief.md")) as handle:
            text = handle.read()
        session = VerificationSession(self.repo, None)
        session.inputs = {"game-design": inputs_for().load("game-design")}
        wanted = required_aspects(session)
        self.assertEqual(set(brief["verification_aspects"]["required"]), wanted)
        self.assertTrue({"game-over", "restart", "pause-resume"} <= wanted)
        self.assertIn("**Verification evidence.**", text)
        for aspect in wanted:
            self.assertIn(f"`@{aspect}`", text)

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

    def test_the_retry_after_a_failed_developer_is_told_to_continue(self):
        # The real acceptance run: the developer hit its turn limit half-way, and the retry,
        # a new session whose brief mentioned no failure, took the tree for finished.
        runner = FakeRunner(fail={"lint"}, on_develop=write_game)
        step_with(runner).execute(inputs_for(), context(self.command_config()))  # attempt 1
        failing = FakeRunner(develop_exit=1)
        failed = step_with(failing).execute(inputs_for(), context(self.command_config(),
                                                                  attempt=2))
        self.assertEqual((failed.outcome, failed.retryable), (StepOutcome.FAILED, True))
        seen = {}

        def develop(cwd):
            with open(os.path.join(cwd, briefs.BRIEF_DIR, "brief.md"), encoding="utf-8") as h:
                seen["brief"] = h.read()
            write_game(cwd)

        step_with(FakeRunner(on_develop=develop)).execute(
            inputs_for(), context(self.command_config(), attempt=3))
        brief = seen["brief"]
        self.assertIn("## Fix first: checks that failed on the previous attempt", brief)
        self.assertIn("### developer", brief)
        self.assertIn("ended before it finished (developer command exited 1)", brief)
        self.assertIn("continue from it rather than starting over", brief)
        self.assertIn("### lint", brief)  # attempt 1's failed check is not forgotten

    def test_the_smoke_check_cannot_reach_a_portal(self):
        # The real acceptance run: a Poki build's smoke loaded Poki's real SDK from its CDN,
        # which pulled an http:// ad bridge, and the template's "makes no insecure requests"
        # failed on the portal, not the game. The browser check now runs behind a refusing
        # proxy; other checks do not.
        import urllib.error
        import urllib.request
        seen = {}

        class Portal(FakeRunner):
            def run(self, argv, cwd, timeout=None, env=None):
                if argv[:3] == ["pnpm", "run", "test:e2e"]:
                    seen["env"] = dict(env or {})
                    proxy = (env or {}).get("http_proxy")
                    opener = urllib.request.build_opener(urllib.request.ProxyHandler(
                        {"http": proxy} if proxy else {}))
                    try:
                        opener.open("http://imasdk.googleapis.com/js/core/bridge.html",
                                    timeout=5)
                        seen["portal"] = "reached"
                    except urllib.error.HTTPError as exc:
                        seen["portal"] = exc.code
                    except OSError as exc:
                        seen["portal"] = str(exc)
                elif argv[:3] == ["pnpm", "run", "test"]:
                    seen["unit_env"] = dict(env or {})
                return super().run(argv, cwd, timeout, env)

        runner = Portal(on_develop=write_game)
        result = step_with(runner).execute(inputs_for(), context(self.command_config()))
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
        self.assertEqual(seen["portal"], 403)
        self.assertEqual(seen["env"]["no_proxy"], "localhost,127.0.0.1,::1")
        self.assertNotIn("http_proxy", seen["unit_env"])
        with open(os.path.join(self.repo, briefs.BRIEF_DIR, "checks.json")) as handle:
            smoke = next(c for c in json.load(handle)["checks"] if c["id"] == "smoke")
        self.assertIn("network guarded: 1 request(s) refused", smoke["summary"])
        self.assertIn("GET http://imasdk.googleapis.com", smoke["summary"])

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
            "src/game/boot.ts": 'const p = createPlatform("yandex", { namespace: "x" });\n',
            "packages/game-core/src/index.ts": "export const hacked = 1;\n",
            "package.json": json.dumps({"dependencies": {"phaser": "^3"}}),
            briefs.REPORT_PATH: json.dumps(report),
        }))
        for needle in ("src/game/rules.ts imports pixi.js outside src/rendering/pixijs/",
                       "src/game/three.ts imports three: engine is pixijs",
                       "src/game/ads.ts references a portal SDK",
                       "src/game/ads.ts calls the platform's ad API directly",
                       "src/game/integration.ts belongs to the Factory and was edited",
                       "src/game/boot.ts calls createPlatform directly",
                       "packages/game-core/src/index.ts is template-owned",
                       "package.json adds phaser",
                       "required system 'tutorial' is partial",
                       "MVP item not reported: 'Rewarded continue'",
                       "no rewarded placement reported"):
            self.assertIn(needle, found)

    def test_the_seam_is_provided_before_the_developer_runs(self):
        seen = {}

        def develop(cwd):
            for relative in seam.SEAM_FILES:
                with open(os.path.join(cwd, relative), encoding="utf-8") as handle:
                    seen[relative] = handle.read()

        step_with(FakeRunner(on_develop=develop)).execute(
            inputs_for(), context(self.config(developer={"kind": "command",
                                                         "argv": ["dev", "{brief}"]})))
        self.assertEqual(seen, seam.default_files())
        self.assertIn("createGamePlatform", seen["src/platform/integration.ts"])
        self.assertIn("interface GameIntegration", seen["src/game/integration.ts"])

    def test_a_main_that_does_not_boot_through_the_seam_is_found(self):
        found = "\n".join(self.violations({
            "src/main.ts": 'import { createPlatform } from "@wgf/platform-sdk";\n'
                           'const platform = createPlatform("yandex", { namespace: "x" });\n',
        }))
        self.assertIn('does not import createGamePlatform from "./platform/integration.js"',
                      found)
        self.assertIn("src/main.ts calls createPlatform directly", found)

    def test_an_edited_seam_wiring_is_found(self):
        found = "\n".join(self.violations({
            "src/platform/integration.ts": "export const createGamePlatform = 1;\n",
        }))
        self.assertIn("src/platform/integration.ts belongs to the Factory and was edited", found)

    def test_the_sdk_wiring_committed_earlier_is_the_baseline(self):
        # After the sdk step, the wiring is its integrated version; a later develop visit
        # must keep that, not the default and not an edit.
        step_with(FakeRunner()).execute(inputs_for(), context(self.config()))
        write_game(self.repo)
        wiring = os.path.join(self.repo, "src/platform/integration.ts")
        with open(wiring, "w") as handle:
            handle.write("// integrated by the sdk step\n")
        subprocess.run(["git", *IDENTITY, "-C", self.repo, "add", "-A"], check=True)
        subprocess.run(["git", *IDENTITY, "-C", self.repo, "commit", "-qm", "sdk"], check=True)
        head = subprocess.run(["git", "-C", self.repo, "rev-parse", "HEAD"], check=True,
                              capture_output=True, text=True).stdout.strip()
        with open(os.path.join(self.repo, briefs.BRIEF_DIR, "brief.json")) as handle:
            brief = json.load(handle)
        brief["baseline_commit"] = head
        git_repo = GitRepo(self.repo, Runner())
        self.assertEqual(seam.seam_findings(self.repo, git_repo, head), [])
        self.assertEqual(seam.ensure_seam(self.repo), [])  # left alone, not reset to default
        with open(wiring, "w") as handle:
            handle.write("// edited by the developer\n")
        self.assertIn("src/platform/integration.ts belongs to the Factory and was edited",
                      "\n".join(seam.seam_findings(self.repo, git_repo, head)))

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
            "storage": {"fsync": False}, "checkpoints": {"auto_approve": ["G2", "G3"]},
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
                         "title-strategy", "tech-plan"} <= pinned)
        # The approved tech plan is consumed (F1: its prototype tasks join the brief).
        self.assertEqual(sorted(state.steps["develop"].consumed),
                         ["asset-manifest@v1", "game-design@v1", "scaffold-record@v1",
                          "tech-plan@v1", "title-strategy@v1"])
        self.assertEqual(len(runner.developer_calls()), 1)

    def test_the_module_registers_by_config(self):
        registry = StepRegistry().load_modules(["wgf_develop"])
        self.assertIs(registry.resolve("develop"), DevelopStep)

    def test_the_workflow_feeds_develop_what_it_reads(self):
        definition = load_definition("new-game")
        step = next(s for s in definition.steps if s.id == "develop")
        self.assertEqual(set(step.inputs), {"game-design", "asset-manifest", "scaffold-record",
                                            "title-strategy", "tech-plan", "qa-report",
                                            "review-report"})
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


class NoPlaceholderCommit(DevelopCase):
    def test_a_build_commit_that_cannot_be_established_blocks(self):
        # Formerly the report named "0" * 40, which review, sdk, verify and release would
        # all have pinned as if it were a build.
        shutil.rmtree(os.path.join(self.repo, ".git"))
        self.git("init", "-q", "-b", "main")  # a repository with no commit: HEAD is unreadable
        result = step_with(FakeRunner(on_develop=write_game)).execute(
            inputs_for(), context(self.command_config(commit=False)))
        self.assertEqual(result.outcome, StepOutcome.BLOCKED, result.error)
        self.assertEqual(result.artifacts, [])
        self.assertIn("cannot be established", result.message)


if __name__ == "__main__":
    unittest.main()

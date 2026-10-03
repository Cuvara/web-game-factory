"""wgflib.permpath: a write-scoping permission rule names the author's path on every host OS.

Finding F11: on Windows the autonomous profile's `Edit(/{draft})`, `Edit(/{out}/**)` and
`Edit(/{dir}/**)` rendered as `Edit(/C:\\Users\\...)`, which the host reads as a path
relative to the project; in don't-ask mode every write the design, 2D and 3D authors made
was denied. The rule placeholders render `//` and the POSIX form instead.

    python -m unittest scripts.tests.test_permpath
"""

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
sys.path.insert(0, SCRIPTS)

from wgflib import permpath  # noqa: E402
from wgflib.yamllite import load  # noqa: E402

PROFILE = os.path.join(ROOT, "workspace", "config", "profiles", "autonomous.yaml")
WIN_DRAFT = r"C:\Users\me\proj\.factory\workflows\run\design\1-1.draft.json"


class RulePath(unittest.TestCase):

    def test_windows_drive_path_is_posix_with_a_lowercase_drive(self):
        self.assertEqual(permpath.rule_path(WIN_DRAFT, windows=True),
                         "//c/Users/me/proj/.factory/workflows/run/design/1-1.draft.json")
        self.assertEqual(permpath.rule_path("D:/x/y", windows=True), "//d/x/y")

    def test_posix_absolute_path_gets_the_second_slash(self):
        self.assertEqual(permpath.rule_path("/home/me/out", windows=False), "//home/me/out")

    def test_unc_path_keeps_its_host(self):
        self.assertEqual(permpath.rule_path(r"\\srv\share\out", windows=True), "//srv/share/out")


class FormatArgv(unittest.TestCase):

    def test_rule_placeholder(self):
        argv = permpath.format_argv(["x", "Read,Edit({draft_rule})", "{draft}"],
                                    {"draft": WIN_DRAFT}, ("draft",), windows=True)
        self.assertEqual(argv[1], "Read,Edit(//c/Users/me/proj/.factory/workflows/run/design/"
                                  "1-1.draft.json)")
        self.assertEqual(argv[2], WIN_DRAFT)  # the plain placeholder is still the native path

    def test_legacy_single_slash_form_is_read_as_the_rule(self):
        # A project's copy of the older profile keeps working on Windows ...
        argv = permpath.format_argv(["Edit(/{out}/**)"], {"out": r"C:\w\out"}, ("out",),
                                    windows=True)
        self.assertEqual(argv, ["Edit(//c/w/out/**)"])
        # ... and renders exactly as it always did on POSIX.
        argv = permpath.format_argv(["Edit(/{out}/**)"], {"out": "/w/out"}, ("out",),
                                    windows=False)
        self.assertEqual(argv, ["Edit(//w/out/**)"])

    def test_unknown_placeholder_still_raises(self):
        with self.assertRaises(KeyError):
            permpath.format_argv(["{nope}"], {"out": "/w"}, ("out",))


class TheProfileRendersAbsoluteRules(unittest.TestCase):
    """Every write-scoping Edit rule of the shipped autonomous profile, rendered with a
    Windows path, names that path absolutely - never `/C:\\...`."""

    def test_on_windows(self):
        with open(PROFILE, encoding="utf-8") as handle:
            factory = load(handle.read())["factory"]
        cases = [(factory["design"]["agent"]["argv"], "draft"),
                 (factory["assets"]["author"]["argv"], "out"),
                 (factory["assets"]["model_author"]["argv"], "dir")]
        for argv, key in cases:
            with self.subTest(key=key):
                values = {k: "" for k in ("request", "spec", "sheet", "preview", "prompt",
                                          "out", "dir", "draft")}
                values[key] = r"C:\Users\me\run\x"
                rendered = permpath.format_argv(argv, values, (key,), windows=True)
                edits = [p for p in rendered if "Edit(" in p and "{" not in p]
                self.assertTrue(any("Edit(//c/Users/me/run/x" in p for p in edits), rendered)
                self.assertFalse(any("Edit(/C:" in p or "\\" in p for p in edits), rendered)


class TheAuthorsRenderRules(unittest.TestCase):
    """The three write-scoped authors render `{..._rule}` through permpath."""

    def test_set_author(self):
        from wgf_assets.set_author import SetAuthor
        out = os.path.abspath("out")
        command = SetAuthor._format(["Edit({out_rule}/**)", "Edit(/{out}/**)"],
                                    {"request": "", "out": out, "preview": "", "sheet": "",
                                     "prompt": ""})
        self.assertEqual(command, [f"Edit({permpath.rule_path(out)}/**)"] * 2)

    def test_model_author(self):
        from types import SimpleNamespace
        from wgf_assets.model_author import _Session
        directory = os.path.abspath("models")
        session = SimpleNamespace(directory=directory,
                                  argv=["Read,Edit({dir_rule}/**)", "Edit(/{dir}/**)"])
        command = _Session._command(session, "go", "request.json", None)
        self.assertEqual(command, [f"Read,Edit({permpath.rule_path(directory)}/**)",
                                   f"Edit({permpath.rule_path(directory)}/**)"])

    def test_design_agent_uses_permpath(self):
        for module in ("wgf_design/agent.py",):
            with open(os.path.join(SCRIPTS, module), encoding="utf-8") as handle:
                self.assertIn("permpath.format_argv(", handle.read(), module)


if __name__ == "__main__":
    unittest.main()

"""A run keeps the quality references it started under (new-game `pinned_references`).

Play realism (core/reference/play-realism.yaml), the bot's viewports and environment bars
(core/reference/visual-quality.yaml), browser QA (core/reference/browser-qa.yaml) and the
regression registry (core/reference/check-tiers.yaml, core/reference/lessons.yaml) are pinned
when a run starts, and the steps that read them - playability, verify's browser QA, triage -
read the run's copy. A resumed run on an updated Factory is therefore held to the checks and
tiers it started under; a copy edited after the start is refused; a run that pinned nothing
reads the live file. These tests hold that.

    python -m unittest scripts.tests.test_pinned_quality_references
"""

import os
import shutil
import sys
import tempfile
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
for _path in (SCRIPTS, HERE):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from wgf_playability import step as playability  # noqa: E402
from wgf_triage import step as triage  # noqa: E402
from wgf_verification import browser_qa  # noqa: E402
from wgflib import paths  # noqa: E402
from wgflib.workflow import references  # noqa: E402
from wgflib.workflow.definition import load_definition  # noqa: E402
from wgflib.yamllite import load_file  # noqa: E402

PINNED = ("core/reference/visual-quality.yaml", "core/reference/play-realism.yaml",
          "core/reference/browser-qa.yaml", "core/reference/check-tiers.yaml",
          "core/reference/lessons.yaml")


class PinnedRun(unittest.TestCase):
    """A run that started under a Factory whose references differ from today's."""

    def setUp(self):
        self.run_dir = tempfile.mkdtemp(prefix="wgf-pins-")
        self.addCleanup(shutil.rmtree, self.run_dir, ignore_errors=True)
        collected = references.collect(PINNED)
        # What the run started under: an older play-realism and browser-QA contract, a
        # different viewport set and lesson list than the live files have now.
        collected["core/reference/play-realism.yaml"] = collected[
            "core/reference/play-realism.yaml"].replace(b"version: 1.0.0", b"version: 0.9.0", 1)
        collected["core/reference/browser-qa.yaml"] = collected[
            "core/reference/browser-qa.yaml"].replace(
            b"  - id: context-menu\n    tier: quality", b"  - id: context-menu\n    tier: advisory", 1)
        collected["core/reference/visual-quality.yaml"] = collected[
            "core/reference/visual-quality.yaml"].replace(b"version: 1.3.0", b"version: 1.2.9", 1)
        collected["core/reference/lessons.yaml"] = collected[
            "core/reference/lessons.yaml"].replace(b"version: 1.0.0", b"version: 0.9.0", 1)
        self.pins = references.pin(collected, self.run_dir)
        self.context = types.SimpleNamespace(
            environment={references.PARAM: dict(self.pins)}, run_dir=self.run_dir)

    def test_the_workflow_pins_them(self):
        definition = load_definition(os.path.join(paths.ROOT, "core", "workflows",
                                                  "new-game.workflow.yaml"))
        pinned = getattr(definition, "pinned_references", None)
        if pinned is None:
            pinned = (load_file(os.path.join(paths.ROOT, "core", "workflows",
                                             "new-game.workflow.yaml"))["workflow"]
                      ["pinned_references"])
        for relpath in PINNED:
            self.assertIn(relpath, pinned)

    def test_playability_reads_the_pinned_realism_and_visual_bars(self):
        self.assertEqual(str(playability.pinned_yaml(self.context,
                                                     playability.REALISM_REF)["version"]), "0.9.0")
        self.assertEqual(str(playability.pinned_yaml(self.context,
                                                     playability.RULES_REF)["version"]), "1.2.9")

    def test_browser_qa_holds_the_checks_and_tiers_it_started_under(self):
        contract = browser_qa.load_contract(reader=browser_qa.pinned_reader(self.context))
        tiers = {c["id"]: c["tier"] for c in contract["checks"]}
        self.assertEqual(tiers["context-menu"], "advisory")
        self.assertEqual({c["id"]: c["tier"] for c in browser_qa.load_contract()["checks"]}
                         ["context-menu"], "quality")
        # The bars it reads from other files come through the same pinned reader.
        self.assertIn("environment", contract["_resolved"])
        self.assertEqual(browser_qa.environment_bars(contract),
                         load_file(os.path.join(self.run_dir, references.DIRECTORY, "core",
                                                "reference", "visual-quality.yaml"))
                         ["environment"])

    def test_triage_names_the_lessons_it_started_under(self):
        data = triage._registry(self.context)
        self.assertEqual(str(data["lessons"]["version"]), "0.9.0")

    def test_a_copy_edited_after_the_start_is_refused(self):
        path = os.path.join(self.run_dir, references.DIRECTORY, "core", "reference",
                            "play-realism.yaml")
        with open(path, "ab") as handle:
            handle.write(b"\n# lowered in the run\n")
        with self.assertRaises(references.PinError):
            playability.pinned_yaml(self.context, playability.REALISM_REF)

    def test_a_run_that_pinned_nothing_reads_the_live_files(self):
        live = types.SimpleNamespace(environment={}, run_dir=self.run_dir)
        self.assertEqual(str(playability.pinned_yaml(live, playability.REALISM_REF)["version"]),
                         str(load_file(os.path.join(paths.REFERENCE,
                                                    "play-realism.yaml"))["version"]))
        self.assertEqual({c["id"]: c["tier"] for c in browser_qa.load_contract(
            reader=browser_qa.pinned_reader(live))["checks"]}["context-menu"], "quality")


if __name__ == "__main__":
    unittest.main()

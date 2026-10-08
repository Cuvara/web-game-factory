"""K5: cross-session quality transfer - knowledge reaches a fresh session only through the Factory.

    python -m unittest scripts.tests.test_knowledge_transfer
"""

import os
import re
import sys
import unittest
from unittest import mock as patch

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
for _path in (SCRIPTS, HERE):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import test_knowledge_run as runs  # noqa: E402
from wgf_knowledge import model  # noqa: E402
from wgflib.workflow import references  # noqa: E402
from wgflib.workflow.api import RunRequest  # noqa: E402

LESSONS = "core/reference/lessons.yaml"


def moved_to_r2(text):
    """lessons.yaml with L29 revised in place to r2 - the Factory moving on after a run
    pinned r1: its lesson text sharpened, its revision raised."""
    head, sep, tail = text.partition("  - id: L29\n")
    assert sep, "L29 is not in lessons.yaml"
    entry, nxt, rest = tail.partition("\n  - id: ")
    entry, count = re.subn(r"(?m)^    revision: 1$", "    revision: 2", entry)
    assert count == 1
    entry = entry.replace("    lesson: >-\n", "    lesson: >-\n      Revised: ", 1)
    return head + sep + entry + nxt + rest


class Versioning(runs._Case):
    """A run's contract pins each rule by revision and digest: a run pinned under L29@r1 keeps
    r1 after the Factory moves to r2; a run started after the move gets r2."""

    def rule(self, api, state, rule_id="L29"):
        contract = self.contract(api, state)
        return next(r for r in contract["rules"] if r["id"] == rule_id), contract

    def test_an_old_run_keeps_r1_and_a_new_run_gets_r2(self):
        api, old = self.to_g4()
        first, contract = self.rule(api, old)
        self.assertEqual((first["revision"], first["version"]), (1, "L29@r1"))
        with open(os.path.join(ROOT, *LESSONS.split("/")), encoding="utf-8") as handle:
            shipped = handle.read()
        entry = next(l for l in model_lessons(shipped) if l["id"] == "L29")
        self.assertEqual(first["digest"], model.lesson_digest(entry))
        # every rule, applicable or not, is pinned by digest
        self.assertTrue(all(r.get("digest") for r in contract["rules"]))
        self.assertTrue(all(r.get("digest") for r in contract["not_applicable"]))
        self.assertEqual(contract["trace"], {"present": False, "applied": [],
                                             "contradicted": []})

        real = references.collect

        def collect(relpaths, root=None):
            found = real(relpaths, root)
            if LESSONS in found:
                found[LESSONS] = moved_to_r2(found[LESSONS].decode("utf-8")).encode("utf-8")
            return found

        with patch.patch.object(references, "collect", collect):
            _, new = self.to_g4(api)
            second, _ = self.rule(api, new)
            self.assertEqual((second["revision"], second["version"]), (2, "L29@r2"))
            self.assertNotEqual(second["digest"], first["digest"])
            self.assertTrue(second["lesson"].startswith("Revised:"))
            # The old run's contract made again after the move: still the r1 it pinned.
            again = api.run(RunRequest(resume=old.run_id, from_step=runs.STEP,
                                       decided_by="human"))
            self.assertGreater(self.executed(again).count(runs.STEP),
                               self.executed(old).count(runs.STEP), "not made again")
            kept, _ = self.rule(api, again)
            self.assertEqual((kept["revision"], kept["digest"]), (1, first["digest"]))


def model_lessons(text):
    from wgflib.yamllite import load
    return load(text)["lessons"]


if __name__ == "__main__":
    unittest.main()

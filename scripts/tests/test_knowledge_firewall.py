"""K4: the regression firewall - every lesson's tests, run, and reported per lesson.

scripts/wgf_knowledge/firewall.py (`wgf knowledge firewall`). A lesson's `catches` tests are
its NEGATIVE case (the check fails the build that showed the defect), its `passes` tests its
POSITIVE case (the check passes the fixed build), its `generalizes` tests the defect caught in
another game. These tests hold:

  * POSITIVE AND NEGATIVE. A check that does its job holds both cases; a check broken either
    way - passing the defect, or failing the fixed build - fails the lesson.
  * NEVER GREEN BY ABSENCE. A test that is missing is MISSING, one that was skipped is SKIP,
    an active lesson with no test FAILs, a validated one without all three kinds FAILs; any of
    them fails the firewall.
  * THE SHIPPED LESSONS. Every lesson of core/reference/lessons.yaml: each test it names
    exists and passes - the Core Acceptance Suite's KNOWLEDGE category runs this.
  * A RUN'S SUITE. `--run` holds the regression suite of the run's knowledge-contract.

    python -m unittest scripts.tests.test_knowledge_firewall
"""

import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import textwrap
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
for entry in (SCRIPTS, HERE):
    if entry not in sys.path:
        sys.path.insert(0, entry)

import knowledge_runs as kr  # noqa: E402
from wgf_knowledge import cli, firewall  # noqa: E402
from wgf_quality import registry  # noqa: E402

# A check under test, and the lesson's two cases written against it. `CHECK` is swapped per
# test module to model a check that works, one that passes the defect, one that fails a fix.
SAMPLE = '''
import unittest

CHECK = {check}


class Cases(unittest.TestCase):
    def test_the_check_fails_the_defect(self):          # catches: the negative case
        self.assertEqual(CHECK(overlap=0.6), "FAIL")

    def test_the_check_passes_the_fixed_build(self):    # passes: the positive case
        self.assertEqual(CHECK(overlap=0.1), "PASS")

    def test_skipped(self):
        self.skipTest("needs a browser")

    def test_errors(self):
        raise RuntimeError("the fixture is gone")


class Switched(Cases):
    test_errors = None
'''
WORKS = 'lambda overlap: "FAIL" if overlap > 0.25 else "PASS"'
BLIND = 'lambda overlap: "PASS"'
STRICT = 'lambda overlap: "FAIL"'


def lesson(lesson_id, module, catches=(), passes=(), generalizes=(), lifecycle="active"):
    ref = f"scripts/tests/{module}.py::"
    return {"id": lesson_id, "lifecycle": lifecycle, "status": "enforced",
            "tests": {"catches": [ref + t for t in catches], "passes": [ref + t for t in passes],
                      "generalizes": [ref + t for t in generalizes]}}


class Sample(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="wgf-fw-")
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        os.makedirs(os.path.join(self.root, "scripts", "tests"))

    def module(self, name, check):
        with open(os.path.join(self.root, "scripts", "tests", f"{name}.py"), "w",
                  encoding="utf-8") as handle:
            handle.write(textwrap.dedent(SAMPLE.format(check=check)))
        self.addCleanup(sys.modules.pop, name, None)
        return name

    def both_cases(self, name):
        return lesson("L1", name, catches=["test_the_check_fails_the_defect"],
                      passes=["test_the_check_passes_the_fixed_build"])

    def test_a_check_that_works_holds_both_cases(self):
        name = self.module("fw_sample_works", WORKS)
        report = firewall.run({"lessons": [self.both_cases(name)]}, self.root)
        self.assertEqual(report["verdict"], firewall.PASS)
        row = report["lessons"][0]
        self.assertEqual(row["verdict"], firewall.PASS)
        self.assertEqual({t["case"]: t["status"] for t in row["tests"]},
                         {"negative": "PASS", "positive": "PASS"})

    def test_a_check_that_passes_the_defect_fails_the_negative_case(self):
        name = self.module("fw_sample_blind", BLIND)
        row = firewall.run({"lessons": [self.both_cases(name)]}, self.root)["lessons"][0]
        self.assertEqual(row["verdict"], firewall.FAIL)
        self.assertEqual({t["case"]: t["status"] for t in row["tests"]},
                         {"negative": "FAIL", "positive": "PASS"})

    def test_a_check_that_fails_the_fix_fails_the_positive_case(self):
        name = self.module("fw_sample_strict", STRICT)
        row = firewall.run({"lessons": [self.both_cases(name)]}, self.root)["lessons"][0]
        self.assertEqual(row["verdict"], firewall.FAIL)
        self.assertEqual({t["case"]: t["status"] for t in row["tests"]},
                         {"negative": "PASS", "positive": "FAIL"})

    def test_missing_skipped_and_errored_tests_are_never_a_pass(self):
        name = self.module("fw_sample_gaps", WORKS)
        lessons = {"lessons": [
            lesson("L1", name, catches=["test_no_such_test"]),
            lesson("L2", "fw_no_such_module", catches=["test_x"]),
            lesson("L3", name, catches=["test_skipped"]),
            lesson("L4", name, catches=["test_errors"]),
            {"id": "L5", "lifecycle": "active", "status": "enforced"},
            dict(self.both_cases(name), id="L6", lifecycle="validated"),
            {"id": "L7", "lifecycle": "candidate", "status": "gap"},
            {"id": "L8", "lifecycle": "active", "status": "process"}]}
        report = firewall.run(lessons, self.root)
        verdicts = {r["id"]: r["verdict"] for r in report["lessons"]}
        self.assertEqual(verdicts, {"L1": "MISSING", "L2": "MISSING", "L3": "SKIP", "L4": "FAIL",
                                    "L5": "FAIL", "L6": "FAIL", "L7": "NO_TESTS",
                                    "L8": "NO_TESTS"})
        self.assertEqual(report["verdict"], firewall.FAIL)
        self.assertIn("generalizes", report["lessons"][5]["why"])
        # A subclass that switched a test off does not run it there.
        self.assertEqual(len(firewall._cases(sys.modules[name], "test_errors")), 1)

    def test_an_inherited_test_runs_where_discovery_runs_it(self):
        name = self.module("fw_sample_inherit", WORKS)
        cases = firewall._cases(sys.modules[name] if name in sys.modules
                                else firewall._module(self.root, f"scripts/tests/{name}.py"),
                                "test_the_check_fails_the_defect")
        self.assertEqual(sorted(type(c).__name__ for c in cases), ["Cases", "Switched"])

    def test_a_kind_filter_never_fails_a_lesson_for_lacking_that_kind(self):
        name = self.module("fw_sample_kind", WORKS)
        only_catches = lesson("L1", name, catches=["test_the_check_fails_the_defect"])
        report = firewall.run({"lessons": [only_catches]}, self.root, kinds=("generalizes",))
        self.assertEqual((report["verdict"], report["lessons"][0]["verdict"]),
                         (firewall.PASS, firewall.NO_TESTS))
        validated = dict(self.both_cases(name), lifecycle="validated")
        report = firewall.run({"lessons": [validated]}, self.root, kinds=("catches",))
        self.assertEqual(report["lessons"][0]["verdict"], firewall.PASS)

    def test_only_a_skip_is_still_not_a_pass(self):
        name = self.module("fw_sample_skip", WORKS)
        report = firewall.run({"lessons": [lesson("L1", name, catches=["test_skipped"])]},
                              self.root)
        self.assertEqual(report["verdict"], firewall.FAIL)

    def test_an_installed_runtime_cannot_run_it(self):
        bare = tempfile.mkdtemp(prefix="wgf-fw-rt-")
        self.addCleanup(shutil.rmtree, bare, ignore_errors=True)
        with self.assertRaises(firewall.FirewallUnusable):
            firewall.run({"lessons": []}, bare)


class ShippedLessons(unittest.TestCase):
    """Every lesson's tests exist and pass: the regression firewall of this checkout."""

    @classmethod
    def setUpClass(cls):
        data = registry.load(ROOT)
        cls.lessons = data["lessons"]
        cls.report = firewall.run(cls.lessons, ROOT)

    def test_every_lesson_holds(self):
        for row in self.report["lessons"]:
            with self.subTest(lesson=row["id"]):
                self.assertIn(row["verdict"], (firewall.PASS, firewall.NO_TESTS), row["why"])
                if row["lifecycle"] in ("active", "validated") and row["status"] != "process":
                    self.assertEqual(row["verdict"], firewall.PASS, row["why"])
        self.assertEqual(self.report["verdict"], firewall.PASS)

    def test_three_lessons_generalize_beyond_the_game_they_came_from(self):
        rows = {r["id"]: r for r in self.report["lessons"]}
        for lesson_id in ("L23", "L25", "L26"):
            cases = [t for t in rows[lesson_id]["tests"] if t["case"] == "generalizes"]
            self.assertTrue(cases, lesson_id)
            self.assertTrue(all(t["status"] == firewall.PASS for t in cases), lesson_id)


KNOWLEDGE_MODULE = """
import os
import sys
import unittest

sys.path.insert(0, {scripts!r})
from wgf_knowledge import firewall

ROOT = {root!r}
LESSONS = {{"lessons": [{{"id": "L1", "lifecycle": "active", "status": "enforced",
                          "tests": {{"catches": ["scripts/tests/{skip}.py::test_skipped"]}}}}]}}


class Firewall(unittest.TestCase):
    def test_every_lesson_holds(self):
        self.assertEqual(firewall.run(LESSONS, ROOT)["verdict"], firewall.PASS)
"""


class TheCategory(unittest.TestCase):
    def test_the_core_suite_runs_the_firewall_as_knowledge(self):
        import core_suite
        modules = core_suite.SUITE["KNOWLEDGE"]
        for name in ("test_knowledge_firewall", "test_knowledge_generalization",
                     "test_knowledge_ingest", "test_knowledge_generations"):
            self.assertIn(name, modules)
            self.assertTrue(os.path.isfile(os.path.join(HERE, f"{name}.py")), name)

    def test_a_skipped_lesson_test_fails_the_knowledge_category(self):
        """A lesson whose only test is skipped: the firewall says FAIL, and the KNOWLEDGE
        category that runs it reports a failure - never a PASS, never a quiet SKIP."""
        import wgf
        root = tempfile.mkdtemp(prefix="wgf-fw-cat-")
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        tests = os.path.join(root, "scripts", "tests")
        os.makedirs(tests)
        tag = f"k{os.getpid()}_{id(self)}"
        skip, check = f"{tag}_lesson", f"{tag}_knowledge"
        with open(os.path.join(tests, f"{skip}.py"), "w", encoding="utf-8") as handle:
            handle.write(textwrap.dedent(SAMPLE.format(check=WORKS)))
        with open(os.path.join(tests, f"{check}.py"), "w", encoding="utf-8") as handle:
            handle.write(KNOWLEDGE_MODULE.format(scripts=SCRIPTS, root=root, skip=skip))
        self.addCleanup(lambda: [sys.modules.pop(n, None) for n in (skip, check)])
        self.addCleanup(lambda: tests in sys.path and sys.path.remove(tests))
        report = firewall.run({"lessons": [lesson("L1", skip, catches=["test_skipped"])]}, root)
        self.assertEqual((report["verdict"], report["lessons"][0]["verdict"]),
                         (firewall.FAIL, firewall.SKIP))
        row = wgf.run_core_suite({"KNOWLEDGE": [check]}, tests)[0]
        self.assertEqual(row["result"], "FAIL")
        self.assertEqual((row["failed"], row["skipped"]), (1, 0))


class RunSuite(unittest.TestCase):
    def test_the_contract_suite_of_a_run(self):
        tmp = tempfile.mkdtemp(prefix="wgf-fw-run-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        store = kr.make_store(os.path.join(tmp, "store"))
        run = kr.add_run(store, "run-fw")
        l25 = next(l for l in registry.load(ROOT)["lessons"]["lessons"] if l["id"] == "L25")
        kr.add_report(store, run, "knowledge-contract", {"rules": [
            {"id": "L25", "level": "required", "tests": l25["tests"]}]})
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(["firewall", "--run", "run-fw", "--store", store.directory, "--json"])
        report = json.loads(out.getvalue())
        self.assertEqual((code, report["verdict"]), (0, firewall.PASS))
        self.assertEqual([r["id"] for r in report["lessons"]], ["L25"])
        none = kr.add_run(store, "run-none")
        del none
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(["firewall", "--run", "run-none",
                                       "--store", store.directory]), 2)


if __name__ == "__main__":
    unittest.main()

"""K4: Factory generations compared, and the benchmark approval table that starts nothing.

scripts/wgf_knowledge/generations.py (`wgf knowledge generations`) and cli.cmd_table
(`wgf knowledge table`). These tests hold:

  * GENERATIONS. Runs are grouped by the Factory and knowledge versions they recorded at
    start; each group says which lessons its runs were held to and their outcomes, and the
    lessons one generation applied that the previous did not.
  * NOTHING HIDDEN. A run that recorded no knowledge is its own generation, named
    unrecorded; an unreadable run is a problem, never dropped.
  * THE TABLE IS DRY. Every row - facet combinations, complexity profiles, roadmap phases -
    lists its budget as requiring a person's approval, and building it starts no run.

    python -m unittest scripts.tests.test_knowledge_generations
"""

import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
for entry in (SCRIPTS, HERE):
    if entry not in sys.path:
        sys.path.insert(0, entry)

import knowledge_runs as kr  # noqa: E402
from wgf_knowledge import cli, generations  # noqa: E402


def run_cli(*argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
        code = cli.main(list(argv))
    return code, out.getvalue()


def compliance(verdict, failed=(), excepted=(), satisfied=()):
    rules = ([{"id": r, "status": "FAILED"} for r in failed]
             + [{"id": r, "status": "EXCEPTED"} for r in excepted]
             + [{"id": r, "status": "SATISFIED"} for r in satisfied])
    return {"mode": "enforcing", "verdict": verdict, "rules": rules, "blocking": list(failed),
            "new_lessons": [], "counts": {"total": {
                "satisfied": len(satisfied), "failed": len(failed), "excepted": len(excepted),
                "unmeasured": 0}}}


class Generations(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="wgf-gen-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.store = kr.make_store(os.path.join(self.tmp, "store"))

    def mock_run(self, run_id, lessons_version, factory, applied, outcome, created):
        params = {"quality": {"tier": "release", "class": "release",
                              "factory": {"version": factory, "commit": "c" * 40},
                              "knowledge": {"lessons": f"lessons@{lessons_version}",
                                            "check-tiers": "check-tiers@1.2.0"}}}
        run = kr.add_run(self.store, run_id, params=params, created_at=created)
        kr.add_report(self.store, run, "knowledge-contract", {
            "facets": {"family": "arcade", "render": "2d"},
            "rules": [{"id": r, "level": "required"} for r in applied]})
        kr.add_report(self.store, run, "quality-report", kr.quality_report([], compliance=outcome))
        return run

    def test_generations_list_runs_by_versions(self):
        self.mock_run("gen1-a", "2.0.0", "2.7.0", ["L23", "L25"],
                      compliance("RELEASE_BLOCKED", failed=["L25"], satisfied=["L23"]),
                      "2026-10-08T09:00:00Z")
        self.mock_run("gen1-b", "2.0.0", "2.7.0", ["L23", "L25"],
                      compliance("PASS", excepted=["L25"], satisfied=["L23"]),
                      "2026-10-08T10:00:00Z")
        self.mock_run("gen2-a", "2.1.0", "2.8.0", ["L23", "L25", "L29"],
                      compliance("PASS", satisfied=["L23", "L25", "L29"]),
                      "2026-10-09T09:00:00Z")
        code, out = run_cli("generations", "--store", self.store.directory, "--json")
        self.assertEqual(code, 0)
        result = json.loads(out)
        self.assertEqual(result["problems"], [])
        self.assertEqual([r["run_id"] for r in result["runs"]], ["gen1-a", "gen1-b", "gen2-a"])
        first, second = result["generations"]
        self.assertEqual(first["runs"], ["gen1-a", "gen1-b"])
        self.assertEqual(first["knowledge"], {"check-tiers": "check-tiers@1.2.0",
                                              "lessons": "lessons@2.0.0"})
        self.assertEqual(first["outcomes"], {"PASS": 1, "RELEASE_BLOCKED": 1})
        self.assertEqual(first["failed_rules"], {"L25": 1})
        self.assertEqual(first["excepted_rules"], {"L25": 1})
        self.assertIn("lessons@2.1.0", second["key"])
        self.assertEqual(second["factory"]["version"], "2.8.0")
        self.assertEqual(second["added"], ["L29"])
        self.assertEqual(second["outcomes"], {"PASS": 1})
        row = result["runs"][0]
        self.assertEqual(row["lessons_applied"], ["L23", "L25"])
        self.assertEqual(row["compliance"]["failed_rules"], ["L25"])
        # The text form names both generations.
        code, text = run_cli("generations", "--store", self.store.directory)
        self.assertIn("generation factory 2.7.0@ccccccc / check-tiers@1.2.0 / lessons@2.0.0", text)
        self.assertIn("lessons added L29", text)

    def test_an_outcome_counts_for_the_knowledge_its_report_was_judged_by(self):
        """A run started under lessons 2.0.0 and resumed under 2.1.0: its quality-report was
        judged against 2.1.0, so its outcome belongs to that generation."""
        run = self.mock_run("resumed", "2.0.0", "2.7.0", ["L23"],
                            dict(compliance("PASS", satisfied=["L23"]), versions={
                                "factory": {"version": "2.8.0", "commit": "d" * 40},
                                "lessons": {"version": "2.1.0"},
                                "check_tiers": {"version": "1.2.0"}}),
                            "2026-10-08T09:00:00Z")
        del run
        entries, _ = generations.rows(self.store)
        entry = entries[0]
        self.assertEqual(entry["attributed_from"], "quality-report")
        self.assertEqual(entry["knowledge"], {"check-tiers": "check-tiers@1.2.0",
                                              "lessons": "lessons@2.1.0"})
        self.assertEqual(entry["factory"]["version"], "2.8.0")
        self.assertEqual(entry["started_with"]["knowledge"]["lessons"], "lessons@2.0.0")
        self.assertEqual(entry["quality_report"]["artifact_id"], "qr-1")
        self.assertEqual(entry["quality_report"]["build_commit"], kr.COMMIT)
        self.assertIn("lessons@2.1.0", generations.generations(entries)[0]["key"])

    def test_the_factory_code_that_judged_the_build_is_its_factory(self):
        """compliance.versions copies the contract's Factory; evaluated_by is the code that
        ran the quality gate, and the outcome's Factory code is attributed to it."""
        self.mock_run("judged", "2.0.0", "2.7.0", ["L23"],
                      dict(compliance("PASS", satisfied=["L23"]), versions={
                          "factory": {"version": "2.7.0", "commit": "c" * 40},
                          "lessons": {"version": "2.0.1"}, "check_tiers": {"version": "1.2.0"}},
                           evaluated_by={"version": "2.9.0", "commit": "e" * 40}),
                      "2026-10-08T09:00:00Z")
        entry = generations.rows(self.store)[0][0]
        self.assertEqual(entry["factory"], {"version": "2.9.0", "commit": "e" * 40})
        self.assertEqual(entry["factory_from"], "quality-report evaluated_by")
        self.assertEqual(entry["knowledge"]["lessons"], "lessons@2.0.1")

    def test_a_run_without_recorded_knowledge_is_unrecorded_and_a_broken_one_a_problem(self):
        kr.add_run(self.store, "old-run", params={"quality": {"tier": "mvp"}})
        broken = kr.add_run(self.store, "broken-run")
        with open(os.path.join(self.store.run_dir(broken.run_id), "state.json"), "w") as handle:
            handle.write("{")
        entries, problems = generations.rows(self.store)
        self.assertEqual([e["run_id"] for e in entries], ["old-run"])
        self.assertIn("unrecorded", generations.key_of(entries[0]))
        self.assertFalse(entries[0]["contract"])
        self.assertTrue(any("broken-run" in p for p in problems))


class Table(unittest.TestCase):
    def test_every_profile_and_phase_requires_budget_approval_and_nothing_starts(self):
        from wgflib.workflow import api
        boom = mock.Mock(side_effect=AssertionError("the table started a run"))
        with mock.patch.object(api.WorkflowAPI, "run", boom, create=True), \
                mock.patch.object(api.WorkflowAPI, "start", boom, create=True):
            code, out = run_cli("table", "--families", "arcade", "--render", "2d,3d",
                                "--tiers", "release", "--profiles", "A,B", "--phases", "1",
                                "--json")
        self.assertIn(code, (0, 1))
        result = json.loads(out)
        self.assertFalse(result["starts_run"])
        self.assertEqual(len(result["rows"]), 4)
        for row in result["rows"]:
            self.assertEqual(row["budget"], "requires human budget approval")
            self.assertFalse(row["starts_run"])
            self.assertIsNone(row["approved_by"])
            self.assertEqual(row["phase"], "1")
        self.assertEqual(sorted({r["facets"]["profile"] for r in result["rows"]}), ["a", "b"])
        boom.assert_not_called()
        code, text = run_cli("table", "--families", "arcade", "--render", "2d",
                             "--tiers", "release", "--phases", "2")
        self.assertIn("requires human budget approval", text)
        self.assertIn("Nothing was started and nothing was spent", text)

    def test_candidate_benchmarks_from_a_file(self):
        tmp = tempfile.mkdtemp(prefix="wgf-table-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        path = os.path.join(tmp, "benchmarks.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({"candidates": [
                {"family": "arcade", "render": "3d", "tier": "release", "profile": "E",
                 "phase": 5, "cost_estimate": "$450-650"}]}, handle)
        code, out = run_cli("table", "--facets", path, "--json")
        row = json.loads(out)["rows"][0]
        self.assertEqual((row["cost_estimate"], row["phase"]), ("$450-650", 5))
        self.assertEqual(row["budget"], "requires human budget approval")


if __name__ == "__main__":
    unittest.main()

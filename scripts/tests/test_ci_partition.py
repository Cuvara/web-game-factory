"""The acceptance workflow's split of the suite (scripts/ci-partition.py): every test module
runs in exactly one job, and the workflow runs the split it was proven on."""
import importlib.util
import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
SPEC = importlib.util.spec_from_file_location("ci_partition",
                                              os.path.join(ROOT, "scripts", "ci-partition.py"))
partition = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(partition)
WORKFLOW = os.path.join(ROOT, ".github", "workflows", "acceptance.yml")


class TheSplit(unittest.TestCase):
    def test_every_module_runs_in_exactly_one_place(self):
        self.assertEqual(partition.check(4), [])

    def test_the_shards_are_disjoint_and_cover_the_unit_modules(self):
        shards = partition.shards(4)
        flat = [m for s in shards for m in s]
        self.assertEqual(len(flat), len(set(flat)))
        self.assertEqual(sorted(flat), partition.unit_modules())
        self.assertTrue(all(shards))

    def test_a_category_module_is_never_a_unit_module(self):
        named = partition.suite_modules(partition.core() + partition.golden())
        self.assertFalse(named & set(partition.unit_modules()))

    def test_a_module_no_job_runs_is_reported(self):
        original = partition.shards
        dropped = original(4)[0][0]
        partition.shards = lambda count: [[m for m in s if m != dropped] for s in original(count)]
        try:
            self.assertIn(f"{dropped} runs nowhere", partition.check(4))
        finally:
            partition.shards = original
        # And twice in one place is reported as well.
        partition.shards = lambda count: [s + [dropped] for s in original(count)]
        try:
            self.assertTrue(any("more than one unit shard" in p for p in partition.check(4)))
        finally:
            partition.shards = original

    def test_the_goldens_and_the_core_categories_are_the_whole_suite_but_opt_in(self):
        import core_suite
        self.assertEqual(set(partition.core()) | set(partition.golden()),
                         set(core_suite.SUITE) - set(core_suite.OPT_IN))
        self.assertFalse(set(partition.core()) & set(partition.golden()))


class TheWorkflow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(WORKFLOW, encoding="utf-8") as handle:
            cls.text = handle.read()

    def test_the_golden_matrix_is_every_golden_category(self):
        matrix = re.search(r"category: \[([^\]]*)\]", self.text).group(1)
        listed = sorted(c.strip().strip("'\"") for c in matrix.split(","))
        self.assertEqual(listed, sorted(partition.golden()))

    def test_the_shard_count_is_the_one_the_split_is_checked_on(self):
        self.assertIn("shard: [0, 1, 2, 3]", self.text)
        self.assertIn("python3 scripts/ci-partition.py check 4", self.text)
        self.assertIn("python3 ../ci-partition.py units ${{ matrix.shard }} 4", self.text)

    def test_the_gate_needs_every_job_and_runs_the_suite_strictly(self):
        self.assertIn("needs: [checks, units, core, golden]", self.text)
        self.assertIn('bin/wgf test-core --strict "${args[@]}"', self.text)
        self.assertIn('bin/wgf test-core --strict --only "${{ matrix.category }}"', self.text)
        self.assertIn("WGF_GOLDEN=1", self.text)


if __name__ == "__main__":
    unittest.main()

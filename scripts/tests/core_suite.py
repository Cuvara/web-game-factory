"""The Core Acceptance Suite: which test modules prove which part of Core v1. Data only.

`wgf test-core` runs these category by category and prints PASS / FAIL / SKIP / MISSING.
A module named here that does not exist yet makes its category MISSING, which fails the
suite: an incomplete suite must never look green. A category that ran nothing, or only
skips, is SKIP, not PASS. Every skipped test is listed with its reason, and the summary
says INCOMPLETE rather than a bare OK; `--strict` exits 4 on any skip (docs/core-v1.md).

Adding a category or a module is an edit to this mapping and nothing else. Module names
are files in scripts/tests/ without `.py`.
"""

SUITE = {
    "WORKFLOW": ["test_core_workflow", "test_core_persistence", "test_decisions"],
    "AGENTS": ["test_core_agents"],
    "CONTRACTS": ["test_core_contracts", "test_core_lineage", "test_core_template", "test_golden_fast"],
    "VERIFY": ["test_core_verify"],
    "RELEASE": ["test_core_release"],
    "2D GOLDEN": ["test_golden_2d"],
    "3D GOLDEN": ["test_golden_3d"],
    "PROCESS CLEANUP": ["test_core_process"],
    "SECURITY": ["test_core_security"],
}

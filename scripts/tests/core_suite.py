"""The Core Acceptance Suite: which test modules prove which part of Core v1. Data only.

`wgf test-core` runs these category by category and prints PASS / FAIL / SKIP / MISSING.
A module named here that does not exist yet makes its category MISSING, which fails the
suite: an incomplete suite must never look green. A category that ran nothing, or only
skips, is SKIP, not PASS. Every skipped test is listed with its reason, and the summary
says INCOMPLETE rather than a bare OK; `--strict` exits 4 on any skip (docs/core-v1.md).

Adding a category or a module is an edit to this mapping and nothing else. Module names
are files in scripts/tests/ without `.py`.

OPT_IN names categories a plain `wgf test-core` does not run: each runs only when named with
`--only`, or when its variable is exactly "1". One not run is listed as such under the table
(and in --json as `opt_in_not_run`), never as PASS; named or enabled, it runs like any other
category - its tests SKIP without the variable, and a skip is never a pass. It keeps a
category that needs its own runner (the golden loop: two more golden runs) out of the
release gate's time budget without making that gate --strict-incomplete.
"""

SUITE = {
    "WORKFLOW": ["test_core_workflow", "test_core_persistence", "test_decisions",
                 "test_triage"],
    "AGENTS": ["test_core_agents", "test_live_loop"],
    "CONTRACTS": ["test_core_contracts", "test_core_lineage", "test_core_template", "test_golden_fast"],
    "VERIFY": ["test_core_verify"],
    "RELEASE": ["test_core_release", "test_publish_module", "test_publish_registry",
                "test_publish_observe", "test_publish_executor", "test_publish_step",
                "test_publish_adaptive", "test_publish_campaign", "test_publish_portals"],
    # An intentionally bad game cannot pass new-game: six genres held to one floor, eleven
    # degradations each detected, blocking and routed, recovery, anti-gaming (WS-13,
    # docs/quality-consistency-tests.md).
    "QUALITY": ["test_quality_consistency"],
    "2D GOLDEN": ["test_golden_2d"],
    "3D GOLDEN": ["test_golden_3d"],
    # The closed loop on a real build: the 2D golden with a planted defect fails a real check
    # (restart.works, real clicks), is routed back to greybox, and passes the same check on a
    # newer commit; and its negative control never passes (docs/golden-runs.md). Opt-in.
    "GOLDEN LOOP": ["test_golden_loop"],
    # The knowledge the Factory learned holds: every lesson's catches, passes and generalizes
    # tests exist and pass (the regression firewall), the model and the resolver, a run held
    # to its contract and its compliance, and the learning loop - ingestion, promotion
    # drafts, generations (docs/knowledge-enforcement.md).
    "KNOWLEDGE": ["test_knowledge_firewall", "test_knowledge_generalization",
                  "test_knowledge_ingest", "test_knowledge_generations",
                  "test_knowledge_model", "test_knowledge_resolve",
                  "test_knowledge_exceptions", "test_knowledge_compliance",
                  # K5: the decision trace, L29's own tests.
                  "test_knowledge_trace", "test_lesson_l29", "test_knowledge_transfer",
                  "test_knowledge_pins"],
    "PROCESS CLEANUP": ["test_core_process"],
    "SECURITY": ["test_core_security"],
}

OPT_IN = {"GOLDEN LOOP": "WGF_GOLDEN_LOOP"}

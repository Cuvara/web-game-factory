# QA Report — {{game_name}} {{release_id}}

<!--
  A RENDERING of the qa-report artifact. The artifact is authoritative.
  Read at gate G5.
-->

**Title** {{title_id}} · **Release** {{release_id}} · **Commit** {{commit_sha}}
**Verdict** **{{verdict}}** · **By** {{role}} · {{produced_at}}

---

## Summary

Blocking defects: **{{blocking_count}}** · Accepted defects: {{accepted_count}}
Performance: {{perf_summary}}

`verdict` is derived from blocking defects and performance budgets, not asserted. A report
saying `pass` while carrying a blocker is malformed.

## Deterministic suites

| Suite | Passed | Failed | Skipped | Coverage | Run |
|---|---|---|---|---|---|
| {{name}} | {{passed}} | {{failed}} | {{skipped}} | {{coverage}} | {{run_url}} |

These are facts from a pipeline, not judgements.

## Blocking defects

Must be empty to reach RC.

| Id | Severity | Summary | Platform | Repro |
|---|---|---|---|---|
| {{id}} | {{severity}} | {{summary}} | {{platform_id}} | {{repro}} |

## Accepted defects

Shipped knowingly. Each needs a rationale, and each is read by a human at G5 — accepted, not
silently dropped.

| Id | Severity | Summary | Why accepted |
|---|---|---|---|
| {{id}} | {{severity}} | {{summary}} | {{accepted_rationale}} |

## Performance

Measured against `tech_plan.perf_budgets`, per device class. The low end is where budgets
break.

| Device class | FPS | Memory | TTI | Bundle | In budget |
|---|---|---|---|---|---|
| {{device_class}} | {{fps}} | {{memory_mb}} MB | {{time_to_interactive_s}}s | {{bundle_mb}} MB | {{within_budget}} |

## Browser matrix

| Browser | Platform | Result | Note |
|---|---|---|---|
| {{browser}} | {{platform}} | {{result}} | {{note}} |

## Platform checks

Functional behaviour per portal — SDK init, ad playback and resume, save/load, leaderboards.
Distinct from the package assertions run at `release:validating`.

| Platform | Result | Checks | Note |
|---|---|---|---|
| {{platform_id}} | {{result}} | {{checks}} | {{note}} |

## Not tested

State the gaps. An untested area reported as passing is worse than an untested area
reported as untested.

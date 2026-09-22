---
description: Assemble, QA and freeze a release candidate, then take it to approval.
---

# /wgf-release

**Transition** `title: production -> releasing; release: draft -> qa -> rc -> approved`
**Role** `release`
**Gate** `G5` — see `core/lifecycle/gates.yaml` for its required artifacts, predicates and approvers.

Assemble, QA and freeze a release candidate, then take it to approval.

## Procedure

1. Read `core/lifecycle/` for the machine that owns this transition, and the
   `procedure` file named on the source state.
2. Read the `x-wgf` block of every artifact schema this transition produces or consumes.
3. Check the transition's guards before acting. A guard that cannot be evaluated is a
   blocker to report, not one to assume.
4. Delegate the work to the `release` agent.
5. Record the outcome: artifacts at their `repo_path`, and the title's `state.json`.

Commands map to transitions rather than to stages, so this file stays correct as long as
the machine does.

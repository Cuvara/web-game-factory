---
description: Present the ranked shortlist and record the selection decision.
---

# /wgf-select

**Transition** `portfolio: shortlisted -> approved -> promoted`
**Role** `analysis`
**Gate** `G1` — see `core/lifecycle/gates.yaml` for its required artifacts, predicates and approvers.

Present the ranked shortlist and record the selection decision.

## Procedure

1. Read `core/lifecycle/` for the machine that owns this transition, and the
   `procedure` file named on the source state.
2. Read the `x-wgf` block of every artifact schema this transition produces or consumes.
3. Check the transition's guards before acting. A guard that cannot be evaluated is a
   blocker to report, not one to assume.
4. Delegate the work to the `analysis` agent.
5. Record the outcome: artifacts at their `repo_path`, and the title's `state.json`.

Commands map to transitions rather than to stages, so this file stays correct as long as
the machine does.

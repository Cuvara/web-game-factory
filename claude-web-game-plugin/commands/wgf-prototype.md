---
description: Build the prototype to a fun-testable standard, have each development commit reviewed (review-report), and write the prototype report.
---

# /wgf-prototype

**Transition** `title: prototype -> prototype-review`
**Role** `gameplay`


Build the prototype to a fun-testable standard, have each development commit reviewed (review-report), and write the prototype report.

## Procedure

1. Read `core/lifecycle/` for the machine that owns this transition, and the
   `procedure` file named on the source state.
2. Read the `x-wgf` block of every artifact schema this transition produces or consumes.
3. Check the transition's guards before acting. A guard that cannot be evaluated is a
   blocker to report, not one to assume.
4. Delegate the work to the `gameplay` agent.
5. Record the outcome: artifacts at their `repo_path`, and the title's `state.json`.

Commands map to transitions rather than to stages, so this file stays correct as long as
the machine does.

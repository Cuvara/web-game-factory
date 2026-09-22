---
description: Produce the game design and asset manifest; run the consistency check.
---

# /wgf-design

**Transition** `title: design -> tech-plan`
**Role** `game-designer`


Produce the game design and asset manifest; run the consistency check.

## Procedure

1. Read `core/lifecycle/` for the machine that owns this transition, and the
   `procedure` file named on the source state.
2. Read the `x-wgf` block of every artifact schema this transition produces or consumes.
3. Check the transition's guards before acting. A guard that cannot be evaluated is a
   blocker to report, not one to assume.
4. Delegate the work to the `game-designer` agent.
5. Record the outcome: artifacts at their `repo_path`, and the title's `state.json`.

Commands map to transitions rather than to stages, so this file stays correct as long as
the machine does.

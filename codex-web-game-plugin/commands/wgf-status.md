# /wgf-status (Web Game Factory)

**Transition** `read-only`
**Role** `-`


Report portfolio and title state from workspace/.

## Procedure

1. Read `core/lifecycle/` for the machine that owns this transition, and the
   `procedure` file named on the source state.
2. Read the `x-wgf` block of every artifact schema this transition produces or consumes.
3. Check the transition's guards before acting. A guard that cannot be evaluated is a
   blocker to report, not one to assume.
4. Read `workspace/` and report. This command changes nothing.
5. Write nothing.

Commands map to transitions rather than to stages, so this file stays correct as long as
the machine does.

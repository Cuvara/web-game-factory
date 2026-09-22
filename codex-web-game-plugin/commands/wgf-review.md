# /wgf-review (Web Game Factory)

**Transition** `title: prototype-review -> production, prototype or abandoned`
**Role** `portfolio-owner`
**Gate** `G4` — see `core/lifecycle/gates.yaml` for its required artifacts, predicates and approvers.

The kill gate. Judge the prototype against the kill criteria set at strategy.

## Procedure

1. Read `core/lifecycle/` for the machine that owns this transition, and the
   `procedure` file named on the source state.
2. Read the `x-wgf` block of every artifact schema this transition produces or consumes.
3. Check the transition's guards before acting. A guard that cannot be evaluated is a
   blocker to report, not one to assume.
4. Prepare the decision for the human approver per `core/roles/portfolio-owner.md`. Do not decide.
5. Record the human's decision as a `decision-record`, and update the title's `state.json`.

Commands map to transitions rather than to stages, so this file stays correct as long as
the machine does.

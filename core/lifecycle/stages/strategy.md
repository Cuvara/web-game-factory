# Strategy

**Machine** title · **State** `strategy` · **Kind** AI-assisted · **Role** game-designer
**Contributors** analysis, architect · **Gate** G2
**Inputs** `opportunity`, `evaluation`, `claim` · **Outputs** `title-strategy`

The commitment. What we are building, for whom, on what, by when — and the terms under
which we stop.

## Why this is its own state

Every other planning concern folds into `design`. Strategy does not, for one reason:
**kill criteria are authored here.**

Criteria written at review time get written to justify the decision already made. Nobody
sets a bar they are about to fail. Writing them before any code exists, under a gate,
while the idea is still cheap, is what makes `abandon` a real option at G4 rather than a
theoretical one. If you remove nothing else from this methodology, keep this.

## The questions the artifact must answer

- What are we building? (`one_liner` — one sentence a stranger understands)
- Why this opportunity? (referencing claims, not restating the score)
- Who is the player?
- Which platform is primary, which secondary, and why? (`platform_set` with roles and
  **pinned profile versions**)
- How does it monetize?
- What is the intended session?
- What is the MVP?
- **What is explicitly out of scope?**
- How long do we give it?
- What must the prototype prove?
- What would make us stop?

## Procedure

1. **Resolve platform profiles** for every candidate platform and pin their versions. From
   this point the design is bound to those constraints; pinning means a later build can be
   checked against the rules that were actually in force.

2. **Set the platform roles.** `required` means the title is not shippable without it.
   Marking everything required is the same as marking nothing required.

3. **Write `out_of_scope` and make it non-empty.** The schema requires it. A strategy that
   excludes nothing has not made a decision, and every attractive concept becomes an
   oversized project through additions that nobody ever refused. The factory must be able
   to say "this is excluded because it does not contribute enough to initial validation" —
   this field is where that sentence lives.

4. **Write `prototype_must_prove`.** Specific questions, not "prove the game is fun".
   Without these the prototype drifts into small production.

5. **Write `success_criteria` and `kill_criteria`** as criteria-expressions with
   rationales. Each kill criterion needs a threshold you can measure and a reason you can
   defend — a criterion nobody can justify gets argued away at exactly the moment it
   matters.

6. **Set `timebox_days` and `max_prototype_iterations`.** The factory targets 7-14 days.
   Beyond ~21 this is a different kind of project and should be decided as one.

7. **Record what the plan rests on.** `concept` narrows the opportunity to one control
   scheme and one gameplay direction. `production_scope` states technical and asset
   complexity, the estimate before fitting, the asset budget, the reusable systems and each
   scope decision. `platform_compatibility` lists every candidate — including the ones left
   out and why — with the SDK features and profile constraints the design inherits.
   `risks` carries the opportunity's risks forward and adds the ones this plan introduces;
   `assumptions` names what the plan takes as true and what would show it false.

## Optimize for rapid production

Strategy is where a title is kept small, because every later stage inherits its scope. The
default answer to a feature is *no*, with the reason written into `out_of_scope` or
`scope_decisions`:

- **A small core loop**, one content set, difficulty from one data-driven ramp rather than
  hand-built levels.
- **Reusable systems** from the template — boot flow, SDK adapter, persistence, ad breaks —
  rather than bespoke ones.
- **A low asset count**, capped as a number in `production_scope.asset_budget`.
- **Short sessions** — minutes, not tens of minutes — and **replay from a system** (score
  chase, procedural variation, a mastery ramp), not from more content.
- **One simple control scheme**, understood without a tutorial.
- **Simple platform integration**: one required platform; secondaries only where the same
  build satisfies them.

An estimate above the target timebox cuts the design, not the calendar. Beyond ~21 days the
opportunity is refused and goes back to be re-scoped — that is a different kind of project.

## Gate G2

Guards: `kill_criteria_defined`, `timebox_set`. The presenter reads the kill criteria
aloud — they are the terms of the bet, and the gate is where both parties agree to them.

Reversible, so auto-approval is permitted (default 48h).

## Failure modes

- **Kill criteria that cannot fire.** "Abandon if the game is not fun" is not a criterion.
  "Abandon if fewer than half of first-time playtesters reach the first reward unaided" is.
- **Platform sprawl.** Four required platforms multiply compliance work and guarantee a
  `partially-live` release. Pick one primary.
- **Optimistic timeboxing.** The timebox is a constraint on scope, not a prediction. If the
  design will not fit, cut the design.

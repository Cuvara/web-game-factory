# Role: Game designer

**Kind** owner · **Owns** `title:strategy`, `title:design`
**Produces** `title-strategy`, `game-design` · **Presents at** G2, G4

Authors the commitment, then solves the design as one problem.

## Charter

Write the strategy — including the terms under which the title is abandoned — and then
design scope, session, retention and monetization together, bound by the platform
constraints that were pinned at strategy.

## The two things that matter most

**1. Kill criteria are written before any code exists.**

Criteria authored at review time get authored to justify the decision already made. Nobody
sets a bar they are about to fail. Writing them at strategy, under a gate, while the idea is
still cheap, is what makes `abandon` real at G4. This is the single most important thing
this role does.

Each criterion needs a measurable threshold and a defensible rationale. "Abandon if the game
is not fun" is not a criterion. "Abandon if fewer than half of first-time playtesters reach
the first reward unaided" is.

**2. Scope, session, retention and monetization are one problem.**

Scope depends on monetization, which depends on session, which depends on scope. Design them
together in one artifact, run the consistency rules, and record the result. Four separate
documents drift and none of them is ever individually wrong.

## Rules

- `out_of_scope` is required and non-empty. A strategy that excludes nothing has not decided
  anything, and every attractive concept becomes an oversized project through additions
  nobody ever refused.
- Read platform profiles as **binding** at design time and record each constraint absorbed
  in `platform_constraints_applied`. An empty list on a title with required platforms means
  they were not read.
- For every monetization placement, state the in-game trigger and the player value. A
  rewarded placement with no player value is an interstitial wearing a costume.
- When the consistency check fails, **cut scope; do not relax the rules.** A rule waived
  once never fires again.

## At G4

You present the prototype evidence, and you do not defend the prototype against its own
kill criteria. The question is whether we would start this today knowing what we now know —
not whether it can be saved.

## Failure modes

- **Designing for the pitch.** A design that reads well and cannot be built in the timebox
  has failed at the only thing it was asked to do.
- **Retrofitting monetization.** Designed after the loop, it interrupts the loop.
- **Open-ended progression.** No terminal state and no deliberate loop is an endless content
  obligation a 7-14 day model cannot service.

# Role: LiveOps

**Kind** owner · **Owns** `title:live`
**Produces** `performance-review`, `claim` · **Presents at** G7

Interprets what happens after launch, and decides what to do about it.

## Why this role exists

It was missing. The `sdk` role integrates the analytics SDK; **nobody interpreted the
data**. That left the factory's entire premise — that it learns from what it ships — without
an owner, and an unowned premise is a slogan.

## Charter

Run the scheduled review at D1, D7, D30 and every 30 days after. Decide `iterate`, `scale`,
`hold` or `sunset`. Feed generalizable observations back into the portfolio as claims.

## The separation you are responsible for

```
Observed metric  →  Analysis  →  Hypothesis  →  Experiment  →  Result
```

Four different things, four different fields in the artifact:

- **`metrics`** — measured values only, per platform, with sample size. No interpretation.
- **`findings`** — derived, citing the metrics they rest on, each with a caveat saying what
  would make the reading wrong.
- **`hypotheses`** — untested, each with how it would be tested.
- **`experiments`** — a change with a stated success condition, so it can be wrong and be
  known to be wrong.

**Correlation is not causation.** The schema is the mechanism that enforces this, because
prose guidance dissolves the moment someone summarizes a review in a hurry.

Report per platform, never averaged: the same game performs differently on different portals
and an average hides exactly what you need to see. Always carry sample size — D1 retention
from 40 players reads identically to 40,000 unless the artifact forces the difference into
view.

## Feeding the portfolio

`emitted_claims` writes back into `workspace/claims/`. This is how shipping one game
improves the next opportunity scan. It is a **data edge to discovery, not a control
transition** — nothing about a live title moves the portfolio; new evidence simply changes
what the next scan believes.

## At G7

You propose a campaign; a human authorizes an amount. Present actuals against the strategy's
success criteria, the ceiling, the stop condition, and `projection_basis` — which observed
metrics the projection extrapolates from and under what assumption.

A projection is a hypothesis with a number attached. Label it as one.

## Failure modes

- **Reviewing without the strategy open.** Criteria set before launch are the only honest
  yardstick.
- **Iterating on a game that should sunset.** The `sunset_floor` was set in advance for
  exactly this reason.
- **Letting reviews lapse.** An unreviewed live title is an unmanaged liability and a
  missing input to discovery.

# Performance review

**Machine** title · **Scheduled job within** `live` · **Kind** AI-assisted · **Role** liveops
**Contributors** analysis
**Outputs** `performance-review`, `claim`

The step that turns a continuous data feed into a decision.

## The separation that matters

```
Observed metric  →  Analysis  →  Hypothesis  →  Experiment  →  Result
```

These are four different things and the artifact keeps them in four different fields:

- **`metrics`** — what was measured. Values only, per platform, with sample size. No
  interpretation. Per platform because the same game performs differently on different
  portals and an average hides exactly the thing you need to see.
- **`findings`** — derived interpretation, each citing the metrics it rests on, each with a
  `caveat` stating what would make the reading wrong.
- **`hypotheses`** — untested explanations, each with how it *would* be tested.
- **`experiments`** — a change with a stated `success_condition`, so it can be wrong and be
  known to be wrong.

**Correlation is not causation, and the schema is the mechanism that keeps it that way.**
Prose guidance dissolves the moment someone summarizes a review in a hurry; separate fields
survive summarization.

Sample size is required for the same reason: a D1 retention figure from 40 players reads
identically to one from 40,000 unless the artifact forces the difference into view.

## Procedure

1. Pull metrics for the window, per platform.
2. Evaluate `title_strategy.success_criteria` — the criteria set before launch. Record each
   result in `vs_success_criteria`.
3. Write findings, citing metrics. Write the caveat; there almost always is one.
4. Write hypotheses separately, with how each would be tested.
5. Propose experiments where a hypothesis is worth testing, each with a success condition.
6. **Emit claims back to the portfolio.** Generalizable observations — about the genre, the
   mechanic, the platform, the audience — become claims in `workspace/claims/`. This is the
   factory learning across titles rather than within one.
7. Decide: `iterate`, `scale`, `hold`, or `sunset`, with a rationale.

## If the decision is `scale`

A paid campaign requires gate **G7** and an explicit spend ceiling. Fill the `campaign`
block including `stop_condition` and `projection_basis` — which observed metrics the
projection extrapolates from and under what assumption.

The AI proposes; a human authorizes an amount. No standing budget, no auto-renewal, and a
projection is never presented as a forecast.

## If the decision is `sunset`

Requires `below_sunset_floor` — sustained underperformance across the number of consecutive
reviews set at strategy. Deciding this in advance is what stops a title being maintained
indefinitely out of reluctance.

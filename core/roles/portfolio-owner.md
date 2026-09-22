# Role: Portfolio owner

**Kind** human · **Gates** G1–G7

The human accountable for every gate decision. The only party that may kill a concept,
authorize publication, or approve spend.

Named as a role rather than left as an implicit "somebody approves", because a gate with no
named approver is a gate that gets skipped.

## Responsibilities

- Decide at all seven gates, and record each decision with a rationale.
- Own the portfolio: how many titles run concurrently, which opportunities are parked, when
  a live title sunsets.
- Maintain the scoring model. Weights are policy, and policy is this role's to set and
  retune against shipped outcomes.
- Resolve escalations from the change process during production.

## What only this role can do

| Gate | Decision | Why it cannot be delegated to an AI |
|---|---|---|
| G4 | Abandon a title | Killing work is a judgement about sunk cost and opportunity, not a computation |
| G6 | Publish | Publication is public, cached, and indexed — it cannot be fully undone |
| G7 | Approve spend | Money leaves |

These three never auto-approve. The decision-record schema enforces `mode: human` on them.

The other four (G1, G2, G3, G5) are reversible and may auto-approve after their configured
window. That is a deliberate concession to throughput: seven gates against a 7-14 day cycle
is a gate roughly every 1.4 days, and a factory whose gates cannot be cleared will have its
gates removed by whoever is under pressure — including the ones that matter.

## How to read what is presented

- **Read the criteria before the results.** At G4 especially: reading the prototype report
  first invites the kill criteria to be reinterpreted in light of it.
- **Ask which numbers are observed.** Every artifact distinguishes observed, derived and
  hypothesis. Use it.
- **Ask what the strongest argument against is.** If the presenter cannot state one, the
  analysis is incomplete rather than the case flawless.
- **Sunk cost is not an input.** The work already done is gone regardless of the decision.

## A note on autonomy

An AI should not autonomously spend money or make irreversible commercial decisions. The
gates encode that. But gates that are never cleared are worse than gates that are
occasionally automatic — this role's real job is to keep the factory moving while holding
the three lines that actually matter.

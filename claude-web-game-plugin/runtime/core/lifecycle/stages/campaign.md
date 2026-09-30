# Campaign

**Machine** title · **Sub-activity within** `live` · **Gate** G7
**Kind** human approval · **Role** liveops (proposes) · **Approver** portfolio-owner
**Inputs** `performance-review` · **Outputs** `decision-record`

Paid user acquisition for a live title.

## Why it is a sub-activity and not a stage

A campaign runs while the game is live and does not change the title's lifecycle state. It
is a self-loop on `live`, gated.

It is documented explicitly because the requirement existed, `campaign.yml` exists in the
template, and it appeared in **no stage** of the proposed workflow — which is how money gets
spent by a system nobody designed to spend money.

## The rule

> **The AI proposes. A human authorizes an amount.**

No standing budget. No auto-renewal. No campaign without a `spend_ceiling_usd` in the
decision record — the schema requires it for G7, because an approval to spend without an
amount is not an approval.

G7 is irreversible (money leaves) and therefore **never auto-approves**.

## What must be presented

1. **Retention and monetization actuals** against the success criteria set at strategy.
   Acquiring players for a game that does not retain them converts budget into nothing at a
   predictable rate.
2. **The proposed ceiling** and the channels.
3. **A `stop_condition`** — the measurable state at which the campaign halts, set before it
   starts.
4. **`projection_basis`** — which observed metrics the projection extrapolates from, and
   under what assumption. A projection is a hypothesis with a number attached and must be
   labelled as one.
5. **Which numbers are observed and which are projected.** This distinction disappears in
   summary unless someone insists on it.

## Preconditions worth enforcing by habit

- The title is `live` on at least one platform, with at least one completed
  `performance-review` past D7. Acquiring into an unmeasured game is buying data at the
  most expensive price available.
- Retention is at or above the strategy's targets, or the campaign is explicitly framed as
  a test with a small ceiling.

## During and after

Track spend against the ceiling and the stop condition continuously. When the campaign
ends, record the outcome as an `experiment` result in the next performance review — including
when it failed. A campaign whose result is never written down teaches nothing and will be
run again.

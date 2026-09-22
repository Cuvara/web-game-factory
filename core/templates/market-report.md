# Market Report — {{scope}}

<!--
  A RENDERING of claims and opportunities for human reading. Deliberately NOT a schema'd
  artifact: nothing downstream parses a market report, so it is not a contract between
  stages. The contracts are `claim` and `opportunity`.

  Every statement here cites a claim id. A sentence in this report with no claim behind it
  is the exact failure mode the claim system exists to prevent.
-->

**Scan scope** {{scope}} · **Run** {{produced_at}} · **By** {{role}}
**Claims written** {{claim_count}} · **Opportunities raised** {{opportunity_count}}

---

## What was looked at

Which platforms, which genres, over what period, and using what sources. State the
boundaries — an unbounded scan produces a wall of undifferentiated observations nobody
scores.

## Observed

Measured or read from a named source. Every line cites `[claim-id]`.

- {{statement}} `[claim-xxxx]` — {{source}}, observed {{observed_at}}

## Derived

Reasoned from the observations above. Each cites its parent claims.

- {{statement}} `[claim-xxxx]` ← `[claim-yyyy, claim-zzzz]`

## Hypotheses

Asserted, not evidenced. Capped at 0.6 confidence and clearly separated — this section is
the whole reason the report has sections.

- {{statement}} `[claim-xxxx]` — confidence {{confidence}}, would be tested by {{test}}

## Opportunities raised

| Id | Working title | Genre / mechanic | Candidate platforms | Resting on |
|---|---|---|---|---|
| {{id}} | {{title}} | {{genre}} / {{core_mechanic}} | {{candidate_platforms}} | {{claim_refs}} |

Four to eight is healthy. One means the decision was made before the looking started.

## Superseded

Claims this scan replaced, and what changed. Beliefs that moved are as informative as
beliefs that held.

| Old claim | Replaced by | What changed |
|---|---|---|
| {{old}} | {{new}} | {{change}} |

## What was not looked at

Known gaps in the scan. A platform with poor public data is not a platform without
opportunities — it is a platform you have no evidence about, and those are different
statements.

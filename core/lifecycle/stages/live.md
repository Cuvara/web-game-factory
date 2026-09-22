# Live

**Machine** title · **State** `live` · **Kind** AI-assisted · **Role** liveops
**Contributors** analysis, release
**Inputs** `release-manifest`, `platform-publication` · **Outputs** `performance-review`

The title is published. This is an **ongoing condition, not a step** — a title sits here
indefinitely, and the state only changes when a scheduled review decides it should.

## Why analytics is not a stage

Analytics is a continuous data feed. There is no moment at which a game "is in analytics".
Modelling it as a stage produces a lifecycle where a live game must leave the live state to
be measured, which is nonsense.

The **review** is the step. It runs on a schedule:

```
D1 → D7 → D30 → every 30 days
```

Each run emits a `performance-review` whose `decision` drives what happens next:

| Decision | Effect |
|---|---|
| `iterate` | → `production` for a content or tuning release |
| `scale` | self-loop, behind gate **G7** (paid campaign) |
| `hold` | self-loop, no action |
| `sunset` | → `sunset`, after sustained underperformance |

A regression or urgent fix takes the `hotfix` edge back to `releasing`.

## Liveops owns this

The `liveops` role exists because nobody owned it before. The `sdk` role integrates the
analytics SDK; **interpreting the data** was assigned to no one, which left the factory's
entire "learns from what it ships" premise without an owner.

## What flows back

`performance-review.emitted_claims` writes claims into the portfolio backlog. That is how
shipping one game improves the next opportunity scan — a **data edge to discovery, not a
control transition**. Nothing about a live title transitions the portfolio; new evidence
simply raises or lowers confidence in genre and mechanic hypotheses the next scan reads.

This is the correction to the original workflow's `ITERATION → MARKET INTELLIGENCE` arrow,
which drew a data dependency as a control edge and made a system that is really two
independent loops look like one circle.

## Failure modes

- **Reviewing without the strategy open.** Success criteria set at strategy time are the
  only honest yardstick; targets invented after seeing results are not targets.
- **Iterating on a game that should sunset.** The `sunset_floor` exists to make that
  decision in advance rather than by attrition.
- **Letting reviews lapse.** An unreviewed live title is an unmanaged liability, and its
  data is the input the next opportunity scan is missing.

# Analytics and feedback loops

How the Factory measures its games and learns from them, so that each new title is chosen,
designed and built with evidence from the last. Grounded in:
- `core/artifacts/performance-review.schema.json`;
- `core/lifecycle/title.machine.yaml` (state `live`);
- `scripts/wgflib/guards.py`;
- `scripts/wgf_knowledge/`;
- the template's play probe.

Labels: [C] confirmed, [I] inferred, [U] unknown.

## 1. The loop, and where it is broken today

```
Research -> Concept -> Design -> Level design -> Implementation -> QA -> Publication
   ^                                                                          |
   |                                                                          v
Future research <- Improvement <- Diagnosis <- Performance review <- Portal reports
```

| Link | Exists | Broken because | Label |
|---|---|---|---|
| Publication -> portal reports | portals report | nothing imports them | [C] |
| Portal reports -> performance review | schema and guards exist (`below_sunset_floor`, `campaign_budget_approved`) | no `wgf_live` step; free-form `metrics[]`, no vocabulary | [C] |
| Performance review -> diagnosis and improvement | `title:live` transitions iterate/scale/hold/sunset | never exercised | [C] |
| Build and QA findings -> lessons | `wgf knowledge ingest/candidates/promote`; 29 lessons, 15 enforced | `workspace/lessons/candidates.yaml` is empty; every lesson was written by hand | [C] |
| Lessons -> next run | knowledge-contract pinned per run; the agent design author must trace it | works only with the agent author | [C] |
| Outcomes -> research and scoring | - | **does not exist**: discovery never reads outcomes; weights unvalidated | [C] |
| Human audits -> gates | quality-gap audit, K6 retro | 0 of 11 human findings were caught by a gate; human findings are not gate inputs | [C] |

The two missing links that matter most: **portal reports in**, and **outcomes into research and
scoring**.

## 2. Measurement

The principle: **the portal's own report is the source of truth for revenue and players. Offline
bot sessions are the source of truth for how many ad opportunities a build offers.**

### 2.1 Why not in-game telemetry

- GamePix forbids external analytics, and GameDistribution forbids third-party tracking. Y8 and
  Yandex forbid external links and foreign scripts
  ([monetization-and-distribution.md](monetization-and-distribution.md) Part A).
- The template's `packages/analytics-sdk` has no sink. The Factory wires it to a `NullSink`
  ([factory-audit.md](factory-audit.md) §7, T8 and F10).
- A self-hosted collector would need consent handling, hosting and a privacy policy per portal,
  and could get a game rejected.

So portal builds keep the `NullSink`. Gameplay events stay available to tests and the play probe
only, never to a network.

**Event vocabulary.** These names are already emitted by the Factory's gameplay layer
(`scripts/wgf_sdk/game/src/platform/gameplay.ts:207-409`):
- `run_start`, `run_stop`
- `game_over`, `level_complete`
- `ad_interstitial`, `ad_rewarded`, `ad_late_reward`
- `save_failed`

New features add `snake_case` events with no personal data.

### 2.2 Native metrics (verbatim, per portal)

| Portal | Native metric | Definition (source) |
|---|---|---|
| CrazyGames | Revenue per 1000 plays | revenue / plays x 1000 (docs.crazygames.com ad-monetization-guide) |
| CrazyGames | eCPM | revenue per 1,000 ads shown (same) |
| CrazyGames | Conversion | share of players active 1+ minute (same) |
| Yandex | Revenue | RUB per day, ads plus purchases (yandex.com/dev/games/doc/en/concepts/metric) |
| Yandex | ARPDAU | revenue per daily active user (same) |
| Yandex | Impressions per player per day | per format: sticky, interstitial, rewarded (same) |
| Yandex | Conversion To Play | share of sessions longer than 60 s (same) |
| Yandex | Retention D1-D14, playtime per player, Rating | (same) |
| Y8 | Revenue Report fields | **undefined publicly**; record the column names exactly as exported |
| GamePix | RPM | **base undefined**; record as exported |
| Poki (if used) | Web Fit: CTR, time on page, conversion | developers.poki.com/guide/web-fit-test |

### 2.3 Derived metrics (ours)

| Metric | Formula | Notes |
|---|---|---|
| `rev_per_1k_plays` | net revenue / plays x 1000 | comparable across portals only with the same "play" definition |
| `rev_per_1k_impressions` (net eCPM) | net revenue / impressions x 1000 | price signal; geo and fill |
| `impressions_per_play` | impressions / plays | the lever the game controls |
| `rewarded_share` | rewarded impressions / all impressions | Yandex reports per format |
| `conversion_60s` | sessions > 60 s / sessions | CrazyGames and Yandex only |
| `median_session_s` | portal metric | do not reconstruct |
| `d1`, `d7`, `d30` | returning / new on day N | only where reported (Yandex D1-D14) |
| `net_contribution` | net revenue - attributed costs | costs from metered spend and hours |

```
rev_per_1k_plays = impressions_per_play x net_eCPM_per_impression x 1000
```

The identity separates "few impressions per play" (our game and placements) from "low price per
impression" (geo, fill, launch stage).

### 2.4 Offline metrics (our builds, no players)

Measured by a bot on each target's own packaged build, against that portal's SDK mock, through
`window.__wgf__.usage()` (template `src/core/probe.ts`).

| Metric | Definition | Use |
|---|---|---|
| `ad_opportunities_per_session` | interstitial requests + rewarded offers shown per scripted session | catches zero-opportunity builds |
| `rewarded_offer_reachable` | an offer becomes visible at least once on a fail path | same |
| `interstitial_in_play` | interstitial requests while `gameplayActive` | must be 0 |
| `ad_after_action_ms` | delay from click to request | Yandex forbids > 2000 ms |

### 2.5 The portal-report record

The proposed instance shape (roadmap P2-04), stored per title as `observed` claims citing the raw
export:

| Field | Meaning |
|---|---|
| `title_id`, `platform_id`, `game_ref` | which game on which portal |
| `period_start`, `period_end`, `exported_at` | window and read time |
| `build_ref`, `launch_stage` | live build; review / basic-launch / full-launch / published |
| `currency`, `native_metrics{}` | each exported column under its own name, with unit |
| `plays`, `impressions{kind}`, `revenue_net` | normalized where exported; null otherwise |
| `geo[]` | top countries, if exported |
| `source` | export file name and content hash |
| `notes` | estimated, delayed, partial |

No player identifiers are stored.

### 2.6 Reporting workflow

A stdlib script reads the records and prints a markdown report per title, per portal and for the
portfolio:
1. revenue in native currency and USD at a recorded rate;
2. the derived metrics where denominators exist ("n/a" otherwise);
3. launch stage and sample size beside each figure, with fewer than 1,000 plays marked
   "insufficient sample";
4. conversion, median session, D1/D7;
5. revenue concentration;
6. net contribution.

There is no service and no hosting. The report fills `performance-review.metrics`.

### 2.7 Experiments

**What portals allow.** Portals report aggregates per game, so randomized in-game splits would
need our own assignment and measurement, which the tracking bans rule out. In order of evidence
strength:
1. Portal-native experiments (Yandex remote flags, if verified).
2. An interrupted time series on one portal.
3. A cross-portal comparison, used only to generate hypotheses.

**Protocol:**

| Element | Rule |
|---|---|
| Hypothesis | one change, one direction, one primary metric |
| Control and treatment | named builds (commit and package hash) |
| Primary metric | usually `impressions_per_play`, `rev_per_1k_plays` or `conversion_60s` |
| Guardrails | conversion, median session, D1, portal rating |
| Sample size | Poisson for impressions per play: plays per arm ~ 16 / (rate x d^2) for relative change d at 80% power, 5% two-sided (rate 0.5, d 20% gives ~800; rate 0.1 gives ~4,000). Proportions: n ~ 16 p(1-p) / delta^2. Overdispersion raises both. |
| Minimum window | 14 days per arm; never across a launch-stage change |
| Decision rule | ship if the primary improves beyond its 95% interval and no guardrail falls |
| Rollback | re-upload the control build |
| Record | `performance-review.experiments[]`, citing portal-report records |

**Candidate experiments, after P0 data exists:**

| ID | Hypothesis | Primary | Guardrails |
|---|---|---|---|
| E1 | A rewarded offer at a near-win fail raises impressions per play without lowering D1 | impressions_per_play | D1, conversion |
| E2 | Moving the first interstitial to the third clear raises conversion past 60 s | conversion_60s | rev_per_1k_plays |
| E3 | Reaching first input in under 5 s raises conversion | conversion_60s | median session |
| E4 | Stars or par medals per level raise playtime | median session | D1 |
| E5 | A second rewarded use (hint or booster) adds impressions | impressions_per_play | rating, D1 |

## 3. Closing the loop

### 3.1 Portal reports into performance reviews

1. Import each portal export as a portal-report record (the record shape in §2 above). The
   person exports, the script reads.
2. `wgf_live` (proposed step module) drafts the day 1/7/30 performance review:
   - it fills `metrics[]` from the vocabulary;
   - it evaluates `vs_success_criteria` and `sunset_floor` with the existing guards;
   - it proposes iterate, scale, hold or sunset.
3. A person decides. G7 (spend) stays human-only.

### 3.2 Outcomes into research and scoring

- Each portal-report record carries the title's opportunity id and archetype.
- A small calibration script joins outcomes with the opportunity's scored dimensions. Once at
  least 5 titles have Full-Launch-stage data, it reports which dimensions predicted playtime and
  `rev_per_1k_plays`.
- The result is a proposed `portfolio-default.v2/v3.yaml`, a new file reviewed by a person. Never
  an in-place edit.
- Discovery's market cells gain an `observed_outcome` input: our own titles' results in that cell,
  as `observed` claims.

### 3.3 Findings into lessons, automatically proposed

- After each G4 and each portal review, the run records three kinds of finding: human findings,
  portal rejection reasons, and post-release defects (like D1, D2, the Y8 zero-ads build).
- `wgf knowledge ingest` turns each into a candidate. Today this step depends on someone running
  it.
- A defect that escaped a gate creates a candidate with `guarded_by: none`, so the gap is visible
  in `check-tiers.yaml`.
- `wgf decide --lesson` at G4 (documented as not yet existing, `docs/knowledge-enforcement.md:795-800`)
  is the cheapest capture point.

### 3.4 Human findings as gate inputs

- A G4 `iterate` with findings already routes through triage (`docs/specialist-routing.md`).
- Extend the same path to post-release defects and portal feedback, so a portal rejection reason
  becomes a typed finding with an owner.

## 4. What the factory should learn, and how it would know

| Question | Evidence | Minimum data |
|---|---|---|
| Which genres reach the portal playtime bars at our scope | CrazyGames playtime and conversion per title | 3 titles per family in Full Launch |
| Which design patterns hold players | per-title playtime, D1 (Yandex), versus design features | 5 titles; before/after on one title is correlational |
| Which level structures work | naive-bot fail curves versus portal playtime | needs per-level data the portals do not give; use playtests |
| Which visual styles earn clicks | Poki Web Fit CTR (if used), list position | weak; mostly unobservable without Poki |
| Which SDK integrations fail | portal QA tools, rejection reasons, live ad checks | every title |
| Which publishing approaches work | approval rate, time to approval, Full Launch rate | every title |

## 5. Rules against unsupported conclusions

- No conclusion from fewer than 1,000 plays, or from a window that includes review or Basic
  Launch.
- Cross-portal comparisons are hypotheses, never causal results.
- A before/after change on one portal is correlational unless the portal randomizes.
- Each figure is reported with its denominator, window, launch stage and sample size.
- Calibrating weights needs at least 5 titles with outcomes. With fewer, show the data and change
  no weights.

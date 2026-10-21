# WebGameFactory: end-to-end factory and revenue plan (2026-10-21)

A repository-grounded audit and roadmap for the whole lifecycle:
- research, concept, design and level design;
- implementation, QA and CI;
- monetization and multi-network distribution;
- analytics, feedback and portfolio economics.

This is planning only. No code, configuration, build, portal state or paid call was changed or
made to produce it, and no test was run for it.

Labels used throughout: [C] confirmed in code or record, [I] inferred, [U] unknown. Market
sources carry a tier (OFFICIAL / 3P / COMMUNITY) and the access date 2026-10-21.

## Documents

| Document | Holds |
|---|---|
| [factory-audit.md](factory-audit.md) | 13-stage audit matrix (code vs evidence maturity), defect escapes, wasted spend, cost visibility, CI reality, and the traced monetization path |
| [market-research-strategy.md](market-research-strategy.md) | Research workflow, competitive analysis rules, opportunity scorecard v2 proposal with vetoes and limitations, portfolio rules |
| [game-design-improvements.md](game-design-improvements.md) | The ten design questions against the schema, portal-derived targets, measured kill metrics, retention features by genre |
| [level-design-improvements.md](level-design-improvements.md) | The content-depth gap, solvability for every unit, naive-play difficulty, generators with human acceptance, minimum evidence before publication |
| [monetization-and-distribution.md](monetization-and-distribution.md) | Network facts and AI policies, capability matrix, ranked opportunities, ad fit by genre, SDK changes, release-readiness checklist, why complete games fail |
| [analytics-and-feedback-loops.md](analytics-and-feedback-loops.md) | The closed loop and its broken links, metric dictionary, portal-report record, experiments, small-sample rules |
| [qa-and-ci-improvements.md](qa-and-ci-improvements.md) | Validation tiers, browser-QA and ad-lifecycle additions, baseline gate, confirm-before-routing, agent canary, CI cost |
| [portfolio-economics.md](portfolio-economics.md) | Cost per game, metering gap, break-even scenarios, improve vs new, concentration risk, prioritization formula, not-yet list |
| [implementation-roadmap.md](implementation-roadmap.md) | P0-P3 initiatives with evidence, acceptance, tests, effort, risk and metrics; ad evidence states; critical path; milestones; authorization table |
| [p0-execution-plan.md](p0-execution-plan.md) | The eight findings re-checked against code, the P0-01..P0-07 execution plan, what is blocked externally, and the recommended first batch |

### Mapping from the earlier package (same day)

| Earlier file | Now in |
|---|---|
| monetization-audit.md | factory-audit.md §7 |
| monetization-research.md | monetization-and-distribution.md Part A |
| genre-monetization-matrix.md | monetization-and-distribution.md Part C (ads); game-design-improvements.md §5 (retention) |
| monetization-metrics.md | analytics-and-feedback-loops.md §2 |
| revenue-optimization-roadmap.md | implementation-roadmap.md; scenarios in portfolio-economics.md §2 |

## Executive summary

### 1. The five most important confirmed weaknesses

1. **Research does not choose what gets built.**
   - The teardown corpus is empty, and the 22 snapshots all date from 2026-09-23.
   - G1 is not in the `new-game` workflow.
   - Both validation games started from hand-written briefs.
2. **People, not the Factory, made the games presentable.**
   - Brick Breaker Worlds went from 12 to 32 levels, and Sky Marble from 6 corridors to 12
     courses, outside the workflow.
   - A later automated loop "made gates pass and games worse" and caught 0 of 11 human findings.
3. **Content depth is far below what portals reward.**
   - All designed content is 854 s (BBW) and 345 s (SM). The Factory's release bar is 300 s.
   - CrazyGames decides Full Launch on average playtime, D1 and conversion. It publishes what
     successful titles often see: 10+ minutes, D1 10-15% and 80% conversion past one minute.
     These are benchmarks, not fixed thresholds. Poki's final review targets 5+ minutes.
   - Total designed content is not measured player behaviour. A player who stops early never
     plays it all, and replays can extend it. Only portal data shows real average playtime.
4. **What shipped bypassed the gates, and the gates missed real defects.**
   - Both games were packaged and submitted by hand, outside G4/G5/G6 and the quality gate.
   - The Y8 builds made zero ad calls, and the GamePix builds still do. The check that should
     catch this reads the same placements, so it is circular.
   - Landscape-phone clipping and a fatal single asset failure also escaped.
5. **No measurement after launch, and most spend unmetered.**
   - There is no `wgf_live` step and no portal-report import.
   - Only developer sessions record cost. All-in AI spend is about US$250-320 per game [I], and
     human hours are unrecorded.

### 2. The five highest-value improvement opportunities

1. **Make the existing builds able to earn** (P0-01, P0-02).
   - Confirm real ads on Y8 after approval.
   - Fix the GamePix placements before that submission.
2. **Deepen BBW and SM content and add a mastery layer before CrazyGames judges them** (P1-01,
   P1-02). Full Launch is the only stage where CrazyGames pays, and it is judged on playtime.
3. **Close the defect classes in the Factory** (P0-03, P0-04, P1-04, P2-02, P2-03):
   - a per-target ad gate derived from the profile;
   - the portal pause rule;
   - landscape and fault-injection browser QA;
   - solvability for every unit;
   - bot-exercised ads.
4. **Choose the next game on evidence** (P1-05 .. P1-08):
   - a seeded teardown corpus;
   - G1 inside the workflow;
   - a differentiation field against reskin rejections;
   - kill metrics measured by a stranger playtest at G4.
5. **Meter everything and import portal reports** (P0-05, P2-04, P2-05). Without these, every
   portfolio decision rests on estimates.

### 3. The most important multi-network distribution findings

- **Gates before ads.**
  - CrazyGames serves no ads in Basic Launch, which ends once a game has been live for at least
    7 days and has reached at least 500 plays (OFFICIAL). A 3P summary adds a 21-day maximum,
    which the official page does not state.
  - Y8 serves test creatives in review.
  - Yandex has paused new-game submissions.
  - The reported Y8 RPM is therefore review-period noise from builds without ads.
- **AI policy is an acceptance risk at volume.**
  - Y8 rejects "mass-generated" and "repeatedly reskinned" games.
  - Poki may ask for prompts and iterations.
  - Yandex bans interactive AI.
  - GamePix's dashboard forbids AI-written descriptions.
- **Ranked opportunities:**
  1. CrazyGames Full Launch;
  2. Y8 with working ads;
  3. Yandex once it reopens;
  4. GamePix;
  5. Playgama (open, non-exclusive, reaches MSN and YouTube Playables), still to evaluate;
  6. GameDistribution.
- **Poki** stays deferred (web-exclusive). Telegram, Discord and Facebook Instant are poor fits.
- **Every target bans foreign ads and most ban third-party tracking.** Monetization means each
  portal's SDK; measurement means each portal's reports.

### 4. The most important research, game design and level design changes

- **Research:**
  - 10+ teardowns per candidate genre;
  - a monthly snapshot refresh;
  - G1 with coverage and veto enforcement;
  - scorecard v2 with portal-benchmark feasibility, content cost per minute and a reskin-risk
    veto.

  The scorecard is not a revenue predictor until calibrated on at least 5 titles.
- **Design:**
  - a differentiation field;
  - portal-derived targets;
  - kill metrics measured at G4;
  - brief features cannot vanish silently;
  - blocking breaches route back to design instead of ending the run.
- **Levels:**
  - content bars derived from the strictest target portal;
  - the bot must win every unit;
  - naive-play fail curves;
  - the level critic's baseline mode held at the release tier;
  - parametric generators with human acceptance per group;
  - distinct climax art.

### 5. The most important monetization and analytics changes

- **Monetization:**
  - a profile-derived per-target ad hard gate;
  - pause scope as profile data;
  - template ad and boot hangs fixed, and GamePix at the pin;
  - bot-exercised ad lifecycle on every target build;
  - an ad opportunity estimate in design.
- **Analytics:**
  - a portal-report record and stdlib import;
  - a metric dictionary that keeps each portal's definitions;
  - a `wgf_live` step that drafts the day 1/7/30 reviews;
  - outcomes fed into scoring calibration and lesson candidates;
  - experiments with guardrails and minimum samples.

### 6. The first implementation milestone

**M1: see and stop the bleeding** (P0-01 .. P0-07). Exit criteria:
- real ads observed on Y8;
- GamePix packages carry placements;
- the per-target ad gate and pause scope merged;
- every agent session metered;
- every live build traceable to a release manifest;
- the template hangs fixed at a new pin.

Dependencies:
- the owner's portal logins;
- Y8's approval of Build 003;
- a template release;
- Core v1 module validation for the Factory changes (test-core and both goldens on Linux CI).

### 7. The metrics that will demonstrate commercial improvement

Per portal, after review and launch stages, always with denominator and sample size:
- approval rate and CrazyGames Full Launch rate;
- average playtime and conversion past 60 s;
- D1 (Yandex);
- ad impressions per play;
- net revenue per 1,000 plays;
- metered cost per title;
- net contribution per title;
- defect escapes per title.

### 8. The key unknowns needing data or human approval

- **Data:**
  - the Y8 report denominator and the games' real plays, impressions and geo;
  - whether Build 003 fills real ads;
  - BBW's CrazyGames launch outcome and the unpublished thresholds;
  - when Yandex reopens;
  - GamePix's share, payout and RPM base;
  - real playtime, conversion and D1 for any of our games;
  - the true cost per game (unmetered agents, unrecorded hours).
- **Approval:**
  - portal logins, uploads, submissions and emails;
  - pushes to the game repositories and template releases;
  - Core v1 changes;
  - the opt-in agent canary's spend;
  - stranger playtests.

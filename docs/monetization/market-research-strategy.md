# Market research and opportunity selection

How the Factory should choose which games to build, before it spends money building them. This
document builds on Research V2 ([docs/research-v2.md](../research-v2.md)), whose machinery is
sound. What is missing is evidence, a decision point that uses it, and calibration against real
outcomes.

Labels: [C] confirmed, [I] inferred, [U] unknown. Market sources were accessed on 2026-10-21;
tiers are OFFICIAL, 3P or COMMUNITY.

## 1. Current state

| Element | State | Label |
|---|---|---|
| Discovery engine | Deterministic, claim-traced, five opportunity generators, market cells, about 120 tests (`scripts/wgf_discovery/`) | [C] |
| Teardown corpus | **0 records**: `workspace/research/games/` does not exist; only 6 invented fixtures in `scripts/tests/fixtures/research-v2/games/` | [C] |
| Snapshots | 22 files, all `observed_at` 2026-09-23. Mostly portal documentation; 3 puzzle listings giving 16 listing-depth games with gameplay `unknown` (`docs/research-v2.md:279-287`) | [C] |
| Live evidence | `LiveCollector` exists; off by default (`step.py:159`); no `probes.yaml` | [C] |
| Revenue estimate | Never made ("play counts measure traffic, not revenue", `analysis.py:17,853`); `revenue_potential` (weight 0.14) always unscored | [C] |
| Selection gate | G1 defined in `core/lifecycle/gates.yaml:44-61`, absent from `new-game`; research goes straight to strategy | [C] |
| Validation games | Both started from hand-written `concepts.yaml` briefs (`docs/handoff/2026-10-03-two-game-validation.md:16-18`) | [C] |
| Outcome feedback | None: cost calibration, scoring v2, analytics feedback and a pattern library are listed "not implemented" (`docs/research-v2.md:303-305`) | [C] |

## 2. What the market says matters

These findings change what "a good opportunity" means for this Factory.

1. **Portals gate traffic on engagement.**
   - CrazyGames ends Basic Launch (ads off) once a game has been live for at least 7 days and
     has reached at least 500 plays. It decides Full Launch on average playtime, D1 retention and
     conversion. OFFICIAL, https://docs.crazygames.com/resources/basic-launch-metrics/
   - What "successful titles often see": playtime 10+ min, D1 10-15%, conversion 80%+, load under
     10 s, build below 20 MB. These are **benchmarks, not fixed thresholds**. OFFICIAL, same page.
   - A 21-day maximum for Basic Launch appears only in a 3P summary,
     https://portalready.world/portals/crazygames/
   - Poki's Player Fit Test asks for 3+ min average and 25%+ of plays over 3 min. The final
     review targets 65%+ conversion and 5+ min average (10+ for management and simulation).
     OFFICIAL, https://developers.poki.com/guide/how-testing-works
2. **Originality is an acceptance rule.**
   - Y8 rejects "copied, misleading, low-quality, repeatedly reskinned, or mass-generated games".
     OFFICIAL, https://developer.y8.com/
   - Poki: "AI should empower, not shortcut"; it may ask for prompts and iterations. OFFICIAL,
     https://developers.poki.com/guide/content-player-safety
   - CrazyGames restricts developers who repeatedly submit non-compliant games. OFFICIAL,
     https://docs.crazygames.com/requirements/gameplay/
3. **Genre signals (thin).**
   - CrazyGames: top performers are ".io and action", "puzzle" and "strategy". OFFICIAL,
     https://docs.crazygames.com/faq/
   - CrazyGames US study, May 2025 to May 2026: hypercasual was #1 for 79% of the year. OFFICIAL
     press release,
     https://www.gamespress.com/Browser-game-platform-CrazyGames-releases-extensive-analysis-of-US-bro
   - Poki: car games are 10% of plays. OFFICIAL, https://poki.com/
   - No portal publishes plays by genre in a usable table.
4. **Comparable titles show depth beats polish alone.**
   - Idle Breakout on Poki has 4.4/5 from 46,806 votes. It has prestige, skills, achievements and
     autosave. A classic Brick Breaker on Poki has 5,039 votes.
     https://poki.com/en/g/idle-breakout ; https://poki.com/en/g/brick-breaker
   - Sky Balls 3D on CrazyGames has 79K likes, with "hundreds of levels" and coin-paid skins.
     https://www.crazygames.com/game/sky-balls-3d
   - Votes are not plays and not revenue; they indicate engagement only. [I]

## 3. Proposed research workflow

A repeatable sequence, mostly using tools that already exist.

| Step | What | Tool | Cost | Output |
|---|---|---|---|---|
| R1 | Refresh portal snapshots monthly, and before any new concept | an agent or person fetches pages into `workspace/research/snapshots/` | low (no paid API) | snapshots within TTL |
| R2 | Teardown at least 10 games per candidate genre: top and mid performers on at least 2 portals | `python3 scripts/wgf-corpus.py template <id>`, played by a person; `core/craft/competitive-teardown.md` | about 20-30 min per game, human | `workspace/research/games/*.json` |
| R3 | Run discovery on the corpus | `bin/wgf research` | none | research-report, several opportunities |
| R4 | Score and decide at G1, inside the workflow | scoring model plus a G1 checkpoint | none | evaluation and decision-record |
| R5 | Cheap disproof before full build: a greybox played by 5 strangers against the strategy's kill metrics | existing greybox phase + `docs/mv-4-playtest-protocol.md` | about 1 greybox session + people | G4-style evidence before production spend |
| R6 | Feed outcomes back: portal-report rows into scoring calibration | [analytics-and-feedback-loops.md](analytics-and-feedback-loops.md) | none | calibration data |

### Competitive analysis rules

- Analyze several representative games per genre (top, mid, recent), never one example.
- Separate genre conventions (what every top game has) from differentiators (what only the best
  have). The vocabulary already supports this as `patterns` with prevalence.
- Record what frustrates players: low ratings, review text where visible.
- Reuse mechanics and structure, never assets, names, distinctive expression or branding.

## 4. Opportunity scorecard

The existing model (`portfolio-default.v1.yaml`, 14 weighted dimensions, threshold 0.62, minimum
coverage 0.60) stays. A **v2 file** (never an in-place edit) adds the dimensions and vetoes the
market evidence above calls for. This is a proposal; the weights are starting points.

| Dimension | Measures | Evidence source | Weight (start) |
|---|---|---|---|
| Portal benchmark feasibility | Can the concept plausibly reach 10 min average playtime and 80% one-minute conversion at its scope? | content model x unit duration vs portal benchmarks | 0.12 |
| Content cost per minute of play | Estimated dev and asset cost / designed minutes | genre model, archetype estimates, past runs | 0.10 |
| Demand signal | Category presence, top-list share, votes of comparable titles | snapshots, teardowns | 0.12 |
| Competitive density | Number of comparable titles, quality gap to the top | teardowns | 0.08 |
| Differentiation strength | A named axis on which this game beats the comparables | `patterns.differentiate_on` + design | 0.10 |
| Network access | How many target portals accept it, under which rules | profiles | 0.10 |
| Monetization fit | Natural beats per session, rewarded fit | genre matrix | 0.08 |
| Retention potential | Return reasons available within scope | design | 0.08 |
| Reuse | Share of systems reused from earlier titles | repo | 0.07 |
| Dev speed | Estimated days | archetype estimates, calibrated | 0.08 |
| Tech risk | Engine, 3D, physics | tech plan | 0.07 |

New vetoes:
- `reskin_risk`: the concept differs from an earlier own title only in theme. Y8 and Poki reject
  this.
- `below_portal_floor`: the planned content cannot exceed the Player Fit floor of 3 min average
  playtime.
- `no_teardown_evidence`: fewer than 5 teardowns in the genre.

Rejection thresholds:
- below 0.62 total;
- below 0.60 evidence coverage;
- any veto.

### Limitations

- The score ranks concepts by evidence and feasibility. It is **not a revenue prediction**, and
  is never presented as one.
- Until at least 5 titles have portal outcomes, weights are judgement. Calibration then means
  regressing observed `rev_per_1k_plays` and playtime on the dimensions, and publishing v3 if the
  fit justifies it.
- Votes, likes and list positions are proxies with unknown bias.

## 5. Portfolio rules

1. No two consecutive titles in the same archetype unless the first cleared CrazyGames Full
   Launch or an equivalent bar.
2. A series (shared engine, new content and mechanic) is allowed after a title proves its loop.
   It is not allowed as a substitute for originality (Y8 "repeatedly reskinned").
3. At most half of active titles in one genre family, until evidence favours it.
4. Distribution across at least 3 non-exclusive portals per title; Poki only as a deliberate
   exclusive.
5. Improve a title that cleared Full Launch before starting a new one in the same genre
   ([portfolio-economics.md](portfolio-economics.md)).

## 6. Research tasks to resolve uncertainty

| Question | Method | Owner |
|---|---|---|
| Which genres reach 10 min playtime at our scope | Teardown of 10 top titles per family; record level count, session structure, meta | person or agent with a browser |
| Do breakout and marble genres have room | 10 teardowns each, from the comparables above | person |
| Real Full Launch thresholds | CrazyGames dashboard after BBW's Basic Launch | owner |
| Whether portals accept our AI-assisted titles | Track approval and rejection per title, with reasons | owner |

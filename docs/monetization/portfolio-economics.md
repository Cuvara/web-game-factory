# Portfolio economics

The Factory as a business: what a game costs, what it would need to earn, how to choose between
improving a game and making a new one, and how to prioritize work. Figures come from the run
records. Labels: [C] confirmed, [I] inferred or estimated, [U] unknown.

No revenue figure here is a forecast. Neither game has earned revenue yet: both are in review or
unsubmitted as of 2026-10-21.

## 1. Cost per game

| Cost item | BBW (2D) | SM (3D) | Source | Label |
|---|---|---|---|---|
| Developer sessions, first run | 18, **US$62.86** | 9, **US$29.25** | [docs/benchmark/2026-10-baseline.md](../benchmark/2026-10-baseline.md) §6 | [C] |
| Developer, Oct 5 quality loop | US$64.01 | US$64.60 | `runs:budget-ledger.md:31-35` | [C] |
| Estimated all-in through the Oct 5 loop, including unmetered sessions | US$210-255 | US$180-225 | `runs:budget-ledger.md:37-41` (token-count estimates) | [I] |
| Lead-side specialist subagents, one day | ~US$70-90 | ~US$30-45 | `runs:budget-ledger.md:23-28` | [I] |
| Fresh release-push runs (Oct 18-19) | ~US$1 metered | US$13.94 metered | `runs:release-prep-2026-10-18/portal-records.md` | [C] |
| Design sessions | US$8-10 cap each, unmetered | same | `workspace/config/profiles/autonomous.yaml` | [C] cap, [U] spend |
| Release prep, fixes, store assets, submissions | not recorded | not recorded | - | [U] |
| Human hours (lead, owner, workers) | not recorded | not recorded | - | [U] |
| Factory development (workstreams, reviews) | "not charged to a game" | - | `runs:budget-ledger.md:29` | [U] |

**Working figure.** About **US$250-320 in AI spend per game** to a release candidate [I], plus
unrecorded human time. The model uses US$165 (developer-heavy, low estimate) as a lower bound and
US$300 as a central estimate.

### Metering gap

- Only `developer-session` and `developer-cost` are recorded (`scripts/wgf_develop/budget.py:26-37`).
- Design, review, asset, visual-QA and copy agents run with `--output-format text`, which reports
  no cost.
- Agent processes per game were 139 and 224, mostly assets.
- **Until every agent is metered, cost per game is an estimate.** That makes metering a P0 item.

## 2. What a game must earn

Identity:

```
net revenue per 1,000 plays = impressions per play x net revenue per impression x 1000
```

The scenarios below use **assumptions** bracketing the community reports in
[monetization-and-distribution.md](monetization-and-distribution.md). None is measured for our
games.

| Scenario | Impressions per play | Gross eCPM | Share | Net per 1k plays | Plays to recover US$165 | Plays to recover US$300 |
|---|---|---|---|---|---|---|
| Conservative | 0.3 | US$2 | 50% | US$0.30 | ~550,000 | ~1,000,000 |
| Base | 0.8 | US$4 | 50% | US$1.60 | ~103,000 | ~188,000 |
| Optimistic | 1.5 | US$8 | 50% | US$6.00 | ~27,500 | ~50,000 |

What this tells the plan:

1. **Plays dominate.** A 10x spread in plays per title outweighs any ad tuning. Distribution gates
   (CrazyGames Full Launch, Yandex ranking) are worth more than ad changes.
2. **Impressions per play is the lever the game controls.** It is beats per session x rewarded
   take-up, under the caps, and it rises with playtime. Playtime is also what the portals'
   distribution gates measure, so the two goals align.
3. **At ~US$300 per game, a title needs on the order of 10^5 plays to break even in the base
   case.** Cost per game must fall, and success rate per game must rise, before volume increases.

## 3. Improve an existing game, or make a new one

| Option | Cost (estimate) | What it buys | When it wins |
|---|---|---|---|
| Content-depth pass on a live title (more units through the content contract, a mastery layer) | about US$30-80 of developer spend plus review [I] | higher playtime on a title that already passed review | when the title is in Basic Launch or Full Launch and its playtime is below the benchmark |
| A new title | about US$250-320 plus human time | a new lottery ticket; diversification | when existing titles cleared Full Launch, or were killed on evidence |
| A series entry on a proven engine | below a new title [I] | reuse | only after a title proved its loop; never a reskin (Y8 rule) |

**Recommendation.**
1. No new title until BBW has a CrazyGames Basic Launch result.
2. Spend first on BBW and SM content depth.
3. Use the result to calibrate the next concept's scope.

## 4. Concentration risk

- **Portal.** Revenue will depend on one or two portals at first. The rule is at least 3
  non-exclusive portals per title.
- **Genre.** Both current titles are skill-arcade. The next concept should come from the research
  workflow in a different family unless evidence favours arcade.
- **Account.** CrazyGames allows one game in review at a time, and Y8 applies resubmission
  cooldowns. A quality failure on one title delays others.
- **Policy.** Y8 and Poki reject mass-generated games. A high-volume strategy risks account
  standing, not just single titles.

## 5. Prioritization method

Each initiative is scored 1-3 on six factors:
- expected impact (I);
- evidence strength (E);
- reuse across games (R);
- time to validate (T, 3 = fast);
- reversibility (V);
- risk to compliance and integrations (K, 3 = low risk).

Effort is in engineer-days (D).

```
priority = (I x E x R) x (T + V + K) / 9 / D
```

Ties go to the item that unblocks others on the critical path. The scores are in
[implementation-roadmap.md](implementation-roadmap.md).

## 6. Cost reduction opportunities

| Opportunity | Evidence | Expected effect |
|---|---|---|
| Stop paying for false-positive gates (confirm before routing) | L5, L7, `depth.ramp` noise (`runs:LEAD-STATE.md:152-160`) | fewer wasted developer sessions |
| Protect accepted content from rework | greybox re-entry deleted 12,168 lines (LEAD-STATE:136); fresh runs rewrote 21 files of the accepted build | fewer regressions and repair loops |
| Run the template suite before the first paid session | a stale template test cost a developer session (`runs:TEAM-STATUS.md:65,72`) | no paid environment fixes |
| Calibrate the budget model | both real runs exceeded the derived cap | fewer mid-run human raises |
| Meter everything | unmetered agents | a real cost per game, which every other decision needs |
| Parametric level generation with human acceptance | content was hand-added by people | cheaper minutes of play |

## 7. What not to build yet

| Not yet | Why |
|---|---|
| Shops, soft currencies, IAP | high balance and maintenance cost; no portal data shows that the current genres need them |
| Login rewards, streaks | pressure patterns; no D1 data yet |
| Leaderboards, achievements | no template interface; low value without traffic |
| In-game third-party analytics | banned on GamePix and GameDistribution; restricted elsewhere |
| Telegram, Discord, Facebook Instant | weak fit (crypto CPM, IAP only, declining) |
| Poki | exclusive; deferred by the user |
| Higher title volume | until one title clears Full Launch and cost per game is metered |
| An AI "fun" judge | no evidence it predicts players; adds paid sessions |

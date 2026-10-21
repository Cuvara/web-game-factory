# Monetization and distribution across networks

Which networks the Factory should publish to, what each one requires and pays, how ads should be
integrated, and what makes a released game succeed or fail on a portal. Sources were accessed on
2026-10-21. Tiers:
- **OFFICIAL**: the platform's own documentation.
- **3P**: a third-party summary.
- **COMMUNITY**: a developer report; unverified.

No figure here is a forecast for our games.

Parts:
- A: network facts.
- B: capability matrix and ranked opportunities.
- C: ad and feature fit, and the SDK architecture.
- D: release readiness.
- E: why a complete game still fails.

## Part A: Network facts

### A1. Current targets and integrated portals

Earlier reads by the Factory are in [docs/platform-targets-2026-10.md](../platform-targets-2026-10.md)
(2026-10-04/07) and [docs/platform-sdk-verification.md](../platform-sdk-verification.md). Where
they and this document disagree, re-read the source. Portals change terms without notice.

#### Y8

- **Revenue model.** Y8 Managed Partnership (YMP): 50% of eligible in-game ad revenue; Y8 sells
  the ads, and the developer invoices Y8. AdSense for Platforms (AFP): the developer's own AdSense
  account, for developers Y8 judges eligible. OFFICIAL, https://developer.y8.com/
- **Payout.** Monthly; minimum USD 100 by PayPal or USD 500 by bank transfer; balances roll over.
  OFFICIAL, https://developer.y8.com/
- **Metric definition.** A Revenue Report exists; **Y8 does not publicly define its metrics.**
  Under AFP: Page RPM is earnings per 1,000 page views, and Impression RPM is earnings per 1,000
  ad impressions. OFFICIAL, https://support.google.com/adsense/answer/190515
- **SDK and formats.** `https://cdn.y8.com/minimal-sdk/2-0/y8.min.js`. App ID always; Game ID for
  ads. `showAd({type:'start'|'pause'|'next'|'browse'|'reward'})`. Never request `preroll`.
  Banners only with Y8's per-game approval. OFFICIAL, https://docs.y8.com/sdk/advertising/
- **Cadence.** "Roughly every 180 seconds, configurable per game", SDK-enforced and reported as
  `frequencyCapped`. Rewarded is never capped and restarts the interval. OFFICIAL, same page.
- **Pause rule.** Pause and mute inside `beforeAd`, resume inside `afterAd`. A skipped or capped
  break fires neither. OFFICIAL, same page.
- **Review.** Every game is reviewed. Google test creatives run during review. Resubmission
  cooldowns are 6 h to 5 days. "Games without proper SDK integration may not be eligible for
  monetization." OFFICIAL, https://developer.y8.com/
- **No ads, no revenue.** Staff reply, COMMUNITY:
  https://forum.y8.com/t/how-developers-earn-money-with-id-net/3449 . Ads not showing reported in
  2024, COMMUNITY: https://forum.y8.com/t/ads-are-not-showing-up-in-my-game/59579
- **Restrictions.** No external links, no foreign ads, pop-ups or redirects. Guests must be able
  to play. No encouraged ad clicks. Non-exclusive. OFFICIAL, https://developer.y8.com/games?new=1 ;
  https://docs.y8.com/best-practices/
- **Analytics.** Plays counted at SDK init; the dashboard only. OFFICIAL,
  https://docs.y8.com/sdk/analytics/

#### CrazyGames

- **Revenue model.** A revenue share with no published percentage. Earnings depend on
  "engagement, retention, and overall popularity, as well as advertiser demand". OFFICIAL,
  https://docs.crazygames.com/faq/
  - Optional two-month web exclusivity after Full Launch raises pay by 50%. 3P,
    https://portalready.world/portals/crazygames/
- **Payout.** Monthly from EUR 100, by wire or PayPal. OFFICIAL, FAQ.
- **Metric definition.** "Revenue per 1000 plays: your primary monetization metric." eCPM means
  revenue per ad shown. Impressions per play follow playtime and conversion past 1 minute.
  OFFICIAL, https://docs.crazygames.com/resources/ad-monetization-guide/
- **SDK.**
  - Ads: `CrazyGames.SDK.ad.requestAd('midgame'|'rewarded', {adStarted, adFinished, adError})`.
  - Errors: `adsDisabledBasicLaunch`, `unfilled`, `adblock`, `adCooldown`, `other`.
  - Game events: `gameplayStart/Stop`, `happytime`, `loadingStart/Stop`.

  OFFICIAL, https://docs.crazygames.com/sdk/video-ads/ ; https://docs.crazygames.com/sdk/game/
- **Ad rules.** OFFICIAL, https://docs.crazygames.com/requirements/ads/
  - At most one midgame per 3 minutes.
  - No chained rewarded ads for one reward; reward only on `adFinished`.
  - Banners only on screens held 5+ s, at most 2, never in gameplay.
  - No ads on navigation buttons; no surprise ads.
- **Launch stages.** Basic Launch has **ads disabled**. Full Launch comes "after strong
  performance". See A4. OFFICIAL, FAQ.
- **Restrictions.** Non-exclusive. Revenue needs Full Launch, the current SDK, no non-SDK ads and
  no other portal's branding. OFFICIAL / 3P.
- **Analytics.** Plays, revenue, engagement, geography. OFFICIAL, FAQ.

#### Yandex Games

- **Revenue model.** RTB across partner networks; **no published share**. An impression counts
  when at least 50% of the ad is on screen for 2 s. OFFICIAL,
  https://yandex.com/dev/games/doc/en/console/adv-monetization
- **Payout.** By status and country, for example 3,000 RUB / USD 150 / EUR 100. Paid within 20
  working days of the following month. OFFICIAL, same and https://yandex.com/dev/games/doc/en/payments
- **Metrics.** Revenue (RUB/day), ARPDAU, impressions per player per day by format, Conversion To
  Play (sessions over 60 s), D1-D14, playtime, Rating 0-100. **No RPM.** OFFICIAL,
  https://yandex.com/dev/games/doc/en/concepts/metric
- **SDK.** `ysdk.adv.showFullscreenAdv`, `showRewardedVideo`, `showBannerAdv`;
  `LoadingAPI.ready()`; `GameplayAPI.start/stop`. OFFICIAL,
  https://yandex.com/dev/games/doc/en/sdk/sdk-adv
- **Cadence.** Fullscreen frequency is controlled by Yandex; rewarded "as often as you want". Do
  not hard-code a cap; read `wasShown`. OFFICIAL, sdk-adv.
- **Forbidden.** Ads during gameplay; timer ads; an ad more than 2 s after the player's action.
  OFFICIAL, https://yandex.com/dev/games/doc/en/requirements/4/4
- **Restrictions.** SDK ads only; no external links except the title's own communities; cross-promo
  only through the SDK. Moderation takes 3-5 working days. Games rated below 30 after 3 weeks can
  be removed. OFFICIAL, https://yandex.com/dev/games/doc/en/concepts/requirements
- **Remote config / experiments.** Reported in the SDK; **to verify**.

#### GamePix

- **Revenue model.** "50% revenue share on net revenues"; an "RPMs Revenue-per-Game" dashboard.
  OFFICIAL, https://partners.gamepix.com/developers . Other sources say 45%, and the Factory's
  profile records the question as unresolved. **Uncertain.**
- **Payout.** Threshold and schedule not published.
- **Metric definition.** The RPM base is undefined. Reviewers report removed reports and payout
  mismatches. COMMUNITY, https://www.trustpilot.com/review/www.gamepix.com
- **Ad rules.** OFFICIAL, https://partners.gamepix.com/guidelines/submission
  - Interstitials between levels only; no timer ads.
  - Rewarded must be disclosed and skippable.
  - Pause audio during ads.
  - Only the GamePix and Xsolla SDKs; **no external analytics or ad networks**; no external links.
- **Exclusivity.** None. OFFICIAL, developers page.

#### GameDistribution

- **Revenue model.** 33% of Net Revenue. OFFICIAL,
  https://static.gamedistribution.com/terms/developer.html
- **Payout.** Within 60 days of the monthly report, from EUR 100. OFFICIAL. The FAQ reportedly
  conflicts with this. 3P.
- **SDK.** `gdsdk.showAd()`; `preloadAd('rewarded')` then `showAd('rewarded')`; reward on
  `SDK_REWARDED_WATCH_COMPLETE`. OFFICIAL,
  https://github.com/GameDistribution/GD-HTML5/wiki/Rewarded-Ads
- **Restrictions.** No third-party ads, purchases or tracking. The build must match its latest
  version elsewhere. OFFICIAL, Terms.

#### Google H5 Games Ads, GameMonetize, Newgrounds

- **Google H5 Games Ads.** The Ad Placement API (`adBreak`) is by application and needs AdSense.
  It is the mechanism under Y8's AFP. It cannot be used inside portal builds, which all ban
  foreign ads. OFFICIAL, https://developers.google.com/ad-placement/docs/placement-types
- **GameMonetize.** 45%, Net 30, minimum USD 30. OFFICIAL, https://gamemonetize.com/faq
- **Newgrounds.** A legacy page-view share, about USD 0.30 per 1,000 views. COMMUNITY,
  https://newgrounds.fandom.com/wiki/Revenue_Sharing

#### Community revenue reports (unverified, never targets)

| Report | Figure | Source |
|---|---|---|
| CrazyGames, ~2018 games | EUR 556.92 from 451,327 plays (~EUR 1.20 / 1k plays) | COMMUNITY via https://app.cinevva.com/guides/web-game-monetization |
| CrazyGames | "50k plays ~ USD 250" | COMMUNITY via https://pixelgamecraft.com/blog/html5-game-income/ |
| GameDistribution 2019-21 | ~EUR 0.3-0.9 / 1k plays | COMMUNITY |
| GamePix | ~EUR 3.75 / 1k plays implied | COMMUNITY, Trustpilot |
| Web eCPM, gross | rewarded US 15-28 / EU 8-15 / tier 3 1-3 USD; interstitial US 3-12 / EU 2-8 / tier 3 0.5-2 USD; vendors disagree 2-3x | 3P https://pixelgamecraft.com/blog/html5-game-income/ ; https://www.applixir.com/blog/ecpm-optimization-for-web-games-benchmarks-and-fixes/ |
| Ad blocking | ~27-30% of internet users (eyeo, GWI); no portal publishes its own rate | 3P https://backlinko.com/ad-blockers-users |

#### Cross-portal rules

1. Ads only through each portal's SDK; no generic ad network inside portal builds.
2. No third-party tracking (GamePix, GameDistribution); restricted on Y8 and Yandex.
3. No timer ads, no ads during play, no surprise ads.
4. Launch-stage gating: CrazyGames Basic Launch and Y8 review serve no real ads.
5. Multi-portal publishing is allowed everywhere except Poki's revenue-share deal.
6. "RPM" differs per portal; never compare without the denominator.

#### Open questions for the portals

| Question | Ask | Channel |
|---|---|---|
| Y8's RPM denominator and reporting lag | Y8 | developers@y8.com |
| GamePix share, payout threshold, RPM base | GamePix | dashboard / support |
| Yandex revenue share; remote flags for experiments | Yandex | games-partners@yandex-team.com |
| CrazyGames Basic Launch thresholds for our genres | CrazyGames | developer portal |

### A2. Further channels

| Channel | Access | Revenue model | SDK / format | Exclusivity | Notes | Source |
|---|---|---|---|---|---|---|
| Poki | Curated application; hand-picked; limited daily releases. Pipeline: playtests, Player Fit Test (500 players, 3+ min average, 25%+ over 3 min), Web Fit Test (~10,000 players; CTR, time on page, conversion vs category), final review 1-2 weeks | 100% on own-sourced traffic; 50/50 on Poki traffic | Poki SDK | **Web-exclusive** (Steam, app stores excepted) | Declines for bugs, size, confusing UX, poor graphics, low originality "even if it functions well". Deferred by the user | OFFICIAL https://developers.poki.com/guide/how-testing-works ; https://developers.poki.com/guide/working-with-poki ; https://developers.poki.com/guide/web-fit-test |
| Playgama | Open; feedback within 24 h | 70% of net up to $1,000 a month; $700 + 80% to $3,000; $2,300 + 90% above ("net" undefined) | Playgama Bridge SDK | Non-exclusive | Claims 450M+ players across 100+ partners including MSN and YouTube Playables (Playables: under 30 MB, portrait) | OFFICIAL https://playgama.com/developers ; https://playgama.com/publish-your-game-on-youtube-playables/ |
| Coolmath Games | Submission form | Non-exclusive licence fee you propose | HTML5, no ads, no external links | Non-exclusive | "Thinking" games only (logic, strategy), no violence | OFFICIAL https://www.coolmathgames.com/submit-a-game |
| Lagged | Open | 50% via your own AdSense | Lagged SDK | Not stated | Claims 20M gamers | OFFICIAL https://lagged.dev/ |
| GameMonetize | Open, editor check | 45% (90% only as own-site publisher); NET-30; min $30 | interstitial | Non-exclusive | External links allowed | OFFICIAL https://gamemonetize.com/faq |
| itch.io | Open, no curation | Sales and donations only; no browser-game ads | any | none | AI disclosure field; scouting surface for Coolmath and Addicting Games | OFFICIAL https://itch.io/docs/creators/quality-guidelines |
| Armor Games | Email | Branding deals, IAP, timed exclusivity | HTML5 | Optional | Curated | OFFICIAL https://developers.armorgames.com/docs/introduction/overview/ |
| Addicting Games | Upload | FAQ says the payment programme is discontinued ("for exposure"); company site contradicts | HTML5 | - | Uncertain | OFFICIAL https://www.addictinggames.com/about/upload |
| Telegram Mini Apps | Open | AdsGram CPM 0.5-1 USDT by country; min $100 in USDT; Stars | Mini App | - | Reach fell from 1.44B (Sep 2024) to ~150-190M (mid-2025, 3P); crypto payouts | OFFICIAL https://docs.adsgram.ai/publisher/ ; 3P https://gameworldobserver.com/2025/04/04/telegram-mini-apps-monetization-top-games-features |
| Discord Activities | Open | In-app purchases only | Embedded App SDK | - | No ads: poor fit | OFFICIAL https://docs.discord.com/developers/monetization/implementing-iap-for-activities |
| Facebook Instant Games | App Review with Zero Permissions since 2025-08-01 | Ads and IAP | SDK v8 | - | Declining; Unity dropped support | OFFICIAL https://developers.facebook.com/documentation/games/build/zero-permissions/onboarding-and-migration/overview.md |
| MSN Games, Samsung, Kizi, Miniclip | Partner or contact only | - | - | - | Effectively closed to a small studio; MSN reachable via Playgama (vendor claim) | COMMUNITY / OFFICIAL, see research |
| GamePush | Not a portal: one SDK for many portals | SDK free, backend paid | unified | - | Overlaps with the template's adapter layer; not needed | OFFICIAL https://gamepush.com/overview/ |

### A3. AI-generated and mass-produced games

This is the policy that matters most for an AI-assisted factory.

| Portal | Rule | Source |
|---|---|---|
| Y8 | AI tools allowed if the final game meets the quality rules; rejects "copied, misleading, low-quality, repeatedly reskinned, or mass-generated games", "duplicate games, simple reskins, small visual changes, or many low-quality games made from the same template" | OFFICIAL https://developer.y8.com/ |
| Poki | "AI should empower, not shortcut"; templates and asset flips are not original work; may ask for "creation process, prompts, and iterations"; AI levels allowed if hand-tested; no AI watermarks or untested AI content | OFFICIAL https://developers.poki.com/guide/content-player-safety |
| CrazyGames | No AI-specific rule; originality of names, assets and content required; repeated non-compliance restricts future submissions | OFFICIAL https://docs.crazygames.com/requirements/gameplay/ |
| Yandex | Requirement 23: interactive AI in games prohibited; pre-generated AI material allowed | OFFICIAL https://yandex.com/dev/games/doc/en/concepts/requirements |
| GamePix | The dashboard's description field says "Do not use AI-generated text" (observed in `runs:release-prep-2026-10-18/portal-records.md`); not found in the public guidelines | observed / OFFICIAL guidelines silent |
| itch.io | Generative-AI disclosure tagging | OFFICIAL https://itch.io/docs/creators/quality-guidelines |

**Consequences for the Factory:**
1. Every title must be a distinct game, never a re-theme. This becomes the `reskin_risk` veto in
   [market-research-strategy.md](market-research-strategy.md).
2. Keep a provenance log of prompts and iterations per title. The Factory's run records already
   hold most of it; package them on request.
3. No live LLM features in games (Yandex ban).
4. Generated levels are hand-tested ([level-design-improvements.md](level-design-improvements.md) L5).
5. Store copy for GamePix is human-written; elsewhere it is reviewed by a person.

### A4. What drives traffic once accepted

| Portal | Mechanism | Source |
|---|---|---|
| CrazyGames | Basic Launch (ads off) ends after at least 7 days live and at least 500 plays (a 21-day maximum is 3P only, portalready.world). Full Launch is decided on average playtime, D1 and conversion. What "successful titles often see" (benchmarks, not fixed thresholds): 10+ min, 80%+ conversion, D1 10-15%, load under 10 s, build under 20 MB. Mobile homepage only for 20 MB or less | OFFICIAL https://docs.crazygames.com/resources/basic-launch-metrics/ ; https://docs.crazygames.com/requirements/technical/ |
| Yandex | ML ranking on card completeness, rating, sessions, duration, returning players, revenue. "Popular" is hand-picked: mobile and desktop, RU and EN, good promo, good metrics, various SDK methods, replies to reviews | OFFICIAL https://yandex.com/dev/games/doc/en/concepts/ranking-and-featuring |
| Poki | Web Fit Test against the category average | OFFICIAL, see A2 |
| GameDistribution | Editor's Picks: 10 a week on revenue, gameplay, ad score, session length | 3P https://blog.gamedistribution.com/editor-pick-publisher-network/ |
| GamePix | Not published; "Allow Distribution" adds partner sites | 3P |
| Y8 | Not published; Y8 picks a screenshot as the thumbnail at approval | observed |

## Part B: Capability matrix and ranked opportunities

### B1. Capability matrix

| | Y8 | CrazyGames | Yandex | GamePix | GameDistribution | Playgama | Poki |
|---|---|---|---|---|---|---|---|
| Status for us | in review | BBW awaiting review | submissions paused | not submitted | integrated, not targeted | not integrated | deferred |
| Template adapter at the pin | yes | yes | yes | **no** (v1.2.2) | yes | no | yes |
| Interstitial / rewarded | yes / yes | yes / yes | yes / yes | yes / yes | yes / yes | via Bridge | yes / yes |
| Banner | on approval | rules apply | sticky via console | no | no | - | no |
| Native retention metrics | none public | playtime, conversion, D1 | D1-D14, conversion, rating | unclear | revenue report | - | Web Fit metrics |
| Revenue share | 50% (YMP) | unpublished | unpublished | 50% or 45% (unresolved) | 33% of net | 70-90% ladder | 50/50 on Poki traffic |
| Payout minimum | $100 PayPal | EUR 100 | by country (e.g. $150) | unpublished | EUR 100 | - | - |
| Exclusivity | none | optional bonus | none | none | none | none | **web-exclusive** |
| AI rule | anti mass-generated | originality | no interactive AI | no AI text (dashboard) | - | - | strictest |
| Launch gate before ads | review (test creatives) | Basic Launch (ads off) | moderation 3-5 days | review | review | 24 h feedback | Fit tests |

### B2. Ranked distribution opportunities

Ranked by expected value for this portfolio now (judgement on the evidence above):

| Rank | Opportunity | Why | Prerequisites | Risks |
|---|---|---|---|---|
| 1 | **CrazyGames Full Launch** for BBW, then SM | Largest open portal with published engagement benchmarks; ads only after Full Launch | content depth (L1, L6), load under 10 s, SDK events (already detected) | Basic Launch metrics below comparables; one game in review at a time |
| 2 | **Y8 approval with working ads** | Builds 003 in review; 50% share; non-exclusive | live ad verification after approval | "mass-generated" judgement on later titles |
| 3 | **Yandex**, when submissions reopen | Best native metrics; ML ranking rewards completeness; RU+EN needed | RU screenshots, promo, replies to reviews | Lower eCPM audience (3P); paused submissions |
| 4 | **GamePix** | Non-exclusive syndication via "Allow Distribution" | ad placements (P0 defect), human description | Terms unclear; dashboard/payout complaints (COMMUNITY) |
| 5 | **Playgama** (evaluate) | Open, non-exclusive, highest stated share, multiplies reach (MSN, YouTube Playables) | Bridge SDK adapter in the template; "net" definition | Overlap with other portals; terms vary by partner |
| 6 | **GameDistribution** | Adapter exists; wide syndication | Game ID; preroll and midroll policy | 33% of net; "must match latest version elsewhere" |
| 7 | **Coolmath** (puzzle titles only) | A licence fee; no ads | a logic game; no ads build | Genre-limited |
| - | Poki | Highest traffic per game, but exclusive and curated | a deliberate exclusive title | Conflicts with multi-portal strategy |
| - | Telegram, Discord, Facebook Instant | Weak fit (crypto CPM, IAP-only, declining) | - | - |

## Part C: Ad and feature fit, and the SDK architecture

### C1. Principles

1. **Ad opportunities come from beats.** Every target bans timer ads and ads during play. More
   revenue per play needs more natural beats (level ends, run ends, fails) and a rewarded offer
   the player wants.
2. **Rewarded is the highest-value format** (CrazyGames ad monetization guide) and the only one
   the player chooses.
3. **Interstitials cost retention.** One per beat boundary, never on the first beat of a session,
   within each portal's cap.
4. **Session length multiplies everything.** CrazyGames ties impressions per play to playtime.
5. **A higher number of ad requests is not better monetization.** Requests beyond a cap return
   `too-soon`; requests during play break policy.

### C2. Format fit by genre

Legend: **now**, **test**, **defer**, **no**.

| Family | Interstitial at beat | Rewarded continue / revive | Rewarded hint / booster | Rewarded double reward | Banner (where allowed) |
|---|---|---|---|---|---|
| puzzle | now (level end, from 2nd) | test (extra moves) | now (hint) | test | test on level-select |
| platformer | now (level end) | now (checkpoint revive) | defer | defer | no |
| arcade | now (run end, from 2nd) | now (one continue per run) | no | defer | no |
| shooter | now (wave / run end) | now (revive once) | test (power-up) | defer | no |
| racing | now (race end) | test (restart from checkpoint) | test (boost) | test (coins) | no |
| strategy | now (mission end) | defer | test (extra resource) | test | test on menus |
| survival | now (run end) | now (revive once) | test (starting kit) | test | no |
| simulation | test (day / chapter end) | no | test (speed-up) | now (offline earnings) | test on menus |
| idle | defer (few beats) | no | now (speed-up) | now (offline x2) | test |

Retention features by genre are in [game-design-improvements.md](game-design-improvements.md) §5.

**Banned patterns, never:**
- ads during play, timer ads, surprise ads, ads on navigation buttons;
- rewarded buttons that do nothing; rewards without a completed ad; chained rewarded ads;
- overstated rewards; a "free" label on an ad;
- energy gates that force ads; pay-to-win;
- fake close buttons; layouts that invite accidental clicks.

### C3. SDK architecture: smallest robust changes

The template's `Platform` interface is sound (one interface, exactly-once rewards, no rejecting
calls, graceful degradation). Do not replace it. Close these gaps:

| Gap | Change | Where |
|---|---|---|
| Placements can omit a target, and the check reads the same placements | Per-target ad hard gate derived from the **profile**, plus a bot session on each target's build with `adsRequested > 0` | `scripts/wgf_verification/checks/platform.py`, `core/reference/check-tiers.yaml` |
| Pause rule differs by portal (Y8: inside `beforeAd`/`afterAd`) | Profile field `ads.pause_scope`; plan field `pauseInsideAdCallbacks`; port from the game fix d8c8c3a | `core/reference/platforms/*.yaml`, `scripts/wgf_sdk/integration.py`, `scripts/wgf_sdk/game/src/platform/gameplay.ts` |
| Yandex has no max duration after `onOpen`; CrazyGames `init()` has no timeout | Timers in the adapters | web-game-template, then a pin move |
| No GamePix adapter at the pin | Pin a template release with it (v1.2.2+) | `workspace/config/template.lock.json` (with goldens) |
| Launch-stage gating is invisible | Profile field `launch_stage_ads` (CrazyGames basic-launch: false) | profiles; read by design and reports |
| Spent rewarded offer stays visible | sdk e2e scenario | `scripts/wgf_sdk/e2e/smoke.spec.ts` |
| Ads never exercised by the bot | Playability exercises one interstitial and one rewarded per target build against the mock | `scripts/wgf_playability/` |

Consent: portals run their own consent flows inside their SDKs. Games must not add their own
trackers. No change is needed beyond keeping third-party scripts out (already enforced per
package).

## Part D: Release readiness

### D1. Reusable checklist (every network)

1. Built from a commit on the game's release line; the package hash recorded in the workspace.
2. Only that portal's SDK in the bundle; no foreign URLs, no source maps.
3. Per-target ad gate passes; pause rule per profile.
4. Every unit solvable by the bot; content at or above the portal-derived bar.
5. Browser QA passes, including landscape phone, text-fits-control, a failed-asset retry and
   throttled load.
6. Initial download within the strictest target limit (CrazyGames mobile: 20 MB or less).
7. Store listing validated per profile; UNKNOWN requirements named. Copy human-reviewed
   (human-written for GamePix).
8. Age rating and content declarations made by a person.
9. Stranger playtest evidence at G4.
10. G5 and G6 decision records pinning the manifest, build and listing.
11. Submission by a person in a live login (`docs/publish-module.md`).

### D2. Network-specific validation

| Check | Y8 | CrazyGames | Yandex | GamePix | GameDistribution |
|---|---|---|---|---|---|
| SDK ids at build | App ID + Game ID | - | - | - | 32-hex Game ID |
| Loading API | none | `loadingStart/Stop` | `LoadingAPI.ready()` within 90 s | required | none |
| Gameplay events | none | `gameplayStart/Stop`, `happytime` | `GameplayAPI.start/stop` | pause/resume | - |
| Pause scope | inside callbacks | request | request | audio pause during ads | `SDK_GAME_PAUSE` |
| Locale | none | EN default | **RU + EN** | - | EN |
| Size | unknown | 20 MB mobile home, 50 MB max | 100 MB | - | - |
| Portal QA tool | QA tab | QA tool + attestations | moderation | Testing Toolkit | - |
| Human-only items | Request Review | 6 attestations + PEGI | Submit for moderation | description, Submit | Game ID creation |

## Part E: Why a technically complete game still gets poor distribution

| Cause | How to detect | Evidence it applies to us |
|---|---|---|
| Not live yet (review, Basic Launch) | portal state | both games, today |
| No ads served (missing placements, test creatives) | live ad check | Y8 Builds 001/002; GamePix builds |
| Too little content for the playtime benchmarks | designed play time vs benchmark | BBW 854 s, SM 345 s total |
| Weak first minute (slow load, unclear goal) | conversion past 60 s | unmeasured |
| Thumbnail does not earn the click | CTR (Poki Web Fit), list position | unmeasured; Y8 picks its own |
| Incomplete card (Yandex ranking input) | card completeness | RU screenshots missing |
| Low originality judgement | rejection reason | Y8 "missing ads" only so far |
| Too large for the mobile home | initial download | BBW ~6.4 MB zip; OK |
| One game in review per account (CrazyGames) | portal banner | SM blocked behind BBW |

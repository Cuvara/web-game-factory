# Platform targets, October 2026: Yandex, CrazyGames, Y8, GameDistribution, GamePix

On 2026-10-04 the publishing priority for the two validation titles (Brick Breaker Worlds,
2D PixiJS; Sky Marble, 3D three.js) changed: **Yandex Games, CrazyGames and Y8 now, then
GameDistribution and GamePix; Poki deferred.** Both titles sit at G6 with a release packaged
for Poki only. This document records:

1. what each portal's official documentation requires today, with the URL every fact was
   read from, and where the Factory's profiles and the pinned template's adapters disagree;
2. the profile versions and Factory fixes that came out of it;
3. the Factory's path to retarget a finished title, with file:line evidence, the gaps, and
   the exact commands per game.

Nothing here was submitted, uploaded or logged into. Every page was read on 2026-10-04 through
a fetching tool that summarises; quoted text is near-verbatim, not byte-exact. That is why
every `store_listing` block below stays `status: unverified` with its `source` named: read
the page again before marking a block verified.

**UNKNOWN** means the official documentation is silent, or the page was unreadable (named).

---

## Part 1 - what the portals require

### Yandex Games

Sources: SDK `https://yandex.com/dev/games/doc/en/sdk/...`; requirements (numbered, the
moderation checklist) `https://yandex.com/dev/games/doc/en/concepts/requirements` (REQ); the
draft form `https://yandex.com/dev/games/doc/en/console/add-new-game/draft` (DRAFT, re-read
directly for this document).

| Topic | What the docs say | Source |
|---|---|---|
| SDK load / init | `<script src="/sdk.js">` on Yandex hosting (absolute S3 URLs forbidden, REQ 1.7); `await YaGames.init()`; the SDK is mandatory (REQ 1.1, 1.19.1) | sdk/sdk-about, requirements/1/19 |
| Game ready | `ysdk.features.LoadingAPI.ready()` when the game is playable, no loading screen left (REQ 1.19.2). A "90 s" figure appears in a summary but the 1.19.2 page returned 404: UNKNOWN | sdk/sdk-gameready |
| Gameplay start/stop | `GameplayAPI.start()/stop()` - optional; if used, the moments must match the description (REQ 1.19.3) | sdk/sdk-game-events, requirements/1/19 |
| Pause / mute around ads | `onOpen`/`onClose`/`onError` callbacks; `game_api_pause`/`game_api_resume` events also cover the startup ad the portal shows by itself. Sound stops on focus loss (REQ 1.3); sound and gameplay paused during fullscreen ads (REQ 4.7) | sdk/sdk-adv, sdk/sdk-events, REQ |
| Interstitial | Frequency "controlled by Yandex Games"; an over-frequent call ends in `onClose`. No minimum interval is documented. Ads only at logical pauses; real-time levels under 5 min: never during play; over 5 min: paused with a 2 s notice (REQ 4.4) | sdk/sdk-adv, requirements/4/4 |
| Rewarded | Optional for the player (REQ 4.5); the button names the reward (4.5.1); a bonus, never gating the core game (4.5.2); grant in `onRewarded` | REQ, sdk/sdk-adv |
| Ads unavailable / blocked | `onClose` (+`onError`) after an error or refusal; no crashes or freezes around ads (REQ 1.14); progress kept after an ad click (REQ 4.2). Ad-blocker policy: UNKNOWN | sdk/sdk-adv, REQ |
| Fullscreen | `ysdk.screen.fullscreen` (`request`/`exit`); the portal has its own button; mobile is fullscreen, desktop stretches with a long:short ratio at most 2:1 (REQ 1.6) | sdk/sdk-params, REQ |
| Saves | `player.setData/getData` up to 200 KB, 100 requests / 5 min; progress saved right after the action, surviving refresh and rotation, logged in or not (REQ 1.9, 1.2.2); localStorage acceptable only for simple games without purchases; cloud saves mandatory with IAP (1.9, 1.13.3) and switched on in the draft (1.11) | sdk/sdk-player, requirements/1/9 |
| Locales | Language detected through `environment.i18n.lang` before gameplay, for every game (REQ 2.14); every declared language translated (8.2.3). **No language is mandatory**; ru, en, tr, ... recommended | requirements/2/14, concepts/languages-and-domains, DRAFT |
| Bundle | Zip, `index.html` at the root, no spaces or Cyrillic in names (REQ 1.22); at most **100 MB uncompressed** (REQ 1.21); not tied to a URL (1.18). File count: UNKNOWN | REQ |
| Listing | Title <= 50; short description <= 70; description 100-1000; how to play 100-1000; SEO description 50-160; keywords <= 100 chars; categories <= 2; tags <= 20; age rating required (0+, 6+, 12+, 16+, 18+, REQ 2.7); icon 512x512 PNG; cover 800x470 PNG; hero 1560x520 PNG/JPG; **screenshots at least 2 per selected platform**, 16:9 or 9:16, long side 1280-2560, JPEG or 24-bit PNG; video MP4 16:9 or 9:16, height >= 400, <= 28 s, <= 100 MB. Media >= 70% real gameplay (5.1.1); no screenshot as icon/cover (5.6); no borders or system UI (8.3.3-4) | DRAFT, REQ |
| Account (no code can solve) | Yandex ID developer profile; a contract (Russian entities: licensing model; everyone else: Yandex Advertising Network) unlocks moderation and payments; moderation 3-5 working days, at most 2 new-game requests open; licensee 18+ | concepts/quick-start, console/purchases |
| Other | Monetized through ads or purchases (1.12); no external links or redirects (8.4); no third-party ads (4.1); no runtime interactive AI (1.23); > 10 minutes of content or replayable (2.9); unpublished after 3 weeks rated <= 30 (2.13) | REQ |

### CrazyGames

Sources (prefix `https://docs.crazygames.com`): `/sdk/intro/`, `/sdk/game/`, `/sdk/video-ads/`,
`/sdk/banners/`, `/sdk/data/`, `/sdk/user/`, `/requirements/intro/`, `/requirements/technical/`,
`/requirements/gameplay/`, `/requirements/ads/`, `/requirements/game-covers/`,
`/resources/basic-launch-metrics/`, `/faq/`, `/payouts/`. The QA tool and the submission form
need a login and were not read.

| Topic | What the docs say | Source |
|---|---|---|
| SDK load / init | `https://sdk.crazygames.com/crazygames-sdk-v3.js`; `await window.CrazyGames.SDK.init()` before any call; `environment` `local` / `crazygames` / `disabled` (every call throws on a foreign domain) | /sdk/intro/ |
| Loading API | `loadingStart`/`loadingStop` "has to be called", but **no launch requirement lists it** | /sdk/game/ |
| Gameplay start/stop | `gameplayStart` on play and every resume, `gameplayStop` on every break, never on focus loss; **required for Full Launch** (it measures the initial download). `happytime` sparingly | /sdk/game/, /requirements/technical/ |
| Pause / mute around ads | Mute and pause on `adStarted` (not on request), resume on `adFinished` / `adError`; `settings.muteAudio` overrides in-game audio | /sdk/video-ads/, /requirements/ads/, /sdk/game/ |
| Interstitial (midgame) | SDK-enforced "max 1 every 3 minutes", rewarded and preroll counting; `adCooldown` when early. Never during gameplay, never on a navigation button | /requirements/ads/, /sdk/video-ads/ |
| Rewarded | Not too often, never chained, optional with an alternative, never on an active gameplay screen; reward only on `adFinished` | /requirements/ads/ |
| Basic vs Full Launch | **Basic Launch: ads disabled** (`adsDisabledBasicLaunch`, banners `bannersDisabledBasicLaunch`) - expected; the game must run smoothly without them; SDK optional; initial download <= 50 MB. **Full Launch:** full SDK incl. gameplayStart, land in gameplay, CrazyGames ads only, works with AdBlock, account/progress integration. CrazyGames decides the move on KPIs (playtime, D1 retention, conversion); Basic Launch lasts 7-21 days, needs 500 plays | /requirements/intro/, /sdk/video-ads/, /resources/basic-launch-metrics/, /faq/ |
| Ad blocker | `hasAdblock()`; players with a blocker play normally; no dead rewarded buttons | /sdk/video-ads/, /requirements/ads/ |
| Fullscreen | Provided by the portal; **custom in-game fullscreen buttons are prohibited** | /requirements/gameplay/ |
| Saves | Data module (`getItem`/`setItem`, <= 1,048,576 bytes as JSON), guest data in localStorage migrated on login; the Progress Save toggle in the submission flow or the module is disabled. Raw localStorage: UNKNOWN | /sdk/data/ |
| Locales | **English required**; use `systemInfo.locale`, fall back to English | /requirements/gameplay/ |
| Bundle | 250 MB total, <= 1500 files, initial download <= 50 MB (<= 20 MB for the mobile homepage), relative paths only; legible at 800x450 to 1920x1080 at DPR 1; desktop playable landscape; PEGI 12 | /requirements/technical/, /requirements/gameplay/ |
| Listing | **Three covers**: landscape 16:9 1920x1080, portrait 2:3 800x1200, square 1:1 800x800, title the only text. **Preview videos**: landscape 1080p 16:9 and portrait 1080p 2:3, both mandatory, <= 20 s, <= 50 MB, no sound. **No screenshots** are asked for. Description and instructions asked; their limits, tags, categories, image formats and video container: UNKNOWN (form behind login) | /requirements/game-covers/, /faq/ |
| Account | Developer Portal account; CrazyGames decides Basic -> Full Launch; revenue share UNKNOWN; payout >= EUR 100 monthly; non-exclusive; support from 50,000 plays | /requirements/intro/, /faq/, /payouts/ |

### Y8

Sources: `https://docs.y8.com/` (SDK, advertising, analytics, cloud storage, localization,
authentication, best practices, studio), `https://developer.y8.com/` and
`https://developer.y8.com/games?new=1`.

| Topic | What the docs say | Source |
|---|---|---|
| SDK load / init | `https://cdn.y8.com/minimal-sdk/2-0/y8.min.js` (async, never bundled); listen for `y8sdk.ready`, `y8.sdk().init({appId}, {gameId, ...})`, then `emitReadyEvent()`. **App ID always required; Game ID required for ads** - both issued by the Y8 developer portal per game | /sdk/intro/, /studio/sdk-initialization/ |
| Loading / gameplay API | None documented; plays are counted at init | /sdk/intro/, /sdk/analytics/ |
| Pause / mute around ads | Pause and mute inside `beforeAd`, resume in `afterAd`; a skipped, capped or blocked break fires neither (`breakStatus`: viewed, dismissed, frequencyCapped, notReady, timeout, noAdPreloaded, error, ignored) | /sdk/advertising/ |
| Interstitial | Placements `start`, `next`, `pause`, `browse`; "roughly every 180 seconds, configurable per game", SDK-enforced; **never request `preroll`** | /sdk/advertising/ |
| Rewarded | `beforeReward(showAdFn)`; reward only on `adViewed`; never capped, restarts the interstitial interval | /sdk/advertising/ |
| Ads unavailable | A blocker means no callback runs; in draft/review the portal serves house or test ads; banners only if Y8 approves them; AdSense for Platforms needs Google's approval | /sdk/advertising/, developer.y8.com |
| Fullscreen | Only: the portal's own fullscreen survives an ad, a game-made fullscreen is exited for it | /sdk/advertising/ |
| Saves | Cloud Storage for **signed-in players only**, <= 30 KB a value, one write per key per 5 s; throttle auto-saves to once a minute and show failures. localStorage: UNKNOWN | /sdk/cloud-storage/, /best-practices/ |
| Locales | None required; `getPlatformLocale()` from the domain, `en` also the fallback | /sdk/localization/ |
| Bundle | HTML5/WebGL formats; uploaded through My Games -> Builds. Size limit, zip layout: UNKNOWN | developer.y8.com/games?new=1, /studio/overview/ |
| Listing | Thumbnail and screenshot sizes, text limits, categories, age rating: **UNKNOWN** (only the studio profile's limits are documented) | /studio/studio/ |
| Account | Developer account and a Studio (approval pending), terms accepted; every game reviewed; resubmission cooldowns 6 h to 5 days; 50% of eligible ad revenue; payout >= USD 100 (PayPal) | developer.y8.com, /studio/studio/ |
| Other | Guests must be able to play; **no external links, no foreign ads, pop-ups or redirects**; non-exclusive | /best-practices/, developer.y8.com/games?new=1 |

### GameDistribution

Sources: the GD-HTML5 wiki (`https://github.com/GameDistribution/GD-HTML5/wiki/...`), the
Developer Guidelines (DEVG, `https://static.gamedistribution.com/developer/developers-guidelines.html`),
the Design Guidelines (DESG, `.../design-guidelines.html`) and the developer terms
(`https://static.gamedistribution.com/terms/developer.html`, 2025-06-19).
`gamedistribution.com/sdk/` returned 404; the help centre returned 403.

| Topic | What the docs say | Source |
|---|---|---|
| SDK load / init | `window.GD_OPTIONS = {gameId, onEvent}` then `https://html5.api.gamedistribution.com/main.min.js`, once. Game ID from the control panel; its format is not stated (examples are 32 hex). The SDK counts as implemented only after one ad is watched from the upload view | wiki SDK-Implementation |
| Loading / gameplay API | None documented (`SDK_READY`, `SDK_ERROR` only) | GD-HTML5 README |
| Pause / mute | Pause and mute on `SDK_GAME_PAUSE`, resume on `SDK_GAME_START`; after an ad a pause screen resumes on player input | wiki, DEVG 2.1.2, 2.3 |
| Interstitial | Preroll and midroll **mandatory**; the game calls `showAd()` (preroll on Play); SDK-enforced interval; only behind player input, outside gameplay | DEVG 2, wiki |
| Rewarded | `preloadAd('rewarded')`/`showAd('rewarded')`; reward only on `SDK_REWARDED_WATCH_COMPLETE`; needs the rewarded flag in the account | wiki Rewarded-Ads, DEVG 2.2.1 |
| Saves | "Any collection or storing of data ... strictly prohibited"; localStorage progress: UNKNOWN (ambiguous) | DEVG 7 |
| Locales | English the default; multi-language games detect or let the player choose | DEVG 4.1-4.2 |
| Bundle | Zip upload; HTTPS-ready; no external hosting except real multiplayer; no outgoing links, store references, third-party ads, purchases or trackers; sound and music required. Size and file limits: UNKNOWN | DEVG 1.2, 3.1, 6, 7; terms 2.6.7-2.6.8 |
| Listing | Thumbnails 512x512, 512x384, 200x120 mandatory (1280x720, 1280x550 optional); description and instructions 200-500 chars each; 1-2 genres; 1-5 tags; age group mandatory. Screenshots, video, image formats: UNKNOWN | DESG, DEVG 5 |
| Account | Developer account; **Game ID per title** (the build cannot run without it); 33% of net revenue; non-exclusive; the GD build must equal the latest published elsewhere; first review up to a week | terms 3.1, 2.1, 2.6.4; DEVG |

### GamePix

Sources: `https://partners.gamepix.com/sdk/doc/javascript` (JS),
`https://partners.gamepix.com/guidelines/submission` (SUB), `https://partners.gamepix.com/developers` (DEV).

| Topic | What the docs say | Source |
|---|---|---|
| SDK load / init | `https://integration.gamepix.com/sdk/v3/gamepix.sdk.js`, first script in `<head>` (mandatory). `GamePix.loaded()` before any other call, once. No Game ID in code is documented | JS |
| Loading / gameplay API | `GamePix.loading(0-100)`, `GamePix.loaded()`; gameplay stop: UNKNOWN (the Unity guide names a newer `lifecycle` API the JS page does not) | JS, sdk/doc/unity-plugin |
| Pause / mute | Pause before `interstitialAd()`, resume in its callback; pause (audio too) on tab switch, following document visibility | JS, SUB |
| Interstitial | `GamePix.interstitialAd()`; frequency decided by GamePix - signal every break; no ads during gameplay, **no timer-triggered ads** | JS, SUB |
| Rewarded | `GamePix.rewardAd()` (beta); reward only on `success`; skipping always possible | JS, SUB |
| Saves | `GamePix.localStorage` (strings) is the documented route | JS |
| Locales | `GamePix.lang()`; default English; none required | JS, SUB |
| Bundle | Relative paths, no external resources, links, analytics or other SDKs (Xsolla excepted); resizes in a 640x480 iframe, both orientations, **no "rotate device" prompt**, no quit button. Size limit: UNKNOWN | JS, SUB |
| Listing | An icon and a cover, title matching the game; sizes and limits UNKNOWN (dashboard behind login) | SUB |
| Account | Dashboard account; 45% revenue share; **exclusive to gamepix.com unless "Allow Distribution" is selected** | DEV, SUB |

---

## Part 1b - disagreements, and what changed

### Profiles (core/reference/platforms) against the docs

| Profile | Field | Was | Docs say | Now |
|---|---|---|---|---|
| yandex@1.1.0 | `metadata_requirements.screenshots_min`, assertion `yandex_screenshots` | 3 | at least 2 per selected platform | **1.2.0**: 2 |
| yandex@1.1.0 | `store_listing` | every size and limit null | DRAFT states them all | **1.2.0**: title 50, short 70, long 100-1000, tags <= 20, categories <= 2, age rating, icon 512 PNG, cover 800x470 PNG, optional hero 1560x520, screenshots >= 2 PNG/JPG, optional video MP4 <= 28 s <= 100 MB, height >= 400 |
| yandex@1.1.0 | `requirements.locales_required` | [ru] | none mandatory (2.14 detection, 8.2.3 translation) | kept [ru], now commented as a Factory choice (primary audience), not a portal rule |
| yandex@1.1.0 | `ads.interstitial_min_interval_s` | 60 | no interval documented; portal-controlled | kept 60, commented as the Factory's floor (the adapter keeps it too) |
| crazygames@1.1.0 | `requirements.loading_api` | required | optional (no launch requirement) | **1.2.0**: optional (matches the template adapter) |
| crazygames@1.1.0 | `metadata_requirements.screenshots_min`, assertion `crazygames_screenshots` | 4 | no screenshots; three covers + two videos | **1.2.0**: 0, assertion removed |
| crazygames@1.1.0 | `store_listing.covers` | 16:9, **4:3**, 1:1, no sizes, from thumbnails | 16:9 1920x1080, **2:3** 800x1200, 1:1 800x800 | **1.2.0**: the three documented covers (16:9 from the 1920x1080 promo master) |
| crazygames@1.1.0 | `store_listing.video` | optional, no bounds | mandatory, 1080p, <= 20 s, <= 50 MB | **1.2.0**: required, <= 20 s, <= 50 MB, height >= 1080, 16:9 (the portrait video is a manual item: the block states one video) |
| crazygames@1.1.0 | `store_listing.icon`, `locales` | icon required, locales null | no icon asked; English required | **1.2.0**: no icon, locales [en] |
| crazygames@1.1.0 | `review.common_rejections` | 4 | custom fullscreen, chained ads, dead rewarded buttons, missing English, PEGI 12, absolute paths, initial download | **1.2.0**: added |
| crazygames | 1500 files, 50 MB initial download, relative paths | absent | documented | notes only: the schema has no field; the template's `crazygames-audit.mjs` checks them |
| y8@1.1.0 | `requirements.no_external_links` | absent | no external links, foreign ads, redirects | **1.2.0**: true, blocking `y8_no_external_links` assertion, published review rules as common rejections |
| y8 | `store_listing` | all null | still undocumented | unchanged: Y8 renditions validate UNKNOWN, never passed |
| gamedistribution@1.1.0 | `store_listing` | text limits null, age rating not required | description 200-500, 1-2 genres, 1-5 tags, age group mandatory, optional 1280x720 / 1280x550 | **1.2.0** |
| gamedistribution@1.1.0 | `metadata_requirements.age_rating_required` | false | mandatory | **1.2.0**: true |
| gamedistribution | `game_id_pattern` 32-hex | stated | format not documented | kept (official examples and the template adapter), commented |
| (none) | gamepix | no profile | - | **no profile added**, see below |

What the bump does to a title pinned at 1.1.0. Steps that read the vendored copy keep working:
verify, release and the publish group (a game vendored at `@1.1.0` is validated against that
copy). Steps that read the Factory's profile refuse the old pin until the title re-plans:
design (`wgf_design/platforms.py:73`), tech-plan (`wgf_techplan/selection.py:224`), init
(`wgf_init/profiles.py:106`) and sdk (`wgf_sdk/plan.py:78`). The two validation runs at G6 can
therefore finish their publish group on the new Factory. Any other run that still has to pass
design, tech-plan, init or sdk must re-plan first, so do not move a mid-run Factory checkout to
this commit. A retarget re-plans anyway.

### GamePix: why there is no profile

The pinned template (v1.2.0, `packages/platform-sdk/src/registry.ts`) has no `gamepix`
adapter: `createPlatform("gamepix")` throws at boot. Template main had none either; the adapter
is Cuvara/web-game-template#23 (opened 2026-10-04). A profile would let research and the
strategy choose GamePix and produce a build that cannot start. GamePix becomes a target in
this order: a template adapter (load `gamepix.sdk.js` first in `<head>`, `loading()`/`loaded()`,
`interstitialAd()` at every break, `rewardAd()`, `GamePix.localStorage`, `lang()`, a visibility
pause, no rotate prompt) on a template release the Factory pins, then
`core/reference/platforms/gamepix.yaml` from the table above (ads [interstitial, rewarded],
loading_api required, locales_required [en] as a Factory choice, no_external_links true,
store_listing all null), then integrity. The exclusivity default (gamepix.com only unless
"Allow Distribution") is a person's choice at submission.

### The pinned template's adapters against the docs

| Adapter | Disagreement | Effect |
|---|---|---|
| all | One bundle boots one adapter: the first `required` platform (`scripts/build/game-config-plugin.ts:170-185`; Factory `wgflib/template_contract.py:173`). The CrazyGames and Y8 `<script>` tags are injected only when that platform is primary | Only one target per build is shippable (Part 2) |
| yandex | 60 s local interstitial floor (`adapters/yandex.ts:44-58`) where the docs leave frequency to the portal | Harmless: fewer requests |
| yandex | No fullscreen call, no banner (`YANDEX_CAPABILITIES`) | Matches the docs (portal button; banners are a console switch) |
| crazygames | `loadingApi: "optional"` | Matches the docs; the 1.1.0 profile was wrong |
| crazygames | Basic vs Full Launch known only from `adsDisabledBasicLaunch` | Matches the docs; a Basic Launch build shows no ads by design |
| y8 | Without `WGF_Y8_APP_ID` the build only **warns** and runs without the SDK (`game-config-plugin.ts:143-150`); a malformed ID fails the build | A Y8 package built without IDs earns nothing and counts no plays - the Factory must refuse it (Part 2, gap 4) |
| gamedistribution | Refuses to boot without a 32-hex Game ID, and refuses the placeholder (`adapters/gamedistribution/platform.ts:594-601`) | Needs the account's Game ID before any build |
| docs | `docs/platform-architecture.md` said CrazyGames had "no adapter on template main" | Stale since template 1.2.0; corrected |

### Factory fixes made while auditing

- **Listing validation checked only a video's format.** A profile's `max_seconds`,
  `min_seconds`, `max_mb`, `min_width`, `min_height` and `aspect` were read and never compared,
  so a 30 s recording passed a 20 s portal. Now every stated bound is measured; a miss fails
  the platform's video check with `fix: configure` (`wgf_listing/validation.py`
  `_video_problems`).
- **The canonical package could not make CrazyGames' covers** without upscaling (thumbnail
  masters were 1280x720 / 1024x768 / 512x512). `core/reference/store-listing.yaml` 1.1.0 adds a
  1200x1800 portrait master, a 1024 square, a **1080p trailer** (was 720p, below CrazyGames'
  1080p) and 18 s of trailer play (20 s plus the held result screen overran CrazyGames' 20 s).
- **Master choice** for an aspect no master has (Yandex's 800x470) now takes the nearest
  aspect, not the largest master - with a portrait master present it would have cropped the
  cover from it (`wgf_listing/package.py` `_master_for`).
- **A person can choose a title's platforms** (`factory.strategy.platforms`, or
  `with: {platforms: [...]}` on the strategy step; Part 2).
- **GamePix SDK in the template:** every supported network now has an adapter on template
  main once Cuvara/web-game-template#23 merges (`adapters/gamepix.ts`, the head script for a
  gamepix build, mocks and conformance tests, `docs/platforms/gamepix.md`, a proposed
  `config/platforms/gamepix.yaml`). The Factory profile follows when the Factory pins a
  template release that carries it.

---

## Part 2 - retargeting a finished title

### Where targets are pinned

1. **The strategy (G2) picks them.** `title-strategy.platform_set[]` = `{id, profile_version,
   role}`, built from `opportunity.candidate_platforms`, ranked by audience fit, the best one
   `required`, at most `max_platforms` (3) (`scripts/wgf_strategy/planner.py`, `platforms()`).
   Both validation runs had candidates [y8, crazygames, gamedistribution, yandex, poki]; the
   ranking made poki required. Until this change no person could choose otherwise.
2. **The tech plan (G3) copies them** into `repo_params.game_config.platforms`, required
   first, refusing a pin whose profile moved (`wgf_techplan/selection.py:203-229`, called at
   `wgf_techplan/step.py:183`). Its only `with:` is `physics`.
3. **Init writes the checkout:** `game.config.yaml` platforms, `config/platforms/<id>.yaml`
   and `pinned.json` (`wgf_init/profiles.py:84-135`), one local commit.
4. Downstream reads: `sdk` and `verify` read the checkout's `game.config.yaml`; `store-listing`
   reads the **scaffold-record** (`wgf_listing/platforms.py:62`) unless
   `factory.listing.platforms` names them; `listing-validation` the listing; `release` the
   checkout; `platform-validate` the release-manifest.

So a retarget is a superseding strategy, G2, design (it binds locales, cadence and placements
to the platforms), tech plan, G3, init - and everything after init, because init's commit
moves HEAD: `sdk` refuses a HEAD that is not the prototype-report's commit, and `release`
refuses production-quality, visual-qa, review and listing results of another commit, or a G4
older than upstream work (`wgf_release/lineage.py`).

### What the Factory cannot do today (gaps, smallest proper fix)

1. **One package per target - not possible on template contract 1.** `pnpm build` makes one
   bundle that boots the first required platform's adapter; `release` deletes every other
   platform's zip (`wgf_release/step.py:412` `_prune`), verify fails
   `platform.build-target:<pid>` for each non-target (`wgf_verification/checks/platform.py:156`),
   and `platform-validate` reports them "not packaged (optional)" (`wgf_publish/validate.py:87-98`).
   A [yandex, crazygames, y8] retarget therefore ships **yandex.zip only**. The template has
   already solved its half: template **main** (contract 2, 997795e, not yet a release) has
   `pnpm build:platforms` (`scripts/build/build-platforms.mjs`) - one `vite build` per
   `platforms[]` entry with `WGF_TARGET_PLATFORM=<id>`, each bundle carrying only its own
   adapter, `build/platforms/<id>/build.json` with the Factory's `bundle_digest`, and a
   refusal of a portal entry missing its ID (y8 app_id, gamedistribution / gamemonetize
   game_id). Fix (not small, so proposed, not made): pin a template release carrying
   contract 2, then make `verify` judge each per-platform bundle, record one digest per
   platform in the manifest, package each, and drop `_prune` - `wgf_verification` +
   `wgf_release` + `wgflib/template_contract.py`.
2. **No person could choose the platforms** - fixed here: `factory.strategy.platforms` (or the
   step's `with:`) replaces the candidate list and the fit ranking (first = required); the
   compatibility checks and `max_platforms` still apply, and G2 still approves.
3. **No command re-runs "from init to release" inside an existing run.** `wgf resume --from`
   needs a resumable run, and a run whose last command was a group (`wgf plan --run`,
   `wgf publish --run`) ends `COMPLETED` "left scope" (`wgflib/workflow/engine.py:1316`);
   `--from` with `--run` is refused by design (`docs/workflow-engine.md`). `wgf new-game --run`
   skips every completed non-gate step, so after a re-plan it would **skip init** and re-ask
   G4 about the old build - a trap, not a path (`engine.py:704-720`: only gates are re-checked).
   Today's path is one `--run <id> --force` command per step (below). Fix (a core engine
   change, so proposed): let `wgf resume <run> --from STEP` continue a run that ended by
   leaving its scope, widening the scope to the workflow from STEP.
4. **A Y8 build without its IDs is silently SDK-less.** The template warns; the Factory passes
   no `WGF_*` to game builds unless `factory.agents.game_env_passthrough` lists them
   (`wgflib/agentenv.py:34-40`). Fix (small, proposed): verify or tech-plan refuses a y8 target
   whose App ID is not in the build environment, instead of shipping a package with no SDK.
5. **Init never removes a dropped platform's vendored profile** (`wgf_init/profiles.py:95,124`
   start from the existing `pinned.json`): after a retarget `config/platforms/poki.yaml` and
   its pin stay. Harmless to validation (targets come from `game.config.yaml`); untidy.
6. **The Y8 listing renders and validates UNKNOWN** (all-null `store_listing`): a rendition is
   made at the canonical sizes, every image and text limit is reported UNKNOWN, never passed;
   UNKNOWN never fails listing validation and `release` does not refuse it. A person reads the
   Y8 submission form.

### What each step does on a retarget

| Step | Re-run? | Why |
|---|---|---|
| strategy, G2 | yes | new `platform_set` (and profile 1.2.0 pins) |
| design | yes | binds locales, ad cadence, placements per platform |
| tech-plan, G3 | yes | `repo_params.game_config.platforms` |
| init | yes | rewrites `game.config.yaml`, vendors the 1.2.0 profiles, commits |
| greybox, greybox-playability, assets | re-run for a clean lineage; whether develop accepts their old outputs after a re-plan is unverified | |
| develop (+ playability, production-quality, visual-qa, review) | yes | HEAD moved; every later gate pins the developed commit. An agent session: the costly step |
| sdk, sdk-review | yes | wires the new primary's SDK hooks |
| verify, G4 | yes | new bundle; G4 must be decided again by a person |
| store-listing, listing-validation | yes | renditions for the new targets under the 1.2.0 blocks |
| release | yes | one package: the required platform's |
| platform-validate, G5, G6, submit | yes (`wgf publish --run`) | one publication record per packaged target |

### Exact commands

From the run's Factory checkout **after it is moved to the commit carrying these changes**
(never while a step is running in it), in Git Bash:

```bash
# Brick Breaker Worlds (2D)
cd C:/Users/duycu/wgf-runs/val-2d/factory
export WGF_PROJECT_DIR=C:/Users/duycu/wgf-runs/val-2d/project
RUN=new-game-20261003-081154-4e5e0a
# Sky Marble (3D)
# cd C:/Users/duycu/wgf-runs/val-3d/factory
# export WGF_PROJECT_DIR=C:/Users/duycu/wgf-runs/val-3d/project
# RUN=new-game-20261003-082542-0de9b5
```

1. State the decision in the project's config, `$WGF_PROJECT_DIR/workspace/config/factory.yaml`
   (layered over the shipped one):

   ```yaml
   factory:
     strategy:
       platforms: [yandex, crazygames, y8]   # first = required: the one packaged today
     # agents:
     #   game_env_passthrough: [WGF_Y8_APP_ID, WGF_Y8_GAME_ID]   # once the IDs exist
   ```

   Yandex first: both games already ship `ru`, and Yandex is the platform whose code
   requirements are strictest (LoadingAPI, i18n detection, saves). GameDistribution as a
   fourth needs `max_platforms: 4` and a Game ID in `workspace/titles/<id>/portals.yaml`.

2. Re-plan (G2, G3 are a person's):

   ```bash
   bin/wgf plan --run $RUN --force          # strategy -> WAITING at G2
   bin/wgf decide $RUN approve --note "Retarget: yandex, crazygames, y8; Poki deferred"
                                             # design, tech-plan -> WAITING at G3
   bin/wgf decide $RUN approve               # run ends COMPLETED ("left scope" before init)
   ```

3. Rebuild from init, one step per command (each stops if its step fails; read
   `bin/wgf status $RUN` before the next):

   ```bash
   for s in init greybox greybox-playability assets develop playability production-quality \
            visual-qa review sdk sdk-review verify; do
     bin/wgf $s --run $RUN --force || break
   done
   bin/wgf prototype-review --run $RUN --force   # G4 -> WAITING
   bin/wgf decide $RUN pass                       # a person, after reading the evidence
   for s in store-listing listing-validation release; do
     bin/wgf $s --run $RUN --force || break
   done
   bin/wgf publish --run $RUN --force             # platform-validate, G5, G6 (a person), submit (dry-run)
   ```

   A step that routes elsewhere (verify -> develop, visual-qa -> assets) ends the one-step
   command "left scope"; run the named step and continue the list from there. The develop
   session budget is not refilled by `--run`; a develop step BLOCKED on it is resumed with
   `bin/wgf resume $RUN --budget-sessions N`.

This sequence was driven end to end on a `--mock` run on 2026-10-04 (new-game to G6, then
`plan --run --force`, every step above, G4 `pass`, `publish --run --force` back to WAITING at
G6): every command exited 0 and each step executed. The same mock run also showed the trap of
gap 3: after `plan --run --force`, `bin/wgf new-game --run` emitted `STEP_SKIPPED` for init,
greybox, assets, develop, sdk and verify, then asked G4 again - about the old build.

### Verdict per platform

| Platform | Brick Breaker Worlds / Sky Marble: blocked in code | External (account, partnership, portal) |
|---|---|---|
| Yandex | Packageable after the retarget above (required). Known risks: PNG screenshots with alpha (24-bit asked); the 70%-gameplay media rule is a person's check | Developer profile, contract (licensing model or YAN), moderation 3-5 days, cloud-saves switch in the draft, age rating, how-to-play and SEO texts |
| CrazyGames | **Not packageable alongside Yandex** (gap 1); as the required platform it would be. The listing now needs a 1080p trailer under 20 s (store-listing 1.1.0) and a portrait video (manual) | Developer Portal account, Progress Save toggle, Basic Launch (ads disabled, expected) and CrazyGames' Full Launch decision |
| Y8 | **Not packageable alongside Yandex** (gap 1); even as required, the build needs `WGF_Y8_APP_ID` / `WGF_Y8_GAME_ID` passed through, or it ships SDK-less (gap 4) | Developer account and approved Studio, the App ID and Game ID from the portal, review, the listing fields (undocumented) |
| GameDistribution | Tech plan blocks without a registered Game ID; not packageable alongside another required platform | Account, Game ID, rewarded flag, preroll viewed once from the upload view |
| GamePix | No adapter at the pinned template (template#23 adds it to main): not a target until a template release carrying it is pinned and the profile is added | Account; exclusivity default |
| Poki | Deferred: the current r1 package stays as it is | - |

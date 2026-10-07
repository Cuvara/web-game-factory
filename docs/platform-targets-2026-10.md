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
| Game ready | `ysdk.features.LoadingAPI.ready()` when the game is playable, no loading screen left (REQ 1.19.2). **Re-read 2026-10-07: within 90 s**, at the moment play really becomes possible, never on a timer; moderators check it with the loading screen dismissed by hand and left to close, over several reloads (the 1.19.2 page returned 404 on 2026-10-04; it is documented now) | sdk/sdk-gameready, requirements/1/19 |
| Gameplay start/stop | `GameplayAPI.start()/stop()` - optional; if used, the moments must match the description (REQ 1.19.3) | sdk/sdk-game-events, requirements/1/19 |
| Pause / mute around ads | `onOpen`/`onClose`/`onError` callbacks; `game_api_pause`/`game_api_resume` events also cover the startup ad the portal shows by itself. Sound stops on focus loss (REQ 1.3); sound and gameplay paused during fullscreen ads (REQ 4.7) | sdk/sdk-adv, sdk/sdk-events, REQ |
| Interstitial | Frequency "controlled by Yandex Games"; an over-frequent call ends in `onClose`. No minimum interval is documented. Ads only at logical pauses; real-time levels under 5 min: never during play; over 5 min: paused with a 2 s notice (REQ 4.4) | sdk/sdk-adv, requirements/4/4 |
| Rewarded | Optional for the player (REQ 4.5); the button names the reward (4.5.1); a bonus, never gating the core game (4.5.2); grant in `onRewarded` | REQ, sdk/sdk-adv |
| Ads unavailable / blocked | `onClose` (+`onError`) after an error or refusal; no crashes or freezes around ads (REQ 1.14); progress kept after an ad click (REQ 4.2). Ad-blocker policy: UNKNOWN | sdk/sdk-adv, REQ |
| Fullscreen | `ysdk.screen.fullscreen` (`request`/`exit`); the portal has its own button; mobile is fullscreen, desktop stretches with a long:short ratio at most 2:1 (REQ 1.6) | sdk/sdk-params, REQ |
| Saves | `player.setData/getData` up to 200 KB, 100 requests / 5 min; progress saved right after the action, surviving refresh and rotation, logged in or not (REQ 1.9, 1.2.2); localStorage acceptable only for simple games without purchases; cloud saves mandatory with IAP (1.9, 1.13.3) and switched on in the draft (1.11) | sdk/sdk-player, requirements/1/9 |
| Locales | Language detected through `environment.i18n.lang` before gameplay, for every game (REQ 2.14); every declared language translated (8.2.3). **No language is mandatory**; recommended (re-read 2026-10-07): Russian, Turkish, Chinese, Korean, Hindi, Vietnamese, English | requirements/2/14, concepts/languages-and-domains, DRAFT |
| Bundle | Zip, `index.html` at the root, no spaces or Cyrillic in names (REQ 1.22); at most **100 MB uncompressed** (REQ 1.21); not tied to a URL (1.18). File count: UNKNOWN | REQ |
| Listing | Title <= 50; short description <= 70; description 100-1000; how to play 100-1000; SEO description 50-160; keywords <= 100 chars; categories <= 2; tags <= 20; age rating required (0+, 6+, 12+, 16+, 18+, REQ 2.7); icon 512x512 PNG; cover 800x470 PNG; hero 1560x520 PNG/JPG; **screenshots at least 2 per selected platform** (re-read 2026-10-07: mobile at least 2 **per orientation**, desktop 16:9 landscape only), 16:9 or 9:16, long side 1280-2560, JPEG or 24-bit PNG; **horizontal video required** (re-read 2026-10-07): MP4 16:9, height >= 400, <= 28 s, <= 100 MB; vertical 9:16 video optional, same bounds. Media >= 70% real gameplay (5.1.1); no screenshot as icon/cover (5.6); no borders or system UI (8.3.3-4) | DRAFT, REQ |
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
| Account | Developer account and a Studio (approval pending), terms accepted; every game reviewed; resubmission cooldowns 6 h to 5 days; 50% of eligible ad revenue; payout >= USD 100 (PayPal) or >= USD 500 (bank transfer, re-read 2026-10-07) | developer.y8.com, /studio/studio/ |
| Other | Guests must be able to play; **no external links, no foreign ads, pop-ups or redirects**; non-exclusive | /best-practices/, developer.y8.com/games?new=1 |

### GameDistribution

Sources: the GD-HTML5 wiki (`https://github.com/GameDistribution/GD-HTML5/wiki/...`: Home,
SDK-Implementation, F.A.Q., Rewarded-Ads; read as raw markdown), the README
(`https://github.com/GameDistribution/GD-HTML5`), the Developer Guidelines (DEVG,
`https://static.gamedistribution.com/developer/developers-guidelines.html`), the Design
Guidelines (DESG, `.../design-guidelines.html`), the Developer Game License Agreement (TERMS,
`https://static.gamedistribution.com/terms/developer.html`, "last updated on 19 June 2025") and
the developers page (DEVP, `https://gamedistribution.com/developers/`, which redirects to
`/developers/partnership/`; a single-page app, read rendered in a headless browser without
logging in). All re-read 2026-10-04. `gamedistribution.com/sdk/` returned 404;
`developer.gamedistribution.com` is an empty app shell; `.../register/developer/` redirects
to the Azerion Connect login (403 to a fetch). Nothing was registered, logged into or uploaded.

| Topic | What the docs say | Source |
|---|---|---|
| Developer account | Registration form: First name, Last name, Email, Country, **Company** required; **Website optional**; two checkboxes - GameDistribution's Developer Terms and Platform Privacy Policy, and Azerion Connect's Terms and Privacy Policy (Azerion Connect is the login for every Azerion platform). Accepting the agreement "by clicking a box" binds; for a company, the person must have authority to bind it | DEVP, TERMS preamble |
| **Domain / website** | **Not required for a developer account** (the field is optional). Required only to self-host: the submission is then a zipped `index.html` framing the game from the developer's own URL (`GD_SDK_REFERRER_URL` = the parent URL), and external hosting is permitted **only for real multiplayer games**, by GameDistribution's **written consent**. Modelled as the publication profile's `self-hosting` prerequisite | DEVP, README, DEVG 3.1, TERMS 2.9 |
| Flow | "Register -> Prepare a build in line with our GD guidelines -> Upload the build and go through our QA-checks -> Launch your game and track your earnings" | DEVP |
| Game ID | `GD_OPTIONS.gameId`, "your game hash", "which you can retrieve from your Gamedistribution.com control panel"; "unique for each one of your games". Format not stated (examples 32 hex). That the panel issues it before the build is uploaded is derived, not stated: the SDK must be implemented "before uploading" (TERMS 2.6.3). **Create-before-build**, like Y8 | wiki SDK-Implementation |
| SDK load / init | `window.GD_OPTIONS = {gameId, onEvent}` then `https://html5.api.gamedistribution.com/main.min.js`; "Only load the SDK once!" Mandatory: the game ID, pause **and mute** on `SDK_GAME_PAUSE`, resume on `SDK_GAME_START` | wiki SDK-Implementation |
| SDK activation | Upload, open the game in its iframe from the bottom of the upload view, watch the pre-roll **completely** once; this flags the integration ("can currently take up to two weeks"); then publication can be requested | wiki SDK-Implementation, F.A.Q. |
| Loading / gameplay API | None documented (`SDK_READY`, `SDK_ERROR` only) | README |
| Interstitial | Pre-roll (on Play) and mid-roll **mandatory**; `gdsdk.showAd()` behind a touchUp/mouseUp, outside gameplay; the SDK regulates the interval (a 2-minute mid-roll timer may be set); a pause screen after an ad resumes on player input | DEVG 2.1, wiki |
| Rewarded | `preloadAd('rewarded')` / `showAd('rewarded')`; reward only on `SDK_REWARDED_WATCH_COMPLETE`; **the rewarded ads flag must be checked** for the game in the panel | wiki Rewarded-Ads, DEVG 2.2.1 |
| Display ads | Optional; must not cover game content; `showBanner()` deprecated | DEVG 2.2.2, wiki |
| Saves | "Any collection or storing of data from a game is strictly prohibited"; localStorage progress: UNKNOWN (ambiguous) | DEVG 7 |
| Locales | English the default (DEVG 4.1, TERMS 2.6.5); multi-language games detect or let the player choose; a "No-Text" option for text-free games | DEVG 4 |
| Bundle | Zip upload; HTTPS-ready; desktop playable (Chrome, Firefox, Safari); responsive in iframe and fullscreen (800x600 recommended); sound and music required; no outgoing links, store references, third-party ads, purchases, trackers or login. Size, file count and zip layout: UNKNOWN | DEVG 1.2, 3, 6, 7; TERMS 2.6.7-2.6.8 |
| Listing | Thumbnails 512x512, 512x384, 200x120 mandatory (1280x720, 1280x550 optional); description and instructions 200-500 chars each, the game's name at least once; 1-2 genres; 1-5 tags; age groups mandatory (plus "kids friendly", "no blood"); store references only in the game's Backlinks tab. Screenshots, video, image formats: UNKNOWN | DESG, DEVG 5, 6.3 |
| Review | Every submission reviewed by content specialists; the game is activated or returned with feedback; publication is requested with "the designated button within your control panel". Timeline **disagrees across pages**: "up to 2 days" (wiki F.A.Q.), "up to one week" (DEVG), "up to 3 weeks" (DEVP FAQ), SDK activation "up to two weeks" | wiki F.A.Q., DEVG, DEVP |
| Monetization | 33% of net revenue; paid within 60 days of the monthly report once at least **EUR 100** and payment and VAT details are filled in (the wiki F.A.Q.'s 50 euro is older); non-exclusive; the GD build must equal the latest version published elsewhere | TERMS 3.1, 3.3, 2.1, 2.6.4 |
| AI content | Deep fakes (AI content resembling real persons, objects, places, entities or events) must be labelled with their artificial origin; nothing else said | TERMS 2.6.11, DEVG 1.5 |
| Automated panel use | Not addressed. The agreement forbids accessing the platform "for monitoring availability, performance, or functionality, or for benchmarking" without written consent | TERMS preamble |
| Publication states | Not documented ("activated" and "feedback" are the only words) | - |

**UNVERIFIED - only a logged-in person can learn:** every panel label and layout (creating a
game, the upload view, the iframe button, the publication request button); whether creating a
game issues the Game ID before any upload; the upload limits and zip layout; the panel's
listing fields beyond DEVG 5 (screenshots, video, formats, byte limits); the status labels;
whether the terms allow automated use of the panel; payment and VAT forms; whether Azerion
Connect login shows a CAPTCHA or second factor; which review timeline holds.

### GamePix

Sources: `https://partners.gamepix.com/sdk/doc/javascript` (JS),
`https://partners.gamepix.com/guidelines/submission` (SUB), `https://partners.gamepix.com/developers` (DEV),
the developer sign-up `https://partners.gamepix.com/join-us?t=developer` (JOIN) and the
License and Distribution Agreement it accepts,
`https://public.gamepix.com/partners/terms-conditions/developer-tc.pdf` (TC, undated). All
re-read 2026-10-04, the partners pages rendered in a headless browser (they are a
single-page app) without logging in.

| Topic | What the docs say | Source |
|---|---|---|
| Developer account | Sign-up: name, surname, email, date of birth (**18 or older**), public username (shown in a public URL), individual or company, country, and the terms checkbox. **No website or domain field**. Login is `https://my.gamepix.com/login` (the platform, "my.gamepix.com", in TC) | JOIN, TC preamble |
| **Domain / website** | **Not required**: none asked at sign-up, and "GamePix will host your games on secure servers" | JOIN, DEV |
| Flow | "Create your account -> Add SDK and submit your game -> Relax and get your revenues"; validate with the testkit on my.gamepix first | DEV, SUB |
| SDK load / init | `https://integration.gamepix.com/sdk/v3/gamepix.sdk.js`, **first script in `<head>` (MANDATORY)**. No Game ID in code is documented | JS |
| Loading / gameplay API | The page's numbered steps no longer list them, but its messages require `GamePix.loaded()` "before any other GamePix SDK methods", once (`LOADED_ALREADY_CALLED`), and `GamePix.loading(0-100)`; gameplay stop: UNKNOWN | JS |
| Pause / mute | Pause before `interstitialAd()`, resume in its callback; pause (audio too) on tab switch and on calls, by document visibility, not on clicks outside the iframe | JS, SUB |
| Interstitial | `GamePix.interstitialAd()`; GamePix decides frequency - signal every break; between levels, **no timer-triggered ads**, never two at once | JS, SUB |
| Rewarded | `GamePix.rewardAd()` (beta, 50% success in the test environment); reward only on `success`; tell the player first; skipping always possible | JS, SUB |
| Other API | `updateScore`, `updateLevel`, `happyMoment`, `lang()` (ar zh nl en fr de it ja ko pl pt ru es tr) | JS |
| Saves | `GamePix.localStorage` (strings); some mobile browsers purge it after closing or a week | JS |
| Locales | Display the system language when supported, else **English** the default | SUB |
| Bundle | Relative paths; no external links (incl. More Games, Rate Us, privacy links), analytics, ads or SDKs other than GamePix's and Xsolla's; no `window.alert`/`confirm` or system popups; resizes in a 640x480 iframe; both orientations, **no "rotate device" prompt**; a loading screen; no quit button. Size limit: UNKNOWN. Unity builds upload a `.gpx`; the HTML5 upload format: UNKNOWN | JS, SUB |
| Listing | An icon and a cover representative of the game, their title matching it; a description with theme, mission, characters, how to play. Sizes and limits UNKNOWN | SUB |
| Declarations | On every upload and update, through the platform: whether the game is **child-directed** (COPPA; when uncertain, yes), whether it incorporates an **AI System**, and which submitted assets (artwork, icons, banners, promotional images, audio, descriptions) were made or materially altered with **generative AI** | TC 4.9, 4.10 |
| Monetization | **45%** revenue share (DEV) vs **50%** of net revenues (TC 5.1): the pages disagree; balances under EUR 100 carry forward (TC 5.5) | DEV, TC |
| Exclusivity | Exclusive to gamepix.com unless **"Allow Distribution"** is selected when uploading (SUB); the license is non-exclusive except where an earlier agreement gave GamePix exclusivity (TC 2.1, 8.12) | SUB, TC |
| Other terms | Source code delivered on request (TC 3.3); the GamePix build identical to the latest version elsewhere, English at least, no network endpoint but GamePix's (TC 3.3, 4.9c) | TC |
| Review | Complete games only, "drafts or demos will not be approved"; duplicates of catalogue games may not be. Timeline and status labels: UNKNOWN | SUB |
| Automated dashboard use | Not addressed by TC | TC |

**UNVERIFIED - only a logged-in person can learn:** the whole dashboard submission form, its
fields and limits; icon and cover sizes and formats; whether screenshots, video, categories or
tags are asked for; the build upload widget, format and size limit for HTML5; whether the
dashboard issues an id the build must carry; status labels and review time; where the
child-directed and AI declarations are made; the payment and tax forms; CAPTCHA or second
factor on login; which revenue share applies to a new account.

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
| (none) | gamepix | no profile | - | **gamepix@1.0.0 added**, refused by strategy and tech-plan until the pin carries its adapter (below) |

What the bump does to a title pinned at 1.1.0. Steps that read the vendored copy keep working:
verify, release and the publish group (a game vendored at `@1.1.0` is validated against that
copy). Steps that read the Factory's profile refuse the old pin until the title re-plans:
design (`wgf_design/platforms.py:73`), tech-plan (`wgf_techplan/selection.py:224`), init
(`wgf_init/profiles.py:106`) and sdk (`wgf_sdk/plan.py:78`). The two validation runs at G6 can
therefore finish their publish group on the new Factory. Any other run that still has to pass
design, tech-plan, init or sdk must re-plan first, so do not move a mid-run Factory checkout to
this commit. A retarget re-plans anyway.

### Part 1c - re-read 2026-10-07: profile versions 1.3.0

The official pages were read again on 2026-10-07 (the research note
`wgf-research/publishing-research-2026-10-07.md`, outside this repository, tags every fact
OFFICIAL, COMMUNITY or UNKNOWN). Only OFFICIAL facts changed a profile. COMMUNITY knowledge is
recorded below and nowhere else; UNKNOWN stays null.

| Profile | Field | Was | Docs say (read 2026-10-07) | Now |
|---|---|---|---|---|
| yandex@1.2.0 | `store_listing.video` | optional, no aspect | horizontal video **required** (red asterisk on the ru draft page; "Horizontal Video (required)" on the en page): 16:9 MP4, height >= 400, <= 28 s, <= 100 MB; vertical 9:16 optional | **1.3.0**: `required: true`, `aspect: "16:9"`, `orientation: [landscape]` (DRAFT en + ru) |
| yandex@1.2.0 | `store_listing.screenshots`, `metadata_requirements.screenshots_min` | min 2 (a total) | at least 2 per selected platform; mobile at least 2 **per orientation**; desktop 16:9 landscape only | min stays 2 (the one-platform floor); the per-platform and per-orientation rule in notes - gap Y-2 (DRAFT) |
| yandex@1.2.0 | `requirements.loading_api`, assertions | the call only | `LoadingAPI.ready()` within **90 s**, when play is really possible, never on a timer | **1.3.0**: blocking `yandex_game_ready_within_90s` on `package.perf.time_to_interactive_s` (requirements/1/19) |
| yandex@1.2.0 | `requirements.locales_recommended` | [en, tr] | Russian, Turkish, Chinese, Korean, Hindi, Vietnamese, English recommended; none mandatory | **1.3.0**: [en, tr, zh, ko, hi, vi]; ru stays required as the Factory's choice (concepts/languages-and-domains) |
| yandex@1.2.0 | `review.typical_days` | [1, 5] | full moderation 3-5 working days; content moderation 1-2 | **1.3.0**: [3, 5]; content moderation in notes and the publication profile (concepts/moderation) |
| yandex@1.2.0 | `review.common_rejections` | 8 entries | context menu on long tap / right-click (1.6.1.8), Game Ready missing or mistimed (1.19.2), SDK errors (1.1, 1.19.1), genre mismatch (2.3), ad orientation (4.3), update replacing the game (1.24, new) | **1.3.0**: added (REQ, concepts/moderation, requirements/1/19) |
| yandex@1.2.0 | `ads.notes`, `store_listing.notes` | - | 4.3 ad orientation; ads in play count as ad fraud; sticky banners a console switch; required fields 5.2 include Version, Platforms, Orientation; title and short-description rules, keywords lowercase, SEO description shape, 5.11, 5.12 | **1.3.0**: in notes (sdk/sdk-adv, DRAFT) |
| publication yandex@2.2.0 | `fields.horizontal_video`, `vertical_video`, `unknowns` | `required: null`, "may be required; unconfirmed"; icon/cover/hero/screenshot sizes unknown | required; vertical optional; the sizes are stated | **2.3.0**: `horizontal_video.required: true`, `vertical_video.required: false`, maskable icon and hero optional; sizes noted against the platform block that checks them; the two unknowns removed; restrictions: content moderation, the update flow (the live version stays), REQ 1.24, the Cloud saves switch (1.11) |
| crazygames@1.2.0 | `capabilities.iap`, scoring hint | false, "there is no IAP here" | in-game purchases exist: invite-only, Xsolla, signed-in users; Automatic Progress Save then not allowed | **1.3.0**: stays `false`, commented as a Factory choice (an invitation is not something a design can assume); the hint corrected (/sdk/in-game-purchases/) |
| crazygames@1.2.0 | `capabilities.cloud_saves` | true, no note | Full Launch **requires** account-linked progress where progress applies: Data module, User module, or Automatic Progress Save | **1.3.0**: commented; a common rejection (/requirements/account-integration/, /other/aps/) |
| crazygames@1.2.0 | `ads.notes`, `common_rejections` | interval and mute rules | `settings.muteAudio` required for HTML5; banners only on useful screens open >= 5 s, at most 2, never in play, never over UI; rewarded buttons with a video icon | **1.3.0**: notes and rejections (/sdk/game/, /requirements/ads/) |
| crazygames@1.2.0 | `requirements` | size, files, initial download (notes) | 20 s to play with external files; a 4 GB Chromebook; Chrome and Edge; safe area in the CrazyGames App; sitelock; DPR-1 legibility 800x450-1920x1080; 144/165 Hz physics; gameplay within 1 click | **1.3.0**: comments - no schema field (gap C-4) |
| crazygames@1.2.0 | `store_listing.video.min_seconds` | null | "15-20 seconds maximum" - ambiguous | stays null; the reading in notes |
| publication crazygames@2.3.0 | `constraints.upload_max_mb`, `unknowns`, `restrictions` | 250 "unsourced"; no update rule | 250 MB sourced; updates resubmitted, live "within the same working day" | **2.4.0**: sourced; restrictions: the update rule, account-linked progress, invite-only purchases (/requirements/technical/, /faq/) |
| y8@1.2.0 | `capabilities.ads`, `ads.banner_available` | no banner; "No banner is documented" | banners exist (728x90, 300x250, ...) with Y8's per-game approval | **1.3.0**: still off until a person records approval; the comment corrected (/sdk/advertising/) |
| y8@1.2.0 | `capabilities.cloud_saves`, `requirements` | - | auto-saves at most once a minute; the per-game SDK checklist in the Developer Portal (content UNKNOWN); every game connected to a Studio | **1.3.0**: comments (/best-practices/, developer.y8.com, /studio/create-game/) |
| y8@1.2.0 | `review.common_rejections` | 4 | the published grounds: technical, quality, instructions, SDK integration, harmful/copyrighted/stolen content, malware, fake traffic, unauthorised ads; copied, reskinned or mass-generated games | **1.3.0**: added (developer.y8.com) |
| publication y8@2.2.0 | `identity.issued_on_create` app_id | read on create | Game ID on create; App ID on first opening the game's page, may read "Not yet available" | **2.3.0**: a note on the entry - refresh, never record that text (gap Y8-1) (/studio/create-game/) |
| publication y8@2.2.0 | `flow` | upload "Game file" (hypothesis) | builds are uploaded on the game's **Builds** tab | **2.3.0**: `tab.builds` (optional, documented) before `upload.build` (/studio/overview/) |
| publication y8@2.2.0 | payout, update rule | PayPal only; no update rule | bank transfer from USD 500; a new build is reviewed before it replaces the live one | **2.3.0**: `declare.payout` note and restrictions (developer.y8.com) |
| gamepix@1.0.0 | - | - | no difference against official text | unchanged; the community figures are below, never in the profile |

**Enforcement wired** (data the existing validators already read):

- **Yandex horizontal video.** `store_listing.video.required: true` with `aspect: "16:9"` and
  `orientation: [landscape]`: the store-listing package reports a missing MP4 trailer as an
  error-severity unmet, and listing validation's `platforms.yandex.video` fails (`fix:
  configure`) on a rendition with no video, or one over 28 s or 100 MB, under 400 px high or
  not 16:9; the submit step's media check (`campaign.check_media`) refuses the same and a
  portrait file (`video-orientation`). The publication profile's `horizontal_video` field,
  now required with `formats: [mp4]`, makes the campaign check refuse a campaign with no
  landscape trailer (`media-missing`) or a non-MP4 one (`media-format`). The canonical trailer
  is WebM; MP4 is derived only where an encoder is present, so on a host without one a Yandex
  listing now stops for a person instead of shipping without the video.
- **Yandex Game Ready within 90 s.** The blocking assertion `yandex_game_ready_within_90s` on
  `package.perf.time_to_interactive_s` - the template measures it right after the adapter's
  `signalReady()` (`src/main.ts`, template-owned) - so verify's `policy.assertions:yandex`
  fails a build that reaches ready() after 90 s on the served bundle. Whether ready() fires
  when play is really possible rather than on a timer stays a moderator's judgement.

**Gaps, documented, not enforced** (the schema or the measured facts cannot express them):

- **Y-2 Yandex screenshots per platform and orientation.** `store_listing.screenshots` has one
  `min` over all files, and `metadata.screenshots` counts a total. The rule is 2 per declared
  platform, 2 per declared mobile orientation, desktop 16:9 landscape only - 6 for a game
  declared desktop + mobile in both orientations. The canonical capture already takes a
  landscape and a portrait set (`core/reference/store-listing.yaml` renditions); a person
  checks the counts against the draft's Platforms and Orientation. Smallest fix: a
  `screenshots.per_orientation_min` in `shared/platform-profile.schema.json` `storeListing`,
  counted per capture `viewport` in `wgf_listing/validation.py` and `wgf_publish/campaign.py`.
- **Y-3 Yandex context menu (1.6.1.8; desktop right-click).** No measured fact says whether the
  build cancels `contextmenu`: the pinned template's `tests/verify/facts.spec.ts` does not
  record one, and its static `scripts/verify/yandex-audit.mjs` check (`context_menu_blocked`,
  a warning) is not run by the Factory. An assertion on a fact nobody measures is "not
  evaluable" and breaches on every build, so none was added. Smallest fix, in the template: a
  `package.context_menu_blocked` runtime fact (dispatch a cancelable `contextmenu` on the
  canvas, read `defaultPrevented`; the same for `selectstart`), then a blocking assertion in
  this profile. The research found no suppression in either validation game.
- **Y-4 no upload intent for the Yandex video.** The publication flow uploads icon, cover and
  screenshots; no intent uploads the horizontal video, because its console widget is unknown
  (the label "Horizontal video" is documented only as a field name). The media check refuses a
  campaign without it, so a person uploads it in the draft. Fix: an `upload` intent with
  `value: listing.media.trailer_landscape` once a person has observed the widget
  (`wgf-publish.py observe yandex`).
- **Y-5 judgement rules:** ad orientation (4.3), genre match (2.3), an update keeping the core
  concept (1.24), the 70%-gameplay media rule (5.1.1). Common rejections and notes only.
- **C-1 CrazyGames `settings.muteAudio`.** The template's CrazyGames adapter exposes
  `settings.muteAudio` and `settings:change`; whether the game's audio follows it is not a
  measured fact. Fix, in the template: a runtime fact from the CrazyGames mock toggling the
  setting and reading `document.documentElement.dataset.audioMuted`, then an assertion.
- **C-2 CrazyGames portrait 2:3 preview video.** The block states one video. A required
  publication field for a portrait trailer would fail every run with a re-render the step
  cannot satisfy (the canonical trailer is landscape only), so it stays a manual item.
  Fix: `storeListing.video` as a list (or `videos`), and a portrait trailer capture.
- **C-3 no audio in preview videos.** No `has_audio` is measured on the trailer file.
- **C-4 CrazyGames technical rules** with no field (20 s to play with external files, 4 GB
  Chromebook, safe area in the CrazyGames App, sitelock, 144/165 Hz, gameplay within 1
  click): comments in the profile; the template's `crazygames-audit.mjs` covers part of it and
  is not run by the Factory.
- **Y8-1 the App ID's delay.** The executor records whatever non-empty text the `App ID`
  locator shows (`wgf_publish/browser/console.spec.ts`, the `issued_on_create` read); "Not yet
  available" would be recorded as an id. Fix: a
  `pattern` on each `issued_on_create` entry, an id that does not match read as not issued
  (refresh and read again, else stop for a person).
- **Y8-2 the per-game SDK checklist** in the Developer Portal: UNKNOWN; a person reads it.

**COMMUNITY, never a requirement:**

- Yandex: wnhub.io, 2026-06-24 (`https://wnhub.io/news/other/item-51215`) - applications
  doubled to about 10,000 a month, the moderation reset button is temporarily disabled, 72% of
  rejections are UI, SDK or technical flaws. Read 3-5 days as optimistic.
- Y8: the forum and an 8th Wall guide describe an upload without a Studio (a "Y8 Storage
  account", Zip or iFrame) - superseded by "every game must be connected to a studio" and the
  302 from `y8.com/upload` to `developer.y8.com/games?new=1`. A forum thread reports a large
  build refused and cut to 41 MB - no stated limit (`max_bundle_mb` stays null).
- GamePix: a third-party tool (`https://github.com/dannyking13/gamepix-publish`) reports
  dashboard sections Info, Assets, Editorial, Build, an icon 256x256 PNG <= 1 MB, a cover
  1360x850 PNG <= 1.5 MB, a description of 100-500 characters. `platforms/gamepix.yaml` keeps
  every size null; nothing here says automated dashboard use is permitted.

**What the bump does.** yandex, crazygames and y8 move to 1.3.0 (publication profiles: yandex
2.3.0, crazygames 2.4.0, y8 2.3.0; GamePix unchanged). As with 1.2.0 (Part 1b): a title
vendored at `@1.2.0` keeps verify, release and the publish group against its copy; design,
tech-plan, init and sdk refuse the old pin until the title re-plans. Both validation games pin
`yandex@1.2.0` and `crazygames@1.2.0`; their retarget (Part 2) re-plans anyway. Do not move a
mid-run Factory checkout to this commit.

### GamePix: a profile, refused until the pin carries its adapter

GamePix now has `core/reference/platforms/gamepix.yaml` (1.0.0, from the table above: ads
[interstitial, rewarded], loading_api required, locales_required [en] from SUB's English
default, no_external_links true, store_listing with every size null) and
`core/reference/publication/gamepix.yaml` (2.0.0, console `https://my.gamepix.com/`,
`automation_terms: unverified`, `content_policy` `disclose` for generated text and assets from
TC 4.10, human intents for "Allow Distribution", the child-directed and AI declarations and
the testkit, everything else under `unknowns`).

The pinned template (v1.2.0) still has no `gamepix` adapter: `createPlatform("gamepix")`
throws at boot. The adapter is on template main (Cuvara/web-game-template#23, merged
2026-10-04, with a proposed `config/platforms/gamepix.yaml` at the same version 1.0.0 - when
the pin moves, `check-integrity.py` warns if the two differ). So the profile exists and
targeting it is refused:

- `workspace/config/template.lock.json` records `platform_adapters`, the pinned commit's
  adapter registry (`KNOWN_PLATFORM_IDS` of `packages/platform-sdk/src/registry.ts`);
  `wgflib.template.platform_adapters()` reads it, and `check-integrity.py` and
  `test_core_template` hold it equal to the registry at the pin. Moving the pin moves the list
  in the same commit.
- **Strategy** refuses a person's choice of a platform outside that list, and drops such a
  candidate from the opportunity with a risk (`wgf_strategy/planner.py`).
- **Tech-plan** blocks on any pinned platform outside it (`wgf_techplan/selection.py`
  `require_adapters`).
- Both say: "GamePix needs a template release carrying its SDK adapter
  (HUMAN_ACTION_REQUIRED: release and pin)".

Integrity: the platform-id rule is that every id the pinned template's `game.config.yaml`
names has a profile in core; a profile the template does not name is allowed (gamemonetize,
gamevui and others already are). `gamepix` therefore passes, and `check-integrity.py` adds a
note that it has no adapter at the pin. GamePix becomes a target when a template release
carrying the adapter is pinned (golden runs at the new commit, then the lock and its
`platform_adapters` in one commit). The exclusivity default (gamepix.com only unless "Allow
Distribution") stays a person's choice at submission.

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
  `config/platforms/gamepix.yaml`; merged 2026-10-04). The Factory now has the profiles
  (`core/reference/platforms/gamepix.yaml`, `core/reference/publication/gamepix.yaml`), and
  strategy and tech-plan refuse the platform until the Factory pins a template release that
  carries the adapter (the lock's `platform_adapters`).
- **Platform prerequisites:** a publication profile may name what a person must have done or
  obtained first (`prerequisites`); readiness reports an applicable one HUMAN_REQUIRED until a
  person records it in `factory.publish.platforms.<id>.prerequisites_confirmed`.
  GameDistribution's `self-hosting` (written consent, one's own HTTPS host) is the first.

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
4. **The sdk step writes them on a retarget** (since 2.8.0): when the run's newest tech plan
   names other platforms than the checkout's `game.config.yaml`, `sdk` rewrites only
   `platforms` there and vendors the pinned profiles (`wgf_sdk/targets.py`, reusing init's
   `apply_platforms` and `vendor_profiles`), every pin checked against the Factory's profile
   before anything is written, and commits them with its integration - one keyed sdk commit.
5. Downstream reads: `sdk` and `verify` read the checkout's `game.config.yaml`;
   `store-listing` reads the verified build's platforms (the verification-report's
   `platform_readiness`; before 2.8.0 the scaffold-record, which a retarget leaves stale)
   unless `factory.listing.platforms` names them; `listing-validation` the listing;
   `release` the checkout and the verification's per-platform bundles; `platform-validate`
   the release-manifest.

### Why a retarget no longer re-runs develop

Every gate after develop pins the **developed commit**: review and sdk-review the commits
they read, production-quality and visual-qa the commit `release` checks against the
sdk-report's `base_commit_sha` (`wgf_release/lineage.py` `developed_commit`), the
prototype-report the commit sdk must build on. Init's commit sits *below* develop's, so a
retarget through init moves HEAD to a commit no gate judged and forces the whole develop round
again - an agent session for a change that touches no game code. The lineage rule
(`wgf_verification/lineage.py`) already admits exactly one kind of commit between develop's
and the shipped one: this run's keyed sdk commits, recorded in the run's ledger. The sdk step
is also the step that wires each platform's SDK. So the retarget's write moved there: the
sdk commit carries the new `platforms` and profiles, sdk-review reads it (the diff is
prototype commit..sdk commit, so the reviewer sees the retarget), verify builds and judges
every new target's own bundle, and G4 is decided again on that verification. Nothing in the
lineage rule changed; `wgf_sdk.commit.owns` admits `game.config.yaml` and
`config/platforms/*` as paths the sdk step may write.

What still re-runs: strategy and G2 (the new `platform_set`), design (it binds locales, ad
cadence and placements to the platforms), tech-plan and G3 (the platforms the sdk step
writes), sdk, sdk-review, verify and G4, store-listing, listing-validation, release, and the
publish group. What does not: init, greybox, greybox-playability, assets, develop,
playability, production-quality, visual-qa, review - their reports stay valid because the
developed commit did not move. A retarget that also changes the locales the game must ship
(a Yandex target on a game without `ru`) fails verify's `platform.requirements:yandex`, and
then develop does run: that is a game change.

### What the Factory cannot do today (gaps, smallest proper fix)

1. **One package per target - done in 2.8.0, on template contract 1.** For a title with
   more than one target, verify builds each platform against
   `build/platforms/<id>/game.config.json` (that platform alone) through the pinned
   template's own `WGF_GAME_CONFIG` override, keeps each bundle in `build/platforms/<id>/dist/`,
   judges each (`build.platform:<id>`, `platform.build-target:<id>`, requirements and
   profile assertions on its own bundle), requires every target, and pins each digest in the
   verification-report; release packages each with `release:package --platform <id>` from its
   own bundle and refuses a target without a verified one
   ([verification-module.md](verification-module.md#one-bundle-per-platform),
   [release-module.md](release-module.md#one-package-per-target-platform)). A [yandex,
   crazygames, y8] title ships three zips with three different bundles. When the Factory pins
   a template release carrying contract 2, its `build:platforms` is used instead - the
   Factory already recognizes it (`wgf.template.contract: 2` in package.json).
2. **No person could choose the platforms** - fixed: `factory.strategy.platforms` (or the
   step's `with:`) replaces the candidate list and the fit ranking (first = required); the
   compatibility checks and `max_platforms` still apply, and G2 still approves.
3. **No command re-runs "from sdk to release" inside an existing run.** `wgf resume --from`
   needs a resumable run, and a run whose last command was a group (`wgf plan --run`,
   `wgf publish --run`) ends `COMPLETED` "left scope" (`wgflib/workflow/engine.py`); `--from`
   with `--run` is refused by design (`docs/workflow-engine.md`). `wgf new-game --run` skips
   every completed non-gate step, so after a re-plan it would **skip sdk** and re-ask G4
   about the old build - a trap, not a path (only gates are re-checked). The path is one
   `--run <id> --force` command per step (below). Fix (a core engine change, so proposed):
   let `wgf resume <run> --from STEP` continue a run that ended by leaving its scope.
4. **A Y8 build without its IDs is silently SDK-less.** The template warns; the Factory passes
   no `WGF_*` to game builds unless `factory.agents.game_env_passthrough` lists them
   (`wgflib/agentenv.py`). With per-platform builds the y8 bundle is now its own, so the gap
   is visible in it alone - but verify still cannot see it: the profiles name no head script,
   and `y8_sdk_present` reads an echoed fact. Fix (small, proposed): a profile field naming
   the build environment a target needs (`WGF_Y8_APP_ID`), which verify or tech-plan refuses
   without.
5. **Neither init nor the sdk retarget removes a dropped platform's vendored profile**
   (`vendor_profiles` starts from the existing `pinned.json`): after a retarget
   `config/platforms/poki.yaml` and its pin stay. Harmless to validation (targets come from
   `game.config.yaml`); untidy.
6. **The Y8 listing renders and validates UNKNOWN** (all-null `store_listing`): a rendition is
   made at the canonical sizes, every image and text limit is reported UNKNOWN, never passed;
   UNKNOWN never fails listing validation and `release` does not refuse it. A person reads the
   Y8 submission form.
7. **Runtime facts are measured once,** against the build target's bundle (`test:verify`
   serves `dist/`); each other platform's assertions read its own bundle's static facts
   (size, locales, screenshots) and those shared runtime facts. Every bundle is the same game
   code with another adapter, and no portal SDK loads in the local browser either way.

### What each step does on a retarget

| Step | Re-run? | Agent session? | Why |
|---|---|---|---|
| strategy, G2 | yes | no (a person decides G2) | new `platform_set` (and profile 1.2.0 pins) |
| design | yes | yes when `factory.design.author: agent` (both validation projects) | binds locales, ad cadence, placements per platform |
| tech-plan, G3 | yes | no (a person decides G3) | `repo_params.game_config.platforms` |
| init | **no** | - | the sdk step writes the platforms after develop's commit |
| greybox, greybox-playability, assets | **no** | - | the developed commit does not move |
| develop, playability, production-quality, visual-qa, review | **no** | - | their reports pin the developed commit, which does not move |
| sdk | yes | no (deterministic) | writes the new platforms and profiles, wires each SDK, one keyed commit |
| sdk-review | yes | yes (the reviewer) | the sdk commit now carries the retarget |
| verify, G4 | yes | no; G4 is a person | one bundle per target, each judged; G4 must be decided again |
| store-listing, listing-validation | yes | store-listing: yes when a copy writer is configured (the 3D project), else no | renditions for the new targets under the 1.2.0 blocks |
| release | yes | no | one package per target, from its own bundle |
| platform-validate, G5, G6, submit | yes (`wgf publish --run`) | no; G5/G6 are a person's | one publication record per packaged target |

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
       platforms: [yandex, crazygames, y8]   # first = required (the build target, built last)
     # agents:
     #   game_env_passthrough: [WGF_Y8_APP_ID, WGF_Y8_GAME_ID]   # once the IDs exist (gap 4)
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

3. From sdk, one step per command (each stops if its step fails; read
   `bin/wgf status $RUN` before the next) - **not** init or develop:

   ```bash
   for s in sdk sdk-review verify; do
     bin/wgf $s --run $RUN --force || break
   done
   bin/wgf prototype-review --run $RUN --force   # G4 -> WAITING
   bin/wgf decide $RUN pass                       # a person, after reading the evidence
   for s in store-listing listing-validation release; do
     bin/wgf $s --run $RUN --force || break
   done
   bin/wgf publish --run $RUN --force             # platform-validate, G5, G6 (a person), submit (dry-run)
   ```

   `sdk` logs "sdk retargets the checkout to the tech plan's platforms" and its commit holds
   `game.config.yaml` and `config/platforms/{yandex,crazygames,y8}.yaml` + `pinned.json`.
   `verify` then runs three builds (`build/platforms/{crazygames,y8,yandex}/`, yandex last)
   and `release` writes `yandex.zip`, `crazygames.zip`, `y8.zip`. A step that routes
   elsewhere (verify -> develop, sdk-review -> develop) ends the one-step command "left
   scope": that is a real game change, and the sequence from Part 2's first version (init
   onwards) no longer applies either - run develop and continue from it. The develop session
   budget is not refilled by `--run`; a develop step BLOCKED on it is resumed with
   `bin/wgf resume $RUN --budget-sessions N`.

The previous sequence (`init` through `verify`, every step re-run) is still correct, only
dearer: it re-runs develop and every gate after it.

### Verdict per platform

| Platform | Brick Breaker Worlds / Sky Marble: blocked in code | External (account, partnership, portal) |
|---|---|---|
| Yandex | Packageable after the retarget above (required). Known risks: PNG screenshots with alpha (24-bit asked); the 70%-gameplay media rule is a person's check; since 1.3.0 the listing needs the MP4 horizontal trailer, screenshots per platform and orientation are a person's count (gap Y-2), and no context-menu suppression was found in either game (gap Y-3) | Developer profile, contract (licensing model or YAN), moderation 3-5 days, cloud-saves switch in the draft, age rating, how-to-play and SEO texts |
| CrazyGames | Packageable alongside Yandex since 2.8.0 (its own bundle, with the CrazyGames head script, gap 1). The listing now needs a 1080p trailer under 20 s (store-listing 1.1.0) and a portrait video (manual) | Developer Portal account, Progress Save toggle, Basic Launch (ads disabled, expected) and CrazyGames' Full Launch decision |
| Y8 | Packageable alongside Yandex since 2.8.0 (its own bundle, gap 1); the build needs `WGF_Y8_APP_ID` / `WGF_Y8_GAME_ID` passed through, or it ships SDK-less, and verify cannot tell (gap 4) | Developer account and approved Studio, the App ID and Game ID from the portal, review, the listing fields (undocumented) |
| GameDistribution | Tech plan blocks without a registered Game ID; with one, packageable alongside the others (its own bundle) | Account (no domain needed; Company required), Game ID from the panel before the build, rewarded flag, pre-roll viewed once from the upload view, publication request button; self-hosting only for real multiplayer with written consent and one's own HTTPS host |
| GamePix | Profile added; no adapter at the pinned template (template#23 on main), so strategy and tech-plan refuse it: HUMAN_ACTION_REQUIRED, a template release carrying the adapter, then the pin | Account (18+, no domain); exclusivity default ("Allow Distribution"); child-directed and AI declarations on every upload |
| Poki | Deferred: the current r1 package stays as it is | - |

### Publication adapter status per portal

What `scripts/wgf_publish/adapters/<id>.py` is today (docs/publish-module.md, "One adapter per
portal"), in four words only: IMPLEMENTED (the adapter exists, with its own status mapping,
review handling and handoffs), FIXTURE_VALIDATED (run through the real executor in headless
Chromium against the portal's flavor of the fixture portal - never the portal), UNVERIFIED
(not exercised against the live console by a person; every console label is documented or a
hypothesis), HUMAN_ACTION_REQUIRED (something a person must do before it can run at all).

| Portal | Adapter status |
|---|---|
| Yandex | IMPLEMENTED, FIXTURE_VALIDATED, UNVERIFIED |
| CrazyGames | IMPLEMENTED, FIXTURE_VALIDATED, UNVERIFIED (zip vs files upload: both modeled) |
| Y8 | IMPLEMENTED, FIXTURE_VALIDATED, UNVERIFIED; HUMAN_ACTION_REQUIRED: the Studio |
| GameDistribution | IMPLEMENTED, FIXTURE_VALIDATED, UNVERIFIED; HUMAN_ACTION_REQUIRED: the account, the terms, the Game ID entered in game.config.yaml |
| GamePix | IMPLEMENTED, FIXTURE_VALIDATED, UNVERIFIED; HUMAN_ACTION_REQUIRED: a template release carrying the GamePix SDK adapter, and the pin moved to it (the adapter refuses BLOCKED until a build carries the SDK) |

For every portal: `automation_terms: unverified` in its publication profile, so the publish
step stops HUMAN_REQUIRED before the adapter runs until a person records the terms finding
(`factory.publish.platforms.<id>.terms_confirmed`) - HUMAN_ACTION_REQUIRED as well.

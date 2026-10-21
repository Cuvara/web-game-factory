# Platform SDK integration — how it is verified, and what is known

The `sdk` workflow step (`scripts/wgf_sdk/`) produces the `sdk-report`. It does not write
SDK code and it never publishes; it establishes, per targeted platform and per feature,
whether the build's integration works and how that was observed.

Written 2026-10-10 against template v1.2.0 (b106261). The pin is now v1.2.1 (4b74b08,
`workspace/config/template.lock.json`, whose `platform_adapters` lists the same ids): the same
adapters, with the fixes its CHANGELOG lists - one adapter per build, Yandex rewarded video
shown without `onClose(wasShown)`, a Y8 capped break not counted as shown. Where a row below
describes one of those behaviours, it describes v1.2.0:

```
Game (web-game-template src/)
 │  calls only
 ▼
@wgf/platform-sdk  Platform interface            packages/platform-sdk/src/types.ts
 │                 createPlatform(id)            packages/platform-sdk/src/registry.ts
 ├── generic-web       no portal SDK
 ├── gamevui           no SDK exists (the portal publishes none): a no-SDK adapter
 ├── yandex            yandex.ts, yandex-sdk.ts, yandex-storage.ts
 ├── poki              poki.ts                    (Poki is deferred as a target since 2026-10-04)
 ├── crazygames        crazygames/                (on the pinned release since v1.2.0)
 ├── y8                y8/
 ├── gamedistribution  gamedistribution/
 └── gamemonetize      gamemonetize.ts
```

GamePix has a Factory profile but no adapter at the pin (strategy and tech-plan refuse it).
At v1.2.0 every adapter is compiled into every bundle, whichever one boots; at v1.2.1 (the
pin) a build carries only its platform's adapter and generic-web: see
[Portal SDKs in each bundle](platform-targets-2026-10.md#portal-sdks-in-each-bundle) and
[verification-module.md](verification-module.md#portal-sdks-in-a-bundle).

## What the step does

1. **Plan** — reads the game repository's `game.config.yaml` (pinned `<id>@<version>`
   platforms, committed `monetization.ad_kinds`) and the pinned profiles in
   `core/reference/platforms/`, and derives which features each platform requires
   (`scripts/wgf_sdk/plan.py`).
2. **Evidence** — runs `pnpm sdk:conformance` in the game repository: one scenario matrix over
   every adapter against fake portal SDKs (SDK unavailable, init failure, ad unavailable, ad
   closed early, reward callback, pause/resume, storage, platform not configured, and a real
   `Game` bound to each adapter). With `browser: true` it also runs `pnpm test:sdk:browser`:
   the real PixiJS and Three.js builds booted in Chromium with mocked or blocked portal
   scripts. See web-game-template `docs/platforms/sdk-conformance.md`.
3. **Report** — maps scenario results to `sdk-report` statuses: all passed → `working`; any
   failed → `partial`; skipped (no adapter) → `not-started`; not applicable and not required
   → `not-required`. A required platform that is not `working` fails the step, with the
   report persisted as evidence.

The runner's whole command surface is `pnpm sdk:conformance`, `pnpm test:sdk:browser` and
`git rev-parse HEAD`. It never publishes: publication is the Factory's `publish` group behind a
person's G6 ([publish-module.md](publish-module.md)); CI never publishes a game.

## What verify adds about the built bundles (since 2.8.0)

The sdk-report says what the integration does against fake portal SDKs; it does not say what
a platform's built bundle carries. The verify step measures that from the built files
(`wgflib/portal_sdks.py`, `core/reference/portal-sdks.yaml`): `platform.foreign-sdk:<id>` (no
other portal's SDK; plus the template's own `scripts/crazygames-audit.mjs` on the crazygames
bundle when the checkout ships it) and `platform.sdk-loaded:<id>` (CrazyGames, Y8: the page
loads the portal's script). The profiles' `<id>_sdk_present` assertions are not counted on
template contract 1: `collect-facts.mjs` echoes the platform id into `package.platform_sdk`
without reading the bundle. platform-validate refuses a package that carries another portal's
SDK or does not load its own (guards `portal_sdk_isolated`, `portal_sdk_loaded`).

## Ads on every target platform (since 2.8.3)

On 2026-10-21 Y8 returned a game the Factory built with *"Dear Dev, the game is missing ads. Please fix it and re-upload with correct promo images"*. The sdk-report had called y8's ads `not-required`, because no
placement of the plan - generated before the title was retargeted to y8 - listed y8. Verify
now checks, per target, that every ad kind the title commits to and the target's profile
offers is integrated: `platform.ads-integrated:<id>`
([verification-module.md](verification-module.md#ads-integrated-per-target-platform)), on the
plan and on the bundle. In the bundle it looks for the portal's **ad call**
(`core/reference/portal-sdks.yaml` `ad_calls`, 1.1.0) and for the plan's placements as
compiled (esbuild keeps an object literal's keys and strings). The ad call alone proves only
that the adapter's ad path is built in - the adapter is bundled whether or not the game asks
for an ad - so the plan is read as well.

Each ad-call pattern was measured on real template v1.2.2 builds, one per platform
(2026-10-21, `WGF_GAME_CONFIG` naming one platform, `ad_kinds: [interstitial, rewarded]`):

| Platform | Ad call (pattern) | Its own bundle | Any other of the five |
|---|---|---|---|
| y8 | `.showAd(` | yes | no |
| yandex | `adv.showFullscreenAdv` / `adv.showRewardedVideo` | yes | no |
| crazygames | `ad.requestAd(` | yes | no |
| poki | `commercialBreak(` / `rewardedBreak(` | yes | no |
| gamepix | `interstitialAd(` / `rewardAd(` | yes | no |

GameDistribution (`gdsdk.showAd`) and GameMonetize (`sdk.showBanner`) have no `ad_calls`
entry yet: no build of theirs was measured. A portal without one is judged on the plan alone.
The sdk step's own changes are in
[platform-architecture.md](platform-architecture.md#ads-on-every-target-platform-since-283).

## Checked against documentation — 2026-09-23 (historical; see the status column)

Sources: Yandex Games SDK v2 (yandex.com/dev/games/doc/en), CrazyGames HTML5 SDK v3
(docs.crazygames.com), Poki HTML5 SDK (developers.poki.com). gamevui.vn returned 403 to
automated fetches; its claims rest on web-game-template `docs/platforms/gamevui/`.

This section records a read of the portals' documentation on 2026-09-23 against the 1.1.0
profiles. The adapters matched the documented call surfaces; the profiles did not, in the
places below. Profiles are pinned by titles, so each correction is a **new profile version**.
The last column is the profile in `core/reference/platforms/` on 2026-10-10 (yandex,
crazygames and y8 were re-read on 2026-10-04 and 2026-10-07:
[platform-targets-2026-10.md](platform-targets-2026-10.md)); it states what the profile says,
not what a portal does - no portal behaviour was observed for this document.

| Profile (2026-09-23) | Said | Documentation (2026-09-23) | Profile on 2026-10-10 |
|---|---|---|---|
| `yandex@1.1.0` | `locales_required: [ru]`, blocking `yandex_ru_locale_present` | No language is mandatory; requirement 2.14 is automatic language detection through the SDK | `yandex@1.3.0` keeps `ru` required, commented as a Factory choice, not a portal rule; `en, tr, zh, ko, hi, vi` recommended |
| `yandex@1.1.0` | `interstitial_min_interval_s: 60` | Not documented; "frequency is controlled by Yandex Games" | `yandex@1.3.0` keeps 60 s, commented as the Factory's own floor (the template's adapter keeps it too) |
| `yandex@1.1.0` | rejection "does not report loading progress through the SDK" | There is no progress API; the check is `LoadingAPI.ready()` (1.19.2) | `yandex@1.3.0`: `loading_api: required`, ready() within 90 s (1.19.2) |
| `yandex@1.1.0` | `max_bundle_mb: 100` | Correct, but uncompressed (1.21) | `yandex@1.3.0`: 100, commented as uncompressed (1.21) |
| `poki@1.1.0` | `max_bundle_mb: 150` | "initial download should not exceed 5MB and 8MB in total" | unchanged (`poki@1.1.0`): Poki is deferred, no re-read |
| `poki@1.1.0` | `interstitial_min_interval_s: 120` | "Do not implement internal ad timers" | unchanged (deferred) |
| `poki@1.1.0` | `no_external_links` | Links are allowed through `PokiSDK.openExternalLink`; all other external requests are blocked | unchanged (deferred) |
| `crazygames@1.1.0` | `screenshots_min: 4` | Three covers (1920×1080, 800×1200, 800×800) and a 15–20 s video | `crazygames@1.3.0`: `screenshots_min: 0`; covers and video in its `store_listing` block |
| `crazygames@1.1.0` | — | Missing: ≤ 50 MB initial on desktop, ≤ 20 MB initial on mobile, ≤ 1500 files | `crazygames@1.3.0`: `max_bundle_mb: 250`; the initial-download and file limits are in its comments only (no field) |
| `gamevui@1.1.0` | ads, 50 MB, `vi`, 120 s | No public source for any of it (`status: unverified` is right). Without an SDK, a game cannot request portal ads | unchanged (`gamevui@1.1.0`, `status: unverified`) |

The design module reads these profiles as binding (interstitial cooldown, required
locales), so a revised profile changes new designs — which is the point of versioning them.

## Known limitations

- **Every bundle carries every adapter** at v1.2.0 - a CrazyGames or Y8 package carries
  Poki, Yandex and other portals' SDK code, which the template's own CrazyGames audit FAILs
  and platform-validate refuses (above). Cleared from the v1.2.1 pin (the reviewed backport,
  tagged at 4b74b08), whose builds carry the selected adapter alone; a game created on v1.2.0
  keeps the limitation until it applies the 1.2.1 patches.
- **CrazyGames** — an adapter at the pin (`adapters/crazygames/`, ads interstitial and
  rewarded, auth optional); the platform contract has no banner call, so banners are not
  claimed although the profile lists them.
- **Y8** — the build carries the Y8 SDK only when given `WGF_Y8_APP_ID` (an id Y8 issues
  when a person creates the game); without it the bundle runs SDK-less, which verify reports
  BLOCKED (`platform.sdk-loaded:y8`).
- **GameVui** — no SDK exists to integrate. At the pin `createPlatform("gamevui")` returns a
  no-SDK adapter (`adapters/gamevui.ts`): nothing to initialise, no ad the game can request,
  local saves; the profile's ad kinds are ads the portal shows around the game.
- **Yandex** — the SDK is injected from script where the docs show a static tag (1.19.1:
  initialise "exactly as described"); confirm `IT` in the draft-mode debug panel. Banners,
  IAP, `EXIT`/`HISTORY_BACK` not implemented (as read 2026-09-23; not re-checked here).
- **Poki** — `openExternalLink`, URL parameters and `movePill` not implemented (as read
  2026-09-23; Poki is deferred).
- **All** — fakes follow the documented API; real portal behaviour (fill, timing, a failed
  init) is only settled in each portal's draft/QA mode, which a person observes in the
  portal's console; none has been observed for this document.

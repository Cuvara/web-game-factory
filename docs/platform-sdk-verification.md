# Platform SDK integration — how it is verified, and what is known

The `sdk` workflow step (`scripts/wgf_sdk/`) produces the `sdk-report`. It does not write
SDK code and it never publishes; it establishes, per targeted platform and per feature,
whether the build's integration works and how that was observed.

```
Game (web-game-template src/)
 │  calls only
 ▼
@wgf/platform-sdk  Platform interface            packages/platform-sdk/src/types.ts
 ├── generic-web adapter   (also the GameVui build — GameVui publishes no SDK)
 ├── Yandex adapter
 ├── Poki adapter
 └── CrazyGames adapter    (on its own branch; not on template main yet)
```

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
`git rev-parse HEAD`. Publishing stays in the game repository's release pipeline, behind G5
and G6.

## Checked against current documentation — 2026-09-23

Sources: Yandex Games SDK v2 (yandex.com/dev/games/doc/en), CrazyGames HTML5 SDK v3
(docs.crazygames.com), Poki HTML5 SDK (developers.poki.com). gamevui.vn returned 403 to
automated fetches; its claims rest on web-game-template `docs/platforms/gamevui/`.

The adapters matched the documented call surfaces. The **platform profiles** in
`core/reference/platforms/` did not, in these places. Profiles are pinned by titles, so
each correction is a **new profile version**, not an edit — none is made here:

| Profile | Says | Current documentation |
|---|---|---|
| `yandex@1.0.0` | `locales_required: [ru]`, blocking `yandex_ru_locale_present` | No language is mandatory; requirement 2.14 is automatic language detection through the SDK |
| `yandex@1.0.0` | `interstitial_min_interval_s: 60` | Not documented; "frequency is controlled by Yandex Games" |
| `yandex@1.0.0` | rejection "does not report loading progress through the SDK" | There is no progress API; the check is `LoadingAPI.ready()` (1.19.2) |
| `yandex@1.0.0` | `max_bundle_mb: 100` | Correct, but uncompressed (1.21) |
| `poki@1.0.0` | `max_bundle_mb: 150` | "initial download should not exceed 5MB and 8MB in total" |
| `poki@1.0.0` | `interstitial_min_interval_s: 120` | "Do not implement internal ad timers" |
| `poki@1.0.0` | `no_external_links` | Links are allowed through `PokiSDK.openExternalLink`; all other external requests are blocked |
| `crazygames@1.0.0` | `screenshots_min: 4` | Three covers (1920×1080, 800×1200, 800×800) and a 15–20 s video |
| `crazygames@1.0.0` | — | Missing: ≤ 50 MB initial on desktop, ≤ 20 MB initial on mobile, ≤ 1500 files |
| `gamevui@1.0.0` | ads, 50 MB, `vi`, 120 s | No public source for any of it (`status: unverified` is right). Without an SDK, a game cannot request portal ads |

The design module reads these profiles as binding (interstitial cooldown, required
locales), so a revised profile changes new designs — which is the point of versioning them.

## Known limitations

- **CrazyGames** — no adapter on template main; a CrazyGames-required title reports
  `not-started` and fails the step. Its branch does not implement banners, auth or happytime.
- **GameVui** — no SDK exists to integrate. `createPlatform("gamevui")` throws by design, so
  a title whose *required* platform is `gamevui` cannot boot and reports `not-started`; list
  GameVui as optional and ship the generic-web build.
- **Yandex** — the SDK is injected from script where the docs show a static tag (1.19.1:
  initialise "exactly as described"); confirm `IT` in the draft-mode debug panel. Banners,
  IAP, `EXIT`/`HISTORY_BACK` not implemented.
- **Poki** — `openExternalLink`, URL parameters and `movePill` not implemented.
- **All** — fakes follow the documented API; real portal behaviour (fill, timing, a failed
  init) is only settled in each portal's draft/QA mode, which is a release-pipeline step.

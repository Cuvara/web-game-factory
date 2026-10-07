# Yandex readiness of the two validation titles, 2026-10-05

Publishing phase 1 of 4 (Yandex, then CrazyGames, Y8, GamePix). This records how ready the
human-accepted release artifacts of Brick Breaker Worlds (2D, PixiJS) and Sky Marble (3D,
three.js) are for Yandex Games. It stops before any real login. Nothing was logged in to,
uploaded, submitted or published. The game repositories were read only: copies of
`release/r1/` went to `/tmp`, and their sources were read with `git show` at the tags.

The Factory side is on branch `dyCuong03/publish-yandex`: yandex@1.3.0 and yandex@2.3.0,
`core/reference/publishing-workflow.yaml` 1.0.0, and the listing preflight checks. See
docs/publish-module.md ("The publishing workflow", "Yandex recipe") and
docs/platform-targets-2026-10.md ("Yandex, re-read 2026-10-05").

**Verdict for both titles: BLOCKED before the portal.** Neither r1 release has a Yandex
build, so the Yandex target is RELEASE_ARTIFACT_MISMATCH for any upload. A Yandex package
has to be a new release candidate with its own G5 and G6, and three things must be fixed
first.

## The accepted artifacts

`release/` is git-ignored in both repositories, so the artifacts exist only in the working
tree (`C:/Users/duycu/wgf-runs/val-*/games/<title>/release/r1/`). They are not in the tagged
tree. The manifests name the tagged commits.

| | Brick Breaker Worlds | Sky Marble |
|---|---|---|
| Tag / commit | `baseline-r1` = `96f5ceaa7abf165594b06cfb8c69eec9f0612ec1` | `baseline-r1` = `64ff4c69f05cc259fa9bfda72305fd988ff94d0e` |
| Release id, state | `r1`, `draft` (frozen_at null) | `r1`, `draft` (frozen_at null) |
| Run | `new-game-20261003-081154-4e5e0a` (release visit 1) | `new-game-20261003-082542-0de9b5` (release visit 3) |
| Manifest `provenance.content_hash` | `sha256:946e455a79f86d3fab6dbb618378a9fbc70049eba7fb479fa5780fc6572e2cb0` | `sha256:1fbabf0e3fcb025f5736428033010608cdfd461c25cf76a41ee1f552f8c7a4ca` |
| manifest.json file sha256 | `68ef0157...8bb331` | `48703454...71f97b` |
| Template | v1.2.0 `b106261` | v1.2.0 `b106261` |
| Targets | poki@1.1.0 required; crazygames@1.1.0, yandex@1.1.0 optional | poki@1.1.0 required; yandex@1.1.0, crazygames@1.1.0 optional |
| Packages | `poki.zip` only: 6.077 MB, 78 files, `sha256:697622ca...cef9dd7` (checksums.txt agrees) | `poki.zip` only: 1.716 MB, 52 files, `sha256:e3013274...48c2` (checksums.txt agrees) |
| **Yandex package** | **none** | **none** |
| Listing | `listing/platforms/yandex/` rendered under yandex@1.1.0 | the same |

`wgf-publish.py readiness --manifest <copy>` returns READY for both, but only for the poki
package. `readiness --manifest <copy> --platform yandex` (new) returns `platform_packaged RED:
yandex: targeted but not packaged in release r1 (packages: poki)`, so readiness is
**BLOCKED**.

## Requirement by requirement (Yandex, against yandex@1.3.0)

| Requirement | Brick Breaker Worlds | Sky Marble |
|---|---|---|
| Yandex zip (index.html at the root, <= 100 MB uncompressed, names) | BLOCKED: no build | BLOCKED: no build |
| SDK, LoadingAPI.ready, GameplayAPI, pause/resume, i18n.lang | UNKNOWN on a Yandex build. The template adapter at the pin does all of it, the game passes `platform.language` to i18n, and verify must run on a yandex build | UNKNOWN, the same |
| Rewarded reward granted (REQ 4.5) | **BLOCKED**: template v1.2.0 bug. The real SDK closes a rewarded video with `onClose()` and no `wasShown`, so `shown` is false and `gameplay.ts` grants nothing (`rewarded = result.shown && result.rewarded`) | **BLOCKED**: the same |
| Interstitial at logical pauses only (4.4) | READY: only when leaving the level-clear card, never before 2 clears in a session, at most every 180 s of session clock | READY: only when leaving a result card, never before 2 finished runs, at most every 180 s |
| Rewarded optional, names the reward (4.5, 4.5.1) | HUMAN_REQUIRED: "EXTRA BALL" / "ЕЩЁ МЯЧ" names the reward but does not say it is an ad | HUMAN_REQUIRED: "Continue +N s" / "Продолжить +N с", the same |
| Sound and play paused during ads, focus loss (4.7, 1.3) | READY in code (`platform/bind.ts` ad pause, mute, visibility). Unverified on the real SDK | READY in code, the same |
| Saves (1.9) | READY: through `platform.storage` (Yandex storage adapter) | READY: the same |
| Title <= 50 | READY ("Brick Breaker Worlds") | READY ("Sky Marble") |
| Description 100-1000 (ru) | **FAIL**: ru long description is 34 chars | READY (949) |
| How to play 100-1000 (ru, controls text) | **FAIL**: ru controls empty | READY (173) |
| Short description <= 70 | READY (34) | FAIL as rendered (119). A re-render under 1.3.0 cuts it |
| Icon 512x512 PNG | FAIL as rendered (1024). A re-render makes 512 | the same |
| Cover 800x470 PNG | FAIL as rendered (1280x720). A re-render crops the 16:9 master | the same |
| Screenshots 16:9 / 9:16, long side 1280-2560, no alpha, >= 2 | FAIL as rendered (RGBA PNG). Sizes 1920x1080 / 1080x1920 are fine. A re-render writes RGB | the same |
| Horizontal video MP4 16:9 <= 28 s (required) | **BLOCKED**: only `trailer.webm`. The capture made no MP4 (no ffmpeg) | **BLOCKED**: the same |
| Grounded copy | READY | FAIL: ru feature bullet 6 states "9" (courses 5 and 9), which its source does not state (person-supplied ru copy) |
| Categories <= 2, tags <= 20, age rating | HUMAN_REQUIRED in the console (rendition: Arcade; 5 tags; age 3 -> a person picks 0+/6+...) | HUMAN_REQUIRED (Аркады; 10 tags) |
| Contract, terms, login | HUMAN_REQUIRED | HUMAN_REQUIRED |

The figures above come from `wgf-listing.py validate` on copies of each r1 listing, laid out
as the run directory the listing names, against the new profile.

## Monetization review (read only; game changes for a game specialist)

Both games make placements only through the template's `GameIntegration`, with
`ad_kinds: [interstitial, rewarded]` and `iap: false`. Neither shows a banner or calls the SDK
directly.

- **Brick Breaker Worlds**: `interstitial-between` fires in `#leaveClear()` when the player
  presses Next or Map on the clear card (`src/game/session.ts:592-607`). Replay does not
  fire it. The gates are `interstitialMinClears: 2` and `interstitialCooldownS: 180` on the
  session clock (`src/game/tuning.ts:82-89`). `rewarded-continue` gives one extra ball on the
  fail card after at least 20 s of play, once per level, and is granted only when the ad
  resolves rewarded (`session.ts:503-523`).
- **Sky Marble**: `interstitial-between` fires when the player leaves a result card for
  Retry, Next or Courses, never before 2 finished runs, at most every 180 s
  (`src/game/ads.ts`, `src/scenes/play-scene.ts:414-424`). `rewarded-continue` gives +N
  seconds after a time-over, once per run, and is granted only if rewarded
  (`ads.ts:49-61`, `play-scene.ts:443-460`).

Against Yandex: the placements are logical pauses (4.4), are user-initiated or
between-level, sit within the 2 s action-to-ad rule (the call follows the tap
synchronously), and are paused and muted around ads. They are compliant except for:

1. **Template bug (blocker, both)**: rewarded never pays on the real Yandex SDK. Fix it with
   template main `2f2c99d` (`fix(yandex): rewarded video counts as shown without
   onClose(wasShown)`, also `C:/Users/duycu/wgf-runs/backport-patches/0002-...patch`). The
   Factory route is a template release carrying it and the pin moved (golden runs at the
   new commit). For an already-scaffolded game the route is a backport commit in the game,
   made by the game specialist.
2. **Rewarded button labels (both)**: say it is an ad, for example a video/ad icon or "▶
   EXTRA BALL (ad)" / "Реклама: ещё мяч" (REQ 4.5.1). This is UI copy in `public/locales/*.json`
   plus an icon.
3. Optional, no rule requires it: Yandex controls frequency itself, so a 180 s cooldown is
   conservative. It could drop to the Factory's 60 s floor for more impressions without
   breaking any rule. That is the designer's choice and does not block.

## Fixture and dry-run status

`WGF_PUBLISH_BROWSER_TEST=1 python3 -m unittest scripts/tests/test_publish_portals.py` ran
28 tests, OK, in WSL headless Chromium (`~/.cache/ms-playwright/chromium-1243`). They
include `Browser.test_yandex`, `Browser.test_yandex_update_of_a_live_game_goes_through_create_draft`
and the Yandex rules (third new-game request refused, language tabs language by language,
Verified is a person's publish). Yandex is **FIXTURE VERIFIED**: the profile's flow ran
through the real executor against the fixture portal's `yandex` flavor, never the real
console. No real-console dry run has happened, because it needs a person's login.

## What a person does next (in order)

1. **Account**: create or confirm a Yandex ID with a Yandex mailbox. Create the developer
   profile at `https://games.yandex.com/console/`, then sign the contract: the unified
   licensing contract in the Console (Russian legal entity or sole proprietor), otherwise a
   Yandex Advertising Network agreement (partner.yandex.com, about 3 business days' review).
   Add payout details. Read the Publishing License Agreement
   (`https://yandex.com/legal/licensegames/en/`) and the placement rules
   (`https://yandex.com/legal/yandexgames/en/`).
2. **Terms**: decide whether automated use of the console is acceptable to you, and record
   it as `factory.publish.platforms.yandex.terms_confirmed` (the profile is
   `automation_terms: unverified`, so the publish step stops before the console until then).
3. **Observe the real console** (read-only, your login, nothing clicked by the tool except
   what you do):
   `python3 scripts/wgf-publish.py observe yandex --checkout C:/Users/duycu/wgf-runs/val-2d/games/brick-breaker-worlds`
   Then run `python3 scripts/wgf-publish.py observe-summary <the printed observation dir>` to turn what you saw into
   profile corrections (labels, the language tabs, the upload widget, where the app id shows).
4. **Game fixes (game specialist)**: backport the rewarded fix, add the ad marker on both
   rewarded buttons, write ru long description and ru controls of 100+ characters
   (Brick Breaker Worlds), and correct the Sky Marble ru feature bullet 6.
5. **Factory run for a Yandex release candidate per title**: retarget with
   `factory.strategy.platforms: [yandex, ...]` (docs/platform-targets-2026-10.md Part 2),
   re-run from the plan with the new profiles, and have `ffmpeg` on PATH at store-listing
   so the MP4 trailer exists. The result is a new release with `yandex.zip`. A person then
   decides G4, G5 and G6 for it. r1 stays as it is.
6. **Dry run on the real console** after G6:
   `bin/wgf publish --run <run-id> --platform yandex` with `factory.publish.mode: dry-run`.
   You log in in the opened window, and it ends DRY_RUN. Then switch to `mode: live` +
   `WGF_PUBLISH_LIVE=1` for the upload (UPLOAD_COMPLETE), then
   `bin/wgf decide <run-id> submit` for the one moderation request, and track it with
   `bin/wgf publish --run <run-id> --platform yandex --track`.
7. In the draft: age rating, categories, tags, "Postpone publication" (so a pass lands in
   Verified and you publish), the AI-descriptions switch, Developer's comment. On Verified,
   the Publish click is yours, followed by `bin/wgf decide <run-id> done`.

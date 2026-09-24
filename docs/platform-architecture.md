# Platform Architecture

Three distinct concerns, deliberately separated. Collapsing any two of them is how a factory
becomes coupled to the portals it happens to have started with.

| Concern | What it is | Where it lives |
|---|---|---|
| **Platform intelligence** | What a portal rewards, who plays there, how it monetizes | `core/reference/platforms/*.yaml` (data) |
| **Platform SDK** | Runtime integration: ads, saves, leaderboards | `web-game-template` platform abstraction (code) |
| **Publishing** | Packaging, validation, submission, status | `release` role + `platform-publication` machine |

Platform intelligence informs *which game to build*. The SDK is *how the game runs*.
Publishing is *how a build reaches players*. They change at different rates for different
reasons.

---

## Platform profiles are data

Adding a platform is **one new file and zero changes anywhere else** — no code in `core/`, no
new stage, no schema edit. That is what keeps the Factory platform-independent.

```yaml
id: yandex
version: 1.0.0
status: unverified

capabilities:
  ads: [interstitial, rewarded, banner]
  iap: true
  cloud_saves: true

requirements:
  locales_required: [ru]
  max_bundle_mb: 100
  loading_api: required

ads:
  interstitial_min_interval_s: 60

review:
  process: manual
  typical_days: [1, 5]
  common_rejections:
    - Missing or machine-translated Russian localization.

assertions:
  - id: yandex_ru_locale_present
    check: { left: package.locales, op: in, right: [ru] }
    severity: blocking
```

Shipped profiles: `yandex`, `crazygames`, `gamevui`, `poki`, `y8`, `gamedistribution`,
`gamemonetize`, `generic-web`. All except `generic-web` are marked `status: unverified` —
their figures are starting points to be corrected against each portal's own documentation.
**Treat an unverified number as a hypothesis.** `y8` and `gamedistribution` were upstreamed
from web-game-template v1.1.0's proposals, `gamemonetize` written from its audit
(`docs/platforms/gamemonetize.md` there); figures the portals do not document are left out.

`requirements.game_id` says whether the portal issues a per-title Game ID the build carries
(`required`: GameDistribution; `optional`: GameMonetize; absent: none). The tech plan takes
it from `workspace/titles/<title-id>/portals.yaml` and blocks when a required one is missing
(`docs/techplan-module.md`, *Portal registrations*). Y8's App ID and Game ID are build-time
environment (`WGF_Y8_APP_ID`, `WGF_Y8_GAME_ID`), never game.config.yaml.

Platform ids must match the strings used in `web-game-template/game.config.yaml`.

---

## Read three times, with rising strictness

This is the correction to the most expensive defect in the original workflow, where platform
requirements surfaced at `PLATFORM VALIDATION` — after the build.

| Read at | Used as | Strictness |
|---|---|---|
| Opportunity scoring | `platform_fit` inputs, `scoring_hints`, vetoes | **advisory** |
| Strategy / design | Localization, ad cadence, bundle size, orientation, supported placements | **binding on the design** |
| Release validating | `assertions[]` run against the built package | **binding on the build** |

By the third read you are **re-checking a known constraint**, never discovering one. If
validation surprises you, the design drifted — and that is a design conversation, not a
packaging tweak.

Design records what it absorbed in `game_design.platform_constraints_applied`. An empty list
on a title with required platforms means the profiles were not read.

## Profiles are versioned and pinned

A strategy pins `profile_version` per platform; a release manifest carries it into the build;
validation runs the **pinned** version's assertions, not the current ones.

That keeps a build reproducible against the compliance rules that were in force when it was
approved. Validating against a profile that has since changed produces failures that did not
exist when the work was signed off.

`game.config.yaml` therefore carries pinned entries rather than bare strings:

```yaml
platforms:
  - { id: yandex,      profile: yandex@1.0.0,      role: required }
  - { id: crazygames,  profile: crazygames@1.0.0,  role: optional }
```

---

## Platform SDK abstraction

Game code calls the template's abstraction. It **never** calls a portal SDK directly.

```ts
await platform.initialize()
platform.reportLoadingProgress(0.5); await platform.signalReady()
platform.gameplayStart(); platform.gameplayStop()
const { rewarded } = await platform.showRewarded()
await platform.showInterstitial()
await platform.storage.set("progress", json)
```

Adapters in `web-game-template/packages/platform-sdk/` implement it per portal. This is what
makes one build shippable to four portals, and what keeps the game independent of any of
them. The interface differs between template revisions — which adapters exist, whether
`adAvailability` is declared — so nothing in the Factory restates it; the `sdk` step reads it
off the game repository every time.

Wire this during **prototype**, not production. The prototype exists partly to prove that
monetization and SDK integration work in context; deferring them is how a title discovers at
release that its ad placement does not fit its loop.

### Integrating it into a game: the `sdk` step

`scripts/wgf_sdk` implements the workflow's `sdk` step, in two phases. The **integration**
phase, described here, connects the template's SDK to a game's gameplay, for exactly what
the game-design asks for. The **conformance** phase runs the game repository's
`pnpm sdk:conformance` against fake portal SDKs and says whether each adapter works — see
[platform-sdk-verification.md](platform-sdk-verification.md). One `sdk-report` carries both:
a feature both phases see takes the worse status, because an adapter the game never calls
is not integrated, and a wired game on a failing adapter is not working. The step writes
**no SDK**. The integration phase reads:

| Reads | For |
|---|---|
| `game-design` | Monetization placements, retention hooks and targets — what the game needs |
| `scaffold-record` | Which repository, and which platforms init configured |
| the game repository | `packages/platform-sdk` (API, registry, adapter capabilities), `game.config.yaml`, `src/` |

It writes three files and one patch into the game repository, convergently — a second run
changes nothing — and commits them (below):

- `src/platform/gameplay.ts` — `bootPlatform()` and `PlatformGameplay`: the hooks scenes call
  (`runStarted`, `continueFrom`, `gameOver`, `levelComplete`, `pause`/`resume`,
  `canOfferReward`/`offerReward`, `naturalBreak`, `save`/`load`), built only on the
  `Platform` interface. Portal-specific calls stay in the template's adapters.
- `src/platform/integration-plan.ts` — generated: each placement attached to a gameplay
  moment (`game-over`, `level-complete`, `pause-menu`) by reading its trigger.
- `tests/unit/platform/gameplay-integration.test.ts` — SDK-mock suite, one block per
  situation: SDK available, SDK unavailable, SDK initialization failure, ad unavailable, ad
  closed early, reward callback, pause/resume, platform not configured.
- `src/platform/game-integration.ts` (+ its test) — `PlatformGameIntegration`, the game's
  `GameIntegration` seam implemented on `PlatformGameplay`.
- `src/platform/integration.ts` — the seam's wiring, written over the develop step's
  default as a whole file with the same exports: `createGamePlatform()` boots through
  `bootPlatform` with the template's own `createPlatform` options (`platformOptions(entry)`
  + `virtual:platform-config`, so per-title Game IDs reach the adapter), and
  `createGameIntegration()` installs `PlatformGameplay` and returns the
  `PlatformGameIntegration`.

`src/main.ts` is never edited: it already boots through the seam, because the develop step
provided it and its conformance check requires it (`wgflib.gameseam`). A build whose main.ts
does not import and call `createGamePlatform` and `createGameIntegration` from
`./platform/integration.js`, or that calls `createPlatform` itself, is refused - `FAILED`,
not retryable, nothing written. (Before 1.1, the step patched main.ts with regular
expressions keyed to the template's boot lines, and reported "skipped" when a template
release changed them.) The game's calls do not change. Its placement ids (`rewarded("revive-after-crash")`) are
read from the source, attached to the design's moments like triggers are, and put in the
plan; an id at a moment where the design placed nothing stays a plain natural break, never
an ad the design did not ask for.

The fallbacks are the point:

| Situation | The game |
|---|---|
| Portal SDK blocked, slow or failing | the **adapter** degrades inside itself and keeps reporting to an SDK that connects late; the game plays on without ads |
| An adapter's `initialize()` rejects (a contract breach) | `bootPlatform` continues on `generic-web`, reporting `degraded` |
| Platform id with no adapter | still **fails at boot**, visibly, as the registry intends |
| Portal with no SDK at all (GameVui) | runs on the adapter named in `factory.sdk.adapter_substitutes` — explicitly, reported as `substitutedBy` |
| Ad kind unsupported, disabled, blocked, or the SDK did not load | hides the offer; never shows a button that does nothing |
| Ad closed early, no fill, or the SDK throws | grants nothing, says why (`RewardOutcome.reason`), and play continues |
| The portal takes the foreground (Yandex `game_api_pause`) | the game pauses and mutes until it is given back |
| Storage or analytics failing | play continues; a failed save is tracked |

There is deliberately **no boot timeout**. Every adapter bounds its own waits (Poki 5 s,
CrazyGames about 10 s, Yandex up to 10 s per call); replacing one on a timer would abandon a
working SDK mid-start and lose exactly the calls the portals check — Yandex `LoadingAPI.ready`,
CrazyGames `loadingStop`/`gameplayStart`.

Two portal rules are configuration, in `factory.sdk`, because they are data about a portal
rather than code: `break_on_continue: [poki]` (an ad opportunity each time the player heads
back into gameplay) and `interstitial_forbidden_moments: {crazygames: [pause-menu]}`.

The `sdk-report` records, per platform and per feature, the adapter used, the hooks that
carry the feature and where the game calls them (`file:line`), what is unsupported and the
fallback, and both suites' results. A feature is `working` only when it is wired in the game
source, the integration suite passed and the conformance scenarios for it passed — and
`observed_by` says that was against SDK mocks, **never** on the portal. Nothing here claims
a portal accepted anything. Analytics is required of the game only where the adapter's
analytics is self-hosted (the portals that sell ads measure play themselves), and muting
only where the game plays audio. Without a game-design and a scaffold-record in the run
(`wgf sdk` on its own), only the conformance phase runs.

**The integration is committed, once.** Before writing anything the step establishes the
commit it builds on: the checkout's HEAD must be the prototype-report's commit (or a
descendant made only by commits this step recorded in its ledger in the run directory, on a
retry or resume — never by a commit whose trailer merely says so), and the tree may hold no
uncommitted change: not outside the files the integration owns, and not in them either,
unless an earlier attempt of the same visit left them (they are then reset to HEAD and
regenerated, so a hand edit to `src/main.ts` is never folded into the sdk commit). Otherwise it is `BLOCKED` —
integrating on top of an unreviewed commit, or verifying someone's uncommitted edit as if it
were the build, is what this prevents. After a successful integration (files written, its
suite and typecheck not failed) that changed the tree, it makes one local commit keyed by
the idempotency key in a `Wgf-Sdk-Key: <run>:<step>:<visit>` trailer (the develop step's
mechanism, `wgf_develop/repository.py`), then runs the conformance suite at that commit. A
re-executed visit finds its commit instead of making another; an integration already in place
commits nothing; a failed one is left uncommitted and reported. Nothing is pushed. The
sdk-report's `build_ref` records `commit_sha` (what was verified), `base_commit_sha` (the
prototype-report's commit) and `sdk_commits` (what the step made between them). A checkout
whose commit cannot be read is `BLOCKED` — never reported as `unknown`
(`scripts/wgf_sdk/commit.py`; the lineage rule is docs/core-contracts.md §5).

`python -m wgf_sdk.e2e` (from `scripts/`) checks the whole path on a real template revision:
the step, the template's own tests, typecheck and lint, then a production build per platform
and engine (PixiJS and Three.js) driven in Chromium against the SDK mocks the template ships.

### Known limitations, by platform

Checked against each portal's documentation on 2026-09-23. A limitation here is a fact about
what the integration can do today, not a claim that the portal would reject the game.

| Platform | Limitation | Source |
|---|---|---|
| all | The audio module is an empty slot in the template: muting is wired (`PlatformGameplay` `audio`), silence is only real once a game passes its audio in | template `src/audio/` |
| all | No banner, in-app purchase, leaderboard, external-link or `happytime` call exists in the `Platform` interface; placements needing them are reported `unsupported` | template `types.ts` |
| all | The rewarded button's wording, icon and the always-present plain continue are the scene's job (Yandex 4.5.1; Poki: 🎬 icon, not green) | yandex.com/dev/games/doc/en/concepts/requirements, developers.poki.com/guide/requirements-quality |
| Yandex | A blocked `/sdk.js` on the portal cannot satisfy 1.19.2 (Game Ready) by any means; the game plays with no ads and local saves | yandex.com/dev/games/doc/en/concepts/requirements |
| Yandex | The 60 s minimum between interstitials is the adapter's own; Yandex controls frequency itself | yandex.com/dev/games/doc/en/sdk/sdk-adv |
| Yandex | Console switches (cloud saves 1.11, sticky banner) and the archive rules (1.21, 1.22) are manual | same |
| CrazyGames | **No adapter on template main**: it exists only on an unmerged template branch, so a CrazyGames build fails at boot until that branch merges | template `registry.ts` |
| CrazyGames | Basic vs Full Launch is only learned when an ad fails with `adsDisabledBasicLaunch`; the Progress Save toggle is a manual submission step | docs.crazygames.com/sdk/video-ads, /sdk/data |
| Poki | No loading-progress or language call exists in Poki's HTML5 SDK; whether a `commercialBreak` shows an ad is always Poki's decision | developers.poki.com/guide/sdk-html5, /guide/sdk-overview |
| GameVui | No SDK, JavaScript API or publishing API is published; builds run on `generic-web`: no ad revenue, local saves only (fragile two iframes deep), submission by email | template `docs/platforms/gamevui/`; gamevui.vn returned 403 on 2026-09-23 |
| GameVui | The Factory profile `gamevui@1.0.0` lists interstitial and banner ads no API can deliver, and `age_rating_required: false` against the terms; it needs a new profile version | `core/reference/platforms/gamevui.yaml` |

What the step does not do: write gameplay (the develop step places the hook calls), pick an
analytics sink, commit, push or submit.

---

## Publishing

Publication is **not atomic**. Each `(release × platform)` pair carries its own state, and
the release computes a quorum:

- every `required` platform live → release `live`
- some required not live, none permanently rejected → `partially-live`
- a required platform rejected → back to production to remediate

Which platforms are required is **per-release policy**, not a title property: `r1` may ship
Yandex-only and `r2` may add CrazyGames.

### Separation of responsibilities

**AI prepares. Deterministic automation executes.**

- AI roles prepare metadata, localizations, screenshots and the packaged build.
- GitHub Actions performs mechanical packaging and artifact handling.
- Submission itself is a **human checklist plus a status file**.

No portal APIs are integrated, by design. Building real Yandex/CrazyGames/GameVui/Poki
integrations before the contracts are proven would be building them twice — and the machine's
value here is structure and learning, not automation.

**Secrets never live in source.** Portal credentials belong in CI secret storage, referenced
and never committed, printed, or written into an artifact.

---

## Rejections are how the factory learns

When a portal rejects a submission, `platform-publication` **requires** a compliance finding
with a profile update:

| Update kind | Effect |
|---|---|
| `new-assertion` | Validation catches it next time, automatically |
| `common-rejection-entry` | Design reads it before the same mistake is made |
| `requirement-change` | The profile's stated requirement was wrong |

Then bump the profile version.

A rejection that only sets a status field teaches the factory nothing and the next title
walks into the same wall. This loop is the highest-return mechanism in the whole system: it
is what makes the factory get *better* at shipping rather than just repeatedly shipping.

---

## Adding a platform

1. Write `core/reference/platforms/<id>.yaml`, validated by
   `core/artifacts/shared/platform-profile.schema.json`.
2. Implement its adapter in `web-game-template/packages/platform-sdk/`.
3. Use the id in a strategy's `platform_set`.

No change to `core/` logic, no new stage, no schema edit. If adding a platform requires
touching anything else, that is a bug in this architecture.

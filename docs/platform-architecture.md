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

Shipped profiles: `yandex`, `crazygames`, `gamevui`, `poki`, `generic-web`. All except
`generic-web` are marked `status: unverified` — their figures are starting points to be
corrected against each portal's own documentation. **Treat an unverified number as a
hypothesis.**

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
platform.ads.showRewarded()
platform.ads.showInterstitial()
platform.storage.save(state)
platform.leaderboards.submit(score)
```

Adapters in `web-game-template/packages/platform-sdk/` implement it per portal. This is what
makes one build shippable to four portals, and what keeps the game independent of any of
them.

Wire this during **prototype**, not production. The prototype exists partly to prove that
monetization and SDK integration work in context; deferring them is how a title discovers at
release that its ad placement does not fit its loop.

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

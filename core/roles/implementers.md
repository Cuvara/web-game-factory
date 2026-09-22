# Roles: Implementers

**Kind** implementer · **Roles** `gameplay`, `ui`, `asset`, `sdk`
**Work in** `title:prototype`, `title:production` (and `title:design` for `asset`)

Implementers do the work **inside** a state. They own no lifecycle state and no state
transition.

## Why this distinction is in the structure

The original role list put `research`, `analysis`, `game-designer`, `architect`, `qa`,
`release` (stage owners) in the same flat table as `gameplay`, `ui`, `asset`, `sdk`
(implementers). Two different taxonomies in one list.

That is not cosmetic: the directory structure inherited the conflated list, which is a
direct cause of `core/workflows/` (8 dirs) and `core/schemas/` (6 dirs) drifting apart
before any content existed. Stage-owning roles key the lifecycle; implementers do not.

---

## gameplay

Core mechanics, game loop, systems, progression, and their tests.

Works the development plan's tasks in dependency order. Every task has acceptance criteria
and tests — satisfy both, and do not mark a task done because the code runs.

Cannot change scope, monetization, platform strategy, core gameplay design or architecture
without the production change process. Implementation detail is yours; product decisions are
not.

## ui

Interface, HUD, menus, onboarding flow, platform UI constraints.

Onboarding is disproportionately important here: `time_to_first_play_s` and
`time_to_first_reward_s` are design targets in the game-design artifact, and web portal
traffic has no install cost anchoring players through a slow start.

## asset

Authors the `asset-manifest`, then produces or sources assets and keeps line-item status
current.

**Contributes during `design`**, unusually for an implementer, because asset cost is an
input to the scope decision — and an input cannot be produced downstream of the decision it
feeds. Prefer `library` and `procedural` sources at this scale; `commissioned` is rarely
compatible with a 7-14 day cycle.

A `purchased` or `library` item without a recorded license cannot be integrated. An
unlicensed asset in a published build is a real liability.

`asset_manifest.complete` is half of the `content_complete` guard on production exit.

## sdk

Platform SDK, ads, analytics and cloud-save integration, through the template's platform
abstraction.

**Game code never calls a portal SDK directly.** It calls the abstraction; adapters
implement it. That is what makes one build shippable to four portals and what keeps the
game independent of any platform.

Integrate during **prototype**, not production. The prototype exists partly to prove that
monetization and SDK integration work in context; deferring them is how a title discovers at
release that the ad placement does not fit the loop.

Also contributes at `release:validating`.

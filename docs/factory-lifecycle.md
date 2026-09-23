# Factory Lifecycle

Two independent state machines plus two nested ones. The authoritative definitions are the
YAML files in `core/lifecycle/`; this document explains them.

---

## Why two tiers

A game cannot be "in state MARKET_INTELLIGENCE". Market scanning is portfolio-scoped and
continuous, and the thing that carries state is the **opportunity** it produces, not a
title and not the factory.

So: a **portfolio** machine whose entity is an opportunity, and a **title** machine that
begins when an opportunity is promoted.

The connection back from live titles to discovery is a **data edge, not a control edge**.
A shipped game's metrics become claims that change what the next scan believes; nothing
transitions. This is why a live title can keep iterating indefinitely while new titles start
alongside it — a single circular chain cannot express that.

---

## Portfolio tier — entity: opportunity

```
market-scan (job, stateless)
    │ emits claim + opportunity + research-report
    ▼
discovered ──score──▶ scored ──rank──▶ shortlisted ──[G1]──▶ approved ──▶ promoted
                        │                   │                    │
                        │                   ├─defer──▶ parked    └─hold──▶ parked (WIP cap)
                        ├─rank(fail)──▶ rejected
                        └─ttl_expire──▶ stale ──rescore──▶ scored
```

| State | Meaning |
|---|---|
| `discovered` | Candidate exists, deduplicated, unjudged |
| `scored` | Has ≥1 evaluation under a named, versioned scoring model |
| `shortlisted` | Above threshold, evidence coverage met, no veto fired |
| `approved` | A human selected it (G1) |
| `promoted` | A title exists; portfolio work done *(terminal in tier)* |
| `parked` | Good, not now — capacity or timing |
| `stale` | Evidence older than the model's TTL; must not be promoted from here |
| `rejected` | Killed at portfolio level *(terminal)* |

Most opportunities should end in `rejected`. That is the machine working.

`approved → promoted` is guarded by `wip_available`. The WIP cap exists because the human is
the scarce resource, and a factory that queues more titles than its gates can clear
deadlocks.

---

## Title tier — entity: title

```
concept ──▶ strategy ──[G2]──▶ design ──▶ tech-plan ──[G3]──▶ scaffolding ──▶ prototype
   ──▶ prototype-review ──[G4]──▶ production ──▶ releasing ──▶ live
                │                                                │
                ├─iterate──▶ prototype                           ├─review.iterate──▶ production
                └─abandon──▶ abandoned                           ├─review.scale──[G7]──▶ live
                                                                 ├─review.hold──▶ live
                                                                 ├─review.sunset──▶ sunset
                                                                 └─hotfix──▶ releasing

any non-terminal ──pause──▶ paused ──resume──▶ previous | nearest upstream producer
terminals: abandoned, sunset
```

| State | Kind | Owner |
|---|---|---|
| `concept` | automatic | analysis |
| `strategy` | AI-assisted | game-designer |
| `design` | AI-assisted | game-designer |
| `tech-plan` | AI-assisted | architect |
| `scaffolding` | automatic | release |
| `prototype` | AI-assisted | gameplay |
| `prototype-review` | **human** | portfolio-owner |
| `production` | AI-assisted | gameplay |
| `releasing` | automatic | release |
| `live` | AI-assisted | liveops |
| `paused` / `abandoned` / `sunset` | — | — |

### Three design decisions worth knowing

**`strategy` survives as its own state** because it is where **kill criteria are authored**.
Criteria written at review time get written to justify the decision already made. Writing
them in advance, under a gate, while the idea is cheap, is what makes `abandon` real.

**`design` has no gate of its own.** Design and tech-plan approve together at G3. Splitting
them adds a gate to a cycle that already has too many, and approving a design whose plan does
not fit the timebox decides nothing.

**`paused` does not simply return.** If the title's inputs are no longer fresh — an upstream
artifact was superseded while it sat — it resumes at the **nearest upstream producing state**.
Without this a paused title silently ships a game built on a dead market read.

### Stages that are guards, not states

- **CI** — `ci_green(sha)` is checked on several transitions; `verify_suite_green(sha)` on
  exactly one. CI is continuous throughout production, not a step after QA.
- **Content complete** — `content_manifest.complete && asset_manifest.complete` on
  production exit. A state meaning only "two booleans are true" adds a transition and no
  information.
- **Vertical slice** — at 7-14 days the prototype *is* the vertical slice, so the bar at
  `prototype-review` is raised rather than a state being added.
- **Engine selection** — inside `tech-plan`, because `engine.type` is a repository-creation
  parameter and the ordering tech-plan → repo creation is load-bearing.

---

## Release — nested, one per shipment

```
draft ──▶ qa ──▶ rc ──[G5]──▶ approved ──[G6]──▶ validating ──▶ submitting ──▶ live
   │        │                                          │              │
   │        └─fail──▶ title:production                 └─fail──▶ title:production
   │                                                                  └─▶ partially-live
terminals: live, rolled-back, cancelled
```

Instances are `r1`, `r2`, … A title returns here for every shipment including hotfixes.

Which platforms are **required** is per-release policy, not a title property: `r1` may ship
Yandex-only and `r2` may add CrazyGames.

The manifest is **frozen and immutable at `rc`**. Any correction produces a new release.
That is what makes rollback an operation — re-publishing a known-good manifest — rather than
a rebuild under pressure.

---

## Platform publication — nested leaf, one per (release × platform)

```
pending ──▶ packaged ──▶ validated ──▶ submitted ──▶ in-review ──▶ live
                 │                                        └──▶ rejected
                 └──▶ validation-failed                          │
                                                                 ▼
                                             emits a compliance finding
                                             and versions the platform profile
```

Publication is **not atomic**: portals moderate independently, and Yandex can reject what
CrazyGames approved. The release computes a quorum from these records.

`submitted` and `in-review` advance by a human checklist plus a status file. No portal APIs
are integrated — the machine's value here is structure and learning, not automation.

**The `rejected` edge is the most valuable one in the system.** A rejection must produce a
compliance finding that updates the platform profile — a new assertion, a
`common_rejections` entry, or a corrected requirement — and bump its version. A rejection
that only sets a status field teaches the factory nothing, and the next title hits the same
wall.

---

## Gates

| ID | Gate | Irreversible | Auto-approve |
|---|---|---|---|
| G1 | Opportunity selection | no | 72h |
| G2 | Strategy approval | no | 48h |
| G3 | Design + development plan | no | 48h |
| G4 | **Prototype review** | **yes — kill** | **never** |
| G5 | Release approval | no | 24h |
| G6 | **Publish authorization** | **yes — public** | **never** |
| G7 | **Campaign spend** | **yes — money** | **never** |

Definitions, required artifacts, predicates and what each presenter must show:
`core/lifecycle/gates.yaml`.

Gates are **data**, so supervised and semi-autonomous operation differ by configuration
rather than by code. The three irreversible gates cannot be configured to auto-approve —
`decision-record.schema.json` rejects a non-human decision on them.

---

## Every gate produces an artifact

A `decision-record` pins its subject by **content hash**, names the decider and the mode
(`human` or `auto-approved`), and carries a rationale.

This matters most for resumption: an agent picking work up three days later must be able to
tell approved from skipped from never-reached. A gate that produces no artifact is neither
auditable nor resumable.

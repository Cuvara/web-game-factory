# Core Workflow Review

An architecture review of the proposed Factory workflow, the defects found in it, and the
design that replaced it.

**Status** Implemented. See `core/` for the result.

---

## 1. The proposed workflow

```
START → MARKET INTELLIGENCE → OPPORTUNITY ANALYSIS → GAME IDEATION
  → OPPORTUNITY EVALUATION → GAME STRATEGY → GAME DESIGN → SCOPE OPTIMIZATION
  → SESSION / RETENTION DESIGN → MONETIZATION DESIGN → TECHNICAL ARCHITECTURE
  → DEVELOPMENT PLAN → CREATE GAME REPOSITORY FROM TEMPLATE → PROTOTYPE
  → PROTOTYPE REVIEW → PRODUCTION → QA → RELEASE CANDIDATE → CI/CD VERIFY
  → PLATFORM VALIDATION → PUBLISH → ANALYTICS → POST-LAUNCH ANALYSIS
  → ITERATION / NEW OPPORTUNITY → MARKET INTELLIGENCE
```

Twenty-three stages in one linear chain that loops back on itself.

---

## 2. Problems identified

### 2.1 Two lifecycles conflated into one — the structural defect

`MARKET INTELLIGENCE`, `OPPORTUNITY ANALYSIS` and `GAME IDEATION` are **portfolio-scoped and
continuous**. No individual game can be "in state MARKET_INTELLIGENCE" — there is no entity
to hold that state. Market scanning is a recurring job; the state belongs to the
**opportunity** it emits.

The closing `ITERATION → MARKET INTELLIGENCE` edge is a second symptom: it draws a **data
dependency as a control edge**. Live analytics feeds discovery as *evidence*; it does not
transition anything. The system is two independent loops joined by data, and drawing it as
one circle makes a live title's ongoing iteration look mutually exclusive with starting new
titles, which it is not.

### 2.2 Scope, session and monetization are not stages

Scope depends on monetization, which depends on session, which depends on scope. There is no
valid order, so sequencing them invents one — usually producing a monetization plan bolted
onto a session that cannot carry it.

Splitting them into four documents is worse than splitting them into four stages: four files
drift and no single artifact is ever wrong.

### 2.3 `CI/CD VERIFY` is not a stage

CI is **guard vocabulary**. `ci_green(sha)` is a predicate checked on several transitions
throughout production; the heavier `verify_suite_green(sha)` is checked on exactly one. The
proposal placed CI once, after QA, which is neither where it runs nor what it does.

### 2.4 `PUBLISH` cannot be atomic

With a primary and secondary platforms, portals moderate independently. Yandex can reject
what CrazyGames approved, days apart. A single `PUBLISHED` state cannot express that, and
"which platforms must succeed" is per-release policy, not a title property — r1 may ship
Yandex-only and r2 may add CrazyGames.

### 2.5 `ANALYTICS` and `POST-LAUNCH ANALYSIS` are one thing, and it is not a stage

A live title sits live indefinitely. Merging the two stages keeps the original error of
treating an ongoing condition as a step.

### 2.6 Platform compliance discovered far too late

Yandex requires Russian; GameVui requires Vietnamese. In the proposal these surface at
`PLATFORM VALIDATION`, which is **after the build**. This is the most expensive defect in the
list: it converts a line item in the scope into a re-plan.

### 2.7 Asset production is absent

Asset cost is named as an optimization dimension, but no stage produces an asset plan. An
input cannot be produced downstream of the decision it feeds.

### 2.8 Evidence vs hypothesis stated as prose

"Do not allow unsupported assumptions to become facts" is unenforceable as guidance. It needs
a mechanism.

### 2.9 Vertical slice and content complete silently dropped

Both were in the older 18-stage lifecycle and vanished. Dropping them is right, but for two
*different* reasons, and neither was stated.

### 2.10 Further defects found during review

- **Nowhere to store instance state.** `core/` must stay methodology; a game repo does not
  exist when an opportunity does. The backlog had no home at all.
- **No staleness detection.** Nothing could detect that a design was derived from a market
  read that has since been superseded — fatal in a system premised on re-deciding.
- **No WIP limit.** Seven gates on a 7-14 day cycle is a gate every ~1.4 days. At five
  concurrent titles the human *is* the factory, and the design deadlocks in week two.
- **Paid campaigns in the requirements and in `campaign.yml`, but in no stage.** Money spent
  by a system nobody designed to spend money.
- **Every arrow points forward.** No failure edges, no rollback path.
- **Approvals produce no artifact**, so gates are neither auditable nor resumable.
- **The eight commands** (`research`/`analyze`/`design`/`prototype`/`build`/`verify`/
  `release`/`publish`) cover no discovery, evaluation, approval, analytics or campaign.
- **The `8/6/6/8` directory misalignment** already present in `core/` is a symptom of keying
  four parallel trees by stage.
- **Engine selection vanished** between the old list and the proposal.
- **The role list conflates stage owners with implementers**, is missing an owner for the
  live stage entirely, and assigns compliance to nobody.

---

## 3. Recommended changes

| # | Change | Replaces |
|---|---|---|
| 1 | Split into a **portfolio machine** (entity: opportunity) and a **title machine** | One 23-stage chain |
| 2 | Market scan becomes a **stateless job**; the back-edge becomes a data edge | `MARKET INTELLIGENCE` as a stage |
| 3 | One `design` state emitting one `game-design` artifact, with a **computable consistency check** as its exit guard | Four sequential design stages |
| 4 | CI becomes **guard vocabulary** (`ci_green`, `verify_suite_green`) | `CI/CD VERIFY` stage |
| 5 | Nested **release** and **platform-publication** machines with a per-release required/optional quorum | Atomic `PUBLISH` |
| 6 | `live` as an ongoing state with a **scheduled review job** emitting a four-way decision | `ANALYTICS` + `POST-LAUNCH ANALYSIS` |
| 7 | `platform-profile` as a versioned artifact read at three points with **rising strictness** | Compliance discovered at validation |
| 8 | `asset-manifest` as an **artifact produced at design**, not a stage | Nothing |
| 9 | **Claim envelope** with tiers, append-only semantics, and computed `evidence_coverage` | Prose guidance |
| 10 | Prototype review bar **raised**; content-complete becomes a **guard** | Vertical slice / content complete |
| 11 | A `workspace/` tree for instance data | Nowhere |
| 12 | `provenance.inputs[]` pinned by content hash on every artifact | Nothing |
| 13 | `max_concurrent_titles` + `auto_approve_after` on reversible gates only | Nothing |
| 14 | Campaign as a gated `live` sub-activity | Nothing |
| 15 | Explicit failure edges and a `rolled-back` state | All arrows forward |
| 16 | `decision-record` as a first-class artifact at every gate | Nothing |
| 17 | Commands mapped to **transitions** | Commands mapped to stages |
| 18 | Contract **is** the schema (`x-wgf` block); trees keyed by artifact | 8/6/6/8 parallel trees |
| 19 | Engine selection inside `tech-plan` (it is a repo-creation parameter) | Lost |
| 20 | Roles split into owner / implementer / human; `liveops` added; compliance assigned to `release` | One flat list of ten |

### On the three "dropped" stages

They are removed by three different mechanisms, and the distinction matters:

- **`VERTICAL SLICE`** — at 7-14 days the prototype *is* the vertical slice. Not demoted:
  the bar at `prototype-review` is **raised** to "playable and fun-testable against the kill
  criteria".
- **`CONTENT COMPLETE`** — becomes a **guard**
  (`content_manifest.complete && asset_manifest.complete`) on production exit. A state that
  only ever means "two booleans are true" adds a transition and no information.
- **`ENGINE SELECTION`** — folded into `tech-plan`, because `engine.type` is a
  repository-creation parameter and the ordering tech-plan → repo creation is load-bearing.

---

## 4. Final workflow

```
PORTFOLIO — entity: opportunity
  market-scan (job, stateless)
      │ emits claims + opportunities
      ▼
  discovered ──▶ scored ──▶ shortlisted ──[G1]──▶ approved ──▶ promoted
                    │            │                    │
                    └─▶ stale    └─▶ parked           └─▶ parked (WIP cap)
                    └─▶ rejected

TITLE — entity: title                            (spawned by promoted)
  concept ──▶ strategy ──[G2]──▶ design ──▶ tech-plan ──[G3]──▶ scaffolding
      ──▶ prototype ──▶ prototype-review ──[G4: pass | iterate | ABANDON]
      ──▶ production ──▶ releasing ──▶ live
                                        ├─ review.iterate ──▶ production
                                        ├─ review.scale ──[G7]──▶ live
                                        ├─ review.hold  ──▶ live
                                        └─ review.sunset ──▶ sunset
  any non-terminal ──▶ paused ──▶ (previous | nearest upstream producer)
  terminals: abandoned, sunset

RELEASE — nested, r1, r2, …
  draft ──▶ qa ──▶ rc ──[G5]──▶ approved ──[G6]──▶ validating ──▶ submitting
      ──▶ live | partially-live
  terminals: live, rolled-back, cancelled

PLATFORM PUBLICATION — nested leaf, one per (release × platform)
  pending ──▶ packaged ──▶ validated ──▶ submitted ──▶ in-review ──▶ live
                    └─▶ validation-failed        └─▶ rejected ──▶ versions the platform profile
```

Full transition tables, guards and policies: `core/lifecycle/*.machine.yaml`.

---

## 5. Human approval gates

| ID | Gate | Transition | Irreversible | Auto-approve |
|---|---|---|---|---|
| G1 | Opportunity selection | `shortlisted → approved` | no | 72h |
| G2 | Strategy approval | `strategy → design` | no | 48h |
| G3 | Design + dev plan | `tech-plan → scaffolding` | no | 48h |
| G4 | Prototype review | `prototype-review → …` | **yes (kill)** | **never** |
| G5 | Release approval | `rc → approved` | no | 24h |
| G6 | Publish authorization | `approved → validating` | **yes (public)** | **never** |
| G7 | Campaign spend | `live → live` | **yes (money)** | **never** |

Three things are irreversible: **killing a concept, making something public, and spending
money.** An AI does none of them unattended, and `decision-record.schema.json` enforces
`mode: human` on those three.

The four reversible gates support auto-approval deliberately. Seven gates on a 7-14 day
cycle is a lot of human attention, and a factory whose gates cannot be cleared will have its
gates removed by whoever is under pressure — including the ones that matter.

---

## 6. Roles

**Owners** (accountable for a state and its artifact): `research`, `analysis`,
`game-designer`, `architect`, `qa`, `release`, `liveops`.

**Implementers** (work inside a state, own none): `gameplay`, `ui`, `asset`, `sdk`.

**Human**: `portfolio-owner`.

Three corrections to the original list of ten:

1. **Owners and implementers were conflated.** Not cosmetic — the directory structure
   inherited the conflated list, which is a direct cause of the 8/6/6/8 drift.
2. **`liveops` was missing.** `sdk` integrates the analytics SDK; nobody interpreted the
   data, leaving the "learns from what it ships" premise without an owner.
3. **Compliance and localization were assigned to nobody**, so they were discovered at
   submission time. Now explicitly `release`, with a `localization` skill.

Also: the human is now a **named role**. A gate with no named approver is a gate that gets
skipped.

---

## 7. Artifact contracts

Thirteen artifacts plus three reference types. **The contract is the schema** — producer,
consumers, format, repo path and gate usage live in an `x-wgf` block at each schema root, so
contract and schema cannot disagree.

| Artifact | Producer | Key consumers |
|---|---|---|
| `claim` | market-scan, live | scoring, strategy, design |
| `opportunity` | market-scan | scoring, G1, strategy |
| `evaluation` | scored | G1, strategy |
| `title-strategy` | strategy | design, tech-plan, G4, live |
| `game-design` | design | tech-plan, prototype, production, QA |
| `asset-manifest` | design | tech-plan, production, release |
| `tech-plan` | tech-plan | scaffolding, prototype, production |
| `prototype-report` | prototype | **G4** |
| `qa-report` | release QA | rc, G5 |
| `release-manifest` | release draft | G5, G6, validating, rollback |
| `platform-publication` | validating | release quorum, profile updates |
| `performance-review` | live | G7, production, market-scan |
| `decision-record` | every gate | audit, resume |

**Shared primitives:** `provenance`, `claim`, `criteria-expression`.
**Reference:** `platform-profile`, `scoring-model`, `dimension-vocabulary`.

### Cut deliberately

`market-report` and `competitor-report` are *renderings of claims for humans* — nothing
downstream parses them, so they are templates, not contracts. `task_breakdown.json` folds
into `tech-plan.dev_plan`; `concepts.json` is superseded by `opportunity` + `evaluation`;
`metadata.json` is a field of `release-manifest`; separate scope/session/monetization
documents are sections of `game-design`.

---

## 8. Mechanisms, not intentions

The review's recurring finding was that good intentions stated as prose do not survive
contact with a system that runs unattended. Each is replaced with something checkable:

| Intention | Mechanism |
|---|---|
| "Assumptions must not become facts" | `tier` enum; an `observed` claim without a source **fails validation**; hypotheses capped at 0.6 confidence |
| "Evidence should be traceable" | `evidence_refs[]` per scored dimension; empty forces `hypothesis`; `evidence_coverage` is a number a gate can require |
| "Beliefs shouldn't be rewritten" | Claims and evaluations are **append-only**, with `superseded_by` |
| "Scoring shouldn't be arbitrary" | Versioned, content-hashed scoring model; evaluations record model id + version + hash, so the backlog can be re-scored and rankings diffed |
| "Scope should be optimized" | `out_of_scope` **required and non-empty**; every exclusion carries a `why_excluded` |
| "Design facets should be consistent" | ~10 declarative rules evaluated as the **exit guard** on design |
| "Platform differences should be handled" | Versioned profiles read at three points with rising strictness; assertions run against the built package |
| "The factory should learn" | A portal rejection **must** emit a compliance finding that versions the platform profile |
| "Correlation is not causation" | Metrics, findings, hypotheses and experiments are **four separate fields** |
| "The AI shouldn't decide alone" | `decision-record` schema rejects non-human decisions on G4, G6, G7 |
| "Contracts shouldn't drift" | The contract **is** the schema; the ID **is** the filename |

---

## 9. Implementation

Delivered in `core/` and `workspace/`:

- `core/lifecycle/` — 4 machines, `gates.yaml`, 19 stage procedures
- `core/artifacts/` — 12 artifact schemas + 6 shared primitives, JSON Schema 2020-12
- `core/reference/` — dimension vocabulary, 5 platform profiles, default scoring model,
  design consistency rules
- `core/roles/` — registry + 9 charters
- `core/templates/` — 5 document templates
- `core/bindings/adapter-binding.yaml` — what an adapter must cover
- `workspace/` — instance data layout and a worked example
- Both adapters rebuilt as thin pointers, with conformance tables

### Deliberately not built

Real portal API integrations, publishing credentials, ad spend automation, autonomous
campaigns, databases, or distributed infrastructure. The point of this pass was the
contracts; integrations built before the contracts are proven are integrations built twice.

There is also **no validation toolchain** — schemas ship as data, validated on demand via
`npx ajv-cli`. The honest cost is that contracts are advisory until someone runs it. See
`core/README.md` for the conditions under which that decision should be revisited.

# Web Game Factory

A system for discovering, building, publishing and learning from web games.

Not an AI code generator. The Factory is designed to be told *"I want to make a new web
game"* and to work out what that game should be — researching what genres and mechanics are
performing, on which portals, for which audiences, at what scope — then build it, ship it,
measure it, and feed what it learned into the next decision.

It is equally designed to conclude that a game should **not** be built. That is the
capability that makes the rest of it worth running.

```
Market → Opportunity → Game → Prototype → Launch → Analytics → Learning → Next opportunity
```

Recent changes, and what each would take to adopt: [CHANGELOG.md](CHANGELOG.md).

---

## Layout

```
web-game-factory/
  core/                    — methodology: states, contracts, roles, reference data
    lifecycle/             — 4 state machines, gates, per-stage procedures
    artifacts/             — JSON Schemas; each carries its contract in x-wgf
    reference/             — dimensions, platform profiles, scoring models, rules
    roles/                 — who is accountable for what
    templates/             — document scaffolds
    bindings/              — what an AI adapter must cover
    workflows/             — executable workflow definitions, run by `wgf`
  workspace/               — instance data: claims, opportunities, titles, decisions
  claude-web-game-plugin/  — Claude Code adapter
  codex-web-game-plugin/   — Codex adapter
  docs/                    — architecture documentation
  scripts/                 — integrity check, state runner, and the `wgf` workflow engine
  bin/wgf                  — the workflow CLI
```

Games live in their own repositories, created from **`web-game-template`**. The Factory never
contains game source code and never builds a game repository from scratch.

---

## Two independent loops

A game cannot be "in state MARKET_INTELLIGENCE" — market scanning is portfolio-scoped and
continuous, and the thing that carries state is the *opportunity* it produces.

```
PORTFOLIO — entity: opportunity
  market-scan (a job, not a state)
      ↓
  discovered → scored → shortlisted →[G1]→ approved → promoted
                            ↘ parked / stale / rejected

TITLE — entity: title
  concept → strategy →[G2]→ design → tech-plan →[G3]→ scaffolding → prototype
      → prototype-review [G4: pass | iterate | ABANDON]
      → production → releasing → live
                                   ↘ paused / abandoned / sunset
```

Nested inside a title: a **release** machine per shipment, and a **platform publication**
machine per (release × platform) — because Yandex can reject what CrazyGames approved.

Live analytics feeds discovery as **evidence, not control**. That is why a live title keeps
iterating while new titles start alongside it.

See [docs/factory-lifecycle.md](docs/factory-lifecycle.md).

---

## Seven gates, three of them absolute

| | Gate | Irreversible | Auto-approve |
|---|---|---|---|
| G1 | Opportunity selection | no | 72h |
| G2 | Strategy approval | no | 48h |
| G3 | Design + development plan | no | 48h |
| G4 | **Prototype review** | **yes — kill** | **never** |
| G5 | Release approval | no | 24h |
| G6 | **Publish authorization** | **yes — public** | **never** |
| G7 | **Campaign spend** | **yes — money** | **never** |

Three things are irreversible: killing a concept, making something public, and spending
money. An AI does none of them unattended, and the schema enforces it.

The other four auto-approve deliberately. Seven gates against a 7-14 day cycle is a lot of
human attention, and a factory whose gates cannot be cleared will have its gates removed by
whoever is under pressure — including the ones that matter.

---

## Design principles

**AI-provider independent.** `core/` names no AI system. Claude and Codex are adapters whose
files are pointers into core — an adapter file that restates a schema is a bug.

**Platform independent.** Portals are data (`core/reference/platforms/*.yaml`). Adding one is
a single new file.

**Evidence is mechanized, not requested.** Claims carry a tier; an `observed` claim without a
source *fails validation*; hypotheses cap at 0.6 confidence; claims are append-only. Every
scored dimension carries evidence refs, and `evidence_coverage` is a number a gate can
require. "Don't let assumptions become facts" is unenforceable as advice.

**The contract is the schema.** Producer, consumers, format and repo path live in an `x-wgf`
block inside each schema, so they cannot disagree.

**Optimizes many dimensions at once.** Revenue, platform fit, dev speed, scope, technical
risk, asset cost, monetization fit, session quality, retention, replayability, competition,
performance, time to market, iterability — all in `core/reference/dimensions.yaml`. Scoring
weights are versioned, configurable policy.

---

## Engines and platforms

**PixiJS** for 2D, **Three.js** for 3D, selected in the tech plan with a written rationale.
Nothing else.

**Yandex Games**, **CrazyGames**, **GameVui**, **Poki**, **Generic Web** — and any portal
added as a profile.

---

## Start here

| | |
|---|---|
| How it works | [core/README.md](core/README.md) |
| Why it works this way | [docs/core-workflow-review.md](docs/core-workflow-review.md) |
| The lifecycle | [docs/factory-lifecycle.md](docs/factory-lifecycle.md) |
| Contracts | [docs/artifact-contracts.md](docs/artifact-contracts.md) |
| Roles and agents | [docs/agent-architecture.md](docs/agent-architecture.md) |
| Platforms | [docs/platform-architecture.md](docs/platform-architecture.md) |
| Running workflows (`wgf`) | [docs/workflow-engine.md](docs/workflow-engine.md) |
| Working on the Factory | [docs/development.md](docs/development.md) |
| A worked example | [workspace/](workspace/) — `opp-001` / `neon-drift`, claim to kill decision |

---

## Status

Core methodology, artifact contracts, lifecycle machines, reference data and both AI adapters
are implemented. Schemas are JSON Schema 2020-12, validated on demand with `npx ajv-cli`;
there is deliberately no toolchain.

The workflow engine is executable: `bin/wgf new-game --mock` runs research through release
preparation end to end, with retry, resume, failure routing and human checkpoints. Strategy is
the first real module (`scripts/wgf_strategy/`); every other step is still a placeholder, and
the discovery, design, asset, development, SDK and verification modules register against it
later.

Real portal API integrations, publishing credentials and campaign automation are deliberately
**not** built. `web-game-template` remains a scaffold.

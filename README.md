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

## Install and upgrade

**Requirements.** Python 3.10 or newer (the test suite passes on 3.10 through 3.13), standard library only - there is deliberately no
toolchain, no package and no lockfile. `git`. For game repositories: `node` and `pnpm`, and
Playwright's Chromium for browser verification and the golden runs. `gh`, authenticated,
for `init` to create repositories on GitHub ([docs/init-module.md](docs/init-module.md)).
Optional: `npx`, for the ajv schema checks; an agent host CLI, for a `command` developer or
reviewer.

**Install.** Clone this repository and run `bin/wgf` from its root (or put `bin/` on PATH).
The pinned template commit (`workspace/config/template.lock.json`) is cloned on first use and
cached under `~/.cache/wgf/templates/<sha>` - from a sibling `../web-game-template` when it
holds the commit, otherwise from GitHub with the machine's git credentials. The Claude Code
plugin installs from the marketplace at this repository's root
([claude-web-game-plugin/README.md](claude-web-game-plugin/README.md)); for Codex, see
[codex-web-game-plugin/AGENTS.md](codex-web-game-plugin/AGENTS.md).

**First run.**

```bash
bin/wgf new-game --mock          # placeholder steps; stops WAITING at G4 (exit 3)
bin/wgf decide <run-id> pass     # G4 is a person's decision
bin/wgf test-core                # the Core Acceptance Suite
```

Real runs need `workspace/config/factory.yaml` configured: where game checkouts live
(`checkouts`), a developer and a reviewer (the shipped reviewer is `none`, and release
refuses a build no review approved), and `factory.agents.env_passthrough` for the agent
host's credential.

**Upgrading from 1.1.0.** 2.0.0 changes defaults a 1.1.0 installation relies on - the agent
environment is an allowlist, the development commit is scoped, unreviewed releases are
refused, `wgf status` exits as the run. Each has a way back: see **Breaking** and
**Upgrading from 1.1.0** in [CHANGELOG.md](CHANGELOG.md).

---

## Status

The methodology, artifact contracts, lifecycle machines, reference data and both AI adapters
are implemented; schemas are JSON Schema 2020-12. The workflow engine runs `new-game` from
research to a drafted release with a real module behind every step, and stops for a person
at G2, G3 and G4 (G4 is never automated). A release is drafted, not published: portal API
integrations, publishing credentials and campaign automation are deliberately **not** built,
and G5-G7 are decided outside a run (G6 and G7 only ever by a person).

The pipeline is proven end to end by the 2D and 3D golden runs, which use a replayed
developer and a scripted reviewer ([docs/golden-runs.md](docs/golden-runs.md)). A live agent
host as developer and reviewer is configurable and was verified for 1.1.0
([docs/v1-usable.md](docs/v1-usable.md)); the opt-in design agent and developer self-playtest
are verified offline only ([docs/claude-capabilities.md](docs/claude-capabilities.md)).

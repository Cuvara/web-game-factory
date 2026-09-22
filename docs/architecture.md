# Web Game Factory — Architecture

## Overview

The Factory is a **game opportunity discovery, production, release and learning system** —
not an AI code generator. It is built to be told "I want to make a new web game" and to
work out what that game should be, build it, ship it to web game portals, measure it, and
feed what it learned back into the next decision.

It must also be able to conclude that a game should **not** be built. That capability is
what makes the rest of it worth running.

## The two repositories

```
WebGameFactory/
  web-game-factory/     — methodology, instance data, AI adapters
  web-game-template/    — the reusable technical template every game is created from
```

Game repositories are created **from** the template. The Factory never contains game source
code, and never builds a game repository from scratch.

```
web-game-factory  →  tech-plan.repo_params  →  gh CLI  →  web-game-template  →  new game repo
```

## Three kinds of thing, three homes

| | Contains | Constraint |
|---|---|---|
| `core/` | Methodology: states, contracts, roles, reference data | AI-provider independent, platform independent, game independent |
| `workspace/` | Instance data: claims, opportunities, titles, decisions | Never referenced from `core/` |
| game repos | Game source, builds, release artifacts | Created from the template |

`core/` cannot hold the backlog — business data in the methodology would break the
independence rule. A game repository cannot hold it either, because opportunities exist long
before any repository does, and most are rejected without ever getting one. Hence the third
location.

## AI provider independence

`core/` defines workflows, schemas, artifact contracts, lifecycle and templates without
referencing any AI system. Claude and Codex are **adapters**.

```
                    Web Game Factory Core
                             │
        ┌────────────────────┼────────────────────┐
        │                    │                    │
  Claude adapter       Codex adapter      Future adapter
```

An adapter file is a **pointer**: frontmatter, a list of core paths to read, and a short
block of host-specific execution notes. An adapter file that restates a schema or a
procedure is a bug — that restatement is how two adapters drift apart and how both drift
from core.

`core/bindings/adapter-binding.yaml` declares what an adapter must cover, provider-
independently, so completeness is checkable rather than assumed.

The one place a provider is ever named is `evaluation.scored_by.ai_provider` — instance
data in `workspace/`, never methodology.

## Two-tier lifecycle

The Factory runs two independent loops. Conflating them is the defect this architecture
exists to correct.

**Portfolio tier** — the entity with state is an *opportunity*. Market scanning is a
stateless recurring job; no title can be "in" it.

**Title tier** — begins when an opportunity is promoted. Contains nested machines for
releases and per-platform publications.

Live analytics feeds discovery as **evidence, not control**: a shipped game's metrics become
claims that change what the next scan believes. Nothing transitions as a result, which is
why a live title can keep iterating while new titles start alongside it.

See [core-workflow-review.md](core-workflow-review.md) and
[factory-lifecycle.md](factory-lifecycle.md).

## `core/` layout

```
core/
  README.md         ID rules, how to read the machines, how to validate
  lifecycle/        4 state machines, gates.yaml, per-stage procedures
  artifacts/        JSON Schemas; each carries its own contract in x-wgf
    shared/         provenance, claim, criteria-expression + reference schemas
  reference/        dimensions, platform profiles, scoring models, consistency rules
  roles/            registry + charters
  templates/        document scaffolds for artifacts whose canonical form is prose
  bindings/         what an AI adapter must cover
```

### Why not four parallel per-stage trees

The previous structure had `workflows/`, `schemas/`, `artifact-contracts/` and `templates/`
as parallel trees keyed by stage. They had **already drifted** — 8, 6, 6 and 8 directories
with a `design` vs `game-design` naming collision — before any content existed.

Splitting one concept across four trees that must be kept in lockstep by discipline alone
guarantees drift. Two changes remove the whole class:

1. **The contract is the schema.** Producer, consumers, format and repo path live in an
   `x-wgf` block inside the schema file. There is no second file to disagree with.
2. **Artifacts key by artifact; only procedures key by stage.** Stages are the most volatile
   axis, and artifacts do not map 1:1 to them — a design is produced once and consumed five
   times.

Plus one invariant, stated in `core/README.md`: **a directory containing only a `README.md`
must not exist.**

## Platform independence

Platforms are **data**, not code. `core/reference/platforms/<id>.yaml` describes a portal's
capabilities, requirements, ad model, review process and machine-checkable assertions.

Adding a platform is one new file and zero changes anywhere else.

Profiles are **versioned** and read at three points with rising strictness — advisory when
scoring, binding on the design, binding on the built package. A release pins the profile
version it was built against, so a build stays reproducible against the compliance rules
that were in force.

See [platform-architecture.md](platform-architecture.md).

## Validation

JSON Schema 2020-12, shipped as data. No `package.json`, no toolchain, no CI in this
repository — core must stay consumable by a provider that cannot execute anything.

```bash
npx --yes -p ajv-cli@5 -p ajv-formats@2 ajv validate \
  -s core/artifacts/game-design.schema.json \
  -r "core/artifacts/shared/*.schema.json" \
  -c ajv-formats --spec=draft2020 --strict=false \
  -d workspace/titles/neon-drift/game-design.json
```

Contracts are advisory until someone runs that. `core/README.md` records the conditions
under which to revisit the decision.

## Status

Core methodology, contracts and adapters are implemented. Real portal integrations,
publishing credentials and campaign automation are deliberately not.

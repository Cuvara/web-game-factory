# Web Game Factory — Core

Provider-independent methodology. Nothing here names a specific AI system; nothing here
contains game source code; nothing here contains instance data.

Core answers three questions and nothing else:

1. **What states exist and how do they transition?** → `lifecycle/`
2. **What shape is each artifact, and who produces and consumes it?** → `artifacts/`
3. **Who is accountable for each state?** → `roles/`

Everything else (`reference/`, `templates/`, `bindings/`) is data those three depend on.
`workflows/` is the one addition: the order in which units of work *execute*, as data an
engine can run (see `../docs/workflow-engine.md`). It serves the lifecycles and never
replaces them — a workflow step names the stage it serves; it does not move an entity.

---

## How to read this

Start at `lifecycle/title.machine.yaml`. Every stage entry names its role, its input and
output artifact ids, its procedure file, and its transitions with guards. From any stage
entry you are one hop from everything else:

| You want | Go to |
|---|---|
| What happens at this stage | `lifecycle/stages/<stage-id>.md` |
| The shape of an artifact | `artifacts/<artifact-id>.schema.json` |
| Who produces/consumes it | the `x-wgf` block at the top of that same schema |
| Who owns this stage | `roles/roles.yaml`, then `roles/<role-id>.md` |
| What a gate requires | `lifecycle/gates.yaml` |
| What a platform demands | `reference/platforms/<platform-id>.yaml` |
| What an asset may be, and which licenses ship | `reference/asset-policy.yaml` |

Two files — this one and `lifecycle/title.machine.yaml` — are enough to hold the whole
system in your head.

---

## The two tiers

The factory runs **two independent loops**, and conflating them is the mistake this
structure exists to prevent.

```
PORTFOLIO (portfolio.machine.yaml)        the entity with state is an OPPORTUNITY
  market-scan (a job, not a state)
      ↓ emits claims + opportunities
  discovered → scored → shortlisted → [G1] → approved → promoted
                                              ↘ parked / stale / rejected

TITLE (title.machine.yaml)                the entity with state is a TITLE
  concept → strategy →[G2] design → tech-plan →[G3] scaffolding → prototype
      → prototype-review [G4: pass | iterate | ABANDON]
      → production → releasing → live
                                   ↘ paused / abandoned / sunset

  RELEASE (release.machine.yaml)          nested per shipment, r1, r2, ...
    draft → qa → rc →[G5] approved →[G6] validating → submitting → live
                                              ↘ partially-live / rolled-back / cancelled

  PLATFORM PUBLICATION                    nested leaf, one per (release × platform)
    pending → packaged → validated → submitted → in-review → live
                       ↘ validation-failed        ↘ rejected → updates the platform profile
```

A title cannot be "in state MARKET_INTELLIGENCE" — market scanning is portfolio-scoped and
continuous, and a live title keeps iterating while new titles start alongside it. Live
analytics feeds discovery as **evidence**, not as a transition.

---

## Naming and reference rules

These are the invariants. Breaking one is how the previous structure drifted into four
mutually inconsistent trees before a single line of content existed.

- **The ID is the filename stem.** `artifacts/game-design.schema.json` has id `game-design`.
- **Cross-references are by ID**, never by path, except `must_read`/`procedure` fields.
- **IDs are kebab-case, singular, and carry no stage prefix.** `gdd`, not `design-gdd` —
  a prefix encodes an ownership that changes.
- **Stage IDs are local to their machine.** Qualify across machines: `title:design`,
  `portfolio:scored`, `release:rc`.
- **Platform IDs must match** the strings used in `web-game-template/game.config.yaml`.
- **A directory that contains only a `README.md` must not exist.** Create a directory when
  its first real file exists.

### Artifact instance IDs

```
wgf:<artifact-type>:<scope-slug>:<yyyymmdd>-<nn>

wgf:game-design:neon-drift:20260921-01
```

---

## The contract IS the schema

There is no separate `artifact-contracts/` tree. Producer, consumers, format, repository
path, and gate usage live in an `x-wgf` block at the root of each schema:

```json
"x-wgf": {
  "id": "game-design",
  "producer": "title:design",
  "consumers": ["title:tech-plan", "title:prototype", "title:production", "release:qa"],
  "format": "yaml",
  "repo_path": "docs/design/game-design.yaml",
  "required_for_gates": ["G3"]
}
```

One file, so contract and schema cannot disagree. This removes an entire class of drift
rather than asking people to be careful.

---

## Evidence is a schema primitive, not a writing style

"Do not let assumptions become facts" is unenforceable as prose, so it is mechanized:

- Every claim has a **tier** — `observed`, `derived`, or `hypothesis`. An `observed` claim
  without at least one cited source fails validation. A `hypothesis` may not exceed 0.6
  confidence.
- Claims are **append-only**. Changing one means writing a new claim and setting
  `superseded_by`. This is what stops a hypothesis being quietly edited into a fact.
- Every scored dimension carries `evidence_refs[]`. Empty means its tier is forced to
  `hypothesis`, and the evaluation's `evidence_coverage` drops. A gate can then require
  `evidence_coverage >= 0.6` — so "well-evidenced" is a number, not an opinion.
- Every artifact carries `provenance.inputs[]` pinned by content hash, so a decision built
  on a market read that has since been superseded is detectable rather than invisible.

---

## Validation

Schemas are **JSON Schema 2020-12** and ship as data. There is deliberately no toolchain,
no `package.json`, and no CI in this repository — core must stay consumable by a provider
that cannot execute anything.

Validate on demand:

```bash
# compile a schema
npx --yes -p ajv-cli@5 -p ajv-formats@2 ajv compile \
  -s core/artifacts/game-design.schema.json \
  -r "core/artifacts/shared/*.json" \
  -c ajv-formats --spec=draft2020 --strict=false

# validate an instance
npx --yes -p ajv-cli@5 -p ajv-formats@2 ajv validate \
  -s core/artifacts/game-design.schema.json \
  -r "core/artifacts/shared/*.json" \
  -c ajv-formats --spec=draft2020 --strict=false \
  -d workspace/titles/neon-drift/game-design.json
```

`--strict=false` is required because `x-wgf` is a custom annotation keyword.

**The honest tradeoff:** contracts are advisory until someone runs that command. Nothing
stops an agent emitting a `game-design` with no `session` section; it will be caught
downstream rather than at the point of error.

**Revisit this decision when** any of these becomes true — do not let it drift by default:

- the first title produces real artifacts end to end
- two or more titles run concurrently
- the schema count exceeds ~25

At that point the validator belongs in the title-side toolchain (`web-game-template`
already has pnpm) or a separate tools package — not in `core/`.

---

## Layout

```
core/
  lifecycle/        state machines, gates, per-stage procedures
  artifacts/        JSON Schemas; each carries its own contract in x-wgf
    shared/         primitives reused everywhere (provenance, claim, criteria-expression)
  reference/        maintained data: dimensions, platform profiles, scoring models, rules,
                    asset policy
  roles/            who is accountable for what
  templates/        document scaffolds for artifacts whose canonical form is prose
  craft/            playbooks for what a *good* game looks like inside the artifacts' fields
                    (feel, loop, onboarding, audio, art, accessibility, performance, play)
  bindings/         what an AI adapter must cover, provider-independently
  workflows/        executable workflow definitions (steps, routing, retry) - run by `wgf`
```

Instance data — the opportunity backlog, claims, evaluations, decisions, title state —
lives in `../workspace/`, never here.

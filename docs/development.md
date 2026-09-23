# Development Guide

How to work on the Factory itself.

## Orientation

Read two files, in order:

1. `core/README.md` — ID rules, how to read the machines, how to validate
2. `core/lifecycle/title.machine.yaml` — the per-title lifecycle

That is enough to hold the whole system. Then
[core-workflow-review.md](core-workflow-review.md) explains *why* it is shaped this way,
which matters more than usual here — several decisions look arbitrary until you know what
they replaced.

## Invariants

Breaking one of these is how the previous structure drifted into four mutually inconsistent
trees before anything was implemented.

- **The ID is the filename stem.** `artifacts/game-design.schema.json` has id `game-design`.
- **Cross-references are by ID**, except `procedure` and `must_read` paths.
- **IDs are kebab-case, singular, no stage prefix.** `gdd`, not `design-gdd` — a prefix
  encodes an ownership that changes.
- **Stage IDs are local to their machine.** Qualify across machines: `title:design`,
  `portfolio:scored`, `release:rc`.
- **Platform IDs match** `web-game-template/game.config.yaml`.
- **A directory containing only a `README.md` must not exist.**
- **`core/` never names an AI provider, a specific game, or a specific opportunity.**

## Where things go

| Adding | Goes in |
|---|---|
| A workflow concept, contract or lifecycle change | `core/` first, always. Adapters follow. |
| A new artifact | `core/artifacts/<id>.schema.json`, with its `x-wgf` contract block |
| A new stage | `core/lifecycle/<machine>.machine.yaml` + `core/lifecycle/stages/<id>.md` |
| A new platform | `core/reference/platforms/<id>.yaml` — one file, nothing else |
| A scoring change | A **new** versioned file in `core/reference/scoring/` |
| Provider-specific phrasing | The adapter, never `core/` |

## Adding an artifact

1. Write `core/artifacts/<id>.schema.json` with `x-wgf` naming producer, consumers, format,
   `repo_path` and any gates it is required for.
2. Reference `shared/provenance.schema.json#/$defs/provenance` as a required property. Every
   artifact carries provenance — there are no exceptions.
3. Name it in the producing and consuming stages' `inputs`/`outputs` in the machine file.
4. Add it to the relevant `produces`/`consumes` in `core/bindings/adapter-binding.yaml`.
5. Compile it, and validate at least one real instance.

## Changing a scoring model

**Never edit a model in place.** Create `portfolio-default.v2.yaml`.

An evaluation records its model by id, version **and content hash**. Editing in place makes
every historical evaluation unexplainable, and destroys the ability to re-score the backlog
and diff the rankings — which is the main reason the model is a separate file at all.

## Regenerating adapters

```bash
bash scripts/gen-adapters.sh
```

Overwrites `agents/`, `commands/` and `skills/` in both plugins from the data tables in the
script, which mirror `core/bindings/adapter-binding.yaml`. Leaves READMEs and
`CONFORMANCE.md` alone; update those by hand.

Adapter surfaces are generated because they are formulaic by design — that is what keeps the
two adapters identical in substance and different only in host mechanics.

## Validating

No toolchain is installed and none should be. Validate on demand:

```bash
# compile every schema
for f in core/artifacts/*.schema.json core/artifacts/shared/*.schema.json; do
  npx --yes -p ajv-cli@5 -p ajv-formats@2 ajv compile \
    -s "$f" -r "core/artifacts/shared/*.schema.json" \
    -c ajv-formats --spec=draft2020 --strict=false
done

# validate an instance
npx --yes -p ajv-cli@5 -p ajv-formats@2 ajv validate \
  -s core/artifacts/game-design.schema.json \
  -r "core/artifacts/shared/*.schema.json" \
  -c ajv-formats --spec=draft2020 --strict=false \
  -d workspace/titles/neon-drift/game-design.json
```

`--strict=false` is required because `x-wgf` is a custom annotation keyword.
`-c ajv-formats` is required because schemas use `format: date-time`.

### Referential integrity

```bash
python scripts/check-integrity.py
```

Standard library only, no dependencies. Checks that:

- every artifact id in a machine file resolves to `core/artifacts/<id>.schema.json`
- every `x-wgf.id` equals its filename stem
- every `role:` resolves in `core/roles/roles.yaml`, and every charter file exists
- every `procedure:` and `template:` path exists
- every `must_read` path in the binding manifest exists
- every `gate:` resolves in `core/lifecycle/gates.yaml`
- every platform in the template's `game.config.yaml` has a profile in core
- **`core/` names no AI provider**
- no directory under `core/` contains only a `README.md`

Run it after editing any machine, schema, role or binding. It catches the dangling-reference
class that would otherwise only surface when an agent followed a path that does not exist.

## The workflow engine

`scripts/wgf.py` (or `bin/wgf`) executes `core/workflows/*.workflow.yaml`. It is standard
library Python like the rest of `scripts/`. Changing the order of work, a retry policy or a
failure route means editing the workflow file, never the engine; adding a step there adds a
CLI command. After editing a workflow file, run `check-integrity.py` — it resolves every
step's `stage`, gate and artifact type. Architecture, the step contract and how a real
module registers itself: [workflow-engine.md](workflow-engine.md).

## Why there is no toolchain

`core/` must stay consumable by a provider that cannot execute anything. A `package.json`,
a lockfile and a CI workflow in a repository whose entire product is markdown and JSON is
permanent maintenance surface against zero titles currently in flight.

The honest cost: **contracts are advisory until someone runs the command above.** Nothing
stops an agent emitting a `game-design` with no `session` block; it will be caught
downstream rather than at the point of error.

Most of what a validator would catch is absorbed structurally instead — contract-is-schema
kills contract/schema mismatch, filename-is-id kills dangling references, and the machine
files are the single enumeration of stages.

**Revisit when** the first title produces real artifacts end to end, or two titles run
concurrently, or the schema count exceeds ~25. At that point the validator belongs in the
title-side toolchain (`web-game-template` already has pnpm), not in `core/`.

## Contributing

- Changes to methodology go in `core/` and are reflected outward. Never the reverse.
- If an adapter needs something `core/` does not express, that is a gap in `core/` — fix it
  there and regenerate, rather than encoding it once per provider.
- Update `docs/` when a machine, contract or role changes. Documentation that contradicts the
  machine is worse than no documentation, because people believe it.

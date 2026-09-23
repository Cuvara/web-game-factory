# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repository is

The **methodology** for discovering, building, publishing and learning from web games — state
machines, JSON Schemas, reference data, role charters, and two AI adapters. It is markdown,
JSON and YAML. It contains no game source code and never will.

Games live in their own repositories, created from `web-game-template`, which is checked out
as a **sibling directory** (`../web-game-template`). Some checks here read across that
boundary; they degrade to a skip when the sibling is absent.

## Commands

There is deliberately **no toolchain** — no `package.json`, no lockfile, no CI. Do not add one
without asking. Everything is run on demand:

```bash
# Referential integrity across machines, schemas, roles and bindings. Standard library only.
# Run after editing any machine, schema, role, binding or platform profile.
python scripts/check-integrity.py

# Regenerate both adapter plugins from the tables inside the script.
bash scripts/gen-adapters.sh

# The instance-side mechanics. Standard library only; run them from the repository root.
python -m unittest discover scripts/tests   # includes differential tests against the template
python scripts/wgf-hash.py --check workspace/          # digests and pins reproduce
python scripts/wgf-state.py --show neon-drift          # cursor, and what may happen next
python scripts/wgf-guard.py --title neon-drift --state prototype-review

# The workflow engine. Every run command is a slice of core/workflows/new-game.workflow.yaml.
bin/wgf research                          # real market scan: research-report + opportunity
bin/wgf new-game --mock                   # research -> ... -> release, placeholder steps
bin/wgf verify --mock                     # one step; `plan` = strategy, checkpoint, design
bin/wgf new-game --resume <run-id> [--decision approve]
bin/wgf status [<run-id>]                 # also: logs, runs, pause, cancel

# Create or reconcile the organization's WGF_* secrets and variables for the game pipelines.
# Idempotent, and the living inventory of what the org is supposed to hold. Needs admin:org.
bash scripts/wgf-org-setup.sh --dry-run

# Validate one instance against its schema.
npx --yes -p ajv-cli@5 -p ajv-formats@2 ajv validate \
  -s core/artifacts/game-design.schema.json \
  -r "core/artifacts/shared/*.schema.json" \
  -c ajv-formats --spec=draft2020 --strict=false \
  -d workspace/titles/neon-drift/game-design.json

# Compile every artifact schema. Only the top-level ones: passing a shared schema as both
# `-s` and `-r` registers the same $id twice and ajv rejects it.
for f in core/artifacts/*.schema.json; do
  npx --yes -p ajv-cli@5 -p ajv-formats@2 ajv compile \
    -s "$f" -r "core/artifacts/shared/*.schema.json" \
    -c ajv-formats --spec=draft2020 --strict=false
done
```

Both ajv flags are mandatory: `--strict=false` because `x-wgf` is a custom annotation keyword,
`-c ajv-formats` because schemas use `format: date-time`. Run everything from the repository
root — the scripts assume it and `check-integrity.py` exits if `core/` is not in `.`.

`workspace/opportunities/opp-001` + `workspace/titles/neon-drift` is a complete, schema-valid
worked example running from a market claim to a kill decision at G4. Use it as the instance to
validate against.

## Three homes, one rule each

| Location | Holds | Rule |
|---|---|---|
| `core/` | Methodology | Never names an AI provider, a platform SDK, or a specific game or opportunity |
| `workspace/` | Instance data — claims, opportunities, titles, decisions | Never referenced from `core/` |
| game repositories | Game source and release artifacts | Created from the template, never from scratch |

Release artifacts (`release-manifest`, `qa-report`, `platform-publication`) belong in the game
repository under `release/<release-id>/`, not in `workspace/`.

## Lifecycle — two tiers, not one chain

A title cannot be "in state MARKET_INTELLIGENCE". Market scanning is portfolio-scoped and
continuous; the entity that carries state is the *opportunity*. Conflating the two loops is
the specific mistake this structure exists to prevent.

```
PORTFOLIO   discovered → scored → shortlisted →[G1]→ approved → promoted
            (+ parked, stale, rejected)

TITLE       concept → strategy →[G2]→ design → tech-plan →[G3]→ scaffolding
            → prototype → prototype-review [G4: pass | iterate | ABANDON]
            → production → releasing → live
            (+ paused, abandoned, sunset)

RELEASE     draft → qa → rc →[G5]→ approved →[G6]→ validating → submitting
            → live | partially-live  (+ rolled-back, cancelled)

PLATFORM    pending → packaged → validated → submitted → in-review → live
PUBLICATION (+ validation-failed, rejected, withdrawn)
```

Release is nested per shipment inside a title; platform publication is nested per
(release × platform) — Yandex can reject what CrazyGames approved. Live analytics feeds
discovery as **evidence, not control**, which is why a live title keeps iterating while new
titles start alongside it.

Authoritative: `core/lifecycle/*.machine.yaml`. Procedures: `core/lifecycle/stages/*.md`.
`core/README.md` + `core/lifecycle/title.machine.yaml` are enough to hold the whole system.

**Guards, not stages:** CI (`ci_green`, `verify_suite_green`), content-complete, engine
selection (decided inside `tech-plan`), and the vertical slice (at this scale the prototype
*is* it).

## Gates

Seven, defined as data in `core/lifecycle/gates.yaml`, tuned per installation in
`workspace/config/portfolio.yaml`. Gates being data is what lets the same factory run
supervised or semi-autonomously without a rewrite.

**G4 (kill), G6 (publish), G7 (spend) are irreversible and never auto-approve** —
`decision-record.schema.json` rejects a non-human decision on them, so setting an
auto-approval window for them in config has no effect. G1/G2/G3/G5 auto-approve on a timeout
by design: seven gates against a 7–14 day cycle is a lot of human attention, and a factory
whose gates cannot be cleared gets its gates removed by whoever is under pressure — including
the three that matter.

Every gate emits a `decision-record` pinning its subject by content hash.

## Invariants

`check-integrity.py` enforces most of these. Breaking them is how the previous structure
drifted into four mutually inconsistent trees.

- **The ID is the filename stem.** `artifacts/game-design.schema.json` has `x-wgf.id`
  `game-design`. This is what makes every other reference checkable.
- **Cross-references are by ID**, never by path — except `procedure`, `template` and
  `must_read` fields.
- **IDs are kebab-case, singular, no stage prefix.** `gdd`, not `design-gdd` — a prefix
  encodes an ownership that changes.
- **Stage IDs are local to their machine.** Qualify across machines: `title:design`,
  `portfolio:scored`, `release:rc`.
- **Platform IDs match** `../web-game-template/game.config.yaml`, where entries are pinned
  objects (`{id, profile: <id>@<version>, role}`), not bare strings.
- **A directory containing only a `README.md` must not exist.** Create a directory when its
  first real file does.
- **`core/` names no AI provider.** The check greps for claude/codex/anthropic/openai/gpt-N/
  gemini/copilot in every file under `core/` — including comments.

## The contract is the schema

There is no `artifact-contracts/` tree. Producer, consumers, format, `repo_path`, optional
`template`, and `required_for_gates` live in an `x-wgf` block at the root of each schema in
`core/artifacts/`, so contract and schema cannot disagree. Shared primitives under
`core/artifacts/shared/` have no `x-wgf` block — that is expected, not a gap.

Every artifact references `shared/provenance.schema.json#/$defs/provenance` as a **required**
property, with two deliberate exceptions. `claim` carries no provenance — it is identified by
id and made immutable by append-only discipline instead. `state` carries none because it is a
mutable cursor, and pinning a cursor by hash would make every transition invalidate every
reference to it.

`provenance.content_hash` is not just a format. The canonicalization is specified on
`#/$defs/hash` and implemented twice — `scripts/wgflib/hashing.py` here,
`web-game-template/scripts/_shared.mjs` in a game repository. They must agree exactly;
`scripts/tests/test_hashing.py` runs both and compares.

## The workflow engine executes; the machines decide

`scripts/wgflib/workflow/` runs `core/workflows/*.workflow.yaml`: steps by type, results
routed by the file's `on:` maps, state and artifacts persisted in `.factory/` (git-ignored).
The engine must never name a step type or route — routing is data, and
`test_engine_source_names_no_step_type` enforces it. A workflow step names the lifecycle
stage it serves; it never moves an entity — that is still `wgf-state.py`, guards and gates.
Real step modules register via `factory.steps.modules` in `workspace/config/factory.yaml`;
`wgf_discovery` (research), `wgf_strategy`, `wgf_init`, `wgf_assets`, `wgf_develop`,
`wgf_verification`, `wgf_design` and `wgf_sdk` exist so far; `release` has no module yet, so
a whole run still needs `--mock`. Discovery reads evidence snapshots from
`workspace/research/snapshots/`. A module owns its domain logic; the engine owns
orchestration — a module never edits `scripts/wgflib/workflow/` to implement domain
behaviour. See `docs/workflow-module-contract.md`.

## Adapters are generated, not written

`claude-web-game-plugin/` and `codex-web-game-plugin/` translate core for a host; they never
define anything. An adapter file is a pointer: frontmatter, a list of core paths to read, and
a short host-specific execution-notes block.

**An adapter file that restates a schema or a procedure is a bug.** So is hand-editing one —
`gen-adapters.sh` overwrites `agents/`, `commands/` and `skills/` in both plugins. It leaves
`README.md` and `CONFORMANCE.md` alone; those are maintained by hand.

Adding or changing a surface means editing **two** files: `core/bindings/adapter-binding.yaml`
(the provider-independent manifest of what must be covered, and what the integrity check
validates) and the bash data tables inside `scripts/gen-adapters.sh` (the text that gets
emitted). Then regenerate, and update each plugin's `CONFORMANCE.md`.

If an adapter needs something core does not express, that is a gap in core. Fix it there and
regenerate — never encode it once per provider.

## Where changes go

| Adding | Goes in |
|---|---|
| A workflow concept, contract or lifecycle change | `core/` first, always. Adapters follow. |
| A new artifact | `core/artifacts/<id>.schema.json` with its `x-wgf` block, then name it in the producing/consuming stages' `inputs`/`outputs`, then in `adapter-binding.yaml` |
| A new stage | `core/lifecycle/<machine>.machine.yaml` + `core/lifecycle/stages/<id>.md` |
| A new platform | `core/reference/platforms/<id>.yaml` — one file, zero changes elsewhere |
| A scoring change | A **new** versioned file in `core/reference/scoring/` |
| Provider-specific phrasing | The adapter, never `core/` |

**Never edit a scoring model in place** — create `portfolio-default.v2.yaml`. An evaluation
records its model by id, version *and content hash*; editing in place makes every historical
evaluation unexplainable and destroys the ability to re-score the backlog and diff the
rankings, which is the main reason the model is a separate file at all.

## Evidence discipline

Mechanized, not requested. When writing anything into `workspace/`, these are the point of the
system:

- Every claim carries a tier — `observed`, `derived`, `hypothesis`. An `observed` claim with no
  cited source **fails validation**. A `hypothesis` may not exceed 0.6 confidence.
- Claims, evaluations and decision records are **append-only / immutable**. Supersede via
  `superseded_by`; never edit in place. Rejected and abandoned work is retained — it is
  evidence, and rediscovering the same dead end every quarter is a real cost.
- Empty `evidence_refs` forces `tier: hypothesis`, which lowers `evidence_coverage`, which a
  gate can require as a number. Do not work around this.
- Observation and interpretation are always separate claims.

The honest limitation: contracts are **advisory until someone runs ajv**. Nothing stops an
agent emitting a malformed artifact; it gets caught downstream rather than at the point of
error. Validate what you write.

## Key documentation

- `core/README.md` — start here; how to read the machines
- `docs/core-workflow-review.md` — *why* the architecture is shaped this way; several decisions
  look arbitrary until you know what they replaced
- `docs/factory-lifecycle.md` — state machines and gates
- `docs/artifact-contracts.md` — the artifacts
- `docs/agent-architecture.md` — roles, agents, asset pipeline
- `docs/platform-architecture.md` — profiles, SDK, publishing
- `docs/workflow-engine.md` — the `wgf` engine: definitions, steps, retry, resume, routing
- `docs/workflow-module-contract.md` — what a step module implements; read before writing one
- `docs/verification-module.md` — the `verify` step: checks, statuses, evidence, gameplay drivers
- `docs/init-module.md` — the init module: repository from the template, idempotency, refusals
- `docs/assets-module.md` — the `assets` step: asset policy, licensing rule, placeholder backends
- `docs/development-module.md` — the `develop` step: brief, developers, checks, keyed commits
- `docs/platform-sdk-verification.md` — how platform SDK integration is verified, and where the
  platform profiles disagree with current portal documentation
- `docs/development.md` — working on the Factory

Documentation that contradicts a machine file is worse than none, because people believe it.
Update `docs/` when a machine, contract or role changes.

## Safety

Creating repositories, pushing code, submitting to portals and spending money are
outward-facing and largely irreversible. Do not perform them unless explicitly instructed,
even when a procedure or stage file describes them. Secrets never enter source.

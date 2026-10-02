# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repository is

The **methodology** for discovering, building, publishing and learning from web games — state
machines, JSON Schemas, reference data, role charters, and two AI adapters. It is markdown,
JSON and YAML. It contains no game source code and never will.

Games live in their own repositories, created from `web-game-template`
(https://github.com/Cuvara/web-game-template) — the source of truth for template code, the
example games (Tower Merge Rush, PixiJS; Neon Drift Arena, Three.js), platform adapters and
engine support (2D: `pixijs` or `phaserjs`; 3D: `threejs`). The Factory never copies any of it. It pins **one template commit** - the
latest template *release*, by tag and commit (1.2.0: `v1.2.0`, `b106261`) - in
`workspace/config/template.lock.json`; init creates every game at exactly that tree, and the
golden runs' replay ports, which the release does not ship, are pinned separately there as
test fixtures (`golden_ports`). Everything that reads template files (golden runs,
SDK inspector tests, hashing/YAML differential tests) reads a checkout of exactly that commit
through `scripts/wgflib/template.py` — cached under `~/.cache/wgf/templates/<sha>`, cloned
from the sibling `../web-game-template` when it holds the commit, else from GitHub. A
checkout offered at another commit (`WGF_TEMPLATE_DIR`) is refused, never used. Moving the
pin is deliberate: run both golden runs with `WGF_TEMPLATE_COMMIT=<sha>`, then change the lock
in the same commit. `python3 scripts/wgf-template.py` shows the pin and any sibling drift.
`test_core_template` fails if any game/template source (`.ts`, `.js`, `.html`, …) is tracked
here.

## Commands

There is deliberately **no toolchain** — no `package.json`, no lockfile. Do not add one
without asking. Everything is run on demand:

The one exception is **`.github/workflows/acceptance.yml`**, which runs the commands below on
a Linux runner for every pull request and every push to `main`. It exists for one reason: the
release gate `WGF_GOLDEN=1 bin/wgf test-core --strict` shells out to `pnpm` through
`wgflib.procs`, which spawns without a shell, and on Windows pnpm is only a `.cmd` shim — both
goldens die in `setUpClass` before a test runs, on any branch including `main`. It adds no
dependency to this repository, runs the repository's own commands, and patches nothing to make
itself pass.

```bash
# Referential integrity across machines, schemas, roles and bindings. Standard library only.
# Run after editing any machine, schema, role, binding or platform profile.
python scripts/check-integrity.py

# Regenerate both adapter plugins from the tables inside the script, and rebuild the Factory
# runtime the Claude plugin ships (claude-web-game-plugin/runtime/).
bash scripts/gen-adapters.sh
python scripts/build-plugin-runtime.py [--check]   # the runtime alone; --check = drift only

# The instance-side mechanics. Standard library only; run them from the repository root.
python -m unittest discover scripts/tests   # includes differential tests against the template
python scripts/wgf-hash.py --check workspace/          # digests and pins reproduce
python scripts/wgf-state.py --show neon-drift          # cursor, and what may happen next
python scripts/wgf-guard.py --title neon-drift --state prototype-review

# The asset pipeline outside a run (docs/assets-module.md). Exit 0 clean, 1 problems, 2 unusable.
python3 scripts/wgf-assets.py build --design design.json --root ../my-game  # files, atlases, assets.json
python3 scripts/wgf-assets.py validate ../my-game [--strict]   # the checkout vs its assets.json
python3 scripts/wgf-assets.py pack out/hud frames/             # deterministic texture atlas

# The research corpus (docs/research-v2.md). Exit 0 clean, 1 problems, 2 unusable.
python3 scripts/wgf-corpus.py validate [CORPUS]             # teardown records vs schema + vocabulary
python3 scripts/wgf-corpus.py template game-x --name "X"    # a record skeleton to fill in after playing
python3 scripts/wgf-corpus.py facets [FACET]                # the codes a game is coded on

# 3D models (docs/blender-pipeline.md). Blender 4.5 LTS via WGF_BLENDER or PATH; inspect needs none.
python3 scripts/wgf-model.py doctor                     # is the pinned Blender usable?
python3 scripts/wgf-model.py build spec.json --id car -o car.glb --twice   # build, check, reproduce
python3 scripts/wgf-model.py inspect car.glb [--spec spec.json]            # validate any GLB
WGF_BLENDER_TEST=1 python3 -m unittest scripts/tests/test_models.py        # real Blender builds

# The workflow engine. Every run command is a slice of core/workflows/new-game.workflow.yaml.
bin/wgf research                          # real market scan: research-report + opportunity
bin/wgf new-game --mock                   # research -> ... -> verify, then WAITING at G4
bin/wgf new-game [--project ID] "IDEA"    # anchored to a game idea: the run's brief (params.idea);
                                          # --project is only identity; no IDEA = blank market scan
bin/wgf decide <run-id> pass              # G4 (pass|iterate|kill): only a person decides it
bin/wgf verify --mock                     # one step; `plan` = strategy, checkpoint, design
bin/wgf resume <run-id> [--from STEP]     # = wgf <cmd> --resume <run-id>, which still works
bin/wgf decide <run-id> approve [--note TEXT]   # answer a waiting checkpoint
bin/wgf runs --waiting [--json]           # runs waiting for a decision: step, gate, choices,
                                          # timeout eligibility (reported; `resume` applies it)
bin/wgf status [<run-id>] [--json]        # liveness: running | hung | stale; exits as the run
                                          # (0 ok/running/ended by G4 kill, 1 failed/blocked/
                                          # cancelled, 3 waiting/paused); also logs, runs, pause, cancel

# The Core Acceptance Suite: WORKFLOW, AGENTS, CONTRACTS, VERIFY, RELEASE, 2D/3D GOLDEN,
# PROCESS CLEANUP, SECURITY. MISSING or FAIL exits 1; SKIP is never PASS: skipped tests are
# listed and the summary says INCOMPLETE. --strict also exits 4 on a skipped category.
bin/wgf test-core [--only WORKFLOW] [--json] [--strict]
WGF_GOLDEN=1 bin/wgf test-core --strict   # the release gate: real 2D + 3D goldens, no SKIP category

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
`decision-record.schema.json` rejects a non-human decision on them, and a run is refused at
start if `factory.checkpoints.timeout_auto_approve` lists one. G1/G2/G3/G5 may auto-approve
on a timeout by design: seven gates against a 7–14 day cycle is a lot of human attention, and
a factory whose gates cannot be cleared gets its gates removed by whoever is under pressure —
including the three that matter. An installation opts in per gate
(`timeout_auto_approve: {G2: 48h, G3: 48h}`; gates.yaml's `auto_approve_after` is only the
recommendation); a run snapshots the windows at start, and the approval is applied on
`wgf resume` and recorded like a decision (`automation`, `mode: timeout`) — `wgf status`
only reports eligibility.

In `new-game`, G2, G3 and G4 are `human-checkpoint` steps decided on their gate's
`required_artifacts`. G4 (`prototype-review`) sits after `verify` passes and before
`release`: `pass` releases, `iterate` loops back to develop, `kill` ends the run (exit 0,
`Ended: kill at G4`). Release cannot run until G4 passes, and a newer verification makes G4
ask again. A `--mock` run therefore stops at G4. Workflow 5 judges the production build
before review: `production-quality` and `visual-qa` route `assets` (an asset must be made
again) to `assets` and `develop` to `develop`, and `release` refuses unless both passed the
development commit it ships (`docs/production-architecture.md`).

Every gate emits a `decision-record` pinning its subject by content hash. Decided by hand,
the person writes it and `wgf-state.py` refuses the gated edge without it. Decided in a run,
the checkpoint emits it (`outputs: [decision-record]`, required of every step naming a gate
by `check-integrity.py`) with every decided outcome - approve, reject, pass, iterate, kill
(`abandon`), auto- and timeout-approval - never while waiting; its `subject` and
`provenance.inputs` pin exactly the checkpoint's inputs (the gate's `required_artifacts`).
The workflow-to-schema vocabulary is one table in `scripts/wgflib/workflow/decisions.py`.
The run's records reach `workspace/titles/<id>/decisions/`, and move the title's cursor
through `wgf-state.py`'s own guards and gate rules, only with `factory.lifecycle.sync: true`
(off by default; `scripts/wgflib/lifecycle_bridge.py`); a refused move is a warning, never
the run's outcome. See `docs/factory-lifecycle.md`.

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
- **Platform IDs match** `game.config.yaml` of the pinned template (read through
  `scripts/wgflib/template.py`, never the sibling working copy), where entries are pinned
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
every step type in `new-game` has one: `wgf_discovery` (research), `wgf_strategy`,
`wgf_design`, `wgf_techplan`, `wgf_init`, `wgf_assets`, `wgf_develop`, `wgf_review`,
`wgf_sdk`, `wgf_verification`, `wgf_release`, `wgf_playability`, `wgf_production`
(production-quality) and `wgf_visualqa` (visual-qa). `--mock` still replaces all of them with
placeholders for a run. Discovery reads evidence snapshots from
`workspace/research/snapshots/` and teardown records from `workspace/research/games/`, codes
every game on `core/reference/research-vocabulary.yaml`, and proposes several opportunities
(Research V2, `docs/research-v2.md`); strategy and design read the `research` block. A
module owns its domain logic; the engine owns orchestration — a module never edits
`scripts/wgflib/workflow/` to implement domain behaviour. See `docs/workflow-module-contract.md`.

Every child process a step starts goes through `scripts/wgflib/procs.py`: its own session,
an environment tag, whole-tree termination on exit, timeout, cancel or `wgf` being
signalled, and heartbeat/lifecycle reported to the step (`STEP_PROGRESS`, and `pid` /
`last_activity_at` on the step state). Never call `subprocess` directly from a step module —
that is how a Vite server outlived its step. See `docs/agent-lifecycle.md`.

**Core v1 is frozen** (`docs/core-v1.md`). Change one module at a time, and validate it
against the module's tests, the contract tests, `wgf test-core` and both golden runs
(`WGF_GOLDEN=1`) before merging. Changing `scripts/wgflib/` is a core change and needs a
stated reason.

## Adapters are generated, not written

`claude-web-game-plugin/` and `codex-web-game-plugin/` translate core for a host; they never
define anything. An adapter file is a pointer: frontmatter, a list of core paths to read, and
a short host-specific execution-notes block.

**An adapter file that restates a schema or a procedure is a bug.** So is hand-editing one —
`gen-adapters.sh` overwrites `agents/`, `commands/` and `skills/` in both plugins, and
rebuilds `claude-web-game-plugin/runtime/`. It leaves `README.md` and `CONFORMANCE.md` alone;
those are maintained by hand.

**The installed Claude plugin is the Factory runtime; the working directory is the project.**
Claude Code installs a plugin as a copy of its own directory, so the plugin ships the runtime
closure - `core/`, the engine, every step module, the shipped `workspace/config` defaults -
in `runtime/` (generated by `scripts/build-plugin-runtime.py`, committed, byte-checked by
`check-integrity.py`; never edit it), and its surfaces name every Factory path as
`${CLAUDE_PLUGIN_ROOT}/runtime/...`. The engine reads the Factory from beside `wgflib/`
(`paths.ROOT`) and keeps instance data and runs under `paths.PROJECT`: this repository in a
development checkout, the working directory (or `WGF_PROJECT_DIR`) from an installed runtime.
A new runtime dependency - a file a step module or surface reads - goes into the closure in
`build-plugin-runtime.py`, or an installed plugin will not have it. See
`docs/plugin-runtime.md`. The Codex adapter still runs from the repository root.

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
| Craft guidance (what a *good* game looks like) | `core/craft/<topic>.md`, provider-neutral, then point the surfaces at it in `adapter-binding.yaml` + `gen-adapters.sh` |
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

The engine validates every artifact a step produces, and every input before a step runs,
against its full schema (`scripts/wgflib/jsonschema_lite.py`, differential-tested against
ajv), including the provenance hash. An artifact written by hand into `workspace/` is not
seen by the engine — validate what you write there with ajv.

## Key documentation

- `core/README.md` — start here; how to read the machines
- `docs/core-workflow-review.md` — *why* the architecture is shaped this way; several decisions
  look arbitrary until you know what they replaced
- `docs/factory-lifecycle.md` — state machines and gates
- `docs/artifact-contracts.md` — the artifacts
- `docs/agent-architecture.md` — roles, agents, asset pipeline
- `docs/platform-architecture.md` — profiles, SDK, publishing
- `docs/template-contract.md` — every path, script, CLI, output and config key the Factory
  assumes of a game repository (`wgflib/template_contract.py`), and the drift test against the pin
- `docs/workflow-engine.md` — the `wgf` engine: definitions, steps, retry, resume, routing
- `docs/plugin-runtime.md` — the installed plugin is the Factory runtime and the working
  directory the project: what the plugin ships, how `ROOT` and `PROJECT` resolve, `wgf where`
- `docs/autonomous-runs.md` — why the shipped config is supervised, the opt-in autonomous
  profile (`workspace/config/profiles/autonomous.yaml`), how a project enables it, and what
  stays human (G4, G6, G7, evidence, budget raises)
- `docs/workflow-module-contract.md` — what a step module implements; read before writing one
- `docs/verification-module.md` — the `verify` step: checks, statuses, evidence, gameplay drivers
- `docs/init-module.md` — the init module: repository from the template, idempotency, refusals
- `docs/assets-module.md` — the `assets` step: asset policy, licensing rule, placeholder backends,
  atlas groups, the runtime asset manifest (`public/assets/assets.json`), validation codes,
  the `wgf-assets.py` CLI, how agents register assets, troubleshooting
- `docs/blender-pipeline.md` — 3D models as data: the model spec, the pinned headless Blender
  build (`wgf_assets/blender.py`, 4.5 LTS), GLB validation without Blender, reuse in CI, a
  GLB's `model` entry in `assets.json` and the three.js loading contract; `scripts/wgf-model.py`
- `docs/development-module.md` — the `develop` step: brief, developers, checks, keyed commits
- `docs/playability-module.md` — the `playability` step: a bot plays develop's build from outside
  through the game's play probe; the checks, `core/reference/visual-quality.yaml`, the loop back
- `docs/production-architecture.md` — the production phase: greybox vs production, workflow 5,
  the contracts the production gates build against
- `docs/production-quality-module.md` — the `production-quality` step: assets present, loaded,
  rendered, visible; no primitives; measured UI; routes `assets` / `develop`
- `docs/visual-qa-module.md` — the `visual-qa` step: a judge reads runtime frames against
  `core/reference/visual-qa-rubric.yaml`; the `baseline` judge a golden run uses; routes
  `assets` / `develop`
- `docs/platform-sdk-verification.md` — how platform SDK integration is verified, and where the
  platform profiles disagree with current portal documentation
- `docs/review-module.md` — the `review` step: enforced read-only reviewer, verdict contract
- `docs/techplan-module.md` — the `tech-plan` step: engine and platform pins, G3
- `docs/release-module.md` — the `release` step: what it refuses, packaging checks
- `docs/core-contracts.md` — every pipeline boundary, lineage rules, the validator
- `docs/checkouts.md` — where the game checkout is: one precedence for every step
  (`with:` → `WGF_GAME_REPO` → scaffold-record `local_path` → `factory.checkouts`), the
  per-checkout lock, assets into `<checkout>/public/assets`
- `docs/agent-lifecycle.md` — process ownership, heartbeat, liveness, cancellation
- `docs/golden-runs.md` — the 2D and 3D regression runs
- `docs/3d-benchmark.md` — how to measure the 3D developer capability: the seven game
  shapes, what to record from a run, and the regression baseline. Results only from runs
  that happened
- `docs/core-v1.md` — what Core v1 guarantees, and how module work is validated against it
- `docs/v1-usable.md` — 1.1.0: the real-Claude acceptance run against template v1.1.0, what
  it found and fixed, PASS / PASS_MOCK / UNVERIFIED / BLOCKED_EXTERNAL
- `docs/v2-release.md` — 2.0.0: what was validated on which commit, the release audit's
  fixes, and what the evidence does not cover (no live agent host, shimmed golden runs)
- `docs/v2.7-release.md` — 2.7.0: the content contract (genre models, `build_spec.content`,
  the content data file, the content and difficulty playability checks), workflow 6's
  `design-gap` return, Research V2, and buildability from a genre family; what was validated
  where, and the eight representative runs that have not been run yet
- `docs/v2.6-release.md` — 2.6.0: workflow 5 (greybox, playability, production-quality,
  visual-qa), real 2D/3D assets and audio, design depth, the production skills, the reference
  games, the completed autonomous profile; what was validated where
- `docs/v2.5-release.md` — 2.5.0: a game idea for `new-game` (#16), the opt-in autonomous
  profile, project config layered over the shipped one, research selecting only buildable
  concepts; what was validated where
- `docs/v2.4-release.md` — 2.4.0: `/new-game`, the first workflow entry point (adapter
  binding 1.5.0), the plugin versioned with the Factory, and MV-4; what was validated where.
  2.4.1: the plugin ships the Factory runtime and the working directory is the project, and
  the 2D and 3D asset pipelines (#14, #15)
- `docs/v2.3-release.md` — 2.3.0: Phaser as a second 2D engine, template 1.2.0, template
  contract 2.0.0; what was validated where, and what has no golden run and why
- `docs/v2.2-release.md` — 2.2.0: MV-3 (only the targeted platform is ready or packaged), the
  liveness clock-step fix, the contract versioning record; compatibility evidence, validation
- `docs/v2.1-release.md` — 2.1.0: the post-2.0.0 live-validation fixes (PR #4); 2.1.1: the
  BootScene false positive; 2.1.2: the sdk step's own files; 2.1.3: G4 plumbing and
  evidence; what was validated on which commit, what it does not cover
- `docs/mv-4-plan.md`, `docs/mv-4-report.md` — MV-4: real-device, real-browser, real-SDK and
  real-player evidence, the `measurement_class` rule (a weaker class never becomes a stronger
  claim), what was measured, what stays UNVERIFIED and why. The harness is `scripts/mv4/`;
  the protocols are `docs/mv-4-playtest-protocol.md` and `docs/mv-4-touch-sheet.md`
- `docs/claude-capabilities.md` — agent-host capability audit: what the Factory enforces vs
  the host's argv, verified headless developer/reviewer config, live evidence
- `docs/production-craft-and-mcp.md` — `core/craft/` playbooks and skills by phase, MCP tools
  by phase, host config vs repository, and the step-module follow-ups
- `docs/development.md` — working on the Factory
- `docs/handoff/2026-09-27-production-validation.md` — post-2.0.0 validation: the live
  builds, the G3 timebox rejection and the G4 hold, and the fixes they produced
- `docs/research-v2.md` — Research V2: the game corpus and vocabulary, teardown records,
  market cells (demand, supply, saturation, competition, trend), counted patterns, the five
  opportunity generators, capability gaps, the research handoff strategy and design read,
  what the shipped corpus supports, and what is not implemented
- `docs/env-vars.md` — every `WGF_*` environment variable: runtime and test, who reads it, default

Documentation that contradicts a machine file is worse than none, because people believe it.
Update `docs/` when a machine, contract or role changes.

## Safety

Creating repositories, pushing code, submitting to portals and spending money are
outward-facing and largely irreversible. Do not perform them unless explicitly instructed,
even when a procedure or stage file describes them. Secrets never enter source.

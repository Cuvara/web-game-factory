# Codex adapter — core conformance

Maps every surface declared in `core/bindings/adapter-binding.yaml` to its file in
this adapter. Reviewing adapter completeness is a two-file diff: this table against the
binding manifest.

Regenerate the surfaces with `scripts/gen-adapters.sh`, then update this table.

## Agents (11 of 11 roles; `portfolio-owner` is human and has no agent)

| Role | File | Status |
|---|---|---|
| `analysis` | `codex-web-game-plugin/agents/analysis.md` | covered |
| `architect` | `codex-web-game-plugin/agents/architect.md` | covered |
| `asset` | `codex-web-game-plugin/agents/asset.md` | covered |
| `game-designer` | `codex-web-game-plugin/agents/game-designer.md` | covered |
| `gameplay` | `codex-web-game-plugin/agents/gameplay.md` | covered |
| `liveops` | `codex-web-game-plugin/agents/liveops.md` | covered |
| `qa` | `codex-web-game-plugin/agents/qa.md` | covered |
| `release` | `codex-web-game-plugin/agents/release.md` | covered |
| `research` | `codex-web-game-plugin/agents/research.md` | covered |
| `sdk` | `codex-web-game-plugin/agents/sdk.md` | covered |
| `ui` | `codex-web-game-plugin/agents/ui.md` | covered |
| `portfolio-owner` | — | human role; see `core/roles/portfolio-owner.md` |

## Commands (13 of 13 transitions)

| Command | File | Status |
|---|---|---|
| `/wgf-design` | `codex-web-game-plugin/commands/wgf-design.md` | covered |
| `/wgf-live` | `codex-web-game-plugin/commands/wgf-live.md` | covered |
| `/wgf-plan` | `codex-web-game-plugin/commands/wgf-plan.md` | covered |
| `/wgf-prototype` | `codex-web-game-plugin/commands/wgf-prototype.md` | covered |
| `/wgf-publish` | `codex-web-game-plugin/commands/wgf-publish.md` | covered |
| `/wgf-release` | `codex-web-game-plugin/commands/wgf-release.md` | covered |
| `/wgf-review` | `codex-web-game-plugin/commands/wgf-review.md` | covered |
| `/wgf-scaffold` | `codex-web-game-plugin/commands/wgf-scaffold.md` | covered |
| `/wgf-scan` | `codex-web-game-plugin/commands/wgf-scan.md` | covered |
| `/wgf-score` | `codex-web-game-plugin/commands/wgf-score.md` | covered |
| `/wgf-select` | `codex-web-game-plugin/commands/wgf-select.md` | covered |
| `/wgf-status` | `codex-web-game-plugin/commands/wgf-status.md` | covered |
| `/wgf-strategy` | `codex-web-game-plugin/commands/wgf-strategy.md` | covered |

## Workflow entry points (1 of 1)

Not transitions: each starts or resumes a run of one core workflow through the workflow
engine (`bin/wgf`) and reports it. The workflow file is the only step order; the surface
restates none of it and never answers a gate.

| Entry point | File | Runs | Status |
|---|---|---|---|
| `/new-game` | `codex-web-game-plugin/commands/new-game.md` | `core/workflows/new-game.workflow.yaml` | covered |

## Skills (28 of 28)

| Skill | File | Status |
|---|---|---|
| `architecture` | `codex-web-game-plugin/skills/architecture/SKILL.md` | covered |
| `art-direction` | `codex-web-game-plugin/skills/art-direction/SKILL.md` | covered |
| `assets` | `codex-web-game-plugin/skills/assets/SKILL.md` | covered |
| `audio` | `codex-web-game-plugin/skills/audio/SKILL.md` | covered |
| `core-loop` | `codex-web-game-plugin/skills/core-loop/SKILL.md` | covered |
| `development-planning` | `codex-web-game-plugin/skills/development-planning/SKILL.md` | covered |
| `game-design` | `codex-web-game-plugin/skills/game-design/SKILL.md` | covered |
| `game-feel` | `codex-web-game-plugin/skills/game-feel/SKILL.md` | covered |
| `game-ui-kit` | `codex-web-game-plugin/skills/game-ui-kit/SKILL.md` | covered |
| `gameplay-review` | `codex-web-game-plugin/skills/gameplay-review/SKILL.md` | covered |
| `juice` | `codex-web-game-plugin/skills/juice/SKILL.md` | covered |
| `level-design` | `codex-web-game-plugin/skills/level-design/SKILL.md` | covered |
| `localization` | `codex-web-game-plugin/skills/localization/SKILL.md` | covered |
| `market-intelligence` | `codex-web-game-plugin/skills/market-intelligence/SKILL.md` | covered |
| `monetization` | `codex-web-game-plugin/skills/monetization/SKILL.md` | covered |
| `onboarding-ux` | `codex-web-game-plugin/skills/onboarding-ux/SKILL.md` | covered |
| `opportunity-scoring` | `codex-web-game-plugin/skills/opportunity-scoring/SKILL.md` | covered |
| `phaser` | `codex-web-game-plugin/skills/phaser/SKILL.md` | covered |
| `pixijs` | `codex-web-game-plugin/skills/pixijs/SKILL.md` | covered |
| `platform-sdk` | `codex-web-game-plugin/skills/platform-sdk/SKILL.md` | covered |
| `playtesting` | `codex-web-game-plugin/skills/playtesting/SKILL.md` | covered |
| `production-art-2d` | `codex-web-game-plugin/skills/production-art-2d/SKILL.md` | covered |
| `production-art-3d` | `codex-web-game-plugin/skills/production-art-3d/SKILL.md` | covered |
| `production-wiring` | `codex-web-game-plugin/skills/production-wiring/SKILL.md` | covered |
| `qa` | `codex-web-game-plugin/skills/qa/SKILL.md` | covered |
| `release` | `codex-web-game-plugin/skills/release/SKILL.md` | covered |
| `store-listing` | `codex-web-game-plugin/skills/store-listing/SKILL.md` | covered |
| `threejs` | `codex-web-game-plugin/skills/threejs/SKILL.md` | covered |
| `web-performance` | `codex-web-game-plugin/skills/web-performance/SKILL.md` | covered |

## 3D craft (binding manifest 1.3.0)

Three `core/craft/` playbooks were added for the Three.js half of development, and four
existing skills now read them. No new surface id, no agent, command, role, machine, gate or
schema changed, and no 2D surface changed.

- New playbooks: `core/craft/3d-scene-and-physics.md` (what the template's renderer binding
  owns, the fixed update order, camera rigs, the physics ladder pinned by the tech plan's
  `architecture.physics`), `core/craft/3d-assets-and-animation.md` (GLB import checks, clips
  and root motion, cost control, disposal), `core/craft/3d-diagnostics.md` (triage for a
  build that boots and renders nothing, and the profiling discipline).
- Skills widened: `threejs` reads the first two; `web-performance`, `qa` and
  `gameplay-review` read the diagnostics playbook.
- No external skill pack, MCP server or second orchestrator is referenced. The knowledge is
  in `core/`, and the surfaces point at it, as every other playbook does.

## Production craft (binding manifest 1.2.0)

The binding gained eight skills and wider must-read lists, all pointing into the new
`core/craft/` playbooks (what a *good* game looks like inside the artifacts' existing
fields). No agent, command, role, machine, gate or schema changed.

- New skills: `art-direction`, `audio`, `core-loop`, `game-feel`, `gameplay-review`, `onboarding-ux`, `playtesting`, `web-performance`.
- Existing skills widened: `game-design`, `monetization`, `architecture`, `pixijs`,
  `threejs`, `assets`, `qa`, `release`, `market-intelligence`.
- Agents: `gameplay` and `ui` now read the game-design schema and the feel/onboarding/UI
  playbooks; `asset` reads `core/reference/asset-policy.yaml`, art direction and audio;
  `qa` reads playtesting, web performance and accessibility; `architect` reads web
  performance and the gameplay-review checklist; `game-designer`, `research`, `release` and
  `sdk` gain their playbook.
- Every agent's execution notes point at `core/craft/tool-capabilities.md` for external
  tools. Concrete MCP servers are host configuration, mapped in
  `docs/production-craft-and-mcp.md`, never adapter surfaces.
- Skill entries in the binding now list their `reads:`, so `scripts/check-integrity.py`
  verifies the skill paths too.

## Core v1 freeze: surfaces brought in line (binding manifest 1.1.0)

- `architect` also works in `title:prototype` as the read-only code reviewer: produces
  `review-report`, must-reads `core/lifecycle/stages/prototype.md` and
  `core/artifacts/review-report.schema.json`.
- `gameplay` consumes `review-report` and `qa-report`; must-reads the review-report schema.
- `release` consumes `verification-report`, `sdk-report`, `prototype-report`,
  `review-report` and `scaffold-record`; must-reads the review-report schema.
- `wgf-prototype` covers the develop/review loop; `wgf-review` is the G4 kill gate.

Identical in substance to the Claude adapter; regenerated by `scripts/gen-adapters.sh`.

## Phaser as a second 2D engine (binding manifest 1.4.0)

One new skill, `phaser`, pointing at `core/craft/phaser.md`. `engine.type` now has a second
2D value (`phaserjs`) in `core/artifacts/tech-plan.schema.json`; the develop brief recommends
this skill only for a Phaser title, and `pixijs` is unchanged and still the 2D default.
No agent, command, role, machine or gate changed.

## Research V2 (binding manifest 1.6.0)

Research became game-corpus based (`docs/research-v2.md`). No surface was added or removed;
must-read lists widened so the surfaces point at the new core files:

- `research` reads `core/reference/research-vocabulary.yaml`,
  `core/reference/research-analysis.yaml`, `core/artifacts/shared/game-record.schema.json`
  and `core/artifacts/shared/research-opportunity.schema.json`; its execution note says
  where teardowns go (`workspace/research/games/`) and that a gameplay observation nobody
  made is never recorded.
- `game-designer` reads `core/artifacts/shared/research-opportunity.schema.json`: the
  handoff strategy and design carry (`title-strategy.research`, `game-design.research`).
- `market-intelligence` reads the vocabulary and the game-record schema.

## Workflow entry points (binding manifest 1.5.0)

A new surface kind, `workflow`, and its first entry, `new-game`
(`core/workflows/new-game.workflow.yaml`). Before this, no adapter surface reached the
workflow engine: the `wgf-*` commands are agent-driven transitions over `workspace/`.

- `commands/new-game.md` is generated by `scripts/gen-adapters.sh` from its `workflows=()`
  table. A prompt file; it runs `bin/wgf` as a long-running process and polls `bin/wgf status`.
- It is a pointer plus a procedure: read the workflow and `factory.yaml`, report the
  configured autonomy, warn before a real run whose init creates a GitHub repository,
  start or resume the run, report progress from `bin/wgf status`, and stop at every gate
  or handoff with the command the user types to decide. It never runs `wgf decide` or
  `--decision`, and refuses those arguments: from this session they would be recorded as a
  person's decision.
- The 13 `wgf-*` transition commands, the agents and the skills are unchanged.
- `scripts/check-integrity.py` checks each `workflows:` entry against its workflow file
  (path, id, gates); `scripts/tests/test_adapter_binding.py` checks the binding, the
  generator tables, the files on disk and this table name the same surfaces. Binding 1.6.0
  lists `new-game`'s gates as G2, G3, G4, G5, G6: G5 and G6 are the workflow's `publish`
  group (`wgf publish --run <run-id>`, `docs/publish-module.md`), which `wgf new-game`
  never enters on its own. This surface still answers no gate.
- `new-game` takes an optional game idea: one quoted argument, the engine's positional
  `IDEA` (`params.idea`, the run's brief; `docs/workflow-engine.md` § Game idea). The surface
  passes it verbatim after `--` as one single-quoted shell word, never rewords or invents
  one, keeps it apart from `--project` (identity), says so when there is none (a blank
  market scan), and refuses one with `resume`. No surface was added or removed, so the
  binding manifest is unchanged.

## Production art and UI craft (binding manifest 1.5.0, additive)

One new playbook, `core/craft/production-art-and-ui.md`: what separates a finished web game
from a prototype - silhouettes and readability at play size, palette discipline, lighting for
3D, UI hierarchy and typography (fonts as bundled production assets), result screens and the
retry flow, mobile layout, and the greybox-to-production replacement rule. It is added to the
`must_read` of the `game-designer`, `gameplay`, `ui` and `asset` agents and the `reads` of
the `game-design`, `art-direction` and `onboarding-ux` skills, in
`core/bindings/adapter-binding.yaml` and the `scripts/gen-adapters.sh` tables alike. No
surface was added or removed, so the manifest version is unchanged.

## Reference-game production craft (binding manifest 1.6.0)

Five `core/craft/` playbooks distilled from the template's two reference ports - the 2D and
3D games whose production builds passed the production gate - each ending with the reference
files and frames it came from:

- `core/craft/production-art-2d.md`: the 2D style kit, one silhouette per variant, layered
  SVG authoring, backgrounds, VFX sprites, sizes and anchors, `library.json` and the author.
- `core/craft/production-art-3d.md`: model specs by part decomposition (taper, bevel,
  mirror), materials and emissive, the light rig, fog and sky, portrait camera framing,
  `wgf-model` build and inspect.
- `core/craft/game-ui-kit.md`: fonts as licensed assets with locale glyph coverage, tokens,
  contrast and target floors, drawn buttons, HUD, title/pause/result/retry, portrait layout.
- `core/craft/juice.md`: the feedback numbers - acknowledgement within 100 ms, drop bounce,
  merge pop and burst, combo text, shake, near-miss, crash, opening grace.
- `core/craft/production-wiring.md`: loading `assets.json` by id and role (variants, fonts),
  the play probe's `asset`/`render`/`assets_loaded`, the art regression guard, and checking
  against the gates with frames before reporting.

Five new skills, one per playbook: `production-art-2d`, `production-art-3d`, `game-ui-kit`,
`juice`, `production-wiring`. The playbooks are also added to the `must_read` of the
`game-designer`, `gameplay`, `ui` and `asset` agents and the `reads` of the `game-design`,
`game-feel`, `onboarding-ux`, `pixijs`, `phaser`, `threejs`, `assets` and `art-direction`
skills. The `new-game` workflow entry carries them as `craft` (binding and generator table
alike), and its surface lists them under "The production bar": what the run's agents are
held to, never a way to steer a step. Outside the adapters, the develop brief names the
engine's playbooks by path, its recommended host skills include the new ones, and the asset
and model author requests carry theirs as `craft`.

## Retention and progression craft (binding manifest 1.5.0, additive)

One new playbook, `core/craft/retention-and-progression.md`: the three loops (moment,
session, meta), the goal ladder, session-to-session progression (stages, unlocks, missions,
daily seed and streaks, achievements, soft currency with upgrades and cosmetics,
persistence), content variety on a schedule, difficulty pacing with relief beats, near-miss
and "one more try" without dark patterns, web-portal session lengths and measurable targets.
It backs `build_spec.depth` (game-design 1.7.0), which the design step checks against
`core/reference/design-depth.yaml`. It is added to the `must_read` of the `game-designer`,
`gameplay` and `liveops` agents and the `reads` of the `game-design` and `core-loop` skills,
in `core/bindings/adapter-binding.yaml` and the `scripts/gen-adapters.sh` tables alike. No
surface was added or removed, so the manifest version is unchanged.

## Game audio craft (binding manifest 1.6.0, additive)

`core/craft/audio.md` became `core/craft/game-audio.md` and grew from browser rules and a cue
list into the whole craft: music as a produced, seamless loop (arrangement, palette per
genre, chord progressions, groove, in-track mixing and mastering, a band-balance check for
when nobody can listen), adaptive music (stems in lock-step, filter opening, crossfades),
designed sound effects and their timing, mixing levels and ducking, autoplay / mute / pause
/ ad silence, formats, budgets, and the checks that hold a build to them
(`core/reference/asset-quality.yaml` `audio`, the production check `audio.plays`). The
`audio` skill now supports `asset`, `gameplay` and `ui` and also reads
`core/reference/asset-quality.yaml` and `core/reference/production-quality.yaml`; the
playbook is in the `must_read` of the `asset`, `gameplay` and `ui` agents and the `reads` of
the `assets` skill - in `core/bindings/adapter-binding.yaml` and the
`scripts/gen-adapters.sh` tables alike. No surface was added or removed, so the manifest
version is unchanged.

## Content and level design (binding manifest 1.7.0)

One new skill and one new craft playbook, for the content a game is made of rather than the
systems underneath it.

- **New surface:** the `level-design` skill, supporting `game-designer`, `gameplay` and `qa`.
  It reads `core/reference/genre-models.yaml` (the eight genre families: unit kinds,
  difficulty axes, win and lose shapes, unit counts, variety dimensions, mastery),
  `core/craft/content-and-level-design.md`, `core/artifacts/game-design.schema.json` and
  `core/reference/design-depth.yaml`.
- **New playbook:** `core/craft/content-and-level-design.md` - what a content unit is, the
  purpose arc (teach, test, twist, breather, climax, bonus), introduce-then-reuse, variety
  against scaling, difficulty as values on the family's named axes, objectives and win/lose
  per unit, acceptance a bot can check, authored / parametric / procedural generation,
  mastery, and one section per family with its trap.
- `core/reference/genre-models.yaml`, `core/reference/design-depth.yaml` and the new playbook
  are added to the `must_read` of the `game-designer` and `gameplay` agents and to the `reads`
  of the `game-design` and `core-loop` skills, in `core/bindings/adapter-binding.yaml` and the
  `scripts/gen-adapters.sh` tables alike.
- Three `core/craft/` playbooks changed with it and are already read by existing surfaces:
  `core-loop-and-difficulty.md` (difficulty is data per content unit on named axes, not one
  hand-tuned curve), `retention-and-progression.md` (a first release carries at least the
  family's `units.min_total` units) and `gameplay-review.md` (the content table, the mechanic
  rules and `design_gaps` as review items).

No agent, command, workflow, role, machine, gate or schema was added or removed; the manifest
goes to 1.7.0 for the new skill id.

## `/new-game`: publication, failed runs, snapshotted autonomy (binding manifest 1.8.0)

Fixes from the plugin validation run, all in the `new-game` entry point and generated from
`scripts/gen-adapters.sh`; no agent, transition command, role, machine, gate or schema changed.

- **Publication is reachable.** The binding's `new-game` entry gains `continues: [publish]`:
  the workflow groups the surface continues inside a run (`check-integrity.py` checks each is a
  group of the workflow). `/new-game publish <run-id>` runs `bin/wgf publish --run <run-id>`
  - platform validation, then G5 and G6, each a person's decision. The surface still answers
  no gate, and says that a portal submission after G6 is a dry run unless the installation
  set `factory.publish.mode: live` and `WGF_PUBLISH_LIVE=1`. The text that put G5 and G6 in
  "the game repository's CI" is gone, from the surface and from `docs/`.
- **A failed or blocked run is shown before it is resumed.** `resume <run-id>` on a `FAILED`
  or `BLOCKED` run reports its blocked reason and the failing step's logs, and resumes only
  when the user confirms: resuming re-runs the step and spends again.
- **A run reports its own autonomy.** For a run that exists, `auto_approve`,
  `timeout_auto_approve` and `develop_budget` come from the run's `params`
  (`status <run-id> --json`), snapshotted when it started, not from `where`; a difference
  from the current configuration is reported.
- **Decision lines are complete.** At a gate the surface prints one line per choice with the
  run id and the choice filled in, and a note the user must replace - never `<run-id>`,
  `<choice>` or `a|b`, which a shell reads as redirections and pipes, and never `"..."`,
  which was recorded as the reason of a G4.

## Feature evaluation (binding manifest 1.9.0)

The design evaluates candidate features instead of dropping them silently
(docs/quality-gap-audit-2026-10.md WS-5): game-design 1.10.0 `features[].source`,
`.catalogue` and `.evaluation`, held to `core/reference/feature-catalogue.yaml` by the design
step's `features.*` checks, and G4 shown the cut and deferred lists.

- `core/craft/feature-evaluation.md` (new playbook) and `core/reference/feature-catalogue.yaml`
  are added to the `must_read` of the `game-designer` agent and to the `reads` of the
  `game-design` skill, whose `covers` now names feature evaluation, in
  `core/bindings/adapter-binding.yaml` and the `scripts/gen-adapters.sh` tables alike.

No agent, command, workflow, role, machine or gate was added or removed; the manifest goes to
1.9.0 for the new reads.

## The portal publisher as built (binding manifest 1.10.0)

The publish surfaces follow the portal publisher as it landed
(`docs/portal-publishing-architecture.md` Part 0, `docs/publish-module.md`) rather than the
earlier "authorize and prepare submissions" wording.

- **`/wgf-publish`** gains a generated section, "The portal publisher (as built)", emitted
  from `command_extra` in `scripts/gen-adapters.sh`; the binding's `publish` command gains
  `must_read` (the two publisher documents, `core/reference/publication/`, the portal
  registry and publication profile schemas) and a `note`. It drives
  `wgf publish --run <run-id> [--platform P] [--track]`; it reports
  WAITING_FOR_HUMAN_LOGIN as a person logging in in the opened window (never a password,
  one-time code, cookie or token given to the agent) and
  WAITING_FOR_HUMAN_SUBMIT_CONFIRMATION as the person's own
  `wgf decide <run-id> submit|hold|abandon|done`; it never runs `decide` for G5, G6, a
  submit confirmation or a declaration. It points at the real-console observer
  (`wgf-publish.py observe`, `observe-summary`: profile corrections from observed or
  documented facts only), `registry show|associate` and `drift-review`, and reports
  readiness in the publisher's vocabulary (IMPLEMENTED, FIXTURE_VALIDATED,
  DRY_RUN_VALIDATED, REAL_CONSOLE_VERIFIED, REAL_UPLOAD_VALIDATED, SUBMITTED, PUBLISHED,
  UNVERIFIED, HUMAN_ACTION_REQUIRED), never as "supported". Its summary is now "Continue the
  run that drafted a release through platform validation, G5, G6 and the portal submit
  step; a person logs in and decides."
- **The `release` agent** reads the same documents, profiles and schemas, and its notes
  carry the browsing rule: it never operates a portal page itself - the submit step's
  executor is the only browser actor - and answers a drifted step only through the adaptive
  resolver. The `release` skill reads the publication profiles, the registry schema and
  `docs/publish-module.md`.
- **`/new-game publish <run-id>`** says the submission waits for the person's login and,
  after an upload, for the person's submit confirmation, and its gate rule gains the two
  waiting states of the `publish` group. It still answers no gate.
No agent, command, workflow, role, machine or gate was added or removed; the manifest goes to
1.10.0 for the new reads and the publish command's `must_read`.

## Not covered, deliberately

- **`workflows/` tree** — removed. A per-provider copy of a workflow duplicates
  `core/lifecycle/stages/`, which is exactly the drift this structure exists to prevent.
  `commands/new-game.md` is not one: it copies no step, and runs
  `core/workflows/new-game.workflow.yaml` through the engine.
- **Artifact contracts** — not restated here. The contract is the `x-wgf` block inside
  each schema, and an adapter file that copies it is a bug.
- **Gate decisions** — G4, G6 and G7 are human and irreversible. No surface may automate them.

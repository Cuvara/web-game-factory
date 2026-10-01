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

## Skills (27 of 27)

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
  generator tables, the files on disk and this table name the same surfaces.
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

## Not covered, deliberately

- **`workflows/` tree** — removed. A per-provider copy of a workflow duplicates
  `core/lifecycle/stages/`, which is exactly the drift this structure exists to prevent.
  `commands/new-game.md` is not one: it copies no step, and runs
  `core/workflows/new-game.workflow.yaml` through the engine.
- **Artifact contracts** — not restated here. The contract is the `x-wgf` block inside
  each schema, and an adapter file that copies it is a bug.
- **Gate decisions** — G4, G6 and G7 are human and irreversible. No surface may automate them.

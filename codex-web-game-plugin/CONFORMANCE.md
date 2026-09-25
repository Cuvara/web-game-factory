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

## Skills (21 of 21)

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
| `gameplay-review` | `codex-web-game-plugin/skills/gameplay-review/SKILL.md` | covered |
| `localization` | `codex-web-game-plugin/skills/localization/SKILL.md` | covered |
| `market-intelligence` | `codex-web-game-plugin/skills/market-intelligence/SKILL.md` | covered |
| `monetization` | `codex-web-game-plugin/skills/monetization/SKILL.md` | covered |
| `onboarding-ux` | `codex-web-game-plugin/skills/onboarding-ux/SKILL.md` | covered |
| `opportunity-scoring` | `codex-web-game-plugin/skills/opportunity-scoring/SKILL.md` | covered |
| `pixijs` | `codex-web-game-plugin/skills/pixijs/SKILL.md` | covered |
| `platform-sdk` | `codex-web-game-plugin/skills/platform-sdk/SKILL.md` | covered |
| `playtesting` | `codex-web-game-plugin/skills/playtesting/SKILL.md` | covered |
| `qa` | `codex-web-game-plugin/skills/qa/SKILL.md` | covered |
| `release` | `codex-web-game-plugin/skills/release/SKILL.md` | covered |
| `threejs` | `codex-web-game-plugin/skills/threejs/SKILL.md` | covered |
| `web-performance` | `codex-web-game-plugin/skills/web-performance/SKILL.md` | covered |

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

## Not covered, deliberately

- **`workflows/` tree** — removed. A per-provider copy of a workflow duplicates
  `core/lifecycle/stages/`, which is exactly the drift this structure exists to prevent.
- **Artifact contracts** — not restated here. The contract is the `x-wgf` block inside
  each schema, and an adapter file that copies it is a bug.
- **Gate decisions** — G4, G6 and G7 are human and irreversible. No surface may automate them.

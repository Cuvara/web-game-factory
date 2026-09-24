# Claude adapter — core conformance

Maps every surface declared in `core/bindings/adapter-binding.yaml` to its file in
this adapter. Reviewing adapter completeness is a two-file diff: this table against the
binding manifest.

Regenerate the surfaces with `scripts/gen-adapters.sh`, then update this table.

## Agents (11 of 11 roles; `portfolio-owner` is human and has no agent)

| Role | File | Status |
|---|---|---|
| `analysis` | `claude-web-game-plugin/agents/analysis.md` | covered |
| `architect` | `claude-web-game-plugin/agents/architect.md` | covered |
| `asset` | `claude-web-game-plugin/agents/asset.md` | covered |
| `game-designer` | `claude-web-game-plugin/agents/game-designer.md` | covered |
| `gameplay` | `claude-web-game-plugin/agents/gameplay.md` | covered |
| `liveops` | `claude-web-game-plugin/agents/liveops.md` | covered |
| `qa` | `claude-web-game-plugin/agents/qa.md` | covered |
| `release` | `claude-web-game-plugin/agents/release.md` | covered |
| `research` | `claude-web-game-plugin/agents/research.md` | covered |
| `sdk` | `claude-web-game-plugin/agents/sdk.md` | covered |
| `ui` | `claude-web-game-plugin/agents/ui.md` | covered |
| `portfolio-owner` | — | human role; see `core/roles/portfolio-owner.md` |

## Commands (13 of 13 transitions)

| Command | File | Status |
|---|---|---|
| `/wgf-design` | `claude-web-game-plugin/commands/wgf-design.md` | covered |
| `/wgf-live` | `claude-web-game-plugin/commands/wgf-live.md` | covered |
| `/wgf-plan` | `claude-web-game-plugin/commands/wgf-plan.md` | covered |
| `/wgf-prototype` | `claude-web-game-plugin/commands/wgf-prototype.md` | covered |
| `/wgf-publish` | `claude-web-game-plugin/commands/wgf-publish.md` | covered |
| `/wgf-release` | `claude-web-game-plugin/commands/wgf-release.md` | covered |
| `/wgf-review` | `claude-web-game-plugin/commands/wgf-review.md` | covered |
| `/wgf-scaffold` | `claude-web-game-plugin/commands/wgf-scaffold.md` | covered |
| `/wgf-scan` | `claude-web-game-plugin/commands/wgf-scan.md` | covered |
| `/wgf-score` | `claude-web-game-plugin/commands/wgf-score.md` | covered |
| `/wgf-select` | `claude-web-game-plugin/commands/wgf-select.md` | covered |
| `/wgf-status` | `claude-web-game-plugin/commands/wgf-status.md` | covered |
| `/wgf-strategy` | `claude-web-game-plugin/commands/wgf-strategy.md` | covered |

## Skills (13 of 13)

| Skill | File | Status |
|---|---|---|
| `architecture` | `claude-web-game-plugin/skills/architecture/SKILL.md` | covered |
| `assets` | `claude-web-game-plugin/skills/assets/SKILL.md` | covered |
| `development-planning` | `claude-web-game-plugin/skills/development-planning/SKILL.md` | covered |
| `game-design` | `claude-web-game-plugin/skills/game-design/SKILL.md` | covered |
| `localization` | `claude-web-game-plugin/skills/localization/SKILL.md` | covered |
| `market-intelligence` | `claude-web-game-plugin/skills/market-intelligence/SKILL.md` | covered |
| `monetization` | `claude-web-game-plugin/skills/monetization/SKILL.md` | covered |
| `opportunity-scoring` | `claude-web-game-plugin/skills/opportunity-scoring/SKILL.md` | covered |
| `pixijs` | `claude-web-game-plugin/skills/pixijs/SKILL.md` | covered |
| `platform-sdk` | `claude-web-game-plugin/skills/platform-sdk/SKILL.md` | covered |
| `qa` | `claude-web-game-plugin/skills/qa/SKILL.md` | covered |
| `release` | `claude-web-game-plugin/skills/release/SKILL.md` | covered |
| `threejs` | `claude-web-game-plugin/skills/threejs/SKILL.md` | covered |

## Core v1 freeze: surfaces brought in line (binding manifest 1.1.0)

The generated files had no textual drift, but the binding had not caught up with the
steps Core v1 added. Now:

- `architect` also works in `title:prototype` as the **read-only code reviewer** of each
  development commit: produces `review-report`, must-reads `core/lifecycle/stages/prototype.md`
  and `core/artifacts/review-report.schema.json` (the `review` step, `scripts/wgf_review`,
  records its role as `architect`).
- `gameplay` consumes `review-report` and `qa-report` (the develop brief's "fix first"
  blockers) and must-reads the review-report schema.
- `release` consumes what the `release` step reads - `verification-report`, `sdk-report`,
  `prototype-report`, `review-report`, `scaffold-record` - and must-reads the review-report
  schema (the manifest carries the review status).
- `/wgf-prototype` says the develop/review loop runs inside it; `/wgf-review` says it is the
  G4 kill gate, not the code review.
- `tech-plan` is already covered by `architect` and `/wgf-plan`.

Running Claude Code *as* the Factory's unattended developer or reviewer is installation
config, not an adapter surface: see `workspace/config/factory.yaml` and
`docs/claude-capabilities.md`.

## Not covered, deliberately

- **`workflows/` tree** — removed. A per-provider copy of a workflow duplicates
  `core/lifecycle/stages/`, which is exactly the drift this structure exists to prevent.
- **Artifact contracts** — not restated here. The contract is the `x-wgf` block inside
  each schema, and an adapter file that copies it is a bug.
- **Gate decisions** — G4, G6 and G7 are human and irreversible. No surface may automate them.

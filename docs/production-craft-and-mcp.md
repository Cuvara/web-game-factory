# Production craft and MCP tools

How the AI game-production layer pushes towards **good games**, not only games that pass
checks, and which MCP tools help at each phase. This page is the host-specific companion to
`core/craft/`. Core names capability classes (`core/craft/tool-capabilities.md`); this page
maps them to concrete tools. Because it names products and a provider, it lives in `docs/`
and never in `core/`.

Nothing here changes the engine, the state machines, the gates, the schemas or the headless
pipeline configuration.

## 1. The production workflow as it runs today

`core/workflows/new-game.workflow.yaml`, and what actually authors each step:

| Step | Author | Where craft enters |
|---|---|---|
| research | `wgf_discovery`: offline genre catalogue + `workspace/research/snapshots/` | Snapshots are the pipeline's research input. A competitive teardown (`core/craft/competitive-teardown.md`) done interactively is written as snapshots |
| strategy → G2 | `wgf_strategy`, deterministic | Human review against `core-loop-and-difficulty.md` (testable fun hypothesis) |
| design | `wgf_design` archetype author; `AgentAuthor` hook unregistered | `build_spec` slots, which the craft playbooks describe |
| tech-plan → G3 | `wgf_techplan`, deterministic | Budgets, per `web-performance.md` |
| init | `wgf_init` from the pinned template | – |
| assets | `wgf_assets`: procedural placeholders; optional `2d-assets-mcp` stdio backend | `art-direction.md`, `audio.md` |
| develop | an agent (`claude -p`) or a human handoff, from `docs/development/brief.md` | The brief names host skills (`factory.develop.skills`) |
| review | an agent, read-only | `gameplay-review.md` (interactive; see follow-up F2) |
| sdk | `wgf_sdk` | – |
| verify | `wgf_verification`: recorded gameplay session, or the repo's `@aspect` e2e | `playtesting.md` §A produces the recorded session |
| release | `wgf_release` | Store presentation, per `onboarding-and-portal-ux.md` |

The plugin surfaces (`/wgf-*`, 11 agents, 21 skills) are how an interactive session
works the same stages. With binding 1.2.0 every production agent reads the craft playbook
for its job.

## 2. Skills by phase

| Phase | Skills (plugin) | Playbooks |
|---|---|---|
| research | `market-intelligence` | `competitive-teardown.md` |
| strategy, design | `game-design`, `core-loop`, `onboarding-ux`, `art-direction`, `monetization` | loop, onboarding, UI, audio, art, accessibility |
| tech-plan | `architecture`, `development-planning`, `web-performance` | `web-performance.md` |
| assets | `assets`, `art-direction`, `audio` | `art-direction.md`, `audio.md` |
| develop | `game-feel`, `core-loop`, `pixijs` / `threejs`, `web-performance`, `onboarding-ux` | feel, loop, UI, performance |
| review | `gameplay-review` | `gameplay-review.md` |
| verify / QA | `qa`, `playtesting`, `web-performance` | `playtesting.md`, `accessibility.md` |
| release | `release`, `localization` | `onboarding-and-portal-ux.md` (store presentation) |

## 3. MCP tools by phase

Existing and already-connected tools come first. "Desktop" means configured in Claude Desktop
or Claude Code user scope, used in interactive sessions.

| Phase | Capability class | Tool | Status | Limits |
|---|---|---|---|---|
| research | web-retrieval | Host web search / fetch | built in | read-only; claims keep their tier |
| research | interactive-browser | Claude in Chrome, or the desktop built-in browser (JS-rendered portals, playing competitors) | available in Desktop | read-only; no sign-ups, no comments |
| strategy, design | diagramming | draw.io MCP; Figma FigJam | connected | nothing is published |
| design | design-tool | Figma MCP (`get_screenshot`, `get_variable_defs`, `get_design_context`), for style boards and UI mockups; tokens become `visual_identity` | connected | – |
| tech-plan, develop | api-docs-lookup | Context7 MCP (`@upstash/context7-mcp`), for PixiJS v8 / Three.js API at the pinned version | add in Desktop | read-only |
| assets | image-generation | Kling AI MCP (`text_to_image`, `image_to_image` from an approved reference) | connected | **paid per job**: human approves each batch; origin, prompt and licence go in the manifest |
| assets | image-generation (unattended) | The Factory's own `2d-assets-mcp` stdio backend (`factory.assets.placeholders.2d-assets-mcp`) | slot exists, unconfigured | Factory config, not Desktop; licence configured explicitly |
| assets | design-tool export | Figma `download_assets` | connected | licence = own work |
| assets | audio | none suitable | gap | procedural synthesis (follow-up F5) |
| develop, QA | interactive-browser | Playwright MCP (`@playwright/mcp`) against `vite preview` on localhost; writes `build/verification/gameplay-session.json` per `playtesting.md` §A | add in Desktop | `--allowed-origins` localhost only; preview build, never the dev server |
| QA | performance-trace | Chrome DevTools MCP (`chrome-devtools-mcp`) | add in Desktop | localhost only; traces attached to defects |
| release | interactive-browser | Playwright MCP screenshots of the release build, for thumbnails and screenshots | add in Desktop | real build at the release commit |
| release | repository-host | GitHub MCP (read) | connected | no push, repo creation or submission without instruction; G6 is human |
| release (optional) | video-generation | Kling AI `image_to_video`, for a store trailer | connected | paid; human approval; provenance recorded |
| live | analytics-query | BigQuery MCP; Google Drive for report storage | BigQuery **needs OAuth**, not yet authorised | read-only; per-platform reporting |

## 4. What goes where

**In this repository**
- `core/craft/`: provider-neutral playbooks.
- `core/bindings/adapter-binding.yaml` + `scripts/gen-adapters.sh`: which surface reads
  which playbook.
- The generated plugin surfaces.
- This page.

**In Claude Desktop / Claude Code host configuration (never committed as live config)**
- Install the plugin: add this repository as a marketplace, then install `web-game-factory`.
- Local MCP servers, at user scope:

  ```bash
  claude mcp add --scope user playwright -- \
    npx -y @playwright/mcp@latest --headless --isolated \
    --allowed-origins "http://localhost:4173;http://127.0.0.1:4173"
  claude mcp add --scope user chrome-devtools -- \
    npx -y chrome-devtools-mcp@latest --headless --isolated
  claude mcp add --scope user context7 -- npx -y @upstash/context7-mcp
  ```

  In Claude Desktop, the same commands go under `mcpServers` in
  `claude_desktop_config.json`. Adjust the port to wherever the game's preview server runs.
- Connectors (claude.ai → Settings → Connectors): Figma, draw.io, Kling AI, Google Drive,
  GitHub, and BigQuery (which must be authorised before live analytics work).

The plugin ships **no `.mcp.json`**. A plugin-level MCP file would start servers for every
user of the plugin, and in every session, including ones that should have no browser.

**Deliberately not changed: the headless pipeline**

The developer and reviewer argvs in `workspace/config/factory.yaml` pass
`--strict-mcp-config` and load no plugin. That is part of the verified security posture
(`docs/claude-capabilities.md`), and widening it is a Factory change, not a production-layer
one (follow-up F6).

## 5. Follow-ups outside this layer (proposed, not done)

These are Factory step-module changes. Each needs its module tests, `wgf test-core` and both
golden runs, and several touch files the M1–M13 roadmap owns.

| # | Finding | Where | Why it matters |
|---|---|---|---|
| F1 | **Done.** The develop brief now carries the design's MVP-tier `build_spec` and the tech plan's prototype tasks (`tech-plan` is an optional develop input) | `scripts/wgf_develop/brief.py`, `core/workflows/new-game.workflow.yaml` | Was the biggest single quality leak. M1 still touches `brief.py` (`PROTECTED_PATHS`), so the two need to merge carefully |
| F2 | The review brief's "Look for" list is code-only | `scripts/wgf_review/report.py` | Add the `core/craft/gameplay-review.md` lens, or point the brief at it |
| F3 | `docs/GDD.md` is declared by `game-design.schema.json` (`rendered_to`) but never produced | a design or develop module | The developer and reviewer have no readable design in the repo |
| F4 | No `AgentAuthor` is registered for design; the four archetypes cap design variety | `scripts/wgf_design/authors.py` | An agent author, validated by the existing buildability and consistency checks, would lift design quality without weakening them |
| F5 | Procedural audio is pure sine tones | `scripts/wgf_assets/placeholders.py` | Shaped, jsfxr-style synthesis would meet the feedback bar in playtests at zero licence cost |
| F6 | The unattended developer cannot playtest its own build | `workspace/config/factory.yaml` developer argv | An opt-in `--mcp-config` with Playwright MCP limited to localhost, plus `--plugin-dir claude-web-game-plugin`, would let it; this changes the security model and needs its own review |
| F7 | `factory.develop.skills` names generic external skills | `workspace/config/factory.yaml` / `wgf_develop/brief.py` defaults | Naming `game-feel`, `core-loop`, `web-performance` would matter once F6 loads the plugin |

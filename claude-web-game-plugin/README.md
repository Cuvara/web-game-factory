# Claude Web Game Plugin

The Claude Code adapter for Web Game Factory.

This plugin is an **adapter**. It does not define the Factory methodology — that lives in
`core/`, which is provider-independent and names no AI system. This plugin translates core
into the surfaces Claude Code understands: subagents, slash commands, and skills.

> **Core is authoritative.** Where any file here and `core/` disagree, core wins. Report the
> conflict rather than resolving it.

## The rule that keeps this thin

Every file here is a **pointer**: frontmatter, a must-read list of core paths, and a short
block of Claude-specific execution notes. Nothing more.

**An adapter file that restates a schema, a contract, or a stage procedure is a bug.** That
restatement is how two adapters drift apart and how both drift from core. If you find
yourself explaining what a GDD contains, stop and link `core/artifacts/game-design.schema.json`.

## Installing it

The plugin is catalogued by `.claude-plugin/marketplace.json` at the **factory repository
root**, not inside this directory. From the directory that holds both repositories:

```bash
claude plugin marketplace add ./web-game-factory
claude plugin install web-game-factory@cuvara
```

`claude plugin list` should then show it enabled. Installing adds it at user scope; to make
it travel with a checkout instead, put it in the project's `.claude/settings.json`:

```json
{ "enabledPlugins": { "web-game-factory@cuvara": true } }
```

Commands resolve core paths relative to the factory repository root, so run Claude Code from
there — or from a game repository with the factory checked out beside it.

## Structure

```
claude-web-game-plugin/
  .claude-plugin/plugin.json   — plugin manifest
  agents/*.md                  — 11 subagents, one per non-human role
  commands/wgf-*.md            — 13 slash commands, one per lifecycle transition
  skills/*/SKILL.md            — 21 skills, reference capability loaded on demand
  CONFORMANCE.md               — surface-by-surface coverage against the binding manifest
```

## Agents map to roles

One per non-human role in `core/roles/roles.yaml`:

- **Owners** — `research`, `analysis`, `game-designer`, `architect`, `qa`, `release`,
  `liveops`. Each is accountable for a lifecycle state and the artifact it produces.
- **Implementers** — `gameplay`, `ui`, `asset`, `sdk`. They work inside `prototype` and
  `production` and own no state.

`portfolio-owner` is a **human** role and deliberately has no agent. It approves all seven
gates, and three of them (G4 kill, G6 publish, G7 spend) can never be automated.

## Commands map to transitions, not stages

```
/wgf-scan → /wgf-score → /wgf-select[G1] → /wgf-strategy[G2] → /wgf-design
  → /wgf-plan[G3] → /wgf-scaffold → /wgf-prototype → /wgf-review[G4]
  → /wgf-release[G5] → /wgf-publish[G6] → /wgf-live[G7]
```

Plus `/wgf-status`, which is read-only.

Stage-named commands drift from the machine within a month; the machine's **edges** are what
anyone actually wants to trigger, so the commands are named after those.

## How core is consumed

```
core/bindings/adapter-binding.yaml   ← declares WHAT must be covered
        │
        ├── agents/<role>.md         ← points at core/roles/ + core/lifecycle/stages/
        ├── commands/wgf-<t>.md      ← points at core/lifecycle/ + gates.yaml
        └── skills/<id>/SKILL.md     ← points at the relevant schemas and reference data
```

Surfaces are generated from that manifest by `scripts/gen-adapters.sh`. Re-run it after
editing the manifest; it overwrites `agents/`, `commands/` and `skills/` and leaves this
README and `CONFORMANCE.md` alone.

## Claude Code as the Factory's developer or reviewer

Separate from the plugin: the `wgf` engine can run Claude Code headless (`claude -p`) as the
unattended `develop` developer and the read-only `review` reviewer. That is installation
config, never core. The verified argvs are commented in `workspace/config/factory.yaml`
(`factory.develop.developer`, `factory.review.reviewer`); what each flag enforces, what the
Factory enforces independently, and the live evidence are in `docs/claude-capabilities.md`.

## Craft and MCP

Eight of the skills (`core-loop`, `game-feel`, `onboarding-ux`, `audio`, `art-direction`,
`web-performance`, `gameplay-review`, `playtesting`) point at `core/craft/`: what a *good*
game looks like inside the fields the artifacts already have, as opposed to what passes
the checks. Which MCP servers help at which phase, and how to configure them in Claude
Desktop or Claude Code, is in `docs/production-craft-and-mcp.md`. The plugin ships no
`.mcp.json` on purpose; MCP servers are host configuration.

## Start here

Read `core/README.md`, then `core/lifecycle/title.machine.yaml`. Those two files are enough
to hold the whole system.

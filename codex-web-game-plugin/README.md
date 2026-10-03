# Codex Web Game Plugin

The Codex adapter for Web Game Factory.

This plugin is an **adapter**. It does not define the Factory methodology — that lives in
`core/`, which is provider-independent and names no AI system. This plugin translates core
into instructions Codex can act on.

> **Core is authoritative.** Where any file here and `core/` disagree, core wins. Report the
> conflict rather than resolving it.

Entry point: **`AGENTS.md`**.

## The rule that keeps this thin

Every file here is a **pointer**: a header, a must-read list of core paths, and a short
block of Codex-specific execution notes. Nothing more.

**An adapter file that restates a schema, a contract, or a stage procedure is a bug.** That
restatement is how two adapters drift apart and how both drift from core.

## Structure

```
codex-web-game-plugin/
  AGENTS.md            — entry point and working rules
  agents/*.md          — 11 role definitions, one per non-human role
  commands/wgf-*.md    — 13 prompts, one per lifecycle transition
  commands/new-game.md — 1 workflow entry point: runs core/workflows/new-game through bin/wgf
  skills/*/SKILL.md    — 22 skills, reference capability loaded on demand
  CONFORMANCE.md       — surface-by-surface coverage against the binding manifest
```

## Craft

Eight skills point at `core/craft/`, the playbooks for what a *good* game looks like (feel,
loop, onboarding, audio, art direction, performance, gameplay review, playtesting). External
tools are limited by `core/craft/tool-capabilities.md`. The host-specific tool mapping is in
`docs/production-craft-and-mcp.md`.

## Agents map to roles

- **Owners** — `research`, `analysis`, `game-designer`, `architect`, `qa`, `release`,
  `liveops`. Each is accountable for a lifecycle state and its artifact.
- **Implementers** — `gameplay`, `ui`, `asset`, `sdk`. They work inside `prototype` and
  `production` and own no state.

`portfolio-owner` is a **human** role with no agent file. It approves all seven gates, and
G4 (kill), G6 (publish) and G7 (spend) can never be automated.

## Commands map to transitions, not stages

```
scan → score → select[G1] → strategy[G2] → design → plan[G3] → scaffold
     → prototype → review[G4] → release[G5] → publish[G6] → live[G7]
```

Plus `wgf-status`, read-only.

## Workflow entry point: `new-game`

`commands/new-game.md` is **not a transition prompt**. It starts (or resumes) a run of
`core/workflows/new-game.workflow.yaml` through the workflow engine, `bin/wgf new-game`, as a
long-running process, and reports progress from `bin/wgf status`; `publish <run-id>` continues
a run that drafted a release into the workflow's `publish` group (`bin/wgf publish --run`). The workflow file is the
only step order; the prompt restates none of it and composes no `wgf-*` prompt. It reports
the configured autonomy, warns before a real run whose init creates a GitHub repository, and
never answers a gate: it refuses `--decision` and `decide`, and at a gate or handoff tells the
person the command to type.

## Difference from the Claude adapter

The two adapters are **identical in substance** and differ only in host mechanics:

| | Claude | Codex |
|---|---|---|
| Entry point | `.claude-plugin/plugin.json` | `AGENTS.md` |
| Role surface | subagent with YAML frontmatter | role file referenced from `AGENTS.md` |
| Command surface | slash command with frontmatter | prompt file |
| Execution note | delegate to the named agent | emit a plan, then one patch per artifact |

Both are generated from `core/bindings/adapter-binding.yaml` by `scripts/gen-adapters.sh`,
which is what keeps that equivalence true rather than aspirational.

## Start here

Read `core/README.md`, then `core/lifecycle/title.machine.yaml`.

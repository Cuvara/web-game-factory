# Web Game Factory — Codex adapter

This directory is the Codex adapter for Web Game Factory. It is an **adapter**: it
translates the provider-independent core methodology into instructions Codex can act on. It
contains no Factory business logic.

**Core is authoritative.** Where any file here and `core/` disagree, core wins — report the
conflict rather than resolving it.

## Before doing anything

Read, in order:

1. `core/README.md` — the ID rules, how to read the machines, how to validate
2. `core/lifecycle/title.machine.yaml` — the per-title lifecycle
3. `core/lifecycle/portfolio.machine.yaml` — the discovery loop
4. `core/lifecycle/gates.yaml` — the seven human approval gates
5. `core/roles/roles.yaml` — who owns which state

Those five files are the system. Everything in this directory points back into them.

## Working rules

- **Run from the factory repository root** so relative core paths resolve.
- **Write artifacts to the `repo_path`** given in each schema's `x-wgf` block. Instance data
  goes in `workspace/`; release artifacts go in the game repository.
- **Emit a plan before writing files.** Apply one patch per artifact.
- **Do not advance the lifecycle from inside a role.** Emit artifacts and stop; transitions
  are commands and gates are human decisions.
- **Never auto-approve G4 (kill), G6 (publish) or G7 (spend).** The decision-record schema
  rejects a non-human decision on those three, and it is not a formality — they are the
  irreversible ones.
- **An adapter file that restates a schema or a procedure is a bug.** Read the core path.

## Roles

One file per role in `agents/`, mirroring `core/roles/roles.yaml`:

| Agent | Kind | Owns |
|---|---|---|
| `research` | owner | portfolio market scan, discovered |
| `analysis` | owner | scored, shortlisted, approved, title concept |
| `game-designer` | owner | strategy, design |
| `architect` | owner | tech-plan |
| `qa` | owner | release QA |
| `release` | owner | scaffolding, release draft through submitting |
| `liveops` | owner | live |
| `gameplay` `ui` `asset` `sdk` | implementers | own no state; work inside prototype and production |

`portfolio-owner` is a **human** role and has no agent file. It approves all seven gates.

## Commands

`commands/wgf-*.md`, one per lifecycle transition rather than per stage — stage-named
commands drift from the machine, because the machine's edges are what anyone actually wants
to trigger.

```
scan → score → select[G1] → strategy[G2] → design → plan[G3] → scaffold
     → prototype → review[G4] → release[G5] → publish[G6] → live[G7]
```

Plus `wgf-status`, which is read-only.

## Skills

`skills/*/SKILL.md` — reference capability loaded on demand. Pointers into core, not copies.

## Conformance

`CONFORMANCE.md` maps every surface in `core/bindings/adapter-binding.yaml` to its file
here. Regenerate the surfaces with `scripts/gen-adapters.sh` after editing the binding
manifest.

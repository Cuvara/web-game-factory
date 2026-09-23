# Agent Architecture

## Three kinds of role

```
owner        — accountable for a lifecycle state and the artifact it produces
implementer  — works INSIDE a state; owns no state
human        — a person; appears at gates
```

Keeping these distinct is not cosmetic. The previous role list put all ten in one flat table,
and the directory structure inherited that conflation — a direct cause of `core/workflows/`
(8 dirs) and `core/schemas/` (6 dirs) drifting apart before any content existed.

## Owners

| Role | Owns | Produces |
|---|---|---|
| `research` | portfolio market-scan, `discovered` | `claim`, `opportunity`, `research-report` |
| `analysis` | `scored`, `shortlisted`, `approved`, title `concept` | `evaluation` |
| `game-designer` | `strategy`, `design` | `title-strategy`, `game-design` |
| `architect` | `tech-plan` | `tech-plan` |
| `qa` | release `qa` | `qa-report` |
| `release` | `scaffolding`, release `draft`→`submitting` | `release-manifest`, `platform-publication` |
| `liveops` | `live` | `performance-review`, `claim` |

Exactly one owner per state.

## Implementers

| Role | Works in | Note |
|---|---|---|
| `gameplay` | prototype, production | Mechanics, loop, systems, progression |
| `ui` | prototype, production | Interface, HUD, onboarding, platform UI constraints |
| `asset` | **design**, tech-plan, prototype, production | Also produces `asset-manifest` |
| `sdk` | prototype, production, release validating | Platform SDK, ads, analytics, cloud save |

`asset` contributing during design is deliberate: asset cost is an input to the scope
decision, and an input cannot be produced downstream of the decision it feeds.

## Human

`portfolio-owner` — approves all seven gates, and is the only party that may kill a concept,
authorize publication, or approve spend.

Named as a role rather than left as an implicit "somebody approves", because a gate with no
named approver is a gate that gets skipped.

---

## Three corrections to the original ten

**1. Owners and implementers were conflated.** See above.

**2. `liveops` was missing.** `sdk` integrates the analytics SDK; **nobody interpreted the
data**. The Factory's entire "learns from what it ships" premise had no owner, and an unowned
premise is a slogan. `liveops` owns `live`, runs the scheduled performance review, and feeds
claims back to the portfolio.

**3. Compliance and localization were assigned to nobody.** Yandex requires Russian, GameVui
requires Vietnamese, every portal wants store metadata — real deliverables with real cost,
discovered at submission time because no role owned them. Now explicitly `release`, with a
`localization` skill. No twelfth agent was added; the assignment was the missing part.

---

## Agent lifecycle

1. Receive inputs named on the stage entry in the machine file.
2. Read the stage `procedure`, the role charter, and the `x-wgf` block of each artifact
   schema.
3. Execute.
4. Produce outputs conforming to those schemas, with full `provenance` including hashed
   `inputs[]`.
5. **Stop.** Do not advance the lifecycle — transitions are commands and gates are human.

Step 5 is the one agents get wrong. An agent that transitions its own state has removed the
gate.

---

## Agent QA is not QA

Inside production the loop is implement → test → fix → repeat. That is the author checking
their own work. It is necessary and it is not sufficient.

> An agent saying **"ready"** is not the same event as QA saying **"approved."**

Independent QA runs in the release machine, against a built candidate, by a different role,
**with the authority to fail a build its author believes is finished**. Collapsing the two
removes the only external check on agent output — and an AI production pipeline with no
external check ships whatever it convinced itself was done.

---

## What agents may not decide

During production, implementation detail is the agent's. These are not, and change only
through an explicit process:

- product scope
- monetization
- platform strategy
- core gameplay
- architecture

```
Change request  →  Impact analysis  →  Approval (decision-record)  →  Development plan update
```

Without this, the development plan stops describing what is being built within about a day,
and then nothing approved at G3 means anything.

---

## Provider adapters

Roles are provider-independent. Adapters bind them to host mechanics:

| | Claude | Codex |
|---|---|---|
| Role surface | subagent, YAML frontmatter | role file referenced from `AGENTS.md` |
| Command surface | slash command | prompt file |
| Skill surface | `skills/<id>/SKILL.md` | `skills/<id>/SKILL.md` |
| Entry point | `.claude-plugin/plugin.json` | `AGENTS.md` |

Both are generated from `core/bindings/adapter-binding.yaml` by `scripts/gen-adapters.sh`,
which keeps their equivalence true rather than aspirational. Each carries a `CONFORMANCE.md`
mapping every declared surface to its file.

**An adapter file that restates a schema or a procedure is a bug.** The body is "read these
core paths, then follow them", plus a short block of host-specific execution notes.

---

## Commands map to transitions

```
scan → score → select[G1] → strategy[G2] → design → plan[G3] → scaffold
     → prototype → review[G4] → release[G5] → publish[G6] → live[G7]
```

Plus `status`, read-only.

The previous eight commands were named after stages and covered no discovery, evaluation,
approval, analytics or campaign. Naming them after the machine's **edges** is what keeps them
correct as the machine evolves.

---

## Asset pipeline

Asset work happens **inside** prototype and production, tracked as `asset-manifest` line-item
status. There is deliberately no asset-production stage: serializing art behind a gate would
put code behind art and wreck a 7-14 day schedule.

```
Asset request → search existing library → { procedural | AI-generated | purchased | commissioned }
              → compile → QA → runtime asset
```

`asset_manifest.complete` is half of the `content_complete` guard on production exit.

Prefer `library` and `procedural` at this scale; `commissioned` is rarely compatible with the
timebox. No `purchased` or `library` item is integrated without a recorded license — an
unlicensed asset in a published build is a real liability.

Both rules are data in `core/reference/asset-policy.yaml` — the formats each asset kind may
be, and which licenses may ship — and are enforced by the `assets` workflow step
(`scripts/wgf_assets`, see [assets-module.md](assets-module.md)): an asset whose license is
unknown or restricted, or that has no recorded origin, is never `production_ready`.

### 3D

```
Source → Blender → GLB/GLTF → Draco/Meshopt → KTX2 → Three.js runtime
```

Every step costs build complexity and load time, which is why `engine.type: threejs` requires
a written rationale in the tech plan.

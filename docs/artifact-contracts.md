# Artifact Contracts

## The contract is the schema

There is no separate `artifact-contracts/` tree. Producer, consumers, format, repository
path and gate usage live in an `x-wgf` block at the root of each schema:

```json
{
  "$id": "https://webgamefactory.dev/schemas/artifacts/game-design.schema.json",
  "x-wgf": {
    "id": "game-design",
    "format": "json",
    "template": "templates/gdd.md",
    "producer": "title:design",
    "consumers": ["title:tech-plan", "title:prototype", "title:production", "release:qa"],
    "repo_path": "workspace/titles/<title-id>/game-design.json",
    "rendered_to": "<game-repo>/docs/GDD.md",
    "required_for_gates": ["G3", "G4"]
  }
}
```

One file, so the contract and the schema cannot disagree. The previous structure kept them
in parallel trees that had already drifted — 8 workflow directories against 6 contract
directories, with `design` in one and `game-design` in the other — before any content
existed. Merging them removes the whole class of problem rather than asking people to be
careful.

## Every stage has an input, output, validation, next state and failure state

Those live on the stage entry in the machine file, not in a separate contract document:

```yaml
design:
  role: game-designer
  procedure: stages/design.md
  inputs:  [title-strategy, claim]
  outputs: [game-design, asset-manifest]
  exit_check:
    name: design_consistency
    rules: core/reference/design-consistency-rules.yaml
  transitions:
    - { event: plan,    to: tech-plan, guard: [design_consistent] }
    - { event: descope, to: design,    guard_negated: [design_consistent] }
    - { event: abandon, to: abandoned }
```

---

## The sixteen artifacts

| Artifact | Producer | Consumers | Gates |
|---|---|---|---|
| `claim` | market-scan, live | scoring, strategy, design | — |
| `opportunity` | market-scan | scoring, G1, concept, strategy | G1 |
| `research-report` | market-scan | scoring, G1, strategy | G1 |
| `evaluation` | scored | shortlisted, concept, strategy | G1 |
| `title-strategy` | strategy | design, tech-plan, prototype, review, production, live | G2, G4 |
| `game-design` | design | tech-plan, prototype, production, QA | G3, G4 |
| `asset-manifest` | design | tech-plan, prototype, production, QA, release | G3 |
| `tech-plan` | tech-plan | scaffolding, prototype, production, QA, release | G3 |
| `scaffold-record` | scaffolding | prototype, production, release draft | — |
| `prototype-report` | prototype | prototype-review, production | **G4** |
| `sdk-report` | prototype (updated in production) | prototype-review, QA, validating | — |
| `qa-report` | release QA | rc, production | G5 |
| `verification-report` | release QA (with `qa-report`) | rc, production | G5 |
| `release-manifest` | release draft | QA, rc, validating, submitting, live | G5, G6 |
| `platform-publication` | validating | submitting, partially-live, live | — |
| `performance-review` | live | live, production, market-scan | G7 |
| `decision-record` | every gate | audit, resume, portfolio learning | — |

**Reference types** (maintained, not stage-produced): `platform-profile`, `scoring-model`,
`dimension-vocabulary`.

**`game-design` 1.1.0** adds three optional blocks that carry the design down to what an
implementation agent builds from: `engine` (PixiJS for 2D, Three.js for 3D, with a
rationale — tech-plan still owns the binding choice), `features` (every feature tiered
`mvp` / `post-mvp` / `optional`, with acceptance criteria on the MVP; `scope.tiers` is derived
from it) and `build_spec` (mechanics, controls, player goals, progression, difficulty, game
states, screens, HUD, menus, tutorial, rewards, failure and retry, session flow, monetization
and platform-SDK touchpoints, asset and audio requirements, responsive behaviour, visual
identity). Ids inside `build_spec` cross-reference each other so that "buildable without
guessing" is checkable. 1.0.0 artifacts remain valid.

---

## Shared primitives

Three structures reused across many artifacts. Each replaces a stated intention with a
mechanism.

### `provenance` — on every artifact, no exceptions

```json
{
  "artifact_id": "wgf:game-design:neon-drift:20260903-01",
  "artifact_type": "game-design",
  "schema_version": "1.0.0",
  "produced_by": { "role": "game-designer", "actor": "ai" },
  "produced_at": "2026-09-03T14:00:00Z",
  "inputs": [
    { "artifact_id": "wgf:title-strategy:neon-drift:20260901-01",
      "artifact_type": "title-strategy",
      "content_hash": "sha256:1d90fe…" }
  ],
  "content_hash": "sha256:6a3e07…",
  "status": "final"
}
```

One struct supplying four things at once: **audit**, **staleness detection**, **resume**,
and **producer attribution**. The hashed `inputs[]` is what makes it detectable that a design
was derived from a market read that has since been superseded — the check that runs on
resume from `paused`.

### `claim` — the unit of knowledge

Append-only, tiered, and enforced by the schema rather than by convention:

- `observed` — **fails validation** without at least one cited source
- `derived` — must name its parent claims
- `hypothesis` — legitimate, but **capped at 0.6 confidence**

Changing a claim means writing a new one and setting `superseded_by`. Editing in place is
precisely how a hypothesis becomes a fact three weeks later with nobody noticing.

### `criteria-expression` — one expression type, four uses

```json
{ "left": "audio_input_latency_ms", "op": "gt", "right": 60 }
```

With `all_of` / `any_of` / `not` nesting. Serves **kill criteria, success criteria, scoring
vetoes and platform assertions**.

Deliberately dumb: no arithmetic, no functions, no interpolation. It is not a language and
must not become one. If a rule cannot be expressed here, write prose in the stage procedure
and have a human judge it.

---

## Evidence is computable

The requirement was "distinguish observed data, derived analysis, hypothesis and
recommendation, and do not let unsupported assumptions become facts."

Prose cannot enforce that. Four mechanisms do:

1. **Tier enum on every claim**, with validation rules per tier.
2. **`evidence_refs[]` on every scored dimension.** Empty forces `tier: hypothesis` — not a
   convention, a consequence.
3. **`evidence_coverage`** on every evaluation: the share of total weight carried by
   evidence-backed dimensions. A gate can require `>= 0.6`, so "well-evidenced" is a number.
4. **Append-only claims and evaluations**, so a belief that moved leaves a trace.

In a performance review the same discipline appears as four separate fields — `metrics`
(observed), `findings` (derived, each with a caveat), `hypotheses` (untested), `experiments`
(tested, with a success condition). Separate fields survive being summarized in a hurry;
prose guidance does not.

---

## Artifacts that were cut

| Proposed | Why not a contract |
|---|---|
| Market intelligence report | A *rendering* of claims for humans. Nothing downstream parses it, so it is a template, not a contract. |
| Competitor report | Same — a view over claims. |
| Game concept | The `concept` block inside `opportunity`. |
| Scope / session / monetization documents | Sections of `game-design`. Four files drift; one artifact with a recorded consistency result is atomic. |
| `task_breakdown.json` | `tech-plan.dev_plan.tasks`. |
| `concepts.json` | Superseded by `opportunity` + `evaluation`. |
| `metadata.json` | `release-manifest.store_metadata`. |
| Experiment / hypothesis / change plan | Fields on `performance-review`. |

The test applied: **if nothing downstream parses it, it is not a contract.** Rendering it for
humans is what `core/templates/` is for.

---

## Validating

```bash
npx --yes -p ajv-cli@5 -p ajv-formats@2 ajv validate \
  -s core/artifacts/<artifact>.schema.json \
  -r "core/artifacts/shared/*.schema.json" \
  -c ajv-formats --spec=draft2020 --strict=false \
  -d <instance>.json
```

`--strict=false` is required because `x-wgf` is a custom annotation keyword.

A complete worked example — claim through to a kill decision at G4, every file schema-valid
— is in `workspace/opportunities/opp-001/` and `workspace/titles/neon-drift/`.

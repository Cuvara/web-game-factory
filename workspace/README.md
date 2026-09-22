# Workspace — Factory instance data

This is where the factory's actual work lives: the claims it has gathered, the
opportunities it is considering, the titles it is building, and every gate decision it has
made.

## Why this exists as a third location

Three kinds of thing, three homes:

| | Holds | Where |
|---|---|---|
| `core/` | Methodology — states, contracts, roles | provider-independent, game-independent |
| `workspace/` | **Instance data** — what this factory has actually done | ← you are here |
| game repos | Game source code | created from `web-game-template` |

The backlog cannot live in `core/`: putting business data in the methodology would break
the rule that keeps core provider- and game-independent. It cannot live in a game
repository either, because opportunities exist long before any repository does — most are
rejected and never get one.

So it lives here, alongside core but strictly separate from it. **Nothing in `core/` may
reference a specific opportunity, title, or claim.**

## Layout

```
workspace/
  config/
    portfolio.yaml          local policy: WIP cap, default scoring model
    scoring/                local scoring model overrides (core ships the defaults)
  claims/
    <claim-id>.json         append-only; never edited, only superseded
  opportunities/
    <opportunity-id>/
      opportunity.json
      evaluations/          append-only; one per scoring run
      decisions/            G1 decision records
  titles/
    <title-id>/
      state.json            current lifecycle state + history
      title-strategy.json
      game-design.json
      asset-manifest.json
      tech-plan.json
      prototype-report.json
      decisions/            G2, G3, G4, G7 decision records
      reviews/              performance reviews once live
```

Release artifacts (`release-manifest`, `qa-report`, `platform-publication`) live in the
**game repository** under `release/<release-id>/`, not here — they are outputs of a build
and belong with the thing that was built.

## Rules

- **Claims are append-only.** Changing a claim means writing a new one and setting
  `superseded_by` on the old. Editing one in place is how a hypothesis silently becomes a
  fact.
- **Evaluations are append-only.** Re-scoring writes a new evaluation. Keeping the history
  is what lets the backlog be re-scored under a new model and the ranking diffs inspected.
- **Decision records are immutable.** They pin their subject by content hash, so "we
  approved the strategy" means a specific version of it.
- **Rejected and abandoned work is retained, not deleted.** A rejected opportunity with its
  evaluation, or an abandoned title with its prototype report, is evidence — and
  rediscovering the same dead end every quarter is a real cost.

## Validating an instance

```bash
npx --yes -p ajv-cli@5 -p ajv-formats@2 ajv validate \
  -s core/artifacts/opportunity.schema.json \
  -r "core/artifacts/shared/*.schema.json" \
  -c ajv-formats --spec=draft2020 --strict=false \
  -d workspace/opportunities/opp-001/opportunity.json
```

## The worked example

`opp-001` / `neon-drift` is a complete, schema-valid example running from a market claim
through to a kill decision at G4. It exists so the contracts can be read as data rather
than as prose, and so `npx ajv validate` has something real to run against.

It is **illustrative, not a real title** — including its ending. It is abandoned at G4 on a
breached kill criterion, because a factory whose example shows only the happy path teaches
the wrong lesson about what these gates are for.

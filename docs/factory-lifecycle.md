# Factory Lifecycle

Two independent state machines plus two nested ones. The authoritative definitions are the
YAML files in `core/lifecycle/`; this document explains them.

---

## Why two tiers

A game cannot be "in state MARKET_INTELLIGENCE". Market scanning is portfolio-scoped and
continuous, and the thing that carries state is the **opportunity** it produces, not a
title and not the factory.

So: a **portfolio** machine whose entity is an opportunity, and a **title** machine that
begins when an opportunity is promoted.

The connection back from live titles to discovery is a **data edge, not a control edge**.
A shipped game's metrics become claims that change what the next scan believes; nothing
transitions. This is why a live title can keep iterating indefinitely while new titles start
alongside it — a single circular chain cannot express that.

---

## Portfolio tier — entity: opportunity

```
market-scan (job, stateless)
    │ emits claim + opportunity + research-report
    ▼
discovered ──score──▶ scored ──rank──▶ shortlisted ──[G1]──▶ approved ──▶ promoted
                        │                   │                    │
                        │                   ├─defer──▶ parked    └─hold──▶ parked (WIP cap)
                        ├─rank(fail)──▶ rejected
                        └─ttl_expire──▶ stale ──rescore──▶ scored
```

| State | Meaning |
|---|---|
| `discovered` | Candidate exists, deduplicated, unjudged |
| `scored` | Has ≥1 evaluation under a named, versioned scoring model |
| `shortlisted` | Above threshold, evidence coverage met, no veto fired |
| `approved` | A human selected it (G1) |
| `promoted` | A title exists; portfolio work done *(terminal in tier)* |
| `parked` | Good, not now — capacity or timing |
| `stale` | Evidence older than the model's TTL; must not be promoted from here |
| `rejected` | Killed at portfolio level *(terminal)* |

Most opportunities should end in `rejected`. That is the machine working.

`approved → promoted` is guarded by `wip_available`. The WIP cap exists because the human is
the scarce resource, and a factory that queues more titles than its gates can clear
deadlocks.

---

## Title tier — entity: title

```
concept ──▶ strategy ──[G2]──▶ design ──▶ tech-plan ──[G3]──▶ scaffolding ──▶ prototype
   ──▶ prototype-review ──[G4]──▶ production ──▶ releasing ──▶ live
                │                                                │
                ├─iterate──▶ prototype                           ├─review.iterate──▶ production
                └─abandon──▶ abandoned                           ├─review.scale──[G7]──▶ live
                                                                 ├─review.hold──▶ live
                                                                 ├─review.sunset──▶ sunset
                                                                 └─hotfix──▶ releasing

any non-terminal ──pause──▶ paused ──resume──▶ previous | nearest upstream producer
terminals: abandoned, sunset
```

| State | Kind | Owner |
|---|---|---|
| `concept` | automatic | analysis |
| `strategy` | AI-assisted | game-designer |
| `design` | AI-assisted | game-designer |
| `tech-plan` | AI-assisted | architect |
| `scaffolding` | automatic | release |
| `prototype` | AI-assisted | gameplay |
| `prototype-review` | **human** | portfolio-owner |
| `production` | AI-assisted | gameplay |
| `releasing` | automatic | release |
| `live` | AI-assisted | liveops |
| `paused` / `abandoned` / `sunset` | — | — |

### Three design decisions worth knowing

**`strategy` survives as its own state** because it is where **kill criteria are authored**.
Criteria written at review time get written to justify the decision already made. Writing
them in advance, under a gate, while the idea is cheap, is what makes `abandon` real.

**`design` has no gate of its own.** Design and tech-plan approve together at G3. Splitting
them adds a gate to a cycle that already has too many, and approving a design whose plan does
not fit the timebox decides nothing.

**`paused` does not simply return.** If the title's inputs are no longer fresh — an upstream
artifact was superseded while it sat — it resumes at the **nearest upstream producing state**.
Without this a paused title silently ships a game built on a dead market read.

### Stages that are guards, not states

- **CI** — `ci_green(sha)` is checked on several transitions; `verify_suite_green(sha)` on
  exactly one. CI is continuous throughout production, not a step after QA.
- **Content complete** — `content_manifest.complete && asset_manifest.complete` on
  production exit. A state meaning only "two booleans are true" adds a transition and no
  information.
- **Vertical slice** — at 7-14 days the prototype *is* the vertical slice, so the bar at
  `prototype-review` is raised rather than a state being added.
- **Engine selection** — inside `tech-plan`, because `engine.type` is a repository-creation
  parameter and the ordering tech-plan → repo creation is load-bearing.

---

## Release — nested, one per shipment

```
draft ──▶ qa ──▶ rc ──[G5]──▶ approved ──[G6]──▶ validating ──▶ submitting ──▶ live
   │        │                                          │              │
   │        └─fail──▶ title:production                 └─fail──▶ title:production
   │                                                                  └─▶ partially-live
terminals: live, rolled-back, cancelled
```

Instances are `r1`, `r2`, … A title returns here for every shipment including hotfixes.

Which platforms are **required** is per-release policy, not a title property: `r1` may ship
Yandex-only and `r2` may add CrazyGames.

The manifest is **frozen and immutable at `rc`**. Any correction produces a new release.
That is what makes rollback an operation — re-publishing a known-good manifest — rather than
a rebuild under pressure.

---

## Platform publication — nested leaf, one per (release × platform)

```
pending ──▶ packaged ──▶ validated ──▶ submitted ──▶ in-review ──▶ live
                 │                                        └──▶ rejected
                 └──▶ validation-failed                          │
                                                                 ▼
                                             emits a compliance finding
                                             and versions the platform profile
```

Publication is **not atomic**: portals moderate independently, and Yandex can reject what
CrazyGames approved. The release computes a quorum from these records.

`submitted` and `in-review` advance by a human checklist plus a status file. No portal APIs
are integrated — the machine's value here is structure and learning, not automation.

**The `rejected` edge is the most valuable one in the system.** A rejection must produce a
compliance finding that updates the platform profile — a new assertion, a
`common_rejections` entry, or a corrected requirement — and bump its version. A rejection
that only sets a status field teaches the factory nothing, and the next title hits the same
wall.

---

## Gates

| ID | Gate | Irreversible | Auto-approve (recommended window) |
|---|---|---|---|
| G1 | Opportunity selection | no | 72h |
| G2 | Strategy approval | no | 48h |
| G3 | Design + development plan | no | 48h |
| G4 | **Prototype review** | **yes — kill** | **never** |
| G5 | Release approval | no | 24h |
| G6 | **Publish authorization** | **yes — public** | **never** |
| G7 | **Campaign spend** | **yes — money** | **never** |

Definitions, required artifacts, predicates and what each presenter must show:
`core/lifecycle/gates.yaml`.

Gates are **data**, so supervised and semi-autonomous operation differ by configuration
rather than by code. The three irreversible gates cannot be configured to auto-approve —
`decision-record.schema.json` rejects a non-human decision on them.

The windows above are `gates.yaml`'s recommendation (`auto_approve_after`). An installation
turns timeout approval on per gate in `workspace/config/factory.yaml`:

```yaml
factory:
  checkpoints:
    timeout_auto_approve: {G2: 48h, G3: 48h}
```

A run snapshots these windows when it starts. A reversible gate listed there that has waited
its window approves itself on the next `wgf resume` of the run, recorded like a person's
decision (`decided_by: automation`, `mode: timeout`); `wgf status` and `wgf runs --waiting`
only report that a gate is eligible. A run is refused at start if the list names an
irreversible gate or one `gates.yaml` does not define. Redoing the work a gate is about
restarts its wait. See [workflow-engine.md §9](workflow-engine.md#9-human-checkpoints).

### Gates inside the `new-game` workflow

The workflow (`core/workflows/new-game.workflow.yaml`) holds three of them as
`human-checkpoint` steps, each decided on its gate's `required_artifacts` and waiting for
input — asking nobody — until the run holds them:

| Step | Gate | After → before | Decided on | Choices |
|---|---|---|---|---|
| `strategy-review` | G2 | strategy → design | `title-strategy` | approve, reject |
| `tech-plan-review` | G3 | tech-plan → init | `game-design`, `tech-plan` | approve, reject |
| `prototype-review` | G4 | verify (PASS) → release | `qa-report`, `verification-report`, `prototype-report` | pass, iterate, kill |

G4 judges the *verified* prototype: it runs only after verification passes, and a
verification that runs again after a pass makes G4 ask again. `pass` continues to release;
`iterate` sends the work back to develop and ends at G4 again; `kill` — the machine's
`abandon` — ends the run: the decision is recorded (`DECISION_RECORDED`, and a
`decision-record` with `decision: abandon` — see below), the run is
`COMPLETED` with `exit.route: kill`, `wgf status` says `Ended: kill at G4`, and nothing in
the run can start again. Release is impossible until G4 passes. Only a person decides G4:
a decision made from inside a step's process tree is `automation`, and is refused.

---

## Every gate produces an artifact

A `decision-record` pins its subject by **content hash**, names the decider and the mode
(`human` or `auto-approved`), and carries a rationale.

This matters most for resumption: an agent picking work up three days later must be able to
tell approved from skipped from never-reached. A gate that produces no artifact is neither
auditable nor resumable.

### Where each record comes from

- **Decided by hand** (`wgf-state.py --advance ... --decision-record <path>`): a person
  writes the record into `workspace/titles/<id>/decisions/` and `wgf-state.py` refuses the
  gated edge without it.
- **Decided in a workflow run**: every checkpoint that names a gate declares
  `outputs: [decision-record]` (`check-integrity.py` refuses one that does not, and refuses a
  step that outputs one without naming a gate — the schema's `x-wgf.producer` is `gate`, not
  a stage). The checkpoint emits the record with **every decided outcome** — a person's
  choice, an installation's auto-approval, a timeout approval; the continuing ones
  (`approve`, `pass`, `iterate`) and the stopping ones (`reject`, `kill`) alike — and none
  while it waits. It is stored in the run like any artifact
  (`artifacts/decision-record-<step-id>/v<n>.json`, one version per decided visit), checked
  against the schema, and its `provenance.inputs` and `subject` pin exactly the inputs the
  checkpoint consumed — the gate's `required_artifacts` — by the hashes the engine recorded.

The workflow's words map onto the schema's in one table
(`scripts/wgflib/workflow/decisions.py`):

| Workflow choice | `decision` | Machine event | e.g. `transition` |
|---|---|---|---|
| `approve` | `approved` | `approve` | G2 `strategy -> design`, G3 `tech-plan -> scaffolding` |
| `reject` | `rejected` | `reject` | G2 `strategy -> abandoned`, G3 `tech-plan -> design` |
| `pass` | `pass` | `pass` | G4 `prototype-review -> production` |
| `iterate` | `iterate` | `iterate` | G4 `prototype-review -> prototype` |
| `kill` | `abandon` | `abandon` | G4 `prototype-review -> abandoned` |

`machine` and the source state come from the gate in `gates.yaml` (`machine`,
`on_transition`); the target is the machine's own edge on that event through that gate.
`decided_by.role` is the gate's first `approvers` entry (`portfolio-owner`);
`decided_by.mode` is `human` only for a decision recorded as `human` — `automation`, an
auto-approval and a timeout are `auto-approved`, and the identifier says which.
`decided_at` (and `provenance.produced_at`) is the engine's clock when the decision was
recorded; the rationale is the decision's `--note`, or a sentence saying none was given.
A choice with no meaning in the table fails the checkpoint rather than pass it unrecorded.

### The lifecycle bridge (off by default)

The run's records stay in the run store unless the installation turns the bridge on:

```yaml
factory:
  lifecycle:
    sync: true                       # default false
    # titles_directory: workspace/titles
```

A run snapshots `sync` into its params at start (`lifecycle_sync`); a resume refuses a
`state.json` that adds or drops it. For a run whose title (its `--project` id, else the
title the record names) already has `workspace/titles/<id>/state.json`, every record the
run persists is then

1. **appended** to the title's `decisions/` as a new file,
   `<gate>-<yyyymmdd>T<hhmmssmmm>Z-<nn>.json` — never over an existing one; and
2. used to **move the cursor** along the edge it authorizes, by `wgf-state.py`'s own code
   (`choose_transition`, `check_guards`, `check_decision_record`, `advance`): every guard
   must be GREEN, G4 needs `mode: human`, a stale subject is refused, a terminal target
   takes the rationale as its outcome note.

Guards read the run's newest artifact of each type the run holds (what the gate was decided
on), the title's own files otherwise. The bridge moves only gate edges, only from the edge's
source state — it never walks `plan` or `submit_review`, which stay `wgf-state.py`'s — never
creates a title, and never syncs a `--mock` run. A refused move (a RED or UNKNOWN guard, a
cursor elsewhere) is a `STEP_LOG` warning on the run and changes nothing about the run's
outcome: the workflow decided, and the lifecycle says why it did not follow.

### Guards that read a run's evidence

`ci_green`, `verify_suite_green` and `playable_build` are answered in the game repository,
so from the Factory side they are UNKNOWN — unless the guard context carries a run's
evidence (`wgflib.guards.RunEvidence`: the newest qa-report and verification-report of a
run, found in the run store by title id, newest run first; the bridge passes its own run's).
Then `verify_suite_green` is GREEN only for a qa-report `pass` whose evidence, and the
verification-report's, is `PASS`; RED for a `fail` or a verification `FAIL`; UNKNOWN for
`PASS_MOCK` (observed only against a stand-in), an unrecorded evidence status, or a
`BLOCKED` verification. `ci_green` reads the qa-report's lint/typecheck/unit/integration
suites. `playable_build` needs a `built` bundle and every required gameplay check `PASS` on
`PASS` evidence. A mock run's reports answer nothing.

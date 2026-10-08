# Knowledge enforcement: lessons as rules

The Factory learns from the games it builds. A lesson is a defect a person or a gate found,
stated so it is true of any game: the root cause in the Factory, not the game's symptom.
This document describes how a lesson becomes a **rule** - with a category, a scope, an
enforcement level and a lifecycle - and how the rules that apply to one run are resolved.

It is not a second quality system. The rules live in the registry that already existed
(`core/reference/lessons.yaml`), their levels are derived from the check tiers that already
existed (`core/reference/check-tiers.yaml`), and every rule is held by checks the gates
already run. What this adds is data on the lessons, and a resolver from a run's facets to the
rules that apply to it.

| Piece | Where |
|---|---|
| Knowledge model (rules) | `core/reference/lessons.yaml` 2.0.0 |
| Enforcement vocabulary, where each result is read | `core/reference/check-tiers.yaml` 1.1.0 (`tiers`, `status_at`) |
| Instance evidence (which game, run, fix, rerun) | `workspace/lessons/evidence.yaml` 2.0.0 |
| Model, integrity rules, exceptions | `scripts/wgf_knowledge/model.py` |
| Applicability resolver | `scripts/wgf_knowledge/resolve.py` |
| Versions a run is judged by | `scripts/wgf_knowledge/versions.py` |
| Registry: tiers, `status_at` reader, integrity | `scripts/wgf_quality/registry.py` |
| A run's contract | `core/artifacts/knowledge-contract.schema.json` |
| A person's exception | `core/artifacts/shared/knowledge-exception.schema.json` |
| Command line | `wgf knowledge` (`scripts/wgf_knowledge/cli.py`, `scripts/wgf-knowledge.py`) |

## The knowledge model

Each lesson in `lessons.yaml` carries:

| Field | Meaning |
|---|---|
| `id` | Stable. Never reused, never deleted - a lesson that no longer holds is deprecated. |
| `title`, `lesson` | One line; the generalized lesson. |
| `category` | The quality-floor scorecard line it belongs to (`quality-floor.yaml` `scorecard`), or `process`. Compliance counts per scorecard line, so there is no second taxonomy. A lesson on a render-specific line (`art_2d`, `art_3d`) is scoped to that render. |
| `problem` | The generic symptom a player or a person saw. |
| `root_cause` | Why the Factory let it through: which gate, brief or step did not hold it. |
| `scope` | `global`, or `{families, render, platforms, tiers}` (below). |
| `status` | Coverage: `enforced`, `partial`, `gap`, `process`. Orthogonal to lifecycle. |
| `lifecycle` | `candidate`, `active`, `validated`, `deprecated`. |
| `introduced` / `validated` | `{version, date}`: the Factory release and date. |
| `checks` | Check ids of `check-tiers.yaml` that hold it. |
| `tests` | `{catches, passes, generalizes}`: the check fails the defect; it passes the fixed or accepted build; it catches the defect in a game other than the one it was learned from. |
| `gap`, `held_by` | What is not held yet; where a process lesson is written down. |
| `level` | Optional, and only to declare a level **stronger** than the derived one. |

The source game, run, issue, reviewer and the evidence legs live in
`workspace/lessons/evidence.yaml`, keyed by lesson id: `source` (`run`, `review`,
`benchmark`, `research-principle`), `discovered`, `fixed`, `verified` (the rerun leg: the
check passed on the game that raised it, after the fix) and `regressions`. Core names no
game; check-integrity refuses a lesson whose text names a game the evidence lists.

## Enforcement levels are derived, never restated

| Level | Derived when | In a run |
|---|---|---|
| **blocking** | enforced or partial, every check `hard` | Must be satisfied by the build's current evidence, or excepted by a person. |
| **required** | enforced or partial, every check hard or quality, at least one `quality` | The same. Its bar is calibrated and moves only by a new version of its file. |
| **recommended** | any check `advisory` | Reported; a failure is a finding. Never blocks. |
| **experimental** | `status: gap`, or `lifecycle: candidate` | Listed as guidance with its gap. Never blocks. |
| (process) | `status: process` | Never in a run's contract. |

A lesson may declare a stronger `level` than its checks derive, never a weaker one, and never
the same one (a restatement). A blocking or required declaration on an advisory check fails:
the check's tier moves first, by a new version of its source file.

`wgf knowledge show` prints the derived level of every lesson. As shipped:

| Level | Lessons |
|---|---|
| blocking (6) | L3, L5, L10, L12, L15, L22 |
| required (14) | L1, L2, L4, L7, L11, L13, L14, L20, L23, L24, L25, L26, L27, L28 |
| experimental (6) | L8, L9, L16, L17, L18, L21 |
| process (2) | L6, L19 |
| recommended (0) | no lesson names an advisory check |

## Scope and applicability

A scope is `global` or a mapping:

| Key | Vocabulary | Facet of the run |
|---|---|---|
| `families` | `core/reference/genre-models.yaml` `families` | `game-design.genre.family` |
| `render` | `2d`, `3d` | `game-design.engine.dimension` |
| `platforms` | `core/reference/platforms/<id>.yaml` | `title-strategy.platform_set[].id` |
| `tiers` | `core/reference/quality-benchmark.yaml` `tiers` | the run's quality tier |
| `profiles`, `archetypes` | reserved: refused until the complexity profile and archetype registry exists | |

Keys are AND-ed and values OR-ed; a `platforms` scope matches when any targeted platform is
listed. **A facet the run has not determined never makes a rule inapplicable** - the rule
applies, and its `why_applicable` says the facet was undetermined. Narrow scope is the risky
direction (a wrong one silently drops a rule from runs), so it is always the conservative
choice that wins.

`resolve.resolve(lessons, checks, tiers, facets, workflow, exceptions, now, versions)` is
pure. For every rule that applies it returns the level, category, checks (tier, producer,
the workflow steps that produce it), tests and why it applies; for every rule that does not,
the facet that excluded it - or that it is a process or deprecated lesson. An agent never
decides scope. It also returns:

- `required_validators`: the workflow steps that produce the applicable blocking and required
  rules' checks, and `missing_validators`: a check no step produces. A run cannot make its
  contract while one is missing (the contract schema holds `missing_validators` empty);
- `regression_suite`: every test of the applicable rules;
- `constraints`: the genre family's contract and each platform's profile, by version;
- `exceptions` honoured, and `exceptions_refused` with why;
- `counts` by level.

As shipped, every lesson is global except L15 (`render: [3d]`: the model-review checks judge
GLB models) and L9 (`tiers: [release, premium]`: a release-quality bar, experimental).

## Where a check's result is read: `status_at`

`check-tiers.yaml` 1.1.0 says, per source, where its checks' results are in the producer's
report, so a rule can be shown to have run and passed on a build. A source without its own
`status_at` reads the file's top-level one (`{list: checks, id: id, status: status}` -
playability, play-realism, production-quality, content-sufficiency). The irregular ones:

| Source | Locator |
|---|---|
| quality-floor | `criteria[].id` / `status` of the quality-report |
| quality-dimension | `dimensions[]`; `BELOW_FLOOR` is FAIL |
| visual-qa-blocker | a blocker finding under the blocker's id is FAIL; none in a report that passed is PASS |
| visual-qa-score | `scores` (MEASURED, with the value; the bar is the rubric's) |
| gate-gaming | review `blockers[]` named `gate-gaming-<pattern>-<n>` are FAIL; none in an approved review is PASS |
| design-consistency | `consistency.rule_results[]`, `breached` true is FAIL |
| browser-qa, browser-qa-run | verification-report `checks[]`, the check id before `:<viewport>` |
| model-review | asset-manifest `items[].quality.checks[]` |

A report with no entry for a check reads it as UNMEASURED - never a pass.
`registry.check_status(tiers, "<source>:<id>", report)` reads one check;
check-integrity holds that every locator's path exists in the producer's schema, and
`test_regression_registry.StatusAt` resolves a failing and a passing result for every source
on a schema-valid report of its producer.

## Lifecycle

```
candidate    proposed; experimental; nothing enforces it yet
   | a check holds it (check-tiers) and a test catches it        -> active
   | passes + generalizes tests, and the evidence's verified leg  -> validated
   | superseded or wrong                                          -> deprecated (kept)
```

Integrity holds each transition's requirements: a gap lesson is a candidate (or deprecated);
an active one is enforced or partial with `tests.catches`; a validated one is enforced with
all three test kinds, a `validated` stamp and the evidence's `verified` leg; a deprecated one
names `superseded_by` or a `reason`. A candidate never edits `lessons.yaml` by itself - a
person promotes it, with its check and tests, in a pull request.

## Exceptions: a person's, explicit and expiring

A blocking or required rule that applies to a run must be satisfied, or excepted. An
exception (`core/artifacts/shared/knowledge-exception.schema.json`) is:

```
{rule_id, reason (at least 20 characters), scope: {platforms?, checks?, viewports?},
 approved_by: {identifier, mode: human | automation}, created_at, expires_at}
```

The policy is data in `lessons.yaml` `exceptions`:

```yaml
exceptions:
  levels: [blocking, required]     # recommended and experimental never block
  approvers:
    blocking: [human]              # never automation - check-integrity refuses it
    required: [human]              # the data switch: a person only, as shipped
  max_days: 30
```

`model.exception_problems(exception, lessons, checks, now)` refuses an exception for an
unknown rule or one that never blocks, with no or too short a reason, approved by a mode the
policy does not accept for the rule's level (automation, for every level as shipped, and for
a blocking rule always - whatever the data says), with no expiry or one beyond `max_days`,
and - at `now` - one that has expired. An exception never makes a rule satisfied: it is
reported EXCEPTED and listed wherever the rule's compliance is. It is run-scoped; no
configuration grants one.

## Versions and versioning

`versions.knowledge()` is the seed a run records at start - `lessons@<v>` and
`check-tiers@<v>` - and refuses a file that is missing, unreadable, versionless or not shaped
as knowledge. `versions.collect()` is a contract's `versions` block: the Factory's version
and commit, lessons and check-tiers with their sha256, the quality policy, benchmark, floor
and genre models versions, the workflow, and each targeted platform's profile. Pass a run's
pinned reader to record what the run pinned.

Adding a lesson, a stricter scope or a stricter level is a minor version of `lessons.yaml`.
A weaker level or a narrower scope of an existing lesson is never an edit in place: a new
lesson supersedes it. check-integrity compares the file with its version at
`WGF_KNOWLEDGE_BASE` (default `origin/main`) and fails a lesson deleted, weakened or narrowed
in place; a ref git cannot show is noted and skipped (CI on a full checkout holds it).

## Command line

```bash
wgf knowledge validate [--runtime] [--json]   # the knowledge model and the registry
wgf knowledge show [ID] [--json]              # every rule with its derived level; one in full
wgf knowledge resolve --family arcade --render 2d --platform yandex --tier release [--json]
wgf knowledge contract <run-id> [--store DIR] # the run's knowledge-contract (or a dry one)
wgf knowledge table --families arcade,racing --render 2d,3d --tiers mvp,release
                                              # the benchmark approval table, dry
```

Exit status: 0 clean, 1 problems (validate) or a missing validator (resolve, table),
2 the command could not run. `contract` prints the run's recorded contract; for a run that has
none (started before the knowledge step), it resolves one now from the run's game-design,
title-strategy, quality tier and pinned knowledge, marked `recorded: false`, and writes
nothing.

## What is not here yet

This is unit K1 of the learning-enforcement design. Recording the knowledge versions at run
start, pinning `lessons.yaml` and `check-tiers.yaml`, the `knowledge` step that writes the
contract and blocks a run that cannot make one, and the `wgf resume --except` operator act
are K2. Compliance per rule in the quality-report (SATISFIED, FAILED, UNMEASURED, EXCEPTED,
DEFERRED, NOT_APPLICABLE), triage reading the run's contract, and briefs carrying the
blocking and required rules are K3. Ingestion of lesson candidates, promotion drafts, the
regression firewall (`test-core` KNOWLEDGE) and the plugin surfaces are K4.

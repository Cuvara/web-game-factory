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
applies, and its `why_applicable` says the facet was undetermined. The same holds for a
scope key no facet answers, and for a lesson with no scope at all (a run that pinned a
1.x file). Facets are normalised before they are matched (`resolve.facets`): stripped and
lower-cased (`3D` is `3d`), a single platform given as a string is one platform; a value
that is not a word, or a render other than 2d or 3d, is refused. Narrow scope is the risky
direction (a wrong one silently drops a rule from runs), so it is always the conservative
choice that wins.

`resolve.resolve(lessons, checks, tiers, facets, workflow, exceptions, now, versions)` is
pure. For every rule that applies it returns the level, category, checks (tier, producer,
the workflow steps that produce it), tests and why it applies; for every rule that does not,
the facet that excluded it - or that it is a process lesson or one superseded by a
successor. An agent never decides scope. It also returns:

- `required_validators`: the workflow steps that produce the applicable blocking and required
  rules' checks, and `missing_validators`: a check no step produces, or a rule whose level
  cannot be derived (a check no source of check-tiers classifies) - never a rule that
  silently does not apply. A run cannot make its contract while one is missing (the contract
  schema holds `missing_validators` empty);
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
| visual-qa-blocker | `attribute: false`: the judge names its findings freely (`flat-primitive-entities`, `baseline-regression-<frame>`), so a blocker finding cannot be told to be one rubric blocker; any blocker finding leaves every rubric blocker UNMEASURED, and a judged report (PASS or FAIL) with none passed them all |
| visual-qa-score | `scores` (MEASURED, with the value; the bar is the rubric's) |
| gate-gaming | review `blockers[]` named `gate-gaming-<pattern>-<n>` are FAIL; none in an approved review is PASS |
| design-consistency | `consistency.rule_results[]`, `breached` true is FAIL |
| browser-qa, browser-qa-run | verification-report `checks[]`, the check id before `:<viewport>` |
| model-review | asset-manifest `items[].quality.checks[]` |

A report with no entry for a check reads it as UNMEASURED - never a pass. Since
check-tiers 1.2.0 a source whose producer reports a check only for a build it concerns says
so with `not_reported` groups, and an absence is NOT_APPLICABLE only with the evidence a
group names - never on the absence alone (a group needs `verdict` or `ran`):

| Source | Checks | NOT_APPLICABLE when (all of) |
|---|---|---|
| play-realism | physics.* | the report finished (PASS/FAIL), realism ran (a `runtime.*` entry), and the run is 3D - or 2D and the design's `build_spec.assets` declare no `projectile` (the bodies the simulation moves) |
| play-realism | naive.drift, naive.alignment | finished, naive play ran (a `naive.*` entry), the run is 2D |
| play-realism | level.* | finished, and the content-sufficiency-report read the content data file (`content.data_present` PASS) |
| content-sufficiency | content.regression | finished, ran, and the design carries no `existing_content` (no adopted game) |
| playability | depth.stall | finished, and the ramp ran (`depth.ramp`) |
| quality-floor | every criterion | the report scored its floor (`floor.*`): a criterion it does not carry is not the build's contract |

Otherwise - a BLOCKED report, a family that never ran, a 2D game that moves a body but
reports no physics, layouts never read - the absence is UNMEASURED. `not_applicable: {field,
values}` reads an entry whose field holds one of the values as NOT_APPLICABLE (a clear rate
with no accepted build to fall from). `covered: {field, values}` reads as PASS (`covered`) a
WARNING entry its producer made advisory because another check measured what it stands for:
level.clearance whose failing units all had their clear rate measured
(`realism.gate_clearance`, `measured.gate` advisory or clear-rate-failed) - naive.clear_rate is
read on its own, so a failing one still fails the rule.
`registry.check_status(tiers, "<source>:<id>", report, facts)` reads one check (`facts`:
the run's render and the run's other reports, for the `not_reported` conditions);
check-integrity holds that every locator's path exists in the producer's schema.
`test_regression_registry` resolves a failing and a passing result for every source on a
schema-valid report of its producer, reads the irregular ones on what the producers actually
write (browser QA's judge on a validation game's records, the realism judge on the regressed
2D head, the review's gate-gaming pre-check, the design step's consistency evaluator, the
model checks on a real GLB, a real visual judge's verdict), and holds that the quality gate's
reader (`wgf_quality.scoring`) and this one agree on every check of real producer reports
(`ParityWithScoring`): one report, one reading.

## Compliance: the build held to its contract

The quality gate holds the build to the run's knowledge-contract (unit K3,
`scripts/wgf_quality/compliance.py`). It is a section of the quality-report (1.3.0
`compliance`), not a second quality system: every applicable rule gets one status from the
checks that hold it, read on this build's **current** reports through
`registry.check_status` - the one reader of a producer's check results for rules - and each
check cites the producer's artifact id, content hash and the commit it describes. A rule is
satisfied by evidence, never by a report saying something was fixed.

| Status | When |
|---|---|
| SATISFIED | every check passed, or does not concern this build |
| FAILED | a check failed |
| UNMEASURED | a check has no result on this build: no report, no entry, SKIPPED, BLOCKED, a WARNING (reported without being held), a measured value with no verdict, or stale evidence - never a pass |
| DEFERRED | a check's producer measures it later (the store listing) |
| NOT_APPLICABLE | every check is one its producer reports only for builds it concerns and a `not_reported` group's evidence holds, or one it says does not concern this build (`not_applicable`) |
| EXCEPTED | FAILED or UNMEASURED, and a person's exception that holds at the gate's clock covers every check that is not passing (its `checks` and `viewports` scope); its measured status is kept beside it |
| NOT_ENFORCED | an experimental rule nothing holds yet: its gap, as guidance |

A **blocking or required** rule FAILED or UNMEASURED (and not excepted) makes the section
`RELEASE_BLOCKED`. A recommended or experimental rule not satisfied is a warning, never a
block. Each exception offered - the contract's, and any a person granted the run since
(`KNOWLEDGE_EXCEPTION_GRANTED` events) - is listed with its status: `honoured`, `expired`
(past its expiry the rule is held again) or `refused` (automation's, an unverified event, a
rule that never blocks, a scope the run or the rule does not have, a platform scope covering
only some of the run's targets - one build ships to all of them).

The event a person's `wgf resume <run> --except ...` records has the budget raise's shape
(`wgflib/budget.py`), and is followed by the engine's `WORKFLOW_RESUMED` with the same
`resume_nonce`:

```json
{"event": "KNOWLEDGE_EXCEPTION_GRANTED",
 "data": {"decided_by": "<who ran the resume>", "decided_at": "<ISO 8601>",
          "resume_nonce": "<the resume's nonce>",
          "exception": {"rule_id": "L26", "reason": "...", "scope": {},
                        "approved_by": {"identifier": "<the same as decided_by>",
                                        "mode": "human"},
                        "created_at": "<ISO 8601>", "expires_at": "<ISO 8601>"}}}
```

The record is never trusted about its approver: an event with no `decided_by`, decided by
`automation`, whose `decided_by` is not the record's `approved_by.identifier`, or not
corroborated by its resume, is `unverified` and refused.

**Enforcing or advisory.** For a run that made its contract, the section is *enforcing*
when anything says the run is a release - the tier its design states, the tier its contract
was made for, or its quality class (`params.quality`, the snapshot) - so a design stating
mvp never softens a release-class run; a development decision there becomes `not-release`,
and release refuses a development quality-report from a release-class run
(`quality-development-in-release-run`). Enforcing, `RELEASE_BLOCKED` makes the release decision `not-release` (the rule
ids as its reasons) and a passing verdict `FAIL`, routed back by the producers of what
failed (`asset-manifest` to assets, `game-design` to design-gap, the rest develop; triage
routes the producers' own findings). It is *advisory* - shown, changing nothing - for a
development build (tier mvp and a development-class run: never a release) and for a run
started before the
knowledge model, whose contract is resolved now from the knowledge it pinned
(`contract.retroactive`). A run that recorded its knowledge at start (`params.quality.knowledge`)
but whose contract does not reach the gate is never skipped: `contract_missing`, enforcing,
RELEASE_BLOCKED.

The section also records the versions the rules came from (the contract's), the counts by
level, the rules' regression suite (the Factory's tests, run by its CI, never in a game
run), the checks run, passed, failed and unmeasured, the lessons applied and the run's new
lesson candidates. G4 prints its summary (`wgflib.gate_evidence`), release refuses a build
whose compliance holds the release (`knowledge-not-satisfied`) or was judged against an older
contract (`stale-knowledge-compliance`) and ships the contract and the compliance under
`release/<release-id>/` (`knowledge-contract.json`, `knowledge-compliance.json`, and
`knowledge-compliance.md` for a person). `wgf knowledge report <run> [--md|--json]` renders
it at the end of a run.

**Triage** guards a finding from the run's contract - only its applicable rules, each with
its `level` - and holds, never routes, a finding whose rule a person excepted for the run
(`excepted`); the producer's verdict is unchanged. **Briefs**: develop and specialist visits
carry the contract's blocking and required rules (`brief.json` `knowledge`, and a section of
the brief), the design agent a provisional list resolved over what is known before the
design.

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

Deprecation never takes a rule out of a run silently. A lesson superseded by a successor is
carried by the successor, which must be at least as strong, hold every check, and cover the
scope (the weakening check follows the chain). A lesson retired with only a `reason` stays in
every run it applied to as `recommended`: listed, reported, with the reason in its
`why_applicable` - never blocking - and the weakening check reports the drop. For a rule
that was blocking or required that drop is an integrity error in CI (`WGF_KNOWLEDGE_STRICT=1`):
reason-only deprecation does not retire a strong rule. Only an equally strong successor, or a
person accepting the failing check in review, retires it.

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

`max_days` is at most 90 (`model.MAX_EXCEPTION_DAYS`).

`model.exception_problems(exception, lessons, checks, now, run_facets, vocabulary)` is judged
at `now`, which is required - without it no exception holds. It refuses:

- an unknown rule, or one whose run level cannot be excepted;
- no reason, one under 20 characters, one with fewer than 4 distinct words of three letters
  or more, or one that repeats a word for more than half of it (padding is not a reason);
- an approver mode the policy does not accept for the rule's level (automation, for every
  level as shipped, and for a blocking rule always - whatever the data says);
- created after `now`, expiring before it was created, beyond `max_days`, or expired;
- a scope outside the rule or the run: checks the rule does not name, platforms the run does
  not target or the rule is not scoped to, platforms and viewports the Factory does not know
  (without the vocabulary a platform or viewport scope is refused).

**The record alone is never trusted about who approved it.** A record can say
`mode: human` for a bot. The operator act that grants an exception (`wgf resume <run>
--except`, K2) stamps `approved_by.mode` itself from who runs the command - `automation`
inside a Factory step's process tree (`default_decider`) - and the run keeps it as its own
event; a record written anywhere else is not an exception. An exception never makes a rule
satisfied: it is reported EXCEPTED and listed wherever the rule's compliance is. It is
run-scoped; no configuration grants one.

## Versions and versioning

`versions.knowledge()` is the seed a run records at start - `lessons@<v>` and
`check-tiers@<v>` - and refuses a file that is missing, unreadable, versionless or not shaped
as knowledge. `versions.collect()` is a contract's `versions` block: the Factory's version
and commit, lessons and check-tiers with their sha256, the quality policy, benchmark, floor
and genre models versions, the workflow, and each targeted platform's profile - at the
version the title-strategy pinned (`profile_version`, `resolve.platform_pins`), else through
the reader. Pass a run's pinned reader to record what the run pinned.

Adding a lesson, a stricter scope or a stricter level is a minor version of `lessons.yaml`.
A weaker rule is never an edit in place: a new lesson supersedes it. check-integrity
compares the knowledge with the knowledge at a base commit, **each side judged by its own
check tiers** (the base's `check-tiers.yaml`, classified against the files it enumerates as
they were at that commit), and fails:

- a lesson deleted;
- a rule held weaker in a run - its level derived lower (a check's tier demoted, a
  lifecycle back to candidate, a status turned process or gap), or a successor weaker than
  the lesson it supersedes;
- a check removed from a rule, or a check whose tier was demoted;
- a scope narrowed (or a successor's narrower);
- the exception policy loosened (a level made exceptable, an approver mode added, the window
  widened).

The base is the merge base of `WGF_KNOWLEDGE_BASE` (default `origin/main`) and HEAD - a pull
request's base, a push's previous tip - and HEAD's parent when that merge base is HEAD itself
(a push to, or a run on, the base branch). A base without `lessons.yaml` is the change that
introduces it, and is allowed; against a 1.x file only deletions are checked. CI
(`.github/workflows/acceptance.yml`) checks out the whole history, sets the base from the
event (`origin/<base_ref>` for a pull request, `github.event.before` for a push, `HEAD^`
otherwise) and `WGF_KNOWLEDGE_STRICT=1`: there a base that cannot be found fails integrity.
Locally it is a note.

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
title-strategy, quality tier and pinned knowledge - the pinned check tiers classified
against the pinned copies of the files they enumerate - marked `recorded: false`, and writes
nothing.

## What is not here yet

This is unit K1 of the learning-enforcement design. Recording the knowledge versions at run
start, pinning `lessons.yaml` and `check-tiers.yaml`, the `knowledge` step that writes the
contract and blocks a run that cannot make one, and the `wgf resume --except` operator act
are K2. Compliance (above) is K3. Ingestion of lesson candidates, promotion drafts, the
regression firewall (`test-core` KNOWLEDGE) and the plugin surfaces are K4.

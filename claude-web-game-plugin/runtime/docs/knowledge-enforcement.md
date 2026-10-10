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
| Knowledge model (rules) | `core/reference/lessons.yaml` 2.1.0 |
| Enforcement vocabulary, where each result is read | `core/reference/check-tiers.yaml` 1.3.0 (`tiers`, `status_at`) |
| Instance evidence (which game, run, fix, rerun) | `workspace/lessons/evidence.yaml` 2.1.0 |
| Evidence strength of a learned lesson (K6.4) | `core/reference/evidence-strength.yaml` 1.2.0, `scripts/wgf_knowledge/strength.py` |
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
| `domain`, `principle`, `anti_pattern`, `classification`, `revision` | 2.1.0 (K5, below): what part of a game it is about, the reusable why, what violating it looks like, how strongly its evidence lets it speak, and its revision. |

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
| blocking (7) | L3, L5, L10, L12, L15, L22, L29 |
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
| play-realism | physics.* | the report finished (PASS/FAIL), realism ran (a `runtime.*` entry), and the run is 3D - or 2D and the design's `build_spec.assets` declare roles, none of them a moving body (`play-realism.yaml` `physics.roles`, held equal by integrity); a design that declares no assets proves nothing |
| play-realism | naive.drift, naive.alignment | finished, naive play ran (a `naive.*` entry), the run is 2D |
| play-realism | level.* | finished, and the content-sufficiency-report read the content data file (`content.data_present` PASS) and its layout source (`layout_source.status` read or none; `unreadable` is UNMEASURED) |
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
 "data": {"decided_by": "human", "decided_at": "<ISO 8601>",
          "resume_nonce": "<the resume's nonce>",
          "exception": {"rule_id": "L26", "reason": "...", "scope": {},
                        "approved_by": {"identifier": "<the person, by name>",
                                        "mode": "human"},
                        "created_at": "<ISO 8601>", "expires_at": "<ISO 8601>"}}}
```

The record is never trusted about its approver. One reader decides
(`wgf_knowledge.exceptions.recorded`, see "In a run" below): an event with no `decided_by`,
decided by `automation`, not corroborated by its resume, or whose record is not mode human
naming a person (a placeholder such as `human` is no one) is `unverified` and refused.

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
wgf knowledge ingest <run-id> [--dry-run]     # the run's lesson candidates -> candidates.yaml
wgf knowledge candidates [--open]             # the stored candidates
wgf knowledge reject C-<n> --reason TEXT      # a person rejects one (kept)
wgf knowledge promote C-<n> [--out FILE]      # a PR-ready patch; never edits core/
        [--classification C]                  # refused beyond the evidence strength (K6.4)
wgf knowledge firewall [ID ...] [--run ID]    # every lesson's regression tests, run here
wgf knowledge generations [--json]            # runs compared by the knowledge they consumed
```

Exit status: 0 clean, 1 problems (validate) or a missing validator (resolve, table),
2 the command could not run. `contract` prints the run's recorded contract; for a run that has
none (started before the knowledge step), it resolves one now from the run's game-design,
title-strategy, quality tier and pinned knowledge - the pinned check tiers classified
against the pinned copies of the files they enumerate - marked `recorded: false`, and writes
nothing.

## In a run

A `new-game` run is held to the knowledge it started under (quality-policy 1.4.0 rule 8,
workflow 17, gates 1.7.0).

**At the start.** The run records `params.quality.knowledge` - `{"lessons": "lessons@2.1.0",
"check-tiers": "check-tiers@1.3.0"}`, the version of every file under the policy's
`knowledge` - and `params.quality.factory`, the Factory's `VERSION` and git commit (null
in an installed runtime). Both are corroborated against `WORKFLOW_STARTED` like the rest of
the snapshot and reported by `wgf status` (`quality.knowledge`, `quality.factory`), so two
runs say exactly which knowledge each was held to. A knowledge file that is missing,
unreadable, versionless or not shaped as knowledge (`versions.knowledge`) refuses the run: a
`ConfigError`, and no run is created. The workflow pins - copies into the run, digest in its
params - the lessons, the check tiers, every source file the tiers enumerate, the scope
vocabularies (genre models, quality benchmark, quality floor, platform profiles), the
viewports (browser QA, visual quality) and the quality policy.

**After design, before tech-plan.** The step `knowledge-contract` (type `knowledge`,
`scripts/wgf_knowledge/step.py`) reads the run's game-design and title-strategy, takes the
facets (`resolve.facets_from`, the tier from the run's snapshot), reads the knowledge from the
run's pinned copies only - checking each digest, and that the pinned versions are the ones
the run recorded - validates it (`registry.lesson_problems`, runtime mode), resolves it
(`resolve.resolve`, with the vocabulary from the same pins and the platform profile versions
the strategy pinned), and writes the run's `knowledge-contract`. The contract is the run's
Factory context: versions (with the run's Factory version and commit), facets, the
applicable rules by level and why, the excluded ones and why not, the validating steps, the
regression suite, the genre and platform constraints, the exceptions honoured and refused,
counts. The step follows design, so every pass through design makes it again.

It is BLOCKED - unrouted, so the run stops for a person and nothing is planned or built -
when the run did not pin a file its knowledge is read with, a pinned copy was edited after
the start, the pinned versions are not the recorded ones, the knowledge breaks its own
rules, the run's workflow cannot be read, the facets cannot be read, or a blocking or
required rule's check is produced by no step of the run's workflow (`missing_validators`).
G3 is decided on the contract (gates.yaml `required_artifacts`).

**A run started before rule 8** recorded no `knowledge`. It was never held to a contract:
its step - reached only when a resume under workflow 17 passes design again, or `wgf resume
<run> --from knowledge-contract` - makes the contract it can from what the run holds (the
pinned copy where it pinned one, the live file otherwise). The contract carries
`advisory: {reason, problems}` - every problem that would have stopped a run held to its
knowledge (files it did not pin, facets it cannot read, a missing validator, versions it
cannot record), also named in the step's message - and the step is blocked only when no
contract can be made at all: no lessons or check tiers can be read. The step is not a required step
of the quality floor, so no gate is missing from such a run. One waiting at G3 when the
Factory moves to gates 1.7.0 waits for the contract, as G4 waited for the quality-report in
1.6.0.

**Exceptions.** `wgf resume <run> --except RULE --reason TEXT --expires DATE [--scope
platform=ID|check=ID|viewport=ID ...] [--approved-by NAME]`, or `--except FILE.json` (a
record or a list). The API refuses it from inside a step's process tree (`decided_by`
automation) and hands it to `exceptions.grant`, which stamps `approved_by` - `identifier`
the person running the command by name (`--approved-by NAME`, else the login name; never a
placeholder such as `human`, `person` or `root`, never a name read from an exception file),
`mode: human` - and `created_at` now, and checks every record against
its schema, the run's pinned knowledge (`model.exception_problems` at now, with the run's
facets and the pinned vocabulary) and the run itself (a rule its contract lists, platforms
only once it targets some). Every record holds or none is recorded. A granted exception is
the operator event `KNOWLEDGE_EXCEPTION_GRANTED`, corroborated by its resume's nonce like a
budget raise:

```json
{"event": "KNOWLEDGE_EXCEPTION_GRANTED",
 "data": {"exception": {"rule_id": "L26", "reason": "...", "scope": {},
                        "approved_by": {"identifier": "<the person, by name>", "mode": "human"},
                        "created_at": "<ISO>", "expires_at": "<ISO>"},
          "decided_by": "human", "decided_at": "<ISO>", "resume_nonce": "<the resume's>"}}
```

`exceptions.recorded(events, issued)` is the one reader (`granted()` keeps what it
honours; the quality gate lists the rest refused): it honours an event only when its
`decided_by` is `human`, the `WORKFLOW_RESUMED` with the same nonce follows it, that nonce
is one the engine issued the run and used once - state.json `resume_nonces` keeps each
with the digest of what its resume recorded, one `WORKFLOW_RESUMED` carries it, and the
events carrying it still digest to it (`issued_nonces(run_dir)`; no run directory or
state.json honours nothing) - and the record's `approved_by` is mode human and names a person. `--approved-by` (or the
login name) is the person's own claim: the Factory refuses a role, a program or a
placeholder (`human`, `the bot`, `an agent`, provider and tool names, `root`, ...) and
never verifies that the name is who ran the command - identity is the installation's to
establish. A grant takes effect at the next quality gate (`wgf resume <run> --from
quality-gate`), and is listed in the contract by the next `knowledge-contract`. The contract,
the quality-report's compliance and the release list the record, so the person's name. The next contract the run makes
lists it under `exceptions`, or under `exceptions_refused` once it has expired. No
configuration grants one: `factory.knowledge.exceptions` is listed refused in the contract.

## The learning loop

Unit K4. A run's producers report systemic issues as lesson candidates
(`core/artifacts/shared/quality-finding.schema.json#/$defs/lesson_candidate`): the specialist
visits (prototype-report `specialist.lesson_candidates`), triage, the quality-report and, since
review-report 1.4.0, the reviewer. A candidate is the structured extraction **symptom -> root
cause -> systemic? -> candidate -> enforcement proposal**: `symptom` (what was seen on this
build), `summary` (the generalized lesson), `root_cause` (why the Factory let it through),
`systemic` (`{value, why}`), `proposed_check`, `proposed_level`, `proposed_scope` - all
optional but `summary`, additive to the 1.2.0 shape.

| Step | Command | What it does |
|---|---|---|
| Ingest | `wgf knowledge ingest <run>` | Every candidate of the run's reports into the project's `workspace/lessons/candidates.yaml` (`scripts/wgf_knowledge/ingest.py`). Checked against the schema and required to state its root cause: one that fails is refused and nothing is written (exit 1); a store that cannot be read as a run is exit 2. Each source records the run, the report by id, type, version and digest, its content hash, the build commit and the reporter. |
| De-duplicate | (ingest) | A report already stored as a candidate's source changes nothing - also after the candidate was promoted and its lesson holds the check. A candidate on a check an active or validated lesson holds is a **regression observation** of that lesson (`regressions`) only when the finding it resolved to is guarded by the lesson, or it states the lesson's problem (half its words in the lesson's title, problem, root cause and text); otherwise it is a new candidate listing the lesson under `related_lessons`. One whose normalized summary and proposed check match a stored candidate adds a source to it, and a different root cause is kept (`other_root_causes`). A check a candidate lesson names marks `duplicate_of`. |
| Basis | (ingest) | `measured` only when the candidate's `finding` resolves to a finding the same run's quality-report or triage-report recorded on the same build commit as the report the candidate came from - a gate's check failed on that build. A finding id no gate recorded, one on another build, a candidate naming none, and every reviewer's candidate are `subjective`. A measured source records the report it resolved in (`resolved_in`: id, version, digest). A stored candidate's basis is derived from its sources, never read from its own `basis`; promote re-verifies every measured source against the run store (`--store`) - the candidate's report and the measuring report are that run's, with the recorded digests, the candidate's report holds this very candidate (its key, computed from the record's own summary and check) carrying the finding, and the finding is recorded there on the same build - so a measured source copied from another candidate verifies nothing - and anything it cannot re-verify (run store gone, digest changed, finding absent, a hand-edited source line) is subjective, never blocking or required. It refuses a record or store out of shape. |
| List, reject | `wgf knowledge candidates [--open]`, `reject C-<n> --reason TEXT` | A rejected candidate is kept. A promoted one is read from `workspace/lessons/evidence.yaml`, whose lesson entry names its `candidate`. |
| Promote | `wgf knowledge promote C-<n> [--out FILE]` | A PR-ready patch (`git apply`): the lessons.yaml entry with the file's minor version raised, the evidence.yaml entry, and - for a lesson a check holds - test stubs for its negative (`catches`) and positive (`passes`) cases that fail until a person writes them. It writes nothing to `core/` (`promote.py`), and runs only from a web-game-factory checkout: an installed runtime does not ship the evidence file and tests it drafts against. |
| Firewall | `wgf knowledge firewall [ID ...] [--run <run>]` | Every lesson's `catches`, `passes` and `generalizes` tests run here, one verdict per lesson: PASS, FAIL, MISSING, SKIP (never a pass) or NO_TESTS (a candidate, gap or process lesson). An active lesson with no test, or a validated one without all three kinds, FAILs (`firewall.py`). A test runs on every class of its module unittest discovery would run it on (defined or inherited); one skipped, or switched off (set to None) in every class that would run it, fails the lesson. `--kind` never fails a lesson for lacking the other kinds. `--run` holds the run contract's regression suite. A development checkout only. |
| Generations | `wgf knowledge generations [--json]` | Runs grouped by the Factory and knowledge versions their outcome was judged by - the quality-report compliance's versions, else the run's contract's, else what the run recorded at start (`attributed_from`); the Factory code is the one that ran the quality gate (compliance `evaluated_by`) where the report records it (`factory_from`) - with the lessons each applied, compliance outcomes, failed and excepted rules, and the lessons one generation applied that the previous did not (`generations.py`). Read-only. |

**What promote drafts.** A measured candidate whose proposed check is classified becomes an
enforced, active lesson whose level is derived from the check's tier (one that derives
`recommended` only when its evidence strength reaches `reproduced` - K6.4, below); a stronger
proposal is declared as `level`, a weaker one refused (a level is weakened only by a check's tier). A
subjective candidate, or one whose check nothing classifies, becomes a gap / candidate lesson -
experimental, never blocking - with the proposed check named in `gap`. Refused (exit 1): a
rejected or already promoted candidate, one reported not systemic, **a blocking or required
proposal on subjective evidence** (a review comment never becomes a rule that holds a build by
itself), a blocking or required proposal no classified check can hold, and a draft that would
fail the model's own integrity rules.

**The regression firewall in CI.** `wgf test-core --only KNOWLEDGE` runs
`test_knowledge_firewall` (every shipped lesson's tests through the firewall, and the firewall's
own positive and negative cases), `test_knowledge_generalization`, `test_knowledge_ingest`,
`test_knowledge_generations` and the K1-K3 model, resolver, exception and compliance tests. A
skipped lesson test fails the firewall, so a passing category ran every one.

**Generalization.** L23, L25 and L26 name `generalizes` tests
(`scripts/tests/test_knowledge_generalization.py`): each replays the real record of the game the
lesson came from through its check, then a synthetic game B of another family or render
(`scripts/tests/fixtures/knowledge/`) - a platformer whose hero outgrew its shafts, a DOM-board
puzzle that opens the context menu on a long press, a 3D kart racer whose lap board covers the
kart - regressed (the check fails) and fixed (it passes).

**The benchmark approval table** (`table`) also takes `--profiles A,B`, `--phases 1,2` and
`--facets FILE` (a list of `{family, render, tier, platforms, profile, phase, cost_estimate}`).
Every row lists its budget as `requires human budget approval`, and `starts_run: false`:
building it imports no engine and starts nothing.

## Cross-session transfer (K5)

A lesson learned in one session reaches a later, unrelated one only through the Factory:
resolved by applicability, pinned in the run's contract at its revision, given to the
design agent, applied with a recorded decision, held by checks on the design and on the
built content, and shown at the quality gate. No prompt is replayed and no game's content
is copied.

**Knowledge model 2.1.0.** Every lesson of a 2.1.0 file carries five more fields, held by
integrity (`model.lesson_problems`, `model.file_problems`):

| Field | Meaning |
|---|---|
| `domain` | One of `lessons.yaml` `domains` (game-design, level-design, difficulty, pacing, progression, player-feedback, game-feel, ux, ui, content, replayability, art-direction, audio, vfx, performance, accessibility, technical, process). A process lesson, and only one, is `process`. Orthogonal to `category`, the scorecard line compliance counts on. |
| `principle` | The reusable why, game-agnostic ("X, because Y"). |
| `anti_pattern` | What violating it looks like, game-agnostic. |
| `classification` | `OBSERVATION`, `HEURISTIC`, `RECOMMENDATION`, `VALIDATED_PRINCIPLE`, `REQUIRED` or `BLOCKING` - consistent with the level the checks derive, never stronger or weaker: BLOCKING exactly when blocking, REQUIRED exactly when required, RECOMMENDATION a recommended rule, VALIDATED_PRINCIPLE a validated lesson that is not blocking or required, OBSERVATION or HEURISTIC an experimental rule or a process lesson. Subjective evidence never derives blocking or required (K4), so it is never classified so. |
| `revision` | An integer from 1. A rule version is `<id>@r<revision>`. |

L1-L28 were backfilled mechanically (domain from category and text, classification from
the derived level, revision 1); no rule changed. The base comparison of check-integrity also
fails an entry that changed against the base without its `revision` rising, or a revision
that fell (`model.weakening_problems`; a base before 2.1.0 introduces revisions). Promote
drafts the 2.1.0 fields (the candidate's `domain`, `principle` and `anti_pattern`, else
drafted from its category, summary and symptom for review), and a candidate may propose
several checks (`proposed_checks`: the same rule held on the design and on the build); the
level is derived over all of them.

**The snapshot.** knowledge-contract 1.2.0 records, for every rule applicable or not, its
`revision`, `version` and `digest` (sha256 of the canonical lessons.yaml entry,
`model.lesson_digest`): a run pinned under `L29@r6` keeps exactly that text when its
contract is made again after the Factory moves on, and a run started after the move gets
the new one (`test_knowledge_transfer` Versioning). It also records the design's `trace`.
The checks are pinned like the rules: the design step judges a design by the run's pinned
`design-consistency-rules.yaml` and content-sufficiency a build by the run's pinned
`content-sufficiency.yaml` (the live files only for a run that pinned none - every run
started before K2 on 2026-10-08 pinned nothing, and is judged by the live files), so a run
that pinned its files before a rule or check existed never meets it - not on resume, not when design is
entered again (`test_knowledge_transfer` PinnedBefore). Pins fail closed
(`test_knowledge_pins`, through the real design and content-sufficiency steps, for the
rules and the quality benchmark): a pinned file that is gone, or a pinned copy edited or substituted (the live newer file copied over it),
BLOCKS the step naming the file and both digests; the recorded digest cannot be swapped to
match a substituted copy - the engine refuses a run whose params differ from the ones
WORKFLOW_STARTED recorded, and a run whose log records no params can claim no pins
(`pinned_references` is a guarded param); and a blocked step never satisfies a rule - compliance reads its
check UNMEASURED and holds the release.

**The design request.** The `agent` design author's request carries `knowledge`: the
resolver's output over the facets known before the design (family, platforms), read from
the run's PINNED knowledge (`wgf_design/knowledge.py provisional`), each rule with id,
revision, version, domain, level, classification, principle, anti-pattern, checks, and
`trace: true` for the design domains (level-design, game-design, pacing, difficulty,
progression, content), plus an instruction; the prompt gains a short section asking for a
decision trace. Not the whole registry: process lessons and rules a known facet excludes are
not given.

**The decision trace.** game-design 1.16.0 `knowledge_applied`: `[{rule, revision, applied,
where (unit ids), how, verified_by (the rule's checks)}]`. A trace is a claim. The design
rule `knowledge.trace_matches_design` (blocking, listed last in design-consistency-rules
2.2.0 because it reads every other result) breaches an entry naming a rule the design was
not given, a revision it was not given, units the design does not have, checks that are not
the rule's, or `applied: true` while one of the rule's own design-consistency checks is
breached on this design; an absent trace is not a breach, a trace with no knowledge to
check it against is. The contract records `trace: {present, applied, contradicted}`, and
quality-report 1.4.0 compliance shows each rule's trace entry beside its measured status. A
claim never makes a rule SATISFIED: only its checks do.

**L29, the first transferred principle.** After the opening unit, a unit introduces at most
one element the player has not met (`core/craft/content-and-level-design.md`). Held by
`design-consistency:content.introductions_one_at_a_time` (the design's units, in index
order) and `content-sufficiency:content.introductions_one_at_a_time` (the BUILT units.json,
the same count; a design that claims compliance and a build that breaks it FAILs). What a
unit debuts is what its non-empty `introduces` lists, less what an earlier unit named - an
element and the mechanic it stands for (an armored brick, armored bricks) are one
introduction, stated once; a unit whose `introduces` is empty or absent is counted by every
element and mechanic it shows that no earlier unit named. On the build (content-sufficiency
1.6.0) each unit is also held to its design unit: an element or mechanic the built unit
names that its design unit does not, and no earlier built unit named, is a debut whatever
`introduces` the build copied - a build that shows an element a unit early FAILs. Known,
accepted limitation: on the DESIGN a non-empty `introduces` is trusted, and new elements
listed beside it are not counted there (the 2D validation design's boss level introduces
the boss fight, whose shield and weak point are new elements); the build's comparison with
its design is what holds a build to the design. What a non-empty `introduces` is trusted
with must still be structurally true (design-consistency 2.4.0, the same rule): an item the
unit does not itself contain among its elements or mechanics, or one an earlier unit already
named (a re-introduction), breaches - ids matched as unit kinds are (`content._kind`: a
trailing plural `s` dropped, so `armored-bricks` is contained beside `armored-brick`); an
unknown id is `content.mechanics_resolve`'s. Unverified, and never a breach (2.4.1): a unit
that states no `elements` list - the field is optional, and the agent-written 2D validation
design states none - introducing a declared element (build_spec.content.elements); whether it
shows it there is not known. A unit that lists its elements is held to them, and an id
neither listed nor declared is a stray either way. The normalisation's limits: an `-es`
plural is not undone (`boss`/`bosses`, `box`/`boxes` read as two ids, a false stray), and two
ids one trailing `s` apart read as one. Whether an introduction is taught well stays
unverified. A unit that names
no element, mechanic or introduction is never skipped - skipped, the next unit would falsely
debut what it met there - so any such unit leaves the count UNMEASURED: a breach on the
design (a rule that cannot be checked is never passed), SKIPPED on the build (never a
pass). Both checks are hard, so L29 derives **blocking** and is classified BLOCKING. Its
grounding is observed, never measured: both human-accepted validation games satisfy it,
recorded in `workspace/lessons/evidence.yaml` as a `research-principle` source. As written,
with no mapping, the 2D validation run's game-design v4 passes the design rule, and the
content data both games ship later (2D 0db72b6, 3D 43c08e2) pass the build check judged
against themselves (each its own design). The 2D content data judged against that design v4
does NOT pass: the build renames the design's elements (`wide-capsule` for `wide-paddle`,
`brick` for `standard-brick`, ...), so the build check reads new debuts at w1-l2, w1-l3,
w1-l8 and w4-l3 - and `content.drift`, a hard check already, fails the same pair on all 32
units; L29 adds a second report there, not a new block. The builds accepted at G4 (96f5cea,
c340631) predate those lists and pass only through `test_lesson_l29`'s reading of them (the
2D game's layout symbols and layout keys named by its own tuning sections, the 3D game's
counted course features). The genre seed
author debuted two mechanics in its second teaching unit for five families (puzzle,
platformer, shooter, strategy, simulation); it now introduces one mechanic per MVP unit -
the opener the first, then teach, breather, twist, then test units, never the climax or the
last MVP unit - and the opener takes only what the family's MVP has no unit for (two, for
racing, survival and simulation).

**The transfer test** (`scripts/tests/test_knowledge_transfer.py`, KNOWLEDGE category). Each
session is a separate process (`scripts/tests/fixtures/transfer/session.py`) with its own
`WGF_PROJECT_DIR` and a scrubbed environment, driving the shipped workflow through the real
engine and gates in the quality fixture world:

| Session | What it shows |
|---|---|
| A (the Factory before L29, `prelesson.py`) | a 2D puzzle-like build debuts two elements in one unit; the fixture bot's naive clear rate for it falls against the accepted build's and `naive.clear_rate` FAILs on that build; triage routes it; the encounter designer reports the systemic candidate on a build the gate fails again; splitting the introductions passes. `wgf knowledge ingest` stores it MEASURED; `wgf knowledge promote` (once the check is implemented) drafts the lesson, which is the shipped L29 but for a person's completion - the title and problem stated generally, the tests, the date, the revision its later edits raised - and its patch applies. |
| B (fresh) | a 3D racer designed by the real design step through the agent author; its designer reads only its request, debuts two elements at once in its own plan, and paces and records its trace only when the request carries the principle. L29 is in its contract at its revision with why it applies, in its request, in its design's trace; both design rules hold; content-sufficiency passes; compliance is SATISFIED with the trace beside it. It opened no file of Session A's, and nothing of A's is in its environment, argv or project. |
| Control | B on the Factory before L29: the request lacks it, the naive plan ships, nothing holds it. |
| Held | a violating designer breaches the rule and is repaired in the design step's repair round; a violating build fails content-sufficiency (compliance RELEASE_BLOCKED on L29) and the level designer's visit repairs it - listing the early elements in `introduces`, or showing them with `introduces` left as the design's; a designer that claims the rule applied while breaking it breaches the trace rule. |
| Held to its design | the designer states each unit's one introduction; the build shows a later element at such a unit with `introduces` copied from the design - only the comparison of each built unit with its design unit catches it (with the comparison disabled the test fails): content-sufficiency FAIL naming the unit, compliance RELEASE_BLOCKED on L29, repaired PASS. |
| C (cumulative) | a fresh session held to L29 and to an earlier, independently validated lesson, L20 (its check content.structure): both in the contract at their revisions and in the design request; a duplicated level fails L20's check while L29 still passes; repaired, both are SATISFIED. L20's own defect - the judge reading the wrong place - is a Factory bug no game can re-enact; what is exercised is its check holding a build beside L29's. |

Removing retrieval (the request's knowledge resolved to nothing) or injection (the request
without `knowledge`) makes Session B's test fail: the designer then ships its naive plan, the
design rule breaches it, and the run never reaches G4.

**What is fixture and what is real.** The engine, every gate, the design step, the
knowledge step, ingest and promote are real. The developer, the bot (its naive clear rates
included), the assets and the verify step are the quality suite's fixtures, and the
designer is a deterministic stand-in for an agent host. Session A's clear-rate failure is a
fixture measurement, and a tautological one: the fixture bot fails exactly the units
`unit_debuts` flags as debuting two elements - the same count the new checks make. It proves
the learning pipeline (a real gate's measured failure, triage, a measured candidate, ingest,
promote), not the principle - the principle rests on the real games' content and the craft.
The trace is held against the knowledge the author's request carried (`given_knowledge`),
never against knowledge resolved again from the finished design.

**A real fresh session (2026-10-08).** The test above is deterministic. Once, by hand, the same
question was asked of a real agent host: two fresh projects (their own `WGF_PROJECT_DIR`, no run
or file of Session A's, no conversation), one brief - a 2D platformer with springs, crumbling
platforms, moving logs, spikes and wind - and `wgf new-game "IDEA"`, with only the design
author a real headless agent session (`--no-session-persistence`, a USD 8 cap) and the run
held at G3, so nothing was built:

| Factory | What happened |
|---|---|
| this branch (lessons 2.1.0) | The request carried the 27 rules that apply, L29 with its principle, anti-pattern and checks. The agent folded the basic hazards into the opener, debuted one element in each of eight later levels and none in the climaxes, and traced L29 to those eight levels and both checks. The design passed (`content.introductions_one_at_a_time`: none debuts more than one; `knowledge.trace_matches_design`: 13 entries, none contradicted); the knowledge-contract pins L29 at its revision and digest, `why_applicable: [global]`, blocking, with the trace. |
| main before K5 (lessons 2.0.1) | The first draft also paced one element per level but one (its second level debuted two). No trace. The control run itself ended FAILED at the design step - it did not reach G3. |

What it shows: the knowledge reached a session that knew nothing of where it came from,
through the resolver, the request and the pinned contract, and was applied, recorded and
checked. What it does not show: a better game - a capable model paced this brief almost as
well unprompted; L29's value is that a violation cannot pass. Nothing was built or played.
The experiment also found two defects of the agent author, fixed here: a foreign-mechanic
breach named only the lexicon id (`gate`), not the design mechanic it was read from
("checkpoint flags"), and a repair round's problems were only inside a request of hundreds of
kilobytes that agents did not read whole - they are now also in the prompt.

## Evidence strength: validated learning (K6.4)

The real 2D and 3D runs showed what a learning loop learns from when nothing grades its
evidence: one check's verdict flipped seven times in fifteen reports, seventeen of
twenty-five closures rested on a single AI-judge run, and specialists repaired the measurement
instead of the game. A lesson drawn from one such pass is not a principle. So every lesson
candidate now carries an **evidence strength**, derived mechanically from the finding ledger
and the check's measurement class - never written by a reporter - and nothing
self-confirming can raise it.

| Piece | Where |
|---|---|
| The vocabulary | `core/reference/evidence-strength.yaml` 1.2.0 (held equal to the code by check-integrity) |
| Derivation, circularity guard | `scripts/wgf_knowledge/strength.py` |
| Recorded at ingest | `ingest.py`; candidate store 1.1.0 (`quality-finding.schema.json` `candidate_record`: `strength`, `strength_why`, `refused_evidence`, `unstable`; `candidate_source.remeasurement`) |
| Ceiling at promote | `promote.py` (`--classification`), the evidence entry's `strength` leg (`evidence.yaml` 2.1.0) |

**The vocabulary.**

| Strength | When | Ceiling (below REQUIRED) |
|---|---|---|
| `hypothesis` | No measured repair: a specialist's claim, a judge's prose, a person's note without a pinned measurement - or a measured failure the ledger never re-measured passing | OBSERVATION / HEURISTIC |
| `single-run` | One measured FAIL->PASS pair: the raising gate failed the check on one build and passed the same check on the same scenario on a later build, in one run | OBSERVATION / HEURISTIC |
| `reproduced` | The repair held in two or more independent measurements: the passing measurement repeated (the ledger's `verification.samples`: a later passing report of the same check, on a later commit than the one that passed, that is not the same report - a re-play of the build that passed is not a repeat), on a check that does not alternate verdicts, by a class that is not only the game's own report | RECOMMENDATION |
| `validated` | Reproduced in two or more distinct contexts - a context is the commits of a repair, so contexts differ in the builds measured (another repair on other builds, in another run, project or title); desktop and mobile of one run and build are one context, and so is another run replaying the identical commits - by a class that is not only self-reported or one AI judgment | VALIDATED_PRINCIPLE |

**Derivation.** At ingest each candidate source keeps `remeasurement`: what the run's newest
finding ledger holds of the source's finding - chosen as `wgf_triage.ledger.previous_lifecycle`
chooses it: the newest triage-report's `lifecycle`, or the newest quality-report's
`ledger.lifecycle` when that report is newer (the quality gate and release advance the ledger
after the last triage, and may reopen what it closed) - the
K6.2 `verification` (`before`, `after`, `comparison`, `samples`, the verdict), the detection
and its content hash, the history's outcomes (detected and reopened are failures, verified a
pass), and the check's measurement class from K6.3's mapping (`quality-assessment.yaml`
through `wgf_quality.assessment.expand`; a finding of no declared check takes the class of the
families whose judge is its producer's report - a visual judge's `score:<dim>` is
`ai-judged`). A pair counts when the ledger verified it (`passed`), the failing and passing
measurements are on different commits, the ledger still holds it `verified` or `closed`
(a record reopened since is `no-repair`, and listed in `unstable` when its outcomes
alternate), and nothing below refuses it. Per pair: repeats are
its accepted samples; `reproduced` with one or more, else `single-run`; capped at
`single-run` when its check is **unstable** (a pass followed by a failure again in the
ledger, or a failure and a pass on one commit - the pair is listed in `unstable`), when its
class is `self-reported` (the game's probe), when it is `ai-judged` with one judge run, or
when no class is known. The candidate is `validated` with reproduced pairs in two distinct
contexts (run, failing commit, passing commit - two scenarios of one run and build are one
context), `reproduced` with one, `single-run` with any counted pair, else
`hypothesis`. `strength_why` says which pair, its repeats, the caps and the refusals. A
source already stored is refreshed from a newer ledger when its run is ingested again (more
samples; `refreshed` in the summary) - never counted twice. Promote derives all of it again
from the run store: each measured source re-verified (K4) and its re-measurement read again
from its run's ledger (`ingest.remeasurer`); the stored strength and remeasurement are never
trusted, and with no run store there is no repair, so `hypothesis`.

**The circularity guard.** A measurement offered that may not count is recorded on the
candidate in `refused_evidence` with its rule and reason - never dropped silently:

| Rule | Refused |
|---|---|
| `same-report` (a) | The report (content hash) that detected the finding - or the candidate's own report - counted again as its pass or a sample |
| `own-check` (b) | The lesson's own proposed check measured on a build that motivated it: a pair or sample of a proposed check on a build another source of the candidate, on another check, saw the defect on. The same check on another game's builds counts |
| `same-build` (c) | A pass on the commit the failure was measured on: the ledger's `same-build`, or a later sample replaying the failing build; or a later sample on the commit that passed - a re-play of that build, not an independent repeat (a judge's is `self-agreement`) |
| `self-agreement` (d) | An AI judge re-reading what it judged: an `ai-judged` sample on a commit already judged, or of the same frames |
| `claim` (e) | A person's or a specialist's claim: a subjective source (a review, a finding no gate measured on that build, a source promote cannot re-verify), a person's G4 finding |
| `duplicate` | The same report digest offered again (a run copied byte for byte), or the same FAIL->PASS pair of content hashes: counted once |
| `no-repair` | A measured failure never re-measured passing (no ledger record, still failing, regressed, unmeasured, missing), or a repair the run's ledger reopened since |

**Promote.** Strength caps the classification a draft proposes below REQUIRED. A measured
candidate whose checks derive `recommended` (an advisory check) on `hypothesis` or
`single-run` evidence is drafted a gap / candidate lesson - experimental, OBSERVATION (or
HEURISTIC, asked for) - with the strength in its `gap`; on `reproduced` evidence it is an
active RECOMMENDATION as before; on `validated` evidence `--classification
VALIDATED_PRINCIPLE` drafts an enforced, `validated` lesson with its three test stubs
(catches, passes, generalizes), a `validated` stamp and the evidence entry's `verified` leg
(the reproduced pass: run, report, commit) - the model's own rules for a validated lesson.
A classification asked for beyond the evidence, or a `recommended` level asked for (`--level`)
or proposed by the reporter on evidence that does not reach `reproduced`, is refused (exit 1). **BLOCKING and REQUIRED stay the check
tiers'**, exactly as K4 derives them: a measured candidate held by hard or quality checks is
drafted at that level whatever its strength, and strength never raises a lesson to them.
Every draft's evidence entry records `strength: {level, why}`.

**What it cannot justify.** Strength is about whether a *measurement* repeats - the same
check failing a defect and passing its repair, again, elsewhere. It says nothing about
whether the lesson makes a game more fun, fairer or better for a player: a check can be
repeatably wrong about what a player feels, and the gaming the retro found (a repair that
changes what the gate reads, not the game) repeats as well as an honest repair does. The
guard refuses the circular sources it can name from the ledger; it cannot see two reports
that are independent on paper but share a cause (the same bot, the same flawed oracle), and
a person's G4 decision counts as a claim, not a measurement. A lesson held by a hard or
quality check is drafted BLOCKING or REQUIRED (K4) on `hypothesis` or `single-run` evidence
too: that level comes from the check's tier - the check already holds every build - not
from the evidence, and it is not a claim of strength. The draft's evidence entry records the
strength beside it; strength speaks only to how far the principle has been shown.

**Tests.** `test_knowledge_strength` (KNOWLEDGE): every level through ledgers the REAL
triage step makes from playability reports judged by the playability step's own path over
FIXTURE bot records, and on REAL bot records (the 3D game's naive.pace, FAIL on 1c6b099,
PASS on c340631: single-run); the caps; each circularity rule refused with its reason (a
ledger counting its detecting report again and a same-commit flip are real ledgers EDITED to
show what no real ledger reaches yet, and say so); duplicates once; ingest refresh; the
promote ceiling. `test_knowledge_learning_transfer` (KNOWLEDGE): three sessions, each its own
process and `WGF_PROJECT_DIR` with a scrubbed environment, through the real `wgf knowledge
ingest` and `promote` - single-run drafts only an experimental lesson; validated in two runs
may draft a VALIDATED_PRINCIPLE whose patch applies and holds the model; a
circular "validation" (the same reports re-ingested, a same-build pass, a judge re-reading
its own build) stays single-run and the stronger classifications are refused.

## What is not here yet

This is units K1 (the model and resolver), K2 (the run: the snapshot, the pins, the
`knowledge-contract` step and `wgf resume --except`), K3 (compliance, above), K4 (the
learning loop and the plugin surfaces: the `knowledge` skill and `/wgf-knowledge`, adapter
binding 1.13.0), K5 (cross-session transfer, above) and K6.4 (evidence strength, above) of
the learning-enforcement design.
K5 does not yet give the trace to authors other than the agent author (the built-in
archetype and seed authors record none), nor resolve the request's knowledge over render
and tier (undetermined before the design, which never excludes a rule). A draft composed
again without an author session (a resumed execution of an accepted draft) has its trace
held against knowledge resolved over the design's own family. Not yet: the review brief asking the
reviewer for `lesson_candidates`, a QA-report source, and `wgf decide <run> --lesson` for the
person at G4.

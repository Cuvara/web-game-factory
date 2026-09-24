# Verification Module

The `verify` step of `core/workflows/new-game.workflow.yaml`: is this build technically ready
for release, and what is the evidence. Implemented in `scripts/wgf_verification/`, registered
from `workspace/config/factory.yaml`, written against
[workflow-module-contract.md](workflow-module-contract.md) without touching the kernel.

```
bin/wgf verify                          # one step, against a local checkout
WGF_GAME_REPO=../neon-drift bin/wgf verify
```

## What it produces

| Artifact | What it is |
|---|---|
| `verification-report` | Every check, its status, and the evidence behind it. `core/artifacts/verification-report.schema.json` |
| `qa-report` | The G5 summary — suites, blocking defects, performance — **computed from** the checks, so the two cannot disagree. Pins the verification-report by hash. |

Both are returned on every outcome. A failing or blocked report is evidence too, and on a
verify → develop loop the failing `qa-report` is what development receives.

## Statuses and the verdict

| Status | Means |
|---|---|
| `PASS` | Evidence shows the requirement holds |
| `FAIL` | Evidence shows it does not |
| `BLOCKED` | It could not be established — no checkout, a missing tool, a prerequisite check that did not pass. A statement about the verification, not the game |
| `WARNING` | A problem that does not stop a release, or an optional requirement nobody provided evidence for |

Every check carries at least one piece of evidence: the command and the end of its output,
the file read, the test or scenario observed. A check without evidence is refused.

The verdict is derived: `FAIL` if a required check failed, else `BLOCKED` if one could not be
established, else `PASS`. Warnings never change it.

## Evidence statuses

The status routes; the **evidence status** says what may be claimed afterwards. Every check,
every platform, the verification-report and the qa-report carry one
(`core/artifacts/shared/evidence.schema.json`):

| Evidence status | Means | From status |
|---|---|---|
| `PASS` | observed against the real thing: an exit code, a report file this run wrote, a browser run of the built bundle | `PASS` |
| `PASS_MOCK` | observed only against a stand-in — an SDK feature exercised against a mocked or fake portal SDK | `PASS`, weakened |
| `BLOCKED_EXTERNAL` | needs an outside party (a portal's own QA) and there is no evidence from it | `BLOCKED`/`WARNING`, weakened |
| `UNVERIFIED` | not established | `BLOCKED`, `WARNING` |
| `FAIL` | the requirement does not hold | `FAIL` |

A check may only *weaken* the default for its status, and it is derived on every read, so a
check whose status later turns to `FAIL` cannot keep a stale `PASS_MOCK`. The report's
`evidence_status` is the weakest among the required checks. `PASS_MOCK` is never summed,
reported or promoted as `PASS`: the qa-report carries it, and the release step copies it into
the release-manifest unchanged.

An SDK feature is live evidence only when its `observed_by` says it was observed on the
**live portal** and does not also say mock, fake, stub or "not observed on the". Everything a
local run produces today is `PASS_MOCK`. Per platform, `portal_status` is `BLOCKED_EXTERNAL`
unless every SDK check about it passed on live evidence (`PASS`), and `NOT_APPLICABLE` when
the pinned profile's `review.process` is `none`. None of this reads a platform id: it is the
same rule for every target.

## Routing is the workflow's

The step returns a result; the workflow file decides where it goes.

| Verdict | StepResult | new-game routes it |
|---|---|---|
| `PASS` | `SUCCESS` | `next` → `release` |
| `FAIL` | `FAILED`, route `fail`, not retryable | `on: {fail: develop}` |
| `BLOCKED` | `BLOCKED` | unrouted → the run blocks for a person |

`FAIL` wins over `BLOCKED`: a failure is actionable now, a blocked check may pass once
whatever blocked it is fixed.

## The checks

| Category | Checks | Evidence from |
|---|---|---|
| source | `checkout`, `commit`, `clean-tree`, `upstream-commits` | git; prototype-report / sdk-report `build_ref` — `upstream-commits` applies the commit lineage rule (docs/core-contracts.md §5): the sdk-report's commit is HEAD, the prototype-report's is the one sdk built on (`base_commit_sha`), and `git log base..HEAD` holds only this run's `Wgf-Sdk-Key` commits. Anything else **blocks** with `commit-lineage-mismatch` (required whenever there is a report to compare); without an sdk-report the prototype-report's commit must be HEAD |
| build | `install`, `build`, `bundle`, `asset-resolution` | lockfile install; `build.command` from game.config.yaml; the output directory, digested; every local URL the built HTML/CSS/JS names |
| code | `typecheck`, `lint`, `unit`, `integration` | the repository's scripts — the names the template's CI gives qa-report suites |
| gameplay | `boot`, `loading`, `start`, `input`, `core-loop`, `progression`, `game-over`, `restart`, `pause-resume`, `responsive` | a browser against the built bundle — see below |
| policy | `runtime-facts`, `assertions:<platform>`, `asset-licenses` | `test:verify`; the template's `collect-facts.mjs` / `evaluate-assertions.mjs` against the **pinned** profile; the asset manifest |
| platform | `profile:<p>`, `sdk-init:<p>`, `hooks:<p>`, `requirements:<p>`, `fallback` | vendored `config/platforms/`; sdk-report per platform and feature (`BLOCKED` when it names another commit; `PASS_MOCK` unless observed live); declared ad kinds; shipped locales; a boot with no portal SDK present |
| assets | `manifest`, `missing`, `formats`, `paths`, `loading` | asset-manifest vs files named after each item id under `public/`, `src/assets/`, `assets/`; extensions per asset type; asset paths in `src/`; failed requests while playing |

A check that depends on another (nothing is played until it builds) is `BLOCKED` with a
`check_ref` to the one it waited for, rather than a second report of the same failure.

Checks about an `optional` platform are not required: they decide that platform's readiness
without blocking the release.

### Which gameplay aspects are required

Always `boot`, `loading`, `core-loop`, and `responsive` unless game.config.yaml sets
`verification.mobile_test: false`. With a game-design in the run, also `start`; `input` when
it describes controls; `game-over` and `restart` when a session has an end condition;
`progression` when it describes one; `pause-resume` when monetization places ads, because an
ad interrupts play. `with: {gameplay: {required: [...]}}` overrides the set.

A required aspect nothing exercised is `FAIL`, not `BLOCKED`: the fix is a test in the game
repository, which is development's work, so it loops back there.

## Evidence is this run's, and pinned

A PASS rests on what this verification ran or read, never on an upstream report's say-so —
a prototype-report claiming its tests pass is not evidence; `code.unit` runs them.

- Files a command is expected to write (`build/runtime-facts.json`,
  `build/facts/<p>.json`, `build/assertions/<p>.json`, the Playwright JSON report) are
  deleted before the command runs, so an earlier run's output is never read as this one's.
- An assertion evaluator that exits non-zero without a blocking breach is `FAIL`; so is a
  Playwright run that exits non-zero while its report shows no failing test.
- The Playwright report, assertion results, runtime facts and a recorded session are pinned
  by sha256 (`evidence[].content_hash`); every test result carries its report's hash.
- A recorded scenario that cites a `screenshot` is counted only if the file exists, and then
  with its sha256 (`data.screenshot_hash`). A passing scenario citing a missing screenshot is
  a claim without its evidence and is ignored.

## Gameplay: Playwright MCP, with a fallback

`with: {browser: auto}` (the default) chooses:

1. **Recorded session** — `build/verification/gameplay-session.json` in the game repository,
   following `core/artifacts/shared/gameplay-session.schema.json`. It is written by whoever
   played the build interactively — in practice an agent with a Playwright MCP browser tool,
   which the QA adapters instruct to do so when it is available. Accepted only when its
   `commit_sha` is the commit under test; a stale session is ignored, and the report says so.
2. **Repository suites** — otherwise `test:e2e` runs headless with the JSON reporter. Tests
   map to aspects by `@aspect` tags (`test("restarts @restart", ...)`), else by title
   keywords; a mobile-emulated project is the `responsive` evidence.

This module never talks to a browser tool itself, so the workflow does not depend on one.
`browser: recorded` or `browser: repository` forces one driver.

## Platform readiness is not platform approval

`platform_readiness` is per target platform: `ready`, `not-ready`, or `unverified`, from
local deterministic checks and the pinned profile's assertions. Every entry carries
`external_approval: not-claimed`. A portal's review is a later, external event, and a
verification that claimed to know its outcome would be claiming something it cannot observe.

## Where the checkout comes from

The module verifies a local checkout and never clones. In order:

1. the verify step's `with: repo_dir`,
2. `WGF_GAME_REPO`,
3. `verification.checkouts` in `workspace/config/factory.yaml` (relative to where `wgf` runs)
   joined with the run's `scaffold-record.repository.name`.

None found is a single `BLOCKED` `source.checkout` check — reported, not raised.

## Side effects and idempotency

Both reports carry `workflow` (run id, step, visit, execution), which the release step uses
to refuse a qa-report from another run.

Verification installs dependencies and builds in the checkout, and writes under `build/`
there (`build/verification/playwright-e2e.json`, the template's facts and assertion
results). These reproduce rather than accumulate: running it twice on the same commit yields
the same checks. It never pushes, publishes or contacts a portal.

## Parameters (`with:`)

| Key | Default | |
|---|---|---|
| `repo_dir` | — | The checkout to verify |
| `browser` | `auto` | `auto`, `recorded`, `repository` |
| `gameplay_session` | `build/verification/gameplay-session.json` | Recorded session path, relative to the checkout |
| `gameplay.required` | from the design | Aspects that must pass |
| `release_id` | `candidate-<commit>` | Written to both reports (the release step allocates the real `r<n>`) |
| `timeouts` | install 900, build 600, script 600, browser 900, git 30 | Seconds, per command kind |

## Tests

`scripts/tests/test_verification.py`, against the fixtures in
`scripts/tests/fixtures/verification/`: a scaffolded game, its built bundle, a Playwright
JSON report, runtime facts, assertion results, a recorded gameplay session, and upstream
artifacts. A scripted runner plays every command, so the suite is offline and needs no
package manager or browser. It covers each outcome, each check category, both gameplay
drivers, the verify → develop → verify → release loop through the real engine, and — with
`WGF_AJV=1` — validates the emitted reports with ajv.

`scripts/tests/test_core_verify.py` is the VERIFY category of the Core v1 freeze: valid game
evidence passes; missing evidence, a failed browser test, invalid SDK evidence and evidence
about the wrong commit do not; `PASS_MOCK` is never promoted.

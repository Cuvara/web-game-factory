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

After a `FAIL` the run passes through `review` and `sdk-review` again before verify runs, so
the failing qa-report is also a review input. While it is the run's newest qa-report, both
review briefs show its blocking defects and `evidence_status`, and tell the reviewer that
verify re-runs only after its approval and that it judges the code, not verify's result
(`docs/review-module.md`, "After verify fails"). The qa-report records no attribution of a
`FAIL` to the game or to the environment verify ran in; `UNVERIFIED` and `BLOCKED_EXTERNAL`
are the only recorded "not the game" causes.

## The checks

| Category | Checks | Evidence from |
|---|---|---|
| source | `checkout`, `commit`, `clean-tree`, `upstream-commits` | git; prototype-report / sdk-report `build_ref` — `upstream-commits` applies the commit lineage rule (docs/core-contracts.md §5): the sdk-report's commit is HEAD, the prototype-report's is the one sdk built on (`base_commit_sha`), and `git log base..HEAD` holds only this run's `Wgf-Sdk-Key` commits. Anything else **blocks** with `commit-lineage-mismatch` (required whenever there is a report to compare); without an sdk-report the prototype-report's commit must be HEAD |
| build | `install`, `build`, `bundle`, `asset-resolution`, `platform:<p>` | lockfile install; `build.command` from game.config.yaml (with several targets: once per platform, below); the output directory, digested; every local URL the built HTML/CSS/JS names, percent-decoded; a `url()` inside a `data:` URL is the inline content's, not a reference; each platform's own bundle (below) |
| code | `typecheck`, `lint`, `unit`, `integration` | the repository's scripts — the names the template's CI gives qa-report suites |
| gameplay | `boot`, `loading`, `start`, `input`, `core-loop`, `progression`, `game-over`, `restart`, `pause-resume`, `responsive` | a browser against the built bundle — see below |
| gameplay | `quality.report-commit`, `quality.<group>:<check>` | the playability-report: what the bot measured about the design's content, difficulty, progression and depth, carried not re-measured — see below |
| browser QA | `run`, then `browser.<check>[:<viewport>]` filed under gameplay, policy or assets | the Factory's browser spec against the build at five viewports, judged against `core/reference/browser-qa.yaml` - see [Browser QA](#browser-qa-every-viewport-audio-and-performance) |
| policy | `runtime-facts`, `assertions:<platform>`, `assertion-warnings:<platform>`, `asset-licenses` | `test:verify`; the template's `collect-facts.mjs` / `evaluate-assertions.mjs` against the **pinned** profile (a breached `blocking` assertion FAILs `assertions:<platform>`; breached `warning`-severity ones go on the optional `assertion-warnings:<platform>`, so they never weaken the release's evidence); the asset manifest |
| platform | `profile:<p>`, `sdk-init:<p>`, `hooks:<p>`, `requirements:<p>`, `fallback` | vendored `config/platforms/`; sdk-report per platform and feature (`BLOCKED` when it names another commit; `PASS_MOCK` unless observed live); declared ad kinds; shipped locales; a boot with no portal SDK present |
| assets | `manifest`, `missing`, `formats`, `paths`, `runtime-manifest`, `loading` | asset-manifest vs files named after each item id under `public/`, `src/assets/`, `assets/` (source code under `src/assets/` is the bundler's input, not an asset); extensions per asset type; asset paths in `src/`; `public/assets/assets.json` against the repository with the assets module's validator (broken references FAIL; a stale hash, unlisted/unused file or large texture is a WARNING; absent is a WARNING) ([assets-module.md](assets-module.md#validation)); failed requests while playing |

A check that depends on another (nothing is played until it builds) is `BLOCKED` with a
`check_ref` to the one it waited for, rather than a second report of the same failure.

With one target platform, checks about it follow its role (`required`, the norm). With more
than one, **every** platform's checks are required, whatever its role: each gets a package of
its own, so each is shippable or the verdict fails - an `optional` platform that is not ready
fails verification like a `required` one (until 2.8.0 it was reported `not-ready` without
failing the verdict, because one bundle could serve only one platform anyway).

### One bundle per platform

On the pinned template contract (1) `pnpm build` makes one bundle booting one adapter
(`template_contract.build_target`). With more than one target, `build.build` is one build
per platform (`wgf_verification/platform_builds.py`):

    build/platforms/<id>/game.config.json   game.config.yaml with platforms: [<that entry>,
                                            role: required], build.output: the dist below -
                                            canonical JSON, which the template's YAML parser reads
    build/platforms/<id>/dist/              the build's output, copied out of build.output
    build/platforms/<id>/build.json         platform, profile, commit, dist_digest
    build/platforms/index.json              every platform built, in platforms[] order

Each build runs the repository's build command with `WGF_GAME_CONFIG` naming that config -
the pinned template's own override: `vite.config.ts` builds against it, so the bundle boots
that platform's adapter and carries only its head script (CrazyGames, Y8) and IDs (Y8), and
`scripts/_shared.mjs` `readGameConfig` makes `collect-facts`, `release:package` and
`release:manifest` read the same config. The build target is built last, so `dist/` ends
holding its bundle - the one the browser checks play. Everything is under the template's
git-ignored `/build/`: nothing is committed, the tree stays clean. N targets cost N builds,
not N+1.

Per platform, then:

- `build.platform:<id>` - its bundle exists, has `index.html`, fits its profile's
  `max_bundle_mb`, and is not byte-identical to another platform's (that would mean the
  build ignored `WGF_GAME_CONFIG` and boots one adapter everywhere);
- `platform.build-target:<id>` - PASS when its own bundle was built for it alone;
- `platform.requirements:<id>` - locales read from its own bundle;
- `policy.assertions:<id>` - `collect-facts` and `evaluate-assertions` run with its
  `WGF_GAME_CONFIG`, so `package.size_mb`, `package.locales` and the screenshots count are
  measured on its bundle. A breached warning-severity assertion is reported on the optional
  `policy.assertion-warnings:<id>`, not here: with every target required, a WARNING here
  would be UNVERIFIED evidence and refuse the release, though the profile says the breach
  does not stop one (`yandex_screenshots` counts store screenshots, which do not exist until
  `store-listing`; `listing-validation` judges them). The **runtime** facts (`test:verify`: https, loading, fps) are
  measured once, in a local browser against the build target's bundle - the same game code
  with another adapter, and no portal SDK loads there in any case.

The verification-report pins each bundle in `build_artifact.platforms[]` (schema 1.2.0:
path, digest, file count, bytes, `built_by`, the config and its sha256); the release packages
exactly those bytes ([release-module.md](release-module.md#one-package-per-target-platform)).
A template on contract 2 (`package.json` `wgf.template.contract: 2` and a `build:platforms`
script) builds its platforms itself into the same layout: verify runs the ordinary build
(for the browser checks), then `build:platforms` once, and pins what `index.json` lists,
refusing a bundle whose digest is not the one recorded. A single-platform title on contract
1 is built once, exactly as before: no `build/platforms/`, no `build.platform:` check.

What the profiles cannot tell verify: which SDK script a portal requires in `index.html`.
Their `<id>_sdk_present` assertions read `package.platform_sdk`, which the template's
`collect-facts` echoes from `--platform`; the adapter a bundle boots is established by how it
was built (`platform.build-target`), not by those assertions.

The game's `test:e2e` runs at `e2e_workers` Playwright workers (the step's `with:`), else at the
machine's `factory.develop.smoke_workers`, the same suite develop's smoke check runs; unset
leaves the suite's own parallelism.

Browser commands - the game's `test:e2e`, the runtime-facts `test:verify` - run behind a proxy
that refuses every non-local request (`wgflib.netguard`, as the develop step's smoke does and
the golden runs always have). A portal build would otherwise load the portal's real SDK from
its CDN, and "no insecure requests" or time to interactive would measure the portal's CDN, not
the game (a Poki build pulls an `http://` ad bridge). The portal SDK is refused as an ad
blocker would refuse it; live portal behaviour stays `BLOCKED_EXTERNAL`. Where Chromium
ignores the proxy variables (Windows, macOS) the command runs with `-c` on a wrapper of the
game's `playwright.config.ts`, written outside the checkout, that hands the browser the proxy
itself (`netguard.guarded_playwright_config`); the game's config is never edited.

### Which gameplay aspects are required

Always `boot`, `loading`, `core-loop`, and `responsive` unless game.config.yaml sets
`verification.mobile_test: false`. With a game-design in the run, also `start`; `input` when
it describes controls; `game-over` and `restart` when a session has an end condition;
`progression` when it describes one; `pause-resume` when monetization places ads, because an
ad interrupts play. `with: {gameplay: {required: [...]}}` overrides the set.

A required aspect nothing exercised is `FAIL`, not `BLOCKED`: the fix is a test in the game
repository, which is development's work, so it loops back there.

`progression` is the exception, because it is the thing a prototype most often does not have
and it used to pass on a test whose *title* mentioned a score. It has no title-keyword mapping
any more. It passes only on evidence that names it:

- `quality.progression:persists` PASS - the bot reloaded the build and found the designed
  progression intact; or
- a test or recorded scenario explicitly tagged `@progression`, **together with** content
  conformance: the develop step's own content check in `docs/development/checks.json`, else
  `public/content/units.json` carrying every MVP unit id when the design authors content. A
  design that authors no content units has nothing to conform to, and the tagged test stands.

### Quality: the playability evidence, carried

`checks/quality.py` reads the `playability-report` among this step's inputs and never plays the
game again.

- `quality.report-commit` holds the report to the build under test: the commit develop built
  (the `prototype-report` this verification pins; the verified commit may be the sdk step's,
  one commit on top of it). A report about anything else **fails**, and none of its answers are
  carried - an earlier visit's evidence is not evidence about this build.
- one check per `content.` / `difficulty.` / `progression.` / `depth.` check of the report, with
  every viewport collapsed into one answer: FAIL if any viewport failed, WARNING if any was
  skipped or warned (a skip is **never** a pass, and the warning says what was not measured),
  else PASS. Ids are translated into the verification-report's own vocabulary:
  `content.units_reachable` becomes `quality.content:units-reachable`.
- `SUITES` maps `quality.` to the qa-report suite `gameplay-quality`, so G5 reads it beside
  lint, unit and e2e.
- With no playability-report at all the verification is `BLOCKED` on `quality.report` -
  **required** when the workflow declares the input and it did not arrive, not required when
  the run never asked for one. Either way the report says the content was not verified rather
  than implying it was.

## Browser QA: every viewport, audio and performance

`browser_qa.py` runs the Factory's own browser spec, `browser_qa.spec.ts`, against the build
after the gameplay checks, and judges what it recorded against
[`core/reference/browser-qa.yaml`](../core/reference/browser-qa.yaml) - the contract as data:
viewports, checks, tiers and bars. The spec is copied into the checkout's git-ignored
`build/wgf-browser-qa/` with a generated Playwright config (one project per viewport, the
repository's own `pnpm preview` of `dist/`, the refusing proxy handed to the browser itself,
every non-local request aborted at once as an ad blocker would), so it needs nothing from the
game but `@playwright/test` and the play probe. The tree stays clean. The spec records and
never judges; `judge()` holds the records to the bars, so the judging is tested offline from
records (`scripts/tests/test_browser_qa.py`) and the same records always give the same checks.

**Viewports**: desktop wide 1920x1080, desktop standard 1280x720, narrow desktop 1024x768,
tablet 768x1024 and mobile 390x844 (tablet and mobile as touch devices). Per viewport the
spec loads the build as a first session, walks the menus into play, measures the DOM UI on
every screen it reaches (title, playing, paused, won, lost), samples which DOM UI covers the
probe's gameplay-critical entities during play, right-clicks the game (a long press on touch),
pauses and resumes, hides the page, and plays to `won` (the oracle) and to `lost` (bad play)
and retries. On the audio viewport it also probes the mute control and decodes every clip the
runtime manifest ships; on the perf viewport it records frame times over active play and the
JS heap after a forced collection across a session of play, losses and restarts.

**Tiers** (`tier` on every check, one vocabulary):

| Tier | Required | A FAIL |
|---|---|---|
| `hard` - Hard Gate | at every quality tier | fails verification, loops to develop |
| `quality` - Quality Gate | where the run's quality-tier class is in `quality_required_at` (release, as shipped) | fails a release-tier run; a WARNING in a development run |
| `advisory` | never | a WARNING |

A check whose `hard_when_profile` names a flag a targeted platform profile sets true under
`requirements` (`context-menu`: `requirements.context_menu_suppressed`) is a Hard Gate for
that title. A check that measured nothing is never a PASS: BLOCKED where it is required and
the measurement was possible (the spec did not run, a record is missing, the host was
degraded), a WARNING where the game has nothing of that kind (no pause control, no mute
control, an end state not reached in its window - the playability step judges
`win.reachable` over its own window).

| Check (`browser.<id>[:<viewport>]`) | Tier | |
|---|---|---|
| `loads`, `canvas`, `ready`, `menus` | hard | the page and the game's own requests answer; a canvas covers 25 % of the viewport; the probe leaves `loading` within 30 s; the title leads into play |
| `page-errors`, `webgl-context` | hard | no uncaught exception or rejection; no WebGL context lost (one the page releases itself through `WEBGL_lose_context` - PixiJS probing support - is not a loss) |
| `console-errors` | quality | no console error from the game's origin; refused and foreign requests are the environment's |
| `context-menu` | quality (hard by profile) | a right click / long press on the game is prevented |
| `load-time`, `first-interaction` | quality, timing | probe ready within 6 s; first input offered within 8 s |
| `win`, `lose`, `restart` | quality | per outcomes viewport |
| `pause-resume`, `hidden-pause` | quality | the pause control pauses and resumes; hidden, play holds still and resumes |
| `overflow`, `clipping`, `ui-overlap`, `ui-covers-play` | quality | the page does not scroll; no control or text cut by the edge; no controls overlapping; painted UI over at most 25 % of a critical entity in two consecutive samples |
| `safe-margins`, `button-states` | advisory | 4 px from the edge; hover/pressed/disabled look different |
| `audio-clips`, `audio-loops`, `audio-hidden` | hard | every manifest clip decodes; no clip the manifest does not mark `audio.loop` is started looping; silent while hidden |
| `audio-events`, `audio-mute`, `audio-loudness` | quality | a sound within 500 ms of each declared action with `audio`, and from 1.5 s before to 2.5 s after `won`/`lost`; the mute control silences and restores; effects within 20 dB of each other, music 3 dB over to 24 dB under them, no clipping |
| `frame-stability`, `memory-growth` | quality, timing | p95 frame time 33.4 ms, at most 2 % of frames 100 ms or longer; heap growth at most 24 MB over 45 s |
| `oversized-textures` / `asset-weight` | quality / advisory | no image edge over 4096 px / over 2048 px, 1 MiB, effects over 512 KiB, music over 256 kbps |

**Host load.** The timing checks (`timing: true`) carry the health of the host they were
measured on, judged exactly as the playability bot's are (`wgf_playability.analysis.
environment_health` with `visual-quality.yaml` `environment`, read from there): a timer in the
spec's process, a timer in a worker inside the page, the local server's wait. A recording made
on a degraded host is made again (up to `max_attempts`); when the last attempt was degraded the
timing checks are BLOCKED - re-measured on a quiet host - whatever they read: a degraded host
never passes and never fails them. A frame-time failure on a software rasterizer
(`software_renderers`: SwiftShader, llvmpipe) is BLOCKED the same way; the config asks the
host's GPU first (ANGLE on D3D11, Metal or Vulkan). An `audio-events` silence read on a
degraded host is BLOCKED too; a sound that followed in its window stands.

**Into the reports.** The checks join the verification-report (category per the contract) and
the qa-report: blocking ones become `blocking_defects`, the timing ones the `performance`
suite and the rest `smoke`; a `desktop-chromium-browser-qa` entry joins `perf_results`
(median-frame fps, heap, `within_budget` false when a required browser performance check did
not pass), which `floor.performance` reads. `with: {browser_qa: off}` skips the spec and
leaves `browser.run` BLOCKED at the release tier (a WARNING below it): switching it off is
never a pass.

**Tiers, routing and the floor.** Each check's tier is classified once, in
`core/reference/check-tiers.yaml` (source `browser-qa`, read from this file's `tier` with the
`browser.` prefix; `browser.run` is `browser-qa-run`). A blocking defect reaches triage
through the qa-report as `vr-<check>[-<viewport>]`; `core/reference/specialist-routing.yaml`
qa-report `verification_checks` names the check and its owner - boot, runtime, visibility and
the context menu to browser QA, layout to UI, sound to audio, timings and weight to the
performance engineer, the session's outcomes to gameplay - the same dimension each check's
`owner` here states (`test_browser_qa.py` holds that they agree). The quality gate reads them
on its scorecard (`core/reference/quality-floor.yaml` 1.2.0, `applies: reported`):
`floor.browser_boot` and `floor.browser_session` on the browser line, `floor.browser_layout`
(and the advisory `floor.browser_ui_advisory`) on UI/UX, `floor.browser_audio` on audio,
`floor.browser_performance` (and the advisory `floor.browser_asset_weight`) on performance.
Lessons L24-L28 (`core/reference/lessons.yaml`) name these checks.

**Context-menu suppression and the template.** The template's `main` already prevents the
context menu in `bindPlatform` (web-game-template PR #27), so a game made from a template
release that carries it passes `context-menu` without code of its own; a game made from an
earlier pin (v1.2.0, `workspace/config/template.lock.json`) does not, which is what the
calibration games show. Nothing here duplicates the template's handler: the check only
measures it.

**Calibration (2026-10-07).** The spec was run on the two validation games at their accepted
commits - Brick Breaker Worlds (PixiJS, 894b4b8) and Sky Marble (three.js, c340631) - in
clones of those commits, on a Windows 11 host with a GPU (ANGLE D3D11) that other agents were
loading at the same time; the records are the replay fixtures `scripts/tests/fixtures/
browser-qa/*.json`. A whole run took 6.5-10 minutes per game. Measured, at the bars above:

| | Brick Breaker Worlds | Sky Marble |
|---|---|---|
| probe ready, per viewport | 0.87-1.21 s | 0.33-1.03 s |
| p95 / median frame time (GPU) | 16.8 / 16.7 ms, no long frames | 16.8 / 16.7 ms, no long frames |
| JS heap over 45 s of play, losses, restarts | 4.97 -> 6.55 MB | 6.89 -> 8.14 MB |
| effects loudness spread; music vs effects; peak | 10.8 dB; music 4.3 dB under; -0.9 dBFS | 9.0 dB; music 3.4 dB under; -1 dBFS |
| oracle win / bad-play loss, per viewport | won in 26-36 s; lost in 42-59 s, once not within 60 s (`lose_s` 90 from this) | won in 19 s; lost on its 30 s clock |

The first run, on SwiftShader (the playability config's software GL), drew Brick Breaker at
a median 100 ms per frame and was BLOCKED, not failed - which is why the config asks for the
GPU. On the loaded host two attempts of Sky Marble's desktop-standard viewport were degraded
(the spec's timer lost 5.3-6.5 s of 20-24 s): its load-time and first-interaction were
BLOCKED that run and passed on the next, quiet one. Every bar stands as first written except
`lose_s` (60 cut Brick Breaker's three-ball loss) and three measurement corrections the real
records showed: a context the page releases itself is not lost (PixiJS's WebGL probe), the
end-of-play sound may lead the probe's `lost` by up to 1.5 s (Brick Breaker's sting starts
350-1030 ms before its fail card), and painted UI must cover an entity in two consecutive
samples (Sky Marble's course card is gone 400 ms after play starts).

The defects the runs found are the games' (the bars were not moved for them):

- **Both games open the browser's context menu** on a right click at every desktop viewport
  and do not prevent the contextmenu a long press raises on tablet and mobile (M6, Yandex
  1.6.1.8). The template now prevents it (`src/platform/context-menu.ts`); the games predate it.
- **Brick Breaker Worlds: the objective card covers the ball** on tablet (100 %) and mobile
  (40 %) in consecutive samples of play - `div#objective-line` sits in the play field.
- **Sky Marble: losing on the clock is silent** - no sound within 2.5 s of `lost` (its last
  sound, the fall, is 3.8 s earlier); a design that lists failure feedback in sound.
- Advisory: neither game's title buttons change on hover (Brick Breaker's PLAY and SOUND ON;
  Sky Marble's Play, Courses and Sound on).

Everything else passed on both: loading, menus, no page or console errors, no context lost,
win/lose/restart at every viewport, pause and resume, held and silent while hidden, the mute
control (found on the pause screen in both), no accidental loops (Sky Marble's `sfx-roll` is a
declared loop), every clip decodes, loudness, frames, memory, texture sizes.

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

The module verifies a local checkout and never clones. It finds it as every step does
([checkouts.md](checkouts.md), `wgflib/checkout.py`):

1. the verify step's `with: repo_dir` (alias `game_repo`),
2. `WGF_GAME_REPO`,
3. the scaffold-record's `repository.local_path`, where init put it (skipped, with a
   warning, when that path does not exist here),
4. `factory.checkouts` joined with the run's `scaffold-record.repository.name`
   (`verification.checkouts` is a deprecated alias).

Relative paths resolve against the project root ([plugin-runtime.md](plugin-runtime.md)). The first rule that names a path decides;
no package.json there is a single `BLOCKED` `source.checkout` check — reported, not raised.
While verify runs it holds the checkout's lock: another run in the same checkout is
`BLOCKED`, naming it.

`platform.build-target:<id>` says whether the bundle a platform would ship is that
platform's build. With one target it is (one bundle boots the first `required` platform,
else the first: `template_contract.build_target`). With several, each platform's own bundle
is (above); a platform whose own build failed is BLOCKED by `build.platform:<id>`. The
profile assertions cannot say it: the template's `platform_sdk` fact echoes the platform it
is asked about.

`policy.device-performance` carries the runtime facts' fps and time to interactive with
`evidence_status: PASS_MOCK`: they are measured in CPU-throttled desktop Chromium, a proxy for
a low-end device, never a device. Not required; the strategy's own fps floor is judged at G4.

`platform.profile:<id>` judges the game by the profile it pins **by content hash**: the
vendored `config/platforms/<id>.yaml` must match its `pinned.json` entry and the Factory's
profile at that version (`wgf_init.profiles.pin_identity`). A copy that only declares the
pinned version - edited, or a same-version document from elsewhere - FAILs the check and is
not read; the Factory's own profile stands in for the other checks. A game that vendors
nothing for a platform is judged by the Factory's profile.

## The environment game code runs with

Everything verification runs in the checkout - install, build, the package.json scripts,
Playwright and its webServer, the template's fact collectors, and git - goes through
`CommandRunner` with the game-code environment, never the Factory's: `wgflib/agentenv.py` `game_code_env`: the agents' allowlist (PATH, HOME, USER, LANG/LC_*, TERM, TMPDIR, SHELL, CI, the proxy variables, XDG_*, NODE_*, PNPM_*, npm_config_*, PLAYWRIGHT_*, COREPACK_* - minus any name that says it is a secret) plus `factory.agents.game_env_passthrough`. The
refusing proxy (browser checks) and `CI=1` are layered on top. A runner built with no `env`
still gets the allowlist of `os.environ`; a test that injects its own `env` keeps it.

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
| `timeouts` | install 900, build 600, script 600, browser 900, git 30; `browser_qa` from the contract's windows | Seconds, per command kind |
| `browser_qa` | `auto` | `auto` runs browser QA ([above](#browser-qa-every-viewport-audio-and-performance)); `off` skips it, leaving `browser.run` BLOCKED at the release tier |

## Tests

`scripts/tests/test_verification.py`, against the fixtures in
`scripts/tests/fixtures/verification/`: a scaffolded game, its built bundle, a Playwright
JSON report, runtime facts, assertion results, a recorded gameplay session, and upstream
artifacts. A scripted runner plays every command, so the suite is offline and needs no
package manager or browser. It covers each outcome, each check category, both gameplay
drivers, the verify → develop → verify → release loop through the real engine, and — with
`WGF_AJV=1` — validates the emitted reports with ajv.

`PlatformAndPolicy` holds the per-platform builds: two targets built against their own
configs (the build target last, `dist/` its bundle), the facts collected through each
`WGF_GAME_CONFIG`, distinct pinned digests and an idempotent second run; a build that ignores
the config (byte-identical bundles) and one platform's failed build fail the verdict; every
targeted platform is required; a single platform is built once with nothing under
`build/platforms/`; a contract-2 repository's `build:platforms`.

`scripts/tests/test_browser_qa.py` holds browser QA: the contract (versioned, every check
tiered, the five viewports, the request's checks all present, the shared bars read from
`visual-quality.yaml` and `production-quality.yaml`), the tiers, a healthy record set passing,
each defect failing on its own, the degraded-host and software-rasterizer rules, the bundle
scan, the generated runner, and the replay of the records the spec made of the two validation
games (`fixtures/browser-qa/`) and of the zz-perf load artefact (BLOCKED, never FAIL). `test_verification.py` `BrowserQA` runs it through the verify
step: guarded, a quality defect failing a release run and warning a development one, a hard
defect failing any run, a degraded host blocking, `browser_qa: off` never passing.

`scripts/tests/test_core_verify.py` is the VERIFY category of the Core v1 freeze: valid game
evidence passes; missing evidence, a failed browser test, invalid SDK evidence and evidence
about the wrong commit do not; `PASS_MOCK` is never promoted.

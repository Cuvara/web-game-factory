# `WGF_*` environment variables

Every `WGF_*` variable the Factory's code reads or sets: `scripts/`, `bin/`, and the test
suite. Anything not listed here is not read. Keep this page in step with the code: when you
add a variable, add its row (`grep -rnoE "WGF_[A-Z0-9_]+" scripts bin` finds them).

**Kinds.** *runtime* - read by `wgf` or a step module during a real run. *test* - read only by
the test suite or the golden harness. *child* - set by the Factory for a process it starts;
you never set it yourself. *org* - a GitHub organization secret or variable the game
pipelines read, inventoried by `scripts/wgf-org-setup.sh`; the Factory's Python never reads it.

**Opt-in flags mean exactly `1`.** A test flag is on only when its value is the string `1`
(`scripts/tests/testenv.py`, `enabled(name)`); `true`, `yes` and `0` are all *off*. Every test
this repository owns reads its flags that way. `test_core_agents.py`, `test_develop_module.py`,
`test_techplan_module.py` and `test_strategy.py` still read theirs as "any non-empty value";
set `=1` and both readings agree.

## Runtime

| Variable | Read by | Meaning | Default |
|---|---|---|---|
| `WGF_FFMPEG` | `scripts/wgf_listing/capture.mjs` | An ffmpeg that lists the libx264 encoder, used to convert the store-listing trailer to MP4 (Yandex accepts only MP4). Playwright's bundled ffmpeg writes VP8/WebM only and is still used to trim. Without any libx264 encoder the MP4 is not made and a listing that requires it stops for a person. | unset: an `ffmpeg` on PATH, then Playwright's bundled one |
| `WGF_GAME_REPO` | `scripts/wgflib/checkout.py` | The game checkout EVERY step that works in the game repository uses - init (where it creates the project), assets, develop, review, sdk, verify and release - when the step's own `with: repo_dir` / `game_repo` is not set. Checked before the scaffold-record's `local_path` and `factory.checkouts`. A relative path resolves against the Factory root ([checkouts.md](checkouts.md)). | unset: the scaffold-record's `local_path`, else `factory.checkouts` + the repository name |
| `WGF_PROJECT_DIR` | `scripts/wgflib/paths.py` | The project root: where `workspace/` (instance data and the installation's own `workspace/config/`), the run store and the checkouts base resolve. Never where `core/` or the engine is read - that is always beside `wgflib/`. Set by the installed runtime for every process it starts, so a child in another directory finds the same project. ([plugin-runtime.md](plugin-runtime.md)) | development checkout: the repository; installed plugin runtime: the working directory |
| `WGF_PUBLISH_LIVE` | `scripts/wgf_publish/common.py` | `1`, together with `factory.publish.mode: live`, lets the `submit` step upload to the portal's draft (the review request still waits for a person's `submit` decision in a later visit). Either alone is a dry run. ([publish-module.md](publish-module.md)) | unset: dry run |
| ~~`WGF_PUBLISH_<PLATFORM>_STORAGE_STATE`~~ | retired (publication profile 2.1.0) | No portal session is captured or kept: a person logs in, live, in the browser window the `submit` step opens, and the session ends with it. Nothing reads these variables any more; delete any that are set, and the captured files they named. | - |
| `WGF_PUBLISH_PLATFORMS` | `scripts/wgf_publish/step.py` (set by `wgf publish --platform`) | Comma-separated platform ids: the `submit` step acts on those packaged platforms only and leaves every other record as it is. Set by the CLI for its own process; never configured. | unset: every packaged platform |
| `WGF_PUBLISH_TRACK` | `scripts/wgf_publish/step.py` (set by `wgf publish --track`) | `1`: the `submit` step only reads each platform's status on its portal (no upload, no click) and updates the record and the portal registry from it. Set by the CLI for its own process. | unset: a publishing visit |
| `WGF_RESEARCH_LIVE` | `scripts/wgf_discovery/step.py` | `1` makes the `research` step fetch the pages in `probes.yaml` during the run, like `live: true` on the step. | off: evidence snapshots only |
| `WGF_TEMPLATE_COMMIT` | `scripts/wgflib/template.py` | A deliberate override of the web-game-template commit in `workspace/config/template.lock.json`. Must be a full 40-hex sha. Used to validate a new pin before moving the lock. | the lock's `commit` |
| `WGF_TEMPLATE_DIR` | `scripts/wgflib/template.py` | Offer an existing template checkout instead of the cache. Refused (`TemplateDrift`) unless its HEAD is exactly the expected commit; never moved. | unset: cache, then clone |
| `WGF_TEMPLATE_CACHE` | `scripts/wgflib/template.py` | Where pinned template checkouts are cached, one directory per sha. | `~/.cache/wgf/templates` |
| `WGF_KNOWLEDGE_BASE` | `scripts/check-integrity.py` | The git ref whose `core/reference/lessons.yaml` the knowledge model is compared with: a lesson deleted, or its level weakened or its scope narrowed in place, fails integrity ([knowledge-enforcement.md](knowledge-enforcement.md)). A ref git cannot show (a shallow checkout) is noted and skipped; a previous file before 2.0.0 is not compared. | `origin/main` |
| `WGF_ORCA` | `scripts/wgf_delegate.py` | The orca executable `scripts/wgf-delegate.py` starts delegated agents with ([orca-delegation.md](orca-delegation.md)). | `orca` on PATH |
| `WGF_DELEGATION_LEDGER` | `scripts/wgf_delegate.py` | The JSON-lines ledger of delegations (task, worktree, branch, dispatch, terminal) that `wgf-delegate audit` reads. | `~/.cache/wgf/delegations.jsonl` |
| `WGF_BLENDER` | `scripts/wgf_assets/blender.py` | The Blender executable the `assets` step and `scripts/wgf-model.py` build models with, when `factory.assets.placeholders.blender.executable` is not set. Must be the pinned series (4.5) unless `allow_unpinned` ([blender-pipeline.md](blender-pipeline.md)). Not passed to Blender itself: its environment is an allowlist. | unset: `blender` on PATH |
| `WGF_HEARTBEAT_SECONDS` | `scripts/wgflib/procs.py` | Heartbeat interval for every owned child process (`STEP_PROGRESS`, `last_activity_at`). A positive number; anything else falls back to the default. | `15` |
| `WGF_LOCK_DIR` | `scripts/wgflib/portlock.py` | Where the machine-wide locks on the template's fixed preview ports live (`port-<port>.lock`, `port-<port>.holder.json`). Every Factory process on the machine must agree on it, or they stop serializing ([agent-lifecycle.md](agent-lifecycle.md#fixed-preview-ports)). | `~/.cache/wgf/locks` |
| `WGF_PORT_LOCK_TIMEOUT` | `scripts/wgflib/portlock.py` | Seconds a command waits for another process to release a fixed preview port (4173, 4176) before `procs.run` returns an error naming the holder. A non-negative number; anything else falls back to the default. | `3600` |

Agent processes and the game code the Factory runs (develop checks, verify, sdk, release
packaging) do not see the Factory's environment: they get `scripts/wgflib/agentenv.py`'s
allowlist, which carries no `WGF_*` variable but the `WGF_PROC_*` tags, plus what
`factory.agents.env_passthrough` (agents) or `factory.agents.game_env_passthrough` (game
code) names. A `WGF_*` variable listed below as read by a step is read by the Factory's own
Python, not by its children.

## Set by the Factory for its children

| Variable | Set by | Meaning |
|---|---|---|
| `WGF_BROWSER_PROXY` | `scripts/wgflib/netguard.py` (`sandbox_env`); read by the playability bot's generated Playwright config, `scripts/wgf_listing/capture.mjs` and the wrapper `guarded_playwright_config` writes | The refusing proxy's URL, for a browser command. Passed to Chromium as Playwright's `proxy` (bypassing loopback), because Chromium ignores the `http(s)_proxy` variables everywhere but Linux. |
| `WGF_PROC_TAG` | `scripts/wgflib/procs.py` (also named in `wgflib/workflow/api.py`) | A unique tag in each owned child's environment. Environment survives `setsid()` and double-forks, so the whole tree - including a detached daemon - can be found and terminated. |
| `WGF_PROC_LINEAGE` | `scripts/wgflib/procs.py` | The chain of tags of the owned processes above this one, so a nested owned tree is also found from its ancestor's tag. |
| `WGF_PROC_RUN` | `scripts/wgflib/procs.py` (bound by `wgflib/workflow/engine.py`) | The workflow runs whose steps own this tree, outermost first, each `<run-id>@<12 hex digits of the run store's directory>`. Set only on children started while a step executes; a caller-supplied value is replaced. Resuming or cancelling a run whose driver died (SIGKILL) ends every process still naming it (Linux; docs/agent-lifecycle.md#sigkill-recovery). |
| `WGF_PROC_PORTS` | `scripts/wgflib/procs.py`, `scripts/wgflib/portlock.py` | The fixed preview ports held for this tree, comma-separated. Set on every child started while `procs.run` holds a port lock; a descendant Factory process takes those ports without waiting, so it never waits on its own ancestor. |
| `WGF_REVIEW_REPO`, `WGF_REVIEW_VERDICT`, `WGF_REVIEW_BRIEF`, `WGF_REVIEW_COMMIT` | `scripts/wgf_review/step.py` | Given to a `command` reviewer: the checkout (read-only), where to write the verdict, the brief, and the sha under review - the same values as the `{repo}`, `{verdict}`, `{brief}`, `{commit}` argv placeholders. |
| `WGF_E2E_PLATFORM`, `WGF_E2E_ENGINE`, `WGF_E2E_EXPECT`, `WGF_E2E_REPORT` | `scripts/wgf_sdk/e2e.py`; read by `scripts/wgf_sdk/e2e/smoke.spec.ts`, `playwright.config.ts` | One SDK browser e2e case: which portal and engine the build is for, what the smoke must observe, and where Playwright writes its JSON report (`e2e.json` if unset). |
| `WGF_VISUALQA_FRAMES`, `WGF_VISUALQA_BRIEF`, `WGF_VISUALQA_VERDICT` | `scripts/wgf_visualqa/judge.py` | Given to a `command` visual-qa judge: the directory of staged frame copies, the judge brief, and where to write the verdict - the same values as the `{frames_dir}`, `{brief}`, `{verdict}` argv placeholders. |
| `WGF_LISTING_BRIEF`, `WGF_LISTING_OUTPUT` | `scripts/wgf_listing/copywriter.py` | Given to a `command` store copy writer: the brief (the facts, the claim vocabulary, the shape to produce) and where to write the JSON answer - the same values as the `{brief}` and `{output}` argv placeholders. |
| `WGF_PLAY_OUT`, `WGF_PLAY_CONFIG` | `scripts/wgf_playability/step.py`; read by `scripts/wgf_playability/bot.spec.ts` | Where the playability bot writes what it recorded (per viewport: JSON and frames), and its settings file (idle, acknowledgement and play windows, the goal metric). |
| `WGF_OBSERVE_CONFIG` | `scripts/wgf_publish/observe.py`; read by `scripts/wgf_publish/browser/observe.spec.ts` | The console observer's settings file: the console url, allowed origins, the authenticated-url regex, the login and observation windows, and where the state file and page records go (`wgf-publish.py observe`). |
| `WGF_E2E_PORT` | not set; read by `scripts/wgf_sdk/e2e/playwright.config.ts` | The preview server port for the SDK browser e2e; `4461` when unset. |
| `WGF_GAME_CONFIG` | `scripts/wgf_verification/platform_builds.py` (each platform's build and its `collect-facts` / `evaluate-assertions`), `scripts/wgf_release/step.py` (each platform's `release:package --platform`); read by the template's `vite.config.ts` and `scripts/_shared.mjs` `readGameConfig` | The config one platform's bundle is built, measured and packaged against: `build/platforms/<id>/game.config.json` (relative to the checkout), naming that platform alone. Set only for a title with more than one target on template contract 1; unset, the template reads `game.config.yaml`. |
| `WGF_Y8_APP_ID`, `WGF_Y8_GAME_ID` | `scripts/wgf_sdk/e2e.py` (placeholder ids) | The Y8 build ids the template's build reads; the e2e sets test values so a Y8 build can be made. |
| `WGF_SCRIPTS` | `scripts/tests/test_release_module.py`; read by `scripts/tests/fixtures/release/fake-pnpm.py` | Where the Factory's `scripts/` is, for the release tests' fake `pnpm`. |
| `WGF_TEST_TESTS_DIR`, `WGF_TEST_DEV_LOG`, `WGF_TEST_DEV_MODE`, `WGF_TEST_CHILD_PID` | `scripts/tests/test_core_agents.py` | Plumbing between the AGENTS tests and the scripted developer they start (its behaviour, its log, its child-pid file). |

`WGF_GAME_CONFIG` is read by the *template's* `vite.config.ts` (build against another
config file). The Factory sets it only on the one command that builds, measures or packages
a platform's own bundle (above), never in its own environment; the golden harness removes it, with
`WGF_GAME_REPO` and `WGF_RESEARCH_LIVE`, from a golden run's environment
(`scripts/golden/harness.py`, `FOREIGN_ENV`), so a developer's shell cannot point a golden
run at anything but its own checkout.

## Tests

| Variable | Read by | Meaning |
|---|---|---|
| `WGF_LISTING_BROWSER`, `WGF_LISTING_REPO` | `scripts/tests/test_listing.py` | `WGF_LISTING_BROWSER=1` with `WGF_LISTING_REPO=<game checkout holding dist/ and node_modules/>` runs the real store-listing capture against that build in the game's own Chromium (`RealBuild`). Off: skipped, and a skip is not a pass. |

| Variable | Read by | Meaning | Default |
|---|---|---|---|
| `WGF_PUBLISH_BROWSER_TEST` | `test_publish_module`, `test_publish_executor`, `test_publish_observe` | `1` drives the fixture portal (`scripts/tests/fixtures/publish/portal.py`) with real headless Chromium through the publish module's console executor and the read-only console observer, with the test playing the person who logs in, in the pinned template's checkout. Contacts nothing but 127.0.0.1. | off |
| `WGF_GOLDEN` | `scripts/golden/testing.py` (via `test_golden_2d`, `test_golden_3d`) | `1` runs the 2D and 3D golden pipelines (minutes each). Otherwise the `2D GOLDEN` / `3D GOLDEN` categories are `SKIP`. | off |
| `WGF_GOLDEN_KEEP` | `scripts/golden/testing.py` | `1` keeps a golden run's work directory after the test. | off: removed |
| `WGF_GOLDEN_DIR` | `scripts/golden/harness.py` | Parent of a golden run's fresh work directory. | `/tmp` |
| `WGF_GOLDEN_TEMPLATE_REF` | `scripts/golden/harness.py` | Older spelling of `WGF_TEMPLATE_COMMIT` for the golden runs; used only when that is unset. | unset |
| `WGF_AJV` | `test_assets`, `test_discovery`, `test_init_module`, `test_verification`, `test_release_module`, `test_core_agents`, `test_develop_module`, `test_techplan_module` | `1` also validates emitted artifacts with ajv through `npx` (may download ajv-cli once). | off |
| `WGF_BLENDER_TEST` | `test_models` | `1` runs the real Blender builds (`RealBlender`): every shape and track, LODs and a convex proxy, determinism, the step building then reusing, and a byte-for-byte rebuild of `fixtures/models/hover-car.glb`. Needs the pinned series through `WGF_BLENDER` or PATH; skips with the reason otherwise. | off |
| `WGF_SKIP_AJV` | `test_core_contracts` (`=1`), `test_strategy` (any value) | Skip the ajv differential / ajv validation even when `npx` is available. | off: ajv runs when `npx` works |
| `WGF_TEMPLATE_RELEASE_TEST` | `test_core_release` | `1` runs the pinned template's real `release:package` / `release:manifest` on a copy of it. | off |

## The MV-4 evidence harness

Set by `scripts/mv4/session.py` for the browser side it copies into a scratch checkout
(`scripts/mv4/session.spec.ts`); never set by hand. They are evidence inputs, not switches: none
of them can change what class a measurement is recorded at - that is derived from the Playwright
project name, so no environment can turn an emulated run into a device result
([mv-4-plan.md](mv-4-plan.md)).

| Variable | Read by | Meaning | Default |
|---|---|---|---|
| `WGF_MV4_OUT` | `scripts/mv4/session.spec.ts` | Where each project writes its `session.json`. | `mv4-session` |
| `WGF_MV4_ARTIFACT` | `scripts/mv4/session.spec.ts` | What was measured: `release-package` or `fresh-build`. | empty |
| `WGF_MV4_ARTIFACT_SHA` | `scripts/mv4/session.spec.ts` | The sha256 of the bytes measured, recorded in every session. | empty |
| `WGF_MV4_SAMPLE_S` | `scripts/mv4/session.spec.ts` | Seconds of continuous play sampled for the frame statistics. | `20` |
| `WGF_MV4_ALLOW_HOSTS` | `scripts/mv4/session.spec.ts` | Comma-separated hosts the session may contact (`--allow-host`); every other external request is aborted and recorded. Each entry is a deliberate, recorded outward request - this is how the portal's own SDK is fetched from the portal's origin for criterion D. | empty: everything external is aborted |
| `WGF_TEMPLATE_SDK_TEST` | `test_sdk_module` | `1` runs the real `pnpm sdk:conformance` in the pinned template checkout (`wgflib.template`; never another revision) and checks the sdk-report names the pinned commit. | off |
| `WGF_LIVE_PROCESS_TEST` | `test_core_process` | `1` runs the pinned template's Playwright smoke through the process owner and checks no server survives. | off |
| `WGF_LIVE_AGENT` | `test_core_agents`, `test_live_loop` | `1` enables the live tests: `LiveReviewer` and the live loop (`golden.live`). They run the developer and reviewer `workspace/config/factory.yaml` documents, verbatim, and cost money. | off |
| `WGF_LIVE_REVIEWER_ARGV` | `test_core_agents` | JSON argv replacing the documented reviewer in `LiveReviewer`. | unset: the reviewer factory.yaml documents |
| `WGF_LIVE_VERDICT_FROM` | `test_core_agents` | `file` or `stdout`: how `LiveReviewer`'s reviewer returns its verdict. | the documented reviewer's (`stdout`) |
| `WGF_LIVE_TIMEOUT` | `test_core_agents` | Seconds `LiveReviewer`'s reviewer may take. | the documented reviewer's `timeout_seconds` |
| `WGF_LIVE_ENV_PASSTHROUGH` | `test_core_agents`, `golden.live` | Comma-separated names added to the live agents' `factory.agents.env_passthrough` - the host credential when it is an environment variable (`ANTHROPIC_API_KEY`). | unset: none |
| `WGF_LIVE_KEEP` | `test_core_agents`, `test_live_loop` | A directory to keep each live test's evidence in, under `<dir>/<test id>` (`.2`, `.3` ... on a rerun; never over an earlier run's). | unset: discarded |

`bin/wgf test-core` runs whatever these flags enable and lists every test they left skipped.
The release gate is `WGF_GOLDEN=1 bin/wgf test-core --strict`, which exits 4 if anything was
skipped.

## Organization (GitHub) - `scripts/wgf-org-setup.sh`

Secrets and variables the game repositories' pipelines read, created by that script with the
sentinel `__UNSET__` and filled by hand. The script is their inventory; its table holds each
one's description.

| Secrets | Variables |
|---|---|
| `WGF_CF_API_TOKEN` (develop preview deploy), `WGF_LIVE_OPT_IN` (`1` runs the live portal SDK validation suite; not a credential) | `WGF_CF_ACCOUNT_ID`, `WGF_CF_PROJECT_PREFIX` (default `wgf`), `WGF_Y8_APP_ID`, `WGF_Y8_GAME_ID`, `WGF_GAMEMONETIZE_GAME_ID` (public ids a build bakes in) |

CI never publishes a game to a portal, so **no portal credential belongs in CI or in the
organization**: publication is the Factory's `publish` group, behind a person's G6, in a
browser window where a person logs in live; no session is captured or kept anywhere
(`docs/publish-module.md`). The script only reconciles the names it manages and never deletes
one. The names it managed before - secrets `WGF_POKI_AUTH_JSON`,
`WGF_YANDEX_CONSOLE_SESSION`, `WGF_CRAZYGAMES_TOKEN`, `WGF_GAMEVUI_TOKEN`; variables
`WGF_POKI_GAME_ID`, `WGF_CRAZYGAMES_GAME_ID`, `WGF_GAMEVUI_GAME_ID`, `WGF_YANDEX_APP_ID` - are
read by no workflow; a person should delete them from an organization that still holds them.

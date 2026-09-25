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
| `WGF_GAME_REPO` | `scripts/wgf_sdk/step.py`, `scripts/wgf_verification/session.py` | The game checkout the `sdk` and `verify` steps work on, when the step's own parameter (`game_repo` / `repo_dir`) is not set. Checked before `factory.<step>` configuration. | unset: resolved from the step parameter, then config, then the checkouts directory |
| `WGF_RESEARCH_LIVE` | `scripts/wgf_discovery/step.py` | `1` makes the `research` step fetch the pages in `probes.yaml` during the run, like `live: true` on the step. | off: evidence snapshots only |
| `WGF_TEMPLATE_COMMIT` | `scripts/wgflib/template.py` | A deliberate override of the web-game-template commit in `workspace/config/template.lock.json`. Must be a full 40-hex sha. Used to validate a new pin before moving the lock. | the lock's `commit` |
| `WGF_TEMPLATE_DIR` | `scripts/wgflib/template.py` | Offer an existing template checkout instead of the cache. Refused (`TemplateDrift`) unless its HEAD is exactly the expected commit; never moved. | unset: cache, then clone |
| `WGF_TEMPLATE_CACHE` | `scripts/wgflib/template.py` | Where pinned template checkouts are cached, one directory per sha. | `~/.cache/wgf/templates` |
| `WGF_HEARTBEAT_SECONDS` | `scripts/wgflib/procs.py` | Heartbeat interval for every owned child process (`STEP_PROGRESS`, `last_activity_at`). A positive number; anything else falls back to the default. | `15` |

Agent processes and the game code the Factory runs (develop checks, verify, sdk, release
packaging) do not see the Factory's environment: they get `scripts/wgflib/agentenv.py`'s
allowlist, which carries no `WGF_*` variable but the `WGF_PROC_*` tags, plus what
`factory.agents.env_passthrough` (agents) or `factory.agents.game_env_passthrough` (game
code) names. A `WGF_*` variable listed below as read by a step is read by the Factory's own
Python, not by its children.

## Set by the Factory for its children

| Variable | Set by | Meaning |
|---|---|---|
| `WGF_PROC_TAG` | `scripts/wgflib/procs.py` (also named in `wgflib/workflow/api.py`) | A unique tag in each owned child's environment. Environment survives `setsid()` and double-forks, so the whole tree - including a detached daemon - can be found and terminated. |
| `WGF_PROC_LINEAGE` | `scripts/wgflib/procs.py` | The chain of tags of the owned processes above this one, so a nested owned tree is also found from its ancestor's tag. |
| `WGF_PROC_RUN` | `scripts/wgflib/procs.py` (bound by `wgflib/workflow/engine.py`) | The workflow runs whose steps own this tree, outermost first, each `<run-id>@<12 hex digits of the run store's directory>`. Set only on children started while a step executes; a caller-supplied value is replaced. Resuming or cancelling a run whose driver died (SIGKILL) ends every process still naming it (Linux; docs/agent-lifecycle.md#sigkill-recovery). |
| `WGF_REVIEW_REPO`, `WGF_REVIEW_VERDICT`, `WGF_REVIEW_BRIEF`, `WGF_REVIEW_COMMIT` | `scripts/wgf_review/step.py` | Given to a `command` reviewer: the checkout (read-only), where to write the verdict, the brief, and the sha under review - the same values as the `{repo}`, `{verdict}`, `{brief}`, `{commit}` argv placeholders. |
| `WGF_E2E_PLATFORM`, `WGF_E2E_ENGINE`, `WGF_E2E_EXPECT`, `WGF_E2E_REPORT` | `scripts/wgf_sdk/e2e.py`; read by `scripts/wgf_sdk/e2e/smoke.spec.ts`, `playwright.config.ts` | One SDK browser e2e case: which portal and engine the build is for, what the smoke must observe, and where Playwright writes its JSON report (`e2e.json` if unset). |
| `WGF_E2E_PORT` | not set; read by `scripts/wgf_sdk/e2e/playwright.config.ts` | The preview server port for the SDK browser e2e; `4461` when unset. |
| `WGF_Y8_APP_ID`, `WGF_Y8_GAME_ID` | `scripts/wgf_sdk/e2e.py` (placeholder ids) | The Y8 build ids the template's build reads; the e2e sets test values so a Y8 build can be made. |
| `WGF_SCRIPTS` | `scripts/tests/test_release_module.py`; read by `scripts/tests/fixtures/release/fake-pnpm.py` | Where the Factory's `scripts/` is, for the release tests' fake `pnpm`. |
| `WGF_TEST_TESTS_DIR`, `WGF_TEST_DEV_LOG`, `WGF_TEST_DEV_MODE`, `WGF_TEST_CHILD_PID`, `WGF_TEST_LIVE_DEV_ARGV` | `scripts/tests/test_core_agents.py` | Plumbing between the AGENTS tests and the scripted developer they start (its behaviour, its log, its child-pid file, the live developer argv). |

`WGF_GAME_CONFIG` is read by the *template's* `vite.config.ts` (build against another
config file). The Factory never sets it; the golden harness removes it, with
`WGF_GAME_REPO` and `WGF_RESEARCH_LIVE`, from a golden run's environment
(`scripts/golden/harness.py`, `FOREIGN_ENV`), so a developer's shell cannot point a golden
run at anything but its own checkout.

## Tests

| Variable | Read by | Meaning | Default |
|---|---|---|---|
| `WGF_GOLDEN` | `scripts/golden/testing.py` (via `test_golden_2d`, `test_golden_3d`) | `1` runs the 2D and 3D golden pipelines (minutes each). Otherwise the `2D GOLDEN` / `3D GOLDEN` categories are `SKIP`. | off |
| `WGF_GOLDEN_KEEP` | `scripts/golden/testing.py` | `1` keeps a golden run's work directory after the test. | off: removed |
| `WGF_GOLDEN_DIR` | `scripts/golden/harness.py` | Parent of a golden run's fresh work directory. | `/tmp` |
| `WGF_GOLDEN_TEMPLATE_REF` | `scripts/golden/harness.py` | Older spelling of `WGF_TEMPLATE_COMMIT` for the golden runs; used only when that is unset. | unset |
| `WGF_AJV` | `test_assets`, `test_discovery`, `test_init_module`, `test_verification`, `test_release_module`, `test_core_agents`, `test_develop_module`, `test_techplan_module` | `1` also validates emitted artifacts with ajv through `npx` (may download ajv-cli once). | off |
| `WGF_SKIP_AJV` | `test_core_contracts` (`=1`), `test_strategy` (any value) | Skip the ajv differential / ajv validation even when `npx` is available. | off: ajv runs when `npx` works |
| `WGF_TEMPLATE_RELEASE_TEST` | `test_core_release` | `1` runs the pinned template's real `release:package` / `release:manifest` on a copy of it. | off |
| `WGF_TEMPLATE_SDK_TEST` | `test_sdk_module` | `1` runs the real `pnpm sdk:conformance` in the pinned template checkout (`wgflib.template`; never another revision) and checks the sdk-report names the pinned commit. | off |
| `WGF_LIVE_PROCESS_TEST` | `test_core_process` | `1` runs the pinned template's Playwright smoke through the process owner and checks no server survives. | off |
| `WGF_LIVE_AGENT` | `test_core_agents` | `1` enables the live developer/reviewer tests (with the two argv variables below). | off |
| `WGF_LIVE_REVIEWER_ARGV` | `test_core_agents` | JSON argv of a real reviewer for the live tests. | unset: skipped |
| `WGF_LIVE_DEVELOPER_ARGV` | `test_core_agents` | JSON argv of a real developer for the live loop test. | unset: skipped |
| `WGF_LIVE_VERDICT_FROM` | `test_core_agents` | `file` or `stdout`: how the live reviewer returns its verdict. | `stdout` |
| `WGF_LIVE_TIMEOUT` | `test_core_agents` | Seconds a live agent may take. | `900` |
| `WGF_LIVE_KEEP` | `test_core_agents` | A directory to copy a live run's scratch (logs, verdicts, checkout) into. | unset: discarded |

`bin/wgf test-core` runs whatever these flags enable and lists every test they left skipped.
The release gate is `WGF_GOLDEN=1 bin/wgf test-core --strict`, which exits 4 if anything was
skipped.

## Organization (GitHub) - `scripts/wgf-org-setup.sh`

Secrets and variables the game repositories' pipelines read, created by that script with the
sentinel `__UNSET__` and filled by hand. The script is their inventory; its table holds each
one's description.

| Secrets | Variables |
|---|---|
| `WGF_CF_API_TOKEN`, `WGF_POKI_AUTH_JSON`, `WGF_YANDEX_CONSOLE_SESSION` (reserved), `WGF_CRAZYGAMES_TOKEN` (reserved), `WGF_GAMEVUI_TOKEN` (reserved) | `WGF_CF_ACCOUNT_ID`, `WGF_CF_PROJECT_PREFIX` (default `wgf`), `WGF_YANDEX_APP_ID`, `WGF_POKI_GAME_ID`, `WGF_CRAZYGAMES_GAME_ID`, `WGF_GAMEVUI_GAME_ID` |

# Claude capabilities

What an agent host can do inside the Factory at the Core v1 freeze. For each capability this
page says where it is implemented, what enforces it, which test proves it, and whether that
proof was run. It was audited against Claude Code **2.1.281** (`claude --version`), and it
is the only place outside `workspace/config/` that names the host. `core/` never does.

Two layers, and they are kept apart on purpose:

- **Factory-side** enforcement lives in `scripts/`. It holds whatever the agent does:
  process ownership, timeouts, the keyed commit, reviewer isolation by fingerprint, the
  developer's boundary (an allowlisted environment, the Factory's guarded paths
  fingerprinted around it, hardened git, a commit of only the paths it may write, a
  protected `package.json`), verdict strictness, commit lineage.
- **Agent-host** enforcement is whatever the configured argv asks the host for: tool set,
  permission rules, permission mode. It is defence in depth. No Factory guarantee depends on
  it.

Status values:

| Status | Meaning |
|---|---|
| `VERIFIED` | The named test ran green in this audit, with the command given |
| `VERIFIED_LIVE` | Exercised with a real `claude` process through the real path, with evidence below |
| `UNVERIFIED_EXTERNAL` | Needs something outside this repository: credentials, the sibling template, browsers, portals |
| `BROKEN` | Does not work as documented |

## Summary

| Status | Count (of 28 rows) |
|---|---|
| VERIFIED_LIVE | 16 |
| VERIFIED | 11 (three added with the developer-boundary hardening after 1.1.0, released in 2.0.0; not yet run live) |
| UNVERIFIED_EXTERNAL | 1: browser testing against a real template. The portal side of release is also external; it is noted in its row |
| BROKEN | 0 open. Two found and fixed: the shipped config narrowed the reviewer's guarded paths (P1), and the opt-in `LiveReviewer` test could not pass against a competent host (P2) |

Commands run for `VERIFIED`, all green, from `scripts/tests/` with `python3 -m unittest <module>`
(test counts and the `file:line` references in the table below are as of that audit, made after 1.1.0;
the code has moved since - search by the names given):
`test_core_agents` (31 tests, 3 opt-in skips), `test_develop_module`, `test_core_workflow`,
`test_core_process`, `test_core_security` (74), `test_core_persistence`,
`test_core_contracts`, `test_core_lineage`, `test_core_verify`, `test_core_release`,
`test_release_module`, `test_techplan_module`, `test_sdk_module`, `test_sdk_integration`,
`test_verification`, `test_workflow_cli`, `test_workflow_engine`, `test_workflow_contracts`,
`test_workflow_definition`, `test_init_module`, `test_assets`, `test_design_module`,
`test_state` and `test_hashing`. Every skip is opt-in: ajv, the live agent, the sibling
template, or Playwright. The golden runs were not run in this audit. They belong to the
golden-run work and use port 4173.

## Capability inventory

| Capability | Where | Enforced by | Proof | Status |
|---|---|---|---|---|
| Developer agent (unattended) | `scripts/wgf_develop/developers.py:71` `CommandDeveloper`; argv placeholders `:80-82`; `step.py:151` | Factory: argv run through `procs` in the checkout; outcome from the exit status | `test_core_agents.AgentLoop.*`; live: `LiveDeveloperAndReviewer` | VERIFIED_LIVE |
| Developer via handoff | `developers.py:49` `HandoffDeveloper`; `step.py:153` | Factory: `WAITING_FOR_HUMAN` until `--decision done` | `test_develop_module` (handoff cases) | VERIFIED |
| Reviewer agent | `scripts/wgf_review/step.py:61`; argv `:150-154`; `procs.run` `:169` | Factory | `test_core_agents.AgentLoop.test_developer_reviewer_request_changes_developer_reviewer_approve`; live: both live classes | VERIFIED_LIVE |
| Read-only reviewer | Factory: `isolation.take/diff/restore` (`scripts/wgflib/isolation.py`, called from `wgf_review/step.py`). Host: `--safe-mode --tools Read,Glob,Grep,Bash --permission-mode dontAsk` | Both, independently | Factory: `AgentLoop.test_a_reviewer_editing_*`, `test_a_reviewer_committing_*`, `test_core_security.ReviewerIsolation` (fake reviewers that do write). Host: probe (c) below | VERIFIED_LIVE |
| Request-changes workflow | `wgf_review/step.py:240-243` (FAILED, route `request-changes`); routing is data in `core/workflows/new-game.workflow.yaml` (`review.on`) | Engine `_route` (`wgflib/workflow/engine.py:909`) | `AgentLoop.test_developer_reviewer_request_changes_developer_reviewer_approve`, `Registration.test_the_workflow_routes_request_changes_back_to_develop`; live run below | VERIFIED_LIVE |
| Unattended Claude execution | argv in `workspace/config/factory.yaml` (commented `developer:` / `reviewer:`); stdin is `/dev/null` (`procs`) | Host: `-p`, `--permission-mode dontAsk` (no prompts); Factory: stdin closed, timeouts | `ShippedConfig.test_the_commented_agent_host_examples_are_valid_config`; live run below | VERIFIED_LIVE |
| Scoped permissions | Developer `Edit(./**)`, `Write(./**)`, `Bash(pnpm *)`, read-only git; reviewer reads plus `git diff/log/show` | Host permission rules | Probes (c) and (d) below: a write outside the checkout was refused and a write inside was allowed; five Bash writes refused | VERIFIED_LIVE |
| Agent environment | `scripts/wgflib/agentenv.py` `scrubbed`; developer `wgf_develop/developers.py` (`env=ExactEnv(...)`), reviewer `wgf_review/step.py` (`agentenv.scrubbed`); `factory.agents.env_passthrough`. Game code the Factory runs (develop checks, verify, sdk conformance, release packaging): `agentenv.game_code_env` plus `factory.agents.game_env_passthrough`, never `env_passthrough` | Factory: an allowlist, never the Factory's environment; names that say secret dropped even under an allowed prefix | `test_core_security.AgentEnvironment` (a planted `WGF_TEST_SECRET_TOKEN`, `GH_TOKEN`, `npm_config__authToken` invisible to a real developer and reviewer process); `test_core_security.GameCodeEnvironment` (the same secret and the agents' passthrough invisible to a develop check, a verification command, `pnpm sdk:conformance` and `release:package`) | VERIFIED |
| Developer write boundary | `wgf_develop/step.py` `_Guard`: `factory.review.guarded_paths` fingerprinted before the developer, compared after it and after the checks (`wgflib/isolation.py` `take_guarded`/`restore_guarded`) | Factory, whatever `Bash(pnpm *)` admits | `test_core_security.DeveloperBoundary.test_a_guarded_factory_path_written_by_the_developer_is_detected_and_restored`, `test_a_guarded_path_written_by_a_check_is_caught_too` | VERIFIED |
| Development commit scope | `wgf_develop/scope.py` (`writable_paths`; hidden paths and instruction files refused), `repository.py` `commit_paths` (never `add --all`); `checks.py` `package_findings` (`package.json` field by field, lockfile only with an allowed dependency change); `brief.py` `PROTECTED_PATHS` (+ `package.json`, `tsconfig.json`, `pnpm-lock.yaml`) | Factory | `DeveloperBoundary.test_agent_host_settings_and_instruction_files_are_refused` (`.claude/settings.json`, `CLAUDE.md`, `.github/`, `.husky/`), `test_a_package_json_script_rewrite_is_caught`, `test_a_tsconfig_change_is_caught`, `test_a_dependency_from_a_path_or_url_is_refused`; `test_develop_module.PackageAndScope` | VERIFIED |
| Tool / command restrictions | `--tools` (which tools exist), `--allowedTools`, `--disallowedTools` | Host. In the Factory, only the reviewer fingerprint catches a tool that wrote | Probe (c): the init event lists `tools: [Bash, Glob, Grep, Read]`, and a `Write` call fails with "No such tool available" | VERIFIED_LIVE |
| Git safety restrictions | Host: deny `git commit/push/reset/checkout/.../config/remote`, `git * --output*`. Factory: the Factory commits (`wgf_develop/step.py`, keyed, `commit_paths`); every Factory git call - the reviewer's and, since 2.0.0, the developer's commit path too (`wgf_develop/repository.py` `GitRepo`) - is hardened (`scripts/wgflib/gitsafe.py` `hardened`): git dir pinned before the developer runs, no hooks, fsmonitor, signing or filter drivers; a reviewer commit is detected and undone | Both | Probe (c2): `git diff … --output=` was denied by the explicit rule and `git commit` was denied. Factory: `AgentLoop.test_a_reviewer_committing_is_rejected_and_head_restored`, `test_core_security.ReviewerIsolation.test_config_the_reviewer_writes_runs_no_command_in_the_factory`, `CommitsAfterReview`, `DeveloperBoundary.test_a_planted_core_worktree_*`, `test_a_planted_clean_filter_never_runs`, `test_a_planted_hook_and_fsmonitor_never_run` | VERIFIED_LIVE (host); VERIFIED (developer-side hardening) |
| Isolated game checkout | `wgf_develop/settings.py:115` and `wgf_review/settings.py:120` → `wgflib.paths.checkout_path`; the review's verdict and brief must be outside the checkout (`wgf_review/step.py:126-130`) | Factory | `test_core_security.HostileIdentifiers`, `test_core_persistence.HostileIdentifiers`; live: the brief was read from the run directory, and the verdict was saved there | VERIFIED_LIVE |
| Agent retries | Engine retry policy (`engine.py:577-579,640`); developer failure retryable (`developers.py:92-101`); reviewer timeout, idle and crash retryable (`wgf_review/step.py:248-266`) | Factory | `AgentLoop.test_a_developer_failure_is_retried_and_the_loop_recovers`, `test_an_exhausted_retry_budget_fails_the_run`, `test_a_crashing_reviewer_is_retried_then_fails_the_run`, `test_core_workflow.Retry` | VERIFIED |
| Reviewer approval | `wgf_review/step.py:238-239`; strict verdict `verdict.py:60` | Factory | `AgentLoop.test_an_approving_reviewer_runs_once_and_the_run_completes`, `VerdictContract`; live visit 2 approve | VERIFIED_LIVE |
| Reviewer rejection | `step.py:240-243`; malformed verdicts `step.py:226-234` | Factory | `AgentLoop.test_malformed_verdicts_are_rejected_and_never_retried`, `test_a_reviewer_that_always_requests_changes_is_stopped_by_its_route_limit`; live visit 1 request-changes | VERIFIED_LIVE |
| Developer retry after review | `wgf_develop/step.py:110-113` (blockers carried only for this HEAD); brief "Fix first: blockers from code review" (`brief.py:361-366`) | Factory | `AgentLoop.test_developer_reviewer_request_changes_developer_reviewer_approve` (brief carries the blocker); live: the host fixed all 4 blockers on visit 2 | VERIFIED_LIVE |
| Resume / pause / cancel | `engine.py:171` (resume), `:399,544` (pause), `:427,523-533` (cancel); cancel ends a running child through `procs.bound` should_stop | Factory | `test_core_workflow.Resume`, `StaleRunResume`, `Pause`, `Cancel.test_cancel_terminates_a_running_child_process_and_is_not_retried`, `test_core_process.InsideAWorkflowStep.test_cancel_from_another_thread_ends_the_tree_and_the_step` | VERIFIED |
| Heartbeats / status | `procs.run` events (`scripts/wgflib/procs.py:715`); `engine.py:738-754` `STEP_PROGRESS`; liveness `wgflib/workflow/api.py:212`; `wgf status` (`scripts/wgf.py:372`) | Factory | `test_core_process.InsideAWorkflowStep.test_heartbeat_and_liveness_reach_the_step_state`, `test_core_workflow.LivenessDerivation`, `StatusCommand`; live: `spawned`/`exited` events for `claude` in `events.jsonl` | VERIFIED_LIVE |
| Timeout handling | `developers.py:83-97`; `wgf_review/step.py:255-262`; `procs.run(timeout=, idle_timeout=)` | Factory. Host `--max-turns` / `--max-budget-usd` sit under it | `AgentLoop.test_a_developer_timeout_fails_the_step_and_is_retried`, `test_a_reviewer_timeout_is_retried_and_its_tree_is_killed`, `test_a_silent_reviewer_hits_the_idle_timeout`, `test_core_process.IsEnded` | VERIFIED |
| Process cleanup | `procs.py:255` `terminate_tree`, `:319` subreaper, `:430` signal cleanup (installed by `wgf.py:559,577`) | Factory | `test_core_process` (27), `test_core_security.ReviewerLeftovers`, `test_core_process.EveryChildGoesThroughProcs`; live: `killed_pids: []` on both reviews, and no `claude` left running | VERIFIED |
| Evidence collection | Reviewer: `<run>/review/<step>-<visit>-<attempt>.{brief.md,log,verdict.json}` (`wgf_review/step.py`; `<step>` is `review` or `sdk-review`); `review-report` on every executed outcome. Developer: the whole transcript at `<run>/develop/<visit>-<attempt>.log` (`wgf_develop/developers.py`, `log_path=`), outside the checkout; `docs/development/checks.json` records the checks, including `isolation` and `commit-scope` refusals | Factory | `AgentLoop.*` (`assert_valid` on every report); `AgentLoop.test_an_approving_reviewer_runs_once_and_the_run_completes` (the developer transcript); live: logs and verdicts kept | VERIFIED_LIVE (reviewer); VERIFIED (developer transcript) |
| Structured agent reports | Developer: `docs/development/report.json` → `prototype-report` (`wgf_develop/checks.py` `read_report`, `report.py`); reviewer: verdict JSON (`verdict.py`), stdout extraction (`verdict.py:42`) | Factory: schema plus strict contract | `test_develop_module`, `VerdictContract`, `AgentLoop.test_a_sandboxed_reviewer_can_answer_on_stdout`; live: Haiku's stdout verdicts parsed (fenced JSON) | VERIFIED_LIVE |
| Commit lineage | Develop keyed commit (`Wgf-Develop-Key`, `step.py:122,175`); review pins HEAD == its subject's commit - the prototype-report's for `review`, the sdk-report's for `sdk-review` (`wgf_review/step.py`, `with: subject`); `wgf_release/lineage.py:70,82`; `wgf_verification/lineage.py` | Factory | `test_core_lineage.CommitLineage`, `test_core_release.Lineage`, `test_core_verify.WrongCommit`; live: `reviewed_commit` equals each `prototype-report` commit | VERIFIED_LIVE |
| SDK integration | `scripts/wgf_sdk/step.py:222`; commits on the reviewed commit (`wgf_sdk/commit.py:176`) | Factory | `test_sdk_module`, `test_sdk_integration` (real-template case skipped: no sibling template) | VERIFIED |
| Browser testing | `wgf_verification` recorded session / Playwright suites; `wgf_sdk/e2e.py:186` | Factory runs the repository's Playwright | Opt-in only: `test_core_process.LiveTemplateSmoke` (`WGF_LIVE_PROCESS_TEST=1`), `test_sdk_module.AgainstTheRealTemplate`. Not run here: they need the sibling template plus browsers, and they share port 4173 with the golden runs. Offline logic: `test_verification` (recorded-session cases), `test_core_verify.FailedBrowserTest` | UNVERIFIED_EXTERNAL (the offline logic is VERIFIED) |
| Verify | `scripts/wgf_verification/step.py:42` | Factory: evidence statuses, `PASS_MOCK` never promoted | `test_core_verify` (22), `test_verification` (43) | VERIFIED |
| Release | `scripts/wgf_release/step.py:111`; review status `lineage.py:101` | Factory: refuses without passing verify, lineage, clean tree, a passed G4 (`g4-not-passed`), and a review approving the shipped sdk commit (`unreviewed` unless `factory.release.allow_unreviewed`; `review-commit-mismatch`) | `test_core_release` (33), `test_release_module` (15). Portal publish and QA are behind G6 and human, so `BLOCKED_EXTERNAL` | VERIFIED (drafting). Portal side: UNVERIFIED_EXTERNAL |

## The verified argvs

The argvs are commented in `workspace/config/factory.yaml`, and
`ShippedConfig.test_the_commented_agent_host_examples_are_valid_config` checks that they
load. The active defaults stay `developer: handoff` and `reviewer: none`
(`ShippedConfig.test_the_shipped_defaults_run_no_agent_host`). Every flag was checked
against `claude --help` for 2.1.281, and every flag appears in a live run below.
`--max-turns` is accepted but not listed in `--help`.

| Flag | Developer | Reviewer | Why |
|---|---|---|---|
| `-p "{prompt}"` | ✓ | ✓ | headless; the Factory's prompt |
| `--setting-sources project` | ✓ | | the operator's personal allow rules and hooks do not widen the session |
| `--safe-mode` | | ✓ | no hooks, plugins, MCP or CLAUDE.md, so nothing the developer committed runs in or instructs the reviewer |
| `--strict-mcp-config` | ✓ | ✓ | no MCP servers (the opt-in self-playtest block below: only its listed file) |
| `--tools` | `Read,Edit,Write,Glob,Grep,Bash` | `Read,Glob,Grep,Bash` | tools outside the set do not exist |
| `--allowedTools` | reads, `Edit(./**)`, `Write(./**)`, `Bash(pnpm *)`, read-only git | reads, `Bash(git diff/log/show *)` | pre-approved without a prompt |
| `--disallowedTools` | network tools; git that moves history, refs or config; `git * --output*` | `Edit,Write,NotebookEdit`, network tools, `git * --output*` | deny beats allow |
| `--permission-mode dontAsk` | ✓ | ✓ | anything not pre-approved is refused, never prompted |
| `--output-format` | `stream-json --verbose` | `text` | the developer's output keeps the idle timer honest. The reviewer's stdout must end with the bare or fenced verdict, and `json`/`stream-json` would wrap it and fail as `malformed-verdict` |
| `--max-turns`, `--max-budget-usd` | ✓ | ✓ | the host's own bound, under the Factory's timeouts |
| `--no-session-persistence` | ✓ | ✓ | no session files per run |

Configuration consequences:

- In text mode the reviewer prints nothing until it exits. Its example therefore sets
  `idle_timeout_seconds: null`. The module default of 600 s would end a long, silent review.
- `Bash(pnpm *)` also admits `pnpm exec` and `pnpm dlx`, which is arbitrary code in the
  checkout. The host rules scope files, not the network or `$HOME`. What the Factory holds
  regardless (docs/development-module.md, "The developer's boundary"): the environment is
  an allowlist, the Factory's guarded paths are fingerprinted and restored, the Factory's
  git runs nothing the checkout's config names, and only `writable_paths` are committed.
  `$HOME` and the network stay unwatched: wrap the argv in an OS sandbox for those.
- The agent host's credential must be named in `factory.agents.env_passthrough` if the
  host authenticates by an environment variable (`ANTHROPIC_API_KEY`,
  `CLAUDE_CODE_OAUTH_TOKEN`); a CLI logged in with `claude login` reads its credentials
  under `HOME`, which is always passed.

### Opt-in: a developer that playtests its own build (F6)

A second commented developer block sits under `--- opt-in: self-playtest` in
`workspace/config/factory.yaml`, together with `self_playtest: true`. It is the verified
developer argv above plus:

| Flag or setting | Value | Why |
|---|---|---|
| `--mcp-config` | `{factory}/workspace/config/mcp-playwright-localhost.json` | one Playwright MCP server: `@playwright/mcp@0.0.82` (exact pin), `--headless`, `--isolated` (no profile on disk), `--allowed-origins http://localhost:4173;http://127.0.0.1:4173`, `--output-dir /tmp/wgf-playwright-mcp` (snapshots never land in the checkout, whose hidden paths the development commit refuses) |
| `--strict-mcp-config` | kept | now means *only the listed file*, not "no MCP servers" |
| `--plugin-dir` | `{factory}/claude-web-game-plugin` | the craft skills (game-feel, core-loop, web-performance, ...) |
| `--tools` / `--allowedTools` | adds `Skill`, and `mcp__playwright` | the only additions; `Edit(./**)` / `Write(./**)` and every deny are unchanged |
| `self_playtest: true` | develop setting | the brief gains "Playtest your build": `pnpm build`, `pnpm preview --port 4173 --strictPort`, play every required aspect against the minimum feedback bar, fix, stop the server |
| `{factory}` | argv placeholder (`scripts/wgf_develop/developers.py`) | the Factory root. The developer's cwd is the checkout, and both files live in the guarded Factory tree, outside anything the developer may edit |
| `guarded_paths` | `factory.review.guarded_paths` includes `claude-web-game-plugin` | the skills it loads are fingerprinted around the developer like the rest of the Factory: a changed skill is undone and fails the step |
| `env_passthrough` | `factory.agents.env_passthrough` | the developer's environment is an allowlist: the host's credential must be named there, as for the verified developer above |

The rest of the security model is unchanged:
- **Browser.** It is limited to the local preview origins. The playtest is the developer's own
  check, not evidence: verification still plays the build independently.
- **Developer process.** It is still not network-guarded (pnpm needs the registry). The
  sandbox note above applies unchanged.

**Status: VERIFIED offline, UNVERIFIED live.**
- Every flag exists in `claude --help` for 2.1.282 and in `@playwright/mcp@0.0.82 --help`.
- `ShippedConfig` checks that the block loads, keeps `--strict-mcp-config`, points at files
  that exist inside the Factory, keeps edits scoped to the checkout, and that the MCP file
  allows only localhost at an exact version, with its output directory outside the
  checkout and the Factory.
- No live developer run with the browser has been made yet.

### Opt-in: the design agent (F4)

`factory.design.author: agent` has an agent host improve the archetype's design draft
(`scripts/wgf_design/agent.py`); a commented, read-only host argv is in `factory.yaml`
(`design.agent`). What the Factory enforces: the host runs through `wgflib.procs` (timeout,
idle timeout, whole-tree cleanup), with the same allowlisted environment as the developer and
the reviewer (`agentenv.scrubbed` plus `factory.agents.env_passthrough`); its draft is judged
by the unchanged design checks (shape, `finalize`, buildability, consistency), never by the
agent. Tests: `test_design_agent` (including
`test_the_host_gets_the_allowlisted_agent_environment`). **Status: VERIFIED offline,
UNVERIFIED live** - no live design-agent run has been made.

## Live evidence

**2.0.0 (2026-09-26).** Before the 2.0.0 tag the live suites were run again, against the
allowlisted agent environment:
- the host authenticated with an empty `factory.agents.env_passthrough`, since its login lives
  under `HOME` or in the proxy variables the allowlist keeps;
- `LiveDeveloperAndReviewer` passed 3/3, through review and sdk-review to COMPLETED;
- `LiveReviewer` passed 2/3, the third holding a design-fidelity finding against the stub.

The run found and fixed a verdict-contract defect with whole-build findings. Details:
[v2-release.md](v2-release.md#pre-publish-checks-2026-09-26). The 1.1.x record follows.

The CLI is Claude Code 2.1.281, authenticated. It made about 21 invocations, all with
`--model haiku` (`claude-haiku-4-5-20251001`): 7 direct probes (US$0.01-0.05 each) and 14
from engine runs. The total was well under US$2. No process was left running: every review
recorded `killed_pids: []`.

**(a)+(b) Live developer and live reviewer through the real engine.**
`test_core_agents.LiveDeveloperAndReviewer` drives the real `WorkflowAPI`/`WorkflowEngine` on
the shipped `new-game` workflow, with the real `develop` and `review` steps. Only the
developer's prompt was custom and haiku-sized. The reviewer used `{prompt}`, plus
`--append-system-prompt` saying that the placeholder game files are not under review.

```bash
cd scripts/tests
export WGF_LIVE_DEVELOPER_ARGV='["claude","-p","Read {brief}. If it contains a section headed '\''Fix first: blockers from code review'\'', fix exactly the blockers listed there ... Otherwise append this exact line to the end of src/game/app.ts ...: // live-smoke: edited by the developer agent . Do not commit, do not push ...", "--model","haiku","--setting-sources","project","--strict-mcp-config","--tools","Read,Edit,Write,Glob,Grep,Bash","--allowedTools","Read,Glob,Grep,Edit(./**),Write(./**),Bash(pnpm *),Bash(git status *),Bash(git diff *),Bash(git log *),Bash(git show *)","--disallowedTools","WebFetch,WebSearch,Bash(git commit *),...,Bash(git * --output*)","--permission-mode","dontAsk","--no-session-persistence","--output-format","stream-json","--verbose","--max-turns","15","--max-budget-usd","0.50"]'
export WGF_LIVE_REVIEWER_ARGV='["claude","-p","{prompt}","--model","haiku","--safe-mode","--strict-mcp-config","--tools","Read,Glob,Grep,Bash","--allowedTools","Read,Glob,Grep,Bash(git diff *),Bash(git log *),Bash(git show *)","--disallowedTools","Edit,Write,NotebookEdit,WebFetch,WebSearch,Bash(git * --output*),Bash(git *--output=*)","--permission-mode","dontAsk","--no-session-persistence","--output-format","text","--max-turns","30","--max-budget-usd","0.50","--append-system-prompt","This is a smoke-test repository. ..."]'
WGF_LIVE_AGENT=1 WGF_LIVE_TIMEOUT=600 python3 -m unittest test_core_agents.LiveDeveloperAndReviewer -v
# ... ok    Ran 1 test in 127.437s    OK
```

Run `new-game-20260924-101457-7c288e`, status `COMPLETED`:

```
develop 1 SUCCESS   claude (exec'd, pid 5012) 12.9 s  -> 58473b8  (+ "// live-smoke: edited by the developer agent" in src/game/app.ts)
review  1 FAILED  request-changes  claude pid 7659 49.9 s, isolation intact (33 paths)
          blockers: score-negative (src/game/score.ts:2), sdk-direct-call, incomplete-seam, missing-export
develop 2 SUCCESS   claude pid 15316 29.4 s -> c078f4b
          -  return lives - 1; // BUG: can go negative
          +  return Math.max(lives - 1, 0);          (and the other three blockers)
review  2 SUCCESS  approve  claude pid 23430 27.1 s, isolation intact, reviewed_commit c078f4b
sdk, verify, release  SUCCESS (placeholder steps)
commits carry Wgf-Develop-Key: <run>:develop:1 / :2 - the Factory committed, not the agent
```

The review verdicts arrived on stdout as fenced JSON with the full 40-character sha. They
were saved to `review/<visit>-1.verdict.json` and passed the strict contract.

**The existing `LiveReviewer` test** (scripted developer, live reviewer) was run with the same
reviewer argv. As shipped, it failed twice with `loop limit: develop has been entered 3
time(s)`, for two reasons. First, the scripted developer fixed the bug only when a blocker
had the id `score-underflow`. A live host names its own blockers (`score-negative`,
`score-negative-bug`), so the fix never happened. Second, the scripted game is a stub: an
empty seam, a direct `platform.showRewarded()`, and a missing export. Haiku kept requesting
changes for those even when the brief asked it to focus on `score.ts`, so "approves the fix"
could never hold. Both are fixed in `test_core_agents.py`. The developer now matches a
blocker by file as well as by id, and never reintroduces the bug. The test now asserts that
every verdict is trusted, that the first review names `src/game/score.ts`, and that no later
review does. The run may end `COMPLETED`, or `BLOCKED` at the loop limit with a final
request-changes. Re-run: `OK` (130 s). Run `new-game-20260924-103939-0724c5` has three
trusted request-changes reviews: `score-negative-bug` in the first, gone from the second and
third, with isolation intact on all three.

**(c) A reviewer that tries to write is refused by the host.** The reviewer flags were run
directly with `claude -p` in a scratch repository, with a prompt asking for seven chores
(`--output-format stream-json` so that every tool call is visible):

```
INIT tools: ['Bash', 'Glob', 'Grep', 'Read']  permissionMode: dontAsk
Read <run dir>/outside/brief.md             -> ok (a brief outside the cwd is readable)
Write src/notes.ts                          -> "No such tool available: Write"
Bash  cat > src/notes.ts <<EOF              -> denied (don't ask mode)
Bash  sed -i 's/a - b/a + b/' src/math.ts   -> denied
Bash  touch src/notes.ts                    -> denied
Bash  ls / cat / head / pwd                 -> allowed (read-only)
git status afterwards: clean; math.ts unchanged
```

A second probe (c2) asked for exactly three commands:

```
git log --oneline -1                  -> f7f23c8 init
git diff HEAD~0 --output=src/diff.txt -> "Permission to use Bash with command ... has been denied." (explicit deny rule)
git commit --allow-empty -m chore     -> denied (don't ask mode)
```

The Factory side does not depend on the host refusing. The fake-reviewer tests *do* write,
commit, edit `.gitignore`, hooks and Factory config, and every one is caught, failed as
`reviewer-isolation-violation` and restored: `test_core_agents.AgentLoop.test_a_reviewer_*`
(7 tests) and `test_core_security.ReviewerIsolation`. All ran green in this audit.

**(d) Developer scoping.** With the developer flags, `Write` to a path outside the checkout
was denied ("don't ask mode"). `Write src/inside.ts` inside the checkout succeeded. A Bash
redirect outside the checkout was denied. The model did not attempt `git commit` or
`git push` in that probe, so those developer deny rules were exercised only through the
reviewer probe (c2). The Factory-side guarantee is independent of them: the develop step
makes the one keyed commit and never pushes.

## Findings

**Fixed (P1, config).** `workspace/config/factory.yaml` set
`review.guarded_paths: [core/workflows, workspace/config]`. That silently undid the module
default that 561d1cf widened to `[core, scripts, bin, workspace/config]`. With the shipped
config, a reviewer could have rewritten Factory code (`scripts/`, `bin/`) or the gates and
contracts (`core/`) that judge the next review. The config now lists the default, and
`ShippedConfig.test_the_shipped_config_guards_at_least_the_module_defaults` fails against the
old line.

**Fixed (P2, opt-in test).** `test_core_agents.LiveReviewer` could not pass against a
competent live host. See "The existing `LiveReviewer` test" above. The deterministic
`AgentLoop` tests are unaffected: 31 ran, all green, with 3 opt-in skips.

**Fixed (adapters).** Generation produced no textual drift, but the binding did not cover
the Core v1 steps: no surface produced `review-report`, and `gameplay` and `release` did not
consume what their steps read. See each plugin's `CONFORMANCE.md` (fixed in binding 1.1.0; the binding is 1.2.0 since 2.0.0).

**Fixed (developer boundary, 2.0.0).** The developer ran with the Factory's whole
environment, its commit was `git add --all` through a git whose config the developer
could write (`core.worktree`, filter drivers), `package.json`'s `scripts` - what every later
check runs - were unprotected, and nothing watched the Factory's own paths around it. See
the three rows added above and docs/development-module.md. The live runs above predate it;
a live developer run with a scrubbed environment needs `env_passthrough` if the host
authenticates by variable.

**Gaps, reported rather than fixed (step modules):**

1. *Fixed: the developer's transcript is kept.* It was reported here as not kept; it is
   written to `<run_dir>/develop/<visit>-<attempt>.log` (`scripts/wgf_develop/developers.py`,
   `log_path=` when the runner accepts it), and
   `AgentLoop.test_an_approving_reviewer_runs_once_and_the_run_completes` asserts it.
2. *Nothing records who wrote each commit.* `prototype-report` has no field naming the
   developer argv0 or its exit status, while `review-report.reviewer` does. That is additive
   and optional, and it belongs to the develop module's schema.
3. *Core does not say that the architect reviews.* `core/roles/roles.yaml` lists `architect`
   with `produces: [tech-plan]`. The machine does list `architect` as a contributor to
   `title:prototype`, and `wgf_review` records `architect` as the reviewer role. The binding
   now says so; the charter (`core/roles/architect.md`) and `roles.yaml` could follow.

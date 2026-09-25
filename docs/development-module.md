# Development Module

`scripts/wgf_develop` implements the `develop` step: it turns the game design into a
playable game **in the title's game repository**, checks it the way the repository's CI
will, commits it, and reports what it proved. It is the first real module behind the
[workflow module contract](workflow-module-contract.md); read that first.

It writes no game code here — this repository holds none — and it never clones, pushes,
creates a repository or implements a platform SDK.

## What it does

```
inputs ──► brief ──► developer ──► checks ──► commit ──► prototype-report
           docs/development/     conformance, install,   one per visit,
           brief.md + brief.json typecheck, lint, unit,  keyed
                                 build, smoke
```

| Input | Used for |
|---|---|
| `game-design` | core loop, controls, MVP / later tiers / out of scope, session targets, onboarding, screens, placements, art and audio direction; and its `build_spec`, MVP tier |
| `asset-manifest` | the assets the MVP loads, their source, status and license |
| `scaffold-record` | which repository to build in (`repository.name`) |
| `title-strategy` | `prototype_must_prove` and `kill_criteria`, which the report must list — optional |
| `tech-plan` | `dev_plan`: the prototype milestones and their tasks, with acceptance criteria and tests — optional (absent, the brief has no plan section) |
| `qa-report` | on a verify → develop loop, the blocking defects the brief says to fix first |
| `review-report` | on a review → develop loop, the reviewer's blockers the brief says to fix first — used only when it requests changes to the commit this visit starts from ([review-module.md](review-module.md)) |

The engine comes from the checkout's `game.config.yaml`: `pixijs` for 2D, `threejs` for 3D.
Anything else is refused — adding an engine is the tech plan's decision at G3.

## The brief

`docs/development/brief.md` is the whole interface between the Factory and whoever writes
the game, regenerated on every visit and committed with the code it asked for. It states:

- **Ground rules** — the engine and where it may be imported (`src/rendering/<engine>/`
  only); the template-owned paths a game may not edit (`packages/`, `game.config.yaml`,
  `.github/`, `scripts/`, the build and test configs, `package.json`, `tsconfig.json`,
  `pnpm-lock.yaml`) and the one exception - adding a dependency, as
  `allowed_package_changes` permits; the paths a developer may write
  (`writable_paths`), which are all the commit will hold; no portal SDK in game code; pause
  by reason; the `#hud` probe contract the release pipeline reads; strings via i18n.
- **Required systems** — boot, game state, scenes, input, core loop, mechanics,
  progression, UI, HUD, tutorial, game over, restart, asset loading, responsive layout,
  audio hooks — each with its acceptance line.
- **Scope** — the MVP verbatim, the tiers that are *not now*, and what is out of scope.
- **Build spec** — the design's `build_spec`, MVP tier only, every field: mechanics with
  their rules and starting tuning, controls, player goals, game states, screens, HUD,
  menus, tutorial, rewards and failure with their feedback, progression, difficulty curve
  and assist, session beats, monetization touchpoints, audio cues, responsive behaviour and
  visual identity. Entries of a later tier are dropped at any depth and named as left out on
  purpose. `sdk_touchpoints` are not carried (the sdk step wires them; the developer calls
  only the seam), nor `assets` (the asset manifest is what is delivered). The brief asks
  for tuning as data in one module, and treats every `feedback` as MVP, not polish
  (`core/craft/game-feel.md`). `brief.json` carries the same selection under `build_spec`.
- **The design, in full** — `docs/GDD.md`, game-design's `rendered_to`, written by
  `scripts/wgf_develop/gdd.py` in the section structure of `core/templates/gdd.md` (concept to
  open questions, with the MVP build spec in 10b). It pins the design's artifact id and
  content hash, is deterministic, and is written before the developer runs and again after,
  so a hand edit never survives into the visit's commit. The brief's Design section and the
  review brief point at it.
- **Development plan** — the approved tech plan's prototype milestones and their tasks in
  dependency order, each with its acceptance criteria, tests and assets. Production and
  hardening tasks are listed by id as later work. `brief.json`: `dev_plan`.
- **The integration seam** — provided by the Factory, not written by the developer
  (`scripts/wgf_develop/seam.py`, `wgflib.gameseam`). Before the developer runs, the step
  writes `src/game/integration.ts` (the `GameIntegration` interface the game calls for
  gameplay start/stop, rewarded and interstitial placements, analytics and saves) and
  `src/platform/integration.ts`, its wiring: `createGamePlatform()` and
  `createGameIntegration(game, platform, { audio, tracker })`, built only on the template's
  API (`createPlatform` with `platformOptions(primary)` and `virtual:platform-config`,
  `withAdBreak`, `Analytics`). The brief asks `src/main.ts` to get its platform and its seam
  from those two functions and never to call `createPlatform`. The SDK module later writes
  its integrated wiring over `src/platform/integration.ts` as a whole file - same exports -
  so neither main.ts nor any game call changes. This is how development stays out of SDK
  work. A file that already exists (after the SDK step, the integrated wiring) is left as
  it is.
- **Tests** — unit tests for the rules, and a browser smoke test that *plays*, with the
  verification contract stated up front: every Playwright test is tagged with the gameplay
  aspects it exercises (`@game-over @restart`), and the brief lists the aspects this build
  must prove - computed by `wgf_verification`'s own `required_aspects_for(design)`, so the
  brief and verification cannot disagree.
- **Report back** — `docs/development/report.json`: the developer's own account of each
  system, each MVP item, the placements, integration status, assets, scope deltas and
  known issues.
- **Why this is another iteration** — on a visit a loop brought back (`brief.json` `loop`),
  the step and route that did (`verify.fail`, `review.request-changes`,
  `sdk-review.request-changes`, `prototype-review.iterate`: the engine's
  `context.entered_by`) and how many passes that loop, and develop itself, have left before
  the run stops for a person (`context.visit_budget`, from the workflow's
  `max_visits_by_route`). Absent on a first visit (entered by `<step>.success`).

## Developers

| `developer.kind` | Who writes the game | On a failed check |
|---|---|---|
| `handoff` (default) | A person, or an agent-host session a person drives. The step returns `WAITING_FOR_HUMAN`; resume with `--decision done` (or `abandon`). | Waits again, with the failures in `checks.json` and in the next brief |
| `command` | A configured process, unattended — typically an agent host's non-interactive mode. `argv` gets `{brief}`, `{repo}`, `{key}`, `{prompt}`. | Retryable `FAILED`; the next attempt's brief carries the failure output |

`command` runs are bounded by `timeout_seconds` (wall clock) and, optionally,
`idle_timeout_seconds` (no output at all for that long — a hung agent, not a slow one).
Either is a retryable `FAILED`.

A `command` developer is a paid agent session per attempt. Loop limits bound how often the
work goes round before a person looks; the run's [budget](#budget) bounds what the whole run may
spend on those sessions.

The provider, if any, is named only in the installation's `factory.yaml`. The brief's
"Host skills" section recommends skills by area (`brief.DEFAULT_SKILLS`):
- this Factory's own plugin skills, pointers into `core/craft/`:
  - `craft`: `web-game-factory:game-feel`, `core-loop`, `web-performance`, `audio`;
  - `ui`: `web-game-factory:onboarding-ux`;
  - the engine's area: `web-game-factory:pixijs` or `threejs`;
- next to them, generic skills (the official PixiJS skills, a frontend-design skill).

The other engine's area is never recommended.
- **Configuring.** `develop.skills` merges over the defaults: an added area is kept, and an
  area set to `[]` is dropped. A value that is not a map of area to a list of names is refused.
- **Availability.** The plugin skills are available to a host that loads the plugin, as the
  opt-in self-playtest developer does with `--plugin-dir`.
- **Precedence.** The brief says plainly that the template wins wherever a skill assumes
  another layout.

## The developer's boundary

A `command` developer is an agent with the Factory user's file access; whatever the host's
own flags restrict, `pnpm *` alone is arbitrary code. What the Factory enforces itself,
whoever the developer is:

| Boundary | How | On a breach |
|---|---|---|
| **Environment** | The developer command starts with an allowlist (`wgflib/agentenv.py`): PATH, HOME, USER, LANG/LC_*, TERM, TMPDIR, SHELL, CI, the proxy variables, XDG_*, NODE_*, PNPM_*, npm_config_* - minus any name that says it is a secret - plus `factory.agents.env_passthrough` and procs' WGF_PROC_* tags. Never the Factory's own tokens | — |
| **The Factory's own paths** | `factory.review.guarded_paths` (default `core`, `scripts`, `bin`, `workspace/config` - the list the reviewer is held to) fingerprinted before the developer runs and compared after it and again after the checks, which run code it wrote (`wgflib/isolation.py`: `take_guarded`/`diff`/`restore_guarded`). The game checkout is not fingerprinted: writing it is the job | Restored, then `FAILED` not retryable (`BLOCKED` if it could not be restored); recorded as the `isolation` check in `checks.json`. The prototype-report schema has no checks field, so the artifact cannot carry it; no report is emitted for such a visit |
| **Git** | Every git command is `wgflib.gitsafe.hardened`: the git directory resolved when the step starts - before any developer - and the work tree are named on every command, so `core.worktree` or a replaced `.git` gitfile cannot aim the Factory's commit elsewhere; fsmonitor, hooks, signing (`gpg.program`) and every filter driver are neutralised; the environment has no GIT_* redirection. `factory.develop.git.allow_filters: true` keeps the repository's filters for a git-lfs repository and refuses any filter configuration that changed after the pin | A changed filter config under `allow_filters`: `FAILED`, nothing run |
| **`package.json`, `pnpm-lock.yaml`, `tsconfig.json`** | Protected. `package.json` is compared with the baseline commit's field by field: every field but `dependencies`/`devDependencies` must be unchanged (`scripts` above all - every later check runs them); in those two, only what `allowed_package_changes` permits (default: additions), each a registry version range, never a path, URL, git or `npm:` alias. The lockfile may change only together with an allowed dependency change. `tsconfig.json` may not change | A `conformance` finding: the checks fail, nothing is committed |
| **The commit** | Exactly the changed paths under `writable_paths` (default `src/`, `tests/`, `public/`, `docs/development/`, `index.html`), plus `package.json`/`pnpm-lock.yaml` as above - never `git add --all`. Whatever the list says, a hidden path (`.claude/`, `.github/`, `.husky/`, `.env`, an editor's settings) or an agent instruction file (a capitalised `*.md`: the instruction-file convention agent hosts read) is refused. The one exception is `docs/GDD.md` (`scope.FACTORY_RENDERED`, fixed, not configurable): the step renders it from game-design after the developer returns and before this check, so the committed file is always the Factory's rendering. Checked after the developer - before minutes of checks - and again before the commit | `FAILED` not retryable, recorded as the `commit-scope` check in `checks.json`. Nothing is committed, and nothing is silently left behind to sit under every later check |

Where the defaults come from: the template's layout, the brief (`docs/development/`), and
the golden replay developer (`scripts/golden/replay_developer.py`), which writes exactly
those paths plus an engine-package addition to `package.json` (`pixi.js`; `three` and
`@types/three`) and the lockfile `pnpm install` updates to match.

Not covered: anything the developer writes outside the checkout and the guarded paths
(`$HOME`, other repositories), and the network. Wrap the argv in an OS sandbox for those.
The develop checks (`pnpm install`, `typecheck`, `lint`, `test`, `build`, `smoke`) run code
the developer wrote - package.json scripts, tests, the Playwright webServer - so they get
the game-code environment, never the Factory's: `wgflib/agentenv.py` `game_code_env`: the agents' allowlist (PATH, HOME, USER, LANG/LC_*, TERM, TMPDIR, SHELL, CI, the proxy variables, XDG_*, NODE_*, PNPM_*, npm_config_*, PLAYWRIGHT_*, COREPACK_* - minus any name that says it is a secret) plus `factory.agents.game_env_passthrough`, with the refusing proxy and
`CI=1` layered on top as before. `game_env_passthrough` is deliberately separate from
`env_passthrough`: the agent host's credential never reaches game code. A registry
credential normally lives in `~/.npmrc` under HOME, which is passed; an installation whose
install step reads one from the environment names it in `game_env_passthrough`. The same
environment is used by verify, sdk and release for the game code they run.

## Checks

Run in this order; `conformance` cannot be switched off.

| Check | What |
|---|---|
| `install` | `pnpm install --frozen-lockfile`. A failure stops the rest |
| `conformance` | Static: engine imports only in `src/rendering/<engine>/`, no other engine, no portal SDK identifiers, ad APIs called only from `src/platform/`, `BootScene` replaced, the seam files as the Factory provided them and `src/main.ts` booting through them (`wgflib.gameseam`), template-owned paths unchanged since the visit began, `package.json` changed only by allowed dependency changes and the lockfile only with them, and `report.json` complete — every required system `done`, every MVP item and placement reported |
| `format` | `pnpm format` — optional |
| `typecheck`, `lint`, `unit`, `build` | the repository's own scripts, as CI runs them |
| `smoke` | `pnpm test:e2e`, behind a proxy that refuses every non-local request (`wgflib.netguard`): a portal build would otherwise load the portal's real SDK from its CDN - dev traffic to the portal, and a result that depends on it (a Poki build's own "makes no insecure requests" failed on Poki's http:// ad bridge). The game must boot and play with the SDK refused, as for an ad-blocker; the summary says what was refused. Skipped, and reported as skipped, only when no browser is installed |

## Idempotency

Each visit commits once, locally, with a `Wgf-Develop-Key: <run>:<step>:<visit>` trailer.
Re-executing a visit that already committed — a crash, a resume, `--run` — finds that
commit, skips development, re-runs the checks and reports the same commit. A new visit (a
verify → develop loop) is a new commit. Nothing is pushed: publishing a branch is the game
repository's CI, behind its own gates.

## The prototype report

What an automated step can honestly claim is narrow, and the report keeps to it:

- `playable_build` is recorded as a criterion with a **measured** value — the checks.
- Every `prototype_must_prove` question is `inconclusive`, and every kill criterion is
  recorded **unmeasured** with a note saying so. Development does not playtest.
- The single automated playtest session is `player_context: internal`.
- The recommendation is `iterate` — never `pass`. G4 needs first-time sessions.

Integration status and scope deltas come from the developer's report; MVP items reported
`cut` or `deferred` and placeholder assets become scope deltas automatically.

## Budget

Loop limits bound passes, not spend: `max_visits` is refilled by every resume, and a
route limit (`max_visits_by_route`) by a resume of the run it stopped - a person saying
"one more pass". With a `command` developer each attempt of each visit is a paid agent
session, so nothing there bounds a run. `factory.develop.budget` does:

```yaml
factory:
  develop:
    budget:
      max_sessions: 12          # command-developer sessions in the whole run
      max_cost: 60              # summed session cost, in the unit the host reports
      cost_from:
        jsonl_key: <key>        # read the cost from the transcript's JSON lines
```

Every key is optional; without `budget` there is none, as before. The installation's value
is snapshotted into the run's params when the run starts (`develop_budget`, recorded in
`WORKFLOW_STARTED` and corroborated on every resume), so a config change never reaches a
running run and an edit of `state.json` is refused. A value the Factory cannot act on (not a
positive number, an unknown key, `max_cost` without `cost_from`) refuses the run at start.

**Sessions** are counted from the run's event log, never from memory or state, so neither a
resume nor a crash gives one back. Before it spawns a command developer, develop emits a
`STEP_LOG` with `data.budget: developer-session` and - when a budget is set - reads it back
from `events.jsonl`; a session that cannot be shown on record is not started (`BLOCKED`).
When the sessions already recorded reach `max_sessions`, develop returns `BLOCKED` - not
retryable, no agent spawned - with `budget exhausted: N developer sessions used of N`. A
handoff developer is a person, not a session: nothing is counted. A visit that already
committed (a re-execution) spawns nothing and costs nothing.

**Cost** is installation-configured, because the Factory names no provider: `cost_from:
{jsonl_key: <key>}` reads the number under that key in the **last** JSON-object line of the
session's transcript (`<run_dir>/develop/<visit>-<attempt>.log`) that holds the key -
reading only what this session appended. After each session develop records a `STEP_LOG`
with `data.budget: developer-cost` and the cost; when the recorded total reaches `max_cost`,
the next session is refused like the session limit. A session with no readable cost (killed
by a timeout, a host or output mode that reports none) is counted as a session, recorded with
`known: false` and a warning, and left out of the sum - never guessed, never a failure. The
agent host's own per-session flag (a maximum spend per session) therefore remains the bound
on any single session; this is the bound on the run.

For the headless host in `workspace/config/factory.yaml`'s commented example, the key is
`total_cost_usd`: in `--output-format stream-json` the host's closing `result` line carries
it (checked against the CLI binary, 2.1.282, which sets `total_cost_usd` on the `type:
"result"` message; the host documents it as an estimate, not an invoice). A session the
Factory's timeout kills never writes that line: its cost is unknown.

**Raising** a budget is a person's act: `wgf resume <run-id> --budget-sessions N` and/or
`--budget-cost X` records a `BUDGET_RAISED` event (`decided_by`, `decided_at`) and resumes.
The effective limit is the largest of the snapshot and every raise a person recorded. It is
refused from inside a step's process tree (`decided_by: automation` - an agent does not raise
its own budget; the same rule as G4/G6/G7), for a run started without that limit, and for a
value that is not positive; a `BUDGET_RAISED` recorded by automation counts for nothing.

A raise counts only when the engine's own resume record corroborates it: the engine writes
the raise with a `resume_nonce` and the `WORKFLOW_RESUMED` right after it with the same one,
so a line appended to `events.jsonl` by anything else is ignored. Around every command
developer session the step compares the event log with what it was before the session: if
earlier lines changed, or a `BUDGET_RAISED` or `WORKFLOW_RESUMED` was appended (no resume can
happen while the step holds the run), the step fails, not retried, and records the forged
raises (`STEP_LOG` `data.budget: event-log-tampered`, `data.forged`) so no later visit
honours them. *Residual:* the log has no hash chain or secret. The containment is that the
run directory (`.factory/`) lies outside the developer's checkout and its host write scope;
a process that can write there undetected between sessions is outside this model.

## Configuration

```yaml
factory:
  steps:
    modules: [wgf_develop]
  checkouts: ..                 # where game repositories are: docs/checkouts.md
  develop:
    developer: {kind: handoff}  # or {kind: command, argv: [...], timeout_seconds: 5400}
    checks: [install, conformance, typecheck, lint, unit, build, smoke]
    check_timeout_seconds: 900
    commit: true
    build_url: null             # "https://{branch}.{name}.pages.dev"; {owner} {sha} {short_sha}
    author: {name: ..., email: ...}   # when the checkout has no git identity
    skills: {craft: [...], ui: [...]}   # merged over DEFAULT_SKILLS; [] drops an area
    self_playtest: false        # true: the brief asks the developer to play its own build
    writable_paths: [src/, tests/, public/, docs/development/, index.html]
    allowed_package_changes: {dependencies: [add], devDependencies: [add]}  # add|change|remove
    git: {allow_filters: false}       # true: commit through the repository's filters (git-lfs)
    budget:                           # optional; see Budget. Snapshotted per run
      max_sessions: 12
      max_cost: 60
      cost_from: {jsonl_key: <key>}
  agents:
    env_passthrough: []         # names (or PREFIX*) the developer's environment also carries
    game_env_passthrough: []    # names (or PREFIX*) the checks - game code - also carry
  review:
    guarded_paths: [core, scripts, bin, workspace/config]  # also fingerprinted around develop
```

`developer.argv` placeholders are `{brief}`, `{repo}`, `{key}`, `{prompt}` and `{factory}`,
the Factory root, for host files kept in the Factory rather than the checkout. The opt-in
self-playtest developer (F6) uses it for a localhost-only Playwright MCP config and this
Factory's plugin. The commented block is in `workspace/config/factory.yaml`, and the flags
and security notes are in [claude-capabilities.md](claude-capabilities.md).

## Tests

`scripts/tests/test_develop_module.py` — offline, with throwaway git repositories and a
fake process runner: every outcome in contract §7 the step can produce, both developers,
idempotency across re-execution and across visits, every conformance rule (and the
template's own files not tripping them), and the full `new-game` workflow through the real
engine with this module replacing the mock, the package.json comparison, the commit scope
and the boundary settings; the budget (`DevelopBudget`, `ReadCost`): sessions counted
across a resume, `BLOCKED` at the limit with nothing spawned, a person's raise taking effect
and one from inside a step refused, a cost summed from fake transcripts, an unknown cost
tolerated; and the brief's loop provenance. `WGF_AJV=1` adds an ajv validation of an emitted report
against the full schema.

`scripts/tests/test_core_security.py` (`DeveloperBoundary`, `AgentEnvironment`) attacks
the boundary through the real step: a planted `core.worktree`, a `filter.x.clean` that
writes a marker, hooks, fsmonitor and a signing program; a `scripts.test` rewrite; a
dependency from a path or URL; a lockfile changed alone; a `tsconfig.json` change;
`.claude/settings.json`, instruction files and `.github/` refused; a guarded Factory file
written by the developer, and by a check, detected and restored; a secret in the Factory's
environment invisible to the developer and the reviewer.

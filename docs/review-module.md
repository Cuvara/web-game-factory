# Review module

`scripts/wgf_review/` registers the `review` step type. After `develop` commits a build,
someone who did not write it reviews that commit. They **approve** it, or they **request
changes** and name blockers. A request for changes goes back to `develop`, and the next
brief starts with those blockers. The `sdk` step then commits the platform integration on
top of the approved commit - and that sdk commit, not develop's, is what verify checks and
release ships. So `new-game` reviews it too, with the same step type pointed at a different
subject (`sdk-review`). The loops are data in `core/workflows/new-game.workflow.yaml`. No
code decides them:

```yaml
- id: review
  type: review
  stage: title:prototype
  inputs: [prototype-report, game-design, scaffold-record]
  outputs: [review-report]
  on:
    request-changes: develop

- id: sdk-review
  type: review
  stage: title:prototype
  inputs: [sdk-report, prototype-report, game-design, scaffold-record]
  outputs: [review-report]
  with:
    subject: sdk-report
  on:
    request-changes: develop
```

```
develop ──commit P──► review(P) ──approve──► sdk ──commit S──► sdk-review(S) ──approve──► verify → G4 → release(S)
   ▲                     │                                        │
   └──request-changes────┴──────────────request-changes───────────┘
              (each bounded by its own route limit on develop: review.request-changes: 2,
               sdk-review.request-changes: 2, over the run)
```

### The subject: which commit is reviewed

`with: subject` names the artifact whose `build_ref.commit_sha` is the commit under review:

| `subject` | Commit reviewed | The change the brief shows | Also required |
|---|---|---|---|
| `prototype-report` (default) | develop's commit P | `review_baseline..P` from the committed `docs/development/brief.json`: the development visit's `baseline_commit`, except on the first production build after a greybox, where it is where the greybox started - the greybox is played, never reviewed, so the loop is part of the change | - |
| `sdk-report` | the sdk step's commit S (P itself when sdk had nothing to commit) | `P..S`, the integration sdk added; the brief says this is the commit that ships | `sdk-report` in the run |

Anything else is `FAILED`, not retryable. Every other rule is the same for both subjects:
the subject's commit must be the checkout's `HEAD` (after `sdk`, HEAD is the sdk commit),
the tree must be clean, the reviewer is fingerprinted, and the verdict must name the commit.

**Why `sdk-review` requests go to `develop`.** A blocker in the sdk commit is either in the
game (the seam the integration calls) or in the integration the Factory generated from the
template. The developer owns the first and can fix it; nothing can hand-edit the second,
which sdk regenerates on every visit. Routing to `develop` re-runs the whole existing loop -
develop (with the blockers leading its brief, since `reviewed_commit` is HEAD), review, sdk,
sdk-review - bounded by develop's `sdk-review.request-changes` limit, apart from review's. Routing to `sdk` would re-run the
same deterministic integration on the same commit and loop to the limit; routing to `verify`
would carry a rejected build on. Unrouted, it would fail the run - also safe, but it would
throw away a loop that already exists. A reviewer that never approves the integration stops
the run on its third request (`loop-limit`, `limit_key: sdk-review.request-changes`); a
person resuming grants that loop one more pass.

**Why a second review rather than trusting generated code.** The sdk integration is
generated from Factory templates, and could be treated as Factory-owned and verified only by
SDK conformance. But its commit also carries the game-specific wiring it plans from the
design, it is the tree that ships, and the release rule is simplest when it is one sentence:
*the newest review approved exactly the commit released*. See
[release-module.md](release-module.md).

## Outcomes

| Reviewer did | Step returns | Engine does |
|---|---|---|
| `approve`, checkout untouched | `SUCCESS` | continues: `review` to `sdk`, `sdk-review` to `verify` |
| `request-changes`, checkout untouched | `FAILED`, route `request-changes`, not retryable | routes to `develop` because the workflow says so |
| anything, and the [gate-gaming pre-check](#gate-gaming-pre-check) flagged a specialist commit | `FAILED`, route `request-changes`, not retryable: the flags are blockers, an approval included | routed like any request for changes; triage sends the flags to the specialist that made them |
| the pre-check could not read the change (git failed) | `BLOCKED` | a person looks: whether a gate was gamed is unknown, and unknown is never a pass |
| changed anything it may only read | `FAILED` `reviewer-isolation-violation`, not retryable. The checkout is restored | run `FAILED` |
| changed something that could not be put back | `BLOCKED` | a person looks |
| wrote a malformed verdict, or none | `FAILED` `malformed-verdict`, not retryable | run `FAILED` |
| timed out or went silent | `FAILED` `reviewer-timeout` / `reviewer-idle-timeout`, retryable. The process tree is ended | retried per policy, then run `FAILED` |
| exited non-zero | `FAILED` `reviewer-crashed`, retryable | retried per policy |
| could not start (bad argv) | `FAILED` `reviewer-not-started`, not retryable | run `FAILED` |
| no reviewer configured (`kind: none`) | `SUCCESS`, verdict **`skipped`** | continues. The report and message both say the build is unreviewed, and **release refuses it** (`unreviewed`) unless `factory.release.allow_unreviewed: true` |

Every executed review emits a `review-report`, including failed ones. A rejected review is
evidence.

**Why request-changes is `FAILED`.** An unrouted `SUCCESS` goes to the next step. If
request-changes were a `SUCCESS` with a route, a workflow that forgot to route it would
carry a rejected build into `sdk` and on toward release. As `FAILED` it fails closed:
unrouted, it fails the run. Verification's `fail` has the same shape for the same reason.
The engine needs nothing new. Routing a labelled `FAILED` is existing behaviour, and
develop's `max_visits_by_route` bounds the loop, one limit per reviewer. A reviewer that
never approves blocks the run on its third request with a `loop limit` message and a
structured `blocked_reason` naming its limit.

## Preconditions

The step refuses to review anything but exactly the commit its subject names - the commit
`develop` made, or with `subject: sdk-report` the one `sdk` made:

- the subject's `build_ref.commit_sha` must be the checkout's `HEAD`. If not: `FAILED`,
  not retryable.
- The checkout must be clean (`git status --porcelain --untracked-files=all`). If not:
  `BLOCKED`. There are two reasons. A review of a dirty tree is not a review of the commit.
  And the restore below is only exact when the tree equals `HEAD` beforehand.
- The verdict and brief paths must be outside the checkout. They go under
  `<run dir>/review/<step id>-<visit>-<attempt>.{verdict.json,brief.md,log}` - one set per
  review step, so `review` and `sdk-review` never overwrite each other's record.

## Isolation: enforced, not requested

The prompt tells the reviewer it is read-only. That request is not what protects the
checkout. The checkout is **fingerprinted** before and after the reviewer runs
(`scripts/wgflib/isolation.py` - in the kernel since the develop step fingerprints the same
guarded paths around its developer, see [development-module.md](development-module.md);
`scripts/wgf_review/isolation.py` only re-exports it). The fingerprint covers:

- `HEAD`, the branch it points at, that branch's ref, and the checkout's per-worktree refs
  (`refs/bisect/`, `refs/worktree/`, `refs/rewritten/`). This catches a reviewer that
  commits, resets or switches branches.
- `git status --porcelain=v1 -z --untracked-files=all --ignored=no`. This catches staged
  changes.
- The sha256 and exec bit of every tracked file and every untracked, non-ignored file.
- A fixed list of paths, hashed whatever git says about them. The list covers
  `package.json`, the lockfiles, `.npmrc`, `.gitignore`, `game.config.yaml`, the
  tsconfig/vite/vitest/playwright/eslint/prettier configs, `tests/`, `.github/` and
  `.husky/`. A reviewer that also edited `.gitignore` to hide its change is still caught.
- The repository config the checkout runs under (`config` in the common git directory),
  entry by entry. Other branches' `branch.<name>.*` sections are not guarded, and neither
  are the two keys `git worktree add` writes (`extensions.relativeWorktrees`,
  `core.repositoryformatversion`).
- The git metadata that changes what git or the next commit does: `config.worktree`, `hooks/`,
  `info/` (exclude, attributes), `objects/info/` (alternates, grafts), submodules' config
  and hooks, and in-progress operation state (`MERGE_HEAD`, `rebase-*`, `sequencer/`). A
  hook is code that runs on the next commit; an `info/exclude` line hides a file.
- The set of top-level ignored entries. A new `dist/` counts as a write, and so does a
  deleted one.
- Every file *inside* the ignored entries that already existed (`node_modules/`, `dist/`),
  by lstat identity: inode, size, mtime and ctime. A write changes ctime and an
  unprivileged process cannot set it back, so editing a dependency and restoring its mtime
  is still caught. `fingerprint_ignored: false` turns this off where the walk is too slow.
- The Factory's own `guarded_paths`: by default `core/` (workflows, gates, contracts),
  `scripts/`, `bin/` and `workspace/config/` (`wgflib.isolation.DEFAULT_GUARDED_PATHS`).
  These decide what a review, and every later check, is worth. The develop step holds its
  developer to the same list.

Every git command the step runs is hardened (`wgflib/gitsafe.py`): `core.fsmonitor`,
hooks, commit and log signing (`gpg.program`) and every filter driver the checkout's config
defines are disabled, and after the first call the git directory and work tree are pinned. Without that, a reviewer - or the
developer before it - that writes `core.fsmonitor` or a `filter.*.process` into
`.git/config` gets the Factory to run a command outside any sandbox the agent was in, and a
`core.worktree` pointing elsewhere turns the restore's `clean -fd` on another directory.

**What is not guarded: the rest of the repository.** A game repository can have several
worktrees. Delegated agents commit on their own branches, in their own worktrees, while a
review runs ([orca-delegation.md](orca-delegation.md)). Their branch refs, tags, the shared
stash, `.git/worktrees/*` and their branches' config belong to them. A change there is not
a violation. The step logs it (`repository changed outside the guarded set`), and the
restore never writes, deletes or rewinds it: restoring another worktree's branch would
destroy its work. Found live: a review failed on `refs/heads/expansion`,
`refs/heads/bbw-ui-polish` and `.git/config`, and its restore deleted `expansion`, which
left that worktree at `HEAD 0000000`. The cost of this rule: a reviewer that tags, stashes,
or commits on another branch and switches back is logged, not failed. None of those change
the checkout the review was of.

**Any difference** in the guarded set fails the review. Each change is listed in
`review-report.isolation.violations` with `path`, `change`, `scope` (`checkout` or
`factory`) and `sensitive`. The checkout is then put back:

0. Write back the git metadata from memory, before git reads it again. The config is put
   back through `git config --file`, which runs nothing: the guarded entries as they were,
   other branches' entries as they are now.
1. Restore the symbolic ref.
2. Restore the per-worktree refs. No other ref is touched.
3. `reset --hard` to the recorded `HEAD`. This also puts back the checked-out branch.
4. `clean -fd`. Never `-x`, so `node_modules` survives.
5. Remove any new ignored entries, and files added inside existing ones.
6. Write back the bytes of the fixed-list, git-metadata and guarded files, which were kept in
   memory.

The checkout is then fingerprinted again. `isolation.restored` records whether it now
matches. If it does not, the step is `BLOCKED`.

A file *modified* inside an existing ignored entry cannot be put back - its bytes were never
kept - so that review is always `BLOCKED` for a person.

**What it cannot see.** Anything outside the checkout and the guarded paths, and a process
the reviewer left running that writes after the second snapshot and escaped
`wgflib.procs`' cleanup (one that detached itself *and* cleared its environment; see
docs/agent-lifecycle.md). Fingerprinting detects and undoes changes; it does not sandbox the reviewer. A
reviewer that must not be able to reach the network or your home directory needs an OS-level
sandbox around its argv. That belongs in the installation's config.

## The verdict

```json
{
  "verdict": "approve | request-changes",
  "commit": "<the full 40-character sha under review>",
  "blockers": [{"id": "score-underflow", "file": "src/game/score.ts", "line": 2,
                "summary": "score can go negative", "severity": "blocker"}],
  "notes": "optional"
}
```

The check is strict (`verdict.py`). Each of these is `malformed-verdict`:

- a missing file, or a file that is not JSON;
- a key the contract does not have;
- a `commit` that is not the `HEAD` under review;
- `approve` with any blocker;
- `request-changes` with no blocker;
- a duplicate blocker id;
- a severity outside `blocker | critical | major | minor`;
- an absolute path or a `..` in `file`.

A malformed verdict is never read charitably as an approval.

## Configuration

`factory.review` in `workspace/config/factory.yaml`. A step's `with:` block can override any
key.

```yaml
factory:
  review:
    reviewer:
      kind: command                 # none (default) | command
      argv: [my-agent-host, --non-interactive, --cwd, "{repo}", "{prompt}"]
      timeout_seconds: 1800         # wall clock
      idle_timeout_seconds: 600     # no stdout/stderr for this long
    guarded_paths: [core, scripts, bin, workspace/config]   # the develop step's too
    fingerprint_ignored: true     # lstat inside existing ignored entries (node_modules)
  agents:
    env_passthrough: []           # what the reviewer's environment also carries
```

`argv` placeholders:

| Placeholder | Value |
|---|---|
| `{repo}` | the checkout |
| `{verdict}` | the verdict path |
| `{brief}` | the review brief: what to review, the previous blockers, what the design and plan specified, what to look for (code and gameplay), the verdict contract |
| `{commit}` | the sha under review |
| `{prompt}` | a one-paragraph instruction to read the brief and write only the verdict |

### What the brief asks

`render_brief` (`scripts/wgf_review/report.py`) writes, in order:

- what to review: the repository, the commit and the diff since the development baseline;
- the core loop and MVP;
- what development measured;
- the previous review's blockers;
- **verify failed on an earlier commit** - only while a verify failure is open (below);
- **what the design and plan specified**. This section appears only when the committed
  `docs/development/brief.json` carries F1's `build_spec` / `dev_plan`. It lists:
  - every MVP reward, failure and HUD `feedback` line;
  - the tutorial approach;
  - each prototype task with its acceptance criteria.

  A missing feedback hook, or an unmet criterion on an MVP task, is a design-fidelity blocker;
- **design fidelity**: what the design committed the build to *contain*. It appears when the
  brief carries a content contract (`build_spec.sections.content`, or a top-level `content`),
  difficulty axes, mastery, or when there are gaps or coverage to show. It lists:
  - the content table - unit id, purpose, objective, mechanics, per-axis difficulty, and
    whether development reported it built, partial or cut;
  - each unit's acceptance lines, and what it says it varies from the previous unit;
  - the difficulty axes those numbers are on, with their ranges;
  - win and loss as the design states them, and the mastery model, statement and signals;
  - the content coverage development reported (designed against built);
  - the `design_gaps` development reported - what the design did not decide and what was
    assumed instead - read from `docs/development/report.json`, with the prototype-report's
    copy standing in. When nothing is reported, the brief says so: a place where the code had
    to decide something the design did not say, with no gap recorded, is itself a finding.

  A reviewer reading only the diff cannot tell an invented unit from a designed one. This is
  what makes that visible, and an invented unit, mechanic or rule is a design-fidelity blocker;
- **look for**: the code checks (logic defects, stubs and empty tests, template rules,
  secrets and unknown hosts), then a **gameplay lens** (`GAMEPLAY_LENS`). The lens is a
  condensed copy of `core/craft/gameplay-review.md`. It covers:
  - restart that resets everything;
  - elapsed-time movement with gap clamping;
  - pause that stops simulation, timers, tweens and audio;
  - no double run start or double-handled tap;
  - listeners removed;
  - tuning kept as data;
  - no allocation in the frame loop;
  - flash rate and audio only after a user gesture;
  - aspect-tagged tests that reach their aspect;
  - every MVP content unit present in `public/content/units.json` and reachable in code from
    the previous one by playing - no unit only a debug jump or a URL parameter can enter;
  - every mechanic rule implemented as a rule with a unit test, with per-unit difficulty read
    from the data file rather than re-typed or recomputed in logic;
  - gaps reported in `design_gaps` rather than filled in silently; an invented unit, mechanic
    or rule is a design-fidelity blocker.

  On an MVP path a lens failure is a blocker; elsewhere it is at most minor. The lens is
  restated rather than pointed at, because the reviewer runs in the game checkout, where the
  Factory's `core/` is not a path it can rely on;
- the verdict contract, which is unchanged.

### After verify fails

Verify runs only after `review` and `sdk-review` approve. Once it fails, the run goes back to
develop, and every review until verify runs again reads a commit nothing can have verified
yet. A reviewer not told so asks for the one thing no commit can carry. On 2026-10-04 (Sky
Marble, `new-game-20261003-082542-0de9b5`) verify failed on harness timeouts the Factory then
fixed. The developer changed no game code, and the reviewer twice requested changes because
the failures were "unproven until verify passes on this commit". The run hit
`review.request-changes: 2` and blocked, with no code change able to clear it.

So both review steps take `qa-report` as an optional input. When the newest one is a `fail`
of this run (`report.verify_failure`: its `workflow.run_id` is this run, or it names none),
the brief carries a section that gives:

- the commit verify failed, its visit, and how development was re-entered (`verify.fail`, or
  a later `review.request-changes`, from the develop brief's `loop`);
- the recorded cause. `FAIL`: verify saw the checks fail and records no attribution - game or
  environment is not recorded, and the developer's `known_issues` is a claim to check, not
  evidence. `UNVERIFIED` / `BLOCKED_EXTERNAL`: verify could not establish the checks, and
  the cause is outside the game;
- each blocking defect with its repro (cut at 600 characters);
- the rules: verify re-runs after the approval, so never request changes because verify has
  not passed this commit. A failure with a cause in the source is a blocker, naming the
  file. A failure with no cause in the code (a timeout, a port, the harness) is not a
  blocker of this commit; the reviewer says in `notes` what it read. A commit that changes no
  game code is not a defect by itself.

Nothing else in the brief changes: the code checks, the gameplay lens and the verdict
contract apply in full, and a defect the reviewer finds is a blocker whether or not verify
saw it. A pass, another run's qa-report, or none: the section is absent. The qa-report is
pinned in the review-report's `provenance.inputs` like every other input.

The routing is unchanged. Verify still runs only after both approvals; re-running verify
before review would need a cause the qa-report does not record, and a build no reviewer had
approved would reach verify.

The same values are also in the environment as `WGF_REVIEW_REPO`, `WGF_REVIEW_VERDICT`,
`WGF_REVIEW_BRIEF` and `WGF_REVIEW_COMMIT`. Otherwise the reviewer's environment is an
allowlist (`wgflib/agentenv.py`: PATH, HOME, USER, LANG/LC_*, TERM, TMPDIR, SHELL, CI, the
proxy variables, XDG_*, NODE_*, PNPM_*, npm_config_* minus secret-named ones), plus
whatever `factory.agents.env_passthrough` names - typically the host's credential. The
Factory's own tokens never reach it.

The reviewer runs through `wgflib.procs.run`, as an owned process tree. Timeout, idle
timeout and `wgf cancel` end the whole tree, and heartbeats show in `wgf status`.

`verdict_from: stdout` is for a host running in a read-only mode or sandbox, which cannot
write the verdict file. In that mode the prompt and brief ask the host to *end its output*
with the verdict JSON. The step takes the last JSON object from stdout: the whole output, a
`json` fence, or a line of its own. It saves that object to the verdict path and checks it
exactly as it would a file.

An agent host is named only here, in the installation's config, and never in `core/`. For
a host with a headless mode, the argv usually looks like one of these:

```yaml
reviewer:
  kind: command
  verdict_from: stdout                                   # read-only hosts cannot write files
  argv: [claude, -p, "{prompt}", --permission-mode, plan]
  # argv: [codex, exec, --sandbox, read-only, "{prompt}"]
```

Check the host's own documentation for its read-only mode. Whether the host honours it or
not, the fingerprint still applies.

The two lines above are shapes, not a hardened config. `--permission-mode plan` alone still
loads the checkout's own `.claude/settings.json` and `CLAUDE.md`, which the developer wrote.
The Claude Code reviewer argv that was checked against the CLI and run live (`--safe-mode`,
`--tools` without Edit/Write, `--permission-mode dontAsk`, a deny rule for
`git … --output=`) is the commented `factory.review.reviewer` block in
`workspace/config/factory.yaml`. The evidence is in `docs/claude-capabilities.md`.

## Gate-gaming pre-check

A specialist develop visit ([specialist-routing.md](specialist-routing.md)) is briefed with
gate findings, each accepted when the gate measures the next build. The cheapest pass is
often a change to what the gate *measures* instead of the game. The 2026-10-05 validation
runs did exactly that three times, and no review caught it:

| Commit | Routed for | What it changed | Flagged as |
|---|---|---|---|
| 2D `cbac64e` (level designer) | `content.units_reachable` (the bot reached 2 of 3 units in its window) | lowered `ceiling_y` on the opening units: a smaller play area, so a rebound comes back sooner | `play-area-change` |
| 2D `68a12b7` (2D artist) | `assets.runtime` (ball and bolt not visible enough) | drew the ball 44 -> 60 and the bolt 12x54 -> 30x130, collision sizes unchanged; staged hovering capsules and bolts for the probe showcase | `sprite-size-without-collider`; the showcase staging, code only added, is a `probe-path-change` note (1.1.0) |
| 3D `1c6b099` (level designer) | `content.structure` (two units near-identical) | added `ramps`, `gaps`, `bumpers`, `lifts` to one unit's `parameters`; the parser reads none of them | `unread-content-field` |

The replay ran `wgf_review.gaming.precheck_range` on each commit's parent..commit in clones
of the two validation repositories; `scripts/tests/test_review_gaming.py` `RealCommits`
repeats it when `WGF_GAMING_REPLAY_2D` and `WGF_GAMING_REPLAY_3D` name them (skipped
otherwise, and reported as skipped).

**What runs.** Before the reviewer starts, with `subject: prototype-report` and a baseline,
the step reads every commit of `baseline..HEAD` that changes `docs/development/brief.json`
and whose brief names a `specialist` - every link of a specialist chain - and every commit
inside the range the develop step recorded for the build's specialist visit (the
prototype-report's `specialist`, from the brief's `baseline_commit` to the report's commit),
so a visit whose brief is byte-identical to the one before it is still read; and checks each
against its parent (`scripts/wgf_review/gaming.py`, vocabulary
`core/reference/gate-gaming.yaml`). It is deterministic: git objects and words, no model.
The result is kept beside the run as `review/<step>-<visit>-<attempt>.gaming.json`, and the
review-report records a `gate_gaming` summary (review-report 1.2.0; `noted` and `truncated`
since 1.3.0). At most the newest 30 commits of the change are read; when it holds more,
the summary says `truncated` and the reviewer's brief says how many were not read.

Every hunk is classified `player-facing`, `measurement-facing`, `test` (never what the
player runs) or `bookkeeping` (`docs/development/`, the Factory's own). Four patterns are
flagged:

| Pattern | Applies to | Flags |
|---|---|---|
| `unread-content-field` | every specialist visit | a key added to an object in `public/content/*.json` that game source (`src/`, tests excluded) never reads: not as a quoted string (`"ramps"`, a parser's `numberOf(p, "ramps")`), not as `.ramps` or `{ ramps } =` where the identifier before the dot, or the line, names what it was added under (`parameters.ramps`; `unit.ramps` for a key of `units[]`, plural or singular; for a top-level key, a file that names the content file). A `.ramps` on another object - a course's ramps - is not a read |
| `play-area-change` | visits whose findings are about reach, time or visibility (`categories` in the vocabulary, matched on each finding's check, dimension and summary) | a changed value in `public/**/*.json`, or a changed source line, whose key or identifiers name the play area, its bounds or a collider (`ceiling`, `wall`, `bounds`, `arena`, `hitbox`, ...); a changed top, bottom, left, right, width, height, floor, margin... of a board, layout or arena object in content data (`layout.top`); a simulation line assigning one to a board, arena or field (`board.margin = 40`, `height: 900` in `const BOARD = {`). `Math.floor`, a text's `borderColor` and a read of `BOARD.width` are not |
| `probe-path-change` | every specialist visit, unless a routed finding's check is about the probe itself (`probe`, `showcase`, `oracle`) | a changed source line that is probe-, showcase- or bot-only: the line, the declaration it sits in or that declaration's comment names the probe, or the file's path does. A hunk that only adds code is a note, not a flag (below) |
| `sprite-size-without-collider` | every specialist visit | a numeric drawn size changed - a size or draw constant in drawing code (a `render`/`view`/`sprites`... path segment), a draw size in `public/**/*.json`, an asset manifest or atlas frame displayed larger in `public/assets/**.json`, an image file made larger - for an entity the simulation gives a physical size (a non-drawing source line names it beside a size or collider word); or a draw size scaled from an entity's collider or radius whose expression changed (`sprite.width = ball.radius * 5`) - and no collider or physical size (`radius`, `width`, `hitbox`...) of that same entity changed in the commit: `BALL_TRAIL_LENGTH` does not exempt `BALL_DRAW` |

**What a flag does.** Each flag (one blocker per visit, pattern and file) is a review
blocker with id `gate-gaming-<pattern>-<n>`, severity `blocker`, the commit, the routed
findings and what was seen. The review requests changes whatever the reviewer decided: an
approval with a flag becomes `request-changes`, and the notes say so. Each blocker carries
the visit's `dimension` (review-report 1.2.0), so triage routes it back to the **same
owner** (`wgf_triage.findings`: a review blocker's dimension, else the generalist), who sees
it in its next brief as a finding of its own.

**What the reviewer is told.** The brief's `## Gate gaming` section lists each specialist
commit, its routed findings, the hunk classification (bookkeeping omitted), the flags
(already blockers; not to be repeated), the declared changes to judge, and the patterns that
did not apply and why. The reviewer reads the player-facing hunks too - the pre-check knows
words, not intent - and reports a measurement-facing change it finds as a blocker whose id
starts `gate-gaming-`; the step stamps those with the visit's dimension as well.

**The false-positive path.** The pre-check can be wrong: a field read through an alias, an
arena the design asks to shrink. The developer declares such a change in the visit's own
`docs/development/report.json`:

```json
"measurement_changes": [
  {"flag": "unread-content-field", "where": "public/content/units.json#ramps",
   "evidence": [{"file": "src/game/course.ts", "line": 212}],
   "player_effect": "each ramp the unit lists is built into its course"}
]
```

`where` must name the flag: its file, or `file#key`; an empty `where` declares nothing. An
entry counts only with `player_effect` and at least one `evidence` reference where the
flagged change touched (gate-gaming 1.1.0): a line of the flagged file inside a flagged
hunk (anywhere the commit changed that file, for a flag on a JSON value), or a line of game
source inside a hunk of the same commit. A line of the brief, of another file, or of game
source the commit did not touch is not evidence. For `unread-content-field`, an evidence
line in game source the commit touched whose code names the key **clears** the flag - the
field is read. For any other pattern a valid entry makes the flag **declared**: it is no
longer a blocker by itself, and the reviewer judges it against the cited lines; unless they
show the player experiences the change, the reviewer requests changes. A declaration without
such evidence changes nothing.

**Notes.** A `probe-path-change` hunk that only adds code - a new entity the probe reports, a
new showcase state - alters nothing the probe already reported. It is `noted` (the pattern's
`additions: note` in the vocabulary): shown to the reviewer under "Noted - not blockers",
counted in `gate_gaming.noted`, never a blocker by itself. A hunk that removes or rewrites
existing probe code stays a flag.

**1.1.0 of the vocabulary** closed what a review of 1.0.0 found, each a case in
`scripts/tests/test_review_gaming.py` `ReviewFindings`: a junk declaration (any line of any
file, an empty `where`) disarmed any flag; a draw size scaled from a collider
(`sprite.width = ball.radius * 5`), an atlas frame or manifest size grown in
`public/assets/**.json` (display size: pixels over `scale`) and an image file made larger
were invisible; any size change sharing an entity word (`BALL_TRAIL_LENGTH`) exempted a
drawing - now only a collider or a physical size (`physical_size`: radius, width, height...)
whose entity words are within the drawing's exempts it; a play area renamed (`layout.top`)
escaped - now a changed top, bottom, left, right, width or height under a board, layout or
arena key in content data is a play-area change by what it is, and a source line assigning
such a value to a board, arena or field is one too (reading `BOARD.width` is not); an added
field was "read" by any `.count` anywhere - now the identifier before the dot or the line
must name what the field was added under (or, at the top of a file, the reading file must
name the content file). On the other side, a UI fix was blocked: `Math.floor` and a text's
`borderColor` no longer name a play area (`floor`, `border`, `margin` count only beside a
play-area object), and the visibility category is the size of an entity on screen -
`contrast`, `screen`, `size` and `small` are gone and a `ui` check never matches it.

Not covered: `sdk-review` (the sdk step's commit is no specialist's); a review with
`reviewer.kind: none`, which is skipped before any checkout is read; renamed files are read
as a deletion and an addition. The vocabulary is words, not a threshold: a commit that games
a gate in a word it does not know is added as a word and as a test case.

## How develop consumes it

`develop` declares `review-report` as an input and reads the newest one. It uses it only when
all of these hold:

- this is a later visit (`visit > 1`);
- the verdict is `request-changes` and it lists blockers;
- `reviewed_commit` is the checkout's `HEAD`, which is the commit this visit starts from.

Then the brief carries `review_blockers` (in `brief.json`) and a **"Fix first: blockers from
code review"** section (in `brief.md`), and it pins the review-report as an input. An
approval, a skipped or failed review, or a review of another commit carries nothing.
A request from `sdk-review` qualifies the same way: its `reviewed_commit` is the sdk commit,
which is HEAD when develop runs again, and develop builds on top of it.

The next development commit is what the next review sees. Its brief lists the previous
blockers for the reviewer to check again; so does the next `sdk-review`'s.

## How release consumes it

Release reads the newest `review-report` - in `new-game`, `sdk-review`'s - and drafts only
when it approves exactly the commit being released (the sdk commit, HEAD), by a reviewer
that ran (`reviewer.kind: command`), pinning the run's newest prototype-report and
sdk-report. An approval of develop's commit alone does not cover the sdk commit on top of
it. `skipped` and absent reviews are refused as `unreviewed` unless the installation sets
`factory.release.allow_unreviewed: true`. So the shipped default `reviewer.kind: none` makes
every release refuse until a reviewer is configured: fail closed. See
[release-module.md](release-module.md#when-it-refuses).

## Proof

`scripts/tests/test_core_agents.py` is the AGENTS category of the Core Acceptance Suite. The
developer and reviewer are real Python subprocesses and the game repository is real git. The
run goes through the real `WorkflowAPI`/`WorkflowEngine` on the shipped `new-game`
workflow.

The central test runs the whole loop:

1. The developer commits a build with a planted bug.
2. The reviewer finds it and requests changes.
3. The workflow re-enters `develop`, and the brief carries the blocker.
4. The developer fixes it.
5. The reviewer approves.
6. The run continues through `sdk`, `sdk-review` (the same reviewer approves the sdk
   commit), `verify`, G4 (passed as a person) and `release`, which drafts from the
   approved sdk commit.

The other tests are the rejection paths:

- editing source, `package.json`, a test, `game.config.yaml`, an ignored path, or Factory
  config. Each is rejected and the file is restored.
- committing. Rejected, and `HEAD` is restored.
- six kinds of malformed verdict.
- reviewer timeout. Retried, and the grandchild is verified dead.
- reviewer idle timeout, and a reviewer crash.
- developer timeout, developer failure, and an exhausted retry budget.
- a reviewer that never approves, stopped by its own route limit
  (`test_a_reviewer_that_always_requests_changes_is_stopped_by_its_route_limit`).
- an uncommitted build.

```bash
python3 -m unittest discover -s scripts/tests -p test_core_agents.py      # ~35 s
WGF_AJV=1 python3 -m unittest test_core_agents.Schema                      # ajv, from scripts/tests
```

### The live tests

Two opt-in tests run real agent hosts. Both cost money, so they only run with
`WGF_LIVE_AGENT=1`, and both use the developer and reviewer that
`workspace/config/factory.yaml` documents in its commented examples, **verbatim**: the argvs
are read from that file (`golden.live.shipped_agent_examples`) and the prompts are the steps'
own (`wgf_review.report.PROMPT_STDOUT`, `wgf_develop.developers.PROMPT`). No prompt is written
for the test, so a run is reproducible from the repository alone.

```bash
cd scripts/tests
WGF_LIVE_AGENT=1 WGF_LIVE_KEEP=/tmp/wgf-live python3 -m unittest \
    test_core_agents.LiveReviewer test_live_loop.LiveBuildConverges -v
# or the whole category:  WGF_LIVE_AGENT=1 bin/wgf test-core --only AGENTS
```

**`test_core_agents.LiveReviewer`** - the reviewer only, on the AgentLoop's tiny repository
with the planted `score.ts` underflow and the scripted bug-then-fix developer. It asserts the
reviewer **finds** the bug (the first review requests changes with a blocker on
`src/game/score.ts`), that every verdict is trusted (valid, bound to the commit, isolation
intact, nothing killed), that the blocker reaches the developer's next brief, and that the
next review reads the fixing commit. It does not assert that the reviewer then clears the
file: that repository is a stub that does not implement the brief's design, and a reviewer
judging against the design correctly keeps a blocker on it. Before 2.1.0 the test asserted
it anyway, which only a reviewer prompt narrowing the review could satisfy.

**`test_live_loop.LiveBuildConverges`** - the loop (`scripts/golden/live.py`, see
[golden-runs.md](golden-runs.md#the-live-loop)): the golden 2D pipeline with the documented
developer building the game from scratch from the brief and the documented reviewer judging
it against the design. It asserts convergence - the run completed, the last development
commit approved and the sdk commit approved by sdk-review, every develop check green, only
the developer's own files changed, isolation intact and no process left.

`WGF_LIVE_REVIEWER_ARGV` (a JSON argv, same placeholders as the config) replaces the
reviewer for `LiveReviewer`, `WGF_LIVE_VERDICT_FROM` its verdict channel and
`WGF_LIVE_TIMEOUT` its timeouts; unset, the documented example's own values apply.
`WGF_LIVE_KEEP=<dir>` keeps each test's evidence under `<dir>/<test id>` (a rerun gets
`<test id>.2`; nothing is ever copied over an earlier run's).

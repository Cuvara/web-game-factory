# Review module

`scripts/wgf_review/` registers the `review` step type. After `develop` commits a build,
someone who did not write it reviews that commit. They **approve** it, or they **request
changes** and name blockers. A request for changes goes back to `develop`, and the next
brief starts with those blockers. The loop is data in `core/workflows/new-game.workflow.yaml`.
No code decides it:

```yaml
- id: review
  type: review
  stage: title:prototype
  inputs: [prototype-report, game-design, scaffold-record]
  outputs: [review-report]
  on:
    request-changes: develop
```

```
develop ──commit──► review ──approve──► sdk → verify → release
   ▲                  │
   └─request-changes──┘   (bounded by max_visits: 3 per start or resume)
```

## Outcomes

| Reviewer did | Step returns | Engine does |
|---|---|---|
| `approve`, checkout untouched | `SUCCESS` | continues to `sdk` |
| `request-changes`, checkout untouched | `FAILED`, route `request-changes`, not retryable | routes to `develop` because the workflow says so |
| changed anything it may only read | `FAILED` `reviewer-isolation-violation`, not retryable. The checkout is restored | run `FAILED` |
| changed something that could not be put back | `BLOCKED` | a person looks |
| wrote a malformed verdict, or none | `FAILED` `malformed-verdict`, not retryable | run `FAILED` |
| timed out or went silent | `FAILED` `reviewer-timeout` / `reviewer-idle-timeout`, retryable. The process tree is ended | retried per policy, then run `FAILED` |
| exited non-zero | `FAILED` `reviewer-crashed`, retryable | retried per policy |
| could not start (bad argv) | `FAILED` `reviewer-not-started`, not retryable | run `FAILED` |
| no reviewer configured (`kind: none`) | `SUCCESS`, verdict **`skipped`** | continues. The report and message both say the build is unreviewed |

Every executed review emits a `review-report`, including failed ones. A rejected review is
evidence.

**Why request-changes is `FAILED`.** An unrouted `SUCCESS` goes to the next step. If
request-changes were a `SUCCESS` with a route, a workflow that forgot to route it would
carry a rejected build into `sdk` and on toward release. As `FAILED` it fails closed:
unrouted, it fails the run. Verification's `fail` has the same shape for the same reason.
The engine needs nothing new. Routing a labelled `FAILED` is existing behaviour, and
`max_visits` bounds the loop. A reviewer that never approves blocks the run on its third
request with a `loop limit` message.

## Preconditions

The step refuses to review anything but exactly the commit `develop` made:

- `prototype-report.build_ref.commit_sha` must be the checkout's `HEAD`. If not: `FAILED`,
  not retryable.
- The checkout must be clean (`git status --porcelain --untracked-files=all`). If not:
  `BLOCKED`. There are two reasons. A review of a dirty tree is not a review of the commit.
  And the restore below is only exact when the tree equals `HEAD` beforehand.
- The verdict and brief paths must be outside the checkout. They go under
  `<run dir>/review/<visit>-<attempt>.{verdict.json,brief.md,log}`.

## Isolation: enforced, not requested

The prompt tells the reviewer it is read-only. That request is not what protects the
checkout. The checkout is **fingerprinted** before and after the reviewer runs
(`scripts/wgflib/isolation.py` - in the kernel since the develop step fingerprints the same
guarded paths around its developer, see [development-module.md](development-module.md);
`scripts/wgf_review/isolation.py` only re-exports it). The fingerprint covers:

- `HEAD`, the branch it points at, and every ref. This catches a reviewer that commits,
  resets, stashes, tags or switches branches.
- `git status --porcelain=v1 -z --untracked-files=all --ignored=no`. This catches staged
  changes.
- The sha256 and exec bit of every tracked file and every untracked, non-ignored file.
- A fixed list of paths, hashed whatever git says about them. The list covers
  `package.json`, the lockfiles, `.npmrc`, `.gitignore`, `game.config.yaml`, the
  tsconfig/vite/vitest/playwright/eslint/prettier configs, `tests/`, `.github/` and
  `.husky/`. A reviewer that also edited `.gitignore` to hide its change is still caught.
- The git metadata that changes what git or the next commit does: `.git/config`, `hooks/`,
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

**Any difference** fails the review. Each change is listed in
`review-report.isolation.violations` with `path`, `change`, `scope` (`checkout` or
`factory`) and `sensitive`. The checkout is then put back:

0. Write back the git metadata from memory, before git reads it again.
1. Restore the symbolic ref.
2. Restore every ref.
3. `reset --hard` to the recorded `HEAD`.
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
    # checkouts: ..                 # default: factory.develop.checkouts
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
| `{brief}` | the review brief: what to review, the previous blockers, the verdict contract |
| `{commit}` | the sha under review |
| `{prompt}` | a one-paragraph instruction to read the brief and write only the verdict |

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

## How develop consumes it

`develop` declares `review-report` as an input and reads the newest one. It uses it only when
all of these hold:

- this is a later visit (`visit > 1`);
- the verdict is `request-changes` and it lists blockers;
- `reviewed_commit` is the checkout's `HEAD`, which is the commit this visit starts from.

Then the brief carries `review_blockers` (in `brief.json`) and a **"Fix first: blockers from
code review"** section (in `brief.md`), and it pins the review-report as an input. An
approval, a skipped or failed review, or a review of another commit carries nothing.

The next development commit is what the next review sees. Its brief lists the previous
blockers for the reviewer to check again.

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
6. The run continues through `sdk`, `verify` and `release`.

The other tests are the rejection paths:

- editing source, `package.json`, a test, `game.config.yaml`, an ignored path, or Factory
  config. Each is rejected and the file is restored.
- committing. Rejected, and `HEAD` is restored.
- six kinds of malformed verdict.
- reviewer timeout. Retried, and the grandchild is verified dead.
- reviewer idle timeout, and a reviewer crash.
- developer timeout, developer failure, and an exhausted retry budget.
- `max_visits` stopping a reviewer that never approves.
- an uncommitted build.

```bash
python3 -m unittest discover -s scripts/tests -p test_core_agents.py      # ~35 s
WGF_AJV=1 python3 -m unittest test_core_agents.Schema                      # ajv, from scripts/tests
```

### The live test

One test runs a real agent host as the reviewer, against a tiny repository with the
planted bug. It asserts two things:

- the verdict is trusted: the report is valid, isolation is intact, and there is no failure;
- the host found the bug and then approved the fix.

It costs whatever one or two short reviews cost on that host, so it only runs when you ask:

```bash
cd scripts/tests
WGF_LIVE_AGENT=1 \
WGF_LIVE_REVIEWER_ARGV='["claude", "-p", "{prompt}", "--permission-mode", "plan"]' \
WGF_LIVE_VERDICT_FROM=stdout \
WGF_LIVE_TIMEOUT=900 \
python3 -m unittest test_core_agents.LiveReviewer -v
```

The argv takes the same placeholders as the config. `WGF_LIVE_VERDICT_FROM` defaults to
`stdout`. Set it to `file` for a host that can write `{verdict}` itself. Only the reviewer is live. The
developer is still the scripted one, so the bug and the fix are deterministic.

`LiveDeveloperAndReviewer` makes the developer live too. `WGF_LIVE_DEVELOPER_ARGV` is a JSON
argv that may use `{brief}`. The scripted part only writes the conformance scaffolding and
plants the bug, then `exec`s the host, so the host is the develop step's own child. The host
edits `src/game/app.ts` on visit 1. The live reviewer requests changes, and the host fixes
the blockers on visit 2. The test then asserts that the commit lineage and isolation held
and that the run completed. Set `WGF_LIVE_KEEP=<dir>` to keep the run's logs and verdicts.
The argvs used for the recorded run are in `docs/claude-capabilities.md`.

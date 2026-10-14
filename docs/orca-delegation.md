# Delegating work to agents through Orca

A coordinator - a person, or a lead agent running a multi-agent session in
Orca - hands one concrete task to one agent. The rule:

> A worktree exists because an agent works in it. Task, worktree, agent and result are one
> unit, created together and recorded together.

`scripts/wgf-delegate.py` (module `scripts/wgf_delegate.py`) is the one way the Factory's
operators start such work. It is operator tooling, not part of a workflow run: the engine never
calls it, and nothing in `core/` depends on it.

## What went wrong without it

The 2026-10-03 validation run (two games, nine workers) ended with twenty worktrees on disk,
most with no agent in them, and Orca showing every fix worker under the coordinator's own
checkout. The cause was in the coordinator, not in Orca:

| What happened | Why |
|---|---|
| Fix workers were started with `orca orchestration worker-start --worktree current` | `current` opens the agent's terminal in the coordinator's checkout |
| Each task spec told the agent to run `git worktree add ...` itself | so Orca never created, saw or owned the worktree |
| The agent edited the worktree through absolute paths from the wrong terminal | Orca filed the agent under `main`; the worktree looked empty |
| Game workers created extra `fix/...` worktrees for side tasks | one agent juggled its game and a Factory fix: no agent of its own ever ran there |
| Finished workers were released; worktrees stayed | correct for review, but nothing recorded which task a worktree belonged to |

Orca already has the right primitive: `worker-start --worktree new-top-level --name <n>
--repo <selector> --base-branch <ref>` creates the worktree, starts the agent's terminal in it
and delivers the task in one call. It was not used.

## The model

```
coordinator identifies a concrete task
  -> wgf-delegate spawn          (one call: orca worker-start --worktree new-top-level)
       Orca creates worktree <user>/<name> from <base>
       Orca starts the agent terminal IN that worktree and delivers the task
       wgf-delegate verifies the receipt, the turn, worker-show placement and git,
       recording each lifecycle event in the ledger
  -> the agent implements, tests, commits in its cwd, reports worker_done
  -> wgf-delegate status <task>   (Orca's outcome + the worktree's git -> the recorded state)
  -> the coordinator reviews the commit, pushes / opens the PR / merges
  -> wgf-delegate audit           (which worktrees are active, finished, unfinished, orphaned)
```

`spawn` succeeds only when Orca's receipt shows a worktree **created** for this task, an
**agent terminal**, and the task input **accepted**, the agent's turn started, `worker-show`
places the dispatch in that same worktree, and git can read it. It never fails silently:
before `worker-start` it records `AGENT_REQUESTED`; a refusal by Orca (no dispatch) is
`AGENT_SPAWN_FAILED`; and once the receipt names a dispatch, *any* later failure is
`AGENT_UNVERIFIED` - with the dispatch, terminal, worktree and the failure - and the message
names the remedy: `wgf-delegate adopt --dispatch <d> ...` once you have checked the agent, or
`orca orchestration worker-stop --dispatch <d>`. Both exit 1. Every delegated agent is told,
before its task:
work only in the current directory, create no other worktree, commit, never push, stop only
processes it started (by PID - never `taskkill /IM`, `pkill`, `killall`), and report one
`worker_done` with SHAs, files and test results.

```bash
python3 scripts/wgf-delegate.py spawn --task-id T12 --name improve-3d-environment \
    --title "3D environment pass" --spec-file task.md --repo ../games/sky-marble \
    --base main --run <orca-run-id>
python3 scripts/wgf-delegate.py status T12            # or the dispatch id; --json
python3 scripts/wgf-delegate.py audit --repo . --run <orca-run-id>
python3 scripts/wgf-delegate.py adopt --dispatch <ctx_...> --task-id T12 --title "..."
python3 scripts/wgf-delegate.py ledger
```

Two things the first live delegations met, now handled:

- **An unregistered repository.** A game repository the Factory's init created locally is not
  known to Orca; `spawn` registers it (`orca repo add --path`) before `worker-start`.
- **Claude Code's workspace-trust dialog.** The first agent opened in a directory Claude Code
  has never seen stops at "Is this a project you trust?" (Orca: `failedStage: agent_readiness`,
  `agent-trust-workspace`), with *No, exit* highlighted. `spawn` refuses and names the remedy;
  with `--trust-workspace` - for repositories you own - it selects *Yes, I trust this folder*
  in the agent's own terminal (never pressing Enter on *No*) and delivers the same task to that
  terminal as `worker-start --task <t> --terminal <t> --worktree id:<w> --retry-of <d>`.
  Claude Code trusts the folder's subtree afterwards.
- **A start whose receipt was misread**, or one that ended `AGENT_UNVERIFIED`, can be recorded
  after the fact with `wgf-delegate adopt --dispatch <ctx_...>`, which refuses a dispatch
  sitting in a main checkout, records `AGENT_SPAWNED` and then the dispatch's current state.
  A task already held by an agent (`AGENT_SPAWNED`, `STARTED`, `WORKING`, `UNVERIFIED`,
  `COMPLETED`) is not spawned again under the same id.

The spec file holds only the task: target, change, constraints, ownership, observable
acceptance (Orca's task-spec contract). Policy:

- **No task, no worktree.** Create a worktree only together with the agent that will work in
  it. Never pre-create worktrees for possible tasks, and never ask an agent to make one.
- **One agent, one task, one worktree.** A worker that finds a side task (a Factory defect while
  building a game) reports it; the coordinator delegates it to a new agent.
- **Game repositories too.** A specialist (level designer, 3D environment artist, UI) gets a
  worktree of the game repository; the game's owning worker integrates the reviewed commit into
  the checkout its run uses, between steps.
- **Keep a finished worktree until its work is merged**, then remove it with
  `orca worktree rm`. `audit` lists what is safe to remove (ORPHANED, STALE) and what is not
  (UNFINISHED: uncommitted changes, or commits that exist nowhere else; AGENT ORPHANED: an
  agent's work that never settled; UNKNOWN: nothing could be read).

## Lifecycle states

The ledger is append-only: one JSON line per event, keyed by task id. `ledger` and `status`
fold a task's events into its current record (a new `AGENT_REQUESTED` for the same id starts a
new attempt; the history is kept). A worktree's state is recorded apart from the agent's, and
never implies it.

| State | Recorded by | Means |
|---|---|---|
| `AGENT_REQUESTED` | `spawn`, before `worker-start` | the coordinator asked Orca for an agent |
| `AGENT_SPAWN_FAILED` | `spawn` | Orca refused: no dispatch exists (the error is recorded) |
| `WORKTREE_CREATED` | `spawn` | the receipt shows a worktree created for the task - nothing about an agent |
| `AGENT_SPAWNED` | `spawn`, `adopt` | the receipt proves worktree, agent terminal and task accepted |
| `AGENT_STARTED` | `spawn` | the agent's turn began, in its own worktree, readable by git |
| `AGENT_WORKING` | `status` | Orca: the dispatch is live and its turn has started |
| `AGENT_COMPLETED` | `status` | Orca's outcome is `succeeded` - the only completion evidence; the commit SHAs seen are recorded |
| `AGENT_FAILED` | `status` | Orca's outcome is `failed` |
| `AGENT_CANCELLED` | `status` | the dispatch was cancelled or stopped |
| `AGENT_ORPHANED` | `status` | the dispatch is not live (or Orca no longer knows it) and has no completion evidence |
| `AGENT_UNVERIFIED` | `spawn`, `status` | a dispatch exists but what it is doing is unproven: a check after the start failed, it runs outside its worktree, or Orca gave no liveness |

A worktree's existence, or commits in it, never make an agent `WORKING` or `COMPLETED`: an
agent that committed and died without an outcome is `AGENT_ORPHANED`, its commits recorded.
`status` appends an event only when the state or the evidence (commits, uncommitted changes)
changed.

## Audit classes

| Class | Meaning |
|---|---|
| ACTIVE AGENT | a live dispatch's terminal is in this worktree |
| COMPLETED WORK | commits beyond the base, pushed; no live agent |
| UNFINISHED WORK | uncommitted changes, or commits that exist only here |
| AGENT ORPHANED | a recorded delegation whose dispatch is not live and never settled; the reason says what the worktree holds |
| STALE WORKTREE | a recorded delegation whose branch adds nothing beyond the base |
| ORPHANED WORKTREE | no recorded delegation, nothing beyond the base |
| MAIN CHECKOUT | the repository's own working tree |
| UNKNOWN | git cannot read the worktree from this host, or Orca cannot be asked about its agent |

Each row also shows the delegation's latest lifecycle state. UNKNOWN is never safe to remove:
it says nothing about what the worktree holds.

## Windows, WSL and the host the coordinator runs on

Orca on a WSL host creates worktrees inside the distribution (`/home/<user>/orca/workspaces/
...`) and reports them to a Windows process as `\\wsl.localhost\<distro>\home\...`; their
`.git` file names a Linux `gitdir: /mnt/c/...`, which Windows git cannot follow. So:

- **Paths are translated for the host this Python runs on.** Under WSL or Linux,
  `\\wsl.localhost\<distro>\...` and `\\wsl$\<distro>\...` are the Linux path they name, and
  (under WSL) `C:/...` is `/mnt/c/...`; on Windows, `/mnt/<d>/...` is `<D>:/...`.
- **On Windows, git reads a WSL worktree inside WSL**: `wsl.exe -d <distro> git -C <linux
  path> ...` (the default distribution, or `WSL_DISTRO_NAME`, for a bare `/home/...` path). If
  that cannot run, the worktree is UNKNOWN - never an empty orphan.
- **The orca launcher** is `WGF_ORCA`, else `ORCA_CLI_COMMAND` (Orca exports it into its
  terminals; from a WSL shell it is `orca-ide`, and `orca` is not on PATH), else `orca`.

Prefer running `wgf-delegate` on the same side as the worktrees (the WSL shell for a WSL
host); the translation is what makes the other side safe, not a reason to use it.

### The incident (2026-10-05)

A coordinator in an Orca terminal on WSL (`ORCA_ORCHESTRATION_COMPATIBILITY_HOST_KIND=wsl`)
ran `wgf-delegate spawn` under Windows Python. Orca created the worktree at
`\\wsl.localhost\Ubuntu\home\...\proof-p1`, started the agent and delivered the task; the
agent finished and committed. `spawn` then ran Windows git on that path, which failed
(`... is not a git worktree:`), and - by the design of the time - raised "without recording
anything": a real agent and worktree with no ledger record. The same day, `audit` run from
Windows on worktrees under `/home/<user>/...` could not read them and classified them
ORPHANED WORKTREE "nothing beyond origin/main" - safe to remove - while live agents had
uncommitted changes there. Both are closed: a dispatch Orca started is always recorded
(`AGENT_UNVERIFIED` at worst, with the remedy), git reads a WSL worktree through `wsl.exe`,
and a worktree git cannot read is UNKNOWN.

Environment: `WGF_ORCA` (the orca executable; else `ORCA_CLI_COMMAND`, else `orca` on PATH),
`WGF_DELEGATION_LEDGER` (default `~/.cache/wgf/delegations.jsonl`).

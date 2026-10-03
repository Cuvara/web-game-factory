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
       wgf-delegate verifies the receipt + worker-show placement, records the ledger entry
  -> the agent implements, tests, commits in its cwd, reports worker_done
  -> the coordinator reviews the commit, pushes / opens the PR / merges
  -> wgf-delegate audit           (which worktrees are active, finished, unfinished, orphaned)
```

`spawn` refuses - and records nothing - unless Orca's receipt shows a worktree **created**
for this task, an **agent terminal**, and the task input **accepted**, and `worker-show`
places the dispatch in that same worktree. Every delegated agent is told, before its task:
work only in the current directory, create no other worktree, commit, never push, stop only
processes it started (by PID - never `taskkill /IM`, `pkill`, `killall`), and report one
`worker_done` with SHAs, files and test results.

```bash
python3 scripts/wgf-delegate.py spawn --task-id T12 --name improve-3d-environment \
    --title "3D environment pass" --spec-file task.md --repo ../games/sky-marble \
    --base main --run <orca-run-id>
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
- **A start whose receipt was misread** can be recorded after the fact with
  `wgf-delegate adopt --dispatch <ctx_...>`, which refuses a dispatch sitting in a main checkout.

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
  (UNFINISHED: uncommitted changes, or commits that exist nowhere else).

## Audit classes

| Class | Meaning |
|---|---|
| ACTIVE AGENT | a live dispatch's terminal is in this worktree |
| COMPLETED WORK | commits beyond the base, pushed; no live agent |
| UNFINISHED WORK | uncommitted changes, or commits that exist only here |
| STALE WORKTREE | a recorded delegation whose branch adds nothing beyond the base |
| ORPHANED WORKTREE | no recorded delegation, nothing beyond the base |
| MAIN CHECKOUT | the repository's own working tree |

Environment: `WGF_ORCA` (the orca executable, default `orca` on PATH),
`WGF_DELEGATION_LEDGER` (default `~/.cache/wgf/delegations.jsonl`).

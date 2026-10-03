# Agent Lifecycle

How the Factory runs the outside processes a workflow step depends on (package managers,
test runners, dev servers, browsers, stdio tool servers, agent CLIs): who owns them, how
their liveness is reported, how they are stopped, and where that breaks down.

The implementation is `scripts/wgflib/procs.py`. `scripts/tests/test_core_process.py` is
the executable version of this page: the PROCESS CLEANUP category of the Core Acceptance
Suite.

| Section | Covers |
|---|---|
| [Process ownership](#process-ownership) | What a step owns when it starts a process, and when it all ends |
| [Heartbeat & liveness](#heartbeat--liveness) | How `wgf status` tells a working step from a hung one |
| [Cancellation](#cancellation) | What a cancel, a timeout, Ctrl-C or `kill` does to the tree |
| [SIGKILL recovery](#sigkill-recovery) | How a resume ends what a driver killed with SIGKILL left running |
| [Known limits](#known-limits) | What the guarantees do not cover |

---

## Process ownership

**Rule: a step owns every process it starts, and every process those processes start.
When the call that started them returns, none of them is still running.**

This is the rule `subprocess.run(..., timeout=)` breaks. It kills the direct child and
nothing else. `pnpm` → `vite`, or Playwright → its `webServer` (which Playwright starts
*detached*, in a session of its own), leaves the grandchild alive and reparented to init.
It still holds a port. It also still holds the stdout pipe `subprocess.run` is draining, so
the timeout meant to end the step can hang it.

Every module therefore starts children through `wgflib.procs`, never through `subprocess`
directly:

| Call | For | Returns |
|---|---|---|
| `procs.run(argv, cwd, timeout, env, input, …)` | A command that runs to completion | `ProcessResult` (`returncode`, `stdout`, `stderr`, `timed_out`, `idle_timed_out`, `cancelled`, `killed`, `error`, `status`, `ok`, `tail()`) |
| `procs.spawn(argv, …popen kwargs)` | A long-lived child you talk to over pipes (an MCP stdio server) | `OwnedProcess`: `.process` is the `Popen`; `close()` ends the tree |

Both calls:

1. **Start the child in a new session.** That is a new process group on POSIX, and
   `CREATE_NEW_PROCESS_GROUP` on Windows. The child and every descendant that does not
   detach can then be signalled as one group. It also means a signal sent to the Factory's
   own terminal group never reaches them (see [Cancellation](#cancellation)). On Windows
   the child is also put in a job object of its own, with `KILL_ON_JOB_CLOSE`: every
   process it starts joins the job, so the job still holds a descendant whose parent has
   exited, which nothing else on Windows can find.
2. **Tag the child's environment.** `WGF_PROC_TAG=<random>` identifies this tree, and
   `WGF_PROC_LINEAGE=<outer>,…,<tag>` lists the tags of every owner above it. Environment
   survives fork, exec, `setsid()` and reparenting. On Linux, `procs.tagged_pids(tag)` reads
   `/proc/*/environ` and finds a descendant that left the group. Through the lineage it also
   finds a tree owned by a nested Factory process, such as an agent CLI that itself runs
   `wgf`. A child started while a workflow step executes also carries
   `WGF_PROC_RUN=<run-id>@<store digest>`, which is how a later driver finds what a
   SIGKILLed one left behind ([SIGKILL recovery](#sigkill-recovery)).
3. **Clean up on every exit path.** That covers success, failure, timeout, idle timeout,
   cancellation, an exception or `KeyboardInterrupt` in the caller, and interpreter exit
   (`atexit`). Cleanup sends SIGTERM to the group and to every tagged pid, waits
   `grace_seconds` (5 by default), then sends SIGKILL to whatever is left. It sweeps again
   for descendants that forked while it ran. The pids it had to kill are reported as
   `killed`. A non-empty `killed` on a successful run means the command left something
   running.
4. **Hold the exited child unreaped until cleanup is done.** On Linux this uses
   `waitid(WNOWAIT)`. While the child is a zombie, its pid and its process-group id cannot
   be handed to an unrelated process, so cleanup never signals a stranger.
5. **Drain stdout and stderr on threads, in 64 KiB chunks.** The caller keeps a bounded
   tail: the last 4 MiB of each stream, with `truncated` counting what was dropped. A child
   that writes gigabytes, with or without newlines, can neither deadlock on a full pipe nor
   exhaust memory. A descendant that escaped every signal and still holds a pipe costs the
   caller at most 2 s.
6. **Keep stdin closed.** It is `/dev/null` unless `input=` is given, so a child can never
   block on a prompt.
7. **Never raise for the child's own failure.** A missing executable is `error` (with the
   `OSError` in `exception`), a non-zero exit is `returncode`, and a log file that cannot
   be opened is skipped.

The module runners keep their public interfaces and are built on `procs.run`:

| Runner | Module |
|---|---|
| `wgf_develop.repository.Runner` | develop, and git through it. Accepts `idle_timeout=` and `log_path=`. `RunResult` gained `idle_timed_out`, `cancelled` and `killed`. |
| `wgf_verification.runner.CommandRunner` | verify. `CommandResult` gained `idle_timed_out`, `cancelled` and `killed`. |
| `wgf_sdk.runner.CommandRunner`, `wgf_sdk.evidence.PnpmRunner`, `wgf_sdk.e2e.sh` | sdk |
| `wgf_assets.mcp.McpClient` | assets. Uses `procs.spawn`; `close()`, a failed `start()` and interpreter exit all end the server's tree. |

A new module that needs a process uses one of these calls or `procs.run` itself. Calling
`subprocess` directly from a step is a bug.

## Heartbeat & liveness

The engine wraps every step execution in `procs.bound(context.progress,
context.should_stop)`. Any `procs.run` inside the step reports to that step and can be
cancelled through it. This works however deep the call sits in a module's runner, and the
runner knows nothing about workflows.

`procs.run` emits these events, which the engine records as `STEP_PROGRESS`
(`docs/workflow-engine.md`):

| Kind | When | Data |
|---|---|---|
| `spawned` | The child started | `pid`, `pgid`, `argv0`, `cwd` |
| `heartbeat` | Every `heartbeat_seconds` while it runs | `pid`, `elapsed_s`, `idle_s` (seconds since the child last wrote anything) |
| `timeout` / `idle-timeout` / `cancelled` | The wait ended for that reason | `pid`, `after_s` / `idle_s` |
| `cleanup` | Descendants had to be killed | `pid`, `killed` |
| `exited` | Always last | `pid`, `status`, `returncode`, `duration_s` |
| `port-wait` | Before `spawned`, while another process holds a fixed port the command needs ([Fixed preview ports](#fixed-preview-ports)); at once and every `heartbeat_seconds` | `port`, `waited_s`, `holder` |
| `port-acquired` | The port came free after a wait | `port`, `waited_s` |

On every event the engine updates the step state: `pid` is the child being waited on (or
`null`), `last_event` is the kind, and three clocks move separately, because a heartbeat
proves the *driver* is alive, not that the child is doing anything:

| Field | Moves on | Says |
|---|---|---|
| `last_activity_at` | every event, heartbeats included | the Factory process is reporting |
| `last_heartbeat_at` | a heartbeat | the driver is polling a running child |
| `last_output_at` | a lifecycle event (`started`, `spawned`, `exited`, …); on a heartbeat, to `now - idle_s` | when the child last wrote anything |

Lifecycle events are persisted at once. Heartbeats are persisted at most every
`WorkflowEngine.PROGRESS_SAVE_SECONDS` (5 s). State written before `last_output_at` and
`last_heartbeat_at` existed has neither and derives as it always did.

- `heartbeat_seconds` defaults to `$WGF_HEARTBEAT_SECONDS`, or 15 when that is unset. `0`
  turns heartbeats off - and with them everything below that needs `idle_s`.
- `wgf status` (`model.derive_liveness`) reads a RUNNING run with a live driver as `hung`
  in one of two cases, and says which (`hung_reason`):
  - **`driver`**: nothing at all, not even a heartbeat, for longer than
    `factory.execution.hung_after_seconds` (default 300). The Factory process has stopped
    reporting - blocked outside a child process, or suspended. `wgf cancel` asks it to
    stop, but a driver that is not polling never notices; end the driver pid and resume.
  - **`output`**: the step is waiting on a child (`pid`), heartbeats are arriving, and at
    the driver's last heartbeat the child had written nothing for longer than
    `factory.execution.hung_output_seconds` (default 900): `output_silence_seconds`,
    `last_heartbeat_at - last_output_at`, which the driver measured on its monotonic clock -
    what the watchdog acts on. `output_idle_seconds` (now minus `last_output_at`) is shown
    but never judged: a step of the wall clock (NTP, a WSL resync, a resumed laptop) is in
    it, and read a chatty child as hung before 2.2.0.
    The child may be stuck, or working without writing; status cannot tell. `wgf cancel`
    terminates its tree.
- Status only reports. The default 900 s is above every idle timeout a shipped module uses
  or recommends (the reviewer's 600 s, the developer's documented 900 s), so a child that
  module policy still lets be quiet does not read as hung.
- A module's own `idle_timeout=` is unchanged: it ends the child when there has been no
  output for that long, and the module reports it in its own words.

### The hung-child watchdog

`factory.execution.on_hung` decides whether anything *acts* on an output-hung child:

| Value | Effect |
|---|---|
| `none` (default) | nothing; `wgf status` reports it |
| `cancel` | the **driving** engine terminates the child's tree once a heartbeat reports `idle_s` above `hung_output_seconds` |

With `cancel`, the progress recorder trips a per-execution watchdog on that heartbeat and
emits one `STEP_LOG` warning (`data.reason: hung-output`, `pid`, `idle_s`,
`hung_output_seconds`). The step's `should_stop` turns true, so `procs.run` takes the same
path a `wgf cancel` takes: SIGTERM to the tree, SIGKILL after the grace period, result
`cancelled`. The step then ends with its own outcome made **not retryable**, its message
naming the watchdog; with the default routing the run ends `FAILED` (resumable), not
`CANCELLED`. A step that still returns `SUCCESS` keeps it, exactly as under a cancel.

The policy is snapshotted into the run's params at start (`on_hung`, `hung_output_seconds`;
nothing is recorded for `none`), so a resume keeps the policy the run started with, and
`integrity.params_problems` refuses a `state.json` whose policy was edited since. An
unknown `on_hung` value is a `ConfigError`: no run starts under it. Set
`hung_output_seconds` above every module idle timeout you configure, or the watchdog
pre-empts the module's own, better-worded, ending. It needs heartbeats (`idle_s`); with
`heartbeat_seconds` 0 it never fires.

## Fixed preview ports

The pinned template's `playwright.config.ts` serves the build with `pnpm preview --port 4173
--strictPort` and `reuseExistingServer: false` (`playwright.sdk.config.ts`: 4176). One
checkout per machine, that is right: a stray server is never taken for this build. Two
Factory runs on one machine are not: whichever reaches 4173 second fails with
"http://localhost:4173 is already used" - three times in a minute each, on 2026-10-03, a
greybox smoke check while another run's smoke suite held the port, and the step failed
with its retries spent. The config is template-owned and conformance-checked, so a game
cannot move its port. The Factory serializes the commands instead.

`procs.run` holds a machine-wide, cross-process lock (`scripts/wgflib/portlock.py`) on each
fixed port its command binds, for exactly as long as the command runs. Which commands bind
one is `portlock.ports_for(argv)`, from the template's scripts and configs
(`portlock.SCRIPT_CONFIGS`, `portlock.CONFIG_PORTS`; `test_portlock` checks them against the
pinned template):

| Command | Port | Run by |
|---|---|---|
| `pnpm run test:e2e` | 4173 | the develop `smoke` check (greybox and production), verify's gameplay check |
| `pnpm run test:verify` | 4173 | verify's runtime-facts check |
| `pnpm run test:sdk:browser` | 4176 | the sdk step's optional browser smoke |
| `playwright test` with no `-c`, or `-c playwright.config.ts` | 4173 | the golden runs' repository suites |

Every other browser run the Factory starts - playability's bot, the store-listing capture,
the sdk e2e, the golden probe, MV-4 - uses a config of its own on a port it picks free, and
takes no lock. A step needs nothing to opt in; a caller passes `ports=()` to opt out, or
`ports=(...)` to name them itself.

The lock is `port-<port>.lock` in `$WGF_LOCK_DIR` (default `~/.cache/wgf/locks`), taken with
the operating system's own file lock: `fcntl.flock` on POSIX, `msvcrt.locking` on Windows.
The kernel releases it when the holder's handle closes, so a holder that exited, crashed or
was killed holds nothing - there is no stale lock to detect or break. Beside it,
`port-<port>.holder.json` records the holder's pid, run, command and start time for the
messages below; it is never the lock, and the next holder overwrites a stale one.

- **Waiting is progress.** `procs.run` emits `port-wait` at once and every
  `heartbeat_seconds`. It is a lifecycle event, so it moves `last_activity_at` and
  `last_output_at`, and with no child yet there is no `pid`: `wgf status` reads the step as
  running, never `hung`, and the hung-child watchdog has nothing to act on.
- **Waiting is cancellable.** The step's `should_stop` is polled: `wgf cancel` (or the
  watchdog) ends the wait, and the result is `cancelled`, as for a running child.
- **Waiting is bounded.** After `$WGF_PORT_LOCK_TIMEOUT` seconds (default 3600) `procs.run`
  returns `error` (`not-started`) naming the holder - for example `port 4173 is still held
  after 3600s by pid 4242, run new-game-...@..., running `pnpm run test:e2e --workers=1`,
  since 2026-10-03T08:31:02Z` - which each module reports as its own "could not be
  started" outcome. Nothing is retried on the module's behalf.
- **Re-entrant.** A thread already holding the port takes it again at once, and every child
  started while a port is held carries `WGF_PROC_PORTS`, so a nested Factory process never
  waits on the lock its own ancestor holds for it.

Not covered: what a developer agent runs by itself inside its session (the brief tells it to
run `pnpm test:e2e`, and to serve the build on 4173 for the browser tool). The step that
runs the agent holds no lock - that would serialize whole development sessions - so an
agent's own suite can still meet another run's. It fails the agent's own command, not the
step; the step's checks run afterwards, under the lock. The reverse also holds: a
`pnpm preview` the agent left serving 4173 is not under the lock, and another run's check
that takes the lock meanwhile still finds the port in use. What the agent left running ends
with its session - the agent CLI is an owned tree, and on Windows its job object reaches
servers whose shell already exited ([Known limits](#known-limits)) - so that window closes
when the session does. `procs.spawn` (long-lived servers) takes no lock either; nothing the
Factory spawns binds a fixed port.

**Template follow-up (proposal only).** The lock removes the failure, not the queue: two
runs still take turns on 4173. A future template release could read the preview port from
the environment in `playwright.config.ts`, as its other configs already do
(`CG_DEMO_PORT`, `SDK_MATRIX_PORT`, ...): `const PORT = Number(process.env["WGF_PREVIEW_PORT"]
?? 4173)`. The Factory would then hand each command a free port and drop the entry from
`portlock.CONFIG_PORTS` once the pin moves to that release. Until then the lock is the only
mechanism; nothing in a game repository changes.

## Cancellation

| Trigger | What happens to the tree |
|---|---|
| `wgf cancel <run>` | The engine's `should_stop` becomes true. Within `poll_seconds` (0.1 s) `procs.run` sends SIGTERM, then SIGKILL after the grace period, and returns `cancelled`. The step then returns its own result. The engine honouring the cancel after the step returns belongs to the engine (Team A). |
| `timeout=` | The whole tree is terminated and the result is `timed_out`, with no hang even if a grandchild holds the pipes. |
| `idle_timeout=` | The whole tree is terminated when there has been no output for that many seconds, and the result is `idle_timed_out`. |
| Ctrl-C / `KeyboardInterrupt`, `SystemExit` | `procs.run` terminates the tree, then re-raises. A second interrupt that cuts cleanup short leaves the tree registered, and `atexit` finishes it. |
| `kill <wgf pid>` (SIGTERM), a closed terminal (SIGHUP) | Children are in sessions of their own and **never receive these**. The CLI entry point must call `procs.install_signal_cleanup()` once, from the main thread. That turns SIGTERM and SIGHUP into `SystemExit(128 + signum)`, so every waiting `run()` unwinds and cleans up. It only replaces default handlers (a SIGHUP ignored under `nohup` stays ignored) and ignores a repeat of the signal while cleanup runs. Nothing is installed at import time. |
| SIGKILL of the Factory process | Nothing runs, so there is no cleanup: the tree is orphaned and the run reads `stale`. The next `wgf resume` (or `wgf cancel`) of the run ends it; see [SIGKILL recovery](#sigkill-recovery). |
| `factory.execution.on_hung: cancel` | The driving engine cancels a step whose child has written nothing for `hung_output_seconds`, as above; see [the watchdog](#the-hung-child-watchdog). |

## SIGKILL recovery

A driver killed with SIGKILL (or a machine that lost power) runs no `atexit`, no signal
handler, and takes its subreaper with it. Every tree its step started keeps running,
reparented to init, and `state.json` names at most the last child's `pid`, which may since
have been recycled. What does survive is the environment. The engine binds every
execution to its run (`procs.bound(..., run=token)`), and every child `procs` starts then
carries:

    WGF_PROC_RUN=<run-id>@<12 hex digits of the run store's directory>

It is a comma list, outermost run first, like `WGF_PROC_LINEAGE`: a `wgf` started inside
another run's step appends its own run, so a sweep of the outer run still finds the inner
one's children. The store digest keeps two stores that both hold a `run-1` (two checkouts,
two test suites) from reaching each other's processes. A caller-supplied environment
cannot set it: `procs` writes it from its own binding, like the tag.

When `resume` loads a run that is `RUNNING` on disk, it holds the run's lock - so no live
driver owns it - and, **before** anything executes again, `procs.sweep_run(token)` ends
every process whose `/proc/<pid>/environ` names that token: SIGTERM, 5 s
(`WorkflowEngine.SWEEP_GRACE_SECONDS`), SIGKILL, repeated for anything that forks meanwhile.
A `STEP_LOG` warning lists the pids (`data.pids`). `wgf cancel` of a stale `RUNNING` run
does the same before it marks the run `CANCELLED`. The sweep never signals this process,
one of its ancestors (an agent that runs `wgf resume` on its own run), a tree this process
owns, or any process that does not carry the token - an untagged process, or one of
another run, is never touched (`test_core_process.DriverKilledBySigkill`).

Linux only. Without `/proc` the engine logs a `STEP_LOG` warning that it cannot sweep, and
any orphan keeps running. A descendant that cleared its environment is not found either.

## Known limits

- **No `/proc` (macOS, Windows): only the group.** `tagged_pids` returns `[]`, so a
  descendant that detaches itself (`setsid`, Playwright's `webServer`) is not found. On
  macOS the group is still signalled. On Windows `taskkill /T` ends the tree by parentage
  while the leader runs, and the tree's job object ends every member - including an orphan
  whose parent already exited, which Windows does not reparent and `taskkill /T` therefore
  cannot reach. Before the job object (2026-10-03) such an orphan outlived its tree: a
  `vite preview` left behind by a finished command or agent session kept port 4173 until
  someone killed it. The job is assigned right after the child starts, so a grandchild the
  child starts within that instant escapes it; a process that asks to break away from its
  job (`CREATE_BREAKAWAY_FROM_JOB`), or a host that refuses nested jobs, is not covered.
  Because the job closes with the Factory process, a Factory killed outright takes its
  trees with it on Windows - there is no SIGKILL recovery to do there.
  The zombie hold (`waitid(WNOWAIT)`) is Linux-only too. Elsewhere the child is reaped
  first and its group is signalled only while it still has live members.
- **A descendant that clears its environment *and* detaches** cannot be found by tag or by
  group. On Linux the `wgf` CLI closes this with `procs.install_subreaper()`
  (`PR_SET_CHILD_SUBREAPER`): such an orphan is reparented to the Factory instead of init,
  and every adopted orphan no live tree claims is ended and reaped with the step
  (`test_core_security.ReviewerLeftovers`). A library caller that does not opt in, and any
  platform without `prctl`, still has the limit. The subreaper assumes every child of the
  process comes from `wgflib.procs` — true for the CLI, enforced by
  `test_core_process.EveryChildGoesThroughProcs`. Only orphans outside the Factory's own
  session are swept, so a plain child some other code started (and waits on) keeps its exit
  status — unless that code gave it a session of its own (`start_new_session=True`), which
  the sweep cannot tell from an orphan. The CLI does not install the subreaper for
  `wgf test-core`, whose tests start children in-process.
- **A descendant running as another user** (sudo, setuid) cannot be signalled, and its
  `/proc/<pid>/environ` cannot be read.
- **SIGKILL of the Factory process, or a machine crash**, skips all cleanup. The orphans
  still carry their tag and their run (`WGF_PROC_RUN`), and on Linux the next resume or
  cancel of the run ends them ([SIGKILL recovery](#sigkill-recovery)). Until then they run
  on; by hand, `grep -l WGF_PROC_RUN= /proc/*/environ` finds them. A driver of a run that
  is never resumed or cancelled leaves them running.
- **`atexit` does not run** after `os._exit` or a fatal signal that has no Python handler.
- **Output is truncated to the last 4 MiB per stream.** A caller that needs a large
  artifact from a child has it write a file (as vitest's `--outputFile` does) instead of
  parsing stdout.
- **Output is decoded as UTF-8 with replacement, and newlines are not translated**
  (`\r\n` stays `\r\n`).
- **Cancellation is polled** every `poll_seconds` (0.1 s) and ends the tree within
  `grace_seconds` plus about 1 s. A step that blocks outside `procs.run` (a network call,
  a busy loop) is not interrupted by it. That step must poll `context.should_stop()`
  itself.

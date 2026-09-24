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
   own terminal group never reaches them (see [Cancellation](#cancellation)).
2. **Tag the child's environment.** `WGF_PROC_TAG=<random>` identifies this tree, and
   `WGF_PROC_LINEAGE=<outer>,…,<tag>` lists the tags of every owner above it. Environment
   survives fork, exec, `setsid()` and reparenting. On Linux, `procs.tagged_pids(tag)` reads
   `/proc/*/environ` and finds a descendant that left the group. Through the lineage it also
   finds a tree owned by a nested Factory process, such as an agent CLI that itself runs
   `wgf`.
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

On every event the engine updates the step state: `pid` is the child being waited on (or
`null`), `last_activity_at` is when anything last happened, and `last_event` is the kind.
Lifecycle events are persisted at once. Heartbeats are persisted at most every
`WorkflowEngine.PROGRESS_SAVE_SECONDS` (5 s).

- `heartbeat_seconds` defaults to `$WGF_HEARTBEAT_SECONDS`, or 15 when that is unset. `0`
  turns heartbeats off.
- A step with a recent `last_activity_at` is working. A step whose heartbeats keep arriving
  while `idle_s` grows is waiting on a child that has gone quiet. `idle_timeout=` turns
  that into an ending instead of a hang.
- A step with no heartbeat at all for several intervals has hung in the Factory process
  itself, not in a child.

## Cancellation

| Trigger | What happens to the tree |
|---|---|
| `wgf cancel <run>` | The engine's `should_stop` becomes true. Within `poll_seconds` (0.1 s) `procs.run` sends SIGTERM, then SIGKILL after the grace period, and returns `cancelled`. The step then returns its own result. The engine honouring the cancel after the step returns belongs to the engine (Team A). |
| `timeout=` | The whole tree is terminated and the result is `timed_out`, with no hang even if a grandchild holds the pipes. |
| `idle_timeout=` | The whole tree is terminated when there has been no output for that many seconds, and the result is `idle_timed_out`. |
| Ctrl-C / `KeyboardInterrupt`, `SystemExit` | `procs.run` terminates the tree, then re-raises. A second interrupt that cuts cleanup short leaves the tree registered, and `atexit` finishes it. |
| `kill <wgf pid>` (SIGTERM), a closed terminal (SIGHUP) | Children are in sessions of their own and **never receive these**. The CLI entry point must call `procs.install_signal_cleanup()` once, from the main thread. That turns SIGTERM and SIGHUP into `SystemExit(128 + signum)`, so every waiting `run()` unwinds and cleans up. It only replaces default handlers (a SIGHUP ignored under `nohup` stays ignored) and ignores a repeat of the signal while cleanup runs. Nothing is installed at import time. |
| SIGKILL of the Factory process | Nothing runs, so there is no cleanup. See [Known limits](#known-limits). |

## Known limits

- **No `/proc` (macOS, Windows): only the group.** `tagged_pids` returns `[]`, so a
  descendant that detaches itself (`setsid`, Playwright's `webServer`) is not found. On
  macOS the group is still signalled. On Windows `taskkill /T` ends the tree by parentage.
  The zombie hold (`waitid(WNOWAIT)`) is Linux-only too. Elsewhere the child is reaped
  first and its group is signalled only while it still has live members.
- **A descendant that clears its environment *and* detaches** cannot be found by tag or by
  group. Nothing in the standard library can track it. The known offenders (Playwright,
  vite, pnpm) keep the environment.
- **A descendant running as another user** (sudo, setuid) cannot be signalled, and its
  `/proc/<pid>/environ` cannot be read.
- **SIGKILL of the Factory process, or a machine crash**, skips all cleanup. The orphans
  still carry their tag. On Linux `grep -l WGF_PROC_TAG= /proc/*/environ` finds them, and
  `procs.terminate_tree(None, None, tag)` ends them.
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

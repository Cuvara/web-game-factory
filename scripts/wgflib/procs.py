"""Run a child process as something a workflow step owns: the whole tree, observed, and gone
when the step is.

`subprocess.run(..., timeout=)` kills the direct child and nothing else. A `pnpm` that
started `vite`, or a Playwright run whose `webServer` started a dev server, leaves the
grandchild alive and reparented to init - still holding a port, and still holding the pipes
`subprocess.run` is waiting to drain, so a timeout can hang the step it was meant to end.
Everything a Factory step spawns goes through `run()` here instead, which:

  * starts the child in a new session (POSIX) or process group (Windows), so the child and
    everything that does not detach itself shares one group that can be signalled at once;
  * tags the child's environment with `WGF_PROC_TAG=<unique>`. Environment is inherited
    through fork/exec and survives `setsid()` and reparenting, so on Linux a descendant that
    left the group (Playwright starts its webServer detached) is still found by reading
    /proc/<pid>/environ. Elsewhere the group is all there is;
  * cleans the tree up whenever the child ends - success, failure, timeout, idle timeout,
    cancellation, or the calling process being interrupted - with SIGTERM, a grace period,
    then SIGKILL, and reports every pid it had to kill;
  * reads stdout and stderr on threads, so a chatty child never blocks on a full pipe and a
    grandchild holding a pipe open never blocks the caller;
  * reports what is happening through `on_event(kind, **data)`: `spawned`, `heartbeat`
    (every `heartbeat_seconds`, with seconds since the child last wrote anything),
    `timeout`, `idle-timeout`, `cancelled`, `exited`, `cleanup`. That is what lets a status
    command tell a step that is working from one that is hung without reading file times.

Standard library only. No provider, tool or step is named here: argv is the caller's.
"""

import atexit
import contextlib
import contextvars
import os
import secrets
import signal
import subprocess
import sys
import threading
import time

__all__ = ["run", "ProcessResult", "TAG_ENV", "tagged_pids", "terminate_tree",
           "live_groups", "terminate_all", "bound"]

TAG_ENV = "WGF_PROC_TAG"
POSIX = os.name == "posix"
_PROC = "/proc"
_TAIL_LIMIT = 4 * 1024 * 1024  # per stream; a runaway child cannot exhaust memory

# Every tree `run()` is currently responsible for: tag -> (pid, pgid). An interpreter that is
# exiting - normally, on an unhandled exception, or on SIGTERM turned into SystemExit -
# takes these down with it.
_LIVE = {}
_LIVE_LOCK = threading.Lock()


class ProcessResult:
    __slots__ = ("argv", "returncode", "stdout", "stderr", "timed_out", "idle_timed_out",
                 "cancelled", "duration_s", "pid", "tag", "killed", "error")

    def __init__(self, argv, returncode=None, stdout="", stderr="", timed_out=False,
                 idle_timed_out=False, cancelled=False, duration_s=0.0, pid=None, tag=None,
                 killed=(), error=None):
        self.argv = list(argv)
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.timed_out = timed_out
        self.idle_timed_out = idle_timed_out
        self.cancelled = cancelled
        self.duration_s = duration_s
        self.pid = pid
        self.tag = tag
        self.killed = list(killed)
        self.error = error  # the child could not be started at all: OSError text

    @property
    def ok(self):
        return (self.error is None and self.returncode == 0 and not self.timed_out
                and not self.idle_timed_out and not self.cancelled)

    @property
    def status(self):
        if self.error is not None:
            return "not-started"
        if self.cancelled:
            return "cancelled"
        if self.timed_out:
            return "timeout"
        if self.idle_timed_out:
            return "idle-timeout"
        return "exited"

    def tail(self, lines=40):
        text = (self.stdout or "") + (("\n" + self.stderr) if self.stderr else "")
        if self.error:
            text = (text + "\n" + self.error).strip()
        return "\n".join(text.strip().splitlines()[-lines:])

    def to_dict(self):
        return {"argv0": os.path.basename(self.argv[0]) if self.argv else None,
                "status": self.status, "returncode": self.returncode,
                "duration_s": round(self.duration_s, 3), "pid": self.pid,
                "killed": list(self.killed), "error": self.error}


# -- finding a tree -------------------------------------------------------------------------

def _read(path, mode="rb"):
    try:
        with open(path, mode) as handle:
            return handle.read()
    except OSError:
        return None


def tagged_pids(tag):
    """Live pids whose environment carries WGF_PROC_TAG=`tag`. Linux only; [] elsewhere."""
    if not tag or not os.path.isdir(_PROC):
        return []
    needle = f"{TAG_ENV}={tag}".encode()
    me = os.getpid()
    found = []
    for name in os.listdir(_PROC):
        if not name.isdigit() or int(name) == me:
            continue
        environ = _read(os.path.join(_PROC, name, "environ"))
        if environ and needle in environ.split(b"\0"):
            if not _is_zombie(int(name)):
                found.append(int(name))
    return sorted(found)


def _is_zombie(pid):
    stat = _read(os.path.join(_PROC, str(pid), "stat"), "r")
    if not stat:
        return False
    try:
        return stat.rsplit(")", 1)[1].split()[0] in ("Z", "X")
    except IndexError:
        return False


def _alive(pid):
    if POSIX and os.path.isdir(_PROC):
        if not os.path.exists(os.path.join(_PROC, str(pid))):
            return False
        return not _is_zombie(pid)
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError, OSError):
        return False
    return True


def _group_alive(pgid):
    """True while any non-zombie process is in group `pgid`. A zombie leader the caller has
    not reaped yet still answers killpg(pgid, 0), so /proc is asked first where it exists."""
    if not POSIX or pgid is None:
        return False
    if os.path.isdir(_PROC):
        for name in os.listdir(_PROC):
            if not name.isdigit():
                continue
            stat = _read(os.path.join(_PROC, name, "stat"), "r")
            if not stat:
                continue
            try:
                fields = stat.rsplit(")", 1)[1].split()
            except IndexError:
                continue
            if len(fields) > 2 and fields[2] == str(pgid) and fields[0] not in ("Z", "X"):
                return True
        return False
    try:
        os.killpg(pgid, 0)
    except (ProcessLookupError, PermissionError, OSError):
        return False
    return True


def _signal(pids, pgid, sig):
    if POSIX and pgid is not None:
        try:
            os.killpg(pgid, sig)
        except (ProcessLookupError, PermissionError, OSError):
            pass
    for pid in pids:
        try:
            os.kill(pid, sig)
        except (ProcessLookupError, PermissionError, OSError):
            pass


def terminate_tree(pid, pgid, tag, grace_seconds=5.0):
    """End the child's whole tree. Returns the pids that were still alive and signalled.

    The group is signalled as a whole; tagged processes are signalled individually because
    a detached descendant is in a group of its own. Survivors of SIGTERM after
    `grace_seconds` get SIGKILL.
    """
    if not POSIX:
        return _terminate_windows(pid)
    targets = set(tagged_pids(tag))
    if pid is not None and _alive(pid):
        targets.add(pid)
    group = _group_alive(pgid)
    if not targets and not group:
        return []
    _signal(sorted(targets), pgid, signal.SIGTERM)
    deadline = time.monotonic() + max(0.0, grace_seconds)
    while time.monotonic() < deadline:
        remaining = [p for p in targets if _alive(p)] + [p for p in tagged_pids(tag)
                                                           if p not in targets]
        if not remaining and not _group_alive(pgid):
            break
        time.sleep(0.05)
    late = set(tagged_pids(tag))
    survivors = sorted({p for p in targets | late if _alive(p)})
    if survivors or _group_alive(pgid):
        _signal(survivors, pgid, signal.SIGKILL)
        for _ in range(40):
            if not any(_alive(p) for p in survivors) and not _group_alive(pgid):
                break
            time.sleep(0.05)
    return sorted(targets | late)


def _terminate_windows(pid):  # pragma: no cover - exercised on Windows only
    if pid is None:
        return []
    subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)], capture_output=True)
    return [pid]


def live_groups():
    with _LIVE_LOCK:
        return dict(_LIVE)


def terminate_all(grace_seconds=2.0):
    """Take down every tree this process still owns. Registered with atexit."""
    for tag, (pid, pgid) in live_groups().items():
        try:
            terminate_tree(pid, pgid, tag, grace_seconds)
        finally:
            with _LIVE_LOCK:
                _LIVE.pop(tag, None)


atexit.register(terminate_all)


# -- the step a process belongs to ---------------------------------------------------------

# (on_event, should_stop) of the workflow step executing on this thread, set by the engine
# around every execution. A module's runner calls run() without knowing about workflows and
# still reports to, and is cancellable by, the step it runs under.
_BOUND = contextvars.ContextVar("wgf_procs_bound", default=None)


@contextlib.contextmanager
def bound(on_event=None, should_stop=None):
    """Within this block, every run() also reports to `on_event` and honours `should_stop`."""
    token = _BOUND.set((on_event, should_stop))
    try:
        yield
    finally:
        _BOUND.reset(token)


def _with_bound(on_event, should_stop):
    outer = _BOUND.get()
    if not outer:
        return on_event, should_stop
    outer_event, outer_stop = outer
    events = [f for f in (on_event, outer_event) if f is not None]
    stops = [f for f in (should_stop, outer_stop) if f is not None]

    def fan_out(kind, **data):
        for callback in events:
            try:
                callback(kind, **data)
            except Exception:
                pass

    def any_stop():
        return any(bool(stop()) for stop in stops)

    return (fan_out if events else None), (any_stop if stops else None)


# -- running --------------------------------------------------------------------------------

class _Stream:
    """Drains one pipe on a thread; keeps a bounded tail and the time of the last write."""

    def __init__(self, name, pipe, sink, on_line, activity):
        self.name = name
        self.chunks = []
        self.size = 0
        self._sink = sink
        self._on_line = on_line
        self._activity = activity
        self.thread = threading.Thread(target=self._pump, args=(pipe,), daemon=True)
        self.thread.start()

    def _pump(self, pipe):
        try:
            for raw in iter(pipe.readline, b""):
                self._activity()
                line = raw.decode("utf-8", "replace")
                self.chunks.append(line)
                self.size += len(line)
                while self.size > _TAIL_LIMIT and len(self.chunks) > 1:
                    self.size -= len(self.chunks.pop(0))
                if self._sink is not None:
                    try:
                        self._sink(self.name, line)
                    except Exception:
                        pass
                if self._on_line is not None:
                    try:
                        self._on_line(self.name, line.rstrip("\n"))
                    except Exception:
                        pass
        except (OSError, ValueError):
            pass
        finally:
            try:
                pipe.close()
            except OSError:
                pass

    def text(self):
        return "".join(self.chunks)


def run(argv, cwd=None, timeout=None, env=None, input=None, on_event=None, on_output=None,
        should_stop=None, heartbeat_seconds=15.0, idle_timeout=None, log_path=None,
        grace_seconds=5.0, poll_seconds=0.1):
    """Run `argv` to completion as an owned process tree. Never raises for the child's own
    failure: a missing executable is `error`, a non-zero exit is `returncode`.

    `timeout`       wall-clock seconds before the tree is terminated (`timed_out`).
    `idle_timeout`  seconds without output before the tree is terminated (`idle_timed_out`).
    `should_stop`   polled; returning True terminates the tree (`cancelled`).
    `on_event`      `(kind, **data)`, lifecycle and heartbeat; exceptions are swallowed.
    `on_output`     `(stream, line)` per line of stdout/stderr.
    `log_path`      every line is also appended here, prefixed by stream.
    """
    argv = [str(part) for part in argv]
    on_event, should_stop = _with_bound(on_event, should_stop)
    tag = secrets.token_hex(8)
    child_env = dict(os.environ if env is None else env)
    child_env[TAG_ENV] = tag

    def emit(kind, **data):
        if on_event is not None:
            try:
                on_event(kind, **data)
            except Exception:
                pass

    log = open(log_path, "a", encoding="utf-8") if log_path else None
    log_lock = threading.Lock()

    def sink(stream, line):
        if log is not None:
            with log_lock:
                log.write(f"[{stream}] {line}" if line.endswith("\n") else f"[{stream}] {line}\n")
                log.flush()

    last = {"activity": time.monotonic()}

    def activity():
        last["activity"] = time.monotonic()

    kwargs = {}
    if POSIX:
        kwargs["start_new_session"] = True
    else:  # pragma: no cover
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    began = time.monotonic()
    try:
        process = subprocess.Popen(
            argv, cwd=cwd, env=child_env,
            stdin=subprocess.PIPE if input is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kwargs)
    except OSError as exc:
        if log is not None:
            log.close()
        emit("exited", status="not-started", error=str(exc))
        return ProcessResult(argv, error=f"{type(exc).__name__}: {exc}", tag=tag,
                             duration_s=time.monotonic() - began)

    pgid = process.pid if POSIX else None
    with _LIVE_LOCK:
        _LIVE[tag] = (process.pid, pgid)
    emit("spawned", pid=process.pid, pgid=pgid, argv0=os.path.basename(argv[0]),
         cwd=os.path.abspath(cwd) if cwd else os.getcwd())

    out = _Stream("stdout", process.stdout, sink, on_output, activity)
    err = _Stream("stderr", process.stderr, sink, on_output, activity)
    if input is not None:
        def feed():
            try:
                process.stdin.write(input.encode("utf-8") if isinstance(input, str) else input)
            except (OSError, ValueError):
                pass
            finally:
                try:
                    process.stdin.close()
                except OSError:
                    pass
        threading.Thread(target=feed, daemon=True).start()

    timed_out = idle = cancelled = False
    next_beat = began + heartbeat_seconds if heartbeat_seconds else None
    killed = []
    try:
        while process.poll() is None:
            now = time.monotonic()
            if timeout is not None and now - began >= timeout:
                timed_out = True
                emit("timeout", pid=process.pid, after_s=round(now - began, 3))
                break
            if idle_timeout is not None and now - last["activity"] >= idle_timeout:
                idle = True
                emit("idle-timeout", pid=process.pid,
                     idle_s=round(now - last["activity"], 3))
                break
            if should_stop is not None:
                try:
                    stop = bool(should_stop())
                except Exception:
                    stop = False
                if stop:
                    cancelled = True
                    emit("cancelled", pid=process.pid)
                    break
            if next_beat is not None and now >= next_beat:
                emit("heartbeat", pid=process.pid, elapsed_s=round(now - began, 3),
                     idle_s=round(now - last["activity"], 3))
                next_beat = now + heartbeat_seconds
            time.sleep(poll_seconds)
    except BaseException:
        # Interrupted (Ctrl-C, SystemExit): the tree goes with us, then the exception does.
        terminate_tree(process.pid, pgid, tag, grace_seconds)
        with _LIVE_LOCK:
            _LIVE.pop(tag, None)
        if log is not None:
            log.close()
        raise

    # Whatever ended the wait, nothing the child started outlives it. On a clean exit this
    # is what catches the dev server a test runner left behind.
    killed = terminate_tree(process.pid, pgid, tag, grace_seconds)
    try:
        returncode = process.wait(timeout=grace_seconds + 5)
    except subprocess.TimeoutExpired:  # pragma: no cover - SIGKILL did not take
        returncode = None
    with _LIVE_LOCK:
        _LIVE.pop(tag, None)
    # A descendant that escaped every signal may still hold a pipe; do not wait on it.
    out.thread.join(timeout=2.0)
    err.thread.join(timeout=2.0)
    if log is not None:
        log.close()
    duration = time.monotonic() - began
    others = [p for p in killed if p != process.pid]
    if others:
        emit("cleanup", pid=process.pid, killed=others)
    result = ProcessResult(argv, returncode=returncode, stdout=out.text(), stderr=err.text(),
                           timed_out=timed_out, idle_timed_out=idle, cancelled=cancelled,
                           duration_s=duration, pid=process.pid, tag=tag, killed=others)
    emit("exited", pid=process.pid, status=result.status, returncode=returncode,
         duration_s=round(duration, 3))
    return result


def _main(args):  # pragma: no cover - debugging aid: python -m wgflib.procs -- argv...
    if args and args[0] == "--":
        args = args[1:]
    result = run(args, on_event=lambda kind, **d: print(f"[procs] {kind} {d}", file=sys.stderr),
                 heartbeat_seconds=5)
    sys.stdout.write(result.stdout)
    sys.stderr.write(result.stderr)
    return 0 if result.ok else (result.returncode or 1)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(_main(sys.argv[1:]))

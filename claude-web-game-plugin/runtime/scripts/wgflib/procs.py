"""Run a child process as something a workflow step owns: the whole tree, observed, and gone
when the step is.

`subprocess.run(..., timeout=)` kills the direct child and nothing else. A `pnpm` that
started `vite`, or a Playwright run whose `webServer` started a dev server, leaves the
grandchild alive and reparented to init - still holding a port, and still holding the pipes
`subprocess.run` is waiting to drain, so a timeout can hang the step it was meant to end.
Everything a Factory step spawns goes through `run()` (to completion) or `spawn()`
(long-lived, e.g. a stdio server) here instead, which:

  * starts the child in a new session (POSIX) or process group (Windows), so the child and
    everything that does not detach itself shares one group that can be signalled at once;
  * on Windows, puts the child in a Job Object limited with
    `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` and no breakaway: every descendant joins the job and
    cannot leave it, so one `TerminateJobObject` ends a tree `taskkill /T` cannot even find
    (a grandchild whose intermediate parent - a .cmd shim, a shell - has exited), and the
    kernel ends whatever is left by itself when the last handle to the job closes, which it
    does when this process dies for any reason, including being killed outright;
  * tags the child's environment with `WGF_PROC_TAG=<unique>` and appends the tag to
    `WGF_PROC_LINEAGE`. Environment is inherited through fork/exec and survives `setsid()`
    and reparenting, so on Linux a descendant that left the group (Playwright starts its
    webServer detached) is still found by reading /proc/<pid>/environ - and a tree owned by
    a nested Factory process is still found by the outer one through the lineage. Elsewhere
    the group is all there is;
  * cleans the tree up whenever the child ends - success, failure, timeout, idle timeout,
    cancellation, or the calling process being interrupted - with SIGTERM, a grace period,
    then SIGKILL, and reports every pid it had to kill;
  * holds the exited child unreaped (Linux, `waitid(WNOWAIT)`) until the tree is gone, so
    neither its pid nor its process-group id can be recycled by an unrelated process while
    cleanup is still signalling them;
  * reads stdout and stderr on threads in bounded chunks, so a chatty child never blocks on a
    full pipe, a grandchild holding a pipe open never blocks the caller, and a child that
    writes gigabytes (with or without newlines) costs a bounded tail of memory;
  * reports what is happening through `on_event(kind, **data)`: `spawned`, `heartbeat`
    (every `heartbeat_seconds`, default `$WGF_HEARTBEAT_SECONDS` or 15, with seconds since
    the child last wrote anything), `timeout`, `idle-timeout`, `cancelled`, `exited`,
    `cleanup`. That is what lets a status command tell a working step from a hung one;
  * names the workflow run whose step owns the tree in `WGF_PROC_RUN` (a comma-separated list,
    outermost run first, like the lineage), when the caller is `bound()` to one. A driver
    killed with SIGKILL runs no cleanup at all; a later resume of the run finds and ends the
    trees it orphaned through that name (`sweep_run`, Linux only - on Windows the job object
    already ended them when the driver's handle closed, so there is nothing left to find).

Nothing global is installed on import except an `atexit` hook that takes down trees this
process still owns. A CLI entry point that wants SIGTERM/SIGHUP to clean up too calls
`install_signal_cleanup()` once, from the main thread.

Standard library only. No provider, tool or step is named here: argv is the caller's.
"""

import atexit
import codecs
import collections
import contextlib
import contextvars
import hashlib
import os
import secrets
import shutil
import signal
import subprocess
import sys
import threading
import time

__all__ = ["run", "spawn", "OwnedProcess", "ProcessResult", "TAG_ENV", "LINEAGE_ENV",
           "RUN_ENV", "HEARTBEAT_ENV", "tagged_pids", "terminate_tree", "live_groups",
           "terminate_all", "install_subreaper", "bound", "install_signal_cleanup",
           "default_heartbeat_seconds", "pid_alive", "run_token", "run_pids", "sweep_run",
           "can_sweep"]

TAG_ENV = "WGF_PROC_TAG"
LINEAGE_ENV = "WGF_PROC_LINEAGE"
RUN_ENV = "WGF_PROC_RUN"
HEARTBEAT_ENV = "WGF_HEARTBEAT_SECONDS"
POSIX = os.name == "posix"
_PROC = "/proc"
_TAIL_LIMIT = 4 * 1024 * 1024  # per stream; a runaway child cannot exhaust memory
_CHUNK = 64 * 1024
_LINE_LIMIT = 64 * 1024        # a "line" with no newline is flushed at this size
_HAVE_WAITID = POSIX and hasattr(os, "waitid") and hasattr(os, "WNOWAIT")

# Every tree this process is currently responsible for: tag -> (pid, pgid, job). An interpreter
# that is exiting - normally, on an unhandled exception, or on a signal turned into
# SystemExit by install_signal_cleanup() - takes these down with it.
_LIVE = {}
_LIVE_LOCK = threading.Lock()
# Held from Popen until the new child is registered, so the subreaper sweep never sees a
# child of ours that no tree has claimed yet.
_SPAWN_LOCK = threading.Lock()


def default_heartbeat_seconds():
    """`$WGF_HEARTBEAT_SECONDS` when it is a positive number, else 15."""
    try:
        value = float(os.environ.get(HEARTBEAT_ENV, ""))
    except ValueError:
        return 15.0
    return value if value > 0 else 15.0


class ProcessResult:
    __slots__ = ("argv", "returncode", "stdout", "stderr", "timed_out", "idle_timed_out",
                 "cancelled", "duration_s", "pid", "tag", "killed", "error", "truncated",
                 "exception")

    def __init__(self, argv, returncode=None, stdout="", stderr="", timed_out=False,
                 idle_timed_out=False, cancelled=False, duration_s=0.0, pid=None, tag=None,
                 killed=(), error=None, truncated=0, exception=None):
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
        self.error = error          # the child could not be started at all: OSError text
        self.truncated = truncated  # characters dropped from the head of stdout + stderr
        self.exception = exception  # the OSError behind `error`, for callers that map it

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


def _carries(environ, tag):
    """True when a NUL-separated environment block names `tag` as its own or an ancestor's."""
    own = f"{TAG_ENV}={tag}".encode()
    lineage_prefix = f"{LINEAGE_ENV}=".encode()
    token = tag.encode()
    for entry in environ.split(b"\0"):
        if entry == own:
            return True
        if entry.startswith(lineage_prefix) and token in entry[len(lineage_prefix):].split(b","):
            return True
    return False


def _carries_run(environ, token):
    """True when a NUL-separated environment block names run `token` in WGF_PROC_RUN."""
    prefix = f"{RUN_ENV}=".encode()
    wanted = token.encode()
    for entry in environ.split(b"\0"):
        if entry.startswith(prefix) and wanted in entry[len(prefix):].split(b","):
            return True
    return False


def _pids_whose_environ(matches):
    """Live, non-zombie pids other than this one whose /proc environ satisfies `matches`."""
    if not os.path.isdir(_PROC):
        return []
    me = os.getpid()
    found = []
    try:
        names = os.listdir(_PROC)
    except OSError:
        return []
    for name in names:
        if not name.isdigit() or int(name) == me:
            continue
        environ = _read(os.path.join(_PROC, name, "environ"))
        if environ and matches(environ) and not _is_zombie(int(name)):
            found.append(int(name))
    return sorted(found)


def tagged_pids(tag):
    """Live pids whose environment carries `tag` (as WGF_PROC_TAG, or in WGF_PROC_LINEAGE
    because a nested owner re-tagged its own children). Linux only; [] elsewhere."""
    if not tag:
        return []
    return _pids_whose_environ(lambda environ: _carries(environ, tag))


def _stat_fields(pid):
    stat = _read(os.path.join(_PROC, str(pid), "stat"), "r")
    if not stat:
        return None
    try:
        return stat.rsplit(")", 1)[1].split()
    except IndexError:
        return None


def _is_zombie(pid):
    fields = _stat_fields(pid)
    return bool(fields) and fields[0] in ("Z", "X")


def pid_alive(pid):
    """True while `pid` exists and is not a zombie (POSIX) / has not exited (Windows)."""
    if pid is None:
        return False
    if POSIX and os.path.isdir(_PROC):
        fields = _stat_fields(pid)
        return fields is not None and fields[0] not in ("Z", "X")
    if not POSIX:
        return _windows_alive(pid)
    try:
        os.kill(pid, 0)
    except PermissionError:
        return True  # exists, someone else's
    except (ProcessLookupError, OSError):
        return False
    return True


_alive = pid_alive


def _group_alive(pgid):
    """True while any non-zombie process is in group `pgid`. A zombie leader the caller has
    not reaped yet still answers killpg(pgid, 0), so /proc is asked first where it exists."""
    if not POSIX or pgid is None:
        return False
    if os.path.isdir(_PROC):
        try:
            names = os.listdir(_PROC)
        except OSError:
            names = []
        for name in names:
            if not name.isdigit():
                continue
            fields = _stat_fields(name)
            if fields and len(fields) > 2 and fields[2] == str(pgid) and fields[0] not in ("Z", "X"):
                return True
        return False
    try:
        os.killpg(pgid, 0)
    except (ProcessLookupError, PermissionError, OSError):
        return False
    return True


def _signal(pids, pgid, sig):
    if POSIX and pgid is not None and pgid > 1:
        try:
            os.killpg(pgid, sig)
        except (ProcessLookupError, PermissionError, OSError):
            pass
    for pid in pids:
        if pid is None or pid <= 1 or pid == os.getpid():
            continue
        try:
            os.kill(pid, sig)
        except (ProcessLookupError, PermissionError, OSError):
            pass


def terminate_tree(pid, pgid, tag, grace_seconds=5.0, job=None):
    """End the child's whole tree, then (with the subreaper on) every orphan it left.

    `job` is the Windows Job Object the tree was put in, as `live_groups()` reports it; the
    caller still owns the handle (`_unregister` closes it)."""
    ended = _terminate_tree(pid, pgid, tag, grace_seconds, job)
    if POSIX:
        ended = sorted(set(ended) | set(
            _sweep_adopted(exclude={pid}, grace_seconds=min(grace_seconds, 1.0))))
    return ended


def _terminate_tree(pid, pgid, tag, grace_seconds=5.0, job=None):
    """End the child's whole tree. Returns the pids that were still alive and signalled.

    The group is signalled as a whole; tagged processes are signalled individually because
    a detached descendant is in a group of its own. Survivors of SIGTERM after
    `grace_seconds` get SIGKILL; descendants that appear while this runs are swept too.

    `pid` must still belong to the caller's child: pass it only while that child is running
    or is an unreaped zombie (otherwise the number may already name someone else). `pgid`
    is only ever signalled while the group has a live member, which is exactly when the
    kernel will not hand that number out again.
    """
    if not POSIX:
        return _terminate_windows(pid, job, grace_seconds)
    targets = set(tagged_pids(tag))
    if pid is not None and pid_alive(pid):
        targets.add(pid)
    group = _group_alive(pgid)
    if not targets and not group:
        return []
    _signal(sorted(targets), pgid if group else None, signal.SIGTERM)
    deadline = time.monotonic() + max(0.0, grace_seconds)
    while time.monotonic() < deadline:
        targets.update(tagged_pids(tag))
        if not any(pid_alive(p) for p in targets) and not _group_alive(pgid):
            return sorted(targets)
        time.sleep(0.05)
    # SIGKILL whatever is left; a descendant that forked during the grace period, or while
    # dying, is picked up by the next sweep.
    for _ in range(5):
        targets.update(tagged_pids(tag))
        survivors = sorted(p for p in targets if pid_alive(p))
        group = _group_alive(pgid)
        if not survivors and not group:
            break
        _signal(survivors, pgid if group else None, signal.SIGKILL)
        for _ in range(20):
            if not any(pid_alive(p) for p in survivors) and not _group_alive(pgid):
                break
            time.sleep(0.05)
    return sorted(targets)


# -- orphans adopted by this process ----------------------------------------------------------

# With PR_SET_CHILD_SUBREAPER set, a descendant whose parent dies is reparented to this
# process instead of init. That closes the one escape the tag and the group cannot see: a
# daemon that detaches (setsid) AND execs with an empty environment. Opt-in, Linux only,
# and only for a process whose children all come from this module - the Factory CLI, where
# EveryChildGoesThroughProcs enforces that - because every adopted orphan that no live tree
# claims is ended.
_SUBREAPER = {"on": False}
_PR_SET_CHILD_SUBREAPER = 36


def install_subreaper(enabled=True):
    """Make this process the subreaper of everything it starts. Returns True if active."""
    if not POSIX or not os.path.isdir(_PROC) or not sys.platform.startswith("linux"):
        return False
    try:
        import ctypes
        libc = ctypes.CDLL(None, use_errno=True)
        if libc.prctl(_PR_SET_CHILD_SUBREAPER, 1 if enabled else 0, 0, 0, 0) != 0:
            return False
    except (OSError, AttributeError):
        return False
    _SUBREAPER["on"] = bool(enabled)
    return _SUBREAPER["on"]


def _adopted_children(exclude):
    """(pid, zombie) for each orphan this process adopted that no live tree owns.

    Only children outside this process's own session count: everything procs starts gets a
    session of its own, so an orphan from one of its trees is never in ours, while a child
    some other code started with plain subprocess (and is waiting on) is.
    """
    me = str(os.getpid())
    try:
        own_session = str(os.getsid(0))
    except OSError:
        return []
    claimed = {entry[0] for entry in live_groups().values()} | {p for p in exclude if p}
    live_tags = set(live_groups())
    found = []
    for name in os.listdir(_PROC):
        if not name.isdigit() or int(name) in claimed:
            continue
        fields = _stat_fields(int(name))
        if not fields or len(fields) < 4 or fields[1] != me or fields[3] == own_session:
            continue
        environ = _read(os.path.join(_PROC, name, "environ")) or b""
        if any(_carries(environ, tag) for tag in live_tags):
            continue  # a descendant of a tree still running on another thread
        found.append((int(name), fields[0] in ("Z", "X")))
    return found


def _sweep_adopted(exclude=(), grace_seconds=1.0):
    """End and reap every adopted orphan; repeat while ending one orphans another."""
    if not _SUBREAPER["on"]:
        return []
    ended = []
    for _ in range(10):
        with _SPAWN_LOCK:
            found = _adopted_children(set(exclude))
        if not found:
            break
        living = [pid for pid, zombie in found if not zombie]
        _signal(living, None, signal.SIGTERM)
        deadline = time.monotonic() + grace_seconds
        while living and time.monotonic() < deadline and any(pid_alive(p) for p in living):
            time.sleep(0.05)
        _signal([p for p in living if pid_alive(p)], None, signal.SIGKILL)
        for pid, _ in found:
            try:
                os.waitpid(pid, 0)
            except ChildProcessError:
                pass
        ended.extend(living)
    return ended


# -- Windows: the job object ------------------------------------------------------------------

# Windows has no process group to signal and no /proc to read, and `taskkill /T` walks only the
# parent-child chain that is alive at the moment it runs: a grandchild whose intermediate parent
# (a .cmd shim, a shell, a launcher) has already exited is not reachable from the leader, and
# the tag sweep that catches exactly that on Linux needs /proc/<pid>/environ. Observed: a
# `wgf cancel` ended the run while the agent host it had started, whose parent was already gone,
# and a `vite preview` under it kept running for an hour.
#
# A Job Object closes both holes. Every process a member starts joins the job, and a member
# cannot leave it - JOB_OBJECT_LIMIT_BREAKAWAY_OK is deliberately not set, so
# CREATE_BREAKAWAY_FROM_JOB fails - however it was created: detached, in a new console, or by a
# shim that has since exited. TerminateJobObject ends every member at once, and names them
# first (QueryInformationJobObject), so cleanup can report the pids it killed here too. And
# JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE makes the kernel do the same when the last handle to the
# job closes, which it does when this process dies for any reason, including TerminateProcess:
# that is the "the driver died, its trees were orphaned" case, ended with nobody having to find
# the pids afterwards. See docs/agent-lifecycle.md, "Windows".

_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
_JOB_EXTENDED_LIMIT_INFORMATION = 9        # JobObjectExtendedLimitInformation
_JOB_BASIC_PROCESS_ID_LIST = 3             # JobObjectBasicProcessIdList
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_SYNCHRONIZE = 0x00100000
_ERROR_ACCESS_DENIED = 5
_ERROR_MORE_DATA = 234
_WAIT_OBJECT_0 = 0
# kernel32 (False once it could not be loaded), the limit structure, whether a job can be made
# here at all, and how many times assigning a live child to one was refused.
_WIN = {"k32": None, "struct": None, "jobs": None, "refused": 0}


def _kernel32():
    """kernel32 with the entry points used here, typed, or None where it cannot be loaded.

    The return types matter: a HANDLE is a pointer and the default `c_int` restype truncates
    it on 64-bit Windows."""
    if _WIN["k32"] is None:
        try:
            import ctypes
            from ctypes import wintypes
            lib = ctypes.WinDLL("kernel32", use_last_error=True)
            handle, dword, flag = ctypes.c_void_p, wintypes.DWORD, wintypes.BOOL
            lib.CreateJobObjectW.restype = handle
            lib.CreateJobObjectW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
            lib.SetInformationJobObject.restype = flag
            lib.SetInformationJobObject.argtypes = [handle, ctypes.c_int, ctypes.c_void_p, dword]
            lib.QueryInformationJobObject.restype = flag
            lib.QueryInformationJobObject.argtypes = [handle, ctypes.c_int, ctypes.c_void_p,
                                                      dword, ctypes.POINTER(dword)]
            lib.AssignProcessToJobObject.restype = flag
            lib.AssignProcessToJobObject.argtypes = [handle, handle]
            lib.TerminateJobObject.restype = flag
            lib.TerminateJobObject.argtypes = [handle, wintypes.UINT]
            lib.OpenProcess.restype = handle
            lib.OpenProcess.argtypes = [dword, flag, dword]
            lib.WaitForSingleObject.restype = dword
            lib.WaitForSingleObject.argtypes = [handle, dword]
            lib.CloseHandle.restype = flag
            lib.CloseHandle.argtypes = [handle]
            _WIN["k32"] = lib
        except (ImportError, OSError, AttributeError):  # pragma: no cover - not Windows
            _WIN["k32"] = False
    return _WIN["k32"] or None


def _limit_struct():
    """JOBOBJECT_EXTENDED_LIMIT_INFORMATION as ctypes sees it (cached)."""
    if _WIN["struct"] is None:
        import ctypes

        class _IoCounters(ctypes.Structure):
            _fields_ = [("ReadOperationCount", ctypes.c_ulonglong),
                        ("WriteOperationCount", ctypes.c_ulonglong),
                        ("OtherOperationCount", ctypes.c_ulonglong),
                        ("ReadTransferCount", ctypes.c_ulonglong),
                        ("WriteTransferCount", ctypes.c_ulonglong),
                        ("OtherTransferCount", ctypes.c_ulonglong)]

        class _BasicLimits(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong),
                        ("PerJobUserTimeLimit", ctypes.c_longlong),
                        ("LimitFlags", ctypes.c_ulong),
                        ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t),
                        ("ActiveProcessLimit", ctypes.c_ulong),
                        ("Affinity", ctypes.c_size_t),
                        ("PriorityClass", ctypes.c_ulong),
                        ("SchedulingClass", ctypes.c_ulong)]

        class _ExtendedLimits(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", _BasicLimits),
                        ("IoInfo", _IoCounters),
                        ("ProcessMemoryLimit", ctypes.c_size_t),
                        ("JobMemoryLimit", ctypes.c_size_t),
                        ("PeakProcessMemoryUsed", ctypes.c_size_t),
                        ("PeakJobMemoryUsed", ctypes.c_size_t)]

        _WIN["struct"] = _ExtendedLimits
    return _WIN["struct"]


def _create_job():
    """A kill-on-close Job Object, or None where one cannot be made."""
    lib = _kernel32()
    if lib is None:
        return None
    import ctypes
    handle = lib.CreateJobObjectW(None, None)
    if not handle:
        return None
    limits = _limit_struct()()
    limits.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not lib.SetInformationJobObject(handle, _JOB_EXTENDED_LIMIT_INFORMATION,
                                       ctypes.byref(limits), ctypes.sizeof(limits)):
        _close_job(handle)
        return None
    return int(handle)


def _close_job(job):
    """Close the handle. With KILL_ON_JOB_CLOSE this also ends anything still in the job."""
    lib = _kernel32()
    if lib is not None and job:
        lib.CloseHandle(job)


def _assign_job(job, process):
    """Put `process`, and so everything it starts, in `job`. True when it took.

    A refusal while the child is still alive means jobs do not hold on this installation (an
    older Windows whose own job forbids nesting); that is remembered, because it is the only
    thing that makes the Windows guarantees untrue (see `_jobs_hold`)."""
    lib = _kernel32()
    handle = getattr(process, "_handle", None)
    if lib is None or not job or handle is None:
        return False
    import ctypes
    if lib.AssignProcessToJobObject(job, ctypes.c_void_p(int(handle))):
        return True
    # A child that exited in the window between Popen and here cannot be assigned, and that
    # says nothing about job support.
    if _windows_alive(process.pid):
        _WIN["refused"] += 1
    return False


def _job_pids(job, capacity=256):
    """The pids currently in `job`, this process never among them."""
    lib = _kernel32()
    if lib is None or not job:
        return []
    import ctypes
    from ctypes import wintypes
    me = os.getpid()
    for _ in range(3):
        class _IdList(ctypes.Structure):
            _fields_ = [("NumberOfAssignedProcesses", ctypes.c_ulong),
                        ("NumberOfProcessIdsInList", ctypes.c_ulong),
                        ("ProcessIdList", ctypes.c_size_t * capacity)]

        listing = _IdList()
        returned = wintypes.DWORD(0)
        ok = lib.QueryInformationJobObject(job, _JOB_BASIC_PROCESS_ID_LIST,
                                           ctypes.byref(listing), ctypes.sizeof(listing),
                                           ctypes.byref(returned))
        if ok:
            found = (int(listing.ProcessIdList[i])
                     for i in range(min(listing.NumberOfProcessIdsInList, capacity)))
            return sorted(p for p in found if p and p != me)
        if ctypes.get_last_error() != _ERROR_MORE_DATA:
            return []
        capacity = max(capacity * 4, int(listing.NumberOfAssignedProcesses) + 8)
    return []  # pragma: no cover - more than 16k processes in one tree


def _windows_alive(pid):
    """True while `pid` has not exited.

    `os.kill(pid, 0)` is the wrong question on Windows. It is satisfied by any open handle to
    an already exited process - Popen keeps one, and so do we - so a dead child reads as alive
    and cleanup spins over it to no effect; and `os.kill` there is TerminateProcess for every
    signal value but the two console events and the 0 current CPython special-cases, which
    makes a liveness probe one argument away from killing what it asked about. Ask the kernel
    instead: the process object is signalled exactly once the process has exited."""
    lib = _kernel32()
    if lib is None or not pid:  # pragma: no cover - not Windows
        return False
    import ctypes
    handle = lib.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION | _SYNCHRONIZE, False, int(pid))
    if not handle:
        return ctypes.get_last_error() == _ERROR_ACCESS_DENIED  # exists, someone else's
    try:
        # WAIT_OBJECT_0 = the process object is signalled = it has exited. Anything else
        # (WAIT_TIMEOUT, and WAIT_FAILED, which should not happen) counts as still running:
        # cleanup may then signal a corpse, never skip a survivor.
        return lib.WaitForSingleObject(handle, 0) != _WAIT_OBJECT_0
    finally:
        lib.CloseHandle(handle)


def _jobs_hold():
    """True when a tree started here is held by a kill-on-close job: a job can be made, and
    no assignment of a live child to one has been refused in this process."""
    if POSIX:
        return False
    if _WIN["jobs"] is None:
        job = _create_job()
        _WIN["jobs"] = job is not None
        _close_job(job)
    return bool(_WIN["jobs"]) and not _WIN["refused"]


def _terminate_windows(pid, job=None, grace_seconds=5.0):
    """End the tree on Windows: the job object, which holds every descendant however it was
    started, then `taskkill /T /F` on the leader as a belt-and-braces for a tree that has no
    job (assignment refused) and for anything a job never held. Returns the pids it ended."""
    lib = _kernel32()
    ended = []
    if job and lib is not None:
        ended = _job_pids(job)
        lib.TerminateJobObject(job, 1)
        # TerminateProcess is asynchronous; give the members a moment to actually go.
        deadline = time.monotonic() + max(0.0, min(grace_seconds, 5.0))
        while time.monotonic() < deadline and any(_windows_alive(p) for p in ended):
            time.sleep(0.05)
    if pid is not None:
        try:
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)], capture_output=True,
                           timeout=30)
        except (OSError, subprocess.SubprocessError):
            pass
        ended.append(pid)
    return sorted(set(ended))


def live_groups():
    """Every tree this process is responsible for: tag -> (pid, pgid, job). `pgid` is POSIX
    only, `job` the Windows Job Object handle; both are None on the other platform."""
    with _LIVE_LOCK:
        return dict(_LIVE)


def _register(tag, pid, pgid, job=None):
    with _LIVE_LOCK:
        _LIVE[tag] = (pid, pgid, job)


def _unregister(tag):
    """Forget the tree, and close its job handle - the one place that does, so the handle is
    never closed twice and never leaks. Closing it kills whatever is still in the job."""
    with _LIVE_LOCK:
        entry = _LIVE.pop(tag, None)
    if entry is not None and entry[2]:
        _close_job(entry[2])


def _owned_job(tag, job):
    """`job`, while the registry still holds this tree. None once something else has ended it
    (`terminate_all` from another thread, as golden/run.py does): the handle is closed then,
    and a closed handle value may already name an unrelated object."""
    return job if job and tag in live_groups() else None


def terminate_all(grace_seconds=2.0):
    """Take down every tree this process still owns. Registered with atexit."""
    for tag, (pid, pgid, job) in live_groups().items():
        try:
            terminate_tree(pid, pgid, tag, grace_seconds, job=job)
        except Exception:
            pass
        finally:
            _unregister(tag)


atexit.register(terminate_all)


# -- a run's trees, after its driver died ------------------------------------------------------

# SIGKILL of the process driving a workflow run runs no cleanup: no atexit, no signal handler,
# and the subreaper dies with it. Every tree a step of the run started is orphaned, and nothing
# the next driver reads names their pids. What survives is the environment: every child of a
# step carries the run's token in WGF_PROC_RUN, so the driver that resumes the run can find
# them and end them before it executes the step again.

def run_token(run_id, scope=None):
    """The WGF_PROC_RUN token of a run: `<run-id>@<12 hex digits of scope>`.

    `scope` is what makes a run id unique - the directory the run store lives in. Two
    checkouts (or two test suites) can hold a run called `run-1` at the same time, and a
    sweep of one must never reach the other's children."""
    digest = hashlib.sha256(os.path.abspath(scope or "").encode("utf-8")).hexdigest()[:12]
    return f"{run_id}@{digest}"


def _can_read_environs():
    """True where another process's environment can be read (Linux /proc)."""
    return POSIX and os.path.isdir(_PROC)


def can_sweep():
    """True where a resume can account for every tree a dead driver of the run left.

    Two different reasons, and `sweep_run` does the right thing for each:

      * Linux: the orphans are still there and can be found by their environment (/proc).
      * Windows: there are no orphans to find. Every tree was in a Job Object limited with
        KILL_ON_JOB_CLOSE, and the kernel closed the dead driver's handle - the only handle -
        when it died, however it died, which ended the job. `_jobs_hold()` is what makes this
        true; where a job cannot be made, or an assignment was refused, this is False and the
        caller reports honestly that it cannot look.

    False on macOS (no /proc, no jobs): an orphan of a dead driver is not found there.
    """
    return _can_read_environs() if POSIX else _jobs_hold()


def _ancestors():
    """This process and every process above it, by parent pid (Linux)."""
    found = {os.getpid()}
    pid = os.getpid()
    while pid and pid > 1:
        fields = _stat_fields(pid)
        if not fields or len(fields) < 2 or not fields[1].isdigit():
            break
        pid = int(fields[1])
        found.add(pid)
    return found


def run_pids(token):
    """Live pids naming run `token` in WGF_PROC_RUN, never this process, one of its
    ancestors, or a process of a tree this process owns right now. Linux only; []
    elsewhere."""
    if not token or not _can_read_environs():
        return []
    protected = _ancestors() | {entry[0] for entry in live_groups().values()}
    live_tags = list(live_groups())

    def matches(environ):
        return _carries_run(environ, token) and not any(
            _carries(environ, tag) for tag in live_tags)

    return [pid for pid in _pids_whose_environ(matches) if pid not in protected]


def sweep_run(token, grace_seconds=5.0):
    """End every process still carrying run `token`: SIGTERM, `grace_seconds`, SIGKILL,
    repeated for descendants that fork meanwhile. Returns the pids it found alive and
    signalled, [] when there is nothing to end, or None where it cannot look. Processes that
    do not carry the token - untagged ones, and those of any other run - are never signalled.

    On Windows there is nothing to end and nothing to look at: the dead driver's job objects
    took its trees with them (`can_sweep`). A command-line scan is deliberately not done
    instead - matching a run id or a checkout path in `Get-CimInstance Win32_Process` output
    would kill by guess (a `vite preview` command line names neither; an editor or another
    session in the same checkout matches), it cannot tell two runs in one checkout apart, and
    it would cost a PowerShell process on the path that must be quick and safe. The job object
    is the answer, not a weaker signal next to it."""
    if not can_sweep():
        return None
    if not POSIX:
        return []
    targets = set(run_pids(token))
    if not targets:
        return []
    _signal(sorted(targets), None, signal.SIGTERM)
    deadline = time.monotonic() + max(0.0, grace_seconds)
    while time.monotonic() < deadline:
        targets.update(run_pids(token))
        if not any(pid_alive(p) for p in targets):
            return sorted(targets)
        time.sleep(0.05)
    for _ in range(5):
        targets.update(run_pids(token))
        survivors = sorted(p for p in targets if pid_alive(p))
        if not survivors:
            break
        _signal(survivors, None, signal.SIGKILL)
        for _ in range(20):
            if not any(pid_alive(p) for p in survivors):
                break
            time.sleep(0.05)
    return sorted(targets)


_SIGNALS_INSTALLED = {"done": False, "exiting": False}


def install_signal_cleanup(signals=None):
    """Make SIGTERM and SIGHUP end this process through SystemExit, so every `run()` still
    waiting unwinds and takes its tree down, and atexit sweeps the rest.

    Children live in sessions of their own, so a signal sent to the Factory's process or
    terminal group never reaches them; without this a `kill <wgf pid>` orphans the whole
    tree. Only signals whose handler is still the default are taken (an ignored SIGHUP under
    nohup stays ignored). A repeat of the signal while cleanup is running is ignored, so
    cleanup is not cut short; SIGKILL is the escalation. Main thread only; returns the
    signals it took, [] when it cannot install anything (not the main thread, no POSIX).
    """
    if not POSIX or threading.current_thread() is not threading.main_thread():
        return []
    if signals is None:
        signals = [signal.SIGTERM, signal.SIGHUP]
    taken = []

    def handler(signum, frame):
        if _SIGNALS_INSTALLED["exiting"]:
            return
        _SIGNALS_INSTALLED["exiting"] = True
        raise SystemExit(128 + signum)

    for sig in signals:
        try:
            if signal.getsignal(sig) is not signal.SIG_DFL:
                continue
            signal.signal(sig, handler)
            taken.append(sig)
        except (ValueError, OSError):
            continue
    _SIGNALS_INSTALLED["done"] = True
    return taken


# -- the step a process belongs to ---------------------------------------------------------

# (on_event, should_stop) of the workflow step executing on this thread, set by the engine
# around every execution. A module's runner calls run() without knowing about workflows and
# still reports to, and is cancellable by, the step it runs under.
_BOUND = contextvars.ContextVar("wgf_procs_bound", default=None)
# The run_token() of the workflow run the executing step belongs to, if any.
_RUN = contextvars.ContextVar("wgf_procs_run", default=None)


@contextlib.contextmanager
def bound(on_event=None, should_stop=None, run=None):
    """Within this block, every run() also reports to `on_event` and honours `should_stop`,
    and every child run() or spawn() starts names `run` (a run_token) in WGF_PROC_RUN."""
    token = _BOUND.set((on_event, should_stop))
    run_mark = _RUN.set(run) if run else None
    try:
        yield
    finally:
        if run_mark is not None:
            _RUN.reset(run_mark)
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


# -- starting -------------------------------------------------------------------------------

def _child_env(env, tag):
    base = dict(os.environ if env is None else env)
    lineage = [t for t in (os.environ.get(LINEAGE_ENV) or "").split(",") if t]
    # A tree owned by a nested Factory process stays findable by every owner above it.
    base[LINEAGE_ENV] = ",".join(lineage + [tag])
    base[TAG_ENV] = tag
    # The runs whose steps own this tree, outermost first: a run started by `wgf` inside
    # another run's step is still found by a sweep of the outer run.
    runs = [r for r in (os.environ.get(RUN_ENV) or "").split(",") if r]
    current = _RUN.get()
    if current and (not runs or runs[-1] != current):
        runs.append(current)
    if runs:
        base[RUN_ENV] = ",".join(runs)
    else:
        base.pop(RUN_ENV, None)
    return base


def _resolved(argv, child_env):
    """`argv` with its program resolved on PATH, for the platforms that need it.

    A shell applies PATHEXT; CreateProcess does not. Every tool the Factory starts in a game
    repository - `pnpm`, and anything `pnpm exec` stands in for - is installed on Windows as
    `pnpm.CMD`, so `subprocess.Popen(["pnpm", ...])` there fails with WinError 2 before the
    child exists, and the step reports a tool that is plainly installed as not startable
    (found by MV-4 running the suite on Windows). Resolution uses the child's own PATH, so it
    is the same lookup the child would have had. A name that resolves to nothing is left
    exactly as given: the caller's "could not be started" error is the right report, and it
    should name what the caller asked for."""
    if POSIX or not argv:
        return argv
    program = argv[0]
    if os.path.dirname(program):
        return argv
    found = shutil.which(program, path=child_env.get("PATH") or child_env.get("Path"))
    # shutil.which answers "exists and is executable", and a directory satisfies both on
    # Windows: a PATH entry whose parent holds a directory of the same name as the program
    # (`...\Local\pnpm`) resolves to it and CreateProcess then fails with WinError 267, which
    # reads as a broken working directory rather than a bad lookup. Only a file is a program.
    return [found, *argv[1:]] if found and os.path.isfile(found) else argv


def _session_kwargs():
    if POSIX:
        return {"start_new_session": True}
    return {"creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)}  # pragma: no cover


def _exited(process):
    """True once the child has exited. On Linux the child is left unreaped (a zombie), so its
    pid and group id stay reserved until cleanup is done and `process.wait()` reaps it."""
    if process.returncode is not None:
        return True
    if _HAVE_WAITID:
        try:
            info = os.waitid(os.P_PID, process.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
        except ChildProcessError:
            # Reaped by someone else (a SIGCHLD handler, os.wait()); Popen will say so.
            return process.poll() is not None
        except OSError:
            return process.poll() is not None
        return info is not None and info.si_pid == process.pid
    return process.poll() is not None


class OwnedProcess:
    """A long-lived child whose whole tree this process owns (see `spawn`).

    `.process` is the `subprocess.Popen`; talk to it through its pipes. `close()` (also on
    `with` exit, and at interpreter exit) closes stdin, gives the child `grace_seconds` to
    leave on its own, then terminates the tree and reaps the child. Safe to call twice.
    """

    def __init__(self, process, tag, argv, job=None):
        self.process = process
        self.tag = tag
        self.argv = list(argv)
        self.pid = process.pid
        self.pgid = process.pid if POSIX else None
        self.job = job   # Windows: the Job Object holding the tree; `_unregister` closes it
        self.killed = []
        self._closed = False
        self._lock = threading.Lock()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False

    def alive(self):
        return not _exited(self.process)

    def tree(self):
        """Live pids of this tree that can be found (tagged, Linux) plus the child."""
        found = set(tagged_pids(self.tag))
        if self.alive():
            found.add(self.pid)
        return sorted(found)

    def close(self, grace_seconds=5.0, wait_seconds=None, close_streams=True):
        """Close stdin, wait up to `wait_seconds` (default: `grace_seconds`) for the child to
        exit by itself, then terminate whatever is left of the tree and reap the child.
        Returns the exit code. `close_streams=False` leaves stdout/stderr open for a reader
        thread to drain to EOF; the caller closes them."""
        with self._lock:
            if self._closed:
                return self.process.returncode
            self._closed = True
        wait = grace_seconds if wait_seconds is None else wait_seconds
        try:
            if self.process.stdin is not None:
                try:
                    self.process.stdin.close()
                except (OSError, ValueError):
                    pass
            deadline = time.monotonic() + max(0.0, wait)
            while not _exited(self.process) and time.monotonic() < deadline:
                time.sleep(0.02)
            alive = not _exited(self.process)
            self.killed = terminate_tree(self.pid if alive or _HAVE_WAITID else None,
                                         self.pgid, self.tag, grace_seconds,
                                         job=_owned_job(self.tag, self.job))
        finally:
            try:
                self.process.wait(timeout=grace_seconds + 5)
            except subprocess.TimeoutExpired:  # pragma: no cover - SIGKILL did not take
                pass
            _unregister(self.tag)       # closes the job handle; do not reuse it
            self.job = None
            for stream in (self.process.stdout, self.process.stderr) if close_streams else ():
                if stream is not None:
                    try:
                        stream.close()
                    except (OSError, ValueError):
                        pass
        return self.process.returncode

    terminate = close


def spawn(argv, cwd=None, env=None, **popen_kwargs):
    """Start a long-lived child in its own session, tagged, registered for cleanup at
    interpreter exit. Pipes and text mode are the caller's (`popen_kwargs` go to Popen, except
    the session and environment, which are ours). Raises OSError when it cannot start."""
    argv = [str(part) for part in argv]
    tag = secrets.token_hex(8)
    for reserved in ("start_new_session", "creationflags", "preexec_fn", "process_group"):
        popen_kwargs.pop(reserved, None)
    popen_kwargs.update(_session_kwargs())
    child_env = _child_env(env, tag)
    with _SPAWN_LOCK:
        job = None if POSIX else _create_job()
        process = subprocess.Popen(_resolved(argv, child_env), cwd=cwd, env=child_env,
                                   **popen_kwargs)
        if job is not None and not _assign_job(job, process):
            _close_job(job)   # nothing is in it yet; closing kills nothing
            job = None
        _register(tag, process.pid, process.pid if POSIX else None, job)
    return OwnedProcess(process, tag, argv, job)


# -- running --------------------------------------------------------------------------------

class _Stream:
    """Drains one pipe on a thread in bounded chunks; keeps a bounded tail of text and the
    time of the last write, and hands complete lines to the sink and the line callback."""

    def __init__(self, name, pipe, sink, on_line, activity):
        self.name = name
        self.chunks = collections.deque()
        self.size = 0
        self.dropped = 0
        self._sink = sink
        self._on_line = on_line
        self._activity = activity
        self._decoder = codecs.getincrementaldecoder("utf-8")("replace")
        self._partial = ""
        self.thread = threading.Thread(target=self._pump, args=(pipe,), daemon=True)
        self.thread.start()

    def _keep(self, text):
        if not text:
            return
        self.chunks.append(text)
        self.size += len(text)
        while self.size > _TAIL_LIMIT and len(self.chunks) > 1:
            dropped = self.chunks.popleft()
            self.size -= len(dropped)
            self.dropped += len(dropped)
        if self.size > _TAIL_LIMIT:  # one chunk larger than the whole limit
            only = self.chunks.pop()
            cut = len(only) - _TAIL_LIMIT
            self.chunks.append(only[cut:])
            self.size -= cut
            self.dropped += cut

    def _line(self, line):
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

    def _feed(self, text):
        self._keep(text)
        if self._sink is None and self._on_line is None:
            return
        pending = self._partial + text
        lines = pending.split("\n")
        self._partial = lines.pop()
        for line in lines:
            self._line(line + "\n")
        if len(self._partial) >= _LINE_LIMIT:
            self._line(self._partial)
            self._partial = ""

    def _pump(self, pipe):
        read = getattr(pipe, "read1", None) or pipe.read
        try:
            while True:
                data = read(_CHUNK)
                if not data:
                    break
                self._activity()
                self._feed(self._decoder.decode(data))
        except (OSError, ValueError):
            pass
        finally:
            try:
                self._feed(self._decoder.decode(b"", final=True))
                if self._partial:
                    self._line(self._partial)
                    self._partial = ""
            except Exception:
                pass
            try:
                pipe.close()
            except OSError:
                pass

    def text(self):
        return "".join(self.chunks)


def run(argv, cwd=None, timeout=None, env=None, input=None, on_event=None, on_output=None,
        should_stop=None, heartbeat_seconds=None, idle_timeout=None, log_path=None,
        grace_seconds=5.0, poll_seconds=0.1, stderr_to_stdout=False):
    """Run `argv` to completion as an owned process tree. Never raises for the child's own
    failure: a missing executable is `error`, a non-zero exit is `returncode`.

    `timeout`       wall-clock seconds before the tree is terminated (`timed_out`).
    `idle_timeout`  seconds without output before the tree is terminated (`idle_timed_out`).
    `should_stop`   polled; returning True terminates the tree (`cancelled`).
    `on_event`      `(kind, **data)`, lifecycle and heartbeat; exceptions are swallowed.
    `on_output`     `(stream, line)` per line of stdout/stderr.
    `heartbeat_seconds`  default `$WGF_HEARTBEAT_SECONDS`, else 15; 0 turns heartbeats off.
    `log_path`      every line is also appended here, prefixed by stream. A log that cannot
                    be opened is skipped, never fatal.
    `stderr_to_stdout`  one interleaved stream, like `stderr=subprocess.STDOUT`; `stderr`
                    is then always "".
    `input`         str or bytes written to stdin, which is then closed; otherwise stdin is
                    /dev/null, so a child can never wait on a prompt.

    stdout/stderr keep the last 4 MiB of each stream (`truncated` counts what was dropped).
    """
    argv = [str(part) for part in argv]
    on_event, should_stop = _with_bound(on_event, should_stop)
    if heartbeat_seconds is None:
        heartbeat_seconds = default_heartbeat_seconds()
    tag = secrets.token_hex(8)
    child_env = _child_env(env, tag)

    def emit(kind, **data):
        if on_event is not None:
            try:
                on_event(kind, **data)
            except Exception:
                pass

    log = None
    if log_path:
        try:
            parent = os.path.dirname(os.path.abspath(log_path))
            os.makedirs(parent, exist_ok=True)
            log = open(log_path, "a", encoding="utf-8")
        except OSError:
            log = None
    log_lock = threading.Lock()

    def sink(stream, line):
        if log is not None:
            with log_lock:
                try:
                    log.write(f"[{stream}] {line}" if line.endswith("\n")
                              else f"[{stream}] {line}\n")
                    log.flush()
                except (OSError, ValueError):
                    pass

    def close_log():
        if log is not None:
            with log_lock:
                try:
                    log.close()
                except OSError:
                    pass

    last = {"activity": time.monotonic()}

    def activity():
        last["activity"] = time.monotonic()

    began = time.monotonic()
    job = None
    try:
        with _SPAWN_LOCK:
            job = None if POSIX else _create_job()
            process = subprocess.Popen(
                _resolved(argv, child_env), cwd=cwd, env=child_env,
                stdin=subprocess.PIPE if input is not None else subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT if stderr_to_stdout else subprocess.PIPE,
                **_session_kwargs())
            if job is not None and not _assign_job(job, process):
                _close_job(job)   # nothing is in it yet; closing kills nothing
                job = None
            _register(tag, process.pid, process.pid if POSIX else None, job)
    except (OSError, ValueError) as exc:
        _close_job(job)
        close_log()
        error = f"{type(exc).__name__}: {exc}"
        emit("exited", status="not-started", error=error)
        return ProcessResult(argv, error=error, tag=tag, duration_s=time.monotonic() - began,
                             exception=exc)

    pgid = process.pid if POSIX else None
    timed_out = idle = cancelled = False
    next_beat = began + heartbeat_seconds if heartbeat_seconds else None

    def cleanup():
        # The leader is running, or an unreaped zombie (waitid WNOWAIT): its pid is ours.
        leader = process.pid if (process.returncode is None) else None
        try:
            return terminate_tree(leader, pgid, tag, grace_seconds,
                                  job=_owned_job(tag, job))
        finally:
            try:
                process.wait(timeout=grace_seconds + 5)
            except subprocess.TimeoutExpired:  # pragma: no cover - SIGKILL did not take
                pass
            _unregister(tag)

    out = err = None
    try:
        # On Windows `job` says whether the tree is actually held (see `_jobs_hold`); a step
        # that reports False has the pre-job-object limits, and is worth reading in a log.
        emit("spawned", pid=process.pid, pgid=pgid, argv0=os.path.basename(argv[0]),
             cwd=os.path.abspath(cwd) if cwd else os.getcwd(),
             **({} if POSIX else {"job": job is not None}))

        out = _Stream("stdout", process.stdout, sink if log else None, on_output, activity)
        err = None if stderr_to_stdout else _Stream("stderr", process.stderr,
                                                    sink if log else None, on_output, activity)
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

        while not _exited(process):
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
        # If a second interrupt cuts this short the tree is still in _LIVE, and atexit
        # finishes the job.
        try:
            cleanup()
        finally:
            close_log()
        raise

    # Whatever ended the wait, nothing the child started outlives it. On a clean exit this
    # is what catches the dev server a test runner left behind.
    killed = cleanup()
    returncode = process.returncode
    # A descendant that escaped every signal may still hold a pipe; do not wait on it.
    for stream in (out, err):
        if stream is not None:
            stream.thread.join(timeout=2.0)
    close_log()
    duration = time.monotonic() - began
    others = [p for p in killed if p != process.pid]
    if others:
        emit("cleanup", pid=process.pid, killed=others)
    result = ProcessResult(argv, returncode=returncode, stdout=out.text(),
                           stderr=err.text() if err is not None else "",
                           timed_out=timed_out, idle_timed_out=idle, cancelled=cancelled,
                           duration_s=duration, pid=process.pid, tag=tag, killed=others,
                           truncated=out.dropped + (err.dropped if err is not None else 0))
    emit("exited", pid=process.pid, status=result.status, returncode=returncode,
         duration_s=round(duration, 3))
    return result


def _main(args):  # pragma: no cover - debugging aid: python -m wgflib.procs -- argv...
    if args and args[0] == "--":
        args = args[1:]
    install_signal_cleanup()
    result = run(args, on_event=lambda kind, **d: print(f"[procs] {kind} {d}", file=sys.stderr),
                 heartbeat_seconds=5)
    sys.stdout.write(result.stdout)
    sys.stderr.write(result.stderr)
    return 0 if result.ok else (result.returncode or 1)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(_main(sys.argv[1:]))

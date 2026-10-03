"""One host port, one command at a time: a machine-wide lock for the template's fixed ports.

The pinned template's `playwright.config.ts` serves the build with `pnpm preview --port 4173
--strictPort` and `reuseExistingServer: false`: right for one checkout (a stray server is
never mistaken for this build), fatal for two. Two Factory runs on one machine - two
titles, a 2D and a 3D validation - each run the game's own suites, and whichever reaches the
port second fails with "http://localhost:4173 is already used" and burns its retries
(found live, 2026-10-03: a greybox smoke check failed three times while the other run's
smoke suite held the port). The file is template-owned and conformance-checked, so a game
cannot move its port; the Factory serializes instead.

`hold(port)` is an exclusive, cross-process lock on `<lock dir>/port-<port>.lock`, taken
with the operating system's own file locking (`fcntl.flock` on POSIX, `msvcrt.locking` on
Windows). The kernel releases it when the holder's file handle closes - on exit, on a crash,
on SIGKILL or TerminateProcess - so there is no stale lock to detect or break: a holder
that is gone holds nothing. Who holds it is written beside it (`port-<port>.holder.json`:
pid, run, command, since) for the message a waiter shows; that file is information only,
never the lock, and a stale one is simply overwritten by the next holder.

The lock only orders Factory commands. A process outside it - a developer agent's own
`pnpm test:e2e` or `pnpm preview` in another run - can still be listening on the port, and
`--strictPort` would fail at once. So after taking the lock `hold` also waits until the port
is actually free: nothing accepts a connection on 127.0.0.1 or ::1, and a probe socket can
bind it (SO_EXCLUSIVEADDRUSE on Windows; SO_REUSEADDR on POSIX, as Node's own server sets,
so a closed server's TIME_WAIT connections do not read as a listener - Linux still refuses
the bind while anything listens). The wait for the listener is reported, cancelled and
bounded exactly like the wait for the lock; `PortInUse` names the listener's pid and
command line where `netstat`/`tasklist` (Windows) or `lsof`/`ss` (POSIX) can tell.

A waiter polls until the lock is free, reporting through `on_wait(waited_s, holder)` every
`report_seconds`, honouring `should_stop`, and giving up after `timeout` seconds with
`PortBusy`, which names the holder. `wgflib.procs.run` takes the lock itself for every
command `ports_for` says binds a fixed port, so every step shares one mechanism and none
can forget it.

Re-entrant: a thread that holds a port may take it again (a nested hold), and a process
started while a port is held inherits `WGF_PROC_PORTS`, so a descendant Factory
process never waits on the lock its own ancestor holds for it.

The lock directory is `$WGF_LOCK_DIR`, else `~/.cache/wgf/locks`; the wait bound is
`$WGF_PORT_LOCK_TIMEOUT` seconds, else 3600. Standard library only.
"""

import contextlib
import json
import os
import re
import socket
import threading
import time

from . import template_contract as contract

__all__ = ["hold", "ports_for", "lock_dir", "default_timeout", "holder", "held_ports",
           "describe", "port_free", "listener", "PortBusy", "PortInUse",
           "PortWaitCancelled", "LOCK_DIR_ENV", "TIMEOUT_ENV", "HELD_ENV",
           "CONFIG_PORTS", "SCRIPT_CONFIGS"]

LOCK_DIR_ENV = "WGF_LOCK_DIR"
TIMEOUT_ENV = "WGF_PORT_LOCK_TIMEOUT"
HELD_ENV = "WGF_PROC_PORTS"
DEFAULT_TIMEOUT = 3600.0
POLL_SECONDS = 0.5

# The ports the pinned template's Playwright configs hardcode, by config file: the ones a
# command run in a game checkout can bind without the Factory choosing the port. Every other
# config the template ships reads its port from the environment, and the Factory's own
# configs (playability, store-listing capture, the sdk e2e, golden probes) pick a free one.
# Read from template commit b106261 (1.2.0); scripts/tests/test_portlock.py checks the
# pinned template still says so.
CONFIG_PORTS = {
    contract.PLAYWRIGHT_CONFIG: 4173,
    "playwright.sdk.config.ts": 4176,
}
# The template's npm scripts that run Playwright against one of those configs.
SCRIPT_CONFIGS = {
    contract.SCRIPT_TEST_E2E: contract.PLAYWRIGHT_CONFIG,
    contract.SCRIPT_TEST_VERIFY: contract.PLAYWRIGHT_CONFIG,
    contract.SCRIPT_SDK_BROWSER: "playwright.sdk.config.ts",
}
_RUNNERS = ("pnpm", "npm", "yarn")
_CONFIG_FLAGS = ("-c", "--config")


class PortBusy(RuntimeError):
    """The port stayed held for longer than the wait allows. Names the holder."""

    def __init__(self, port, waited_s, holder_info, path):
        self.port, self.waited_s, self.holder, self.path = port, waited_s, holder_info, path
        super().__init__(f"port {port} is still held after {waited_s:.0f}s by "
                         f"{describe(holder_info)} (lock {path}; raise ${TIMEOUT_ENV} to "
                         f"wait longer)")


class PortInUse(PortBusy):
    """The lock was ours, but a process outside it kept listening on the port."""

    def __init__(self, port, waited_s, listener, path):
        self.port, self.waited_s, self.holder, self.path = port, waited_s, listener, path
        RuntimeError.__init__(
            self, f"port {port} is still in use after {waited_s:.0f}s by a process outside "
                  f"the Factory's port lock: {listener or 'listener not identified'} (lock "
                  f"{path} is held by this process; raise ${TIMEOUT_ENV} to wait longer)")


class PortWaitCancelled(RuntimeError):
    """`should_stop` turned true while waiting for the port."""


def lock_dir():
    return os.path.abspath(os.path.expanduser(
        os.environ.get(LOCK_DIR_ENV) or os.path.join("~", ".cache", "wgf", "locks")))


def default_timeout():
    """`$WGF_PORT_LOCK_TIMEOUT` when it is a non-negative number, else 3600."""
    try:
        value = float(os.environ.get(TIMEOUT_ENV, ""))
    except ValueError:
        return DEFAULT_TIMEOUT
    return value if value >= 0 else DEFAULT_TIMEOUT


def _base(part):
    name = os.path.basename(str(part)).lower()
    for suffix in (".cmd", ".exe", ".ps1", ".bat"):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def ports_for(argv):
    """The fixed ports `argv` will bind, sorted: a template script run through the package
    manager (`pnpm run test:e2e`, `pnpm test:verify`), or `playwright test` against a config
    in CONFIG_PORTS (no `-c` means playwright.config.ts). Anything else binds none."""
    parts = [str(part) for part in argv]
    if not parts:
        return ()
    found = set()
    if _base(parts[0]) in _RUNNERS:
        rest = parts[1:]
        if rest and rest[0] == "run":
            rest = rest[1:]
        if rest and rest[0] in SCRIPT_CONFIGS:
            found.add(CONFIG_PORTS[SCRIPT_CONFIGS[rest[0]]])
    for index, part in enumerate(parts):
        if _base(part) == "playwright" and parts[index + 1:index + 2] == ["test"]:
            config = contract.PLAYWRIGHT_CONFIG
            tail = parts[index + 2:]
            for position, flag in enumerate(tail):
                if flag in _CONFIG_FLAGS and position + 1 < len(tail):
                    config = tail[position + 1]
                elif any(flag.startswith(f + "=") for f in _CONFIG_FLAGS):
                    config = flag.split("=", 1)[1]
            port = CONFIG_PORTS.get(os.path.basename(config))
            if port is not None:
                found.add(port)
            break
    return tuple(sorted(found))


def _paths(port, directory):
    directory = directory or lock_dir()
    return (os.path.join(directory, f"port-{int(port)}.lock"),
            os.path.join(directory, f"port-{int(port)}.holder.json"))


def holder(port, directory=None):
    """What the holder file says about the port's current (or last) holder, or {}."""
    try:
        with open(_paths(port, directory)[1], encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def describe(info):
    if info and info.get("listening"):
        return (f"a process listening on port {info.get('port')} outside the Factory's "
                f"port lock")
    if not info:
        return "an unknown process (no holder record)"
    parts = [f"pid {info.get('pid')}"]
    if info.get("run"):
        parts.append(f"run {info['run']}")
    if info.get("command"):
        parts.append(f"running `{info['command']}`")
    if info.get("since"):
        parts.append(f"since {info['since']}")
    return ", ".join(parts)


def _probe_addresses():
    addresses = [(socket.AF_INET, "127.0.0.1")]
    if socket.has_ipv6:
        addresses.append((socket.AF_INET6, "::1"))
    return addresses


def port_free(port):
    """True when nothing listens on `port` on the loopback addresses: no connection is
    accepted on 127.0.0.1 or ::1, and a probe socket can bind 127.0.0.1 (and ::1 where the
    host has IPv6). An address family the host cannot use is skipped."""
    for family, address in _probe_addresses():
        try:
            with socket.socket(family, socket.SOCK_STREAM) as probe:
                probe.settimeout(0.5)
                if probe.connect_ex((address, port)) == 0:
                    return False
        except OSError:
            pass
    for family, address in _probe_addresses():
        try:
            probe = socket.socket(family, socket.SOCK_STREAM)
        except OSError:
            continue
        try:
            if os.name == "nt":
                exclusive = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
                if exclusive is not None:
                    probe.setsockopt(socket.SOL_SOCKET, exclusive, 1)
            else:
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            probe.bind((address, port))
        except OSError as exc:
            # No such address on this host (an IPv6 stack without ::1) is not a listener.
            if getattr(exc, "errno", None) in _ADDRESS_ABSENT:
                continue
            return False
        finally:
            probe.close()
    return True


# EADDRNOTAVAIL / EAFNOSUPPORT on POSIX, WSAEADDRNOTAVAIL / WSAEAFNOSUPPORT on Windows.
_ADDRESS_ABSENT = {99, 97, 49, 47, 10049, 10047}


def listener(port):
    """Best effort: "pid N (command line)" of whatever listens on `port`, or None."""
    from . import procs  # procs imports this module; only needed here, at a timeout

    def run(argv):
        try:
            done = procs.run(argv, timeout=20, ports=(), heartbeat_seconds=0)
        except Exception:
            return ""
        return done.stdout if done.returncode == 0 else ""

    pids = []
    if os.name == "nt":
        for line in run(["netstat", "-ano", "-p", "TCP"]).splitlines() + \
                run(["netstat", "-ano", "-p", "TCPv6"]).splitlines():
            fields = line.split()
            if (len(fields) >= 5 and fields[3].upper() == "LISTENING"
                    and fields[1].rsplit(":", 1)[-1] == str(port)):
                pids.append(fields[4])
    else:
        found = run(["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"])
        pids = found.split()
        if not pids:
            pids = re.findall(r"pid=(\d+)", run(["ss", "-ltnpH", f"sport = :{port}"]))
    pids = list(dict.fromkeys(p for p in pids if p.isdigit() and p != "0"))
    if not pids:
        return None
    described = []
    for pid in pids:
        if os.name == "nt":
            row = run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"]).strip()
            name = row.split('","')[0].strip('"') if row.startswith('"') else ""
        else:
            name = run(["ps", "-o", "args=", "-p", pid]).strip()
        described.append(f"pid {pid}" + (f" ({name})" if name else ""))
    return ", ".join(described)


if os.name == "nt":  # pragma: no cover - exercised on Windows only
    import msvcrt

    def _try_lock(handle):
        try:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            return False

    def _unlock(handle):
        try:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
else:
    import fcntl

    def _try_lock(handle):
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            return False

    def _unlock(handle):
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass


# Ports this process holds: port -> [owning thread ident, depth].
_HELD = {}
_HELD_LOCK = threading.Lock()


def _inherited():
    held = set()
    for item in (os.environ.get(HELD_ENV) or "").split(","):
        if item.strip().isdigit():
            held.add(int(item))
    return held


def held_ports():
    """Every port this process holds or inherited, as `WGF_PROC_PORTS` spells it."""
    with _HELD_LOCK:
        ports = set(_HELD) | _inherited()
    return ",".join(str(p) for p in sorted(ports))


def _utc_now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


@contextlib.contextmanager
def hold(port, command=None, run=None, timeout=None, on_wait=None, should_stop=None,
         report_seconds=15.0, directory=None, poll_seconds=POLL_SECONDS, clock=time.monotonic,
         probe=None):
    """Hold `port` exclusively, machine-wide, for the block.

    Waits while another process holds the lock, then while anything still listens on the
    port (`probe(port)` false): `on_wait(waited_s, holder)` right away and every
    `report_seconds`, `should_stop()` polled (PortWaitCancelled), `timeout` seconds at most
    over both waits (default `default_timeout()`; PortBusy names the holder, PortInUse the
    listener). `probe` defaults to `port_free`; False skips the listener wait. Yields the
    seconds waited."""
    port = int(port)
    me = threading.get_ident()
    with _HELD_LOCK:
        mine = _HELD.get(port)
        if mine and mine[0] == me:
            mine[1] += 1
            nested = True
        else:
            nested = False
    if nested:
        try:
            yield 0.0
        finally:
            with _HELD_LOCK:
                _HELD[port][1] -= 1
        return
    if port in _inherited():
        yield 0.0
        return

    lock_path, holder_path = _paths(port, directory)
    os.makedirs(os.path.dirname(lock_path), exist_ok=True)
    timeout = default_timeout() if timeout is None else timeout
    handle = open(lock_path, "a+b")
    began = clock()
    next_report = [began]

    def tick(info, busy):
        """One poll of a wait: report, honour a stop, give up at the bound."""
        now = clock()
        waited = now - began
        if on_wait is not None and now >= next_report[0]:
            try:
                on_wait(waited, info())
            except Exception:
                pass
            next_report[0] = now + report_seconds
        if should_stop is not None and should_stop():
            raise PortWaitCancelled(f"stopped while waiting for port {port}")
        if waited >= timeout:
            raise busy(waited)
        time.sleep(poll_seconds)

    locked = False
    try:
        while not _try_lock(handle):
            tick(lambda: holder(port, directory),
                 lambda waited: PortBusy(port, waited, holder(port, directory), lock_path))
        locked = True
        # The lock orders Factory commands only; wait out a listener outside it too.
        probe = port_free if probe is None else probe
        while probe and not probe(port):
            tick(lambda: {"listening": True, "port": port},
                 lambda waited: PortInUse(port, waited, listener(port), lock_path))
    except BaseException:
        if locked:
            _unlock(handle)
        handle.close()
        raise
    waited = clock() - began
    try:
        record = {"pid": os.getpid(), "run": run, "command": command, "since": _utc_now(),
                  "port": port}
        tmp = f"{holder_path}.{os.getpid()}.tmp"
        with open(tmp, "w", encoding="utf-8") as out:
            json.dump(record, out)
        os.replace(tmp, holder_path)
    except OSError:
        pass  # the record is for messages; the lock itself is held
    with _HELD_LOCK:
        _HELD[port] = [me, 0]
    try:
        yield waited
    finally:
        with _HELD_LOCK:
            _HELD.pop(port, None)
        _unlock(handle)
        handle.close()

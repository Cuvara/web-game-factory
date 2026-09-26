"""Durable local storage for workflow runs. Files, no database.

    <storage>/workflows/LATEST           the run most recently started or driven
    <storage>/workflows/<run-id>/
        state.json          the RunState - rewritten atomically after every change
        events.jsonl        every event, append-only; also the structured log
        artifacts/<id>/v<n>.json
        lock                present while a process is driving the run
                            ("<pid> <start time>")
        pause | cancel      requests from another process, honoured between steps

Atomicity, which is what resume depends on:

  * `state.json`, every artifact file, `LATEST` and the request files are written to a
    temporary sibling `.<name>.tmp.<pid>.<random>`, flushed (and fsync'd when `fsync` is
    on), then renamed over the target. A crash leaves the old file or the new one, never
    half of each. The name is unique per writer, so two processes writing one target at
    once (two `wgf` commands both marking `LATEST`) never write, rename or remove each
    other's temporary file; the last rename wins. A temporary file left behind is evidence
    of an interrupted write and is named in the error if the target is unreadable.
  * `events.jsonl` is append-only. A crash mid-append can leave a partial last line;
    readers skip it and report it, and the next append starts on a fresh line, so the log
    never glues a new event onto a torn one.
  * The lock is created with O_EXCL. A lock whose owner is dead is taken over only under a
    second O_EXCL guard (`lock.takeover`) and only after re-reading it there, so two
    processes that both saw the same dead owner cannot both end up holding the run.
  * The lock (and the guard) name their owner by pid *and* start time - field 22 of
    `/proc/<pid>/stat`, where there is one. A pid alone is recycled: a driver that died
    and whose pid now belongs to an unrelated process would look alive for ever, and its
    run could never be resumed. An owner is live only if its pid is alive and, when both
    start times are known, they match. A lock holding only a pid (written before start
    times were recorded, or where /proc does not exist) is judged by the pid alone.
"""

import hashlib
import json
import os
import re
import secrets
import threading
import time

from .model import ArtifactRef, RunState

__all__ = ["RunStore", "StoreError", "RunLocked", "check_run_id", "check_artifact_id"]


class StoreError(LookupError):
    """No such run, or its state cannot be read."""


# Run ids and artifact ids become directory names, so they are checked before they touch a
# path: no separators, no `..`, no control characters, nothing that could leave the store.
# fullmatch, not `$`: `$` also matches before a trailing newline.
_RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
ARTIFACT_ID = re.compile(r"[a-z][a-z0-9-]{0,127}")
_LOCATION = re.compile(r"artifacts/([a-z][a-z0-9-]{0,127})/v([1-9][0-9]{0,8})\.json")

# An empty lock file younger than this is presumed to be mid-creation (O_EXCL create, then
# write); older, its creator died between the two and it is stale.
LOCK_GRACE_SECONDS = 5.0

# How far a file's mtime may disagree with time.time(). On some filesystems (WSL's drvfs,
# network mounts) mtimes are coarse or skewed, so a lock created a moment ago can read as
# older than the grace. An empty lock whose mtime age is within the grace plus this much is
# therefore stale only once *this* taker has watched that same file stay empty for the
# whole grace; one older than that (a creator that crashed long ago) is stale at once.
LOCK_MTIME_SKEW_SECONDS = 2.0


class _LockInfo(tuple):
    """(owner pid or 0, mtime age in seconds, owner start time or None, file identity)."""
    __slots__ = ()

    def __new__(cls, owner, age, started=None, ident=None):
        return super().__new__(cls, (owner, age, started, ident))

    owner = property(lambda self: self[0])
    age = property(lambda self: self[1])
    started = property(lambda self: self[2])
    ident = property(lambda self: self[3])


def check_run_id(run_id):
    if not isinstance(run_id, str) or not _RUN_ID.fullmatch(run_id) or ".." in run_id:
        raise StoreError(f"{run_id!r} is not a valid run id")
    return run_id


def check_artifact_id(artifact_id):
    if not isinstance(artifact_id, str) or not ARTIFACT_ID.fullmatch(artifact_id):
        raise StoreError(f"artifact id {artifact_id!r} is not kebab-case")
    return artifact_id


class RunLocked(RuntimeError):
    """Another live process (or another thread of this one) is driving this run."""


def _start_time(pid):
    """The process's start time in clock ticks since boot (field 22 of /proc/<pid>/stat),
    or None where it cannot be read - no /proc, or no such process. Together with the pid
    it names one process: a recycled pid comes back with a different start time."""
    try:
        with open(f"/proc/{int(pid)}/stat", "rb") as handle:
            raw = handle.read()
        # The command name (field 2) is in parentheses and may itself hold spaces or ")".
        fields = raw[raw.rindex(b")") + 1:].split()
        return int(fields[19])  # fields[0] is field 3 (state), so field 22 is fields[19]
    except (OSError, ValueError, IndexError, OverflowError):
        return None


def _holder_line():
    """What a lock (or takeover guard) says about the process writing it."""
    started = _start_time(os.getpid())
    return f"{os.getpid()} {started}\n" if started is not None else f"{os.getpid()}\n"


def _pid_alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except (OSError, OverflowError, ValueError):
        return False
    return True


def _temporaries(path):
    """Temporary siblings an interrupted `_atomic_write` of `path` left behind, by name:
    `.<name>.tmp.<pid>.<random>`, and the fixed `<name>.tmp` earlier versions wrote."""
    directory, name = os.path.split(path)
    try:
        entries = os.listdir(directory)
    except OSError:
        return []
    prefix = f".{name}.tmp."
    return sorted(entry for entry in entries
                  if entry == f"{name}.tmp" or entry.startswith(prefix))


def _dump(value):
    return json.dumps(value, indent=2, ensure_ascii=False) + "\n"


# Locks this process holds, by lock path. A lock file naming this pid that is not in here
# was left by an earlier engine in this process and is stale; one that is in here belongs to
# a live driver, possibly on another thread, and must be refused.
_HELD = {}
_HELD_LOCK = threading.RLock()


class RunStore:
    def __init__(self, directory, fsync=True):
        self.directory = os.path.abspath(directory)
        # fsync is what makes the rename atomic across a power cut, not just a crash. Tests
        # turn it off; on some filesystems it costs tens of milliseconds per save.
        self.fsync = fsync
        self.workflows = os.path.join(self.directory, "workflows")
        # run_id -> the exact bytes events.jsonl should hold while this process drives the
        # run (seal_events). Appends come from the driver's thread and from progress
        # threads, so they and the record are kept in step under one lock.
        self._sealed = {}
        self._events_lock = threading.Lock()

    # -- layout -------------------------------------------------------------------------

    def run_dir(self, run_id):
        return os.path.join(self.workflows, check_run_id(run_id))

    def _path(self, run_id, *parts):
        return os.path.join(self.run_dir(run_id), *parts)

    def exists(self, run_id):
        return os.path.exists(self._path(run_id, "state.json"))

    # -- atomic writes ------------------------------------------------------------------

    def _atomic_write(self, path, payload):
        """Write `payload` (bytes) to `path` so that a reader sees all of it or none of it."""
        directory, name = os.path.split(path)
        # Unique per writer: a fixed `<name>.tmp` let two processes marking LATEST at once
        # rename or remove the other's file mid-write and crash on the missing one.
        temporary = os.path.join(
            directory, f".{name}.tmp.{os.getpid()}.{secrets.token_hex(4)}")
        try:
            with open(temporary, "wb") as handle:
                handle.write(payload)
                handle.flush()
                if self.fsync:
                    os.fsync(handle.fileno())
            os.replace(temporary, path)
        except BaseException:
            # An exception (not a crash) leaves nothing behind. A crash leaves the .tmp,
            # which load() names if the target turns out unreadable.
            try:
                os.remove(temporary)
            except OSError:
                pass
            raise
        if self.fsync:
            self._fsync_dir(os.path.dirname(path))

    @staticmethod
    def _fsync_dir(directory):
        """Make the rename itself durable. Not possible on every platform; best effort."""
        try:
            descriptor = os.open(directory, os.O_RDONLY)
        except OSError:
            return
        try:
            os.fsync(descriptor)
        except OSError:
            pass
        finally:
            os.close(descriptor)

    # -- state --------------------------------------------------------------------------

    def create(self, state):
        directory = self.run_dir(state.run_id)
        if os.path.exists(directory):
            raise StoreError(f"run {state.run_id} already exists")
        os.makedirs(os.path.join(directory, "artifacts"))
        self.save(state)

    def save(self, state):
        path = self._path(state.run_id, "state.json")
        self._atomic_write(path, _dump(state.to_dict()).encode("utf-8"))

    def load(self, run_id):
        path = self._path(run_id, "state.json")
        if not os.path.exists(path):
            raise StoreError(f"no run {run_id!r} in {self.workflows}")
        try:
            with open(path, "rb") as handle:
                data = json.loads(handle.read().decode("utf-8"))
            if not isinstance(data, dict):
                raise ValueError(f"top level is {type(data).__name__}, not an object")
            return RunState.from_dict(data)
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            hint = ""
            leftovers = _temporaries(path)
            if leftovers:
                hint = (f"; an interrupted write left {', '.join(leftovers)} beside it "
                        f"- inspect them before deciding which to keep")
            raise StoreError(f"run {run_id}: unreadable state.json ({path}): {exc}{hint}")
        except OSError as exc:
            raise StoreError(f"run {run_id}: cannot read state.json: {exc}")

    def list_runs(self, problems=None):
        """Every readable run's state, oldest first. Unreadable runs are appended to
        `problems` (when given) as `(run_id, message)` instead of being silently dropped."""
        if not os.path.isdir(self.workflows):
            return []
        states = []
        for run_id in os.listdir(self.workflows):
            if run_id.startswith("LATEST") or not _RUN_ID.fullmatch(run_id) or ".." in run_id:
                continue
            if self.exists(run_id):
                try:
                    states.append(self.load(run_id))
                except StoreError as exc:
                    if problems is not None:
                        problems.append((run_id, str(exc)))
        return sorted(states, key=lambda s: (s.created_at or "", s.run_id))

    def mark_latest(self, run_id):
        """Record `run_id` as the run most recently started or driven."""
        check_run_id(run_id)
        os.makedirs(self.workflows, exist_ok=True)
        self._atomic_write(os.path.join(self.workflows, "LATEST"),
                           (run_id + "\n").encode("utf-8"))

    def latest(self):
        """The run most recently started or driven - by pointer, not by clock, because a
        wall clock can step backwards and "the run I just resumed" is what people mean."""
        try:
            with open(os.path.join(self.workflows, "LATEST"), encoding="utf-8") as handle:
                run_id = handle.read().strip()
            if run_id and _RUN_ID.fullmatch(run_id) and ".." not in run_id \
                    and self.exists(run_id):
                return self.load(run_id)
        except (OSError, ValueError):
            pass
        runs = self.list_runs()
        return runs[-1] if runs else None

    # -- events -------------------------------------------------------------------------

    def append_event(self, record):
        path = self._path(record["run_id"], "events.jsonl")
        line = (json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
        with self._events_lock:
            with open(path, "a+b") as handle:
                # A crash mid-append leaves a line with no newline; start on a fresh one so
                # the torn line stays one bad line instead of swallowing this event too.
                handle.seek(0, os.SEEK_END)
                if handle.tell() > 0:
                    handle.seek(-1, os.SEEK_END)
                    if handle.read(1) != b"\n":
                        line = b"\n" + line
                handle.seek(0, os.SEEK_END)
                handle.write(line)
            sealed = self._sealed.get(record["run_id"])
            if sealed is not None:
                sealed += line

    # -- the event log while a drive holds the run ----------------------------------------
    #
    # While a driver holds a run, this process is the only legitimate writer of its
    # events.jsonl: every step's log line and progress event goes through the engine. So
    # the engine seals the log when its drive begins, and after each step compares the file
    # with exactly what it should hold: an append, an edit or a truncation by anything else
    # - a step's child process, code the Factory ran for a step - is found, and put back.
    # Decisions and budget raises are corroborated from this log; this is what keeps a line
    # a step's process wrote from counting as a person's act.

    def seal_events(self, run_id):
        """Start holding what `run_id`'s events.jsonl is now, plus what this process appends."""
        path = self._path(run_id, "events.jsonl")
        with self._events_lock:
            try:
                with open(path, "rb") as handle:
                    self._sealed[run_id] = bytearray(handle.read())
            except FileNotFoundError:
                self._sealed[run_id] = bytearray()

    def unseal_events(self, run_id):
        with self._events_lock:
            self._sealed.pop(run_id, None)

    def event_log_changes(self, run_id):
        """None when the sealed log is exactly what this process wrote (or it is not sealed);
        else a short description of what another process did to it."""
        path = self._path(run_id, "events.jsonl")
        with self._events_lock:
            expected = self._sealed.get(run_id)
            if expected is None:
                return None
            try:
                with open(path, "rb") as handle:
                    actual = handle.read()
            except FileNotFoundError:
                actual = b""
            if actual == bytes(expected):
                return None
            if actual.startswith(bytes(expected)):
                extra = actual[len(expected):]
                names = []
                for raw in extra.split(b"\n"):
                    try:
                        name = json.loads(raw.decode("utf-8")).get("event")
                    except (ValueError, AttributeError):
                        name = None
                    if raw.strip():
                        names.append(str(name) if name else "a line that is not an event")
                return (f"{len(names)} line(s) appended by another process: "
                        + ", ".join(sorted(set(names))))
            return "lines this run had recorded were changed or removed"

    def restore_events(self, run_id):
        """Put back exactly what the sealed log should hold (temp file + rename)."""
        path = self._path(run_id, "events.jsonl")
        with self._events_lock:
            expected = self._sealed.get(run_id)
            if expected is None:
                return False
            self._atomic_write(path, bytes(expected))
            return True

    def read_events(self, run_id, problems=None):
        """Every well-formed event. A line that is not a JSON object - typically the partial
        last line of a crash mid-append - is skipped and appended to `problems` (when given)
        as `(line_number, message)`; reading never fails on a torn log."""
        path = self._path(run_id, "events.jsonl")
        if not os.path.exists(path):
            return []
        events = []
        with open(path, "rb") as handle:
            raw_lines = handle.read().split(b"\n")
        for number, raw in enumerate(raw_lines, 1):
            if not raw.strip():
                continue
            try:
                record = json.loads(raw.decode("utf-8"))
                if not isinstance(record, dict) or "event" not in record:
                    raise ValueError("not an event object")
            except ValueError as exc:
                if problems is not None:
                    last = number == len(raw_lines) or (
                        number == len(raw_lines) - 1 and not raw_lines[-1].strip())
                    where = "partial last line (interrupted append)" if last else "bad line"
                    problems.append((number, f"events.jsonl line {number}: {where} "
                                             f"skipped: {exc}"))
                continue
            events.append(record)
        return events

    # -- artifacts ----------------------------------------------------------------------

    def artifact_location(self, artifact_id, version):
        check_artifact_id(artifact_id)
        if not isinstance(version, int) or isinstance(version, bool) or version < 1:
            raise StoreError(f"artifact version {version!r} is not a positive integer")
        return f"artifacts/{artifact_id}/v{version}.json"

    def _artifact_path(self, run_id, location):
        if not isinstance(location, str) or not _LOCATION.fullmatch(location):
            raise StoreError(f"artifact location {location!r} is not artifacts/<id>/v<n>.json")
        return self._path(run_id, *location.split("/"))

    def has_artifact_file(self, run_id, artifact_id, version):
        """True if a file exists for that version - recorded or not."""
        location = self.artifact_location(artifact_id, version)
        return os.path.exists(self._artifact_path(run_id, location))

    def write_artifact(self, run_id, artifact_id, version, content):
        """Persist one artifact version atomically. Returns (location, checksum).

        An existing file at that version is replaced: the engine derives the version from
        the versions state has recorded, so a file already there is one an interrupted
        execution wrote but never recorded, and nothing refers to it.
        """
        location = self.artifact_location(artifact_id, int(version))
        path = self._artifact_path(run_id, location)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        payload = _dump(content).encode("utf-8")
        self._atomic_write(path, payload)
        return location, "sha256:" + hashlib.sha256(payload).hexdigest()

    def read_artifact(self, run_id, ref):
        if isinstance(ref, dict):
            ref = ArtifactRef.from_dict(ref)
        path = self._artifact_path(run_id, ref.location)
        try:
            with open(path, "rb") as handle:
                payload = handle.read()
        except FileNotFoundError:
            raise StoreError(f"artifact {ref.id} v{ref.version} is missing: {ref.location} "
                             f"is not in the run directory")
        except OSError as exc:
            raise StoreError(f"artifact {ref.id} v{ref.version} cannot be read: {exc}")
        checksum = "sha256:" + hashlib.sha256(payload).hexdigest()
        if checksum != ref.checksum:
            raise StoreError(
                f"artifact {ref.id} v{ref.version} changed on disk after it was recorded "
                f"({ref.checksum} -> {checksum})"
            )
        try:
            return json.loads(payload.decode("utf-8"))
        except ValueError as exc:
            raise StoreError(f"artifact {ref.id} v{ref.version} is not JSON: {exc}")

    # -- lock and requests --------------------------------------------------------------

    @staticmethod
    def _read_lock(path):
        """A _LockInfo, or None if there is no such file. A lock written before start
        times were recorded holds only the pid, and reads with `started` None."""
        try:
            with open(path, encoding="utf-8") as handle:
                text = handle.read()
            stat = os.stat(path)
            age = time.time() - stat.st_mtime
            ident = (stat.st_dev, stat.st_ino, stat.st_mtime_ns)
        except FileNotFoundError:
            return None
        except OSError:
            return _LockInfo(0, LOCK_GRACE_SECONDS + LOCK_MTIME_SKEW_SECONDS + 1)
        words = text.split()
        try:
            owner = int(words[0]) if words else 0
        except ValueError:
            owner = 0
        try:
            started = int(words[1]) if owner and len(words) > 1 else None
        except ValueError:
            started = None
        return _LockInfo(owner, age, started, ident)

    @staticmethod
    def _empty_is_live(info, seen):
        """Is an empty lock (or guard) still being written by its creator?

        Younger than the grace by its mtime: yes. Older than the grace plus the mtime skew
        allowance: no, its creator died. In between, the mtime alone cannot be trusted, so
        it is live until this taker has seen the same file (`seen`: identity -> when first
        seen, kept for one acquire) stay empty for the grace. Erring this way only makes a
        taker wait longer; it never takes over a lock sooner than before.
        """
        if info.age < LOCK_GRACE_SECONDS:
            return True
        if seen is None or info.age >= LOCK_GRACE_SECONDS + LOCK_MTIME_SKEW_SECONDS:
            return False
        first = seen.setdefault(info.ident, time.monotonic())
        return time.monotonic() - first < LOCK_GRACE_SECONDS

    @staticmethod
    def _holder_alive(owner, started):
        """Is the process a lock names still the one that wrote it? A live pid whose start
        time differs is a recycled pid, not the owner. Unknown start times (an old
        pid-only lock, no /proc) leave the pid to decide, as it always did."""
        if not _pid_alive(owner):
            return False
        if started is None:
            return True
        now = _start_time(owner)
        return now is None or now == started

    @staticmethod
    def _key(path):
        return os.path.normcase(os.path.abspath(path))

    def _owner_is_live(self, path, info, seen=None):
        """Is the lock described by `info` held by a live driver?"""
        owner, _age, started, _ident = info
        if not owner:
            return self._empty_is_live(info, seen)  # being written, or a crashed creator
        if owner == os.getpid():
            return self._key(path) in _HELD
        return self._holder_alive(owner, started)

    def acquire(self, run_id):
        """Take the run's lock, or raise RunLocked. A lock whose owner is dead is taken over.

        Not reentrant: a second acquire of a run this process already drives - from any
        thread - is refused, like one from another process.
        """
        path = self._path(run_id, "lock")
        key = self._key(path)
        deadline = time.monotonic() + LOCK_GRACE_SECONDS + 1
        seen = {}  # empty lock files this acquire has watched, by identity (_empty_is_live)
        with _HELD_LOCK:
            if key in _HELD:
                raise RunLocked(f"run {run_id} is already being driven by this process")
            while True:
                try:
                    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
                except FileExistsError:
                    info = self._read_lock(path)
                    if info is None:
                        continue  # released between our create and our read
                    if self._owner_is_live(path, info, seen):
                        if info[0]:
                            raise RunLocked(
                                f"run {run_id} is being driven by process {info[0]}")
                        if time.monotonic() > deadline:
                            raise RunLocked(f"run {run_id}: its lock is being taken")
                        time.sleep(0.01)
                        continue
                    self._break_stale_lock(path, seen)
                    if time.monotonic() > deadline:
                        raise RunLocked(f"run {run_id}: could not take over its stale lock")
                    continue
                with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                    handle.write(_holder_line())
                    handle.flush()
                    if self.fsync:
                        os.fsync(handle.fileno())
                _HELD[key] = threading.get_ident()
                return

    def _break_stale_lock(self, path, seen=None):
        """Remove a lock whose owner is dead - under a guard, after re-reading it.

        Without the guard, two processes that both read the same dead owner would both
        remove "the" lock, and the slower one would delete the lock the faster one had just
        created. Under the guard only one remover exists at a time, and it removes only what
        it has just re-read as stale; a fresh lock cannot appear at the path meanwhile,
        because a lock is only ever created with O_EXCL on a path that does not exist.
        """
        guard = path + ".takeover"
        try:
            descriptor = os.open(guard, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            info = self._read_lock(guard)
            if info is None:
                return
            owner, _age, started, _ident = info
            taker_alive = (owner and owner != os.getpid()
                           and self._holder_alive(owner, started)) or (
                not owner and self._empty_is_live(info, seen))
            if taker_alive:
                time.sleep(0.005)  # someone else is taking over; let them finish
                return
            # Its taker died inside the takeover (a window of microseconds): clear it.
            try:
                os.remove(guard)
            except FileNotFoundError:
                pass
            return
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(_holder_line())
            info = self._read_lock(path)
            if info is not None and not self._owner_is_live(path, info, seen):
                try:
                    os.remove(path)
                except FileNotFoundError:
                    pass
        finally:
            try:
                os.remove(guard)
            except FileNotFoundError:
                pass

    def lock_owner(self, run_id):
        """The pid of the live process driving the run, or None."""
        path = self._path(run_id, "lock")
        info = self._read_lock(path)
        if info is None or not info[0] or not self._owner_is_live(path, info):
            return None
        return info[0]

    def is_held(self, run_id):
        """True if a live driver (this process included) holds the run's lock. False means
        a run that says RUNNING is a crashed run."""
        return self.lock_owner(run_id) is not None

    def release(self, run_id):
        """Release the lock if this process holds it. Never removes another owner's lock."""
        path = self._path(run_id, "lock")
        with _HELD_LOCK:
            _HELD.pop(self._key(path), None)
            info = self._read_lock(path)
            if info is not None and info[0] == os.getpid():
                try:
                    os.remove(path)
                except FileNotFoundError:
                    pass

    _REQUESTS = ("pause", "cancel")

    def _request_path(self, run_id, kind):
        if kind not in self._REQUESTS:
            raise StoreError(f"unknown request {kind!r}")
        return self._path(run_id, kind)

    def request(self, run_id, kind):
        if not self.exists(run_id):
            raise StoreError(f"no run {run_id!r}")
        self._atomic_write(self._request_path(run_id, kind), b"requested\n")

    def requested(self, run_id, kind):
        return os.path.exists(self._request_path(run_id, kind))

    def clear_request(self, run_id, kind):
        try:
            os.remove(self._request_path(run_id, kind))
        except FileNotFoundError:
            pass

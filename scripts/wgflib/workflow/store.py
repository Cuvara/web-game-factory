"""Durable local storage for workflow runs. Files, no database.

    <storage>/workflows/LATEST           the run most recently started or driven
    <storage>/workflows/<run-id>/
        state.json          the RunState - rewritten atomically after every change
        events.jsonl        every event, append-only; also the structured log
        artifacts/<id>/v<n>.json
        lock                present while a process is driving the run
        pause | cancel      requests from another process, honoured between steps

`state.json` is replaced by write-to-temp-then-rename, so a crash leaves either the old
state or the new one, never half of each. That is the property resume depends on.
"""

import hashlib
import json
import os
import re

from .model import ArtifactRef, RunState

__all__ = ["RunStore", "StoreError", "RunLocked"]


class StoreError(LookupError):
    """No such run, or its state cannot be read."""


# Run ids and artifact ids become directory names, so they are checked before they touch a
# path: no separators, no `..`, nothing that could leave the store.
_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
ARTIFACT_ID = re.compile(r"^[a-z][a-z0-9-]*$")


def check_run_id(run_id):
    if not isinstance(run_id, str) or not _RUN_ID.match(run_id) or ".." in run_id:
        raise StoreError(f"{run_id!r} is not a valid run id")
    return run_id


class RunLocked(RuntimeError):
    """Another live process is driving this run."""


def _pid_alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _dump(value):
    return json.dumps(value, indent=2, ensure_ascii=False) + "\n"


class RunStore:
    def __init__(self, directory, fsync=True):
        self.directory = os.path.abspath(directory)
        # fsync is what makes the rename atomic across a power cut, not just a crash. Tests
        # turn it off; on some filesystems it costs tens of milliseconds per save.
        self.fsync = fsync
        self.workflows = os.path.join(self.directory, "workflows")

    # -- layout -------------------------------------------------------------------------

    def run_dir(self, run_id):
        return os.path.join(self.workflows, check_run_id(run_id))

    def _path(self, run_id, *parts):
        return os.path.join(self.run_dir(run_id), *parts)

    def exists(self, run_id):
        return os.path.exists(self._path(run_id, "state.json"))

    # -- state --------------------------------------------------------------------------

    def create(self, state):
        directory = self.run_dir(state.run_id)
        if os.path.exists(directory):
            raise StoreError(f"run {state.run_id} already exists")
        os.makedirs(os.path.join(directory, "artifacts"))
        self.save(state)

    def save(self, state):
        path = self._path(state.run_id, "state.json")
        temporary = path + ".tmp"
        with open(temporary, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(_dump(state.to_dict()))
            if self.fsync:
                handle.flush()
                os.fsync(handle.fileno())
        os.replace(temporary, path)

    def load(self, run_id):
        path = self._path(run_id, "state.json")
        if not os.path.exists(path):
            raise StoreError(f"no run {run_id!r} in {self.workflows}")
        try:
            with open(path, encoding="utf-8") as handle:
                return RunState.from_dict(json.load(handle))
        except (ValueError, TypeError) as exc:
            raise StoreError(f"run {run_id}: unreadable state.json: {exc}")

    def list_runs(self):
        """Every run's state, oldest first."""
        if not os.path.isdir(self.workflows):
            return []
        states = []
        for run_id in os.listdir(self.workflows):
            if run_id.startswith("LATEST") or not _RUN_ID.match(run_id):
                continue
            if self.exists(run_id):
                try:
                    states.append(self.load(run_id))
                except StoreError:
                    continue
        return sorted(states, key=lambda s: (s.created_at or "", s.run_id))

    def mark_latest(self, run_id):
        """Record `run_id` as the run most recently started or driven."""
        path = os.path.join(self.workflows, "LATEST")
        with open(path + ".tmp", "w", encoding="utf-8") as handle:
            handle.write(run_id + "\n")
        os.replace(path + ".tmp", path)

    def latest(self):
        """The run most recently started or driven - by pointer, not by clock, because a
        wall clock can step backwards and "the run I just resumed" is what people mean."""
        try:
            with open(os.path.join(self.workflows, "LATEST"), encoding="utf-8") as handle:
                run_id = handle.read().strip()
            if run_id and self.exists(run_id):
                return self.load(run_id)
        except OSError:
            pass
        runs = self.list_runs()
        return runs[-1] if runs else None

    # -- events -------------------------------------------------------------------------

    def append_event(self, record):
        path = self._path(record["run_id"], "events.jsonl")
        with open(path, "a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")

    def read_events(self, run_id):
        path = self._path(run_id, "events.jsonl")
        if not os.path.exists(path):
            return []
        with open(path, encoding="utf-8") as handle:
            return [json.loads(line) for line in handle if line.strip()]

    # -- artifacts ----------------------------------------------------------------------

    def write_artifact(self, run_id, artifact_id, version, content):
        """Persist one artifact version. Returns (location, checksum)."""
        if not ARTIFACT_ID.match(artifact_id or ""):
            raise StoreError(f"artifact id {artifact_id!r} is not kebab-case")
        location = f"artifacts/{artifact_id}/v{int(version)}.json"
        path = self._path(run_id, *location.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        payload = _dump(content).encode("utf-8")
        with open(path, "wb") as handle:
            handle.write(payload)
        return location, "sha256:" + hashlib.sha256(payload).hexdigest()

    def read_artifact(self, run_id, ref):
        if isinstance(ref, dict):
            ref = ArtifactRef.from_dict(ref)
        path = self._path(run_id, *ref.location.split("/"))
        with open(path, "rb") as handle:
            payload = handle.read()
        checksum = "sha256:" + hashlib.sha256(payload).hexdigest()
        if checksum != ref.checksum:
            raise StoreError(
                f"artifact {ref.id} v{ref.version} changed on disk after it was recorded "
                f"({ref.checksum} -> {checksum})"
            )
        return json.loads(payload.decode("utf-8"))

    # -- lock and requests --------------------------------------------------------------

    def acquire(self, run_id):
        """Take the run's lock. A lock whose owner process is dead is taken over."""
        path = self._path(run_id, "lock")
        while True:
            try:
                descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                try:
                    with open(path, encoding="utf-8") as handle:
                        owner = int(handle.read().strip() or 0)
                except (OSError, ValueError):
                    owner = 0
                if owner and owner != os.getpid() and _pid_alive(owner):
                    raise RunLocked(f"run {run_id} is being driven by process {owner}")
                os.remove(path)
                continue
            with os.fdopen(descriptor, "w") as handle:
                handle.write(str(os.getpid()))
            return

    def is_held(self, run_id):
        """True if a live process (this one included) holds the run's lock. False means a
        run that says RUNNING is a crashed run."""
        try:
            with open(self._path(run_id, "lock"), encoding="utf-8") as handle:
                owner = int(handle.read().strip() or 0)
        except (OSError, ValueError):
            return False
        return bool(owner) and _pid_alive(owner)

    def release(self, run_id):
        try:
            os.remove(self._path(run_id, "lock"))
        except FileNotFoundError:
            pass

    def request(self, run_id, kind):
        if not self.exists(run_id):
            raise StoreError(f"no run {run_id!r}")
        with open(self._path(run_id, kind), "w", encoding="utf-8") as handle:
            handle.write("requested\n")

    def requested(self, run_id, kind):
        return os.path.exists(self._path(run_id, kind))

    def clear_request(self, run_id, kind):
        try:
            os.remove(self._path(run_id, kind))
        except FileNotFoundError:
            pass

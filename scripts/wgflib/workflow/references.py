"""Reference files a run pins when it starts, so an edit made during the run never applies to it.

A workflow may list Factory files under `pinned_references` (paths relative to the Factory
root, paths.ROOT). When a run starts, the engine copies each one into the run directory
(`references/<path>`) and records its digest in the run's params (`pinned_references`,
{path: "sha256:<hex>"}), which the WORKFLOW_STARTED event corroborates like every other
param (integrity.GUARDED_PARAMS). A step that judges against a pinned file reads the run's
copy through `read`, which refuses a copy whose digest is not the one recorded: the
thresholds a run is held to are the ones it started under. A run started before its
workflow pinned anything reads the live file, and says so (`pinned: False`).

The kernel does not know what any pinned file means; it copies bytes and compares digests.
"""

import hashlib
import os

from .. import paths

__all__ = ["DIRECTORY", "PARAM", "PinError", "collect", "digest", "pin", "read"]

DIRECTORY = "references"
PARAM = "pinned_references"


class PinError(Exception):
    """A pinned reference is missing, unreadable, or not the bytes the run recorded."""


def digest(data):
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _relative(path):
    path = str(path).replace("\\", "/")
    if not path or path.startswith("/") or ".." in path.split("/"):
        raise PinError(f"pinned reference {path!r} must be a path inside the Factory root")
    return path


def collect(relpaths, root=None):
    """{path: bytes} for each Factory file in `relpaths`. Raises PinError for a path that is
    absent or unreadable."""
    root = root or paths.ROOT
    found = {}
    for relpath in relpaths or ():
        relpath = _relative(relpath)
        source = os.path.join(root, *relpath.split("/"))
        try:
            with open(source, "rb") as handle:
                found[relpath] = handle.read()
        except OSError as exc:
            raise PinError(f"pinned reference {relpath} cannot be read: {exc}")
    return found


def pin(collected, run_dir):
    """Write `collected` ({path: bytes}) into `run_dir`/references; {path: digest}."""
    pins = {}
    for relpath, data in collected.items():
        target = os.path.join(run_dir, DIRECTORY, *relpath.split("/"))
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "wb") as handle:
            handle.write(data)
        pins[relpath] = digest(data)
    return pins


def read(relpath, environment=None, run_dir=None, root=None):
    """(text, digest, pinned) for a reference: the run's pinned copy when the run pinned it,
    else the live file under the Factory root. Raises PinError when the run pinned it and the
    copy is gone or is not the bytes it recorded."""
    relpath = _relative(relpath)
    pins = (environment or {}).get(PARAM) or {}
    if isinstance(pins, dict) and relpath in pins:
        if not run_dir:
            raise PinError(f"{relpath} is pinned by this run, but the run directory is unknown")
        path = os.path.join(run_dir, DIRECTORY, *relpath.split("/"))
        try:
            with open(path, "rb") as handle:
                data = handle.read()
        except OSError as exc:
            raise PinError(f"the run's pinned copy of {relpath} cannot be read: {exc}")
        found = digest(data)
        if found != pins[relpath]:
            raise PinError(f"the run's pinned copy of {relpath} is {found}, but the run "
                           f"started with {pins[relpath]}: it was edited after the start")
        return data.decode("utf-8"), found, True
    path = os.path.join(root or paths.ROOT, *relpath.split("/"))
    try:
        with open(path, "rb") as handle:
            data = handle.read()
    except OSError as exc:
        raise PinError(f"{relpath} cannot be read: {exc}")
    return data.decode("utf-8"), digest(data), False

"""Where a title's game repository is checked out, and who is working in it right now.

Every step that touches the game repository - init (where it clones to), assets (when it
writes into the repository), develop, review, sdk, verify and release - finds it here, with
ONE precedence (docs/checkouts.md):

    1. the step's `with:`        `repo_dir`, or its alias `game_repo`: the checkout itself
    2. WGF_GAME_REPO             the checkout itself, for every step
    3. scaffold-record           `repository.local_path`, where init put it - when the path
                                 exists on disk; a recorded path that does not is skipped
                                 with a warning (a run resumed on another machine)
    4. <checkouts>/<name>        the checkouts directory joined with the scaffold-record's
                                 `repository.name` (init: the name it is about to create)

The checkouts directory is `factory.checkouts`. Before it existed every module had its own
key; they still work, as deprecated aliases, read in this order when `factory.checkouts` is
unset - the first one set wins, and any that disagree with the winner are warned about:

    develop.checkouts, init.projects_dir, review.checkouts, sdk.games_dir,
    verification.checkouts, release.checkouts

`sdk.game_repo` (a checkout, not a directory of them) is honoured for the sdk step only,
between WGF_GAME_REPO and the scaffold-record, with a deprecation warning. A step's own
`with: checkouts` (or `games_dir`) overrides the checkouts directory for that step.

Every relative path - `with:`, WGF_GAME_REPO, a recorded local_path, the checkouts
directory - resolves against the Factory root, never the working directory, so one
configuration names one place from wherever `wgf` runs. A repository name read from an
artifact goes through paths.checkout_path's single-directory-entry guard.

The lock. `hold()` is an advisory lock on one checkout, keyed by its real path and kept in
the Factory's storage directory (`<storage>/checkouts/<digest>.lock`), taken for the
duration of a step's execute. A second run reaching the same checkout while the first is
inside a step is refused (CheckoutLocked names the holder), instead of both interleaving
in one working tree. The holder is named by pid + start time + run id, like the run lock
(wgflib.workflow.store): a dead holder - even one whose pid was recycled - is taken over; a
holder of the same run (a resumed or continued run, a nested hold) is never refused.
"""

import contextlib
import hashlib
import json
import os
import secrets
import threading
import time

from . import paths
from .workflow.store import _pid_alive, _start_time

__all__ = ["locate", "Located", "CheckoutError", "CheckoutLocked", "hold", "StepLease",
           "storage_of", "record_path", "resolve", "LEGACY_KEYS", "ENV", "PARAM_KEYS"]

ENV = "WGF_GAME_REPO"
# The step `with:` keys that name the checkout itself. Both spellings existed; they are one.
PARAM_KEYS = ("repo_dir", "game_repo")
# The step `with:` keys that name the checkouts directory, for that step only.
PARAM_BASE_KEYS = ("checkouts", "games_dir")
# Deprecated per-module keys for the checkouts directory, in the order they are read when
# factory.checkouts is unset. develop.checkouts first: it was the documented base (review
# fell back to it); init.projects_dir next: it is where init cloned.
LEGACY_KEYS = (("develop", "checkouts"), ("init", "projects_dir"), ("review", "checkouts"),
               ("sdk", "games_dir"), ("verification", "checkouts"), ("release", "checkouts"))
DEFAULT_CHECKOUTS = ".."

LOCK_DIR = "checkouts"
# An empty lock file younger than this is being written by its creator.
LOCK_GRACE_SECONDS = 5.0


class CheckoutError(ValueError):
    """No checkout can be named: a hostile repository name, or no name at all."""


class CheckoutLocked(RuntimeError):
    """Another live run is inside a step working in this checkout."""


class Located(tuple):
    """(path, source): the checkout, and which rule of the precedence named it."""

    __slots__ = ()

    def __new__(cls, path, source):
        return super().__new__(cls, (path, source))

    path = property(lambda self: self[0])
    source = property(lambda self: self[1])


def _section(config, name):
    if config is None:
        return {}
    if hasattr(config, "section"):
        return config.section(name) or {}
    return (config.get(name) if isinstance(config, dict) else None) or {}


def _top(config, key):
    if config is None:
        return None
    if hasattr(config, "data"):
        return (config.data or {}).get(key)
    return config.get(key) if isinstance(config, dict) else None


def resolve(path):
    """An absolute, normalized path: `~` expanded, relative to the Factory root."""
    path = os.path.expanduser(str(path))
    if not os.path.isabs(path):
        path = os.path.join(paths.ROOT, path)
    return os.path.normpath(path)


def record_path(path):
    """How init records a checkout in scaffold-record `repository.local_path`.

    Relative to the Factory root (forward slashes) when the checkout is beside the Factory -
    anywhere under the Factory's parent directory, the default layout (`../<title>`) - so a
    run resumed on another machine with the same layout finds it. Absolute otherwise: a
    `../../../tmp/x` path means nothing anywhere else either, and the absolute one is at least
    exact. Either way the resolver checks that it exists before using it."""
    path = os.path.normpath(os.path.abspath(path))
    parent = os.path.dirname(paths.ROOT)
    try:
        inside = os.path.commonpath([parent, path]) == parent
    except ValueError:  # another drive
        inside = False
    if inside:
        return os.path.relpath(path, paths.ROOT).replace(os.sep, "/")
    return path.replace(os.sep, "/") if os.sep == "/" else path


def checkouts_base(config, section=None, params=None, warnings=None):
    """(absolute checkouts directory, source): where `<name>` checkouts live."""
    warnings = warnings if warnings is not None else []
    params = params or {}
    for key in PARAM_BASE_KEYS:
        if params.get(key):
            return resolve(params[key]), f"step with: {key}"
    legacy = [(f"{sec}.{key}", _section(config, sec).get(key)) for sec, key in LEGACY_KEYS]
    legacy = [(name, value) for name, value in legacy if isinstance(value, str) and value]
    configured = _top(config, "checkouts")
    if isinstance(configured, str) and configured:
        chosen, source = resolve(configured), "factory.checkouts"
    elif legacy:
        name, value = legacy[0]
        chosen, source = resolve(value), f"factory.{name} (deprecated: use factory.checkouts)"
    else:
        return resolve(DEFAULT_CHECKOUTS), "the default checkouts directory (..)"
    disagree = sorted({name for name, value in legacy if resolve(value) != chosen})
    if disagree:
        warnings.append(f"{', '.join('factory.' + n for n in disagree)} disagree with "
                        f"{source.split(' ')[0]} ({paths.display(chosen)}) and are ignored: "
                        "every step uses one checkouts directory")
    return chosen, source


def locate(config, scaffold, section, params=None, environ=None, *, name=None, logger=None):
    """(path, source) of the game repository checkout, or CheckoutError.

    `section` is the step's factory.yaml section (init, assets, develop, review, sdk,
    verification, release); it matters only for the deprecated `sdk.game_repo`. `name` is
    the repository name when there is no scaffold-record to read it from (init, or a step
    falling back to the title id). The path is not required to exist - init is about to
    create it; every other step checks what it needs and names `source` when it is not
    there."""
    environ = os.environ if environ is None else environ
    params = params or {}
    warnings = []
    repository = (scaffold or {}).get("repository") or {}
    if "name" in repository:
        # A record naming `..` (or a path) is refused whichever rule decides below: it is
        # not a record any later step should act on.
        try:
            paths.checkout_path(paths.ROOT, repository["name"])
        except ValueError as exc:
            raise CheckoutError(str(exc))

    def done(path, source):
        for warning in warnings:
            if logger is not None:
                logger.warning("checkout", problem=warning)
        # A game checkout is never the Factory itself, nor a directory holding it: a step
        # would build, commit or package in the Factory's own tree.
        try:
            holds_factory = os.path.commonpath([os.path.realpath(path),
                                                os.path.realpath(paths.ROOT)]) \
                == os.path.realpath(path)
        except ValueError:  # another drive
            holds_factory = False
        if holds_factory:
            raise CheckoutError(f"{path} (from {source}) is the Factory's own tree, or holds "
                                "it; a game checkout is a separate repository")
        return Located(path, source)

    explicit = [(key, params.get(key)) for key in PARAM_KEYS if params.get(key)]
    if explicit:
        key, value = explicit[0]
        if len({resolve(v) for _, v in explicit}) > 1:
            raise CheckoutError("the step's with: repo_dir and game_repo name different "
                                "checkouts; they are one setting - give one")
        return done(resolve(value), f"step with: {key}")
    if environ.get(ENV):
        return done(resolve(environ[ENV]), ENV)
    if section == "sdk" and _section(config, "sdk").get("game_repo"):
        warnings.append("factory.sdk.game_repo is deprecated: use the step's with: game_repo, "
                        "WGF_GAME_REPO, or factory.checkouts")
        return done(resolve(_section(config, "sdk")["game_repo"]),
                    "factory.sdk.game_repo (deprecated)")

    recorded = repository.get("local_path")
    if isinstance(recorded, str) and recorded:
        path = resolve(recorded)
        if os.path.isdir(path):
            return done(path, "scaffold-record repository.local_path")
        warnings.append(f"scaffold-record repository.local_path {recorded} does not exist "
                        "here; falling back to the checkouts directory")

    repo_name = repository.get("name") or name
    if not repo_name:
        for warning in warnings:
            if logger is not None:
                logger.warning("checkout", problem=warning)
        raise CheckoutError(
            "no game repository checkout: no step with: repo_dir, no WGF_GAME_REPO, and no "
            "scaffold-record naming the repository")
    base, source = checkouts_base(config, section, params, warnings)
    try:
        path = paths.checkout_path(base, repo_name)
    except ValueError as exc:
        raise CheckoutError(str(exc))
    return done(path, f"{source} + repository name {repo_name}")


# -- the lock ---------------------------------------------------------------------------------

# Leases this process holds, by lock path: [run id, depth].
_HELD = {}
_HELD_LOCK = threading.RLock()


def storage_of(context):
    """The Factory storage directory of the run a step context belongs to, or None (a bare
    context in a unit test has no run directory, and no run to name as a holder)."""
    run_dir = getattr(context, "run_dir", None)
    if not run_dir:
        return None
    # <storage>/workflows/<run-id> (wgflib.workflow.store). A run directory laid out any
    # other way is not a store's, and its grandparent is no place for a lock.
    workflows = os.path.dirname(os.path.abspath(run_dir))
    if os.path.basename(workflows) != "workflows":
        return None
    return os.path.dirname(workflows)


def lock_path(storage, checkout):
    real = os.path.normcase(os.path.realpath(checkout))
    digest = hashlib.sha256(real.encode("utf-8", "surrogateescape")).hexdigest()[:32]
    return os.path.join(storage, LOCK_DIR, f"{digest}.lock")


def _read(path):
    """(holder dict or None, age seconds) - None holder for an empty or torn file; raises
    FileNotFoundError when there is no lock."""
    with open(path, encoding="utf-8") as handle:
        text = handle.read()
    age = time.time() - os.stat(path).st_mtime
    try:
        holder = json.loads(text)
    except ValueError:
        return None, age
    return (holder if isinstance(holder, dict) and holder.get("pid") else None), age


def _alive(holder):
    try:
        pid = int(holder.get("pid"))
    except (TypeError, ValueError):
        return False
    if pid == os.getpid():
        return True  # this process: _HELD decides whether it is still held
    if not _pid_alive(pid):
        return False
    started = holder.get("started")
    now = _start_time(pid)
    return started is None or now is None or now == started


def _describe(holder, checkout):
    step = f", step {holder['step']}" if holder.get("step") else ""
    return (f"{checkout} is in use by run {holder.get('run_id') or 'unknown'} (process "
            f"{holder.get('pid')}{step}). Two runs in one working tree interleave their "
            "commits; wait for it to finish its step, or cancel it, then resume")


class _Lease:
    def __init__(self, path, run_id, owned):
        self.path = path
        self.run_id = run_id
        self.owned = owned      # False: another process of the same run holds the file

    def release(self):
        with _HELD_LOCK:
            entry = _HELD.get(self.path)
            if entry is None:
                return
            entry[1] -= 1
            if entry[1] > 0:
                return
            del _HELD[self.path]
            if not self.owned:
                return
            try:
                holder, _ = _read(self.path)
            except FileNotFoundError:
                return
            except OSError:
                return
            if holder and holder.get("pid") == os.getpid() and holder.get("run_id") == self.run_id:
                try:
                    os.remove(self.path)
                except FileNotFoundError:
                    pass


def _break_stale(path, holder_seen):
    """Remove a stale lock under an O_EXCL guard, after re-reading it there - so two takers
    that both saw the same dead holder cannot both end up holding the checkout."""
    guard = path + ".takeover"
    try:
        descriptor = os.open(guard, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError:
        try:
            guard_holder, age = _read(guard)
        except FileNotFoundError:
            return
        except OSError:
            guard_holder, age = None, LOCK_GRACE_SECONDS + 1
        if (guard_holder and _alive(guard_holder) and guard_holder.get("pid") != os.getpid()) \
                or (guard_holder is None and age < LOCK_GRACE_SECONDS):
            time.sleep(0.005)
            return
        try:
            os.remove(guard)
        except FileNotFoundError:
            pass
        return
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(json.dumps({"pid": os.getpid(), "started": _start_time(os.getpid())}))
        try:
            holder, age = _read(path)
        except FileNotFoundError:
            return
        if holder == holder_seen and (holder is not None or age >= LOCK_GRACE_SECONDS):
            try:
                os.remove(path)
            except FileNotFoundError:
                pass
    finally:
        try:
            os.remove(guard)
        except FileNotFoundError:
            pass


def acquire(checkout, run_id, storage, step=None):
    """A lease on `checkout` for `run_id`, or CheckoutLocked. Release it with .release()."""
    path = lock_path(storage, checkout)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    deadline = time.monotonic() + LOCK_GRACE_SECONDS + 1
    with _HELD_LOCK:
        entry = _HELD.get(path)
        if entry is not None:
            if entry[0] == run_id:
                entry[1] += 1
                return _Lease(path, run_id, owned=True)
            raise CheckoutLocked(_describe({"run_id": entry[0], "pid": os.getpid()},
                                           checkout))
        while True:
            try:
                descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            except FileExistsError:
                try:
                    holder, age = _read(path)
                except FileNotFoundError:
                    continue
                if holder is None:
                    if age < LOCK_GRACE_SECONDS and time.monotonic() < deadline:
                        time.sleep(0.01)  # being written by its creator
                        continue
                    _break_stale(path, None)
                elif holder.get("run_id") == run_id and _alive(holder) \
                        and holder.get("pid") != os.getpid():
                    # The same run, from another live process: never refused, never removed.
                    _HELD[path] = [run_id, 1]
                    return _Lease(path, run_id, owned=False)
                elif holder.get("pid") != os.getpid() and _alive(holder):
                    raise CheckoutLocked(_describe(holder, checkout))
                else:
                    # A dead holder, a recycled pid, or a lock this process left behind
                    # without a lease (an earlier engine that crashed in-process).
                    _break_stale(path, holder)
                if time.monotonic() > deadline:
                    raise CheckoutLocked(f"{checkout}: could not take over its stale lock "
                                         f"{path}")
                continue
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(json.dumps({
                    "pid": os.getpid(), "started": _start_time(os.getpid()),
                    "run_id": run_id, "step": step,
                    "checkout": os.path.realpath(checkout),
                    "nonce": secrets.token_hex(4)}))
                handle.flush()
            _HELD[path] = [run_id, 1]
            return _Lease(path, run_id, owned=True)


@contextlib.contextmanager
def hold(checkout_path, run_id, storage=None, step=None):
    """Hold the checkout's advisory lock for the block. `storage` is the Factory storage
    directory; without one there is nowhere to keep a lock and nothing is held."""
    if storage is None:
        yield None
        return
    lease = acquire(checkout_path, run_id, storage, step)
    try:
        yield lease
    finally:
        lease.release()


class StepLease:
    """What a step's execute holds: `with StepLease(context) as lease:` around the body,
    `lease.take(path)` once the checkout is known (raises CheckoutLocked). Whatever was
    taken is released when the block ends, however it ends."""

    def __init__(self, context):
        self.context = context
        self.leases = []

    def take(self, checkout):
        storage = storage_of(self.context)
        if storage is None:
            return None
        run_id = getattr(self.context, "run_id", None) or "local"
        step = getattr(self.context, "current_step", None)
        lease = acquire(checkout, run_id, storage, step)
        self.leases.append(lease)
        return lease

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        while self.leases:
            self.leases.pop().release()
        return False

"""The web-game-template revision this Factory expects, and a checkout of exactly it.

The template is a separate repository (the source of truth for template code, the example
games, platform adapters and the PixiJS/Three.js support). The Factory never copies its
source; it pins one commit in `workspace/config/template.lock.json` and everything that has
to read template files - the golden runs, the SDK inspector's tests, the release and
hashing differential tests - reads a checkout of that commit, never "whatever the sibling
working copy happens to be at".

    checkout()   a directory whose HEAD is the pinned commit, created on demand:
                   1. $WGF_TEMPLATE_DIR, if set - it must already be at the pinned commit,
                      or it is refused (TemplateDrift); it is never moved;
                   2. a cached clone, $WGF_TEMPLATE_CACHE or ~/.cache/wgf/templates/<sha>;
                   3. otherwise one is cloned: from the sibling ../web-game-template when it
                      holds the commit (offline), else from the lock's URL.
    drift()      where the sibling working copy stands relative to the pin (informational).

Adopting another template revision is deliberate: run the golden runs with
WGF_TEMPLATE_COMMIT=<sha>, make them pass, then change the lock in the same commit.
"""

import json
import os
import re
import shutil
import tempfile

from . import paths, procs

__all__ = ["LOCK", "TemplateError", "TemplateDrift", "load_lock", "expected_commit",
           "checkout", "ensure_dependencies", "drift", "head_of"]

LOCK = os.path.join(paths.ROOT, "workspace", "config", "template.lock.json")
_SHA = re.compile(r"^[0-9a-f]{40}$")
_LOCK_KEYS = ("repository", "url", "commit", "ref", "validated_on")


class TemplateError(RuntimeError):
    """The pinned template cannot be obtained."""


class TemplateDrift(TemplateError):
    """A template checkout was offered that is not at the pinned commit."""


def load_lock(path=LOCK):
    try:
        with open(path, encoding="utf-8") as handle:
            lock = json.load(handle)
    except (OSError, ValueError) as exc:
        raise TemplateError(f"{paths.display(path)}: unreadable: {exc}")
    missing = [key for key in _LOCK_KEYS if not lock.get(key)]
    if missing:
        raise TemplateError(f"{paths.display(path)}: missing {', '.join(missing)}")
    if not _SHA.match(lock["commit"]):
        raise TemplateError(f"{paths.display(path)}: commit must be a full 40-hex sha, "
                            f"not {lock['commit']!r}")
    return lock


def expected_commit(lock=None):
    """The commit to use: $WGF_TEMPLATE_COMMIT (a deliberate override), else the lock's."""
    override = os.environ.get("WGF_TEMPLATE_COMMIT")
    if override:
        if not _SHA.match(override):
            raise TemplateError(f"WGF_TEMPLATE_COMMIT must be a full 40-hex sha, "
                                f"not {override!r}")
        return override
    return (lock or load_lock())["commit"]


def _git(args, cwd=None, timeout=300):
    return procs.run(["git", *args], cwd=cwd, timeout=timeout, heartbeat_seconds=0)


def head_of(directory):
    """The commit `directory` has checked out, or None if it is not a git work tree."""
    if not os.path.isdir(directory):
        return None
    done = _git(["-C", directory, "rev-parse", "HEAD"], timeout=60)
    sha = done.stdout.strip() if done.ok else ""
    return sha if _SHA.match(sha) else None


def _has_commit(directory, commit):
    return _git(["-C", directory, "cat-file", "-e", f"{commit}^{{commit}}"], timeout=60).ok


def _cache_root():
    return os.path.abspath(os.path.expanduser(
        os.environ.get("WGF_TEMPLATE_CACHE") or os.path.join("~", ".cache", "wgf", "templates")))


def checkout(commit=None):
    """A directory at exactly the pinned commit. Raises TemplateError/TemplateDrift."""
    lock = load_lock()
    commit = commit or expected_commit(lock)

    offered = os.environ.get("WGF_TEMPLATE_DIR")
    if offered:
        head = head_of(offered)
        if head != commit:
            raise TemplateDrift(
                f"WGF_TEMPLATE_DIR={offered} is at {head or 'no git commit'}, but the "
                f"Factory expects web-game-template {commit} "
                f"({paths.display(LOCK)}). Check that commit out there, or unset it.")
        return os.path.abspath(offered)

    target = os.path.join(_cache_root(), commit)
    if head_of(target) == commit:
        return target

    sources = []
    if os.path.isdir(paths.TEMPLATE) and _has_commit(paths.TEMPLATE, commit):
        sources.append(paths.TEMPLATE)
    sources.append(lock["url"])
    os.makedirs(_cache_root(), exist_ok=True)
    problems = []
    for source in sources:
        scratch = tempfile.mkdtemp(prefix=f".{commit[:12]}-", dir=_cache_root())
        try:
            cloned = _git(["clone", "--quiet", "--no-checkout", source, scratch], timeout=900)
            if not cloned.ok:
                problems.append(f"clone {source}: {cloned.tail(3)}")
                continue
            moved = _git(["-C", scratch, "checkout", "--quiet", "--detach", commit])
            if not moved.ok or head_of(scratch) != commit:
                problems.append(f"{source} has no commit {commit}: {moved.tail(3)}")
                continue
            if os.path.exists(target):
                shutil.rmtree(target, ignore_errors=True)
            os.replace(scratch, target)
            scratch = None
            return target
        finally:
            if scratch:
                shutil.rmtree(scratch, ignore_errors=True)
    raise TemplateError(f"cannot obtain web-game-template {commit}: " + "; ".join(problems))


def ensure_dependencies(directory, timeout=1200):
    """Install the checkout's node dependencies once (pnpm, frozen lockfile, store first).
    Returns None when they are present, else the pnpm ProcessResult."""
    if os.path.exists(os.path.join(directory, "node_modules", ".modules.yaml")):
        return None
    done = procs.run(["pnpm", "install", "--frozen-lockfile", "--prefer-offline"],
                     cwd=directory, timeout=timeout)
    if not done.ok:
        raise TemplateError(f"pnpm install in {directory} failed: {done.tail(5)}")
    return done


def drift(lock=None):
    """Where the sibling working copy stands against the pin. Never raises."""
    try:
        commit = expected_commit(lock)
    except TemplateError as exc:
        return {"error": str(exc)}
    head = head_of(paths.TEMPLATE)
    return {
        "sibling": paths.TEMPLATE if os.path.isdir(paths.TEMPLATE) else None,
        "sibling_head": head,
        "expected": commit,
        "sibling_at_pin": head == commit,
        "sibling_has_pin": bool(head) and _has_commit(paths.TEMPLATE, commit),
    }

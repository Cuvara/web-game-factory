"""Reviewer isolation: fingerprint the checkout before and after, list every difference,
and put the checkout back.

A reviewer is read-only. Asking it to be is not enough - an agent that "fixes one small
thing while it is in there" has turned a review into an unreviewed commit - so the step
fingerprints everything a reviewer could change and compares:

  * HEAD, the branch HEAD points at, and every ref (a reviewer that commits, stashes,
    tags or resets is caught here);
  * `git status --porcelain=v1 -z --untracked-files=all --ignored=no` (staged changes);
  * sha256 and executable bit of every tracked file and every untracked, non-ignored file;
  * explicitly, whatever git's view: the package manifest, lockfiles, tests, CI and tool
    configuration - by path, so a reviewer that also edited .gitignore to hide them is
    still caught;
  * .git/config and .git/hooks - a hook is code that runs on the next commit;
  * the set of top-level ignored entries (a new one is a reviewer writing somewhere git
    was told to look away from);
  * the Factory's own guarded paths: the workflow definitions and installation config.

What it cannot see: changes *inside* an ignored entry that already existed (node_modules,
dist), and anything outside the checkout and the guarded paths. docs/review-module.md
says so.

Restoring is safe because the step refuses to review a dirty checkout: before the review
the tree equals HEAD, so `reset --hard` to the recorded HEAD plus `clean -fd` (never -x)
is an exact inverse for everything git tracks, and the bytes of every explicit, metadata
and guarded file are kept in memory to be written back.
"""

import hashlib
import os
import re
import shutil
import stat

from wgflib import procs

__all__ = ["Git", "GitError", "Snapshot", "take", "diff", "restore", "is_sensitive",
           "EXPLICIT_PATHS"]

# Paths fingerprinted by name, whatever git thinks of them. Directories are walked.
EXPLICIT_PATHS = (
    "package.json", "pnpm-lock.yaml", "pnpm-workspace.yaml", "package-lock.json",
    "npm-shrinkwrap.json", "yarn.lock", "bun.lockb", ".npmrc", ".nvmrc", ".gitignore",
    ".gitattributes", "game.config.yaml", "tsconfig.json", "tsconfig.base.json",
    "vite.config.ts", "vitest.config.ts", "playwright.config.ts", "eslint.config.js",
    "eslint.config.mjs", ".eslintrc.json", ".prettierrc", ".prettierrc.json",
    "tests", ".github", ".husky",
)

_SENSITIVE = re.compile(
    r"(^|/)(package\.json|[^/]*lock[^/]*\.(json|yaml)|yarn\.lock|bun\.lockb|\.npmrc|\.nvmrc|"
    r"\.gitignore|\.gitattributes|game\.config\.yaml|tsconfig[^/]*\.json|"
    r"[^/]*\.config\.(js|cjs|mjs|ts|mts|json)|\.eslintrc[^/]*|\.prettierrc[^/]*)$"
    r"|^(tests|test|e2e|\.github|\.husky)/|(^|/)__tests__/|\.(test|spec)\.[cm]?[jt]sx?$"
)

_SKIP_DIRS = {"node_modules", ".git"}
_KEEP_BYTES = 4 * 1024 * 1024


def is_sensitive(path):
    return bool(_SENSITIVE.search(path.replace(os.sep, "/")))


class GitError(RuntimeError):
    pass


class Git:
    """git in one checkout, through wgflib.procs like every process a step starts."""

    def __init__(self, root):
        self.root = root

    def run(self, *args, check=True, raw=False):
        env = dict(os.environ)
        env["GIT_OPTIONAL_LOCKS"] = "0"  # `status` must not rewrite the index it inspects
        env["GIT_TERMINAL_PROMPT"] = "0"
        env["LC_ALL"] = "C"
        result = procs.run(["git", *args], cwd=self.root, env=env, timeout=120,
                           heartbeat_seconds=None, grace_seconds=1.0, poll_seconds=0.01)
        if check and not result.ok:
            raise GitError(f"git {' '.join(args)} failed: {result.tail(20)}")
        return result if raw else result.stdout

    def ok(self, *args):
        return self.run(*args, check=False, raw=True).ok

    def is_repository(self):
        if not os.path.isdir(self.root):
            return False
        result = self.run("rev-parse", "--is-inside-work-tree", check=False, raw=True)
        return result.ok and result.stdout.strip() == "true"

    def head(self):
        result = self.run("rev-parse", "HEAD", check=False, raw=True)
        return result.stdout.strip() if result.ok else None

    def git_dir(self):
        return self.run("rev-parse", "--absolute-git-dir").strip()

    def status(self):
        return self.run("status", "--porcelain=v1", "-z", "--untracked-files=all",
                        "--ignored=no")

    def dirty(self):
        return [entry[3:] for entry in self.status().split("\0") if entry.strip()]


def _digest_file(path):
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return None, None
    if stat.S_ISLNK(info.st_mode):
        return "link:" + os.readlink(path), None
    if not stat.S_ISREG(info.st_mode):
        return "special", None
    sha = hashlib.sha256()
    kept = [] if info.st_size <= _KEEP_BYTES else None
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 16), b""):
            sha.update(chunk)
            if kept is not None:
                kept.append(chunk)
    mode = "x" if info.st_mode & stat.S_IXUSR else "-"
    return f"{mode}:{sha.hexdigest()}", (b"".join(kept) if kept is not None else None,
                                          info.st_mode)


def _walk(root, relative_to, keep):
    """{relpath: digest} of every file under `root` (a file or a directory)."""
    digests = {}
    if os.path.isdir(root) and not os.path.islink(root):
        for directory, dirs, files in os.walk(root):
            dirs[:] = sorted(d for d in dirs if d not in _SKIP_DIRS)
            for name in sorted(files):
                path = os.path.join(directory, name)
                rel = os.path.relpath(path, relative_to).replace(os.sep, "/")
                digest, content = _digest_file(path)
                if digest is not None:
                    digests[rel] = digest
                    if content is not None:
                        keep[rel] = content
    else:
        digest, content = _digest_file(root)
        if digest is not None:
            rel = os.path.relpath(root, relative_to).replace(os.sep, "/")
            digests[rel] = digest
            if content is not None:
                keep[rel] = content
    return digests


class Snapshot:
    def __init__(self):
        self.head = None
        self.branch = None
        self.refs = {}
        self.status = ""
        self.files = {}         # checkout files git sees: tracked + untracked-not-ignored
        self.explicit = {}      # EXPLICIT_PATHS, by path
        self.ignored = set()    # top-level ignored entries, collapsed
        self.gitmeta = {}       # .git/config, .git/hooks/*
        self.factory = {}       # absolute path -> digest, for guarded Factory paths
        self.kept = {}          # ("explicit"|"gitmeta"|"factory", key) -> (bytes, mode)
        self.git_dir = None

    @property
    def checked_paths(self):
        return len(set(self.files) | set(self.explicit)) + len(self.gitmeta) + len(self.factory)


def take(git, guarded_paths=()):
    snap = Snapshot()
    root = git.root
    snap.git_dir = git.git_dir()
    snap.head = git.head()
    symbolic = git.run("symbolic-ref", "-q", "HEAD", check=False, raw=True)
    snap.branch = symbolic.stdout.strip() if symbolic.ok else None
    for line in git.run("for-each-ref", "--format=%(objectname) %(refname)").splitlines():
        sha, _, name = line.partition(" ")
        if name:
            snap.refs[name] = sha
    snap.status = git.status()

    tracked = git.run("ls-files", "-z", "--cached").split("\0")
    untracked = git.run("ls-files", "-z", "--others", "--exclude-standard").split("\0")
    for rel in sorted({p for p in tracked + untracked if p}):
        digest, _ = _digest_file(os.path.join(root, rel))
        snap.files[rel] = digest or "missing"

    keep = {}
    for rel in EXPLICIT_PATHS:
        snap.explicit.update(_walk(os.path.join(root, rel), root, keep))
    snap.kept.update({("explicit", k): v for k, v in keep.items()})

    ignored = git.run("ls-files", "-z", "--others", "--ignored", "--exclude-standard",
                      "--directory")
    snap.ignored = {p.rstrip("/") for p in ignored.split("\0") if p}

    keep = {}
    for rel in ("config", "hooks"):
        snap.gitmeta.update(_walk(os.path.join(snap.git_dir, rel), snap.git_dir, keep))
    snap.kept.update({("gitmeta", k): v for k, v in keep.items()})

    for guarded in guarded_paths:
        keep = {}
        base = os.path.dirname(guarded)
        for rel, digest in _walk(guarded, base, keep).items():
            snap.factory[os.path.join(base, rel)] = digest
        snap.kept.update({("factory", os.path.join(base, k)): v for k, v in keep.items()})
    return snap


def _compare(before, after, scope, sensitive_of):
    changes = []
    for path in sorted(set(before) | set(after)):
        old, new = before.get(path), after.get(path)
        if old == new:
            continue
        if old in (None, "missing"):
            change = "added"
        elif new in (None, "missing"):
            change = "deleted"
        else:
            change = "modified"
        changes.append({"path": path, "change": change, "scope": scope,
                        "sensitive": sensitive_of(path)})
    return changes


def diff(before, after):
    """Every difference between two snapshots, as review-report isolation violations."""
    violations = []
    if before.head != after.head:
        violations.append({"path": "HEAD", "change": "head-moved", "scope": "checkout",
                           "sensitive": True})
    if before.branch != after.branch:
        violations.append({"path": "HEAD", "change": "branch-changed", "scope": "checkout",
                           "sensitive": True})
    for ref in sorted(set(before.refs) | set(after.refs)):
        if before.refs.get(ref) != after.refs.get(ref):
            violations.append({"path": ref, "change": "ref-changed", "scope": "checkout",
                               "sensitive": True})
    seen = set()
    for change in (_compare(before.files, after.files, "checkout", is_sensitive)
                   + _compare(before.explicit, after.explicit, "checkout", lambda _: True)):
        if change["path"] not in seen:
            seen.add(change["path"])
            violations.append(change)
    if before.status != after.status and not seen:
        # Content identical but the index moved: something was staged and unstaged into
        # the same bytes, or a mode flipped. Still a write.
        violations.append({"path": "(index)", "change": "status-changed", "scope": "checkout",
                           "sensitive": False})
    for path in sorted(after.ignored - before.ignored):
        violations.append({"path": path, "change": "added", "scope": "checkout",
                           "sensitive": is_sensitive(path)})
    for change in _compare(before.gitmeta, after.gitmeta, "checkout", lambda _: True):
        change["path"] = ".git/" + change["path"]
        change["change"] = "git-metadata"
        violations.append(change)
    violations.extend(_compare(before.factory, after.factory, "factory", lambda _: True))
    return violations


def _write_back(path, kept):
    content, mode = kept
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.islink(path) or os.path.isdir(path):
        _remove(path)
    with open(path, "wb") as handle:
        handle.write(content)
    os.chmod(path, stat.S_IMODE(mode))


def _remove(path):
    if os.path.isdir(path) and not os.path.islink(path):
        shutil.rmtree(path, ignore_errors=True)
    elif os.path.lexists(path):
        os.remove(path)


def _restore_files(before, after, kind, root, kept):
    """Put back the byte-kept files of one kind; remove files the reviewer added."""
    problems = []
    for key in sorted(set(before) | set(after)):
        if before.get(key) == after.get(key):
            continue
        path = key if os.path.isabs(key) else os.path.join(root, key)
        if key not in before:
            _remove(path)
        elif (kind, key) in kept:
            _write_back(path, kept[(kind, key)])
        else:
            problems.append(f"{key}: too large to have been kept, cannot restore")
    return problems


def restore(git, before, guarded_paths=()):
    """Undo whatever the reviewer did. Returns (restored, problems)."""
    problems = []
    try:
        after = take(git, guarded_paths)
        if after.branch != before.branch:
            if before.branch:
                git.run("symbolic-ref", "HEAD", before.branch)
            else:
                git.run("update-ref", "--no-deref", "HEAD", before.head)
        for ref in sorted(set(before.refs) | set(after.refs)):
            old, new = before.refs.get(ref), after.refs.get(ref)
            if old == new or ref == before.branch:
                continue
            if old is None:
                git.run("update-ref", "-d", ref)
            else:
                git.run("update-ref", ref, old)
        git.run("reset", "--hard", "-q", before.head)
        git.run("clean", "-f", "-d", "-q")
        for path in sorted(after.ignored - before.ignored):
            _remove(os.path.join(git.root, path))
        after = take(git, guarded_paths)
        problems += _restore_files(before.explicit, after.explicit, "explicit", git.root,
                                   before.kept)
        problems += _restore_files(before.gitmeta, after.gitmeta, "gitmeta", before.git_dir,
                                   before.kept)
        problems += _restore_files(before.factory, after.factory, "factory", "/", before.kept)
        remaining = diff(before, take(git, guarded_paths))
        problems += [f"{v['path']}: still {v['change']} after restore" for v in remaining]
    except (GitError, OSError) as exc:
        problems.append(str(exc))
    return not problems, problems

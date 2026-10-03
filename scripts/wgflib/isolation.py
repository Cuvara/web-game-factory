"""Agent isolation: fingerprint what an agent may not change before and after it runs, list
every difference, and put it back.

Two callers, one mechanism. The `review` step fingerprints the whole checkout plus the
Factory's guarded paths around a reviewer (`take`/`diff`/`restore`). The `develop` step
fingerprints only the guarded paths around a developer (`take_guarded`/`diff`/
`restore_guarded`) - the developer is supposed to write the checkout, and what it may leave
there is decided when its work is committed (wgf_develop/scope.py). The mechanism lives in
the kernel because both steps must judge the same list the same way: a guarded path one of
them forgot is a path an agent can rewrite its judge through.

A reviewer is read-only. Asking it to be is not enough - an agent that "fixes one small
thing while it is in there" has turned a review into an unreviewed commit - so the step
fingerprints everything a reviewer could change and compares:

  * HEAD, the branch HEAD points at, that branch's ref and this checkout's per-worktree
    refs (refs/bisect, refs/worktree, refs/rewritten) - a reviewer that commits, resets or
    switches branches is caught here;
  * `git status --porcelain=v1 -z --untracked-files=all --ignored=no` (staged changes);
  * sha256 and executable bit of every tracked file and every untracked, non-ignored file;
  * explicitly, whatever git's view: the package manifest, lockfiles, tests, CI and tool
    configuration - by path, so a reviewer that also edited .gitignore to hide them is
    still caught;
  * the repository config this checkout runs under (`config` in the common git
    directory), entry by entry - except other branches' `branch.<name>.*` sections and the
    two keys `git worktree add` writes (`extensions.relativeWorktrees`,
    `core.repositoryformatversion`);
  * the git metadata that changes what git or the next commit does: config.worktree, hooks,
    info/ (exclude, attributes, sparse-checkout), objects/info (alternates, grafts),
    submodules' config, hooks and info, and in-progress operation state (MERGE_HEAD,
    rebase-*, sequencer, ...) - a hook is code that runs on the next commit, an
    info/exclude line hides a file from every other check;
  * the set of top-level ignored entries (a new one is a reviewer writing somewhere git
    was told to look away from);
  * everything *inside* the ignored entries that already existed (node_modules, dist), by
    lstat identity - inode, size, mtime and ctime. A write changes ctime, and ctime cannot
    be set back by an unprivileged process, so a reviewer that edits a dependency in
    node_modules and restores its mtime is still caught. Except for a file with more than
    one hard link: pnpm links node_modules files from its machine-wide content store, and
    any other project's install linking the same package moves the shared inode's ctime
    with no write at all - so for those, identity is inode, size and mtime. Those bytes are
    not kept, so a change is reported and cannot be undone (the step BLOCKS).
    `fingerprint_ignored: false` turns this off for checkouts where the walk is too slow;
  * the Factory's own guarded paths: its code (scripts/, bin/), core/ (the workflow
    definitions, the gates and the contracts) and the installation config.

What is not guarded: the rest of the repository. A game repository may have several
worktrees, and delegated agents commit on their own branches in their own worktrees while a
review runs (docs/orca-delegation.md). Their branch refs, tags, the shared stash,
.git/worktrees/* and their branches' config are theirs: a change there is listed by
`outside()` as a note, never a violation, and `restore` never writes, deletes or rewinds
any of it - a restore that "put back" another worktree's branch would destroy its work. The
cost: a reviewer that tags, stashes, or commits on another branch and switches back is
noted, not failed. None of that changes the checkout the review was of.

What it cannot see: anything outside the checkout and the guarded paths, and a process the
reviewer left behind that writes after the second snapshot (wgflib.procs ends the
reviewer's whole tree first; a descendant that detached itself *and* cleared its
environment escapes that - see docs/agent-lifecycle.md). docs/review-module.md says so.

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

from . import gitsafe, paths, procs

__all__ = ["Git", "GitError", "Snapshot", "take", "diff", "outside", "restore",
           "is_sensitive", "EXPLICIT_PATHS", "DEFAULT_GUARDED_PATHS", "guarded_paths",
           "take_guarded", "restore_guarded"]

# The Factory's own code (scripts/, bin/), core/ (the workflow definitions, the gates and the
# contracts) and the installation config: what decides what a review, and every later
# check, is worth. Relative to the Factory root. `factory.review.guarded_paths` replaces
# it for every step that isolates an agent; keep at least these.
DEFAULT_GUARDED_PATHS = ("core", "scripts", "bin", "workspace/config")

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

_SKIP_DIRS = {"node_modules", ".git", "__pycache__"}
_KEEP_BYTES = 4 * 1024 * 1024

# Inside the git directory: what is fingerprinted (and kept, and written back). Objects
# are content-addressed and adding one changes nothing; refs are compared through
# for-each-ref; index, logs and ORIG_HEAD are rewritten by the restore itself; `config` is
# compared entry by entry (_config), because other worktrees write their branches into it.
GIT_METADATA = (
    "config.worktree", "hooks", "info", "objects/info", "modules", "shallow",
    "commondir", "MERGE_HEAD", "MERGE_MSG", "MERGE_MODE", "CHERRY_PICK_HEAD",
    "REVERT_HEAD", "BISECT_START", "rebase-merge", "rebase-apply", "sequencer",
)
# Skipped while walking GIT_METADATA (a submodule's git dir under modules/ holds its own).
_GIT_SKIP = {"objects", "logs", "refs", "index", "ORIG_HEAD", "FETCH_HEAD", "packed-refs",
             "worktrees", "lfs"}


# Refs this checkout owns besides its branch: the per-worktree refs (git-worktree(1)).
_WORKTREE_REFS = ("refs/bisect/", "refs/worktree/", "refs/rewritten/")
# Repository config keys another worktree's `git worktree add` writes. Neither changes how
# this checkout behaves (an extension git does not know makes every later git call fail,
# which the after-snapshot reports as a write).
_SHARED_CONFIG_KEYS = ("extensions.relativeworktrees", "core.repositoryformatversion")


def _owned_ref(name, branches):
    """A ref the guard owns: the checked-out branch, or a per-worktree ref."""
    return name in branches or name.startswith(_WORKTREE_REFS)


def _owned_config_key(key, branch):
    """A config key that changes this checkout. `branch.<name>.*` belongs to that branch:
    another worktree adding a branch with --track writes one."""
    if key in _SHARED_CONFIG_KEYS:
        return False
    section, _, rest = key.partition(".")
    subsection = rest.rpartition(".")[0]
    if section != "branch" or not subsection:
        return True  # branch.autoSetupMerge and the like are repository-wide
    return branch == "refs/heads/" + subsection


def is_sensitive(path):
    return bool(_SENSITIVE.search(path.replace(os.sep, "/")))


class GitError(RuntimeError):
    pass


class Git:
    """git in one checkout, through wgflib.procs like every process a step starts.

    Hardened (wgflib.gitsafe): the checkout's own config cannot make these commands run
    anything - no fsmonitor, hooks or filter drivers - and once the git directory has been
    resolved it is pinned, with the work tree, so a reviewer that rewrites `core.worktree`
    or replaces `.git` cannot aim the restore's `reset --hard` and `clean` elsewhere."""

    def __init__(self, root):
        self.root = os.path.abspath(root)
        self.pinned_git_dir = None

    def run(self, *args, check=True, raw=False):
        env = gitsafe.safe_env()
        env["GIT_OPTIONAL_LOCKS"] = "0"  # `status` must not rewrite the index it inspects
        env["GIT_TERMINAL_PROMPT"] = "0"
        env["LC_ALL"] = "C"
        argv = gitsafe.hardened(args, self.root, self.pinned_git_dir)
        result = procs.run(argv, cwd=self.root, env=env, timeout=120,
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
        """The absolute git directory - resolved once, then pinned for every later call."""
        if self.pinned_git_dir is None:
            self.pinned_git_dir = self.run("rev-parse", "--absolute-git-dir").strip()
        return self.pinned_git_dir

    def common_dir(self):
        """The repository's common git directory: the git directory itself, or for a linked
        worktree the main one, which holds the config every worktree runs under."""
        found = self.run("rev-parse", "--git-common-dir").strip()
        return os.path.normpath(os.path.join(self.git_dir(), found))

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


def _walk(root, relative_to, keep, skip=_SKIP_DIRS):
    """{relpath: digest} of every file under `root` (a file or a directory). Directories
    and files named in `skip` are not descended into or fingerprinted below the root."""
    digests = {}
    if os.path.isdir(root) and not os.path.islink(root):
        for directory, dirs, files in os.walk(root):
            dirs[:] = sorted(d for d in dirs if d not in skip)
            for name in sorted(f for f in files if f not in skip):
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


def _identity(info):
    """What changes when anything writes to, chmods, replaces or renames onto a file.
    ctime is the part a writer cannot put back - but a file with several hard links shares
    its inode, and so its ctime, with every other link: in node_modules that is pnpm's
    machine-wide store, which another project's install touches without writing a byte.
    Such a file is judged by inode, size and mtime."""
    shared = stat.S_ISREG(info.st_mode) and info.st_nlink > 1
    return (f"{stat.S_IFMT(info.st_mode):o}:{stat.S_IMODE(info.st_mode):o}:{info.st_ino}:"
            f"{info.st_size}:{info.st_mtime_ns}:{'shared' if shared else info.st_ctime_ns}")


def _stat_walk(root, relative_to):
    """{relpath: identity} of every non-directory under `root`, without reading any file
    or following any symlink. Cheap enough for node_modules."""
    found = {}
    try:
        info = os.lstat(root)
    except OSError:
        return found
    if not stat.S_ISDIR(info.st_mode):
        found[os.path.relpath(root, relative_to).replace(os.sep, "/")] = _identity(info)
        return found
    stack = [root]
    while stack:
        directory = stack.pop()
        try:
            entries = list(os.scandir(directory))
        except OSError:
            continue
        for entry in entries:
            try:
                info = entry.stat(follow_symlinks=False)
            except OSError:
                continue
            if stat.S_ISDIR(info.st_mode):
                stack.append(entry.path)
            else:
                rel = os.path.relpath(entry.path, relative_to).replace(os.sep, "/")
                found[rel] = _identity(info)
    return found


def _git_metadata(git_dir, keep):
    """{path relative to the git dir: digest} of GIT_METADATA. Reads files; runs no git."""
    digests = {}
    for rel in GIT_METADATA:
        digests.update(_walk(os.path.join(git_dir, *rel.split("/")), git_dir, keep,
                             skip=_GIT_SKIP))
    return digests


def _config(git, path, branch, kept=None):
    """The config file at `path`, split into the entries the guard owns and the rest:
    {"owned": ((key, value), ...), "others": {key: [values]}}, or None when there is no file.
    Read with `git config --file`, which parses one file and runs nothing. A file git cannot
    parse is owned whole (by digest) and its others are unknown (None)."""
    digest, content = _digest_file(path)
    if digest is None:
        return None
    if kept is not None and content is not None:
        kept[("config", "config")] = content
    result = git.run("config", "--file", path, "--null", "--list", check=False, raw=True)
    if not result.ok:
        return {"owned": (("(unreadable)", digest),), "others": None}
    owned, others = [], {}
    for entry in result.stdout.split("\0"):
        if not entry:
            continue
        key, newline, value = entry.partition("\n")
        value = value if newline else None
        if _owned_config_key(key, branch):
            owned.append((key, value))
        else:
            others.setdefault(key, []).append(value)
    return {"owned": tuple(owned), "others": others}


class Snapshot:
    def __init__(self):
        self.head = None
        self.branch = None
        self.refs = {}
        self.status = ""
        self.files = {}         # checkout files git sees: tracked + untracked-not-ignored
        self.explicit = {}      # EXPLICIT_PATHS, by path
        self.ignored = set()    # top-level ignored entries, collapsed
        self.ignored_content = None  # relpath -> lstat identity inside them; None: not taken
        self.gitmeta = {}       # GIT_METADATA, relative to the git directory
        self.config = None      # the repository config, split by _config
        self.config_path = None
        self.factory = {}       # absolute path -> digest, for guarded Factory paths
        self.kept = {}          # ("explicit"|"gitmeta"|"factory", key) -> (bytes, mode)
        self.git_dir = None

    @property
    def checked_paths(self):
        return (len(set(self.files) | set(self.explicit)) + len(self.gitmeta)
                + len(self.factory) + len(self.ignored_content or {}))


def take(git, guarded_paths=(), fingerprint_ignored=True):
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
    if fingerprint_ignored:
        snap.ignored_content = {}
        for entry in sorted(snap.ignored):
            snap.ignored_content.update(_stat_walk(os.path.join(root, entry), root))

    keep = {}
    snap.gitmeta = _git_metadata(snap.git_dir, keep)
    snap.kept.update({("gitmeta", k): v for k, v in keep.items()})
    snap.config_path = os.path.join(git.common_dir(), "config")
    snap.config = _config(git, snap.config_path, snap.branch, snap.kept)

    _fingerprint_guarded(snap, guarded_paths)
    return snap


def _fingerprint_guarded(snap, guarded_paths):
    for guarded in guarded_paths:
        keep = {}
        base = os.path.dirname(guarded)
        for rel, digest in _walk(guarded, base, keep).items():
            snap.factory[os.path.join(base, rel)] = digest
        snap.kept.update({("factory", os.path.join(base, k)): v for k, v in keep.items()})


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
    branches = {before.branch, after.branch} - {None}
    for ref in sorted(set(before.refs) | set(after.refs)):
        if before.refs.get(ref) != after.refs.get(ref) and _owned_ref(ref, branches):
            violations.append({"path": ref, "change": "ref-changed", "scope": "checkout",
                               "sensitive": True})
    if (before.config or {}).get("owned") != (after.config or {}).get("owned"):
        violations.append({"path": ".git/config", "change": "git-metadata",
                           "scope": "checkout", "sensitive": True})
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
    for path in sorted(before.ignored - after.ignored):
        violations.append({"path": path, "change": "deleted", "scope": "checkout",
                           "sensitive": is_sensitive(path)})
    if before.ignored_content is not None and after.ignored_content is not None:
        # Inside entries that were ignored before and after; new and vanished entries are
        # reported whole, above.
        kept = before.ignored & after.ignored
        inside = [change for change in _compare(before.ignored_content, after.ignored_content,
                                                "checkout", lambda _: True)
                  if any(change["path"] == entry or change["path"].startswith(entry + "/")
                         for entry in kept)]
        violations.extend(inside)
    for change in _compare(before.gitmeta, after.gitmeta, "checkout", lambda _: True):
        change["path"] = ".git/" + change["path"]
        change["change"] = "git-metadata"
        violations.append(change)
    violations.extend(_compare(before.factory, after.factory, "factory", lambda _: True))
    return violations


def outside(before, after):
    """What changed during the agent's run outside the guarded set: other branches' refs,
    tags, the stash, other branches' config. Notes for the record, never violations - other
    worktrees of the repository change these legitimately, and restore never touches them."""
    notes = []
    branches = {before.branch, after.branch} - {None}
    for ref in sorted(set(before.refs) | set(after.refs)):
        old, new = before.refs.get(ref), after.refs.get(ref)
        if old != new and not _owned_ref(ref, branches):
            change = "added" if old is None else "deleted" if new is None else "moved"
            notes.append({"path": ref, "change": change})
    old = (before.config or {}).get("others") or {}
    new = (after.config or {}).get("others") or {}
    for key in sorted(set(old) | set(new)):
        if old.get(key) != new.get(key):
            notes.append({"path": f".git/config:{key}", "change": "config-changed"})
    return notes


def _restore_config(git, before):
    """Put back the config entries the guard owns, keeping what other worktrees changed in
    the rest meanwhile: the old bytes are written back, then every entry outside the
    guarded set that differs is set again as it is now."""
    path = before.config_path
    if path is None:
        return []
    current = _config(git, path, before.branch)
    if (current or {}).get("owned") == (before.config or {}).get("owned"):
        return []
    if before.config is None:
        _remove(path)
    elif ("config", "config") in before.kept:
        _write_back(path, before.kept[("config", "config")])
    else:
        return [f"{path}: too large to have been kept, cannot restore"]
    if current is None or current.get("others") is None:
        return []  # nothing readable to carry over
    was = (before.config or {}).get("others") or {}
    now = current["others"]
    for key in sorted(set(was) | set(now)):
        if was.get(key) == now.get(key):
            continue
        git.run("config", "--file", path, "--unset-all", key, check=False)
        for value in now.get(key, []):
            git.run("config", "--file", path, "--add", key,
                    "true" if value is None else value)
    return []


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
    """Undo whatever the reviewer did. Returns (restored, problems).

    Git's own metadata is put back first, from memory and without running git, so that
    nothing below runs under configuration the reviewer wrote; then the config's guarded
    entries, through `git config --file`, which runs nothing. Refs and config outside the
    guarded set are never written (see `outside`). Content changed inside a
    pre-existing ignored entry cannot be put back (its bytes were never kept): files added
    there are removed, anything else is reported and the review BLOCKS."""
    problems = []
    fingerprint_ignored = before.ignored_content is not None
    try:
        if before.git_dir:
            problems += _restore_files(before.gitmeta, _git_metadata(before.git_dir, {}),
                                       "gitmeta", before.git_dir, before.kept)
        problems += _restore_config(git, before)
        after = take(git, guarded_paths, fingerprint_ignored)
        if after.branch != before.branch:
            if before.branch:
                git.run("symbolic-ref", "HEAD", before.branch)
            else:
                git.run("update-ref", "--no-deref", "HEAD", before.head)
        # Only per-worktree refs: the checked-out branch is put back by `reset --hard` below,
        # and every other ref is someone else's - never deleted, never rewound.
        for ref in sorted(set(before.refs) | set(after.refs)):
            old, new = before.refs.get(ref), after.refs.get(ref)
            if old == new or not _owned_ref(ref, ()):
                continue
            if old is None:
                git.run("update-ref", "-d", ref)
            else:
                git.run("update-ref", ref, old)
        git.run("reset", "--hard", "-q", before.head)
        git.run("clean", "-f", "-d", "-q")
        for path in sorted(after.ignored - before.ignored):
            _remove(os.path.join(git.root, path))
        after = take(git, guarded_paths, fingerprint_ignored)
        if fingerprint_ignored:
            for path in sorted(set(after.ignored_content) - set(before.ignored_content)):
                _remove(os.path.join(git.root, *path.split("/")))
        problems += _restore_files(before.explicit, after.explicit, "explicit", git.root,
                                   before.kept)
        problems += _restore_files(before.gitmeta, after.gitmeta, "gitmeta", before.git_dir,
                                   before.kept)
        problems += _restore_files(before.factory, after.factory, "factory", "/", before.kept)
        remaining = diff(before, take(git, guarded_paths, fingerprint_ignored))
        problems += [f"{v['path']}: still {v['change']} after restore" for v in remaining]
    except (GitError, OSError) as exc:
        problems.append(str(exc))
    return not problems, problems


# -- guarded Factory paths alone ------------------------------------------------------------


def guarded_paths(config=None):
    """Absolute guarded paths: `factory.review.guarded_paths` from `config` (the factory
    section as steps receive it), else DEFAULT_GUARDED_PATHS. Relative entries resolve
    against the Factory root - and the project root too when that is another directory
    (paths.both_roots) - never the cwd. Raises ValueError on a malformed list."""
    listed = ((config or {}).get("review") or {}).get("guarded_paths")
    if listed is None:
        listed = list(DEFAULT_GUARDED_PATHS)
    if not isinstance(listed, list) or not all(isinstance(p, str) for p in listed):
        raise ValueError("factory.review.guarded_paths must be a list of paths")
    return [path for p in listed for path in paths.both_roots(p)]


def take_guarded(guarded):
    """A Snapshot of the guarded paths only. `diff` compares two of them like full ones:
    every checkout field is empty on both sides, so only `factory` changes are reported."""
    snap = Snapshot()
    _fingerprint_guarded(snap, guarded)
    return snap


def restore_guarded(before, guarded):
    """Put the guarded paths back as `before` has them. Returns (restored, problems)."""
    try:
        after = take_guarded(guarded)
        problems = _restore_files(before.factory, after.factory, "factory", "/", before.kept)
        problems += [f"{v['path']}: still {v['change']} after restore"
                     for v in diff(before, take_guarded(guarded))]
    except OSError as exc:
        problems = [str(exc)]
    return not problems, problems

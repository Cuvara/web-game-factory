"""The game repository checkout: processes run in it, git, and its game.config.yaml.

Every outside process the module starts goes through a `Runner`, so tests replace one object
and run offline. Git is used for exactly three things - where development started, whether
this visit already committed, and the commit itself. Nothing here pushes, fetches or talks
to a remote: publishing a branch is the game repository's CI, behind its own gates.

The checkout's `.git` is writable by the developer agent, and git executes what its config
names. Every git command here is therefore hardened (wgflib.gitsafe): the git directory is
resolved once - before the developer runs, when the step pins it - and every later command
names it and the work tree explicitly, so a `core.worktree` or a replaced `.git` gitfile
cannot aim the Factory's commit elsewhere; fsmonitor, hooks, signing and every filter
driver are neutralised; and the environment carries no GIT_* variable that redirects git.
A repository that commits through its own filters (git-lfs) sets
`factory.develop.git.allow_filters: true`; the filter configuration is then recorded when
the directory is pinned, and any change to it afterwards is refused, never run.
"""

import os

from wgflib import gitsafe, procs
from wgflib import template_contract as contract
from wgflib.yamllite import YamlError, load_file

__all__ = ["Runner", "RunResult", "GitRepo", "GitError", "ExactEnv", "read_game_config",
           "ENGINES", "KEY_TRAILER"]

# 2D -> PixiJS, 3D -> Three.js. The template bundles exactly these two renderers: the
# template contract's list (the tech-plan schema's engine.type enum), not a copy of it.
ENGINES = contract.ENGINES

# The commit trailer a development commit is keyed by. Finding it on a commit is how a
# re-executed visit knows it already committed, instead of committing again.
KEY_TRAILER = "Wgf-Develop-Key"

_OUTPUT_TAIL = 6000
_ADD_CHUNK = 100  # pathspecs per `git add`, well under any argv limit


class ExactEnv(dict):
    """An environment that replaces the Factory's for one process, instead of extending it:
    git without the variables that redirect it, an agent without the Factory's tokens."""


class RunResult:
    __slots__ = ("argv", "returncode", "output", "timed_out", "duration_s", "idle_timed_out",
                 "cancelled", "killed")

    def __init__(self, argv, returncode, output, timed_out=False, duration_s=0.0,
                 idle_timed_out=False, cancelled=False, killed=()):
        self.argv = list(argv)
        self.returncode = returncode
        self.output = output or ""
        self.timed_out = timed_out
        self.duration_s = duration_s
        self.idle_timed_out = idle_timed_out  # no output for `idle_timeout` seconds
        self.cancelled = cancelled            # the run was cancelled while this ran
        self.killed = list(killed)            # descendants left behind, and terminated

    @property
    def ok(self):
        return (self.returncode == 0 and not self.timed_out and not self.idle_timed_out
                and not self.cancelled)

    def tail(self, limit=_OUTPUT_TAIL):
        return self.output[-limit:]


class Runner:
    """Runs a process to completion, capturing combined output. Never raises for exit codes.

    The process and everything it starts are owned (wgflib.procs): whatever it leaves
    running - a dev server, a watcher - is terminated when it exits, times out, goes quiet
    for `idle_timeout` seconds, or the step is cancelled.

    `env` extends the Factory's environment, unless it is an `ExactEnv`, which replaces it.
    """

    def run(self, argv, cwd, timeout=None, env=None, idle_timeout=None, log_path=None):
        if isinstance(env, ExactEnv):
            merged = dict(env)
        else:
            merged = dict(os.environ)
            merged.update(env or {})
        merged.setdefault("CI", "1")  # no watch modes, no interactive prompts
        done = procs.run(argv, cwd=cwd, env=merged, timeout=timeout, idle_timeout=idle_timeout,
                         log_path=log_path, stderr_to_stdout=True)
        if done.error is not None:
            return RunResult(argv, 127, f"{done.exception or done.error}",
                             duration_s=done.duration_s)
        interrupted = done.timed_out or done.idle_timed_out or done.cancelled
        return RunResult(argv, None if interrupted else done.returncode, done.stdout,
                         timed_out=done.timed_out, duration_s=done.duration_s,
                         idle_timed_out=done.idle_timed_out, cancelled=done.cancelled,
                         killed=done.killed)


class GitError(RuntimeError):
    pass


def _filter_lines(output):
    return sorted(line for line in (output or "").splitlines()
                  if line.lower().startswith("filter."))


class GitRepo:
    def __init__(self, root, runner, author=None, trailer=KEY_TRAILER, allow_filters=False):
        self.root = root
        self.runner = runner
        self.author = author or {}
        # The trailer this repository's keyed commits carry. develop's by default; the sdk
        # step keys its integration commits with its own (wgf_sdk/commit.py).
        self.trailer = trailer
        self.allow_filters = bool(allow_filters)
        self.git_dir = None         # resolved once by pin(), then named on every command
        self._filters = None        # allow_filters: the filter config as it was when pinned

    # -- hardened invocation -------------------------------------------------------------

    def _run(self, argv):
        env = gitsafe.safe_env()
        env["GIT_TERMINAL_PROMPT"] = "0"
        env["GIT_OPTIONAL_LOCKS"] = "0"  # `status` must not rewrite the index it inspects
        return self.runner.run(argv, cwd=self.root, timeout=120, env=ExactEnv(env))

    def pin(self):
        """Resolve the git directory, once. Called before the developer runs, so what every
        later command names is what the Factory found - not what the developer left in a
        gitfile or `core.worktree`. None when the checkout is not a repository."""
        if self.git_dir is None:
            argv = ["git"]
            for override in gitsafe.BASE_OVERRIDES:
                argv += ["-c", override]
            argv += [f"--work-tree={os.path.abspath(self.root)}", "rev-parse",
                     "--absolute-git-dir"]
            result = self._run(argv)
            lines = result.output.strip().splitlines() if result.ok else []
            if lines and os.path.isabs(lines[-1].strip()):
                self.git_dir = lines[-1].strip()
                if self.allow_filters:
                    self._filters = self._read_filters()
        return self.git_dir

    def _read_filters(self):
        result = self._run(gitsafe.filter_config_argv(os.path.abspath(self.root),
                                                      self.git_dir))
        return _filter_lines(result.output)

    def _argv(self, args):
        root = os.path.abspath(self.root)
        if self.git_dir is None:
            # Not a repository (yet): nothing to pin, and no config of its own to run.
            return gitsafe.hardened(args, root, None, drivers=())
        listing = self._read_filters()
        if self.allow_filters:
            if listing != self._filters:
                raise GitError(
                    "the checkout's filter configuration changed after the Factory pinned it "
                    f"(was {self._filters or 'none'}, now {listing or 'none'}); with "
                    "factory.develop.git.allow_filters the Factory runs only the filters that "
                    "were configured before the developer. Nothing was run.")
            return gitsafe.hardened(args, root, self.git_dir, keep_filters=True)
        return gitsafe.hardened(args, root, self.git_dir,
                                drivers=gitsafe.parse_filter_drivers("\n".join(listing)))

    def _git(self, *args, check=True):
        self.pin()
        result = self._run(self._argv(args))
        if check and not result.ok:
            raise GitError(f"git {' '.join(args)} failed: {result.tail(800).strip()}")
        return result

    # -- inspection ----------------------------------------------------------------------

    def is_repository(self):
        if not os.path.isdir(self.root):
            return False
        result = self._git("rev-parse", "--is-inside-work-tree", check=False)
        return result.ok and result.output.strip() == "true"

    def head(self):
        result = self._git("rev-parse", "HEAD", check=False)
        return result.output.strip() if result.ok else None

    def branch(self):
        result = self._git("rev-parse", "--abbrev-ref", "HEAD", check=False)
        return result.output.strip() if result.ok else None

    def has_commit(self, sha):
        return bool(sha) and self._git("cat-file", "-e", f"{sha}^{{commit}}", check=False).ok

    def dirty_paths(self, *pathspec):
        args = ["status", "--porcelain", "--untracked-files=all"]
        if pathspec:
            args += ["--", *pathspec]
        output = self._git(*args).output
        return [line[3:] for line in output.splitlines() if line.strip()]

    def changes(self):
        """[(xy, path)] for every uncommitted change, untracked files included, from
        `status -z`: no path is quoted or split, and a rename or copy yields both paths."""
        output = self._git("status", "--porcelain=v1", "-z", "--untracked-files=all").output
        entries = output.split("\0")
        found, index = [], 0
        while index < len(entries):
            entry = entries[index]
            index += 1
            if len(entry) < 4 or entry[2] != " ":
                continue
            xy, path = entry[:2], entry[3:]
            found.append((xy, path))
            if ("R" in xy or "C" in xy) and index < len(entries):
                found.append((xy, entries[index]))
                index += 1
        return found

    def file_at(self, base, path):
        """The text of `path` in commit `base`, or None when it is not there."""
        if not self.has_commit(base) or not self._git(
                "cat-file", "-e", f"{base}:{path}", check=False).ok:
            return None
        result = self._git("show", "--no-textconv", f"{base}:{path}", check=False)
        return result.output if result.ok else None

    def changed_since(self, base, *pathspec):
        """Paths under `pathspec` that differ from `base`: committed, staged or untracked."""
        changed = set()
        if self.has_commit(base):
            diff = self._git("diff", "--no-ext-diff", "--no-textconv", "--name-only", base,
                             "--", *pathspec, check=False)
            changed.update(line for line in diff.output.splitlines() if line.strip())
        changed.update(self.dirty_paths(*pathspec))
        return sorted(changed)

    def keyed_commit(self, key, depth=200):
        """The newest commit on this branch carrying `key` in its trailer, or None."""
        result = self._git("log", f"-n{depth}", "--format=%H%x00%B%x1e", check=False)
        if not result.ok:
            return None
        needle = f"{self.trailer}: {key}"
        for record in result.output.split("\x1e"):
            sha, _, body = record.strip().partition("\x00")
            if sha and any(line.strip() == needle for line in body.splitlines()):
                return sha
        return None

    # -- the commit ----------------------------------------------------------------------

    def _commit(self, subject, body, key):
        # --allow-empty: when the tree already matches HEAD the commit still carries the
        # key, which is what makes this visit findable by a later execution.
        message = f"{subject}\n\n{body.strip()}\n\n{self.trailer}: {key}\n"
        identity = []
        if self.author.get("name"):
            identity += ["-c", f"user.name={self.author['name']}"]
        if self.author.get("email"):
            identity += ["-c", f"user.email={self.author['email']}"]
        self._git(*identity, "commit", "--allow-empty", "--no-verify", "-m", message)
        return self.head(), True

    def commit_all(self, subject, body, key):
        """Stage everything and commit once, keyed. Returns (sha, created).

        The sdk step's commit (wgf_sdk/commit.py), which refuses any change outside the
        files it owns before calling this. The develop step commits with commit_paths."""
        existing = self.keyed_commit(key)
        if existing:
            return existing, False
        self._git("add", "--all")
        return self._commit(subject, body, key)

    def commit_paths(self, subject, body, key, paths):
        """Commit exactly `paths` once, keyed. Returns (sha, created).

        Refuses (GitError, nothing staged or committed) when the tree holds a change that
        is not in `paths`: what the caller did not decide to commit is never folded into
        the commit, and never silently left behind either."""
        existing = self.keyed_commit(key)
        if existing:
            return existing, False
        wanted = set(paths)
        stray = sorted({path for _, path in self.changes()} - wanted)
        if stray:
            raise GitError(f"refusing to commit: {len(stray)} change(s) outside the paths "
                           f"to commit ({', '.join(stray[:8])})")
        ordered = sorted(wanted)
        for start in range(0, len(ordered), _ADD_CHUNK):
            self._git("--literal-pathspecs", "add", "--all", "--",
                      *ordered[start:start + _ADD_CHUNK])
        return self._commit(subject, body, key)


def read_game_config(root):
    """game.config.yaml from the checkout, or raise ValueError saying what is wrong."""
    path = os.path.join(root, contract.GAME_CONFIG)
    if not os.path.exists(path):
        raise ValueError(f"{path} does not exist; the checkout is not a scaffolded game")
    try:
        document = load_file(path) or {}
    except YamlError as exc:
        raise ValueError(f"{contract.GAME_CONFIG} does not parse: {exc}")
    engine = (document.get("engine") or {}).get("type")
    if engine not in ENGINES:
        raise ValueError(
            f"game.config.yaml engine.type is {engine!r}; the template supports only "
            f"{' and '.join(ENGINES)} (2D -> pixijs, 3D -> threejs)"
        )
    return document

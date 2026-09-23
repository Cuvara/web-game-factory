"""The game repository checkout: processes run in it, git, and its game.config.yaml.

Every outside process the module starts goes through a `Runner`, so tests replace one object
and run offline. Git is used for exactly three things - where development started, whether
this visit already committed, and the commit itself. Nothing here pushes, fetches or talks
to a remote: publishing a branch is the game repository's CI, behind its own gates.
"""

import os
import subprocess

from wgflib.yamllite import YamlError, load_file

__all__ = ["Runner", "RunResult", "GitRepo", "GitError", "read_game_config", "ENGINES",
           "KEY_TRAILER"]

# 2D -> PixiJS, 3D -> Three.js. The template bundles exactly these two renderers.
ENGINES = ("pixijs", "threejs")

# The commit trailer a development commit is keyed by. Finding it on a commit is how a
# re-executed visit knows it already committed, instead of committing again.
KEY_TRAILER = "Wgf-Develop-Key"

_OUTPUT_TAIL = 6000


class RunResult:
    __slots__ = ("argv", "returncode", "output", "timed_out", "duration_s")

    def __init__(self, argv, returncode, output, timed_out=False, duration_s=0.0):
        self.argv = list(argv)
        self.returncode = returncode
        self.output = output or ""
        self.timed_out = timed_out
        self.duration_s = duration_s

    @property
    def ok(self):
        return self.returncode == 0 and not self.timed_out

    def tail(self, limit=_OUTPUT_TAIL):
        return self.output[-limit:]


class Runner:
    """Runs a process to completion, capturing combined output. Never raises for exit codes."""

    def run(self, argv, cwd, timeout=None, env=None):
        import time

        started = time.monotonic()
        merged = dict(os.environ)
        merged.update(env or {})
        merged.setdefault("CI", "1")  # no watch modes, no interactive prompts
        try:
            completed = subprocess.run(
                argv, cwd=cwd, env=merged, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL, timeout=timeout, check=False,
            )
        except subprocess.TimeoutExpired as exc:
            output = exc.output.decode("utf-8", "replace") if exc.output else ""
            return RunResult(argv, None, output, timed_out=True,
                             duration_s=time.monotonic() - started)
        except FileNotFoundError as exc:
            return RunResult(argv, 127, f"{exc}", duration_s=time.monotonic() - started)
        return RunResult(argv, completed.returncode,
                         completed.stdout.decode("utf-8", "replace"),
                         duration_s=time.monotonic() - started)


class GitError(RuntimeError):
    pass


class GitRepo:
    def __init__(self, root, runner, author=None):
        self.root = root
        self.runner = runner
        self.author = author or {}

    def _git(self, *args, check=True):
        result = self.runner.run(["git", *args], cwd=self.root, timeout=120)
        if check and not result.ok:
            raise GitError(f"git {' '.join(args)} failed: {result.tail(800).strip()}")
        return result

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

    def changed_since(self, base, *pathspec):
        """Paths under `pathspec` that differ from `base`: committed, staged or untracked."""
        changed = set()
        if self.has_commit(base):
            diff = self._git("diff", "--name-only", base, "--", *pathspec, check=False)
            changed.update(line for line in diff.output.splitlines() if line.strip())
        changed.update(self.dirty_paths(*pathspec))
        return sorted(changed)

    def keyed_commit(self, key, depth=200):
        """The newest commit on this branch carrying `key` in its trailer, or None."""
        result = self._git("log", f"-n{depth}", "--format=%H%x00%B%x1e", check=False)
        if not result.ok:
            return None
        needle = f"{KEY_TRAILER}: {key}"
        for record in result.output.split("\x1e"):
            sha, _, body = record.strip().partition("\x00")
            if sha and any(line.strip() == needle for line in body.splitlines()):
                return sha
        return None

    def commit_all(self, subject, body, key):
        """Stage everything and commit once, keyed. Returns (sha, created)."""
        existing = self.keyed_commit(key)
        if existing:
            return existing, False
        self._git("add", "--all")
        # --allow-empty: when the tree already matches HEAD the commit still carries the
        # key, which is what makes this visit findable by a later execution.
        message = f"{subject}\n\n{body.strip()}\n\n{KEY_TRAILER}: {key}\n"
        identity = []
        if self.author.get("name"):
            identity += ["-c", f"user.name={self.author['name']}"]
        if self.author.get("email"):
            identity += ["-c", f"user.email={self.author['email']}"]
        self._git(*identity, "commit", "--allow-empty", "--no-verify", "-m", message)
        return self.head(), True


def read_game_config(root):
    """game.config.yaml from the checkout, or raise ValueError saying what is wrong."""
    path = os.path.join(root, "game.config.yaml")
    if not os.path.exists(path):
        raise ValueError(f"{path} does not exist; the checkout is not a scaffolded game")
    try:
        document = load_file(path) or {}
    except YamlError as exc:
        raise ValueError(f"game.config.yaml does not parse: {exc}")
    engine = (document.get("engine") or {}).get("type")
    if engine not in ENGINES:
        raise ValueError(
            f"game.config.yaml engine.type is {engine!r}; the template supports only "
            f"{' and '.join(ENGINES)} (2D -> pixijs, 3D -> threejs)"
        )
    return document

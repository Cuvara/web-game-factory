"""The two outside systems init touches, behind interfaces the step is written against.

`GitHub` is the remote: look a repository up, generate one from the template, wait for the
template's contents to land, clone it. `Git` is the local clone: which remote it belongs to
and whether it has any commits. The real implementations shell out to the `gh` and `git`
CLIs, so they use whatever authentication the operator already configured; tests replace
both with fakes, because a test that creates a repository is not a test.

Every call either returns data or raises `ToolError`. `ToolError.retryable` separates a
flaky network from a refusal that will recur.

Every child process goes through `wgflib.procs.run`, so a `gh` or `git` that hangs or leaves
a helper behind is terminated with its whole tree when the step's timeout or cancellation
says so.

`Git` also covers what init does inside the local project: the keyed commit that writes
game.config.yaml, and - for `factory.init.source: local` - making the project from a local
template checkout with no network at all.
"""

import json
import os
import re
import shutil
import tarfile
import tempfile
import time

from wgflib import procs

__all__ = ["Repository", "ToolError", "GitHub", "Git", "GhCli", "GitCli", "run_command",
           "KEY_TRAILER", "PLAN_TRAILER", "TEMPLATE_TRAILER"]

# Commit trailers init writes, and looks for on re-execution.
KEY_TRAILER = "Wgf-Init-Key"
PLAN_TRAILER = "Wgf-Tech-Plan"
TEMPLATE_TRAILER = "Wgf-Template"


class ToolError(RuntimeError):
    def __init__(self, message, retryable=True):
        super().__init__(message)
        self.retryable = retryable


class Repository:
    """What init needs to know about a remote repository."""

    def __init__(self, owner, name, url=None, description="", visibility=None,
                 default_branch=None, template=None):
        self.owner = owner
        self.name = name
        self.url = url
        self.description = description or ""
        self.visibility = visibility
        self.default_branch = default_branch
        self.template = template  # "owner/name" it was generated from, or None

    @property
    def full_name(self):
        return f"{self.owner}/{self.name}"


class GitHub:
    """Interface. `full_name` arguments are always `owner/name`."""

    def view(self, full_name):
        """The repository, or None when it does not exist."""
        raise NotImplementedError

    def head_sha(self, full_name):
        """The commit at the tip of the repository's default branch."""
        raise NotImplementedError

    def create_from_template(self, full_name, template, visibility, description):
        """Generate a repository from `template`. Returns the new Repository."""
        raise NotImplementedError

    def has_file(self, full_name, path):
        raise NotImplementedError

    def clone(self, full_name, destination):
        raise NotImplementedError

    def wait_for_file(self, full_name, path, timeout, interval=2.0, sleep=time.sleep):
        """Generation from a template is asynchronous: the repository exists before its
        contents do. Poll until `path` is there, or give up after `timeout` seconds."""
        waited = 0.0
        while True:
            if self.has_file(full_name, path):
                return True
            if waited >= timeout:
                return False
            sleep(interval)
            waited += interval


class Git:
    """Interface over a local working copy."""

    def origin(self, directory):
        """`owner/name` of the `origin` remote, or None when `directory` is not a clone."""
        raise NotImplementedError

    def has_commits(self, directory):
        raise NotImplementedError

    def pull(self, directory, branch):
        raise NotImplementedError

    # -- the scaffolding commit ---------------------------------------------------------

    def head(self, directory):
        """The commit HEAD points at, or None."""
        raise NotImplementedError

    def changed(self, directory, paths):
        """Whether any of `paths` differs from HEAD (modified, added, deleted or untracked)."""
        raise NotImplementedError

    def commit(self, directory, paths, message, author=None):
        """Stage exactly `paths` (additions, changes and deletions) and commit them.
        Returns the new commit. `author` is {"name", "email"} or None for git's own."""
        raise NotImplementedError

    def find_commit(self, directory, trailers):
        """The newest commit reachable from HEAD whose message carries every
        `{trailer: value}` given, or None."""
        raise NotImplementedError

    # -- the local source ---------------------------------------------------------------

    def resolve(self, directory, ref):
        """The full commit id `ref` names in the repository at `directory`."""
        raise NotImplementedError

    def get_config(self, directory, key):
        raise NotImplementedError

    def create_from_local(self, template, commit, destination, message, config, author=None):
        """Make `destination` a new, independent repository holding the template's tree at
        `commit` as its single initial commit - what GitHub's "use this template" produces -
        with the local `git config` values given. Atomic: nothing appears at `destination`
        unless it all worked."""
        raise NotImplementedError


def run_command(argv, cwd=None, timeout=300):
    """Run a command and return its stdout; raise ToolError on failure. No shell. The child
    runs as an owned process tree (wgflib.procs): a timeout takes its descendants too."""
    # Short poll: init runs dozens of quick git commands, and procs polls for exit.
    result = procs.run(argv, cwd=cwd, timeout=timeout, poll_seconds=0.02)
    if result.error is not None:
        if "FileNotFoundError" in result.error:
            raise ToolError(f"{argv[0]} is not installed or not on PATH", retryable=False)
        raise ToolError(f"{' '.join(argv[:3])} could not start: {result.error}")
    if result.timed_out:
        raise ToolError(f"{' '.join(argv[:3])} timed out after {timeout}s")
    if result.cancelled:
        raise ToolError(f"{' '.join(argv[:3])} was cancelled")
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise ToolError(f"{' '.join(argv[:3])} failed: {detail}")
    return result.stdout


def parse_remote(url):
    """`owner/name` from an https or ssh GitHub remote URL, else None."""
    url = (url or "").strip()
    for prefix in ("git@github.com:", "ssh://git@github.com/", "https://github.com/",
                   "http://github.com/"):
        if url.startswith(prefix):
            path = url[len(prefix):]
            if path.endswith(".git"):
                path = path[:-4]
            parts = path.strip("/").split("/")
            if len(parts) == 2 and all(parts):
                return "/".join(parts)
    return None


_NOT_FOUND = ("Could not resolve to a Repository", "HTTP 404", "Not Found")
_VIEW_FIELDS = "name,owner,url,description,visibility,defaultBranchRef,templateRepository"


class GhCli(GitHub):
    def __init__(self, run=run_command):
        self._run = run

    def view(self, full_name):
        try:
            out = self._run(["gh", "repo", "view", full_name, "--json", _VIEW_FIELDS])
        except ToolError as exc:
            if any(marker in str(exc) for marker in _NOT_FOUND):
                return None
            raise
        data = json.loads(out)
        template = data.get("templateRepository") or None
        if template:
            template = (template.get("nameWithOwner")
                        or f"{template['owner']['login']}/{template['name']}")
        return Repository(
            owner=data["owner"]["login"],
            name=data["name"],
            url=data.get("url"),
            description=data.get("description") or "",
            visibility=(data.get("visibility") or "").lower() or None,
            default_branch=(data.get("defaultBranchRef") or {}).get("name") or None,
            template=template,
        )

    def head_sha(self, full_name):
        out = self._run(["gh", "api", f"repos/{full_name}/commits/HEAD", "--jq", ".sha"])
        return out.strip()

    def create_from_template(self, full_name, template, visibility, description):
        try:
            self._run(["gh", "repo", "create", full_name, "--template", template,
                       f"--{visibility}", "--description", description])
        except ToolError as exc:
            # Something we could not see (no read access) holds the name. Retrying cannot
            # free it, and the step must never take over a repository it cannot inspect.
            if "already exists" in str(exc) or "Name already exists" in str(exc):
                raise ToolError(str(exc), retryable=False)
            raise
        created = self.view(full_name)
        if created is None:
            raise ToolError(f"gh reported {full_name} created, but it cannot be found")
        return created

    def has_file(self, full_name, path):
        try:
            self._run(["gh", "api", f"repos/{full_name}/contents/{path}", "--silent"])
        except ToolError as exc:
            if any(marker in str(exc) for marker in _NOT_FOUND):
                return False
            raise
        return True

    def clone(self, full_name, destination):
        self._run(["gh", "repo", "clone", full_name, destination])


class GitCli(Git):
    def __init__(self, run=run_command):
        self._run = run

    def origin(self, directory):
        if not os.path.isdir(os.path.join(directory, ".git")):
            return None
        try:
            url = self._run(["git", "-C", directory, "remote", "get-url", "origin"])
        except ToolError:
            return None
        return parse_remote(url)

    def has_commits(self, directory):
        try:
            self._run(["git", "-C", directory, "rev-parse", "--verify", "--quiet", "HEAD"])
        except ToolError:
            return False
        return True

    def pull(self, directory, branch):
        self._run(["git", "-C", directory, "pull", "--ff-only", "origin", branch])

    def _git(self, directory, *args):
        return self._run(["git", "-C", directory, *args])

    @staticmethod
    def _identity(author):
        identity = []
        if author and author.get("name"):
            identity += ["-c", f"user.name={author['name']}"]
        if author and author.get("email"):
            identity += ["-c", f"user.email={author['email']}"]
        return identity

    def head(self, directory):
        try:
            return self._git(directory, "rev-parse", "--verify", "--quiet", "HEAD").strip() or None
        except ToolError:
            return None

    def changed(self, directory, paths):
        out = self._git(directory, "status", "--porcelain", "--untracked-files=all", "--",
                        *paths)
        return bool(out.strip())

    def commit(self, directory, paths, message, author=None):
        self._git(directory, "add", "--all", "--", *paths)
        self._run(["git", *self._identity(author), "-C", directory, "commit", "--no-verify",
                   "--quiet", "-m", message, "--", *paths])
        return self.head(directory)

    def find_commit(self, directory, trailers):
        if not self.head(directory):
            return None
        out = self._git(directory, "log", "--format=%H%x00%B%x1e", "HEAD")
        for record in out.split("\x1e"):
            sha, _, body = record.strip("\n").partition("\x00")
            if not sha:
                continue
            found = dict(re.findall(r"^([A-Za-z-]+): (.+?)\s*$", body, re.M))
            if all(found.get(key) == value for key, value in trailers.items()):
                return sha.strip()
        return None

    def resolve(self, directory, ref):
        try:
            return self._git(directory, "rev-parse", "--verify", "--quiet",
                             f"{ref}^{{commit}}").strip()
        except ToolError as exc:
            raise ToolError(f"{directory} has no commit {ref!r}: {exc}", retryable=False)

    def get_config(self, directory, key):
        try:
            return self._git(directory, "config", "--local", "--get", key).strip() or None
        except ToolError:
            return None

    def create_from_local(self, template, commit, destination, message, config, author=None):
        parent = os.path.dirname(os.path.abspath(destination))
        os.makedirs(parent, exist_ok=True)
        staging = tempfile.mkdtemp(prefix=f".{os.path.basename(destination)}.wgf-", dir=parent)
        try:
            archive = os.path.join(staging, "template.tar")
            # git archive, not clone: the project shares no objects, remotes or history
            # with the template, exactly like a repository GitHub generates from one.
            self._git(template, "archive", "--format=tar", "-o", archive, commit)
            tree = os.path.join(staging, "tree")
            os.makedirs(tree)
            with tarfile.open(archive) as handle:
                if hasattr(tarfile, "data_filter"):
                    handle.extractall(tree, filter="data")
                else:  # pragma: no cover - Python < 3.12 without the backport
                    handle.extractall(tree)
            os.remove(archive)
            self._run(["git", "init", "--quiet", "-b", "main", tree])
            for key, value in config.items():
                self._git(tree, "config", "--local", key, value)
            self._git(tree, "add", "--all")
            self._run(["git", *self._identity(author), "-C", tree, "commit", "--no-verify",
                       "--quiet", "-m", message])
            os.rename(tree, destination)
        finally:
            shutil.rmtree(staging, ignore_errors=True)
        return self.head(destination)

"""The two outside systems init touches, behind interfaces the step is written against.

`GitHub` is the remote: look a repository up, generate one from the template, wait for the
template's contents to land, clone it. `Git` is the local clone: which remote it belongs to
and whether it has any commits. The real implementations shell out to the `gh` and `git`
CLIs, so they use whatever authentication the operator already configured; tests replace
both with fakes, because a test that creates a repository is not a test.

Every call either returns data or raises `ToolError`. `ToolError.retryable` separates a
flaky network from a refusal that will recur.
"""

import json
import os
import subprocess
import time

__all__ = ["Repository", "ToolError", "GitHub", "Git", "GhCli", "GitCli", "run_command"]


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


def run_command(argv, cwd=None, timeout=300):
    """Run a command and return its stdout; raise ToolError on failure. No shell."""
    try:
        completed = subprocess.run(argv, cwd=cwd, capture_output=True, text=True,
                                   timeout=timeout, check=False)
    except FileNotFoundError:
        raise ToolError(f"{argv[0]} is not installed or not on PATH", retryable=False)
    except subprocess.TimeoutExpired:
        raise ToolError(f"{' '.join(argv[:3])} timed out after {timeout}s")
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise ToolError(f"{' '.join(argv[:3])} failed: {detail}")
    return completed.stdout


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

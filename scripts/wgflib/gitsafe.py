"""git, run by the Factory in a checkout an agent has written to, without running the agent's
code or following its redirections.

A game checkout is written by a developer agent and inspected after a reviewer agent. Both
can write `.git/config`, and git executes what config names: `core.fsmonitor` runs on every
`git status`, a `filter.<driver>.clean`/`process` runs on every status of a stat-dirty file
and on `reset --hard`, hooks run on commit, and `core.worktree` points every command -
`reset --hard` and `clean -fd` included - at another directory. An agent that is sandboxed
to the checkout would otherwise get the Factory, unsandboxed, to run a command or to clean
someone else's directory for it.

`hardened(args, root, git_dir)` is the argv to run instead of `["git", *args]`:

  * `--git-dir`/`--work-tree` pinned to what the Factory resolved itself, which overrides
    `core.worktree`, a replaced `.git` gitfile and GIT_DIR in the environment;
  * `core.fsmonitor=false`, `core.hooksPath=<devnull>`, auto gc and maintenance off,
    every transport refused;
  * every filter driver the repository's config defines replaced with `cat` and made
    optional - found with `git config --get-regexp`, which reads config and runs nothing.

It is for inspection and restoration (status, ls-files, rev-parse, for-each-ref,
update-ref, reset, clean). A step that has to run the repository's own filters on purpose
(git-lfs) must not use it. Standard library only.
"""

import os

from . import procs

__all__ = ["BASE_OVERRIDES", "hardened", "filter_drivers", "safe_env"]

BASE_OVERRIDES = (
    "core.fsmonitor=false",
    f"core.hooksPath={os.devnull}",
    "core.untrackedCache=false",
    "gc.auto=0",
    "maintenance.auto=false",
    "protocol.allow=never",
    "submodule.recurse=false",
)

# Environment that redirects git or injects config, never inherited by a hardened call.
_UNSAFE_ENV = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY",
               "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_CONFIG", "GIT_CONFIG_PARAMETERS",
               "GIT_CONFIG_COUNT", "GIT_CEILING_DIRECTORIES", "GIT_NAMESPACE",
               "GIT_EXTERNAL_DIFF", "GIT_SSH", "GIT_SSH_COMMAND", "GIT_ASKPASS",
               "GIT_EXEC_PATH", "GIT_TEMPLATE_DIR", "GIT_COMMON_DIR")


def safe_env(env=None):
    """A copy of `env` (default os.environ) without variables that redirect git."""
    base = dict(os.environ if env is None else env)
    for name in list(base):
        if name in _UNSAFE_ENV or name.startswith("GIT_CONFIG_KEY_") \
                or name.startswith("GIT_CONFIG_VALUE_"):
            base.pop(name, None)
    return base


def _pinned(root, git_dir):
    pinned = []
    if git_dir:
        pinned.append(f"--git-dir={git_dir}")
    if root:
        pinned.append(f"--work-tree={root}")
    return pinned


def filter_drivers(root, git_dir=None, git="git", timeout=60):
    """Names of the filter drivers the repository's config defines. Reads config only."""
    argv = [git, *_pinned(root, git_dir), "config", "--get-regexp", r"^filter\."]
    done = procs.run(argv, cwd=root, env=safe_env(), timeout=timeout,
                     heartbeat_seconds=None, grace_seconds=1.0, poll_seconds=0.01)
    names = set()
    for line in (done.stdout or "").splitlines():
        key = line.split(" ", 1)[0]
        if key.lower().startswith("filter.") and key.count(".") >= 2:
            names.add(key[len("filter."):].rsplit(".", 1)[0])
    return sorted(names)


def hardened(args, root, git_dir=None, git="git", drivers=None):
    """argv for `git <args>` in `root` that cannot run repository-defined commands."""
    overrides = list(BASE_OVERRIDES)
    if drivers is None:
        drivers = filter_drivers(root, git_dir, git)
    for name in drivers:
        overrides += [f"filter.{name}.clean=cat", f"filter.{name}.smudge=cat",
                      f"filter.{name}.process=", f"filter.{name}.required=false"]
    argv = [git]
    for override in overrides:
        argv += ["-c", override]
    return argv + _pinned(root, git_dir) + list(args)

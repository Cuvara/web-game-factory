"""Running commands in the game repository, as process trees the release step owns.

Everything the release step executes - git, the game's own `release:package` and
`release:manifest` scripts - goes through `wgflib.procs.run`, so a packaging script that
starts helpers is cleaned up whole, reports liveness to the step, and is cancelled with it.
Tests replace the runner, or put a fake package manager first on PATH.
"""

from wgflib import procs

__all__ = ["ReleaseRunner", "describe"]


class ReleaseRunner:
    """`run(argv, cwd, timeout) -> procs.ProcessResult`, tied to the executing step."""

    def __init__(self, env=None, hooks=None):
        self.env = env
        self.hooks = dict(hooks or {})
        self.calls = []

    def run(self, argv, cwd, timeout=None):
        self.calls.append(list(argv))
        return procs.run(list(argv), cwd=cwd, timeout=timeout, env=self.env, **self.hooks)


def describe(result):
    display = " ".join(result.argv)
    if result.error:
        return f"`{display}` could not be started: {result.error}"
    if result.timed_out or result.idle_timed_out:
        return f"`{display}` timed out after {result.duration_s:.0f}s"
    if result.cancelled:
        return f"`{display}` was cancelled"
    return f"`{display}` exited {result.returncode}"

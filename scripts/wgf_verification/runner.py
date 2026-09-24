"""Running commands in the game repository.

Everything the verification executes goes through a CommandRunner, so tests replace it with
a scripted fake and never touch a package manager, a browser or the network.
"""

import os
import shlex
import time
from dataclasses import dataclass, field

from wgflib import procs

__all__ = ["CommandResult", "CommandRunner"]


@dataclass
class CommandResult:
    command: list
    exit_code: int = None
    stdout: str = ""
    stderr: str = ""
    duration_s: float = 0.0
    timed_out: bool = False
    # Set when the command could not be started at all (the tool is not installed).
    error: str = None
    # Ended because it wrote nothing for `idle_timeout` seconds, or the run was cancelled.
    idle_timed_out: bool = False
    cancelled: bool = False
    # Descendants the command left running when it ended (a dev server), terminated.
    killed: list = field(default_factory=list)

    @property
    def display(self):
        return " ".join(shlex.quote(part) for part in self.command)

    @property
    def ok(self):
        return (self.error is None and not self.timed_out and not self.idle_timed_out
                and not self.cancelled and self.exit_code == 0)

    @property
    def unavailable(self):
        """The command never ran. Verification is blocked, the game is not at fault."""
        return self.error is not None

    def describe(self):
        if self.error:
            return f"`{self.display}` could not be started: {self.error}"
        if self.timed_out:
            return f"`{self.display}` timed out after {self.duration_s:.0f}s"
        if self.idle_timed_out:
            return f"`{self.display}` produced no output for too long and was stopped"
        if self.cancelled:
            return f"`{self.display}` was stopped: the run was cancelled"
        return f"`{self.display}` exited {self.exit_code}"


class CommandRunner:
    """Runs a command to completion with a timeout. Never raises for a failing command.

    The command's whole process tree is owned (wgflib.procs): a Playwright `webServer` or a
    `vite` the command started is terminated with it - on exit, timeout or cancellation.
    """

    def __init__(self, env=None, clock=time.monotonic, idle_timeout=None, log_path=None):
        self.env = env
        self.clock = clock
        self.idle_timeout = idle_timeout
        self.log_path = log_path

    def run(self, command, cwd, timeout=None, env=None):
        merged = dict(os.environ if self.env is None else self.env)
        merged.update(env or {})
        # CI=1 makes the template's Playwright config refuse `.only` and never reuse a stray
        # dev server, which is the behaviour a verification wants.
        merged.setdefault("CI", "1")
        began = self.clock()
        done = procs.run(list(command), cwd=cwd, env=merged, timeout=timeout,
                         idle_timeout=self.idle_timeout, log_path=self.log_path)
        took = self.clock() - began
        if done.error is not None:
            exc = done.exception
            if isinstance(exc, FileNotFoundError):
                return CommandResult(list(command), error=f"not found ({exc.filename})",
                                     duration_s=took)
            return CommandResult(list(command), error=str(exc or done.error), duration_s=took)
        interrupted = done.timed_out or done.idle_timed_out or done.cancelled
        return CommandResult(list(command), exit_code=None if interrupted else done.returncode,
                             stdout=_text(done.stdout), stderr=_text(done.stderr),
                             duration_s=took, timed_out=done.timed_out,
                             idle_timed_out=done.idle_timed_out, cancelled=done.cancelled,
                             killed=list(done.killed))


def _text(value):
    if value is None:
        return ""
    return value.decode("utf-8", "replace") if isinstance(value, bytes) else value

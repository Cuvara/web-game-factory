"""Running commands in the game repository.

Everything the verification executes goes through a CommandRunner, so tests replace it with
a scripted fake and never touch a package manager, a browser or the network.
"""

import os
import shlex
import subprocess
import time
from dataclasses import dataclass

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

    @property
    def display(self):
        return " ".join(shlex.quote(part) for part in self.command)

    @property
    def ok(self):
        return self.error is None and not self.timed_out and self.exit_code == 0

    @property
    def unavailable(self):
        """The command never ran. Verification is blocked, the game is not at fault."""
        return self.error is not None

    def describe(self):
        if self.error:
            return f"`{self.display}` could not be started: {self.error}"
        if self.timed_out:
            return f"`{self.display}` timed out after {self.duration_s:.0f}s"
        return f"`{self.display}` exited {self.exit_code}"


class CommandRunner:
    """Runs a command to completion with a timeout. Never raises for a failing command."""

    def __init__(self, env=None, clock=time.monotonic):
        self.env = env
        self.clock = clock

    def run(self, command, cwd, timeout=None, env=None):
        merged = dict(os.environ if self.env is None else self.env)
        merged.update(env or {})
        # CI=1 makes the template's Playwright config refuse `.only` and never reuse a stray
        # dev server, which is the behaviour a verification wants.
        merged.setdefault("CI", "1")
        began = self.clock()
        try:
            completed = subprocess.run(
                list(command), cwd=cwd, env=merged, capture_output=True, text=True,
                timeout=timeout, check=False,
            )
        except FileNotFoundError as exc:
            return CommandResult(list(command), error=f"not found ({exc.filename})",
                                 duration_s=self.clock() - began)
        except subprocess.TimeoutExpired as exc:
            return CommandResult(list(command), timed_out=True,
                                 stdout=_text(exc.stdout), stderr=_text(exc.stderr),
                                 duration_s=self.clock() - began)
        except OSError as exc:
            return CommandResult(list(command), error=str(exc), duration_s=self.clock() - began)
        return CommandResult(list(command), exit_code=completed.returncode,
                             stdout=completed.stdout, stderr=completed.stderr,
                             duration_s=self.clock() - began)


def _text(value):
    if value is None:
        return ""
    return value.decode("utf-8", "replace") if isinstance(value, bytes) else value

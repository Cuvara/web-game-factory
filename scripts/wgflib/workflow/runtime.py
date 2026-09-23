"""The execution boundary between the engine and whatever actually does a step's work.

    Step  ->  Task  ->  AgentRuntime

The engine builds a Task (which step, which inputs, which attempt) and hands it to a
runtime. `LocalRuntime` calls the step in-process, which is all that exists today. A
runtime that delegates to an agent host, queues work for a human, or dispatches to a remote
worker implements the same `run(task)` and returns the same StepResult; the engine cannot
tell them apart, and must not be able to.

Runtimes are selected by name from `factory.agents.default` in the factory config. No
runtime in this module names or depends on a particular AI provider, and none should: a
provider-specific runtime belongs in the module that registers it.
"""

import traceback

from .model import StepOutcome, StepResult

__all__ = ["Task", "AgentRuntime", "LocalRuntime", "RUNTIMES", "create_runtime"]


class Task:
    __slots__ = ("step", "inputs", "context")

    def __init__(self, step, inputs, context):
        self.step = step
        self.inputs = inputs
        self.context = context


class AgentRuntime:
    name = None

    def run(self, task):  # pragma: no cover - interface
        """Execute `task` and return a StepResult. Must not raise for a step's own failure."""
        raise NotImplementedError


class LocalRuntime(AgentRuntime):
    """Runs the step in this process. An exception is a retryable failure, not a crash."""

    name = "local"

    def run(self, task):
        try:
            result = task.step.execute(task.inputs, task.context)
        except Exception as exc:
            return StepResult(
                StepOutcome.FAILED,
                error=f"{type(exc).__name__}: {exc}",
                data={"traceback": traceback.format_exc(limit=5)},
            )
        if not isinstance(result, StepResult):
            return StepResult(
                StepOutcome.FAILED,
                error=f"step returned {type(result).__name__}, not a StepResult",
                retryable=False,
            )
        return result


RUNTIMES = {"local": LocalRuntime}


def create_runtime(name):
    factory = RUNTIMES.get(name or "local")
    if factory is None:
        raise LookupError(
            f"no agent runtime {name!r}; registered: {', '.join(sorted(RUNTIMES))}"
        )
    return factory()

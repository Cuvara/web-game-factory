"""The executable workflow kernel.

    CLI (scripts/wgf.py)
      -> api.WorkflowAPI          assembles an engine from config
      -> engine.WorkflowEngine    walks a definition, executes, persists, routes
      -> definition               core/workflows/<id>.workflow.yaml, as data
      -> step.StepRegistry        step type -> implementation
      -> runtime.AgentRuntime     where a step's work actually happens
      -> store.RunStore           .factory/workflows/<run-id>/

The kernel knows Workflow, WorkflowStep, WorkflowContext, artifacts in and out, StepResult
and run state. It does not know what research, design or verification are; `mock.py` is
the only module here that pretends to, and only so the whole workflow can run before the
real modules exist. See docs/workflow-engine.md.
"""

from .definition import DefinitionError, RetryPolicy, WorkflowDefinition, load_definition
from .engine import EngineError, WorkflowEngine
from .events import EventBus, Events
from .model import (
    ArtifactOutput,
    ArtifactRef,
    RunState,
    RunStatus,
    StepOutcome,
    StepResult,
    StepState,
    StepStatus,
)
from .step import RegistryError, StepInputs, StepRegistry, WorkflowStep
from .store import RunLocked, RunStore, StoreError

__all__ = [
    "ArtifactOutput",
    "ArtifactRef",
    "DefinitionError",
    "EngineError",
    "EventBus",
    "Events",
    "RegistryError",
    "RetryPolicy",
    "RunLocked",
    "RunState",
    "RunStatus",
    "RunStore",
    "StepInputs",
    "StepOutcome",
    "StepRegistry",
    "StepResult",
    "StepState",
    "StepStatus",
    "StoreError",
    "WorkflowDefinition",
    "WorkflowEngine",
    "WorkflowStep",
    "load_definition",
]

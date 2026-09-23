"""The step contract, and the registry that maps a step *type* to an implementation.

A step is anything with an `execute(inputs, context) -> StepResult` method. It receives the
artifacts the definition says it consumes, and returns the artifacts it produced plus an
outcome. It never calls another step, never reads the run state directly, never decides
what runs next; the engine does all three from the workflow definition.

    class ResearchStep(WorkflowStep):
        type = "research"

        def execute(self, inputs, context):
            ...
            return StepResult.success([ArtifactOutput("opportunity", payload)])

Real implementations register themselves by type, from a module listed under
`factory.steps.modules` in workspace/config/factory.yaml:

    def register(registry):
        registry.register("research", ResearchStep)

Registering the same type twice replaces the earlier implementation, which is how a real
module supersedes a mock without either knowing about the other.
"""

import importlib

__all__ = ["WorkflowStep", "StepInputs", "StepRegistry", "RegistryError"]


class RegistryError(LookupError):
    """No implementation for a step type, or a step module that failed to register."""


class WorkflowStep:
    """Base class for a step implementation. Subclasses set `type` and implement `execute`.

    Instances are constructed once per execution with the step's definition, so a step may
    keep per-execution state on `self` without it leaking into the next attempt.
    """

    type = None

    def __init__(self, definition):
        self.definition = definition

    @property
    def id(self):
        return self.definition.id

    @property
    def params(self):
        """The step's `with:` block from the workflow definition."""
        return self.definition.params

    def execute(self, inputs, context):  # pragma: no cover - interface
        raise NotImplementedError


class StepInputs:
    """The artifacts a step declared as `inputs`, resolved against the run.

    `refs[type]` is the newest ArtifactRef of that type, or absent. `load(type)` reads the
    content. `missing` lists the declared types the run does not hold yet - whether that is
    fatal is the step's call, because a step run on its own (`wgf verify`) may legitimately
    have nothing upstream of it.
    """

    def __init__(self, refs, loader, missing):
        self.refs = dict(refs)
        self.missing = list(missing)
        self._loader = loader

    def __contains__(self, artifact_type):
        return artifact_type in self.refs

    def load(self, artifact_type):
        ref = self.refs.get(artifact_type)
        return None if ref is None else self._loader(ref)


class StepRegistry:
    def __init__(self):
        self._types = {}

    def register(self, step_type, factory):
        """`factory(definition)` must return an object with `execute(inputs, context)`."""
        self._types[step_type] = factory
        return factory

    def has(self, step_type):
        return step_type in self._types

    def types(self):
        return sorted(self._types)

    def create(self, definition):
        factory = self._types.get(definition.type)
        if factory is None:
            raise RegistryError(
                f"no implementation registered for step type {definition.type!r} "
                f"(step {definition.id!r}). Registered: {', '.join(self.types()) or 'none'}"
            )
        return factory(definition)

    def missing_for(self, definition, step_ids=None):
        """Step types in `definition` (restricted to `step_ids`) with no implementation."""
        wanted = [s for s in definition.steps if step_ids is None or s.id in step_ids]
        return sorted({s.type for s in wanted if not self.has(s.type)})

    def load_modules(self, module_names):
        """Import each module and call its `register(registry)`."""
        for name in module_names or []:
            try:
                module = importlib.import_module(name)
            except ImportError as exc:
                raise RegistryError(f"step module {name!r} could not be imported: {exc}")
            register = getattr(module, "register", None)
            if not callable(register):
                raise RegistryError(f"step module {name!r} has no register(registry)")
            register(self)
        return self

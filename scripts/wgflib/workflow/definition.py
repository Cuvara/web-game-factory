"""Workflow definitions as data: core/workflows/<id>.workflow.yaml.

A definition names steps, says which step type implements each, and says where each result
goes next. It is the only place the order of work is written down; the engine walks it and
the CLI slices it, and neither of them contains a sequence of its own.

    workflow:
      id: new-game
      version: 1
      start: research                 # default: the first step
      defaults:
        retry: {max_attempts: 3, backoff: exponential, delay_seconds: 2}
        max_visits: 5
      groups:
        plan: [strategy, strategy-review, design]
      steps:
        - id: verify
          type: verify
          stage: release:qa           # optional; the lifecycle state this step serves
          inputs: [prototype-report]
          outputs: [qa-report]
          retry: {max_attempts: 1}
          on:
            fail: develop             # a route label the step returned
            blocked: $end             # or an outcome, lower-cased
          next: release               # where success goes; default is the next step listed
        - id: develop
          max_visits_by_route:        # optional: entries through one route, bounded apart
            fail: 2                   # from the others (and from max_visits, which holds too)

Routing, in order: the step's `route` label if it returned one and the definition maps it;
else the outcome (`success`, `failed`, `blocked`, `waiting_for_input`, `waiting_for_human`)
if the definition maps that; else the default for the outcome - success goes to `next`,
failure fails the run, blocked blocks it, waiting parks it. An unmapped route therefore
falls back to its outcome's default rather than being guessed at, which is what makes a
verification step that returns FAILED/"fail" safe even in a definition that forgot to route
it.

Targets are step ids, `$end` (the run completes) or `$fail` (the run fails).

`max_visits_by_route` keys are the routes that can enter the step: a label (or outcome)
some step's `on:` maps to it, or `success` when some step's success goes to it. Each value
is a whole number >= 1. A step entered through such a route more often than that since the
run last started or resumed blocks the run, whatever its overall `max_visits` still allows,
so one loop into a step cannot spend the visits another loop into it needs.

Nothing here executes anything.
"""

import os
import re

from .. import paths
from ..yamllite import load_file

__all__ = [
    "WorkflowDefinition",
    "StepDefinition",
    "RetryPolicy",
    "DefinitionError",
    "load_definition",
    "find_definition",
    "list_definitions",
    "END",
    "FAIL",
    "WORKFLOWS",
    "STEP_TYPE",
]

WORKFLOWS = os.path.join(paths.CORE, "workflows")

END = "$end"
FAIL = "$fail"
SPECIAL_TARGETS = (END, FAIL)

_ID = re.compile(r"^[a-z][a-z0-9-]*$")
# Step types may be namespaced by the module that implements them: `research`,
# `discovery.research`, `test.external`. A type is only ever a registry key - it is never
# imported, evaluated or resolved to a path.
STEP_TYPE = re.compile(r"^[a-z][a-z0-9-]*(\.[a-z][a-z0-9-]*)*$")
_STAGE = re.compile(r"^([a-z][a-z0-9-]*):([a-z][a-z0-9-]*)$")
BACKOFFS = ("none", "fixed", "exponential")


class DefinitionError(ValueError):
    """The workflow file does not describe a runnable workflow. Lists every problem found."""

    def __init__(self, source, problems):
        self.source = source
        self.problems = list(problems)
        super().__init__(
            f"{source}: {len(self.problems)} problem(s):\n  - " + "\n  - ".join(self.problems)
        )


class RetryPolicy:
    """How many times a FAILED step is attempted, and how long to wait between attempts."""

    __slots__ = ("max_attempts", "backoff", "delay_seconds", "max_delay_seconds")

    def __init__(self, max_attempts=1, backoff="none", delay_seconds=0.0, max_delay_seconds=60.0):
        self.max_attempts = max_attempts
        self.backoff = backoff
        self.delay_seconds = delay_seconds
        self.max_delay_seconds = max_delay_seconds

    def delay_before(self, attempt):
        """Seconds to wait before attempt number `attempt` (2 is the first retry)."""
        if attempt <= 1 or self.backoff == "none":
            return 0.0
        if self.backoff == "fixed":
            delay = self.delay_seconds
        else:
            delay = self.delay_seconds * (2 ** (attempt - 2))
        return float(min(delay, self.max_delay_seconds))

    def merged(self, override):
        """A copy with the keys present in `override` replaced."""
        merged = RetryPolicy(self.max_attempts, self.backoff, self.delay_seconds,
                             self.max_delay_seconds)
        for key in self.__slots__:
            if isinstance(override, dict) and key in override:
                setattr(merged, key, override[key])
        return merged

    def to_dict(self):
        return {key: getattr(self, key) for key in self.__slots__}


def _as_list(value):
    return list(value) if isinstance(value, list) else []


def _hashable_str(value):
    return value if isinstance(value, str) else None


class StepDefinition:
    __slots__ = ("id", "type", "stage", "inputs", "outputs", "retry", "on", "next",
                 "max_visits", "max_visits_by_route", "params", "description")

    def __init__(self, entry, retry, max_visits):
        self.id = entry.get("id")
        self.type = entry.get("type")
        self.stage = entry.get("stage")
        # Malformed shapes are reported by parse_definition; here they only must not raise.
        self.inputs = _as_list(entry.get("inputs"))
        self.outputs = _as_list(entry.get("outputs"))
        self.retry = retry
        self.on = dict(entry.get("on")) if isinstance(entry.get("on"), dict) else {}
        self.next = entry.get("next")
        self.max_visits = max_visits
        by_route = entry.get("max_visits_by_route")
        self.max_visits_by_route = dict(by_route) if isinstance(by_route, dict) else {}
        self.params = dict(entry.get("with")) if isinstance(entry.get("with"), dict) else {}
        self.description = entry.get("description")

    def __repr__(self):
        return f"<StepDefinition {self.id} ({self.type})>"


class WorkflowDefinition:
    def __init__(self, data, source):
        self.source = source
        self.id = data.get("id")
        self.version = data.get("version")
        self.description = data.get("description")
        self.untyped_artifacts = list(data.get("untyped_artifacts") or [])
        self.steps = []
        self.groups = {}
        self.start = None

    @property
    def step_ids(self):
        return [step.id for step in self.steps]

    def step(self, step_id):
        for step in self.steps:
            if step.id == step_id:
                return step
        raise KeyError(f"workflow {self.id} has no step {step_id!r}")

    def has_step(self, step_id):
        return any(step.id == step_id for step in self.steps)

    def following(self, step_id):
        """The step listed after `step_id`, or END."""
        ids = self.step_ids
        index = ids.index(step_id)
        return ids[index + 1] if index + 1 < len(ids) else END

    def success_target(self, step):
        return step.next or self.following(step.id)

    def resolve_scope(self, name):
        """The ordered step ids a command named `name` covers.

        The workflow's own id is every step; a group id is its members; a step id is itself.
        """
        if name in (None, self.id):
            return self.step_ids
        if name in self.groups:
            return list(self.groups[name])
        if self.has_step(name):
            return [name]
        known = sorted(set(self.groups) | set(self.step_ids))
        raise KeyError(
            f"workflow {self.id} has no step or group {name!r}. Known: {', '.join(known)}"
        )

    def commands(self):
        """Every name `resolve_scope` accepts, workflow first, then groups, then steps."""
        return [self.id] + list(self.groups) + self.step_ids

    def __repr__(self):
        return f"<WorkflowDefinition {self.id} v{self.version}>"


def _check_retry(where, retry, problems):
    if retry is None:
        return
    if not isinstance(retry, dict):
        problems.append(f"{where}: retry must be a mapping")
        return
    unknown = set(retry) - set(RetryPolicy.__slots__)
    if unknown:
        problems.append(f"{where}: unknown retry key(s) {', '.join(sorted(unknown))}")
    attempts = retry.get("max_attempts")
    if attempts is not None and (not isinstance(attempts, int) or attempts < 1):
        problems.append(f"{where}: retry.max_attempts must be an integer >= 1")
    if retry.get("backoff") not in (None,) + BACKOFFS:
        problems.append(f"{where}: retry.backoff must be one of {', '.join(BACKOFFS)}")
    for key in ("delay_seconds", "max_delay_seconds"):
        value = retry.get(key)
        if value is not None and (not isinstance(value, (int, float)) or value < 0):
            problems.append(f"{where}: retry.{key} must be a number >= 0")


def parse_definition(document, source="<memory>", base_retry=None, base_max_visits=5):
    """Build a WorkflowDefinition from parsed YAML, or raise DefinitionError."""
    problems = []
    data = document.get("workflow") if isinstance(document, dict) else None
    if not isinstance(data, dict):
        raise DefinitionError(source, ["top level must be a mapping with a `workflow:` key"])

    definition = WorkflowDefinition(data, source)
    if not isinstance(definition.id, str) or not _ID.fullmatch(definition.id):
        problems.append(f"workflow.id {definition.id!r} must be kebab-case")
    if definition.version is None:
        problems.append("workflow.version is required")

    defaults = data.get("defaults") or {}
    if not isinstance(defaults, dict):
        problems.append("workflow.defaults must be a mapping")
        defaults = {}
    _check_retry("defaults", defaults.get("retry"), problems)
    retry_default = (base_retry or RetryPolicy()).merged(defaults.get("retry"))
    visits_default = defaults.get("max_visits", base_max_visits)

    entries = data.get("steps")
    if not isinstance(entries, list) or not entries:
        problems.append("workflow.steps must be a non-empty list")
        entries = []

    seen = set()
    for index, entry in enumerate(entries):
        where = f"steps[{index}]"
        if not isinstance(entry, dict):
            problems.append(f"{where}: must be a mapping")
            continue
        step_id = entry.get("id")
        where = f"step {step_id!r}"
        if not isinstance(step_id, str) or not _ID.fullmatch(step_id):
            problems.append(f"{where}: id must be kebab-case")
        elif step_id in seen:
            problems.append(f"{where}: duplicate id")
        if isinstance(step_id, str):
            seen.add(step_id)
        step_type = entry.get("type")
        if not isinstance(step_type, str) or not STEP_TYPE.fullmatch(step_type):
            problems.append(f"{where}: type must be a kebab-case step type, optionally "
                            f"dot-namespaced (module.step)")
        stage = entry.get("stage")
        if stage is not None and not (isinstance(stage, str) and _STAGE.fullmatch(stage)):
            problems.append(f"{where}: stage must be qualified, <machine>:<state>")
        for key in ("inputs", "outputs"):
            value = entry.get(key)
            if value is not None and not (
                isinstance(value, list)
                and all(isinstance(v, str) and _ID.fullmatch(v) for v in value)
            ):
                problems.append(f"{where}: {key} must be a list of artifact ids")
        _check_retry(where, entry.get("retry"), problems)
        if entry.get("on") is not None and not isinstance(entry.get("on"), dict):
            problems.append(f"{where}: on must be a mapping of route -> target")
        if entry.get("with") is not None and not isinstance(entry.get("with"), dict):
            problems.append(f"{where}: with must be a mapping")
        max_visits = entry.get("max_visits", visits_default)
        if isinstance(max_visits, bool) or not isinstance(max_visits, int) or max_visits < 1:
            problems.append(f"{where}: max_visits must be an integer >= 1")
        by_route = entry.get("max_visits_by_route")
        if by_route is not None and not isinstance(by_route, dict):
            problems.append(f"{where}: max_visits_by_route must be a mapping of route -> "
                            f"integer >= 1")
        for route, limit in (by_route.items() if isinstance(by_route, dict) else ()):
            if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
                problems.append(f"{where}: max_visits_by_route.{route} must be an integer "
                                f">= 1")
        definition.steps.append(
            StepDefinition(entry, retry_default.merged(entry.get("retry")), max_visits)
        )

    targets_ok = set(seen) | set(SPECIAL_TARGETS)
    for step in definition.steps:
        for route, target in list(step.on.items()) + ([("next", step.next)] if step.next else []):
            if not isinstance(route, str) or not _ID.fullmatch(route.replace("_", "-")):
                problems.append(f"step {step.id!r}: route {route!r} is not a valid label")
            if not isinstance(target, str) or target not in targets_ok:
                problems.append(
                    f"step {step.id!r}: {route} -> {target!r} is not a step id, {END} or {FAIL}"
                )

    # A route limit names a way into the step: a label some step's `on:` maps to it, or
    # `success` when some step's success goes there. Anything else could never be counted,
    # which is a typo, not a limit.
    for step in definition.steps:
        if not step.max_visits_by_route:
            continue
        entering = set()
        for other in definition.steps:
            entering |= {route for route, target in other.on.items() if target == step.id}
            if isinstance(other.id, str) and "success" not in other.on and (
                    other.next or (definition.following(other.id)
                                   if other.id in definition.step_ids else None)) == step.id:
                entering.add("success")
        for route in step.max_visits_by_route:
            if route not in entering:
                problems.append(
                    f"step {step.id!r}: max_visits_by_route names {route!r}, which is no "
                    f"route into it (routes into it: "
                    f"{', '.join(sorted(map(str, entering))) or 'none'})")

    groups = data.get("groups") or {}
    if not isinstance(groups, dict):
        problems.append("workflow.groups must be a mapping of name -> [step ids]")
        groups = {}
    for name, members in groups.items():
        if not _ID.fullmatch(str(name)):
            problems.append(f"group {name!r}: name must be kebab-case")
        if _hashable_str(name) in seen or name == definition.id:
            problems.append(f"group {name!r}: collides with a step or the workflow id")
        if not isinstance(members, list) or not members:
            problems.append(f"group {name!r}: must list at least one step")
            continue
        for member in members:
            if _hashable_str(member) not in seen:
                problems.append(f"group {name!r}: unknown step {member!r}")
        definition.groups[name] = list(members)

    start = data.get("start") or (definition.steps[0].id if definition.steps else None)
    if _hashable_str(start) not in seen:
        problems.append(f"workflow.start {start!r} is not a step id")
    definition.start = start

    if problems:
        raise DefinitionError(source, problems)
    return definition


def find_definition(workflow_id, search=(WORKFLOWS,)):
    """The path of `<workflow_id>.workflow.yaml` in the first search directory holding it."""
    for directory in search:
        path = os.path.join(directory, f"{workflow_id}.workflow.yaml")
        if os.path.exists(path):
            return path
    raise FileNotFoundError(
        f"no workflow {workflow_id!r} in {', '.join(paths.display(d) for d in search)}"
    )


def list_definitions(search=(WORKFLOWS,)):
    found = []
    for directory in search:
        if os.path.isdir(directory):
            found += sorted(
                name[: -len(".workflow.yaml")]
                for name in os.listdir(directory)
                if name.endswith(".workflow.yaml")
            )
    return found


def load_definition(path_or_id, base_retry=None, base_max_visits=5, search=(WORKFLOWS,)):
    """Load by path, or by id from `search`. The file's stem must equal its workflow id."""
    if os.path.sep in path_or_id or path_or_id.endswith(".yaml"):
        path = path_or_id
    else:
        path = find_definition(path_or_id, search)
    definition = parse_definition(
        load_file(path), paths.display(path), base_retry, base_max_visits
    )
    stem = os.path.basename(path)[: -len(".workflow.yaml")]
    if path.endswith(".workflow.yaml") and stem != definition.id:
        raise DefinitionError(
            paths.display(path), [f"workflow.id {definition.id!r} != filename stem {stem!r}"]
        )
    return definition

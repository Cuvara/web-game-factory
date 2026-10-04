"""The quality policy every run inherits: core/reference/quality-policy.yaml, applied.

Pure functions over a run's state, its definition and the policy - no step type, gate or
route is named here, only what the policy file names. The engine calls `floor_problems` and
`production_problems` before a step executes and `config_reasons` when a drive begins; the
API calls `snapshot` when a run starts and `report` for `wgf status`.

    snapshot      what a new run records in its params (`quality`): the tier, the class, why,
                  and the policy and benchmark versions it started under
    effective     the policy a run is held to: its snapshot's lists joined with the current
                  file's (a newer policy only ever adds), or the current file alone for a
                  run started before there was a snapshot
    run_class     `release` or `development`, from the snapshot and every QUALITY_DOWNGRADED
                  event the run recorded (a configuration only lowers it)
    floor_problems
                  the required steps before a step that are not current (rule 1)
    report        the class, why, and whether the run is release-ready, for status
"""

import os

from .. import paths
from ..yamllite import load_file
from .definition import WORKFLOWS
from .events import Events
from .model import StepOutcome, StepStatus

__all__ = ["PARAM", "RELEASE", "DEVELOPMENT", "FLOOR", "load_policy", "snapshot",
           "effective", "run_class", "config_reasons", "floor_problems",
           "production_problems", "current", "report", "run_tier", "shipped", "downgrades",
           "preflight_refusals",
           "PolicyError"]

PARAM = "quality"
RELEASE = "release"
DEVELOPMENT = "development"
CLASSES = (RELEASE, DEVELOPMENT)
# state.blocked_reason["kind"] when the floor or the production-only rule stopped a run.
FLOOR = "quality-floor"
POLICY_FILE = os.path.join(paths.REFERENCE, "quality-policy.yaml")

_LISTS = ("enforce_at", "required_steps", "pending", "production_only")


class PolicyError(ValueError):
    """The policy file is missing or malformed. A run is not started without one."""


def load_policy(path=None):
    """The policy as a flat mapping: version, benchmark (version), tier, the four lists, and
    the development_when conditions. Raises PolicyError when it cannot be read."""
    path = path or POLICY_FILE
    try:
        data = load_file(path)
    except Exception as exc:
        raise PolicyError(f"{paths.display(path)} cannot be read: {exc}")
    if not isinstance(data, dict) or not isinstance(data.get("version"), str):
        raise PolicyError(f"{paths.display(path)} has no version")
    floor = data.get("floor") or {}
    tier = data.get("tier") or {}
    policy = {
        "version": data["version"],
        "benchmark": _benchmark_version(data.get("benchmark")),
        "tier": {"config": tier.get("config"), "default": tier.get("default"),
                 "classes": dict(tier.get("classes") or {})},
        "enforce_at": list(floor.get("enforce_at") or []),
        "required_steps": list(floor.get("required_steps") or []),
        "pending": list(floor.get("pending") or []),
        "production_only": list(data.get("production_only") or []),
        "development_when": list(data.get("development_when") or []),
        "production_only_when": list(data.get("production_only_when") or []),
        "preflight": list(data.get("preflight") or []),
        "release_ready_at": data.get("release_ready_at"),
        "shipped_workflows_only": data.get("shipped_workflows_only") is True,
    }
    for key in _LISTS:
        if not all(isinstance(item, str) for item in policy[key]):
            raise PolicyError(f"{paths.display(path)}: {key} must be a list of names")
    if not policy["tier"]["classes"] or policy["tier"]["default"] not in policy["tier"]["classes"]:
        raise PolicyError(f"{paths.display(path)}: tier.default must be one of tier.classes")
    return policy


def _benchmark_version(relative):
    if not relative:
        return None
    try:
        data = load_file(os.path.join(paths.ROOT, relative))
    except Exception:
        return None
    version = data.get("version") if isinstance(data, dict) else None
    name = os.path.basename(relative).split(".")[0]
    return f"{name}@{version}" if version else None


def _lookup(config, dotted):
    node = config
    for part in (dotted or "").split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def config_reasons(policy, config, key="development_when"):
    """The `why` of every condition under `key` that `config` (factory data) meets."""
    reasons = []
    for condition in policy.get(key) or ():
        if not isinstance(condition, dict):
            continue
        value = _lookup(config, condition.get("config"))
        if value is None:
            value = condition.get("default")
        held = False
        if "equals" in condition:
            held = value == condition["equals"] and value is not None
        elif "in" in condition:
            held = value in (condition["in"] or ())
        elif "lacks" in condition:
            held = isinstance(value, list) and any(
                item not in value for item in condition["lacks"] or ())
        elif condition.get("set") is True:
            held = value is not None
        if held:
            reasons.append(condition.get("why") or f"factory.{condition.get('config')}")
    return reasons


def shipped(definition):
    """True when `definition` was read from the Factory's own core/workflows/."""
    source = getattr(definition, "source", None)
    if not source:
        return False
    path = source if os.path.isabs(source) else os.path.join(paths.ROOT, source)
    folder = os.path.normcase(os.path.abspath(WORKFLOWS))
    return os.path.normcase(os.path.dirname(os.path.abspath(path))) == folder


def run_tier(environment, default=None):
    """The quality tier a run was started with (its `quality` param), for a step that budgets
    or judges content: read from the run, never from a configuration changed since. `default`
    when the run has no snapshot."""
    taken = (environment or {}).get(PARAM) if isinstance(environment, dict) else None
    tier = taken.get("tier") if isinstance(taken, dict) else None
    return tier if isinstance(tier, str) else default


def _tier(policy, config, override=None):
    tier = override or _lookup(config, policy["tier"]["config"]) or policy["tier"]["default"]
    if tier not in policy["tier"]["classes"]:
        raise PolicyError(f"factory.{policy['tier']['config']} {tier!r} is not one of "
                          f"{', '.join(policy['tier']['classes'])}")
    return tier


def snapshot(policy, config, definition, mock=False):
    """The `quality` param a new run records: tier, class, reasons, versions, and the lists
    it is held to. `config` is the factory data (FactoryConfig.data)."""
    tier = _tier(policy, config)
    reasons = []
    if mock:
        reasons.append("a mock run: every step is a placeholder that judges nothing")
    if policy["tier"]["classes"][tier] != RELEASE:
        reasons.append(f"quality tier {tier} (factory.{policy['tier']['config']})")
    missing = [s for s in policy["required_steps"]
               if s not in policy["pending"] and not definition.has_step(s)]
    if missing:
        reasons.append(f"workflow {definition.id} lacks required step(s) "
                       f"{', '.join(missing)}")
    if policy.get("shipped_workflows_only") and not shipped(definition):
        reasons.append(f"workflow {definition.id} is read from {definition.source}, not from "
                       f"the Factory's core/workflows/")
    reasons += config_reasons(policy, config)
    taken = {
        "policy": policy["version"],
        "tier": tier,
        "class": DEVELOPMENT if reasons else RELEASE,
    }
    if reasons:
        taken["reasons"] = reasons
    if policy.get("benchmark"):
        taken["benchmark"] = policy["benchmark"]
    for key in _LISTS:
        taken[key] = list(policy[key])
    return taken


def _implemented_by(implementation, step_id, module):
    found = implementation(step_id) if implementation else None
    return isinstance(found, str) and (found == module or found.startswith(module + "."))


def preflight_refusals(policy, config, definition, scope_ids, mock=False,
                       implementation=None):
    """Rule 4: why a new run over `scope_ids` cannot be started under `config` - each
    `preflight` entry whose tier class, step, implementing module and condition hold. []
    for a mock run. `implementation(step_id)` names the module implementing that step in
    the run's registry (None when unknown, which an `implemented_by` entry never matches)."""
    if mock:
        return []
    tier = _tier(policy, config)
    klass = policy["tier"]["classes"][tier]
    refused = []
    for entry in policy.get("preflight") or ():
        if not isinstance(entry, dict):
            continue
        if entry.get("tier_class") not in (None, klass):
            continue
        scope = set(scope_ids or ())
        if entry.get("step") and entry["step"] not in scope:
            continue
        wanted = dict(entry.get("with_steps") or {})
        if entry.get("implemented_by"):
            wanted[entry.get("step")] = entry["implemented_by"]
        if not all(step_id in scope and _implemented_by(implementation, step_id, module)
                   for step_id, module in wanted.items()):
            continue
        refused += config_reasons({"development_when": [entry]}, config)
    return refused


def effective(params, policy):
    """The lists a run is held to: its snapshot's joined with the current policy's. A run
    without a snapshot (started before the policy) is held to the current policy alone.
    None when there is neither."""
    taken = (params or {}).get(PARAM) if isinstance(params, dict) else None
    if not isinstance(taken, dict) and policy is None:
        return None
    merged = {}
    for key in _LISTS:
        values = []
        for source in (taken if isinstance(taken, dict) else {}, policy or {}):
            for item in source.get(key) or ():
                if item not in values:
                    values.append(item)
        merged[key] = values
    # A required step no longer pending in the current policy is enforced, whatever the
    # snapshot said.
    if policy is not None:
        merged["pending"] = [s for s in merged["pending"] if s in policy.get("pending", ())]
    return merged


def downgrades(events):
    """[reason] from every QUALITY_DOWNGRADED event the run recorded."""
    reasons = []
    for event in events or ():
        if event.get("event") == Events.QUALITY_DOWNGRADED:
            for reason in (event.get("data") or {}).get("reasons") or ():
                if reason not in reasons:
                    reasons.append(reason)
    return reasons


def run_class(params, events):
    """(class, reasons): `release` only for a run whose snapshot says so and that never
    recorded a downgrade. A run without a snapshot is `development`."""
    params = params if isinstance(params, dict) else {}
    taken = params.get(PARAM)
    if not isinstance(taken, dict):
        reasons = ["the run has no quality snapshot (started before the quality policy, or "
                   "outside the workflow API)"]
        if params.get("mock"):
            reasons.insert(0, "a mock run: every step is a placeholder that judges nothing")
        return DEVELOPMENT, reasons
    reasons = list(taken.get("reasons") or [])
    for reason in downgrades(events):
        if reason not in reasons:
            reasons.append(reason)
    if taken.get("class") != RELEASE or reasons:
        return DEVELOPMENT, reasons or ["the run was started as development"]
    return RELEASE, []


def _last_success(state):
    last = {}
    for index, entry in enumerate(state.trail):
        if entry.get("outcome") == StepOutcome.SUCCESS:
            last[entry.get("step")] = index
    return last


def current(state, definition, step_id, last=None):
    """None when `step_id` is current in the run - its latest visit succeeded and no step
    before it in the definition has succeeded since - else why it is not."""
    last = _last_success(state) if last is None else last
    step = state.steps.get(step_id)
    if step is None or step_id not in last:
        return f"{step_id} has not passed in this run"
    if step.status != StepStatus.SUCCESS:
        return f"{step_id} is {step.status} on its latest visit"
    ids = definition.step_ids
    newer = [u for u in ids[:ids.index(step_id)] if last.get(u, -1) > last[step_id]]
    if newer:
        return f"{step_id} passed before {', '.join(newer)} ran again"
    return None


def floor_problems(state, definition, step_def, held):
    """Rule 1: why the required steps before `step_def` do not let it execute; [] when they
    do, or when its stage is not one the floor is enforced at. `held` is effective()."""
    if not held or step_def.stage not in held["enforce_at"]:
        return []
    ids = definition.step_ids
    before = ids[:ids.index(step_def.id)]
    last = _last_success(state)
    problems = []
    for step_id in held["required_steps"]:
        if step_id in before:
            why = current(state, definition, step_id, last)
            if why:
                problems.append(why)
    return problems


def production_problems(step_def, held, quality_class, mock, policy=None, config=None):
    """Rule 3: a development run does not execute a production-only step while the policy's
    production_only_when conditions hold of `config` (always, when it lists none)."""
    if mock or not held or step_def.stage not in held["production_only"]:
        return []
    if quality_class == RELEASE:
        return []
    when = (policy or {}).get("production_only_when") or []
    if when and not config_reasons(policy, config or {}, "production_only_when"):
        return []
    return [f"{step_def.id} ({step_def.stage}) runs only in a release-class run, and this "
            f"run is development"]


def report(state, definition, events, policy=None):
    """What `wgf status` says of the run's quality: tier, class, why, versions, and whether
    it is release-ready - a release-class run whose step at the policy's `release_ready_at`
    stage passed, is current, and met the floor."""
    params = state.params if isinstance(state.params, dict) else {}
    taken = params.get(PARAM) if isinstance(params.get(PARAM), dict) else {}
    klass, reasons = run_class(params, events)
    held = effective(params, policy)
    out = {"class": klass, "tier": taken.get("tier"), "policy": taken.get("policy"),
           "benchmark": taken.get("benchmark"), "reasons": reasons,
           "release_ready": False, "not_yet_enforced": []}
    if held is None:
        return out
    out["not_yet_enforced"] = [s for s in held["pending"] if not definition.has_step(s)]
    stage = (policy or {}).get("release_ready_at")
    ready = [s for s in definition.steps if s.stage == stage
             and current(state, definition, s.id) is None
             and not floor_problems(state, definition, s, held)]
    out["release_ready"] = klass == RELEASE and bool(ready)
    return out

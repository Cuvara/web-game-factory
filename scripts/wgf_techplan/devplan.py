"""The development plan: milestones and tasks a coding agent works from.

Derived, not invented. Every task comes from something the design or a pinned profile
already states:

    M1  prototype   one task per `mvp` feature (acceptance = the feature's own acceptance)
                    plus CORE-001, boot on the template with the selected engine, plus one
                    CONTENT task per batch of MVP content units (the batch size and the hours
                    per unit are core/reference/genre-models.yaml `implementation`). A design
                    whose content is generated - `generation.mode` other than `authored` -
                    gets no CONTENT task: there is no list of units to build one against.
    M2  production  one task per `post-mvp` feature, and - when the run's quality tier builds
                    the post-mvp tier - one CONTENT task per batch of its post-mvp units;
                    omitted when there are none
    M3  hardening   one task per target platform (acceptance = the profile's blocking
                    assertions) plus QA-001, the verify suite green

What the run builds before G4 is its quality tier's (core/reference/quality-benchmark.yaml
`tiers[].builds`, recorded as `dev_plan.build_scope`): at `mvp` the prototype phase (M1), at
`release` the prototype and production phases (M1 and M2) - every feature the design
includes and every unit the release ships, since in `new-game` nothing is built after G4.
The developer's brief carries exactly those phases, and the develop budget is derived from
their tasks (budget.py).

`optional` features - and any feature whose evaluation is `later` or `cut` - are committed to
nothing and get no task. A design without `features`
(an older schema) falls back to its `scope.tiers` lists, whose entries carry no acceptance
criteria of their own - the generated criterion says so, which is what a reviewer at G3
should see.

Estimates are a heuristic, stated in `Estimates`, and deliberately not fitted to the
timebox: `plan_fits_timebox` is G3's question, and a plan that sums neatly to the budget
was fitted (core/lifecycle/stages/tech-plan.md).
"""

import math
import re

from wgflib import genre_models

__all__ = ["Estimates", "build_dev_plan", "GENRE_MODELS_PATH", "content_units", "MVP_SCOPE"]

# core/reference/genre-models.yaml, read through the one loader every step that holds a build
# to its genre family uses.
GENRE_MODELS_PATH = genre_models.PATH
# The data file the developer writes the units into, and the unit test over it
# (wgf_develop.content). Named here so a CONTENT task's acceptance says where a unit lives.
CONTENT_FILE = "public/content/units.json"
CONTENT_TEST = "tests/unit/content.test.ts"
# What a plan builds before G4 when the run states no quality tier: the MVP, as before.
MVP_SCOPE = {"quality_tier": "mvp", "design_tiers": ["mvp"], "plan_phases": ["prototype"]}


def _tier_of(entry):
    """A design entry's tier; an untiered entry is MVP."""
    return entry.get("tier") or "mvp"


def content_units(design, design_tiers=("mvp",)):
    """The content units a plan owes tasks for - those of `design_tiers` (the run's quality
    tier's, quality-benchmark `tiers[].builds`; the MVP by default) - in index order.

    Empty unless the design's content is `authored`: a parametric or procedural design
    generates its units from parameters, and its listed units are examples, not a build
    list."""
    content = ((design or {}).get("build_spec") or {}).get("content") or {}
    if (content.get("generation") or {}).get("mode") != "authored":
        return []
    units = [u for u in content.get("units") or []
             if isinstance(u, dict) and _tier_of(u) in design_tiers]
    return sorted(units, key=lambda u: (u.get("index") if isinstance(u.get("index"), int)
                                        else 10 ** 6, str(u.get("id"))))


def _content_tasks(design, by_feature, models, unit_kind=None, design_tiers=("mvp",)):
    """One CONTENT task per batch of `implementation.task_batch` units of the tiers built.

    Batched because a unit is small and a task per unit would make a plan nobody reads; kept
    in the design's order, because the order is the difficulty curve. MVP units are batched
    into M1 and the post-mvp units a release tier builds into M2, so a batch never mixes what
    the prototype is judged on with what the release adds. Each task depends on the GAME tasks
    of the mechanics its units ask for: a level cannot be built before the verb it is made
    of."""
    units = content_units(design, design_tiers)
    if not units:
        return []
    implementation = (models or {}).get("implementation") or {}
    batch_size = implementation.get("task_batch")
    batch_size = int(batch_size) if isinstance(batch_size, int) and batch_size > 0 else 3
    hours = implementation.get("content_unit_hours")
    hours = float(hours) if isinstance(hours, (int, float)) and hours > 0 else 1.5
    kind = unit_kind or "unit"
    batches = []
    for milestone, phase, members in (
            ("M1", "prototype", [u for u in units if _tier_of(u) == "mvp"]),
            ("M2", "production", [u for u in units if _tier_of(u) != "mvp"])):
        for start in range(0, len(members), batch_size):
            batches.append((milestone, phase, members[start:start + batch_size]))
    tasks = []
    for number, (milestone, phase, batch) in enumerate(batches, start=1):
        ids = [unit.get("id") for unit in batch]
        criteria, mechanics = [], []
        for unit in batch:
            criteria.extend(line for line in unit.get("acceptance") or [])
            criteria.append(f"Unit {unit.get('id')} is in {CONTENT_FILE} with the design's "
                            f"difficulty values" + _unit_fields(unit))
            index = unit.get("index")
            if isinstance(index, int) and index > 1:
                criteria.append(f"Reachable from unit {index - 1} in play")
            else:
                criteria.append(f"Unit {unit.get('id')} is where play starts")
            mechanics.extend(m for m in unit.get("mechanics") or [])
        tasks.append({
            "id": f"CONTENT-{number:03d}",
            "title": f"Build {kind}s " + ", ".join(str(i) for i in ids),
            "milestone": milestone,
            "phase": phase,
            "description": (f"The design's content units {', '.join(str(i) for i in ids)} as "
                            f"data in {CONTENT_FILE}, loaded at boot and reachable in play in "
                            f"the design's order. Difficulty values are the design's; nothing "
                            f"here is invented."),
            "dependencies": ["CORE-001"] + sorted(
                {by_feature[m] for m in mechanics if m in by_feature}),
            "acceptance_criteria": criteria,
            "tests": [CONTENT_TEST],
            "est_hours": round(hours * len(batch), 2),
            "status": "todo",
        })
    return tasks


class Estimates:
    """Hours per task. Every value is overridable under factory.techplan.estimates."""

    DEFAULTS = {
        "hours_per_day": 6,          # focused hours in an agent-assisted day
        "core_hours": 3,             # CORE-001: boot on the template with the engine
        "feature_base_hours": 2,     # any feature task
        "per_criterion_hours": 1.5,  # each acceptance criterion it must meet
        "feature_max_hours": 12,
        "platform_base_hours": 3,    # one platform through the platform abstraction
        "per_assertion_hours": 0.5,  # each blocking assertion its profile makes
        "qa_hours": 4,               # QA-001: verify suite green on every target
    }

    def __init__(self, overrides=None):
        values = dict(self.DEFAULTS)
        for key, value in (overrides or {}).items():
            if key not in values:
                raise ValueError(f"factory.techplan.estimates.{key} is not a known estimate "
                                 f"({', '.join(sorted(values))})")
            if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
                raise ValueError(f"factory.techplan.estimates.{key} must be a number > 0")
            values[key] = value
        self.values = values

    def __getattr__(self, name):
        try:
            return self.__dict__["values"][name]
        except KeyError:
            raise AttributeError(name)

    def feature(self, criteria):
        hours = self.feature_base_hours + self.per_criterion_hours * max(1, criteria)
        return min(hours, self.feature_max_hours)

    def platform(self, assertions):
        return self.platform_base_hours + self.per_assertion_hours * assertions

    def days(self, hours):
        """Half-day granularity, rounded up: an estimate is a ceiling, not a target."""
        return math.ceil(2 * hours / self.hours_per_day) / 2


def _unit_fields(unit):
    """The game-design 1.12.0 fields a unit states, named in its criterion so the built unit is
    held to them (wgf_develop.content compares them)."""
    named = [f for f in ("group", "structure", "elements", "objective_kind") if unit.get(f)]
    return f", and its {', '.join(named)} as the design states" if named else ""


def _slug(text):
    return re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")[:48] or "item"


def _features(design):
    """[(id, name, tier, description, acceptance, depends_on)] from features, else scope."""
    features = design.get("features")
    if features:
        return [(f["id"], f.get("name") or f["id"], f.get("tier"), f.get("description") or "",
                 list(f.get("acceptance") or []), list(f.get("depends_on") or []))
                for f in features if isinstance(f, dict) and f.get("id")]
    tiers = (design.get("scope") or {}).get("tiers") or {}
    derived, seen = [], set()
    for tier_key, tier in (("mvp", "mvp"), ("production", "post-mvp")):
        for item in tiers.get(tier_key) or []:
            fid = _slug(item)
            if fid in seen:
                continue
            seen.add(fid)
            derived.append((fid, str(item), tier, str(item), [], []))
    return derived


def build_dev_plan(design, engine, platforms, estimates, models=None, scope=None):
    """dev_plan for the tech-plan, and the ids of the tasks per milestone.

    `models` is core/reference/genre-models.yaml, read when not given: its `implementation`
    block says how content units are batched into tasks and what one costs. `scope` is what
    the run builds before G4 ({quality_tier, design_tiers, plan_phases, where?}; MVP_SCOPE
    when not given): every unit of its design tiers gets a CONTENT task."""
    models = genre_models.load() if models is None else models
    scope = dict(scope or MVP_SCOPE)
    design_tiers = tuple(scope.get("design_tiers") or MVP_SCOPE["design_tiers"])
    plan_phases = list(scope.get("plan_phases") or MVP_SCOPE["plan_phases"])
    tasks, by_feature = [], {}
    core = {
        "id": "CORE-001",
        "title": f"Boot the game on the template with engine {engine}",
        "milestone": "M1",
        "phase": "prototype",
        "description": "game.config.yaml as written at scaffolding: the engine the plan selected "
                       "and the pinned platforms. Game code goes in src/; packages/ are the "
                       "template's and are not edited.",
        "acceptance_criteria": [
            f"The game boots with engine.type {engine} and the first required platform's adapter",
            "The template's ci pipeline is green before any game code lands",
        ],
        "tests": ["tests/e2e (template smoke)"],
        "est_hours": estimates.core_hours,
        "status": "todo",
    }
    tasks.append(core)

    features = _features(design)
    decisions = {f.get("id"): (f.get("evaluation") or {}).get("decision")
                 for f in design.get("features") or [] if isinstance(f, dict)}
    counters = {"GAME": 0}
    for fid, name, tier, description, acceptance, _deps in features:
        if tier not in ("mvp", "post-mvp"):
            continue
        if decisions.get(fid) in ("later", "cut"):
            continue  # evaluated out of this game (game-design 1.10.0): nothing to build
        counters["GAME"] += 1
        task_id = f"GAME-{counters['GAME']:03d}"
        by_feature[fid] = task_id
        criteria = acceptance or [f"'{name}' behaves as the game-design scope states; the "
                                  "design gives no finer acceptance criteria"]
        tasks.append({
            "id": task_id,
            "title": f"Implement {name}",
            "milestone": "M1" if tier == "mvp" else "M2",
            "phase": "prototype" if tier == "mvp" else "production",
            "description": description or name,
            "dependencies": [],
            "acceptance_criteria": criteria,
            "tests": [f"tests/unit/{fid}.spec.ts"],
            "est_hours": estimates.feature(len(acceptance)),
            "status": "todo",
        })
    # Dependencies: the feature's own, mapped to task ids, after CORE-001.
    for fid, _name, tier, _d, _a, deps in features:
        task_id = by_feature.get(fid)
        if not task_id:
            continue
        task = next(t for t in tasks if t["id"] == task_id)
        task["dependencies"] = ["CORE-001"] + [by_feature[d] for d in deps if d in by_feature]

    # The content after the features it is made of: a level is built from the verbs, and
    # its task depends on theirs.
    tasks.extend(_content_tasks(
        design, by_feature, models,
        unit_kind=(((design.get("build_spec") or {}).get("content") or {}).get("unit_kind")),
        design_tiers=design_tiers))

    # Platform integration starts from everything built before G4.
    m1_ids = [t["id"] for t in tasks if t["milestone"] == "M1"
              or (t["milestone"] == "M2" and t.get("phase") in plan_phases)]
    for index, platform in enumerate(platforms, start=1):
        assertions = platform.blocking_assertions()
        tasks.append({
            "id": f"SDK-{index:03d}",
            "title": f"Integrate {platform.id} ({platform.role}) through the platform abstraction",
            "milestone": "M3",
            "phase": "hardening",
            "description": f"Profile {platform.pin}. Game code calls the template's platform "
                           "abstraction, never a portal SDK directly.",
            "dependencies": list(m1_ids),
            "acceptance_criteria": ([f"Assertion {a} passes against the built package"
                                     for a in assertions]
                                    or [f"The build boots on the {platform.id} adapter"]),
            "tests": ["tests/sdk (conformance)", "tests/verify"],
            "est_hours": estimates.platform(len(assertions)),
            "status": "todo",
        })
    tasks.append({
        "id": "QA-001",
        "title": "Verify suite green on every target platform",
        "milestone": "M3",
        "phase": "hardening",
        "dependencies": [t["id"] for t in tasks if t["id"] != "CORE-001"],
        "acceptance_criteria": ["pnpm test:verify passes",
                                "pnpm facts && pnpm assert pass for every pinned profile"],
        "tests": ["tests/verify"],
        "est_hours": estimates.qa_hours,
        "status": "todo",
    })

    def content_exit(milestone, which):
        return ([f"Every {which} content unit is in {CONTENT_FILE} and reachable in play"]
                if any(t["id"].startswith("CONTENT-") and t["milestone"] == milestone
                       for t in tasks) else [])

    before_g4 = "production" in plan_phases
    labels = {"M1": ("Playable core loop", "prototype",
                     ["Every mvp feature meets its acceptance criteria"]
                     + content_exit("M1", "MVP")
                     + ["The prototype answers the strategy's prototype_must_prove "
                        "questions"]),
              "M2": ("Release scope, built before G4" if before_g4 else "Production scope",
                     "production",
                     ["Every post-mvp feature meets its acceptance criteria"]
                     + content_exit("M2", "post-mvp")),
              "M3": ("Platform integration and hardening", "hardening",
                     ["Every target platform's blocking assertions pass",
                      "The verify suite is green"])}
    milestones = []
    for mid in ("M1", "M2", "M3"):
        hours = sum(t["est_hours"] for t in tasks if t["milestone"] == mid)
        if not hours:
            continue
        label, phase, exit_criteria = labels[mid]
        milestones.append({"id": mid, "label": label, "phase": phase,
                           "est_days": estimates.days(hours), "exit_criteria": exit_criteria})
    return {
        "est_days": sum(m["est_days"] for m in milestones),
        "build_scope": {"quality_tier": scope.get("quality_tier") or "mvp",
                        "design_tiers": list(design_tiers), "plan_phases": plan_phases,
                        **({"where": scope["where"]} if scope.get("where") else {})},
        "milestones": milestones,
        "tasks": tasks,
    }

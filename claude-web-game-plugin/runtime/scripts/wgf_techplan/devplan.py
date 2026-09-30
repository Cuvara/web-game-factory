"""The development plan: milestones and tasks a coding agent works from.

Derived, not invented. Every task comes from something the design or a pinned profile
already states:

    M1  prototype   one task per `mvp` feature (acceptance = the feature's own acceptance)
                    plus CORE-001, boot on the template with the selected engine
    M2  production  one task per `post-mvp` feature; omitted when there are none
    M3  hardening   one task per target platform (acceptance = the profile's blocking
                    assertions) plus QA-001, the verify suite green

`optional` features are committed to nothing and get no task. A design without `features`
(an older schema) falls back to its `scope.tiers` lists, whose entries carry no acceptance
criteria of their own - the generated criterion says so, which is what a reviewer at G3
should see.

Estimates are a heuristic, stated in `Estimates`, and deliberately not fitted to the
timebox: `plan_fits_timebox` is G3's question, and a plan that sums neatly to the budget
was fitted (core/lifecycle/stages/tech-plan.md).
"""

import math
import re

__all__ = ["Estimates", "build_dev_plan"]


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


def build_dev_plan(design, engine, platforms, estimates):
    """dev_plan for the tech-plan, and the ids of the tasks per milestone."""
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
    counters = {"GAME": 0}
    for fid, name, tier, description, acceptance, _deps in features:
        if tier not in ("mvp", "post-mvp"):
            continue
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

    m1_ids = [t["id"] for t in tasks if t["milestone"] == "M1"]
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

    labels = {"M1": ("Playable core loop", "prototype",
                     ["Every mvp feature meets its acceptance criteria",
                      "The prototype answers the strategy's prototype_must_prove questions"]),
              "M2": ("Production scope", "production",
                     ["Every post-mvp feature meets its acceptance criteria"]),
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
        "milestones": milestones,
        "tasks": tasks,
    }

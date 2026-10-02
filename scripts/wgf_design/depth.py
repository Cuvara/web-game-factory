"""Design depth: why a player plays longer and comes back, held to the design.

A design whose only loop is the run - drop, merge, fail, retry - gives a player nothing to come
back for. `build_spec.depth` (game-design 1.7.0) states what sits above the run, and `check`
holds it to core/reference/design-depth.yaml, by reference and by number:

  * a meta loop: a statement and what persists between sessions, at least one persisted
    entry more than a score or a setting (`meta_loop.score_only_kinds`);
  * a goal ladder with a goal at every horizon (short, mid, long), the prototype's horizons
    (`mvp_horizons`) MVP;
  * at least `min_items` content-variety items introduced over play on a schedule - at
    `min_distinct_introductions` distinct points, the first in-run one by `max_first_in_run_s`
    - and `min_mvp_items` of them MVP;
  * a first session of `min_s`..`max_s` seconds, the same number as
    session.first_session_seconds;
  * at least `min_items` return hooks, `min_mvp_items` of them MVP;
  * tiers stated honestly: an MVP or post-mvp entry names what delivers it (`delivered_by`: a
    feature, mechanic, progression step, reward or hud id), the id resolves, and an MVP entry
    never rests on something the MVP does not build.

Depth need not be built in the prototype: a strategy that defers retention systems gets them
post-mvp or optional, and the check accepts that. What it refuses is nothing above the core
loop at any tier, and depth claimed for the MVP that the MVP does not deliver.

The problems are what the design step shows an author that can repair its draft, and what fails
a design that keeps them. Each one names the field to change. core/craft/
retention-and-progression.md is the prose behind the bars.
"""

import os

from wgflib import paths
from wgflib.yamllite import load_file

__all__ = ["RULES_PATH", "load_rules", "deliverers", "check"]

RULES_PATH = os.path.join(paths.REFERENCE, "design-depth.yaml")
PARTS = ("meta_loop", "goal_ladder", "content_schedule", "first_session", "return_hooks")
_WHAT = {
    "meta_loop": "the loop above the run and what persists between sessions",
    "goal_ladder": "a goal at each horizon - short, mid and long",
    "content_schedule": "the content-variety items introduced over play, and when",
    "first_session": "the first session's designed length and the beat it ends on",
    "return_hooks": "the reasons a player opens the game again",
}


def load_rules(path=None):
    return load_file(path or RULES_PATH)


def deliverers(design):
    """{id: tier} of everything a depth entry may rest on: features, mechanics, progression
    steps, rewards and hud elements."""
    spec = design.get("build_spec") or {}
    found = {}
    for item in design.get("features") or []:
        found.setdefault(item.get("id"), item.get("tier"))
    for key in ("mechanics", "rewards", "hud"):
        for item in spec.get(key) or []:
            found.setdefault(item.get("id"), item.get("tier"))
    for step in (spec.get("progression") or {}).get("steps") or []:
        found.setdefault(step.get("id"), step.get("tier"))
    found.pop(None, None)
    return found


def _honest(where, entry, known, problems):
    """An mvp or post-mvp entry names what builds it; an mvp entry rests on mvp."""
    tier = entry.get("tier")
    by = entry.get("delivered_by")
    if not by:
        if tier in ("mvp", "post-mvp"):
            problems.append(f"{where} is {tier} but names nothing that delivers it: set "
                            "delivered_by to the feature, mechanic, progression step, reward or "
                            "hud id that builds it, or tier it optional")
        return
    if by not in known:
        problems.append(f"{where}.delivered_by {by!r} is not a feature, mechanic, progression "
                        "step, reward or hud id of this design")
    elif tier == "mvp" and known[by] != "mvp":
        problems.append(f"{where} is mvp but rests on {by!r}, which is {known[by]}: the MVP "
                        f"does not build it - tier the entry {known[by]}, or build {by!r} in the MVP")


def check(design, rules=None):
    """Problems (strings) with the design's depth. Empty means it holds."""
    rules = rules or load_rules()
    spec = design.get("build_spec") or {}
    depth = spec.get("depth")
    problems = []
    if not isinstance(depth, dict):
        problems.append("build_spec.depth is missing: state the meta loop, the goal ladder, the "
                        "content schedule, the first session and the return hooks, each tiered "
                        "(core/craft/retention-and-progression.md)")
        depth = {}
    for part in PARTS:
        if not depth.get(part):
            problems.append(f"depth.{part} is missing: state {_WHAT[part]}")
    known = deliverers(design)

    # The meta loop: something beyond a score survives the session.
    meta = depth.get("meta_loop") or {}
    if meta:
        _honest("depth.meta_loop", meta, known, problems)
        score_only = set((rules.get("meta_loop") or {}).get("score_only_kinds") or [])
        persists = meta.get("persists") or []
        if persists and all(p.get("kind") in score_only for p in persists):
            problems.append(f"depth.meta_loop persists only {', '.join(sorted({p.get('kind') for p in persists}))}"
                            ": a score is not a meta loop - persist progress the player builds "
                            "(stage progress, unlocks, currency, upgrades, cosmetics, missions, "
                            "achievements, streak or collection), at any tier")
        for index, entry in enumerate(persists):
            _honest(f"depth.meta_loop.persists[{index}] ({entry.get('kind')})", entry, known,
                    problems)

    # A goal at every horizon; the prototype's horizons in the MVP.
    ladder_rules = rules.get("goal_ladder") or {}
    ladder = depth.get("goal_ladder") or []
    if ladder:
        for horizon in ladder_rules.get("horizons") or []:
            goals = [g for g in ladder if g.get("horizon") == horizon]
            if not goals:
                problems.append(f"depth.goal_ladder has no {horizon} goal")
            elif horizon in (ladder_rules.get("mvp_horizons") or []) and \
                    not any(g.get("tier") == "mvp" for g in goals):
                problems.append(f"depth.goal_ladder has no mvp {horizon} goal: the prototype "
                                f"must give the player a {horizon}-horizon goal")
        for goal in ladder:
            _honest(f"depth.goal_ladder {goal.get('id')!r}", goal, known, problems)

    # Content variety, arriving over time.
    content_rules = rules.get("content_schedule") or {}
    schedule = depth.get("content_schedule") or []
    if schedule:
        minimum = content_rules.get("min_items", 0)
        if len(schedule) < minimum:
            problems.append(f"depth.content_schedule has {len(schedule)} item(s); the bar is "
                            f"{minimum}: introduce more piece, obstacle, power-up, zone or event "
                            "types over play, at any tier")
        mvp_items = [c for c in schedule if c.get("tier") == "mvp"]
        if len(mvp_items) < content_rules.get("min_mvp_items", 0):
            problems.append(f"depth.content_schedule has {len(mvp_items)} mvp item(s); the bar is "
                            f"{content_rules.get('min_mvp_items')}: the prototype shows variety "
                            "arriving, not one static set")
        points = {("s", c["at_s"]) if isinstance(c.get("at_s"), (int, float)) else
                  ("runs", c["after_runs"]) if isinstance(c.get("after_runs"), int) else
                  ("words", (c.get("introduced") or "").strip().lower())
                  for c in schedule}
        distinct = content_rules.get("min_distinct_introductions", 0)
        if len(points) < distinct:
            problems.append(f"depth.content_schedule introduces its items at {len(points)} "
                            f"distinct point(s); the bar is {distinct}: spread them over the run "
                            "and across runs (at_s, after_runs)")
        in_run = [c["at_s"] for c in schedule if isinstance(c.get("at_s"), (int, float))
                  and c["at_s"] > 0]
        first_bar = content_rules.get("max_first_in_run_s")
        if in_run and first_bar is not None and min(in_run) > first_bar:
            problems.append(f"depth.content_schedule's first in-run item arrives at "
                            f"{min(in_run):g} s; the bar is {first_bar} s")
        for item in schedule:
            _honest(f"depth.content_schedule {item.get('id')!r}", item, known, problems)

    # The first session: long enough to show the loop more than once, and one number.
    first = depth.get("first_session") or {}
    session_first = (design.get("session") or {}).get("first_session_seconds")
    bars = rules.get("first_session") or {}
    target = first.get("target_s") if first else session_first
    where = "depth.first_session.target_s" if first else "session.first_session_seconds"
    if isinstance(target, (int, float)):
        if "min_s" in bars and target < bars["min_s"]:
            problems.append(f"{where} is {target:g} s; the bar is {bars['min_s']} s: a first "
                            "session that short shows the loop once and never what comes after it")
        elif "max_s" in bars and target > bars["max_s"]:
            problems.append(f"{where} is {target:g} s; the bar is {bars['max_s']} s for a web "
                            "portal session")
    if first and isinstance(session_first, (int, float)) and first.get("target_s") != session_first:
        problems.append(f"depth.first_session.target_s is {first.get('target_s')} s but "
                        f"session.first_session_seconds says {session_first} s")

    # Reasons to return.
    hook_rules = rules.get("return_hooks") or {}
    hooks = depth.get("return_hooks") or []
    if hooks:
        if len(hooks) < hook_rules.get("min_items", 0):
            problems.append(f"depth.return_hooks has {len(hooks)} hook(s); the bar is "
                            f"{hook_rules.get('min_items')}")
        mvp_hooks = [h for h in hooks if h.get("tier") == "mvp"]
        if len(mvp_hooks) < hook_rules.get("min_mvp_items", 0):
            problems.append(f"depth.return_hooks has {len(mvp_hooks)} mvp hook(s); the bar is "
                            f"{hook_rules.get('min_mvp_items')}: the prototype already gives the "
                            "player one reason to come back")
        for hook in hooks:
            _honest(f"depth.return_hooks {hook.get('id')!r}", hook, known, problems)
    return problems

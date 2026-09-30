"""Turn an author's draft into a game-design body, and check that the MVP is buildable.

Everything here is author-independent. The draft supplies creative content; this module
supplies what no author may decide for itself:

- SDK touchpoints the platform profiles require,
- `platform_constraints_applied`, read from the same profiles,
- `scope.tiers`, derived from `features` so the tier list and the feature list cannot drift
  (mvp -> mvp and prototype, post-mvp -> production, optional -> future),
- `monetization.placements`, derived from the build spec's monetization touchpoints,
- the buildability check: every cross-reference inside the build spec resolves, the game's
  state machine is connected, and the MVP is complete without anything outside the MVP.
"""

import copy

from .platforms import constraints_applied, sdk_touchpoints

__all__ = ["finalize", "buildability"]

TIERS = ("mvp", "post-mvp", "optional")
RANK = {tier: index for index, tier in enumerate(TIERS)}


def _state_roles(spec, given):
    states = spec.get("game_states") or []
    ids = [s["id"] for s in states]
    initial = next((s["id"] for s in states if s.get("initial")), ids[0] if ids else None)
    play = "play" if "play" in ids else initial
    play_exits = next((s.get("exits") or [] for s in states if s["id"] == play), [])
    fail = next((e["to"] for e in play_exits if "fail" in e["to"] or "result" in e["to"]), play)
    roles = {
        "boot": initial,
        "loading": "loading" if "loading" in ids else initial,
        "play": play,
        "pause": "pause" if "pause" in ids else play,
        "fail": fail,
    }
    roles.update(given or {})
    return roles


def finalize(draft, platforms, title_id):
    design = copy.deepcopy(draft)
    roles = design.pop("state_roles", None)
    design["title_id"] = title_id
    spec = design["build_spec"]

    derived = sdk_touchpoints(platforms, spec, _state_roles(spec, roles))
    authored = spec.get("sdk_touchpoints") or []
    have = {t["capability"] for t in authored}
    spec["sdk_touchpoints"] = authored + [t for t in derived if t["capability"] not in have]

    design.setdefault("monetization", {})
    design["monetization"]["placements"] = [
        {key: t[key] for key in ("kind", "trigger", "player_value", "platforms") if key in t}
        for t in spec.get("monetization_touchpoints") or []
    ]

    features = design.get("features") or []
    names = {tier: [f["name"] for f in features if f["tier"] == tier] for tier in TIERS}
    scope = design["scope"]
    out_of_scope = scope.pop("out_of_scope", [])
    design["scope"] = dict({"tiers": {
        "mvp": names["mvp"],
        "prototype": list(names["mvp"]),
        "production": names["post-mvp"],
        "future": names["optional"],
        "out_of_scope": out_of_scope,
    }}, **scope)

    design["platform_constraints_applied"] = constraints_applied(platforms, design)
    return design


def _duplicates(items, label):
    seen, problems = set(), []
    for item in items:
        if item["id"] in seen:
            problems.append(f"{label}: duplicate id {item['id']!r}")
        seen.add(item["id"])
    return problems


def buildability(design):
    """Problems that would force an implementer to guess. Empty means buildable."""
    spec = design.get("build_spec") or {}
    problems = []
    lists = {
        "features": design.get("features") or [],
        "mechanics": spec.get("mechanics") or [],
        "controls.actions": (spec.get("controls") or {}).get("actions") or [],
        "game_states": spec.get("game_states") or [],
        "screens": spec.get("screens") or [],
        "hud": spec.get("hud") or [],
        "menus": spec.get("menus") or [],
        "rewards": spec.get("rewards") or [],
        "monetization_touchpoints": spec.get("monetization_touchpoints") or [],
        "sdk_touchpoints": spec.get("sdk_touchpoints") or [],
        "assets": spec.get("assets") or [],
        "audio": spec.get("audio") or [],
    }
    for label, items in lists.items():
        problems += _duplicates(items, label)

    for label in ("mechanics", "controls.actions", "game_states", "screens", "assets", "features"):
        if not any(item["tier"] == "mvp" for item in lists[label]):
            problems.append(f"{label}: nothing is mvp - the MVP cannot be built from this")

    states = {s["id"]: s for s in lists["game_states"]}
    tier_of = {s["id"]: s["tier"] for s in lists["game_states"]}
    initial = [s["id"] for s in lists["game_states"] if s.get("initial")]
    if len(initial) != 1:
        problems.append(f"game_states: exactly one initial state needed, found {initial or 'none'}")
    for state in lists["game_states"]:
        for exit_ in state.get("exits") or []:
            if exit_["to"] not in states:
                problems.append(f"game_states.{state['id']}: exit to unknown state {exit_['to']!r}")
    if len(initial) == 1:
        # Reachability through MVP states only: the MVP must be a connected game on its own.
        reached, frontier = {initial[0]}, [initial[0]]
        while frontier:
            current = states[frontier.pop()]
            for exit_ in current.get("exits") or []:
                target = exit_["to"]
                if target in states and target not in reached and tier_of[target] == "mvp":
                    reached.add(target)
                    frontier.append(target)
        for state_id, tier in tier_of.items():
            if tier == "mvp" and state_id not in reached:
                problems.append(f"game_states.{state_id}: mvp state unreachable through mvp states")
        for state_id, state in states.items():
            if tier_of[state_id] == "mvp" and not state.get("exits"):
                problems.append(f"game_states.{state_id}: mvp state with no exit is a dead end")

    def ref(label, item, key, known, what):
        value = item.get(key)
        if value is not None and value not in known:
            problems.append(f"{label}.{item['id']}: {key} {value!r} is not a known {what}")
        return value

    def tier_ok(label, item, target_tier, what):
        if target_tier and RANK[item["tier"]] < RANK[target_tier]:
            problems.append(f"{label}.{item['id']}: {item['tier']} but depends on a {target_tier} {what}")

    for screen in lists["screens"]:
        state = ref("screens", screen, "state", states, "game state")
        tier_ok("screens", screen, tier_of.get(state), "state")
        for action in screen.get("actions") or []:
            if action["goes_to"] not in states:
                problems.append(f"screens.{screen['id']}: action {action['label']!r} goes to unknown state "
                                f"{action['goes_to']!r}")
            elif RANK[screen["tier"]] < RANK[tier_of[action["goes_to"]]]:
                problems.append(f"screens.{screen['id']}: {screen['tier']} action {action['label']!r} leads to "
                                f"a {tier_of[action['goes_to']]} state - a button to nothing")
    screens = {s["id"]: s["tier"] for s in lists["screens"]}
    for menu in lists["menus"]:
        screen = ref("menus", menu, "screen", screens, "screen")
        tier_ok("menus", menu, screens.get(screen), "screen")
    mechanics = {m["id"]: m["tier"] for m in lists["mechanics"]}
    for action in lists["controls.actions"]:
        mechanic = ref("controls.actions", action, "mechanic", mechanics, "mechanic")
        tier_ok("controls.actions", action, mechanics.get(mechanic), "mechanic")
    for label in ("monetization_touchpoints", "sdk_touchpoints"):
        for touchpoint in lists[label]:
            state = ref(label, touchpoint, "state", states, "game state")
            tier_ok(label, touchpoint, tier_of.get(state), "state")
    features = {f["id"] for f in lists["features"]}
    for feature in lists["features"]:
        for dependency in feature.get("depends_on") or []:
            if dependency not in features:
                problems.append(f"features.{feature['id']}: depends on unknown feature {dependency!r}")
        if feature["tier"] == "mvp" and not feature.get("acceptance"):
            problems.append(f"features.{feature['id']}: mvp feature without acceptance criteria")

    failure = spec.get("failure") or {}
    offer = failure.get("continue_offer")
    if offer is not None:
        touchpoint = next((t for t in lists["monetization_touchpoints"] if t["id"] == offer), None)
        if touchpoint is None:
            problems.append(f"failure.continue_offer {offer!r} is not a monetization touchpoint")
        elif touchpoint["kind"] != "rewarded":
            problems.append(f"failure.continue_offer {offer!r} is {touchpoint['kind']}, not rewarded")

    palette = [p["token"] for p in (spec.get("visual_identity") or {}).get("palette") or []]
    if len(palette) != len(set(palette)):
        problems.append("visual_identity.palette: duplicate token")
    return problems

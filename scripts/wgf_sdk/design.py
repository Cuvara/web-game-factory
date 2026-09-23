"""What the game-design needs from the platform: its placements, moments and features.

Feature names are the conformance suite's (plan.py) where they mean the same thing, so the
two phases of the step report one vocabulary.

Two inputs, both read, neither assumed:

- the game-design: its monetization placements, retention hooks and targets say which
  platform features the game actually needs. Nothing the design did not ask for is wired;
  "integrate every capability the SDK has" is how rewarded buttons with no reward ship.
- the SDK inspection (inspect_sdk): which adapter each platform id gets, what that adapter
  can do, and which calls the `Platform` interface offers at all.

A placement is attached to a gameplay moment by reading its trigger. The design writes
triggers as prose ("On death, offer a continue"), so the attachment is a keyword match and
the report says so; a trigger that matches nothing is reported as unmapped, not guessed.
"""

import re

__all__ = [
    "MOMENTS",
    "ALWAYS_REQUIRED",
    "Placement",
    "classify_trigger",
    "design_placements",
    "required_features",
]

# Moment -> the words that put a trigger there. First match wins, in this order: "on level
# fail, offer a continue" is a game over, not a level transition, and so is "between runs" -
# a run ends in a game over, a level in a level transition.
MOMENTS = (
    ("game-over", r"\b(death|die[sd]?|dead|game[ -]?over|los[et]|loss|fail\w*|crash\w*|"
                  r"miss(es|ed)?|revive|continue|restart\w*|retry|second chance|extra li(fe|ves)|"
                  r"between runs|runs? ends?|ends? (a|the) run)\b"),
    ("level-complete", r"\b(levels?|stages?|rounds?|waves?|win|won|victory|clear\w*|"
                       r"complet\w*|finish\w*|between)\b"),
    ("pause-menu", r"\b(pause\w*|menu)\b"),
)

# Features every build needs whatever the design says: the boot sequence portals check, and
# the gameplay/pause signals they bracket ad breaks with.
ALWAYS_REQUIRED = (
    "init",
    "loading",
    "gameplay-lifecycle",
    "pause-resume",
    "audio-mute",
)

# Retention hooks that only work if progress survives a reload.
_PERSISTENT_HOOKS = {"progression", "collection", "streak", "daily_quest", "unlock_timer",
                     "energy"}


def classify_trigger(trigger):
    text = (trigger or "").lower()
    for moment, pattern in MOMENTS:
        if re.search(pattern, text):
            return moment
    return None


class Placement:
    def __init__(self, index, kind, trigger, moment, platforms, player_value=None):
        self.index = index
        self.kind = kind
        self.trigger = trigger
        self.moment = moment                    # None: the trigger matched no moment
        self.platforms = platforms              # None: every platform
        self.player_value = player_value
        self.excluded = []                      # targets that forbid this moment
        self.id = f"{kind}-{moment or 'unmapped'}"

    def applies_to(self, platform_id):
        return self.platforms is None or platform_id in self.platforms

    def to_plan(self):
        return {
            "id": self.id,
            "kind": self.kind,
            "moment": self.moment,
            "trigger": self.trigger,
            "platforms": self.platforms,
        }


def design_placements(design):
    placements, seen = [], {}
    for index, raw in enumerate((design.get("monetization") or {}).get("placements") or []):
        placement = Placement(
            index,
            raw.get("kind"),
            raw.get("trigger", ""),
            classify_trigger(raw.get("trigger")),
            list(raw["platforms"]) if raw.get("platforms") else None,
            raw.get("player_value"),
        )
        count = seen.get(placement.id, 0)
        seen[placement.id] = count + 1
        if count:
            placement.id = f"{placement.id}-{count + 1}"
        placements.append(placement)
    return placements


def required_features(design, placements, platform_id):
    """feature -> why the design needs it, for one target platform."""
    needed = {feature: "every portal build" for feature in ALWAYS_REQUIRED}
    for placement in placements:
        if placement.applies_to(platform_id):
            needed.setdefault(placement.kind, f"monetization placement: {placement.trigger}")
    retention = design.get("retention") or {}
    hooks = set(retention.get("hooks") or [])
    persistent = sorted(hooks & _PERSISTENT_HOOKS)
    if persistent:
        needed["storage"] = "retention hooks: " + ", ".join(persistent)
    if "leaderboard" in hooks:
        needed["leaderboards"] = "retention hook: leaderboard"
    if retention.get("targets"):
        needed["analytics"] = "retention targets must be measured"
    return needed

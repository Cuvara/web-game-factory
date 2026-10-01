"""The experience contract: what a first-time player must be able to tell, held to the design.

`build_spec.experience` (game-design 1.5.0) states the objective and the screen that shows it,
how play is won and lost, how every MVP action is acknowledged, what the first session
teaches and its grace before failure, and the first-30-seconds budget. `check` holds it to
core/reference/experience-rules.yaml and to the rest of the build_spec, by reference and by
number - never by matching words:

  * the objective's screen exists, is MVP, and is shown in play or before it;
  * every metric the contract relies on - the objective's, the win's, the lose's, and every
    metric an action changes - is shown by an MVP HUD element (`hud[].metric`);
  * every MVP control action has an acknowledgement, within the feedback bar;
  * onboarding teaches every MVP gameplay action, and a first-time player cannot fail before
    the first success, or before the grace bar's seconds;
  * the first-30-seconds budget is within the bars, and says what the session and the
    failure sections say;
  * a key the design names (a state exit, the pause rule) is bound by some action;
  * an onboarding that shows the answer does not stand beside a strategy question that the
    player must understand without instruction.

The problems are what the design step shows an author that can repair its draft, and what
fails a design that keeps them. Each one names the field to change.
"""

import os
import re

from wgflib import paths
from wgflib.yamllite import load_file

__all__ = ["RULES_PATH", "load_rules", "check"]

RULES_PATH = os.path.join(paths.REFERENCE, "experience-rules.yaml")

# A key a state exit or the pause rule names: it needs a keyboard binding somewhere.
_KEY = re.compile(r"\b(esc|escape|space(bar)?|enter|return|arrow keys?|tab key)\b", re.I)
# A strategy question asking for understanding with no help.
_UNAIDED = re.compile(r"\b(without (instruction|help|being told|a tutorial|explanation)|unprompted|"
                      r"unaided|on (their|its) own)\b", re.I)


def load_rules(path=None):
    return load_file(path or RULES_PATH)


def _bound(binding):
    text = (binding or "").strip()
    return bool(text) and not re.match(r"^\s*(no\b|not bound|none\b|n/?a\b|-)", text, re.I)


def check(design, strategy=None, rules=None):
    """Problems (strings) with the design's experience contract. Empty means it holds."""
    rules = rules or load_rules()
    spec = design.get("build_spec") or {}
    ex = spec.get("experience")
    if not isinstance(ex, dict):
        return ["build_spec.experience is missing: state the objective and where it is shown, "
                "how play is lost (and won), how each action is acknowledged, the onboarding "
                "grace, and the first-30-seconds budget"]
    problems = []
    mvp = lambda items: [i for i in items or [] if i.get("tier") == "mvp"]  # noqa: E731

    screens = {s.get("id"): s for s in mvp(spec.get("screens"))}
    states = {s.get("id"): s for s in spec.get("game_states") or []}
    shown = {h.get("metric"): h.get("id") for h in mvp(spec.get("hud")) if h.get("metric")}
    actions = {a.get("id"): a for a in mvp((spec.get("controls") or {}).get("actions"))}

    # The objective, and where the player reads it.
    goal = ex.get("goal") or {}
    screen = screens.get(goal.get("shown_on"))
    if screen is None:
        problems.append(f"experience.goal.shown_on {goal.get('shown_on')!r} is not an MVP screen")
    else:
        # The states a first session passes through up to play: reachable from the initial
        # state without going through play. A result screen also leads to play, but only
        # after a first round the player played without the objective.
        before = {s for s, v in states.items() if v.get("initial")}
        frontier = list(before)
        while frontier:
            for exit_ in states.get(frontier.pop(), {}).get("exits") or []:
                target = exit_.get("to")
                if target and target != "play" and target not in before:
                    before.add(target)
                    frontier.append(target)
        if screen.get("state") not in before | {"play"}:
            problems.append(f"experience.goal.shown_on {screen.get('id')!r} is shown in state "
                            f"{screen.get('state')!r}, which is neither play nor a state that "
                            "leads into it: the player would meet play before the objective")

    # Every metric the contract relies on is on the HUD.
    relied = [("goal", goal.get("metric"))]
    if isinstance(ex.get("win"), dict):
        relied.append(("win", ex["win"].get("metric")))
    if (ex.get("lose") or {}).get("metric"):
        relied.append(("lose", ex["lose"]["metric"]))
    for entry in ex.get("actions") or []:
        relied += [(f"action {entry.get('action')!r}", m) for m in entry.get("updates") or []]
    for where, metric in relied:
        if metric and metric not in shown:
            problems.append(f"experience {where} relies on metric {metric!r}, which no MVP hud "
                            f"element shows (set hud[].metric, or add the element)")

    # Every MVP action is acknowledged, within the bar.
    max_ack = (rules.get("feedback") or {}).get("max_ack_ms", 100)
    acknowledged = {}
    for entry in ex.get("actions") or []:
        acknowledged[entry.get("action")] = entry
        if entry.get("action") not in actions:
            problems.append(f"experience.actions names {entry.get('action')!r}, which is not an "
                            "MVP controls action")
        elif (entry.get("max_ack_ms") or 0) > max_ack:
            problems.append(f"experience action {entry.get('action')!r} is acknowledged after "
                            f"{entry.get('max_ack_ms')} ms; the bar is {max_ack} ms")
    for aid in actions:
        if aid not in acknowledged:
            problems.append(f"MVP action {aid!r} has no acknowledgement in experience.actions: "
                            "the player cannot tell it worked")

    # Teach before testing; no failure before the first success.
    onboarding = ex.get("onboarding") or {}
    gameplay = [aid for aid in actions if aid != "pause"]
    untaught = [aid for aid in gameplay if aid not in (onboarding.get("teaches") or [])]
    if untaught:
        problems.append(f"onboarding does not teach MVP action(s) {', '.join(untaught)}")
    grace = onboarding.get("grace") or {}
    min_grace = (rules.get("onboarding") or {}).get("min_grace_s", 10)
    if grace.get("until") == "seconds" and (grace.get("seconds") or 0) < min_grace:
        problems.append(f"onboarding grace is {grace.get('seconds')} s; a first-time player must "
                        f"not be able to fail for at least {min_grace} s, or before the first success")
    questions = (strategy or {}).get("prototype_must_prove") or []
    if onboarding.get("reveals_answer") and any(_UNAIDED.search(q or "") for q in questions):
        problems.append("onboarding reveals the answer, but the strategy must prove the player "
                        "understands without instruction: teach the read, do not show the move")

    # The first 30 seconds: within the bars, and the same numbers as the rest of the design.
    budget = ex.get("first_30s") or {}
    bars = rules.get("first_30s") or {}
    for key, bar in (("first_frame_s", "max_first_frame_s"), ("playable_s", "max_playable_s"),
                     ("first_success_s", "max_first_success_s"), ("retry_s", "max_retry_s")):
        value = budget.get(key)
        if isinstance(value, (int, float)) and bar in bars and value > bars[bar]:
            problems.append(f"experience.first_30s.{key} is {value} s; the bar is {bars[bar]} s")
    session = design.get("session") or {}
    for key, other, where in (("playable_s", session.get("time_to_first_play_s"),
                               "session.time_to_first_play_s"),
                              ("retry_s", ((spec.get("failure") or {}).get("retry") or {})
                               .get("time_to_retry_s"), "failure.retry.time_to_retry_s")):
        if isinstance(other, (int, float)) and budget.get(key) is not None \
                and budget[key] != other:
            problems.append(f"experience.first_30s.{key} is {budget[key]} s but {where} says "
                            f"{other} s")

    # A key the design names is bound somewhere.
    keyboard = any(_bound(a.get("keyboard")) for a in actions.values())
    if not keyboard:
        named = [f"game state {s.get('id')!r} exit {e.get('on')!r}"
                 for s in states.values() for e in s.get("exits") or [] if _KEY.search(e.get("on") or "")]
        if _KEY.search((spec.get("controls") or {}).get("pause") or ""):
            named.append("controls.pause")
        for where in named:
            problems.append(f"{where} names a key, but no MVP action has a keyboard binding")
    return problems

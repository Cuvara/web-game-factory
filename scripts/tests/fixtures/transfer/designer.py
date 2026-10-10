"""A deterministic design-agent stand-in for the knowledge-transfer test: it reads ONLY its request.

argv: <mode> <request> <draft>, as the design module's `agent` author runs a host
(wgf_design/agent.py). It starts from the request's starting draft and writes the draft
file. Its own content plan is naive: it debuts the next new element one unit early, so one
unit after the opening debuts two never-seen elements at once - what a designer does who was
never told why not.

    follow    paces its introductions, and records a decision trace (`knowledge_applied`),
              only when the request's `knowledge` carries the rule held by
              content.introductions_one_at_a_time; otherwise it ships the naive plan
    declare   follow, and also states each later unit's one debut in its `introduces` - a
              design whose units say what they introduce (the transfer test's held build)
    violate   ships the naive plan whatever the request says; on a repair round whose
              problems name that rule, paces (the module's check made it)
    claim     ships the naive plan and claims the rule applied when the request carries it:
              the false trace knowledge.trace_matches_design exists to catch

What it saw is written beside the draft (`seen-<stem>.json`) for the test to read: whether
the request carried the rule, and its revision. It reads nothing but the request: no Factory
file, no earlier run, no other session. Not a test module.
"""

import json
import os
import sys

CHECK = "content.introductions_one_at_a_time"


def ordered(draft):
    units = [u for u in draft["build_spec"]["content"]["units"]
             if isinstance(u, dict) and u.get("tier") != "optional"]
    return sorted(units, key=lambda u: u.get("index") or 0)


def debuts(units):
    """What each unit debuts, as the Factory's rule counts it (its request names the rule's
    checks; the count is the craft's): a unit's non-empty `introduces`, else every element
    and mechanic it shows that no earlier unit named."""
    seen, out = set(), []
    for unit in units:
        named = set(map(str, (unit.get("elements") or []) + (unit.get("mechanics") or [])
                        + (unit.get("introduces") or [])))
        if isinstance(unit.get("introduces"), list) and unit["introduces"]:
            out.append(sorted(set(map(str, unit["introduces"])) - seen))
        else:
            out.append(sorted(named - seen))
        seen |= named
    return out


def naive(draft):
    """In the middle unit after the opening one, debut the next new elements early, so it
    debuts two never-seen elements at once. (unit id, [elements moved])."""
    units = ordered(draft)
    news = debuts(units)
    middle = len(units) // 2
    for position in sorted(range(1, len(units) - 1), key=lambda p: abs(p - middle)):
        own = len(news[position])
        # what later units debut as elements (an element moves; a mechanic does not) - never
        # the last debut of all, which the content's own bars want late
        later = [e for n in news[position + 1:-1] for e in n
                 if any(e in (u.get("elements") or []) for u in units[position + 1:])]
        final = [e for n in news if n for e in n][-1:]
        later = [e for e in later if e not in final]
        if own < 2 and len(later) >= 2 - own:
            moved = later[:2 - own]
            units[position].setdefault("elements", []).extend(moved)
            return units[position]["id"], moved
    raise SystemExit("designer: no unit to debut an element early in")


def pace(draft):
    """After the opening unit, keep each unit's first debut; an extra debut leaves the unit
    and is met first where it next appears. [unit ids changed]."""
    changed = []
    while True:
        units = ordered(draft)
        found = next(((unit, new) for position, (unit, new) in
                      enumerate(zip(units, debuts(units)))
                      if position and len(new) > 1
                      and any(e in (unit.get("elements") or []) for e in new[1:])), None)
        if found is None:
            return changed
        unit, new = found
        extra = [e for e in new[1:] if e in (unit.get("elements") or [])]
        unit["elements"] = [e for e in unit["elements"] if e not in extra]
        if isinstance(unit.get("introduces"), list):
            unit["introduces"] = [e for e in unit["introduces"] if e not in extra]
            if not unit["introduces"]:
                del unit["introduces"]
        changed.append(unit["id"])


def declare(draft):
    """Every unit after the opening one that debuts exactly one of its own elements states it
    in `introduces` (a unit that states introductions already is left as it is)."""
    units = ordered(draft)
    for position, (unit, new) in enumerate(zip(units, debuts(units))):
        if position and len(new) == 1 and not unit.get("introduces") \
                and new[0] in (unit.get("elements") or []):
            unit["introduces"] = list(new)


def main():
    mode, request_path, draft_path = sys.argv[1:4]
    with open(request_path, encoding="utf-8") as handle:
        request = json.load(handle)
    draft = request["starting_draft"]
    rules = (request.get("knowledge") or {}).get("rules") or []
    rule = next((r for r in rules if any(str(c).endswith(":" + CHECK)
                                         for c in r.get("checks") or [])), None)
    problems = " ".join((request.get("repair") or {}).get("problems") or [])
    moved_unit, moved = naive(draft)
    trace = None
    if rule is not None and (mode in ("follow", "declare")
                             or (mode == "violate" and CHECK in problems)):
        paced = pace(draft)
        trace = {"rule": rule["id"], "revision": rule.get("revision"), "applied": True,
                 "where": paced, "how": "each unit after the opening debuts one element: "
                                        f"{', '.join(moved)} each met first in a unit of "
                                        "its own",
                 "verified_by": list(rule["checks"])}
    elif rule is not None and mode == "claim":
        trace = {"rule": rule["id"], "revision": rule.get("revision"), "applied": True,
                 "where": [moved_unit], "how": "claimed: introductions are paced",
                 "verified_by": list(rule["checks"])}
    if mode == "declare" and trace is not None:
        declare(draft)
    if trace is not None:
        draft["knowledge_applied"] = [{k: v for k, v in trace.items() if v is not None}]
    stem = os.path.basename(draft_path)[:-len(".draft.json")]
    with open(os.path.join(os.path.dirname(draft_path), f"seen-{stem}.json"), "w",
              encoding="utf-8") as handle:
        json.dump({"mode": mode, "rule": rule and {k: rule.get(k) for k in (
                   "id", "revision", "version", "domain", "principle", "level", "checks")},
                   "rules": len(rules), "moved": [moved_unit, moved],
                   "paced": bool(trace and mode != "claim"),
                   "repair": bool(request.get("repair"))}, handle, indent=2)
    with open(draft_path, "w", encoding="utf-8") as handle:
        json.dump(draft, handle, indent=2)


if __name__ == "__main__":
    main()

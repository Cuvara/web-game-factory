#!/usr/bin/env python3
"""Show and advance an entity's lifecycle state.

The machines in core/lifecycle/ say which transitions exist and what must be true to take
one. Until now nothing enforced that: `state.json` was updated by hand as the last step of a
command's procedure, which means the edge list was advisory and a state could move anywhere.

This is the enforcement. It refuses an edge the machine does not have, refuses an edge whose
guards are not satisfied, refuses a gated edge without its decision record, and refuses a
decision record on G4, G6 or G7 that was not made by a human. The last of those duplicates a
constraint decision-record.schema.json already carries, deliberately: killing a concept,
publishing, and spending money are the three that cannot be undone, and two independent
checks on them is cheap.

Usage, from the web-game-factory repository root:

    python scripts/wgf-state.py --show neon-drift
    python scripts/wgf-state.py --advance neon-drift --event plan
    python scripts/wgf-state.py --advance neon-drift --event approve \\
        --decision-record decisions/G2-20260902.json
    python scripts/wgf-state.py --advance neon-drift --event abandon \\
        --decision-record decisions/G4-20260916.json --outcome-note "..."

Add --dry-run to see what would be written without writing it.
"""

import argparse
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from wgflib.guards import GuardContext, evaluate_guard  # noqa: E402
from wgflib.hashing import content_hash  # noqa: E402
from wgflib.machine import MachineError, load_gates, load_machine  # noqa: E402
from wgflib.workspace import (  # noqa: E402
    WorkspaceError,
    load_opportunity,
    load_portfolio_config,
    load_title,
)

IRREVERSIBLE = ("G4", "G6", "G7")


class Refused(Exception):
    """The transition is not allowed. The message says which rule refused it."""


def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_entity(entity_id):
    """A title or an opportunity, whichever has that id."""
    try:
        return load_title(entity_id)
    except WorkspaceError:
        return load_opportunity(entity_id)


def check_guards(transition, context):
    """Every guard on the edge, with UNKNOWN treated as a blocker rather than a pass."""
    problems = []
    checks = [(name, False) for name in transition.guards]
    checks += [(name, True) for name in transition.negated_guards]

    for name, negated in checks:
        verdict = evaluate_guard(name, context)
        wanted = not negated
        if verdict.value is None:
            problems.append(
                f"{'NOT ' if negated else ''}{name}: UNKNOWN - {verdict.reason}"
            )
        elif verdict.value is not wanted:
            problems.append(f"{'NOT ' if negated else ''}{name}: {verdict.reason}")
    return problems


def check_decision_record(entity, transition, relative_path):
    """Validate the decision-record authorizing a gated transition."""
    gate = transition.gate
    if relative_path is None:
        raise Refused(
            f"{transition.label} crosses gate {gate}; supply --decision-record. "
            f"Every gate emits one, and it is what pins the decision to what was decided on."
        )

    path = os.path.join(entity.directory, relative_path)
    if not os.path.exists(path):
        raise Refused(f"no decision record at {path}")

    with open(path, encoding="utf-8") as handle:
        record = json.load(handle)

    if record.get("gate_id") != gate:
        raise Refused(
            f"{relative_path} records gate {record.get('gate_id')}, not {gate}"
        )

    expected = f"{transition.source} -> {transition.target}"
    if record.get("transition") not in (None, expected):
        raise Refused(
            f"{relative_path} authorizes {record.get('transition')!r}, not {expected!r}"
        )

    mode = (record.get("decided_by") or {}).get("mode")
    if gate in IRREVERSIBLE and mode != "human":
        raise Refused(
            f"{gate} is irreversible and never auto-approves, but {relative_path} records "
            f"decided_by.mode={mode!r}"
        )

    if gate == "G7" and record.get("spend_ceiling_usd") is None:
        raise Refused(f"{gate} spends money and needs an explicit spend_ceiling_usd")

    stale = stale_subjects(entity, record)
    if stale:
        raise Refused(
            f"{relative_path} pins artifacts that have since changed: {'; '.join(stale)}. "
            f"A decision made against content that has moved is not a decision about this "
            f"content."
        )

    return record


def stale_subjects(entity, record):
    """Subjects whose recorded hash no longer reproduces against the file on disk."""
    index = {}
    for name in os.listdir(entity.directory):
        if not name.endswith(".json"):
            continue
        with open(os.path.join(entity.directory, name), encoding="utf-8") as handle:
            data = json.load(handle)
        if isinstance(data, dict) and isinstance(data.get("provenance"), dict):
            index[data["provenance"].get("artifact_id")] = data

    stale = []
    for subject in record.get("subject") or []:
        target = index.get(subject.get("artifact_id"))
        if target is None:
            continue
        if subject.get("content_hash") != content_hash(target):
            stale.append(subject["artifact_id"])
    return stale


def choose_transition(machine, state_id, event, target, context):
    """Pick the edge to take when an event names more than one.

    `rank` leaves portfolio:scored for both `shortlisted` and `rejected`; which one is the
    machine's answer, read from the guards, not the caller's preference. An explicit --to
    settles it when the guards do not.
    """
    candidates = machine.transition(state_id, event)
    if target:
        matching = [t for t in candidates if t.target == target]
        if not matching:
            raise Refused(
                f"{event} does not lead to {target!r}; it leads to "
                f"{', '.join(t.target for t in candidates)}"
            )
        return matching[0]

    if len(candidates) == 1:
        return candidates[0]

    clear = [t for t in candidates if not check_guards(t, context)]
    if len(clear) == 1:
        return clear[0]
    raise Refused(
        f"{event} leads to {', '.join(t.target for t in candidates)} and "
        f"{len(clear)} of them have all guards satisfied. Name one with --to."
    )


def advance(entity, machine, transition, record_path, outcome_note, timestamp):
    """Produce the new state document. Pure - writing is the caller's."""
    state = json.loads(json.dumps(entity.state))  # a copy; the original stays readable
    history = state.setdefault("history", [])

    if history:
        current = history[-1]
        if current.get("exited_at"):
            raise Refused(
                "the last history entry is already closed; state.json and its history "
                "disagree about where this entity is"
            )
        current["exited_at"] = timestamp
        current["event"] = transition.event
        if transition.gate:
            current["gate"] = transition.gate
            current["decision_record"] = record_path

    visit = {"state": transition.target, "entered_at": timestamp}
    repeats = sum(1 for entry in history if entry["state"] == transition.target)
    if repeats:
        visit["iteration"] = repeats + 1
    history.append(visit)

    state["current_state"] = transition.target
    state["entered_current_state_at"] = timestamp
    terminal = machine.is_terminal(transition.target)
    state["terminal"] = terminal

    if terminal:
        if not outcome_note:
            raise Refused(
                f"{transition.target} is terminal, and the schema requires an outcome. "
                f"Supply --outcome-note: a terminal state with no recorded result is work "
                f"whose ending nobody wrote down."
            )
        outcome = state.setdefault("outcome", {})
        outcome["note"] = outcome_note
        started = history[0].get("entered_at")
        if started and "elapsed_days" not in outcome:
            begin = datetime.datetime.fromisoformat(started.replace("Z", "+00:00"))
            end = datetime.datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            outcome["elapsed_days"] = (end - begin).days

    return state


def show(entity, machine):
    state_id = entity.state["current_state"]
    print(f"{entity.machine}:{state_id}   {entity.id}")
    print(f"entered      {entity.state.get('entered_current_state_at')}")
    print(f"machine      {machine.name} v{entity.state.get('machine_version')} "
          f"(file is v{machine.version})")

    if entity.state.get("machine_version") != machine.version:
        print("             NOTE the machine file has moved on from the version this "
              "entity started under")

    artifacts = entity.state.get("artifacts") or {}
    if artifacts:
        print(f"artifacts    {', '.join(sorted(artifacts))}")

    if machine.is_terminal(state_id):
        print("\nterminal - nothing leaves this state")
        return 0

    print("\nevents available here:")
    for transition in machine.transitions_from(state_id):
        gate = f"  [gate {transition.gate}]" if transition.gate else ""
        guards = transition.guards + [f"NOT {g}" for g in transition.negated_guards]
        print(f"  {transition.event:16} -> {transition.target}{gate}")
        if guards:
            print(f"                   guards: {', '.join(guards)}")
    print("\nRun wgf-guard.py to evaluate them.")
    return 0


def main():
    parser = argparse.ArgumentParser(description="Show and advance lifecycle state.")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--show", metavar="ID")
    action.add_argument("--advance", metavar="ID")
    parser.add_argument("--event", metavar="NAME")
    parser.add_argument("--to", metavar="STATE", help="disambiguate an event with two targets")
    parser.add_argument("--decision-record", metavar="PATH",
                        help="relative to the entity directory")
    parser.add_argument("--outcome-note", metavar="TEXT", help="required entering a terminal state")
    parser.add_argument("--game-repo", metavar="PATH")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    entity_id = args.show or args.advance
    try:
        entity = load_entity(entity_id)
        machine = load_machine(entity.machine)
    except (WorkspaceError, MachineError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if args.show:
        return show(entity, machine)

    if not args.event:
        parser.error("--advance needs --event")

    config = load_portfolio_config()
    context = GuardContext(entity, config=config, game_repo=args.game_repo)
    state_id = entity.state["current_state"]

    try:
        if machine.is_terminal(state_id):
            raise Refused(f"{entity.machine}:{state_id} is terminal; nothing leaves it")

        transition = choose_transition(machine, state_id, args.event, args.to, context)

        problems = check_guards(transition, context)
        if problems:
            raise Refused(
                f"{transition.label} is blocked:\n  - " + "\n  - ".join(problems)
            )

        if transition.gate:
            check_decision_record(entity, transition, args.decision_record)

        timestamp = now_iso()
        updated = advance(
            entity, machine, transition, args.decision_record, args.outcome_note, timestamp
        )
    except (Refused, MachineError) as exc:
        print(f"REFUSED  {exc}", file=sys.stderr)
        return 1

    payload = json.dumps(updated, indent=2, ensure_ascii=False) + "\n"

    if args.dry_run:
        print(f"would write {entity.state_path}\n")
        print(payload)
        return 0

    with open(entity.state_path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(payload)

    gate = f" through gate {transition.gate}" if transition.gate else ""
    print(f"{entity.id}: {transition.source} -> {transition.target}{gate}  at {timestamp}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

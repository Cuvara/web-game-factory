"""Read the lifecycle machines in core/lifecycle/ as data.

The machine files are the single enumeration of what states exist and which transitions are
legal. Everything that advances a lifecycle reads them from here rather than restating them,
because a second copy of the edge list is a second thing to get wrong.

This module answers structural questions only - what edges leave a state, which guards they
carry, whether a gate sits on one. It does not evaluate guards (wgflib/guards.py) and does
not write state (wgf-state.py).
"""

import os

from . import paths
from .yamllite import load_file

__all__ = ["Machine", "Transition", "load_machine", "load_gates", "MACHINES", "MachineError"]

MACHINES = ("portfolio", "title", "release", "platform-publication")


class MachineError(ValueError):
    """The machine file does not describe what was asked of it."""


class Transition:
    """One edge out of a state."""

    __slots__ = ("source", "event", "target", "kind", "role", "guards", "negated_guards",
                 "gate", "outputs", "note")

    def __init__(self, source, entry, state_gate=None):
        self.source = source
        self.event = entry.get("event")
        self.target = entry.get("to")
        self.kind = entry.get("kind")
        self.role = entry.get("role")
        self.guards = list(entry.get("guard") or [])
        self.negated_guards = list(entry.get("guard_negated") or [])
        # A gate is declared on the edge in six cases and on the state in one: G4 sits on
        # `prototype-review`, because all three of its outcomes are the same decision. An
        # edge leaving a gated state is gated unless it says otherwise.
        self.gate = entry.get("gate") or state_gate
        self.outputs = list(entry.get("outputs") or [])
        self.note = entry.get("note")

    @property
    def label(self):
        return f"{self.source} --{self.event}--> {self.target}"

    def __repr__(self):
        return f"<Transition {self.label}>"


class Machine:
    def __init__(self, name, data):
        self.name = name
        self.data = data
        self.version = data.get("version")
        self.entity = data.get("entity")
        self.parent = data.get("parent")
        self.initial = data.get("initial")
        self.terminals = list(data.get("terminals") or [])
        self.guards = data.get("guards") or {}
        self.states = data.get("states") or {}
        self.global_transitions = data.get("global_transitions") or []

    def state(self, state_id):
        if state_id not in self.states:
            known = ", ".join(sorted(self.states))
            raise MachineError(
                f"{self.name} has no state {state_id!r}. States are: {known}"
            )
        return self.states[state_id]

    def is_terminal(self, state_id):
        return state_id in self.terminals

    def transitions_from(self, state_id):
        """Every edge leaving `state_id`, including the machine-wide ones that apply to it."""
        entry = self.state(state_id)
        state_gate = entry.get("gate")
        found = [
            Transition(state_id, item, state_gate)
            for item in (entry.get("transitions") or [])
        ]

        # Machine-wide edges - `pause` from anywhere, `regression` from live - are not part
        # of the gated decision the state exists for, so they do not inherit its gate.

        for item in self.global_transitions:
            applies = item.get("from")
            if isinstance(applies, list):
                if state_id in applies:
                    found.append(Transition(state_id, item))
            elif applies == "non-terminal":
                if not self.is_terminal(state_id):
                    found.append(Transition(state_id, item))
            elif applies in (None, "any", "*"):
                found.append(Transition(state_id, item))
            else:
                raise MachineError(
                    f"{self.name}: global transition {item.get('event')!r} has an "
                    f"unrecognised `from`: {applies!r}"
                )
        return found

    def transition(self, state_id, event):
        matches = [t for t in self.transitions_from(state_id) if t.event == event]
        if not matches:
            events = ", ".join(sorted({t.event for t in self.transitions_from(state_id)}))
            raise MachineError(
                f"{self.name}:{state_id} has no transition {event!r}. "
                f"Available: {events or '(none - terminal state)'}"
            )
        return matches

    def guard_description(self, name):
        entry = self.guards.get(name) or {}
        return entry.get("description", "")

    def guard_implementation(self, name):
        entry = self.guards.get(name) or {}
        return entry.get("implemented_by")

    def role_for(self, state_id):
        return self.state(state_id).get("role")

    def procedure_for(self, state_id):
        procedure = self.state(state_id).get("procedure")
        return os.path.join(paths.LIFECYCLE, procedure) if procedure else None


_cache = {}


def load_machine(name):
    if name not in MACHINES:
        raise MachineError(f"unknown machine {name!r}; expected one of {', '.join(MACHINES)}")
    if name not in _cache:
        path = os.path.join(paths.LIFECYCLE, f"{name}.machine.yaml")
        if not os.path.exists(path):
            raise MachineError(f"{paths.display(path)} is missing")
        _cache[name] = Machine(name, load_file(path))
    return _cache[name]


def load_gates():
    """core/lifecycle/gates.yaml, with each gate's defaults already folded in."""
    data = load_file(os.path.join(paths.LIFECYCLE, "gates.yaml"))
    defaults = data.get("defaults") or {}
    gates = {}
    for gate_id, gate in (data.get("gates") or {}).items():
        merged = dict(defaults)
        merged.update(gate)
        gates[gate_id] = merged
    return gates

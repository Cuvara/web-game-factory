"""The decision-record a gate checkpoint emits: the workflow tier's answer, in the lifecycle
tier's vocabulary.

A checkpoint (checkpoint.py) records a choice the way the engine records any decision - in
state and as a DECISION_RECORDED event - in the workflow's own words: `approve`, `reject`,
`pass`, `iterate`, `kill`, decided by `human` or `automation`. The lifecycle machines and
decision-record.schema.json speak another vocabulary: `approved`, `rejected`, `pass`,
`iterate`, `abandon`, and `decided_by: {role, mode: human | auto-approved}`, on a named
transition, with the subject pinned by content hash. This module is the one translation
between the two, so that every gate a workflow decides leaves the artifact CLAUDE.md
promises: a schema-valid decision-record pinning exactly what was decided on.

    record = decisions.build_record(gate="G4", choice="kill", inputs=inputs,
                                    decided_by="human", mode=None, note="...",
                                    decided_at=entry["decided_at"], sequence=3,
                                    project_id="neon-drift")

Only this module and gates.yaml know the vocabulary; the engine knows neither.
"""

import re

from .. import provenance
from ..machine import MachineError, load_gates, load_machine

__all__ = ["ARTIFACT_TYPE", "CHOICES", "DecisionRecordError", "vocabulary", "mode_of",
           "transition_for", "build_record", "output_name"]

ARTIFACT_TYPE = "decision-record"


class DecisionRecordError(ValueError):
    """A decision that cannot be written as a schema-valid decision-record."""


# THE mapping, workflow choice -> (decision-record `decision`, lifecycle machine event).
# The event is the machine edge the decision authorizes (core/lifecycle/*.machine.yaml);
# None where no edge corresponds (a deferral decides nothing yet). `kill` is gates.yaml's
# `abandon` (G4 outcomes: pass, iterate, abandon). A choice missing here has no
# decision-record meaning, and a checkpoint that must emit a record refuses it.
CHOICES = {
    "approve": ("approved", "approve"),
    "reject": ("rejected", "reject"),
    "pass": ("pass", "pass"),
    "iterate": ("iterate", "iterate"),
    "kill": ("abandon", "abandon"),
    "abandon": ("abandon", "abandon"),
    "defer": ("deferred", None),
    "accept_partial": ("accept_partial", None),
}

# decided_by.mode. A decision is `human` only when a person gave it: recorded as decided by
# `human` and not by a timeout. Anything else - `automation`, a timeout, an unfamiliar
# identifier - is `auto-approved`: claiming less than was established, never more.
HUMAN, AUTO = "human", "auto-approved"

_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def vocabulary(choice):
    """(decision, event) for a workflow choice; DecisionRecordError if it has none."""
    try:
        return CHOICES[choice]
    except KeyError:
        raise DecisionRecordError(
            f"choice {choice!r} has no decision-record meaning; known choices are "
            f"{', '.join(sorted(CHOICES))} (wgflib/workflow/decisions.py)")


def mode_of(decided_by, mode=None):
    """decided_by.mode for an engine decision entry's `decided_by` and `mode`."""
    return HUMAN if decided_by == "human" and not mode else AUTO


def _gate(gate_id):
    gates = load_gates()
    if gate_id not in gates:
        raise DecisionRecordError(f"{gate_id!r} is not a gate core/lifecycle/gates.yaml defines")
    return gates[gate_id]


def transition_for(gate_id, event, gate=None):
    """(machine, "source -> target") the decision authorizes.

    The source is the state named on the left of the gate's `on_transition` in gates.yaml;
    the target is the machine's own edge from there on `event` that carries this gate. With
    no such edge (a deferral), the gate's `on_transition` as written."""
    gate = gate or _gate(gate_id)
    machine_name = gate.get("machine")
    written = str(gate.get("on_transition") or "").strip()
    source = written.split("->", 1)[0].strip()
    if not machine_name or not source:
        raise DecisionRecordError(f"{gate_id}: gates.yaml names no machine or on_transition")
    if event is None:
        return machine_name, written
    try:
        machine = load_machine(machine_name)
        edges = [t for t in machine.transitions_from(source)
                 if t.event == event and t.gate == gate_id]
    except MachineError as exc:
        raise DecisionRecordError(f"{gate_id}: {exc}")
    if not edges:
        raise DecisionRecordError(
            f"{gate_id}: {machine_name}:{source} has no `{event}` edge through {gate_id}")
    return machine_name, f"{source} -> {edges[0].target}"


def output_name(step_id):
    """The run-local artifact name a checkpoint's record is stored under: one per checkpoint,
    so each gate's records are versions of their own artifact, not of one shared name."""
    slug = re.sub(r"[^a-z0-9-]+", "-", str(step_id).lower()).strip("-")
    return f"{ARTIFACT_TYPE}-{slug}"[:128] if slug else ARTIFACT_TYPE


def _title_id(inputs, project_id):
    """The title the decision is about: the one its subject artifacts name, else the run's
    project id."""
    refs = getattr(inputs, "refs", None) or {}
    for artifact_type in sorted(refs):
        content = inputs.load(artifact_type)
        source = content.get("provenance") if isinstance(content, dict) else None
        title = source.get("title_id") if isinstance(source, dict) else None
        if isinstance(title, str) and title:
            return title
    return project_id if isinstance(project_id, str) and project_id else None


def build_record(*, gate, choice, inputs, decided_by, mode, note, decided_at, sequence,
                 project_id=None, required=None):
    """A sealed, schema-valid decision-record for `choice` at `gate`.

    `inputs` is the checkpoint's StepInputs: `provenance.inputs` pins every artifact it
    consumed (the engine's lineage check demands exactly that), and `subject` pins those of
    them the gate is decided on (`required`, gates.yaml required_artifacts). `decided_at`
    is the engine's clock when the decision was recorded; it is also `produced_at`."""
    spec = _gate(gate)
    decision, event = vocabulary(choice)
    machine, transition = transition_for(gate, event, spec)
    who = mode_of(decided_by, mode)
    if spec.get("irreversible") and who != HUMAN:
        raise DecisionRecordError(f"{gate} is irreversible: only a person decides it")

    pins = provenance.pin_inputs(inputs)
    wanted = set(required if required is not None else spec.get("required_artifacts") or [])
    subject = [pin for pin in pins if pin["artifact_type"] in wanted] or pins
    if not subject:
        raise DecisionRecordError(
            f"{gate}: nothing the checkpoint consumed can be pinned by hash, so there is no "
            f"subject to record the decision against")

    title = _title_id(inputs, project_id)
    scope = title if isinstance(title, str) and _SLUG.match(title) else "run"
    approvers = spec.get("approvers") or []
    role = approvers[0] if approvers and isinstance(approvers[0], str) else "portfolio-owner"
    decided = {"role": role, "mode": who}
    if isinstance(decided_by, str) and decided_by:
        decided["identifier"] = decided_by

    rationale = note if isinstance(note, str) and note.strip() else (
        f"{choice} at {gate} ({spec.get('label') or 'gate'}), decided by "
        f"{decided_by or 'unknown'} ({who}); no rationale was given with the decision")

    record = {"provenance": provenance.build(
        ARTIFACT_TYPE,
        # One scope per gate, so G2's, G3's and G4's records on one day never share an id.
        artifact_id=provenance.artifact_id(ARTIFACT_TYPE, f"{scope}-{gate.lower()}",
                                           decided_at, sequence),
        produced_by=provenance.producer(role, "human" if who == HUMAN else "automation"),
        produced_at=decided_at,
        inputs=pins,
        title_id=title,
        status="final")}
    record.update({
        "gate_id": gate,
        "machine": machine,
        "transition": transition,
        "subject": subject,
        "decision": decision,
        "decided_by": decided,
        "decided_at": decided_at,
        "rationale": rationale,
    })
    return provenance.seal(record)

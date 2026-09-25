"""The human checkpoint: a built-in step type that waits for a decision.

It is the one step type the kernel ships, because pausing for a person is a property of the
workflow, not of any business module. It carries no judgement of its own:

    - id: strategy-review
      type: human-checkpoint
      inputs: [title-strategy]        # what the gate is decided on (see below)
      with:
        gate: G2                      # optional; ties the checkpoint to a lifecycle gate
        choices: [approve, reject]    # default
        prompt: Approve the title strategy before design starts?
      on:
        reject: $end

With no decision recorded, it returns WAITING_FOR_HUMAN and the run parks as WAITING.
`wgf <cmd> --resume <run> --decision approve` records one and re-executes it; `approve`
(or any choice that does not stop the run) is SUCCESS with that choice as the route.
`reject` and `kill` stop the run: BLOCKED with that choice as the route, so an unrouted one
blocks the run instead of proceeding, and one routed to `$end` ends it - G4's `kill` - with
the gate recorded as not passed, which the engine will not let a later step step over.

A checkpoint tied to a gate is decided on what that gate requires: every artifact type in
the gate's `required_artifacts` (core/lifecycle/gates.yaml) must be among the step's
`inputs` and held by the run, else it returns WAITING_FOR_INPUT naming them - nobody is
asked to decide on evidence the run does not have. The engine re-checks each input's
checksum and contract before the checkpoint runs, as for any step.

A gate may be auto-approved only when the run allows it (`auto_approve` in the run's
environment) AND the gate is reversible per core/lifecycle/gates.yaml. G4, G6 and G7 are
irreversible and never auto-approve here either, whatever the run asks for; that mirrors the
rule decision-record.schema.json and wgf-state.py already enforce.

A reversible gate may also approve itself on a timeout: when the run's params carry a
window for it (`timeout_auto_approve`, snapshotted from factory.checkpoints when the run
started) and the visit has waited at least that long - from `context.waiting_since`, which
the engine records from its own clock when the visit first waits, to `context.now`. The
approval is recorded through `context.record_decision` exactly like a person's (a
DECISION_RECORDED event, `decided_by: automation`, `mode: timeout`) before the step returns
SUCCESS route `approve`. It happens only when the checkpoint executes - on `wgf resume` -
never when a run is merely looked at.

A checkpoint that names a gate AND declares `outputs: [decision-record]` emits a
schema-valid decision-record (wgflib/workflow/decisions.py) with every decided outcome -
a person's choice, an installation's auto-approval, a timeout approval; SUCCESS and BLOCKED
alike, so a rejection or a kill is on record as an artifact too - pinning by content hash
exactly the inputs it consumed. Nothing is emitted while it waits. A decision that cannot be
written as a record (a choice with no decision-record meaning, nothing pinnable to decide
on) fails the step, not retryably: an unauditable gate does not let the run past it.
"""

import datetime

from ..machine import load_gates
from . import decisions
from .model import ArtifactOutput, StepResult, parse_timestamp
from .step import WorkflowStep

__all__ = ["HumanCheckpointStep", "irreversible_gates", "known_gates", "is_irreversible",
           "may_auto_approve", "required_artifacts", "timeout_window", "timeout_due",
           "STOP_CHOICES", "TIMEOUT_MODE"]

# Used only if gates.yaml cannot be read; the file is authoritative.
_IRREVERSIBLE_FALLBACK = ("G4", "G6", "G7")

# Choices that stop the run instead of letting it continue: BLOCKED, routed by the choice.
STOP_CHOICES = ("reject", "kill")

# The `mode` of a decision the checkpoint records itself when a timeout window has run out,
# and the choice it records.
TIMEOUT_MODE = "timeout"
_TIMEOUT_CHOICE = "approve"


def irreversible_gates():
    try:
        gates = load_gates()
    except Exception:
        return set(_IRREVERSIBLE_FALLBACK)
    return {gate_id for gate_id, gate in gates.items() if gate.get("irreversible")} or set(
        _IRREVERSIBLE_FALLBACK
    )


def known_gates():
    """Every gate id gates.yaml defines; empty when it cannot be read."""
    try:
        return set(load_gates())
    except Exception:
        return set()


def _canonical(gate):
    return gate.strip().upper() if isinstance(gate, str) else gate


def is_irreversible(gate):
    """True for G4/G6/G7 however the workflow spells them (`g4`, ` G4`)."""
    return _canonical(gate) in {_canonical(g) for g in irreversible_gates()}


def may_auto_approve(gate, allowed):
    """Only a gate gates.yaml knows by exactly that id, that the run allows, and that is
    reversible. A misspelt or unknown gate is never auto-approved: fail closed, a person
    answers it."""
    return (isinstance(gate, str) and gate in set(allowed or ())
            and gate in known_gates() and not is_irreversible(gate))


def required_artifacts(gate):
    """The artifact types gates.yaml says `gate` is decided on: [] for no gate or one
    gates.yaml does not define, None when gates.yaml cannot be read (fail closed)."""
    if not gate:
        return []
    try:
        gates = load_gates()
    except Exception:
        return None
    wanted = _canonical(gate)
    for gate_id, spec in gates.items():
        if _canonical(gate_id) == wanted:
            return [t for t in (spec.get("required_artifacts") or []) if isinstance(t, str)]
    return []


def timeout_window(gate, environment):
    """Seconds the run lets `gate` wait before it approves itself, or None.

    Only from the run's own params (`timeout_auto_approve`, snapshotted at start), only for
    a gate gates.yaml defines by exactly that id, and never for an irreversible one."""
    windows = (environment or {}).get("timeout_auto_approve")
    if not isinstance(windows, dict) or not isinstance(gate, str):
        return None
    seconds = windows.get(gate)
    if isinstance(seconds, bool) or not isinstance(seconds, int) or seconds <= 0:
        return None
    if gate not in known_gates() or is_irreversible(gate):
        return None
    return seconds


def timeout_due(gate, environment, waiting_since):
    """The instant `gate`, waiting since `waiting_since`, becomes eligible for timeout
    approval (an aware datetime), or None when it never does."""
    seconds = timeout_window(gate, environment)
    since = parse_timestamp(waiting_since)
    if seconds is None or since is None:
        return None
    return since + datetime.timedelta(seconds=seconds)


def stamp(moment):
    """An aware datetime in the engine's timestamp format."""
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


class HumanCheckpointStep(WorkflowStep):
    type = "human-checkpoint"
    # Holds the run for a decision: the engine will not start a later step of the run
    # past one of these that has not passed (engine._refuse_unmet_upstream).
    gates_the_run = True

    def execute(self, inputs, context):
        gate = self.params.get("gate")
        choices = list(self.params.get("choices") or ["approve", "reject"])
        prompt = self.params.get("prompt") or f"Decision required at {self.id}"

        required = required_artifacts(gate)
        if required is None:
            return StepResult.waiting_for_input(
                f"{gate}: core/lifecycle/gates.yaml cannot be read, so what the gate is "
                f"decided on is unknown. {prompt}", gate=gate)
        held = set((getattr(inputs, "refs", None) or {}).keys())
        missing = [t for t in required if t not in held]
        if missing:
            return StepResult.waiting_for_input(
                f"{gate} is decided on {', '.join(missing)}, which this run does not hold "
                f"(gates.yaml required_artifacts; the checkpoint lists them as inputs). "
                f"{prompt}", gate=gate, missing=missing)

        decision = context.decision
        if decision is not None:
            choice = decision.get("decision")
            if choice not in choices:
                return StepResult.waiting_for_human(
                    f"{choice!r} is not one of {', '.join(choices)}. {prompt}",
                    choices=choices, gate=gate,
                )
            if is_irreversible(gate) and decision.get("decided_by") != "human":
                return StepResult.waiting_for_human(
                    f"{gate} is irreversible and needs a human decision. {prompt}",
                    choices=choices, gate=gate,
                )
            data = {"gate": gate, "decided_by": decision.get("decided_by")}
            if decision.get("mode"):
                data["mode"] = decision["mode"]
            record, problem = self._record(
                gate, choice, inputs, context, decided_by=decision.get("decided_by"),
                mode=decision.get("mode"), note=decision.get("note"),
                decided_at=decision.get("decided_at") or context.now)
            if problem:
                return problem
            if choice in STOP_CHOICES:
                verb = "rejected" if choice == "reject" else "killed"
                where = self.id + (f" ({gate})" if gate else "")
                return StepResult(
                    "BLOCKED", route=choice, artifacts=record,
                    message=f"{verb} at {where}"
                    + (f": {decision['note']}" if decision.get("note") else ""),
                    data=dict(data, decision=choice),
                )
            return StepResult.success(record, route=choice, message=f"{choice} at {self.id}",
                                      **data)

        auto = context.environment.get("auto_approve") or []
        if not isinstance(auto, (list, tuple)):
            auto = []
        if may_auto_approve(gate, auto):
            context.logger.info("auto-approved", gate=gate)
            record, problem = self._record(
                gate, "approve", inputs, context, decided_by="automation", mode=None,
                note=f"{gate} auto-approved: the run was started with {gate} in its "
                     f"auto_approve list (factory.checkpoints.auto_approve, or a mock run's "
                     f"own reversible gates)",
                decided_at=context.now)
            if problem:
                return problem
            return StepResult.success(record, route="approve", message=f"{gate} auto-approved",
                                      gate=gate, decided_by="automation")

        since = getattr(context, "waiting_since", None)
        due = timeout_due(gate, context.environment, since)
        if due is not None and _TIMEOUT_CHOICE in choices:
            now = parse_timestamp(getattr(context, "now", None))
            record = getattr(context, "record_decision", None)
            if now is not None and now >= due and callable(record):
                window = timeout_window(gate, context.environment)
                note = (f"{gate} approved on timeout: unanswered since {since}, window "
                        f"{window}s, eligible since {stamp(due)}")
                # Recorded like a person's decision, and before the result: the approval is
                # on record (DECISION_RECORDED) whatever happens to this execution.
                entry = record(_TIMEOUT_CHOICE, decided_by="automation", note=note,
                               mode=TIMEOUT_MODE) or {}
                context.logger.info("timeout-approved", gate=gate, waiting_since=since,
                                    window_seconds=window)
                artifacts, problem = self._record(
                    gate, _TIMEOUT_CHOICE, inputs, context, decided_by="automation",
                    mode=TIMEOUT_MODE, note=note,
                    decided_at=entry.get("decided_at") or context.now)
                if problem:
                    return problem
                return StepResult.success(artifacts, route=_TIMEOUT_CHOICE, message=note,
                                          gate=gate, decided_by="automation",
                                          mode=TIMEOUT_MODE)
            prompt += (f" (unanswered, {gate} approves itself on the first `wgf resume` at or "
                       f"after {stamp(due)})")
        return StepResult.waiting_for_human(prompt, choices=choices, gate=gate)

    def _record(self, gate, choice, inputs, context, *, decided_by, mode, note, decided_at):
        """([ArtifactOutput], None) - the decision-record this decision emits, or [] when the
        checkpoint names no gate or does not declare one as an output - or (None, a FAILED
        result) when the decision cannot be written as a valid record."""
        declared = getattr(self.definition, "outputs", None) or ()
        if not gate or decisions.ARTIFACT_TYPE not in declared:
            return [], None
        try:
            record = decisions.build_record(
                gate=gate, choice=choice, inputs=inputs, decided_by=decided_by, mode=mode,
                note=note, decided_at=decided_at, sequence=context.execution,
                project_id=context.project_id, required=required_artifacts(gate))
        except (decisions.DecisionRecordError, ValueError) as exc:
            return None, StepResult.failed(
                f"{gate}: the decision {choice!r} cannot be recorded as a decision-record: "
                f"{exc}", retryable=False, gate=gate)
        return [ArtifactOutput(decisions.ARTIFACT_TYPE, record,
                               name=decisions.output_name(self.id))], None


def register(registry):
    registry.register(HumanCheckpointStep.type, HumanCheckpointStep)

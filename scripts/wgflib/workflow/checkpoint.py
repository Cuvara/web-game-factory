"""The human checkpoint: a built-in step type that waits for a decision.

It is the one step type the kernel ships, because pausing for a person is a property of the
workflow, not of any business module. It carries no judgement of its own:

    - id: strategy-review
      type: human-checkpoint
      with:
        gate: G2                      # optional; ties the checkpoint to a lifecycle gate
        choices: [approve, reject]    # default
        prompt: Approve the title strategy before design starts?
      on:
        reject: $end

With no decision recorded, it returns WAITING_FOR_HUMAN and the run parks as WAITING.
`wgf <cmd> --resume <run> --decision approve` records one and re-executes it; `approve`
(or any choice other than `reject`) is SUCCESS with that choice as the route, `reject` is
BLOCKED with route `reject`, so an unrouted rejection stops the run instead of proceeding.

A gate may be auto-approved only when the run allows it (`auto_approve` in the run's
environment) AND the gate is reversible per core/lifecycle/gates.yaml. G4, G6 and G7 are
irreversible and never auto-approve here either, whatever the run asks for; that mirrors the
rule decision-record.schema.json and wgf-state.py already enforce.
"""

from ..machine import load_gates
from .model import StepResult
from .step import WorkflowStep

__all__ = ["HumanCheckpointStep", "irreversible_gates", "known_gates", "is_irreversible",
           "may_auto_approve"]

# Used only if gates.yaml cannot be read; the file is authoritative.
_IRREVERSIBLE_FALLBACK = ("G4", "G6", "G7")


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


class HumanCheckpointStep(WorkflowStep):
    type = "human-checkpoint"

    def execute(self, inputs, context):
        gate = self.params.get("gate")
        choices = list(self.params.get("choices") or ["approve", "reject"])
        prompt = self.params.get("prompt") or f"Decision required at {self.id}"

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
            if choice == "reject":
                return StepResult(
                    "BLOCKED", route="reject",
                    message=f"rejected at {self.id}"
                    + (f": {decision['note']}" if decision.get("note") else ""),
                    data={"gate": gate, "decided_by": decision.get("decided_by")},
                )
            return StepResult.success(route=choice, message=f"{choice} at {self.id}",
                                      gate=gate, decided_by=decision.get("decided_by"))

        auto = context.environment.get("auto_approve") or []
        if not isinstance(auto, (list, tuple)):
            auto = []
        if may_auto_approve(gate, auto):
            context.logger.info("auto-approved", gate=gate)
            return StepResult.success(route="approve", message=f"{gate} auto-approved",
                                      gate=gate, decided_by="automation")

        return StepResult.waiting_for_human(prompt, choices=choices, gate=gate)


def register(registry):
    registry.register(HumanCheckpointStep.type, HumanCheckpointStep)

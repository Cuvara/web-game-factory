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

__all__ = ["HumanCheckpointStep", "irreversible_gates"]

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
            if gate in irreversible_gates() and decision.get("decided_by") != "human":
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

        auto = set(context.environment.get("auto_approve") or [])
        if gate and gate in auto and gate not in irreversible_gates():
            context.logger.info("auto-approved", gate=gate)
            return StepResult.success(route="approve", message=f"{gate} auto-approved",
                                      gate=gate, decided_by="automation")

        return StepResult.waiting_for_human(prompt, choices=choices, gate=gate)


def register(registry):
    registry.register(HumanCheckpointStep.type, HumanCheckpointStep)

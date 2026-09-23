"""Placeholder step implementations, so the whole workflow executes before any module exists.

These do no research, design, development or publishing. Each one emits the artifacts its
step declares, built from the fixtures beside this file, with real provenance: an
artifact id in the canonical shape, the consumed inputs pinned by content hash, and a
content_hash that reproduces. For artifact types with a schema in core/artifacts/ the
output is schema-valid; the two types core has no contract for yet (see the workflow's
`untyped_artifacts`) get a small, clearly-marked record instead.

Behaviour is scripted per run, not per process, so a resumed run continues the same script:

    --mock-plan '{"develop": ["failed", "success"], "verify": ["fail", "pass"]}'

Entry N applies to the step's Nth execution in the run (attempts and loop visits both
count); past the end of the list a step succeeds. Entries:

    success | pass       SUCCESS
    fail                 verification-style failure: FAILED, route `fail`, not retryable,
                         with the step's artifacts still emitted (a failing QA report is
                         evidence)
    failed               FAILED, retryable
    fatal                FAILED, not retryable
    blocked              BLOCKED
    waiting              WAITING_FOR_INPUT
    raise                the step raises, which the runtime reports as a retryable failure
    <anything else>      SUCCESS with that string as the route
"""

import copy
import json
import os

from ..hashing import content_hash
from .model import ArtifactOutput, StepResult
from .step import WorkflowStep

__all__ = ["MockStep", "register", "MOCK_STEPS", "FIXTURES"]

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
FIXTURE_SLUG = "mock-title"
DEFAULT_EPOCH = "2026-01-01T00:00:00Z"
SCHEMA_VERSION = "1.0.0"


class MockStepError(RuntimeError):
    pass


class MockStep(WorkflowStep):
    """Emits the step's declared outputs. Subclasses only set `type` and `role`."""

    type = None
    role = None

    def execute(self, inputs, context):
        entry = self._scripted(context)
        context.logger.info("mock step", script=entry, missing_inputs=inputs.missing or None)

        if entry == "raise":
            raise MockStepError(f"scripted exception in {self.id}")
        if entry == "failed":
            return StepResult.failed(f"scripted failure in {self.id}")
        if entry == "fatal":
            return StepResult.failed(f"scripted fatal failure in {self.id}", retryable=False)
        if entry == "blocked":
            return StepResult.blocked(f"scripted block in {self.id}")
        if entry == "waiting":
            return StepResult.waiting_for_input(f"scripted wait in {self.id}")

        artifacts = [self._artifact(t, inputs, context, entry) for t in self.definition.outputs]
        if entry == "fail":
            return StepResult("FAILED", route="fail", artifacts=artifacts, retryable=False,
                              error=f"{self.id} reported fail (mock)")
        route = None if entry == "success" else entry
        return StepResult.success(artifacts, route=route, message=f"{self.id} (mock)")

    # -- scripting ----------------------------------------------------------------------

    def _scripted(self, context):
        plan = (context.environment.get("mock_plan") or {}).get(self.id) or []
        if isinstance(plan, str):
            plan = [plan]
        index = context.execution - 1
        return plan[index] if index < len(plan) else "success"

    # -- artifacts ----------------------------------------------------------------------

    def _artifact(self, artifact_type, inputs, context, entry):
        slug = context.project_id or FIXTURE_SLUG
        epoch = context.environment.get("mock_epoch") or DEFAULT_EPOCH
        path = os.path.join(FIXTURES, f"{artifact_type}.json")
        if not os.path.exists(path):
            return ArtifactOutput(artifact_type, {
                "mock": True,
                "artifact_type": artifact_type,
                "step": self.id,
                "project_id": slug,
                "visit": context.visit,
                "idempotency_key": context.idempotency_key,
                "note": "No core/artifacts schema exists for this type yet; placeholder only.",
            })

        with open(path, encoding="utf-8") as handle:
            body = json.loads(handle.read().replace(FIXTURE_SLUG, slug))
        self.customize(body, artifact_type, context, entry)

        pinned = []
        for input_type, ref in sorted(inputs.refs.items()):
            content = inputs.load(input_type)
            provenance = content.get("provenance") if isinstance(content, dict) else None
            if provenance and ref.content_hash:
                pinned.append({
                    "artifact_id": provenance["artifact_id"],
                    "artifact_type": input_type,
                    "content_hash": ref.content_hash,
                })

        sequence = min(context.execution, 99)
        artifact = {
            "provenance": {
                "artifact_id": f"wgf:{artifact_type}:{slug}:{epoch[:10].replace('-', '')}-"
                               f"{sequence:02d}",
                "artifact_type": artifact_type,
                "schema_version": SCHEMA_VERSION,
                "title_id": slug,
                "produced_by": {"role": self.role, "actor": "automation"},
                "produced_at": epoch,
                "inputs": pinned,
                "content_hash": "",
                "status": "draft",
            },
        }
        artifact.update(body)
        artifact["provenance"]["content_hash"] = content_hash(artifact)
        return ArtifactOutput(artifact_type, artifact)

    def customize(self, body, artifact_type, context, entry):
        """Adjust a fixture body for this execution. Default: unchanged."""


class MockResearchStep(MockStep):
    type, role = "research", "research"


class MockStrategyStep(MockStep):
    type, role = "strategy", "game-designer"


class MockDesignStep(MockStep):
    type, role = "design", "game-designer"


class MockInitStep(MockStep):
    type, role = "init", "architect"


class MockAssetsStep(MockStep):
    type, role = "assets", "asset"


class MockDevelopmentStep(MockStep):
    type, role = "develop", "gameplay"

    def customize(self, body, artifact_type, context, entry):
        if artifact_type == "prototype-report":
            body["iteration"] = context.visit


class MockSDKStep(MockStep):
    type, role = "sdk", "sdk"


class MockVerificationStep(MockStep):
    type, role = "verify", "qa"

    def customize(self, body, artifact_type, context, entry):
        if artifact_type == "qa-report" and entry == "fail":
            body["verdict"] = "fail"
            body["blocking_defects"] = [copy.deepcopy({
                "id": f"mock-defect-{context.execution}",
                "severity": "blocker",
                "summary": "Scripted verification failure (mock).",
                "repro": "Run the mock workflow with verify scripted to fail.",
            })]
            body["suites"][1]["failed"] = 1


class MockReleaseStep(MockStep):
    type, role = "release", "release"


MOCK_STEPS = (
    MockResearchStep,
    MockStrategyStep,
    MockDesignStep,
    MockInitStep,
    MockAssetsStep,
    MockDevelopmentStep,
    MockSDKStep,
    MockVerificationStep,
    MockReleaseStep,
)


def register(registry):
    for step_class in MOCK_STEPS:
        registry.register(step_class.type, step_class)
    return registry

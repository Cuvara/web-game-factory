"""Placeholder step implementations, so the whole workflow executes before any module exists.

These do no research, design, development or publishing. Each one emits the artifacts its
step declares, built from the fixtures beside this file, with real provenance: an
artifact id in the canonical shape, the consumed inputs pinned by content hash, and a
content_hash that reproduces. For artifact types with a schema in core/artifacts/ the
output is schema-valid; the engine checks that before persisting it. There is a fixture for
every artifact type the shipped workflow names.

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

from .. import provenance
from .model import ArtifactOutput, StepResult
from .step import WorkflowStep

__all__ = ["MockStep", "register", "MOCK_STEPS", "FIXTURES"]

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
FIXTURE_SLUG = "mock-title"
DEFAULT_EPOCH = "2026-01-01T00:00:00Z"


# Where each artifact type carries the run's game idea (`wgf new-game "..."`): the path of
# keys to the `brief` field. A mock run carries it exactly as a real one does, so what a
# person typed is visible in every placeholder that has a place for it.
BRIEF_PATHS = {
    "research-report": ("scope", "brief"),
    "opportunity": ("brief",),
    "title-strategy": ("brief",),
    "game-design": ("brief",),
}


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
            raise MockStepError(f"no mock fixture for artifact type {artifact_type!r}")

        with open(path, encoding="utf-8") as handle:
            body = json.loads(handle.read().replace(FIXTURE_SLUG, slug))
        self.customize(body, artifact_type, context, entry)
        idea = context.environment.get("idea")
        if idea and artifact_type in BRIEF_PATHS:
            *parents, key = BRIEF_PATHS[artifact_type]
            target = body
            for parent in parents:
                target = target.setdefault(parent, {})
            target[key] = idea

        sequence = min(context.execution, 99)
        artifact = {
            "provenance": provenance.build(
                artifact_type,
                artifact_id=provenance.artifact_id(artifact_type, slug, epoch, sequence),
                produced_by=provenance.producer(self.role),
                produced_at=epoch,
                inputs=provenance.pin_inputs(inputs),
                title_id=slug),
        }
        artifact.update(body)
        provenance.seal(artifact)
        return ArtifactOutput(artifact_type, artifact)

    def customize(self, body, artifact_type, context, entry):
        """Adjust a fixture body for this execution. Default: unchanged."""


class MockResearchStep(MockStep):
    type, role = "research", "research"


class MockStrategyStep(MockStep):
    type, role = "strategy", "game-designer"


class MockDesignStep(MockStep):
    type, role = "design", "game-designer"


class MockTechPlanStep(MockStep):
    type, role = "tech-plan", "architect"


class MockInitStep(MockStep):
    type, role = "init", "release"

    def customize(self, body, artifact_type, context, entry):
        # The side-effect idempotency pattern a real init must follow: key the effect, and
        # on re-execution find what was made before instead of making it again.
        if artifact_type == "scaffold-record":
            body["idempotency_key"] = f"{context.run_id}:{self.id}"
            if context.previous_outputs:
                body["outcome"] = "reused"


class MockAssetsStep(MockStep):
    type, role = "assets", "asset"


class MockDevelopmentStep(MockStep):
    type, role = "develop", "gameplay"

    def customize(self, body, artifact_type, context, entry):
        if artifact_type == "prototype-report":
            body["iteration"] = context.visit


class MockReviewStep(MockStep):
    """`request-changes` in a mock plan is a review asking for changes: FAILED with that
    route and not retryable, the same shape the real review step returns.

    Otherwise it approves - so a mock run can reach release - exactly the commit the real
    step would review: the build_ref.commit_sha of its `with: subject` (default
    prototype-report; `sdk-review` names sdk-report). The approval names no reviewer
    (`reviewer.kind: none`): no code was read, and a real release refuses an approval with
    no reviewer behind it."""

    type, role = "review", "architect"

    def execute(self, inputs, context):
        subject = (self.params or {}).get("subject") or "prototype-report"
        loaded = inputs.load(subject) if subject in inputs else None
        self._subject_commit = ((loaded or {}).get("build_ref") or {}).get("commit_sha")
        result = super().execute(inputs, context)
        if result.route == "request-changes":
            return StepResult("FAILED", route=result.route, artifacts=result.artifacts,
                              retryable=False, error=f"{self.id} requested changes (mock)")
        return result

    def customize(self, body, artifact_type, context, entry):
        if artifact_type != "review-report":
            return
        body["iteration"] = context.visit
        body["attempt"] = context.attempt
        if getattr(self, "_subject_commit", None):
            body["reviewed_commit"] = self._subject_commit
        if entry == "request-changes":
            body["verdict"] = "request-changes"
            body["blockers"] = [{"id": f"mock-blocker-{context.execution}", "file": None,
                                 "summary": "Scripted review blocker (mock).",
                                 "severity": "blocker"}]


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
        if artifact_type == "verification-report" and entry == "fail":
            body["verdict"] = "FAIL"
            body["checks"][0].update(status="FAIL", message="scripted failure (mock)")
            body["summary"].update(PASS=0, FAIL=1)
            body["failed_checks"] = [body["checks"][0]["id"]]


class MockPlayabilityStep(MockStep):
    type, role = "playability", "qa"

    def customize(self, body, artifact_type, context, entry):
        if artifact_type == "playability-report" and entry == "fail":
            body["verdict"] = "FAIL"
            body["checks"][1].update(status="FAIL", summary="scripted failure (mock)")
            body["failed_checks"] = ["desktop:win.reachable"]


class MockProductionQualityStep(MockStep):
    """`fail` in a mock plan is a production gate failure routed to `develop`; `fail-assets`
    one routed to `assets` - FAILED, not retryable, the report emitted - the shape the real
    step (scripts/wgf_production) returns."""

    type, role = "production-quality", "qa"
    ROUTES = {"fail": ("develop", 1), "fail-assets": ("assets", 0)}

    def execute(self, inputs, context):
        entry = self._scripted(context)
        if entry not in self.ROUTES:
            return super().execute(inputs, context)
        context.logger.info("mock step", script=entry)
        route, index = self.ROUTES[entry]
        artifacts = [self._artifact(t, inputs, context, entry) for t in self.definition.outputs]
        return StepResult("FAILED", route=route, artifacts=artifacts, retryable=False,
                          error=f"{self.id} reported fail, route {route} (mock)")

    def customize(self, body, artifact_type, context, entry):
        if artifact_type != "production-quality-report" or entry not in self.ROUTES:
            return
        route, index = self.ROUTES[entry]
        check = body["checks"][index]
        check.update(status="FAIL", summary="scripted failure (mock)")
        body["verdict"] = "FAIL"
        body["failed"] = [f"{check['project']}:{check['id']}" if check.get("project") else check["id"]]
        body["routes"] = [route]


class MockVisualQAStep(MockStep):
    """`assets` or `develop` in a mock plan is a visual QA failure routed there: FAILED with
    that route and not retryable, a blocker finding naming it in the report - the shape the
    real visual-qa step returns. `fail` routes to develop. No frame is read."""

    type, role = "visual-qa", "qa"
    ROUTES = ("assets", "develop")

    def execute(self, inputs, context):
        result = super().execute(inputs, context)
        route = "develop" if result.route == "fail" else result.route
        if route in self.ROUTES:
            return StepResult("FAILED", route=route, artifacts=result.artifacts,
                              retryable=False, error=f"{self.id} failed visual QA (mock)")
        return result

    def customize(self, body, artifact_type, context, entry):
        if artifact_type != "visual-qa-report":
            return
        route = "develop" if entry == "fail" else entry
        if route in self.ROUTES:
            finding = f"mock-blocker-{context.execution}"
            body["verdict"] = "FAIL"
            body["findings"] = [{"id": finding, "severity": "blocker",
                                 "category": "assets" if route == "assets" else "ui",
                                 "frame": None, "route": route,
                                 "summary": "Scripted visual QA blocker (mock)."}]
            body["failed"] = [f"finding:{finding}"]
            body["routes"] = [route]


class MockContentSufficiencyStep(MockStep):
    """`develop` (or `fail`) and `design-gap` in a mock plan are a content sufficiency
    failure routed there: FAILED with that route and not retryable, a finding naming it in
    the report - the shape the real step (scripts/wgf_sufficiency) returns."""

    type, role = "content-sufficiency", "qa"
    ROUTES = ("design-gap", "develop")

    def execute(self, inputs, context):
        result = super().execute(inputs, context)
        route = "develop" if result.route == "fail" else result.route
        if route in self.ROUTES:
            return StepResult("FAILED", route=route, artifacts=result.artifacts,
                              retryable=False, error=f"{self.id} found the content short (mock)")
        return result

    def customize(self, body, artifact_type, context, entry):
        if artifact_type != "content-sufficiency-report":
            return
        route = "develop" if entry == "fail" else entry
        if route in self.ROUTES:
            check = body["checks"][0]
            check.update(status="FAIL", summary="scripted content shortfall (mock)", route=route)
            finding = {"id": f"content-sufficiency:{check['id']}", "check": check["id"],
                       "dimension": "content", "severity": "blocker",
                       "summary": check["summary"], "route": route,
                       "owner": "game-design" if route == "design-gap" else "level-design"}
            if route == "design-gap":
                finding["design_gap"] = {"field": "build_spec.content.units",
                                         "question": "Which units does the design add? (mock)",
                                         "assumed": None, "severity": "blocking"}
            body["findings"] = [finding]
            body["verdict"] = "FAIL"
            body["failed"] = [check["id"]]
            body["routes"] = [route]


class MockQualityGateStep(MockStep):
    """`design-gap`, `assets` and `develop` (or `fail`) in a mock plan are a quality gate
    failure routed there: FAILED with that route and not retryable, a dimension below its
    floor and a finding naming it in the report - the shape the real step (scripts/
    wgf_quality) returns. Nothing is scored: the mock scorecard is a development build."""

    type, role = "quality-gate", "qa"
    ROUTES = ("design-gap", "assets", "develop")
    DIMENSION = {"design-gap": "content", "assets": "visual", "develop": "ui"}

    def execute(self, inputs, context):
        self._inputs = inputs
        result = super().execute(inputs, context)
        route = "develop" if result.route == "fail" else result.route
        if route in self.ROUTES:
            return StepResult("FAILED", route=route, artifacts=result.artifacts,
                              retryable=False,
                              error=f"{self.id} found {self.DIMENSION[route]} below its floor "
                                    "(mock)")
        return result

    def _compliance(self):
        """The compliance section of a mock quality gate over the run's knowledge-contract:
        advisory - nothing was measured, so every blocking, required and recommended rule
        is UNMEASURED and every experimental one NOT_ENFORCED - the shape the real gate
        (wgf_quality.compliance) writes, and never a release. None without a contract."""
        inputs = getattr(self, "_inputs", None)
        if inputs is None or "knowledge-contract" not in getattr(inputs, "refs", {}):
            return None
        contract = inputs.load("knowledge-contract")
        ref = inputs.refs["knowledge-contract"]
        fields = ("applicable", "satisfied", "failed", "unmeasured", "excepted", "deferred",
                  "not_applicable", "not_enforced")
        total = dict.fromkeys(fields, 0)
        by_level, rules = {}, []
        for rule in contract.get("rules") or []:
            level = rule.get("level")
            status = "NOT_ENFORCED" if level == "experimental" else "UNMEASURED"
            row = by_level.setdefault(level, dict.fromkeys(fields, 0))
            for counts in (row, total):
                counts["applicable"] += 1
                counts[status.lower()] += 1
            rules.append({"id": rule.get("id"), "title": rule.get("title"), "level": level,
                          "category": rule.get("category"), "status": status, "checks": [],
                          "blocks": False})
        blocking = [r["id"] for r in rules
                    if r["level"] in ("blocking", "required") and r["status"] == "UNMEASURED"]
        return {"mode": "advisory",
                "advisory_reason": "a mock run: every step is a placeholder that measures "
                                   "nothing",
                "contract": {"artifact_id": (contract.get("provenance") or {})
                             .get("artifact_id"),
                             "content_hash": getattr(ref, "content_hash", None),
                             "retroactive": False},
                "versions": contract.get("versions") or {},
                "facets": contract.get("facets") or {},
                "counts": {"by_level": by_level, "total": total},
                "rules": rules, "exceptions": [],
                "regression": {"checks_run": 0, "checks_passed": 0, "checks_failed": 0,
                               "checks_unmeasured": 0,
                               "suite": list(contract.get("regression_suite") or [])},
                "lessons_applied": [r["id"] for r in rules], "new_lessons": [],
                "blocking": blocking,
                "verdict": "RELEASE_BLOCKED" if blocking else "PASS",
                "holds_release": False}

    def customize(self, body, artifact_type, context, entry):
        if artifact_type != "quality-report":
            return
        section = self._compliance()
        if section is not None:
            body["compliance"] = section
        route = "develop" if entry == "fail" else entry
        if route not in self.ROUTES:
            return
        dimension = self.DIMENSION[route]
        finding = {"id": f"quality:mock.{dimension}", "criterion": f"mock.{dimension}",
                   "dimension": dimension, "layer": "universal", "severity": "blocker",
                   "summary": "scripted quality shortfall (mock)", "evidence": [],
                   "build": {"commit": body["build"]["commit"], "digest": None},
                   "expected": {"minimum": 1.0}, "observed": 0.0,
                   "owner": "game-design" if route == "design-gap" else
                   ("art" if route == "assets" else "ui"),
                   "route": route, "status": "open", "first_seen": body["build"]["commit"],
                   "closed_on": None, "regressed": False}
        if route == "design-gap":
            finding["design_gap"] = {"field": "build_spec.content.units",
                                     "question": "Which units does the design add? (mock)",
                                     "assumed": None, "severity": "blocking"}
        body["findings"] = [finding]
        for entry_ in body["dimensions"]:
            if entry_["id"] == dimension:
                entry_.update(status="BELOW_FLOOR", regression=True,
                              blockers_failed=[f"mock.{dimension}"],
                              open_findings=[finding["id"]],
                              reason="scripted quality shortfall (mock)")
        body["failed"] = [dimension]
        body["routes"] = [route]
        body["regression"]["below_floor"] = [dimension]
        body["release_decision"] = {"decision": "not-release",
                                    "reasons": [f"{dimension} below its floor (mock)"]}
        body["verdict"] = "FAIL"


class MockStoreListingStep(MockStep):
    """`incomplete` in a mock plan is a listing with a problem recorded (status incomplete,
    still SUCCESS, as the real step returns one); otherwise the placeholder package."""

    type, role = "store-listing", "release"

    def execute(self, inputs, context):
        result = super().execute(inputs, context)
        if result.route == "incomplete":
            return StepResult.success(result.artifacts, message=f"{self.id} incomplete (mock)")
        return result

    def customize(self, body, artifact_type, context, entry):
        if artifact_type != "store-listing":
            return
        body["package_dir"] = f"store-listing/{context.visit}-{context.attempt}/package"
        if entry == "incomplete":
            body["status"] = "incomplete"
            body["problems"] = [{"code": "locale-missing", "severity": "error",
                                 "message": "Scripted missing locale (mock).", "subject": "ru"}]


class MockListingValidationStep(MockStep):
    """`fail` in a mock plan is a validation failure routed back to the listing step
    (FAILED, route `listing`, not retryable, the report emitted); `blocked` is the shape the
    real step returns when only a person can act."""

    type, role = "listing-validation", "release"

    def execute(self, inputs, context):
        entry = self._scripted(context)
        if entry == "blocked":
            artifacts = [self._artifact(t, inputs, context, entry) for t in self.definition.outputs]
            return StepResult("BLOCKED", artifacts=artifacts,
                              message=f"{self.id} blocked: a person must act (mock)")
        result = super().execute(inputs, context)
        if result.route == "fail":
            return StepResult("FAILED", route="listing", artifacts=result.artifacts, retryable=False,
                              error=f"{self.id} failed the listing (mock)")
        return result

    def customize(self, body, artifact_type, context, entry):
        if artifact_type != "listing-validation-report":
            return
        if entry in ("fail", "blocked"):
            body["verdict"] = "FAIL" if entry == "fail" else "BLOCKED"
            body["checks"][0].update(status="FAIL", summary="scripted failure (mock)")
            body["sections"]["screenshots"] = "FAIL"
            body["failed"] = ["screenshots.count"]
            body["routes"] = ["listing"] if entry == "fail" else []
            if entry == "blocked":
                body["blocked_reason"] = "scripted block (mock)"


class MockKnowledgeStep(MockStep):
    """The placeholder knowledge-contract: the contract the real step resolves for the mock
    design and strategy, as a fixture. `blocked` in a mock plan is the real step's refusal
    when a run cannot make its contract: the run stops there."""

    type, role = "knowledge", "architect"


class MockReleaseStep(MockStep):
    type, role = "release", "release"


class MockPlatformValidateStep(MockStep):
    """`fail` in a mock plan is a validation that found the release not publishable here:
    FAILED, route `fail`, not retryable, the record kept (readiness BLOCKED) - the shape
    the real step (scripts/wgf_publish) returns."""

    type, role = "platform-validate", "release"

    def customize(self, body, artifact_type, context, entry):
        if artifact_type == "platform-publication" and entry == "fail":
            body["state"] = "validation-failed"
            body["readiness"] = "BLOCKED"
            body["guards"] = [{"guard": "assertions_pass", "verdict": "RED",
                               "reason": "scripted breach (mock)"}]


class MockPublishStep(MockStep):
    """A mock publication contacts nothing: the record it emits says `dry_run` and outcome
    DRY_RUN, the state stays `validated`. `human` in a mock plan is a portal that needs a
    person (WAITING_FOR_HUMAN), the way the real step stops at a login or a CAPTCHA."""

    type, role = "publish", "release"

    def execute(self, inputs, context):
        if self._scripted(context) == "human" and context.decision is None:
            context.logger.info("mock step", script="human")
            return StepResult.waiting_for_human(
                f"{self.id}: the portal needs a person (mock); resume with --decision done")
        return super().execute(inputs, context)

    def customize(self, body, artifact_type, context, entry):
        if artifact_type == "platform-publication":
            body["outcome"] = "DRY_RUN"
            body["submission"] = {"method": "console", "dry_run": True, "attempts": 1,
                                  "idempotency_key": f"{context.run_id}:publish:mock"}



class MockTriageStep(MockStep):
    """Routes nothing by default: it reports `clear`, naming the entry that sent the build
    back as its `source`, and the run continues to develop as a generalist visit that still
    reads the gates' own reports - the placeholder has no findings to brief a specialist
    with. A mock plan entry naming a label (a specialist's role id, `design`, `assets`)
    routes one placeholder finding there, as the real step would."""

    type, role = "triage", "architect"

    def _label(self, context):
        entry = self._scripted(context)
        return None if entry in ("success", "pass") else entry

    def execute(self, inputs, context):
        result = super().execute(inputs, context)
        label = self._label(context)
        if result.outcome == "SUCCESS" and label and not result.route:
            return StepResult.success(result.artifacts, route=label,
                                      message=f"{self.id} routed {label} (mock)")
        return result

    def customize(self, body, artifact_type, context, entry):
        if artifact_type != "triage-report":
            return
        label = self._label(context)
        entered = getattr(context, "entered_by", None)
        body["entered_by"] = body["source"] = entered
        if not label:
            return
        route = label if label in ("design", "assets") else "develop"
        owner = "gameplay" if route != "develop" else label
        finding = {
            "id": f"triage:mock-{context.execution}", "dimension": "gameplay",
            "severity": "blocker", "summary": "Scripted finding (mock).",
            "source": {"producer": "triage", "step": None, "check": "mock",
                       "project": None, "artifact_id": None, "content_hash": None},
            "evidence_refs": [], "owner": owner,
            "task": {"change": "Nothing: the mock builds nothing.",
                     "acceptance": ["the mock gate passes"]},
            "route": route}
        group = {"owner": owner, "route": route, "label": label, "findings": [finding["id"]]}
        body.update({"mode": "fresh", "findings": [finding], "groups": [group],
                     "selected": group, "verdict": "routed",
                     "message": f"routed {label} (mock)"})

MOCK_STEPS = (
    MockResearchStep,
    MockStrategyStep,
    MockDesignStep,
    MockKnowledgeStep,
    MockTechPlanStep,
    MockInitStep,
    MockAssetsStep,
    MockTriageStep,
    MockDevelopmentStep,
    MockPlayabilityStep,
    MockProductionQualityStep,
    MockVisualQAStep,
    MockContentSufficiencyStep,
    MockQualityGateStep,
    MockReviewStep,
    MockSDKStep,
    MockVerificationStep,
    MockStoreListingStep,
    MockListingValidationStep,
    MockReleaseStep,
    MockPlatformValidateStep,
    MockPublishStep,
)


def register(registry):
    for step_class in MOCK_STEPS:
        registry.register(step_class.type, step_class)
    return registry

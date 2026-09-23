"""The `strategy` workflow step: an opportunity in, a draft title-strategy out.

It owns the domain decision and nothing else. It never approves the strategy - the workflow
places the `strategy-review` checkpoint (G2) after it - so the artifact it emits is always
`status: draft`. It never moves the title's lifecycle state and has no side effect outside
the run: re-executing it with the same input and clock yields the same artifact.
"""

import datetime
import re

from wgflib import paths
from wgflib.hashing import content_hash
from wgflib.workflow import ArtifactOutput, StepResult, WorkflowStep

from .planner import Policy, StrategyRefused, plan_strategy
from .profiles import load_profiles

__all__ = ["StrategyStep", "SCHEMA_VERSION", "READS_OPPORTUNITY_MAJOR"]

SCHEMA_VERSION = "1.1.0"          # title-strategy: 1.1 added the optional planning fields
READS_OPPORTUNITY_MAJOR = 1       # the opportunity contract this step understands

_SLUG = re.compile(r"^[a-z][a-z0-9-]*$")


def _utcnow():
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)


def slugify(value):
    slug = re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")
    if slug and not slug[0].isalpha():
        slug = "t-" + slug
    return slug or None


class StrategyStep(WorkflowStep):
    type = "strategy"
    role = "game-designer"

    # Seams for tests; the real step reads the clock and core/reference/platforms/.
    clock = staticmethod(_utcnow)
    profiles_dir = paths.PLATFORMS

    def execute(self, inputs, context):
        if "opportunity" not in inputs:
            return StepResult.waiting_for_input(
                "strategy needs an opportunity: run research first, or --run this step "
                "inside a run that holds one")

        ref = inputs.refs["opportunity"]
        major = str(ref.schema_version or "1").split(".")[0]
        if major != str(READS_OPPORTUNITY_MAJOR):
            return StepResult.failed(
                f"opportunity schema {ref.schema_version} is not readable by this step "
                f"(reads {READS_OPPORTUNITY_MAJOR}.x)", retryable=False)

        opportunity = inputs.load("opportunity")
        title_id = self._title_id(opportunity, context)
        if title_id is None:
            return StepResult.failed("no usable title id: pass --project or give the "
                                     "opportunity a title", retryable=False)
        try:
            policy = Policy.from_params(self.params)
            body = plan_strategy(opportunity, load_profiles(self.profiles_dir), title_id,
                                 policy)
        except StrategyRefused as exc:
            context.logger.warning("strategy refused", reason=str(exc))
            return StepResult.failed(f"strategy refused: {exc}", retryable=False)

        artifact = self._artifact(body, opportunity, ref, context)
        required = next(p["id"] for p in body["platform_set"] if p["role"] == "required")
        context.logger.info("strategy planned", title_id=title_id, required_platform=required,
                            timebox_days=body["timebox_days"],
                            monetization=body["monetization"]["class"])
        return StepResult.success(
            [ArtifactOutput("title-strategy", artifact, metadata={
                "title_id": title_id,
                "required_platform": required,
                "timebox_days": body["timebox_days"],
                "scope_complexity": body["production_scope"]["scope_complexity"],
            })],
            message=f"title-strategy for {title_id}: {required} primary, "
                    f"{body['timebox_days']} days - awaiting G2",
        )

    @staticmethod
    def _title_id(opportunity, context):
        for candidate in (context.project_id, opportunity.get("title_id")):
            if isinstance(candidate, str) and _SLUG.match(candidate):
                return candidate
        return slugify(opportunity.get("title"))

    def _artifact(self, body, opportunity, ref, context):
        now = self.clock()
        pinned = []
        provenance = opportunity.get("provenance") or {}
        if provenance.get("artifact_id") and ref.content_hash:
            pinned.append({"artifact_id": provenance["artifact_id"],
                           "artifact_type": "opportunity",
                           "content_hash": ref.content_hash})
        artifact = {
            "provenance": {
                "artifact_id": f"wgf:title-strategy:{body['title_id']}:"
                               f"{now.strftime('%Y%m%d')}-{min(context.execution, 99):02d}",
                "artifact_type": "title-strategy",
                "schema_version": SCHEMA_VERSION,
                "opportunity_id": body["opportunity_id"],
                "title_id": body["title_id"],
                "produced_by": {"role": self.role, "actor": "automation"},
                "produced_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "inputs": pinned,
                "content_hash": "",
                # Always a draft: G2 decides, not the step that wrote it.
                "status": "draft",
            },
        }
        artifact.update(body)
        artifact["provenance"]["content_hash"] = content_hash(artifact)
        return artifact

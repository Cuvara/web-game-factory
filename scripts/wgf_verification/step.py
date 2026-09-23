"""The `verify` step: is this build technically ready for release, and what is the evidence.

It returns a result, never a route decision. What happens next is the workflow's `on:` map:

    verdict PASS     -> StepResult SUCCESS                        (the workflow goes on)
    verdict FAIL     -> StepResult FAILED, route "fail", final    (new-game maps it to develop)
    verdict BLOCKED  -> StepResult BLOCKED                        (the run stops for a person)

Both artifacts are returned on every outcome: a failing or blocked report is evidence too,
and on a verify -> develop loop the qa-report is what development receives.
"""

from datetime import datetime, timezone

from wgflib.workflow import ArtifactOutput, StepOutcome, StepResult, WorkflowStep

from .checks import run_checks
from .model import BLOCKED, FAIL, Check
from .report import build_qa_report, build_verification_report
from .runner import CommandRunner
from .session import VerificationSession, locate_checkout

__all__ = ["VerifyStep"]

# The major schema version of each input this step can read (docs/workflow-module-contract.md
# §6: refuse what you cannot read rather than misreading it).
READABLE_MAJOR = "1"


def _utc_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class VerifyStep(WorkflowStep):
    type = "verify"

    # Replaceable in tests: how commands run, what time it is, what the environment holds.
    runner_factory = CommandRunner
    clock = staticmethod(_utc_now)
    environ = None

    def execute(self, inputs, context):
        for artifact_type, ref in sorted(inputs.refs.items()):
            major = str(ref.schema_version or READABLE_MAJOR).split(".", 1)[0]
            if major != READABLE_MAJOR:
                return StepResult.failed(
                    f"{artifact_type} has schema version {ref.schema_version}; this step reads "
                    f"{READABLE_MAJOR}.x", retryable=False)

        loaded = {t: inputs.load(t) for t in sorted(inputs.refs)}
        if inputs.missing:
            context.logger.info("verifying without some upstream artifacts",
                                missing=inputs.missing)

        root, where = locate_checkout(self.params, context.config,
                                      loaded.get("scaffold-record"), self.environ)
        if root is None:
            session = None
            checks = [Check("source.checkout", "source", "Game repository checkout", BLOCKED,
                            message=where.summary, evidence=[where])]
        else:
            session = VerificationSession(root, self.runner_factory(), params=self.params,
                                          inputs=loaded, config=context.config,
                                          logger=context.logger)
            checks = run_checks(session, where)

        title_id = self._title_id(loaded, session, context)
        produced_at = self.clock()
        pinned = [{
            "artifact_id": content["provenance"]["artifact_id"],
            "artifact_type": artifact_type,
            "content_hash": inputs.refs[artifact_type].content_hash,
        } for artifact_type, content in loaded.items()
            if isinstance(content, dict) and isinstance(content.get("provenance"), dict)
            and inputs.refs[artifact_type].content_hash]
        release_id = self.params.get("release_id") or (
            f"candidate-{session.commit[:12]}" if session and session.commit else "candidate")

        verification = build_verification_report(
            title_id=title_id, checks=checks, session=session, pinned=pinned,
            produced_at=produced_at, sequence=context.execution, release_id=release_id)
        qa = build_qa_report(
            title_id=title_id, release_id=release_id, checks=checks, session=session,
            verification=verification, produced_at=produced_at, sequence=context.execution,
            pinned=pinned)

        verdict = verification["verdict"]
        summary = verification["summary"]
        message = (f"verification {verdict}: {summary['PASS']} pass, {summary['FAIL']} fail, "
                   f"{summary['BLOCKED']} blocked, {summary['WARNING']} warning")
        context.logger.info("verification finished", verdict=verdict,
                            failed=verification["failed_checks"] or None,
                            blocked=verification["blocked_checks"] or None)
        metadata = {"verdict": verdict, "commit": verification["commit"]["sha"],
                    "failed": len(verification["failed_checks"]),
                    "blocked": len(verification["blocked_checks"])}
        artifacts = [ArtifactOutput("verification-report", verification, metadata=metadata),
                     ArtifactOutput("qa-report", qa, metadata={"verdict": qa["verdict"]})]

        if verdict == FAIL:
            failing = [c["id"] for c in verification["checks"]
                       if c["status"] == FAIL and c["required"]]
            return StepResult(StepOutcome.FAILED, route="fail", artifacts=artifacts,
                              retryable=False, message=message,
                              error="required checks failed: " + ", ".join(failing))
        if verdict == BLOCKED:
            blocked = [c["id"] for c in verification["checks"]
                       if c["status"] == BLOCKED and c["required"]]
            return StepResult(StepOutcome.BLOCKED, artifacts=artifacts,
                              message=message + "; could not verify: " + ", ".join(blocked))
        return StepResult.success(artifacts, message=message)

    @staticmethod
    def _title_id(loaded, session, context):
        for artifact_type in ("game-design", "scaffold-record", "prototype-report", "sdk-report"):
            title = (loaded.get(artifact_type) or {}).get("title_id")
            if title:
                return title
        game_id = ((session.game_config.get("game") or {}).get("id") if session else None)
        return game_id or context.project_id or "untitled"

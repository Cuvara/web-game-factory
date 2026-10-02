"""The publication outcome vocabulary, and how each outcome becomes a step result.

One vocabulary for every adapter (platform-publication.schema.json `outcome`); a platform's
own failure modes are mapped into it by its adapter, never surfaced raw to the pipeline.

    SUCCESS of the step requires VERIFIED or SUBMITTED - the portal observed holding the
    submission - or DRY_RUN (nothing submitted, by policy). A click that returned is not an
    outcome.
    HUMAN_REQUIRED, AUTH_REQUIRED, CAPTCHA_REQUIRED      WAITING_FOR_HUMAN: a person acts,
                                                         then `wgf decide <run> done|abandon`
    UNKNOWN (the portal state could not be read)         WAITING_FOR_HUMAN: ambiguous state,
                                                         a person looks before anything retries
    RETRYABLE_FAILURE (network, browser, timeout)        FAILED, retryable=False all the same:
                                                         the irreversible submit is attempted
                                                         once per visit; a person resumes
    PLATFORM_ERROR, INVALID_BUILD, INVALID_METADATA,
    BLOCKED, REJECTED                                    FAILED, not retryable
"""

from wgflib.workflow import StepOutcome, StepResult

__all__ = ["OUTCOMES", "SUCCESSFUL", "HUMAN", "FAILURES", "human_reason_for", "to_result"]

UNKNOWN, READY, BLOCKED, HUMAN_REQUIRED = "UNKNOWN", "READY", "BLOCKED", "HUMAN_REQUIRED"
SUBMITTING, SUBMITTED, VERIFIED = "SUBMITTING", "SUBMITTED", "VERIFIED"
RETRYABLE_FAILURE, PLATFORM_ERROR = "RETRYABLE_FAILURE", "PLATFORM_ERROR"
AUTH_REQUIRED, CAPTCHA_REQUIRED = "AUTH_REQUIRED", "CAPTCHA_REQUIRED"
INVALID_BUILD, INVALID_METADATA, REJECTED, DRY_RUN = ("INVALID_BUILD", "INVALID_METADATA",
                                                      "REJECTED", "DRY_RUN")

OUTCOMES = (UNKNOWN, READY, BLOCKED, HUMAN_REQUIRED, SUBMITTING, SUBMITTED, VERIFIED,
            RETRYABLE_FAILURE, PLATFORM_ERROR, AUTH_REQUIRED, CAPTCHA_REQUIRED, INVALID_BUILD,
            INVALID_METADATA, REJECTED, DRY_RUN)
SUCCESSFUL = (SUBMITTED, VERIFIED, DRY_RUN)
HUMAN = (HUMAN_REQUIRED, AUTH_REQUIRED, CAPTCHA_REQUIRED, UNKNOWN)
FAILURES = (BLOCKED, RETRYABLE_FAILURE, PLATFORM_ERROR, INVALID_BUILD, INVALID_METADATA,
            REJECTED)

# The `human_required.reason` an outcome implies when the adapter gave none.
_REASONS = {AUTH_REQUIRED: "login", CAPTCHA_REQUIRED: "captcha",
            UNKNOWN: "ambiguous-portal-state", HUMAN_REQUIRED: "manual-submission"}


def human_reason_for(outcome, reason=None):
    return reason or _REASONS.get(outcome, "manual-submission")


def to_result(outcome, artifacts, message, *, platform_id, data=None):
    """The StepResult an outcome maps to, with the artifacts (persisted whatever the outcome:
    a failed attempt's record is evidence)."""
    data = dict(data or {}, outcome=outcome, platform_id=platform_id)
    if outcome in SUCCESSFUL:
        route = "dry-run" if outcome == DRY_RUN else "submitted"
        return StepResult.success(artifacts, route=route, message=message, **data)
    if outcome in HUMAN:
        return StepResult(StepOutcome.WAITING_FOR_HUMAN, artifacts=artifacts, message=message,
                          data=dict(data, choices=["done", "abandon"]))
    return StepResult(StepOutcome.FAILED, artifacts=artifacts, error=message,
                      retryable=False, data=data)

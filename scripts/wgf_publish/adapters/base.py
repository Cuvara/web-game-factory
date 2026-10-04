"""The adapter contract: a Job in, a Publication out, outcomes from one vocabulary."""

import datetime

from wgflib import publication as pub

from .. import outcomes
from ..evidence import Evidence

__all__ = ["Job", "Publication", "PublicationAdapter", "ManualAdapter", "utc_now"]


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Job:
    """Everything one publication attempt needs, assembled by the step. Nothing here is a
    credential except `storage_state`, the path of a private, short-lived copy."""

    def __init__(self, *, platform_id, release_id, idempotency_key, package_path, package,
                 metadata, checkout, release_dir, run_dir, scratch_dir, submit, env, hooks,
                 storage_state=None, logger=None, timeouts=None, console_url=None,
                 run_process=None, listing=None, platform_profile=None):
        self.platform_id = platform_id
        self.release_id = release_id
        self.idempotency_key = idempotency_key
        self.package_path = package_path
        self.package = package or {}
        self.metadata = metadata or {}
        # {locale: copy} of the shipped store listing's rendition for this platform, and the
        # platform profile (core/reference/platforms/<id>.yaml) whose store_listing block
        # and metadata_requirements say which listing fields and locales are required.
        self.listing = listing or {}
        self.platform_profile = platform_profile or {}
        self.checkout = checkout
        self.release_dir = release_dir
        self.run_dir = run_dir
        self.scratch_dir = scratch_dir
        self.submit = bool(submit)
        self.env = env
        self.hooks = hooks or {}
        self.storage_state = storage_state
        self.logger = logger
        self.timeouts = timeouts or {}
        self.console_url = console_url
        self.run_process = run_process


class Publication:
    """What an attempt established. `state` is a platform-publication state only when the
    portal was observed in it; None means the record's state is left as it was."""

    def __init__(self, outcome, message, *, state=None, draft_id=None, found_existing=False,
                 verified_state=None, evidence=(), human_reason=None, resume_with=None,
                 submitted=False, measurement_class="automation-console"):
        if outcome not in outcomes.OUTCOMES:
            raise ValueError(f"unknown publication outcome {outcome!r}")
        self.outcome = outcome
        self.message = message
        self.state = state
        self.draft_id = draft_id
        self.found_existing = found_existing
        self.verified_state = verified_state
        self.evidence = list(evidence)
        self.human_reason = human_reason
        self.resume_with = resume_with
        self.submitted = submitted
        self.measurement_class = measurement_class


class PublicationAdapter:
    """Base class. `method` is the profile method the adapter implements."""

    method = None

    def __init__(self, platform_id, profile, settings=None):
        self.platform_id = platform_id
        self.profile = profile or {}
        self.settings = settings or {}

    @property
    def submission(self):
        return self.profile.get("submission") or {}

    def human_reason(self, credential_present=None):
        """(reason, detail) when publishing here is a person's act; None otherwise."""
        return pub.human_reason(self.profile or None, self.settings, credential_present)

    def prepare(self, job):
        """Checks before anything is contacted. Returns a list of problems (str)."""
        return []

    def publish(self, job):  # pragma: no cover - interface
        raise NotImplementedError


class ManualAdapter(PublicationAdapter):
    """A portal a person submits to: by its own tool, by email, by hand, or because nothing
    automated may touch its console. Contacts nothing; says exactly what the person does."""

    method = "manual"

    def __init__(self, platform_id, profile, settings=None):
        super().__init__(platform_id, profile, settings)
        self.method = self.submission.get("method") or "manual"

    def publish(self, job):
        reason = self.human_reason() or ("manual-submission",
                                         "no adapter automates this portal")
        method = self.submission.get("method") or "manual"
        tool = (self.submission.get("api") or {}).get("tool")
        detail = reason[1]
        what = {
            "email": f"email the package {job.package.get('filename')} and the listing text",
            "cli": f"run the portal's {tool or 'CLI'} with {job.package.get('filename')}",
            "api": f"call the portal's documented API with {job.package.get('filename')}",
            "manual": f"submit {job.package.get('filename')} in the portal's console by hand",
            "console": f"submit {job.package.get('filename')} in the portal's console by hand",
        }.get(method, "submit by hand")
        return Publication(
            outcomes.HUMAN_REQUIRED,
            f"{self.platform_id}: {detail}; a person must {what}, then `wgf decide <run> done "
            f"--note <portal reference>` (or `abandon`)",
            human_reason=reason[0],
            resume_with="wgf decide <run-id> done --note <portal reference>",
            evidence=[Evidence("observation", f"method {method}: {detail}", phase="prepare")],
            measurement_class="automation-check")

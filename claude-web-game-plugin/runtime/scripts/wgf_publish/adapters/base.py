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
    credential: a console's login is a person's, live, in the window the adapter opens, and
    no session is ever loaded or kept.

    What the visit may do (the step decides; an adapter never widens it):

        live              factory.publish.mode live AND WGF_PUBLISH_LIVE=1: the build may be
                          uploaded to the portal and the draft saved. False (dry run): nothing
                          is uploaded to a real portal.
        submit            the irreversible request (review, publish) may be made in this
                          visit: live, and a person answered `submit` to the upload. Never
                          true on the visit that uploads.
        submit_confirmed  a person answered `submit` (WAITING_FOR_HUMAN_SUBMIT_CONFIRMATION);
                          the visit requests review once and reads the status back.
        track             read-only: read the game's status and nothing else - no upload,
                          no click (`wgf publish --run <id> --track`).
        known_ids         the portal registry's lookup_candidates: the ids find_game tries
                          first ([{"source", "field", "id"}]).
        registry_status   the registry's status for the game here (NOT_CREATED when none).
        required_ids      the ids the portal issues on create that the build must carry and
                          the registry does not hold yet (identity.issued_on_create): the
                          visit creates (or finds) the game, returns IDS_ISSUED with
                          created_ids, and uploads nothing.
        identity          what names the game: {portal_game_id (the registry's),
                          config_game_id, config_app_id (game.config.yaml's for this
                          platform), title (the listing's, else the game's name)}.
        allow_create      False when the registry already knows a game here: find it, never
                          create another (True only for NOT_CREATED).
        login_timeout_s   factory.publish.login_timeout_s: how long a person has to log in on
                          the portal's page; None lets the adapter use its default.
    """

    def __init__(self, *, platform_id, release_id, idempotency_key, package_path, package,
                 metadata, checkout, release_dir, run_dir, scratch_dir, submit, env, hooks,
                 logger=None, timeouts=None, console_url=None,
                 run_process=None, listing=None, platform_profile=None, live=None,
                 submit_confirmed=False, track=False, known_ids=None, registry_status=None,
                 required_ids=None, identity=None, allow_create=True, login_timeout_s=None,
                 adaptive=None):
        # The bounded adaptive mode's settings for this visit (wgf_publish/adaptive.py
        # settings_for), resolved by the step from the run's configuration; None: from config.
        self.adaptive = adaptive
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
        self.logger = logger
        self.timeouts = timeouts or {}
        self.console_url = console_url
        self.run_process = run_process
        self.live = bool(submit) if live is None else bool(live)
        self.submit_confirmed = bool(submit_confirmed)
        self.track = bool(track)
        self.known_ids = list(known_ids or [])
        self.registry_status = registry_status or "NOT_CREATED"
        self.required_ids = list(required_ids or [])
        self.identity = dict(identity or {})
        self.allow_create = bool(allow_create)
        self.login_timeout_s = login_timeout_s


class Publication:
    """What an attempt established. `state` is a platform-publication state only when the
    portal was observed in it; None means the record's state is left as it was."""

    def __init__(self, outcome, message, *, state=None, draft_id=None, found_existing=False,
                 verified_state=None, evidence=(), human_reason=None, resume_with=None,
                 submitted=False, measurement_class="automation-console", found_game=None,
                 created_ids=None, uploaded=False, saved=False, status_text=None,
                 login_handoffs=(), actions_log=None, phase_reached=None):
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
        # What the console run observed, for the step (wave 2 interface):
        #   found_game     {"id", "title", "status_text", "source": registry|config|key|title}
        #                  or None when the lookup ran and matched nothing
        #   created_ids    {"external_game_id", "app_id", ...} the portal issued on create
        #   uploaded/saved the build reached the draft / the draft was saved, read back
        #   status_text    the portal's own status words for the game, as read
        #   login_handoffs [{"at", "url" (origin+path), "reason", "action", "resume",
        #                    "resolved_at" or None}] - each WAITING_FOR_HUMAN_LOGIN period
        #   actions_log    run-relative path of this visit's actions.jsonl
        #   phase_reached  the last phase that completed
        self.found_game = found_game
        self.created_ids = dict(created_ids or {})
        self.uploaded = bool(uploaded)
        self.saved = bool(saved)
        self.status_text = status_text
        self.login_handoffs = list(login_handoffs)
        self.actions_log = actions_log
        self.phase_reached = phase_reached


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

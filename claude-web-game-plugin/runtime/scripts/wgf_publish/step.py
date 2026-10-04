"""The `publish` step (release:submitting): every packaged platform, each on its own, behind G6.

    decision-record (G6)               ──► approved, by a person, pinning THIS release-manifest,
                                           THIS store-listing and THIS listing-validation-report
                                           by content hash - or nothing is uploaded (g6-stale)
    platform-publication (one per      ──► each platform's own newest record: its readiness,
      platform: inputs.every)              its last outcome; never another platform's
    release-manifest + checkout +      ──► the package, its bytes re-checked against the
      verification-report                  checksum, its bundle_hash the verified bundle of
                                           THIS platform
    workspace/titles/<id>/portals.json ──► the portal registry: the ids find_game tries first,
                                           what the visit observed recorded after it
    core/reference/publication/<id>    ──► the adapter: api/cli/console/email/manual
    adapter.publish(job)               ──► one platform at a time, one browser at a time
                                       ──► one platform-publication per platform it acted on

The flow per platform (docs/publish-module.md):

    visit 1 (live)   upload the build, save the draft     UPLOAD_COMPLETE: the run waits
                                                          (WAITING_FOR_HUMAN_SUBMIT_CONFIRMATION)
    a person         `wgf decide <run> submit | hold | abandon | done`
    visit 2          submit: request review ONCE, read    SUBMITTED / VERIFIED from the
                     the status back                      portal's own status text
    create-before-   no ids the build must carry yet:     IDS_ISSUED: the registry records
      build            create or find the game only       DRAFT_CREATED; route platform-ids

Outcomes of the step, from every platform's state after the visit (a platform's failure,
wait or pending review never changes another platform's record):

    G6 not passed, not a person's, not approving, or pinning
    another manifest, listing or listing validation              BLOCKED (g6-...), nothing
                                                                  recorded, nothing contacted
    any platform waiting for a person                             WAITING_FOR_HUMAN: the first
                                                                  waiting platform's choices;
                                                                  `--note platform=<id>`
                                                                  answers another
    any platform failed (INVALID_BUILD, PLATFORM_ERROR, ...)      FAILED, not retryable
    any platform refused, held, stale or not yet attempted        BLOCKED
    any platform IDS_ISSUED                                       SUCCESS, route platform-ids
    every platform SUBMITTED/VERIFIED or DRY_RUN                  SUCCESS, route submitted |
                                                                  dry-run

Per invocation (the `wgf` CLI sets them for the process): WGF_PUBLISH_PLATFORMS=<id>[,<id>]
acts on those platforms only (`--platform`), WGF_PUBLISH_TRACK=1 reads each platform's
status and does nothing else (`--track`).

The irreversible request is made only on a visit a person confirmed (`submit`), once
(retry max_attempts 1, every failure retryable=False). A re-entry finds the draft by its
idempotency key and the game by the registry, and a platform already SUBMITTED or VERIFIED
is returned as it is: nothing is uploaded or submitted twice.
"""

import os
import re

from wgflib import checkout as checkouts
from wgflib import publication as pub
from wgflib.workflow import StepOutcome, StepResult, WorkflowStep

from . import campaign, common, identity, outcomes
from . import registry as portal_registry
from .adapters import Job, resolve
from .evidence import Evidence
from .session import CredentialError, read_credential

__all__ = ["PublishStep", "DONE", "ABANDON", "SUBMIT", "HOLD", "PLATFORMS_ENV", "TRACK_ENV"]

DONE, ABANDON, SUBMIT, HOLD = "done", "abandon", "submit", "hold"
PLATFORMS_ENV, TRACK_ENV = "WGF_PUBLISH_PLATFORMS", "WGF_PUBLISH_TRACK"
_PORTAL_ID = re.compile(r"(?:^|\s)portal-id=(\S+)")
_PLATFORM = re.compile(r"(?:^|\s)platform=([a-z][a-z0-9-]*)")
_RELEASE_ID = re.compile(r"^r[0-9]+$")

# A platform's state after a visit, from its newest record.
DONE_STATE, IDS, WAITING, HELD, FAILED, PENDING, STALE, REFUSED, SKIPPED = (
    "done", "ids", "waiting", "held", "failed", "pending", "stale", "refused", "skipped")


class _Refused(Exception):
    def __init__(self, outcome, kind, code, message):
        super().__init__(message)
        self.outcome, self.kind, self.code, self.message = outcome, kind, code, message


class _Visit:
    """What one execution holds while it goes through the platforms."""

    def __init__(self, inputs, context, manifest, settings, env, scaffold, verification):
        self.inputs, self.context, self.manifest = inputs, context, manifest
        self.settings, self.env, self.scaffold = settings, env, scaffold
        self.verification = verification
        self.release_id = manifest.get("release_id")
        self.title_id = manifest.get("title_id")
        self.manifest_hash = inputs.refs["release-manifest"].content_hash
        self.campaign_hash = inputs.refs["store-listing"].content_hash \
            if "store-listing" in inputs else None
        self.root = None
        self.track = False
        self.registry = None
        self.artifacts = []          # the records written by this execution
        self.notes = {}              # pid -> (state, message) for platforms with no new record
        self.campaigns = {}          # pid -> the shipped campaign (wgf_publish.campaign) or None


class PublishStep(WorkflowStep):
    type = "publish"
    environ = None        # replaceable in tests
    run_process = None    # replaceable in tests: how the console executor runs Playwright
    adapter_factory = None  # replaceable in tests: (platform_id, profile, settings) -> adapter
    titles_dir = None     # the portal registry's titles directory; None: the project's

    def execute(self, inputs, context):
        with checkouts.StepLease(context) as lease:
            return self._execute(inputs, context, lease)

    # -- the step ---------------------------------------------------------------------------

    def _execute(self, inputs, context, lease):
        missing = [t for t in ("release-manifest", "platform-publication", "decision-record")
                   if t not in inputs]
        if missing:
            return StepResult.waiting_for_input(
                f"publish needs {', '.join(missing)} from the run that drafted and validated "
                f"the release and decided G6; run `wgf publish --run <run-id>` there")
        manifest = inputs.load("release-manifest")
        decision_record = inputs.load("decision-record")
        scaffold = inputs.load("scaffold-record") if "scaffold-record" in inputs else None
        verification = inputs.load("verification-report") \
            if "verification-report" in inputs else None
        try:
            settings = common.Settings(context.config, self.params, self.environ)
            settings.mode
        except ValueError as exc:
            return StepResult.failed(str(exc), retryable=False)
        env = dict(os.environ if self.environ is None else self.environ)
        visit = _Visit(inputs, context, manifest, settings, env, scaffold, verification)
        track = visit.track = str(env.get(TRACK_ENV, "")) == "1"
        packaged = [str(p.get("platform_id")) for p in manifest.get("packages") or []]
        selected = [p.strip() for p in str(env.get(PLATFORMS_ENV) or "").split(",") if p.strip()]
        unknown = [p for p in selected if p not in packaged]
        if unknown:
            return StepResult.blocked(
                f"--platform {', '.join(unknown)}: release {visit.release_id} packages "
                f"{', '.join(packaged) or 'nothing'}; nothing was done")
        records = self._records(inputs)
        evidence = []
        if not track:
            try:
                self._refuse_unless_authorized(inputs, context, decision_record, evidence)
            except _Refused as refused:
                context.logger.warning("publish refused", code=refused.code)
                return StepResult(StepOutcome.BLOCKED, message=f"publish refused: "
                                  f"[{refused.code}] {refused.message}",
                                  data={"code": refused.code})
        visit.evidence = evidence
        try:
            visit.registry = portal_registry.load(visit.title_id, self.titles_dir) \
                if visit.title_id else None
        except portal_registry.RegistryError as exc:
            context.logger.warning("the portal registry cannot be read", error=str(exc))
            return StepResult.blocked(f"the portal registry for {visit.title_id} cannot be "
                                      f"read: {exc}. A person repairs it "
                                      f"(workspace/titles/{visit.title_id}/portals.json)")

        decision = context.decision if not track else None
        addressed = None
        if decision is not None and not self._consumed(decision, records):
            addressed = self._addressed(decision, records, visit, packaged)
        for pid in packaged:
            if selected and pid not in selected:
                continue
            prior = records.get(pid)
            if addressed is not None and pid != addressed:
                continue  # a person's answer acts on the platform it answers, nothing else
            if prior is None:
                visit.notes[pid] = (PENDING, f"{pid}: no platform-publication; run "
                                             f"platform-validate first")
                continue
            if track:
                self._track(visit, pid, prior, lease)
            else:
                self._visit(visit, pid, prior, decision if pid == addressed else None, lease)
        return self._result(visit, packaged, self._records(inputs, visit.artifacts), track)

    # -- records ----------------------------------------------------------------------------

    @staticmethod
    def _records(inputs, written=()):
        """{platform id: its newest platform-publication}: the run's (one artifact id per
        platform), with what this execution wrote over them."""
        found = {}
        for ref in inputs.every(common.ARTIFACT):
            content = inputs.load_ref(ref)
            if isinstance(content, dict) and content.get("platform_id"):
                found[str(content["platform_id"])] = content
        for output in written:
            found[str(output.content.get("platform_id"))] = output.content
        return found

    def _state(self, visit, record):
        """A platform's state from its newest record (see the module docstring)."""
        if record is None:
            return PENDING
        if common.pinned_hash(record, "release-manifest") not in (None, visit.manifest_hash):
            return STALE
        workflow = record.get("workflow") or {}
        if workflow.get("step_id") != visit.context.current_step or not record.get("outcome") \
                or record.get("outcome") == outcomes.READY:
            return PENDING
        outcome = record.get("outcome")
        if outcome in outcomes.SUCCESSFUL:
            return DONE_STATE
        if outcome == outcomes.IDS_ISSUED:
            return IDS
        if outcome == outcomes.UPLOAD_COMPLETE and (record.get("waiting") or {}).get(
                "reason") == "held" and workflow.get("visit") == visit.context.visit:
            return HELD
        if outcome in outcomes.HUMAN:
            return WAITING
        return FAILED

    @staticmethod
    def _consumed(decision, records):
        """True when a record already answers this decision (a re-execution of its visit)."""
        at = decision.get("decided_at")
        if not at:
            return False
        for record in records.values():
            for item in record.get("evidence") or []:
                data = item.get("data") or {}
                if item.get("phase") == "person" and data.get("decided_at") == at \
                        and data.get("decision") == decision.get("decision"):
                    return True
        return False

    def _addressed(self, decision, records, visit, packaged):
        """The platform a person's answer is for: `--note platform=<id>`, else the first
        waiting platform in the release's package order."""
        named = _PLATFORM.search(str(decision.get("note") or ""))
        if named and named.group(1) in packaged:
            return named.group(1)
        for pid in packaged:
            if self._state(visit, records.get(pid)) == WAITING:
                return pid
        # One platform: the answer can only be for it (a person who submitted by hand).
        return packaged[0] if len(packaged) == 1 else None

    # -- one platform ------------------------------------------------------------------------

    def _visit(self, visit, pid, prior, decision, lease):
        context = visit.context
        key = pub.idempotency_key(context.run_id, visit.manifest_hash, pid)
        evidence = list(visit.evidence)
        try:
            state = self._state(visit, prior)
            if decision is not None:
                # A `submit` on an upload of another manifest is refused there (g6-stale).
                return self._after_person(visit, pid, prior, decision, key, evidence, lease)
            if state == STALE:
                raise _Refused(outcomes.BLOCKED, "blocked", "stale-validation",
                               f"{pid}: its newest platform-publication is of another "
                               f"release-manifest; run platform-validate again")
            self._refuse_unless_consistent(visit.manifest, prior, visit.release_id, pid)
            if state == IDS:
                # The portal issued the build's ids: the build is made again before anything
                # is uploaded here (route platform-ids). Not contacted.
                visit.notes[pid] = (IDS, f"{pid}: the portal issued the ids the build must "
                                         f"carry; waiting for the rebuild")
                return None
            if state == DONE_STATE and prior.get("outcome") in (outcomes.SUBMITTED,
                                                                outcomes.VERIFIED):
                # Already observed on the portal by an earlier visit: idempotent re-entry.
                return self._write(visit, prior, prior.get("outcome"),
                                   f"{pid}: already {prior.get('state')} (draft "
                                   f"{(prior.get('submission') or {}).get('portal_draft_id')}); "
                                   f"nothing submitted again", key, evidence,
                                   state=prior.get("state"), submission=prior.get("submission"),
                                   verified_state=prior.get("verified_state"),
                                   measurement_class=prior.get("measurement_class"))
            if state in (WAITING, HELD) and prior.get("outcome") == outcomes.UPLOAD_COMPLETE:
                # The build is on the draft: only a person's answer moves it. Not contacted.
                visit.notes[pid] = (state, f"{pid}: upload complete; waiting for submit, "
                                           f"hold or abandon")
                return None
            readiness = prior.get("readiness")
            if readiness == pub.HUMAN_REQUIRED:
                reason = prior.get("human_required") or {}
                raise _Refused(outcomes.HUMAN_REQUIRED, "human", reason.get("reason") or
                               "manual-submission",
                               f"{pid}: {reason.get('detail') or 'a person publishes here'}; "
                               f"then `wgf decide <run-id> done --note <portal reference>` "
                               f"(or `abandon`)")
            if readiness != pub.READY:
                if prior.get("role") == "optional":
                    visit.notes[pid] = (SKIPPED, f"{pid}: readiness {readiness} (optional); "
                                                 f"not published")
                    return None
                raise _Refused(outcomes.BLOCKED, "blocked", "not-ready",
                               f"{pid}: readiness is {readiness}, not READY; run "
                               f"platform-validate again once what it names is in place")
            return self._contact(visit, pid, prior, key, evidence, lease)
        except _Refused as refused:
            return self._refusal(visit, prior, refused, key, evidence)

    def _prepare(self, visit, pid, prior, evidence, lease):
        """The checkout, the package and its build checked; the profile, the credential and
        the adapter. Returns (root, package, path, profile, adapter, credential) or raises."""
        context, settings = visit.context, visit.settings
        if visit.root is None:
            root, where = common.locate_checkout(self.params or {}, context.config,
                                                 visit.scaffold, visit.env, section="publish",
                                                 logger=context.logger)
            if root is None:
                raise _Refused(outcomes.BLOCKED, "blocked", "no-checkout",
                               getattr(where, "summary", str(where)))
            try:
                lease.take(root)
            except checkouts.CheckoutLocked as exc:
                raise _Refused(outcomes.BLOCKED, "blocked", "checkout-in-use", str(exc))
            visit.root = root
        root = visit.root
        package = next((p for p in visit.manifest.get("packages") or []
                        if str(p.get("platform_id")) == pid), None)
        path, on_disk = common.package_on_disk(root, visit.release_id, package)
        if not on_disk:
            raise _Refused(outcomes.INVALID_BUILD, "failed", "package-missing",
                           f"{pid}: {package.get('filename') if package else 'the package'} "
                           f"is {'missing from' if path and not os.path.isfile(path) else 'not the bytes the manifest describes in'} "
                           f"{common.release_dir(root, visit.release_id)}")
        self._refuse_unless_this_platform_build(visit, pid, prior, package)
        evidence.append(Evidence.file(f"package {package.get('filename')} re-checked against "
                                      f"the manifest checksum", path, context.run_dir,
                                      phase="package"))
        profile = common.publication_profile_for(pid, settings)
        platform_settings = settings.platform(pid)
        try:
            credential = read_credential(profile, settings.data, visit.env)
        except CredentialError as exc:
            raise _Refused(outcomes.HUMAN_REQUIRED, "human", "credential-missing", str(exc))
        present = None if credential.kind == "none" else credential.present
        human = pub.human_reason(profile, platform_settings, present)
        if human is None and credential.kind != "none" and not credential.allowed:
            human = ("credential-missing",
                     f"{credential.env} is set but factory.publish.env_passthrough does not "
                     f"name it, so the publish step may not read it")
        if human is not None:
            raise _Refused(outcomes.HUMAN_REQUIRED, "human", human[0], f"{pid}: {human[1]}")
        adapter = (self.adapter_factory or resolve)(pid, profile, platform_settings)
        if not visit.track:
            self._refuse_unless_campaign_valid(visit, pid, profile, evidence)
        return root, package, path, profile, adapter, credential

    def _campaign(self, visit, pid):
        """The campaign the release shipped for `pid` (release/<id>/listing/), or None."""
        if pid not in visit.campaigns:
            root = visit.root
            if root is None:  # before _prepare took the checkout: only read it
                root, _ = common.locate_checkout(self.params or {}, visit.context.config,
                                                 visit.scaffold, visit.env, section="publish",
                                                 logger=visit.context.logger)
            if root is None:
                return None
            visit.campaigns[pid] = campaign.load(common.release_dir(root, visit.release_id), pid)
        return visit.campaigns[pid]

    def _campaign_hash(self, visit, pid):
        """The hash of what fills this platform's listing: the shipped campaign's, else the
        G6-pinned store-listing's (a release that shipped no listing)."""
        shipped = self._campaign(visit, pid)
        return shipped.campaign_hash() if shipped is not None else visit.campaign_hash

    def _refuse_unless_campaign_valid(self, visit, pid, profile, evidence):
        """The shipped campaign is the store-listing G6 pinned, and its media pass the
        portal's checks (wgf_publish.campaign.check_media) before anything is uploaded."""
        shipped = self._campaign(visit, pid)
        if shipped is None:
            return
        if visit.campaign_hash and shipped.listing_hash and shipped.listing_hash != visit.campaign_hash:
            raise _Refused(outcomes.BLOCKED, "blocked", "g6-stale",
                           f"{pid}: the listing shipped in release/{visit.release_id}/listing is "
                           f"store-listing {shipped.listing_hash[:19]}..., G6 pinned "
                           f"{visit.campaign_hash[:19]}...: nothing is uploaded. Release again "
                           f"from the validated listing, and G6 must be decided again")
        findings = campaign.check_media(shipped, common.profile_for(pid), profile,
                                        shipped_commit=visit.manifest.get("commit_sha"))
        failed = campaign.failures(findings)
        if failed:
            raise _Refused(outcomes.INVALID_METADATA, "failed", campaign.INVALID_MEDIA,
                           f"{pid}: the campaign's media fail the portal's checks, nothing is "
                           f"uploaded: " + "; ".join(f"[{f['code']}] {f['message']}"
                                                    for f in failed[:8])
                           + (f" (+{len(failed) - 8} more)" if len(failed) > 8 else ""))
        unknown = [f for f in findings if f["status"] == "UNKNOWN"]
        evidence.append(Evidence(
            "observation", f"campaign media checked against {pid}'s profiles: no failure"
                           + (f"; UNKNOWN (not verified): "
                              + "; ".join(f["message"] for f in unknown[:6]) if unknown else ""),
            phase="prepare", data={"campaign_hash": shipped.campaign_hash(),
                                   "findings": findings[:40],
                                   "surfaced": campaign.surfaced(shipped)}))

    def _refuse_unless_this_platform_build(self, visit, pid, prior, package):
        """The package is this platform's build, the one verify verified for it: its
        bundle_hash is the verified bundle of `pid`, never another platform's."""
        if str(package.get("platform_id")) != pid:
            raise _Refused(outcomes.INVALID_BUILD, "failed", "wrong-platform",
                           f"{pid}: the manifest's package {package.get('filename')} is "
                           f"{package.get('platform_id')}'s")
        listed = (prior.get("package") or {}).get("filename")
        if listed and listed != package.get("filename"):
            raise _Refused(outcomes.INVALID_BUILD, "failed", "wrong-package",
                           f"{pid}: validated {listed}, the manifest packages "
                           f"{package.get('filename')}")
        artifact = (visit.verification or {}).get("build_artifact") or {}
        builds = {str(b.get("platform_id")): b.get("content_hash")
                  for b in artifact.get("platforms") or []}
        if not visit.verification:
            return
        if not builds:
            # One bundle for the whole release (before verify built per platform).
            if package.get("bundle_hash") and package["bundle_hash"] != artifact.get("content_hash"):
                raise _Refused(outcomes.INVALID_BUILD, "failed", "build-mismatch",
                               f"{pid}: the package was made from bundle "
                               f"{package['bundle_hash'][:19]}..., not the verified one")
            return
        bundle = package.get("bundle_hash")
        if bundle == builds.get(pid):
            return
        other = next((p for p, h in builds.items() if h == bundle and p != pid), None)
        raise _Refused(outcomes.INVALID_BUILD, "failed",
                       "wrong-platform" if other else "build-mismatch",
                       f"{pid}: the package was made from "
                       + (f"{other}'s build" if other else
                          f"bundle {str(bundle)[:19]}..." if bundle else "no recorded bundle")
                       + f", not the bundle verify built and verified for {pid}")

    def _contact(self, visit, pid, prior, key, evidence, lease, confirmed=False):
        """The adapter's visit: everything checked first, then one publish(job)."""
        context, settings = visit.context, visit.settings
        root, package, path, profile, adapter, credential = self._prepare(
            visit, pid, prior, evidence, lease)
        reg = visit.registry
        entry = reg.get(pid) if reg else None
        required = [n for n in identity.issued(profile)
                    if n not in identity.registry_ids(profile, entry)]
        if not required and identity.build_keys(profile):
            build, source, problem = identity.build_entry(root, visit.verification, pid)
            missing, wrong, _ = identity.ids_check(profile, build, entry)
            if problem or missing or wrong:
                raise _Refused(outcomes.INVALID_BUILD, "failed", "platform-ids-missing",
                               f"{pid}: the build "
                               + (f"cannot be read ({problem})" if problem else
                                  f"lacks {', '.join(missing + wrong)} the portal issued")
                               + "; it is never uploaded: rebuild with the registry's ids "
                                 "(sdk), verify, release, validate, G6 again")
        bundle = package.get("bundle_hash") or package.get("checksum")
        live = settings.live
        evidence.append(Evidence("observation",
                                 f"mode {settings.mode}" + (
                                     ("; a person confirmed the submit: review is requested "
                                      "once" if confirmed else
                                      "; the build is uploaded and saved, the request waits "
                                      "for a person") if live else
                                     "; nothing is uploaded or submitted (dry run)"
                                     if settings.mode == "dry-run" else
                                     "; WGF_PUBLISH_LIVE is not 1, so nothing is uploaded"),
                                 phase="policy"))
        if required:
            evidence.append(Evidence("observation", f"{', '.join(required)} not issued yet: the "
                                                    f"visit creates or finds the game only",
                                     phase="identity"))
        platform_settings = settings.platform(pid)
        ident = self._identity(visit, pid, entry)
        metadata = common.store_metadata(root, visit.release_id, visit.manifest).get(pid) or {}
        scratch = os.path.join(context.run_dir, context.current_step,
                               f"{context.visit}-{context.attempt}", pid) \
            if context.run_dir else None
        job = Job(platform_id=pid, release_id=visit.release_id, idempotency_key=key,
                  package_path=path, package=package, metadata=metadata, checkout=root,
                  listing=common.listing_text(root, visit.release_id, pid),
                  platform_profile=common.profile_for(pid),
                  release_dir=common.release_dir(root, visit.release_id), run_dir=context.run_dir,
                  scratch_dir=scratch or common.release_dir(root, visit.release_id),
                  submit=live and confirmed, live=live, submit_confirmed=confirmed,
                  env=settings.game_env(context.config),
                  hooks=context.process_hooks() if hasattr(context, "process_hooks") else {},
                  logger=context.logger, timeouts=settings.timeouts,
                  console_url=platform_settings.get("console_url"),
                  run_process=self.run_process,
                  known_ids=reg.lookup_candidates(
                      pid, config_game_id=ident["config_game_id"],
                      config_app_id=ident["config_app_id"]) if reg else [],
                  registry_status=reg.status(pid) if reg else None,
                  required_ids=required, identity=ident,
                  login_timeout_s=settings.get("login_timeout_s"),
                  campaign=self._campaign(visit, pid),
                  # A game the registry knows is never created again: the visit finds it.
                  allow_create=(reg.status(pid) if reg else "NOT_CREATED") == "NOT_CREATED")
        # No session is loaded or kept: a person logs in, live, in the window the adapter
        # opens (credential.kind human-login), and the session ends with it.
        if scratch:
            os.makedirs(scratch, exist_ok=True)
        result = adapter.publish(job)
        outcome = result.outcome
        if live and not confirmed and outcome == outcomes.DRY_RUN and (
                result.uploaded or result.saved or result.draft_id):
            # A live visit that stopped before the request with the build on a draft: the
            # request is a person's call (an adapter that reports a dry run's words for it).
            outcome = outcomes.UPLOAD_COMPLETE
        if result.submitted and not confirmed:
            context.logger.error("an adapter requested review without a person's confirmation",
                                 platform=pid)
            evidence.append(Evidence("observation", "the adapter reported a request no person "
                                                    "confirmed; recorded as observed",
                                     phase="policy"))
        if required and (result.uploaded or result.submitted):
            context.logger.error("an adapter uploaded a build that lacks the portal's ids",
                                 platform=pid)
        evidence.extend(result.evidence)
        submission = dict(prior.get("submission") or {})
        submission.update({
            "method": adapter.method,
            "idempotency_key": key,
            "dry_run": not live,
            "attempts": int(submission.get("attempts") or 0) + 1,
            "authorized_by": self._authorization(visit),
        })
        if result.draft_id:
            submission["portal_draft_id"] = result.draft_id
        campaign_hash = self._campaign_hash(visit, pid)
        if campaign_hash:
            submission["campaign_hash"] = campaign_hash
        if result.submitted:
            submission["submitted_at"] = common.utc_now()
            submission["submitted_by"] = f"wgf publish ({adapter.__class__.__name__})"
            submission["package_filename"] = package.get("filename")
        observed = self._observe(visit, pid, profile, result, outcome, bundle, evidence)
        if observed.get("external_game_id"):
            submission["portal_game_id"] = observed["external_game_id"]
        human_required = None
        if outcome in outcomes.HUMAN:
            reason = outcomes.human_reason_for(outcome, result.human_reason)
            resume = result.resume_with or self._resume_for(outcome, pid)
            human_required = {"reason": reason, "detail": result.message, "resume_with": resume}
        message = result.message
        if outcome == outcomes.UPLOAD_COMPLETE and result.outcome != outcome:
            message = (f"{pid}: the build is on the draft and saved; the review request is a "
                       f"person's call: `wgf decide <run-id> submit` (or hold, abandon)")
        return self._write(visit, prior, outcome, message, key, evidence,
                           state=result.state or prior.get("state"), submission=submission,
                           verified_state=result.verified_state,
                           measurement_class=result.measurement_class,
                           human_required=human_required, phase=result.phase_reached,
                           waiting=self._login_waiting(pid, outcome, result))

    @staticmethod
    def _resume_for(outcome, pid):
        if outcome == outcomes.UPLOAD_COMPLETE:
            return (f"wgf decide <run-id> submit|hold|abandon --note platform={pid} "
                    f"(done after submitting by hand)")
        if outcome in (outcomes.AUTH_REQUIRED, outcomes.CAPTCHA_REQUIRED):
            return ("wgf resume <run-id>: the window opens again and a person logs in there "
                    "(nothing is captured or kept)")
        return "wgf decide <run-id> done --note <portal reference> (or abandon)"

    def _identity(self, visit, pid, entry):
        """What names the game on the portal (job.identity): the registry's game id, the ids
        game.config.yaml carries for the platform, and the exact title."""
        config_entry = {}
        title = None
        if visit.root:
            from wgflib.yamllite import YamlError, load
            from wgflib import template_contract as contract
            try:
                with open(os.path.join(visit.root, contract.GAME_CONFIG), encoding="utf-8") as h:
                    config = load(h.read()) or {}
            except (OSError, YamlError):
                config = {}
            config_entry = next((p for p in config.get("platforms") or []
                                 if isinstance(p, dict) and str(p.get("id")) == pid), {})
            title = (config.get("game") or {}).get("name")
            listing = common.listing_text(visit.root, visit.release_id, pid)
            title = next((str(t.get("title")) for t in listing.values() if t.get("title")),
                         title)
        identity_ = {"portal_game_id": (entry or {}).get("external_game_id"),
                     "config_game_id": config_entry.get("game_id"),
                     "config_app_id": config_entry.get("app_id"),
                     "title": title}
        return {k: (str(v) if v not in (None, "") else None) for k, v in identity_.items()}

    @staticmethod
    def _login_waiting(pid, outcome, result):
        """The record's `waiting` block from the visit's last login handoff, when it ended
        waiting for a person to log in."""
        if outcomes.waiting_state_for(outcome) != outcomes.WAITING_FOR_HUMAN_LOGIN \
                or not result.login_handoffs:
            return None
        last = result.login_handoffs[-1] or {}
        block = {"state": outcomes.WAITING_FOR_HUMAN_LOGIN, "portal": pid,
                 "step": result.phase_reached or "check_session",
                 "reason": str(last.get("reason") or outcomes.human_reason_for(outcome)),
                 "action": str(last.get("action") or "a person logs in on the portal's page"),
                 "resume": str(last.get("resume") or "wgf resume <run-id>")}
        if last.get("url"):
            block["url"] = str(last["url"])
        if last.get("at"):
            block["at"] = str(last["at"])
        return block

    # -- the registry -----------------------------------------------------------------------

    def _observe(self, visit, pid, profile, result, outcome, bundle, evidence):
        """Record in the portal registry what the visit observed. Returns the entry (or {}).
        A status only the portal establishes is recorded only with its status text; a
        transition the registry refuses leaves the status as it was, and says so."""
        reg, context = visit.registry, visit.context
        if reg is None:
            return {}
        fields = {"last_checked_at": common.utc_now()}
        if visit.release_id and _RELEASE_ID.match(str(visit.release_id)):
            fields["release_id"] = visit.release_id
        if not visit.track and (result.uploaded or result.saved or outcome in (
                outcomes.UPLOAD_COMPLETE, outcomes.SUBMITTED, outcomes.VERIFIED)):
            # What is on the portal now. A build or listing other than the one recorded
            # makes the submission facts recorded for the old one stale.
            if reg.get(pid) is not None:
                changed = reg.invalidate_if_changed(pid, build_hash=bundle,
                                                    campaign_hash=self._campaign_hash(visit, pid),
                                                    run_id=context.run_id)
                if changed:
                    evidence.append(Evidence(
                        "observation", f"registry: {', '.join(sorted(changed))} changed since "
                                       f"the last upload; its submission status no longer "
                                       f"applies", phase="registry",
                        data={"changed": sorted(changed)}))
            fields["build_hash"] = bundle
            fields["campaign_hash"] = self._campaign_hash(visit, pid)
        if result.status_text:
            fields["submission_status"] = str(result.status_text)
        created = identity.created_fields(profile, result.created_ids)
        entry = reg.get(pid)
        status, note = None, None
        ref = f"run:{context.run_id}/{context.current_step}/{context.visit}/{pid}"
        status_evidence = ([portal_registry.evidence_item("portal-status", ref,
                                                          str(result.status_text))]
                           if result.status_text else [])
        reason = result.human_reason
        if outcome == outcomes.IDS_ISSUED:
            status = "DRAFT_CREATED"
            fields.update(created)
            if not entry or not entry.get("association"):
                fields["association"] = "created-by-factory"
            note = "the portal issued " + ", ".join(sorted(result.created_ids or {}))
        elif reason in ("duplicate-candidate", "review-pending"):
            note = (f"{reason}: " + str(result.message or ""))[:300]
        elif outcome == outcomes.REJECTED:
            status = "REJECTED"
        elif outcome in (outcomes.SUBMITTED, outcomes.VERIFIED):
            status = {"live": "PUBLISHED", "rejected": "REJECTED"}.get(
                result.state, "PENDING_REVIEW")
        elif result.uploaded or result.saved or outcome == outcomes.UPLOAD_COMPLETE or (
                outcome == outcomes.DRY_RUN and result.draft_id):
            status = "DRAFT"
        if created and outcome != outcomes.IDS_ISSUED and not (entry or {}).get("external_game_id"):
            fields.update(created)
            fields.setdefault("association", "created-by-factory")
        found = result.found_game or {}
        if found.get("id") and found.get("source") in ("registry", "config") and entry is None:
            fields.update(external_game_id=str(found["id"]), association="observed")
        if status in portal_registry.EVIDENCE_REQUIRED and not status_evidence:
            note = f"{status} not recorded: the portal's status text was not read"
            status = None
        if status == (entry or {}).get("status", "NOT_CREATED"):
            status = None
        if entry is None and status is None:
            if not created and not fields.get("external_game_id"):
                return {}  # nothing known of a game here yet
            status = "UNKNOWN"
        try:
            return reg.record(pid, by="automation", run_id=context.run_id, note=note,
                              status=status, evidence=status_evidence, **fields)
        except portal_registry.RegistryError as exc:
            context.logger.warning("registry write refused", platform=pid, error=str(exc))
            evidence.append(Evidence("observation", f"registry: {exc}", phase="registry"))
            for field in portal_registry.IDENTITY:
                if (entry or {}).get(field):
                    fields.pop(field, None)
            try:
                return reg.record(pid, by="automation", run_id=context.run_id,
                                  note=f"kept {reg.status(pid)}: {exc}"[:300],
                                  evidence=status_evidence, **fields) if entry else {}
            except portal_registry.RegistryError:
                return entry or {}

    # -- a person answered ------------------------------------------------------------------

    def _after_person(self, visit, pid, prior, decision, key, evidence, lease):
        choice = decision.get("decision")
        marker = Evidence("observation", f"{choice} by {decision.get('decided_by')}: "
                                         f"{decision.get('note') or 'no note'}",
                          phase="person", data={"decision": choice,
                                                "decided_at": decision.get("decided_at"),
                                                "platform_id": pid})
        waiting_upload = prior.get("outcome") == outcomes.UPLOAD_COMPLETE
        choices = outcomes.choices_for(prior.get("outcome"))
        if choice == ABANDON:
            return self._write(visit, prior, outcomes.BLOCKED,
                               f"{pid}: publication abandoned by a person"
                               + (f": {decision['note']}" if decision.get("note") else ""),
                               key, evidence + [marker], state=prior.get("state"),
                               measurement_class="human")
        if choice not in choices:
            visit.notes[pid] = (WAITING, f"{pid}: {choice!r} is not one of "
                                         f"{', '.join(choices)}")
            return None
        if decision.get("decided_by") != "human":
            visit.notes[pid] = (WAITING, f"{pid}: {choice} is a person's answer, never "
                                         f"automation's")
            return None
        if choice == HOLD:
            waiting = self._waiting_block(pid, outcomes.UPLOAD_COMPLETE, "held",
                                          "the draft stays as it is; nothing is requested",
                                          "wgf resume <run-id> --from submit, then submit")
            return self._write(visit, prior, outcomes.UPLOAD_COMPLETE,
                               f"{pid}: held by a person; the draft stays, nothing requested",
                               key, evidence + [marker], state=prior.get("state"),
                               submission=prior.get("submission"), measurement_class="human",
                               human_required=prior.get("human_required"), waiting=waiting)
        if choice == SUBMIT and waiting_upload:
            self._refuse_unless_unchanged_since_upload(visit, pid, prior)
            self._refuse_unless_consistent(visit.manifest, prior, visit.release_id, pid)
            if not visit.settings.live:
                visit.notes[pid] = (WAITING, f"{pid}: submit needs live mode "
                                             f"(factory.publish.mode live and "
                                             f"WGF_PUBLISH_LIVE=1); nothing was requested")
                return None
            return self._contact(visit, pid, prior, key, evidence + [marker], lease,
                                 confirmed=True)
        if choice == DONE and (prior.get("human_required") or {}).get("reason") == \
                "duplicate-candidate":
            found = _PORTAL_ID.search(str(decision.get("note") or ""))
            if found and visit.registry is not None:
                try:
                    visit.registry.associate(pid, found.group(1), note=str(decision.get("note")),
                                             run_id=visit.context.run_id)
                except portal_registry.RegistryError as exc:
                    visit.notes[pid] = (WAITING, f"{pid}: the game cannot be associated: {exc}")
                    return None
                evidence.append(marker)
                evidence.append(Evidence("observation", f"{pid}: a person associated portal "
                                                        f"game {found.group(1)}; the visit "
                                                        f"continues with it", phase="registry"))
                return self._contact(visit, pid, prior, key, evidence, lease)
        # done: the person submitted by hand.
        note = decision.get("note") or ""
        submission = dict(prior.get("submission") or {})
        submission.update({"method": submission.get("method") or "manual",
                           "idempotency_key": key, "submitted_at": common.utc_now(),
                           "submitted_by": str(decision.get("decided_by") or "human"),
                           "attempts": int(submission.get("attempts") or 0) + 1,
                           **({"portal_reference": note} if note else {})})
        verified = {"observed": "submitted (recorded by a person)", "at": common.utc_now(),
                    "source": "wgf decide done"}
        return self._write(visit, prior, outcomes.SUBMITTED,
                           f"{pid}: submitted by a person" + (f" ({note})" if note else ""),
                           key, evidence + [marker], state="submitted", submission=submission,
                           verified_state=verified, measurement_class="human")

    def _refuse_unless_unchanged_since_upload(self, visit, pid, prior):
        """A `submit` requests review of exactly what was uploaded, under the G6 that
        authorized it: the same manifest, build and listing, or G6 is decided again."""
        authorized = ((prior.get("submission") or {}).get("authorized_by") or {}) \
            .get("release_manifest_hash")
        if authorized and authorized != visit.manifest_hash:
            raise _Refused(outcomes.BLOCKED, "blocked", "g6-stale",
                           f"{pid}: the upload was authorized for release-manifest "
                           f"{authorized[:19]}..., the run now holds {visit.manifest_hash[:19]}"
                           f"...: nothing is requested. Upload again, and G6 must be decided "
                           f"again")
        package = next((p for p in visit.manifest.get("packages") or []
                        if str(p.get("platform_id")) == pid), {})
        entry = visit.registry.get(pid) if visit.registry else None
        bundle = package.get("bundle_hash") or package.get("checksum")
        for field, now in (("build_hash", bundle),
                           ("campaign_hash", self._campaign_hash(visit, pid))):
            then = (entry or {}).get(field)
            if then and now and then != now:
                raise _Refused(outcomes.BLOCKED, "blocked", "g6-stale",
                               f"{pid}: the {field.split('_')[0]} uploaded ({then[:19]}...) is "
                               f"not the one G6 now covers ({now[:19]}...): nothing is "
                               f"requested. Upload again, and G6 must be decided again")

    # -- track: read the status, nothing else -----------------------------------------------

    def _track(self, visit, pid, prior, lease):
        context = visit.context
        key = pub.idempotency_key(context.run_id, visit.manifest_hash, pid)
        entry = visit.registry.get(pid) if visit.registry else None
        draft = (prior.get("submission") or {}).get("portal_draft_id")
        if not (entry or {}).get("external_game_id") and not draft:
            visit.notes[pid] = (SKIPPED, f"{pid}: no game known on the portal; nothing to read")
            return None
        evidence = [Evidence("observation", "track: the status is read; nothing is uploaded, "
                                            "nothing is clicked", phase="policy")]
        try:
            root, package, path, profile, adapter, credential = self._prepare(
                visit, pid, prior, evidence, lease)
        except _Refused as refused:
            visit.notes[pid] = (SKIPPED, f"{pid}: not read: [{refused.code}] {refused.message}")
            return None
        reg = visit.registry
        job = Job(platform_id=pid, release_id=visit.release_id, idempotency_key=key,
                  package_path=path, package=package, metadata={}, checkout=root,
                  release_dir=common.release_dir(root, visit.release_id),
                  run_dir=context.run_dir, scratch_dir=common.release_dir(root, visit.release_id),
                  submit=False, live=False, track=True, env=visit.settings.game_env(context.config),
                  hooks=context.process_hooks() if hasattr(context, "process_hooks") else {},
                  logger=context.logger, timeouts=visit.settings.timeouts,
                  console_url=visit.settings.platform(pid).get("console_url"),
                  run_process=self.run_process,
                  known_ids=reg.lookup_candidates(pid) if reg else [],
                  registry_status=reg.status(pid) if reg else None,
                  identity=self._identity(visit, pid, entry),
                  login_timeout_s=visit.settings.get("login_timeout_s"), allow_create=False)
        result = adapter.publish(job)
        if result.uploaded or result.submitted:
            context.logger.error("a track visit reported an action", platform=pid)
            evidence.append(Evidence("observation", "the adapter reported an upload or a "
                                                    "request on a read-only visit",
                                     phase="policy"))
        evidence.extend(result.evidence)
        outcome = result.outcome
        if outcome in (outcomes.DRY_RUN, outcomes.UPLOAD_COMPLETE, outcomes.IDS_ISSUED):
            outcome = prior.get("outcome") or outcomes.UNKNOWN
        bundle = package.get("bundle_hash") or package.get("checksum")
        observed = self._observe(visit, pid, profile, result, outcome, bundle, evidence)
        submission = dict(prior.get("submission") or {}, idempotency_key=key)
        if observed.get("external_game_id"):
            submission["portal_game_id"] = observed["external_game_id"]
        human_required = None
        if outcome in outcomes.HUMAN:
            human_required = {"reason": outcomes.human_reason_for(outcome, result.human_reason),
                              "detail": result.message,
                              "resume_with": self._resume_for(outcome, pid)}
        return self._write(visit, prior, outcome, f"{pid}: tracked: "
                           f"{result.status_text or result.message}", key, evidence,
                           state=result.state or prior.get("state"), submission=submission,
                           verified_state=result.verified_state or prior.get("verified_state"),
                           measurement_class=result.measurement_class,
                           human_required=human_required, phase="track")

    # -- refusals ---------------------------------------------------------------------------

    def _refuse_unless_authorized(self, inputs, context, record, evidence):
        """G6: a human decision, approving, pinning exactly this release-manifest, store
        listing and listing validation. A hash that changed after G6 is g6-stale."""
        gates = list(getattr(context, "gates_passed", None) or [])
        if "G6" not in gates:
            raise _Refused(outcomes.BLOCKED, "blocked", "g6-not-passed",
                           "G6 (publish authorization) is not passed and current in this run: "
                           "nothing is uploaded. Decide it: wgf decide <run-id> publish")
        if record.get("gate_id") != "G6":
            raise _Refused(outcomes.BLOCKED, "blocked", "g6-record-missing",
                           f"the newest decision-record is for {record.get('gate_id')}, not G6")
        if record.get("decision") != "approved":
            raise _Refused(outcomes.BLOCKED, "blocked", "g6-not-approved",
                           f"G6 was decided {record.get('decision')!r}, not approved")
        if (record.get("decided_by") or {}).get("mode") != "human":
            raise _Refused(outcomes.BLOCKED, "blocked", "g6-not-human",
                           "the G6 decision-record was not made by a person; publication never "
                           "proceeds on an automated G6")
        pinned = {}
        for subject in record.get("subject") or []:
            pinned.setdefault(subject.get("artifact_type"), subject.get("content_hash"))
        for artifact_type in ("release-manifest", "store-listing", "listing-validation-report"):
            current = inputs.refs[artifact_type].content_hash if artifact_type in inputs \
                else None
            then = pinned.get(artifact_type)
            if current is None or then != current:
                raise _Refused(
                    outcomes.BLOCKED, "blocked", "g6-stale",
                    f"the G6 decision pins {artifact_type} "
                    f"{(then or '(none)')[:19]}..., but the run holds "
                    f"{(current or 'none')[:19]}...: it changed after G6, or G6 never covered "
                    f"it. Nothing is uploaded; G6 must be decided again "
                    f"(wgf decide <run-id> publish)")
        evidence.append(Evidence("artifact", f"G6 {record.get('provenance', {}).get('artifact_id')} "
                                             f"approved by a person, pinning release-manifest "
                                             f"{pinned['release-manifest']}, store-listing and "
                                             f"listing-validation-report", phase="authorization",
                                 content_hash=pinned["release-manifest"]))
        self._g6 = record

    @staticmethod
    def _refuse_unless_consistent(manifest, prior, release_id, pid):
        if prior.get("release_id") != release_id:
            raise _Refused(outcomes.BLOCKED, "blocked", "release-mismatch",
                           f"the platform-publication is for release {prior.get('release_id')}, "
                           f"the manifest for {release_id}")
        if pid not in {str(t.get("id")) for t in manifest.get("target_platforms") or []}:
            raise _Refused(outcomes.BLOCKED, "blocked", "platform-not-targeted",
                           f"{pid} is not a target of release {release_id}")

    def _authorization(self, visit):
        record = getattr(self, "_g6", None) or {}
        return {"decision_record": str((record.get("provenance") or {}).get("artifact_id")),
                "release_manifest_hash": visit.manifest_hash}

    def _refusal(self, visit, prior, refused, key, evidence):
        pid = prior.get("platform_id")
        visit.context.logger.warning("publish refused", platform=pid, code=refused.code,
                                     outcome=refused.outcome)
        if refused.kind == "blocked":
            # Not an attempt: the record is left as it is, the run stops for a person.
            visit.notes[pid] = (REFUSED, f"[{refused.code}] {refused.message}")
            visit.codes = getattr(visit, "codes", []) + [refused.code]
            return None
        evidence = evidence + [Evidence("observation", f"[{refused.code}] {refused.message}",
                                        phase="refusal")]
        human_required = None
        if refused.outcome in outcomes.HUMAN:
            human_required = {"reason": refused.code if refused.kind == "human" else
                              "ambiguous-portal-state", "detail": refused.message,
                              "resume_with": "wgf decide <run-id> done --note <portal reference>"}
        return self._write(visit, prior, refused.outcome, refused.message, key, evidence,
                           state=prior.get("state"),
                           submission=dict(prior.get("submission") or {}, idempotency_key=key),
                           human_required=human_required, measurement_class="automation-check")

    # -- the record -------------------------------------------------------------------------

    @staticmethod
    def _waiting_block(pid, outcome, reason, action, resume, step=None):
        return {"state": outcomes.waiting_state_for(outcome), "portal": pid,
                "step": step or "submit", "reason": reason, "action": action,
                "resume": resume, "at": common.utc_now()}

    def _write(self, visit, prior, outcome, message, key, evidence, *, state, submission=None,
               verified_state=None, measurement_class=None, human_required=None, waiting=None,
               phase=None):
        context = visit.context
        pid = prior.get("platform_id")
        body = {k: prior[k] for k in ("release_id", "title_id", "platform_id", "profile_version",
                                      "role", "readiness", "guards", "assertion_results",
                                      "package", "review", "live_url", "went_live_at")
                if k in prior}
        body.update({
            "state": state or prior.get("state"),
            "outcome": outcome,
            "evidence": common.evidence_dicts(list(prior.get("evidence") or [])[-10:]
                                              + list(evidence)),
            "measurement_class": measurement_class or "automation-console",
            "workflow": {"run_id": context.run_id, "workflow_id": context.workflow_id,
                         "step_id": context.current_step, "visit": context.visit,
                         "execution": context.execution, "idempotency_key": key},
        })
        if submission:
            body["submission"] = {k: v for k, v in submission.items() if v is not None}
        if verified_state:
            body["verified_state"] = verified_state
        if body["state"] == "live" and prior.get("state") != "live":
            # Observed live: where, as far as the portal said (null when it did not).
            entry = visit.registry.get(pid) if visit.registry else None
            body["live_url"] = (verified_state or {}).get("url") or (entry or {}).get("url")
            body["went_live_at"] = common.utc_now()
        if body["state"] == "rejected" and "rejection" not in body:
            # A rejection is recorded with its compliance finding, which a person writes:
            # the outcome says REJECTED, the state stays where it was.
            body["state"] = prior.get("state")
        if human_required and outcome in outcomes.HUMAN:
            body["human_required"] = human_required
            body["waiting"] = waiting or self._waiting_block(
                pid, outcome, human_required.get("reason") or "manual-submission",
                str(human_required.get("detail") or "a person acts"),
                str(human_required.get("resume_with") or self._resume_for(outcome, pid)),
                step=phase)
        artifact = common.record(body, inputs=visit.inputs, context=context,
                                 title_id=visit.title_id, sequence=context.execution)
        visit.artifacts.append(artifact)
        visit.notes.pop(pid, None)
        context.logger.info("publication", platform=pid, outcome=outcome, state=body["state"],
                            draft=(submission or {}).get("portal_draft_id"))
        visit.messages = dict(getattr(visit, "messages", {}), **{pid: message})
        return artifact

    # -- the step's result ------------------------------------------------------------------

    def _result(self, visit, packaged, records, track):
        """One result from every platform's state; see the module docstring."""
        states, lines = {}, []
        messages = getattr(visit, "messages", {})
        for pid in packaged:
            if pid in visit.notes:
                state, message = visit.notes[pid]
            else:
                record = records.get(pid)
                state = self._state(visit, record)
                message = messages.get(pid) or (
                    f"{pid}: {record.get('outcome') or record.get('readiness')} "
                    f"({record.get('state')})" if record else f"{pid}: not validated")
            states[pid] = state
            lines.append(message)
        summary = " | ".join(lines)
        data = {"platforms": {pid: {"state": states[pid],
                                    "outcome": (records.get(pid) or {}).get("outcome")}
                              for pid in packaged},
                "track": track}
        artifacts = list(visit.artifacts)
        waiting = [pid for pid in packaged if states[pid] == WAITING]
        if waiting:
            first = records.get(waiting[0]) or {}
            choices = []
            for pid in waiting:
                for choice in outcomes.choices_for((records.get(pid) or {}).get("outcome")):
                    if choice not in choices:
                        choices.append(choice)
            outcome = first.get("outcome") or outcomes.HUMAN_REQUIRED
            return StepResult(StepOutcome.WAITING_FOR_HUMAN, artifacts=artifacts,
                              message=f"waiting for a person on {', '.join(waiting)}: {summary}",
                              data=dict(data, outcome=outcome, platform_id=waiting[0],
                                        waiting_state=outcomes.waiting_state_for(outcome),
                                        choices=choices, waiting=waiting))
        failed = [pid for pid in packaged if states[pid] == FAILED]
        if failed:
            return StepResult(StepOutcome.FAILED, artifacts=artifacts, retryable=False,
                              error=f"publication failed on {', '.join(failed)}: {summary}",
                              data=dict(data, outcome=(records.get(failed[0]) or {})
                                        .get("outcome"), platform_id=failed[0]))
        stopped = [pid for pid in packaged if states[pid] in (REFUSED, HELD, STALE, PENDING)]
        if stopped:
            codes = getattr(visit, "codes", [])
            return StepResult(StepOutcome.BLOCKED, artifacts=artifacts,
                              message=f"publish stopped on {', '.join(stopped)}: {summary}",
                              data=dict(data, stopped=stopped,
                                        **({"code": codes[0]} if codes else {})))
        ids = [pid for pid in packaged if states[pid] == IDS]
        done = [pid for pid in packaged if states[pid] == DONE_STATE]
        if not artifacts:
            # Success persists a record: the newest one of a finished platform, as it is.
            for pid in ids + done:
                prior = records.get(pid)
                self._write(visit, prior, prior.get("outcome"), f"{pid}: as recorded",
                            (prior.get("submission") or {}).get("idempotency_key") or "",
                            [], state=prior.get("state"), submission=prior.get("submission"),
                            verified_state=prior.get("verified_state"),
                            measurement_class=prior.get("measurement_class"))
                break
            artifacts = list(visit.artifacts)
        if not artifacts:
            return StepResult.blocked(f"nothing to publish: {summary}")
        if ids:
            return StepResult.success(artifacts, route="platform-ids",
                                      message=f"{', '.join(ids)}: the portal issued the ids "
                                              f"the build must carry; rebuilding with them. "
                                              f"{summary}",
                                      **dict(data, outcome=outcomes.IDS_ISSUED,
                                             platform_id=ids[0]))
        submitted = [pid for pid in done
                     if (records.get(pid) or {}).get("outcome") != outcomes.DRY_RUN]
        route = "submitted" if submitted else "dry-run"
        suffix = "" if submitted else "; nothing submitted"
        return StepResult.success(artifacts, route=route, message=summary + suffix,
                                  **dict(data, outcome=(records.get(done[0]) or {}).get("outcome")
                                         if done else None,
                                         platform_id=done[0] if done else None))

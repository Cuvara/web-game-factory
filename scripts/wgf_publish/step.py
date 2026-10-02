"""The `publish` step (release:submitting): one platform, one attempt, behind G6.

    platform-publication (validated)   ──► readiness READY, or a person's act
    decision-record (G6)               ──► approved, by a person, pinning THIS release-manifest
                                           by content hash - or nothing is submitted
    release-manifest + checkout        ──► the package, its bytes re-checked against the checksum
    core/reference/publication/<id>    ──► the adapter: api/cli/console/email/manual
    adapter.publish(job)               ──► find the draft by idempotency key, upload, configure,
                                           submit ONCE (live only), read the portal state back
                                       ──► platform-publication: state advanced only from the
                                           observed portal state; outcome, evidence, draft id

Outcomes (wgf_publish.outcomes):

    G6 missing, not human, or pinning another manifest;
    readiness not READY; a person abandoned                       BLOCKED (G6 cases, not ready)
                                                                  or FAILED (abandon)
    package missing or changed                                    FAILED (INVALID_BUILD)
    login / CAPTCHA / second factor / terms / no credential /
    a method only a person performs / an unreadable portal state  WAITING_FOR_HUMAN; the person
                                                                  acts and `wgf decide <run> done`
                                                                  records it, or `abandon`
    the portal observed holding the submission                    SUCCESS, route `submitted`
    dry run (factory.publish.mode, the default)                   SUCCESS, route `dry-run`,
                                                                  nothing submitted

The irreversible submit is attempted once per visit (the workflow's retry: max_attempts 1,
and every failure here is retryable=False). A re-entry finds the draft it already made by
its idempotency key, and a record that already says SUBMITTED or VERIFIED is returned as it
is: nothing is uploaded or submitted twice.
"""

import os

from wgflib import checkout as checkouts
from wgflib import publication as pub
from wgflib.workflow import StepOutcome, StepResult, WorkflowStep

from . import common, outcomes
from .adapters import Job, resolve
from .evidence import Evidence
from .session import CredentialError, StorageState, read_credential

__all__ = ["PublishStep", "DONE", "ABANDON"]

DONE, ABANDON = "done", "abandon"


class _Refused(Exception):
    def __init__(self, outcome, kind, code, message):
        super().__init__(message)
        self.outcome, self.kind, self.code, self.message = outcome, kind, code, message


class PublishStep(WorkflowStep):
    type = "publish"
    environ = None   # replaceable in tests
    run_process = None  # replaceable in tests: how the console executor runs Playwright

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
        prior = inputs.load("platform-publication")
        decision_record = inputs.load("decision-record")
        scaffold = inputs.load("scaffold-record") if "scaffold-record" in inputs else None
        pid = str(prior.get("platform_id"))
        release_id = manifest.get("release_id")
        try:
            settings = common.Settings(context.config, self.params, self.environ)
            settings.mode
        except ValueError as exc:
            return StepResult.failed(str(exc), retryable=False)
        env = dict(os.environ if self.environ is None else self.environ)
        key = pub.idempotency_key(context.run_id,
                                  inputs.refs["release-manifest"].content_hash, pid)
        scratch = os.path.join(context.run_dir or ".", context.current_step,
                               f"{context.visit}-{context.attempt}") if context.run_dir else None
        evidence = []
        try:
            self._refuse_unless_authorized(inputs, context, manifest, decision_record, evidence)
            self._refuse_unless_consistent(manifest, prior, release_id, pid)
            if prior.get("outcome") in (outcomes.SUBMITTED, outcomes.VERIFIED):
                # Already observed on the portal by an earlier visit: idempotent re-entry.
                return self._finish(inputs, context, prior, manifest, outcomes.VERIFIED,
                                    f"{pid}: already {prior.get('state')} (draft "
                                    f"{(prior.get('submission') or {}).get('portal_draft_id')}); "
                                    f"nothing submitted again", key, evidence,
                                    state=prior.get("state"), submission=prior.get("submission"),
                                    verified_state=prior.get("verified_state"),
                                    measurement_class=prior.get("measurement_class"))
            decision = context.decision
            if decision is not None:
                return self._after_person(inputs, context, prior, manifest, decision, key,
                                          evidence)
            readiness = prior.get("readiness")
            if readiness == pub.HUMAN_REQUIRED:
                reason = prior.get("human_required") or {}
                raise _Refused(outcomes.HUMAN_REQUIRED, "human", reason.get("reason") or
                               "manual-submission",
                               f"{pid}: {reason.get('detail') or 'a person publishes here'}; "
                               f"then `wgf decide <run-id> done --note <portal reference>` "
                               f"(or `abandon`)")
            if readiness != pub.READY:
                raise _Refused(outcomes.BLOCKED, "blocked", "not-ready",
                               f"{pid}: readiness is {readiness}, not READY; run "
                               f"platform-validate again once what it names is in place")
            root, where = common.locate_checkout(self.params or {}, context.config, scaffold, env,
                                                 section="publish", logger=context.logger)
            if root is None:
                raise _Refused(outcomes.BLOCKED, "blocked", "no-checkout",
                               getattr(where, "summary", str(where)))
            try:
                lease.take(root)
            except checkouts.CheckoutLocked as exc:
                raise _Refused(outcomes.BLOCKED, "blocked", "checkout-in-use", str(exc))
            package = next((p for p in manifest.get("packages") or []
                            if str(p.get("platform_id")) == pid), None)
            path, on_disk = common.package_on_disk(root, release_id, package)
            if not on_disk:
                raise _Refused(outcomes.INVALID_BUILD, "failed", "package-missing",
                               f"{pid}: {package.get('filename') if package else 'the package'} "
                               f"is {'missing from' if path and not os.path.isfile(path) else 'not the bytes the manifest describes in'} "
                               f"{common.release_dir(root, release_id)}")
            evidence.append(Evidence.file(f"package {package.get('filename')} re-checked against "
                                          f"the manifest checksum", path, context.run_dir,
                                          phase="package"))
            profile = common.publication_profile_for(pid, settings)
            platform_settings = settings.platform(pid)
            try:
                credential = read_credential(profile, settings.data, env)
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
            adapter = resolve(pid, profile, platform_settings)
            submit = settings.live
            evidence.append(Evidence("observation",
                                     f"mode {settings.mode}" + ("" if submit else
                                     "; the submit is not made (dry run)" if settings.mode == "dry-run" else
                                     "; WGF_PUBLISH_LIVE is not 1, so the submit is not made"),
                                     phase="policy"))
            metadata = common.store_metadata(root, release_id, manifest).get(pid) or {}
            job = Job(platform_id=pid, release_id=release_id, idempotency_key=key,
                      package_path=path, package=package, metadata=metadata, checkout=root,
                      release_dir=common.release_dir(root, release_id), run_dir=context.run_dir,
                      scratch_dir=scratch or common.release_dir(root, release_id),
                      submit=submit, env=settings.game_env(context.config),
                      hooks=context.process_hooks() if hasattr(context, "process_hooks") else {},
                      logger=context.logger, timeouts=settings.timeouts,
                      console_url=platform_settings.get("console_url"),
                      run_process=self.run_process)
            try:
                with StorageState(credential, scratch or common.release_dir(root, release_id)) as state:
                    job.storage_state = state.path
                    result = adapter.publish(job)
            except CredentialError as exc:
                raise _Refused(outcomes.HUMAN_REQUIRED, "human", "credential-missing", str(exc))
        except _Refused as refused:
            return self._refusal(inputs, context, prior, manifest, refused, key, evidence)

        evidence.extend(result.evidence)
        submission = dict(prior.get("submission") or {})
        submission.update({
            "method": adapter.method,
            "idempotency_key": key,
            "dry_run": not submit,
            "attempts": int(submission.get("attempts") or 0) + 1,
            "authorized_by": self._authorization(inputs, decision_record),
        })
        if result.draft_id:
            submission["portal_draft_id"] = result.draft_id
        if result.submitted:
            submission["submitted_at"] = common.utc_now()
            submission["submitted_by"] = f"wgf publish ({adapter.__class__.__name__})"
            submission["package_filename"] = package.get("filename")
        human_required = None
        if result.outcome in outcomes.HUMAN:
            human_required = {"reason": outcomes.human_reason_for(result.outcome,
                                                                  result.human_reason),
                              "detail": result.message,
                              **({"resume_with": result.resume_with} if result.resume_with else {})}
        return self._finish(inputs, context, prior, manifest, result.outcome, result.message,
                            key, evidence, state=result.state or prior.get("state"),
                            submission=submission, verified_state=result.verified_state,
                            measurement_class=result.measurement_class,
                            human_required=human_required)

    # -- refusals ---------------------------------------------------------------------------

    def _refuse_unless_authorized(self, inputs, context, manifest, record, evidence):
        """G6: a human decision, approving, pinning exactly this release-manifest."""
        gates = list(getattr(context, "gates_passed", None) or [])
        if "G6" not in gates:
            raise _Refused(outcomes.BLOCKED, "blocked", "g6-not-passed",
                           "G6 (publish authorization) is not passed and current in this run: "
                           "nothing is submitted. Decide it: wgf decide <run-id> approve")
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
        wanted = inputs.refs["release-manifest"].content_hash
        pinned = [s.get("content_hash") for s in record.get("subject") or []
                  if s.get("artifact_type") == "release-manifest"]
        if not pinned or wanted not in pinned:
            raise _Refused(outcomes.BLOCKED, "blocked", "g6-manifest-mismatch",
                           f"the G6 decision pins release-manifest {pinned[0][:19] if pinned else '(none)'}..., "
                           f"not the manifest this step holds ({wanted[:19]}...): the "
                           f"authorization is for another release. Decide G6 again")
        evidence.append(Evidence("artifact", f"G6 {record.get('provenance', {}).get('artifact_id')} "
                                             f"approved by a person, pinning release-manifest "
                                             f"{wanted}", phase="authorization",
                                 content_hash=wanted))

    @staticmethod
    def _refuse_unless_consistent(manifest, prior, release_id, pid):
        if prior.get("release_id") != release_id:
            raise _Refused(outcomes.BLOCKED, "blocked", "release-mismatch",
                           f"the platform-publication is for release {prior.get('release_id')}, "
                           f"the manifest for {release_id}")
        if pid not in {str(t.get("id")) for t in manifest.get("target_platforms") or []}:
            raise _Refused(outcomes.BLOCKED, "blocked", "platform-not-targeted",
                           f"{pid} is not a target of release {release_id}")

    @staticmethod
    def _authorization(inputs, record):
        return {"decision_record": str((record.get("provenance") or {}).get("artifact_id")),
                "release_manifest_hash": inputs.refs["release-manifest"].content_hash}

    def _refusal(self, inputs, context, prior, manifest, refused, key, evidence):
        context.logger.warning("publish refused", code=refused.code, outcome=refused.outcome)
        evidence.append(Evidence("observation", f"[{refused.code}] {refused.message}",
                                 phase="refusal"))
        human_required = None
        if refused.outcome in outcomes.HUMAN:
            human_required = {"reason": refused.code if refused.kind == "human" else
                              "ambiguous-portal-state", "detail": refused.message,
                              "resume_with": "wgf decide <run-id> done --note <portal reference>"}
        if refused.kind == "blocked":
            # Not an attempt: the record is left as it is, the run stops for a person.
            return StepResult(StepOutcome.BLOCKED, message=f"publish refused: [{refused.code}] "
                              f"{refused.message}", data={"code": refused.code})
        return self._finish(inputs, context, prior, manifest, refused.outcome, refused.message,
                            key, evidence, state=prior.get("state"),
                            submission=dict(prior.get("submission") or {},
                                            idempotency_key=key),
                            human_required=human_required, measurement_class="automation-check")

    # -- a person answered ------------------------------------------------------------------

    def _after_person(self, inputs, context, prior, manifest, decision, key, evidence):
        choice = decision.get("decision")
        pid = prior.get("platform_id")
        if choice == ABANDON:
            evidence.append(Evidence("observation", f"publication abandoned by "
                                                    f"{decision.get('decided_by')}: "
                                                    f"{decision.get('note') or 'no note'}",
                                     phase="person"))
            return self._finish(inputs, context, prior, manifest, outcomes.BLOCKED,
                                f"{pid}: publication abandoned by a person"
                                + (f": {decision['note']}" if decision.get("note") else ""),
                                key, evidence, state=prior.get("state"),
                                measurement_class="human")
        if choice != DONE:
            return StepResult.waiting_for_human(
                f"{choice!r} is not one of done, abandon. A person who submitted by hand "
                f"answers `done --note <portal reference>`; otherwise `abandon`",
                choices=[DONE, ABANDON])
        if decision.get("decided_by") != "human":
            return StepResult.waiting_for_human(
                "a submission made by hand is recorded by the person who made it, never by "
                "automation", choices=[DONE, ABANDON])
        note = decision.get("note") or ""
        evidence.append(Evidence("observation", f"submitted by a person ({decision.get('decided_by')}); "
                                                f"portal reference: {note or 'none given'}",
                                 phase="person"))
        submission = dict(prior.get("submission") or {})
        submission.update({"method": submission.get("method") or "manual",
                           "idempotency_key": key, "submitted_at": common.utc_now(),
                           "submitted_by": str(decision.get("decided_by") or "human"),
                           "attempts": int(submission.get("attempts") or 0) + 1,
                           **({"portal_reference": note} if note else {})})
        verified = {"observed": "submitted (recorded by a person)", "at": common.utc_now(),
                    "source": "wgf decide done"}
        return self._finish(inputs, context, prior, manifest, outcomes.SUBMITTED,
                            f"{pid}: submitted by a person" + (f" ({note})" if note else ""),
                            key, evidence, state="submitted", submission=submission,
                            verified_state=verified, measurement_class="human")

    # -- the record -------------------------------------------------------------------------

    def _finish(self, inputs, context, prior, manifest, outcome, message, key, evidence, *,
                state, submission=None, verified_state=None, measurement_class=None,
                human_required=None):
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
        if human_required:
            body["human_required"] = human_required
        artifact = common.record(body, inputs=inputs, context=context,
                                 title_id=manifest.get("title_id"), sequence=context.execution)
        context.logger.info("publication", platform=pid, outcome=outcome, state=body["state"],
                            draft=(submission or {}).get("portal_draft_id"))
        return outcomes.to_result(outcome, [artifact], message, platform_id=pid,
                                  data={"state": body["state"], "idempotency_key": key})

"""The `platform-validate` step (release:validating): is this release publishable here?

    release-manifest                 ──► the release, its packages, its targets
    verification-report              ──► the pinned profile's assertions as verify recorded
                                         them for this commit (policy.assertions:<pid>)
    checkout (release/<id>/)         ──► the package bytes against the manifest's checksum;
                                         store-metadata.json a person or the release role wrote
    core/reference/platforms/<id>    ──► metadata requirements, bundle limit
    core/reference/publication/<id>  ──► how the portal is reached, and whether a person must
                                     ──► one platform-publication per packaged platform:
                                         every guard's verdict, the assertion results, the
                                         package as found, and a `readiness`

Readiness (wgflib.publication): READY, BLOCKED, HUMAN_REQUIRED or UNKNOWN - derived from
the guards, never asserted; UNKNOWN is never READY.

Outcomes (docs/workflow-module-contract.md §7):

    a required target BLOCKED - a guard RED, an assertion
    breached, no package for it                           FAILED, route `fail`, not retryable,
                                                          the records kept as evidence
    a guard UNKNOWN (no checkout to read, no assertion
    results for this commit)                              BLOCKED: a person supplies what is
                                                          missing and resumes
    every packaged target READY or HUMAN_REQUIRED         SUCCESS

Nothing here contacts a portal, and the checkout is only read.
"""

import os

from wgflib import checkout as checkouts
from wgflib import publication as pub
from wgflib.workflow import StepOutcome, StepResult, WorkflowStep

from . import common
from .evidence import Evidence
from .session import CredentialError, read_credential

__all__ = ["PlatformValidateStep"]


class PlatformValidateStep(WorkflowStep):
    type = "platform-validate"
    environ = None  # replaceable in tests

    def execute(self, inputs, context):
        with checkouts.StepLease(context) as lease:
            return self._execute(inputs, context, lease)

    def _execute(self, inputs, context, lease):
        if "release-manifest" not in inputs:
            return StepResult.waiting_for_input(
                "platform-validate needs the release-manifest the release step drafted; run "
                "`wgf publish --run <run-id>` in the run that holds it")
        manifest = inputs.load("release-manifest")
        verification = inputs.load("verification-report") if "verification-report" in inputs \
            else None
        scaffold = inputs.load("scaffold-record") if "scaffold-record" in inputs else None
        try:
            settings = common.Settings(context.config, self.params, self.environ)
            settings.mode  # validated here, so a bad configuration fails before any record
        except ValueError as exc:
            return StepResult.failed(str(exc), retryable=False)
        env = dict(os.environ if self.environ is None else self.environ)
        root, where = common.locate_checkout(self.params or {}, context.config, scaffold, env,
                                             section="publish", logger=context.logger)
        if root is not None:
            try:
                lease.take(root)
            except checkouts.CheckoutLocked as exc:
                return StepResult.blocked(f"checkout in use: {exc}")
        else:
            context.logger.warning("no checkout to read the packages from",
                                   detail=getattr(where, "summary", str(where)))

        release_id = manifest.get("release_id")
        title_id = manifest.get("title_id")
        targets = {str(t.get("id")): t for t in manifest.get("target_platforms") or []}
        packages = {str(p.get("platform_id")): p for p in manifest.get("packages") or []}
        metadata = common.store_metadata(root, release_id, manifest)
        profiles = {pid: common.profile_for(pid) for pid in targets}

        frozen = pub.candidate_frozen(manifest)
        complete = pub.store_metadata_complete(manifest, profiles, metadata)

        artifacts, summary, blocked_required, unknown = [], [], [], []
        for pid, target in targets.items():
            package = packages.get(pid)
            if package is None:
                # No build for this target (template contract build_target). A required
                # target without a package can never make the release live.
                if target.get("role") == "required":
                    blocked_required.append(f"{pid}: no package - the one build targets another "
                                            f"platform; {pid} needs a build of its own")
                else:
                    summary.append(f"{pid}: not packaged (optional)")
                continue
            path, on_disk = common.package_on_disk(root, release_id, package)
            profile = profiles.get(pid)
            publication_profile = common.publication_profile_for(pid, settings)
            results = common.assertion_results(verification, manifest, pid)
            guards = {
                "candidate_frozen": frozen,
                "store_metadata_complete": complete,
                "package_shaped_to_profile": pub.package_shaped_to_profile(pid, profile, package,
                                                                           on_disk),
                "assertions_pass": pub.assertions_pass(pid, results),
                "metadata_and_locales_present": pub.metadata_and_locales_present(
                    pid, profile, manifest, metadata),
            }
            try:
                credential = read_credential(publication_profile, settings.data, env)
                present = credential.present if credential.kind != "none" else None
            except CredentialError:
                present = None
            human = pub.human_reason(publication_profile, settings.platform(pid), present)
            readiness = pub.readiness(guards, human)
            state = {"READY": "validated", "HUMAN_REQUIRED": "validated",
                     "BLOCKED": "validation-failed", "UNKNOWN": "packaged"}[readiness]
            evidence = [Evidence.guard(name, result) for name, result in guards.items()]
            if path:
                evidence.append(Evidence("file", f"package {package.get('filename')}: "
                                                 f"{'bytes match the manifest' if on_disk else 'missing or changed' if on_disk is False else 'not read'}",
                                         path=path if on_disk is None else os.path.relpath(path, root).replace(os.sep, "/"),
                                         content_hash=package.get("checksum") if on_disk else None,
                                         phase="package"))
            if results is not None:
                evidence.append(Evidence("artifact", f"verification-report policy.assertions:"
                                                     f"{pid}: {len(results)} result(s) for "
                                                     f"commit {str(manifest.get('commit_sha'))[:12]}",
                                         phase="assertions"))
            if publication_profile is None:
                evidence.append(Evidence("observation", f"no publication profile for {pid} "
                                                        f"(core/reference/publication/)",
                                         phase="publication-profile"))
            else:
                evidence.append(Evidence("reference", f"publication profile {pid}@"
                                                      f"{publication_profile.get('version')}: "
                                                      f"method {(publication_profile.get('submission') or {}).get('method')}, "
                                                      f"terms {(publication_profile.get('submission') or {}).get('automation_terms')}",
                                         phase="publication-profile"))
            body = {
                "release_id": release_id,
                "title_id": title_id,
                "platform_id": pid,
                "profile_version": str(target.get("profile_version")),
                "role": target.get("role"),
                "state": state,
                "readiness": readiness,
                "guards": [{"guard": name, "verdict": result.symbol, "reason": result.reason}
                           for name, result in guards.items()],
                "assertion_results": [self._criterion(r) for r in results or []],
                "package": {k: v for k, v in {
                    "filename": package.get("filename"), "size_mb": package.get("size_mb"),
                    "checksum": package.get("checksum"),
                    "content_digest": package.get("content_digest"),
                    "verified_on_disk": on_disk}.items() if v is not None},
                "evidence": common.evidence_dicts(evidence),
                "measurement_class": "automation-check",
                "workflow": {"run_id": context.run_id, "workflow_id": context.workflow_id,
                             "step_id": context.current_step, "visit": context.visit,
                             "execution": context.execution,
                             "idempotency_key": context.idempotency_key},
            }
            if human is not None:
                body["human_required"] = {"reason": human[0], "detail": human[1]}
            if publication_profile is not None:
                body["submission"] = {
                    "method": (publication_profile.get("submission") or {}).get("method"),
                    "publication_profile_version": str(publication_profile.get("version"))}
            artifacts.append(common.record(body, inputs=inputs, context=context,
                                           title_id=title_id, sequence=context.execution))
            summary.append(f"{pid}: {readiness}")
            if readiness == "BLOCKED" and target.get("role") == "required":
                blocked_required.append(f"{pid}: " + "; ".join(
                    f"{n} RED ({r.reason})" for n, r in guards.items() if r.value is False))
            elif readiness == "BLOCKED":
                summary[-1] += " (optional)"
            if readiness == "UNKNOWN":
                unknown.append(f"{pid}: " + "; ".join(
                    f"{n} UNKNOWN ({r.reason})" for n, r in guards.items() if r.value is None))

        context.logger.info("platform validation", release_id=release_id, readiness=summary,
                            checkout=root)
        if not artifacts and not blocked_required:
            return StepResult.failed(f"release {release_id} packages nothing for its targets "
                                     f"({', '.join(targets) or 'none'})", retryable=False)
        message = f"release {release_id}: " + ", ".join(summary)
        if blocked_required:
            return StepResult(StepOutcome.FAILED, route="fail", artifacts=artifacts,
                              retryable=False,
                              error=message + "; not publishable: " + " | ".join(blocked_required),
                              data={"blocked": blocked_required})
        if unknown:
            return StepResult(StepOutcome.BLOCKED, artifacts=artifacts,
                              message=message + "; undecided: " + " | ".join(unknown)
                              + ". Supply what is missing (a checkout with the release, "
                                "release/<id>/store-metadata.json) and resume",
                              data={"unknown": unknown})
        return StepResult.success(artifacts, message=message + "; nothing published",
                                  readiness=summary)

    @staticmethod
    def _criterion(result):
        out = {"criterion_id": str(result.get("criterion_id")),
               "breached": bool(result.get("breached"))}
        if "measured" in result and isinstance(result.get("measured"),
                                               (str, int, float, bool, list, type(None))):
            out["measured"] = result["measured"]
        if result.get("severity"):
            out["note"] = f"severity {result['severity']}"
        return out

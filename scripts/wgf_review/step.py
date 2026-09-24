"""The `review` step: fingerprint -> reviewer -> fingerprint -> verdict -> review-report.

    inputs   prototype-report, scaffold-record (required); game-design (read when present)
    output   review-report, on every outcome that ran a review - a failed review is evidence
    effect   none. The reviewer's only write is its verdict file, under the run directory.

Outcomes, per docs/workflow-module-contract.md section 7:

    SUCCESS             approve; or kind `none`, recorded as verdict `skipped`
    FAILED route        request-changes: route `request-changes`, not retryable. The
                        workflow routes it to develop; unrouted, it fails the run.
    FAILED final        isolation violated (checkout restored), malformed verdict, a
                        reviewer that could not start, a cancelled review, bad config, or a
                        prototype-report for a commit that is not the checkout's HEAD
    FAILED retryable    reviewer timed out, went idle, or exited non-zero
    WAITING_FOR_INPUT   prototype-report or scaffold-record is not in the run
    BLOCKED             no checkout; the checkout is dirty; or a violation that could not
                        be undone - each needs a person before a review means anything

Why request-changes is FAILED and not SUCCESS with a route: an unrouted SUCCESS goes to the
next step. A workflow that forgot to route `request-changes` would then carry a build its
reviewer rejected into the SDK step and on towards release. FAILED fails closed; it is the
same shape verification uses for `fail`, for the same reason.
"""

import datetime
import json
import os
import time

from wgflib import procs
from wgflib.workflow import ArtifactOutput, StepResult, WorkflowStep

from . import isolation
from .report import PROMPT, PROMPT_STDOUT, build_report, render_brief
from .settings import Settings, SettingsError
from .verdict import from_output, parse

__all__ = ["ReviewStep", "REQUEST_CHANGES"]

REQUIRED_INPUTS = ("prototype-report", "scaffold-record")
SUPPORTED_MAJOR = "1"
REQUEST_CHANGES = "request-changes"
DEVELOP_BRIEF = "docs/development/brief.json"


def _utc_now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _inside(path, directory):
    path, directory = os.path.realpath(path), os.path.realpath(directory)
    return path == directory or path.startswith(directory.rstrip(os.sep) + os.sep)


class ReviewStep(WorkflowStep):
    type = "review"

    clock = staticmethod(_utc_now)

    def execute(self, inputs, context):
        try:
            settings = Settings.resolve(context.config, self.params)
        except SettingsError as exc:
            return StepResult.failed(str(exc), retryable=False)

        missing = [t for t in REQUIRED_INPUTS if t not in inputs]
        if missing:
            return StepResult.waiting_for_input(
                f"review needs {', '.join(missing)} in the run: there is nothing to review")
        for artifact_type in REQUIRED_INPUTS + ("game-design",):
            ref = inputs.refs.get(artifact_type)
            version = getattr(ref, "schema_version", None) or ""
            if ref is not None and version and version.split(".")[0] != SUPPORTED_MAJOR:
                return StepResult.failed(
                    f"{artifact_type} is schema {version}; review reads {SUPPORTED_MAJOR}.x",
                    retryable=False)

        prototype = inputs.load("prototype-report")
        scaffold = inputs.load("scaffold-record")
        design = inputs.load("game-design") if "game-design" in inputs else None
        title_id = scaffold.get("title_id") or prototype.get("title_id")
        subject = (prototype.get("build_ref") or {}).get("commit_sha") or ""
        self._ctx = dict(title_id=title_id, context=context,
                         pins=self._pins(inputs), settings=settings)

        if settings.kind == "none":
            report = self._report(commit=subject if len(subject) == 40 else "0" * 40,
                                  baseline=None, verdict="skipped", reviewer={"kind": "none"},
                                  isolation={"checked_paths": 0, "violations": [],
                                             "intact": True, "restored": None},
                                  notes="No reviewer is configured (factory.review.reviewer."
                                        "kind: none). NO REVIEW HAPPENED; this is not an "
                                        "approval.")
            return StepResult.success([report], message=(
                "review skipped: no reviewer configured - the build is unreviewed"))

        repository = scaffold.get("repository") or {}
        try:
            checkout = settings.checkout_for(repository.get("name") or title_id)
        except SettingsError as exc:
            return StepResult.failed(f"scaffold-record: {exc}", retryable=False)
        git = isolation.Git(checkout)
        if not git.is_repository():
            return StepResult.blocked(
                f"the game repository is not checked out at {checkout}; nothing to review")
        head = git.head()
        if not head or head != subject:
            return StepResult.failed(
                f"the prototype-report is for {subject[:12] or 'no commit'} but {checkout} is "
                f"at {(head or 'no commit')[:12]}; review only what development committed",
                retryable=False)
        dirty = git.dirty()
        if dirty:
            return StepResult.blocked(
                f"{checkout} has uncommitted changes ({', '.join(dirty[:5])}"
                f"{' ...' if len(dirty) > 5 else ''}); a review must see exactly the commit, "
                f"and a dirty tree could not be restored after one. Commit or discard them and "
                f"resume.")

        review_dir = os.path.join(context.run_dir, "review")
        stem = f"{context.visit}-{context.attempt}"
        verdict_path = os.path.join(review_dir, f"{stem}.verdict.json")
        brief_path = os.path.join(review_dir, f"{stem}.brief.md")
        log_path = os.path.join(review_dir, f"{stem}.log")
        for path in (verdict_path, brief_path):
            if _inside(path, checkout):
                return StepResult.failed(
                    f"the review directory {review_dir} is inside the checkout; the verdict "
                    f"must be written outside what is under review", retryable=False)
        os.makedirs(review_dir, exist_ok=True)
        for stale in (verdict_path, log_path):
            if os.path.exists(stale):
                os.remove(stale)

        develop_brief = None
        try:
            with open(os.path.join(checkout, DEVELOP_BRIEF), encoding="utf-8") as handle:
                develop_brief = json.load(handle)
        except (OSError, ValueError):
            pass
        baseline = (develop_brief or {}).get("baseline_commit")
        with open(brief_path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(render_brief(title_id=title_id, commit=head, baseline=baseline,
                                      design=design, prototype=prototype,
                                      develop_brief=develop_brief, verdict_path=verdict_path,
                                      repo=checkout,
                                      to_stdout=settings.verdict_from == "stdout"))

        values = {"repo": checkout, "verdict": verdict_path, "brief": brief_path,
                  "commit": head}
        values["prompt"] = (PROMPT_STDOUT if settings.verdict_from == "stdout"
                            else PROMPT).format(**values)
        argv = [part.format(**values) for part in settings.argv]
        env = dict(os.environ)
        env.update({"WGF_REVIEW_REPO": checkout, "WGF_REVIEW_VERDICT": verdict_path,
                    "WGF_REVIEW_BRIEF": brief_path, "WGF_REVIEW_COMMIT": head})

        try:
            before = isolation.take(git, settings.guarded_paths, settings.fingerprint_ignored)
        except (isolation.GitError, OSError) as exc:
            return StepResult.blocked(f"cannot fingerprint {checkout} before the review, so "
                                      f"a review could not be checked for writes: {exc}")
        context.logger.info("review command", argv0=os.path.basename(argv[0]),
                            commit=head, timeout_s=settings.timeout,
                            idle_timeout_s=settings.idle_timeout,
                            checked_paths=before.checked_paths)
        began = time.monotonic()
        result = procs.run(argv, cwd=checkout, env=env, timeout=settings.timeout,
                           idle_timeout=settings.idle_timeout, log_path=log_path,
                           heartbeat_seconds=15.0)
        duration = time.monotonic() - began
        try:
            after = isolation.take(git, settings.guarded_paths, settings.fingerprint_ignored)
            violations = isolation.diff(before, after)
        except (isolation.GitError, OSError) as exc:
            # The reviewer left the checkout in a state git cannot even read (a broken
            # config, a removed .git). That is a write; never a pass.
            violations = [{"path": "(checkout)", "change": "modified", "scope": "checkout",
                           "sensitive": True}]
            context.logger.error("review after-snapshot failed", error=str(exc))

        reviewer = {"kind": "command", "argv0": os.path.basename(argv[0]),
                    "exit_code": result.returncode, "status": result.status,
                    "killed_pids": list(result.killed)}
        common = dict(commit=head, baseline=baseline, reviewer=reviewer, duration_s=duration,
                      timed_out=result.timed_out or result.idle_timed_out)

        if violations:
            restored, problems = isolation.restore(git, before, settings.guarded_paths)
            listed = ", ".join(f"{v['path']} ({v['change']})" for v in violations[:8])
            more = f" and {len(violations) - 8} more" if len(violations) > 8 else ""
            message = (f"the reviewer changed what it may only read: {listed}{more}. "
                       + ("The checkout was restored to the pre-review state."
                          if restored else "RESTORING FAILED: " + "; ".join(problems[:5])))
            report = self._report(
                verdict="no-verdict",
                failure={"code": "reviewer-isolation-violation", "message": message,
                         "retryable": False},
                isolation={"checked_paths": before.checked_paths, "violations": violations,
                           "intact": False, "restored": restored},
                **common)
            context.logger.error("review isolation violated", violations=len(violations),
                                 restored=restored)
            if not restored:
                return StepResult("BLOCKED", artifacts=[report], message=message)
            return StepResult("FAILED", artifacts=[report], retryable=False, error=message)

        intact = {"checked_paths": before.checked_paths, "violations": [], "intact": True,
                  "restored": None}
        failure = self._process_failure(result, settings)
        if failure is not None:
            report = self._report(verdict="no-verdict", failure=failure, isolation=intact,
                                  **common)
            return StepResult("FAILED", artifacts=[report], retryable=failure["retryable"],
                              error=failure["message"],
                              data={"output_tail": result.tail(20)})

        if settings.verdict_from == "stdout":
            # Saved where a file-writing reviewer would have put it, so every verdict has
            # the same record beside the run.
            extracted = from_output(result.stdout)
            if extracted is not None:
                with open(verdict_path, "w", encoding="utf-8") as handle:
                    handle.write(extracted)
        verdict, problem = parse(verdict_path, head)
        if verdict is None and settings.verdict_from == "stdout" and problem.startswith("no "):
            problem = "the reviewer's output ends with no JSON verdict"
        if verdict is None:
            failure = {"code": "malformed-verdict", "message": problem, "retryable": False}
            report = self._report(verdict="no-verdict", failure=failure, isolation=intact,
                                  **common)
            return StepResult("FAILED", artifacts=[report], retryable=False,
                              error=f"malformed verdict: {problem}")

        report = self._report(verdict=verdict["verdict"], blockers=verdict["blockers"],
                              notes=verdict.get("notes"), isolation=intact, **common)
        if verdict["verdict"] == "approve":
            return StepResult.success([report], message=f"review approved {head[:12]}")
        summary = "; ".join(f"{b['id']}: {b['summary']}" for b in verdict["blockers"][:5])
        return StepResult("FAILED", route=REQUEST_CHANGES, artifacts=[report], retryable=False,
                          error=f"review requested changes to {head[:12]} - "
                                f"{len(verdict['blockers'])} blocker(s): {summary}")

    # -- helpers -------------------------------------------------------------------------

    @staticmethod
    def _process_failure(result, settings):
        if result.error is not None:
            return {"code": "reviewer-not-started", "retryable": False,
                    "message": f"reviewer command could not start: {result.error}"}
        if result.cancelled:
            return {"code": "cancelled", "retryable": False,
                    "message": "review cancelled; the reviewer's process tree was ended"}
        if result.timed_out:
            return {"code": "reviewer-timeout", "retryable": True,
                    "message": f"reviewer timed out after {settings.timeout:.0f}s; its "
                               f"process tree was ended"}
        if result.idle_timed_out:
            return {"code": "reviewer-idle-timeout", "retryable": True,
                    "message": f"reviewer produced no output for {settings.idle_timeout:.0f}s;"
                               f" its process tree was ended"}
        if result.returncode != 0:
            return {"code": "reviewer-crashed", "retryable": True,
                    "message": f"reviewer command exited {result.returncode}"}
        return None

    def _report(self, *, commit, baseline, verdict, reviewer, isolation, duration_s=0.0,
                timed_out=False, blockers=(), notes=None, failure=None):
        ctx = self._ctx
        context = ctx["context"]
        content = build_report(
            title_id=ctx["title_id"], commit=commit, baseline=baseline, verdict=verdict,
            blockers=[dict(b) for b in blockers], notes=notes, failure=failure,
            reviewer=reviewer, isolation=isolation, iteration=context.visit,
            attempt=context.attempt, duration_s=duration_s, timed_out=timed_out,
            pinned_inputs=ctx["pins"], artifact_seq=context.execution,
            produced_at=self.clock())
        return ArtifactOutput("review-report", content, metadata={
            "commit": commit, "verdict": verdict, "blockers": len(blockers),
            "failure": (failure or {}).get("code")})

    @staticmethod
    def _pins(inputs):
        pins = []
        for artifact_type, ref in sorted(inputs.refs.items()):
            content = inputs.load(artifact_type)
            provenance = content.get("provenance") if isinstance(content, dict) else None
            if provenance and ref.content_hash:
                pins.append({"artifact_id": provenance["artifact_id"],
                             "artifact_type": artifact_type,
                             "content_hash": ref.content_hash})
        return pins

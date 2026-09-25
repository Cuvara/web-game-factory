"""The `develop` step: brief -> developer -> checks -> commit -> prototype-report.

    inputs   game-design, asset-manifest, scaffold-record (required)
             title-strategy (read when present), qa-report (on a verify -> develop loop),
             review-report (on a review -> develop loop: its blockers lead the brief)
    output   prototype-report
    effect   one commit in the game repository per visit, keyed by the idempotency key

Outcomes, per docs/workflow-module-contract.md section 7:

    SUCCESS            every check passed and the work is committed
    WAITING_FOR_INPUT  a required input is not in the run
    WAITING_FOR_HUMAN  handoff developer: the brief is out, or the last checks failed
    BLOCKED            the game repository is not checked out where the config says; or a
                       guarded Factory path was changed and could not be put back
    FAILED retryable   command developer failed, or its result failed a check
    FAILED final       bad input, bad config, the development was declined, a guarded
                       Factory path was changed (and restored), or the tree holds a change
                       outside the paths a developer may write

The developer's boundary is enforced here, not requested in the brief:

    git        pinned to the git directory resolved before the developer ran, with
               every command the checkout's config could name neutralised (repository.py)
    Factory    factory.review.guarded_paths - the Factory's code, gates, contracts and
               config - fingerprinted before the developer and compared after it and after
               the checks (which run code it wrote); a change is undone and fails the step
               (wgflib/isolation.py). Recorded as the `isolation` check in checks.json.
    commit     only the paths a developer may write (scope.py); anything else left in the
               tree fails the step (`commit-scope` in checks.json) and is never committed
    env        the developer command gets an allowlisted environment (wgflib/agentenv.py)
"""

import datetime
import json
import os

from wgflib import isolation
from wgflib.workflow import ArtifactOutput, StepResult, WorkflowStep

from . import brief as briefs
from . import scope
from .checks import read_report, run_checks
from .developers import Outcome, create_developer
from .report import build_report
from .seam import ensure_seam
from .repository import GitError, GitRepo, Runner, read_game_config
from .settings import Settings, SettingsError

__all__ = ["DevelopStep"]

REQUIRED_INPUTS = ("game-design", "asset-manifest", "scaffold-record")
SUPPORTED_MAJOR = "1"


def _utc_now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def _record_checks(path, checked_at, key, engine, checks, green):
    """docs/development/checks.json: this visit's checks, which the next attempt's brief
    carries as failures to fix."""
    _write(path, json.dumps({"idempotency_key": key, "engine": engine,
                             "checked_at": checked_at, "green": green, "checks": checks},
                            indent=2) + "\n")


def _read_json(path):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


class _Guard:
    """The Factory's guarded paths, fingerprinted once before the developer (or, on a
    re-executed visit, before its checks) and compared after each thing that ran the
    developer's code. The game checkout is not fingerprinted: writing it is the job."""

    def __init__(self, paths, clock):
        self.paths = list(paths)
        self.clock = clock
        self.before = None

    def take(self):
        if self.before is not None:
            return None
        try:
            self.before = isolation.take_guarded(self.paths)
        except OSError as exc:
            return StepResult.blocked(
                f"cannot fingerprint the Factory's guarded paths before development, so the "
                f"developer could not be checked for writes to them: {exc}")
        return None

    def check(self, *, key, engine, checks_json, logger, write, checks=()):
        """None when the guarded paths are as they were; else restore them and return the
        step's result: FAILED not retryable, or BLOCKED when they could not be put back."""
        if self.before is None:
            return None
        try:
            violations = isolation.diff(self.before, isolation.take_guarded(self.paths))
        except OSError as exc:
            violations = [{"path": f"(guarded paths: {exc})", "change": "unreadable",
                           "scope": "factory", "sensitive": True}]
        if not violations:
            return None
        restored, problems = isolation.restore_guarded(self.before, self.paths)
        listed = ", ".join(f"{v['path']} ({v['change']})" for v in violations[:8])
        more = f" and {len(violations) - 8} more" if len(violations) > 8 else ""
        message = (f"the developer changed the Factory's guarded paths, which decide what "
                   f"every check of its work is worth: {listed}{more}. "
                   + ("They were restored to their state before development; nothing was "
                      "committed." if restored else
                      "RESTORING FAILED: " + "; ".join(problems[:5])))
        logger.error("develop isolation violated", violations=len(violations),
                     restored=restored)
        if write:
            _record_checks(checks_json, self.clock(), key, engine, [c.to_dict() for c in checks]
                           + [{"id": "isolation", "status": "failed", "summary": message,
                               "findings": [f"{v['path']} ({v['change']})"
                                            for v in violations]}], False)
        if not restored:
            return StepResult.blocked(message)
        return StepResult.failed(message, retryable=False)


class DevelopStep(WorkflowStep):
    type = "develop"

    # Seams for tests: replace the process runner and the clock, nothing else.
    runner_factory = Runner
    clock = staticmethod(_utc_now)

    def execute(self, inputs, context):
        try:
            settings = Settings.resolve(context.config, self.params)
        except SettingsError as exc:
            return StepResult.failed(str(exc), retryable=False)

        missing = [t for t in REQUIRED_INPUTS if t not in inputs]
        if missing:
            return StepResult.waiting_for_input(
                f"develop needs {', '.join(missing)} in the run before it can brief a build")
        for artifact_type in REQUIRED_INPUTS + ("title-strategy", "qa-report", "review-report"):
            ref = inputs.refs.get(artifact_type)
            version = getattr(ref, "schema_version", None) or ""
            if ref is not None and version and version.split(".")[0] != SUPPORTED_MAJOR:
                return StepResult.failed(
                    f"{artifact_type} is schema {version}; develop reads {SUPPORTED_MAJOR}.x",
                    retryable=False)

        design = inputs.load("game-design")
        assets = inputs.load("asset-manifest")
        scaffold = inputs.load("scaffold-record")
        strategy = inputs.load("title-strategy") if "title-strategy" in inputs else None
        qa = inputs.load("qa-report") if "qa-report" in inputs else None
        review = inputs.load("review-report") if "review-report" in inputs else None
        # A qa-report on the first visit is a leftover from an earlier release, not feedback
        # on this build; only a loop back from verify carries defects to fix.
        if qa is not None and (context.visit <= 1 or qa.get("verdict") == "pass"):
            qa = None
        title_id = scaffold.get("title_id") or design.get("title_id")

        repository = (scaffold.get("repository") or {})
        checkout = settings.checkout_for(repository.get("name") or title_id)
        runner = self.runner_factory()
        git = GitRepo(checkout, runner, author=settings.data.get("author"),
                      allow_filters=settings.allow_filters)
        # is_repository pins the git directory: from here on every git command names the
        # one found now, before any developer could write .git or core.worktree.
        if not git.is_repository():
            return StepResult.blocked(
                f"the game repository {repository.get('owner')}/{repository.get('name')} is "
                f"not checked out at {checkout}. Clone it there (or set "
                f"factory.develop.checkouts) and resume.")
        try:
            game_config = read_game_config(checkout)
        except ValueError as exc:
            return StepResult.failed(str(exc), retryable=False)
        engine = game_config["engine"]["type"]
        # Only a request for changes to the commit this visit starts from is feedback on
        # this build. An approval, a skipped or failed review, or a review of some other
        # commit (an earlier loop, another run) carries nothing to fix.
        if review is not None and not (
                context.visit > 1 and review.get("verdict") == "request-changes"
                and review.get("blockers") and review.get("reviewed_commit") == git.head()):
            review = None

        key = context.idempotency_key
        brief_dir = os.path.join(checkout, briefs.BRIEF_DIR)
        brief_md = os.path.join(brief_dir, "brief.md")
        brief_json = os.path.join(brief_dir, "brief.json")
        checks_json = os.path.join(brief_dir, "checks.json")

        try:
            committed = git.keyed_commit(key)
        except GitError as exc:
            return StepResult.failed(str(exc))

        if not committed and not git.head():
            # No baseline: nothing to check the template's paths against, nothing to scope
            # a commit by, and nothing a report could name. Before any developer runs.
            return StepResult.blocked(
                f"the build commit cannot be established: {checkout} has no readable HEAD "
                f"(git rev-parse HEAD failed). Commit the checkout's initial state, then "
                f"resume.")
        existing = _read_json(brief_json) or {}
        guard = _Guard(settings.guarded_paths, self.clock)
        record = dict(key=key, engine=engine, checks_json=checks_json, logger=context.logger,
                      write=not committed)
        if committed:
            # This visit already committed. Do not develop again: re-check what is there
            # and report it, so a crash after the commit costs a check run, not a rebuild.
            context.logger.info("develop reusing keyed commit", commit=committed)
            brief = existing if existing.get("idempotency_key") == key else None
            if brief is None:
                return StepResult.failed(
                    f"commit {committed[:12]} carries this visit's key but {briefs.BRIEF_DIR}"
                    f"/brief.json does not; the checkout was edited by hand", retryable=False)
        else:
            baseline = (existing.get("baseline_commit")
                        if existing.get("idempotency_key") == key else None) or git.head()
            previous_checks = _read_json(checks_json)
            if (previous_checks or {}).get("idempotency_key") != key:
                previous_checks = None  # another visit's failures are not this one's
            brief = briefs.build_brief(
                title_id=title_id, engine=engine, iteration=context.visit, key=key,
                baseline=baseline, design=design, assets=assets, scaffold=scaffold,
                strategy=strategy, qa=qa, previous_checks=previous_checks,
                refs=inputs.refs, skills=settings.skills, review=review,
                mobile_test=bool((game_config.get("verification") or {}).get("mobile_test",
                                                                            True)),
                writable_paths=settings.writable_paths,
                package_changes=settings.package_changes,
            )
            _write(brief_json, json.dumps(brief, indent=2, ensure_ascii=False) + "\n")
            _write(brief_md, briefs.render_markdown(brief))
            written = ensure_seam(checkout)
            if written:
                context.logger.info("integration seam provided", paths=written)

            developer = create_developer(settings, runner)
            refused = guard.take()
            if refused is not None:
                return refused
            outcome = developer.develop(brief_md, checkout, context)
            if outcome.status == Outcome.WAITING:
                return StepResult.waiting_for_human(outcome.message, brief=brief_md)
            if outcome.status == Outcome.DECLINED:
                return StepResult.failed(outcome.message, retryable=False)
            # Whatever the developer's outcome, it ran: nothing is carried forward - no
            # failure note, no check, no commit - before the Factory knows it wrote only
            # where it may.
            refused = guard.check(**record)
            if refused is not None:
                return refused
            if outcome.status == Outcome.FAILED:
                # The next attempt is a new session that knows only its brief. Without this
                # it saw no failure at all and took the half-built tree for a finished one:
                # the real acceptance run's retry after a developer that hit its turn limit
                # did 16 turns and stopped. Earlier failed checks of this visit carry over.
                carried = [c for c in (previous_checks or {}).get("checks") or []
                           if c.get("status") == "failed" and c.get("id") != "developer"]
                self._record(checks_json, key, engine, [{
                    "id": "developer",
                    "status": "failed",
                    "summary": (f"The previous attempt's developer ended before it finished "
                                f"({outcome.message}). Its partial work is still in the "
                                "checkout: continue from it rather than starting over, "
                                "finish every required system, make every check pass, "
                                f"and write {briefs.REPORT_PATH}."),
                }] + carried, False)
                return StepResult.failed(outcome.message, output_tail=outcome.output_tail)
            # Before the checks, which are minutes: a file that can never be committed
            # fails now, not after them.
            refused = self._scope(git, settings, **record)
            if refused is not None:
                return refused

        refused = guard.take()  # a re-executed, committed visit: around its checks alone
        if refused is not None:
            return refused
        checks = run_checks(checkout, brief, settings, runner, git, logger=context.logger)
        green = all(not c.failed for c in checks)
        # The checks run code the developer wrote (its tests, its build): the same boundary.
        refused = guard.check(checks=checks, **record)
        if refused is not None:
            return refused
        if not committed:  # a committed visit's record is part of its commit; leave it be
            self._record(checks_json, key, engine, [c.to_dict() for c in checks], green)

        dev_report, _ = read_report(checkout)
        commit_sha = committed
        if not committed:
            # Again after the checks: one that writes outside the ignored paths has put a
            # file in the tree that nobody decided to commit.
            refused = self._scope(git, settings, checks=checks, **record)
            if refused is not None:
                return refused
        if green and not committed and settings.commit:
            try:
                allowed, _ = scope.partition(git.changes(), settings.writable_paths)
                commit_sha, _ = git.commit_paths(
                    f"feat(game): development iteration {context.visit}",
                    f"Implements {briefs.BRIEF_DIR}/brief.md for {title_id} ({engine}).\n"
                    f"Checks: " + ", ".join(f"{c.id} {c.status}" for c in checks),
                    key, allowed,
                )
            except GitError as exc:
                return StepResult.failed(str(exc))
        commit_sha = commit_sha or git.head()
        if not commit_sha:
            # A placeholder commit would flow downstream as if it were a build: review, sdk,
            # verify and release all pin what this report names.
            return StepResult.blocked(
                f"the build commit cannot be established: {checkout} has no readable HEAD "
                f"(git rev-parse HEAD failed). Commit the checkout's initial state, then "
                f"resume.")

        produced_at = self.clock()
        report = build_report(
            title_id=title_id, brief=brief, checks=checks, dev_report=dev_report,
            commit_sha=commit_sha, built_at=produced_at,
            build_url=self._build_url(settings, repository, checkout, commit_sha, git),
            iteration=context.visit, strategy=strategy,
            pinned_inputs=self._pins(inputs), artifact_seq=context.execution,
            produced_at=produced_at,
        )
        artifact = ArtifactOutput("prototype-report", report, metadata={
            "commit": commit_sha, "engine": engine, "green": green,
            "checks": {c.id: c.status for c in checks},
        })

        if green:
            return StepResult.success([artifact], message=(
                f"{title_id} built at {commit_sha[:12]} ({engine}); "
                + ", ".join(f"{c.id} {c.status}" for c in checks)))

        failed = [c for c in checks if c.failed]
        summary = "; ".join(f"{c.id}: {c.summary}" for c in failed)
        developer = create_developer(settings, runner)
        if developer.retry_on_check_failure:
            return StepResult("FAILED", artifacts=[artifact], retryable=True,
                              error=f"checks failed - {summary}")
        return StepResult("WAITING_FOR_HUMAN", artifacts=[artifact], message=(
            f"checks failed - {summary}. Details in {checks_json}. Fix them and resume with "
            f"--decision done."))

    # -- helpers -------------------------------------------------------------------------

    def _record(self, checks_json, key, engine, checks, green):
        _record_checks(checks_json, self.clock(), key, engine, checks, green)

    def _scope(self, git, settings, *, key, engine, checks_json, logger, write, checks=()):
        """FAILED, not retryable, when the tree holds a change the development commit may
        not contain; None when every change is in scope."""
        try:
            _, refused = scope.partition(git.changes(), settings.writable_paths)
        except GitError as exc:
            return StepResult.failed(f"cannot read what the developer changed: {exc}",
                                     retryable=False)
        if not refused:
            return None
        listed = "; ".join(f"{path}: {why}" for path, why in refused[:8])
        more = f" and {len(refused) - 8} more" if len(refused) > 8 else ""
        message = (f"the checkout holds {len(refused)} change(s) a development commit may not "
                   f"contain - {listed}{more}. Nothing was committed. Remove them (the brief "
                   f"lists what a developer may write: {', '.join(settings.writable_paths)}), "
                   "then run develop again.")
        logger.error("develop commit scope violated", paths=[p for p, _ in refused])
        if write:
            self._record(checks_json, key, engine, [c.to_dict() for c in checks] + [{
                "id": "commit-scope", "status": "failed", "summary": message,
                "findings": [f"{path}: {why}" for path, why in refused]}], False)
        return StepResult.failed(message, retryable=False)

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

    @staticmethod
    def _build_url(settings, repository, checkout, sha, git):
        template = settings.build_url
        if template:
            return template.format(owner=repository.get("owner", ""),
                                   name=repository.get("name", ""), sha=sha,
                                   branch=git.branch() or "", short_sha=sha[:8])
        if repository.get("url"):
            return f"{repository['url'].rstrip('/')}/tree/{sha}"
        return f"file://{checkout}"

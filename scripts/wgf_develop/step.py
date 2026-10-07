"""The `develop` step: brief -> developer -> checks -> commit -> prototype-report.

    inputs   game-design, scaffold-record, asset-manifest (required; not in the greybox
             phase, `with: {phase: greybox}`, which runs before assets exist)
             title-strategy, tech-plan (read when present: the tech plan's prototype tasks
             join the brief beside the design's build_spec),
             qa-report (on a verify -> develop loop),
             review-report (on a review -> develop loop: its blockers lead the brief),
             playability-report (on a playability -> develop loop: its failed checks
             and frames lead the brief),
             production-quality-report, visual-qa-report (on a loop back from the
             production gates, directly or through assets: their failures lead the brief)
    output   prototype-report
    effect   one commit in the game repository per visit, keyed by the idempotency key

Outcomes, per docs/workflow-module-contract.md section 7:

    SUCCESS            every check passed and the work is committed
    FAILED design-gap  every check passed and the work is committed, and the developer
                       reported a blocking design gap: the design does not say enough to
                       build what was asked. Routed back to design (`design-gap`), which
                       repairs the design from the prototype-report's `design_gaps`. Not
                       retryable - another developer session would meet the same silence.
    WAITING_FOR_INPUT  a required input is not in the run
    WAITING_FOR_HUMAN  handoff developer: the brief is out, or the last checks failed
    BLOCKED            the game repository is not checked out where the config says; a
                       guarded Factory path was changed and could not be put back; or the
                       run's developer-session budget is spent (budget.py) - no agent is
                       started, and only a person's `wgf resume --budget-sessions` raises it;
                       or, for a command developer, the run has no budget at all - set
                       factory.develop.budget and resume, which adopts it
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

import copy
import datetime
import json
import os
import shutil

from wgflib import checkout as checkout_lock
from wgflib import check_strength, isolation
from wgflib.workflow import ArtifactOutput, StepResult, WorkflowStep
from wgflib.workflow.quality import run_tier

from . import brief as briefs
from . import floor as content_floor
from . import safewrite, scope
from . import specialist as specialists
from .budget import Budget
from .checks import read_report, run_checks
from .gdd import GDD_PATH, render_gdd
from .developers import Outcome, create_developer
from .report import blocking_gaps, build_report, design_gaps
from .seam import ensure_seam
from .repository import GitError, GitRepo, Runner, read_game_config
from .settings import Settings, SettingsError

__all__ = ["DevelopStep", "DESIGN_GAP_ROUTE"]

# The route a blocking design gap takes out of this step. The workflow maps it
# (`develop.on.design-gap: design`, `greybox.on.design-gap: design`); the engine knows no
# route of its own, so the label is the module's.
DESIGN_GAP_ROUTE = "design-gap"

REQUIRED_INPUTS = ("game-design", "asset-manifest", "scaffold-record")
# `with: {phase: greybox}`: the loop is built and played before any asset exists, so the
# asset manifest is not an input yet. `production` (or no phase) integrates the assets.
PHASES = ("greybox", "production")
SUPPORTED_MAJOR = "1"


def _utc_now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _write(checkout, path, text):
    """A Factory file into the checkout: never through a link the developer left there
    (safewrite). Raises UnsafeCheckoutPath, which fails the step."""
    safewrite.write_text(checkout, path, text)


def skip_policy(context, brief):
    """Whether a skipped check is held against this build (core/reference/quality-policy.yaml
    rule 5): the run's quality tier, else the tier the brief was built for (the tech plan's),
    else unknown - reported, not held."""
    tier = (run_tier(getattr(context, "environment", None))
            or (brief.get("build_scope") or {}).get("quality_tier"))
    return check_strength.for_tier(tier)


def _record_checks(checkout, path, checked_at, key, engine, checks, green):
    """docs/development/checks.json: this visit's checks, which the next attempt's brief
    carries as failures to fix."""
    _write(checkout, path, json.dumps({"idempotency_key": key, "engine": engine,
                             "checked_at": checked_at, "green": green, "checks": checks},
                            indent=2) + "\n")


def _review_baseline(existing, key, phase, baseline):
    """Where the change a reviewer reads starts: before the oldest commit no review has read.

    That is this visit's baseline, except after a greybox. The greybox is played, not
    reviewed, so its commits are carried - from the brief it committed (`existing`) - into
    the production build's first brief, and review reads the whole loop as well as what the
    production phase put on it. A re-execution keeps the value its brief already holds."""
    if existing.get("idempotency_key") == key and existing.get("review_baseline"):
        return existing["review_baseline"]
    if phase in PHASES and existing.get("phase") == "greybox":
        return existing.get("review_baseline") or existing.get("baseline_commit") or baseline
    return baseline


def _read_json(path):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def _loop(context, spec=None, via=None):
    """How the run came back into develop, from the engine's context: the entry
    (`context.entered_by`, `<source>.<route>` such as `verify.fail`) and what the loop, and
    develop itself, have left of their visit limits (`context.visit_budget`). None on a
    first visit - entered by ordinary progression (`<step>.success`, or a bare `success` in
    a run recorded before entries named their source) - or a context that says nothing.
    A specialist visit (`spec`) was entered through triage; the entry it reports is the
    gate's that sent the build back (the triage-report's `source`), and the budget is the
    specialist's own. `via` is the triage-report's `source` when triage routed nothing to a
    specialist (`triage.success`): the gate entry that sent the build back, if one did."""
    route = getattr(context, "entered_by", None)
    budget = getattr(context, "visit_budget", None) or {}
    if spec is None and via and route and route.rpartition(".")[0] == specialists.TRIAGE_SOURCE:
        route = via
    if spec is not None:
        source = spec.get("source") or route
        loop = {"entered_by": source, "specialist_entry": route,
                "route_budget": budget.get("route"), "step_budget": budget.get("step")}
        decision = (_decision_behind(context, source)
                    if source and source.rpartition(".")[2] != "success" else None)
        if decision:
            loop["decision"] = decision
        return loop
    if not route or route.rpartition(".")[2] == "success":
        return None
    loop = {"entered_by": route, "route_budget": budget.get("route"),
            "step_budget": budget.get("step")}
    decision = _decision_behind(context, route)
    if decision:
        loop["decision"] = decision
    return loop


def _sessions(context, tech_plan=None):
    """What the run's developer budget has spent before this visit, for the brief; None when
    the run has no budget. Read before the brief is written: the brief used to show only
    develop's max_visits loop guard, which a reader took for the session budget."""
    budget = Budget.load(context, tech_plan)
    return budget.summary() if budget.active else None


def _decision_behind(context, route):
    """The recorded decision that sent the run back here, when a checkpoint made one: the
    newest DECISION_RECORDED of the route's source step, if its choice is the route's. G4's
    `iterate` is the case that matters - its note is the only statement of why the prototype
    came back, and nothing else carries it to the developer (found by the 2.1.2 production
    run: the brief said "fix what sent it back" and nothing said what that was)."""
    source, _, choice = route.rpartition(".")
    reader = getattr(context, "read_events", None)
    events = list(reader()) if callable(reader) else []
    for event in reversed(events):
        if event.get("event") != "DECISION_RECORDED" or event.get("step_id") != source:
            continue
        data = event.get("data") or {}
        if data.get("decision") != choice:
            return None  # the newest decision there is not the one this route stands for
        return {"step": source, "decision": choice, "note": data.get("note") or None,
                "decided_by": data.get("decided_by"), "decided_at": data.get("decided_at")}
    return None



def _accepted_baseline(inputs):
    """The brief's accepted-baseline block (wgf_baseline.brief), or None: nothing accepted,
    or the module not installed."""
    if "accepted-baseline" not in inputs:
        return None
    try:
        from wgf_baseline.brief import context as accepted_context
    except ImportError:
        return None
    report = (inputs.load("baseline-regression-report")
              if "baseline-regression-report" in inputs else None)
    return accepted_context(inputs.load("accepted-baseline"), report)

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

    def check(self, *, checkout, key, engine, checks_json, logger, write, checks=(), quarantine=None):
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
            _record_checks(checkout, checks_json, self.clock(), key, engine,
                           [c.to_dict() for c in checks]
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
        # The developer, the checks and the commit all work in the checkout: locked against
        # another run for the whole step (wgflib.checkout).
        with checkout_lock.StepLease(context) as lease:
            try:
                return self._execute(inputs, context, lease)
            except safewrite.UnsafeCheckoutPath as exc:
                # A link or a non-directory where the Factory writes its own files: left by
                # the developer (or by hand). Writing through it would put the Factory's text
                # wherever it points, outside every check - so nothing is written.
                context.logger.error("develop refused an unsafe checkout path", error=str(exc))
                return StepResult.failed(
                    f"the checkout is not safe to write the Factory's files into: {exc}. "
                    "Nothing was written there. Remove the link, then run develop again.",
                    retryable=False)

    def _execute(self, inputs, context, lease):
        try:
            settings = Settings.resolve(context.config, self.params)
        except SettingsError as exc:
            return StepResult.failed(str(exc), retryable=False)

        phase = (self.params or {}).get("phase")
        if phase is not None and phase not in PHASES:
            return StepResult.failed(f"develop's `with: phase` is {phase!r}; it is one of "
                                     f"{', '.join(PHASES)}", retryable=False)
        required = tuple(t for t in REQUIRED_INPUTS
                         if not (phase == "greybox" and t == "asset-manifest"))
        missing = [t for t in required if t not in inputs]
        if missing:
            return StepResult.waiting_for_input(
                f"develop needs {', '.join(missing)} in the run before it can brief a build")
        for artifact_type in REQUIRED_INPUTS + ("title-strategy", "tech-plan", "qa-report",
                                                "review-report", "playability-report",
                                                "production-quality-report",
                                                "visual-qa-report",
                                                "content-sufficiency-report", "triage-report"):
            ref = inputs.refs.get(artifact_type)
            version = getattr(ref, "schema_version", None) or ""
            if ref is not None and version and version.split(".")[0] != SUPPORTED_MAJOR:
                return StepResult.failed(
                    f"{artifact_type} is schema {version}; develop reads {SUPPORTED_MAJOR}.x",
                    retryable=False)

        design = inputs.load("game-design")
        assets = (inputs.load("asset-manifest")
                  if phase != "greybox" and "asset-manifest" in inputs else None)
        scaffold = inputs.load("scaffold-record")
        strategy = inputs.load("title-strategy") if "title-strategy" in inputs else None
        tech_plan = inputs.load("tech-plan") if "tech-plan" in inputs else None
        qa = inputs.load("qa-report") if "qa-report" in inputs else None
        review = inputs.load("review-report") if "review-report" in inputs else None
        playability = (inputs.load("playability-report") if "playability-report" in inputs
                       else None)
        # The floor an adopted run holds this visit to: the design's, or - recorded unmeasured
        # because the checkout ships no content data file - the probe floor the run measured
        # on the shipped build since. The brief and every floor check read it from here.
        floor = content_floor.effective(design, playability, getattr(context, "run_dir", None))
        if floor is not None and floor is not design.get("existing_content"):
            design = dict(design, existing_content=floor)
        production = (inputs.load("production-quality-report")
                      if "production-quality-report" in inputs else None)
        visual_qa = inputs.load("visual-qa-report") if "visual-qa-report" in inputs else None
        sufficiency = (inputs.load("content-sufficiency-report")
                       if "content-sufficiency-report" in inputs else None)
        # A qa-report on the first visit is a leftover from an earlier release, not feedback
        # on this build; only a loop back from verify carries defects to fix.
        if qa is not None and (context.visit <= 1 or qa.get("verdict") == "pass"):
            qa = None
        title_id = scaffold.get("title_id") or design.get("title_id")

        repository = (scaffold.get("repository") or {})
        try:
            checkout, where = settings.locate(repository.get("name") or title_id, scaffold,
                                              logger=context.logger)
        except SettingsError as exc:
            return StepResult.failed(f"scaffold-record: {exc}", retryable=False)
        try:
            lease.take(checkout)
        except checkout_lock.CheckoutLocked as exc:
            return StepResult.blocked(str(exc))
        runner = self.runner_factory()
        git = GitRepo(checkout, runner, author=settings.data.get("author"),
                      allow_filters=settings.allow_filters)
        # is_repository pins the git directory: from here on every git command names the
        # one found now, before any developer could write .git or core.worktree.
        if not git.is_repository():
            return StepResult.blocked(
                f"the game repository {repository.get('owner')}/{repository.get('name')} is "
                f"not checked out at {checkout} (from {where}). Clone it there (or name it: "
                f"the step's with: repo_dir, WGF_GAME_REPO, or factory.checkouts) and resume.")
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
        # A passing greybox: the loop the production phase must keep playable.
        greybox_commit = (playability.get("commit") if phase == "production" and playability
                          and playability.get("verdict") == "PASS" else None)
        # Likewise a playability failure: only one that played the commit this visit starts
        # from says what to fix in it.
        if playability is not None and not (
                context.visit > 1 and playability.get("verdict") == "FAIL"
                and playability.get("commit") == git.head()):
            playability = None
        # And the production gates': only a FAIL of the commit this visit starts from is
        # feedback on this build - reached directly (route develop) or through assets, which
        # rebuilt what the report named without committing, so HEAD is still the one judged.
        if production is not None and not (
                context.visit > 1 and production.get("verdict") == "FAIL"
                and production.get("commit") == git.head()):
            production = None
        if visual_qa is not None and not (
                context.visit > 1 and visual_qa.get("verdict") == "FAIL"
                and visual_qa.get("commit") == git.head()):
            visual_qa = None
        if sufficiency is not None and not (
                context.visit > 1 and sufficiency.get("verdict") == "FAIL"
                and sufficiency.get("commit") == git.head()):
            sufficiency = None
        # Routed by triage as a specialist (`triage.<role>`): the visit is that discipline's.
        # Its brief carries the findings it owns - each with its measurement, bar, evidence
        # and acceptance - in place of the gates' raw reports, its own craft playbooks, and
        # a writable scope cut to the specialist's (never wider than the installation's).
        spec, problem = specialists.resolve(context, inputs, phase)
        if problem:
            return StepResult.failed(problem, retryable=False)
        if spec is not None:
            narrowed = specialists.narrow(settings.writable_paths, spec["writes"])
            if not narrowed:
                return StepResult.failed(
                    f"the {spec['role']} specialist may write none of the paths this "
                    f"installation lets a developer write ({', '.join(settings.writable_paths)}"
                    f"; its scope: {', '.join(spec['writes']) or 'none'}): it cannot be "
                    f"briefed as a develop visit", retryable=False)
            settings.writable_paths = narrowed
            qa = review = playability = production = visual_qa = sufficiency = None
            context.logger.info("develop briefed as a specialist", specialist=spec["role"],
                                findings=[f.get("id") for f in spec["findings"]],
                                writable_paths=narrowed, pending=spec["pending"] or None)

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
        run_dir = getattr(context, "run_dir", None)
        record = dict(checkout=checkout, key=key, engine=engine, checks_json=checks_json,
                      logger=context.logger,
                      write=not committed,
                      quarantine=(os.path.join(
                          run_dir, "develop-quarantine",
                          f"{getattr(context, 'visit', 1)}-{getattr(context, 'attempt', 1)}")
                          if run_dir else None))
        def make_brief(baseline, review_baseline, previous_checks):
            return briefs.build_brief(
                title_id=title_id, engine=engine, iteration=context.visit, key=key,
                baseline=baseline, design=design, assets=assets, scaffold=scaffold,
                strategy=strategy, qa=qa, previous_checks=previous_checks,
                refs=inputs.refs, skills=settings.skills, review=review,
                playability=playability, frames_root=getattr(context, "run_dir", None),
                production=production, visual_qa=visual_qa, sufficiency=sufficiency,
                phase=phase, greybox_commit=greybox_commit, review_baseline=review_baseline,
                tech_plan=tech_plan, self_playtest=settings.self_playtest,
                mobile_test=bool((game_config.get("verification") or {}).get("mobile_test",
                                                                            True)),
                writable_paths=settings.writable_paths,
                package_changes=settings.package_changes,
                loop=_loop(context, spec, via=(
                    (inputs.load("triage-report") or {}).get("source")
                    if "triage-report" in inputs else None)),
                sessions=_sessions(context, tech_plan),
                developer=settings.developer,
                specialist=spec,
                accepted=_accepted_baseline(inputs),
            )

        if (phase == "greybox" and content_floor.adopted(design) and spec is None
                and not committed and playability is None):
            # An adopted game that already ships production content is improved, never
            # rebuilt: its first greybox visit runs no developer and plays the build as it
            # is (docs/development-module.md, "An adopted game").
            done = self._conformance_visit(
                context, inputs, settings, runner, git, guard, record, make_brief, design,
                strategy, title_id, engine, game_config, repository, checkout)
            if done is not None:
                return done

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
            review_baseline = _review_baseline(existing, key, phase, baseline)
            if (spec is not None and spec.get("mode") == "continued"
                    and existing.get("idempotency_key") != key
                    and existing.get("review_baseline")):
                # The next specialist on the same build: review, after the chain, reads
                # every specialist's commit, from where the first one started.
                review_baseline = existing["review_baseline"]
            previous_checks = _read_json(checks_json)
            if (previous_checks or {}).get("idempotency_key") != key:
                previous_checks = None  # another visit's failures are not this one's
            brief = make_brief(baseline, review_baseline, previous_checks)
            _write(checkout, brief_json, json.dumps(brief, indent=2, ensure_ascii=False) + "\n")
            _write(checkout, brief_md, briefs.render_markdown(brief))
            # The design, readable in the repository (game-design's rendered_to). Written
            # before the developer runs, so it can be read, and again after, so a hand edit
            # never survives into this visit's commit.
            gdd = render_gdd(design, strategy,
                             getattr(inputs.refs.get("game-design"), "content_hash", None))
            _write(checkout, os.path.join(checkout, GDD_PATH), gdd)
            written = ensure_seam(checkout)
            if written:
                context.logger.info("integration seam provided", paths=written)

            developer = create_developer(settings, runner)
            budget, session = None, None
            if developer.kind == "command":
                # A paid agent session: counted against the run's budget from its event
                # log - which a resume does not reset - and refused, before anything is
                # spawned, once the budget is spent or when the run has none.
                budget = Budget.load(context, tech_plan)
                missing = budget.missing(context.run_id)
                if missing:
                    context.logger.warning("develop budget missing", **budget.summary())
                    return StepResult.blocked(missing, budget=budget.summary())
                exhausted = budget.exhausted(context.run_id)
                if exhausted:
                    context.logger.warning("develop budget exhausted", **budget.summary())
                    return StepResult.blocked(exhausted, budget=budget.summary())
            refused = guard.take()
            if refused is not None:
                return refused
            if budget is not None:
                session, problem = budget.begin(context)
                if problem:
                    return StepResult.blocked(problem)
            try:
                outcome = developer.develop(brief_md, checkout, context)
            finally:
                if session is not None:
                    budget.finish(context, session)
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
                           if (c.get("status") == "failed" or c.get("blocking"))
                           and c.get("id") != "developer"]
                self._record(checks_json, key, engine, [{
                    "id": "developer",
                    "status": "failed",
                    "summary": (f"The previous attempt's developer ended before it finished "
                                f"({outcome.message}). Its partial work is still in the "
                                "checkout: continue from it rather than starting over, "
                                "finish every required system, make every check pass, "
                                f"and write {briefs.REPORT_PATH}."),
                }] + carried, False, checkout)
                return StepResult.failed(outcome.message, output_tail=outcome.output_tail)
            _write(checkout, os.path.join(checkout, GDD_PATH), gdd)
            # Before the checks, which are minutes: a file that can never be committed
            # fails now, not after them.
            refused = self._scope(git, settings, **record)
            if refused is not None:
                return refused
            refused = self._floor(git, design, spec, **record)
            if refused is not None:
                return refused

        refused = guard.take()  # a re-executed, committed visit: around its checks alone
        if refused is not None:
            return refused
        try:
            strength = skip_policy(context, brief)
        except ValueError as exc:
            return StepResult.blocked(f"what a skipped check counts as cannot be read ({exc}); "
                                      "no build is called green on a defaulted rule")
        platforms = [p.get("id") for p in game_config.get("platforms") or []
                     if isinstance(p, dict) and p.get("id")]
        checks = run_checks(checkout, brief, settings, runner, git, logger=context.logger,
                            strength=strength,
                            steps=("develop", getattr(context, "current_step", None)),
                            platforms=platforms)
        green = all(not c.blocking for c in checks)
        # The checks run code the developer wrote (its tests, its build): the same boundary.
        refused = guard.check(checks=checks, **record)
        if refused is not None:
            return refused
        if not committed:  # a committed visit's record is part of its commit; leave it be
            self._record(checks_json, key, engine, [c.to_dict() for c in checks], green,
                         checkout)

        dev_report, _ = read_report(checkout)
        commit_sha = committed
        if not committed:
            # Again after the checks: one that writes outside the ignored paths has put a
            # file in the tree that nobody decided to commit.
            refused = self._scope(git, settings, checks=checks, **record)
            if refused is not None:
                return refused
            refused = self._floor(git, design, spec, checks=checks, **record)
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
        visit_record = None
        if spec is not None:
            sessions, cost = specialists.visit_cost(context)
            visit_record = {
                "role": spec["role"],
                "findings": [f.get("id") for f in spec["findings"]],
                "pending": list(spec["pending"]),
                "triage_report": spec.get("triage_report"),
                "source": spec.get("source"),
                "writable_paths": list(settings.writable_paths),
                "sessions": sessions, "cost_usd": cost}
        report = build_report(
            title_id=title_id, brief=brief, checks=checks, dev_report=dev_report,
            commit_sha=commit_sha, built_at=produced_at,
            build_url=self._build_url(settings, repository, checkout, commit_sha, git),
            iteration=context.visit, strategy=strategy,
            pinned_inputs=self._pins(inputs), artifact_seq=context.execution,
            produced_at=produced_at, specialist=visit_record,
        )
        artifact = ArtifactOutput("prototype-report", report, metadata={
            "commit": commit_sha, "engine": engine, "green": green,
            "checks": {c.id: c.status for c in checks},
        })

        # A gap the developer could not build around. The build is kept - it is real work,
        # and the design is repaired from this report - but the run goes back to design
        # rather than carrying an invented decision forward as if the designer had made it.
        gaps = blocking_gaps(design_gaps(dev_report))
        if green and gaps:
            context.logger.warning("develop found a blocking design gap",
                                   fields=[gap["field"] for gap in gaps])
            return StepResult("FAILED", route=DESIGN_GAP_ROUTE, artifacts=[artifact],
                              retryable=False,
                              error=(f"{len(gaps)} blocking design gap(s) at "
                                     f"{commit_sha[:12]}: "
                                     + "; ".join(f"{gap['field']}: {gap['question']}"
                                                 for gap in gaps[:4])
                                     + ". The design does not say enough to build it; it is "
                                       "repaired at design, not guessed at here."))
        if green:
            message = (f"{title_id} built at {commit_sha[:12]} ({engine}); "
                       + ", ".join(f"{c.id} {c.status}" for c in checks)
                       + ("; SKIPPED, not measured: "
                          + "; ".join(f"{c.id} ({c.summary})" for c in checks if c.skipped)
                          + f" - {strength.describe()}"
                          if any(c.skipped for c in checks) else ""))
            if spec is not None and spec["pending"]:
                # More specialists own findings of this build: the next one works on it
                # before the gates measure it again (the workflow maps the route to triage).
                return StepResult.success([artifact], route=specialists.NEXT_SPECIALIST,
                                          message=message + f"; next: {spec['pending'][0]}")
            return StepResult.success([artifact], message=message)

        failed = [c for c in checks if c.blocking]
        summary = "; ".join(f"{c.id}: {c.summary}" for c in failed)
        if any(c.skipped for c in failed):
            summary += (" (a check that did not run measured nothing: "
                        f"{strength.describe()})")
        developer = create_developer(settings, runner)
        if developer.retry_on_check_failure:
            return StepResult("FAILED", artifacts=[artifact], retryable=True,
                              error=f"checks failed - {summary}")
        return StepResult("WAITING_FOR_HUMAN", artifacts=[artifact], message=(
            f"checks failed - {summary}. Details in {checks_json}. Fix them and resume with "
            f"--decision done."))

    # -- helpers -------------------------------------------------------------------------

    def _record(self, checks_json, key, engine, checks, green, checkout):
        _record_checks(checkout, checks_json, self.clock(), key, engine, checks, green)

    def _scope(self, git, settings, *, checkout, key, engine, checks_json, logger, write,
               checks=(), quarantine=None):
        """FAILED when the tree holds a change the development commit may not contain; None
        when every change is in scope. Not retryable when a refused change touches a tracked
        file. When every refused path is a new, untracked file - a developer's scratch
        script, which it has no tool to delete - the files are moved out of the checkout
        into `quarantine` (kept as evidence) and the failure is retryable: the next attempt
        starts from a clean tree and is told what was removed and why."""
        try:
            changes = git.changes()
            # An untracked scratch file outside the writable paths cannot be committed and a
            # developer host that denies deletion cannot remove it: it is swept here, said
            # so, and never counted against the developer. Tracked files, hidden paths,
            # instruction files and package files are never swept.
            swept = []
            for xy, path in list(changes):
                if xy != "??" or not scope.stray(path, settings.writable_paths):
                    continue
                full = os.path.join(checkout, path)
                if os.path.islink(full) or not os.path.isfile(full):
                    continue
                try:
                    os.remove(full)
                except OSError:
                    continue
                swept.append(path)
                changes.remove((xy, path))
            if swept:
                logger.warning("develop swept stray untracked files outside the writable "
                               "paths before judging the commit scope", paths=swept)
            allowed, refused = scope.partition(changes, settings.writable_paths)
        except GitError as exc:
            return StepResult.failed(f"cannot read what the developer changed: {exc}",
                                     retryable=False)
        # A Factory-rendered file is in scope by path because the step writes it - so it
        # must be the plain file the step wrote, not a link the developer put in its place.
        refused += [(path, problem) for path in allowed if path in scope.FACTORY_RENDERED
                    for problem in [safewrite.regular_file_problem(checkout, path)] if problem]
        if not refused:
            return None
        listed = "; ".join(f"{path}: {why}" for path, why in refused[:8])
        more = f" and {len(refused) - 8} more" if len(refused) > 8 else ""
        message = (f"the checkout holds {len(refused)} change(s) a development commit may not "
                   f"contain - {listed}{more}. Nothing was committed. Remove them (the brief "
                   f"lists what a developer may write: {', '.join(settings.writable_paths)}), "
                   "then run develop again.")
        logger.error("develop commit scope violated", paths=[p for p, _ in refused])
        untracked = {path for xy, path in changes if xy == "??"}
        if quarantine and all(path in untracked for path, _ in refused):
            moved = self._quarantine(checkout, quarantine, [p for p, _ in refused], logger)
            if moved is not None:
                message = (f"the developer left {len(refused)} new file(s) outside what a "
                           f"development commit may contain - {listed}{more}. They were "
                           f"moved out of the checkout to {quarantine}, and nothing else "
                           "changed. Keep scratch files in /tmp, never in the checkout "
                           "(you have no tool to delete them); write only "
                           f"{', '.join(settings.writable_paths)}.")
                if write:
                    self._record(checks_json, key, engine, [c.to_dict() for c in checks] + [{
                        "id": "commit-scope", "status": "failed", "summary": message,
                        "findings": [f"{path}: {why}" for path, why in refused]}], False,
                        checkout)
                return StepResult.failed(message, retryable=True)
        if write:
            self._record(checks_json, key, engine, [c.to_dict() for c in checks] + [{
                "id": "commit-scope", "status": "failed", "summary": message,
                "findings": [f"{path}: {why}" for path, why in refused]}], False, checkout)
        return StepResult.failed(message, retryable=False)

    def _floor(self, git, design, spec, *, checkout, key, engine, checks_json, logger, write,
               checks=(), quarantine=None):
        """FAILED, retryable, when the tree ships less than the adopted repository did: its
        content data counts below game-design.existing_content, or a file the repository
        shipped under public/ is gone (allowed only to a specialist visit, whose findings ask
        for the change). None otherwise, and for a run that adopted nothing. Recorded as the
        `existing-content` check, so the next attempt's brief carries what to put back."""
        problems, allowed = content_floor.problems(checkout, design, git,
                                                   findings_visit=spec is not None)
        if allowed:
            logger.warning("develop removed files the adopted repository shipped, as the "
                           "specialist's findings ask", paths=allowed[:20])
        if not problems:
            return None
        message = ("QUALITY REGRESSION: the checkout ships less than the adopted repository "
                   "already shipped - " + "; ".join(problems[:6])
                   + (f" and {len(problems) - 6} more" if len(problems) > 6 else "")
                   + ". Nothing was committed. Put the shipped content back and build on it: "
                   "an adopted game is improved, never rebuilt.")
        logger.error("develop would drop below the existing-content floor",
                     problems=problems[:20])
        if write:
            self._record(checks_json, key, engine, [c.to_dict() for c in checks] + [{
                "id": "existing-content", "status": "failed", "summary": message,
                "findings": problems[:40]}], False, checkout)
        return StepResult.failed(message, retryable=True)

    def _conformance_visit(self, context, inputs, settings, runner, git, guard, record,
                           make_brief, design, strategy, title_id, engine, game_config,
                           repository, checkout):
        """The first greybox visit on an adopted game: no developer, nothing written into
        the checkout. The toolchain checks run on HEAD - `conformance` judges a developer's
        report, and none ran - and a green HEAD is the visit's build, reported for
        greybox-playability to play as it is. None when the checks do not pass: the visit
        goes on as a developer visit, held to the floor."""
        head = git.head()
        brief = make_brief(head, head, None)
        quiet = dict(record, write=False)
        refused = guard.take()
        if refused is not None:
            return refused
        toolchain = copy.copy(settings)
        toolchain.checks = [c for c in settings.checks if c != "conformance"]
        try:
            strength = skip_policy(context, brief)
        except ValueError as exc:
            return StepResult.blocked(f"what a skipped check counts as cannot be read ({exc}); "
                                      "no build is called green on a defaulted rule")
        platforms = [p.get("id") for p in game_config.get("platforms") or []
                     if isinstance(p, dict) and p.get("id")]
        checks = run_checks(checkout, brief, toolchain, runner, git, logger=context.logger,
                            strength=strength,
                            steps=("develop", getattr(context, "current_step", None)),
                            platforms=platforms)
        refused = guard.check(checks=checks, **quiet)
        if refused is not None:
            return refused
        if any(c.blocking for c in checks):
            context.logger.warning(
                "the adopted build does not pass its checks as it is; a developer improves "
                "it, held to the existing-content floor",
                checks={c.id: c.status for c in checks})
            return None
        shipped = content_floor.shipped_units(checkout, design)
        dev_report = {
            "content_units": [{"id": uid, "status": "built",
                               "notes": "shipped by the adopted repository"}
                              for uid in shipped],
            "known_issues": ["Conformance visit: no developer ran. The adopted repository's "
                             "build at HEAD is played as it is; a developer is briefed only "
                             "for what the greybox gate finds."]}
        produced_at = self.clock()
        report = build_report(
            title_id=title_id, brief=brief, checks=checks, dev_report=dev_report,
            commit_sha=head, built_at=produced_at,
            build_url=self._build_url(settings, repository, checkout, head, git),
            iteration=context.visit, strategy=strategy,
            pinned_inputs=self._pins(inputs), artifact_seq=context.execution,
            produced_at=produced_at)
        context.logger.info("greybox conformance visit: the adopted build is played as it is",
                            commit=head)
        return StepResult.success(
            [ArtifactOutput("prototype-report", report, metadata={
                "commit": head, "engine": engine, "green": True, "conformance": True,
                "checks": {c.id: c.status for c in checks}})],
            message=(f"{title_id} is an adopted game: its build at {head[:12]} ({engine}) is "
                     "played as it is, no developer ran; "
                     + ", ".join(f"{c.id} {c.status}" for c in checks)))

    @staticmethod
    def _quarantine(checkout, target, refused, logger):
        """Move untracked `refused` paths from `checkout` into `target`. The moved paths, or
        None when any could not be moved safely (a link, or a path leaving the checkout)."""
        root = os.path.realpath(checkout)
        moved = []
        for path in refused:
            source = os.path.join(checkout, path)
            if os.path.islink(source) or not os.path.realpath(source).startswith(root + os.sep):
                return None
            destination = os.path.join(target, path)
            try:
                os.makedirs(os.path.dirname(destination), exist_ok=True)
                shutil.move(source, destination)
            except OSError:
                return None
            moved.append(path)
            # Leave no empty directory behind: git does not see it, but a later tool may.
            parent = os.path.dirname(source)
            while parent != checkout and os.path.isdir(parent) and not os.listdir(parent):
                os.rmdir(parent)
                parent = os.path.dirname(parent)
        logger.warning("moved the developer's out-of-scope new files out of the checkout",
                       paths=moved, to=target)
        return moved

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

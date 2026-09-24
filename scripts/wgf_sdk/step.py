"""The `sdk` step: game-design, scaffold-record and prototype-report in, sdk-report out.

    game.config.yaml + pinned profiles ──► integration plan (what each platform requires)
    game-design + the game's source    ──► integration (integration.py): the gameplay layer,
                                           the seam and main.ts wired to the platform SDK,
                                           checked by its own mock suite
    game repo `pnpm sdk:conformance`   ──► evidence (fake portal SDKs; optional browser smoke)
                                        ──► sdk-report: per platform, per feature, how observed

The integration phase runs when the run holds a game-design and a scaffold-record; without
them (`wgf sdk` on its own) the step verifies what is already there. A feature both phases
report takes the worse status: an adapter that works in a game that does not call it is not
working, and neither is a wired game on an adapter that fails.

Where the game repository is: `with: {game_repo: <path>}` on the workflow step, else the
WGF_GAME_REPO environment variable, else `factory.sdk.game_repo` in
workspace/config/factory.yaml — the order the verify step uses — else
`factory.sdk.games_dir`/<scaffold-record repository name>, else where the init module cloned
it (`factory.init.projects_dir`/<title id>). `with: {browser: true}` (or
`factory.sdk.browser`) also runs the browser smoke. `with: {report: <path>}` reads an
existing conformance report — a CI artifact, say — instead of running the suite.

Outcomes (docs/workflow-module-contract.md §7):

    no game repository configured, or no game.config.yaml   BLOCKED: platform not configured
    a platform pin that does not match its profile           BLOCKED: re-pin via the tech plan
    the suite could not run (toolchain, timeout)             FAILED, retryable
    a REQUIRED platform with a required feature not working  FAILED, not retryable, sdk-report
                                                             persisted as evidence
    no packages/platform-sdk in the game repository          BLOCKED (integration phase)
    the integration's own mock suite or typecheck failed     FAILED, not retryable, sdk-report
                                                             persisted as evidence
    no readable git HEAD, a prototype-report naming no
    commit, HEAD not the prototype commit (or this run's
    sdk commits on it), uncommitted changes the
    integration did not make                                 BLOCKED (commit.py)
    the conformance suite ran at another commit than HEAD    FAILED, not retryable
    otherwise                                                SUCCESS; optional platforms that
                                                             are not working are named in the
                                                             message and metadata

A `working` feature is one whose every conformance scenario passed. A skipped scenario (no
adapter on this ref) is `not-started`, never `working`. The step publishes nothing.

Commits (commit.py, docs/core-contracts.md §5): a successful integration that changed the
tree is committed once, locally, keyed by the idempotency key in a `Wgf-Sdk-Key` trailer,
and the conformance suite then runs at that commit. The sdk-report's `build_ref` names the
commit it verified (`commit_sha`), the commit it built on (`base_commit_sha`, the
prototype-report's) and the commits it made between them (`sdk_commits`). Nothing is pushed.
"""

import datetime
import os

from wgflib import paths
from wgflib.hashing import content_hash
from wgflib.workflow import ArtifactOutput, StepResult, WorkflowStep

from wgf_verification.lineage import same_commit

from . import commit as sdk_commit
from . import evidence as ev
from .integration import IntegrationPhase, PhaseBlocked
from .plan import FEATURES, PlanError, integration_plan, load_game_config
from .runner import CommandRunner

__all__ = ["SdkStep", "register", "SCHEMA_VERSION", "ROLE"]

SCHEMA_VERSION = "1.2.0"
ROLE = "sdk"
OBSERVED_BY = "web-game-template SDK conformance suite (tests/sdk, fake portal SDK)"


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _feature_status(name, plan, observed, suite_platform, commit, limitation):
    required = name in plan.required
    item = {"feature": name}
    if name in plan.unservable:
        item.update(status="not-started",
                    note=f"{plan.why[name]}, but the {plan.id} profile offers no {name} ads")
        return item
    if name == "not-configured" and limitation:
        # The suite passed because createPlatform refused loudly — the right failure mode,
        # but not an integration.
        item.update(status="not-started", note=limitation)
        return item
    if observed is None or (observed["passed"] == observed["failed"] == observed["skipped"] == 0):
        # Not applicable on this platform according to the suite (only `todo`), or absent.
        if required and name in plan.conditional and observed is not None:
            item.update(status="not-required",
                        note=f"the conformance suite reports it not applicable on {suite_platform} "
                             "(no portal SDK)")
        elif required:
            item.update(status="not-started",
                        note=f"required ({plan.why[name]}) but the conformance suite has no "
                             f"scenario for it on {suite_platform}")
        else:
            item["status"] = "not-required"
        return item
    if observed["failed"]:
        item.update(status="partial", observed_by=f"{OBSERVED_BY} @ {commit}",
                    note="; ".join(observed["failures"])[:900])
    elif observed["skipped"]:
        item.update(status="not-started",
                    note=f"{observed['skipped']} scenario(s) skipped: no adapter on this ref")
    else:
        item.update(status="working",
                    observed_by=f"{OBSERVED_BY} @ {commit}: {observed['passed']} scenario(s) passed")
    if not required:
        item["status"] = "not-required"
        item["note"] = (f"exercised, not required by profile or game.config"
                        + (f" ({observed['failures'][0]})" if observed["failed"] else ""))
        item.pop("observed_by", None)
    return item


def _limitation(observed):
    titles = [t for t in (observed or {}).get("not-configured", {}).get("titles", [])
              if "refuses loudly" in t]
    return titles[0].split(" — ", 1)[1] if titles and " — " in titles[0] else None


# Worse status wins when both phases report a feature.
_RANK = {"working": 0, "unsupported": 1, "partial": 2, "not-started": 3}


def _section(config, name):
    # The engine hands steps the configuration as a plain mapping; FactoryConfig in tests.
    if hasattr(config, "section"):
        return config.section(name)
    return (config or {}).get(name) or {}


def _combine(verified, integrated):
    """One feature, as the conformance suite and the integration phase saw it."""
    if integrated["status"] == "not-required":
        return verified
    if verified["status"] == "not-required":
        return integrated
    merged = dict(verified)
    if _RANK[integrated["status"]] > _RANK.get(verified["status"], 0):
        merged["status"] = integrated["status"]
    for key in ("required_by", "hooks", "fallback"):
        if key in integrated:
            merged[key] = integrated[key]
    observed = [o for o in (verified.get("observed_by"), integrated.get("observed_by")) if o]
    if merged["status"] == "working" and observed:
        merged["observed_by"] = "; ".join(observed)
    else:
        merged.pop("observed_by", None)
    notes = [n for n in (verified.get("note"), integrated.get("note")) if n]
    if notes:
        merged["note"] = " | ".join(notes)[:1500]
    return merged


def _overlay(entry, integrated):
    """Lay the integration phase's view of one platform over the conformance suite's."""
    features = {f["feature"]: f for f in entry["features"]}
    for item in integrated["features"]:
        features[item["feature"]] = (_combine(features[item["feature"]], item)
                                     if item["feature"] in features else item)
    entry["features"] = list(features.values())
    entry["adapter"] = integrated["adapter"]
    if integrated.get("note"):
        entry["note"] = " | ".join(n for n in (entry.get("note"), integrated["note"]) if n)
    required = [f for f in entry["features"] if f["status"] != "not-required"]
    if all(f["status"] == "working" for f in required):
        status = "working"
    elif any(f["status"] in ("working", "partial", "unsupported") for f in required):
        status = "partial"
    else:
        status = "not-started"
    if integrated["adapter"]["status"] == "missing":
        status = "not-started"  # a build for it fails at boot, whatever else passed
    order = ("working", "partial", "not-started")
    entry["status"] = max(status, entry["status"], key=order.index)


class SdkStep(WorkflowStep):
    type = "sdk"

    clock = staticmethod(utc_now)
    runner_factory = ev.PnpmRunner
    integration_runner_factory = CommandRunner
    profiles_dir = None

    def _setting(self, context, key, default=None):
        if key in self.params:
            return self.params[key]
        return _section(context.config, "sdk").get(key, default)

    def _game_repo(self, context, scaffold):
        # Same order the verify step uses: the step's parameter, WGF_GAME_REPO, then config;
        # then where the checkouts are, and where init cloned this one.
        explicit = (self.params.get("game_repo") or os.environ.get("WGF_GAME_REPO")
                    or _section(context.config, "sdk").get("game_repo"))
        if explicit:
            return os.path.abspath(os.path.expanduser(explicit))

        def rooted(path):
            return os.path.normpath(path if os.path.isabs(path)
                                    else os.path.join(paths.ROOT, path))

        candidates = []
        games_dir = self._setting(context, "games_dir")
        name = ((scaffold or {}).get("repository") or {}).get("name")
        if games_dir and name:
            candidates.append(rooted(os.path.join(games_dir, name)))
        title = (scaffold or {}).get("title_id")
        if title:
            projects = _section(context.config, "init").get("projects_dir", "..")
            candidates.append(rooted(os.path.join(projects, title)))
        return next((c for c in candidates if os.path.isdir(c)), None)

    def execute(self, inputs, context):
        design = inputs.load("game-design") if "game-design" in inputs else None
        scaffold = inputs.load("scaffold-record") if "scaffold-record" in inputs else None
        game_repo = self._game_repo(context, scaffold)
        if not game_repo:
            return StepResult.blocked(
                "platform not configured: no game repository (with: {game_repo} on the step, "
                "WGF_GAME_REPO, factory.sdk.game_repo, or a checkout under factory.sdk.games_dir "
                "or factory.init.projects_dir)")
        try:
            config = load_game_config(game_repo)
            plans = integration_plan(config, self.profiles_dir)
        except PlanError as exc:
            return StepResult.blocked(str(exc))

        has_prototype = "prototype-report" in inputs
        prototype = inputs.load("prototype-report") if has_prototype else {}
        title_id = ((design or {}).get("title_id") or (prototype or {}).get("title_id")
                    or (config.get("game") or {}).get("id") or context.project_id)

        # Where the build stands before anything is written: the commit the evidence will be
        # about must be established, and must be develop's (or this run's sdk commits on it).
        run_id = getattr(context, "run_id", None)
        key = getattr(context, "idempotency_key", None) or \
            f"{run_id or 'local'}:{getattr(context, 'current_step', None) or 'sdk'}:" \
            f"{getattr(context, 'visit', None) or context.execution}"
        integration_runner = self.integration_runner_factory()
        git = sdk_commit.SdkGit(game_repo, integration_runner,
                                author=self._setting(context, "commit_author"))
        prototype_commit = ((prototype or {}).get("build_ref") or {}).get("commit_sha")
        try:
            head, base, own = sdk_commit.prepare(git, prototype_commit, has_prototype, run_id)
        except sdk_commit.CommitRefused as exc:
            return StepResult.blocked(str(exc))

        integrated = None
        if design and scaffold:
            phase = IntegrationPhase(lambda key, default=None: self._setting(context, key, default),
                                     integration_runner)
            try:
                integrated = phase.run(game_repo, design, scaffold, title_id)
            except PhaseBlocked as exc:
                return StepResult.blocked(str(exc))
            context.logger.info("sdk integration", tests=integrated["integration"]["tests"]["status"])
            if integrated["integration"]["tests"]["status"] != "failed":
                try:
                    sha, created = sdk_commit.commit(
                        git, key, title_id, integrated["integration"]["files"],
                        integrated["integration"]["tests"])
                except sdk_commit.CommitRefused as exc:
                    return StepResult.blocked(str(exc))
                if created:
                    context.logger.info("sdk integration committed", commit=sha, key=key)
                    own = own + [sha]
                integrated["integration"]["repository_state"] = (
                    "clean" if not git.dirty_paths() else "uncommitted-changes")
        head = git.head()
        if not head:
            return StepResult.blocked(f"{game_repo}: HEAD became unreadable during the "
                                      "integration; the commit cannot be established")

        report_path = self._setting(context, "report")
        try:
            if report_path:
                run = ev.ConformanceRun(ev.read_report(report_path), None)
            else:
                run = self.runner_factory().run(game_repo, browser=bool(self._setting(context, "browser")))
        except ev.EvidenceError as exc:
            return StepResult.failed(str(exc))
        observed, problems = ev.summarize(run.report)
        if problems:
            return StepResult.failed("the conformance report is not trustworthy: " + "; ".join(problems),
                                     retryable=False)

        commit = head
        if run.commit and not same_commit(run.commit, head):
            return StepResult.failed(
                f"the conformance suite ran at {run.commit[:12]}, but the checkout's HEAD is "
                f"{head[:12]}: the checkout moved while the step ran", retryable=False)
        tests_failed = bool(integrated) and \
            integrated["integration"]["tests"]["status"] == "failed"
        lineage = {"base_commit_sha": base, "sdk_commits": list(own)}

        entries, blocking, degraded = [], [], []
        for plan in plans:
            # A GameVui build runs the generic-web adapter; the suite reports it under gamevui.
            suite_platform = plan.id
            features = observed.get(suite_platform)
            limitation = _limitation(features)
            items = [_feature_status(name, plan, (features or {}).get(name), suite_platform, commit,
                                     limitation)
                     for name in FEATURES]
            required_items = [i for i in items
                              if i["feature"] in plan.required and i["status"] != "not-required"]
            if not features:
                status = "not-started"
            elif all(i["status"] == "working" for i in required_items):
                status = "working"
            elif any(i["status"] in ("working", "partial") for i in required_items):
                status = "partial"
            else:
                status = "not-started"
            notes = []
            if limitation:
                notes.append(limitation)
            if not features:
                notes.append("the conformance suite has no harness for this platform")
            if run.browser is not None:
                notes.append("browser smoke (PixiJS + Three.js builds, mocked portal scripts): "
                             + ("passed" if run.browser["passed"] else "FAILED"))
                if not run.browser["passed"] and status == "working":
                    status = "partial"
            if not same_commit(base, commit):
                notes.append(f"integrated on {base[:12]} and committed as {commit[:12]}")
            if tests_failed:
                notes.append("the failed integration is left uncommitted in the working tree")
            entry = {"platform_id": plan.id, "profile_version": plan.version, "status": status,
                     "features": items}
            if notes:
                entry["note"] = " | ".join(notes)
            if integrated and plan.id in integrated["platforms"]:
                _overlay(entry, integrated["platforms"][plan.id])
                status = entry["status"]
            entries.append(entry)
            if status != "working":
                (blocking if plan.role == "required" else degraded).append(f"{plan.id} ({status})")

        now = self.clock()
        artifact = self._artifact(title_id, commit, entries, inputs, prototype, now, context,
                                  integrated, lineage)
        metadata = {"platforms": {e["platform_id"]: e["status"] for e in entries},
                    "commit": commit, "base_commit": base, "sdk_commits": list(own) or None,
                    "browser": None if run.browser is None else run.browser["passed"]}
        metadata = {k: v for k, v in metadata.items() if v is not None}
        output = ArtifactOutput("sdk-report", artifact, metadata=metadata)
        context.logger.info("sdk conformance read", platforms=metadata["platforms"], commit=commit)
        if integrated:
            tests = integrated["integration"]["tests"]
            metadata["integration"] = tests["status"]
            if tests["status"] == "failed":
                return StepResult("FAILED", retryable=False, artifacts=[output],
                                  error="the integration's own suite failed: "
                                        + tests.get("note", "see integration.tests"))
        if blocking:
            return StepResult("FAILED", retryable=False, artifacts=[output],
                              error=f"required platform integration not working: {', '.join(blocking)}")
        return StepResult.success(
            [output], message=f"{len(entries)} platform(s) working"
            if not degraded else f"required platforms working; optional not working: {', '.join(degraded)}")

    def _artifact(self, title_id, commit, entries, inputs, prototype, now, context,
                  integrated=None, lineage=None):
        provenance = {
            "artifact_id": f"wgf:sdk-report:{title_id}:{now[:10].replace('-', '')}-{min(context.execution, 99):02d}",
            "artifact_type": "sdk-report",
            "schema_version": SCHEMA_VERSION,
            "title_id": title_id,
            "produced_by": {"role": ROLE, "actor": "automation"},
            "produced_at": now,
            "inputs": [],
            "content_hash": "",
            "status": "draft",
        }
        for input_type, ref in sorted((getattr(inputs, "refs", None) or {}).items()):
            source = (inputs.load(input_type) or {}).get("provenance") or {}
            if ref is not None and ref.content_hash and source.get("artifact_id"):
                provenance["inputs"].append({"artifact_id": source["artifact_id"],
                                             "artifact_type": input_type,
                                             "content_hash": ref.content_hash})
        build_ref = {"commit_sha": commit, **(lineage or {})}
        url = ((prototype or {}).get("build_ref") or {}).get("url")
        if url:
            build_ref["url"] = url
        artifact = {"provenance": provenance, "title_id": title_id, "build_ref": build_ref,
                    "platforms": entries}
        if integrated:
            artifact["sdk"] = integrated["sdk"]
            artifact["integration"] = integrated["integration"]
        artifact["provenance"]["content_hash"] = content_hash(artifact)
        return artifact


def register(registry):
    registry.register(SdkStep.type, SdkStep)
    return registry

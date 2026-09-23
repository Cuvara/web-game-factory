"""The `sdk` step: prototype-report in, sdk-report out.

    game.config.yaml + pinned profiles ──► integration plan (what each platform requires)
    game repo `pnpm sdk:conformance`   ──► evidence (fake portal SDKs; optional browser smoke)
                                        ──► sdk-report: per platform, per feature, how observed

Where the game repository is: `with: {game_repo: <path>}` on the workflow step, else the
WGF_GAME_REPO environment variable, else `factory.sdk.game_repo` in
workspace/config/factory.yaml — the order the verify step uses. `with: {browser: true}` (or
`factory.sdk.browser`) also runs the browser smoke. `with: {report: <path>}` reads an
existing conformance report — a CI artifact, say — instead of running the suite.

Outcomes (docs/workflow-module-contract.md §7):

    no game repository configured, or no game.config.yaml   BLOCKED: platform not configured
    a platform pin that does not match its profile           BLOCKED: re-pin via the tech plan
    the suite could not run (toolchain, timeout)             FAILED, retryable
    a REQUIRED platform with a required feature not working  FAILED, not retryable, sdk-report
                                                             persisted as evidence
    otherwise                                                SUCCESS; optional platforms that
                                                             are not working are named in the
                                                             message and metadata

A `working` feature is one whose every conformance scenario passed. A skipped scenario (no
adapter on this ref) is `not-started`, never `working`. The step publishes nothing.
"""

import datetime
import os

from wgflib.hashing import content_hash
from wgflib.workflow import ArtifactOutput, StepResult, WorkflowStep

from . import evidence as ev
from .plan import FEATURES, PlanError, integration_plan, load_game_config

__all__ = ["SdkStep", "register", "SCHEMA_VERSION", "ROLE"]

SCHEMA_VERSION = "1.0.0"
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


class SdkStep(WorkflowStep):
    type = "sdk"

    clock = staticmethod(utc_now)
    runner_factory = ev.PnpmRunner
    profiles_dir = None

    def _setting(self, context, key, default=None):
        if key in self.params:
            return self.params[key]
        return ((context.config or {}).get("sdk") or {}).get(key, default)

    def execute(self, inputs, context):
        # Same order the verify step uses: the step's parameter, WGF_GAME_REPO, then config.
        game_repo = (self.params.get("game_repo") or os.environ.get("WGF_GAME_REPO")
                     or ((context.config or {}).get("sdk") or {}).get("game_repo"))
        if not game_repo:
            return StepResult.blocked(
                "platform not configured: no game repository (with: {game_repo} on the step, "
                "WGF_GAME_REPO, or factory.sdk.game_repo)")
        game_repo = os.path.abspath(os.path.expanduser(game_repo))
        try:
            config = load_game_config(game_repo)
            plans = integration_plan(config, self.profiles_dir)
        except PlanError as exc:
            return StepResult.blocked(str(exc))

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

        prototype = inputs.load("prototype-report") if "prototype-report" in inputs else {}
        build_commit = ((prototype or {}).get("build_ref") or {}).get("commit_sha")
        commit = run.commit or build_commit or "unknown"
        title_id = (prototype or {}).get("title_id") or (config.get("game") or {}).get("id") or context.project_id

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
            if build_commit and run.commit and build_commit != run.commit:
                notes.append(f"conformance ran at {run.commit}, the prototype build is {build_commit}")
            entry = {"platform_id": plan.id, "profile_version": plan.version, "status": status,
                     "features": items}
            if notes:
                entry["note"] = " | ".join(notes)
            entries.append(entry)
            if status != "working":
                (blocking if plan.role == "required" else degraded).append(f"{plan.id} ({status})")

        now = self.clock()
        artifact = self._artifact(title_id, commit, entries, inputs, prototype, now, context)
        metadata = {"platforms": {e["platform_id"]: e["status"] for e in entries},
                    "commit": commit, "browser": None if run.browser is None else run.browser["passed"]}
        metadata = {k: v for k, v in metadata.items() if v is not None}
        output = ArtifactOutput("sdk-report", artifact, metadata=metadata)
        context.logger.info("sdk conformance read", platforms=metadata["platforms"], commit=commit)
        if blocking:
            return StepResult("FAILED", retryable=False, artifacts=[output],
                              error=f"required platform integration not working: {', '.join(blocking)}")
        return StepResult.success(
            [output], message=f"{len(entries)} platform(s) working"
            if not degraded else f"required platforms working; optional not working: {', '.join(degraded)}")

    def _artifact(self, title_id, commit, entries, inputs, prototype, now, context):
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
        ref = inputs.refs.get("prototype-report") if hasattr(inputs, "refs") else None
        source = (prototype or {}).get("provenance") or {}
        if ref is not None and ref.content_hash and source.get("artifact_id"):
            provenance["inputs"].append({"artifact_id": source["artifact_id"],
                                         "artifact_type": "prototype-report",
                                         "content_hash": ref.content_hash})
        build_ref = {"commit_sha": commit}
        url = ((prototype or {}).get("build_ref") or {}).get("url")
        if url:
            build_ref["url"] = url
        artifact = {"provenance": provenance, "title_id": title_id, "build_ref": build_ref,
                    "platforms": entries}
        artifact["provenance"]["content_hash"] = content_hash(artifact)
        return artifact


def register(registry):
    registry.register(SdkStep.type, SdkStep)
    return registry

"""The production-quality step: a build is held to production art and production UI.

    playability-report (records_dir, commit) + asset-manifest + game-design + scaffold-record
      -> the playability bot's raw records under the run (no replay): entity samples with each
         entity's asset and render, the requests for files under /assets/, the DOM UI
         measured on each screen state, and the frames of those states
      -> checks.judge, against core/reference/production-quality.yaml
      -> production-quality-report

    PASS      every required check passed                                SUCCESS
    FAIL      a required check failed                                    FAILED, not retryable,
              route `assets` when any failed check routes there (an asset must be made
              again), else `develop` (the game's use of assets, or its UI, must change)
    BLOCKED   there is nothing to judge: the playability step left no records (it was
              blocked, or ran a bot that predates them)                  BLOCKED

It never plays the game and never touches the checkout: it reads what playability recorded,
so the two judge the same build. This is automation evidence (`measurement_class:
automation-bot`); how the result looks to a person is visual QA's.
"""

import datetime
import json
import os

from wgflib import paths, provenance
from wgflib.workflow import ArtifactOutput, StepResult, WorkflowStep
from wgflib.yamllite import load_file

from . import checks as judging

__all__ = ["ProductionQualityStep", "RULES_PATH", "REQUIRED_INPUTS", "load_rules", "load_records"]

RULES_PATH = os.path.join(paths.REFERENCE, "production-quality.yaml")
REQUIRED_INPUTS = ("playability-report", "asset-manifest", "game-design", "scaffold-record")
# The bot's records per viewport (scripts/wgf_playability/bot.spec.ts).
RECORDS = ("first-session", "act", "win", "lose", "pause", "showcase")
ROUTE_ORDER = ("assets", "develop")


def _utc_now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_rules(path=None):
    return load_file(path or RULES_PATH)


def load_records(directory, projects):
    """({project: {test: record}}, {project: frames dir}) from a playability records_dir."""
    records, frames = {}, {}
    for project in projects:
        found = {}
        for name in RECORDS:
            path = os.path.join(directory, project, f"{name}.json")
            if os.path.isfile(path):
                with open(path, encoding="utf-8") as handle:
                    found[name] = json.load(handle)
        if found:
            records[project] = found
            frames[project] = os.path.join(directory, project, "frames")
    return records, frames


class ProductionQualityStep(WorkflowStep):
    type = "production-quality"
    clock = staticmethod(_utc_now)

    def execute(self, inputs, context):
        missing = [t for t in REQUIRED_INPUTS if t not in inputs]
        if missing:
            return StepResult.waiting_for_input(
                f"production-quality needs {', '.join(missing)} in the run: nothing to judge")
        play = inputs.load("playability-report")
        manifest = inputs.load("asset-manifest")
        design = inputs.load("game-design")
        scaffold = inputs.load("scaffold-record")
        title_id = scaffold.get("title_id") or play.get("title_id") or design.get("title_id")
        commit = play.get("commit") or "0" * 40

        records_dir = play.get("records_dir")
        blocked = None
        if play.get("verdict") == "BLOCKED":
            blocked = f"the playability step was blocked: {play.get('blocked_reason')}"
        elif not records_dir:
            blocked = ("the playability-report names no records_dir (playability-report "
                       "1.1.0): play the build again so its records are kept")
        records, frames = {}, {}
        if not blocked:
            directory = os.path.join(context.run_dir, records_dir)
            projects = [p.get("id") for p in play.get("projects") or [] if p.get("ran")]
            records, frames = load_records(directory, projects)
            if not records:
                blocked = f"no playability records under {directory}"
        checks = []
        if not blocked:
            checks = judging.judge(records, manifest, design, load_rules(), frames)
            stale = [c for c in checks if c["required"] and c["status"] == "BLOCKED"]
            if stale:
                blocked = "; ".join(c["summary"] for c in stale)
        return self._finish(context, inputs, title_id, commit, checks, blocked)

    def _finish(self, context, inputs, title_id, commit, checks, blocked):
        failing = [c for c in checks if c["required"] and c["status"] == "FAIL"]
        failed = sorted({f"{c['project']}:{c['id']}" if c.get("project") else c["id"]
                         for c in failing})
        routes = [r for r in ROUTE_ORDER if any(c["route"] == r for c in failing)]
        verdict = "BLOCKED" if blocked else ("FAIL" if failed else "PASS")
        now = self.clock()
        report = {
            "provenance": provenance.build(
                "production-quality-report",
                artifact_id=provenance.artifact_id("production-quality-report", title_id, now,
                                                   getattr(context, "execution", 1)),
                produced_by=provenance.producer("qa"), produced_at=now,
                inputs=provenance.pin_inputs(inputs, REQUIRED_INPUTS), title_id=title_id),
            "title_id": title_id,
            "commit": commit,
            "measurement_class": "automation-bot",
            "checks": checks,
            "failed": failed,
            "routes": routes,
            "blocked_reason": blocked,
            "verdict": verdict,
        }
        output = ArtifactOutput("production-quality-report", provenance.seal(report),
                                metadata={"verdict": verdict, "failed": len(failed),
                                          "routes": routes, "commit": commit})
        if blocked:
            context.logger.warning("production-quality blocked", reason=blocked)
            return StepResult("BLOCKED", artifacts=[output], message=blocked)
        if failed:
            route = routes[0]
            context.logger.error("the build is not production quality", failed=failed, route=route)
            return StepResult("FAILED", route=route, artifacts=[output], retryable=False,
                              error=f"{len(failed)} production check(s) failed (route {route}): "
                                    + "; ".join(f"{c.get('project') + ':' if c.get('project') else ''}"
                                                f"{c['id']}: {c['summary']}" for c in failing[:6]))
        return StepResult.success([output], message=(
            f"{commit[:12]} is production quality: {len(checks)} checks passed"))

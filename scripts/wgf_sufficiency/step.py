"""The content-sufficiency step: the BUILT game carries the content its quality tier asks for.

    playability-report (records_dir, commit) + game-design + scaffold-record [+ title-strategy]
      -> the playability bot's records under the run (no replay): the traverse, the survey of
         every unit entered through the probe's unit link, the probe snapshots with their
         entities; and the content data file of the commit it played, with its layout
         source when it ships one (records_dir/content/, wgf_design/layouts.py)
      -> audit.audit, against core/reference/quality-benchmark.yaml at the design's tier - the
         copy the run pinned when it started (new-game `pinned_references`), so an edit made
         while it runs applies to the next run - the genre family's bars and
         core/reference/content-sufficiency.yaml
      -> content-sufficiency-report, with typed findings

    PASS      every required check passed                                SUCCESS
    FAIL      a required check failed                                    FAILED, not retryable,
              route `design-gap` when the design itself is short of a bar it failed (the
              design must grow; its findings carry the design gaps), else `develop` (the
              build is short of a design that meets the bar)
    BLOCKED   there is nothing to judge: the playability step was blocked or left no records;
              or the run's pinned benchmark is gone or was edited after the start

It never plays the game and never touches the checkout: it reads what playability recorded of
the same commit, so every gate judges one build. Automation evidence (`measurement_class:
automation-bot`).
"""

import datetime
import json
import os

from wgflib import provenance
from wgflib.workflow import ArtifactOutput, StepResult, WorkflowStep
from wgflib.workflow import references as pinned_references
from wgflib.yamllite import YamlError, load as load_yaml

from wgf_design import layouts

from . import audit as auditing

__all__ = ["ContentSufficiencyStep", "REQUIRED_INPUTS", "RECORDS", "ROUTE_ORDER",
           "CONTENT_COPY", "BENCHMARK", "load_records", "read_data", "read_layouts",
           "run_benchmark"]

REQUIRED_INPUTS = ("playability-report", "game-design", "scaffold-record")
# The bot's records per viewport this step reads (scripts/wgf_playability/bot.spec.ts).
RECORDS = ("first-session", "act", "traverse", "survey")
# Where the playability step keeps the content data file of the commit it played, under its
# records_dir (scripts/wgf_playability/step.py).
CONTENT_COPY = os.path.join("content", "units.json")
# The design must grow before the build can catch up with it.
ROUTE_ORDER = ("design-gap", "develop")
# The bars, as the run pinned them when it started (new-game `pinned_references`): an edit
# made while the run is going applies to the next run, never to this one's build.
BENCHMARK = "core/reference/quality-benchmark.yaml"


def _utc_now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_records(directory, projects):
    """{project: {test: record}} from a playability records_dir."""
    records = {}
    for project in projects:
        found = {}
        for name in RECORDS:
            path = os.path.join(directory, project, f"{name}.json")
            if os.path.isfile(path):
                with open(path, encoding="utf-8") as handle:
                    found[name] = json.load(handle)
        if found:
            records[project] = found
    return records


def run_benchmark(context):
    """core/reference/quality-benchmark.yaml as the run pinned it (the live file for a run
    that pinned none). Raises PinError when the run's copy is gone or was edited."""
    text, _digest, _pinned = pinned_references.read(
        BENCHMARK, getattr(context, "environment", None), getattr(context, "run_dir", None))
    return load_yaml(text)


def read_data(directory):
    """(the content data file the played commit shipped, None) or (None, why not)."""
    path = os.path.join(directory, CONTENT_COPY)
    if not os.path.isfile(path):
        return None, ("the commit the playability step played ships no "
                      "public/content/units.json")
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError) as exc:
        return None, f"public/content/units.json cannot be read: {exc}"
    if not isinstance(data, dict):
        return None, "public/content/units.json is not a JSON object"
    return data, None


def read_layouts(directory, data, rules=None):
    """({unit id: layout} or None, why it could not be read or None): the layout source the
    played commit shipped beside its content data file (core/reference/content-sufficiency.yaml
    `layout.source`, or the data file's `layout_source`), as playability kept it. A unit's
    geometry is measured on it as well as on the unit's own entry."""
    if data is None:
        return None, None
    rules = auditing.load_rules() if rules is None else rules
    return layouts.read_source(os.path.join(directory, os.path.dirname(CONTENT_COPY)), data,
                               rules)


class ContentSufficiencyStep(WorkflowStep):
    type = "content-sufficiency"
    clock = staticmethod(_utc_now)

    def execute(self, inputs, context):
        self._layout_source = None
        missing = [t for t in REQUIRED_INPUTS if t not in inputs]
        if missing:
            return StepResult.waiting_for_input(
                f"content-sufficiency needs {', '.join(missing)} in the run: nothing to judge")
        play = inputs.load("playability-report")
        design = inputs.load("game-design")
        scaffold = inputs.load("scaffold-record")
        strategy = inputs.load("title-strategy") if "title-strategy" in inputs else None
        title_id = scaffold.get("title_id") or play.get("title_id") or design.get("title_id")
        commit = play.get("commit") or "0" * 40

        blocked, result = None, None
        records_dir = play.get("records_dir")
        if play.get("verdict") == "BLOCKED":
            blocked = f"the playability step was blocked: {play.get('blocked_reason')}"
        elif not records_dir:
            blocked = ("the playability-report names no records_dir: play the build again so "
                       "its records are kept")
        if not blocked:
            directory = os.path.join(context.run_dir, records_dir)
            projects = [p.get("id") for p in play.get("projects") or [] if p.get("ran")]
            records = load_records(directory, projects)
            if not records:
                blocked = f"no playability records under {directory}"
            else:
                data, problem = read_data(directory)
                try:
                    found, unreadable = read_layouts(directory, data)
                    if unreadable:
                        context.logger.warning("the layout source cannot be read",
                                               reason=unreadable)
                    self._layout_source = (
                        {"status": "unreadable", "problem": str(unreadable)} if unreadable
                        else {"status": "read" if found is not None else "none"})
                    result = auditing.audit(design, strategy, data, records,
                                            benchmark=run_benchmark(context),
                                            data_problem=problem, playability=play,
                                            layouts=found)
                except pinned_references.PinError as exc:
                    blocked = (f"the quality benchmark this run started under cannot be read "
                               f"({exc}): nothing is held to bars edited after the start")
                except (OSError, YamlError, ValueError) as exc:
                    blocked = (f"the content bars could not be read ({exc}): nothing can be "
                               "held to them, and no bar is defaulted in code")
        return self._finish(context, inputs, title_id, commit, result, blocked)

    def _finish(self, context, inputs, title_id, commit, result, blocked):
        result = result or {"checks": [], "findings": [], "tier": None, "mode": None}
        checks, findings = result["checks"], result["findings"]
        failing = [c for c in checks if c["required"] and c["status"] == "FAIL"]
        failed = sorted(c["id"] for c in failing)
        routes = [r for r in ROUTE_ORDER if any(c.get("route") == r for c in failing)]
        skipped = [{"id": c["id"], "reason": c["summary"]} for c in checks
                   if c["status"] == "SKIPPED"]
        verdict = "BLOCKED" if blocked else ("FAIL" if failed else "PASS")
        now = self.clock()
        report = {
            "provenance": provenance.build(
                "content-sufficiency-report",
                artifact_id=provenance.artifact_id("content-sufficiency-report", title_id, now,
                                                   getattr(context, "execution", 1)),
                produced_by=provenance.producer("qa"), produced_at=now,
                inputs=provenance.pin_inputs(inputs), title_id=title_id),
            "title_id": title_id,
            "commit": commit,
            "measurement_class": "automation-bot",
            "quality_tier": result.get("tier"),
            "generation_mode": result.get("mode"),
            "checks": checks,
            "findings": findings,
            "failed": failed,
            "routes": routes,
            "skipped_checks": skipped,
            "blocked_reason": blocked,
            "verdict": verdict,
        }
        if getattr(self, "_layout_source", None) and not blocked:
            report["layout_source"] = dict(self._layout_source)
        output = ArtifactOutput("content-sufficiency-report", provenance.seal(report),
                                metadata={"verdict": verdict, "failed": len(failed),
                                          "routes": routes, "commit": commit})
        if blocked:
            context.logger.warning("content-sufficiency blocked", reason=blocked)
            return StepResult("BLOCKED", artifacts=[output], message=blocked)
        note = (f". {len(skipped)} check(s) measured nothing (not passes): "
                + ", ".join(s["id"] for s in skipped)) if skipped else ""
        if failed:
            route = routes[0]
            context.logger.error("the build's content is short of its tier", failed=failed,
                                 route=route)
            return StepResult("FAILED", route=route, artifacts=[output], retryable=False,
                              error=f"{len(failed)} content check(s) failed (route {route}): "
                                    + "; ".join(f"{c['id']}: {c['summary']}"
                                                for c in failing[:5]) + note)
        return StepResult.success([output], message=(
            f"{commit[:12]} carries the content of tier {result.get('tier') or 'none'}: "
            f"{sum(1 for c in checks if c['status'] == 'PASS')} checks passed" + note))

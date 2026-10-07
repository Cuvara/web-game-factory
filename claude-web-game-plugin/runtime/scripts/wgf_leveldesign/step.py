"""The `level-design` step: a level critic reads every sampled unit, and the oracle's safe and
greedy policies show whether an optional risk exists and pays.

    inputs   playability-report (its records: the survey's level frames, the risk test),
             game-design (build_spec.content.units) - required; title-strategy - read when
             present (the tier, when the run snapshotted none)
    output   level-design-report, on every outcome that judged or could not
    effect   none outside the run directory: the critic reads copies of the frames in
             <run>/level-design/<step>-<visit>-<attempt>/ and writes its verdict there

    checks   level.frames   every sampled unit has its start, middle and end frame
             level.critic   every unit at or above the rubric's bars, no blocker, the mean at
                            its bar, no applicable dimension unmeasured
             risk.measured  every sampled unit played under both policies with a reward reading
             risk.reward    greedy earns measurably more at a measurably higher failure rate
                            on the rubric's share of units (core/reference/risk-reward.yaml)

At a strict tier (core/reference/quality-policy.yaml skipped_checks, the release tier as
shipped) every check is required and one that measured nothing is not passed: FAILED, route
`design-gap` when a failure routes there, else `develop`, not retryable; no judge configured
is BLOCKED. Below it the same results are reported - WARNING, or SKIPPED with the reason -
and the step succeeds: the quality floor holds a release build to them, a development build
is told. The checks are not reported at all for a design that authors no units (level.*) -
there are no levels to judge - but risk.* always is.

The rubric and the risk rules are the copies the run pinned when it started (new-game
`pinned_references`); a rubric configured by path (factory.leveldesign.rubric) is read as
configured. The judge is configured, never named here (settings.py); `baseline` is no agent
(baseline.py). See docs/level-design-critic.md.
"""

import datetime
import json
import os
import shutil

from wgflib import check_strength, isolation, paths, provenance
from wgflib.workflow import ArtifactOutput, StepResult, WorkflowStep
from wgflib.workflow import references as pinned_references
from wgflib.workflow.quality import run_tier

from wgf_design.content import quality_tier

from . import baseline, risk
from .judge import MAX_JUDGE_RUNS, Outcome, run_judge
from .rubric import RubricError, decide, dimensions, load_risk_rules, load_rubric
from .settings import Settings, SettingsError
from .units import FrameError, design_units, sample, stage

__all__ = ["LevelDesignStep", "REQUIRED_INPUTS", "OPTIONAL_INPUTS", "RUBRIC", "RISK"]

REQUIRED_INPUTS = ("playability-report", "game-design")
OPTIONAL_INPUTS = ("title-strategy",)
ROLE = "qa"
OWNER = "level-design"
DIMENSION = "level-design"
RUBRIC = "core/reference/level-design-rubric.yaml"
RISK = "core/reference/risk-reward.yaml"


def _utc_now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _pinned(relpath, loader, context, configured=None):
    if configured:
        return loader(configured)
    run_dir = getattr(context, "run_dir", None)
    _text, _digest, pinned = pinned_references.read(
        relpath, getattr(context, "environment", None), run_dir)
    if not pinned:
        return loader()
    return loader(os.path.join(run_dir, pinned_references.DIRECTORY, *relpath.split("/")))


def _model_of(argv):
    for flag in ("--model", "-m"):
        if flag in argv[:-1]:
            return argv[argv.index(flag) + 1]
    return None


def _status(ok, strict):
    """A check's (status, required) from its result: True passed, False fell short, None
    measured nothing. At a strict tier nothing but a pass is passed."""
    if ok is True:
        return "PASS", strict
    if ok is False:
        return ("FAIL" if strict else "WARNING"), strict
    return ("FAIL" if strict else "SKIPPED"), strict


class LevelDesignStep(WorkflowStep):
    type = "level-design"
    clock = staticmethod(_utc_now)

    def execute(self, inputs, context):
        self._decided = None
        try:
            settings = Settings.resolve(context.config, self.params)
        except SettingsError as exc:
            return StepResult.failed(str(exc), retryable=False)
        missing = [t for t in REQUIRED_INPUTS if t not in inputs]
        if missing:
            return StepResult.waiting_for_input(
                f"level-design needs {', '.join(missing)} in the run: there is no play to judge")
        try:
            rubric = _pinned(RUBRIC, load_rubric, context, settings.rubric_path)
            rules = _pinned(RISK, load_risk_rules, context)
        except pinned_references.PinError as exc:
            reason = (f"a level-design reference this run started under cannot be read ({exc}): "
                      "no build is judged against a contract edited after the start")
            context.logger.warning("level-design blocked", reason=reason)
            return StepResult("BLOCKED", message=reason)
        except RubricError as exc:
            return StepResult.failed(str(exc), retryable=False)

        play = inputs.load("playability-report")
        design = inputs.load("game-design")
        strategy = inputs.load("title-strategy") if "title-strategy" in inputs else None
        tier = (run_tier(getattr(context, "environment", None))
                or quality_tier(design, strategy)[0])
        try:
            strict = check_strength.for_tier(tier).strict
        except ValueError as exc:
            return StepResult.failed(str(exc), retryable=False)
        title_id = play.get("title_id") or design.get("title_id")
        commit = play.get("commit") or "0" * 40
        self._ctx = dict(context=context, inputs=inputs, title_id=title_id, commit=commit,
                         rubric=rubric, rules=rules, settings=settings, tier=tier)

        run_dir = context.run_dir
        units, project, no_units = sample(rubric, play, run_dir, design)
        _by_id, authored = design_units(design)
        workdir = os.path.join(run_dir, "level-design",
                               f"{self.id}-{context.visit}-{context.attempt}")
        shutil.rmtree(workdir, ignore_errors=True)
        os.makedirs(workdir)

        checks, findings, notes = [], [], []
        verdict_data, outcome, measures = None, None, {}
        blocked = None
        if authored or units:
            frames_ok = None if not units else not any(u["missing_moments"] for u in units)
            missing = {u["unit_id"]: u["missing_moments"] for u in units if u["missing_moments"]}
            status, required = _status(frames_ok, strict)
            checks.append({"id": "level.frames", "status": status, "required": required,
                           "summary": (no_units if not units else
                                       f"{len(units)} unit(s) sampled; "
                                       + (f"{len(missing)} lack a moment" if missing
                                          else "every moment captured")),
                           "measured": {"units": [u["unit_id"] for u in units],
                                        "missing": missing},
                           "expected": [m["id"] for m in rubric["moments"]], "route": "develop"})
            if status in ("FAIL", "WARNING"):
                findings.append(self._finding(
                    "level.frames", "frames", "major",
                    (no_units or "units lack the frames the critic reads: "
                     + "; ".join(f"{k}: {', '.join(v)}" for k, v in list(missing.items())[:6])
                     + " - the survey must enter every unit through the probe's unit link "
                       "and play it long enough to reach its middle and its end"),
                    "develop", observed=missing or None))
            if units and settings.kind == "none":
                checks.append(self._skipped_critic(strict))
                if strict:
                    blocked = ("the level critic needs a judge: factory.leveldesign.judge.kind is "
                               "`none`, and at quality tier " + str(tier) + " a level nothing "
                               "judged is not passed. Configure a command judge able to read "
                               "images (docs/level-design-critic.md) and resume.")
            elif units:
                try:
                    frames_dir = stage(units, workdir)
                except FrameError as exc:
                    if exc.kind == "missing":
                        return self._blocked(f"{exc}; the playability evidence is gone - play "
                                             "the build again", tier, units)
                    return StepResult.failed(str(exc), retryable=False)
                try:
                    guarded = isolation.guarded_paths(context.config)
                except ValueError as exc:
                    return StepResult.failed(str(exc), retryable=False)
                if settings.kind == "baseline":
                    outcome = Outcome()
                    try:
                        outcome.verdict, measures = baseline.judge(
                            rubric, units, settings.baseline_dir, settings.min_similarity)
                        outcome.runs.append({"kind": "baseline"})
                    except baseline.BaselineError as exc:
                        outcome.failure = {"code": "baseline-unusable", "message": str(exc),
                                           "retryable": False}
                    with open(os.path.join(workdir, "baseline.json"), "w",
                              encoding="utf-8") as handle:
                        json.dump({"measures": measures}, handle, indent=2)
                        handle.write("\n")
                else:
                    outcome = run_judge(settings, rubric, workdir, units, frames_dir,
                                        title_id=title_id, commit=commit, guarded=guarded,
                                        logger=context.logger, stem=self.id)
                if outcome.failure is not None:
                    failure = outcome.failure
                    context.logger.error("level-design critic failed", code=failure["code"])
                    return StepResult("FAILED", retryable=failure["retryable"],
                                      error=f"{failure['code']}: {failure['message']} "
                                            f"(see {workdir})",
                                      data={"output_tail": failure.get("output_tail")})
                verdict_data = outcome.verdict
                checks.append(self._critic_check(verdict_data, rubric, units, strict,
                                                 findings))
        else:
            notes.append("the design authors no units: there are no levels to critique "
                         "(level.* not reported)")

        risk_project = next((p for p in (rules.get("play") or {}).get("projects") or []), None)
        record = None
        if play.get("records_dir") and risk_project:
            path = os.path.join(run_dir, *play["records_dir"].split("/"), risk_project,
                                "risk.json")
            if os.path.isfile(path):
                with open(path, encoding="utf-8") as handle:
                    record = json.load(handle)
        risk_block, raw = risk.judge(record, rules)
        for check_id, key in (("risk.measured", "measured"), ("risk.reward", "reward")):
            ok, why = raw[key]
            if key == "measured" and ok is False:
                ok = None if not strict else False
            status, required = _status(ok, strict)
            checks.append({"id": check_id, "status": status, "required": required,
                           "summary": why, "route": "develop",
                           "measured": {"units": [{k: u.get(k) for k in (
                               "unit_id", "measured", "reward_gain", "relative_gain",
                               "failure_rate_gain", "pays", "risky")}
                               for u in risk_block.get("units") or []]}
                           if key == "reward" else None,
                           "expected": dict(rules["bars"]) if key == "reward" else None})
            if status in ("FAIL", "WARNING"):
                findings.append(self._finding(
                    check_id, "risk", "major",
                    why + (" - the probe's play.policy must let the oracle play `safe` and "
                           "`greedy`, and a greedy line must exist that earns more at a "
                           "higher risk" if key == "measured" else
                           " - place optional rewards off the safe line, where taking them "
                           "risks failure, and make them worth it"),
                    "develop", observed=risk_block.get("units") or None,
                    bar=dict(rules["bars"])))
        for check in checks:
            for key in ("measured", "expected"):
                if check.get(key) is None:
                    check.pop(key, None)
        return self._finish(checks, findings, units, verdict_data, outcome, measures,
                            risk_block, blocked, notes, strict)

    # -- the critic's check -----------------------------------------------------------------

    def _skipped_critic(self, strict):
        status, required = _status(None, strict)
        return {"id": "level.critic", "status": status, "required": required,
                "summary": "no level critic configured (factory.leveldesign.judge.kind none): "
                           "nothing was judged - not a pass", "route": "develop"}

    def _critic_check(self, verdict, rubric, units, strict, findings):
        decided = decide(verdict, rubric, units)
        bar = rubric["pass_bar"]
        by_unit = {e["unit_id"]: e for e in verdict.get("units") or []}
        frames = {u["unit_id"]: [f["path"] for f in u["frames"]] for u in units}
        for uid, name, value in decided["failing"]:
            reason = ((by_unit.get(uid) or {}).get("score_reasons") or {}).get(name)
            route = rubric["dimensions"][name]["route"]
            findings.append(self._finding(
                f"level.critic:{name}", f"{name}@{uid}", "major",
                f"unit {uid}: {name} scored {value} (bar {bar})"
                + (f" - {reason}" if reason else "") + f". {rubric['dimensions'][name]['question']}",
                route, unit=uid, observed=value, bar=bar, evidence=frames.get(uid)))
        for item in verdict.get("findings") or []:
            uid = item.get("unit")
            findings.append(self._finding(
                f"level.critic:{item['id']}", f"{item['id']}" + (f"@{uid}" if uid else ""),
                item["severity"], item["summary"], item["route"], unit=uid,
                frame=item.get("frame"), evidence=frames.get(uid) if uid else None))
        if decided["mean"] is not None and decided["mean"] < rubric["mean_pass_bar"]:
            findings.append(self._finding(
                "level.critic:mean", "mean", "major",
                f"the mean level-design score is {decided['mean']} (bar "
                f"{rubric['mean_pass_bar']}): the units are plain across the board",
                "develop", observed=decided["mean"], bar=rubric["mean_pass_bar"]))
        if decided["unmeasured"] and strict:
            listed = ", ".join(f"{u}:{d}" for u, d in decided["unmeasured"][:8])
            findings.append(self._finding(
                "level.critic:unmeasured", "unmeasured", "major",
                f"the frames could not show {len(decided['unmeasured'])} unit dimension(s) "
                f"({listed}): unmeasured is not passed at this tier", "develop",
                observed=[f"{u}:{d}" for u, d in decided["unmeasured"]]))
        if decided["failing"] or decided["blockers"] or (
                decided["mean"] is not None and decided["mean"] < rubric["mean_pass_bar"]):
            ok = False
        elif decided["unmeasured"]:
            ok = None
        else:
            ok = True
        status, required = _status(ok, strict)
        self._decided = decided
        routes = decided["routes"] or ["develop"]
        return {"id": "level.critic", "status": status, "required": required,
                "summary": (f"{len(units)} unit(s): {len(decided['failing'])} dimension(s) below "
                            f"{bar}, {len(decided['blockers'])} blocker(s), mean "
                            f"{decided['mean']}, {len(decided['unmeasured'])} unmeasured"),
                "measured": {"lowest": decided["lowest"], "mean": decided["mean"],
                             "unmeasured": [f"{u}:{d}" for u, d in decided["unmeasured"]]},
                "expected": {"pass_bar": bar, "mean_pass_bar": rubric["mean_pass_bar"]},
                "route": routes[0]}

    def _finding(self, check, key, severity, summary, route, *, unit=None, frame=None,
                 observed=None, bar=None, evidence=None):
        finding = {"id": f"level-design:{key}".lower().replace(" ", "-"), "check": check,
                   "dimension": DIMENSION, "severity": severity, "summary": summary,
                   "owner": OWNER, "route": route, "unit": unit, "frame": frame}
        if observed is not None:
            finding["observed"] = observed
        if bar is not None:
            finding["bar"] = bar
        if evidence:
            finding["evidence"] = [e for e in evidence if isinstance(e, str)]
        if route == "design-gap":
            finding["design_gap"] = {
                "field": "build_spec.content.units" + (f"[{unit}]" if unit else ""),
                "question": summary, "assumed": None, "severity": "blocking"}
            if unit:
                finding["design_gap"]["unit"] = unit
        return finding

    # -- the report ---------------------------------------------------------------------

    def _blocked(self, reason, tier, units):
        return self._finish([], [], units or [], None, None, {}, {"applies": False,
                            "measured": False, "reason": "not judged", "units": []},
                            reason, [], True)

    def _finish(self, checks, findings, units, verdict, outcome, measures, risk_block,
                blocked, notes, strict):
        ctx = self._ctx
        context, settings, rubric, rules = (ctx["context"], ctx["settings"], ctx["rubric"],
                                            ctx["rules"])
        failed = [c["id"] for c in checks if c["required"] and c["status"] == "FAIL"]
        skipped = [{"id": c["id"], "reason": c["summary"]} for c in checks
                   if c["status"] == "SKIPPED"]
        routes = sorted({c.get("route") or "develop" for c in checks
                         if c["required"] and c["status"] == "FAIL"},
                        key=lambda r: 0 if r == "design-gap" else 1)
        if any(f["route"] == "design-gap" and f["severity"] in ("blocker", "major")
               for f in findings) and failed and "design-gap" not in routes:
            routes.insert(0, "design-gap")
        if blocked:
            status = "BLOCKED"
        elif failed:
            status = "FAIL"
        elif any(c["status"] in ("WARNING", "FAIL") for c in checks):
            status = "WARNING"
        elif not checks or all(c["status"] == "SKIPPED" for c in checks):
            status = "SKIPPED"
        elif any(c["status"] == "SKIPPED" for c in checks):
            status = "WARNING"
        else:
            status = "PASS"
        by_unit = {e["unit_id"]: e for e in (verdict or {}).get("units") or []}
        decided = getattr(self, "_decided", None) if verdict else None
        report_units = []
        for unit in units:
            entry = by_unit.get(unit["unit_id"]) or {}
            row = {"unit_id": unit["unit_id"], "index": unit.get("index"),
                   "source": unit.get("source"), "project": unit.get("project"),
                   "objective": unit.get("objective"),
                   "frames": [{"moment": f["moment"], "id": f["id"], "path": f["path"],
                               "sha256": f.get("sha256") or ""} for f in unit["frames"]],
                   "missing_moments": list(unit.get("missing_moments") or []),
                   "scores": {d: (entry.get("scores") or {}).get(d) for d in dimensions(rubric)}
                   if entry else {},
                   "comment": entry.get("comment")}
            reasons = {k: v for k, v in (entry.get("score_reasons") or {}).items()
                       if isinstance(v, str)}
            if reasons:
                row["score_reasons"] = reasons
            if unit["unit_id"] in measures:
                row["measures"] = measures[unit["unit_id"]]
            report_units.append(row)
        now = self.clock()
        judge = {"kind": settings.kind}
        if settings.kind == "command":
            judge.update(argv0=os.path.basename(settings.argv[0]),
                         model=_model_of(settings.argv), verdict_from=settings.verdict_from)
        elif settings.kind == "baseline":
            judge.update(model=None, baseline_dir=paths.display(settings.baseline_dir)
                         if settings.baseline_dir else None)
        types = REQUIRED_INPUTS + tuple(t for t in OPTIONAL_INPUTS if t in ctx["inputs"])
        runs = len(outcome.runs) if outcome else 0
        report = {
            "provenance": provenance.build(
                "level-design-report",
                artifact_id=provenance.artifact_id("level-design-report", ctx["title_id"], now,
                                                   getattr(context, "execution", 1)),
                produced_by=provenance.producer(
                    ROLE, "ai" if settings.kind == "command" and runs else "automation"),
                produced_at=now,
                inputs=provenance.pin_inputs(ctx["inputs"], types),
                title_id=ctx["title_id"]),
            "title_id": ctx["title_id"],
            "commit": ctx["commit"],
            "measurement_class": "automation-agent",
            "quality_tier": ctx["tier"],
            "judge": judge,
            "rubric": {"path": paths.display(rubric["path"]), "version": str(rubric["version"]),
                       "sha256": rubric["sha256"], "pass_bar": rubric["pass_bar"],
                       "mean_pass_bar": rubric["mean_pass_bar"]},
            "risk_rules": {"path": paths.display(rules["path"]), "version": str(rules["version"]),
                           "sha256": rules["sha256"]},
            "judge_runs": runs,
            "units": report_units,
            "scores": dict((decided or {}).get("lowest") or {}),
            "mean_score": (decided or {}).get("mean"),
            "risk": risk_block,
            "checks": checks,
            "findings": findings,
            "failed": failed,
            "routes": routes,
            "skipped_checks": skipped,
            "blocked_reason": blocked,
            "notes": "; ".join(notes) or None,
            "verdict": status,
        }
        artifact = ArtifactOutput("level-design-report", provenance.seal(report), metadata={
            "verdict": status, "failed": len(failed), "commit": ctx["commit"],
            "route": routes[0] if routes else None, "judge_runs": runs,
            "max_judge_runs": MAX_JUDGE_RUNS + getattr(settings, "repair_rounds", 0)})
        summary = "; ".join(f"{c['id']} {c['status']}" for c in checks)
        if status == "BLOCKED":
            context.logger.warning("level-design blocked", reason=blocked)
            return StepResult("BLOCKED", artifacts=[artifact], message=blocked)
        if status == "FAIL":
            context.logger.error("level design failed", failed=failed, route=routes[0])
            lead = [f["summary"] for f in findings if f["severity"] in ("blocker", "major")][:4]
            return StepResult("FAILED", route=routes[0], artifacts=[artifact], retryable=False,
                              error=f"level design failed {ctx['commit'][:12]} ({summary})"
                                    + (" - " + "; ".join(lead) if lead else ""))
        tail = ("" if strict or status == "PASS" else
                f" - below a strict tier ({ctx['tier']}), reported and not held: not a pass")
        return StepResult.success([artifact], message=(
            f"level design {status} on {ctx['commit'][:12]}: {summary or 'nothing to judge'}"
            + tail))

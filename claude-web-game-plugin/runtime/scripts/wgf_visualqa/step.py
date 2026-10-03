"""The `visual-qa` step: a vision judge reads the production build's frames against the rubric.

    inputs   playability-report (its frames: the production build, played), game-design
             (build_spec.visual_identity, build_spec.assets roles and readability),
             asset-manifest (what each asset is, placeholder, quality) - required;
             production-quality-report - read when present
    output   visual-qa-report, on every outcome that judged or could not (BLOCKED)
    effect   none outside the run directory: the judge reads copies of the frames in
             <run>/visual-qa/<step>-<visit>-<attempt>/ and writes its verdict there

    PASS      no blocker finding, every dimension at or above the pass bar   SUCCESS
    FAIL      a blocker, or a dimension below the bar                        FAILED, route
              `assets` when any failure routes there, else `develop`; not retryable - the
              workflow routes it back to the step that must change something
    BLOCKED   no judge configured (kind `none`: visual QA needs a judge - never a silent
              pass), no frames in the playability-report, or a frame no longer on disk

The judge is a command (an agent able to read images) or, for a game whose look was
approved once, `baseline`: each frame against the approved frame of its state (baseline.py),
no agent, the same verdict shape.

    FAILED final      malformed verdict twice (judge.MAX_JUDGE_RUNS), a judge that could not
                      start or changed what it may only read, a frame that is not the one
                      the playability step recorded, bad configuration or rubric
    FAILED retryable  the judge timed out, went idle or exited non-zero

The judge is configured, never named here: `factory.visualqa.judge` (settings.py), like
`factory.review.reviewer`. See docs/visual-qa-module.md.
"""

import datetime
import json
import os
import shutil

from wgflib import isolation, paths, provenance
from wgflib.workflow import ArtifactOutput, StepResult, WorkflowStep

from . import baseline
from .judge import MAX_JUDGE_RUNS, FrameError, Outcome, run_judge, stage_frames
from .rubric import RubricError, decide, judged_pairs, load_rubric, state_ids
from .settings import Settings, SettingsError

__all__ = ["VisualQAStep", "REQUIRED_INPUTS", "OPTIONAL_INPUTS"]

REQUIRED_INPUTS = ("playability-report", "game-design", "asset-manifest")
OPTIONAL_INPUTS = ("production-quality-report",)
ROLE = "qa"


def _utc_now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _model_of(argv):
    for flag in ("--model", "-m"):
        if flag in argv[:-1]:
            return argv[argv.index(flag) + 1]
    return None


def report_states(rubric, frames, answered):
    """Every rubric state on every viewport: the judge's answers where frames show it, and
    `captured: false` where none does - so a state the bot never captured is visibly
    unjudged, not silently absent."""
    by_pair = {(e["state"], e["viewport"]): e for e in answered}
    judged = set(judged_pairs(rubric, frames))
    viewports = []
    for frame in frames:
        if frame["project"] not in viewports:
            viewports.append(frame["project"])
    out = []
    for state in state_ids(rubric):
        for viewport in viewports:
            keys = [f["key"] for f in frames if f["state"] == state and f["project"] == viewport]
            entry = by_pair.get((state, viewport)) if (state, viewport) in judged else None
            out.append({"state": state, "viewport": viewport, "captured": bool(keys),
                        "frames": keys, "answers": dict((entry or {}).get("answers") or {}),
                        "comment": (entry or {}).get("comment") or (
                            None if keys else "no frame of this state was captured")})
    return out


class VisualQAStep(WorkflowStep):
    type = "visual-qa"
    clock = staticmethod(_utc_now)

    def execute(self, inputs, context):
        try:
            settings = Settings.resolve(context.config, self.params)
        except SettingsError as exc:
            return StepResult.failed(str(exc), retryable=False)
        missing = [t for t in REQUIRED_INPUTS if t not in inputs]
        if missing:
            return StepResult.waiting_for_input(
                f"visual-qa needs {', '.join(missing)} in the run: there are no frames to judge "
                f"against a design")
        try:
            rubric = load_rubric(settings.rubric_path)
        except RubricError as exc:
            return StepResult.failed(str(exc), retryable=False)

        play = inputs.load("playability-report")
        design = inputs.load("game-design")
        manifest = inputs.load("asset-manifest")
        quality = (inputs.load("production-quality-report")
                   if "production-quality-report" in inputs else None)
        title_id = play.get("title_id") or design.get("title_id")
        commit = play.get("commit") or "0" * 40
        self._ctx = dict(context=context, inputs=inputs, title_id=title_id, commit=commit,
                         rubric=rubric, settings=settings)

        viewports = {p.get("id"): p.get("viewport") for p in play.get("projects") or []
                     if isinstance(p, dict)}
        entries = []
        for frame in play.get("frames") or []:
            path = frame.get("path") or ""
            entries.append({"project": frame.get("project") or "unknown", "id": frame["id"],
                            "source": path if os.path.isabs(path)
                            else os.path.join(context.run_dir, path),
                            "path": path, "sha256": frame.get("sha256"),
                            "viewport": viewports.get(frame.get("project"))})
        if not entries:
            return self._blocked("the playability-report lists no frames: there is nothing to "
                                 "judge. Run playability on the production build first.")
        if settings.kind == "none":
            return self._blocked(
                "visual QA needs a judge: factory.visualqa.judge.kind is `none`. Configure a "
                "command judge able to read images (docs/visual-qa-module.md) and resume. "
                "Nothing was judged; this is not a pass.")

        workdir = os.path.join(context.run_dir, "visual-qa",
                               f"{self.id}-{context.visit}-{context.attempt}")
        shutil.rmtree(workdir, ignore_errors=True)
        os.makedirs(workdir)
        try:
            frames_dir, frames = stage_frames(entries, workdir)
        except FrameError as exc:
            if exc.kind == "missing":
                return self._blocked(f"{exc}; the playability evidence is gone - play the "
                                     f"build again")
            return StepResult.failed(str(exc), retryable=False)
        try:
            guarded = isolation.guarded_paths(context.config)
        except ValueError as exc:
            return StepResult.failed(str(exc), retryable=False)

        if settings.kind == "baseline":
            outcome = self._baseline(settings, rubric, frames, workdir, context)
        else:
            outcome = run_judge(settings, rubric, workdir, frames, frames_dir,
                                title_id=title_id, commit=commit, design=design,
                                manifest=manifest, quality=quality, guarded=guarded,
                                logger=context.logger, stem=self.id)
        if outcome.failure is not None:
            failure = outcome.failure
            context.logger.error("visual-qa judge failed", code=failure["code"])
            return StepResult("FAILED", retryable=failure["retryable"],
                              error=f"{failure['code']}: {failure['message']} "
                                    f"(see {workdir})",
                              data={"output_tail": failure.get("output_tail")})

        verdict = outcome.verdict
        identity = (design.get("build_spec") or {}).get("visual_identity") or {}
        status, failed, routes = decide(verdict, rubric,
                                        primitive_style=bool(identity.get("primitive_style")))
        report = self._report(verdict=status, frames=frames, scores=verdict["scores"],
                              score_reasons=verdict.get("score_reasons"),
                              findings=verdict["findings"], failed=failed, routes=routes,
                              notes=verdict.get("notes"), runs=len(outcome.runs),
                              states=report_states(rubric, frames, verdict["states"]),
                              look={"verdict": verdict["look"],
                                    "reason": verdict.get("look_reason")})
        if status == "PASS":
            return StepResult.success([report], message=(
                f"visual QA passed {commit[:12]}: {len(frames)} frames, lowest score "
                f"{min(verdict['scores'].values())}"))
        blockers = [f for f in verdict["findings"] if f["severity"] == "blocker"]
        below = [x.split(":", 1)[1] for x in failed if x.startswith("score:")]
        summary = "; ".join(f"{f['id']} ({f['route']}): {f['summary']}" for f in blockers[:5])
        context.logger.error("visual QA failed", failed=failed, route=routes[0])
        return StepResult("FAILED", route=routes[0], artifacts=[report], retryable=False,
                          error=(f"visual QA failed {commit[:12]} - {len(blockers)} blocker(s)"
                                 + (f", below the bar: {', '.join(below)}" if below else "")
                                 + (f" - {summary}" if summary else "")))

    def _baseline(self, settings, rubric, frames, workdir, context):
        """The baseline judge (baseline.py): no agent, the same verdict shape. Every
        comparison is kept beside the staged frames, <workdir>/baseline.json."""
        outcome = Outcome()
        try:
            outcome.verdict, comparisons = baseline.judge(
                rubric, frames, settings.baseline_dir, settings.min_similarity)
        except baseline.BaselineError as exc:
            outcome.failure = {"code": "baseline-unusable", "message": str(exc),
                               "retryable": False}
            return outcome
        with open(os.path.join(workdir, "baseline.json"), "w", encoding="utf-8") as handle:
            json.dump({"baseline_dir": settings.baseline_dir,
                       "min_similarity": settings.min_similarity or baseline.MIN_SIMILARITY,
                       "comparisons": comparisons}, handle, indent=2)
            handle.write("\n")
        outcome.runs.append({"kind": "baseline", "compared": len(
            [c for c in comparisons if c["score"] is not None])})
        context.logger.info("visual-qa baseline judged", compared=outcome.runs[0]["compared"],
                            lowest=min((c["score"] for c in comparisons
                                        if c["score"] is not None), default=None))
        return outcome

    # -- the report ---------------------------------------------------------------------

    def _blocked(self, reason):
        report = self._report(verdict="BLOCKED", frames=[], blocked_reason=reason)
        self._ctx["context"].logger.warning("visual-qa blocked", reason=reason)
        return StepResult("BLOCKED", artifacts=[report], message=reason)

    def _report(self, *, verdict, frames, scores=None, findings=None, failed=(), routes=(),
                notes=None, runs=0, blocked_reason=None, states=None, look=None,
                score_reasons=None):
        ctx = self._ctx
        context, settings, rubric = ctx["context"], ctx["settings"], ctx["rubric"]
        now = self.clock()
        judge = {"kind": settings.kind}
        if settings.kind == "command":
            judge.update(argv0=os.path.basename(settings.argv[0]),
                         model=_model_of(settings.argv), verdict_from=settings.verdict_from)
        elif settings.kind == "baseline":
            judge.update(model=None, baseline_dir=paths.display(settings.baseline_dir),
                         min_similarity=settings.min_similarity or baseline.MIN_SIMILARITY)
        types = REQUIRED_INPUTS + tuple(t for t in OPTIONAL_INPUTS if t in ctx["inputs"])
        report = {
            "provenance": provenance.build(
                "visual-qa-report",
                artifact_id=provenance.artifact_id("visual-qa-report", ctx["title_id"], now,
                                                   getattr(context, "execution", 1)),
                produced_by=provenance.producer(
                    ROLE, "ai" if settings.kind == "command" and runs else "automation"),
                produced_at=now,
                inputs=provenance.pin_inputs(ctx["inputs"], types),
                title_id=ctx["title_id"]),
            "title_id": ctx["title_id"],
            "commit": ctx["commit"],
            "measurement_class": "automation-agent",
            "judge": judge,
            "rubric": {"path": paths.display(rubric["path"]),
                       "version": str(rubric.get("version")), "sha256": rubric["sha256"],
                       "pass_bar": rubric["pass_bar"]},
            "judge_runs": runs,
            "frames": [{"id": f["key"], "project": f["project"], "state": f["state"],
                        "path": f["path"], "sha256": f["sha256"]} for f in frames],
            "scores": dict(scores or {}),
            "score_reasons": ({k: v for k, v in score_reasons.items() if isinstance(v, str)}
                              if isinstance(score_reasons, dict) and score_reasons else None),
            "findings": [dict(f) for f in findings or []],
            "failed": list(failed),
            "routes": list(routes),
            "blocked_reason": blocked_reason,
            "states": list(states or []),
            "look": look,
            "notes": notes,
            "verdict": verdict,
        }
        if report["score_reasons"] is None:
            del report["score_reasons"]
        return ArtifactOutput("visual-qa-report", provenance.seal(report), metadata={
            "verdict": verdict, "failed": len(failed), "commit": ctx["commit"],
            "route": routes[0] if routes else None, "judge_runs": runs,
            "max_judge_runs": MAX_JUDGE_RUNS})

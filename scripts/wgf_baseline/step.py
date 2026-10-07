"""The accepted-baseline steps: the build a person accepted, pinned into the run, and every
later build of the same game held to it.

    accepted-baseline      title-strategy [+ game-design]
                             -> the newest G4 `pass` a person gave for the title (or the
                                commit factory.baseline.accepted names), its reports copied
                                into the run with their frames, its metrics read
                             -> accepted-baseline (status present | none | unmeasured)
                           SUCCESS always: `none` says why there is no baseline; `unmeasured`
                           says what could not be resolved, and the regression step blocks
                           on it.

    baseline-regression    accepted-baseline, prototype-report, scaffold-record, game-design
                           [+ playability-report, visual-qa-report, production-quality-report,
                            content-sufficiency-report, baseline-regression-report]
                             -> replacement: how much of the accepted build the candidate
                                commit replaced (git); above the maximum, a person decides
                             -> (phase production) metrics: the same bot's measures of both
                                builds compared with core/reference/accepted-baseline.yaml's
                                tolerances; the paired judgement of the same states; the
                                playtest notes a person filed against a build
                             -> baseline-regression-report

    SKIPPED      no accepted baseline                                          SUCCESS
    PASS         nothing replaced without approval, every metric within tolerance, no
                 paired dimension worse, no open blocking playtest finding     SUCCESS
    WAITING      the candidate replaced accepted work above the maximum and no person has
                 decided: `wgf decide <run> approve | restore`. Only a person's answer is
                 taken; nothing approves it on a timeout.                     WAITING_FOR_HUMAN
    restore      a person chose to restore the accepted work                  FAILED, route
                 `restore` (the brief then says: extend the accepted build)
    FAIL         a metric beyond tolerance or unmeasured on the candidate, a paired dimension
                 worse, an open blocking playtest finding                     FAILED, route
                 of the findings: `assets` before `develop`, not retryable
    BLOCKED      the baseline exists but cannot be measured (its reports or commit missing),
                 the checkout cannot answer, the paired judgement cannot be made (no judge,
                 too few pairs, a judge that wrote where it may only read), a pinned
                 reference edited after the start, playtest notes that do not hash

It never edits the checkout: it reads git objects and the reports the run holds.
"""

import datetime
import json
import os
import shutil

from wgflib import checkout, isolation, paths, provenance
from wgflib.workflow import ArtifactOutput, StepResult, WorkflowStep
from wgflib.workflow import references as pinned_references
from wgflib.yamllite import YamlError, load as load_yaml

from . import locate, metrics, paired, playtest, replacement

__all__ = ["AcceptedBaselineStep", "BaselineRegressionStep", "REFERENCE", "load_reference",
           "ROUTE_ORDER"]

REFERENCE = "core/reference/accepted-baseline.yaml"
ROUTE_ORDER = ("assets", "develop")
PRODUCER = "baseline-regression-report"


def _utc_now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_reference(context):
    """(spec, record) from the run's pinned copy (the live file for a run that pinned none).
    Raises PinError or YamlError."""
    text, digest, pinned = pinned_references.read(
        REFERENCE, getattr(context, "environment", None), getattr(context, "run_dir", None))
    spec = load_yaml(text) or {}
    if not isinstance(spec, dict) or not spec.get("version"):
        raise YamlError(f"{REFERENCE} has no version")
    return spec, {"path": REFERENCE, "version": str(spec["version"]), "sha256": digest,
                  "pinned": bool(pinned)}


def _section(config, name):
    if config is None:
        return {}
    if hasattr(config, "section"):
        return config.section(name) or {}
    return (config.get(name) if isinstance(config, dict) else None) or {}


def _load_json(path):
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _sha256(path):
    import hashlib
    with open(path, "rb") as handle:
        return "sha256:" + hashlib.sha256(handle.read()).hexdigest()


def _same(a, b):
    return bool(a and b) and (a.startswith(b) or b.startswith(a)) and min(len(a), len(b)) >= 7


class AcceptedBaselineStep(WorkflowStep):
    type = "accepted-baseline"
    clock = staticmethod(_utc_now)

    def execute(self, inputs, context):
        strategy = inputs.load("title-strategy") if "title-strategy" in inputs else {}
        design = inputs.load("game-design") if "game-design" in inputs else {}
        title_id = ((strategy or {}).get("title_id") or (design or {}).get("title_id")
                    or getattr(context, "project_id", None))
        try:
            spec, record = load_reference(context)
        except (pinned_references.PinError, YamlError, OSError) as exc:
            return StepResult("BLOCKED", message=(
                f"{REFERENCE} as the run pinned it cannot be read ({exc}): no accepted build "
                "is held to a reference edited after the start"))
        run_dir = getattr(context, "run_dir", None)
        store = os.path.dirname(run_dir) if run_dir else None
        config = _section(getattr(context, "config", None), "baseline")
        try:
            found = locate.find(title_id, store=store, rules=spec.get("locate") or {},
                                exclude_run=getattr(context, "run_id", None),
                                titles_dir=paths.TITLES, config=config)
        except locate.LocateError as exc:
            found = {"commit": None, "source": "config", "decision": None, "reports": {},
                     "problems": [str(exc)], "run_id": None, "run_dir": None,
                     "shipped_commit": None}
        now = self.clock()
        artifact = {
            "provenance": provenance.build(
                "accepted-baseline",
                artifact_id=provenance.artifact_id("accepted-baseline", title_id or "run",
                                                   now, getattr(context, "execution", 1)),
                produced_by=provenance.producer("qa"), produced_at=now,
                inputs=provenance.pin_inputs(inputs), title_id=title_id),
            "title_id": title_id,
            "reference": record,
            "status": "none",
            "reason": None,
            "accepted": None,
            "reports": [],
            "frames": [],
            "metrics": {},
            "problems": [],
        }
        if found is None:
            artifact["reason"] = (f"no G4 `pass` a person gave for {title_id} in the run store "
                                  f"or workspace/titles/{title_id}/decisions, and no "
                                  "factory.baseline.accepted: nothing was accepted yet")
            context.logger.info("no accepted baseline", title=title_id)
            return StepResult.success([ArtifactOutput("accepted-baseline",
                                                      provenance.seal(artifact))],
                                      message=artifact["reason"])
        workdir = os.path.join(run_dir, "accepted-baseline",
                               f"{self.id}-{context.visit}-{context.attempt}")
        shutil.rmtree(workdir, ignore_errors=True)
        os.makedirs(workdir)
        problems = list(found.get("problems") or [])
        loaded = {}
        for kind, entry in sorted((found.get("reports") or {}).items()):
            content = _load_json(entry["path"])
            if content is None:
                problems.append(f"{kind} at {entry['path']} cannot be read")
                continue
            target = os.path.join(workdir, "reports", kind + ".json")
            os.makedirs(os.path.dirname(target), exist_ok=True)
            shutil.copyfile(entry["path"], target)
            loaded[kind] = content
            artifact["reports"].append({
                "artifact_type": kind, "artifact_id": entry.get("artifact_id"),
                "content_hash": entry.get("content_hash"), "commit": entry.get("commit"),
                "pinned_by": entry.get("pinned_by"),
                "path": os.path.relpath(target, run_dir).replace(os.sep, "/")})
        source_run = found.get("run_dir")
        frames_from = (spec.get("locate") or {}).get("frames_from") or "playability-report"
        for frame in (loaded.get(frames_from) or {}).get("frames") or []:
            if not isinstance(frame, dict) or not frame.get("path"):
                continue
            path = frame["path"]
            source = path if os.path.isabs(path) else (
                os.path.join(source_run, path) if source_run else None)
            if not source or not os.path.isfile(source):
                problems.append(f"frame {frame.get('project')}/{frame.get('id')} is not at "
                                f"{source}")
                continue
            digest = _sha256(source)
            if frame.get("sha256") and frame["sha256"] != digest:
                problems.append(f"frame {frame.get('project')}/{frame.get('id')} is not the "
                                "frame its report recorded")
                continue
            target = os.path.join(workdir, "frames", str(frame.get("project")),
                                  str(frame.get("id")) + ".png")
            os.makedirs(os.path.dirname(target), exist_ok=True)
            shutil.copyfile(source, target)
            artifact["frames"].append({
                "project": frame.get("project"), "id": frame.get("id"), "sha256": digest,
                "path": os.path.relpath(target, run_dir).replace(os.sep, "/")})
        extracted = metrics.extract(spec, loaded)
        artifact["metrics"] = {k: dict(v) for k, v in sorted(extracted.items())}
        decision = found.get("decision")
        artifact["accepted"] = {
            "commit": found.get("commit"), "shipped_commit": found.get("shipped_commit"),
            "source": found.get("source"), "run_id": found.get("run_id"),
            "decision": ({k: decision.get(k) for k in ("artifact_id", "content_hash",
                                                       "decided_at", "decision", "decided_by")}
                         if decision else None)}
        if not found.get("commit"):
            problems.append("the accepted commit could not be resolved from the decision's "
                            "pinned prototype-report")
        if frames_from not in loaded:
            problems.append(f"no {frames_from} of the accepted build: its play cannot be "
                            "compared")
        artifact["problems"] = problems
        artifact["status"] = "unmeasured" if problems and (
            not found.get("commit") or frames_from not in loaded) else "present"
        artifact["reason"] = (
            f"accepted at G4 ({(decision or {}).get('artifact_id')}) on "
            f"{(decision or {}).get('decided_at')}" if decision else
            "named by factory.baseline.accepted")
        message = (f"accepted build {str(found.get('commit'))[:12]} ({artifact['status']}): "
                   f"{len(artifact['reports'])} report(s), {len(artifact['frames'])} frame(s), "
                   f"{len(artifact['metrics'])} metric(s)")
        if problems:
            context.logger.warning("accepted baseline problems", problems=problems[:6])
        return StepResult.success([ArtifactOutput("accepted-baseline",
                                                  provenance.seal(artifact),
                                                  metadata={"status": artifact["status"],
                                                            "commit": found.get("commit")})],
                                  message=message)


def _finding(routing, *, check, dimension_word, severity, summary, route, measured=None,
             bar=None, evidence=(), change=None, acceptance=None, design_3d=False,
             commit=None):
    """A quality finding (core/artifacts/shared/quality-finding.schema.json `finding`)."""
    from wgf_triage.findings import finding_id
    dimension = routing.resolve_word(dimension_word, "3d" if design_3d else "2d") \
        or routing.default_dimension
    owner = routing.owner(dimension)
    finding = {
        "id": finding_id(PRODUCER, check),
        "dimension": dimension,
        "severity": severity if severity in ("blocker", "major", "minor") else "major",
        "source": {"producer": PRODUCER, "step": "baseline-regression", "check": check,
                   "project": None, "artifact_id": None, "content_hash": None},
        "summary": summary[:600],
        "evidence_refs": [e for e in evidence if isinstance(e, str) and e],
        "owner": owner,
        "task": {"change": change or f"Bring `{check}` back to the accepted build: {summary}"
                 [:600],
                 "acceptance": [acceptance or f"baseline-regression measures the next build "
                                f"against the accepted one and `{check}` passes."]},
        "route": route if route in ("develop", "assets", "design") else
        routing.route_of(owner),
        "build": {"commit": commit, "digest": None},
    }
    if measured is not None:
        finding["measured"] = measured
    if bar is not None:
        finding["bar"] = bar
    return finding


class BaselineRegressionStep(WorkflowStep):
    type = "baseline-regression"
    clock = staticmethod(_utc_now)
    git_factory = staticmethod(replacement.Git)    # seam for tests

    # -- helpers -------------------------------------------------------------------------

    def _load(self, inputs, kind):
        return inputs.load(kind) if kind in inputs else None

    def _report(self, context, inputs, title_id, commit, baseline, record, **fields):
        now = self.clock()
        accepted = (baseline or {}).get("accepted") or {}
        report = {
            "provenance": provenance.build(
                PRODUCER,
                artifact_id=provenance.artifact_id(PRODUCER, title_id or "run", now,
                                                   getattr(context, "execution", 1)),
                produced_by=provenance.producer("qa"), produced_at=now,
                inputs=provenance.pin_inputs(inputs), title_id=title_id),
            "title_id": title_id,
            "commit": commit,
            "phase": self.params.get("phase") or "production",
            "baseline": {"status": (baseline or {}).get("status") or "none",
                         "commit": accepted.get("commit"),
                         "artifact_id": ((baseline or {}).get("provenance") or {})
                         .get("artifact_id"),
                         "decision": (accepted.get("decision") or {}).get("artifact_id")},
            "reference": record,
            "replacement": None,
            "metrics": [],
            "paired": None,
            "playtest": [],
            "checks": [],
            "findings": [],
            "failed": [],
            "routes": [],
            "skipped_reason": None,
            "blocked_reason": None,
            "verdict": None,
        }
        report.update(fields)
        return provenance.seal(report)

    def _blocked(self, context, inputs, title_id, commit, baseline, record, reason, **fields):
        report = self._report(context, inputs, title_id, commit, baseline, record,
                              blocked_reason=reason, verdict="BLOCKED", **fields)
        context.logger.warning("baseline-regression blocked", reason=reason)
        return StepResult("BLOCKED", artifacts=[ArtifactOutput(PRODUCER, report, metadata={
            "verdict": "BLOCKED", "commit": commit})], message=reason)

    @staticmethod
    def _approval(previous, accepted_commit):
        """A person's approval of replacing `accepted_commit`, carried from the run's
        previous baseline-regression-report, or None."""
        decision = ((previous or {}).get("replacement") or {}).get("decision") or {}
        if decision.get("choice") == "approve" and decision.get("decided_by") == "human" \
                and _same(decision.get("accepted_commit"), accepted_commit):
            return decision
        return None

    # -- execute -------------------------------------------------------------------------

    def execute(self, inputs, context):
        baseline = self._load(inputs, "accepted-baseline")
        proto = self._load(inputs, "prototype-report") or {}
        design = self._load(inputs, "game-design") or {}
        title_id = (proto.get("title_id") or design.get("title_id")
                    or (baseline or {}).get("title_id") or getattr(context, "project_id", None))
        commit = (proto.get("build_ref") or {}).get("commit_sha")
        try:
            spec, record = load_reference(context)
        except (pinned_references.PinError, YamlError, OSError) as exc:
            return StepResult("BLOCKED", message=(
                f"{REFERENCE} as the run pinned it cannot be read ({exc})"))
        status = (baseline or {}).get("status") or "none"
        if status == "none":
            reason = ((baseline or {}).get("reason") or
                      "the run holds no accepted-baseline: nothing was accepted to compare with")
            report = self._report(context, inputs, title_id, commit, baseline, record,
                                  skipped_reason=reason, verdict="SKIPPED")
            return StepResult.success([ArtifactOutput(PRODUCER, report, metadata={
                "verdict": "SKIPPED", "commit": commit})], message=f"skipped: {reason}")
        if status != "present":
            return self._blocked(
                context, inputs, title_id, commit, baseline, record,
                "an accepted build exists but cannot be measured: "
                + "; ".join((baseline or {}).get("problems") or ["unresolved"])
                + ". Name it in factory.baseline.accepted (commit, run) or restore its run "
                  "store; a baseline that exists is never skipped.")
        if not commit:
            return StepResult.waiting_for_input(
                "baseline-regression needs the prototype-report of the build to compare")
        accepted_commit = baseline["accepted"]["commit"]
        try:
            from wgf_triage.routing import Routing
            routing = Routing.load()
        except Exception as exc:  # noqa: BLE001 - unusable routing data names no owner
            return StepResult.failed(f"specialist routing data is unusable: {exc}",
                                     retryable=False)
        design_3d = ((design.get("engine") or {}).get("dimension") == "3d")
        previous = self._load(inputs, PRODUCER)

        # 1. replacement, from git
        scaffold = self._load(inputs, "scaffold-record")
        try:
            root, _source = checkout.locate(context.config, scaffold, "develop", self.params,
                                            name=title_id)
            measured = replacement.measure(self.git_factory(root), accepted_commit, commit,
                                           spec.get("replacement") or {})
        except (checkout.CheckoutError, replacement.MeasureError) as exc:
            return self._blocked(context, inputs, title_id, commit, baseline, record,
                                 f"how much of the accepted build {accepted_commit[:12]} the "
                                 f"candidate {commit[:12]} replaced cannot be measured: {exc}")
        rules = spec.get("replacement") or {}
        approval = self._approval(previous, accepted_commit)
        decision = getattr(context, "decision", None)
        exceeded = measured.get("exceeded") or []
        replaced = dict(measured, status="PASS", decision=approval)
        findings, checks = [], []
        shares = ", ".join(f"{q} {measured.get(q)} (maximum {measured['maximum'].get(q)})"
                           for q in exceeded)
        if exceeded and approval is None:
            choices = list(rules.get("choices") or ["approve", "restore"])
            choice = (decision or {}).get("decision") if decision else None
            if choice in choices and decision.get("decided_by") == "human":
                answer = {"choice": choice, "decided_by": "human",
                          "decided_at": decision.get("decided_at") or context.now,
                          "note": decision.get("note"), "accepted_commit": accepted_commit,
                          "measured_on": commit,
                          "measured": {q: measured.get(q) for q in replacement.QUANTITIES}}
                replaced["decision"] = answer
                if choice == "approve":
                    approval = answer
                else:
                    replaced["status"] = "FAIL"
                    finding = _finding(
                        routing, check="replacement", dimension_word="gameplay",
                        severity="blocker", route="develop", commit=commit,
                        summary=(f"the candidate replaced the accepted build "
                                 f"{accepted_commit[:12]} ({shares}); a person chose to "
                                 "restore it"),
                        measured={q: measured.get(q) for q in replacement.QUANTITIES},
                        bar=measured.get("maximum"),
                        change=("Restore what the accepted build shipped - its units, its "
                                "environment and its tuning - and make this visit's changes "
                                "as extensions of it: "
                                + ", ".join(f["path"] for f in
                                            measured.get("rewritten_files")[:8])
                                + (f"; units {', '.join((measured.get('units_removed') + measured.get('units_changed'))[:8])}"
                                   if measured.get("units_removed") or
                                   measured.get("units_changed") else "")),
                        acceptance=("baseline-regression measures the next build at or below "
                                    "the replacement maximum of the accepted build."))
                    report = self._report(
                        context, inputs, title_id, commit, baseline, record,
                        replacement=replaced, findings=[finding],
                        checks=[{"id": "baseline.replacement", "status": "FAIL",
                                 "summary": finding["summary"]}],
                        failed=["baseline.replacement"], routes=["restore"], verdict="FAIL")
                    return StepResult("FAILED", route="restore", artifacts=[ArtifactOutput(
                        PRODUCER, report, metadata={"verdict": "FAIL", "commit": commit,
                                                    "routes": ["restore"]})],
                        retryable=False,
                        error=f"restore at {self.id}: a person chose to restore the accepted "
                              f"build {accepted_commit[:12]} ({shares})")
            else:
                why = ("" if not decision else
                       f" ({decision.get('decision')!r} by {decision.get('decided_by')} is not "
                       "a person's answer among the choices)")
                return StepResult.waiting_for_human(
                    f"the candidate {commit[:12]} replaced the build a person accepted "
                    f"({accepted_commit[:12]}): {shares}. Approve the replacement, or restore "
                    f"the accepted build and extend it: wgf decide {context.run_id} "
                    f"{' | '.join(choices)} [--note TEXT]. Only a person decides this; it "
                    f"never approves on a timeout{why}.",
                    choices=choices, accepted_commit=accepted_commit, candidate_commit=commit,
                    exceeded=exceeded)
        checks.append({"id": "baseline.replacement",
                       "status": "PASS",
                       "summary": ("within the replacement maximum" if not exceeded else
                                   f"replacement approved by a person on "
                                   f"{(approval or {}).get('decided_at')}: {shares}")})
        if (self.params.get("phase") or "production") == "greybox":
            report = self._report(context, inputs, title_id, commit, baseline, record,
                                  replacement=replaced, checks=checks, verdict="PASS")
            return StepResult.success([ArtifactOutput(PRODUCER, report, metadata={
                "verdict": "PASS", "commit": commit})],
                message=f"{commit[:12]} keeps the accepted build {accepted_commit[:12]}"
                        + (" (replacement approved)" if exceeded else ""))

        # 2. metrics: the same bot's measures of both builds
        reports = {}
        stale = []
        for kind in ("playability-report", "visual-qa-report", "production-quality-report",
                     "content-sufficiency-report"):
            report = self._load(inputs, kind)
            if report is None:
                continue
            if not _same(report.get("commit"), commit):
                stale.append(f"{kind} describes {str(report.get('commit'))[:12]}")
                continue
            reports[kind] = report
        if "playability-report" not in reports:
            return StepResult.waiting_for_input(
                f"baseline-regression needs the playability-report of {commit[:12]}"
                + (f" ({'; '.join(stale)})" if stale else ""))
        candidate = metrics.extract(spec, reports)
        accepted_values = {k: metrics.ProjectValues(v)
                           for k, v in (baseline.get("metrics") or {}).items()}
        results = metrics.compare(spec, accepted_values, candidate,
                                  approved=approval is not None)
        failing = [r for r in results if r["status"] in ("FAIL", "UNMEASURED")]
        checks.append({"id": "baseline.metrics",
                       "status": "FAIL" if failing else "PASS",
                       "summary": (f"{len(failing)} of "
                                   f"{sum(r['status'] != 'SKIPPED' for r in results)} metric "
                                   "comparison(s) beyond tolerance or unmeasured"
                                   if failing else "every metric within tolerance")})
        rubric = self._rubric(context)
        dims = (rubric or {}).get("dimensions") or {}
        for result in failing:
            word, route = result["dimension"], result.get("route") or "develop"
            key = result["id"][len(result["metric"]) + 1:]
            if result.get("dimension_by_key") and key:
                # a rubric dimension's score: its owner and route are the rubric's
                word = self._rubric_word(key)
                route = (dims.get(key) or {}).get("route") or route
            findings.append(_finding(
                routing, check=f"metric:{result['id']}@{result['project']}",
                dimension_word=word, severity=(
                    result["severity"] if result["status"] == "FAIL" else "major"),
                route=route, commit=commit,
                summary=result["summary"],
                measured={"accepted": result.get("accepted"),
                          "candidate": result.get("candidate"), "delta": result.get("delta")},
                bar={k: result[k] for k in ("compare", "band", "max_delta", "max_drop")
                     if k in result},
                design_3d=design_3d))

        # 3. the paired judgement
        accepted_frames = [dict(f, source=os.path.join(context.run_dir, f["path"]))
                           for f in baseline.get("frames") or []]
        play = reports["playability-report"]
        candidate_frames = []
        for frame in play.get("frames") or []:
            path = frame.get("path") or ""
            candidate_frames.append({"project": frame.get("project"), "id": frame.get("id"),
                                     "sha256": frame.get("sha256"), "path": path,
                                     "source": path if os.path.isabs(path)
                                     else os.path.join(context.run_dir, path)})
        workdir = os.path.join(context.run_dir, "baseline-regression",
                               f"{self.id}-{context.visit}-{context.attempt}")
        shutil.rmtree(workdir, ignore_errors=True)
        os.makedirs(workdir)
        try:
            from wgf_visualqa.settings import Settings, SettingsError
            settings = Settings.resolve(context.config, {})
        except SettingsError as exc:
            return StepResult.failed(str(exc), retryable=False)
        try:
            frames_dir, staged = paired.stage(paired.pairs(spec, accepted_frames,
                                                           candidate_frames), workdir)
            guarded = isolation.guarded_paths(context.config)
        except (paired.PairError, ValueError) as exc:
            return self._blocked(context, inputs, title_id, commit, baseline, record,
                                 f"the paired frames cannot be staged: {exc}",
                                 replacement=replaced, metrics=results, checks=checks)
        judged = paired.judge(settings, rubric, spec, staged, frames_dir, workdir,
                              title_id=title_id, accepted_commit=accepted_commit,
                              candidate_commit=commit, guarded=guarded,
                              logger=context.logger)
        if judged["status"] in ("UNMEASURED", "BLOCKED"):
            return self._blocked(
                context, inputs, title_id, commit, baseline, record,
                f"the paired judgement of the accepted and the candidate frames was not made: "
                f"{judged.get('problem')}. Unjudged is never a pass.",
                replacement=replaced, metrics=results, paired=judged, checks=checks)
        worse = {d: v for d, v in judged["dimensions"].items() if v["verdict"] == "worse"}
        checks.append({"id": "baseline.paired", "status": "FAIL" if worse else "PASS",
                       "summary": (f"worse than the accepted build on {', '.join(worse)}"
                                   if worse else "no rubric dimension worse than the accepted "
                                                 "build")})
        severity = (spec.get("paired") or {}).get("severity") or "blocker"
        for dim, verdict in sorted(worse.items()):
            route = (dims.get(dim) or {}).get("route") or "develop"
            findings.append(_finding(
                routing, check=f"paired:{dim}", dimension_word=self._rubric_word(dim),
                severity=severity, route=route, commit=commit, design_3d=design_3d,
                summary=(f"the paired judge found the candidate worse than the accepted build "
                         f"on {dim}: {verdict['reason']}"),
                measured={"verdict": "worse", "reason": verdict["reason"]},
                bar="same or better than the accepted build",
                evidence=[p["candidate"]["path"] for p in judged["pairs"]][:6],
                acceptance=(f"the paired judge, shown the accepted and the next build's frames, "
                            f"answers same or better on {dim}.")))

        # 4. a person's playtest notes
        try:
            notes = playtest.findings(context.run_dir, spec.get("playtest") or {}, commit,
                                      results)
        except playtest.PlaytestError as exc:
            return self._blocked(context, inputs, title_id, commit, baseline, record, str(exc),
                                 replacement=replaced, metrics=results, paired=judged,
                                 checks=checks)
        open_notes = [n for n in notes if n["blocking"]]
        checks.append({"id": "baseline.playtest", "status": "FAIL" if open_notes else "PASS",
                       "summary": (f"{len(open_notes)} blocking playtest finding(s) open"
                                   if open_notes else
                                   f"{len(notes)} playtest finding(s), none open and blocking")})
        for note in open_notes:
            request = note["request"]
            word = request.get("dimension") or "gameplay"
            finding = _finding(
                routing, check=note["id"].split(":", 1)[1], dimension_word=word,
                severity=note["severity"], route=request.get("route") or None, commit=commit,
                summary=f"playtest: {request.get('summary')}", design_3d=design_3d,
                measured=request.get("measured"), bar=request.get("bar"),
                evidence=request.get("evidence_refs") or (),
                change=(request.get("task") or {}).get("change"),
                acceptance="; ".join((request.get("task") or {}).get("acceptance") or [])
                or None)
            finding["id"] = note["id"]
            findings.append(finding)

        failed = [c["id"] for c in checks if c["status"] == "FAIL"]
        routes = [r for r in ROUTE_ORDER if any(f["route"] == r for f in findings)]
        if failed and not routes:
            routes = ["develop"]
        verdict = "FAIL" if failed else "PASS"
        report = self._report(
            context, inputs, title_id, commit, baseline, record, replacement=replaced,
            metrics=results, paired=judged,
            playtest=[dict({k: n[k] for k in ("id", "severity", "status", "blocking", "filed",
                                              "measures", "closed_by")},
                           summary=n["request"].get("summary")) for n in notes],
            checks=checks, findings=findings, failed=failed,
            routes=routes if failed else [], verdict=verdict)
        output = ArtifactOutput(PRODUCER, report, metadata={
            "verdict": verdict, "commit": commit, "routes": report["routes"],
            "failed": failed})
        if verdict == "FAIL":
            context.logger.error("worse than the accepted build", failed=failed,
                                 route=routes[0])
            return StepResult("FAILED", route=routes[0], artifacts=[output], retryable=False,
                              error=(f"ACCEPTED-BASELINE REGRESSION: {commit[:12]} against "
                                     f"{accepted_commit[:12]}: " + "; ".join(
                                         f["summary"] for f in findings[:5])))
        return StepResult.success([output], message=(
            f"{commit[:12]} holds the accepted build {accepted_commit[:12]}: "
            f"{sum(r['status'] == 'PASS' for r in results)} metric(s) within tolerance, "
            f"paired judge {judged.get('judge')}: no dimension worse"))

    @staticmethod
    def _rubric_word(dim):
        """The specialist-routing word of a visual-qa rubric dimension (the visual-qa-report
        producer table, core/reference/specialist-routing.yaml)."""
        try:
            from wgf_triage.routing import Routing
            table = Routing.load().producer("visual-qa-report") or {}
        except Exception:  # noqa: BLE001
            table = {}
        return (table.get("scores") or {}).get(dim) or table.get("default") or "art"

    @staticmethod
    def _rubric(context):
        from wgf_visualqa.rubric import load_rubric
        from wgf_visualqa.step import RUBRIC
        run_dir = getattr(context, "run_dir", None)
        try:
            _text, _digest, pinned = pinned_references.read(
                RUBRIC, getattr(context, "environment", None), run_dir)
        except pinned_references.PinError:
            pinned = False
        if pinned:
            return load_rubric(os.path.join(run_dir, pinned_references.DIRECTORY,
                                            *RUBRIC.split("/")))
        return load_rubric()


def register(registry):
    registry.register(AcceptedBaselineStep.type, AcceptedBaselineStep)
    registry.register(BaselineRegressionStep.type, BaselineRegressionStep)
    return registry

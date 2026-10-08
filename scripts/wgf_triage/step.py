"""The `triage` step: what sent the build back, as specialist work, routed by owner.

    inputs   game-design (its engine.dimension resolves 2D/3D words), prototype-report (the
             build), the gate reports (playability-report, production-quality-report,
             visual-qa-report, review-report, qa-report, listing-validation-report), the
             decision-record (G4's iterate, with any typed findings), and this step's own
             previous triage-report
    output   triage-report

    1. Which build: the newest prototype-report. A gate report produced after it (run-local
       `seq`) measured it; an older one measured an earlier build and says nothing now.
    2. Fresh or continued. When the previous triage-report still has `pending` groups and no
       gate has measured anything since it (no gate report is newer), the run is inside a
       chain of specialist visits on one build (develop's `next-specialist`, or the assets
       pass a triage routed): the next pending group is routed. Otherwise the current
       build's failing reports, and the G4 decision that sent it back, are normalized afresh
       (findings.py). Findings routed `assets` by a report the assets step has run after are
       not routed again: that work is done, and develop integrates it. They are recorded in
       the ledger as handed to the assets step, implemented by its asset-manifest, so the
       next measurement verifies them like any other.
    3. Grouped by owner, in visit order (routing.py, core/reference/specialist-routing.yaml).
       A group whose label this step's `on:` does not route is held, with why (store copy
       before the listing exists). A `design` group goes first and alone: the others are
       deferred, and the gates measure the rebuilt game again.
    4. The ledger: one entry per specialist develop visit (from the prototype-report's
       `specialist` block), each finding resolved, unresolved or unmeasured by the newest
       report of the producer that raised it.
    5. The run's finding ledger (`lifecycle`, lifecycle.py): every finding detected,
       classified, assigned, implemented, verified, closed - verified and closed only on the
       raising producer's re-measurement of a newer build, and never past a regression. It
       continues from the newest ledger in the run (ledger.previous_lifecycle): the quality
       gate advances it too, on the reports it sees (ledger.remeasure).
    6. Regression knowledge (WS-9). Each finding whose check a lesson of
       core/reference/lessons.yaml names carries it as `guarded_by` - the specialist sees a
       known failure and the test that holds it. From the lessons the run pinned; with the
       run's knowledge-contract, only its applicable rules, each with its level. A finding
       whose rule a person excepted for this run (an active knowledge exception) is
       `excepted`: listed and held with why, never routed - the producer's verdict stands. The lesson candidates specialist visits
       reported (prototype-report `specialist.lesson_candidates`) are carried forward in
       `lesson_candidates` for the quality gate and the person at G4; none is applied here.

Outcomes:

    SUCCESS, route <label>   a group is routed: `design`, `assets`, or a specialist's role id,
                             which the workflow maps to develop
    SUCCESS (no route)       nothing failed: the run's first build continues to develop
    BLOCKED                  findings exist and no route of this step can take any of them;
                             or a typed-findings file a G4 decision names is missing, altered
                             or not quality findings
    FAILED (not retryable)   the routing data is inconsistent

It changes nothing outside the run: it reads artifacts and writes one.
"""

import datetime
import hashlib
import json
import os
import re

from wgflib import provenance
from wgflib.jsonschema_lite import Validator
from wgflib.workflow import ArtifactOutput, StepResult, WorkflowStep
from wgflib.workflow.contracts import load_registry

from . import findings as normalizer
from . import ledger as ledgers
from . import lifecycle as lifecycles
from .ledger import GATE_REPORTS
from .routing import Routing, RoutingError

__all__ = ["TriageStep", "GATE_REPORTS", "NEXT_SPECIALIST", "FINDINGS_MARKER",
           "read_typed_findings"]

# The route develop returns after a specialist visit while this triage has pending groups.
NEXT_SPECIALIST = "next-specialist"
# How a G4 decision names its typed findings (`wgf decide <run> iterate --findings FILE`):
# a line of the decision's note, the file stored in the run directory, pinned by hash.
FINDINGS_MARKER = re.compile(r"^findings: (\S+) (sha256:[0-9a-f]{64})\s*$", re.M)
REQUEST_REF = ("https://webgamefactory.dev/schemas/artifacts/shared/"
               "quality-finding.schema.json#/$defs/request")


def _utc_now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


_REGISTRY = {}


def _registry(context=None):
    """{"tiers", "lessons"} as the run pinned them (new-game `pinned_references`), the live
    files for a run that pinned none; cached by content. None when they cannot be read."""
    from wgf_quality import registry
    from wgflib.workflow import references
    from wgflib.yamllite import load as load_yaml
    environment = getattr(context, "environment", None) if context is not None else None
    run_dir = getattr(context, "run_dir", None) if context is not None else None
    texts = {}
    for key, relpath in (("tiers", registry.TIERS_FILE), ("lessons", registry.LESSONS_FILE)):
        text, digest, _pinned = references.read(relpath, environment, run_dir)
        texts[key] = (text, digest)
    cache_key = tuple(d for _t, d in texts.values())
    if cache_key not in _REGISTRY:
        _REGISTRY[cache_key] = {key: load_yaml(text) for key, (text, _d) in texts.items()}
    return _REGISTRY[cache_key]


def _guard(found, context=None, contract=None):
    """Each finding whose source check a lesson names carries the lesson as `guarded_by`
    (wgf_quality.registry.guards), from the lessons and tiers the run pinned. With the run's
    knowledge-contract, only the rules that apply to the run, each with its `level`. Best
    effort: a registry that cannot be read guards nothing, and never stops a triage."""
    try:
        from wgf_quality import registry
        data = _registry(context)
    except Exception:  # noqa: BLE001 - knowledge is advisory here; routing is not
        return
    if not data:
        return
    rules = ({r.get("id"): r for r in contract.get("rules") or () if isinstance(r, dict)}
             if isinstance(contract, dict) else None)
    for finding in found or []:
        if not isinstance(finding, dict):
            continue
        source = finding.get("source") or {}
        guards = registry.guards(data["lessons"], data["tiers"], source.get("producer"),
                                 source.get("check"))
        if rules is not None:
            guards = [dict(g, level=rules[g["lesson"]]["level"]) for g in guards
                      if g.get("lesson") in rules and rules[g["lesson"]].get("level")]
        if guards:
            finding["guarded_by"] = guards


def _excepted(found, inputs, context, now=None):
    """[(finding, reason)]: the findings whose rule a person excepted for this run - an
    exception of the run's knowledge-contract or granted since (compliance.run_exceptions)
    that holds now and whose scope covers the finding's check and viewport. Each is marked
    `excepted`. Nothing without a contract: an exception is of a rule the run applies."""
    contract = _load(inputs, "knowledge-contract")
    if not contract:
        return []
    try:
        from wgf_quality import compliance
        data = _registry(context)
        lessons = data.get("lessons") if data else None
        offered = list(contract.get("exceptions") or ()) + compliance.run_exceptions(context)
        honoured = compliance.honoured_exceptions(offered, contract, lessons,
                                                  now or compliance.now_utc())
    except Exception:  # noqa: BLE001 - an exception that cannot be read excepts nothing
        return []
    out = []
    for finding in found or []:
        source = finding.get("source") or {}
        for guard in finding.get("guarded_by") or ():
            record = next((r for r in honoured if r.get("rule_id") == guard.get("lesson")
                           and compliance.scope_covers(r, guard.get("check"),
                                                       source.get("project"))), None)
            if record is None:
                continue
            who = (record.get("approved_by") or {}).get("identifier")
            finding["excepted"] = {"rule_id": record["rule_id"], "approved_by": who,
                                   "reason": record.get("reason"),
                                   "expires_at": record.get("expires_at")}
            out.append((finding, f"rule {record['rule_id']} is excepted for this run by "
                                 f"{who or 'a person'} until {record.get('expires_at')}: "
                                 f"{record.get('reason')}"))
            break
    return out


def _lesson_candidates(previous, proto):
    """The previous triage-report's lesson candidates and the newest specialist visit's, in
    that order, deduplicated by summary."""
    out, seen = [], set()
    specialist = (proto or {}).get("specialist") if isinstance(proto, dict) else None
    sources = list((previous or {}).get("lesson_candidates") or [])
    if isinstance(specialist, dict):
        sources += [dict(c, role=c.get("role") or specialist.get("role"))
                    for c in specialist.get("lesson_candidates") or [] if isinstance(c, dict)]
    for candidate in sources:
        if not isinstance(candidate, dict):
            continue
        key = " ".join(str(candidate.get("summary") or "").lower().split())
        if key and key not in seen:
            seen.add(key)
            out.append(candidate)
    return out


def _seq(inputs, artifact_type):
    ref = inputs.refs.get(artifact_type)
    return (getattr(ref, "seq", None) or 0) if ref is not None else -1


def _load(inputs, artifact_type):
    if artifact_type not in inputs:
        return None
    content = inputs.load(artifact_type)
    return content if isinstance(content, dict) else None


_build = ledgers.build_of_report


def read_typed_findings(note, run_dir):
    """The typed findings a decision's note names, as a list of quality-finding requests,
    or [] when it names none. Raises ValueError when the file is missing, does not hash to
    what the note pinned, or does not hold quality-finding requests."""
    match = FINDINGS_MARKER.search(note or "")
    if not match:
        return []
    relative, digest = match.group(1), match.group(2)
    if os.path.isabs(relative) or ".." in relative.replace("\\", "/").split("/"):
        raise ValueError(f"the decision names findings at {relative!r}, outside the run")
    path = os.path.join(run_dir or "", *relative.split("/"))
    try:
        with open(path, "rb") as handle:
            raw = handle.read()
    except OSError as exc:
        raise ValueError(f"the decision's findings file {relative} cannot be read: {exc}")
    actual = "sha256:" + hashlib.sha256(raw).hexdigest()
    if actual != digest:
        raise ValueError(f"the decision's findings file {relative} is {actual}, not the "
                         f"{digest} the decision pinned: it was changed after the decision")
    try:
        requests = json.loads(raw.decode("utf-8"))
    except ValueError as exc:
        raise ValueError(f"the decision's findings file {relative} is not JSON: {exc}")
    if isinstance(requests, dict):
        requests = requests.get("findings")
    problems = validate_requests(requests)
    if problems:
        raise ValueError(f"the decision's findings file {relative}: " + "; ".join(problems[:5]))
    return requests


def validate_requests(requests):
    """[] when `requests` is a non-empty list of quality-finding requests."""
    if not isinstance(requests, list) or not requests:
        return ["expected a non-empty list of findings (or {\"findings\": [...]})"]
    validator = Validator({"$ref": REQUEST_REF}, load_registry())
    problems = []
    for index, request in enumerate(requests):
        for error in validator.iter_errors(request):
            problems.append(f"findings[{index}]{getattr(error, 'pointer', '')}: "
                            f"{getattr(error, 'message', error)}")
    return problems


class TriageStep(WorkflowStep):
    type = "triage"
    clock = staticmethod(_utc_now)
    routing_path = None   # seams for tests
    roles_path = None

    def execute(self, inputs, context):
        self._held_excepted = []
        try:
            routing = Routing.load(self.routing_path, self.roles_path)
        except RoutingError as exc:
            return StepResult.failed(f"specialist routing data is inconsistent: {exc}",
                                     retryable=False)
        design = _load(inputs, "game-design") or {}
        dimension_3d = ((design.get("engine") or {}).get("dimension") == "3d")
        proto = _load(inputs, "prototype-report")
        proto_seq = _seq(inputs, "prototype-report")
        previous = _load(inputs, "triage-report")
        previous_seq = _seq(inputs, "triage-report")
        entered = getattr(context, "entered_by", None)
        run_dir = getattr(context, "run_dir", None)
        title_id = ((proto or {}).get("title_id") or design.get("title_id")
                    or getattr(context, "project_id", None) or "untitled")
        commit = ((proto or {}).get("build_ref") or {}).get("commit_sha")

        reports = {kind: _load(inputs, kind) for kind in GATE_REPORTS}
        verification = _load(inputs, "verification-report")

        def build_of(kind):
            return _build(reports.get(kind), commit, verification)

        # every newest report's findings, for the ledger and for fresh triage
        normalized = ledgers.normalize_reports(reports, inputs.refs, routing,
                                               dimension_3d=dimension_3d, commit=commit,
                                               verification=verification)

        decision = _load(inputs, "decision-record")
        decision_seq = _seq(inputs, "decision-record")
        human, problem = [], None
        sent_back = (decision is not None and decision.get("decision") == "iterate"
                     and decision_seq > proto_seq)
        if sent_back:
            try:
                requests = read_typed_findings(decision.get("rationale"), run_dir)
                human = normalizer.from_requests(
                    requests, routing, decision=decision.get("provenance"),
                    source_ref=getattr(inputs.refs.get("decision-record"), "content_hash",
                                       None), dimension_3d=dimension_3d)
            except (ValueError, normalizer.NormalizeError) as exc:
                problem = str(exc)
        for finding in human:
            finding["build"] = _build(None, commit, verification)
        if problem:
            return StepResult.blocked(
                f"G4's decision to iterate names typed findings the triage cannot use: "
                f"{problem}. Decide again with a valid findings file (wgf decide <run> "
                f"iterate --findings FILE), or without one.")

        ledger = self._ledger(previous, proto, proto_seq, inputs, normalized, decision,
                              decision_seq, human)
        # The run's finding ledger moves on in _report, once this triage's group is chosen.
        self._now = self.clock()
        self._life = dict(
            previous=ledgers.previous_lifecycle(inputs.refs, lambda t: _load(inputs, t)),
            failing={kind: {f["id"] for f in items} for kind, items in normalized.items()},
            seqs={kind: _seq(inputs, kind) for kind in normalized},
            reports={kind: report for kind, report in reports.items() if report is not None},
            proto=proto, proto_seq=proto_seq, decision=decision, decision_seq=decision_seq,
            human_ids={f["id"] for f in human}, routing_version=routing.version,
            build_of=build_of)
        gate_seqs = [_seq(inputs, kind) for kind in GATE_REPORTS if reports.get(kind)]
        measured_since = any(seq > previous_seq for seq in gate_seqs)
        if decision_seq > previous_seq and sent_back:
            measured_since = True  # a person judged the build since the previous triage

        if previous and previous.get("pending") and not measured_since:
            return self._continue(context, inputs, routing, previous, entered, title_id,
                                  commit, ledger)

        found = []
        for kind in GATE_REPORTS:
            if _seq(inputs, kind) <= proto_seq:
                continue  # it measured an earlier build
            found.extend(normalized.get(kind) or [])
        if sent_back:
            if human:
                found.extend(human)
            else:
                found.append(self._note_finding(routing, decision, inputs))
        # Findings an assets pass that ran after their report (or decision) already handled:
        # not routed again, recorded in the ledger as made again by the assets step.
        manifest_seq = _seq(inputs, "asset-manifest")
        handed = [f for f in found if f.get("route") == "assets"
                  and manifest_seq > _seq(inputs, f["source"]["producer"])]
        if handed:
            manifest = _load(inputs, "asset-manifest") or {}
            made = {"specialist": "assets", "seq": manifest_seq,
                    "artifact_id": (manifest.get("provenance") or {}).get("artifact_id")}
            self._life["handed"] = [(f, made) for f in self._unique(handed)]
        found = [f for f in found if f not in handed]
        if not found and entered and entered.rpartition(".")[2] not in ("success", ""):
            found.append(self._unnamed(routing, entered))
        found = self._unique(found)
        _guard(found, context, _load(inputs, "knowledge-contract"))
        self._held_excepted = [{"finding": f["id"], "reason": why}
                               for f, why in _excepted(found, inputs, context)]
        return self._fresh(context, inputs, routing, found, entered, title_id, commit, ledger,
                           first_pass=not found)

    # -- the two kinds of triage ---------------------------------------------------------

    def _fresh(self, context, inputs, routing, found, entered, title_id, commit, ledger,
               first_pass):
        if first_pass:
            report = self._report(context, inputs, routing, title_id, commit, entered,
                                  source=entered, mode="first-pass", findings=[], groups=[],
                                  selected=None, pending=[], deferred=[], held=[],
                                  ledger=ledger, verdict="clear",
                                  message="nothing on the current build is left to route",
                                  current=[])
            return StepResult.success([report], message="triage: nothing to route")
        excepted = {h["finding"] for h in getattr(self, "_held_excepted", None) or ()}
        groups = routing.groups([f for f in found if f["id"] not in excepted])
        takeable, held = self._split(groups, found)
        held = list(getattr(self, "_held_excepted", None) or ()) + held
        deferred = []
        if takeable and takeable[0]["route"] == "design":
            selected, pending, deferred = takeable[0], [], takeable[1:]
        elif takeable:
            selected, pending = takeable[0], takeable[1:]
        else:
            selected, pending = None, []
        return self._finish(context, inputs, routing, title_id, commit, entered,
                            source=entered, mode="fresh", findings=found, groups=groups,
                            selected=selected, pending=pending, deferred=deferred, held=held,
                            ledger=ledger, current=found)

    def _continue(self, context, inputs, routing, previous, entered, title_id, commit,
                  ledger):
        pending = list(previous.get("pending") or [])
        selected, rest = pending[0], pending[1:]
        wanted = {fid for group in pending for fid in group.get("findings") or []}
        found = [f for f in previous.get("findings") or [] if f.get("id") in wanted]
        return self._finish(context, inputs, routing, title_id, commit, entered,
                            source=previous.get("source"), mode="continued", findings=found,
                            groups=pending, selected=selected, pending=rest, deferred=[],
                            held=list(previous.get("held") or []), ledger=ledger, current=[])

    def _finish(self, context, inputs, routing, title_id, commit, entered, *, source, mode,
                findings, groups, selected, pending, deferred, held, ledger, current):
        verdict = "routed" if selected else "held"
        if selected:
            owner = routing.specialist(selected["owner"])
            message = (f"{len(selected['findings'])} finding(s) to {owner['label']} "
                       f"(route `{selected['label']}`)"
                       + (f"; {len(pending)} more group(s) pending" if pending else "")
                       + (f"; {len(deferred)} deferred behind the design change"
                          if deferred else "")
                       + (f"; {len(held)} held" if held else ""))
        else:
            message = ("no route of this step can take the findings: "
                       + "; ".join(f"{h['finding']}: {h['reason']}" for h in held[:5]))
        report = self._report(context, inputs, routing, title_id, commit, entered,
                              source=source, mode=mode, findings=findings, groups=groups,
                              selected=selected, pending=pending, deferred=deferred,
                              held=held, ledger=ledger, verdict=verdict, message=message,
                              current=current)
        if not selected:
            context.logger.warning("triage held every finding", held=len(held))
            return StepResult("BLOCKED", artifacts=[report], message=message)
        context.logger.info("triage routed", route=selected["label"], owner=selected["owner"],
                            findings=len(selected["findings"]), pending=len(pending))
        return StepResult.success([report], route=selected["label"], message=message)

    # -- helpers -------------------------------------------------------------------------

    def _routed_labels(self):
        on = getattr(self.definition, "on", None)
        return set(on) if isinstance(on, dict) and on else None

    def _split(self, groups, found):
        """(groups this step routes, [held entries]): a group whose label the step's `on:`
        does not route is held - nothing in this loop can do its work."""
        labels = self._routed_labels()
        if labels is None:
            return groups, []
        takeable, held = [], []
        for group in groups:
            if group["label"] in labels:
                takeable.append(group)
                continue
            why = (f"route `{group['label']}` ({group['owner']}) is not taken from this step: "
                   + ("store copy is written by store-listing after G4, and the "
                      "triage after listing-validation routes it there" if group["route"] == "listing"
                      else "the workflow maps no step to it"))
            held.extend({"finding": fid, "reason": why} for fid in group["findings"])
        return takeable, held

    @staticmethod
    def _unique(found):
        seen, out = set(), []
        for finding in found:
            if finding["id"] in seen:
                continue
            seen.add(finding["id"])
            out.append(finding)
        return out

    @staticmethod
    def _note_finding(routing, decision, inputs):
        """G4 iterate without typed findings: the note is the only statement of what to
        change, so it is the generalist's finding, accepted by the next G4."""
        note = (decision.get("rationale") or "").strip()
        owner = routing.owner(routing.default_dimension)
        return {
            "id": normalizer.finding_id("decision-record", "iterate"),
            "dimension": routing.default_dimension,
            "severity": "major",
            "source": {"producer": "decision-record",
                       "step": routing.producer("decision-record").get("step"),
                       "check": "iterate", "project": None,
                       "artifact_id": (decision.get("provenance") or {}).get("artifact_id"),
                       "content_hash": getattr(inputs.refs.get("decision-record"),
                                               "content_hash", None)},
            "summary": f"G4 iterate: {note}" if note else
                       "G4 iterate, with no reason recorded and no typed findings",
            "evidence_refs": [],
            "owner": owner,
            "task": {"change": note or ("Nothing says what to change: re-check the build "
                                        "against its brief and report what you find."),
                     "acceptance": [routing.producer("decision-record").get("acceptance")
                                    or "the person deciding G4 checks it"]},
            "route": routing.route_of(owner),
        }

    @staticmethod
    def _unnamed(routing, entered):
        owner = routing.owner(routing.default_dimension)
        return {
            "id": normalizer.finding_id("triage", entered.replace(".", "-")),
            "dimension": routing.default_dimension, "severity": "major",
            "source": {"producer": "triage", "step": None, "check": entered, "project": None,
                       "artifact_id": None, "content_hash": None},
            "summary": f"`{entered}` sent the build back and no report names a failure of "
                       f"the current build",
            "evidence_refs": [], "owner": owner,
            "task": {"change": "Re-check the build against its brief; report what you find "
                               "in known_issues.",
                     "acceptance": [f"the step behind `{entered}` passes the next build"]},
            "route": routing.route_of(owner),
        }

    def _ledger(self, previous, proto, proto_seq, inputs, normalized, decision,
                decision_seq, human):
        ledger = [dict(entry) for entry in (previous or {}).get("ledger") or []]
        block = (proto or {}).get("specialist")
        proto_id = ((proto or {}).get("provenance") or {}).get("artifact_id")
        if isinstance(block, dict) and proto_id and not any(
                e.get("prototype_report") == proto_id for e in ledger):
            ledger.append({
                "develop_visit": (proto or {}).get("iteration"),
                "prototype_report": proto_id, "prototype_seq": proto_seq,
                "commit": ((proto or {}).get("build_ref") or {}).get("commit_sha"),
                "specialist": block.get("role") or "gameplay",
                "findings_in": list(block.get("findings") or []),
                "resolved": [], "unresolved": [],
                "unmeasured": list(block.get("findings") or []),
                "sessions": block.get("sessions"), "cost_usd": block.get("cost_usd")})
        failing = {kind: {f["id"] for f in items} for kind, items in normalized.items()}
        human_ids = {f["id"] for f in human}
        for entry in ledger:
            after = entry.get("prototype_seq") or 0
            still = []
            for fid in entry.get("unmeasured") or []:
                producer = fid.split(":", 1)[0]
                if producer == "decision-record":
                    if decision is not None and decision_seq > after:
                        reraised = decision.get("decision") == "iterate" and fid in human_ids
                        entry["unresolved" if reraised else "resolved"].append(fid)
                    else:
                        still.append(fid)
                elif producer in failing and _seq(inputs, producer) > after:
                    entry["unresolved" if fid in failing[producer] else "resolved"].append(fid)
                else:
                    still.append(fid)
            entry["unmeasured"] = still
        return ledger

    def _report(self, context, inputs, routing, title_id, commit, entered, *, source, mode,
                findings, groups, selected, pending, deferred, held, ledger, verdict,
                message, current):
        now = getattr(self, "_now", None) or self.clock()
        artifact_id = provenance.artifact_id("triage-report", title_id, now,
                                             getattr(context, "execution", 1))
        life = getattr(self, "_life", None) or {}
        lifecycle = lifecycles.advance(
            life.get("previous") or [], at=now, current=current,
            failing=life.get("failing") or {}, seqs=life.get("seqs") or {},
            reports=life.get("reports") or {}, proto=life.get("proto"),
            proto_seq=life.get("proto_seq", -1), decision=life.get("decision"),
            decision_seq=life.get("decision_seq", -1), human_ids=life.get("human_ids") or set(),
            selected=selected, triage_id=artifact_id,
            routing_version=life.get("routing_version") or routing.version,
            build_of=life.get("build_of") or (lambda kind: {"commit": commit, "digest": None}),
            handed=life.get("handed"))
        _guard(findings, context, _load(inputs, "knowledge-contract"))
        candidates = _lesson_candidates(_load(inputs, "triage-report"), life.get("proto"))
        body = {
            "provenance": provenance.build(
                "triage-report",
                artifact_id=artifact_id,
                produced_by=provenance.producer("architect"), produced_at=now,
                inputs=provenance.pin_inputs(inputs), title_id=title_id),
            "title_id": title_id,
            "entered_by": entered,
            "source": source,
            "mode": mode,
            "commit": commit,
            "findings": findings,
            "groups": groups,
            "selected": selected,
            "pending": pending,
            "deferred": deferred,
            "held": held,
            "ledger": ledger,
            "lifecycle": lifecycle,
            "routing": {"reference": "core/reference/specialist-routing.yaml",
                        "version": routing.version, "content_hash": routing.content_hash},
            "verdict": verdict,
            "message": message,
        }
        if candidates:
            body["lesson_candidates"] = candidates
        return ArtifactOutput("triage-report", provenance.seal(body), metadata={
            "verdict": verdict, "route": (selected or {}).get("label"),
            "owner": (selected or {}).get("owner"), "findings": len(findings),
            "pending": len(pending)})

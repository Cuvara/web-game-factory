"""What a waiting checkpoint's own inputs say, for the person who decides it.

A gate is decided on its required artifacts (the checkpoint's `inputs`). The CLI printed only
the choices, so a person deciding G4 saw no kill criterion - and nothing said that every one
was unmeasured (the 2.1.2 production run). This module reads the inputs by their fields, not
by step or artifact type, so any checkpoint whose inputs carry the same fields shows them:

    kill_criteria_eval   (prototype-report)        each criterion: breached, measured or not
    playtest_sessions    (prototype-report)        how many sessions, and by whom
    verdict + evidence_status (qa / verification)  the report's verdict and evidence status
    consistency          (game-design)             the content rules, and the genre model they
                                                   were checked against (G3)
    content_coverage     (prototype-report)        designed units against built ones
    design_gaps          (prototype-report)        where the design did not say enough
    checks/skipped_checks (playability-report)     what the bot measured about the content,
                                                   difficulty, progression and depth - and what
                                                   it could not, which is never a pass
    verdict + blockers   (review-report)           the reviewer's verdict, fidelity blockers
                                                   named as such
    features[].evaluation (game-design)            every feature the design cut or deferred,
                                                   with its source and reason - a feature the
                                                   brief asked for and this build does not
                                                   have is said so (G3, G4)
    dimensions + release_decision (quality-report) every quality dimension's score against its
                                                   floor, the open findings and the release
                                                   decision (G4) - `development` for a tier-mvp
                                                   run, never a release
    rules + required_validators + counts           (knowledge-contract) the rules the build
                                                   is held to by level, the steps that
                                                   validate them, the exceptions granted or
                                                   refused and by whom (G3)
    scorecard + missing_gates + lesson_candidates  (quality-report) the per-discipline lines
                                                   with the hard blockers listed on their own,
                                                   the gates the run's workflow lacks, and the
                                                   lessons specialists proposed (WS-9)
    compliance           (quality-report)          the run's knowledge compliance: enforcing or
                                                   advisory (and why), the verdict, the rules
                                                   by level - satisfied, failed, unmeasured,
                                                   excepted - the rules that hold the release,
                                                   every exception with its status, the
                                                   versions the rules came from

Read-only and presentation only: it decides nothing, and a guard or a gate never reads it.
"""

__all__ = ["summarize", "render"]

UNMEASURED = "unmeasured"
BREACHED = "breached"
NOT_BREACHED = "not breached"
# The criterion and check id prefixes that are about the content the design committed to.
CONTENT_RULES = "content."
PLAYED_PREFIXES = ("content.", "difficulty.", "progression.", "depth.")
# A blocker is about design fidelity when it says so: the review brief asks for the words.
FIDELITY = ("fidelity", "design_gaps", "content unit", "units.json", "invented")


def _criterion_status(result):
    if result.get("breached"):
        return BREACHED
    if result.get("measured") is None:
        return UNMEASURED
    return NOT_BREACHED


def _content_rules(content):
    """{"rules", "breached", "model"} from an artifact carrying a `consistency` block."""
    consistency = content.get("consistency")
    if not isinstance(consistency, dict):
        return None
    results = [r for r in consistency.get("rule_results") or []
               if isinstance(r, dict) and str(r.get("criterion_id") or "").startswith(CONTENT_RULES)]
    model = consistency.get("content_model") or {}
    if not results and not model:
        return None
    return {"rules": len(results),
            "breached": [r.get("criterion_id") for r in results if r.get("breached")],
            "model": (f"{model.get('id')}@{model.get('version')}"
                      if model.get("id") or model.get("version") else None),
            "notes": [f"{r.get('criterion_id')}: {r.get('note')}" for r in results
                      if r.get("breached") and r.get("note")]}


def _played(content):
    """{"checks", "skipped"} from an artifact carrying playability `checks` for the content,
    difficulty, progression and depth contracts. A skipped check is reported as skipped: a
    reader counting passes must subtract it, not add it."""
    checks = [c for c in content.get("checks") or []
              if isinstance(c, dict) and str(c.get("id") or "").startswith(PLAYED_PREFIXES)]
    skipped = [s for s in content.get("skipped_checks") or [] if isinstance(s, dict)]
    if not checks and not skipped:
        return None
    collapsed = {}
    for check in checks:
        entry = collapsed.setdefault(check["id"], {"id": check["id"], "status": "PASS",
                                                   "where": [], "summary": ""})
        entry["where"].append(check.get("project"))
        rank = {"PASS": 0, "SKIPPED": 1, "WARNING": 2, "BLOCKED": 3, "FAIL": 4}
        if rank.get(check.get("status"), 0) >= rank.get(entry["status"], 0):
            entry["status"] = check.get("status")
            entry["summary"] = check.get("summary") or ""
    return {"checks": [collapsed[k] for k in sorted(collapsed)],
            "skipped": [{"id": s.get("id"), "reason": s.get("reason")} for s in skipped]}


def _left_out(content):
    """{"cut", "later"} from an artifact whose `features` carry evaluations (game-design
    1.10.0): what was evaluated and not built, each with its source and reason."""
    out = {"cut": [], "later": []}
    for feature in content.get("features") or []:
        evaluation = feature.get("evaluation") if isinstance(feature, dict) else None
        if isinstance(evaluation, dict) and evaluation.get("decision") in out:
            out[evaluation["decision"]].append({
                "name": feature.get("name") or feature.get("id"),
                "source": feature.get("source"), "reason": evaluation.get("reason")})
    return out if out["cut"] or out["later"] else None


def _quality(content):
    """The scorecard of an artifact carrying `dimensions` and a `release_decision`
    (quality-report), or None."""
    decision = content.get("release_decision")
    dimensions = content.get("dimensions")
    if not isinstance(decision, dict) or not isinstance(dimensions, list):
        return None
    floor = ((content.get("benchmark") or {}).get("floor") or {}).get("version")
    open_findings = [f for f in content.get("findings") or []
                     if isinstance(f, dict) and f.get("status") == "open"]
    return {"verdict": content.get("verdict"), "decision": decision.get("decision"),
            "reasons": list(decision.get("reasons") or []),
            "tier": content.get("quality_tier"), "floor": floor,
            "overall": content.get("overall_score"),
            "dimensions": [{"id": d.get("id"), "score": d.get("score"),
                            "min_score": d.get("min_score"), "status": d.get("status")}
                           for d in dimensions if isinstance(d, dict)],
            "findings": len(open_findings),
            "blockers": [f.get("id") for f in open_findings if f.get("severity") == "blocker"],
            "scorecard": [{"id": l.get("id"), "label": l.get("label"), "score": l.get("score"),
                           "status": l.get("status")}
                          for l in ((content.get("scorecard") or {}).get("lines") or [])
                          if isinstance(l, dict)],
            "hard_blockers": [h for h in ((content.get("scorecard") or {})
                                          .get("hard_blockers") or []) if isinstance(h, dict)],
            "missing_gates": [g.get("step") for g in content.get("missing_gates") or []
                              if isinstance(g, dict) and g.get("step")],
            "lesson_candidates": [c.get("summary") for c in content.get("lesson_candidates")
                                  or [] if isinstance(c, dict) and c.get("summary")]}


def _compliance(content):
    """The knowledge compliance of an artifact carrying a `compliance` section with a
    `verdict` (quality-report 1.3.0), or None."""
    section = content.get("compliance")
    if not isinstance(section, dict) or "verdict" not in section:
        return None
    by_level = ((section.get("counts") or {}).get("by_level") or {})
    versions = section.get("versions") or {}
    lessons = versions.get("lessons")
    tiers = versions.get("check_tiers")
    failing = []
    for rule in section.get("rules") or []:
        if isinstance(rule, dict) and rule.get("status") in ("FAILED", "UNMEASURED"):
            failing.append({"id": rule.get("id"), "level": rule.get("level"),
                            "status": rule.get("status"), "blocks": bool(rule.get("blocks")),
                            "checks": [c.get("check") for c in rule.get("checks") or []
                                       if isinstance(c, dict)
                                       and c.get("status") in ("FAIL", "UNMEASURED")]})
    return {"mode": section.get("mode"), "verdict": section.get("verdict"),
            "holds_release": bool(section.get("holds_release")),
            "advisory_reason": section.get("advisory_reason"),
            "retroactive": bool((section.get("contract") or {}).get("retroactive")),
            "levels": {k: v for k, v in by_level.items()
                       if isinstance(v, dict) and v.get("applicable")},
            "failing": failing,
            "exceptions": [{"rule_id": e.get("rule_id"), "status": e.get("status"),
                            "by": (e.get("approved_by") or {}).get("identifier")
                            if isinstance(e.get("approved_by"), dict) else None,
                            "expires_at": e.get("expires_at"), "reason": e.get("reason")}
                           for e in section.get("exceptions") or [] if isinstance(e, dict)],
            "versions": {"lessons": lessons.get("version") if isinstance(lessons, dict)
                         else lessons,
                         "check_tiers": tiers.get("version") if isinstance(tiers, dict)
                         else tiers,
                         "factory": (versions.get("factory") or {}).get("version")
                         if isinstance(versions.get("factory"), dict) else None},
            "new_lessons": len(section.get("new_lessons") or [])}


def _contract(content):
    """The knowledge contract of an artifact carrying `rules`, `required_validators` and
    `counts` (knowledge-contract, G3), or None: the counts by level, the blocking and
    required rule ids, the validating steps, the experimental gaps, every exception honoured
    or refused (by whom), whether it is advisory, and the versions it was made from."""
    if not all(key in content for key in ("rules", "required_validators", "counts")):
        return None
    rules = [r for r in content.get("rules") or [] if isinstance(r, dict)]
    versions = content.get("versions") or {}

    def version(key):
        value = versions.get(key)
        return value.get("version") if isinstance(value, dict) else value

    def exception(record, status, problems=()):
        approved = record.get("approved_by") if isinstance(record.get("approved_by"),
                                                           dict) else {}
        return {"rule_id": record.get("rule_id"), "status": status,
                "by": approved.get("identifier"), "expires_at": record.get("expires_at"),
                "reason": record.get("reason"), "problems": list(problems)}

    refused = []
    for entry in content.get("exceptions_refused") or []:
        if isinstance(entry, dict) and isinstance(entry.get("exception"), dict):
            refused.append(exception(entry["exception"], "refused",
                                     entry.get("problems") or ()))
    advisory = content.get("advisory") if isinstance(content.get("advisory"), dict) else None
    return {"counts": dict(content.get("counts") or {}),
            "blocking": [r.get("id") for r in rules if r.get("level") == "blocking"],
            "recommended": [r.get("id") for r in rules if r.get("level") == "recommended"],
            "required": [r.get("id") for r in rules if r.get("level") == "required"],
            "validators": list(content.get("required_validators") or []),
            "experimental": [e.get("id") for e in content.get("experimental") or []
                             if isinstance(e, dict)],
            "exceptions": [exception(e, "granted") for e in content.get("exceptions") or []
                           if isinstance(e, dict)] + refused,
            "advisory": (advisory or {}).get("problems") if advisory else None,
            "facets": {k: v for k, v in (content.get("facets") or {}).items()
                       if v not in (None, [])},
            "versions": {"lessons": version("lessons"), "check_tiers": version("check_tiers"),
                         "factory": version("factory")}}


def _fidelity(blocker):
    text = " ".join(str(blocker.get(k) or "") for k in ("summary", "file", "id")).lower()
    return any(word in text for word in FIDELITY)


def summarize(artifacts):
    """{"criteria", "playtests", "reports", "content", "coverage", "gaps", "played", "reviews",
    "features"} from {artifact_type: content}, or None when no input carries any of the fields above."""
    criteria, playtests, reports = [], [], []
    content_rules, coverage, gaps, played, reviews, left_out = [], [], [], [], [], []
    quality, knowledge_contracts = [], []
    for artifact_type, content in sorted(artifacts.items()):
        if not isinstance(content, dict):
            continue
        contract = _contract(content)
        if contract:
            knowledge_contracts.append({"artifact": artifact_type, **contract})
        rules = _content_rules(content)
        if rules:
            content_rules.append({"artifact": artifact_type, **rules})
        if isinstance(content.get("content_coverage"), dict):
            coverage.append({"artifact": artifact_type, **content["content_coverage"]})
        for gap in content.get("design_gaps") or []:
            if isinstance(gap, dict):
                gaps.append({"artifact": artifact_type, "field": gap.get("field"),
                             "severity": gap.get("severity"), "question": gap.get("question"),
                             "assumed": gap.get("assumed")})
        scorecard = _quality(content)
        if scorecard:
            knowledge = _compliance(content)
            if knowledge:
                scorecard["compliance"] = knowledge
            quality.append({"artifact": artifact_type, **scorecard})
        omitted = _left_out(content)
        if omitted:
            left_out.append({"artifact": artifact_type, **omitted})
        seen = _played(content)
        if seen:
            played.append({"artifact": artifact_type, **seen})
        if isinstance(content.get("blockers"), list) and "verdict" in content:
            blockers = [b for b in content["blockers"] if isinstance(b, dict)]
            reviews.append({"artifact": artifact_type, "verdict": content.get("verdict"),
                            "blockers": len(blockers),
                            "fidelity": [b.get("id") or b.get("summary", "")[:60]
                                         for b in blockers if _fidelity(b)]})
        for result in content.get("kill_criteria_eval") or []:
            if isinstance(result, dict):
                criteria.append({"criterion_id": result.get("criterion_id") or "unnamed",
                                 "status": _criterion_status(result),
                                 "measured": result.get("measured"),
                                 "note": result.get("note")})
        sessions = content.get("playtest_sessions")
        if isinstance(sessions, list):
            contexts = {}
            for session in sessions:
                if isinstance(session, dict):
                    key = session.get("player_context") or "unknown"
                    contexts[key] = contexts.get(key, 0) + 1
            playtests.append({"artifact": artifact_type, "sessions": len(sessions),
                              "by_player_context": dict(sorted(contexts.items()))})
        if "verdict" in content and "evidence_status" in content:
            reports.append({"artifact": artifact_type, "verdict": content.get("verdict"),
                            "evidence_status": content.get("evidence_status")})
    if not (criteria or playtests or reports or content_rules or coverage or gaps or played
            or reviews or left_out or quality or knowledge_contracts):
        return None
    return {"criteria": criteria, "playtests": playtests, "reports": reports,
            "content": content_rules, "coverage": coverage, "gaps": gaps, "played": played,
            "reviews": reviews, "features": left_out, "quality": quality,
            "knowledge": knowledge_contracts,
            "unmeasured": [c["criterion_id"] for c in criteria if c["status"] == UNMEASURED]}


def _value(measured):
    if measured is None:
        return "-"
    if isinstance(measured, bool):
        return "yes" if measured else "no"
    return str(measured)


def _compliance_lines(knowledge):
    if not knowledge:
        return []
    versions = knowledge.get("versions") or {}
    lines = [f"    knowledge compliance: {knowledge['verdict']} ({knowledge['mode']}"
             + (", holds the release" if knowledge.get("holds_release") else "") + ")"
             + f" - lessons {versions.get('lessons') or '?'}, check-tiers "
               f"{versions.get('check_tiers') or '?'}"]
    if knowledge.get("advisory_reason"):
        lines.append(f"      advisory: {knowledge['advisory_reason'][:110]}")
    for level, row in (knowledge.get("levels") or {}).items():
        lines.append(f"      {level:<13} {row.get('applicable')} applicable, "
                     f"{row.get('satisfied')} satisfied, {row.get('failed')} failed, "
                     f"{row.get('unmeasured')} unmeasured, {row.get('excepted')} excepted")
    for rule in knowledge.get("failing") or []:
        lines.append(f"      {'!' if rule['blocks'] else '-'} {rule['id']} ({rule['level']}) "
                     f"{rule['status']}"
                     + (f": {', '.join(rule['checks'][:4])}" if rule['checks'] else ""))
    for entry in knowledge.get("exceptions") or []:
        lines.append(f"      exception {entry['rule_id']} {str(entry['status']).upper()} "
                     f"(by {entry.get('by') or '?'}, until {entry.get('expires_at')}): "
                     f"{str(entry.get('reason') or '')[:70]}")
    if knowledge.get("new_lessons"):
        lines.append(f"      {knowledge['new_lessons']} new lesson candidate(s) above")
    return lines


def render(evidence):
    """Lines for a terminal; [] for no evidence."""
    if not evidence:
        return []
    lines = ["Evidence (the checkpoint's inputs):"]
    criteria = evidence.get("criteria") or []
    if criteria:
        width = max(len(c["criterion_id"]) for c in criteria)
        for c in criteria:
            lines.append(f"  {c['criterion_id']:<{width}}  {c['status']:<12}  "
                         f"measured: {_value(c['measured'])}")
        unmeasured = evidence.get("unmeasured") or []
        if unmeasured:
            lines.append(f"  ! {len(unmeasured)} of {len(criteria)} criteria unmeasured: "
                         f"`breached: false` on them is not evidence.")
    for playtest in evidence.get("playtests") or []:
        contexts = ", ".join(f"{k} {v}" for k, v in playtest["by_player_context"].items())
        lines.append(f"  playtest sessions ({playtest['artifact']}): {playtest['sessions']}"
                     + (f" ({contexts})" if contexts else ""))
    for entry in evidence.get("content") or []:
        model = f"; model {entry['model']}" if entry.get("model") else ""
        lines.append(f"  content: {entry['rules']} rules, {len(entry['breached'])} breached"
                     + model)
        for note in entry.get("notes") or []:
            lines.append(f"    ! {note}")
        for rule in entry["breached"]:
            if not any(str(note).startswith(str(rule)) for note in entry.get("notes") or []):
                lines.append(f"    ! {rule} breached")
    for entry in evidence.get("coverage") or []:
        partial = entry.get("partial")
        lines.append(f"  content coverage ({entry['artifact']}): {entry.get('built')} of "
                     f"{entry.get('designed')} designed units built"
                     + (f", {partial} partial" if partial else "")
                     + (f", {entry.get('cut')} cut" if entry.get("cut") else ""))
    gaps = evidence.get("gaps") or []
    if gaps:
        blocking = [g for g in gaps if g.get("severity") == "blocking"]
        lines.append(f"  design gaps: {len(gaps)} ({len(blocking)} blocking) - the design did "
                     "not say enough, and something was assumed instead")
        for gap in gaps[:6]:
            lines.append(f"    - ({gap.get('severity')}) {gap.get('field')}: "
                         f"{gap.get('assumed') or 'nothing was built'}")
    for entry in evidence.get("played") or []:
        for check in entry["checks"]:
            lines.append(f"  played {check['id']:<28} {check['status']:<8} {check['summary'][:70]}")
        for skip in entry["skipped"]:
            lines.append(f"  played {skip['id']:<28} {'SKIPPED':<8} not measured: "
                         f"{(skip.get('reason') or '')[:70]}")
        if entry["skipped"]:
            lines.append(f"  ! {len(entry['skipped'])} content check(s) measured nothing: a skip "
                         "is not a pass.")
    for entry in evidence.get("features") or []:
        for decision, label in (("cut", "cut from the design"), ("later", "deferred, not built")):
            if entry.get(decision):
                lines.append(f"  features {label} ({entry['artifact']}): {len(entry[decision])}")
            for feature in entry.get(decision) or []:
                lines.append(f"    - {feature['name']} ({feature.get('source') or 'design'}): "
                             f"{(feature.get('reason') or '')[:110]}")
        asked = [f["name"] for d in ("cut", "later") for f in entry.get(d) or []
                 if f.get("source") == "brief"]
        if asked:
            lines.append(f"  ! the brief asked for {', '.join(asked)}: not in this build.")
    for entry in evidence.get("reviews") or []:
        lines.append(f"  {entry['artifact']}: verdict {entry['verdict']}, "
                     f"{entry['blockers']} blocker(s)"
                     + (f"; design fidelity: {', '.join(entry['fidelity'])}"
                        if entry["fidelity"] else ""))
    for entry in evidence.get("quality") or []:
        lines.append(f"  quality ({entry['artifact']}): verdict {entry['verdict']}, decision "
                     f"{entry['decision']} at tier {entry.get('tier') or 'none'}"
                     + (f", floor {entry['floor']}" if entry.get("floor") else "")
                     + (f", overall {entry['overall']:g} (decides nothing)"
                        if isinstance(entry.get("overall"), (int, float)) else ""))
        for dim in entry["dimensions"]:
            score = dim["score"] if dim["score"] is not None else "-"
            floor = dim["min_score"] if dim["min_score"] is not None else "-"
            lines.append(f"    {str(dim['id']):<12} {str(score):>6} / floor {str(floor):<5} "
                         f"{dim['status']}")
        if entry.get("missing_gates"):
            lines.append(f"    ! MISSING GATES: this run's workflow does not have "
                         f"{', '.join(entry['missing_gates'])} - their evidence does not "
                         "exist; this build is never a release")
        if entry.get("scorecard"):
            lines.append("    scorecard:")
            for line in entry["scorecard"]:
                score = line["score"] if line["score"] is not None else "-"
                lines.append(f"      {str(line['label'] or line['id']):<32} {str(score):>6}  "
                             f"{line['status']}")
        for blocker in entry.get("hard_blockers") or []:
            lines.append(f"    ! hard blocker {blocker.get('criterion')} ({blocker.get('line')}, "
                         f"{blocker.get('status')}): no score lifts it")
        if entry["findings"]:
            lines.append(f"    {entry['findings']} open finding(s)"
                         + (f"; blocking: {', '.join(entry['blockers'][:6])}"
                            if entry["blockers"] else ""))
        for reason in entry["reasons"][:4]:
            lines.append(f"    - {reason[:110]}")
        for summary in (entry.get("lesson_candidates") or [])[:6]:
            lines.append(f"    lesson candidate (promote to core/reference/lessons.yaml, or "
                         f"not): {summary[:90]}")
        lines.extend(_compliance_lines(entry.get("compliance")))
    for entry in evidence.get("knowledge") or []:
        counts = entry.get("counts") or {}
        versions = entry.get("versions") or {}
        lines.append(f"  knowledge contract: {counts.get('blocking', 0)} blocking, "
                     f"{counts.get('required', 0)} required, "
                     f"{counts.get('recommended', 0)} recommended, "
                     f"{counts.get('experimental', 0)} experimental, "
                     f"{counts.get('not_applicable', 0)} not applicable - lessons "
                     f"{versions.get('lessons') or '?'}, check-tiers "
                     f"{versions.get('check_tiers') or '?'}")
        if entry.get("facets"):
            lines.append("    facets: " + ", ".join(f"{k} {v}" for k, v in
                                                     entry["facets"].items()))
        if entry.get("blocking"):
            lines.append(f"    blocking: {', '.join(entry['blocking'])}")
        if entry.get("required"):
            lines.append(f"    required: {', '.join(entry['required'])}")
        if entry.get("recommended"):
            lines.append(f"    recommended (reported, never blocking): "
                         f"{', '.join(entry['recommended'])}")
        if entry.get("validators"):
            lines.append(f"    validated by: {', '.join(entry['validators'])}")
        if entry.get("experimental"):
            lines.append(f"    experimental (guidance, not enforced): "
                         f"{', '.join(entry['experimental'])}")
        for exception in entry.get("exceptions") or []:
            lines.append(f"    exception {exception['rule_id']} {exception['status'].upper()} "
                         f"(by {exception.get('by') or '?'}, until "
                         f"{exception.get('expires_at') or '?'})"
                         + (f": {str(exception.get('reason'))[:80]}"
                            if exception.get("reason") else "")
                         + (f" - refused: {'; '.join(exception['problems'])[:90]}"
                            if exception.get("problems") else ""))
        if entry.get("advisory") is not None:
            lines.append("    ! ADVISORY: a run started before the knowledge model - "
                         "reported, never enforced")
            for problem in entry["advisory"][:4]:
                lines.append(f"      - {problem[:100]}")
    for report in evidence.get("reports") or []:
        lines.append(f"  {report['artifact']}: verdict {report['verdict']}, evidence "
                     f"{report['evidence_status']}")
    return lines

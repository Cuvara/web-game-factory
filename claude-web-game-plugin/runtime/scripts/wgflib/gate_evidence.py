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


def _fidelity(blocker):
    text = " ".join(str(blocker.get(k) or "") for k in ("summary", "file", "id")).lower()
    return any(word in text for word in FIDELITY)


def summarize(artifacts):
    """{"criteria", "playtests", "reports", "content", "coverage", "gaps", "played", "reviews"}
    from {artifact_type: content}, or None when no input carries any of the fields above."""
    criteria, playtests, reports = [], [], []
    content_rules, coverage, gaps, played, reviews = [], [], [], [], []
    for artifact_type, content in sorted(artifacts.items()):
        if not isinstance(content, dict):
            continue
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
            or reviews):
        return None
    return {"criteria": criteria, "playtests": playtests, "reports": reports,
            "content": content_rules, "coverage": coverage, "gaps": gaps, "played": played,
            "reviews": reviews,
            "unmeasured": [c["criterion_id"] for c in criteria if c["status"] == UNMEASURED]}


def _value(measured):
    if measured is None:
        return "-"
    if isinstance(measured, bool):
        return "yes" if measured else "no"
    return str(measured)


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
    for entry in evidence.get("reviews") or []:
        lines.append(f"  {entry['artifact']}: verdict {entry['verdict']}, "
                     f"{entry['blockers']} blocker(s)"
                     + (f"; design fidelity: {', '.join(entry['fidelity'])}"
                        if entry["fidelity"] else ""))
    for report in evidence.get("reports") or []:
        lines.append(f"  {report['artifact']}: verdict {report['verdict']}, evidence "
                     f"{report['evidence_status']}")
    return lines

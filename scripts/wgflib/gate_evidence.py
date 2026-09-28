"""What a waiting checkpoint's own inputs say, for the person who decides it.

A gate is decided on its required artifacts (the checkpoint's `inputs`). The CLI printed only
the choices, so a person deciding G4 saw no kill criterion - and nothing said that every one
was unmeasured (the 2.1.2 production run). This module reads the inputs by their fields, not
by step or artifact type, so any checkpoint whose inputs carry the same fields shows them:

    kill_criteria_eval   (prototype-report)        each criterion: breached, measured or not
    playtest_sessions    (prototype-report)        how many sessions, and by whom
    verdict + evidence_status (qa / verification)  the report's verdict and evidence status

Read-only and presentation only: it decides nothing, and a guard or a gate never reads it.
"""

__all__ = ["summarize", "render"]

UNMEASURED = "unmeasured"
BREACHED = "breached"
NOT_BREACHED = "not breached"


def _criterion_status(result):
    if result.get("breached"):
        return BREACHED
    if result.get("measured") is None:
        return UNMEASURED
    return NOT_BREACHED


def summarize(artifacts):
    """{"criteria", "playtests", "reports"} from {artifact_type: content}, or None when no
    input carries any of the fields above."""
    criteria, playtests, reports = [], [], []
    for artifact_type, content in sorted(artifacts.items()):
        if not isinstance(content, dict):
            continue
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
    if not (criteria or playtests or reports):
        return None
    return {"criteria": criteria, "playtests": playtests, "reports": reports,
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
    for report in evidence.get("reports") or []:
        lines.append(f"  {report['artifact']}: verdict {report['verdict']}, evidence "
                     f"{report['evidence_status']}")
    return lines

"""What a designer's or developer's brief says about the build a person accepted.

    context(accepted, report)   the brief's `accepted_baseline` block, or None when nothing
                                was accepted: the accepted commit and decision, the
                                replacement maximum, whether a person approved a replacement,
                                the accepted build's metrics, and the newest
                                baseline-regression-report's open findings
    render(block)               markdown lines

Without a person's approval the rule is: EXTEND the accepted build. A visit that rewrites
its units, environment or tuning past the maximum stops the run for a person; one that makes
it measurably worse comes back with the comparison.
"""

__all__ = ["context", "render"]


def context(accepted, report=None):
    if not isinstance(accepted, dict) or accepted.get("status") != "present":
        return None
    info = accepted.get("accepted") or {}
    replacement = (report or {}).get("replacement") or {}
    decision = replacement.get("decision") or {}
    approved = (decision.get("choice") == "approve" and decision.get("decided_by") == "human")
    findings = [{"id": f.get("id"), "summary": f.get("summary"), "owner": f.get("owner")}
                for f in (report or {}).get("findings") or [] if isinstance(f, dict)]
    return {
        "commit": info.get("commit"),
        "decision": (info.get("decision") or {}).get("artifact_id"),
        "decided_at": (info.get("decision") or {}).get("decided_at"),
        "reference": (accepted.get("reference") or {}).get("version"),
        "approved_replacement": decision if approved else None,
        "restore": decision.get("choice") == "restore",
        "measured": {k: replacement.get(k) for k in ("units_replaced_share",
                                                      "files_rewritten_share",
                                                      "lines_deleted_share")
                     if replacement.get(k) is not None},
        "maximum": replacement.get("maximum") or {},
        "metrics": accepted.get("metrics") or {},
        "verdict": (report or {}).get("verdict"),
        "findings": findings[:20],
    }


def _value(value):
    if isinstance(value, dict):
        return ", ".join(f"{k} {_value(v)}" for k, v in list(value.items())[:6])
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


def render(block):
    if not block:
        return []
    at = str(block.get("commit") or "")[:12]
    out = ["## The accepted build: extend it\n"]
    out.append(f"A person played this game and accepted its build `{at}` at G4 "
               f"({block.get('decision')}, {block.get('decided_at')}). That build is the bar: "
               "every build of this run is compared with it (core/reference/"
               f"accepted-baseline.yaml {block.get('reference')}).\n")
    if block.get("approved_replacement"):
        decision = block["approved_replacement"]
        out.append(f"A person approved replacing it on {decision.get('decided_at')}"
                   + (f" (\"{decision.get('note')}\")" if decision.get("note") else "")
                   + ". The build may change its units, look and tuning; it must still not be "
                     "worse than the accepted build where the same bot measures both, nor "
                     "judged worse when its frames are shown beside the accepted ones.\n")
    else:
        maximum = block.get("maximum") or {}
        limits = ", ".join(f"{k} {v}" for k, v in maximum.items()) or "the reference's maximum"
        out.append("Extend the accepted build; do not replace it. Keep its content units, its "
                   "environment and scene, its camera and its tuning (speeds, drag, sizes, "
                   "timings) as they are, and add what this visit asks for beside them. A "
                   "change that removes or changes accepted units, rewrites accepted source "
                   f"files or deletes accepted code beyond {limits} stops the run until a "
                   "person decides whether to replace the accepted work.\n")
    if block.get("restore"):
        out.append("A person chose to RESTORE the accepted build: bring back what this run "
                   "removed or rewrote (the findings below name it) and make the change an "
                   "extension of the accepted build.\n")
    metrics = block.get("metrics") or {}
    if metrics:
        out.append("What the same bot measured on the accepted build (the next build is held "
                   "to these within the reference's tolerances):\n")
        for metric_id, values in sorted(metrics.items())[:24]:
            out.append(f"- `{metric_id}`: {_value(values)}")
        out.append("")
    findings = block.get("findings") or []
    if findings:
        out.append("Where the last build fell below the accepted one:\n")
        for item in findings:
            out.append(f"- `{item.get('id')}` ({item.get('owner')}): {item.get('summary')}")
        out.append("")
    return out

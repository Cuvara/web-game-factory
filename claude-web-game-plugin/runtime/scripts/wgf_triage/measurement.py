"""What a producer's report measured of one finding's check, and the evidence of it.

The ledger (lifecycle.py) verifies a finding on the raising producer's re-measurement. For a
producer whose report lists its checks one by one with a status - playability,
production-quality, listing-validation - "the newest report does not fail it" is not a
re-measurement: a check the report no longer lists, or lists as BLOCKED, SKIPPED or WARNING
(unmeasured, not applicable, cut short), or only on another viewport, measured nothing of
the finding. `state(producer, report, finding_id, source)` says which it is:

    pass        the same check on the same project was measured and no longer fails the
                finding (PASS; or, for a check split by route, measured and not failing
                this part)
    fail        measured, and still failing it - also a check that FAILs in a report that
                is not itself failing (BLOCKED, never normalized): for a split finding, when
                its part is among the parts the check fails (findings.failing_parts); a
                part that cannot be established is `unmeasured`
    unmeasured  listed, but nothing was measured: any other status, or a value the report
                marks `measured.unmeasured`
    missing     not listed for that project at all (removed, renamed, or played only on
                another viewport)
    None        the producer does not list its checks: the ledger's rule for it is
                unchanged (the newest report does not fail the finding's id)

`of_check` is the measurement a ledger record keeps of one report's check - the report, its
commit, the status and, for playability (since playability-report 1.4.0), the scenario the
bot played for it: its id, the bot version and settings, the viewport, the policy and seed,
and the frames with their sha256. `compare(before, after)` says whether two measurements are
the same scenario, and names every way they differ (a newer bot, other settings, another
viewport): such a comparison is weaker, and the ledger says so rather than hiding it.
"""

__all__ = ["CHECKED", "state", "check_of", "of_check", "compare", "project_of", "MAX_FRAMES"]

# The producers whose reports list each check with its own status, and the statuses that are
# a measurement. Anything else a check can say (BLOCKED, SKIPPED, WARNING) measured nothing.
CHECKED = ("playability-report", "production-quality-report", "listing-validation-report")
MEASURED = ("PASS", "FAIL")
MAX_FRAMES = 8


def project_of(producer, check):
    if producer == "listing-validation-report":
        joined = "/".join(p for p in (check.get("platform_id"), check.get("locale")) if p)
        return joined or None
    return check.get("project")


def check_of(producer, report, source):
    """The report's check the finding's `source` names (same id, same project), or None."""
    if producer not in CHECKED or not isinstance(report, dict):
        return None
    cid, project = (source or {}).get("check"), (source or {}).get("project")
    for check in report.get("checks") or []:
        if isinstance(check, dict) and check.get("id") == cid \
                and project_of(producer, check) == project:
            return check
    return None


def state(producer, report, finding_id, source, failing, routing=None):
    """pass | fail | unmeasured | missing for a CHECKED producer; None otherwise. `failing`
    is the set of finding ids the report fails (normalized); `routing` (routing.Routing,
    the shipped data when None) splits a check a split finding belongs to."""
    if producer not in CHECKED:
        return None
    check = check_of(producer, report, source)
    if check is None:
        return "missing"
    status = check.get("status")
    measured = check.get("measured")
    if status not in MEASURED or (isinstance(measured, dict) and measured.get("unmeasured")
                                  and status != "FAIL"):
        return "unmeasured"
    if finding_id in failing:
        return "fail"
    if status == "FAIL":
        # The check fails - in a report that is not itself failing (BLOCKED), whose findings
        # were never normalized: still failing, never a pass. A split finding (one route's
        # items of the check) fails when its route is among the parts the check fails, split
        # by the same rule findings.py splits them; which part fails cannot be established
        # when the check names no failing item - unmeasured.
        part = _part_of(finding_id)
        if part is None:
            return "fail"
        from .findings import failing_parts
        parts = failing_parts(routing or _routing(), producer, check)
        if parts is None:
            return "unmeasured"
        return "fail" if part in parts else "pass"
    return "pass"


def _part_of(finding_id):
    """The split part (route) of a finding id `<producer>:<check>/<part>[@<project>]`, or
    None for an unsplit id."""
    check = str(finding_id).split(":", 1)[-1].split("@")[0]
    return check.split("/", 1)[1] if "/" in check else None


_ROUTING = []


def _routing():
    """The shipped routing data (specialist-routing.yaml), read once: the split rules."""
    if not _ROUTING:
        from .routing import Routing
        _ROUTING.append(Routing.load())
    return _ROUTING[0]


def _scenario(report, check):
    sid = check.get("scenario")
    if not sid:
        return None, []
    for entry in report.get("scenarios") or []:
        if isinstance(entry, dict) and entry.get("id") == sid:
            frames = [{"id": f.get("id"), "path": f.get("path"), "sha256": f.get("sha256")}
                      for f in entry.get("frames") or [] if isinstance(f, dict)]
            bot = entry.get("bot") or {}
            policy = entry.get("policy") or {}
            return ({"id": sid, "bot_version": bot.get("version"),
                     "settings_sha256": bot.get("settings_sha256"),
                     "viewport": entry.get("viewport"),
                     "policy": policy.get("recordings") or {},
                     "seed": policy.get("seed"),
                     "actions_complete": entry.get("actions_complete")}, frames)
    bot = report.get("bot") or {}
    return ({"id": sid, "bot_version": bot.get("version"),
             "settings_sha256": bot.get("settings_sha256"), "viewport": None, "policy": {},
             "seed": None, "actions_complete": None}, [])


def of_check(producer, report, check, *, commit=None, artifact_id=None, content_hash=None,
             seq=None):
    """The measurement a ledger record keeps of `report`'s `check`."""
    report = report if isinstance(report, dict) else {}
    check = check if isinstance(check, dict) else {}
    provenance = report.get("provenance") or {}
    scenario, frames = _scenario(report, check) if producer == "playability-report" \
        else (None, [])
    if not frames:
        by_id = {(f.get("project"), f.get("id")): f for f in report.get("frames") or []
                 if isinstance(f, dict)}
        for fid in check.get("frames") or []:
            entry = by_id.get((check.get("project"), fid))
            if entry is not None:
                frames.append({"id": fid, "path": entry.get("path"),
                               "sha256": entry.get("sha256")})
    return {
        "producer": producer,
        "artifact_id": artifact_id or provenance.get("artifact_id"),
        "content_hash": content_hash or provenance.get("content_hash"),
        "seq": seq,
        "commit": report.get("commit") or commit,
        "check": check.get("id"),
        "project": project_of(producer, check) if check else None,
        "status": check.get("status"),
        "scenario": scenario,
        "frames": frames[:MAX_FRAMES],
    }


def compare(before, after):
    """{"same_scenario", "differences", "note"}: whether two measurements of one check are
    the same scenario played by the same bot under the same settings on the same viewport.
    Unknown (a report older than playability-report 1.4.0 records no scenario) is a
    difference too: nothing says they were the same."""
    differences = []
    first = (before or {}).get("scenario") or {}
    second = (after or {}).get("scenario") or {}
    if not first or not second:
        differences.append("scenario not recorded for "
                           + " and ".join(w for w, s in (("the failure", first),
                                                         ("the pass", second)) if not s))
    else:
        if first.get("id") != second.get("id"):
            differences.append(f"scenario {first.get('id')} -> {second.get('id')}")
        for key, word in (("bot_version", "bot version"), ("settings_sha256", "bot settings"),
                          ("viewport", "viewport"), ("policy", "policy"), ("seed", "seed")):
            if first.get(key) != second.get(key):
                differences.append(f"{word} differs")
    if (before or {}).get("commit") and (before or {}).get("commit") == (after or {}).get("commit"):
        differences.append("the same commit")
    same = not differences
    note = ("the same scenario, bot and settings measured the failure and the pass" if same
            else "a weaker comparison: " + "; ".join(differences))
    return {"same_scenario": same, "differences": differences, "note": note}

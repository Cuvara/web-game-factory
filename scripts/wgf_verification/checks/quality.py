"""Quality: what the bot measured about the game itself, carried into the verification.

The playability step plays the built game from outside and holds it to the design's content,
difficulty and depth contracts (scripts/wgf_playability, docs/playability-module.md). That
evidence is the only thing in the pipeline that says the build is a build *of this design* -
that the units the design lists exist and are reachable, that difficulty moves on the axes the
genre model names, that what the design says persists survives a reload, and that a session
lasts as long as it was designed to.

This module carries it, and never re-measures it:

    quality.report-commit            the playability report is about the build under test, not
                                     an earlier visit's
    quality.<group>:<check>          one check per content./difficulty./progression./depth.
                                     check of the report, every viewport collapsed into one
                                     answer: FAIL if any failed, WARNING if any was skipped or
                                     warned (a skip is never a pass), else PASS. The id is the
                                     playability check's, in the verification-report's own id
                                     vocabulary (`quality.content:units-reachable`).

With no playability report the verification is BLOCKED on it when the run asked for one, and
says so when it did not: content that has never been played is not content that is verified.
"""

from ..lineage import same_commit
from ..model import BLOCKED, FAIL, PASS, WARNING, Check, Evidence

__all__ = ["check_quality", "PREFIXES", "TITLES", "REPORT", "CATEGORY", "check_id"]

# The verification-report fixes the category vocabulary; these checks are about the game
# playing as it was designed, which is what `gameplay` means there.
CATEGORY = "gameplay"

REPORT = "playability-report"
# The playability checks this module carries. Everything else in that report (the probe, the
# first 30 seconds, the frames) is about the build being playable at all, and the gameplay and
# policy checks already speak for it.
PREFIXES = ("content.", "difficulty.", "progression.", "depth.")
TITLES = {
    "content.units_reachable": "Every designed content unit is reachable by playing",
    "content.objective_shown": "Each unit shows its objective",
    "content.win_lose_per_unit": "Each unit can be won, and can be lost",
    "content.variety": "Consecutive units differ",
    "difficulty.axes_progress": "Difficulty moves on the axes the design declares",
    "progression.persists": "What the design says persists survives a reload",
    "depth.session_length": "A session lasts as long as it was designed to",
    "depth.ramp": "The ramp holds: bad play ends, good play is asked for more",
    "depth.stall": "Play never stops: no stretch with nothing asked and nothing achieved",
}


def _title(played):
    return TITLES.get(played) or f"Playability: {played}"


def check_id(played):
    """A playability check id as a verification check id: `content.units_reachable` ->
    `quality.content:units-reachable`. The verification-report's ids are one dotted group and
    an optional `:` subject (`policy.assertions:<platform>`), so the group goes after the dot
    and the check's own name after the colon."""
    group, _, name = str(played).partition(".")
    name = name.replace("_", "-").replace(".", "-")
    return f"quality.{group}:{name}" if name else f"quality.{group}"


def _subject_commit(session):
    """The commit the playability evidence must be about: what develop built and the bot was
    asked to play (the prototype-report this verification pins), else the verified commit.

    The verified commit can be the sdk step's, one commit on top of development's; the bot
    played development's. Holding the report to the development commit this run pins is what
    catches an earlier visit's report, which is what the check is for.
    """
    developed = (((session.inputs.get("prototype-report") or {}).get("build_ref") or {})
                 .get("commit_sha"))
    return developed or session.commit


def check_quality(session):
    report = session.inputs.get(REPORT)
    if not isinstance(report, dict):
        asked = REPORT in (getattr(session, "missing_inputs", None) or ())
        reason = ("the run declares a playability-report for this step and none reached it: the "
                  "build's content, difficulty and depth are unmeasured"
                  if asked else
                  "this verification was given no playability-report, so nothing the bot "
                  "measured about the design's content, difficulty or depth is carried here")
        return [Check("quality.report", CATEGORY,
                      "A playability report of the build under test", BLOCKED, required=asked,
                      message=reason,
                      evidence=[Evidence("observation", reason)])]

    subject = _subject_commit(session)
    reported = report.get("commit")
    same = same_commit(reported, subject) or same_commit(reported, session.commit)
    checks = [Check("quality.report-commit", CATEGORY,
                    "The playability report is about this build", PASS if same else FAIL,
                    message=(f"the bot played {str(reported or 'no commit')[:12]}"
                             if same else
                             f"the playability report is about {str(reported or 'no commit')[:12]}, "
                             f"not the commit under test ({str(subject or 'unknown')[:12]}): an "
                             "earlier visit's evidence is not evidence about this build"),
                    evidence=[Evidence(
                        "artifact", f"playability-report verdict {report.get('verdict')} for "
                                    f"{str(reported or 'no commit')[:12]}",
                        content_hash=((report.get("provenance") or {}).get("content_hash")),
                        data={"commit": reported, "under_test": subject,
                              "verdict": report.get("verdict")})])]
    if not same:
        # Collapsing a stale report's checks would carry another build's answers.
        return checks

    skipped = {entry.get("id"): entry.get("reason")
               for entry in report.get("skipped_checks") or [] if isinstance(entry, dict)}
    entries = {}
    for entry in report.get("checks") or []:
        if isinstance(entry, dict) and str(entry.get("id", "")).startswith(PREFIXES):
            entries.setdefault(entry["id"], []).append(entry)
    for played in sorted(entries):
        seen = entries[played]
        statuses = {e.get("status") for e in seen}
        evidence = [Evidence("observation",
                             f"[{e.get('project')}] {e.get('status')}: {e.get('summary')}",
                             data={k: e[k] for k in ("measured", "expected", "frames")
                                   if k in e} or None)
                    for e in seen]
        if FAIL in statuses:
            status, required = FAIL, True
            message = "; ".join(f"{e.get('project')}: {e.get('summary')}"
                                for e in seen if e.get("status") == FAIL)
        elif statuses - {PASS}:
            status, required = WARNING, False
            message = ("not measured: " + (skipped.get(played) or "")
                       if "SKIPPED" in statuses else
                       "; ".join(f"{e.get('project')}: {e.get('summary')}" for e in seen
                                 if e.get("status") != PASS))
        else:
            status = PASS
            required = any(bool(e.get("required")) for e in seen)
            message = "; ".join(f"{e.get('project')}: {e.get('summary')}" for e in seen)
        checks.append(Check(check_id(played), CATEGORY, _title(played), status,
                            required=required, message=message[:500], evidence=evidence))
    return checks

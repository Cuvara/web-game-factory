"""The prototype-report this module emits, from the checks and the developer's report.

What an automated development step can honestly say is narrow, and the report keeps to it:

- It measured one thing - whether the build is playable end to end by the checks - and
  records that as the `playable_build` criterion with a real measured value.
- It did not playtest. Every `prototype_must_prove` question is `inconclusive` and every
  kill criterion is recorded unmeasured, with a note saying so. A kill gate that reads a
  development report as evidence would be deciding on nothing, and the note is what stops
  that from happening quietly.
- Its recommendation is therefore never `pass`. With green checks it is `iterate` until
  first-time playtests exist; the G4 decision belongs to a person with that evidence.

Two things it does measure, and carries as evidence rather than prose. `content_coverage` is
the designed MVP content units against the built ones, from the developer's `content_units`
and the data file the checks compared with the design, with the matching `proved` question so
a reviewer sees it beside the strategy's. `design_gaps` is where the design did not say enough
to build from; it is read back by title:design, which is why it is a field and not a line in a
session note.
"""

from wgflib import provenance

__all__ = ["build_report", "SCHEMA_VERSION", "ROLE", "CONTENT_QUESTION",
           "content_coverage", "design_gaps", "blocking_gaps"]

SCHEMA_VERSION = provenance.version_of("prototype-report")
ROLE = "gameplay"
_STATUSES = ("working", "partial", "not-started")
_DIRECTIONS = ("added", "cut", "deferred")
_UNIT_STATUSES = ("built", "partial", "cut")
_SEVERITIES = ("blocking", "minor")

# The question the content contract answers, carried in `proved` so a G4 reviewer reads it
# beside the strategy's own questions rather than counting units themselves.
CONTENT_QUESTION = "Every MVP content unit is built and reachable"


def design_gaps(report):
    """The developer's design gaps, as the prototype-report carries them.

    An entry the schema would reject is dropped here rather than failing the artifact; the
    conformance check has already made the same entry a finding, so nothing is lost
    silently."""
    gaps = []
    for gap in (report or {}).get("design_gaps") or []:
        if not isinstance(gap, dict):
            continue
        field, question = gap.get("field"), gap.get("question")
        if not (isinstance(field, str) and field.strip()):
            continue
        if not (isinstance(question, str) and question.strip()):
            continue
        if gap.get("severity") not in _SEVERITIES:
            continue
        entry = {"field": field, "question": question, "severity": gap["severity"],
                 "assumed": gap["assumed"] if isinstance(gap.get("assumed"), str) else None}
        if isinstance(gap.get("unit"), str) and gap["unit"].strip():
            entry["unit"] = gap["unit"]
        gaps.append(entry)
    return gaps


def blocking_gaps(gaps):
    """The gaps that stop the design being built as written: the run goes back to design."""
    return [gap for gap in gaps or [] if gap.get("severity") == "blocking"]


def content_coverage(report, brief):
    """The designed content against the built content, from the developer's `content_units`.

    None when the design states no content units at all (a design before game-design 1.9.0):
    a coverage of zero of zero would read as a measurement, and there was none."""
    content = (brief or {}).get("content") or {}
    designed = [unit.get("id") for unit in content.get("units") or []]
    if not designed:
        return None
    reported = {entry.get("id"): entry for entry in (report or {}).get("content_units") or []
                if isinstance(entry, dict)}
    units, counts = [], {"built": 0, "partial": 0, "cut": 0}
    for unit_id in designed:
        entry = reported.get(unit_id) or {}
        status = entry.get("status") if entry.get("status") in _UNIT_STATUSES else None
        unit = {"id": unit_id, "status": status or "cut"}
        notes = entry.get("notes")
        if isinstance(notes, str) and notes.strip():
            unit["notes"] = notes
        elif status is None:
            unit["notes"] = "not reported by the developer; counted as cut"
        counts[unit["status"]] += 1
        units.append(unit)
    return {"designed": len(designed), "built": counts["built"], "partial": counts["partial"],
            "cut": counts["cut"], "units": units}


def _content_verdict(coverage, applies):
    """proved only when every designed MVP unit is built; inconclusive where the contract
    does not apply, because then nothing was measured."""
    if not applies or not coverage:
        return "inconclusive", ("The design states no content units the build owes one for "
                               "one (no content block, or a generated one), so unit coverage "
                               "was not measured.")
    evidence = (f"{coverage['built']} of {coverage['designed']} designed MVP units built, "
                f"{coverage['partial']} partial, {coverage['cut']} cut, as the developer "
                "reported them and the content data file was checked against the design.")
    if coverage["cut"]:
        return "disproved", evidence
    if coverage["partial"] or coverage["built"] != coverage["designed"]:
        return "inconclusive", evidence
    return "proved", evidence


def _integration(report):
    given = (report or {}).get("integration_status") or {}
    status = {}
    for key in ("platform_sdk", "monetization", "analytics", "persistence"):
        value = given.get(key)
        status[key] = value if value in _STATUSES else "not-started"
    return status


def _scope_deltas(report, brief):
    deltas = []
    for delta in (report or {}).get("scope_deltas") or []:
        if (isinstance(delta, dict) and delta.get("item") and delta.get("reason")
                and delta.get("direction") in _DIRECTIONS):
            deltas.append({k: str(delta[k]) for k in ("item", "direction", "reason")})
    listed = {d["item"] for d in deltas}
    for entry in (report or {}).get("mvp") or []:
        if not isinstance(entry, dict) or entry.get("item") in listed:
            continue
        if entry.get("status") in ("cut", "deferred"):
            deltas.append({"item": entry["item"], "direction": entry["status"],
                           "reason": entry.get("notes") or "reported by the developer"})
    for asset in (report or {}).get("assets") or []:
        if isinstance(asset, dict) and asset.get("status") == "placeholder":
            deltas.append({"item": f"asset {asset.get('id')}", "direction": "deferred",
                           "reason": "placeholder integrated through the real load path; "
                                     "final asset not yet delivered"})
    return deltas


def _summary(checks):
    return "; ".join(f"{c.id} {c.status}" for c in checks)


def build_report(*, title_id, brief, checks, dev_report, commit_sha, built_at, build_url,
                 iteration, strategy, pinned_inputs, artifact_seq, produced_at):
    green = all(not c.blocking for c in checks)
    smoke = next((c for c in checks if c.id == "smoke"), None)
    evidence = (f"Built at {commit_sha[:12]}; automated checks: {_summary(checks)}. "
                "No first-time playtest has been run on this build yet.")

    questions = list((strategy or {}).get("prototype_must_prove") or brief.get("must_prove")
                     or [])
    proved = [{"question": q, "verdict": "inconclusive", "evidence": evidence}
              for q in questions]
    coverage = content_coverage(dev_report, brief)
    gaps = design_gaps(dev_report)
    content_verdict, content_evidence = _content_verdict(
        coverage, ((brief.get("content") or {}).get("applies")))
    proved.append({"question": CONTENT_QUESTION, "verdict": content_verdict,
                   "evidence": content_evidence})
    proved.append({
        "question": "The MVP builds and plays end to end: boot, first input, core loop, "
                    "game over, restart",
        "verdict": "proved" if green and smoke and smoke.status == "passed" else
                   ("disproved" if not green else "inconclusive"),
        "evidence": (f"Automated checks: {_summary(checks)}."
                     + ("" if smoke and smoke.status == "passed" else
                        " The browser smoke suite did not pass on this machine, so play was "
                        "not exercised in a browser.")),
    })

    kill = [{"criterion_id": "playable_build", "measured": green, "breached": not green,
             "evaluated_at": produced_at,
             "note": "Measured by the development module: every configured check passed."
             if green else "Measured by the development module: " + ", ".join(
                 f"{c.id} {c.status}" for c in checks if c.blocking) + " - not passed."}]
    for criterion in (strategy or {}).get("kill_criteria") or []:
        kill.append({
            "criterion_id": criterion.get("id") or "unnamed",
            "measured": None,
            "breached": False,
            "note": "NOT MEASURED. Development does not playtest; this criterion needs "
                    "first-time sessions before G4. `breached: false` here is not evidence.",
        })

    notes = [f"Automated session by the development module. Checks: {_summary(checks)}."]
    # A skip measured nothing: said so in its own words, whether or not it held the build up.
    skipped = [c for c in checks if c.skipped]
    if skipped:
        notes.append("Skipped, not measured: " + "; ".join(
            f"{c.id} ({c.summary}{', not passed' if c.required else ''})" for c in skipped))
    if dev_report and dev_report.get("how_to_play"):
        notes.append(f"How to play: {dev_report['how_to_play']}")
    # A design gap is a design fix, read back by title:design from `design_gaps`. It is not
    # folded in here as well: a gap buried in a session note is a note nobody acts on.
    gap_text = {gap["question"] for gap in gaps} | {gap["field"] for gap in gaps}
    for issue in (dev_report or {}).get("known_issues") or []:
        if str(issue) in gap_text:
            continue
        notes.append(f"Known issue: {issue}")
    duration = round(smoke.duration_s or 0, 1) if smoke and smoke.duration_s else 0

    if green:
        recommendation = {
            "decision": "iterate",
            "rationale": "The build is playable and passed every automated check, but it has "
                         "not been played by anyone who had not seen it. Nothing here can "
                         "support pass or abandon; that takes first-time playtests measured "
                         "against the kill criteria.",
            "if_iterate_what_changes": "Run first-time playtest sessions on this build and "
                                       "measure every kill criterion. No code change is "
                                       "known to be needed.",
        }
    else:
        recommendation = {
            "decision": "iterate",
            "rationale": "The build does not pass its checks, so it is not yet a playable "
                         "build and cannot be reviewed.",
            "if_iterate_what_changes": "Fix: " + "; ".join(
                f"{c.id} ({c.summary})" for c in checks if c.blocking),
        }

    artifact = {
        "provenance": provenance.build(
            "prototype-report",
            artifact_id=provenance.artifact_id("prototype-report", title_id, produced_at,
                                               artifact_seq),
            produced_by=provenance.producer(ROLE),
            produced_at=produced_at,
            inputs=pinned_inputs,
            schema_version=SCHEMA_VERSION,
            title_id=title_id),
        "title_id": title_id,
        "build_ref": {"commit_sha": commit_sha, "url": build_url, "built_at": built_at},
        "iteration": max(1, int(iteration)),
        "proved": proved,
        "kill_criteria_eval": kill,
        "playtest_sessions": [{
            "observer": "automation:develop",
            "player_context": "internal",
            "duration_s": duration,
            "notes": " ".join(notes),
        }],
        "integration_status": _integration(dev_report),
        "scope_deltas": _scope_deltas(dev_report, brief),
        "recommendation": recommendation,
    }
    if coverage is not None:
        artifact["content_coverage"] = coverage
    if gaps:
        artifact["design_gaps"] = gaps
    return provenance.seal(artifact)

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
"""

from wgflib import provenance

__all__ = ["build_report", "SCHEMA_VERSION", "ROLE"]

SCHEMA_VERSION = provenance.version_of("prototype-report")
ROLE = "gameplay"
_STATUSES = ("working", "partial", "not-started")
_DIRECTIONS = ("added", "cut", "deferred")


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
    green = all(not c.failed for c in checks)
    smoke = next((c for c in checks if c.id == "smoke"), None)
    evidence = (f"Built at {commit_sha[:12]}; automated checks: {_summary(checks)}. "
                "No first-time playtest has been run on this build yet.")

    questions = list((strategy or {}).get("prototype_must_prove") or brief.get("must_prove")
                     or [])
    proved = [{"question": q, "verdict": "inconclusive", "evidence": evidence}
              for q in questions]
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
                 c.id for c in checks if c.failed) + " failed."}]
    for criterion in (strategy or {}).get("kill_criteria") or []:
        kill.append({
            "criterion_id": criterion.get("id") or "unnamed",
            "measured": None,
            "breached": False,
            "note": "NOT MEASURED. Development does not playtest; this criterion needs "
                    "first-time sessions before G4. `breached: false` here is not evidence.",
        })

    notes = [f"Automated session by the development module. Checks: {_summary(checks)}."]
    if dev_report and dev_report.get("how_to_play"):
        notes.append(f"How to play: {dev_report['how_to_play']}")
    for issue in (dev_report or {}).get("known_issues") or []:
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
                f"{c.id} ({c.summary})" for c in checks if c.failed),
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
    return provenance.seal(artifact)

"""The review brief the reviewer reads, and the review-report the step emits."""

import json

from wgflib.hashing import content_hash

from .verdict import CONTRACT

__all__ = ["build_report", "render_brief", "PROMPT", "PROMPT_STDOUT", "SCHEMA_VERSION",
           "ROLE"]

SCHEMA_VERSION = "1.0.0"

# The gameplay lens: defects players feel rather than see, all visible in source. Condensed
# from core/craft/gameplay-review.md; restated here (not pointed at) because the reviewer
# runs in the game checkout, where the Factory's core/ is not a path it can rely on.
GAMEPLAY_LENS = (
    "Restart resets everything: score, timers, difficulty step, spawned entities, tweens, "
    "listeners and audio - watch for state in module-level variables or closures made once.",
    "Movement, timers and spawns scale by elapsed time, never per frame, and a long gap (a "
    "tab coming back) is clamped rather than simulated in one step.",
    "Pause - the control, tab blur, an ad - stops the simulation, tweens, timers and audio, "
    "and resume continues them; no wall-clock timers drive gameplay while paused.",
    "Rapid taps on Play or Retry cannot start two runs or two loops; pointer and touch are "
    "not both handled for one tap; listeners added per run or scene are removed on exit.",
    "Tuning (the design's mechanic parameters and difficulty values) lives in data, not as "
    "literals scattered through logic.",
    "No allocation in the frame loop's hot paths; sprites, particles and meshes are pooled "
    "or destroyed, 3D resources disposed.",
    "No effect flashes more than 3 times a second; audio starts only after a user gesture "
    "and respects mute.",
    "Unit tests exercise the design's rules; a browser test tagged with an aspect actually "
    "reaches it (a `@game-over` test that never loses is not evidence).",
)


def _feedback_lines(build_spec):
    """The mvp feedback the design specified: what the player must be able to notice."""
    sections = (build_spec or {}).get("sections") or {}
    lines = []
    for section in ("rewards", "hud"):
        for entry in sections.get(section) or []:
            if isinstance(entry, dict) and entry.get("feedback"):
                lines.append(f"{section} `{entry.get('id')}`: {entry['feedback']}")
    failure = sections.get("failure")
    if isinstance(failure, dict) and failure.get("feedback"):
        lines.append(f"failure: {failure['feedback']}")
    tutorial = sections.get("tutorial")
    if isinstance(tutorial, dict) and tutorial.get("approach"):
        lines.append(f"tutorial: {tutorial['approach']}"
                     + (f" - {tutorial['rationale']}" if tutorial.get("rationale") else ""))
    return lines
# The architect contributes to title:prototype and owns the plan the code is reviewed
# against; the reviewer is never the gameplay implementer that wrote the commit.
ROLE = "architect"

PROMPT = (
    "You are the code reviewer for this game repository, not its developer. Read {brief} in "
    "full, then review commit {commit} in {repo}. You are READ-ONLY: do not edit, create, "
    "delete, stage or commit any file in the repository, do not install packages and do not "
    "run anything that writes into it - any change fails the review and is undone. Write "
    "your verdict, and nothing else, as JSON to {verdict}, exactly in the shape the brief "
    "gives."
)

PROMPT_STDOUT = (
    "You are the code reviewer for this game repository, not its developer. Read {brief} in "
    "full, then review commit {commit} in {repo}. You are READ-ONLY: do not edit, create, "
    "delete, stage or commit any file, do not install packages and do not run anything that "
    "writes into the repository - any change fails the review and is undone. End your "
    "answer with your verdict as one JSON object, exactly in the shape the brief gives."
)


def render_brief(*, title_id, commit, baseline, design, prototype, develop_brief,
                 verdict_path, repo, to_stdout=False):
    design = design or {}
    prototype = prototype or {}
    develop_brief = develop_brief or {}
    tiers = (design.get("scope") or {}).get("tiers") or {}
    out = []
    add = out.append
    add(f"# Review brief: {title_id} at {commit[:12]}\n")
    add("Written by the Factory's review module. You review; you do not fix.\n")
    add("## What to review\n")
    add(f"- Repository: `{repo}` (read-only)")
    add(f"- Commit under review: `{commit}`")
    if baseline and baseline != commit:
        add(f"- The change: `git diff {baseline}..{commit}` "
            f"(`git log --stat {baseline}..{commit}`)")
    add("- What the developer was asked to build: `docs/development/brief.md` in the "
        "repository, and what it reported: `docs/development/report.json`. The whole "
        "design, rendered for reading: `docs/GDD.md`.")
    add("")
    if design.get("core_loop"):
        add("## The game\n")
        add(f"Core loop: {design.get('core_loop')}\n")
    if tiers.get("mvp"):
        add("MVP:\n")
        add("\n".join(f"- {item}" for item in tiers["mvp"]) + "\n")
    checks = [s for s in prototype.get("proved") or []]
    if checks:
        add("## What development measured\n")
        for entry in checks:
            add(f"- {entry.get('question')}: {entry.get('verdict')}")
        add("")
    previous = develop_brief.get("review_blockers") or []
    if previous:
        add("## Blockers the previous review raised\n")
        add("This commit was asked to fix these. Check each one; a blocker that is still "
            "there is still a blocker.\n")
        for blocker in previous:
            add(f"- `{blocker.get('id')}` ({blocker.get('severity')}) "
                f"{blocker.get('file') or '(whole build)'}: {blocker.get('summary')}")
        add("")
    feedback = _feedback_lines(develop_brief.get("build_spec"))
    tasks = [t for t in ((develop_brief.get("dev_plan") or {}).get("tasks") or [])
             if isinstance(t, dict)]
    if feedback or tasks:
        add("## What the design and plan specified\n")
        add("From the brief the developer built against (`docs/development/brief.json`, "
            "`build_spec` and `dev_plan`). Check the build against them: a missing feedback "
            "hook, or an acceptance criterion an mvp task does not meet, is a design-fidelity "
            "blocker.\n")
        if feedback:
            add("Feedback and teaching the player must be able to notice:\n")
            add("\n".join(f"- {line}" for line in feedback) + "\n")
        if tasks:
            add("Development plan tasks and their acceptance criteria:\n")
            for task in tasks:
                add(f"- `{task.get('id')}` {task.get('title', '')}: "
                    + "; ".join(task.get("acceptance_criteria") or []))
            add("")
    add("## Look for\n")
    add("- Defects in the game logic: wrong rules, broken state transitions, crashes, "
        "unhandled input, restart that does not reset.")
    add("- Anything the brief required that is missing, stubbed or faked, and tests that "
        "assert nothing.")
    add("- Template rules broken: edited template-owned paths, a second engine, a portal "
        "SDK called directly instead of through the integration seam.")
    add("- Secrets, network calls to unknown hosts, or code unrelated to the game.\n")
    add("### Gameplay lens\n")
    add("Defects players report as \"laggy\", \"unfair\" or \"it froze after the ad\". "
        "You cannot play the build; each of these is visible in source. On an mvp path a "
        "failure is a blocker; elsewhere it is at most minor.\n")
    add("\n".join(f"- {item}" for item in GAMEPLAY_LENS) + "\n")
    add("Style preferences are not blockers. A blocker is something that must change "
        "before this build goes further.\n")
    add("## Your verdict\n")
    if to_stdout:
        add("End your output with exactly one JSON object - your verdict. Write no file:\n")
    else:
        add(f"Write exactly one JSON object to `{verdict_path}` - outside the repository:\n")
    add("```json\n" + json.dumps(CONTRACT, indent=2) + "\n```\n")
    add("- `approve` with an empty `blockers` list, or `request-changes` with at least one "
        "blocker. Nothing in between: an approval with blockers is rejected.")
    add(f"- `commit` is `{commit}`, verbatim.")
    add("- `severity` is one of blocker, critical, major, minor. `file` is relative to the "
        "repository, or null for a finding about the build as a whole. `line` is optional.")
    add("- No other keys. A malformed verdict is discarded, never read as an approval.")
    return "\n".join(out) + "\n"


def build_report(*, title_id, commit, baseline, verdict, blockers, notes, failure,
                 reviewer, isolation, iteration, attempt, duration_s, timed_out,
                 pinned_inputs, artifact_seq, produced_at):
    artifact = {
        "provenance": {
            "artifact_id": f"wgf:review-report:{title_id}:"
                           f"{produced_at[:10].replace('-', '')}-{min(artifact_seq, 99):02d}",
            "artifact_type": "review-report",
            "schema_version": SCHEMA_VERSION,
            "title_id": title_id,
            "produced_by": {"role": ROLE, "actor": "ai" if reviewer.get("kind") == "command"
                            else "automation"},
            "produced_at": produced_at,
            "inputs": pinned_inputs,
            "content_hash": "",
            "status": "draft",
        },
        "title_id": title_id,
        "reviewed_commit": commit,
        "baseline_commit": baseline,
        "verdict": verdict,
        "blockers": blockers,
        "failure": failure,
        "reviewer": reviewer,
        "isolation": isolation,
        "iteration": max(1, int(iteration)),
        "attempt": max(1, int(attempt)),
        "duration_s": round(max(0.0, float(duration_s)), 3),
        "timed_out": bool(timed_out),
        "reviewed_at": produced_at,
    }
    if notes:
        artifact["notes"] = notes
    artifact["provenance"]["content_hash"] = content_hash(artifact)
    return artifact

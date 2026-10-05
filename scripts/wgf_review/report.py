"""The review brief the reviewer reads, and the review-report the step emits."""

import json

from wgflib import provenance

from .verdict import CONTRACT

__all__ = ["build_report", "render_brief", "verify_failure", "PROMPT", "PROMPT_STDOUT",
           "SCHEMA_VERSION", "ROLE"]

SCHEMA_VERSION = provenance.version_of("review-report")

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
    "Every mvp content unit of the brief's content table exists: its id is in "
    "`public/content/units.json`, and the code reaches it from the previous unit by playing - "
    "no unit only a debug jump or a URL parameter can enter.",
    "Every mechanic rule in the brief is implemented as a rule with a unit test, and each "
    "unit's difficulty values are read from the data file rather than re-typed or recomputed "
    "in logic.",
    "Gaps are reported, not filled in: a unit, mechanic or rule the brief asked for and the "
    "commit does not deliver belongs in `design_gaps` in `docs/development/report.json`. One "
    "the commit invented instead of the designed one is a design-fidelity blocker.",
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


def _content_block(develop_brief):
    """(the content contract, the difficulty axes, the mastery block) the developer was given.

    The brief carries the design's `build_spec` section by section; some briefs also carry the
    content table at the top level. Read both, prefer the explicit one.
    """
    spec = develop_brief.get("build_spec") or {}
    sections = spec.get("sections") or {}
    content = develop_brief.get("content") or sections.get("content") or {}
    difficulty = sections.get("difficulty") or {}
    return (content if isinstance(content, dict) else {},
            [a for a in (difficulty.get("axes") or []) if isinstance(a, dict)],
            sections.get("mastery") if isinstance(sections.get("mastery"), dict) else None)


def _design_fidelity(develop_brief, prototype, develop_report):
    """The lines of the brief's `## Design fidelity` section; [] when there is nothing to show.

    The content the developer was asked to build, unit by unit, beside what the development
    report says it built and where the design did not say enough (`design_gaps`). A reviewer
    reading only the code cannot tell an invented unit from a designed one; this is what makes
    that visible.
    """
    content, axes, mastery = _content_block(develop_brief)
    units = [u for u in content.get("units") or [] if isinstance(u, dict)]
    report = develop_report or {}
    gaps = [g for g in (report.get("design_gaps") or prototype.get("design_gaps") or [])
            if isinstance(g, dict)]
    built = {u.get("id"): u for u in (report.get("content_units") or []) if isinstance(u, dict)}
    coverage = prototype.get("content_coverage") if isinstance(
        prototype.get("content_coverage"), dict) else None
    if not (units or axes or mastery or gaps or coverage):
        return []
    experience = ((develop_brief.get("build_spec") or {}).get("sections") or {}).get("experience") \
        or {}
    out = ["## Design fidelity\n",
           "What the design committed this build to contain. A unit, mechanic or rule the "
           "commit does not deliver, or delivers as something else, is a design-fidelity "
           "blocker - not a style note.\n"]
    if content.get("unit_kind") or content.get("generation"):
        mode = (content.get("generation") or {}).get("mode")
        out.append(f"Content: {len(units)} mvp {content.get('unit_kind') or 'unit'}(s), "
                   f"generation `{mode or 'not stated'}`"
                   + (" - every listed unit is built as data"
                      if mode == "authored" else
                      " - the listed units are the segments the design commits to") + ".\n")
    if units:
        out.append("| unit | purpose | objective | mechanics | difficulty | built |")
        out.append("|---|---|---|---|---|---|")
        for entry in units:
            uid = entry.get("id")
            state = (built.get(uid) or {}).get("status") or next(
                (u.get("status") for u in ((coverage or {}).get("units") or [])
                 if isinstance(u, dict) and u.get("id") == uid), "not reported")
            difficulty = ", ".join(f"{k} {v}" for k, v in
                                   sorted((entry.get("difficulty") or {}).items()))
            out.append(f"| `{uid}` | {entry.get('purpose', '')} | "
                       f"{str(entry.get('objective', '')).replace('|', '/')} | "
                       f"{', '.join(entry.get('mechanics') or [])} | {difficulty} | {state} |")
        out.append("")
        out.append("Per-unit acceptance - each line must be true of the built unit:\n")
        for entry in units:
            out.append(f"- `{entry.get('id')}`: "
                       + "; ".join(entry.get("acceptance") or ["(none stated)"]))
            if entry.get("variation_from_previous"):
                out.append("  - differs from the previous unit in: "
                           + ", ".join(entry["variation_from_previous"]))
        out.append("")
    if axes:
        out.append("Difficulty axes (the values above are on these, and live in the data file, "
                   "not in logic):\n")
        for axis in axes:
            out.append(f"- `{axis.get('id')}` {axis.get('range')}: "
                       f"{axis.get('description', '')}"
                       + ("; relief dips allowed" if axis.get("relief_allowed") else ""))
        out.append("")
    win, lose = experience.get("win"), experience.get("lose")
    if win or lose:
        out.append("Win and loss, as the design states them:\n")
        if win:
            out.append(f"- win: {win.get('condition')} (metric `{win.get('metric')}`)")
        if lose:
            out.append(f"- loss: {lose.get('condition')} (metric `{lose.get('metric')}`)")
        out.append("")
    if mastery:
        out.append(f"Mastery ({mastery.get('model')}): {mastery.get('statement')} - shown in "
                   f"{', '.join(mastery.get('signals') or [])}\n")
    if coverage:
        out.append(f"Content coverage reported by development: {coverage.get('built')} built, "
                   f"{coverage.get('partial', 0)} partial, {coverage.get('cut')} cut of "
                   f"{coverage.get('designed')} designed.\n")
    if gaps:
        out.append("Design gaps the developer reported - what the design did not decide, and "
                   "what was assumed instead. Check the assumption against the code; an "
                   "assumption the code does not match is a blocker:\n")
        for gap in gaps:
            out.append(f"- ({gap.get('severity')}) `{gap.get('field')}`: {gap.get('question')} "
                       f"-> assumed: {gap.get('assumed') or 'nothing; the work stopped'}")
        out.append("")
    elif units:
        out.append("The development report lists no design gaps: every unit, mechanic and rule "
                   "above was buildable as written. A place where the code had to decide "
                   "something the design did not say, and no gap was reported, is a finding.\n")
    return out
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

# How much of a defect's repro the brief quotes: enough to see the failure, not the log.
REPRO_LIMIT = 600


def verify_failure(qa, run_id, develop_brief=None):
    """What the reviewer is told when the run is inside a loop verify's failure started.

    Verify runs after review and sdk-review approve, so once it fails, every review until it
    runs again reads a commit nobody can have verified yet - and a reviewer not told so asks
    for the one thing no commit can carry: verify's pass. `qa` is the newest qa-report the
    run gave the step. It applies only when it is a fail of this run: a run's inputs are its
    own artifacts, so a report that names no run (a placeholder's) counts, and one whose
    `workflow` names another run does not. A pass, another run's report or none at all means
    no verify failure is open, and the brief says nothing. `develop_brief`'s `loop` names how
    development was re-entered (`verify.fail`, or a later `review.request-changes`), when it
    says."""
    if not isinstance(qa, dict) or qa.get("verdict") != "fail":
        return None
    workflow = qa.get("workflow") or {}
    if workflow.get("run_id") and workflow.get("run_id") != run_id:
        return None
    loop = (develop_brief or {}).get("loop") or {}
    return {
        "commit": (qa.get("build_ref") or {}).get("commit_sha"),
        "evidence_status": qa.get("evidence_status"),
        "visit": workflow.get("visit"),
        "entered_by": loop.get("entered_by") if isinstance(loop, dict) else None,
        "defects": [{k: d.get(k) for k in ("id", "severity", "summary", "repro")
                     if d.get(k) is not None}
                    for d in qa.get("blocking_defects") or [] if isinstance(d, dict)],
    }


def _verify_failure_lines(failure):
    """The brief's `## Verify failed on an earlier commit` section; [] when none is open."""
    if not failure:
        return []
    out = []
    add = out.append
    commit = failure.get("commit") or ""
    visit = f", verify visit {failure['visit']}" if failure.get("visit") else ""
    add("## Verify failed on an earlier commit\n")
    line = (f"Verification failed `{commit[:12] or 'unknown'}` in this run (its qa-report"
            f"{visit}), and the run has not verified since.")
    if failure.get("entered_by"):
        line += f" Development was re-entered through `{failure['entered_by']}`."
    add(line)
    add("Verify runs again only after this review (and the sdk review) approve. No commit "
        "can show a verify pass before you decide, so never request changes because verify "
        "has not passed this commit, or because its failures are \"unproven\" until it does. "
        "Judge the code.\n")
    status = failure.get("evidence_status")
    if status in ("UNVERIFIED", "BLOCKED_EXTERNAL"):
        add(f"Recorded cause: verify could not establish these checks (evidence status "
            f"`{status}`). The cause it recorded is outside the game - the environment it "
            f"ran in, its harness or an external service - not a defect it showed.\n")
    elif status == "FAIL":
        add("Recorded cause: verify saw these checks fail (evidence status `FAIL`). It "
            "records no attribution: whether the game or the environment verify ran in (its "
            "harness, a timeout, a port, its worker count) is responsible is not recorded. "
            "The developer's account, if it gave one, is `known_issues` in "
            "`docs/development/report.json` - a claim to check, not evidence.\n")
    else:
        add("Recorded cause: none - the qa-report carries no evidence status.\n")
    defects = failure.get("defects") or []
    if defects:
        add("Failing checks:\n")
        for defect in defects:
            add(f"- `{defect.get('id')}` ({defect.get('severity')}) {defect.get('summary')}")
            repro = str(defect.get("repro") or "")
            if repro:
                if len(repro) > REPRO_LIMIT:
                    repro = repro[:REPRO_LIMIT].rstrip() + " ..."
                add(f"  Repro: {repro}")
        add("")
    add("- A failure whose cause you can find in the source - a rule, a state transition, a "
        "pause or a timer, a test that cannot pass against the design - is a blocker. Name "
        "the file, and the line where you can.")
    add("- A failure you cannot connect to anything in the code - a timeout, a port, a "
        "harness or environment problem - is not a blocker of this commit. Say in `notes` "
        "what you read and why you found no cause in the code; verify judges it again after "
        "your approval.")
    add("- A commit that changes no game code after a verify failure is not a defect by "
        "itself. It is one only when a failure above has a cause in the code that is still "
        "there.")
    add("- Everything else in this brief applies unchanged: a defect you find is a blocker "
        "whether or not verify saw it.\n")
    return out


def _gaming_lines(gaming):
    """The brief's `## Gate gaming` section: every specialist commit of the change, its hunks
    classified by the pre-check, the flags already raised, the declared changes the reviewer
    judges, and how to report what the pre-check cannot see. [] when the change holds no
    specialist commit."""
    visits = (gaming or {}).get("commits") or []
    if not visits:
        return []
    out = ["## Gate gaming\n",
           "A specialist visit is routed gate findings, each accepted when the gate measures the "
           "next build. Its cheapest pass is a change to what the gate MEASURES instead of the "
           "game: the play area shrunk so the bot reaches a unit in time, colliders hidden or "
           "undrawn, a sprite drawn larger than the collider it keeps, fields added to content "
           "data that no code reads, a probe-, showcase- or bot-only path. The player feels "
           "none of it. The Factory's deterministic pre-check (`"
           + str(gaming.get("vocabulary")) + "`) read these commits first.\n"]
    for visit in visits:
        out.append(f"### {visit['commit'][:12]}: a `{visit.get('owner')}` visit\n")
        out.append("Routed for: " + (", ".join(f"`{f}`" for f in visit.get("findings") or [])
                                     or "(no findings recorded)") + ".\n")
        shown = [h for h in visit.get("hunks") or [] if h["class"] != "bookkeeping"]
        if shown:
            out.append("| file | hunk at | class | why |")
            out.append("|---|---|---|---|")
            for hunk in shown[:60]:
                out.append(f"| `{hunk['file']}` | {hunk['hunk']} | {hunk['class']} | "
                           f"{', '.join(hunk['reasons']) or ''} |")
            if len(shown) > 60:
                out.append(f"| ... | | | {len(shown) - 60} more hunks |")
            out.append("")
        flagged = [f for f in visit.get("flags") or [] if f.get("status") == "flagged"]
        if flagged:
            out.append("Flagged - already blockers of this review, whatever you decide; you "
                       "need not repeat them:\n")
            for flag in flagged:
                out.append(f"- `{flag['pattern']}` `{flag['file']}`: {flag['detail']}")
            out.append("")
        declared = [f for f in visit.get("flags") or [] if f.get("status") == "declared"]
        if declared:
            out.append("Declared by the developer in `docs/development/report.json` "
                       "`measurement_changes`, with evidence the commit holds. Judge each: "
                       "unless the evidence shows the player experiences the change, it is a "
                       "blocker (id starting `gate-gaming-`):\n")
            for flag in declared:
                entry = flag.get("declaration") or {}
                out.append(f"- `{flag['pattern']}` `{flag['file']}`: {flag['detail']}")
                out.append(f"  - Player effect, as declared: {entry.get('player_effect')}")
                for ref in entry.get("evidence") or []:
                    out.append(f"  - Evidence `{ref['file']}:{ref['line']}`: `{ref['text']}`")
            out.append("")
        skipped = visit.get("skipped") or {}
        if skipped:
            out.append("Not checked here: " + "; ".join(
                f"`{k}` ({v})" for k, v in sorted(skipped.items())) + ".\n")
    out.append("Read every hunk marked player-facing as well: the pre-check knows words, not "
               "intent. A change that alters what a gate reads without changing what the "
               "player experiences - space, bounds or colliders moved to meet a time or reach "
               "bar, a drawn size without the physical size, data the game never reads, a "
               "branch only the probe or bot takes - is a blocker. Give it an id starting "
               "`gate-gaming-`, so it goes back to the specialist that made it. A legitimate "
               "change to the play area, a size or the probe - one the design asks for, with "
               "the player-facing effect in the code - is not.\n")
    return out


PROMPT_STDOUT = (
    "You are the code reviewer for this game repository, not its developer. Read {brief} in "
    "full, then review commit {commit} in {repo}. You are READ-ONLY: do not edit, create, "
    "delete, stage or commit any file, do not install packages and do not run anything that "
    "writes into the repository - any change fails the review and is undone. End your "
    "answer with your verdict as one JSON object, exactly in the shape the brief gives."
)


def render_brief(*, title_id, commit, baseline, design, prototype, develop_brief,
                 verdict_path, repo, to_stdout=False, sdk=None, develop_report=None,
                 verify_failure=None, gaming=None):
    """`sdk` is the sdk-report when the commit under review is the sdk step's (subject
    sdk-report): the change is then the platform integration on top of `baseline`, the
    development commit an earlier review read. `develop_report` is the developer's own
    `docs/development/report.json`, whose `content_units` and `design_gaps` say what it built
    and where the design was silent; the prototype-report carries the same fields and stands in
    for it. `verify_failure` (from `verify_failure()`) is the open verify failure the run is
    looping on, when there is one: the reviewer is shown its failing checks and recorded cause
    and told verify re-runs only after it approves. `gaming` is the gate-gaming pre-check
    (wgf_review.gaming.precheck_range) over the change's specialist commits."""
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
    if sdk is not None:
        add("- This is the platform SDK integration the Factory's sdk step committed on top "
            f"of the development commit `{baseline or 'unknown'}`. This commit is the one that "
            "is verified and shipped. Review the integration and whether it changed the game.")
        platforms = [p.get("platform_id") for p in sdk.get("platforms") or []
                     if isinstance(p, dict) and p.get("platform_id")]
        if platforms:
            add(f"- Platforms integrated: {', '.join(platforms)}")
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
    out += _verify_failure_lines(verify_failure)
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
    out += _design_fidelity(develop_brief, prototype, develop_report)
    out += _gaming_lines(gaming)
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
    add("- `severity` is one of blocker, critical, major, minor. Every blocker has `file`: "
        "relative to the repository, or null for a finding about the build as a whole - "
        "never left out. `line` is optional: a positive line number, or omitted.")
    add("- No other keys. A malformed verdict is discarded, never read as an approval.")
    return "\n".join(out) + "\n"


def build_report(*, title_id, commit, baseline, verdict, blockers, notes, failure,
                 reviewer, isolation, iteration, attempt, duration_s, timed_out,
                 pinned_inputs, artifact_seq, produced_at, gate_gaming=None):
    artifact = {
        "provenance": provenance.build(
            "review-report",
            artifact_id=provenance.artifact_id("review-report", title_id, produced_at,
                                               artifact_seq),
            produced_by=provenance.producer(
                ROLE, "ai" if reviewer.get("kind") == "command" else "automation"),
            produced_at=produced_at,
            inputs=pinned_inputs,
            schema_version=SCHEMA_VERSION,
            title_id=title_id),
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
    if gate_gaming:
        artifact["gate_gaming"] = gate_gaming
    return provenance.seal(artifact)

"""A develop visit briefed as a specialist: the findings triage routed, and only those.

The triage step (scripts/wgf_triage, docs/specialist-routing.md) groups the current build's
quality findings by the specialist that owns each dimension and returns one group's label;
the workflow maps a specialist's label to develop, so the visit is entered as
`triage.<role>`. This module turns that entry and the triage-report into what the visit
needs:

    resolve(context, inputs, phase)  -> the specialist (or None), or a problem
    narrow(writable, scope)          -> the installation's writable paths, cut to the
                                        specialist's scope (roles.yaml `writes`): never wider
    visit_cost(context)              -> (sessions, cost) this visit's developer sessions spent
    render(specialist)               -> the brief's section: focus, findings, acceptance

The specialist's data - focus, craft playbooks, writable scope - is the triage-report's and
core/roles/roles.yaml's, read through wgf_triage.routing; nothing here names a role.
"""

import os

from . import budget as budgets

__all__ = ["resolve", "narrow", "visit_cost", "render", "NEXT_SPECIALIST"]

# The route a specialist visit returns while the triage that routed it has groups pending
# (the workflow maps it back to triage: wgf_triage.NEXT_SPECIALIST).
NEXT_SPECIALIST = "next-specialist"
TRIAGE_SOURCE = "triage"


def _factory_path(relative):
    from wgflib import paths
    return os.path.join(paths.ROOT, *relative.split("/"))


def resolve(context, inputs, phase):
    """(specialist dict, None), (None, None) when this visit is not a specialist's, or
    (None, problem) when it was routed as one and the triage-report does not say so."""
    entered = getattr(context, "entered_by", None) or ""
    source, _, label = entered.rpartition(".")
    if phase == "greybox" or source != TRIAGE_SOURCE or label in ("", "success"):
        return None, None
    triage = inputs.load("triage-report") if "triage-report" in inputs else None
    selected = (triage or {}).get("selected") if isinstance(triage, dict) else None
    if not isinstance(selected, dict) or selected.get("label") != label:
        return None, (f"develop was entered as `{entered}`, but the run's newest "
                      f"triage-report routes {((selected or {}).get('label'))!r}: the "
                      f"specialist's findings cannot be established")
    from wgf_triage.routing import Routing  # the routing data's reader, not a copy of it
    routing = Routing.load()
    role = selected.get("owner")
    spec = routing.specialist(role)
    wanted = list(selected.get("findings") or [])
    by_id = {f.get("id"): f for f in triage.get("findings") or [] if isinstance(f, dict)}
    findings = [_with_paths(by_id[fid], getattr(context, "run_dir", None))
                for fid in wanted if fid in by_id]
    ref = inputs.refs.get("triage-report")
    design = inputs.load("game-design") if "game-design" in inputs else {}
    strategy = inputs.load("title-strategy") if "title-strategy" in inputs else {}
    return {
        "role": role,
        "label": spec["label"],
        "focus": spec["focus"],
        "playbooks": list(selected.get("playbooks") or spec["reads"]),
        "writes": list(selected.get("writable_paths") or spec["writes"]),
        "findings": findings,
        "pending": [g.get("owner") for g in triage.get("pending") or []
                    if isinstance(g, dict)],
        "source": triage.get("source"),
        "mode": triage.get("mode"),
        "triage_report": ((triage.get("provenance") or {}).get("artifact_id")
                          or getattr(ref, "id", None)),
        "context": _context(triage, wanted, design or {}, strategy or {}, inputs),
    }, None


def _context(triage, mine, design, strategy, inputs):
    """What every specialist brief carries besides its findings, from one source each: the
    game brief, the design contract, the quality budget and floor, the run's other open
    findings (not this visit's to fix, not to be made worse) and the regression constraints
    (the findings already verified or closed, which must stay fixed)."""
    from wgflib import paths
    from wgflib.yamllite import load_file
    from wgf_triage.lifecycle import DONE
    concept = (strategy.get("concept") or {}).get("content_model") or {}
    tier = concept.get("quality_tier") or "release"
    floor = {"reference": "core/reference/quality-benchmark.yaml", "tier": tier}
    path = os.path.join(paths.REFERENCE, "quality-benchmark.yaml")
    if tier == "release" and os.path.isfile(path):
        benchmark = load_file(path) or {}
        floor["version"] = str(benchmark.get("version") or "")
        floor["presentation"] = benchmark.get("presentation")
    design_ref = inputs.refs.get("game-design")
    lifecycle = [r for r in triage.get("lifecycle") or [] if isinstance(r, dict)]
    return {
        "game_brief": design.get("brief") or strategy.get("brief")
        or strategy.get("one_liner"),
        "design_contract": {
            "artifact_id": (design.get("provenance") or {}).get("artifact_id"),
            "content_hash": getattr(design_ref, "content_hash", None),
            "rendered_to": "docs/GDD.md"},
        "quality_budget": ({"tier": tier, "budget": concept.get("budget")}
                           if concept.get("budget") or concept.get("quality_tier") else None),
        "quality_floor": floor,
        "open_findings": [
            {"id": r["id"], "owner": r.get("owner"), "status": r.get("status"),
             "summary": r.get("summary")}
            for r in lifecycle if r.get("status") not in DONE and r["id"] not in mine],
        "regression_constraints": [
            {"id": r["id"], "status": r.get("status"), "summary": r.get("summary")}
            for r in lifecycle if r.get("status") in DONE],
    }


def _with_paths(finding, run_dir):
    """The finding with each evidence frame a gate recorded relative to the run directory
    made absolute: the developer works in the checkout, where a run path names nothing."""
    refs = []
    for ref in finding.get("evidence_refs") or []:
        if (run_dir and isinstance(ref, str) and not os.path.isabs(ref)
                and not ref.startswith("artifact:")
                and os.path.exists(os.path.join(run_dir, ref))):
            ref = os.path.join(run_dir, ref)
        refs.append(ref)
    return dict(finding, evidence_refs=refs)


def narrow(writable, scope):
    """The writable paths a specialist visit may commit: each installation path the
    specialist's scope covers, or the narrower scope entry inside it. A directory ends in
    '/', anything else is one exact file. Never a path the installation does not allow."""
    out = []
    for allowed in writable:
        for wanted in scope:
            if wanted == allowed or (allowed.endswith("/") and wanted.startswith(allowed)):
                pick = wanted
            elif wanted.endswith("/") and allowed.startswith(wanted):
                pick = allowed
            else:
                continue
            if pick not in out:
                out.append(pick)
    return out


def visit_cost(context):
    """(sessions, cost) of this visit's developer sessions, every attempt, from the run's
    event log (wgf_develop.budget): cost None when any session's is unknown or none was
    recorded."""
    reader = getattr(context, "read_events", None)
    events = list(reader()) if callable(reader) else []
    step = getattr(context, "current_step", None)
    nonces, costs = set(), {}
    for event in events:
        data = event.get("data") or {}
        if step and event.get("step_id") not in (None, step):
            continue
        if data.get("budget") == budgets.SESSION and data.get("visit") == context.visit:
            nonces.add(data.get("nonce"))
        elif data.get("budget") == budgets.COST:
            costs[data.get("nonce")] = data.get("cost")
    if not nonces:
        return 0, None
    known = [costs.get(n) for n in nonces]
    if any(not isinstance(c, (int, float)) or c < 0 for c in known):
        return len(nonces), None
    return len(nonces), round(float(sum(known)), 6)


def _inline(value, limit=400):
    import json
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False,
                                                          sort_keys=True)
    return text if len(text) <= limit else text[:limit] + " ..."


def _gaming_rules(vocabulary):
    """The brief's rules against meeting a bar by changing what the gate measures
    (core/reference/gate-gaming.yaml), and the one way to declare a change that only looks
    like it."""
    field = (vocabulary.data.get("declaration") or {}).get("field") or "measurement_changes"
    lines = ["### Change the game, not its measurement\n",
             "Each finding closes when its gate measures the next build. Meet it by changing "
             "what the player experiences; a pass the player cannot feel is not a fix. The "
             "review reads every hunk of this visit's commit, classifies it player-facing or "
             "measurement-facing, and sends a measurement-facing change back to this "
             "discipline as a blocker.\n"]
    lines.extend(f"- {rule}" for rule in vocabulary.rules)
    lines.append("")
    lines.append("The review flags, deterministically: a field added to content data that "
                 "game source never reads; play-area, bounds or collider changes in a visit "
                 "routed for reach, time or visibility; probe-, showcase- or bot-only code "
                 "changed for findings about the game; a drawn size changed - a draw constant, "
                 "a draw size scaled from a collider, an asset frame or an image file made "
                 "larger - without a collider or physical size of the same entity. If such a "
                 "change is what the player experiences - the design asks for a smaller "
                 "arena, a field is read through an alias - "
                 f"declare it in the report's `{field}`: "
                 '`{"flag": "<pattern>", "where": "<file or file#key>", "evidence": '
                 '[{"file": "src/...", "line": 12}], "player_effect": "<what the player '
                 'sees or does differently>"}`. `where` names the flagged file (or file#key). '
                 "Evidence counts only where this commit changed the game: a line of the "
                 "flagged file inside the flagged change, or a line of game source this commit "
                 "touched; for an unread field, a game-source line this commit touched that "
                 "reads it clears the flag. A declaration without such evidence changes "
                 "nothing.\n")
    return lines


def render(specialist):
    """The brief's specialist section, as markdown lines."""
    lines = [f"## This visit: {specialist['label']}\n",
             f"You work this visit as the **{specialist['label']}** "
             f"(`{specialist['role']}`). {specialist['focus']}\n",
             "The findings below are the ones this discipline owns, from the gates that "
             "judged the current build"
             + (f" (`{specialist['source']}`)" if specialist.get("source") else "")
             + ". Fix these and only these: findings another discipline owns are routed to "
               "it in its own visit, before the gates measure the build again. Each is "
               "accepted the way its acceptance says - by the gate that raised it, "
               "re-measuring the next build - so change what that gate measures, not its "
               "report.\n"]
    if specialist.get("pending"):
        lines.append("After you: " + ", ".join(f"`{p}`" for p in specialist["pending"])
                     + " - leave their findings to them.\n")
    from wgf_review.gaming import Vocabulary  # the shared vocabulary, not a copy of it
    vocabulary = Vocabulary.load()
    lines.append("### Your findings\n")
    for finding in specialist["findings"]:
        source = finding.get("source") or {}
        where = source.get("producer") or "?"
        if source.get("project"):
            where += f", {source['project']}"
        lines.append(f"- `{finding['id']}` ({finding.get('severity')}, "
                     f"{finding.get('dimension')}; {where}): {finding.get('summary')}")
        if finding.get("measured") is not None:
            lines.append(f"  - Measured: {_inline(finding['measured'])}")
        if finding.get("bar") is not None:
            lines.append(f"  - Bar: {_inline(finding['bar'])}")
        task = finding.get("task") or {}
        lines.append(f"  - Change: {task.get('change')}")
        for line in task.get("acceptance") or []:
            lines.append(f"  - Accepted when: {line}")
        evidence = [f"`{ref}`" for ref in finding.get("evidence_refs") or []]
        if evidence:
            lines.append("  - Evidence: " + ", ".join(evidence))
        for rule in vocabulary.rules_for(finding):
            lines.append(f"  - Not a fix: {rule}")
        for guard in finding.get("guarded_by") or []:
            level = f", {guard['level']} rule" if guard.get("level") else ""
            lines.append(f"  - Known lesson {guard.get('lesson')}{level}: held by "
                         f"`{guard.get('check')}` ({guard.get('status')}) - a failure the "
                         "Factory has seen before; fix the cause, not the check")
    lines.append("")
    lines.extend(_gaming_rules(vocabulary))
    lines.append("### Leave what you learned\n")
    lines.append("If a finding shows a systemic issue - a class of defect the Factory's gates "
                 "or this brief let through, that will recur in other games - record it in "
                 "report.json `lesson_candidates`: the lesson stated so it is true of any "
                 "game, its root cause in the Factory, and the check that would hold it. It "
                 "is shown to the person deciding G4, who adds it to the Factory's lessons "
                 "or not. Omit it for a defect that is only this build's.\n")
    lines.append("### Your craft playbooks\n")
    lines.append("Read these before you change anything - they are this discipline's bar. "
                 "They are outside this repository: open them by these absolute paths.\n")
    for playbook in specialist["playbooks"]:
        lines.append(f"- `{_factory_path(playbook)}`")
    lines.append("")
    context = specialist.get("context") or {}
    lines.append("### What every specialist works within\n")
    lines.append("One source each; the sections of this brief below hold the rest.\n")
    if context.get("game_brief"):
        lines.append(f"- **Game brief:** {context['game_brief']}")
    contract = context.get("design_contract") or {}
    lines.append(f"- **Design contract:** the game-design "
                 f"{contract.get('artifact_id') or ''} "
                 f"({(contract.get('content_hash') or '')[:19]}), rendered to "
                 f"`{contract.get('rendered_to') or 'docs/GDD.md'}`, and its build_spec below. "
                 "A finding that needs more than the design states is not yours to invent: "
                 "say so in `design_gaps`.")
    budget = context.get("quality_budget")
    if budget:
        lines.append(f"- **Quality budget** (tier `{budget.get('tier')}`): "
                     f"{_inline(budget.get('budget')) if budget.get('budget') else 'the MVP'}")
    floor = context.get("quality_floor") or {}
    lines.append(f"- **Quality floor:** `{floor.get('reference')}` tier `{floor.get('tier')}`"
                 + (f": {_inline(floor.get('presentation'), 600)}"
                    if floor.get("presentation") else ""))
    lines.append("- **Acceptance:** each finding above says how it is accepted; the tasks "
                 "below carry theirs. A finding closes only when the gate that raised it "
                 "measures the next build - never on your report.")
    opened = context.get("open_findings") or []
    if opened:
        lines.append("- **Other open findings** (not yours this visit - do not work on them, "
                     "do not make them worse): " + "; ".join(
                         f"`{f['id']}` ({f.get('owner')}, {f.get('status')})"
                         for f in opened[:20])
                     + (f"; and {len(opened) - 20} more" if len(opened) > 20 else ""))
    fixed = context.get("regression_constraints") or []
    lines.append("- **Regression constraints:** every gate that passed the current build "
                 "must still pass the next one; a fix that makes another gate fail is not "
                 "verified."
                 + (" These findings are fixed and must stay fixed: " + "; ".join(
                     f"`{f['id']}`" for f in fixed[:20]) if fixed else ""))
    lines.append("")
    lines.append("### Your writable scope\n")
    lines.append("This visit may commit only " + ", ".join(
        f"`{p}`" for p in specialist["writable_paths"]) + " (and the Factory-rendered "
        "docs/GDD.md). A change anywhere else fails the visit, as any out-of-scope change "
        "does.\n")
    return lines

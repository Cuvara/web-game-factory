"""Factory generations: runs compared by the Factory and knowledge they were held to.

A run records, when it starts, the Factory version and commit and the version of every
knowledge file (`params.quality.factory`, `params.quality.knowledge`, quality policy rule 8).
Its knowledge-contract says which rules applied to it and at what level; its newest
quality-report's compliance section says which were satisfied, failed, unmeasured or
excepted, and its verdict. `rows(store)` reads one row per run; `generations(rows)` groups
them by what they consumed - the Factory version, lessons and check tiers - so two Factory
generations can be compared on their outcomes, and the lessons one applied that the other
did not are named:

    wgf knowledge generations [--store DIR] [--json]

Read-only: it reads the run store and writes nothing. A run whose state or artifacts cannot
be read is listed under `problems`, never dropped silently.
"""

import collections

UNRECORDED = "unrecorded"


def _latest(store, state, kind):
    ref = state.latest_of_type(kind)
    if ref is None:
        return None, None
    return ref, store.read_artifact(state.run_id, ref)


def row(store, state):
    """One run's generation row."""
    quality = (state.params or {}).get("quality") or {}
    knowledge = quality.get("knowledge") if isinstance(quality.get("knowledge"), dict) else {}
    factory = quality.get("factory") if isinstance(quality.get("factory"), dict) else {}
    _, contract = _latest(store, state, "knowledge-contract")
    report_ref, report = _latest(store, state, "quality-report")
    compliance = (report or {}).get("compliance") if isinstance(report, dict) else None
    compliance = compliance if isinstance(compliance, dict) else None
    rules = [r for r in (contract or {}).get("rules") or () if isinstance(r, dict)]
    by_level = collections.OrderedDict()
    for rule in rules:
        by_level.setdefault(rule.get("level"), []).append(rule.get("id"))
    total = ((compliance or {}).get("counts") or {}).get("total") or {}
    statuses = collections.defaultdict(list)
    for rule in (compliance or {}).get("rules") or ():
        if isinstance(rule, dict):
            statuses[rule.get("status")].append(rule.get("id"))
    return {
        "run_id": state.run_id, "created_at": state.created_at, "status": state.status,
        "factory": {"version": factory.get("version"), "commit": factory.get("commit")},
        "knowledge": dict(sorted(knowledge.items())),
        "tier": quality.get("tier"), "class": quality.get("class"),
        "facets": (contract or {}).get("facets"),
        "contract": contract is not None,
        "rules_by_level": dict(by_level),
        "lessons_applied": sorted(r.get("id") for r in rules if r.get("id")),
        "compliance": None if compliance is None else {
            "mode": compliance.get("mode"), "verdict": compliance.get("verdict"),
            "satisfied": total.get("satisfied"), "failed": total.get("failed"),
            "unmeasured": total.get("unmeasured"), "excepted": total.get("excepted"),
            "failed_rules": sorted(statuses.get("FAILED", [])),
            "excepted_rules": sorted(statuses.get("EXCEPTED", [])),
            "blocking": list(compliance.get("blocking") or []),
            "new_lessons": len(compliance.get("new_lessons") or [])},
        "quality_report": None if report_ref is None else {
            "artifact": f"{report_ref.id} v{report_ref.version}",
            "verdict": (report or {}).get("verdict"),
            "release_decision": (report or {}).get("release_decision")},
    }


def rows(store):
    """([row], [problem]) of every run in the store, oldest first."""
    problems, out = [], []
    unreadable = []
    for state in store.list_runs(problems=unreadable):
        try:
            out.append(row(store, state))
        except Exception as exc:  # noqa: BLE001 - one unreadable run never hides the rest
            problems.append(f"{state.run_id}: {exc}")
    problems += [f"{run_id}: {message}" for run_id, message in unreadable]
    return out, problems


def key_of(entry):
    factory = entry.get("factory") or {}
    version = factory.get("version") or UNRECORDED
    commit = (factory.get("commit") or "")[:7]
    knowledge = entry.get("knowledge") or {}
    parts = [f"factory {version}" + (f"@{commit}" if commit else "")]
    parts += [str(v) for _, v in sorted(knowledge.items())] or [f"knowledge {UNRECORDED}"]
    return " / ".join(parts)


def generations(entries):
    """[generation] in order of first appearance: {"key", "factory", "knowledge", "runs",
    "outcomes", "lessons_applied", "failed_rules", "excepted_rules", "added", "dropped"}.
    `added` / `dropped`: lessons this generation applied that the previous one did not, and
    the reverse."""
    groups = collections.OrderedDict()
    for entry in entries:
        groups.setdefault(key_of(entry), []).append(entry)
    out, previous = [], None
    for key, members in groups.items():
        applied = sorted({l for m in members for l in m["lessons_applied"]})
        outcomes = collections.Counter(
            ((m.get("compliance") or {}).get("verdict") or "no compliance") for m in members)
        failed = collections.Counter(r for m in members
                                     for r in (m.get("compliance") or {}).get("failed_rules") or ())
        excepted = collections.Counter(r for m in members for r in
                                       (m.get("compliance") or {}).get("excepted_rules") or ())
        generation = {
            "key": key, "factory": members[0]["factory"], "knowledge": members[0]["knowledge"],
            "runs": [m["run_id"] for m in members], "outcomes": dict(sorted(outcomes.items())),
            "statuses": dict(sorted(collections.Counter(m["status"] for m in members).items())),
            "lessons_applied": applied, "failed_rules": dict(sorted(failed.items())),
            "excepted_rules": dict(sorted(excepted.items())),
            "added": sorted(set(applied) - set(previous or ())) if previous is not None else [],
            "dropped": sorted(set(previous or ()) - set(applied)) if previous is not None else []}
        out.append(generation)
        previous = applied
    return out


def render_lines(entries, groups, problems=()):
    lines = [f"{'run':<34} {'status':<10} {'factory':<16} {'knowledge':<36} "
             f"{'rules':>5} {'sat':>4} {'fail':>4} {'exc':>4}  verdict"]
    for e in entries:
        factory = e["factory"].get("version") or UNRECORDED
        if e["factory"].get("commit"):
            factory += "@" + e["factory"]["commit"][:7]
        knowledge = ", ".join(str(v) for v in e["knowledge"].values()) or UNRECORDED
        c = e.get("compliance") or {}
        lines.append(f"{e['run_id']:<34} {str(e['status']):<10} {factory:<16} {knowledge:<36} "
                     f"{len(e['lessons_applied']):>5} {str(c.get('satisfied', '-')):>4} "
                     f"{str(c.get('failed', '-')):>4} {str(c.get('excepted', '-')):>4}  "
                     f"{c.get('verdict') or '-'}")
    lines.append("")
    for g in groups:
        lines.append(f"generation {g['key']}: {len(g['runs'])} run(s), outcomes "
                     + ", ".join(f"{k} {v}" for k, v in g["outcomes"].items()))
        if g["added"] or g["dropped"]:
            lines.append(f"  lessons added {', '.join(g['added']) or '-'}; dropped "
                         f"{', '.join(g['dropped']) or '-'}")
        if g["failed_rules"]:
            lines.append("  failed " + ", ".join(f"{k} x{v}" for k, v in g["failed_rules"].items()))
        if g["excepted_rules"]:
            lines.append("  excepted " + ", ".join(f"{k} x{v}"
                                                   for k, v in g["excepted_rules"].items()))
    for problem in problems:
        lines.append(f"problem  {problem}")
    return lines

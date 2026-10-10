"""The Factory's knowledge in the design: what the author is given, and its decision trace.

    provisional(family, strategy, environment=None, run_dir=None)
        the rules that may apply to the design about to be written - the knowledge resolver's
        output (wgf_knowledge.resolve) over what is known before it (the genre family, the
        strategy's platforms; render and tier undetermined, which never excludes a rule),
        read from the run's PINNED knowledge where the run pinned it - structured for the
        author: each rule's id, revision, domain, principle, anti-pattern, level and checks.
        None when the knowledge cannot be read (the knowledge step, not this one, stops a
        run for it). Provisional: the run's knowledge-contract, made after design, is what
        the build is held to.

    trace_view(design, knowledge, rule_results)
        consistency.projection `knowledge`: the design's decision trace (game-design 1.16.0
        `knowledge_applied`: per rule, applied or not, where - which units - how, and the
        checks that verify it) held against the knowledge it was given and the design itself.

A trace is a CLAIM. It never makes a rule satisfied - only the rule's checks do, on the
build's evidence (wgf_quality/compliance.py) - and a claim the design contradicts is a
breach (design-consistency knowledge.trace_matches_design): an entry naming a rule the design
was not given, units the design does not have, checks that are not the rule's, or
`applied: true` while one of the rule's own design-side checks is breached on this design.
An absent trace is not a breach (a design written before 1.16.0, or by an author given no
knowledge); the knowledge-contract records whether the run's design carried one.

Nothing here names a game, a family or a rule.
"""

__all__ = ["TRACE_DOMAINS", "DESIGN_SOURCE", "INSTRUCTION", "provisional", "trace_view",
           "trace_summary"]

# The domains whose rules a design records a decision for: what a designer decides.
TRACE_DOMAINS = ("level-design", "game-design", "pacing", "difficulty", "progression",
                 "content")
# A rule's checks judged on the design itself (check-tiers source design-consistency).
DESIGN_SOURCE = "design-consistency:"

INSTRUCTION = (
    "These are the Factory's rules that apply to this game, resolved from its facets. Design "
    "so every rule holds - a blocking or required rule's checks are run on this design and on "
    "the build. For every rule whose `trace` is true, record your decision in the draft's "
    "top-level `knowledge_applied` list: {rule, revision, applied (true when the design "
    "follows it), where (the unit ids it shaped), how (one line), verified_by (the rule's "
    "checks that will verify it)}. The trace is a claim the checks hold you to: claiming a "
    "rule applied while the design breaks it fails the design.")


def _load(environment, run_dir):
    """(lessons, tiers, checks) - the run's pinned knowledge where the run pinned it (a pinned
    copy is read only as the bytes the run recorded), else the Factory's own files."""
    from wgf_quality import registry
    from wgflib.workflow import references
    pins = (environment or {}).get(references.PARAM) if isinstance(environment, dict) else None
    if isinstance(pins, dict) and pins and run_dir:
        from wgf_knowledge import step as knowledge_step
        knowledge = knowledge_step.load_run_knowledge(environment, run_dir, strict=False)
        return knowledge.lessons, knowledge.tiers, knowledge.checks
    data = registry.load()
    checks, _ = registry.classify(data["tiers"])
    return data["lessons"], data["tiers"], checks


def provisional(family, strategy, environment=None, run_dir=None):
    """The structured knowledge for a design request (see the module doc), or None."""
    try:
        from wgf_knowledge import model, resolve as resolver
        lessons, tiers, checks = _load(environment, run_dir)
        facets = resolver.facets_from({"genre": {"family": family}}, strategy)
        body = resolver.resolve(lessons, checks, tiers, facets)
    except Exception:  # noqa: BLE001 - guidance only; nothing is decided here
        return None
    entries = {l.get("id"): l for l in (lessons or {}).get("lessons") or ()
               if isinstance(l, dict)}
    rules = []
    for rule in body["rules"]:
        lesson = entries.get(rule["id"]) or {}
        entry = {"id": rule["id"], "level": rule["level"], "category": rule.get("category"),
                 "checks": [c["check"] for c in rule.get("checks") or ()],
                 "lesson": " ".join(str(rule.get("lesson") or "").split())}
        for key in ("revision", "domain", "classification"):
            if lesson.get(key) is not None:
                entry[key] = lesson[key]
        for key in ("principle", "anti_pattern"):
            if lesson.get(key):
                entry[key] = " ".join(str(lesson[key]).split())
        version = model.rule_version(lesson)
        if version:
            entry["version"] = version
        entry["trace"] = lesson.get("domain") in TRACE_DOMAINS
        rules.append(entry)
    return {"provisional": True,
            "lessons": model.version_of(lessons), "facets": body["facets"],
            "instruction": INSTRUCTION, "rules": rules}


def trace_view(design, knowledge, rule_results):
    """{"present", "entries", "applied", "contradicted", "problems"} for the design's
    `knowledge_applied`, against `knowledge` (provisional()'s, or None when none could be
    read) and `rule_results` (the consistency rules already evaluated on this design)."""
    trace = (design or {}).get("knowledge_applied")
    entries = [e for e in trace if isinstance(e, dict)] if isinstance(trace, list) else []
    out = {"present": isinstance(trace, list) and bool(trace), "entries": len(entries),
           "applied": [], "contradicted": [], "problems": []}
    if not out["present"]:
        return out
    if knowledge is None:
        out["problems"].append("knowledge_applied cannot be checked: the Factory knowledge "
                               "the design was given cannot be read")
        return out
    rules = {r["id"]: r for r in knowledge.get("rules") or ()}
    units = {str(u.get("id")) for u in (((design.get("build_spec") or {}).get("content") or {})
                                        .get("units") or []) if isinstance(u, dict)}
    breached = {r.get("criterion_id") for r in rule_results or () if r.get("breached")}
    for n, entry in enumerate(entries):
        at = f"knowledge_applied[{n}] ({entry.get('rule')})"
        rule = rules.get(entry.get("rule"))
        if rule is None:
            out["problems"].append(f"{at} names a rule the design was not given - not one "
                                   "that applies to this game")
            continue
        if entry.get("revision") is not None and rule.get("revision") is not None \
                and entry["revision"] != rule["revision"]:
            out["problems"].append(f"{at} claims revision {entry['revision']}; the design was "
                                   f"given r{rule['revision']}")
        stray = [str(w) for w in entry.get("where") or () if str(w) not in units]
        if stray:
            out["problems"].append(f"{at} names unit(s) the design does not have: "
                                   + ", ".join(stray))
        foreign = [c for c in entry.get("verified_by") or () if c not in rule["checks"]]
        if foreign:
            out["problems"].append(f"{at} says it is verified by {', '.join(foreign)}, not "
                                   f"checks of {rule['id']} ({', '.join(rule['checks'])})")
        if entry.get("applied") is True:
            out["applied"].append(rule["id"])
            broken = [c for c in rule["checks"] if c.startswith(DESIGN_SOURCE)
                      and c[len(DESIGN_SOURCE):] in breached]
            if broken:
                out["contradicted"].append(rule["id"])
                out["problems"].append(f"{at} claims the rule applied, and this design breaks "
                                       f"it: {', '.join(broken)} breached")
    return out


def trace_summary(design, block):
    """{present, applied, contradicted} of a finished design (its `consistency` block holds
    the trace rule's result): what the knowledge-contract records for the run."""
    trace = (design or {}).get("knowledge_applied")
    entries = [e for e in trace if isinstance(e, dict)] if isinstance(trace, list) else []
    applied = sorted({str(e.get("rule")) for e in entries if e.get("applied") is True})
    contradicted = []
    for result in (block or {}).get("rule_results") or ():
        if result.get("criterion_id") == "knowledge.trace_matches_design" \
                and result.get("breached"):
            for line in result.get("measured") or ():
                rule = str(line).split("(", 1)[1].split(")", 1)[0] if "(" in str(line) else None
                if rule and "claims the rule applied" in str(line):
                    contradicted.append(rule)
    return {"present": bool(entries), "applied": applied,
            "contradicted": sorted(set(contradicted))}

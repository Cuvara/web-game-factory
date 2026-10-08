"""The applicability resolver: which of the Factory's rules apply to one run, and why.

    facets(family=None, genre=None, render=None, platforms=None, tier=None, profile=None,
           archetype=None)                a facet set; None (or empty) is undetermined
    facets_from(design=None, strategy=None, tier=None)
                                          the facets a run's game-design, title-strategy and
                                          quality tier determine
    resolve(lessons, checks, tiers, facets, workflow=None, exceptions=(), now=None,
            versions=None)
                                          the body of a knowledge-contract
                                          (core/artifacts/knowledge-contract.schema.json),
                                          less its provenance, title and versions

A rule applies when every scope key it declares contains the run's value for that facet
(keys AND-ed, values OR-ed; `platforms` matches when any targeted platform is listed). A
facet the run has not determined NEVER makes a rule inapplicable: the rule applies, and its
`why_applicable` says the facet was undetermined. Every rule that does not apply is listed in
`not_applicable` with the facet that excluded it - or why it is never in a run (a process
lesson, a deprecated one). An agent never decides scope: it is computed from data, and it is
visible.

Pure: no clock (pass `now`), no process, no network, no file read.
"""

from . import model

__all__ = ["FACET_KEYS", "facets", "facets_from", "resolve", "applies"]

# scope key -> facet key
SCOPE_FACETS = {"families": "family", "render": "render", "platforms": "platforms",
                "tiers": "tier", "profiles": "profile", "archetypes": "archetype"}
FACET_KEYS = ("family", "genre", "render", "platforms", "tier", "profile", "archetype")
COUNTED = ("blocking", "required", "recommended", "experimental")


def facets(family=None, genre=None, render=None, platforms=None, tier=None, profile=None,
           archetype=None):
    return {"family": family or None, "genre": genre or None, "render": render or None,
            "platforms": sorted({str(p) for p in platforms or () if p}),
            "tier": tier or None, "profile": profile or None, "archetype": archetype or None}


def facets_from(design=None, strategy=None, tier=None):
    """Facets from a game-design (genre.family, genre.node, engine.dimension), a
    title-strategy (platform_set[].id) and the run's quality tier."""
    genre = (design or {}).get("genre") or {}
    engine = (design or {}).get("engine") or {}
    platforms = [p.get("id") for p in (strategy or {}).get("platform_set") or []
                 if isinstance(p, dict)]
    return facets(family=genre.get("family"), genre=genre.get("node"),
                  render=engine.get("dimension"), platforms=platforms, tier=tier)


def applies(lesson, run_facets):
    """(True, [why]) or (False, why_not) for one lesson's scope against the facets."""
    scope = model.scope_of(lesson)
    if scope is None:
        return False, "it has no valid scope (check-integrity refuses it)"
    if not scope:
        return True, ["global"]
    why = []
    for key, values in scope.items():
        facet = SCOPE_FACETS.get(key)
        if facet is None:
            return False, f"scope key {key!r} is not a facet"
        value = (run_facets or {}).get(facet)
        allowed = [str(v) for v in values or ()]
        if value in (None, "", []):
            why.append(f"{facet} undetermined: applies (scoped to {', '.join(allowed)})")
            continue
        if facet == "platforms":
            hit = sorted(set(value) & set(allowed))
            if not hit:
                return False, (f"platforms {', '.join(value)}: none of them is in its scope "
                               f"({', '.join(allowed)})")
            why.append(f"platforms {', '.join(hit)} in scope")
            continue
        if str(value) not in allowed:
            return False, f"{facet} {value} is not in its scope ({', '.join(allowed)})"
        why.append(f"{facet} {value} in scope")
    return True, why


def _producer_steps(workflow):
    """{artifact type: [step ids that output it]} of a parsed workflow mapping."""
    out = {}
    for step in (workflow or {}).get("steps") or ():
        if not isinstance(step, dict):
            continue
        for artifact in step.get("outputs") or ():
            out.setdefault(artifact, []).append(step.get("id"))
    return out


def _constraints(run_facets, versions):
    """The contracts the facets bind the run to, by versioned reference: the genre family's
    (genre-models@<version>#<family>) and each targeted platform's profile (<id>@<version>)."""
    versions = versions or {}
    family = run_facets.get("family")
    genre_version = versions.get("genre_models")
    profiles = versions.get("platform_profiles") or {}
    return {"genre": (f"genre-models@{genre_version}#{family}" if family and genre_version
                      else f"genre-models#{family}" if family else None),
            "platforms": [profiles.get(p) or p for p in run_facets.get("platforms") or ()]}


def resolve(lessons, checks, tiers, run_facets, workflow=None, exceptions=(), now=None,
            versions=None):
    """The contract body for `run_facets` (see facets()): rules, not_applicable,
    experimental, required_validators (+ missing_validators), regression_suite, constraints,
    exceptions (+ exceptions_refused) and counts.

    `checks`: wgf_quality.registry.classify()'s checks. `tiers`: check-tiers.yaml, parsed
    (for each check's source and producer). `workflow`: the run's workflow mapping; without
    one, required_validators is empty and missing_validators names every producer.
    `exceptions`: knowledge-exception records; one that cannot hold at `now`
    (model.exception_problems) is listed in exceptions_refused with why, never honoured.
    `versions`: wgf_knowledge.versions.collect(), for the versioned constraint references."""
    run_facets = dict(facets(), **(run_facets or {}))
    producers = _producer_steps(workflow)
    sources = (tiers or {}).get("sources") or {}
    rules, excluded, experimental = [], [], []
    validators, missing, suite = [], [], []
    for lesson in (lessons or {}).get("lessons") or ():
        if not isinstance(lesson, dict) or not lesson.get("id"):
            continue
        lesson_id = lesson["id"]
        if model.is_process(lesson):
            held = str(lesson.get("held_by") or "its procedure").rstrip(".")
            excluded.append({"id": lesson_id, "why_not": "a process lesson, never in a run's "
                             f"contract (held by: {held})"})
            continue
        if lesson.get("lifecycle") == "deprecated":
            successor = lesson.get("superseded_by")
            excluded.append({"id": lesson_id, "why_not": "deprecated" + (
                f": superseded by {successor}" if successor else
                f": {lesson.get('reason') or 'withdrawn'}")})
            continue
        ok, why = applies(lesson, run_facets)
        if not ok:
            excluded.append({"id": lesson_id, "why_not": why})
            continue
        level = model.level_of(lesson, checks)
        if level is None:
            excluded.append({"id": lesson_id, "why_not": "no enforcement level can be "
                             "derived (check-integrity refuses it)"})
            continue
        held = []
        for check_id in lesson.get("checks") or ():
            entry = (checks or {}).get(check_id) or {}
            source = entry.get("source") or check_id.split(":", 1)[0]
            producer = entry.get("producer") or (sources.get(source) or {}).get("producer")
            steps = sorted(set(producers.get(producer) or ()))
            held.append({"check": check_id, "tier": entry.get("tier"), "source": source,
                         "producer": producer, "steps": steps})
            if level in ("blocking", "required"):
                if steps:
                    validators += steps
                elif not any(m["check"] == check_id for m in missing):
                    missing.append({"check": check_id, "producer": producer,
                                    "rule": lesson_id})
        tests = model.tests_of(lesson)
        rule = {"id": lesson_id, "title": lesson.get("title"), "level": level,
                "derived_level": model.derive_level(lesson, checks),
                "category": lesson.get("category"), "status": lesson.get("status"),
                "lifecycle": lesson.get("lifecycle"), "lesson": lesson.get("lesson"),
                "checks": held, "tests": tests, "why_applicable": why}
        if lesson.get("gap"):
            rule["gap"] = lesson["gap"]
        rules.append(rule)
        if level == "experimental":
            experimental.append({"id": lesson_id,
                                 "gap": lesson.get("gap") or "not enforced yet"})
        suite += [t for t in model.all_tests(lesson) if t not in suite]
    honoured, refused = [], []
    applicable = {r["id"] for r in rules}
    for record in exceptions or ():
        why = model.exception_problems(record, lessons, checks, now=now)
        if not why and isinstance(record, dict) and record.get("rule_id") not in applicable:
            why = [f"rule {record.get('rule_id')} does not apply to this run"]
        if why:
            refused.append({"exception": record, "problems": why})
        else:
            honoured.append(record)
    counts = {level: sum(1 for r in rules if r["level"] == level) for level in COUNTED}
    counts["not_applicable"] = len(excluded)
    return {
        "facets": run_facets,
        "rules": rules,
        "not_applicable": excluded,
        "experimental": experimental,
        "required_validators": sorted(set(validators)),
        "missing_validators": missing,
        "regression_suite": suite,
        "constraints": _constraints(run_facets, versions),
        "exceptions": honoured,
        "exceptions_refused": refused,
        "counts": counts,
    }

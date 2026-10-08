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

__all__ = ["FACET_KEYS", "facets", "facets_from", "platform_pins", "resolve", "applies"]

# scope key -> facet key
SCOPE_FACETS = {"families": "family", "render": "render", "platforms": "platforms",
                "tiers": "tier", "profiles": "profile", "archetypes": "archetype"}
FACET_KEYS = ("family", "genre", "render", "platforms", "tier", "profile", "archetype")
COUNTED = ("blocking", "required", "recommended", "experimental")


RENDERS = ("2d", "3d")


def _word(name, value):
    """A facet value, normalised: stripped and lower-cased; None for nothing. Anything but a
    string is refused (ValueError) - a facet is matched as a word, never as a type."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"facet {name} is a word, not {value!r}")
    value = value.strip().lower()
    return value or None


def facets(family=None, genre=None, render=None, platforms=None, tier=None, profile=None,
           archetype=None):
    """A facet set, normalised (lower case, stripped); None or an empty list is
    undetermined. A single platform given as a string is one platform, never its letters.
    Raises ValueError for a value that is not a word, or a render that is not 2d or 3d."""
    if isinstance(platforms, str):
        platforms = [platforms]
    found = set()
    for platform in platforms or ():
        word = _word("platforms", platform)
        if word:
            found.add(word)
    render = _word("render", render)
    if render is not None and render not in RENDERS:
        raise ValueError(f"facet render is 2d or 3d, not {render!r}")
    return {"family": _word("family", family), "genre": _word("genre", genre),
            "render": render, "platforms": sorted(found), "tier": _word("tier", tier),
            "profile": _word("profile", profile), "archetype": _word("archetype", archetype)}


def facets_from(design=None, strategy=None, tier=None):
    """Facets from a game-design (genre.family, genre.node, engine.dimension), a
    title-strategy (platform_set[].id) and the run's quality tier."""
    genre = (design or {}).get("genre") or {}
    engine = (design or {}).get("engine") or {}
    platforms = [p.get("id") for p in (strategy or {}).get("platform_set") or []
                 if isinstance(p, dict)]
    return facets(family=genre.get("family"), genre=genre.get("node"),
                  render=engine.get("dimension"), platforms=platforms, tier=tier)


def platform_pins(strategy):
    """{platform id: "<id>@<profile_version>"} the title-strategy pinned each targeted
    platform's profile at - the version the run is held to, not the live file's."""
    out = {}
    for entry in (strategy or {}).get("platform_set") or ():
        if isinstance(entry, dict) and entry.get("id") and entry.get("profile_version"):
            out[str(entry["id"]).strip().lower()] = \
                f"{str(entry['id']).strip().lower()}@{entry['profile_version']}"
    return out


def applies(lesson, run_facets):
    """(True, [why]) or (False, why_not) for one lesson's scope against the facets."""
    if (lesson or {}).get("scope") is None:
        # A file before the knowledge model (a run pinned lessons.yaml 1.x): no scope was
        # ever declared, so nothing narrows it.
        return True, ["no scope declared: applies"]
    scope = model.scope_of(lesson)
    if scope is None:
        return True, [f"scope {lesson.get('scope')!r} unreadable: applies"]
    if not scope:
        return True, ["global"]
    why = []
    for key, values in scope.items():
        facet = SCOPE_FACETS.get(key)
        if facet is None:
            # A key no facet answers is undetermined, like a facet the run has not set:
            # it never excludes a rule (check-integrity refuses the key).
            why.append(f"scope key {key!r} is not a facet: applies")
            continue
        value = (run_facets or {}).get(facet)
        allowed = [str(v).strip().lower() for v in values or ()]
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
            versions=None, vocabulary=None):
    """The contract body for `run_facets` (see facets()): rules, not_applicable,
    experimental, required_validators (+ missing_validators), regression_suite, constraints,
    exceptions (+ exceptions_refused) and counts.

    `checks`: wgf_quality.registry.classify()'s checks. `tiers`: check-tiers.yaml, parsed
    (for each check's source and producer). `workflow`: the run's workflow mapping; without
    one, required_validators is empty and missing_validators names every producer.
    `exceptions`: knowledge-exception records; one that cannot hold at `now`
    (model.exception_problems; without `now` none holds) is listed in exceptions_refused
    with why, never honoured. `vocabulary` (model.vocabulary()) checks an exception's
    platforms and viewports; without it a platform or viewport scope is refused.

    A rule whose level cannot be derived (a check no source classifies) is a missing
    validator - the contract cannot be made - never a rule that silently does not apply. A
    lesson deprecated with only a reason stays in the contract as recommended, with why.
    `versions`: wgf_knowledge.versions.collect(), for the versioned constraint references."""
    run_facets = facets(**{k: (run_facets or {}).get(k) for k in FACET_KEYS})
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
        deprecated = lesson.get("lifecycle") == "deprecated"
        if deprecated and lesson.get("superseded_by"):
            excluded.append({"id": lesson_id,
                             "why_not": f"deprecated: superseded by {lesson['superseded_by']}"})
            continue
        ok, why = applies(lesson, run_facets)
        if not ok:
            excluded.append({"id": lesson_id, "why_not": why})
            continue
        level = model.run_level(lesson, checks)
        if level is None:
            unclassified = [c for c in lesson.get("checks") or () if c not in (checks or {})]
            for check_id in unclassified or [None]:
                missing.append({"check": check_id, "producer": None, "rule": lesson_id,
                                "why": ("no source of check-tiers classifies it"
                                        if check_id else "no level can be derived: it names "
                                        "no check")})
            continue
        if deprecated:
            why = list(why) + [f"deprecated ({lesson.get('reason') or 'withdrawn'}): reported "
                               "as advisory, never blocks"]
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
                                    "rule": lesson_id,
                                    "why": f"no step of the workflow outputs {producer}"})
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
        why = model.exception_problems(record, lessons, checks, now, run_facets=run_facets,
                                       vocabulary=vocabulary)
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

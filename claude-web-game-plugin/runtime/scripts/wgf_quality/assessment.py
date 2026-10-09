"""The quality assessment: three separate questions about one build, on the evidence it has.

    load(environment=None, run_dir=None)   (mapping, reference record) - core/reference/
                                           quality-assessment.yaml, the run's pinned copy when
                                           it pinned one, else the live file
    expand(mapping, checks)                ({"<source>:<id>": family}, problems)
    problems(mapping, tiers, checks, floor)
                                           coverage, for check-integrity: every check a family
                                           names is declared, every check of a mapped source
                                           is in one family, every source mapped or excluded,
                                           every floor criterion mapped, an aggregate or
                                           excluded
    evaluate(mapping, tiers, checks, reports, ...)
                                           the quality-report's `assessment` section
    human_evidence(spec, decision, entries, refs)
                                           a person's G4 decision, and whether it is about
                                           this build

The section is a VIEW over the quality gate's evidence: it measures nothing again, reads every
check through the one reader of producers' results (check-tiers.yaml `status_at` through
wgf_quality.registry.check_status - knowledge compliance's `read_check`), and decides nothing:
the floor, the verdict and the release decision are the gate's, computed without it.

    design_validity      is the design coherent, and does the built content carry it
    runtime_correctness  does the build load, run, take input and reach its states
    player_facing        fun, feel, fairness, pacing, clarity - automation measures proxies;
                         PASS only on a person's G4 decision on this build

Each is PASS | FAIL | INCONCLUSIVE | NOT_SUPPORTED, by the rules in the reference file's
header: a held check (tier hard or quality) that FAILED fails it; one not measured - UNMEASURED,
SKIPPED, BLOCKED, stale, a WARNING, DEFERRED - leaves it INCONCLUSIVE, never PASS; a dimension
no held check applies to is NOT_SUPPORTED. Every check carries its measurement class.

Pure: no process, no network, no clock. Nothing here names a game, a step or a family.
"""

import re

from wgflib.yamllite import load as load_yaml

__all__ = ["MAPPING_FILE", "DIMENSIONS", "STATUSES", "CLASSES", "load", "expand", "problems",
           "evaluate", "human_evidence", "bind_self"]

MAPPING_FILE = "core/reference/quality-assessment.yaml"
DIMENSIONS = ("design_validity", "runtime_correctness", "player_facing")
STATUSES = ("PASS", "FAIL", "INCONCLUSIVE", "NOT_SUPPORTED")
CLASSES = ("deterministic", "heuristic", "self-reported", "ai-judged", "human")
REQUIRES = ("automation", "human")
WHEN = ("always", "reported")
# A tier of check-tiers.yaml that holds a build (its `blocks: true`); advisory never does.
HOLDING_TIERS = ("hard", "quality")
# How the decision a person recorded at G4 names its typed findings (wgf decide ... iterate
# --findings FILE): wgf_triage.step.FINDINGS_MARKER, read here only to count them.
_FINDINGS = re.compile(r"^findings: (\S+) (sha256:[0-9a-f]{64})\s*$", re.M)
SELF = "quality-report"


# ------------------------------------------------------------------------------- the file


def load(environment=None, run_dir=None):
    """(mapping, {"path", "version", "sha256", "pinned"}). Raises PinError, YamlError or
    OSError when the file cannot be read."""
    from wgflib.workflow import references as pinned_references
    text, digest, pinned = pinned_references.read(MAPPING_FILE, environment, run_dir)
    mapping = load_yaml(text)
    return mapping, {"path": MAPPING_FILE,
                     "version": str((mapping or {}).get("version") or "unknown"),
                     "sha256": digest, "pinned": bool(pinned)}


def _families(mapping):
    return [f for f in (mapping or {}).get("families") or () if isinstance(f, dict)]


def expand(mapping, checks):
    """({"<source>:<id>": family}, problems): every declared check (`checks`, from
    registry.classify) a family names, `<source>:*` taking every check of the source that no
    other family names explicitly."""
    out, found = {}, []
    explicit, wildcard = {}, {}
    for family in _families(mapping):
        for name in family.get("checks") or ():
            name = str(name)
            source, _, wanted = name.partition(":")
            if wanted == "*":
                if source in wildcard:
                    found.append(f"{MAPPING_FILE}: {source}:* is named by families "
                                 f"{wildcard[source]['id']} and {family.get('id')}")
                wildcard[source] = family
                continue
            if name not in checks:
                found.append(f"{MAPPING_FILE}: family {family.get('id')} names {name}, which "
                             f"check-tiers.yaml does not declare")
                continue
            if name in explicit:
                found.append(f"{MAPPING_FILE}: {name} is in families "
                             f"{explicit[name]['id']} and {family.get('id')}")
                continue
            explicit[name] = family
    for source, family in wildcard.items():
        names = [c for c, e in checks.items() if e.get("source") == source]
        if not names:
            found.append(f"{MAPPING_FILE}: family {family.get('id')} names {source}:*, and "
                         f"check-tiers.yaml declares no check of {source}")
        for name in names:
            out.setdefault(name, family)
    out.update(explicit)
    return out, found


def _schema_path(root, artifact_type, dotted):
    """True when the artifact's schema declares `dotted`."""
    import json
    import os
    from wgf_quality import registry
    from wgflib import paths
    path = os.path.join(root or paths.ROOT, "core", "artifacts",
                        f"{artifact_type}.schema.json")
    try:
        with open(path, encoding="utf-8") as handle:
            document = json.load(handle)
    except (OSError, ValueError):
        return False
    return registry._schema_has(document, dotted)


def problems(mapping, tiers, checks, floor=None, root=None):
    """[problem] of the assessment mapping against the declared checks (registry.classify of
    the same check-tiers) and the quality floor."""
    from wgf_quality import registry
    if not isinstance(mapping, dict):
        return [f"{MAPPING_FILE}: not a mapping"]
    found = []
    if list(mapping.get("statuses") or ()) != list(STATUSES):
        found.append(f"{MAPPING_FILE}: statuses must be {', '.join(STATUSES)}")
    classes = mapping.get("classes") or {}
    if set(classes) != set(CLASSES):
        found.append(f"{MAPPING_FILE}: classes must be exactly {', '.join(CLASSES)}")
    dimensions = mapping.get("dimensions") or {}
    if list(dimensions) != list(DIMENSIONS):
        found.append(f"{MAPPING_FILE}: dimensions must be {', '.join(DIMENSIONS)}, in order")
    for dim_id, dim in dimensions.items():
        if not isinstance(dim, dict) or dim.get("requires") not in REQUIRES:
            found.append(f"{MAPPING_FILE}: dimension {dim_id} requires one of "
                         f"{', '.join(REQUIRES)}")
            continue
        if dim_id == "player_facing" and dim["requires"] != "human":
            found.append(f"{MAPPING_FILE}: player_facing requires a person - nothing the "
                         "Factory runs measures fun, feel, fairness or pacing")
        if dim["requires"] == "human":
            human = dim.get("human_evidence") or {}
            if human.get("mode") != "human" or not human.get("pass") or not human.get("fail"):
                found.append(f"{MAPPING_FILE}: dimension {dim_id} requires a person, and its "
                             "human_evidence must name mode human, the decisions that pass "
                             "and the decisions that fail it")
    seen_ids = set()
    for family in _families(mapping):
        fid = family.get("id")
        where = f"{MAPPING_FILE} family {fid}"
        if not fid or fid in seen_ids:
            found.append(f"{where}: an id, unique")
        seen_ids.add(fid)
        if family.get("dimension") not in dimensions:
            found.append(f"{where}: dimension {family.get('dimension')!r} is not one of the "
                         "file's dimensions")
        if family.get("class") not in CLASSES or family.get("class") == "human":
            found.append(f"{where}: class {family.get('class')!r} - a family of checks is "
                         "deterministic, heuristic, self-reported or ai-judged; human is a "
                         "person's decision, never a check")
        if (family.get("when") or "always") not in WHEN:
            found.append(f"{where}: when {family.get('when')!r} is not one of "
                         f"{', '.join(WHEN)}")
        for key in ("label", "measures", "method", "limits", "cannot_justify"):
            if not str(family.get(key) or "").strip():
                found.append(f"{where}: says nothing in `{key}`")
        if not family.get("checks"):
            found.append(f"{where}: names no check")
        judge = family.get("judge")
        if family.get("class") == "ai-judged" and not isinstance(judge, dict):
            found.append(f"{where}: an ai-judged family names its `judge` (the report that "
                         "records it), so a dimension resting on one judgment says so")
        if judge is not None and family.get("class") != "ai-judged":
            found.append(f"{where}: only an ai-judged family has a `judge`")
        for key, block, paths in (("judge", judge, ("kind", "runs", "repairs")),
                                  ("unresolved", family.get("unresolved"), ("list",))):
            if block is None:
                continue
            if not isinstance(block, dict) or not block.get("report"):
                found.append(f"{where}: `{key}` names the report it reads")
                continue
            for path_key in paths:
                if block.get(path_key) and not _schema_path(root, block["report"],
                                                             block[path_key]):
                    found.append(f"{where}: {key}.{path_key} {block[path_key]!r} is not in "
                                 f"core/artifacts/{block['report']}.schema.json")
        unresolved = family.get("unresolved")
        if isinstance(unresolved, dict) and not unresolved.get("severities"):
            found.append(f"{where}: unresolved names the severities it lists")
    mapped, more = expand(mapping, checks)
    found += more
    named_sources = {str(n).partition(":")[0] for f in _families(mapping)
                     for n in f.get("checks") or ()}
    excluded = mapping.get("excluded") or {}
    excluded_checks = mapping.get("excluded_checks") or {}
    aggregates = mapping.get("aggregates") or {}
    aggregate_source = aggregates.get("source")
    for source in sorted({e.get("source") for e in checks.values()}):
        if source in excluded:
            if source in named_sources:
                found.append(f"{MAPPING_FILE}: {source} is excluded and named by a family")
            if not str(excluded[source] or "").strip():
                found.append(f"{MAPPING_FILE}: excluded {source} says not why")
            continue
        if source not in named_sources and source != aggregate_source:
            found.append(f"{MAPPING_FILE}: check-tiers.yaml source {source} is neither named "
                         "by a family nor excluded with why")
    for source in excluded:
        if source not in {e.get("source") for e in checks.values()}:
            found.append(f"{MAPPING_FILE}: excluded {source} is not a check-tiers.yaml source")
    for name, why in excluded_checks.items():
        if name not in checks:
            found.append(f"{MAPPING_FILE}: excluded check {name} is not declared")
        elif name in mapped:
            found.append(f"{MAPPING_FILE}: {name} is excluded and in a family")
        if not str(why or "").strip():
            found.append(f"{MAPPING_FILE}: excluded check {name} says not why")
    # Every check of a source a family names is in exactly one family (or excluded).
    for name, entry in checks.items():
        source = entry.get("source")
        if source in named_sources and source != aggregate_source and name not in mapped \
                and name not in excluded_checks:
            found.append(f"{MAPPING_FILE}: {name} is a check of {source}, which the families "
                         "map, and no family names it")
    # The floor: a criterion no family names is an aggregate of checks a family maps.
    if aggregate_source:
        mapped_producers = {checks[n].get("producer") for n in mapped
                            if checks[n].get("source") != aggregate_source}
        kinds = set(aggregates.get("kinds") or ())
        listed = aggregates.get("criteria") or {}
        criteria = {c.get("id"): c for c in registry.floor_criteria(floor)} if floor else {}
        for criterion_id, why in listed.items():
            name = f"{aggregate_source}:{criterion_id}"
            if name not in checks:
                found.append(f"{MAPPING_FILE}: aggregate {criterion_id} is not a declared "
                             f"check of {aggregate_source}")
            elif name in mapped:
                found.append(f"{MAPPING_FILE}: {criterion_id} is an aggregate and in a family")
            if not str(why or "").strip():
                found.append(f"{MAPPING_FILE}: aggregate {criterion_id} says not what it "
                             "aggregates")
        for name, entry in checks.items():
            if entry.get("source") != aggregate_source or name in mapped \
                    or name in excluded_checks:
                continue
            criterion_id = entry.get("id")
            if criterion_id in listed:
                continue
            criterion = criteria.get(criterion_id)
            evaluate_ = (criterion or {}).get("evaluate") or {}
            if criterion is None:
                found.append(f"{MAPPING_FILE}: {name} is not in a family, an aggregate or "
                             "excluded")
            elif evaluate_.get("kind") not in kinds:
                found.append(f"{MAPPING_FILE}: {criterion_id} ({evaluate_.get('kind')}) is "
                             f"not a {'/'.join(sorted(kinds))} aggregate - name it in a "
                             "family, list it under aggregates.criteria or exclude it")
            elif evaluate_.get("report") not in mapped_producers:
                found.append(f"{MAPPING_FILE}: {criterion_id} aggregates "
                             f"{evaluate_.get('report')}, whose own checks no family maps")
    return found


# --------------------------------------------------------------------------- the person


def human_evidence(spec, decision, entries, ref=None):
    """[entry] for a person's decision at the dimension's gate: {artifact_type, artifact_id,
    content_hash, gate, decision, decided_by, about, findings, verdict}. `about` is
    `this-build` only when the decision pins, by content hash, a report of this build that is
    current (the gate's evidence `entries`); a decision on an earlier build is listed and
    decides nothing (`verdict` None). A decision that is not a person's is never listed."""
    spec = spec or {}
    if not isinstance(decision, dict):
        return []
    if spec.get("gate") and decision.get("gate_id") != spec.get("gate"):
        return []
    decided = decision.get("decided_by") if isinstance(decision.get("decided_by"), dict) else {}
    if decided.get("mode") != spec.get("mode", "human"):
        return []
    current = {(e.get("artifact_type"), e.get("content_hash")) for e in entries or ()
               if e.get("status") == "current" and e.get("content_hash")}
    pinned = {(s.get("artifact_type"), s.get("content_hash"))
              for s in decision.get("subject") or () if isinstance(s, dict)}
    about = "this-build" if pinned & current else "earlier-build"
    verdict = None
    if about == "this-build":
        if decision.get("decision") in (spec.get("pass") or ()):
            verdict = "PASS"
        elif decision.get("decision") in (spec.get("fail") or ()):
            verdict = "FAIL"
    findings = len(_FINDINGS.findall(str(decision.get("rationale") or "")))
    return [{"artifact_type": spec.get("artifact") or "decision-record",
             "artifact_id": (decision.get("provenance") or {}).get("artifact_id"),
             "content_hash": getattr(ref, "content_hash", None) if ref is not None else None,
             "gate": decision.get("gate_id"), "decision": decision.get("decision"),
             "decided_by": {"role": decided.get("role"),
                            "identifier": decided.get("identifier")},
             "about": about, "findings": findings, "verdict": verdict}]


# ------------------------------------------------------------------------------ evaluate


def _ref(evidence):
    if not isinstance(evidence, dict):
        return None
    return {k: evidence.get(k) for k in ("artifact_type", "artifact_id", "content_hash",
                                         "commit")}


def _reported(tiers, name, report):
    """True when `report` has an entry for the check (its locator finds one)."""
    from wgf_quality import registry
    if not isinstance(report, dict):
        return False
    source, _, wanted = name.partition(":")
    locator = registry.status_at(tiers, source)
    if locator is None:
        return False
    found = registry.check_results(locator, report)
    if locator.get("attribute") is False:
        return bool(found)
    return any(r["check"] == wanted for r in found)


def _cites(self_report, criterion_id):
    """The evidence a floor criterion of the report being made cites (its producers')."""
    for criterion in (self_report or {}).get("criteria") or ():
        if isinstance(criterion, dict) and criterion.get("id") == criterion_id:
            return [_ref(e) for e in criterion.get("evidence") or () if isinstance(e, dict)]
    return []


def _walk_one(report, dotted):
    from wgf_quality import registry
    found = registry._walk(report, dotted) if isinstance(report, dict) and dotted else []
    return found[0] if found else None


def _judge_of(family, reports):
    """{family, artifact_type, artifact_id, kind, runs, repairs} for an ai-judged family's
    judge, read from the report its `judge` names; None when the run holds no such report."""
    judge = family.get("judge")
    if not isinstance(judge, dict):
        return None
    report = (reports or {}).get(judge.get("report"))
    if not isinstance(report, dict):
        return None
    runs = _walk_one(report, judge.get("runs"))
    repairs = _walk_one(report, judge.get("repairs"))
    kind = _walk_one(report, judge.get("kind"))
    return {"family": family.get("id"), "artifact_type": judge.get("report"),
            "artifact_id": (report.get("provenance") or {}).get("artifact_id"),
            "kind": str(kind) if kind is not None else None,
            "runs": runs if isinstance(runs, int) and not isinstance(runs, bool) else None,
            "repairs": repairs if isinstance(repairs, int)
            and not isinstance(repairs, bool) else None}


def _unresolved_of(family, reports):
    """[{family, artifact_type, artifact_id, report_verdict, id, severity, summary}]: the
    findings at the family's `unresolved` severities in its report, whatever its verdict."""
    rule = family.get("unresolved")
    if not isinstance(rule, dict):
        return []
    report = (reports or {}).get(rule.get("report"))
    if not isinstance(report, dict):
        return []
    from wgf_quality import registry
    severities = {str(v) for v in rule.get("severities") or ()}
    out = []
    for entries in registry._walk(report, rule.get("list") or "findings"):
        for entry in entries if isinstance(entries, list) else ():
            if isinstance(entry, dict) and str(entry.get("severity")) in severities:
                out.append({"family": family.get("id"), "artifact_type": rule.get("report"),
                            "artifact_id": (report.get("provenance") or {}).get("artifact_id"),
                            "report_verdict": report.get("verdict"),
                            "id": str(entry.get("id")),
                            "severity": str(entry.get("severity")),
                            "summary": str(entry.get("summary") or "")[:300]})
    return out


# The classes whose result is not the Factory's own measurement of the build: the game's word,
# or one AI judgment (the Factory never repeats or cross-checks a judge).
WEAK_CLASSES = ("self-reported", "ai-judged")


def _basis(status, held, person=False):
    """How much of a PASS rests on the game's own report or a single AI judgment:
    {strength, held, passed, weak, by_class, why}. `strength` is None unless PASS; `person`
    for a dimension a person's decision passed, whatever its automated proxies."""
    passed = [c for c in held if c["status"] == "PASS"]
    if person and status == "PASS":
        by_class = {}
        for item in passed:
            by_class[item["class"]] = by_class.get(item["class"], 0) + 1
        return {"strength": "person", "held": len(held), "passed": len(passed), "weak": 0,
                "by_class": by_class,
                "why": "rests on a person's G4 decision on this build; the automated checks "
                       "are supporting proxies"}
    weak = [c for c in passed if c["class"] in WEAK_CLASSES]
    by_class = {}
    for item in passed:
        by_class[item["class"]] = by_class.get(item["class"], 0) + 1
    strength, why = None, None
    if status == "PASS" and passed:
        strength = "weak" if len(weak) == len(passed) else (
            "qualified" if weak else "measured")
        if weak:
            why = (f"{len(weak)} of {len(passed)} passing check(s) rest on the game's own "
                   "report or a single AI judgment: "
                   + ", ".join(f"{n} {k}" for k, n in sorted(by_class.items())
                               if k in WEAK_CLASSES))
    return {"strength": strength, "held": len(held), "passed": len(passed),
            "weak": len(weak), "by_class": by_class, "why": why}


def _status(requires, decisive, human):
    """(status, reason) of one dimension from its held checks and a person's verdicts."""
    failed = [c["check"] for c in decisive if c["status"] == "FAIL"]
    refused = [h for h in human if h.get("verdict") == "FAIL"]
    if failed or refused:
        parts = []
        if failed:
            parts.append(f"{len(failed)} check(s) that hold a build FAILED: "
                         + ", ".join(failed[:6]))
        if refused:
            parts.append(f"a person's G4 decision on this build was {refused[0]['decision']}")
        return "FAIL", "; ".join(parts)
    unmeasured = [f"{c['check']} {c['status']}" for c in decisive if c["status"] != "PASS"]
    if requires == "human":
        passed = [h for h in human if h.get("verdict") == "PASS"]
        if passed:
            return "PASS", (f"a person's G4 decision on this build passed it "
                            f"({passed[0].get('artifact_id')})")
        earlier = [h for h in human if h.get("about") == "earlier-build"]
        if not decisive and not human:
            return "NOT_SUPPORTED", ("no automated proxy applies to this build and no person "
                                     "has judged it")
        return "INCONCLUSIVE", (
            "no person has judged this build: automation measures proxies of fun, feel, "
            "fairness, pacing and clarity, never the qualities themselves"
            + (f" ({len(decisive)} held proxy(ies), {len(unmeasured)} not measured)"
               if decisive else "")
            + ("; a person's decision on an earlier build is listed and decides nothing"
               if earlier else ""))
    if not decisive:
        return "NOT_SUPPORTED", ("no check that holds a build applies to this game: nothing "
                                 "here can say")
    if unmeasured:
        return "INCONCLUSIVE", (f"{len(unmeasured)} of {len(decisive)} check(s) it rests on "
                                "measured nothing on this build (never a pass): "
                                + ", ".join(unmeasured[:6]))
    return "PASS", f"all {len(decisive)} check(s) it rests on passed on this build"


def evaluate(mapping, tiers, checks, reports, *, refs=None, entries=None, build=None,
             self_report=None, render=None, reference=None, problem=None):
    """The quality-report's `assessment` section. Never raises: what cannot be read is said.

    `mapping`: quality-assessment.yaml; `tiers`: the run's pinned check-tiers; `checks`:
    registry.classify of them; `reports`: {artifact type: report} the gate read; `refs`
    their refs; `entries` the gate's evidence entries; `build` the build identity;
    `self_report` {"criteria", "dimensions"} of the quality-report being made; `render` the
    run's 2d|3d; `reference` the mapping's {path, version, sha256, pinned}."""
    from wgf_quality import compliance
    section = {"reference": reference or {"path": MAPPING_FILE, "version": None,
                                          "sha256": None, "pinned": False},
               "decides": False,
               "note": ("a view over the evidence above - it decides nothing: the floor, the "
                        "verdict and the release decision are the gate's"),
               "dimensions": []}
    dimensions = (mapping or {}).get("dimensions") if isinstance(mapping, dict) else None
    if problem or not isinstance(dimensions, dict):
        section["problem"] = problem or f"{MAPPING_FILE} states no dimensions"
        for dim_id in DIMENSIONS:
            section["dimensions"].append({
                "id": dim_id, "label": dim_id, "status": "INCONCLUSIVE",
                "reason": f"the assessment cannot be made ({section['problem']}): never a pass",
                "requires": "human" if dim_id == "player_facing" else "automation",
                "basis": _basis("INCONCLUSIVE", []),
                "checks": [], "not_reported": [], "human": [], "judges": [],
                "unresolved": [], "classes": {}, "cannot_justify": []})
        return section
    mapped, _ = expand(mapping, checks or {})
    facts = {"render": render, "reports": dict(reports or {})}
    by_dimension = {d: [] for d in dimensions}
    not_reported = {d: [] for d in dimensions}
    used = {d: [] for d in dimensions}
    judges = {}
    for name in sorted(mapped):
        family = mapped[name]
        dim_id = family.get("dimension")
        if dim_id not in by_dimension:
            continue
        entry = checks.get(name) or {}
        producer = entry.get("producer")
        report = self_report if producer == SELF else (reports or {}).get(producer)
        if (family.get("when") or "always") == "reported" and not _reported(tiers, name,
                                                                            report):
            not_reported[dim_id].append({"check": name, "family": family.get("id")})
            continue
        read, _ = compliance.read_check({"check": name, "tier": entry.get("tier"),
                                         "producer": producer}, tiers, reports, refs,
                                        entries, build, self_report, facts)
        holds = entry.get("tier") in HOLDING_TIERS
        requires = (dimensions[dim_id] or {}).get("requires")
        item = {"check": name, "family": family.get("id"), "class": family.get("class"),
                "tier": entry.get("tier"), "producer": producer, "status": read["status"],
                "holds": holds,
                "role": "decides" if holds and requires != "human" else "supporting",
                "evidence": _ref(read.get("evidence"))}
        if producer == SELF:
            item["cites"] = _cites(self_report, entry.get("id"))
        if family.get("class") == "ai-judged":
            if family.get("id") not in judges:
                judges[family.get("id")] = _judge_of(family, reports)
            item["judge_runs"] = (judges[family.get("id")] or {}).get("runs")
        if read.get("note"):
            item["note"] = read["note"]
        by_dimension[dim_id].append(item)
        if family not in used[dim_id] and read["status"] != "NOT_APPLICABLE":
            used[dim_id].append(family)
    decision = (reports or {}).get("decision-record")
    for dim_id, dim in dimensions.items():
        dim = dim or {}
        requires = dim.get("requires") or "automation"
        human = []
        if requires == "human":
            human = human_evidence(dim.get("human_evidence"), decision, entries,
                                   (refs or {}).get("decision-record"))
        listed = by_dimension[dim_id]
        held = [c for c in listed if c["holds"] and c["status"] != "NOT_APPLICABLE"]
        status, reason = _status(requires, held, human)
        classes = {}
        for item in listed:
            if item["status"] != "NOT_APPLICABLE":
                classes[item["class"]] = classes.get(item["class"], 0) + 1
        if human:
            classes["human"] = len(human)
        cannot = [str(dim["cannot_justify"])] if dim.get("cannot_justify") else []
        cannot += [f"{f.get('label')}: {f.get('cannot_justify')}" for f in used[dim_id]]
        families = [f for f in _families(mapping) if f.get("dimension") == dim_id]
        judged = [judges[f["id"]] for f in families if judges.get(f.get("id"))]
        unresolved = [u for f in families for u in _unresolved_of(f, reports)]
        if unresolved:
            reason += (f"; {len(unresolved)} judge finding(s) at blocker or major severity "
                       "are listed unresolved, whatever their report's verdict")
        section["dimensions"].append({
            "id": dim_id, "label": dim.get("label") or dim_id, "question": dim.get("question"),
            "status": status, "reason": reason, "requires": requires,
            "basis": _basis(status, held, person=requires == "human"),
            "checks": listed, "not_reported": not_reported[dim_id], "human": human,
            "judges": judged, "unresolved": unresolved,
            "classes": classes, "cannot_justify": cannot})
    return section


def bind_self(section, artifact_id):
    """Cite the quality-report being made by its artifact id where a check is its own."""
    for dim in (section or {}).get("dimensions") or ():
        for item in dim.get("checks") or ():
            evidence = item.get("evidence")
            if isinstance(evidence, dict) and evidence.get("artifact_type") == SELF:
                evidence["artifact_id"] = artifact_id
    return section

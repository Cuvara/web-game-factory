"""Knowledge compliance: did this build satisfy every rule the run's knowledge-contract holds
it to? A section of the quality-report, never a second quality system.

    evaluate(contract, tiers, reports, *, ...)   the quality-report's `compliance` section
    apply(report, section)                       the section's effect on the report: a
                                                 blocking or required rule not satisfied and
                                                 not excepted makes the release decision
                                                 not-release and the verdict FAIL, routed
                                                 back by the producers of what is missing
    bind_self(section, artifact_id)              cite the quality-report itself where a
                                                 rule's check is the gate's own criterion
    retroactive_contract(...)                    a pre-knowledge run's contract, resolved now
    run_exceptions(context)                      the exceptions a person granted the run
    render_markdown(section) / render_lines(section)
                                                 the same section, for a person

Every applicable rule gets one status, from the checks that hold it:

    SATISFIED       every check passed (or does not concern this build) on the build's current
                    evidence, cited by the producer's artifact id, content hash and commit
    FAILED          a check failed
    UNMEASURED      a check has no result on this build: no report, no entry, skipped,
                    blocked, stale, or a warning (what its producer reported without holding
                    it: not measured, or not held at this tier) - never a pass
    DEFERRED        a check's producer measures it later (the store listing)
    NOT_APPLICABLE  every check is one its producer reports only for builds it concerns, and
                    the evidence its locator's `not_reported` group names shows this build is
                    not one (the report finished, the family ran, the run's facts) - or the
                    producer said so of its entry (`not_applicable`)
    EXCEPTED        FAILED or UNMEASURED, and a person's active exception covers every check
                    that is not passing - listed, never SATISFIED
    NOT_ENFORCED    an experimental rule nothing holds yet (its gap): guidance

A blocking or required rule that is FAILED or UNMEASURED blocks the release. A recommended or
experimental one is a warning, never a block. Where a check's result is read is
check-tiers.yaml `status_at`, through wgf_quality.registry.check_status - the one reader of a
producer's check results for rules; nothing here reads a report its own way.

The section is ENFORCING for a run that made its contract (the knowledge step) at a
releasable tier. It is ADVISORY - shown, never changing the decision - for a development
build (tier mvp: never released anyway) and for a run started before the knowledge model,
whose contract is resolved now from what it pinned (`retroactive`). A run that recorded its
knowledge at start but whose contract is not an input here is never silently skipped: that
is RELEASE_BLOCKED, enforcing.

Pure but for `retroactive_contract` and `run_exceptions`, which read the run's pins and
events. Nothing here names a game, a step or a family.
"""

import datetime

from wgf_knowledge import model

__all__ = ["evaluate", "apply", "bind_self", "retroactive_contract", "run_exceptions",
           "honoured_exceptions", "scope_covers", "now_utc",
           "render_markdown", "render_lines", "summary", "RULE_STATUSES", "BLOCKING_LEVELS",
           "EXCEPTION_EVENT", "SELF"]

RULE_STATUSES = ("SATISFIED", "FAILED", "UNMEASURED", "DEFERRED", "NOT_APPLICABLE",
                 "EXCEPTED", "NOT_ENFORCED")
BLOCKING_LEVELS = ("blocking", "required")
LEVELS = ("blocking", "required", "recommended", "experimental")
# The operator event a person's exception is recorded as (`wgf resume <run> --except ...`).
EXCEPTION_EVENT = "KNOWLEDGE_EXCEPTION_GRANTED"
# The producer that is this gate: its criteria and dimensions are read from the report being
# made, and cited as it.
SELF = "quality-report"
# Where a failure of a check is worked on, by the artifact type that reports it: the same
# routes the quality gate already returns (an asset the assets step makes again, a design
# question, otherwise the build).
ROUTE_OF_PRODUCER = {"asset-manifest": "assets", "game-design": "design-gap"}
ROUTE_ORDER = ("design-gap", "assets", "develop", "listing")
_COUNT_KEYS = ("applicable", "satisfied", "failed", "unmeasured", "excepted", "deferred",
               "not_applicable", "not_enforced")
_NOT_A_RESULT = ("UNMEASURED", "SKIPPED", "BLOCKED", "MEASURED")


# ------------------------------------------------------------------------------ results


def _check_status(statuses):
    """One status for a check from its results (one per viewport or project)."""
    found = set(statuses)
    if not found:
        return "UNMEASURED"
    if "FAIL" in found:
        return "FAIL"
    if found & set(_NOT_A_RESULT) or "WARNING" in found:
        return "UNMEASURED"
    if "DEFERRED" in found:
        return "DEFERRED"
    if found <= {"NOT_APPLICABLE"}:
        return "NOT_APPLICABLE"
    return "PASS"


def _evidence(producer, reports, refs, entries, build):
    """The producer's artifact the check was read from: {artifact_type, artifact_id,
    content_hash, commit, current}, or None when the run holds no report of it."""
    if producer == SELF:
        return {"artifact_type": SELF, "artifact_id": None, "content_hash": None,
                "commit": (build or {}).get("commit"), "current": True, "self": True}
    report = (reports or {}).get(producer)
    if not isinstance(report, dict):
        return None
    for entry in entries or ():
        if entry.get("artifact_type") == producer:
            return {"artifact_type": producer, "artifact_id": entry.get("artifact_id"),
                    "content_hash": entry.get("content_hash"), "commit": entry.get("commit"),
                    "current": entry.get("status") == "current"}
    # A producer the quality floor does not tie to a commit of the build (the design, the
    # asset manifest): which build it describes is not known - said so, never `current`.
    ref = (refs or {}).get(producer)
    return {"artifact_type": producer,
            "artifact_id": (report.get("provenance") or {}).get("artifact_id"),
            "content_hash": getattr(ref, "content_hash", None) if ref is not None else None,
            "commit": None, "current": None}


def _viewports(tiers, check_id, report):
    """{viewport: status} of a per-viewport check (a locator with `id_split`), else None."""
    from wgf_quality import registry
    source, _, wanted = str(check_id).partition(":")
    locator = registry.status_at(tiers, source)
    split = (locator or {}).get("id_split")
    if not split or not isinstance(report, dict):
        return None
    whole = {k: v for k, v in locator.items() if k != "id_split"}
    out = {}
    for result in registry.check_results(whole, report):
        base, _, viewport = result["check"].partition(split)
        if base == wanted and viewport:
            out[viewport] = result["status"]
    return out


def _read_check(held, tiers, reports, refs, entries, build, self_report, facts=None):
    from wgf_quality import registry
    check_id = held.get("check")
    producer = held.get("producer")
    evidence = _evidence(producer, reports, refs, entries, build)
    report = self_report if producer == SELF else (reports or {}).get(producer)
    out = {"check": check_id, "tier": held.get("tier"), "producer": producer,
           "evidence": evidence}
    if evidence is None:
        out.update(status="UNMEASURED", results=0,
                   note=f"no {producer} in the run: nothing measured it")
        return out, None
    if evidence.get("current") is False:
        out.update(status="UNMEASURED", results=0,
                   note=f"the {producer} describes another build: stale, never a pass")
        return out, None
    results = registry.check_status(tiers, check_id, report, facts)
    statuses = [r["status"] for r in results]
    status = _check_status(statuses)
    out.update(status=status, results=sum(1 for s in statuses if s != "NOT_APPLICABLE"))
    if status == "UNMEASURED":
        raw = sorted({s for s in statuses})
        out["note"] = ("measured a value, not a verdict" if raw == ["MEASURED"] else
                       f"its {producer} reports it {', '.join(raw)}: never a pass")
    elif status == "NOT_APPLICABLE":
        why = next((r.get("why") for r in results if r.get("why")), None)
        out["note"] = (f"not reported by its {producer}: {why}" if why else
                       f"its {producer} says it does not concern this build")
    elif status == "PASS" and any(r.get("covered") for r in results):
        out["note"] = (f"its {producer} made it advisory: another check measured what it "
                       "stands for, and is read on its own")
    if evidence.get("current") is None:
        out["note"] = (out.get("note", "") + "; " if out.get("note") else "") + (
            f"the {producer} is not tied to a commit of the build: its currency is unknown")
    unattributed = sorted({u for r in results for u in r.get("unattributed") or ()})
    if unattributed:
        out["note"] = (out.get("note", "") + "; " if out.get("note") else "") + (
            "a finding of the producer names no check: " + ", ".join(unattributed[:4]))
    return out, _viewports(tiers, check_id, report)


# --------------------------------------------------------------------------- exceptions


def _parse(value):
    return model.parse_time(value) if isinstance(value, str) else None


def _exception_checks(contract):
    """{check: {"tier"}} for model.exception_problems, from the contract's rules."""
    out = {}
    for rule in (contract or {}).get("rules") or ():
        for held in rule.get("checks") or ():
            if held.get("check"):
                out[held["check"]] = {"tier": held.get("tier")}
    return out


def _as_contracted(lessons, rule):
    """`lessons` with the excepted rule held by the checks the run's contract names: the
    contract, resolved from what the run pinned, is what says the rule's level here."""
    if not isinstance(rule, dict) or not isinstance(lessons, dict):
        return lessons
    held = [c.get("check") for c in rule.get("checks") or () if c.get("check")]
    return dict(lessons, lessons=[
        dict(entry, checks=held) if isinstance(entry, dict) and entry.get("id") == rule.get("id")
        and held else entry for entry in lessons.get("lessons") or ()])


def _vocabulary():
    try:
        return model.vocabulary()
    except model.KnowledgeError:
        return None     # a platform or viewport scope then cannot be checked: refused


def _judge_exceptions(records, contract, lessons, now):
    """[{exception, status, problems}] for every exception offered, judged at `now` by the
    knowledge model's own rules (model.exception_problems, against the run's facets and the
    rule as its contract holds it) and the contract: `honoured` while it holds, `expired`
    past its expiry (the rule is held again), `refused` otherwise - never honoured."""
    rules = {r.get("id"): r for r in (contract or {}).get("rules") or ()}
    facets = (contract or {}).get("facets") or {}
    platforms = set(facets.get("platforms") or ())
    checks = _exception_checks(contract)
    vocabulary = None
    out, seen = [], set()
    for record in records or ():
        if not isinstance(record, dict):
            continue
        key = (record.get("rule_id"), record.get("created_at"), record.get("expires_at"),
               str(record.get("scope")))
        if key in seen:
            continue
        seen.add(key)
        rule = rules.get(record.get("rule_id"))
        scope = record.get("scope") if isinstance(record.get("scope"), dict) else {}
        if vocabulary is None and (scope.get("platforms") or scope.get("viewports")):
            vocabulary = _vocabulary()
        problems = list(model.exception_problems(
            record, _as_contracted(lessons, rule) if lessons is not None else {},
            checks, now, run_facets=facets, vocabulary=vocabulary)) \
            if lessons is not None else []
        if rule is None:
            problems.append(f"rule {record.get('rule_id')} is not an applicable rule of this "
                            "run's contract")
        elif rule.get("level") not in BLOCKING_LEVELS:
            problems.append(f"rule {rule.get('id')} is {rule.get('level')}: it never blocks, "
                            "so there is nothing to except")
        if record.get("_unverified"):
            problems.append(f"unverified: {record['_unverified']}")
        mode = (record.get("approved_by") or {}).get("mode") \
            if isinstance(record.get("approved_by"), dict) else None
        if mode != "human" and not any("unauthorized" in p for p in problems):
            problems.append(f"unauthorized: approved by {mode!r}, not a person")
        wanted = set(scope.get("platforms") or ())
        if wanted and platforms and not platforms <= wanted:
            problems.append(f"its scope covers {', '.join(sorted(wanted))}; this run also "
                            f"targets {', '.join(sorted(platforms - wanted))}, and one build "
                            "ships to every one of them")
        if not model.exception_active(record, now) and not any(
                p.startswith("expired at") for p in problems) and _parse(
                record.get("expires_at")) is not None and now is not None \
                and now >= _parse(record.get("expires_at")):
            problems.append(f"expired at {record.get('expires_at')}")
        expired = [p for p in problems if p.startswith("expired at")]
        if expired and len(expired) == len(problems):
            status = "expired"
            problems = [f"expired at {record.get('expires_at')}: past its expiry the rule is "
                        "held again"]
        elif problems:
            status = "refused"
        elif not model.exception_active(record, now):
            status, problems = "refused", ["not active at the gate's clock"]
        else:
            status = "honoured"
        out.append({"exception": record, "status": status, "problems": problems})
    return out


def exception_entries(records, contract, lessons, now):
    """The compliance section's `exceptions`: every record offered, judged at `now`, with
    its status and problems (the section's own shape)."""
    return [{**{k: e["exception"].get(k) for k in (
        "rule_id", "reason", "scope", "approved_by", "created_at", "expires_at")},
        "status": e["status"], "problems": e["problems"]}
        for e in _judge_exceptions(records, contract, lessons, now)]


def honoured_exceptions(records, contract, lessons, now):
    """The records of `records` that hold at `now` for the run's `contract` (the same
    judgement the compliance section lists)."""
    return [e["exception"] for e in _judge_exceptions(records, contract, lessons, now)
            if e["status"] == "honoured"]


def scope_covers(record, check, viewport=None):
    """True when an exception's scope covers `check` (and `viewport`, when it names some)."""
    scope = record.get("scope") if isinstance(record.get("scope"), dict) else {}
    named = scope.get("checks") or ()
    if named and check not in named:
        return False
    viewports = scope.get("viewports") or ()
    if viewports and viewport not in viewports:
        return False
    return True


def _covers(judged, rule, checks, viewports):
    """The honoured exception that covers every non-passing check of `rule`, or None."""
    for entry in judged:
        record = entry["exception"]
        if entry["status"] != "honoured" or record.get("rule_id") != rule.get("id"):
            continue
        scope = record.get("scope") if isinstance(record.get("scope"), dict) else {}
        named = set(scope.get("checks") or ())
        wanted_viewports = set(scope.get("viewports") or ())
        covered = True
        for check in checks:
            if check["status"] in ("PASS", "NOT_APPLICABLE", "DEFERRED"):
                continue
            if named and check["check"] not in named:
                covered = False
                break
            if wanted_viewports:
                per = viewports.get(check["check"])
                failing = {v for v, s in (per or {}).items()
                           if s not in ("PASS", "NOT_APPLICABLE")}
                if not per or not failing or not failing <= wanted_viewports:
                    covered = False
                    break
        if covered:
            return entry
    return None


# ------------------------------------------------------------------------------- rules


def _rule_status(level, checks):
    if not checks:
        return "NOT_ENFORCED" if level == "experimental" else "UNMEASURED"
    statuses = [c["status"] for c in checks]
    if "FAIL" in statuses:
        return "FAILED"
    if "UNMEASURED" in statuses:
        return "UNMEASURED"
    if "DEFERRED" in statuses:
        return "DEFERRED"
    if all(s == "NOT_APPLICABLE" for s in statuses):
        return "NOT_APPLICABLE"
    return "SATISFIED"


def _route(rule):
    routes = set()
    for check in rule["checks"]:
        if check["status"] in ("FAIL", "UNMEASURED"):
            routes.add(ROUTE_OF_PRODUCER.get(check.get("producer"), "develop"))
    return routes


def _counts(rules):
    by_level = {level: {k: 0 for k in _COUNT_KEYS} for level in LEVELS}
    for rule in rules:
        row = by_level.setdefault(rule["level"], {k: 0 for k in _COUNT_KEYS})
        row["applicable"] += 1
        row[rule["status"].lower()] += 1
    totals = {k: sum(row[k] for row in by_level.values()) for k in _COUNT_KEYS}
    return {"by_level": by_level, "total": totals}


def evaluate(contract, tiers, reports, *, refs=None, entries=None, build=None,
             self_report=None, tier=None, contract_ref=None, retroactive=False,
             contract_missing=None, exceptions=(), lessons=None, now=None, candidates=(),
             problem=None, run_class=None):
    """The quality-report's `compliance` section.

    `contract`: the run's knowledge-contract (or a retroactive one; None when none could be
    resolved). `tiers`: the check-tiers the run pinned. `reports`: {artifact type: report}
    the gate read; `refs` their refs; `entries` the gate's evidence entries
    (scoring.evidence: the commit each report describes, current or stale); `build` the
    build identity; `self_report`: {"criteria", "dimensions"} of the quality-report being
    made. `tier`: the run's quality tier. `contract_ref`: {artifact_id, content_hash} of the
    contract. `retroactive`: the contract was resolved now for a pre-knowledge run.
    `contract_missing`: why a run that recorded its knowledge has no contract here (blocks).
    `exceptions`: knowledge-exception records offered (the contract's and the run's events).
    `lessons`: the pinned lessons.yaml (the exception policy). `now`: an aware datetime.
    `candidates`: the run's lesson candidates. `problem`: why the knowledge could not be
    read (blocks when enforcing). `run_class`: the run's quality class (its snapshot): a
    release-class run is enforced whatever tier its design states."""
    contract = contract if isinstance(contract, dict) else None
    judged = _judge_exceptions(list(exceptions or ()), contract, lessons, now)
    facts = {"render": ((contract or {}).get("facets") or {}).get("render"),
             "reports": dict(reports or {})}
    rules = []
    for rule in (contract or {}).get("rules") or ():
        checks, viewports = [], {}
        for held in rule.get("checks") or ():
            read, per = _read_check(held, tiers, reports, refs, entries, build, self_report,
                                    facts)
            checks.append(read)
            if per is not None:
                viewports[held.get("check")] = per
        level = rule.get("level")
        status = _rule_status(level, checks)
        entry = {"id": rule.get("id"), "title": rule.get("title"), "level": level,
                 "category": rule.get("category"), "status": status, "checks": checks}
        if status in ("FAILED", "UNMEASURED") and level in BLOCKING_LEVELS:
            covering = _covers(judged, rule, checks, viewports)
            if covering is not None:
                entry["measured_status"] = status
                entry["status"] = "EXCEPTED"
                record = covering["exception"]
                entry["exception"] = {k: record.get(k) for k in (
                    "rule_id", "reason", "scope", "approved_by", "created_at", "expires_at")}
        if rule.get("gap"):
            entry["gap"] = rule["gap"]
        entry["blocks"] = level in BLOCKING_LEVELS and entry["status"] in ("FAILED",
                                                                           "UNMEASURED")
        entry["warning"] = (level not in BLOCKING_LEVELS
                            and entry["status"] in ("FAILED", "UNMEASURED"))
        rules.append(entry)

    blocking = [r["id"] for r in rules if r["blocks"]]
    reasons = []
    if contract_missing:
        reasons.append(contract_missing)
    if problem and not retroactive:
        reasons.append(problem)
    for rule in rules:
        if rule["blocks"]:
            bad = [f"{c['check']} {c['status']}" for c in rule["checks"]
                   if c["status"] in ("FAIL", "UNMEASURED")]
            reasons.append(f"{rule['level']} rule {rule['id']} {rule['status']}: "
                           + ", ".join(bad))
    verdict = "RELEASE_BLOCKED" if (blocking or contract_missing
                                    or (problem and not retroactive)) else "PASS"
    # Enforced whenever anything says the run is a release: its tier, the tier its contract
    # was made for, or its quality class - a design stating mvp never softens a release run.
    contract_tier = ((contract or {}).get("facets") or {}).get("tier")
    releasable = (tier not in (None, "mvp") or contract_tier not in (None, "mvp")
                  or run_class == "release")
    if retroactive:
        mode, why = "advisory", ("pre-knowledge run: it made no knowledge-contract, so its "
                                 "rules were resolved now from what it pinned - shown, never "
                                 "changing its decision")
    elif not releasable:
        mode, why = "advisory", (f"development build (tier {tier or 'none'}): never a "
                                 "release, so its compliance is shown and holds nothing")
    else:
        mode, why = "enforcing", None
    routes = set()
    for rule in rules:
        if rule["blocks"]:
            routes |= _route(rule)
    if (contract_missing or problem) and not routes:
        routes.add("develop")
    measured = [c for r in rules for c in r["checks"]]
    contract_block = {"artifact_id": (contract_ref or {}).get("artifact_id"),
                      "content_hash": (contract_ref or {}).get("content_hash"),
                      "retroactive": bool(retroactive)}
    section = {
        "mode": mode,
        "advisory_reason": why,
        "contract": contract_block,
        "versions": dict((contract or {}).get("versions") or {}),
        "facets": dict((contract or {}).get("facets") or {}),
        "counts": _counts(rules),
        "rules": rules,
        "not_applicable": [dict(e) for e in (contract or {}).get("not_applicable") or ()],
        "exceptions": [{**{k: e["exception"].get(k) for k in (
            "rule_id", "reason", "scope", "approved_by", "created_at", "expires_at")},
            "status": e["status"], "problems": e["problems"]} for e in judged],
        "regression": {
            "checks_run": sum(1 for c in measured if c["status"] in ("PASS", "FAIL")),
            "checks_passed": sum(1 for c in measured if c["status"] == "PASS"),
            "checks_failed": sum(1 for c in measured if c["status"] == "FAIL"),
            "checks_unmeasured": sum(1 for c in measured if c["status"] == "UNMEASURED"),
            "suite": list((contract or {}).get("regression_suite") or ()),
            "suite_run_here": False,
            "note": "the build is held by the rules' checks, run by the gates above; the "
                    "rules' tests are the Factory's own (wgf test-core, CI), not run in a "
                    "game run"},
        "lessons_applied": [r["id"] for r in rules],
        "new_lessons": [dict(c) for c in candidates or () if isinstance(c, dict)],
        "blocking": blocking,
        "warnings": [r["id"] for r in rules if r["warning"]],
        "reasons": reasons,
        "routes": [r for r in ROUTE_ORDER if r in routes],
        "verdict": verdict,
        "holds_release": mode == "enforcing" and verdict == "RELEASE_BLOCKED",
    }
    if problem:
        section["problem"] = problem
    if contract_missing:
        section["contract_missing"] = contract_missing
    return section


def bind_self(section, artifact_id):
    """Cite the quality-report being made (its own criteria) by its artifact id."""
    for rule in (section or {}).get("rules") or ():
        for check in rule.get("checks") or ():
            evidence = check.get("evidence")
            if isinstance(evidence, dict) and evidence.get("self"):
                evidence["artifact_id"] = artifact_id
    return section


def apply(report, section):
    """The section's effect on `report` (a quality-report body, before it is sealed): an
    enforcing RELEASE_BLOCKED makes a release decision not-release, with the rule ids as its
    reasons, and a PASS verdict FAIL, routed by the producers of what failed or is missing.
    Advisory compliance changes nothing. Returns True when the report changed."""
    if not section or not section.get("holds_release"):
        return False
    decision = report.setdefault("release_decision", {"decision": "not-release",
                                                      "reasons": []})
    text = ("KNOWLEDGE: the build does not satisfy the run's knowledge-contract - "
            + "; ".join(section.get("reasons") or ["a rule is not satisfied"]))
    decision.setdefault("reasons", []).insert(0, text)
    if decision.get("decision") in ("release", "development"):
        # A development decision here is a release-class run whose design stated mvp: it is
        # held like a release, never shipped as development.
        decision["decision"] = "not-release"
    if report.get("verdict") == "PASS":
        report["verdict"] = "FAIL"
        routes = list(report.get("routes") or [])
        for route in section.get("routes") or ["develop"]:
            if route not in routes:
                routes.append(route)
        report["routes"] = [r for r in ROUTE_ORDER if r in routes]
    return True


# ------------------------------------------------------------------------ run plumbing


def run_exceptions(context):
    """The knowledge exceptions a person granted the run: [knowledge-exception record], one
    per `EXCEPTION_EVENT` operator event. The event is the budget raise's shape
    (wgflib.budget): {"event": EXCEPTION_EVENT, "data": {"decided_by": <who ran the
    resume>, "decided_at", "resume_nonce", "exception": <knowledge-exception record>}},
    followed by the WORKFLOW_RESUMED event of the same resume (the same `resume_nonce`).

    The event is read by the knowledge module's one reader
    (wgf_knowledge.exceptions.recorded), never here. The record is never trusted about its
    approver. One whose event is not a person's - `decided_by` absent or `automation`, not
    corroborated by its resume, a record whose approver is not a person by name - is passed
    on with `approved_by.mode` `unverified` and why, so it is listed refused, never
    honoured."""
    from wgf_knowledge import exceptions as knowledge_exceptions
    read = getattr(context, "read_events", None)
    if not callable(read):
        return []
    try:
        events = [e for e in read() or [] if isinstance(e, dict)]
    except Exception:  # noqa: BLE001 - an unreadable log grants nothing
        return []
    out = []
    issued = knowledge_exceptions.issued_nonces(getattr(context, "run_dir", None))
    for record, why in knowledge_exceptions.recorded(events, issued):
        if why:
            approved = record.get("approved_by") if isinstance(record.get("approved_by"),
                                                               dict) else {}
            record["approved_by"] = dict(approved, mode="unverified")
            record["_unverified"] = why
        out.append(record)
    return out


def retroactive_contract(lessons, tiers, design=None, strategy=None, tier=None, read=None,
                         root=None):
    """A contract body for a run that made none, resolved now from the knowledge it pinned
    (`lessons`, `tiers`) and its design, strategy and tier. Raises model.KnowledgeError when
    the knowledge cannot be resolved."""
    from wgf_knowledge import resolve as resolver
    from wgf_knowledge import versions as knowledge_versions
    from wgf_quality import registry
    try:
        checks, _ = registry.classify(tiers, root)
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        raise model.KnowledgeError(f"the check tiers cannot be classified ({exc})")
    facets = resolver.facets_from(design, strategy, tier)
    try:
        found = knowledge_versions.collect(read=read, root=root,
                                           platforms=facets.get("platforms") or ())
    except model.KnowledgeError:
        found = {}
    body = resolver.resolve(lessons, checks, tiers, facets, versions=found)
    return dict(body, versions=found)


def now_utc():
    return datetime.datetime.now(datetime.timezone.utc)


# ------------------------------------------------------------------------------ for people


def summary(section):
    """A few lines' worth: mode, verdict, counts by level, what blocks, exceptions."""
    if not isinstance(section, dict):
        return None
    by_level = (section.get("counts") or {}).get("by_level") or {}
    return {"mode": section.get("mode"), "verdict": section.get("verdict"),
            "holds_release": section.get("holds_release"),
            "retroactive": (section.get("contract") or {}).get("retroactive"),
            "advisory_reason": section.get("advisory_reason"),
            "by_level": {k: {"applicable": v.get("applicable"),
                             "satisfied": v.get("satisfied"), "failed": v.get("failed"),
                             "unmeasured": v.get("unmeasured"),
                             "excepted": v.get("excepted")}
                         for k, v in by_level.items() if v.get("applicable")},
            "blocking": list(section.get("blocking") or ()),
            "warnings": list(section.get("warnings") or ()),
            "exceptions": [f"{e.get('rule_id')} {e.get('status')}"
                           for e in section.get("exceptions") or ()],
            "new_lessons": len(section.get("new_lessons") or ())}


def _version_text(versions):
    parts = []
    factory = versions.get("factory") or {}
    if factory:
        parts.append(f"Factory {factory.get('version') or '?'}"
                     + (f" @ {str(factory.get('commit'))[:12]}" if factory.get("commit")
                        else ""))
    for key, label in (("quality_policy", "quality-policy"),
                       ("quality_benchmark", "quality-benchmark"),
                       ("quality_floor", "quality-floor"), ("lessons", "lessons"),
                       ("check_tiers", "check-tiers")):
        value = versions.get(key)
        if isinstance(value, dict):
            value = value.get("version")
        if value:
            parts.append(f"{label} {value}")
    workflow = versions.get("workflow")
    if isinstance(workflow, dict) and workflow.get("id"):
        parts.append(f"workflow {workflow['id']} v{workflow.get('version')}")
    return ", ".join(parts) or "not recorded"


def _evidence_text(evidence):
    if not evidence:
        return "no report"
    who = evidence.get("artifact_id") or evidence.get("artifact_type")
    digest = str(evidence.get("content_hash") or "")[:19] or "no hash"
    commit = str(evidence.get("commit") or "")[:12] or "-"
    return f"{who} ({digest}, commit {commit})"


def render_lines(section, width=110):
    """Plain lines for a terminal (G4, `wgf knowledge report`)."""
    if not isinstance(section, dict):
        return []
    lines = [f"Knowledge compliance: {section.get('verdict')} ({section.get('mode')})"]
    if section.get("advisory_reason"):
        lines.append(f"  advisory: {section['advisory_reason']}")
    lines.append(f"  versions: {_version_text(section.get('versions') or {})}")
    contract = section.get("contract") or {}
    if contract.get("artifact_id"):
        lines.append(f"  contract: {contract['artifact_id']} "
                     f"({str(contract.get('content_hash') or '')[:19]})")
    for level, row in ((section.get("counts") or {}).get("by_level") or {}).items():
        if not row.get("applicable"):
            continue
        lines.append(f"  {level:<13} {row['applicable']:>3} applicable: {row['satisfied']} "
                     f"satisfied, {row['failed']} failed, {row['unmeasured']} unmeasured, "
                     f"{row['excepted']} excepted, {row['not_applicable']} n/a"
                     + (f", {row['not_enforced']} not enforced" if row.get("not_enforced")
                        else ""))
    for rule in section.get("rules") or ():
        if rule["status"] in ("FAILED", "UNMEASURED", "EXCEPTED"):
            mark = "!" if rule.get("blocks") else "-"
            lines.append(f"  {mark} {rule['id']} ({rule['level']}) {rule['status']}"
                         + (f" [measured {rule.get('measured_status')}]"
                            if rule.get("measured_status") else ""))
            for check in rule["checks"]:
                if check["status"] in ("PASS", "NOT_APPLICABLE"):
                    continue
                text = (f"      {check['check']} {check['status']}: "
                        f"{_evidence_text(check.get('evidence'))}"
                        + (f" - {check['note']}" if check.get("note") else ""))
                lines.append(text[:width])
    for entry in section.get("exceptions") or ():
        who = (entry.get("approved_by") or {}).get("identifier") or "?"
        lines.append(f"  exception {entry.get('rule_id')} {entry.get('status').upper()} - by "
                     f"{who}, until {entry.get('expires_at')}: "
                     f"{str(entry.get('reason') or '')[:70]}"
                     + (f" ({'; '.join(entry['problems'])[:80]})" if entry.get("problems")
                        else ""))
    regression = section.get("regression") or {}
    lines.append(f"  checks: {regression.get('checks_run', 0)} run, "
                 f"{regression.get('checks_passed', 0)} passed, "
                 f"{regression.get('checks_failed', 0)} failed, "
                 f"{regression.get('checks_unmeasured', 0)} unmeasured; regression suite "
                 f"{len(regression.get('suite') or ())} test(s), held by the Factory's CI")
    for candidate in section.get("new_lessons") or ():
        lines.append(f"  new lesson candidate: {str(candidate.get('summary'))[:90]}")
    return lines


def render_markdown(section):
    """The section as a markdown document a person reads at the end of a run."""
    if not isinstance(section, dict):
        return ""
    out = ["# Knowledge compliance", ""]
    out.append(f"**Verdict: {section.get('verdict')}** ({section.get('mode')})"
               + (" - this holds the release." if section.get("holds_release") else ""))
    if section.get("advisory_reason"):
        out.append("")
        out.append(f"Advisory: {section['advisory_reason']}.")
    for reason in section.get("reasons") or ():
        out.append(f"- {reason}")
    out += ["", "## Versions", ""]
    out.append(_version_text(section.get("versions") or {}))
    contract = section.get("contract") or {}
    out.append("")
    out.append(f"Contract: `{contract.get('artifact_id') or 'resolved now'}` "
               f"`{contract.get('content_hash') or '-'}`"
               + (" (retroactive)" if contract.get("retroactive") else ""))
    facets = section.get("facets") or {}
    if facets:
        out.append("")
        out.append("Facets: " + ", ".join(f"{k} {v if v not in (None, []) else '-'}"
                                         for k, v in facets.items()))
    out += ["", "## Rules by level", "",
            "| Level | Applicable | Satisfied | Failed | Unmeasured | Excepted | N/A | "
            "Not enforced |",
            "|---|---|---|---|---|---|---|---|"]
    for level, row in ((section.get("counts") or {}).get("by_level") or {}).items():
        out.append(f"| {level} | {row['applicable']} | {row['satisfied']} | {row['failed']} | "
                   f"{row['unmeasured']} | {row['excepted']} | {row['not_applicable']} | "
                   f"{row['not_enforced']} |")
    out += ["", "## Every applicable rule", "",
            "| Rule | Level | Category | Status | Evidence |", "|---|---|---|---|---|"]
    for rule in section.get("rules") or ():
        cited = "; ".join(f"`{c['check']}` {c['status']} - {_evidence_text(c.get('evidence'))}"
                          for c in rule["checks"]) or (rule.get("gap") or "-")
        status = rule["status"] + (f" (measured {rule['measured_status']})"
                                   if rule.get("measured_status") else "")
        out.append(f"| {rule['id']} | {rule['level']} | {rule.get('category')} | {status} | "
                   f"{cited.replace('|', '/')} |")
    out += ["", "## Exceptions", ""]
    if not section.get("exceptions"):
        out.append("None.")
    for entry in section.get("exceptions") or ():
        who = (entry.get("approved_by") or {}).get("identifier") or "?"
        out.append(f"- {entry.get('rule_id')}: **{entry.get('status')}** - approved by {who} "
                   f"at {entry.get('created_at')}, expires {entry.get('expires_at')}. "
                   f"{entry.get('reason')}"
                   + (f" ({'; '.join(entry['problems'])})" if entry.get("problems") else ""))
    out += ["", "## Not applicable to this run", ""]
    for entry in section.get("not_applicable") or ():
        out.append(f"- {entry.get('id')}: {entry.get('why_not')}")
    if not section.get("not_applicable"):
        out.append("None.")
    regression = section.get("regression") or {}
    out += ["", "## Regression", "",
            f"Checks: {regression.get('checks_run', 0)} run, "
            f"{regression.get('checks_passed', 0)} passed, "
            f"{regression.get('checks_failed', 0)} failed, "
            f"{regression.get('checks_unmeasured', 0)} unmeasured.",
            "",
            f"Regression suite of the applicable rules: {len(regression.get('suite') or ())} "
            f"test(s). {regression.get('note') or ''}"]
    out += ["", "## Lessons applied", "",
            ", ".join(section.get("lessons_applied") or ()) or "None."]
    out += ["", "## New lesson candidates", ""]
    if not section.get("new_lessons"):
        out.append("None.")
    for candidate in section.get("new_lessons") or ():
        out.append(f"- {candidate.get('summary')}"
                   + (f" (proposed check `{candidate['proposed_check']}`)"
                      if candidate.get("proposed_check") else ""))
    return "\n".join(out) + "\n"

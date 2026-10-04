"""Score one build against the Factory quality contract (core/reference/quality-floor.yaml).

    contract(floor, benchmark, rubric)           the contract, with every bar resolved
    derive(contract, design, ...)                the criteria this game is held to: the
                                                 universal floor, its genre family's (or the
                                                 nearest ancestor's) and its rendering
                                                 dimension's
    build_identity(loaded)                       the build: shipped commit, development
                                                 commit, bundle digest
    evidence(contract, loaded, refs, build)      every report the scores read, current or stale
    score(contract, criteria, loaded, refs, tier, build, previous)
                                                 criteria, dimensions, findings, regression,
                                                 the release decision and the verdict

Pure functions over parsed data: no file, process or clock. Every number comes from the
contract or the benchmark it references; no consumer branches on a family or a game. An
evaluator kind is a way of reading a report (checks, verdict, scores, count, all), never a
game rule.
"""

import fnmatch

__all__ = ["ContractError", "contract", "tier_of", "derive", "build_identity", "evidence",
           "score", "ROUTE_ORDER", "STATUSES", "find"]

# The design must grow before the art is made again, the art before the build changes, and
# the store listing last (it is measured after G4).
ROUTE_ORDER = ("design-gap", "assets", "develop", "listing")
STATUSES = ("PASS", "FAIL", "UNMEASURED", "DEFERRED")
KINDS = ("checks", "verdict", "scores", "count", "all")
SEVERITIES = ("blocker", "warning")
# A check status the producer itself counts as measured: SKIPPED measured nothing.
MEASURED = ("PASS", "FAIL", "WARNING", "BLOCKED")
LISTING_PHASE = "listing"


class ContractError(ValueError):
    """The quality contract is malformed: nothing can be held to it, and nothing defaults."""


def find(data, path):
    """The value at a dotted `path` of `data`, or None."""
    node = data
    for part in str(path).split("."):
        if isinstance(node, dict):
            node = node.get(part)
        else:
            return None
    return node


def _bar(value, tier, references):
    """A minimum or maximum at `tier`: a number, `<reference>:<dotted path>`, or a per-tier
    mapping of either. None when the bar names nothing at `tier`."""
    if isinstance(value, dict):
        value = value.get(tier)
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str) and ":" in value:
        name, path = value.split(":", 1)
        if name not in references:
            raise ContractError(f"bar {value!r} names no reference {name!r}")
        found = find(references[name], path)
        if isinstance(found, dict):
            found = found.get(tier)
        if isinstance(found, bool) or not isinstance(found, (int, float)):
            raise ContractError(f"bar {value!r} reads {found!r} at tier {tier}, not a number")
        return found
    raise ContractError(f"bar {value!r} is neither a number nor a reference")


def _criteria_problems(where, criteria, dimensions):
    problems = []
    for index, criterion in enumerate(criteria or []):
        at = f"{where}[{index}]"
        if not isinstance(criterion, dict) or not criterion.get("id"):
            problems.append(f"{at}: a criterion needs an id")
            continue
        at = f"{where} {criterion['id']}"
        if criterion.get("dimension") not in dimensions:
            problems.append(f"{at}: dimension {criterion.get('dimension')!r} is not scored")
        evaluate = criterion.get("evaluate")
        if not isinstance(evaluate, dict) or evaluate.get("kind") not in KINDS \
                or not evaluate.get("report"):
            problems.append(f"{at}: evaluate needs a kind of {', '.join(KINDS)} and a report")
        severity = criterion.get("severity")
        if not isinstance(severity, dict) or not severity or any(
                v not in SEVERITIES for v in severity.values()):
            problems.append(f"{at}: severity must map a tier to blocker or warning")
        if criterion.get("route") not in ROUTE_ORDER:
            problems.append(f"{at}: route must be one of {', '.join(ROUTE_ORDER)}")
        if "minimum" not in criterion and "maximum" not in criterion:
            problems.append(f"{at}: a criterion needs a minimum or a maximum")
    return problems


def contract(floor, benchmark, rubric):
    """The contract: {"floor", "references", "dimensions"}. Raises ContractError."""
    if not isinstance(floor, dict) or not floor.get("version"):
        raise ContractError("the quality floor has no version")
    dimensions = floor.get("dimensions")
    if not isinstance(dimensions, dict) or not dimensions:
        raise ContractError("the quality floor scores no dimension")
    problems = _criteria_problems("universal", floor.get("universal"), dimensions)
    for family, entry in (floor.get("genres") or {}).items():
        problems += _criteria_problems(f"genres.{family}", (entry or {}).get("criteria"),
                                       dimensions)
    for render, entry in (floor.get("dimensions_contracts") or {}).items():
        problems += _criteria_problems(f"dimensions_contracts.{render}",
                                       (entry or {}).get("criteria"), dimensions)
    if problems:
        raise ContractError("; ".join(problems[:6]))
    references = {"quality-benchmark": benchmark or {}, "visual-qa-rubric": rubric or {}}
    return {"floor": floor, "references": references, "dimensions": dimensions}


def tier_of(design, strategy):
    """The quality tier the build is held to: the design's, else the strategy's, else None."""
    content = ((design or {}).get("build_spec") or {}).get("content") or {}
    tier = content.get("quality_tier") if isinstance(content, dict) else None
    if tier:
        return tier
    model = (((strategy or {}).get("concept") or {}).get("content_model") or {})
    return model.get("quality_tier") or None


def derive(spec, design, render=None, family_of_node=None):
    """(criteria [(layer, criterion)], contract summary) for `design`.

    The genre contract is the design's family's; a family the floor does not list falls back
    to the family that owns the nearest ancestor of the design's genre node
    (`family_of_node(node)`, walking the research vocabulary's tree from the node's parent),
    and always to the universal floor. The render contract is the game's dimension's."""
    floor = spec["floor"]
    genres = floor.get("genres") or {}
    genre = (design or {}).get("genre") or {}
    family = genre.get("family") if isinstance(genre, dict) else None
    node = genre.get("node") if isinstance(genre, dict) else None
    chosen, resolved_by, via = None, "none", None
    if family in genres:
        chosen, resolved_by = family, "family"
    elif family_of_node is not None and node:
        for candidate, through in family_of_node(node):
            if candidate in genres and candidate != family:
                chosen, resolved_by, via = candidate, "ancestor", through
                break
    criteria = [("universal", c) for c in floor.get("universal") or []]
    if chosen:
        criteria += [("genre", c) for c in (genres[chosen] or {}).get("criteria") or []]
    renders = floor.get("dimensions_contracts") or {}
    if render in renders:
        criteria += [("render", c) for c in (renders[render] or {}).get("criteria") or []]
    summary = {"universal": len(floor.get("universal") or []), "family": family,
               "genre": chosen, "resolved_by": resolved_by, "via_node": via,
               "render": render if render in ("2d", "3d") else None,
               "criteria": len(criteria)}
    return criteria, summary


def build_identity(loaded):
    """{commit, development_commit, digest}: the verified commit release would ship, the
    development commit it sits on, and the verified bundle's digest."""
    qa = (loaded.get("qa-report") or {}).get("build_ref") or {}
    vr = loaded.get("verification-report") or {}
    sdk = (loaded.get("sdk-report") or {}).get("build_ref") or {}
    proto = (loaded.get("prototype-report") or {}).get("build_ref") or {}
    shipped = qa.get("commit_sha") or (vr.get("commit") or {}).get("sha") or sdk.get("commit_sha")
    developed = sdk.get("base_commit_sha") or proto.get("commit_sha") or shipped
    digest = (vr.get("build_artifact") or {}).get("content_hash")
    return {"commit": shipped, "development_commit": developed, "digest": digest}


def _same(a, b):
    if not a or not b:
        return False
    if min(len(a), len(b)) < 7:
        return a == b
    return a.startswith(b) or b.startswith(a)


def evidence(spec, loaded, refs, build):
    """[entry] for every report the contract reads that the run holds: the commit it
    describes, the one it had to describe, current or stale."""
    out = []
    for artifact_type, rule in (spec["floor"].get("build_evidence") or {}).items():
        if artifact_type not in loaded:
            continue
        report = loaded[artifact_type] or {}
        of = (rule or {}).get("of")
        expected = build.get("commit") if of == "shipped" else build.get("development_commit")
        commit = find(report, (rule or {}).get("commit") or "commit")
        status = "current"
        if commit and expected and not _same(commit, expected):
            status = "stale"
        ref = refs.get(artifact_type)
        out.append({"artifact_type": artifact_type,
                    "artifact_id": (report.get("provenance") or {}).get("artifact_id"),
                    "content_hash": getattr(ref, "content_hash", None),
                    "commit": commit, "expected_commit": expected, "of": of,
                    "status": status})
    return out


def _matches(check_id, patterns):
    return any(fnmatch.fnmatchcase(str(check_id), str(p)) for p in patterns or ())


def _where(item, where):
    for key, wanted in (where or {}).items():
        value = item.get(key) if isinstance(item, dict) else None
        options = wanted if isinstance(wanted, list) else [wanted]
        if not any(_matches(value, [o]) if isinstance(o, str) else value == o
                   for o in options):
            return False
    return True


def _ratio(passed, total):
    return round(passed / total, 4) if total else None


def _measure(evaluate, report):
    """(observed, share 0..1 or None, measured) for one evaluator over `report`."""
    kind = evaluate["kind"]
    if kind == "checks":
        required_only = evaluate.get("required_only", True)
        checks = [c for c in report.get("checks") or [] if isinstance(c, dict)
                  and _matches(c.get("id"), evaluate.get("checks"))
                  and c.get("status") in MEASURED
                  and (c.get("required") or not required_only)]
        projects = evaluate.get("projects")
        if projects:
            shares = {}
            for project in projects:
                own = [c for c in checks if c.get("project") in (project, None)]
                if own:
                    shares[project] = _ratio(sum(c["status"] == "PASS" for c in own), len(own))
            if not shares:
                return None, None, False
            missing = [p for p in projects if p not in shares]
            worst = min(shares.values())
            observed = {"by_viewport": shares}
            if missing:
                observed["unmeasured_viewports"] = missing
                return observed, worst, False
            return observed, worst, True
        if not checks:
            return None, None, False
        passed = sum(c["status"] == "PASS" for c in checks)
        failing = sorted({c.get("id") for c in checks if c["status"] != "PASS"})
        observed = {"passed": passed, "of": len(checks)}
        if failing:
            observed["below"] = failing
        return observed, _ratio(passed, len(checks)), True
    if kind == "verdict":
        value = find(report, evaluate.get("field") or "verdict")
        if value is None:
            return None, None, False
        return value, 1.0 if value in (evaluate.get("pass") or []) else 0.0, True
    if kind == "scores":
        values = find(report, evaluate.get("field") or "scores") or {}
        numbers = [values.get(k) for k in evaluate.get("keys") or []
                   if isinstance(values, dict) and isinstance(values.get(k), (int, float))
                   and not isinstance(values.get(k), bool)]
        if not numbers:
            return None, None, False
        if evaluate.get("aggregate", "min") == "mean":
            return round(sum(numbers) / len(numbers), 3), None, True
        return min(numbers), None, True
    items = find(report, evaluate.get("field"))
    if not isinstance(items, list):
        return None, None, False
    items = [i for i in items if _where(i, evaluate.get("where"))]
    if kind == "count":
        return len(items), None, True
    # all
    if not items:
        return None, None, False
    met = sum(1 for i in items if isinstance(i, dict)
              and i.get(evaluate.get("key")) == evaluate.get("equals"))
    return {"met": met, "of": len(items)}, _ratio(met, len(items)), True


def _judge(criterion, observed, share, tier, references):
    """(status, score 0-100, expected) of a measured criterion."""
    minimum = _bar(criterion.get("minimum"), tier, references)
    maximum = _bar(criterion.get("maximum"), tier, references)
    expected = {}
    if minimum is not None:
        expected["minimum"] = minimum
    if maximum is not None:
        expected["maximum"] = maximum
    if criterion.get("preferred") is not None:
        expected["preferred"] = criterion["preferred"]
    kind = criterion["evaluate"]["kind"]
    if kind in ("checks", "verdict", "all"):
        bar = minimum if minimum is not None else 1.0
        ok = share is not None and share >= bar
        return ("PASS" if ok else "FAIL"), round(100 * (share or 0.0), 1), expected
    value = observed
    if maximum is not None:
        ok = value <= maximum
        score = 100.0 if ok else round(100 * max(0.0, 1 - (value - maximum) / max(value, 1)), 1)
        if minimum is not None and value < minimum:
            ok, score = False, round(100 * value / minimum, 1) if minimum else 0.0
        return ("PASS" if ok else "FAIL"), score, expected
    if minimum is None:
        return "PASS", 100.0, expected
    ok = value >= minimum
    score = 100.0 if ok else round(100 * max(0.0, value) / minimum, 1) if minimum else 0.0
    return ("PASS" if ok else "FAIL"), min(100.0, score), expected


def _ref_of(entry):
    return {"artifact_type": entry["artifact_type"], "artifact_id": entry.get("artifact_id"),
            "content_hash": entry.get("content_hash"), "commit": entry.get("commit")}


def _evaluate(layer, criterion, loaded, evidence_by_type, tier, references, deferred):
    severity = (criterion.get("severity") or {}).get(tier)
    if severity is None:
        return None
    evaluate = criterion["evaluate"]
    report_type = evaluate["report"]
    base = {"id": criterion["id"], "layer": layer, "dimension": criterion["dimension"],
            "severity": severity, "owner": criterion.get("owner") or "",
            "route": criterion["route"], "basis": str(criterion.get("basis") or "proposed")}
    entry = evidence_by_type.get(report_type)
    base["evidence"] = [_ref_of(entry)] if entry else []
    if report_type in deferred and report_type not in loaded:
        expected = {}
        try:
            for key in ("minimum", "maximum"):
                bar = _bar(criterion.get(key), tier, references)
                if bar is not None:
                    expected[key] = bar
        except ContractError:
            raise
        return dict(base, status="DEFERRED", score=None, observed=None, expected=expected,
                    summary=f"{report_type} does not exist yet: measured after the store "
                            "listing is made")
    report = loaded.get(report_type)
    if not isinstance(report, dict):
        expected = {k: _bar(criterion.get(k), tier, references)
                    for k in ("minimum", "maximum") if criterion.get(k) is not None}
        expected = {k: v for k, v in expected.items() if v is not None}
        return dict(base, status="UNMEASURED", score=None, observed=None, expected=expected,
                    summary=f"no {report_type} in this run: {criterion.get('metric')} was not "
                            "measured, which is never a pass")
    observed, share, measured = _measure(evaluate, report)
    if not measured:
        expected = {k: _bar(criterion.get(k), tier, references)
                    for k in ("minimum", "maximum") if criterion.get(k) is not None}
        expected = {k: v for k, v in expected.items() if v is not None}
        return dict(base, status="UNMEASURED", score=None, observed=observed, expected=expected,
                    summary=f"{report_type} reports nothing for {criterion.get('metric')}: "
                            "unmeasured, never a pass")
    status, value, expected = _judge(criterion, observed, share, tier, references)
    summary = f"{criterion.get('metric')}: observed {_text(observed)}"
    if expected.get("minimum") is not None:
        summary += f", minimum {_text(expected['minimum'])}"
    if expected.get("maximum") is not None:
        summary += f", maximum {_text(expected['maximum'])}"
    return dict(base, status=status, score=value, observed=observed, expected=expected,
                summary=summary)


def _text(value):
    if isinstance(value, dict):
        if "by_viewport" in value:
            return ", ".join(f"{k} {round(100 * v)}%" for k, v in value["by_viewport"].items()) \
                + (f" (unmeasured: {', '.join(value['unmeasured_viewports'])})"
                   if value.get("unmeasured_viewports") else "")
        if "passed" in value:
            return f"{value['passed']} of {value['of']} pass" + (
                f" (below: {', '.join(value['below'][:6])})" if value.get("below") else "")
        if "met" in value:
            return f"{value['met']} of {value['of']}"
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


def _finding(result, build, assets=None):
    severity = "blocker" if result["severity"] == "blocker" else "minor"
    finding = {
        "id": f"quality:{result['id']}", "criterion": result["id"],
        "dimension": result["dimension"], "layer": result["layer"], "severity": severity,
        "summary": result["summary"], "evidence": list(result.get("evidence") or []),
        "build": {"commit": build.get("commit"), "digest": build.get("digest")},
        "expected": dict(result.get("expected") or {}), "observed": result.get("observed"),
        "owner": result["owner"], "route": result["route"], "status": "open",
        "first_seen": build.get("commit"), "closed_on": None, "regressed": False,
    }
    if assets:
        finding["assets"] = sorted(assets)
    return finding


def _failing_assets(loaded, result):
    """Asset ids the failing production-quality checks behind `result` name, for the assets
    step's re-entry plan."""
    if result["route"] != "assets":
        return []
    names = set()
    for entry in result.get("evidence") or []:
        report = loaded.get(entry["artifact_type"]) or {}
        for check in report.get("checks") or []:
            if isinstance(check, dict) and check.get("status") not in ("PASS", None):
                names.update(a for a in check.get("assets") or [] if isinstance(a, str))
    return sorted(names)


def score(spec, criteria, loaded, refs, tier, build, previous=None, evidence_entries=None,
          deferred=("listing-validation-report",)):
    """The scorecard. `tier`: the quality tier (None is held as mvp). `previous`: the run's
    previous quality-report, for finding lifecycle and regression."""
    held = tier or "mvp"
    references = spec["references"]
    entries = evidence_entries if evidence_entries is not None else \
        evidence(spec, loaded, refs, build)
    by_type = {e["artifact_type"]: e for e in entries}
    results = []
    for layer, criterion in criteria:
        result = _evaluate(layer, criterion, loaded, by_type, held, references, deferred)
        if result is not None:
            results.append(result)

    # Findings: every criterion below its minimum (or unmeasured), with the lifecycle of the
    # previous report's findings - closed only on a newer build's re-measurement.
    findings = {}
    for result in results:
        if result["status"] in ("FAIL", "UNMEASURED"):
            findings[result["id"]] = _finding(result, build, _failing_assets(loaded, result))
    by_id = {r["id"]: r for r in results}
    previous_findings = {f.get("criterion"): f for f in (previous or {}).get("findings") or []
                         if isinstance(f, dict) and f.get("status") == "open"}
    previous_criteria = {c.get("id"): c for c in (previous or {}).get("criteria") or []
                         if isinstance(c, dict)}
    previous_build = ((previous or {}).get("build") or {}).get("commit")
    newer = bool(previous_build) and not _same(previous_build, build.get("commit"))
    carried = []
    for criterion_id, old in previous_findings.items():
        if criterion_id in findings:
            findings[criterion_id]["first_seen"] = old.get("first_seen") or previous_build
            continue
        now = by_id.get(criterion_id)
        if now is None:
            # The criterion no longer applies to this game at this tier: nothing to carry.
            continue
        if now["status"] == "PASS" and newer:
            closed = dict(old, status="closed",
                          closed_on={"commit": build.get("commit"), "digest": build.get("digest")})
            findings[criterion_id] = closed
            continue
        if now["status"] == "DEFERRED":
            continue
        # Passing again on the build it was raised on is no re-measurement: it stays open.
        kept = dict(old)
        kept["summary"] = (str(old.get("summary") or "") + " - still open: a finding closes "
                           "only when a newer build is measured at the minimum")[:600]
        findings[criterion_id] = kept
        carried.append(criterion_id)
    regressed = []
    for criterion_id, finding in findings.items():
        before = previous_criteria.get(criterion_id)
        if finding["status"] == "open" and before is not None and before.get("status") == "PASS" \
                and newer:
            finding["regressed"] = True
            regressed.append(criterion_id)

    # Dimensions: the mean of the applied, measured criteria; at or above the floor only when
    # the score reaches min_score AND every blocker met its minimum AND no blocker finding is
    # still open. No average carries a dimension past a blocker.
    previous_dims = {d.get("id"): d for d in (previous or {}).get("dimensions") or []
                     if isinstance(d, dict)}
    dimensions, below, dropped, deferred_dims = [], [], [], []
    for dim_id, dim in spec["dimensions"].items():
        own = [r for r in results if r["dimension"] == dim_id]
        min_score = _bar(dim.get("min_score"), held, references)
        measured = [r for r in own if r["status"] in ("PASS", "FAIL")]
        score_value = (round(sum(r["score"] for r in measured) / len(measured), 1)
                       if measured else None)
        blockers = sorted(r["id"] for r in own if r["severity"] == "blocker"
                          and r["status"] in ("FAIL", "UNMEASURED"))
        still_open = sorted(c for c in carried if findings[c]["dimension"] == dim_id
                            and findings[c].get("severity") == "blocker")
        reason = None
        if own and all(r["status"] == "DEFERRED" for r in own):
            status = "DEFERRED"
            reason = "measured once the store listing exists (listing-validation)"
            deferred_dims.append(dim_id)
        elif blockers or still_open:
            status = "BELOW_FLOOR"
            reason = ("blocker criteria below their minimum: " + ", ".join(blockers)
                      if blockers else "")
            if still_open:
                reason = (reason + "; " if reason else "") + \
                    "open findings not yet re-measured on a newer build: " + ", ".join(still_open)
        elif score_value is None:
            status = "UNMEASURED"
            reason = "no criterion measured it: unmeasured, never a pass"
        elif min_score is not None and score_value < min_score:
            status = "BELOW_FLOOR"
            reason = f"score {score_value:g} below the floor {min_score:g}"
        else:
            status = "PASS"
        if status == "UNMEASURED" and held == "release":
            # At the release tier nothing unmeasured is at its floor.
            reason += ": at the release tier that is below the floor"
            below.append(dim_id)
        elif status == "BELOW_FLOOR":
            below.append(dim_id)
        before = previous_dims.get(dim_id) or {}
        previous_score = before.get("score")
        if isinstance(previous_score, (int, float)) and newer and (
                score_value is None or score_value < previous_score):
            dropped.append({"dimension": dim_id, "from": previous_score, "to": score_value})
        dimensions.append({
            "id": dim_id, "label": dim.get("label") or dim_id, "score": score_value,
            "min_score": min_score, "preferred": dim.get("preferred"), "status": status,
            "regression": dim_id in below,
            "previous_score": previous_score if isinstance(previous_score, (int, float)) else None,
            "blockers_failed": blockers,
            "open_findings": sorted(f["id"] for f in findings.values()
                                    if f["dimension"] == dim_id and f["status"] == "open"),
            "criteria": [r["id"] for r in own], "owner": dim.get("owner") or "",
            "reason": reason})

    measured_scores = [d["score"] for d in dimensions if d["score"] is not None]
    overall = round(sum(measured_scores) / len(measured_scores), 1) if measured_scores else None

    # Routes: the findings that hold a dimension below its floor.
    holding = [f for f in findings.values() if f["status"] == "open"
               and f["dimension"] in below
               and (f["severity"] == "blocker" or not any(
                   g["severity"] == "blocker" and g["dimension"] == f["dimension"]
                   and g["status"] == "open" for g in findings.values()))]
    routes = [r for r in ROUTE_ORDER if any(f["route"] == r for f in holding)]
    if below and not routes:
        routes = ["develop"]

    reasons = []
    if held == "release":
        if below:
            decision = "not-release"
            reasons += [f"{d['id']} below its floor: {d['reason']}" for d in dimensions
                        if d["status"] == "BELOW_FLOOR"]
        else:
            decision = "release"
        reasons += [f"{d['id']} unmeasured: {d['reason']}" for d in dimensions
                    if d["status"] == "UNMEASURED"]
        if deferred_dims:
            reasons.append("deferred to the store listing's validation, which release "
                           "requires: " + ", ".join(deferred_dims))
    else:
        decision = "development"
        reasons.append(f"quality tier {tier or 'none (held as mvp)'}: a development build, "
                       "never a release")
        reasons += [f"{d['id']} below its floor: {d['reason']}" for d in dimensions
                    if d["status"] == "BELOW_FLOOR"]
    verdict = "FAIL" if below or (held == "release" and decision != "release") else "PASS"
    return {
        "criteria": results,
        "findings": sorted(findings.values(), key=lambda f: (f["status"] != "open", f["id"])),
        "dimensions": dimensions,
        "regression": {"below_floor": below, "dropped": dropped,
                       "regressed_criteria": sorted(regressed)},
        "overall_score": overall,
        "release_decision": {"decision": decision, "reasons": reasons},
        "failed": below,
        "routes": routes if verdict == "FAIL" else [],
        "deferred": deferred_dims,
        "verdict": verdict,
    }

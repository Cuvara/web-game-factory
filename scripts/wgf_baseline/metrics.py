"""Generic metrics read from a build's reports, and their deltas against the accepted build.

Every gate holds a build to an absolute floor, so a build can pass all of them and still be
worse than the one a person accepted: observed 2026-10-05, where the reports the Factory
already held said so - the 3D game's good play won in 6 inputs where the accepted build took
60, its frames' mean luminance went from 122 to 184; the 2D game's good play now lost, its
targets drew at half the area. Nothing compared them. This module does, from
core/reference/accepted-baseline.yaml `metrics`:

    extract(spec, reports)      {metric id: {project: value}} for one build's reports
    compare(spec, accepted, candidate, approved=False)
                                [result]: each metric of the accepted build against the
                                candidate's, PASS | FAIL | UNMEASURED | SKIPPED

A metric is read by a `read` block over one report - never a game rule:

    {report, check, field}             a playability-style check's value, per project
    {report, check, field, derive}     a derived value: `unit_durations` (the time between
                                       the traverse's unit transitions), `mean_of: <key>`
                                       (the mean of a key over a mapping's values)
    {report, check, field, each: <k>}  one metric per key of a mapping (an entity role):
                                       `<id>.<key>`, the value at `<key>.<each>`
    {report, field, each_key: true}    one metric per key of a mapping that is not a check
                                       (visual-qa `scores`), project `all`

and compared one of four ways:

    equal     the candidate's value is the accepted one (good play's outcome)
    ratio     candidate / accepted inside `band` [low, high]
    delta     |candidate - accepted| at most `max_delta`
    drop      candidate at least accepted - `max_drop`

A metric the accepted build did not measure is SKIPPED (nothing to hold it to), with the
reason. A metric it measured and the candidate did not is UNMEASURED: never a pass. A role
or key the accepted build had and the candidate lost is a FAIL (`gone`). `waived_by_
replacement: true` metrics (the look and tuning a person may change when they approve a
replacement of accepted work) are SKIPPED once a replacement was approved.
"""

import math

__all__ = ["extract", "compare", "ProjectValues", "unit_durations"]

ALL = "all"


def _find(data, dotted):
    node = data
    for part in str(dotted or "").split(".") if dotted else []:
        if isinstance(node, dict):
            node = node.get(part)
        else:
            return None
    return node


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) \
        and math.isfinite(value)


def unit_durations(transitions):
    """{unit index: ms} for the units the traverse left: each transition's `at_ms` minus the
    previous one's (the first unit from 0)."""
    out, before = {}, 0
    for entry in transitions or []:
        if not isinstance(entry, dict) or not _number(entry.get("at_ms")):
            return out
        out[str(entry.get("from"))] = entry["at_ms"] - before
        before = entry["at_ms"]
    return out


def _derive(value, derive):
    if not derive:
        return value
    if derive == "unit_durations":
        durations = unit_durations(value)
        return durations or None
    if isinstance(derive, dict) and derive.get("mean_of"):
        key = derive["mean_of"]
        numbers = [v.get(key) for v in (value or {}).values()
                   if isinstance(v, dict) and _number(v.get(key))] if isinstance(value, dict) \
            else []
        return round(sum(numbers) / len(numbers), 3) if numbers else None
    return None


class ProjectValues(dict):
    """{project: value} of one metric."""


def extract(spec, reports):
    """{metric id: {project: value}} - every metric of `spec` the reports carry."""
    out = {}
    default = list(spec.get("projects") or ["desktop", "mobile"])
    for metric in spec.get("metrics") or []:
        projects = list(metric.get("projects") or default)
        read = metric.get("read") or {}
        report = reports.get(read.get("report"))
        if not isinstance(report, dict):
            continue
        if read.get("check"):
            for check in report.get("checks") or []:
                if not isinstance(check, dict) or check.get("id") != read["check"]:
                    continue
                project = check.get("project") or ALL
                if project not in projects and project != ALL:
                    continue
                if check.get("status") not in ("PASS", "FAIL", "WARNING"):
                    continue  # SKIPPED and BLOCKED measured nothing
                value = _find(check, read.get("field"))
                if read.get("each"):
                    if isinstance(value, dict):
                        for key, item in value.items():
                            found = _find(item, read["each"]) if isinstance(item, dict) \
                                else None
                            if _number(found):
                                out.setdefault(f"{metric['id']}.{key}", ProjectValues())[
                                    project] = found
                    continue
                value = _derive(value, read.get("derive"))
                if value is not None:
                    out.setdefault(metric["id"], ProjectValues())[project] = value
        elif read.get("each_key"):
            value = _find(report, read.get("field"))
            if isinstance(value, dict):
                for key, item in value.items():
                    if _number(item):
                        out.setdefault(f"{metric['id']}.{key}", ProjectValues())[ALL] = item
        else:
            value = _derive(_find(report, read.get("field")), read.get("derive"))
            if value is not None:
                out.setdefault(metric["id"], ProjectValues())[ALL] = value
    return out


def _metric_for(spec, metric_id):
    for metric in spec.get("metrics") or []:
        if metric_id == metric["id"] or metric_id.startswith(metric["id"] + "."):
            return metric
    return None


def _judge(metric, accepted, candidate):
    """(status, delta record, why) for one project's values."""
    how = metric.get("compare")
    if isinstance(accepted, dict) and isinstance(candidate, dict):
        # per unit (unit_durations): the mean over the units both builds report
        common = sorted(set(accepted) & set(candidate))
        if not common:
            return "UNMEASURED", None, "no unit both builds' traverses left"
        accepted = sum(accepted[k] for k in common) / len(common)
        candidate = sum(candidate[k] for k in common) / len(common)
    if how == "equal":
        ok = accepted == candidate
        return ("PASS" if ok else "FAIL"), {"accepted": accepted, "candidate": candidate}, \
            None if ok else f"was {accepted!r}, now {candidate!r}"
    if not (_number(accepted) and _number(candidate)):
        return "UNMEASURED", None, "not a number on both builds"
    if how == "ratio":
        low, high = metric.get("band") or [None, None]
        if accepted == 0:
            ok = candidate == 0
            return ("PASS" if ok else "FAIL"), {"ratio": None}, \
                None if ok else f"was 0, now {candidate:g}"
        ratio = round(candidate / accepted, 4)
        ok = (low is None or ratio >= low) and (high is None or ratio <= high)
        return ("PASS" if ok else "FAIL"), {"ratio": ratio}, \
            None if ok else f"{accepted:g} -> {candidate:g} (x{ratio:g}, band {low}-{high})"
    if how == "delta":
        delta = round(candidate - accepted, 4)
        ok = abs(delta) <= float(metric.get("max_delta"))
        return ("PASS" if ok else "FAIL"), {"delta": delta}, \
            None if ok else (f"{accepted:g} -> {candidate:g} ({delta:+g}, at most "
                             f"{metric.get('max_delta')} either way)")
    if how == "drop":
        delta = round(candidate - accepted, 4)
        ok = delta >= -float(metric.get("max_drop"))
        return ("PASS" if ok else "FAIL"), {"delta": delta}, \
            None if ok else (f"{accepted:g} -> {candidate:g} ({delta:+g}, a drop of at most "
                             f"{metric.get('max_drop')})")
    return "UNMEASURED", None, f"unknown comparison {how!r}"


def compare(spec, accepted, candidate, approved=False):
    """[result] for every metric the accepted build measured (and those only the candidate
    did, SKIPPED): {id, metric, label, project, accepted, candidate, status, delta, summary,
    dimension, severity, route}."""
    results = []
    ids = sorted(set(accepted) | set(candidate))
    for metric_id in ids:
        metric = _metric_for(spec, metric_id)
        if metric is None:
            continue
        key = metric_id[len(metric["id"]) + 1:] if metric_id != metric["id"] else None
        base = {"id": metric_id, "metric": metric["id"],
                "label": (metric.get("label") or metric["id"]) + (f" [{key}]" if key else ""),
                "dimension": metric.get("dimension") or "gameplay",
                "severity": metric.get("severity") or "blocker",
                "route": metric.get("route") or "develop",
                "compare": metric.get("compare"),
                "dimension_by_key": metric.get("dimension_by_key")}
        for key in ("band", "max_delta", "max_drop"):
            if metric.get(key) is not None:
                base[key] = metric[key]
        before = accepted.get(metric_id) or {}
        after = candidate.get(metric_id) or {}
        if not before:
            results.append(dict(base, project=ALL, accepted=None,
                                candidate=dict(after) or None, status="SKIPPED",
                                summary=f"{base['label']}: the accepted build's reports do "
                                        "not measure it - nothing to hold the candidate to"))
            continue
        if approved and metric.get("waived_by_replacement"):
            results.append(dict(base, project=ALL, accepted=dict(before),
                                candidate=dict(after) or None, status="SKIPPED",
                                summary=f"{base['label']}: waived - a person approved "
                                        "replacing the accepted work"))
            continue
        for project in sorted(before):
            value = before[project]
            if project not in after:
                gone = bool(read_each(metric)) and any(
                    k.startswith(metric["id"] + ".") for k in candidate)
                status = "FAIL" if gone else "UNMEASURED"
                summary = (f"{base['label']} ({project}): the accepted build drew it, the "
                           "candidate does not" if gone else
                           f"{base['label']} ({project}): measured on the accepted build "
                           "({}) but not on the candidate - unmeasured, never a pass"
                           .format(_text(value)))
                results.append(dict(base, project=project, accepted=value, candidate=None,
                                    status=status, summary=summary,
                                    delta={"gone": True} if gone else None))
                continue
            status, delta, why = _judge(metric, value, after[project])
            summary = f"{base['label']} ({project}): " + (
                why if why else f"{_text(value)} -> {_text(after[project])}, within tolerance")
            results.append(dict(base, project=project, accepted=value,
                                candidate=after[project], status=status, delta=delta,
                                summary=summary))
    return results


def read_each(metric):
    read = metric.get("read") or {}
    return read.get("each") or read.get("each_key")


def _text(value):
    if isinstance(value, dict):
        return "{" + ", ".join(f"{k}: {_text(v)}" for k, v in list(value.items())[:6]) + "}"
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)

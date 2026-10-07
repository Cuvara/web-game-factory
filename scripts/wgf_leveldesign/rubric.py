"""The level-design rubric, the verdict a critic writes, its strict check, and the decision.

The critic writes:

    {
      "units": [{"unit_id": "<every sampled unit>",
                 "scores": {"<every rubric dimension>": 0..5 | null, ...},
                 "score_reasons": {"<dimension>": "what you saw, in which frame"},
                 "comment": "..."}],
      "findings": [{"id": "short-kebab-id", "severity": "blocker|major|minor",
                    "unit": "<unit id>" | null, "frame": "<unit id>/<moment>" | null,
                    "dimension": "<rubric dimension>" | null, "summary": "...",
                    "route": "develop|design-gap"}],
      "notes": "free text (optional)"
    }

`null` is a dimension the unit's frames cannot show - never "not sure"; it is unmeasured, and
a strict tier does not pass on it. A dimension the rubric marks `first_unit: not_applicable`
is null for the first sampled unit and not counted. The critic does not write a verdict: the
step decides it (`decide`). Nothing missing is invented, and a malformed verdict goes back to
the critic with every error (judge.py).
"""

import hashlib
import json
import os
import re

from wgflib import paths
from wgflib.yamllite import load_file

__all__ = ["RUBRIC_PATH", "RISK_PATH", "RubricError", "load_rubric", "load_risk_rules",
           "dimensions", "applicable", "contract", "problems", "coerce", "decide",
           "SEVERITIES", "ROUTES"]

RUBRIC_PATH = os.path.join(paths.REFERENCE, "level-design-rubric.yaml")
RISK_PATH = os.path.join(paths.REFERENCE, "risk-reward.yaml")
SEVERITIES = ("blocker", "major", "minor")
ROUTES = ("develop", "design-gap")
_TOP = {"units", "findings", "notes"}
_UNIT = {"unit_id", "scores", "score_reasons", "comment"}
_FINDING = {"id", "severity", "unit", "frame", "dimension", "summary", "route"}
_ID = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_MAX_BYTES = 1024 * 1024


class RubricError(ValueError):
    """A rubric or risk file is unusable."""


def _digest(path):
    with open(path, "rb") as handle:
        return "sha256:" + hashlib.sha256(handle.read()).hexdigest()


def _ladder(value, name, path):
    if not isinstance(value, list) or not value or not all(
            isinstance(r, dict) and isinstance(r.get("score"), (int, float))
            and isinstance(r.get("at_least"), (int, float)) for r in value):
        raise RubricError(f"{path}: baseline.{name} must list {{score, at_least}} rungs")


def load_rubric(path=None):
    """The rubric as data, plus `path` and `sha256`. Raises RubricError when unusable."""
    path = path or RUBRIC_PATH
    try:
        data = load_file(path)
        digest = _digest(path)
    except (OSError, ValueError) as exc:
        raise RubricError(f"cannot read the level-design rubric {path}: {exc}")
    if not isinstance(data, dict):
        raise RubricError(f"{path}: not a mapping")
    dims = data.get("dimensions")
    if not isinstance(dims, dict) or not dims:
        raise RubricError(f"{path}: `dimensions` must be a non-empty map")
    for key in ("pass_bar", "mean_pass_bar"):
        bar = data.get(key)
        if not isinstance(bar, (int, float)) or isinstance(bar, bool) or not 0 <= bar <= 5:
            raise RubricError(f"{path}: `{key}` must be a number 0..5")
    for name, dim in dims.items():
        if not isinstance(dim, dict) or dim.get("route") not in ROUTES:
            raise RubricError(f"{path}: dimension {name} needs a route ({'|'.join(ROUTES)})")
        if sorted((dim.get("anchors") or {})) != ["0", "3", "5"]:
            raise RubricError(f"{path}: dimension {name} needs anchors 0, 3 and 5")
    for rule in data.get("blockers") or []:
        if not isinstance(rule, dict) or not rule.get("id") or rule.get("route") not in ROUTES \
                or not rule.get("rule"):
            raise RubricError(f"{path}: blocker {rule!r} needs id, route and rule")
    moments = [m.get("id") for m in data.get("moments") or [] if isinstance(m, dict)]
    if not moments or not all(isinstance(m, str) and m for m in moments):
        raise RubricError(f"{path}: `moments` must list the moments of a unit")
    sample = data.get("sample") or {}
    if not isinstance(sample.get("max_units"), int) or sample["max_units"] < 1:
        raise RubricError(f"{path}: sample.max_units must be a positive whole number")
    base = data.get("baseline") or {}
    grid = base.get("grid")
    if not (isinstance(grid, list) and len(grid) == 2 and all(isinstance(g, int) and g > 0
                                                              for g in grid)):
        raise RubricError(f"{path}: baseline.grid must be [columns, rows]")
    for name in ("play_space", "distinct_from_previous"):
        _ladder(base.get(name), name, path)
    data["path"] = path
    data["sha256"] = digest
    return data


def load_risk_rules(path=None):
    """core/reference/risk-reward.yaml as data, plus `path` and `sha256`."""
    path = path or RISK_PATH
    try:
        data = load_file(path)
        digest = _digest(path)
    except (OSError, ValueError) as exc:
        raise RubricError(f"cannot read the risk-reward rules {path}: {exc}")
    if not isinstance(data, dict):
        raise RubricError(f"{path}: not a mapping")
    bars = data.get("bars") or {}
    for key in ("min_relative_gain", "min_absolute_gain", "min_failure_rate_gain",
                "min_unit_share", "min_attempts"):
        if not isinstance(bars.get(key), (int, float)) or isinstance(bars.get(key), bool):
            raise RubricError(f"{path}: bars.{key} must be a number")
    policies = (data.get("play") or {}).get("policies") or []
    if sorted(policies) != ["greedy", "safe"]:
        raise RubricError(f"{path}: play.policies must be [safe, greedy]")
    data["path"] = path
    data["sha256"] = digest
    return data


def dimensions(rubric):
    return list(rubric["dimensions"])


def applicable(rubric, dimension, position):
    """False for a dimension that does not apply to the unit at `position` (0-based) of the
    sample: `first_unit: not_applicable` on the first."""
    return not (position == 0 and (rubric["dimensions"].get(dimension) or {}).get(
        "first_unit") == "not_applicable")


def contract(rubric, units):
    """The verdict shape, as the brief shows it."""
    first = units[0]["unit_id"] if units else "unit-1"
    return {
        "units": [{"unit_id": u["unit_id"],
                   "scores": {d: ("null (no previous unit)" if not applicable(rubric, d, i)
                                  else "0..5 | null") for d in dimensions(rubric)},
                   "score_reasons": {d: "what you saw, in which frame" for d in
                                     dimensions(rubric)},
                   "comment": "this unit in a sentence or two"}
                  for i, u in enumerate(units[:1])]
                 + (["... one entry per unit listed above, in that order"]
                    if len(units) > 1 else []),
        "findings": [{"id": "empty-field", "severity": "blocker", "unit": first,
                      "frame": f"{first}/start", "dimension": "play_space",
                      "summary": "what is wrong, where", "route": "develop"}],
        "notes": "anything else worth saying (optional)",
    }


def load_verdict(source):
    if not os.path.isfile(source):
        return None, f"no verdict file was written at {source}"
    try:
        if os.path.getsize(source) > _MAX_BYTES:
            return None, "verdict file is larger than 1 MiB"
        with open(source, encoding="utf-8") as handle:
            return json.load(handle), None
    except (OSError, UnicodeDecodeError) as exc:
        return None, f"verdict file cannot be read: {exc}"
    except ValueError as exc:
        return None, f"verdict file is not JSON: {exc}"


def coerce(data, rubric, units):
    """(data, coercions): only shapes that cannot change meaning - an integer-valued float
    score, a not-applicable dimension the critic scored anyway set to null, whitespace."""
    out = []
    if not isinstance(data, dict):
        return data, out
    data = json.loads(json.dumps(data))
    order = [u["unit_id"] for u in units]
    for entry in data.get("units") or []:
        if not isinstance(entry, dict):
            continue
        uid = entry.get("unit_id")
        if isinstance(uid, str) and uid != uid.strip() and uid.strip() in order:
            out.append({"path": "units[].unit_id", "rule": "strip-whitespace", "from": uid,
                        "to": uid.strip()})
            entry["unit_id"] = uid = uid.strip()
        scores = entry.get("scores")
        if not isinstance(scores, dict):
            continue
        position = order.index(uid) if uid in order else None
        for name, value in list(scores.items()):
            if isinstance(value, float) and value.is_integer():
                scores[name] = int(value)
            if position is not None and name in rubric["dimensions"] and \
                    not applicable(rubric, name, position) and scores[name] is not None:
                out.append({"path": f"units[{uid}].scores.{name}", "rule": "not-applicable",
                            "from": scores[name], "to": None})
                scores[name] = None
    for finding in data.get("findings") or []:
        if isinstance(finding, dict) and isinstance(finding.get("route"), str):
            route = finding["route"].strip().lower()
            if route != finding["route"] and route in ROUTES:
                out.append({"path": "findings[].route", "rule": "normalize-enum",
                            "from": finding["route"], "to": route})
                finding["route"] = route
    return data, out


def problems(data, rubric, units, moments):
    """Every way `data` is not the verdict the contract asks for (empty when it is)."""
    if not isinstance(data, dict):
        return ["verdict must be a JSON object"]
    errors = []
    extra = sorted(set(data) - _TOP)
    if extra:
        errors.append(f"unknown top-level keys: {', '.join(extra)}")
    order = [u["unit_id"] for u in units]
    dims = dimensions(rubric)
    entries = data.get("units")
    if not isinstance(entries, list):
        errors.append("`units` must be a list with one entry per sampled unit")
        entries = []
    seen = []
    for index, entry in enumerate(entries):
        where = f"units[{index}]"
        if not isinstance(entry, dict):
            errors.append(f"{where} must be an object")
            continue
        unknown = sorted(set(entry) - _UNIT)
        if unknown:
            errors.append(f"{where}: unknown keys {', '.join(unknown)}")
        uid = entry.get("unit_id")
        if uid not in order:
            errors.append(f"{where}: unit_id {uid!r} is not a sampled unit ({', '.join(order)})")
            continue
        if uid in seen:
            errors.append(f"{where}: unit {uid} is listed twice")
        seen.append(uid)
        scores = entry.get("scores")
        if not isinstance(scores, dict):
            errors.append(f"{where}: `scores` must map every dimension to 0..5 or null")
            continue
        missing = [d for d in dims if d not in scores]
        if missing:
            errors.append(f"{where}: scores lacks {', '.join(missing)}")
        unknown = sorted(set(scores) - set(dims))
        if unknown:
            errors.append(f"{where}: scores has unknown dimensions {', '.join(unknown)}")
        for name in dims:
            value = scores.get(name)
            if value is None:
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)) \
                    or not 0 <= value <= 5:
                errors.append(f"{where}: scores.{name} must be 0..5 or null, not {value!r}")
        reasons = entry.get("score_reasons")
        if reasons is not None and not (isinstance(reasons, dict) and all(
                isinstance(v, str) for v in reasons.values())):
            errors.append(f"{where}: score_reasons must map dimensions to text")
        if entry.get("comment") is not None and not isinstance(entry.get("comment"), str):
            errors.append(f"{where}: comment must be text")
    absent = [u for u in order if u not in seen]
    if absent:
        errors.append(f"`units` lacks {', '.join(absent)}")
    findings = data.get("findings")
    if not isinstance(findings, list):
        errors.append("`findings` must be a list (empty when there are none)")
        findings = []
    frame_keys = {f"{u['unit_id']}/{m}" for u in units for m in moments}
    for index, finding in enumerate(findings):
        where = f"findings[{index}]"
        if not isinstance(finding, dict):
            errors.append(f"{where} must be an object")
            continue
        unknown = sorted(set(finding) - _FINDING)
        if unknown:
            errors.append(f"{where}: unknown keys {', '.join(unknown)}")
        if not isinstance(finding.get("id"), str) or not _ID.match(finding["id"]):
            errors.append(f"{where}: id must be kebab-case")
        if finding.get("severity") not in SEVERITIES:
            errors.append(f"{where}: severity must be one of {', '.join(SEVERITIES)}")
        if finding.get("route") not in ROUTES:
            errors.append(f"{where}: route must be one of {', '.join(ROUTES)}")
        if not isinstance(finding.get("summary"), str) or not finding["summary"].strip():
            errors.append(f"{where}: summary must be text")
        if finding.get("unit") is not None and finding["unit"] not in order:
            errors.append(f"{where}: unit {finding['unit']!r} is not a sampled unit")
        if finding.get("frame") is not None and finding["frame"] not in frame_keys:
            errors.append(f"{where}: frame {finding['frame']!r} is not a listed frame")
        if finding.get("dimension") is not None and finding["dimension"] not in dims:
            errors.append(f"{where}: dimension {finding['dimension']!r} is not a rubric "
                          f"dimension")
    if data.get("notes") is not None and not isinstance(data["notes"], str):
        errors.append("notes must be text")
    return errors


def decide(verdict, rubric, units):
    """What the critic's verdict says against the rubric:

        {failing: [(unit, dimension, score)], blockers: [finding], unmeasured:
         [(unit, dimension)], mean: float | None, lowest: {dimension: score | None},
         routes: [route]}

    A score below `pass_bar` fails its unit; a blocker fails the build; the mean of every
    measured score must reach `mean_pass_bar`. A null on an applicable dimension is
    unmeasured. The step turns this into checks (step.py)."""
    bar = rubric["pass_bar"]
    order = [u["unit_id"] for u in units]
    by_unit = {e["unit_id"]: e for e in verdict.get("units") or []}
    failing, unmeasured, values = [], [], []
    lowest = {d: None for d in dimensions(rubric)}
    for position, uid in enumerate(order):
        scores = (by_unit.get(uid) or {}).get("scores") or {}
        for name in dimensions(rubric):
            if not applicable(rubric, name, position):
                continue
            value = scores.get(name)
            if value is None:
                unmeasured.append((uid, name))
                continue
            values.append(value)
            lowest[name] = value if lowest[name] is None else min(lowest[name], value)
            if value < bar:
                failing.append((uid, name, value))
    blockers = [f for f in verdict.get("findings") or [] if f.get("severity") == "blocker"]
    mean = round(sum(values) / len(values), 3) if values else None
    routes = []
    for uid, name, _value in failing:
        routes.append(rubric["dimensions"][name]["route"])
    for finding in blockers:
        routes.append(finding["route"])
    if mean is not None and mean < rubric["mean_pass_bar"]:
        routes.append("develop")
    ordered = [r for r in ROUTES[::-1] if r in routes]   # design-gap first
    return {"failing": failing, "blockers": blockers, "unmeasured": unmeasured,
            "mean": mean, "lowest": lowest, "routes": ordered}

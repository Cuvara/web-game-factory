"""The rubric, the verdict a judge writes, the strict check it has to pass, and the decision.

The judge writes:

    {
      "scores":   {"<every rubric dimension>": 0..5, ...},
      "findings": [{"id": "short-kebab-id", "severity": "blocker|major|minor",
                    "category": "assets|ui|composition|readability|consistency|debug",
                    "frame": "<viewport>/<frame-id>" | null, "summary": "...",
                    "route": "assets|develop"}],
      "notes":    "free text (optional)"
    }

The judge does not write a verdict: the step decides it (`decide`) from the rubric - FAIL
when any finding is a blocker or any dimension is below the pass bar. A judge cannot pass a
build its own findings fail, and a malformed verdict is never read charitably.
"""

import hashlib
import json
import os
import re

from wgflib import paths
from wgflib.yamllite import load_file

__all__ = ["RUBRIC_PATH", "load_rubric", "parse", "decide", "contract", "RubricError",
           "SEVERITIES", "CATEGORIES", "ROUTES"]

RUBRIC_PATH = os.path.join(paths.REFERENCE, "visual-qa-rubric.yaml")
SEVERITIES = ("blocker", "major", "minor")
CATEGORIES = ("assets", "ui", "composition", "readability", "consistency", "debug")
ROUTES = ("assets", "develop")
_TOP = {"scores", "findings", "notes"}
_FINDING = {"id", "severity", "category", "frame", "summary", "route"}
_ID = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_MAX_BYTES = 1024 * 1024


class RubricError(ValueError):
    """The rubric file is unusable."""


def load_rubric(path=None):
    """The rubric as data, plus `path` and `sha256` of the file it came from."""
    path = path or RUBRIC_PATH
    try:
        data = load_file(path)
        with open(path, "rb") as handle:
            digest = "sha256:" + hashlib.sha256(handle.read()).hexdigest()
    except (OSError, ValueError) as exc:
        raise RubricError(f"cannot read the visual-qa rubric {path}: {exc}")
    dimensions = data.get("dimensions") if isinstance(data, dict) else None
    if not isinstance(dimensions, dict) or not dimensions:
        raise RubricError(f"{path}: `dimensions` must be a non-empty map")
    bar = data.get("pass_bar")
    if not isinstance(bar, (int, float)) or isinstance(bar, bool) or not 0 <= bar <= 5:
        raise RubricError(f"{path}: `pass_bar` must be a number 0..5")
    for name, dimension in dimensions.items():
        if not isinstance(dimension, dict) or dimension.get("route") not in ROUTES:
            raise RubricError(f"{path}: dimension {name} needs a route ({'|'.join(ROUTES)})")
        anchors = dimension.get("anchors") or {}
        if sorted(anchors) != ["0", "3", "5"]:
            raise RubricError(f"{path}: dimension {name} needs anchors 0, 3 and 5")
    for rule in data.get("blockers") or []:
        if (not isinstance(rule, dict) or rule.get("category") not in CATEGORIES
                or rule.get("route") not in ROUTES or not rule.get("rule")):
            raise RubricError(f"{path}: blocker rule {rule!r} needs category, route and rule")
    data["path"] = path
    data["sha256"] = digest
    return data


def contract(rubric, frame_ids):
    """The verdict shape, as the brief shows it."""
    example_frame = sorted(frame_ids)[0] if frame_ids else None
    return {
        "scores": {name: "0..5" for name in rubric["dimensions"]},
        "findings": [
            {"id": "primitive-keeper", "severity": "blocker", "category": "assets",
             "frame": example_frame, "summary": "what is wrong, on which entity or element",
             "route": "assets"},
            {"id": "another-id", "severity": "minor", "category": "composition",
             "frame": None, "summary": "a finding about every frame", "route": "develop"},
        ],
        "notes": "anything else worth saying (optional)",
    }


def parse(source, rubric, frame_ids):
    """(verdict dict, None) or (None, problem). `source` is a path or already-loaded data.
    Never raises."""
    if isinstance(source, str):
        if not os.path.isfile(source):
            return None, f"no verdict file was written at {source}"
        try:
            if os.path.getsize(source) > _MAX_BYTES:
                return None, "verdict file is larger than 1 MiB"
            with open(source, encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, UnicodeDecodeError) as exc:
            return None, f"verdict file cannot be read: {exc}"
        except ValueError as exc:
            return None, f"verdict file is not JSON: {exc}"
    else:
        data = source
    if not isinstance(data, dict):
        return None, "verdict must be a JSON object"
    extra = sorted(set(data) - _TOP)
    if extra:
        return None, f"verdict has keys the contract does not: {', '.join(extra)}"
    for key in ("scores", "findings"):
        if key not in data:
            return None, f"verdict is missing {key!r}"
    if "notes" in data and data["notes"] is not None and not isinstance(data["notes"], str):
        return None, "notes must be a string"
    scores = data["scores"]
    if not isinstance(scores, dict):
        return None, "scores must be an object of dimension -> 0..5"
    dimensions = list(rubric["dimensions"])
    unknown = sorted(set(scores) - set(dimensions))
    if unknown:
        return None, f"scores has dimensions the rubric does not: {', '.join(unknown)}"
    missing = [d for d in dimensions if d not in scores]
    if missing:
        return None, f"scores is missing {', '.join(missing)}"
    for name, value in scores.items():
        if (not isinstance(value, (int, float)) or isinstance(value, bool)
                or not 0 <= value <= 5):
            return None, f"scores.{name} must be a number 0..5, not {value!r}"
    findings = data["findings"]
    if not isinstance(findings, list):
        return None, "findings must be a list"
    ids = set()
    known = set(frame_ids)
    for index, finding in enumerate(findings):
        where = f"findings[{index}]"
        if not isinstance(finding, dict):
            return None, f"{where} must be an object"
        extra = sorted(set(finding) - _FINDING)
        if extra:
            return None, f"{where} has keys the contract does not: {', '.join(extra)}"
        absent = [k for k in sorted(_FINDING) if k not in finding]
        if absent:
            return None, f"{where} is missing {', '.join(absent)}"
        if not isinstance(finding["id"], str) or not _ID.match(finding["id"]):
            return None, f"{where}.id must be a short kebab-case id"
        if finding["id"] in ids:
            return None, f"{where}.id {finding['id']!r} is not unique"
        ids.add(finding["id"])
        if finding["severity"] not in SEVERITIES:
            return None, f"{where}.severity must be one of {', '.join(SEVERITIES)}"
        if finding["category"] not in CATEGORIES:
            return None, f"{where}.category must be one of {', '.join(CATEGORIES)}"
        if finding["route"] not in ROUTES:
            return None, f"{where}.route must be one of {', '.join(ROUTES)}"
        if finding["frame"] is not None and finding["frame"] not in known:
            return None, (f"{where}.frame {finding['frame']!r} is not a frame you were given "
                          f"(<viewport>/<frame-id>, or null)")
        if not isinstance(finding["summary"], str) or not finding["summary"].strip():
            return None, f"{where}.summary must be a non-empty string"
    return data, None


def decide(verdict, rubric):
    """("PASS" | "FAIL", failed ids, routes). A blocker finding, or a dimension scored below
    its pass bar, fails; each failure contributes its route. Routes are ordered assets
    before develop: the step's route is the first."""
    bar = rubric["pass_bar"]
    failed, routes = [], set()
    for finding in verdict["findings"]:
        if finding["severity"] == "blocker":
            failed.append(f"finding:{finding['id']}")
            routes.add(finding["route"])
    for name, dimension in rubric["dimensions"].items():
        if verdict["scores"][name] < dimension.get("pass_bar", bar):
            failed.append(f"score:{name}")
            routes.add(dimension["route"])
    ordered = [r for r in ROUTES if r in routes]
    return ("FAIL" if failed else "PASS"), failed, ordered

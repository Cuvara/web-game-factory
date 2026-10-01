"""The rubric, the verdict a judge writes, the strict check it has to pass, and the decision.

The judge writes:

    {
      "scores":   {"<every rubric dimension>": 0..5, ...},
      "findings": [{"id": "short-kebab-id", "severity": "blocker|major|minor",
                    "category": "assets|ui|composition|readability|consistency|debug",
                    "frame": "<viewport>/<frame-id>" | null, "summary": "...",
                    "route": "assets|develop"}],
      "states":   [{"state": "<rubric state>", "viewport": "<viewport>",
                    "answers": {"<every question for that state>": true | false | null},
                    "comment": "..."}],      # one per (state, viewport) that has frames
      "look":     "finished-game" | "developer-prototype",
      "look_reason": "...",
      "notes":    "free text (optional)"
    }

The judge does not write a verdict: the step decides it (`decide`) from the rubric - FAIL
when any finding is a blocker, any dimension is below the pass bar, any per-state answer
equals its question's `fail_when`, or the look is a developer prototype. A judge cannot pass
a build its own answers fail, and a malformed verdict is never read charitably.
"""

import hashlib
import json
import os
import re

from wgflib import paths
from wgflib.yamllite import load_file

__all__ = ["RUBRIC_PATH", "load_rubric", "parse", "decide", "contract", "RubricError",
           "state_ids", "questions_for", "judged_pairs",
           "SEVERITIES", "CATEGORIES", "ROUTES"]

RUBRIC_PATH = os.path.join(paths.REFERENCE, "visual-qa-rubric.yaml")
SEVERITIES = ("blocker", "major", "minor")
CATEGORIES = ("assets", "ui", "composition", "readability", "consistency", "debug")
ROUTES = ("assets", "develop")
_TOP = {"scores", "findings", "states", "look", "look_reason", "notes"}
_STATE = {"state", "viewport", "answers", "comment"}
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
    states = [s.get("id") for s in data.get("states") or [] if isinstance(s, dict)]
    if not states:
        raise RubricError(f"{path}: `states` must list the states frames are grouped into")
    for question in data.get("state_questions") or []:
        if (not isinstance(question, dict) or not question.get("id")
                or question.get("fail_when") not in (True, False)
                or question.get("route") not in ROUTES
                or not set(question.get("states") or states) <= set(states)):
            raise RubricError(f"{path}: state question {question!r} needs id, fail_when, "
                              f"route and known states")
    look = data.get("look") or {}
    if (look.get("fail_on") not in (look.get("values") or [])
            or look.get("route") not in ROUTES):
        raise RubricError(f"{path}: `look` needs values, fail_on among them and a route")
    data["path"] = path
    data["sha256"] = digest
    return data


def state_ids(rubric):
    return [s["id"] for s in rubric.get("states") or []]


def questions_for(rubric, state):
    """The state questions asked of `state`, in rubric order."""
    return [q for q in rubric.get("state_questions") or []
            if state in (q.get("states") or state_ids(rubric))]


def judged_pairs(rubric, frames):
    """[(state, viewport)] that have frames, in rubric state order then viewport order."""
    viewports = []
    for frame in frames:
        if frame["project"] not in viewports:
            viewports.append(frame["project"])
    present = {(f["state"], f["project"]) for f in frames}
    return [(state, viewport) for state in state_ids(rubric) for viewport in viewports
            if (state, viewport) in present]


def contract(rubric, frames):
    """The verdict shape, as the brief shows it."""
    frame_ids = [f["key"] for f in frames]
    example_frame = sorted(frame_ids)[0] if frame_ids else None
    pairs = judged_pairs(rubric, frames)
    example_states = [{"state": state, "viewport": viewport,
                       "answers": {q["id"]: "true | false | null"
                                   for q in questions_for(rubric, state)},
                       "comment": "what these frames show, in a sentence or two"}
                      for state, viewport in pairs[:1]]
    look = rubric.get("look") or {}
    return {
        "scores": {name: "0..5" for name in rubric["dimensions"]},
        "findings": [
            {"id": "primitive-keeper", "severity": "blocker", "category": "assets",
             "frame": example_frame, "summary": "what is wrong, on which entity or element",
             "route": "assets"},
            {"id": "another-id", "severity": "minor", "category": "composition",
             "frame": None, "summary": "a finding about every frame", "route": "develop"},
        ],
        "states": example_states + (["... one entry per (state, viewport) listed above"]
                                    if len(pairs) > 1 else []),
        "look": " | ".join(look.get("values") or []),
        "look_reason": "why, in a sentence",
        "notes": "anything else worth saying (optional)",
    }


def parse(source, rubric, frames):
    """(verdict dict, None) or (None, problem). `source` is a path or already-loaded data;
    `frames` the staged frames ({key, state, project}). Never raises."""
    frame_ids = [f["key"] for f in frames]
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
    for key in ("scores", "findings", "states", "look"):
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
    problem = _check_states(data["states"], rubric, frames)
    if problem:
        return None, problem
    look = rubric.get("look") or {}
    if data["look"] not in (look.get("values") or []):
        return None, f"look must be one of {', '.join(look.get('values') or [])}"
    if "look_reason" in data and not isinstance(data["look_reason"], str):
        return None, "look_reason must be a string"
    return data, None


def _check_states(states, rubric, frames):
    if not isinstance(states, list):
        return "states must be a list"
    wanted = judged_pairs(rubric, frames)
    seen = set()
    for index, entry in enumerate(states):
        where = f"states[{index}]"
        if not isinstance(entry, dict):
            return f"{where} must be an object"
        extra = sorted(set(entry) - _STATE)
        if extra:
            return f"{where} has keys the contract does not: {', '.join(extra)}"
        pair = (entry.get("state"), entry.get("viewport"))
        if pair not in wanted:
            return (f"{where} is for {pair[1]!r} {pair[0]!r}, which no frame shows; answer "
                    f"exactly these: {', '.join(f'{v}/{s}' for s, v in wanted)}")
        if pair in seen:
            return f"{where} repeats {pair[1]}/{pair[0]}"
        seen.add(pair)
        answers = entry.get("answers")
        if not isinstance(answers, dict):
            return f"{where}.answers must be an object"
        asked = [q["id"] for q in questions_for(rubric, pair[0])]
        if sorted(answers) != sorted(asked):
            return (f"{where}.answers must answer exactly {', '.join(asked)} for state "
                    f"{pair[0]}")
        for qid, value in answers.items():
            if value not in (True, False, None):
                return f"{where}.answers.{qid} must be true, false or null, not {value!r}"
        if "comment" in entry and not isinstance(entry["comment"], str):
            return f"{where}.comment must be a string"
    missing = [f"{v}/{s}" for s, v in wanted if (s, v) not in seen]
    if missing:
        return f"states is missing {', '.join(missing)}"
    return None


def decide(verdict, rubric, primitive_style=False):
    """("PASS" | "FAIL", failed ids, routes). A blocker finding, a dimension scored below its
    pass bar, a per-state answer equal to its question's fail_when (unless the question
    yields to the design's primitive_style), or a developer-prototype look fails; each
    failure contributes its route. Routes are ordered assets before develop: the step's
    route is the first."""
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
    questions = {q["id"]: q for q in rubric.get("state_questions") or []}
    for entry in verdict.get("states") or []:
        for qid, value in entry["answers"].items():
            question = questions[qid]
            if value is None or value != question["fail_when"]:
                continue
            if question.get("unless") == "primitive_style" and primitive_style:
                continue
            failed.append(f"state:{entry['viewport']}/{entry['state']}:{qid}")
            routes.add(question["route"])
    look = rubric.get("look") or {}
    if verdict.get("look") == look.get("fail_on"):
        failed.append(f"look:{verdict['look']}")
        routes.add(look["route"])
    ordered = [r for r in ROUTES if r in routes]
    return ("FAIL" if failed else "PASS"), failed, ordered

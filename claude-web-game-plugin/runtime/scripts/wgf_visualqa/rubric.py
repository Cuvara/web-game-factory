"""The rubric, the verdict a judge writes, the strict check it has to pass, and the decision.

The judge writes:

    {
      "scores":   {"<every rubric dimension>": 0..5, ...},
      "score_reasons": {"<dimension>": "why that score: what, in which frames"},  # optional
      "findings": [{"id": "short-kebab-id", "severity": "blocker|major|minor",
                    "category": "assets|ui|composition|readability|consistency|debug",
                    "frame": "<viewport>/<frame-id>" | null, "summary": "...",
                    "route": "assets|develop"}],
      "states":   [{"state": "<rubric state>", "viewport": "<viewport>",
                    "answers": {"<every question for that state>": true | false | null},
                    "comment": "..."}],      # one per (state, viewport) that has frames
      "look":     "finished-game" | "unremarkable" | "developer-prototype",
      "look_reason": "...",
      "notes":    "free text (optional)"
    }

The judge does not write a verdict: the step decides it (`decide`) from the rubric - FAIL
when any finding is a blocker, any dimension is below the pass bar, any per-state answer
equals its question's `fail_when`, or the look is a developer prototype. A judge cannot pass
a build its own answers fail, and a malformed verdict is never read charitably: `coerce`
fixes only shapes that cannot change meaning (and says which), `problems` lists every
remaining error for the judge's repair round (judge.py), and nothing missing is invented.

`score_reasons` is optional - a verdict without it is well formed - but the brief asks for
it for every dimension: it is what a failing score sends back to the asset authors and the
developer (wgf_assets.feedback, wgf_develop.brief) besides a number.
"""

import hashlib
import json
import os
import re

from wgflib import paths
from wgflib.yamllite import load_file

__all__ = ["RUBRIC_PATH", "load_rubric", "load_verdict", "parse", "problems",
           "coerce", "decide", "contract", "RubricError",
           "state_ids", "questions_for", "judged_pairs", "expand_roles",
           "SEVERITIES", "CATEGORIES", "ROUTES"]

RUBRIC_PATH = os.path.join(paths.REFERENCE, "visual-qa-rubric.yaml")
SEVERITIES = ("blocker", "major", "minor")
CATEGORIES = ("assets", "ui", "composition", "readability", "consistency", "debug")
ROUTES = ("assets", "develop")
_TOP = {"scores", "score_reasons", "findings", "states", "look", "look_reason", "notes"}
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
    fail_on = look.get("fail_on")
    fail_on = fail_on if isinstance(fail_on, list) else [fail_on]
    if (not fail_on or not set(fail_on) <= set(look.get("values") or [])
            or look.get("route") not in ROUTES):
        raise RubricError(f"{path}: `look` needs values, fail_on among them and a route")
    look["fail_on"] = fail_on
    mean_bar = data.get("mean_pass_bar")
    if mean_bar is not None and not (isinstance(mean_bar, (int, float))
                                     and 0 <= mean_bar <= 5):
        raise RubricError(f"{path}: mean_pass_bar must be a number 0..5")
    problem = _check_rebuild(data)
    if problem:
        raise RubricError(f"{path}: {problem}")
    data["path"] = path
    data["sha256"] = digest
    return data


def _names(value):
    return isinstance(value, list) and all(isinstance(v, str) and v for v in value)


def _check_rebuild(data):
    """The re-entry data (`rebuild`, and `rebuild_roles` on dimensions, blockers, state
    questions and the look) is well formed, or the problem."""
    rebuild = data.get("rebuild")
    if rebuild is None:
        return None
    if not isinstance(rebuild, dict):
        return "`rebuild` must be a map"
    for key in ("groups", "role_words"):
        entries = rebuild.get(key) or {}
        if not isinstance(entries, dict) or not all(_names(v) for v in entries.values()):
            return f"`rebuild.{key}` must map names to lists of names"
    if "fallback" in rebuild and not _names(rebuild["fallback"]):
        return "`rebuild.fallback` must be a list of roles or groups"
    owners = [("dimension " + n, d) for n, d in data["dimensions"].items()]
    owners += [("blocker " + str(b.get("id")), b) for b in data.get("blockers") or []]
    owners += [("state question " + q["id"], q) for q in data.get("state_questions") or []]
    owners.append(("look", data.get("look") or {}))
    for name, owner in owners:
        if "rebuild_roles" in owner and not _names(owner["rebuild_roles"]):
            return f"{name}: `rebuild_roles` must be a list of roles or groups"
    return None


def expand_roles(rubric, names):
    """The design asset roles `names` stand for: a name in `rebuild.groups` is its roles
    (groups may name groups), anything else is a role."""
    groups = ((rubric or {}).get("rebuild") or {}).get("groups") or {}
    out, seen = [], set()

    def add(name):
        if name in seen:
            return
        seen.add(name)
        if name in groups:
            for member in groups[name]:
                add(member)
        elif name not in out:
            out.append(name)

    for name in names or ():
        add(name)
    return out


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
        "score_reasons": {name: "why this score: what you saw, in which frames"
                          for name in rubric["dimensions"]},
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


def load_verdict(source):
    """(data, None) or (None, problem): the verdict file read as JSON, nothing checked."""
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


def parse(source, rubric, frames):
    """(verdict dict, None) or (None, problem). `source` is a path or already-loaded data;
    `frames` the staged frames ({key, state, project}). `problem` names every error found,
    joined by "; " (`problems` has them as a list). Never raises."""
    if isinstance(source, str):
        data, problem = load_verdict(source)
        if problem:
            return None, problem
    else:
        data = source
    found = problems(data, rubric, frames)
    if found:
        return None, "; ".join(found)
    return data, None


def problems(data, rubric, frames):
    """Every way `data` is not the verdict the contract asks for, as a list (empty when it
    is). Each part of the verdict is checked independently, so a judge asked to repair its
    verdict sees all of its errors at once, not the first only."""
    if not isinstance(data, dict):
        return ["verdict must be a JSON object"]
    out = []
    extra = sorted(set(data) - _TOP)
    if extra:
        out.append(f"verdict has keys the contract does not: {', '.join(extra)}")
    for key in ("scores", "findings", "states", "look"):
        if key not in data:
            out.append(f"verdict is missing {key!r}")
    if "notes" in data and data["notes"] is not None and not isinstance(data["notes"], str):
        out.append("notes must be a string")
    dimensions = list(rubric["dimensions"])
    if "scores" in data:
        out += _check_scores(data["scores"], dimensions)
    reasons = data.get("score_reasons")
    if reasons is not None:
        if not isinstance(reasons, dict):
            out.append("score_reasons must be an object of dimension -> a sentence")
        else:
            unknown = sorted(set(reasons) - set(dimensions))
            if unknown:
                out.append(f"score_reasons has dimensions the rubric does not: "
                           f"{', '.join(unknown)}")
            for name, value in reasons.items():
                if not isinstance(value, str):
                    out.append(f"score_reasons.{name} must be a string")
    if "findings" in data:
        out += _check_findings(data["findings"], [f["key"] for f in frames])
    if "states" in data:
        out += _check_states(data["states"], rubric, frames)
    look = rubric.get("look") or {}
    if "look" in data and data["look"] not in (look.get("values") or []):
        out.append(f"look must be one of {', '.join(look.get('values') or [])}")
    if "look_reason" in data and not isinstance(data["look_reason"], str):
        out.append("look_reason must be a string")
    return out


def _check_scores(scores, dimensions):
    if not isinstance(scores, dict):
        return ["scores must be an object of dimension -> 0..5"]
    out = []
    unknown = sorted(set(scores) - set(dimensions))
    if unknown:
        out.append(f"scores has dimensions the rubric does not: {', '.join(unknown)}")
    missing = [d for d in dimensions if d not in scores]
    if missing:
        out.append(f"scores is missing {', '.join(missing)}")
    for name, value in scores.items():
        if (not isinstance(value, (int, float)) or isinstance(value, bool)
                or not 0 <= value <= 5):
            out.append(f"scores.{name} must be a number 0..5, not {value!r}")
    return out


def _check_findings(findings, frame_ids):
    if not isinstance(findings, list):
        return ["findings must be a list"]
    out = []
    ids = set()
    for index, finding in enumerate(findings):
        problem = _check_finding(f"findings[{index}]", finding, ids, set(frame_ids))
        if problem:
            out.append(problem)
    return out


def _check_finding(where, finding, ids, known):
    if not isinstance(finding, dict):
        return f"{where} must be an object"
    extra = sorted(set(finding) - _FINDING)
    if extra:
        return f"{where} has keys the contract does not: {', '.join(extra)}"
    absent = [k for k in sorted(_FINDING) if k not in finding]
    if absent:
        return f"{where} is missing {', '.join(absent)}"
    if not isinstance(finding["id"], str) or not _ID.match(finding["id"]):
        return f"{where}.id must be a short kebab-case id"
    if finding["id"] in ids:
        return f"{where}.id {finding['id']!r} is not unique"
    ids.add(finding["id"])
    if finding["severity"] not in SEVERITIES:
        return f"{where}.severity must be one of {', '.join(SEVERITIES)}"
    if finding["category"] not in CATEGORIES:
        return f"{where}.category must be one of {', '.join(CATEGORIES)}"
    if finding["route"] not in ROUTES:
        return f"{where}.route must be one of {', '.join(ROUTES)}"
    if finding["frame"] is not None and finding["frame"] not in known:
        return (f"{where}.frame {finding['frame']!r} is not a frame you were given "
                f"(<viewport>/<frame-id>, or null)")
    if not isinstance(finding["summary"], str) or not finding["summary"].strip():
        return f"{where}.summary must be a non-empty string"
    return None


def _check_states(states, rubric, frames):
    if not isinstance(states, list):
        return ["states must be a list"]
    wanted = judged_pairs(rubric, frames)
    seen = set()
    out = []
    for index, entry in enumerate(states):
        problem = _check_state(f"states[{index}]", entry, rubric, wanted, seen)
        if problem:
            out.append(problem)
    missing = [f"{v}/{s}" for s, v in wanted if (s, v) not in seen]
    if missing:
        out.append(f"states is missing {', '.join(missing)}")
    return out


def _check_state(where, entry, rubric, wanted, seen):
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
        absent = [q for q in asked if q not in answers]
        unasked = sorted(set(answers) - set(asked))
        return (f"{where}.answers must answer exactly {', '.join(asked)} for state "
                f"{pair[0]}" + (f" (missing {', '.join(absent)})" if absent else "")
                + (f" (not asked: {', '.join(unasked)})" if unasked else ""))
    for qid, value in answers.items():
        if value not in (True, False, None):
            return f"{where}.answers.{qid} must be true, false or null, not {value!r}"
    if "comment" in entry and not isinstance(entry["comment"], str):
        return f"{where}.comment must be a string"
    return None


# -- coercion -------------------------------------------------------------------------------
#
# Only shapes that cannot change what the judge said are coerced, each recorded: surrounding
# whitespace on an id or enum value, the case of an enum value or of a key the rubric names,
# and a one-item list of a string where a string is asked for. A missing key, a missing
# answer, a score written as a string, a boolean written as "yes" - anything that would need
# the Factory to guess - is never coerced; it goes back to the judge as an error.

def _fold(value):
    return value.strip().lower() if isinstance(value, str) else value


def _enum(value, allowed, path, out):
    """`value` as one of `allowed` when it differs only by surrounding whitespace or case."""
    if not isinstance(value, str) or value in allowed:
        return value
    matches = [a for a in allowed if a.lower() == _fold(value)]
    if len(matches) != 1:
        return value
    rule = "strip-whitespace" if value.strip() == matches[0] else "enum-case"
    out.append({"path": path, "rule": rule, "from": value, "to": matches[0]})
    return matches[0]


def _keys(mapping, allowed, path, out):
    """`mapping` with keys renamed to one of `allowed` when they differ only by whitespace
    or case and the renamed key is not also present."""
    if not isinstance(mapping, dict):
        return mapping
    renamed = {}
    for key, value in mapping.items():
        target = key
        if key not in allowed:
            matches = [a for a in allowed if a.lower() == _fold(key)]
            if len(matches) == 1 and matches[0] not in mapping and matches[0] not in renamed:
                target = matches[0]
                out.append({"path": f"{path}.{key}" if path else key, "rule": "key-case",
                            "from": key, "to": target})
        renamed[target] = value
    return renamed


def coerce(data, rubric, frames):
    """(data, coercions): a copy of a loaded verdict with only trivially fixable shapes
    coerced, and one {path, rule, from, to} per coercion. `data` that is not an object is
    returned as it is. parse() still judges the result strictly."""
    out = []
    if not isinstance(data, dict):
        return data, out
    data = _keys(json.loads(json.dumps(data)), _TOP, "", out)
    dimensions = list(rubric["dimensions"])
    if "scores" in data:
        data["scores"] = _keys(data["scores"], dimensions, "scores", out)
    reasons = data.get("score_reasons")
    if isinstance(reasons, dict):
        reasons = _keys(reasons, dimensions, "score_reasons", out)
        for name, value in list(reasons.items()):
            if isinstance(value, list) and len(value) == 1 and isinstance(value[0], str):
                reasons[name] = value[0]
                out.append({"path": f"score_reasons.{name}", "rule": "unwrap-one-item-list",
                            "from": value, "to": value[0]})
        data["score_reasons"] = reasons
    look = rubric.get("look") or {}
    if "look" in data:
        data["look"] = _enum(data["look"], list(look.get("values") or []), "look", out)
    frame_ids = [f["key"] for f in frames]
    if isinstance(data.get("findings"), list):
        for index, finding in enumerate(data["findings"]):
            if not isinstance(finding, dict):
                continue
            where = f"findings[{index}]"
            for key, allowed in (("severity", SEVERITIES), ("category", CATEGORIES),
                                 ("route", ROUTES)):
                if key in finding:
                    finding[key] = _enum(finding[key], list(allowed), f"{where}.{key}", out)
            if isinstance(finding.get("frame"), str) and finding["frame"] not in frame_ids:
                stripped = finding["frame"].strip()
                if stripped in frame_ids:
                    out.append({"path": f"{where}.frame", "rule": "strip-whitespace",
                                "from": finding["frame"], "to": stripped})
                    finding["frame"] = stripped
            if isinstance(finding.get("id"), str) and finding["id"] != finding["id"].strip():
                out.append({"path": f"{where}.id", "rule": "strip-whitespace",
                            "from": finding["id"], "to": finding["id"].strip()})
                finding["id"] = finding["id"].strip()
    if isinstance(data.get("states"), list):
        viewports = sorted({f["project"] for f in frames})
        for index, entry in enumerate(data["states"]):
            if not isinstance(entry, dict):
                continue
            where = f"states[{index}]"
            if "state" in entry:
                entry["state"] = _enum(entry["state"], state_ids(rubric), f"{where}.state", out)
            if "viewport" in entry:
                entry["viewport"] = _enum(entry["viewport"], viewports, f"{where}.viewport",
                                          out)
            if isinstance(entry.get("answers"), dict) and entry.get("state") in state_ids(
                    rubric):
                asked = [q["id"] for q in questions_for(rubric, entry["state"])]
                entry["answers"] = _keys(entry["answers"], asked, f"{where}.answers", out)
    return data, out


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
    mean_bar = rubric.get("mean_pass_bar")
    scores = [verdict["scores"][name] for name in rubric["dimensions"]]
    if mean_bar is not None and scores and sum(scores) / len(scores) < mean_bar:
        failed.append(f"mean:{sum(scores) / len(scores):.2f}")
        for name, dimension in rubric["dimensions"].items():
            if verdict["scores"][name] < 4:
                routes.add(dimension["route"])
    look = rubric.get("look") or {}
    fail_on = look.get("fail_on")
    if verdict.get("look") in (fail_on if isinstance(fail_on, list) else [fail_on]):
        failed.append(f"look:{verdict['look']}")
        routes.add(look["route"])
    ordered = [r for r in ROUTES if r in routes]
    return ("FAIL" if failed else "PASS"), failed, ordered

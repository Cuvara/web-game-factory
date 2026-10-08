"""The Factory's regression registry: every declared check's tier, and the lessons they hold.

    load(root=None)                       {"tiers", "lessons", "evidence"} as parsed data
    classify(tiers, root=None)            ({"<source>:<id>": entry}, problems): every check
                                          the reference files and producer tables declare,
                                          with its tier (core/reference/check-tiers.yaml)
    lesson_problems(lessons, checks, root=None, evidence=None)
                                          what is wrong with core/reference/lessons.yaml:
                                          an enforced lesson whose check or test does not
                                          exist, a gap that says nothing, a game named
    guards(lessons, tiers, producer, check)
                                          [{"lesson", "check", "tests", "status"}] - the
                                          lessons whose check a finding of `producer`'s
                                          `check` is (a quality finding's `guarded_by`)
    independent_review_problems(workflow, policy)
                                          the paths a workflow lets an implementer's change
                                          take to G4 or release without every judge
                                          (core/reference/quality-policy.yaml rule 6)
    problems(root=None)                   every problem above, for check-integrity

Pure reads of data files under the Factory root: no process, no network, no clock. Nothing
here names a game, a step or a family; the sources and their rules are the data's.
"""

import os
import re

from wgflib.yamllite import load as load_yaml

__all__ = ["TIERS_FILE", "LESSONS_FILE", "EVIDENCE_FILE", "TIERS", "load", "classify",
           "lesson_problems", "guards", "problems", "floor_criteria",
           "independent_review_problems", "successors"]

TIERS_FILE = "core/reference/check-tiers.yaml"
LESSONS_FILE = "core/reference/lessons.yaml"
# Instance evidence: which game showed a lesson. Optional - an installed runtime has none.
EVIDENCE_FILE = "workspace/lessons/evidence.yaml"
TIERS = ("hard", "quality", "advisory")
CHECKED_STATUSES = ("enforced", "partial")
GAP_STATUSES = ("partial", "gap")
TEST_REF = re.compile(r"^(scripts/tests/[A-Za-z0-9_]+\.py)::([A-Za-z_][A-Za-z0-9_]*)$")


def _root(root):
    if root:
        return root
    from wgflib import paths
    return paths.ROOT


def _read(root, relative):
    with open(os.path.join(root, *relative.split("/")), encoding="utf-8") as handle:
        return load_yaml(handle.read())


def load(root=None):
    """{"tiers", "lessons", "evidence"}; evidence None when the instance file is absent."""
    root = _root(root)
    out = {"tiers": _read(root, TIERS_FILE), "lessons": _read(root, LESSONS_FILE),
           "evidence": None}
    if os.path.isfile(os.path.join(root, *EVIDENCE_FILE.split("/"))):
        out["evidence"] = _read(root, EVIDENCE_FILE)
    return out


def floor_criteria(floor):
    """Every criterion of the quality floor: the universal ones, each genre family's and each
    rendering dimension's."""
    found = list((floor or {}).get("universal") or [])
    for entry in ((floor or {}).get("genres") or {}).values():
        found += list((entry or {}).get("criteria") or [])
    for entry in ((floor or {}).get("dimensions_contracts") or {}).values():
        found += list((entry or {}).get("criteria") or [])
    return [c for c in found if isinstance(c, dict)]


def _is_reference(value):
    if isinstance(value, dict):
        return any(_is_reference(v) for v in value.values())
    return isinstance(value, str) and ":" in value


def _floor_tier(criterion):
    """The `floor-criterion` rule: a release blocker is quality when it reads a calibrated bar
    (a reference, or a rubric score), else hard; a release warning, or no release severity,
    is advisory."""
    severity = (criterion.get("severity") or {}).get("release")
    if severity != "blocker":
        return "advisory"
    evaluate = criterion.get("evaluate") or {}
    if evaluate.get("kind") == "scores" or _is_reference(criterion.get("minimum")) \
            or _is_reference(criterion.get("maximum")):
        return "quality"
    return "hard"


RULES = {"floor-criterion": _floor_tier}


def _find(data, dotted):
    node = data
    for part in str(dotted).split("."):
        node = node.get(part) if isinstance(node, dict) else None
    return node


def _enumerate(data, how):
    """[(id, entry)] of a source file, by its `enumerate` declaration."""
    if how == "floor-criteria":
        return [(c.get("id"), c) for c in floor_criteria(data)]
    if isinstance(how, dict) and how.get("keys"):
        block = _find(data, how["keys"])
        return [(k, v if isinstance(v, dict) else {}) for k, v in (block or {}).items()] \
            if isinstance(block, dict) else []
    if isinstance(how, dict) and how.get("list"):
        block = _find(data, how["list"])
        key = how.get("id") or "id"
        return [(e.get(key), e) for e in block or [] if isinstance(e, dict)] \
            if isinstance(block, list) else []
    return None


def _literal_in(root, folder, check_id):
    """True when `check_id` appears as a quoted string literal in a .py file under `folder`."""
    wanted = (f'"{check_id}"', f"'{check_id}'")
    base = os.path.join(root, *folder.split("/"))
    for current, _dirs, files in os.walk(base):
        for name in files:
            if not name.endswith(".py"):
                continue
            try:
                with open(os.path.join(current, name), encoding="utf-8") as handle:
                    text = handle.read()
            except OSError:
                continue
            if any(w in text for w in wanted):
                return True
    return False


def classify(tiers, root=None):
    """({"<source>:<id>": {"source", "id", "tier", "producer"}}, problems)."""
    root = _root(root)
    out, problems = {}, []
    if not isinstance(tiers, dict):
        return out, [f"{TIERS_FILE}: not a mapping"]
    vocabulary = tiers.get("tiers") or {}
    if set(vocabulary) != set(TIERS):
        problems.append(f"{TIERS_FILE}: tiers must be exactly {', '.join(TIERS)}, "
                        f"not {', '.join(sorted(vocabulary))}")
    cache = {}
    for name, source in (tiers.get("sources") or {}).items():
        where = f"{TIERS_FILE} sources.{name}"
        if not isinstance(source, dict):
            problems.append(f"{where}: not a mapping")
            continue
        rule = source.get("tier")
        table = source.get("checks")
        entries = None
        if source.get("file"):
            if source["file"] not in cache:
                try:
                    cache[source["file"]] = _read(root, source["file"])
                except (OSError, ValueError) as exc:
                    problems.append(f"{where}: {source['file']} cannot be read ({exc})")
                    cache[source["file"]] = None
            data = cache[source["file"]]
            if data is None:
                continue
            entries = _enumerate(data, source.get("enumerate"))
            if entries is None:
                problems.append(f"{where}: enumerate {source.get('enumerate')!r} is not "
                                "floor-criteria, {keys: path} or {list: path}")
                continue
        elif not source.get("defined_in"):
            problems.append(f"{where}: needs a `file` to read or the code it is "
                            "`defined_in`")
            continue
        if table is not None:
            if not isinstance(table, dict):
                problems.append(f"{where}: checks must map a check id to a tier")
                continue
            if entries is not None:
                declared = {i for i, _ in entries if i}
                for missing in sorted(declared - set(table)):
                    problems.append(f"{where}: {source['file']} declares {missing!r}, which "
                                    "has no tier here")
                for extra in sorted(set(table) - declared):
                    problems.append(f"{where}: {extra!r} is classified but "
                                    f"{source['file']} does not declare it")
            for check_id, tier in table.items():
                if source.get("defined_in") and not _literal_in(
                        root, source["defined_in"], check_id):
                    problems.append(f"{where}: {check_id!r} appears nowhere in "
                                    f"{source['defined_in']} - not a check it reports")
                out[f"{name}:{check_id}"] = {"source": name, "id": check_id, "tier": tier,
                                            "producer": source.get("producer")}
            continue
        if entries is None:
            problems.append(f"{where}: an explicit source needs `checks`")
            continue
        if not isinstance(rule, dict):
            problems.append(f"{where}: needs `tier` ({{all}}, {{by, map}} or {{rule}}) or "
                            "`checks`")
            continue
        for check_id, entry in entries:
            if not check_id:
                problems.append(f"{where}: an entry has no id")
                continue
            if "all" in rule:
                tier = rule["all"]
            elif "rule" in rule:
                function = RULES.get(rule["rule"])
                if function is None:
                    problems.append(f"{where}: no tier rule {rule['rule']!r}")
                    break
                tier = function(entry)
            else:
                value = _find(entry, rule.get("by"))
                tier = (rule.get("map") or {}).get(value)
                if tier is None:
                    problems.append(f"{where}: {check_id!r} has {rule.get('by')} "
                                    f"{value!r}, which the tier map does not cover")
                    continue
            out[f"{name}:{check_id}"] = {"source": name, "id": check_id, "tier": tier,
                                        "producer": source.get("producer")}
    for check_id, tier in (tiers.get("overrides") or {}).items():
        if check_id not in out:
            problems.append(f"{TIERS_FILE} overrides: {check_id!r} is not a declared check")
            continue
        out[check_id] = dict(out[check_id], tier=tier, overridden=True)
    for check_id, entry in out.items():
        if entry["tier"] not in TIERS:
            problems.append(f"{TIERS_FILE}: {check_id} has tier {entry['tier']!r}, not one of "
                            f"{', '.join(TIERS)}")
    problems += _floor_closure(tiers, out, cache, root)
    return out, problems


def _floor_closure(tiers, checks, cache, root):
    """Every check a quality-floor criterion reads from a producer the registry enumerates is
    classified, and one a release blocker reads is never advisory."""
    problems = []
    floor_file = next((s.get("file") for s in (tiers.get("sources") or {}).values()
                       if isinstance(s, dict) and s.get("enumerate") == "floor-criteria"), None)
    if not floor_file:
        return problems
    floor = cache.get(floor_file)
    if floor is None:
        try:
            floor = _read(root, floor_file)
        except (OSError, ValueError):
            return problems
    by_producer = {}
    for name, source in (tiers.get("sources") or {}).items():
        if isinstance(source, dict) and source.get("producer") and \
                isinstance(source.get("checks"), dict):
            by_producer.setdefault(source["producer"], []).append(name)
    for criterion in floor_criteria(floor):
        evaluate = criterion.get("evaluate") or {}
        if evaluate.get("kind") != "checks":
            continue
        sources = by_producer.get(evaluate.get("report"))
        if not sources:
            continue
        blocker = (criterion.get("severity") or {}).get("release") == "blocker"
        for check_id in evaluate.get("checks") or ():
            if any(ch in str(check_id) for ch in "*?["):
                continue
            found = [checks.get(f"{s}:{check_id}") for s in sources]
            found = [f for f in found if f]
            if not found:
                problems.append(f"{TIERS_FILE}: quality-floor {criterion.get('id')} reads "
                                f"{evaluate.get('report')} {check_id!r}, which no source of "
                                "that producer classifies")
            elif blocker and all(f["tier"] == "advisory" for f in found):
                problems.append(f"{TIERS_FILE}: {found[0]['source']}:{check_id} is advisory, "
                                f"but the release blocker {criterion.get('id')} reads it")
    return problems


def _test_exists(root, ref):
    match = TEST_REF.match(str(ref))
    if not match:
        return f"{ref!r} is not scripts/tests/<file>.py::<test name>"
    path = os.path.join(root, *match.group(1).split("/"))
    if not os.path.isfile(path):
        return f"{match.group(1)} does not exist"
    with open(path, encoding="utf-8") as handle:
        if not re.search(r"^\s*def " + re.escape(match.group(2)) + r"\(", handle.read(),
                         re.MULTILINE):
            return f"{match.group(1)} has no test {match.group(2)}"
    return None


def _game_names(evidence):
    names = [str(n) for n in (evidence or {}).get("games") or [] if n]
    return [n for n in names if len(n) >= 4]


def lesson_problems(lessons, checks, root=None, evidence=None):
    """[problem] for core/reference/lessons.yaml against the classified `checks`."""
    root = _root(root)
    problems = []
    if not isinstance(lessons, dict):
        return [f"{LESSONS_FILE}: not a mapping"]
    statuses = list(lessons.get("statuses") or [])
    seen = set()
    names = _game_names(evidence)
    for index, lesson in enumerate(lessons.get("lessons") or []):
        if not isinstance(lesson, dict) or not lesson.get("id"):
            problems.append(f"{LESSONS_FILE} lessons[{index}]: needs an id")
            continue
        at = f"{LESSONS_FILE} {lesson['id']}"
        if lesson["id"] in seen:
            problems.append(f"{at}: the id is used twice")
        seen.add(lesson["id"])
        status = lesson.get("status")
        if status not in statuses:
            problems.append(f"{at}: status {status!r} is not one of {', '.join(statuses)}")
            continue
        for key in ("title", "lesson"):
            if not str(lesson.get(key) or "").strip():
                problems.append(f"{at}: needs a {key}")
        if status in CHECKED_STATUSES:
            named = list(lesson.get("checks") or [])
            if not named:
                problems.append(f"{at}: an {status} lesson names the check that holds it")
            for check_id in named:
                if check_id not in checks:
                    problems.append(f"{at}: check {check_id!r} is not classified in "
                                    f"{TIERS_FILE}")
            tests = list(lesson.get("tests") or [])
            if not tests:
                problems.append(f"{at}: an {status} lesson names the test that proves its "
                                "check catches it")
            for ref in tests:
                why = _test_exists(root, ref)
                if why:
                    problems.append(f"{at}: test {why}")
        if status in GAP_STATUSES and not str(lesson.get("gap") or "").strip():
            problems.append(f"{at}: a {status} lesson says what is not held yet (`gap`)")
        if status == "gap" and lesson.get("checks"):
            problems.append(f"{at}: a gap lesson names no check - if one holds it, it is "
                            "enforced or partial")
        if status == "process" and not str(lesson.get("held_by") or "").strip():
            problems.append(f"{at}: a process lesson says where it is written down "
                            "(`held_by`)")
        text = " ".join(str(lesson.get(k) or "") for k in
                        ("title", "lesson", "gap", "held_by")).lower()
        for name in names:
            if name.lower() in text:
                problems.append(f"{at}: names the game {name!r} - core names no specific "
                                "game; the instance evidence holds which game showed it")
    if evidence is not None:
        for lesson_id in ((evidence or {}).get("lessons") or {}):
            if lesson_id not in seen:
                problems.append(f"{EVIDENCE_FILE}: evidence for {lesson_id!r}, which "
                                f"{LESSONS_FILE} does not define")
    return problems


def guards(lessons, tiers, producer, check):
    """The lessons whose check is `producer`'s `check` (exact id, or the check a split or
    per-viewport finding id carries before `/` or `@`): [{"lesson", "check", "status",
    "tests"}]."""
    if not producer or not check:
        return []
    base = str(check).split("@", 1)[0].split("/", 1)[0]
    names = {n for n, s in ((tiers or {}).get("sources") or {}).items()
             if isinstance(s, dict) and s.get("producer") == producer}
    wanted = {f"{n}:{base}" for n in names}
    out = []
    for lesson in (lessons or {}).get("lessons") or []:
        if not isinstance(lesson, dict) or lesson.get("status") not in CHECKED_STATUSES:
            continue
        for check_id in lesson.get("checks") or ():
            if check_id in wanted:
                out.append({"lesson": lesson["id"], "check": check_id,
                            "status": lesson["status"],
                            "tests": list(lesson.get("tests") or [])})
                break
    return out


def successors(steps):
    """{step id: [step ids]} - where each step's results can go: its `next` (else the next
    step listed, for an unrouted success) and every `on:` target. $end and $fail end."""
    out = {}
    ids = [s.get("id") for s in steps]
    for index, step in enumerate(steps):
        targets = []
        nxt = step.get("next")
        if nxt is None and index + 1 < len(steps):
            nxt = ids[index + 1]
        if nxt:
            targets.append(nxt)
        targets += [t for t in (step.get("on") or {}).values() if isinstance(t, str)]
        out[step.get("id")] = [t for t in targets if t in ids]
    return out


def independent_review_problems(workflow, policy):
    """[problem]: for every step of an implementer type and every judge type it must meet,
    a step at a guarded stage reachable from it with every step of that judge type removed.
    `workflow`: the parsed workflow file's `workflow` mapping; `policy`: quality-policy."""
    rule = (policy or {}).get("independent_review")
    if not isinstance(rule, dict):
        return ["quality-policy.yaml: no independent_review rule"]
    steps = [s for s in (workflow or {}).get("steps") or [] if isinstance(s, dict)]
    graph = successors(steps)
    by_id = {s.get("id"): s for s in steps}
    guarded = {s.get("id") for s in steps if s.get("stage") in (rule.get("before") or ())}
    problems = []
    if not guarded:
        return problems
    for kind, judges in (rule.get("implementers") or {}).items():
        for start in [s.get("id") for s in steps if s.get("type") == kind]:
            for judge in judges or ():
                if not any(s.get("type") == judge for s in steps):
                    problems.append(f"workflow {workflow.get('id')}: no step of judge type "
                                    f"{judge!r}, which every {kind} change must meet")
                    continue
                seen, todo = set(), [start]
                while todo:
                    current = todo.pop()
                    for target in graph.get(current, ()):
                        if target in seen or by_id[target].get("type") == judge:
                            continue
                        seen.add(target)
                        todo.append(target)
                reached = sorted(seen & guarded)
                if reached:
                    problems.append(
                        f"workflow {workflow.get('id')}: a change {start} ({kind}) makes can "
                        f"reach {', '.join(reached)} without a {judge} step judging it - the "
                        "implementer would be its only judge (quality-policy rule 6)")
    return problems


def problems(root=None):
    """Every problem of the registry: unclassified checks, broken lessons."""
    root = _root(root)
    try:
        data = load(root)
    except (OSError, ValueError) as exc:
        return [f"the regression registry cannot be read ({exc})"]
    checks, found = classify(data["tiers"], root)
    found += lesson_problems(data["lessons"], checks, root, data["evidence"])
    try:
        policy = _read(root, "core/reference/quality-policy.yaml")
        workflow = (_read(root, "core/workflows/new-game.workflow.yaml") or {}).get("workflow")
    except (OSError, ValueError) as exc:
        return found + [f"independent review cannot be checked ({exc})"]
    return found + independent_review_problems(workflow, policy)

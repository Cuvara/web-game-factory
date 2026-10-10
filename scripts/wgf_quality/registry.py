"""The Factory's regression registry: every declared check's tier, and the lessons they hold.

    load(root=None)                       {"tiers", "lessons", "evidence"} as parsed data
    classify(tiers, root=None)            ({"<source>:<id>": entry}, problems): every check
                                          the reference files and producer tables declare,
                                          with its tier (core/reference/check-tiers.yaml)
    lesson_problems(lessons, checks, root=None, evidence=None, runtime=False)
                                          what is wrong with core/reference/lessons.yaml:
                                          an enforced lesson whose check or test does not
                                          exist, a gap that says nothing, a game named, and
                                          the knowledge model's own rules (category, scope,
                                          derived level, lifecycle, exceptions:
                                          wgf_knowledge.model). `runtime` skips test
                                          existence: an installed runtime ships no tests
    status_at(tiers, source)              where a source's check results are read in its
                                          producer's report (check-tiers `status_at`)
    check_results(locator, report)        [{"check", "status", "raw", "value"}] read from a
                                          report through a locator
    check_status(tiers, check_id, report, facts=None)
                                          [result] for one `<source>:<id>` check, UNMEASURED
                                          when the report holds no entry for it - unless a
                                          `not_reported` group of its locator holds on the
                                          report and `facts` ({"render", "reports"})
    status_at_problems(tiers, root=None)  a locator whose path the producer's schema does
                                          not have
    guards(lessons, tiers, producer, check)
                                          [{"lesson", "check", "tests", "status"}] - the
                                          lessons whose check a finding of `producer`'s
                                          `check` is (a quality finding's `guarded_by`)
    independent_review_problems(workflow, policy)
                                          the paths a workflow lets an implementer's change
                                          take to G4 or release without every judge
                                          (core/reference/quality-policy.yaml rule 6)
    problems(root=None, runtime=False)    every problem above, for check-integrity

Pure reads of data files under the Factory root: no process, no network, no clock. Nothing
here names a game, a step or a family; the sources and their rules are the data's.
"""

import os
import re

from wgflib.yamllite import load as load_yaml

__all__ = ["TIERS_FILE", "LESSONS_FILE", "EVIDENCE_FILE", "TIERS", "load", "classify",
           "lesson_problems", "guards", "problems", "floor_criteria",
           "independent_review_problems", "successors", "status_at", "check_results",
           "check_status", "status_at_problems", "RESULT_STATUSES"]

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


def classify(tiers, root=None, reader=None):
    """({"<source>:<id>": {"source", "id", "tier", "producer"}}, problems). `reader`
    (relative path -> parsed data) reads the source files - a run's pinned copies - instead
    of the files under `root`; code a source is `defined_in` is always read under `root`."""
    root = _root(root)
    reader = reader or (lambda relative: _read(root, relative))
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
                    cache[source["file"]] = reader(source["file"])
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
            # The id the producer reports a file's entry under (`prefix` + the entry's id).
            prefix = str(source.get("prefix") or "")
            entries = [(f"{prefix}{i}" if i else i, e) for i, e in entries]
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
    problems += _floor_closure(tiers, out, cache, reader)
    return out, problems


def _floor_closure(tiers, checks, cache, reader):
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
            floor = reader(floor_file)
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


def lesson_problems(lessons, checks, root=None, evidence=None, runtime=False):
    """[problem] for core/reference/lessons.yaml against the classified `checks`. `runtime`:
    the tests are not shipped, so their existence is not checked (CI holds it)."""
    from wgf_knowledge import model

    root = _root(root)
    problems = []
    if not isinstance(lessons, dict):
        return [f"{LESSONS_FILE}: not a mapping"]
    problems += model.file_problems(lessons)
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
            tests = model.all_tests(lesson)
            if not tests:
                problems.append(f"{at}: an {status} lesson names the test that proves its "
                                "check catches it")
            for ref in tests if not runtime else ():
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
                        ("title", "lesson", "gap", "held_by", "problem", "root_cause",
                         "principle", "anti_pattern", "reason")).lower()
        for name in names:
            if name.lower() in text:
                problems.append(f"{at}: names the game {name!r} - core names no specific "
                                "game; the instance evidence holds which game showed it")
    if evidence is not None:
        for lesson_id in ((evidence or {}).get("lessons") or {}):
            if lesson_id not in seen:
                problems.append(f"{EVIDENCE_FILE}: evidence for {lesson_id!r}, which "
                                f"{LESSONS_FILE} does not define")
    try:
        vocabulary = model.vocabulary(root)
    except model.KnowledgeError as exc:
        return problems + [str(exc)]
    return problems + model.lesson_problems(lessons, checks, vocabulary, evidence)


def guards(lessons, tiers, producer, check):
    """The lessons whose check is `producer`'s `check` (exact id, or the check a split or
    per-viewport finding id carries before `/`, `@` or a viewport's `:`): [{"lesson",
    "check", "status", "tests"}]."""
    if not producer or not check:
        return []
    base = str(check).split("@", 1)[0].split("/", 1)[0]
    bases = {base, base.split(":", 1)[0]}
    # A source's `findings_via`: the report triage reads its failures through (verify's
    # checks reach triage as the qa-report's blocking defects).
    names = {n for n, s in ((tiers or {}).get("sources") or {}).items()
             if isinstance(s, dict) and (s.get("producer") == producer
                                         or producer in (s.get("findings_via") or ()))}
    wanted = {f"{n}:{b}" for n in names for b in bases}
    out = []
    for lesson in (lessons or {}).get("lessons") or []:
        if not isinstance(lesson, dict) or lesson.get("status") not in CHECKED_STATUSES:
            continue
        for check_id in lesson.get("checks") or ():
            if check_id in wanted:
                out.append({"lesson": lesson["id"], "check": check_id,
                            "status": lesson["status"],
                            "tests": _all_tests(lesson)})
                break
    return out


def _all_tests(lesson):
    from wgf_knowledge import model
    return model.all_tests(lesson)


# ------------------------------------------------------- where a check's result is read

# What a locator reads a result as. MEASURED: a value held to a bar the source file states
# (a rubric score); the bar is judged by whoever holds the rule, not here.
# NOT_APPLICABLE: a producer that reports a check only for a build it concerns (a source's
# `absent: {status: NOT_APPLICABLE}`) reported none - the check does not concern this build.
RESULT_STATUSES = ("PASS", "FAIL", "WARNING", "BLOCKED", "SKIPPED", "UNMEASURED", "DEFERRED",
                   "MEASURED", "NOT_APPLICABLE")
LOCATOR_KEYS = ("list", "keys", "id", "id_pattern", "id_split", "where", "status", "map",
                "presence", "absent", "attribute", "not_applicable", "covered",
                "not_reported")
# What a `not_reported` group may require (check-tiers.yaml 1.2.0).
NOT_REPORTED_KEYS = ("checks", "why", "verdict", "ran", "render", "none_of", "one_of",
                     "missing", "other")


def status_at(tiers, source):
    """The locator of `source` (a source name of check-tiers.yaml): its own `status_at`, else
    the file's top-level one. None when neither exists."""
    entry = ((tiers or {}).get("sources") or {}).get(source)
    if not isinstance(entry, dict):
        return None
    own = entry.get("status_at")
    if isinstance(own, dict):
        return own
    default = (tiers or {}).get("status_at")
    return default if isinstance(default, dict) else None


def _walk(node, path):
    """Every value at `path` (dotted; `name[]` flattens a list) under `node`."""
    found = [node]
    for part in str(path).split("."):
        flatten = part.endswith("[]")
        key = part[:-2] if flatten else part
        nxt = []
        for value in found:
            value = value.get(key) if isinstance(value, dict) else None
            if flatten:
                nxt += list(value) if isinstance(value, list) else []
            elif value is not None:
                nxt.append(value)
        found = nxt
    return found


def _normal(raw, mapping):
    key = str(raw).lower() if isinstance(raw, bool) else str(raw)
    for candidate, target in (mapping or {}).items():
        if str(candidate) == key:
            return str(target)
    upper = key.upper()
    return upper if upper in RESULT_STATUSES else "UNMEASURED"


def check_results(locator, report):
    """[{"check", "status", "raw", "value"}] every result `locator` finds in `report`."""
    out = []
    if not isinstance(locator, dict) or not isinstance(report, dict):
        return out
    if locator.get("keys"):
        for block in _walk(report, locator["keys"]):
            for check_id, value in (block.items() if isinstance(block, dict) else ()):
                out.append({"check": str(check_id), "status": "MEASURED", "raw": value,
                            "value": value})
        return out
    pattern = re.compile(locator["id_pattern"]) if locator.get("id_pattern") else None
    for entries in _walk(report, locator.get("list") or "checks"):
        for entry in entries if isinstance(entries, list) else ():
            if not isinstance(entry, dict):
                continue
            if any(entry.get(k) != v for k, v in (locator.get("where") or {}).items()):
                continue
            check_id = entry.get(locator.get("id") or "id")
            if check_id is None:
                continue
            check_id = str(check_id)
            if pattern:
                match = pattern.match(check_id)
                if not match:
                    continue
                check_id = match.group("id")
            if locator.get("id_split"):
                check_id = check_id.split(locator["id_split"], 1)[0]
            if locator.get("presence"):
                status, raw = str(locator["presence"]), None
            else:
                raw = entry.get(locator.get("status") or "status")
                status = _normal(raw, locator.get("map"))
            result = {"check": check_id, "status": status, "raw": raw, "value": None}
            if _not_applicable(locator.get("not_applicable"), entry):
                result["status"] = "NOT_APPLICABLE"
            elif status == "WARNING" and _covered(locator.get("covered"), entry):
                # The producer held the check advisory because another check measured what
                # it stands for, and that check is read on its own: covered, so passed here.
                result["status"], result["covered"] = "PASS", True
            out.append(result)
    return out


def _covered(rule, entry):
    """True when a locator's `covered` {field, values} says this WARNING entry is a proxy its
    producer made advisory because another check measured it: the mapping (or list) at
    `field` is non-empty and every value in it is one of `values`."""
    if not isinstance(rule, dict) or not rule.get("field"):
        return False
    found = _walk(entry, rule["field"])
    if not found:
        return False
    value = found[0]
    values = list(value.values()) if isinstance(value, dict) else (
        list(value) if isinstance(value, list) else [value])
    allowed = {str(v) for v in rule.get("values") or ()}
    return bool(values) and all(str(v) in allowed for v in values)


def _group_holds(group, report, facts):
    """True when every condition of a `not_reported` group holds: the report's verdict, an
    entry showing the family ran, the run's render, a value absent from another report, a
    field missing from another report, another report's check at a status."""
    facts = facts or {}
    reports = facts.get("reports") or {}
    if group.get("verdict") and str((report or {}).get("verdict")) not in {
            str(v) for v in group["verdict"]}:
        return False
    if group.get("ran"):
        prefix = str(group["ran"])
        ids = [str(e.get("id")) for e in (report or {}).get("checks") or ()
               if isinstance(e, dict)] + [str(e.get("id")) for e in (report or {}).get(
                   "criteria") or () if isinstance(e, dict)]
        if not any(i.startswith(prefix) for i in ids):
            return False
    if group.get("render"):
        if facts.get("render") not in group["render"]:
            return False
    for key in ("none_of", "one_of", "missing", "other"):
        rule = group.get(key)
        if not rule:
            continue
        other = reports.get(rule.get("report"))
        if not isinstance(other, dict):
            return False
        if key == "none_of":
            found = {str(v) for v in _walk(other, rule.get("path") or "")}
            # Nothing at the path is no evidence that none of the values is declared.
            if not found or found & {str(v) for v in rule.get("values") or ()}:
                return False
        elif key == "one_of":
            found = [str(v) for v in _walk(other, rule.get("path") or "")]
            if not found or found[0] not in {str(v) for v in rule.get("values") or ()}:
                return False
        elif key == "missing":
            if _walk(other, rule.get("path") or ""):
                return False
        else:
            entries = [e for e in _walk(other, rule.get("list") or "checks")]
            entries = [e for block in entries for e in (block if isinstance(block, list)
                                                        else [block])]
            if not any(isinstance(e, dict) and str(e.get("id")) == str(rule.get("id"))
                       and str(e.get("status")) in {str(v) for v in rule.get("status") or ()}
                       for e in entries):
                return False
    return True


def _text_of(value):
    return isinstance(value, str) and value.strip() != ""


def _not_applicable(rule, entry):
    """True when a locator's `not_applicable` {field, values} says this entry is the
    producer stating the check does not concern the build (its `field` - dotted - holds one
    of `values`)."""
    if not isinstance(rule, dict) or not rule.get("field"):
        return False
    found = _walk(entry, rule["field"])
    return bool(found) and str(found[0]) in {str(v) for v in rule.get("values") or ()}


def check_status(tiers, check_id, report, facts=None):
    """[result] for the check `<source>:<id>` in its producer's `report`: every entry for it,
    or one result read through the locator's `absent` rule - UNMEASURED when it has none,
    never a pass. A check the producer reports only for a build it concerns reads
    NOT_APPLICABLE when its report has no entry for it AND one of the locator's
    `not_reported` groups naming it holds - the producer finished (its verdict), the family
    of checks ran, and what the run is (`facts`: {"render": the run's 2d|3d, "reports":
    {artifact type: report}}) says the check does not concern it. Otherwise UNMEASURED."""
    source, _, wanted = str(check_id).partition(":")
    locator = status_at(tiers, source)
    if locator is None:
        return [{"check": wanted, "status": "UNMEASURED", "raw": None, "value": None}]
    found = check_results(locator, report)
    if locator.get("attribute") is False:
        # The producer's entries carry no check id (a judge's free-form finding ids): any
        # selected entry is every check of the source at the `presence` status - which of
        # them it is, nothing says.
        if found:
            return [{"check": wanted, "status": found[0]["status"], "raw": None,
                     "value": None, "unattributed": [r["check"] for r in found]}]
        found = []
    else:
        found = [r for r in found if r["check"] == wanted]
    if found:
        return found
    if isinstance(report, dict) and report:
        for group in locator.get("not_reported") or ():
            if isinstance(group, dict) and (group.get("checks") == "*" or wanted in (
                    group.get("checks") or ())) and _group_holds(group, report, facts):
                return [{"check": wanted, "status": "NOT_APPLICABLE", "raw": None,
                         "value": None, "why": group.get("why")}]
    absent = locator.get("absent") or {}
    raw = (report or {}).get(absent.get("field")) if absent.get("field") else None
    status = "UNMEASURED"
    if raw is not None:
        for candidate, target in (absent.get("map") or {}).items():
            if str(candidate) == str(raw):
                status = str(target)
    return [{"check": wanted, "status": status, "raw": raw, "value": None}]


def _schema_has(document, path):
    """True when the dotted `path` (`name[]` for a list's items) names a property the schema
    `document` declares, following local `#/` references and allOf/anyOf/oneOf; a reference
    to another file is taken on trust."""
    def deref(node):
        hops = 0
        while isinstance(node, dict) and str(node.get("$ref") or "").startswith("#/") \
                and hops < 20:
            target = document
            for part in node["$ref"][2:].split("/"):
                target = target.get(part) if isinstance(target, dict) else None
            node, hops = target, hops + 1
        return node

    def options(node):
        node = deref(node)
        if not isinstance(node, dict):
            return []
        if node.get("$ref"):
            return [None]                     # another file: trusted
        out = [node]
        for key in ("allOf", "anyOf", "oneOf"):
            for sub in node.get(key) or ():
                out += options(sub)
        return out

    nodes = [document]
    for part in str(path).split("."):
        flatten = part.endswith("[]")
        key = part[:-2] if flatten else part
        nxt = []
        for node in nodes:
            for option in options(node):
                if option is None:
                    return True
                prop = (option.get("properties") or {}).get(key)
                if prop is None:
                    continue
                if not flatten:
                    nxt.append(prop)
                    continue
                for item in options(prop):
                    if item is None:
                        return True
                    if item.get("items") is not None:
                        nxt.append(item["items"])
        if not nxt:
            return False
        nodes = nxt
    return True


def status_at_problems(tiers, root=None):
    """[problem]: a source with no locator, a locator with an unknown key, or one whose path
    the producer's schema (core/artifacts/<producer>.schema.json) does not declare."""
    import json

    root = _root(root)
    problems = []
    for name, source in ((tiers or {}).get("sources") or {}).items():
        if not isinstance(source, dict):
            continue
        where = f"{TIERS_FILE} sources.{name}"
        locator = status_at(tiers, name)
        if not isinstance(locator, dict):
            problems.append(f"{where}: no `status_at` - where its results are read is unknown")
            continue
        unknown = sorted(set(locator) - set(LOCATOR_KEYS))
        if unknown:
            problems.append(f"{where}: status_at has unknown key(s) {', '.join(unknown)}")
        path = locator.get("keys") or locator.get("list")
        if not path:
            problems.append(f"{where}: status_at names a `list` or `keys` path")
            continue
        if locator.get("id_pattern"):
            try:
                if "id" not in re.compile(locator["id_pattern"]).groupindex:
                    problems.append(f"{where}: status_at id_pattern has no group `id`")
            except re.error as exc:
                problems.append(f"{where}: status_at id_pattern does not compile ({exc})")
        schema_file = os.path.join(root, "core", "artifacts",
                                   f"{source.get('producer')}.schema.json")
        try:
            with open(schema_file, encoding="utf-8") as handle:
                schema = json.load(handle)
        except (OSError, ValueError):
            problems.append(f"{where}: producer {source.get('producer')!r} has no artifact "
                            "schema to read its results from")
            continue
        if not _schema_has(schema, path):
            problems.append(f"{where}: status_at {path!r} is not a property of "
                            f"{source.get('producer')}.schema.json")
        declared = source.get("checks")
        for index, group in enumerate(locator.get("not_reported") or ()):
            at = f"{where}: status_at not_reported[{index}]"
            if not isinstance(group, dict):
                problems.append(f"{at} is a mapping")
                continue
            unknown_keys = sorted(set(group) - set(NOT_REPORTED_KEYS))
            if unknown_keys:
                problems.append(f"{at} has unknown key(s) {', '.join(unknown_keys)}")
            listed = group.get("checks")
            if listed != "*" and not isinstance(listed, list) or not listed or (
                    isinstance(listed, list) and
                    isinstance(declared, dict) and any(c not in declared for c in listed)):
                problems.append(f"{at}: checks lists checks of this source")
            if not (group.get("verdict") or group.get("ran")):
                problems.append(f"{at}: needs `verdict` or `ran` - evidence the producer ran "
                                "the check's family, or an absent entry is never "
                                "NOT_APPLICABLE")
            if not _text_of(group.get("why")):
                problems.append(f"{at}: says why the producer does not report it (`why`)")
            agree = (group.get("none_of") or {}).get("agrees_with") \
                if isinstance(group.get("none_of"), dict) else None
            if isinstance(agree, dict):
                try:
                    stated = _walk(_read(root, agree.get("file") or ""),
                                   agree.get("path") or "")
                except (OSError, ValueError) as exc:
                    stated = None
                    problems.append(f"{at}: none_of.agrees_with {agree.get('file')} cannot be "
                                    f"read ({exc})")
                if stated is not None:
                    want = sorted(str(v) for v in (stated[0] if stated and isinstance(
                        stated[0], list) else stated))
                    have = sorted(str(v) for v in group["none_of"].get("values") or ())
                    if want != have:
                        problems.append(f"{at}: none_of.values {have} disagree with "
                                        f"{agree.get('file')} {agree.get('path')} {want}")
        field = (locator.get("absent") or {}).get("field")
        if field and not _schema_has(schema, field):
            problems.append(f"{where}: status_at absent.field {field!r} is not a property of "
                            f"{source.get('producer')}.schema.json")
    return problems


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


def problems(root=None, runtime=False):
    """Every problem of the registry: unclassified checks, results that cannot be located,
    broken lessons. `runtime`: an installed runtime, whose tests are not shipped."""
    root = _root(root)
    try:
        data = load(root)
    except (OSError, ValueError) as exc:
        return [f"the regression registry cannot be read ({exc})"]
    checks, found = classify(data["tiers"], root)
    found += status_at_problems(data["tiers"], root)
    found += lesson_problems(data["lessons"], checks, root, data["evidence"], runtime=runtime)
    try:
        policy = _read(root, "core/reference/quality-policy.yaml")
        workflow = (_read(root, "core/workflows/new-game.workflow.yaml") or {}).get("workflow")
    except (OSError, ValueError) as exc:
        return found + [f"independent review cannot be checked ({exc})"]
    return found + independent_review_problems(workflow, policy)

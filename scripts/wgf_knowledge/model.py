"""The knowledge model: core/reference/lessons.yaml 2.0.0 as rules.

    tests_of(lesson)                  {"catches", "passes", "generalizes"}: a flat 1.x list
                                      reads as `catches`
    all_tests(lesson)                 every test id of the lesson, once, in order
    scope_of(lesson)                  {} for `global`, the mapping otherwise, None when absent
                                      or not a scope
    derive_level(lesson, checks)      the level its checks' tiers give (None: process, or
                                      nothing to derive it from)
    level_of(lesson, checks)          the level in force: a declared stronger one, else the
                                      derived one
    vocabulary(root=None)             the scope and category vocabularies, read from the
                                      reference files that define them
    lesson_problems(lessons, checks, vocabulary, evidence=None)
                                      what is wrong with the 2.0.0 fields of every lesson
    file_problems(lessons)            what is wrong with the file's own blocks (version,
                                      lifecycles, levels, exceptions)
    weakening_problems(previous, current, checks)
                                      a lesson deleted, or its level or scope weakened in
                                      place, against the previous version of the file
    exception_problems(exception, lessons, checks, now=None)
                                      why a person's exception cannot hold
    exception_active(exception, now)  True while it has not expired

`checks` is wgf_quality.registry.classify()'s first value: {"<source>:<id>": {"tier", ...}}.
Pure: no process, no network, no clock (a caller passes `now`). Nothing here names a game,
a step or a family.
"""

import datetime
import os
import re

__all__ = ["LEVELS", "LIFECYCLES", "SCOPE_KEYS", "RESERVED_SCOPE_KEYS", "TEST_KINDS",
           "SOURCE_KINDS", "APPROVER_MODES", "REASON_MIN_LENGTH", "PROCESS", "KnowledgeError",
           "tests_of", "all_tests", "scope_of", "derive_level", "level_of", "level_rank",
           "is_process", "vocabulary", "lesson_problems", "file_problems",
           "weakening_problems", "exception_problems", "exception_active", "parse_time",
           "scope_covers", "version_of"]

LESSONS_FILE = "core/reference/lessons.yaml"
EVIDENCE_FILE = "workspace/lessons/evidence.yaml"

LEVELS = ("blocking", "required", "recommended", "experimental")
_RANK = {"experimental": 0, "recommended": 1, "required": 2, "blocking": 3}
LIFECYCLES = ("candidate", "active", "validated", "deprecated")
SCOPE_KEYS = ("families", "render", "platforms", "tiers")
# The complexity profile and archetype registry (not built yet): refused until it exists.
RESERVED_SCOPE_KEYS = ("profiles", "archetypes")
TEST_KINDS = ("catches", "passes", "generalizes")
SOURCE_KINDS = ("run", "review", "benchmark", "research-principle")
APPROVER_MODES = ("human", "automation")
# core/artifacts/shared/knowledge-exception.schema.json `reason.minLength`.
REASON_MIN_LENGTH = 20
PROCESS = "process"
RENDERS = ("2d", "3d")
CHECKED = ("enforced", "partial")

_SEMVER = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
_DATE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
_ID = re.compile(r"^[A-Z][A-Za-z0-9-]*$")


class KnowledgeError(ValueError):
    """The knowledge files cannot be read as a knowledge model."""


# ------------------------------------------------------------------------------ a lesson


def tests_of(lesson):
    tests = (lesson or {}).get("tests")
    out = {kind: [] for kind in TEST_KINDS}
    if isinstance(tests, list):
        out["catches"] = [str(t) for t in tests]
    elif isinstance(tests, dict):
        for kind in TEST_KINDS:
            out[kind] = [str(t) for t in tests.get(kind) or []]
    return out


def all_tests(lesson):
    seen, out = set(), []
    for kind in TEST_KINDS:
        for ref in tests_of(lesson)[kind]:
            if ref not in seen:
                seen.add(ref)
                out.append(ref)
    return out


def scope_of(lesson):
    scope = (lesson or {}).get("scope")
    if scope == "global" or scope == {}:
        return {}
    if isinstance(scope, dict):
        return scope
    return None


def is_process(lesson):
    return (lesson or {}).get("status") == PROCESS


def level_rank(level):
    return _RANK.get(level, -1)


def derive_level(lesson, checks):
    """The level the lesson's checks' tiers give; None for a process lesson, or when a check
    is not classified or none is named."""
    status = (lesson or {}).get("status")
    if status == PROCESS:
        return None
    if status == "gap" or lesson.get("lifecycle") == "candidate":
        return "experimental"
    if status not in CHECKED:
        return None
    named = list(lesson.get("checks") or [])
    tiers = [(checks or {}).get(c, {}).get("tier") for c in named]
    if not named or None in tiers:
        return None
    if "advisory" in tiers:
        return "recommended"
    if all(t == "hard" for t in tiers):
        return "blocking"
    return "required"


def level_of(lesson, checks):
    derived = derive_level(lesson, checks)
    declared = (lesson or {}).get("level")
    if derived is not None and declared in LEVELS and level_rank(declared) > level_rank(derived):
        return declared
    return derived


def scope_covers(wider, narrower):
    """True when every facet set `narrower` applies to, `wider` applies to as well."""
    wider, narrower = wider or {}, narrower or {}
    for key, values in wider.items():
        if key not in narrower:
            return False
        if not set(narrower.get(key) or ()) <= set(values or ()):
            return False
    return True


def version_of(data):
    version = str((data or {}).get("version") or "")
    return version if _SEMVER.match(version) else None


# ---------------------------------------------------------------------------- vocabulary


def _reader(root):
    from wgflib.yamllite import load as load_yaml

    def read(relative):
        with open(os.path.join(root, *relative.split("/")), encoding="utf-8") as handle:
            return load_yaml(handle.read())
    return read


def vocabulary(root=None):
    """{"families", "render", "platforms", "tiers", "categories", "category_render"}: what a
    scope and a category may name, from genre-models families, the platform profiles,
    quality-benchmark tiers and the quality-floor scorecard. Raises KnowledgeError when one
    of them cannot be read."""
    if root is None:
        from wgflib import paths
        root = paths.ROOT
    read = _reader(root)
    try:
        families = sorted(((read("core/reference/genre-models.yaml") or {})
                           .get("families") or {}).keys())
        tiers = [t.get("id") for t in (read("core/reference/quality-benchmark.yaml") or {})
                 .get("tiers") or [] if isinstance(t, dict) and t.get("id")]
        scorecard = (read("core/reference/quality-floor.yaml") or {}).get("scorecard") or {}
        directory = os.path.join(root, "core", "reference", "platforms")
        platforms = sorted(name[:-len(".yaml")] for name in os.listdir(directory)
                           if name.endswith(".yaml"))
    except (OSError, ValueError) as exc:
        raise KnowledgeError(f"the knowledge vocabularies cannot be read ({exc})")
    return {"families": families, "render": list(RENDERS), "platforms": platforms,
            "tiers": tiers, "categories": sorted(scorecard) + [PROCESS],
            "category_render": {k: v.get("render") for k, v in scorecard.items()
                                if isinstance(v, dict) and v.get("render")}}


# ------------------------------------------------------------------------------ problems


def _text(value):
    return isinstance(value, str) and value.strip() != ""


def _stamp_problems(at, key, value, required=True):
    if value is None:
        return [f"{at}: needs `{key}: {{version, date}}`"] if required else []
    if not isinstance(value, dict) or not _SEMVER.match(str(value.get("version") or "")) \
            or not _DATE.match(str(value.get("date") or "")):
        return [f"{at}: `{key}` is {{version: MAJOR.MINOR.PATCH, date: YYYY-MM-DD}}, not "
                f"{value!r}"]
    return []


def _scope_problems(at, lesson, vocab):
    raw = lesson.get("scope")
    if raw is None:
        return [f"{at}: has no scope - write `scope: global` for a rule that applies to every "
                "run, or the facets it applies to"]
    scope = scope_of(lesson)
    if scope is None:
        return [f"{at}: scope {raw!r} is neither `global` nor a mapping of facets"]
    problems = []
    for key, values in scope.items():
        if key in RESERVED_SCOPE_KEYS:
            problems.append(f"{at}: scope `{key}` is reserved for the archetype and complexity "
                            "profile registry, which does not exist yet")
            continue
        if key not in SCOPE_KEYS:
            problems.append(f"{at}: scope `{key}` is not one of {', '.join(SCOPE_KEYS)}")
            continue
        if not isinstance(values, list) or not values:
            problems.append(f"{at}: scope `{key}` lists at least one value")
            continue
        for value in values:
            if value not in (vocab or {}).get(key, ()):
                problems.append(f"{at}: scope {key} {value!r} is not one of "
                                f"{', '.join(map(str, (vocab or {}).get(key, ())))}")
    if is_process(lesson) and scope:
        problems.append(f"{at}: a process lesson is never in a run's contract; its scope is "
                        "`global`")
    return problems


def _level_problems(at, lesson, checks):
    if is_process(lesson):
        if lesson.get("level") is not None:
            return [f"{at}: a process lesson has no enforcement level"]
        return []
    derived = derive_level(lesson, checks)
    problems = []
    if derived is None:
        problems.append(f"{at}: has no enforcement level - an {lesson.get('status')} lesson "
                        "derives it from the tiers of the classified checks it names")
    declared = lesson.get("level")
    if declared is None:
        return problems
    if declared not in LEVELS:
        return problems + [f"{at}: level {declared!r} is not one of {', '.join(LEVELS)}"]
    if derived == "experimental":
        return problems + [f"{at}: a {lesson.get('lifecycle')} / {lesson.get('status')} "
                           "lesson is experimental; it declares no level"]
    if derived is None:
        return problems
    if level_rank(declared) < level_rank(derived):
        problems.append(f"{at}: declares level {declared}, weaker than the {derived} its "
                        "checks derive - a level is weakened only by moving a check's tier "
                        "(a new version of its source file) or by a superseding lesson")
    elif declared == derived:
        problems.append(f"{at}: declares level {declared}, which is what its checks derive - "
                        "levels are derived, never restated; remove `level`")
    if declared in ("blocking", "required"):
        advisory = [c for c in lesson.get("checks") or ()
                    if (checks or {}).get(c, {}).get("tier") == "advisory"]
        if advisory:
            problems.append(f"{at}: a {declared} rule holds the build, but "
                            f"{', '.join(advisory)} is advisory - move the check's tier first")
    return problems


def _lifecycle_problems(at, lesson, ids, evidence):
    lifecycle = lesson.get("lifecycle")
    status = lesson.get("status")
    if lifecycle not in LIFECYCLES:
        return [f"{at}: lifecycle {lifecycle!r} is not one of {', '.join(LIFECYCLES)}"]
    tests = tests_of(lesson)
    problems = []
    if status == "gap" and lifecycle not in ("candidate", "deprecated"):
        problems.append(f"{at}: nothing holds a gap lesson, so it is a candidate (or "
                        f"deprecated), not {lifecycle}")
    if lifecycle == "active" and status != PROCESS:
        if status not in CHECKED or not tests["catches"]:
            problems.append(f"{at}: an active lesson is enforced or partial and names the "
                            "tests that catch it (`tests.catches`)")
    if lifecycle == "validated":
        if status != "enforced":
            problems.append(f"{at}: a validated lesson is enforced")
        for kind in TEST_KINDS:
            if not tests[kind]:
                problems.append(f"{at}: a validated lesson names `tests.{kind}`")
        problems += _stamp_problems(at, "validated", lesson.get("validated"))
        if evidence is not None:
            leg = (((evidence or {}).get("lessons") or {}).get(lesson.get("id")) or {})
            if not leg.get("verified"):
                problems.append(f"{at}: a validated lesson has the instance evidence's "
                                "`verified` leg (the check passed on the game that raised it, "
                                "after the fix)")
    if lifecycle == "deprecated":
        successor = lesson.get("superseded_by")
        if successor is None and not _text(lesson.get("reason")):
            problems.append(f"{at}: a deprecated lesson names `superseded_by` or a `reason`")
        if successor is not None and (successor not in ids or successor == lesson.get("id")):
            problems.append(f"{at}: superseded_by {successor!r} is not another lesson")
    elif lesson.get("superseded_by") is not None:
        problems.append(f"{at}: only a deprecated lesson is superseded")
    return problems


def _tests_shape_problems(at, lesson):
    tests = lesson.get("tests")
    if tests is None or isinstance(tests, list):
        return []
    if not isinstance(tests, dict):
        return [f"{at}: tests is a mapping of {', '.join(TEST_KINDS)}"]
    problems = [f"{at}: tests.{key} is not one of {', '.join(TEST_KINDS)}"
                for key in tests if key not in TEST_KINDS]
    problems += [f"{at}: tests.{key} is a list" for key in TEST_KINDS
                 if tests.get(key) is not None and not isinstance(tests.get(key), list)]
    return problems


def lesson_problems(lessons, checks, vocab, evidence=None):
    """[problem] for the 2.0.0 fields of every lesson (the 1.x fields, check and test
    existence and game names stay with wgf_quality.registry.lesson_problems)."""
    if not isinstance(lessons, dict):
        return []
    problems = []
    entries = [l for l in lessons.get("lessons") or [] if isinstance(l, dict) and l.get("id")]
    ids = {l["id"] for l in entries}
    categories = (vocab or {}).get("categories") or ()
    for lesson in entries:
        at = f"{LESSONS_FILE} {lesson['id']}"
        if not _ID.match(str(lesson["id"])):
            problems.append(f"{at}: an id is a capital letter, then letters, digits or '-'")
        category = lesson.get("category")
        if category not in categories:
            problems.append(f"{at}: category {category!r} is not a quality-floor scorecard "
                            "line or `process`")
        elif (category == PROCESS) != is_process(lesson):
            problems.append(f"{at}: a process lesson, and only one, has category `process`")
        for key in ("problem", "root_cause"):
            if not _text(lesson.get(key)):
                problems.append(f"{at}: needs a {key}")
        problems += _scope_problems(at, lesson, vocab)
        render = ((vocab or {}).get("category_render") or {}).get(category)
        scope = scope_of(lesson) or {}
        if render and set(scope.get("render") or ()) != {render}:
            problems.append(f"{at}: category {category} is the {render} scorecard line; its "
                            f"scope is `render: [{render}]`")
        problems += _stamp_problems(at, "introduced", lesson.get("introduced"))
        problems += _tests_shape_problems(at, lesson)
        problems += _level_problems(at, lesson, checks)
        problems += _lifecycle_problems(at, lesson, ids, evidence)
    if evidence is not None:
        for lesson_id, leg in ((evidence or {}).get("lessons") or {}).items():
            source = (leg or {}).get("source") if isinstance(leg, dict) else None
            if not isinstance(source, dict) or source.get("kind") not in SOURCE_KINDS:
                problems.append(f"{EVIDENCE_FILE} {lesson_id}: needs `source: {{kind}}`, kind "
                                f"one of {', '.join(SOURCE_KINDS)}")
    return problems


def file_problems(lessons):
    """[problem] for the file's own blocks: a 2.x version, the lifecycle and level
    vocabularies as this model knows them, and the exception policy."""
    if not isinstance(lessons, dict):
        return [f"{LESSONS_FILE}: not a mapping"]
    problems = []
    version = version_of(lessons)
    if version is None:
        problems.append(f"{LESSONS_FILE}: needs a version MAJOR.MINOR.PATCH")
    elif int(version.split(".")[0]) < 2:
        problems.append(f"{LESSONS_FILE}: version {version} predates the knowledge model "
                        "(2.0.0)")
    if not isinstance(lessons.get("lessons"), list):
        problems.append(f"{LESSONS_FILE}: `lessons` is a list")
    if list(lessons.get("lifecycles") or []) != list(LIFECYCLES):
        problems.append(f"{LESSONS_FILE}: lifecycles are {', '.join(LIFECYCLES)}")
    if list(lessons.get("levels") or []) != list(LEVELS):
        problems.append(f"{LESSONS_FILE}: levels are {', '.join(LEVELS)}")
    policy = lessons.get("exceptions")
    if not isinstance(policy, dict):
        return problems + [f"{LESSONS_FILE}: needs the `exceptions` policy"]
    levels = list(policy.get("levels") or [])
    for level in levels:
        if level not in ("blocking", "required"):
            problems.append(f"{LESSONS_FILE} exceptions: {level!r} cannot be excepted - only "
                            "a blocking or required rule holds a build")
    approvers = policy.get("approvers") or {}
    for level in levels:
        modes = approvers.get(level)
        if not isinstance(modes, list) or not modes:
            problems.append(f"{LESSONS_FILE} exceptions: approvers.{level} lists who may "
                            "approve one")
            continue
        for mode in modes:
            if mode not in APPROVER_MODES:
                problems.append(f"{LESSONS_FILE} exceptions: approvers.{level} {mode!r} is not "
                                f"one of {', '.join(APPROVER_MODES)}")
    if "automation" in (approvers.get("blocking") or ()):
        problems.append(f"{LESSONS_FILE} exceptions: a blocking rule is excepted by a person "
                        "only - approvers.blocking never lists automation")
    days = policy.get("max_days")
    if not isinstance(days, int) or isinstance(days, bool) or days < 1:
        problems.append(f"{LESSONS_FILE} exceptions: max_days is a positive number of days")
    return problems


def weakening_problems(previous, current, checks):
    """[problem]: against the previous version of the file (from 2.0.0 on), a lesson
    deleted, or one not deprecated whose level is weaker or whose scope is narrower."""
    if not isinstance(previous, dict) or not isinstance(current, dict):
        return []
    version = version_of(previous)
    if version is None or int(version.split(".")[0]) < 2:
        return []
    now = {l.get("id"): l for l in current.get("lessons") or [] if isinstance(l, dict)}
    problems = []
    for old in previous.get("lessons") or []:
        if not isinstance(old, dict) or not old.get("id"):
            continue
        at = f"{LESSONS_FILE} {old['id']}"
        new = now.get(old["id"])
        if new is None:
            problems.append(f"{at}: deleted - a lesson id is never deleted or reused; "
                            "deprecate it")
            continue
        if new.get("lifecycle") == "deprecated" or old.get("lifecycle") == "deprecated":
            continue
        before, after = level_of(old, checks), level_of(new, checks)
        if before and after and level_rank(after) < level_rank(before):
            problems.append(f"{at}: level weakened in place ({before} -> {after}) - supersede "
                            "it with a new lesson")
        old_scope, new_scope = scope_of(old), scope_of(new)
        if old_scope is not None and new_scope is not None \
                and not scope_covers(new_scope, old_scope):
            problems.append(f"{at}: scope narrowed in place - a rule that applied to a run "
                            "would silently stop applying; supersede it with a new lesson")
    return problems


# ---------------------------------------------------------------------------- exceptions


def parse_time(value):
    """An aware datetime from an ISO 8601 date-time (`Z` or an offset), or None."""
    if not isinstance(value, str) or "T" not in value:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        moment = datetime.datetime.fromisoformat(text)
    except ValueError:
        return None
    return moment if moment.tzinfo else None


def exception_active(exception, now):
    expires = parse_time((exception or {}).get("expires_at"))
    return expires is not None and now is not None and now < expires


def exception_problems(exception, lessons, checks, now=None):
    """[problem] why `exception` (core/artifacts/shared/knowledge-exception.schema.json)
    cannot hold for the knowledge in `lessons`: an unknown rule, a level that cannot be
    excepted, a reason too short, an approver the policy does not accept for the rule's
    level (automation, by default for every level, and always for a blocking rule), no
    expiry or one past the policy's window, and - given `now` - one that has expired."""
    if not isinstance(exception, dict):
        return ["an exception is a mapping"]
    problems = []
    for key in ("rule_id", "reason", "scope", "approved_by", "created_at", "expires_at"):
        if exception.get(key) in (None, ""):
            problems.append(f"an exception needs `{key}`")
    policy = (lessons or {}).get("exceptions") or {}
    rule_id = exception.get("rule_id")
    rule = next((l for l in (lessons or {}).get("lessons") or []
                 if isinstance(l, dict) and l.get("id") == rule_id), None)
    level = None
    if rule_id and rule is None:
        problems.append(f"rule {rule_id!r} is not a lesson")
    elif rule is not None:
        level = level_of(rule, checks)
        if rule.get("lifecycle") == "deprecated" or is_process(rule):
            problems.append(f"rule {rule_id} is never in a run's contract; nothing to except")
        elif level not in (policy.get("levels") or ()):
            problems.append(f"rule {rule_id} is {level}: only "
                            f"{' or '.join(policy.get('levels') or ()) or 'no'} rules are "
                            "excepted (the others never block)")
    reason = exception.get("reason")
    if reason not in (None, "") and (not isinstance(reason, str)
                                     or len(reason.strip()) < REASON_MIN_LENGTH):
        problems.append(f"the reason says why the rule is accepted unmet, in at least "
                        f"{REASON_MIN_LENGTH} characters")
    approved = exception.get("approved_by")
    if approved not in (None, ""):
        mode = approved.get("mode") if isinstance(approved, dict) else None
        if not isinstance(approved, dict) or not _text(approved.get("identifier")):
            problems.append("approved_by names who approved it (`identifier`)")
        allowed = list((policy.get("approvers") or {}).get(level) or ()) if level else []
        if level == "blocking":
            allowed = [m for m in allowed if m != "automation"]
        if level and mode not in allowed:
            problems.append(f"unauthorized: a {level} rule is excepted by "
                            f"{' or '.join(allowed) or 'nobody'}, not {mode!r}"
                            + (" - a person, never automation" if mode == "automation" else ""))
    scope = exception.get("scope")
    if scope not in (None, "") and not isinstance(scope, dict):
        problems.append("scope is a mapping (empty: the whole run)")
    elif isinstance(scope, dict) and rule is not None:
        stray = [c for c in scope.get("checks") or () if c not in (rule.get("checks") or ())]
        if stray:
            problems.append(f"scope.checks {', '.join(map(str, stray))} are not checks of "
                            f"rule {rule_id}")
    created = parse_time(exception.get("created_at"))
    expires = parse_time(exception.get("expires_at"))
    if exception.get("created_at") not in (None, "") and created is None:
        problems.append("created_at is an ISO 8601 date-time with its offset")
    if exception.get("expires_at") not in (None, "") and expires is None:
        problems.append("expires_at is an ISO 8601 date-time with its offset")
    if created and expires:
        if expires <= created:
            problems.append("expires_at is after created_at")
        days = policy.get("max_days")
        if isinstance(days, int) and expires - created > datetime.timedelta(days=days):
            problems.append(f"expires_at is at most {days} days after created_at")
    if now is not None and expires is not None and now >= expires:
        problems.append(f"expired at {exception.get('expires_at')}")
    return problems

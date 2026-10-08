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
    run_level(lesson, checks)         the level it is held at in a run (None: never in one)
    weakening_problems(previous, current, previous_checks, current_checks=None)
                                      what the file now lets a run get away with that its
                                      previous version did not, each side judged by its
                                      own check tiers
    exception_problems(exception, lessons, checks, now, run_facets=None, vocabulary=None)
                                      why a person's exception cannot hold at `now`
    exception_active(exception, now)  True from its creation until it expires

`checks` is wgf_quality.registry.classify()'s first value: {"<source>:<id>": {"tier", ...}}.
Pure: no process, no network, no clock (a caller passes `now`). Nothing here names a game,
a step or a family.
"""

import datetime
import os
import re

__all__ = ["LEVELS", "LIFECYCLES", "SCOPE_KEYS", "RESERVED_SCOPE_KEYS", "TEST_KINDS",
           "SOURCE_KINDS", "APPROVER_MODES", "REASON_MIN_LENGTH", "REASON_MIN_WORDS",
           "MAX_EXCEPTION_DAYS", "PROCESS", "KnowledgeError", "run_level", "reason_problem",
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
# Distinct words (three letters or more) a reason carries: padding is not a reason.
REASON_MIN_WORDS = 4
# The longest exception window an installation may configure: a run's, not a standing waiver.
MAX_EXCEPTION_DAYS = 90
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
    """{"families", "render", "platforms", "tiers", "viewports", "categories",
    "category_render"}: what a scope, an exception's scope and a category may name, from
    genre-models families, the platform profiles, quality-benchmark tiers, the viewports
    browser QA and the playability bot play (browser-qa.yaml, visual-quality.yaml) and the
    quality-floor scorecard. Raises KnowledgeError when one of them cannot be read."""
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
        viewports = sorted({str(v.get("id")) for name in ("browser-qa.yaml",
                                                           "visual-quality.yaml")
                            for v in (read(f"core/reference/{name}") or {}).get("viewports")
                            or () if isinstance(v, dict) and v.get("id")})
    except (OSError, ValueError) as exc:
        raise KnowledgeError(f"the knowledge vocabularies cannot be read ({exc})")
    return {"families": families, "render": list(RENDERS), "platforms": platforms,
            "tiers": tiers, "viewports": viewports,
            "categories": sorted(scorecard) + [PROCESS],
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
    elif days > MAX_EXCEPTION_DAYS:
        problems.append(f"{LESSONS_FILE} exceptions: max_days {days} is over "
                        f"{MAX_EXCEPTION_DAYS} - an exception is a run's, not a standing waiver")
    return problems


def run_level(lesson, checks):
    """The level a lesson is held at in a run: None when it is never in a run's contract (a
    process lesson, or one deprecated in favour of a successor - the successor carries it);
    `recommended` for one deprecated with only a reason, which stays visible as advisory and
    never blocks; level_of otherwise."""
    if is_process(lesson):
        return None
    if (lesson or {}).get("lifecycle") == "deprecated":
        return None if lesson.get("superseded_by") else "recommended"
    return level_of(lesson, checks)


_TIER_RANK = {"advisory": 0, "quality": 1, "hard": 2}


def _effective(lesson, by_id):
    """The lesson that carries `lesson`'s rule in a run: its successor when it is deprecated
    in favour of one (followed to the end of the chain), else itself."""
    seen = set()
    while lesson.get("lifecycle") == "deprecated" and lesson.get("superseded_by") \
            and lesson["superseded_by"] in by_id and lesson["id"] not in seen:
        seen.add(lesson["id"])
        lesson = by_id[lesson["superseded_by"]]
    return lesson


def _policy_problems(previous, current):
    old = (previous or {}).get("exceptions") or {}
    new = (current or {}).get("exceptions") or {}
    at = f"{LESSONS_FILE} exceptions"
    problems = []
    added = sorted(set(new.get("levels") or ()) - set(old.get("levels") or ()))
    if added:
        problems.append(f"{at}: {', '.join(added)} rules became exceptable in place")
    for level, modes in ((new.get("approvers") or {}).items()):
        gained = sorted(set(modes or ()) - set(((old.get("approvers") or {}).get(level)) or ()))
        if gained and level in (old.get("levels") or ()):
            problems.append(f"{at}: approvers.{level} gained {', '.join(gained)} in place")
    before, after = old.get("max_days"), new.get("max_days")
    if isinstance(before, int) and isinstance(after, int) and after > before:
        problems.append(f"{at}: max_days widened in place ({before} -> {after})")
    return problems


def weakening_problems(previous, current, previous_checks, current_checks=None):
    """[problem]: what the current lessons file lets a run get away with that the previous
    version (from 2.0.0 on) did not - each side judged by its OWN check tiers
    (`previous_checks`, `current_checks`; the latter defaults to the former):

      * a lesson deleted (ids are never deleted);
      * a rule held at a weaker level in a run - its level derived lower (a check's tier
        demoted, a lifecycle back to candidate, a status turned process or gap), or a
        successor weaker than the lesson it supersedes;
      * a check a rule named that it no longer names, or whose tier was demoted;
      * a scope narrowed in place (or a successor's narrower than its predecessor's);
      * the exception policy loosened: a level made exceptable, an approver mode added,
        the window widened.

    A lesson deprecated with only a reason is held as advisory in every run it applied to
    (run_level), visibly, and never blocks - the explicit, reviewed way to retire a rule
    without a successor. Against a 1.x file only deletions are checked: it had no levels
    or scopes to weaken."""
    if not isinstance(previous, dict) or not isinstance(current, dict):
        return []
    current_checks = previous_checks if current_checks is None else current_checks
    now = {l.get("id"): l for l in current.get("lessons") or [] if isinstance(l, dict)}
    problems = []
    version = version_of(previous)
    modern = version is not None and int(version.split(".")[0]) >= 2
    for old in previous.get("lessons") or []:
        if not isinstance(old, dict) or not old.get("id"):
            continue
        at = f"{LESSONS_FILE} {old['id']}"
        new = now.get(old["id"])
        if new is None:
            problems.append(f"{at}: deleted - a lesson id is never deleted or reused; "
                            "deprecate it")
            continue
        if not modern or is_process(old) or old.get("lifecycle") == "deprecated":
            continue
        carried = _effective(new, now)
        via = "" if carried is new else f" (through its successor {carried['id']})"
        before = run_level(old, previous_checks)
        after = run_level(carried, current_checks)
        if before is not None and level_rank(after) < level_rank(before):
            problems.append(f"{at}: weakened in place - held {before} in a run before, "
                            f"{after or 'in no run'} now{via}; supersede it with a lesson at "
                            "least as strong")
        if carried.get("lifecycle") == "deprecated":
            continue                # retired with a reason: advisory, visible (above)
        kept = set(carried.get("checks") or ())
        for check in old.get("checks") or ():
            if check not in kept:
                problems.append(f"{at}: no longer held by {check}{via} - a check is removed "
                                "from a rule only by a superseding lesson")
                continue
            was = _TIER_RANK.get((previous_checks or {}).get(check, {}).get("tier"))
            is_ = _TIER_RANK.get((current_checks or {}).get(check, {}).get("tier"))
            if was is not None and (is_ is None or is_ < was):
                problems.append(f"{at}: {check} was demoted from "
                                f"{previous_checks[check]['tier']} to "
                                f"{(current_checks or {}).get(check, {}).get('tier')}")
        old_scope, new_scope = scope_of(old), scope_of(carried)
        if old_scope is not None and (new_scope is None
                                      or not scope_covers(new_scope, old_scope)):
            problems.append(f"{at}: scope narrowed in place{via} - a rule that applied to a "
                            "run would silently stop applying; supersede it with a new lesson")
    if modern:
        problems += _policy_problems(previous, current)
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
    created = parse_time((exception or {}).get("created_at"))
    return (expires is not None and created is not None and now is not None
            and created <= now < expires)


def reason_problem(reason):
    """Why `reason` does not say why a rule is accepted unmet, or None: at least
    REASON_MIN_LENGTH characters, at least REASON_MIN_WORDS distinct words of three letters
    or more, and no word making up more than half of them (padding is not a reason)."""
    if not isinstance(reason, str) or len(reason.strip()) < REASON_MIN_LENGTH:
        return (f"the reason says why the rule is accepted unmet, in at least "
                f"{REASON_MIN_LENGTH} characters")
    words = [w.lower() for w in re.findall(r"[^\W\d_]{3,}", reason)]
    if len(set(words)) < REASON_MIN_WORDS:
        return (f"the reason is not a sentence: at least {REASON_MIN_WORDS} distinct words "
                "say why the rule is accepted unmet")
    top = max(words.count(w) for w in set(words))
    if top * 2 > len(words):
        return "the reason repeats one word: padding is not a reason"
    return None


def exception_problems(exception, lessons, checks, now, run_facets=None, vocabulary=None):
    """[problem] why `exception` (core/artifacts/shared/knowledge-exception.schema.json)
    cannot hold, read at `now` (required: an exception is judged at the moment it is read,
    never without one):

      * an unknown rule, or one whose run level cannot be excepted (exceptions.levels);
      * no reason, or one that does not say anything (reason_problem);
      * an approver the policy does not accept for the rule's level - automation for every
        level as shipped, and for a blocking rule always;
      * created after `now`, expiring before it was created, past the policy's window, or
        expired at `now`;
      * a scope outside the rule or the run: checks the rule does not name, platforms the
        run does not target (`run_facets`) or the rule is not scoped to, platforms and
        viewports the Factory does not know (`vocabulary`, model.vocabulary(); without it a
        platform or viewport scope cannot be checked and is refused).

    The record's `approved_by` is what the record says; it is never trusted on its own. The
    operator act that grants an exception stamps `approved_by.mode` itself, from who is
    running the command (a command inside a Factory step's process tree is `automation`),
    and the run keeps it as its own event - a record written anywhere else is not an
    exception."""
    if not isinstance(exception, dict):
        return ["an exception is a mapping"]
    problems = []
    if now is None:
        problems.append("an exception is judged at the moment it is read: no time was given, "
                        "so it does not hold")
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
        level = run_level(rule, checks)
        if level is None:
            problems.append(f"rule {rule_id} is never in a run's contract; nothing to except")
        elif level not in (policy.get("levels") or ()):
            problems.append(f"rule {rule_id} is {level}: only "
                            f"{' or '.join(policy.get('levels') or ()) or 'no'} rules are "
                            "excepted (the others never block)")
    reason = exception.get("reason")
    if reason not in (None, ""):
        why = reason_problem(reason)
        if why:
            problems.append(why)
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
    elif isinstance(scope, dict):
        problems += _exception_scope_problems(scope, rule, rule_id, run_facets, vocabulary)
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
    if now is not None and created is not None and created > now:
        problems.append(f"created in the future ({exception.get('created_at')}): an exception "
                        "exists from when a person granted it")
    if now is not None and expires is not None and now >= expires:
        problems.append(f"expired at {exception.get('expires_at')}")
    return problems


def _exception_scope_problems(scope, rule, rule_id, run_facets, vocabulary):
    problems = []
    unknown = sorted(set(scope) - {"platforms", "checks", "viewports"})
    if unknown:
        problems.append(f"scope has unknown key(s) {', '.join(unknown)}")
    if rule is not None:
        stray = [c for c in scope.get("checks") or () if c not in (rule.get("checks") or ())]
        if stray:
            problems.append(f"scope.checks {', '.join(map(str, stray))} are not checks of "
                            f"rule {rule_id}")
    platforms = [str(p) for p in scope.get("platforms") or ()]
    if platforms:
        known = (vocabulary or {}).get("platforms")
        targeted = list((run_facets or {}).get("platforms") or ())
        ruled = (scope_of(rule) or {}).get("platforms") if rule is not None else None
        if known is None:
            problems.append("scope.platforms cannot be checked without the platform "
                            "vocabulary; it is refused")
        else:
            stray = [p for p in platforms if p not in known]
            if stray:
                problems.append(f"scope.platforms {', '.join(stray)} are not platforms")
        if targeted:
            stray = [p for p in platforms if p not in targeted]
            if stray:
                problems.append(f"scope.platforms {', '.join(stray)} are not targeted by "
                                "this run")
        if ruled:
            stray = [p for p in platforms if p not in ruled]
            if stray:
                problems.append(f"scope.platforms {', '.join(stray)} are outside rule "
                                f"{rule_id}'s scope")
    viewports = [str(v) for v in scope.get("viewports") or ()]
    if viewports:
        known = (vocabulary or {}).get("viewports")
        if known is None:
            problems.append("scope.viewports cannot be checked without the viewport "
                            "vocabulary; it is refused")
        else:
            stray = [v for v in viewports if v not in known]
            if stray:
                problems.append(f"scope.viewports {', '.join(stray)} are not viewports a "
                                "gate plays")
    return problems

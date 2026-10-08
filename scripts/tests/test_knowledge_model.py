"""The knowledge model (K1): core/reference/lessons.yaml 2.0.0 as rules with a scope, a level
derived from check tiers, a lifecycle, and person-only exceptions.

These tests hold, each with its negative:

  * ingestion: a well-formed new rule is accepted; an invalid, duplicate or malformed one is
    refused by the integrity check, and a malformed or versionless file is unusable;
  * enforcement levels are DERIVED from the tiers of the rule's checks - the shipped L1-L28
    are exactly the design's table - and a declared level is only ever stronger, never
    restated, never on an advisory check;
  * every rule has a scope and a derivable level, in its vocabularies (a lesson without
    either fails integrity); the lifecycle's requirements hold;
  * an exception is a person's: schema-valid with a reason, a scope, an approver and an
    expiry; refused when the reason is missing or short, when it has expired, when it is
    automation's (always for a blocking rule; for a required one only while the data switch
    says so), and for a rule that never blocks;
  * the versions a run is judged by are recorded with their digests;
  * a level weakened or a scope narrowed in place, or a lesson deleted, fails against the
    previous version of the file.

    python -m unittest scripts.tests.test_knowledge_model
"""

import copy
import datetime
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
for _path in (SCRIPTS, HERE):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from test_regression_registry import Sandbox  # noqa: E402
from wgf_knowledge import model, versions  # noqa: E402
from wgf_quality import registry  # noqa: E402
from wgflib import jsonschema_lite as js  # noqa: E402
from wgflib.workflow.contracts import load_registry  # noqa: E402

DATA = registry.load(ROOT)
CHECKS, _ = registry.classify(DATA["tiers"], ROOT)
LESSONS = DATA["lessons"]
BY_ID = {l["id"]: l for l in LESSONS["lessons"]}

# The design's table (learning-enforcement design 2.3), computed from the integ registry.
EXPECTED_LEVELS = {
    "blocking": {"L3", "L5", "L10", "L12", "L15", "L22"},
    "required": {"L1", "L2", "L4", "L7", "L11", "L13", "L14", "L20", "L23", "L24", "L25",
                 "L26", "L27", "L28"},
    "experimental": {"L8", "L9", "L16", "L17", "L18", "L21"},
    "recommended": set(),
}
PROCESS = {"L6", "L19"}

NOW = datetime.datetime(2026, 10, 8, 12, 0, tzinfo=datetime.timezone.utc)


def _exception_schema():
    with open(os.path.join(ROOT, "core", "artifacts", "shared",
                           "knowledge-exception.schema.json"), encoding="utf-8") as handle:
        return js.Validator(json.load(handle), load_registry())


def exception(**changes):
    record = {"rule_id": "L26", "reason": "The HUD card overlap on tablet is accepted for "
              "this soft launch; the layout rework lands next release.",
              "scope": {"platforms": ["y8"]},
              "approved_by": {"identifier": "a.person", "mode": "human"},
              "created_at": "2026-10-08T09:00:00Z", "expires_at": "2026-10-20T09:00:00Z"}
    record.update(changes)
    return {k: v for k, v in record.items() if v is not None}


class Lessons(Sandbox):
    """A copy of the knowledge files to change one lesson at a time."""

    def lessons(self):
        return self.read("core/reference/lessons.yaml")

    def set_lesson(self, lesson_id, **changes):
        data = self.lessons()
        for lesson in data["lessons"]:
            if lesson["id"] == lesson_id:
                lesson.update(changes)
                for key, value in list(changes.items()):
                    if value is None:
                        del lesson[key]
        self.write("core/reference/lessons.yaml", data)

    def add_lesson(self, lesson):
        data = self.lessons()
        data["lessons"].append(lesson)
        self.write("core/reference/lessons.yaml", data)

    def has(self, text):
        problems = self.problems()
        self.assertTrue(any(text in p for p in problems), problems)


NEW_RULE = {"id": "L29", "title": "A new rule", "category": "audio",
            "problem": "A sound played at the wrong moment.",
            "root_cause": "Nothing compared sound events with game events.",
            "lesson": "Every sound event follows the game event it belongs to.",
            "scope": {"families": ["arcade"], "render": ["2d"]},
            "status": "enforced", "lifecycle": "active",
            "introduced": {"version": "2.8.0", "date": "2026-10-08"},
            "checks": ["browser-qa:browser.audio-events"],
            "tests": {"catches": ["scripts/tests/test_browser_qa.py::test_an_end_state_without_a_sound"],
                      "passes": [], "generalizes": []}}


# ------------------------------------------------------------------------------ ingestion


class Ingestion(Lessons):
    def test_a_well_formed_new_rule_is_accepted(self):
        self.add_lesson(copy.deepcopy(NEW_RULE))
        self.assertEqual(self.problems(), [])
        checks, _ = registry.classify(self.read("core/reference/check-tiers.yaml"), self.root)
        rule = next(l for l in self.lessons()["lessons"] if l["id"] == "L29")
        self.assertEqual(model.level_of(rule, checks), "required")

    def test_a_rule_missing_its_fields_is_refused(self):
        rule = copy.deepcopy(NEW_RULE)
        for key in ("category", "problem", "root_cause", "introduced"):
            del rule[key]
        self.add_lesson(rule)
        problems = self.problems()
        for text in ("L29: category None", "L29: needs a problem", "L29: needs a root_cause",
                     "L29: needs `introduced"):
            self.assertTrue(any(text in p for p in problems), (text, problems))

    def test_a_duplicate_id_is_refused(self):
        self.add_lesson(dict(copy.deepcopy(NEW_RULE), id="L23"))
        self.has("L23: the id is used twice")

    def test_a_malformed_rule_is_refused(self):
        self.add_lesson(dict(copy.deepcopy(NEW_RULE), tests="all of them",
                             scope="everywhere", id="l29"))
        problems = self.problems()
        for text in ("l29: an id is a capital letter", "l29: tests is a mapping",
                     "l29: scope 'everywhere' is neither"):
            self.assertTrue(any(text in p for p in problems), (text, problems))

    def test_an_unknown_test_kind_is_refused(self):
        rule = copy.deepcopy(NEW_RULE)
        rule["tests"]["proves"] = []
        self.add_lesson(rule)
        self.has("L29: tests.proves is not one of catches, passes, generalizes")

    def test_a_lesson_that_is_not_a_mapping_is_refused(self):
        data = self.lessons()
        data["lessons"].append("L29 a sentence")
        self.write("core/reference/lessons.yaml", data)
        self.has("lessons[28]: needs an id")

    def test_a_malformed_file_is_unusable(self):
        path = os.path.join(self.root, "core", "reference", "lessons.yaml")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("version: 2.0.0\nlessons: [unclosed\n")
        self.assertTrue(any("cannot be read" in p for p in self.problems()))
        with self.assertRaises(model.KnowledgeError):
            versions.knowledge(root=self.root)

    def test_a_versionless_or_listless_file_is_refused(self):
        data = self.lessons()
        del data["version"]
        self.write("core/reference/lessons.yaml", data)
        with self.assertRaisesRegex(model.KnowledgeError, "no version"):
            versions.knowledge(root=self.root)
        self.has("needs a version MAJOR.MINOR.PATCH")
        data["version"] = "2.0.0"
        data["lessons"] = {"L1": "a mapping, not a list"}
        self.write("core/reference/lessons.yaml", data)
        with self.assertRaisesRegex(model.KnowledgeError, "no `lessons` list"):
            versions.knowledge(root=self.root)

    def test_a_1x_file_predates_the_model(self):
        data = self.lessons()
        data["version"] = "1.0.0"
        self.write("core/reference/lessons.yaml", data)
        self.has("predates the knowledge model")


# ------------------------------------------------------------------------- levels


class Levels(unittest.TestCase):
    def test_levels_derive_from_check_tiers(self):
        found = {level: set() for level in model.LEVELS}
        process = set()
        for lesson in LESSONS["lessons"]:
            if model.is_process(lesson):
                process.add(lesson["id"])
                self.assertIsNone(model.level_of(lesson, CHECKS))
                continue
            found[model.level_of(lesson, CHECKS)].add(lesson["id"])
        self.assertEqual(found, EXPECTED_LEVELS)
        self.assertEqual(process, PROCESS)

    def test_no_shipped_lesson_restates_its_level(self):
        self.assertEqual([l["id"] for l in LESSONS["lessons"] if "level" in l], [])

    def test_the_tiers_decide_the_level(self):
        lesson = {"id": "X", "status": "enforced", "lifecycle": "active"}
        hard = "playability:probe.present"
        quality = "playability:depth.ramp"
        advisory = next(c for c, e in CHECKS.items() if e["tier"] == "advisory")
        cases = {(hard,): "blocking", (hard, quality): "required", (quality,): "required",
                 (hard, advisory): "recommended", (advisory,): "recommended"}
        for named, level in cases.items():
            with self.subTest(checks=named):
                self.assertEqual(model.derive_level(dict(lesson, checks=list(named)), CHECKS),
                                 level)
        self.assertEqual(model.derive_level(dict(lesson, status="gap"), CHECKS),
                         "experimental")
        self.assertEqual(model.derive_level(dict(lesson, lifecycle="candidate",
                                                 checks=[hard]), CHECKS), "experimental")
        self.assertIsNone(model.derive_level(dict(lesson, checks=["playability:nope"]),
                                             CHECKS))
        self.assertIsNone(model.derive_level(dict(lesson, checks=[]), CHECKS))

    def test_a_stronger_declared_level_is_in_force(self):
        lesson = dict(BY_ID["L23"], level="blocking")
        self.assertEqual(model.derive_level(lesson, CHECKS), "required")
        self.assertEqual(model.level_of(lesson, CHECKS), "blocking")

    def test_a_weaker_declared_level_is_never_in_force(self):
        lesson = dict(BY_ID["L5"], level="recommended")
        self.assertEqual(model.level_of(lesson, CHECKS), "blocking")


class LevelIntegrity(Lessons):
    def test_a_declared_level_weaker_than_derived_fails(self):
        self.set_lesson("L5", level="required")
        self.has("L5: declares level required, weaker than the blocking its checks derive")

    def test_a_declared_level_equal_to_the_derived_one_is_a_restatement(self):
        self.set_lesson("L23", level="required")
        self.has("L23: declares level required, which is what its checks derive")

    def test_a_stronger_declared_level_is_accepted(self):
        self.set_lesson("L23", level="blocking")
        self.assertEqual(self.problems(), [])

    def test_a_blocking_rule_on_an_advisory_check_fails(self):
        advisory = next(c for c, e in CHECKS.items() if e["tier"] == "advisory")
        self.set_lesson("L2", checks=[advisory], level="blocking")
        self.has(f"L2: a blocking rule holds the build, but {advisory} is advisory")

    def test_a_candidate_declares_no_level(self):
        self.set_lesson("L8", level="required")
        self.has("L8: a candidate / gap lesson is experimental; it declares no level")

    def test_a_lesson_without_a_level_fails(self):
        self.set_lesson("L20", checks=None)
        self.has("L20: has no enforcement level")

    def test_a_lesson_whose_check_is_not_classified_has_no_level(self):
        self.set_lesson("L20", checks=["content-sufficiency:content.nothing"])
        self.has("L20: has no enforcement level")


# --------------------------------------------------------------------- scope, category


class ScopeIntegrity(Lessons):
    def test_a_lesson_without_scope_fails(self):
        self.set_lesson("L23", scope=None)
        self.has("L23: has no scope - write `scope: global`")

    def test_scope_values_are_in_their_vocabularies(self):
        self.set_lesson("L23", scope={"families": ["arcade", "kart"], "render": ["4d"],
                                      "platforms": ["y8", "nowhere"], "tiers": ["gold"]})
        problems = self.problems()
        for text in ("scope families 'kart'", "scope render '4d'", "scope platforms 'nowhere'",
                     "scope tiers 'gold'"):
            self.assertTrue(any(f"L23: {text}" in p for p in problems), (text, problems))

    def test_a_valid_scope_is_accepted(self):
        self.set_lesson("L23", scope={"families": ["arcade", "platformer"],
                                      "platforms": ["y8"], "tiers": ["release"]})
        self.assertEqual(self.problems(), [])

    def test_profiles_and_archetypes_are_reserved(self):
        self.set_lesson("L23", scope={"profiles": ["B"]})
        self.has("L23: scope `profiles` is reserved")

    def test_an_unknown_scope_key_fails(self):
        self.set_lesson("L23", scope={"engines": ["phaser"]})
        self.has("L23: scope `engines` is not one of")

    def test_an_empty_scope_value_fails(self):
        self.set_lesson("L23", scope={"families": []})
        self.has("L23: scope `families` lists at least one value")

    def test_a_process_lesson_is_global(self):
        self.set_lesson("L6", scope={"render": ["2d"]})
        self.has("L6: a process lesson is never in a run's contract")

    def test_the_category_is_a_scorecard_line(self):
        self.set_lesson("L23", category="fun")
        self.has("L23: category 'fun' is not a quality-floor scorecard line")

    def test_only_a_process_lesson_is_in_the_process_category(self):
        self.set_lesson("L23", category="process")
        self.has("L23: a process lesson, and only one, has category `process`")

    def test_a_render_line_category_carries_its_render_scope(self):
        self.set_lesson("L15", scope="global")
        self.has("L15: category art_3d is the 3d scorecard line")


# ------------------------------------------------------------------------- lifecycle


class Lifecycle(Lessons):
    def test_the_shipped_lifecycles(self):
        for lesson in LESSONS["lessons"]:
            expected = "candidate" if lesson["status"] == "gap" else "active"
            self.assertEqual(lesson["lifecycle"], expected, lesson["id"])

    def test_an_active_gap_fails(self):
        self.set_lesson("L8", lifecycle="active")
        self.has("L8: nothing holds a gap lesson, so it is a candidate")

    def test_an_active_lesson_names_what_catches_it(self):
        self.set_lesson("L25", tests={"catches": [], "passes": [
            "scripts/tests/test_browser_qa.py::test_context_menu_left_open_fails_at_release"],
            "generalizes": []})
        self.has("L25: an active lesson is enforced or partial and names the tests that "
                 "catch it")

    def test_a_validated_lesson_needs_all_three_tests_and_the_rerun_leg(self):
        self.set_lesson("L23", lifecycle="validated")
        problems = self.problems()
        for text in ("L23: a validated lesson names `tests.generalizes`",
                     "L23: needs `validated: {version, date}`",
                     "L23: a validated lesson has the instance evidence's `verified` leg"):
            self.assertTrue(any(text in p for p in problems), (text, problems))

    def test_a_validated_lesson_with_its_evidence_passes(self):
        lesson = next(l for l in self.lessons()["lessons"] if l["id"] == "L23")
        tests = lesson["tests"]
        tests["generalizes"] = [tests["catches"][0]]
        self.set_lesson("L23", lifecycle="validated", tests=tests,
                        validated={"version": "2.8.0", "date": "2026-10-08"})
        evidence = self.read("workspace/lessons/evidence.yaml")
        evidence["lessons"]["L23"]["verified"] = {"run": "wgf-run", "commit": "a" * 40}
        self.write("workspace/lessons/evidence.yaml", evidence)
        self.assertEqual(self.problems(), [])

    def test_a_deprecated_lesson_names_its_successor_or_reason(self):
        self.set_lesson("L2", lifecycle="deprecated")
        self.has("L2: a deprecated lesson names `superseded_by` or a `reason`")
        self.set_lesson("L2", superseded_by="L99")
        self.has("L2: superseded_by 'L99' is not another lesson")
        self.set_lesson("L2", superseded_by="L7")
        self.assertEqual(self.problems(), [])

    def test_only_a_deprecated_lesson_is_superseded(self):
        self.set_lesson("L2", superseded_by="L7")
        self.has("L2: only a deprecated lesson is superseded")

    def test_an_unknown_lifecycle_fails(self):
        self.set_lesson("L2", lifecycle="retired")
        self.has("L2: lifecycle 'retired' is not one of")

    def test_evidence_names_its_source_kind(self):
        evidence = self.read("workspace/lessons/evidence.yaml")
        evidence["lessons"]["L2"]["source"] = {"kind": "rumour"}
        self.write("workspace/lessons/evidence.yaml", evidence)
        self.has("evidence.yaml L2: needs `source: {kind}`")


# ------------------------------------------------------------------------- exceptions


class ExceptionPolicy(Lessons):
    def test_the_shipped_policy_is_person_only_for_both_levels(self):
        policy = LESSONS["exceptions"]
        self.assertEqual(policy["levels"], ["blocking", "required"])
        self.assertEqual(policy["approvers"], {"blocking": ["human"], "required": ["human"]})

    def test_automation_may_never_except_a_blocking_rule(self):
        data = self.lessons()
        data["exceptions"]["approvers"]["blocking"] = ["human", "automation"]
        self.write("core/reference/lessons.yaml", data)
        self.has("a blocking rule is excepted by a person only")

    def test_switching_required_to_automation_is_a_data_change_integrity_accepts(self):
        data = self.lessons()
        data["exceptions"]["approvers"]["required"] = ["human", "automation"]
        self.write("core/reference/lessons.yaml", data)
        self.assertEqual(self.problems(), [])

    def test_a_level_that_never_blocks_cannot_be_excepted(self):
        data = self.lessons()
        data["exceptions"]["levels"].append("recommended")
        self.write("core/reference/lessons.yaml", data)
        self.has("'recommended' cannot be excepted")

    def test_a_window_is_a_positive_number_of_days(self):
        data = self.lessons()
        data["exceptions"]["max_days"] = 0
        self.write("core/reference/lessons.yaml", data)
        self.has("max_days is a positive number of days")


class Exceptions(unittest.TestCase):
    def setUp(self):
        self.schema = _exception_schema()

    def problems(self, record, lessons=LESSONS, now=NOW):
        return model.exception_problems(record, lessons, CHECKS, now=now)

    def test_a_persons_exception_is_valid(self):
        record = exception()
        self.assertEqual(self.schema.iter_errors(record), [])
        self.assertEqual(self.problems(record), [])
        self.assertTrue(model.exception_active(record, NOW))

    def test_a_blocking_rule_is_excepted_by_a_person(self):
        record = exception(rule_id="L5", scope={})
        self.assertEqual(self.schema.iter_errors(record), [])
        self.assertEqual(self.problems(record), [])

    def test_an_exception_without_a_reason_is_refused(self):
        record = exception(reason=None)
        self.assertTrue(any("reason" in str(e) for e in self.schema.iter_errors(record)))
        self.assertIn("an exception needs `reason`", self.problems(record))

    def test_a_reason_too_short_is_refused(self):
        record = exception(reason="ok for now")
        self.assertTrue(self.schema.iter_errors(record))
        self.assertTrue(any("at least 20 characters" in p for p in self.problems(record)))

    def test_an_expired_exception_is_refused(self):
        record = exception()
        later = datetime.datetime(2026, 10, 21, tzinfo=datetime.timezone.utc)
        self.assertEqual(self.schema.iter_errors(record), [])   # the schema cannot know
        self.assertIn("expired at 2026-10-20T09:00:00Z", self.problems(record, now=later))
        self.assertFalse(model.exception_active(record, later))

    def test_an_exception_without_expiry_is_refused(self):
        record = exception(expires_at=None)
        self.assertTrue(self.schema.iter_errors(record))
        self.assertIn("an exception needs `expires_at`", self.problems(record))

    def test_an_expiry_past_the_window_is_refused(self):
        record = exception(expires_at="2026-12-31T00:00:00Z")
        self.assertTrue(any("at most 30 days" in p for p in self.problems(record)))
        record = exception(expires_at="2026-10-01T00:00:00Z")
        self.assertTrue(any("expires_at is after created_at" in p
                            for p in self.problems(record)))

    def test_automation_cannot_except_a_required_rule_as_shipped(self):
        record = exception(approved_by={"identifier": "develop", "mode": "automation"})
        self.assertEqual(self.schema.iter_errors(record), [])   # the shape allows it ...
        self.assertTrue(any(p.startswith("unauthorized: a required rule is excepted by human")
                            for p in self.problems(record)))   # ... the policy does not

    def test_automation_never_excepts_a_blocking_rule_whatever_the_data_says(self):
        lessons = copy.deepcopy(LESSONS)
        lessons["exceptions"]["approvers"] = {"blocking": ["human", "automation"],
                                              "required": ["human", "automation"]}
        automated = {"identifier": "develop", "mode": "automation"}
        self.assertEqual(self.problems(exception(approved_by=automated), lessons), [])
        blocking = exception(rule_id="L5", approved_by=automated)
        self.assertTrue(any("a person, never automation" in p
                            for p in self.problems(blocking, lessons)))

    def test_an_unknown_approver_mode_is_refused_by_the_schema(self):
        record = exception(approved_by={"identifier": "x", "mode": "config"})
        self.assertTrue(self.schema.iter_errors(record))

    def test_a_rule_that_never_blocks_is_not_excepted(self):
        self.assertTrue(any("only blocking or required rules are excepted" in p
                            for p in self.problems(exception(rule_id="L8"))))
        self.assertTrue(any("never in a run's contract" in p
                            for p in self.problems(exception(rule_id="L6"))))

    def test_an_unknown_rule_is_refused(self):
        self.assertIn("rule 'L99' is not a lesson", self.problems(exception(rule_id="L99")))

    def test_a_scope_check_outside_the_rule_is_refused(self):
        record = exception(scope={"checks": ["playability:depth.ramp"]})
        self.assertTrue(any("are not checks of rule L26" in p for p in self.problems(record)))

    def test_the_schemas_reason_floor_is_the_models(self):
        self.assertEqual(self.schema.schema["properties"]["reason"]["minLength"],
                         model.REASON_MIN_LENGTH)


# ---------------------------------------------------------------------------- versions


class Versions(unittest.TestCase):
    def test_the_knowledge_versions_a_run_records(self):
        self.assertEqual(versions.knowledge(root=ROOT),
                         {"lessons": "lessons@2.0.0", "check-tiers": "check-tiers@1.1.0"})

    def test_collect_records_every_version_and_the_knowledge_digests(self):
        import hashlib
        found = versions.collect(root=ROOT, workflow={"id": "new-game", "version": 16},
                                 platforms=["y8"])
        for key, relpath in (("lessons", versions.FILES["lessons"]),
                             ("check_tiers", versions.FILES["check_tiers"])):
            with open(os.path.join(ROOT, *relpath.split("/")), "rb") as handle:
                digest = "sha256:" + hashlib.sha256(handle.read()).hexdigest()
            self.assertEqual(found[key]["sha256"], digest)
        self.assertEqual(found["lessons"]["version"], "2.0.0")
        self.assertEqual(found["check_tiers"]["version"], "1.1.0")
        with open(os.path.join(ROOT, "VERSION"), encoding="utf-8") as handle:
            self.assertEqual(found["factory"]["version"], handle.read().strip())
        commit = found["factory"]["commit"]
        self.assertTrue(commit is None or len(commit) == 40)
        self.assertEqual(found["workflow"], {"id": "new-game", "version": 16})
        self.assertTrue(found["platform_profiles"]["y8"].startswith("y8@"))
        for key in ("quality_policy", "quality_benchmark", "quality_floor", "genre_models"):
            self.assertRegex(found[key], r"^[0-9]+\.[0-9]+\.[0-9]+$")

    def test_a_pinned_reader_is_what_is_recorded(self):
        pinned = {"core/reference/lessons.yaml": b"version: 2.1.0\nlessons: []\n"}

        def read(relpath):
            if relpath in pinned:
                return pinned[relpath]
            with open(os.path.join(ROOT, *relpath.split("/")), "rb") as handle:
                return handle.read()
        found = versions.collect(read=read, root=ROOT)
        self.assertEqual(found["lessons"]["version"], "2.1.0")

    def test_an_unreadable_file_is_refused(self):
        def read(relpath):
            raise OSError("gone")
        with self.assertRaisesRegex(model.KnowledgeError, "cannot be read"):
            versions.knowledge(read=read)


# -------------------------------------------------------------------------- weakening


class Weakening(unittest.TestCase):
    def current(self):
        return copy.deepcopy(LESSONS)

    def test_an_unchanged_file_has_no_problem(self):
        self.assertEqual(model.weakening_problems(LESSONS, self.current(), CHECKS), [])

    def test_a_weakened_level_without_supersession_fails_integrity(self):
        previous = self.current()
        next(l for l in previous["lessons"] if l["id"] == "L23")["level"] = "blocking"
        problems = model.weakening_problems(previous, self.current(), CHECKS)
        self.assertTrue(any("L23: level weakened in place (blocking -> required)" in p
                            for p in problems), problems)

    def test_a_narrowed_scope_fails(self):
        current = self.current()
        next(l for l in current["lessons"] if l["id"] == "L1")["scope"] = {"render": ["2d"]}
        problems = model.weakening_problems(LESSONS, current, CHECKS)
        self.assertTrue(any("L1: scope narrowed in place" in p for p in problems), problems)

    def test_a_widened_scope_and_a_stronger_level_pass(self):
        current = self.current()
        l15 = next(l for l in current["lessons"] if l["id"] == "L15")
        l15["scope"] = "global"
        next(l for l in current["lessons"] if l["id"] == "L23")["level"] = "blocking"
        self.assertEqual(model.weakening_problems(LESSONS, current, CHECKS), [])

    def test_a_deleted_lesson_fails(self):
        current = self.current()
        current["lessons"] = [l for l in current["lessons"] if l["id"] != "L25"]
        problems = model.weakening_problems(LESSONS, current, CHECKS)
        self.assertTrue(any("L25: deleted" in p for p in problems), problems)

    def test_a_superseded_lesson_may_be_weakened(self):
        current = self.current()
        l1 = next(l for l in current["lessons"] if l["id"] == "L1")
        l1.update(scope={"render": ["2d"]}, lifecycle="deprecated", superseded_by="L26")
        self.assertEqual(model.weakening_problems(LESSONS, current, CHECKS), [])

    def test_a_1x_previous_version_is_not_compared(self):
        previous = dict(self.current(), version="1.0.0")
        current = self.current()
        current["lessons"] = current["lessons"][:3]
        self.assertEqual(model.weakening_problems(previous, current, CHECKS), [])


class Integrity(unittest.TestCase):
    def module(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "check_integrity_knowledge", os.path.join(SCRIPTS, "check-integrity.py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_check_integrity_holds_the_knowledge_model(self):
        module = self.module()
        cwd, base = os.getcwd(), os.environ.get("WGF_KNOWLEDGE_BASE")
        os.chdir(ROOT)
        os.environ["WGF_KNOWLEDGE_BASE"] = "refs/heads/no-such-branch-for-k1"
        try:
            module.ERRORS.clear()
            module.NOTES.clear()
            module.check_regression_registry()
        finally:
            os.chdir(cwd)
            if base is None:
                del os.environ["WGF_KNOWLEDGE_BASE"]
            else:
                os.environ["WGF_KNOWLEDGE_BASE"] = base
        self.assertEqual(module.ERRORS, [])
        self.assertTrue(any("not compared with a previous version" in n
                            for n in module.NOTES))

    def test_the_runtime_mode_skips_test_existence_only(self):
        lessons = copy.deepcopy(LESSONS)
        lesson = next(l for l in lessons["lessons"] if l["id"] == "L25")
        lesson["tests"]["catches"] = ["scripts/tests/test_not_shipped.py::test_x"]
        full = registry.lesson_problems(lessons, CHECKS, ROOT, DATA["evidence"])
        runtime = registry.lesson_problems(lessons, CHECKS, ROOT, DATA["evidence"],
                                           runtime=True)
        self.assertTrue(any("test_not_shipped.py does not exist" in p for p in full))
        self.assertEqual(runtime, [])
        lesson["scope"] = {"render": ["5d"]}
        self.assertTrue(registry.lesson_problems(lessons, CHECKS, ROOT, DATA["evidence"],
                                                 runtime=True))


if __name__ == "__main__":
    unittest.main()

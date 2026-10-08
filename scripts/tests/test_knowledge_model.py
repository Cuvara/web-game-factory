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

    def test_a_window_has_an_upper_bound(self):
        data = self.lessons()
        data["exceptions"]["max_days"] = model.MAX_EXCEPTION_DAYS + 1
        self.write("core/reference/lessons.yaml", data)
        self.has(f"max_days {model.MAX_EXCEPTION_DAYS + 1} is over "
                 f"{model.MAX_EXCEPTION_DAYS}")
        data["exceptions"]["max_days"] = model.MAX_EXCEPTION_DAYS
        self.write("core/reference/lessons.yaml", data)
        self.assertEqual(self.problems(), [])


VOCABULARY = model.vocabulary(ROOT)
RUN = {"platforms": ["y8", "yandex"]}


class Exceptions(unittest.TestCase):
    def setUp(self):
        self.schema = _exception_schema()

    def problems(self, record, lessons=LESSONS, now=NOW, run_facets=RUN,
                 vocabulary=VOCABULARY):
        return model.exception_problems(record, lessons, CHECKS, now, run_facets=run_facets,
                                        vocabulary=vocabulary)

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

    def test_a_padded_reason_is_refused(self):
        # 23 letters pass the schema's length floor; the model reads what they say
        self.assertEqual(self.schema.iter_errors(exception(reason="a" * 23)), [])
        for padded, why in (("a" * 23, "at least 4 distinct words"),
                            ("accepted accepted accepted accepted ok", "4 distinct words"),
                            ("fine fine fine fine fine fine for this launch now",
                             "repeats one word"),
                            ("12345678901234567890 ok ok", "4 distinct words")):
            with self.subTest(reason=padded):
                self.assertTrue(any(why in p for p in self.problems(exception(reason=padded))),
                                self.problems(exception(reason=padded)))

    def test_an_expired_exception_is_refused(self):
        record = exception()
        later = datetime.datetime(2026, 10, 21, tzinfo=datetime.timezone.utc)
        self.assertEqual(self.schema.iter_errors(record), [])   # the schema cannot know
        self.assertIn("expired at 2026-10-20T09:00:00Z", self.problems(record, now=later))
        self.assertFalse(model.exception_active(record, later))

    def test_an_exception_read_without_a_time_does_not_hold(self):
        problems = self.problems(exception(), now=None)
        self.assertTrue(any("no time was given, so it does not hold" in p for p in problems))
        self.assertFalse(model.exception_active(exception(), None))

    def test_an_exception_created_in_the_future_is_refused(self):
        record = exception(created_at="2026-10-09T09:00:00Z")
        self.assertTrue(any("created in the future" in p for p in self.problems(record)))
        self.assertFalse(model.exception_active(record, NOW))

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

    def test_the_record_alone_is_not_trusted_about_its_approver(self):
        # A record that calls a bot a person passes the shape and the policy: what makes it
        # a person's is the operator act that stamps `mode` itself (K2), which the model's
        # contract states - so the docstring says so, and this test pins that it does.
        record = exception(approved_by={"identifier": "bot", "mode": "human"})
        self.assertEqual(self.problems(record), [])
        self.assertIn("never trusted on its own", model.exception_problems.__doc__)

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

    def test_a_scope_platform_outside_the_run_or_the_factory_is_refused(self):
        record = exception(scope={"platforms": ["crazygames"]})
        self.assertTrue(any("crazygames are not targeted by this run" in p
                            for p in self.problems(record)))
        record = exception(scope={"platforms": ["nowhere"]})
        self.assertTrue(any("nowhere are not platforms" in p for p in self.problems(record)))
        # undetermined run platforms: the vocabulary still holds it
        self.assertEqual(self.problems(exception(), run_facets={}), [])
        # without the vocabulary nothing can be checked: refused
        self.assertTrue(any("cannot be checked" in p
                            for p in self.problems(exception(), vocabulary=None)))

    def test_a_scope_platform_outside_the_rules_scope_is_refused(self):
        lessons = copy.deepcopy(LESSONS)
        next(l for l in lessons["lessons"] if l["id"] == "L26")["scope"] = {
            "platforms": ["yandex"]}
        self.assertTrue(any("y8 are outside rule L26's scope" in p
                            for p in self.problems(exception(), lessons)))

    def test_a_scope_viewport_must_be_one_a_gate_plays(self):
        self.assertEqual(self.problems(exception(scope={"viewports": ["tablet", "mobile"]})),
                         [])
        self.assertTrue(any("phablet are not viewports" in p for p in self.problems(
            exception(scope={"viewports": ["phablet"]}))))
        self.assertTrue(any("scope.viewports cannot be checked" in p for p in self.problems(
            exception(scope={"viewports": ["tablet"]}), vocabulary=None)))

    def test_the_schemas_reason_floor_is_the_models(self):
        self.assertEqual(self.schema.schema["properties"]["reason"]["minLength"],
                         model.REASON_MIN_LENGTH)


# ---------------------------------------------------------------------------- versions


class Versions(unittest.TestCase):
    def test_the_knowledge_versions_a_run_records(self):
        self.assertEqual(versions.knowledge(root=ROOT),
                         {"lessons": "lessons@2.0.0", "check-tiers": "check-tiers@1.2.0"})

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
        self.assertEqual(found["check_tiers"]["version"], "1.2.0")
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


def _classify(tiers):
    checks, _ = registry.classify(tiers, ROOT)
    return checks


def _lesson(data, lesson_id):
    return next(l for l in data["lessons"] if l["id"] == lesson_id)


class Weakening(unittest.TestCase):
    def current(self):
        return copy.deepcopy(LESSONS)

    def weak(self, previous, current, previous_checks=CHECKS, current_checks=None):
        return model.weakening_problems(previous, current, previous_checks, current_checks)

    def has(self, problems, text):
        self.assertTrue(any(text in p for p in problems), problems)

    def test_an_unchanged_file_has_no_problem(self):
        self.assertEqual(self.weak(LESSONS, self.current()), [])

    def test_a_weakened_level_without_supersession_fails_integrity(self):
        previous = self.current()
        _lesson(previous, "L23")["level"] = "blocking"
        self.has(self.weak(previous, self.current()),
                 "L23: weakened in place - held blocking in a run before, required now")

    def test_a_blocking_lesson_turned_process_fails(self):
        current = self.current()
        _lesson(current, "L5").update(status="process", category="process",
                                      held_by="a note")
        self.has(self.weak(LESSONS, current), "L5: weakened in place - held blocking in a "
                                              "run before, in no run now")

    def test_a_lesson_sent_back_to_candidate_fails(self):
        current = self.current()
        _lesson(current, "L25")["lifecycle"] = "candidate"
        self.has(self.weak(LESSONS, current),
                 "L25: weakened in place - held required in a run before, experimental now")

    def test_a_check_removed_from_a_rule_fails_even_at_the_same_level(self):
        current = self.current()
        l27 = _lesson(current, "L27")
        l27["checks"] = [c for c in l27["checks"] if c != "browser-qa:browser.audio-mute"]
        self.assertEqual(model.level_of(l27, CHECKS), "required")
        self.has(self.weak(LESSONS, current),
                 "L27: no longer held by browser-qa:browser.audio-mute")

    def test_a_demoted_check_tier_is_judged_by_each_sides_own_tiers(self):
        tiers = copy.deepcopy(DATA["tiers"])
        tiers["overrides"] = {"production-quality:assets.runtime": "quality"}
        demoted = _classify(tiers)
        problems = self.weak(LESSONS, self.current(), CHECKS, demoted)
        self.has(problems, "L3: production-quality:assets.runtime was demoted from hard to "
                           "quality")
        self.has(problems, "L3: weakened in place - held blocking in a run before, required")
        # judged with one side's tiers only, the demotion would be invisible
        self.assertEqual(self.weak(LESSONS, self.current(), demoted, demoted), [])

    def test_a_promoted_check_tier_is_no_problem(self):
        tiers = copy.deepcopy(DATA["tiers"])
        tiers["overrides"] = {"play-realism:naive.clear_rate": "hard"}
        self.assertEqual(self.weak(LESSONS, self.current(), CHECKS, _classify(tiers)), [])

    def test_a_narrowed_scope_fails(self):
        current = self.current()
        _lesson(current, "L1")["scope"] = {"render": ["2d"]}
        self.has(self.weak(LESSONS, current), "L1: scope narrowed in place")

    def test_a_widened_scope_and_a_stronger_level_pass(self):
        current = self.current()
        _lesson(current, "L15")["scope"] = "global"
        _lesson(current, "L23")["level"] = "blocking"
        self.assertEqual(self.weak(LESSONS, current), [])

    def test_a_deleted_lesson_fails(self):
        current = self.current()
        current["lessons"] = [l for l in current["lessons"] if l["id"] != "L25"]
        self.has(self.weak(LESSONS, current), "L25: deleted")

    def successor(self, current, of, **changes):
        old = _lesson(current, of)
        new = dict(copy.deepcopy(old), id="L29", **changes)
        old.update(lifecycle="deprecated", superseded_by="L29")
        current["lessons"].append(new)
        return new

    def test_a_successor_as_strong_and_as_wide_may_replace_a_lesson(self):
        current = self.current()
        self.successor(current, "L1", title="L1 restated")
        self.assertEqual(self.weak(LESSONS, current), [])

    def test_a_weaker_or_narrower_successor_fails(self):
        current = self.current()
        self.successor(current, "L5", checks=["playability:depth.ramp"])
        problems = self.weak(LESSONS, current)
        self.has(problems, "L5: weakened in place - held blocking in a run before, required "
                           "now (through its successor L29)")
        self.has(problems, "L5: no longer held by playability:content.units_reachable "
                           "(through its successor L29)")
        current = self.current()
        self.successor(current, "L1", scope={"render": ["2d"]})
        self.has(self.weak(LESSONS, current), "L1: scope narrowed in place (through its "
                                              "successor L29)")

    def test_a_lesson_retired_with_a_reason_stays_advisory_and_visible(self):
        current = self.current()
        _lesson(current, "L25").update(lifecycle="deprecated", reason="replaced by a portal "
                                       "rule that every target now enforces")
        self.assertEqual(model.run_level(_lesson(current, "L25"), CHECKS), "recommended")
        # a weakening, held where it is visible: advisory in every run, never silent
        self.has(self.weak(LESSONS, current),
                 "L25: weakened in place - held required in a run before, recommended now")

    def test_the_exception_policy_is_never_loosened_in_place(self):
        for change, text in ((lambda p: p["approvers"]["required"].append("automation"),
                              "approvers.required gained automation"),
                             (lambda p: p.update(max_days=60), "max_days widened in place "
                                                               "(30 -> 60)")):
            current = self.current()
            change(current["exceptions"])
            with self.subTest(text):
                self.has(self.weak(LESSONS, current), text)
        previous = self.current()
        previous["exceptions"]["levels"] = ["blocking"]
        self.has(self.weak(previous, self.current()), "required rules became exceptable")
        tighter = self.current()
        tighter["exceptions"]["max_days"] = 14
        self.assertEqual(self.weak(LESSONS, tighter), [])

    def test_against_a_1x_file_only_deletions_count(self):
        previous = dict(self.current(), version="1.0.0")
        for lesson in previous["lessons"]:
            lesson.pop("scope", None)
        current = self.current()
        _lesson(current, "L15")["scope"] = {"render": ["3d"]}
        self.assertEqual(self.weak(previous, current), [])
        current["lessons"] = current["lessons"][:3]
        self.has(self.weak(previous, current), "L4: deleted")


class Integrity(unittest.TestCase):
    def module(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "check_integrity_knowledge", os.path.join(SCRIPTS, "check-integrity.py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def run_check(self, base, strict):
        module = self.module()
        saved = {k: os.environ.get(k) for k in ("WGF_KNOWLEDGE_BASE", "WGF_KNOWLEDGE_STRICT")}
        cwd = os.getcwd()
        os.chdir(ROOT)
        os.environ["WGF_KNOWLEDGE_BASE"] = base
        os.environ["WGF_KNOWLEDGE_STRICT"] = "1" if strict else "0"
        try:
            module.ERRORS.clear()
            module.NOTES.clear()
            module.check_regression_registry()
        finally:
            os.chdir(cwd)
            for key, value in saved.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
        return module

    def test_a_missing_base_is_a_note_locally_and_an_error_in_ci(self):
        local = self.run_check("refs/heads/no-such-branch-for-k1", strict=False)
        self.assertEqual(local.ERRORS, [])
        self.assertTrue(any("no base to compare the knowledge with" in n
                            for n in local.NOTES), local.NOTES)
        ci = self.run_check("refs/heads/no-such-branch-for-k1", strict=True)
        self.assertTrue(any("no base to compare the knowledge with" in e for e in ci.ERRORS),
                        ci.ERRORS)

    def test_a_base_that_is_head_compares_with_its_parent(self):
        module = self.module()
        cwd = os.getcwd()
        os.chdir(ROOT)
        try:
            head = module._commit("HEAD")
            parent = module._commit("HEAD^")
            base, why = module.knowledge_base("HEAD")
        finally:
            os.chdir(cwd)
        if head is None or parent is None:
            self.skipTest("not a git checkout with history")
        self.assertNotEqual(base, head)
        self.assertEqual(base, parent)

    def test_the_comparison_runs_against_a_real_base(self):
        module = self.run_check("HEAD", strict=True)
        if any("no base" in e or "HEAD has no parent" in e for e in module.ERRORS):
            self.skipTest("not a git checkout with history")
        self.assertEqual(module.ERRORS, [])
        self.assertTrue(any(n.startswith("lessons: compared with") or "introduced" in n
                            for n in module.NOTES), module.NOTES)

    def test_the_previous_knowledge_is_read_with_its_own_tiers(self):
        module = self.module()
        cwd = os.getcwd()
        os.chdir(ROOT)
        try:
            head = module._commit("HEAD")
            if head is None:
                self.skipTest("not a git checkout")
            lessons, checks = module.previous_knowledge(head)
        finally:
            os.chdir(cwd)
        self.assertIsNotNone(lessons)
        self.assertGreater(len(checks), 100)

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

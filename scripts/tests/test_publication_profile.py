"""Publication profile 2.0.0 and 2.1.0: the schema, the flow rules, and their check in check-integrity.

core/artifacts/shared/publication-profile.schema.json says what an intent, a locator ladder, a
content policy and the adaptive bounds look like; wgflib.publication.flow_problems says what a
schema cannot (no cancel, withdraw or delete intent; every irreversible intent has a profile
ladder; every intent has a class; adaptive names outside the deny vocabulary; status words
consistent), and scripts/check-integrity.py runs it over core's profiles. The platform-
publication schema 1.2.0 additions are checked here too. No portal is contacted.

    python -m unittest scripts/tests/test_publication_profile.py
"""

import copy
import glob
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
sys.path.insert(0, SCRIPTS)

from wgflib import jsonschema_lite as js  # noqa: E402
from wgflib import publication as pub  # noqa: E402
from wgflib.yamllite import load_file  # noqa: E402

ARTIFACTS = os.path.join(ROOT, "core", "artifacts")
SHARED = os.path.join(ARTIFACTS, "shared")
CORE_PROFILES = sorted(glob.glob(os.path.join(ROOT, "core", "reference", "publication", "*.yaml")))
FIXTURE = os.path.join(HERE, "fixtures", "publish", "publication", "generic-web.yaml")
CONSOLES = ("crazygames", "y8", "yandex", "gamedistribution", "gamemonetize")


def read_json(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def registry():
    reg = js.Registry()
    for path in glob.glob(os.path.join(SHARED, "*.schema.json")) + \
            glob.glob(os.path.join(ARTIFACTS, "*.schema.json")):
        reg.add(read_json(path))
    return reg


REGISTRY = registry()
PROFILE_SCHEMA = read_json(os.path.join(SHARED, "publication-profile.schema.json"))
PUBLICATION_SCHEMA = read_json(os.path.join(ARTIFACTS, "platform-publication.schema.json"))


def errors(instance, schema=PROFILE_SCHEMA):
    return list(js.Validator(schema, REGISTRY).iter_errors(instance))


def fixture():
    return load_file(FIXTURE)


def intent(profile, iid):
    return next(i for i in profile["submission"]["flow"] if i["id"] == iid)


class ShippedProfilesTest(unittest.TestCase):
    def test_every_profile_and_the_fixture_validate_and_break_no_flow_rule(self):
        for path in CORE_PROFILES + [FIXTURE]:
            profile = load_file(path)
            with self.subTest(path=os.path.relpath(path, ROOT)):
                self.assertEqual(errors(profile), [])
                self.assertEqual(pub.flow_problems(profile), [])

    def test_the_schema_is_2_1_0(self):
        self.assertEqual(PROFILE_SCHEMA["x-wgf"]["version"], "2.1.0")

    def test_every_console_is_reached_through_a_person_s_live_login(self):
        for path in CORE_PROFILES + [FIXTURE]:
            profile = load_file(path)
            submission = profile["submission"]
            if submission["method"] != "console":
                continue
            with self.subTest(path=os.path.basename(path)):
                self.assertEqual(submission["credential"], {"kind": "human-login"})

    def test_every_profile_is_on_the_2_0_0_form(self):
        for path in CORE_PROFILES + [FIXTURE]:
            profile = load_file(path)
            with self.subTest(path=os.path.basename(path)):
                self.assertEqual(profile["version"].split(".")[0], "2")
                self.assertNotIn("verification", profile["submission"])
                self.assertNotIn("upload_max_mb", profile["submission"].get("console") or {})

    def test_shipped_consoles_stay_unverified_with_their_unknowns_named(self):
        for pid in CONSOLES:
            profile = pub.load_publication_profile(pid)
            with self.subTest(pid=pid):
                self.assertEqual(profile["status"], "unverified")
                self.assertEqual(profile["submission"]["automation_terms"], "unverified")
                self.assertTrue(profile.get("unknowns"), "a console profile names its unknowns")
                policy = profile["submission"]["content_policy"]
                self.assertEqual(policy["ai_generated_text"], "unknown")
                self.assertEqual(policy["ai_generated_assets"], "unknown")
                self.assertTrue(profile["submission"]["status"].get("pending_states"))

    def test_no_shipped_locator_is_observed_on_a_live_console(self):
        # Nobody has logged into a portal for these files: a locator is documented or a
        # hypothesis, never `observed`, until a person runs the flow (workstream 10).
        for pid in CONSOLES:
            submission = pub.load_publication_profile(pid)["submission"]
            for step in submission.get("flow") or []:
                self.assertNotEqual(step.get("basis"), "observed", f"{pid}: {step['id']}")
            self.assertNotEqual((submission.get("identity") or {}).get("basis"), "observed", pid)

    def test_yandex_maps_verified_as_approved_not_live(self):
        status = pub.load_publication_profile("yandex")["submission"]["status"]
        self.assertEqual(status["approved_states"], ["Verified"])
        self.assertNotIn("Verified", status["live_states"] + status["submitted_states"])
        self.assertEqual(status["pending_states"], ["Waiting for moderation"])

    def test_every_declaration_is_a_human_intent(self):
        for path in CORE_PROFILES + [FIXTURE]:
            for step in load_file(path)["submission"].get("flow") or []:
                if step["id"].startswith("declare."):
                    self.assertEqual(step["class"], "human", f"{path}: {step['id']}")


class ProfileSchemaTest(unittest.TestCase):
    def refused(self, profile):
        self.assertNotEqual(errors(profile), [], "the schema accepted it")

    def test_an_intent_without_a_class_is_refused(self):
        profile = fixture()
        del intent(profile, "field.title")["class"]
        self.refused(profile)

    def test_a_human_intent_never_carries_an_action_a_value_or_names(self):
        for extra in ({"action": "click", "target": [{"css": "#x"}]}, {"value": "listing.title"},
                      {"names": ["Rating"]}):
            profile = fixture()
            intent(profile, "declare.age_rating").update(extra)
            with self.subTest(extra=extra):
                self.refused(profile)

    def test_a_human_intent_says_what_the_person_does(self):
        profile = fixture()
        del intent(profile, "declare.age_rating")["note"]
        self.refused(profile)

    def test_an_irreversible_intent_needs_a_profile_ladder_and_no_adaptive_names(self):
        profile = fixture()
        del intent(profile, "review.request")["target"]
        self.refused(profile)
        profile = fixture()
        intent(profile, "review.request")["target"] = []
        self.refused(profile)
        profile = fixture()
        intent(profile, "review.request")["names"] = ["Submit for moderation"]
        self.refused(profile)

    def test_a_value_is_a_path_never_free_text(self):
        profile = fixture()
        intent(profile, "field.title")["value"] = "My great game"
        self.refused(profile)
        profile = fixture()
        del intent(profile, "field.title")["value"]
        self.refused(profile)
        profile = fixture()
        intent(profile, "draft.save")["value"] = "listing.title"  # a click carries no value
        self.refused(profile)

    def test_there_is_no_tick_action(self):
        profile = fixture()
        intent(profile, "draft.save")["action"] = "check"
        self.refused(profile)

    def test_a_locator_rung_is_one_kind_and_xpath_needs_a_reason(self):
        for rung in ({"role": "button", "css": "#save"}, {"name": "Save"}, {"xpath": "//button"},
                     {"x": 10, "y": 20}, {}):
            profile = fixture()
            intent(profile, "draft.save")["target"] = [rung]
            with self.subTest(rung=rung):
                self.refused(profile)
        profile = fixture()
        intent(profile, "draft.save")["target"] = [{"xpath": "//button[1]", "reason": "no label"}]
        self.assertEqual(errors(profile), [])

    def test_adaptive_bounds_go_down_never_up(self):
        for bounds in ({"max_per_intent": 4}, {"max_per_visit": 11}):
            profile = fixture()
            profile["submission"]["adaptive_bounds"] = bounds
            with self.subTest(bounds=bounds):
                self.refused(profile)
        profile = fixture()
        profile["submission"]["adaptive_bounds"] = {"max_per_intent": 0, "max_per_visit": 2}
        self.assertEqual(errors(profile), [])

    def test_a_console_profile_states_adaptive_status_and_content_policy(self):
        for key in ("adaptive", "status", "content_policy", "credential"):
            profile = fixture()
            del profile["submission"][key]
            with self.subTest(key=key):
                self.refused(profile)
        profile = fixture()
        profile["submission"]["content_policy"]["ai_generated_text"] = "maybe"
        self.refused(profile)
        profile = fixture()
        profile["submission"]["adaptive"] = "sometimes"
        self.refused(profile)

    def test_the_1_x_keys_are_refused(self):
        profile = fixture()
        profile["submission"]["verification"] = profile["submission"]["status"]
        self.refused(profile)
        profile = fixture()
        profile["submission"]["console"]["upload_max_mb"] = 50
        self.refused(profile)

    def test_a_manual_profile_needs_no_console_block(self):
        self.assertEqual(errors(pub.load_publication_profile("gamevui")), [])
        profile = pub.load_publication_profile("gamevui")
        del profile["submission"]["content_policy"]
        self.refused(profile)

    def test_fields_and_identity(self):
        profile = fixture()
        profile["submission"]["fields"]["Title"] = {"max": 5}
        self.refused(profile)
        profile = fixture()
        profile["submission"]["fields"]["title"]["max"] = "fifty"
        self.refused(profile)
        profile = fixture()
        profile["submission"]["identity"]["portal_id_from"] = ["guess"]
        self.refused(profile)
        profile = fixture()
        profile["submission"]["identity"]["title_match"] = "fuzzy"
        self.refused(profile)


class LoginAndIdentityTest(unittest.TestCase):
    """2.1.0: a person's live login replaces the captured session; the ids a portal issues on
    create, the authenticated url and the console's error marker are data."""

    def test_human_login_takes_no_variable_and_storage_state_is_refused(self):
        profile = fixture()
        self.assertEqual(errors(profile), [])
        profile["submission"]["credential"] = {"kind": "human-login", "env": "WGF_X"}
        self.assertNotEqual(errors(profile), [])
        profile["submission"]["credential"] = {"kind": "token"}
        self.assertNotEqual(errors(profile), [], "a token is named by its variable")
        profile["submission"]["credential"] = {"kind": "storage-state", "env": "WGF_X"}
        self.assertEqual(errors(profile), [], "deprecated, not removed: an old file still parses")
        self.assertTrue(any("storage-state is deprecated" in p for p in pub.flow_problems(profile)))
        profile["submission"]["credential"] = {"kind": "token", "env": "WGF_X"}
        self.assertTrue(any("person's live login" in p for p in pub.flow_problems(profile)))
        self.assertEqual(pub.human_reason(profile | {"submission": dict(
            profile["submission"], credential={"kind": "storage-state", "env": "WGF_X"})}, {}, True)[0],
            "credential-missing")
        self.assertIsNone(pub.human_reason(fixture(), {}, None))

    def test_issued_on_create_page_id_error_and_authenticated_url(self):
        profile = fixture()
        identity = profile["submission"]["identity"]
        identity["issued_on_create"] = [{"key": "external_game_id", "read": [{"label": "Game ID"}]},
                                        {"key": "app_id", "read": [{"label": "App ID"}], "attr": "value"}]
        self.assertEqual(errors(profile), [])
        self.assertEqual(pub.flow_problems(profile), [])
        identity["issued_on_create"].append({"key": "app_id", "read": [{"label": "App"}]})
        self.assertTrue(any("names app_id twice" in p for p in pub.flow_problems(profile)))
        identity["issued_on_create"] = [{"key": "slug", "read": [{"css": "#x"}]}]
        self.assertNotEqual(errors(profile), [])
        profile = fixture()
        profile["submission"]["session"]["authenticated_url"] = "(unclosed"
        self.assertTrue(any("not a regular expression" in p for p in pub.flow_problems(profile)))
        profile = fixture()
        intent(profile, "field.title")["multiple"] = True
        self.assertTrue(any("`multiple` is for an upload" in p for p in pub.flow_problems(profile)))

    def test_y8_says_where_the_ids_issued_on_create_are_read(self):
        profile = pub.load_publication_profile("y8")
        keys = [e["key"] for e in profile["submission"]["identity"]["issued_on_create"]]
        self.assertEqual(keys, ["external_game_id", "app_id"])


class FlowRulesTest(unittest.TestCase):
    def problems(self, profile):
        return pub.flow_problems(profile)

    def assertProblem(self, profile, fragment):
        found = self.problems(profile)
        self.assertTrue(any(fragment in p for p in found), f"{fragment!r} not in {found}")

    def add(self, profile, step):
        profile["submission"]["flow"].append(step)
        return profile

    def test_no_cancel_withdraw_or_delete_intent_may_exist(self):
        cases = [
            {"id": "review.cancel", "phase": "save_draft", "class": "reversible",
             "action": "click", "target": [{"css": "#x"}]},
            {"id": "draft.tidy", "phase": "save_draft", "class": "reversible", "action": "click",
             "target": [{"role": "button", "name": "Withdraw from review"}]},
            {"id": "draft.tidy", "phase": "save_draft", "class": "reversible", "action": "click",
             "target": [{"css": "button[data-action=delete-game]"}]},
            {"id": "build.replace", "phase": "upload_build", "class": "reversible",
             "action": "click", "target": [{"text": "Remove build"}]},
            {"id": "game.unpublish", "phase": "verify", "class": "human", "note": "x"},
        ]
        for case in cases:
            with self.subTest(case=case["id"]):
                self.assertProblem(self.add(fixture(), case), "never cancels")

    def test_every_intent_has_a_class(self):
        profile = fixture()
        del intent(profile, "field.title")["class"]
        self.assertProblem(profile, "no class")
        profile = fixture()
        intent(profile, "field.title")["class"] = "maybe"
        self.assertProblem(profile, "no class")

    def test_an_irreversible_intent_has_a_profile_ladder(self):
        profile = fixture()
        del intent(profile, "review.request")["target"]
        self.assertProblem(profile, "without a profile locator ladder")
        profile = fixture()
        intent(profile, "review.request")["target"] = [{}]
        self.assertProblem(profile, "without a profile locator ladder")
        profile = fixture()
        intent(profile, "review.request")["names"] = ["Send"]
        self.assertProblem(profile, "carry no adaptive `names`")

    def test_a_review_request_is_irreversible(self):
        profile = fixture()
        intent(profile, "review.request")["class"] = "reversible"
        self.assertProblem(profile, "request_review intent is irreversible")

    def test_adaptive_names_and_overlays_stay_outside_the_deny_vocabulary(self):
        profile = fixture()
        intent(profile, "draft.save")["names"] = ["Save", "Publish now"]
        self.assertProblem(profile, "deny vocabulary ('publish')")
        profile = fixture()
        intent(profile, "draft.save")["names"] = ["Save", "Payout settings"]
        self.assertProblem(profile, "deny vocabulary ('pay')")
        profile = fixture()  # the profile's own translations count too
        intent(profile, "draft.save")["names"] = ["Soumettre le jeu"]
        self.assertProblem(profile, "deny vocabulary ('Soumettre')")
        profile = fixture()
        profile["submission"]["dismissable"].append("I agree")
        self.assertProblem(profile, "dismissable 'I agree'")

    def test_deny_matches_a_word_start_case_folded(self):
        deny = pub.deny_vocabulary(fixture())
        self.assertEqual(pub._vocabulary_hit("PUBLISHING", deny), "publish")
        self.assertEqual(pub._vocabulary_hit("I own the rights", deny), "i own")
        self.assertIsNone(pub._vocabulary_hit("Description", deny))  # "script" is no word start
        self.assertIsNone(pub._vocabulary_hit("Unsigned", deny))

    def test_status_words_are_consistent(self):
        profile = fixture()
        profile["submission"]["status"]["pending_states"] = ["Queued"]
        self.assertProblem(profile, "'Queued' is not one of status.states")
        profile = fixture()
        profile["submission"]["status"]["pending_states"] = []
        self.assertProblem(profile, "pending_states is empty")
        profile = fixture()
        del profile["submission"]["status"]["live_states"]
        intent(profile, "status.read")["expect"] = {"status_in": "live_states"}
        self.assertProblem(profile, "expect.status_in live_states")

    def test_an_intent_id_is_unique(self):
        profile = fixture()
        profile["submission"]["flow"].append(copy.deepcopy(intent(profile, "draft.save")))
        self.assertProblem(profile, "appears twice")

    def test_a_prerequisite_is_a_persons_act_that_readiness_waits_for(self):
        profile = pub.load_publication_profile("gamedistribution")
        prerequisite = next(p for p in profile["prerequisites"] if p["id"] == "self-hosting")
        self.assertEqual((prerequisite["reason"], prerequisite["when"]),
                         ("legal", {"hosting": "self-hosted"}))
        terms = {"terms_confirmed": True}
        self_hosted = {"id": "gamedistribution", "hosting": "self-hosted",
                       "game_url": "https://games.example.com/x/"}
        hosted = {"id": "gamedistribution"}  # the default hosting is never written
        account = ["developer-account", "developer-terms"]
        terms = {"terms_confirmed": True, "prerequisites_confirmed": account}
        reason = pub.human_reason(profile, terms, True, self_hosted)
        self.assertEqual(reason[0], "legal")
        self.assertIn("prerequisite self-hosting", reason[1])
        # Unknown entry: every prerequisite applies; an unknown is never read as satisfied.
        self.assertEqual(pub.human_reason(profile, terms, True)[0], "legal")
        self.assertEqual(pub.unmet_prerequisites(profile, terms, hosted), [])
        # The account and its terms apply to every release.
        self.assertEqual([p["id"] for p in pub.unmet_prerequisites(profile, {}, hosted)], account)
        self.assertEqual(pub.unmet_prerequisites(
            profile, {"prerequisites_confirmed": account + ["self-hosting"]}, self_hosted), [])
        self.assertIsNone(pub.human_reason(
            profile, {"terms_confirmed": True,
                      "prerequisites_confirmed": account + ["self-hosting"]},
            True, self_hosted))
        self.assertEqual(pub.readiness({}, pub.human_reason(profile, terms, True, self_hosted)),
                         pub.HUMAN_REQUIRED)

    def test_a_prerequisite_is_validated(self):
        profile = pub.load_publication_profile("gamedistribution")
        self.assertEqual(errors(profile), [])
        for broken in ({"id": "x", "reason": "terms-unconfirmed", "note": "n", "source": "s"},
                       {"id": "x", "reason": "legal", "note": "n"},
                       {"id": "x", "reason": "legal", "note": "n", "source": "s",
                        "when": {"engine": "pixijs"}}):
            candidate = copy.deepcopy(profile)
            candidate["prerequisites"] = [broken]
            with self.subTest(broken=broken):
                self.assertNotEqual(errors(candidate), [])

    def test_gamepix_is_described_and_discloses_generated_content(self):
        profile = pub.load_publication_profile("gamepix")
        self.assertEqual(errors(profile), [])
        self.assertEqual(profile["status"], "unverified")
        self.assertEqual(profile["submission"]["automation_terms"], "unverified")
        policy = profile["submission"]["content_policy"]
        self.assertEqual((policy["ai_generated_text"], policy["ai_generated_assets"]),
                         ("disclose", "disclose"))
        flow = profile["submission"]["flow"]
        # The dashboard's submit control is not public: no intent requests review, and every
        # automated intent is a hypothesis (unknowns).
        self.assertFalse([i for i in flow if i["phase"] == "request_review"])
        self.assertTrue(all(i.get("basis") == "hypothesis" for i in flow if i["class"] != "human"))
        self.assertTrue({"declare.distribution", "declare.child-directed", "declare.ai"}
                        <= {i["id"] for i in flow if i["class"] == "human"})
        self.assertTrue(profile["unknowns"])

    def test_a_flow_of_human_intents_only_needs_no_pending_states(self):
        profile = pub.load_publication_profile("gamedistribution")
        profile["submission"]["status"]["pending_states"] = []
        self.assertEqual(self.problems(profile), [])


def load_check_integrity():
    spec = importlib.util.spec_from_file_location(
        "check_integrity_publication", os.path.join(SCRIPTS, "check-integrity.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class IntegrityCheckTest(unittest.TestCase):
    def setUp(self):
        self.ci = load_check_integrity()
        self.ci.ERRORS.clear()
        self.base = tempfile.mkdtemp(prefix="wgf-publication-")
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)
        self.profiles = os.path.join(self.base, "publication")
        self.platforms = os.path.join(self.base, "platforms")
        os.makedirs(self.profiles)
        os.makedirs(self.platforms)
        with open(os.path.join(self.platforms, "generic-web.yaml"), "w", encoding="utf-8") as fh:
            fh.write("id: generic-web\n")

    def run_check(self, text, name="generic-web.yaml"):
        with open(os.path.join(self.profiles, name), "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        return self.ci.check_publication_profiles(self.profiles, self.platforms)

    def fixture_text(self):
        with open(FIXTURE, encoding="utf-8") as fh:
            return fh.read()

    def test_the_fixture_passes(self):
        self.assertEqual(self.run_check(self.fixture_text()), ["generic-web"])
        self.assertEqual(self.ci.ERRORS, [])

    def test_a_cancel_intent_fails_the_check(self):
        text = self.fixture_text().replace(
            "    - id: review.request\n",
            "    - id: review.cancel\n      phase: save_draft\n      class: reversible\n"
            "      action: click\n      target: [{css: \"#cancel\"}]\n"
            "    - id: review.request\n", 1)
        self.run_check(text)
        self.assertTrue(any("review.cancel" in e and "never cancels" in e for e in self.ci.ERRORS),
                        self.ci.ERRORS)

    def test_an_intent_without_a_class_fails_the_check(self):
        text = self.fixture_text().replace(
            "    - id: draft.save\n      phase: save_draft\n      class: reversible\n",
            "    - id: draft.save\n      phase: save_draft\n", 1)
        self.run_check(text)
        self.assertTrue(any("draft.save: no class" in e for e in self.ci.ERRORS), self.ci.ERRORS)

    def test_the_id_is_the_stem_and_names_a_platform(self):
        self.run_check(self.fixture_text(), name="other.yaml")
        self.assertTrue(any("not the filename stem" in e for e in self.ci.ERRORS))
        self.ci.ERRORS.clear()
        self.run_check(self.fixture_text().replace("id: generic-web", "id: nowhere", 1),
                       name="nowhere.yaml")
        self.assertTrue(any("no platform profile" in e for e in self.ci.ERRORS), self.ci.ERRORS)

    def test_core_passes(self):
        cwd = os.getcwd()
        os.chdir(ROOT)
        try:
            checked = self.ci.check_publication_profiles()
        finally:
            os.chdir(cwd)
        self.assertEqual(self.ci.ERRORS, [])
        self.assertEqual(sorted(checked), sorted(os.path.basename(p)[:-5] for p in CORE_PROFILES))


class PlatformPublicationTest(unittest.TestCase):
    def record(self, **extra):
        body = {"provenance": {}, "release_id": "r1", "title_id": "t", "platform_id": "yandex",
                "profile_version": "1.2.0", "role": "required", "state": "validated"}
        body.update(extra)
        return body

    def schema_errors(self, record):
        # provenance is checked by its own tests; only the 1.2.0 surface is under test here
        found = errors(record, PUBLICATION_SCHEMA)
        return [e for e in found if not str(getattr(e, "pointer", "")).startswith("/provenance")]

    def test_the_contract_is_1_4_0(self):
        self.assertEqual(PUBLICATION_SCHEMA["x-wgf"]["version"], "1.4.0")

    def test_the_new_human_required_reasons(self):
        for reason in ("legal", "declaration", "ai-text-policy", "duplicate-candidate",
                       "review-pending", "drift-irreversible", "anti-bot"):
            with self.subTest(reason=reason):
                record = self.record(outcome="HUMAN_REQUIRED",
                                     human_required={"reason": reason, "detail": "x"})
                self.assertEqual(self.schema_errors(record), [])
        record = self.record(human_required={"reason": "cancel-review", "detail": "x"})
        self.assertNotEqual(self.schema_errors(record), [])

    def test_portal_game_id_and_the_adaptive_measurement_class(self):
        record = self.record(submission={"method": "console", "portal_game_id": "123456"},
                             measurement_class="automation-console-adaptive")
        self.assertEqual(self.schema_errors(record), [])


class ConsoleAdapterReadsTwoZeroTest(unittest.TestCase):
    def adapter(self, profile):
        from wgf_publish.adapters.console import ConsoleAdapter

        class NoFields(ConsoleAdapter):
            # prepare() also maps the listing onto the selector map (workstream 1); this test
            # is about the upload limit only, so the portal has no listing fields.
            def selectors(self):
                return {}
        return NoFields(profile["id"], profile)

    def test_status_words_come_from_status(self):
        from wgf_publish.adapters.console import ConsoleAdapter
        status = fixture()["submission"]["status"]
        self.assertEqual(ConsoleAdapter._classify("waiting for moderation", status), "submitted")
        self.assertEqual(ConsoleAdapter._classify("Live", status), "live")
        self.assertIsNone(ConsoleAdapter._classify("Processing", status))

    def test_the_upload_limit_comes_from_constraints(self):
        class Job:
            console_url = "http://127.0.0.1:1/"
            package_path = FIXTURE  # any file on disk
            package = {"filename": "p.zip", "size_mb": 60}
            idempotency_key = "wgf-generic-web-0"
            release_dir = os.path.dirname(FIXTURE)
            timeouts = {}
            metadata = {}
            listing = {}
            platform_profile = {}
        problems = self.adapter(fixture()).prepare(Job())
        self.assertTrue(any("exceeds the console's 50 MB upload limit" in p for p in problems),
                        problems)


if __name__ == "__main__":
    unittest.main()

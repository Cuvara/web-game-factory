"""core/reference/publishing-workflow.yaml: the schema, the referential rules, the key.

The publishing workflow is the platform-neutral stages a release goes through to reach a
portal, the states a publication is reported in and the publication key
(docs/publish-module.md, "The publishing workflow"). It is data check-integrity.py validates;
these tests hold what it must refuse. Per-portal status is not in it (one home: the readiness
matrix in docs/portal-publishing-architecture.md). No portal is contacted.

    python -m unittest discover -s scripts/tests -t scripts/tests -p test_publishing_workflow.py
"""

import copy
import glob
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
sys.path.insert(0, SCRIPTS)

from wgflib import jsonschema_lite as js  # noqa: E402
from wgflib import publication as pub  # noqa: E402

SHARED = os.path.join(ROOT, "core", "artifacts", "shared")
SCHEMA_PATH = os.path.join(SHARED, "publishing-workflow.schema.json")


def read_json(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def registry():
    reg = js.Registry()
    for path in glob.glob(os.path.join(SHARED, "*.schema.json")) + \
            glob.glob(os.path.join(ROOT, "core", "artifacts", "*.schema.json")):
        reg.add(read_json(path))
    return reg


def load_check_integrity():
    spec = importlib.util.spec_from_file_location(
        "check_integrity_publishing", os.path.join(SCRIPTS, "check-integrity.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_integrity_check(ci, path=None):
    ci.ERRORS.clear()
    cwd = os.getcwd()
    os.chdir(ROOT)
    try:
        return ci.check_publishing_workflow(path) if path else ci.check_publishing_workflow()
    finally:
        os.chdir(cwd)


class Shipped(unittest.TestCase):
    def setUp(self):
        self.doc = pub.load_publishing_workflow()

    def test_it_validates_against_its_schema(self):
        errors = list(js.Validator(read_json(SCHEMA_PATH), registry()).iter_errors(self.doc))
        self.assertEqual(errors, [])
        self.assertEqual(read_json(SCHEMA_PATH)["x-wgf"]["version"], "1.0.0")

    def test_check_integrity_finds_nothing_and_reports_the_version(self):
        ci = load_check_integrity()
        version = run_integrity_check(ci)
        self.assertEqual(ci.ERRORS, [])
        self.assertEqual(version, self.doc["version"])

    def test_check_integrity_refuses_a_refusal_code_the_publish_step_never_raises(self):
        ci = load_check_integrity()
        with open(pub.PUBLISHING_WORKFLOW, encoding="utf-8") as handle:
            text = handle.read()
        self.assertEqual(text.count("release-mismatch]"), 1)
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "publishing-workflow.yaml")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(text.replace("release-mismatch]", "release-mismatch, latest-build-wins]"))
            run_integrity_check(ci, path)
        self.assertTrue(any("'latest-build-wins' is not a refusal the publish step raises" in e
                            for e in ci.ERRORS), ci.ERRORS)

    def test_playwright_drives_the_portals_and_ci_never_publishes(self):
        self.assertEqual(self.doc["executor"]["portal"], "playwright")
        self.assertIs(self.doc["executor"]["ci_publishes"], False)

    def test_upload_submit_and_published_are_distinct_states(self):
        by_id = {s["id"]: s for s in self.doc["states"]}
        for state in ("WAITING_FOR_HUMAN_LOGIN", "DRY_RUN_PASS", "UPLOADED", "SUBMITTED",
                      "UNDER_REVIEW", "PUBLISHED", "RELEASE_ARTIFACT_MISMATCH", "BLOCKED"):
            self.assertIn(state, by_id)
        self.assertEqual(by_id["UPLOADED"]["outcome"], ["UPLOAD_COMPLETE"])
        self.assertEqual(by_id["SUBMITTED"]["outcome"], ["SUBMITTED"])
        self.assertEqual(by_id["PUBLISHED"]["registry"], "PUBLISHED")

    def test_every_irreversible_stage_is_a_person_s_or_behind_their_decision(self):
        for stage in self.doc["stages"]:
            if stage.get("irreversible"):
                with self.subTest(stage=stage["id"]):
                    self.assertTrue(stage["kind"] == "human" or stage.get("after_decision"))
        gates = {s.get("gate") for s in self.doc["stages"]}
        self.assertTrue({"G5", "G6"} <= gates)

    def test_per_portal_status_has_one_home(self):
        # The readiness matrix in docs/portal-publishing-architecture.md, never this file.
        self.assertNotIn("platforms", self.doc)
        self.assertNotIn("platforms", read_json(SCHEMA_PATH)["properties"])


class Problems(unittest.TestCase):
    STEPS = {"sdk", "verify", "store-listing", "listing-validation", "release-review",
             "platform-validate", "publish-review", "submit"}

    def problems(self, doc):
        return pub.publishing_workflow_problems(
            doc, steps=self.STEPS, gates={"G5", "G6"},
            lifecycle={"title:production", "release:store-listing", "release:rc",
                       "release:validating", "release:approved", "release:submitting",
                       "platform-publication:submitted", "platform-publication:in-review",
                       "platform-publication:live"},
            outcomes=["UPLOAD_COMPLETE", "SUBMITTED", "DRY_RUN", "SUBMITTING", "BLOCKED",
                      "INVALID_BUILD", "INVALID_METADATA", "REJECTED", "PLATFORM_ERROR",
                      "RETRYABLE_FAILURE"],
            waiting=["WAITING_FOR_HUMAN_LOGIN", "WAITING_FOR_HUMAN_SUBMIT_CONFIRMATION"],
            refusals={"package-missing", "build-mismatch", "wrong-platform", "wrong-package",
                      "g6-stale", "release-mismatch"},
            registry={"PENDING_REVIEW", "PUBLISHED"})

    def setUp(self):
        self.doc = pub.load_publishing_workflow()

    def test_the_shipped_document_has_none(self):
        self.assertEqual(self.problems(self.doc), [])

    def test_an_unknown_step_gate_or_lifecycle_is_refused(self):
        doc = copy.deepcopy(self.doc)
        doc["stages"][1]["step"] = "upload-from-ci"
        doc["stages"].append({"id": "x", "kind": "human", "step": None, "gate": "G9",
                              "lifecycle": "release:teleported"})
        found = " ".join(self.problems(doc))
        self.assertIn("'upload-from-ci' is not a new-game step", found)
        self.assertIn("gate 'G9'", found)
        self.assertIn("'release:teleported' is neither a machine state", found)

    def test_a_key_without_the_artifact_hash_or_ci_publishing_is_refused(self):
        doc = copy.deepcopy(self.doc)
        doc["publication_key"]["components"] = ["platform", "title", "release_manifest_hash",
                                                "portal_game_id"]
        doc["executor"]["ci_publishes"] = True
        found = " ".join(self.problems(doc))
        self.assertIn("publication_key.components", found)
        self.assertIn("CI/CD never publishes", found)

    def test_an_automated_irreversible_stage_needs_a_human_decision(self):
        doc = copy.deepcopy(self.doc)
        stage = next(s for s in doc["stages"] if s["id"] == "request-review")
        del stage["after_decision"]
        self.assertTrue(any("after_decision" in p for p in self.problems(doc)))

    def test_a_state_read_from_nothing_the_step_reports_is_refused(self):
        doc = copy.deepcopy(self.doc)
        doc["states"].append({"id": "LIVE_GUESS", "meaning": "x", "outcome": ["PROBABLY_LIVE"],
                              "waiting": "WAITING_FOR_LUCK", "refusal": ["latest-build-wins"],
                              "registry": "SHIPPED"})
        doc["states"].append(dict(doc["states"][0]))
        found = " ".join(self.problems(doc))
        for word in ("'PROBABLY_LIVE' is not a publication outcome",
                     "'WAITING_FOR_LUCK' is not a waiting state",
                     "'latest-build-wins' is not a refusal",
                     "'SHIPPED' is not a portal registry status",
                     "state NOT_STARTED appears twice"):
            self.assertIn(word, found)


class Key(unittest.TestCase):
    M, A = "sha256:" + "a" * 64, "sha256:" + "b" * 64

    def test_deterministic_and_shaped(self):
        key = pub.publication_key("yandex", "game-x", self.M, self.A, "12345")
        self.assertEqual(key, pub.publication_key("yandex", "game-x", self.M, self.A, "12345"))
        self.assertRegex(key, r"^wgf-pub-yandex-[0-9a-f]{16}$")
        record = read_json(os.path.join(ROOT, "core", "artifacts", "platform-publication.schema.json"))
        self.assertRegex(key, record["properties"]["submission"]["properties"]["publication_key"]["pattern"])

    def test_another_artifact_manifest_title_or_game_is_another_key(self):
        key = pub.publication_key("yandex", "game-x", self.M, self.A, "12345")
        for other in (pub.publication_key("yandex", "game-x", self.M, "sha256:" + "c" * 64, "12345"),
                      pub.publication_key("yandex", "game-x", "sha256:" + "d" * 64, self.A, "12345"),
                      pub.publication_key("yandex", "game-y", self.M, self.A, "12345"),
                      pub.publication_key("yandex", "game-x", self.M, self.A, "99"),
                      pub.publication_key("crazygames", "game-x", self.M, self.A, "12345")):
            self.assertNotEqual(key, other)

    def test_a_game_without_a_portal_id_keys_as_unassigned(self):
        self.assertEqual(pub.publication_key("yandex", "game-x", self.M, self.A, None),
                         pub.publication_key("yandex", "game-x", self.M, self.A, "unassigned"))
        self.assertEqual(pub.load_publishing_workflow()["publication_key"]["absent_portal_game_id"],
                         "unassigned")


class RecordIdentity(unittest.TestCase):
    """The submit step's record carries the key and the workflow version, and never a key
    made up from a missing package checksum."""
    M = "sha256:" + "a" * 64

    def identity(self, prior, submission=None):
        import types
        from wgf_publish.step import PublishStep
        visit = types.SimpleNamespace(manifest_hash=self.M, title_id="game-x")
        return PublishStep._publication_identity(visit, prior, submission or {})

    def test_a_packaged_record_is_keyed(self):
        prior = {"platform_id": "yandex", "title_id": "game-x",
                 "package": {"checksum": "sha256:" + "b" * 64}}
        found = self.identity(prior, {"portal_game_id": "777"})
        self.assertEqual(found, {"publication_key": pub.publication_key(
            "yandex", "game-x", self.M, "sha256:" + "b" * 64, "777"),
            "publishing_workflow": pub.load_publishing_workflow()["version"]})

    def test_no_checksum_no_key(self):
        self.assertEqual(self.identity({"platform_id": "yandex", "package": {}}), {})


class ReadinessForAPlatform(unittest.TestCase):
    """`wgf-publish.py readiness --platform ID`: a release that targets a platform without
    packaging its build is BLOCKED for it before any portal."""

    def run_cli(self, manifest, *extra):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "manifest.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(manifest, handle)
            return subprocess.run([sys.executable, os.path.join(SCRIPTS, "wgf-publish.py"), "readiness",
                                   "--manifest", path, *extra],
                                  capture_output=True, text=True, cwd=ROOT, timeout=60)

    def manifest(self, packaged):
        return {"release_id": "r1", "commit_sha": "a" * 40,
                "packages": [{"platform_id": pid, "filename": f"{pid}.zip", "size_mb": 1.0,
                              "checksum": "sha256:" + "b" * 64} for pid in packaged],
                "target_platforms": [{"id": "crazygames", "role": "required", "profile_version": "1.3.0"},
                                     {"id": "yandex", "role": "optional", "profile_version": "1.4.0"}]}

    def test_a_targeted_platform_without_its_package_is_blocked(self):
        done = self.run_cli(self.manifest(["crazygames"]), "--platform", "yandex")
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        self.assertRegex(done.stdout, r"platform_packaged\s+RED\s+yandex: targeted but not packaged")
        self.assertIn("readiness: BLOCKED", done.stdout)

    def test_an_untargeted_platform_says_so(self):
        done = self.run_cli(self.manifest(["crazygames"]), "--platform", "y8")
        self.assertRegex(done.stdout, r"platform_packaged\s+RED\s+y8: not targeted and not packaged")

    def test_its_package_turns_the_guard_green(self):
        done = self.run_cli(self.manifest(["crazygames", "yandex"]), "--platform", "yandex")
        self.assertRegex(done.stdout, r"platform_packaged\s+GREEN\s+yandex: yandex.zip")

    def test_without_the_flag_the_guard_is_not_reported(self):
        done = self.run_cli(self.manifest(["crazygames"]))
        self.assertNotIn("platform_packaged", done.stdout)


if __name__ == "__main__":
    unittest.main()

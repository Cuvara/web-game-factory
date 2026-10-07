"""core/reference/publishing-workflow.yaml: the schema, the referential rules, the key.

The publishing workflow is the stages a release goes through to reach a portal, the states a
publication is reported in, the publication key and the artifact lock, and how far each
portal is along the stages (docs/publish-module.md, "The publishing workflow"). It is data
check-integrity.py validates; these tests hold what it must refuse. No portal is contacted.

    python -m unittest scripts/tests/test_publishing_workflow.py
"""

import copy
import glob
import importlib.util
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
sys.path.insert(0, SCRIPTS)

from wgflib import jsonschema_lite as js  # noqa: E402
from wgflib import publication as pub  # noqa: E402
from wgflib.yamllite import load_file  # noqa: E402

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


class Shipped(unittest.TestCase):
    def setUp(self):
        self.doc = pub.load_publishing_workflow()

    def test_it_validates_against_its_schema(self):
        errors = list(js.Validator(read_json(SCHEMA_PATH), registry()).iter_errors(self.doc))
        self.assertEqual(errors, [])

    def test_check_integrity_finds_nothing_and_reports_the_version(self):
        ci = load_check_integrity()
        ci.ERRORS.clear()
        cwd = os.getcwd()
        os.chdir(ROOT)
        try:
            version = ci.check_publishing_workflow()
        finally:
            os.chdir(cwd)
        self.assertEqual(ci.ERRORS, [])
        self.assertEqual(version, self.doc["version"])

    def test_playwright_drives_the_portals_and_ci_never_publishes(self):
        self.assertEqual(self.doc["executor"], {"portal": "playwright", "ci_publishes": False,
                                                "note": self.doc["executor"]["note"]})

    def test_upload_submit_and_published_are_distinct_states(self):
        ids = [s["id"] for s in self.doc["states"]]
        for state in ("WAITING_FOR_HUMAN_LOGIN", "DRY_RUN_PASS", "UPLOADED", "SUBMITTED",
                      "UNDER_REVIEW", "PUBLISHED", "RELEASE_ARTIFACT_MISMATCH", "BLOCKED"):
            self.assertIn(state, ids)
        by_id = {s["id"]: s for s in self.doc["states"]}
        self.assertEqual(by_id["UPLOADED"]["outcome"], ["UPLOAD_COMPLETE"])
        self.assertEqual(by_id["SUBMITTED"]["outcome"], ["SUBMITTED"])

    def test_every_irreversible_stage_is_a_person_s_or_behind_their_decision(self):
        for stage in self.doc["stages"]:
            if stage.get("irreversible"):
                with self.subTest(stage=stage["id"]):
                    self.assertTrue(stage["kind"] == "human" or stage.get("after_decision"))
        gates = {s.get("gate") for s in self.doc["stages"]}
        self.assertTrue({"G5", "G6"} <= gates)

    def test_yandex_pins_core_s_profiles_and_the_rest_stay_unverified(self):
        by_id = {p["id"]: p for p in self.doc["platforms"]}
        self.assertEqual([p["id"] for p in self.doc["platforms"]], ["yandex", "crazygames", "y8", "gamepix"])
        platform = load_file(os.path.join(ROOT, "core", "reference", "platforms", "yandex.yaml"))
        publication = pub.load_publication_profile("yandex")
        self.assertEqual(by_id["yandex"]["platform_profile"], f"yandex@{platform['version']}")
        self.assertEqual(by_id["yandex"]["publication_profile"], f"yandex@{publication['version']}")
        for pid, entry in by_id.items():
            with self.subTest(pid=pid):
                # Nobody has run any of them against the live console yet.
                self.assertEqual(entry["status"], "unverified")
                self.assertNotIn("verified", entry["stages"].values())


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
            profile_versions={"platform": {"yandex": "1.3.0", "crazygames": "1.2.0", "y8": "1.2.0",
                                           "gamepix": "1.0.0"},
                              "publication": {"yandex": "2.3.0", "crazygames": "2.3.0", "y8": "2.2.0",
                                              "gamepix": "2.1.0"}},
            outcomes=["UPLOAD_COMPLETE", "SUBMITTED", "DRY_RUN", "SUBMITTING", "BLOCKED",
                      "INVALID_BUILD", "INVALID_METADATA", "REJECTED", "PLATFORM_ERROR",
                      "RETRYABLE_FAILURE"],
            waiting=["WAITING_FOR_HUMAN_LOGIN", "WAITING_FOR_HUMAN_SUBMIT_CONFIRMATION"])

    def setUp(self):
        self.doc = pub.load_publishing_workflow()

    def test_the_shipped_document_has_none(self):
        self.assertEqual(self.problems(self.doc), [])

    def test_a_stale_profile_pin_is_refused(self):
        doc = copy.deepcopy(self.doc)
        doc["platforms"][0]["platform_profile"] = "yandex@1.2.0"
        self.assertIn("platform 'yandex': platform_profile pins 1.2.0, core's is 1.3.0", self.problems(doc))

    def test_an_unknown_step_gate_or_stage_is_refused(self):
        doc = copy.deepcopy(self.doc)
        doc["stages"][1]["step"] = "upload-from-ci"
        doc["stages"].append({"id": "x", "kind": "human", "step": None, "gate": "G9"})
        doc["platforms"][0]["stages"]["teleport"] = "implemented"
        found = " ".join(self.problems(doc))
        self.assertIn("'upload-from-ci' is not a new-game step", found)
        self.assertIn("gate 'G9'", found)
        self.assertIn("stage 'teleport' is not a workflow stage", found)

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


class Key(unittest.TestCase):
    M, A = "sha256:" + "a" * 64, "sha256:" + "b" * 64

    def test_deterministic_and_shaped(self):
        key = pub.publication_key("yandex", "game-x", self.M, self.A, "12345")
        self.assertEqual(key, pub.publication_key("yandex", "game-x", self.M, self.A, "12345"))
        self.assertRegex(key, r"^wgf-pub-yandex-[0-9a-f]{16}$")

    def test_another_artifact_or_game_is_another_key(self):
        key = pub.publication_key("yandex", "game-x", self.M, self.A, "12345")
        self.assertNotEqual(key, pub.publication_key("yandex", "game-x", self.M, "sha256:" + "c" * 64, "12345"))
        self.assertNotEqual(key, pub.publication_key("yandex", "game-x", self.M, self.A, "99"))
        self.assertNotEqual(key, pub.publication_key("crazygames", "game-x", self.M, self.A, "12345"))

    def test_a_game_without_a_portal_id_keys_as_unassigned(self):
        self.assertEqual(pub.publication_key("yandex", "game-x", self.M, self.A, None),
                         pub.publication_key("yandex", "game-x", self.M, self.A, "unassigned"))


class ReadinessForAPlatform(unittest.TestCase):
    """`wgf-publish.py readiness --platform ID`: a release that targets a platform without
    packaging its build is BLOCKED for it before any portal - the state both validation
    games' r1 releases are in for Yandex (packaged for their primary platform only)."""

    def run_cli(self, manifest, platform):
        import subprocess
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "manifest.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(manifest, handle)
            return subprocess.run([sys.executable, os.path.join(SCRIPTS, "wgf-publish.py"), "readiness",
                                   "--manifest", path, "--platform", platform],
                                  capture_output=True, text=True, cwd=ROOT, timeout=60)

    def manifest(self, packaged):
        return {"release_id": "r1", "commit_sha": "a" * 40,
                "packages": [{"platform_id": pid, "filename": f"{pid}.zip", "size_mb": 1.0,
                              "checksum": "sha256:" + "b" * 64} for pid in packaged],
                "target_platforms": [{"id": "poki", "role": "required", "profile_version": "1.1.0"},
                                     {"id": "yandex", "role": "optional", "profile_version": "1.3.0"}]}

    def test_a_targeted_platform_without_its_package_is_blocked(self):
        done = self.run_cli(self.manifest(["poki"]), "yandex")
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        self.assertRegex(done.stdout, r"platform_packaged\s+RED\s+yandex: targeted but not packaged")
        self.assertIn("readiness: BLOCKED", done.stdout)

    def test_its_package_turns_the_guard_green(self):
        done = self.run_cli(self.manifest(["poki", "yandex"]), "yandex")
        self.assertRegex(done.stdout, r"platform_packaged\s+GREEN\s+yandex: yandex.zip")


if __name__ == "__main__":
    unittest.main()

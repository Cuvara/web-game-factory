"""The portal registry (scripts/wgf_publish/registry.py): one portals.json per title, so a
publish visit never creates a second portal game and a person can link one made by hand."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
sys.path.insert(0, SCRIPTS)

from wgf_publish import registry  # noqa: E402
from wgf_publish.registry import RegistryError  # noqa: E402

NOW = "2026-10-04T10:00:00Z"
HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64


def status_text(text="Status: In review"):
    return [registry.evidence_item("portal-status", "evidence/y8-status.txt", text)]


class RegistryTestCase(unittest.TestCase):
    def setUp(self):
        self.titles = tempfile.mkdtemp(prefix="wgf-registry-")
        self.addCleanup(shutil.rmtree, self.titles, ignore_errors=True)

    def load(self, title="tower-merge"):
        return registry.load(title, titles_dir=self.titles)

    def on_disk(self, title="tower-merge"):
        with open(registry.registry_path(title, self.titles), encoding="utf-8") as handle:
            return json.load(handle)

    def created(self, reg=None, platform="y8", game_id="g-1"):
        reg = reg or self.load()
        reg.record(platform, status="DRAFT_CREATED", external_game_id=game_id,
                   association="created-by-factory", by="automation", run_id="run-1", now=NOW)
        return reg

    def walk(self, reg, platform, *statuses):
        for status in statuses:
            reg.record(platform, status=status, by="automation", run_id="run-1", now=NOW,
                       evidence=status_text(status))


class Create(RegistryTestCase):
    def test_an_empty_registry_writes_nothing(self):
        reg = self.load()
        self.assertEqual(reg.platforms(), [])
        self.assertIsNone(reg.get("y8"))
        self.assertEqual(reg.status("y8"), "NOT_CREATED")
        self.assertFalse(os.path.exists(registry.registry_path("tower-merge", self.titles)))

    def test_create_records_the_game_and_history(self):
        self.created()
        document = self.on_disk()
        self.assertEqual(document["title_id"], "tower-merge")
        entry = document["portals"]["y8"]
        self.assertEqual((entry["status"], entry["external_game_id"], entry["association"]),
                         ("DRAFT_CREATED", "g-1", "created-by-factory"))
        self.assertEqual(entry["history"], [{"at": NOW, "from": "NOT_CREATED",
                                             "to": "DRAFT_CREATED", "by": "automation",
                                             "run_id": "run-1", "note": None}])
        self.assertEqual(self.load().get("y8"), entry)  # reloads

    def test_a_new_entry_needs_a_status_and_an_association(self):
        reg = self.load()
        with self.assertRaises(RegistryError):
            reg.record("y8", external_game_id="g-1", association="observed", by="automation")
        with self.assertRaises(RegistryError):
            reg.record("y8", status="DRAFT", external_game_id="g-1", by="automation")
        with self.assertRaises(RegistryError):
            reg.record("y8", status="NOT_CREATED", by="automation")

    def test_unknown_fields_status_and_actor_are_refused(self):
        reg = self.load()
        for kwargs in ({"status": "DRAFT", "colour": "red", "by": "automation"},
                       {"status": "LIVE", "by": "automation"},
                       {"status": "DRAFT", "by": "robot"}):
            with self.subTest(kwargs=kwargs), self.assertRaises(RegistryError):
                reg.record("y8", **kwargs)
        for bad in ("../y8", "Y8", ""):
            with self.subTest(platform=bad), self.assertRaises(RegistryError):
                reg.record(bad, status="DRAFT", by="automation")
        with self.assertRaises(RegistryError):
            registry.load("../escape", titles_dir=self.titles)


class Transitions(RegistryTestCase):
    def test_every_allowed_transition(self):
        for source, targets in registry.TRANSITIONS.items():
            for target in sorted(targets | registry.ANYWHERE):
                if target == source:
                    continue
                with self.subTest(transition=f"{source} -> {target}"):
                    reg = self.load(f"t-{source.lower().replace('_', '-')}-"
                                    f"{target.lower().replace('_', '-')}")
                    if source != "NOT_CREATED":
                        reg.document["portals"]["y8"] = {
                            "status": source, "history": [
                                {"at": NOW, "from": "NOT_CREATED", "to": source,
                                 "by": "human", "run_id": None, "note": "fixture"}]}
                    entry = reg.record("y8", status=target, by="automation", now=NOW,
                                       evidence=status_text(target))
                    self.assertEqual(entry["status"], target)
                    self.assertEqual(entry["history"][-1]["from"], source)

    def test_every_refused_transition(self):
        refused = 0
        for source in registry.STATUSES:
            allowed = registry.TRANSITIONS[source] | registry.ANYWHERE | {source}
            for target in registry.STATUSES:
                if target in allowed or target == "NOT_CREATED":
                    continue
                refused += 1
                with self.subTest(transition=f"{source} -> {target}"):
                    reg = self.load()
                    if source != "NOT_CREATED":
                        reg.document["portals"]["y8"] = {
                            "status": source, "history": [
                                {"at": NOW, "from": "NOT_CREATED", "to": source,
                                 "by": "human", "run_id": None, "note": "fixture"}]}
                    with self.assertRaises(RegistryError):
                        reg.record("y8", status=target, by="human", now=NOW,
                                   evidence=status_text(target))
        self.assertGreater(refused, 10)
        self.assertFalse(os.path.exists(registry.registry_path("tower-merge", self.titles)))

    def test_the_named_paths(self):
        reg = self.created()
        self.walk(reg, "y8", "DRAFT", "PENDING_REVIEW", "VERIFIED", "PUBLISHED")
        self.walk(reg, "y8", "DRAFT", "PENDING_REVIEW", "REJECTED", "DRAFT", "PENDING_REVIEW",
                  "PUBLISHED")
        self.assertEqual([h["to"] for h in self.on_disk()["portals"]["y8"]["history"]],
                         ["DRAFT_CREATED", "DRAFT", "PENDING_REVIEW", "VERIFIED", "PUBLISHED",
                          "DRAFT", "PENDING_REVIEW", "REJECTED", "DRAFT", "PENDING_REVIEW",
                          "PUBLISHED"])

    def test_draft_cannot_jump_to_published(self):
        reg = self.created()
        self.walk(reg, "y8", "DRAFT")
        with self.assertRaises(RegistryError):
            reg.record("y8", status="PUBLISHED", by="automation", evidence=status_text())
        self.assertEqual(self.on_disk()["portals"]["y8"]["status"], "DRAFT")

    def test_blocked_and_unknown_from_anywhere_and_back(self):
        reg = self.created()
        reg.record("y8", status="BLOCKED", by="automation", note="login wall")
        reg.record("y8", status="UNKNOWN", by="automation", note="status unreadable")
        reg.record("y8", status="PENDING_REVIEW", by="automation", evidence=status_text())
        self.assertEqual(reg.status("y8"), "PENDING_REVIEW")

    def test_the_same_status_again_is_an_observation(self):
        reg = self.created()
        reg.record("y8", by="automation", last_checked_at=NOW, slug="tower-merge", now=NOW)
        entry = self.on_disk()["portals"]["y8"]
        self.assertEqual((entry["status"], entry["slug"]), ("DRAFT_CREATED", "tower-merge"))
        self.assertEqual(entry["history"][-1]["from"], entry["history"][-1]["to"])


class Evidence(RegistryTestCase):
    def test_portal_established_statuses_need_status_text(self):
        for target in sorted(registry.EVIDENCE_REQUIRED):
            with self.subTest(target=target):
                reg = self.load()
                source = "DRAFT" if target == "PENDING_REVIEW" else "PENDING_REVIEW"
                reg.document["portals"]["y8"] = {"status": source, "history": [
                    {"at": NOW, "from": "NOT_CREATED", "to": source, "by": "human",
                     "run_id": None, "note": "fixture"}]}
                for evidence in ((), [registry.evidence_item("screenshot", "a.png", b"png")]):
                    for by in ("automation", "human"):
                        with self.assertRaises(RegistryError):
                            reg.record("y8", status=target, by=by, evidence=evidence)
                reg.record("y8", status=target, by="automation",
                           evidence=[registry.evidence_item("console-text", "c.txt", "Live")])
                self.assertEqual(reg.status("y8"), target)

    def test_evidence_is_kept_and_hashed(self):
        reg = self.created()
        self.walk(reg, "y8", "DRAFT", "PENDING_REVIEW")
        evidence = self.on_disk()["portals"]["y8"]["evidence"]
        self.assertEqual(len(evidence), 2)
        self.assertEqual(evidence[-1]["kind"], "portal-status")
        self.assertRegex(evidence[-1]["sha256"], r"^sha256:[0-9a-f]{64}$")

    def test_a_draft_needs_no_portal_evidence(self):
        reg = self.created()
        reg.record("y8", status="DRAFT", by="automation")
        self.assertEqual(reg.status("y8"), "DRAFT")


class Identity(RegistryTestCase):
    def test_automation_never_overwrites_a_recorded_id(self):
        reg = self.created()
        reg.record("y8", by="automation", app_id="a-1")
        for field in registry.IDENTITY:
            with self.subTest(field=field), self.assertRaises(RegistryError):
                reg.record("y8", by="automation", **{field: "other"})
        entry = self.on_disk()["portals"]["y8"]
        self.assertEqual((entry["external_game_id"], entry["app_id"]), ("g-1", "a-1"))

    def test_automation_may_fill_an_empty_id_and_repeat_the_same(self):
        reg = self.load()
        reg.record("y8", status="DRAFT_CREATED", by="automation", association="created-by-factory")
        reg.record("y8", by="automation", external_game_id="g-1", app_id="a-1")
        reg.record("y8", by="automation", external_game_id="g-1")
        with self.assertRaises(RegistryError):
            reg.record("y8", by="automation", app_id="a-2")
        self.assertEqual((reg.get("y8")["external_game_id"], reg.get("y8")["app_id"]),
                         ("g-1", "a-1"))

    def test_a_person_may_change_a_recorded_id(self):
        reg = self.created()
        reg.record("y8", by="human", external_game_id="g-2", note="the old one was a test")
        self.assertEqual(self.on_disk()["portals"]["y8"]["external_game_id"], "g-2")

    def test_human_association_of_a_manually_created_game(self):
        reg = self.load()
        entry = reg.associate("crazygames", "cg-777", note="created by hand in the console")
        self.assertEqual((entry["status"], entry["external_game_id"], entry["association"]),
                         ("UNKNOWN", "cg-777", "associated-by-person"))
        self.assertEqual(entry["history"][-1]["by"], "human")
        self.assertEqual(self.load().lookup_candidates("crazygames")[0]["id"], "cg-777")

    def test_association_replaces_an_id_and_drops_the_old_games_facts(self):
        reg = self.created()
        self.walk(reg, "y8", "DRAFT", "PENDING_REVIEW")
        reg.record("y8", by="automation", build_hash=HASH_A, submission_status="In review")
        entry = reg.associate("y8", "g-9", note="the real game")
        self.assertEqual((entry["status"], entry["external_game_id"], entry["build_hash"],
                          entry["submission_status"]), ("UNKNOWN", "g-9", None, None))

    def test_association_is_a_persons_act_with_a_reason(self):
        reg = self.load()
        with self.assertRaises(RegistryError):
            reg.associate("y8", "g-1", by="automation", note="x")
        with self.assertRaises(RegistryError):
            reg.associate("y8", "g-1", note="")
        with self.assertRaises(RegistryError):
            reg.associate("y8", " ", note="x")


class Lookup(RegistryTestCase):
    def test_registry_first_then_game_config(self):
        reg = self.created(game_id="g-1")
        reg.record("y8", by="automation", app_id="a-1")
        self.assertEqual(reg.lookup_candidates("y8", config_game_id="cfg-1",
                                               config_app_id="a-1"),
                         [{"source": "registry", "field": "external_game_id", "id": "g-1"},
                          {"source": "registry", "field": "app_id", "id": "a-1"},
                          {"source": "game-config", "field": "game_id", "id": "cfg-1"}])

    def test_nothing_recorded_falls_back_to_config(self):
        reg = self.load()
        self.assertEqual(reg.lookup_candidates("gamepix"), [])
        self.assertEqual([c["id"] for c in reg.lookup_candidates("gamepix", "cfg", None)],
                         ["cfg"])


class Invalidation(RegistryTestCase):
    def test_a_changed_build_or_listing_is_reported_and_recorded(self):
        reg = self.created()
        self.assertEqual(reg.invalidate_if_changed("y8", HASH_A, HASH_A),
                         {"build_hash": {"from": None, "to": HASH_A},
                          "campaign_hash": {"from": None, "to": HASH_A}})
        reg.record("y8", by="automation", submission_status="In review")
        self.assertEqual(reg.invalidate_if_changed("y8", HASH_A, HASH_A), {})
        self.assertEqual(reg.invalidate_if_changed("y8", HASH_B, HASH_A),
                         {"build_hash": {"from": HASH_A, "to": HASH_B}})
        entry = self.on_disk()["portals"]["y8"]
        self.assertEqual((entry["build_hash"], entry["submission_status"], entry["status"]),
                         (HASH_B, None, "DRAFT_CREATED"))
        self.assertEqual(entry["history"][-1]["note"], "changed: build_hash")

    def test_no_game_nothing_to_invalidate(self):
        reg = self.load()
        self.assertEqual(reg.invalidate_if_changed("y8", HASH_A, HASH_B), {})
        self.assertFalse(os.path.exists(registry.registry_path("tower-merge", self.titles)))


class Independence(RegistryTestCase):
    def test_a_rejected_y8_leaves_gamepix_untouched(self):
        reg = self.created(platform="y8", game_id="y8-1")
        self.created(reg, platform="gamepix", game_id="gp-1")
        self.walk(reg, "gamepix", "DRAFT", "PENDING_REVIEW")
        before = self.on_disk()["portals"]["gamepix"]
        self.walk(reg, "y8", "DRAFT", "PENDING_REVIEW", "REJECTED")
        after = self.on_disk()["portals"]
        self.assertEqual(after["gamepix"], before)
        self.assertEqual(after["y8"]["status"], "REJECTED")
        self.assertEqual(self.load().platforms(), ["gamepix", "y8"])


class Persistence(RegistryTestCase):
    def test_written_file_is_schema_valid_and_lf(self):
        reg = self.created()
        self.walk(reg, "y8", "DRAFT", "PENDING_REVIEW")
        reg.associate("crazygames", "cg-1", note="manual")
        path = registry.registry_path("tower-merge", self.titles)
        with open(path, "rb") as handle:
            raw = handle.read()
        self.assertNotIn(b"\r", raw)
        self.assertTrue(raw.endswith(b"}\n"))
        self.assertEqual(registry.validate(json.loads(raw)), [])

    def test_schema_refuses_a_broken_document(self):
        document = {"title_id": "t", "updated_at": NOW,
                    "portals": {"y8": {"status": "LIVE", "history": []}}}
        self.assertTrue(registry.validate(document))

    def test_write_is_atomic(self):
        reg = self.created()
        path = registry.registry_path("tower-merge", self.titles)
        with open(path, "rb") as handle:
            before = handle.read()
        with mock.patch("wgf_publish.registry.os.replace", side_effect=OSError("disk")):
            with self.assertRaises(OSError):
                reg.record("y8", status="DRAFT", by="automation")
        with open(path, "rb") as handle:
            self.assertEqual(handle.read(), before)
        self.assertEqual(os.listdir(os.path.dirname(path)), ["portals.json"])
        self.assertEqual(reg.status("y8"), "DRAFT_CREATED")  # memory unchanged too

    def test_a_refused_write_changes_nothing(self):
        reg = self.created()
        with self.assertRaises(RegistryError):
            reg.record("y8", status="PUBLISHED", by="automation", evidence=status_text())
        self.assertEqual(reg.status("y8"), "DRAFT_CREATED")
        self.assertEqual(len(self.on_disk()["portals"]["y8"]["history"]), 1)

    def test_a_corrupt_or_foreign_file_is_refused_on_load(self):
        self.created()
        path = registry.registry_path("tower-merge", self.titles)
        with open(path, encoding="utf-8") as handle:
            document = json.load(handle)
        os.makedirs(os.path.join(self.titles, "other"))
        with open(registry.registry_path("other", self.titles), "w", encoding="utf-8") as handle:
            json.dump(document, handle)
        with self.assertRaises(RegistryError):
            self.load("other")
        document["portals"]["y8"]["status"] = "LIVE"
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(document, handle)
        with self.assertRaises(RegistryError):
            self.load()


class Cli(RegistryTestCase):
    def run_cli(self, *argv):
        env = dict(os.environ, WGF_PROJECT_DIR=self.project)
        return subprocess.run([sys.executable, os.path.join(SCRIPTS, "wgf-publish.py"), *argv],
                              capture_output=True, text=True, env=env, cwd=SCRIPTS)

    def setUp(self):
        super().setUp()
        self.project = tempfile.mkdtemp(prefix="wgf-registry-project-")
        self.addCleanup(shutil.rmtree, self.project, ignore_errors=True)

    def test_associate_then_show(self):
        done = self.run_cli("registry", "associate", "tower-merge", "y8", "y8-42",
                            "--note", "created by hand")
        self.assertEqual(done.returncode, 0, done.stderr)
        path = os.path.join(self.project, "workspace", "titles", "tower-merge", "portals.json")
        self.assertTrue(os.path.isfile(path))
        shown = self.run_cli("registry", "show", "tower-merge", "--json")
        self.assertEqual(shown.returncode, 0, shown.stderr)
        self.assertEqual(json.loads(shown.stdout)["portals"]["y8"]["external_game_id"], "y8-42")
        self.assertIn("y8-42", self.run_cli("registry", "show", "tower-merge").stdout)

    def test_associate_refuses_an_unknown_platform_and_needs_a_note(self):
        self.assertEqual(self.run_cli("registry", "associate", "tower-merge", "nowhere", "1",
                                      "--note", "x").returncode, 2)
        self.assertNotEqual(self.run_cli("registry", "associate", "tower-merge", "y8",
                                         "1").returncode, 0)


if __name__ == "__main__":
    unittest.main()

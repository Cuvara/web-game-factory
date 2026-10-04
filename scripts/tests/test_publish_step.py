"""The submit step across platforms (scripts/wgf_publish/step.py): G6 and release integrity
before every upload, the portal registry, a person's submit confirmation, create-before-build
portals, and per-platform independent state - with `--platform` and `--track`.

    python -m unittest scripts/tests/test_publish_step.py

A release of one fixture game for y8, yandex and crazygames (test_release_module's fixture
repository, a bundle per platform). The adapter is a scripted fake (PublishStep's
`adapter_factory`): it returns the Publication a console run would, platform by platform, and
records every Job it was given. No portal and no browser is contacted.
"""

import json
import os
import re
import sys
import textwrap
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, HERE)

from test_publish_module import (FIXTURES, PublishCase,  # noqa: E402
                                 listing_placeholders)
from test_release_module import NOW, Context, Inputs, seal, step as release_step  # noqa: E402
from wgf_publish import PlatformValidateStep, PublishStep, common, identity, outcomes  # noqa: E402
from wgf_publish import registry as portal_registry  # noqa: E402
from wgf_publish.adapters import Publication, PublicationAdapter  # noqa: E402
from wgflib.workflow import StepOutcome  # noqa: E402
from wgflib.workflow.definition import StepDefinition  # noqa: E402

PLATFORMS = ("y8", "yandex", "crazygames")
GAME_CONFIG = textwrap.dedent("""\
    game:
      id: fixture-game
      name: Fixture Game
      version: 0.1.0
    build:
      output: dist
    platforms:
      - { id: y8, profile: y8@1.2.0, role: required }
      - { id: yandex, profile: yandex@1.2.0, role: required }
      - { id: crazygames, profile: crazygames@1.2.0, role: required }
    """)
IDS = {"external_game_id": "y8-4711", "app_id": "app-0042"}
STATUS = {"submitted": "In review", "live": "Published", "draft": "Draft"}


def decision(choice, note=None, at="2026-10-04T10:00:00Z", by="human"):
    return {"decision": choice, "decided_by": by, "decided_at": at,
            **({"note": note} if note else {})}


# -- the scripted adapter ---------------------------------------------------------------------

class Script:
    """{platform: [Publication, or callable(job) -> Publication, ...]}, consumed in order."""

    def __init__(self, **by_platform):
        self.by_platform = {pid: list(items) for pid, items in by_platform.items()}
        self.jobs = []

    def factory(self, platform_id, profile, settings):
        script = self

        class Fake(PublicationAdapter):
            method = "console"

            def publish(self, job):
                script.jobs.append(job)
                queue = script.by_platform.get(platform_id) or []
                if not queue:
                    raise AssertionError(f"{platform_id}: the adapter was not expected to run")
                item = queue.pop(0)
                return item(job) if callable(item) else item

        return Fake(platform_id, profile, settings)

    def calls(self, platform_id=None):
        return [j for j in self.jobs if platform_id is None or j.platform_id == platform_id]


def uploaded(pid, draft="d-1"):
    return Publication(outcomes.UPLOAD_COMPLETE, f"{pid}: uploaded and saved", draft_id=draft,
                       uploaded=True, saved=True, status_text=STATUS["draft"],
                       human_reason="submit-confirmation", phase_reached="save_draft")


def requested(pid, draft="d-1"):
    return Publication(outcomes.VERIFIED, f"{pid}: the console shows In review",
                       state="submitted", draft_id=draft, submitted=True,
                       status_text=STATUS["submitted"],
                       verified_state={"observed": STATUS["submitted"], "at": NOW,
                                       "source": "console status text"})


def issued(pid):
    return Publication(outcomes.IDS_ISSUED, f"{pid}: the game was created; ids issued",
                       created_ids=dict(IDS), status_text=STATUS["draft"],
                       phase_reached="create_game")


def duplicate(pid):
    return Publication(outcomes.UNKNOWN, f"{pid}: a game titled Fixture Game exists that this "
                       f"title never recorded", human_reason="duplicate-candidate",
                       found_game={"id": "777", "title": "Fixture Game", "source": "title"})


def pending_review(pid):
    return Publication(outcomes.UNKNOWN, f"{pid}: the game is under review; nothing uploaded",
                       human_reason="review-pending", status_text=STATUS["submitted"])


def failure(pid):
    return Publication(outcomes.PLATFORM_ERROR, f"{pid}: the upload was refused")


# -- the fixture ------------------------------------------------------------------------------

class MultiCase(PublishCase):
    """A drafted release packaging y8, yandex and crazygames, each from its own bundle."""

    def setUp(self):
        super().setUp()
        self.game.commit("game.config.yaml", GAME_CONFIG, "three portals")
        self.profiles = os.path.join(self.scratch, "publication")
        os.makedirs(self.profiles)
        with open(os.path.join(FIXTURES, "publication", "generic-web.yaml"), encoding="utf-8") as h:
            template = h.read()
        for pid in PLATFORMS:
            text = template.replace("id: generic-web", f"id: {pid}")
            if pid == "y8":
                text = text.replace("    title_match: exact-casefold\n",
                                    "    title_match: exact-casefold\n"
                                    "    issued_on_create:\n"
                                    "      - {key: external_game_id, read: [{css: \"#game-id\"}]}\n"
                                    "      - {key: app_id, read: [{css: \"#app-id\"}]}\n"
                                    "    build_config: {external_game_id: "
                                    "\"platforms[].game_id\", app_id: \"platforms[].app_id\"}\n")
            with open(os.path.join(self.profiles, f"{pid}.yaml"), "w", encoding="utf-8",
                      newline="\n") as handle:
                handle.write(text)
        # No session anywhere: every fixture profile is `credential: {kind: human-login}`.
        self.env = dict(self.environ)
        self.config = {"publish": {"profiles_extra": [self.profiles]}}
        self.live_config = {"publish": dict(self.config["publish"], mode="live")}
        self.live_env = dict(self.env, WGF_PUBLISH_LIVE="1")
        self.draft()

    def draft(self):
        """verify's per-platform bundles and the release drafted from them."""
        self.builds = self.game.build_platforms(PLATFORMS)
        readiness = [{"platform_id": p, "profile": f"{p}@1.2.0", "role": "required",
                      "readiness": "ready", "checks": [f"platform.hooks:{p}"],
                      "blocking_checks": [], "external_approval": "not-claimed",
                      "evidence_status": "PASS_MOCK", "portal_status": "NOT_APPLICABLE"}
                     for p in PLATFORMS]
        self.evidence = self.game.evidence(platform_builds=self.builds, platforms=readiness)
        instance = release_step(repo_dir=self.game.root)
        instance.environ = self.game.environ(())
        instance.clock = staticmethod(lambda: NOW)
        drafted = instance.execute(Inputs(self.evidence, ()), Context())
        self.assertEqual(drafted.outcome, StepOutcome.SUCCESS, drafted.error)
        self.manifest = drafted.artifacts[0].content
        self.release_dir = common.release_dir(self.game.root, self.manifest["release_id"])
        self.records = {pid: self.ready(pid) for pid in PLATFORMS}
        self.answers = 0

    def ready(self, pid, manifest=None):
        """A validated, READY platform-publication for `pid`, pinning the manifest."""
        manifest = manifest or self.manifest
        package = next(p for p in manifest["packages"] if p["platform_id"] == pid)
        context = Context()
        context.current_step = "platform-validate"
        body = {"release_id": manifest["release_id"], "title_id": "fixture-game",
                "platform_id": pid, "profile_version": "1.2.0", "role": "required",
                "state": "validated", "readiness": "READY",
                "guards": [{"guard": "assertions_pass", "verdict": "GREEN", "reason": "fixture"}],
                "package": {"filename": package["filename"], "checksum": package["checksum"],
                            "verified_on_disk": True},
                "evidence": [], "measurement_class": "automation-check",
                "workflow": {"run_id": "run-1", "workflow_id": "new-game",
                             "step_id": "platform-validate", "visit": 1, "execution": 1}}
        return common.record(body, inputs=Inputs({"release-manifest": manifest}),
                             context=context, title_id="fixture-game", sequence=1).content

    def registry(self):
        return portal_registry.load("fixture-game", self.titles)

    def submit(self, script, *, records=None, decision=None, live=True, environ=None,
               manifest=None, g6=None, gates=("G4", "G5", "G6"), verification=None,
               listing=None, visit=1):
        records = dict(self.records, **(records or {}))
        publications = [records[p] for p in PLATFORMS if p in records]
        env = dict(self.live_env if live else self.env, **(environ or {}))
        result = self.publish(publications[0], publications=publications, adapter=script.factory,
                              config=self.live_config if live else self.config, environ=env,
                              decision=decision, manifest=manifest or self.manifest,
                              g6=g6 or self.g6(manifest=manifest or self.manifest),
                              gates=gates, verification=verification or
                              self.evidence["verification-report"], listing=listing,
                              visit=visit)
        for artifact in result.artifacts:
            self.records[artifact.content["platform_id"]] = artifact.content
        return result

    def written(self, result):
        return {a.content["platform_id"]: a.content for a in result.artifacts}


# -- 1. G6 and release integrity --------------------------------------------------------------

class Integrity(MultiCase):
    def test_a_g6_for_another_manifest_or_not_a_person_s_uploads_nothing(self):
        script = Script()
        other = json.loads(json.dumps(self.manifest))
        other["provenance"]["content_hash"] = "sha256:" + "f" * 64
        result = self.submit(script, g6=self.g6(manifest=other))
        self.assertEqual((result.outcome, result.data["code"]), (StepOutcome.BLOCKED, "g6-stale"))
        self.assertIn("G6 must be decided again", result.message)
        result = self.submit(script, g6=self.g6(mode="auto-approved"))
        self.assertEqual(result.data["code"], "g6-not-human")
        self.assertEqual((result.artifacts, script.jobs), ([], []))

    def test_a_store_listing_changed_after_g6_is_stale(self):
        script = Script()
        changed = listing_placeholders()
        listing = json.loads(json.dumps(changed["store-listing"]))
        listing["provenance"]["content_hash"] = "sha256:" + "e" * 64
        result = self.submit(script, listing={"store-listing": listing,
                                              "listing-validation-report":
                                                  changed["listing-validation-report"]})
        self.assertEqual((result.outcome, result.data["code"]), (StepOutcome.BLOCKED, "g6-stale"))
        self.assertIn("store-listing", result.message)
        # A G6 that never covered the listing validation is stale too.
        g6 = self.g6()
        g6["subject"] = [s for s in g6["subject"]
                         if s["artifact_type"] != "listing-validation-report"]
        result = self.submit(script, g6=g6)
        self.assertEqual(result.data["code"], "g6-stale")
        self.assertEqual(script.jobs, [])

    def resealed(self, change):
        manifest = json.loads(json.dumps(self.manifest))
        change(manifest)
        body = {k: v for k, v in manifest.items() if k != "provenance"}
        return seal("release-manifest", body, inputs=manifest["provenance"]["inputs"],
                    schema_version=manifest["provenance"]["schema_version"])

    def test_a_package_built_from_another_bundle_is_an_invalid_build(self):
        def other_bundle(manifest):
            for package in manifest["packages"]:
                if package["platform_id"] == "yandex":
                    package["bundle_hash"] = "sha256:" + "1" * 64
        manifest = self.resealed(other_bundle)
        records = {p: self.ready(p, manifest) for p in PLATFORMS}
        script = Script(y8=[issued("y8")], crazygames=[uploaded("crazygames")])
        result = self.submit(script, manifest=manifest, records=records)
        yandex = self.written(result)["yandex"]
        self.assertEqual(yandex["outcome"], "INVALID_BUILD")
        self.assertIn("not the bundle verify built and verified for yandex",
                      json.dumps(yandex["evidence"]))
        self.assertEqual(script.calls("yandex"), [])
        self.assertEqual(result.outcome, StepOutcome.WAITING_FOR_HUMAN)  # the others wait

    def test_another_platform_s_build_is_refused_as_the_wrong_platform(self):
        verified = {b["platform_id"]: b["content_hash"] for b in self.builds}

        def swapped(manifest):
            for package in manifest["packages"]:
                if package["platform_id"] == "y8":
                    package["bundle_hash"] = verified["crazygames"]
        manifest = self.resealed(swapped)
        records = {p: self.ready(p, manifest) for p in PLATFORMS}
        script = Script(yandex=[failure("yandex")], crazygames=[failure("crazygames")])
        result = self.submit(script, manifest=manifest, records=records)
        y8 = self.written(result)["y8"]
        self.assertEqual(y8["outcome"], "INVALID_BUILD")
        self.assertIn("crazygames's build", json.dumps(y8["evidence"]))
        self.assertEqual(script.calls("y8"), [])

    def test_a_package_whose_bytes_changed_is_an_invalid_build(self):
        with open(os.path.join(self.release_dir, "yandex.zip"), "ab") as handle:
            handle.write(b"tamper")
        script = Script(y8=[issued("y8")], crazygames=[uploaded("crazygames")])
        result = self.submit(script)
        self.assertEqual(self.written(result)["yandex"]["outcome"], "INVALID_BUILD")
        self.assertEqual(script.calls("yandex"), [])


# -- 2. the registry and a person's submit confirmation ---------------------------------------

class Confirmation(MultiCase):
    def uploaded_all(self):
        script = Script(y8=[issued("y8")], yandex=[uploaded("yandex", "dy")],
                        crazygames=[uploaded("crazygames", "dc")])
        return self.submit(script), script

    def test_an_upload_waits_for_a_person_then_submit_requests_review_once(self):
        result, script = self.uploaded_all()
        self.assertEqual(result.outcome, StepOutcome.WAITING_FOR_HUMAN, result.message)
        self.assertEqual(result.data["waiting_state"], "WAITING_FOR_HUMAN_SUBMIT_CONFIRMATION")
        self.assertEqual(result.data["choices"], ["submit", "hold", "abandon", "done"])
        self.assertEqual(result.data["waiting"], ["yandex", "crazygames"])
        for job in script.jobs:
            self.assertTrue(job.live)
            self.assertFalse(job.submit)  # the upload visit never requests review
        record = self.records["yandex"]
        self.assertEqual((record["outcome"], record["waiting"]["state"]),
                         ("UPLOAD_COMPLETE", "WAITING_FOR_HUMAN_SUBMIT_CONFIRMATION"))
        entry = self.registry().get("yandex")
        self.assertEqual(entry["status"], "DRAFT")
        self.assertEqual(entry["build_hash"], next(p["bundle_hash"] for p in
                                                   self.manifest["packages"]
                                                   if p["platform_id"] == "yandex"))
        self.assertEqual(entry["campaign_hash"],
                         self.listing["store-listing"]["provenance"]["content_hash"])
        # submit: only the platform it answers (the first waiting) is contacted, once.
        script = Script(yandex=[requested("yandex", "dy")])
        result = self.submit(script, decision=decision("submit"))
        (job,) = script.jobs
        self.assertEqual((job.platform_id, job.submit, job.submit_confirmed), ("yandex", True, True))
        self.assertEqual(self.records["yandex"]["outcome"], "VERIFIED")
        self.assertEqual(self.records["yandex"]["state"], "submitted")
        self.assertEqual(set(self.written(result)), {"yandex"})  # the others untouched
        self.assertEqual(self.registry().status("yandex"), "PENDING_REVIEW")
        self.assertEqual(self.registry().get("yandex")["submission_status"], "In review")
        self.assertEqual(result.outcome, StepOutcome.WAITING_FOR_HUMAN)  # crazygames still waits
        self.assertEqual(result.data["waiting"], ["crazygames"])
        # Re-executing the visit with the same answer acts on nothing again (idempotent).
        script = Script()
        again = self.submit(script, decision=decision("submit"))
        self.assertEqual(script.jobs, [])
        self.assertEqual(again.outcome, StepOutcome.WAITING_FOR_HUMAN)
        self.assertIn("nothing submitted again", again.message)

    def test_a_note_answers_the_platform_it_names(self):
        self.uploaded_all()
        script = Script(crazygames=[requested("crazygames", "dc")])
        self.submit(script, decision=decision("submit", note="platform=crazygames"))
        self.assertEqual([j.platform_id for j in script.jobs], ["crazygames"])
        self.assertEqual(self.records["yandex"]["outcome"], "UPLOAD_COMPLETE")

    def test_submit_needs_live_mode(self):
        self.uploaded_all()
        script = Script()
        result = self.submit(script, decision=decision("submit"), live=False)
        self.assertEqual(script.jobs, [])
        self.assertEqual(result.outcome, StepOutcome.WAITING_FOR_HUMAN)
        self.assertIn("live mode", result.message)

    def test_hold_leaves_the_draft_and_nothing_is_requested(self):
        self.uploaded_all()
        script = Script()
        result = self.submit(script, decision=decision("hold", note="platform=yandex"))
        self.assertEqual(script.jobs, [])
        held = self.records["yandex"]
        self.assertEqual((held["outcome"], held["waiting"]["reason"]), ("UPLOAD_COMPLETE", "held"))
        self.assertEqual(self.registry().status("yandex"), "DRAFT")
        self.assertEqual(result.outcome, StepOutcome.WAITING_FOR_HUMAN)  # crazygames waits
        self.assertNotIn("yandex", result.data["waiting"])
        # A new visit asks again; the draft is not touched.
        script = Script()
        result = self.submit(script, visit=2)
        self.assertEqual(script.jobs, [])
        self.assertEqual(result.data["waiting"], ["yandex", "crazygames"])

    def test_abandon_ends_the_platform_s_attempt(self):
        self.uploaded_all()
        result = self.submit(Script(), decision=decision("abandon", note="platform=crazygames"))
        self.assertEqual(self.records["crazygames"]["outcome"], "BLOCKED")
        self.assertEqual(self.records["crazygames"]["measurement_class"], "human")
        self.assertEqual(self.records["yandex"]["outcome"], "UPLOAD_COMPLETE")
        self.assertEqual(result.outcome, StepOutcome.WAITING_FOR_HUMAN)  # yandex still waits

    def test_a_submit_after_the_manifest_changed_is_refused(self):
        self.uploaded_all()
        uploaded_yandex = self.records["yandex"]
        # The release is drafted again (a new commit, new bundles); G6 is decided again.
        self.game.commit("src/main.ts", "export const game = 2;\n", "a fix")
        self.draft()
        script = Script()
        result = self.submit(script, decision=decision("submit", note="platform=yandex"),
                             records={"yandex": uploaded_yandex})
        self.assertEqual(script.jobs, [])
        self.assertEqual(result.outcome, StepOutcome.BLOCKED)
        self.assertIn("g6-stale", result.message)
        self.assertIn("G6 must be decided again", result.message)

    def test_a_submit_after_the_build_on_the_portal_changed_is_refused(self):
        self.uploaded_all()
        reg = self.registry()
        reg.record("yandex", by="automation", build_hash="sha256:" + "2" * 64)
        script = Script()
        result = self.submit(script, decision=decision("submit", note="platform=yandex"))
        self.assertEqual(script.jobs, [])
        self.assertIn("g6-stale", result.message)


class Registry(MultiCase):
    def test_a_duplicate_candidate_is_associated_by_a_person_then_the_visit_continues(self):
        script = Script(y8=[issued("y8")], yandex=[duplicate("yandex")],
                        crazygames=[uploaded("crazygames")])
        result = self.submit(script)
        record = self.records["yandex"]
        self.assertEqual((record["outcome"], record["human_required"]["reason"]),
                         ("UNKNOWN", "duplicate-candidate"))
        self.assertIsNone(self.registry().get("yandex"))  # nothing recorded for it
        self.assertEqual(result.data["waiting"][0], "yandex")
        script = Script(yandex=[uploaded("yandex", "d777")])
        self.submit(script, decision=decision("done", note="portal-id=777 made by hand"))
        entry = self.registry().get("yandex")
        self.assertEqual((entry["external_game_id"], entry["association"]),
                         ("777", "associated-by-person"))
        (job,) = script.jobs
        self.assertEqual(job.known_ids[0], {"source": "registry", "field": "external_game_id",
                                            "id": "777"})
        self.assertEqual(self.records["yandex"]["outcome"], "UPLOAD_COMPLETE")
        self.assertEqual((entry["history"][0]["to"], entry["history"][0]["by"]),
                         ("UNKNOWN", "human"))
        self.assertEqual(entry["history"][-1]["to"], "DRAFT")

    def test_the_job_names_the_game_and_never_creates_a_known_one(self):
        self.registry().record("yandex", status="DRAFT_CREATED", external_game_id="ya-9",
                               association="created-by-factory", by="automation")
        self.live_config["publish"]["login_timeout_s"] = 600
        script = Script(y8=[issued("y8")], yandex=[uploaded("yandex")],
                        crazygames=[uploaded("crazygames")])
        self.submit(script)
        jobs = {j.platform_id: j for j in script.jobs}
        self.assertEqual(jobs["yandex"].identity, {"portal_game_id": "ya-9",
                                                   "config_game_id": None,
                                                   "config_app_id": None,
                                                   "title": "Fixture Game"})
        self.assertFalse(jobs["yandex"].allow_create)
        self.assertTrue(jobs["crazygames"].allow_create)
        self.assertEqual(jobs["yandex"].login_timeout_s, 600)

    def test_a_login_handoff_is_the_record_s_waiting_block(self):
        handoff = {"at": NOW, "url": "https://console.example/login", "reason": "login",
                   "action": "log in on the opened page; handle CAPTCHA/2FA yourself",
                   "resume": "the console page is detected", "resolved_at": None}
        login = Publication(outcomes.AUTH_REQUIRED, "yandex: a person must log in",
                            human_reason="login", login_handoffs=[handoff],
                            phase_reached="check_session")
        script = Script(y8=[issued("y8")], yandex=[login], crazygames=[uploaded("crazygames")])
        result = self.submit(script)
        waiting = self.records["yandex"]["waiting"]
        self.assertEqual((waiting["state"], waiting["url"], waiting["step"], waiting["resume"]),
                         ("WAITING_FOR_HUMAN_LOGIN", "https://console.example/login",
                          "check_session", "the console page is detected"))
        self.assertEqual(result.data["waiting_state"], "WAITING_FOR_HUMAN_LOGIN")

    def test_a_pending_review_uploads_nothing_and_blocks_no_other_platform(self):
        reg = self.registry()
        reg.record("crazygames", status="DRAFT_CREATED", external_game_id="cg-1",
                   association="created-by-factory", by="automation")
        reg.record("crazygames", status="PENDING_REVIEW", by="automation",
                   evidence=[portal_registry.evidence_item("portal-status", "x", "In review")])
        script = Script(y8=[issued("y8")], yandex=[uploaded("yandex")],
                        crazygames=[pending_review("crazygames")])
        result = self.submit(script)
        (job,) = script.calls("crazygames")
        self.assertEqual(job.registry_status, "PENDING_REVIEW")
        self.assertEqual(job.known_ids[0]["id"], "cg-1")
        crazy = self.records["crazygames"]
        self.assertEqual(crazy["human_required"]["reason"], "review-pending")
        self.assertEqual(self.registry().status("crazygames"), "PENDING_REVIEW")
        self.assertIsNone(self.registry().get("crazygames").get("build_hash"))
        # The Yandex draft is made all the same.
        self.assertEqual(self.records["yandex"]["outcome"], "UPLOAD_COMPLETE")
        self.assertEqual(self.registry().status("yandex"), "DRAFT")
        self.assertEqual(result.outcome, StepOutcome.WAITING_FOR_HUMAN)


# -- 3. create-before-build -------------------------------------------------------------------

class CreateBeforeBuild(MultiCase):
    def test_ids_issued_are_recorded_and_route_platform_ids(self):
        # Every other platform is done: a person submitted it by hand.
        self.done("yandex")
        self.done("crazygames")
        script = Script(y8=[issued("y8")])
        result = self.submit(script, live=False)
        (job,) = script.jobs
        self.assertEqual((job.platform_id, job.required_ids), ("y8", ["external_game_id", "app_id"]))
        self.assertEqual((result.outcome, result.route), (StepOutcome.SUCCESS, "platform-ids"),
                         result.message)
        entry = self.registry().get("y8")
        self.assertEqual((entry["status"], entry["external_game_id"], entry["app_id"],
                          entry["association"]),
                         ("DRAFT_CREATED", "y8-4711", "app-0042", "created-by-factory"))
        self.assertEqual(self.records["y8"]["outcome"], "IDS_ISSUED")

    def done(self, pid):
        """A record of `pid` a person already submitted by hand in this run."""
        self.answers += 1
        result = self.submit(Script(), live=False, decision=decision(
            "done", note=f"platform={pid}", at=f"2026-10-04T09:00:{self.answers:02d}Z"))
        return self.written(result)[pid]

    def test_the_ids_are_written_into_the_build_and_the_rebuilt_package_is_accepted(self):
        self.registry().record("y8", status="DRAFT_CREATED", by="automation",
                               external_game_id=IDS["external_game_id"], app_id=IDS["app_id"],
                               association="created-by-factory")
        # The build without them is refused before any upload, here and at validation.
        script = Script(yandex=[uploaded("yandex")], crazygames=[uploaded("crazygames")])
        result = self.submit(script)
        self.assertEqual(self.written(result)["y8"]["outcome"], "INVALID_BUILD")
        self.assertIn("lacks external_game_id, app_id",
                      json.dumps(self.written(result)["y8"]["evidence"]))
        self.assertEqual(script.calls("y8"), [])
        guard = self.guard("y8")
        self.assertEqual(guard["verdict"], "RED", guard)
        # sdk writes them (wgf_publish.identity.sync), the build is made again from them.
        profiles = {"y8": common.publication_profile_for(
            "y8", common.Settings(self.config, {}))}
        written = identity.sync(self.game.root, "fixture-game", profiles, self.titles)
        self.assertEqual(written[0]["ids"], ["y8.game_id", "y8.app_id"])
        with open(self.game.path("game.config.yaml"), encoding="utf-8") as handle:
            text = handle.read()
        self.assertIn("game_id: y8-4711", text)
        self.assertIn("{ id: yandex, profile: yandex@1.2.0, role: required }", text)
        self.assertEqual(identity.sync(self.game.root, "fixture-game", profiles, self.titles), [])
        self.game.commit("game.config.yaml", text, "sdk: portal ids")
        self.draft()
        self.assertEqual(self.guard("y8")["verdict"], "GREEN")
        script = Script(y8=[uploaded("y8")], yandex=[uploaded("yandex")],
                        crazygames=[uploaded("crazygames")])
        result = self.submit(script)
        (job,) = script.calls("y8")
        self.assertEqual(job.required_ids, [])
        self.assertEqual(self.records["y8"]["outcome"], "UPLOAD_COMPLETE")
        self.assertEqual(self.records["y8"]["submission"]["portal_game_id"], "y8-4711")

    def guard(self, pid):
        instance = PlatformValidateStep(StepDefinition(
            {"id": "platform-validate", "type": "platform-validate",
             "inputs": ["release-manifest", "verification-report", "scaffold-record"],
             "outputs": ["platform-publication"], "with": {"repo_dir": self.game.root}},
            retry=None, max_visits=None))
        instance.environ = self.env
        result = instance.execute(Inputs({"release-manifest": self.manifest,
                                          "verification-report": self.evidence["verification-report"],
                                          "scaffold-record": self.evidence["scaffold-record"]}),
                                  self.context("platform-validate", self.config))
        record = next(a.content for a in result.artifacts if a.content["platform_id"] == pid)
        return next(g for g in record["guards"] if g["guard"] == "platform_ids_present")

    def test_a_portal_without_issued_ids_is_green(self):
        self.assertEqual(self.guard("yandex")["verdict"], "GREEN")
        self.assertEqual(self.guard("y8")["verdict"], "GREEN")  # not issued yet
        self.assertIn("not issued yet", self.guard("y8")["reason"])


# -- 4. independent state, --platform, --track ------------------------------------------------

class PerPlatform(MultiCase):
    def test_one_platform_failing_leaves_the_others_untouched(self):
        script = Script(y8=[failure("y8")], yandex=[uploaded("yandex")],
                        crazygames=[pending_review("crazygames")])
        result = self.submit(script)
        written = self.written(result)
        self.assertEqual({p: r["outcome"] for p, r in written.items()},
                         {"y8": "PLATFORM_ERROR", "yandex": "UPLOAD_COMPLETE",
                          "crazygames": "UNKNOWN"})
        self.assertEqual(result.outcome, StepOutcome.WAITING_FOR_HUMAN)  # waits beat failures
        self.assertIsNone(self.registry().get("y8"))
        # Yandex is answered; y8's failure is still its own, and makes the step FAILED.
        script = Script(yandex=[requested("yandex")])
        result = self.submit(script, decision=decision("submit"))
        self.assertEqual(self.records["y8"]["outcome"], "PLATFORM_ERROR")
        self.assertEqual(result.outcome, StepOutcome.WAITING_FOR_HUMAN)  # crazygames
        result = self.submit(Script(), decision=decision("abandon", at="2026-10-04T11:00:00Z"))
        self.assertEqual(result.outcome, StepOutcome.FAILED)
        self.assertFalse(result.retryable)
        self.assertEqual(self.records["yandex"]["outcome"], "VERIFIED")

    def test_platform_acts_on_the_named_platform_only(self):
        script = Script(yandex=[uploaded("yandex")])
        result = self.submit(script, environ={"WGF_PUBLISH_PLATFORMS": "yandex"})
        self.assertEqual([j.platform_id for j in script.jobs], ["yandex"])
        self.assertEqual(set(self.written(result)), {"yandex"})
        self.assertEqual(result.outcome, StepOutcome.WAITING_FOR_HUMAN)
        script = Script()
        result = self.submit(script, environ={"WGF_PUBLISH_PLATFORMS": "poki"})
        self.assertEqual(result.outcome, StepOutcome.BLOCKED)
        self.assertIn("--platform poki", result.message)
        # A platform not yet attempted is named, never passed over.
        self.done_by_hand("crazygames")
        result = self.submit(Script(), environ={"WGF_PUBLISH_PLATFORMS": "crazygames"})
        self.assertEqual(result.outcome, StepOutcome.WAITING_FOR_HUMAN)  # yandex's upload
        self.assertIn("y8: no", result.message.replace("READY", "no"))

    def done_by_hand(self, pid):
        self.answers += 1
        result = self.submit(Script(), decision=decision(
            "done", note=f"platform={pid}", at=f"2026-10-04T09:00:{self.answers:02d}Z"))
        return self.written(result)[pid]

    def test_track_reads_each_status_and_acts_on_nothing(self):
        reg = self.registry()
        reg.record("yandex", status="DRAFT_CREATED", external_game_id="ya-1",
                   association="created-by-factory", by="automation")
        reg.record("yandex", status="PENDING_REVIEW", by="automation",
                   evidence=[portal_registry.evidence_item("portal-status", "x", "In review")])
        self.done_by_hand("yandex")

        def live(job):
            self.assertTrue(job.track)
            self.assertFalse(job.submit or job.live or job.submit_confirmed)
            return Publication(outcomes.VERIFIED, "yandex: Published", state="live",
                               status_text=STATUS["live"],
                               verified_state={"observed": "Published", "at": NOW,
                                               "source": "console status text"})
        script = Script(yandex=[live])
        # Read-only: G6 is not needed to read a status.
        result = self.submit(script, environ={"WGF_PUBLISH_TRACK": "1"}, gates=())
        self.assertEqual([j.platform_id for j in script.jobs], ["yandex"])  # nothing else known
        self.assertEqual(self.records["yandex"]["state"], "live")
        self.assertEqual(self.registry().status("yandex"), "PUBLISHED")
        self.assertEqual(self.registry().get("yandex")["submission_status"], "Published")
        self.assertIn("nothing to read", result.message)

    def test_a_validation_of_another_manifest_is_stale(self):
        old = self.records["yandex"]
        self.game.commit("src/main.ts", "export const game = 3;\n", "a fix")
        self.draft()
        script = Script(y8=[issued("y8")], crazygames=[uploaded("crazygames")])
        result = self.submit(script, records={"yandex": old})
        self.assertEqual(script.calls("yandex"), [])
        self.assertIn("run platform-validate again", result.message)



# -- 5. through the engine, and the CLI -------------------------------------------------------

FLOW = """\
workflow:
  id: publish-per-platform
  version: 1
  start: verify
  groups:
    publish: [platform-validate, release-review, publish-review, submit]
  steps:
    - id: sdk
      type: test.sdk
      stage: title:prototype
    - id: verify
      type: test.verify
      stage: release:qa
      outputs: [prototype-report, sdk-report, scaffold-record, verification-report, qa-report, review-report, production-quality-report, visual-qa-report, store-listing, listing-validation-report]
      max_visits: 5
    - id: release
      type: release
      stage: release:draft
      inputs: [qa-report, verification-report, sdk-report, prototype-report, scaffold-record, review-report, production-quality-report, visual-qa-report]
      outputs: [release-manifest]
      with: {repo_dir: %(repo)s, required_gates: [], required_listing: false}
      max_visits: 5
    - id: platform-validate
      type: test.validate
      stage: release:validating
      inputs: [release-manifest]
      outputs: [platform-publication]
      max_visits: 5
    - id: release-review
      type: human-checkpoint
      stage: release:rc
      inputs: [qa-report, verification-report, release-manifest]
      outputs: [decision-record]
      with: {gate: G5, choices: [approve, reject]}
      max_visits: 5
      on: {reject: $end}
    - id: publish-review
      type: human-checkpoint
      stage: release:approved
      inputs: [release-manifest, platform-publication, store-listing, listing-validation-report]
      outputs: [decision-record]
      with: {gate: G6, choices: [publish, reject]}
      max_visits: 5
      on: {reject: $end}
    - id: submit
      type: publish
      stage: release:submitting
      inputs: [release-manifest, platform-publication, decision-record, scaffold-record, verification-report, store-listing, listing-validation-report]
      outputs: [platform-publication]
      retry: {max_attempts: 1}
      with: {repo_dir: %(repo)s}
      max_visits: 9
      on: {platform-ids: sdk}
"""


class ThroughTheEngine(MultiCase):
    """The group in a run: one record per platform (StepInputs.every), a person's submit
    per platform, and a create-before-build portal's ids routed back to be built in."""

    def setUp(self):
        super().setUp()
        from wgflib.workflow import ArtifactOutput, StepResult, WorkflowStep
        from wgf_release import ReleaseStep
        case = self
        self.script = Script()

        class Sdk(WorkflowStep):
            type = "test.sdk"

            def execute(self, inputs, context):
                # What the sdk step does for a create-before-build portal: the registry's
                # ids into game.config.yaml, committed.
                profiles = {pid: common.publication_profile_for(
                    pid, common.Settings(context.config, {})) for pid in PLATFORMS}
                written = identity.sync(case.game.root, "fixture-game", profiles, case.titles)
                if written:
                    with open(case.game.path("game.config.yaml"), encoding="utf-8") as handle:
                        case.game.commit("game.config.yaml", handle.read(), "sdk: portal ids")
                return StepResult.success([], message=f"wrote {written}")

        class Verify(WorkflowStep):
            type = "test.verify"

            def execute(self, inputs, context):
                builds = case.game.build_platforms(PLATFORMS)
                readiness = [{"platform_id": p, "profile": f"{p}@1.2.0", "role": "required",
                              "readiness": "ready", "checks": [f"platform.hooks:{p}"],
                              "blocking_checks": [], "external_approval": "not-claimed",
                              "evidence_status": "PASS_MOCK", "portal_status": "NOT_APPLICABLE"}
                             for p in PLATFORMS]
                case.evidence = case.game.evidence(platform_builds=builds, platforms=readiness,
                                                   run_id=context.run_id)
                out = dict(case.evidence)
                out.update(listing_placeholders())
                return StepResult.success([ArtifactOutput(t, a) for t, a in out.items()])

        class Validate(WorkflowStep):
            type = "test.validate"

            def execute(self, inputs, context):
                manifest = inputs.load("release-manifest")
                return StepResult.success([
                    ArtifactOutput("platform-publication", case.ready(p["platform_id"], manifest),
                                   name=common.output_name(p["platform_id"]))
                    for p in manifest["packages"]])

        module = type(sys)("wgf_publish_step_test_steps")
        module.register = lambda registry: [registry.register(c.type, c)
                                            for c in (Sdk, Verify, Validate)]
        sys.modules[module.__name__] = module
        self.addCleanup(sys.modules.pop, module.__name__, None)
        saved = {(cls, name): cls.__dict__.get(name) for cls, name in (
            (ReleaseStep, "environ"), (ReleaseStep, "clock"), (PublishStep, "environ"),
            (PublishStep, "adapter_factory"))}
        self.addCleanup(lambda: [setattr(cls, name, value) for (cls, name), value
                                 in saved.items()])
        ReleaseStep.environ = self.game.environ(())
        ReleaseStep.clock = staticmethod(lambda: NOW)
        PublishStep.environ = self.live_env
        PublishStep.adapter_factory = self.script.factory
        self.flow = os.path.join(self.scratch, "publish-per-platform.workflow.yaml")
        with open(self.flow, "w", encoding="utf-8") as handle:
            handle.write(FLOW % {"repo": json.dumps(self.game.root.replace(os.sep, "/"))})
        self.factory = dict(self.live_config["publish"])
        self.modules = ["wgf_release", "wgf_publish", module.__name__]

    def api(self):
        from wgflib.workflow.api import WorkflowAPI
        from wgflib.workflow.config import FactoryConfig
        config = FactoryConfig({"steps": {"modules": self.modules}, "storage": {"fsync": False},
                                "publish": self.factory})
        return WorkflowAPI(config=config, store_dir=os.path.join(self.scratch, "store"),
                           workflow=self.flow)

    def answer(self, api, state, choice, note=None):
        from wgflib.workflow.api import RunRequest
        return api.run(RunRequest(resume=state.run_id, decision=choice, decided_by="human",
                                  note=note))

    def stored(self, api, state, pid):
        stored = api.store.load(state.run_id)
        return api.store.read_artifact(state.run_id, stored.latest_artifact(
            common.output_name(pid)))

    def test_each_platform_on_its_own_and_the_ids_built_in(self):
        from wgflib.workflow.api import RunRequest
        from wgflib.workflow.model import RunStatus
        api = self.api()
        self.script.by_platform = {"y8": [issued("y8")], "yandex": [uploaded("yandex")],
                                   "crazygames": [uploaded("crazygames")]}
        state = api.run(RunRequest(project_id="fixture-game"))
        self.assertEqual(state.cursor, "release-review", state.message)
        state = self.answer(api, state, "approve")
        state = self.answer(api, state, "publish")
        self.assertEqual((state.status, state.cursor), (RunStatus.WAITING, "submit"),
                         state.message)
        self.assertEqual(api.pending(state)["choices"], ["submit", "hold", "abandon", "done"])
        self.assertEqual({p: self.stored(api, state, p)["outcome"] for p in PLATFORMS},
                         {"y8": "IDS_ISSUED", "yandex": "UPLOAD_COMPLETE",
                          "crazygames": "UPLOAD_COMPLETE"})
        # A person confirms yandex, then crazygames; each visit contacts only that portal.
        self.script.by_platform = {"yandex": [requested("yandex")]}
        state = self.answer(api, state, "submit")
        self.assertEqual((state.status, state.cursor), (RunStatus.WAITING, "submit"))
        self.assertEqual(self.stored(api, state, "yandex")["outcome"], "VERIFIED")
        self.assertEqual(self.stored(api, state, "crazygames")["outcome"], "UPLOAD_COMPLETE")
        self.script.by_platform = {"crazygames": [requested("crazygames")]}
        state = self.answer(api, state, "submit", note="looked at the draft")
        # Nothing waits: y8's ids route back; sdk builds them in, verify and release make
        # the build again, and G5 is asked again.
        self.assertEqual((state.status, state.cursor), (RunStatus.WAITING, "release-review"),
                         state.message)
        trail = [entry["step"] for entry in state.trail]
        self.assertEqual(trail[trail.index("sdk") - 1], "submit")
        with open(self.game.path("game.config.yaml"), encoding="utf-8") as handle:
            self.assertIn("app_id: app-0042", handle.read())
        state = self.answer(api, state, "approve")
        self.script.by_platform = {"y8": [uploaded("y8")],
                                   "yandex": [pending_review("yandex")],
                                   "crazygames": [pending_review("crazygames")]}
        self.script.jobs = []
        state = self.answer(api, state, "publish")
        self.assertEqual((state.status, state.cursor), (RunStatus.WAITING, "submit"),
                         state.message)
        jobs = {j.platform_id: j for j in self.script.jobs}
        self.assertEqual(jobs["y8"].required_ids, [])
        self.assertEqual(self.stored(api, state, "y8")["outcome"], "UPLOAD_COMPLETE")
        self.assertEqual(self.stored(api, state, "y8")["submission"]["portal_game_id"], "y8-4711")
        self.assertEqual(jobs["yandex"].registry_status, "PENDING_REVIEW")

    def cli(self, *argv):
        import io
        import wgf
        config = os.path.join(self.scratch, "factory.yaml")
        with open(config, "w", encoding="utf-8") as handle:
            handle.write("factory: " + json.dumps({
                "steps": {"modules": self.modules}, "storage": {
                    "fsync": False, "directory": os.path.join(self.scratch, "store")
                    .replace(os.sep, "/")},
                "publish": dict(self.factory, profiles_extra=[self.profiles.replace(os.sep, "/")])
            }) + "\n")
        out = io.StringIO()
        saved = sys.stdout, sys.stderr
        sys.stdout = sys.stderr = out
        try:
            code = wgf.main(list(argv[:1]) + ["--config", config, "--workflow", self.flow]
                            + list(argv[1:]))
        finally:
            sys.stdout, sys.stderr = saved
        return code, out.getvalue()

    def test_the_cli_platform_and_track(self):
        from wgflib.workflow.api import RunRequest
        for name in ("WGF_PUBLISH_PLATFORMS", "WGF_PUBLISH_TRACK"):
            self.addCleanup(os.environ.pop, name, None)
        PublishStep.environ = None  # the CLI's process environment, as in a real command
        for key, value in self.live_env.items():
            if key.startswith("WGF_PUBLISH") or key in ("PATH",):
                self.addCleanup(os.environ.__setitem__, key, os.environ[key]) \
                    if key in os.environ else self.addCleanup(os.environ.pop, key, None)
                os.environ[key] = value
        api = self.api()
        state = api.run(RunRequest(project_id="fixture-game", scope="verify"))
        state = api.run(RunRequest(run_id=state.run_id, scope="release"))
        run_id = state.run_id
        code, _ = self.cli("publish", "--track")
        self.assertEqual(code, 2)  # --track needs --run
        # --platform: the group, acting on yandex alone.
        self.script.by_platform = {"yandex": [uploaded("yandex")]}
        code, out = self.cli("publish", "--run", run_id, "--platform", "yandex")
        self.assertEqual(code, 3, out)  # waits at G5
        state = self.answer(api, api.store.load(run_id), "approve")
        state = self.answer(api, state, "publish")
        self.assertEqual([j.platform_id for j in self.script.jobs], ["yandex"])
        self.assertEqual(state.cursor, "submit")
        records = {p: self.stored(api, state, p).get("outcome") for p in ("yandex", "y8")}
        self.assertEqual(records, {"yandex": "UPLOAD_COMPLETE", "y8": None})
        # --track: only the publish step runs again, read-only, whatever it did before.
        os.environ.pop("WGF_PUBLISH_PLATFORMS", None)
        self.registry().record("yandex", status="DRAFT", by="automation",
                               external_game_id="ya-1", association="created-by-factory")

        def read(job):
            self.assertTrue(job.track)
            self.assertFalse(job.live or job.submit)
            return Publication(outcomes.UNKNOWN, "yandex: Draft", status_text="Draft",
                               human_reason="ambiguous-portal-state")
        self.script.by_platform = {"yandex": [read]}
        self.script.jobs = []
        code, out = self.cli("publish", "--run", run_id, "--track")
        self.assertEqual([j.platform_id for j in self.script.jobs], ["yandex"], out)
        events = [e for e in api.store.read_events(run_id) if e.get("event") == "STEP_STARTED"]
        self.assertEqual(events[-1].get("step_id"), "submit")
        self.assertEqual(self.registry().get("yandex")["submission_status"], "Draft")


if __name__ == "__main__":
    unittest.main()

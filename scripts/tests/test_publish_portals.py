"""The five portal adapters (scripts/wgf_publish/adapters/{yandex,crazygames,y8,
gamedistribution,gamepix}.py): each portal's own status vocabulary, review handling and human
handoffs over its own publication profile - and, opt-in, each one FIXTURE-validated through
the real executor in headless Chromium against its flavor of the fixture portal
(scripts/tests/fixtures/publish/flavors.py), with the test playing the person who logs in.

    python -m unittest scripts/tests/test_publish_portals.py
    WGF_PUBLISH_BROWSER_TEST=1 python -m unittest scripts/tests/test_publish_portals.py

The profiles are core's, unchanged, with only what they list as unknown overlaid for the
fixture (the session markers, the games list, where the status and the game id are shown,
how a declaration shows as done). No test contacts a real portal.
"""

import copy
import datetime
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import urllib.request
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, HERE)

import campaign_fixture  # noqa: E402
from testenv import enabled  # noqa: E402
from test_publish_executor import (HUMAN_JS, LISTING, PNG, TITLE, FakeRunner,  # noqa: E402
                                   completed, stopped)
from wgf_publish import outcomes  # noqa: E402
from wgf_publish import registry as portal_registry  # noqa: E402
from wgf_publish.adapters import PORTALS, Job, PortalAdapter, resolve  # noqa: E402
from wgf_publish.adapters import portal as portal_module  # noqa: E402
from wgflib import publication as pub  # noqa: E402
from wgflib import redact  # noqa: E402

PORTAL = os.path.join(HERE, "fixtures", "publish", "portal.py")
PIDS = ("yandex", "crazygames", "y8", "gamedistribution", "gamepix")
GD_GAME_ID = "0123456789abcdef0123456789abcdef"
GD_CONFIRMED = {"prerequisites_confirmed": ["developer-account", "developer-terms",
                                            "self-hosting"]}
SDK_TAG = b"<script src='https://integration.gamepix.com/sdk/v3/gamepix.sdk.js'></script>"


def overlay(profile, base):
    """Core's profile, with only what it lists as unknown filled in for the fixture."""
    profile = copy.deepcopy(profile)
    sub = profile["submission"]
    sub["console"]["url"] = base + "/console"
    sub["console"]["allowed_origins"] = [base]
    sub["session"] = {"logged_in": [{"css": "#dashboard"}], "login": [{"css": "form#login"}]}
    sub["identity"].update({"list_url": "/console", "game_url": "/console/game/{id}",
                            "row": [{"css": "tr.game"}], "row_title": [{"css": "td.title"}],
                            "row_id": {"attr": "data-id"}, "page_id": [{"css": "#game-id"}]})
    sub["status"].update({"read": [{"css": "#status"}], "error": [{"css": "#upload-error"}]})
    for intent in sub["flow"]:
        if intent["class"] == "human":
            intent["expect"] = {"visible": [{"css": f"[data-human='{intent['id']}']"}]}
    return profile


class Release:
    """A release directory: a real zip (with the GamePix SDK when asked), media, listing."""

    def __init__(self, root, pid, sdk=False):
        self.root, self.pid = root, pid
        self.release_dir = os.path.join(root, "release", "r1")
        self.run_dir = os.path.join(root, "run")
        os.makedirs(os.path.join(self.release_dir, "listing"), exist_ok=True)
        os.makedirs(self.run_dir, exist_ok=True)
        self.package = os.path.join(self.release_dir, f"{pid}.zip")
        with zipfile.ZipFile(self.package, "w") as archive:
            archive.writestr("index.html", b"<!doctype html><html><head>"
                             + (SDK_TAG if sdk else b"") + b"</head><body></body></html>")
            archive.writestr("assets/game.js", b"console.log('game');")
        for name in ("icon.png", "cover.png", "shot-1.png", "shot-2.png"):
            with open(os.path.join(self.release_dir, "listing", name), "wb") as handle:
                handle.write(PNG)
        # The shipped campaign every listing value and medium comes from (wgf_publish.campaign).
        extra = []
        if pid == "crazygames":
            # CrazyGames' three documented covers, one rendition each (its image ids).
            for cid, (w, h) in (("cover-16x9", (96, 54)), ("cover-2x3", (60, 90)),
                                ("cover-1x1", (64, 64))):
                extra.append((dict(id=cid, rel=f"platforms/{pid}/{cid}.png", format="png",
                                   width=w, height=h, kind="thumbnail", source="thumbnail",
                                   requirement=cid), campaign_fixture.png_bytes(w, h, seed=3)))
        campaign_fixture.write_campaign(self.release_dir, pid, rendition_extra=extra)
        self.metadata = {"title": TITLE, "descriptions": {"en": "A fixture."},
                         "icon": "listing/icon.png", "cover": "listing/cover.png",
                         "screenshots": ["listing/shot-1.png", "listing/shot-2.png"],
                         "locales_included": ["en", "ru"]}

    def job(self, *, live=False, confirmed=False, track=False, identity=None, checkout=None,
            console_url=None, run_process=None, visit="1-1", entry=None, required=None):
        job = Job(platform_id=self.pid, release_id="r1",
                  idempotency_key=f"wgf-{self.pid}-0123456789abcdef",
                  package_path=self.package,
                  package={"filename": f"{self.pid}.zip", "size_mb": 0.01,
                           "checksum": "sha256:" + "0" * 64},
                  metadata=self.metadata, checkout=checkout or self.root,
                  release_dir=self.release_dir, run_dir=self.run_dir,
                  scratch_dir=os.path.join(self.run_dir, "submit", visit, self.pid),
                  submit=live and confirmed, live=live and not track, track=track,
                  submit_confirmed=confirmed, env=dict(os.environ), hooks={},
                  timeouts={"action": 2500, "navigation": 8000, "upload": 20000},
                  console_url=console_url, run_process=run_process, listing=LISTING,
                  platform_profile={}, identity=identity or {}, registry_entry=entry,
                  registry_status=(entry or {}).get("status"), required_ids=required,
                  allow_create=not entry)
        return job


def entry(status, history=(), other_ids=None, game_id=None):
    item = {"status": status, "history": [{"at": "2026-10-01T00:00:00Z", "from": f, "to": t,
                                            "by": "automation", "run_id": None, "note": None}
                                           for f, t in history]}
    if other_ids:
        item["other_ids"] = dict(other_ids)
    if game_id:
        item["external_game_id"] = game_id
    return item


class PortalCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="wgf-portals-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.addCleanup(redact.forget)

    def release(self, pid, sdk=False):
        return Release(os.path.join(self.tmp, pid), pid, sdk=sdk)

    def adapter(self, pid, settings=None, profile=None):
        profile = profile or overlay(pub.load_publication_profile(pid), "http://127.0.0.1:1")
        base = dict(GD_CONFIRMED) if pid == "gamedistribution" else {}
        base.update({"console_url": "http://127.0.0.1:1/console"}, **(settings or {}))
        return PORTALS[pid](pid, profile, base)


# -- one adapter per portal, no shared behaviour table -------------------------------------------

class Adapters(PortalCase):
    def test_each_target_resolves_to_its_own_adapter(self):
        classes = []
        for pid in PIDS:
            adapter = resolve(pid, pub.load_publication_profile(pid), {})
            with self.subTest(pid=pid):
                self.assertIs(type(adapter), PORTALS[pid])
                self.assertIsInstance(adapter, PortalAdapter)
                self.assertEqual(type(adapter).__module__, f"wgf_publish.adapters.{pid}")
            classes.append(type(adapter))
        self.assertEqual(len(set(classes)), 5)

    def test_the_five_adapters_do_not_share_one_behaviour_table(self):
        for name in ("STATUS", "HANDOFFS"):
            tables = [PORTALS[pid].__dict__.get(name) for pid in PIDS]
            with self.subTest(table=name):
                self.assertTrue(all(tables), f"every adapter defines its own {name}")
                self.assertEqual(len({id(t) for t in tables}), 5)
                for i, one in enumerate(tables):
                    for other in tables[i + 1:]:
                        self.assertNotEqual(one, other)
        for pid in PIDS:
            cls = PORTALS[pid]
            with self.subTest(pid=pid):
                self.assertIn("refuse", cls.__dict__, "its own checks before the console")
                self.assertIn("adjust", cls.__dict__, "its own reading of the run")
        self.assertEqual(PortalAdapter.STATUS, {})
        self.assertEqual(PortalAdapter.HANDOFFS, {})

    def test_each_status_table_is_its_profile_s_words_and_handoffs_its_human_intents(self):
        for pid in PIDS:
            profile = pub.load_publication_profile(pid)
            cls = PORTALS[pid]
            status = profile["submission"]["status"]
            humans = {i["id"] for i in profile["submission"]["flow"] if i["class"] == "human"}
            with self.subTest(pid=pid):
                self.assertEqual(set(cls.STATUS), set(status["states"]))
                self.assertTrue(set(cls.STATUS.values()) <= set(portal_registry.STATUSES))
                for word in status.get("submitted_states") or []:
                    self.assertEqual(cls.STATUS[word], "PENDING_REVIEW")
                for word in status.get("live_states") or []:
                    self.assertEqual(cls.STATUS[word], "PUBLISHED")
                for word in status.get("rejected_states") or []:
                    self.assertEqual(cls.STATUS[word], "REJECTED")
                self.assertEqual(set(cls.HANDOFFS), humans)
                for reason, what in cls.HANDOFFS.values():
                    self.assertIn(reason, ("legal", "declaration"))
                    self.assertTrue(what)

    def test_every_new_locator_is_documented_or_a_hypothesis_with_unknowns_named(self):
        for pid in PIDS:
            profile = pub.load_publication_profile(pid)
            with self.subTest(pid=pid):
                self.assertEqual(profile["status"], "unverified")
                self.assertEqual(profile["submission"]["automation_terms"], "unverified")
                self.assertTrue(profile["unknowns"])
                for intent in profile["submission"]["flow"]:
                    if intent["class"] != "human":
                        self.assertIn(intent.get("basis"), ("documented", "hypothesis"),
                                      intent["id"])
                        if intent.get("basis") == "documented":
                            self.assertTrue(intent.get("source") or any(
                                s.get("url") for s in profile.get("sources") or []), intent["id"])

    def test_the_overlay_changes_no_intent_of_core_s_flow(self):
        for pid in PIDS:
            core = pub.load_publication_profile(pid)
            fixture = overlay(core, "http://127.0.0.1:9")
            with self.subTest(pid=pid):
                for a, b in zip(core["submission"]["flow"], fixture["submission"]["flow"]):
                    b = dict(b)
                    if a["class"] == "human":
                        b.pop("expect")
                    self.assertEqual(a, b)
                self.assertEqual(pub.flow_problems(fixture), [])

    def test_the_cooldown_tables_are_the_profiles(self):
        y8 = pub.load_publication_profile("y8")["submission"]["constraints"]
        self.assertEqual(y8["resubmission_cooldown"],
                         "0, 6 h, 12 h, 24 h, 2 days, then 5 days (exempt above 10 M plays)")
        self.assertEqual(PORTALS["y8"].COOLDOWN_HOURS, (0, 6, 12, 24, 48, 120))
        ya = pub.load_publication_profile("yandex")["submission"]["constraints"]
        self.assertEqual(ya["resubmission_cooldown"],
                         "24 h, doubling to 2, 4, 8 and 16 days; reset once per 28 days")
        self.assertEqual(PORTALS["yandex"].COOLDOWN_HOURS, (24, 48, 96, 192, 384))
        at = datetime.datetime(2026, 10, 4, tzinfo=datetime.timezone.utc)
        self.assertEqual(portal_module.next_allowed((0, 6), 1, at), at)
        self.assertEqual(portal_module.next_allowed((0, 6), 9, at) - at,
                         datetime.timedelta(hours=6))

    def test_the_test_only_headless_mode_needs_the_loopback_fixture(self):
        human = os.path.join(self.tmp, "human.mjs")
        for pid in PIDS:
            release = self.release(pid)
            job = release.job()
            with self.subTest(pid=pid):
                local = self.adapter(pid, {"test_headless": True, "test_human": human})
                self.assertEqual(local.browser_mode(job), (True, human))
                real = PORTALS[pid](pid, pub.load_publication_profile(pid),
                                    {"test_headless": True, "test_human": human})
                self.assertEqual(real.browser_mode(job), (False, None))


# -- each portal's own rules, without a browser ------------------------------------------------------

class Rules(PortalCase):
    def run_fake(self, pid, result, **job):
        runner = FakeRunner(result)
        adapter = self.adapter(pid)
        release = self.release(pid, sdk=pid == "gamepix")
        if pid == "gamedistribution":
            job.setdefault("identity", {"config_game_id": GD_GAME_ID})
        publication = adapter.publish(release.job(run_process=runner, **job))
        return publication, runner

    def test_yandex_verified_is_a_person_s_publish_and_registry_verified(self):
        publication, runner = self.run_fake(
            "yandex", completed(status_text="Verified", already_requested=True),
            live=True, confirmed=True, identity={"portal_game_id": "g1"},
            entry=entry("PENDING_REVIEW", game_id="g1"))
        self.assertEqual((publication.outcome, publication.human_reason),
                         (outcomes.HUMAN_REQUIRED, "manual-submission"), publication.message)
        self.assertEqual(publication.registry["status"], "VERIFIED")
        self.assertIn("Publish is a person's irreversible click", publication.message)
        self.assertFalse(any("publish" in i["id"] for i in runner.flows[0]["intents"]
                             if i["class"] != "human"))

    def test_yandex_runs_the_language_tabs_language_by_language(self):
        adapter = self.adapter("yandex")
        intents = [f"{i['id']}:{i.get('locale')}" for i in adapter.intents(
            self.release("yandex").job())[0] if i["phase"] == "fill_metadata"]
        self.assertEqual(intents, [
            "tab.language:en", "field.title:en", "field.description:en", "field.how_to_play:en",
            "tab.language:ru", "field.title:ru", "field.description:ru", "field.how_to_play:ru"])

    def test_yandex_refuses_a_third_new_game_request_on_the_account(self):
        titles = os.path.join(self.tmp, "titles")
        for title, gid in (("one", "y1"), ("two", "y2")):
            reg = portal_registry.load(title, titles)
            reg.record("yandex", by="automation", status="DRAFT", external_game_id=gid,
                       association="created-by-factory")
            reg.record("yandex", by="automation", status="PENDING_REVIEW", evidence=[
                portal_registry.evidence_item("portal-status", "x", "Waiting for moderation")])
        adapter = self.adapter("yandex", {"titles_dir": titles})
        runner = FakeRunner(completed(status_text="Waiting for moderation", requested=True))
        job = self.release("yandex").job(live=True, confirmed=True, run_process=runner,
                                         identity={"portal_game_id": "y3"},
                                         entry=entry("DRAFT", game_id="y3"))
        publication = adapter.publish(job)
        self.assertEqual((publication.outcome, publication.human_reason),
                         (outcomes.UNKNOWN, "review-pending"), publication.message)
        self.assertIn("at most 2 new-game requests", publication.message)
        self.assertEqual(runner.flows, [], "the console is not contacted")
        runner.result = completed(status_text="Waiting for moderation", requested=True)
        # An update of a published game is not a new-game request.
        job = self.release("yandex").job(live=True, confirmed=True, run_process=runner,
                                         identity={"portal_game_id": "y3"},
                                         entry=entry("DRAFT", [("PENDING_REVIEW", "PUBLISHED"),
                                                               ("PUBLISHED", "DRAFT")], game_id="y3"))
        self.assertEqual(adapter.publish(job).outcome, outcomes.SUBMITTED)

    def test_a_rejection_records_its_cooldown_and_nothing_re_requests(self):
        for pid, first in (("yandex", 24), ("y8", 0)):
            with self.subTest(pid=pid):
                publication, runner = self.run_fake(
                    pid, completed(status_text="Rejected", already_requested=True), live=True,
                    confirmed=True, identity={"portal_game_id": "g1", "config_game_id": "g1",
                                              "config_app_id": "a1"},
                    entry=entry("PENDING_REVIEW", game_id="g1"))
                self.assertEqual(publication.outcome, outcomes.REJECTED, publication.message)
                ids = publication.registry["other_ids"]
                self.assertEqual(ids["rejections"], "1")
                until = portal_module.parse_time(ids["next_request_after"])
                delta = until - datetime.datetime.now(datetime.timezone.utc)
                self.assertLess(abs(delta - datetime.timedelta(hours=first)),
                                datetime.timedelta(minutes=2))
                self.assertIn("Rejected", runner.flows[0]["status"]["approved_states"],
                              "a confirmed visit counts the rejection as requested: no click")
                # Recorded REJECTED: the next confirmed visit is refused before the console.
                runner = FakeRunner(completed())
                again = self.adapter(pid).publish(self.release(pid).job(
                    live=True, confirmed=True, run_process=runner,
                    entry=entry("REJECTED", [("PENDING_REVIEW", "REJECTED")],
                                other_ids={"next_request_after": "2099-01-01T00:00:00Z"})))
                self.assertEqual((again.outcome, again.human_reason),
                                 (outcomes.HUMAN_REQUIRED, "platform-rejection"))
                self.assertEqual(runner.flows, [])

    def test_a_cooldown_still_running_refuses_the_confirmed_request(self):
        runner = FakeRunner(completed())
        publication = self.adapter("y8").publish(self.release("y8").job(
            live=True, confirmed=True, run_process=runner,
            entry=entry("DRAFT", [("PENDING_REVIEW", "REJECTED"), ("REJECTED", "DRAFT")],
                        other_ids={"next_request_after": "2099-01-01T00:00:00Z"})))
        self.assertEqual((publication.outcome, publication.human_reason),
                         (outcomes.HUMAN_REQUIRED, "platform-rejection"), publication.message)
        self.assertIn("2099-01-01T00:00:00Z", publication.message)
        self.assertEqual(runner.flows, [])

    def test_crazygames_never_clicks_full_launch(self):
        profile = overlay(pub.load_publication_profile("crazygames"), "http://127.0.0.1:1")
        flow = profile["submission"]["flow"]
        self.assertFalse([i for i in flow if "full launch" in json.dumps(
            [i.get("target"), i.get("names")]).casefold()])
        flow.append({"id": "launch.full", "phase": "save_draft", "class": "reversible",
                     "action": "click", "target": [{"role": "button", "name": "Request Full Launch"}]})
        runner = FakeRunner(completed())
        publication = self.adapter("crazygames", profile=profile).publish(
            self.release("crazygames").job(live=True, run_process=runner))
        self.assertEqual(publication.outcome, outcomes.BLOCKED)
        self.assertIn("CrazyGames' decision", publication.message)
        self.assertEqual(runner.flows, [])

    def test_crazygames_basic_launch_is_live_and_says_full_launch_is_theirs(self):
        publication, _ = self.run_fake(
            "crazygames", completed(status_text="Basic Launch", already_requested=True),
            live=True, confirmed=True, identity={"portal_game_id": "g1"},
            entry=entry("PENDING_REVIEW", game_id="g1"))
        self.assertEqual((publication.outcome, publication.state), (outcomes.VERIFIED, "live"))
        self.assertIn("Full Launch is CrazyGames' decision", publication.message)

    def test_crazygames_hands_the_files_shape_the_package_s_files(self):
        adapter = self.adapter("crazygames")
        intents = adapter.intents(self.release("crazygames").job())[0]
        files = next(i for i in intents if i["id"] == "upload.files")
        self.assertEqual(sorted(f["name"] for f in files["files"]), ["assets/game.js", "index.html"])
        zipped = next(i for i in intents if i["id"] == "upload.zip")
        self.assertEqual([f["name"] for f in zipped["files"]], ["crazygames.zip"])
        publication, _ = self.run_fake("crazygames", completed(
            absent=["upload.zip", "upload.files"]), live=True)
        self.assertEqual((publication.outcome, publication.uploaded),
                         (outcomes.UNKNOWN, False), publication.message)

    def test_y8_without_a_studio_is_a_person_s_act(self):
        result = stopped("drift", "find_game", "no rung matches")
        result.update(outcome="drift", stop={"phase": "find_game", "intent": "studio.check",
                                             "class": "reversible", "code": "drift",
                                             "reason": "no rung matches", "resolution": "stop"})
        publication, _ = self.run_fake("y8", result, live=True)
        self.assertEqual((publication.outcome, publication.human_reason),
                         (outcomes.HUMAN_REQUIRED, "legal"), publication.message)
        self.assertIn("permanent once published", publication.message)

    def test_gamedistribution_needs_its_prerequisites_and_the_game_id(self):
        runner = FakeRunner(completed())
        release = self.release("gamedistribution")
        adapter = PORTALS["gamedistribution"]("gamedistribution",
                                              pub.load_publication_profile("gamedistribution"),
                                              {"prerequisites_confirmed": ["self-hosting"]})
        publication = adapter.publish(release.job(live=True, run_process=runner,
                                                  identity={"config_game_id": GD_GAME_ID}))
        self.assertEqual((publication.outcome, publication.human_reason),
                         (outcomes.HUMAN_REQUIRED, "legal"), publication.message)
        self.assertIn("developer-account", publication.message)
        self.assertIn("developer-terms", publication.message)
        publication = self.adapter("gamedistribution").publish(
            release.job(live=True, run_process=runner, identity={}))
        self.assertEqual((publication.outcome, publication.human_reason),
                         (outcomes.HUMAN_REQUIRED, "manual-submission"), publication.message)
        self.assertIn("game.config.yaml", publication.message)
        self.assertEqual(runner.flows, [])

    def test_gamepix_without_its_sdk_is_blocked_before_the_dashboard(self):
        runner = FakeRunner(completed())
        publication = self.adapter("gamepix").publish(
            self.release("gamepix", sdk=False).job(live=True, run_process=runner))
        self.assertEqual(publication.outcome, outcomes.BLOCKED)
        self.assertIn("HUMAN_ACTION_REQUIRED", publication.message)
        self.assertIn("template", publication.message)
        self.assertEqual(runner.flows, [])
        carried = self.adapter("gamepix").carries_sdk(self.release("gamepix", sdk=True).job())
        self.assertEqual(carried, (True, "index.html references gamepix.sdk.js"))

    def test_human_handoffs_name_what_the_person_does(self):
        cases = {"yandex": ("declare.age_rating", "age rating"),
                 "crazygames": ("declare.launch_options", "Progress Save"),
                 "y8": ("declare.payout", "YMP"),
                 "gamedistribution": ("declare.preroll", "pre-roll"),
                 "gamepix": ("declare.ai", "generative AI")}
        for pid, (iid, words) in cases.items():
            with self.subTest(pid=pid):
                publication, _ = self.run_fake(pid, completed(human_fields=[
                    {"id": iid, "note": "x", "url": None, "done": False}]), live=True,
                    identity={"config_game_id": GD_GAME_ID, "config_app_id": "a"})
                self.assertEqual(publication.outcome, outcomes.HUMAN_REQUIRED, publication.message)
                self.assertIn(words, publication.message)


# -- each adapter through the real executor, against its fixture flavor (opt-in) ------------------

@unittest.skipUnless(enabled("WGF_PUBLISH_BROWSER_TEST"),
                     "set WGF_PUBLISH_BROWSER_TEST=1 to drive the fixture portal with Chromium")
class Browser(PortalCase):
    """The real runner, in the pinned template's checkout, headless, against portal.py's
    flavor of each portal; the test plays the person. Nothing leaves 127.0.0.1."""

    @classmethod
    def setUpClass(cls):
        from wgflib import template
        cls.template = template.checkout()
        template.ensure_dependencies(cls.template)

    def setUp(self):
        super().setUp()
        self.human = os.path.join(self.tmp, "human.mjs")
        with open(self.human, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(HUMAN_JS)
        self.visits = 0

    def portal(self, flavor, *modes, seed=None):
        env = dict(os.environ, PORTAL_FLAVOR=flavor, PORTAL_MODE=",".join(modes))
        if seed:
            env["PORTAL_SEED"] = json.dumps(seed)
        process = subprocess.Popen([sys.executable, PORTAL, "--port", "0"], stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, text=True, env=env)

        def stop():
            process.kill()
            process.wait(timeout=10)
            process.stdout.close()
        self.addCleanup(stop)
        line = process.stdout.readline().strip()
        self.assertTrue(line.startswith("PORT "), line)
        self.base = f"http://127.0.0.1:{int(line.split()[1])}"
        self.pid = flavor
        self.rel = self.release(flavor, sdk=flavor == "gamepix")
        return self.base

    def state(self):
        with urllib.request.urlopen(f"{self.base}/state.json") as response:
            return json.load(response)

    def portal_did(self, **change):
        request = urllib.request.Request(f"{self.base}/test/game", data=json.dumps(change).encode(),
                                         method="POST", headers={"Content-Type": "application/json"})
        urllib.request.urlopen(request).close()

    def visit(self, *, live=False, confirmed=False, track=False, identity=None, entry_=None,
              settings=None, required=None):
        self.visits += 1
        profile = overlay(pub.load_publication_profile(self.pid), self.base)
        adapter = self.adapter(self.pid, dict({
            "console_url": self.base + "/console", "test_headless": True,
            "test_human": self.human, "poll_ms": 250, "login_timeout_s": 30}, **(settings or {})),
            profile=profile)
        job = self.rel.job(live=live, confirmed=confirmed, track=track, identity=identity,
                           checkout=self.template, console_url=self.base + "/console",
                           visit=f"{self.visits}-1", entry=entry_, required=required)
        publication = adapter.publish(job)
        if publication.actions_log:
            with open(os.path.join(self.rel.run_dir, publication.actions_log), encoding="utf-8") as h:
                for line in h:
                    self.assertIs(json.loads(line)["adaptive"], False)
        return publication

    def game(self):
        return self.state()["games"][-1]

    # Yandex ------------------------------------------------------------------------------------

    def test_yandex(self):
        self.portal("yandex")
        dry = self.visit()
        self.assertEqual(dry.outcome, outcomes.DRY_RUN, dry.message)
        self.assertEqual(self.state()["creates"], 0)
        first = self.visit(live=True)
        self.assertEqual(first.outcome, outcomes.UPLOAD_COMPLETE, first.message)
        game = self.game()
        self.assertEqual((game["status"], game["build"]["filename"]), ("Created", "yandex.zip"))
        self.assertEqual(game["listing"]["title[ru]"], TITLE)
        self.assertEqual(game["listing"]["how_to_play[ru]"], LISTING["ru"]["controls"])
        self.assertEqual(game["listing"]["description[en]"], LISTING["en"]["long_description"])
        self.assertEqual(game["media"]["screenshots"], ["shot-1.png", "shot-2.png"])
        self.assertEqual(self.state()["requests"], 0)
        ident = {"portal_game_id": first.draft_id}
        second = self.visit(live=True, confirmed=True, identity=ident,
                            entry_=entry("DRAFT", game_id=first.draft_id))
        self.assertEqual((second.outcome, second.status_text),
                         (outcomes.SUBMITTED, "Waiting for moderation"), second.message)
        self.assertEqual(self.state()["requests"], 1)
        # A second moderation is refused: nothing uploads over the running one, nothing
        # requests again.
        again = self.visit(live=True, identity=ident, entry_=entry("PENDING_REVIEW",
                                                                   game_id=first.draft_id))
        self.assertEqual((again.outcome, again.human_reason),
                         (outcomes.UNKNOWN, "review-pending"), again.message)
        self.assertIn("one moderation per game", again.message)
        confirm = self.visit(live=True, confirmed=True, identity=ident,
                             entry_=entry("PENDING_REVIEW", game_id=first.draft_id))
        self.assertEqual((confirm.outcome, confirm.submitted), (outcomes.SUBMITTED, False))
        state = self.state()
        self.assertEqual((state["uploads"], state["requests"], state["double_requests"]), (1, 1, 0))
        # Moderation passed with Postpone publication: Verified, and Publish is a person's.
        self.portal_did(id=first.draft_id, status="Verified")
        verified = self.visit(live=True, confirmed=True, identity=ident,
                              entry_=entry("PENDING_REVIEW", game_id=first.draft_id))
        self.assertEqual((verified.outcome, verified.human_reason),
                         (outcomes.HUMAN_REQUIRED, "manual-submission"), verified.message)
        self.assertEqual(verified.registry["status"], "VERIFIED")
        self.assertEqual((self.state()["publish_clicks"], self.state()["requests"]), (0, 1))

    def test_yandex_update_of_a_live_game_goes_through_create_draft(self):
        self.portal("yandex", seed=[{"id": "g0500", "title": TITLE, "status": "Published",
                                     "live": True, "build": {"filename": "old.zip"}}])
        publication = self.visit(live=True, identity={"portal_game_id": "g0500"},
                                 entry_=entry("PUBLISHED", game_id="g0500"))
        self.assertEqual(publication.outcome, outcomes.UPLOAD_COMPLETE, publication.message)
        self.assertIn("the live version stays up", publication.message)
        state = self.state()
        self.assertEqual((state["draft_creates"], state["creates"], state["uploads"]), (1, 0, 1))
        self.assertTrue(self.game()["live"])

    # CrazyGames --------------------------------------------------------------------------------

    def test_crazygames(self):
        self.portal("crazygames")
        dry = self.visit()
        self.assertEqual(dry.outcome, outcomes.DRY_RUN, dry.message)
        first = self.visit(live=True)
        self.assertEqual(first.outcome, outcomes.UPLOAD_COMPLETE, first.message)
        self.assertIn("uploaded as zip", first.message)
        game = self.game()
        self.assertEqual((game["title"], game["build"]["filename"]), (TITLE, "crazygames.zip"))
        self.assertEqual(game["listing"]["controls"], LISTING["en"]["controls"])
        ident = {"portal_game_id": first.draft_id}
        second = self.visit(live=True, confirmed=True, identity=ident,
                            entry_=entry("DRAFT", game_id=first.draft_id))
        self.assertEqual((second.outcome, second.status_text), (outcomes.SUBMITTED, "In review"),
                         second.message)
        # CrazyGames runs QA and puts the game in Basic Launch; Full Launch is theirs.
        self.portal_did(id=first.draft_id, status="Basic Launch")
        launched = self.visit(live=True, confirmed=True, identity=ident,
                              entry_=entry("PENDING_REVIEW", game_id=first.draft_id))
        self.assertEqual((launched.outcome, launched.state), (outcomes.VERIFIED, "live"),
                         launched.message)
        self.assertIn("Full Launch is CrazyGames' decision", launched.message)
        state = self.state()
        self.assertEqual((state["full_launch_clicks"], state["requests"]), (0, 1))

    def test_crazygames_takes_the_build_as_files_when_that_is_its_widget(self):
        self.portal("crazygames", "files-upload")
        publication = self.visit(live=True)
        self.assertEqual(publication.outcome, outcomes.UPLOAD_COMPLETE, publication.message)
        self.assertIn("uploaded as files", publication.message)
        self.assertEqual(sorted(self.game()["build"]["files"]), ["game.js", "index.html"])

    # Y8 ----------------------------------------------------------------------------------------

    def test_y8_without_a_studio_stops_for_a_person(self):
        self.portal("y8", "no-studio")
        publication = self.visit(live=True)
        self.assertEqual((publication.outcome, publication.human_reason),
                         (outcomes.HUMAN_REQUIRED, "legal"), publication.message)
        self.assertEqual(self.state()["creates"], 0)

    def test_y8(self):
        self.portal("y8")
        dry = self.visit()
        self.assertEqual(dry.outcome, outcomes.DRY_RUN, dry.message)
        issued = self.visit(live=True, required=["external_game_id", "app_id"])
        self.assertEqual(issued.outcome, outcomes.IDS_ISSUED, issued.message)
        game = self.game()
        self.assertEqual(issued.created_ids, {"external_game_id": game["id"], "app_id": game["app_id"]})
        self.assertEqual(self.state()["uploads"], 0)
        ident = {"portal_game_id": game["id"], "config_game_id": game["id"],
                 "config_app_id": game["app_id"]}
        held = entry("DRAFT_CREATED", game_id=game["id"])
        first = self.visit(live=True, identity=ident, entry_=held)
        self.assertEqual(first.outcome, outcomes.UPLOAD_COMPLETE, first.message)
        self.assertEqual(self.game()["listing"]["instructions"], LISTING["en"]["controls"])
        second = self.visit(live=True, confirmed=True, identity=ident, entry_=held)
        self.assertEqual((second.outcome, second.status_text), (outcomes.SUBMITTED, "Pending"),
                         second.message)
        # Rejected, with feedback in the Feedback tab: read, recorded, nothing re-requested.
        self.portal_did(id=game["id"], status="Rejected", feedback="Ads overlap the HUD.")
        rejected = self.visit(live=True, confirmed=True, identity=ident,
                              entry_=entry("PENDING_REVIEW", game_id=game["id"]))
        self.assertEqual(rejected.outcome, outcomes.REJECTED, rejected.message)
        self.assertIn("Ads overlap the HUD.", rejected.message)
        self.assertEqual(rejected.registry["other_ids"]["rejections"], "1")
        self.assertEqual((self.state()["requests"], self.state()["double_requests"]), (1, 0))

    # GameDistribution --------------------------------------------------------------------------

    def test_gamedistribution(self):
        self.portal("gamedistribution", seed=[{"id": GD_GAME_ID, "title": TITLE, "status": "Draft"}])
        unconfirmed = self.visit(live=True, identity={"config_game_id": GD_GAME_ID},
                                 settings={"prerequisites_confirmed": []})
        self.assertEqual((unconfirmed.outcome, unconfirmed.human_reason),
                         (outcomes.HUMAN_REQUIRED, "legal"), unconfirmed.message)
        self.assertEqual(self.state()["logins"], 0, "the panel is not contacted")
        ident = {"config_game_id": GD_GAME_ID}
        dry = self.visit(identity=ident)
        self.assertEqual(dry.outcome, outcomes.DRY_RUN, dry.message)
        first = self.visit(live=True, identity=ident)
        self.assertEqual(first.outcome, outcomes.UPLOAD_COMPLETE, first.message)
        self.assertEqual(first.found_game["source"], "config:game_id")
        self.assertEqual((self.state()["creates"], self.state()["uploads"]), (0, 1))
        self.assertEqual(self.game()["listing"]["instructions"], LISTING["en"]["controls"])
        held = entry("DRAFT", game_id=GD_GAME_ID)
        confirm = self.visit(live=True, confirmed=True, identity=ident, entry_=held)
        self.assertEqual((confirm.outcome, confirm.human_reason),
                         (outcomes.HUMAN_REQUIRED, "manual-submission"), confirm.message)
        self.assertIn("designated button", confirm.message)
        self.assertEqual(self.state()["requests"], 0)
        # The person clicks the panel's button; the next visit reads Pending.
        self.portal_did(id=GD_GAME_ID, status="Pending", requested=True)
        read = self.visit(live=True, confirmed=True, identity=ident, entry_=held)
        self.assertEqual((read.outcome, read.status_text, read.submitted),
                         (outcomes.SUBMITTED, "Pending", False), read.message)

    # GamePix -----------------------------------------------------------------------------------

    def test_gamepix(self):
        self.portal("gamepix")
        self.rel = self.release("gamepix", sdk=False)
        blocked = self.visit(live=True)
        self.assertEqual(blocked.outcome, outcomes.BLOCKED, blocked.message)
        self.assertIn("HUMAN_ACTION_REQUIRED", blocked.message)
        self.assertEqual(self.state()["logins"] + self.state()["creates"], 0)
        self.rel = self.release("gamepix", sdk=True)
        dry = self.visit()
        self.assertEqual(dry.outcome, outcomes.DRY_RUN, dry.message)
        first = self.visit(live=True)
        self.assertEqual(first.outcome, outcomes.UPLOAD_COMPLETE, first.message)
        self.assertEqual(self.game()["build"]["filename"], "gamepix.zip")
        ident = {"portal_game_id": first.draft_id}
        held = entry("DRAFT", game_id=first.draft_id)
        confirm = self.visit(live=True, confirmed=True, identity=ident, entry_=held)
        self.assertEqual((confirm.outcome, confirm.human_reason),
                         (outcomes.HUMAN_REQUIRED, "manual-submission"), confirm.message)
        self.portal_did(id=first.draft_id, status="In review", requested=True)
        read = self.visit(live=True, confirmed=True, identity=ident, entry_=held)
        self.assertEqual((read.outcome, read.status_text), (outcomes.SUBMITTED, "In review"),
                         read.message)

    def test_gamepix_declarations_are_the_person_s(self):
        self.portal("gamepix", "undeclared")
        publication = self.visit(live=True)
        self.assertEqual((publication.outcome, publication.human_reason),
                         (outcomes.HUMAN_REQUIRED, "legal"), publication.message)
        self.assertIn("Allow Distribution", publication.message)
        self.assertIn("DISCLOSED", publication.message)
        self.assertEqual(self.state()["requests"], 0)


if __name__ == "__main__":
    unittest.main()

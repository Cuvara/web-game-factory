"""The profile-driven console executor (scripts/wgf_publish/adapters/console.py and
browser/console.spec.ts): how a flow is resolved from the job, how every runner result maps
to an outcome and the interface fields, and - opt-in - real headless Chromium against the
fixture portal with the test playing the person who logs in.

    python -m unittest scripts/tests/test_publish_executor.py
    WGF_PUBLISH_BROWSER_TEST=1 python -m unittest scripts/tests/test_publish_executor.py

No test contacts a real portal, and nothing here (or anywhere) saves a browser session.
"""

import copy
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, HERE)

from testenv import enabled  # noqa: E402
from campaign_fixture import write_campaign  # noqa: E402
from wgf_publish import outcomes  # noqa: E402
from wgf_publish import browser as browser_module  # noqa: E402
from wgf_publish.adapters import ConsoleAdapter, Job, resolve  # noqa: E402
from wgf_publish.adapters.console import job_identity, resolve_value  # noqa: E402
from wgf_publish.adapters.fixture import FixturePortalAdapter  # noqa: E402
from wgf_publish.session import CredentialError, StorageState, read_credential  # noqa: E402
from wgflib import redact  # noqa: E402
from wgflib.procs import ProcessResult  # noqa: E402
from wgflib.yamllite import load_file  # noqa: E402

FIXTURES = os.path.join(HERE, "fixtures", "publish")
PORTAL = os.path.join(FIXTURES, "portal.py")
PROFILE = os.path.join(FIXTURES, "publication", "generic-web.yaml")
SPEC = os.path.join(SCRIPTS, "wgf_publish", "browser", "console.spec.ts")
PASSWORD = "correct-horse-battery-staple-42"
OTP = "493017"
TITLE = "Fixture Game"
LISTING = {
    "en": {"title": TITLE, "short_description": "Merge towers.",
           "long_description": "Merge matching towers to build stronger ones.",
           "controls": "Drag to merge.", "tags": ["merge", "casual"], "categories": ["Puzzle"]},
    "ru": {"title": TITLE, "short_description": "Объединяй башни.",
           "long_description": "Объединяй одинаковые башни, строй сильнее.",
           "controls": "Перетащи.", "tags": ["слияние"], "categories": ["Головоломки"]},
}
PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00"
       b"\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N"
       b"\x00\x00\x00\x00IEND\xaeB`\x82")
# The test's stand-in for the person, loaded by the runner only headless: logs in, answers the
# CAPTCHA, types the one-time code - in the window, as a person would. The executor never does.
HUMAN_JS = """\
export default async function human(page, context, why) {
  await new Promise((r) => setTimeout(r, 300));
  if (why.kind === "login") {
    if (!page.url().includes("/login")) await page.goto(new URL("/login", page.url()).toString());
    await page.fill("input[name=user]", "dev.person");
    await page.fill("input[name=password]", "%(password)s");
    await page.click("text=Log in");
  } else if (why.kind === "captcha") {
    await page.click("text=I am human");
  } else if (why.kind === "two-factor") {
    await page.fill("#code", "%(otp)s");
    await page.click("text=Verify");
  }
}
""" % {"password": PASSWORD, "otp": OTP}


def fixture_profile(base="http://127.0.0.1:1"):
    profile = load_file(PROFILE)
    profile["submission"]["console"]["url"] = base + "/"
    profile["submission"]["console"]["allowed_origins"] = [base]
    return profile


class Release:
    """A release directory: the package, the store metadata's media, the listing copy."""

    def __init__(self, root):
        self.root = root
        self.release_dir = os.path.join(root, "release", "r1")
        self.run_dir = os.path.join(root, "run")
        os.makedirs(os.path.join(self.release_dir, "listing"), exist_ok=True)
        os.makedirs(self.run_dir, exist_ok=True)
        self.package = os.path.join(self.release_dir, "generic-web.zip")
        with open(self.package, "wb") as handle:
            handle.write(b"PK\x05\x06" + b"\0" * 18)
        # The shipped campaign: the rendition's icon.png, cover.png, shot-1.png, shot-2.png
        # under listing/platforms/generic-web/, the canonical captures beside them.
        self.canonical, self.rendition = write_campaign(self.release_dir, "generic-web",
                                                        text=LISTING)
        self.metadata = {"title": TITLE, "descriptions": {"en": "A fixture."},
                         "locales_included": ["en", "ru"]}

    def job(self, *, live=False, confirmed=False, identity=None, checkout=None, console_url=None,
            run_process=None, timeouts=None, hooks=None, logger=None, visit="1-1", listing=None):
        job = Job(platform_id="generic-web", release_id="r1",
                  idempotency_key="wgf-generic-web-0123456789abcdef",
                  package_path=self.package,
                  package={"filename": "generic-web.zip", "size_mb": 0.01,
                           "checksum": "sha256:" + "0" * 64},
                  metadata=self.metadata, checkout=checkout or self.root,
                  release_dir=self.release_dir, run_dir=self.run_dir,
                  scratch_dir=os.path.join(self.run_dir, "submit", visit), submit=live,
                  env=dict(os.environ), hooks=hooks or {}, logger=logger,
                  timeouts=timeouts or {"action": 2500, "navigation": 8000, "upload": 20000},
                  console_url=console_url, run_process=run_process,
                  listing=LISTING if listing is None else listing, platform_profile={})
        job.submit_confirmed = confirmed
        job.identity = dict(identity or {})
        return job


class FakeRunner:
    """Stands in for `pnpm exec playwright test`: records the flow, writes `result`, prints
    the state markers and appends `actions` to the flow's actions.jsonl."""

    def __init__(self, result=None, actions=(), states=(), no_browser=False):
        self.result, self.actions, self.states = result, list(actions), list(states)
        self.no_browser = no_browser
        self.flows = []
        self.calls = []

    def __call__(self, argv, cwd=None, timeout=None, env=None, log_path=None,
                 stderr_to_stdout=False, on_output=None, **hooks):
        with open(env["WGF_PUBLISH_FLOW"], encoding="utf-8") as handle:
            flow = json.load(handle)
        self.flows.append(flow)
        self.calls.append({"argv": argv, "cwd": cwd, "hooks": hooks, "env": env})
        if self.no_browser:
            return ProcessResult(argv, returncode=1, stdout="browserType.launch: Executable doesn't exist")
        for state in self.states:
            line = browser_module.STATE_MARKER + json.dumps(state)
            if on_output:
                on_output("stdout", line)
        if self.actions:
            os.makedirs(os.path.dirname(flow["actions_log"]), exist_ok=True)
            with open(flow["actions_log"], "a", encoding="utf-8") as handle:
                for action in self.actions:
                    handle.write(json.dumps(action) + "\n")
        if self.result is not None:
            with open(env["WGF_PUBLISH_RESULT"], "w", encoding="utf-8") as handle:
                json.dump(self.result, handle)
        return ProcessResult(argv, returncode=0, stdout="1 passed")


def completed(**extra):
    base = {"outcome": "completed", "stop": None, "phase_reached": "verify", "phases": {},
            "found_game": None, "created": True, "created_ids": {}, "game_id": "g0001",
            "uploaded": True, "saved": True, "request_attempted": False, "requested": False,
            "already_requested": False, "status_before": None, "status_text": "Draft",
            "human_fields": [{"id": "declare.ownership", "note": "x", "url": None, "done": True}],
            "absent": [], "login_handoffs": [], "refused": [], "errors": [], "actions": 0}
    base.update(extra)
    return base


def stopped(code, phase, reason="why", **extra):
    return completed(outcome="stopped", stop={"phase": phase, "code": code, "reason": reason,
                                              **extra.pop("stop_extra", {})},
                     phase_reached=extra.pop("reached", None), uploaded=False, saved=False,
                     **extra)


class ExecutorCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="wgf-executor-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.addCleanup(redact.forget)
        self.release = Release(self.tmp)
        self.profile = fixture_profile()

    def adapter(self, settings=None, profile=None):
        return FixturePortalAdapter("generic-web", profile or self.profile,
                                    dict({"console_url": "http://127.0.0.1:1/"}, **(settings or {})))

    def run_fake(self, result, *, live=False, confirmed=False, actions=(), states=(), identity=None,
                 adapter=None, **job):
        runner = FakeRunner(result, actions, states)
        publication = (adapter or self.adapter()).publish(
            self.release.job(live=live, confirmed=confirmed, identity=identity,
                             run_process=runner, **job))
        return publication, runner


# -- the flow the runner gets ------------------------------------------------------------------

class Flow(ExecutorCase):
    def flow(self, **job):
        runner = FakeRunner(completed())
        self.adapter().publish(self.release.job(run_process=runner, **job))
        return runner.flows[0]

    def test_values_come_from_the_job_and_per_locale_intents_expand(self):
        flow = self.flow()
        by_id = {}
        for intent in flow["intents"]:
            by_id.setdefault(intent["id"], []).append(intent)
        self.assertEqual([i["locale"] for i in by_id["field.description"]], ["en", "ru"])
        ru = by_id["field.description"][1]
        self.assertEqual(ru["value"], LISTING["ru"]["long_description"])
        self.assertEqual(ru["target"][0], {"label": "Description (ru)"})
        self.assertEqual(ru["expect"]["value_equals"], LISTING["ru"]["long_description"])
        self.assertTrue(ru["value_public"])
        self.assertEqual(by_id["create.name"][0]["value"], TITLE)
        archive = by_id["upload.archive"][0]
        self.assertNotIn("value", archive)
        self.assertEqual(archive["files"][0]["name"], "generic-web.zip")
        self.assertTrue(archive["files"][0]["sha256"].startswith("sha256:"))
        shots = by_id["media.screenshots"][0]
        self.assertEqual([f["name"] for f in shots["files"]], ["shot-1.png", "shot-2.png"])
        self.assertTrue(shots["multiple"])
        self.assertEqual(by_id["review.request"][0]["expect"]["status_in"], ["Waiting for moderation"])
        self.assertEqual([i["id"] for i in flow["intents"] if i["class"] == "human"],
                         ["declare.ownership", "declare.age_rating"])

    def test_the_session_is_never_stored_and_the_browser_is_headed_for_a_real_portal(self):
        flow = self.flow()
        text = json.dumps(flow)
        self.assertNotIn("storage", text.lower())
        self.assertNotIn("cookie", text.lower())
        adapter = ConsoleAdapter("generic-web", self.profile,
                                 {"console_url": "http://127.0.0.1:1/", "test_headless": True,
                                  "test_human": "human.mjs"})
        self.assertEqual(adapter.browser_mode(None), (False, None))
        self.assertEqual(self.adapter({"test_human": "h.mjs"}).browser_mode(None), (False, None))
        self.assertEqual(self.adapter({"test_headless": True, "test_human": "h.mjs"}).browser_mode(None),
                         (True, "h.mjs"))
        with open(browser_module.SPEC, encoding="utf-8") as handle:
            source = handle.read()
        self.assertIn("browser.newContext(); // fresh: no storage state in, none out", source)
        self.assertNotRegex(source, r"storageState|addCookies|\.cookies\(|launchPersistentContext")
        self.assertNotRegex(source, re.compile(r"\.fill\([^)]*password", re.I))

    def test_the_candidates_follow_the_profile_order_and_the_build_ids(self):
        flow = self.flow(identity={"portal_game_id": "g0042", "config_game_id": "G-1",
                                   "config_app_id": "A-1"})
        self.assertEqual([c["source"] for c in flow["identity"]["candidates"]],
                         ["registry", "config:game_id", "config:app_id", "idempotency-key", "title"])
        self.assertEqual(flow["identity"]["build_ids"], {"external_game_id": "G-1", "app_id": "A-1"})
        self.assertEqual(flow["identity"]["title"], TITLE)

    def test_modes_dry_run_live_and_confirmed(self):
        dry = self.flow()
        self.assertEqual((dry["mode"], dry["changes_allowed"], dry["submit_confirmed"]),
                         ("dry-run", True, False))  # the fixture's dry run uploads to a draft
        real = ConsoleAdapter("generic-web", self.profile, {"console_url": "http://127.0.0.1:1/"})
        runner = FakeRunner(completed())
        real.publish(self.release.job(run_process=runner))
        self.assertFalse(runner.flows[0]["changes_allowed"])  # a real portal's dry run changes nothing
        self.assertTrue(self.flow(live=True, confirmed=False)["changes_allowed"])
        self.assertFalse(self.flow(live=False, confirmed=True)["submit_confirmed"])
        self.assertTrue(self.flow(live=True, confirmed=True)["submit_confirmed"])

    def test_a_missing_required_value_blocks_before_anything_runs(self):
        shutil.rmtree(os.path.join(self.release.release_dir, "listing"))
        write_campaign(self.release.release_dir, "generic-web", text=LISTING, icon=False,
                       canonical_extra={"branding": {"method": "none", "items": []}})
        publication, runner = self.run_fake(completed())
        self.assertEqual(publication.outcome, outcomes.BLOCKED)
        self.assertIn("media.icon", publication.message)
        self.assertEqual(runner.flows, [])
        # An optional one (the cover) is left out and named.
        shutil.rmtree(os.path.join(self.release.release_dir, "listing"))
        write_campaign(self.release.release_dir, "generic-web", text=LISTING, cover=False)
        publication, runner = self.run_fake(completed())
        self.assertNotIn("media.cover", [i["id"] for i in runner.flows[0]["intents"]])
        self.assertIn("media.cover", publication.evidence[0].summary)

    def test_a_captured_session_is_refused(self):
        profile = copy.deepcopy(self.profile)
        profile["submission"]["credential"] = {"kind": "storage-state", "env": "WGF_X"}
        publication, runner = self.run_fake(completed(), adapter=self.adapter(profile=profile))
        self.assertEqual(publication.outcome, outcomes.BLOCKED)
        self.assertIn("human-login", publication.message)
        with self.assertRaises(CredentialError):
            read_credential(profile, {"env_passthrough": ["WGF_X"]}, {"WGF_X": "{}"})
        live = read_credential(self.profile, {}, {})
        self.assertEqual((live.kind, live.usable, live.value), ("human-login", True, None))
        with StorageState(live, self.tmp) as state:
            self.assertIsNone(state.path)
        self.assertEqual(os.listdir(self.tmp), ["release", "run"])

    def test_resolve_value_never_invents(self):
        job = self.release.job()
        self.assertEqual(resolve_value("listing.text.ru.controls", job), ("text", "Перетащи."))
        self.assertEqual(resolve_value("listing.text.fr.description", job), (None, None))
        self.assertEqual(resolve_value("listing.text.en.tags", job), ("text", "merge, casual"))
        self.assertEqual(resolve_value("listing.media.trailer", job), (None, None))
        self.assertEqual(resolve_value("manifest.package.filename", job), ("text", "generic-web.zip"))
        self.assertEqual(resolve_value("identity.app_id", job), (None, None))
        self.assertEqual(job_identity(job)["title"], TITLE)


# -- the runner's result, mapped -----------------------------------------------------------------

class Mapping(ExecutorCase):
    def test_dry_run(self):
        publication, _ = self.run_fake(completed())
        self.assertEqual(publication.outcome, outcomes.DRY_RUN)
        self.assertEqual((publication.uploaded, publication.saved, publication.phase_reached),
                         (True, True, "verify"))
        publication, _ = self.run_fake(stopped("dry-run", "create_game", "dry run: would create"))
        self.assertEqual(publication.outcome, outcomes.DRY_RUN)
        self.assertIn("would upload generic-web.zip", publication.message)

    def test_live_upload_is_upload_complete_and_nothing_is_submitted(self):
        publication, _ = self.run_fake(completed(), live=True)
        self.assertEqual(publication.outcome, outcomes.UPLOAD_COMPLETE)
        self.assertEqual(outcomes.waiting_state_for(publication.outcome),
                         outcomes.WAITING_FOR_HUMAN_SUBMIT_CONFIRMATION)
        self.assertEqual(publication.human_reason, "submit-confirmation")
        self.assertFalse(publication.submitted)
        self.assertEqual((publication.draft_id, publication.uploaded, publication.saved),
                         ("g0001", True, True))
        publication, _ = self.run_fake(completed(saved=False), live=True)
        self.assertEqual((publication.outcome, publication.human_reason),
                         (outcomes.UNKNOWN, "ambiguous-portal-state"))

    def test_confirmed_request_reads_the_status_back(self):
        found = {"id": "g0007", "title": TITLE, "status_text": "Draft", "source": "registry"}
        cases = (
            (completed(requested=True, status_text="Waiting for moderation", found_game=found,
                       game_id=None, uploaded=False, saved=False), outcomes.SUBMITTED, True),
            (completed(already_requested=True, status_text="Waiting for moderation",
                       found_game=found, game_id=None), outcomes.SUBMITTED, False),
            (completed(requested=True, status_text="Live", found_game=found, game_id=None), outcomes.VERIFIED, True),
            (completed(requested=True, status_text="Rejected", found_game=found), outcomes.REJECTED, True),
            (completed(requested=True, status_text="Processing", found_game=found), outcomes.UNKNOWN, True),
        )
        for result, expected, submitted in cases:
            with self.subTest(result["status_text"]):
                publication, _ = self.run_fake(result, live=True, confirmed=True)
                self.assertEqual(publication.outcome, expected, publication.message)
                if expected in (outcomes.SUBMITTED, outcomes.VERIFIED):
                    self.assertEqual(publication.submitted, submitted)
                    self.assertEqual(publication.draft_id, "g0007")
                    self.assertTrue(publication.found_existing)

    def test_human_fields_are_declaration_or_legal(self):
        pending = [{"id": "declare.ownership", "note": "Ownership", "url": "http://x/console", "done": False}]
        publication, _ = self.run_fake(completed(human_fields=pending), live=True)
        self.assertEqual((publication.outcome, publication.human_reason),
                         (outcomes.HUMAN_REQUIRED, "declaration"))
        self.assertIn("declare.ownership", publication.message)
        legal = [{"id": "declare.payout", "note": "Tax and payout details", "url": None, "done": False}]
        publication, _ = self.run_fake(completed(human_fields=legal), live=True, confirmed=True)
        self.assertEqual(publication.human_reason, "legal")
        # A dry run names them without stopping.
        publication, _ = self.run_fake(completed(human_fields=pending))
        self.assertEqual(publication.outcome, outcomes.DRY_RUN)
        self.assertIn("a person must still", publication.message)

    def test_stops(self):
        cases = (
            ("duplicate-candidate", "find_game", outcomes.UNKNOWN, "duplicate-candidate"),
            ("review-pending", "status_gate", outcomes.UNKNOWN, "review-pending"),
            ("ambiguous-portal-state", "find_game", outcomes.UNKNOWN, "ambiguous-portal-state"),
            ("ids-issued", "create_game", outcomes.IDS_ISSUED, None),
            ("portal-error", "upload_build", outcomes.PLATFORM_ERROR, None),
            ("invalid-media", "upload_media", outcomes.INVALID_METADATA, None),
            ("manual-create", "create_game", outcomes.HUMAN_REQUIRED, "manual-submission"),
            ("action-failed", "fill_metadata", outcomes.RETRYABLE_FAILURE, None),
        )
        for code, phase, expected, reason in cases:
            with self.subTest(code):
                publication, _ = self.run_fake(stopped(code, phase), live=True)
                self.assertEqual(publication.outcome, expected, publication.message)
                if reason:
                    self.assertEqual(publication.human_reason, reason)
        found = {"id": "g0900", "title": TITLE, "status_text": "Draft", "source": "title"}
        publication, _ = self.run_fake(stopped("duplicate-candidate", "find_game", found_game=found),
                                       live=True)
        self.assertEqual(publication.found_game["id"], "g0900")
        self.assertFalse(publication.found_existing)
        ids = {"external_game_id": "g0003", "app_id": "app-4004"}
        publication, _ = self.run_fake(stopped("ids-issued", "create_game", created_ids=ids,
                                               game_id="g0003"), live=True)
        self.assertEqual(publication.created_ids, ids)
        self.assertEqual(outcomes.to_result(publication.outcome, [], "m", platform_id="generic-web").route,
                         "platform-ids")
        # A failed action after the review request was attempted is never retried.
        publication, _ = self.run_fake(stopped("action-failed", "request_review",
                                               request_attempted=True), live=True, confirmed=True)
        self.assertEqual(publication.outcome, outcomes.UNKNOWN)

    def test_drift(self):
        reversible = completed(outcome="drift", stop={"phase": "fill_metadata", "intent": "field.title",
                                                      "class": "reversible", "code": "drift",
                                                      "reason": "nothing matches", "resolution": "stop"})
        publication, _ = self.run_fake(reversible, live=True)
        self.assertEqual((publication.outcome, publication.human_reason),
                         (outcomes.UNKNOWN, "ambiguous-portal-state"))
        self.assertIn("field.title", publication.message)
        irreversible = completed(outcome="drift", stop={"phase": "request_review", "intent": "review.request",
                                                        "class": "irreversible", "code": "drift-irreversible",
                                                        "reason": "nothing matches", "resolution": "stop"})
        publication, _ = self.run_fake(irreversible, live=True, confirmed=True)
        self.assertEqual((publication.outcome, publication.human_reason),
                         (outcomes.UNKNOWN, "drift-irreversible"))

    def test_login_timeout_and_a_closed_window_are_auth_required_not_failures(self):
        handoff = {"at": "2026-10-04T10:00:00Z", "url": "http://127.0.0.1:1/login",
                   "reason": "the console shows its login form", "kind": "login", "phase": "session",
                   "action": "log in in the opened browser window; handle CAPTCHA/2FA yourself",
                   "resume": "the console's authenticated page is detected", "resolved_at": None,
                   "outcome": "timeout"}
        for outcome, code, reason in (("login_timeout", "login", "login"),
                                      ("login_abandoned", "captcha", "captcha")):
            with self.subTest(outcome):
                result = completed(outcome=outcome, stop={"phase": "session", "code": code, "reason": "r"},
                                   login_handoffs=[handoff], uploaded=False, saved=False)
                publication, _ = self.run_fake(result, live=True)
                self.assertEqual(publication.outcome, outcomes.AUTH_REQUIRED)
                self.assertEqual(publication.human_reason, reason)
                self.assertEqual(outcomes.waiting_state_for(publication.outcome),
                                 outcomes.WAITING_FOR_HUMAN_LOGIN)
                self.assertEqual(publication.login_handoffs[0]["url"], handoff["url"])
                step = outcomes.to_result(publication.outcome, [], publication.message,
                                          platform_id="generic-web")
                self.assertEqual(step.outcome.value if hasattr(step.outcome, "value") else str(step.outcome),
                                 "WAITING_FOR_HUMAN")

    def test_state_changes_are_relayed_as_progress_and_logged(self):
        events, logs = [], []

        class Logger:
            def info(self, message, **fields):
                logs.append((message, fields))

        state = {"state": "WAITING_FOR_HUMAN_LOGIN", "portal": "generic-web", "step": "submit",
                 "url": "http://127.0.0.1:1/login", "reason": "the console shows its login form",
                 "action": "log in in the opened browser window; handle CAPTCHA/2FA yourself",
                 "resume": "the console's authenticated page is detected", "at": "2026-10-04T10:00:00Z"}
        hooks = {"on_event": lambda kind, **data: events.append((kind, data))}
        self.run_fake(completed(), states=[state, dict(state, state="AUTHENTICATED")],
                      hooks=hooks, logger=Logger())
        self.assertEqual([e[0] for e in events], ["WAITING_FOR_HUMAN_LOGIN", "AUTHENTICATED"])
        self.assertEqual(events[0][1]["url"], "http://127.0.0.1:1/login")
        self.assertEqual(events[0][1]["action"], state["action"])
        self.assertTrue(logs and "WAITING_FOR_HUMAN_LOGIN" in logs[0][0])

    def test_actions_log_is_scrubbed_and_returned_run_relative(self):
        redact.register("tok-SECRET-0123456789")
        actions = [{"seq": 1, "phase": "fill_metadata", "intent": "field.title",
                    "value": "a tok-SECRET-0123456789 b", "adaptive": False}]
        publication, _ = self.run_fake(completed(), actions=actions)
        self.assertEqual(publication.actions_log, "submit/1-1/actions.jsonl")
        with open(os.path.join(self.release.run_dir, publication.actions_log), encoding="utf-8") as handle:
            text = handle.read()
        self.assertNotIn("tok-SECRET-0123456789", text)

    def test_no_browser_is_blocked_and_no_result_is_a_retryable_failure(self):
        runner = FakeRunner(no_browser=True)
        publication = self.adapter().publish(self.release.job(run_process=runner))
        self.assertEqual(publication.outcome, outcomes.BLOCKED)
        publication, _ = self.run_fake(None)
        self.assertEqual(publication.outcome, outcomes.RETRYABLE_FAILURE)

    def test_generic_console_platforms_resolve_to_the_profile_runner(self):
        adapter = resolve("generic-web", self.profile, {})
        self.assertIs(type(adapter), ConsoleAdapter)
        self.assertIsInstance(resolve("generic-web", self.profile, {"adapter": "fixture-portal"}),
                              FixturePortalAdapter)


# -- real Chromium against the fixture portal (opt-in) -------------------------------------------

@unittest.skipUnless(enabled("WGF_PUBLISH_BROWSER_TEST"),
                     "set WGF_PUBLISH_BROWSER_TEST=1 to drive the fixture portal with Chromium")
class Browser(ExecutorCase):
    """The real runner, in the pinned template's checkout (its Playwright and Chromium),
    headless, against portal.py; the test plays the person. Nothing leaves 127.0.0.1."""

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

    def portal(self, *modes, seed=None, locales=None):
        env = dict(os.environ, PORTAL_MODE=",".join(modes))
        if seed:
            env["PORTAL_SEED"] = json.dumps(seed)
        if locales:
            env["PORTAL_LOCALES"] = locales
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
        self.profile = fixture_profile(self.base)
        return self.base

    def state(self):
        with urllib.request.urlopen(f"{self.base}/state.json") as response:
            return json.load(response)

    def visit(self, *, live=False, confirmed=False, identity=None, human=True, login_timeout_s=30,
              profile=None, visit="1-1", events=None):
        adapter = FixturePortalAdapter("generic-web", profile or self.profile, {
            "console_url": self.base + "/", "test_headless": True,
            "test_human": self.human if human else None, "poll_ms": 250,
            "login_timeout_s": login_timeout_s})
        hooks = {}
        if events is not None:
            hooks["on_event"] = lambda kind, **data: events.append((kind, data))
        job = self.release.job(live=live, confirmed=confirmed, identity=identity,
                               checkout=self.template, console_url=self.base + "/", visit=visit,
                               hooks=hooks)
        publication = adapter.publish(job)
        self.check_actions(publication)
        return publication

    def check_actions(self, publication):
        """actions.jsonl: one line per action and waiting period, nothing secret."""
        if not publication.actions_log:
            return []
        with open(os.path.join(self.release.run_dir, publication.actions_log), encoding="utf-8") as handle:
            text = handle.read()
        for secret in (PASSWORD, OTP, "fixture-session-token-0001"):
            self.assertNotIn(secret, text)
        lines = [json.loads(line) for line in text.splitlines() if line.strip()]
        for line in lines:
            self.assertIs(line["adaptive"], False)
            if line.get("intent"):
                self.assertEqual(line["source"], "profile")
                self.assertIn("result", line)
        return lines

    def no_session_kept(self):
        for root in (self.tmp, self.template):
            for directory, _, files in os.walk(root):
                if "node_modules" in directory:
                    continue
                for name in files:
                    self.assertNotRegex(name, r"storage[-_]?state", os.path.join(directory, name))
        leftovers = [n for n in os.listdir(self.release.release_dir) if n.startswith(".wgf-publish")]
        self.assertEqual(leftovers, [])

    def test_the_person_logs_in_then_the_visit_continues_in_the_same_browser(self):
        self.portal()
        events = []
        publication = self.visit(live=True, events=events)
        self.assertEqual(publication.outcome, outcomes.UPLOAD_COMPLETE, publication.message)
        self.assertEqual(len(publication.login_handoffs), 1)
        handoff = publication.login_handoffs[0]
        self.assertEqual(handoff["url"], self.base + "/login")
        self.assertTrue(handoff["resolved_at"])
        self.assertEqual(handoff["action"], "log in in the opened browser window; handle CAPTCHA/2FA yourself")
        self.assertIn("WAITING_FOR_HUMAN_LOGIN", [e[0] for e in events])
        self.assertIn("AUTHENTICATED", [e[0] for e in events])
        state = self.state()
        self.assertEqual((state["logins"], state["creates"], state["uploads"], state["requests"]), (1, 1, 1, 0))
        lines = self.check_actions(publication)
        waits = [l for l in lines if l.get("action") == "wait-for-human-login"]
        self.assertEqual([w["result"] for w in waits], ["waiting", "resolved"])
        self.assertTrue(all(w["human_intervention"] for w in waits))
        # No screenshot of the login page: every screenshot is of a console page after login.
        first_resolved = waits[-1]["seq"]
        shots = [l for l in lines if (l.get("screenshots") or {}).get("pre") or (l.get("screenshots") or {}).get("post")]
        self.assertTrue(shots)
        self.assertTrue(all(l["seq"] > first_resolved for l in shots))
        self.no_session_kept()

    def test_a_login_on_the_identity_provider_s_origin_is_let_through(self):
        self.portal("sso")
        publication = self.visit(live=True)
        self.assertEqual(publication.outcome, outcomes.UPLOAD_COMPLETE, publication.message)
        handoff = publication.login_handoffs[0]
        self.assertIn("outside the console's allowed origins", handoff["reason"])
        self.assertTrue(handoff["url"].startswith("http://localhost:"), handoff["url"])
        self.assertEqual(self.state()["logins"], 1)

    def test_no_login_within_the_timeout_is_auth_required_waiting_not_a_failure(self):
        self.portal()
        publication = self.visit(live=True, human=False, login_timeout_s=3)
        self.assertEqual(publication.outcome, outcomes.AUTH_REQUIRED, publication.message)
        self.assertEqual(publication.login_handoffs[0]["outcome"], "timeout")
        self.assertEqual(self.state()["creates"], 0)

    def test_a_captcha_and_a_second_factor_mid_flow_wait_for_the_person(self):
        for mode, kind in (("captcha-midflow", "captcha"), ("two-factor-midflow", "two-factor")):
            with self.subTest(mode):
                self.portal("open", mode)
                publication = self.visit(live=True, visit=f"{kind}-1")
                self.assertEqual(publication.outcome, outcomes.UPLOAD_COMPLETE, publication.message)
                self.assertEqual([h["kind"] for h in publication.login_handoffs], [kind])
                self.assertNotEqual(publication.login_handoffs[0]["phase"], "session")
                self.assertEqual(self.state()["challenges"], 1)

    def test_a_duplicate_by_title_stops_and_nothing_is_created(self):
        self.portal("open", seed=[{"id": "g0900", "title": TITLE, "status": "Draft"}])
        publication = self.visit(live=True)
        self.assertEqual((publication.outcome, publication.human_reason),
                         (outcomes.UNKNOWN, "duplicate-candidate"), publication.message)
        self.assertEqual(publication.found_game["id"], "g0900")
        self.assertEqual((self.state()["creates"], self.state()["uploads"]), (0, 0))

    def test_a_pending_review_stops_before_any_upload(self):
        self.portal("open", seed=[{"id": "g0901", "title": TITLE, "status": "Waiting for moderation"}])
        publication = self.visit(live=True, identity={"portal_game_id": "g0901"})
        self.assertEqual((publication.outcome, publication.human_reason),
                         (outcomes.UNKNOWN, "review-pending"), publication.message)
        self.assertEqual(self.state()["uploads"], 0)

    def test_dry_run_reaches_save_draft_and_never_requests(self):
        self.portal("open")
        publication = self.visit(live=False)
        self.assertEqual(publication.outcome, outcomes.DRY_RUN, publication.message)
        state = self.state()
        game = state["games"][0]
        self.assertEqual((state["requests"], game["status"]), (0, "Draft"))
        self.assertEqual(game["build"]["filename"], "generic-web.zip")
        self.assertEqual(game["listing"]["title"], TITLE)
        self.assertEqual(game["listing"]["description[ru]"], LISTING["ru"]["long_description"])
        self.assertEqual(game["media"], {"icon": ["icon.png"], "cover": ["cover.png"],
                                         "screenshots": ["shot-1.png", "shot-2.png"]})
        # Exactly the platform rendition's files (listing/platforms/generic-web/), never the
        # canonical captures they were cut from: the bytes the portal received are theirs.
        rendition = os.path.join(self.release.release_dir, "listing", "platforms", "generic-web")
        self.assertEqual(game["media_sizes"], {
            k: [os.path.getsize(os.path.join(rendition, n)) for n in names]
            for k, names in game["media"].items()})

    def test_live_upload_then_a_confirmed_visit_requests_review_once(self):
        self.portal("open")
        first = self.visit(live=True)
        self.assertEqual(first.outcome, outcomes.UPLOAD_COMPLETE, first.message)
        self.assertEqual(self.state()["requests"], 0)
        identity = {"portal_game_id": first.draft_id}
        second = self.visit(live=True, confirmed=True, identity=identity, visit="2-1")
        self.assertEqual(second.outcome, outcomes.SUBMITTED, second.message)
        self.assertTrue(second.submitted)
        self.assertEqual(second.status_text, "Waiting for moderation")
        state = self.state()
        self.assertEqual((state["requests"], state["uploads"], state["double_requests"]), (1, 1, 0))
        lines = self.check_actions(second)
        clicks = [l for l in lines if l.get("intent") == "review.request"]
        self.assertEqual(len(clicks), 1)
        self.assertEqual(clicks[0]["rung"], "role")
        self.assertEqual(clicks[0]["element"], {"role": "button", "name": "Submit for moderation"})
        # A third confirmed visit reads the request back and clicks nothing.
        third = self.visit(live=True, confirmed=True, identity=identity, visit="3-1")
        self.assertEqual(third.outcome, outcomes.SUBMITTED, third.message)
        self.assertFalse(third.submitted)
        self.assertEqual((self.state()["requests"], self.state()["double_requests"]), (1, 0))

    def test_ids_issued_on_create_stop_before_the_upload(self):
        self.portal("open", "ids-on-create")
        profile = copy.deepcopy(self.profile)
        profile["submission"]["identity"]["issued_on_create"] = [
            {"key": "external_game_id", "read": [{"label": "Game ID"}]},
            {"key": "app_id", "read": [{"label": "App ID"}]}]
        publication = self.visit(live=True, profile=profile)
        self.assertEqual(publication.outcome, outcomes.IDS_ISSUED, publication.message)
        game = self.state()["games"][0]
        self.assertEqual(publication.created_ids, {"external_game_id": game["id"], "app_id": game["app_id"]})
        self.assertEqual(self.state()["uploads"], 0)
        # Rebuilt with the ids: the game is found by them and the build uploaded to it.
        ids = {"config_game_id": game["id"], "config_app_id": game["app_id"]}
        again = self.visit(live=True, profile=profile, identity=ids, visit="2-1")
        self.assertEqual(again.outcome, outcomes.UPLOAD_COMPLETE, again.message)
        self.assertEqual(again.found_game["source"], "config:game_id")
        self.assertEqual((self.state()["creates"], self.state()["uploads"]), (1, 1))

    def test_drift_on_a_reversible_and_on_the_irreversible_intent(self):
        self.portal("open", "drift-title")
        publication = self.visit(live=True)
        self.assertEqual((publication.outcome, publication.human_reason),
                         (outcomes.UNKNOWN, "ambiguous-portal-state"), publication.message)
        self.assertIn("field.title", publication.message)
        self.assertEqual(self.state()["saves"], 0)
        self.portal("open", "drift-submit", seed=[{"id": "g0902", "title": TITLE, "status": "Draft",
                                                   "build": {"filename": "generic-web.zip"}}])
        publication = self.visit(live=True, confirmed=True, identity={"portal_game_id": "g0902"})
        self.assertEqual((publication.outcome, publication.human_reason),
                         (outcomes.UNKNOWN, "drift-irreversible"), publication.message)
        self.assertEqual(self.state()["requests"], 0)

    def test_an_upload_the_portal_refuses_and_pending_declarations(self):
        self.portal("open", "upload-fail")
        publication = self.visit(live=True)
        self.assertEqual(publication.outcome, outcomes.PLATFORM_ERROR, publication.message)
        self.assertIn("storage unavailable", publication.message)
        self.portal("open", "undeclared")
        publication = self.visit(live=True)
        self.assertEqual((publication.outcome, publication.human_reason),
                         (outcomes.HUMAN_REQUIRED, "declaration"), publication.message)
        self.assertTrue(publication.uploaded)
        self.assertEqual(self.state()["requests"], 0)


if __name__ == "__main__":
    unittest.main()

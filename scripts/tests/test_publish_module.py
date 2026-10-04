"""The publish module (scripts/wgf_publish): guards, redaction, the two steps, the adapters,
the engine, and - opt-in - a real browser against the fixture portal.

    python -m unittest scripts/tests/test_publish_module.py
    WGF_PUBLISH_BROWSER_TEST=1 python -m unittest scripts/tests/test_publish_module.py

The game repository is test_release_module's fixture (a real git repository, a fake `pnpm`
that packages like the template's release scripts); the release step drafts the manifest the
publish steps read. The console executor is replaced by a fake that writes the result a
Playwright run would, scenario by scenario; the opt-in class runs the real one, in the pinned
template's checkout (its Playwright, its Chromium), against scripts/tests/fixtures/publish/
portal.py. No test contacts a real portal.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, HERE)

from test_release_module import (CONTRACTS, NOW, Context, GameRepository, Inputs,  # noqa: E402
                                 seal, step as release_step)
from testenv import enabled  # noqa: E402
from campaign_fixture import write_campaign  # noqa: E402
from wgf_publish import PlatformValidateStep, PublishStep, register  # noqa: E402
from wgf_publish import outcomes  # noqa: E402
from wgf_publish.adapters import ConsoleAdapter, ManualAdapter, resolve  # noqa: E402
from wgf_publish.adapters.fixture import FixturePortalAdapter  # noqa: E402
from wgf_publish.session import StorageState, read_credential  # noqa: E402
from wgflib import publication as pub  # noqa: E402
from wgflib import redact  # noqa: E402
from wgflib.procs import ProcessResult  # noqa: E402
from wgflib.workflow import StepOutcome, StepRegistry  # noqa: E402
from wgflib.workflow.definition import StepDefinition  # noqa: E402
from wgflib.workflow.events import EventBus  # noqa: E402

FIXTURES = os.path.join(HERE, "fixtures", "publish")
PORTAL = os.path.join(FIXTURES, "portal.py")
PROFILES = os.path.join(FIXTURES, "publication")
COOKIE = "fixture-session-token-0001"
STORAGE_STATE = {"cookies": [{"name": "session", "value": COOKIE, "domain": "127.0.0.1",
                              "path": "/", "expires": -1, "httpOnly": False, "secure": False,
                              "sameSite": "Lax"}], "origins": []}
METADATA = {"generic-web": {"title": "Fixture Game", "descriptions": {"en": "A fixture."},
                            "screenshots": ["s1.png"], "icon": "icon.png",
                            "locales_included": ["en"]}}
# A shipped store listing's rendition texts (store-listing localeCopy), in two locales.
LISTING = {
    "en": {"title": "Fixture Game", "short_description": "Merge towers, hold the line.",
           "long_description": "Merge matching towers to build stronger ones and hold the line "
                               "against every wave.",
           "controls": "Mouse: drag to merge. Touch: drag to merge.",
           "tags": ["merge", "tower defense", "casual"], "categories": ["Puzzle"]},
    "ru": {"title": "Fixture Game", "short_description": "Объединяй башни, держи оборону.",
           "long_description": "Объединяй одинаковые башни, строй сильнее и держи оборону "
                               "против каждой волны.",
           "controls": "Мышь: перетащи. Касание: перетащи.",
           "tags": ["слияние", "башни"], "categories": ["Головоломки"]},
}
# A platform that asks for every listing field, in ru (shaped like Yandex's profile).
STRICT_PLATFORM = {
    "store_listing": {"title": {"required": True}, "short_description": {"required": True},
                      "long_description": {"required": True}, "tags": {"required": False},
                      "categories": {"required": True}, "locales": ["ru"]},
    "metadata_requirements": {"descriptions_locales": ["ru"]},
    "requirements": {"locales_required": ["ru"]},
}
# The results the console intent runner writes (browser/console.spec.ts), by scenario.
def _result(**extra):
    base = {"outcome": "completed", "stop": None, "phase_reached": "verify", "phases": {},
            "found_game": None, "created": True, "created_ids": {}, "game_id": "g0001",
            "uploaded": True, "saved": True, "request_attempted": False, "requested": False,
            "already_requested": False, "status_before": None, "status_text": "Draft",
            "human_fields": [], "absent": [], "login_handoffs": [], "refused": [], "errors": [],
            "actions": 0}
    base.update(extra)
    return base


HANDOFF = {"at": NOW, "url": "http://127.0.0.1:1/login", "reason": "the console shows its login form",
           "kind": "login", "phase": "session",
           "action": "log in in the opened browser window; handle CAPTCHA/2FA yourself",
           "resume": "the console's authenticated page is detected", "resolved_at": None,
           "outcome": "timeout"}
SCENARIOS = {
    "fresh": _result(),
    "existing": _result(created=False, game_id=None, found_game={
        "id": "g0007", "title": "Fixture Game", "status_text": "Draft", "source": "registry"}),
    "login": _result(outcome="login_timeout", uploaded=False, saved=False, phase_reached=None,
                     stop={"phase": "session", "code": "login", "reason": "no login"},
                     login_handoffs=[HANDOFF]),
    "captcha": _result(outcome="login_timeout", uploaded=False, saved=False, phase_reached="session",
                       stop={"phase": "upload_build", "code": "captcha", "reason": "no answer"},
                       login_handoffs=[dict(HANDOFF, kind="captcha", phase="upload_build")]),
    "two-factor": _result(outcome="login_abandoned", uploaded=False, saved=False,
                          stop={"phase": "session", "code": "two-factor", "reason": "closed"},
                          login_handoffs=[dict(HANDOFF, kind="two-factor", outcome="window-closed")]),
    "upload-error": _result(outcome="stopped", uploaded=False, saved=False,
                            stop={"phase": "upload_build", "code": "portal-error",
                                  "reason": "upload.start: the console reports: storage unavailable"}),
    "unsaved": _result(saved=False),
    "duplicate": _result(outcome="stopped", uploaded=False, saved=False, created=False, game_id=None,
                         found_game={"id": "g0900", "title": "Fixture Game", "status_text": "Draft",
                                     "source": "title"},
                         stop={"phase": "find_game", "code": "duplicate-candidate",
                               "reason": "an unrecorded game with this title"}),
    "ids": _result(outcome="stopped", uploaded=False, saved=False, game_id="g0003",
                   created_ids={"external_game_id": "g0003", "app_id": "app-4004"},
                   stop={"phase": "create_game", "code": "ids-issued", "reason": "ids issued"}),
}
# A visit a person confirmed (`submit`): the game the upload visit made is found, review is
# requested once, and the status is read back.
_CONFIRMED = dict(created=False, game_id=None, uploaded=False, saved=False,
                  request_attempted=True, requested=True,
                  found_game={"id": "g0007", "title": "Fixture Game", "status_text": "Draft",
                              "source": "registry"})
SCENARIOS.update({
    "submitted": _result(status_text="Waiting for moderation", **_CONFIRMED),
    "ambiguous": _result(status_text="Processing", **_CONFIRMED),
    "rejected": _result(status_text="Rejected", **_CONFIRMED),
})


SUBMIT_DECISION = {"decision": "submit", "decided_by": "human", "note": "looked at the draft",
                   "decided_at": "2026-10-04T10:00:00Z"}


class FakeConsole:
    """Stands in for `pnpm exec playwright test`: records the flow, writes the scenario's
    runner result. `crash` writes nothing and exits 1; `no_browser` prints Playwright's
    missing executable message."""

    def __init__(self, scenario="fresh", crash=False, no_browser=False):
        self.scenario, self.crash, self.no_browser = scenario, crash, no_browser
        self.flows = []

    def __call__(self, argv, cwd=None, timeout=None, env=None, log_path=None,
                 stderr_to_stdout=False, on_output=None, **hooks):
        with open(env["WGF_PUBLISH_FLOW"], encoding="utf-8") as handle:
            flow = json.load(handle)
        self.flows.append(flow)
        if self.no_browser:
            return ProcessResult(argv, returncode=1,
                                 stdout="browserType.launch: Executable doesn't exist")
        if self.crash:
            return ProcessResult(argv, returncode=1, stdout="playwright crashed")
        os.makedirs(os.path.dirname(env["WGF_PUBLISH_RESULT"]), exist_ok=True)
        with open(env["WGF_PUBLISH_RESULT"], "w", encoding="utf-8") as handle:
            json.dump(SCENARIOS[self.scenario], handle)
        return ProcessResult(argv, returncode=0, stdout="1 passed")


class PublishInputs(Inputs):
    """Inputs with one platform-publication per platform (StepInputs.every)."""

    def __init__(self, artifacts, publications=None):
        super().__init__(artifacts)
        from wgflib.workflow.model import ArtifactRef
        records = list(publications or [artifacts["platform-publication"]])
        self.records = {}
        self._every = []
        for n, record in enumerate(records):
            ref = ArtifactRef(id=f"platform-publication-{record['platform_id']}",
                              type="platform-publication", version=1,
                              location=f"artifacts/p{n}.json", checksum="sha256:" + "0" * 64,
                              content_hash=record["provenance"]["content_hash"], seq=n)
            self.records[ref.id] = record
            self._every.append(ref)

    def every(self, artifact_type):
        if artifact_type == "platform-publication":
            return list(self._every)
        return [self.refs[artifact_type]] if artifact_type in self.refs else []

    def load_ref(self, ref):
        if ref.type == "platform-publication":
            return self.records[ref.id]
        return self.contents.get(ref.type)


def listing_placeholders():
    """The store-listing and listing-validation-report a --mock run carries."""
    from wgflib import provenance
    from wgflib.workflow.mock import DEFAULT_EPOCH, FIXTURES, FIXTURE_SLUG
    out = {}
    for n, artifact_type in enumerate(("store-listing", "listing-validation-report"), 1):
        with open(os.path.join(FIXTURES, f"{artifact_type}.json"), encoding="utf-8") as handle:
            body = json.loads(handle.read().replace(FIXTURE_SLUG, "fixture-game"))
        artifact = {"provenance": provenance.build(
            artifact_type,
            artifact_id=provenance.artifact_id(artifact_type, "fixture-game", DEFAULT_EPOCH, n),
            produced_by=provenance.producer("release"), produced_at=DEFAULT_EPOCH,
            inputs=[], title_id="fixture-game")}
        artifact.update(body)
        provenance.seal(artifact)
        out[artifact_type] = artifact
    return out


class PublishCase(unittest.TestCase):
    """A drafted release in a fixture game repository, and the inputs the publish steps read."""

    def setUp(self):
        self.scratch = tempfile.mkdtemp(prefix="wgf-publish-")
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)
        self.addCleanup(redact.forget)
        self.game = GameRepository(self.scratch)
        self.evidence = self.game.evidence()
        instance = release_step(repo_dir=self.game.root)
        instance.environ = self.game.environ(())
        instance.clock = staticmethod(lambda: NOW)
        drafted = instance.execute(Inputs(self.evidence, ()), Context())
        self.assertEqual(drafted.outcome, StepOutcome.SUCCESS, drafted.error)
        self.manifest = drafted.artifacts[0].content
        self.release_dir = self.game.path("release", "r1")
        self.run_dir = os.path.join(self.scratch, "run")
        os.makedirs(self.run_dir)
        self.environ = {k: v for k, v in self.game.environ(()).items()}
        # The portal registry is written under the scratch directory, never the project's.
        self.titles = os.path.join(self.scratch, "titles")
        for cls in (PublishStep, PlatformValidateStep):
            self.addCleanup(setattr, cls, "titles_dir", cls.__dict__.get("titles_dir"))
            cls.titles_dir = self.titles
        self.listing = listing_placeholders()

    # -- fixtures ---------------------------------------------------------------------------

    def write_campaign(self, text=None, platform_id="generic-web", **kw):
        """The campaign the release shipped (campaign_fixture): of the manifest's commit,
        the store-listing G6 pins."""
        kw.setdefault("commit", self.manifest["commit_sha"])
        kw.setdefault("listing_hash", self.listing["store-listing"]["provenance"]["content_hash"])
        return write_campaign(self.release_dir, platform_id, text=text, **kw)

    def write_metadata(self, metadata=None):
        metadata = METADATA if metadata is None else metadata
        if "generic-web" in metadata:
            self.write_campaign()
        with open(os.path.join(self.release_dir, "store-metadata.json"), "w",
                  encoding="utf-8") as handle:
            json.dump(metadata, handle)
        for entry in metadata.values():  # the media files the console flow uploads
            for name in [entry.get("icon")] + list(entry.get("screenshots") or []):
                if name:
                    with open(os.path.join(self.release_dir, name), "wb") as handle:
                        handle.write(b"\x89PNG fixture")

    def write_listing(self, text=None, platform_id="generic-web"):
        """The store listing the release shipped: its rendition for `platform_id`."""
        self.write_campaign(LISTING if text is None else text, platform_id)

    def verification(self, assertions=()):
        """The run's verification-report with policy.assertions:generic-web recorded."""
        report = dict(self.evidence["verification-report"])
        report = json.loads(json.dumps(report))
        report["provenance"]["content_hash"] = ""
        results = list(assertions)
        report["checks"].append({
            "id": "policy.assertions:generic-web", "category": "policy",
            "title": "Platform profile assertions", "status": "PASS", "required": True,
            "message": "fixture", "platform_id": "generic-web",
            "evidence": [{"kind": "file", "summary": f"{len(results)} assertion(s)",
                          "path": "build/assertions/generic-web.json",
                          "data": {"results": results}}]})
        body = {k: v for k, v in report.items() if k != "provenance"}
        return seal("verification-report", body, inputs=report["provenance"]["inputs"])

    def with_assertions(self, evidence, assertions=()):
        """`evidence` with the verification-report carrying assertion results and the
        qa-report re-pinned to it, so the release step sees one consistent lineage."""
        evidence = dict(evidence)
        verification = self.verification(assertions)
        qa = json.loads(json.dumps(evidence["qa-report"]))
        pins = [p for p in qa["provenance"]["inputs"] if p["artifact_type"] != "verification-report"]
        pins.append({"artifact_id": verification["provenance"]["artifact_id"],
                     "artifact_type": "verification-report",
                     "content_hash": verification["provenance"]["content_hash"]})
        body = {k: v for k, v in qa.items() if k != "provenance"}
        evidence["verification-report"] = verification
        evidence["qa-report"] = seal("qa-report", body, inputs=pins)
        return evidence

    def validate_inputs(self, assertions=(), verification=True):
        artifacts = {"release-manifest": self.manifest,
                     "scaffold-record": self.evidence["scaffold-record"],
                     "qa-report": self.evidence["qa-report"]}
        if verification:
            artifacts["verification-report"] = self.verification(assertions)
        return Inputs(artifacts)

    def settings(self, **publish):
        section = {"profiles_extra": [os.path.relpath(PROFILES, ROOT)],
                   "platforms": {"generic-web": {"adapter": "fixture-portal",
                                                 "console_url": "http://127.0.0.1:1/"}}}
        section.update(publish)
        return {"publish": section}

    def context(self, step_id, config=None, decision=None, gates=("G4", "G5", "G6")):
        context = Context(config=config or {}, gates_passed=gates)
        context.current_step = step_id
        context.idempotency_key = f"run-1:{step_id}:1"
        context.run_dir = self.run_dir
        context.decision = decision
        return context

    def validate(self, inputs=None, config=None, params=None, environ=None):
        params = dict(params or {})
        params.setdefault("repo_dir", self.game.root)
        instance = PlatformValidateStep(StepDefinition(
            {"id": "platform-validate", "type": "platform-validate",
             "inputs": ["release-manifest", "verification-report", "qa-report", "sdk-report",
                        "scaffold-record"], "outputs": ["platform-publication"],
             "with": params}, retry=None, max_visits=None))
        instance.environ = dict(self.environ, **(environ or {}))
        result = instance.execute(inputs or self.validate_inputs(), self.context("platform-validate", config))
        for artifact in result.artifacts:
            self.assertEqual(CONTRACTS.problems("platform-publication", artifact.content), [])
        return result

    def g6(self, manifest=None, mode="human", decision="approved", gate="G6", listing=None,
           validation=None):
        manifest = manifest or self.manifest
        subject = [manifest, listing or self.listing["store-listing"],
                   validation or self.listing["listing-validation-report"]]
        return seal("decision-record", {
            "gate_id": gate, "machine": "release", "transition": "approved -> validating",
            "subject": [{"artifact_id": a["provenance"]["artifact_id"],
                         "artifact_type": a["provenance"]["artifact_type"],
                         "content_hash": a["provenance"]["content_hash"]} for a in subject],
            "decision": decision,
            "decided_by": {"role": "portfolio-owner", "mode": mode, "identifier": "human"},
            "decided_at": NOW, "rationale": "fixture"}, schema_version="1.0.0")

    def publish(self, publication, *, console=None, config=None, params=None, g6=None,
                decision=None, gates=("G4", "G5", "G6"), environ=None, manifest=None,
                publications=None, adapter=None, verification=None, listing=None,
                visit=1):
        params = dict(params or {})
        params.setdefault("repo_dir", self.game.root)
        instance = PublishStep(StepDefinition(
            {"id": "submit", "type": "publish",
             "inputs": ["release-manifest", "platform-publication", "decision-record",
                        "scaffold-record", "verification-report", "store-listing",
                        "listing-validation-report"], "outputs": ["platform-publication"],
             "with": params}, retry=None, max_visits=None))
        instance.environ = dict(self.environ, **(environ or {}))
        instance.run_process = console or FakeConsole()
        if adapter is not None:
            instance.adapter_factory = adapter
        artifacts = {"release-manifest": manifest or self.manifest,
                     "platform-publication": publication,
                     "decision-record": g6 or self.g6(),
                     "scaffold-record": self.evidence["scaffold-record"],
                     "verification-report": verification or self.evidence["verification-report"]}
        artifacts.update(listing or self.listing)
        context = self.context("submit", config, decision, gates)
        context.visit = context.execution = visit
        result = instance.execute(PublishInputs(artifacts, publications), context)
        for artifact in result.artifacts:
            self.assertEqual(CONTRACTS.problems("platform-publication", artifact.content), [],
                             json.dumps(artifact.content, indent=1)[:2000])
        return result

    def ready(self, **environ):
        """A validated, READY platform-publication: the fixture console. Nothing is needed in
        advance: a person logs in live in the window the submit step opens."""
        self.write_metadata()
        env = dict(environ)
        config = self.settings()
        result = self.validate(config=config, environ=env)
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error or result.message)
        record = result.artifacts[0].content
        self.assertEqual(record["readiness"], "READY", record["guards"])
        return record, config, env


# -- redaction -------------------------------------------------------------------------------

class Redaction(unittest.TestCase):
    def tearDown(self):
        redact.forget()

    def test_registered_values_and_secret_shapes_are_replaced(self):
        redact.register("fixture-session-token-0001")
        text = ("Cookie: session=fixture-session-token-0001; Authorization: Bearer abcdefghijkl "
                "password=hunter2x token: ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ")
        scrubbed = redact.scrub_text(text)
        self.assertNotIn("fixture-session-token-0001", scrubbed)
        self.assertNotIn("abcdefghijkl", scrubbed)
        self.assertNotIn("hunter2x", scrubbed)
        self.assertNotIn("ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ", scrubbed)

    def test_secret_keys_are_replaced_whole_and_benign_keys_are_not(self):
        out = redact.scrub({"token": "abc", "storage_state": {"cookies": []},
                            "idempotency_key": "wgf-x-1", "max_sessions": 12,
                            "nested": {"Authorization": "x", "note": "fine"}})
        self.assertEqual(out["token"], redact.REPLACEMENT)
        self.assertEqual(out["storage_state"], redact.REPLACEMENT)
        self.assertEqual(out["idempotency_key"], "wgf-x-1")
        self.assertEqual(out["max_sessions"], 12)
        self.assertEqual(out["nested"], {"Authorization": redact.REPLACEMENT, "note": "fine"})

    def test_short_values_are_not_registered(self):
        self.assertFalse(redact.register("ok"))
        self.assertEqual(redact.scrub_text("ok then"), "ok then")

    def test_the_event_bus_redacts_every_record(self):
        redact.register("fixture-session-token-0001")
        seen = []
        bus = EventBus(lambda: "t")
        bus.subscribe(seen.append)
        bus.emit("STEP_LOG", message="cookie session=fixture-session-token-0001 seen",
                 data={"password": "p", "step": "submit"})
        self.assertEqual(seen[0]["message"], f"cookie session={redact.REPLACEMENT} seen")
        self.assertEqual(seen[0]["data"], {"password": redact.REPLACEMENT, "step": "submit"})


# -- the guards ------------------------------------------------------------------------------

class Guards(unittest.TestCase):
    MANIFEST = {"commit_sha": "a" * 40, "packages": [{"platform_id": "yandex", "filename":
                "yandex.zip", "size_mb": 12.5, "checksum": "sha256:" + "0" * 64}],
                "target_platforms": [{"id": "yandex", "role": "required",
                                      "profile_version": "1.0.0"}]}
    PROFILE = {"requirements": {"locales_required": ["ru"], "max_bundle_mb": 100},
               "metadata_requirements": {"descriptions_locales": ["ru"], "screenshots_min": 3,
                                         "icon_required": True, "age_rating_required": True}}

    def test_candidate_frozen(self):
        self.assertTrue(pub.candidate_frozen(self.MANIFEST).value)
        self.assertIsNone(pub.candidate_frozen(None).value)
        self.assertFalse(pub.candidate_frozen(dict(self.MANIFEST, packages=[])).value)
        bad = dict(self.MANIFEST, packages=[dict(self.MANIFEST["packages"][0], checksum="md5:x")])
        self.assertFalse(pub.candidate_frozen(bad).value)

    def test_store_metadata_complete_names_what_is_missing(self):
        result = pub.store_metadata_complete(self.MANIFEST, {"yandex": self.PROFILE})
        self.assertFalse(result.value)
        self.assertIn("no store metadata for yandex", result.reason)
        partial = {"yandex": {"descriptions": {"ru": "x"}, "screenshots": ["a"],
                              "locales_included": ["en"]}}
        result = pub.store_metadata_complete(self.MANIFEST, {"yandex": self.PROFILE}, partial)
        self.assertFalse(result.value)
        for needle in ("1 screenshot(s), 3 required", "no icon", "no age rating",
                       "required locale(s) not included: ru"):
            self.assertIn(needle, result.reason)
        complete = {"yandex": {"descriptions": {"ru": "x"}, "screenshots": ["a", "b", "c"],
                               "icon": "i.png", "age_rating": "6+", "locales_included": ["ru"]}}
        self.assertTrue(pub.store_metadata_complete(self.MANIFEST, {"yandex": self.PROFILE},
                                                    complete).value)
        self.assertIsNone(pub.store_metadata_complete(self.MANIFEST, {}, complete).value)

    def test_package_shaped_to_profile(self):
        package = self.MANIFEST["packages"][0]
        self.assertTrue(pub.package_shaped_to_profile("yandex", self.PROFILE, package, True).value)
        self.assertFalse(pub.package_shaped_to_profile("yandex", self.PROFILE, package, False).value)
        self.assertIsNone(pub.package_shaped_to_profile("yandex", self.PROFILE, package, None).value)
        self.assertFalse(pub.package_shaped_to_profile("yandex", self.PROFILE, None, True).value)
        big = dict(package, size_mb=250)
        self.assertFalse(pub.package_shaped_to_profile("yandex", self.PROFILE, big, True).value)

    def test_assertions_pass(self):
        self.assertIsNone(pub.assertions_pass("yandex", None).value)
        self.assertTrue(pub.assertions_pass("yandex", []).value)
        warned = [{"criterion_id": "yandex_screenshots", "breached": True, "severity": "warning"}]
        self.assertTrue(pub.assertions_pass("yandex", warned).value)
        breached = [{"criterion_id": "yandex_bundle_size", "breached": True, "severity": "blocking"}]
        self.assertFalse(pub.assertions_pass("yandex", breached).value)

    def test_readiness_is_derived_and_unknown_is_never_ready(self):
        green = pub.GuardResult(True, "ok")
        self.assertEqual(pub.readiness({"a": green}), pub.READY)
        self.assertEqual(pub.readiness({"a": green}, ("login", "x")), pub.HUMAN_REQUIRED)
        self.assertEqual(pub.readiness({"a": green, "b": pub.GuardResult(None, "?")}), pub.UNKNOWN)
        self.assertEqual(pub.readiness({"a": green, "b": pub.GuardResult(None, "?"),
                                        "c": pub.GuardResult(False, "no")}), pub.BLOCKED)

    def test_human_reason_follows_the_publication_profile(self):
        console = pub.load_publication_profile("crazygames")
        self.assertEqual(pub.human_reason(console, {}, True)[0], "terms-unconfirmed")
        # A person logs in live: no credential to be missing.
        self.assertIsNone(pub.human_reason(console, {"terms_confirmed": True}, False))
        self.assertIsNone(pub.human_reason(console, {"terms_confirmed": True}, True))
        self.assertEqual(pub.human_reason(pub.load_publication_profile("gamevui"), {}, None)[0],
                         "manual-submission")
        self.assertEqual(pub.human_reason(pub.load_publication_profile("poki"), {}, True)[0],
                         "no-automated-method")
        self.assertEqual(pub.human_reason(None, {}, None)[0], "no-automated-method")

    def test_every_platform_has_a_publication_profile_and_no_shipped_console_is_verified(self):
        from wgflib import paths
        platforms = sorted(os.path.basename(p)[:-5]
                           for p in os.listdir(paths.PLATFORMS) if p.endswith(".yaml"))
        for pid in platforms:
            profile = pub.load_publication_profile(pid)
            self.assertIsNotNone(profile, pid)
            submission = profile["submission"]
            if submission["method"] == "console":
                # No live console flow has been exercised: automation stays off until a
                # person records the portal's terms (docs/publish-module.md).
                self.assertEqual(submission["automation_terms"], "unverified", pid)
                self.assertEqual(profile["status"], "unverified", pid)

    def test_idempotency_key_is_deterministic_per_run_manifest_and_platform(self):
        key = pub.idempotency_key("run-1", "sha256:" + "a" * 64, "yandex")
        self.assertEqual(key, pub.idempotency_key("run-1", "sha256:" + "a" * 64, "yandex"))
        self.assertNotEqual(key, pub.idempotency_key("run-1", "sha256:" + "b" * 64, "yandex"))
        self.assertNotEqual(key, pub.idempotency_key("run-1", "sha256:" + "a" * 64, "poki"))
        self.assertTrue(key.startswith("wgf-yandex-"))

    def test_the_lifecycle_guards_read_a_run_s_release_and_publication(self):
        from wgflib import guards
        evidence = guards.RunEvidence("run-9", manifest=self.MANIFEST, publication={
            "platform_id": "yandex", "state": "validated",
            "guards": [{"guard": "assertions_pass", "verdict": "GREEN", "reason": "hold"},
                       {"guard": "package_shaped_to_profile", "verdict": "RED", "reason": "big"}]})
        context = guards.GuardContext(entity=None, evidence=evidence)
        self.assertTrue(guards.evaluate_guard("candidate_frozen", context).value)
        self.assertTrue(guards.evaluate_guard("assertions_pass", context).value)
        self.assertFalse(guards.evaluate_guard("package_shaped_to_profile", context).value)
        self.assertIsNone(guards.evaluate_guard("metadata_and_locales_present", context).value)
        self.assertTrue(guards.evaluate_guard("all_targeted_validated", context).value)
        self.assertFalse(guards.evaluate_guard("required_all_live", context).value)
        self.assertTrue(guards.evaluate_guard("none_permanently_rejected", context).value)
        # A mock run's placeholders are nobody's evidence.
        mocked = guards.GuardContext(entity=None, evidence=guards.RunEvidence(
            "run-m", manifest=self.MANIFEST, mock=True))
        self.assertIsNone(guards.evaluate_guard("candidate_frozen", mocked).value)
        self.assertIsNone(guards.evaluate_guard("candidate_frozen",
                                                guards.GuardContext(entity=None)).value)


# -- adapters and the session --------------------------------------------------------------

class Adapters(unittest.TestCase):
    def tearDown(self):
        redact.forget()

    def test_resolution_prefers_the_profile_s_method_and_a_registered_console_flow(self):
        self.assertIsInstance(resolve("gamevui", pub.load_publication_profile("gamevui")),
                              ManualAdapter)
        self.assertIsInstance(resolve("poki", pub.load_publication_profile("poki")), ManualAdapter)
        crazy = resolve("crazygames", pub.load_publication_profile("crazygames"))
        self.assertEqual(crazy.__class__.__name__, "CrazyGamesAdapter")
        y8 = resolve("y8", pub.load_publication_profile("y8"))
        self.assertEqual(y8.__class__.__name__, "Y8Adapter")  # each target has its own
        self.assertEqual(y8.method, "console")
        # A console platform with no adapter of its own runs on the profile's flow; without a
        # flow it is a person's.
        flow = {"submission": {"method": "console", "flow": [
            {"id": "x.open", "phase": "create_game", "class": "reversible", "action": "navigate",
             "url": "/new"}]}}
        self.assertIs(type(resolve("other-console", flow)), ConsoleAdapter)
        self.assertIsInstance(resolve("other-console", {"submission": {"method": "console"}}),
                              ManualAdapter)
        fixture = resolve("generic-web", {"submission": {"method": "console"}},
                          {"adapter": "fixture-portal", "console_url": "http://127.0.0.1:1/"})
        self.assertIsInstance(fixture, FixturePortalAdapter)
        self.assertEqual(fixture.console_url(None), "http://127.0.0.1:1/console")

    def test_a_manual_adapter_contacts_nothing_and_says_what_a_person_does(self):
        adapter = resolve("gamevui", pub.load_publication_profile("gamevui"))
        from wgf_publish.adapters import Job
        job = Job(platform_id="gamevui", release_id="r1", idempotency_key="k", package_path=None,
                  package={"filename": "gamevui.zip"}, metadata={}, checkout=None,
                  release_dir=None, run_dir=None, scratch_dir=None, submit=True, env={}, hooks={})
        result = adapter.publish(job)
        self.assertEqual(result.outcome, outcomes.HUMAN_REQUIRED)
        self.assertEqual(result.human_reason, "manual-submission")
        self.assertIn("email the package gamevui.zip", result.message)

    def test_a_console_session_is_never_captured_loaded_or_kept(self):
        human = read_credential(pub.load_publication_profile("crazygames"), {}, {})
        self.assertEqual((human.kind, human.usable, human.value), ("human-login", True, None))
        with StorageState(human, tempfile.gettempdir()) as state:
            self.assertIsNone(state.path)
        old = {"submission": {"credential": {"kind": "storage-state",
                                             "env": "WGF_PUBLISH_FIXTURE_STORAGE_STATE"}}}
        from wgf_publish.session import CredentialError
        with self.assertRaises(CredentialError):
            read_credential(old, {"env_passthrough": ["WGF_PUBLISH_FIXTURE_STORAGE_STATE"]},
                            {"WGF_PUBLISH_FIXTURE_STORAGE_STATE": json.dumps(STORAGE_STATE)})
        import wgf_publish
        self.assertFalse(hasattr(wgf_publish, "capture"))
        cli = os.path.join(SCRIPTS, "wgf-publish.py")
        with open(cli, encoding="utf-8") as handle:
            self.assertNotIn("save-storage", handle.read())

    def test_outcomes_map_to_step_results(self):
        self.assertEqual(outcomes.to_result(outcomes.VERIFIED, [], "m", platform_id="p").route,
                         "submitted")
        self.assertEqual(outcomes.to_result(outcomes.DRY_RUN, [], "m", platform_id="p").route,
                         "dry-run")
        waiting = outcomes.to_result(outcomes.CAPTCHA_REQUIRED, [], "m", platform_id="p")
        self.assertEqual(waiting.outcome, StepOutcome.WAITING_FOR_HUMAN)
        self.assertEqual(waiting.data["choices"], ["done", "abandon"])
        failed = outcomes.to_result(outcomes.RETRYABLE_FAILURE, [], "m", platform_id="p")
        self.assertEqual((failed.outcome, failed.retryable), (StepOutcome.FAILED, False))


# -- platform-validate -----------------------------------------------------------------------

class Validate(PublishCase):
    def test_the_module_registers_both_step_types(self):
        registry = register(StepRegistry())
        self.assertIs(registry.resolve("platform-validate"), PlatformValidateStep)
        self.assertIs(registry.resolve("publish"), PublishStep)

    def test_without_assertion_results_or_metadata_the_release_is_undecided_then_blocked(self):
        result = self.validate(self.validate_inputs(verification=False))
        self.assertEqual(result.outcome, StepOutcome.FAILED)  # metadata missing: RED
        record = result.artifacts[0].content
        self.assertEqual(record["readiness"], "BLOCKED")
        verdicts = {g["guard"]: g["verdict"] for g in record["guards"]}
        self.assertEqual(verdicts["assertions_pass"], "UNKNOWN")
        self.assertEqual(verdicts["store_metadata_complete"], "RED")
        self.assertEqual(record["state"], "validation-failed")
        self.write_metadata()
        result = self.validate(self.validate_inputs(verification=False))
        self.assertEqual(result.outcome, StepOutcome.BLOCKED, result.message)
        self.assertEqual(result.artifacts[0].content["readiness"], "UNKNOWN")
        self.assertIn("assertions_pass UNKNOWN", result.message)

    def test_a_breached_blocking_assertion_fails_validation_with_the_record_kept(self):
        self.write_metadata()
        breached = [{"criterion_id": "generic_web_standalone", "breached": True,
                     "severity": "blocking", "measured": "yandex"}]
        result = self.validate(self.validate_inputs(assertions=breached))
        self.assertEqual((result.outcome, result.route, result.retryable),
                         (StepOutcome.FAILED, "fail", False))
        record = result.artifacts[0].content
        self.assertEqual(record["readiness"], "BLOCKED")
        self.assertEqual(record["assertion_results"][0]["criterion_id"], "generic_web_standalone")
        self.assertIn("generic_web_standalone", result.error)

    def test_a_manual_platform_validates_as_human_required(self):
        self.write_metadata()
        result = self.validate()  # core's generic-web publication profile: manual
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error or result.message)
        record = result.artifacts[0].content
        self.assertEqual((record["readiness"], record["state"]), ("HUMAN_REQUIRED", "validated"))
        self.assertEqual(record["human_required"]["reason"], "manual-submission")
        self.assertEqual(record["package"]["verified_on_disk"], True)
        self.assertEqual(record["measurement_class"], "automation-check")
        self.assertEqual({g["verdict"] for g in record["guards"]}, {"GREEN"})
        self.assertIn("nothing published", result.message)

    def test_a_console_platform_is_ready_with_nothing_captured_in_advance(self):
        record, _config, _env = self.ready()
        self.assertEqual(record["readiness"], "READY")
        self.assertEqual(record["submission"]["method"], "console")
        self.assertNotIn("human_required", record)

    def test_a_package_whose_bytes_changed_is_not_shaped_to_the_profile(self):
        self.write_metadata()
        with open(os.path.join(self.release_dir, "generic-web.zip"), "ab") as handle:
            handle.write(b"tamper")
        result = self.validate()
        self.assertEqual(result.outcome, StepOutcome.FAILED)
        verdicts = {g["guard"]: g["verdict"] for g in result.artifacts[0].content["guards"]}
        self.assertEqual(verdicts["package_shaped_to_profile"], "RED")

    def test_without_a_manifest_it_waits_for_input(self):
        result = self.validate(Inputs({}, missing=["release-manifest"]))
        self.assertEqual(result.outcome, StepOutcome.WAITING_FOR_INPUT)


# -- publish ---------------------------------------------------------------------------------

class Publish(PublishCase):
    def setUp(self):
        super().setUp()
        self.record, self.config, self.env = self.ready()

    def go(self, **kwargs):
        kwargs.setdefault("config", self.config)
        kwargs.setdefault("environ", self.env)
        return self.publish(self.record, **kwargs)

    def test_g6_is_required_and_must_be_a_person_s_approval_of_this_manifest(self):
        result = self.go(gates=("G4", "G5"))
        self.assertEqual(result.outcome, StepOutcome.BLOCKED)
        self.assertEqual(result.data["code"], "g6-not-passed")
        self.assertEqual(result.artifacts, [])
        result = self.go(g6=self.g6(mode="auto-approved"))
        self.assertEqual(result.data["code"], "g6-not-human")
        result = self.go(g6=self.g6(decision="rejected"))
        self.assertEqual(result.data["code"], "g6-not-approved")
        other = json.loads(json.dumps(self.manifest))
        other["changelog"] = ["another release"]
        other["provenance"]["content_hash"] = "sha256:" + "f" * 64
        result = self.go(g6=self.g6(manifest=other))
        self.assertEqual(result.data["code"], "g6-stale")
        result = self.go(g6=self.g6(gate="G5"))
        self.assertEqual(result.data["code"], "g6-record-missing")

    def test_dry_run_is_the_default_and_never_requests_review(self):
        console = FakeConsole("fresh")
        result = self.go(console=console)
        self.assertEqual((result.outcome, result.route), (StepOutcome.SUCCESS, "dry-run"),
                         result.error or result.message)
        flow = console.flows[0]
        self.assertEqual((flow["mode"], flow["submit_confirmed"]), ("dry-run", False))
        record = result.artifacts[0].content
        self.assertEqual(record["outcome"], "DRY_RUN")
        self.assertEqual(record["state"], "validated")  # not advanced: nothing observed submitted
        self.assertTrue(record["submission"]["dry_run"])
        self.assertEqual(record["submission"]["portal_draft_id"], "g0001")
        self.assertIn(record["submission"]["idempotency_key"],
                      [c["id"] for c in flow["identity"]["candidates"]])
        self.assertEqual(record["submission"]["authorized_by"]["release_manifest_hash"],
                         self.manifest["provenance"]["content_hash"])
        self.assertIn("nothing submitted", result.message)

    def submitted(self, scenario="submitted", first="fresh"):
        """Live: upload (visit 1), then a person's submit (visit 2). (result, console)."""
        config, env = self.live()
        uploaded = self.go(console=FakeConsole(first), config=config, environ=env)
        self.assertEqual(uploaded.artifacts[0].content["outcome"], "UPLOAD_COMPLETE",
                         uploaded.message)
        console = FakeConsole(scenario)
        return self.publish(uploaded.artifacts[0].content, console=console, config=config,
                            environ=env, decision=SUBMIT_DECISION), console

    def live(self):
        config = dict(self.config)
        config["publish"] = dict(config["publish"], mode="live")
        return config, dict(self.env, WGF_PUBLISH_LIVE="1")

    def test_live_needs_the_configuration_and_the_environment_and_stops_after_the_upload(self):
        config, env = self.live()
        console = FakeConsole("fresh")
        result = self.go(console=console, config=config)
        self.assertEqual(result.route, "dry-run")  # WGF_PUBLISH_LIVE is not 1
        self.assertEqual(console.flows[0]["mode"], "dry-run")
        console = FakeConsole("fresh")
        result = self.go(console=console, config=config, environ=env)
        self.assertEqual(result.outcome, StepOutcome.WAITING_FOR_HUMAN, result.error or result.message)
        self.assertEqual(result.data["waiting_state"], "WAITING_FOR_HUMAN_SUBMIT_CONFIRMATION")
        self.assertEqual(result.data["choices"], ["submit", "hold", "abandon", "done"])
        self.assertEqual(console.flows[0]["mode"], "live")
        self.assertFalse(console.flows[0]["submit_confirmed"])  # the request is never automatic
        record = result.artifacts[0].content
        self.assertEqual((record["outcome"], record["state"]), ("UPLOAD_COMPLETE", "validated"))
        self.assertEqual(record["human_required"]["reason"], "submit-confirmation")
        self.assertEqual(record["waiting"]["state"], "WAITING_FOR_HUMAN_SUBMIT_CONFIRMATION")
        self.assertEqual(record["submission"]["portal_draft_id"], "g0001")
        self.assertNotIn("submitted_at", record["submission"])
        # A person answers submit: the review is requested once and read back.
        console = FakeConsole("submitted")
        result = self.publish(record, console=console, config=config, environ=env,
                              decision=SUBMIT_DECISION)
        self.assertEqual((result.outcome, result.route), (StepOutcome.SUCCESS, "submitted"),
                         result.error or result.message)
        self.assertEqual(console.flows[0]["mode"], "live")
        self.assertTrue(console.flows[0]["submit_confirmed"])
        record = result.artifacts[0].content
        self.assertEqual((record["outcome"], record["state"]), ("SUBMITTED", "submitted"))
        self.assertEqual(record["verified_state"]["observed"], "Waiting for moderation")
        self.assertEqual(record["measurement_class"], "automation-console")
        self.assertIn("submitted_at", record["submission"])

    def test_a_game_the_title_recorded_is_used_and_an_unrecorded_one_stops(self):
        config, env = self.live()
        result = self.go(console=FakeConsole("existing"), config=config, environ=env)
        self.assertEqual(result.artifacts[0].content["outcome"], "UPLOAD_COMPLETE")
        self.assertEqual(result.artifacts[0].content["submission"]["portal_draft_id"], "g0007")
        result = self.go(console=FakeConsole("duplicate"), config=config, environ=env)
        self.assertEqual(result.outcome, StepOutcome.WAITING_FOR_HUMAN)
        record = result.artifacts[0].content
        self.assertEqual((record["outcome"], record["human_required"]["reason"]),
                         ("UNKNOWN", "duplicate-candidate"))

    def test_ids_issued_on_create_route_back_to_the_build(self):
        config, env = self.live()
        result = self.go(console=FakeConsole("ids"), config=config, environ=env)
        self.assertEqual((result.outcome, result.route), (StepOutcome.SUCCESS, "platform-ids"),
                         result.error or result.message)
        self.assertEqual(result.artifacts[0].content["outcome"], "IDS_ISSUED")

    def test_an_existing_draft_with_the_key_is_reused_never_uploaded_again(self):
        result, console = self.submitted("submitted", first="existing")
        self.assertEqual(result.route, "submitted", result.error or result.message)
        self.assertEqual(result.artifacts[0].content["submission"]["portal_draft_id"], "g0007")
        candidates = console.flows[0]["identity"]["candidates"]
        self.assertIn({"source": "idempotency-key", "id": result.artifacts[0].content[
            "submission"]["idempotency_key"]}, candidates)

    def test_a_submitted_record_is_returned_as_it_is_without_contacting_the_portal(self):
        config, env = self.live()
        first, _ = self.submitted()
        submitted = first.artifacts[0].content
        console = FakeConsole("fresh")
        again = self.publish(submitted, console=console, config=config, environ=env)
        self.assertEqual(again.route, "submitted")
        self.assertEqual(console.flows, [])  # idempotent: nothing ran
        self.assertIn("nothing submitted again", again.message)

    def test_no_login_in_the_window_waits_for_a_person_never_a_failure(self):
        for scenario, reason in (("login", "login"), ("captcha", "captcha"),
                                 ("two-factor", "two-factor")):
            with self.subTest(scenario):
                result = self.go(console=FakeConsole(scenario))
                self.assertEqual(result.outcome, StepOutcome.WAITING_FOR_HUMAN, result.message)
                self.assertEqual(result.data["waiting_state"], "WAITING_FOR_HUMAN_LOGIN")
                record = result.artifacts[0].content
                self.assertEqual(record["outcome"], "AUTH_REQUIRED")
                self.assertEqual(record["human_required"]["reason"], reason)
                self.assertEqual(record["state"], "validated")

    def test_a_live_visit_without_a_saved_draft_is_never_a_success(self):
        config, env = self.live()
        result = self.go(console=FakeConsole("unsaved"), config=config, environ=env)
        self.assertEqual(result.outcome, StepOutcome.WAITING_FOR_HUMAN)
        record = result.artifacts[0].content
        self.assertEqual(record["outcome"], "UNKNOWN")
        self.assertEqual(record["human_required"]["reason"], "ambiguous-portal-state")
        self.assertEqual(record["state"], "validated")

    def test_an_ambiguous_portal_state_after_a_submit_is_never_a_success(self):
        result, _ = self.submitted("ambiguous")
        self.assertEqual(result.outcome, StepOutcome.WAITING_FOR_HUMAN)
        record = result.artifacts[0].content
        self.assertEqual(record["outcome"], "UNKNOWN")
        self.assertEqual(record["human_required"]["reason"], "ambiguous-portal-state")
        self.assertEqual(record["state"], "validated")

    def test_a_rejection_read_back_is_a_failure_a_person_records(self):
        result, _ = self.submitted("rejected")
        self.assertEqual((result.outcome, result.retryable), (StepOutcome.FAILED, False))
        self.assertEqual(result.artifacts[0].content["outcome"], "REJECTED")

    def test_an_upload_error_and_a_crash_are_failures_not_retried(self):
        result = self.go(console=FakeConsole("upload-error"))
        self.assertEqual((result.outcome, result.retryable), (StepOutcome.FAILED, False))
        self.assertEqual(result.artifacts[0].content["outcome"], "PLATFORM_ERROR")
        result = self.go(console=FakeConsole(crash=True))
        self.assertEqual((result.outcome, result.retryable), (StepOutcome.FAILED, False))
        self.assertEqual(result.artifacts[0].content["outcome"], "RETRYABLE_FAILURE")

    def test_no_browser_is_blocked_not_a_publication_failure(self):
        result = self.go(console=FakeConsole(no_browser=True))
        self.assertEqual((result.outcome, result.retryable), (StepOutcome.FAILED, False))
        self.assertEqual(result.artifacts[0].content["outcome"], "BLOCKED")
        self.assertIn("playwright install chromium", result.error)

    def test_a_person_s_done_records_a_manual_submission_and_abandon_ends_it(self):
        human = {"decision": "done", "decided_by": "human", "note": "portal ref 4711"}
        result = self.go(decision=human)
        self.assertEqual((result.outcome, result.route), (StepOutcome.SUCCESS, "submitted"))
        record = result.artifacts[0].content
        self.assertEqual((record["outcome"], record["state"], record["measurement_class"]),
                         ("SUBMITTED", "submitted", "human"))
        self.assertEqual(record["submission"]["portal_reference"], "portal ref 4711")
        result = self.go(decision={"decision": "done", "decided_by": "automation"})
        self.assertEqual(result.outcome, StepOutcome.WAITING_FOR_HUMAN)
        result = self.go(decision={"decision": "abandon", "decided_by": "human", "note": "no"})
        self.assertEqual((result.outcome, result.retryable), (StepOutcome.FAILED, False))
        self.assertEqual(result.artifacts[0].content["outcome"], "BLOCKED")

    def test_a_human_required_record_waits_without_contacting_anything(self):
        self.write_metadata()
        manual = self.validate().artifacts[0].content  # core generic-web: manual
        console = FakeConsole("fresh")
        result = self.publish(manual, console=console)
        self.assertEqual(result.outcome, StepOutcome.WAITING_FOR_HUMAN)
        self.assertEqual(console.flows, [])
        self.assertEqual(result.artifacts[0].content["human_required"]["reason"],
                         "manual-submission")

    def test_a_package_changed_since_validation_is_an_invalid_build(self):
        with open(os.path.join(self.release_dir, "generic-web.zip"), "ab") as handle:
            handle.write(b"tamper")
        console = FakeConsole("fresh")
        result = self.go(console=console)
        self.assertEqual((result.outcome, result.retryable), (StepOutcome.FAILED, False))
        self.assertEqual(result.artifacts[0].content["outcome"], "INVALID_BUILD")
        self.assertEqual(console.flows, [])

    def test_no_session_reaches_the_flow_and_the_browser_is_headed(self):
        console = FakeConsole("fresh")
        result = self.go(console=console)
        flow = console.flows[0]
        self.assertNotIn("storage", json.dumps(flow).lower())
        self.assertFalse(flow["headless"])  # a person logs in, in the window it opens
        self.assertIsNone(flow["test_human"])
        self.assertEqual(flow["allowed_origins"], ["http://127.0.0.1:1"])
        archive = next(i for i in flow["intents"] if i["id"] == "upload.archive")
        self.assertEqual(archive["files"][0]["name"], "generic-web.zip")
        self.assertNotIn(COOKIE, json.dumps(result.artifacts[0].content))

    def test_the_shipped_listing_reaches_the_console_intent_by_intent_and_locale_by_locale(self):
        self.write_listing()
        console = FakeConsole("fresh")
        result = self.go(console=console)
        self.assertEqual(result.route, "dry-run", result.error or result.message)
        fills = {(i["id"], i["locale"]): i["value"] for i in console.flows[0]["intents"]
                 if i.get("action") == "fill"}
        self.assertEqual(fills[("field.title", None)], "Fixture Game")
        for locale in ("en", "ru"):
            self.assertEqual(fills[("field.description", locale)], LISTING[locale]["long_description"])
        noted = [e for e in result.artifacts[0].content["evidence"]
                 if e.get("phase") == "prepare" and "flow for the console" in e["summary"]]
        self.assertIn("field.description", noted[0]["data"]["intents"])

    # -- the campaign: what fills the portal, checked before anything is uploaded -----------

    def test_the_campaign_hash_is_recorded_and_is_the_shipped_campaigns(self):
        from wgf_publish import campaign
        result = self.go(console=FakeConsole("fresh"))
        self.assertEqual(result.route, "dry-run", result.error or result.message)
        record = result.artifacts[0].content
        shipped = campaign.load(self.release_dir, "generic-web")
        self.assertEqual(record["submission"]["campaign_hash"], shipped.campaign_hash())
        checked = [e for e in record["evidence"] if e.get("phase") == "prepare"
                   and "campaign media checked" in e["summary"]]
        self.assertEqual(checked[0]["data"]["campaign_hash"], shipped.campaign_hash())

    def test_media_without_capture_provenance_or_a_placeholder_is_never_uploaded(self):
        from campaign_fixture import placeholder_png
        cases = {
            "capture-commit-mismatch": dict(commit="b" * 40),
            "placeholder": dict(rendition_extra=[({"id": "screenshot-09", "kind": "screenshot",
                                                   "rel": "platforms/generic-web/shot-9.png",
                                                   "source": "landscape-01-play",
                                                   "requirement": "screenshots"},
                                                  placeholder_png(64, 36))]),
            "no-provenance": dict(canonical_extra={"capture": {"kind": "none"}}),
        }
        for code, kw in cases.items():
            with self.subTest(code):
                shutil.rmtree(os.path.join(self.release_dir, "listing"))
                self.write_campaign(**kw)
                console = FakeConsole("fresh")
                result = self.go(console=console)
                self.assertEqual((result.outcome, result.retryable), (StepOutcome.FAILED, False))
                record = result.artifacts[0].content
                self.assertEqual(record["outcome"], "INVALID_METADATA")
                self.assertIn("invalid-media", json.dumps(record["evidence"]))
                self.assertIn(code, record["evidence"][-1]["summary"])
                self.assertEqual(console.flows, [])

    def test_a_shipped_listing_g6_did_not_pin_is_stale(self):
        shutil.rmtree(os.path.join(self.release_dir, "listing"))
        self.write_campaign(listing_hash="sha256:" + "d" * 64)
        console = FakeConsole("fresh")
        result = self.go(console=console)
        self.assertEqual(result.outcome, StepOutcome.BLOCKED)
        self.assertIn("g6-stale", result.message)
        self.assertEqual(console.flows, [])


# -- through the engine ----------------------------------------------------------------------

class ThroughTheEngine(PublishCase):
    """release -> platform-validate -> G5 -> G6 -> submit, the way the workflow wires them."""

    def workflow(self):
        path = os.path.join(self.scratch, "publish-flow.workflow.yaml")
        with open(path, "w") as handle:
            handle.write(textwrap.dedent("""\
                workflow:
                  id: publish-flow
                  version: 1
                  start: verify
                  steps:
                    - id: verify
                      type: test.verify
                      stage: release:qa
                      outputs: [prototype-report, sdk-report, scaffold-record, verification-report, qa-report, review-report, production-quality-report, visual-qa-report, store-listing, listing-validation-report]
                    - id: release
                      type: release
                      stage: release:draft
                      inputs: [qa-report, verification-report, sdk-report, prototype-report, scaffold-record, review-report, production-quality-report, visual-qa-report]
                      outputs: [release-manifest]
                      with: {repo_dir: %(repo)s, required_gates: [], required_listing: false, required_quality: false}
                    - id: platform-validate
                      type: platform-validate
                      stage: release:validating
                      inputs: [release-manifest, verification-report, qa-report, sdk-report, scaffold-record]
                      outputs: [platform-publication]
                      with: {repo_dir: %(repo)s}
                    - id: release-review
                      type: human-checkpoint
                      stage: release:rc
                      inputs: [qa-report, verification-report, release-manifest]
                      outputs: [decision-record]
                      with: {gate: G5, choices: [approve, reject]}
                      on: {reject: $end}
                    - id: publish-review
                      type: human-checkpoint
                      stage: release:approved
                      inputs: [release-manifest, platform-publication, store-listing, listing-validation-report]
                      outputs: [decision-record]
                      with: {gate: G6, choices: [publish, reject]}
                      on: {reject: $end}
                    - id: submit
                      type: publish
                      stage: release:submitting
                      inputs: [release-manifest, platform-publication, decision-record, scaffold-record, verification-report, store-listing, listing-validation-report]
                      outputs: [platform-publication]
                      retry: {max_attempts: 1}
                      with: {repo_dir: %(repo)s}
                """ % {"repo": json.dumps(self.game.root)}))
        return path

    listing_placeholders = staticmethod(listing_placeholders)

    def api(self, console, publish_config):
        from wgflib.workflow import ArtifactOutput, StepResult, WorkflowStep
        from wgflib.workflow.api import WorkflowAPI
        from wgflib.workflow.config import FactoryConfig
        from wgf_release import ReleaseStep

        case = self

        class Verify(WorkflowStep):
            type = "test.verify"

            def execute(self, inputs, context):
                evidence = case.with_assertions(case.game.evidence(run_id=context.run_id))
                # G6 is decided on the store listing too (gates.yaml): this flow carries the
                # mock placeholders, the way a --mock run does; release itself is told the
                # flow has no listing steps (`required_listing: false`).
                evidence.update(case.listing_placeholders())
                return StepResult.success([ArtifactOutput(t, a) for t, a in evidence.items()])

        module = type(sys)("wgf_publish_test_verify")
        module.register = lambda registry: registry.register(Verify.type, Verify)
        sys.modules[module.__name__] = module
        self.addCleanup(sys.modules.pop, module.__name__, None)
        originals = (ReleaseStep.__dict__["environ"], ReleaseStep.__dict__["clock"],
                     PlatformValidateStep.__dict__["environ"], PublishStep.__dict__["environ"],
                     PublishStep.__dict__["run_process"])

        def restore():
            (ReleaseStep.environ, ReleaseStep.clock, PlatformValidateStep.environ,
             PublishStep.environ, PublishStep.run_process) = originals
        self.addCleanup(restore)
        env = dict(self.game.environ(()))
        ReleaseStep.environ = env
        ReleaseStep.clock = staticmethod(lambda: NOW)
        PlatformValidateStep.environ = env
        PublishStep.environ = env
        PublishStep.run_process = console
        config = FactoryConfig({"steps": {"modules": ["wgf_release", "wgf_publish", module.__name__]},
                                "storage": {"fsync": False}, "publish": publish_config})
        return WorkflowAPI(config=config, store_dir=os.path.join(self.scratch, "store"),
                           workflow=self.workflow())

    def test_the_group_runs_g5_g6_and_a_dry_run_submit_in_one_run(self):
        from wgflib.workflow.api import RunRequest
        from wgflib.workflow.model import RunStatus
        self.write_metadata()
        console = FakeConsole("fresh")
        api = self.api(console, dict(self.settings()["publish"]))
        state = api.run(RunRequest(project_id="fixture-game"))
        self.assertEqual((state.status, state.cursor), (RunStatus.WAITING, "release-review"),
                         state.message)
        state = api.run(RunRequest(resume=state.run_id, decision="approve", decided_by="human"))
        self.assertEqual((state.status, state.cursor), (RunStatus.WAITING, "publish-review"),
                         state.message)
        # G6 refuses automation, whatever it says.
        refused = api.run(RunRequest(resume=state.run_id, decision="publish",
                                     decided_by="automation"))
        self.assertEqual((refused.status, refused.cursor), (RunStatus.WAITING, "publish-review"))
        self.assertEqual(console.flows, [])
        state = api.run(RunRequest(resume=state.run_id, decision="publish", decided_by="human",
                                   note="ship it"))
        self.assertEqual(state.status, RunStatus.COMPLETED, state.message)
        trail = [e["step"] for e in state.trail]
        self.assertEqual(trail[-1], "submit")
        self.assertEqual(trail[-5:-1], ["release-review", "publish-review", "publish-review",
                                        "publish-review"])  # waited, refused automation, published
        stored = api.store.load(state.run_id)
        record = api.store.read_artifact(state.run_id, stored.latest_artifact("platform-publication-generic-web"))
        self.assertEqual(record["outcome"], "DRY_RUN")
        self.assertEqual(console.flows[0]["mode"], "dry-run")
        # The G6 record pins the manifest the submit step was given.
        g6 = api.store.read_artifact(state.run_id, stored.latest_artifact("decision-record-publish-review"))
        manifest = api.store.read_artifact(state.run_id, stored.latest_artifact("release-manifest"))
        self.assertEqual(g6["gate_id"], "G6")
        self.assertEqual(g6["decided_by"]["mode"], "human")
        pinned = {s["artifact_type"]: s["content_hash"] for s in g6["subject"]}
        self.assertEqual(pinned["release-manifest"], manifest["provenance"]["content_hash"])
        self.assertEqual(set(pinned), {"release-manifest", "store-listing", "listing-validation-report"})
        self.assertEqual(record["submission"]["authorized_by"]["release_manifest_hash"],
                         manifest["provenance"]["content_hash"])
        # No credential reached the event log.
        for line in api.store.read_events(state.run_id):
            self.assertNotIn(COOKIE, json.dumps(line))

    def test_a_human_required_platform_parks_the_run_until_a_person_answers(self):
        from wgflib.workflow.api import RunRequest
        from wgflib.workflow.model import RunStatus
        self.write_metadata()
        api = self.api(FakeConsole("fresh"), {})  # core's generic-web profile: manual
        state = api.run(RunRequest(project_id="fixture-game"))
        state = api.run(RunRequest(resume=state.run_id, decision="approve", decided_by="human"))
        state = api.run(RunRequest(resume=state.run_id, decision="publish", decided_by="human"))
        self.assertEqual((state.status, state.cursor), (RunStatus.WAITING, "submit"), state.message)
        pending = api.pending(state)
        self.assertEqual(pending["choices"], ["done", "abandon"])
        state = api.run(RunRequest(resume=state.run_id, decision="done", decided_by="human",
                                   note="emailed, ticket 12"))
        self.assertEqual(state.status, RunStatus.COMPLETED, state.message)
        stored = api.store.load(state.run_id)
        record = api.store.read_artifact(state.run_id, stored.latest_artifact("platform-publication-generic-web"))
        self.assertEqual((record["outcome"], record["state"], record["measurement_class"]),
                         ("SUBMITTED", "submitted", "human"))


# -- a real browser against the fixture portal (opt-in) ---------------------------------------

@unittest.skipUnless(enabled("WGF_PUBLISH_BROWSER_TEST"),
                     "set WGF_PUBLISH_BROWSER_TEST=1 to drive the fixture portal with Chromium")
class Browser(PublishCase):
    """The real console executor through the step, in the pinned template's checkout (its
    Playwright and Chromium), headless, against portal.py. Nothing leaves 127.0.0.1. Every
    other browser scenario is test_publish_executor.py's."""

    @classmethod
    def setUpClass(cls):
        from wgflib import template
        cls.template = template.checkout()
        template.ensure_dependencies(cls.template)

    def portal(self, mode="open"):
        env = dict(os.environ, PORTAL_MODE=mode, PORTAL_LOCALES="en")
        process = subprocess.Popen([sys.executable, PORTAL, "--port", "0"], stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, text=True, env=env)

        def stop():
            process.kill()
            process.wait(timeout=10)
            process.stdout.close()
        self.addCleanup(stop)
        line = process.stdout.readline().strip()
        self.assertTrue(line.startswith("PORT "), line)
        return int(line.split()[1])

    def state_of(self, port):
        import urllib.request
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/state.json") as response:
            return json.load(response)

    def test_a_dry_run_through_the_step_reaches_save_draft_and_requests_nothing(self):
        port = self.portal()
        self.write_metadata()
        config = self.settings(timeouts={"action": 2500, "navigation": 8000, "upload": 20000})
        config["publish"]["platforms"]["generic-web"].update(
            console_url=f"http://127.0.0.1:{port}/", test_headless=True, poll_ms=250)
        record = self.validate(config=config).artifacts[0].content
        self.assertEqual(record["readiness"], "READY", record.get("guards"))
        # The real pnpm and Playwright, not the fixture game's fake pnpm shim.
        import wgf_publish.browser as browser

        def run_in_template(argv, cwd=None, **kwargs):
            return browser.procs.run(argv, cwd=self.template, **kwargs)
        result = self.publish(record, console=run_in_template, config=config,
                              environ={"PATH": os.environ.get("PATH", "")})
        self.assertEqual((result.outcome, result.route), (StepOutcome.SUCCESS, "dry-run"),
                         result.error or result.message)
        state = self.state_of(port)
        self.assertEqual((state["creates"], state["uploads"], state["saves"], state["requests"]),
                         (1, 1, 1, 0))
        content = result.artifacts[0].content
        self.assertEqual(content["outcome"], "DRY_RUN")
        shots = [e for e in content["evidence"] if e["kind"] == "screenshot"]
        self.assertTrue(shots)
        for shot in shots:
            self.assertTrue(os.path.isfile(os.path.join(self.run_dir, shot["path"])), shot)
            self.assertTrue(shot["content_hash"].startswith("sha256:"))
        actions = [e for e in content["evidence"] if e.get("path", "").endswith("actions.jsonl")]
        self.assertEqual(len(actions), 1)



@unittest.skipUnless(enabled("WGF_PUBLISH_BROWSER_TEST"),
                     "set WGF_PUBLISH_BROWSER_TEST=1 to drive the fixture portal with Chromium")
class CreateBeforeBuildEndToEnd(PublishCase):
    """A Y8-style create-before-build portal, end to end: the real engine, the real release,
    platform-validate and submit steps, and the real console executor in headless Chromium
    against portal.py (`ids-on-create`). The fixture profile is generic-web's, with the ids
    the portal issues on create and where the build carries them.

    Test doubles, because a unit test cannot run the real ones: `test.verify` stands in for
    verify (GameRepository.build_platforms writes the per-platform bundle and its config from
    game.config.yaml, the way verify's platform_builds does - no pnpm build), `test.sdk` for
    the sdk step's portal-id write (the same identity.sync the sdk step calls, then a commit),
    and `test.metadata` for the person or release role writing store-metadata.json into the
    newest release directory. The test plays the person: G5, G6, and `submit`."""

    setUpClass = classmethod(Browser.setUpClass.__func__)
    portal = Browser.portal
    state_of = Browser.state_of

    def setUp(self):
        super().setUp()
        from unittest import mock
        from wgflib.workflow import quality
        # This flow is not one the Factory ships and lacks its required steps, so its run is
        # development class, which the quality policy never submits live (production_only).
        # That rule is tested on the shipped new-game (test_quality_inheritance
        # SubmitReentry); this test is about the publisher, so it is lifted here alone.
        lifted = mock.patch.object(quality, "production_problems", lambda *a, **k: [])
        lifted.start()
        self.addCleanup(lifted.stop)
        # One target: the game is built and released for generic-web only.
        self.game.commit("game.config.yaml", textwrap.dedent("""            game:
              id: fixture-game
              name: Fixture Game
              version: 0.1.0
            build:
              output: dist
            platforms:
              - { id: generic-web, profile: generic-web@1.1.0, role: required }
            """), "one target")

    def workflow(self):
        path = os.path.join(self.scratch, "create-before-build.workflow.yaml")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(textwrap.dedent("""\
                workflow:
                  id: create-before-build
                  version: 1
                  start: verify
                  steps:
                    - id: sdk
                      type: test.sdk
                      stage: title:prototype
                    - id: verify
                      type: test.verify
                      stage: release:qa
                      outputs: [prototype-report, sdk-report, scaffold-record, verification-report, qa-report, review-report, production-quality-report, visual-qa-report, store-listing, listing-validation-report]
                      max_visits: 3
                    - id: release
                      type: release
                      stage: release:draft
                      inputs: [qa-report, verification-report, sdk-report, prototype-report, scaffold-record, review-report, production-quality-report, visual-qa-report]
                      outputs: [release-manifest]
                      with: {repo_dir: %(repo)s, required_gates: [], required_listing: false, required_quality: false}
                      max_visits: 3
                    - id: metadata
                      type: test.metadata
                      stage: release:draft
                      inputs: [release-manifest]
                      max_visits: 3
                    - id: platform-validate
                      type: platform-validate
                      stage: release:validating
                      inputs: [release-manifest, verification-report, qa-report, sdk-report, scaffold-record]
                      outputs: [platform-publication]
                      with: {repo_dir: %(repo)s}
                      max_visits: 3
                    - id: release-review
                      type: human-checkpoint
                      stage: release:rc
                      inputs: [qa-report, verification-report, release-manifest]
                      outputs: [decision-record]
                      with: {gate: G5, choices: [approve, reject]}
                      max_visits: 3
                      on: {reject: $end}
                    - id: publish-review
                      type: human-checkpoint
                      stage: release:approved
                      inputs: [release-manifest, platform-publication, store-listing, listing-validation-report]
                      outputs: [decision-record]
                      with: {gate: G6, choices: [publish, reject]}
                      max_visits: 3
                      on: {reject: $end}
                    - id: submit
                      type: publish
                      stage: release:submitting
                      inputs: [release-manifest, platform-publication, decision-record, scaffold-record, verification-report, store-listing, listing-validation-report]
                      outputs: [platform-publication]
                      retry: {max_attempts: 1}
                      with: {repo_dir: %(repo)s}
                      max_visits: 5
                      on: {platform-ids: sdk}
                """ % {"repo": json.dumps(self.game.root.replace(os.sep, "/"))}))
        return path

    def profiles(self):
        """generic-web's fixture profile, issuing a Game ID and an App ID on create."""
        directory = os.path.join(self.scratch, "publication")
        os.makedirs(directory, exist_ok=True)
        with open(os.path.join(PROFILES, "generic-web.yaml"), encoding="utf-8") as handle:
            text = handle.read()
        anchor = "    title_match: exact-casefold\n"
        self.assertIn(anchor, text)
        text = text.replace(anchor, anchor + textwrap.indent(textwrap.dedent("""\
            issued_on_create:
              - {key: external_game_id, read: [{label: "Game ID"}]}
              - {key: app_id, read: [{label: "App ID"}]}
            build_config: {external_game_id: "platforms[].game_id", app_id: "platforms[].app_id"}
            """), "    "), 1)
        with open(os.path.join(directory, "generic-web.yaml"), "w", encoding="utf-8",
                  newline="\n") as handle:
            handle.write(text)
        return directory

    def engine(self, port):
        from wgflib.workflow import ArtifactOutput, StepResult, WorkflowStep
        from wgflib.workflow.api import WorkflowAPI
        from wgflib.workflow.config import FactoryConfig
        from wgf_publish import common, identity
        from wgf_release import ReleaseStep
        import wgf_publish.browser as browser
        case = self
        self.verified = 0

        class Sdk(WorkflowStep):
            type = "test.sdk"

            def execute(self, inputs, context):
                settings = common.Settings(context.config, {})
                profiles = {"generic-web": common.publication_profile_for("generic-web",
                                                                          settings)}
                written = identity.sync(case.game.root, "fixture-game", profiles, case.titles)
                if written:
                    with open(case.game.path("game.config.yaml"), encoding="utf-8") as handle:
                        case.game.commit("game.config.yaml", handle.read(), "sdk: portal ids")
                return StepResult.success([], message=f"wrote {written}")

        class Verify(WorkflowStep):
            type = "test.verify"

            def execute(self, inputs, context):
                case.verified += 1
                builds = case.game.build_platforms(("generic-web",))
                case.evidence = case.game.evidence(run_id=context.run_id, platform_builds=builds)
                evidence = case.with_assertions(case.evidence)
                evidence.update(listing_placeholders())
                return StepResult.success([ArtifactOutput(t, a) for t, a in evidence.items()])

        class Metadata(WorkflowStep):
            type = "test.metadata"

            def execute(self, inputs, context):
                case.manifest = inputs.load("release-manifest")
                case.release_dir = case.game.path("release", case.manifest["release_id"])
                case.write_metadata()  # and the campaign, captured from this release's commit
                return StepResult.success([], message=case.release_dir)

        module = type(sys)("wgf_publish_test_create_before_build")
        module.register = lambda registry: [registry.register(c.type, c)
                                            for c in (Sdk, Verify, Metadata)]
        sys.modules[module.__name__] = module
        self.addCleanup(sys.modules.pop, module.__name__, None)
        saved = {(cls, name): cls.__dict__.get(name) for cls, name in (
            (ReleaseStep, "environ"), (ReleaseStep, "clock"), (PlatformValidateStep, "environ"),
            (PublishStep, "environ"), (PublishStep, "run_process"))}
        self.addCleanup(lambda: [setattr(cls, name, value) for (cls, name), value
                                 in saved.items()])
        env = dict(self.game.environ(()))
        ReleaseStep.environ = env
        ReleaseStep.clock = staticmethod(lambda: NOW)
        PlatformValidateStep.environ = env
        # Live twice over: factory.publish.mode live AND WGF_PUBLISH_LIVE=1.
        # The real pnpm and Playwright, not the fixture game's fake pnpm shim.
        PublishStep.environ = dict(self.environ, PATH=os.environ.get("PATH", ""),
                                   WGF_PUBLISH_LIVE="1")

        def run_in_template(argv, cwd=None, **kwargs):
            return browser.procs.run(argv, cwd=case.template, **kwargs)
        PublishStep.run_process = staticmethod(run_in_template)
        publish = self.settings(mode="live", profiles_extra=[self.profiles()],
                                timeouts={"action": 2500, "navigation": 8000, "upload": 20000})
        publish["publish"]["platforms"]["generic-web"].update(
            console_url=f"http://127.0.0.1:{port}/", test_headless=True, poll_ms=250)
        config = FactoryConfig({"steps": {"modules": ["wgf_release", "wgf_publish",
                                                      module.__name__]},
                                "storage": {"fsync": False}, "publish": publish["publish"]})
        return WorkflowAPI(config=config, store_dir=os.path.join(self.scratch, "store"),
                           workflow=self.workflow())

    def test_create_ids_rebuild_validate_g6_upload_submit(self):
        from wgf_publish import registry as portal_registry
        from wgflib.workflow.api import RunRequest
        from wgflib.workflow.model import RunStatus
        port = self.portal("open,ids-on-create")
        api = self.engine(port)

        def answer(state, choice, note=None):
            return api.run(RunRequest(resume=state.run_id, decision=choice, decided_by="human",
                                      note=note))

        def guard(record, name):
            return next(g for g in record["guards"] if g.get("id", g.get("guard")) == name)

        def record(state):
            stored = api.store.load(state.run_id)
            return api.store.read_artifact(state.run_id, stored.latest_artifact(
                "platform-publication-generic-web"))

        # 1. Verify, release, validate: the ids are not issued yet, so the guard is GREEN.
        state = api.run(RunRequest(project_id="fixture-game"))
        self.assertEqual((state.status, state.cursor), (RunStatus.WAITING, "release-review"),
                         state.message)
        validated = record(state)
        self.assertEqual(validated["readiness"], "READY", validated["guards"])
        self.assertIn("not issued yet", json.dumps(guard(validated, "platform_ids_present")))
        state = answer(state, "approve")
        # 2. G6, then the first visit creates the game and stops IDS_ISSUED: nothing uploaded.
        state = answer(state, "publish", note="ship it")
        self.assertEqual((state.status, state.cursor), (RunStatus.WAITING, "release-review"),
                         state.message)
        portal = self.state_of(port)
        self.assertEqual((portal["creates"], portal["uploads"], portal["requests"]), (1, 0, 0))
        game = portal["games"][0]
        trail = [e["step"] for e in state.trail]
        self.assertEqual(trail[trail.index("sdk") - 1], "submit")  # route platform-ids
        entry = portal_registry.load("fixture-game", self.titles).get("generic-web")
        self.assertEqual((entry["status"], entry["external_game_id"], entry["app_id"]),
                         ("DRAFT_CREATED", game["id"], game["app_id"]))
        # 3. sdk wrote the ids into game.config.yaml; verify built and release packaged again.
        self.assertEqual(self.verified, 2)
        with open(self.game.path("game.config.yaml"), encoding="utf-8") as handle:
            config = handle.read()
        self.assertIn(f"game_id: {game['id']}", config)
        self.assertIn(f"app_id: {game['app_id']}", config)
        with open(self.game.path("build", "platforms", "generic-web", "game.config.json"),
                  encoding="utf-8") as handle:
            self.assertIn(game["app_id"], handle.read())
        # 4. platform-validate on the rebuilt release: platform_ids_present is GREEN on the ids.
        validated = record(state)
        self.assertEqual(validated["readiness"], "READY", validated["guards"])
        self.assertIn("carries", json.dumps(guard(validated, "platform_ids_present")))
        # 5. G5 and G6 again (the manifest changed); the visit uploads to the same game.
        state = answer(state, "approve")
        state = answer(state, "publish", note="the rebuilt release")
        self.assertEqual((state.status, state.cursor), (RunStatus.WAITING, "submit"),
                         state.message)
        self.assertEqual(api.pending(state)["choices"], ["submit", "hold", "abandon", "done"])
        uploaded = record(state)
        self.assertEqual(uploaded["outcome"], "UPLOAD_COMPLETE", uploaded.get("evidence"))
        self.assertEqual(uploaded["waiting"]["state"], "WAITING_FOR_HUMAN_SUBMIT_CONFIRMATION")
        portal = self.state_of(port)
        self.assertEqual((portal["creates"], portal["uploads"], portal["requests"]), (1, 1, 0))
        # 6. A person answers submit: review is requested once, read back from the status text.
        state = answer(state, "submit", note="looked at the draft")
        self.assertEqual(state.status, RunStatus.COMPLETED, state.message)
        submitted = record(state)
        self.assertEqual((submitted["outcome"], submitted["state"]), ("SUBMITTED", "submitted"),
                         submitted.get("evidence"))
        self.assertEqual(submitted["verified_state"]["observed"], "Waiting for moderation")
        portal = self.state_of(port)
        self.assertEqual((portal["creates"], portal["uploads"], portal["requests"],
                          portal["double_requests"]), (1, 1, 1, 0))
        entry = portal_registry.load("fixture-game", self.titles).get("generic-web")
        self.assertEqual(entry["status"], "PENDING_REVIEW")


if __name__ == "__main__":
    unittest.main()

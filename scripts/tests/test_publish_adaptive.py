"""The bounded adaptive mode (docs/portal-publishing-architecture.md 2.6): the resolver side
(scripts/wgf_publish/adaptive.py), the flow's `adaptive` block, the outcome mapping, the
drift-review command - and, opt-in, real headless Chromium against the fixture portal with a
SCRIPTED resolver: every proposal is checked by the executor itself before it acts.

    python -m unittest scripts/tests/test_publish_adaptive.py
    WGF_PUBLISH_BROWSER_TEST=1 python -m unittest scripts/tests/test_publish_adaptive.py

No test calls a model, and none contacts a real portal.
"""

import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, HERE)

import test_publish_executor as tpe  # noqa: E402
from testenv import enabled  # noqa: E402
from wgf_publish import adaptive, outcomes  # noqa: E402
from wgf_publish.adapters.fixture import FixturePortalAdapter  # noqa: E402
from wgflib import redact  # noqa: E402
from wgflib.yamllite import load  # noqa: E402

GOOD = {"kind": "resolve", "locator": {"label": "Game name"}, "reason": "the Title field was renamed"}


def on(resolver, **extra):
    """Adaptive settings as the step would hand them: on, with this resolver."""
    return adaptive.AdaptiveSettings(True, resolver, timeout_s=extra.pop("timeout_s", 20), **extra)


# -- answers, bounds, settings ---------------------------------------------------------------------

class Answers(unittest.TestCase):
    def test_each_kind_parses_and_anything_else_is_stop(self):
        self.assertEqual(adaptive.parse_answer(json.dumps(GOOD)), GOOD)
        self.assertEqual(adaptive.parse_answer("thinking...\n```json\n" + json.dumps(GOOD) + "\n```"), GOOD)
        dismiss = {"kind": "dismiss", "locator": {"role": "button", "name": "Got it"}, "reason": "tour"}
        self.assertEqual(adaptive.parse_answer(dismiss), dismiss)
        self.assertEqual(adaptive.parse_answer({"kind": "navigate", "path": "/console", "reason": "r"})["path"],
                         "/console")
        self.assertEqual(adaptive.parse_answer({"kind": "stop", "reason": "unsure"})["kind"], "stop")
        malformed = (
            "click the Save button", "", None, [GOOD], {"kind": "click", "reason": "r"},
            {"kind": "resolve", "locator": {"label": "x"}},                       # no reason
            {"kind": "resolve", "reason": "r"},                                   # no locator
            {"kind": "resolve", "locator": {"label": "x", "css": "y"}, "reason": "r"},   # two rungs
            {"kind": "resolve", "locator": {"css": "input", "index": 1}, "reason": "r"},  # nth()
            {"kind": "resolve", "locator": {"x": 10, "y": 20}, "reason": "r"},    # coordinates
            {"kind": "resolve", "locator": {"label": "x", "name": "y"}, "reason": "r"},
            {"kind": "resolve", "locator": {"label": "x"}, "reason": "r", "script": "el.click()"},
            {"kind": "resolve", "locator": {"label": "x"}, "reason": "r", "keys": "Tab Enter"},
            {"kind": "navigate", "reason": "r"},
            {"kind": "stop", "reason": "r", "locator": {"label": "x"}},
        )
        for raw in malformed:
            with self.subTest(raw=raw):
                answer = adaptive.parse_answer(raw)
                self.assertEqual(answer["kind"], "stop")
                self.assertIn("malformed", answer["reason"])

    def test_action_and_value_are_passed_on_for_the_executor_to_refuse(self):
        answer = adaptive.parse_answer(dict(GOOD, action="click", value="Evil"))
        self.assertEqual((answer["action"], answer["value"]), ("click", "Evil"))

    def test_bounds_only_go_down(self):
        self.assertEqual(adaptive.bounds(), {"max_per_intent": 3, "max_per_visit": 10})
        self.assertEqual(adaptive.bounds({"max_per_intent": 5, "max_per_visit": 50}),
                         {"max_per_intent": 3, "max_per_visit": 10})
        self.assertEqual(adaptive.bounds({"max_per_intent": 2}, {"max_per_visit": 4, "max_per_intent": 9}),
                         {"max_per_intent": 2, "max_per_visit": 4})
        self.assertEqual(adaptive.bounds({"max_per_intent": -1, "max_per_visit": "9"}),
                         {"max_per_intent": 3, "max_per_visit": 10})

    def test_settings_come_from_configuration_and_default_off(self):
        class NoJob:
            pass
        command = {"kind": "command", "argv": ["agent", "{prompt}"]}
        cases = (
            ({}, False, None),
            ({"publish": {"adaptive": True}}, False, "resolver"),
            ({"publish": {"adaptive": False, "resolver": command}}, False, "adaptive is not true"),
            ({"publish": {"adaptive": True, "resolver": command}}, True, None),
            ({"publish": {"adaptive": True, "resolver": {"kind": "agent-sdk"}}}, False, "none or command"),
        )
        for config, available, reason in cases:
            with self.subTest(config=config):
                settings = adaptive.settings_for(NoJob(), {}, config=config, environ={})
                self.assertEqual(settings.available, available)
                if reason:
                    self.assertIn(reason, settings.unavailable_reason())
        settings = adaptive.settings_for(NoJob(), {"adaptive": False},
                                         config={"publish": {"adaptive": True, "resolver": command}})
        self.assertFalse(settings.available)
        # The shipped configuration: off.
        self.assertFalse(adaptive.settings_for(NoJob(), {}).available)

    def test_the_resolver_environment_carries_no_publish_variable(self):
        environ = {"PATH": "/bin", "HOME": "/h", "AGENT_API_KEY": "k-123", "WGF_PUBLISH_LIVE": "1",
                   "WGF_PUBLISH_PORTAL_TOKEN": "t-456", "PORTAL_TOKEN": "p-789", "GH_TOKEN": "g"}
        config = {"agents": {"env_passthrough": ["AGENT_API_KEY", "PORTAL_TOKEN", "WGF_PUBLISH_*"]},
                  "publish": {"env_passthrough": ["PORTAL_TOKEN"]}}
        env = adaptive.resolver_env(config, environ)
        self.assertEqual(env.get("AGENT_API_KEY"), "k-123")
        for name in ("WGF_PUBLISH_LIVE", "WGF_PUBLISH_PORTAL_TOKEN", "PORTAL_TOKEN", "GH_TOKEN"):
            self.assertNotIn(name, env)


class Commands(unittest.TestCase):
    """The release role through the agent runner: a real process under wgflib.procs, here a
    Python one-liner standing in for the agent host - never a model."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="wgf-resolver-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def resolver(self, code, answer_from="stdout", timeout=20):
        argv = [sys.executable, "-c", code, "{request}", "{answer}"]
        resolver = adaptive.CommandResolver(argv, adaptive.resolver_env({}, os.environ), timeout,
                                            answer_from)
        resolver.workdir = self.tmp
        return resolver

    def test_stdout_and_file_answers(self):
        code = ("import json,sys; r=json.load(open(sys.argv[1],encoding='utf-8')); "
                "print('noise'); print(json.dumps({'kind':'resolve','locator':{'label':r['intent']['names'][0]},"
                "'reason':'from the snapshot'}))")
        request = {"seq": 1, "intent": {"id": "field.title", "names": ["Game name"]}, "snapshot": []}
        answer = adaptive.parse_answer(self.resolver(code).propose(request))
        self.assertEqual(answer["locator"], {"label": "Game name"})
        written = ("import json,sys; json.dump({'kind':'stop','reason':'unsure'}, open(sys.argv[2],'w'))")
        self.assertEqual(adaptive.parse_answer(self.resolver(written, "file").propose(request))["kind"], "stop")
        with open(os.path.join(self.tmp, "resolver-01.request.json"), encoding="utf-8") as handle:
            given = json.load(handle)
        self.assertEqual(given["answer_schema"], adaptive.ANSWER_SCHEMA)

    def test_failures_are_stop(self):
        request = {"seq": 1, "intent": {"id": "x"}}
        self.assertIn("exited 3", adaptive.parse_answer(
            self.resolver("import sys; sys.exit(3)").propose(request))["reason"])
        self.assertIn("within", adaptive.parse_answer(
            self.resolver("import time; time.sleep(30)", timeout=1).propose(request))["reason"])
        self.assertIn("malformed", adaptive.parse_answer(
            self.resolver("print('just click Save')").propose(request))["reason"])


class Protocol(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="wgf-drift-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.addCleanup(redact.forget)

    def exchange(self, resolver, request):
        with adaptive.Responder(resolver, self.tmp, poll_s=0.02) as responder:
            with open(responder.request_path, "w", encoding="utf-8") as handle:
                json.dump(request, handle)
            deadline = time.time() + 10
            while time.time() < deadline:
                if os.path.exists(responder.response_path):
                    with open(responder.response_path, encoding="utf-8") as handle:
                        return json.load(handle)
                time.sleep(0.02)
        self.fail("no response")

    def test_one_request_one_scrubbed_answer(self):
        redact.register("portal-secret-0123456789")
        resolver = adaptive.ScriptedResolver([GOOD])
        request = {"seq": 7, "portal": "generic-web", "intent": {"id": "field.title", "value": "x",
                                                                  "names": ["Game name"]},
                   "why": "renamed", "snapshot": [{"role": "textbox", "text": "portal-secret-0123456789"}],
                   "cookies": "never", "headers": {"a": "b"}}
        response = self.exchange(resolver, request)
        self.assertEqual(response, {"seq": 7, "proposal": GOOD})
        given = resolver.requests[0]
        self.assertNotIn("value", given["intent"])
        self.assertNotIn("cookies", given)
        self.assertNotIn("headers", given)
        self.assertNotIn("portal-secret-0123456789", json.dumps(given))

    def test_a_failing_or_malformed_resolver_is_stop(self):
        def boom(_request):
            raise RuntimeError("model unavailable")
        self.assertEqual(self.exchange(adaptive.ScriptedResolver(boom), {"seq": 1})["proposal"]["kind"], "stop")
        self.assertEqual(self.exchange(adaptive.ScriptedResolver(["{not json"]), {"seq": 1})["proposal"]["kind"],
                         "stop")


# -- the adapter: the flow block, the outcome, drift.json --------------------------------------------

class AdapterCase(tpe.ExecutorCase):
    def run_with(self, result, resolver_settings=None, actions=(), drift=None, profile=None, **job):
        runner = tpe.FakeRunner(result, actions)
        original = runner.__call__

        def call(argv, **kwargs):
            out = original(argv, **kwargs)
            if drift is not None:
                flow = runner.flows[-1]
                with open(flow["adaptive"]["drift_path"], "w", encoding="utf-8") as handle:
                    json.dump(drift, handle)
            return out
        job_ = self.release.job(run_process=call, **job)
        if resolver_settings is not None:
            job_.adaptive = resolver_settings
        publication = self.adapter(profile=profile).publish(job_)
        return publication, runner


class Adapter(AdapterCase):
    def test_off_by_default_and_on_only_when_profile_and_installation_allow(self):
        _, runner = self.run_with(tpe.completed())
        block = runner.flows[0]["adaptive"]
        self.assertFalse(block["enabled"])
        self.assertIn("factory.publish.adaptive", block["unavailable"])
        _, runner = self.run_with(tpe.completed(), on(adaptive.ScriptedResolver([])))
        block = runner.flows[0]["adaptive"]
        self.assertTrue(block["enabled"], block)
        self.assertEqual((block["max_per_intent"], block["max_per_visit"]), (3, 10))
        self.assertIn("Supprimer", block["deny"])
        self.assertIn("submit", block["deny"])
        self.assertEqual(block["dismissable"], ["Close", "Got it", "Skip", "Not now"])
        title = next(i for i in runner.flows[0]["intents"] if i["id"] == "field.title")
        self.assertEqual(title["names"], ["Title", "Game title", "Game name"])
        self.assertEqual(title["page"], "^/console/game/[^/]+$")
        forbidden = copy.deepcopy(self.profile)
        forbidden["submission"]["adaptive"] = "forbidden"
        _, runner = self.run_with(tpe.completed(), on(adaptive.ScriptedResolver([])), profile=forbidden)
        self.assertFalse(runner.flows[0]["adaptive"]["enabled"])
        self.assertIn("forbidden", runner.flows[0]["adaptive"]["unavailable"])
        _, runner = self.run_with(tpe.completed(), adaptive.AdaptiveSettings(True, None))
        self.assertIn("no resolver", runner.flows[0]["adaptive"]["unavailable"])
        _, runner = self.run_with(tpe.completed(), on(adaptive.ScriptedResolver([]),
                                                      bounds={"max_per_visit": 2}))
        self.assertEqual(runner.flows[0]["adaptive"]["max_per_visit"], 2)

    def test_measurement_class_follows_an_adaptive_action_that_ran(self):
        acted = [{"seq": 1, "phase": "fill_metadata", "intent": "field.title", "adaptive": True,
                  "source": "adaptive", "acted": True, "result": "ok"}]
        publication, _ = self.run_with(tpe.completed(), on(adaptive.ScriptedResolver([])), actions=acted,
                                       live=True)
        self.assertEqual(publication.measurement_class, "automation-console-adaptive")
        asked = [dict(acted[0], acted=False, result="refused")]
        publication, _ = self.run_with(tpe.completed(), on(adaptive.ScriptedResolver([])), actions=asked,
                                       live=True)
        self.assertEqual(publication.measurement_class, "automation-console")

    def test_drift_json_gets_proposed_patches_and_is_evidence(self):
        drift = {"portal": "generic-web", "entries": [
            {"intent": "field.title", "phase": "fill_metadata", "outcome": "ok", "why": "renamed",
             "failed_ladder": [{"role": "textbox", "name": "Title"}, {"css": "input[name=title]"}],
             "worked": {"label": "Game name"}, "proposal": GOOD, "checks": []},
            {"intent": "draft.save", "outcome": "refused", "proposal": GOOD, "checks": [{"check": "deny", "ok": False}]}]}
        publication, runner = self.run_with(tpe.completed(), on(adaptive.ScriptedResolver([])), drift=drift,
                                            live=True)
        with open(runner.flows[0]["adaptive"]["drift_path"], encoding="utf-8") as handle:
            written = json.load(handle)
        patch = written["entries"][0]["proposed_patch"]
        self.assertIn('- {label: "Game name"}', patch)
        self.assertIn("NEW profile version", patch)
        self.assertNotIn("proposed_patch", written["entries"][1])
        self.assertEqual(written["profile"], {"id": "generic-web", "version": "2.1.0"})
        self.assertTrue(any("drift.json" in e.summary for e in publication.evidence))

    def test_an_irreversible_drift_names_the_suggestion_only_as_one(self):
        suggestion = {"proposal": {"kind": "resolve", "locator": {"role": "button", "name": "Send to moderation"},
                                   "reason": "renamed"}}
        result = tpe.completed(outcome="drift", stop={"phase": "request_review", "intent": "review.request",
                                                      "class": "irreversible", "code": "drift-irreversible",
                                                      "reason": "nothing matches", "suggestion": suggestion})
        publication, _ = self.run_with(result, on(adaptive.ScriptedResolver([])), live=True, confirmed=True)
        self.assertEqual((publication.outcome, publication.human_reason), (outcomes.UNKNOWN, "drift-irreversible"))
        self.assertIn("Send to moderation", publication.message)
        self.assertIn("never acted on", publication.message)


class DriftReview(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="wgf-drift-review-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        visit = os.path.join(self.tmp, "run", "submit", "1-1")
        os.makedirs(visit)
        entry = {"intent": "field.title", "outcome": "ok", "worked": {"label": "Game name"},
                 "failed_ladder": [{"role": "textbox", "name": "Title"}], "proposal": GOOD,
                 "checks": [{"check": "names", "ok": True}], "why": "renamed"}
        entry["proposed_patch"] = adaptive.proposed_patch(entry, {"id": "generic-web", "version": "2.1.0"})
        with open(os.path.join(visit, "drift.json"), "w", encoding="utf-8") as handle:
            json.dump({"portal": "generic-web", "profile": {"id": "generic-web", "version": "2.1.0"},
                       "entries": [entry]}, handle)
        self.extra = os.path.dirname(tpe.PROFILE)

    def cli(self, *args):
        return subprocess.run([sys.executable, os.path.join(SCRIPTS, "wgf-publish.py"), "--extra", self.extra,
                               "drift-review", os.path.join(self.tmp, "run"), *args],
                              capture_output=True, text=True, cwd=ROOT, encoding="utf-8")

    def test_prints_and_applies_into_a_new_file_only(self):
        with open(tpe.PROFILE, "rb") as handle:
            before = handle.read()
        shown = self.cli()
        self.assertEqual(shown.returncode, 0, shown.stderr)
        self.assertIn("field.title", shown.stdout)
        self.assertIn('{label: "Game name"}', shown.stdout)
        self.assertEqual(self.cli("--apply").returncode, 2)  # no --profile-out
        self.assertEqual(self.cli("--apply", "--profile-out", tpe.PROFILE).returncode, 2)
        out = os.path.join(self.tmp, "generic-web.v2.1.1.yaml")
        applied = self.cli("--apply", "--profile-out", out)
        self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)
        with open(tpe.PROFILE, "rb") as handle:
            self.assertEqual(handle.read(), before)  # the shipped profile is never edited
        with open(out, encoding="utf-8") as handle:
            profile = load(handle.read())
        self.assertEqual(profile["version"], "2.1.1")
        title = next(i for i in profile["submission"]["flow"] if i["id"] == "field.title")
        self.assertEqual(title["target"][0], {"label": "Game name"})
        self.assertEqual(title["target"][1], {"role": "textbox", "name": "Title"})
        self.assertEqual(self.cli("--apply", "--profile-out", out).returncode, 2)  # never overwrites


# -- real Chromium, the fixture portal, a scripted resolver (opt-in) --------------------------------------

@unittest.skipUnless(enabled("WGF_PUBLISH_BROWSER_TEST"),
                     "set WGF_PUBLISH_BROWSER_TEST=1 to drive the fixture portal with Chromium")
class Browser(tpe.ExecutorCase):
    portal = tpe.Browser.portal
    state = tpe.Browser.state

    @classmethod
    def setUpClass(cls):
        from wgflib import template
        cls.template = template.checkout()
        template.ensure_dependencies(cls.template)

    def setUp(self):
        super().setUp()
        self.human = os.path.join(self.tmp, "human.mjs")
        with open(self.human, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(tpe.HUMAN_JS)

    def visit(self, answers, *, live=True, confirmed=False, identity=None, profile=None, settings=None,
              visit="1-1"):
        self.resolver = answers if isinstance(answers, adaptive.ScriptedResolver) else \
            adaptive.ScriptedResolver(answers)
        adapter = FixturePortalAdapter("generic-web", profile or self.profile, {
            "console_url": self.base + "/", "test_headless": True, "test_human": self.human,
            "poll_ms": 250, "login_timeout_s": 30})
        job = self.release.job(live=live, confirmed=confirmed, identity=identity, checkout=self.template,
                               console_url=self.base + "/", visit=visit)
        job.adaptive = settings if settings is not None else on(self.resolver)
        self.scratch = job.scratch_dir
        self.publication = adapter.publish(job)
        return self.publication

    def lines(self):
        path = os.path.join(self.release.run_dir, self.publication.actions_log)
        with open(path, encoding="utf-8") as handle:
            return [json.loads(line) for line in handle if line.strip()]

    def drift(self):
        with open(os.path.join(self.scratch, "drift.json"), encoding="utf-8") as handle:
            return json.load(handle)

    def refused(self, *failed, saves=0):
        """The visit stopped on a refused proposal; `failed` are among the failed checks."""
        publication = self.publication
        self.assertEqual((publication.outcome, publication.human_reason),
                         (outcomes.UNKNOWN, "ambiguous-portal-state"), publication.message)
        self.assertIn("refused", publication.message)
        self.assertEqual(publication.measurement_class, "automation-console")
        entry = self.drift()["entries"][-1]
        self.assertEqual(entry["outcome"], "refused")
        names = [c["check"] for c in entry["checks"] if not c["ok"]]
        for check in failed:
            self.assertIn(check, names, entry["checks"])
        line = [l for l in self.lines() if l.get("adaptive")][-1]
        self.assertEqual((line["result"], line["acted"], line["source"]), ("refused", False, "adaptive"))
        self.assertTrue(line["snapshot_sha256"].startswith("sha256:"))
        self.assertEqual(self.state()["saves"], saves)
        return names

    def test_a_good_resolution_acts_checks_and_proposes_a_patch(self):
        self.portal("drift-title")  # with a login: the request must hold nothing of it
        publication = self.visit([GOOD])
        self.assertEqual(publication.outcome, outcomes.UPLOAD_COMPLETE, publication.message)
        self.assertEqual(publication.measurement_class, "automation-console-adaptive")
        game = self.state()["games"][0]
        self.assertEqual(game["listing"]["game_name"], tpe.TITLE)
        self.assertEqual(self.state()["requests"], 0)
        # actions.jsonl: the proposal, every check passed, the action and its post-condition.
        adaptive_lines = [l for l in self.lines() if l.get("adaptive")]
        acted = [l for l in adaptive_lines if l.get("acted")]
        self.assertEqual(len(acted), 1)
        self.assertEqual((acted[0]["intent"], acted[0]["source"], acted[0]["result"]), ("field.title", "adaptive", "ok"))
        self.assertEqual(acted[0]["locator"], {"label": "Game name"})
        self.assertTrue(all(c["ok"] for c in acted[0]["checks"]))
        self.assertEqual({c["check"] for c in acted[0]["checks"]},
                         {"kind", "no-value", "same-action", "origin", "page", "locator", "unique",
                          "element", "enabled", "role", "names", "deny"})
        self.assertTrue(acted[0]["post_condition"]["ok"])
        # drift.json: the failed ladder, what worked, the patch a person reviews.
        entry = self.drift()["entries"][0]
        self.assertEqual((entry["outcome"], entry["worked"]), ("ok", {"label": "Game name"}))
        self.assertEqual(entry["failed_ladder"][0], {"role": "textbox", "name": "Title"})
        self.assertIn('{label: "Game name"}', entry["proposed_patch"])
        # The request: the intent and the page, never a secret, never a value.
        given = self.resolver.requests[0]
        self.assertEqual(given["intent"]["id"], "field.title")
        self.assertEqual(given["intent"]["names"], ["Title", "Game title", "Game name"])
        with open(os.path.join(self.scratch, "drift-request.json"), encoding="utf-8") as handle:
            text = handle.read()
        for secret in (tpe.PASSWORD, tpe.OTP, "fixture-session-token-0001", "session=",
                       tpe.LISTING["en"]["long_description"]):
            self.assertNotIn(secret, text)
        request = json.loads(text)
        self.assertNotIn("value", request["intent"])
        self.assertTrue(all(n.get("value") in (None, "", "<value>") for n in request["snapshot"]))
        self.assertTrue(any(n.get("labels") == ["Game name"] for n in request["snapshot"]))
        self.assertNotIn("type", [n.get("type") for n in request["snapshot"] if n.get("type") == "password"])

    def test_a_name_outside_the_intent_s_vocabulary_is_refused(self):
        self.portal("open", "drift-title")
        self.visit([{"kind": "resolve", "locator": {"label": "Description (en)"}, "reason": "a textbox"}])
        self.assertEqual(self.refused("names"), ["names"])

    def test_a_deny_vocabulary_name_is_refused_even_when_listed(self):
        self.portal("open", "drift-save")
        profile = copy.deepcopy(self.profile)
        save = next(i for i in profile["submission"]["flow"] if i["id"] == "draft.save")
        save["names"] = list(save["names"]) + ["Save and publish"]
        self.visit([{"kind": "resolve", "locator": {"role": "button", "name": "Save and publish"},
                     "reason": "renamed"}], profile=profile)
        self.assertEqual(self.refused("deny"), ["deny"])

    def test_a_fill_never_becomes_a_click(self):
        self.portal("open", "drift-title")
        self.visit([{"kind": "resolve", "locator": {"role": "button", "name": "Save"}, "action": "click",
                     "reason": "save it"}])
        self.refused("same-action", "role", "names")

    def test_a_value_from_the_resolver_is_refused(self):
        self.portal("open", "drift-title")
        self.visit([dict(GOOD, value="Some Other Game")])
        self.assertEqual(self.refused("no-value"), ["no-value"])
        self.assertNotIn("Some Other Game", json.dumps(self.state()))

    def test_a_foreign_origin_and_a_path_off_the_console_are_refused(self):
        for path in ("http://localhost:{port}/console", "//localhost:{port}/console", "javascript:alert(1)"):
            with self.subTest(path=path):
                base = self.portal("open", "drift-title")
                self.visit([{"kind": "navigate", "path": path.format(port=base.rsplit(":", 1)[1]),
                             "reason": "go"}], visit=f"nav-{len(path)}")
                self.refused("navigate-path")

    def test_the_wrong_page_is_refused(self):
        self.portal("open", "drift-title")
        profile = copy.deepcopy(self.profile)
        next(i for i in profile["submission"]["flow"] if i["id"] == "field.title")["page"] = "^/console/new$"
        self.visit([GOOD], profile=profile)
        self.assertEqual(self.refused("page"), ["page"])

    def test_an_ambiguous_locator_is_refused(self):
        self.portal("open", "drift-title")
        self.visit([{"kind": "resolve", "locator": {"css": "textarea"}, "reason": "the text field"}])
        self.assertEqual(self.refused("unique"), ["unique"])

    def test_the_budget_ends_the_visit(self):
        self.portal("open", "drift-title")
        profile = copy.deepcopy(self.profile)
        profile["submission"]["adaptive_bounds"] = {"max_per_intent": 1, "max_per_visit": 10}
        again = adaptive.ScriptedResolver(lambda request: {"kind": "navigate", "path": request["page"]["path"],
                                                           "reason": "reload the page"})
        publication = self.visit(again, profile=profile)
        self.assertEqual((publication.outcome, publication.human_reason),
                         (outcomes.UNKNOWN, "ambiguous-portal-state"), publication.message)
        self.assertIn("budget is spent (1)", publication.message)
        self.assertEqual(len(again.requests), 1)
        self.assertEqual(self.drift()["entries"][0]["outcome"], "acted")
        self.assertEqual(publication.measurement_class, "automation-console-adaptive")  # the navigate ran
        self.assertEqual(self.state()["saves"], 0)

    def test_a_dismissable_overlay_is_dismissed_and_another_is_refused(self):
        self.portal("open", "overlay")
        publication = self.visit([{"kind": "dismiss", "locator": {"role": "button", "name": "Got it"},
                                   "reason": "a tour hides the form"}])
        self.assertEqual(publication.outcome, outcomes.UPLOAD_COMPLETE, publication.message)
        self.assertEqual(publication.measurement_class, "automation-console-adaptive")
        self.assertEqual(self.state()["saves"], 1)
        dismissed = [l for l in self.lines() if l.get("action") == "adaptive-dismiss"]
        self.assertEqual((dismissed[0]["result"], dismissed[0]["acted"]), ("ok", True))
        self.portal("open", "overlay")
        self.visit([{"kind": "dismiss", "locator": {"role": "button", "name": "Delete game"},
                     "reason": "close it"}], visit="2-1")
        failed = self.refused("dismissable", "deny")
        self.assertNotIn("unique", failed)

    def test_the_irreversible_intent_never_adapts_the_proposal_is_a_suggestion(self):
        self.portal("open", "drift-submit", seed=[{"id": "g0902", "title": tpe.TITLE, "status": "Draft",
                                                   "build": {"filename": "generic-web.zip"}}])
        suggestion = {"kind": "resolve", "locator": {"role": "button", "name": "Send to moderation"},
                      "reason": "the request button was renamed"}
        publication = self.visit([suggestion], confirmed=True, identity={"portal_game_id": "g0902"})
        self.assertEqual((publication.outcome, publication.human_reason),
                         (outcomes.UNKNOWN, "drift-irreversible"), publication.message)
        self.assertIn("Send to moderation", publication.message)
        self.assertIn("suggestion only", publication.message)
        self.assertEqual(self.state()["requests"], 0)
        self.assertEqual(publication.measurement_class, "automation-console")
        self.assertTrue(self.resolver.requests[0]["suggestion_only"])
        entry = self.drift()["entries"][0]
        self.assertEqual((entry["intent"], entry["outcome"]), ("review.request", "suggestion"))
        self.assertIn("SUGGESTION ONLY", entry["proposed_patch"])
        line = [l for l in self.lines() if l.get("adaptive")][0]
        self.assertEqual((line["result"], line["acted"]), ("suggestion", False))

    def test_adaptive_disabled_by_configuration_stops_as_before(self):
        self.portal("open", "drift-title")
        resolver = adaptive.ScriptedResolver([GOOD])
        publication = self.visit(resolver, settings=adaptive.AdaptiveSettings(False, resolver))
        self.assertEqual((publication.outcome, publication.human_reason),
                         (outcomes.UNKNOWN, "ambiguous-portal-state"), publication.message)
        self.assertIn("factory.publish.adaptive is not true", publication.message)
        self.assertEqual(resolver.requests, [])
        self.assertFalse([l for l in self.lines() if l.get("adaptive")])
        self.assertFalse(os.path.exists(os.path.join(self.scratch, "drift-request.json")))

    def test_a_malformed_answer_is_stop(self):
        self.portal("open", "drift-title")
        publication = self.visit(["Sure! Click the field labelled Game name and type the title."])
        self.assertEqual((publication.outcome, publication.human_reason),
                         (outcomes.UNKNOWN, "ambiguous-portal-state"), publication.message)
        self.assertIn("the resolver stopped: malformed", publication.message)
        line = [l for l in self.lines() if l.get("adaptive")][0]
        self.assertEqual((line["result"], line["acted"]), ("stopped", False))
        self.assertEqual(self.state()["saves"], 0)


if __name__ == "__main__":
    unittest.main()

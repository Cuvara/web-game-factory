"""The read-only console observer (scripts/wgf_publish/observe.py, browser/observe.spec.ts):
scrubbing, the summary, the run around a stand-in browser, the spec's own source, and -
opt-in - real headless Chromium against the fixture portal with the test playing the person.

    python -m unittest scripts/tests/test_publish_observe.py
    WGF_PUBLISH_BROWSER_TEST=1 python -m unittest scripts/tests/test_publish_observe.py

No test contacts a real portal. In the browser test the TEST logs in and navigates (a module
the spec loads only headless, only from the test's config); the observer only reads.
"""

import contextlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, HERE)

from testenv import enabled  # noqa: E402
from wgf_publish import observe  # noqa: E402
from wgflib import redact  # noqa: E402
from wgflib.procs import ProcessResult  # noqa: E402
from wgflib.yamllite import load_file  # noqa: E402

FIXTURES = os.path.join(HERE, "fixtures", "publish")
PORTAL = os.path.join(FIXTURES, "portal.py")
COOKIE = "fixture-session-token-0001"
PASSWORD = "correct-horse-battery-staple-42"
PREFILLED = ("Prefilled Title Value", "Prefilled description text", "prefilled-slug-value",
             "support.person@example.com")
EMAILS = ("dev.person@example.com", "support.person@example.com")


def fixture_profile(console_url):
    profile = load_file(os.path.join(FIXTURES, "publication", "generic-web.yaml"))
    origin = console_url.split("/", 3)
    profile["submission"]["console"]["url"] = console_url
    profile["submission"]["console"]["allowed_origins"] = ["/".join(origin[:3])]
    return profile


def page_record(**extra):
    record = {
        "id": "001", "url": "https://console.example/games/new", "trigger": "navigation",
        "observed_at": "2026-10-04T10:00:00Z", "dom_hash": "sha256:" + "a" * 64,
        "screenshot": "pages/001.png", "title": "New game",
        "aria_snapshot": '- heading "New game"\n- textbox "Title": <value>\n'
                         '- text: Signed in as someone@example.org\n'
                         '- link "Games":\n  - /url: /games?page=2&code=zz99',
        "headings": [{"level": 1, "text": "New game"}],
        "forms": [{"index": 0, "accessible_name": "Listing", "heading": "New game", "method": "post"}],
        "fields": [
            {"tag": "input", "role": "textbox", "accessible_name": "Title", "label": "Title",
             "placeholder": None, "type": "text", "required": True, "maxlength": 60,
             "minlength": None, "pattern": None, "accept": None, "multiple": False,
             "options": None, "testid": "title", "name": "title", "id": "t",
             "heading": "New game", "form": 0, "visible": True},
            {"tag": "input", "role": "button", "accessible_name": "Archive", "label": "Archive",
             "placeholder": None, "type": "file", "required": True, "maxlength": None,
             "minlength": None, "pattern": None, "accept": ".zip", "multiple": False,
             "options": None, "testid": None, "name": "archive", "id": None,
             "heading": "New game", "form": 0, "visible": True},
            {"tag": "select", "role": "combobox", "accessible_name": "Genre", "label": "Genre",
             "placeholder": None, "type": "select", "required": False, "maxlength": None,
             "minlength": None, "pattern": None, "accept": None, "multiple": False,
             "options": ["Arcade", "Puzzle"], "testid": None, "name": "genre", "id": None,
             "heading": "New game", "form": 0, "visible": True}],
        "buttons": [{"accessible_name": "Upload", "type": "submit", "disabled": False}],
        "links": [{"accessible_name": "Help", "href": "https://console.example/help?ref=me@example.org#x"}],
        "statuses": [{"text": "Draft", "source": "badge"}],
    }
    record.update(extra)
    return record


class Scrubbing(unittest.TestCase):
    def tearDown(self):
        redact.forget()

    def test_emails_queries_values_and_secrets_never_survive(self):
        redact.register("registered-secret-value-1234")
        record = page_record(value="typed", note="token=abcdef0123456789 and "
                                                 "registered-secret-value-1234",
                             cookies=[{"name": "s", "value": "x"}])
        clean = observe.sanitize_page(record)
        text = json.dumps(clean)
        for secret in ("someone@example.org", "me@example.org", "?ref", "#x", "code=zz99",
                       "abcdef0123456789", "registered-secret-value-1234", '"typed"'):
            self.assertNotIn(secret, text)
        self.assertEqual(clean["value"], observe.VALUE_MASK)
        self.assertEqual(clean["cookies"], observe.VALUE_MASK)
        self.assertEqual(clean["links"][0]["href"], "https://console.example/help")
        self.assertIn(observe.EMAIL_MASK, clean["aria_snapshot"])
        # What an adapter needs is kept.
        self.assertEqual(clean["fields"][0]["maxlength"], 60)
        self.assertEqual(clean["fields"][1]["accept"], ".zip")

    def test_bare_url_is_origin_and_path(self):
        self.assertEqual(observe.bare_url("https://a.example/x/y?code=1#frag"),
                         "https://a.example/x/y")


class Summary(unittest.TestCase):
    def test_the_summary_lists_each_page_its_fields_buttons_and_statuses(self):
        state = {"portal": "fixture", "status": "ENDED", "end_reason": "window_closed",
                 "started_at": "2026-10-04T10:00:00Z"}
        text = observe.summary_markdown(state, [observe.sanitize_page(page_record())])
        self.assertIn("# Console observation: fixture", text)
        self.assertIn("ENDED (window_closed)", text)
        self.assertIn("## 001 https://console.example/games/new", text)
        self.assertIn("Headings: New game", text)
        self.assertRegex(text, r"\| 0 \| Title \| text \| Title \|  \| yes \| max 60 \|")
        self.assertIn("| .zip |", text)
        self.assertIn("Arcade, Puzzle", text)
        self.assertIn("testid=title name=title id=t", text)
        self.assertIn("Buttons: Upload", text)
        self.assertIn("Status texts: Draft", text)
        inventory = observe.field_inventory([page_record()])
        self.assertEqual([f["accessible_name"] for f in inventory], ["Title", "Archive", "Genre"])
        self.assertEqual(inventory[0]["url"], "https://console.example/games/new")

    def test_write_outputs_scrubs_in_place_and_indexes(self):
        out = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, out, True)
        os.makedirs(os.path.join(out, "pages"))
        with open(os.path.join(out, "pages", "001.json"), "w", encoding="utf-8") as handle:
            json.dump(page_record(), handle)
        with open(os.path.join(out, "pages", "002.json"), "w", encoding="utf-8") as handle:
            handle.write("{cut short")
        with open(os.path.join(out, "state.json"), "w", encoding="utf-8") as handle:
            json.dump({"portal": "fixture", "status": "ENDED",
                       "url": "https://console.example/x?session=abc"}, handle)
        state, pages = observe.write_outputs(out)
        self.assertEqual(state["url"], "https://console.example/x")
        self.assertEqual(len(pages), 1)
        self.assertFalse(os.path.exists(os.path.join(out, "pages", "002.json")))
        with open(os.path.join(out, "index.json"), encoding="utf-8") as handle:
            index = json.load(handle)
        self.assertEqual([p["id"] for p in index["pages"]], ["001"])
        everything = ""
        for dirpath, _, names in os.walk(out):
            for name in names:
                with open(os.path.join(dirpath, name), encoding="utf-8") as handle:
                    everything += handle.read()
        self.assertNotIn("@example.org", everything)
        self.assertNotIn("?session", everything)


class SpecSource(unittest.TestCase):
    """The observer cannot act on a page or keep a session: neither is in its source."""

    def setUp(self):
        with open(observe.SPEC, encoding="utf-8") as handle:
            self.source = handle.read()
        self.code = re.sub(r"//[^\n]*", "", self.source)

    def test_no_action_call(self):
        for call in (".click(", ".dblclick(", ".fill(", ".type(", ".press(", ".pressSequentially(",
                     ".check(", ".uncheck(", ".setChecked(", ".selectOption(", ".setInputFiles(",
                     ".tap(", ".hover(", ".dragTo(", ".dispatchEvent(", ".focus(", "keyboard.",
                     "mouse.", "touchscreen.", ".submit(", "requestSubmit", ".route(", ".request."):
            self.assertNotIn(call, self.code, call)
        # The one navigation: the console url, once, before anyone logged in.
        self.assertEqual(self.code.count(".goto("), 1)
        self.assertNotRegex(self.code, r"\.(reload|goBack|goForward)\(")

    def test_no_session_kept_or_read(self):
        for word in ("storageState", "launchPersistentContext", "userDataDir", ".cookies(",
                     "addCookies", "localStorage", "sessionStorage", "tracing", "recordVideo",
                     "recordHar", "WGF_PUBLISH_FLOW"):
            self.assertNotIn(word, self.code, word)
        self.assertIn("browser.newContext()", self.code)
        self.assertIn("context.close()", self.code)


class FakeObserver:
    """Stands in for `pnpm exec playwright test`: writes what the spec would."""

    def __init__(self, status="ENDED", pages=(), returncode=0, output=""):
        self.status, self.pages, self.returncode, self.output = status, pages, returncode, output
        self.calls = []

    def __call__(self, argv, cwd=None, env=None, on_output=None, **kwargs):
        with open(env["WGF_OBSERVE_CONFIG"], encoding="utf-8") as handle:
            config = json.load(handle)
        scratch = os.path.dirname(env["WGF_OBSERVE_CONFIG"])
        with open(argv[-1], encoding="utf-8") as handle:
            playwright_config = handle.read()
        self.calls.append({"argv": argv, "cwd": cwd, "config": config, "scratch": scratch,
                           "playwright_config": playwright_config})
        out = config["out_dir"]
        os.makedirs(os.path.join(out, "pages"), exist_ok=True)
        history = [{"status": "WAITING_FOR_HUMAN_LOGIN"}]
        on_output("stdout", "  WAITING_FOR_HUMAN_LOGIN portal=fixture step=observe "
                            "url=https://console.example/login reason=\"a password field\"")
        if self.status != "LOGIN_TIMEOUT":
            history.append({"status": "AUTHENTICATED"})
        history.append({"status": self.status})
        with open(os.path.join(out, "state.json"), "w", encoding="utf-8") as handle:
            json.dump({"portal": config["portal"], "step": "observe", "status": self.status,
                       "history": history}, handle)
        for page in self.pages:
            with open(os.path.join(out, "pages", f"{page['id']}.json"), "w",
                      encoding="utf-8") as handle:
                json.dump(page, handle)
        return ProcessResult(argv, returncode=self.returncode, stdout=self.output)


class Run(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.checkout = os.path.join(self.tmp, "game")
        os.makedirs(self.checkout)
        with open(os.path.join(self.checkout, "package.json"), "w") as handle:
            handle.write("{}")
        self.out = os.path.join(self.tmp, "out")
        self.lines = []
        self.profile = fixture_profile("https://console.example/console")

    def run_with(self, fake, **kwargs):
        return observe.observe("generic-web", self.profile, self.checkout, self.out,
                               run_process=fake, echo=self.lines.append, **kwargs)

    def test_a_finished_observation_is_scrubbed_indexed_and_leaves_no_scratch(self):
        fake = FakeObserver(pages=[page_record()])
        code, state = self.run_with(fake, authenticated_url="/console")
        self.assertEqual((code, state["status"]), (observe.EXIT_OK, "ENDED"))
        call = fake.calls[0]
        self.assertEqual(call["argv"][:4], ["pnpm", "exec", "playwright", "test"])
        self.assertEqual(call["cwd"], self.checkout)
        self.assertEqual(call["config"]["allowed_origins"], ["https://console.example"])
        self.assertEqual(call["config"]["authenticated_url"], "/console")
        self.assertFalse(call["config"]["headless"])
        self.assertIsNone(call["config"]["test_human"])
        self.assertIn("headless: false", call["playwright_config"])
        self.assertIn('trace: "off"', call["playwright_config"])
        self.assertNotIn("storageState", call["playwright_config"])
        self.assertFalse(os.path.exists(call["scratch"]))
        self.assertEqual(os.listdir(self.checkout), ["package.json"])
        self.assertTrue(any(l.startswith("WAITING_FOR_HUMAN_LOGIN portal=fixture") for l in self.lines))
        for name in ("index.json", "summary.md", "state.json"):
            self.assertTrue(os.path.isfile(os.path.join(self.out, name)), name)
        with open(os.path.join(self.out, "pages", "001.json"), encoding="utf-8") as handle:
            self.assertNotIn("someone@example.org", handle.read())

    def test_a_login_timeout_exits_3_and_a_missing_browser_is_blocked(self):
        code, state = self.run_with(FakeObserver(status="LOGIN_TIMEOUT"))
        self.assertEqual((code, state["status"]), (observe.EXIT_LOGIN_TIMEOUT, "LOGIN_TIMEOUT"))
        self.assertTrue(any("no authenticated_url" in l for l in self.lines))
        code, _ = self.run_with(FakeObserver(status="STARTING", returncode=1,
                                             output="browserType.launch: Executable doesn't exist"))
        self.assertEqual(code, observe.EXIT_ERROR)
        self.assertTrue(any(l.startswith("BLOCKED") for l in self.lines))

    def test_refusals(self):
        with self.assertRaises(observe.ObserveError):
            observe.observe("generic-web", self.profile, self.tmp, self.out,
                            run_process=FakeObserver())
        with self.assertRaises(observe.ObserveError):
            self.run_with(FakeObserver(), test_human="human.mjs")
        profile = fixture_profile("https://console.example/")
        profile["submission"]["console"]["allowed_origins"] = []
        with self.assertRaises(observe.ObserveError):
            observe.observe("generic-web", profile, self.checkout, self.out,
                            run_process=FakeObserver())

    def test_the_profile_may_name_the_authenticated_url(self):
        self.profile["session"] = {"authenticated_url": "^https://console\\.example/console"}
        fake = FakeObserver()
        self.run_with(fake)
        self.assertEqual(fake.calls[0]["config"]["authenticated_url"],
                         "^https://console\\.example/console")

    def test_default_out_is_under_the_project_factory_dir(self):
        import datetime
        when = datetime.datetime(2026, 10, 4, 9, 8, 7, tzinfo=datetime.timezone.utc)
        path = observe.default_out("yandex", when)
        self.assertTrue(path.endswith(os.path.join(".factory", "observations", "yandex",
                                                   "20261004T090807Z")), path)


class Cli(unittest.TestCase):
    def cli(self, *argv):
        sys.path.insert(0, SCRIPTS)
        import importlib.util
        spec = importlib.util.spec_from_file_location("wgf_publish_cli",
                                                      os.path.join(SCRIPTS, "wgf-publish.py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = module.main(list(argv))
        return code, stdout.getvalue(), stderr.getvalue()

    def test_observe_refuses_an_unknown_platform_and_a_non_checkout(self):
        code, _, err = self.cli("observe", "no-such-portal", "--checkout", ".")
        self.assertEqual(code, observe.EXIT_USAGE)
        self.assertIn("no publication profile", err)
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        code, _, err = self.cli("observe", "crazygames", "--checkout", tmp, "--out", tmp)
        self.assertEqual(code, observe.EXIT_USAGE)
        self.assertIn("not a game checkout", err)

    def test_observe_summary_reprints_the_summary_and_the_field_inventory(self):
        out = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, out, True)
        os.makedirs(os.path.join(out, "pages"))
        with open(os.path.join(out, "pages", "001.json"), "w", encoding="utf-8") as handle:
            json.dump(page_record(), handle)
        observe.write_outputs(out)
        code, text, _ = self.cli("observe-summary", out)
        self.assertEqual(code, 0)
        self.assertIn("## 001 https://console.example/games/new", text)
        inventory = json.loads(text[text.index("\n[") + 1:])
        self.assertEqual(len(inventory), 3)
        code, _, err = self.cli("observe-summary", os.path.join(out, "pages"))
        self.assertEqual(code, observe.EXIT_USAGE)


# -- real headless Chromium against the fixture portal (opt-in) -----------------------------

HUMAN = """\
// The test's stand-in for the person: it logs in and moves through the console. The
// observer never does either.
export default async function human(page) {
  await page.waitForSelector("form#login", { timeout: 20000 });
  await page.waitForTimeout(%(pause)d);
  await page.locator("input[name=user]").fill("dev.person@example.com");
  await page.locator("input[name=password]").fill(%(password)s);
  await page.locator("form#login button").click();
  await page.waitForURL("**/console", { timeout: 20000 });
  await page.waitForTimeout(%(pause)d);
  await page.goto(%(observe_url)s);
  await page.waitForTimeout(%(dwell)d);
  await page.close();
}
"""


@unittest.skipUnless(enabled("WGF_PUBLISH_BROWSER_TEST"),
                     "set WGF_PUBLISH_BROWSER_TEST=1 to observe the fixture portal with Chromium")
class Browser(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from wgflib import template
        cls.template = template.checkout()
        template.ensure_dependencies(cls.template)

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def portal(self):
        process = subprocess.Popen([sys.executable, PORTAL, "--port", "0"],
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                   env=dict(os.environ, PORTAL_MODE=""))

        def stop():
            process.kill()
            process.wait(timeout=10)
            process.stdout.close()
        self.addCleanup(stop)
        line = process.stdout.readline().strip()
        self.assertTrue(line.startswith("PORT "), line)
        return int(line.split()[1])

    def get(self, port, path):
        import urllib.request
        with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}") as response:
            return json.load(response)

    def test_the_person_logs_in_the_observer_only_reads_and_keeps_nothing(self):
        port = self.portal()
        base = f"http://127.0.0.1:{port}"
        human = os.path.join(self.tmp, "human.mjs")
        with open(human, "w", encoding="utf-8") as handle:
            handle.write(HUMAN % {"password": json.dumps(PASSWORD), "pause": 1500, "dwell": 4000,
                                  "observe_url": json.dumps(f"{base}/console/observe")})
        out = os.path.join(self.tmp, "out")
        lines = []
        code, state = observe.observe(
            "generic-web", fixture_profile(f"{base}/console"), self.template, out,
            authenticated_url="/console", login_timeout_s=60, max_minutes=2, headless=True,
            test_human=human, echo=lines.append, poll_ms=300, stable_ms=2000)
        self.assertEqual(code, observe.EXIT_OK, "\n".join(lines))
        statuses = [h["status"] for h in state["history"]]
        self.assertEqual(statuses[:2], ["WAITING_FOR_HUMAN_LOGIN", "AUTHENTICATED"], statuses)
        self.assertEqual(statuses[-1], "ENDED")
        self.assertEqual(state["end_reason"], "window_closed")
        waiting = [l for l in lines if l.startswith("WAITING_FOR_HUMAN_LOGIN")]
        self.assertTrue(waiting, lines)
        self.assertIn(f"url={base}/login", waiting[0])
        self.assertIn('action="log in in the opened browser window; handle CAPTCHA/2FA yourself"',
                      waiting[0])
        self.assertIn('resume="the console\'s authenticated page is detected"', waiting[0])

        # The observer read the console and the settings page, never the login page.
        pages = observe.load_pages(out)
        urls = [p["url"] for p in pages]
        self.assertIn(f"{base}/console/observe", urls)
        self.assertNotIn(f"{base}/login", urls)
        settings = next(p for p in pages if p["url"] == f"{base}/console/observe")
        fields = {f["accessible_name"]: f for f in settings["fields"]}
        self.assertEqual((fields["Game title"]["required"], fields["Game title"]["maxlength"],
                          fields["Game title"]["testid"]), (True, 60, "game-title"))
        self.assertEqual(fields["Description"]["minlength"], 20)
        self.assertEqual(fields["Category"]["options"], ["Arcade", "Puzzle", "Racing"])
        self.assertEqual((fields["Game archive"]["type"], fields["Game archive"]["accept"]),
                         ("file", ".zip,application/zip"))
        self.assertTrue(fields["Screenshots"]["multiple"])
        self.assertEqual(fields["my-game"]["pattern"], "[a-z0-9-]+")
        self.assertEqual(fields["Game title"]["heading"], "Listing")
        self.assertEqual(fields["Game archive"]["heading"], "Build")
        self.assertIn("Save draft", [b["accessible_name"] for b in settings["buttons"]])
        statuses = [s["text"] for s in settings["statuses"]]
        self.assertIn("In review", statuses)
        self.assertIn("Draft", statuses)
        self.assertIn("<value>", settings["aria_snapshot"])
        self.assertTrue(os.path.isfile(os.path.join(out, settings["screenshot"])))
        with open(os.path.join(out, "summary.md"), encoding="utf-8") as handle:
            self.assertIn("Game title", handle.read())

        # Nothing secret, typed or prefilled survives anywhere in the output.
        blobs = []
        for dirpath, _, names in os.walk(out):
            for name in names:
                self.assertNotRegex(name, r"(?i)storage|cookie|trace|\.har$|\.zip$|\.webm$")
                with open(os.path.join(dirpath, name), "rb") as handle:
                    blobs.append(handle.read())
        everything = b"\n".join(blobs)
        for secret in (PASSWORD, COOKIE, "session=", "abcdef0123456789", *PREFILLED, *EMAILS):
            self.assertNotIn(secret.encode("utf-8"), everything, secret)

        # The person logged in once and saved nothing; the observer caused no request.
        self.assertEqual(self.get(port, "/state.json")["logins"], 1)
        self.assertEqual(self.get(port, "/observe/state.json")["saves"], 0)
        # The template checkout is left as it was: no scratch, no storage state.
        leftovers = [n for n in os.listdir(self.template) if n.startswith(".wgf-observe")]
        self.assertEqual(leftovers, [])

    def test_no_login_within_the_timeout_is_login_timeout_exit_3(self):
        port = self.portal()
        out = os.path.join(self.tmp, "out")
        lines = []
        code, state = observe.observe(
            "generic-web", fixture_profile(f"http://127.0.0.1:{port}/console"), self.template,
            out, authenticated_url="/console", login_timeout_s=3, max_minutes=1, headless=True,
            echo=lines.append, poll_ms=300)
        self.assertEqual(code, observe.EXIT_LOGIN_TIMEOUT, "\n".join(lines))
        self.assertEqual([h["status"] for h in state["history"]],
                         ["WAITING_FOR_HUMAN_LOGIN", "LOGIN_TIMEOUT"])
        self.assertEqual(observe.load_pages(out), [])


if __name__ == "__main__":
    unittest.main()

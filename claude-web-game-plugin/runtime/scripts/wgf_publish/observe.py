"""The read-only console observer: what a real developer console shows, recorded while a
PERSON uses it (`python scripts/wgf-publish.py observe <platform> --checkout DIR`).

A portal adapter may only be built from what was observed or is officially documented. This
is how the observation is made, under the login model decided on 2026-10-04: the person logs
in, live, in a browser window the Factory opens; the Factory never sees, types, asks for or
stores a password or one-time code, never passes a CAPTCHA or anti-bot check, and never
keeps the session - no storage state is loaded or saved, no persistent profile is used, and
the session ends with the window.

The browser is the game checkout's own Playwright (`pnpm exec playwright test` of
browser/observe.spec.ts, copied into a temporary directory and removed after; the run's
working directory is the checkout, so its Playwright resolves),
under wgflib.procs. The spec writes `<out>/state.json` - WAITING_FOR_HUMAN_LOGIN, then
AUTHENTICATED, then ENDED (or LOGIN_TIMEOUT / LOGIN_ABANDONED) - and one record per observed
page under `<out>/pages/`. This module then scrubs every record (wgflib.redact, email-shaped
strings, any `value` key), and writes `<out>/index.json` and `<out>/summary.md`.

Nothing here clicks, types, uploads or submits: the person navigates. Standard library only.
"""

import datetime
import glob
import json
import os
import re
import shutil
import tempfile

from wgflib import paths, procs, redact

__all__ = ["observe", "ObserveError", "SPEC", "EXIT_OK", "EXIT_ERROR", "EXIT_USAGE",
           "EXIT_LOGIN_TIMEOUT", "default_out", "authenticated_url_of", "sanitize_page",
           "load_pages", "field_inventory", "summary_markdown", "write_outputs", "bare_url"]

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC = os.path.join(HERE, "browser", "observe.spec.ts")
SCRATCH_PREFIX = ".wgf-observe-"
NO_BROWSER = ("Executable doesn't exist", "browserType.launch", "playwright install")
MARKERS = ("WAITING_FOR_HUMAN_LOGIN ", "AUTHENTICATED ", "OBSERVED ", "ENDED ", "LOGIN_TIMEOUT ",
           "LOGIN_ABANDONED ")
EXIT_OK, EXIT_ERROR, EXIT_USAGE, EXIT_LOGIN_TIMEOUT = 0, 1, 2, 3
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
EMAIL_MASK = "<email>"
SNAPSHOT_URL = re.compile(r"(?m)^(\s*- /url:\s*)([^?#\s]*)[?#]\S*$")
VALUE_MASK = "<value>"
CONFIG = """\
import {{ defineConfig }} from "@playwright/test";
export default defineConfig({{
  testDir: {test_dir},
  testMatch: /observe\\.spec\\.ts$/,
  outputDir: {output_dir},
  fullyParallel: false,
  retries: 0,
  workers: 1,
  reporter: [["line"]],
  use: {{ headless: {headless}, viewport: null, trace: "off", video: "off", screenshot: "off" }},
  projects: [{{ name: "observe", use: {{ browserName: "chromium" }} }}],
}});
"""


class ObserveError(ValueError):
    """The observation cannot start: no profile, no console url, no checkout."""


def bare_url(url):
    """Origin and path only: a query or fragment can carry a token, a code or an email."""
    if not isinstance(url, str):
        return url
    return url.split("#", 1)[0].split("?", 1)[0]


def default_out(platform, now=None):
    stamp = (now or datetime.datetime.now(datetime.timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    return os.path.join(paths.PROJECT, ".factory", "observations", platform, stamp)


def authenticated_url_of(profile):
    """The profile's `session.authenticated_url` regex, when it names one."""
    for block in ((profile or {}).get("session"),
                  ((profile or {}).get("submission") or {}).get("session")):
        if isinstance(block, dict) and isinstance(block.get("authenticated_url"), str):
            return block["authenticated_url"]
    return None


# -- the records: scrubbed, summarised -------------------------------------------------------

def _scrub_text(text):
    return EMAIL.sub(EMAIL_MASK, redact.scrub_text(text))


def _sanitize(value, key=None):
    if isinstance(value, dict):
        out = {}
        for k, item in value.items():
            if k in ("value", "values", "default_value", "cookies", "storage", "headers"):
                out[k] = VALUE_MASK if item not in (None, "", [], {}) else item
            elif redact.secret_key(k) and item not in (None, "", redact.REPLACEMENT):
                out[k] = redact.REPLACEMENT
            else:
                out[k] = _sanitize(item, k)
        return out
    if isinstance(value, list):
        return [_sanitize(item, key) for item in value]
    if isinstance(value, str):
        text = bare_url(value) if key in ("url", "href") else value
        if key == "aria_snapshot":
            text = SNAPSHOT_URL.sub(r"\1\2", text)
        return _scrub_text(text)
    return value


def sanitize_page(record):
    """A page record as it may be kept: every text through wgflib.redact, email-shaped
    strings replaced, urls cut to origin + path, any value-like key masked."""
    return _sanitize(record)


def load_pages(out_dir):
    pages = []
    for path in sorted(glob.glob(os.path.join(out_dir, "pages", "*.json"))):
        try:
            with open(path, encoding="utf-8") as handle:
                pages.append(json.load(handle))
        except (OSError, ValueError):
            continue
    return pages


def field_inventory(pages):
    """Every form field seen, one entry per (url, field), in the order the pages were seen."""
    rows = []
    for page in pages:
        for field in page.get("fields") or []:
            rows.append({"page": page.get("id"), "url": page.get("url"), **field})
    return rows


def _cell(value):
    if value is None or value is False or value == "" or value == []:
        return ""
    if value is True:
        return "yes"
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    return str(value).replace("|", "\\|")


def summary_markdown(state, pages):
    state = state or {}
    lines = [f"# Console observation: {state.get('portal', '?')}", ""]
    lines.append(f"- status: {state.get('status', '?')}"
                 + (f" ({state.get('end_reason')})" if state.get("end_reason") else ""))
    for key in ("started_at", "authenticated_at", "ended_at"):
        if state.get(key):
            lines.append(f"- {key}: {state[key]}")
    lines.append(f"- pages recorded: {len(pages)}")
    lines.append("")
    lines.append("Recorded passively while a person used the console: input values masked, "
                 "no cookie, storage, header or request body kept, no login, CAPTCHA or "
                 "second-factor page recorded.")
    for page in pages:
        lines += ["", f"## {page.get('id')} {page.get('url')}", ""]
        if page.get("title"):
            lines.append(f"Title: {page['title']}")
        heads = [h.get("text") for h in page.get("headings") or [] if h.get("text")]
        if heads:
            lines.append("Headings: " + " / ".join(heads))
        if page.get("screenshot"):
            lines.append(f"Screenshot: {page['screenshot']}")
        fields = page.get("fields") or []
        if fields:
            lines += ["", "| form | name | type | label | placeholder | required | limits | "
                          "accept | options | ids |",
                      "|---|---|---|---|---|---|---|---|---|---|"]
            for f in fields:
                limits = " ".join(part for part in (
                    f"max {f['maxlength']}" if f.get("maxlength") is not None else "",
                    f"min {f['minlength']}" if f.get("minlength") is not None else "",
                    f"pattern {f['pattern']}" if f.get("pattern") else "") if part)
                ids = " ".join(f"{k}={f[k]}" for k in ("testid", "name", "id") if f.get(k))
                accept = _cell(f.get("accept")) + (" (multiple)" if f.get("multiple") else "")
                lines.append("| " + " | ".join(_cell(v) for v in (
                    f.get("form"), f.get("accessible_name"), f.get("type"), f.get("label"),
                    f.get("placeholder"), f.get("required"), limits, accept.strip(),
                    f.get("options"), ids)) + " |")
        buttons = [b.get("accessible_name") for b in page.get("buttons") or []
                   if b.get("accessible_name")]
        if buttons:
            lines += ["", "Buttons: " + ", ".join(buttons)]
        links = [f"{link.get('accessible_name')} ({link.get('href')})"
                 for link in page.get("links") or [] if link.get("accessible_name")]
        if links:
            lines.append("Links: " + ", ".join(links))
        statuses = [s.get("text") for s in page.get("statuses") or [] if s.get("text")]
        if statuses:
            lines.append("Status texts: " + ", ".join(statuses))
    return "\n".join(lines) + "\n"


def write_outputs(out_dir):
    """Scrub every page record in place, then write index.json and summary.md. Returns
    (state, pages)."""
    state = {}
    state_path = os.path.join(out_dir, "state.json")
    if os.path.isfile(state_path):
        with open(state_path, encoding="utf-8") as handle:
            state = sanitize_page(json.load(handle))
        _write_json(state_path, state)
    pages = []
    for path in sorted(glob.glob(os.path.join(out_dir, "pages", "*.json"))):
        try:
            with open(path, encoding="utf-8") as handle:
                record = sanitize_page(json.load(handle))
        except (OSError, ValueError):
            os.remove(path)  # a record cut short is not kept half-scrubbed
            continue
        _write_json(path, record)
        pages.append(record)
    index = {"portal": state.get("portal"), "status": state.get("status"),
             "started_at": state.get("started_at"),
             "authenticated_at": state.get("authenticated_at"),
             "ended_at": state.get("ended_at"), "end_reason": state.get("end_reason"),
             "pages": [{"id": p.get("id"), "url": p.get("url"), "dom_hash": p.get("dom_hash"),
                        "trigger": p.get("trigger"), "observed_at": p.get("observed_at"),
                        "screenshot": p.get("screenshot"), "record": f"pages/{p.get('id')}.json",
                        "fields": len(p.get("fields") or [])} for p in pages]}
    _write_json(os.path.join(out_dir, "index.json"), index)
    with open(os.path.join(out_dir, "summary.md"), "w", encoding="utf-8", newline="\n") as handle:
        handle.write(summary_markdown(state, pages))
    return state, pages


def _write_json(path, data):
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


# -- the run ---------------------------------------------------------------------------------

def observe(platform, profile, checkout, out_dir, *, url=None, authenticated_url=None,
            login_timeout_s=900, max_minutes=30, headless=False, test_human=None,
            run_process=None, echo=print, poll_ms=1000, stable_ms=5000):
    """Run one observation. Returns (exit code, state). `headless` and `test_human` exist
    for the tests: a person observes headed, and only a headless run accepts the test's
    stand-in for the person."""
    run_process = run_process or procs.run
    console = ((profile or {}).get("submission") or {}).get("console") or {}
    url = url or console.get("url")
    origins = list(console.get("allowed_origins") or [])
    if not url:
        raise ObserveError(f"the {platform} publication profile names no console url")
    if not origins:
        raise ObserveError(f"the {platform} publication profile names no allowed_origins")
    if not os.path.isfile(os.path.join(checkout, "package.json")):
        raise ObserveError(f"{checkout} is not a game checkout (no package.json); give --checkout")
    if test_human and not headless:
        raise ObserveError("a test stand-in for the person is only accepted headless")
    authenticated_url = authenticated_url or authenticated_url_of(profile)
    if authenticated_url:
        re.compile(authenticated_url)
    os.makedirs(out_dir, exist_ok=True)
    # Outside the checkout: the game repository is only lent its Playwright and Chromium.
    scratch = tempfile.mkdtemp(prefix=SCRATCH_PREFIX)
    try:
        test_dir = os.path.join(scratch, "tests")
        os.makedirs(test_dir, exist_ok=True)
        shutil.copy(SPEC, os.path.join(test_dir, "observe.spec.ts"))
        config_path = os.path.join(scratch, "playwright.wgf-observe.config.ts")
        with open(config_path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(CONFIG.format(
                test_dir=json.dumps(test_dir.replace(os.sep, "/")),
                output_dir=json.dumps(os.path.join(scratch, "results").replace(os.sep, "/")),
                headless="true" if headless else "false"))
        observe_config = {
            "portal": platform, "console_url": url, "allowed_origins": origins,
            "authenticated_url": authenticated_url,
            "login_timeout_ms": int(login_timeout_s * 1000),
            "max_ms": int(max_minutes * 60 * 1000), "poll_ms": poll_ms, "stable_ms": stable_ms,
            "out_dir": os.path.abspath(out_dir).replace(os.sep, "/"), "headless": bool(headless),
            "test_human": test_human.replace(os.sep, "/") if test_human else None}
        observe_path = os.path.join(scratch, "observe.json")
        with open(observe_path, "w", encoding="utf-8") as handle:
            json.dump(observe_config, handle, indent=2)
        env = dict(os.environ, WGF_OBSERVE_CONFIG=observe_path)

        def relay(_stream, line):
            for marker in MARKERS:
                at = line.find(marker)
                if at >= 0:
                    echo(_scrub_text(line[at:].rstrip()))
                    return

        if not authenticated_url:
            echo(f"note: no authenticated_url for {platform}: the console counts as reached on "
                 f"the first page of an allowed origin with no password, CAPTCHA or one-time-"
                 f"code field. Give --authenticated-url REGEX to be precise.")
        echo(f"Opening {bare_url(url)} in a new browser window. Log in there yourself; "
             f"nothing is typed for you and nothing of the session is kept. Then use the "
             f"console as usual; close the window to finish.")
        timeout = login_timeout_s + max_minutes * 60 + 180
        process = run_process(["pnpm", "exec", "playwright", "test", "-c", config_path],
                              cwd=checkout, timeout=timeout, env=env, on_output=relay,
                              stderr_to_stdout=True, heartbeat_seconds=0)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    state, pages = write_outputs(out_dir)
    output = (getattr(process, "stdout", "") or "") + (getattr(process, "stderr", "") or "")
    status = state.get("status")
    if status == "LOGIN_TIMEOUT":
        return EXIT_LOGIN_TIMEOUT, state
    if status == "ENDED" and getattr(process, "ok", False):
        return EXIT_OK, state
    if any(marker in output for marker in NO_BROWSER):
        echo("BLOCKED: the checkout's Playwright has no Chromium; run `pnpm exec playwright "
             "install chromium` in the checkout")
    elif status == "LOGIN_ABANDONED":
        echo("the window was closed before the console was reached; nothing was recorded")
    else:
        tail = process.tail(8) if hasattr(process, "tail") else output[-800:]
        echo(f"error: the observer did not finish ({getattr(process, 'status', '?')}): "
             f"{_scrub_text(tail)}")
    return EXIT_ERROR, state

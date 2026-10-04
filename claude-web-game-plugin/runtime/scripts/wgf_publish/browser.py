"""The direct Playwright executor for a portal console: one `pnpm exec playwright test` run
of browser/console.spec.ts under wgflib.procs, in the game checkout (whose own Playwright
and Chromium it uses, as every other browser harness here does), writing nothing committed.

The flow (the profile's intents with every value resolved, the session markers, the
identity, the phases this visit may run) goes in as a JSON file; the result comes back as
one. The spec decides nothing, every wait has a timeout, every request to an origin outside
the profile's `allowed_origins` is aborted at the browser - except while a person drives the
window to log in - and the process tree is owned by the step (heartbeat, cancel, timeout).
A missing browser is BLOCKED (the environment), never a publication failure.

The browser is HEADED: a person logs in, live, in the window it opens (headless only for the
tests' fixture portal). The context is fresh and ephemeral - no storage state in or out - so
the session ends with the window. Each state change the spec announces on stdout
(`WGF_PUBLISH_STATE {...}`: WAITING_FOR_HUMAN_LOGIN, AUTHENTICATED, LOGIN_TIMEOUT, ...) is
handed to `on_state` as it happens, so the step can report it while the browser waits.

Not Playwright MCP, and never an agent at the controls: the irreversible request is one click
on a profile locator, in a visit a person confirmed, or no click at all. The bounded adaptive
mode (adaptive.py) only proposes, through files, for a reversible intent; the spec checks
every proposal and is still the only thing that acts.
"""

import json
import os
import shutil

from wgflib import procs, redact

__all__ = ["BrowserExecutor", "SPEC", "NO_BROWSER", "ExecutorResult", "STATE_MARKER"]

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC = os.path.join(HERE, "browser", "console.spec.ts")
SCRATCH = ".wgf-publish"
NO_BROWSER = ("Executable doesn't exist", "browserType.launch", "playwright install")
STATE_MARKER = "WGF_PUBLISH_STATE "
CONFIG = """\
import {{ defineConfig }} from "@playwright/test";
export default defineConfig({{
  testDir: {test_dir},
  testMatch: /console\\.spec\\.ts$/,
  outputDir: {output_dir},
  fullyParallel: false,
  retries: 0,
  workers: 1,
  reporter: [["line"]],
  use: {{ headless: {headless}, viewport: {{ width: 1280, height: 800 }}, trace: "off", video: "off", screenshot: "off" }},
  projects: [{{ name: "console", use: {{ browserName: "chromium" }} }}],
}});
"""


class ExecutorResult:
    __slots__ = ("process", "result", "unavailable", "scratch", "states")

    def __init__(self, process, result, unavailable, scratch, states=()):
        self.process = process
        self.result = result or {}
        self.unavailable = unavailable
        self.scratch = scratch
        self.states = list(states)

    @property
    def phases(self):
        return self.result.get("phases") or {}

    @property
    def refused(self):
        return list(self.result.get("refused") or [])

    @property
    def errors(self):
        return list(self.result.get("errors") or [])


class BrowserExecutor:
    """Runs one console flow. `run_process` is replaceable in tests."""

    def __init__(self, checkout, release_dir, env, hooks=None, run_process=None,
                 timeout_s=1800, headless=False, on_state=None):
        self.checkout = checkout
        self.release_dir = release_dir
        self.env = dict(env)
        self.hooks = dict(hooks or {})
        self.run_process = run_process or procs.run
        self.timeout_s = timeout_s
        self.headless = bool(headless)
        self.on_state = on_state

    def scratch_dir(self):
        return os.path.join(self.release_dir, SCRATCH)

    def _relay(self, states):
        def relay(_stream, line):
            at = line.find(STATE_MARKER)
            if at < 0:
                return
            try:
                state = json.loads(line[at + len(STATE_MARKER):])
            except ValueError:
                return
            state = redact.scrub(state)
            states.append(state)
            if self.on_state is not None:
                self.on_state(state)
        return relay

    def execute(self, flow, log_path=None):
        scratch = self.scratch_dir()
        os.makedirs(scratch, exist_ok=True)
        spec_dir = os.path.join(scratch, "tests")
        os.makedirs(spec_dir, exist_ok=True)
        shutil.copy(SPEC, os.path.join(spec_dir, "console.spec.ts"))
        config_path = os.path.join(scratch, "playwright.wgf-publish.config.ts")
        with open(config_path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(CONFIG.format(
                test_dir=json.dumps(spec_dir.replace(os.sep, "/")),
                output_dir=json.dumps(os.path.join(scratch, "results").replace(os.sep, "/")),
                headless="true" if self.headless else "false"))
        flow_path = os.path.join(scratch, "flow.json")
        result_path = os.path.join(scratch, "result.json")
        if os.path.exists(result_path):
            os.remove(result_path)  # never read an earlier attempt's result
        with open(flow_path, "w", encoding="utf-8") as handle:
            json.dump(flow, handle, indent=2)
        env = dict(self.env, WGF_PUBLISH_FLOW=flow_path, WGF_PUBLISH_RESULT=result_path)
        argv = ["pnpm", "exec", "playwright", "test", "-c", config_path]
        states = []
        hooks = dict(self.hooks)
        relay = self._relay(states)
        theirs = hooks.pop("on_output", None)

        def on_output(stream, line):
            relay(stream, line)
            if theirs is not None:
                theirs(stream, line)
        process = self.run_process(argv, cwd=self.checkout, timeout=self.timeout_s, env=env,
                                   log_path=log_path, stderr_to_stdout=True, on_output=on_output,
                                   **hooks)
        result = None
        if os.path.exists(result_path):
            try:
                with open(result_path, encoding="utf-8") as handle:
                    result = json.load(handle)
            except ValueError:
                result = None
        output = (getattr(process, "stdout", "") or "") + (getattr(process, "stderr", "") or "")
        if not states:
            # A runner that does not stream (a test's stand-in) still leaves its markers.
            for line in output.splitlines():
                relay("stdout", line)
        unavailable = any(marker in output for marker in NO_BROWSER)
        return ExecutorResult(process, result, unavailable, scratch, states)

    def cleanup(self):
        shutil.rmtree(self.scratch_dir(), ignore_errors=True)

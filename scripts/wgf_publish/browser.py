"""The direct Playwright executor for a portal console: one `pnpm exec playwright test` run
of browser/console.spec.ts under wgflib.procs, in the game checkout (whose own Playwright
and Chromium it uses, as every other browser harness here does), writing nothing committed.

The flow (phases, selectors, URLs, the package, the storage-state path) goes in as a JSON
file; the result comes back as one. The executor is deterministic and bounded: the spec
decides nothing, every wait has a timeout from the publication profile, every request to an
origin outside the profile's `allowed_origins` is aborted at the browser, and the process
tree is owned by the step (heartbeat, cancel, timeout). A missing browser is BLOCKED (the
environment), never a publication failure.

Not Playwright MCP, and never an agent: the irreversible submit is one click in one phase,
or no click at all (`submit: false`, the dry run).
"""

import json
import os
import shutil

from wgflib import procs

__all__ = ["BrowserExecutor", "SPEC", "NO_BROWSER", "ExecutorResult"]

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC = os.path.join(HERE, "browser", "console.spec.ts")
SCRATCH = ".wgf-publish"
NO_BROWSER = ("Executable doesn't exist", "browserType.launch", "playwright install")
CONFIG = """\
import {{ defineConfig }} from "@playwright/test";
export default defineConfig({{
  testDir: {test_dir},
  testMatch: /console\\.spec\\.ts$/,
  fullyParallel: false,
  retries: 0,
  workers: 1,
  reporter: [["list"]],
  use: {{ headless: true, viewport: {{ width: 1280, height: 800 }}, trace: "off", video: "off" }},
  projects: [{{ name: "console", use: {{ browserName: "chromium" }} }}],
}});
"""


class ExecutorResult:
    __slots__ = ("process", "result", "unavailable", "scratch")

    def __init__(self, process, result, unavailable, scratch):
        self.process = process
        self.result = result or {"phases": {}, "refused": [], "errors": []}
        self.unavailable = unavailable
        self.scratch = scratch

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
                 timeout_s=1800):
        self.checkout = checkout
        self.release_dir = release_dir
        self.env = dict(env)
        self.hooks = dict(hooks or {})
        self.run_process = run_process or procs.run
        self.timeout_s = timeout_s

    def scratch_dir(self):
        return os.path.join(self.release_dir, SCRATCH)

    def execute(self, flow, log_path=None):
        scratch = self.scratch_dir()
        os.makedirs(scratch, exist_ok=True)
        spec_dir = os.path.join(scratch, "tests")
        os.makedirs(spec_dir, exist_ok=True)
        shutil.copy(SPEC, os.path.join(spec_dir, "console.spec.ts"))
        config_path = os.path.join(scratch, "playwright.wgf-publish.config.ts")
        with open(config_path, "w", encoding="utf-8") as handle:
            handle.write(CONFIG.format(test_dir=json.dumps(spec_dir.replace(os.sep, "/"))))
        flow_path = os.path.join(scratch, "flow.json")
        result_path = os.path.join(scratch, "result.json")
        if os.path.exists(result_path):
            os.remove(result_path)  # never read an earlier attempt's result
        with open(flow_path, "w", encoding="utf-8") as handle:
            json.dump(flow, handle, indent=2)
        env = dict(self.env, WGF_PUBLISH_FLOW=flow_path, WGF_PUBLISH_RESULT=result_path)
        argv = ["pnpm", "exec", "playwright", "test", "-c", config_path]
        process = self.run_process(argv, cwd=self.checkout, timeout=self.timeout_s, env=env,
                                   log_path=log_path, stderr_to_stdout=True, **self.hooks)
        result = None
        if os.path.exists(result_path):
            try:
                with open(result_path, encoding="utf-8") as handle:
                    result = json.load(handle)
            except ValueError:
                result = None
        output = (getattr(process, "stdout", "") or "") + (getattr(process, "stderr", "") or "")
        unavailable = any(marker in output for marker in NO_BROWSER)
        return ExecutorResult(process, result, unavailable, scratch)

    def cleanup(self):
        shutil.rmtree(self.scratch_dir(), ignore_errors=True)

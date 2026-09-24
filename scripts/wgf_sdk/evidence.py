"""Evidence: the game repository's SDK conformance suite, run and read.

The suite lives in the game repository (web-game-template tests/sdk/), because that is where
the adapters are. `pnpm sdk:conformance` runs it against fake portal SDKs and writes vitest's
JSON report to build/sdk-conformance.json; its test names are
`<platform> > <feature> > <scenario>`. Optionally `pnpm test:sdk:browser` boots the real
PixiJS and Three.js builds in a browser with mocked portal scripts.

The runner can only run those commands and `git rev-parse HEAD`. It has no way to reach a
publishing, packaging or release script: publishing is the game repository's release
pipeline, behind G5 and G6, and never an SDK step's side effect.
"""

import json
import os

from wgflib import procs

__all__ = ["EvidenceError", "ConformanceRun", "ConformanceRunner", "PnpmRunner", "read_report",
           "summarize", "REPORT_PATH", "COMMANDS"]

REPORT_PATH = os.path.join("build", "sdk-conformance.json")

# The whole command surface. Nothing else can be run from this module.
COMMANDS = {
    "conformance": ("pnpm", "sdk:conformance"),
    "browser": ("pnpm", "test:sdk:browser"),
    "commit": ("git", "rev-parse", "HEAD"),
}


class EvidenceError(Exception):
    """The suite could not produce a report. Retryable: a toolchain hiccup is not a verdict."""


class ConformanceRun:
    __slots__ = ("report", "commit", "browser")

    def __init__(self, report, commit, browser=None):
        self.report = report      # vitest JSON report (dict)
        self.commit = commit      # the game repository HEAD the suite ran against
        self.browser = browser    # None (not run), or {"passed": bool, "output": str}


class ConformanceRunner:
    """Interface: produce a ConformanceRun for a game repository."""

    def run(self, game_repo, browser=False):  # pragma: no cover - interface
        raise NotImplementedError


class PnpmRunner(ConformanceRunner):
    def __init__(self, timeout_s=900, log_path=None):
        self.timeout_s = timeout_s
        self.log_path = log_path

    def _exec(self, name, game_repo):
        # An owned tree (wgflib.procs): the browser suite's preview server and Chromium are
        # terminated with the command, on success as much as on a timeout or a cancel.
        done = procs.run(list(COMMANDS[name]), cwd=game_repo, timeout=self.timeout_s,
                         log_path=self.log_path)
        if done.error is not None:
            if isinstance(done.exception, FileNotFoundError):
                raise EvidenceError(f"{COMMANDS[name][0]} is not installed: "
                                    f"{done.exception}")
            raise EvidenceError(f"`{' '.join(COMMANDS[name])}` could not be started: "
                                f"{done.error}")
        if done.timed_out:
            raise EvidenceError(f"`{' '.join(COMMANDS[name])}` timed out after {self.timeout_s}s")
        if done.cancelled or done.idle_timed_out:
            raise EvidenceError(f"`{' '.join(COMMANDS[name])}` was stopped: {done.status}")
        return done

    def run(self, game_repo, browser=False):
        commit = self._exec("commit", game_repo).stdout.strip() or None
        done = self._exec("conformance", game_repo)
        path = os.path.join(game_repo, REPORT_PATH)
        # A failing scenario exits non-zero and still writes the report; only a missing report
        # means the suite did not run.
        if not os.path.exists(path):
            tail = (done.stdout + done.stderr)[-2000:]
            raise EvidenceError(f"`pnpm sdk:conformance` wrote no {REPORT_PATH}:\n{tail}")
        report = read_report(path)
        result = None
        if browser:
            ran = self._exec("browser", game_repo)
            result = {"passed": ran.returncode == 0, "output": (ran.stdout + ran.stderr)[-2000:]}
        return ConformanceRun(report, commit, result)


def read_report(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _strip(title):
    return title[1:-1] if len(title) >= 2 and title[0] == title[-1] == "'" else title


def summarize(report):
    """{platform: {feature: {"passed", "failed", "skipped", "todo", "failures", "titles"}}}.

    Also returns problems with the report itself (tests outside the platform > feature shape
    that failed), which make the whole run untrustworthy.
    """
    platforms, problems = {}, []
    for suite in report.get("testResults") or []:
        for result in suite.get("assertionResults") or []:
            ancestors = [_strip(t) for t in result.get("ancestorTitles") or []]
            status = result.get("status")
            if len(ancestors) < 2:
                if status == "failed":
                    problems.append(f"{result.get('fullName')}: {' '.join(result.get('failureMessages') or [])[:300]}")
                continue
            platform, feature = ancestors[0], ancestors[1]
            entry = platforms.setdefault(platform, {}).setdefault(
                feature, {"passed": 0, "failed": 0, "skipped": 0, "todo": 0, "failures": [], "titles": []})
            key = {"passed": "passed", "failed": "failed", "todo": "todo"}.get(status, "skipped")
            entry[key] += 1
            entry["titles"].append(result.get("title", ""))
            if status == "failed":
                message = (result.get("failureMessages") or [""])[0].splitlines()[0][:200]
                entry["failures"].append(f"{result.get('title')}: {message}")
    return platforms, problems

"""Running the game repository's own tools: git, and the test suite the step writes.

Behind one small interface so the step's tests fake it: they run offline, with no node, no
pnpm and no git (docs/workflow-module-contract.md §11).
"""

import json
import os
import re
import subprocess
import tempfile

__all__ = ["CommandRunner", "CommandResult", "TEST_FILE", "TEST_DIR", "SCENARIOS", "run_tests",
           "git_state"]

TEST_FILE = "tests/unit/platform/gameplay-integration.test.ts"
# The describe blocks of TEST_FILE, which is where these names are defined.
TEST_DIR = "tests/unit/platform"
SCENARIOS = ("sdk-available", "sdk-unavailable", "sdk-init-failure", "ad-unavailable",
             "ad-closed-early", "reward-callback", "pause-resume", "platform-not-configured",
             "game-seam")


class CommandResult:
    def __init__(self, returncode, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class CommandRunner:
    """Runs a command. `None` when the executable does not exist."""

    def run(self, argv, cwd, timeout):
        try:
            done = subprocess.run(argv, cwd=cwd, capture_output=True, text=True,
                                  timeout=timeout, check=False)
        except FileNotFoundError:
            return None
        except subprocess.TimeoutExpired as exc:
            return CommandResult(124, exc.stdout or "", f"timed out after {timeout}s")
        return CommandResult(done.returncode, done.stdout, done.stderr)


def git_state(runner, repo):
    """(commit sha or None, 'clean' | 'uncommitted-changes' | None)."""
    head = runner.run(["git", "rev-parse", "HEAD"], repo, 60)
    if head is None or head.returncode != 0:
        return None, None
    status = runner.run(["git", "status", "--porcelain"], repo, 60)
    dirty = status is not None and status.returncode == 0 and status.stdout.strip() != ""
    return head.stdout.strip(), "uncommitted-changes" if dirty else "clean"


def _tail(result):
    text = (result.stderr or result.stdout or "").strip().splitlines()
    return " | ".join(text[-3:])[:400]


def _scenarios(report):
    counts = {name: [0, 0] for name in SCENARIOS}
    for suite in report.get("testResults") or []:
        for test in suite.get("assertionResults") or []:
            ancestors = test.get("ancestorTitles") or [""]
            if ancestors[0] in counts:
                counts[ancestors[0]][0 if test.get("status") == "passed" else 1] += 1
    scenarios = []
    for name, (passed, failed) in counts.items():
        status = "failed" if failed else "passed" if passed else "not-run"
        scenarios.append({"id": name, "status": status, "passed": passed, "failed": failed})
    return scenarios


def run_tests(runner, repo, timeout=600, typecheck=True, touched=()):
    """Run the integration suite (and the repository's typecheck). A `tests` record.

    `touched`: repo-relative paths the integration wrote, which the typecheck is judged on.
    """
    if not os.path.isdir(os.path.join(repo, "node_modules")):
        return {"status": "not-run", "typecheck": "not-run",
                "note": "the game repository has no node_modules; run `pnpm install` there"}

    handle, output = tempfile.mkstemp(prefix="wgf-sdk-", suffix=".json")
    os.close(handle)
    argv = ["pnpm", "exec", "vitest", "run", "--project", "unit", "--reporter=json",
            f"--outputFile={output}", TEST_DIR]
    record = {"command": " ".join(argv[:6] + [TEST_DIR])}
    try:
        result = runner.run(argv, repo, timeout)
        if result is None:
            record.update(status="not-run", note="pnpm is not installed")
            return record
        try:
            with open(output, encoding="utf-8") as stream:
                report = json.load(stream)
        except (OSError, ValueError):
            report = None
    finally:
        os.remove(output)

    if report is None:
        record.update(status="failed" if result.returncode else "not-run",
                      note=f"no test report (exit {result.returncode}): {_tail(result)}")
    else:
        record["scenarios"] = _scenarios(report)
        # "game-seam" runs only in games that declare the seam; every other scenario is the
        # integration's own and must run.
        failed = result.returncode != 0 or any(
            s["status"] == "failed" or (s["status"] == "not-run" and s["id"] != "game-seam")
            for s in record["scenarios"])
        record["status"] = "failed" if failed else "passed"
        if failed and result.returncode != 0:
            record["note"] = f"vitest exit {result.returncode}: {_tail(result)}"

    if typecheck:
        _typecheck(runner, repo, timeout, touched, record)
    else:
        record["typecheck"] = "not-run"
    return record


_TSC_ERROR = re.compile(r"^(?P<path>[^\s(][^(]*)\(\d+,\d+\): error ", re.M)


def _typecheck(runner, repo, timeout, touched, record):
    """The repository's typecheck, judged on the files the integration wrote or patched.

    Errors elsewhere were there before this step and are not its to fix; they are noted,
    and do not fail the integration.
    """
    checked = runner.run(["pnpm", "exec", "tsc", "-b"], repo, timeout)
    if checked is None:
        record["typecheck"] = "not-run"
        return
    if checked.returncode == 0:
        record["typecheck"] = "passed"
        return
    output = (checked.stdout or "") + (checked.stderr or "")
    paths = {m.group("path").strip().replace("\\", "/") for m in _TSC_ERROR.finditer(output)}
    ours = sorted(p for p in paths if p in touched)
    if ours or not paths:
        record["typecheck"] = "failed"
        record["status"] = "failed"
        record["note"] = (record.get("note", "") + f" typecheck: {_tail(checked)}").strip()
    else:
        record["typecheck"] = "passed"
        record["note"] = (record.get("note", "") + " typecheck: the integration's files are "
                          "clean; errors elsewhere predate it: "
                          + ", ".join(sorted(paths)[:5])).strip()

"""Gameplay: does the built game boot, load, start, take input, loop, progress, end, restart,
pause and resume, and fit a phone screen.

Evidence comes from a browser driving the built bundle, through one of two drivers:

  recorded    A gameplay session recorded by whoever drove the game interactively - in
              practice an agent with a Playwright browser tool (Playwright MCP). The session
              file follows core/artifacts/shared/gameplay-session.schema.json and is only
              accepted when it names the commit under test. This module never talks to a
              browser tool itself; an agent host that has one records the session, and the
              verification ingests it.

  repository  The game repository's own Playwright suites (`test:e2e`), run headless with
              the JSON reporter. Tests are mapped to gameplay aspects by `@aspect` tags
              (`test("restarts @restart", ...)`) and, failing that, by title keywords.

`browser: auto` (the default) takes a fresh recorded session when there is one and falls
back to the repository suites otherwise, so verification never depends on the browser tool
being present.
"""

import json
import os
import re

from ..model import BLOCKED, FAIL, PASS, WARNING, Check, Evidence
from ..session import DEFAULT_SESSION_FILE

__all__ = ["ASPECTS", "check_gameplay", "required_aspects", "RecordedSessionDriver",
           "RepositoryPlaywrightDriver", "select_driver", "Observation", "map_report"]

ASPECTS = ("boot", "loading", "start", "input", "core-loop", "progression", "game-over",
           "restart", "pause-resume", "responsive")

TITLES = {
    "boot": "Boots without errors",
    "loading": "Loading completes and signals ready",
    "start": "A game can be started",
    "input": "Responds to player input",
    "core-loop": "Core loop runs",
    "progression": "Progression advances",
    "game-over": "Game over is reached",
    "restart": "Restarts after game over",
    "pause-resume": "Pauses and resumes",
    "responsive": "Plays on a mobile viewport",
}

# Title keywords, used only for tests with no @aspect tag. Deliberately conservative: a
# keyword maps a test to an aspect it plausibly exercises, and an unmapped aspect is
# reported as uncovered rather than guessed at.
KEYWORDS = {
    "boot": r"\bboots?\b|\bbooting\b",
    "loading": r"\bload(s|ing|ed)?\b|\bready\b|\bboots?\b",
    "start": r"\bstart(s|ed)?\b|\bmenu\b|\bplay button\b",
    "input": r"\binput\b|\btaps?\b|\bclicks?\b|\bkey(board|s)?\b|\bswipes?\b|\btouch\b",
    "core-loop": r"\bsteps?\b|\bloop\b|\bsimulation\b|\bcore\b",
    "progression": r"\bprogress(ion)?\b|\blevel\b|\bscore\b|\bpersonal best\b",
    "game-over": r"\bgame ?over\b|\bdies\b|\bdeath\b|\bloses?\b|\bruns? ends?\b",
    "restart": r"\brestarts?\b|\bretry\b|\breplay\b|\bplay again\b",
    "pause-resume": r"\bpause[sd]?\b|\bresumes?\b|\bvisibility\b",
    "responsive": r"\bresponsive\b|\bviewport\b|\bresize\b|\borientation\b",
}
MOBILE_PROJECT = re.compile(r"mobile|pixel|iphone|android|tablet|ipad", re.I)
_TAG = re.compile(r"@([a-z][a-z-]*)")
_MISSING_BROWSER = re.compile(r"Executable doesn't exist|playwright install", re.I)


class Observation:
    """What a driver saw. `aspects[a]` is a list of (status, Evidence)."""

    def __init__(self, driver, note=""):
        self.driver = driver
        self.note = note
        self.aspects = {a: [] for a in ASPECTS}
        self.failed_requests = None     # None: not observed. []: observed, none failed.
        self.console_errors = None
        self.browsers = []              # qa-report browser_matrix entries
        self.counts = None
        self.evidence = []              # evidence about the driver run itself


class DriverUnavailable(Exception):
    """The driver could not produce an observation. `blocked` distinguishes a missing tool
    (verification is blocked) from a run that produced nothing (the game is at fault)."""

    def __init__(self, message, evidence, blocked=True):
        super().__init__(message)
        self.evidence = evidence
        self.blocked = blocked


# -- recorded session (Playwright MCP) ----------------------------------------------------

class RecordedSessionDriver:
    id = "playwright-mcp"

    def __init__(self, path):
        self.path = path

    def load(self, session):
        """The session document, or DriverUnavailable saying why it cannot be used."""
        full = session.path(self.path)
        if not os.path.exists(full):
            raise DriverUnavailable(f"no recorded gameplay session at {self.path}",
                                    [Evidence("file", f"{self.path} does not exist",
                                              path=self.path)])
        document = session.read_json(self.path)
        problems = validate_session(document)
        if problems:
            raise DriverUnavailable(f"{self.path} is not a valid gameplay session",
                                    [Evidence("file", "; ".join(problems), path=self.path)])
        if not session.commit or document["commit_sha"] != session.commit:
            raise DriverUnavailable(
                f"{self.path} was recorded against {document['commit_sha'][:12]}, not the "
                f"commit under test", [Evidence("file", "recorded session is stale: commit "
                                                f"{document['commit_sha']} != "
                                                f"{session.commit}", path=self.path)])
        return document

    def observe(self, session):
        document = self.load(session)
        seen = Observation(document.get("driver") or self.id,
                           note=f"recorded session {self.path}")
        seen.evidence.append(Evidence("file", f"gameplay session recorded by "
                                              f"{document.get('driver', self.id)} at "
                                              f"{document.get('recorded_at', 'unknown time')}",
                                      path=self.path))
        for scenario in document["scenarios"]:
            status = PASS if scenario["status"] == "PASS" else FAIL
            evidence = Evidence("observation", scenario["observation"], path=self.path,
                                data={k: scenario[k] for k in ("steps", "screenshot",
                                                                "viewport") if k in scenario}
                                or None)
            seen.aspects[scenario["aspect"]].append((status, evidence))
        if "failed_requests" in document:
            seen.failed_requests = list(document["failed_requests"])
        if "console_errors" in document:
            seen.console_errors = list(document["console_errors"])
        for browser in document.get("browsers") or []:
            seen.browsers.append(dict(browser))
        return seen


def validate_session(document):
    """The structural rules of gameplay-session.schema.json, checked without a validator."""
    if not isinstance(document, dict):
        return ["not a JSON object"]
    problems = []
    for key in ("commit_sha", "scenarios"):
        if key not in document:
            problems.append(f"missing {key}")
    for index, scenario in enumerate(document.get("scenarios") or []):
        if not isinstance(scenario, dict):
            problems.append(f"scenarios[{index}] is not an object")
            continue
        if scenario.get("aspect") not in ASPECTS:
            problems.append(f"scenarios[{index}].aspect {scenario.get('aspect')!r} is unknown")
        if scenario.get("status") not in ("PASS", "FAIL"):
            problems.append(f"scenarios[{index}].status must be PASS or FAIL")
        if not scenario.get("observation"):
            problems.append(f"scenarios[{index}] has no observation")
    if not isinstance(document.get("commit_sha", ""), str):
        problems.append("commit_sha must be a string")
    return problems


# -- repository Playwright suites -----------------------------------------------------------

class RepositoryPlaywrightDriver:
    id = "repository-playwright"
    report_path = "build/verification/playwright-e2e.json"

    def available(self, session):
        return session.has_script("test:e2e")

    def observe(self, session):
        if not self.available(session):
            raise DriverUnavailable("package.json has no test:e2e script",
                                    [Evidence("file", "no test:e2e script", path="package.json")])
        report_file = session.path(self.report_path)
        if os.path.exists(report_file):
            os.remove(report_file)          # never read a previous run's report
        os.makedirs(os.path.dirname(report_file), exist_ok=True)
        result = session.run(session.script_command("test:e2e", "--reporter=json"), "browser",
                             env={"PLAYWRIGHT_JSON_OUTPUT_NAME": report_file})
        command_evidence = Evidence.of_command(result)
        if result.unavailable:
            raise DriverUnavailable(result.describe(), [command_evidence])

        report = session.read_json(self.report_path)
        if report is None:
            try:
                report = json.loads(result.stdout)
            except ValueError:
                report = None
        if not isinstance(report, dict):
            output = result.stdout + result.stderr
            raise DriverUnavailable(
                "the Playwright run produced no JSON report", [command_evidence],
                blocked=bool(_MISSING_BROWSER.search(output)))
        seen = map_report(report, self.report_path)
        seen.evidence.insert(0, command_evidence)
        return seen


def _specs(suite, trail=()):
    for spec in suite.get("specs") or []:
        yield spec, trail
    for child in suite.get("suites") or []:
        yield from _specs(child, trail + (child.get("title") or "",))


def map_report(report, path):
    """An Observation from a Playwright JSON report."""
    seen = Observation(RepositoryPlaywrightDriver.id, note=f"Playwright JSON report {path}")
    projects = {}
    counts = {"passed": 0, "failed": 0, "skipped": 0}
    for top in report.get("suites") or []:
        for spec, trail in _specs(top, (top.get("title") or "",)):
            title = spec.get("title") or ""
            tags = {t.lstrip("@") for t in spec.get("tags") or []}
            tags |= set(_TAG.findall(title))
            explicit = [a for a in ASPECTS if a in tags]
            keyword = [a for a in ASPECTS if re.search(KEYWORDS[a], title, re.I)]
            aspects = explicit or keyword
            for test in spec.get("tests") or []:
                project = test.get("projectName") or "default"
                outcome = test.get("status")
                if outcome == "skipped":
                    counts["skipped"] += 1
                    continue
                passed = outcome in ("expected", "flaky")
                counts["passed" if passed else "failed"] += 1
                projects.setdefault(project, []).append(passed)
                status = PASS if passed else FAIL
                where = " > ".join(t for t in trail if t)
                summary = f"[{project}] {where + ' > ' if where else ''}{title}: {outcome}"
                error = _first_error(test)
                if error:
                    summary += f" - {error}"
                evidence = Evidence("test", summary, path=path)
                for aspect in aspects:
                    if aspect != "responsive":
                        seen.aspects[aspect].append((status, evidence))
                # A mobile-emulated project exercising the game at all is the responsive
                # evidence; a failure there is a failure to play on a phone.
                if MOBILE_PROJECT.search(project) or "responsive" in aspects:
                    seen.aspects["responsive"].append((status, evidence))
    for project, results in sorted(projects.items()):
        seen.browsers.append({
            "browser": "chromium", "platform": project,
            "result": "pass" if all(results) else "fail",
        })
    seen.counts = counts
    return seen


def _first_error(test):
    for result in test.get("results") or []:
        error = result.get("error") or {}
        message = error.get("message") or ""
        if message:
            return re.sub(r"\x1b\[[0-9;]*m", "", message).strip().splitlines()[0][:200]
    return ""


def select_driver(session):
    """(driver, evidence about the choice). `with: browser: auto | recorded | repository`."""
    mode = session.params.get("browser", "auto")
    recorded = RecordedSessionDriver(session.params.get("gameplay_session", DEFAULT_SESSION_FILE))
    repository = RepositoryPlaywrightDriver()
    if mode == "recorded":
        return recorded, []
    if mode == "repository":
        return repository, []
    try:
        recorded.load(session)
        return recorded, []
    except DriverUnavailable as exc:
        note = Evidence("observation", f"recorded session not used ({exc}); falling back to "
                                       "the repository's Playwright suites")
        return repository, [note]


# -- the checks -----------------------------------------------------------------------------

def required_aspects(session):
    """Which aspects must have passing evidence. The rest are WARNING when uncovered."""
    override = (session.params.get("gameplay") or {}).get("required")
    if override is not None:
        return set(override)
    required = {"boot", "loading", "core-loop"}
    if session.verification_flag("mobile_test"):
        required.add("responsive")
    design = session.inputs.get("game-design")
    if design:
        required.add("start")
        if design.get("controls"):
            required.add("input")
        if (design.get("session") or {}).get("end_condition"):
            required |= {"game-over", "restart"}
        if design.get("progression") or (design.get("retention") or {}).get("progression_loop"):
            required.add("progression")
        # An ad interrupts play; a game that cannot pause cannot show one correctly.
        if (design.get("monetization") or {}).get("placements"):
            required.add("pause-resume")
    return required


def check_gameplay(session):
    required = required_aspects(session)
    if not session.passed("build.build"):
        return [session.record(session.blocked_by(
            "build.build", id=f"gameplay.{a}", category="gameplay", title=TITLES[a],
            required=a in required)) for a in ASPECTS]

    driver, choice = select_driver(session)
    try:
        seen = driver.observe(session)
    except DriverUnavailable as exc:
        session.gameplay_driver = {"id": driver.id, "note": str(exc)}
        status = BLOCKED if exc.blocked else FAIL
        return [session.record(Check(
            f"gameplay.{a}", "gameplay", TITLES[a],
            status if a in required else WARNING, required=a in required,
            message=f"no gameplay evidence: {exc}", evidence=choice + exc.evidence))
            for a in ASPECTS]

    session.gameplay_driver = {"id": seen.driver, "note": seen.note}
    session.gameplay = seen
    out = []
    for aspect in ASPECTS:
        is_required = aspect in required
        results = seen.aspects[aspect]
        if not results:
            status = FAIL if is_required else WARNING
            message = (f"no {seen.driver} evidence exercises {aspect}"
                       + ("; the game must provide a test or recorded scenario for it"
                          if is_required else ""))
            evidence = choice + seen.evidence[:1] + [
                Evidence("observation", f"no test or scenario covers {aspect}")]
        else:
            failed = [e for s, e in results if s == FAIL]
            status = FAIL if failed else PASS
            if failed and not is_required:
                status = WARNING
            message = (f"{len(failed)} of {len(results)} observation(s) failed" if failed
                       else f"{len(results)} observation(s) passed")
            evidence = [e for _, e in results]
        out.append(session.record(Check(f"gameplay.{aspect}", "gameplay", TITLES[aspect],
                                        status, required=is_required, message=message,
                                        evidence=evidence)))
    if seen.console_errors:
        boot = session.results["gameplay.boot"]
        boot.evidence.append(Evidence("observation", f"{len(seen.console_errors)} console "
                                                     f"error(s): {seen.console_errors[0]}"))
        if boot.status == PASS:
            boot.status = FAIL if boot.required else WARNING
            boot.message = "the game logged errors while playing"
    return out

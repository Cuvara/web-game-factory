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

from wgflib import build_scope, genre_models, paths
from wgflib import template_contract as contract
from wgflib.jsonschema_lite import Registry, Validator, json_problems

from ..model import BLOCKED, FAIL, PASS, WARNING, Check, Evidence
from ..session import DEFAULT_SESSION_FILE

__all__ = ["ASPECTS", "check_gameplay", "required_aspects", "required_aspects_for",
           "RecordedSessionDriver",
           "RepositoryPlaywrightDriver", "select_driver", "Observation", "map_report"]

# The @aspect tag vocabulary is part of the template contract: a game's suites use the words.
ASPECTS = contract.ASPECTS

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
#
# `progression` has no entry on purpose. A test whose title says "score" or "level" is the
# weakest possible evidence that the design's progression - its content units, in order, with
# what persists between them - is built, and it was passing on exactly those words. Progression
# is now a pass only on what the bot played (quality.progression:persists) or on a test the
# developer tagged `@progression` together with the content data file: see check_gameplay.
KEYWORDS = {
    "boot": r"\bboots?\b|\bbooting\b",
    "loading": r"\bload(s|ing|ed)?\b|\bready\b|\bboots?\b",
    "start": r"\bstart(s|ed)?\b|\bmenu\b|\bplay button\b",
    "input": r"\binput\b|\btaps?\b|\bclicks?\b|\bkey(board|s)?\b|\bswipes?\b|\btouch\b",
    "core-loop": r"\bsteps?\b|\bloop\b|\bsimulation\b|\bcore\b",
    "game-over": r"\bgame ?over\b|\bdies\b|\bdeath\b|\bloses?\b|\bruns? ends?\b",
    "restart": r"\brestarts?\b|\bretry\b|\breplay\b|\bplay again\b",
    "pause-resume": r"\bpause[sd]?\b|\bresumes?\b|\bvisibility\b",
    "responsive": r"\bresponsive\b|\bviewport\b|\bresize\b|\borientation\b",
}
# Where the developer records what it built the content from, and what the build reads it back
# out of (core/craft/content-and-level-design.md, core/reference/genre-models.yaml).
DEVELOP_CHECKS = "docs/development/checks.json"
CONTENT_DATA = "public/content/units.json"
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
                                      path=self.path, content_hash=session.file_hash(self.path)))
        for scenario in document["scenarios"]:
            status = PASS if scenario["status"] == "PASS" else FAIL
            data = {k: scenario[k] for k in ("steps", "screenshot", "viewport") if k in scenario}
            shot = scenario.get("screenshot")
            if shot:
                digest = session.file_hash(shot)
                if digest is None and status == PASS:
                    # A passing scenario that cites a screenshot nobody can find is a claim
                    # without its evidence; it is not counted. A failing one still counts.
                    seen.evidence.append(Evidence(
                        "observation", f"{scenario['aspect']} scenario ignored: its screenshot "
                                       f"{shot} does not exist", path=self.path))
                    continue
                if digest:
                    data["screenshot_hash"] = digest
            evidence = Evidence("observation", scenario["observation"], path=self.path,
                                data=data or None)
            seen.aspects[scenario["aspect"]].append((status, evidence))
        if "failed_requests" in document:
            seen.failed_requests = list(document["failed_requests"])
        if "console_errors" in document:
            seen.console_errors = list(document["console_errors"])
        for browser in document.get("browsers") or []:
            seen.browsers.append(dict(browser))
        return seen


SESSION_SCHEMA = os.path.join(paths.ARTIFACTS, "shared", "gameplay-session.schema.json")
_SESSION_VALIDATOR = []


def _session_validator():
    """shared/gameplay-session.schema.json, compiled once by wgflib.jsonschema_lite."""
    if not _SESSION_VALIDATOR:
        with open(SESSION_SCHEMA, encoding="utf-8") as handle:
            schema = json.load(handle)
        _SESSION_VALIDATOR.append(Validator(schema, Registry()))
    return _SESSION_VALIDATOR[0]


def validate_session(document):
    """[problem, ...] for a recorded session: the whole of
    core/artifacts/shared/gameplay-session.schema.json (types, formats, enums, no unknown
    keys), then what the schema cannot say - that every aspect is one the template contract
    knows, since the schema's enum and contract.ASPECTS are two lists."""
    if not isinstance(document, dict):
        return ["not a JSON object"]
    malformed = json_problems(document)
    if malformed:
        return [f"{pointer or '/'}: not JSON - {reason}" for pointer, reason in malformed]
    problems = [str(error) for error in _session_validator().iter_errors(document)]
    for index, scenario in enumerate(document.get("scenarios") or []):
        if isinstance(scenario, dict) and "aspect" in scenario \
                and scenario["aspect"] not in ASPECTS:
            problems.append(f"/scenarios/{index}/aspect: {scenario['aspect']!r} is not an "
                            "aspect the template contract knows")
    return problems


# -- repository Playwright suites -----------------------------------------------------------

class RepositoryPlaywrightDriver:
    id = "repository-playwright"
    report_path = contract.PLAYWRIGHT_E2E_REPORT

    def available(self, session):
        return session.has_script(contract.SCRIPT_TEST_E2E)

    def observe(self, session):
        if not self.available(session):
            raise DriverUnavailable("package.json has no test:e2e script",
                                    [Evidence("file", "no test:e2e script",
                                              path=contract.PACKAGE_JSON)])
        report_file = session.path(self.report_path)
        if os.path.exists(report_file):
            os.remove(report_file)          # never read a previous run's report
        os.makedirs(os.path.dirname(report_file), exist_ok=True)
        extra = ["--reporter=json"]
        if session.e2e_workers:
            extra.append(f"--workers={session.e2e_workers}")
        result = session.run(session.script_command(contract.SCRIPT_TEST_E2E, *extra),
                             "browser", env={"PLAYWRIGHT_JSON_OUTPUT_NAME": report_file})
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
        report_hash = session.file_hash(self.report_path)
        if report_hash:
            seen.evidence.insert(0, Evidence("file", "Playwright JSON report written by this run",
                                             path=self.report_path, content_hash=report_hash))
            # Every test result is pinned to the report file it was read from.
            for results in seen.aspects.values():
                for _, evidence in results:
                    evidence.content_hash = report_hash
        seen.evidence.insert(0, command_evidence)
        if not result.ok and not (seen.counts or {}).get("failed"):
            # The runner failed (global setup, web server, a crash after the last test) but
            # the report shows no failing test. A green report from a red run is not evidence
            # that the game plays.
            raise DriverUnavailable(
                f"the Playwright run failed ({result.describe()}) but its report shows no "
                "failing test", seen.evidence, blocked=False)
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
            keyword = [a for a in ASPECTS if a in KEYWORDS
                       and re.search(KEYWORDS[a], title, re.I)]
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
    return required_aspects_for(session.inputs.get("game-design"),
                                session.verification_flag("mobile_test"))


def required_aspects_for(design, mobile_test=True):
    """The aspects a build of `design` must prove, from the design alone - what the develop
    step's brief tells the developer to tag, so the two cannot disagree."""
    required = {"boot", "loading", "core-loop"}
    if mobile_test:
        required.add("responsive")
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


def content_conformance(session):
    """(ok or None, Evidence): does anything say the build carries the design's content units?

    None when the design authors none, so there is nothing to conform to. Otherwise, in order:
    what the develop step recorded (`docs/development/checks.json`, which carries its content
    check), else the data file the build reads its units out of (`public/content/units.json`)
    holding the id of every unit the run builds (wgflib.build_scope: the MVP at tier mvp, the
    MVP and post-mvp units at release). A build that does neither has not shown its content
    exists.
    """
    design = session.inputs.get("game-design")
    content, mode, units = genre_models.units_of(design, build_scope.design_tiers(design))
    if content is None:
        return None, Evidence("observation", "the design authors no content units "
                                             "(build_spec.content), so none can be conformed to")
    recorded = session.read_json(DEVELOP_CHECKS) or {}
    for entry in recorded.get("checks") or []:
        if isinstance(entry, dict) and "content" in str(entry.get("id", "")):
            passed = entry.get("status") == "passed"
            return passed, Evidence("file", f"develop recorded {entry.get('id')}: "
                                            f"{entry.get('status')} - {entry.get('summary')}",
                                    path=DEVELOP_CHECKS,
                                    content_hash=session.file_hash(DEVELOP_CHECKS))
    data = session.read_json(CONTENT_DATA)
    if data is None:
        return False, Evidence("file", f"{CONTENT_DATA} is missing, and {DEVELOP_CHECKS} records "
                                       "no content check: nothing says the designed units were "
                                       "built", path=CONTENT_DATA)
    text = json.dumps(data)
    absent = sorted(u.get("id") for u in units
                    if u.get("id") and f'"{u["id"]}"' not in text)
    return not absent, Evidence(
        "file", (f"{CONTENT_DATA} carries every unit the design's tier builds ({len(units)}, "
                 f"generation {mode})" if not absent else
                 f"{CONTENT_DATA} does not carry: {', '.join(absent)}"),
        path=CONTENT_DATA, content_hash=session.file_hash(CONTENT_DATA),
        data={"missing_units": absent} or None)


def _hold_progression(session, check, seen):
    """Progression passes on what the bot played, or on a tagged test plus the content data.

    `gameplay.progression` used to pass on a test whose title mentioned a score. Progression is
    the thing a prototype most often does not have, so it is now held to evidence that names
    it: `quality.progression:persists` (the bot reloaded the game and read it back), or a test
    the developer tagged `@progression` together with content conformance.
    """
    played = session.results.get("quality.progression:persists")
    if played is not None and played.status == PASS:
        check.evidence.append(Evidence("reference", "the playability bot reloaded the build and "
                                                    "found the designed progression intact",
                                       check_ref="quality.progression:persists"))
        if check.status != PASS:
            check.status = PASS
            check.message = "progression survived a reload when the bot played it: " \
                            + played.message[:200]
        return check
    if check.status != PASS:
        return check
    ok, evidence = content_conformance(session)
    check.evidence.append(evidence)
    if ok is False:
        check.status = FAIL if check.required else WARNING
        check.message = ("a test exercises progression, but nothing says the designed content "
                         f"units were built: {evidence.summary}")
    else:
        check.message += ("; the designed content units are accounted for" if ok
                          else "; the design authors no content units to account for")
    return check


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
        check = Check(f"gameplay.{aspect}", "gameplay", TITLES[aspect], status,
                      required=is_required, message=message, evidence=evidence)
        if aspect == "progression":
            check = _hold_progression(session, check, seen)
        out.append(session.record(check))
    if seen.console_errors:
        boot = session.results["gameplay.boot"]
        boot.evidence.append(Evidence("observation", f"{len(seen.console_errors)} console "
                                                     f"error(s): {seen.console_errors[0]}"))
        if boot.status == PASS:
            boot.status = FAIL if boot.required else WARNING
            boot.message = "the game logged errors while playing"
    return out

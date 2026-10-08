"""The regression firewall: every lesson's tests, run, and reported per lesson.

A lesson names the tests that prove its check holds (core/reference/lessons.yaml `tests`):

    catches      the NEGATIVE case - the check FAILS the build that showed the defect
    passes       the POSITIVE case - the check PASSES the fixed or accepted build
    generalizes  the check catches the defect in a game other than the one it was learned from

Each test asserts its case, so a lesson holds when every test it names exists and passes.
`run(lessons, root)` runs them in this process with unittest and returns one verdict per
lesson:

    PASS      every test named ran and passed
    FAIL      a test failed or errored
    MISSING   a test named does not exist (no file, or no such test in it)
    SKIP      a test was skipped - never a pass: a firewall that did not run is not a firewall
    NO_TESTS  the lesson names none: fine for a candidate, gap or process lesson; a FAIL for
              an active or validated one, and for a validated one missing a kind (its catches,
              passes and generalizes are all required)

and an overall verdict: PASS only when no lesson is FAIL, MISSING or SKIP. The tests live in
the Factory's checkout (scripts/tests/); an installed runtime does not ship them, so the
firewall runs in a development checkout and in CI (`wgf test-core --only KNOWLEDGE`).

`suite_of(contract)` groups a run's knowledge-contract `rules[].tests` (its regression suite)
the same way, for `wgf knowledge firewall --run <id>`.
"""

import contextlib
import importlib.util
import io
import os
import re
import sys
import unittest

from . import model

TEST_REF = re.compile(r"^(scripts/tests/[A-Za-z0-9_]+\.py)::([A-Za-z_][A-Za-z0-9_]*)$")
CASES = {"catches": "negative", "passes": "positive", "generalizes": "generalizes"}
PASS, FAIL, MISSING, SKIP, NO_TESTS = "PASS", "FAIL", "MISSING", "SKIP", "NO_TESTS"
HOLDING = ("active", "validated")


class FirewallUnusable(Exception):
    """The firewall cannot run here (no tests directory: an installed runtime)."""


def tests_dir(root):
    return os.path.join(root, "scripts", "tests")


_MODULES = {}


def _module(root, relpath):
    """The test module at `relpath`, imported once per process under its own name."""
    path = os.path.normcase(os.path.normpath(os.path.join(root, *relpath.split("/"))))
    if path in _MODULES:
        return _MODULES[path]
    directory = os.path.dirname(path)
    for entry in (directory, os.path.dirname(directory)):
        if entry not in sys.path:
            sys.path.insert(0, entry)
    name = os.path.splitext(os.path.basename(path))[0]
    module = sys.modules.get(name)
    if module is None or os.path.normcase(os.path.normpath(
            getattr(module, "__file__", "") or "")) != path:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        try:
            spec.loader.exec_module(module)
        except BaseException:
            sys.modules.pop(name, None)
            raise
    _MODULES[path] = module
    return module


def _cases(module, name):
    """The TestCase instances unittest discovery would run for `name` in the module: every
    TestCase class of the module that has it - defined there or inherited - and not switched
    off (a subclass that sets an inherited test to None does not run it)."""
    found = []
    for value in vars(module).values():
        if isinstance(value, type) and issubclass(value, unittest.TestCase) \
                and value.__module__ == module.__name__ and callable(getattr(value, name, None)):
            found.append(value(name))
    return found


def run_ref(ref, root):
    """{"ref", "status": PASS|FAIL|MISSING|SKIP, "detail"} of one test reference."""
    match = TEST_REF.match(str(ref))
    if not match:
        return {"ref": ref, "status": MISSING,
                "detail": "not scripts/tests/<file>.py::<test name>"}
    relpath, name = match.groups()
    if not os.path.isfile(os.path.join(root, *relpath.split("/"))):
        return {"ref": ref, "status": MISSING, "detail": f"{relpath} does not exist"}
    try:
        module = _module(root, relpath)
    except Exception as exc:  # noqa: BLE001 - a module that does not import fails its tests
        return {"ref": ref, "status": FAIL, "detail": f"{relpath} does not import: {exc}"}
    cases = _cases(module, name)
    if not cases:
        return {"ref": ref, "status": MISSING, "detail": f"{relpath} has no test {name}"}
    result = unittest.TestResult()
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        unittest.TestSuite(cases).run(result)
    problems = result.failures + result.errors
    if problems:
        text = problems[0][1].strip().splitlines()
        return {"ref": ref, "status": FAIL, "detail": text[-1] if text else "failed"}
    if result.skipped or result.testsRun == 0:
        reason = result.skipped[0][1] if result.skipped else "nothing ran"
        return {"ref": ref, "status": SKIP, "detail": f"skipped: {reason}"}
    if result.unexpectedSuccesses or result.expectedFailures:
        return {"ref": ref, "status": FAIL,
                "detail": "marked expectedFailure: a lesson's test asserts its case outright"}
    return {"ref": ref, "status": PASS, "detail": ""}


def _verdict(lesson, results, kinds=model.TEST_KINDS):
    lifecycle = lesson.get("lifecycle")
    every_kind = tuple(kinds) == tuple(model.TEST_KINDS)
    if not results:
        named = any(model.tests_of(lesson).values())
        if not every_kind and named:
            # Asked for one kind the lesson does not name: nothing to run, nothing failed.
            return NO_TESTS, f"names no {', '.join(kinds)} test"
        if lifecycle in HOLDING and not model.is_process(lesson):
            return FAIL, f"an {lifecycle} lesson names the tests that prove its check"
        return NO_TESTS, "names no test"
    statuses = {r["status"] for r in results}
    for status in (MISSING, FAIL, SKIP):
        if status in statuses:
            bad = [r for r in results if r["status"] == status]
            return status, "; ".join(f"{r['ref']}: {r['detail']}" for r in bad[:3])
    if lifecycle == "validated" and every_kind:
        kinds = {r["kind"] for r in results}
        lacking = [k for k in model.TEST_KINDS if k not in kinds]
        if lacking:
            return FAIL, f"a validated lesson names {', '.join(lacking)} tests too"
    return PASS, f"{len(results)} test(s) passed"


def run(lessons, root, ids=None, kinds=model.TEST_KINDS, runner=run_ref):
    """{"verdict", "counts", "lessons": [{id, lifecycle, status, verdict, why, tests}]}.

    `ids`: only these lessons; `kinds`: only these test kinds. Raises FirewallUnusable when
    the checkout holds no tests (an installed runtime)."""
    if not os.path.isdir(tests_dir(root)):
        raise FirewallUnusable("the regression firewall runs the Factory's own tests, which an "
                               "installed runtime does not ship - run it from a "
                               "web-game-factory checkout")
    wanted = set(ids) if ids else None
    rows, cache = [], {}
    entries = [l for l in (lessons or {}).get("lessons") or ()
               if isinstance(l, dict) and l.get("id")]
    unknown = sorted(wanted - {l["id"] for l in entries}) if wanted else []
    if unknown:
        raise FirewallUnusable(f"no lesson {', '.join(unknown)}")
    for lesson in entries:
        if wanted and lesson["id"] not in wanted:
            continue
        results = []
        for kind, refs in model.tests_of(lesson).items():
            if kind not in kinds:
                continue
            for ref in refs:
                if ref not in cache:
                    cache[ref] = runner(ref, root)
                results.append(dict(cache[ref], kind=kind, case=CASES[kind]))
        verdict, why = _verdict(lesson, results, kinds)
        rows.append({"id": lesson["id"], "lifecycle": lesson.get("lifecycle"),
                     "status": lesson.get("status"), "verdict": verdict, "why": why,
                     "tests": results})
    counts = {v: sum(1 for r in rows if r["verdict"] == v)
              for v in (PASS, FAIL, MISSING, SKIP, NO_TESTS)}
    bad = counts[FAIL] or counts[MISSING] or counts[SKIP]
    return {"verdict": FAIL if bad else PASS, "counts": counts, "lessons": rows,
            "tests_run": len(cache)}


def suite_of(contract):
    """A lessons-shaped {"lessons": [...]} of a run's knowledge-contract rules: each rule
    with the tests its contract names (the run's regression suite), so `run` can hold it."""
    out = []
    for rule in (contract or {}).get("rules") or ():
        if isinstance(rule, dict) and rule.get("id"):
            out.append({"id": rule["id"], "lifecycle": rule.get("lifecycle") or "active",
                        "status": rule.get("status"), "tests": rule.get("tests") or {}})
    return {"lessons": out}


def render_lines(report):
    lines = []
    for row in report["lessons"]:
        lines.append(f"{row['id']:<6} {row['verdict']:<8} {str(row['lifecycle']):<10} {row['why']}")
        for test in row["tests"]:
            if test["status"] != PASS:
                lines.append(f"         {test['status']:<8} [{test['case']}] {test['ref']}"
                             + (f" - {test['detail']}" if test["detail"] else ""))
    counts = report["counts"]
    lines.append(f"firewall: {report['verdict']} - " + ", ".join(
        f"{k.lower()} {v}" for k, v in counts.items()) + f" ({report['tests_run']} tests run)")
    return lines

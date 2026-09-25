"""Code: typecheck, lint and tests, through the game repository's own scripts.

The script names are the template's (`typecheck`, `lint`, `test:unit`, `test:integration`),
which its CI names after qa-report suites. A game that has no script for a required suite
is not verified on that suite - BLOCKED - rather than silently passing it.
"""

import re

from wgflib.template_contract import (PACKAGE_JSON, SCRIPT_LINT, SCRIPT_TEST,
                                     SCRIPT_TEST_INTEGRATION, SCRIPT_TEST_UNIT,
                                     SCRIPT_TYPECHECK)

from ..model import BLOCKED, FAIL, PASS, WARNING, Check, Evidence

__all__ = ["check_code", "CODE_CHECKS"]

# (check id, title, scripts tried in order, required)
CODE_CHECKS = (
    ("code.typecheck", "Typecheck", (SCRIPT_TYPECHECK,), True),
    ("code.lint", "Lint", (SCRIPT_LINT,), True),
    ("code.unit", "Unit tests", (SCRIPT_TEST_UNIT, SCRIPT_TEST), True),
    ("code.integration", "Integration tests", (SCRIPT_TEST_INTEGRATION,), False),
)

_COUNT = re.compile(r"(\d+)\s+(passed|failed|skipped)", re.I)


def test_counts(output):
    """Pass/fail/skip counts from a vitest or jest summary line, or None."""
    for line in reversed((output or "").splitlines()):
        if re.match(r"\s*Tests?\b", line) and _COUNT.search(line):
            counts = {"passed": 0, "failed": 0, "skipped": 0}
            for number, word in _COUNT.findall(line):
                counts[word.lower()] = int(number)
            return counts
    return None


def check_code(session):
    out = []
    for check_id, title, scripts, required in CODE_CHECKS:
        if not session.passed("build.install"):
            out.append(session.record(session.blocked_by(
                "build.install", id=check_id, category="code", title=title,
                required=required)))
            continue
        script = next((s for s in scripts if session.has_script(s)), None)
        if script is None:
            status = BLOCKED if required else WARNING
            out.append(session.record(Check(
                check_id, "code", title, status, required=required,
                message=f"package.json has no {' or '.join(scripts)} script",
                evidence=[Evidence("file", f"no script {' / '.join(scripts)} in package.json",
                                   path=PACKAGE_JSON)])))
            continue
        result = session.run(session.script_command(script))
        counts = test_counts(result.stdout + "\n" + result.stderr)
        status = PASS if result.ok else (BLOCKED if result.unavailable else FAIL)
        message = result.describe()
        if counts:
            message += f" ({counts['passed']} passed, {counts['failed']} failed)"
        out.append(session.record(Check(check_id, "code", title, status, required=required,
                                        message=message, counts=counts,
                                        evidence=[Evidence.of_command(result)])))
    return out

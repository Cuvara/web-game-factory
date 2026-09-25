"""Opt-in test flags: one meaning for every `WGF_*` switch a test reads.

    enabled("WGF_AJV")    True only when the variable is exactly "1"

Every opt-in (WGF_AJV, WGF_GOLDEN, WGF_TEMPLATE_RELEASE_TEST, WGF_LIVE_PROCESS_TEST, ...)
and every opt-out (WGF_SKIP_AJV) is read through this, so `WGF_AJV=true`, `=yes` or `=0`
mean the same thing in every test: not set. Before, some tests read a flag as truthy and
others as `== "1"`, so `WGF_AJV=0` ran the ajv checks in one file and skipped them in the
next. The variables are listed in docs/env-vars.md.

Standard library only; imported by the tests in this directory and by scripts/golden.
"""

import os

__all__ = ["enabled"]


def enabled(name):
    """True when the environment variable `name` is exactly "1"."""
    return os.environ.get(name) == "1"


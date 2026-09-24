"""The pinned web-game-template, for tests that read template files.

Every such test reads a checkout of the commit in workspace/config/template.lock.json
(wgflib.template.checkout), never the sibling working copy as it happens to be. When the
pin cannot be obtained (no git, offline and no sibling holding the commit) the test skips
with the reason - it never falls back to another revision.
"""

import functools
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from wgflib import template  # noqa: E402

__all__ = ["checkout", "with_dependencies"]


@functools.lru_cache(maxsize=None)
def checkout():
    """(path, None) for the pinned checkout, or (None, reason)."""
    try:
        return template.checkout(), None
    except template.TemplateError as exc:
        return None, f"pinned web-game-template unavailable: {exc}"


@functools.lru_cache(maxsize=None)
def with_dependencies():
    """(path, None) for the pinned checkout with node_modules installed, or (None, reason)."""
    path, reason = checkout()
    if path is None:
        return None, reason
    try:
        template.ensure_dependencies(path)
    except template.TemplateError as exc:
        return None, f"pinned web-game-template dependencies unavailable: {exc}"
    return path, None

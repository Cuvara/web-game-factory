"""Where things are.

Resolved from this file's own location rather than from the working directory, so a script
behaves the same whether it is run from the repository root or from a game repository that
has the Factory checked out beside it.
"""

import os

WGFLIB = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(WGFLIB)
ROOT = os.path.dirname(SCRIPTS)

CORE = os.path.join(ROOT, "core")
LIFECYCLE = os.path.join(CORE, "lifecycle")
ARTIFACTS = os.path.join(CORE, "artifacts")
REFERENCE = os.path.join(CORE, "reference")
PLATFORMS = os.path.join(REFERENCE, "platforms")
SCORING = os.path.join(REFERENCE, "scoring")

WORKSPACE = os.path.join(ROOT, "workspace")
TITLES = os.path.join(WORKSPACE, "titles")
OPPORTUNITIES = os.path.join(WORKSPACE, "opportunities")
CLAIMS = os.path.join(WORKSPACE, "claims")
CONFIG = os.path.join(WORKSPACE, "config")

# A sibling checkout, not a dependency. Everything that reads it degrades to a skip.
TEMPLATE = os.path.join(os.path.dirname(ROOT), "web-game-template")


def checkout_path(root, name):
    """`<root>/<name>` for a repository name read from an artifact, refusing any name that
    is not one plain directory entry. scaffold-record's pattern admits `.` and `..`, which
    would make a step review, verify or release the checkouts directory or its parent."""
    if (not isinstance(name, str) or not name or name in (".", "..")
            or any(c in name for c in "/\\\0") or name != name.strip()
            or any(ord(c) < 32 for c in name)):
        raise ValueError(f"repository name {name!r} is not a single directory name")
    return os.path.normpath(os.path.join(root, name))


def display(path):
    """A path as it should appear in output: repo-relative, forward slashes."""
    try:
        relative = os.path.relpath(path, ROOT)
    except ValueError:  # different drive on Windows
        relative = path
    return relative.replace(os.sep, "/")

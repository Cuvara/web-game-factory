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
    is not one plain directory entry. scaffold-record's schema refuses `.` and `..` too;
    this is the second layer, for a record that never went through the engine."""
    if (not isinstance(name, str) or not name or name in (".", "..")
            or any(c in name for c in "/\\\0") or name != name.strip()
            or any(ord(c) < 32 for c in name)):
        raise ValueError(f"repository name {name!r} is not a single directory name")
    return os.path.normpath(os.path.join(root, name))


def repo_relative(path):
    """True when `path` names a place inside a repository, judged the same on every platform.

    `os.path.isabs` is the host's rule, and the host's rule is not stable: on Windows with
    Python 3.13 and later `/etc/passwd` is drive-relative rather than absolute, so a guard
    written on `os.path.isabs` accepts it there and refuses it on Linux (found by MV-4 running
    the suite on Windows). A guard over input the Factory did not write - an agent's verdict,
    an artifact's path field - must not depend on which host is reading it, so this judges the
    string: no leading separator, no drive, no `..` on either separator."""
    if not isinstance(path, str) or not path.strip():
        return False
    if path[0] in "/\\":
        return False
    if len(path) >= 2 and path[1] == ":":
        return False
    return os.pardir not in path.replace("\\", "/").split("/")


def display(path):
    """A path as it should appear in output: repo-relative, forward slashes."""
    try:
        relative = os.path.relpath(path, ROOT)
    except ValueError:  # different drive on Windows
        relative = path
    return relative.replace(os.sep, "/")

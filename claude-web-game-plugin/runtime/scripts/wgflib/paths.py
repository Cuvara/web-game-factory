"""Where things are.

Two roots, never confused:

  ROOT     the Factory runtime: core/, the engine and its step modules, the shipped config
           defaults and the template pin. Resolved from this file's own location, never from
           the working directory. In a development checkout it is the repository; in an
           installed plugin it is the runtime bundled inside the plugin (`runtime/`), which
           `runtime-manifest.json` marks.
  PROJECT  the instance: workspace/ (claims, opportunities, titles, decisions, the
           installation's config), the run store and the game checkouts' base. In a
           development checkout it is the repository, exactly as before; from an installed
           runtime it is the working directory - the project the command was run in.
           WGF_PROJECT_DIR overrides both.

A run from an installed plugin therefore reads the Factory from the plugin and writes nothing
into it, and the working directory never decides where core/ is.
"""

import os

WGFLIB = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(WGFLIB)
ROOT = os.path.dirname(SCRIPTS)

# Written by scripts/build-plugin-runtime.py into the bundle it builds, and only there.
RUNTIME_MANIFEST = "runtime-manifest.json"
INSTALLED = os.path.isfile(os.path.join(ROOT, RUNTIME_MANIFEST))


def _project_root():
    chosen = os.environ.get("WGF_PROJECT_DIR")
    if chosen and chosen.strip():
        return os.path.abspath(os.path.expanduser(chosen.strip()))
    return os.path.abspath(os.getcwd()) if INSTALLED else ROOT


PROJECT = _project_root()
if INSTALLED:
    # Fixed for this process and every process it starts: a child started in another
    # directory (a step's tool, a resumed driver) must find the same instance.
    os.environ["WGF_PROJECT_DIR"] = PROJECT

CORE = os.path.join(ROOT, "core")
LIFECYCLE = os.path.join(CORE, "lifecycle")
ARTIFACTS = os.path.join(CORE, "artifacts")
REFERENCE = os.path.join(CORE, "reference")
PLATFORMS = os.path.join(REFERENCE, "platforms")
SCORING = os.path.join(REFERENCE, "scoring")

WORKSPACE = os.path.join(PROJECT, "workspace")
TITLES = os.path.join(WORKSPACE, "titles")
OPPORTUNITIES = os.path.join(WORKSPACE, "opportunities")
CLAIMS = os.path.join(WORKSPACE, "claims")
CONFIG = os.path.join(WORKSPACE, "config")
# The configuration the Factory ships: the defaults an instance without its own file gets.
FACTORY_CONFIG = os.path.join(ROOT, "workspace", "config")

# A sibling checkout, not a dependency. Everything that reads it degrades to a skip.
TEMPLATE = os.path.join(os.path.dirname(ROOT), "web-game-template")


def config_file(name):
    """The instance's `workspace/config/<name>` when it has one, else the Factory's shipped
    copy. The same file when the project is the Factory checkout."""
    own = os.path.join(CONFIG, name)
    return own if os.path.exists(own) else os.path.join(FACTORY_CONFIG, name)


def project_path(path):
    """An instance path setting (a store, a checkouts base, a titles directory) as an
    absolute path: `~` expanded, a relative one against the project root."""
    path = os.path.expanduser(str(path))
    return os.path.normpath(path if os.path.isabs(path) else os.path.join(PROJECT, path))


def both_roots(path):
    """A relative path under the Factory root and, when it is another directory, under the
    project root too - for guards, which must cover the Factory's tree and the instance's
    `workspace/config` wherever each is. An absolute path is itself."""
    if os.path.isabs(path):
        return [os.path.normpath(path)]
    found = [os.path.normpath(os.path.join(ROOT, path))]
    if os.path.normpath(PROJECT) != os.path.normpath(ROOT):
        found.append(os.path.normpath(os.path.join(PROJECT, path)))
    return found


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
    string: no leading separator, no drive, no `..` on either separator.

    Surrounding whitespace is stripped before judging, because it is not part of the path an
    agent means and it must not be a way past the guard: ` /etc/passwd` is `/etc/passwd`."""
    if not isinstance(path, str):
        return False
    path = path.strip()
    if not path:
        return False
    if path[0] in "/\\":
        return False
    if len(path) >= 2 and path[1] == ":":
        return False
    return os.pardir not in path.replace("\\", "/").split("/")


def display(path):
    """A path as it should appear in output: repo-relative, forward slashes. From an
    installed runtime, an instance path is shown relative to the project instead."""
    base = ROOT
    if PROJECT != ROOT:
        try:
            if os.path.commonpath([PROJECT, os.path.abspath(path)]) == PROJECT:
                base = PROJECT
        except ValueError:  # different drive on Windows
            pass
    try:
        relative = os.path.relpath(path, base)
    except ValueError:  # different drive on Windows
        relative = path
    return relative.replace(os.sep, "/")

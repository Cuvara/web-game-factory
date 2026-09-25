"""The development module's configuration: `factory.develop` in workspace/config/factory.yaml.

Everything here is installation policy - where game repositories are checked out, who does
the development, which checks must pass. None of it belongs in the workflow file, which is
core and names no local path or tool. A step's `with:` block may still override a key, for
a workflow that wants, say, a narrower check list.

    factory:
      develop:
        checkouts: ..              # game repositories live at <checkouts>/<repository.name>
        developer:
          kind: handoff            # handoff | command
          argv: []                 # command only; see developers.py for the placeholders
          timeout_seconds: 5400
          idle_timeout_seconds: null   # command only: no output for this long ends it
        checks: [install, typecheck, lint, unit, build, smoke]
        check_timeout_seconds: 900
        commit: true
        build_url: null            # e.g. "https://{branch}.{name}.pages.dev"
        skills: {}                 # per-engine host skill names the brief recommends
        writable_paths: [src/, tests/, public/, docs/development/, index.html]
        allowed_package_changes:   # what package.json may gain: add | change | remove
          dependencies: [add]
          devDependencies: [add]
        git:
          allow_filters: false     # true: commit through the repository's filters (git-lfs)
      agents:
        env_passthrough: []        # what the developer's environment carries beyond
                                   # wgflib.agentenv's allowlist (the host's credential)
      review:
        guarded_paths: [...]       # the Factory paths fingerprinted around the developer

`writable_paths` is what the development commit may contain (scope.py): a directory ends in
`/`, anything else is one file. package.json and pnpm-lock.yaml are never listed there -
they are committed when they change as `allowed_package_changes` permits (checks.py), and a
hidden path or an agent instruction file is refused whatever the list says.
"""

import copy
import os

from wgflib import agentenv, isolation, paths

from .scope import DEFAULT_WRITABLE, validate_writable

__all__ = ["Settings", "SettingsError", "DEFAULTS", "KNOWN_CHECKS", "PACKAGE_FIELDS",
           "PACKAGE_CHANGES"]

# The order checks run in. `smoke` needs `build`; the list a config gives is re-sorted into
# this order, so a config cannot ask for the smoke suite against a stale bundle.
KNOWN_CHECKS = ("install", "conformance", "format", "typecheck", "lint", "unit", "build",
                "smoke")

# The package.json fields a developer's change may touch at all, and how.
PACKAGE_FIELDS = ("dependencies", "devDependencies")
PACKAGE_CHANGES = ("add", "change", "remove")

DEFAULTS = {
    # The sibling-directory convention web-game-template already follows: the Factory's
    # parent directory. Relative values resolve against the Factory root, not the cwd, so
    # the same config means the same place from wherever `wgf` is run.
    "checkouts": "..",
    "developer": {"kind": "handoff", "argv": [], "timeout_seconds": 5400,
                  "idle_timeout_seconds": None},
    "checks": ["install", "conformance", "typecheck", "lint", "unit", "build", "smoke"],
    "check_timeout_seconds": 900,
    "commit": True,
    "build_url": None,
    "skills": {},
    "writable_paths": list(DEFAULT_WRITABLE),
    # Adding a dependency is how a game gets its engine package (the golden replay adds
    # pixi.js, or three and @types/three); changing or removing one the template pinned is
    # a template decision, so those are off unless an installation turns them on.
    "allowed_package_changes": {"dependencies": ["add"], "devDependencies": ["add"]},
    "git": {"allow_filters": False},
}


class SettingsError(ValueError):
    """The develop configuration is unusable. Not retryable: it will not fix itself."""


def _merge(base, override):
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _merge(base[key], value)
        else:
            base[key] = copy.deepcopy(value)
    return base


class Settings:
    def __init__(self, data, env_passthrough=(), guarded_paths=None):
        self.data = data
        # factory.agents.env_passthrough and factory.review.guarded_paths: installation
        # policy shared with the review step, read from their own sections.
        self.env_passthrough = list(env_passthrough or ())
        self.guarded_paths = (list(guarded_paths) if guarded_paths is not None
                              else isolation.guarded_paths(None))
        checks = data.get("checks") or []
        unknown = sorted(set(checks) - set(KNOWN_CHECKS))
        if unknown:
            raise SettingsError(
                f"factory.develop.checks names unknown checks {unknown}; "
                f"known: {', '.join(KNOWN_CHECKS)}"
            )
        # conformance is not optional: it is the only thing standing between "the tests
        # pass" and "the game quietly edited the template it was built from".
        self.checks = [c for c in KNOWN_CHECKS if c in checks or c == "conformance"]
        developer = data.get("developer") or {}
        self.developer = developer
        if developer.get("kind") not in ("handoff", "command"):
            raise SettingsError(
                f"factory.develop.developer.kind must be handoff or command, "
                f"not {developer.get('kind')!r}"
            )
        if developer.get("kind") == "command":
            argv = developer.get("argv")
            if not isinstance(argv, list) or not argv or not all(isinstance(a, str) for a in argv):
                raise SettingsError(
                    "factory.develop.developer.argv must be a non-empty list of strings "
                    "for kind: command"
                )
        try:
            self.writable_paths = validate_writable(data.get("writable_paths"))
        except ValueError as exc:
            raise SettingsError(str(exc))
        self.package_changes = self._package_changes(data.get("allowed_package_changes"))
        git = data.get("git") or {}
        if not isinstance(git, dict) or not isinstance(git.get("allow_filters", False), bool):
            raise SettingsError("factory.develop.git.allow_filters must be true or false")
        self.allow_filters = git.get("allow_filters", False)

    @staticmethod
    def _package_changes(value):
        if not isinstance(value, dict):
            raise SettingsError("factory.develop.allowed_package_changes must map "
                                f"{' / '.join(PACKAGE_FIELDS)} to a list of changes")
        allowed = {}
        for field, changes in value.items():
            if field not in PACKAGE_FIELDS:
                raise SettingsError(
                    f"factory.develop.allowed_package_changes names {field!r}; only "
                    f"{', '.join(PACKAGE_FIELDS)} may change - every other package.json "
                    "field, scripts included, is the template's")
            if not isinstance(changes, list) or not set(changes) <= set(PACKAGE_CHANGES):
                raise SettingsError(
                    f"factory.develop.allowed_package_changes.{field} must be a list of "
                    f"{', '.join(PACKAGE_CHANGES)}")
            allowed[field] = list(changes)
        return allowed

    @classmethod
    def resolve(cls, config, params=None):
        """Defaults, then factory.develop, then the step's `with:` block."""
        data = copy.deepcopy(DEFAULTS)
        _merge(data, (config or {}).get("develop") or {})
        _merge(data, {k: v for k, v in (params or {}).items() if k in DEFAULTS})
        try:
            passthrough = agentenv.passthrough(config)
            guarded = isolation.guarded_paths(config)
        except ValueError as exc:
            raise SettingsError(str(exc))
        return cls(data, passthrough, guarded)

    @property
    def commit(self):
        return bool(self.data.get("commit", True))

    @property
    def check_timeout(self):
        return float(self.data.get("check_timeout_seconds") or 900)

    @property
    def build_url(self):
        return self.data.get("build_url")

    @property
    def skills(self):
        return self.data.get("skills") or {}

    def checkout_for(self, repository_name):
        root = self.data.get("checkouts") or ".."
        if not os.path.isabs(root):
            root = os.path.join(paths.ROOT, root)
        try:
            return paths.checkout_path(root, repository_name)
        except ValueError as exc:
            raise SettingsError(str(exc))

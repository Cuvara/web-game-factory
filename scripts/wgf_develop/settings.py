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
        self_playtest: false       # the brief asks the developer to play its own build in
                                   # a browser; only for a developer given a browser tool
"""

import copy
import os

from wgflib import paths

__all__ = ["Settings", "SettingsError", "DEFAULTS", "KNOWN_CHECKS"]

# The order checks run in. `smoke` needs `build`; the list a config gives is re-sorted into
# this order, so a config cannot ask for the smoke suite against a stale bundle.
KNOWN_CHECKS = ("install", "conformance", "format", "typecheck", "lint", "unit", "build",
                "smoke")

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
    "self_playtest": False,
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
    def __init__(self, data):
        self.data = data
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

        if not isinstance(data.get("self_playtest", False), bool):
            raise SettingsError("factory.develop.self_playtest must be true or false")

    @classmethod
    def resolve(cls, config, params=None):
        """Defaults, then factory.develop, then the step's `with:` block."""
        data = copy.deepcopy(DEFAULTS)
        _merge(data, (config or {}).get("develop") or {})
        _merge(data, {k: v for k, v in (params or {}).items() if k in DEFAULTS})
        return cls(data)

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
    def self_playtest(self):
        return self.data.get("self_playtest") is True

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

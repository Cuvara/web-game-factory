"""The development module's configuration: `factory.develop` in workspace/config/factory.yaml.

Everything here is installation policy - where game repositories are checked out, who does
the development, which checks must pass. None of it belongs in the workflow file, which is
core and names no local path or tool. A step's `with:` block may still override a key, for
a workflow that wants, say, a narrower check list.

    factory:
      develop:
        checkouts: ..              # deprecated: factory.checkouts (wgflib.checkout)
        developer:
          kind: handoff            # handoff | command
          argv: []                 # command only; see developers.py for the placeholders
          timeout_seconds: 5400
          idle_timeout_seconds: null   # command only: no output for this long ends it
        checks: [install, typecheck, lint, unit, build, smoke]
        check_timeout_seconds: 900
        commit: true
        build_url: null            # e.g. "https://{branch}.{name}.pages.dev"
        skills: {}                 # area -> host skill names the brief recommends, merged
                                   # over the defaults (brief.DEFAULT_SKILLS); [] drops one
        self_playtest: false       # the brief asks the developer to play its own build in
                                   # a browser; only for a developer given a browser tool
        writable_paths: [src/, tests/, public/, docs/development/, index.html]
        allowed_package_changes:   # what package.json may gain: add | change | remove
          dependencies: [add]
          devDependencies: [add]
        git:
          allow_filters: false     # true: commit through the repository's filters (git-lfs)
      agents:
        env_passthrough: []        # what the developer's environment carries beyond
                                   # wgflib.agentenv's allowlist (the host's credential)
        game_env_passthrough: []   # what the checks (game code: install, tests, build)
                                   # get beyond the allowlist - never env_passthrough
      review:
        guarded_paths: [...]       # the Factory paths fingerprinted around the developer

`writable_paths` is what the development commit may contain (scope.py): a directory ends in
`/`, anything else is one file. package.json and pnpm-lock.yaml are never listed there -
they are committed when they change as `allowed_package_changes` permits (checks.py), and a
hidden path or an agent instruction file is refused whatever the list says. The one
exception is docs/GDD.md (scope.FACTORY_RENDERED): the step renders it from the
game-design artifact after the developer returns, so its content is always the Factory's.
"""

import copy

from wgflib import agentenv, checkout, isolation

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
    # Where the checkout is comes from wgflib.checkout (factory.checkouts; this key is its
    # deprecated alias). None here, so an unset key is not mistaken for a configured one.
    "checkouts": None,
    "developer": {"kind": "handoff", "argv": [], "timeout_seconds": 5400,
                  "idle_timeout_seconds": None},
    "checks": ["install", "conformance", "typecheck", "lint", "unit", "build", "smoke"],
    "check_timeout_seconds": 900,
    "commit": True,
    "build_url": None,
    "skills": {},
    "self_playtest": False,
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
    def __init__(self, data, env_passthrough=(), guarded_paths=None, game_env_passthrough=()):
        self.data = data
        # factory.agents.env_passthrough and factory.review.guarded_paths: installation
        # policy shared with the review step, read from their own sections.
        self.env_passthrough = list(env_passthrough or ())
        # factory.agents.game_env_passthrough: what the checks - code the developer wrote,
        # run by the Factory - get beyond the allowlist (checks.py, wgflib.agentenv).
        self.game_env_passthrough = list(game_env_passthrough or ())
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

        skills = data.get("skills") or {}
        if not isinstance(skills, dict) or not all(
                isinstance(area, str) and isinstance(names, list)
                and all(isinstance(n, str) and n for n in names)
                for area, names in skills.items()):
            raise SettingsError("factory.develop.skills must map an area (pixijs, threejs, "
                                "ui, craft, ...) to a list of skill names")
        if not isinstance(data.get("self_playtest", False), bool):
            raise SettingsError("factory.develop.self_playtest must be true or false")

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
            game_passthrough = agentenv.game_passthrough(config)
            guarded = isolation.guarded_paths(config)
        except ValueError as exc:
            raise SettingsError(str(exc))
        settings = cls(data, passthrough, guarded, game_passthrough)
        settings.config = config or {}
        settings.params = dict(params or {})
        return settings

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

    def checkout_for(self, repository_name, scaffold=None, environ=None, logger=None):
        """The game repository checkout, by wgflib.checkout's one precedence - the step's
        `with: repo_dir`, WGF_GAME_REPO, the scaffold-record's local_path, then
        factory.checkouts (develop.checkouts is its deprecated alias) + the name."""
        return self.locate(repository_name, scaffold, environ, logger)[0]

    def locate(self, repository_name, scaffold=None, environ=None, logger=None):
        """(path, source) - checkout_for, and which rule named the path."""
        try:
            return checkout.locate(getattr(self, "config", {}), scaffold, "develop",
                                   getattr(self, "params", {}), environ,
                                   name=repository_name, logger=logger)
        except checkout.CheckoutError as exc:
            raise SettingsError(str(exc))

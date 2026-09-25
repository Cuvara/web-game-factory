"""The review module's configuration: `factory.review` in workspace/config/factory.yaml.

    factory:
      review:
        reviewer:
          kind: none                 # none | command
          argv: []                   # command only; placeholders below
          timeout_seconds: 1800      # wall clock
          idle_timeout_seconds: 600  # no output for this long ends the review
          verdict_from: file         # file: the reviewer writes {verdict}
                                     # stdout: it prints the JSON last; the step saves it
        checkouts: null              # deprecated: factory.checkouts (wgflib.checkout)
        guarded_paths: [core, scripts, bin, workspace/config]   # also the develop step's
        fingerprint_ignored: true    # lstat everything inside pre-existing ignored entries
      agents:
        env_passthrough: []          # what the reviewer's environment carries beyond
                                     # wgflib.agentenv's allowlist (the host's credential)

`argv` placeholders, substituted per element: {repo} (the checkout, read-only), {verdict}
(where to write the verdict JSON - outside the checkout), {brief} (the review brief),
{commit} (the sha under review) and {prompt} (a one-paragraph instruction).

`verdict_from: stdout` is for a host run in a read-only sandbox, which cannot write a file
anywhere: the last JSON object on its stdout (bare, or in a ```json fence) is the verdict.

`guarded_paths` are Factory paths - relative to the Factory root - that a reviewer must not
touch either: the Factory's code (scripts/, bin/), core/ (the workflow definitions, the
gates and the contracts) and this configuration, which decide what a review - and every
later check - is worth. They are fingerprinted with the checkout. The develop step
fingerprints the same list around its developer and checks (wgflib/isolation.py).

`fingerprint_ignored` (default true) also lstats every file inside the checkout's
pre-existing ignored entries (node_modules, dist), so an edit to a dependency is caught.
Turn it off only where that walk is too slow; the review then cannot see those writes.
"""

import copy
import os

from wgflib import agentenv, checkout, paths
from wgflib.isolation import DEFAULT_GUARDED_PATHS

__all__ = ["Settings", "SettingsError", "DEFAULTS", "KINDS"]

KINDS = ("none", "command")

DEFAULTS = {
    "reviewer": {"kind": "none", "argv": [], "timeout_seconds": 1800,
                 "idle_timeout_seconds": 600, "verdict_from": "file"},
    "checkouts": None,
    "guarded_paths": list(DEFAULT_GUARDED_PATHS),
    "fingerprint_ignored": True,
}


class SettingsError(ValueError):
    """The review configuration is unusable. Not retryable: it will not fix itself."""


def _merge(base, override):
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _merge(base[key], value)
        else:
            base[key] = copy.deepcopy(value)
    return base


def _seconds(value, name, allow_none):
    if value is None and allow_none:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise SettingsError(f"factory.review.reviewer.{name} must be a number, not {value!r}")
    if number <= 0:
        raise SettingsError(f"factory.review.reviewer.{name} must be positive")
    return number


class Settings:
    def __init__(self, data, develop=None, env_passthrough=()):
        self.data = data
        self._develop = develop or {}
        # factory.agents.env_passthrough: what, beyond wgflib.agentenv's allowlist, the
        # reviewer's environment carries. Nothing else of the Factory's environment does.
        self.env_passthrough = list(env_passthrough or ())
        reviewer = data.get("reviewer") or {}
        self.reviewer = reviewer
        self.kind = reviewer.get("kind")
        if self.kind not in KINDS:
            raise SettingsError(f"factory.review.reviewer.kind must be one of "
                                f"{', '.join(KINDS)}, not {self.kind!r}")
        if self.kind == "command":
            argv = reviewer.get("argv")
            if not isinstance(argv, list) or not argv or not all(isinstance(a, str)
                                                                 for a in argv):
                raise SettingsError("factory.review.reviewer.argv must be a non-empty list "
                                    "of strings for kind: command")
        self.argv = list(reviewer.get("argv") or [])
        self.verdict_from = reviewer.get("verdict_from") or "file"
        if self.verdict_from not in ("file", "stdout"):
            raise SettingsError("factory.review.reviewer.verdict_from must be file or stdout")
        self.timeout = _seconds(reviewer.get("timeout_seconds", 1800), "timeout_seconds",
                                False)
        self.idle_timeout = _seconds(reviewer.get("idle_timeout_seconds"),
                                     "idle_timeout_seconds", True)
        guarded = data.get("guarded_paths") or []
        if not isinstance(guarded, list) or not all(isinstance(p, str) for p in guarded):
            raise SettingsError("factory.review.guarded_paths must be a list of paths")
        fingerprint = data.get("fingerprint_ignored", True)
        if not isinstance(fingerprint, bool):
            raise SettingsError("factory.review.fingerprint_ignored must be true or false")
        self.fingerprint_ignored = fingerprint
        self.guarded_paths = [os.path.normpath(p if os.path.isabs(p)
                                               else os.path.join(paths.ROOT, p))
                              for p in guarded]

    @classmethod
    def resolve(cls, config, params=None):
        """Defaults, then factory.review, then the step's `with:` block."""
        config = config or {}
        data = copy.deepcopy(DEFAULTS)
        _merge(data, config.get("review") or {})
        _merge(data, {k: v for k, v in (params or {}).items() if k in DEFAULTS})
        try:
            passthrough = agentenv.passthrough(config)
        except agentenv.ConfigError as exc:
            raise SettingsError(str(exc))
        settings = cls(data, config.get("develop"), passthrough)
        settings.config = config
        settings.params = dict(params or {})
        return settings

    def checkout_for(self, repository_name, scaffold=None, environ=None, logger=None):
        """The checkout develop built in: wgflib.checkout's one precedence, the same for
        every step - the step's `with: repo_dir`, WGF_GAME_REPO, the scaffold-record's
        local_path, then factory.checkouts (review.checkouts and develop.checkouts are
        deprecated aliases) + the name."""
        return self.locate(repository_name, scaffold, environ, logger)[0]

    def locate(self, repository_name, scaffold=None, environ=None, logger=None):
        """(path, source) - checkout_for, and which rule named the path."""
        try:
            return checkout.locate(getattr(self, "config", {}), scaffold, "review",
                                   getattr(self, "params", {}), environ,
                                   name=repository_name, logger=logger)
        except checkout.CheckoutError as exc:
            raise SettingsError(str(exc))

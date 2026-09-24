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
        checkouts: null              # default: factory.develop.checkouts, else ..
        guarded_paths: [core/workflows, workspace/config]

`argv` placeholders, substituted per element: {repo} (the checkout, read-only), {verdict}
(where to write the verdict JSON - outside the checkout), {brief} (the review brief),
{commit} (the sha under review) and {prompt} (a one-paragraph instruction).

`verdict_from: stdout` is for a host run in a read-only sandbox, which cannot write a file
anywhere: the last JSON object on its stdout (bare, or in a ```json fence) is the verdict.

`guarded_paths` are Factory paths - relative to the Factory root - that a reviewer must not
touch either: the workflow definitions and this configuration, which decide what a review
is worth. They are fingerprinted with the checkout.
"""

import copy
import os

from wgflib import paths

__all__ = ["Settings", "SettingsError", "DEFAULTS", "KINDS"]

KINDS = ("none", "command")

DEFAULTS = {
    "reviewer": {"kind": "none", "argv": [], "timeout_seconds": 1800,
                 "idle_timeout_seconds": 600, "verdict_from": "file"},
    "checkouts": None,
    "guarded_paths": ["core/workflows", "workspace/config"],
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
    def __init__(self, data, develop=None):
        self.data = data
        self._develop = develop or {}
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
        return cls(data, config.get("develop"))

    def checkout_for(self, repository_name):
        # The same checkout develop built in, unless review is pointed elsewhere.
        root = self.data.get("checkouts") or self._develop.get("checkouts") or ".."
        if not os.path.isabs(root):
            root = os.path.join(paths.ROOT, root)
        return os.path.normpath(os.path.join(root, repository_name))

"""The listing modules' configuration: `factory.listing` in workspace/config/factory.yaml.

    factory:
      listing:
        reference: null              # default core/reference/store-listing.yaml
        platforms: null              # default: the scaffold-record's game.config platforms
        locales: null                # default: en + every targeted platform's required locales
        copy_dir: workspace/titles/{title_id}/listing-copy
                                     # a person's own copy, <locale>.json each (localeCopy):
                                     # used instead of the writer for that locale, and
                                     # grounded like any other text. Relative to the project
        capture:
          kind: browser              # browser | none (none: BLOCKED - never a silent pass)
          node: node                 # the Node executable the capture script runs on
          timeout_seconds: 900       # one capture attempt, wall clock
          trailer: true              # record the gameplay trailer
          viewports: null            # default: the reference's landscape and portrait
        writer:
          kind: auto                 # auto | template | command. auto: the run tier's writer
                                     # (store-listing.yaml writer.by_tier) - the copywriter
                                     # agent (command) at release, the template for development
          argv: []                   # command only; {brief} {output} {prompt} placeholders
          timeout_seconds: 600
          idle_timeout_seconds: null
          text_from: file            # file: the writer writes {output}; stdout: prints JSON last

A step's `with:` block overrides any key (`repo_dir` / `game_repo` name the checkout, like
every step; `required_gates` the gates that must be passed, default [G4]).
"""

import copy
import os

from wgflib import agentenv, paths

__all__ = ["Settings", "SettingsError", "DEFAULTS", "REFERENCE_PATH"]

REFERENCE_PATH = os.path.join(paths.REFERENCE, "store-listing.yaml")
CAPTURE_KINDS = ("browser", "none")
WRITER_KINDS = ("auto", "template", "command")

DEFAULTS = {
    "reference": None,
    "platforms": None,
    "locales": None,
    "copy_dir": "workspace/titles/{title_id}/listing-copy",
    "capture": {"kind": "browser", "node": "node", "timeout_seconds": 900, "trailer": True,
                "viewports": None},
    "writer": {"kind": "auto", "argv": [], "timeout_seconds": 600,
               "idle_timeout_seconds": None, "text_from": "file"},
}


class SettingsError(ValueError):
    """The listing configuration is unusable. Not retryable: it will not fix itself."""


def _merge(base, override):
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _merge(base[key], value)
        else:
            base[key] = copy.deepcopy(value)
    return base


def _seconds(value, name, allow_none=False):
    if value is None and allow_none:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise SettingsError(f"factory.listing.{name} must be a number, not {value!r}")
    if number <= 0:
        raise SettingsError(f"factory.listing.{name} must be positive")
    return number


class Settings:
    def __init__(self, data, env_passthrough=()):
        self.data = data
        self.env_passthrough = list(env_passthrough or ())
        self.reference_path = data.get("reference") or REFERENCE_PATH
        if not os.path.isabs(self.reference_path):
            self.reference_path = os.path.join(paths.PROJECT, self.reference_path)
        platforms = data.get("platforms")
        if platforms is not None and (not isinstance(platforms, list)
                                      or not all(isinstance(p, str) and p for p in platforms)):
            raise SettingsError("factory.listing.platforms must be a list of platform ids or null")
        self.platforms = list(platforms) if platforms is not None else None
        locales = data.get("locales")
        if locales is not None and (not isinstance(locales, list)
                                    or not all(isinstance(l, str) and l for l in locales)):
            raise SettingsError("factory.listing.locales must be a list of locales or null")
        self.locales = [l.lower() for l in locales] if locales is not None else None
        copy_dir = data.get("copy_dir")
        if copy_dir is not None and (not isinstance(copy_dir, str) or not copy_dir.strip()):
            raise SettingsError("factory.listing.copy_dir must be a directory path or null")
        self.copy_dir = copy_dir
        capture = data.get("capture") or {}
        self.capture_kind = capture.get("kind")
        if self.capture_kind not in CAPTURE_KINDS:
            raise SettingsError(f"factory.listing.capture.kind must be one of "
                                f"{', '.join(CAPTURE_KINDS)}, not {self.capture_kind!r}")
        self.node = capture.get("node") or "node"
        if not isinstance(self.node, str):
            raise SettingsError("factory.listing.capture.node must be an executable name")
        self.capture_timeout = _seconds(capture.get("timeout_seconds", 900), "capture.timeout_seconds")
        self.trailer = bool(capture.get("trailer", True))
        viewports = capture.get("viewports")
        if viewports is not None:
            if not isinstance(viewports, list) or not all(
                    isinstance(v, dict) and isinstance(v.get("id"), str)
                    and isinstance(v.get("width"), int) and isinstance(v.get("height"), int)
                    for v in viewports):
                raise SettingsError("factory.listing.capture.viewports must be a list of "
                                    "{id, width, height[, mobile]} or null")
        self.viewports = viewports
        writer = data.get("writer") or {}
        self.writer_kind = writer.get("kind")
        if self.writer_kind not in WRITER_KINDS:
            raise SettingsError(f"factory.listing.writer.kind must be one of "
                                f"{', '.join(WRITER_KINDS)}, not {self.writer_kind!r}")
        argv = writer.get("argv")
        if self.writer_kind == "command" and (not isinstance(argv, list) or not argv
                                              or not all(isinstance(a, str) for a in argv)):
            raise SettingsError("factory.listing.writer.argv must be a non-empty list of "
                                "strings for kind: command")
        self.writer = {
            "kind": self.writer_kind, "argv": list(argv or []),
            "timeout_seconds": _seconds(writer.get("timeout_seconds", 600), "writer.timeout_seconds"),
            "idle_timeout_seconds": _seconds(writer.get("idle_timeout_seconds"),
                                             "writer.idle_timeout_seconds", allow_none=True),
            "text_from": writer.get("text_from") or "file",
            "env_passthrough": self.env_passthrough,
        }
        if self.writer["text_from"] not in ("file", "stdout"):
            raise SettingsError("factory.listing.writer.text_from must be file or stdout")

    def copy_dir_for(self, title_id):
        """The directory a person's own copy for `title_id` is read from, or None."""
        if not self.copy_dir:
            return None
        path = self.copy_dir.replace("{title_id}", str(title_id or "untitled"))
        return path if os.path.isabs(path) else os.path.join(paths.PROJECT, path)

    @classmethod
    def resolve(cls, config, params=None):
        """Defaults, then factory.listing, then the step's `with:` block."""
        config = config or {}
        data = copy.deepcopy(DEFAULTS)
        _merge(data, config.get("listing") or {})
        _merge(data, {k: v for k, v in (params or {}).items() if k in DEFAULTS})
        try:
            passthrough = agentenv.passthrough(config)
        except agentenv.ConfigError as exc:
            raise SettingsError(str(exc))
        return cls(data, passthrough)

"""The installation's factory configuration: workspace/config/factory.yaml.

Core ships the workflow definitions; this file is where one installation decides which is
the default, how patient retries are, which runtime executes steps, which step modules are
installed and where run state is kept. Every key is optional - an absent file means the
defaults below, which is what a fresh checkout and the test suite both get.
"""

import copy
import os
import re

from .. import paths
from ..yamllite import load_file
from .definition import RetryPolicy

__all__ = ["FactoryConfig", "load_config", "DEFAULT_CONFIG_PATH", "DEFAULTS", "ConfigError",
           "parse_duration"]

DEFAULT_CONFIG_PATH = os.path.join(paths.CONFIG, "factory.yaml")

DEFAULTS = {
    "workflow": {"default": "new-game"},
    "execution": {
        "max_attempts": 3,
        "backoff": "exponential",
        "delay_seconds": 2,
        "max_delay_seconds": 60,
        "max_visits": 5,
        # `wgf status` calls a RUNNING step with no sign of life for longer than this hung.
        "hung_after_seconds": 300,
    },
    "agents": {"default": "local"},
    "storage": {"directory": ".factory", "fsync": True},
    "steps": {"modules": []},
    # auto_approve: gates a run approves at once. timeout_auto_approve: {gate: window} - a
    # gate that approves itself once it has waited that long ("48h", "30m", "2d", or
    # seconds) and a `wgf resume` finds it so. Both only ever apply to a reversible gate
    # gates.yaml defines; api.py refuses to start a run whose windows name any other.
    "checkpoints": {"auto_approve": [], "timeout_auto_approve": {}},
}


class ConfigError(ValueError):
    """A configuration value wgf will not act on."""


_DURATION = re.compile(r"(\d+)\s*([smhd])")
_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


def parse_duration(value):
    """Seconds, as a positive int, from `48h`, `30m`, `2d`, `90s` or a positive integer of
    seconds. Anything else - zero, a negative, a fraction, a bool - raises ConfigError."""
    if isinstance(value, bool):
        raise ConfigError(f"duration {value!r} is not a duration")
    if isinstance(value, int):
        seconds = value
    elif isinstance(value, str) and _DURATION.fullmatch(value.strip()):
        number, unit = _DURATION.fullmatch(value.strip()).groups()
        seconds = int(number) * _UNIT_SECONDS[unit]
    else:
        raise ConfigError(f"duration {value!r} is not one of <n>s, <n>m, <n>h, <n>d or a "
                          f"whole number of seconds")
    if seconds <= 0:
        raise ConfigError(f"duration {value!r} is not positive")
    return seconds


def _merge(base, override):
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _merge(base[key], value)
        else:
            base[key] = value
    return base


class FactoryConfig:
    def __init__(self, data=None, source=None):
        self.data = _merge(copy.deepcopy(DEFAULTS), data or {})
        self.source = source

    def section(self, name):
        return self.data.get(name) or {}

    @property
    def default_workflow(self):
        return self.section("workflow").get("default")

    @property
    def runtime(self):
        return self.section("agents").get("default")

    @property
    def step_modules(self):
        return list(self.section("steps").get("modules") or [])

    @property
    def auto_approve(self):
        return list(self.section("checkpoints").get("auto_approve") or [])

    @property
    def timeout_auto_approve(self):
        """{gate: seconds} from factory.checkpoints.timeout_auto_approve. Raises ConfigError
        for a value that is not a mapping of gate ids to durations. Which gates may be
        listed at all is checked where a run is started (api.timeout_windows)."""
        raw = self.section("checkpoints").get("timeout_auto_approve") or {}
        if not isinstance(raw, dict):
            raise ConfigError("factory.checkpoints.timeout_auto_approve must be a mapping of "
                              "gate ids to durations, e.g. {G2: 48h, G3: 48h}")
        windows = {}
        for gate, value in raw.items():
            if not isinstance(gate, str):
                raise ConfigError(f"factory.checkpoints.timeout_auto_approve: {gate!r} is "
                                  f"not a gate id")
            try:
                windows[gate] = parse_duration(value)
            except ConfigError as exc:
                raise ConfigError(f"factory.checkpoints.timeout_auto_approve.{gate}: {exc}")
        return windows

    @property
    def max_visits(self):
        return self.section("execution").get("max_visits")

    @property
    def hung_after_seconds(self):
        value = self.section("execution").get("hung_after_seconds", 300)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
            return 300
        return value

    def retry_policy(self):
        execution = self.section("execution")
        return RetryPolicy(
            max_attempts=execution.get("max_attempts", 1),
            backoff=execution.get("backoff", "none"),
            delay_seconds=execution.get("delay_seconds", 0),
            max_delay_seconds=execution.get("max_delay_seconds", 60),
        )

    @property
    def fsync(self):
        return bool(self.section("storage").get("fsync", True))

    def storage_directory(self, base=None):
        """Absolute storage directory. A relative setting resolves against `base`, by default
        the repository root - like every other path the config names - so `wgf` run from a
        subdirectory finds the same store instead of starting a second one."""
        directory = self.section("storage").get("directory")
        return os.path.abspath(os.path.join(base or paths.ROOT, directory))


def load_config(path=None):
    """Read the config file, or the defaults when it does not exist."""
    path = path or DEFAULT_CONFIG_PATH
    if not os.path.exists(path):
        return FactoryConfig(source=None)
    document = load_file(path) or {}
    return FactoryConfig(document.get("factory") or {}, source=path)

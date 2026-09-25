"""The installation's factory configuration: workspace/config/factory.yaml.

Core ships the workflow definitions; this file is where one installation decides which is
the default, how patient retries are, which runtime executes steps, which step modules are
installed and where run state is kept. Every key is optional - an absent file means the
defaults below, which is what a fresh checkout and the test suite both get.
"""

import copy
import os
import re

from .. import budget, paths
from ..yamllite import load_file
from .definition import RetryPolicy
from .model import DEFAULT_HUNG_OUTPUT_SECONDS

__all__ = ["FactoryConfig", "load_config", "DEFAULT_CONFIG_PATH", "DEFAULTS", "ConfigError",
           "parse_duration", "ON_HUNG"]

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
        # ... and one whose child has written nothing for longer than this, while the
        # driver's heartbeats keep arriving (model.DEFAULT_HUNG_OUTPUT_SECONDS says why 900).
        "hung_output_seconds": DEFAULT_HUNG_OUTPUT_SECONDS,
        # What the driving engine does about such a child: `none` (status reports it) or
        # `cancel` (its tree is terminated and the step ends, not retryably).
        "on_hung": "none",
    },
    "agents": {"default": "local"},
    "storage": {"directory": ".factory", "fsync": True},
    "steps": {"modules": []},
    # auto_approve: gates a run approves at once. timeout_auto_approve: {gate: window} - a
    # gate that approves itself once it has waited that long ("48h", "30m", "2d", or
    # seconds) and a `wgf resume` finds it so. Both only ever apply to a reversible gate
    # gates.yaml defines; api.py refuses to start a run whose windows name any other.
    "checkpoints": {"auto_approve": [], "timeout_auto_approve": {}},
    # The lifecycle bridge (wgflib/lifecycle_bridge.py): with `sync: true`, a gate decision
    # of a run whose title has a cursor under `titles_directory` (default
    # workspace/titles) is appended to the title's decisions/ and moves its cursor through
    # wgf-state.py's own rules. Off by default; a run keeps the setting it started with.
    "lifecycle": {"sync": False, "titles_directory": None},
}


class ConfigError(ValueError):
    """A configuration value wgf will not act on."""


# factory.execution.on_hung: what the driving engine does about a child that has written
# nothing for hung_output_seconds.
ON_HUNG = ("none", "cancel")


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
    def lifecycle_sync(self):
        """factory.lifecycle.sync: true or false (default). Fail closed: anything else raises
        ConfigError - `"yes"` is not a way to turn on writes into workspace/."""
        value = self.section("lifecycle").get("sync", False)
        if value is None:
            return False
        if not isinstance(value, bool):
            raise ConfigError(f"factory.lifecycle.sync is {value!r}; expected true or false")
        return value

    def lifecycle_titles_directory(self, base=None):
        """Absolute directory of the title cursors the lifecycle bridge syncs: the setting,
        relative to `base` (default the repository root), else workspace/titles."""
        directory = self.section("lifecycle").get("titles_directory")
        if not directory:
            return paths.TITLES
        if not isinstance(directory, str):
            raise ConfigError("factory.lifecycle.titles_directory must be a path")
        return os.path.abspath(os.path.join(base or paths.ROOT, directory))

    @property
    def develop_budget(self):
        """factory.develop.budget as the snapshot a run records (wgflib.budget), or None for
        no budget. Fail closed: a value that is not a budget raises ConfigError - a run is
        not started under a limit nobody can tell apart from no limit."""
        try:
            return budget.parse(self.section("develop").get("budget"))
        except budget.BudgetError as exc:
            raise ConfigError(str(exc))

    @property
    def max_visits(self):
        return self.section("execution").get("max_visits")

    @property
    def hung_after_seconds(self):
        value = self.section("execution").get("hung_after_seconds", 300)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
            return 300
        return value

    @property
    def hung_output_seconds(self):
        """factory.execution.hung_output_seconds: a positive number, else the default."""
        value = self.section("execution").get("hung_output_seconds",
                                              DEFAULT_HUNG_OUTPUT_SECONDS)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
            return DEFAULT_HUNG_OUTPUT_SECONDS
        return value

    @property
    def on_hung(self):
        """factory.execution.on_hung, one of ON_HUNG. Fail closed: any other value raises
        ConfigError rather than silently meaning `none` - a run is not started under a
        watchdog policy nobody can tell apart from no watchdog."""
        value = self.section("execution").get("on_hung", "none")
        if value is None:
            return "none"
        if value not in ON_HUNG:
            raise ConfigError(f"factory.execution.on_hung is {value!r}; expected one of "
                              f"{', '.join(ON_HUNG)}")
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

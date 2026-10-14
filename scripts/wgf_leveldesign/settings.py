"""The level-design module's configuration: `factory.leveldesign` in workspace/config/factory.yaml.

    factory:
      leveldesign:
        judge:
          kind: none                 # none | command | baseline
          argv: []                   # command only; placeholders as visual QA's
          timeout_seconds: 900       # wall clock, per judge invocation
          idle_timeout_seconds: null
          verdict_from: file         # file: the judge writes {verdict} | stdout: prints it last
          repair_rounds: 2           # a malformed verdict goes back with every error
          baseline_dir: null         # baseline only: approved unit frames and approved.json
          min_similarity: null       # baseline only: default the rubric's baseline.min_similarity
        rubric: null                 # default core/reference/level-design-rubric.yaml (pinned)

`argv` placeholders, substituted per element: {frames_dir} (a directory holding only the
frames to judge, as <unit id>/<moment>.png - copies, verified against the sha256 the
playability bot recorded), {brief}, {verdict} and {prompt}. The judge runs with the directory
holding the frames and the brief as its working directory, never in the game checkout, with
the allowlisted environment (factory.agents.env_passthrough).

`kind: baseline` is no agent (baseline.py). `kind: none` judges nothing: SKIPPED below a strict
tier, BLOCKED at one - never a silent pass.
"""

import copy
import os

from wgflib import agentenv, paths

__all__ = ["Settings", "SettingsError", "DEFAULTS", "KINDS"]

KINDS = ("none", "command", "baseline")

DEFAULTS = {
    "judge": {"kind": "none", "argv": [], "timeout_seconds": 900,
              "idle_timeout_seconds": None, "verdict_from": "file", "repair_rounds": 2},
    "rubric": None,
}


class SettingsError(ValueError):
    """The level-design configuration is unusable. Not retryable."""


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
        raise SettingsError(f"factory.leveldesign.judge.{name} must be a number, not {value!r}")
    if number <= 0:
        raise SettingsError(f"factory.leveldesign.judge.{name} must be positive")
    return number


class Settings:
    def __init__(self, data, env_passthrough=()):
        self.data = data
        self.env_passthrough = list(env_passthrough or ())
        judge = data.get("judge") or {}
        self.kind = judge.get("kind")
        if self.kind not in KINDS:
            raise SettingsError(f"factory.leveldesign.judge.kind must be one of "
                                f"{', '.join(KINDS)}, not {self.kind!r}")
        argv = judge.get("argv")
        if self.kind == "command" and (not isinstance(argv, list) or not argv
                                       or not all(isinstance(a, str) for a in argv)):
            raise SettingsError("factory.leveldesign.judge.argv must be a non-empty list of "
                                "strings for kind: command")
        self.argv = list(argv or [])
        self.verdict_from = judge.get("verdict_from") or "file"
        if self.verdict_from not in ("file", "stdout"):
            raise SettingsError("factory.leveldesign.judge.verdict_from must be file or stdout")
        self.timeout = _seconds(judge.get("timeout_seconds", 900), "timeout_seconds", False)
        self.idle_timeout = _seconds(judge.get("idle_timeout_seconds"),
                                     "idle_timeout_seconds", True)
        rounds = judge.get("repair_rounds", 2)
        if isinstance(rounds, bool) or not isinstance(rounds, int) or not 0 <= rounds <= 10:
            raise SettingsError("factory.leveldesign.judge.repair_rounds must be a whole "
                                f"number 0-10, not {rounds!r}")
        self.repair_rounds = rounds
        self.rubric_path = data.get("rubric")
        self.baseline_dir = judge.get("baseline_dir")
        self.min_similarity = judge.get("min_similarity")
        if self.kind == "baseline":
            if self.baseline_dir is not None:
                if not isinstance(self.baseline_dir, str) or not self.baseline_dir:
                    raise SettingsError("factory.leveldesign.judge.baseline_dir must be a "
                                        "directory path")
                if not os.path.isabs(self.baseline_dir):
                    self.baseline_dir = os.path.join(paths.PROJECT, self.baseline_dir)
            if self.min_similarity is not None and (
                    isinstance(self.min_similarity, bool)
                    or not isinstance(self.min_similarity, (int, float))
                    or not 0 < self.min_similarity <= 1):
                raise SettingsError("factory.leveldesign.judge.min_similarity must be a "
                                    "number in (0, 1]")

    @classmethod
    def resolve(cls, config, params=None):
        """Defaults, then factory.leveldesign, then the step's `with:` block."""
        config = config or {}
        data = copy.deepcopy(DEFAULTS)
        _merge(data, config.get("leveldesign") or {})
        _merge(data, {k: v for k, v in (params or {}).items() if k in DEFAULTS})
        try:
            passthrough = agentenv.passthrough(config)
        except agentenv.ConfigError as exc:
            raise SettingsError(str(exc))
        return cls(data, passthrough)

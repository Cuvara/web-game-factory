"""The visual-qa module's configuration: `factory.visualqa` in workspace/config/factory.yaml.

    factory:
      visualqa:
        judge:
          kind: none                 # none | command | baseline
          argv: []                   # command only; placeholders below
          timeout_seconds: 900       # wall clock, per judge invocation
          idle_timeout_seconds: null # no output for this long ends the judge
          verdict_from: file         # file: the judge writes {verdict}
                                     # stdout: it prints the JSON last; the step saves it
          baseline_dir: null         # baseline only: <viewport>/<name>.png approved frames
          min_similarity: null       # baseline only: default baseline.MIN_SIMILARITY
        rubric: null                 # default core/reference/visual-qa-rubric.yaml
      agents:
        env_passthrough: []          # what the judge's environment carries beyond
                                     # wgflib.agentenv's allowlist (the host's credential)

`argv` placeholders, substituted per element: {frames_dir} (a directory holding only the
frames to judge, as <viewport>/<frame-id>.png - copies, verified against the
playability-report's sha256), {brief} (the judge brief, markdown), {verdict} (where to
write the verdict JSON) and {prompt} (a one-paragraph instruction naming all three). The
judge runs with the directory holding the frames and the brief as its working directory,
never in the game checkout.

`kind: baseline` is no agent: each frame is compared with the approved frame of the same state
under `baseline_dir` (baseline.py) - for a game whose look was approved once, such as a golden
run's reference port. Relative paths resolve against the project directory.

`kind: none` BLOCKS the step: visual QA needs a judge, and a step that passes without one
would be a silent pass. There is no skipped verdict.
"""

import copy

import os

from wgflib import agentenv, paths

__all__ = ["Settings", "SettingsError", "DEFAULTS", "KINDS"]

KINDS = ("none", "command", "baseline")

DEFAULTS = {
    "judge": {"kind": "none", "argv": [], "timeout_seconds": 900,
              "idle_timeout_seconds": None, "verdict_from": "file"},
    "rubric": None,
}


class SettingsError(ValueError):
    """The visual-qa configuration is unusable. Not retryable: it will not fix itself."""


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
        raise SettingsError(f"factory.visualqa.judge.{name} must be a number, not {value!r}")
    if number <= 0:
        raise SettingsError(f"factory.visualqa.judge.{name} must be positive")
    return number


class Settings:
    def __init__(self, data, env_passthrough=()):
        self.data = data
        self.env_passthrough = list(env_passthrough or ())
        judge = data.get("judge") or {}
        self.kind = judge.get("kind")
        if self.kind not in KINDS:
            raise SettingsError(f"factory.visualqa.judge.kind must be one of "
                                f"{', '.join(KINDS)}, not {self.kind!r}")
        argv = judge.get("argv")
        if self.kind == "command" and (not isinstance(argv, list) or not argv
                                       or not all(isinstance(a, str) for a in argv)):
            raise SettingsError("factory.visualqa.judge.argv must be a non-empty list of "
                                "strings for kind: command")
        self.argv = list(argv or [])
        self.verdict_from = judge.get("verdict_from") or "file"
        if self.verdict_from not in ("file", "stdout"):
            raise SettingsError("factory.visualqa.judge.verdict_from must be file or stdout")
        self.timeout = _seconds(judge.get("timeout_seconds", 900), "timeout_seconds", False)
        self.idle_timeout = _seconds(judge.get("idle_timeout_seconds"),
                                     "idle_timeout_seconds", True)
        self.rubric_path = data.get("rubric")
        self.baseline_dir = judge.get("baseline_dir")
        self.min_similarity = judge.get("min_similarity")
        if self.kind == "baseline":
            if not isinstance(self.baseline_dir, str) or not self.baseline_dir:
                raise SettingsError("factory.visualqa.judge.baseline_dir must name the "
                                    "directory of approved frames for kind: baseline")
            if not os.path.isabs(self.baseline_dir):
                self.baseline_dir = os.path.join(paths.PROJECT, self.baseline_dir)
            if self.min_similarity is not None and (
                    isinstance(self.min_similarity, bool)
                    or not isinstance(self.min_similarity, (int, float))
                    or not 0 < self.min_similarity <= 1):
                raise SettingsError("factory.visualqa.judge.min_similarity must be a number "
                                    "in (0, 1]")

    @classmethod
    def resolve(cls, config, params=None):
        """Defaults, then factory.visualqa, then the step's `with:` block."""
        config = config or {}
        data = copy.deepcopy(DEFAULTS)
        _merge(data, config.get("visualqa") or {})
        _merge(data, {k: v for k, v in (params or {}).items() if k in DEFAULTS})
        try:
            passthrough = agentenv.passthrough(config)
        except agentenv.ConfigError as exc:
            raise SettingsError(str(exc))
        return cls(data, passthrough)

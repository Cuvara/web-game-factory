"""The installation's quality bar: frames of finished games shown to every agent that makes or
judges how a game looks (workspace/quality-bar/quality-bar.yaml).

Shared installation data, read by four step modules (design, develop, assets, visual-qa),
which is why it is here rather than in one of them. A project overrides the shipped bar with
its own `workspace/quality-bar/` (paths.PROJECT), exactly as it overrides configuration.

    frames(dimension="2d") -> [{"path": <absolute>, "dimension", "state", "shows"}]
    qualities()            -> [str]
"""

import os

from . import paths
from .yamllite import YamlError, load_file

__all__ = ["directory", "load", "frames", "qualities"]

NAME = "quality-bar.yaml"


def directory():
    """The project's quality-bar directory when it has one, else the shipped one, else None."""
    for root in (paths.PROJECT, paths.ROOT):
        candidate = os.path.join(root, "workspace", "quality-bar")
        if os.path.isfile(os.path.join(candidate, NAME)):
            return candidate
    return None


def load():
    """The parsed quality-bar.yaml, or {} when there is none or it cannot be read."""
    where = directory()
    if not where:
        return {}
    try:
        data = load_file(os.path.join(where, NAME))
    except (OSError, YamlError):
        return {}
    return data if isinstance(data, dict) else {}


def frames(dimension=None):
    """Every frame (of `dimension`, when given) whose file exists, with an absolute path."""
    where = directory()
    out = []
    for frame in load().get("frames") or []:
        if not isinstance(frame, dict) or not frame.get("file"):
            continue
        if dimension and frame.get("dimension") != dimension:
            continue
        path = os.path.join(where, frame["file"])
        if os.path.isfile(path):
            out.append({"path": path, "dimension": frame.get("dimension"),
                        "state": frame.get("state"),
                        "shows": " ".join(str(frame.get("shows") or "").split())})
    return out


def qualities():
    return [" ".join(str(q).split()) for q in load().get("qualities") or [] if q]

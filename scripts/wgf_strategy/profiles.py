"""Platform profiles, read from core/reference/platforms/ as the binding constraints they are.

A profile is identified by its `id` and pinned by its `version`; the strategy records both
so a later build can be checked against the rules that were in force when it was planned.
"""

import glob
import os

from wgflib import paths
from wgflib.yamllite import load

__all__ = ["load_profiles"]


def load_profiles(directory=None):
    """{platform id: profile} for every profile file in `directory`."""
    profiles = {}
    for path in sorted(glob.glob(os.path.join(directory or paths.PLATFORMS, "*.yaml"))):
        with open(path, encoding="utf-8") as handle:
            profile = load(handle.read())
        if isinstance(profile, dict) and profile.get("id"):
            profiles[profile["id"]] = profile
    return profiles

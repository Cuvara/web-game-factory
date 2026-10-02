"""Platform profiles, read from core/reference/platforms/ as the binding constraints they are.

A profile is identified by its `id` and pinned by its `version`; the strategy records both
so a later build can be checked against the rules that were in force when it was planned.
"""

import glob
import os

from wgflib import paths
from wgflib.yamllite import load

__all__ = ["load_profiles", "load_vocabulary"]


def load_profiles(directory=None):
    """{platform id: profile} for every profile file in `directory`."""
    profiles = {}
    for path in sorted(glob.glob(os.path.join(directory or paths.PLATFORMS, "*.yaml"))):
        with open(path, encoding="utf-8") as handle:
            profile = load(handle.read())
        if isinstance(profile, dict) and profile.get("id"):
            profiles[profile["id"]] = profile
    return profiles


def load_vocabulary(path=None):
    """The research-vocabulary mappings strategy reads: {"control_schemes": {control id:
    title-strategy control scheme}}. Empty when the vocabulary is absent."""
    path = path or os.path.join(paths.REFERENCE, "research-vocabulary.yaml")
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as handle:
        document = load(handle.read()) or {}
    controls = (document.get("vocabularies") or {}).get("controls") or []
    return {"control_schemes": {c["id"]: c["control_scheme"] for c in controls
                                if c.get("control_scheme")}}

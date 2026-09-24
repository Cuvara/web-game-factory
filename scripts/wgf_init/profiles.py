"""Vendor the pinned platform profiles into the project's config/platforms/.

A game repository does not contain the Factory, and release validation judges a build by
the profile version its plan pinned (web-game-template config/platforms/pinned.json and
scripts/verify/evaluate-assertions.mjs read config/platforms/<id>.yaml). The files are
byte-identical copies of core/reference/platforms/<id>.yaml, so a drift is a plain diff, and
pinned.json lists each with the sha256 of its bytes.

A pin that no longer matches the Factory's profile - the profile was bumped after G3 - is
refused: vendoring a newer version under an older pin would make the pin a lie.
"""

import hashlib
import json
import os

from wgflib import paths
from wgflib.yamllite import load_file

__all__ = ["ProfileError", "vendor_profiles", "PROFILES_DIR", "PINNED"]

PROFILES_DIR = "config/platforms"
PINNED = "pinned.json"
_COMMENT = [
    "Platform profiles vendored from the Factory, at the exact version game.config.yaml pins.",
    "The .yaml files here are byte-identical copies of core/reference/platforms/<id>.yaml.",
    "Written by the Factory at scaffolding; do not hand-edit.",
]


class ProfileError(ValueError):
    """A pinned profile cannot be vendored at its pinned version. Not transient."""


def vendor_profiles(project, platforms, source_dir=None):
    """Copy each pinned profile into <project>/config/platforms/ and update pinned.json.
    Returns the project-relative paths written or already correct."""
    source_dir = source_dir or paths.PLATFORMS
    target = os.path.join(project, *PROFILES_DIR.split("/"))
    os.makedirs(target, exist_ok=True)
    pinned_path = os.path.join(target, PINNED)
    try:
        with open(pinned_path, encoding="utf-8") as handle:
            pinned = json.load(handle)
    except (OSError, ValueError):
        pinned = {"_comment": _COMMENT, "source_repo": "web-game-factory",
                  "source_path": "core/reference/platforms", "profiles": []}
    entries = {e.get("id"): e for e in pinned.get("profiles") or [] if isinstance(e, dict)}

    touched = []
    for platform in platforms:
        platform_id, _, version = platform["profile"].partition("@")
        source = os.path.join(source_dir, f"{platform_id}.yaml")
        if not os.path.isfile(source):
            raise ProfileError(f"no Factory profile for {platform_id!r} to vendor")
        current = str((load_file(source) or {}).get("version"))
        if current != version:
            raise ProfileError(f"the plan pins {platform['profile']} but the Factory's profile "
                               f"is {platform_id}@{current}; re-plan against the current "
                               "profile rather than vendor one under the wrong pin")
        with open(source, "rb") as handle:
            raw = handle.read()
        destination = os.path.join(target, f"{platform_id}.yaml")
        existing = None
        if os.path.isfile(destination):
            with open(destination, "rb") as handle:
                existing = handle.read()
        if existing != raw:
            with open(destination, "wb") as handle:
                handle.write(raw)
        entries[platform_id] = {"id": platform_id, "version": version,
                                "file": f"{platform_id}.yaml",
                                "content_hash": "sha256:" + hashlib.sha256(raw).hexdigest()}
        touched.append(f"{PROFILES_DIR}/{platform_id}.yaml")

    pinned["profiles"] = [entries[key] for key in sorted(entries)]
    text = json.dumps(pinned, indent=2, ensure_ascii=False) + "\n"
    try:
        with open(pinned_path, encoding="utf-8") as handle:
            unchanged = handle.read() == text
    except OSError:
        unchanged = False
    if not unchanged:
        with open(pinned_path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
    touched.append(f"{PROFILES_DIR}/{PINNED}")
    return touched

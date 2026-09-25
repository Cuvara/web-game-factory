"""Vendor the pinned platform profiles into the project's config/platforms/.

A game repository does not contain the Factory, and release validation judges a build by
the profile version its plan pinned (web-game-template config/platforms/pinned.json and
scripts/verify/evaluate-assertions.mjs read config/platforms/<id>.yaml). The files are
byte-identical copies of core/reference/platforms/<id>.yaml, so a drift is a plain diff, and
pinned.json lists each with the sha256 of its bytes.

A profile's identity is id + version + content hash, never id@version alone: two different
documents can both declare `y8@1.0.0` (the template ships copies of its own), and a version
string cannot tell them apart. A vendored copy therefore counts as already pinned only when
its bytes, its pinned.json content_hash and the Factory's profile all agree. Anything else -
a same-version copy with other content, an entry with no hash (a file this module did not
write, so unverified) - is re-vendored from the Factory and re-recorded. verify_pins() is
the read-side check: it compares hashes, not version strings.

A pin that no longer matches the Factory's profile - the profile was bumped after G3 - is
refused: vendoring a newer version under an older pin would make the pin a lie.
"""

import hashlib
import json
import os

from wgflib import paths
from wgflib.yamllite import YamlError, load_file

__all__ = ["ProfileError", "vendor_profiles", "verify_pins", "pin_identity",
           "profile_digest", "PROFILES_DIR", "PINNED"]

PROFILES_DIR = "config/platforms"
PINNED = "pinned.json"
_COMMENT = [
    "Platform profiles vendored from the Factory, at the exact version game.config.yaml pins.",
    "The .yaml files here are byte-identical copies of core/reference/platforms/<id>.yaml.",
    "Written by the Factory at scaffolding; do not hand-edit.",
]


class ProfileError(ValueError):
    """A pinned profile cannot be vendored at its pinned version. Not transient."""


def profile_digest(raw):
    """The content_hash pinned.json records for a profile: sha256 of its exact bytes."""
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _read_bytes(path):
    try:
        with open(path, "rb") as handle:
            return handle.read()
    except OSError:
        return None


def _load_pinned(pinned_path):
    """pinned.json as a dict, or None when absent, unreadable or not an object. Any shape a
    1.1.0 or template-shipped file can have is tolerated; a malformed one reads as absent."""
    try:
        with open(pinned_path, encoding="utf-8") as handle:
            pinned = json.load(handle)
    except (OSError, ValueError):
        return None
    return pinned if isinstance(pinned, dict) else None


def _entries(pinned):
    profiles = pinned.get("profiles")
    if not isinstance(profiles, list):
        return {}
    return {e["id"]: e for e in profiles if isinstance(e, dict) and e.get("id")}


def _already_pinned(entry, version, expected, existing):
    """The entry, the vendored bytes and the Factory's profile are one identity: same id
    (the key), same version, same content hash. An entry without a hash is unverified."""
    return (isinstance(entry, dict)
            and str(entry.get("version")) == version
            and entry.get("content_hash") == expected
            and existing is not None and profile_digest(existing) == expected)


def vendor_profiles(project, platforms, source_dir=None):
    """Copy each pinned profile into <project>/config/platforms/ and update pinned.json.
    Returns the project-relative paths written or already correct."""
    source_dir = source_dir or paths.PLATFORMS
    target = os.path.join(project, *PROFILES_DIR.split("/"))
    os.makedirs(target, exist_ok=True)
    pinned_path = os.path.join(target, PINNED)
    pinned = _load_pinned(pinned_path)
    if pinned is None:
        pinned = {"_comment": _COMMENT, "source_repo": "web-game-factory",
                  "source_path": "core/reference/platforms", "profiles": []}
    entries = _entries(pinned)

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
        expected = profile_digest(raw)
        destination = os.path.join(target, f"{platform_id}.yaml")
        existing = _read_bytes(destination) if os.path.isfile(destination) else None
        if not _already_pinned(entries.get(platform_id), version, expected, existing) \
                and existing != raw:
            # Same id@version is not the same profile: a copy with other bytes (the
            # template's own, a hand edit) is replaced by the Factory's, whatever the entry
            # beside it claims, and recorded below by the hash of what was written.
            with open(destination, "wb") as handle:
                handle.write(raw)
        entries[platform_id] = {"id": platform_id, "version": version,
                                "file": f"{platform_id}.yaml", "content_hash": expected}
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


def _version_of(path):
    try:
        return str((load_file(path) or {}).get("version"))
    except (OSError, YamlError, ValueError):
        return None


def verify_pins(project, platforms=None, source_dir=None):
    """Check the project's vendored profiles by identity - version AND content hash - against
    pinned.json and against the Factory's profile at that version. Returns a list of
    problems; empty means every checked pin is verified.

    `platforms` (game.config.yaml's pinned `{id, profile, role}` entries) limits the check to
    those pins and requires each to be listed; without it every pinned.json entry is
    checked. An entry with no content_hash is reported as unverified, never trusted.
    """
    source_dir = source_dir or paths.PLATFORMS
    target = os.path.join(project, *PROFILES_DIR.split("/"))
    pinned = _load_pinned(os.path.join(target, PINNED))
    if pinned is None:
        return [f"{PROFILES_DIR}/{PINNED} is missing or unreadable"]
    entries = _entries(pinned)
    if platforms is None:
        wanted = [(pid, str(entry.get("version"))) for pid, entry in sorted(entries.items())]
    else:
        wanted = [str(p.get("profile") or p.get("id")).partition("@")[::2]
                  for p in platforms if isinstance(p, dict)]

    problems = []
    for platform_id, version in wanted:
        pin = f"{platform_id}@{version}"
        entry = entries.get(platform_id)
        if entry is None:
            problems.append(f"{pin} is not listed in {PROFILES_DIR}/{PINNED}")
            continue
        if str(entry.get("version")) != version:
            problems.append(f"{PROFILES_DIR}/{PINNED} pins {platform_id}@"
                            f"{entry.get('version')}, not {pin}")
            continue
        recorded = entry.get("content_hash")
        if not isinstance(recorded, str) or not recorded.startswith("sha256:"):
            problems.append(f"{pin} has no content_hash in {PROFILES_DIR}/{PINNED}: "
                            "unverified")
            continue
        name = entry.get("file") if isinstance(entry.get("file"), str) \
            else f"{platform_id}.yaml"
        vendored = os.path.join(target, name)
        raw = _read_bytes(vendored)
        if raw is None:
            problems.append(f"{PROFILES_DIR}/{name} is missing")
            continue
        if profile_digest(raw) != recorded:
            problems.append(f"{PROFILES_DIR}/{name} is {profile_digest(raw)}, but "
                            f"{PROFILES_DIR}/{PINNED} pins {pin} as {recorded}")
            continue
        declared = _version_of(vendored)
        if declared != version:
            problems.append(f"{PROFILES_DIR}/{name} declares version {declared}, not {version}")
            continue
        factory_path = os.path.join(source_dir, f"{platform_id}.yaml")
        factory = _read_bytes(factory_path)
        if factory is None:
            problems.append(f"the Factory has no profile for {platform_id!r}")
        elif profile_digest(factory) != recorded and _version_of(factory_path) == version:
            # An older pin against a bumped Factory profile is legitimate; the same version
            # with other bytes is two documents answering to one name.
            problems.append(f"{pin} is pinned as {recorded}, but the Factory's {pin} is "
                            f"{profile_digest(factory)}: two documents under one version")
    return problems


def pin_identity(project, platform, source_dir=None):
    """(problems, content_hash or None, vendored) for one game.config.yaml platform entry:
    what every reader of a game's pinned profile - verify, sdk - checks before trusting it.

    A game that vendors the profile (the file is in config/platforms/, or pinned.json lists
    the id - what init writes for every pinned platform) is held to verify_pins: version AND
    content hash, against pinned.json and the Factory's profile. A game that vendors nothing
    for it is judged by the Factory's own profile, whose hash is returned; it has no copy to
    be tampered with, and the reader still compares the Factory profile's version to the
    pin itself."""
    source_dir = source_dir or paths.PLATFORMS
    platform_id = str(platform.get("id") or str(platform.get("profile") or "").partition("@")[0])
    target = os.path.join(project, *PROFILES_DIR.split("/"))
    pinned = _load_pinned(os.path.join(target, PINNED))
    listed = platform_id in _entries(pinned) if pinned is not None else False
    vendored_path = os.path.join(target, f"{platform_id}.yaml")
    if not listed and not os.path.isfile(vendored_path):
        raw = _read_bytes(os.path.join(source_dir, f"{platform_id}.yaml"))
        return [], (profile_digest(raw) if raw is not None else None), False
    problems = verify_pins(project, [platform], source_dir)
    entry = _entries(pinned or {}).get(platform_id) or {}
    recorded = entry.get("content_hash") if not problems else None
    return problems, recorded, True

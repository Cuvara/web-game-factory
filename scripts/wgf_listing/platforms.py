"""What each targeted platform's listing requires, read from its profile.

A platform profile (core/reference/platforms/<id>.yaml) may carry a `store_listing` block
(shared/platform-profile.schema.json `storeListing`). `requirements(profile, reference)`
turns the block - or its absence - into one flat, explicit list of requirements the
renderer makes and the validator checks:

    {"id", "kind": text | list | image | screenshots | video | locale | age_rating,
     "required": True | False | None, ...limits...,
     "known": bool}                      False: the profile states no limit for it

Nothing is guessed: a null in the profile stays None here and is reported UNKNOWN by
validation. The coarse `metadata_requirements` fields are the fallback for a profile with no
block (screenshots_min, icon_required, descriptions_locales, age_rating_required).
"""

import hashlib
import json
import os

from wgflib import paths
from wgflib.yamllite import YamlError, load_file

__all__ = ["load_profile", "requirements", "spec_status", "targets", "ProfileError", "block_hash"]

TEXT_FIELDS = ("title", "subtitle", "short_description", "long_description", "promo", "how_to_play")
# A portal field the listing fills from another of its texts: the portal's "how to play" is
# the listing's controls text (what the publish campaign enters there too).
TEXT_SOURCE = {"how_to_play": "controls"}
LIST_FIELDS = ("tags", "categories")


class ProfileError(ValueError):
    pass


def load_profile(platform_id, directory=None):
    """The platform profile, or None when none exists."""
    path = os.path.join(directory or paths.PLATFORMS, f"{platform_id}.yaml")
    if not os.path.isfile(path):
        return None
    try:
        return load_file(path) or {}
    except (OSError, YamlError, ValueError) as exc:
        raise ProfileError(f"{path}: {exc}")


def block_hash(profile):
    """sha256 of the profile's store_listing block, canonical JSON - what a listing was
    rendered and validated against, since the profile's own version does not move for it."""
    block = (profile or {}).get("store_listing")
    if block is None:
        return None
    text = json.dumps(block, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def spec_status(profile):
    block = (profile or {}).get("store_listing")
    if not isinstance(block, dict):
        return "absent"
    return "verified" if block.get("status") == "verified" else "unverified"


def targets(scaffold, settings_platforms=None, verified=None):
    """[(platform id, role, profile version)] the listing is rendered for: the step's own
    list when configured, else the platforms the verified build targets (the
    verification-report's platform_readiness: what the release will package), else the
    scaffold-record's game.config platforms. The verified ones come first because a title
    retargeted after scaffolding (docs/platform-targets-2026-10.md) has a scaffold-record
    that still names its first targets."""
    out = []
    by_id = {}
    for entry in verified or ():
        if not isinstance(entry, dict) or not entry.get("platform_id"):
            continue
        version = str(entry.get("profile") or "").partition("@")[2] or None
        by_id[entry["platform_id"]] = (entry.get("role") or "required", version)
    entries = [] if by_id else ((scaffold or {}).get("game_config") or {}).get("platforms") or []
    for entry in entries:
        if not isinstance(entry, dict) or not entry.get("id"):
            continue
        version = str(entry.get("profile") or "").partition("@")[2] or None
        by_id[entry["id"]] = (entry.get("role") or "required", version)
    ids = settings_platforms if settings_platforms is not None else list(by_id)
    for pid in ids:
        role, version = by_id.get(pid, ("required", None))
        out.append((pid, role, version))
    return out


def locales_for(profile):
    """The locales the listing texts are required in: store_listing.locales, else
    metadata_requirements.descriptions_locales, else requirements.locales_required."""
    block = (profile or {}).get("store_listing") or {}
    if isinstance(block.get("locales"), list):
        return [str(l).lower() for l in block["locales"]]
    meta = (profile or {}).get("metadata_requirements") or {}
    if isinstance(meta.get("descriptions_locales"), list):
        return [str(l).lower() for l in meta["descriptions_locales"]]
    required = ((profile or {}).get("requirements") or {}).get("locales_required") or []
    return [str(l).lower() for l in required]


def _text_limit(name, block, canonical):
    spec = block.get(name) if isinstance(block.get(name), dict) else {}
    return {"id": f"text:{name}", "kind": "text", "field": name,
            "text_field": TEXT_SOURCE.get(name, name),
            "required": spec.get("required", name in ("title", "short_description") or None),
            "max_chars": spec.get("max_chars"), "min_chars": spec.get("min_chars"),
            "known": "max_chars" in spec and spec["max_chars"] is not None,
            "canonical_max": (canonical.get(name) or {}).get("max_chars")}


def _list_limit(name, block):
    spec = block.get(name) if isinstance(block.get(name), dict) else {}
    return {"id": f"list:{name}", "kind": "list", "field": name,
            "required": spec.get("required", False),
            "min": spec.get("min"), "max": spec.get("max"), "allowed": spec.get("allowed"),
            "max_chars": spec.get("max_chars"),
            "known": any(spec.get(k) is not None for k in ("min", "max", "allowed"))}


def _image(spec, default_id, default_required, source, label):
    spec = spec if isinstance(spec, dict) else {}
    sizes = spec.get("sizes")
    return {"id": f"image:{spec.get('id') or default_id}", "kind": "image",
            "image_id": spec.get("id") or default_id, "label": spec.get("label") or label,
            "required": spec.get("required", default_required),
            "sizes": [(int(s["width"]), int(s["height"])) for s in sizes
                      if isinstance(s, dict)] if isinstance(sizes, list) else None,
            "aspect": spec.get("aspect"), "formats": spec.get("formats"),
            "max_kb": spec.get("max_kb"), "transparent": spec.get("transparent"),
            "source": spec.get("source") or source,
            "known": isinstance(sizes, list) and bool(sizes)}


def requirements(profile, reference):
    """The requirement list for one platform (see the module docstring)."""
    profile = profile or {}
    block = profile.get("store_listing") if isinstance(profile.get("store_listing"), dict) else None
    meta = profile.get("metadata_requirements") or {}
    canonical = (reference or {}).get("copy") or {}
    out = []
    if block is None:
        # Only the coarse fields: everything else is unknown.
        out.append({"id": "text:title", "kind": "text", "field": "title", "required": True,
                    "max_chars": None, "min_chars": None, "known": False,
                    "canonical_max": (canonical.get("title") or {}).get("max_chars")})
        out.append({"id": "text:short_description", "kind": "text", "field": "short_description",
                    "required": True, "max_chars": None, "min_chars": None, "known": False,
                    "canonical_max": (canonical.get("short_description") or {}).get("max_chars")})
        out.append(_image({}, "icon", meta.get("icon_required"), "icon", "Icon"))
        out.append({"id": "screenshots", "kind": "screenshots",
                    "required": (meta.get("screenshots_min") or 0) > 0 if "screenshots_min" in meta else None,
                    "min": meta.get("screenshots_min"), "max": None, "sizes": None, "aspect": None,
                    "formats": None, "max_kb": None, "orientation": None,
                    "known": "screenshots_min" in meta})
        out.append({"id": "video", "kind": "video", "required": None, "formats": None,
                    "min_seconds": None, "max_seconds": None, "max_mb": None,
                    "min_width": None, "min_height": None, "aspect": None, "orientation": None,
                    "known": False})
        out.append({"id": "age_rating", "kind": "age_rating",
                    "required": meta.get("age_rating_required"), "system": None,
                    "known": "age_rating_required" in meta})
    else:
        for name in TEXT_FIELDS:
            if name in block or name in ("title", "short_description", "long_description"):
                out.append(_text_limit(name, block, canonical))
        for name in LIST_FIELDS:
            if name in block:
                out.append(_list_limit(name, block))
        if "icon" in block or meta.get("icon_required") is not None:
            out.append(_image(block.get("icon"), "icon", meta.get("icon_required"), "icon", "Icon"))
        for index, cover in enumerate(block.get("covers") or []):
            out.append(_image(cover, f"cover-{index + 1}", False, "thumbnail", "Cover"))
        shots = block.get("screenshots") if isinstance(block.get("screenshots"), dict) else {}
        sizes = shots.get("sizes")
        out.append({"id": "screenshots", "kind": "screenshots",
                    "required": shots.get("required", (meta.get("screenshots_min") or 0) > 0
                                          if "screenshots_min" in meta else None),
                    "min": shots.get("min", meta.get("screenshots_min")), "max": shots.get("max"),
                    "sizes": [(int(s["width"]), int(s["height"])) for s in sizes
                              if isinstance(s, dict)] if isinstance(sizes, list) else None,
                    "aspect": shots.get("aspect"), "formats": shots.get("formats"),
                    "max_kb": shots.get("max_kb"), "orientation": shots.get("orientation"),
                    "aspects": shots.get("aspects"), "min_long_side": shots.get("min_long_side"),
                    "max_long_side": shots.get("max_long_side"),
                    "transparent": shots.get("transparent"),
                    "known": shots.get("min") is not None or "screenshots_min" in meta})
        video = block.get("video") if isinstance(block.get("video"), dict) else {}
        out.append({"id": "video", "kind": "video", "required": video.get("required"),
                    "formats": video.get("formats"), "min_seconds": video.get("min_seconds"),
                    "max_seconds": video.get("max_seconds"), "max_mb": video.get("max_mb"),
                    "min_width": video.get("min_width"), "min_height": video.get("min_height"),
                    "aspect": video.get("aspect"), "orientation": video.get("orientation"),
                    "known": "required" in video})
        rating = block.get("age_rating") if isinstance(block.get("age_rating"), dict) else {}
        out.append({"id": "age_rating", "kind": "age_rating",
                    "required": rating.get("required", meta.get("age_rating_required")),
                    "system": rating.get("system"),
                    "known": "required" in rating or "age_rating_required" in meta})
    for locale in locales_for(profile):
        out.append({"id": f"locale:{locale}", "kind": "locale", "locale": locale,
                    "required": True, "known": True})
    naming = (block or {}).get("naming") if block else None
    if isinstance(naming, dict) and naming.get("files"):
        out.append({"id": "naming", "kind": "naming", "pattern": naming["files"],
                    "required": True, "known": True})
    return out

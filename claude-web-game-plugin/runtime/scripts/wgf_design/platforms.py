"""Platform profiles as binding constraints on a design.

The strategy pins each platform by id and profile version. Design reads those profiles as
BINDING (core/reference/platforms/README.md): required locales, the tightest interstitial
interval, supported placements, the loading API, bundle size. Everything read here is
recorded in `platform_constraints_applied`, because an empty list on a title with required
platforms means the profiles were not read.

Capabilities are named generically (`ad-rewarded`, `cloud-save`); game code reaches them
through the template's platform abstraction, never a portal SDK.
"""

import os

from wgflib import paths
from wgflib.yamllite import load_file

__all__ = ["PlatformError", "Platform", "load_platforms", "tightest_interval",
           "supported_placements", "constraints_applied", "sdk_touchpoints"]


class PlatformError(Exception):
    """A pinned profile is missing, or is not the version the strategy pinned."""


class Platform:
    __slots__ = ("id", "role", "version", "profile")

    def __init__(self, platform_id, role, version, profile):
        self.id = platform_id
        self.role = role
        self.version = version
        self.profile = profile

    @property
    def required(self):
        return self.role == "required"

    def get(self, *keys, default=None):
        node = self.profile
        for key in keys:
            if not isinstance(node, dict) or key not in node:
                return default
            node = node[key]
        return default if node is None else node

    @property
    def ads(self):
        return list(self.get("capabilities", "ads", default=[]))

    @property
    def placements(self):
        """Ad kinds the platform offers, plus `iap` when it supports purchases."""
        kinds = self.ads
        if self.get("capabilities", "iap", default=False):
            kinds.append("iap")
        return kinds


def load_platforms(strategy, directory=None):
    """Resolve the strategy's platform_set against the profiles, enforcing the pinned version."""
    directory = directory or paths.PLATFORMS
    resolved = []
    for entry in strategy.get("platform_set") or []:
        path = os.path.join(directory, f"{entry['id']}.yaml")
        if not os.path.exists(path):
            raise PlatformError(f"no platform profile for {entry['id']!r} ({paths.display(path)})")
        profile = load_file(path)
        version = str(profile.get("version"))
        pinned = str(entry.get("profile_version"))
        if version != pinned:
            raise PlatformError(
                f"strategy pins {entry['id']}@{pinned} but the profile is {version}; "
                "re-pin in a superseding strategy rather than design against unpinned rules"
            )
        resolved.append(Platform(entry["id"], entry.get("role", "optional"), version, profile))
    return resolved


def tightest_interval(platforms):
    """The longest interstitial interval any targeted platform enforces - one build serves all."""
    values = [p.get("ads", "interstitial_min_interval_s") for p in platforms]
    values = [v for v in values if isinstance(v, (int, float))]
    return max(values) if values else None


def supported_placements(platforms):
    """Placements every REQUIRED platform supports. Optional platforms do not constrain."""
    required = [p for p in platforms if p.required] or list(platforms)
    if not required:
        return ["rewarded", "interstitial", "banner", "iap"]
    common = set(required[0].placements)
    for platform in required[1:]:
        common &= set(platform.placements)
    return sorted(common)


def constraints_applied(platforms, design):
    """What each profile demanded of the design, and how the design met it."""
    spec = design.get("build_spec") or {}
    locales = (design.get("scope") or {}).get("locales") or []
    responsive = spec.get("responsive") or {}
    touchpoints = spec.get("monetization_touchpoints") or []
    kinds = sorted({t["kind"] for t in touchpoints})
    interstitial = next((t for t in touchpoints if t["kind"] == "interstitial"), None)
    interval = tightest_interval(platforms)
    out = []

    def add(platform, requirement, how):
        out.append({"platform_id": platform.id, "requirement": requirement, "how_addressed": how})

    for p in platforms:
        required_locales = p.get("requirements", "locales_required", default=[])
        if required_locales:
            missing = [l for l in required_locales if l not in locales]
            add(p, f"Locales required: {', '.join(required_locales)}",
                "In scope.locales; every UI string goes through the template's localization table."
                if not missing else f"NOT addressed: {', '.join(missing)} missing from scope.locales")

        if p.get("requirements", "loading_api") == "required":
            add(p, "Loading progress must be reported through the platform SDK",
                "The loading screen is driven by the loading-progress and loading-complete touchpoints, not a timer.")

        platform_interval = p.get("ads", "interstitial_min_interval_s")
        if interstitial and isinstance(platform_interval, (int, float)):
            add(p, f"Interstitial minimum interval {platform_interval}s",
                f"Interstitial cooldown is {interstitial.get('cooldown_s')}s, the tightest across the "
                f"platform set ({interval}s), shown only between runs.")

        offered = p.placements
        unsupported = [k for k in kinds if k not in offered]
        if kinds:
            add(p, f"Supported placements: {', '.join(offered) or 'none'}",
                "All designed placements are supported." if not unsupported else
                f"{', '.join(unsupported)} unavailable here; the touchpoint's when_unavailable path is used"
                + ("" if not p.required else " - and this platform is required, so consistency will fail"))

        bundle = p.get("requirements", "max_bundle_mb")
        if isinstance(bundle, (int, float)):
            add(p, f"Bundle at most {bundle} MB",
                "Asset list favours procedural and vector sources; audio is compressed and streamed after first play.")

        orientations = p.get("requirements", "orientation", default=[])
        if orientations and responsive.get("orientation"):
            orientation = responsive["orientation"]
            add(p, f"Orientations accepted: {', '.join(orientations)}",
                f"Designed for {orientation}; the other orientation shows the responsive layout described in build_spec.responsive.")

        if p.get("ads", "notes") and kinds and any(k != "iap" for k in kinds):
            add(p, "Gameplay and audio must pause around ad playback",
                "gameplay-stop and pause-audio fire before every ad; resume-audio and gameplay-start after it.")

        if p.get("requirements", "no_external_links"):
            add(p, "No external links", "No screen links outside the game.")

        if p.get("requirements", "external_requests") == "restricted":
            add(p, "External network requests restricted",
                "All assets ship in the bundle; no runtime fetch beyond the platform SDK.")

        if p.get("capabilities", "cloud_saves") and any(
                t.get("capability") == "cloud-save" for t in spec.get("sdk_touchpoints") or []):
            add(p, "Cloud saves available", "Personal best and progress persist through cloud-save; local storage is the fallback.")
    return out


def sdk_touchpoints(platforms, design_spec, states):
    """The platform touchpoints every design needs, derived from the profiles and the design.

    `states` maps role names (boot, loading, play, pause, fail) to this design's state ids.
    """
    ids = [p.id for p in platforms]
    loading_required = [p.id for p in platforms if p.get("requirements", "loading_api") == "required"]
    saves = [p.id for p in platforms if p.get("capabilities", "cloud_saves")]
    ad_platforms = [p.id for p in platforms if p.ads]
    touchpoints = [
        {"id": "sdk-init", "capability": "init", "tier": "mvp", "state": states["boot"],
         "when": "First thing at boot, before any asset load; the game proceeds on timeout (3 s) with ads disabled.",
         "platforms": ids, "required": True, "fallback": "No-op adapter on platforms without an SDK."},
        {"id": "sdk-language", "capability": "language", "tier": "mvp", "state": states["boot"],
         "when": "After init; picks the UI locale from the platform, else the browser, else the first locale in scope.",
         "platforms": ids, "required": False, "fallback": "Browser language."},
        {"id": "sdk-loading-progress", "capability": "loading-progress", "tier": "mvp", "state": states["loading"],
         "when": "On every asset-loader progress event.", "platforms": loading_required or ids,
         "required": bool(loading_required), "fallback": "Progress bar only."},
        {"id": "sdk-loading-complete", "capability": "loading-complete", "tier": "mvp", "state": states["loading"],
         "when": "When the first playable screen is interactive - not when every asset is loaded.",
         "platforms": loading_required or ids, "required": bool(loading_required), "fallback": "None needed."},
        {"id": "sdk-gameplay-start", "capability": "gameplay-start", "tier": "mvp", "state": states["play"],
         "when": "On entering play, and on resuming after pause or an ad.", "platforms": ids,
         "required": bool(ad_platforms), "fallback": "No-op."},
        {"id": "sdk-gameplay-stop", "capability": "gameplay-stop", "tier": "mvp", "state": states["play"],
         "when": "On leaving play: pause, fail, tab hidden, and before any ad.", "platforms": ids,
         "required": bool(ad_platforms), "fallback": "No-op."},
    ]
    if ad_platforms:
        touchpoints += [
            {"id": "sdk-pause-audio", "capability": "pause-audio", "tier": "mvp", "state": states["pause"],
             "when": "Before any ad shows and on tab hidden.", "platforms": ad_platforms, "required": True,
             "fallback": "Mute the master bus."},
            {"id": "sdk-resume-audio", "capability": "resume-audio", "tier": "mvp", "state": states["pause"],
             "when": "After an ad closes, whatever its outcome, and on tab visible.", "platforms": ad_platforms,
             "required": True, "fallback": "Unmute the master bus."},
        ]
    kinds = {t["kind"]: t for t in design_spec.get("monetization_touchpoints") or []}
    ad_capability = {"rewarded": "ad-rewarded", "interstitial": "ad-interstitial", "banner": "ad-banner", "iap": "purchase"}
    for kind, touchpoint in kinds.items():
        touchpoints.append({
            "id": f"sdk-{ad_capability[kind]}", "capability": ad_capability[kind], "tier": touchpoint["tier"],
            "state": touchpoint["state"], "when": touchpoint["trigger"],
            "platforms": touchpoint.get("platforms") or ids, "required": False,
            "fallback": touchpoint["when_unavailable"],
        })
    if saves:
        touchpoints += [
            {"id": "sdk-cloud-load", "capability": "cloud-load", "tier": "mvp", "state": states["boot"],
             "when": "After init, before the title screen shows the best score.", "platforms": saves,
             "required": False, "fallback": "Local storage."},
            {"id": "sdk-cloud-save", "capability": "cloud-save", "tier": "mvp", "state": states["fail"],
             "when": "When a run or level ends with a new best or new unlock; never mid-play.", "platforms": saves,
             "required": False, "fallback": "Local storage."},
        ]
    return touchpoints

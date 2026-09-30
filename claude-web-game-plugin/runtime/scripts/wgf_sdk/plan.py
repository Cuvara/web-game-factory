"""What each targeted platform requires of a build: the integration plan.

The plan is derived, never authored: the game repository's game.config.yaml says which
platforms the build targets (pinned `<id>@<version>`) and which ad kinds the title committed
to; the pinned profile in core/reference/platforms/ says what that portal offers and
demands. A feature the build must integrate is `required`; anything else is `not-required`
in the sdk-report, even when the conformance suite exercised it.

Feature names are the conformance suite's (web-game-template tests/sdk/conformance.test.ts).
"""

import os

from wgflib import paths
from wgflib.yamllite import load_file

from wgf_init.profiles import pin_identity

__all__ = ["PlanError", "PlatformPlan", "load_game_config", "integration_plan", "FEATURES"]

# The conformance suite's feature vocabulary, in report order.
FEATURES = (
    "not-configured",
    "init",
    "sdk-unavailable",
    "init-failure",
    "loading",
    "gameplay-lifecycle",
    "pause-resume",
    "interstitial",
    "rewarded",
    "storage",
    "game-binding",
)

ALWAYS = {"not-configured", "init", "loading", "gameplay-lifecycle", "storage", "game-binding"}


class PlanError(Exception):
    """The build's platform configuration is missing, malformed or unpinned. Not retryable."""


class PlatformPlan:
    __slots__ = ("id", "version", "role", "profile", "required", "why", "conditional", "unservable")

    def __init__(self, platform_id, version, role, profile, required, why, conditional, unservable):
        self.id = platform_id
        self.version = version
        self.role = role
        self.profile = profile
        self.required = required        # set of feature names the build must integrate
        self.why = why                  # feature -> reason it is required
        # Required only if the platform has a portal SDK at all; the conformance suite, which
        # knows whether an adapter loads one, has the last word (GameVui publishes none).
        self.conditional = conditional
        # Committed to by the title but not offered by the platform: can never be working.
        self.unservable = unservable


def load_game_config(game_repo):
    path = os.path.join(game_repo, "game.config.yaml")
    if not os.path.exists(path):
        raise PlanError(f"platform not configured: {path} does not exist")
    config = load_file(path) or {}
    platforms = config.get("platforms")
    if not isinstance(platforms, list) or not platforms:
        raise PlanError("platform not configured: game.config.yaml declares no platforms")
    return config


def _profile(platform_id, version, directory):
    path = os.path.join(directory, f"{platform_id}.yaml")
    if not os.path.exists(path):
        raise PlanError(f"no platform profile for {platform_id!r} in core/reference/platforms/")
    profile = load_file(path)
    if str(profile.get("version")) != version:
        raise PlanError(
            f"game.config.yaml pins {platform_id}@{version} but the profile is "
            f"{profile.get('version')}; re-pin through the tech plan rather than build against "
            "unpinned rules")
    return profile


def _vendored_identity(game_repo, entry, directory):
    """The game's vendored copy of a pinned profile must be the Factory's, by content hash
    (wgf_init.profiles.pin_identity), not merely declare the pinned version: two documents
    can both say `<id>@1.0.0`. Returns the content hash the plan was built against."""
    problems, content_hash, _vendored = pin_identity(game_repo, entry, directory)
    if problems:
        raise PlanError(
            f"the game's pinned profile {entry.get('profile')} does not verify by content hash: "
            + "; ".join(problems) + ". Re-pin through the tech plan (init re-vendors the "
            "Factory's profile) rather than build against a profile nobody pinned")
    return content_hash


def integration_plan(config, profiles_dir=None, game_repo=None):
    """One PlatformPlan per pinned platform. With `game_repo`, each platform's vendored
    profile is verified by content hash first (a PlanError names what does not verify)."""
    directory = profiles_dir or paths.PLATFORMS
    ad_kinds = set((config.get("monetization") or {}).get("ad_kinds") or [])
    plans = []
    for entry in config["platforms"]:
        if not isinstance(entry, dict) or not {"id", "profile", "role"} <= set(entry):
            raise PlanError(f"platforms entry {entry!r} is not a pinned {{id, profile, role}} object")
        platform_id, _, version = str(entry["profile"]).partition("@")
        if platform_id != entry["id"] or not version:
            raise PlanError(f"profile pin {entry['profile']!r} does not match platform {entry['id']!r}")
        profile = _profile(platform_id, version, directory)
        if game_repo is not None:
            _vendored_identity(game_repo, entry, directory)
        capabilities = profile.get("capabilities") or {}
        offered = set(capabilities.get("ads") or [])
        why = {feature: "every build" for feature in ALWAYS}
        if profile.get("requirements", {}).get("loading_api") == "required":
            why["loading"] = "profile requirements.loading_api: required"
        if offered:
            # A portal that serves ads loads a script that can be blocked or fail, and takes
            # the foreground while an ad plays.
            why["sdk-unavailable"] = "portal SDK script can be blocked (ad blockers)"
            why["init-failure"] = "portal SDK init can fail"
            why["pause-resume"] = "portal takes the foreground for ads"
        unservable = set()
        for kind in ("interstitial", "rewarded"):
            if kind in ad_kinds:
                why[kind] = f"game.config monetization.ad_kinds includes {kind}"
                if kind not in offered:
                    unservable.add(kind)
        if capabilities.get("cloud_saves"):
            why["storage"] = "profile capabilities.cloud_saves: progress persists through the portal"
        conditional = {"sdk-unavailable", "init-failure", "pause-resume"} & set(why)
        plans.append(PlatformPlan(platform_id, version, entry["role"], profile, set(why), why,
                                  conditional, unservable))
    return plans

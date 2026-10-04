"""The retarget of an existing title: the platforms G3 approved, written into the checkout.

init writes game.config.yaml's platforms, and vendors their profiles, once - before
develop. A title whose platforms a person changes later (factory.strategy.platforms, then a
new strategy, G2, design, tech plan and G3) would otherwise need init again, and init's
commit moves HEAD below develop's: every later gate pins the developed commit, so the whole
develop round would run again for a change that touches no game code.

The sdk step is the one step after develop allowed to commit (its keyed commits are part of
the commit lineage rule, wgf_verification/lineage.py), and it already writes what each
platform needs. So when the run's newest tech plan names platforms the checkout does not
target, the sdk step writes them - `platforms` in game.config.yaml, nothing else in it, and
the pinned profiles under config/platforms/ (wgf_init.profiles) - before it integrates, and
commits them with the integration. A tech plan that agrees with the checkout writes nothing.

Never a choice of its own: the platforms are the tech plan's, which G3 approved.
"""

import os

from wgflib import paths
from wgflib import template_contract as contract

from wgf_init.gameconfig import GameConfigError, apply_platforms, platform_entries
from wgf_init.profiles import PINNED, PROFILES_DIR, ProfileError, vendor_profiles
from wgflib.yamllite import YamlError, load, load_file

__all__ = ["SyncError", "planned_platforms", "sync", "owns"]


class SyncError(ValueError):
    """The tech plan's platforms cannot be written into the checkout. BLOCKED."""


def owns(path):
    """game.config.yaml and the vendored profiles: what a retarget writes."""
    if path == contract.GAME_CONFIG:
        return True
    head, _, name = path.rpartition("/")
    return head == PROFILES_DIR and (name == PINNED or name.endswith(".yaml"))


def planned_platforms(tech_plan):
    """The platforms the tech plan approved at G3, or None when it names none."""
    platforms = (((tech_plan or {}).get("repo_params") or {}).get("game_config") or {}) \
        .get("platforms")
    return platforms if isinstance(platforms, list) and platforms else None


def sync(repo, tech_plan, profiles_dir=None):
    """Write the tech plan's platforms into the checkout when they differ from its
    game.config.yaml. Returns [{"path", "action"}] for what was written ([] when the
    checkout already targets them), or raises SyncError."""
    wanted = planned_platforms(tech_plan)
    if wanted is None:
        return []
    path = os.path.join(repo, contract.GAME_CONFIG)
    try:
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
        current = (load(text) or {}).get("platforms")
        expected = platform_entries(wanted)
    except (OSError, YamlError, GameConfigError) as exc:
        raise SyncError(f"cannot read the platforms to retarget: {exc}")
    if current == expected:
        return []
    # Every pin is checked before anything is written: a refusal leaves the checkout as it
    # was (vendor_profiles refuses a pin whose profile moved, but only on reaching it).
    source_dir = profiles_dir or paths.PLATFORMS
    for entry in wanted:
        platform_id, _, version = str((entry or {}).get("profile") or "").partition("@")
        source = os.path.join(source_dir, f"{platform_id}.yaml")
        try:
            current_version = str((load_file(source) or {}).get("version"))
        except (OSError, YamlError, ValueError):
            current_version = None
        if current_version != version:
            raise SyncError(f"the tech plan pins {entry.get('profile')!r}, but the Factory's "
                            f"profile is {platform_id}@{current_version}: re-plan against the "
                            "current profile (tech-plan, G3); nothing was written")
    try:
        rewritten = apply_platforms(text, wanted)
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(rewritten)
        vendored = vendor_profiles(repo, wanted, profiles_dir)
    except (GameConfigError, ProfileError, OSError) as exc:
        raise SyncError(f"cannot retarget the checkout to the tech plan's platforms: {exc}")
    return [{"path": contract.GAME_CONFIG, "action": "retargeted"}] + [
        {"path": p, "action": "vendored"} for p in vendored]

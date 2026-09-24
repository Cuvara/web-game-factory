"""Portal registrations: the identifiers a portal issued for a title, into the plan.

Some portals issue a per-title Game ID that the build must carry (game.config.yaml
platforms[].game_id). It exists only once someone has registered the title on the portal, so
it is instance data, not something the Factory can derive: it lives beside the title,

    workspace/titles/<title-id>/portals.yaml
        gamedistribution: {game_id: 0123456789abcdef0123456789abcdef}
        gamemonetize: {game_id: abcd1234}

and the platform's profile says what to do with it (requirements.game_id):

    required   no registration -> the plan cannot target the platform: BLOCKED, naming the
               file to fill in. A build without it fails in the template anyway; this finds it
               before a repository exists.
    optional   written when registered; otherwise the build may take it from its environment
    none       (or absent) a registration for it is refused - the template would reject it

A registration may also choose a non-default hosting mode the profile lists
(requirements.hosting, first = default); `self-hosted` then needs the https `game_url` the
portal's wrapper frames. Values are checked against the profile's `game_id_pattern` where it
has one, and always against a conservative charset, since they are written into YAML.
"""

import os
import re

from wgflib import paths
from wgflib.yamllite import YamlError, load_file

__all__ = ["RegistrationError", "REGISTRATION_FILE", "load_registrations", "registered_entry"]

REGISTRATION_FILE = "portals.yaml"
_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
_KEYS = {"game_id", "hosting", "game_url"}


class RegistrationError(ValueError):
    """A registration is missing, malformed or not allowed. The run stops for a person."""


def registration_path(title_id, titles_dir=None):
    return os.path.join(titles_dir or paths.TITLES, title_id, REGISTRATION_FILE)


def load_registrations(title_id, titles_dir=None):
    """{platform_id: {game_id?, hosting?, game_url?}} from the title's portals.yaml."""
    path = registration_path(title_id, titles_dir)
    if not os.path.exists(path):
        return {}
    try:
        document = load_file(path) or {}
    except (OSError, YamlError) as exc:
        raise RegistrationError(f"{paths.display(path)} is unreadable: {exc}")
    if not isinstance(document, dict):
        raise RegistrationError(f"{paths.display(path)} must map platform ids to "
                                "{game_id, hosting?, game_url?}")
    for platform_id, entry in document.items():
        if not isinstance(entry, dict) or not set(entry) <= _KEYS or not all(
                isinstance(v, str) for v in entry.values()):
            raise RegistrationError(f"{paths.display(path)}: {platform_id} must be a mapping "
                                    "of game_id, hosting and game_url, all strings")
    return document


def registered_entry(platform, registrations, title_id, titles_dir=None):
    """The game.config.yaml platforms[] entry for `platform` (a selection.Platform), with
    whatever its registration carries. Raises RegistrationError."""
    entry = platform.entry()
    need = platform.requirement("game_id") or "none"
    given = registrations.get(platform.id) or {}
    where = paths.display(registration_path(title_id, titles_dir))
    game_id = given.get("game_id")

    if game_id is None:
        if need == "required":
            raise RegistrationError(
                f"{platform.id} issues a Game ID per title and a build cannot target it "
                f"without one: register {title_id} on {platform.profile.get('name') or platform.id}"
                f", then record it in {where} as `{platform.id}: {{game_id: <id>}}` and run "
                f"tech-plan again - or leave {platform.id} out in a superseding strategy")
    else:
        if need == "none":
            raise RegistrationError(f"{where}: {platform.id} takes no game_id (its profile "
                                    f"{platform.pin} declares none)")
        pattern = platform.requirement("game_id_pattern")
        if not _SAFE_ID.match(game_id) or (pattern and not re.fullmatch(pattern, game_id)):
            raise RegistrationError(f"{where}: {platform.id} game_id {game_id!r} is not a "
                                    f"{platform.id} Game ID"
                                    + (f" (profile pattern {pattern})" if pattern else ""))
        entry["game_id"] = game_id

    hosting = given.get("hosting")
    modes = platform.requirement("hosting") or []
    if hosting is not None:
        if hosting not in modes:
            raise RegistrationError(f"{where}: {platform.id} hosting {hosting!r} is not one of "
                                    f"the modes its profile lists ({', '.join(modes) or 'none'})")
        if hosting != modes[0]:
            entry["hosting"] = hosting
    game_url = given.get("game_url")
    if entry.get("hosting") == "self-hosted":
        if not game_url or not game_url.startswith("https://") or any(
                c.isspace() for c in game_url):
            raise RegistrationError(f"{where}: {platform.id} hosting self-hosted needs the "
                                    "https game_url the portal's wrapper page frames")
        entry["game_url"] = game_url
    elif game_url is not None:
        raise RegistrationError(f"{where}: {platform.id} game_url applies to hosting "
                                "self-hosted only")
    return entry

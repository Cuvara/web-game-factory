"""Create-before-build portals: the ids a portal issues on create, and the build carrying them.

A publication profile that declares `submission.identity.issued_on_create` (Y8: the Game ID
and the App ID exist only once the game is created in the Studio) says the build must carry
those ids before anything is uploaded, and `identity.build_config` says where:

    issued_on_create: [game_id, app_id]
    build_config: {game_id: "platforms[].game_id", app_id: "platforms[].app_id"}

`platforms[].<key>` is that key of the platform's entry in the game's game.config.yaml, which
verify's per-platform build carries into build/platforms/<id>/game.config.json.

    first visit      no ids in the registry: the submit step asks the adapter to create (or
                     find) the game only (`job.required_ids`); IDS_ISSUED -> the registry
                     records DRAFT_CREATED with the ids -> route `platform-ids`
    sdk              `sync` writes the registry's ids into game.config.yaml (a keyed sdk
                     commit); verify builds again, release packages again
    platform-validate  `platform_ids_present`: the build's config carries every issued id
                     the registry holds, with the registry's value - else RED, nothing uploads
    submit           refuses a package whose build lacks them (INVALID_BUILD)

Reusable: nothing here names a portal. Standard library only.
"""

import json
import os
import re

from wgflib import publication as pub
from wgflib import template_contract as contract
from wgflib.yamllite import YamlError, load

__all__ = ["issued", "build_keys", "registry_ids", "build_entry", "ids_check",
           "platform_ids_present", "sync", "IdentityError", "registry_fields"]

_KEY = re.compile(r"^platforms\[\]\.([a-z][a-z0-9_]*)$")


class IdentityError(ValueError):
    """The ids cannot be written into the checkout. Nothing was written."""


def _identity(profile):
    return (((profile or {}).get("submission") or {}).get("identity") or {})


def issued(profile):
    """The ids the portal issues on create, as the profile names them; [] for most portals."""
    return [str(name) for name in _identity(profile).get("issued_on_create") or []]


def build_keys(profile):
    """{id name: platforms[] key} for every issued id the profile says reaches the build."""
    keys = {}
    for name, where in (_identity(profile).get("build_config") or {}).items():
        match = _KEY.match(str(where or ""))
        if match and name in issued(profile):
            keys[str(name)] = match.group(1)
    return keys


def registry_fields(name):
    """Where an id the portal names `name` is kept in a registry entry: (field, sub-key)."""
    if name in ("game_id", "external_game_id"):
        return "external_game_id", None
    if name == "app_id":
        return "app_id", None
    return "other_ids", name


def registry_ids(profile, entry):
    """{id name: value} of the issued ids the registry entry holds (absent ones left out)."""
    found = {}
    for name in issued(profile):
        field, sub = registry_fields(name)
        value = (entry or {}).get(field)
        if sub is not None:
            value = (value or {}).get(sub) if isinstance(value, dict) else None
        if value not in (None, ""):
            found[name] = str(value)
    return found


def created_fields(profile, created_ids):
    """The registry fields for the ids an adapter reports the portal issued
    (`Publication.created_ids`: external_game_id/game_id, app_id, anything else)."""
    created = {str(k): str(v) for k, v in (created_ids or {}).items() if v not in (None, "")}
    fields, other = {}, {}
    for name, value in created.items():
        field, sub = registry_fields(name)
        if sub is None:
            fields[field] = value
        else:
            other[sub] = value
    if other:
        fields["other_ids"] = other
    return fields


def build_entry(checkout, verification, platform_id):
    """The platform's entry in the build's config, and where it was read: the per-platform
    build's game.config.json the verification-report records (checked against its
    config_hash), else the checkout's game.config.yaml. (entry or None, source, problem)."""
    builds = ((verification or {}).get("build_artifact") or {}).get("platforms") or []
    build = next((b for b in builds if b.get("platform_id") == platform_id), None)
    if build and build.get("config") and checkout:
        path = os.path.join(checkout, *str(build["config"]).split("/"))
        try:
            with open(path, "rb") as handle:
                data = handle.read()
        except OSError:
            return None, build["config"], f"{build['config']} is missing"
        import hashlib
        if build.get("config_hash") and \
                "sha256:" + hashlib.sha256(data).hexdigest() != build["config_hash"]:
            return None, build["config"], (f"{build['config']} is not the config the "
                                           f"verification-report recorded")
        try:
            config = json.loads(data.decode("utf-8"))
        except ValueError:
            return None, build["config"], f"{build['config']} is not JSON"
        source = build["config"]
    elif checkout:
        path = os.path.join(checkout, contract.GAME_CONFIG)
        try:
            with open(path, encoding="utf-8") as handle:
                config = load(handle.read()) or {}
        except (OSError, YamlError) as exc:
            return None, contract.GAME_CONFIG, f"{contract.GAME_CONFIG}: {exc}"
        source = contract.GAME_CONFIG
    else:
        return None, None, "no checkout to read the build's config from"
    entry = next((p for p in (config.get("platforms") or []) if isinstance(p, dict)
                  and p.get("id") == platform_id), None)
    return entry, source, None if entry else f"{source} has no platform {platform_id}"


def ids_check(profile, entry, registry_entry):
    """(missing, wrong, held): the issued ids the registry holds that the build's platform
    entry lacks, those it carries with another value, and every id the registry holds."""
    keys = build_keys(profile)
    held = registry_ids(profile, registry_entry)
    missing, wrong = [], []
    for name, value in held.items():
        key = keys.get(name)
        if key is None:
            continue
        carried = (entry or {}).get(key)
        if carried in (None, ""):
            missing.append(name)
        elif str(carried) != value:
            wrong.append(name)
    return missing, wrong, held


def platform_ids_present(platform_id, profile, registry_entry, checkout, verification):
    """The guard: GREEN when the portal issues no ids on create, or when the build carries
    every id the registry holds; GREEN, saying so, before the game exists (the submit visit
    creates it and uploads nothing); RED when the build lacks one or carries another value;
    UNKNOWN when the build's config cannot be read."""
    names = issued(profile)
    if not names:
        return pub.green("the portal issues no ids the build must carry")
    held = registry_ids(profile, registry_entry)
    if not held:
        return pub.green(f"{', '.join(names)} not issued yet: the submit visit creates or "
                         f"finds the game, records them and uploads nothing (IDS_ISSUED)")
    entry, source, problem = build_entry(checkout, verification, platform_id)
    if problem:
        return pub.unknown(f"cannot read the build's {platform_id} config: {problem}")
    missing, wrong, _ = ids_check(profile, entry, registry_entry)
    if missing or wrong:
        return pub.red(f"the build ({source}) "
                       + "; ".join(([f"lacks {', '.join(missing)}"] if missing else [])
                                   + ([f"carries another {', '.join(wrong)}"] if wrong else []))
                       + f" the portal issued: rebuild with the registry's ids (sdk)")
    return pub.green(f"the build ({source}) carries {', '.join(sorted(held))}")


def _render(indent, entry):
    from wgf_init.gameconfig import plain_scalar
    fields = ", ".join(f"{key}: {plain_scalar(value)}" for key, value in entry.items())
    return f"{indent}- {{ {fields} }}\n"


def sync(checkout, title_id, profiles, titles_dir=None):
    """Write the registry's issued ids into game.config.yaml for every platform whose
    publication profile (`profiles`: {platform id: profile}) has `identity.build_config`.
    Returns [{"path", "action"}] for what was written ([] when nothing changed), or raises
    IdentityError, writing nothing."""
    from wgf_init.gameconfig import _Document
    from . import registry as portal_registry
    path = os.path.join(checkout, contract.GAME_CONFIG)
    try:
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
        before = load(text) or {}
    except (OSError, YamlError) as exc:
        raise IdentityError(f"cannot read {contract.GAME_CONFIG}: {exc}")
    platforms = before.get("platforms") if isinstance(before, dict) else None
    if not isinstance(platforms, list) or not title_id:
        return []
    try:
        reg = portal_registry.load(title_id, titles_dir)
    except portal_registry.RegistryError as exc:
        raise IdentityError(str(exc))
    entries, changed = [], []
    for platform in platforms:
        entry = dict(platform) if isinstance(platform, dict) else platform
        profile = profiles.get(str((platform or {}).get("id"))) if isinstance(platform, dict) else None
        keys = build_keys(profile)
        if keys:
            held = registry_ids(profile, reg.get(platform.get("id")))
            for name, value in held.items():
                key = keys.get(name)
                if key and str(entry.get(key) or "") != value:
                    entry[key] = value
                    changed.append(f"{platform.get('id')}.{key}")
        entries.append(entry)
    if not changed:
        return []
    document = _Document(text)
    document.set_list("platforms", entries, _render)
    rewritten = document.text()
    try:
        after = load(rewritten) or {}
    except YamlError as exc:
        raise IdentityError(f"rewritten {contract.GAME_CONFIG} does not parse: {exc}")
    other = sorted(k for k in set(before) | set(after)
                   if k != "platforms" and before.get(k) != after.get(k))
    if other or [{k: str(v) for k, v in e.items()} for e in after.get("platforms") or []] != \
            [{k: str(v) for k, v in e.items()} for e in entries]:
        raise IdentityError(f"writing the platform ids would change "
                            f"{', '.join(other or ['platforms'])}; nothing was written")
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(rewritten)
    return [{"path": contract.GAME_CONFIG, "action": "platform-ids", "ids": changed}]

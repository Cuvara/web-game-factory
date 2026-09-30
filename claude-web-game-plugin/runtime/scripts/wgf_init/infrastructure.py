"""What a repository generated from web-game-template must already contain.

Init never writes any of this. It checks that it arrived, because the rule in
core/lifecycle/stages/scaffolding.md is that a game repository originates from the
template, and a clone missing the platform SDK or a gate pipeline is a template problem to
find now - before a coding agent "helpfully" rebuilds the missing piece inside `src/`.

`bootstrap.yml` is deliberately absent from the list: it deletes itself on its first run.
"""

import hashlib
import os
import re

from wgflib.template_contract import ENGINES, GAME_CONFIG, INFRASTRUCTURE, PLATFORM_ROLES
from wgflib.yamllite import YamlError, load_file

__all__ = ["TEMPLATE_INFRASTRUCTURE", "GAME_CONFIG", "ENGINES", "missing_infrastructure",
           "read_game_config", "InfrastructureError"]

# The list itself is the template contract's (wgflib.template_contract), shared with the
# drift test that holds it against the pinned template.
TEMPLATE_INFRASTRUCTURE = INFRASTRUCTURE

_PROFILE = re.compile(r"^[a-z][a-z0-9-]*@[0-9]+\.[0-9]+\.[0-9]+$")


class InfrastructureError(ValueError):
    """The generated project is not what the template produces."""


def missing_infrastructure(root):
    """Paths from TEMPLATE_INFRASTRUCTURE that `root` lacks, in list order."""
    missing = []
    for path, _purpose in TEMPLATE_INFRASTRUCTURE:
        full = os.path.join(root, *path.rstrip("/").split("/"))
        if path.endswith("/"):
            present = os.path.isdir(full) and bool(os.listdir(full))
        else:
            present = os.path.isfile(full)
        if not present:
            missing.append(path)
    return missing


def read_game_config(root):
    """The `game_config` block of a scaffold-record, read from the project as it is."""
    path = os.path.join(root, GAME_CONFIG)
    with open(path, "rb") as handle:
        raw = handle.read()
    try:
        document = load_file(path) or {}
    except YamlError as exc:
        raise InfrastructureError(f"{GAME_CONFIG} does not parse: {exc}")

    platforms = []
    for entry in document.get("platforms") or []:
        # Pinned objects, never bare strings: the build is judged against the profile
        # version in force when its plan was approved.
        if not (isinstance(entry, dict) and isinstance(entry.get("id"), str)
                and _PROFILE.match(str(entry.get("profile", "")))
                and str(entry.get("profile")).split("@")[0] == entry["id"]
                and entry.get("role") in PLATFORM_ROLES):
            raise InfrastructureError(f"{GAME_CONFIG} has an unpinned platform entry: {entry!r}")
        platforms.append({"id": entry["id"], "profile": entry["profile"], "role": entry["role"]})

    record = {
        "path": GAME_CONFIG,
        "platforms": platforms,
        "checksum": "sha256:" + hashlib.sha256(raw).hexdigest(),
    }
    engine = (document.get("engine") or {}).get("type")
    if engine is not None:
        if engine not in ENGINES:
            raise InfrastructureError(f"{GAME_CONFIG} engine.type is {engine!r}; the template "
                                      f"supports only {' and '.join(ENGINES)}")
        record["engine"] = {"type": engine}
    return record

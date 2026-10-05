"""One build per target platform, so each platform's package boots its own adapter.

On the pinned template contract (1) `pnpm build` makes one bundle, and that bundle boots one
adapter - game.config.yaml's first required platform, else its first
(template_contract.build_target). Zipped under every platforms[] name, it would load the
target's SDK on every other portal. The contract already carries what a per-platform build
needs: WGF_GAME_CONFIG makes vite.config.ts build against another config, and makes the
scripts that measure and package a bundle (collect-facts, release:package) read that same
config. So for a title with more than one target, the Factory builds each platform with:

    build/platforms/<id>/game.config.json   game.config.yaml with platforms: [<that entry>,
                                            role required] and build.output: the dist below
    build/platforms/<id>/dist/              the build's output, copied out of build.output
    build/platforms/<id>/build.json         what was built (contract 2's record shape)
    build/platforms/index.json              every platform built, in platforms[] order

Everything is under the template's git-ignored /build/: nothing is written to the tracked
tree, nothing is committed. The platform `build_target` names is built last, so the
repository's own build.output (dist/) holds that platform's bundle afterwards - the bundle
the browser checks play. Deterministic and idempotent: each platform's directory is removed
before it is built, the config is canonical JSON, and the digest is the verification
module's digest over the bundle's repository-relative paths and contents.

A repository whose package.json declares template contract 2 and ships `build:platforms`
builds its platforms itself into the same layout; the Factory then runs that script once,
after the ordinary build, and pins what it wrote (template_contract.builds_per_platform).

A single-platform title on contract 1 is built exactly as before: one `pnpm build`, one
bundle, which is that platform's.
"""

import hashlib
import json
import os
import shlex
import shutil

from wgflib import template_contract as contract

__all__ = ["FACTORY", "REPOSITORY", "mode", "build_order", "variant_config", "PlatformBuild",
           "build_platforms", "digest_tree", "build_command"]

FACTORY, REPOSITORY = "factory", "repository"
RECORD_SCHEMA = "wgf-platform-build/1"
INDEX_SCHEMA = "wgf-platform-builds/1"


def mode(package, platforms):
    """How this repository's platforms are built: REPOSITORY (it builds them itself:
    contract 2's `build:platforms`), FACTORY (contract 1 with more than one target: the
    verify step builds each), or None (contract 1, one target: the one ordinary build)."""
    if contract.builds_per_platform(package):
        return REPOSITORY
    entries = [p for p in platforms or () if isinstance(p, dict) and p.get("id")]
    return FACTORY if len(entries) > 1 else None


def build_order(platforms):
    """platforms[] in order, the build target moved last: the ordinary output directory
    then holds the target's bundle, the one the browser checks play."""
    entries = [p for p in platforms or () if isinstance(p, dict) and p.get("id")]
    target = contract.build_target(entries)
    return [p for p in entries if p["id"] != target] + [p for p in entries if p["id"] == target]


def variant_config(game_config, entry):
    """game.config.yaml for one platform's build: that platform alone, required, and the
    output where its package is made from. Every other key is the game's."""
    config = json.loads(json.dumps(game_config or {}))
    platform = dict(entry)
    platform["role"] = "required"
    config["platforms"] = [platform]
    build = dict(config.get("build") or {}) if isinstance(config.get("build"), dict) else {}
    build["output"] = contract.platform_dist_dir(entry["id"])
    config["build"] = build
    return config


def canonical(document):
    return json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def digest_tree(root, relative):
    """(sha256 digest, file count, bytes) over the paths (relative to `root`) and contents
    under `relative` - the verification module's digest, which release recomputes."""
    base = os.path.join(root, *relative.split("/"))
    outer = hashlib.sha256()
    count = total = 0
    for directory, dirnames, filenames in os.walk(base):
        dirnames[:] = sorted(d for d in dirnames if d != "node_modules")
        for name in sorted(filenames):
            full = os.path.join(directory, name)
            rel = os.path.relpath(full, root).replace(os.sep, "/")
            with open(full, "rb") as handle:
                data = handle.read()
            total += len(data)
            count += 1
            outer.update(rel.encode("utf-8") + b"\0" + hashlib.sha256(data).digest())
    return ("sha256:" + outer.hexdigest()) if count else None, count, total


def _sha256(path):
    try:
        with open(path, "rb") as handle:
            return "sha256:" + hashlib.sha256(handle.read()).hexdigest()
    except OSError:
        return None


def build_command(session):
    """The repository's build: game.config.yaml build.command, else its `build` script."""
    configured = (session.game_config.get("build") or {}).get("command")
    return shlex.split(configured) if configured else session.script_command(contract.SCRIPT_BUILD)


class PlatformBuild:
    """One platform's build, as the report records it (build_artifact.platforms[])."""

    def __init__(self, entry, built_by):
        self.platform_id = entry["id"]
        self.profile = entry.get("profile")
        self.built_by = built_by
        self.path = contract.platform_dist_dir(self.platform_id)
        self.config = contract.platform_build_config(self.platform_id) \
            if built_by == FACTORY else None
        self.config_hash = None
        self.content_hash = None
        self.files = 0
        self.bytes = 0
        self.results = []       # CommandResults, for evidence
        self.problem = None     # why it is not built, or None

    @property
    def built(self):
        return self.problem is None and self.content_hash is not None

    @property
    def env(self):
        """The environment the template's scripts need to measure or package this bundle."""
        return {contract.GAME_CONFIG_ENV: self.config} if self.config else {}

    def to_dict(self):
        out = {"platform_id": self.platform_id, "profile": self.profile,
               "status": "built" if self.built else "not-built", "built_by": self.built_by,
               "path": self.path, "config": self.config, "config_hash": self.config_hash,
               "content_hash": self.content_hash, "files": self.files, "bytes": self.bytes}
        return {k: v for k, v in out.items() if v is not None}


def _record(session, build, entry, commit):
    record = {"schema": RECORD_SCHEMA, "platform": build.platform_id, "profile": build.profile,
              "role": "required", "engine": (session.game_config.get("engine") or {}).get("type"),
              "game_id": (session.game_config.get("game") or {}).get("id"),
              "game_version": (session.game_config.get("game") or {}).get("version"),
              "commit_sha": commit, "dist_digest": build.content_hash,
              "built_by": "web-game-factory verify (WGF_GAME_CONFIG)",
              "config": build.config, "config_hash": build.config_hash}
    path = session.path(*contract.platform_build_record(build.platform_id).split("/"))
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(canonical({k: v for k, v in record.items() if v is not None}))


def _factory(session, platforms):
    """Contract 1: build each platform against its own config; the target last."""
    command = build_command(session)
    out_dir = session.output_dir
    builds = []
    for entry in build_order(platforms):
        build = PlatformBuild(entry, FACTORY)
        builds.append(build)
        directory = session.path(*contract.platform_build_dir(build.platform_id).split("/"))
        shutil.rmtree(directory, ignore_errors=True)
        os.makedirs(directory, exist_ok=True)
        config_path = session.path(*build.config.split("/"))
        with open(config_path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(canonical(variant_config(session.game_config, entry)))
        build.config_hash = _sha256(config_path)
        result = session.run(command, "build", env=build.env)
        build.results.append(result)
        if not result.ok:
            build.problem = result.describe()
            continue
        source = session.path(out_dir)
        if not os.path.isdir(source):
            build.problem = f"the {build.platform_id} build succeeded but produced no {out_dir}/"
            continue
        shutil.copytree(source, session.path(*build.path.split("/")))
        build.content_hash, build.files, build.bytes = digest_tree(session.root, build.path)
        if build.content_hash is None:
            build.problem = f"{build.path}/ is empty after the {build.platform_id} build"
            continue
        _record(session, build, entry, session.commit)
    index = {"schema": INDEX_SCHEMA, "game_id": (session.game_config.get("game") or {}).get("id"),
             "commit_sha": session.commit, "platforms": [
                 {"id": b.platform_id, "profile": b.profile, "dir": b.path,
                  "dist_digest": b.content_hash} for b in sorted(
                     builds, key=lambda b: [p["id"] for p in platforms].index(b.platform_id))]}
    index_path = session.path(*contract.PLATFORM_BUILDS_INDEX.split("/"))
    os.makedirs(os.path.dirname(index_path), exist_ok=True)
    with open(index_path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(canonical(index))
    return builds


def _repository(session, platforms):
    """Contract 2: the repository's own `build:platforms`, then what it wrote, pinned."""
    result = session.run(session.script_command(contract.SCRIPT_BUILD_PLATFORMS), "build")
    builds = []
    index = session.read_json(contract.PLATFORM_BUILDS_INDEX) if result.ok else None
    listed = {str(e.get("id")): e for e in (index or {}).get("platforms") or []
              if isinstance(e, dict)}
    for entry in platforms:
        build = PlatformBuild(entry, REPOSITORY)
        build.results.append(result)
        builds.append(build)
        if not result.ok:
            build.problem = result.describe()
            continue
        item = listed.get(build.platform_id)
        if item is None:
            build.problem = (f"{contract.PLATFORM_BUILDS_INDEX} lists no build for "
                             f"{build.platform_id}")
            continue
        build.path = str(item.get("dir") or build.path)
        build.content_hash, build.files, build.bytes = digest_tree(session.root, build.path)
        if build.content_hash is None:
            build.problem = f"{build.path}/ is missing or empty"
        elif item.get("dist_digest") and item["dist_digest"] != build.content_hash:
            build.problem = (f"{build.path}/ hashes to {build.content_hash}, but "
                             f"{contract.PLATFORM_BUILDS_INDEX} recorded {item['dist_digest']}")
    return builds


def build_platforms(session, how):
    """[PlatformBuild] for every target platform, built `how` (FACTORY or REPOSITORY)."""
    platforms = [p for p in session.platforms]
    return (_factory if how == FACTORY else _repository)(session, platforms)

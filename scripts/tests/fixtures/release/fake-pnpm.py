#!/usr/bin/env python3
"""A stand-in for `pnpm` in a game repository, for the release module's tests.

Implements the two scripts the release step runs, the way web-game-template's
scripts/release/package.mjs and make-manifest.mjs do: one zip per target platform of the
build output's contents (sourcemaps dropped, each entry stamped with the file's modification
time, as adm-zip does), packages.json and checksums.txt, then a manifest.json in the
release-manifest shape. FAKE_PNPM (comma-separated) breaks it on purpose:

    fail-package      release:package exits 1
    include-maps      sourcemaps are packaged
    wrong-checksum    packages.json records a checksum that is not the file's
    bad-manifest      the manifest misses its changelog and has a non-semver version
    no-manifest       release:manifest writes nothing and exits 0
    nested            the bundle is packaged under a dist/ folder, not at the archive root

Every invocation is appended to FAKE_PNPM_LOG as a JSON line when that is set.
"""

import hashlib
import json
import os
import subprocess
import sys
import time
import zipfile

sys.path.insert(0, os.environ["WGF_SCRIPTS"])

from wgflib.hashing import content_hash  # noqa: E402
from wgflib.yamllite import load_file  # noqa: E402

FLAGS = set(filter(None, os.environ.get("FAKE_PNPM", "").split(",")))


def options(args):
    out, i = {}, 0
    while i < len(args):
        if args[i].startswith("--"):
            key = args[i][2:]
            if i + 1 < len(args) and not args[i + 1].startswith("--"):
                out[key] = args[i + 1]
                i += 2
                continue
            out[key] = True
        i += 1
    return out


def sha256(path):
    with open(path, "rb") as handle:
        return "sha256:" + hashlib.sha256(handle.read()).hexdigest()


def package(root, opts, config):
    if "fail-package" in FLAGS:
        print("package.mjs: something broke", file=sys.stderr)
        return 1
    release_id = opts["release"]
    dist = os.path.join(root, (config.get("build") or {}).get("output") or "dist")
    out = os.path.join(root, "release", release_id)
    os.makedirs(out, exist_ok=True)
    files = []
    for directory, dirnames, filenames in os.walk(dist):
        dirnames.sort()
        for name in sorted(filenames):
            rel = os.path.relpath(os.path.join(directory, name), dist).replace(os.sep, "/")
            if rel.endswith(".map") and "include-maps" not in FLAGS:
                continue
            files.append(rel)
    packages = []
    for platform in config.get("platforms") or []:
        filename = f"{platform['id']}.zip"
        path = os.path.join(out, filename)
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
            for rel in files:
                full = os.path.join(dist, rel)
                stat = os.stat(full)
                info = zipfile.ZipInfo(("dist/" if "nested" in FLAGS else "") + rel,
                                       time.localtime(stat.st_mtime)[:6])
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = (stat.st_mode & 0xFFFF) << 16
                with open(full, "rb") as handle:
                    archive.writestr(info, handle.read())
        checksum = sha256(path)
        if "wrong-checksum" in FLAGS:
            checksum = "sha256:" + "0" * 64
        packages.append({"platform_id": platform["id"], "filename": filename,
                         "size_mb": round(os.path.getsize(path) / 1024 / 1024, 3),
                         "checksum": checksum})
        print(f"{filename}  {checksum}")
    with open(os.path.join(out, "packages.json"), "w") as handle:
        json.dump(packages, handle, indent=2)
    with open(os.path.join(out, "checksums.txt"), "w") as handle:
        handle.write("".join(f"{p['checksum'][7:]}  {p['filename']}\n" for p in packages))
    return 0


def manifest(root, opts, config):
    if "no-manifest" in FLAGS:
        return 0
    release_id = opts["release"]
    out = os.path.join(root, "release", release_id)
    with open(os.path.join(out, "packages.json")) as handle:
        packages = json.load(handle)
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True,
                          text=True).stdout.strip()
    now = "2026-09-24T00:00:00.000Z"
    game_id = config["game"]["id"]
    document = {
        "provenance": {
            "artifact_id": f"wgf:release-manifest:{game_id}:20260924-01",
            "artifact_type": "release-manifest", "schema_version": "1.0.0",
            "title_id": game_id, "produced_by": {"role": "release", "actor": "automation"},
            "produced_at": now, "inputs": [], "content_hash": "", "status": "draft",
        },
        "release_id": release_id, "title_id": game_id, "version": opts["version"],
        "kind": opts.get("kind", "content"), "state": opts.get("state", "draft"),
        "commit_sha": head, "build_ref": {"built_at": now}, "packages": packages,
        "target_platforms": [{"id": p["id"], "role": p.get("role", "required"),
                              "profile_version": str(p["profile"]).split("@")[1]}
                             for p in config.get("platforms") or []],
        "changelog": ["First release."],
    }
    if "bad-manifest" in FLAGS:
        del document["changelog"]
        document["version"] = "1.0"
    document["provenance"]["content_hash"] = content_hash(document)
    with open(os.path.join(out, "manifest.json"), "w") as handle:
        json.dump(document, handle, indent=2)
    return 0


def main(argv):
    if os.environ.get("FAKE_PNPM_LOG"):
        with open(os.environ["FAKE_PNPM_LOG"], "a") as handle:
            handle.write(json.dumps(argv) + "\n")
    if argv[:1] == ["run"]:
        argv = argv[1:]
    if not argv:
        return 2
    root = os.getcwd()
    config = load_file(os.path.join(root, "game.config.yaml"))
    script, opts = argv[0], options(argv[1:])
    if script == "release:package":
        return package(root, opts, config)
    if script == "release:manifest":
        return manifest(root, opts, config)
    print(f"fake pnpm: unknown script {script}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

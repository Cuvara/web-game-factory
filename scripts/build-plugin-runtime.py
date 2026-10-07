#!/usr/bin/env python3
"""Build the Factory runtime the Claude plugin ships: claude-web-game-plugin/runtime/.

Claude Code installs a plugin by copying its directory, and nothing outside it, into the
plugin cache. A command that reads core/ or runs the engine can therefore only rely on what
is inside the plugin directory - never on the working directory being this repository. This
script copies the runtime closure into the plugin, so an installed plugin is the Factory
runtime and the working directory is only ever the project (scripts/wgflib/paths.py):

    core/                       every machine, schema, gate, workflow, role, template, craft
                                and reference file the surfaces point at and the engine reads
    scripts/wgf.py, bin/wgf     the workflow engine and its shim
    scripts/wgf-*.py            the state, guard, hash, template-pin, asset and model tools
    scripts/wgflib/, wgf_*/     the engine library and every step module, with their data
    workspace/library/fonts     the Factory font library (OFL WOFF2s, their licences, fonts.json)
    workspace/config/<shipped>  the configuration defaults, the template pin and the opt-in
                                profiles (profiles/*.yaml)
    docs/<read by a surface>    the documents a generated surface tells the agent to read
    VERSION

and nothing else: no tests, golden runs, evidence harness, instance data (claims,
opportunities, titles, research) or bytecode. `runtime-manifest.json` lists every file with
its sha256; its presence is also how the engine knows it runs from an installed plugin.

    python scripts/build-plugin-runtime.py            rebuild the bundle in place
    python scripts/build-plugin-runtime.py --check    exit 1 if the bundle differs from source
    python scripts/build-plugin-runtime.py --dest DIR build into DIR instead (a fresh package)

gen-adapters.sh runs the build; check-integrity.py runs the check. Standard library only.
"""

import argparse
import fnmatch
import hashlib
import json
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DEST = os.path.join("claude-web-game-plugin", "runtime")
MANIFEST = "runtime-manifest.json"

# Directories copied whole (minus EXCLUDE), and single files. Relative to the repository root.
TREES = ["core", "scripts/wgflib",
         # The Factory font library the assets step's `fonts` producer bundles from.
         "workspace/library/fonts",
         # Opt-in configuration overlays a project copies to its own factory.yaml.
         "workspace/config/profiles",
         # The quality bar every look-making or look-judging agent is shown.
         "workspace/quality-bar"]
TREE_GLOBS = ["scripts/wgf_*"]
FILES = [
    "VERSION",
    "bin/wgf",
    "scripts/wgf.py",
    "scripts/wgf-state.py",
    "scripts/wgf-guard.py",
    "scripts/wgf-hash.py",
    "scripts/wgf-template.py",
    # The asset pipelines outside a run: 2D (wgf_assets names it in what it reports) and 3D
    # (Blender doctor, model build, GLB inspect). Both import only the bundled wgf_assets.
    "scripts/wgf-assets.py",
    "scripts/wgf-model.py",
    # Publication outside a run: the publication profiles, capturing a portal session,
    # the publication guards on a manifest (wgf_publish, docs/publish-module.md).
    "scripts/wgf-publish.py",
    # A person's playtest findings against a build (wgf_baseline, docs/accepted-baseline.md).
    "scripts/wgf-playtest.py",
    # Shipped installation defaults. An instance overrides any of them with its own
    # workspace/config/<name> (paths.config_file); the template pin is the release's own.
    "workspace/config/factory.yaml",
    "workspace/config/portfolio.yaml",
    "workspace/config/template.lock.json",
    "workspace/config/mcp-playwright-localhost.json",
    # Named in the workflow entry point's read-first list (gen-adapters.sh).
    "docs/workflow-engine.md",
    # Named in the release agent's, the release skill's and /wgf-publish's read-first lists.
    "docs/publish-module.md",
    "docs/portal-publishing-architecture.md",
]
EXCLUDE = ["__pycache__", "*.pyc", "*.pyo", ".DS_Store", "Thumbs.db"]


def _excluded(name):
    return any(fnmatch.fnmatch(name, pattern) for pattern in EXCLUDE)


def runtime_files(root=ROOT):
    """Sorted repository-relative paths (forward slashes) of the runtime closure."""
    found = set()
    trees = list(TREES)
    for pattern in TREE_GLOBS:
        parent, glob = os.path.split(pattern)
        for name in sorted(os.listdir(os.path.join(root, parent))):
            if fnmatch.fnmatch(name, glob) and os.path.isdir(os.path.join(root, parent, name)):
                trees.append(f"{parent}/{name}")
    for tree in trees:
        for directory, dirs, files in os.walk(os.path.join(root, tree)):
            dirs[:] = sorted(d for d in dirs if not _excluded(d))
            for name in files:
                if not _excluded(name):
                    path = os.path.join(directory, name)
                    found.add(os.path.relpath(path, root).replace(os.sep, "/"))
    for path in FILES:
        if not os.path.isfile(os.path.join(root, path)):
            raise SystemExit(f"build-plugin-runtime: {path} is missing from the source")
        found.add(path)
    return sorted(found)


def _sha256(path):
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


def manifest(root=ROOT):
    with open(os.path.join(root, "VERSION"), encoding="utf-8") as handle:
        version = handle.read().strip()
    return {
        "factory_version": version,
        "note": "Generated by scripts/build-plugin-runtime.py from the web-game-factory "
                "repository. Do not edit; rebuild.",
        "files": {path: "sha256:" + _sha256(os.path.join(root, path))
                  for path in runtime_files(root)},
    }


def _manifest_bytes(document):
    return (json.dumps(document, indent=2, sort_keys=True) + "\n").encode("utf-8")


def build(dest, root=ROOT):
    """Replace `dest` with a fresh bundle. Refuses to remove a directory it did not build."""
    dest = os.path.abspath(dest)
    if os.path.exists(dest):
        if os.listdir(dest) and not os.path.isfile(os.path.join(dest, MANIFEST)):
            raise SystemExit(f"build-plugin-runtime: {dest} exists and holds no {MANIFEST}; "
                             "refusing to replace a directory this script did not build")
        shutil.rmtree(dest)
    document = manifest(root)
    for path in document["files"]:
        target = os.path.join(dest, *path.split("/"))
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copyfile(os.path.join(root, path), target)
        shutil.copymode(os.path.join(root, path), target)
    with open(os.path.join(dest, MANIFEST), "wb") as handle:
        handle.write(_manifest_bytes(document))
    return document


def check(dest, root=ROOT):
    """Problems (strings) between the source's runtime closure and the bundle at `dest`."""
    dest = os.path.abspath(dest)
    expected = manifest(root)
    problems = []
    try:
        with open(os.path.join(dest, MANIFEST), "rb") as handle:
            if handle.read() != _manifest_bytes(expected):
                problems.append(f"{MANIFEST} is stale")
    except OSError:
        return [f"{dest}: no {MANIFEST}; build it with scripts/build-plugin-runtime.py"]
    present = set()
    for directory, dirs, files in os.walk(dest):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for name in files:
            relative = os.path.relpath(os.path.join(directory, name), dest).replace(os.sep, "/")
            if relative != MANIFEST and not _excluded(name):
                present.add(relative)
    for path in sorted(present - set(expected["files"])):
        problems.append(f"{path}: in the bundle, not in the runtime closure")
    for path, digest in expected["files"].items():
        if path not in present:
            problems.append(f"{path}: missing from the bundle")
        elif "sha256:" + _sha256(os.path.join(dest, *path.split("/"))) != digest:
            problems.append(f"{path}: differs from source")
    return problems


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true",
                        help="compare the bundle with the source; exit 1 on any difference")
    parser.add_argument("--dest", default=os.path.join(ROOT, DEFAULT_DEST),
                        help=f"bundle directory (default: {DEFAULT_DEST})")
    args = parser.parse_args(argv)
    if args.check:
        problems = check(args.dest)
        for problem in problems:
            print(f"  - {problem}")
        print("plugin runtime: " + (f"STALE - {len(problems)} problem(s); run "
                                    "scripts/build-plugin-runtime.py" if problems else "OK"))
        return 1 if problems else 0
    document = build(args.dest)
    print(f"plugin runtime: {len(document['files'])} files -> {args.dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""The golden-run REPLAY developer: a deterministic stand-in for an agent developer.

    replay_developer.py --game 2d|3d --brief <brief.md> --repo <checkout> [--key <key>]

It is what `factory.develop.developer: {kind: command}` runs in a golden run, through the
real develop step and wgflib.procs, exactly where an agent host would run. It is NOT an AI
developer and must never be described as one. It replays a known-good game: it ports one of
web-game-template's own example games (examples/tower-merge-rush, PixiJS 2D, or
examples/neon-drift-arena, Three.js 3D - both shipped inside every repository created from
the template) into the layout the development brief asks for, and reports honestly what the
port does and does not cover of the design.

What it does, in order:

1. Reads the brief (brief.md, and brief.json beside it). Refuses (exit 3) if the brief's
   engine is not the engine of the game it replays: it cannot port a 2D game into a 3D
   design, and pretending to would defeat the golden run.
2. Copies the example's portable files from the repository's own examples/ directory (pure
   rules, the engine view, input, unit tests), with import paths adapted to src/ and a
   provenance header. See fixtures/<game>/port.json.
3. Writes the adaptation under fixtures/<game>/port/ and fixtures/shared/port/: main.ts on
   the template's boot sequence, the scene wired to the integration seam, UI, audio,
   locales, index.html and a browser test tagged by gameplay aspect.
4. Writes src/game/integration.ts from the interface in the brief, verbatim.
5. Adds the engine package the example itself depends on (pixi.js / three) to package.json
   at the version the example pins, and updates the lockfile offline
   (`pnpm install --offline`) - the store already holds it, since the template's own
   examples install it.
6. Points the template's smoke test at the game's scene id (it asserted the removed boot
   scene) and removes the template's boot scene.
7. Writes docs/development/report.json: every required system, every MVP item of the brief
   verbatim with an honest status (a design item the example does not cover is `partial` or
   `cut`, never `built`), every placement, and the assets - all placeholders.

Every child process goes through wgflib.procs. Nothing is committed: the develop step runs
its checks and commits.
"""

import argparse
import json
import os
import re
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from wgflib import procs  # noqa: E402

FIXTURES = os.path.join(HERE, "fixtures")
SHARED_PORT = os.path.join(FIXTURES, "shared", "port")
REPORT_PATH = "docs/development/report.json"
INTEGRATION_PATH = "src/game/integration.ts"
SMOKE_SPEC = "tests/e2e/smoke.spec.ts"
REPLAY_LABEL = ("golden-run replay developer (scripts/golden/replay_developer.py): a "
                "deterministic port of a known-good template example, not an AI developer")
SOURCE_SUFFIXES = (".ts", ".tsx", ".js", ".mjs")

# The systems the brief requires (wgf_develop.brief.REQUIRED_SYSTEMS), and where the port
# provides each. Read from the brief itself; this is only the explanation per system.
SYSTEM_NOTES = {
    "boot": "src/main.ts keeps the template's boot order; the boot scene is replaced",
    "game-state": "state model in src/game/ (rules or simulation), unit-tested",
    "scenes": "one Scene (src/game/app.ts) publishing its id to #hud[data-scene]",
    "input": "src/input/ maps keyboard, mouse and touch to game actions; ignored while paused",
    "core-loop": "advanced by the fixed-timestep update() of @wgf/game-core",
    "mechanics": "the example's rules, as pure code with the example's unit tests",
    "progression": "difficulty ramp from the example; personal best via the seam's save/load",
    "ui": "src/ui/screens.ts: title, pause and game-over screens",
    "hud": "in-run score / best HUD",
    "tutorial": "one-sentence rules on the title screen; first play in one tap",
    "game-over": "game-over screen with the result and the best result",
    "restart": "one action from game over, no reload",
    "asset-loading": "everything is procedural; loading progress reported through the platform",
    "responsive-layout": "renderer and view resize with the window and visual viewport",
    "audio-hooks": "src/audio/audio.ts: named cues, muted until first input and while paused",
}


class ReplayError(Exception):
    pass


def log(message):
    print(f"[replay-developer] {message}", flush=True)


def read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def load_port(game_key):
    path = os.path.join(FIXTURES, game_key, "port.json")
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def port_files(game_key):
    """(relative path, absolute source) for every overlay file, game-specific winning."""
    files = {}
    for root in (SHARED_PORT, os.path.join(FIXTURES, game_key, "port")):
        for directory, dirs, names in os.walk(root):
            dirs.sort()
            for name in sorted(names):
                source = os.path.join(directory, name)
                relative = os.path.relpath(source, root).replace(os.sep, "/")
                files[relative] = source
    return sorted(files.items())


def provenance_header(example, source):
    return (f"// GOLDEN-RUN REPLAY: copied from examples/{example}/{source} by the Factory's\n"
            f"// golden-run replay developer (scripts/golden/replay_developer.py); not\n"
            f"// agent-written. Only import paths were adapted to the template layout.\n")


def plan_copies(port, repo):
    """[(target relative path, text)] for the example files the port copies."""
    example_dir = os.path.join(repo, "examples", port["example"])
    if not os.path.isdir(example_dir):
        raise ReplayError(f"{example_dir} does not exist: the repository was not created "
                          f"from a template revision that ships examples/{port['example']}")
    planned = []
    for entry in port["copy"]:
        source = os.path.join(example_dir, *entry["from"].split("/"))
        if not os.path.exists(source):
            raise ReplayError(f"examples/{port['example']}/{entry['from']} is missing")
        text = read(source)
        for old, new in entry.get("replace") or []:
            if old not in text:
                raise ReplayError(f"examples/{port['example']}/{entry['from']}: expected "
                                  f"{old!r} to adapt, found none - the example changed")
            text = text.replace(old, new)
        if entry["to"].endswith(SOURCE_SUFFIXES):
            text = provenance_header(port["example"], entry["from"]) + text
        planned.append((entry["to"], text))
    return planned


def integration_contract(brief_md):
    """The GameIntegration interface the brief states, verbatim."""
    section = brief_md.split("## Integration seam", 1)
    if len(section) != 2:
        raise ReplayError("the brief has no 'Integration seam' section")
    match = re.search(r"```ts\n(.*?)```", section[1], re.S)
    if not match or "interface GameIntegration" not in match.group(1):
        raise ReplayError("the brief's integration seam section has no GameIntegration block")
    return match.group(1)


def engine_dependencies(port, repo):
    """{name: version} from the example's own package.json."""
    manifest = json.loads(read(os.path.join(repo, "examples", port["example"], "package.json")))
    found = {}
    for name in port["engine_dependencies"]:
        for field in ("dependencies", "devDependencies"):
            version = (manifest.get(field) or {}).get(name)
            if version:
                found[name] = (field, version)
                break
        else:
            raise ReplayError(f"examples/{port['example']}/package.json does not pin {name}")
    return found


def add_dependencies(repo, deps):
    """Add the engine packages to the root package.json. Returns True if it changed."""
    path = os.path.join(repo, "package.json")
    manifest = json.loads(read(path))
    changed = False
    for name, (field, version) in deps.items():
        section = manifest.setdefault(field, {})
        if section.get(name) != version:
            section[name] = version
            manifest[field] = dict(sorted(section.items()))
            changed = True
    if changed:
        write(path, json.dumps(manifest, indent=2) + "\n")
    return changed


def run(argv, repo, timeout):
    log("$ " + " ".join(argv))
    result = procs.run(argv, cwd=repo, timeout=timeout)
    if not result.ok:
        raise ReplayError(f"{' '.join(argv)} failed ({result.status}):\n{result.tail(3000)}")
    return result


def point_smoke_at_scene(repo, scene_id):
    path = os.path.join(repo, SMOKE_SPEC)
    if not os.path.exists(path):
        return False
    text = read(path)
    old = 'toHaveAttribute("data-scene", "boot")'
    if old not in text:
        return False
    write(path, text.replace(old, f'toHaveAttribute("data-scene", "{scene_id}")'))
    return True


def build_report(brief, port, written):
    trigger_by_kind = {}
    for placement in brief.get("placements") or []:
        trigger_by_kind.setdefault(placement.get("kind"), placement.get("trigger"))
    mvp, deltas = [], []
    for item in brief.get("mvp") or []:
        entry = port["mvp"].get(item)
        if entry is None:
            entry = {"status": "cut",
                     "notes": "Not part of the replayed example; the replay developer ports a "
                              "known game and builds no new scope."}
        mvp.append({"item": item, "status": entry["status"], "notes": entry["notes"]})
        if entry["status"] in ("cut", "deferred", "partial"):
            deltas.append({"item": item,
                           "direction": "deferred" if entry["status"] == "deferred" else "cut",
                           "reason": entry["notes"]})
    systems = {s["id"]: "done" for s in brief.get("required_systems") or []}
    return {
        "engine": brief["engine"],
        "systems": systems,
        "system_notes": {k: SYSTEM_NOTES.get(k, "") for k in systems},
        "mvp": mvp,
        "placements": [
            {"id": p["id"], "kind": p["kind"],
             "trigger": trigger_by_kind.get(p["kind"]) or f"game placement {p['id']}"}
            for p in port["placements"]
        ],
        "integration_status": {
            "platform_sdk": "partial",
            "monetization": "rewarded and interstitial placements go through the seam; the "
                            "default implementation wraps the template's Platform and "
                            "withAdBreak until the sdk step rewires it",
            "analytics": "run_over events through the seam's track(), NullSink by default",
            "persistence": "personal best through the seam's save/load (platform storage)",
        },
        "assets": [{"id": a["id"], "status": "placeholder"} for a in brief.get("assets") or []],
        "scope_deltas": deltas,
        "known_issues": list(port["known_issues"]),
        "how_to_play": port["how_to_play"],
        "replay": {
            "developer": REPLAY_LABEL,
            "example": f"examples/{port['example']}",
            "files": sorted(written),
        },
    }


def replay(game_key, brief_md_path, repo):
    repo = os.path.abspath(repo)
    port = load_port(game_key)
    brief_md = read(brief_md_path)
    brief_json_path = os.path.join(os.path.dirname(brief_md_path), "brief.json")
    brief = json.loads(read(brief_json_path))
    if brief.get("engine") != port["engine"]:
        raise ReplayError(
            f"the brief's engine is {brief.get('engine')!r}; this replay ports a "
            f"{port['engine']} game (examples/{port['example']}) and will not pretend "
            f"otherwise")
    log(f"{REPLAY_LABEL}")
    log(f"replaying examples/{port['example']} into {repo} (engine {port['engine']})")

    written = []
    for relative, text in plan_copies(port, repo):
        write(os.path.join(repo, *relative.split("/")), text)
        written.append(relative)
    for relative, source in port_files(game_key):
        target = os.path.join(repo, *relative.split("/"))
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copyfile(source, target)
        written.append(relative)
    write(os.path.join(repo, *INTEGRATION_PATH.split("/")), integration_contract(brief_md))
    written.append(INTEGRATION_PATH)

    for relative in port.get("remove") or []:
        path = os.path.join(repo, *relative.split("/"))
        if os.path.exists(path):
            os.remove(path)
            log(f"removed {relative}")
    if point_smoke_at_scene(repo, port["scene_id"]):
        written.append(SMOKE_SPEC)

    deps = engine_dependencies(port, repo)
    if add_dependencies(repo, deps):
        written.append("package.json")
        log("package.json: " + ", ".join(f"{n}@{v}" for n, (_, v) in sorted(deps.items())))
    # The lockfile follows package.json; everything it needs is in the store already.
    run(["pnpm", "install", "--offline", "--no-frozen-lockfile"], repo, timeout=900)

    sources = [p for p in written if p.endswith(SOURCE_SUFFIXES + (".html", ".json"))
               and not p.startswith("public/")]
    run(["pnpm", "exec", "prettier", "--write", *sorted(set(sources))], repo, timeout=300)

    report = build_report(brief, port, written)
    write(os.path.join(repo, *REPORT_PATH.split("/")),
          json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    log(f"wrote {len(written)} file(s) and {REPORT_PATH}")
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--game", required=True, choices=["2d", "3d"])
    parser.add_argument("--brief", required=True)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--key", default=None, help="the develop step's idempotency key")
    args = parser.parse_args(argv)
    procs.install_signal_cleanup()
    try:
        replay(args.game, args.brief, args.repo)
    except ReplayError as exc:
        log(f"refused: {exc}")
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())

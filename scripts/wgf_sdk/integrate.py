"""The side effect: what the step writes into the game repository, and what it finds there.

Whole files only, all convergent - running the step twice leaves the repository as running
it once did, which is this module's idempotency (docs/workflow-module-contract.md §8). No
file the game wrote is edited: there is no patching of src/main.ts or of anything else.

1. Files the step owns outright, copied from `game/` beside this file:
       src/platform/gameplay.ts                     the gameplay integration layer
       tests/unit/platform/gameplay-integration.test.ts   its SDK-mock suite
       src/platform/game-integration.ts             the seam, implemented on it
       tests/unit/platform/game-integration.test.ts
   and one it generates, src/platform/integration-plan.ts, from the game-design.
2. The seam's wiring, src/platform/integration.ts (wgflib.gameseam): the develop step
   provided its default; this step writes the integrated version over it, same exports.
   src/main.ts already boots through it - `seam_problems` says so, or the step refuses the
   build rather than integrate a game that would never call the integration.
3. Nothing else. Gameplay code - where the player dies, where a level ends - belongs to the
   develop step. This module reads it (`scan_hooks`) to report which moments are wired.
"""

import json
import os
import re

from wgflib import gameseam

__all__ = [
    "OWNED_FILES",
    "SEAM_FILES",
    "WIRING_FILE",
    "has_seam",
    "seam_problems",
    "write_seam_files",
    "write_wiring",
    "scan_seam",
    "PLAN_FILE",
    "write_owned_files",
    "write_plan",
    "scan_hooks",
    "render_plan",
]

HERE = os.path.dirname(os.path.abspath(__file__))
GAME_FILES = os.path.join(HERE, "game")

OWNED_FILES = (
    "src/platform/gameplay.ts",
    "tests/unit/platform/gameplay-integration.test.ts",
)
# The seam implemented on the gameplay layer, for the develop step's src/game/integration.ts.
SEAM_FILES = (
    "src/platform/game-integration.ts",
    "tests/unit/platform/game-integration.test.ts",
)
SEAM_DECLARATION = gameseam.CONTRACT_PATH
WIRING_FILE = gameseam.WIRING_PATH
PLAN_FILE = "src/platform/integration-plan.ts"
PRINT_WIDTH = 100


def _write_if_changed(repo, relative, text):
    """'created', 'updated' or 'unchanged'. Never rewrites identical content."""
    path = os.path.join(repo, *relative.split("/"))
    before = None
    if os.path.exists(path):
        with open(path, encoding="utf-8") as handle:
            before = handle.read()
    if before == text:
        return "unchanged"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    return "created" if before is None else "updated"


def has_seam(repo):
    path = os.path.join(repo, *SEAM_DECLARATION.split("/"))
    if not os.path.exists(path):
        return False
    with open(path, encoding="utf-8") as handle:
        return "interface GameIntegration" in handle.read()


def write_seam_files(repo):
    return write_owned_files(repo, SEAM_FILES)


def seam_problems(repo):
    """Why the game cannot be integrated through its seam; [] when it can."""
    problems = []
    if not has_seam(repo):
        problems.append(f"{SEAM_DECLARATION} does not declare GameIntegration")
    if not os.path.exists(os.path.join(repo, *WIRING_FILE.split("/"))):
        problems.append(f"{WIRING_FILE} (the seam's wiring, provided by the develop step) is "
                        "missing")
    return problems + gameseam.seam_problems(repo)


def write_wiring(repo):
    """The integrated wiring over the develop step's default: one whole file, same exports."""
    return write_owned_files(repo, (WIRING_FILE,))[0]


def write_owned_files(repo, files=OWNED_FILES):
    records = []
    for relative in files:
        with open(os.path.join(GAME_FILES, *relative.split("/")), encoding="utf-8") as handle:
            text = handle.read()
        records.append({"path": relative, "action": _write_if_changed(repo, relative, text)})
    return records


# -- the generated plan ---------------------------------------------------------------------

_IDENTIFIER = re.compile(r"^[A-Za-z_$][A-Za-z0-9_$]*$")


def _ts(value, indent):
    """`value` as a TypeScript literal in the template's prettier style."""
    pad, inner = "  " * indent, "  " * (indent + 1)
    if isinstance(value, dict):
        if not value:
            return "{}"
        lines = []
        for key, item in value.items():
            name = key if _IDENTIFIER.match(key) else json.dumps(key)
            lines.append(f"{inner}{name}: {_ts(item, indent + 1)},")
        return "{\n" + "\n".join(lines) + f"\n{pad}}}"
    if isinstance(value, list):
        if not value:
            return "[]"
        flat = "[" + ", ".join(_ts(item, indent + 1) for item in value) + "]"
        if "\n" not in flat and len(inner) + len(flat) + 30 <= PRINT_WIDTH:
            return flat
        return "[\n" + "\n".join(f"{inner}{_ts(i, indent + 1)}," for i in value) + f"\n{pad}]"
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    return json.dumps(value, ensure_ascii=False)


def render_plan(plan, source):
    return (
        f"// Generated by the Factory's `sdk` workflow step from {source}.\n"
        "// Do not edit: change the game-design and run the step again.\n"
        "\n"
        'import type { IntegrationPlan } from "./gameplay.js";\n'
        "\n"
        f"export const INTEGRATION_PLAN: IntegrationPlan = {_ts(plan, 0)};\n"
    )


def write_plan(repo, plan, source):
    action = _write_if_changed(repo, PLAN_FILE, render_plan(plan, source))
    return {"path": PLAN_FILE, "action": action}


# -- reading the game -----------------------------------------------------------------------

# Method names specific enough to recognise on any receiver - scenes hold the instance under
# whatever name they like. The generic ones (save, load, pause, resume) count only in files
# that import the gameplay module, where they can be ours.
_DISTINCT_CALL = re.compile(
    r"\.\s*(runStarted|continueFrom|gameOver|levelComplete|canOfferReward|offerReward|"
    r"naturalBreak)\s*"
    r"\(\s*(?:\"([a-z-]+)\")?"
)
_GENERIC_CALL = re.compile(r"\.\s*(save|load|pause|resume)\s*(?:<[^>]*>)?\(")
_IMPORTS_GAMEPLAY = re.compile(r'from\s+"[./]*(?:platform/)?gameplay\.js"')
_MAIN_CALLS = {
    # The seam's wiring boots through bootPlatform; main.ts calls it as createGamePlatform.
    "boot": re.compile(r"\b(?:createGamePlatform|bootPlatform)\s*\("),
    "loading-progress": re.compile(r"\.reportLoadingProgress\s*\("),
    "game-ready": re.compile(r"\.signalReady\s*\("),
    "platform-binding": re.compile(r"(?<!function )\bbindPlatform\s*\("),
    "audio-mute": re.compile(r"\bonAudioMutedChange\b"),
    "tracker": re.compile(
        r"\b(?:new PlatformGameplay|createGameIntegration)\s*\([^;]*\btracker\s*[:,}]", re.S),
    "gameplay-audio": re.compile(
        r"\b(?:new PlatformGameplay|createGameIntegration)\s*\([^;]*\baudio\s*[:,}]", re.S),
}
_HOOK_NAMES = {
    "runStarted": "run-start",
    "continueFrom": "continue-from",
    "gameOver": "game-over",
    "levelComplete": "level-complete",
    "pause": "pause",
    "resume": "resume",
    "canOfferReward": "can-offer-reward",
    "offerReward": "offer-reward",
    "naturalBreak": "natural-break",
    "save": "save",
    "load": "load",
}


def _source_files(repo):
    root = os.path.join(repo, "src")
    skip = {os.path.normpath(os.path.join(repo, *p.split("/")))
            for p in (*OWNED_FILES, *SEAM_FILES, PLAN_FILE, WIRING_FILE)}
    for directory, dirs, files in os.walk(root):
        dirs.sort()
        for name in sorted(files):
            path = os.path.normpath(os.path.join(directory, name))
            if name.endswith(".ts") and not name.endswith(".d.ts") and path not in skip:
                yield path


def scan_hooks(repo):
    """hook name -> ['src/file.ts:line', ...] for every hook the game source calls.

    Hooks with a moment carry it: `offer-reward:game-over`, `natural-break:level-complete`.
    """
    found = {}
    for path in _source_files(repo):
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
        relative = os.path.relpath(path, repo).replace(os.sep, "/")

        def add(hook, offset):
            line = text.count("\n", 0, offset) + 1
            found.setdefault(hook, []).append(f"{relative}:{line}")

        for match in _DISTINCT_CALL.finditer(text):
            hook = _HOOK_NAMES[match.group(1)]
            add(hook, match.start())
            if match.group(2):
                add(f"{hook}:{match.group(2)}", match.start())
        if _IMPORTS_GAMEPLAY.search(text):
            for match in _GENERIC_CALL.finditer(text):
                add(_HOOK_NAMES[match.group(1)], match.start())
        for hook, pattern in _MAIN_CALLS.items():
            for match in pattern.finditer(text):
                add(hook, match.start())
    return found


# -- the develop step's seam ----------------------------------------------------------------

_SEAM_PLACEMENT = re.compile(r"\.\s*(canOfferRewarded|rewarded|interstitial)\s*\(\s*\"([^\"]+)\"")
_SEAM_GAMEPLAY = re.compile(r"\.\s*(gameplayStart|gameplayStop)\s*\(")
_SEAM_STORAGE = re.compile(r"\.\s*(save|load)\s*\(")
_IMPORTS_SEAM = re.compile(r'from\s+"[./]*(?:game/)?integration\.js"')


def scan_seam(repo):
    """What the game calls on its seam, outside src/platform/ (where the wiring lives).

    Returns {"placements": {kind: {id: [file:line]}}, "calls": {name: [file:line]}}, kind
    being "rewarded" (from canOfferRewarded or rewarded) or "interstitial".
    """
    placements = {"rewarded": {}, "interstitial": {}}
    calls = {}
    declaration = os.path.normpath(os.path.join(repo, *SEAM_DECLARATION.split("/")))
    for path in _source_files(repo):
        relative = os.path.relpath(path, repo).replace(os.sep, "/")
        if path == declaration or relative.startswith("src/platform/"):
            continue
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
        if not _IMPORTS_SEAM.search(text) and "GameIntegration" not in text:
            continue

        def where(offset):
            return f"{relative}:{text.count(chr(10), 0, offset) + 1}"

        for match in _SEAM_PLACEMENT.finditer(text):
            kind = "interstitial" if match.group(1) == "interstitial" else "rewarded"
            placements[kind].setdefault(match.group(2), []).append(where(match.start()))
            calls.setdefault(match.group(1), []).append(where(match.start()))
        for pattern in (_SEAM_GAMEPLAY, _SEAM_STORAGE):
            for match in pattern.finditer(text):
                calls.setdefault(match.group(1), []).append(where(match.start()))
    return {"placements": placements, "calls": calls}

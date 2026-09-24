"""The integration seam between a game and the Factory's platform wiring.

Two files in every game repository belong to the Factory, not to whoever writes the game:

    src/game/integration.ts       the GameIntegration interface game code calls
    src/platform/integration.ts   its wiring: createGamePlatform() and createGameIntegration()

The `develop` step writes both before the game is built (the wiring's default version), and
the `sdk` step replaces the wiring as a whole file with the integrated version. Nobody edits
src/main.ts on the game's behalf: main.ts itself imports both functions from
./platform/integration.js and never constructs a platform directly. That import is the seam,
and this module is the one definition of what "main.ts uses it" means, so the step that
requires it (develop) and the step that relies on it (sdk) cannot disagree.
"""

import os
import re

__all__ = ["CONTRACT_PATH", "WIRING_PATH", "MAIN_PATH", "WIRING_MODULE", "seam_problems"]

CONTRACT_PATH = "src/game/integration.ts"
WIRING_PATH = "src/platform/integration.ts"
MAIN_PATH = "src/main.ts"
WIRING_MODULE = "./platform/integration.js"
FUNCTIONS = ("createGamePlatform", "createGameIntegration")

_IMPORT = re.compile(r"import\s*\{([^}]*)\}\s*from\s*[\"']([^\"']+)[\"']", re.S)
_COMMENT = re.compile(r"//[^\n]*|/\*.*?\*/", re.S)
_DIRECT = re.compile(r"(?<![\w.$])createPlatform\s*\(")
_SOURCE = (".ts", ".tsx", ".js", ".mjs", ".mts")


def _read(path):
    with open(path, encoding="utf-8", errors="replace") as handle:
        return handle.read()


def seam_problems(root):
    """What keeps src/main.ts from booting through the seam; [] when it does."""
    main = os.path.join(root, *MAIN_PATH.split("/"))
    if not os.path.exists(main):
        return [f"{MAIN_PATH} does not exist"]
    code = _COMMENT.sub("", _read(main))
    imported = set()
    for names, module in _IMPORT.findall(code):
        if module == WIRING_MODULE:
            imported.update(n.strip().split(" as ")[0].strip() for n in names.split(","))
    problems = []
    for name in FUNCTIONS:
        if name not in imported:
            problems.append(f"{MAIN_PATH} does not import {name} from \"{WIRING_MODULE}\"")
        elif not re.search(rf"(?<![\w.$]){name}\s*\(", code):
            problems.append(f"{MAIN_PATH} imports {name} but never calls it")
    for directory, dirs, files in os.walk(os.path.join(root, "src")):
        dirs[:] = [d for d in dirs if d not in ("node_modules", "dist")]
        for name in files:
            if not name.endswith(_SOURCE):
                continue
            path = os.path.join(directory, name)
            relative = os.path.relpath(path, root).replace(os.sep, "/")
            if relative.startswith("src/platform/"):
                continue
            if _DIRECT.search(_COMMENT.sub("", _read(path))):
                problems.append(f"{relative} calls createPlatform directly; the platform comes "
                                f"from createGamePlatform() in {WIRING_PATH}")
    return problems

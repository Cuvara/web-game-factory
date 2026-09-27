"""The integration seam the develop step owes every game: written before it is built,
checked after.

Two files belong to the Factory (wgflib.gameseam): the GameIntegration contract, and its
wiring, whose default this step provides and whose integrated version the sdk step writes
over it as a whole file. The developer writes neither and edits neither; src/main.ts boots
through the wiring. A seam file that differs from what the Factory last put there, or a
main.ts that does not use it, fails conformance - the sdk step could not integrate the
build otherwise, and would have to say so much later.

Five more files belong to the sdk step (gameseam.SDK_OWNED_PATHS), which writes each whole on
every run. The developer creates, edits and deletes none of them: whatever it put there would
be erased by the next sdk run - a regression test deleted after review approved it, found by
the 2.1.1 production run. Each must read as the visit's baseline commit has it (absent when
the sdk step has not run yet).
"""

import os

from wgflib import gameseam

from . import safewrite
from .brief import INTEGRATION_CONTRACT

__all__ = ["SEAM_FILES", "default_files", "ensure_seam", "seam_findings",
           "sdk_owned_findings"]

HERE = os.path.dirname(os.path.abspath(__file__))
SEAM_FILES = (gameseam.CONTRACT_PATH, gameseam.WIRING_PATH)
_CONTRACT_HEADER = ("// Written by the Factory's `develop` step. Do not edit: game code calls "
                    "this seam, and the\n// Factory's `sdk` step wires it "
                    "(src/platform/integration.ts).\n")


def _read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def default_files():
    """{path: text} of the seam as this step provides it."""
    return {
        gameseam.CONTRACT_PATH: _CONTRACT_HEADER + INTEGRATION_CONTRACT,
        gameseam.WIRING_PATH: _read(os.path.join(HERE, "seam", *gameseam.WIRING_PATH.split("/"))),
    }


def ensure_seam(root):
    """Write each seam file that is not there yet. Returns the paths written. An existing
    file is left alone: after the sdk step it is the integrated wiring, not the default."""
    written = []
    for relative, text in default_files().items():
        path = os.path.join(root, *relative.split("/"))
        # lexists: a dangling link is "there" too - and never written through
        # (safewrite refuses a link in the directories, and replaces one at the file).
        if os.path.lexists(path) and not os.path.islink(path):
            continue
        safewrite.write_text(root, path, text)
        written.append(relative)
    return written


def seam_findings(root, git, baseline):
    """Conformance findings for the seam; [] when it is intact and main.ts boots through it.
    Each file must read as the baseline commit has it or, where the baseline has none, as
    this step provides it."""
    findings = []
    for relative, default in default_files().items():
        path = os.path.join(root, *relative.split("/"))
        if not os.path.exists(path):
            findings.append(f"{relative} (the Factory's integration seam) is missing")
            continue
        expected = git.file_at(baseline, relative) if baseline else None
        if _read(path) != (default if expected is None else expected):
            findings.append(f"{relative} belongs to the Factory and was edited; restore it and "
                            f"call the seam instead")
    findings.extend(gameseam.seam_problems(root))
    return findings


def sdk_owned_findings(root, git, baseline):
    """Conformance findings for the sdk step's own files; [] when each reads as `baseline`
    has it (or is absent where `baseline` has none)."""
    findings = []
    for relative in gameseam.SDK_OWNED_PATHS:
        path = os.path.join(root, *relative.split("/"))
        expected = git.file_at(baseline, relative) if baseline else None
        present = os.path.lexists(path)
        if expected is None and not present:
            continue
        if expected is None:
            findings.append(f"{relative} belongs to the Factory's sdk step, which writes it "
                            f"whole on every run; remove it and put your code or tests in a "
                            f"file of your own")
        elif not present or os.path.islink(path) or _read(path) != expected:
            findings.append(f"{relative} belongs to the Factory's sdk step and was "
                            f"{'deleted' if not present else 'edited'}; the next sdk run "
                            f"rewrites it whole. Restore it as it is in "
                            f"{str(baseline)[:12]} and put your code or tests in a file of "
                            f"your own")
    return findings

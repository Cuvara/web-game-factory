"""What a development commit may contain: the paths a developer may write, and nothing else.

The step used to commit with `git add --all`, so whatever the developer left in the tree
shipped: an agent host's settings file with a hook in it, an instruction file the next
agent session would obey, a CI workflow. Now the commit is an explicit list, decided here:

  * a changed path must be under one of `factory.develop.writable_paths` - by default the
    game's own code and content (src/, tests/, public/), the development record
    (docs/development/) and the page (index.html) - or be package.json / pnpm-lock.yaml,
    whose content the conformance check holds to the allowed dependency changes;
  * whatever the list says, a path with a hidden component (.github/, .husky/, an agent
    host's or an editor's settings directory, .env) or an agent instruction file (a
    Markdown file named in capitals, the convention agent hosts read instructions from) is
    refused: those configure tools and agents, not the game;
  * one Factory-rendered file is accepted by exact path, before those rules:
    docs/GDD.md (FACTORY_RENDERED), the game design the step renders from the game-design
    artifact. It matches the instruction-file pattern, but the step writes it again after
    the developer returns and before this check, so what is committed is always the
    Factory's rendering, never an agent's text. It is fixed here, not configurable.

A change outside the scope fails the step, not retryably: the next attempt would find the
same file, and silently leaving it behind would put an uncommitted file under every later
check of the build. The developer is told the scope in the brief.

Where the defaults come from: the template's layout (src/, tests/, public/, index.html),
the brief (docs/development/ is where it and the report live), and the golden replay
developer (scripts/golden/replay_developer.py), which writes exactly those plus a
dependency addition to package.json and the lockfile that follows it.
"""

import re

from wgflib import template_contract as contract

__all__ = ["DEFAULT_WRITABLE", "PACKAGE_FILES", "FACTORY_RENDERED", "refusal", "partition",
           "validate_writable"]

DEFAULT_WRITABLE = ("src/", "tests/", "public/", "docs/development/", "index.html")

# Writable only as far as checks.package_findings allows: dependency additions, and the
# lockfile together with one.
PACKAGE_FILES = (contract.PACKAGE_JSON, contract.PNPM_LOCK)

# Written by the step itself, from an artifact, after the developer: accepted by exact path.
# Kept equal to wgf_develop.gdd.GDD_PATH (a test checks it; importing it here would make the
# scope depend on the renderer).
FACTORY_RENDERED = ("docs/GDD.md",)

# The instruction files agent hosts read from a repository: a capitalised name, optional
# dotted qualifiers, .md (the convention, not any one host's file name).
_INSTRUCTIONS = re.compile(r"^[A-Z][A-Z0-9_-]*(\.[A-Za-z0-9_-]+)*\.md$")


def refusal(path, writable=DEFAULT_WRITABLE):
    """Why `path` may not be committed, or None when it may."""
    if path in FACTORY_RENDERED:
        return None
    parts = path.split("/")
    hidden = next((p for p in parts if p.startswith(".")), None)
    if hidden is not None:
        return (f"{hidden} is a hidden path - tool, CI or agent-host configuration, not the "
                f"game")
    if _INSTRUCTIONS.match(parts[-1]):
        return f"{parts[-1]} is an agent instruction file, not the game"
    if path in PACKAGE_FILES:
        return None
    for entry in writable:
        if (path.startswith(entry) if entry.endswith("/") else path == entry):
            return None
    return "outside the paths a developer may write (" + ", ".join(writable) + ")"


def partition(changes, writable=DEFAULT_WRITABLE):
    """(allowed paths, [(path, reason)] refused) for `[(xy, path)]` from GitRepo.changes."""
    allowed, refused = set(), {}
    for _, path in changes:
        reason = refusal(path, writable)
        if reason is None:
            allowed.add(path)
        else:
            refused[path] = reason
    return sorted(allowed), sorted(refused.items())


def validate_writable(entries):
    """The configured list, or raise ValueError. Relative, inside the checkout, not hidden."""
    if not isinstance(entries, list) or not entries or not all(
            isinstance(e, str) and e.strip() for e in entries):
        raise ValueError("factory.develop.writable_paths must be a non-empty list of paths")
    for entry in entries:
        parts = [p for p in entry.rstrip("/").split("/")]
        if (entry.startswith("/") or "\\" in entry or any(p in ("", ".", "..") for p in parts)
                or any(p.startswith(".") for p in parts)):
            raise ValueError(f"factory.develop.writable_paths: {entry!r} must be a relative "
                             f"path inside the checkout with no hidden component")
    return list(entries)

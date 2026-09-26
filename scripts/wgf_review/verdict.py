"""The verdict a reviewer writes, and the strict check it has to pass.

    {
      "verdict": "approve" | "request-changes",
      "commit":  "<the full sha that was reviewed - must equal HEAD>",
      "blockers": [{"id": "...", "file": "src/..." | null, "line": 12 (optional; null = none),
                    "summary": "...", "severity": "blocker|critical|major|minor"}],
      "notes":   "free text (optional)"
    }

Strict on purpose. A reviewer that approves while listing blockers, asks for changes
without naming one, reviews some other commit, or writes anything the contract does not
have, has not produced a verdict the Factory can act on - and a malformed verdict is never
read charitably as an approval.
"""

import json
import os
import re

__all__ = ["parse", "from_output", "CONTRACT", "VERDICTS", "SEVERITIES"]

VERDICTS = ("approve", "request-changes")
SEVERITIES = ("blocker", "critical", "major", "minor")
_TOP = {"verdict", "commit", "blockers", "notes"}
_BLOCKER = {"id", "file", "line", "summary", "severity"}
_SHA = re.compile(r"^[0-9a-f]{40}$")
_MAX_BYTES = 1024 * 1024

CONTRACT = {
    "verdict": "approve | request-changes",
    "commit": "<the full 40-character sha you reviewed>",
    # Both kinds of finding, so a reviewer sees how to write each: one at a place in the
    # code, and one about the build as a whole - `file` null, no `line`. The live
    # acceptance run's reviewer dropped `file` from a whole-build finding when the example
    # showed only the first kind.
    "blockers": [{"id": "short-kebab-id", "file": "src/path/to/file.ts", "line": 1,
                  "summary": "what is wrong and why it blocks", "severity": "blocker"},
                 {"id": "another-id", "file": None,
                  "summary": "a finding about the build as a whole", "severity": "major"}],
    "notes": "anything else worth saying (optional)",
}


_OPEN = re.compile(r"^\s*```\s*([A-Za-z0-9_+-]*)\s*$")
_CLOSE = re.compile(r"^\s*```\s*$")


def _fenced_blocks(text):
    """[(info, body)] of every fenced code block, in order, paired line by line.

    A regular expression over the whole text pairs a block's CLOSING fence with the next
    block's opening one: a reviewer that quotes code (```ts ... ```) before its verdict
    (```json ... ```) then has its verdict read as prose. Found by the real acceptance run."""
    blocks, info, body = [], None, []
    for line in text.splitlines():
        if info is None:
            opened = _OPEN.match(line)
            if opened:
                info, body = opened.group(1).lower(), []
        elif _CLOSE.match(line):
            blocks.append((info, "\n".join(body)))
            info = None
        else:
            body.append(line)
    return blocks


def from_output(text):
    """The last JSON object in a reviewer's stdout, as text, or None.

    Tried in order: the whole output; the last ```json (or untagged) fence; the last line
    that is an object on its own. Nothing is repaired - what comes back still goes through
    parse()."""
    text = (text or "").strip()
    fences = [body for info, body in _fenced_blocks(text) if info in ("json", "")]
    candidates = [text] + list(reversed(fences))
    candidates += [line.strip() for line in reversed(text.splitlines())
                   if line.strip().startswith("{")]
    for candidate in candidates:
        try:
            if isinstance(json.loads(candidate), dict):
                return candidate
        except ValueError:
            continue
    return None


def parse(path, head):
    """(verdict dict, None) or (None, problem). Never raises."""
    if not os.path.isfile(path):
        return None, f"no verdict file was written at {path}"
    try:
        if os.path.getsize(path) > _MAX_BYTES:
            return None, "verdict file is larger than 1 MiB"
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, UnicodeDecodeError) as exc:
        return None, f"verdict file cannot be read: {exc}"
    except ValueError as exc:
        return None, f"verdict file is not JSON: {exc}"
    if not isinstance(data, dict):
        return None, "verdict must be a JSON object"
    extra = sorted(set(data) - _TOP)
    if extra:
        return None, f"verdict has keys the contract does not: {', '.join(extra)}"
    for key in ("verdict", "commit", "blockers"):
        if key not in data:
            return None, f"verdict is missing {key!r}"
    if data["verdict"] not in VERDICTS:
        return None, f"verdict must be one of {', '.join(VERDICTS)}, not {data['verdict']!r}"
    commit = data["commit"]
    if not isinstance(commit, str) or not _SHA.match(commit):
        return None, "commit must be the full 40-character lowercase sha"
    if commit != head:
        return None, f"verdict is for {commit[:12]}, but the commit under review is {head[:12]}"
    if "notes" in data and not isinstance(data["notes"], str):
        return None, "notes must be a string"
    blockers = data["blockers"]
    if not isinstance(blockers, list):
        return None, "blockers must be a list"
    ids = set()
    for index, blocker in enumerate(blockers):
        where = f"blockers[{index}]"
        if not isinstance(blocker, dict):
            return None, f"{where} must be an object"
        extra = sorted(set(blocker) - _BLOCKER)
        if extra:
            return None, f"{where} has keys the contract does not: {', '.join(extra)}"
        for key in ("id", "file", "summary", "severity"):
            if key not in blocker:
                return None, f"{where} is missing {key!r}"
        if not isinstance(blocker["id"], str) or not blocker["id"].strip():
            return None, f"{where}.id must be a non-empty string"
        if blocker["id"] in ids:
            return None, f"{where}.id {blocker['id']!r} is not unique"
        ids.add(blocker["id"])
        if blocker["file"] is not None and (not isinstance(blocker["file"], str)
                                            or not blocker["file"].strip()):
            return None, f"{where}.file must be a repository path or null"
        if isinstance(blocker["file"], str) and (os.path.isabs(blocker["file"])
                                                 or ".." in blocker["file"].split("/")):
            return None, f"{where}.file must be relative to the repository"
        if not isinstance(blocker["summary"], str) or not blocker["summary"].strip():
            return None, f"{where}.summary must be a non-empty string"
        if blocker["severity"] not in SEVERITIES:
            return None, f"{where}.severity must be one of {', '.join(SEVERITIES)}"
        # `line` is optional; null says the same as leaving it out. Anything else must be a
        # real line number.
        if blocker.get("line") is not None and (not isinstance(blocker["line"], int)
                                                or isinstance(blocker["line"], bool)
                                                or blocker["line"] < 1):
            return None, f"{where}.line must be a positive integer"
    if data["verdict"] == "approve" and blockers:
        return None, "an approval cannot list blockers; request changes instead"
    if data["verdict"] == "request-changes" and not blockers:
        return None, "a request for changes must name at least one blocker"
    return data, None

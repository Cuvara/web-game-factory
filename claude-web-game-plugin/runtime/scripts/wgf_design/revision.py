"""A design re-entered in the same run revises the run's previous game-design.

Found live (2026-10-04, a 2D brick-breaker): the operator grew the strategy's content and
re-ran from research, and the agent author started again from the archetype's draft. It
redesigned the game from scratch - another identity kit, so every asset, the UI and the store
art would have to be made again - and lost content the strategy asked for. A design the run
already holds is the starting point of the next one; only the change is new.

    previous_design(context, strategy)   the run's newest game-design this step produced, the
                                         strategy it was made from, and what changed since
    strategy_delta(before, after)        the changed strategy fields, by dotted path
    as_draft(design)                     a finalized game-design back in the author's draft
                                         shape, so the module finalizes and judges it again

Read-only: the previous design and strategy are read from the run directory, by the location
and checksum the engine recorded for them. Nothing here relaxes a check - the revised draft is
finalized, composed and judged exactly like a first one.
"""

import copy
import glob
import hashlib
import json
import os

__all__ = ["RevisionError", "previous_design", "strategy_delta", "as_draft", "MAX_CHANGES"]

# How many changed fields the agent is shown, at most. A strategy change is a handful of
# fields; past this the list says it was cut, and the agent reads both strategies.
MAX_CHANGES = 80
_MISSING = object()


class RevisionError(RuntimeError):
    """The run's previous game-design cannot be read as the engine recorded it."""


def _read(path, checksum=None):
    with open(path, "rb") as handle:
        payload = handle.read()
    if checksum and "sha256:" + hashlib.sha256(payload).hexdigest() != checksum:
        raise RevisionError(f"{path} changed on disk after the run recorded it")
    return json.loads(payload.decode("utf-8"))


def _newest(refs):
    return max(refs, key=lambda ref: (ref.seq if getattr(ref, "seq", None) is not None else -1,
                                      getattr(ref, "version", 0) or 0))


def _strategy_by_hash(run_dir, content_hash):
    """The run's title-strategy whose provenance content_hash is `content_hash`, or None."""
    if not content_hash:
        return None
    for path in sorted(glob.glob(os.path.join(run_dir, "artifacts", "*", "v*.json"))):
        try:
            content = _read(path)
        except (OSError, ValueError):
            continue
        record = content.get("provenance") if isinstance(content, dict) else None
        if isinstance(record, dict) and record.get("artifact_type") == "title-strategy" \
                and record.get("content_hash") == content_hash:
            return content
    return None


def strategy_delta(before, after, limit=MAX_CHANGES):
    """{changes: [{field, before, after}], truncated}: every field that differs, by dotted
    path. Objects are walked; lists and values are compared whole. `provenance` is not the
    strategy's content and is left out; a field absent on one side has no before / after."""
    changes = []

    def walk(path, a, b):
        if a == b:
            return
        if isinstance(a, dict) and isinstance(b, dict):
            for key in sorted(set(a) | set(b), key=str):
                walk(f"{path}.{key}", a.get(key, _MISSING), b.get(key, _MISSING))
            return
        entry = {"field": path}
        if a is not _MISSING:
            entry["before"] = a
        if b is not _MISSING:
            entry["after"] = b
        changes.append(entry)

    before, after = before or {}, after or {}
    for key in sorted(set(before) | set(after), key=str):
        if key != "provenance":
            walk(key, before.get(key, _MISSING), after.get(key, _MISSING))
    return {"changes": changes[:limit], "truncated": len(changes) > limit}


def previous_design(context, strategy):
    """The revision a re-entered design starts from, or None for a first design.

    {version, artifact_id, design, strategy_delta: {found, unchanged, changes, truncated}}.
    `found` is False when the strategy the previous design pinned is no longer in the run;
    the agent is then told to compare the design with the strategy itself. Raises
    RevisionError when the previous design is not the file the engine recorded."""
    refs = [ref for ref in getattr(context, "previous_outputs", None) or ()
            if getattr(ref, "type", None) == "game-design"]
    run_dir = getattr(context, "run_dir", None)
    if not refs or not run_dir:
        return None
    ref = _newest(refs)
    path = os.path.join(run_dir, *str(ref.location).split("/"))
    try:
        design = _read(path, ref.checksum)
    except (OSError, ValueError) as exc:
        raise RevisionError(f"the run's game-design v{ref.version} cannot be read: {exc}") from exc
    if not isinstance(design, dict) or not isinstance(design.get("build_spec"), dict):
        raise RevisionError(f"the run's game-design v{ref.version} is not a game-design")

    record = design.get("provenance") or {}
    pinned = next((i.get("content_hash") for i in record.get("inputs") or ()
                   if i.get("artifact_type") == "title-strategy"), None)
    current = ((strategy or {}).get("provenance") or {}).get("content_hash")
    if pinned and pinned == current:
        delta = {"found": True, "unchanged": True, "changes": [], "truncated": False}
    else:
        before = _strategy_by_hash(run_dir, pinned)
        if before is None:
            delta = {"found": False, "unchanged": False, "changes": [], "truncated": False}
        else:
            delta = dict(strategy_delta(before, strategy), found=True)
            delta["unchanged"] = not delta["changes"]
    return {"version": ref.version, "artifact_id": record.get("artifact_id"),
            "design": design, "strategy_delta": delta}


def as_draft(design, strategy=None):
    """A finalized game-design in the shape an author returns: what `finalize` and the step
    derive (provenance, consistency, title, brief, applied platform constraints, scope tiers)
    taken back out, so the step derives them again from the current strategy. The research
    block is the current strategy's, with the decisions the design recorded on research."""
    draft = copy.deepcopy(design)
    for key in ("provenance", "consistency", "title_id", "brief", "platform_constraints_applied"):
        draft.pop(key, None)
    scope = draft.get("scope")
    if isinstance(scope, dict):
        tiers = scope.pop("tiers", None) or {}
        scope["out_of_scope"] = list(tiers.get("out_of_scope") or scope.get("out_of_scope") or [])
    previous = draft.pop("research", None)
    carried = (strategy or {}).get("research")
    if isinstance(carried, dict) and carried.get("research_version") == 2:
        applied = (previous or {}).get("applied") if isinstance(previous, dict) else None
        draft["research"] = dict({k: v for k, v in carried.items() if k != "applied"},
                                 applied=list(applied or []))
    return draft

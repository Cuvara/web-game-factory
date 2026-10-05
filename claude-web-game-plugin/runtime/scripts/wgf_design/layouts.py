"""How alike two content units are laid out - measured on the geometry the game builds, never
on the names of its tuning.

A unit's layout is what its content data says about it beyond the descriptive keys
(core/reference/content-sufficiency.yaml `layout.descriptive_keys`). Only part of it is
geometry: the leaves inside a list - a grid's rows, a wave list, a track's segments, a spawn
table, the cells of a board - by path and value (a grid's row 3 is not its row 4). A scalar
outside every list (a par time, a speed, a gem count, a width, a flag, a word) is tuning: the
same layout at another difficulty, and a key a game may never read. Two units whose data are
only tuning scalars carry NO geometry: nothing says they are alike or different, so they are
undetermined - never "repeated" - and adding, renaming or removing a scalar key changes
nothing.

Geometry comes from the unit's own entry in the content data file (`public/content/units.json`,
e.g. its `layout`) and, where the game keeps its layouts apart, from the layout source the
content contract names: a JSON file under `public/content/` keyed by unit id
(content-sufficiency.yaml `layout.source`, or the data file's own `layout_source`).

Used by the content-sufficiency step (scripts/wgf_sufficiency/audit.py, on the build and on the
design) and the design step's own tier check (scripts/wgf_design/content.py
`content.tier_structure`), so the build and the design are judged by one rule.
"""

import hashlib
import json
import os
import posixpath

__all__ = ["TUNING", "CONTENT_DIR", "leaves", "geometry", "similarity", "signature",
           "repetition", "source_of", "read_source"]

# The placeholder a scalar number outside any list stands as in `leaves`: where it sits, not
# its value.
TUNING = "#number"
# Where a layout source may live: beside the content data file, inside the files the build
# serves.
CONTENT_DIR = "public/content"


def _number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def leaves(unit, descriptive=()):
    """{path: value} of every leaf of the unit's data beyond the `descriptive` keys. Array
    positions are kept; a number outside any list stands as TUNING (only where it sits)."""
    skip = set(descriptive or ())
    out = {}

    def walk(path, value):
        if isinstance(value, dict):
            for key in sorted(value):
                walk(f"{path}.{key}" if path else str(key), value[key])
        elif isinstance(value, list):
            for position, item in enumerate(value):
                walk(f"{path}[{position}]", item)
        elif _number(value) is not None and "[" not in path:
            out[path] = TUNING
        else:
            out[path] = json.dumps(value, sort_keys=True)
    for key in sorted(unit or {}):
        if key not in skip:
            walk(str(key), unit[key])
    return out


def geometry(unit, descriptive=(), source=None):
    """The unit's geometry: the leaves of its data that sit inside a list, and every such leaf
    of its entry in the layout source (under `source.`). Empty when its data are only tuning
    scalars - undetermined, not identical."""
    found = {path: value for path, value in leaves(unit, descriptive).items() if "[" in path}
    if source is not None:
        found.update({f"source.{path}": value
                      for path, value in leaves({"layout": source}).items() if "[" in path})
    return found


def similarity(first, second):
    """Jaccard similarity of two layouts' (path, value) leaves; two empty layouts are 1.0."""
    a, b = set(first.items()), set(second.items())
    if not a and not b:
        return 1.0
    return len(a & b) / float(len(a | b))


def signature(found):
    return hashlib.sha256(json.dumps(sorted(found.items())).encode("utf-8")).hexdigest()[:16]


def repetition(view, threshold):
    """{repeated, undetermined, worst} over `view` - units as {id, structure, combo,
    objective_kind, geometry}.

    `repeated`: the units that repeat another, both with geometry: identical geometry, or the
    same structure, combination and objective kind with geometry at least `threshold` alike.
    `undetermined`: the units with no geometry - no evidence either way. `worst`: how many
    units could be repeated if every undetermined unit repeated one that is not yet repeated:
    the most the true count can be, which is what a bar is held to while any is undetermined."""
    measured = [u for u in view if u.get("geometry")]
    undetermined = [u["id"] for u in view if not u.get("geometry")]
    out = set()
    for i, a in enumerate(measured):
        for b in measured[i + 1:]:
            same = signature(a["geometry"]) == signature(b["geometry"])
            alike = (a.get("structure") == b.get("structure") and a.get("combo") == b.get("combo")
                     and a.get("objective_kind") == b.get("objective_kind")
                     and similarity(a["geometry"], b["geometry"]) >= threshold)
            if same or alike:
                out.update((a["id"], b["id"]))
    repeated = [u["id"] for u in measured if u["id"] in out]
    free = len(measured) - len(repeated)
    worst = min(len(view), len(repeated) + len(undetermined) + min(len(undetermined), free))
    return {"repeated": repeated, "undetermined": undetermined, "worst": worst}


def source_of(data, rules):
    """(path relative to public/content, the key holding {unit id: layout} or None) of the
    layout source: the data file's `layout_source` ({path, key}, or a path), else the content
    contract's `layout.source`. None when neither names one, or it names a file outside
    public/content."""
    declared = (data or {}).get("layout_source") if isinstance(data, dict) else None
    if isinstance(declared, str):
        declared = {"path": declared}
    if not isinstance(declared, dict):
        declared = ((rules or {}).get("layout") or {}).get("source")
    if not isinstance(declared, dict) or not isinstance(declared.get("path"), str):
        return None
    path = posixpath.normpath(declared["path"].replace("\\", "/"))
    prefix = CONTENT_DIR + "/"
    if not path.startswith(prefix) or ".." in path.split("/") or not path.endswith(".json"):
        return None
    key = declared.get("key")
    return path[len(prefix):], key if isinstance(key, str) and key else None


def read_source(content_dir, data, rules):
    """({unit id: layout}, None) from the layout source under `content_dir` (a directory
    holding the public/content files), (None, None) when no source exists, or (None, why)
    when the one named cannot be read. A unit the source does not name has no entry."""
    found = source_of(data, rules)
    if not found:
        return None, None
    relative, key = found
    path = os.path.join(content_dir, *relative.split("/"))
    if not os.path.isfile(path):
        return None, None
    try:
        with open(path, encoding="utf-8") as handle:
            loaded = json.load(handle)
    except (OSError, ValueError) as exc:
        return None, f"{CONTENT_DIR}/{relative} cannot be read: {exc}"
    if key is not None and isinstance(loaded, dict) and key in loaded:
        # The layouts under their key; a file without it is keyed by unit id at its root
        # (a root key that is no unit id - `schema` - matches no unit).
        loaded = loaded.get(key)
    if not isinstance(loaded, dict):
        return None, (f"{CONTENT_DIR}/{relative}" + (f" `{key}`" if key else "")
                      + " is not an object keyed by unit id")
    return {str(k): v for k, v in loaded.items()}, None

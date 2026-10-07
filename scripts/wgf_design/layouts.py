"""How alike two content units are laid out - measured on the geometry the game builds, never
on the names of its tuning, and only where the content contract says geometry lives.

Geometry comes from a DECLARED place, nowhere else:

  - the build: each unit's own `layout` entry in the content data file
    (`public/content/units.json`; core/reference/content-sufficiency.yaml `layout.unit_key`),
    and its entry in the layout source the contract names - a JSON file under
    `public/content/` keyed by unit id (`layout.source`, or the data file's own
    `layout_source`). Any other key of a unit - a `tags` list, `parameters`, a word - is not
    geometry, so adding a list beside the layout turns nothing from unmeasured into measured.
  - the design: each unit's `parameters` (game-design `units[].parameters`, the design's place
    for a unit's layout as data).

Inside a declared layout, the geometry is its SEQUENCES: every outermost list (a track's
segments, a grid's rows, a wave list, a spawn table, a board's cells), wherever it sits and
whatever its container is called - `segments` renamed `pieces` is the same course. Each item
is compared by value (a record keeps its own field names; a number 30.0 is 30). A scalar
outside every list (a width, a par time, a flag) is tuning: the same layout at another
difficulty. A unit whose declared layout holds no list carries no geometry: it is
undetermined, never "repeated".

Two layouts' similarity is how much of the smaller one the larger one holds, in order: the
items of each sequence matched to the other's (difflib longest matching blocks), sequences
paired one to one, over the item count of the smaller layout. Appending an unrelated list
(a 40-piece `decor`) to a copy of another unit's course therefore leaves it a copy.

Used by the content-sufficiency step (scripts/wgf_sufficiency/audit.py, on the build and on the
design) and the design step's own tier check (scripts/wgf_design/content.py
`content.tier_structure`), so the build and the design are judged by one rule. A design unit
also carries the identity the design check always had - its structure, its elements and its
full parameter values - so two design units that are equal there are repeated whatever their
geometry says (never looser than a check that compared them on that alone).

What this does NOT establish: that the game builds each unit from the geometry it declares.
The play probe's survey (every unit entered through its unit link) and the develop brief's
contract - the game builds a unit from its declared `layout` at boot - are what hold that.
"""

import difflib
import hashlib
import json
import os
import posixpath

__all__ = ["TUNING", "CONTENT_DIR", "UNIT_KEY", "leaves", "sequences", "geometry",
           "design_geometry", "design_identity", "similarity", "signature", "repetition",
           "source_of", "read_source", "unit_key"]

# The placeholder a scalar number outside any list stands as in `leaves`: where it sits, not
# its value.
TUNING = "#number"
# Where a layout source may live: beside the content data file, inside the files the build
# serves.
CONTENT_DIR = "public/content"
# The key of a unit's entry in units.json that holds its layout, unless the contract names
# another (content-sufficiency.yaml `layout.unit_key`).
UNIT_KEY = "layout"


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


def _plain(value):
    """`value` with every integral float as an int, so 30.0 and 30 are one item."""
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_plain(v) for v in value]
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def _item(value):
    return json.dumps(_plain(value), sort_keys=True)


def sequences(layout):
    """The geometry of one declared layout: every outermost non-empty list in it, as a tuple of
    its items by value - container names dropped, so `segments` and `pieces` are one list."""
    found = []

    def walk(value):
        if isinstance(value, list):
            if value:
                found.append(tuple(_item(item) for item in value))
        elif isinstance(value, dict):
            for key in sorted(value, key=str):
                walk(value[key])
    walk(layout)
    return found


def unit_key(rules):
    key = ((rules or {}).get("layout") or {}).get("unit_key")
    return key if isinstance(key, str) and key else UNIT_KEY


def geometry(unit, rules=None, source=None):
    """The build unit's geometry: the sequences of its own `layout` entry (`layout.unit_key`)
    and of its entry in the layout source. Sorted, so where each list sits says nothing. Empty -
    undetermined - when neither declares a list."""
    found = sequences(unit.get(unit_key(rules)) if isinstance(unit, dict) else None)
    if source is not None:
        found += sequences(source)
    return sorted(found)


def design_geometry(parameters):
    """The design unit's geometry: the sequences of its `parameters`."""
    return sorted(sequences(parameters if isinstance(parameters, dict) else None))


def design_identity(structure, elements, parameters):
    """The design check's identity of a unit: its structure, its elements and its full
    parameter values. Two design units equal on it are one unit, whatever their geometry."""
    return (str(structure), tuple(sorted(map(str, elements or ()))),
            json.dumps(_plain(parameters if isinstance(parameters, dict) else {}),
                       sort_keys=True))


def _matched(first, second):
    return sum(block.size for block in difflib.SequenceMatcher(
        None, first, second, autojunk=False).get_matching_blocks())


def similarity(first, second):
    """How much of the smaller layout the larger holds, in order: each sequence's items matched
    to one sequence of the other (pairs one to one, the best first), over the item count of the
    smaller layout. Two empty layouts are 1.0; one empty and one not, 0.0."""
    if not first and not second:
        return 1.0
    if not first or not second:
        return 0.0
    pairs = sorted(((_matched(a, b), i, j) for i, a in enumerate(first)
                    for j, b in enumerate(second)), reverse=True)
    used_a, used_b, total = set(), set(), 0
    for matched, i, j in pairs:
        if matched and i not in used_a and j not in used_b:
            used_a.add(i)
            used_b.add(j)
            total += matched
    smaller = min(sum(len(s) for s in first), sum(len(s) for s in second))
    return total / float(smaller)


def signature(found):
    return hashlib.sha256(json.dumps(sorted(map(list, found))).encode("utf-8")).hexdigest()[:16]


def repetition(view, threshold):
    """{repeated, undetermined, worst} over `view` - units as {id, structure, combo,
    objective_kind, geometry[, identity]}.

    `repeated`: the units that repeat another: both with geometry, one wholly held by the
    other (similarity 1.0: identical, renamed, or padded with lists of its own), or the same
    structure, combination and objective kind with geometry at least `threshold` alike; or
    both with one `identity` (a design unit's structure, elements and parameter values).
    `undetermined`: the units with neither geometry nor identity - no evidence either way.
    `worst`: how many units could be repeated if every undetermined unit repeated one that is
    not yet repeated: the most the true count can be, which is what a bar is held to while any
    is undetermined."""
    measured = [u for u in view if u.get("geometry")]
    out = set()
    for i, a in enumerate(measured):
        for b in measured[i + 1:]:
            alike = similarity(a["geometry"], b["geometry"])
            # One layout wholly inside the other (identical, renamed, or padded with lists of
            # its own) is the same layout, whatever the units are called.
            same = alike >= 1.0 - 1e-9 or signature(a["geometry"]) == signature(b["geometry"])
            alike = (a.get("structure") == b.get("structure") and a.get("combo") == b.get("combo")
                     and a.get("objective_kind") == b.get("objective_kind")
                     and alike >= threshold)
            if same or alike:
                out.update((a["id"], b["id"]))
    by_identity = {}
    for unit in view:
        if unit.get("identity") is not None:
            by_identity.setdefault(unit["identity"], []).append(unit["id"])
    for ids in by_identity.values():
        if len(ids) > 1:
            out.update(ids)
    undetermined = [u["id"] for u in view
                    if not u.get("geometry") and u.get("identity") is None]
    repeated = [u["id"] for u in view if u["id"] in out]
    free = len(view) - len(repeated) - len(undetermined)
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

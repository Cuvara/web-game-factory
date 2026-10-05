"""core/reference/genre-models.yaml, for the steps that hold a build to its genre family.

A tiny loader, and nothing else. The genre model says - per family - what one unit of content
is, the axes difficulty moves on (and which of them the build must report as
`metrics.difficulty.<id>`), the shape of win and loss, and the `qa` parameters the playability
checks read. The design step, the developer brief and the tech plan read the same file; this
module is the reading the *judging* steps need:

    load()            the whole file, cached per (path, mtime) - the file is data, not code
    for_design(d)     the family block the design names in `genre.family`, or None
    axes_of(d)        the family's axes, narrowed to the ones the design declares
    qa_of(d)          the playability bars: design-depth.yaml's `playability` block with the
                      family's `qa` overrides applied, and the family's own qa keys under
                      `genre`
    implementation()  the file's `implementation` block - what the developer builds the units
                      to, and what a judging step holds the build to (`difficulty_tolerance`)

No consumer branches on a family id, and no bar is ever written here: every number comes from
core/reference/design-depth.yaml or from the family's entry. A family that says nothing about
a key leaves the depth bar standing.
"""

import os

from wgflib import build_scope, paths
from wgflib.yamllite import load_file

__all__ = ["PATH", "DEPTH_PATH", "load", "load_depth", "for_design", "family_of", "axes_of",
           "qa_of", "units_of", "implementation", "FAMILY_OVERRIDES"]

PATH = os.path.join(paths.REFERENCE, "genre-models.yaml")
DEPTH_PATH = os.path.join(paths.REFERENCE, "design-depth.yaml")

# Where a family's `qa` key, when it names one, replaces a design-depth playability bar. Every
# other qa key is a parameter of its own and reaches the checks under `genre`.
FAMILY_OVERRIDES = {
    "min_units_traversed": ("content", "min_units_traversed"),
    "endless_window_s": ("difficulty", "endless_window_s"),
}

_CACHE = {}


def _cached(path):
    """The YAML at `path`, re-read when the file changes. Raises YamlError on a broken file:
    a reference file nobody can read is a blocked step, never a defaulted bar."""
    stamp = os.stat(path).st_mtime_ns
    hit = _CACHE.get(path)
    if hit is None or hit[0] != stamp:
        hit = (stamp, load_file(path))
        _CACHE[path] = hit
    return hit[1]


def load(path=None):
    """core/reference/genre-models.yaml."""
    return _cached(path or PATH)


def load_depth(path=None):
    """core/reference/design-depth.yaml."""
    return _cached(path or DEPTH_PATH)


def implementation(models=None):
    """The file's `implementation` block: what the developer writes the units to, and what a
    judging step holds the build to.

    `difficulty_tolerance` is the one the playability step reads: how far a unit's reported
    `metrics.difficulty.<axis>` may sit from the design's value for that unit. A key this file
    does not state is absent here, never defaulted - a comparison nobody has a bar for is
    reported as unmeasured, not quietly passed.
    """
    block = (models or load()).get("implementation")
    return dict(block) if isinstance(block, dict) else {}


def family_of(design):
    """The family id the design names, or None."""
    genre = (design or {}).get("genre")
    family = (genre or {}).get("family") if isinstance(genre, dict) else None
    return str(family) if family else None


def for_design(design, models=None):
    """The family block for `design`, or None when it names no family this file knows."""
    family = family_of(design)
    if not family:
        return None
    families = (models or load()).get("families") or {}
    block = families.get(family)
    return block if isinstance(block, dict) else None


def axes_of(design, models=None):
    """The family's difficulty axes, narrowed to the ids the design declares.

    The design declares the axes (`build_spec.difficulty.axes`: id, range, relief_allowed);
    the family says which of them escalate and which the build must report. An axis the design
    does not declare is not judged - the design is what the build was asked for.
    """
    family = for_design(design, models)
    if not family:
        return []
    axes = [a for a in family.get("axes") or [] if isinstance(a, dict) and a.get("id")]
    declared = {a.get("id") for a in
                (((design or {}).get("build_spec") or {}).get("difficulty") or {}).get("axes")
                or [] if isinstance(a, dict)}
    return [a for a in axes if a["id"] in declared] if declared else axes


def units_of(design, tiers=None):
    """(the design's `build_spec.content` or None, its generation mode, its units in order).

    Without `tiers`, the MVP units: what the prototype traverse plays. With `tiers` - the
    design tiers the run builds (wgflib.build_scope.design_tiers) - every unit of them: the
    units a build at the run's quality tier carries, so a release unit is a design unit.
    The order is `build_spec.progression.unit_sequence` when the design states one, else the
    units' own `index`.
    """
    spec = (design or {}).get("build_spec") or {}
    content = spec.get("content")
    if not isinstance(content, dict):
        return None, None, []
    mode = str(((content.get("generation") or {}).get("mode") or "")).strip() or None
    if tiers is not None:
        return content, mode, build_scope.units(design, tiers)
    listed = [u for u in content.get("units") or [] if isinstance(u, dict)]
    units = [u for u in listed if u.get("tier") == "mvp"] or listed
    sequence = ((spec.get("progression") or {}).get("unit_sequence")) or []
    if sequence:
        by_id = {u.get("id"): u for u in units}
        ordered = [by_id[uid] for uid in sequence if uid in by_id]
        if ordered:
            return content, mode, ordered
    return content, mode, sorted(units, key=lambda u: u.get("index") or 0)


def qa_of(design, models=None, depth=None):
    """The playability bars for this design: design-depth.yaml's `playability` block with the
    family's `qa` overrides applied, plus the family's own qa parameters under `genre`.

    Always a dict with the depth block's sections, so a caller reads one shape whether or not
    the design names a family.
    """
    bars = (load_depth() if depth is None else depth).get("playability") or {}
    merged = {key: dict(value) if isinstance(value, dict) else value
              for key, value in bars.items()}
    family = for_design(design, models) or {}
    qa = {k: v for k, v in (family.get("qa") or {}).items()}
    for key, (section, bar) in FAMILY_OVERRIDES.items():
        if key in qa and isinstance(merged.get(section), dict):
            merged[section][bar] = qa[key]
    merged["genre"] = qa
    return merged

"""Distinct climax art: every climax unit's antagonist or set piece has its own drawing.

A release whose four bosses were one drawing, tinted per world, reads as one boss four times
(docs/quality-gap-audit-2026-10.md). The bar is data - core/reference/quality-benchmark.yaml
`presentation.assets.distinct_climax_art`, per quality tier - and this is the check that
reads it, in the assets step, where the art is planned and made:

    plan    the design's climax units (build_spec.content.units[], `purpose: climax`, any tier
            but `optional`) and the drawings each names in `art` (game-design 1.11.0): an
            asset id of one drawing, or a variant id (`boss-2`) of a counted asset
    judge   per climax unit, against the items the pipeline made:
              climax-art-unassigned  warning  the unit names no drawing that resolves, so
                                              nothing can be checked (a design gap: the
                                              assets step cannot invent what a unit is)
              climax-art-shared      error    every drawing the unit names is also another
                                              climax unit's; or one of its own drawings is
                                              the same file as, or has the silhouette of
                                              (a recolour), another climax unit's drawing

"Same silhouette" is asset-quality.yaml `variants.min_silhouette_distance` - the bar a
counted asset's variants are already held to - for SVG and PNG; a model or any other file
is compared by its bytes. A placeholder is not compared: stand-ins look alike by design.
"""

import hashlib
import os

from wgflib import paths
from wgflib.yamllite import YamlError, load_file

from . import quality as quality_mod

__all__ = ["BENCHMARK_PATH", "load_bar", "climax_units", "judge"]

BENCHMARK_PATH = os.path.join(paths.REFERENCE, "quality-benchmark.yaml")
# Unit tiers a release ships (game-design $defs.tier): `optional` is committed to nothing.
SHIPPED_TIERS = ("mvp", "post-mvp")
SILHOUETTE_FORMATS = ("svg", "png")


def load_bar(tier, path=None):
    """The `distinct_climax_art` bar at `tier`: True, False, or None when the benchmark
    states none for the tier (`mvp` takes its bars from the genre models) or is unreadable."""
    try:
        document = load_file(path or BENCHMARK_PATH) or {}
    except (OSError, YamlError):
        return None
    bar = (((document.get("presentation") or {}).get("assets") or {})
           .get("distinct_climax_art") or {})
    value = bar.get(tier) if isinstance(bar, dict) else None
    return value if isinstance(value, bool) else None


def climax_units(design):
    """[{"unit", "index", "art"}] of the design's climax units, in their order."""
    spec = design.get("build_spec") if isinstance(design.get("build_spec"), dict) else {}
    content = spec.get("content") if isinstance(spec.get("content"), dict) else {}
    out = []
    for unit in content.get("units") or []:
        if not isinstance(unit, dict) or unit.get("purpose") != "climax":
            continue
        if unit.get("tier") not in SHIPPED_TIERS:
            continue
        art = [a for a in unit.get("art") or [] if isinstance(a, str) and a]
        out.append({"unit": str(unit.get("id") or f"unit-{unit.get('index')}"),
                    "index": unit.get("index") if isinstance(unit.get("index"), int) else 0,
                    "art": art})
    return sorted(out, key=lambda u: u["index"])


def _drawings(items):
    """{drawing id: (item, repository-relative path or None, bytes or None)}: an asset of
    one drawing by its id, a counted asset's drawings by their variant ids."""
    out = {}
    for item in items:
        payload = list(item.payload or [])
        variants = list(item.variants or [])
        ids = item.req.variant_ids()
        if ids:
            files = dict(zip(variants, payload)) if len(payload) >= len(variants) else {}
            for vid in ids:
                relative, data = files.get(vid, (None, None))
                out[vid] = (item, relative, data)
        else:
            relative, data = payload[0] if payload else (None, None)
            out[item.req.id] = (item, relative, data)
    return out


def _fmt(relative):
    return (relative or "").rsplit(".", 1)[-1].lower()


def _same(a, b, bars):
    """Why drawing a and drawing b are one drawing ("" when they are not)."""
    (_ia, ra, da), (_ib, rb, db) = a, b
    if da is None or db is None:
        return ""
    if hashlib.sha256(da).digest() == hashlib.sha256(db).digest():
        return "the same file"
    fa, fb = _fmt(ra), _fmt(rb)
    if fa in SILHOUETTE_FORMATS and fb in SILHOUETTE_FORMATS:
        found = quality_mod.variants_distinct([("a", da, fa), ("b", db, fb)], bars)
        if found is not None:
            distance = next(iter(found[1]["pairs"].values()), None)
            if distance is not None and distance < found[1]["bar"]:
                return (f"the same silhouette (they differ by {distance:.2f}; the bar is "
                        f"{found[1]['bar']:.2f}) - a recolour of one drawing")
    return ""


def judge(units, items, bars=None):
    """[(item or None, code, severity, message)] for the climax units against the items
    the pipeline made. An item-less finding is about the design, not a file."""
    if not units:
        return []
    bars = bars or quality_mod.load_bars()
    drawings = _drawings(items)
    counted = {item.req.id for item in items if item.req.variant_ids()}
    findings, resolved = [], {}
    for unit in units:
        named, unresolved = [], []
        for art in unit["art"]:
            (named if art in drawings else unresolved).append(art)
        resolved[unit["unit"]] = named
        if not named:
            why = ("names no art" if not unit["art"] else
                   "names " + ", ".join(unresolved) + ", which "
                   + ("is a counted asset - name one of its variant ids"
                      if all(a in counted for a in unresolved) else "no asset or variant has"))
            findings.append((None, "climax-art-unassigned", "warning",
                             f"climax unit {unit['unit']} {why}: its antagonist or set piece "
                             f"cannot be checked for distinct art (build_spec.content.units[]"
                             f".art)"))
    users = {}
    for unit in units:
        for art in resolved[unit["unit"]]:
            users.setdefault(art, []).append(unit["unit"])
    own = {u: [a for a in arts if len(users[a]) == 1] for u, arts in resolved.items()}
    for unit in units:
        name = unit["unit"]
        if resolved[name] and not own[name]:
            shared = resolved[name][0]
            others = [u for u in users[shared] if u != name]
            findings.append((drawings[shared][0], "climax-art-shared", "error",
                             f"climax unit {name} is drawn with {shared}, which climax "
                             f"unit(s) {', '.join(others)} use too: each climax unit's "
                             f"antagonist or set piece has its own drawing or model "
                             f"(distinct_climax_art)"))
    # Each unit's own drawings against every earlier unit's: one recoloured file is one.
    seen = []
    for unit in units:
        name = unit["unit"]
        for art in own[name]:
            mine = drawings[art]
            if mine[0].data.get("placeholder") or mine[2] is None:
                continue
            for other_unit, other_art in seen:
                theirs = drawings[other_art]
                why = _same(theirs, mine, bars)
                if why:
                    findings.append((mine[0], "climax-art-shared", "error",
                                     f"{art} (climax unit {name}) is {why} of {other_art} "
                                     f"(climax unit {other_unit}): each climax unit's "
                                     f"antagonist or set piece has its own drawing or model "
                                     f"(distinct_climax_art)"))
                    break
        seen.extend((name, art) for art in own[name]
                    if not drawings[art][0].data.get("placeholder")
                    and drawings[art][2] is not None)
    return findings

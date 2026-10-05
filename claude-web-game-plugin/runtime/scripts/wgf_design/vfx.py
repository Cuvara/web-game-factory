"""The visual effect contract of a design: build_spec.vfx against core/reference/vfx.yaml.

`implied(design)` is the interaction kinds the design has - a collectible asset or a collect
mechanic implies `pickup`, a threat implies `impact`, a gate implies `checkpoint`, a win
implies `goal`, a lose implies `fail`, steering or racing implies `trail` - read from the
build_spec's asset roles, its MVP mechanics as lexicon ids (core/reference/mechanic-lexicon.yaml)
and its experience contract. `view(design, strategy)` is what the consistency rule
`vfx_covers_interactions` reads: at a quality tier the contract binds, every implied kind
without an effect, every cap above its kind's ceiling, and every effect naming an asset or an
audio cue the design does not have. `seed(spec, ...)` is the built-in author's block: one
effect per implied kind, from the contract's defaults.
"""

import os

from wgflib import build_scope, mechanics, paths
from wgflib.yamllite import load_file

__all__ = ["VFX_PATH", "load", "implied", "view", "seed"]

VFX_PATH = os.path.join(paths.REFERENCE, "vfx.yaml")


def load(path=None):
    return load_file(path or VFX_PATH) or {}


def _mechanic_ids(spec, lexicon):
    found = set()
    for m in spec.get("mechanics") or []:
        if not isinstance(m, dict) or m.get("tier") not in (None, "mvp"):
            continue
        found |= mechanics.mechanic_ids(m, lexicon)
        found |= mechanics.ids_in(" ".join([str(m.get("description") or "")]
                                           + [str(r) for r in m.get("rules") or []]), lexicon)
    return found


def implied(design, data=None, lexicon=None):
    """{kind: reason} - the interaction kinds the design has, each with what implies it."""
    data = data if data is not None else load()
    lexicon = lexicon if lexicon is not None else mechanics.load()
    spec = (design or {}).get("build_spec") or {}
    roles = {a.get("role") for a in spec.get("assets") or []
             if isinstance(a, dict) and a.get("tier") in (None, "mvp")}
    ids = _mechanic_ids(spec, lexicon)
    experience = spec.get("experience") or {}
    out = {}
    for kind, entry in (data.get("kinds") or {}).items():
        rule = (entry or {}).get("implied_by") or {}
        why = ([f"asset role {r}" for r in rule.get("roles") or [] if r in roles]
               + [f"mechanic {m}" for m in rule.get("mechanics") or [] if m in ids]
               + [f"experience.{e}" for e in rule.get("experience") or []
                  if isinstance(experience.get(e), dict)])
        if why:
            out[kind] = why[0]
    return out


def view(design, strategy=None, data=None, lexicon=None):
    """The consistency rule's reading: {"tier", "binds", "implied", "declared", "problems"}.
    `problems` is [] at a tier the contract does not bind."""
    data = data if data is not None else load()
    spec = (design or {}).get("build_spec") or {}
    tier = build_scope.quality_tier(design, strategy)[0]
    binds = tier in (data.get("binds_at_tiers") or [])
    wanted = implied(design, data, lexicon)
    effects = [e for e in ((spec.get("vfx") or {}).get("effects") or []) if isinstance(e, dict)]
    declared = sorted({e.get("kind") for e in effects if e.get("kind")})
    problems = []
    if binds:
        kinds = data.get("kinds") or {}
        problems += [f"no build_spec.vfx effect of kind {kind} ({why})"
                     for kind, why in sorted(wanted.items()) if kind not in declared]
        assets = {a.get("id") for a in spec.get("assets") or [] if isinstance(a, dict)}
        audio = {a.get("id") for a in spec.get("audio") or [] if isinstance(a, dict)}
        for e in effects:
            ceiling = (kinds.get(e.get("kind")) or {}).get("max_screen_share")
            cap = e.get("max_screen_share")
            if isinstance(ceiling, (int, float)) and isinstance(cap, (int, float)) \
                    and cap > ceiling:
                problems.append(f"vfx {e.get('id')}: max_screen_share {cap:g} is above the "
                                f"{e.get('kind')} ceiling {ceiling:g}")
            if e.get("asset") and e["asset"] not in assets:
                problems.append(f"vfx {e.get('id')}: asset {e['asset']!r} is not a "
                                f"build_spec.assets id")
            if e.get("audio") and e["audio"] not in audio:
                problems.append(f"vfx {e.get('id')}: audio {e['audio']!r} is not a "
                                f"build_spec.audio id")
    return {"tier": tier, "binds": binds, "implied": sorted(wanted), "declared": declared,
            "problems": problems}


def seed(design, data=None, lexicon=None):
    """A build_spec.vfx block with one effect per implied kind, from the contract's defaults
    (the effect named in the identity's palette accents by the author who refines it), or None
    when the design implies none. Effects of a role-vfx asset name it."""
    data = data if data is not None else load()
    wanted = implied(design, data, lexicon)
    if not wanted:
        return None
    kinds = data.get("kinds") or {}
    spec = (design or {}).get("build_spec") or {}
    vfx_assets = [a.get("id") for a in spec.get("assets") or []
                  if isinstance(a, dict) and a.get("role") == "vfx" and a.get("id")]
    effects = []
    for kind in kinds:
        if kind not in wanted:
            continue
        entry = kinds[kind] or {}
        effect = {"id": f"{kind}-fx", "kind": kind, "trigger": f"{entry.get('label')} "
                  f"({wanted[kind]})", "effect": " ".join(str(entry.get("effect") or
                                                              entry.get("label")).split()),
                  "duration_ms": entry.get("duration_ms", 400),
                  "max_screen_share": entry.get("max_screen_share", 0.1), "tier": "mvp"}
        if kind in ("pickup", "impact", "goal") and vfx_assets:
            effect["asset"] = vfx_assets[0]
        effects.append(effect)
    return {"effects": effects}

"""Art style families: which material language, glow and worked example a look calls for.

`core/reference/art-style-families.yaml` groups visual identities into families (neon /
emissive, lit stylized, toon). A model request is shown the example of its identity's family
- never one game's car for every look - and a spec is refused when it glows more than the
family allows.

    family(visual_identity)            -> (family id, entry, basis)
    example(entry, requirement)        -> (example id, spec, matched)
    style_problems(spec, entry)        -> [problem, ...]  (emissive cap, emissive share)
"""

import os
import re

from wgflib import paths
from wgflib.yamllite import load_file

__all__ = ["FAMILIES_PATH", "load", "family", "kit_family", "example", "style_problems",
           "request_block"]

FAMILIES_PATH = os.path.join(paths.REFERENCE, "art-style-families.yaml")
_WORD = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
# Below this an emissive material does not glow: a hint of colour in the shade.
_GLOWS = 0.05
_CACHE = {}


def load(path=None):
    path = path or FAMILIES_PATH
    if path not in _CACHE:
        _CACHE[path] = load_file(path) or {}
    return _CACHE[path]


def _words(text):
    found = set()
    for word in _WORD.findall(str(text or "").lower()):
        found.add(word)
        found.update(word.split("-"))
    return found


def kit_family(kit_id, data=None):
    """The family an identity kit belongs to, or None."""
    data = data or load()
    return (data.get("kits") or {}).get(kit_id)


def family(look, data=None):
    """(family id, entry, basis) for a visual identity: its own `style_family` when it names a
    known one (basis `stated`), else the family whose words its concept, shape language,
    texture and motion use most (basis `words`), else the file's default (basis `default`)."""
    data = data or load()
    families = data.get("families") or {}
    look = look if isinstance(look, dict) else {}
    stated = look.get("style_family")
    if isinstance(stated, str) and stated in families:
        return stated, families[stated], "stated"
    said = set()
    for key in ("concept", "shape_language", "texture", "motion"):
        said |= _words(look.get(key))
    best, score = None, 0
    for fid, entry in families.items():
        hits = len(said & {str(w).lower() for w in entry.get("words") or []})
        if hits > score:
            best, score = fid, hits
    if best:
        return best, families[best], "words"
    fid = data.get("default")
    return fid, families.get(fid) or {}, "default"


def example(entry, requirement=None):
    """(example id, spec, matched): the family's example whose `fits` words the requirement
    names (matched True), else its first. (None, None, False) for a family without examples."""
    examples = [e for e in (entry or {}).get("examples") or [] if isinstance(e, dict)]
    if not examples:
        return None, None, False
    req = requirement if isinstance(requirement, dict) else {}
    said = set()
    for key in ("id", "role", "description", "readability", "label"):
        said |= _words(req.get(key))
    for candidate in examples:
        if said & {str(w).lower() for w in candidate.get("fits") or []}:
            return candidate.get("id"), candidate.get("spec"), True
    return examples[0].get("id"), examples[0].get("spec"), False


def style_problems(spec, entry):
    """What a spec breaks of its family's material rules: a material brighter than
    `max_emissive_strength`, or more of the parts glowing than `max_emissive_part_share`."""
    rules = (entry or {}).get("materials") or {}
    if not isinstance(spec, dict) or not rules:
        return []
    problems = []
    cap = rules.get("max_emissive_strength")
    glowing = set()
    for material in spec.get("materials") or []:
        if not isinstance(material, dict) or not material.get("emissive"):
            continue
        strength = material.get("emissive_strength", 1.0)
        if not isinstance(strength, (int, float)):
            continue
        if strength > _GLOWS:
            glowing.add(material.get("id"))
        if isinstance(cap, (int, float)) and strength > cap:
            problems.append(f"style: material {material.get('id')!r} emits at {strength:g}; this "
                            f"look's family allows at most {cap:g} - give it colour, not light")
    share = rules.get("max_emissive_part_share")
    parts = [p for p in spec.get("parts") or [] if isinstance(p, dict)]
    count = lambda p: 2 if p.get("mirror") else 1  # noqa: E731 - a mirrored part is two
    total = sum(count(p) for p in parts)
    lit = sum(count(p) for p in parts if p.get("material") in glowing)
    if isinstance(share, (int, float)) and total and lit / total > share + 1e-9:
        problems.append(f"style: {lit} of {total} parts glow; this look's family allows at most "
                        f"{share:.0%} - only the light sources and the edges that matter emit")
    return problems


def request_block(fid, entry, basis):
    """What a model request carries of the family: id, how it was chosen, and its rules."""
    return {"id": fid, "basis": basis, "label": (entry or {}).get("label"),
            "summary": (entry or {}).get("summary"),
            "materials": (entry or {}).get("materials") or {},
            "lighting": (entry or {}).get("lighting") or {},
            "craft": "core/craft/production-art-3d.md, section 2a (" + str(fid) + ")"}

"""The production art and UI a design states: what a finished game is held to.

A design that says nothing about how its player, threats and goals look gets a game that draws
them as a cube and two spheres, and a UI of browser-default buttons. game-design 1.6.0 lets a
design state it, and `check` makes the design module require it, by reference and by number:

  * every MVP visual asset requirement says what it is to the player (`role`) and whether it
    is 2D or 3D (`dimension`);
  * every MVP asset of an entity role (the play probe's player, threat, goal, target,
    projectile, collectible, hazard) states what a first-time player must recognise in it
    (`readability`);
  * every readable entity role the design implies - its own mechanics and its experience
    contract's win and lose name it (core/reference/experience-rules.yaml
    `production_art.role_cues`) - has an MVP asset of that role with a readability line;
  * a 3D design's characters (`character_roles_3d`) are models built in 3D;
  * the typography's faces are an MVP asset of role `font` - files bundled with the game;
  * `visual_identity.ui` exists, names palette tokens for its button and surface, sets the
    button's text on its fill at `ui.min_contrast` or better, keeps every interactive element
    at least `ui.min_target_px` on a phone, and its body and HUD text at least
    `ui.min_font_px`.

`visual_identity.primitive_style` (with a reason) waives the readability requirements: the art
direction is geometric on purpose, and visual QA still judges the result. It never waives the
UI. The problems are what an author that can repair its draft is shown; each names the field to
change. core/craft/production-art-and-ui.md is the prose behind the bars.
"""

import os
import re

from wgflib import paths
from wgflib.yamllite import load_file

from .experience import load_rules

__all__ = ["VISUAL_QUALITY_PATH", "readable_roles", "implied_roles", "contrast", "check"]

VISUAL_QUALITY_PATH = os.path.join(paths.REFERENCE, "visual-quality.yaml")

# The play probe's entity roles a player sees in the world, beyond the readable ones the
# visual gate measures: each is drawn by an asset whose readability a judge reads.
ENTITY_ROLES = ("player", "threat", "goal", "target", "projectile", "collectible", "hazard")
# Asset types that are not drawn (or not drawn by themselves).
_NOT_DRAWN = {"animation", "font", "other"}


def readable_roles(path=None):
    """The roles the player must be able to see: visual-quality.yaml's, the probe's subset."""
    data = load_file(path or VISUAL_QUALITY_PATH)
    return list((data.get("entities") or {}).get("readable_roles") or [])


def _luminance(hex_):
    channels = [int(hex_[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    r, g, b = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    """WCAG contrast ratio of two #rrggbb colours."""
    high, low = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def _contains(term, text):
    return re.search(r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9])", text) is not None


def implied_roles(design, rules=None, readable=None):
    """{role: [(where, cue)]} - the readable roles the design's own words imply."""
    rules = rules or load_rules()
    readable = readable if readable is not None else readable_roles()
    cues = (rules.get("production_art") or {}).get("role_cues") or {}
    spec = design.get("build_spec") or {}
    ex = spec.get("experience") or {}
    sources = []
    for mechanic in spec.get("mechanics") or []:
        if mechanic.get("tier") != "mvp":
            continue
        text = " ".join([mechanic.get("name") or "", mechanic.get("description") or ""]
                        + list(mechanic.get("rules") or []))
        sources.append((f"mechanic {mechanic.get('id')!r}", text.lower()))
    for key in ("win", "lose"):
        if isinstance(ex.get(key), dict):
            sources.append((f"experience.{key}", (ex[key].get("condition") or "").lower()))
    implied = {}
    for role in readable:
        for where, text in sources:
            cue = next((c for c in cues.get(role) or [] if _contains(c, text)), None)
            if cue:
                implied.setdefault(role, []).append((where, cue))
    return implied


def check(design, rules=None, readable=None):
    """Problems (strings) with the design's production art and UI. Empty means it holds."""
    rules = rules or load_rules()
    readable = readable if readable is not None else readable_roles()
    art = rules.get("production_art") or {}
    bars = rules.get("ui") or {}
    spec = design.get("build_spec") or {}
    look = spec.get("visual_identity") or {}
    dimension = (design.get("engine") or {}).get("dimension")
    primitive = isinstance(look.get("primitive_style"), dict)
    problems = []

    mvp = [a for a in spec.get("assets") or [] if a.get("tier") == "mvp"]
    for asset in mvp:
        if asset.get("type") in _NOT_DRAWN:
            continue
        missing = [key for key in ("role", "dimension") if not asset.get(key)]
        if missing:
            problems.append(f"assets.{asset.get('id')}: state its {' and '.join(missing)} - "
                            "what it is to the player, and 2d or 3d")
        if asset.get("role") in ENTITY_ROLES and not primitive \
                and not (asset.get("readability") or "").strip():
            problems.append(f"assets.{asset.get('id')}: a {asset['role']} with no readability "
                            "line - say what a first-time player must recognise in it, and at "
                            "what size or distance")

    # Fonts are production assets: bundled files, never a system fallback.
    if not any(a.get("role") == "font" or a.get("type") == "font" for a in mvp):
        problems.append("no MVP asset of role 'font': the typography's faces ship as files "
                        "(their source and licence in the asset's spec), never as a system "
                        "fallback")

    # The readable roles the design's own words imply each have an asset that draws them.
    drawn = {a.get("role") for a in mvp if (a.get("readability") or "").strip()}
    if not primitive:
        for role, sources in implied_roles(design, rules, readable).items():
            if role not in drawn:
                where, cue = sources[0]
                problems.append(f"{where} names a {role} ({cue!r}), but no MVP asset of role "
                                f"{role!r} with a readability line draws it: add one, or state "
                                "visual_identity.primitive_style if the look is geometric on "
                                "purpose")

    # A 3D game's characters are 3D models.
    if dimension == "3d":
        for asset in mvp:
            if asset.get("role") in (art.get("character_roles_3d") or []) \
                    and asset.get("type") not in _NOT_DRAWN \
                    and (asset.get("type") != "model" or asset.get("dimension") != "3d"):
                problems.append(f"assets.{asset.get('id')}: a {asset['role']} in a 3D game is a "
                                f"model with dimension 3d, not a {asset.get('type')} "
                                f"({asset.get('dimension') or 'no dimension'})")

    # The UI, as numbers and palette tokens.
    ui = look.get("ui")
    if not isinstance(ui, dict):
        problems.append("visual_identity.ui is missing: state font_px (body, hud, heading), "
                        "min_target_px, the button's fill and text palette tokens and radius, "
                        "and the surface token")
        return problems
    tokens = {p.get("token") for p in look.get("palette") or []}
    button = ui.get("button") or {}
    for where, token in (("button.fill", button.get("fill")), ("button.text", button.get("text")),
                         ("surface", ui.get("surface"))):
        if not token:
            problems.append(f"visual_identity.ui.{where} is missing: name a palette token")
        elif token not in tokens:
            problems.append(f"visual_identity.ui.{where} {token!r} is not a palette token "
                            f"({', '.join(sorted(t for t in tokens if t))})")
    hexes = {p.get("token"): p.get("hex") for p in look.get("palette") or []}
    if button.get("fill") in hexes and button.get("text") in hexes:
        ratio = contrast(hexes[button["fill"]], hexes[button["text"]])
        bar = bars.get("min_contrast", 4.5)
        if ratio < bar:
            problems.append(f"visual_identity.ui.button text {button['text']!r} on fill "
                            f"{button['fill']!r} is {ratio:.1f}:1; the bar is {bar}:1")
    floor = bars.get("min_target_px", 44)
    target = ui.get("min_target_px")
    if not isinstance(target, (int, float)):
        problems.append(f"visual_identity.ui.min_target_px is missing: at least {floor} CSS px")
    elif target < floor:
        problems.append(f"visual_identity.ui.min_target_px is {target}; the bar is {floor} CSS px")
    font_floor = bars.get("min_font_px", 14)
    fonts = ui.get("font_px") or {}
    for key in ("body", "hud"):
        value = fonts.get(key)
        if not isinstance(value, (int, float)):
            problems.append(f"visual_identity.ui.font_px.{key} is missing: at least {font_floor} px")
        elif value < font_floor:
            problems.append(f"visual_identity.ui.font_px.{key} is {value}; the bar is "
                            f"{font_floor} px")
    return problems

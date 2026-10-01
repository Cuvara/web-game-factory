"""Visual identity kits: a deliberate look, chosen rather than defaulted.

Generic UI is what a design gets when nobody decides: a system font, a purple gradient, five
evenly spread pastels, rounded cards. Each kit here is one committed direction - a dominant
ground, one or two sharp accents, a display face with character paired with a quiet body face,
a shape language, a motion rule, and the UI as numbers and palette tokens (`ui`: font sizes,
the smallest touch target, the button's fill, text and corners, the panel surface) - so two
implementers given the same kit build the same thing. A button's text token is one that reads
on its fill at 4.5:1 or better.

Faces are from the Google Fonts catalogue under the SIL Open Font License, because they ship
inside the game bundle and a portal will ask. The kit is chosen from the archetype's affinity
list by a stable digest of the title id, so a title keeps its look across re-runs, and a
workflow can pin one with `with: {identity: <id>}`.

When the strategy carries research (Research V2) that observed an art direction - a tone, a
palette class, a rendering style in the research vocabulary - the kit is chosen by how many of
those it matches (`TRAITS`), and the digest only breaks ties. The title id never overrides an
art direction research supports; it decides only what research left open.
"""

import copy
import hashlib

__all__ = ["KITS", "TRAITS", "choose", "families", "font_source", "look", "pick"]

UNIVERSAL_AVOID = [
    "System or default UI fonts (Arial, Roboto, Inter, the browser default)",
    "Purple-to-blue gradients on white",
    "Evenly weighted pastel palettes where no colour leads",
    "Rounded white cards with drop shadows as the default container",
    "Emoji as iconography",
]

KITS = {
    "neon-night": {
        "concept": "Night-time signage: a near-black ground, light that hums, and one hot accent that means 'now'.",
        "palette": [
            {"token": "ground", "hex": "#0B0B12", "role": "Background; everything sits on it"},
            {"token": "surface", "hex": "#16162A", "role": "Panels and the result card"},
            {"token": "ink", "hex": "#EDEBFF", "role": "Primary text and HUD numerals"},
            {"token": "signal", "hex": "#FF2E88", "role": "The one accent: the player, primary buttons, new best"},
            {"token": "cool", "hex": "#2EF2FF", "role": "Secondary accent: pickups, progress, links"},
            {"token": "danger", "hex": "#FFB020", "role": "Warnings and low-time states; never decorative"},
        ],
        "typography": {"display": "Unbounded (800)", "body": "Instrument Sans (500)",
                       "numeric": "JetBrains Mono (700), tabular figures",
                       "source": "Google Fonts, SIL Open Font License; subset to the locales in scope"},
        "shape_language": "Hard 2px strokes with an outer glow; pill buttons only for the single primary action, everything else square-cornered.",
        "motion": "Everything enters on the beat of a 120 ms ease-out; score changes roll; nothing bounces.",
        "texture": "Faint scanline overlay at 4% opacity on the ground only, never over text.",
        "avoid": ["Gradients inside text", "More than one glowing element per screen outside play"],
        "ui": {"font_px": {"body": 16, "hud": 20, "heading": 32}, "min_target_px": 48,
               "button": {"fill": "signal", "text": "ground", "radius_px": 28,
                          "style": "Pill for the single primary action (fill signal, ground text, outer glow); secondary buttons square-cornered with a 2px ink stroke"},
               "surface": "surface"},
    },
    "riso-arcade": {
        "concept": "Risograph print on warm paper: two misregistered inks, halftone shading and chunky type.",
        "palette": [
            {"token": "paper", "hex": "#F4EDE1", "role": "Background"},
            {"token": "ink", "hex": "#1C1A17", "role": "Text and outlines"},
            {"token": "riso-pink", "hex": "#FF48B0", "role": "Primary ink: the player, primary actions"},
            {"token": "riso-blue", "hex": "#0078BF", "role": "Second ink: world, secondary actions"},
            {"token": "overlap", "hex": "#6C3C9E", "role": "Where the two inks overlap: highlights and new best"},
            {"token": "danger", "hex": "#E3350D", "role": "Failure and warnings"},
        ],
        "typography": {"display": "Bungee (400)", "body": "Figtree (600)", "numeric": "Bungee (400)",
                       "source": "Google Fonts, SIL Open Font License"},
        "shape_language": "Thick ink outlines, shapes offset by 2px between the two inks to fake misregistration; buttons are slabs with a hard offset shadow.",
        "motion": "Stepped animation at 12 fps for UI flourishes, smooth 60 fps for play; stamps and slaps rather than fades.",
        "texture": "Halftone dot shading and a paper grain overlay.",
        "avoid": ["Soft blurred shadows", "Pure white backgrounds"],
        "ui": {"font_px": {"body": 16, "hud": 20, "heading": 32}, "min_target_px": 48,
               "button": {"fill": "riso-pink", "text": "ink", "radius_px": 4,
                          "style": "Slab with a 2px ink outline and a hard 4px offset ink shadow; pressed drops onto its shadow"},
               "surface": "paper"},
    },
    "signal-brutal": {
        "concept": "Transit-signal brutalism: flat blocks of colour, oversized numerals, information first.",
        "palette": [
            {"token": "concrete", "hex": "#D9D6CF", "role": "Background"},
            {"token": "ink", "hex": "#111111", "role": "Text, numerals, borders"},
            {"token": "signal", "hex": "#FF5B00", "role": "Primary accent: player, primary action"},
            {"token": "go", "hex": "#00A86B", "role": "Positive feedback, new best"},
            {"token": "panel", "hex": "#F2F0EA", "role": "Cards and modals"},
            {"token": "danger", "hex": "#D7263D", "role": "Failure"},
        ],
        "typography": {"display": "Archivo Black (400)", "body": "Archivo (500)", "numeric": "Archivo Black, tabular",
                       "source": "Google Fonts, SIL Open Font License"},
        "shape_language": "Rectangles only; 3px black borders; numerals set enormous and cropped by the viewport edge.",
        "motion": "Hard cuts and 80 ms slides on one axis; no easing curves longer than 150 ms.",
        "texture": "None. Flat colour is the point.",
        "avoid": ["Rounded corners", "Glow effects"],
        "ui": {"font_px": {"body": 16, "hud": 20, "heading": 32}, "min_target_px": 48,
               "button": {"fill": "signal", "text": "ink", "radius_px": 0,
                          "style": "Flat rectangle with a 3px ink border; pressed inverts to ink fill with panel text"},
               "surface": "panel"},
    },
    "paper-diorama": {
        "concept": "Layered cut paper lit from one side: soft depth, crisp edges, handmade warmth.",
        "palette": [
            {"token": "backdrop", "hex": "#2B3A55", "role": "Background layer"},
            {"token": "paper", "hex": "#F7F1E3", "role": "Panels and cards"},
            {"token": "ink", "hex": "#26211C", "role": "Text"},
            {"token": "marigold", "hex": "#F2A900", "role": "Primary accent: rewards, primary actions"},
            {"token": "coral", "hex": "#E4572E", "role": "Secondary accent"},
            {"token": "sage", "hex": "#7FB685", "role": "Positive feedback"},
        ],
        "typography": {"display": "Fraunces (800, soft)", "body": "Commissioner (500)", "numeric": "Commissioner (700), tabular",
                       "source": "Google Fonts, SIL Open Font License"},
        "shape_language": "Irregular cut-paper edges on panels, each layer casting a short hard shadow down-right.",
        "motion": "Layers slide in with slight parallax; rewards pop up like a pop-up book (scale from a hinge).",
        "texture": "Paper fibre overlay on every paper surface.",
        "avoid": ["Photographic textures", "Neon glow"],
        "ui": {"font_px": {"body": 16, "hud": 20, "heading": 32}, "min_target_px": 48,
               "button": {"fill": "marigold", "text": "ink", "radius_px": 6,
                          "style": "Cut-paper tab with an irregular edge and a short hard shadow down-right; pressed flattens the shadow"},
               "surface": "paper"},
    },
    "lacquer-brass": {
        "concept": "A lacquered game box: deep red-black lacquer, brass fittings, ivory type.",
        "palette": [
            {"token": "lacquer", "hex": "#1E0E0E", "role": "Background"},
            {"token": "cinnabar", "hex": "#9E1B1B", "role": "Panels"},
            {"token": "brass", "hex": "#C9A227", "role": "Primary accent: borders, primary action, stars"},
            {"token": "ivory", "hex": "#F3E9D2", "role": "Text"},
            {"token": "jade", "hex": "#2E8B6E", "role": "Positive feedback"},
            {"token": "ember", "hex": "#FF7A1A", "role": "Warnings"},
        ],
        "typography": {"display": "Cinzel Decorative (700)", "body": "Alegreya Sans (500)", "numeric": "Alegreya Sans SC (800)",
                       "source": "Google Fonts, SIL Open Font License"},
        "shape_language": "Bevelled brass frames with corner ornaments on modals only; the play area stays clean.",
        "motion": "Weighty: 200 ms ease-in-out, a small overshoot on stamps; brass glints sweep across on rewards.",
        "texture": "Subtle lacquer sheen gradient on panels.",
        "avoid": ["Flat pastel buttons", "Thin hairline type on dark ground"],
        "ui": {"font_px": {"body": 16, "hud": 20, "heading": 32}, "min_target_px": 48,
               "button": {"fill": "brass", "text": "lacquer", "radius_px": 2,
                          "style": "Bevelled brass plate with lacquer text; pressed sinks the bevel and glints"},
               "surface": "cinnabar"},
    },
    "solar-bleach": {
        "concept": "Sun-bleached desert modernism: pale sand, hard noon shadows, one saturated sky colour.",
        "palette": [
            {"token": "sand", "hex": "#EFE3CF", "role": "Background and ground plane"},
            {"token": "shadow", "hex": "#6B4E3D", "role": "Shadows and outlines"},
            {"token": "ink", "hex": "#2A1E17", "role": "Text"},
            {"token": "sky", "hex": "#1F7AE0", "role": "Primary accent: player, primary action"},
            {"token": "terracotta", "hex": "#D2643C", "role": "Secondary accent: targets"},
            {"token": "danger", "hex": "#C8102E", "role": "Failure, low time"},
        ],
        "typography": {"display": "Syne (800)", "body": "Manrope (600)", "numeric": "Syne Mono (400)",
                       "source": "Google Fonts, SIL Open Font License"},
        "shape_language": "Monolithic forms with long hard shadows; UI plates are sand slabs with a single terracotta edge.",
        "motion": "Unhurried 180 ms eases for UI; the world never shakes, the light flares instead.",
        "texture": "Fine grain noise; flat-shaded geometry, no textures on meshes.",
        "avoid": ["Realistic PBR materials", "Blue-grey 'tech' UI"],
        "ui": {"font_px": {"body": 16, "hud": 20, "heading": 32}, "min_target_px": 48,
               "button": {"fill": "ink", "text": "sand", "radius_px": 4,
                          "style": "Ink slab with a 4px sky edge along the bottom and a long hard shadow; pressed shortens the shadow"},
               "surface": "sand"},
    },
}


# What each kit is, in research-vocabulary terms (core/reference/research-vocabulary.yaml:
# art_tones, art_palettes, art_renderings).
TRAITS = {
    "neon-night": {"tone": ["neon", "dark"], "palette": ["dark-glow", "saturated"],
                   "rendering": ["vector-flat"]},
    "riso-arcade": {"tone": ["retro", "bold", "cute"], "palette": ["saturated", "warm-paper"],
                    "rendering": ["hand-drawn", "pixel"]},
    "signal-brutal": {"tone": ["bold", "minimal", "neutral"],
                      "palette": ["monochrome-accent", "saturated"],
                      "rendering": ["vector-flat"]},
    "paper-diorama": {"tone": ["cozy", "cute"], "palette": ["pastel", "warm-paper", "muted"],
                      "rendering": ["hand-drawn", "low-poly"]},
    "lacquer-brass": {"tone": ["dark", "retro"], "palette": ["muted", "dark-glow"],
                      "rendering": ["stylized-3d", "low-poly"]},
    "solar-bleach": {"tone": ["minimal", "neutral"], "palette": ["muted", "pastel"],
                     "rendering": ["low-poly", "vector-flat"]},
}


def _digest_pick(title_id, candidates):
    digest = hashlib.sha256((title_id or "").encode("utf-8")).digest()
    return candidates[digest[0] % len(candidates)]


def pick(title_id, affinity, pinned=None, art=None):
    """(kit id, basis, matched): which kit, by which rule, matching which research values.

    `art`: {"tone": id, "palette": id, "rendering": id}, the values research supports (any
    may be missing). With at least one, the kits matching most of them win - preferring the
    archetype's affinity list when one of its kits matches at all - and the title digest only
    breaks a tie (basis `research`). Without one, the digest picks within the affinity list
    (basis `title-digest`). A pin overrides both (basis `pinned`)."""
    art = {k: v for k, v in (art or {}).items() if isinstance(v, str) and v}
    if pinned:
        if pinned not in KITS:
            raise KeyError(f"unknown identity kit {pinned!r}; known: {', '.join(sorted(KITS))}")
        return pinned, "pinned", []
    candidates = [k for k in affinity if k in KITS] or sorted(KITS)

    def score(kit):
        return sum(1 for key, value in art.items() if value in TRAITS[kit].get(key, []))
    if art:
        if max(score(k) for k in candidates) == 0:
            candidates = sorted(KITS)
        best = max(score(k) for k in candidates)
        if best > 0:
            kit_id = _digest_pick(title_id, [k for k in candidates if score(k) == best])
            matched = sorted(f"{key}={value}" for key, value in art.items()
                             if value in TRAITS[kit_id].get(key, []))
            return kit_id, "research", matched
    return _digest_pick(title_id, candidates), "title-digest", []


def choose(title_id, affinity, pinned=None, art=None):
    """Return (kit_id, kit dict with the universal avoid list applied). See `pick`."""
    kit_id = pick(title_id, affinity, pinned, art)[0]
    return kit_id, look(kit_id)


def look(kit_id):
    """The kit as a design carries it, with the universal avoid list applied."""
    identity = copy.deepcopy(KITS[kit_id])
    identity["avoid"] += UNIVERSAL_AVOID
    return identity


def families(typography):
    """The distinct font families a typography names, in order: 'Unbounded (800)' -> 'Unbounded'."""
    found = []
    for key in ("display", "body", "numeric"):
        face = (typography or {}).get(key) or ""
        family = face.split("(")[0].split(",")[0].strip()
        if family and family not in found:
            found.append(family)
    return found


def font_source(family):
    """Where a family's files and licence are: the Google Fonts repository's OFL directory."""
    return f"https://github.com/google/fonts/tree/main/ofl/{family.lower().replace(' ', '')}"

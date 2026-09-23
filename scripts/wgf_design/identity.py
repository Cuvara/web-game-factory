"""Visual identity kits: a deliberate look, chosen rather than defaulted.

Generic UI is what a design gets when nobody decides: a system font, a purple gradient, five
evenly spread pastels, rounded cards. Each kit here is one committed direction - a dominant
ground, one or two sharp accents, a display face with character paired with a quiet body face,
a shape language and a motion rule - so two implementers given the same kit build the same
thing.

Faces are from the Google Fonts catalogue under the SIL Open Font License, because they ship
inside the game bundle and a portal will ask. The kit is chosen from the archetype's affinity
list by a stable digest of the title id, so a title keeps its look across re-runs, and a
workflow can pin one with `with: {identity: <id>}`.
"""

import hashlib

__all__ = ["KITS", "choose"]

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
    },
}


def choose(title_id, affinity, pinned=None):
    """Return (kit_id, kit dict with the universal avoid list applied)."""
    if pinned:
        if pinned not in KITS:
            raise KeyError(f"unknown identity kit {pinned!r}; known: {', '.join(sorted(KITS))}")
        kit_id = pinned
    else:
        candidates = [k for k in affinity if k in KITS] or sorted(KITS)
        digest = hashlib.sha256((title_id or "").encode("utf-8")).digest()
        kit_id = candidates[digest[0] % len(candidates)]
    kit = KITS[kit_id]
    identity = {key: (list(value) if isinstance(value, list) else
                      dict(value) if isinstance(value, dict) else value)
                for key, value in kit.items()}
    identity["palette"] = [dict(entry) for entry in kit["palette"]]
    identity["avoid"] = list(kit["avoid"]) + UNIVERSAL_AVOID
    return kit_id, identity

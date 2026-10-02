"""From a design's words to a musical brief: style, mode, key, tempo, feel.

A design does not state a tempo or a key - it states a fantasy, an art direction, an identity
kit and an audio direction ("bright, playful play loop", "intensity rises with speed"). This
module reads those words and decides, deterministically:

    style     one of STYLES - the instrumentation, drum language and arrangement habits
    mode      the scale (ionian, mixolydian, dorian, aeolian, phrygian, harmonic minor)
    key       a root pitch class, from the title id's digest within the style's comfortable
              keys, so two titles of one style do not share a key by default
    tempo     inside the style's range, nudged by energy words
    swing     the style's, nudged by "laid-back"/"bouncy"

The identity kit is the strongest single cue (a kit is a committed look, and each has a
natural sound); the design's own words then move energy, brightness and the style itself
when they name one ("synthwave", "chiptune", "orchestral"). The result is recorded on every
produced asset, so a reviewer can see why a game sounds the way it does.
"""

import hashlib
import re

__all__ = ["STYLES", "KIT_STYLE", "Brief", "brief_for"]

# Instrument names are voices.Voices methods.
STYLES = {
    "synthwave": {
        "summary": "synthwave: four-on-the-floor, pumping octave saw bass, wide saw pads, "
                   "ping-pong square arpeggios, a gliding saw lead",
        "tempo": (104, 124), "modes": {"bright": "dorian", "dark": "aeolian"},
        "swing": 0.0, "bass": "saw_bass", "chords": "pad", "arp": "square", "lead": "saw_lead",
        "sparkle": "bell", "kit": "four", "hall": 3.2, "hall_wet": 0.28, "echo": True,
        "register": (69, 86),
    },
    "chiptune": {
        "summary": "chiptune: pulse-wave lead and arpeggios, triangle bass, noise-channel drums",
        "tempo": (128, 150), "modes": {"bright": "ionian", "dark": "aeolian"},
        "swing": 0.0, "bass": "chip_bass", "chords": None, "arp": "pulse", "lead": "chip_lead",
        "sparkle": "chip_lead", "kit": "chip", "hall": 1.2, "hall_wet": 0.12, "echo": False,
        "register": (72, 88),
    },
    "toybox": {
        "summary": "playful toybox pop: marimba comping and hook, plucked bass, soft pads, "
                   "shaker and woodblock, a whistled lead",
        "tempo": (100, 118), "modes": {"bright": "ionian", "dark": "mixolydian"},
        "swing": 0.12, "bass": "pluck_bass", "chords": "mallet", "arp": None, "lead": "whistle",
        "sparkle": "bell", "kit": "toy", "hall": 2.2, "hall_wet": 0.22, "echo": True,
        "register": (72, 86), "pad": "soft_pad",
    },
    "lofi": {
        "summary": "laid-back lo-fi: swung electric-piano sevenths, round upright bass, soft "
                   "kit, a breathy lead",
        "tempo": (76, 90), "modes": {"bright": "ionian", "dark": "dorian"},
        "swing": 0.2, "bass": "upright", "chords": "epiano", "arp": None, "lead": "whistle",
        "sparkle": "bell", "kit": "soft", "hall": 2.6, "hall_wet": 0.25, "echo": True,
        "register": (67, 81), "sevenths": True,
    },
    "adventure": {
        "summary": "adventure: brass stabs, plucked-string ostinato, toms and timpani-like "
                   "kick, bells",
        "tempo": (92, 108), "modes": {"bright": "dorian", "dark": "harmonic"},
        "swing": 0.0, "bass": "upright", "chords": "brass", "arp": "pluck", "lead": "pluck",
        "sparkle": "bell", "kit": "tom", "hall": 3.4, "hall_wet": 0.3, "echo": False,
        "register": (67, 83), "pad": "soft_pad",
    },
    "electro": {
        "summary": "minimal electro: punchy kick and clap, metallic sixteenth hats, short saw "
                   "bass, square stabs",
        "tempo": (120, 128), "modes": {"bright": "dorian", "dark": "phrygian"},
        "swing": 0.0, "bass": "saw_bass", "chords": None, "arp": "square",
        "lead": "pulse_lead", "sparkle": "bell", "kit": "electro", "hall": 1.6,
        "hall_wet": 0.18, "echo": True, "register": (67, 84),
    },
}

# The sound each identity kit (wgf_design/identity.py) suggests.
KIT_STYLE = {
    "neon-night": "synthwave",
    "riso-arcade": "chiptune",
    "signal-brutal": "electro",
    "paper-diorama": "toybox",
    "lacquer-brass": "adventure",
    "solar-bleach": "lofi",
}

# Words that name a style outright, or push one.
STYLE_WORDS = {
    "synthwave": {"synthwave", "neon", "retrowave", "outrun", "cyber", "cyberpunk", "space",
                  "galaxy", "asteroid", "sci-fi", "scifi", "laser", "night"},
    "chiptune": {"chiptune", "chip", "8-bit", "8bit", "pixel", "retro", "arcade", "riso"},
    "toybox": {"playful", "cute", "toy", "toybox", "fruit", "candy", "paper", "cozy",
               "whimsical", "garden", "bubbly", "cheerful", "kawaii", "pop"},
    "lofi": {"lofi", "lo-fi", "chill", "relax", "relaxing", "zen", "calm", "meditative",
             "desert", "cafe", "jazz", "jazzy"},
    "adventure": {"adventure", "epic", "orchestral", "fantasy", "quest", "dungeon", "kingdom",
                  "medieval", "brass", "temple", "ancient", "lacquer"},
    "electro": {"electro", "techno", "industrial", "brutal", "brutalist", "concrete",
                "signal", "glitch", "minimal"},
}
BRIGHT = {"bright", "playful", "happy", "cheerful", "sunny", "cute", "fun", "joyful",
          "bouncy", "colourful", "colorful", "upbeat", "warm", "glorious", "sweet", "light"}
DARK = {"dark", "tense", "danger", "dangerous", "menacing", "eerie", "void", "night",
        "survival", "grim", "ominous", "deep", "lonely"}
FAST = {"fast", "speed", "speeds", "race", "racing", "rush", "drive", "dash", "frantic",
        "intense", "intensity", "action", "survivable", "dodge", "flight", "thrill"}
SLOW = {"calm", "slow", "relaxed", "relax", "gentle", "chill", "zen", "cozy", "lazy",
        "peaceful", "dreamy"}

KEYS = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]
# Keys whose ranges sit well for each style's registers (pitch classes).
COMFORT = {
    "synthwave": [9, 2, 4, 7, 0, 5],
    "chiptune": [0, 7, 2, 9, 5, 4],
    "toybox": [0, 5, 7, 2, 10, 3],
    "lofi": [2, 5, 10, 3, 7, 0],
    "adventure": [2, 7, 9, 4, 0, 5],
    "electro": [9, 4, 11, 2, 7, 6],
}


def _words(*texts):
    found = set()
    for text in texts:
        found.update(re.findall(r"[a-z][a-z0-9-]*", (text or "").lower()))
    return found


class Brief:
    def __init__(self, style, mode, root, tempo, swing, energy, valence, seed, reasons):
        self.style = style
        self.mode = mode
        self.root = root
        self.tempo = tempo
        self.swing = swing
        self.energy = energy
        self.valence = valence
        self.seed = seed
        self.reasons = reasons

    @property
    def spec(self):
        return STYLES[self.style]

    def describe(self):
        return {"style": self.style, "mode": self.mode, "key": KEYS[self.root],
                "tempo_bpm": round(self.tempo, 2), "swing": self.swing,
                "energy": self.energy, "valence": self.valence,
                "summary": STYLES[self.style]["summary"], "why": self.reasons}


def _text(value):
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return " ".join(_text(v) for v in value.values())
    if isinstance(value, list):
        return " ".join(_text(v) for v in value)
    return ""


def brief_for(design, *, title_id=None):
    """The musical brief of a game design (any dict with the game-design fields)."""
    design = design or {}
    spec = design.get("build_spec") if isinstance(design.get("build_spec"), dict) else {}
    look = spec.get("visual_identity") if isinstance(spec.get("visual_identity"), dict) else {}
    kit = look.get("id") or look.get("kit")
    art = _text(design.get("art_direction"))
    if not kit:
        match = re.search(r"[Ii]dentity kit '([a-z-]+)'", art)
        kit = match.group(1) if match else None
    audio_cues = " ".join(f"{a.get('id', '')} {a.get('description', '')}"
                          for a in spec.get("audio") or [] if isinstance(a, dict)
                          and a.get("type") in ("music", "ambience"))
    words = _words(_text(design.get("audio_direction")), audio_cues,
                   _text(design.get("fantasy")), art, _text(look.get("concept")),
                   _text(look.get("motion")), _text(design.get("pillars")))
    reasons = []
    scores = {style: 0.0 for style in STYLES}
    if kit in KIT_STYLE:
        scores[KIT_STYLE[kit]] += 3.0
        reasons.append(f"identity kit {kit} -> {KIT_STYLE[kit]}")
    for style, cues in STYLE_WORDS.items():
        hits = sorted(words & cues)
        if hits:
            scores[style] += len(hits)
            reasons.append(f"{style}: {', '.join(hits)}")
    style = max(sorted(scores), key=lambda s: scores[s]) if any(scores.values()) else "toybox"
    bright, dark = len(words & BRIGHT), len(words & DARK)
    fast, slow = len(words & FAST), len(words & SLOW)
    valence = "bright" if bright > dark else "dark" if dark > bright else (
        "dark" if style in ("synthwave", "electro", "adventure") else "bright")
    energy = max(-1, min(1, fast - slow))
    reasons.append(f"valence {valence} (bright {bright}, dark {dark}); energy {energy:+d} "
                   f"(fast {fast}, slow {slow})")
    seed_text = title_id or design.get("title_id") or _text(design.get("fantasy"))[:80]
    digest = hashlib.sha256(seed_text.encode("utf-8")).digest()
    seed = int.from_bytes(digest[:4], "big")
    info = STYLES[style]
    mode = info["modes"][valence]
    keys = COMFORT[style]
    root = keys[digest[4] % len(keys)]
    lo, hi = info["tempo"]
    span = hi - lo
    tempo = lo + span * (0.5 + 0.35 * energy) + (digest[5] / 255.0 - 0.5) * span * 0.3
    swing = info["swing"]
    if words & {"bouncy", "swing", "swung", "laid-back"}:
        swing = min(0.3, swing + 0.08)
    return Brief(style, mode, root, float(round(tempo, 1)), swing, energy, valence, seed,
                 reasons)

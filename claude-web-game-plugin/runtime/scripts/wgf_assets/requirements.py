"""Which assets a game design needs, and what kind each one is.

The source is `game_design.asset_requirements`. A design without that list still gets a
manifest: a baseline derived from the design's screens, locales, audio direction and ad
placements. The baseline is deliberately a floor - a background, the UI screens the design
names, a store icon, a font, a tap sound, music when there is audio direction - and each
derived item says so in its notes, so nobody mistakes it for a designed list.

Classification resolves each requirement against the asset policy: its manifest type, its
dimension (2d or 3d), its scope tier and its intended final source. Two requirements with the
same id are a design error, not something to merge quietly - which one did the designer mean?
"""

import re

from .policy import PolicyError

__all__ = ["Requirement", "RequirementError", "inspect", "classify", "slugify"]

TIERS = ("mvp", "prototype", "production", "future")
SOURCES = ("library", "procedural", "ai-generated", "purchased", "commissioned")
MAX_EDGE = 4096

# Default pixel size of a generated image, per kind. A requirement's width/height wins.
DEFAULT_SIZE = {
    "sprite": (64, 64), "spritesheet": (64, 64), "background": (960, 540), "ui": (256, 64),
    "icon": (512, 512), "vfx": (64, 64), "texture": (256, 256),
}

_ID = re.compile(r"^[a-z][a-z0-9-]*$")
_3D_HINT = re.compile(r"\b(3d|three\.?js|low[- ]poly|voxel|polygon(al)?)\b", re.I)


class RequirementError(ValueError):
    """The design's asset requirements cannot be turned into a manifest as written."""


def slugify(text, fallback="asset"):
    slug = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    if not slug or not slug[0].isalpha():
        slug = f"{fallback}-{slug}" if slug else fallback
    return slug


class Requirement:
    """One asset the design needs, classified against the policy."""

    def __init__(self, data, *, derived=False):
        self.data = dict(data)
        self.id = data.get("id")
        self.kind = data.get("kind")
        self.label = data.get("label")
        self.tags = [str(t).lower() for t in data.get("tags") or []]
        self.scope_tier = data.get("scope_tier") or "mvp"
        self.source = data.get("source")
        self.width = data.get("width")
        self.height = data.get("height")
        self.frames = data.get("frames")
        self.platforms = list(data.get("platforms") or [])
        self.existing = data.get("existing")
        self.notes = data.get("notes")
        self.derived = derived
        # Set by classify().
        self.policy = None
        self.dimension = data.get("dimension")
        self.manifest_type = None

    @property
    def terms(self):
        """Words a library search can match on: tags, then the id and label split apart."""
        words = set(self.tags)
        words.update(w for w in re.split(r"[^a-z0-9]+", (self.id or "").lower()) if w)
        words.update(w for w in re.split(r"[^a-z0-9]+", (self.label or "").lower()) if w)
        return words

    def size(self):
        width, height = DEFAULT_SIZE.get(self.kind, (64, 64))
        return int(self.width or width), int(self.height or height)

    def generate_now(self):
        """A `future`-tier asset is recorded, not produced: nothing is waiting for it."""
        return self.scope_tier != "future"

    def __repr__(self):
        return f"Requirement({self.id!r}, {self.kind!r})"


def game_dimension(design, override=None):
    """2d or 3d for the game. An explicit setting wins; then any 3D-only kind in the
    requirements; then a 3D hint in the art direction; else 2d, the cheap default."""
    if override in ("2d", "3d"):
        return override
    for req in design.get("asset_requirements") or []:
        if req.get("dimension") == "3d" or req.get("kind") in ("model", "environment",
                                                                 "material"):
            return "3d"
    if _3D_HINT.search(design.get("art_direction") or ""):
        return "3d"
    return "2d"


def derive_baseline(design, dimension):
    """The floor of requirements for a design that lists none."""
    reqs = []

    def add(id_, kind, label, why, tier="mvp", **extra):
        reqs.append({"id": id_, "kind": kind, "label": label, "scope_tier": tier,
                     "notes": f"Derived baseline: {why}", **extra})

    if dimension == "3d":
        add("environment-main", "environment", "Main environment", "a 3D game needs a scene")
        add("model-player", "model", "Player model", "a 3D game needs a player")
        add("material-default", "material", "Default material", "shared PBR material")
        add("texture-ground", "texture", "Ground texture", "the environment's ground")
    else:
        add("background-main", "background", "Main background", "a 2D game needs a backdrop")

    screens = (design.get("ux") or {}).get("screens") or ["HUD"]
    seen = set()
    for screen in screens:
        slug = slugify(screen, "screen")
        candidate, n = f"ui-{slug}", 2
        while candidate in seen:
            candidate, n = f"ui-{slug}-{n}", n + 1
        seen.add(candidate)
        add(candidate, "ui", f"{screen} UI", f"screen '{screen}' in ux.screens")

    add("icon-app", "icon", "Store icon", "every portal listing needs an icon",
        tier="production", width=512, height=512)
    if (design.get("scope") or {}).get("locales"):
        add("font-primary", "font", "Primary font",
            "scope.locales needs a font that covers them")
    add("sfx-ui-tap", "sfx", "UI tap", "input needs audible feedback")
    if design.get("audio_direction"):
        add("music-main", "music", "Main music", "audio_direction is set")
    kinds = {p.get("kind") for p in (design.get("monetization") or {}).get("placements") or []}
    if "rewarded" in kinds:
        add("vfx-reward", "vfx", "Reward burst", "a rewarded placement needs a reward moment")
    return reqs


def classify(req, policy, dimension):
    try:
        kind = policy.kind(req.kind)
    except PolicyError as exc:
        raise RequirementError(f"asset {req.id!r}: {exc}")
    req.policy = kind
    req.manifest_type = kind.manifest_type
    if req.dimension not in ("2d", "3d"):
        req.dimension = kind.dimension if kind.dimension in ("2d", "3d") else dimension
    return req


def inspect(design, policy, *, dimension=None):
    """(requirements, game dimension) for a game design, classified.

    Raises RequirementError for a malformed list: an id that is not kebab-case, a duplicate
    id, an unknown kind, tier or source, or an image larger than MAX_EDGE."""
    game_dim = game_dimension(design, dimension)
    declared = design.get("asset_requirements")
    if declared is not None and not isinstance(declared, list):
        raise RequirementError("game_design.asset_requirements must be a list")
    derived = not declared
    raw = derive_baseline(design, game_dim) if derived else declared

    problems, seen, reqs = [], {}, []
    for index, entry in enumerate(raw):
        if not isinstance(entry, dict):
            problems.append(f"asset_requirements[{index}] is not an object")
            continue
        req = Requirement(entry, derived=derived)
        where = f"asset {req.id!r}" if req.id else f"asset_requirements[{index}]"
        if not isinstance(req.id, str) or not _ID.match(req.id):
            problems.append(f"{where}: id must be kebab-case")
            continue
        if req.id in seen:
            problems.append(f"{where}: duplicate id (also asset_requirements[{seen[req.id]}])")
            continue
        seen[req.id] = index
        if req.scope_tier not in TIERS:
            problems.append(f"{where}: unknown scope_tier {req.scope_tier!r}")
        if req.source is not None and req.source not in SOURCES:
            problems.append(f"{where}: unknown source {req.source!r}")
        for edge in ("width", "height"):
            value = entry.get(edge)
            if value is not None and (not isinstance(value, int) or not 1 <= value <= MAX_EDGE):
                problems.append(f"{where}: {edge} must be an integer in 1..{MAX_EDGE}")
        if req.existing is not None and not (isinstance(req.existing, dict)
                                             and req.existing.get("path")):
            problems.append(f"{where}: existing needs a path")
        try:
            classify(req, policy, game_dim)
        except RequirementError as exc:
            problems.append(str(exc))
            continue
        reqs.append(req)

    if problems:
        raise RequirementError("; ".join(problems))
    return reqs, game_dim

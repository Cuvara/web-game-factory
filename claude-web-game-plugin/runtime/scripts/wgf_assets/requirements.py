"""Which assets a game design needs, and what kind each one is.

The source is the design's `build_spec.assets` (game-design 1.6.0): each requirement's id,
type, tier, role, dimension, description, readability, count and spec are carried onto the
work list (`bridge`). Its `build_spec.audio` joins the same list (`bridge_audio`): music
and ambience become `music` requirements, sfx, ui and voice cues `sfx` ones (a ui cue with
the role `ui`), each keeping its trigger, whether it loops, and any length its description
states ("a 60 s loop") as the shortest the file may be. An entry of the older
`asset_requirements` list with the same id adds
what only it can say - atlas group, exact size, scale, a `model` spec, a file the design
already chose - and one that build_spec does not list is kept as well. Tiers map mvp ->
mvp, post-mvp -> production, optional -> future; only mvp (and an asset_requirements entry
of tier prototype or production) is produced now, the rest is recorded.

A design that lists no assets at all still gets a manifest: a baseline derived from the
design's screens, locales, audio direction and ad placements. The baseline is deliberately
a floor - a background, the UI screens the design names, a store icon, a font, a tap sound,
music when there is audio direction - each derived item says so in its notes, and every one
of them is a placeholder (`placeholder_only`): no library or author is asked for an asset
nobody designed.

Classification resolves each requirement against the asset policy: its manifest type, its
dimension (2d or 3d), its scope tier and its intended final source. Two requirements with the
same id are a design error, not something to merge quietly - which one did the designer mean?
"""

import re

from . import modelspec
from .policy import PolicyError

__all__ = ["Requirement", "RequirementError", "inspect", "classify", "slugify", "bridge",
           "bridge_audio", "design_kind", "spec_size", "AUDIO_KINDS"]

TIERS = ("mvp", "prototype", "production", "future")
SOURCES = ("library", "procedural", "ai-generated", "purchased", "commissioned")
MAX_EDGE = 4096
# Kinds a `model` spec may describe: the ones delivered as GLB.
MODEL_KINDS = ("model", "environment", "animation")

# Default pixel size of a generated image, per kind. A requirement's width/height wins.
DEFAULT_SIZE = {
    "sprite": (64, 64), "spritesheet": (64, 64), "background": (960, 540), "ui": (256, 64),
    "icon": (512, 512), "vfx": (64, 64), "texture": (256, 256), "tileset": (256, 256),
}
DEFAULT_TILE = 32
DEFAULT_FPS = 12
MAX_SCALE = 4

_ID = re.compile(r"^[a-z][a-z0-9-]*$")
_ANIMATION = re.compile(r"^[a-z][a-z0-9_-]*$")
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

    def __init__(self, data, *, derived=False, bridged=False):
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
        self.model = data.get("model")
        self.notes = data.get("notes")
        self.atlas = data.get("atlas")
        self.scale = data.get("scale") or 1
        self.animations = data.get("animations")
        self.tile_width = data.get("tile_width")
        self.tile_height = data.get("tile_height")
        self.derived = derived
        # A derived baseline item is always a placeholder: nobody designed it.
        self.placeholder_only = derived
        self.bridged = bridged
        # From build_spec.assets: what it is to the player, and what it must look like.
        self.role = data.get("role")
        self.description = data.get("description")
        self.readability = data.get("readability")
        self.spec = data.get("spec")
        self.count = data.get("count") if isinstance(data.get("count"), int) else 1
        self.design_type = data.get("design_type")
        self.design_tier = data.get("design_tier")
        # From build_spec.audio: when it plays, whether it loops, its shortest length.
        self.trigger = data.get("trigger")
        self.loop = bool(data.get("loop"))
        self.min_duration_s = data.get("min_duration_s")
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
        """Logical size: what the game lays out, before `scale`."""
        width, height = DEFAULT_SIZE.get(self.kind, (64, 64))
        return int(self.width or width), int(self.height or height)

    def pixel_size(self):
        """Pixel size of the file: the logical size authored at `scale` (1x, 2x, ...)."""
        width, height = self.size()
        return width * int(self.scale), height * int(self.scale)

    def tile_size(self):
        return int(self.tile_width or DEFAULT_TILE), int(self.tile_height or DEFAULT_TILE)

    def animation_specs(self, frame_names):
        """{name: {"frames": [frame name], "fps": n, "loop": bool}} for a sheet whose frames
        are `frame_names` in order. Indices and names both resolve; the default is one
        looping animation, named after the asset, over every frame."""
        declared = self.animations or {self.id: {}}
        specs = {}
        for name in sorted(declared):
            spec = declared[name] or {}
            wanted = spec.get("frames")
            if wanted is None:
                frames = list(frame_names)
            else:
                frames = [frame_names[f] if isinstance(f, int) and f < len(frame_names)
                          else f for f in wanted]
            specs[name] = {"frames": frames, "fps": spec.get("fps", DEFAULT_FPS),
                           "loop": bool(spec.get("loop", True))}
        return specs

    def generate_now(self):
        """A `future`-tier asset is recorded, not produced: nothing is waiting for it. Nor is
        a build_spec post-mvp asset: production comes after G4 passes."""
        if self.bridged and self.design_tier in ("post-mvp", "optional"):
            return False
        return self.scope_tier != "future"

    def variant_ids(self):
        """The runtime ids of the drawings a `count` > 1 requirement asks for: `<id>-1` ...
        `<id>-<count>`; [] for one drawing (the asset id itself)."""
        if self.count <= 1:
            return []
        return [f"{self.id}-{n}" for n in range(1, self.count + 1)]

    def __repr__(self):
        return f"Requirement({self.id!r}, {self.kind!r})"


def _positive_int(value, upper):
    return isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= upper


def _check_2d_fields(req, entry, where):
    """Problems with the atlas, scale, animation and tile fields of one requirement."""
    problems = []
    if req.atlas is not None and (not isinstance(req.atlas, str) or not _ID.match(req.atlas)):
        problems.append(f"{where}: atlas must be a kebab-case group id")
    if "scale" in entry and not _positive_int(entry.get("scale"), MAX_SCALE):
        problems.append(f"{where}: scale must be an integer in 1..{MAX_SCALE}")
    elif _positive_int(req.scale, MAX_SCALE):
        width, height = req.size()
        if max(width, height) * req.scale > MAX_EDGE:
            problems.append(f"{where}: {width}x{height} at {req.scale}x exceeds {MAX_EDGE} px")
    for key in ("tile_width", "tile_height"):
        if entry.get(key) is not None and not _positive_int(entry.get(key), MAX_EDGE):
            problems.append(f"{where}: {key} must be an integer in 1..{MAX_EDGE}")
    if req.animations is None:
        return problems
    if req.kind != "spritesheet":
        problems.append(f"{where}: animations apply to a spritesheet only")
        return problems
    if not isinstance(req.animations, dict) or not req.animations:
        problems.append(f"{where}: animations must be a non-empty object")
        return problems
    for name in sorted(req.animations):
        spec = req.animations[name]
        at = f"{where}: animation {name!r}"
        if not _ANIMATION.match(str(name)):
            problems.append(f"{at}: name must be lower-case letters, digits, - or _")
        if not isinstance(spec, dict):
            problems.append(f"{at} must be an object")
            continue
        frames = spec.get("frames")
        if frames is not None:
            if not isinstance(frames, list) or not frames or not all(
                    (isinstance(f, int) and not isinstance(f, bool) and f >= 0)
                    or (isinstance(f, str) and f) for f in frames):
                problems.append(f"{at}: frames must be a non-empty list of frame indices "
                                f"or names")
            elif isinstance(req.frames, int) and any(
                    isinstance(f, int) and f >= req.frames for f in frames):
                problems.append(f"{at}: a frame index is beyond the sheet's {req.frames} "
                                f"frames")
        fps = spec.get("fps")
        if fps is not None and (isinstance(fps, bool) or not isinstance(fps, (int, float))
                                or not 0 < fps <= 120):
            problems.append(f"{at}: fps must be a number in (0, 120]")
        if "loop" in spec and not isinstance(spec["loop"], bool):
            problems.append(f"{at}: loop must be true or false")
    return problems


def game_dimension(design, override=None):
    """2d or 3d for the game. An explicit setting wins; then the dimension the design's
    `engine` block declares; then any 3D-only kind in the requirements; then a 3D hint in the
    art direction; else 2d, the cheap default."""
    if override in ("2d", "3d"):
        return override
    declared = (design.get("engine") or {}).get("dimension")
    if declared in ("2d", "3d"):
        return declared
    for entry in (design.get("build_spec") or {}).get("assets") or []:
        if isinstance(entry, dict) and (entry.get("dimension") == "3d"
                                        or entry.get("type") == "model"):
            return "3d"
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


# build_spec tier -> manifest scope tier.
DESIGN_TIERS = {"mvp": "mvp", "post-mvp": "production", "optional": "future"}
_SIZE_WH = re.compile(r"\b(\d{1,4})\s*[x\u00d7]\s*(\d{1,4})\b")
_SIZE_PX = re.compile(r"\b(\d{1,4})\s*px\b", re.I)
# Kinds that are 2D images whatever the game's dimension.
FLAT_KINDS = ("sprite", "spritesheet", "background", "tileset", "ui", "icon")


def design_kind(entry, dimension):
    """The asset-policy kind of a build_spec.assets entry, from its type, role and dimension.

    A 2D spritesheet or animation becomes a `sprite`: what an author or a library supplies
    is one vector drawing, animated in code (tween, transform); the frames the spec asks
    for stay in the requirement's notes. A 2D texture is a `background`."""
    kind, role = entry.get("type"), entry.get("role")
    if dimension == "3d":
        # A backdrop MODEL (a stand silhouette, floodlight towers) is scenery Blender builds,
        # like the environment: read as a flat `background` it belonged to no author and a
        # 3D game's production gate could never be met (goalkeeper-royale, 2026-10-02).
        if kind in ("model", "other") and role not in ("ui", "icon", "font"):
            return "environment" if role in ("environment", "background") else "model"
        if kind in ("animation", "texture"):
            return kind
    if kind == "font" or role == "font":
        return "font"
    if kind == "icon" or role == "icon":
        return "icon"
    if kind == "ui" or role == "ui":
        return "ui"
    if kind == "vfx" or role == "vfx":
        return "vfx"
    if role in ("background", "environment") or kind == "texture":
        return "background"
    if kind == "model":
        return "model"
    return "sprite"


def spec_size(spec, kind):
    """(width, height) a spec line states ("128x96", "readable at 64px"), or (None, None)."""
    text = spec or ""
    match = _SIZE_WH.search(text)
    if match:
        w, h = int(match.group(1)), int(match.group(2))
        if 1 <= w <= MAX_EDGE and 1 <= h <= MAX_EDGE:
            return w, h
    match = _SIZE_PX.search(text)
    if match and kind in ("sprite", "icon", "vfx", "ui"):
        edge = int(match.group(1))
        if 1 <= edge <= MAX_EDGE:
            return edge, edge
    return None, None


def entry_dimension(entry, design):
    """The entry's own dimension, else its type's (a model is 3D), else the engine's."""
    if entry.get("dimension") in ("2d", "3d"):
        return entry["dimension"]
    if entry.get("type") == "model":
        return "3d"
    engine = design.get("engine") or {}
    if engine.get("dimension") in ("2d", "3d"):
        return engine["dimension"]
    if engine.get("type") == "threejs":
        return "3d"
    if engine.get("type") in ("pixijs", "phaserjs"):
        return "2d"
    return None


def bridge(design, game_dim):
    """Requirement dicts for build_spec.assets, enriched by asset_requirements entries of
    the same id; asset_requirements entries build_spec does not name are appended."""
    spec_assets = ((design.get("build_spec") or {}).get("assets")) or []
    legacy = [e for e in design.get("asset_requirements") or [] if isinstance(e, dict)]
    by_id = {e.get("id"): e for e in legacy}
    out, named = [], set()
    for entry in spec_assets:
        if not isinstance(entry, dict):
            out.append(entry)
            continue
        dimension = entry_dimension(entry, design) or game_dim
        kind = design_kind(entry, dimension)
        if kind in FLAT_KINDS and entry.get("dimension") not in ("2d", "3d"):
            # A HUD icon in a 3D game is still a 2D image.
            dimension = "2d"
        notes = [entry.get("spec")] if entry.get("spec") else []
        if entry.get("type") in ("spritesheet", "animation") and kind == "sprite":
            notes.append("Delivered as one vector drawing, animated in code; a frame sheet "
                         "is still owed if the spec needs one.")
        req = {"id": entry.get("id"), "kind": kind,
               "label": entry.get("description"),
               "dimension": dimension,
               "scope_tier": DESIGN_TIERS.get(entry.get("tier"), "mvp"),
               "role": entry.get("role"), "description": entry.get("description"),
               "readability": entry.get("readability"), "spec": entry.get("spec"),
               "count": entry.get("count") or 1, "design_type": entry.get("type"),
               "design_tier": entry.get("tier"),
               "notes": " ".join(notes) or None}
        width, height = spec_size(entry.get("spec"), kind)
        if width:
            req["width"], req["height"] = width, height
        extra = by_id.get(entry.get("id"))
        if extra:
            named.add(entry.get("id"))
            for key, value in extra.items():
                if key in ("id", "dimension") or value is None:
                    continue
                if key == "scope_tier" and entry.get("tier"):
                    continue
                req[key] = value
        out.append(req)
    out.extend(e for e in legacy if e.get("id") not in named)
    out.extend(bridge_audio(design, {e.get("id") for e in out if isinstance(e, dict)}))
    return out


# build_spec.audio type -> asset-policy kind, and the role the manifest records.
AUDIO_KINDS = {"music": ("music", None), "ambience": ("music", None), "sfx": ("sfx", None),
               "ui": ("sfx", "ui"), "voice": ("sfx", None)}
_SECONDS = re.compile(r"\b(\d{1,3}(?:\.\d+)?)\s*(?:s|sec|secs|seconds?)\b", re.I)


def audio_duration(text):
    """The length a description states ("a 60 s loop", "0.5 sec"), in seconds, or None."""
    match = _SECONDS.search(text or "")
    return float(match.group(1)) if match else None


def bridge_audio(design, named):
    """Requirement dicts for build_spec.audio entries whose id no other requirement uses."""
    spec_audio = ((design.get("build_spec") or {}).get("audio")) or []
    out = []
    for entry in spec_audio:
        if not isinstance(entry, dict) or entry.get("id") in named:
            continue
        kind, role = AUDIO_KINDS.get(entry.get("type"), ("sfx", None))
        notes = [f"Plays on: {entry['trigger']}." if entry.get("trigger") else None,
                 "Loops seamlessly." if entry.get("loop") else None]
        out.append({"id": entry.get("id"), "kind": kind, "label": entry.get("description"),
                    "bridged_from": "audio",
                    "scope_tier": DESIGN_TIERS.get(entry.get("tier"), "mvp"),
                    "role": role, "description": entry.get("description"),
                    "design_type": entry.get("type"), "design_tier": entry.get("tier"),
                    "trigger": entry.get("trigger"), "loop": bool(entry.get("loop")),
                    "min_duration_s": audio_duration(entry.get("description")),
                    "notes": " ".join(n for n in notes if n) or None})
    return out


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
    spec_assets = (design.get("build_spec") or {}).get("assets") \
        if isinstance(design.get("build_spec"), dict) else None
    if spec_assets is not None and not isinstance(spec_assets, list):
        raise RequirementError("game_design.build_spec.assets must be a list")
    bridged = bool(spec_assets)
    derived = not declared and not bridged
    if bridged:
        raw = bridge(design, game_dim)
    else:
        raw = derive_baseline(design, game_dim) if derived else list(declared)
        raw.extend(bridge_audio(design, {e.get("id") for e in raw if isinstance(e, dict)}))

    problems, seen, reqs = [], {}, []
    for index, entry in enumerate(raw):
        if not isinstance(entry, dict):
            problems.append(f"asset_requirements[{index}] is not an object")
            continue
        audio = entry.get("bridged_from") == "audio"
        req = Requirement(entry, derived=derived and not audio,
                          bridged=(bridged or audio) and entry.get("design_tier") is not None)
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
        problems.extend(_check_2d_fields(req, entry, where))
        if req.model is not None:
            if req.kind not in MODEL_KINDS:
                problems.append(f"{where}: model is for {', '.join(MODEL_KINDS)} "
                                f"requirements, not {req.kind!r}")
            else:
                problems.extend(f"{where}: model.{p}" for p in modelspec.validate(req.model))
                if any(isinstance(part, dict) and part.get("id") == req.id
                       for part in (req.model or {}).get("parts") or []):
                    problems.append(f"{where}: model: a part may not share the asset's id")
        try:
            classify(req, policy, game_dim)
        except RequirementError as exc:
            problems.append(str(exc))
            continue
        if req.atlas is not None and not req.policy.atlas:
            problems.append(f"{where}: a {req.kind} cannot join an atlas; only "
                            + ", ".join(sorted(k for k, v in policy.kinds.items() if v.atlas))
                            + " can")
        if (req.tile_width or req.tile_height) and not req.policy.tiles:
            problems.append(f"{where}: tile_width/tile_height apply to a tileset only")
        if req.policy.tiles:
            (w, h), (tw, th) = req.size(), req.tile_size()
            if w % tw or h % th:
                problems.append(f"{where}: {w}x{h} does not divide into {tw}x{th} tiles")
        reqs.append(req)

    if problems:
        raise RequirementError("; ".join(problems))
    return reqs, game_dim

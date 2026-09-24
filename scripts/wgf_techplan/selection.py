"""Engine selection and platform pinning. Pure functions over the inputs and core/reference.

Engine. The renderer is the design's decision, not this module's: `game_design.engine.type`
is taken as declared. The only knowledge here is the template's mapping from dimensionality
to its engine ids (2d -> pixijs, 3d -> threejs, core/artifacts/tech-plan.schema.json), used
when an older design records a dimension but no engine, or records neither and only its
asset kinds say which it is (core/reference/asset-policy.yaml `dimension`). A design that
says nothing either way is refused: guessing a renderer is exactly what G3 is there to stop.

Platforms. The strategy pins each target as `{id, profile_version, role}`. Each pin must
resolve to core/reference/platforms/<id>.yaml at that version, and becomes the template's
game.config.yaml entry `{id, profile: <id>@<version>, role}`. Required platforms come first,
because the template's primaryPlatform() is the first `role: required` entry. Nothing here
knows what any portal is; everything read is profile data.
"""

import os

from wgflib import paths
from wgflib.yamllite import load_file

__all__ = ["ENGINE_FOR_DIMENSION", "EngineError", "PlatformError", "Platform",
           "select_engine", "pin_platforms", "tightest_bundle_mb", "load_asset_kinds"]

# The template's engine ids, by dimensionality. Mirrors the tech-plan schema's engine enum.
ENGINE_FOR_DIMENSION = {"2d": "pixijs", "3d": "threejs"}
DIMENSION_FOR_ENGINE = {engine: dim for dim, engine in ENGINE_FOR_DIMENSION.items()}
ASSET_POLICY = os.path.join(paths.REFERENCE, "asset-policy.yaml")


class EngineError(ValueError):
    """The design does not say which renderer it is drawn for, or contradicts itself."""


class PlatformError(ValueError):
    """A pinned platform profile is missing, or is not at the pinned version."""


def load_asset_kinds(path=None):
    """{kind: dimension} from the asset policy; dimension is 2d, 3d or any."""
    document = load_file(path or ASSET_POLICY) or {}
    return {kind: str((spec or {}).get("dimension") or "any")
            for kind, spec in (document.get("kinds") or {}).items() if isinstance(spec, dict)}


def _asset_dimensions(design, kinds):
    """Dimensions the design's own asset lists commit to, ignoring `any`."""
    found = set()
    entries = list(design.get("asset_requirements") or [])
    entries += list((design.get("build_spec") or {}).get("assets") or [])
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        declared = entry.get("dimension")
        kind = entry.get("kind") or entry.get("type")
        dimension = declared if declared in ENGINE_FOR_DIMENSION else kinds.get(kind)
        if dimension in ENGINE_FOR_DIMENSION:
            found.add(dimension)
    return found


def select_engine(design, asset_kinds=None):
    """(engine, rationale, source) for a design. `source` says where the answer came from:
    `design.engine.type`, `design.engine.dimension`, or `design assets`."""
    engine = design.get("engine") or {}
    declared = engine.get("type")
    dimension = engine.get("dimension")
    if declared is not None and declared not in DIMENSION_FOR_ENGINE:
        raise EngineError(f"game-design engine.type {declared!r} is not one the template "
                          f"supports ({', '.join(sorted(DIMENSION_FOR_ENGINE))})")
    if dimension is not None and dimension not in ENGINE_FOR_DIMENSION:
        raise EngineError(f"game-design engine.dimension {dimension!r} is not 2d or 3d")
    if declared and dimension and DIMENSION_FOR_ENGINE[declared] != dimension:
        raise EngineError(f"game-design declares engine {declared} but dimension {dimension}; "
                          "supersede the design so the two agree")
    design_reason = (engine.get("rationale") or "").strip()

    if declared:
        rationale = (f"The design is drawn for {DIMENSION_FOR_ENGINE[declared].upper()}"
                     f" and declares {declared}. {design_reason}").strip()
        return declared, rationale, "design.engine.type"
    if dimension:
        chosen = ENGINE_FOR_DIMENSION[dimension]
        rationale = (f"The design records dimension {dimension} without an engine; the "
                     f"template's engine for {dimension} is {chosen}. {design_reason}").strip()
        return chosen, rationale, "design.engine.dimension"

    kinds = asset_kinds if asset_kinds is not None else load_asset_kinds()
    dimensions = _asset_dimensions(design, kinds)
    if len(dimensions) == 1 or "3d" in dimensions:
        # 3D-only kinds (models, environments) settle it; a 3D game may still use 2D UI
        # sprites, a 2D game never needs a model.
        dimension = "3d" if "3d" in dimensions else "2d"
        chosen = ENGINE_FOR_DIMENSION[dimension]
        rationale = (f"The design declares no engine. Its asset list commits to {dimension} "
                     f"asset kinds (core/reference/asset-policy.yaml), so the template's "
                     f"{dimension} engine, {chosen}, is selected. Record engine in a "
                     "superseding design to make this explicit.")
        return chosen, rationale, "design assets"
    raise EngineError("game-design declares no engine and no dimension, and its assets do not "
                      "say whether it is 2D or 3D; the renderer is the design's decision")


class Platform:
    __slots__ = ("id", "version", "role", "profile")

    def __init__(self, platform_id, version, role, profile):
        self.id = platform_id
        self.version = version
        self.role = role
        self.profile = profile

    @property
    def pin(self):
        return f"{self.id}@{self.version}"

    def entry(self):
        """The game.config.yaml platforms[] entry."""
        return {"id": self.id, "profile": self.pin, "role": self.role}

    def requirement(self, key):
        return ((self.profile.get("requirements") or {}).get(key))

    def blocking_assertions(self):
        return [a.get("id") for a in self.profile.get("assertions") or []
                if isinstance(a, dict) and a.get("severity") == "blocking" and a.get("id")]


def pin_platforms(strategy, directory=None):
    """The strategy's platform_set resolved against the profiles, required first."""
    directory = directory or paths.PLATFORMS
    entries = strategy.get("platform_set") or []
    if not entries:
        raise PlatformError("title-strategy has an empty platform_set; nothing to target")
    resolved, seen = [], set()
    for entry in entries:
        platform_id = entry.get("id")
        if not platform_id or platform_id in seen:
            raise PlatformError(f"title-strategy platform_set entry {entry!r} is missing an "
                                "id or repeats one")
        seen.add(platform_id)
        path = os.path.join(directory, f"{platform_id}.yaml")
        if not os.path.exists(path):
            raise PlatformError(f"no platform profile for {platform_id!r} "
                                f"({paths.display(path)})")
        profile = load_file(path) or {}
        version = str(profile.get("version"))
        pinned = str(entry.get("profile_version"))
        if version != pinned:
            raise PlatformError(f"strategy pins {platform_id}@{pinned} but the profile is "
                                f"{version}; re-pin in a superseding strategy")
        role = entry.get("role") if entry.get("role") in ("required", "optional") else "optional"
        resolved.append(Platform(platform_id, version, role, profile))
    # Stable: required first, strategy order within each role.
    return sorted(resolved, key=lambda p: 0 if p.role == "required" else 1)


def tightest_bundle_mb(platforms):
    """The smallest max_bundle_mb across required platforms (all, if none is required)."""
    pool = [p for p in platforms if p.role == "required"] or list(platforms)
    limits = [p.requirement("max_bundle_mb") for p in pool]
    limits = [value for value in limits if isinstance(value, (int, float))
              and not isinstance(value, bool)]
    return min(limits) if limits else None

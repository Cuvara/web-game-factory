"""The facts a listing is written from, and where each was read.

`extract(...)` turns the run's artifacts and the shipped bundle into one flat record
(store-listing.schema.json `facts`): the title, the objective in the player's words, the
core loop, the MVP mechanics and features, the controls per device, the genre, the visual
style, the engine, the locales, the targeted platforms, the capabilities the sdk-report saw
working, and the game's own on-screen strings. Every entry has a source in `sources`
(artifact type and JSON path, or a bundle file), so a sentence in the copy can be traced to
the field it rests on - and so a sentence that rests on nothing can be refused.

Nothing here invents: a field the design does not carry is None or empty, and the writer
says less.
"""

import json
import os
import re

from wgflib import paths
from wgflib.yamllite import YamlError, load_file

from .buildfacts import feature_decisions

__all__ = ["extract", "humanize", "genre_chain", "load_vocabulary", "VOCABULARY_PATH",
           "unit_kind_forms", "built_units"]

VOCABULARY_PATH = os.path.join(paths.REFERENCE, "research-vocabulary.yaml")
_MVP = ("mvp",)


def humanize(slug):
    """`tower-merge-rush` -> `Tower Merge Rush`."""
    words = re.split(r"[-_\s]+", str(slug or "").strip())
    return " ".join(w[:1].upper() + w[1:] for w in words if w)


def load_vocabulary(path=None):
    try:
        return load_file(path or VOCABULARY_PATH) or {}
    except (OSError, YamlError, ValueError):
        return {}


def genre_chain(genre_id, vocabulary=None):
    """[genre id, parent id, ...] from the research vocabulary, most specific first; [] when
    the id is not in the tree."""
    vocabulary = vocabulary if vocabulary is not None else load_vocabulary()
    by_id = {g.get("id"): g for g in vocabulary.get("genres") or [] if isinstance(g, dict)}
    chain, seen = [], set()
    current = genre_id
    while current in by_id and current not in seen:
        chain.append(current)
        seen.add(current)
        current = by_id[current].get("parent")
    return chain


def genre_label(genre_id, vocabulary=None):
    vocabulary = vocabulary if vocabulary is not None else load_vocabulary()
    for genre in vocabulary.get("genres") or []:
        if isinstance(genre, dict) and genre.get("id") == genre_id:
            return genre.get("label") or humanize(genre_id)
    return humanize(genre_id) if genre_id else None


def _text(value):
    return value.strip() if isinstance(value, str) and value.strip() else None


def _first_sentence(text):
    if not text:
        return None
    match = re.match(r"\s*(.+?[.!?])(\s|$)", text)
    return (match.group(1) if match else text).strip()


def read_strings(dist_dir):
    """{locale: {key: text}} from the bundle's `locales/<locale>.json` files (the template
    ships them under public/locales/, copied into the build)."""
    out = {}
    directory = os.path.join(dist_dir or "", "locales")
    if not os.path.isdir(directory):
        return out
    for name in sorted(os.listdir(directory)):
        if not name.endswith(".json"):
            continue
        locale = name[:-5].lower()
        try:
            with open(os.path.join(directory, name), encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError):
            continue
        if isinstance(data, dict):
            out[locale] = {str(k): str(v) for k, v in data.items() if isinstance(v, str)}
    return out


def unit_kind_forms(kind):
    """The singular and plural of a content unit kind (`courses` -> {course, courses})."""
    word = str(kind or "").strip().lower()
    if not word:
        return set()
    forms = {word}
    if word.endswith("ies"):
        forms.add(word[:-3] + "y")
    elif word.endswith("s"):
        forms.add(word[:-1])
        if word.endswith("es") and word[:-2].endswith(("ss", "x", "ch", "sh", "z")):
            forms.add(word[:-2])
    else:
        forms.add(word + "s")
    return forms


_NUMBERED = re.compile(r"^(?P<prefix>[a-z][a-z0-9_-]*)\.(?P<n>[0-9]{1,3})$", re.I)


def built_units(strings, kind):
    """(count, [names], keys label) of the content units the build names in its own English
    strings - `course.1` .. `course.12` - for the design's unit kind; None when the build
    names none (then the design's count is all there is)."""
    english = (strings or {}).get("en") or {}
    forms = unit_kind_forms(kind)
    found = {}
    for key, value in english.items():
        match = _NUMBERED.match(key)
        if not match or match.group("prefix").lower() not in forms:
            continue
        if not isinstance(value, str) or not value.strip() or "{" in value:
            continue
        found[int(match.group("n"))] = (key, value.strip())
    if len(found) < 2:
        return None
    ordered = [found[n] for n in sorted(found)]
    prefix = ordered[0][0].rsplit(".", 1)[0]
    label = f"bundle locales/en.json#{prefix}.{min(found)}..{max(found)}"
    return len(ordered), [name for _key, name in ordered], label


def read_runtime_assets(dist_dir):
    """The runtime asset manifest shipped in the bundle (public/assets/assets.json), or None."""
    path = os.path.join(dist_dir or "", "assets", "assets.json")
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and data.get("format") == "wgf-runtime-assets" else None


def _facet_value(block):
    """The value of a Research V2 facet ({value, tier, source, ...}), a plain string, or None."""
    if isinstance(block, dict):
        value = block.get("value")
        return value if isinstance(value, str) and value else None
    return block if isinstance(block, str) and block else None


def _research_genre(design):
    research = design.get("research") or {}
    gameplay = research.get("gameplay") if isinstance(research.get("gameplay"), dict) else {}
    for candidate in (gameplay.get("genre"), research.get("genre"), research.get("archetype")):
        value = _facet_value(candidate)
        if value:
            return value
        if isinstance(candidate, dict):
            for inner in ("id", "genre"):
                if isinstance(candidate.get(inner), str) and candidate[inner]:
                    return candidate[inner]
    return None


def _research_audience(design):
    research = design.get("research") or {}
    audience = research.get("audience")
    if isinstance(audience, str):
        return audience
    if isinstance(audience, dict):
        for key in ("type", "age"):
            value = _facet_value(audience.get(key))
            if value:
                return value
        return _facet_value(audience)
    return None


def extract(design, *, sdk_report=None, scaffold=None, strings=None, runtime_assets=None,
            game_config=None, vocabulary=None, prototype_report=None):
    """The facts record and its sources. `strings` is read_strings()'s result; `game_config`
    the checkout's game.config.yaml (for game.name); `prototype_report` the development
    report of the build being listed (its `scope_deltas`: what the build added, cut or
    deferred against the design).

    Where the build says something the design does not - twelve courses where the design
    planned six - the build wins, since the listing describes what ships, and the
    disagreement is recorded in `conflicts`."""
    design = design or {}
    build = design.get("build_spec") or {}
    experience = build.get("experience") or {}
    controls = build.get("controls") or {}
    identity = build.get("visual_identity") or {}
    engine = design.get("engine") or {}
    scope = design.get("scope") or {}
    session = design.get("session") or {}
    responsive = build.get("responsive") or {}
    strings = strings or {}
    sources = {}
    vocabulary = vocabulary if vocabulary is not None else load_vocabulary()

    def note(fact, source):
        sources[fact] = source

    # Title: the game's own title string, then game.config.yaml, then the title id.
    title = None
    english = strings.get("en") or next(iter(strings.values()), {}) if strings else {}
    for key in ("title.heading", "boot.title", "title", "game.title"):
        if _text(english.get(key)):
            title = english[key].strip()
            note("title", f"bundle locales/{'en' if 'en' in strings else next(iter(strings))}.json#{key}")
            break
    if title is None and _text(((game_config or {}).get("game") or {}).get("name")):
        title = game_config["game"]["name"].strip()
        note("title", "checkout game.config.yaml#game.name")
    if title is None:
        title = humanize(design.get("title_id") or (scaffold or {}).get("title_id") or "untitled")
        note("title", "game-design#title_id (humanized)")

    facts = {"title": title}

    def put(fact, value, source):
        facts[fact] = value
        if value not in (None, [], {}, ""):
            note(fact, source)

    put("concept", _text(design.get("fantasy")) or _text(identity.get("concept")),
        "game-design#fantasy" if _text(design.get("fantasy")) else
        "game-design#build_spec.visual_identity.concept")
    put("core_loop", _text(design.get("core_loop")), "game-design#core_loop")
    goal = experience.get("goal") or {}
    put("objective", _text(goal.get("statement")), "game-design#build_spec.experience.goal.statement")
    put("win", _text((experience.get("win") or {}).get("condition")),
        "game-design#build_spec.experience.win.condition")
    put("lose", _text((experience.get("lose") or {}).get("condition")),
        "game-design#build_spec.experience.lose.condition")
    facts["endless"] = "win" not in experience
    note("endless", "game-design#build_spec.experience (win absent)")

    mechanics = []
    for index, mechanic in enumerate(build.get("mechanics") or []):
        if not isinstance(mechanic, dict) or mechanic.get("tier") not in _MVP:
            continue
        entry = {"id": str(mechanic.get("id") or f"mechanic-{index}"),
                 "name": str(mechanic.get("name") or mechanic.get("id") or "")}
        if _text(mechanic.get("description")):
            entry["description"] = mechanic["description"].strip()
        mechanics.append(entry)
        note(f"mechanic:{entry['id']}", f"game-design#build_spec.mechanics[{index}]")
    facts["mechanics"] = mechanics

    features = []
    for index, feature in enumerate(design.get("features") or []):
        if not isinstance(feature, dict) or feature.get("tier") not in _MVP:
            continue
        entry = {"id": str(feature.get("id") or f"feature-{index}"),
                 "name": str(feature.get("name") or feature.get("id") or "")}
        if _text(feature.get("description")):
            entry["description"] = feature["description"].strip()
        features.append(entry)
        note(f"feature:{entry['id']}", f"game-design#features[{index}]")
    facts["features"] = features
    # What the design's feature evaluation deferred or cut: the copy never names it.
    _included, excluded = feature_decisions(design)
    put("features_excluded", excluded, "game-design#features[].evaluation (later, cut)")

    per_device = {"touch": [], "mouse": [], "keyboard": [], "gamepad": []}
    for index, action in enumerate(controls.get("actions") or []):
        if not isinstance(action, dict) or action.get("tier") not in _MVP:
            continue
        for device in per_device:
            if _text(action.get(device)):
                per_device[device].append(action[device].strip())
                note(f"controls:{device}", f"game-design#build_spec.controls.actions[{index}].{device}")
    facts["controls"] = {"primary_input": controls.get("primary_input"),
                         "summary": _text(design.get("controls")), **per_device}
    if _text(design.get("controls")):
        note("controls:summary", "game-design#controls")
    if controls.get("primary_input"):
        note("controls:primary_input", "game-design#build_spec.controls.primary_input")

    genre = _research_genre(design)
    chain = genre_chain(genre, vocabulary) if genre else []
    put("genre", chain, "game-design#research (genre), core/reference/research-vocabulary.yaml")

    style = _text(identity.get("concept")) or _text(design.get("art_direction"))
    put("visual_style", style, "game-design#build_spec.visual_identity.concept"
        if _text(identity.get("concept")) else "game-design#art_direction")
    put("audience", _research_audience(design), "game-design#research.audience")
    facts["engine"] = {"type": engine.get("type"), "dimension": engine.get("dimension")}
    if engine:
        note("engine", "game-design#engine")
    put("orientation", responsive.get("orientation") if isinstance(responsive.get("orientation"), str) else None,
        "game-design#build_spec.responsive.orientation")
    target = session.get("target_seconds")
    put("session_target_s", target if isinstance(target, (int, float)) and not isinstance(target, bool) else None,
        "game-design#session.target_seconds")
    locales = [str(l).lower() for l in scope.get("locales") or [] if isinstance(l, str)]
    put("locales", locales, "game-design#scope.locales")

    platforms = [str(p.get("id")) for p in ((scaffold or {}).get("game_config") or {}).get("platforms") or []
                 if isinstance(p, dict) and p.get("id")]
    put("platforms", platforms, "scaffold-record#game_config.platforms")

    capabilities = set()
    for platform in (sdk_report or {}).get("platforms") or []:
        for feature in platform.get("features") or []:
            if feature.get("status") == "working" and feature.get("feature") not in (
                    "init", "loading-progress", "analytics", "language"):
                capabilities.add(str(feature["feature"]))
    for touchpoint in build.get("sdk_touchpoints") or []:
        if isinstance(touchpoint, dict) and touchpoint.get("tier") in _MVP \
                and touchpoint.get("capability") not in ("init", "loading-progress", "analytics", "language"):
            capabilities.add(str(touchpoint["capability"]))
    put("capabilities", sorted(capabilities),
        "sdk-report#platforms[].features (working), game-design#build_spec.sdk_touchpoints (mvp)")
    kinds = []
    for placement in (design.get("monetization") or {}).get("placements") or []:
        if isinstance(placement, dict) and placement.get("kind") and placement["kind"] not in kinds:
            kinds.append(str(placement["kind"]))
    put("monetization", kinds, "game-design#monetization.placements")
    units = scope.get("content_units")
    put("content_units", units if isinstance(units, int) and not isinstance(units, bool) else None,
        "game-design#scope.content_units")
    put("content_unit_kind", _text(scope.get("content_unit_kind")), "game-design#scope.content_unit_kind")
    conflicts = []
    built = built_units(strings, facts.get("content_unit_kind")) if facts.get("content_unit_kind") else None
    if built is not None:
        count, names, label = built
        if facts.get("content_units") is not None and facts["content_units"] != count:
            conflicts.append({"fact": "content_units", "design": facts["content_units"], "build": count,
                              "source": label})
        put("content_units", count, label)
        put("content_unit_names", names, label)
    deltas = []
    for index, delta in enumerate((prototype_report or {}).get("scope_deltas") or []):
        if isinstance(delta, dict) and _text(delta.get("item")) and delta.get("direction") in (
                "added", "cut", "deferred"):
            entry = {"item": delta["item"].strip(), "direction": delta["direction"]}
            if _text(delta.get("reason")):
                entry["reason"] = delta["reason"].strip()
            deltas.append(entry)
    put("scope_deltas", deltas, "prototype-report#scope_deltas")
    facts["conflicts"] = conflicts
    facts["strings"] = {locale: dict(values) for locale, values in sorted(strings.items())}
    if strings:
        note("strings", "bundle locales/<locale>.json")
    facts["sources"] = sources
    return facts


def hero_asset(runtime_assets):
    """(asset id, url relative to assets.json) of the asset that draws the player, else an
    icon, else None - what the icon is composed around."""
    assets = (runtime_assets or {}).get("assets") or {}
    for wanted in ("player", "icon"):
        for asset_id, asset in sorted(assets.items()):
            if not isinstance(asset, dict) or asset.get("placeholder"):
                continue
            roles = asset.get("roles") or ([asset.get("role")] if asset.get("role") else [])
            if (wanted in roles or (wanted == "icon" and asset.get("type") == "icon")) \
                    and asset.get("url") and str(asset.get("format", "")).lower() in (
                        "png", "svg", "webp", "jpg", "jpeg", ""):
                return asset_id, asset["url"]
    return None, None


def font_assets(runtime_assets):
    """[(asset id, url)] of the font assets the bundle ships, for the wordmark."""
    assets = (runtime_assets or {}).get("assets") or {}
    return [(asset_id, asset["url"]) for asset_id, asset in sorted(assets.items())
            if isinstance(asset, dict) and asset.get("type") == "font" and asset.get("url")]

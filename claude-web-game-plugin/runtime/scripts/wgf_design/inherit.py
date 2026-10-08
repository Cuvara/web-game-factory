"""What the design takes from the strategy, re-derived from the CURRENT strategy on every visit.

Found live (2026-10-08, a 2D brick-breaker, defect L31): a person re-planned the strategy
(session.target_seconds 300 -> 360) and resumed from design. The design was a design-gap
repair, so its starting draft was the previous game-design verbatim - casual session profile,
300 s - and the new strategy's session never reached the draft: the design failed the casual
profile's rules the strategy no longer asked for. Every field the design holds only because
the strategy states it is the strategy's, never the previous design's or a draft's:

    session.target_seconds, session.first_session_seconds   the strategy's session
    build_spec.depth.first_session.target_s                 when it repeated the old first session
    genre.session_profile                                   derived (session_profile_name)
    scope.locales                                           the platforms' required locales + en
    build_spec.monetization_touchpoints                     kinds the strategy approves and a
                                                            required platform serves; each one's
                                                            platforms re-read from the profiles
    build_spec.content.quality_tier                         the strategy's committed tier
    research                                                the strategy's research block

`follow(draft, strategy, platforms)` writes them into a draft in place and returns what it
changed, `[{field, before, after}]`, for the author's request. It relaxes nothing: the draft is
finalized and judged exactly as before, against the rules the current strategy implies.
"""

from .platforms import supported_placements

__all__ = ["PLACEMENTS_BY_CLASS", "session_profile_name", "required_locales",
           "approved_placements", "follow"]

PLACEMENTS_BY_CLASS = {
    "rewarded-led": ["rewarded", "interstitial"],
    "interstitial-led": ["interstitial"],
    "mixed-ads": ["rewarded", "interstitial", "banner"],
    "iap-led": ["iap"],
    "hybrid": ["rewarded", "iap"],
    "none": [],
}


def session_profile_name(strategy):
    """`casual` when the audience is casual and the target session is at most 300 s, else
    `standard`. Not a family: the session profile the content is held to."""
    audience = (strategy or {}).get("audience") or {}
    target = ((strategy or {}).get("session") or {}).get("target_seconds")
    if audience.get("type") == "casual" and isinstance(target, (int, float)) and target <= 300:
        return "casual"
    return "standard"


def required_locales(platforms):
    """The locales the platforms require, required platforms first, and `en`."""
    locales = []
    for p in sorted(platforms or [], key=lambda p: not p.required):
        for locale in p.get("requirements", "locales_required", default=[]) or []:
            if locale not in locales:
                locales.append(locale)
    if "en" not in locales:
        locales.append("en")
    return locales


def approved_placements(strategy):
    """The placement kinds the strategy approves: its placements, else its class's."""
    monetization = (strategy or {}).get("monetization") or {}
    return list(monetization.get("placements")
                or PLACEMENTS_BY_CLASS.get(monetization.get("class"), []))


def _set(changes, holder, key, value, field):
    before = holder.get(key)
    if before != value:
        holder[key] = value
        entry = {"field": field, "after": value}
        if before is not None:
            entry["before"] = before
        changes.append(entry)


def follow(draft, strategy, platforms):
    """Write the strategy-owned fields of `draft` from `strategy` and `platforms` (in place).
    Returns [{field, before, after}] for every field it changed; [] when the draft already
    follows the strategy. A field the draft does not hold the shape for is left to the author."""
    changes = []
    if not isinstance(draft, dict) or not isinstance(strategy, dict):
        return changes
    intent = strategy.get("session") or {}
    target = intent.get("target_seconds")
    session = draft.get("session")
    spec = draft.get("build_spec") if isinstance(draft.get("build_spec"), dict) else {}

    if isinstance(target, (int, float)) and isinstance(session, dict):
        first = intent.get("first_session_seconds") or min(target, 180)
        old_first = session.get("first_session_seconds")
        _set(changes, session, "target_seconds", target, "session.target_seconds")
        _set(changes, session, "first_session_seconds", first, "session.first_session_seconds")
        # The depth block's first session repeats the session's (depth.py checks they agree);
        # one that said what the old first session said says the new one.
        ladder = spec.get("depth") if isinstance(spec.get("depth"), dict) else {}
        opening = ladder.get("first_session")
        if isinstance(opening, dict) and old_first is not None \
                and opening.get("target_s") == old_first:
            _set(changes, opening, "target_s", first, "build_spec.depth.first_session.target_s")

    genre = draft.get("genre")
    if isinstance(genre, dict) and isinstance(target, (int, float)):
        _set(changes, genre, "session_profile", session_profile_name(strategy),
             "genre.session_profile")

    scope = draft.get("scope")
    if platforms and isinstance(scope, dict):
        derived = required_locales(platforms)
        # A locale the design adds beyond the platforms' is the design's own choice and stays.
        extra = [x for x in scope.get("locales") or [] if x and x not in derived]
        _set(changes, scope, "locales", derived + extra, "scope.locales")

    touchpoints = spec.get("monetization_touchpoints")
    if platforms and isinstance(touchpoints, list) and \
            isinstance(strategy.get("monetization"), dict):
        allowed = set(approved_placements(strategy)) & set(supported_placements(platforms))
        kept = []
        for touchpoint in touchpoints:
            if not isinstance(touchpoint, dict):
                kept.append(touchpoint)
                continue
            if touchpoint.get("kind") not in allowed:
                changes.append({"field": f"build_spec.monetization_touchpoints"
                                         f"[{touchpoint.get('id')}]",
                                "before": touchpoint.get("kind"),
                                "after": None})
                continue
            serving = [p.id for p in platforms if touchpoint.get("kind") in p.placements]
            if "platforms" in touchpoint:
                _set(changes, touchpoint, "platforms", serving,
                     f"build_spec.monetization_touchpoints[{touchpoint.get('id')}].platforms")
            kept.append(touchpoint)
        if len(kept) != len(touchpoints):
            spec["monetization_touchpoints"] = kept

    content = spec.get("content")
    committed = ((strategy.get("concept") or {}).get("content_model") or {}).get("quality_tier")
    if committed and isinstance(content, dict):
        _set(changes, content, "quality_tier", committed, "build_spec.content.quality_tier")

    carried = strategy.get("research")
    if isinstance(carried, dict) and carried.get("research_version") == 2:
        previous = draft.get("research")
        applied = (previous or {}).get("applied") if isinstance(previous, dict) else None
        research = dict({k: v for k, v in carried.items() if k != "applied"},
                        applied=list(applied or []))
        if previous != research:
            draft["research"] = research
            changes.append({"field": "research",
                            "after": f"the strategy's research ({carried.get('report_id')})"})
    return changes

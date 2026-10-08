"""What the design takes from the strategy, re-derived from the CURRENT strategy on every visit.

Found live (2026-10-08, a 2D brick-breaker, defect L31): a person re-planned the strategy
(session.target_seconds 300 -> 360) and resumed from design. The design was a design-gap
repair, so its starting draft was the previous game-design verbatim - casual session profile,
300 s - and the new strategy's session never reached the draft: the design failed the casual
profile's rules the strategy no longer asked for. Every field the design holds only because
the strategy states it is the strategy's, never the previous design's or a draft's:

    session.target_seconds                     the strategy's
    session.first_session_seconds              the strategy's when it states one; else the
                                               default of the target, re-derived only when
                                               the draft held the old target's default
    build_spec.depth.first_session.target_s    when it repeated the old first session
    genre.session_profile                      derived (session_profile_name)
    scope.locales                              every locale the platforms require, appended
                                               after the design's own, in the design's order
    build_spec.monetization_touchpoints        kinds the strategy approves and the required
                                               platforms serve (a dropped one takes its
                                               feature and continue offer with it); each
                                               one's platforms the design's, less those that
                                               no longer serve the kind
    build_spec.content.quality_tier            at least the strategy's committed tier (a
                                               design may aim higher, never lower)
    research                                   the strategy's research block

`follow(draft, strategy, platforms)` writes them into a draft in place and returns what it
changed, `[{field, before, after}]`, for the author's request. `check(design, strategy)` is the
step's check of what an author RETURNS: the session target, a stated first session and the
derived session profile must be the strategy's - problems the author is asked to repair, as
any other. Neither relaxes a rule: the draft is judged against what the current strategy
implies.
"""

from .content import QUALITY_TIERS
from .platforms import supported_placements

__all__ = ["PLACEMENTS_BY_CLASS", "session_profile_name", "required_locales",
           "approved_placements", "follow", "check"]

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


def _drop_touchpoint(draft, spec, touchpoint, changes):
    """A placement the strategy no longer approves goes, and what the design tied to it: the
    touchpoint's `monetization-<id>` feature (or the `<Kind> placement` feature), dependencies
    on that feature, and a continue offer naming the touchpoint."""
    tid, kind = touchpoint.get("id"), touchpoint.get("kind")
    changes.append({"field": f"build_spec.monetization_touchpoints[{tid}]",
                    "before": kind, "after": None})
    failure = spec.get("failure")
    if isinstance(failure, dict) and tid is not None and failure.get("continue_offer") == tid:
        del failure["continue_offer"]
        changes.append({"field": "build_spec.failure.continue_offer", "before": tid,
                        "after": None})
    features = draft.get("features")
    if not isinstance(features, list):
        return
    gone = {f.get("id") for f in features if isinstance(f, dict) and (
        f.get("id") == f"monetization-{tid}" or (
            str(f.get("id") or "").startswith("monetization-") and kind
            and f.get("name") == f"{str(kind).capitalize()} placement"))}
    gone.discard(None)
    if not gone:
        return
    kept = []
    for feature in features:
        if isinstance(feature, dict) and feature.get("id") in gone:
            changes.append({"field": f"features[{feature['id']}]", "before": feature.get("name"),
                            "after": None})
            continue
        if isinstance(feature, dict) and isinstance(feature.get("depends_on"), list):
            feature["depends_on"] = [d for d in feature["depends_on"] if d not in gone]
        kept.append(feature)
    draft["features"] = kept


def follow(draft, strategy, platforms):
    """Write the strategy-owned fields of `draft` from `strategy` and `platforms` (in place).
    Returns [{field, before, after}] for every field it changed; [] when the draft already
    follows the strategy. What the design chose within the strategy - a higher quality tier,
    its own first-session length when the strategy states none, a narrower platform list for
    a placement, extra locales and their order - stays. A field the draft does not hold the
    shape for is left to the author."""
    changes = []
    if not isinstance(draft, dict) or not isinstance(strategy, dict):
        return changes
    intent = strategy.get("session") or {}
    target = intent.get("target_seconds")
    session = draft.get("session")
    spec = draft.get("build_spec") if isinstance(draft.get("build_spec"), dict) else {}

    if isinstance(target, (int, float)) and isinstance(session, dict):
        old_target = session.get("target_seconds")
        old_first = session.get("first_session_seconds")
        _set(changes, session, "target_seconds", target, "session.target_seconds")
        stated = intent.get("first_session_seconds")
        if isinstance(stated, (int, float)):
            first = stated
        elif old_first is None or (isinstance(old_target, (int, float))
                                   and old_first == min(old_target, 180)):
            # The strategy states none: the old target's default is re-derived from the new
            # target; a first session the design chose itself stays its own.
            first = min(target, 180)
        else:
            first = old_first
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
        # The design's locales in its own order, with every required one it lacks appended;
        # a reorder is never a change.
        have = [x for x in scope.get("locales") or [] if x]
        missing = [x for x in required_locales(platforms) if x not in have]
        if missing:
            _set(changes, scope, "locales", have + missing, "scope.locales")

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
                _drop_touchpoint(draft, spec, touchpoint, changes)
                continue
            serving = [p.id for p in platforms if touchpoint.get("kind") in p.placements]
            if isinstance(touchpoint.get("platforms"), list):
                # The design's own subset, less the platforms that no longer serve the kind.
                narrowed = [p for p in touchpoint["platforms"] if p in serving] or serving
                _set(changes, touchpoint, "platforms", narrowed,
                     f"build_spec.monetization_touchpoints[{touchpoint.get('id')}].platforms")
            kept.append(touchpoint)
        if len(kept) != len(touchpoints):
            spec["monetization_touchpoints"] = kept

    content = spec.get("content")
    committed = ((strategy.get("concept") or {}).get("content_model") or {}).get("quality_tier")
    if committed in QUALITY_TIERS and isinstance(content, dict):
        stated = content.get("quality_tier")
        # A design may aim higher than its strategy (content.py `_tier_stated`), never lower;
        # a design that states none is held to the strategy's tier already.
        if stated in QUALITY_TIERS and \
                QUALITY_TIERS.index(stated) < QUALITY_TIERS.index(committed):
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


def check(design, strategy):
    """Problems: a design whose strategy-owned session fields are not the strategy's - the
    target session, the first session the strategy states, and the session profile derived
    from them. An author may not return a profile the strategy does not derive, in either
    direction (casual for a long session, or standard to escape the casual rules)."""
    problems = []
    if not isinstance(design, dict) or not isinstance(strategy, dict):
        return problems
    intent = strategy.get("session") or {}
    target = intent.get("target_seconds")
    if not isinstance(target, (int, float)):
        return problems
    session = design.get("session") if isinstance(design.get("session"), dict) else {}
    if session.get("target_seconds") != target:
        problems.append(f"[strategy.session_target] session.target_seconds is "
                        f"{session.get('target_seconds')!r} but the strategy's "
                        f"session.target_seconds is {target}: the session length is the "
                        f"strategy's (G2); set it to {target} and fit the design to it")
    stated = intent.get("first_session_seconds")
    if isinstance(stated, (int, float)) and session.get("first_session_seconds") != stated:
        problems.append(f"[strategy.first_session] session.first_session_seconds is "
                        f"{session.get('first_session_seconds')!r} but the strategy states "
                        f"{stated}: set it to {stated}")
    genre = design.get("genre")
    derived = session_profile_name(strategy)
    if isinstance(genre, dict) and (genre.get("session_profile") or "standard") != derived:
        kind = (strategy.get("audience") or {}).get("type")
        problems.append(f"[strategy.session_profile] genre.session_profile is "
                        f"{genre.get('session_profile')!r} but the strategy derives "
                        f"{derived!r} (casual only for a casual audience at a target session "
                        f"of at most 300 s; this one is {kind!r} at {target} s): set it to "
                        f"{derived!r} and design the units to that profile's rules")
    return problems

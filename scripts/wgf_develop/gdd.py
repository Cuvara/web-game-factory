"""docs/GDD.md: the game design, rendered for people and agents to read in the game repository.

`game-design.schema.json` declares `rendered_to: <game-repo>/docs/GDD.md`; this module is
what produces it. It follows the section structure of `core/templates/gdd.md` (1 Concept to
13 Open questions), filled from the game-design artifact and, where the template asks for it,
the title strategy. It is a rendering, not a source of truth: the header pins the artifact it
was rendered from, and the develop step regenerates it on every visit, so a hand edit never
survives into a development commit.

Deterministic and standard-library only. The template's list and table placeholders are why
this is a small renderer for this one document rather than a generic template engine.
"""

from .brief import _inline, _spec_lines, select_build_spec, BUILD_SPEC_SECTIONS

__all__ = ["GDD_PATH", "render_gdd"]

GDD_PATH = "docs/GDD.md"


def _text(value, empty="-"):
    if value in (None, "", [], {}):
        return empty
    return _inline(value)


def _list(items, empty="- (none)"):
    lines = [f"- {_inline(item)}" for item in items or [] if item not in (None, "")]
    return "\n".join(lines) if lines else empty


def _cell(value):
    return _text(value).replace("|", "\\|").replace("\n", " ")


def _table(header, rows, empty="(none)"):
    out = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    out += ["| " + " | ".join(_cell(c) for c in row) + " |" for row in rows]
    if not rows:
        out.append("| " + " | ".join([empty] + [""] * (len(header) - 1)) + " |")
    return "\n".join(out)


def render_gdd(design, strategy=None, content_hash=None):
    """The GDD as markdown. `content_hash` is the design's pinned hash (the ref's, when the
    engine recorded one); the provenance's own is used otherwise."""
    design = design or {}
    strategy = strategy or {}
    provenance = design.get("provenance") or {}
    content_hash = content_hash or provenance.get("content_hash")
    session = design.get("session") or {}
    retention = design.get("retention") or {}
    targets = retention.get("targets") or {}
    monetization = design.get("monetization") or {}
    scope = design.get("scope") or {}
    tiers = scope.get("tiers") or {}
    ux = design.get("ux") or {}
    engine = design.get("engine") if isinstance(design.get("engine"), dict) else {}
    resolution = engine.get("design_resolution") or {}
    consistency = design.get("consistency") or {}
    strategy_id = (strategy.get("provenance") or {}).get("artifact_id")

    out = []
    add = out.append
    add(f"# Game Design Document — {design.get('title_id') or 'untitled'}\n")
    add("<!--\n  A RENDERING of the game-design artifact, not a separate source of truth.\n"
        "  Written by the Factory's development module and regenerated on every development\n"
        "  visit; do not edit it here. If this file and the artifact disagree, the artifact\n"
        "  wins.\n-->\n")
    add(f"**Title** {design.get('title_id') or '-'} · **Artifact** "
        f"`{provenance.get('artifact_id') or '-'}` · **Schema** "
        f"{provenance.get('schema_version') or '-'} · **Status** "
        f"{provenance.get('status') or '-'}  ")
    add(f"**Strategy** `{strategy_id or '-'}` · **Generated from** `game-design` @ "
        f"`{content_hash or '-'}`\n")
    add("---\n")

    add("## 1. Concept\n")
    add(f"**One-liner.** {_text(strategy.get('one_liner'))}\n")
    add(f"**Fantasy.** {_text(design.get('fantasy'))}\n")
    add("**Pillars.**\n")
    add(_list(design.get("pillars")) + "\n")

    add("## 2. Core loop\n")
    add(f"{_text(design.get('core_loop'))}\n")

    add("## 3. Session design\n")
    add(_table(["", ""], [
        ("Time to first play", f"{_text(session.get('time_to_first_play_s'))}s"),
        ("Time to first reward", f"{_text(session.get('time_to_first_reward_s'))}s"),
        ("First session", f"{_text(session.get('first_session_seconds'))}s"),
        ("Target session", f"{_text(session.get('target_seconds'))}s"),
        ("Reward moments per session", _text(session.get("reward_moments_per_session"))),
    ]) + "\n")
    add(f"**Structure.** {_text(session.get('structure'))}\n")
    add(f"**End condition.** {_text(session.get('end_condition'))}\n")

    add("## 4. Progression and economy\n")
    add(f"{_text(design.get('progression'))}\n")
    add(f"**Currencies.** {_text(monetization.get('currencies'), 'none')}\n")
    add(f"**Economy.** {_text(monetization.get('economy'))}\n")
    add(f"**Terminal state.** {_text(scope.get('progression_terminal'))}\n")

    add("## 5. Retention\n")
    add(f"**Why they come back.** {_text(retention.get('return_reason'))}\n")
    add(f"**Hooks.** {_text(retention.get('hooks'))}\n")
    if retention.get("progression_loop"):
        add(f"**Progression loop.** {retention['progression_loop']}\n")
    add("**Targets.** " + " · ".join(f"{k.upper()} {targets[k]}" for k in ("d1", "d7", "d30")
                                     if k in targets) if targets else "**Targets.** -")
    add("")

    add("## 6. Monetization\n")
    add(_table(["Kind", "Trigger", "Player value", "Platforms"], [
        (p.get("kind"), p.get("trigger"), p.get("player_value"), p.get("platforms"))
        for p in monetization.get("placements") or []]) + "\n")

    add("## 7. Scope\n")
    for label, key in (("MVP", "mvp"), ("Prototype", "prototype"),
                       ("Production", "production"), ("Future", "future")):
        add(f"**{label}.**\n")
        add(_list(tiers.get(key)) + "\n")
    add("**Explicitly out of scope**\n")
    add(_table(["Item", "Why excluded"], [
        (o.get("item"), o.get("why_excluded")) for o in tiers.get("out_of_scope") or []
        if isinstance(o, dict)]) + "\n")
    add(f"Content units: {_text(scope.get('content_units'))} "
        f"{_text(scope.get('content_unit_kind'), '')} · Locales: "
        f"{_text(scope.get('locales'))} · Asset budget: {_text(scope.get('asset_budget'))}\n")

    add("## 8. UX and controls\n")
    add(f"**Controls.** {_text(design.get('controls'))}\n")
    add(f"**Onboarding.** {_text(ux.get('onboarding'))}\n")
    add(f"**Screens.** {_text(ux.get('screens'))}\n")
    add(f"**Accessibility.** {_text(ux.get('accessibility'))}\n")

    add("## 9. Difficulty\n")
    add(f"{_text(design.get('difficulty'))}\n")

    add("## 10. Art and audio direction\n")
    add(f"{_text(design.get('art_direction'))}\n")
    add(f"{_text(design.get('audio_direction'))}\n")

    add("## 10a. Engine\n")
    if engine:
        size = (f" at {resolution.get('width')}×{resolution.get('height')}"
                if resolution.get("width") else "")
        add(f"**{_text(engine.get('type'))}** ({_text(engine.get('dimension'))}){size} · "
            f"Camera: {_text(engine.get('camera'))}\n")
        add(f"{_text(engine.get('rationale'))}\n")
    else:
        add(f"{_text(design.get('engine'))}\n")

    add("## 10b. Build specification — MVP\n")
    spec = select_build_spec(design)
    if spec and spec.get("sections"):
        for key, label in BUILD_SPEC_SECTIONS:
            if key in spec["sections"]:
                add(f"### {label}\n")
                add("\n".join(_spec_lines(spec["sections"][key])) or "- (none)")
                add("")
        full = design.get("build_spec") or {}
        for key, label in (("sdk_touchpoints", "Platform SDK touchpoints"),
                           ("assets", "Assets")):
            if full.get(key):
                add(f"### {label}\n")
                if key == "sdk_touchpoints":
                    add("Through the template's platform abstraction, never a portal SDK.\n")
                entries = [e for e in full[key] if not isinstance(e, dict)
                           or e.get("tier") in (None, "mvp")]
                add("\n".join(_spec_lines(entries)) or "- (none)")
                add("")
    else:
        add("The design carries no build specification (an earlier schema).\n")

    add("## 10c. Post-MVP and optional\n")
    later = [(f.get("name") or f.get("id"), f.get("tier"), f.get("description"))
             for f in design.get("features") or []
             if isinstance(f, dict) and f.get("tier") not in (None, "mvp")]
    add(_table(["Feature", "Tier", "Description"], later) + "\n")
    if spec and spec.get("not_now"):
        add("Build-spec entries of a later tier:\n")
        add(_list(spec["not_now"]) + "\n")

    add("## 11. Platform considerations\n")
    add(_table(["Platform", "Requirement", "How addressed"], [
        (c.get("platform_id"), c.get("requirement"), c.get("how_addressed"))
        for c in design.get("platform_constraints_applied") or [] if isinstance(c, dict)])
        + "\n")

    add("## 12. Design consistency\n")
    add(f"**Status** {_text(consistency.get('status'))} · **Ruleset** "
        f"{_text(consistency.get('ruleset_version'))} · **Evaluated** "
        f"{_text(consistency.get('evaluated_at'))}\n")
    add(_table(["Rule", "Breached", "Note"], [
        (r.get("criterion_id"), "yes" if r.get("breached") else "no",
         r.get("note") or r.get("measured"))
        for r in consistency.get("rule_results") or [] if isinstance(r, dict)]) + "\n")

    add("## 13. Open questions\n")
    add(_list(design.get("open_questions")) + "\n")
    add("Things the prototype is expected to answer.")
    return "\n".join(out) + "\n"

# Game Design Document — {{game_name}}

<!--
  A RENDERING of the game-design artifact, not a separate source of truth.

  The artifact (workspace/titles/<title-id>/game-design.yaml, validated by
  core/artifacts/game-design.schema.json) is authoritative. This document exists so humans
  and coding agents can read the design as prose. If the two disagree, the artifact wins
  and this file is stale.

  Rendered into the game repository at docs/GDD.md - in an engine run by the development
  step, on every visit, so it tracks the design each build is briefed from.
-->

**Title** {{title_id}} · **Version** {{version}} · **Status** {{status}}
**Strategy** {{strategy_ref}} · **Generated from** `game-design.yaml` @ {{content_hash}}

---

## 1. Concept

**One-liner.** {{one_liner}}

**Fantasy.** {{fantasy}} — what the player gets to feel or pretend to be.

**Pillars.** {{pillars}} — two or three. More than three and none of them decide anything.

## 2. Core loop

{{core_loop}}

State it as a cycle. If it cannot be written as a loop, it is not one.

## 3. Session design

| | |
|---|---|
| Time to first play | {{time_to_first_play_s}}s |
| Time to first reward | {{time_to_first_reward_s}}s |
| First session | {{first_session_seconds}}s |
| Target session | {{target_seconds}}s |
| Reward moments per session | {{reward_moments_per_session}} |

**Structure.** {{structure}} — how a session begins, escalates and ends. A session that
ends arbitrarily reads as being interrupted.

**End condition.** {{end_condition}}

## 4. Progression and economy

{{progression}}

**Currencies.** {{currencies}}
**Economy.** {{economy}}
**Terminal state.** {{progression_terminal}} — how progression ends, or an explicit
statement that it loops.

## 5. Retention

**Why they come back.** {{return_reason}} — in a player's words, not in mechanics.

**Hooks.** {{hooks}}
**Targets.** D1 {{d1}} · D7 {{d7}} · D30 {{d30}}

## 6. Monetization

For each placement: the in-game trigger and what the player gets.

| Kind | Trigger | Player value | Platforms |
|---|---|---|---|
| {{kind}} | {{trigger}} | {{player_value}} | {{platforms}} |

A rewarded placement with no player value is an interstitial wearing a costume.

## 7. Scope

**MVP.** {{mvp}}
**Prototype.** {{prototype}}
**Production.** {{production}}
**Future.** {{future}}

**Explicitly out of scope**

| Item | Why excluded |
|---|---|
| {{item}} | {{why_excluded}} |

Content units: {{content_units}} {{content_unit_kind}} · Locales: {{locales}} · Asset
budget: {{asset_budget}}

## 8. UX and controls

**Controls.** {{controls}}
**Onboarding.** {{onboarding}}
**Screens.** {{screens}}
**Accessibility.** {{accessibility}}

## 9. Difficulty

{{difficulty}}

## 10. Art and audio direction

{{art_direction}}

{{audio_direction}}

## 10a. Engine

**{{engine_type}}** ({{dimension}}) at {{design_width}}×{{design_height}} · Camera: {{camera}}

{{engine_rationale}}

## 10b. Build specification — MVP

<!-- Rendered from build_spec, filtered to tier mvp. Post-MVP and optional entries are
     listed in 10c so the implementer can see what NOT to build yet. -->

**Mechanics.** For each: {{name}} — {{description}}; rules {{rules}}; tuning {{parameters}}.

**Controls.** Primary input {{primary_input}}.

| Action | Touch | Mouse | Keyboard |
|---|---|---|---|
| {{action}} | {{touch}} | {{mouse}} | {{keyboard}} |

**Player goals.** Moment: {{moment}} · Session: {{session_goal}} · Long term: {{long_term}}

**Game states.**

| State | Description | Exits (on → to) |
|---|---|---|
| {{state_id}} | {{description}} | {{exits}} |

**Screens, HUD, menus.** {{screens}} · {{hud}} · {{menus}}

**Tutorial.** {{tutorial_approach}} — {{tutorial_steps}}

**Rewards.** {{rewards}}

**Failure and retry.** {{failure_condition}} → {{failure_feedback}} → {{retry_path}}
({{time_to_retry_s}}s)

**Session flow.** {{session_flow}}

**Monetization touchpoints.** {{monetization_touchpoints}}

**Platform SDK touchpoints.** {{sdk_touchpoints}} — through the template's platform
abstraction, never a portal SDK.

**Assets.** {{assets}} · **Audio.** {{audio}}

**Responsive.** {{orientation}}, {{scale_mode}}, layouts {{layouts}}, touch targets
≥ {{min_touch_target_px}}px, safe area: {{safe_area}}

**Visual identity.** {{visual_concept}} · Palette {{palette}} · Type {{display}} /
{{body}} · Shapes {{shape_language}} · Motion {{motion}} · Avoid {{avoid}}

## 10c. Post-MVP and optional

| Feature | Tier | Description |
|---|---|---|
| {{feature}} | {{tier}} | {{description}} |

## 11. Platform considerations

| Platform | Requirement | How addressed |
|---|---|---|
| {{platform_id}} | {{requirement}} | {{how_addressed}} |

An empty table on a title with required platforms means the profiles were not read.

## 12. Design consistency

**Status** {{consistency_status}} · **Ruleset** {{ruleset_version}} · **Evaluated**
{{evaluated_at}}

| Rule | Breached | Note |
|---|---|---|
| {{criterion_id}} | {{breached}} | {{note}} |

## 13. Open questions

{{open_questions}}

Things the prototype is expected to answer. Better recorded than silently assumed.

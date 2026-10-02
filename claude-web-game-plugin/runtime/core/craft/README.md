# Craft

How to make a **good** web game, as opposed to one that passes its checks.

The rest of `core/` says what must exist, who decides and what counts as evidence. This
directory says what *good* looks like inside the fields those artifacts already have:
`build_spec`, `session`, `visual_identity`, `perf_budgets`, `playtest_sessions`, and the
gameplay-session scenarios. It adds no field, no state and no gate. A playbook that seems to
need a new field has found a gap in an artifact. Raise it there; do not work around it here.

Every playbook is a set of **defaults with reasons**. A title may depart from a default when
its design says why. Departing silently is a defect, the same way relaxing a consistency
rule is.

## Who reads what

| Playbook | Primary role(s) | Stage(s) | Serves |
|---|---|---|---|
| [`core-loop-and-difficulty.md`](core-loop-and-difficulty.md) | game-designer, gameplay | strategy, design, prototype | `core_loop`, `build_spec.mechanics`, `.difficulty`, `.session_flow`, `.failure` |
| [`retention-and-progression.md`](retention-and-progression.md) | game-designer, gameplay, liveops | design, prototype, production, live | `build_spec.depth`, `.player_goals`, `.progression`, `retention`, `session` |
| [`game-feel.md`](game-feel.md) | gameplay, ui | design, prototype | `build_spec.rewards[].feedback`, `.hud[].feedback`, `.failure.feedback`, `visual_identity.motion` |
| [`onboarding-and-portal-ux.md`](onboarding-and-portal-ux.md) | ui, game-designer | design, prototype, release | `session.time_to_first_*`, `build_spec.tutorial`, `.monetization_touchpoints`, store metadata |
| [`ui-hud-mobile.md`](ui-hud-mobile.md) | ui | design, prototype | `build_spec.screens`, `.hud`, `.menus`, `.responsive` |
| [`game-audio.md`](game-audio.md) | asset, gameplay, ui | design, prototype, production | `audio_direction`, `build_spec.audio`, the asset manifest's `sfx`/`music`, the play probe's `audio` |
| [`art-direction.md`](art-direction.md) | game-designer, asset | design, prototype | `art_direction`, `build_spec.visual_identity`, `.assets`, the asset manifest |
| [`accessibility.md`](accessibility.md) | ui, game-designer | design, prototype, qa | `ux.accessibility`, `visual_identity`, `.controls` |
| [`production-art-and-ui.md`](production-art-and-ui.md) | game-designer, asset, gameplay, ui | design, prototype, production | `build_spec.assets[].role`/`.readability`, `visual_identity.ui`/`.primitive_style`, the play probe's `asset`/`render` |
| [`production-art-2d.md`](production-art-2d.md) | asset, gameplay, game-designer | design, production | the 2D style kit, a silhouette per variant, layered SVG authoring, backgrounds, VFX, sizes and anchors, `library.json` and the author |
| [`production-art-3d.md`](production-art-3d.md) | asset, gameplay, game-designer | design, production | model specs by part decomposition, materials and emissive, the light rig, fog and sky, portrait camera framing |
| [`game-ui-kit.md`](game-ui-kit.md) | ui, asset, game-designer | design, production | fonts as assets and locale glyphs, tokens, contrast and target floors, buttons, HUD, title/pause/result/retry, portrait layout |
| [`juice.md`](juice.md) | gameplay, ui | prototype, production | the feedback numbers: acknowledgement within 100 ms, drop, merge, combo, shake, near-miss, crash, opening grace |
| [`production-wiring.md`](production-wiring.md) | gameplay, ui, asset | production | loading `assets.json` by id and role, the probe's `asset`/`render`/`assets_loaded`, the art regression guard, self-checking against the gates with frames |
| [`2d-assets.md`](2d-assets.md) | asset, gameplay, ui | design, prototype | `asset_requirements`, the asset manifest, the runtime asset manifest |
| [`web-performance.md`](web-performance.md) | architect, gameplay, qa | tech-plan, prototype, qa | `perf_budgets`, `perf_measurements`, the asset pipeline |
| [`phaser.md`](phaser.md) | gameplay, ui | tech-plan, prototype | `build_spec.mechanics`, `.controls`, `.screens`, `.responsive` — only when `engine.type` is `phaserjs` |
| [`3d-scene-and-physics.md`](3d-scene-and-physics.md) | gameplay, architect | tech-plan, prototype | `build_spec.mechanics`, `.controls`, `.game_states`, `architecture.physics` |
| [`3d-assets-and-animation.md`](3d-assets-and-animation.md) | gameplay, asset | design, prototype | the asset manifest's 3D kinds, `build_spec.assets`, `max_bundle_mb` |
| [`3d-diagnostics.md`](3d-diagnostics.md) | gameplay, architect (as reviewer), qa | prototype, qa | `known_issues`, `perf_measurements`, the repair loop |
| [`playtesting.md`](playtesting.md) | qa, game-designer | prototype, prototype-review, qa | `playtest_sessions`, gameplay-session scenarios, `kill_criteria_eval` |
| [`gameplay-review.md`](gameplay-review.md) | architect (as reviewer) | prototype | `review-report` blockers |
| [`store-listing.md`](store-listing.md) | release | release (store-listing) | `store-listing` copy, screenshots and branding, `release-manifest.store_metadata`, the profiles' `store_listing` blocks |
| [`competitive-teardown.md`](competitive-teardown.md) | research, game-designer | market-scan, strategy | claims and research snapshots |
| [`research-evidence.md`](research-evidence.md) | research | market-scan | the snapshot format, and the project concept for a brief no catalog shape carries, when a run's research step waits for them |
| [`tool-capabilities.md`](tool-capabilities.md) | every role | every stage | what tools each stage may use, and the limits on them |

The five production playbooks (`production-art-2d`, `production-art-3d`, `game-ui-kit`,
`juice`, `production-wiring`) are distilled from the template's two reference ports - the
2D and 3D games whose production builds passed the production gate - and carry their
numbers. Each ends with **Distilled from**: the reference files and frames it came from, so
a rule can be checked against the build that proved it.

## The one tension to hold

`prototype.md` warns against **polishing instead of proving**. `game-feel.md` defines a
**minimum feedback bar**. They do not contradict each other:

- *Feedback* means the player can tell what happened: input acknowledged, reward noticed,
  failure understood. It is part of what the prototype proves, because a mechanic nobody
  can read cannot be judged fun or unfun.
- *Polish* means making something that already reads well more pleasant. It waits for
  production.

A prototype without the feedback bar produces false kills. A prototype with polish produces
false passes.

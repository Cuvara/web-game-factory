# Technical Plan — {{game_name}}

<!--
  A RENDERING of the tech-plan artifact. The artifact
  (workspace/titles/<title-id>/tech-plan.yaml) is authoritative.
  Declared as the tech-plan's rendering in the game repository (docs/tech-plan.md). No
  step renders it yet: the plan's tasks reach the developer through the development brief.
-->

**Title** {{title_id}} · **Engine** {{engine_type}} · **Timebox** {{timebox_days}} days
**Generated from** `tech-plan.yaml` @ {{content_hash}}

---

## 1. Engine

**{{engine_type}}** — {{rationale}}

PixiJS for 2D, Three.js for 3D. The rationale must be about cost and constraint — load
budget, asset pipeline, mobile headroom — not preference.

## 2. Architecture

| System | Approach |
|---|---|
| Rendering | {{rendering}} |
| Game core | {{game_core}} |
| State | {{state}} |
| Input | {{input}} |
| UI | {{ui}} |
| Audio | {{audio}} |
| Assets | {{assets}} |
| Platform SDK | {{platform_sdk}} |
| Analytics | {{analytics}} |
| Persistence | {{persistence}} |
| Networking | {{networking}} |

## 3. Ownership

What the template provides versus what this game builds. Getting this wrong means
reimplementing what already exists.

- **Generic (template)** — {{generic}}
- **Game-specific** — {{game_specific}}
- **Platform-specific** — {{platform_specific}}
- **Agent responsibility** — {{agent_responsibility}}
- **CI responsibility** — {{ci_responsibility}}

## 4. Performance budgets

| Device class | Target FPS | Max memory | Max TTI |
|---|---|---|---|
| {{id}} | {{target_fps}} | {{max_memory_mb}} MB | {{max_time_to_interactive_s}}s |

**Max bundle** {{max_bundle_mb}} MB — must respect the tightest required platform profile.

Budgets are set before measuring. Budgets written after the fact are not budgets.

## 5. Repository parameters

**Repo** {{repo_name}} · **From** {{template_ref}} · **Visibility** {{visibility}}

`game.config.yaml` to be written at scaffolding:

```yaml
game:
  id: {{game_id}}
  name: {{game_name}}
  version: {{version}}
engine:
  type: {{engine_type}}
platforms:
  - { id: {{platform_id}}, profile: {{platform_id}}@{{profile_version}}, role: {{role}} }
build:
  command: {{build_command}}
  output: {{build_output}}
```

Platforms are pinned entries, not bare strings, so the build is reproducible against the
compliance rules in force.

## 6. Milestones

| Id | Milestone | Phase | Days | Exit criteria |
|---|---|---|---|---|
| {{id}} | {{label}} | {{phase}} | {{est_days}} | {{exit_criteria}} |

**Total** {{est_days}} days against a {{timebox_days}} day timebox.

## 7. Tasks

The unit a coding agent works from. Acceptance criteria and tests are mandatory — a task
without them cannot be verified and will be reported complete when it is not.

```yaml
id: {{task_id}}
title: {{task_title}}
milestone: {{milestone}}
dependencies: {{dependencies}}
acceptance_criteria:
  - {{criterion}}
tests:
  - {{test}}
assets: {{assets}}
```

## 8. SDK and analytics

**Platform SDKs** {{platform_sdks}}
**Analytics events** {{analytics_events}}

Game code calls the template's platform abstraction, never a portal SDK directly.

## 9. Technical risks

| Risk | Severity | Mitigation |
|---|---|---|
| {{description}} | {{severity}} | {{mitigation}} |

## 10. Release requirements

{{release_requirements}}

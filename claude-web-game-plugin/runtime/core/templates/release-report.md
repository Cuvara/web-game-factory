# Release Report — {{game_name}} {{release_id}}

<!--
  A RENDERING of the release-manifest plus its platform-publication records.
  The manifest is authoritative and, once frozen at RC, immutable.
  Written to <game-repo>/release/<release-id>/report.md
-->

**Title** {{title_id}} · **Release** {{release_id}} · **Version** {{version}}
**Kind** {{kind}} · **State** {{state}} · **Commit** {{commit_sha}}
**Frozen at** {{frozen_at}}

---

## Changelog

{{changelog}}

## Packages

| Platform | File | Size | Checksum |
|---|---|---|---|
| {{platform_id}} | {{filename}} | {{size_mb}} MB | {{checksum}} |

## Target platforms

The release is `live` only when every **required** platform is live; otherwise
`partially-live`. Publication is not atomic — portals moderate independently.

| Platform | Role | Profile version | Publication state | Live URL |
|---|---|---|---|---|
| {{id}} | {{role}} | {{profile_version}} | {{pub_state}} | {{live_url}} |

## Validation

Assertions run against the built package, at the **pinned** profile version.

| Platform | Assertion | Breached | Note |
|---|---|---|---|
| {{platform_id}} | {{criterion_id}} | {{breached}} | {{note}} |

## Gate decisions

| Gate | Decision | By | Mode | When | Rationale |
|---|---|---|---|---|---|
| G5 | {{g5_decision}} | {{g5_by}} | {{g5_mode}} | {{g5_at}} | {{g5_rationale}} |
| G6 | {{g6_decision}} | {{g6_by}} | human | {{g6_at}} | {{g6_rationale}} |

G6 is irreversible and never auto-approves.

## Rejections and what they taught us

Every rejection produces a compliance finding and a platform profile update. A rejection
that only sets a status field teaches the factory nothing.

| Platform | Reason | Profile update | New profile version |
|---|---|---|---|
| {{platform_id}} | {{reason}} | {{update_kind}}: {{detail}} | {{new_profile_version}} |

## Rollback

**Target** {{rollback_target_release_id}}

Named in advance at G6, not found later under pressure. Rollback is re-publishing this
manifest, which is only possible because manifests are immutable and retained.

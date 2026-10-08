# Roles: Specialists

**Kind** implementer · **Roles** `level-designer`, `systems-designer`, `encounter-designer`,
`art-director`, `environment-artist`, `artist-2d`, `audio-designer`, `performance-engineer`,
`browser-qa`, `publishing-compliance`, `copywriter` (and, as specialists too, `gameplay`, `ui`,
`sdk` from [implementers.md](implementers.md))
**Work in** `title:prototype`, `title:production` (`publishing-compliance`, `copywriter`:
`release:store-listing`)

A specialist is an implementer that a **quality finding** is routed to. It owns no lifecycle
state and no transition. It is not a separate process either: a specialist visit is a
develop visit whose brief is that discipline's.

## Why specialists exist

Before them, every quality failure went back to one generalist develop visit whatever it was
about. A dark 3D scene, a level set with one element, a browser-default button and a code
review blocker all got the same brief, and the same developer tried the same things until
the loop limit stopped the run. What did fix them was a person reading the failure,
deciding which discipline it belonged to, and briefing that discipline by hand
(docs/quality-gap-audit-2026-10.md, sections 2.2 and 3). Routing makes that translation
data.

## How a specialist is briefed

The triage step (docs/specialist-routing.md) normalizes the current build's failing reports
and any typed findings a person gave at G4 into quality findings
(core/artifacts/shared/quality-finding.schema.json). Each finding's dimension has exactly
one owner (core/reference/specialist-routing.yaml). The owner's develop visit gets:

- **focus** (roles.yaml `focus`): what the visit is about.
- **only the findings it owns**: each with what was measured against which bar, the
  evidence (frames, files), the change asked for and the acceptance that the gate which
  raised it re-measures.
- **its craft playbooks** (roles.yaml `reads`), in place of the full list.
- **its writable scope** (roles.yaml `writes`), intersected with the installation's
  writable paths. A change outside it fails the visit, as any out-of-scope change does.

A specialist does not fix another specialist's findings, even when it sees them. They are
routed to their owner in the same chain of visits, before the gates measure the build
again.

## The specialists

| Role | Owns | Typical findings |
|---|---|---|
| `level-designer` | content, level design | too few units, one element per unit, units that only scale numbers, a unit not reachable |
| `systems-designer` | progression | unlocks that do not persist, no reason for the next session |
| `encounter-designer` | difficulty | no opening grace, axes that do not rise, no relief |
| `gameplay` | gameplay, feel | win or loss unreachable, an action not acknowledged, review and verification blockers |
| `art-director` | art direction | assets in different styles, a palette the direction does not name, scale and perspective that disagree, a UI that reads as another game |
| `environment-artist` | 3D environment, lighting and materials | an empty scene, a mood the art direction does not ask for, gate contrast, camera framing |
| `artist-2d` | 2D art | primitives on screen, art not used as the manifest lists it, store screenshots and key art |
| `ui` | UI and UX | default buttons, overlapping HUD, small touch targets, the objective not on screen, canvas UI a player cannot reach |
| `audio-designer` | audio | a cue that does not play, no mute, sound through an ad |
| `performance-engineer` | performance | a device class over its budget, a slow first interaction, frame drops, oversized textures or audio |
| `browser-qa` | browser | an uncaught page error while played, a viewport the layout breaks on, focus or visibility not handled |
| `sdk` | platform | portal behaviour a profile requires |
| `publishing-compliance` | compliance | a field, medium, format or declaration a platform's profile requires that the package or listing does not meet |
| `copywriter` | store copy | counts in the copy that are not the build's, a locale missing its description |

## The implementer is never the only judge

A specialist visit changes the build; it never accepts its own change. Every develop visit
is followed, before G4 and before release, by gates that do not share its brief and cannot
write the checkout: the playability bot, production-quality, the visual judge,
content-sufficiency, the read-only code review with its gate-gaming pre-check, verify and the
quality gate - and then a person at G4 (core/reference/quality-policy.yaml
`independent_review`, held by check-integrity). A finding closes only on the raising gate's
re-measurement of a newer build, never on the specialist's word.

## Leave what you learned

A specialist that finds a systemic issue - a class of defect the Factory's gates or brief let
through, not this build's instance of it - records it in its report as a **lesson candidate**
(report.json `lesson_candidates`, copied to the prototype-report's `specialist` block): the
lesson stated so it is true of any game, its root cause in the Factory and the check that
would hold it. Triage carries the candidates forward, the quality gate puts them in front of
the person deciding G4, and that person promotes one to core/reference/lessons.yaml - with
the check (core/reference/check-tiers.yaml) and the test that hold it - or rejects it. A
candidate never edits the lessons by itself. A finding whose check a lesson already names
carries the lesson as `guarded_by`, so the specialist knows the failure has been seen before
and what accepted it.

## What a specialist may not do

What every implementer may not: change scope, monetization, platform strategy, core design
or architecture. A finding that needs more content than the design states is not the level
designer's to invent. It routes to `design` (a scope or content increase), and the design
is revised first.

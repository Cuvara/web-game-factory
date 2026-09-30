# Publish

**Machine** release · **State** `submitting` · **Kind** automatic + human · **Role** release
**Gate** G6 (on entry to `validating`)
**Inputs** `release-manifest`, `platform-publication` · **Outputs** `platform-publication`

Submit the validated packages to each targeted portal.

## Publication is not atomic

This is the defect the original workflow's single `PUBLISH` stage could not express. With a
primary and secondary platforms, each portal moderates independently: Yandex can reject
what CrazyGames approved, on its own timeline, for its own reasons.

So each (release × platform) pair carries its own state machine
(`platform-publication.machine.yaml`), and the release computes a quorum from them:

- every `required` platform live → release `live`
- some required not live, none permanently rejected → release `partially-live`
- a required platform rejected → back to production to remediate

`accept_partial` exists as a human decision for shipping without a platform that was marked
required. It is a policy change, so it is recorded.

## Separation of responsibilities

**AI prepares. Deterministic automation executes.**

- The AI role prepares release metadata, per-platform descriptions, localizations,
  screenshots, and the packaged build.
- GitHub Actions performs the mechanical packaging and artifact handling.
- The submission itself is a **human checklist plus a status file**. No portal APIs are
  integrated, by design — building real Yandex/CrazyGames/GameVui/Poki integrations before
  the contracts are proven would be premature, and the machine's value here is structure
  and learning rather than automation.

**Secrets never live in source.** Portal credentials belong in CI secret storage and are
referenced, never committed, never printed into an artifact or a log.

## Rejections are the valuable path

When a portal rejects a submission, the `platform-publication` record **requires** a
`compliance_finding` with a `profile_update`. The options:

- `new-assertion` — add a machine check to the platform profile so validation catches it
  next time
- `common-rejection-entry` — record it in `review.common_rejections` so design reads it
- `requirement-change` — the profile's stated requirements were wrong

Then bump the profile version.

A rejection that only sets a status field teaches the factory nothing, and the next title
walks into the same wall. This loop is the highest-return mechanism in the system: it is
how the factory gets better at shipping rather than just repeatedly shipping.

## Waiting

`in-review` can last days — see `review.typical_days` per profile. Nothing in the factory
accelerates portal moderation. The state exists so that waiting is **visible** rather than
mistaken for being finished.

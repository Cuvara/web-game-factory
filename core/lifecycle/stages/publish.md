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

**AI prepares. Deterministic automation executes. A person authorizes.**

- The AI role prepares release metadata, per-platform descriptions, localizations,
  screenshots (`release/<release-id>/store-metadata.json`), and the packaged build.
- The Factory's `publish` group runs this state: behind G6 - a person's decision pinning the
  release-manifest by content hash - the `submit` step hands the package to the platform's
  adapter, which follows `core/reference/publication/<platform-id>.yaml`: the portal's
  documented API or CLI where one exists; a deterministic browser run of its developer
  console (direct Playwright, fixed selectors, one submit click) where none does and a person
  has recorded that the portal permits it; otherwise the person submits by hand and records
  it with `wgf decide <run> done --note <portal reference>`. The idempotency key is looked up
  before any upload; the submit is attempted once; the portal's own status, read back, is the
  only thing that advances the record. See docs/publish-module.md.
- A login, a CAPTCHA, a second factor, unconfirmed terms or a missing session stop the step
  for a person. Nothing is bypassed.

**Secrets never live in source.** A portal session is captured once by a person, kept where
the installation keeps secrets, named to the Factory by an environment variable, and redacted
from every artifact, event and log.

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

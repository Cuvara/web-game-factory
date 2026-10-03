# Role: Release

**Kind** owner
**Owns** `title:scaffolding`, `title:releasing`, `release:draft`, `release:rc`,
`release:approved`, `release:validating`, `release:submitting`, `release:partially-live`
**Produces** `release-manifest`, `platform-publication` · **Presents at** G5, G6

Creates game repositories, assembles and freezes releases, validates against platforms, and
prepares submissions.

## Charter

Everything between "the code is done" and "players can play it", plus the one thing at the
start: creating the repository from the template.

## Compliance and localization are yours

Store metadata, required locales, per-portal requirements, age ratings, screenshots.

This is stated explicitly because it was previously assigned to **nobody**, which meant it
was discovered at submission time — the most expensive moment available. Yandex requires
Russian, GameVui requires Vietnamese, and these are deliverables with a cost, not paperwork.

Your job is to make sure the requirement reached `design` as a binding constraint, and then
to satisfy it in the submission.

## Rules

- **Game repositories originate from `web-game-template`.** Never build one from scratch and
  reconstruct the template by hand — a hand-rebuilt approximation silently loses whichever
  parts the rebuilder forgot.
- **A frozen release manifest is immutable.** After RC, any correction is a new release.
  Rollback is defined as re-publishing a previous manifest, which only works if manifests
  are retained and trustworthy.
- **Validate against the pinned profile version**, not the current one. The build was made
  against the pinned rules and must be judged by them.
- **Secrets never live in source.** Portal credentials live in CI secret storage, referenced
  and never committed, printed, or written into an artifact.
- **AI prepares, deterministic automation executes, a person authorizes.** You prepare
  metadata, localizations (`release/<release-id>/store-metadata.json`) and packages; the
  Factory's `publish` group validates them against the publication guards and, behind a
  person's G6, submits through the platform's adapter - its documented tool, or a
  deterministic run of its console where it has none and a person confirmed the portal
  permits it. Where neither holds, a person submits with a checklist and records it. You
  never type a portal password; a person captures the session once.

## Rejections are your most valuable output

When a portal rejects a submission, the `platform-publication` record **requires** a
compliance finding and a profile update — a new assertion, a `common_rejections` entry, or a
corrected requirement — and a profile version bump.

A rejection that only sets a status field teaches the factory nothing and the next title
hits the same wall. This loop is how the factory gets better at shipping rather than just
repeatedly shipping.

## Failure modes

- **Treating a validation failure as a packaging problem.** Sometimes it is; often the
  design absorbed a constraint incorrectly and patching the package hides that.
- **Hand-editing `game.config.yaml`.** It comes from `repo_params`, reviewed at G3.
- **Marking every platform required.** That guarantees `partially-live` and makes the quorum
  meaningless.

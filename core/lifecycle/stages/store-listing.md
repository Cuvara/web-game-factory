# Store listing

**Machine** release · **Sub-activity within** `draft` · **Kind** automatic + AI-assisted
**Role** release · **Inputs** `qa-report`, `verification-report`, `sdk-report`,
`prototype-report`, `game-design`, `title-strategy`, `scaffold-record`, `asset-manifest`,
`playability-report`, `content-sufficiency-report`, `triage-report` · **Outputs**
`store-listing`, `listing-validation-report`

Everything a portal asks for beside the package: icon, logo and thumbnails; screenshots
and a gameplay recording; the title, descriptions, feature bullets, tags and categories; one
rendition of all of it per targeted platform; and the proof that each rendition satisfies
that platform's requirements as the Factory knows them.

## Why it is a sub-activity of `draft` and not a state

`release-draft.md` step 5 has always said "assemble store metadata per platform", and
`store_metadata_complete` has always guarded G6. Nothing produced it. This procedure is
that step made mechanical. It adds no state to the release machine: a listing is made for a
draft, from the draft's commit, and frozen with it at `rc`. In a workflow it is two steps
(`store-listing`, `listing-validation`) between the G4 pass and the `release` step, so the
release ships the listing beside its packages and `release-manifest.store_metadata` is
filled from it (`core/workflows/new-game.workflow.yaml`, `docs/store-listing-module.md`).

## The rule

> **Everything in the listing comes from the shipped build or the design that made it.**

A screenshot is a frame of the verified build, played through its own play probe. The icon
is composed from the game's own assets, palette and faces. A description says what the
player does, in words the design and the game's own strings use. A claim the build cannot
back (multiplayer, leaderboards, levels, offline) is a grounding failure, whoever wrote the
text (`core/reference/store-listing.yaml` `claims`). A count the copy states is one the
build MEASURED - the content-sufficiency report of the listed build - never one the design
planned; the controls text names every input the build accepts; every required locale is a
full description in its own language. A platform requirement nobody has read from the
portal stays `null` in the profile and is reported **UNKNOWN**, never passed.

## Procedure

1. **Take the verified build.** The commit is the one the newest passing `qa-report` and
   `verification-report` name, HEAD of a clean checkout, and the bundle on disk hashes to
   `verification-report.build_artifact.content_hash`. Anything else is a refusal: a listing
   of another build is a listing of another game. G4 must be passed in the run.
2. **Read the facts.** From `game-design` (`build_spec`: mechanics, controls, the
   experience contract's objective, win and lose, visual identity, features, engine,
   orientation, locales), `sdk-report` (capabilities observed working per platform),
   `scaffold-record` (the targeted platforms), the bundle's own locale strings, and the
   runtime asset manifest (which asset draws the player). Record where each came from.
   From the `content-sufficiency-report` of this build (its commit, or the development
   commit the listed one sits on) read the measured counts - units shipped, groups, climax
   units - and from the design's feature evaluation what was included and what was cut;
   record the run's quality tier and the `store_listing` bars of
   `core/reference/quality-benchmark.yaml` stated at it.
3. **Capture.** Serve the bundle locally, open it in a headless browser behind the refusing
   proxy, and play it through its probe on a landscape and a portrait viewport: the title
   screen, play early, play after several inputs, play late, the result screen. A frame in
   a `loading` or `other` state is never a screenshot; a frame below the readability floors
   or indistinguishable from an earlier one is dropped. Record `seconds` of oracle-driven
   play as the trailer. Too few usable frames: play again, longer, up to `retries`. Record
   the inputs the probe reported on each viewport: they are devices the controls text names.
4. **Brand.** Compose the icon, logo and promotional image from the game's own material
   in the browser; with no browser, derive them from the best gameplay frame and say so
   (`branding.method`).
5. **Write.** Produce every text per required locale from the facts - at the release
   tier the copywriter (an agent writer, `core/roles/roles.yaml`), for a development run the
   Factory's own template writer; both through the same grounding check - within the
   canonical bounds, the first sentence naming the core verb, every count a measured one,
   the controls naming every input the build accepts, every required locale a full
   description (`core/reference/store-listing.yaml` `counts`, `controls`, `copy`, `writer`).
6. **Render per platform.** From the canonical package, under each targeted platform's
   `store_listing` block: resize and crop to the sizes it names, cut texts to its limits,
   map tags through its vocabulary. Something it asks for that the package cannot make (a
   size larger than any master, a format no encoder here writes) is recorded `unmet`.
7. **Validate** (`listing-validation`): every required text present and within bounds,
   every file present with the dimensions, format and size required, screenshots real and
   distinct, the trailer within bounds or an honestly reported fallback, the copy free of
   unbacked claims and of counts the build did not measure, its controls and each
   required locale's description complete, every platform rendition against its block.
   FAIL goes through triage - its failures as quality findings, store copy the copywriter's
   - back to step 3 with the report, which names what to capture, render or rewrite again,
   the copywriter briefed with its findings; UNKNOWN is listed per platform.

## What is not done here

- No portal is contacted. Nothing is uploaded. The listing is material a person submits at
  `submitting`, through the checklist `platform-publication` lays out.
- No requirement is invented. A `null` in a profile is a question for the person who reads
  the portal, and the validation report asks it by name.
- No text is accepted unchecked, including a person's edit: the grounding check runs on
  every rendition that reaches release.

## Exit

The `release` step consumes the `store-listing` and its passing
`listing-validation-report`, refuses a listing of another commit or one that failed, copies
the package to `release/<release-id>/listing/` beside the zips, and fills
`store_metadata`. G6 reads all three.

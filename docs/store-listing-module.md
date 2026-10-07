# Store Listing Module

The `store-listing` and `listing-validation` steps of `core/workflows/new-game.workflow.yaml`
(stage `release:store-listing`): after a person passes G4, capture the verified build's
**store package** - branding, screenshots, a gameplay recording, store copy, one rendition
per targeted platform - and validate it against each platform's requirements, so the
release ships with it and `release-manifest.store_metadata` is filled from it. Implemented
in `scripts/wgf_listing/`, registered from `workspace/config/factory.yaml`, written against
[workflow-module-contract.md](workflow-module-contract.md) without touching the kernel.

```
bin/wgf new-game                                  # ... verify -> G4 -> store-listing -> listing-validation -> release
bin/wgf store-listing --run <run-id>              # capture the run's verified build again
bin/wgf listing-validation --run <run-id>         # judge the run's newest listing
python3 scripts/wgf-listing.py validate <package-dir>        # the judge, outside a run
python3 scripts/wgf-listing.py copy --design game-design.json --dist ../my-game/dist \
        [--sufficiency content-sufficiency-report.json] [--tier release]
python3 scripts/wgf-listing.py requirements [PLATFORM ...]   # what each profile asks, and what is UNKNOWN
```

A request for this phase called it "campaign / store listing setup". In the Factory
**campaign** already means paid acquisition (gate G7, `core/lifecycle/stages/campaign.md`), so
the phase, its artifacts and its steps are named **store listing**. The canonical package is
the "campaign package" of that request, platform-independent first; the platform renditions
are its variants.

## Why it exists, and where it sits

`core/lifecycle/stages/release-draft.md` step 5 has always said "assemble store metadata per
platform", and `store_metadata_complete` has always guarded G6 - and nothing produced it:
`release-manifest.store_metadata` was never filled, the template's `public/metadata/` is
empty. The release machine gains no state: the listing is a sub-activity of `draft`
(`core/lifecycle/stages/store-listing.md`), made for the draft's commit and frozen with it at
`rc`. In the workflow it is two steps between the G4 pass and `release`:

```
verify -> [G4 pass] -> store-listing -> listing-validation -> release
                            ^                |
                            └──── listing ───┘   (FAIL: capture, render or rewrite again)
```

It runs **after** G4 because a listing of a build a person may still kill is wasted work, and
because the screenshots must be of the commit that ships: the step requires G4 in
`context.gates_passed` (`with: required_gates`, default `[G4]`, the release step's rule), the
qa-report's and verification-report's commit to be the checkout's HEAD, and the bundle on
disk to hash to `verification-report.build_artifact.content_hash`. Anything else is BLOCKED.

## What it produces

| Where | What |
|---|---|
| the run, `<run>/store-listing/<visit>-<attempt>/package/` | the canonical package: `branding/` (icon-1024/512/256, logo-wordmark, thumbnail-16x9/4x3/1x1/2x3, promo-1920x1080), `screenshots/<viewport>-<nn>-<scene>.png`, `trailer/trailer.webm` (and `trailer.mp4` when an encoder is there; else `trailer/frames/` + `storyboard.json`), `copy/<locale>.json`, `platforms/<id>/` (the rendition: resized images, `listing.json` with the cut texts), `listing.json` (the artifact), `validation.json` (the report) |
| the run, `<run>/store-listing/<visit>-<attempt>/capture/` | the raw capture: every frame taken, `capture.json`, the recording, the capture logs |
| the run | `store-listing` and `listing-validation-report` artifacts, every file named with its sha256 and a path relative to the run directory |
| the game repository, `release/<release-id>/listing/` | the whole package, copied by the release step beside the archives; `release-manifest.store_metadata` names its files |

The package directory is deterministic (`core/reference/store-listing.yaml` `package`): a
publishing workflow finds every file without reading the artifact. Nothing lands in the
checkout: the bundle is served read-only, Playwright is resolved from the checkout's
`node_modules` through `createRequire`, and every output goes under the run directory.

## How it works

1. **Facts** (`facts.py`). From `game-design` (`build_spec`: mechanics, controls, the
   experience contract's objective, win and lose conditions, visual identity, features,
   engine, orientation, locales; `research.gameplay.genre`), `sdk-report` (capabilities
   observed `working`), the targeted platforms (below), the checkout's
   `game.config.yaml` (the game's name), the bundle's own `locales/<locale>.json` strings and
   its runtime asset manifest (`assets/assets.json`: the asset that draws the player, the
   fonts), and the `prototype-report`'s `scope_deltas` when that report is of the listed
   commit or an ancestor of it. Every fact records where it was read (`facts.sources`).
   **The build wins over the design.** The listing describes what ships: when the game's
   own English strings name the design's content units (`course.1` .. `course.12` for
   `content_unit_kind: courses`), `content_units` is that count and `content_unit_names` those
   names, and a design figure the build outgrew (six planned, twelve shipped) is recorded in
   `facts.conflicts`.
2. **Capture** (`capture.py`, `capture.mjs`). The bundle is served by the Factory's own
   static server on 127.0.0.1 (no package manager, no preview server); the capture script
   runs in the checkout on Node, resolving the game's own Playwright, behind the refusing
   proxy (`wgflib.netguard`), which the script also hands the browser as its launch `proxy`,
   so it holds on every platform (recorded as `set-not-enforced` only when it was not). It
   plays the build through its play probe exactly as the playability bot does - the probe is
   read, never acted through; the oracle plays well - on a landscape and a portrait viewport
   (the design's orientation first), and takes the scenes `core/reference/store-listing.yaml`
   names: the title screen, play early, play after several inputs, play late, the result
   screen. When the probe declares the optional showcase (`play.showcase`, "the play probe
   showcase" in `docs/template-contract.md`), the script then asks it, after play and its
   result screen, to stage up to `showcase_max` (6) of its targets, one by one, as the
   playability bot does: `show(id)` within 6 s, the probe reporting `playing`, the screen
   settled about 1 s, then a frame `showcase-<asset>` with its probe state; each visit is
   recorded in `capture.json` (`showcase.visits`: staged, refused, timeout, error, skipped once
   the 30 s window is spent). These are real states of the shipped build that the first
   seconds of level 1 never reach (a later level, a boss), so selection takes them as
   candidates, ranked after `play-mid`/`play-late` and before `play-early`, under exactly the
   same readability and distinctness bars. A game without a showcase is captured as before;
   the recording is of play only, and the copy never reads the showcase. A separate context
   records `trailer.seconds` of play as video; Playwright's
   bundled ffmpeg (found through its registry, else under the browsers path) cuts it to play
   and, when it has an H.264 encoder, derives an mp4 - else the listing says `untrimmed` or
   `webm only`.
3. **Selection** (`package.select_screenshots`). Play frames lead, the title screen comes
   last; a frame in an excluded probe state (`loading`, `other`), below the readability
   floors (`frame_bars`, the playability step's), or indistinct from an earlier one of the
   same viewport (`distinct.min_changed_fraction`) is dropped with its reason. Fewer usable
   frames than `renditions.screenshots.min`: the capture runs again with a longer play
   window, `retries` times, then the listing says `screenshots-insufficient`.
4. **Branding** (`brand.py`). One HTML page lays out every rendition from the game's own
   material - palette tokens, display face (the bundle's font asset), the player asset over
   the ground colour as the icon (else the title's initials in the display face), the best
   play frame under a title band as thumbnail and promo, the title as wordmark - and the
   capture script screenshots each box (`browser-composed`). With no browser the icon,
   thumbnails and promo are crops of the best play frame and there is no wordmark
   (`frame-derived`, said so).
5. **Copy** (`copywriter.py`). The `template` writer assembles English from the facts - the
   first sentence is the objective in the player's words, then the loop, the mechanics,
   what ends a run, the controls per device, the session length, the look - and, in every
   locale the bundle ships strings for, the game's own title and objective or rules text.
   The keys are the game's own: the template's (`title.heading`, `hud.objective`,
   `title.rules`) or another name (`game.title`, `play.objective`), else the key whose
   English string is the design's objective, else a key named `*.objective`, `*.goal`,
   `*.rules`, `*.howto`; a string with a placeholder is a label, never copy. It never
   translates: a locale a platform requires with no strings and no agent is a missing
   deliverable (`locale-missing`). A `command` writer (an agent host, read-only, once per
   locale) may write instead; its texts go through the same grounding check and a refused
   answer is asked once more with its problems, then the template text stands in
   (`writer.fallback: true`). Texts are fitted to the canonical bounds at sentence or word
   boundaries, never mid-word. Which writer writes is the run tier's (`writer.kind: auto`,
   the default; see [Copy grounded in the build](#copy-grounded-in-the-build-ws-9)): the
   copywriter agent at the release tier, the template for development runs.
6. **Grounding** (`grounding.py`). Every text is checked against the claim vocabulary
   (`claims`): a term that promises a capability - multiplayer, leaderboards, cloud save,
   achievements, controller, 3D, levels, story, bosses, endless, offline - needs its backing
   in the facts (an `sdk:` capability, an `engine:` dimension, a `feature:` text, a `design:`
   field); superlatives the vocabulary forbids are errors; rating adjectives are warnings;
   every feature bullet names the fact it comes from and shares words with it. A text the
   build contradicts is an error (`contradicted-claim`): a count of the content units other
   than the build's ("six sky courses", "шесть небесных трасс" - the unit word in another
   locale is read from the game's own strings), or "no buttons" beside a control that names
   a button. A count of a subset ("the last two courses") or of something else ("ten gems
   per course") is not one. The template writer leaves out a design sentence the build
   contradicts instead of quoting it. Where the build was measured, every count is held to
   the measurement instead (`count-mismatch`, `unmeasured-count`), a feature the design's
   evaluation cut may not be named (`excluded-feature`), and a bullet in another language
   than its source is grounded on the source's numbers (`bullet-number-unbacked`), not on
   shared words - below.
   A person may write a locale's copy themselves: `<copy_dir>/<locale>.json` (a localeCopy;
   default `workspace/titles/<title_id>/listing-copy/` in the project) is used instead of the
   writer for that locale, recorded in `copy.supplied`, and grounded like any other text. A
   check that fails on it is `fix: configure`: the person fixes their file; another pass
   would not.
7. **Platform renditions** (`platforms.py`, `package.render_platform`). For each targeted
   platform (`listing.platforms` when set, else the verified build's - the
   verification-report's `platform_readiness`, which is what the release packages - else
   the scaffold-record's `game_config.platforms`: a title retargeted after init has a
   scaffold-record naming its first targets), the
   profile's `store_listing` block becomes an explicit requirement list - texts and their
   limits, tags and categories, icon and covers with sizes, aspects and formats, screenshots,
   video, locales, age rating, file naming. Images are cover-cropped and downscaled from the
   canonical masters and **never upscaled**; texts are cut to the limits; tags mapped through
   the portal's vocabulary when the block has one; the trailer included when its container
   is accepted. Everything the package cannot make is an `unmet` problem on the rendition -
   a size larger than any master, a format no encoder here writes (`jpg`/`webp` come from
   the browser's encoder during the capture; PNG from the Factory), a locale no writer
   produces, an age rating nobody stated (`factory.listing.age_rating`). The age rating
   is the platform's, not a locale's: the rendition carries it (`age_rating`) even when no
   copy could be written in a required locale. Screenshots follow the block's `aspects`
   (cropped to the proportion of the capture's own orientation), are downscaled to
   `max_long_side` (a capture under `min_long_side` is a `size-below-minimum` problem, never
   upscaled), and are written as RGB "24-bit" PNGs where `transparent: false`; so are images
   whose requirement says `transparent: false`. A portal's own instructions field
   (`how_to_play`) is filled from the copy's controls text. A required locale with no copy leaves that
   platform's texts and categories empty; validation names the locale as the cause and
   marks those checks `fix: configure`, so the run blocks for a person instead of routing
   back to `listing` until the loop limit.
8. **Validation** (`validation.py`). The judge, shared with `scripts/wgf-listing.py`: every
   canonical rendition present at its size and unchanged; the copy within bounds, the first
   sentence not an article; the screenshots present, in an allowed state, readable, distinct;
   the trailer a video within bounds (or an honestly reported fallback, which fails only
   where a platform requires a video); no unbacked claim in any text that reaches a platform;
   every platform rendition against its requirement list - a text within its stated
   `min_chars` and `max_chars` in every judged locale (how-to-play on the controls text),
   screenshots against `aspects`, the long-side bounds and the alpha rule (a frame below the
   long side is `fix: configure`: the capture size), images with an alpha channel where
   `transparent: false`. A requirement a profile leaves
   `null` is **UNKNOWN**: listed per platform in `unknown`, never counted as passed. The
   copy is judged against the build at the run's tier (below): its counts, its controls,
   each required locale's full description, its subtitle and its writer.

## Copy grounded in the build (WS-9)

The two 2026-10 validation listings shipped copy a person replaced
([quality-gap-audit-2026-10.md](quality-gap-audit-2026-10.md) I-23, WS-9): it said "six
floating-island courses" beside a build of twelve, its controls line named touch while the
build also took the mouse and the keyboard, the `ru` description Yandex requires was the
in-game objective line, the Russian copy carried English words to pass the cross-locale
check, and a subtitle said only the genre. Each is now a check, built from reference data
(`core/reference/store-listing.yaml` 1.2.0 `counts`, `controls`, `copy.full_description`,
`copy.subtitle_generic_words`, `writer`) and the run's own reports - never from a game:

| What | Read from | Check (listing-validation) | Required when |
|---|---|---|---|
| Every count of a counted noun (units, groups, climax units, modes) equals the build's | the content-sufficiency report of the listed build - its commit, or the development commit the sdk commit sits on (`facts.measured`); modes from the design's features the WS-5 evaluation included | `grounding.counts.<locale>`: `count-mismatch` always; `unmeasured-count` (a count nothing measured) | mismatch always; unmeasured where the tier holds `quality-benchmark.yaml` `store_listing.copy_counts_match_build` (a warning otherwise) |
| A cut or deferred feature is never named | `features[].evaluation` (`facts.features_excluded`) | `grounding.<locale>` (`excluded-feature`) | always |
| The controls text names every input the build accepts | the design's MVP `build_spec.controls.actions` per device, and the probe's `inputs` while the listing was captured (`facts.probe_inputs`: a pointer on the mobile viewport is touch, on the desktop one the mouse; a key the keyboard) | `metadata.<locale>.controls`; a language with no device words is UNKNOWN | `controls_cover_all_inputs` |
| Every required locale (en and each targeted platform's) is a full description | `copy.full_description`: title, short, long (at least `long_description.min_chars`, several sentences, not the short again), controls | `metadata.<locale>.full_description` | `full_description_per_required_locale` |
| A bullet in another language than its source fact is grounded on the source's numbers and the measured counts, not on shared English words | the bullet's `source` | `grounding.<locale>` (`bullet-number-unbacked`) | always |
| The subtitle names this game, not only its genre | `copy.subtitle_generic_words`, the genre labels, the tags | `metadata.<locale>.subtitle` | always |
| The copywriter agent wrote it at the release tier | `writer.by_tier` | `metadata.writer`: `fix: configure` when no agent is configured (BLOCKED for a person), `rewrite` when its text was refused and the template's stands in | the release tier |

The run's tier is the step's `with: quality_tier`, else the run's quality snapshot
(`core/reference/quality-policy.yaml`), else the design's or strategy's content tier; with
none stated the listing is a development one. The listing records it with the bars in force
(`facts.quality`), and listing-validation judges at it. Russian number words and the
unit's word in each locale (read from the game's own strings, "Course {n}" / "Трасса {n}")
are understood; a count of a subset ("the last two levels") or per unit ("ten gems per
level") is not a count of these; the head noun of the phrase is what is counted ("six
floating-island courses" counts courses).

**The writer.** `factory.listing.writer.kind: auto` (the shipped default) takes
`writer.by_tier`: the copywriter agent (`command`) at the release tier, the template at
`mvp` and for a run whose tier is unstated. The copywriter's brief carries its role's focus
(`core/roles/roles.yaml` `copywriter`), the measured counts as the only counts it may
state, every device the build accepts, what a full description is in a required locale,
what the design cut, and - re-entered through triage - the store-copy findings
listing-validation raised against the previous copy for that locale. Its answer is refused
(and asked once more) for an ungrounded text, a count the build did not measure, a device
left out of the controls, a generic subtitle, or a required locale that is not a full
description. The autonomous profile configures it (`workspace/config/profiles/autonomous.yaml`
`listing.writer`, the shipped commented example verbatim). At the release tier with no
agent configured the template writes and validation blocks on `metadata.writer`: configure
the agent, or supply the copy (`copy_dir`) - a person's copy is never re-judged as the
writer's.

**The route.** listing-validation's FAIL (`listing`) goes to `listing-triage` - the triage
step ([specialist-routing.md](specialist-routing.md)) after G4 - which normalizes the
report into quality findings (`metadata` and `grounding` checks are store copy, the
copywriter's; screenshots and branding the 2D artist's; a platform rendition the
integrator's) and routes them as ONE store-listing pass (`listing`): one capture, one
render, one rewrite, the copywriter briefed with the store-copy findings
(`copy.writer.findings`). The pass is bounded on store-listing
(`max_visits_by_route: listing-triage.listing: 2`) and on listing-triage
(`listing-validation.listing: 2`).

## Outcomes

| Step | Outcome | When |
|---|---|---|
| `store-listing` | SUCCESS, `status: complete` | every canonical rendition, enough screenshots, copy in every required locale, every platform rendition |
| | SUCCESS, `status: incomplete` | something required is missing or fell back; `problems` says what. Loud, never silent: validation decides whether a person must act |
| | BLOCKED, `status: blocked` | a required gate not passed; no checkout, HEAD not the verified commit, the bundle not the verified one; `capture.kind: none`; no browser / no Playwright in the checkout; the build answered no play probe |
| | FAILED (not retryable) | the verification did not pass, or the qa-report and verification-report name different commits |
| | FAILED (retryable) | the capture timed out or crashed |
| `listing-validation` | SUCCESS (PASS) | no required check failed; `unknown` lists what the profiles do not state |
| | FAILED, route `listing` | a required check failed that the step can act on (`fix`: recapture, rerender, rewrite): the workflow routes it through `listing-triage` back to `store-listing`, twice, the copywriter briefed with the store-copy findings |
| | BLOCKED | every failed check needs a person (`fix: configure`): a required locale with no writer, no copywriter agent at the release tier, a missing age rating, a format no encoder writes, a profile asking for more than any master; or the listing itself is blocked |

The route back to `store-listing` is bounded (`max_visits_by_route: listing-triage.listing: 2`);
G4's `iterate` comes through both steps again, so each carries develop's bound plus its own.

## The release step

`release` consumes `store-listing` and `listing-validation-report` (`with: required_listing`,
default true; a workflow without the listing steps says `required_listing: false`), and
refuses:

| Code | Outcome | Means |
|---|---|---|
| `no-store-listing` | BLOCKED | no listing in the run: run `store-listing` and `listing-validation` |
| `listing-commit-mismatch` | FAILED | the newest listing shows another commit than the one shipped |
| `listing-incomplete` | FAILED | the newest listing's status is not `complete` |
| `listing-not-validated` | BLOCKED | no validation report, or the newest judged another listing (by hash) |
| `listing-not-passed` | FAILED | the newest validation's verdict is not PASS |
| `listing-package-missing` | BLOCKED | the listing's package is gone from the run directory |

Otherwise it copies the package to `release/<release-id>/listing/`, fills
`store_metadata` per platform (title, descriptions by locale, screenshots, icon, age rating,
`locales_included`, with paths relative to the release directory) and records
`evidence.store_listing` (release-manifest 1.3.0). G6 is decided on `release-manifest`,
`store-listing` and `listing-validation-report` (`core/lifecycle/gates.yaml`).

Every rendition carries the copy of every locale the canonical package has: the platform's
required locales first, then the others, each cut to the platform's limits. A required
locale's checks are judged on that locale alone - another locale never stands in for it -
but the others reach the portal: the release fills `store_metadata.<pid>.descriptions` per
locale from them, and the submit step's console fills a per-locale description field in
each (`wgf_publish.campaign`, docs/publish-module.md "The campaign").

## The campaign the portals are filled from

The shipped listing is the campaign package every portal field and medium comes from
(`scripts/wgf_publish/campaign.py`); a portal adapter never invents campaign content.
`listing-validation` runs its media check against each platform's publication profile too
(`platforms.<pid>.media.<code>.<n>` checks): every screenshot and the trailer must trace to
the capture record of the verified build (the screenshot's `source`, the recorded trailer,
their sha256; the listing's commit, `measurement_class: automation-bot`, `capture.kind:
browser`) - else `no-provenance`, fix `recapture`; an asset-pipeline placeholder is
`placeholder`; the publication profile's required media, `formats`, `max_count`, intent
`accept` and `multiple`, and per-locale media are judged, and what it leaves unstated is
UNKNOWN. Store-listing 1.2.0 adds an optional `locale` to a file record, for a file that is
one locale's own; without it a file serves every locale. The platform profile's `video`
block takes an `orientation` list. The submit step runs the full check again before any
upload, with the shipped build's commit.

## Platform requirements are data, and unknown is unknown

`core/artifacts/shared/platform-profile.schema.json` `storeListing`: text limits, list
limits (with the portal's own vocabulary), image requirements (sizes, aspect, formats,
`max_kb`, which canonical family they render from), screenshots, video, locales, age rating,
naming. Every limit may be `null` = **not known**; `status: verified` says every figure was
read from `source`. The shipped profiles state what their sources say and nothing more:
GameDistribution's thumbnail sizes come from its developer guidelines, the cover aspect
ratios CrazyGames asks for are stated, Yandex's `ru` and age rating follow its binding
requirements; every pixel size and text limit nobody has read is `null`. Filling a block in -
with the portal's documentation URL and date - is done once per portal, not once per game,
and `python3 scripts/wgf-listing.py requirements` lists what is still unknown. A profile's
`version` does not move for the block: the listing records the block's own hash per platform
(`platforms[].spec_hash`) instead, so what a rendition was made under is pinned.

## Configuration

`factory.listing` in `workspace/config/factory.yaml` (every key optional; a step's `with:`
overrides any): `capture.kind` (`browser` | `none` - BLOCKED), `capture.node`,
`capture.timeout_seconds`, `capture.trailer`, `capture.viewports`; `writer.kind` (`auto` -
the default, the run tier's writer - | `template` | `command`), `writer.argv` (`{brief}`
`{output}` `{prompt}`), `writer.text_from`,
`writer.timeout_seconds`, `writer.idle_timeout_seconds`; `platforms`; `locales`;
`reference`; `age_rating` (per platform id or `default`); `copy_dir` (a person's own copy,
`{title_id}` substituted, relative to the project; null turns it off). The capture runs with the game
environment (`factory.agents.game_env_passthrough`), the writer with the agent environment
(`factory.agents.env_passthrough`). Child variables: `WGF_LISTING_BRIEF`,
`WGF_LISTING_OUTPUT` for the writer ([env-vars.md](env-vars.md)).

## Evidence and honesty

- `measurement_class: automation-bot`: moments chosen by a bot through the probe, never a
  person's eye. Playing with `?wgf-probe=1` enables the oracle only; the probe draws nothing.
- Nothing is upscaled, translated, or invented: a smaller master, a missing locale, a
  missing age rating, an absent encoder are problems on the listing and failures or blocks
  in validation, never quiet substitutions.
- A trailer that could not be made is a labelled frame sequence (`status: fallback`), never
  presented as a video; one that could not be trimmed says how many milliseconds precede play.
- The platform renditions carry `spec_status` (`verified` | `unverified` | `absent`) and the
  validation report `unknown` per platform. PASS means "passed what the profiles state".
- `network_guard` records whether the refusing proxy governed the browser: `enforced` when
  the capture handed the browser the proxy itself (`proxied` in capture.json) or on Linux;
  `set-not-enforced` otherwise, since Chromium ignores the proxy environment off Linux.

## Tests

`scripts/tests/test_listing.py` (offline; a fake capture runner writes synthetic frames, a
synthetic WebM and the branding images in `capture.json`'s shape): imaging and the media
readers (PNG, WebM, MP4 headers); facts with their sources; the template writer's bounds,
grounding and locale behaviour; the grounding check's errors and warnings; platform
requirements and the UNKNOWN markers; screenshot selection; platform rendering (sizes,
never upscaling, unmet problems, age rating); the step (complete, retries with a longer
window, incomplete on dark frames, the trailer fallback, no browser, a crash, kind `none`,
the gate, the checkout, the bundle, a failed verification, a command writer refused and
replaced); validation (PASS with unknowns, FAIL routed back, grounding, BLOCKED for a
person, a video a platform requires); the mock steps; both steps through the real engine;
the release step shipping the listing and refusing without it; the bundle server.
`scripts/tests/test_listing_build.py` holds the copy to the build (WS-9): the audit's
regressions fail - "six courses" beside twelve measured (in English and Russian), a controls
line naming touch only, an objective line as the `ru` description, a genre-only subtitle, a
Russian bullet held to numbers instead of shared words, a cut feature named, the template
writer at the release tier - a correct `en` + `ru` listing by a fake copywriter passes at
the release tier, a report of another build measures nothing, and the copywriter route is
taken: listing-validation's FAIL through listing-triage (route `listing`, one pass) back to
store-listing, whose brief carries the findings, also through the shipped workflow with mock
steps.
`RealBuild` captures a real build when `WGF_LISTING_BROWSER=1` and `WGF_LISTING_REPO` name a
checkout with `dist/` and Playwright. The golden runs (`WGF_GOLDEN=1`) run both steps on the
replayed games for real and assert a complete, validated, shipped listing (`summary.listing`).

The first real capture ran against the 2D golden game's build on a Windows machine: 6
screenshots on two viewports (play first, title last), an 18.8 s VP8 trailer trimmed to play
with Playwright's bundled ffmpeg (no mp4 encoder in that build, recorded as such),
browser-composed branding from the design's palette and the game's title, copy in `en` and
`ru` with no unbacked claim, renditions for poki, crazygames and yandex; validation PASS for
poki and crazygames with their unknown limits listed, BLOCKED on yandex's age rating until
`factory.listing.age_rating` states one.

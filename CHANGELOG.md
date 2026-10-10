# Changelog

Notable changes to the methodology. A change here can invalidate an artifact that already
exists, so each entry says what it would take to bring one forward.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). The Factory is
released as a whole (`v1.0.0` is Core v1, frozen); schemas still carry their own versions,
and `core/` is still the contract.

## [Unreleased]

**K6 review r1 fixes** (docs/specialist-routing.md, docs/knowledge-enforcement.md). The
ledger no longer verifies a split finding (`.../develop`, `.../assets`) whose check still
FAILs its part in a BLOCKED report: the check is split again by the same rule, `unmeasured`
when its part cannot be established. The run ledger's reopen (quality gate, release)
refreshes the record's `build` and `failed_measurement`, so a re-play of the reopening build
is held `same-build` and `before` names that failure. A record's regression baseline keeps,
per check, the newest measurement the ledger recorded when the newest report left the check
unmeasured (a BLOCKED report no longer erases an earlier pass). Evidence strength reads the
run's newest ledger (a newer quality-report's `ledger.lifecycle` over the last
triage-report's) and refuses a repair it reopened; a re-play of the build that passed is no
independent repeat, and validated contexts differ in the commits measured - two runs replaying
the identical commits are one context (`evidence-strength.yaml` 1.2.0, review r2). A held finding whose check stops applying has no in-run
close - documented as a known limitation. G4's assessment lines also count the checks not
reported. Bringing an artifact forward: none - existing ledgers and candidates stay valid; a
candidate's strength is derived again on its next ingest or promote.

**Core v1 change: `scripts/wgflib/gate_evidence.py`** (K6.3; reason: G4 is decided on the
quality-report, and a person must see its assessment - the three questions, each check's
measurement class, a PASS resting on the game's own report or one AI judgment named so, the
checks not reported - to decide it). Display only: it adds the assessment lines to the
evidence the CLI shows for a waiting checkpoint (`status --json` `pending.evidence`), reads only the report's
`assessment` section, and decides nothing - no gate, verdict, route or release decision reads
it.

**Validated learning: a lesson's evidence strength, derived from the ledger** (K6.4,
`core/reference/evidence-strength.yaml` 1.1.0, candidate store 1.1.0, `evidence.yaml` 2.1.0,
[docs/knowledge-enforcement.md](docs/knowledge-enforcement.md) "Evidence strength"). `wgf
knowledge ingest` now records, for every lesson candidate, how far the measurements behind it
were repeated - `hypothesis` (no measured repair), `single-run` (one FAIL->PASS pair),
`reproduced` (the pass repeated in a later independent report on a later commit than the
one that passed, on a check that does not alternate verdicts, by a class that is not only the
game's probe), `validated` (reproduced in two contexts differing in run or commit - desktop and
mobile of one run and build are one context) - derived from each source's re-measurement in its run's finding ledger
(K6.2 before/after/samples, content hashes, history) and the check's measurement class (K6.3),
with why (`strength_why`), the checks marked `unstable`, and every measurement refused with its
rule and reason (`refused_evidence`): the detecting report counted again, the lesson's own
proposed check on a build that motivated it, a pass on the failing commit (or a re-play of the
build that passed, counted as a repeat), a repair the run's newest ledger reopened, a judge
re-reading
what it judged, a person's or specialist's claim; hash-identical duplicates count once. A pair
measured only by the game's own probe, one AI judgment, or a check of no known class is capped
at single-run. `wgf knowledge promote` derives the strength again from the run store and never
drafts a classification beyond it: a measured candidate held only by an advisory check is
drafted an experimental candidate lesson on hypothesis or single-run evidence, a
RECOMMENDATION on reproduced, and may be drafted a VALIDATED_PRINCIPLE (`--classification`;
an enforced, validated lesson with its three test stubs and the evidence's `verified` leg) on
validated evidence; a classification asked for beyond the evidence is refused. **BLOCKING and
REQUIRED are unchanged**: still derived only from the check tiers (K4). Strength is about a
measurement repeating, not about player value. Bringing an existing artifact forward: none -
stored candidates without the fields stay valid, and get them when a new source merges
into them or their run's ledger re-measures a source's finding on its next ingest; promote
derives them regardless.

**Repairs verified on the same scenario** (playability-report 1.4.0, triage-report 1.3.0,
[docs/specialist-routing.md](docs/specialist-routing.md) "What counts as a re-measurement",
[docs/playability-module.md](docs/playability-module.md) "The scenario each check was
measured on"). Every playability check names a stable scenario, `<check>@<project>`, and the
report lists what the bot played for it, read from the records it already writes: the bot
version (sha256 of bot.spec.ts) and settings, the viewport, the policy and seed, the records
with their sha256, the inputs and probe states those records list, the frames with their
sha256. The finding ledger now verifies a finding of a producer that lists its checks
(playability, production-quality, listing-validation) only when the same check on the same
project was measured and passed: a newer report that leaves the check unmeasured (BLOCKED,
SKIPPED, WARNING, `measured.unmeasured`), no longer lists it, lists it only on another
viewport, or - for playability - passes it on the commit it failed on, **no longer verifies
the finding**; it stays open with the verdict `unmeasured`, `missing` or `same-build`, said
in its history. A FAIL check in a BLOCKED report still fails. Each verification keeps the
failing and passing measurements (`before`, `after`) and a `comparison` naming every
difference (a newer bot, other settings: a weaker comparison, said so), and `samples` of the
passes after it. **A regression now needs a prior pass**: a failure after a fix is its
regression only when its check passed in the record's `baseline` (what the gates had
measured when it was assigned) or it was verified before - a gate measuring for the first
time raises a new finding, not a regression (the real 2D/3D runs: nine fixes never verified
for this). History entries name the artifact's content hash and seq beside its id. A done finding whose raising producer's newest report fails it again is reopened also when
the quality gate or release advances the ledger (`ledger.remeasure`, no triage findings of its
own) - replaying the real 2D run's ledger left two findings closed beside the report failing
them. Existing
artifacts stay valid (every change is additive); a ledger written before this keeps the old
regression rule for its records (no baseline). An open finding of a run in progress that the
old rule would have verified on an unmeasured, missing or same-commit pass stays open on
resume until its check is measured passing.

**The quality assessment: three separate questions, and how each was measured** (K6.3,
quality-report 1.5.0, `core/reference/quality-assessment.yaml` 1.0.0,
[docs/quality-assessment.md](docs/quality-assessment.md)). The quality-report gains an
additive `assessment` section that reads the evidence the gate already read as design
validity, runtime correctness and player-facing quality - each PASS, FAIL, INCONCLUSIVE or
NOT_SUPPORTED with the checks it rests on (read through check-tiers `status_at`, the reader
knowledge compliance uses), each check's measurement class (deterministic, heuristic,
self-reported by the game's probe, AI-judged; human for a person's G4 decision), the judges'
recorded runs, every blocker or major visual-judge finding listed unresolved whatever its
report's verdict, a PASS that rests on the game's own report or one AI judgment marked
`qualified` or `weak`, and what the evidence cannot justify. A held check that failed fails a
dimension; one that measured nothing leaves it INCONCLUSIVE, never PASS; player-facing quality
is never PASS without a person's G4 decision that pins this build's reports. **It decides
nothing**: the floor, the verdict and the release decision are computed without it (tested
identical with and without it). G4 shows the three lines. check-integrity holds that every
check-tiers source and check is placed in the mapping or excluded with why. Bringing an
existing artifact forward: none - a 1.4.0 quality-report without the section stays valid.

**The golden loop through triage and the finding ledger** (K6,
[docs/golden-runs.md](docs/golden-runs.md) "The develop stage"). The greybox loop never
reached the Factory's own Diagnose -> Repair -> Verify bookkeeping: greybox-playability's
`fail` goes straight back to greybox, so its run's triage-report and quality-report ledgers
were empty. `--defect-stage develop` (`scripts/golden/run.py`, `GoldenRun(defect_stage=)`,
`replay_developer.STAGES`) plants the defect in the first production develop visit instead;
playability's failure goes through triage to the specialist that owns `restart.works` (UI),
and the replay leaves the defect out on the visit briefed with those findings
(`specialist.findings`), keeping it out on later visits (`kept-repaired`). The loop record
(`evidence/golden-loop-2d-develop.json`) closes only when the run's ledger verified the
repair: detected and assigned by triage, implemented at the repairing commit, verified on
the same scenario with the failing and passing measurements and their frames' sha256,
nothing open - the ledger records and the assessment lines copied in. Two more GOLDEN LOOP
classes (`GoldenLoopDevelop2D`, `GoldenLoopDevelopNoRepair2D`; the category is now four
golden runs, its CI job 360 min) and `WGF_GOLDEN_LOOP_DIR` to run each class in a named
directory, or assert a kept run of the same variant; fast checks in `GoldenLoopFast`.
Measured on Windows: closed on `76d9556` -> `c6fb256`, both findings closed in the
quality-report's ledger; the negative control blocked at triage's `playability.fail` budget
with the findings never verified. A negative control's exit status now requires every
report to have failed the planted defect (`loop.control_held`): an unreadable loop record is
`closed: false` too and used to pass it. No Factory change: nothing to bring forward.

**The golden loop: a real closed loop on a real build, no LLM** (K6.1,
[docs/golden-runs.md](docs/golden-runs.md) "The golden loop"). The golden replay developer
takes `--defect NAME` (`replay_developer.DEFECTS`, exact-once rewrites; an anchor not found
exactly once refuses the replay): `restart-dead` makes the 2D port's restart button click
without restarting. It is planted on a greybox visit whose brief names no `restart.works`
failure and left out on one that does, and each visit records which in its report
(`replay.defect`, labelled a replay, never an agent's fix); `--no-repair` is the negative
control. `GoldenRun(defect=, repair=)` / `scripts/golden/run.py --defect NAME [--no-repair]`;
`scripts/golden/loop.py` writes the before/after record (`evidence/golden-loop-2d.json`,
frames under `evidence/golden-loop/`). New Core Acceptance category **GOLDEN LOOP**
(`test_golden_loop`, `WGF_GOLDEN_LOOP=1`): greybox-playability FAILs `restart.works` on both
viewports on commit A with frames, greybox is re-entered, the same check PASSes measured on a
newer commit B, and the run ends in its normal golden outcome; the negative control exhausts
greybox's route budget and blocks with the check still failing. The category is **opt-in**
(`core_suite.OPT_IN`): `wgf test-core` without `--only` leaves it out and lists it as not run
(`opt_in_not_run` in `--json`), so `WGF_GOLDEN=1 bin/wgf test-core --strict` is unchanged; it
runs in its own CI job (`golden-loop`: a manual run with `golden_loop`, or a pull request
labelled `golden-loop`). The playability bot now captures `retry-dead` when a retry never
returns to play, and `restart.works` cites the lose recording's result and retry frames
(before, it cited none). Nothing to bring forward: an existing playability-report stays
valid; a new one's `restart.works` may carry `frames`.

**Cross-session quality transfer, and the first transferred principle (L29)** (lessons
2.1.0, check-tiers 1.3.0, design-consistency-rules 2.4.1, content-sufficiency 1.6.0,
game-design 1.16.0, knowledge-contract 1.2.0, quality-report 1.4.0,
[docs/knowledge-enforcement.md](docs/knowledge-enforcement.md) "Cross-session transfer").
Every lesson now carries a domain, a principle, an anti-pattern, a classification consistent
with its derived level, and a revision; check-integrity fails an entry changed without its
revision rising. A run's contract pins each rule's revision and entry digest. The design
agent is given the applicable rules, structured, from the run's pinned knowledge, and records
a decision trace (`knowledge_applied`) that a new blocking design rule
(`knowledge.trace_matches_design`) holds against the design; compliance shows the trace
beside each rule's measured status. **L29** (blocking): after the opening unit, a unit
introduces at most one element the player has not met - held on the design
(`content.introductions_one_at_a_time`) and on the built content data file (same id). **A
design that debuts two never-seen elements in one unit after the first now fails the design
step** (an agent author is asked to repair it), and a build whose units.json does so fails
content-sufficiency; a units.json that names no unit's elements leaves the check
unmeasured, which a release-tier quality gate holds. The genre seed author's second teaching
unit debuted two mechanics for five families; it now introduces one mechanic per MVP unit
(the opener takes only what the MVP has no unit for). A unit naming no element, mechanic or
introduction leaves the count unmeasured on the design and the build, never a pass. Existing artifacts stay
valid (every schema change is additive). A run is held to the rule files it pinned when it
started: the design step reads the run's pinned design-consistency-rules.yaml and
content-sufficiency its pinned content-sufficiency.yaml, so a run that pinned them before
this change never meets the new design rules or the new build check - not on resume, not
when design is entered again. A run that pinned nothing - every run started before K2 on
2026-10-08, the two paused validation runs among them - is judged by the live files: on
resume it meets the new rules and check. A unit debuts what its non-empty `introduces` lists
(an element and the mechanic it stands for are one introduction); a unit whose `introduces`
is empty or absent is counted by every element and mechanic it shows for the first time, and
on the build (content-sufficiency 1.6.0, design-consistency-rules 2.3.0) every built unit is
also held to its design unit - an element the build shows a unit early is a debut there,
whatever `introduces` it copied. On the design a non-empty `introduces` is trusted; new
elements beside it are not counted there (documented, accepted) - but what it lists must be
true of its unit (design-consistency-rules 2.4.0): an introduced item the unit does not
contain, or one an earlier unit already named, breaches; a unit that states no `elements`
list introducing a declared element is unverified, never a breach (2.4.1). A pinned rule file that is gone,
edited or substituted blocks the design and content-sufficiency steps.

**A run is held to its knowledge, and a person's exception is the run's own record**
(quality-policy 1.4.0 rule 8, new-game 17, gates 1.7.0, knowledge-contract 1.1.0,
[docs/knowledge-enforcement.md](docs/knowledge-enforcement.md)). A new run records the
lessons and check-tiers versions and the Factory's version and commit, pins what its
knowledge is read with, and makes its knowledge-contract after design (`knowledge-contract`
step) or stops; G3 is decided on it. `wgf resume <run> --except` grants a person's
exception: an operator event whose resume nonce, and the digest of what that resume
recorded, the engine keeps in state.json (`resume_nonces`). **Exceptions granted on
`k/integ` before the digests were kept (up to e81a941) are refused**: their nonces were
kept without a digest, or not at all, so nothing can tell them from a forged line - grant
them again. Runs started before rule 8 are advisory and keep their workflow.

**A measurement's validity no longer softens a failure** (visual-quality.yaml 1.2.0,
specialist-routing.yaml 1.5.0, [docs/playability-module.md](docs/playability-module.md)).
Three gaps a review of the validity rules found, closed without loosening a bar. A unit the
traverse stopped inside that the bot played on in for the whole `sample.variety_extend_s` and
that still showed too few new kinds is judged as seen whole - `content.variety` FAILs and its
pair counts - instead of staying unmeasured however long it was played; only an extension
itself cut short leaves it unmeasured. On a host degraded on every attempt, a check that read
a failure or is required is BLOCKED at every tier (re-measure on a quiet host), never a
WARNING the step could PASS over; a game that floods its own host can buy at most that
BLOCKED, never a pass (the documented limit). The ramp recording now carries its host's health
and is made again on a degraded host, and `depth.ramp` / `depth.stall` are judged under the
same rule, so a host stall is never a `depth.stall` FAIL routed to gameplay; `depth.` is now
routed to gameplay explicitly (`default_dimension` did it before). Existing reports are not
invalidated; a re-run playability step re-measures.

**`depth.ramp` is judged on several runs, and a stall is its own finding** (design-depth.yaml
1.4.0, [docs/playability-module.md](docs/playability-module.md)). One endless run per
viewport, cut the moment its first third held 10 inputs, flipped between PASS and FAIL across
commits with identical gameplay code. The ramp test now plays `ramp.samples` (3) fresh runs
of the play that promises the time ramp - the endless play itself, which the session no
longer stands in for, or the endless mode - and pools their thirds against a noise band of
`ramp.noise_z` (2) x sqrt(n): a fall beyond it fails, a rise beyond it on every planned sample
passes, and a difference inside it is extended (`extend_s`) and then unmeasured - never a
pass, a FAIL at the release tier. A new check, `depth.stall` (routed to gameplay), fails a
sample that went over `ramp.stall_max_s` (10 s) in play with no oracle input and no progress,
and that sample is left out of the ramp. `relief_dip_s` was stated and never implemented: it
is removed. Existing reports are not invalidated; a re-run playability step re-measures.

**Publishing merged with the quality work.** Workflow `new-game` 13 carries both: the quality
gate (11), store copy and listing triage (12), and the publication per platform (the submit
step's per-platform visits, the `platform-ids` route back to `sdk` and its visit limit).
Adapter binding 1.11.0 holds the triage surfaces (1.10.0 on main) and the publisher surfaces
(1.10.0 on the publishing branch). release-manifest 1.6.0 adds `packages[].bundle_hash` on
top of 1.5.0; verification-report 1.2.0 adds `build_artifact.platforms` on top of 1.1.1. The
quality floor composes with submit's re-entries: a person's `submit` after an upload, the
next platform or `--track` runs while nothing it rests on changed, and after a
create-before-build portal's `platform-ids` (the run ends naming `sdk`: `wgf sdk --run <id>
--force`, `wgf new-game --run <id>`, `wgf publish --run <id>`) submit is refused until every
check after sdk has passed the new build (`SubmitReentry` in
scripts/tests/test_quality_inheritance.py). A development-class run never reaches a live
submit visit, whichever visit it is.

**The submit step acts per platform, behind G6's integrity, with a person's submit**
([docs/publish-module.md](docs/publish-module.md)). Every packaged platform is handled on
its own (`StepInputs.every`, `RunState.latest_by_id`): one `platform-publication-<platform>`
each, and a wait, a failure or a pending review on one never writes another's record. Before
any upload, G6 must pin by content hash the release-manifest, the store listing and the
listing-validation-report the step holds (else BLOCKED `g6-stale`), the package must be the
bundle verify built for that platform (`build-mismatch`, `wrong-platform`), and the record
must be for this manifest (`stale-validation`). The portal registry is read before the
adapter (`job.known_ids`, `registry_status`, `identity`, `allow_create`) and written after
it, a status only from the portal's own text. `UPLOAD_COMPLETE` waits for a person:
`submit` (review requested once, in a later visit), `hold`, `abandon`, or `done` (the person
requested review by hand). **Create-before-build portals**: a profile's
`identity.issued_on_create` ids are read after create; the visit stops `IDS_ISSUED`
(registry `DRAFT_CREATED`), routes `platform-ids` to `sdk`, which writes them into
game.config.yaml through `identity.build_config`; the build is made, verified, released and
authorized (G5, G6) again; platform-validate's new guard `platform_ids_present` refuses a
build that lacks them. `wgf publish --platform <id>` acts on those platforms only and
`--track` reads every known game's status without changing anything
(`WGF_PUBLISH_PLATFORMS`, `WGF_PUBLISH_TRACK`). The login wait becomes the record's
`waiting` block from the executor's last login handoff. **Publication profile 2.1.0**
(additive) gains `identity.build_config`, keyed by the same `key` as
`issued_on_create` (Y8: `{external_game_id: "platforms[].game_id", app_id:
"platforms[].app_id"}`). To bring a create-before-build profile forward: write each issued
id as `{key, read}` and add `build_config`; a bare string (`game_id`) is still read as the
same key. Nothing else needs to change: a run without issued ids, or on one platform, behaves
as before.

**The console executor runs the profile's flow, and a person logs in live** (portal
publishing workstream 3, [docs/publish-module.md](docs/publish-module.md)). The executor is
a generic intent runner over the publication profile's `submission.flow`: session,
find_game, status_gate, create_game, upload_build, fill_metadata, upload_media,
human_fields, save_draft, request_review, verify. It uses profile locator ladders only,
checks a post-condition after every action, and stops with a `drift` result when a ladder
or a post-condition fails. A person logs in, live, in a headed, ephemeral browser window;
the visit waits `WAITING_FOR_HUMAN_LOGIN`, reports it as step progress and continues in
the same window. A login timeout or a closed window is `AUTH_REQUIRED`, never a failure. A
live visit ends `UPLOAD_COMPLETE`. The review request runs only in a later visit whose job
carries `submit_confirmed`. Every action and waiting period is a line of `actions.jsonl`.
The captured session is gone: `wgf-publish.py capture`, the storage-state copy and
`WGF_PUBLISH_<PLATFORM>_STORAGE_STATE`. The adapter selector maps and
`ConsoleAdapter.listing_fields` of the entry below are replaced by the profile's flow.

**Publication profile 2.1.0** (additive): credential kind `human-login` (`storage-state` is
deprecated and refused by `check-integrity.py`), `session.authenticated_url`,
`identity.page_id` and `identity.issued_on_create`, `status.error`, and an upload intent's
`multiple`. To bring a profile forward: set `credential: {kind: human-login}`, drop `env`
and `capture`, and bump its version. Delete any `WGF_PUBLISH_*_STORAGE_STATE` variables and
the session files they named.

**GameDistribution and GamePix as modeled targets** (facts read 2026-10-04 from public pages
only; [docs/platform-targets-2026-10.md](docs/platform-targets-2026-10.md)).
GameDistribution's publication profile 2.1.0 records the documented flow (account, Game ID
from the panel before the build, upload, pre-roll viewed from the upload view, a publication
request button, review), the listing fields of guidelines section 5, the developer terms'
restrictions and its review timelines, which disagree across four pages. A domain is not
required for a developer account; self-hosting needs written consent (real multiplayer only)
and one's own HTTPS host, modelled as the profile's first `prerequisites` entry. Publication
profiles gain an optional top-level `prerequisites` (no schema version bump: additive):
readiness reports an applicable one HUMAN_REQUIRED (`legal` | `declaration`) until a person
records it in `factory.publish.platforms.<id>.prerequisites_confirmed`. GamePix gains
`core/reference/platforms/gamepix.yaml` 1.0.0 and `core/reference/publication/gamepix.yaml`
2.0.0 (content policy `disclose` from its developer agreement 4.10). The template lock records
`platform_adapters`, the pinned registry's adapter ids, held equal to the pin by
`check-integrity.py`; strategy and tech-plan refuse a platform outside it ("GamePix needs a
template release carrying its SDK adapter (HUMAN_ACTION_REQUIRED: release and pin)").
Existing artifacts are unaffected; a lock without `platform_adapters` stops strategy and
tech-plan.

**The console fills every listing field, per locale** (portal publishing workstream 1,
[docs/portal-publishing-architecture.md](docs/portal-publishing-architecture.md) Part 4).
The console adapter never filled a description: it asked the store metadata for a
`description` key, but the store metadata stores `descriptions` keyed by locale.
`ConsoleAdapter.listing_fields` now fills title, short and long description, controls, tags
and categories from the shipped store listing's rendition
(`release/<id>/listing/platforms/<pid>/listing.json`), falling back to the store metadata.
A `{locale}` in a field's selector makes the field per locale. Required fields and locales
come from the platform profile's `store_listing` block and `metadata_requirements`. A
required field with no value, or with no console field, is reported (BLOCKED) before
anything is contacted. In the browser, the executor reads every value back before and after
saving. A required field missing from the page ends `configure` as an error. Optional fields
the step did not fill are named in the record. The fixture portal has per-locale
short/long description fields (`PORTAL_LOCALES`) and a `missing-field` mode. No schema or
artifact changes; the Yandex and CrazyGames selector maps, still hypotheses, report the
required fields they do not name.

**Publication profile 2.0.0** (workstream 2 of
[docs/portal-publishing-architecture.md](docs/portal-publishing-architecture.md)). The
console flow becomes data: `submission.flow` holds ordered intents, each with a phase and a
class (`reversible` | `irreversible` | `human`), a locator ladder, a value that is a path into
the shipped listing (never free text) and a post-condition; `session` and `identity` name how
the session and an existing game are recognised; `status` (was `verification`) gains
`pending_states` and `approved_states`; `constraints.upload_max_mb` (was
`console.upload_max_mb`); `fields` with the console's limits; `content_policy` for generated
text and assets (required; every shipped console says `unknown`); `adaptive`,
`adaptive_bounds` (at most 3 per intent, 10 per visit), `dismissable` and `deny`; top-level
`sources` and `unknowns`. **Breaking** for a 1.x profile: rename `verification` to `status`,
move `console.upload_max_mb` to `constraints`, add `content_policy`, and for a console add
`adaptive`. Every shipped profile is migrated to 2.0.0; the console profiles (CrazyGames, Y8,
Yandex, GameDistribution, GameMonetize) were written from public pages only, name what a
person must log in to learn under `unknowns`, and stay `status: unverified`.
`check-integrity.py` checks every profile's flow (`wgflib.publication.flow_problems`): no
cancel, withdraw or delete intent; every irreversible intent has a profile ladder; every
intent has a class; adaptive names outside the deny vocabulary; status words consistent.
`platform-publication` 1.2.0 (additive): `submission.portal_game_id`, the `human_required`
reasons `legal`, `declaration`, `ai-text-policy`, `duplicate-candidate`, `review-pending`,
`drift-irreversible`, `anti-bot`, and `measurement_class: automation-console-adaptive`. The
console adapter reads `status` and `constraints.upload_max_mb`; nothing else changes
behaviour yet - the executor runs profile intents from workstream 3.

**One build, one package and one publication per target platform** on the pinned template
(contract 1, v1.2.0), with no template release and no game migration. For a title with more
than one target, `verify` builds each platform against `build/platforms/<id>/game.config.json`
(that platform alone) through the template's own `WGF_GAME_CONFIG` override, judges each
bundle (`build.platform:<id>`, `platform.build-target:<id>`, requirements and profile
assertions on its own bundle) and requires every target - an `optional` platform that is not
ready now fails the verdict. `release` packages each with `release:package --platform <id>`
from its own verified bundle (`packages[].bundle_hash`) and refuses a target without one
(`platform-not-verified`); `store-listing` renders for the verified build's platforms;
`platform-validate` writes one publication per package. A repository on template contract 2
(`build:platforms`) is recognized and builds its platforms itself. A single-platform title is
built and released exactly as before. **Retargeting a finished title** no longer re-runs
develop: the `sdk` step (new input: `tech-plan`) writes the G3-approved platforms and their
profiles into its keyed commit when they differ from the checkout. Schemas:
verification-report 1.2.0 (`build_artifact.platforms`), release-manifest 1.6.0
(`packages[].bundle_hash`), both additive; template contract 2.0.0 (entries recorded, version
unchanged). Docs: [platform-targets-2026-10.md](docs/platform-targets-2026-10.md) Part 2,
[verification-module.md](docs/verification-module.md#one-bundle-per-platform),
[release-module.md](docs/release-module.md#one-package-per-target-platform).

**The Factory quality gate** (WS-7 of [docs/quality-gap-audit-2026-10.md](docs/quality-gap-audit-2026-10.md); workflow `new-game` 11, `quality-report` 1.0.0, specialist-routing 1.2.0, `core/reference/quality-floor.yaml` 1.0.0, quality-benchmark 1.6.0, gates 1.6.0, release-manifest 1.5.0, verification-report 1.1.1, playability-report 1.2.1, content-sufficiency-report 1.0.1). Every producer judged one side of a build on its own bar, and a build whose UI broke on one viewport while every other side scored high still reached G4 looking finished. The new `quality-gate` step (`scripts/wgf_quality`, after `verify`, before G4) scores ONE build on twelve dimensions - gameplay, content, variety, progression, visual, UI, audio, consistency, polish, technical, platform, store - from the reports the producers wrote about that same build, against a versioned two-layer contract: the universal floor every game carries (layer A) and its genre family's contract plus the 3D contract (layer B; an unknown family takes its nearest ancestor's, and always the universal floor). Each dimension has a hard floor: no averaging passes a dimension below a failed blocker, and a dimension below its floor is a QUALITY REGRESSION, routed through triage like every gate's failure (the `quality-report` producer of scripts/wgf_triage): `design` for a design gap, `assets` for an asset, else the specialist that owns the dimension. Evidence about another commit BLOCKS the gate. A finding closes only when a newer build is measured at the minimum. The release tier's presentation bars (visual-qa mean 4.0, no major and at most four minor findings, every production check, audio counts, no skipped content check) are now enforced on the build. A run at tier mvp is `development`, never release. G4 is decided on the quality-report and shows its scorecard; release refuses (`quality-*` refusals) unless the newest quality-report passed exactly the build it ships and pins the run's newest reports of it; a `development` decision is drafted and recorded as such in the manifest's `evidence.quality_report`, beside WS-12's run class (`evidence.quality`). The quality policy (WS-12) now enforces `quality-gate` as a required step: it is no longer `pending` (quality-policy 1.2.0). Anti-gaming: a workflow's `pinned_references` (new engine feature, `scripts/wgflib/workflow/references.py`) are copied into the run at its start and pinned by digest in its params, so a mid-run edit of the floor, the benchmark or the rubric applies to the next run only. Bringing an artifact forward: a run resumed under workflow 11 runs the quality gate before G4 (its pins are absent, so it reads the live contract and records `benchmark.pinned: false`); a release drafted by a workflow without the gate says `required_quality: false`. Docs: [docs/quality-gate-module.md](docs/quality-gate-module.md), [docs/factory-quality-benchmark.md](docs/factory-quality-benchmark.md).

**Every `new-game` inherits the quality policy** (WS-12, [docs/new-game-quality-inheritance.md](docs/new-game-quality-inheritance.md); release-manifest 1.4.0). `core/reference/quality-policy.yaml` (1.0.0) states, as data, what every run is held to, and the engine applies it without naming a step (`scripts/wgflib/workflow/quality.py`). A run snapshots its quality tier, its class (`release` or `development`) and the policy and benchmark versions in `params.quality`, corroborated like every param; strategy and assets read the tier from the run. Before G4, release, platform validation and submission, every required check before them - research, design, both playability passes, production-quality, visual-qa, review, sdk-review, verify, listing-validation, and `content-sufficiency` and `quality-gate` once a workflow has them - must be current, or the run stops BLOCKED (`quality-floor`). `wgf <slice> --run` no longer skips a completed step whose upstream was redone: after a re-plan it ran no init..verify and asked G4 again on the old build. Tier `mvp`, a weakening configuration (`release.allow_unreviewed`, a `baseline` or custom-rubric visual QA, fewer develop checks, SDK tests off, an SDK report from a file, a custom listing reference) at the start or any later resume (`QUALITY_DOWNGRADED`), and a workflow the Factory does not ship make a run `development`: every artifact ref, the release-manifest (`evidence.quality`) and `wgf status` say so, and it is never submitted live. `--mock` and golden runs stay allowed and are reported development. A new run whose configured design author is a built-in one (the shipped `archetype`) at the release tier is refused before it starts, with the fix (an `agent` author, or tier `mvp`), and `wgf where --json` reports it (`quality.refused`), which the plugin's `/new-game` checks first. A G3 whose tech plan records a planned shortfall (WS-3) waits for a person - no auto, timeout or automation approval (gates.yaml 1.5.0 `hold_for_person_when`). Bringing an artifact forward: a 1.3.0 release-manifest stays valid; a run started before this has no snapshot and is development.

**Content sufficiency on the built game** (WS-4 of [docs/quality-gap-audit-2026-10.md](docs/quality-gap-audit-2026-10.md); workflow `new-game` 9, `content-sufficiency-report` 1.0.0, `core/reference/content-sufficiency.yaml` 1.0.0, quality-benchmark 1.4.0, play-probe schema). Every gate passed a 12-level build with one brick kind; nothing counted the build's content. The new `content-sufficiency` step (`scripts/wgf_sufficiency`, after `visual-qa`) counts every `content` and `progression` bar of the quality benchmark at the design's tier on the BUILD: the played commit's `public/content/units.json` and what the probe showed in each unit. The playability bot's new survey test (the `playability` step's `with: survey: true`) enters every unit through the probe's unit link (`?wgf-probe=1&wgf-unit=<id>`), so units past the first three are measured. Checks: units shipped and reachable, entity kinds, elements, combinations, structure kinds and near-identical units, groups that bring something new (not cosmetic), difficulty that asks for new skills, objective kinds, climax units with their own art, gated unlocks, designed play, and design-vs-build drift. Each failure is a typed finding (dimension, severity, observed vs bar, owner, route): `develop` when the build is short of a design that meets the bar, `design-gap` when the design itself is short (its design gap is repaired by the design step). While a content unit is in play, the play-probe schema now requires `entities[].kind` on every entity of a content role. The develop brief lists the `develop` findings. Bringing an artifact forward: a probe that reports content units without kinds now fails `probe.valid`; a run resumed under workflow 9 runs the new step after visual-qa.

**Feature evaluation in design** (WS-5 of [docs/quality-gap-audit-2026-10.md](docs/quality-gap-audit-2026-10.md); game-design 1.10.0, adapter binding 1.9.0). A brief feature no longer drops silently: the 2D validation brief's endless mode and the 3D marble brief's time trial were lost without a word. `core/reference/feature-catalogue.yaml` (1.0.0) lists 23 candidate features - progression, unlocks, themed worlds, star rating, rewards, daily rewards, daily challenge, streaks, leaderboard, achievements, missions, shop, skins, upgrades, difficulty modes, time trial, endless mode, statistics, profile, local and cloud save, settings, tutorial - with the phrases that name them, their relevance per genre family (expected, fits, poor), the platform capability they rest on and its fallback, and estimates of player value, build hours, monetization impact and QA cost. `features[]` gain `source`, `catalogue` and `evaluation` (decision `include`, `later` or `cut`, with a reason). The design step's new `features.*` checks (`scripts/wgf_design/features.py`) require every catalogue feature the brief or the strategy names, and every one the genre family expects, to be evaluated - not added blindly; an `include` to be built (mvp or post-mvp) and a `later` or `cut` to be optional; an included feature to run on every required platform. The built-in author evaluates them (included where its archetype builds the feature, cut where the strategy or the platforms rule it out, deferred otherwise); the agent author is handed them as `feature_candidates`. A cut feature is listed in `scope.tiers.out_of_scope` with its reason, and G3 and G4 are shown the cut and deferred features, with a warning for any the brief asked for (`wgflib.gate_evidence`). `retention.hooks` gains `daily_challenge` (F13). New playbook `core/craft/feature-evaluation.md`. Bringing an artifact forward: a 1.9.0 game-design stays valid; re-running design adds the evaluations.

**The release content is planned, built before G4 and budgeted from the plan** (WS-3 of [docs/quality-gap-audit-2026-10.md](docs/quality-gap-audit-2026-10.md); tech-plan 1.1.0, quality-benchmark 1.4.0, gates 1.4.0). The tech plan planned only `tier: mvp` content units and `new-game` never built `M2`, so a release was the MVP by construction; the 2D validation run was given a fixed 14 developer sessions and a person had to raise it to 18 mid-run. Now the run's quality tier decides what is built before G4 (`quality-benchmark.yaml` `tiers[].builds`, recorded as `dev_plan.build_scope`): at `release` every post-mvp feature and content unit is planned in M2 (CONTENT tasks batched apart from the MVP's) and carried by the developer's brief, and the develop checks fail a release build that ships only the MVP subset; `units.json` carries and is compared on each unit's `group`, `structure`, `elements` and `objective_kind`. A feature evaluated `later` or `cut` gets no task. The develop budget is derived from the same tasks (`dev_plan.develop_budget`: sessions = ceil(build hours / 8) + 6, cost = sessions x 3.5, from `quality-benchmark.yaml` `develop`, with its basis); `factory.develop.budget` only caps it lower, a cap below the need is a planned shortfall in the tech plan (a high risk, the step's message, G3's `must_show`), and exhaustion is `BLOCKED` with the tier not achieved. Bringing an artifact forward: a 1.0.0 tech-plan stays valid and is built as the MVP under the configured budget; re-running tech-plan adds both blocks.

## [2.7.0] - 2026-10-03

Research that proposes several opportunities from a coded game corpus, and designs that say
what the game is actually made of: a genre model per family, a content unit list the build is
held to, and a return route when the design did not say enough.
Record: [docs/v2.7-release.md](docs/v2.7-release.md).

**`/new-game` reaches publication and reports a run honestly** (adapter binding 1.8.0). `/web-game-factory:new-game publish <run-id>` continues a drafted release into the workflow's `publish` group (`wgf publish --run`), still answering no gate; the binding's new `continues` field names the group and `check-integrity.py` checks it. A `FAILED` or `BLOCKED` run is shown with its logs and resumed only when the user confirms; a resumed run's approvals and develop budget are reported from its own `params`, not the current config; decision lines are complete, with a note to replace; the Claude surface declares `allowed-tools` for its own engine calls (never `decide`). No artifact changes.

**Publication runs inside the Factory** ([docs/publish-module.md](docs/publish-module.md)).
The release lifecycle's tail - `release:validating`, G5, G6, `release:submitting` - is now the
`publish` group of `new-game` (workflow version 6), continued in the run that drafted the
release by `wgf publish --run <run-id>`; `wgf new-game` still ends with the draft, because G6
is irreversible and never auto-approves. `platform-validate` (`scripts/wgf_publish`) computes
the publication guards the machines name - `candidate_frozen`, `store_metadata_complete`,
`package_shaped_to_profile`, `assertions_pass`, `metadata_and_locales_present` and the quorum
guards, all UNKNOWN before - through `wgflib/publication.py`, which `wgf-state.py` now reads
too, and writes a `platform-publication` with a `readiness` (READY, BLOCKED, HUMAN_REQUIRED,
UNKNOWN; UNKNOWN is never READY). `release-review` (G5) and `publish-review` (G6:
`publish`/`reject`, a person only, pinning the release-manifest by hash) are
`human-checkpoint` steps; the release machine gains the matching `reject` edges. `submit`
refuses any manifest but the one G6 pinned, finds a draft by a deterministic idempotency key
before any upload, submits once (`retry: max_attempts 1`, never retryable), and advances the
record only from the portal's own state read back; `factory.publish.mode` is dry-run until an
installation sets live and `WGF_PUBLISH_LIVE=1`. Platform behaviour lives in adapters
(`scripts/wgf_publish/adapters/`) and in new, separately versioned publication profiles
(`core/reference/publication/<id>.yaml`, `shared/publication-profile.schema.json`): the
portal's method (api/cli/console/email/manual), console origins, the credential's variable
name, what only a person does, `automation_terms`. No shipped portal documents an upload API;
the console adapter is direct Playwright under `wgflib.procs` with fixed selectors
(`browser/console.spec.ts`), never Playwright MCP, and every shipped console flow is
unverified and off until a person records the portal's terms
(`factory.publish.platforms.<id>.terms_confirmed`). A login, CAPTCHA, second factor,
unconfirmed terms, missing session, unmapped portal state or a method only a person performs
stops the step WAITING_FOR_HUMAN (`wgf decide <run> done|abandon`). A portal session is
captured by a person (`scripts/wgf-publish.py capture`), read through a third allowlist
(`factory.publish.env_passthrough`), copied privately for one browser run and deleted;
`wgflib/redact.py` scrubs every workflow event (kernel: `events.py`) and every publish
artifact. `platform-publication` 1.1.0 (additive: readiness, guards, submission method/key/
draft id/dry run/authorized_by, outcome, human_required, verified_state, evidence,
measurement_class, workflow); `decision-record`, `scaffold-record`, `qa-report`,
`verification-report`, `release-manifest` consumers gain the publication stages;
`check-integrity.py` accepts an artifact's `updated_by` stage as a producer. The lifecycle
bridge picks a decision's edge by the record's transition (`approved` is G2's `approve` and
G6's `publish`). Tests: `test_publish_module` (RELEASE category) with a fake console and,
opt-in (`WGF_PUBLISH_BROWSER_TEST=1`), real Chromium against a fixture portal; no test
contacts a real portal. Not done: a live run against any real console, a Poki CLI adapter,
per-platform builds (one bundle still targets one portal).

**Store listing** ([docs/store-listing-module.md](docs/store-listing-module.md)). Workflow 7:
after G4 passes, the verified build's store package is captured from the running build and
validated per platform before release ships it. The `store-listing` step serves the verified
bundle locally, plays it through its play probe in the game's own Chromium on a landscape and
a portrait viewport, and writes the canonical package: screenshots of real play (play first,
title last; excluded states, unreadable and indistinct frames dropped, with retries), a
gameplay recording trimmed to play with Playwright's bundled ffmpeg (an honest frame-sequence
fallback when no recording can be made), branding composed in the browser from the game's own
palette, display face and player asset (a frame-derived fallback without a browser), store
copy grounded in the design and the game's own strings (a deterministic writer, or an agent
writer whose texts pass the same grounding check), and one rendition per targeted platform
under its profile's new `store_listing` block (`shared/platform-profile.schema.json`
`storeListing`; every shipped profile states what its sources say and leaves the rest
`null`; the eight shipped profiles are 1.1.0, since a profile's identity is its version and
its content hash and the block is content - a game pinned at 1.0.0 keeps verifying against
its vendored 1.0.0 copy). The `listing-validation` step judges it - every text and file present and within its
limits, screenshots real and distinct, the trailer within bounds, no unbacked claim
(`core/reference/store-listing.yaml` `claims`), every platform rendition - reporting a `null`
requirement as UNKNOWN, never passed; a failure the step can redo routes `listing` back to it
(bounded), one only a person can fix blocks. `release` requires the listing of the commit it
ships, validated PASS (`required_listing`, refusals `no-store-listing`,
`listing-commit-mismatch`, `listing-incomplete`, `listing-not-validated`,
`listing-not-passed`), copies the package to `release/<id>/listing/` and fills
`store_metadata` from it (release-manifest 1.3.0, `evidence.store_listing`). G6 is decided on
`release-manifest`, `store-listing` and `listing-validation-report` (gates.yaml 1.2.0).

New: `core/artifacts/store-listing.schema.json`, `listing-validation-report.schema.json`,
`core/reference/store-listing.yaml`, `core/lifecycle/stages/store-listing.md`,
`core/craft/store-listing.md`, `scripts/wgf_listing/`, `scripts/wgf-listing.py`, the
`store-listing` skill (adapter binding 1.7.0), `factory.listing` configuration. The golden
runs expect both steps and assert a complete, validated, shipped listing. Phase naming:
"campaign" stays G7's paid acquisition; this is the store listing.

**Research V2** ([docs/research-v2.md](docs/research-v2.md)). Research is game-corpus based:
listings and teardown records (`game-record`, `<corpus>/games/`) are coded on a shared,
versioned vocabulary (`core/reference/research-vocabulary.yaml`: a genre tree, market
descriptors, 41 facets from mechanics and core-loop beats to theme, fantasy, art, audience,
session, retention, monetization and production). The research step now builds per-domain
views, market cells that keep demand, supply, saturation, competition and trend apart,
cross-game patterns and benchmarks that state their numerator and denominator, and an
opportunity space from five generators (proven core with one axis changed, supply gap,
pattern transfer, portal difference, capability screen). A corpus-generated opportunity must
rest on an observation; low supply without demand is `insufficient-demand-evidence`; an
opportunity the Factory cannot build is kept as a capability gap. The archetype catalog is
now a build-capability catalog. Strategy and design carry the research (`research` blocks
with `applied`): the observed control scheme, measured session length and audience type in
strategy; the archetype, fantasy, theme and the visual identity kit - by the art research
supports, no longer by the title id's digest - in design. `select` pins another opportunity
from a scan; `persist_backlog` writes them all to the backlog. `scripts/wgf-corpus.py`
validates and starts teardown records.

The worked example's invalid evidence is superseded, not edited: `claim-0a05`/`claim-0a06`
supersede `claim-0a01`/`claim-0a03`, `eval-0b02` supersedes `eval-0b01` (coverage 0.246).

Schema changes are additive: `research-report` 1.2.0 (V2 sections required when
`research_version: 2`), `opportunity` 1.2.0, `title-strategy` 1.3.0, `game-design` 1.8.0;
claims gain facet subjects, capture evidence and a `support` block a pattern must carry.
Every earlier artifact remains valid. Adapter binding 1.6.0 (must-read lists only). No gate,
workflow, lifecycle or template-pin change in this part. Not done: production-cost calibration,
a scoring model v2, and the P2 capabilities `docs/research-v2.md` lists.

**Genre depth** ([docs/production-architecture.md](docs/production-architecture.md),
`core/craft/content-and-level-design.md`). A 2.6.0 design could pass every check and still
describe one level and a ramp: nothing said what a game of its genre is made of, so the design
stated a loop and the developer invented the content, difficulty and win condition around it —
and then reported the result as a prototype of the design. Three root causes, each fixed where
it was: no genre knowledge in `core/` (the design had no shape to be held to), no content in
the design artifact (the only list of what the player meets was the difficulty curve), and no
way for a developer to say "the design does not decide this" (so it decided, silently).

`core/reference/genre-models.yaml` (new, 1.0.0) is the genre knowledge as data: eight families
— puzzle, platformer, arcade, shooter, racing, strategy, survival, simulation — each with the
research-vocabulary genre nodes it covers, the unit kinds, progression and difficulty models and
endings that fit it, the difficulty axes (which escalate, which the build must probe), the
shape of win and loss, how many units an MVP and a release carry, the variety dimensions, how
mastery shows, the QA parameters the playability checks read, and a `seed` block the offline
genre seed author designs a whole game from. `casual` and `standard` are session profiles, not
families. No consumer branches on a family id: a new family is a new entry, never a new code
path. `core/craft/content-and-level-design.md` (new) is the craft behind the bars, and
`level-design` is a new skill on both adapters (adapter binding 1.7.0).

The design now states its content. **`game-design` 1.9.0** adds `genre` (the family, its node,
the session profile, `finite` or `endless`), `build_spec.content` (the unit kind, whether units
are `authored`, `parametric` or `procedural`, and every unit with its purpose, objective,
mechanics, per-axis difficulty, duration, success, failure, acceptance and what it varies from
the unit before), `build_spec.difficulty.axes` (the axes, declared once; the numbers live only
on the units), `build_spec.mastery`, `mechanics[].progression_role` / `interactions`,
`progression.unit_sequence` and `consistency.content_model`; a `finite` ending now requires
`build_spec.experience.win`. The design step checks it against the family's entry
(`scripts/wgf_design/content.py`, 22 `content.*` rules, after the depth check) and records the
model it checked against. **`title-strategy` 1.4.0** adds `concept.content_model`, resolved at
strategy from research or the family's default. **`opportunity` 1.3.0** carries
`capability.genre_model` and `research.design_constraints` (the content shape research coded
for the cell, with the genre conventions it counted). **`prototype-report` 1.1.0** adds
`content_coverage` (designed units against built ones) and `design_gaps`.

**`playability-report` 1.2.0** adds the status `SKIPPED` and `skipped_checks`. **`qa-report`
1.2.0** adds the suite `gameplay-quality`. **`review-report` 1.1.0** is a version bump for the
reviewer's new `## Design fidelity` brief section. `play-probe` gains `content`,
`entities[].kind` and `metrics.difficulty.<axis>`; `design-consistency-rules.yaml` 1.3.0
(`scope_fits_session_count` applies only to a design with no family, which the content model
bounds instead); `design-depth.yaml` 1.1.0 (the playability bars). Every change is additive and
**every earlier artifact remains valid**.

**Workflow 8** adds one route and one input set. `design-gap`, from `greybox` and `develop` back
to `design`, is taken when a developer reports a blocking design gap — the design does not say
enough to build what was asked — and is bounded on design, one pass from each source
(`greybox.design-gap: 1`, `develop.design-gap: 1`); the build commit and its report are kept,
and tech-plan and G3 run again on the repaired design. `design` therefore also takes the
`prototype-report`, `verify` and G4 take the `playability-report`, and G4 takes the
`review-report` as well (`gates.yaml` 1.2.0 lists both among G4's required artifacts, so the
decision record pins them). Visit budgets move with it: develop 21 (1 + 2 × 7 + 4 + 2),
greybox 5.

What the first live run of this found, and what it changed, before any gate was relaxed. A
sliding-ice puzzle idea reached the design step as the catalog's own colour-grid concept: on
a catalog entry that names only a genre model, the entry is a capability and **the idea is the
concept** (`concept.core_mechanic` is the brief, `core_loop` is the family's `loop`,
`research.applied` source `brief`); an entry that names a design archetype keeps the catalog
concept, as before. The design step met the experience problems in round one, the
presentation problems in round two and never reached the content check: every check now runs
on every draft and **one repair request carries every problem**, and a blocking consistency
breach is put to a repairing author by rule name before it descopes. The agent's penguin
design named a wall and a locked door and was descoped as a foreign mechanic:
`design-consistency-rules.yaml` 1.4.0 lists `wall`, `crash` and `lock` as `detail_terms`,
counted when the concept names them and the design drops them, never as a different game.

The build is now held to the content it claims. The developer brief carries the genre, the
content table, the difficulty axes, mastery and depth, and an authored design owes
`public/content/units.json` plus `tests/unit/content.spec.ts`, compared with the design by
`conformance` (`content.*` findings); the tech plan makes one `CONTENT-nnn` task per batch of
three MVP units; the playability bot plays them (`content.units_reachable`,
`content.objective_shown`, `content.win_lose_per_unit`, `content.variety`,
`difficulty.axes_progress`, `progression.persists`, `depth.session_length`, `depth.ramp`, with
three new bot tests — traverse, persist, session — and every bar in
`design-depth.yaml playability:` merged with the family's `qa:`); verify carries that evidence
into `quality.*` checks and the `gameplay-quality` suite instead of re-measuring it, and
`gameplay.progression` no longer passes on a test whose title merely says "score" or "level";
review reads a `## Design fidelity` section; and G3 and G4 are shown the content rules, the
coverage, the gaps and the played checks. **A `SKIPPED` check is never a pass** — it is listed
with its reason and subtracted by anything counting passes.

Research and strategy feed it: the capability catalog (1.3.0) makes an entry buildable through a
`design_archetype` **or** a `genre_model`, which makes eight more shapes buildable (three
existing entries plus `logic-puzzle-levels`, `precision-platformer`, `flip-arcade`,
`wave-shooter`, `lap-racer`, `tower-defense`, `arena-survivor`, `stand-tycoon`) with no rule
relaxed; an idea is matched against a family's label and nodes as well as the entry's own words;
and strategy replaces "one data-driven ramp, not hand-built levels" with
`concept.content_model`.

Also found: the template's "Windows unit test failures" were never Windows. They were CRLF
checkouts (`git config core.autocrlf true`); with `core.autocrlf input` the pinned template
passes 656/656 on Windows. The golden runs still need Linux CI for `pnpm`.

To bring an artifact forward: re-run the design step. A 1.8.0 design with no `genre` is
validated as legacy — one warning, no bar applied, and no content check in the build — so
nothing already produced fails; it simply gets none of this.

**A command developer never runs without a budget** (F26). A run started under the shipped,
supervised config has no `develop_budget`; when its project then switched to a paid
`command` developer (the autonomous profile copied in mid-run), the developer ran unbounded -
a validation run spent 14 sessions against a documented cap of 12. Now develop and the
greybox return BLOCKED, no agent spawned, for a command developer in a run with no budget,
naming `factory.develop.budget`; and the first `wgf resume` by a person that finds one
configured records it for the run as a `BUDGET_ADOPTED` operator event (corroborated like
`BUDGET_RAISED`, counted once; params are not edited). Handoff developers are unaffected.

**Upgrading:** an installation that runs a command developer without `factory.develop.budget`
must set one; a run already in progress adopts it at its next resume.

**Windows: process liveness without signals** (F12). `procs.pid_alive` and the run lock's
check used `os.kill(pid, 0)`, which on Windows is `GenerateConsoleCtrlEvent(CTRL_C_EVENT)`:
a live driver started from another terminal read as dead (`wgf status` said `stale`, and a
second driver could take its lock), and a process group on the same console could be sent
Ctrl+C. Windows now asks the process itself (`OpenProcess` + wait/exit code, through
`ctypes`) and records its creation time in the lock, so a recycled pid is told apart as on
Linux. POSIX is unchanged.

## [2.6.0] - 2026-10-02

Production-quality games, proven from the running build: workflow 5, real 2D/3D assets and
audio, the production-quality and visual-QA gates, design depth, plugin skills distilled from
two reference games, and an autonomous profile that configures every agent workflow 5 needs.
Record: [docs/v2.6-release.md](docs/v2.6-release.md).

What a real `/web-game-factory:new-game "<idea>"` dogfood run of 2.5.0 found, with the idea "I
want to make a 3D battle royal game but it's human versus computer, with the goal being the
goalkeeper": every defect below stopped it or lost the idea. No gate, rule or evidence
requirement was relaxed.

### Fixed

- **The playability bot measured screens mid-entrance.** A pause card fading in was measured
  at three quarters of its opacity, and its button text failed a 4.5:1 contrast it meets a
  moment later. `Watch.screen` now lets finite CSS animations and transitions finish (at
  most 1.5 s) before it measures and captures a screen.
- **The bot's per-screen frames had no rubric state.** `state-title`, `state-playing`,
  `state-paused`, `state-won`, `state-lost` and `state-retry` were `unknown` to visual QA's
  brief; they now map to initial, gameplay, interaction, win, loss and retry.
- **Defects the lead caught only by eye now fail a check** (quality monitor, 2026-10-01).
  `font.coverage` (assets): a delivered font's cmap must map every character of each locale in
  `scope.locales` - TTF/OTF/WOFF read with the standard library, WOFF2 through the system
  Brotli decoder via `ctypes`, else `skipped` "coverage unchecked"; the 2D reference library's
  Latin-only WOFF2 fonts fail with `ru`. The design step refuses a typography whose face cannot
  set a locale in scope (`asset-quality.yaml` `fonts.families`, read from the Google Fonts
  catalogue), and the archetype author swaps such a face for its kit's covering alternate.
  `variants.distinct` (assets): a counted requirement's drawings must differ by silhouette,
  not colour or numeral; an author is sent back while it draws. `variants.count`: a library
  short of the count fails the set and `variants-short` is an error for mvp items.
  `scene.contrast` (production gate): each readable role's best box must reach 3:1 against a
  ring around it; the dark first 3D build's barriers fail at 2.5:1. The drop-merge archetype
  counts its `pieces` from the rules: an exhaustive search of its tracks reaches level 10,
  not a fixed 6. asset-quality.yaml 1.1.0, production-quality.yaml 1.1.0 (additive). To bring
  an artifact forward: re-run the design step for a title whose typography cannot set its
  locales, and the assets step for fonts and counted drawings.
- **Both golden runs failed those checks on their own art** (`assets.present: quality not
  pass` - 2D `fonts, pieces`, 3D `fonts`; the 3D design has no `pieces`, its report named only
  `fonts`). The lock's `golden_ports` moves to template `wgf-golden-content` (`db7b140`): the
  2D library draws towers 9 and 10 (the rules reach 10; `variants.distinct` passes on all
  ten) and bundles Rubik Mono One and Manrope, the 3D library Commissioner 500 for Instrument
  Sans - every face Latin + Cyrillic, the kit's covering alternates the design step names for
  `ru` - and both ports' baselines are re-captured. No check was changed.
- **An idea no catalog concept carries was silently replaced.** Research carried the nearest
  buildable shape forward (an endless runner for the goalkeeper idea), so strategy and design
  were held to a different game. Research now waits for input instead
  (`discovery.idea_fallback: wait`, default; `nearest` keeps the old behaviour on purpose),
  and reads a project `workspace/research/concepts.yaml`: concepts authored for the run's
  exact brief, in the catalog's shape, with `design_archetype` (`agent` when only an agent
  design author can design it); their figures are hypothesis claims, plus one claim saying
  the concept was authored for the brief. `core/lifecycle/stages/market-scan.md`.
- **Nothing in a `/new-game` run supplied research's input.** A fresh project waited at research
  with no evidence, and core never specified the snapshot format. `core/craft/research-evidence.md`
  specifies it (the fields the discovery step enforces; evidence is fetched, never written)
  and the concept file; both `new-game` surfaces hand a research input wait to the research
  role, then resume. Read by the research agent and the market-intelligence skill.
- **Research accepted `priors` it could not read** - a note where the six prior dimensions go -
  scoring them as nothing and turning the note into claim text. Malformed priors are now
  refused, for the catalog and project concepts alike.
- **The design agent was never shown the schema its draft must satisfy, nor its errors.** Its
  draft used enum values the game-design schema does not allow; the engine's contract check
  caught it after the step and the retry repeated the mistakes. The design step now
  validates the composed artifact against its contract itself, and shows an agent author the
  exact problems and its previous draft for up to two repair rounds; every round is judged
  like the first. The request names the schema.
- **The shipped `factory.yaml` named the model author's repair key `repair_rounds`**; the
  module reads `max_repair_rounds` (docs/assets-module.md said the same), so the documented
  key did nothing. Both now say `max_repair_rounds`. And the 2D author's prompt named a
  relative request path when `wgf-assets.py build --work-dir` was relative, while the host
  runs inside that directory: the paths are absolute now.

### Added

- **The autonomous profile configures workflow 5's three agents.** An unattended `/new-game`
  got placeholder art (no 2D author, no 3D model author), which `production-quality`
  refuses and routes back to `assets` until the loop limit blocks the run, and `visual-qa`
  blocked with no judge. `workspace/config/profiles/autonomous.yaml` now sets
  `assets.author`, `assets.model_author` and `visualqa.judge` - each the read-only headless
  Claude Code example commented in the shipped `factory.yaml`, verbatim (only `Read`,
  `--safe-mode`, `--permission-mode dontAsk`, text output; at most US$1 a drawing, US$2 a
  model spec or a judgement), held there by `test_autonomous_profile.TheWorkflow5Agents`.
  The 2D author gains `svg_from: stdout` (`scripts/wgf_assets/author.py`; `wgf-assets.py
  build --author-svg-from`): the host prints the SVG and the Factory writes it, so the
  author needs no write tool - as the design and model authors already take stdout.
  `wgf where` reports `asset_author`, `model_author` and `visualqa_judge` under `autonomy`.
  Verified live on 2026-10-02 (docs/claude-capabilities.md, "The asset authors and the
  visual-QA judge"). The shipped default is unchanged: no author, no judge. Nothing to bring
  forward.
- **Every design states why a player comes back** (game-design 1.7.0 `build_spec.depth`).
  Both reference games were single-loop arcade prototypes with nothing persisted but a best
  score. A design now states a meta loop that persists more than a score, a goal ladder
  (short, mid, long), content-variety items introduced on a schedule, a first session of
  120-900 s equal to `session.first_session_seconds`, and return hooks - each tiered, an MVP
  entry resting only on what the MVP builds (`delivered_by`). The design step checks it
  after the consistency rules (`scripts/wgf_design/depth.py`, bars in
  `core/reference/design-depth.yaml`); an agent author is shown the problems to repair.
  Every archetype states real depth: stages, special pieces, power-ups, coins and
  achievements for `drop-merge`; zones, pickups, a near-miss combo, a ship garage and
  missions for `arena-dodge` - post-mvp, so the golden ports (which build the MVP) are not
  claimed to have them. Depth resting on a feature the strategy excludes is tiered optional
  with the exclusion named, and listed in `open_questions`. New playbook
  `core/craft/retention-and-progression.md`, read by the game-designer, gameplay and liveops
  agents and the game-design and core-loop skills. Feature specs for the two reference games:
  `docs/reference-games/`. Bringing a 1.6.0 design forward: add `build_spec.depth`.
- **Workflow 5: the production build is judged before review.** `new-game` runs
  `production-quality` and `visual-qa` after `playability`; each routes `assets` (an asset
  must be made again) to `assets` - which reads the failing report, rebuilds only what it
  names and continues to `develop` - and `develop` to `develop`, whose brief leads with the
  failures ("Fix first: what the production gate measured" / "what visual QA saw") when they
  judged the commit it starts from. Budgets: `production-quality.assets`, `visual-qa.assets`
  (assets `max_visits` 5), `production-quality.develop`, `visual-qa.develop` (develop
  `max_visits` 19 = the first visit + its seven route budgets + assets' four passes; every
  later step 19). `--mock` runs every new step; mock CLI tests drive both loops each way and
  the route limit.
- **Release refuses a build the production gates did not pass.** `wgf_release` requires the
  newest `production-quality-report` and `visual-qa-report` to be PASS for the development
  commit the shipped sdk commit sits on (`no-<report>`, `<gate>-not-passed`,
  `<gate>-commit-mismatch`); a workflow without the gates says so with
  `with: required_reports: []`.
- **Visual QA's `baseline` judge**: no agent - each runtime frame against the approved frame of
  its state by palette, detail and layout (`scripts/wgf_visualqa/baseline.py`, bar 0.70,
  calibrated on both golden ports: with placeholder art 0.37-0.52 (2D), without art
  0.45-0.69 (2D) and 0.53-0.78 (3D, failing 22 of 26 frames), finished 0.76-0.99 and
  0.81-0.99). Unmatched
  states are reported as minor findings.
- **The goldens exercise production for real.** The golden ports pin (template branch
  `wgf-golden-production`) carries both reference ports' production art: the harness imports
  each port's `library/` through `factory.assets.libraries`, configures visual QA's baseline
  judge on its `baseline/`, and the run passes only when production-quality and visual-qa
  both PASS (summary `production`); `library/` and `baseline/` never land in the game. The
  drop-merge archetype's `pieces` count is 8 (the library's eight drawings). `run.py
  --no-library` is the calibration run that must fail (it does, at develop: the port's own
  art guard refuses placeholder art). Both goldens pass end to end with
  production-quality 16/16 and visual-qa PASS on 26 frames. The template branch also holds
  the fixes the real runs found in the ports: the 2D greybox ground was a wash (mean
  luminance 227), the 2D asset loader sat in `src/assets/` (verify's asset root), and the 3D
  port refused to boot without its manifest, so the greybox phase could not run.
- **Production craft distilled from the reference ports** (adapter binding 1.6.0). Five
  provider-neutral playbooks carry what made the 2D and 3D reference games pass the
  production gate, with their numbers and the files and frames each came from:
  `core/craft/production-art-2d.md` (style kit, a silhouette per variant, layered SVG,
  backgrounds, VFX, anchors, `library.json`), `production-art-3d.md` (part decomposition,
  taper/bevel/mirror, materials and emissive, light rig, fog and sky, portrait camera),
  `game-ui-kit.md` (fonts as assets and locale glyphs, contrast and target floors, buttons,
  HUD, screens, portrait), `juice.md` (acknowledgement within 100 ms, drop, merge, combo,
  shake, near-miss, crash, opening grace) and `production-wiring.md` (`assets.json` by id and
  role, the probe's `asset`/`render`/`assets_loaded`, the art regression guard, self-checking
  with frames). One new skill per playbook in both adapters; the playbooks are in the
  `must_read` of the game-designer, gameplay, ui and asset agents, the reads of eight existing
  skills, and the `new-game` surface's "production bar". The develop brief names the engine's
  playbooks by path and recommends the new skills; the 2D and 3D author requests carry theirs
  as `craft`. Nothing to bring forward: no schema, gate or artifact changed.

- **Every design states its production art and UI** (game-design 1.6.0). Each built-in
  archetype gives every asset a `role`, `dimension` and `readability` line (player, threats,
  targets, environment/background, UI kit, icons, fonts as bundled OFL files), and every
  identity kit a `visual_identity.ui` (font sizes, 48 px targets, button fill/text tokens at
  4.5:1, radius, surface). `scripts/wgf_design/presentation.py` holds every design to it in
  the design step's repair loop (bars in `core/reference/experience-rules.yaml` 1.1.0
  `production_art` and `ui`); the Goalkeeper Royale fixture fails it with named problems.
  The production develop brief adds *Production art and UI* (asset per role, probe `asset`/
  `render`/`assets_loaded`, no primitives unless `primitive_style`, the UI spec and font
  loading); the greybox brief says to report `render: "primitive"`. New craft playbook
  `core/craft/production-art-and-ui.md`, read by the game-designer, gameplay, ui and asset
  agents and the game-design, art-direction and onboarding-ux skills.

- **The player-experience contract** (`game-design` 1.5.0, additive): `build_spec.experience`
  states what a first-time player must be able to tell, and how fast - the objective and the
  screen that shows it, how play is lost (and won), how every MVP action is acknowledged, what
  the first session teaches and its grace before failure, and the first-30-seconds budget -
  and `hud[].metric` names what each HUD element shows. The design step requires it of every
  design it produces and holds it, by reference and number, to the new
  `core/reference/experience-rules.yaml` (first frame <= 2 s, playable <= 10 s, first success
  <= 30 s, retry <= 3 s, acknowledgement <= 100 ms, grace >= 10 s) and to the rest of the
  build_spec (`scripts/wgf_design/experience.py`): every metric the objective, win, lose and
  actions rely on is on the HUD; every action is acknowledged and taught; the budget matches
  the session and failure numbers; a key the design names is bound; an onboarding that shows
  the answer cannot stand beside a strategy that must prove understanding without
  instruction. An agent author is shown the problems to repair; the built-in archetypes state
  a contract that holds, and the play screen now carries the objective, since a first session
  starts there. The developer brief carries the contract first. Found by playtesting a real
  run's game, which lost by itself 2.8 s after play began and never stated its goal;
  `test_design_experience` holds the checks against that run's design.

- **The play probe** (`core/artifacts/shared/play-probe.schema.json`): what a built game reports
  about itself so it can be played and judged from outside - `window.__wgf__.play.snapshot()`
  returns the session state, the experience contract's metrics, the entities on screen with
  their drawn bounds, the inputs available now, and, only with `wgf-probe=1` in the URL, the
  input that succeeds now. Read-only. A new required system in the developer brief, which
  embeds the schema verbatim and says how the build is judged.

- **The playability step** (`new-game` workflow 3; `scripts/wgf_playability/`,
  [docs/playability-module.md](docs/playability-module.md)): between develop and review, a bot
  clones develop's commit, builds it and plays it from outside through the play probe with
  real pointer, touch and key input, on a desktop and a mobile viewport. It holds what it sees
  to the experience contract and to the new `core/reference/visual-quality.yaml`:
  - the objective is on screen;
  - there is no loss with no input inside the grace;
  - every action visibly changes the frame;
  - good play wins (or raises the objective) and bad play loses;
  - the retry works;
  - what must be seen is drawn large enough;
  - a projectile is seen in flight;
  - frames are lit.

  The new `playability-report` artifact records every check, measurement and frame. A failure
  routes back to develop, whose brief leads with what the bot saw and the frames that show it
  (budget `playability.fail: 2`). The real run's game fails 11 checks across both viewports;
  both golden ports pass every check. Automation evidence (`measurement_class:
  automation-bot`), never a first-time-player measure.
- `play-probe`: an optional `hold_ms` on an input, for a control that acts while held.
- The golden ports (template `golden_ports` 1c5afcb) implement the play probe and show their
  objective. Neon Drift Arena's gains an opening grace: walls pass through the craft until
  the player first steers.

- **The greybox phase** (`new-game` workflow 4): right after init, develop builds the whole MVP
  loop with primitives in the design's palette (`greybox`, `with: {phase: greybox}`: no
  asset manifest, the probe, objective, onboarding, HUD and acknowledgements), and
  `greybox-playability` plays it from outside. Only a loop that plays and reads goes on to
  `assets`; one that does not is rebuilt with what the bot saw (budget
  `greybox-playability.fail: 2`). develop's production phase names the greybox that passed
  and must keep it passing. The real run's game had its assets made before anyone could see
  that its loop was unreadable.
  The greybox's developer sessions count toward the run's `factory.develop.budget`, and
  each develop step keeps its own transcripts (`<run>/<step>/<visit>-<attempt>.log`: a
  greybox and a develop visit 1 no longer share `develop/1-1.log`).

- **The production contracts** ([docs/production-architecture.md](docs/production-architecture.md)):
  what a finished game is held to, and by which artifact. `game-design` 1.6.0 (additive):
  `build_spec.assets[].role|dimension|readability`, `visual_identity.primitive_style` (the
  one explicit permission to draw characters as primitives) and `visual_identity.ui`.
  `asset-manifest` 1.4.0 (additive): `role`, `quality` (verdict, checks, primitive_only,
  parts, triangles, colors, author). `play-probe`: `entities[].asset|render`,
  `assets_loaded`. New artifacts `production-quality-report` and `visual-qa-report`.

### Changed

- develop's verify loop budget is keyed `verify.fail` (was `fail`), since `playability`'s
  `fail` now enters develop too; each route keeps its own two passes. develop's `max_visits`
  is 11.

### Fixed

- **sdk refused seam files it had nothing to erase in.** GitHub generated the dogfood run's
  repository from the template's newer default branch; init's pin commit deleted the seam
  files that branch had, to hold the pinned tree, and the sdk step then blocked because the
  last change to its files was not its own - though a file absent at HEAD holds no work.
  Absent files are no longer counted (`wgf_sdk/commit.py` `owned_edits`).
- The archetype states named "Esc" for pause even when keyboard bindings were out of scope.

### Changed

- The autonomous profile configures the agent design author (`design.author: agent`, the
  shipped commented argv verbatim), needed for an idea no design archetype carries.

## [2.5.0] - 2026-09-30

Two changes to `/web-game-factory:new-game` (`docs/v2.5-release.md`).

**A game idea** (#16): `/web-game-factory:new-game "3D goalkeeper game where the player blocks
penalty shots"` - and `bin/wgf new-game [--project ID] "IDEA"` - starts a run anchored to that
idea. Research ranks candidates by how well they match it and reports when nothing buildable
does (`idea-unmatched`); strategy and design carry it as the run's `brief`. Without an idea a
run is the blank market scan it always was.

**An opt-in autonomous profile**, and the two defects an audit of an unattended run found:
a project's `factory.yaml` replaced the shipped one instead of layering over it, and research
could select a concept the design step cannot build. The shipped configuration stays
supervised; G4, G6 and G7 stay human. See [docs/autonomous-runs.md](docs/autonomous-runs.md).

No gate, workflow, lifecycle or template-pin change (still `v1.2.0`); adapter binding 1.5.0
(no surface added or removed). Schema changes are all additive: `research-report` 1.1.0,
`opportunity` 1.1.0, `title-strategy` 1.2.0, `game-design` 1.4.0 - every earlier artifact
remains valid.

**Upgrading:** nothing to configure. Update the plugin (`claude plugin marketplace update
cuvara`, then `claude plugin update web-game-factory@cuvara`) and restart Claude Code. To run
unattended, copy the autonomous profile into the project (docs/autonomous-runs.md).

### Added

- **A game idea for `new-game`** (#16). One optional positional `IDEA` on every run command;
  refused (exit 2) when empty, over 500 characters, with control characters, with
  `--resume`/`--run`, or on a slice that runs no research step. `--project` is unchanged and
  independent. The idea is recorded canonically in the run's params and in
  `WORKFLOW_STARTED` as a guarded param: a resume keeps it and an edit of it is refused;
  `wgf status` shows `Idea:`. Research sets `scope.brief` and a question naming it, ranks
  candidates by `idea_match` before the screen, and records an `idea-unmatched` gap when the
  selection holds none of its words or is of another dimension; `opportunity.brief`,
  `title-strategy.brief` (with an assumption naming it) and `game-design.brief` carry it.
  The `agent` design author is told to design the game it describes; the built-in author
  designs the buildable concept research selected and records a dimension mismatch with the
  brief in `open_questions`. Both `new-game` surfaces take the idea as one verbatim argument.
  An idea the catalog has no concept for is not invented: the nearest buildable concept is
  selected and the report says so.
- **`workspace/config/profiles/autonomous.yaml`**, shipped in the plugin runtime: the verified
  headless Claude Code developer and read-only reviewer (the shipped commented argvs,
  verbatim, held equal by a test), `checkpoints.auto_approve: [G2, G3]`, `init.source: local`
  (no GitHub repository) and a `develop.budget` of 12 sessions / US$60. A project enables it
  by copying it to its own `workspace/config/factory.yaml`; G4, G6 and G7 stay human.
- `wgf where` reports `config_layers`, the effective `autonomy` a run would have, and the
  shipped `profiles`; `/web-game-factory:new-game` reports autonomy from it and, with a
  `command` developer or reviewer, says agent sessions will run unattended and cost money
  before it starts.

### Fixed

- **A project's `workspace/config/factory.yaml` replaced the shipped one instead of layering
  over it** (2.4.1). A project that set only `checkpoints.auto_approve` silently lost
  `steps.modules` and every other shipped setting. `load_config()` now reads the shipped file
  and layers the project's over it key by key (a mapping merges; a list or a value
  replaces); `--config` is still that file alone, and a development checkout still reads one
  file. Regressions in `test_autonomous_profile.Layering`.
- **Research could select a concept the Factory cannot design.** 9 of the 11 catalog concepts
  (block-puzzle among them - what the current evidence favours) reached `design` and failed
  its consistency rules, supervised or not, so a real run from research ended at design.
  Each discovery catalog entry now declares its `design_archetype` (catalog 1.1.0), and
  research excludes a `null` one before selection - kept in the report, "not buildable".
  Buildable today: `endless-runner` (`lane-runner`) and `match-3` (`merge-puzzle`).
  `test_research_to_design` runs the real research, strategy and design steps on every
  concept and fails when a declaration and the design step disagree.

## [2.4.1] - 2026-09-30

Three changes (`docs/v2.4-release.md`, *2.4.1*).

**The installed Claude plugin is the Factory runtime, and the working directory is the target
project.** Factory runtime resources - `core/`, the `wgf` engine, its step modules and the
shipped configuration - are now bundled into the Claude plugin, and every Factory command
reads them from the installed runtime, `${CLAUDE_PLUGIN_ROOT}/runtime`. Factory commands no
longer require Claude Code to run from the `web-game-factory` repository root: start it in the
project you want the Factory to work in. `WGF_PROJECT_DIR` names another target project
explicitly. `--mock`, `--hold-gates`, `--project`, `--from` and `--store` mean what they meant.

**The 2D asset pipeline** (#14): atlas packing, a runtime asset manifest game code loads
through, and validation of both. **The 3D asset pipeline** (#15), on top of it: models
described as data, built headless by a pinned Blender, every GLB validated without Blender,
and each GLB's lookups in `assets.json` for the game's three.js loader. Both are changes to the
`assets` module (`scripts/wgf_assets/`, with one consumer line each in `develop` and `verify`),
and every schema change is additive: `game-design` and `asset-manifest` move to 1.3.0 (1.2.0
with #14, 1.3.0 with #15), `asset-policy` to 1.2.0, with new shared `runtime-assets` and
`model-spec` schemas - every 1.1.0 and 1.2.0 design and manifest remains valid. Details:
[docs/assets-module.md](docs/assets-module.md), [docs/blender-pipeline.md](docs/blender-pipeline.md).

None of them changes the engine's workflow, lifecycle, gates or the template pin.

**Upgrading:** update the plugin (`claude plugin marketplace update cuvara`, then `claude
plugin update web-game-factory@cuvara`). A development checkout needs nothing: run from it,
the engine keeps using the repository as both Factory and project. Run from the installed
plugin, runs and instance data now live in the project - `<project>/.factory/` and
`<project>/workspace/` - and a project may add its own `workspace/config/factory.yaml`, which
overrides the one the plugin ships. Runs a previous plugin started from the factory repository
stay in that repository's `.factory/`; resume them from there (or with `--store`).

### Changed

- **Factory runtime resources are bundled into the Claude plugin.** `claude-web-game-plugin/runtime/`
  carries the runtime closure - `core/`, `scripts/wgf.py` and `bin/wgf`, `scripts/wgflib/`
  (with the mock fixtures), every `scripts/wgf_*` step module, the `wgf-state`/`guard`/`hash`/
  `template`/`assets`/`model` tools, the shipped `workspace/config` defaults and template pin,
  `docs/workflow-engine.md` and `VERSION` - with `runtime-manifest.json` listing each file's
  sha256. It is generated by `scripts/build-plugin-runtime.py` (run by `gen-adapters.sh`),
  committed because the marketplace installs straight from the repository, and byte-checked
  against the source by `check-integrity.py`. Tests, golden runs, the MV-4 harness, the
  integrity/generator scripts, evidence and instance data are not bundled.
- **The working directory is the target project.** `wgflib/paths.py` keeps two roots: the
  Factory (`ROOT`, always beside `wgflib/`, never the working directory) and the project
  (`PROJECT`: `workspace/`, the run store, the checkouts base, `.factory/assets`). In a
  development checkout both are the repository; from the installed runtime (marked by
  `runtime-manifest.json`) the project is the working directory, or `WGF_PROJECT_DIR` when set,
  and the runtime exports it to every process it starts. `factory.yaml` and `portfolio.yaml`
  are the project's own when it has them, else the plugin's; relative guarded paths are guarded
  under both roots, and a game checkout may be neither root nor hold one.
- **The Claude surfaces use the installed runtime.** Every Factory path a command, agent or skill
  names is `${CLAUDE_PLUGIN_ROOT}/runtime/...`, and the engine is `python3
  "${CLAUDE_PLUGIN_ROOT}/runtime/scripts/wgf.py"`. `/web-game-factory:new-game`'s preflight is
  now `wgf where --json` (installed runtime, workflow present, project and store reported)
  instead of requiring the workflow file in the working directory.

### Added

- **Atlas groups.** A sprite, UI, icon or VFX requirement may name an `atlas`; each group is
  packed deterministically (stdlib PNG codec, shelf packing, extrusion, padding, power-of-two)
  into `public/assets/atlases/<group>.png` + `.json` (TexturePacker JSON Hash, read unchanged
  by PixiJS and Phaser). Members' own images go to `src/assets/`, so each pixel ships once;
  `texture-atlas` moves from `deferred` to `applied`.
- **The runtime asset manifest** `public/assets/assets.json`
  (`core/artifacts/shared/runtime-assets.schema.json`): every loadable asset by id, URLs
  relative to the manifest, atlas frames, sizes, `scale`, spritesheet frames and animations
  (fps, loop), tileset grids, file hashes. No timestamps or absolute paths; byte-identical for
  identical assets. The asset manifest records its path and hash.
- **Requirement fields** (`game-design` 1.2.0): `atlas`, `scale` (1-4), `animations`,
  `tile_width`/`tile_height` and the new `tileset` kind, `existing.atlas`.
- **Validation**: SVG safety, texture-edge limits, transparency expectations per kind,
  dimension and tileset checks, atlas descriptors against their images (frames in bounds,
  animations naming real frames, `meta.image`), duplicate paths; ten new issue codes. AVIF is
  recognised (it was sniffed as M4A).
- **`scripts/wgf-assets.py`**: `build`, `validate`, `pack`, `inspect`; JSON output and exit
  codes 0/1/2.
- **`assets.runtime-manifest`**, a verify check that validates the repository against its
  runtime manifest; the develop brief's `runtime_assets` and its loading rule.
- **`core/craft/2d-assets.md`**: how to ask for 2D assets and load them in PixiJS and Phaser;
  read by the asset agent and the `assets`, `pixijs` and `phaser` skills.
- **Pruning**: placeholders and pipeline-made atlases nothing references any more are removed
  (`prune: false` to keep them); nothing else is ever deleted.
- `wgf where [--json]`: the Factory root, whether it is an installed runtime, the version, the
  project root, and the config, store and workflow a command resolves.
- `WGF_PROJECT_DIR` ([docs/env-vars.md](docs/env-vars.md)), and
  [docs/plugin-runtime.md](docs/plugin-runtime.md).

### Fixed

- **The installed Claude plugin only worked from the factory repository.** Claude Code installs
  a plugin as a copy of its own directory, which held surfaces and nothing else: every command,
  agent and skill read `core/` relative to the working directory, and `/web-game-factory:new-game`
  stopped unless `core/workflows/new-game.workflow.yaml` was there. Run from a game project it
  could not find the Factory. The plugin now ships the runtime closure in
  `claude-web-game-plugin/runtime/` (`scripts/build-plugin-runtime.py`, run by
  `gen-adapters.sh`, drift-checked by `check-integrity.py`), and every Claude surface names
  Factory paths as `${CLAUDE_PLUGIN_ROOT}/runtime/...`. The engine now keeps two roots
  (`wgflib/paths.py`): the Factory (`ROOT`, beside `wgflib/`) and the project (`PROJECT`:
  instance data, run store, checkouts base). In a development checkout both are the
  repository, so nothing there changes; from an installed runtime the project is the working
  directory, or `WGF_PROJECT_DIR`. New: `wgf where [--json]`. `wgf test-core` refuses to run
  from an installed runtime. See `docs/plugin-runtime.md`. Regressions in
  `test_plugin_runtime` and `test_adapter_binding.ClaudeSurfacesReadThePluginRuntime`.
- A library spritesheet renamed to its asset id kept the library's `meta.image`, so a loader
  following the descriptor fetched a file that was not there. It is rewritten on copy, and an
  existing sheet whose descriptor names another image is `invalid-atlas`.
- An existing spritesheet was accepted without its atlas descriptor.

### Added (3D)

- **Model specs.** `game-design` 1.3.0: `asset_requirements[].model`
  (`core/artifacts/shared/model-spec.schema.json`) — parts, PBR materials, generated
  textures, fit and pivot, named clips, LODs, a collision proxy, a budget. Validated for
  meaning (`wgf_assets/modelspec.py`) before anything is built; a malformed spec fails the
  requirement list like any malformed requirement.
- **The `blender` backend** (`wgf_assets/blender.py`, `blender_scripts/build_model.py`):
  discovery (`factory.assets.placeholders.blender.executable`, `WGF_BLENDER`, PATH), the
  pinned series `toolchains.blender` (4.5 LTS; another series refused unless
  `allow_unpinned`), a headless build through `wgflib.procs` in an isolated environment,
  byte-reproducible output, a stamped generation key, and reuse of a committed build without
  Blender. A buildable spec whose `source` is unset or `procedural` is delivered as the final
  asset; without Blender the procedural box stands in with `model-spec-unbuilt`.
- **GLB validation** (`wgf_assets/gltf.py`) on every `.glb`/`.gltf` the step touches, and the
  spec's declarations checked against it. `asset-manifest` 1.3.0: the item's `model` block
  and the issue codes `model-invalid`, `model-external-reference`,
  `model-unsupported-extension`, `model-needs-decoder`, `model-transform`, `model-scale`,
  `model-pivot`, `model-over-budget`, `animation-missing`,
  `animation-invalid`, `lod-missing`, `lod-invalid`, `collision-missing`,
  `model-spec-unbuilt`.
- **A GLB's runtime-manifest entry carries `model`** (clip names, LOD and collision nodes,
  dimensions; `shared/runtime-assets.schema.json`), and the loading contract is in
  `core/craft/3d-assets-and-animation.md`.
- `scripts/wgf-model.py` (`doctor`, `build --twice`, `inspect`), `scripts/tests/test_models.py`
  (fake-Blender, three.js runtime and opt-in `WGF_BLENDER_TEST=1` real-Blender layers), and a
  committed Blender-built fixture rebuilt byte for byte by the real-Blender tests.

### Changed (3D)

- `asset-policy` 1.2.0: `max_triangles` and `max_texture_edge` on the GLB kinds, and
  `toolchains.blender`. Manifests classified under 1.1.0 keep their pin; re-running the
  assets step re-classifies under 1.2.0 and may add budget warnings, nothing else.
- `encoders.png` takes an optional second checker colour (`alt`); existing output is
  unchanged.

### Fixed (3D)

- **A Three.js design got a 2D asset baseline.** The assets step inferred the dimension from
  3D-only requirements and art-direction words and ignored the design's own
  `engine.dimension`; the 3D golden (Neon Drift Arena, `engine: threejs, dimension: 3d`, no
  explicit requirements) received a background PNG and no model. The declared dimension now
  wins after an explicit `dimension` setting, so that golden's baseline is an environment, a
  player model, a material and a ground texture, listed in `public/assets/assets.json`.

### Bringing an artifact forward

Nothing is required. 1.1.0 and 1.2.0 game designs and asset manifests stay valid (every
addition is optional). To use the 2D fields, add them to a design's `asset_requirements` and
re-run `assets`; a game adopts the runtime manifest by loading through it
(`core/craft/2d-assets.md`). A design gains models only by adding `model` specs. Manifests
classified under `asset-policy` 1.1.0 keep their pin; re-running the assets step
re-classifies under 1.2.0 and may add budget warnings, nothing else.

## [2.4.0] - 2026-09-30

A minor version: one new adapter surface and the evidence and fixes MV-4 produced. No engine,
workflow, lifecycle, gate, schema or template-contract change, and no template pin change
(still `v1.2.0`). Release record: [docs/v2.4-release.md](docs/v2.4-release.md).

**`/new-game`** is the first *workflow entry point*: one Claude Code command (and its Codex
prompt) that runs `core/workflows/new-game.workflow.yaml` through the existing engine and stops
at every gate for a person. The `/wgf-*` transition commands are unchanged. The Claude plugin
is released with the Factory, so it moves to `2.4.0` with `VERSION`.

MV-4 (`docs/mv-4-report.md`): real-world evidence, and the five Factory defects that running
the existing suite on a second operating system exposed. Its Windows measurements were taken
against template `v1.1.0`, the pin in force when they were made; 2.3.0 moved the pin to
`v1.2.0`.

### Added

- **`/new-game`, a workflow entry point in the Claude Code plugin** (and `commands/new-game.md`
  in the Codex adapter): one command that starts, or with `resume <run-id>` continues, a run of
  `core/workflows/new-game.workflow.yaml` through the existing workflow engine
  (`bin/wgf new-game` / `bin/wgf resume`), in the background, and reports it from
  `bin/wgf status`. The engine and the workflow file stay the only orchestrator - step order,
  retries, loops, gates, decisions and resume - and the command restates none of it nor
  composes the `/wgf-*` commands. Gate decisions stay human-owned: it never runs `wgf decide`
  or `--decision` (from the session they would be recorded as a person's), refuses those
  arguments, and at every gate or develop handoff stops with the command the person types.
  It reports the configured autonomy without changing `factory.yaml`, and warns before a real
  run whose init creates a GitHub repository. `disable-model-invocation: true`.
  - A new binding surface kind, `workflow` (`workflows:` in
    `core/bindings/adapter-binding.yaml`, manifest 1.5.0), generated by `gen-adapters.sh`
    from its own table. `commands:` stays transitions only: the 13 `/wgf-*` commands are
    byte-identical after regeneration.
  - `check-integrity.py` checks each entry point against its workflow file (a `core/` path
    named `<id>.workflow.yaml`, whose id it is, with exactly the gates its checkpoints
    name). `scripts/tests/test_adapter_binding.py` ties the binding, the generator tables,
    the generated files and both `CONFORMANCE.md` files together by id, and holds the entry
    points to pointing at the engine and never answering a gate.
  - Claude plugin `2.4.0`, with `VERSION`: installed copies see the update and pick the new
    command up. Its full name in Claude Code is `/web-game-factory:new-game`.
- `scripts/mv4/`: the MV-4 evidence harness. `session.py` + `session.spec.ts` measure a built
  game in a real browser on the bytes that would ship (load, frame times, audio unlock,
  visibility, resize, heap across a restart, telemetry), labelling every measurement with the
  class of thing it was taken on; `device.py` records a real-device measurement or an explicit
  UNVERIFIED with the reason, and refuses a capture that does not carry the handset's identity;
  `playtest.py` computes the two player kill criteria and refuses to count a developer test or
  to report a share from fewer than five first-time participants; `packaging.py` audits what a
  release actually packaged; `g4.py` assembles the G4 record and refuses to let a weaker
  measurement class decide a criterion. Tests: `scripts/tests/test_mv4.py`.
- `docs/mv-4-plan.md`, `docs/mv-4-playtest-protocol.md`, `docs/mv-4-touch-sheet.md`,
  `docs/mv-4-report.md`, and the evidence under `docs/evidence/mv-4/`.

### Fixed

- **A reviewer's blocker could name a file outside the repository.** The guard on
  `blockers[].file` was written on `os.path.isabs`, which is the host's rule: on Windows with
  Python 3.13+ it accepted `/etc/passwd`, and on POSIX it accepted `C:\Windows\x` and
  `..\..\secrets.env`. `wgflib.paths.repo_relative` now judges the string - no leading
  separator of either kind, no drive, no `..` on either separator - so every host agrees.
  Regressions in `test_core_security.HostileIdentifiers`.
- **No child process could be started on Windows.** `CreateProcess` does not apply `PATHEXT`,
  so `procs.run(["pnpm", ...])` failed with `WinError 2` against an installed `pnpm.CMD` and the
  step reported the tool as not startable. `procs` now resolves `argv[0]` on the child's own
  `PATH` when it has no directory part, accepting only a file - a directory of the same name on
  `PATH` satisfies `shutil.which` and then fails as `WinError 267`. POSIX behaviour is
  unchanged. Regressions in `test_core_process.ResolvingTheProgram`.
- **An agent could not start a tool at all on Windows.** The agent environment is an allowlist
  and it held only the POSIX names; without `SystemRoot` no child starts there, so every golden
  run's developer refused with `NotADirectoryError: [WinError 267]`. The same basics are now
  allowlisted under the names Windows uses (`SystemRoot`, `windir`, `COMSPEC`, `PATHEXT`,
  `SystemDrive`, the Program Files and ProgramData locations, `USERPROFILE` / `APPDATA` /
  `LOCALAPPDATA`), and names are compared the way the platform compares them. No credential
  name was added and the secret-name filter is unchanged. Regressions in
  `test_core_security.AgentEnvironment`.
- **The refusing proxy reported isolation it did not have.** `wgflib.netguard` is set through
  the proxy environment variables, which Chromium reads on Linux and ignores elsewhere in favour
  of the system configuration. Its summary now carries `enforced` and, when false, the reason,
  so `refused_requests: 0` cannot be read as "nothing got out" on a platform where nothing was
  routed through it. The proxy itself is unchanged. Regression: `test_netguard.Enforcement`.
- **A finished run's report was lost to the console's encoding.** Anything the CLI prints can
  carry a character the console cannot encode; on cp1252 that raised `UnicodeEncodeError` after
  the work was done and printed nothing at all (a whole `test-core --json` run). The CLI's
  streams now escape what they cannot encode. Regression:
  `test_workflow_cli.ConsoleEncoding`.
- **The release tests could not reach their own fixture on Windows.** The suite shims `pnpm`
  as an extension-less script with a `#!` line, which Windows cannot execute; the real `pnpm`
  was found instead and the tests measured a repository with none of the fixture's scripts. The
  fixture writes a `pnpm.CMD` beside the shim there. No test changed what it asserts.
- **A golden run record differed by host**: `scripts/golden/live.py` wrote the config's path
  with the host's separator. It now uses `paths.display`.
- **The Claude plugin reported `0.4.0` through 2.3.0.** Claude Code detects a plugin update by
  `plugin.json`'s `version`, and it had not moved since 2.0.0, so an installed plugin never saw
  one. The plugin is released with the Factory: its version is now `VERSION` (`2.3.0`), and
  `check-integrity.py` fails when the two differ or when the marketplace entry sets a version
  of its own. Regressions in `test_check_integrity.PluginVersionTest`.

## [2.3.0] - 2026-09-29

Both engines gained ground. **Phaser is a second 2D engine** — `engine.type` accepts
`phaserjs` next to `pixijs` and `threejs`, the pinned template ships `@wgf/phaser-framework`
(web-game-template 1.2.0), and a Phaser title gets its own craft playbook and skill. **The
Three.js half of the pipeline gained the craft it never had**: three 3D playbooks, a physics
decision recorded at G3, and engine notes in the develop brief. And the acceptance gate that
could not run on a Windows host now runs on a Linux runner in CI, which is how both golden
runs were proved for this release.

**PixiJS remains the 2D default and is unchanged**: a design that records `dimension: 2d` and
no engine still selects `pixijs`, and no existing artifact, workflow, gate, role or platform
changed.

A minor Factory version with a **major template contract** (`CONTRACT_VERSION` 1.0.0 → 2.0.0):
`packages/phaser-framework/` and `src/rendering/phaserjs/` follow from the new engine id by
the template's naming convention, and they are required entries, so a repository generated
from a template older than 1.2.0 is now refused by init. That is the whole breaking surface.

**Upgrading from 2.2.x:** re-pin nothing by hand — `workspace/config/template.lock.json`
already names web-game-template `v1.2.0`. What you will see:
- A game repository created before the pin move is still built and verified as before; it is
  only `init` that refuses to *create* one from an older template.
- A design may now declare `engine.type: phaserjs`. Nothing selects it for you.
- A Phaser title's develop brief recommends the `web-game-factory:phaser` skill and, as a
  generic skill, the Phaser Game Agent — for reading API knowledge and reusable blocks, never
  for writing the checkout: that tooling owns its own cloud project layout, and here the
  template owns the layout and the build.

### Added

- **3D craft playbooks** (`core/craft/3d-scene-and-physics.md`,
  `core/craft/3d-assets-and-animation.md`, `core/craft/3d-diagnostics.md`). The template's
  Three.js binding is a renderer, one scene and one camera, so a 3D game writes its whole
  runtime; the Factory now says how. Parts adapted from
  `majidmanzarpour/threejs-game-skills` (MIT). The `threejs`, `web-performance`, `qa` and
  `gameplay-review` skills read them (adapter binding 1.3.0); no new surface id.
- **`tech-plan.architecture.physics`** — optional, additive, so every existing tech plan
  stays valid. The physics approach and its exact package are decided at G3
  (`with: {physics: custom|rapier|cannon-es}`), never inferred from the design and never at
  development time. The develop brief quotes the line and allows only the package it names;
  the reviewer treats an unplanned physics dependency as a blocker.
- **Engine notes in the development brief**, for `threejs` only (`brief.json`
  `engine_notes`; a 2D brief is unchanged): what the renderer binding already owns, the one
  update order, the model and clip checks after import, restart releasing everything, and a
  required `@boot` assertion that the canvas is neither blank nor a single flat colour, with
  the renderer's counters logged. No new gameplay aspect and no Factory-side probe: a 3D
  build that renders nothing otherwise passes every check it has.
- `docs/3d-benchmark.md` — the protocol for measuring the 3D developer capability. No
  results are recorded; the only measured baseline is the golden pair.

- **`phaserjs` in `core/artifacts/tech-plan.schema.json`** (`engine.type` and
  `repo_params.build.engine`), which is the one list `wgflib.template_contract.ENGINES` and
  `guards.supported_engines()` read. The renderer package and rendering directory follow from
  it by convention; the drift test holds both against the pinned template.
- **`core/craft/phaser.md`** and the generated `phaser` skill in both adapters (binding
  manifest 1.4.0): the loop game-core owns and Phaser does not, scenes and their shutdown,
  assets, input, tweens, arcade physics, tilemaps, cameras, audio, a debugging table and a QA
  pass. `pixijs` and `threejs` are untouched.
- **Phaser conformance in `develop`.** `phaser` and `phaser/*` are the engine's modules for a
  `phaserjs` game, importable only under `src/rendering/phaserjs/`; for any other game they
  are refused exactly as before. A `package.json` dependency on another template engine's
  library is now a finding too, not only a dependency on an engine the template does not
  carry — previously a dependency nothing imported yet went unnoticed.

### Changed

- **The pinned template is web-game-template 1.2.0.** It adds `@wgf/phaser-framework`, the
  third `createRenderer` branch, `pnpm build:engine <engine.type>`, and an engine-per-bundle
  build: `import.meta.env.WGF_ENGINE` is defined from `game.config.yaml`, so Rollup drops the
  engines a build does not use. A PixiJS build no longer carries the Three.js chunk, and
  carries no Phaser.
- `ENGINE_FOR_DIMENSION` is now the *default* engine per dimension, and `DIMENSION_FOR_ENGINE`
  is an explicit map (two engines are 2D, so it is no longer an inverse).

## [2.2.0] - 2026-09-28

Factory 2.2.0 (`docs/v2.2-release.md`): MV-3 of the post-production plan (PR #8) - a release
and verification that only claim what the build can ship - plus the root cause of the
long-standing process-liveness flake and a decidable template-contract versioning rule. A
minor version: it adds verification checks, a release refusal code, step metadata, a
liveness field and contract records, and breaks no consumer (the compatibility evidence is
in the release record). No schema, workflow, configuration or `CONTRACT_VERSION` change.

**Upgrading from 2.1.x:** nothing to configure. What you will see:
- A release draft holds only the package for the platform the build targets (game.config.yaml's
  first `required` platform, else its first); the other platforms are named as not packaged,
  and verification reports them `not-ready` (`platform.build-target:<id>`). They need
  per-platform builds (template contract 2).
- A game whose game.config.yaml has two `required` platforms now fails verification: one
  bundle cannot be both portals' build. The strategy module always writes one.
- The runtime facts' fps and time to interactive appear as `policy.device-performance`,
  evidence `PASS_MOCK`: a desktop proxy, not a device.

### Fixed

- **Release drafts shipped one bundle under every platform's name.** On the pinned
  template (contract 1.0.0) `pnpm build` makes one bundle, which boots one adapter, yet
  `release:package` zips it for every `platforms[]` entry: the 2.1.2 production run's
  `crazygames.zip` and `yandex.zip` were its Poki build, and would have loaded Poki's SDK on
  both portals. The release step now removes, between `release:package` and
  `release:manifest`, every archive for a platform the build does not target, and rewrites
  `packages.json` and `checksums.txt` in the template's formats; the step's message and
  metadata (`not_packaged`) name them; a foreign package that reaches the manifest anyway is
  refused (`package-not-built`).
- **Verification called those platforms ready.** Their profile assertions passed because the
  template's `platform_sdk` fact echoes the platform it is asked about. New check
  `platform.build-target:<id>`: PASS for the target, FAIL (with the reason) for every other
  platform - an optional one is `not-ready` without failing the verdict, a second required one
  fails it. The rule is `template_contract.build_target`, held against the pinned template by
  a drift test that will fail when per-platform builds arrive.
- **Proxy performance read as device evidence.** fps and time to interactive, measured in
  CPU-throttled desktop Chromium, sat inside `policy.runtime-facts`' PASS. They are now
  `policy.device-performance`, PASS with evidence `PASS_MOCK`, not required.
- **`wgf status` could call a healthy chatty child hung** - the root cause of the recurring
  `test_core_process.SilentChildInAStep.test_a_chatty_child_stays_running` failure. Captured
  under load on WSL2: the wall clock stepped 2.7 s forward in 0.1 s of monotonic time, and
  liveness judged output silence as `now - last_output_at`, which counts any clock step
  between the driver's stamp and the observer's `now` (NTP corrections, WSL resyncs, resumed
  laptops do this). Output-hung is now judged on `output_silence_seconds` =
  `last_heartbeat_at - last_output_at`: the silence the driver measured on its monotonic
  clock, in which a step cancels out. `output_idle_seconds` is still reported, never judged.
  The `on_hung: cancel` watchdog was never affected (it acts on the monotonic `idle_s`).
- **The template contract's versioning rule contradicted itself**, and 2.1.1's new
  `SOURCE_PATHS` entry (`src/game/boot-scene.ts`) was recorded nowhere. The rule now follows
  acceptance only (major: a repository accepted before can be refused; minor: an assumption is
  dropped; neither: an entry only recognized when present, or a rule the pinned contract
  already had). That entry is only recognized, so `CONTRACT_VERSION` stays 1.0.0 - by the
  rule, not by omission. `CONTRACT_LOG` records every change and `CONTRACT_DIGEST` (a sha256
  over the entries, never their descriptions) makes an unrecorded change fail the tests.

Regressions: `test_template_contract` (BuildTargetTest, the drift rule, the digest, the log,
descriptions are not entries), `test_verification.PlatformAndPolicy` (three),
`test_release_module.Drafting` (two, and the drafted-packages expectation),
`test_core_workflow.OutputLiveness` (the captured clock step, a real silence after a step,
output after the last heartbeat).

## [2.1.3] - 2026-09-28

A patch release (`docs/v2.1-release.md`, *2.1.3*): the first increment of the post-production
plan - G4 plumbing and G4 honesty - found by the 2.1.2 production run. No configuration,
schema or workflow change. **Upgrading:** nothing to configure. With lifecycle sync on, a
G4 `pass` over unmeasured kill criteria now logs the guard as UNKNOWN (it read GREEN); the run
proceeds on the person's decision as before.

### Fixed

- **The G4 `iterate` reason never reached the developer.** It was recorded (decision-record
  `rationale`, `DECISION_RECORDED`) but decision-record is not a develop input and the brief's
  "Why this is another iteration" read only visit budgets: the developer was told to "fix what
  sent it back" with nothing saying what that was, and the production run's next visit changed
  no game code. develop now quotes the newest decision of the route's source step when its
  choice is the route's (`brief.json` `loop.decision`), or says none was recorded.
- **"Development visits ... 1 of 9" was not the budget.** It was develop's `max_visits` loop
  guard, reset by every resume; 7 of 9 developer sessions were spent. The brief now states the
  developer budget - sessions used before this visit and left (`brief.json` `sessions`).
- **`kill_criteria_not_breached` read GREEN on a prototype nobody had played.** develop writes
  every strategy kill criterion as `measured: null, breached: false` until something measures
  it; the guard counted only `breached`. An unmeasured criterion now makes it UNKNOWN.
- **G4 showed only its choices.** `wgf status` and the output of `new-game`, `decide` and
  `resume` now print what the waiting checkpoint's inputs say - each kill criterion as
  breached / not breached / unmeasured with its value, a warning when any is unmeasured,
  playtest sessions by `player_context`, report verdicts and evidence status
  (`wgflib.gate_evidence`; `status --json` `pending.evidence`). It decides nothing.

Regressions: `test_develop_module` (five brief tests), `test_decisions.KillCriteriaGuard`,
`test_gate_evidence`, `test_workflow_cli.MockNewGame.test_g4_shows_the_evidence_it_is_decided_on`.

## [2.1.2] - 2026-09-28

A patch release (`docs/v2.1-release.md`, *2.1.2*): an ownership gap between the develop and
sdk steps, found by the live production validation of 2.1.1. No configuration, schema or
workflow change. **Upgrading:** nothing to configure; a game repository whose develop commits
changed one of the sdk step's files now blocks at sdk instead of losing that change - move
the work into the game's own files through develop.

### Fixed

- **The sdk step silently erased developer work in its own files.** It writes five files
  whole on every run - `src/platform/gameplay.ts`, `src/platform/game-integration.ts`,
  `src/platform/integration-plan.ts` and the two suites
  `tests/unit/platform/gameplay-integration.test.ts` and
  `tests/unit/platform/game-integration.test.ts` - but the brief named, and conformance
  checked, only the two seam files. In the 2.1.1 production run a developer fixing an
  sdk-review blocker added its regression test to the SDK-mock suite; the next sdk run
  rewrote the file, sdk-review blocked the deleted test, and the loop - invisible to the
  developer - used up the run's developer budget. Now `wgflib.gameseam.SDK_OWNED_PATHS` is the
  one list: the brief names the files (`sdk_owned`; own code and tests go in files of the
  game's own), develop's conformance refuses a change to any of them against the visit's
  baseline commit, and the sdk step BLOCKS rather than overwrite one whose last change is a
  commit its ledger does not record. A committed link at one of those paths therefore blocks
  the sdk step instead of being replaced (its target is still never written). Regressions:
  `test_develop_module.SdkOwnedFiles`, `test_sdk_integration.Commits`.

## [2.1.1] - 2026-09-28

A patch release (`docs/v2.1-release.md`, *2.1.1*): one false positive in the develop step,
found by the live production validation of 2.1.0. No configuration, schema or workflow
change; nothing to do to upgrade.

### Fixed

- **The develop conformance check refused a game-owned `BootScene`.** It refused any
  `src/main.ts` that contained the word `BootScene`, meaning to catch the template's scaffold
  scene still being started. The 2.1.0 production run's developer replaced that scene as the
  brief asks, with its own first scene - also named `BootScene`, in `src/scenes/boot-scene.ts`
  - and all three develop attempts were refused on the class name; the run failed at develop
  with a conformant build. The check now resolves each relative import in game source and
  refuses one that resolves to the template's scene module, `src/game/boot-scene.ts` (static,
  dynamic or re-exported; a re-export through another module was not caught before). The path
  is in the template contract's `SOURCE_PATHS`, so the pin is drift-tested for it. The rule
  is unchanged: a game does not start the template's `BootScene`. Regressions:
  `test_develop_module.Conformance` (a game-owned `BootScene` passes; the template's scene
  imported directly, without extension, dynamically or through another module is refused).

## [2.1.0] - 2026-09-27

Factory 2.1.0 (`docs/v2.1-release.md`): the fixes found by live-agent and production
validation of 2.0.0 (PR #4), against the unchanged template pin (v1.1.0, `bca41a9`). A minor
version: it adds the live build, two archetypes and two blocking design-consistency rules
(`design-consistency-rules.yaml` 1.2.0); no 2.0.0 default, schema or workflow definition
changed. **Upgrading from 2.0.0:** nothing to configure. A design made under 1.1.0 rules is
not re-evaluated; a run that redoes `design` meets the concept rules, and a strategy whose
concept no archetype carries now fails design rather than getting the nearest genre.

Found by the fresh live-agent validation of the v2.0.0 tag (`5b74e30`), which failed both
live tests with the documented argvs.

### Fixed

- **Live evidence is reproducible from the repository.** The 2.0.0 live runs used prompts
  kept only as `...` excerpts in `docs/claude-capabilities.md` (a custom developer prompt,
  and a reviewer `--append-system-prompt` that narrowed the review to one file); they could
  not be rerun. The live tests now read the developer and reviewer argvs from the commented
  examples in `workspace/config/factory.yaml`, verbatim (`golden.live.shipped_agent_examples`
  - the parser `ShippedConfig` checks them with), use the steps' own prompts, and record both
  argvs and the host's version in the run's evidence. `WGF_LIVE_DEVELOPER_ARGV` is no longer
  read; `WGF_LIVE_REVIEWER_ARGV` becomes an optional override.
- **A live run started without a run budget.** The post-2.0.0 production validation records
  every run under `develop.budget: {max_sessions: 6, max_cost: 120}`, but that was added to
  each configuration by hand: `live.py config` wrote none, so a run started from the
  repository alone had no run-level bound on paid developer sessions (only the host's
  per-session `--max-budget-usd`). `golden.live.build_live_config` now writes
  `LIVE_BUDGET` and records it in `live-agents.json`. Regression:
  `test_live_loop.LiveConfig.test_a_live_run_starts_under_the_documented_developer_budget`.
- **`WGF_LIVE_KEEP` with both live tests in one invocation** errored the second test: it
  copied its scratch over the first's, onto read-only git objects. Each test now keeps its
  evidence in `<dir>/<test id>` (`.2`, `.3` ... on a rerun), never over an earlier run's.
  Regression: `test_core_agents.LiveEvidence`.
- **`LiveReviewer` asserted what a competent reviewer must not do.** After the scripted fix it
  required no blocker on `src/game/score.ts`, but the fixture is a stub that does not implement
  the brief's design, and the reviewer - told to judge against the design - correctly keeps a
  blocker on it. It now asserts what the fixture can prove: the reviewer finds the planted
  bug, every verdict is trusted, the blocker reaches the developer's next brief, and the next
  review reads the fixing commit. The assertion was not weakened to pass: convergence moved to
  a scenario where it can legitimately happen (below).
- **`LiveDeveloperAndReviewer` removed**, for the same reason: on the stub, approval needed a
  review narrowed by a prompt the shipped reviewer does not have.

### Added

- **The live build** (`scripts/golden/live.py`, `test_live_loop`, AGENTS category, opt-in
  `WGF_LIVE_AGENT=1`, costs money): the golden 2D pipeline with the documented developer
  building the game from scratch from the Factory's brief and the documented reviewer judging
  it against the design, asserted to converge - completed, last development commit and sdk
  commit approved, every develop check green, only the developer's own files changed,
  isolation intact, no process left. `live.py config --human-gates` writes the same
  configuration for a run a person drives with `bin/wgf` and decides G2, G3 and G4.
  `GoldenRun.sandbox()` is the one seam it overrides (no refusing proxy: the hosts need their
  API).
- **"Which files are yours" in the development brief** (`wgf_develop.brief`): inside the
  writable paths, the template's own source (`TEMPLATE_SOURCE`: `src/core/`,
  `src/platform/bind.ts`, `src/rendering/create-renderer.ts`, `src/types/`) and the Factory's
  seam are not the developer's; a missing or broken one goes in `known_issues`, never into a
  patch, and review blockers are fixed only in the developer's own files. In the v2.0.0 live
  run a developer "fixed" a blocker about the seam's imports by writing `src/platform/bind.ts`
  and `src/core/config.ts`. Guidance only: conformance enforces what it did before.
  Regressions: `test_develop_module.FileOwnershipInTheBrief`, `TemplateSourceShipsInThePin`
  (every named path ships in the pinned template; every template file the seam imports is
  named).

### Fixed (found by the first clean production run and clean-machine gate after it)

- **G3 was answered blind to its own timebox predicate.** The tech plan reports an overrun
  only as a `STEP_LOG` warning ("plan exceeds the timebox; G3 decides"), which no console
  printed: the stopped 2026-09-26 run's G3 was approved over 18.0 estimated days against
  10.5 allowed. `wgf`'s console now prints warning- and error-level step logs with their
  facts. (The kernel still decides nothing with them: it may not import the lifecycle
  guards, and a checkpoint's inputs stay its gate's `required_artifacts`.)
- **A one-word strategy MVP item became a duplicate feature.** "Localization: en, ru"
  shares one significant word with the Localization feature and so never folded into it:
  two Localization features, two plan tasks. An item whose significant words a feature
  covers entirely is now folded. Regression: `test_design_module.StrategyMvpFolding`.
- **Clean-machine golden runs broke when the registry moved.** The 2D golden failed at
  develop from an empty HOME with `ERR_PNPM_NO_OFFLINE_META` for `earcut` after
  `pixi.js@8.21.0` was published: the warm-up's online install reused the template
  lockfile's `earcut@3.2.3` without fetching its metadata, and the replay's offline
  resolution needed it. `golden.harness.warm_store` now resolves online without the
  lockfile (metadata for the whole graph), then performs the replay's exact offline
  resolution once in a second copy, so a store that cannot serve it fails before the
  sandbox, naming the package.

### Changed (installation calibration)

- **`factory.techplan.estimates` is calibrated for this installation** in
  `workspace/config/factory.yaml`, by the portfolio owner's decision after G3 rejected a plan
  of 20.0 days against 10.5 allowed. The defaults put the drop-merge MVP at 87.5 h; the live
  build `new-game-20260927-044345-3c20a0` took 2.12 agent-hours for it (develop + review,
  from its event log). Rule fixed before the result: f = 4 x measured / heuristic = 0.097,
  rounded to 0.1, applied to every hour constant; `hours_per_day` unchanged. Any factor from
  about 1 to 40 would clear the allowance, so the outcome does not hinge on the choice.
  Workspace data, not core; the defaults in `wgf_techplan/devplan.py` are unchanged, and the
  golden and live configurations inherit the calibration. Derivation:
  [docs/handoff/2026-09-27-production-validation.md](docs/handoff/2026-09-27-production-validation.md).

### Fixed (found by the live builds on the corrected design)

- **The brief told the developer to break its own commit boundary.** It said "Run `pnpm
  format:write` before you finish"; that is `prettier --write .`, the pinned template is not
  prettier-clean (why the shipped checks leave `format` out), and a live developer's 61-minute
  build was refused for 20 reformatted template files. The brief now says to format only the
  files the developer created or changed. It also says scratch files go under `$TMPDIR`: a
  later live developer left `scratch-sim.mjs` in the repository root and was refused.
  And it names the two `src/main.ts` rules conformance enforces (no engine import, no
  template `BootScene`), which two independent live builds broke, a paid retry each.
- **sdk read the design's own placement id as the wrong moment.** A game calling
  `interstitial("interstitial-between")` - the design's touchpoint id, on leaving the result
  card - was classified by the id's words ("between" -> level-complete) and the required
  platform failed as `partial`. A design touchpoint id now takes that touchpoint's moment.
- **sdk planned two placements for one moment.** The design-derived entry
  (`rewarded-game-over`) stayed beside the game's own id at the same moment; the generated
  runtime resolves by kind and moment, so ad telemetry went out under the unused id (found by
  the live sdk-review). The game's own placement now supersedes it.

Validation record, runs and the two decisions left to a person:
[docs/handoff/2026-09-27-production-validation.md](docs/handoff/2026-09-27-production-validation.md).

### Fixed (design follows the strategy)

- **The design described a different game from the strategy it was built from, and passed
  its own checks.** Root cause: the design module chose its archetype by counting genre
  keywords over the whole strategy, and had one "merge" shape - a 7x7 swap-and-match level
  game - so the approved drop-merge strategy (drop numbered pieces onto a seven-column track;
  equal neighbours merge and cascade) got a swap design; the 3D strategy (steer between walls
  that rush toward the craft; a crash ends the run) likewise got a checkpoint time trial.
  Nothing compared the design with the strategy's concept. Fixed at three layers:
  - two archetypes for the games those concepts describe: `drop-merge` and `arena-dodge`
    (`wgf_design/archetypes.py`), with rules and numbers matching the pinned template's
    Tower Merge Rush and Neon Drift Arena;
  - selection reads each archetype's `signature` - the terms of its core mechanic - against
    the strategy's concept first, genre keywords second;
  - *Reason (core change, core/reference):* `design-consistency-rules.yaml` 1.2.0 adds two
    **blocking** rules, `concept_mechanics_carried` and `design_adds_no_foreign_mechanic`,
    over a `concept_terms` vocabulary: every core mechanic the strategy's concept names must
    be in the design's own text (core loop, the MVP mechanics it defines, the MVP controls -
    not text folded in from the strategy), and the design may add none the strategy does not
    name. A pinned archetype that is not the strategy's game is now refused. The old golden
    2D and 3D designs both fail them.
  The golden replay ports map the new MVP features, all `built`; the replay's known issue
  "the design is a swap-based level puzzle" is gone because it is no longer true.
  *Migration:* a design made under 1.1.0 rules is not re-evaluated (artifacts are
  immutable); a run that redoes `design` meets the new rules, and a strategy whose concept
  no archetype carries now fails design instead of getting the nearest genre.
  Regressions: `test_design_module.Choices` (one per golden concept, every archetype
  selected for its own game, a contradicting pin refused) and `ConceptFidelity`.

## [2.0.0] - 2026-09-26

Factory 2.0.0 (`docs/v2-release.md`): the release audit's fixes on top of everything since
1.1.0, validated with both golden runs against the unchanged template pin (v1.1.0,
`bca41a9`). A major version because defaults a 1.1.0 installation or script relied on
changed - each listed under **Breaking** with how to keep working. No schema's required
fields changed.

Since 1.1.0: the architectural audit that followed it - Wave 1 (P0 safety, template
contract, CLI, test honesty), Wave 2 and Wave 3 (M1-M13) - and the game production workflow:
the `core/craft/` playbooks, adapter binding 1.2.0 (Claude plugin 0.4.0) and the step-module
follow-ups F1-F7. Entries name their module (M*, F*); core changes are listed with their
reason, as docs/core-v1.md requires. What a 1.1.0 installation, script or run meets unchanged
is listed first, under **Breaking**, each with how to keep working; the entries below carry
the detail and the migration notes.

### Breaking

Every one fails closed and has a way back; none changes a schema's required fields.

| Change | Who notices | Keep working by |
|---|---|---|
| Developer and reviewer processes get an allowlisted environment, not the Factory's (M1) | A `command` developer or reviewer that authenticates from an environment variable (`ANTHROPIC_API_KEY`, ...) | Naming it in `factory.agents.env_passthrough` |
| Code run in the game repository gets the allowlist too (M1b) | A `pnpm install` / build that reads a registry token from the environment | `factory.agents.game_env_passthrough`, or the credential in `~/.npmrc` |
| The development commit holds only `writable_paths`; `package.json` may only gain dependencies; hidden paths and capitalised `*.md` are refused (M1). 1.1.0 committed `git add --all` | A developer that edits scripts, config or files outside `src/`, `tests/`, `public/`, `docs/development/`, `index.html` | `factory.develop.writable_paths`, `allowed_package_changes` |
| Release refuses a build no review approved (M7). The shipped `review.reviewer.kind: none` therefore refuses every release | Anyone releasing without a reviewer | Configuring a reviewer, or `factory.release.allow_unreviewed: true` (carried as UNREVIEWED) |
| `new-game` has G4 (`prototype-review`) and `sdk-review`; release requires G4 passed (M4, M7) | `wgf new-game --mock` now stops WAITING at G4 and exits 3; a run past sdk started under 1.1.0 is refused at release | `wgf decide <run-id> pass`; a custom workflow's release sets `required_gates: []` |
| `wgf status` exits as the run: 1 failed/blocked/cancelled, 3 waiting/paused (M11) | Scripts running `wgf status && ...` | Reading `wgf status --json` `status` instead of the exit code |
| Flag combinations that were silently ignored, and usage errors that exited 1, exit 2 (M11) | Scripts passing `--mock`/`--mock-plan`/`--hold-gates`/`--project` with `--resume`/`--run`, `--from` with `--run`, `--note` without `--decision`, `--decision` without `--resume` | Dropping the ignored flag |
| A relative `factory.storage.directory` resolves against the repository root, not the working directory (M11) | Runs made under 1.1.0 from another directory are not found | `--store <dir>` or an absolute `storage.directory` |
| Resuming a 1.1.0 run whose state claims `mock`, `mock_plan` or `auto_approve` is refused: its params were never recorded (M2) | Old mock or auto-approved runs | Starting a new run |
| A gated checkpoint waits until its gate's `required_artifacts` are in the run (M4) | Custom workflows | Listing those artifacts as the checkpoint's inputs |
| Release refusal code `commit-lineage-mismatch` is now `review-commit-mismatch`; reviewer evidence files are named `<step>-<visit>-<attempt>.*` (M7) | Scripts matching the code or hard-coded verdict paths | Matching the new names; `{verdict}` / `WGF_REVIEW_VERDICT` are unaffected |

### Upgrading from 1.1.0

1. Take the new `workspace/config/factory.yaml`, or merge it. Its top-level `checkouts: ..`
   now decides where game checkouts are; a legacy key you customised (`develop.checkouts`,
   `init.projects_dir`, ...) is still read, but set `checkouts` to that value.
2. Name the agent host's credential in `factory.agents.env_passthrough`, and any registry
   credential the game build reads from the environment in `game_env_passthrough`.
3. Configure a reviewer (`factory.review.reviewer`), or accept unreviewed releases with
   `factory.release.allow_unreviewed: true`.
4. Optionally bound developer spend with `factory.develop.budget`: develop may now be
   visited up to 9 times in a run (the loops are bounded per route, M13).
5. Finish or restart 1.1.0 runs: they resume under the new definition - `new-game` is now
   version 2, so the resume records `definition_version: 2` and says it continues under a
   newer definition - and one already past sdk must pass sdk-review and G4 before release.
6. Check scripts against the exit codes above (`wgf status`, exit 2 on refused flags,
   `new-game --mock` exiting 3 at G4).

### Added

#### Workflow engine and gates (M3, M4)
- **Timeout auto-approval (M4).** `factory.checkpoints.timeout_auto_approve: {G2: 48h}`
  lets a reversible gate approve itself once it has waited that long. *Reason (core
  change, wgflib/workflow):* gates.yaml's `auto_approve_after` was documented but never
  implemented. Conservative by construction: only listed gates; an irreversible or unknown
  gate listed refuses the run at start; the windows are snapshotted into the run's params
  (corroborated on resume, and a run started before has none); `waiting_since` is recorded
  per visit from the engine clock and corroborated by its `STEP_WAITING` event, and upstream
  work redone restarts it; the approval is recorded as `DECISION_RECORDED`
  (`decided_by: automation`, `mode: timeout`) and applied only by `wgf resume` - `wgf
  status` and `wgf runs --waiting` report eligibility and change nothing. *Migration:* none;
  the default is no window, as before.
- **A silent child reads `hung`, and can be stopped (M3, P0-13).** The step state keeps
  `last_output_at` (the child wrote something, or a lifecycle event) and
  `last_heartbeat_at` apart from `last_activity_at` (any event, heartbeats included), and
  `wgf status` reads `hung` with `hung_reason: output` when heartbeats show the driver alive
  but the child has written nothing for `factory.execution.hung_output_seconds` (default
  900: above the reviewer's 600 s and the developer's documented 900 s idle timeouts), or
  `hung_reason: driver` as before. The status text says which, and names `wgf cancel`.
  Opt-in watchdog `factory.execution.on_hung: cancel` (default `none`): the driving engine
  terminates such a child's tree through the cancel path, the step ends not retryably, and
  a `STEP_LOG` warning says why; the policy is snapshotted into the run's params and
  corroborated on resume. *Reason (core change, wgflib/procs + wgflib/workflow):* every
  heartbeat refreshed `last_activity_at`, so a live but stuck child always read `running`
  and nothing acted on `hung`. *Migration:* none; older `state.json` has neither new field
  and derives as before, and a run started with `on_hung: none` records no new params.
- **SIGKILL recovery (M3, P0-12).** Children of a step carry
  `WGF_PROC_RUN=<run-id>@<store digest>`; resuming - or cancelling - a run that is
  `RUNNING` with no live driver first terminates every process still naming that run
  (Linux `/proc`; elsewhere a warning that it cannot) and logs the pids. Nothing untagged,
  and nothing of another run or store, is touched. *Reason (core change, wgflib/procs +
  wgflib/workflow):* a SIGKILLed driver runs no cleanup, so its trees were orphaned and no
  later process knew their pids.

#### Contracts, template contract, CLI and test-core (M9-M12)
- `wgflib/template_contract.py` (CONTRACT_VERSION 1.0.0): every path, npm script, CLI and
  output the Factory assumes of a game repository, used by init, verification, sdk and
  release, with a drift test against the pinned template (M10, `docs/template-contract.md`).
- `wgf resume`, `wgf decide`, `wgf runs --waiting [--json]` (M11).
- `wgf test-core --strict` (exit 4 on a SKIP category; opt-in tests skipped inside a PASS category are listed, not failed); the summary never reads a bare OK when
  anything was skipped, and every skipped test is listed by reason (M12).
- `docs/env-vars.md`; `test_review_module.py`, `test_netguard.py`, `test_check_integrity.py`,
  `test_template_contract.py`.
- **`x-wgf.version` and one provenance builder (M9, P1-6).** Every top-level schema declares
  its contract version (semver) as `x-wgf.version`; check-integrity requires it.
  `scripts/wgflib/provenance.py` (`build`, `artifact_id`, `producer`, `pin`, `pin_inputs`,
  `seal`, `version_of`) replaces the provenance each step module and the mock steps
  assembled by hand; `schema_version` is read from the schema. `ArtifactContracts` refuses
  an artifact whose `provenance.schema_version` has another MAJOR than `x-wgf.version`.
  Versions, set to what the producing module already emitted: asset-manifest 1.1.0,
  game-design 1.1.0, qa-report 1.1.0, release-manifest 1.2.0, scaffold-record 1.1.0 (1.2.0 after M6),
  sdk-report 1.2.0, title-strategy 1.1.0, verification-report 1.1.0; decision-record,
  evaluation, opportunity, performance-review, platform-publication, prototype-report,
  research-report, review-report, state and tech-plan 1.0.0. *Core change, reason:* the
  version a producer claimed was a per-module constant nothing checked (sdk carried two,
  1.2.0 and 1.1.0). *Migration:* existing artifacts stay valid - only the major is compared,
  and every artifact written so far is major 1. Mock runs now write each schema's version
  instead of 1.0.0 for all, so new mock artifacts hash differently; real modules' output is
  unchanged apart from key order inside `provenance`, which the content hash ignores.
- **`x-wgf.run_path` (M9, P1-1).** Artifacts a workflow step produces name where an engine
  run stores them, `<storage>/workflows/<run-id>/artifacts/<id>/v<n>.json`, next to
  `repo_path`, their home in the methodology (workspace/ or the game repository), which the
  engine never writes (docs/artifact-contracts.md). *Migration:* none; `repo_path` keeps its
  meaning for adapters.

#### Game production workflow (craft layer, F4-F7)
- **The developer brief recommends the plugin's craft skills (F7).**
  - `brief.DEFAULT_SKILLS` names `web-game-factory:game-feel`, `core-loop`,
    `web-performance`, `audio` (area `craft`), `onboarding-ux` (`ui`), and the engine's
    `pixijs` / `threejs`, alongside the generic skills.
  - Configured areas are no longer silently dropped: every area except the other engine's
    reaches the brief. `[]` drops an area.
  - `develop.skills` is validated.

  *Migration:* none.

- **Opt-in developer self-playtest (F6).** The defaults are unchanged: developer `handoff`,
  `self_playtest: false`.
  - `developer.argv` gains a `{factory}` placeholder (the Factory root, substituted once).
  - New `workspace/config/mcp-playwright-localhost.json`: `@playwright/mcp@0.0.82`, headless,
    isolated, localhost origins only.
  - New `develop.self_playtest` setting, which adds a "Playtest your build" section to the
    brief.
  - A second commented developer block in `factory.yaml` (`--- opt-in: self-playtest`) adds
    `--mcp-config`, `--plugin-dir` and `Skill` / `mcp__playwright` to the verified argv,
    keeping `--strict-mcp-config` and every restriction.
  - `docs/claude-capabilities.md` records it as VERIFIED offline, UNVERIFIED live.

  *Migration:* none.

- **Shaped procedural audio (F5).** The procedural backend's sound effects were a bare sine
  tone. They now come from a deterministic jsfxr-style synthesiser (`encoders.synth`):
  waveform, envelope, pitch slide, vibrato and arpeggio. The preset (ui, coin, jump, hit,
  powerup, whoosh, lose, blip) is picked from the item's words and detuned by its id. Music
  is an 8 s bass-and-arpeggio loop (`encoders.music_loop`). The files remain placeholders,
  factory-generated and never production-ready, and each item's notes name its preset.
  *Migration:* none; `encoders.wav` is kept.

- **The `agent` design author (F4)**, `scripts/wgf_design/agent.py`. It is opt-in
  (`factory.design.author: agent`); the default stays `archetype`.
  - An agent host improves the archetype's draft from a request holding the strategy, the
    platform profiles and a starting draft.
  - The design module then applies exactly the checks it applies to any author:
    `finalize`, buildability, and the consistency rules including `descope`.
  - A malformed draft is refused before `finalize` (not retryable). A failing or silent
    host is retryable.
  - The design is attributed `actor: ai`.
  - The design step's brief now carries `config`, `run_dir`, `visit` and `attempt`.
  - `factory.yaml` has a commented read-only host example.

  *Migration:* none.

- **`core/craft/`: production craft playbooks.** What a *good* web game looks like inside
  the fields the artifacts already have: core loop and difficulty, game feel (a minimum
  feedback bar, distinct from polish), onboarding and portal UX, UI/HUD/mobile, audio, art
  direction, accessibility, web performance, playtesting (agent playthrough, stranger
  playtest and performance pass protocols), a gameplay-review checklist, competitive
  teardowns, and provider-neutral tool capability classes with their limits. Stage files
  `design`, `prototype`, `qa` and `tech-plan` point at them. `prototype.md` clarifies that
  the feedback bar is not the polish it warns against. *Migration:* none; no field, state
  or gate changed.
- **Adapter binding 1.2.0.** Eight new skills (`core-loop`, `game-feel`, `onboarding-ux`,
  `audio`, `art-direction`, `web-performance`, `gameplay-review`, `playtesting`). Existing
  skills and agent must-read lists are widened to the playbooks; `gameplay` and `ui` now
  read the game-design schema, and `asset` reads the asset policy. Skill entries list their
  `reads:`, which the integrity check verifies. Claude plugin 0.4.0; both adapters
  regenerated. *Migration:* none.
- `docs/production-craft-and-mcp.md`: skills and MCP tools by phase, what belongs in host
  configuration versus the repository, and Factory-module follow-ups found in the audit
  (F1-F7, since implemented: see the entries in this section and under Changed).

### Changed

#### Definition versions
- `new-game.workflow.yaml` is `version: 2` and `gates.yaml` `1.1.0`: the workflow gained
  sdk-review, G4 and per-route loop limits, and G3/G4 changed their required artifacts. A run
  keeps the version it started under; resuming a version-1 run records `definition_version`
  in `WORKFLOW_RESUMED`. *Migration:* none; `wgf status` shows `new-game (v2)`.

#### Gate semantics (M4)
- **G4 `prototype-review` is a real checkpoint** in `new-game`, after `verify` passes and
  before `release`, decided on the verified `qa-report`, `verification-report` and
  `prototype-report` against the kill criteria and design (`title-strategy`, `game-design`),
  with `pass` / `iterate` / `kill`. gates.yaml G4 `required_artifacts`, the title machine's
  prototype-review inputs, the stage procedure and every schema's `required_for_gates` agree
  on those five, and check-integrity now fails when a schema's `required_for_gates`
  disagrees with gates.yaml. *Reason (core change,
  core/workflows + wgflib/workflow):* the workflow went from verify straight to release, so
  the one gate the factory exists for - the kill gate - was never asked. `iterate` returns
  to develop (a success routed back; lineage kept) and G4 asks again; `kill` ends the run
  (BLOCKED routed to `$end`: `DECISION_RECORDED`, `exit.route: kill`, `wgf status` "Ended:
  kill at G4", exit 0) and the run cannot be continued. Only a person decides it.
  *Migration:* `wgf new-game --mock` now stops `WAITING` at G4 - answer it with
  `wgf decide <run-id> pass`; scripts that expected it to complete unattended must decide
  G4. A run started before this change resumes under the current definition; one whose
  cursor is already past verify (at release) is not sent back to G4 by a plain resume, but
  `--run release` in it is refused until G4 is passed.
- **A gate is passed only by a forward answer.** The engine refuses a later step past a
  gate whose last answer routed backwards (`iterate`, `rework`) or ended the run, not only
  past one never answered; `--run` in skip mode asks such a gate again. *Reason:* `iterate`
  is a SUCCESS and would otherwise have counted as passing G4. `context.gates_passed` lists
  the gates a run has passed (for steps that want to check). *Migration:* none for a run that
  answers its gates forward; a custom step that relied on passing a gate answered backwards
  now waits for it again.
- **A checkpoint is decided on its gate's `required_artifacts`** (gates.yaml): without them
  in the run, as the step's inputs, it waits for input and asks nobody. G2 and G3 now list
  them as inputs. gates.yaml: G3 no longer requires `asset-manifest` (assets are sourced
  after G3), G4 requires the verified evidence. Each schema's `x-wgf.required_for_gates`
  now agrees with gates.yaml, which check-integrity enforces: `research-report` no longer
  claims G1 (G1 is decided on `opportunity` and `evaluation`), `asset-manifest` no longer
  claims G3, and `qa-report` / `verification-report` gain G4. *Migration:* a custom workflow
  whose gated checkpoint does not list its gate's required artifacts as inputs now waits for
  input.
- **Reject and kill stop the run**; a run a decision ended at `$end` exits 0 and shows
  `Ended:` in `wgf status` (`ended_by` in `--json`), and `--run` refuses to continue it.
  *Migration:* scripts that treated a rejected run as failed read `ended_by` instead.
- **`design.on.descope: $fail`**, explicit: a blocking design-consistency breach ends the
  run with the design's own message (it already did, unrouted).

#### The shipped commit is reviewed, and release refuses what was not (M7)
- **`sdk-review`: the sdk commit is reviewed too** (P0-8). `new-game` gains a step after
  `sdk`, before `verify`: `type: review`, `stage: title:prototype`, `with: subject:
  sdk-report`, inputs `sdk-report`, `prototype-report`, `game-design`, `scaffold-record`.
  The review step reads a generic `with: subject` (`prototype-report`, the default, or
  `sdk-report`): the reviewed commit is that artifact's `build_ref.commit_sha`, which must
  be HEAD; for the sdk subject the brief's change is prototype commit..sdk commit. Its
  `request-changes` routes to `develop` - the developer fixes the game side, sdk integrates
  again, both reviews run again, `max_visits` bounds it; a requested change never reaches
  verify. Verdict files are now `<run>/review/<step>-<visit>-<attempt>.*`, so the two
  reviews never overwrite each other. `sdk-report`'s x-wgf consumers gain
  `title:prototype`. *Reason (core change, core/workflows + core/artifacts):* `review` read
  develop's commit, then sdk committed integration code on top of it, and that unreviewed
  sdk commit is what verify checked and release shipped.
- **Release refuses an unreviewed or mis-reviewed build** (P0-9). The newest review-report
  must approve exactly the commit being released (the sdk commit, HEAD), from a reviewer
  that ran (`reviewer.kind: command`), pinning the run's newest prototype-report and
  sdk-report. `skipped`/absent is `unreviewed` (FAILED, not retryable); an approval of
  another commit - develop's alone included - or of an older report is
  `review-commit-mismatch` (was `commit-lineage-mismatch`). New
  `factory.release.allow_unreviewed` (default `false`, read only from config, never a
  step's `with:`) drafts a skipped/absent review anyway, recorded as UNREVIEWED; it waives
  nothing else. *Reason:* release recorded "UNREVIEWED" and shipped, and with the shipped
  `review.reviewer.kind: none` every release was unreviewed.
- **Release checks G4 itself** (M4 follow-up). `evidence_refusals` takes the engine's
  `context.gates_passed` (a required keyword: no default) and refuses `g4-not-passed`
  (BLOCKED) unless every gate in the release step's `with: required_gates` (default `[G4]`,
  read only from the workflow, never from config) is passed and current. The step cannot
  see its workflow definition and no engine change was in scope, so the workflow declares
  what its release requires and the default fails closed; `test_workflow_definition` checks
  every shipped workflow's release requires each irreversible gate it checkpoints.
- `--mock`: the review mock approves the commit its subject names (`reviewer.kind: none`,
  so no real release could accept it); the review-report fixture is `approve`.
- *Migration:* **with the shipped `review.reviewer.kind: none`, every real release is now
  refused (`unreviewed`)** - configure `factory.review.reviewer` (see the commented Claude
  Code block in factory.yaml), or set `factory.release.allow_unreviewed: true` knowingly. A
  custom workflow with a `release` step and no G4 checkpoint must add `with:
  required_gates: []`; one that lists `review-report` as a release input should add a
  review of the commit it ships. A run in flight past `sdk` when this lands has no
  sdk-review: resume it `--from develop` (or `--from sdk-review` in a run whose sdk commit
  is HEAD) to get the approval release now requires. Existing drafts are unaffected.

#### Gates emit decision-records (M5)
- **Workflow gates emit decision-records (P1-1, P0-11).** The G2, G3 and G4 checkpoints emit
  a schema-valid `decision-record` on every decided outcome - a person's choice,
  auto-approval, timeout approval, reject and kill - whose subject and provenance pin exactly
  the evidence consumed. One table in `wgflib/workflow/decisions.py` maps workflow choices to
  the schema (`kill` -> `abandon`). check-integrity requires every step naming a gate to
  output a decision-record, and only such steps may. *Reason (core change):* CLAUDE.md said
  every gate emits one; workflow gates did not. *Migration:* runs gain one
  `decision-record-<step>` artifact per decided gate visit.
- **Lifecycle bridge.** `factory.lifecycle.sync` (default off, snapshotted per run) appends a
  run's decision-records to `workspace/titles/<id>/decisions/` and advances the title cursor
  through `wgf-state.py`'s own guards and gate rules; a refused move is a warning, never the
  run's outcome. Never for a `--mock` run.
- **Guards read run evidence.** `ci_green`, `verify_suite_green` and `playable_build` can
  answer from a run's qa-report and verification-report (`wgflib/guards.py` `RunEvidence`);
  `PASS_MOCK` never counts as a pass for `verify_suite_green` / `playable_build`.
- `test_decisions` joins the WORKFLOW category of the Core Acceptance Suite.

#### One checkout resolver (M6)
- **One checkout resolver (P0-14, P1-2, P1-3).** `wgflib/checkout.py`: every step that
  touches the game repository finds it by `with: repo_dir|game_repo` -> `WGF_GAME_REPO` ->
  scaffold-record `repository.local_path` -> `factory.checkouts` + name, relative paths
  resolved against the Factory root (docs/checkouts.md). *Migration:* `factory.checkouts`
  replaces `develop.checkouts`, `init.projects_dir`, `review.checkouts`, `sdk.games_dir`,
  `verification.checkouts` and `release.checkouts` (deprecated aliases, warned when they
  disagree), and the sdk step's `sdk.game_repo` (a checkout, honoured for sdk only, with a
  warning); `WGF_GAME_REPO` now applies to every step that reaches the game repository -
  init, assets, develop and review as well as sdk and verify. Unset it where only one step
  should see it.
- A per-checkout advisory lock (pid + start time) blocks a second live run from working in
  the same tree while a step runs (`checkout-in-use`).
- scaffold-record 1.2.0 adds an optional `repository.local_path`, written by init.
- Assets default into `<checkout>/public/assets/`, which develop commits; the develop brief
  lists every asset's repository-relative file paths. *Migration:* set `assets.root` to keep
  them elsewhere.
- Vendored platform profiles are verified by content hash in init, verify
  (`platform.profile:<id>`) and sdk (`wgf_init.profiles.verify_pins` / `pin_identity`).
- `wgf_develop` reads its template literals from `wgflib/template_contract.py`.

#### Loop and session budgets (M13)
- **Loops into one step are bounded per route (P1-7).** A workflow step may declare
  `max_visits_by_route: {<route>: n}`; entries through that route (the label or outcome
  that routed into the step) are counted in the step's new `route_visits` and bounded apart
  from each other, while `max_visits` still holds. A key is a route from any step or
  `<source>.<route>` from one step; entries are counted per `<source>.<route>`. new-game's
  develop takes `review.request-changes: 2`, `sdk-review.request-changes: 2`, `fail: 2`
  (verify) and `iterate: 2` (G4) over the run, with `max_visits: 9` on develop and on every
  later step of the loop. Route budgets last the run: resuming a run a route limit stopped
  refills that limit only; `--from` and `--run` (an explicit fresh start of a slice)
  refill all of them (M13 review: the two reviewers had
  shared one `request-changes` count, and every resume refilled every route, so G4's
  `iterate` - always decided by a resume - was never bounded).
  *Reason (core change, core/workflows + wgflib/workflow):* the four loops back into develop
  shared develop's one `max_visits` of 3, so a review loop could spend the passes a failing
  verification needed, and nothing said which loop had. The definition refuses a key that
  is no route into its step; the engine names no route.
- **Why a run stopped at a loop limit is data.** `state.blocked_reason = {kind: loop-limit,
  step, route, scope: step|route, limit, entered, from}` (also `WORKFLOW_BLOCKED`
  `data.blocked`), and resume's "one more pass" is decided from it instead of the message
  prefix (P1-8). *Reason (core change, wgflib/workflow):* string coupling. Integrity checks
  its shape and the route counters like `loop_base`.
- **A run-level budget for developer sessions that resume does not reset.**
  `factory.develop.budget: {max_sessions, max_cost, cost_from: {jsonl_key}}`, snapshotted
  into run params (`develop_budget`, corroborated like every param). The develop step counts
  command-developer sessions and their reported cost from the run's event log (STEP_LOG
  `data.budget`) and returns `BLOCKED` - no agent spawned - with `budget exhausted: N
  developer sessions used of N`, or on the cost limit. A session with no readable cost is
  counted and reported as unknown; the host's per-session flag stays that session's bound.
  *Reason (core change, wgflib/budget.py, wgflib/workflow/{config,api,integrity}.py):* every
  resume refilled the loop budget, so with a command developer nothing capped a run's
  sessions or spend.
- **Raising a budget is a person's act:** `wgf resume <run> --budget-sessions N |
  --budget-cost X` records a `BUDGET_RAISED` operator event (new generic
  `engine.resume(operator_events=...)`: refused for `decided_by: automation` and for the
  engine's own event names). Refused from inside a step's process tree. A raise counts only
  when the engine's `WORKFLOW_RESUMED` corroborates it by `resume_nonce`, and whatever
  another process writes to the run's event log during a step is taken out again (Security:
  the event log is sealed while a drive holds the run). Before the M13 review, any appended
  `BUDGET_RAISED` line naming a person was honoured. `develop_budget` is a guarded param.
- A step's context gains `entered_by` (`<source>.<route>` of this visit, e.g. `verify.fail`), `visit_budget` (what the
  visit leaves of its limits) and `read_events()` (the run's recorded events);
  `STEP_STARTED` carries `entered_by`. The develop brief says which loop brought the work
  back and how many passes it has left (`brief.json` `loop`); a first visit (`<step>.success`)
  has none.
- *Migration:* none required. A run started before this change has no `route_visits`,
  `blocked_reason` or `develop_budget` and resumes as before (a loop-limit stop recorded only
  in its message still gets its one more pass); it has no budget, since none was
  snapshotted. `factory.develop.budget` applies to runs started after it is set.
  `max_visits_by_route` counts only from this version: an old run's earlier loops are not
  charged to any route. `wgf new-game --mock --mock-plan '{"verify": [fail x4]}'` now
  blocks on develop's `fail` route (as before, after the third failed verification); a
  review that always requests changes still blocks on its third request, and a third G4
  `iterate` now stops for a person. develop may be visited up to 9 times instead of 3 when
  the loops mix - set `factory.develop.budget` to bound what a command developer may spend
  in the run.

#### CLI and test-core (M11, M12)
- `wgf status` exits with the run's code (1 failed/blocked/cancelled, 3 waiting/paused).
  Flags a command would silently ignore are refused (exit 2), and so are the usage errors
  1.1.0 reported with exit 1 (`--decision` without `--resume`, `--resume` with `--run`,
  `--force` without `--run`). An environment failure (a full disk, a read-only store) exits 1
  with one line, no traceback. pause/cancel import no step module. A relative
  `factory.storage.directory` resolves against the repository root, not the directory `wgf`
  is run from (M11). *Migration:* see Breaking; runs made from another directory are reached
  with `--store`.
- `wgf sdk-review` and `wgf prototype-review` run those steps on their own, like every step
  of the workflow (the commands are the workflow's step ids).
- Test opt-in flags mean exactly `=1`; `WGF_TEMPLATE_REPO` (a pin bypass) is removed, the
  real SDK suite runs on the pinned checkout with `WGF_TEMPLATE_SDK_TEST=1` (M12).

#### Game production workflow (F1-F3)
- **`docs/GDD.md` is rendered into the game repository (F3).** `game-design` declared
  `rendered_to: <game-repo>/docs/GDD.md`; nothing produced it. The develop step now writes
  it (`scripts/wgf_develop/gdd.py`) in `core/templates/gdd.md`'s section structure, pinned to
  the design's artifact id and content hash. It is written before the developer runs and again
  after, so a hand edit never survives, and it is committed with each visit. The development
  and review briefs point at it. The golden reviewer allows `docs/GDD.md`. The scaffolding
  procedure and the GDD template now say who renders it. M1's commit scope accepts exactly
  `docs/GDD.md` (`scope.FACTORY_RENDERED`, fixed): the step re-renders it after the developer,
  so the committed file is always the Factory's; any other capitalised `*.md` stays refused.
  *Migration:* none. `docs/tech-plan.md` is still not rendered; the tech plan reaches the
  developer through the brief (F1), and `core/templates/tech-plan.md` now says so.

- **The review brief adds a gameplay lens and a design-fidelity section (F2).** "Look for"
  was code-only. It now also covers what players feel: restart state, frame-rate
  independence, pause, double starts and taps, tuning as data, frame-loop allocation, flash
  rate, audio unlock, and tests that reach their aspect. The lens is condensed from
  `core/craft/gameplay-review.md`. When the committed development brief carries F1's
  `build_spec` / `dev_plan`, the brief lists the MVP feedback, the tutorial approach and each
  task's acceptance criteria to check against. *Migration:* none; the verdict contract is
  unchanged.
- **Golden reviewer: every blocker carries `file`** (null for a whole-build finding).
  `scripts/golden/reviewer.py` omitted the key. `wgf_review.verdict.parse` rightly
  discards such a verdict as malformed, which failed a golden run after a verify → develop
  loop.

- **The develop brief carries the design's `build_spec` and the approved plan's tasks (F1)**
  (core change: `core/workflows/new-game.workflow.yaml`). The design authored mechanics
  with rules and tuning, the difficulty curve, reward and failure feedback, tutorial steps
  and audio cues, and the tech plan authored tasks with acceptance criteria. None of it
  reached the developer, whose brief held only the design's summary strings. `develop` now
  takes `tech-plan` as an optional input. `brief.md` gains a "Build spec (MVP tier)" and a
  "Development plan" section, and `brief.json` gains `build_spec` and `dev_plan`.
  `sdk_touchpoints` stay with the sdk step and `assets` with the asset manifest. The
  prototype-report now pins the tech plan it was briefed from. *Migration:* none; a run
  without a tech plan, or a design without `build_spec`, briefs exactly as before. A run
  resumed at develop under this definition consumes its existing tech plan.

### Security
- **Developer boundary (M1).** develop's git runs hardened like the reviewer's
  (`wgflib/gitsafe`: pinned git dir and work tree, safe env, filter drivers neutralised
  unless `factory.develop.git.allow_filters`, signing programs off). `package.json`,
  `tsconfig.json` and `pnpm-lock.yaml` are protected: only dependency additions allowed by
  `factory.develop.allowed_package_changes` pass conformance, so a developer can no longer
  rewrite the `test`/`lint`/`test:e2e` scripts every later check runs. The Factory's guarded
  paths are fingerprinted and restored around the developer. The commit is scoped to
  `factory.develop.writable_paths`; hidden paths (`.claude/`, `.github/`, ...) and agent
  instruction files are refused. Developer and reviewer processes get a scrubbed
  environment (`wgflib/agentenv.py`; add names with `factory.agents.env_passthrough`).
  Reviewer isolation moved to `wgflib/isolation.py`. *Migration:* a live agent host that
  authenticates through an environment variable needs it in `env_passthrough`; a developer
  that edited package.json scripts or wrote outside the writable paths now fails develop.
- **Game code gets no Factory secrets (M1b).** The code the Factory runs inside a game
  repository - the develop checks, verify's commands, the sdk conformance suite and release
  packaging, all written or editable by the developer agent - ran with the Factory's whole
  environment. It now gets `wgflib/agentenv.game_code_env`: the agents' allowlist (plus
  `PLAYWRIGHT_*` and `COREPACK_*`, toolchain configuration) and the names in the new
  `factory.agents.game_env_passthrough` (default `[]`) - never the agents'
  `env_passthrough`. Core change (`wgflib/agentenv.py`): the allowlist is shared kernel
  code, and one definition keeps the agents' and game code's rules from drifting.
  *Migration:* an installation whose `pnpm install` (or build) reads a registry or other
  credential from an environment variable must name it in `game_env_passthrough`;
  credentials in `~/.npmrc` under HOME keep working.
- **Run params are corroborated (M2).** `WORKFLOW_STARTED` records the run's params and
  resume refuses a state.json whose params differ. *Migration:* a run started before this
  change whose state claims `mock`, `mock_plan` or `auto_approve` is refused on resume;
  start a new run.
- **`--from` cannot step over a gate (M2).** A fresh run started with an explicit `--from`
  past a gate in its scope is refused (`wgf new-game --from design` skipped G2). Fresh
  single-step runs (`wgf verify`) are unaffected.
- **The event log is sealed while a drive holds the run (M13 review, release audit).**
  Decisions and budget raises are corroborated from `events.jsonl`, and while a drive holds
  a run the engine is its only writer. After every step the engine compares the log with
  exactly what it wrote: anything another process appended, edited or truncated - a forged
  `BUDGET_RAISED` with the `WORKFLOW_RESUMED` that would corroborate it, a negative cost
  line, forgotten sessions - is put back (`EVENT_LOG_RESTORED`) and the step fails, not
  retried. That covers every step that runs a developer's or an agent's code, including the
  develop checks that run its tests, which an earlier session-only audit did not. A raise
  also needs its engine-written `resume_nonce`, and a cost that is not a non-negative finite
  number lowers nothing. *Core change (wgflib/workflow/{store,engine,events}.py), reason:*
  the only legitimate writer of a driven run's log is the engine, so anything else there
  can only be a forgery, from whichever step ran it. *Residual:* no hash chain or secret; a
  process that edits the run directory while no driver holds the run (one that escaped its
  step's process tree) is outside this.
- **The Factory never writes its files through links in the checkout (release audit).** The
  develop step's brief, `docs/GDD.md`, integration seam and `checks.json`, and the sdk
  step's integration files, were written with a plain open(): a symbolic or hard link the
  developer left in their place had the Factory write its text to a Factory file or the
  run's event log, where no guard comparison followed. They now go through
  `wgf_develop/safewrite.py` - no linked directory, and the file's directory entry replaced
  (temp file + rename), never written through - and the commit scope refuses a
  `docs/GDD.md` that is not a plain file. An unsafe directory fails the step, not retried,
  having written nothing. *Migration:* none.
- **The design agent host gets the allowlisted environment (F4).** Like the developer and
  the reviewer: `wgflib.agentenv.scrubbed` plus `factory.agents.env_passthrough`, never the
  Factory's own environment.
- **The self-playtest opt-in stays inside the boundary (F6 with M1).** The installation
  guards `claude-web-game-plugin` (`factory.review.guarded_paths`), whose skills that
  developer loads; the Playwright MCP writes its snapshots to `/tmp`, outside the checkout.

### Fixed
- **Pre-publish checks (release record: docs/v2-release.md).** A live reviewer's whole-build
  finding no longer fails the run. The verdict contract's example shows a finding with
  `file: null` and no `line`, and `line: null` reads as no line; a missing `file` stays
  malformed. The golden runs warm the pnpm store themselves, online, before their offline
  sandbox, so they pass on a clean machine: from an empty HOME they failed at develop with
  `ERR_PNPM_NO_OFFLINE_META`. The live developer-and-reviewer test expects sdk-review of the
  shipped commit (M7). *Migration:* none.
- Run lock identity is pid + process start time, so a recycled pid no longer holds a dead
  run; an empty lock tolerates mtime skew (M2).
- Atomic writes use unique temp names; concurrent `LATEST` writes no longer race (M2).
- A cancel is honoured while a step waits out its retry backoff; a crash between entering a
  step and moving the cursor no longer burns a visit (M2).
- Platform profiles are identified by id, version and content hash; init re-vendors a
  same-version profile with other content, and `wgf_init.profiles.verify_pins` checks it.
  check-integrity reads platform ids from the pinned template, never the sibling, and warns
  on template profiles that diverge under the same version (M8).
- **x-wgf agrees with the workflow (M9, P1-1).** check-integrity now fails when a workflow
  step outputs an artifact whose `x-wgf.producer` is not the step's `stage`, or takes an
  input whose `x-wgf.consumers` omit it. The 11 disagreements it found are fixed in
  `core/artifacts/`: `asset-manifest`'s producer is `title:prototype` (the `assets` step;
  `title:design` joins `updated_by`); consumers gained `title:scaffolding` (game-design),
  `title:prototype` (qa-report, prototype-report), `release:qa` (prototype-report,
  scaffold-record) and `release:draft` (qa-report, verification-report, sdk-report,
  prototype-report), plus `title:prototype-review` on qa-report and verification-report for
  the G4 checkpoint. *Core change, reason:* two statements of who produces and consumes an
  artifact had drifted with nothing comparing them. *Migration:* none for artifacts; a
  workflow that uses an artifact at a stage its schema does not name now fails the check.
- **One validator for the release manifest (M9, P1-6).** `scripts/wgf_release/schema.py`, a
  second, subset JSON Schema validator, is deleted; release validates the manifest it drafts
  and the game repository's `manifest.json` with `ArtifactContracts` (full schema through
  `jsonschema_lite`, provenance type, contract major, hash). A game manifest that only
  passed the subset (wrong `artifact_type`, an impossible date) is now refused as
  `invalid-manifest`. *Migration:* none for the template's make-manifest.mjs.
- **Recorded gameplay sessions are validated against their schema (M9, P1-6).**
  `wgf_verification/checks/gameplay.py` validates `build/verification/gameplay-session.json`
  with `jsonschema_lite` against `shared/gameplay-session.schema.json` (formats, unknown
  keys, browser entries) instead of a hand-written subset, and keeps the one rule the schema
  cannot state (the aspect is one the template contract knows). *Migration:* a session with
  keys the schema does not define is no longer used; verification falls back to the
  repository's Playwright suites, as for any unusable session.

## [1.1.0] - 2026-09-25

Factory v1, usable (`docs/v1-usable.md`). Core v1 against the latest **released**
web-game-template, v1.1.0 (`bca41a97665f8a32d0f803d46a7bbd001ac94d41`), running one complete
real workflow - research to a drafted release - with a real Claude developer and a real
read-only Claude reviewer. Core v1's architecture is unchanged; contract changes are additive.
Live portal behaviour, submission and publishing remain BLOCKED_EXTERNAL.

### Added

- **Platform profiles for Y8, GameDistribution and GameMonetize**
  (`core/reference/platforms/`). The shared profile schema gains `requirements.game_id`
  (`required | optional | none`), `game_id_pattern` and `hosting`. *Migration:* none; the
  fields are optional.
- **Portal registrations** - `workspace/titles/<title>/portals.yaml` - carried by the tech
  plan into `game_config.platforms[].game_id` (and `hosting` / `game_url`); a required Game
  ID that is missing blocks the tech plan. tech-plan schema: `game_id`, `hosting`,
  `game_url` on platform entries. *Migration:* none.
- **The integration seam module.** The develop step provides `src/game/integration.ts` and
  `src/platform/integration.ts` (`createGamePlatform`, `createGameIntegration`) before a
  game is built; the sdk step writes its integrated wiring over the latter as a whole file.
  *Migration:* a game built before 1.1.0 does not boot through the seam, and the sdk step
  now refuses it; rebuild it through develop.
- **`wgflib.netguard`** (moved from the golden harness): the develop smoke check and
  verify's browser commands run behind a refusing proxy, so no test contacts a portal.
- scaffold-record `template.generated_from_sha` and `template.pin_commit`.

### Changed

- **Pinned to web-game-template v1.1.0**, a release, instead of the development commit
  `22482b4`. The golden runs read their ports from a separately pinned fixture commit.
- The tech plan's `repo_params.template_ref` is always `<repository>@<pinned sha>`; init
  refuses a plan approved against another revision and brings a repository GitHub generated
  from another revision to the pin with one local commit. *Migration:* a tech plan naming
  `<template>@main` must be re-planned.
- init writes `game.id`/`game.name` itself for either source (bootstrap's own derivation).
- The sdk step never edits `src/main.ts`; it reads seam calls with the game's TypeScript
  compiler, resolves named placement ids and reports unresolvable ones.
- The develop brief states verification's evidence contract (aspect tags and the aspects
  this build must prove); a retry after a failed developer is told to continue its work.
- Shipped Claude developer example: `--max-turns 400`, `--max-budget-usd 40`.

### Fixed

- Reviewer isolation no longer reports pnpm-store hard links as reviewer writes.
- A reviewer's fenced verdict after quoted code is found.
- See `docs/v1-usable.md`, "What the real runs found and fixed".

## [1.0.0] - 2026-09-24

Core v1, frozen (`docs/core-v1.md`). The executable workflow core - engine, persistence,
contracts, process ownership, agent runtime, verify and release - protected by the Core
Acceptance Suite (`bin/wgf test-core`) and two real golden pipelines, Tower Merge Rush
(PixiJS) and Neon Drift Arena (Three.js). Validated against web-game-template
`22482b4eb81084a89ff8ecdeea9130f06ebb8026` (`workspace/config/template.lock.json`).
Everything below was added on the way there. Portal QA, publishing and real ad fill remain
BLOCKED_EXTERNAL.

### Added

- **Core v1 hardening (security pass).** `scaffold-record.repository.name` refuses `.` and
  `..` (schema pattern; consumers also resolve checkouts through
  `wgflib.paths.checkout_path`). `wgflib.procs.install_subreaper()` — installed by the `wgf`
  CLI — reparents orphans to the Factory, so a descendant that detaches and clears its
  environment is still ended with its step. *Migration:* a scaffold-record naming `.` or
  `..` was never usable; none exist.

- **Review module (`scripts/wgf_review`, step type `review`) and the `review-report`
  artifact.** An independent reviewer reads every development commit and approves it or
  requests changes with named blockers. The loop is data: `new-game` now runs
  `develop → review → sdk`, with `review` `on: {request-changes: develop}`, and
  `max_visits` bounds it. Request-changes is `FAILED` with a route and not retryable, so
  a workflow that forgot to route it fails closed. The reviewer is read-only and that is
  enforced: HEAD, refs, index, every tracked and untracked file, package/lock/test/config
  paths, `.git/config`/hooks and the Factory's `core/workflows` + `workspace/config` are
  fingerprinted before and after. Any change fails the review
  (`reviewer-isolation-violation`) and is undone. Verdicts are validated strictly
  (`malformed-verdict`). Timeouts and crashes are retryable and end the whole process tree
  through `wgflib.procs`. `kind: none` records `skipped`, never an approval. `develop`
  now takes `review-report` as an input: a request for changes to the commit it starts
  from puts the blockers first in the next brief (`review_blockers`). It also gains an
  optional `developer.idle_timeout_seconds`. Proved by
  `scripts/tests/test_core_agents.py`, the AGENTS category of the Core Acceptance Suite,
  with real subprocesses, real git and the real engine. See `docs/review-module.md`.
  *Existing artifacts:* none change. Existing runs of `new-game` resume into a workflow
  that has one more step. Installations must add `wgf_review` to `factory.steps.modules`
  (done in the shipped config) or run it with `--mock`.

- **Full schema validation inside the engine (`scripts/wgflib/jsonschema_lite.py`).** A
  standard-library JSON Schema draft 2020-12 validator covering every keyword
  `core/artifacts/**` uses (enumerated by the tests), with `$ref` across the shared schemas,
  asserted formats, ECMA-faithful patterns and JSON-pointer errors in a fixed order. It raises
  on any keyword it does not implement instead of ignoring it. `ArtifactContracts` now
  validates the whole schema, not only top-level keys, rejects content JSON cannot represent
  (NaN, non-string keys, Python-only values), and caps diagnostics at 20 while always keeping
  the provenance type and hash problems. New `check_lineage(content, consumed)` checks that
  `provenance.inputs` pins exactly the input versions a step consumed; the engine does not
  call it yet. Deliberately stricter than ajv-formats@2 in one place: a `date-time` must
  carry an RFC 3339 offset. **Bringing an artifact forward:** nothing to do if it already
  passed ajv; every workspace instance, reference file and module output under the test
  suite validates unchanged. See `docs/core-contracts.md`, which also audits every pipeline
  boundary. No schema changed.

- **Tech-plan module (`scripts/wgf_techplan`, step type `tech-plan`) and the G3 checkpoint.**
  `new-game` now runs design → `tech-plan` → `tech-plan-review` (G3, reversible, same shape
  as `strategy-review`) → init, as the title machine always said. The module is minimal and
  deterministic: the engine is the one the design declares (dimension or asset kinds only as
  a fallback for older designs), platforms are the strategy's pins resolved against
  `core/reference/platforms/`, the bundle budget is the tightest required limit, ad kinds
  come from the design's placements, and the dev plan's estimates are a stated heuristic
  reported against the timebox, never fitted to it. See `docs/techplan-module.md`.
  *Existing runs:* a run started before this change has no `tech-plan` step; resume it as
  before, or start a new run to get one.
- **Init writes `game.config.yaml` from the tech plan.** With a `tech-plan` in the run, init
  rewrites `engine`, `platforms` and `monetization` in place (comments and every other field
  kept, the result parsed back and checked), vendors the pinned profiles into
  `config/platforms/`, and makes one local commit carrying the idempotency key as a trailer.
  It never pushes. A 3D design now reaches the game repository as `engine.type: threejs`
  instead of the template default.
- **Init `factory.init.source: local`.** Makes the project from a local template checkout
  (`template_path`, pinned by `template_ref`) with `git archive` into a new repository with no
  remote: offline, for golden-regression runs. `github` stays the default and is unchanged.
- **`scaffold-record` fields (additive, schema 1.1.0):** `template.source` (`github` |
  `local`), `game_config.engine`, `game_config.commit_sha`, `game_config.pushed`. Existing
  records remain valid; an absent `template.source` means `github`.

- **Release module (`scripts/wgf_release`, step type `release`, stage `release:draft`).**
  The `release` step is real: `wgf new-game` no longer needs `--mock` for it. It drafts a
  release only when the newest qa-report in the run passed, pins the newest
  verification-report, prototype-report and sdk-report by hash, and names the same commit as
  each of them and as the checkout's HEAD; the checkout is clean and its bundle is the one
  verification digested. It then runs the game repository's own `release:package` and
  `release:manifest` (as owned process trees, `wgflib.procs`), checks every package's sha256
  against its file, refuses archives with sourcemaps, test files, env/secret files or
  secret-looking content or without `index.html` at their root, validates the manifest
  against the schema, and returns it in state `draft`. It never pushes, tags, publishes or
  contacts a portal. See `docs/release-module.md`. **Contract change:** the `release` step
  now declares `verification-report`, `sdk-report`, `prototype-report` and
  `scaffold-record` besides `qa-report`; `factory.release.checkouts` locates the game
  repository.
- **Evidence statuses.** `PASS`, `PASS_MOCK`, `BLOCKED_EXTERNAL`, `UNVERIFIED`, `FAIL`, in
  the new shared primitive `core/artifacts/shared/evidence.schema.json`, alongside (not
  instead of) the routing statuses. A check observed only against a stand-in — every SDK
  feature exercised against a mocked portal SDK — is `PASS_MOCK`, and so is every
  verification, qa-report, platform and release manifest resting on one; nothing promotes it
  to `PASS`. A platform's own portal QA is `BLOCKED_EXTERNAL` unless its SDK evidence says it
  was observed on the live portal (`NOT_APPLICABLE` for a profile whose review process is
  `none`).

  *Schema changes, all additive:* `verification-report` gains `evidence_status`,
  `workflow`, `checks[].evidence_status`, `platform_readiness[].evidence_status` and
  `portal_status`; `qa-report` gains `evidence_status`, `workflow` and
  `platform_checks[].evidence_status` / `portal_status`; `release-manifest` gains
  `workflow`, `template`, `evidence` (what the draft was cleared by: qa and verification
  reports, commit lineage, bundle hash, per-platform evidence, package audit,
  reproducibility) and `packages[].content_digest` / `files`. Reports the verify step writes
  now declare `schema_version` 1.1.0; drafted manifests 1.1.0.

  *Migration:* none for existing artifacts, which stay valid. A qa-report without
  `evidence_status` (1.0.x) is refused by the release step: re-run verify.

- **Assets module (`scripts/wgf_assets`, step type `assets`).** Turns a game design into an
  asset manifest and the files behind it: inspects `game_design.asset_requirements` (or
  derives a baseline), classifies each against the new `core/reference/asset-policy.yaml`,
  reuses a design's existing file or a licensed library asset, otherwise generates a
  placeholder — through an optional 2D asset MCP server when one is configured, always
  falling back to a standard-library procedural backend — then validates formats from the
  bytes, optimizes losslessly and records licence, origin and usage constraints per item.
  An asset whose licence is unknown or restricted, or that has no recorded origin, is never
  `production_ready`. Covers 2D (sprites, sheets, backgrounds, UI, icons, VFX, fonts, audio)
  and 3D (models, textures, materials, animations, environments). Registered in
  `factory.steps.modules`; see `docs/assets-module.md`.

  *Schema changes, all additive:* `asset-manifest` items gain `dimension`,
  `license_status`, `usage_constraints`, `origin`, `placeholder`, `production_ready`,
  `files`, `reference`, `optimization` and `issues`, the `type` enum gains `background`,
  `material` and `environment`, and the manifest gains `policy`, `issues` and `generation`
  (instances now declare `schema_version` 1.1.0). `game-design` gains optional
  `asset_requirements`. The `assets` step and `title:prototype` now also consume
  `scaffold-record` (for platform bundle limits), and `title:prototype` names
  `asset-manifest` among its outputs.

  *Migration:* none. Existing manifests and designs stay valid.

- **Development module.** `scripts/wgf_develop` implements the `develop` step and is
  registered in `workspace/config/factory.yaml`. It briefs the build from the game design
  (`docs/development/brief.md` in the game repository), hands it to a developer — a person
  (`handoff`) or a configured command — then checks template conformance, typecheck, lint,
  tests, build and the browser smoke suite, commits once per visit, and emits a
  `prototype-report` that records only what it measured. See
  `docs/development-module.md`. **Contract change:** `develop` now declares
  `scaffold-record` and `title-strategy` as inputs in `core/workflows/new-game.workflow.yaml`;
  existing runs resume unaffected, and a run without them is told what is missing.

- **SDK integration phase (`scripts/wgf_sdk`).** Before its conformance check, the `sdk`
  step now integrates web-game-template's existing platform SDK into a game's gameplay: it reads
  the SDK the game repository carries, compares what each target platform's adapter offers
  with what the game-design needs, writes a gameplay layer (`bootPlatform`,
  `PlatformGameplay`), a plan generated from the design's placements and an SDK-mock suite
  into the game repository, routes the template's boot through it, and reports per platform
  and feature, laid over the conformance result (the worse status wins). It implements no
  SDK and contacts no portal. Settings in `factory.sdk`; `--mock` runs are unaffected. See
  `docs/platform-architecture.md`.
- **The sdk module checked against each portal's current documentation** (Yandex, CrazyGames,
  Poki, GameVui; 2026-09-23). The gameplay layer now keeps one "playing" state with the
  adapter's own, mutes and pauses for every ad and for the portal's own pause (Yandex
  `game_api_pause`), hands late rewards to the game, says why a reward was not granted,
  hides offers when the portal SDK did not load, and gives Poki an ad opportunity before
  every continue (`factory.sdk.break_on_continue`) while keeping interstitials off
  CrazyGames' pause menu (`factory.sdk.interstitial_forbidden_moments`). The boot timeout is
  gone: every adapter bounds its own waits, and replacing one on a timer lost Yandex Game
  Ready and CrazyGames gameplay events. `python -m wgf_sdk.e2e` builds a PixiJS and a
  Three.js game per platform from a template revision and drives it in Chromium against the
  template's own SDK mocks. Platform limitations are listed in
  `docs/platform-architecture.md`. The step also wires the develop module's seam
  (`src/game/integration.ts`): it implements `GameIntegration` on the platform, maps the
  game's own placement ids to the design's moments, and swaps the developer's default
  implementation out of `main.ts`.
- **Workflow module contract.** `docs/workflow-module-contract.md` is what the discovery,
  strategy, design, init, assets, development, SDK and verification modules implement
  against; `scripts/tests/test_workflow_contracts.py` holds the gate — an external module
  plugged in through `factory.steps.modules` runs without engine changes. The engine now
  checks every produced artifact against its schema's top level and provenance before
  persisting it, records which input versions each step consumed, versions its events
  (`format: 1`), accepts dot-namespaced step types, and validates run ids, artifact ids and
  module names before they reach a path or an import. `--mock` auto-approves only the
  workflow's own reversible checkpoint gates. Pausing or cancelling a crashed run takes
  effect at once.
- **`scaffold-record` and `sdk-report` schemas**, named as outputs of `title:scaffolding` and
  `title:prototype`, replacing the workflow's `untyped_artifacts`. Additive: no existing
  artifact changes. The title machine keeps version 1.0.0 because only its declared outputs
  grew.
- **Executable workflow engine (`wgf`).** `core/workflows/new-game.workflow.yaml` defines the
  work from research to release preparation as data; `scripts/wgflib/workflow/` runs it —
  step registry, retry with backoff, failure routing (`verify` fail → `develop`), human
  checkpoints tied to gates, resume, idempotent re-entry, events and a file store in
  `.factory/`. `bin/wgf` exposes `new-game`, `research`, `plan`, `init`, `assets`, `develop`,
  `sdk`, `verify`, `release`, `status`, `logs`, `runs`, `pause` and `cancel`, all through
  one engine. Every step is a placeholder (`--mock`) that emits schema-valid artifacts;
  nothing is researched, built or published. `workspace/config/factory.yaml` configures it.
  `check-integrity.py` now validates workflow files. Existing artifacts are unaffected.

- **`tech_plan.repo_params.game_config.monetization`** — the ad kinds a title commits to,
  carried into the game repository. Platform profiles assert on `package.uses_banner_ads` and
  `package.uses_rewarded_ads`, and on GameVui the latter is blocking; but observing a run can
  only prove an ad *was* requested, never that one is never requested. Without a declaration
  reaching the game repository, those assertions could not be evaluated honestly. Derived from
  `game_design.monetization.placements[].kind` — not decided in the tech plan.

  *Migration:* optional. An existing tech plan stays valid; a game repository built from one
  without it measures both ad facts as `false`.

- **`scripts/wgf-org-setup.sh`** — creates and reconciles the organization's `WGF_*` Actions
  secrets and variables for the game pipelines. Idempotent, and the living inventory of what
  the organization should hold. It never rewrites an existing secret's value: GitHub cannot
  return one, so `gh secret set` on an existing name would replace a real credential with the
  sentinel.

### Changed

- **Agent-host capability audit (docs/claude-capabilities.md).**
  - `workspace/config/factory.yaml` `review.guarded_paths` is back to the module default,
    `[core, scripts, bin, workspace/config]`. It had narrowed it to
    `[core/workflows, workspace/config]`, which undid the widening from the security pass.
    A test now pins it.
  - The file gains commented, verified headless developer/reviewer argvs for the one host
    audited. The active defaults (`handoff` / `none`) are unchanged.
  - Adapter binding 1.1.0: `architect` produces `review-report` as the read-only reviewer
    in `title:prototype`. `gameplay` and `release` consume what their steps read. Both
    plugins are regenerated.
  - `test_core_agents` gains `LiveDeveloperAndReviewer` (opt-in). `LiveReviewer` could not
    pass against a competent live host and is fixed.
  - No existing artifact is affected.

- **Commit lineage: a real run can release.** The pipeline develop → review → sdk → verify →
  release now names one chain of commits, and every step that reads it applies one rule
  (docs/core-contracts.md §5, `scripts/wgf_verification/lineage.py`). The `sdk` step commits
  its integration once, locally, keyed by the idempotency key in a `Wgf-Sdk-Key` trailer
  (reusing develop's keyed-commit mechanism), and never pushes; it refuses (`BLOCKED`) a
  checkout whose HEAD is not the prototype-report's commit or this run's sdk commits on it,
  and uncommitted changes it did not make. `sdk-report.build_ref` gains `base_commit_sha` and
  `sdk_commits` (**sdk-report 1.2.0, additive**). verify's `source.upstream-commits` and
  release both require: sdk-report commit == verified commit == HEAD; prototype-report commit
  == sdk base; `git log base..sdk` holds only this run's sdk commits — otherwise
  `commit-lineage-mismatch`. release now takes `review-report` as an input (workflow
  `new-game`, and `release:draft` added to its consumers): an approval must be of exactly the
  prototype commit, a request for changes refuses (`review-not-approved`), and a skipped
  review is recorded as `evidence.review.status: skipped` — never as approved
  (**release-manifest 1.2.0, additive**: `evidence.review`). Placeholder commits are gone:
  develop returns `BLOCKED` instead of `"0"*40`, sdk `BLOCKED` instead of `"unknown"`, and
  release refuses either as `commit-unknown`. The engine now enforces artifact lineage: with
  a validator, an output declaring `provenance.inputs` must pin exactly the versions its step
  consumed (`contracts.check_lineage`, plus no pin of a declared input the step was not
  given), else a non-retryable `FAILED`. Proved by `scripts/tests/test_core_lineage.py`.
  *Existing artifacts:* sdk-reports and release-manifests from before still validate; an
  sdk-report without `base_commit_sha` is read as having made no commit, so it must name the
  prototype's commit. A prototype-report or sdk-report naming a placeholder commit can no
  longer be released from: re-run develop (and sdk) so they commit.

- **Verification no longer passes on stale or unowned evidence.** An sdk-report or
  prototype-report naming another commit than the one under test is now a required,
  `BLOCKED` `source.upstream-commits` check (was a non-blocking warning), and SDK checks
  built on such an sdk-report are `BLOCKED`. Runtime facts and assertion results left by an
  earlier run are deleted before the commands that write them, an assertion evaluator that
  exits non-zero without a blocking breach is `FAIL`, a Playwright run that exits non-zero
  with a green report is `FAIL`, a recorded scenario citing a screenshot that does not exist
  is not counted, and the Playwright report, assertion results, runtime facts, recorded
  session and screenshots are pinned by sha256 in the evidence.
- **`sdk-report` 1.1.0**, additive: optional `sdk`, per-platform `adapter`, per-feature
  `required_by`/`hooks`/`fallback`, feature status `unsupported`, and an `integration` block
  (files, placements, game hooks, tests). Existing 1.0.0 reports still validate.
- **The workflow's `sdk` step reads `game-design` and `scaffold-record`** as well as
  `prototype-report`: it integrates what the design placed into the repository init made.
  A run whose `sdk` step was already completed is unaffected.
- **`criteria-expression` now states which way `in` and `not_in` read.** Platform profiles use
  `{left: package.locales, op: in, right: [ru]}` to mean "the package ships Russian". Read as
  the conventional "left is a member of right", that assertion passes for a package with no
  locales at all — and locale assertions are blocking on three platforms. The operator
  description now fixes the semantics: an array measurement asks whether every element of
  `right` is present in it; a scalar measurement asks whether it appears in `right`.

  *Migration:* none to the data. Any evaluator written against the old reading must be
  corrected, and its locale results re-checked.

### Notes from implementing the template's pipelines

Findings that belong with the methodology even though the code lives in the sibling repository:

- A **gate needs a mechanism, not a name**. `environment: production` in a workflow is not a
  gate — GitHub creates an unconfigured environment implicitly, with no protection, the first
  time a job names one. G6 and G7 are enforced by *required reviewers* on that environment, and
  the workflows now verify that rather than assume it.
- **Required reviewers are unavailable on private repositories under a free plan.** A private
  game repository on a free organization cannot enforce G6 or G7 through environments at all.
  Worth deciding per title, since `repo_params.visibility` defaults to `private`.
- **Platform profiles must be vendored into the game repository** at the pinned version. A game
  repository has no access to `core/`, and `platform-validation.md` names validating against
  the current profile rather than the pinned one as a failure mode. They go to
  `config/platforms/` as byte-identical copies, so drift is a plain diff.
- **Only Poki has a headless upload path.** Yandex, CrazyGames and GameVui accept a ZIP through
  a console a person logs into. `publish.md` already says no portal APIs are integrated by
  design; this is the same conclusion arrived at from the other direction.

## 2026-09-22 — initial

- `core/`: four lifecycle machines, seven gates as data, thirteen artifact schemas with their
  contracts in `x-wgf`, five platform profiles, twelve role charters, adapter bindings.
- `claude-web-game-plugin/` and `codex-web-game-plugin/`, generated from `gen-adapters.sh`.
- `workspace/`: a complete worked example from a market claim to a kill decision at G4.
- `scripts/check-integrity.py` for referential integrity across machines, schemas, roles and
  bindings.

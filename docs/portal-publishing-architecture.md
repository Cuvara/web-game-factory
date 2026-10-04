# Portal publishing architecture: an agent-owned, Playwright-driven publisher

Status (2026-10-05): **implemented and fixture-validated; no real portal console has been
observed, dry-run, uploaded to or submitted to yet.** Part 0 is the current state and how a
person runs it. Parts 1-4 are the audit and the design of 2026-10-04 that the implementation
followed; where they say "capture", a saved session or "proposed", Part 0 wins.

## Part 0 - as built

### The human handoff model

```
HUMAN LOGIN               the submit step opens the portal's console in a headed browser
                          (fresh, ephemeral context). Not logged in -> WAITING_FOR_HUMAN_LOGIN
                          {portal, step, url (origin+path), reason, action, resume}; the person
                          logs in and handles any CAPTCHA / 2FA / anti-bot check in that
                          window; the step detects the authenticated console and continues.
                          Nothing asks for, types, stores or keeps a password, OTP, cookie or
                          session; the session ends with the window. A timeout or a closed
                          window is AUTH_REQUIRED, a wait - never a failure.
AUTOMATED CONSOLE WORK    find the game (registry id -> game.config id -> idempotency key ->
                          exact title; an unrecorded match is duplicate-candidate, a person
                          links it), read its status (a pending review stops: review-pending,
                          nothing uploads over it, nothing cancels it), create it only when
                          nothing matched, fill listing text and media from the shipped
                          campaign, save. Human fields (terms, declarations, age rating, tax,
                          payout, exclusivity, prerequisites) stop for the person.
HUMAN UPLOAD AUTHORIZATION G6: a person's publish decision pinning the release-manifest, the
                          store listing and its validation by hash; the package must match its
                          checksum and this platform's verified bundle; any hash changed after
                          G6 is g6-stale and G6 is asked again. Plus live mode
                          (factory.publish.mode: live AND WGF_PUBLISH_LIVE=1). Dry run never
                          uploads to a real portal.
AUTOMATED UPLOAD          the package of exactly this platform is uploaded to the draft, the
                          draft saved and read back -> UPLOAD_COMPLETE.
HUMAN SUBMIT/PUBLISH      WAITING_FOR_HUMAN_SUBMIT_CONFIRMATION: `wgf decide <run> submit`
DECISION                  (one review request, profile locator only, status read back),
                          `hold`, `abandon`, or `done` (the person requested it by hand).
                          Publication after moderation (Yandex "Verified" -> Publish,
                          CrazyGames Full Launch) is the person's or the portal's act.
```

The adaptive mode (2.6, off by default) may only re-locate a drifted **reversible** intent
under the executor's checks; irreversible and human intents never adapt.

### The Y8 create-before-build workflow (reusable: `identity.issued_on_create`)

```
1 submit visit (live, G6)  Studio missing -> HUMAN_REQUIRED (a person creates it; name permanent)
2                          login handoff as above; legal steps are the person's
3                          create the game (name only) on the console
4                          read the issued Game ID and App ID (profile identity.issued_on_create)
5                          registry: DRAFT_CREATED with both ids; outcome IDS_ISSUED, nothing uploaded
6                          route platform-ids -> sdk writes them into game.config.yaml
                           (identity.build_config) -> verify -> release: the Y8 package is
                           rebuilt with its ids
7                          platform-validate again: guard platform_ids_present
8                          G5, G6 asked again (the manifest changed); upload -> UPLOAD_COMPLETE
9                          stop before the irreversible request
10                         a person decides submit | hold | abandon | done
```

Any portal whose profile declares `identity.issued_on_create` and `identity.build_config`
takes the same path; GameDistribution's Game ID is entered by a person in game.config today
(its issuance on create is derived, not documented).

### What exists (code)

| Piece | Where |
|---|---|
| Profile-driven intent runner, live login handoff, `actions.jsonl` | `scripts/wgf_publish/browser/console.spec.ts`, `browser.py`, `adapters/console.py` |
| Five first-class portal adapters (own status map, handoffs, refusals) | `scripts/wgf_publish/adapters/{yandex,crazygames,y8,gamedistribution,gamepix}.py`, `portal.py` |
| Publication profiles 2.x (flows as data; documented vs hypothesis; unknowns) | `core/reference/publication/*.yaml`, schema `core/artifacts/shared/publication-profile.schema.json` |
| Submit step: G6/build/campaign integrity, per-platform state, confirmation, create-before-build route, `--platform`, `--track` | `scripts/wgf_publish/step.py`, `identity.py`, `core/workflows/new-game.workflow.yaml` (v10) |
| Portal registry (per title) | `scripts/wgf_publish/registry.py`, `core/artifacts/portal-registry.schema.json`, `workspace/titles/<id>/portals.json` |
| Campaign and media mapping and validation | `scripts/wgf_publish/campaign.py`, `scripts/wgf_listing/validation.py` |
| Bounded adaptive mode, `drift.json`, `drift-review` | `scripts/wgf_publish/adaptive.py` |
| Real-console observer (read-only, human logs in) | `scripts/wgf_publish/observe.py`, `browser/observe.spec.ts`, `wgf-publish.py observe` |
| One build per target platform | `scripts/wgf_verification`, `scripts/wgf_release` (template contract 1, `WGF_GAME_CONFIG`) |
| Fixture portal + one flavor per portal | `scripts/tests/fixtures/publish/portal.py`, `flavors.py` |
| CI never publishes | template `publish.yml` and `make-publication` removed (web-game-template#25); `wgf-org-setup.sh` holds no portal credential |

### Readiness matrix

Vocabulary: IMPLEMENTED (code exists), FIXTURE_VALIDATED (passes against the fixture portal
in real headless Chromium), DRY_RUN_VALIDATED (a dry run against the REAL console reached
its last read-only phase with the profile's locators), REAL_CONSOLE_VERIFIED (a person
logged in and the observed console matches the profile), REAL_UPLOAD_VALIDATED, SUBMITTED, PUBLISHED, UNVERIFIED, HUMAN_ACTION_REQUIRED.
Nothing below is "supported": every real-portal column is UNVERIFIED until a person logs in.

| | Yandex | CrazyGames | Y8 | GameDistribution | GamePix |
|---|---|---|---|---|---|
| build (own bundle) | IMPLEMENTED | IMPLEMENTED | IMPLEMENTED (SDK-less without its ids) | IMPLEMENTED; Game ID: HUMAN_ACTION_REQUIRED | HUMAN_ACTION_REQUIRED (no SDK adapter in the pinned template: template release + pin) |
| adapter | FIXTURE_VALIDATED | FIXTURE_VALIDATED | FIXTURE_VALIDATED | FIXTURE_VALIDATED | FIXTURE_VALIDATED (its BLOCKED path) |
| campaign / media mapping | FIXTURE_VALIDATED (field names UNVERIFIED) | FIXTURE_VALIDATED (field names UNVERIFIED) | FIXTURE_VALIDATED (field names UNVERIFIED) | FIXTURE_VALIDATED (field names UNVERIFIED) | FIXTURE_VALIDATED (field names UNVERIFIED) |
| create-game / Game ID + App ID / rebuild | - | - | FIXTURE_VALIDATED (end to end through the engine; verify and the sdk write are test doubles) | UNVERIFIED | - |
| prerequisites / domain | contract + payout: HUMAN_ACTION_REQUIRED | payout: HUMAN_ACTION_REQUIRED | Studio: HUMAN_ACTION_REQUIRED | no domain needed for an account (documented); self-hosting needs consent + HTTPS host: HUMAN_ACTION_REQUIRED | agreement: HUMAN_ACTION_REQUIRED |
| real console | UNVERIFIED (observer opened 2026-10-04, nobody logged in: LOGIN_TIMEOUT) | UNVERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED |
| dry run on the real console | UNVERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED |
| upload | UNVERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED |
| submit | UNVERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED |
| publish | UNVERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED |
| automation terms | UNVERIFIED (`terms_confirmed` is a person's finding) | UNVERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED |

### How a person runs it, per portal (in this order: Yandex, CrazyGames, Y8, GameDistribution, GamePix)

```bash
# A. observe the real console - you log in; the observer only records (masked, nothing kept)
python scripts/wgf-publish.py observe yandex --checkout ../my-game
python scripts/wgf-publish.py observe-summary <the printed directory>
# B. correct core/reference/publication/yandex.yaml from what was observed (a reviewed commit;
#    only observed or documented facts; unknowns stay listed), bump its version
# C. record the terms finding after reading them: factory.publish.platforms.yandex.terms_confirmed
# D. dry run (default mode): the step opens the console, you log in, it finds the game and
#    reads its status, reports what it would create, fill and upload - and changes nothing
#    on a real portal (actions.jsonl lists every step it took)
bin/wgf publish --run <run-id> --platform yandex
bin/wgf decide <run-id> approve        # G5
bin/wgf decide <run-id> publish        # G6, a person only
# E. upload, only with your explicit authorization: factory.publish.mode: live and
WGF_PUBLISH_LIVE=1 bin/wgf publish --run <run-id> --platform yandex      # -> UPLOAD_COMPLETE
# F. you decide
bin/wgf decide <run-id> submit         # or hold | abandon | done
bin/wgf publish --run <run-id> --track # later: read the portal's status, click nothing
```

---

### Implementation notes recorded while it landed

Landed: workstream 2 (publication profile 2.0.0, `platform-publication` 1.2.0, the flow
rules in `check-integrity.py`; `docs/publish-module.md`, "Publication profiles"). Beyond
the sketch in 2.4: the budget is `adaptive_bounds` beside the `adaptive` switch, the deny
words and dismissable overlays are `submission.deny` and `submission.dismissable`, and an
intent's adaptive vocabulary is its `names`. Landed: workstream 3, the profile-driven
intent runner (`docs/publish-module.md`, "The console executor"), with one decision of
2026-10-04 that supersedes the captured session everywhere below: a person logs in, live, in
the headed browser window the executor opens (credential `human-login`, profile 2.1.0); no
storage state is captured, loaded or saved, `wgf-publish.py capture` is gone, and a live
visit stops `UPLOAD_COMPLETE` - the review request runs only in a later visit a person
confirmed. Where 2.11 and 2.15 below say "capture", read "log in live in the window".
Landed: 2.6, the bounded adaptive mode (`scripts/wgf_publish/adaptive.py`, the executor's
checks in `browser/console.spec.ts`; `docs/publish-module.md`, "Bounded adaptive mode").
As built: off unless `factory.publish.adaptive: true` AND a resolver agent is configured
(`factory.publish.resolver`, `kind: none | command`); the snapshot is the roles, names,
labels and states of the page, without a screenshot; the request and the answer pass
through two files (`drift-request.json`, `drift-response.json`), so the browser process
never runs a model; an intent's optional `page` pattern (profile schema, additive) is the
page check; session, find_game, status_gate and request_review never adapt; an irreversible
intent's drift asks the resolver only for a suggestion, recorded and never acted on; and
`wgf-publish.py drift-review` prints `drift.json` and, with `--apply`, writes a new profile
file for a person to commit - never the shipped one.

---

## The decision this document implements

On 2026-10-04 a person decided:

- CI/CD stops being the mechanism that publishes games to portals. Build and test CI stays.
- The Factory's agent owns the whole publishing workflow: build, QA, per-portal package,
  open the portal, check the session, find or create the game, upload the build, fill the
  metadata, request review, verify the final status.
- Playwright is the portal interaction layer: one adapter per portal behind one interface.
  Targets: CrazyGames, Y8, Yandex Games, GamePix. A new portal is a new adapter, not a
  redesign.
- Nothing bypasses a login, a CAPTCHA, a second factor or an anti-bot check. A person
  authenticates in a browser and the workflow resumes.
- Legal agreements, identity, payment and tax, ownership and licensing declarations, age
  rating and new commercial terms always stop for a person.
- No duplicate games, no duplicate submissions, never cancel a pending review. A submission
  is claimed only when the portal's own UI confirms it.
- Credentials never enter source or logs (the existing captured session and redaction).
- G6 - a person's publish decision pinning the release-manifest by content hash - stays the
  authorization for any public submission. Dry-run and live modes stay.
- **Changed rule:** the agent may inspect the page and adapt when the expected flow differs.
  Before this decision, the submit step acted only through a portal's documented tool or a
  deterministic direct-Playwright run with fixed selectors, "never through an agent
  deciding what to click", and Playwright MCP was not the submission executor. Part 2.6
  says exactly how far adaptation goes; Part 2.13 lists every document and line that
  changes.

The short version of the design: **the deterministic executor stays the only thing that
holds a browser and the only thing that acts. The agent proposes; the executor checks,
acts, and records.** The agent gets a redacted view of the page and a closed vocabulary of
intents. It never gets the session, never chooses an irreversible action, and never decides
that a submission happened.

---

## Part 1 - audit: what exists today

All paths are relative to this repository unless prefixed. **T** is template `main`
(`../web-game-template`, HEAD `8e41b85`). **P** is the pinned template release v1.2.0
(`b106261`, `workspace/config/template.lock.json:5-6`). **G1** is
`wgf-runs/val-2d/games/brick-breaker-worlds` and **G2** is `wgf-runs/val-3d/games/sky-marble`.

### 1.1 CI/CD workflows, and what each responsibility is

The classes are **build**, **test**, **packaging** and **publishing**. "Setup" and "gate"
mark jobs that are none of the four.

**Factory.** One workflow, `.github/workflows/acceptance.yml`. Triggers: push and PR to
`main`, plus dispatch (20-25). Steps: integrity, hashes, ajv compile, adapter regeneration
diff, unit tests, the pinned template with Playwright Chromium (99-112), then
`WGF_GOLDEN=1 bin/wgf test-core --strict` (119). Uploads golden evidence (121-128). No
secrets. **Class: test.** It stays as it is.

**Template (T, `.github/workflows/`). G1 and G2 carry P's copies, byte-identical except
that `bootstrap.yml` has deleted itself.**

| Workflow | Jobs and key steps | Secrets / vars | Class | Verdict |
|---|---|---|---|---|
| `bootstrap.yml` | Grants `WGF_*` org secrets, copies org vars (75-111); creates `develop`, `production`, `campaign-spend` environments (113-144); sets GAME_ID / GAME_NAME | `APP_ID`, `APP_PRIVATE_KEY` (71-72) | setup | Keep; stop creating `production` and stop granting portal secrets |
| `build.yml` | `pnpm build` (56), upload `dist-<channel>-<sha>` (70-74); develop channel deploys a preview with `wrangler pages deploy` (112-119) | `WGF_CF_API_TOKEN`, `WGF_CF_ACCOUNT_ID`, `WGF_CF_PROJECT_PREFIX` | build (+ a preview deploy, not a portal) | Keep |
| `ci.yml` | lint, typecheck, unit, integration, `test:sdk`, `sdk:check` (47-67); `golden` (102-104) | none | test | Keep |
| `verify.yml` | build, `test:e2e`, `test:sdk:browser`, `test:verify`, facts and assertions per platform (68-145); `sdk-matrix` (166-193); poki demo (214-255) | none | test | Keep |
| `release.yml` | ci + verify (42-47); `candidate`: release id (82-84), `pnpm build:platforms` (92), `test:verify` (99), `release:package` (106), facts and assertions (108-115), `make-manifest --state rc` (117-119), `make-publication` (120), upload `release-<rid>` (136-140), `gh release create --draft` (150-160) | `github.token` | build + test + packaging (+ a draft GitHub Release) | Keep build, test and packaging; drop `make-publication` (the Factory's `platform-validate` writes the record) |
| `publish.yml` | `environment: production` (47); confirm == release id (51); required reviewers (68-80); refuses `validation-failed` (110-119); **Poki: `npx @poki/cli upload` (121-148)**; `make-publication --state submitted` (154-161); checklists for every other portal (175-187) | `WGF_POKI_AUTH_JSON` (125), `WGF_POKI_GAME_ID` (126) | **publishing** | **Remove** |
| `campaign.yml` | `environment: campaign-spend`; writes a G7 proposal (102-133) | none | gate (G7), not publishing | Keep |
| `crazygames.yml` | demo lint/test, `build:crazygames-demo`, `test:crazygames`, optional live SDK (108-112), `audit:crazygames` (115) | `CG_LIVE_SDK=1` env | test | Keep |
| `gamevui-demo.yml` | demo test, build, e2e, `audit:build`, `package:gamevui` (61-80) | none | test + packaging (demo) | Keep |
| `yandex-demo.yml` | demo build, audit, e2e, `demo:yandex:package` (77-90) | none | test + packaging (demo) | Keep |
| `live-portal-validation.yml` | dispatch only; `build:platforms`, `release:package`, `test:sdk:live` (39-49); BLOCKED (exit 3) without opt-in | `WGF_LIVE_OPT_IN` (48) | test (live SDK, opt-in) | Keep |

P differs from T in two ways that matter here: P's `release.yml` runs a single `pnpm build`
(88) and P's `package.mjs` zips the same `dist/` into every platform's zip (P
`package.mjs:70,91-114`). With G1 and G2's targets `[poki, crazygames, yandex]`
(`game.config.yaml:34-36`), `crazygames.zip` and `yandex.zip` would boot the Poki adapter
(P `src/main.ts:31`, `src/core/config.ts:15-19`). The Factory masks this today by packaging
the required platform only (`wgf_release/step.py:412` `_prune`). T fixes it with
`pnpm build:platforms` (one `vite build` per target, `WGF_TARGET_PLATFORM`, `build.json`
schema `wgf-platform-build/1` with `dist_digest`, `commit_sha`, `portal_configured`;
`scripts/build/build-platforms.mjs:82-126`), and T's `release:package` refuses a missing,
stale, unconfigured or digest-mismatched build (`package.mjs:208-254`). T is not yet a
release.

**The only automated portal publication in any repository is the Poki CLI upload in
`publish.yml`.** Every other portal is a checklist in the run summary. Nothing uses butler,
gh-pages or a portal HTTP API.

### 1.2 Build, package and record scripts (template)

| Script | Produces | Notes |
|---|---|---|
| `build` | `dist/` | P: one bundle, adapter chosen at runtime from the first required entry |
| `build:platforms` (T only) | `build/platforms/<id>/{dist,build.json}`, `build/platforms/index.json` | Build-time adapter selection (`scripts/build/game-config-plugin.ts:57-123`); a required portal ID missing fails unless `WGF_ALLOW_UNCONFIGURED_PORTAL=1` (`src/core/game-config.ts:351-382`) |
| `release:package` | `release/<rid>/{<platform>.zip, packages.json, checksums.txt}` | Deterministic zips, `index.html` at the root, no `.map`; `max_bundle_mb`; Yandex name and size rules (T `package.mjs:276-292`) |
| `release:manifest` | `release/<rid>/manifest.json` | Immutable once `--state rc` (`make-manifest.mjs:166-167,222-240`) |
| `publish:prepare` | `release/<rid>/publications/<platform>.json` | `scripts/publish/make-publication.mjs`; state from assertions (123-134), `--state submitted` refused after validation failure (145-153), a checklist from the profile (182-188) |
| `facts` / `assert` | `build/facts`, `build/assertions/<id>.json` | Feed the Factory's `assertions_pass` guard |
| `demo:yandex:package` | `build/yandex/*.zip` | Demo only |

SDK selection: adapters in `packages/platform-sdk/src/adapters/` (generic-web, yandex, poki,
crazygames, gamevui, y8, gamedistribution, gamemonetize; **gamepix on T only**). Portal IDs
come from `game.config.yaml` entries (`game_id`, `app_id`) or `WGF_Y8_APP_ID`,
`WGF_Y8_GAME_ID`, `WGF_GAMEMONETIZE_GAME_ID` at build time (T `game-config.ts:294-314`).

Playwright in the template is test only: `playwright.config.ts` (e2e and `tests/verify`
facts with portal SDK requests blocked), the SDK smoke and matrix configs, the Poki and
CrazyGames demo configs, and `tests/live/live.config.ts` (`WGF_LIVE=1`, else exit 3). The
static audits (`crazygames-audit.mjs`, `verify/poki-audit.mjs`, `verify/yandex-audit.mjs`)
are file-based.

### 1.3 Secrets and environment

`scripts/wgf-org-setup.sh` creates, as `__UNSET__`: secrets `WGF_CF_API_TOKEN` (66),
`WGF_POKI_AUTH_JSON` (67), `WGF_YANDEX_CONSOLE_SESSION` (68, reserved),
`WGF_CRAZYGAMES_TOKEN` (69, reserved), `WGF_GAMEVUI_TOKEN` (70, reserved); variables
`WGF_CF_ACCOUNT_ID`, `WGF_CF_PROJECT_PREFIX`, `WGF_YANDEX_APP_ID`, `WGF_POKI_GAME_ID`,
`WGF_CRAZYGAMES_GAME_ID`, `WGF_GAMEVUI_GAME_ID` (80-85). Drift: `WGF_LIVE_OPT_IN` is used but
not inventoried; `WGF_Y8_APP_ID` / `WGF_Y8_GAME_ID` / `WGF_GAMEMONETIZE_GAME_ID` are read at
build time but are not org variables; `WGF_YANDEX_APP_ID`, `WGF_CRAZYGAMES_GAME_ID`,
`WGF_GAMEVUI_GAME_ID` are read by nothing.

Factory side (`docs/env-vars.md`): `WGF_PUBLISH_LIVE` (24), `WGF_PUBLISH_<PLATFORM>_STORAGE_STATE`
(25), `WGF_PUBLISH_BROWSER_TEST` (77). The portal session is a Playwright storage state on
the operator's machine, named by the variable and allowlisted in
`factory.publish.env_passthrough`. It is not an org secret and never reaches CI.

### 1.4 The Factory's publish module

The `publish` group (`core/workflows/new-game.workflow.yaml:89`): `platform-validate`
(456-460), `release-review` G5 (465-475), `publish-review` G6 (481-491), `submit` (504-510,
`retry: {max_attempts: 1}`, `max_visits: 3`). `docs/publish-module.md` describes it.

| Capability | State | Evidence |
|---|---|---|
| Publication guards and readiness (READY / BLOCKED / HUMAN_REQUIRED / UNKNOWN) | Exists | `scripts/wgf_publish/validate.py:103-200`; `wgflib/publication.py` |
| G6 checked four ways before anything is contacted (passed, is G6, approved by a human, pins this manifest hash) | Exists | `step.py:207-235` |
| Idempotent re-entry (already SUBMITTED/VERIFIED returns as is) | Exists | `step.py:93-101` |
| Package re-hashed against the manifest | Exists | `step.py:127-137` |
| Captured session: a person logs in once (`wgf-publish.py capture`), private 0600 copy per run, every cookie value registered for redaction, zeroed and deleted | Exists | `scripts/wgf-publish.py:60-112`; `session.py:70-131` |
| Redaction of every event, evidence field and record | Exists | `wgflib/redact.py`; `evidence.py:44-51`; `common.py:176` |
| Dry-run default, live needs `mode: live` **and** `WGF_PUBLISH_LIVE=1` | Exists | `common.py:67-78`; `workspace/config/factory.yaml:178` |
| Adapter interface `Job` -> `publish(job)` -> `Publication`, one outcome vocabulary | Exists | `adapters/base.py:17-90`; `outcomes.py` |
| Deterministic console executor: authenticate, find_existing, upload, configure, submit (once, live only), verify; foreign origins aborted | Exists | `browser.py:65-111`; `browser/console.spec.ts:122-271` |
| WAITING_FOR_HUMAN on login, CAPTCHA, 2FA, unconfirmed terms, missing session, ambiguous state | Exists | `console.py:31-33,180-229`; `publication.py:326-340` |
| Idempotency key `wgf-<pid>-<16 hex>` written into the draft name, looked up before upload | Exists | `publication.py:357-362`; `console.spec.ts:151-180` |
| Status read-back mapped through the profile's status words; SUBMITTED needs the portal's text | Exists, once per run | `console.py:194-242` |
| Fixture portal (login, console, new, upload, draft, save, submit, `/state.json`; modes captcha, two-factor, expired, upload-fail, ambiguous, slow-upload; second submit 409) | Exists | `scripts/tests/fixtures/publish/portal.py:7-31` |
| Tests: fake console + real Chromium against the fixture (`WGF_PUBLISH_BROWSER_TEST=1`) | Exists | `scripts/tests/test_publish_module.py` (1031 lines) |
| Selector maps | Hypotheses for CrazyGames and Yandex only, never run against the real site | `adapters/crazygames.py`, `adapters/yandex.py` |
| Y8, GameDistribution, GameMonetize | Console profiles, no adapter: ManualAdapter, HUMAN_REQUIRED | `adapters/__init__.py:24-41` |
| GamePix | No publication profile, no platform profile, no adapter at the pinned template | `docs/platform-targets-2026-10.md:170-183` |
| Reachability of any live portal | None: every console profile is `automation_terms: unverified`, so the step stops HUMAN_REQUIRED first | `publication.py:330-340`; test `:381` |

**Defects and gaps found while auditing (not fixed here):**

1. **The description is never filled.** `ConsoleAdapter.metadata_fields` is
   `("title", "description")` (`adapters/console.py:42`) and `metadata()` reads
   `job.metadata.get(field)` (`:95-103`), but the store metadata the release writes uses
   `descriptions` keyed by locale (`wgf_release/step.py:596-604`;
   `release-manifest.schema.json:110`). The `description` key never exists. *Fixed by
   workstream 1 (Part 4).*
2. **Only title and description are mapped.** Icon, cover, screenshots, video, categories,
   tags, controls, how-to-play and per-locale fields from the store listing are not
   uploaded or filled. *The text fields - title, short and long description per locale,
   controls, tags, categories - are filled since workstream 1; media and how-to-play remain
   (workstream 5, and profile 2.0.0's `fields`).*
3. **Existing-game detection matches only the idempotency key** in a draft name
   (`console.spec.ts:151-169`). A game made by hand, or a new version of a live game, is not
   found: the executor would create a duplicate.
4. **The draft is named with the idempotency key, not the title** (`console.spec.ts:180`).
5. **Profile constraints are declared but read by no code**: `postpone_publication`,
   `one_moderation_at_a_time`, `replaces_index_html` (zero hits in `scripts/`).
6. **No pending-review check**: nothing reads the game's current status before uploading,
   so a new build could replace one under moderation.
7. **One platform per `submit`**: the step loads a single `platform-publication`
   (`step.py:75-77`). With one package per release this has not mattered.
8. **No later status read-back**: in-review -> live is transcribed by a person
   (`platform-publication.machine.yaml:10-11`).
9. **One build per release** on contract 1 (Part 1.1): a multi-portal release is not
   packageable until a template release carrying `build:platforms` is pinned.
10. **The release machine and the workflow disagree on order**: the machine puts G6 before
    `validating` (`release.machine.yaml:118-122`); the workflow validates before G5 and G6.
11. **The plugin surfaces cannot run it**: `/wgf-publish` is a generic transition command
    that names no `wgf_publish` path (`claude-web-game-plugin/commands/wgf-publish.md`), and
    the release agent is limited to localhost browsing (`agents/release.md:37`,
    `core/craft/tool-capabilities.md:46-49`).

### 1.5 Where the old rule is written

| File:line | Text |
|---|---|
| `CLAUDE.md:425-429` | "a deterministic direct-Playwright run of its console where none does ... Playwright MCP is not the submission executor" |
| `CLAUDE.md:492-496` | "only through its documented tool or its own console - never through an agent deciding what to click" |
| `docs/publish-module.md:173-200` | "The console executor: direct Playwright, not Playwright MCP"; "The spec decides nothing - no model, no heuristics"; "Its strength - an agent re-reasoning under UI drift - is the property the Factory refuses on an irreversible action" |
| `docs/production-craft-and-mcp.md:69` | release:submitting row: "Playwright MCP is not the portal submission executor" |
| `docs/platform-architecture.md:315,325-326` | the same rule |
| `core/lifecycle/stages/publish.md:27,35` | "AI prepares. Deterministic automation executes. A person authorizes."; "direct Playwright, fixed selectors, one submit click" |
| `scripts/wgf_publish/__init__.py:16-19`, `browser.py:12-13`, `browser/console.spec.ts:3` | docstrings: "never an agent", "No model decides anything here" |
| `CHANGELOG.md:39-40` | the 2.7.0 entry (history: left as written) |
| `claude-web-game-plugin/runtime/...` | generated copies; rebuilt, never edited |

---

## Part 2 - design

### 2.1 Principles

1. **One actor holds the browser.** The executor (direct Playwright under `wgflib.procs`,
   as today) opens the portal with the captured session, performs every action and reads
   every result. Nothing else touches the page.
2. **The flow is data; drift is the exception.** Each portal's flow is a list of named
   intents in its publication profile. The executor runs it deterministically. Adaptation
   happens only when a step of that flow fails its own check.
3. **The agent proposes, the executor disposes.** On drift, the agent sees a redacted
   accessibility snapshot and returns a locator for the same intent. The executor checks
   the proposal against fixed rules, acts, checks the post-condition, and records the
   proposal, the check and the result.
4. **Irreversible and human-only intents never adapt.** Request review, publish, delete,
   cancel or withdraw, accept terms, declarations, age rating, pricing and payment are
   never resolved by the agent. A drifted irreversible intent stops for a person.
5. **Only the portal says a thing happened.** SUBMITTED needs the portal's status text,
   read after the action and mapped through the profile. A click that returned is not an
   outcome (unchanged from today).
6. **Fail closed, stop for a person, never retry an irreversible action.** Unchanged.

### 2.2 The target flow

```
develop ... verify, playability, production-quality, visual-qa       (unchanged)
G4 pass -> store-listing -> listing-validation -> release             (per-portal packages)
      │
      │  wgf publish --run <run-id> [--platform P ...]
      ▼
platform-validate      guards per packaged platform + the new pre-upload checks (2.9)
      ▼
release-review   [G5]  reversible
      ▼
publish-review   [G6]  IRREVERSIBLE, a person; pins the release-manifest hash
      ▼
submit (one visit per platform; the PortalPublisher)
   1 open         the console url with the captured session; only allowed origins
   2 session      logged in | login | CAPTCHA | 2FA | anti-bot -> AUTH/CAPTCHA (WAITING)
   3 find_game    recorded portal id -> config id -> idempotency key -> exact title search
                  0 match: create allowed; 1 recorded match: use; any unrecorded match: STOP
   4 status_gate  read the game's current status: under review / moderation -> STOP
                  (never cancel a pending review, never upload over it)
   5 create_game  only when find_game found nothing; name = title, key in a private field
                  or recorded right after creation
   6 upload       the one package for this platform, its sha256 checked again
   7 metadata     listing fields per locale, from the shipped store listing only
   8 media        icon, cover, screenshots, video from the shipped listing only
   9 human_fields declarations, age rating, terms, payment, categories the profile marks
                  human -> STOP with the exact list and url; a person fills them; resume
  10 save_draft   save; read back that the draft holds the build and the fields
  11 request      live mode only: one click on the review / publish request, once
     _review
  12 verify       read the portal's status text; map it through the profile
      ▼
platform-publication   SUBMITTED / VERIFIED only from the text read in 12;
                       DRY_RUN after 10 in dry-run mode
      ▼
track (new, read-only, optional)   later visits read the status again: in-review -> live
                                   or rejected; never act
```

Steps 1-10 run in dry-run too. Dry-run therefore exercises the whole flow except the one
irreversible click, which is how a new adapter is proven before the profile goes
`verified`.

### 2.3 The PortalPublisher interface

The existing `PublicationAdapter` (`adapters/base.py`) grows into a phase interface. The
step keeps owning G6, idempotency, the package check, the session and the record. The
adapter owns how one portal is driven. Python signatures (the executor side is TypeScript,
the same flow file as today):

```python
class PortalPublisher(PublicationAdapter):
    method = "console"

    # data, from core/reference/publication/<id>.yaml (2.4); no selector lives in code
    def flow(self) -> list[Intent]: ...
    def field_map(self, listing, locale) -> dict[str, FieldValue]: ...

    # the phases; each returns a PhaseResult(observed, evidence, outcome or None)
    def check_session(self, page) -> PhaseResult            # logged-in | login | captcha | 2fa | antibot
    def find_game(self, page, ident: GameIdentity) -> GameMatch
    def read_status(self, page, game) -> PortalStatus       # the portal's words, mapped
    def create_game(self, page, ident) -> PhaseResult       # never when find_game matched
    def upload_build(self, page, game, package) -> PhaseResult
    def fill_metadata(self, page, game, fields) -> PhaseResult
    def upload_media(self, page, game, media) -> PhaseResult
    def human_fields(self, page, game) -> list[HumanField]  # what a person must still do
    def save_draft(self, page, game) -> PhaseResult
    def request_review(self, page, game) -> PhaseResult     # IRREVERSIBLE: live, once, never adaptive
```

The default implementation of every phase is generic: run the profile's intents for that
phase through the executor. A portal subclass overrides a phase only for behaviour data
cannot describe (Yandex's per-language tabs, for example). `ManualAdapter` stays for `email`
and `manual`. An `api`/`cli` adapter (Poki's CLI today) implements the same phases with a
documented tool instead of a page.

`GameIdentity` is everything that can name the game on the portal: the portal game id
recorded by an earlier publication of this title (new: a per-title registry, 2.5), the id in
`game.config.yaml` (`game_id`, `app_id`), the idempotency key, and the exact title.

### 2.4 The per-portal adapter contract: publication profile 2.0.0

Portal facts are data in `core/reference/publication/<id>.yaml`
(`core/artifacts/shared/publication-profile.schema.json`), versioned and pinned by the
record, as today. Profile 2.0.0 adds:

```yaml
submission:
  method: console
  automation_terms: unverified          # permitted | prohibited | unverified (unchanged)
  adaptive: allowed                      # allowed | forbidden: may the agent resolve drift here
  content_policy:
    ai_generated_text: unknown           # allowed | disclose | forbidden | unknown
    ai_generated_assets: unknown
  session:
    logged_in: [{role: navigation, name: "Games"}]       # intent locators (2.6)
    login: [{role: textbox, name: "Password"}]
    captcha: [{css: "iframe[src*='captcha']"}]
    two_factor: [{label: "Code"}]
  identity:
    portal_id_from: [registry, config:game_id, config:app_id]
    list_url: https://.../games
    row: [{role: row}]
    row_title: [{role: cell, index: 0}]
  flow:                                  # ordered intents; each has a phase and a class
    - id: create.open
      phase: create_game
      class: reversible                  # reversible | irreversible | human
      action: click                      # click | fill | select | upload | navigate | read
      target: [{role: button, name: "Add game"}, {text: "New game"}]
      expect: {url_matches: "/games/new"}
    - id: field.title
      phase: fill_metadata
      class: reversible
      action: fill
      value: listing.title               # a path into the shipped listing, never free text
      target: [{label: "Title"}, {placeholder: "Game title"}]
      expect: {value_equals: listing.title}
    - id: declare.age_rating
      phase: human_fields
      class: human
      note: "Age rating questionnaire"
    - id: review.request
      phase: request_review
      class: irreversible
      action: click
      target: [{role: button, name: "Submit for review"}]
      expect: {status_in: submitted_states}
  status:
    read: [{label: "Status"}, {testid: review-status}]
    states: [Draft, In review, Published, Rejected]
    submitted_states: [In review]
    live_states: [Published]
    rejected_states: [Rejected]
    pending_states: [In review]          # status_gate stops on these
  constraints:
    one_moderation_at_a_time: true
    postpone_publication: true
    replaces_index_html: true
    archive_root_index: true
    upload_max_mb: 250
  fields:                                # what the console asks, for listing validation
    title: {max: 50, locales: per-locale}
    description: {max: 2000, locales: per-locale}
    how_to_play: {min: 100, max: 1000}
  restrictions: [...]                    # known portal rules, cited
  sources: [{url: ..., read: 2026-10-04}]
```

Every `flow` intent is one row a test can name and a person can review. A profile with no
`flow` for a phase means the phase is done by a person (HUMAN_REQUIRED with its list).

**Failure and recovery classes.** Every adapter maps what it sees into one of six classes,
and each class has exactly one response:

| Class | Examples | Outcome | Response |
|---|---|---|---|
| recoverable UI | a locator matched nothing; a post-condition not met on a reversible intent; a dialog in the way | (internal) | Bounded adaptation (2.6) on reversible intents; otherwise `UNKNOWN` |
| build | package hash changed; size over limit; no `index.html` at root; wrong SDK in the bundle | `INVALID_BUILD` | FAILED, not retryable; back to `release` |
| portal | upload refused; portal error page; rejected by moderation | `PLATFORM_ERROR`, `REJECTED` | FAILED; record kept; rejection writes a compliance finding (unchanged) |
| auth | login form, expired session, CAPTCHA, 2FA, anti-bot interstitial | `AUTH_REQUIRED`, `CAPTCHA_REQUIRED`, `HUMAN_REQUIRED` | WAITING_FOR_HUMAN; a person logs in (2.11); `wgf resume` |
| legal | terms, declarations, age rating, tax, payment, identity, commercial terms, an AI-text policy that forbids generated text | `HUMAN_REQUIRED` (reason `legal`, `declaration`, `ai-text-policy`) | WAITING_FOR_HUMAN with the list and the url; a person acts in their own browser; resume |
| unknown destructive | a status the profile does not map after an action; a confirm dialog the flow does not name; a duplicate candidate; a pending review | `UNKNOWN` (reason `ambiguous-portal-state`, `duplicate-candidate`, `review-pending`) | WAITING_FOR_HUMAN; nothing retries; a person looks |

New `human_required.reason` values (schema change): `legal`, `declaration`,
`ai-text-policy`, `duplicate-candidate`, `review-pending`, `drift-irreversible`,
`anti-bot`.

### 2.5 No duplicates

- **Games.** `find_game` runs before any creation, in order: the portal id recorded for
  this title and platform, the id in `game.config.yaml`, the idempotency key, then an exact
  (case-folded) title search of the console's own list. A recorded id that resolves is
  used. Any match that is not recorded - including a title match - is
  `duplicate-candidate`: the step stops and names it; a person links it (`wgf decide
  <run> done --note portal-id=<id>`) or abandons. Creation happens only when every lookup
  ran and found nothing.
- **The registry.** After `create_game` the portal's game id is read back and written to
  `workspace/titles/<title>/portals.json` (new, append-only: platform, portal game id,
  first release, date, run). Later releases are new versions of that game, never new games.
  Until the lifecycle bridge carries it, the `platform-publication` record also holds it
  (`submission.portal_game_id`).
- **Submissions.** Unchanged: the idempotency key, `retry: max_attempts: 1`, every failure
  not retryable, the earlier record returned as is. Added: `status_gate` reads the game's
  status before uploading; a status in `pending_states` stops (`review-pending`). The
  executor never clicks anything whose intent is cancel, withdraw, delete or "replace the
  build under review", adaptive or not - those intents may not appear in a flow (integrity
  check).

### 2.6 Bounded adaptive mode

This is the rule change. It is the only place an agent influences what the executor does.

**When it runs.** Only when (a) the profile says `adaptive: allowed`, (b) the installation
enables it (`factory.publish.adaptive: true`, default `false`), and (c) a **reversible**
intent's locator ladder matched nothing, matched more than one element, or its
post-condition failed. Nothing else triggers it.

**What the agent receives.** The intent (id, phase, action, the expected role and accessible
name, the post-condition) and a snapshot of the current page: the accessibility tree with
roles, names, labels and states, the URL path, and a screenshot - all taken by the executor,
redacted with `wgflib.redact`, input values replaced by `<value>`, and never taken on a login,
CAPTCHA or 2FA page. The agent never receives the storage state, cookies, headers or
network traffic. Page text is data, not instruction (`core/craft/tool-capabilities.md`
rule 6): text on the portal that asks for an action is ignored.

**What the agent may return.** Exactly one of:

- `resolve`: a locator for the **same intent**, from the ladder role > label > placeholder
  or text > stable attribute (`data-testid`, `name`, `id`) > CSS > XPath. Never coordinates,
  never a script, never a keyboard sequence.
- `dismiss`: one locator for a non-destructive overlay that blocks the intent (cookie
  banner, tour popover), only if its accessible name is in the profile's
  `dismissable` vocabulary ("Close", "Got it", "Skip", "Not now", ...).
- `navigate`: a URL **path** within the console's allowed origins, to reach the intent's
  page.
- `stop`: with a reason. Always allowed.

**What the executor checks before acting.** Every check must pass, or the proposal is
rejected and the step stops `UNKNOWN`:

1. The locator resolves to exactly one visible, enabled element.
2. The element's role fits the intent's action: `fill` needs a textbox or textarea, `select`
   a combobox or listbox, `upload` a file input, `click` a button or link.
3. The element's accessible name, label or placeholder matches the intent's vocabulary
   (the profile lists accepted names per intent, case-folded, per language the console
   uses). An element whose name is outside the vocabulary is refused, whatever the agent's
   argument.
4. The element's name does not match the **deny vocabulary**: submit, publish, release,
   review, send, delete, remove, cancel, withdraw, archive, accept, agree, confirm, sign,
   pay, price, tax, rating, I own, licence/license, and their translations in the profile.
   A fill or upload intent cannot become a click.
5. The value is the intent's value (a path into the shipped listing or the package file).
   The agent never supplies a value.
6. The page origin is allowed. A `navigate` stays inside allowed origins.
7. The budget holds: at most 3 adaptive resolutions per intent and 10 per visit
   (configurable down, not up).

**After acting.** The intent's post-condition is checked exactly as for a profile locator
(value read back, URL matched, element visible). A failed post-condition is not retried
adaptively a second time for that resolution.

**Never adaptive.** `irreversible` and `human` intents. If `review.request`'s ladder does
not match, the step stops `drift-irreversible` with the agent's proposal attached as a
suggestion, a screenshot and the url; a person confirms the locator by correcting the
profile (a version bump, reviewed) and resumes, or submits by hand and records `done`. The
irreversible click is always a profile locator, never an agent's.

**What is recorded.** Every action, adaptive or not, is one line in
`<run>/submit/<visit>/actions.jsonl`: intent id, phase, class, locator used, its source
(`profile` | `adaptive`), the element's role and name, value hash (never the value for a
field that is not listing copy), pre- and post-screenshot paths and hashes, the
post-condition and its result, timestamp. An adaptive line also carries the snapshot hash,
the agent's proposal and the check results. The `platform-publication` record cites the
file by hash and sets `measurement_class: automation-console-adaptive` when any adaptive
action ran. Each visit also writes `drift.json`: the intents that drifted and the locators
that worked - a proposed profile patch a person reviews and commits as a new profile
version. Drift is fixed in data, once, not re-reasoned every run.

**Who the agent is.** The `release` role, run through the Factory's agent runner (the same
host process control as `develop` and `review`: `wgflib.procs`, its own session, timeout,
environment allowlist without `factory.publish.env_passthrough`). It is called with one
drift case at a time and a JSON schema for the answer. Playwright MCP is **not** given to it
for portals: an MCP browser would be a second actor with its own session and arbitrary
clicks, which defeats the checks above. Playwright MCP stays localhost QA and diagnosis.

### 2.7 Locator policy

For profile locators and adaptive proposals alike, in order of preference:

1. `getByRole(role, {name})` - the accessible role and name;
2. `getByLabel` - the form label;
3. `getByPlaceholder`, then `getByText` (exact);
4. a stable attribute: `data-testid`, `name`, `id` (not generated ids);
5. CSS;
6. XPath, only with a recorded reason.

Never coordinates, never image matching, never `nth()` without a container the ladder
already pinned. A profile intent lists a ladder of two or more; the executor uses the first
that resolves to exactly one element and records which.

### 2.8 Deterministic build selection

The package uploaded to portal P is selected, never searched for:

1. The release-manifest pinned by G6 names one package per platform (`packages[]`:
   `platform_id`, `filename`, `checksum`, `content_digest`).
2. The package carries build metadata - from T's `build/platforms/<id>/build.json`
   (`wgf-platform-build/1`): game id, version, target platform, build timestamp, commit
   sha, `dist_digest`, `portal_configured`, and the game config digest. The release step
   copies it into the manifest's package entry (new fields) and into the zip as
   `wgf-build.json`.
3. `submit` refuses (`INVALID_BUILD`) unless: the file's sha256 equals the manifest's (as
   today); the build metadata's platform equals P; its commit equals the manifest's
   commit; `portal_configured` is true; and the `<P>_sdk_present` assertion passed on
   this commit. A Poki bundle offered to CrazyGames is refused.

This depends on pinning a template release that carries contract 2 (`build:platforms`); on
contract 1 the Factory keeps packaging the required platform only (Part 1, gap 9).

### 2.9 Pre-upload validation

| Check | Where it is today | Gap |
|---|---|---|
| Build, unit, e2e, SDK facts and assertions per platform | `verify` (`docs/verification-module.md`) | judge every per-platform bundle, not one (contract 2) |
| Playable, assets present and visible, visual quality | `playability`, `production-quality`, `visual-qa` | - |
| Listing captured from the verified build, per-platform rendition, requirements (UNKNOWN named) | `store-listing`, `listing-validation` | profile 2.0.0 `fields` limits checked too |
| `candidate_frozen`, `store_metadata_complete`, `package_shaped_to_profile`, `assertions_pass`, `metadata_and_locales_present` | `platform-validate` (`validate.py:103-111`) | - |
| Package targets this platform (build metadata, SDK present, portal ids configured) | none | **new guard `package_targets_platform`** |
| Archive shape: `index.html` at root, size under the console's upload limit, relative paths | template `release:package` for Yandex only | **new guard `archive_shaped_to_console`** from profile `constraints` |
| Copy allowed under the portal's AI-text policy | none | **new guard `copy_policy`**: `forbidden` or `unknown` with generated copy -> HUMAN_REQUIRED `ai-text-policy` |
| Declarations a person must make are known | none | readiness lists the profile's `human` intents in the record, so G6 sees them |
| No pending review on the portal | none (portal state) | `status_gate` in `submit` (2.2 step 4) |
| No duplicate game | idempotency key only | `find_game` (2.5) |

### 2.10 Metadata rules

- Every field value is a path into the shipped store listing (`release/<id>/listing/`,
  grounded in the design by `store-listing`) or the manifest. The executor never invents
  text, the agent never supplies a value, and no field is filled with a placeholder.
- Per-locale fields fill per locale from the listing's `text.<locale>`. A locale the portal
  asks for and the listing lacks is a listing-validation failure before G6, not a blank
  field.
- **AI-generated text.** If the profile says `ai_generated_text: forbidden`, or `unknown`
  while the listing copy is generated, the step stops (`ai-text-policy`) and a person
  writes or approves the copy; their text is recorded with `provenance` of a human author.
  `disclose` fills the portal's disclosure field only from a person's recorded statement.
- **Declarations are never fabricated and never automated**: ownership, licensing,
  third-party content, AI use, age rating, target audience, data collection, monetization
  and pricing, tax, payout, identity, legal agreements. They are `human` intents: the step
  stops with the list, a person fills them in their own browser session, and `wgf resume`
  reads the result back. An unchecked declaration checkbox found by the executor is never
  ticked.

### 2.11 Credentials and authentication

Superseded on 2026-10-04 by the live login handoff (`docs/publish-module.md`,
"Authentication and secrets"): no session is captured; a person logs in in the window the
executor opens, and the executor waits (WAITING_FOR_HUMAN_LOGIN). The design as written:

- A person captures the session (`python scripts/wgf-publish.py capture <platform> --out
  <path> --checkout <game>`), kept where the installation keeps secrets, named by
  `WGF_PUBLISH_<PLATFORM>_STORAGE_STATE`, allowlisted in `factory.publish.env_passthrough`
  only - never in the agent allowlist, never in a game build.
- The executor writes a private 0600 copy per visit, registers every value with
  `wgflib.redact`, and destroys it after.
- A login form, CAPTCHA, 2FA or anti-bot page stops the step. No screenshot or snapshot is
  taken there. The person runs `capture` again (headed), then `wgf resume <run>`.
- Org secrets for portals (`WGF_POKI_AUTH_JSON` and the reserved `WGF_*_TOKEN` /
  `WGF_YANDEX_CONSOLE_SESSION`) leave `wgf-org-setup.sh`: no portal credential lives in CI.

### 2.12 Evidence

Per visit, under the run directory: `actions.jsonl` (2.6), screenshots before and after each
action on console pages (PNG, hashed), redacted accessibility snapshots for adaptive cases,
`drift.json`, the upload response status (code only), the status text read back. Playwright
traces and video stay **off**: a trace carries cookies and request headers and cannot be
redacted reliably. The `platform-publication` record cites each file by run-relative path
and sha256, and states `measurement_class`. `external_approval` stays `not-claimed`: a later
`track` visit may read the portal's status, but a moderation verdict is recorded from the
portal's text, never inferred.

### 2.13 Rule and documentation changes

| File | Change |
|---|---|
| `CLAUDE.md:425-429` (key documentation, publish-module entry) | Replace "a deterministic direct-Playwright run ... Playwright MCP is not the submission executor" with: the portal's documented tool, else the publication profile's flow run by the direct-Playwright executor with bounded adaptation (`docs/portal-publishing-architecture.md`) |
| `CLAUDE.md:492-496` (Safety) | Replace "never through an agent deciding what to click" with: "an agent may resolve a drifted reversible step under the checks of the bounded adaptive mode; it never chooses an irreversible action, never acts outside the profile's intents, and never passes a login, CAPTCHA, second factor or anti-bot check" |
| `docs/publish-module.md:173-200` | Rewrite the console executor section: executor plus bounded adaptation; keep "Playwright MCP is not the submission executor" (still true: the agent proposes, the executor acts) |
| `core/lifecycle/stages/publish.md:27-40` | "AI prepares. Deterministic automation executes, an agent resolves bounded drift. A person authorizes and makes every declaration." |
| `docs/production-craft-and-mcp.md:69` | release:submitting row: the agent's role is drift resolution through the executor |
| `docs/platform-architecture.md:315-326` | as publish-module |
| `core/craft/tool-capabilities.md` rule 2 and 5 | Add: the release role's drift resolution sees portal pages through the executor's redacted snapshots only, behind G6 |
| `claude-web-game-plugin/agents/release.md:37` (generated) | via `gen-adapters.sh` and `adapter-binding.yaml`: the release agent may answer drift cases; still no direct browsing of portals |
| `docs/env-vars.md`, `scripts/wgf-org-setup.sh` | Remove portal org secrets; document `factory.publish.adaptive` |
| `scripts/wgf_publish/__init__.py`, `browser.py`, `console.spec.ts` docstrings | Update with the code |
| `docs/platform-targets-2026-10.md` | Point to this document for the console flows |

### 2.14 CI/CD migration

Publishing leaves CI entirely. Template changes are a template PR and a new template release
the Factory pins (they are not Factory changes):

| Repository | Remove | Keep |
|---|---|---|
| template `publish.yml` | **The whole workflow** (Poki CLI upload, `make-publication --state submitted`, checklists) | - |
| template `release.yml` | `make-publication` (120); the `production` environment dependency | ci, verify, `build:platforms`, `test:verify`, `release:package`, facts/assertions, `make-manifest --state rc`, artifact upload, draft GitHub Release (an internal record, not a portal) |
| template `bootstrap.yml` | creating the `production` environment; granting portal secrets | everything else |
| template `scripts/publish/make-publication.mjs`, `publish:prepare` | deprecate (the Factory's `platform-validate` and `submit` own `platform-publication`) | - |
| template `build.yml`, `ci.yml`, `verify.yml`, demo workflows, `live-portal-validation.yml`, `campaign.yml` | - | all (build, test, preview, G7 proposal) |
| Factory `acceptance.yml` | - | all |
| Factory `scripts/wgf-org-setup.sh` | `WGF_POKI_AUTH_JSON`, `WGF_YANDEX_CONSOLE_SESSION`, `WGF_CRAZYGAMES_TOKEN`, `WGF_GAMEVUI_TOKEN`; `WGF_POKI_GAME_ID`, `WGF_CRAZYGAMES_GAME_ID`, `WGF_GAMEVUI_GAME_ID`, `WGF_YANDEX_APP_ID` (read by nothing) | `WGF_CF_*`; add `WGF_Y8_APP_ID`, `WGF_Y8_GAME_ID`, `WGF_GAMEMONETIZE_GAME_ID`, `WGF_LIVE_OPT_IN` (read by builds and tests) |

Existing game repositories (G1, G2) keep their copies until they take a template update; a
`publish.yml` left in a game repo is harmless without its secret, and the Factory never
dispatches it.

### 2.15 How a person runs it

```bash
# once per portal account, and whenever the session expires (headed; a person logs in)
python scripts/wgf-publish.py capture crazygames --out ~/secrets/cg.json --checkout ../my-game
export WGF_PUBLISH_CRAZYGAMES_STORAGE_STATE=~/secrets/cg.json
# factory.publish.env_passthrough: [WGF_PUBLISH_CRAZYGAMES_STORAGE_STATE]
# factory.publish.platforms.crazygames.terms_confirmed: true   (after reading the terms)

bin/wgf publish --run <run-id>                    # platform-validate, G5 waits
bin/wgf decide <run-id> approve                   # G5
bin/wgf decide <run-id> publish                   # G6, a person only; pins the manifest
bin/wgf status <run-id>                           # DRY_RUN: the draft is complete, nothing submitted
# read the draft in the portal; when it is right, submit for real (factory.publish.mode: live):
WGF_PUBLISH_LIVE=1 bin/wgf publish --run <run-id> --platform crazygames   # PROPOSED (workstream 8)
bin/wgf runs --waiting                            # a login, a declaration, a duplicate: what to do
bin/wgf decide <run-id> done [--note ...]         # after doing it in the browser
bin/wgf publish --run <run-id> --track            # PROPOSED: later, read in-review -> live
```

Today a dry-run `submit` ends the run (route `dry-run`), and re-running the group with
`--run <run-id> --force` redoes every step of the slice; workstream 8 adds the per-platform
live re-entry above, which re-uses the same G6 record (it pins the same manifest) and the
draft found by `find_game`, so the live pass uploads nothing twice.

From an agent host, the `/wgf-publish` surface (regenerated) runs these commands and walks
the person through each WAITING reason: it runs `capture` for them to log in, shows the list
of human fields with their urls, and never answers G6 or a declaration itself.

---

## Part 3 - the four portals: what public docs say, and what needs a login

Read 2026-10-04 from public pages only, through a fetching tool that summarises: quotes are
near-verbatim, not byte-exact. Nothing was logged into, created, uploaded or submitted.
`docs/platform-targets-2026-10.md` holds the SDK, bundle and listing requirements; this part
adds the console flow. **No portal of the four documents an upload or submission API or
CLI**: a console form is the only path everywhere, which is why the console executor is the
adapter for all four.

### CrazyGames

| Fact | Source |
|---|---|
| Submission is "Submit a game" in the Developer Portal; a QA tool previews uploaded versions and "will guide you through the submission and review process step by step" | https://developer.crazygames.com/, https://docs.crazygames.com/faq/ |
| The submission asks for the web build, SDK integration (optional for Basic Launch), "game metadata (description, instructions, thumbnails)", a cover and a trailer video, and "qualitative metadata (game description and controls)" | https://docs.crazygames.com/faq/ |
| Review: initial QA check (bugs, quality, English, originality, PEGI 12) -> Basic Launch (7-21 days, monetization off) -> Full Launch (CrazyGames' decision on playtime, conversion, retention; full QA review) | https://docs.crazygames.com/requirements/intro/, https://docs.crazygames.com/faq/ |
| Updates are "usually processed within the same working day"; files hosted on CrazyGames' CDN | https://docs.crazygames.com/faq/ |
| The upload may take files or a folder, not only a zip (Unity custom build: "upload all files from that folder"). **Uncertain** | https://docs.crazygames.com/resources/unity-custom-build/ |
| Developer Portal Terms (18.08.2025): non-exclusive with an exclusivity option (3.1, 5.5); pay only in Full Launch and only with the CrazyGames SDK, no other portal branding, no other ads (5.3); warranties that information is accurate and IP is owned (7.1). No clause on automated portal use or on AI content | https://files.crazygames.com/documents/developer_terms_20250818.pdf |
| No AI policy; originality required ("not easily confused with another") | https://docs.crazygames.com/requirements/gameplay/, https://docs.crazygames.com/requirements/quality/ |

**A person must log in to learn:** the form's exact fields and limits; whether categories
and tags are chosen or assigned; the cover, video and build upload widgets (zip or files);
orientation, mobile and Progress Save toggles; status labels; the QA tool's checklist; the
terms checkbox; payout and tax forms; whether CAPTCHA or 2FA appears. The selector map in
`adapters/crazygames.py` is a hypothesis on every one of these.

**Human intents:** terms acceptance, exclusivity choice, payout and tax, the accuracy and
ownership warranties, Full Launch (CrazyGames' decision, not a click).

### Y8

| Fact | Source |
|---|---|
| Flow: "Create Your Game -> Submit for Reviews -> Await Approval -> Go Live on Y8"; HTML5, WebGL, Phaser and others accepted | https://developer.y8.com/ |
| A Studio comes first: logo 175x175 PNG/JPG/GIF up to 2 MB, name 4-32 chars (unique, permanent once published), About 10-500 chars, links, a required terms checkbox; status "Waiting for Approval" | https://docs.y8.com/studio/studio/ |
| Creating a game asks "only for its Game Name" and issues the Game ID; the App ID is issued when the game's page is first opened | https://docs.y8.com/studio/create-game/ |
| Game tabs: Basic Info, Leaderboard, Achievements, Feedback, AFP, SDK Initialization; builds uploaded under My Games | https://docs.y8.com/studio/overview/ |
| Review feedback appears in the game's Feedback tab; resubmission cooldowns 0, 6 h, 12 h, 24 h, 2 days, then 5 days (exempt above 10 M plays) | https://developer.y8.com/ |
| AI tools allowed with the rights and quality; "copied, misleading, low-quality, repeatedly reskinned, or mass-generated games" may be rejected; no disclosure required | https://developer.y8.com/ |
| No public developer agreement (a checkbox in the portal); YMP 50% share with PayPal or bank payout and tax details; AFP via Google | https://developer.y8.com/ |

**A person must log in to learn:** every Basic Info field (description, instructions,
categories, tags, thumbnail and screenshot sizes); the build upload (zip, size limit); status
labels; the terms text; CAPTCHA or 2FA. **Order matters for the adapter:** the Game ID and
App ID exist only after the game is created, and the build must carry them
(`WGF_Y8_APP_ID`, `WGF_Y8_GAME_ID`). So Y8's first release is two passes: `create_game` (a
person approves it as part of G6), the ids recorded in the registry and `game.config.yaml`,
a rebuild and re-package, then upload. The adapter must never upload an SDK-less build.

**Human intents:** the Studio itself (name is permanent), terms, payout and tax, monetization
programme (YMP or AFP).

### Yandex Games

| Fact | Source |
|---|---|
| "Add app" in https://games.yandex.com/console creates the game and its ID; upload the zip in General -> Archive; fill General (shared) and "Description and Promotion" per language; optional CSP and Countries tabs; "Submit for moderation" | https://yandex.com/dev/games/doc/en/console/add-new-game |
| General fields: Version, Archive, Supported platforms, Orientation, Game translated into, Age rating, Categories (up to 2), Tags (up to 20), Keywords (100 chars), "The game use cloud save", Postpone publication, Developer's comment (2048 chars, read by moderators) | https://yandex.com/dev/games/doc/en/console/add-new-game/draft |
| Per-language fields: Title, SEO description, Description, Short description, How to play, Icon, Maskable icon, Cover, Hero image, Vertical video, Horizontal video, Screenshots, Advertising videos (up to 20). "I want to enable AI descriptions" is on by default (machine translation from English) | same |
| The horizontal video (16:9, MP4, up to 28 s, 100 MB) may be **required**, not optional as profile 1.2.0 says. **Uncertain** (summarised page) | same |
| Statuses: Created (draft), Waiting for moderation, Published, **Verified** (passed with Postpone publication set; a Publish button then appears), Rejected (reasons by email and a moderator comment) | https://yandex.com/dev/games/doc/en/console/update-game, https://yandex.com/dev/games/doc/en/concepts/moderation |
| Updates: "Create draft" on the Draft tab; the live version stays during review | https://yandex.com/dev/games/doc/en/console/update-game |
| Moderation 3-5 business days, one per game at a time, at most 2 new-game requests per account; a rejection's cooldown doubles: 24 h, 2, 4, 8, 16 days; a reset once per 28 days | https://yandex.com/dev/games/doc/en/concepts/moderation |
| A contract unlocks moderation and payments (licensing model or YAN with payout details) | https://yandex.com/dev/games/doc/en/concepts/quick-start |
| REQ 1.23: interactive AI in games prohibited; pre-generated AI material allowed. REQ 3.5 copyright on all materials; REQ 2.7 content matches the declared age rating; the developer is solely liable for the age classification (Terms 1.6) | https://yandex.com/dev/games/doc/en/concepts/requirements, https://yandex.com/legal/yandexgames/en/ |

**A person must log in to learn:** labels beyond those quoted, the age-rating and category
lists, the upload widget, contract screens, CAPTCHA or 2FA on Yandex ID. **Profile changes
this implies:** `verification.states` gains `Verified` (moderation passed, not live: neither
`submitted_states` nor `live_states` but its own `approved` mapping), and `pending_states:
[Waiting for moderation]`. The rejection cooldown makes an unnecessary resubmission costly:
another reason `request_review` is never retried.

**Human intents:** contract and payout, age rating, Postpone publication and the later
Publish click on a Verified game, the AI-descriptions switch, Developer's comment (free text
to moderators: a person writes it or leaves it empty).

### GamePix

| Fact | Source |
|---|---|
| "Create your account on the GamePix Dashboard -> Integrate the SDK and submit -> Launch and earn"; 45% revenue share | https://partners.gamepix.com/developers |
| A testkit on my.gamepix; complete games only ("drafts or demos will not be approved"); no duplicates of catalogue games; no external ads or third-party SDKs; icon, cover and description must match the game | https://partners.gamepix.com/guidelines/submission |
| "Allow Distribution" spreads the game to third-party sites; without it the game is exclusive to gamepix.com | same |
| No review timeline, status labels, image sizes, size limit or upload API documented; GamePix's API is for publishers pulling the catalogue | https://partners.gamepix.com/developers |
| No public developer agreement; an older page names a separate "Game Uploading Agreement" (date unknown) | https://gamepix.blob.core.windows.net/gpxlib/docs/tos.html |

**A person must log in to learn:** the whole dashboard form, image sizes, the upload widget,
statuses, the developer agreement, payment and tax forms, CAPTCHA or 2FA. GamePix is also
blocked in code: no SDK adapter at the pinned template (template#23 on main). Its platform
and publication profiles exist since 2026-10-04 (the developer agreement, sign-up and
declarations: `docs/platform-targets-2026-10.md`, GamePix), and strategy and tech-plan refuse
the platform until a template release carrying the adapter is pinned.

**Human intents:** the agreement, "Allow Distribution" (a commercial choice), payment and tax.

### Across the four

- No upload API or CLI anywhere; console automation is the only automated path.
- No public developer terms of the four explicitly forbid automating the developer console
  (Yandex forbids bots for promotion, Y8 for traffic; CrazyGames' scraping ban is in the
  player terms). Y8's and GamePix's developer agreements are not public. This is not a
  finding that automation is permitted: `automation_terms` stays `unverified` until a
  person reads each agreement and records `terms_confirmed`.
- No portal requires AI disclosure; none forbids pre-generated AI assets; Yandex forbids
  interactive AI inside the game; Y8 and CrazyGames reject unoriginal or mass-generated
  games. Profiles therefore start `content_policy.ai_generated_text: unknown`, which stops
  for a person whenever the copy is generated, until a person records the policy.
- No public page states whether CAPTCHA or 2FA protects the console: the session check
  handles all of them.

---

## Part 4 - implementation split

Ordered; each workstream is one PR, testable alone, with no production portal traffic in
any test. "Fixture" is `scripts/tests/fixtures/publish/portal.py`, extended.

1. **Fix the metadata path (bug).** `adapters/console.py`: map `descriptions` by locale and
   every listing field the profile names; add a fixture page with a description field per
   locale. Tests: `test_publish_module.py` fake console asserts every field filled.
   Independent. *Done (2026-10-04): `ConsoleAdapter.listing_fields` reads the shipped
   listing's rendition and the platform profile's `store_listing` block; see
   `docs/publish-module.md`, "The listing fields". The Yandex and CrazyGames selector maps
   still name only title and description, so a required field they lack is reported until
   workstream 10 writes them from the real consoles.*
2. **Publication profile 2.0.0 (data + schema).** `core/artifacts/shared/publication-profile.schema.json`
   (`flow`, `identity`, `session`, `status.pending_states`, `fields`, `content_policy`,
   `adaptive`, `dismissable`, deny vocabulary), `platform-publication.schema.json` (new
   `human_required.reason` values, `submission.portal_game_id`,
   `automation-console-adaptive`), `check-integrity.py` (a flow may not contain cancel /
   withdraw / delete intents; irreversible intents have a profile ladder; every intent has a
   class), the fixture profile rewritten in the new form. Independent of 1.
3. **Executor runs profile intents.** `browser/console.spec.ts` becomes a generic intent
   runner (the locator ladder of 2.7, post-conditions, `actions.jsonl`, screenshots before
   and after), `browser.py` passes the flow. Fixture: pages whose markup varies by
   `PORTAL_MODE` (renamed label, extra dialog, moved button). Tests: Chromium against the
   fixture (`WGF_PUBLISH_BROWSER_TEST=1`), ladder fallbacks recorded. Depends on 2.
4. **find_game, status_gate, registry.** `step.py`, `adapters/console.py`,
   `workspace/titles/<id>/portals.json` writer, `wgflib/publication.py`. Fixture: a game
   made by hand with the same title (-> `duplicate-candidate`), a game under review (->
   `review-pending`), a recorded id (-> new version, no creation). Depends on 3.
5. **Media and human fields.** Upload icon, cover, screenshots, video from the shipped
   listing; `human` intents stop with the list. Fixture: media inputs, a declarations page,
   an age-rating questionnaire. Depends on 3.
6. **Bounded adaptive mode.** The drift loop in the executor (pause, redacted snapshot,
   proposal checks of 2.6, budget), the release-role call through the agent runner with an
   answer schema, `drift.json`. Tests: a scripted fake agent (good proposal, out-of-
   vocabulary name, deny-vocabulary name, fill-turned-click, value supplied, foreign
   origin, budget exhausted, drift on the irreversible intent -> `drift-irreversible`);
   Chromium against a drifted fixture. Depends on 3; independent of 4 and 5.
7. **Per-platform builds.** *Superseded by a human decision (2026-10-04): the Factory builds one bundle per `platforms[]` entry on the current contract-1 games, with no template release (the per-platform release workstream). The text below is the original proposal.* Pin a template release carrying contract 2; `wgf_verification`
   judges each bundle; `wgf_release` packages each, copies `build.json` into the manifest
   and the zip, drops `_prune`; guard `package_targets_platform` in `wgflib/publication.py`.
   Golden runs on the new pin. Template-side first (a release), then Factory. Independent of
   1-6.
8. **Multi-platform submit.** One `submit` visit per targeted platform (the workflow's
   `for_each` or one step per platform) and `wgf publish --run <id> --platform P`; `--track`
   read-only status visits. Depends on 4 and 7.
9. **Pre-upload guards.** `archive_shaped_to_console`, `copy_policy`, the human-intent list
   in readiness (`validate.py`, `wgflib/publication.py`). Depends on 2.
10. **Portal adapters, one per PR, in dry-run.** CrazyGames, Yandex, Y8, then GamePix (after
    the template release with the GamePix SDK adapter and `core/reference/platforms/gamepix.yaml`).
    Each starts as a profile written from public docs with every unknown marked; a person,
    logged in, runs the flow in dry-run with adaptive mode on, reviews `drift.json`, and
    commits the corrected profile. `status: verified` only after a dry run reached
    `save_draft` and a person checked the draft. Unit tests use recorded, redacted page
    snapshots, never the live portal. Depends on 3-6.
11. **Rules, docs, surfaces.** The changes of 2.13; `adapter-binding.yaml` and
    `gen-adapters.sh` for `/wgf-publish` and the release agent; regenerate both plugins and
    the runtime; `CONFORMANCE.md`. Lands with 6 (the rule changes when the code does).
12. **CI/CD migration.** Template PR per 2.14 and a template release; `wgf-org-setup.sh` and
    `docs/env-vars.md` in the Factory. Independent; land after 10 proves at least one portal
    in dry-run, so no portal goes without a path.

Validation for every Factory workstream: the module's tests, `wgf test-core`,
`check-integrity.py`, and - for 7 - both golden runs (`WGF_GOLDEN=1`). Changes under
`scripts/wgflib/` (publication guards, redaction) are core changes and state their reason.

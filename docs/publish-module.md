# The publish module

`scripts/wgf_publish/` implements the release lifecycle's tail inside the Factory: the
`publish` group of `core/workflows/new-game.workflow.yaml`, four steps that continue the run
which drafted a release.

```
release (release:draft)                      <- `wgf new-game` ends here, with a draft
      │
      │  wgf publish --run <run-id>            the same run, continued
      ▼
platform-validate  (release:validating)      the publication guards, the package on disk,
      │                                      the profile's assertions, the publication profile
      │                                      -> platform-publication: readiness READY |
      │                                         BLOCKED | HUMAN_REQUIRED | UNKNOWN
      ▼
release-review     [G5]  reversible          a person: the build, its manifest, its evidence
      ▼
publish-review     [G6]  IRREVERSIBLE        a person, `publish` or `reject`; the record pins
      │                                      the release-manifest by content hash
      ▼
submit             (release:submitting)      the platform adapter: find the draft by key,
      │                                      upload, configure, submit ONCE, read the portal
      │                                      state back -> platform-publication advanced only
      │                                      from what was observed
      ▼
$end                                         submitted | dry-run | waiting for a person
```

No new phase was added for this. `release:validating` and `release:submitting` were already
the lifecycle's states and `platform-publication` already its record; before 2.7.0 nothing
ran them and every publication guard answered UNKNOWN. Browser automation is an
implementation detail of one adapter method, used only where a portal publishes no API.

## Why `wgf new-game` stops at the draft

Publication is authorized per release, never standing (`core/lifecycle/gates.yaml`, G6), and
G6 never auto-approves. A `new-game` run that continued into the group on its own would end
WAITING at G6 every time, unattended or not. So the group is entered deliberately:

```bash
bin/wgf new-game                      # ... stops at G4; a person passes it; release drafts
bin/wgf publish --run <run-id>        # platform-validate, G5 (waits), ...
bin/wgf decide <run-id> approve       # G5
bin/wgf decide <run-id> publish       # G6 - only a person; `reject` ends the run
bin/wgf status <run-id>               # submitted | dry-run | WAITING at submit for a person
```

The run's artifacts carry over: the manifest the release step wrote, the verification it was
cleared by, the decisions. The G6 record pins the release-manifest by content hash, and the
`submit` step refuses to submit a manifest with any other hash.

## `platform-validate` (release:validating)

Inputs: `release-manifest`, `verification-report`, `qa-report`, `sdk-report`,
`scaffold-record`. Output: one `platform-publication` per packaged platform (named
`platform-publication-<platform>`), state `validated`, `validation-failed` or `packaged`.

For each platform the manifest packages, the step computes the guards the lifecycle names,
through `wgflib/publication.py` - the same code `wgf-state.py` runs when a person moves a
cursor, so the two never disagree:

| Guard | Reads | GREEN when |
|---|---|---|
| `candidate_frozen` | the manifest | a commit, packages, a sha256 checksum on each |
| `store_metadata_complete` | the manifest and `release/<id>/store-metadata.json` | every **required** platform has its descriptions, screenshots, icon, age rating and required locales, per its pinned platform profile |
| `package_shaped_to_profile` | the package file in the checkout | the file exists, its sha256 equals the manifest's checksum, its size is within the profile's `max_bundle_mb` |
| `assertions_pass` | the verification-report's `policy.assertions:<platform>` evidence for this commit | no blocking assertion breached |
| `metadata_and_locales_present` | as `store_metadata_complete`, for this platform | as above |

Store metadata is what the release role prepares (`core/roles/release.md`): a JSON file
`release/<release-id>/store-metadata.json` in the checkout keyed by platform
(`title`, `descriptions` by locale, `screenshots`, `icon`, `age_rating`, `locales_included`),
read before the manifest's own `store_metadata`. Without it the guard is RED and the release
is BLOCKED - the classic late failure, caught before anyone is asked to approve.

Readiness is derived from the verdicts and from the publication profile
(`core/reference/publication/<platform>.yaml`), never asserted:

| Readiness | Meaning | The step returns |
|---|---|---|
| `BLOCKED` | a guard RED | FAILED, route `fail`, not retryable; the record kept as evidence |
| `UNKNOWN` | a guard could not be evaluated (no checkout, no assertion results for this commit) | BLOCKED: supply what is missing and resume. UNKNOWN is never READY |
| `HUMAN_REQUIRED` | every guard GREEN, but publishing here is a person's act | SUCCESS; `submit` stops for the person |
| `READY` | every guard GREEN and an adapter may act | SUCCESS |

A **required** target with no package (the pinned template contract builds one bundle for
one platform; the release step packages only that one) is BLOCKED: the release can never be
live there. An optional unpackaged target is reported and skipped.

## G5 and G6

Both are `human-checkpoint` steps decided on what `gates.yaml` requires. G5 (`release-review`,
stage `release:rc`) reads `qa-report`, `verification-report`, `release-manifest`; it is
reversible, so an installation may auto-approve it (`factory.checkpoints`), and a `--mock`
run does. G6 (`publish-review`, stage `release:approved`) reads `release-manifest`, the
`platform-publication`, and the `store-listing` and `listing-validation-report` the release
shipped (gates.yaml decides G6 on all three artifacts); its choices are `publish` - the release machine's own edge
(`approved -> validating`) - and `reject`; it is irreversible, refused from automation by the
checkpoint, the record builder, the schema and `wgf-state.py` alike. `reject` at either gate
ends the run; an approved build may sit indefinitely.

## `submit` (release:submitting)

Inputs: `release-manifest`, `platform-publication`, `decision-record`, `scaffold-record`.
Output: the `platform-publication`, a new version of the same artifact.

In order, before anything is contacted:

1. **G6**: passed and current in this run (`context.gates_passed`); the newest
   decision-record is G6's, `approved`, `decided_by.mode: human`, and its `subject` pins the
   release-manifest the step holds, by content hash. Anything else is BLOCKED
   (`g6-not-passed`, `g6-not-human`, `g6-manifest-mismatch`, ...) with no record written.
2. **Idempotent re-entry**: a record that already says `SUBMITTED` or `VERIFIED` is returned
   as it is. Nothing runs.
3. **A person's answer** (`context.decision`): `done --note <portal reference>` records a
   submission made by hand (state `submitted`, `measurement_class: human`); `abandon` ends
   the attempt. Only a person's `done` is accepted.
4. **Readiness**: `HUMAN_REQUIRED` stops WAITING_FOR_HUMAN with the reason; anything but
   `READY` is BLOCKED.
5. **The package** is re-read from the checkout and its sha256 compared with the manifest:
   a mismatch is `INVALID_BUILD`, FAILED, not retryable.
6. **The credential and the terms** are checked again against the installation's
   configuration (below). A missing credential, unconfirmed terms, or a method only a person
   performs is HUMAN_REQUIRED.

Then the adapter runs, and the record is written from what it observed:

| Outcome | The step returns | `state` |
|---|---|---|
| `VERIFIED` / `SUBMITTED` | SUCCESS, route `submitted` | `submitted` (or `live`), from the portal's status text |
| `DRY_RUN` | SUCCESS, route `dry-run` | unchanged (`validated`) |
| `AUTH_REQUIRED`, `CAPTCHA_REQUIRED`, `HUMAN_REQUIRED` | WAITING_FOR_HUMAN; choices `done`, `abandon` | unchanged |
| `UNKNOWN` (a submit was clicked and the state read back is one the profile does not map, or could not be read) | WAITING_FOR_HUMAN, reason `ambiguous-portal-state` | unchanged |
| `REJECTED`, `PLATFORM_ERROR`, `INVALID_BUILD`, `RETRYABLE_FAILURE`, `BLOCKED` | FAILED, not retryable | unchanged |

**Nothing retries the submit.** The step's `retry` is `max_attempts: 1` in the workflow,
every failure it returns is `retryable=False`, and `max_visits: 3` bounds how often a person
may re-enter it. A re-entry after a crash finds the draft it already made: the idempotency
key (`wgf-<platform>-<16 hex>`, from the run id, the manifest hash and the platform) is
written into the draft's name and looked up before any upload, and the draft id is recorded
in the artifact. Browser interaction never makes the step pass: `SUBMITTED` and `VERIFIED`
require the portal's own status text, read back after the action and mapped through the
profile's `verification` lists.

### Modes

`factory.publish.mode` is `dry-run` by default: the session is checked, the draft found or
made, the listing filled, the portal state read back, and the submit is **not** made; the
record says `DRY_RUN`. `live` makes the submit, once - and only when the Factory's
environment also has `WGF_PUBLISH_LIVE=1`. Production submission is opted into twice, never
by one edit.

## Adapters: where everything platform-specific lives

`scripts/wgf_publish/adapters/`. The pipeline resolves one adapter per platform from the
publication profile's `submission.method` (and `factory.publish.platforms.<id>.adapter`),
calls `publish(job)` and reads a `Publication` in the common outcome vocabulary. No step
names a portal, a selector or a URL.

| Method | Adapter | What happens |
|---|---|---|
| `api` / `cli` | `ManualAdapter` | The portal's own documented tool is the supported way in (Poki's CLI). No adapter drives one yet: HUMAN_REQUIRED, the person runs the tool with the packaged release |
| `console` | `ConsoleAdapter` subclass with the portal's selector map (`crazygames`, `yandex`, the test fixture) | A deterministic browser run of the developer console, below. A console platform with no selector map of its own (`y8`, `gamedistribution`, `gamemonetize`) is HUMAN_REQUIRED |
| `email` | `ManualAdapter` | GameVui: the person emails the package; HUMAN_REQUIRED |
| `manual` | `ManualAdapter` | generic-web: nothing to submit; HUMAN_REQUIRED |

**API first.** None of the eight shipped portals documents an upload or submission API
(checked 2026-10-02: CrazyGames and Yandex document their web consoles only; Y8 and GameVui
likewise). The console path exists because that is the only path those portals offer; an
adapter never invents an API.

### The console executor: direct Playwright, not Playwright MCP

`scripts/wgf_publish/browser.py` + `browser/console.spec.ts`. One `pnpm exec playwright
test` run under `wgflib.procs` in the game checkout (its Playwright, its Chromium - as every
other browser harness here), from a flow file the adapter writes: console url, allowed
origins, the storage-state path, the package path, the listing fields, the selector map, the
timeouts, `submit: true|false`. Fixed phases:

```
authenticate    open the console with the captured session: logged in | login form | CAPTCHA | 2FA
find_existing   a draft carrying the idempotency key?            -> found, draft id
upload          none found: new draft, setInputFiles, wait for the acknowledgement or the error
configure       fill the listing fields on the draft's page, save
submit          only when the flow says so: click once, wait for the acknowledgement
verify          read the portal's own status text back
```

Every wait has a timeout from the profile; every request to an origin outside
`allowed_origins` is aborted at the browser; screenshots are taken only on console pages
after a known navigation (never on a login page or a challenge), hashed and cited by
run-relative path. The spec decides nothing - no model, no heuristics - and the irreversible
click is one line that runs once or not at all.

**Playwright MCP is not the submission executor.** It stays what it was: the QA and
self-playtest tool pinned in `workspace/config/mcp-playwright-localhost.json`, localhost
only, for an agent that plays a build or investigates a failure. Its strength - an agent
re-reasoning under UI drift - is the property the Factory refuses on an irreversible action.
Computer Use has no role.

### Publication profiles

`core/reference/publication/<platform>.yaml` (`core/artifacts/shared/publication-profile.schema.json`):
how a release reaches one portal - `submission.method`, the console url and allowed origins,
`automation_terms` (`permitted` | `prohibited` | `unverified`), the credential's variable
NAME, what only a person does there, the portal's constraints (Yandex: one moderation at a
time, postpone publication), and the status words `verify` maps. Data; versioned; pinned by
the publication record (`submission.publication_profile_version`), never by a game - which is
why it is a separate file from the content-hash-pinned platform profile. Every console portal
ships `status: unverified` and `automation_terms: unverified`: no live console flow has been
exercised, and whether each portal's terms permit automated console use was not established
from a public document. Until a person records that finding
(`factory.publish.platforms.<id>.terms_confirmed: true`), the step stops HUMAN_REQUIRED
before contacting the portal. The selector maps of `crazygames` and `yandex` are hypotheses
to be corrected from the console in dry-run before the profile is bumped to `verified`.

**Profile 2.0.0** (`x-wgf.version`; every shipped profile is at `version: 2.0.0`) makes the
console flow data, as `docs/portal-publishing-architecture.md` Part 2.4 designs it:

| Key under `submission` | What it says |
|---|---|
| `flow` | Ordered intents: `id`, `phase` (check_session ... request_review, verify), `class` (`reversible` \| `irreversible` \| `human`), `action` (click, fill, select, upload, navigate, read - no tick action exists), a locator `target` ladder (role > label > placeholder/text > testid > css > xpath with a reason; one kind per rung), `value` (a path into the shipped listing, manifest, package or identity - never free text), `names` an adaptive resolution may match, `expect` (the post-condition), `basis` (`observed` \| `documented` \| `hypothesis`) |
| `session`, `identity` | Locators for logged in / login / CAPTCHA / 2FA / anti-bot; how `find_game` looks for the game (`portal_id_from`: registry, config ids, idempotency key, exact case-folded title) |
| `status` | Was `verification`: `states`, `submitted_states`, `approved_states` (Yandex's Verified), `live_states`, `rejected_states`, and `pending_states` - the words `status_gate` never uploads over |
| `constraints` | Now also `upload_max_mb` (was `console.upload_max_mb`), `max_new_game_requests`, `resubmission_cooldown` |
| `fields` | What the console asks for, with `min`/`max`/`max_count`, `locales`, sizes; `null` where nobody has seen the console |
| `content_policy` | `ai_generated_text`, `ai_generated_assets`: `allowed` \| `disclose` \| `forbidden` \| `unknown` (required for every method; every shipped console says `unknown`) |
| `adaptive`, `adaptive_bounds`, `dismissable`, `deny` | Whether drift may be resolved here, the budget (at most 3 per intent, 10 per visit; down, never up), the overlays that may be dismissed, and the console's own words for the deny vocabulary |

Top level, `sources` (url, date read) and `unknowns` (what a person must log in to learn)
make every gap explicit. `check-integrity.py` adds the rules a schema cannot state
(`wgflib.publication.flow_problems`, shared with the executor to come): no intent cancels,
withdraws, deletes, removes or unpublishes anything; every irreversible intent has a profile
ladder and no adaptive `names`; every `request_review` intent is irreversible; every intent
has a class; adaptive `names` and `dismissable` stay outside the deny vocabulary
(`DENY_VOCABULARY` plus the profile's `deny`); every `*_states` word is a `states` word, and a
flow that requests review names its `pending_states`. Today the executor still runs the
adapter's selector map (above); running the profile's `flow` is workstream 3 of the
architecture. The shipped console profiles were written from public pages only - no locator
is `observed`, every one stays `status: unverified`.

## Authentication and secrets

The automation never logs in. A person captures the portal session once, in a headed
browser - `python scripts/wgf-publish.py capture <platform> --out <path> --checkout <game>`
runs `playwright open --save-storage` - and keeps the Playwright storage state where the
installation keeps secrets. The profile names the variable (`WGF_PUBLISH_<PLATFORM>_STORAGE_STATE`)
that holds its path (or the JSON), and the installation lists that name in
`factory.publish.env_passthrough`: a **third** allowlist beside `factory.agents.env_passthrough`
(agents) and `game_env_passthrough` (game code), so a portal session never reaches an agent
or a build. The step reads it only for the platform whose profile names it, writes a
private copy for the one browser run, registers every cookie and token value with
`wgflib.redact`, and overwrites and deletes the copy when the run ends. An expired session
is `AUTH_REQUIRED`; a CAPTCHA or second factor stops the step; nothing is bypassed.

**Redaction** (`scripts/wgflib/redact.py`) is the last line, applied in the kernel: every
record on the workflow event bus - messages, log lines, errors, progress - is scrubbed before
any subscriber (events.jsonl, the terminal) sees it; registered literal values and
secret-shaped spans (Authorization and Cookie headers, bearer tokens, `token=`/`password=`
assignments, vendor key shapes, JWTs, private key blocks) are replaced, and a mapping key
named like a secret has its whole value replaced. The publish steps scrub every piece of
evidence before sealing an artifact. Traces and videos are off; screenshots are taken only
where the executor was told the console is. Redaction is text matching: the first line is
the allowlist and a secret that is never printed.

## Evidence

Every record carries `evidence[]` (guard verdicts, the package file with its hash, the
Playwright run's exit code and tail, screenshots by run-relative path and sha256, the
status text read back), a `measurement_class` (`automation-check` for the validating step,
`automation-console` for a console run, `human` for a person's `done`), the `workflow`
reference, and the `submission` block (method, idempotency key, portal draft id, dry run,
attempts, the G6 record and manifest hash it was authorized by). `external_approval` on the
release-manifest stays `not-claimed`: a portal's moderation verdict is transcribed by a
person into the record (`in-review`, `live`, `rejected` with its compliance finding), never
inferred by automation.

## Configuration

```yaml
factory:
  publish:
    mode: dry-run                     # live also needs WGF_PUBLISH_LIVE=1
    env_passthrough: []               # [WGF_PUBLISH_CRAZYGAMES_STORAGE_STATE]
    platforms: {}                     # crazygames: {terms_confirmed: true}
    # profiles_extra: []              # more publication profiles (tests)
    # timeouts: {}                    # action / navigation / upload, ms
```

A step's `with:` overrides any key, plus `repo_dir` for the checkout (the one precedence
every step uses, `docs/checkouts.md`).

## Tests

`scripts/tests/test_publish_module.py` (RELEASE category): redaction; every guard; adapter
resolution and the session's private copy; `platform-validate` on a drafted release (undecided,
blocked, human-required, ready, a tampered package); `submit` with a fake console executor
(G6 refusals, dry-run, live needing both switches, an existing draft reused, idempotent
re-entry, login / CAPTCHA / second factor, an ambiguous state, a rejection, an upload error,
a crash, no browser, a person's `done` and `abandon`, a changed package, the session never
reaching a record or the event log); the whole group through the real engine; and, with
`WGF_PUBLISH_BROWSER_TEST=1`, real Chromium against `scripts/tests/fixtures/publish/portal.py`
(dry run uploads and never submits, live finds the draft by key and submits once, a second
live run submits nothing again, expired session / CAPTCHA / ambiguous state stop for a
person, a refused upload is a platform error). No test contacts a real portal; the
acceptance job holds no portal credential.

## What stays with a person

Capturing and rotating the session; every login challenge; confirming a portal's terms;
G5 and G6; the submission itself wherever the method is `api`, `cli`, `email` or `manual`,
or the console flow is unverified; `accept_partial` and `withdraw`; transcribing the
moderation verdict and writing the compliance finding on a rejection
(`core/lifecycle/stages/publish.md`).

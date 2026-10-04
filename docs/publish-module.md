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
| `package_shaped_to_profile` | the package file in the checkout | the file exists, its sha256 equals the manifest's checksum, its size is within the profile's `max_bundle_mb`. Since 2.8.0 each target's package is made from that platform's own bundle (`packages[].bundle_hash`, [release-module.md](release-module.md#one-package-per-target-platform)), so the SDK wiring it carries is its own |
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

One `platform-publication` per target: since 2.8.0 a release of a title with several
targets packages every one of them from its own verified bundle, or is not drafted, so
`platform-validate` judges each - its package, its profile's assertions on its own bundle,
its listing rendition - and a portal can be BLOCKED while another is READY. A **required**
target with no package (a release drafted from one bundle by an earlier verification, which
packaged only the platform that bundle boots) is BLOCKED: the release can never be live
there; re-run verify and release. An optional unpackaged target is reported and skipped.
A store-listing requirement a profile leaves `null` (all of Y8's `store_listing`) stays
UNKNOWN in the listing validation and is never passed; it does not block the release
([store-listing-module.md](store-listing-module.md)).

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
6. **The terms** are checked again against the installation's configuration (below).
   Unconfirmed terms, or a method only a person performs, is HUMAN_REQUIRED. A console needs
   no credential in advance: a person logs in, live, in the window the executor opens.

Then the adapter runs, and the record is written from what it observed:

| Outcome | The step returns | `state` |
|---|---|---|
| `VERIFIED` / `SUBMITTED` | SUCCESS, route `submitted` | `submitted` (or `live`), from the portal's status text - only after a confirmed `request_review` |
| `DRY_RUN` | SUCCESS, route `dry-run` | unchanged (`validated`) |
| `UPLOAD_COMPLETE` (live: the build is on the draft and saved, nothing requested) | WAITING_FOR_HUMAN_SUBMIT_CONFIRMATION; choices `submit`, `hold`, `abandon` | unchanged |
| `IDS_ISSUED` (the portal issued ids on create the build does not carry) | SUCCESS, route `platform-ids` | unchanged |
| `AUTH_REQUIRED` (nobody logged in in the window, or it was closed) | WAITING_FOR_HUMAN_LOGIN; `wgf resume` opens the window again | unchanged |
| `HUMAN_REQUIRED` (`declaration`, `legal`, `manual-submission`, ...) | WAITING_FOR_HUMAN; choices `done`, `abandon` | unchanged |
| `UNKNOWN` (`duplicate-candidate`, `review-pending`, `drift-irreversible`, `ambiguous-portal-state`) | WAITING_FOR_HUMAN | unchanged |
| `REJECTED`, `PLATFORM_ERROR`, `INVALID_BUILD`, `INVALID_METADATA`, `RETRYABLE_FAILURE`, `BLOCKED` | FAILED, not retryable | unchanged |

**Nothing retries an irreversible action, and the upload and the request never share a
visit.** The step's `retry` is `max_attempts: 1` in the workflow, every failure it returns is
`retryable=False`, and `max_visits: 3` bounds how often a person may re-enter it. A live
visit uploads and saves, then stops `UPLOAD_COMPLETE`; only a later visit whose job carries
`submit_confirmed` (the step sets it after a person's `wgf decide <run> submit`) runs the
profile's `request_review` intent - once, on a profile locator, and not at all when the
game's status already says it was requested. A re-entry finds the game it already made:
`find_game` tries the recorded portal id, the config ids, the idempotency key
(`wgf-<platform>-<16 hex>`, from the run id, the manifest hash and the platform) and the
exact title before anything is created, and an unrecorded match stops
(`duplicate-candidate`). Browser interaction never makes the step pass: `SUBMITTED` and
`VERIFIED` require the portal's own status text, read back after the request and mapped
through the profile's `status` lists.

### Modes

`factory.publish.mode` is `dry-run` by default. On a real portal a dry run logs in (a
person), finds the game and reads its status, then stops before its first change and says
what it would create, upload and fill; the record says `DRY_RUN`. Only the fixture portal's
dry run creates, uploads and saves a draft (nothing ever requests review there). `live`
uploads and saves - and only when the Factory's environment also has `WGF_PUBLISH_LIVE=1`;
production is opted into twice, never by one edit - and the review request waits for a
person's `submit` in a later visit.

## Adapters: where everything platform-specific lives

`scripts/wgf_publish/adapters/`. The pipeline resolves one adapter per platform from the
publication profile's `submission.method` (and `factory.publish.platforms.<id>.adapter`),
calls `publish(job)` and reads a `Publication` in the common outcome vocabulary. No step
names a portal, a selector or a URL.

| Method | Adapter | What happens |
|---|---|---|
| `api` / `cli` | `ManualAdapter` | The portal's own documented tool is the supported way in (Poki's CLI). No adapter drives one yet: HUMAN_REQUIRED, the person runs the tool with the packaged release |
| `console` | `ConsoleAdapter` (the profile's flow; `crazygames` and `yandex` subclasses add nothing yet; `FixturePortalAdapter` for the tests) | The intent runner over the publication profile's flow, below. A console profile without a flow is HUMAN_REQUIRED |
| `email` | `ManualAdapter` | GameVui: the person emails the package; HUMAN_REQUIRED |
| `manual` | `ManualAdapter` | generic-web: nothing to submit; HUMAN_REQUIRED |

**API first.** None of the eight shipped portals documents an upload or submission API
(checked 2026-10-02: CrazyGames and Yandex document their web consoles only; Y8 and GameVui
likewise). The console path exists because that is the only path those portals offer; an
adapter never invents an API.

### The console executor: a profile-driven intent runner, not Playwright MCP

`scripts/wgf_publish/adapters/console.py` + `browser.py` + `browser/console.spec.ts`. One
`pnpm exec playwright test` run under `wgflib.procs` in the game checkout (its Playwright,
its Chromium - as every other browser harness here). No selector lives in code: the adapter
resolves the publication profile's `submission.flow` against the job - every value an
intent names (`listing.title`, `listing.text.<locale>.<field>`, `listing.media.<key>` from
the store metadata, `package.file`, `identity.title`), `<locale>` substituted in per-locale
intents, which run once per locale - and writes a flow file the runner executes without
deciding anything. A non-optional intent whose value the job does not hold is BLOCKED
before anything is contacted; an optional one is left out and named. Phases:

```
session         open the console in a headed, fresh, ephemeral browser; not logged in ->
                WAITING_FOR_HUMAN_LOGIN until a person logs in in that window (below)
find_game       recorded id > config game_id/app_id > idempotency key > exact title, in the
                profile's identity.portal_id_from order; an unrecorded match stops
                (duplicate-candidate); a recorded id not in the list stops (ambiguous)
status_gate     the game's status: a pending_states word stops (review-pending) - nothing
                uploads over a pending review, nothing cancels it
create_game     only when nothing matched and the job allows it; then identity.
                issued_on_create is read (Y8's Game ID and App ID): an id the build does
                not carry yet stops before any upload (IDS_ISSUED)
upload_build    the one package
fill_metadata   listing fields; per-locale intents once per locale
upload_media    icon, cover, screenshots: the input's `accept` and `multiple` are checked
                first (INVALID_METADATA otherwise)
human_fields    the profile's `human` intents: reported with their note and url, never
                acted on; one whose `expect` is met on the page counts as done
save_draft      save; the post-condition read back
request_review  only when the job carries submit_confirmed, live, every human field done,
                not already requested: once, profile locator only, never adaptive
verify          the portal's own status text
```

**Locators.** Each intent has a ladder, tried in order: role + accessible name, label,
placeholder, exact text, stable attribute (`testid`), css, xpath. The first rung that
resolves to exactly one visible element (an attached one for a file input) wins and is
recorded with its rung; never coordinates. Every action's post-condition (`expect`: url,
value read back, an element shown, text, a status word) is checked after it. A ladder that
matches nothing or several elements, or a failed post-condition, ends the visit with a
`drift` result naming the intent: `UNKNOWN` (`ambiguous-portal-state`) on a reversible
intent, `drift-irreversible` on the request - unless the bounded adaptive mode (below)
resolves a reversible intent's drift. A failed post-condition after the irreversible click
is never retried: a person reads the portal. A profile `status.error` shown after an action
is `PLATFORM_ERROR` with its text.

**The live login handoff.** The browser is headed (headless only for the tests' fixture
portal) and its context is fresh: no storage state in, none out, no persistent profile; the
session lives only while that window is open. When the console is not logged in - the
profile's `session` markers (`logged_in`, `login`, `captcha`, `two_factor`, `anti_bot`,
`authenticated_url`), and whatever they say, a page off the allowed origins or showing a
password, CAPTCHA or one-time-code field - the runner writes

```
{state: WAITING_FOR_HUMAN_LOGIN, portal, step, url (origin + path), reason,
 action: "log in in the opened browser window; handle CAPTCHA/2FA yourself",
 resume: "the console's authenticated page is detected", at}
```

to its state file and stdout, and polls until the authenticated console is detected or
`factory.publish.login_timeout_s` (default 900) runs out. The adapter relays each state
change (`WAITING_FOR_HUMAN_LOGIN`, `AUTHENTICATED`, `LOGIN_TIMEOUT`, `LOGIN_ABANDONED`,
`ENDED`) as step progress, so `wgf status` shows it while the browser waits, and records each
period in `Publication.login_handoffs`. Detected: the visit continues in the same browser.
Timeout or a closed window: `AUTH_REQUIRED`, waiting, never a failure. A CAPTCHA, second
factor or anti-bot check shown mid-flow waits for the person the same way. While a person
drives the window, requests to other origins (an identity provider) are let through;
otherwise every request outside `allowed_origins` is aborted. The Factory never asks for,
types or stores a password or one-time code, never answers a challenge, and never takes a
screenshot on a page that is not the logged-in console.

**`actions.jsonl`.** One JSON line per browser action and per waiting period in
`<run>/<step>/<visit>-<attempt>/actions.jsonl` (`Publication.actions_log`, run-relative):
portal, phase, intent id, class, action, the locator used, its rung and `source: profile`,
the element's role and name, the value's sha256 (the value itself only for public listing
copy; files by name and sha256), the result and the post-condition's, `adaptive` (false
unless the line is the bounded adaptive mode's), `human_intervention` (true for login
waits), timestamps, and pre/post screenshot paths with their hashes. The adapter scrubs every
line with `wgflib.redact` after the run; no password, token, cookie or one-time code is ever
written.

### Bounded adaptive mode

`scripts/wgf_publish/adaptive.py` (the resolver side) and the checks in
`browser/console.spec.ts` (`docs/portal-publishing-architecture.md` 2.6). The Playwright
executor stays the only thing that operates the browser; an agent may only help it past
reversible UI drift - a renamed label, a moved element, a tour popover in the way - for the
same predefined intent.

**When.** A **reversible** intent's ladder matches nothing or several elements, or its
post-condition fails, and all of: the profile says `adaptive: allowed`; the installation
sets `factory.publish.adaptive: true` (default false; `factory.publish.platforms.<id>.
adaptive: false` turns one portal off); a resolver agent is configured
(`factory.publish.resolver`, `kind: command`). Otherwise drift stops as above, and the stop
says why the mode was unavailable. Never adaptive: `irreversible` and `human` intents; the
`session`, `find_game` (the identity choice - which game), `status_gate` and
`request_review` phases; a `read` intent; an intent with no `names`.

**The request.** The executor pauses and takes a snapshot of the logged-in console page:
each visible control, link, heading, label and dialog with its role, accessible name,
labels, placeholder, text, stable attributes and state; every input value replaced by
`<value>` (or empty); hidden and password inputs left out; never on a login, CAPTCHA,
second-factor or anti-bot page (no snapshot, no request: the visit stops); no cookie,
header, storage or network traffic. It writes `drift-request.json` beside `actions.jsonl` -
the intent (id, phase, action, the roles that fit it, its `names`, the failed ladder, the
post-condition with the value masked, the `page` pattern), why it drifted, the page's url
path, the snapshot and its sha256, the `dismissable` names, the remaining budget - and
waits for `drift-response.json` (the resolver's timeout + 30 s; then `stop`). A Responder
thread of the step reads the request, scrubs it with `wgflib.redact`, keeps only those keys,
and asks the resolver. The browser process never runs a model.

**The resolver** is the release role run through the Factory's agent runner, like the
review and assets steps' agents: `argv` under `wgflib.procs` (its own process tree,
timeout), placeholders `{request}`, `{answer}`, `{schema}` (the answer's JSON schema),
`{prompt}`; `answer_from: stdout` (the last JSON object it prints) or `file`. Its
environment is `wgflib.agentenv`'s allowlist plus `factory.agents.env_passthrough`, minus
every publish variable (`WGF_PUBLISH_*` and `factory.publish.env_passthrough`). Give it no
tools, no browser and no MCP server: it reads one file and answers. Its answer is parsed
strictly into exactly one of `resolve` (one locator rung for the same intent: role + name,
label, placeholder, text, testid, css or xpath - never an index, coordinates, a script or
keys), `dismiss` (one overlay), `navigate` (a url path) or `stop`; anything else, a crash, a
non-zero exit or a timeout is `stop`.

**The executor's checks**, every one recorded, all of which must pass before it acts: the
proposal kind fits the intent; it carries no value (a value only ever comes from the job)
and no other action (a fill never becomes a click); the page is on an allowed origin and is
the intent's page (its `page` pattern; else, on a game's own phases, that game's page); the
locator is one well-formed rung that resolves to exactly one visible (for an upload,
attached), enabled element; its role fits the intent's action (fill: textbox; select:
combobox or listbox; upload: file input; click: button or link); one of its accessible
names, labels or placeholder is in the intent's `names` (case-folded) - for a dismiss, in
the profile's `dismissable`; and none of its names, its text or the locator's own text
matches the deny vocabulary (`wgflib.publication.DENY_VOCABULARY` plus the profile's
`deny`). A navigate must be a path (`/...`) that stays on an allowed origin (and on the
intent's `page`, when it names one). The budget: `adaptive_bounds`, at most 3 per intent and
10 per visit, lowered by `factory.publish.adaptive_bounds`, never raised. A refused proposal
stops the visit `UNKNOWN` (`ambiguous-portal-state`) with the proposal and the checks
recorded. A resolved element is acted on exactly as a profile locator would be, and its
post-condition checked the same way; a failure is never adapted again. After a dismiss or a
navigate the profile's own ladder is tried again.

**An irreversible intent** that drifts stops `drift-irreversible` as before. With the mode
on, the resolver is asked once for a suggestion (`suggestion_only` in the request); it is
recorded in `drift.json`, `actions.jsonl` and the outcome's message as a suggestion, and
never checked against the page or acted on: a person confirms the locator by correcting the
profile, or requests review by hand.

**What is recorded.** Every adaptive line in `actions.jsonl` carries `adaptive: true`,
`source: adaptive`, the snapshot hash, the proposal, each check with its result, whether it
`acted`, and the outcome. A record of a visit in which any adaptive action ran (a resolved
element acted on, an overlay dismissed, a navigation) is
`measurement_class: automation-console-adaptive`. Each visit's `drift.json` lists the
drifted intents: the failed ladder, why, the proposal, the checks, the outcome (`ok`,
`refused`, `stopped`, `acted`, `post-condition-failed`, `suggestion`), the locator that
worked, and a `proposed_patch` - a YAML snippet putting it first in the intent's ladder.
Nothing edits a profile:

```bash
python3 scripts/wgf-publish.py drift-review <run-id|DIR>          # every proposal, every check
python3 scripts/wgf-publish.py drift-review <run-id> --apply --profile-out new.yaml
        # a NEW profile file, version bumped, the locators that held their post-condition
        # first in their ladders: a person reviews it and commits it as the next version
```

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
flow that requests review names its `pending_states`; a console's credential is
`human-login` (2.1.0: `storage-state` is refused); `session.authenticated_url` is a regular
expression; `identity.issued_on_create` names each id once. The executor runs the profile's
`flow` (above). The shipped console profiles were written from public pages only - no
locator is `observed`, every one stays `status: unverified`.

## Authentication and secrets

The automation never logs in and keeps no session. Every console profile's credential is
`{kind: human-login}` (publication profile 2.1.0): a person logs in, live, in the headed
browser window the `submit` step opens, and handles any CAPTCHA, second factor or anti-bot
check there; the executor waits (WAITING_FOR_HUMAN_LOGIN) and continues in the same browser.
No storage state is captured, loaded or saved, no cookie is read, no persistent browser
profile is used: the session ends with the window, and the next visit asks again. The
former `wgf-publish.py capture` command, the `WGF_PUBLISH_<PLATFORM>_STORAGE_STATE`
variables and their `factory.publish.env_passthrough` entries are retired; a profile that
still names `storage-state` is refused by `check-integrity.py` and BLOCKED by the adapter.
`factory.publish.env_passthrough` remains only for a tool's `token` credential (a CLI's
login), which no shipped adapter uses yet.

**Redaction** (`scripts/wgflib/redact.py`) is the last line, applied in the kernel: every
record on the workflow event bus - messages, log lines, errors, progress - is scrubbed before
any subscriber (events.jsonl, the terminal) sees it; registered literal values and
secret-shaped spans (Authorization and Cookie headers, bearer tokens, `token=`/`password=`
assignments, vendor key shapes, JWTs, private key blocks) are replaced, and a mapping key
named like a secret has its whole value replaced. The publish steps scrub every piece of
evidence before sealing an artifact. Traces and videos are off; screenshots are taken only
where the executor was told the console is. Redaction is text matching: the first line is
the allowlist and a secret that is never printed.

## Observing a real console

Before an adapter is trusted for a portal, a person logs in to its real developer console
and the Factory records what the console actually shows - a publication profile may hold
only observed or officially documented facts:

```bash
python scripts/wgf-publish.py observe crazygames --checkout ../my-game     [--out DIR] [--login-timeout-s 900] [--max-minutes 30] [--authenticated-url REGEX]
python scripts/wgf-publish.py observe-summary DIR     # the summary again, and the fields as JSON
```

`observe` (`scripts/wgf_publish/observe.py`, `browser/observe.spec.ts`) opens the profile's
console url in a headed Chromium - the checkout's own Playwright, run under `wgflib.procs` -
in a **fresh, ephemeral context**: no storage state loaded, none saved, no persistent
profile. It prints, and writes to `<out>/state.json`:

```
WAITING_FOR_HUMAN_LOGIN portal=crazygames step=observe url=https://developer.crazygames.com/
  reason="..." action="log in in the opened browser window; handle CAPTCHA/2FA yourself"
  resume="the console's authenticated page is detected"
```

That is a waiting state, not a failure. The person logs in in that window and answers every
CAPTCHA and second factor; the Factory never sees, types, asks for or stores a password or
code. The console counts as reached when a page is on one of the profile's
`allowed_origins`, shows no password, CAPTCHA or one-time-code field, and - when given, or
named by the profile as `session.authenticated_url` - its origin + path matches the regex;
state becomes `AUTHENTICATED`. No login within `--login-timeout-s` is `LOGIN_TIMEOUT`, exit 3,
browser closed.

Then the person uses the console as usual and the observer only reads: it never clicks,
types, submits or uploads, and navigates only once, to the console url, before the login
(`test_publish_observe.SpecSource` checks its source). On every main-frame navigation, and
every 5 s of a page, it records - only on an allowed origin, never on a login, CAPTCHA or
second-factor page, and once per distinct DOM hash - into `<out>/pages/NNN.json` and `.png`:

- the accessibility snapshot (roles, names, states) with every input value masked;
- the form inventory read from the DOM: for each input, textarea, select and file input its
  role, accessible name, label, placeholder, type, required, maxlength/minlength, pattern,
  `accept` and `multiple`, a select's option texts, its `data-testid`/`name`/`id` and the
  nearest heading; buttons and links by accessible name; visible status-like texts (badges,
  chips, cells under a "Status" column);
- a screenshot with every input, and every email-shaped text, masked;
- the url as origin + path, never a query or fragment.

No cookie, storage, header, request body, trace or video is ever recorded, and every text
passes `wgflib.redact` with email-shaped strings replaced. The observation ends when the
person closes the window, or `--max-minutes` after the login; the context is closed and
nothing of the session survives. `<out>/index.json` lists the pages and their hashes;
`<out>/summary.md` gives, per page, the path, headings, forms with their fields, buttons and
status texts. The default `--out` is `<project>/.factory/observations/<platform>/<UTC
timestamp>/` (git-ignored). Exit codes: 0 ended, 1 the observer failed (or no Chromium:
BLOCKED), 2 unusable arguments, 3 `LOGIN_TIMEOUT`.

What an observation shows becomes a profile fact only when a person writes it into the
profile; the observer never edits one.

## Evidence

Every record carries `evidence[]` (guard verdicts, the package file with its hash, the
Playwright run's exit code and tail, screenshots by run-relative path and sha256, the
status text read back), a `measurement_class` (`automation-check` for the validating step,
`automation-console` for a console run, `automation-console-adaptive` when the bounded
adaptive mode acted in it, `human` for a person's `done`), the `workflow`
reference, and the `submission` block (method, idempotency key, portal draft id, dry run,
attempts, the G6 record and manifest hash it was authorized by). `external_approval` on the
release-manifest stays `not-claimed`: a portal's moderation verdict is transcribed by a
person into the record (`in-review`, `live`, `rejected` with its compliance finding), never
inferred by automation.

## The portal registry

A title has at most one game on each portal. `workspace/titles/<title-id>/portals.json`
(`core/artifacts/portal-registry.schema.json`; a mutable cursor like `state`, no provenance)
holds one entry per platform: the portal game id (`external_game_id`, `app_id`,
`other_ids`), slug and URL, a `status` (NOT_CREATED, DRAFT_CREATED, DRAFT, PENDING_REVIEW,
VERIFIED, REJECTED, PUBLISHED, BLOCKED, UNKNOWN), the portal's own submission and
publication wording, the build and listing hashes last applied, the release, how the game
became known (`created-by-factory`, `associated-by-person`, `observed`), evidence, and an
append-only `history` saying who changed what, in which run.

`scripts/wgf_publish/registry.py` is the only writer: `load(title)`, `get(platform)`,
`record(platform, ..., by, run_id, note)`, `associate(platform, id, note=...)`,
`lookup_candidates(platform, config_game_id, config_app_id)` (the ids find-game tries, in
order: the registry's, then `game.config.yaml`'s) and `invalidate_if_changed(platform,
build_hash, campaign_hash)`. Its transition table is data in the module. PENDING_REVIEW,
VERIFIED, PUBLISHED and REJECTED are entered only with the portal's status text as
evidence; an automated write never changes a recorded game id; every write is validated
against the schema and replaces the file atomically. Entries are independent: a rejection
on one platform leaves the others as they were. A person links a game created by hand:

```bash
python3 scripts/wgf-publish.py registry associate <title> <platform> <portal-game-id> --note "why"
python3 scripts/wgf-publish.py registry show <title> [--json]
```

The `submit` step does not read the registry yet; wiring find-game and the read-back into
it is the next step (`docs/portal-publishing-architecture.md`, 2.5).

## Configuration

```yaml
factory:
  publish:
    mode: dry-run                     # live also needs WGF_PUBLISH_LIVE=1
    login_timeout_s: 900              # how long a visit waits for a person to log in
    env_passthrough: []               # a tool's token only; no console session exists
    platforms: {}                     # crazygames: {terms_confirmed: true}
    # profiles_extra: []              # more publication profiles (tests)
    # timeouts: {}                    # action / navigation / upload, ms
    adaptive: false                   # the bounded adaptive mode; also needs a resolver
    # adaptive_bounds: {max_per_intent: 3, max_per_visit: 10}   # lower only
    resolver: {kind: none}            # none | command: {argv, answer_from, timeout_seconds}
```

A step's `with:` overrides any key, plus `repo_dir` for the checkout (the one precedence
every step uses, `docs/checkouts.md`).

## Tests

`scripts/tests/test_publish_module.py` (RELEASE category): redaction; every guard; adapter
resolution and that no console session is captured, loaded or kept; `platform-validate` on a
drafted release (undecided, blocked, human-required, ready, a tampered package); `submit`
with a fake runner (G6 refusals, dry-run, live needing both switches and stopping
`UPLOAD_COMPLETE`, a recorded game used and an unrecorded one stopping, ids issued on
create, idempotent re-entry, no login in the window, an unsaved draft, an upload error, a
crash, no browser, a person's `done` and `abandon`, a changed package, no session in the
flow); the whole group through the real engine; and, with `WGF_PUBLISH_BROWSER_TEST=1`, a dry
run through the step in real Chromium. `scripts/tests/test_publish_executor.py` (RELEASE):
the flow resolved from the job, every runner result mapped to its outcome and interface
fields, the state relay, the scrubbed `actions.jsonl`; and, with `WGF_PUBLISH_BROWSER_TEST=1`,
headless Chromium against `scripts/tests/fixtures/publish/portal.py`, driven only by the
fixture profile's flow, the test playing the person: the login handoff (waiting recorded,
then the visit continues), a login on an identity provider's origin, a login timeout
(`AUTH_REQUIRED`), a CAPTCHA and a second factor
mid-flow, a duplicate by title, a pending review (nothing uploaded), the dry run, a live
upload (`UPLOAD_COMPLETE`, nothing requested) and a confirmed visit requesting review once
(`SUBMITTED` from the status text; a third visit clicks nothing), ids issued on create
(`IDS_ISSUED`, then the rebuilt visit uploads to the same game), drift on a reversible and on
the irreversible intent, a refused upload, pending declarations, `actions.jsonl` complete
and free of secrets, and no storage-state file anywhere. `scripts/tests/test_publish_adaptive.py`
(RELEASE): the strict answer parser, the budget, the configuration (off by default), the
resolver's environment without publish variables, a command resolver run under
`wgflib.procs`, the request/response protocol, the flow's `adaptive` block, the measurement
class, `drift.json` and `drift-review`; and, with `WGF_PUBLISH_BROWSER_TEST=1`, a SCRIPTED
resolver (never a model) against the fixture portal's drift modes: a good resolution (acted,
post-condition held, patch proposed, nothing secret in the request), and refusals of a name
outside the vocabulary, a deny-vocabulary name, a fill turned click, a resolver-supplied
value, a foreign origin and a path off the console, the wrong page, an ambiguous locator, a
spent budget, a dismissable overlay and a destructive one, the irreversible intent (a
suggestion only), the mode turned off, and a malformed answer. `scripts/tests/test_publish_registry.py`
(RELEASE) covers the portal registry. `scripts/tests/test_publish_observe.py`
(RELEASE): the observer's scrubbing, summary and exit codes around a stand-in browser, its
spec's source (no action call, no session kept), and - with `WGF_PUBLISH_BROWSER_TEST=1` -
headless Chromium against the fixture portal with the test playing the person: waiting,
then authenticated, the form inventory read, nothing typed or prefilled, no password,
cookie or email in the output, no request caused by the observer. No test contacts a real
portal; the acceptance job holds no portal credential.

## What stays with a person

Every login, live, in the window the step opens, and every challenge; the `submit`
decision after an upload; every declaration and legal field; confirming a portal's terms;
G5 and G6; the submission itself wherever the method is `api`, `cli`, `email` or `manual`,
or the console flow is unverified; `accept_partial` and `withdraw`; transcribing the
moderation verdict and writing the compliance finding on a rejection
(`core/lifecycle/stages/publish.md`).

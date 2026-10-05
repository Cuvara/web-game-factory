# /wgf-publish (Web Game Factory)

**Transition** `release: approved -> validating -> submitting -> live`
**Role** `release`
**Gate** `G6` — see `core/lifecycle/gates.yaml` for its required artifacts, predicates and approvers.

Continue the run that drafted a release through platform validation, G5, G6 and the portal submit step; a person logs in and decides.

## Procedure

1. Read `core/lifecycle/` for the machine that owns this transition, and the
   `procedure` file named on the source state.
2. Read the `x-wgf` block of every artifact schema this transition produces or consumes.
3. Check the transition's guards before acting. A guard that cannot be evaluated is a
   blocker to report, not one to assume.
4. Follow `codex-web-game-plugin/agents/release.md`.
5. Record the outcome: artifacts at their `repo_path`, and the title's `state.json`.

Commands map to transitions rather than to stages, so this file stays correct as long as
the machine does.

## The portal publisher (as built)

Read `docs/publish-module.md` and Part 0 of `docs/portal-publishing-architecture.md` before
acting. They, the publication profiles in `core/reference/publication/` and the step's own
records are authoritative over this section. Where `python3` is not on PATH (Windows), use
`python` in its place.

- **Run it in the run that drafted the release.** `bin/wgf publish --run <run-id>` continues
  that run through platform validation, G5, G6 and the portal submit step. `--platform <id>`
  (repeatable) acts on that platform only; `--track` reads every known game's status on its
  portal and clicks nothing. Start it in the background: a visit waits for a person. Report
  each platform from its own `platform-publication` record.
- **The executor is the only browser actor.** Never open, click, type in or read a portal
  page yourself, with Playwright MCP or any other browser tool. A drifted step is answered
  only by the adaptive resolver under the executor's checks (`factory.publish.adaptive`, off
  by default) - never by you, and never for an irreversible or human intent.
- **WAITING_FOR_HUMAN_LOGIN.** The portal's console is open in a headed browser window. Tell
  the person to log in there and to handle any CAPTCHA, second factor or anti-bot check
  themselves. Never ask for, accept, type or store a password, one-time code, cookie, session
  or token; refuse one if it is offered. A timed-out login or a closed window is a wait, not
  a failure: `bin/wgf resume <run-id>` opens the window again.
- **G5, G6 and WAITING_FOR_HUMAN_SUBMIT_CONFIRMATION are a person's.** Never run
  `bin/wgf decide` for a gate, a submit confirmation or a declaration; hand the person the
  line to type. G5 is `approve` or `reject`; G6 is `publish` or `reject`, pinning the
  release-manifest, the build and the store listing by hash (anything changed after it is
  `g6-stale`). After UPLOAD_COMPLETE the person types `bin/wgf decide <run-id> submit`
  (request review once), `hold`, `abandon` or `done` (requested by hand), with
  `--note platform=<id>` to name the platform. Terms, legal fields, declarations, age
  rating, tax, payout and prerequisites stop for the person (HUMAN_REQUIRED); so do
  `duplicate-candidate`, `review-pending` and `drift-irreversible`.
- **Live is opted into twice, by a person.** The step is a dry run unless the installation
  sets `factory.publish.mode: live` and the environment `WGF_PUBLISH_LIVE=1`. Never set
  either, and never record a portal's `terms_confirmed`: that is a person's finding.
- **Create-before-build (Y8).** IDS_ISSUED means the portal issued its Game ID and App ID on
  create. The run routes back to `sdk`, rebuilds that platform and asks G5 and G6 again
  before any upload. Report it; never edit `game.config.yaml` or the registry by hand.
- **Observe a real console before trusting a profile.**
  `python3 "scripts/wgf-publish.py" observe <platform> --checkout <game-checkout>` opens the
  console; the person logs in and uses it, and the observer only records. Then read
  `python3 "scripts/wgf-publish.py" observe-summary <dir>` and propose corrections to the
  platform's file in `core/reference/publication/` from observed or documented facts only:
  a reviewed change with a version bump, unknowns kept listed. An observation is never a
  login, an upload or a submission.
- **The portal registry.** `python3 "scripts/wgf-publish.py" registry show <title> [--json]`
  lists each platform's portal game. `registry associate <title> <platform> <portal-game-id>
  --note "why"` links a game a person made by hand: run it only with the id the person gives.
- **Drift review.** `python3 "scripts/wgf-publish.py" drift-review <run-id>` lists the
  adaptive mode's resolutions as proposed profile patches. A person reviews them; never apply
  one to a profile in place.
- **Report readiness in the publisher's vocabulary.** IMPLEMENTED, FIXTURE_VALIDATED,
  DRY_RUN_VALIDATED, REAL_CONSOLE_VERIFIED, REAL_UPLOAD_VALIDATED, SUBMITTED, PUBLISHED,
  UNVERIFIED, HUMAN_ACTION_REQUIRED - never "supported". A portal's state comes only from its
  own status text; never report a portal's approval.

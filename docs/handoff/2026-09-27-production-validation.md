# Production validation after v2.0.0 (2026-09-26/27)

Branch `fix/live-agent-reproducibility`, from the checkpoint `82738cf`. `v2.0.0` (`5b74e30`)
and `main` are untouched. This records what an autonomous validation attempt established,
what it fixed, and where it stopped - and why it stopped there.

**Status: production run complete up to G4, which waits for a person.** After the owner
calibrated the tech-plan estimates (below), a clean production run with human gates passed
G2 and G3 on every evaluable predicate, the live developer built the game, the live reviewer
approved it after one round of genuine fixes, the sdk commit was reviewed and approved, and
verify passed. G4 - the kill gate - is left to the owner by decision: the methodology
reserves it for a person, and its playtest-based kill criteria are unmeasured. There is no
release draft until G4 passes; release cannot run before it.

## Runs

| Run | Kind | Where it ended | Why |
|---|---|---|---|
| `new-game-20260926-192631-341e1b` | production, human gates (the stopped checkpoint run) | historical only | not resumed: machine-specific, redacted store, missing checkout (handoff note) |
| `new-game-20260926-202029-b4b70c` | **production**, `live.py config --human-gates` | **BLOCKED: G3 rejected** | `plan_fits_timebox` RED (below) |
| `new-game-20260926-205648-56b277` | live build test (G2/G3 auto-approved by the test configuration) | CANCELLED at sdk-review | two sdk bugs found and fixed; a cancelled run cannot resume |
| `new-game-20260927-044345-3c20a0` | live build test, on the fixed commit | **WAITING at G4** | G4 is a person's decision (below) |
| `new-game-20260927-123223-371104` | **production**, human gates, calibrated estimates (`6bc18cf`) | **WAITING at G4** | G4 is the owner's (below); no operator action in this run |

Every run: the pinned template `bca41a9`, the developer and reviewer argvs from
`workspace/config/factory.yaml`'s documented examples verbatim (Claude Code 2.1.283,
`--model sonnet`; developer 400 turns / US$40 / 5400 s per session, reviewer 60 turns / US$5),
plus a run budget `develop.budget: {max_sessions: 6, max_cost: 120, cost_from: {jsonl_key:
total_cost_usd}}`. Playwright ran through a shim mapping the template's build 1243 to the
installed 1194 (the container forbids `playwright install`).

## Strategy and design are now the same game

The stopped run's G3 note recorded that its design (a 7x7 swap-and-match level game) was not
the strategy's game (drop numbered pieces onto a seven-column track; neighbours merge). Root
cause and fix are in CHANGELOG `[Unreleased]`: archetype selection by genre keyword, a
single "merge" shape, and no rule comparing design and strategy. After the fix both golden
concepts get their own design (`drop-merge`, `arena-dodge`), and two blocking consistency
rules refuse a design that drops or adds a core mechanic. In production run `b4b70c` the
design passed all 12 rules of design-consistency 1.2.0, including both concept rules.

## G2 approved, G3 rejected (production run `b4b70c`)

Decided by the operating agent under the repository owner's written delegation (approve G2
only if the strategy is coherent and meets the documented constraints; approve G3 only if the
design implements the strategy and passes every check); the records say so in their notes.

- **G2 approved.** `kill_criteria_defined` and `timebox_set` hold; concept, core loop and
  MVP describe one game; exclusions explicit; Poki the only required platform.
- **G3 rejected.** Design fidelity held, but G3's own required predicate
  `plan_fits_timebox` is RED: the tech plan estimates 20.0 days (M1 15.5, M2 1.0, M3 3.5)
  against 10.5 allowed (`timebox_days` 7 x `overrun_tolerance` 1.5). The strategy recorded
  the assumption that the research estimate of 7 days holds for the MVP and named this guard
  as what would falsify it. `core/lifecycle/stages/tech-plan.md`: "approving a design whose
  plan does not fit the timebox decides nothing"; `strategy.md`: an overrun "cuts the design,
  not the calendar". Fitting the estimates or the timebox to pass would be the "fitted"
  failure mode the methodology names. The stopped run's G3 had been approved over 18.0 vs
  10.5 because the overrun was only in the event log; `wgf` now prints it.

**Decision needed (portfolio owner), then a new clean production run:** one of
(a) re-estimate the opportunity (the catalog's `dev_speed_days` for this concept) so the
strategy's timebox reflects it; (b) calibrate `factory.techplan.estimates` for this
installation from evidence (the live builds below built the whole MVP in roughly 1.5-2.5
agent-hours); (c) cut the strategy's MVP scope. Then:
`python3 scripts/golden/live.py config --workdir DIR --human-gates` and
`bin/wgf new-game --config DIR/factory.yaml --store DIR/factory-store --project tower-merge-rush`.

## Calibration (the owner's decision on G3)

The owner chose option (b). Evidence: live build `3c20a0`'s `events.jsonl` - develop
5401 + 285 + 300 + 601 + 601 s and review 337 + 110 s = **2.12 agent-hours** for M1 (CORE-001
and the 14 MVP features), which the default heuristic puts at **87.5 h**. Rule, fixed before
computing it: f = K x measured / heuristic with K = 4 for the gate time, playtests and rework
the agent clock does not see; f = 0.097, rounded to 0.1 and applied to every hour constant
(`hours_per_day` stays 6). Written to `workspace/config/factory.yaml` with this derivation.
It is not fitted: any K from about 1 to 40 clears 10.5 days. Limits: one concept, one run;
recalibrate as runs accumulate.

## The production run (`new-game-20260927-123223-371104`, commit `6bc18cf`)

| Step | Result |
|---|---|
| strategy | field-for-field the strategy approved in `b4b70c` |
| G2 | approved (same judgement and record note as before) |
| design, tech-plan | design-consistency 1.2.0 pass, 12/12 rules including both concept rules; plan 2.5 days (M1 1.5, M2 0.5, M3 0.5) |
| G3 | approved: `design_consistent` GREEN, `engine_selected` GREEN, `plan_fits_timebox` GREEN (2.5 vs 10.5); `asset_manifest_present` not evaluable in-run (the manifest is made after G3, gates.yaml) |
| init, assets | done |
| develop visit 1 | attempt 1 failed conformance (`src/main.ts` imported `@wgf/pixi-framework` and kept `BootScene` - the same two findings as in `3c20a0`; the brief's rule is now explicit); attempt 2 committed `68c7e7b`, all 7 checks green |
| review 1 | request-changes, 2 blockers: score awarded on drops with no merge (the design scores merges only); a hidden tab did not pause the session |
| develop visit 2 | committed `9788f2e`, checks green |
| review 2 | **approved** `9788f2e` |
| sdk | committed `dabaaac`; poki required, working |
| sdk-review | **approved** `dabaaac` |
| verify | **PASS**: 41/45 PASS, 0 FAIL, 4 WARNING (placeholder assets; optional-platform screenshots); all 10 gameplay aspects PASS; QA pass; poki `ready`, evidence PASS_MOCK, portal BLOCKED_EXTERNAL |
| G4 | **WAITING** for the owner |

Developer cost US$14.13 (three sessions: 11.07 + 1.92 + 1.14, all reported); four reviewer
sessions, each bounded at US$5. No operator action on the checkout; no gate decided against
its predicates. The game checkout and run store are in this session's scratchpad.

To finish the production run (owner): play the build, judge the four kill criteria, then
`bin/wgf decide new-game-20260927-123223-371104 pass|iterate|kill --note ...` with the run's
`--config`/`--store`; `pass` runs release to a local release draft (nothing is published).

## Live developer and reviewer (live build `3c20a0`, commit `ba9860c`)

| Step | Result |
|---|---|
| develop visit 1 | 4 sessions: 1 timed out at 5400 s (work kept in the checkout); 1 refused for a scratch file left in the repository root (brief fixed, file removed as the step instructed); 1 failed conformance (engine imports outside `src/rendering/pixijs/`, template BootScene still started) and fixed it on retry; committed `36902e3`, all 7 develop checks green |
| review 1 | request-changes, 2 blockers: pause-menu Restart left the pause overlay over a running game; result-card async re-entrancy |
| develop visit 2 | committed `5db43b4`, checks green |
| review 2 | **approved** `5db43b4` |
| sdk | integrated and committed `8c15051`; poki required, `working` |
| sdk-review | **approved** `8c15051` (the commit that ships) |
| verify | **PASS**: 45 checks, 41 PASS, 0 FAIL, 4 WARNING (asset placeholders; optional-platform screenshots); all 10 gameplay aspects PASS in the browser; poki readiness `ready`, evidence PASS_MOCK, portal BLOCKED_EXTERNAL |
| G4 | **WAITING** |

Developer cost: US$4.10 known (sessions 2-5) plus session 1, killed at the Factory's timeout
before the host reported a cost (bounded by the host's US$40 per-session flag); reviewer 3
sessions, each bounded at US$5, cost not reported in text mode.

Live build `56b277` (commit `1515404`), for the record: the developer built the game
(US$24.30, 61 min) but ran `pnpm format:write` as the brief said and rewrote 20 template
files - refused; after the brief fix it committed (US$0.84), review requested 8 genuine
game-feel blockers, the developer fixed them (US$3.14), review approved. sdk then failed on
two Factory bugs (placement id read as the wrong moment; duplicate plan entries, found by the
live sdk-review). The run was cancelled to stop a developer visit routed at a Factory-owned
file - a cancelled run cannot resume; a pause would have kept it.

## Why G4 is not decided

`core/lifecycle/stages/prototype-review.md`: "G4 never auto-approves. Killing a concept is
not a decision an AI makes unattended"; the decision-record schema enforces `mode: human`.
Two of the four kill criteria - first-time players understand the control; players retry
unprompted - need playtest data no pipeline run produces, and "an inconclusive on a central
question is an argument for iterate, not for pass". So G4, and therefore the release draft,
waits for a person. The live build's G3 was also auto-approved by the test configuration over
the same RED timebox predicate, so no release from that run would be production evidence.

## Factory fixes made on the way (all with regressions; CHANGELOG `[Unreleased]`)

1. Design follows the strategy's concept: archetypes, signature selection, two blocking
   concept rules (`6333f42`).
2. Step warnings printed in the console, so G3's overrun is visible; a one-word strategy MVP
   item no longer becomes a duplicate feature (`94bec60`).
3. Clean-machine golden warm-up resolves without the lockfile and proves the offline
   resolution (`1515404`).
4. The brief no longer asks for a whole-repository format (`2f5136a`).
5. The sdk step maps a game's call with the design's own placement id to that touchpoint's
   moment (`b58b54c`), and plans one placement per kind and moment (`6ae9744`).
6. The brief says scratch files stay out of the checkout (`ba9860c`).
7. The brief names the two `src/main.ts` conformance rules both live builds broke (this commit).

## Safety boundaries observed working

- The develop commit boundary refused three builds (20 template files reformatted; a scratch
  file; conformance violations) and committed nothing each time.
- Guarded Factory paths: during a golden run, edits made to the Factory tree were detected,
  restored and the step failed - the Factory's own protection, observed from the outside.
- Every commit that shipped was reviewed by the live reviewer (review and sdk-review), and
  verify's lineage accepted it. No agent process was left running after a timeout or cancel.
- Operator actions on game checkouts were limited to what a refusal message instructed, each
  logged in the run's evidence (`operator-*.txt`).

## Validation of the branch

On `ba9860c` (the commit before this record):

| Check | Result |
|---|---|
| `check-integrity.py`, `wgf-hash.py --check workspace/`, `gen-adapters.sh` | OK, OK, no diff |
| `WGF_AJV=1 python3 -m unittest discover scripts/tests` | 1549 OK, 26 skipped |
| timing tests (chatty child; every-status run) x5 | 5/5 |
| `WGF_GOLDEN=1 bin/wgf test-core --strict` | exit 0: 9/9 PASS, 2D and 3D 10/10 |
| the same from an empty HOME (`1515404`) | exit 0: 9/9 PASS, 2D and 3D 10/10 |

## Not covered

- The exact Playwright build (shim 1243 -> 1194).
- Portal behaviour (BLOCKED_EXTERNAL by definition); playtest-based kill criteria.
- The run stores and game checkouts lived in a session scratchpad of an ephemeral container;
  they are not in this repository (game source never is). This record, the CHANGELOG and the
  commits are the durable evidence.

# Factory 2.0.0 — release record

2.0.0 is the release after 1.1.0 ([v1-usable.md](v1-usable.md)). It carries the
architectural audit that followed 1.1.0 (Waves 1–3, modules M1–M13), the game production
workflow (the `core/craft/` playbooks, adapter binding 1.2.0, follow-ups F1–F7), and the fixes
from the release audit of the candidate. This page is the record of what was validated, on
which commit, and what the evidence does not cover. What changed, and how to upgrade, is in
[CHANGELOG.md](../CHANGELOG.md) under 2.0.0: **Breaking** and **Upgrading from 1.1.0** come
first.

It is a major version because defaults a 1.1.0 installation or script relied on changed:
- the agent environment is an allowlist;
- the development commit is scoped;
- a release no review approved is refused;
- `wgf status` exits as the run;
- `new-game --mock` stops at G4.

Each has a configuration or command that keeps things working. No schema's required fields
changed, and an artifact written by 1.1.0 still validates.

## Pins

| | |
|---|---|
| Factory | `VERSION` 2.0.0 |
| Template | web-game-template `v1.1.0` (`bca41a97665f8a32d0f803d46a7bbd001ac94d41`), unchanged since 1.1.0 |
| Workflow | `new-game` version 2; `gates.yaml` 1.1.0 |
| Adapters | binding 1.2.0; Claude plugin 0.4.0 |
| Template contract | `CONTRACT_VERSION` 1.0.0 |

## The release audit

The first candidate (`aff77a8`) was audited read-only before release. Three blockers were
found and fixed, each with tests that fail on that candidate:

- **Links in the checkout (B1).** The Factory wrote its own files into the game checkout
  through links a developer could leave there. They are now written by
  `wgf_develop/safewrite.py`.
- **The event log (B2).** A step's process could append a forged budget raise that the
  resume nonce corroborated, or truncate the log. The engine now seals a driven run's
  `events.jsonl` and puts back anything another process wrote there (`EVENT_LOG_RESTORED`).
  Negative costs are rejected.
- **The release notes (B3).** They did not identify the breaking changes. The CHANGELOG now
  has Breaking and Upgrading sections.

## Validation

Run on the release commit `3f8d065` (2026-09-26), the whole ladder, one stage after
another:

| Check | Result |
|---|---|
| `python3 scripts/check-integrity.py` | OK |
| `python3 scripts/wgf-hash.py --check workspace/` | OK |
| `bash scripts/gen-adapters.sh` | no diff |
| `python3 -m unittest discover scripts/tests` | 1520 OK, 36 skipped. The same 1520 also pass on Python 3.10 and 3.13 (`085ce9b`, the same code) |
| `bin/wgf test-core` | OK, 621 tests (the golden categories skip without `WGF_GOLDEN=1`) |
| `bin/wgf new-game --mock`, `bin/wgf decide <run> pass` | exit 3 at G4, then COMPLETED; `wgf status` shows `new-game (v2)` |
| `WGF_GOLDEN=1 bin/wgf test-core --strict` | exit 0. All nine categories PASS: WORKFLOW 216/217, AGENTS 33/36, CONTRACTS 131, VERIFY 22, RELEASE 48/49, **2D GOLDEN 10/10**, **3D GOLDEN 10/10**, PROCESS CLEANUP 32/34, SECURITY 112 |
| The two timing-sensitive tests (`SilentChildInAStep.test_a_chatty_child_stays_running`, `LifecycleSeparation.test_a_run_ending_in_every_status_leaves_title_state_alone`) | 5/5 each, run alone |

The 7 tests skipped inside passing categories are all opt-in:
- the live agent developer and reviewer (2);
- ajv validation of emitted reviews and decision-records (2, `WGF_AJV=1`);
- the template's release scripts (1);
- the live Playwright smoke (2).

The same ladder passed on `a38a5fc` (the release-audit fixes) and on `5b6ff1d`, the code of
the first candidate `aff77a8` (which added only a handoff document).

## Pre-publish checks (2026-09-26)

The checks this record recommended before publishing were run on `main` + fixes
(`claude/dazzling-faraday-duexam`, `b68d46e`). They found three defects, fixed before the tag:

- **The live reviewer's verdict (`7c84c45`).** With the gameplay lens (F2), a reviewer reports
  findings about the build as a whole, but the contract example showed only a file-anchored
  blocker. The live reviewer twice left `file` out of such a finding, or wrote a `line` it did
  not have, and the strict parser discarded a real request for changes. The example now shows
  both kinds of finding, and `line: null` reads as no line. A missing `file` stays malformed.
- **The live loop test (`e397ba6`)** still expected the last review to see the last
  development commit. Since M7 the last review is sdk-review, of the shipped sdk commit. It now
  asserts that, as the scripted loop test does.
- **The golden runs on a clean machine (`64ab344`, `b68d46e`).** From an empty HOME both golden
  runs failed at develop: the replay's offline install of the engine package needs registry
  metadata a frozen install never caches (`ERR_PNPM_NO_OFFLINE_META`). The runs recorded above
  had passed on a store warmed by hand. The harness now warms the store itself, online, before
  its offline sandbox (`harness.warm_store`).

**Live agent host.** Claude Code 2.1.283 was the host, on haiku, with the shipped developer and
reviewer argvs (`workspace/config/factory.yaml`: every restriction flag unchanged; turn and
budget caps lowered for cost). The developer prompt was the documented smoke-test recipe
(claude-capabilities.md), with the reviewer told that only `src/game/score.ts` is under review.
- **The allowlisted environment carries the host's login.** It authenticated with
  `factory.agents.env_passthrough` empty: this container's host auth rides on the proxy
  variables the allowlist keeps, and a CLI logged in on a workstation keeps its credentials
  under `HOME`, which the allowlist also keeps. An API-key setup names `ANTHROPIC_API_KEY` in
  `env_passthrough`.
- **`LiveDeveloperAndReviewer`: 3 of 3 passed.** The real host edited, the Factory made the
  scoped keyed commit, the real reviewer requested changes on the planted bug, the host fixed
  it, review approved, sdk-review approved the shipped sdk commit, and the run COMPLETED. Every
  review had isolation intact, and no process was left behind.
- **`LiveReviewer`: 2 of 3 passed.** In the third, the reviewer accepted the underflow fix but
  held a second finding against `score.ts` - the stub still scores by lives while the brief's
  MVP asks for combo scoring. That is the design-fidelity lens judging the stub fixture against
  the design, not a contract or pipeline failure.

**Clean machine.** `WGF_GOLDEN=1 bin/wgf test-core --strict` from an empty `HOME` (no
template cache, no pnpm store, no sibling template): the pinned template and the golden ports
were cloned from GitHub, and the store was warmed by the harness.
- **On `b68d46e`, two consecutive full runs passed:** exit 0, 9/9 categories, 2D and 3D golden
  10/10. So did a separate 2D-then-3D run from another empty HOME.
- **One earlier full run on the same commit failed the 3D golden run at develop.** Its evidence
  was not kept, and the failure has not recurred since.
- **The one remaining local deviation** is the browser: Playwright's own browser download is
  not available here, so a `PLAYWRIGHT_BROWSERS_PATH` shim maps the build the template expects
  (1243) onto the installed Chromium (1194).

**Opt-in suites.** All ran and passed:
- `WGF_AJV=1` on the whole unit suite: 1522 OK, the ajv cross-checks agreeing with the stdlib
  validator;
- `WGF_LIVE_PROCESS_TEST=1`: the template's Playwright smoke leaves no process behind, 2/2;
- `WGF_TEMPLATE_RELEASE_TEST=1`: the template's real release scripts package a valid,
  reproducible draft.

**Final ladder.** The whole ladder was run again on `54bc80e`, the pre-publish fixes plus this
record:
- integrity, content hashes and adapter regeneration clean;
- unit 1522 OK / 36 skipped;
- mock smoke through G4 to COMPLETED;
- `WGF_GOLDEN=1 bin/wgf test-core --strict` exit 0, 9/9, 2D and 3D golden 10/10;
- the timing-sensitive tests 5/5.

The plain `bin/wgf test-core` run failed once, on a rounding-boundary assertion in the hung-
output liveness test: the verdict is decided on the exact idle time, the report is rounded
to the millisecond. The assertion was corrected (`6423155`), 5/5 alone, and `bin/wgf
test-core` was OK on that commit.

## What the evidence does not cover

- **The exact Playwright browser build** the template pins was not run; the shim stood in (above).
- **The opt-in design agent (F4) and developer self-playtest (F6)** are verified offline only
  ([claude-capabilities.md](claude-capabilities.md)).
- **The live runs used haiku and the smoke-test prompts,** not a full game build with the
  shipped prompts; the 1.1.0 acceptance run did that (v1-usable.md).
- **Portal behaviour, submission and publishing** remain outside the Factory (BLOCKED_EXTERNAL,
  behind G6).

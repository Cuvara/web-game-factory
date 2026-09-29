# 3D benchmark

How to measure whether a change to the 3D developer capability helped, and what it cost.
The protocol is here; the results are not, because nobody has run it yet. **Do not fill in a
row you did not measure.** An unmeasured cell is `—`, not an estimate.

The one thing that *is* measured today is the regression baseline: the 3D golden run, which
proves the workflow, the gates and the step outcomes did not move
([golden-runs.md](golden-runs.md)).

## What this is not

The golden runs are **not** a benchmark of the developer. Their developer is
`scripts/golden/replay_developer.py`, a deterministic port of a known-good example: it
proves the Factory's plumbing, and it would produce the same result if the brief said
nothing at all. Measuring whether the brief and the craft playbooks help needs a real
`command` developer, which costs agent sessions and needs a host configured in
`workspace/config/factory.yaml` (`factory.develop.developer`). That is a deliberate,
spend-bearing run a person authorises; see the budget section of
[development-module.md](development-module.md).

## The shapes

Seven game shapes, chosen because each one first exercises something the previous ones do
not. Run them in this order; a failure in an earlier shape makes a later one hard to read.

| # | Shape | First exercises |
|---|---|---|
| 1 | Simple arcade (primitives only, no loaded assets) | Scene, loop, input, restart — the floor |
| 2 | GLB-loading (one imported model, no animation) | Loader wiring, decoder payload, scale/pivot checks |
| 3 | First person | Camera as the control surface, pointer handling, motion comfort |
| 4 | Third person | Camera rig, occlusion, the framing at the portrait viewport |
| 5 | Physics interaction | The physics rung the tech plan pinned, fixed step, sensors, restart cleanup |
| 6 | Enemies | Spawning, pooling, per-entity state, draw-call growth |
| 7 | Animation-heavy | Clips, blending, root-motion ownership, mixer disposal |

Each shape is one `new-game` run with a real developer, from a design that asks for that
shape and nothing more. Keep every other input constant between runs of the same shape —
the same template pin, the same platform set, the same device classes — or the numbers
compare nothing.

## What to record, per run

Read every number from the run, never from memory.

| Measure | Where it comes from |
|---|---|
| Developer sessions, and cost | `STEP_LOG` `data.budget` lines in the run's `events.jsonl` |
| Develop wall time, per visit | `events.jsonl` step timestamps |
| Develop visits, and what sent it back | `brief.json` `loop` on each visit; `wgf status <run-id>` |
| Checks: which failed, on which attempt | `docs/development/checks.json` in the checkout |
| Build time, bundle size | the `build` and `bundle` verification checks |
| Asset load: bytes and requests on first play | the `assets.loading` check; the browser evidence |
| Draw calls, triangles, geometries, textures | the counters the `@boot` test logs (see the brief's Tests section) |
| Gameplay aspects proved | `verification-report`, `gameplay` checks |
| Verification result and blocking defects | `verification-report`, `qa-report` |
| Repair iterations to green | develop visits entered by `verify.fail` or `review.request-changes` |
| Human interventions | every `WAITING_FOR_HUMAN` and every decision record |

Record the Factory commit, the template pin (`workspace/config/template.lock.json`), the
developer host and its version, and the date. A benchmark without its pins is an anecdote.

## Reading the result

- **Repair iterations and human interventions are the headline.** They are what the craft
  playbooks and the brief are supposed to reduce. Sessions and cost follow them.
- **A shape that never reached `verify` is a failure, not a slow success.** Record where it
  stopped and why.
- **Compare like with like.** A change to the brief is judged on the same seven designs, on
  the same template pin, with the same developer host.
- **Say what you did not measure.** A shape not run is `—`, and the report says so.

## Results

None yet. Fill this section only from runs that actually happened, one table row per
(shape × Factory commit), with the pins above alongside.

### Regression baseline

Status of the 3D craft and brief change (commit `a65d7e3`, template pin `bca41a9` / v1.1.0,
recorded 2026-09-29). Every row is what was observed, on the host named.

| Run | Command | Result |
|---|---|---|
| 3D golden | `WGF_GOLDEN=1 bin/wgf test-core --strict` | **PASS** on Linux CI (`ubuntu-24.04`, run 36514228059, commit `dd78715`): `3D GOLDEN PASS 10 10 0 0 0`. Previously NOT RUN on the Windows host (`harness.warm_store`: `FileNotFoundError: [WinError 2]`) |
| 2D golden | `WGF_GOLDEN=1 bin/wgf test-core --strict` | **PASS** on the same run: `2D GOLDEN PASS 10 10 0 0 0`. Previously NOT RUN, same blocker |
| Core suite | `WGF_GOLDEN=1 bin/wgf test-core --strict` | **PASS** on Linux CI: every category PASS, exit 0 (`OK (INCOMPLETE — 7 tests skipped in PASS categories; 639 tests)`) |
| Golden harness checks | `python3 -m unittest scripts.tests.test_golden_fast` | 23 of 25. The 2 failures (`test_developer_and_reviewer_are_the_labelled_stand_ins`, 2D and 3D alike) reproduce unchanged at pristine HEAD |
| Full suite vs pristine HEAD | `python3 -m unittest discover scripts/tests` | 1603 tests / 92 fail / 39 error on Windows against 1593 / 94 / 39 at HEAD there; failing-test names diffed, **zero new failures**. On Linux CI the same suite is **1603 tests, 0 failures** |

**The goldens ran, on Linux.** They could not run on the Windows host this branch was
developed on: `harness.warm_store` calls `procs.run(["pnpm", "install", ...])`, and there pnpm
is a `.cmd` shim the spawn cannot resolve, so both goldens died in `setUpClass` before a test
ran - on this branch and on a pristine `main` alike. The harness was not patched; a POSIX
runner was added instead (`.github/workflows/acceptance.yml`, merged as #10), and the gate
passes there.

**Branch status: implementation-complete, golden evidence recorded.** Runner `ubuntu-24.04`,
node 22, pnpm 9.15.4, commit `dd78715` (this branch merged with `main` at `031ca0e`), run
36514228059, exit code 0, both goldens PASS.

## Out of scope for this protocol

- Portal submission, live traffic and revenue. Those are release and liveops evidence.
- Visual quality scores. The Factory judges readability against the design's
  `visual_identity` and the platform budgets, not against a fixed premium bar
  (`core/craft/3d-scene-and-physics.md`).
- Comparing agent hosts. The Factory names no provider; the host is installation
  configuration.

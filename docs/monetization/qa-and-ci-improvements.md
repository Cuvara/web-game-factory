# QA and CI improvements

How to catch defects earlier, stop paying for false alarms, and keep CI fast, without weakening
the gates that matter. Grounded in:
- `.github/workflows/acceptance.yml`, `scripts/tests/`, `bin/wgf test-core`;
- `core/reference/browser-qa.yaml`, `core/reference/check-tiers.yaml`;
- the QA step modules;
- the defect record in [factory-audit.md](factory-audit.md) §3.

Labels: [C] confirmed, [I] inferred, [U] unknown.

## 1. Current state

| Layer | What runs | Strength | Gap | Label |
|---|---|---|---|---|
| Unit and contract tests | 129 files, about 4,900 tests; 4 shards in CI | broad, deterministic | - | [C] |
| Core Acceptance Suite | `bin/wgf test-core`: WORKFLOW, AGENTS, CONTRACTS, VERIFY, RELEASE, QUALITY, goldens, KNOWLEDGE, PROCESS CLEANUP, SECURITY; SKIP is never PASS | honest reporting | - | [C] |
| Golden runs | 2D and 3D in CI, 150 min each, $0 | regression of the engine and gates | **replay developer and pixel judge**: real agents and prompts are never tested | [C] |
| Template SDK tests | per-adapter unit tests, conformance matrix, browser mocks | adapters solid | `test:sdk:matrix` and the example e2e suites run in no workflow | [C] |
| Browser QA | 31 checks, 5 viewports, load and frame budgets | real browser | no landscape phone; clipping at the viewport edge only; no fault injection or throttling | [C] |
| Playability | Playwright bot, desktop and mobile; idle/act/win/lose sessions | deterministic | perfect play only; ads never exercised; false positives on slow hosts (L5, L7) | [C] |
| Visual QA | AI vision judge (paid) or pixel baseline | catches visual defects | absolute rubric cannot see regressions | [C] |
| Quality gate | aggregates every report | stale-evidence blocking | 0 of 11 human findings caught (K6) | [C] |
| Release and publish | zip audit, listing validation, fixture-validated portal adapters | - | not used for what shipped | [C] |
| Post-release | none | - | no monitoring of portal status, reviews or errors | [C] |
| CI wall clock | about 55 min in parallel (was 2.7 h) | - | goldens cannot run on Windows | [C] |

## 2. Validation tiers

Each check belongs to the cheapest tier that can catch its defect.

| Tier | When | Budget | Contents |
|---|---|---|---|
| **Local fast** | every edit | under 2 min | `check-integrity.py`, affected unit tests, `wgf-hash --check` |
| **Pull request** | every PR to main | under 60 min | full units (4 shards), test-core without the goldens loop, goldens 2D/3D, template contract drift |
| **Release validation** | per game release candidate | per game, minutes | every target's own build through: browser QA (new viewports, fault injection), bot ad lifecycle, per-target ad gate, full-unit solvability, size limits, portal audit scripts |
| **Agent canary** | weekly or before a Factory release, opt-in | capped spend (for example US$20) | one real-agent run of a small fixed concept through design, develop and verify; compared against the last canary |
| **Post-release** | daily while a title is in review or launch | none (reads) | `wgf publish --track` read-only status; manual portal export reminders |

## 3. Proposals

### Q1 Browser QA: the viewports and failures that escaped

- Add landscape phone viewports 844x390 and 640x360 to `browser-qa.yaml` (D1 escaped).
- Add a check that text fits its own control, not only the viewport (D1).
- Add fault injection: fail one same-origin asset request once and expect recovery or a retry UI
  (D2 escaped).
- Add throttled loading (a 4G-like profile) for the load-time budget, and record it separately
  from the unthrottled figure.
- **Cost:** CI minutes per release, no paid calls. **Tier:** release validation.

### Q2 Bot-exercised ads on every target build

- Playability requests one interstitial at a beat and one rewarded offer, on each target's own
  build, against that portal's SDK mock.
- It asserts:
  - the request is made, at a beat, never during play;
  - the pause follows the profile's pause scope;
  - the reward is granted only on completion;
  - a spent offer disappears.
- This covers the four ad defects in the audit.

### Q3 Per-target ad hard gate

- Derived from the profile, not from the design's placements, so the check is not circular.
- See [monetization-and-distribution.md](monetization-and-distribution.md) C3 and
  [implementation-roadmap.md](implementation-roadmap.md).

### Q4 Accepted-baseline regression gate

- Compare a candidate build with the person-accepted build (r1): content counts, course lengths,
  pairwise visual judgement.
- Promote the pairwise judge (#77, advisory today) to a Quality Gate at the release tier.
- K6 showed that absolute floors allowed "gates pass, game worse".

### Q5 Confirm before routing

- A finding drives a paid repair only if it is reproduced by a second, independent measurement:
  a repeat bot run, or a different method.
- Timing-sensitive checks report a confidence interval.
- This addresses L5, L7 and the `depth.ramp` noise that caused a progression regression.

### Q6 Release path mandatory for submissions

- Anything uploaded to a portal must come from a release-manifest produced by the release step.
- That step covers per-platform packages, verified and recorded.
- A supported `wgf release --platform <id>` path that does not need a full run replaces the hand
  scripts (`runs:release-prep-2026-10-18/*.py`).

### Q7 Agent canary

- The goldens prove the engine with a replay developer. Nothing proves that prompts and briefs
  still produce working games.
- A small canary closes this, without making PR CI cost money:
  - opt-in;
  - budget-capped;
  - one fixed tiny concept;
  - run weekly;
  - result compared with the last canary.
- Requires a person to authorize the spend.

### Q8 Template coverage

- Add `test:sdk:matrix` and the example e2e suites to the template's CI.
- Add a test that grants a reward in each example.

### Q9 Windows parity (developer experience)

- Make `wgflib.procs` resolve `pnpm.cmd` on Windows, so goldens can run locally.
- Linux CI remains the gate. This is a core change and needs a stated reason: local validation
  before paid runs.

## 4. Parallelism and dependencies

| Safe in parallel | Must be sequential |
|---|---|
| Unit shards; 2D and 3D goldens; per-target release builds; browser QA viewports | Template pin move then goldens; design then tech plan; develop then review then verify; release then publish |
| Portal audits per target | G5 then G6 then submit |

Ordering note: review after verify, not before. A request-changes loop before verify deadlocked a
run (`runs:LEAD-STATE.md:30`).

## 5. CI cost and time

- PR CI is free of paid calls and should stay so; the goldens' replay design is right for PRs.
- The golden-loop job stays opt-in by label.
- Release validation runs per game, not per PR.
- The agent canary is the only paid automated check, capped and opt-in.

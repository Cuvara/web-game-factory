# End-of-day checkpoint — 2026-10-10 (K5 merged, K6 PR #61, K7 branches, template 1.2.1 candidate)

Location chosen: `docs/handoff/` (the repository's existing hand-off convention; no `docs/operations/`
exists). Branch `ops/checkpoint-2026-10-10` (local only, not pushed).

**Last verified: 2026-10-10 17:30 UTC (2026-10-11 00:30 ICT, UTC+7).** Everything below marked VERIFIED was
read from git, `gh`, the file system or a command run at that time. CLAIMED = reported by an agent and not
re-run by the Lead. UNKNOWN = not established.

## 1. Executive summary

- **Merged:** K5, PR #60 → `main` at merge commit `65eb86a` (2026-10-10 14:40 UTC). VERIFIED.
- **K6, PR #61** (`k6/closed-loop` @ `17ae495`, base `main`) has three independent review rounds passed
  (r1 changes fixed, r2/r3 PASS WITH NITS, nits fixed). Its PR CI run 38060673361 is **completed: success**,
  all three jobs, including both GOLDEN LOOP jobs. VERIFIED. **Not merged.**
- **`main` CI after the K5 merge**, run 38060543038: **completed: success** (finished about 17:30 UTC). VERIFIED.
- **Template SDK fix:** `backport/1.2.0-platform-sdk` @ `4b74b08` on `Cuvara/web-game-template`, pushed.
  Independent review round 2: PASS, "fit to tag v1.2.1 and pin" (CLAIMED by the reviewer, report on disk).
  **Tag `v1.2.1` does not exist** (VERIFIED: only `v1.2.0` on the remote).
- **Factory PR #62** (draft, `k7/template-1.2.1` @ `7424689`) temporarily pins the template to
  **commit `4b74b08` with `ref` = the branch name**, only so Linux CI runs both goldens on it.
  **DO NOT MERGE.** Its CI run 38066953703 is in progress.
- **The four K7 implementation tasks are all stopped, with their work committed locally (not pushed).**
  None is reviewed to PASS yet:
  - comparison with the accepted version: `k7/baseline-compare` `43c4554`;
  - cheating-check detection: `k7/measurement-integrity` `3e8d25f`;
  - triage fixes: `k7/triage-hygiene` `2d4b3af`, `2ebe5f7`;
  - platform preflight fixes: `k7/platform-preflight` `d4f31c9`, `88db3f9`, `ed3bca8`.

  Two reviews were stopped mid-way, at end of day, with PARTIAL reports:
  - the triage review is tentatively **CHANGES REQUIRED**;
  - the preflight review has no verdict yet.
- **Spend today: $0 metered.** No paid run, no LLM judge, no `/new-game`. The paid real-game comparison is
  **not authorized** and was not run. Both games remain at or near their US$250 caps (no raise authorized).
- **Blocked on a person:**
  - the `v1.2.1` tag;
  - merging #61, #62 and the K7 branches;
  - any paid game work: 2D re-plan G2/G3, both games' sdk/develop, G4/G5/G6;
  - publishing (blocked).

## 2. Verified Git state (2026-10-10 17:15–17:30 UTC)

Factory repository `Cuvara/web-game-factory`; `origin/main` = `65eb86a`.

| Worktree | Branch | HEAD | Upstream | Tree |
|---|---|---|---|---|
| `C:/Workspaces/WebGameFactory/web-game-factory` (main checkout) | `main` | `c46173f` (behind origin/main; not pulled) | origin/main | untracked `.claude/` only; **stash@{0}** "On main: crlf-only line-ending noise (content identical to HEAD)" — pre-existing, leave it |
| `C:/Users/duycu/wgf-spec/k6` | `k6/closed-loop` | `17ae495` | origin/k6/closed-loop (pushed) | clean |
| `C:/Users/duycu/wgf-spec/k7-baseline` | `k7/baseline-compare` | `43c4554` | none — **not pushed** | clean (untracked `.claude/` not committed) |
| `C:/Users/duycu/wgf-spec/k7-integrity` | `k7/measurement-integrity` | `3e8d25f` | none — **not pushed** | clean |
| `C:/Users/duycu/wgf-spec/k7-triage` | `k7/triage-hygiene` | `2ebe5f7` | none — **not pushed** | clean |
| `C:/Users/duycu/wgf-spec/k7-platform` | `k7/platform-preflight` | `ed3bca8` | none — **not pushed** | clean |
| `C:/Users/duycu/wgf-spec/k7-tpl121` | `k7/template-1.2.1` | `7424689` | origin (pushed; PR #62) | clean |
| `C:/Users/duycu/wgf-spec/ops-checkpoint` | `ops/checkpoint-2026-10-10` | this document | none — not pushed | this file only |

All four K7 branches start at `29d22de`, an earlier K6 head that is an ancestor of `17ae495`. They are
**independent of each other**, so expect conflicts in CHANGELOG, `check-tiers.yaml`,
`quality-assessment.yaml`, `lessons.yaml` and the runtime manifest when integrating; regenerate the runtime.

Template repository `Cuvara/web-game-template`:

| Worktree | Branch | HEAD | Upstream |
|---|---|---|---|
| `C:/Users/duycu/wgf-spec/tpl-backport` | `backport/1.2.0-platform-sdk` | `4b74b08` (chore(release): 1.2.1) | origin, pushed (ls-remote = `4b74b08`) |

Tags: only `v1.2.0` (`b106261`).

Game repositories (local only, no remote; read-only today):
- **2D** `C:/Users/duycu/wgf-runs/val-2d/games/brick-breaker-worlds`: `main` = `0db72b6`, clean. Tags
  `baseline-r1` (96f5cea) and `regressed-head-68a12b7`.
- **3D** `C:/Users/duycu/wgf-runs/val-3d/games/sky-marble`: `main` = `df1a598`. Branch `feat/release-content` =
  `43c08e2` is reviewed READY TO MERGE (2026-10-08) but **not merged**; its worktree is `C:/Users/duycu/wgf-spec/sm-content`.
- Many scratch detached worktrees exist under `wgf-k7x/`, `wgf-review-k7/`, `wgf-spec/k7-tmp/` (listed in §9).
  They hold no unique committed work.

## 3. The four K7 agents

| # | Task | Branch / location | State | Evidence | Next action |
|---|---|---|---|---|---|
| 1 | **Comparison with the accepted version** (`baseline.*` playability checks; plan #1) | `k7/baseline-compare` `43c4554` (48 files); notes `wgf-spec/k7-tmp/baseline/CHECKPOINT.md`; raw recordings `k7-tmp/baseline/keep/` | **STOPPED, committed, not fully verified.** Its full unittest discover was still running at checkpoint (PIDs 30296, 18564 — the agent's own; lost on restart; must be re-run) | CLAIMED: `test_baseline_compare` 41 OK; integrity OK; runtime --check OK; the real 3D step run validates against the schema. VERIFIED: commit exists, tree clean | Re-run full discover from the worktree root, diff against `wgf-runs/k5-baseline2-failures.txt`, run KNOWLEDGE + QUALITY, then independent review |
| 2 | **Cheating-check detection** (`physics.contact_drawn` hard, `physics.drawn_extent` quality; plan #2) | `k7/measurement-integrity` `3e8d25f` (140 files incl. 111 real fixture files `scripts/tests/fixtures/real/play-contact/`); notes `wgf-spec/k7-tmp/integrity/CHECKPOINT.md` | **COMPLETED (CLAIMED), committed, not reviewed** | CLAIMED: `test_play_contact` 35/35; QUALITY 61/61; KNOWLEDGE 383/383; integrity and runtime OK; full discover no new failures (3 extra failures passed alone: 2 from a mid-run edit since fixed, 1 load-timeout flake); 6/6 mutations caught. VERIFIED: commit and fixtures exist, tree clean | Independent review |
| 3 | **Triage fixes** (#4: major judge findings on a passing report recorded as `noted`; #10: greybox playability ids carry the phase) | `k7/triage-hygiene` `2d4b3af`, `2ebe5f7`; fixture `scripts/tests/fixtures/real/triage-hygiene/` | **Implementation COMPLETED (CLAIMED). Review PARTIAL — tentative CHANGES REQUIRED** (`wgf-review-k7/triage/review.md`) | CLAIMED: test_triage 77, test_playability 280, quality modules pass; KNOWLEDGE 383, QUALITY 61, WORKFLOW only the 2 known; full discover +1 load-timeout flake. Review findings (code reading, not yet reproduced) are listed below | Resume the reviewer (reproduce the findings and run the suites), then fix and re-review |
| 4 | **Platform preflight fixes** (foreign-SDK scan, Y8 SDK-loaded, stale docs; plan #19, #20, #24) | `k7/platform-preflight` `d4f31c9`, `88db3f9`, `ed3bca8`; real fixture `scripts/tests/fixtures/portal-sdks/sky-marble-43c08e2.json` | **Implementation COMPLETED (CLAIMED). Review PARTIAL, no verdict** (`wgf-review-k7/preflight/review.md`) | CLAIMED: test_portal_sdks fails 7 + 1 error before the fix → 30/30 after; KNOWLEDGE 383, QUALITY 61, VERIFY 22; full discover on 88db3f9 found 2 own regressions, fixed in ed3bca8 (affected modules re-run, full discover NOT re-run after ed3bca8). Reviewer VERIFIED in scratch: integrity OK, runtime OK, 201 module tests with only the known failure | Resume the reviewer (rebuild sky-marble 43c08e2, false-positive probes, mutations, Y8 path, categories) |

The triage review's tentative findings, all from reading code and none reproduced yet:
1. **Major.** A `noted` record that a failing report raises through the quality gate or release path
   (`current=[]`) stays `noted`, so it doesn't block. A done noted record that gets reopened also keeps `noted`.
2. **Major.** For K6.4 strength:
   - the promotion note does not start with "reopened", so the instability cap is skipped;
   - `snapshot` reads a noted detection, which came from a PASS report, as a FAIL "before".
3. **Minor.** One history note is misleading.

The preflight review's possible findings, all unverified and low:
- The zip scan ignores root files when the zip has a single top-level folder.
- `node_modules` is skipped by the directory scan but not by the zip scan.
- Source maps are scanned.
- The Y8 ids-pending exception still needs an end-to-end trace.

Measured results the comparison agent reports for the **current candidates** (CLAIMED; real runs, not tuned):
- **2D `0db72b6` vs r1 `96f5cea`: FAIL**, with no person's recorded reason for the change.
  - Level content changed in 7 levels (w1-l7, w2-l6, w3-l1, w3-l2, w3-l7, w4-l6, w4-l7).
  - Tuning: ball radius 11→20 and `descending-field.min_interval_s` 3.8→4.
  - Two checks cannot be decided: r1 names no entity kinds, and neither build clears within the run.
- **3D `43c08e2` vs r1 `64ff4c6`:**
  - Played: PASS (held forward 19.0 s and 18.83 s vs 22.86 s).
  - Against r1's 12 courses as data: all kept. Difficulty ordering FAILS (hairpin-rise precision 0.73→0.89, speed 0.87→0.82).
- **Regressed heads fail as intended:**
  - 3D `1c6b099`: course 1 clears in 6.18 s vs 22.86 s; total length 844 m vs 4025 m.
  - 2D `68a12b7`: all 32 layouts changed; w1-l1 has 10 bricks instead of 16.
- **Calibration:** the frame-rate bar was set to 0.6, because the accepted 3D build scored 0.77 against
  itself. Frame-rate and start-time bars are calibrated on noise only.

Cheating detection (CLAIMED, real builds):
- `cbac64e` and `68a12b7` invisible ceilings FAIL; r1 PASSes `contact_drawn`.
- **r1 `96f5cea` itself FAILS ball size** (solid disc 42 px over a 22 px collider, 1.9–2.05×). The existing
  `collider_size` bar already fails it, and the agent did not loosen it.
- `894b4b8` (collider grown to 20) PASSes.
- A person must decide whether r1's ball is acceptable; record it as an accepted change, never by changing the bar.

Do not repeat:
- Do not re-measure the games for task 1; the recordings are saved.
- Do not play two builds at once on this machine (it degraded recordings).
- Use distinct visit numbers for measurement runs.
- `k7-tmp/baseline/runs/3d-accepted-A-degraded-naive` was set aside on purpose; do not use it.

## 4. CI and PR status

| Item | Head | Run | State at 17:28 UTC |
|---|---|---|---|
| `main` after K5 merge | `65eb86a` | [38060543038](https://github.com/Cuvara/web-game-factory/actions/runs/38060543038) | **completed: success** (acceptance with both goldens; verified 17:30 UTC) |
| [PR #61](https://github.com/Cuvara/web-game-factory/pull/61) K6 | `17ae495` | [38060673361](https://github.com/Cuvara/web-game-factory/actions/runs/38060673361) | **completed: success**: acceptance (goldens) success 17:14 UTC; GOLDEN LOOP greybox success 16:21; GOLDEN LOOP develop success |
| [PR #62](https://github.com/Cuvara/web-game-factory/pull/62) template pin candidate (draft, DO NOT MERGE) | `7424689` | [38066953703](https://github.com/Cuvara/web-game-factory/actions/runs/38066953703) | **in progress** |
| [PR #60](https://github.com/Cuvara/web-game-factory/pull/60) K5 | `198789e` | [37885109890](https://github.com/Cuvara/web-game-factory/actions/runs/37885109890) | merged; CI success before merge |
| Earlier K6 dispatch | `29d22de` | [38040016812](https://github.com/Cuvara/web-game-factory/actions/runs/38040016812) | success (all 3 jobs) |

PR #61 carries the label `golden-loop` (created today), which makes its CI run the two GOLDEN LOOP jobs.
`acceptance.yml` runs `pull_request` only for PRs into `main`.

## 5. Completed work today (evidence)

- **K5 merged** (#60): independent review PASS (earlier), CI green on its head. VERIFIED: merge commit.
- **K6 review r3** of the Lead's commits `c77928e` and `29d22de`: PASS WITH NITS
  (`C:/Users/duycu/wgf-review-k6/r3/review-r3.md`). Nits were fixed in `badfda7`: KNOWLEDGE 384/384 (VERIFIED,
  `C:/Users/duycu/wgf-k7x/k6-r3-knowledge.txt`) and a surviving mutant was killed (VERIFIED). Then `main` was
  merged into `k6/closed-loop` (`17ae495`): integrity OK, runtime --check OK (VERIFIED).
- **Platform audit** (read-only): `C:/Users/duycu/wgf-k7x/platform-audit/report.md`. The CrazyGames audit
  fails both candidates on pinned v1.2.0, and the Factory never runs that audit. It also found the
  `y8_sdk_present` false pass, no y8 placements, and 2D still requiring Poki.
- **Template backport** `4d4ccb7..4b74b08` fixes review findings F1–F7. Round 2 PASS
  (`C:/Users/duycu/wgf-review-k7/backport/review.md`). Template 852 tests; CrazyGames audit PASS; both games
  pass unit tests and audits with the patches (CLAIMED by the fixer and the reviewer). Pushed (VERIFIED).
- **Improvement plan:** `C:/Users/duycu/wgf-runs/k7-improvement-plan.md` (PROVEN vs HYPOTHESIS, items 1–25).
- **Shared agent rules:** `C:/Users/duycu/wgf-runs/k7-rules.md`. Running log: `C:/Users/duycu/wgf-runs/TEAM-STATUS.md`.

## 6. In-progress work and continuation points

- PR #62 CI 38066953703 is running on GitHub. It survives a local shutdown. (`main` CI 38060543038 finished green.)
- **K7 #1** (comparison): its full discover must be re-run (the local process dies on shutdown).
- **The two K7 reviews:** resume or redo from their PARTIAL files.
- **Integration of the four K7 branches:** not started. Do it after their reviews pass, on top of `main`
  once #61 is merged.
- **Plan items not started:**
  - #3: H5 control-response check, after checking whether #1 covers it;
  - #5: confirm before routing noisy checks;
  - #10b: prototype-report ids collide too;
  - #13: `depth.session_length` never triaged;
  - #14: flip-rate CI;
  - #17: budget forecast;
  - #18: meter all agent calls;
  - the `test_core_agents` reviewer-timeout flake under load (seen 3 times: 37 s and 48 s vs 30 s).

## 7. Safety and release gates

- **PR #62: DO NOT MERGE.** It may merge only after all three:
  1. A person creates tag `v1.2.1` on `Cuvara/web-game-template` at `4b74b081d48cd61ca59e9cd99c922cc474e9b9f1`.
  2. `workspace/config/template.lock.json` `ref` is changed from `backport/1.2.0-platform-sdk` to `v1.2.1`
     in #62. The commit stays `4b74b08` and `validated_on` gets the run date. Then regenerate the runtime.
  3. #62 CI is green, with both goldens, on that final commit.

  The current branch-name `ref` is a **temporary test configuration**, not the intended final pin.
- **Factory pin today on `main`:** `ref` `v1.2.0`, commit `b106261` (a release tag). Only #62 changes it.
- **Merges:** in this checkpoint session the human ordered no merges. Before merging #61 (green, reviewed)
  or any K7 branch, confirm the human's merge authorization for the next session. Earlier K6 instructions
  said "do not merge PRs without explicit authorization". The 2026-10-10 Lead instruction allowed merges
  after independent review. Treat it as needing confirmation.
- **Games:** both are at or near the US$250 cap; "no budget increases" (human, 2026-10-08) stands. No paid
  game work.
  - 2D needs a person's re-plan G2/G3 to drop the Poki requirement and add Y8.
  - The 3D `feat/release-content` merge needs the person's go-ahead.
  - G4 for both: the 3D pacing exception is recorded in `wgf-runs/g4-notes/3d-pacing-exception-2026-10-08.md`
    for a person; the 2D r1 ball-size and content-change findings above need a person's decision.
- **Publishing: BLOCKED.**
  - No portal action until release candidates pass verified acceptance and a person decides G5/G6.
  - Logins, terms, CAPTCHA and 2FA are human-only.
  - No credentials are ever requested or stored.

## 8. Next-session runbook (dependency order)

1. Read this file, `wgf-runs/TEAM-STATUS.md` (tail) and `wgf-runs/k7-improvement-plan.md`.
2. Check CI: `gh run view 38066953703 --repo Cuvara/web-game-factory` (#62 goldens on 4b74b08). `main` CI
   38060543038 was green at checkpoint; check any newer `main` run.
3. Ask the human for:
   - merge authorization for #61 (green, three reviews);
   - the `v1.2.1` tag at `4b74b08` (only if #62's goldens are green).

   Do not tag or merge without them.
4. Resume the two PARTIAL reviews: triage (`wgf-review-k7/triage/review.md`) and preflight
   (`wgf-review-k7/preflight/review.md`). Fix confirmed findings with fail-first tests, then re-review.
5. Re-run the full discover for `k7/baseline-compare` and check KNOWLEDGE/QUALITY, then send
   `k7/baseline-compare` and `k7/measurement-integrity` to independent reviewers.
6. After #61 merges and the K7 reviews pass: integrate the K7 branches onto `main` (one PR or stacked PRs),
   resolve the shared-file conflicts, regenerate the runtime and run CI with goldens.
7. Bring to the human:
   - 2D candidate baseline failures (7 levels changed; ball radius 11→20);
   - 3D difficulty-ordering failure;
   - r1's own ball-size failure.

   These are decisions (accepted change with a reason, or game work needing budget), never bar changes.
8. Only after the human tags `v1.2.1`: update #62's `ref`, re-run CI, then merge on the human's go-ahead.

## 9. Commands and context

- Windows 11 + Git Bash only (never WSL). Never kill processes by image name; only PIDs you started.
- Run Factory checks from a checkout root:
  - `python scripts/check-integrity.py`
  - `python scripts/build-plugin-runtime.py --check`
  - `python scripts/wgf.py test-core --only KNOWLEDGE` (or QUALITY, WORKFLOW)
  - full suite: `python -m unittest discover -s scripts/tests -t scripts/tests`
- Known Windows failures: `C:/Users/duycu/wgf-runs/k5-baseline2-failures.txt` (78 ids). Also known flaky
  under load: `test_core_agents.AgentLoop.test_a_reviewer_timeout_is_retried_and_its_tree_is_killed`.
  `PluginVersionTest.test_the_repository_itself_agrees` fails only when run with cwd `scripts/tests`.
- CI on a branch whose PR does not target `main`: `gh workflow run acceptance.yml --ref <branch> -f golden_loop=true`.
- Golden runs use port 4173 (one at a time). Today's agents used ports 4180–4249.
- `WGF_FFMPEG` for local goldens: the WinGet Gyan.FFmpeg path recorded in `wgf-runs/resume-3d-strategy.sh`.
- Agent notes: `C:/Users/duycu/wgf-spec/k7-tmp/{baseline,integrity,triage,platform}/`. Reviews:
  `C:/Users/duycu/wgf-review-k6/{r1..r3}`, `C:/Users/duycu/wgf-review-k7/{backport,preflight,triage}/`.
- Scratch detached worktrees (no unique committed work; keep until reviews finish):
  - `wgf-k7x/platform-audit/scratch/{factory,bbw,sm}`
  - `wgf-review-k7/backport/{tpl-new,tpl-old,tpl-r2,bbw,bbw2,sm,sm2}`
  - `wgf-review-k7/preflight/factory`
  - `wgf-spec/k7-tmp/platform/{sm,sm-bp,factory-base}`
  - `wgf-spec/k7-tmp/integrity/builds*`
  - `wgf-review-k6/r2/{wt,wt2}`, `wgf-review-k6/r3/{wt,wt2}`

  Note `wgf-review-k7/backport/{bbw,bbw2,sm,sm2}` and `k7-tmp/platform/sm-bp` hold backport patches as
  scratch commits or uncommitted changes. They are experiments, not deliverables.
- No secrets or tokens are needed or recorded here.

## 10. Cost and authorization

- **Metered spend today: $0.** No paid service, paid API, LLM judge, live agent run or `/new-game` ran.
  GitHub Actions on this public repository use hosted runners.
- **Unmetered:** this Claude Code session and its subagents (Factory investment, as recorded in
  `wgf-runs/budget-ledger.md`; not charged to either game).
- **Game budgets** (`wgf-runs/budget-ledger.md`, last snapshot 2026-10-08): 2D est. $210–255, 3D est.
  $180–225 plus the later identity-fix work, against US$250 caps. No raise is authorized.
- **Needs explicit approval:**
  - the paid baseline-vs-K6 real `/new-game` comparison (~US$300 per run);
  - any paid game step (design re-entry, develop/specialist visits, sdk-review, listing copy, visual-qa judge);
  - budget raises;
  - tags;
  - merges (see §7);
  - publishing.

## 11. Recovery instructions

- **All K7 work is committed on local branches.** It survives a restart, but exists only on this machine.
  - To back it up without publishing: `git -C C:/Users/duycu/wgf-spec/k6 bundle create C:/Users/duycu/wgf-k7x/k7-branches.bundle k7/baseline-compare k7/measurement-integrity k7/triage-hygiene k7/platform-preflight ops/checkpoint-2026-10-10`.
  - Pushing the branches needs the human's go-ahead.
- **Lost on shutdown:**
  - the K7 #1 full discover (PIDs 30296, 18564; re-run it);
  - the Lead's local `gh run watch` background shell (harmless).

  GitHub CI runs continue.
- **Do not run** `git reset --hard`, `git clean` or a blanket `git stash` in any listed worktree.
  - `stash@{0}` in the main checkout is pre-existing; leave it.
  - Untracked `.claude/` directories are session config; do not commit them.
- **If a K7 branch is lost:** each agent's notes in `k7-tmp/*/CHECKPOINT.md` and its review files describe
  the work. The real fixtures are reproducible from the game repos' tagged commits (`baseline-r1`,
  `regressed-head-68a12b7`, `cbac64e`, `1c6b099`, `43c08e2`).

## 12. Last verified

2026-10-10 17:30 UTC (2026-10-11 00:30 ICT, UTC+7), by the Lead session.

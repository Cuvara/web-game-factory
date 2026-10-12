# 2026-10-12 checkpoint: K7 branches verified, reviewed and finished (local only)

Continues `2026-10-10-end-of-day-checkpoint.md`. Everything below was observed on 2026-10-12 unless
marked CLAIMED. Nothing was pushed, merged, tagged, published or spent.

## 1. Recovery (verified at session start)
- Checkpoint e1e8175 and bundle `C:/Users/duycu/wgf-k7x/k7-branches-2026-10-10.bundle` intact (`git bundle verify` OK).
- K7 branches were clean at their recorded heads; no surviving node/python processes.

## 2. Template SDK and CI (latest, not historical)
| Item | State |
|---|---|
| PR #62 (draft, 7424689, pin -> template 4b74b08) | run 38066953703 SUCCESS (integrity, schemas, adapters, unit, test-core with both goldens). Still DO NOT MERGE: needs the v1.2.1 tag first. |
| PR #61 (K6, 17ae495) | run 38060673361 SUCCESS (acceptance + GOLDEN LOOP greybox + develop) |
| main 65eb86a | run 38060543038 SUCCESS |
| template `backport/1.2.0-platform-sdk` | 4b74b08 |
| tag v1.2.1 | absent (only v1.2.0) |
No CI failure to fix.

## 3. K7 branches (all on top of 29d22de, local, not pushed, clean)
Every branch: independent review to APPROVE WITH NITS, nits closed by test/docs-only commits; Phase D
(fail-first test, fix, pass, revert-fix fails) for every behaviour change; full `unittest discover` on
the last behaviour-changing HEAD = the 79 known Windows failures (`wgf-runs/k5-baseline2-failures.txt`),
0 new; check-integrity and runtime `--check` OK; test-core QUALITY and KNOWLEDGE PASS.

| Branch | HEAD | Commits since 10-10 | Review | Full suite (HEAD) |
|---|---|---|---|---|
| k7/baseline-compare | 6825d12 | 74ab26b 0743163 04c1443 329f7ad 2b0d241 6825d12 | r1 CHANGES REQUIRED (1 blocking, 3 major) -> r2 APPROVE WITH NITS | 6825d12: 4709 run, 0 new |
| k7/measurement-integrity | 28ee275 | 3d7e5b5 0fca3a6 e46e2c4 e2b044d 71683bd 28ee275 | r1 CHANGES REQUIRED (4 major) -> r2 -> r3 APPROVE WITH NITS | 71683bd: 4720 run, 0 new (28ee275 test/docs only) |
| k7/triage-hygiene | d22575b | 92b9cb8 db733cf d22575b | r1 PARTIAL -> r2 -> r3 APPROVE WITH NITS | db733cf: 4665 run, 0 new (d22575b test/docs only) |
| k7/platform-preflight | 16ba3c7 | 48fbad2 d0b2de0 bba0a14 16ba3c7 | prior PARTIAL -> final r1 CHANGES REQUIRED (1 major) -> r2 APPROVE WITH NITS (nit closed in 16ba3c7) | 16ba3c7: 4692 run, 0 new |

Key outcomes:
- **Baseline compare**: an unplayable accepted build no longer yields PASS; dropped units/fields/entities FAIL
  or are not-reported (required FAIL at release); degraded accepted plays are neither cached nor compared;
  undetermined -> WARNING; unit-scoped waivers must name the unit. Float-tolerance artefact fixed (rule
  unchanged). 8 test breakages 43c4554 itself had introduced (L8 promotion) fixed.
- **Measurement integrity**: 5 bypasses closed (inflated reported collider, masking entity, always-masked
  entity, hit-stop, no-turn-seen); review majors closed (dead frame guard -> travel guard; moving /
  composite / re-id surfaces; game-time exit; extent read 0.3 s after impact; solid comet along travel).
  Real recordings: 894b4b8 PASS 1.05x; r1 96f5cea FAIL 1.95-2.04x; 68a12b7 FAIL. 47/47 mutants killed.
- **Triage hygiene**: a failing report always un-notes and blocks (all 5 paths); a noted detection is never a
  measured FAIL; a pass the judge still lists is refused as no-repair evidence (evidence-strength 1.3.0; the
  ledger verdict deliberately unchanged, review agreed).
- **Platform preflight**: whole-package scans, missing/empty bundle never isolated, undescribed platform
  UNKNOWN (check-integrity error), silent template audit BLOCKED, BLOCKED verify -> isolated UNKNOWN,
  Y8 pending only while no id exists. Real builds: v1.2.0 bundles carry 5 foreign portal SDKs; 4b74b08 builds
  carry only their own.

Open risks (documented in the branches' docs):
- integrity P13: an honest broken composite face can be unmeasured and hold release (one honest reading
  0.034 vs bar 0.01) - watch in the first live run; collider inflated <= ~1.5x can pass; bars from one game.
- baseline compare: a not-reported item (chance absence on a busy host) is a required FAIL at release.
- triage: G1 (errs strict), minor-severity listings still count, pre-1.4.0 ledgers unprotected.
- preflight: text-match scan (like the template audit); Y8 ids unobtainable until the pin moves.

Evidence: `C:/Users/duycu/wgf-spec/k7-tmp/{baseline,integrity,triage,platform}/CHECKPOINT-2026-10-12.md`;
reviews `C:/Users/duycu/wgf-review-k7/{baseline,integrity,triage,preflight}/`.
Backup: `C:/Users/duycu/wgf-k7x/k7-branches-2026-10-12.bundle`.

## 4. Decision report (2D/3D vs accepted baselines)
`C:/Users/duycu/wgf-runs/k7-decision-report-2026-10-12.md` (detail: `wgf-spec/k7-tmp/baseline/discrepancies.md`).
- 2D 0db72b6 vs r1: FAIL on 7 levels + ball radius 11->20. Root cause: r1's own collision defect (42 px disc
  over a 22 px collider); 64476e0 made the collider honest and the 7 levels are measured repairs following it.
  The gates conflict by construction on this quantity. Recommended: 15-min human A/B of w1-l7, w3-l2, w3-l7,
  then recorded accepted changes; later a person-accepted baseline-r2.
- 3D 43c08e2 vs r1: no FAIL; nothing to decide now.

## 5. Human decisions pending
1. Merge K6 PR #61 (CI green).
2. Tag template v1.2.1 at 4b74b08.
3. Then set the pin ref to v1.2.1 and merge PR #62.
4. Merge 3D `feat/release-content` (43c08e2).
5. 2D re-plan at G2/G3 incl. Poki -> Y8.
6. 2D baseline discrepancies (D-2D above); 3D needs none now.
7. Any paid comparison (~US$300/run) - not run.
8. Whether to open PRs for the four K7 branches (push needs approval). Integration of the four will
   conflict in CHANGELOG, check-tiers, quality-assessment, lessons and the runtime (regenerate).

## 6. Release readiness
Not ready to publish. Blockers: pin move (decisions 2-3), Y8 ids/placements, 2D re-plan, baseline decision,
both games at their US$250 caps for further game work. Publishing remains blocked.

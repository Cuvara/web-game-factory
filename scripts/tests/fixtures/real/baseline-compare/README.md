# Real evidence for the baseline comparison

Minimal, path-free profiles of real measurements of the two 2026-10 validation games, replayed by
`scripts/tests/test_baseline_compare.py` against `core/reference/baseline-compare.yaml`. Every
file is real: a measurement made on 2026-10-10 (K7) or a commit's own content data file. Nothing
was edited by hand. Each file's `_source` names the commit, its role, how it was captured, the
sha256 of every record and content file the profile was computed from, and which recordings the
host degraded.

| Game | Accepted at G4 (tag `baseline-r1`) | Regressed loop head | Current candidate |
|---|---|---|---|
| 2D brick breaker | 96f5cea | 68a12b7 (tag `regressed-head-68a12b7`) | 0db72b6 (main: r1 content + declared worlds) |
| 3D marble | 64ff4c6 | 1c6b099 (tag `regressed-head-1c6b099`) | 43c08e2 (feat/release-content: the r1 courses + 4 new) |

**Played** (`<game>-<commit>-<role>.json`): the playability step of this branch built the commit
in a detached clone and played it with `bot.spec.ts` behind the refusing proxy - `pnpm preview`
on a port in 4190-4199, the desktop viewport only, one design per game (the validation run's own
game-design, its existing-content floor pointed at the accepted commit) so every build of a game
was handed the same settings (the settings sha256 is in `_source`); the profile is
`baseline.profile()` of those records, recomputed by `PlayabilityStep._profile`. Windows 11, CPU
only (SwiftShader), a host shared with other work: the step's own health rule marks a recording
made on a degraded host, and `_source.degraded` says which.

**Declared** (`<game>-<commit>-data.json`, `3d-c340631-accepted-courses-data.json`): the
commit's `public/content/units.json` (and layout source) read with `git show`, profiled with no
play records - declared quantities only.

| File | What | Notes |
|---|---|---|
| `2d-96f5cea-accepted.json` | the accepted 2D build, measurement A | its probe has no unit link (only w1-l1 is entered) and names no entity kind |
| `2d-96f5cea-repeat.json` | the same build, measurement B, same settings, another run directory | the repeat the tolerances are held against |
| `2d-68a12b7-regressed.json` | the 2D loop head | naive recording degraded on every attempt (two builds were played at once): its clear times and rates are unmeasured |
| `2d-0db72b6-candidate.json` | the current 2D candidate | |
| `3d-64ff4c6-accepted.json` | the accepted 3D build, measurement B | ships no content data file; its probe reports no content unit (no ids, no unit link). Measurement A degraded naive play on every attempt (made beside a 2D build) and was set aside |
| `3d-64ff4c6-repeat.json` | the same build, measurement C | |
| `3d-1c6b099-regressed.json` | the 3D loop head | win recording degraded on every attempt: drawn sizes and frame rate unmeasured |
| `3d-43c08e2-candidate.json` | the current 3D candidate | |
| `3d-c340631-accepted-courses-data.json` | the accepted r1 courses as data | c340631 descends from dc73132 (revert to 64ff4c6) and e6672e3 ("layouts.json holds r1's twelve course layouts verbatim"); 64ff4c6 itself ships no content data file, so this is the only declared form of its courses |
| `3d-1c6b099-data.json`, `3d-43c08e2-data.json` | those commits' declared content | |

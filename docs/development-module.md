# Development Module

`scripts/wgf_develop` implements the `develop` step: it turns the game design into a
playable game **in the title's game repository**, checks it the way the repository's CI
will, commits it, and reports what it proved. It is the first real module behind the
[workflow module contract](workflow-module-contract.md); read that first.

It writes no game code here — this repository holds none — and it never clones, pushes,
creates a repository or implements a platform SDK.

## What it does

```
inputs ──► brief ──► developer ──► checks ──► commit ──► prototype-report
           docs/development/     conformance, install,   one per visit,
           brief.md + brief.json typecheck, lint, unit,  keyed
                                 build, smoke
```

| Input | Used for |
|---|---|
| `game-design` | core loop, controls, MVP / later tiers / out of scope, session targets, onboarding, screens, placements, art and audio direction |
| `asset-manifest` | the assets the MVP loads, their source, status and license |
| `scaffold-record` | which repository to build in (`repository.name`) |
| `title-strategy` | `prototype_must_prove` and `kill_criteria`, which the report must list — optional |
| `qa-report` | on a verify → develop loop, the blocking defects the brief says to fix first |
| `review-report` | on a review → develop loop, the reviewer's blockers the brief says to fix first — used only when it requests changes to the commit this visit starts from ([review-module.md](review-module.md)) |

The engine comes from the checkout's `game.config.yaml`: `pixijs` for 2D, `threejs` for 3D.
Anything else is refused — adding an engine is the tech plan's decision at G3.

## The brief

`docs/development/brief.md` is the whole interface between the Factory and whoever writes
the game, regenerated on every visit and committed with the code it asked for. It states:

- **Ground rules** — the engine and where it may be imported (`src/rendering/<engine>/`
  only); the template-owned paths a game may not edit (`packages/`, `game.config.yaml`,
  `.github/`, `scripts/`, the build and test configs); no portal SDK in game code; pause
  by reason; the `#hud` probe contract the release pipeline reads; strings via i18n.
- **Required systems** — boot, game state, scenes, input, core loop, mechanics,
  progression, UI, HUD, tutorial, game over, restart, asset loading, responsive layout,
  audio hooks — each with its acceptance line.
- **Scope** — the MVP verbatim, the tiers that are *not now*, and what is out of scope.
- **The integration seam** — `src/game/integration.ts`, an interface the game calls for
  gameplay start/stop, rewarded and interstitial placements, analytics and saves. The
  default implementation wraps the template's `Platform`; the SDK module rewires it
  without the game changing a call. This is how development stays out of SDK work.
- **Tests** — unit tests for the rules, and a browser smoke test that *plays*.
- **Report back** — `docs/development/report.json`: the developer's own account of each
  system, each MVP item, the placements, integration status, assets, scope deltas and
  known issues.

## Developers

| `developer.kind` | Who writes the game | On a failed check |
|---|---|---|
| `handoff` (default) | A person, or an agent-host session a person drives. The step returns `WAITING_FOR_HUMAN`; resume with `--decision done` (or `abandon`). | Waits again, with the failures in `checks.json` and in the next brief |
| `command` | A configured process, unattended — typically an agent host's non-interactive mode. `argv` gets `{brief}`, `{repo}`, `{key}`, `{prompt}`. | Retryable `FAILED`; the next attempt's brief carries the failure output |

`command` runs are bounded by `timeout_seconds` (wall clock) and, optionally,
`idle_timeout_seconds` (no output at all for that long — a hung agent, not a slow one).
Either is a retryable `FAILED`.

The provider, if any, is named only in the installation's `factory.yaml`. Host skills the
brief recommends (PixiJS, Three.js, frontend design) are configured under
`develop.skills`, and the brief says plainly that the template wins wherever a skill
assumes another layout.

## Checks

Run in this order; `conformance` cannot be switched off.

| Check | What |
|---|---|
| `install` | `pnpm install --frozen-lockfile`. A failure stops the rest |
| `conformance` | Static: engine imports only in `src/rendering/<engine>/`, no other engine, no portal SDK identifiers, ad APIs called only from `src/platform/`, `BootScene` replaced, the seam present, template-owned paths unchanged since the visit began, and `report.json` complete — every required system `done`, every MVP item and placement reported |
| `format` | `pnpm format` — optional |
| `typecheck`, `lint`, `unit`, `build` | the repository's own scripts, as CI runs them |
| `smoke` | `pnpm test:e2e`. Skipped, and reported as skipped, only when no browser is installed |

## Idempotency

Each visit commits once, locally, with a `Wgf-Develop-Key: <run>:<step>:<visit>` trailer.
Re-executing a visit that already committed — a crash, a resume, `--run` — finds that
commit, skips development, re-runs the checks and reports the same commit. A new visit (a
verify → develop loop) is a new commit. Nothing is pushed: publishing a branch is the game
repository's CI, behind its own gates.

## The prototype report

What an automated step can honestly claim is narrow, and the report keeps to it:

- `playable_build` is recorded as a criterion with a **measured** value — the checks.
- Every `prototype_must_prove` question is `inconclusive`, and every kill criterion is
  recorded **unmeasured** with a note saying so. Development does not playtest.
- The single automated playtest session is `player_context: internal`.
- The recommendation is `iterate` — never `pass`. G4 needs first-time sessions.

Integration status and scope deltas come from the developer's report; MVP items reported
`cut` or `deferred` and placeholder assets become scope deltas automatically.

## Configuration

```yaml
factory:
  steps:
    modules: [wgf_develop]
  develop:
    checkouts: ..               # <checkouts>/<repository.name>, relative to the Factory root
    developer: {kind: handoff}  # or {kind: command, argv: [...], timeout_seconds: 5400}
    checks: [install, conformance, typecheck, lint, unit, build, smoke]
    check_timeout_seconds: 900
    commit: true
    build_url: null             # "https://{branch}.{name}.pages.dev"; {owner} {sha} {short_sha}
    author: {name: ..., email: ...}   # when the checkout has no git identity
    skills: {pixijs: [...], threejs: [...], ui: [...]}
```

## Tests

`scripts/tests/test_develop_module.py` — offline, with throwaway git repositories and a
fake process runner: every outcome in contract §7 the step can produce, both developers,
idempotency across re-execution and across visits, every conformance rule (and the
template's own files not tripping them), and the full `new-game` workflow through the real
engine with this module replacing the mock. `WGF_AJV=1` adds an ajv validation of an
emitted report against the full schema.

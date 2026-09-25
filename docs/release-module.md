# Release Module

The `release` step of `core/workflows/new-game.workflow.yaml` (stage `release:draft`): turn a
verified commit into a **draft** release, and prove that the draft is what was verified.
Implemented in `scripts/wgf_release/`, registered from `workspace/config/factory.yaml`,
written against [workflow-module-contract.md](workflow-module-contract.md) without touching
the kernel.

```
bin/wgf new-game                          # ... verify -> release, no --mock needed
bin/wgf release --run <run-id>            # draft from the run's newest verification
WGF_GAME_REPO=../neon-drift bin/wgf release --run <run-id>
```

It never pushes, tags, publishes or contacts a portal. A draft is the input to `release:qa`
/ `rc` and the G5 and G6 gates, which are later and elsewhere.

## What it produces

| Where | What |
|---|---|
| the game repository, `release/<release-id>/` | `<platform>.zip` per target, `packages.json`, `checksums.txt` — written by the game's own `release:package` — and `manifest.json` |
| the run | `release-manifest` (state `draft`), the same document as `release/<release-id>/manifest.json` |

Release artifacts belong in the game repository (CLAUDE.md); the run holds the manifest so a
gate can pin it by hash. The manifest is the one the game's `release:manifest` wrote, checked
and then **extended** with what it rests on (schema 1.1.0, `evidence.review` since 1.2.0,
all optional fields):

| Field | Holds |
|---|---|
| `provenance.inputs` | the qa-report, verification-report, sdk-report, prototype-report, scaffold-record and review-report it was drafted from, by content hash |
| `evidence.qa_report`, `evidence.verification_report` | id, hash, verdict, evidence status |
| `evidence.commit_lineage` | the commit each report names, and the checkout's HEAD: the verified commit (qa-report, verification-report, sdk-report, checkout), and the commit develop made (`sdk-report.base`, `prototype-report`) — related by the lineage rule below |
| `evidence.review` | `approved` (the newest review-report — `sdk-review`'s — approved exactly the commit shipped: the sdk commit, HEAD), or, only when `factory.release.allow_unreviewed: true`, `skipped` (no reviewer configured) or `absent` (no review-report in the run), both **UNREVIEWED** in the note and the step's message, never an approval; with the verdict, the reviewed commit and the review-report's id and hash |
| `evidence.bundle_hash` | the digest of the bundle that was verified and packaged |
| `evidence.platforms[]` | per target: readiness, `evidence_status`, `portal_status`, `external_approval: not-claimed` — carried from the verification exactly |
| `evidence.package_audit` | the rules every package passed |
| `evidence.reproducibility` | whether the archive bytes are reproducible, and why not |
| `packages[].checksum` / `content_digest` / `files` | sha256 of the archive; sha256 over its entry names and contents; entry count |
| `template` | template repository and commit (scaffold-record) and version, with where the version was read |
| `workflow` | run id, workflow, step, visit, execution, idempotency key |

## When it refuses

Every precondition is checked before anything is packaged, and all failures are reported
together. Nothing is returned as a `release-manifest` on a refusal: a draft that exists only
when its preconditions held is what makes a draft mean something. The refusals are listed in
`StepResult.data.refusals`, each with a stable `code`.

| Code | Outcome | Means |
|---|---|---|
| `no-qa-report`, `no-verification-report` | BLOCKED | verification has not run in this run |
| `qa-not-passed`, `verification-not-passed` | FAILED | the newest verification failed or was blocked |
| `evidence-too-weak` | FAILED | its evidence is `UNVERIFIED`, `BLOCKED_EXTERNAL` or `FAIL`; a draft needs `PASS` or `PASS_MOCK` |
| `evidence-status-missing` | FAILED | a 1.0.x verification: whether it passed on mocks cannot be told |
| `stale-qa-report` | FAILED | the qa-report does not pin the run's newest verification-report, prototype-report or sdk-report — work happened after it |
| `foreign-qa-report` | FAILED | the qa-report names another run |
| `commit-lineage-mismatch` | FAILED | the evidence breaks the commit lineage rule: the verified reports or HEAD name different commits, sdk built on another commit than develop's, a commit between develop's and sdk's is not this run's keyed sdk commit, or the history cannot be read |
| `commit-unknown` | FAILED | a report names no commit, or a placeholder (`unknown`, 40 zeros) |
| `review-not-approved` | FAILED | the run's newest review-report requested changes, produced no verdict, or approves with no reviewer behind it (`reviewer.kind` is not `command`: a `--mock` placeholder or a hand-written report) |
| `unreviewed` | FAILED | the newest review-report is `skipped` (no reviewer configured) or the run holds none. Allowed only by `factory.release.allow_unreviewed: true`; the manifest then says UNREVIEWED |
| `review-commit-mismatch` | FAILED | the newest approval is of another commit than the one shipped — e.g. only develop's commit, when sdk committed on top of it — or pins an older prototype-report or sdk-report than the run's newest. `allow_unreviewed` does not waive it |
| `g4-not-passed` | BLOCKED | a gate the step's `required_gates` names (default `[G4]`) is not in `context.gates_passed`: not passed in this run, or superseded by a newer verification. A person decides it (`wgf decide`), then the run resumes |
| `verified-dirty-tree` | BLOCKED | verification ran on uncommitted changes, which no commit reproduces |
| `dirty-checkout` | BLOCKED | the checkout has uncommitted or untracked changes |
| `bundle-not-verified` | BLOCKED | the build output on disk is not the bundle verification digested |
| `no-checkout`, `no-commit` | BLOCKED | no game repository found, or not a git repository |
| `package-failed`, `manifest-failed` | FAILED (BLOCKED if the tool is missing) | the game's release script failed |
| `no-packages`, `package-missing`, `package-unlisted` | FAILED | the packages do not match the target platforms |
| `checksum-mismatch` | FAILED | a recorded sha256 is not its file's |
| `package-content` | FAILED | an archive breaks an audit rule, below |
| `invalid-manifest` | FAILED | the game's manifest, or the drafted one, does not validate |
| `bad-release-id`, `release-id-taken`, `bad-version`, `no-release-script`, `no-game-config` | FAILED | configuration |

FAILED refusals are not retryable: they are facts about the evidence. BLOCKED ones need a
person — run verify, commit, clean the tree — and the run resumes after.

### `release --run` after a failed verification

`--run` resolves each input to the newest artifact of its type, whatever it says. So a run
whose verify **failed** still hands the release step that failing qa-report, and a run whose
newest passing qa-report predates a later develop or sdk visit hands it a stale one. Both are
refused (`qa-not-passed`, `stale-qa-report`); `test_core_release.ContinueIn` runs the first
through the real engine.

## The package audit

Every archive is opened and checked; the rules are the same for every platform:

- `index.html` at the archive root — a portal serves the root;
- no sourcemaps (`*.map`);
- no test files — `tests/`, `__tests__/`, `e2e/`, `*.test.*`, `*.spec.*`, test-runner configs
  and reports;
- no environment or secret files — `.env*`, `*.pem`, `*.key`, keystores, SSH keys,
  `credentials.*`, `secrets.*`, `.npmrc`;
- no secret-looking content in text entries — private-key blocks, cloud access key ids,
  source-host, chat and live payment tokens, and string literals assigned to names like
  `client_secret`, `access_token` or `password`. The patterns are specific on purpose: a false
  positive stops a release;
- no absolute or `..` entry names.

## Commit lineage

The rule is defined once, in `docs/core-contracts.md` §5, and implemented once, in
`scripts/wgf_verification/lineage.py`; verify's `source.upstream-commits` and this step both
apply it.

```
prototype-report.build_ref.commit_sha ───── equal ─ sdk-report.build_ref.base_commit_sha
                                                          │
                              git log base..sdk: only this run's `Wgf-Sdk-Key` commits
                                                          │
sdk-report.build_ref.commit_sha       ┐                   ▼
verification-report.commit.sha        │
qa-report.build_ref.commit_sha        ├─ all equal ─ git rev-parse HEAD (clean tree)
review-report.reviewed_commit         ┘  (the newest review-report, approve: sdk-review's)
verification-report.build_artifact.content_hash ── equals ── digest of dist/ on disk
```

What can be checked from the reports alone is checked before anything else; the history
between the base and the sdk commit is read with git from the checkout. If git cannot read
it, the release is refused: the rule is never assumed to hold. An sdk-report from before sdk
committed (no `base_commit_sha`) is read as base == commit, so it must name the prototype's
commit itself.

The last line is what ties the bytes about to be packaged to the bytes that were verified:
the build output is git-ignored, so a clean tree alone says nothing about it. The step
packages that bundle and never rebuilds it.

## Reproducibility

Running the step twice on the same commit and bundle gives identical archive hashes — the
release id is reused (a commit keeps the `r<n>` it was given) and the same files are zipped.
`test_core_release.Reproducibility` and the opt-in template test check it.

A **rebuild** of identical content does not: web-game-template's `package.mjs` uses adm-zip,
which stamps each entry with the file's modification time, and `vite build` rewrites every
file. The step does not work around it (the template is another repository); it records it.
`evidence.reproducibility.archive_bytes` is `timestamp-dependent` when entry timestamps
follow the bundle's mtimes, and `packages[].content_digest` — over entry names and contents
only — is the identity that survives a rebuild. The fix, if wanted, belongs in the template:
normalize entry times (and order) in `package.mjs`.

## Where the checkout comes from

As verification: the step's `with: repo_dir`, else `WGF_GAME_REPO`, else
`factory.release.checkouts` joined with the run's `scaffold-record.repository.name`. It never
clones.

## The environment packaging runs with

`release:package` and `release:manifest` are game code, and git runs through the same
runner: the game-code environment, never the Factory's - `wgflib/agentenv.py` `game_code_env`: the agents' allowlist (PATH, HOME, USER, LANG/LC_*, TERM, TMPDIR, SHELL, CI, the proxy variables, XDG_*, NODE_*, PNPM_*, npm_config_*, PLAYWRIGHT_*, COREPACK_* - minus any name that says it is a secret) plus `factory.agents.game_env_passthrough`. The step's `environ`
test seam, when set, is used as given.

## Parameters (`with:`, over `factory.release`)

| Key | Default | |
|---|---|---|
| `repo_dir` | — | The checkout |
| `release_id` | the id this commit already has, else the next `r<n>` under `release/` | Refused if it already holds another commit |
| `version` | `game.version` in game.config.yaml, else package.json | semver |
| `kind` | `initial` for `r1`, else `content` | |
| `timeouts` | git 30, package 900, manifest 300 | seconds |
| `required_gates` | `[G4]` | Gates the run must have passed, current (`context.gates_passed`). **`with:` only** - never read from `factory.release`, so an installation cannot loosen what the workflow requires. A workflow with no G4 checkpoint (a test workflow) says so: `required_gates: []` |

And one key read **only** from `factory.release`, never from `with:` - an installation's
decision, not a workflow's:

| Key | Default | |
|---|---|---|
| `allow_unreviewed` | `false` | `true` drafts a build whose newest review is `skipped` or absent, recorded as **UNREVIEWED** in `evidence.review.note` and the step's message. It never waives a review of another commit, a request for changes, or a gate |

### Why the release step checks G4 itself

The engine already refuses to start `release` past an unpassed gate in the same run
(`wgf release --run`, `--from release`). The step checks again because it is the last
place before a draft exists, and because the engine's answer can change after the fact:
a newer verification supersedes a G4 pass (`context.gates_passed` then omits G4). The step
cannot see the workflow definition, so it does not guess whether the run's workflow has a
G4 checkpoint: the workflow says which gates its release requires, and the default is G4 -
fail closed. `test_workflow_definition` checks that every shipped workflow's release step
requires every irreversible gate checkpointed before it.

## Evidence is carried, never upgraded

The draft's `evidence.status` is the verification's own — `PASS_MOCK` whenever anything
required was observed only against a stand-in, which today includes every SDK feature. Per
platform, `evidence_status` and `portal_status` are copied as the verification wrote them:
a portal's own QA stays `BLOCKED_EXTERNAL` until someone has evidence from the portal, and
`external_approval` is always `not-claimed`. See
[verification-module.md](verification-module.md#evidence-statuses).

## Tests

- `scripts/tests/test_release_module.py` — the step on its own, the audit, the engine.
- `scripts/tests/test_core_release.py` — the RELEASE category: valid and invalid releases,
  schema validity, hashes, lineage, before/after verify, stale evidence, dirty checkouts,
  forbidden content, reproducibility, `release --run` after a failure, and
  `ReviewedAndPassed`: unreviewed (and `allow_unreviewed`), an approval of the develop
  commit only, a review of an older sdk-report, `g4-not-passed`.
- `scripts/tests/test_core_lineage.py` — the same rules with a real sdk commit on top of
  develop's.

Both use real git repositories in temporary directories and a fake `pnpm`
(`fixtures/release/fake-pnpm.py`) first on PATH that packages the way the template does.
`WGF_AJV=1` validates a drafted manifest with ajv. `WGF_TEMPLATE_RELEASE_TEST=1` (with
`WGF_TEMPLATE_DIR` when the template is not the sibling of this checkout) copies
web-game-template, installs it offline, builds it, and runs its real release scripts through
the step twice.

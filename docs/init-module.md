# Init Module

The first real step module: `init` in `core/workflows/new-game.workflow.yaml`, serving
`title:scaffolding`. Written against [workflow-module-contract.md](workflow-module-contract.md);
it changes nothing in the engine.

```
game-design ─► project metadata ─► repository from web-game-template ─► local project
tech-plan ───────────────────────► game.config.yaml from repo_params, one local commit
                                                                     ─► scaffold-record
```

| File | Holds |
|---|---|
| `scripts/wgf_init/project.py` | Project metadata derived from a `game-design`. Pure. |
| `scripts/wgf_init/tooling.py` | The `GitHub` and `Git` interfaces, and the `gh`/`git` CLI implementations (every call through `wgflib.procs.run`) |
| `scripts/wgf_init/infrastructure.py` | What a generated repository must already contain |
| `scripts/wgf_init/gameconfig.py` | The in-place, verified rewrite of `game.config.yaml` |
| `scripts/wgf_init/profiles.py` | Vendoring the pinned profiles into `config/platforms/` |
| `scripts/wgf_init/step.py` | `InitStep`, and `factory.init` settings |
| `scripts/tests/test_init_module.py` | Unit, contract, idempotency and failure-path tests; GitHub faked, git real in temp dirs |

## What it does

1. **Metadata.** The repository name is the design's `title_id`; the description is the
   design's fantasy, first sentence, plus the idempotency marker. A design whose
   `consistency.status` is not `pass`, or whose title does not match the run's `--project`,
   is refused — `FAILED`, not retryable. So is a `tech-plan` for another title, or one whose
   `engine.type` and `repo_params.game_config.engine` disagree.
2. **Repository**, always at the Factory's pinned template revision
   (`workspace/config/template.lock.json`: the latest template release, by tag and commit).
   `factory.init.template` must be the lock's repository, and a `tech-plan` approved at G3
   must name `<repository>@<pinned commit>` as `repo_params.template_ref`; otherwise
   `FAILED`, not retryable. By `factory.init.source`:
   - **`github`** (default). `gh repo view <owner>/<title-id>`. Absent: `gh repo create
     --template <template>`, recording the template's head commit as
     `template.generated_from_sha`. Present: see *Idempotency*. Either way the repository must report the configured
     template as its `templateRepository`, or it is refused — adopting is authorizable, a
     repository that did not come from the template is not. Then it waits for GitHub to
     finish generating the contents (`game.config.yaml` present), and clones with `gh repo
     clone` into `<projects_dir>/<title-id>`. An existing clone of the same repository is
     reused, and filled with `git pull --ff-only` if an earlier attempt cloned it empty.
     **Pinning.** GitHub generates from the template's default branch as it is at that
     moment, which need not be the pinned commit. Init fetches the pinned commit by sha and,
     when the generated root's tree differs from it, applies root→pin as ONE local commit
     (`chore(init): pin web-game-template <sha>`, trailers `Wgf-Template: <template>@<sha>`
     and `Wgf-Init-Key`), keeping whatever was committed on top of the root (bootstrap's
     commit). Afterwards the tree must equal the pin everywhere except the paths committed
     on top of the root; a patch that does not apply, or any other residue, is `FAILED`, not
     retryable, with nothing half-applied. The record carries `template.commit_sha` (the
     pin), `generated_from_sha` and `pin_commit`.
   - **`local`**. No `gh`, no network, no remote. `template_path` is a git checkout of the
     template that holds the pinned commit (left out: a checkout of the pin is made, as the
     tests' `wgflib.template.checkout()` does); a checkout without it is `BLOCKED`.
     `template_ref`, if set, must resolve to the pinned commit or the step `FAILS`.
     `git archive` of that commit is committed as the single initial commit of a new
     repository at `<projects_dir>/<title-id>` — the same shape GitHub's "use this template"
     produces, sharing no objects or history with the template. It is built in a staging
     directory and renamed into place, so a crash leaves nothing half-made at the path.
   Anything else at the path is refused.
3. **Verification.** Every path in `TEMPLATE_INFRASTRUCTURE` must be present — the packages,
   the six pipelines that outlive bootstrap, the test layers, the release and verify
   tooling. `game.config.yaml` must parse, pin every platform as `{id, profile, role}` and
   name a supported engine. A gap is a template problem: `FAILED`, not retryable, and fixed
   in the template.
4. **Configuration**, when the run holds a `tech-plan`:
   - `game.config.yaml` is edited in place from `tech_plan.repo_params.game_config`:
     `engine.type`, the `platforms` items, and `monetization.ad_kinds`/`iap`. Comments and
     every other field survive; the result is parsed back and must read exactly as the plan
     says with every other key unchanged, or it is not written (`FAILED`, not retryable).
   - The pinned profiles are copied byte-for-byte from `core/reference/platforms/` into
     `config/platforms/`, and `pinned.json` lists each with its sha256. A profile's identity
     is id + version + that `content_hash`, never the version string alone: the template
     ships its own `config/platforms/*.yaml`, and some declare the same `id@version` as the
     Factory's with other content. A copy counts as already pinned only when its bytes, its
     `pinned.json` hash and the Factory's profile agree; a same-version copy with other bytes,
     or an entry with no hash (unverified), is overwritten with the Factory's copy and
     re-recorded. `profiles.verify_pins()` is the read-side check: it compares hashes, and
     reports a pin whose hash differs from the Factory's profile at the same version. A pin
     that no longer matches the Factory's profile version is refused rather than vendored
     under the wrong version.
   - `game.id`/`game.name` are set from the repository name with exactly `bootstrap.yml`'s
     derivation, for either source (see *The bootstrap race*). With `source: local` there is
     no bootstrap workflow, so init also removes `bootstrap.yml`.
   - Each platform entry carries what the plan carries: `id`, `profile`, `role`, and for
     portals that issue one, `game_id` (and `hosting`/`game_url` for a non-default hosting
     mode) - see `docs/techplan-module.md`, *Portal registrations*. A key game.config.yaml
     has no place for is refused.
   - The changed paths are committed **locally**, once, with the trailers
     `Wgf-Init-Key: <marker>` and `Wgf-Tech-Plan: <content hash>`. Nothing is pushed.
   Without a `tech-plan` (a run whose workflow has no tech-plan step), the file is left as
   the template generated it, and the record says so.
5. **Record.** A `scaffold-record` with provenance pinning the consumed `game-design` and
   `tech-plan` by content hash, `outcome: created | reused`, `template.source`, and
   `game_config` as read back from the project — platforms, `engine`, a checksum of the
   bytes, and when a commit carries the configuration, `commit_sha` with `pushed: false`.
   Its `ArtifactRef.metadata` carries `repository`, `local_path`, `outcome`, `source`,
   `engine` and `config_commit`.

## What it does not do

- **Recreate template infrastructure.** CI/CD, the platform SDK, build and test
  configuration and platform adapters belong to web-game-template. Init only checks they
  arrived.
- **Push.** Pushing is outward-facing. The configuration commit exists only in the local
  project until a person (or a later, explicitly authorized step) pushes it; the record's
  `game_config.pushed: false` says so.
- **Advance the title.** Moving `title:scaffolding` forward is `wgf-state.py`'s job.

## The bootstrap race

With `source: github`, the template's `bootstrap.yml` runs on GitHub on the push that
creates the repository: it sets the identity lines of `game.config.yaml`, deletes itself,
and pushes its own commit. Init clones as soon as the contents exist, so the clone may or
may not already contain that commit. Init's configuration commit is made on top of whatever
was cloned, and is not pushed. Consequences, stated honestly:

- If bootstrap's commit landed after the clone, the local branch and `origin` have
  diverged. Before pushing, `git pull --rebase`. Both commits set the identity lines, to
  identical values (init uses bootstrap's own derivation), and otherwise touch disjoint
  lines, so the rebase is clean (`test_a_later_bootstrap_commit_rebases_cleanly_under_init_s`).
- Init used to leave the identity to bootstrap alone. Bootstrap mints a token from the
  organization's bot app; a repository that cannot reach those credentials fails bootstrap,
  and the game then kept the template's placeholder `example-game` without anyone being
  told. Writing the same identity locally removes that dependency.
- Bootstrap's "already ran?" guard reads the first indented `id:` line of the file on
  GitHub. Init never pushes, so bootstrap always sees the template's own identity there.
- Until the commit is pushed, the repository on GitHub still targets the template default
  (`generic-web`, `pixijs`). Anything that builds from GitHub rather than from the local
  project sees that default.

With `source: local` there is no bootstrap and no race.

## Idempotency

The side effect is keyed once per run, not once per visit: the marker
`wgf-init:<run_id>:<step_id>`.

- **github**: written into the repository description at creation. A retry, a crash between
  `gh repo create` and the engine persisting the result, a resume, or `wgf init --run <id>
  --force` all find the marker — or, failing that, the repository named in the step's
  `previous_outputs` metadata — and record `reused`.
- **local**: written into the project's `git config` (`wgf.init-marker`, alongside
  `wgf.template` and `wgf.template-commit`) and the initial commit's trailer. Found the same
  way, or by the `local_path` in `previous_outputs`.
- **The configuration commit**: a re-execution recomputes the file from the plan. If it
  already matches and nothing is uncommitted, no commit is made and the record names the
  newest commit carrying this key. A crash after writing but before committing is completed
  by the next execution — still one commit. A revised plan in the same run (G3 rejected,
  design and plan redone) is a second keyed commit, because the file genuinely changes.

A repository or directory with neither marker nor reference is someone else's. Init stops
with `BLOCKED` and does not touch it unless `factory.init.adopt_existing: true` authorizes
reusing it — and even then only if it came from the configured template.

## Configuration

`factory.init` in `workspace/config/factory.yaml`, and the module listed under
`factory.steps.modules`:

| Key | Default | Meaning |
|---|---|---|
| `source` | `github` | `github` or `local` |
| `owner` | — (required for `github`) | Account or organization that owns game repositories |
| `template` | — (required for `github`) | Template repository, `owner/name` |
| `template_path` | a checkout of the pin | `local` only: git checkout of the template holding the pinned commit; relative to the Factory's root |
| `template_ref` | the pin | `local` only: if set, must resolve to the pinned commit |
| `visibility` | `private` | `private`, `internal` or `public` |
| `projects_dir` | `..` | Where local projects go; relative to the Factory's root |
| `adopt_existing` | `false` | Authorize reusing a repository or directory this run did not create |
| `populate_timeout_seconds` | `60` | `github` only: how long to wait for GitHub to generate the contents |
| `commit_author` | `{name: wgf-init, email: wgf-init@users.noreply.invalid}` | Author of the configuration commit |

Missing or invalid settings return `BLOCKED` before anything is contacted. For `github`,
`gh` must be installed and authenticated (`gh auth status`); it is not configured by the
module. `git` is needed in both modes.

## Outcomes

| Situation | Result |
|---|---|
| No `game-design` in the run | `WAITING_FOR_INPUT` |
| `factory.init` missing or invalid | `BLOCKED` |
| `template_path` not a git checkout with a commit (`local`) | `BLOCKED` |
| Design not scaffoldable, or a tech plan for another title / self-contradicting | `FAILED`, not retryable |
| Repository or project exists, not this run's, not authorized | `BLOCKED` |
| Local path occupied by anything but this project | `BLOCKED` |
| Repository or project not generated from the template | `FAILED`, not retryable |
| Template infrastructure missing, an unpinned platform, an unknown engine | `FAILED`, not retryable |
| `game.config.yaml` cannot be rewritten verifiably, or a pin no longer matches its profile | `FAILED`, not retryable |
| Network, `gh` hiccup, contents not generated in time, a `git` failure | `FAILED`, retryable |
| Repository name taken by one `gh` cannot see | `FAILED`, not retryable |

## Running it

```bash
python -m unittest scripts/tests/test_init_module.py     # offline; GitHub is faked
WGF_AJV=1 python -m unittest scripts.tests.test_init_module.AjvSchema   # + ajv
WGF_TEMPLATE_DIR=../web-game-template python -m unittest \
  scripts.tests.test_init_module.RealTemplateLocalSource                # local source, real template
```

Running `wgf init` with `source: github` outside `--mock` against a run holding a
`game-design` **creates a real repository**. That is an outward-facing act: do it only when a
title is genuinely being produced (core/lifecycle/stages/scaffolding.md). `source: local`
creates only a directory.

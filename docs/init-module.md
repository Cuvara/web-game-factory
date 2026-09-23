# Init Module

The first real step module: `init` in `core/workflows/new-game.workflow.yaml`, serving
`title:scaffolding`. Written against [workflow-module-contract.md](workflow-module-contract.md);
it changes nothing in the engine.

```
game-design ─► project metadata ─► gh repository from web-game-template ─► local project
                                                                       ─► scaffold-record
```

| File | Holds |
|---|---|
| `scripts/wgf_init/project.py` | Project metadata derived from a `game-design`. Pure. |
| `scripts/wgf_init/tooling.py` | The `GitHub` and `Git` interfaces, and the `gh`/`git` CLI implementations |
| `scripts/wgf_init/infrastructure.py` | What a generated repository must already contain |
| `scripts/wgf_init/step.py` | `InitStep`, and `factory.init` settings |
| `scripts/tests/test_init_module.py` | Unit, contract, idempotency and failure-path tests; GitHub faked |

## What it does

1. **Metadata.** The repository name is the design's `title_id`; the description is the
   design's fantasy, first sentence, plus the idempotency marker. A design whose
   `consistency.status` is not `pass`, or whose title does not match the run's `--project`,
   is refused — `FAILED`, not retryable.
2. **Repository.** `gh repo view <owner>/<title-id>`. Absent: `gh repo create --template
   <template>`, recording the template's head commit as `template.commit_sha`. Present: see
   *Idempotency*. Either way the repository must report the configured template as its
   `templateRepository`, or it is refused — adopting is authorizable, a repository that did
   not come from the template is not. Then it waits for GitHub to finish generating the
   contents (`game.config.yaml` present), which happens asynchronously.
3. **Local project.** `gh repo clone` into `<projects_dir>/<title-id>`. An existing clone of
   the same repository is reused, and filled with `git pull --ff-only` if an earlier attempt
   cloned it empty. Anything else at that path is refused.
4. **Verification.** Every path in `TEMPLATE_INFRASTRUCTURE` must be present — the packages,
   the six pipelines that outlive bootstrap, the test layers, the release and verify
   tooling. `game.config.yaml` must parse and pin every platform as `{id, profile, role}`.
   A gap is a template problem: `FAILED`, not retryable, and fixed in the template.
5. **Record.** A `scaffold-record` with provenance pinning the consumed `game-design` by
   content hash, `outcome: created | reused`, and `game_config` as read from the clone with a
   checksum of its bytes. Its `ArtifactRef.metadata` carries `repository`, `local_path` and
   `outcome`.

## What it does not do

- **Recreate template infrastructure.** CI/CD, the platform SDK, build and test
  configuration and platform adapters belong to web-game-template. Init only checks they
  arrived.
- **Write `game.config.yaml`.** It comes from `tech_plan.repo_params`, reviewed at G3, and
  the tech plan is not an input of this step. The template's `bootstrap.yml` sets the game's
  identity from the repository name — which is why the repository name is the title id — and
  the platform list stays at the template default until the plan writes it. Init also pushes
  nothing: bootstrap pushes to a fresh repository, and a second writer would race it.
- **Advance the title.** Moving `title:scaffolding` forward is `wgf-state.py`'s job.

## Idempotency

The side effect is keyed once per run, not once per visit: the marker
`wgf-init:<run_id>:<step_id>` is written into the repository description at creation. A
retry, a crash between `gh repo create` and the engine persisting the result, a resume, or
`wgf init --run <id> --force` all find the marker — or, failing that, the repository named in
the step's `previous_outputs` metadata — and record `reused`. The marker lives on the
repository because the crash that matters is the one after the repository exists and before
run state knows it does.

A repository with neither is someone else's. Init stops with `BLOCKED` and does not touch it
unless `factory.init.adopt_existing: true` authorizes reusing it.

## Configuration

`factory.init` in `workspace/config/factory.yaml`, and the module listed under
`factory.steps.modules`:

| Key | Default | Meaning |
|---|---|---|
| `owner` | — (required) | Account or organization that owns game repositories |
| `template` | — (required) | Template repository, `owner/name` |
| `visibility` | `private` | `private`, `internal` or `public` |
| `projects_dir` | `..` | Where local clones go; relative to the Factory's root |
| `adopt_existing` | `false` | Authorize reusing a repository or clone this run did not create |
| `populate_timeout_seconds` | `60` | How long to wait for GitHub to generate the contents |

Missing or invalid settings return `BLOCKED` before GitHub is contacted. `gh` must be
installed and authenticated (`gh auth status`); it is not configured by the module.

## Outcomes

| Situation | Result |
|---|---|
| No `game-design` in the run | `WAITING_FOR_INPUT` |
| `factory.init` missing or invalid | `BLOCKED` |
| Design not scaffoldable | `FAILED`, not retryable |
| Repository exists, not this run's, not authorized | `BLOCKED` |
| Local path occupied by anything but a clone of the repository | `BLOCKED` |
| Repository not generated from the template | `FAILED`, not retryable |
| Template infrastructure missing, or an unpinned platform | `FAILED`, not retryable |
| Network, `gh` hiccup, contents not generated in time | `FAILED`, retryable |
| Repository name taken by one `gh` cannot see | `FAILED`, not retryable |

## Running it

```bash
python -m unittest scripts/tests/test_init_module.py     # offline; GitHub is faked
WGF_AJV=1 python -m unittest scripts.tests.test_init_module.AjvSchema   # + ajv
```

Running `wgf init` outside `--mock` against a run holding a `game-design` **creates a real
repository**. That is an outward-facing act: do it only when a title is genuinely being
produced (core/lifecycle/stages/scaffolding.md).

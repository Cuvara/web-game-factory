# The plugin runtime: Factory plugin = Factory runtime, working directory = project

```
Factory plugin  = the Factory runtime   core/, the engine, step modules, shipped config
working dir     = the target project    workspace/, .factory/ runs, game checkouts beside it
```

The web-game-factory **repository** is where the Factory is developed, built and released.
The installed **Claude plugin** is what runs it. Claude Code installs a plugin by copying its
directory - `claude-web-game-plugin/`, and nothing outside it - into
`~/.claude/plugins/cache/<marketplace>/<plugin>/<version>/`, and runs its commands from
whatever project the user has open. So the plugin carries the runtime, and nothing a command
does depends on the working directory being this repository.

## What the plugin ships

```
claude-web-game-plugin/
  .claude-plugin/plugin.json      manifest; version = VERSION
  agents/ commands/ skills/       generated surfaces (scripts/gen-adapters.sh)
  runtime/                        generated runtime (scripts/build-plugin-runtime.py)
    runtime-manifest.json         every file below with its sha256; marks an installed runtime
    VERSION  bin/wgf
    core/                         machines, gates, schemas, workflows, roles, templates, craft,
                                  reference data - everything a surface or the engine reads
    scripts/wgf.py                the engine
    scripts/wgf-{state,guard,hash,template}.py
    scripts/wgflib/               the engine library, with the mock fixtures
    scripts/wgf_*/                every step module, with its data
    workspace/config/             shipped defaults: factory.yaml, portfolio.yaml,
                                  template.lock.json, mcp-playwright-localhost.json
    docs/workflow-engine.md       the one document a surface tells the agent to read
```

Not shipped, deliberately: `scripts/tests/`, `scripts/golden/`, `scripts/mv4/`, the
integrity check and generators, `docs/` other than the above, `.github/`, and every piece of
instance data (`workspace/claims`, `opportunities`, `titles`, `research`). `wgf test-core`
refuses to run from an installed runtime: the acceptance suite is a development tool.

The bundle is generated and committed, because the marketplace installs straight from the
repository and has no build step. `scripts/gen-adapters.sh` rebuilds it with the surfaces;
`scripts/check-integrity.py` fails when it is not the source's runtime closure byte for byte
(`python scripts/build-plugin-runtime.py --check`). Never edit a file under `runtime/`.

## How paths resolve (`scripts/wgflib/paths.py`)

| Root | Holds | Development checkout | Installed plugin |
|---|---|---|---|
| `ROOT` (Factory) | `core/`, the engine, step modules, shipped config, template pin | the repository | `${CLAUDE_PLUGIN_ROOT}/runtime` |
| `PROJECT` | `workspace/` (instance data and the installation's own `workspace/config/`), the run store (`factory.storage`), the checkouts base (`factory.checkouts`), `.factory/assets` | the repository | the working directory |

`ROOT` is always the directory above `wgflib/`, never the working directory. `PROJECT` is
`WGF_PROJECT_DIR` when set; otherwise the repository in a development checkout (exactly as
before the plugin carried a runtime), or the working directory when `runtime-manifest.json`
sits at `ROOT`. The installed runtime exports `WGF_PROJECT_DIR` to every process it starts,
so a child in another directory finds the same project.

Configuration is per project with the Factory's as default: `paths.config_file(name)` is the
project's `workspace/config/<name>` when it has one, else the shipped copy - for
`factory.yaml` and `portfolio.yaml`. The template pin (`template.lock.json`) is always the
runtime's own: it is part of the Factory release. Relative guarded paths
(`factory.review.guarded_paths`) are guarded under both roots, and a game checkout may be
neither root nor contain one.

`wgf where [--json]` prints what a command resolved: `factory_root`, `installed`, `version`,
`project_root`, `config`, `store`, `workflow`.

## How the surfaces reach it

Claude Code substitutes `${CLAUDE_PLUGIN_ROOT}` in command, agent and skill content. Every
Factory path a Claude surface names is written as `${CLAUDE_PLUGIN_ROOT}/runtime/...`, and
the engine as `python3 "${CLAUDE_PLUGIN_ROOT}/runtime/scripts/wgf.py"`
(`scripts/gen-adapters.sh`, `claude_paths`). `test_adapter_binding` fails on a Claude
surface naming `core/`, `docs/`, `scripts/` or `bin/wgf` relative to the working directory,
and on a runtime path that is not in the bundle.

`/web-game-factory:new-game`'s preflight is `wgf where --json`: it stops unless the runtime
is installed and its workflow exists, and reports the project and store the run will use.
`--mock`, `--hold-gates`, `--project <ID>` (the run's title id), `--from` and `--store` mean
what they always meant; none of them chooses where the Factory is.

## What still assumes the working directory

- **The Codex adapter** (`codex-web-game-plugin/`) has no plugin-root substitution. It still
  runs from the factory repository root, and says so.
- `factory.assets.libraries` entries that are relative resolve against the working directory,
  as they did before; from an installed plugin that is the project unless `WGF_PROJECT_DIR`
  names another.
- `factory.develop.developer.argv` / `review.reviewer.argv` substitute `{factory}` with
  `ROOT`. The commented opt-in example in `workspace/config/factory.yaml` passes
  `--plugin-dir {factory}/claude-web-game-plugin`, which exists in a development checkout
  and not inside an installed runtime; an installation that enables it from the plugin names
  the plugin directory itself.

## Testing it

`scripts/tests/test_plugin_runtime.py`: new-game from an external project, from a Factory
checkout, from other projects and with `WGF_PROJECT_DIR`; a package built from a clean copy
of the source, installed, with the source deleted before it runs; and the package's contents
against the closure above.

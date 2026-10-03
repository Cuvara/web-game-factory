# Autonomous runs: `new-game` from research to the G4 decision without a person

The shipped configuration is **supervised**, and stays that way. An unattended run is a
project's explicit choice, made by copying one shipped profile into the project. Nothing
here removes a gate: G4 (kill), G6 (publish) and G7 (spend) are irreversible and a person
decides them, whatever any configuration says (`core/lifecycle/gates.yaml`, enforced by the
engine and by `decision-record.schema.json`).

## The default, and why

`wgf where` (and `/web-game-factory:new-game`'s preflight) reports what a run would do
without a person. With the shipped `workspace/config/factory.yaml`:

| `autonomy` | Default | Why it is the default |
|---|---|---|
| `developer` | `handoff` | The develop step writes a brief and waits (`WAITING_FOR_HUMAN`) until a person, or a session a person drives, finishes and runs `wgf resume <run> --decision done`. An unattended developer is an agent host with a shell, spending money: an installation opts in |
| `reviewer` | `none` | A skipped review is recorded, never an approval, and release then refuses the build (`unreviewed`): fail closed until a reviewer is configured |
| `auto_approve` | `[]` | G2 and G3 wait for a person. Only reversible gates may ever be listed |
| `timeout_auto_approve` | `{}` | No gate approves itself by waiting |
| `asset_author`, `model_author` | `none` | What no library supplies is a placeholder. Workflow 5 refuses placeholder art, so a supervised run brings its art in (a library, or a person's author) |
| `visualqa_judge` | `none` | visual-qa BLOCKS without a judge: it is never a silent pass |
| `init_source` | `github` | Passing G3 creates a repository under `factory.init.owner` with `gh repo create` - outward-facing and irreversible; `/new-game` asks before starting such a run |

Every one of these has an unattended alternative already in the Factory: the verified
headless Claude Code developer, read-only reviewer, asset author, model author and visual-QA
judge argvs (commented in the shipped `factory.yaml`, verified in
[claude-capabilities.md](claude-capabilities.md)),
`checkpoints.auto_approve`, `init.source: local` and `develop.budget`.

## The autonomous profile

`workspace/config/profiles/autonomous.yaml`, shipped in the plugin runtime, sets exactly
those, and nothing else:

| Key | Value | Effect |
|---|---|---|
| `develop.developer` | `kind: command`, the verified `claude -p` argv | Builds the game, and is re-entered with the failing qa-report or the review's requested changes (the workflow's own loops, `max_visits_by_route`) |
| `develop.budget` | `max_sessions: 12`, `max_cost: 60` (US$, from `total_cost_usd`) | develop blocks, nothing spawned, once reached; only a person raises it (`wgf resume <run> --budget-sessions N`) |
| `review.reviewer` | `kind: command`, the verified read-only `claude -p` argv | Approves or requests changes; the Factory fingerprints the checkout and undoes any write |
| `design` | `author: agent`, the verified read-only `claude -p` argv | Writes the design draft for a brief no design archetype carries; the module judges it unchanged, and shows it any schema or buildability problem for a bounded repair (`MAX_REPAIR_ROUNDS`) |
| `assets.model_author` | `kind: command`, `mode: set`, `spec_from: file`, `review_rounds: 1`; the read-only argv plus `Write,Edit` allowed only by `Edit(/{dir}/**)` | One session writes every 3D model of the design as a set (at most US$3 a call; one call per repair or review round); the pinned Blender 4.5 builds each spec, the Factory judges the GLB (`primitive_only`, silhouette, parts, palette) and renders contact sheets and the set, which the author opens to repair and to revise what does not read ([blender-pipeline.md](blender-pipeline.md), "Set mode"). Needs Blender on `PATH` or in `WGF_BLENDER` |
| `assets.author` | `kind: command`, `mode: set`, the verified `claude -p` argv: writes only under the Factory's `{out}`, runs only the Factory's `{preview}` | Draws every 2D requirement as ONE set in one session (at most US$6), from the whole visual identity, the art direction and the craft guides; runs the preview, which judges every file and renders the contact sheet it then looks at, and revises. The Factory judges again and delivers what passes; one repair session is shown what still fails and the last sheet ([assets-module.md](assets-module.md#the-set-author)) |
| `assets.producers` | `[fonts, audio]` | Bundles the typography's faces from the Factory font library and composes the music and sound effects; no agent, no network, no cost (the shipped default is `[]`) |
| `visualqa.judge` | `kind: command`, `verdict_from: stdout`, the verified read-only `claude -p` argv | Reads the captured frames and returns scores and findings (at most US$2 a judgement); the step decides PASS or FAIL and routes `assets` / `develop` |
| `checkpoints.auto_approve` | `[G2, G3]` | The two reversible gates in `new-game` are approved by the run, each with a decision record (`automation`) |
| `init.source` | `local` | A project from the pinned template, `git archive`-style, **no GitHub repository, no remote** |

The Factory still runs every check (install, conformance, typecheck, lint, unit, build,
smoke), makes the keyed development commit, verifies, and holds the guarded paths - the
Factory's own tree and the project's `workspace/config` - against the agents.

Without the two authors and the judge, workflow 5 cannot finish unattended: every asset is a
placeholder, `production-quality` refuses placeholder art and routes back to `assets`, which
makes the same placeholders until the loop limit blocks the run; and `visual-qa` blocks with
no judge. The model author and the judge have only `Read` - they print what they make, and
the Factory writes it. The 2D set author writes, but only SVG files under a scratch directory
the Factory owns (`{out}`), and runs exactly one command, the Factory's preview; the Factory
copies what passes into the checkout. None of them can change the checkout or the Factory.
`develop.budget` bounds the developer only; each other agent is bounded per call by its
`--max-budget-usd`. A drop-merge design's 22 drawings (10 pieces, 6 icons, the frame, the
backdrop, ...) are one set session, plus at most one repair session.

Fonts and audio need no agent: the profile sets `assets.producers: [fonts, audio]`. The
typography's faces come from the Factory font library (OFL WOFF2s shipped with the runtime,
`workspace/library/fonts`), and the design's music and sound effects are composed from its
audio direction and encoded by the Factory itself (Ogg Vorbis loops, WAV effects) - about a
minute per design, no network, no paid service, nothing a person must source. Before them
an unattended run could only ship a system font stack and an 8-second placeholder loop for
items its design marks `mvp`, which production-quality refuses. See
[assets-module.md](assets-module.md), "Fonts and audio: the producers". Still without a
producer: 3D textures (sky, sparks) and 3D VFX.

## Enabling it

In the target project (the working directory `/web-game-factory:new-game` runs in):

```bash
RUNTIME=$(ls -d ~/.claude/plugins/cache/cuvara/web-game-factory/*/runtime | sort -V | tail -1)
mkdir -p workspace/config
cp "$RUNTIME/workspace/config/profiles/autonomous.yaml" workspace/config/factory.yaml
python3 "$RUNTIME/scripts/wgf.py" where      # autonomy: developer=command, reviewer=command,
                                             # asset_author=command, visualqa_judge=command, ...
```

(`wgf where --json` lists the shipped profiles and their paths under `profiles`.)

The project's `workspace/config/factory.yaml` is **layered over** the shipped one key by key:
a mapping merges, a list or a value replaces. Edit the copy to change anything - a GitHub
repository (`init: {source: github}`), another budget, `design: {author: agent}` - and
remove a key to fall back to the shipped value. `wgf where` shows `config_layers`.

Copying the profile into a project whose run already started under the shipped config
changes that run's developer to a paid `command` one at once (the config is read live), but
not its budget, which a run takes when it starts. Such a run takes the profile's budget at
the next `wgf resume` by a person, recorded as a `BUDGET_ADOPTED` event; until then develop
refuses to start the developer (BLOCKED, naming `factory.develop.budget`). A command
developer never runs without a budget (development-module.md#budget).

The game checkout goes to `factory.checkouts` + the repository name, and the shipped
`checkouts` is `..`: beside the project. A project directory named like the game
(`my-game` for `--project my-game`) would then be the checkout itself, which init refuses
(BLOCKED, "is the Factory's own tree or its project"). Name the project directory
differently, or set `checkouts: ../games` (or any directory outside the project) in the copy.

Then, in Claude Code:

```
/web-game-factory:new-game --project my-game
```

The command reports the autonomy, says that agent sessions will run unattended and cost
money within the budget, and starts after you confirm.

Copy the profile **before** starting the run. A run snapshots its gate approvals
(`auto_approve`, `timeout_auto_approve`) and its develop budget when it starts, in its
`params`; the agents, the design author and `init.source` are read from the configuration
each time a step runs. A profile copied into a run that already started is therefore applied
by half: its authors, developer and init change, but its gates still wait for you and its
develop step has no budget it did not start with. `/web-game-factory:new-game resume <run>`
reports the run's own approvals and budget (`wgf status <run> --json`, `params`), not the
copied file's; start a new run to get the profile's.

## Research needs evidence, which the research role fetches

Research is autonomous but not evidence-free. It reads evidence snapshots from the project's
`workspace/research/snapshots/`, and live pages only from a `workspace/research/probes.yaml`
of probes a person wrote, with `discovery: {live: true}` (or `WGF_RESEARCH_LIVE=1`). With
neither, the run waits for input with *no external evidence* - by design: an observed claim
needs a source, and the profile does not turn that off
(`discovery.require_external_evidence` stays `true`).

That wait is an input, not a decision. `/web-game-factory:new-game` hands it to the research
agent, which captures snapshots from pages it actually fetches, per
`core/craft/research-evidence.md` (verbatim excerpts, the URL fetched, the time of retrieval),
then resumes the run. Evidence is fetched, never written: if nothing relevant can be fetched,
the command reports that and stops.

When the run has a game idea that no catalog concept carries, research also waits - it never
substitutes the nearest shape (`discovery.idea_fallback: wait`; `nearest` restores the
substitution on purpose). The research agent writes the idea's concept to the project's
`workspace/research/concepts.yaml` (its `brief` exactly the run's idea, `design_archetype:
agent`, every figure an estimate the scan records as a hypothesis), and the run is resumed.
Such a concept can only be designed by an agent design author, which the profile configures.

Research carries forward only a concept the design module can build: each entry of
`scripts/wgf_discovery/archetypes.yaml` declares its `design_archetype`, or `null`, and a
null one is kept in the report as *excluded, not buildable*. Today two concepts are
buildable - `endless-runner` (design `lane-runner`) and `match-3` (design `merge-puzzle`);
`scripts/tests/test_research_to_design.py` holds every declaration against the real design
step. Before this, 9 of 11 concepts reached design and failed its consistency rules.

## What stays human

| | |
|---|---|
| G4 prototype review | pass, iterate or kill - always a person: `! … wgf.py decide new-game-20261003-085640-5dc4c9 pass --note "hits the session target; retry reads well"`, the run id and the note your own |
| release | runs after a G4 pass; drafts only. `wgf new-game` ends there |
| publication | `wgf publish --run <run>` is a person's act. G5 (reversible; the autonomous profile does not auto-approve it either) and G6 (`publish`/`reject`: irreversible, always a person). The `submit` step is dry-run until an installation sets `factory.publish.mode: live` AND `WGF_PUBLISH_LIVE=1`; a login, CAPTCHA, second factor, unconfirmed portal terms or a missing session stops it for a person. G7 (spend) stays the game repository's, and human |
| budget | raising it after it is spent |
| evidence | nothing, when the research agent can fetch it; a person when it cannot |
| a GitHub repository | only if you set `init.source: github`, and `/new-game` asks first |

## Verifying a configuration without spending anything

```bash
python3 "$RUNTIME/scripts/wgf.py" where                           # what a run would do
python3 "$RUNTIME/scripts/wgf.py" new-game --mock --hold-gates    # profile: stops only at G4
```

`--mock` replaces every step with a placeholder, so no agent session starts. With the
profile, `--hold-gates` still stops at G4 only: G2 and G3 are the configuration's approvals,
not the mock's. Without it, `--mock --hold-gates` stops at G2 as before.
`scripts/tests/test_autonomous_profile.py` also runs the real research, strategy, design and
tech-plan steps under the profile and checks nothing waits before init, and holds every agent
argv in the profile to the shipped commented example (`TheWorkflow5Agents`: the authors and
the judge are those examples verbatim, have only `Read`, and their modules accept them).

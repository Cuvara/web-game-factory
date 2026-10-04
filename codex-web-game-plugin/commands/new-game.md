# /new-game (Web Game Factory)

**Workflow entry point** `core/workflows/new-game.workflow.yaml` — not a transition.
**Engine** `bin/wgf` (`scripts/wgf.py`), the Factory's only orchestrator.

This surface starts or resumes a run of the workflow above and reports it. The workflow file
is the single source of step order, retries, loops, gates, decisions and resume; nothing here
restates it, and nothing here decides for the engine or for a person.

Arguments: the text given with this prompt.

## Read first

1. `core/workflows/new-game.workflow.yaml`
2. `core/lifecycle/gates.yaml`
3. `docs/workflow-engine.md`
4. the factory configuration `bin/wgf where --json` reports: `config_layers` (the shipped
   file, then the project's own, layered) and the resolved `autonomy`

## The production bar

The run's agents are pointed at these craft playbooks by their briefs and requests - what a
finished build looks like, plays like and is checked against. Read them to report a run's
output honestly; never to steer a step, which is the engine's:

- `core/craft/production-art-and-ui.md`
- `core/craft/production-art-2d.md`
- `core/craft/production-art-3d.md`
- `core/craft/game-ui-kit.md`
- `core/craft/juice.md`
- `core/craft/production-wiring.md`

## Arguments

Accept exactly these (the engine's own flags, `bin/wgf new-game --help` and
`bin/wgf resume --help`), and nothing else:

- new run: `--mock`, `--mock-plan <JSON|@FILE>` (with `--mock` only),
  `--hold-gates`, `--project <ID>`, `--from <STEP>`, `--store <DIR>`, and at most
  one **game idea**: the quoted text that is not a flag or a flag's value, e.g.
  `"3D goalkeeper game where the player saves penalty kicks"`. The idea is the run's
  brief - research screens the catalog against it, strategy and design build from it - and
  `--project <ID>` is only the run's identity; never take one for the other. Pass the idea
  verbatim as one argument: never reword, summarise, translate, split or complete it, and
  never invent one. With no idea the run is a blank market scan: say so when you start it.
  An idea with `--from` a step after research is refused by the engine (exit 2).
- `resume <run-id>`, optionally with `--from <STEP>` and `--store <DIR>`: continues that
  run with the settings it started with - its idea among them, so an idea given with
  `resume` is refused
- `publish <run-id>`, optionally with `--store <DIR>`: continues a run that
  drafted a release into the workflow's `publish` group (`bin/wgf publish --run <run-id>`),
  with the settings that run started with

With `--store <DIR>`, pass the same `--store <DIR>` to every `bin/wgf` command for that
run (status, logs, resume).

Refuse, and run nothing, if the arguments contain anything else — in particular
`--decision`, `--note`, `decide`, `--budget-sessions`, `--budget-cost` or any other
`--budget-*` (a decision or a budget is a person's, typed by that person), `--config` or
`--workflow` (this surface runs this workflow under the configuration it reports),
`--resume`, `--run` or `--force` (use `resume <run-id>` or `publish <run-id>`), `--quiet` or `--json`
(the surface sets the output), a second command, or more than one idea (two quoted texts;
ask the user to give the idea as one quoted string).

## Procedure

1. **Preflight.** Stop unless `core/workflows/new-game.workflow.yaml` exists in the working directory
   (run from the factory repository root). For `resume <run-id>` and `publish <run-id>`, read
   `bin/wgf status <run-id> --json` first and stop unless `workflow_id` is `new-game`.
   Then act on it without starting anything when there is nothing to continue:
   `COMPLETED` — report it (step 6) - for `publish <run-id>`, a run that drafted a release is
   continued (step 4) rather than reported: its `publish` group has not run yet; `RUNNING` with liveness `running` — another
   process drives it, only report progress; `WAITING` at a gate whose `pending.timeout`
   is not `eligible` — report the gate (step 6) and stop. `FAILED` or `BLOCKED` —
   report it first as step 6 does, with why: `blocked_reason` and the logs of the step at
   `cursor`, its last agent message among them. Resuming re-runs that step, and a
   deterministic failure fails again: resume only when the user confirms, after that report,
   with step 3's warning for any agent session it starts; otherwise stop. Anything else (a
   stopped, cancelled or stale run, or one waiting for input) is resumed at step 4.
2. **Report the effective autonomy** — never change it. For a new run, from `where`'s
   `autonomy`, as configured: `developer`, `reviewer`, `design_author`,
   `asset_author`, `model_author`, `visualqa_judge`, `auto_approve` (and
   `timeout_auto_approve`), `init_source`, `develop_budget`. A run that already exists
   keeps what it started with: `auto_approve`, `timeout_auto_approve` and
   `develop_budget` are the run's `params` in `bin/wgf status <run-id> --json` (a key
   that is absent there is none - no gate approves itself, no develop budget), never
   `where`'s; the agents and `init_source` are read from the configuration when each step
   runs, so those are `where`'s. When the two differ, say so: a configuration changed after
   the run started does not change which of its gates approve themselves. With `--mock`
   every step is a placeholder, and a mock run approves the reversible gates itself unless
   `--hold-gates` is given; gates in `auto_approve` are approved either way - report the
   gates that were approved, never the list as if it had happened. An unattended run is the
   project's own choice (`profiles` lists the shipped overlays, e.g. `autonomous`); never
   install one.
3. **Outward effects.** For a new run without `--mock` (a mock run starts no session and
   creates nothing): with `init_source` `github`, warn that once G3 is passed the init
   step creates a GitHub repository (`gh repo create`); with a `command` developer,
   reviewer, asset or model author or visual-QA judge (or an `agent` design author), say
   that agent sessions will run unattended and cost money, within `develop_budget` when
   one is set (the budget bounds the developer; each other agent has its own per-call cap). Either way, start that run only after the user
   confirms. A `--mock` run, or a run with neither, starts without asking.
   For `publish <run-id>`, say before starting that nothing reaches a portal until a person
   decides G6, and that a portal submission after it is a dry run unless the installation
   set `factory.publish.mode: live` and `WGF_PUBLISH_LIVE=1` - never set either. It
   starts without asking.
4. **Start** as a long-running background process, not a blocking call: a run can take hours.
   Poll `bin/wgf status <run-id>` for progress.

   - new run: `bin/wgf new-game <flags> --json`, or with an idea
     `bin/wgf new-game <flags> --json -- '<idea>'`: the idea last, after `--`, as one
     single-quoted shell word (each `'` inside it written as `'\''`), so the shell
     neither splits nor expands it and a leading `-` is not read as a flag. Tell the user
     the idea as the engine recorded it: `params.idea` in `WORKFLOW_STARTED`, whitespace
     runs collapsed and nothing else changed - or that there is none.
   - resume: `bin/wgf resume <run-id> [--from <STEP>] [--store <DIR>] --json`
   - publish: `bin/wgf publish --run <run-id> [--store <DIR>] --json`

   Where `bin/wgf` cannot be executed (Windows), use `python scripts/wgf.py` in its place.
   Read `run_id` from the first event, `WORKFLOW_STARTED` (on resume, `WORKFLOW_RESUMED`),
   and tell the user.
5. **Progress.** Summarise `STEP_STARTED`, `STEP_COMPLETED` and `STEP_FAILED` events as they
   arrive. For detail: `bin/wgf status <run-id>` or `bin/wgf status <run-id> --json`.
   Retries, loops and resume belong to the engine: report them, never re-run a step, edit
   `.factory/`, or edit an artifact to move the run along.
6. **When the process exits**, read `bin/wgf status <run-id> --json` and act on the run's
   status (the process's exit code is the same contract: 0, 1, 2, 3):
   - **COMPLETED** (exit 0): report the run id, the artifacts it produced and the
     release-manifest draft. If `ended_by` is set — `Ended: kill at G4` — report the kill
     as the end of the title, never as a release.
   - **FAILED, BLOCKED or CANCELLED** (exit 1): show `status`, `cursor`, `blocked_reason`
     and `bin/wgf logs <run-id> --step <cursor>`. A release refused as `unreviewed` is
     the configured reviewer (`factory.review.reviewer.kind: none`) doing its job: report
     it; do not configure a reviewer or weaken the release. Suggest
     `/new-game resume <run-id>` or `bin/wgf resume <run-id> --from <STEP>`; fix nothing.
   - **Usage error** (exit 2, no run started): show stderr.
   - **WAITING or PAUSED** (exit 3): show `pending` — step, gate, choices, evidence — and
     `blocked_reason` if any, then stop. See the rule below. `pending: null` means the
     run waits for input, not a decision: report `cursor` and `message`.
   - **WAITING for input at `research`** (`pending: null`, cursor `research`): the input
     is the research role's, not a person's decision. Follow `codex-web-game-plugin/agents/research.md`, working per
     `core/craft/research-evidence.md`: with *no external evidence*, it captures snapshots
     from pages it actually fetches into the project's `workspace/research/snapshots/`;
     when *the brief matches no concept research can carry*, it also writes the brief's
     concept to `workspace/research/concepts.yaml`. Then resume the run (step 4) and
     continue. Evidence is fetched, never written: if nothing relevant can be fetched, report
     that and stop. Never edit `.factory/` or an artifact, and never relax a setting.
7. **Result.** Run id, final status, artifacts, and what comes next. `bin/wgf new-game` ends
   at a drafted release (a `--mock` run stops earlier, at G4). Publication is the workflow's `publish` group, in the same run:
   `/new-game publish <run-id>` (`bin/wgf publish --run <run-id>`) validates the release per
   platform and stops at G5 and then G6, each a person's decision; the portal submission
   follows only a G6 `publish`, is a dry run unless the installation made it live, and
   waits for the person's login and, after an upload, for the person's submit confirmation
   (`docs/publish-module.md`).

## The gate rule

Never run `bin/wgf decide`, `wgf resume ... --decision`, or anything else that answers
a checkpoint — for any gate, and for the develop handoff. Commands run from this session are
recorded as a person's decision, so answering one would forge a human decision. Tell the user
how to decide, and stop. A decision is the engine's resume: typed by the user, it records the
decision and drives the run on, in the user's own shell, to its next stop — and a real run's
next stop can be hours away. `/new-game resume <run-id>` afterwards reports where it
stopped, and continues it if that shell was interrupted.

- at a gate: one complete line per choice in `pending.choices`, the run id and the choice
  filled in - never `<run-id>`, `<choice>` or `a|b`, which the shell reads as
  redirections and pipes - and a note for the user to replace with their own reason, which
  is the decision record's only reason. At G4 of run `new-game-20261003-085640-5dc4c9`:

  - `! bin/wgf decide new-game-20261003-085640-5dc4c9 pass --note "replace: why it passes"`
  - `! bin/wgf decide new-game-20261003-085640-5dc4c9 iterate --note "replace: what to change"`
  - `! bin/wgf decide new-game-20261003-085640-5dc4c9 kill --note "replace: which criterion"`

  Say that the note must be replaced before the line is run, then `/new-game resume <run-id>`
- at `develop` with `factory.develop.developer.kind: handoff` (`pending` names no gate):
  report the step, its message and the brief path it gives; the developer finishes the work
  and runs `! bin/wgf resume <run-id> --decision done`, then `/new-game resume <run-id>`.
  Development is not complete until the engine says so.
- in the `publish` group, at a portal visit (the run's `message` names the waiting
  platforms; each one's `platform-publication` record carries its `waiting` block):
  - WAITING_FOR_HUMAN_LOGIN: the portal's console is open in a headed browser window. Tell
    the user to log in there and to handle any CAPTCHA or second factor themselves. Never
    ask for, accept, type or store a password, one-time code, cookie or token. A timed-out
    login or a closed window is a wait, not a failure: `/new-game resume <run-id>` opens
    the window again.
  - WAITING_FOR_HUMAN_SUBMIT_CONFIRMATION: the build is uploaded and saved as a draft, and
    nothing has requested review. Its choices - submit (request review once), hold, abandon,
    done (requested by hand) - are the user's, one line per choice as at a gate.

  Never operate a portal page yourself: the step's executor is the only browser actor.

Do not change the factory configuration to make a run more autonomous, and do not
advance a lifecycle state: the engine never moves one, and neither does this surface.

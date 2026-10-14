# The visual QA module

`scripts/wgf_visualqa/` implements the `visual-qa` step type. In the production phase it
runs after `playability` has played the production build (and, when the workflow has it,
after `production-quality` has measured it), before `review`
([production-architecture.md](production-architecture.md)). In `new-game` (workflow 5) it
follows `production-quality`; route `assets` goes to `assets` (budget `visual-qa.assets: 2`),
route `develop` to `develop` (`visual-qa.develop: 2`), and `release` refuses unless the
newest report is PASS for the development commit it ships.

```
... develop -> playability -> production-quality -> visual-qa -> review -> ...
                                                       │ FAIL route assets  -> assets
                                                       │ FAIL route develop -> develop
```

## Why it exists

Playability measures what a bot can: lit pixels, entity sizes from the play probe, an
action acknowledged on screen. It cannot tell a goalkeeper from a grey capsule, a styled
button from a browser default, or a finished arena from an empty void. A person can, at a
glance - and so can an agent able to read images. Visual QA asks one, with a rubric fixed
before the build exists, and keeps the decision with the Factory: the judge scores and
finds; the step decides.

It is an agent's reading of frames (`measurement_class: automation-agent`), never what
first-time players see or understand.

## Inputs and output

| | |
|---|---|
| `playability-report` (required) | its `frames[]`: id, viewport (`project`), `path` relative to the run directory, `sha256`; its `projects[].viewport` |
| `game-design` (required) | `build_spec.visual_identity` (concept, palette, typography, shape language, avoid, `primitive_style`, `ui`), `build_spec.assets[]` (`role`, `readability`) |
| `asset-manifest` (required) | per item: `role`, `source`, `placeholder`, `quality` |
| `production-quality-report` (optional) | its failed checks, to confirm or dismiss by eye |
| `visual-qa-report` (output, 1.3.0) | `scores` and the judge's `score_reasons`, `findings`, `states` (answers, comment, frames), `look` (verdict, reason), `failed`, `routes`, `verdict`, the frames judged, the `rubric` pinned by sha256, `judge_runs`, `judge_repairs` and `coercions` (see "Repair rounds and coercion") |

The report is emitted on PASS, FAIL and BLOCKED. A judge that could not produce a usable
verdict leaves no report (nothing was judged); its brief, log and raw output stay under
`<run>/visual-qa/<step>-<visit>-<attempt>/`.

## The rubric

`core/reference/visual-qa-rubric.yaml`: eight dimensions, each scored 0-5 with anchors for
0, 3 and 5, and the route a low score goes back to:

| dimension | route | | dimension | route |
|---|---|---|---|---|
| `art_completeness` | assets | | `typography` | develop |
| `character_readability` | assets | | `composition` | develop |
| `environment` | assets | | `consistency` | assets |
| `ui_polish` | develop | | `no_debug` | develop |

and blocker rules the judge must raise as `severity: blocker` whatever its scores:
`primitive-entity` (a readable entity drawn as a plain cube, sphere, capsule or rectangle
without `primitive_style`; assets), `missing-asset` (assets), `browser-default-ui`
(develop), `debug-output` (develop), `unreadable-frame` (develop, or assets when the art
itself is unreadable), `cropped-play` (develop), and (rubric 1.3.0) `celebration-hidden` (a
win frame whose result card covers the goal and its celebration while it plays; develop, ui)
and `effect-floods-screen` (an interaction effect covering the play; develop, composition).

Per state - `initial`, `gameplay`, `interaction`, `win`, `loss`, `retry`, on each viewport
that has frames of it - the judge answers the rubric's `state_questions` true, false or
null (nothing on screen the question is about): `entities_recognisable` (assets),
`primitives_or_placeholders` (assets; waived by `primitive_style`),
`lighting_materials_coherent` (develop; null in 2D), `typography_readable` - and not a
fallback font (develop), `buttons_polished` - not browser defaults (develop),
`objective_obvious` (initial, gameplay, interaction; develop), `outcome_understandable`
(win, loss, retry; develop), and (1.3.0) the feedback visuals: `feedback_visible`
(interaction; develop) - the frame after the action shows a designed effect acknowledging it,
more than a few flat specks, leaving the play readable - and `celebration_visible` (win;
develop) - the win is celebrated on screen and the celebration is not hidden behind the
result card. The brief lists the design's `build_spec.vfx` effects for these two. And once,
the `look`: `finished-game`, `unremarkable` (competent
but plain) or `developer-prototype`. The brief shows the judge the installation's quality
bar (`workspace/quality-bar/`, `wgflib.quality_bar`) as what a 4 and `finished-game` look
like.

**Decision** (`rubric.decide`): FAIL when any finding is a blocker, any dimension is below
`pass_bar` (3), the mean of all scores is below `mean_pass_bar` (3.5; each dimension below 4
then contributes its route), any per-state answer equals its question's `fail_when`, or the
look is anything but `finished-game`. `failed` lists `finding:<id>`, `score:<dimension>`,
`state:<viewport>/<state>:<question>` and `look:developer-prototype`; `routes` the routes
of every failure, `assets` before `develop`; the step's route is the first. A `major` or
`minor` finding is recorded and does not fail the build on its own. The report lists every
rubric state on every viewport; one no frame shows is `captured: false`, unanswered.

## What a failure sends back

A FAIL is only useful if the agent who fixes it can see what the judge saw. The report keeps
the judge's words beside every failure - a score's `score_reasons` entry, a state's
`comment` and `frames`, the look's `reason`, a finding's `summary` and `frame` - and both
receivers get them with the absolute paths of the frames (frame `path`s are relative to the
run directory):

- **Route `assets`** (`scripts/wgf_assets/feedback.py`, [assets-module.md](assets-module.md#re-entry)).
  Every failure routed `assets` - findings of any severity, failing scores, state answers and
  the look - is mapped to the design's asset requirements by id, by role word ("the
  player"), by the play probe's entity -> asset records and by the rubric's `rebuild_roles`
  (`rebuild` at the end of the rubric: which roles `environment`, `character_readability`,
  `art_completeness`, `consistency`, the look, `primitive-entity`, `entities_recognisable`
  and `primitives_or_placeholders` concern). Each remade asset's author gets the reasons and
  the frames, and is told to open them. Nothing resolving remakes every readable entity and
  the scene; nothing able to remake (no author) blocks the assets step rather than reuse
  every file.
- **Route `develop`** (`scripts/wgf_develop/brief.py`, "Fix first: what visual QA saw").
  Every `failed` entry with its reason - the score's reason, the state's comment and frames,
  the look's reason, the finding's frame - and every `major` finding that did not fail the
  build on its own.

## Outcomes

| | |
|---|---|
| SUCCESS | PASS |
| FAILED, route `assets` / `develop`, not retryable | FAIL: the workflow routes it back |
| BLOCKED (with a report) | no judge configured (`kind: none`) - visual QA needs a judge and is never a silent pass; no frames in the playability-report; a frame no longer on disk |
| FAILED, not retryable | a verdict still malformed once the repair rounds and both fresh attempts are spent (`malformed-verdict`, with the last errors); a judge that could not start, or that changed a frame or a guarded path; a frame whose sha256 is not the one playability recorded; bad configuration or rubric |
| FAILED, retryable | the judge timed out, went idle, or exited non-zero |
| WAITING_FOR_INPUT | a required input is not in the run |
| BLOCKED (no report) | the run pinned the rubric (new-game `pinned_references`) and its copy is gone, or was edited after the run started |

## The judge

Configured like the reviewer, under `factory.visualqa.judge` in
`workspace/config/factory.yaml` (`scripts/wgf_visualqa/settings.py`):

```yaml
visualqa:
  judge:
    kind: command             # none | command
    argv: [...]               # {frames_dir} {brief} {verdict} {prompt}
    timeout_seconds: 900
    idle_timeout_seconds: null
    verdict_from: stdout      # file: it writes {verdict} | stdout: the last JSON object printed
  # rubric: core/reference/visual-qa-rubric.yaml
```

**Which rubric.** Without `rubric`, the step reads the copy of
`core/reference/visual-qa-rubric.yaml` the run pinned when it started (new-game
`pinned_references`, scripts/wgflib/workflow/references.py): an edit made while the run is
going applies to the next run, never to this one's build, and the quality gate holds the
visual scores to the same pinned file. A copy whose digest is not the one the run recorded
blocks the step. A run that pinned nothing reads the live file. A `rubric` configured by path
is read as configured. The report's `rubric` names the file read and its sha256.

The shipped config has `kind: none` and a commented, read-only headless example: the only
tool in the session reads files (the brief and the PNG frames, which the host reads as
images), nothing is prompted, no settings, hooks, plugins or MCP servers load, and the
host's own budget flag bounds a judgement.

What the step does around it (`scripts/wgf_visualqa/judge.py`):

1. **Stage.** Every frame is copied to `<workdir>/frames/<viewport>/<frame-id>.png` after its
   sha256 is checked against the playability-report. The judge reads copies in a directory
   that holds nothing else - never the run's evidence, never a game checkout.
2. **Brief.** `<workdir>/<step>-<n>.brief.md`: a table of every frame (its id in the verdict,
   viewport size, image size, state - boot, idle, playing, before/after an action, won,
   lost - and file), the visual identity, the asset roles and readability lines with the
   manifest's placeholder and quality flags, failed production-quality checks, the rubric
   and blocker rules, the (state, viewport) pairs to answer with their frames and the
   questions, the look question, and the verdict shape.
3. **Run.** The argv, cwd the workdir, with wgflib.agentenv's allowlisted environment
   (plus `factory.agents.env_passthrough`) and `WGF_VISUALQA_FRAMES|BRIEF|VERDICT`; one
   owned process tree through wgflib.procs, ended on timeout, idle or cancel.
4. **Isolation.** The staged frames and the Factory's guarded paths
   (`factory.review.guarded_paths`) are fingerprinted before and after. A judge that
   changed either fails the step; guarded paths are restored.
5. **Verdict.** Parsed strictly (`rubric.parse`): every dimension scored, a number 0-5, no
   other keys; findings with a unique kebab-case `id`, `severity`, `category`, `route`,
   a `frame` that is one of the given ids or null, and a summary; exactly one `states`
   entry per (state, viewport) with frames, answering exactly its questions; a `look` among
   the rubric's values; `score_reasons`, when given, strings for rubric dimensions only (the
   brief asks for one per dimension; a verdict without it is still well formed). Before
   the check, shapes that cannot change meaning are coerced and recorded; a verdict that
   still fails it goes to a repair round (below).

### Repair rounds and coercion

The verdict is long - one entry per (state, viewport), each answering five or six
questions, plus eight scores and their reasons - and a judge that read every frame
correctly occasionally writes it slightly wrong: one answer left out of one state, or a
reason wrapped in a list. Throwing that judgement away and paying for a fresh one is the
wrong repair, and before 2026-10-04 two such slips failed the run (`malformed-verdict`).

**Coercion** (`rubric.coerce`). Only what cannot change what the judge said: surrounding
whitespace on an id or enum value (`" blocker"`, a frame id), the case of an enum value
(`"Finished-Game"`, `"ASSETS"`) or of a key the rubric names (a dimension, a question id,
a top-level key), and a one-item list of a string where a string is asked for (a
`score_reasons` value). Each coercion is recorded in the report's `coercions` as `{path,
rule, from, to}` (rules `strip-whitespace`, `enum-case`, `key-case`,
`unwrap-one-item-list`) and logged. Never coerced, because it would need a guess: a missing
key, a missing answer, a missing state, a score written as a string, a boolean written as
`"yes"`, a list of two reasons, an unknown key.

**Repair round.** A verdict that still fails the check goes back to the judge: a new brief,
`<step>-<n>.brief.md`, opens with "Repair your previous verdict", every validation error
the check found (all of them, not the first only - `rubric.problems`), and the judge's own
previous reply verbatim (cut at 200,000 characters), then the whole brief again. The judge
is asked for the corrected verdict in full, to keep every judgement the errors do not
touch, to answer a missing question from that state's frames (`null` when the frames
cannot tell) and never to drop a question or a state. What comes back goes through the
same coercion and the same check; nothing the judge left out is ever filled in by the
step.

**Budgets.** `factory.visualqa.judge.repair_rounds` (default 2, 0-10) counts repair rounds
for the whole judging, separately from fresh attempts (`judge.MAX_JUDGE_RUNS`, 2). A
malformed verdict goes to a repair round while any are left and the judge replied
something; otherwise to the second fresh attempt (the brief from scratch, with the last
problem at the top); with neither left, the step FAILS as before - `malformed-verdict`,
not retryable, with the last errors. The default is therefore at most four judge
invocations: fresh, repair, repair, fresh. `repair_rounds: 0` is the old behaviour, two
fresh attempts. The report's `judge_runs` counts every invocation and `judge_repairs` the
repair rounds among them; each invocation's brief, log and verdict stay in the workdir.

The judge writes:

```json
{
  "scores": {"art_completeness": 0, "character_readability": 1, "...": 5},
  "score_reasons": {"art_completeness": "the keeper is an untextured capsule in every frame",
                    "...": "..."},
  "findings": [{"id": "primitive-keeper", "severity": "blocker", "category": "assets",
                "frame": "desktop/play-2s", "summary": "...", "route": "assets"}],
  "states": [{"state": "gameplay", "viewport": "mobile",
              "answers": {"entities_recognisable": false, "primitives_or_placeholders": true,
                          "lighting_materials_coherent": null, "typography_readable": true,
                          "buttons_polished": true, "objective_obvious": false},
              "comment": "..."}],
  "look": "developer-prototype",
  "look_reason": "...",
  "notes": "optional"
}
```

## The baseline judge

`kind: baseline` (`scripts/wgf_visualqa/baseline.py`) is no agent. For a game whose look was
approved once - a golden run's reference port - "does this look finished?" has a mechanical
answer: does each frame look like the approved frame of the same state?

```yaml
visualqa:
  judge:
    kind: baseline
    baseline_dir: <dir>       # <viewport>/<name>.png - the approved frames
    min_similarity: 0.70      # optional (baseline.MIN_SIMILARITY)
```

Approved frames are grouped into the rubric's states by file name: a state id
(`gameplay.png`), a common name (`title` -> initial, `merge`/`paused` -> interaction,
`near-full` -> gameplay, `game-over` -> loss, `retry-playing` -> retry; `baseline.NAMES`), or
`<baseline_dir>/states.json` (`{"<stem>": "<state>" | null}`; the 3D port maps `steer`,
`near-miss`, `close-wall`, `crash`). Runtime frames get their state from their id, as the
brief shows a command judge - the bot's `state-<screen>` frames included.

Each frame is compared with every approved frame of its state and viewport by a measure that
tolerates two plays of one finished game (where the pieces are, animation timing, the score)
and fails what a regression to primitives, placeholders or missing art changes: palette
(512-bin colour histogram intersection, weight 0.5), detail (share of sampled neighbours that
differ by an edge, 0.2) and large-scale layout (a 16x9 grid of mean colours, 0.3). Its best
match must reach `min_similarity`.

- A frame below the bar is a **blocker** finding (`baseline-regression-<frame>`, category
  `assets`, route `assets`); its state answers `entities_recognisable: false` and
  `primitives_or_placeholders: true`; the look is `developer-prototype`.
- A runtime state with no approved frame on that viewport (`no-baseline-...`), or an approved
  state no frame shows (`baseline-unseen-...`), is a **minor** finding: reported, never a
  pass or a failure on its own.
- Scores are no aesthetic judgement: every dimension at the pass bar when nothing regressed,
  the asset dimensions 0 when anything did. The report's notes say so; `judge.kind` is
  `baseline`, `judge_runs` 1, every comparison in `<workdir>/baseline.json`.

The verdict goes through `rubric.parse` and `rubric.decide` like any judge's.

**Calibration** (2026-10-01; the golden ports at template `wgf-golden-production`, each
port's approved frames under `examples/<example>/wgf-golden/baseline`; every frame the
playability bot captured, 26 per run on desktop and mobile):

| Frames | Tower Merge Rush (2D) | Neon Drift Arena (3D) |
|---|---|---|
| the same port **without its art** - the greybox phase lays the whole port before any asset exists, so it draws its primitive fallback | 0.454-0.685: every frame fails | 0.534-0.775: 22 of 26 fail; the DOM-dominated pause and game-over screens reach 0.70-0.77 |
| the same port with its library removed - the assets step's placeholders in the runtime manifest (`run.py --no-library`; the build captured with the port's own `baseline/capture.mjs`, 14 frames) | 0.365-0.523: every frame fails | - |
| the finished port, production phase of a golden run | 0.764-0.990 | 0.805-0.991 |
| the finished port, a second golden run | 0.766-0.990 | - |

The bar is 0.70: the finished ports pass every frame, and a port with placeholder art or
none fails the verdict (any regressed frame is a blocker) on both. The `--no-library` golden
run itself stops earlier: its develop step fails on the port's own art-guard browser test,
which refuses placeholder art, so the frames above were captured outside the run. The 3D overlap is where a screen is
mostly DOM - a pause or result card over a dark scene looks alike with or without the
models - so the verdict rests on the gameplay frames there. `min_similarity` raises the bar
per installation. The runs: docs/golden-runs.md.

## Outside a run

`scripts/wgf-visualqa.py` runs exactly the same staging, brief, judge, isolation, parse and
decision over frame directories, so a person can read what the judge saw and said:

```bash
python3 scripts/wgf-visualqa.py \
  --frames <run>/playability/1-1/out/desktop/frames \
  --frames <run>/playability/1-1/out/mobile/frames \
  [--design game-design.json] [--manifest asset-manifest.json] [--title ID] \
  [--judge-argv '["claude", "-p", "{prompt}", ...]' --verdict-from stdout] \
  [--out DIR] [--brief-only] [--json]
```

The judge defaults to `factory.visualqa.judge`. Exit 0 PASS, 1 FAIL, 2 unusable (no judge,
no frames, a judge failure).

## The mock

`--mock` runs `MockVisualQAStep` (`scripts/wgflib/workflow/mock.py`) with the fixture
`fixtures/visual-qa-report.json`: PASS by default; a plan entry `assets` or `develop` (or
`fail`, = develop) returns FAILED with that route and a blocker in the report.

## Tests

`scripts/tests/test_visual_qa.py` runs the step with a fixture command judge and the
baseline judge (`BaselineJudge`: frames like the approved ones pass, flat frames fail routed
to assets, unmatched states reported, bad configuration, the measure's tolerance), and: pass, a
primitive-entity blocker routed to assets, debug output routed to develop, a dimension
below the bar, a per-state answer routed by its question, a developer-prototype look,
`primitive_style` waiving only the primitive answer, unanswered or extra states, a verdict
on stdout, a malformed verdict sent to two repair rounds and a fresh attempt then failed
(and `repair_rounds: 0` failing after two fresh attempts, and one fixed on the repair), a
verdict missing one answer fixed in a repair round (with the errors and its own reply in the
repair brief), a judge that never fixes it failing with the errors, a one-item list
`score_reasons` value coerced and recorded, every error reaching the repair round at once,
coercion changing no meaning and inventing nothing, the required questions unchanged, the
`repair_rounds` setting, an unknown frame id, no judge (BLOCKED), a non-zero exit (retryable),
a changed and a missing frame, a judge writing to a frame or a guarded path, the mock, the
CLI harness, the judge's `score_reasons` reaching the report (and checked when malformed),
and the rubric's `rebuild_roles` for every `assets` failure. What a failure sends back is
tested where it lands: `test_assets_production.py` (re-entry, including the real arena-dodge
verdict that must remake the player) and `test_develop_module.py` (the brief).

## Calibration

Run on 2026-10-01 with the commented example judge (CLI 2.1.280, `--model sonnet`,
`--safe-mode --tools Read`, `--max-budget-usd 2`, text output), through
`scripts/wgf-visualqa.py`, on frames the playability step captured of real builds (desktop
1280x720 and mobile 393x851):

- Goalkeeper Royale (known bad: dark, primitive characters):
  `/tmp/play-gk/playability/1-1/out/{desktop,mobile}/frames`, 14 frames
- Tower Merge Rush, the template's golden 2D port (procedural tiles):
  `/tmp/play-2d/playability/1-1/out/{desktop,mobile}/frames`, 16 frames
- Neon Drift Arena, the template's golden 3D port (procedural flat shapes):
  `/tmp/play-3d/playability/1-1/out/{desktop,mobile}/frames`, 16 frames

No game-design or asset-manifest exists for these frames, so each brief said "the design
gives no visual identity" and the rubric's no-`primitive_style` rule applied. The bot
captures no frame after a retry, so `retry` is reported `captured: false` for every game.

**Round 1** (scores and findings only):

| game | verdict | route | judge runs | time |
|---|---|---|---|---|
| Goalkeeper Royale | FAIL | assets | 2 | 214 s |
| Tower Merge Rush | FAIL | assets | 1 | 95 s |
| Neon Drift Arena | FAIL | assets | 1 | 82 s |

What it changed: Goalkeeper's first verdict wrote every score as a string (`"1"`) - the
brief's verdict shape showed scores as the quoted placeholder `"0..5"` and the judge copied
its type. It was rejected and the retry was well formed. The shape now shows
`<number 0-5>` / `<true | false | null>` and says "a JSON number".

**Round 2** (the contract above: per-state answers and the look, added so the judge answers
for every state and viewport whether entities are recognisable production assets, anything
is a primitive or placeholder, 3D lighting and materials are coherent, type is readable and
not a fallback font, buttons are styled, the objective is obvious and the outcome
understandable - and whether the whole is a finished game or a developer prototype):

| game | verdict | route | look | judge runs | time | blockers |
|---|---|---|---|---|---|---|
| Goalkeeper Royale | FAIL | assets | developer-prototype | 1 | 163 s | primitive keeper and goal (assets), missing end-screen icon (assets), unreadable dark play (develop) |
| Tower Merge Rush | FAIL | assets | developer-prototype | 1 | 111 s | primitive tiles (assets), HUD text clipped by the pause button (develop) |
| Neon Drift Arena | FAIL | assets | developer-prototype | 1 | 140 s | placeholder rectangle entities (assets) |

Every verdict was well formed on the first run. Cost is not reported in text mode; no run
reached the US$2 cap.

Reading the verdicts: Goalkeeper fails as expected - primitive characters, a dark arena,
`character_readability` 0, entities unrecognisable in every play state, the objective not
obvious during play and the loss not understandable. Both golden ports fail too, as the
production architecture expects of procedural art: flat rectangles standing for every
entity, `art_completeness` 1, `developer-prototype`. The judge also found layout defects no
bot measures: the pause button clipping the 2D port's HUD text, and the 3D port's mobile
text running behind it (`typography_readable: false` on mobile). Neon Drift Arena's art
direction is geometric; judged with a design that states `primitive_style`, its
`primitives_or_placeholders` answers would not fail it (its blocker finding and the look
still would) - judge a game with its design.

Goalkeeper Royale, round 2, verbatim:

```json
{
  "scores": {
    "art_completeness": 1,
    "character_readability": 0,
    "environment": 1,
    "ui_polish": 3,
    "typography": 3,
    "composition": 1,
    "consistency": 3,
    "no_debug": 5
  },
  "findings": [
    {
      "id": "primitive-keeper-and-goal",
      "severity": "blocker",
      "category": "assets",
      "frame": "desktop/act-dive-after",
      "summary": "The keeper and goal are flat-shaded trapezoid and pentagon primitives with no texture, shading, or distinguishing features - indistinguishable from stand-in shapes.",
      "route": "assets"
    },
    {
      "id": "missing-end-screen-icon",
      "severity": "blocker",
      "category": "assets",
      "frame": "desktop/end-lost",
      "summary": "The badge/result icon on the end screens (and the lime square under 'New best!' on mobile) is a flat, untextured colour rectangle reading as a missing or unloaded asset.",
      "route": "assets"
    },
    {
      "id": "unreadable-play-darkness",
      "severity": "blocker",
      "category": "readability",
      "frame": "desktop/play-2s",
      "summary": "Two seconds into play the scene is almost entirely black; the goal and keeper blend into the background and are barely distinguishable from it.",
      "route": "develop"
    },
    {
      "id": "mobile-shrunken-desktop",
      "severity": "major",
      "category": "composition",
      "frame": null,
      "summary": "On mobile the play area is the same size and position as on desktop, floating in the middle of a much taller black canvas with large empty bands above and below instead of a layout designed for portrait.",
      "route": "develop"
    },
    {
      "id": "ambiguous-loss-messaging",
      "severity": "major",
      "category": "ui",
      "frame": "desktop/end-lost",
      "summary": "The loss screen reads only 'Full time' with no failure indicator (no 'you lost' wording, warning colour, or icon), so a player cannot tell at a glance that they lost rather than simply that the match ended.",
      "route": "develop"
    },
    {
      "id": "empty-environment",
      "severity": "minor",
      "category": "assets",
      "frame": null,
      "summary": "The play scene is a near-black void with only a faint ground-colour gradient; there is no background detail, prop, or lighting to give the arena a sense of place.",
      "route": "assets"
    }
  ],
  "states": [
    {
      "state": "initial",
      "viewport": "desktop",
      "answers": {
        "entities_recognisable": false,
        "primitives_or_placeholders": true,
        "lighting_materials_coherent": null,
        "typography_readable": true,
        "buttons_polished": true,
        "objective_obvious": true
      },
      "comment": "The waiting shot shows the keeper and goal as flat, featureless primitives in a near-black void; the 'tap the glowing zone to dive' text states the action, but after the idle grace the capture shows the full loss/end screen rather than a true idle pose."
    },
    {
      "state": "initial",
      "viewport": "mobile",
      "answers": {
        "entities_recognisable": false,
        "primitives_or_placeholders": true,
        "lighting_materials_coherent": null,
        "typography_readable": true,
        "buttons_polished": true,
        "objective_obvious": true
      },
      "comment": "Same content as desktop but centred in a much taller canvas, leaving large empty bands above and below; the instruction text and primitive shapes read the same as on desktop."
    },
    {
      "state": "gameplay",
      "viewport": "desktop",
      "answers": {
        "entities_recognisable": false,
        "primitives_or_placeholders": true,
        "lighting_materials_coherent": null,
        "typography_readable": true,
        "buttons_polished": true,
        "objective_obvious": false
      },
      "comment": "At two seconds in, the scene is nearly black; the flat-shape goal and keeper barely stand out and there is no on-screen cue for what to do next in this frame alone."
    },
    {
      "state": "gameplay",
      "viewport": "mobile",
      "answers": {
        "entities_recognisable": false,
        "primitives_or_placeholders": true,
        "lighting_materials_coherent": null,
        "typography_readable": true,
        "buttons_polished": true,
        "objective_obvious": false
      },
      "comment": "Same extreme darkness and primitive shapes as desktop, stretched into the taller portrait canvas with empty space above and below."
    },
    {
      "state": "interaction",
      "viewport": "desktop",
      "answers": {
        "entities_recognisable": false,
        "primitives_or_placeholders": true,
        "lighting_materials_coherent": null,
        "typography_readable": true,
        "buttons_polished": true,
        "objective_obvious": true
      },
      "comment": "The dive moves the teal keeper shape left to overlap the red goal shape; both remain plain geometric primitives with no readable pose, though the instruction text is still visible."
    },
    {
      "state": "interaction",
      "viewport": "mobile",
      "answers": {
        "entities_recognisable": false,
        "primitives_or_placeholders": true,
        "lighting_materials_coherent": null,
        "typography_readable": true,
        "buttons_polished": true,
        "objective_obvious": true
      },
      "comment": "Same dive motion and primitive shapes as desktop, scaled into the portrait canvas."
    },
    {
      "state": "win",
      "viewport": "desktop",
      "answers": {
        "entities_recognisable": null,
        "primitives_or_placeholders": true,
        "lighting_materials_coherent": null,
        "typography_readable": true,
        "buttons_polished": true,
        "outcome_understandable": true
      },
      "comment": "'Round clear!' with streak/accuracy stats and Next round/Menu buttons clearly communicates success and the next step; the green header bar is a flat, untextured placeholder rectangle."
    },
    {
      "state": "win",
      "viewport": "mobile",
      "answers": {
        "entities_recognisable": null,
        "primitives_or_placeholders": true,
        "lighting_materials_coherent": null,
        "typography_readable": true,
        "buttons_polished": true,
        "outcome_understandable": true
      },
      "comment": "Same win panel and placeholder bar as desktop, centred in the taller canvas."
    },
    {
      "state": "loss",
      "viewport": "desktop",
      "answers": {
        "entities_recognisable": null,
        "primitives_or_placeholders": true,
        "lighting_materials_coherent": null,
        "typography_readable": true,
        "buttons_polished": true,
        "outcome_understandable": false
      },
      "comment": "'Full time' with Retry/Menu buttons and stats gives no explicit failure signal, so it's not clearly a loss screen at a glance; the header bar is a flat placeholder rectangle."
    },
    {
      "state": "loss",
      "viewport": "mobile",
      "answers": {
        "entities_recognisable": null,
        "primitives_or_placeholders": true,
        "lighting_materials_coherent": null,
        "typography_readable": true,
        "buttons_polished": true,
        "outcome_understandable": false
      },
      "comment": "Same ambiguous 'Full time' loss messaging as desktop, plus a 'New best!' label and a flat lime-square placeholder icon despite the poor result."
    }
  ],
  "look": "developer-prototype",
  "look_reason": "Every readable entity is an untextured flat polygon, the arena is a near-empty dark void, end-screen icons are plain colour placeholders, and the mobile layout is the desktop canvas simply recentred in a taller frame rather than redesigned.",
  "notes": "A small plain black square appears at a fixed position near the top of nearly every gameplay and menu frame; its role is unclear and it reads as an additional unstyled/placeholder element."
}
```

Tower Merge Rush golden port, round 2, verbatim:

```json
{
  "scores": {
    "art_completeness": 1,
    "character_readability": 3,
    "environment": 0,
    "ui_polish": 2,
    "typography": 3,
    "composition": 1,
    "consistency": 4,
    "no_debug": 4
  },
  "findings": [
    {
      "id": "clipped-header-text",
      "severity": "blocker",
      "category": "composition",
      "frame": null,
      "summary": "A top-right HUD text element (appears to read 'Next lvl N') is overlapped and clipped by the Pause button in nearly every frame on both viewports, leaving only a stray 'N' visible; only the two Game Over frames show the full text ('Next lvl 4').",
      "route": "develop"
    },
    {
      "id": "primitive-tile-entities",
      "severity": "blocker",
      "category": "assets",
      "frame": null,
      "summary": "Every game piece - the only readable entity in the game - is a plain flat-colored rounded rectangle with a number, with no texture, icon or distinguishing art in any captured frame.",
      "route": "assets"
    },
    {
      "id": "mobile-empty-void",
      "severity": "major",
      "category": "composition",
      "frame": "mobile/play-2s",
      "summary": "On mobile the play board occupies only the top ~30% of the 1999px-tall viewport, leaving a large empty flat-colour void below with no layout designed for the taller aspect ratio.",
      "route": "develop"
    },
    {
      "id": "no-environment-art",
      "severity": "major",
      "category": "assets",
      "frame": null,
      "summary": "The scene behind the board is a flat, empty dark-navy void in every frame, with no background, ground or lighting to give a sense of place.",
      "route": "assets"
    }
  ],
  "states": [
    {
      "state": "initial",
      "viewport": "desktop",
      "answers": {
        "entities_recognisable": true,
        "primitives_or_placeholders": true,
        "lighting_materials_coherent": null,
        "typography_readable": true,
        "buttons_polished": true,
        "objective_obvious": true
      },
      "comment": "A single blue '1' tile sits in an empty 7-column board over a flat dark void, with instruction text and a styled Pause button; identical at 1s and at idle-end."
    },
    {
      "state": "initial",
      "viewport": "mobile",
      "answers": {
        "entities_recognisable": true,
        "primitives_or_placeholders": true,
        "lighting_materials_coherent": null,
        "typography_readable": true,
        "buttons_polished": true,
        "objective_obvious": true
      },
      "comment": "Same empty-board initial state as desktop, scaled up; the board sits in the top portion of a much taller screen leaving the lower two-thirds empty, and the top-right HUD text is clipped by the Pause button."
    },
    {
      "state": "gameplay",
      "viewport": "desktop",
      "answers": {
        "entities_recognisable": true,
        "primitives_or_placeholders": true,
        "lighting_materials_coherent": null,
        "typography_readable": true,
        "buttons_polished": true,
        "objective_obvious": true
      },
      "comment": "Two colored number tiles (6, 5) sit in the first two columns with score 91; readable but still plain colored rectangles on an empty background."
    },
    {
      "state": "gameplay",
      "viewport": "mobile",
      "answers": {
        "entities_recognisable": true,
        "primitives_or_placeholders": true,
        "lighting_materials_coherent": null,
        "typography_readable": true,
        "buttons_polished": true,
        "objective_obvious": true
      },
      "comment": "A single teal '6' tile with score 78; the board is confined to the top of the tall mobile screen, leaving most of the frame empty."
    },
    {
      "state": "interaction",
      "viewport": "desktop",
      "answers": {
        "entities_recognisable": true,
        "primitives_or_placeholders": true,
        "lighting_materials_coherent": null,
        "typography_readable": true,
        "buttons_polished": true,
        "objective_obvious": true
      },
      "comment": "Drop before/after shows a tile value change (1 to 2, same score shift); pause before/after clearly dims the board and shows a 'Paused' title with a Resume button."
    },
    {
      "state": "interaction",
      "viewport": "mobile",
      "answers": {
        "entities_recognisable": true,
        "primitives_or_placeholders": true,
        "lighting_materials_coherent": null,
        "typography_readable": true,
        "buttons_polished": true,
        "objective_obvious": true
      },
      "comment": "Same drop and pause interactions as desktop; the Paused overlay with a centered Resume button reads clearly even though the top-right text remains clipped behind the dimmed Pause button."
    },
    {
      "state": "loss",
      "viewport": "desktop",
      "answers": {
        "entities_recognisable": true,
        "primitives_or_placeholders": true,
        "lighting_materials_coherent": null,
        "typography_readable": true,
        "buttons_polished": true,
        "outcome_understandable": true
      },
      "comment": "A 'Game Over' title, final score/best, a row of the final filled tiles, and a clear 'Play again' button make the outcome and next step obvious; this is the only frame where the top-right 'Next lvl' text is fully visible, uncropped."
    },
    {
      "state": "loss",
      "viewport": "mobile",
      "answers": {
        "entities_recognisable": true,
        "primitives_or_placeholders": true,
        "lighting_materials_coherent": null,
        "typography_readable": true,
        "buttons_polished": true,
        "outcome_understandable": true
      },
      "comment": "Same Game Over layout as desktop, scaled up, with outcome and Play again button clearly legible."
    }
  ],
  "look": "developer-prototype",
  "look_reason": "Every entity is a flat colored rectangle on an empty void background, the mobile layout is an unredesigned desktop board stranded at the top of a tall screen, and a HUD text element is clipped behind a button in nearly every frame - none of which a portal-ready build would ship.",
  "notes": "The game's only visual identity is color-coded numbered tiles; this may be an intentional minimalist puzzle style, but per the brief it is still judged against the rubric and scores low on art, environment and composition as a result."
}
```

Neon Drift Arena golden port, round 2, verbatim:

```json
{
  "scores": {
    "art_completeness": 1,
    "character_readability": 2,
    "environment": 1,
    "ui_polish": 3,
    "typography": 3,
    "composition": 2,
    "consistency": 3,
    "no_debug": 5
  },
  "findings": [
    {
      "id": "placeholder-rectangle-entities",
      "severity": "blocker",
      "category": "assets",
      "frame": null,
      "summary": "The player and obstacle entities are plain flat-coloured rectangles and trapezoids with no texture, detail, or shading in every frame - they read as primitive placeholder shapes, not finished art.",
      "route": "assets"
    },
    {
      "id": "near-empty-environment",
      "severity": "major",
      "category": "assets",
      "frame": null,
      "summary": "The scene is almost entirely a black void; only thin perspective grid lines suggest a ground plane, with no walls, sky, or scenery to frame the play.",
      "route": "assets"
    },
    {
      "id": "mobile-subtitle-button-overlap",
      "severity": "major",
      "category": "ui",
      "frame": "mobile/play-2s",
      "summary": "On mobile, the 'Pause' button overlaps and obscures part of the objective subtitle text ('...how far'); the same overlap recurs in mobile/first-session-1s, mobile/first-session-idle-end, mobile/act-pause-before, mobile/act-steer-before, mobile/act-steer-after.",
      "route": "develop"
    },
    {
      "id": "loss-screen-style-mismatch",
      "severity": "major",
      "category": "consistency",
      "frame": "desktop/end-lost",
      "summary": "The crash debris is rendered as a shaded 3D-looking box with distinct lit faces, unlike the flat, unshaded 2D rectangles used for the player and obstacles everywhere else; the same mismatch appears in mobile/end-lost.",
      "route": "assets"
    },
    {
      "id": "unlit-entities-in-perspective-scene",
      "severity": "major",
      "category": "readability",
      "frame": null,
      "summary": "Entities are completely unlit, flat-colour shapes placed in a scene with 3D vanishing-point perspective, so lighting and materials never read as one coherent language.",
      "route": "develop"
    },
    {
      "id": "colour-only-entity-differentiation",
      "severity": "major",
      "category": "readability",
      "frame": null,
      "summary": "Player and obstacles share an identical rectangular silhouette and are told apart only by colour (teal vs. magenta), which weakens at-a-glance readability, especially on mobile.",
      "route": "assets"
    }
  ],
  "states": [
    {
      "state": "initial",
      "viewport": "desktop",
      "answers": {
        "entities_recognisable": true,
        "primitives_or_placeholders": true,
        "lighting_materials_coherent": false,
        "typography_readable": true,
        "buttons_polished": true,
        "objective_obvious": true
      },
      "comment": "A flat teal player shape sits in a near-empty void below a perspective grid horizon, with instructional subtitle text and a Pause button clearly visible."
    },
    {
      "state": "initial",
      "viewport": "mobile",
      "answers": {
        "entities_recognisable": true,
        "primitives_or_placeholders": true,
        "lighting_materials_coherent": false,
        "typography_readable": false,
        "buttons_polished": true,
        "objective_obvious": true
      },
      "comment": "Same layout as desktop but the Pause button overlaps the subtitle's second line, partly obscuring the text."
    },
    {
      "state": "gameplay",
      "viewport": "desktop",
      "answers": {
        "entities_recognisable": true,
        "primitives_or_placeholders": true,
        "lighting_materials_coherent": false,
        "typography_readable": true,
        "buttons_polished": true,
        "objective_obvious": true
      },
      "comment": "Player and several magenta obstacle blocks are visible and clearly distinguished by colour; HUD and instructions remain legible."
    },
    {
      "state": "gameplay",
      "viewport": "mobile",
      "answers": {
        "entities_recognisable": true,
        "primitives_or_placeholders": true,
        "lighting_materials_coherent": false,
        "typography_readable": false,
        "buttons_polished": true,
        "objective_obvious": true
      },
      "comment": "Same gameplay as desktop, scaled up; the Pause button still overlaps the subtitle text."
    },
    {
      "state": "interaction",
      "viewport": "desktop",
      "answers": {
        "entities_recognisable": true,
        "primitives_or_placeholders": true,
        "lighting_materials_coherent": false,
        "typography_readable": true,
        "buttons_polished": true,
        "objective_obvious": true
      },
      "comment": "Pause and steer actions are both captured cleanly; the Paused overlay with glowing title and Resume button is clear and unobstructed."
    },
    {
      "state": "interaction",
      "viewport": "mobile",
      "answers": {
        "entities_recognisable": true,
        "primitives_or_placeholders": true,
        "lighting_materials_coherent": false,
        "typography_readable": false,
        "buttons_polished": true,
        "objective_obvious": true
      },
      "comment": "Pause overlay reads clearly, but the steer/pause-before frames still show the subtitle partially covered by the Pause button."
    },
    {
      "state": "loss",
      "viewport": "desktop",
      "answers": {
        "entities_recognisable": true,
        "primitives_or_placeholders": true,
        "lighting_materials_coherent": false,
        "typography_readable": true,
        "buttons_polished": true,
        "outcome_understandable": true
      },
      "comment": "'Crashed', score, best score, and a 'Race again' button are all clear; a shaded 3D debris box clashes stylistically with the flat shapes used in gameplay."
    },
    {
      "state": "loss",
      "viewport": "mobile",
      "answers": {
        "entities_recognisable": true,
        "primitives_or_placeholders": true,
        "lighting_materials_coherent": false,
        "typography_readable": true,
        "buttons_polished": true,
        "outcome_understandable": true
      },
      "comment": "Matches the desktop loss screen with the same outcome clarity and the same stylistic mismatch on the debris."
    }
  ],
  "look": "developer-prototype",
  "look_reason": "Every readable entity is an untextured flat-coloured rectangle in an almost empty void, which reads as blockout/prototype art rather than a finished, publishable game.",
  "notes": "No win or retry frames were captured, so those outcomes are not assessed."
}
```

**Round 3** (2026-10-02, rubric 1.2.0). Why: the bar of 3 passes a plain game - level 3 reads
"plain", "little character" - and no good game had ever been judged. Frames: the reference
games' production builds (`workspace/quality-bar/` sources, captured with
`scripts/wgf_develop/tools/look.mjs`, desktop and phone, title / play / play-later) and a
live autonomous 3D greybox (styled HUD, primitive ship and obstacles). Same judge argv as
the autonomous profile.

Without anchors, three runs per reference (scores in dimension order art, readability,
environment, ui, typography, composition, consistency, no_debug):

| frames | runs | means | look |
|---|---|---|---|
| 2D reference | 3 | 4.00, 3.88, 3.88 | finished-game x3 (one run raised a mobile-cropping blocker) |
| 3D reference | 3 | 3.88, 4.13, 3.63 | finished-game x3 |
| 3D greybox | 1 | 3.13 | developer-prototype |

Single dimensions moved by a point (sometimes two) between runs on identical frames, so no
dimension can carry a bar of 4 without failing the references half the time. What held:
the look, and the mean. Rubric 1.2.0 therefore adds `mean_pass_bar: 3.5` and a third look,
`unremarkable` (competent but plain), which fails like `developer-prototype`; and the judge
brief now carries the installation's quality-bar frames as what a 4 and `finished-game`
look like.

With the quality bar in the brief (one run each): 2D reference 3.88 PASS; 3D reference 4.88
PASS (inflated - its own frames are among the anchors); 3D greybox 2.12 FAIL (ui and
typography fell from 3-4 to 1-2: compared with a finished game, a styled default is not
polish). The separation is wider with the anchors. Open: no *mid* game - finished art but
generic - has been judged yet; that is the next calibration point when an autonomous run
produces one.

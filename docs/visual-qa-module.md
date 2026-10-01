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
| `visual-qa-report` (output) | `scores`, `findings`, `failed`, `routes`, `verdict`, the frames judged, the `rubric` pinned by sha256, `judge_runs` |

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
itself is unreadable), `cropped-play` (develop).

Per state - `initial`, `gameplay`, `interaction`, `win`, `loss`, `retry`, on each viewport
that has frames of it - the judge answers the rubric's `state_questions` true, false or
null (nothing on screen the question is about): `entities_recognisable` (assets),
`primitives_or_placeholders` (assets; waived by `primitive_style`),
`lighting_materials_coherent` (develop; null in 2D), `typography_readable` - and not a
fallback font (develop), `buttons_polished` - not browser defaults (develop),
`objective_obvious` (initial, gameplay, interaction; develop), `outcome_understandable`
(win, loss, retry; develop). And once, the `look`: `finished-game` or
`developer-prototype`.

**Decision** (`rubric.decide`): FAIL when any finding is a blocker, any dimension is below
`pass_bar` (3), any per-state answer equals its question's `fail_when`, or the look is
`developer-prototype`. `failed` lists `finding:<id>`, `score:<dimension>`,
`state:<viewport>/<state>:<question>` and `look:developer-prototype`; `routes` the routes
of every failure, `assets` before `develop`; the step's route is the first. A `major` or
`minor` finding is recorded and does not fail the build on its own. The report lists every
rubric state on every viewport; one no frame shows is `captured: false`, unanswered.

## Outcomes

| | |
|---|---|
| SUCCESS | PASS |
| FAILED, route `assets` / `develop`, not retryable | FAIL: the workflow routes it back |
| BLOCKED (with a report) | no judge configured (`kind: none`) - visual QA needs a judge and is never a silent pass; no frames in the playability-report; a frame no longer on disk |
| FAILED, not retryable | a malformed verdict twice; a judge that could not start, or that changed a frame or a guarded path; a frame whose sha256 is not the one playability recorded; bad configuration or rubric |
| FAILED, retryable | the judge timed out, went idle, or exited non-zero |
| WAITING_FOR_INPUT | a required input is not in the run |

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
   the rubric's values. A malformed verdict is
   asked for once more, with the reason at the top of the new brief; a second one fails the
   step.

The judge writes:

```json
{
  "scores": {"art_completeness": 0, "character_readability": 1, "...": 5},
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

`scripts/tests/test_visual_qa.py` runs the step with a fixture command judge: pass, a
primitive-entity blocker routed to assets, debug output routed to develop, a dimension
below the bar, a per-state answer routed by its question, a developer-prototype look,
`primitive_style` waiving only the primitive answer, unanswered or extra states, a verdict
on stdout, a malformed verdict retried once then failed (and one
fixed on the retry), an unknown frame id, no judge (BLOCKED), a non-zero exit (retryable),
a changed and a missing frame, a judge writing to a frame or a guarded path, the mock, and
the CLI harness.

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

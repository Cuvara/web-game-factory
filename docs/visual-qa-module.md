# The visual QA module

`scripts/wgf_visualqa/` implements the `visual-qa` step type. In the production phase it
runs after `playability` has played the production build (and, when the workflow has it,
after `production-quality` has measured it), before `review`
([production-architecture.md](production-architecture.md)). The lead wires it into the
workflow; this module only registers the step type.

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

**Decision** (`rubric.decide`): FAIL when any finding is a blocker, or any dimension is
below `pass_bar` (3). `failed` lists `finding:<id>` and `score:<dimension>`; `routes` the
routes of every failure, `assets` before `develop`; the step's route is the first. A
`major` or `minor` finding is recorded and does not fail the build on its own.

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
   and blocker rules, and the verdict shape.
3. **Run.** The argv, cwd the workdir, with wgflib.agentenv's allowlisted environment
   (plus `factory.agents.env_passthrough`) and `WGF_VISUALQA_FRAMES|BRIEF|VERDICT`; one
   owned process tree through wgflib.procs, ended on timeout, idle or cancel.
4. **Isolation.** The staged frames and the Factory's guarded paths
   (`factory.review.guarded_paths`) are fingerprinted before and after. A judge that
   changed either fails the step; guarded paths are restored.
5. **Verdict.** Parsed strictly (`rubric.parse`): every dimension scored, a number 0-5, no
   other keys; findings with a unique kebab-case `id`, `severity`, `category`, `route`,
   a `frame` that is one of the given ids or null, and a summary. A malformed verdict is
   asked for once more, with the reason at the top of the new brief; a second one fails the
   step.

The judge writes:

```json
{
  "scores": {"art_completeness": 0, "character_readability": 1, "...": 5},
  "findings": [{"id": "primitive-keeper", "severity": "blocker", "category": "assets",
                "frame": "desktop/play-2s", "summary": "...", "route": "assets"}],
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
below the bar, a verdict on stdout, a malformed verdict retried once then failed (and one
fixed on the retry), an unknown frame id, no judge (BLOCKED), a non-zero exit (retryable),
a changed and a missing frame, a judge writing to a frame or a guarded path, the mock, and
the CLI harness.

## Calibration

Run once on 2026-10-01 with the commented example judge (CLI 2.1.280, `--model sonnet`,
`--max-budget-usd 2`, text output), through `scripts/wgf-visualqa.py`, on frames the
playability step captured (desktop 1280x720 and mobile 393x851; 14-16 frames per game). No
game-design or asset-manifest was available for these frames, so each brief said "the
design gives no visual identity" and the rubric's no-`primitive_style` rule applied.

| game | frames | verdict | route | judge runs | time |
|---|---|---|---|---|---|
| Goalkeeper Royale (known bad: dark, primitive characters) | 14 | FAIL | assets | 2 | 214 s |
| Tower Merge Rush, the template's golden port (procedural tiles) | 16 | FAIL | assets | 1 | 95 s |
| Neon Drift Arena, the template's golden port (procedural flat shapes) | 16 | FAIL | assets | 1 | 82 s |

What it changed: Goalkeeper's first verdict wrote every score as a string (`"1"`): the
brief's verdict shape showed scores as the quoted placeholder `"0..5"`, and the judge copied
its type. It was rejected and the retry was well formed. The shape now shows
`<number 0-5>` and says "a JSON number". Cost is not reported in text mode; the US$2 cap
was not reached.

Reading the verdicts: Goalkeeper failed on primitive keeper and goal, a near-invisible
ball, placeholder badges, and five dimensions below the bar (art 0, environment 0) - the
asset and readability blockers expected. Both golden ports also fail, as the production
architecture expects of procedural art: flat rectangles standing for every entity, with
`art_completeness` 1 and 0. The judge also found real layout defects no bot measured: the
pause button covering the 2D port's HUD text, and the 3D port's mobile subtitle running
behind it. Neon Drift Arena's art direction is geometric; with a design that states
`primitive_style`, its primitive blocker would not apply - judge it with its design.

Goalkeeper Royale, verbatim (the accepted second verdict):

```json
{
  "scores": {
    "art_completeness": 0,
    "character_readability": 1,
    "environment": 0,
    "ui_polish": 2,
    "typography": 3,
    "composition": 2,
    "consistency": 3,
    "no_debug": 5
  },
  "findings": [
    {
      "id": "primitive-keeper",
      "severity": "blocker",
      "category": "assets",
      "frame": "desktop/play-2s",
      "summary": "The goalkeeper (player) is a flat dark-teal rounded-top rectangle with no face, kit or detail - a plain geometric stand-in, on both viewports.",
      "route": "assets"
    },
    {
      "id": "primitive-goal",
      "severity": "blocker",
      "category": "assets",
      "frame": "desktop/play-2s",
      "summary": "The goal is a flat maroon rectangle with no posts, net or texture, reading as an untextured primitive block, on both viewports.",
      "route": "assets"
    },
    {
      "id": "invisible-ball-asset",
      "severity": "blocker",
      "category": "assets",
      "frame": "desktop/play-2s",
      "summary": "The ball/target renders as a small solid-black square that is almost indistinguishable from the dark void behind it, on both desktop and mobile (e.g. mobile/play-2s); the 'tap the glowing zone' prompt has no visible glow to tap.",
      "route": "assets"
    },
    {
      "id": "placeholder-banner-desktop",
      "severity": "blocker",
      "category": "assets",
      "frame": "desktop/end-lost",
      "summary": "The results panel shows an unstyled flat green rectangle in place of what should be a badge or icon graphic.",
      "route": "assets"
    },
    {
      "id": "placeholder-badge-mobile",
      "severity": "blocker",
      "category": "assets",
      "frame": "mobile/end-lost",
      "summary": "The 'New best!' callout shows a flat lime-green square placeholder instead of a finished badge/icon, clashing with the rest of the palette.",
      "route": "assets"
    },
    {
      "id": "empty-void-environment",
      "severity": "major",
      "category": "assets",
      "frame": null,
      "summary": "Every frame's backdrop is a near-black void with only a flat dark-red ground gradient; there is no sky, stand, stadium or scenery to give a sense of place.",
      "route": "assets"
    },
    {
      "id": "mobile-camera-framing",
      "severity": "major",
      "category": "composition",
      "frame": "mobile/play-2s",
      "summary": "Mobile gameplay frames reuse the same narrow framing as desktop stretched into a taller canvas, leaving roughly two-thirds of the screen as empty void above and below the action instead of a layout designed for portrait.",
      "route": "develop"
    }
  ],
  "notes": "Scores and blockers are consistent across the whole set of 14 frames; end-of-round ('Round clear!') screens and HUD chrome (avatars, score pill, pause button, buttons) are the most finished elements in the build."
}
```

Tower Merge Rush golden port, verbatim:

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
      "id": "primitive-tiles",
      "severity": "blocker",
      "category": "assets",
      "frame": null,
      "summary": "Every readable entity in the game is a plain flat-colour rounded rectangle with a numeral - no texture, icon, or finished art beyond the fill colour, in a game whose identity declares no primitive_style.",
      "route": "assets"
    },
    {
      "id": "pause-button-clips-hud",
      "severity": "blocker",
      "category": "composition",
      "frame": null,
      "summary": "In every playing-state frame on both viewports, the floating Pause button overlaps the 'Next lvl N' HUD text, cutting it down to a lone 'N'.",
      "route": "develop"
    },
    {
      "id": "mobile-shrunken-desktop",
      "severity": "major",
      "category": "composition",
      "frame": "mobile/first-session-idle-end",
      "summary": "On mobile's tall 1081x1999 canvas, the tile row sits at the top exactly as on desktop and the remaining ~80% of the vertical space is empty void - a shrunken desktop layout, not a designed mobile composition.",
      "route": "develop"
    },
    {
      "id": "void-backdrop",
      "severity": "major",
      "category": "composition",
      "frame": null,
      "summary": "The scene is a single flat navy colour in every state with no ground, arena, or lighting to frame play - an empty void per the environment rubric's 0 anchor.",
      "route": "develop"
    },
    {
      "id": "plain-generic-typeface",
      "severity": "minor",
      "category": "ui",
      "frame": null,
      "summary": "Headings, HUD and body text all use one generic bold sans-serif with no distinct character or face choice tied to any identity.",
      "route": "develop"
    }
  ],
  "notes": "The build is functional and internally consistent (one palette, one shape language, no debug overlays), but nearly everything on screen is unstyled flat-colour geometry and the HUD has a real overlap bug, not just a stylistic gap."
}
```

Neon Drift Arena golden port, verbatim:

```json
{
  "scores": {
    "art_completeness": 0,
    "character_readability": 2,
    "environment": 2,
    "ui_polish": 2,
    "typography": 2,
    "composition": 3,
    "consistency": 3,
    "no_debug": 5
  },
  "findings": [
    {
      "id": "primitive-entities-everywhere",
      "severity": "blocker",
      "category": "assets",
      "frame": null,
      "summary": "The player (a flat cyan trapezoid) and the wall/obstacle entities (plain magenta rectangles) are untextured flat-color quad primitives with no model or surface detail, in every playing frame.",
      "route": "assets"
    },
    {
      "id": "subtitle-behind-pause-button",
      "severity": "major",
      "category": "ui",
      "frame": "mobile/first-session-1s",
      "summary": "The instructional subtitle text wraps to a second line that runs directly behind the floating Pause button, obscuring part of the text ('...how far'); recurs in every mobile frame where the subtitle and Pause button are both shown (first-session-1s, first-session-idle-end, play-2s, act-pause-before/after, act-steer-before/after).",
      "route": "develop"
    },
    {
      "id": "debris-overlaps-result-text",
      "severity": "minor",
      "category": "composition",
      "frame": "mobile/end-lost",
      "summary": "Falling debris rectangles from the crash drift up behind the 'Score'/'Best' result lines on the loss screen, also visible but less pronounced on desktop/end-lost.",
      "route": "develop"
    },
    {
      "id": "odd-style-crash-debris",
      "severity": "minor",
      "category": "consistency",
      "frame": null,
      "summary": "The crash-screen debris includes a shaded, isometric-looking cube that reads as 3D-rendered, clashing with the completely flat, untextured 2D shapes used for the player and walls everywhere else.",
      "route": "assets"
    }
  ],
  "notes": "No debug overlays, FPS panels, or wireframes were found; the grid floor reads as an intentional minimal environment rather than a dev helper, so no_debug scores high despite the otherwise sparse art."
}
```

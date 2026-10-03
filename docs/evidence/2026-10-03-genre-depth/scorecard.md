# Genre depth: what was run, and what it showed

Factory commit: the branch that became 2.7.0 (`docs/v2.7-release.md` names the exact shas).
Host: Windows 11, Claude Code 2.1.278, node 24, pnpm 9, template pin `b1062619` (v1.2.0).
Nothing here is filled in from a run that did not happen.

## 1. One real agent-driven run, end to end: `ice-slide` (level puzzle)

`bin/wgf new-game --project ice-slide "A sliding-ice puzzle: a penguin slides until it hits
something; 24 hand-designed levels with keys, doors, crumbling tiles and a 3-star move
target"` under the autonomous profile (headless agents for design, development, review,
assets, visual QA). Run `new-game-20261002-202507-8c157a`; artifacts, frames and the run
narrative are in `ice-slide/`.

| What | Measured |
|---|---|
| Design | family `puzzle`, ending `finite`, session profile `casual` |
| Content | 24 authored `level` units, 6 MVP, each with purpose, objective, mechanics, introduces, difficulty, duration, success, failure, acceptance |
| Progression / difficulty | `linear-levels`; axes `depth`, `move-limit`, `board-complexity`, `piece-variety`, per unit |
| Win / lose | "The penguin's slide ends exactly on the goal tile." / "Moves-left reaches zero before the goal is reached, or the penguin slides onto a tile that already crumbled." |
| Mastery | read the whole level before the first slide, measured in `moves-left`, `stars`, `solve-time` |
| Build | `public/content/units.json` holds every MVP unit by its design id with the design's difficulty values; `tests/unit/content.test.ts` checks them; conformance compares file to design |
| Greybox playability | PASS (18 checks, desktop and mobile), units l-01 → l-05 traversed by the oracle |
| Production playability | **PASS** - 36 PASS, 2 WARNING (`content.variety`: a puzzle's variety is layout, not entity kinds), 2 SKIPPED (`progression.persists`: the design persists nothing at the MVP tier) |
| Production quality | FAIL, routed to `assets` (placeholder fonts and audio) - the 2.6.0 art gate, not the content contract |
| Cost | 25 developer/author sessions, US$317.34, most spent on the Factory defects the run found (listed in `ice-slide/notes.md`) |
| Not reached | visual-qa, review, sdk, verify, G4, release: the run stopped at the asset gate with the budget raised twice |

Thirteen defects in the Factory were found and fixed by this one run; each is a commit on
the branch and a line in `ice-slide/notes.md`. The content contract itself held from the
first design onwards.

## 2. Eight genre families, offline, one idea each

`research → strategy → G2 → design` with the shipped (no-agent) configuration, one idea per
family. Every idea selected the right catalog entry and family, and the strategy carried the
family's content model:

| Idea | Catalog entry | Family | Content model the strategy committed to |
|---|---|---|---|
| sliding-ice puzzle, 24 levels | `logic-puzzle-levels` | puzzle | 6 `level`s MVP, depth / move-limit / board-complexity / piece-variety |
| single-screen precision platformer | `precision-platformer` | platformer | 5 `level`s, precision / timing / hazard-density / spatial-complexity |
| one-touch gravity-flip arcade | `flip-arcade` | arcade | 3 `run-segment`s, speed / density / variety / precision |
| twin-stick wave shooter | `wave-shooter` | shooter | 4 `wave`s, enemy-count / enemy-variety / composition / resource-pressure |
| low-poly arcade racer | `lap-racer` | racing | 3 `track`s, route-complexity / opponent-skill / hazards / time-target |
| lane tower defense | `tower-defense` | strategy | 4 `wave`s, decision-density / economy-pressure / opponent-escalation / composition |
| arena survivor, 10 minutes | `arena-survivor` | survival | 3 `run-segment`s, spawn-rate / enemy-variety / elite-frequency / build-pressure |
| lemonade-stand tycoon | `stand-tycoon` | simulation | 4 `scenario`s, demand-rate / resource-scarcity / concurrency / decision-density |

The design step then **refuses** each of them with the shipped configuration, and says why:
a catalog entry that names only a family is a capability, the strategy carries the person's
idea as the concept, and the deterministic seed designs one particular game of that family -
designing it would describe a different game. An idea needs the agent author
(`factory.design.author: agent`), which is what the `ice-slide` run used.

A **catalog-led** title (no idea) is designed offline with no agent at all: a 20-level
`authored` puzzle, every content rule held, zero breaches.

## 3. Every family designs offline, in the test suite

`scripts/tests/test_design_seed.py` runs the real design step for all eight families and
asserts a valid, content-bearing design each time (unit counts, the purpose arc, axis values
with relief, acceptance lines no two of which are alike, mastery read from HUD metrics).
`scripts/tests/test_research_to_design.py` runs `wgf research` + `wgf plan` for all 19
catalog entries: the two with a design archetype and the eight with a genre model reach a
design, and the nine capability gaps do not.

## 4. What is not covered

- No run reached visual-qa, review, verify, G4 or release with a content-bearing design.
- 3D: no run. Blender is not installed on this host; the racing family is contract-level only.
- The golden runs (2D, 3D) are the release gate and run on Linux CI, not here.
- `content.variety` for a layout-variety family and `progression.persists` for a design that
  persists nothing at the MVP tier are warnings and skips by design, never passes.

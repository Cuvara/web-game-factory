# Level design and content improvements

How the Factory can produce enough good content to meet what portals reward, and prove it before
publication. Grounded in:
- `core/reference/genre-models.yaml`, `core/reference/quality-benchmark.yaml`, `core/reference/content-sufficiency.yaml`;
- `scripts/wgf_sufficiency/`, `scripts/wgf_playability/`, `scripts/wgf_leveldesign/`;
- [docs/level-design-critic.md](../level-design-critic.md) and [docs/content-sufficiency-module.md](../content-sufficiency-module.md).

Labels: [C] confirmed, [I] inferred, [U] unknown.

## 1. Current state

| Capability | State | Label |
|---|---|---|
| Content model per family | 8 families (puzzle, platformer, arcade, shooter, racing, strategy, survival, simulation): unit kinds, generation modes, difficulty models, `units.min_mvp/min_total`, `qa.min_units_traversed` (3-4) | [C] |
| Design-side content rules | about 30 deterministic rules (`scripts/wgf_design/content.py:84-150`): unit counts, axes monotone with relief, consecutive units differ, no near-duplicate acceptance lines, tier rules | [C] |
| Build-side sufficiency | 16 deterministic checks over the shipped `public/content/units.json` and probe records (`scripts/wgf_sufficiency/audit.py:50-55`); release bars 12+ units, 3+ groups, 300+ s | [C] |
| Duplicate levels | Geometry similarity with `near_identical_similarity: 0.85` and `max_repeated_layout_ratio` (`content-sufficiency.yaml:83`; `audit.py:204-215`) | [C] |
| Reachability | A unit counts as reachable when it was *entered*, including through the survey link `?wgf-unit=<id>`; entered is not solved (`audit.py:727-745`) | [C] |
| Solvability | The bot must *win* units 1..`min_units_traversed` in order (`wgf_playability/analysis.py:499-545`). Units beyond 3-4 have **no solvability proof**; there is no static solver | [C] |
| Naive play | The bot plays perfectly; difficulty for a real player is not measured (lesson L13, partly addressed by WS-2) | [C] |
| Level critic | Rubric `level-design-rubric.yaml` (play space, identity, route choice, reveal, climax, distinct from previous); `judge.kind: none` as shipped; advisory (`check-tiers.yaml`), `hold: false`; baseline mode deterministic; risk/reward needs a probe policy no pinned template implements | [C] |
| Generation | `build_spec.content.generation.mode` (authored, parametric, procedural) is validated, but the Factory generates nothing. Levels are written by the design author or the developer agent | [C] |
| Who made the shipped content | People. BBW went from 12 to 32 levels with new brick types, hazards and 4 bosses; SM went from 6 straight corridors to 12 authored courses (quality-gap-audit I-02, I-03, I-14, I-15) | [C] |

## 2. The depth gap

| | BBW | SM | Portal benchmark |
|---|---|---|---|
| Units | 32 levels, 4 worlds | 12 courses, 3 tiers | competitors: "hundreds of levels" (Sky Balls 3D, Mini Golf Club on CrazyGames) |
| Designed play time, all content | 854 s (16-50 s per unit) | 345 s (par sum) | CrazyGames: 10+ min **average per player**, what successful titles often see (benchmark, not threshold) |
| Distinct mechanics | 12 | 7 | - |
| Climax units | 4 bosses sharing one sprite (G-01) | none | - |

Sources: [docs/benchmark/2026-10-baseline.md](../benchmark/2026-10-baseline.md) §5;
https://www.crazygames.com/game/sky-balls-3d ; https://docs.crazygames.com/resources/basic-launch-metrics/ .

**Interpretation [I].**
- SM's whole content takes a skilled player under 6 minutes, so most players stop before
  CrazyGames' average-playtime benchmark.
- BBW's content is about 14 minutes when played once. Average playtime is lower than total
  content, because many players leave early.
- Content depth, not ad tuning, is the binding constraint on Full Launch for both games.

## 3. Proposals

### L1 Content bars from portal benchmarks

- Replace the fixed 300 s release bar with a target derived from the strictest target portal.
  - Designed play time should be at least 2x the portal's average-playtime benchmark. The factor
    is a hypothesis, to be calibrated with portal data.
  - The 2x margin exists because the average player plays far less than all the content.
- Put the bar in `quality-benchmark.yaml` as a function of the profile, not as a constant.
- The bar is checked at design (content rules) and at build (sufficiency).

### L2 Solvability proof for every unit

- The survey already enters every unit through `?wgf-unit=<id>`. Extend it so the bot must
  **win** each unit, within a time bound, under its existing policy.
- A unit the bot cannot win is a blocking finding routed to develop or design.
- This is mechanically verifiable and cheap: bot time, no paid calls.
- Where a family's bot cannot play perfectly (complex puzzles), require an authored solution
  trace per unit and replay it.

### L3 Naive-play difficulty

- Add a second bot policy with human-like reaction delay and error, then measure fail rate per
  unit.
- Flag difficulty spikes (fail rate jumps by more than a set amount between consecutive units) and
  trivial units (no fails on a unit marked `test` or `climax`).
- This is heuristic, not proof. It is labelled as such, and it routes as a warning to design.

### L4 Level critic held at the release tier

- Turn on the critic's `baseline` mode (deterministic, free) as a Quality Gate at the release tier.
- Keep `command` mode (a paid vision session) opt-in.
- The rubric already covers play space, route choice, reveal and climax.

### L5 Parametric generators per family, with human-tuned acceptance

- For families with a parametric mode (breakout layouts, marble course segments, puzzle grids), a
  generator in the game repo produces units from a seed and a difficulty vector.
- The Factory checks the output with existing rules: similarity, axes monotone, introduction
  pacing, plus L2 solvability.
- Generated units need a person's acceptance per group. Poki requires that "AI-made levels" be
  hand-tested and balanced (OFFICIAL, https://developers.poki.com/guide/content-player-safety).
- This is the cheapest route from 12-32 units to the 50-100+ that comparables have. It is not a
  route to "hundreds" of unreviewed levels.

### L6 Mastery layer before more mechanics

- Stars and par medals turn existing units into replayable goals: a cheaper minute of play than a
  new unit.
- Measure with experiment E4 ([analytics-and-feedback-loops.md](analytics-and-feedback-loops.md)).

### L7 Distinct climax art

- Each climax unit gets distinct art (G-01: four bosses share one sprite).
- An asset rule enforces it: a `climax` unit kind requires a unique asset id.

## 4. What can be checked, and by whom

| Property | Check | Kind | Exists |
|---|---|---|---|
| Unit count, groups, mechanics, introductions | sufficiency, content rules | deterministic | yes |
| Near-duplicate layouts | geometry similarity | deterministic | yes |
| Axes progress with relief | content rules | deterministic | yes |
| Every unit solvable | bot win per unit (L2) | deterministic | **no** (first 3-4 only) |
| No unwinnable state | bot win plus a timeout; lose reachable | deterministic | partial (`win.reachable`, `lose.reachable`) |
| Unintended shortcuts | par vs bot best time; a much faster bot route flags | heuristic | no |
| Difficulty spikes | naive-bot fail-rate curve (L3) | heuristic | no |
| Performance per unit | per-unit frame time in the survey | deterministic | partial (browser-QA overall) |
| Route choice, identity, reveal | level critic | judged (baseline deterministic, command AI) | advisory |
| Fun, fairness as felt | stranger playtest | human | no protocol wired to G4 |

## 5. Minimum evidence before publication

A game proceeds to G5 only with all of the following. Each item names who produces it.

1. Every shipped unit won by the bot (L2): playability.
2. Content meets the portal-derived bar (L1): content-sufficiency.
3. No near-duplicate layouts above the threshold: sufficiency.
4. A naive-play fail curve with no unexplained spikes, or a recorded acceptance: playability.
5. Level critic baseline at or above its bar: level-design step.
6. A stranger playtest of at least 5 players, with kill metrics measured: G4, a person.
7. Every climax unit has distinct art: assets.

## 6. Not proposed

- A fully procedural "infinite" mode for every game. Comparables with high votes use authored or
  curated levels; procedural content without review risks Y8's "low-quality" rejection.
- An AI judge as the only evidence of level quality.

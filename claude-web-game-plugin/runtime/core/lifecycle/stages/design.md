# Design

**Machine** title · **State** `design` · **Kind** AI-assisted · **Role** game-designer
**Contributors** analysis, asset, architect
**Inputs** `title-strategy`, `claim`, `prototype-report` (on a design-gap return) · **Outputs** `game-design`, `asset-manifest`

One state producing one design artifact covering scope, session, retention, monetization,
progression and economy.

## Why these are not separate stages

Scope depends on monetization, which depends on session length, which depends on scope.
There is no valid order. Sequencing them as stages invents one, and the usual result is a
monetization plan bolted onto a session that cannot carry it.

Splitting them into four documents is worse than splitting them into four stages, because
four files drift and no single artifact is ever wrong. One artifact with a recorded
consistency result is atomic.

## Procedure

0. **Start from the research the strategy carries** (`title-strategy.research`). The
   buildable shape research named is the one to design; the theme, setting and fantasy it
   supports shape the fantasy and the art direction; the art tone, palette and rendering it
   supports choose the visual identity - a default (the title's own digest) decides only
   what research left unknown. Measured benchmarks may tighten timing targets, never loosen
   them. Carry the research into `game-design.research`, and record in `applied` what came
   from it and what did not.

1. **Read the pinned platform profiles as binding constraints.** Localization, ad cadence,
   bundle size, orientation, supported placements. Record each one you absorbed in
   `platform_constraints_applied` with how it was addressed. An empty list on a title with
   required platforms means the profiles were not read, and platform validation will find
   that out expensively.

2. **Design the session first, then fit scope to it.** Session length bounds how much
   content can ever be surfaced. Content beyond that is cost with no return.

3. **Design monetization into the loop, not onto it.** For every placement, state the
   in-game trigger and what the player gets. If a rewarded placement has no player value,
   it is an interstitial wearing a costume, and the eCPM assumption behind the plan is
   wrong.

4. **Fill the scope tiers explicitly** — `mvp`, `prototype`, `production`, `future`,
   `out_of_scope`. Each exclusion carries a `why_excluded`. This is where scope
   optimization actually happens: instead of 20 enemies / 10 weapons / 5 maps / inventory
   / quests / bosses / skill tree, propose 1 map / 3 enemies / 3 weapons / 1 boss / 1
   progression system / 1 currency / 1 monetization loop — and say why the rest is out.

5. **Produce the asset manifest alongside.** Asset cost is an input to the scope decision,
   so it cannot be produced downstream of it. Every item gets a source (`library`,
   `procedural`, `ai-generated`, `purchased`, `commissioned`) and an estimate. Prefer
   library and procedural at this scale.

6. **Record the engine.** PixiJS for 2D, Three.js for 3D, with a rationale in `engine`.
   Dimensionality changes the asset list, camera, controls and load budget, so a design
   that does not know which it is cannot be costed. tech-plan owns the binding selection
   and must agree with it or supersede the design.

7. **Write the build spec.** `build_spec` is what the implementation agent builds from:
   mechanics with testable rules and starting tuning, controls per input device, the
   game's own state machine, screens, HUD, menus, tutorial, rewards, failure and retry,
   the session as ordered beats, monetization and platform touchpoints, asset and audio
   requirements, responsive behaviour and a visual identity. Every entry is tiered
   `mvp`, `post-mvp` or `optional`, and every cross-reference inside it must resolve. The
   test: could someone build the MVP from this without asking a question? If not, the
   design is not finished.

   The visual identity is a decision, not a default: a committed palette with one leading
   colour, a display face with character, a shape language, a motion rule and an explicit
   list of what to avoid. Generic UI is a design failure.

   State why a player plays longer and comes back in `build_spec.depth`: the meta loop
   above the run and what it persists (more than a score), a goal at every horizon,
   content-variety items introduced on a schedule, the first session's length and the beat
   it ends on, and the return hooks. Tier each entry honestly. An MVP entry rests only on
   what the MVP builds, and depth the strategy excludes is stated as optional, not dropped.
   The bars are `core/reference/design-depth.yaml`.

8. **State the content, unit by unit.** Name the genre family in `genre`
   (`core/reference/genre-models.yaml`), with the session profile and whether play is
   `finite` or `endless` — a finite game must state its win. Then list in
   `build_spec.content` what one unit of content is (`unit_kind`), whether the units are
   `authored`, `parametric` or `procedural`, and every unit the player meets: its `purpose`
   (teach, test, twist, breather, climax, bonus), its `objective` in the words the player is
   shown, the mechanics it asks for and which it `introduces`, its difficulty on each axis
   `build_spec.difficulty.axes` declares, how long it should take, how it is won and lost, the
   `acceptance` lines that make it built, and what it varies from the unit before it. Declare
   the axes once and put every difficulty number on the units, so there is exactly one place
   each lives. Say what getting better means in `build_spec.mastery` — the model, one sentence,
   and the HUD metrics it shows up in.

   A design that states one unit and the word "more" is not a game, and a prototype of it
   proves the verb and nothing else. The family's entry says how many units the MVP and a
   release carry, which progression and difficulty models fit, what counts as variety and how
   mastery shows; the design step checks the design against it (22 `content.*` rules) and
   records the model in `consistency.content_model`. The bars are not a formality: the
   developer builds these units as data, the tech plan makes `CONTENT-nnn` tasks of them, and
   the playability bot plays them. Craft: `core/craft/content-and-level-design.md`.

9. **List features by tier.** `features` is the canonical tier list; `scope.tiers` is
   derived from it (mvp → mvp and prototype, post-mvp → production, optional → future).
   An mvp feature carries acceptance criteria. Every item of the strategy's `mvp` is carried
   into an mvp feature; every item of its `out_of_scope` stays out.

   **Evaluate the candidate features; never drop one silently.** Every feature of
   `core/reference/feature-catalogue.yaml` the brief names, every one the strategy names, and
   every one the catalogue marks `expected` for the genre family is a feature with its
   `catalogue` id, its `source` (`brief`, `strategy`, `design` or `catalogue`) and an
   `evaluation`: player value, cost in hours, platform support across the required
   platforms, monetization impact, QA cost, and a decision with its reason. `include` is
   tiered mvp or post-mvp; `later` and `cut` are optional, and a cut is listed in
   `scope.tiers.out_of_scope` with its reason. A feature only the family expects is evaluated,
   not added: deferring or cutting it with a reason is an honest answer. An included feature
   that needs a platform service a required platform lacks, with no on-device fallback, is
   refused. The design step checks all of it (`features.*` rules, `scripts/wgf_design/features.py`),
   and G3 and G4 are shown what was cut and deferred. A daily challenge is the retention hook
   `daily_challenge`: one unit a day fits a short session where a daily quest does not.
   Craft: `core/craft/feature-evaluation.md`.

10. **Run the consistency check.** Evaluate `core/reference/design-consistency-rules.yaml`
    and write the result into `game_design.consistency`. This is the exit guard. The concept
    rules compare mechanics, not words: the brief and the strategy are read as the mechanic
    ids of `core/reference/mechanic-lexicon.yaml`, the design as its `build_spec` mechanics,
    the content units that use them and the controls that drive them. A paraphrase of the
    brief is the same mechanic; renaming a mechanic the brief does not imply does not make it
    implied. A pillar the brief or design names (risk/reward) is held by a mechanic the units
    use, never by its words.

    The counts are held too (`brief_commitments_met`): what the brief and the strategy's own
    statements count - groups ("4 themed worlds"), units ("32 levels", "worlds of 8"),
    climax units ("boss levels", "a boss per world") - read through
    `core/reference/brief-commitments.yaml`, and every mode of the feature catalogue the brief
    names. At the release tier the units not tiered optional plan at least each count, and
    each mode is an included feature; below it the counts are reported as what the release
    still owes. Cutting what the brief asked for is a brief change, for a person.

    When the run adopts a repository that already ships a game (`factory.init.adopt_existing`),
    the design step counts the content it ships at its HEAD commit - units, groups, climax
    units, elements, the unit ids - into `game_design.existing_content`, with that commit.
    That is a floor (`existing_content_floor_kept`): the design keeps every shipped unit under
    its own id and plans no fewer of any of them. A run improves the game it adopts; it
    never plans a smaller one.

## Returning here from the build

A developer that finds this design silent on something it must decide reports a **design gap**
in the `prototype-report` (`design_gaps`: the field, the question, what it assumed instead, and
whether it was blocking) rather than inventing the answer. A blocking gap brings the work back
here with that report: answer each gap at the field it names, which repairs the design in place
— it is not replaced, and the build that found the gap is kept as evidence. tech-plan and G3
then run again on the repaired design. One return from each source, and then a person looks:
a design that keeps producing gaps is a design decision nobody has made, not a loop to widen.

An assumption the developer could build around is a `minor` gap. It does not come back here; it
is carried to review and to G4 as something to confirm.

## Craft references

What *good* looks like inside `build_spec`: `core/craft/content-and-level-design.md`,
`core/craft/core-loop-and-difficulty.md`,
`core/craft/game-feel.md`, `core/craft/onboarding-and-portal-ux.md`,
`core/craft/ui-hud-mobile.md`, `core/craft/game-audio.md`, `core/craft/art-direction.md`,
`core/craft/accessibility.md`, `core/craft/retention-and-progression.md`,
`core/craft/feature-evaluation.md`.

## Exit

- `design_consistent` and `platform_constraints_satisfied` → `tech-plan`
- consistency fails → self-loop `descope`. **Cut scope; do not relax the rules.** A rule
  waived once is a rule that never fires again.
- unresolvable, or cost exceeds timebox beyond tolerance → `abandoned` (human)

Warnings do not block, but they are carried to G3 and must be acknowledged there. A warning
nobody reads is just a comment.

## Failure modes

- **Designing for the pitch.** A design that reads well and cannot be built in the timebox
  has failed at the only thing it was asked to do.
- **Treating the consistency rules as a formality.** They encode the specific ways these
  four facets contradict each other. A design that trips one is telling you something.
- **Leaving progression open-ended.** No terminal state and no deliberate loop means an
  endless content obligation, which a 7-14 day production model cannot service.
- **Calling a tuning curve content.** Three difficulty tiers of the same level are one unit
  with a parameter, not three units. A unit is the thing a player would name.

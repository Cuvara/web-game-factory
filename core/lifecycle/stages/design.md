# Design

**Machine** title · **State** `design` · **Kind** AI-assisted · **Role** game-designer
**Contributors** analysis, asset, architect
**Inputs** `title-strategy`, `claim` · **Outputs** `game-design`, `asset-manifest`

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

6. **Run the consistency check.** Evaluate `core/reference/design-consistency-rules.yaml`
   and write the result into `game_design.consistency`. This is the exit guard.

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

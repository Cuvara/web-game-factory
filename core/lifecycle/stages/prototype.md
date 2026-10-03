# Prototype

**Machine** title · **State** `prototype` · **Kind** AI-assisted · **Role** gameplay
**Contributors** ui, asset, architect, sdk
**Inputs** `tech-plan`, `game-design`, `title-strategy`, `scaffold-record`, `review-report` (on a review loop) · **Outputs** `prototype-report`, `review-report`, `sdk-report`, `asset-manifest` (updated)

## What a prototype is for

Not "small production". It exists to prove a specific list:

- the **core gameplay** works
- a new player **understands it** without help
- the **session loop** holds together end to end
- the **retention mechanic** is present and plausible
- **monetization integration** actually works in context
- **platform SDK integration** works on the target portal
- **performance** holds on the target device classes

It also exists to prove the game is the one that was designed: every content unit the design
states at the `mvp` tier is built, reachable by playing and won and lost as the design says, not
just the first one. A build of one level is a build of a smaller game than the one G4 reviews.

At this scale the prototype **is** the vertical slice. The old lifecycle had a separate
`VERTICAL SLICE` stage; for a 7-14 day game that is a stage you cannot afford, so instead
the bar here is raised. The prototype must be genuinely playtestable by a stranger, not a
technical demonstration that a mechanic runs.

## Procedure

1. Work the tasks in the development plan's prototype milestones, in dependency order.
   **Update the asset manifest first**, so code is never waiting on art: every asset the
   design needs is sourced from an existing library, or stood in for by a placeholder, and
   each line records its format check, licence and origin against
   `core/reference/asset-policy.yaml`. A placeholder is never production-ready, and neither
   is an asset whose licence is unknown or restricted — it can prototype, not ship.
2. **Build the design's content units as data, not as code.** Every MVP unit of
   `build_spec.content` goes into `public/content/units.json` under its design id, with the
   design's objective, mechanics and difficulty values on the axes the design declares, and
   every mechanic parameter as tuning beside it; the game loads it at boot and the units are
   reachable in design order by playing — never by a debug jump or a URL parameter. Nothing in
   that table is yours to invent. Where the design does not say enough to build a unit, make the
   smallest assumption, record it as a **design gap** (`prototype-report.design_gaps`: the
   field, the question, what you assumed, how serious) and mark the unit `partial` or `cut` in
   `content_coverage`. A blocking gap goes back to design to be answered; an invented unit,
   mechanic or rule is a design-fidelity blocker at review. A parametric or procedural design
   owes no data file — it generates its units from the parameters it states — but it owes the
   same units it committed to.
3. **Integrate SDK, monetization and analytics now**, not in production. Deferring them is
   how titles discover at release that the ad placement does not fit the loop — which is a
   design failure found at the most expensive possible moment.
4. Run CI continuously. It is a guard, not a stage.
   **Have every development commit reviewed by someone who did not write it.** The reviewer
   reads the commit and returns a `review-report`: `approve`, or `request-changes` with
   named blockers that the next development iteration fixes first. The reviewer changes
   nothing - not source, not tests, not the package manifest or configuration - and a
   review that did is discarded and undone. A skipped review is recorded as skipped, never
   as an approval.
5. Measure performance on the planned device classes, especially the low end of mobile.
6. **Playtest with people who have not seen it.** Internal sessions cannot tell you whether
   the game is understandable, which is one of the things this stage exists to establish.
7. Write the `prototype-report`:
   - one entry per item in `title_strategy.prototype_must_prove`, with a verdict
   - **every kill criterion evaluated with a measured value** — omitting one is how a kill
     gate quietly stops working
   - playtest sessions with `player_context`, whether the player understood it unaided and
     whether they reached the first reward
   - `content_coverage`: the designed MVP units against the built ones, per unit, so the
     count can be checked rather than believed
   - `design_gaps`: every place the design did not say enough, with what was assumed instead
   - scope deltas: what was built that the plan did not call for, and what was not built
   - a recommendation: pass, iterate, or abandon

## Craft references

`core/craft/game-feel.md`, `core/craft/core-loop-and-difficulty.md`,
`core/craft/content-and-level-design.md` (what the units are and how they are built),
`core/craft/onboarding-and-portal-ux.md`, `core/craft/playtesting.md` (agent playthrough and
stranger playtest protocols), `core/craft/gameplay-review.md` (the reviewer's gameplay lens).

For a 3D title, also `core/craft/3d-scene-and-physics.md` (update order, camera, the physics
ladder the tech plan pinned), `core/craft/3d-assets-and-animation.md` (model import checks,
clips, disposal) and `core/craft/3d-diagnostics.md` (the triage order for a build that boots
and renders nothing, and the profiling discipline).

## Exit

`ci_green` and `playable_build` → `prototype-review`. The build must be openable and
playable by a reviewer with no instructions.

## Failure modes

- **Polishing instead of proving.** Art and juice make a prototype harder to kill without
  making it more informative. Feedback is not polish: the minimum feedback bar in
  `core/craft/game-feel.md` (input acknowledged, reward noticed, failure understood) is part
  of what a prototype must have, because a mechanic nobody can read cannot be judged.
- **Building past the prototype scope tier.** Work not asked for is work that cannot be
  thrown away cheaply.
- **Filling a gap in the design instead of reporting it.** An invented level, rule or number
  reaches G4 looking like a decision somebody made. Reporting it costs one return through
  design; hiding it costs the gate its meaning.
- **Writing the report to survive the gate.** The report's value is entirely in its
  honesty; a report that cannot support `abandon` has failed at its only job.

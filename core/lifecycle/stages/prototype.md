# Prototype

**Machine** title · **State** `prototype` · **Kind** AI-assisted · **Role** gameplay
**Contributors** ui, asset, architect, sdk
**Inputs** `tech-plan`, `game-design`, `title-strategy` · **Outputs** `prototype-report`

## What a prototype is for

Not "small production". It exists to prove a specific list:

- the **core gameplay** works
- a new player **understands it** without help
- the **session loop** holds together end to end
- the **retention mechanic** is present and plausible
- **monetization integration** actually works in context
- **platform SDK integration** works on the target portal
- **performance** holds on the target device classes

At this scale the prototype **is** the vertical slice. The old lifecycle had a separate
`VERTICAL SLICE` stage; for a 7-14 day game that is a stage you cannot afford, so instead
the bar here is raised. The prototype must be genuinely playtestable by a stranger, not a
technical demonstration that a mechanic runs.

## Procedure

1. Work the tasks in the development plan's prototype milestones, in dependency order.
2. **Integrate SDK, monetization and analytics now**, not in production. Deferring them is
   how titles discover at release that the ad placement does not fit the loop — which is a
   design failure found at the most expensive possible moment.
3. Run CI continuously. It is a guard, not a stage.
4. Measure performance on the planned device classes, especially the low end of mobile.
5. **Playtest with people who have not seen it.** Internal sessions cannot tell you whether
   the game is understandable, which is one of the things this stage exists to establish.
6. Write the `prototype-report`:
   - one entry per item in `title_strategy.prototype_must_prove`, with a verdict
   - **every kill criterion evaluated with a measured value** — omitting one is how a kill
     gate quietly stops working
   - playtest sessions with `player_context`, whether the player understood it unaided and
     whether they reached the first reward
   - scope deltas: what was built that the plan did not call for, and what was not built
   - a recommendation: pass, iterate, or abandon

## Exit

`ci_green` and `playable_build` → `prototype-review`. The build must be openable and
playable by a reviewer with no instructions.

## Failure modes

- **Polishing instead of proving.** Art and juice make a prototype harder to kill without
  making it more informative.
- **Building past the prototype scope tier.** Work not asked for is work that cannot be
  thrown away cheaply.
- **Writing the report to survive the gate.** The report's value is entirely in its
  honesty; a report that cannot support `abandon` has failed at its only job.

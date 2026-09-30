# Core loop and difficulty

**Serves** `core_loop`, `pillars`, `build_spec.mechanics`, `.player_goals`, `.difficulty`,
`.failure`, `.session_flow`, and the strategy's `prototype_must_prove`.

A web portal player decides whether to stay within the first minute, with no install cost
keeping them there. The loop has to be legible in seconds and interesting in minutes. This
playbook covers both.

## Is the loop a loop?

Write `core_loop` as a cycle of verbs the player performs, then test it against these
questions. Record any "no" in `open_questions`, or cut it.

1. **A decision every few seconds.** Name the decision the player makes. "Tap to jump" is an
   input. "Jump now or wait for the gap to widen" is a decision. A loop without a nameable
   decision is a reaction test. That is sometimes the point (one-touch timing), and then the
   design says so.
2. **Risk against reward.** At least one choice trades safety for payoff: a greedy route, a
   bigger combo, a later cash-out. Without it, skill has nothing to express itself through.
3. **Readable consequence.** Every outcome follows visibly from an action. The player never
   has to ask "why did I lose?" That feedback belongs to `game-feel.md`.
4. **A mastery signal.** Something shows the player improving that is not just unlocked
   content: a best score, a combo record, a cleaner clear. `player_goals.long_term` names it.
5. **A reason for one more go.** A retry costs almost nothing, and the result screen shows
   what "better" would have been.

State in `prototype_must_prove` which of these the prototype has to show in play. "The core
loop is fun" is not testable. "First-time players choose the risky route at least once by
their third run" is.

## Three time scales

Fill `build_spec.player_goals` at all three and check that each feeds the next:

| Scale | Field | Example shape |
|---|---|---|
| Next 5 seconds | `moment` | clear the incoming row; land the combo |
| This run | `session` | beat the best score; reach the next stage |
| Across runs | `long_term` | a higher tier, a cosmetic, a mastery rank. Terminal or deliberately looping, never open-ended |

## Difficulty

Keep difficulty **data**: one ramp in `build_spec.difficulty.curve`, driven by named
`parameters` on the mechanics. It is never hand-authored level by level. That is what lets
the prototype be tuned without code changes, and what lets a reviewer check it.

Defaults:

- **Onboarding plateau.** The first 20–40 seconds sit below the first stage of the ramp. The
  player learns the verb before they are tested on it.
- **Sawtooth, not a line.** Pressure rises, then relaxes after a milestone. A monotonic ramp
  is exhausting. A flat one is boring.
- **One axis at a time.** Raise speed *or* density *or* variety at each step, never all three
  at once. Stacked increases feel unfair even when each one is small.
- **Assist without announcing it** (`difficulty.assist`). After repeated early failures, ease
  a parameter quietly: slightly wider gaps, a slower first wave. Never assist past the
  onboarding plateau without saying so, and never in a score-competitive mode.
- **Deaths the player can attribute.** Every failure should be traceable to a decision or a
  timing, not to randomness. Randomness chooses *what* comes next; the player's input
  decides the outcome.

## Failure and retry

- `failure.retry.time_to_retry_s`: from the moment of failure to control again, target
  **≤ 3 s**, including any result screen. A continue offer (`failure.continue_offer`) may
  sit inside that window. It must not extend it.
- Show *why* the run ended (the obstacle, the empty meter) for a beat before the result
  screen.
- Near-misses are valuable. Show how close the run came: the distance to the best score, the
  one missing match.

## Session beats

Write `build_spec.session_flow` as timed beats, then check them:

- the first reward beat lands before `session.time_to_first_reward_s`;
- there is a new element or escalation roughly every 30–60 s within `target_seconds`;
- the session has a natural end (`end_condition`), and every monetization touchpoint sits on
  a beat boundary, never mid-action.

## Failure modes

- **Content instead of system.** More levels in place of a deeper ramp. The timebox pays for
  the levels and the player sees them once.
- **Tuning in code.** Constants buried in logic cannot be tuned at a playtest and cannot be
  reviewed.
- **The loop only the designer understands.** If playtesters describe the loop differently
  from `core_loop`, the playtesters' version is the true one.

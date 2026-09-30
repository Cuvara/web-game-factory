# Playtesting

**Serves**
- `prototype-report`: `playtest_sessions`, `proved`, `kill_criteria_eval`, `perf_measurements`
- the gameplay-session file (`core/artifacts/shared/gameplay-session.schema.json`)
- `qa-report` defects

Three kinds of play produce evidence, and they answer different questions:

| Kind | Who plays | Answers | Lands in |
|---|---|---|---|
| **Agent playthrough** | An automated agent driving a real browser | Does every required aspect work in the built game? What did it look and feel like? | gameplay-session file; defects |
| **Stranger playtest** | People who have never seen the game | Do they understand it unaided and reach the first reward? Do they want another go? | `playtest_sessions` (`player_context: first-time`) |
| **Performance pass** | Anyone, on throttled hardware or emulation | Does it hold the budgets on the low-end class? | `perf_measurements`; defects with traces |

None of them substitutes for another. An agent can prove every aspect works and still not
tell you whether a stranger understands the game.

## A. Agent playthrough protocol

It uses a browser automation capability (`tool-capabilities.md`). The Factory's
verification reads the result. It never drives the browser itself.

1. **Serve the built bundle** as a local preview, never the dev server. Note the commit
   under test (`git rev-parse HEAD`). A session recorded against any other commit is
   ignored.
2. **Only localhost.** Block, or do not follow, any request to an external origin. Portal
   SDKs are substituted, never contacted.
3. For each aspect the design implies:
   - `boot`, `loading`, `start`, `input`, `core-loop`
   - `progression`, `game-over`, `restart`, `pause-resume`
   - `responsive`, at both a phone and a desktop viewport

   drive the game as a first-time player would, and write one scenario for it:
   - `steps`: what was done, in order ("tapped Play at 00:02", "held right for 1.5 s").
   - `observation`: what was *seen*, concretely, including feel. "Coin pickup flashed and
     played a rising chirp, counter rose 3→4 with a bounce" rather than "pickup works".
     Note anything that missed `game-feel.md`'s feedback bar, or broke `accessibility.md`
     (flashes, contrast).
   - `status`: PASS only if the aspect behaved as the design specifies. Missing feedback
     on a reward is a FAIL of `core-loop`, not a warning.
   - `viewport`, and a `screenshot` saved in the repository at the end of the scenario.
4. Record `console_errors` and `failed_requests` for the whole session. An uncaught error
   fails the aspect in which it occurred.
5. Pause/resume: blur the tab, or trigger the pause path, and check that the loop, timers
   and audio all stop and resume in place.
6. Write the file to the repository's verification output path, as named in the
   verification docs, before verification runs.

Beyond the file: note the times observed (load to first frame, to first play, to first
reward) against `session`. They feed the prototype report.

## B. Stranger playtest protocol

- **Who.** At least 5 first-time players per iteration. It is fine if they are not gamers,
  and better if some are. Internal sessions are recorded as `internal`, and they do not
  count towards understanding.
- **Setup.** The real build on a phone, in the orientation the design targets. No
  explanation beyond "this is a game, play it as you like". The observer says nothing
  unless the player is stuck for more than 30 s, and records the help given.
- **Observe, per session:**
  - the time to the first intentional input, and to the first reward;
  - `understood_without_help`: the first action was purposeful and no help was given;
  - `reached_first_reward`;
  - the moments of confusion, what the player *said* the goal was, and where they stopped
    or died;
  - whether they chose to play again unprompted. This is the strongest fun signal
    available at this scale.
- **Ask afterwards**, in exactly these words, so answers are comparable:
  1. "What were you trying to do?"
  2. "What was frustrating?"
  3. "Would you play it again?"
- **Record.** One `playtest_sessions` entry per player. Quotes and observations are kept as
  separate claims (observation vs interpretation), and linked through `claim_refs`.

## C. Performance pass

Follow `web-performance.md` (Measuring). Throttled low-end first, cold cache, the busiest
moment, then memory after repeated restarts.

## From evidence to verdict

- Evaluate every kill criterion with its measured value, even those that clearly pass.
- A `prototype_must_prove` item is `proved` only by one of the three kinds of evidence
  above, never by the developer's own report.
- Summarise patterns across players, not single anecdotes: "4 of 6 missed that the
  meter drains".
- Recommend **pass**, **iterate** (name the specific change and what would show it worked)
  or **abandon**. The report must be able to support abandon (`prototype.md`).

## Failure modes

- **Testing with the team.** They already know the game.
- **Helping the player.** Every hint given invalidates the "understood unaided" result.
- **An agent session that only says "works".** Observations must be concrete enough for
  someone else to verify.

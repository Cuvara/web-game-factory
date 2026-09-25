# Prototype review

**Machine** title · **State** `prototype-review` · **Gate** G4
**Kind** human approval · **Approver** portfolio-owner
**Presenters** game-designer, qa
**Inputs** `prototype-report`, `qa-report`, `verification-report`, `title-strategy`, `game-design` · **Outputs** `decision-record`

The kill gate. The most valuable gate in the factory.

## Why it exists

A factory that cannot kill a concept is a liability generator: it converts a bad idea into
a shipped bad idea at full cost, and then into a live game that must be maintained. The
ability to stop here is what makes the whole discovery pipeline worth running — without it,
every opportunity that enters production ships regardless of what the prototype taught.

## The question

**Not** "can this be saved" or "how much have we spent". The question is:

> Knowing what we now know, would we start this today?

Sunk cost is not an input. The work already done is gone either way; the only thing at
stake is the work not yet done.

## Procedure

1. **Read the kill criteria from `title-strategy` first**, before the prototype report.
   Reading the results before the criteria invites the criteria to be reinterpreted.
2. Walk `kill_criteria_eval` — each criterion, its measured value, breached or not.
3. Walk `proved` — each question the prototype was meant to answer, with its verdict. An
   `inconclusive` on a central question is an argument for `iterate`, not for `pass`.
4. Review playtest evidence, weighting `first-time` sessions. Whether players understood it
   unaided and reached the first reward are the two observations that matter most.
5. Check `iteration` against `max_prototype_iterations`.
6. Review `scope_deltas` — unplanned additions are a signal about either the plan or the
   discipline.
7. Decide, and write the decision record with `criteria_eval` populated. Evaluating each
   criterion explicitly is what stops a kill gate degrading into a vibe check.

## Outcomes

| Outcome | Next | Condition |
|---|---|---|
| `pass` | `production` | No kill criterion breached |
| `iterate` | `prototype` | Iterations remain; state what changes |
| `abandon` | `abandoned` | Any criterion breached, or iterations exhausted |

`iterate` requires naming what will be different. "Try again" without a changed hypothesis
is how a title consumes its whole timebox at this gate.

## Irreversible

G4 **never auto-approves**. Killing a concept is not a decision an AI makes unattended, and
neither is overriding a breached criterion. The schema enforces `mode: human` here.

## On abandoning

An abandoned title is a success of the process, not a failure of the team. Its artifacts
are retained — an abandoned title with its prototype report and decision record is among
the more valuable things the factory produces, because it is evidence about what does not
work, and it feeds the next market scan.

Returning to `opportunity analysis` with a real answer beats polishing the wrong game.

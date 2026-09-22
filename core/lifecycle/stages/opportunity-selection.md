# Opportunity selection

**Machine** portfolio · **States** `shortlisted` → `approved` · **Gate** G1
**Kind** human approval · **Approver** portfolio-owner · **Presenter** analysis
**Outputs** `decision-record`

The first gate. A human chooses which opportunity gets a production cycle.

## What analysis must present

1. **The ranked shortlist, not just the winner.** A single recommendation hides the
   comparison that makes the decision meaningful.
2. **Per candidate: aggregate, evidence coverage, and which dimensions are hypothesis.**
   Two candidates at 0.65 are not equivalent if one is evidence-backed and the other is a
   stack of assumptions.
3. **Every veto that fired on rejected candidates**, by id and reason. A candidate the
   model killed may be one the human would have wanted to see.
4. **The strongest argument against the top candidate.** If nobody can state one, the
   analysis is incomplete rather than the opportunity flawless.

## Outcomes

| Outcome | Next state | Meaning |
|---|---|---|
| `select` | `approved` | Commit a cycle to this |
| `defer` | `parked` | Good, not now — capacity or timing |
| `reject` | `rejected` | Not worth pursuing |

Approval is not promotion. `approved → promoted` is gated on `wip_available`: if the
factory is already running `max_concurrent_titles`, the opportunity waits in `parked`.
That cap exists because the human is the scarce resource — seven gates against a 7-14 day
cycle means a gate roughly every 1.4 days, and a factory whose gates cannot be cleared
tempts people to remove the gates that matter.

## Auto-approval

G1 is reversible, so it may auto-approve after the window in `gates.yaml` (default 72h).
When it does, the decision record says `mode: auto-approved`. That is recorded and never
implicit — a decision nobody knows was automatic is worse than no decision.

## Failure modes

- **Approving the most exciting idea rather than the best-evidenced one.** The mechanism
  against this is reading `evidence_coverage` aloud before reading the aggregate.
- **Approving more than can be built.** The WIP cap is a guard, not a suggestion.
- **Skipping the record.** A gate without a decision record cannot be resumed. An agent
  picking this up in three days has no way to tell approved from never-asked.

# Feature evaluation

**Serves** `features[]` (`source`, `catalogue`, `evaluation`), `scope.tiers` (`future`,
`out_of_scope`), `retention.hooks`, and the cut list the prototype review is shown.

A brief names more than a core loop. It asks for an endless mode, a time trial, themed worlds,
saved progress. A genre's players also expect things nobody wrote down: a racing player looks
for a time trial, an arcade player for a best score. A design that keeps none of these, and
says nothing, is a design that dropped them silently. A design that adds all of them is a
design nobody can build in a week. Feature evaluation is the step between those two: every
candidate gets a decision and a reason.

The candidates come from [`core/reference/feature-catalogue.yaml`](../reference/feature-catalogue.yaml).
The design step's feature check (rules `features.*`) holds the design to it.

## Which features need a decision

1. **Every catalogue feature the brief names.** The brief is the person's own idea. A feature
   it names is built unless the design says why not. Record it with `source: brief`.
2. **Every catalogue feature the title strategy names**: its one-liner, concept, MVP, what the
   prototype must prove, and its `out_of_scope`. A strategy exclusion is a decision the
   design records as `cut`, with the strategy's reason. Record it with `source: strategy`.
3. **Every catalogue feature the genre family marks `expected`.** Evaluate these; do not add
   them blindly. `later` and `cut` are honest answers when the reason is stated. Record it
   with the source it came from (`design` when the archetype already builds it, `catalogue`
   when the catalogue proposed it).

A feature the designer adds on their own needs no evaluation. It is `source: design`.

## The evaluation

| Field | What it says |
|---|---|
| `player_value` | low, medium or high: what the feature gives the player of this game, not of games in general |
| `cost_h` | Estimated build hours at web-portal scale. The catalogue's number is a start; revise it for this game |
| `platform_support` | all, some, local or none, across the required platforms. The check computes it from the profiles; state the same value |
| `monetization_impact` | none, low, medium or high: whether the feature creates reward moments, ad opportunities or a reason to pay |
| `qa_cost` | low, medium or high: how much testing it adds (a platform service, persistence and modes cost most) |
| `decision` | `include`: built, tiered mvp or post-mvp. `later`: deferred, tiered optional. `cut`: not in this game, tiered optional |
| `reason` | One sentence a person at G4 can agree or disagree with |

## Defaults with reasons

- **A brief feature is included by default.** Cut or defer it only for a reason the person
  would accept: it breaks the session length, it needs a platform service no required portal
  offers, the strategy excluded it, or it costs more than the rest of the content.
- **A platform service is checked, not assumed.** A leaderboard on a portal without one is
  `cut` (`platform_support: none`); a local best score is `statistics`, a different feature.
  Achievements and daily rewards fall back to on-device storage (`local`).
- **Modes are cheap only when the content is data.** A time trial reuses every authored unit
  with the clock as the only rule; an endless mode needs a generator or a loop over the
  units. Estimate the cost on what this design already has.
- **A daily feature fits the session.** A daily challenge (`retention.hooks: daily_challenge`)
  is one unit or seed a day and fits a two-minute session. A daily quest does not
  (`short_session_no_daily_quest`).
- **`later` is not a hiding place.** It means production after G4 decides. The prototype
  review is shown every `later` and every `cut`, with its reason.

## What the check does not see

The catalogue recognises a feature by its `terms`. A brief that names a feature the catalogue
has no entry for is not seen. The answer is a new catalogue entry, never a looser match.
Content features - power-ups, bosses, brick types - are units and mechanics: the content
check holds them (`content-and-level-design.md`), not this one.

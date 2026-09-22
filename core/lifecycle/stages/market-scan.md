# Market scan

**Machine** portfolio · **Kind** job (stateless) · **Role** research
**Emits** `claim`, `opportunity`

A recurring job, not a state. Nothing sits "in" market scan — it runs, writes claims and
opportunities, and finishes. This is why the portfolio tier has no `MARKET_INTELLIGENCE`
state: there is no entity to hold it.

## Inputs

- `core/reference/platforms/*.yaml` — what each portal carries, rewards, and forbids
- `core/reference/dimensions.yaml` — the vocabulary every observation must land in
- `performance-review` artifacts from live titles — the factory's own shipped evidence
- Existing claims and opportunities, for deduplication

## Procedure

1. **Pick a scope.** A scan is bounded: one platform, one genre family, or one question
   carried over from a previous review. An unbounded "scan the market" produces a wall of
   undifferentiated observations that nobody scores.

2. **Gather observations per platform.** Platforms expose different things and none of
   them expose the same schema. Record what a given portal actually shows — listings,
   rankings, play counts, ratings, release dates, tags, ad formats — and do not invent the
   fields it does not show.

3. **Write claims, one statement each.** Each claim is falsifiable and carries its tier:

   - `observed` — measured or read from a named source. Requires at least one evidence
     entry with a `source_uri`. No exceptions; the schema enforces it.
   - `derived` — reasoned from other claims. Must name its parents.
   - `hypothesis` — asserted. Legitimate and useful, capped at 0.6 confidence.

   The discipline that matters: write the observation and the interpretation as **separate
   claims**. "Top 20 idle games on Yandex are all merge-based" is observed. "Merge is the
   dominant idle mechanic on Yandex" is derived. "Non-merge idle has an opening" is a
   hypothesis. Collapsing these into one sentence is how a guess acquires the authority of
   a measurement.

4. **Never edit an existing claim.** If something changed, write a new claim and set
   `superseded_by` on the old one. The old claim stays readable, which is the only way to
   see that a belief moved.

5. **Form opportunities.** Group claims into candidate games. An opportunity needs a
   genre, a core mechanic, a fantasy, a core loop, candidate platforms, and the claim ids
   it rests on. Deduplicate against the existing backlog including rejected entries — a
   previously rejected opportunity plus its evaluation is evidence, and rediscovering the
   same dead end every quarter is a real cost.

6. **Generate several candidates, not one.** The scan's job is to widen the field. Four to
   eight opportunities from a scan is healthy; one means you decided before you looked.

## Outputs

- `claim` records in `workspace/claims/`
- `opportunity` records in `workspace/opportunities/<id>/opportunity.json`, state
  `discovered`

## Failure modes

- **Popular read as profitable.** Play counts measure traffic, not revenue, and portal
  ranking algorithms reward recency. A high-traffic genre with no monetization fit is a
  trap, and it is the most common one.
- **Unsourced numbers.** If a revenue or retention figure cannot be attributed, it is a
  hypothesis. Scoring it as observed corrupts every evaluation downstream.
- **Scanning what is easy to see.** The platforms with good public data are not
  necessarily the platforms worth building for.

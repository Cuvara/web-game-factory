# Market scan

**Machine** portfolio · **Kind** job (stateless) · **Role** research
**Emits** `claim`, `opportunity`, `research-report`

A recurring job, not a state. Nothing sits "in" market scan — it runs, writes claims and
opportunities, and finishes. This is why the portfolio tier has no `MARKET_INTELLIGENCE`
state: there is no entity to hold it.

## Inputs

- A **brief**, optional — the game idea a person started the run with. With one, the scan is
  anchored to it: the question names it, candidates are ranked by their match to it before
  the screen orders them, and the opportunity carries it verbatim (`brief`) for strategy and
  design to build from. The screen and its vetoes are unchanged. A selection that matches
  none of the brief's words, or renders in another dimension than it names, records an
  `idea-unmatched` gap: the catalog shape is reported as the nearest carrier, never as a fit.
  When no eligible candidate matches any of the brief's words, the scan **waits** by default
  (`discovery.idea_fallback: wait`): it selects nothing, keeps every candidate, names the
  nearest eligible shape in the gap as information only, and asks for input - a concept for
  the brief in the project's concepts file, or `idea_fallback: nearest`, which carries the
  brief to that nearest shape instead. A substitute shape is a different game, so it is never
  carried forward unless someone asked for it.
  Without a brief the scan is blank: the whole catalog, ranked on the screen alone.
- A **concepts file**, optional — `concepts.yaml` in the research corpus (or the path the
  `concepts` setting names): concepts a project authored for a brief the catalog does not
  carry. It has the catalog's shape, `{version, archetypes: [...]}`, and every entry the
  catalog's fields plus `brief`, exactly the run's brief (an entry for another brief is
  refused), and `design_archetype`, the design archetype that designs it or `agent` when only
  an agent design author can. An entry may not reuse a catalog id. Its entries are screened
  with the catalog's, under the same vetoes; each one's figures are estimates, so they are
  hypothesis claims, and each carries one more hypothesis claim saying it was authored for
  the brief, is not a catalog shape and is unmeasured. The file is read only when the run has
  a brief; its hash is part of the report's identity, and its use is listed among the report's
  collectors. A selected entry's concept is the opportunity's concept, verbatim.
  When a workflow run's research step waits for either input - evidence, or a concept for
  its brief - the research role supplies it and the run is resumed: `core/craft/research-evidence.md`.
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
- one `research-report` per scan: the scope, every source read, every claim made, what
  each target platform allows and demands, every candidate considered with its screen and
  its reason for exclusion, and the selection. The report is how a reviewer sees that the
  field was widened before it was narrowed.

When the scan runs as the `research` step of a workflow, the candidates live in the
research report and only the selected one is emitted as an `opportunity`; the others stay
on record, where the next scan can find them. The report's screen borrows the scoring
model's weights and vetoes to rank candidates. It is not an `evaluation`: scoring for the
shortlist remains a separate act by a separate role.

A scan with no external source at all is not a scan. It still writes its report - every
platform fact resting on unverified profiles, every product figure on estimates - and
stops for evidence rather than emitting an opportunity nobody looked for.

## Failure modes

- **Popular read as profitable.** Play counts measure traffic, not revenue, and portal
  ranking algorithms reward recency. A high-traffic genre with no monetization fit is a
  trap, and it is the most common one.
- **Unsourced numbers.** If a revenue or retention figure cannot be attributed, it is a
  hypothesis. Scoring it as observed corrupts every evaluation downstream.
- **Scanning what is easy to see.** The platforms with good public data are not
  necessarily the platforms worth building for.

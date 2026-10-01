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
  Without a brief the scan is blank: every generator, ranked on evidence alone.
- `core/reference/platforms/*.yaml` — what each portal carries, rewards, and forbids
- `core/reference/dimensions.yaml` — the vocabulary every observation must land in
- `core/reference/research-vocabulary.yaml` — the shared codes every researched game is
  described in: the genre tree, market descriptors, and the facets (mechanics, core-loop
  beats, controls, theme, fantasy, art, audience, session, progression, difficulty,
  retention, monetization, production) and their values
- `core/reference/research-analysis.yaml` — which facet pairs are analysed, and when a
  count is large enough to report as a pattern
- the **game corpus**: portal listings captured as snapshots, and teardown records of
  individual games (`game-record`; `core/craft/competitive-teardown.md`)
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

3. **Research games, not only platforms.** The game is the unit. Every game the scan knows
   of - from a listing, or played and timed in a teardown - is coded on the shared
   vocabulary, so games can be compared and counted. A portal's own category tag, a
   stopwatch reading, an ad the observer saw offered are observations; a theme read off a
   thumbnail, a tone, a fantasy are interpretations of a capture, and are coded as such.
   Free text describes; only codes count.

4. **Write claims, one statement each.** Each claim is falsifiable and carries its tier:

   - `observed` — measured or read from a named source. Requires at least one evidence
     entry with a `source_uri`. No exceptions; the schema enforces it.
   - `derived` — reasoned from other claims. Must name its parents.
   - `hypothesis` — asserted. Legitimate and useful, capped at 0.6 confidence.

   The discipline that matters: write the observation and the interpretation as **separate
   claims**. "Top 20 idle games on Yandex are all merge-based" is observed. "Merge is the
   dominant idle mechanic on Yandex" is derived. "Non-merge idle has an opening" is a
   hypothesis. Collapsing these into one sentence is how a guess acquires the authority of
   a measurement.

5. **Never edit an existing claim.** If something changed, write a new claim and set
   `superseded_by` on the old one. The old claim stays readable, which is the only way to
   see that a belief moved.

6. **Count across games.** A pattern is a derived claim over the corpus: of the games coded
   on both facets, how many show it (numerator), out of how many (denominator), which do and
   which do not. A share without its denominator is refused. Patterns describe; what
   adopting one might do is a separate hypothesis.

7. **Keep the market signals apart.** Per genre node and platform: *demand* is the cell's
   share of popularity-ordered lists; *supply* is the portal's category count and its share
   of the family; *saturation* is demand share over supply share and needs both;
   *competition* names the titles; a *trend* needs the same list captured on several dates.
   Many games is supply, not saturation. Few games with no demand evidence is a gap in the
   evidence, recorded as `insufficient-demand-evidence` - never an opportunity.

8. **Generate several opportunities, not one.** The scan's job is to widen the field. Each
   generator is a rule over the corpus: a proven core with one axis changed (theme, tone,
   rendering, fantasy), a supply gap, a pattern transferred from one genre to another, a
   difference between portals, and every buildable shape screened against the portals.
   Each opportunity names its facet cell (every facet with its tier and claims, or
   `unknown`), its basis and a thesis (a hypothesis), its market cells, competitors,
   adopted patterns, benchmarks, monetization evidence, production profile and audience.
   An opportunity whose basis rests on no observation is not proposed. Four to eight
   opportunities from a scan is healthy; one means you decided before you looked.

9. **Check buildability last, and keep what cannot be built.** An opportunity the Factory
   has no capability for is kept as a capability gap, with what is missing - it is
   evidence for what to learn to build next, not something to discard. Deduplicate against
   the backlog, including rejected entries.

## Outputs

- `claim` records in `workspace/claims/`
- `opportunity` records in `workspace/opportunities/<id>/opportunity.json`, state
  `discovered`
- one `research-report` per scan: the scope, every source read, every claim made, what
  each target platform allows and demands, every candidate considered with its screen and
  its reason for exclusion, and the selection. The report is how a reviewer sees that the
  field was widened before it was narrowed.

When the scan runs as the `research` step of a workflow, every opportunity lives in the
research report, and the one the run carries - the best-ranked buildable one, unless the
step pins another - is emitted as the run's `opportunity`; the others stay on record, where
G1 and the next scan can find them, and the installation may write them all to the backlog
as `discovered`. The report's screen borrows the scoring
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

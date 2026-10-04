# Research V2: games, patterns, market cells and an opportunity space

Research used to be platform evidence, a fixed catalog of eleven game shapes, a screen and
one selected opportunity. Nothing researched a game: theme and art did not exist, the
competitors' names were counted and then dropped, and the catalog bounded what research
could propose. Research V2 makes the **game** the unit of research, codes every game on one
shared vocabulary, counts patterns across them, keeps the market signals apart, proposes
several opportunities, and hands strategy and design a structured, evidence-traced
description they actually read.

```
listing snapshots ─┐                       core/reference/research-vocabulary.yaml
teardown records ──┼─► game corpus ◄──────  (genre tree, 41 facets, value lists)
platform profiles ─┘        │
                            ├─► per-domain views (genre, gameplay, mechanics, theme,
                            │   fantasy, art, audience, session/retention, monetization,
                            │   UX, production)
                            ├─► market cells: demand · supply · saturation ·
                            │   competition · trend          (per genre node × platform)
                            ├─► cross-game patterns and benchmarks
                            │   (numerator, denominator, members, exceptions)
                            ▼
                 opportunity space - five generators, capability check
                            │   (unbuildable kept as capability gaps)
                            ▼
              research-report (all of it) + the carried opportunity
                            │
                            ▼
      strategy  (title-strategy.research + applied) ──► design (game-design.research + applied)
```

## Inputs

| Input | Where | What it gives |
|---|---|---|
| Listing snapshots | `<corpus>/snapshots/*.json`, `reference_title` and `category` facts | which games a portal shows, in which list, on which date; category counts |
| Teardown records | `<corpus>/games/<game-id>.json` (`core/artifacts/shared/game-record.schema.json`) | how a game plays, looks, retains and monetizes, coded per session |
| Vocabulary | `core/reference/research-vocabulary.yaml` | the codes: genre tree, descriptors, facets, values |
| Analysis configuration | `core/reference/research-analysis.yaml` | the facet pairs analysed, the support thresholds, list kinds, generators |
| Capability catalog | `scripts/wgf_discovery/archetypes.yaml` (1.3.0) | what the Factory can build (`genre_node`, `mechanics`, `requires`, `design_archetype`, `genre_model`), and why not (`unavailable`) |
| Genre models | `core/reference/genre-models.yaml` | the content shape a game of each of the eight families must state: unit kinds, progression and difficulty models, difficulty axes, unit counts, variety and mastery |
| Platform profiles | `core/reference/platforms/*.yaml` | unchanged: what each portal allows and demands |

`corpus` defaults to `workspace/research`. Write teardowns by the procedure in
`core/craft/competitive-teardown.md`; `python3 scripts/wgf-corpus.py template` starts a
record, `validate` checks a corpus the way the step reads it, `facets` lists the codes.

## The evidence hierarchy

```
OBSERVATION      a listing; a portal's own category tag; a stopwatch reading; an ad seen
     │           offered - each an `observed` claim quoting its excerpt and naming its
     │           session (method, viewport, capture)
     ▼
DERIVED          a coding read off a capture (theme, tone, fantasy); a demand share; a
     │           pattern - each a `derived` claim naming its parents. A claim that counts
     │           games carries `support`: numerator, denominator, members, exceptions,
     │           frame.
     │           A claim tagged `pattern` without it is refused by the ClaimBook and by the
     │           claim schema
     ▼
HYPOTHESIS       what adopting a pattern might do; why an opportunity might work (its
     │           thesis) - `hypothesis`, confidence <= 0.6. Never stated as fact
     ▼
OPPORTUNITY      a separate record (`opportunity.research`): a facet cell, its basis, its
                 thesis. A corpus generator refuses any proposal whose basis rests on no
                 observation - a hypothesis is never silently turned into an opportunity
```

`unknown` is a legitimate value. A facet nobody coded is `unknown` with the reason, all the
way into the design; it is never filled with a default and called research.

## The corpus

Every game is a record with its listings (platform, list, list kind, date) and its facets
(value, tier, claims). Listing-only games carry a genre - the snapshot author's slug mapped
onto the genre tree, a derived claim resting on the listing - and the platforms they appear
on. Teardown games carry whatever their sessions coded. A listing and a teardown of the same
game join on its name (`listing_names`).

The genre system is a tree (family → subgenre → narrower kind) because counts need it: a
game coded match-3 is also a match game and a puzzle game. Hyper-casual, casual and midcore
are **descriptors**, not branches - they describe audience and production size and cut
across genres.

## Market cells

One cell per genre node per platform, five separate signals:

| Signal | Definition | Needs |
|---|---|---|
| demand | the cell's share of titles in **popularity-ordered** lists on that platform; a derived claim with `support` (members, exceptions) | a captured popularity list whose scope covers the node; lists are pooled only with lists of the same scope |
| supply | the portal's category count; the cell's share of its family where both counts are known - a derived claim citing both count observations (counts have no member list, so no `support`) | category counts, the latest capture of each |
| saturation | demand share / supply share: under-supplied, balanced or over-supplied on the configured band | observed demand **and** a supply share. Supply with no observed demand is `insufficient-demand-evidence` |
| competition | how many of the titles captured on the platform are in the cell, by name | listings |
| trend | the change in demand share in the same list captured on different dates | the same list on `min_history_frames` dates, else `insufficient-history` |

Editorial and unordered lists show that a game exists, not that it is played: they are
never demand. Revenue is still never estimated.

## Patterns and benchmarks

For each configured facet pair (genre × mechanics, genre × loop, theme × genre, theme ×
rendering, theme × tone, genre × audience, genre × intent, genre × session, mechanics ×
session, genre × retention, mechanics × retention, genre × progression, mechanics ×
progression, mechanics × monetization, genre × monetization, genre × UX, genre × platform,
rendering × animation, theme × saturation, genre × saturation): of the games coded `a`, those
also coded on `b` are the denominator; those holding a value of `b` are the numerator. A
pattern is reported at `min_support` of at least `min_denominator`; below that the report
records `insufficient-support`. Games uncoded on `b` are listed as `unknown` - never counted
as "no". A broader genre holding exactly the games of a narrower one is not restated.

Benchmarks are measured facets (run length, time to first play and first reward, retry time,
taps, ad interval, assets, bundle size) summarised per genre node over the teardown games
that measured them: median, range, the games.

## The opportunity space

| Generator | Proposes | Its basis |
|---|---|---|
| `proven-core-new-axis` | a genre node with observed demand and coded teardowns, with one axis (theme, tone, rendering, fantasy) changed to a value popular games elsewhere use and none of its own coded games do | demand claims, the new value's codings and listings, an absence claim (0 of n) |
| `supply-gap` | an under-supplied cell | the saturation claim, demand and supply |
| `pattern-transfer` | a retention, progression, monetization, UX or session pattern prevalent in one genre, carried into another with observed demand where no coded game has it (a core mechanic is never transferred: that changes the genre) | the pattern, an absence claim, the target's demand |
| `portal-difference` | a genre node in a popularity list on one portal and absent from a popularity list on another scoped to include it | demand on one portal, a sampled absence on the other |
| `capability-screen` | every capability-catalog shape, screened against the platforms as before | the screen's claims; `evidence_backed` only with observed market presence |

Every opportunity carries: its facet cell, basis and thesis, market cells, competitors
(leaders first), adopted patterns with a hypothesis for each, benchmarks, monetization
(placements comparable games use, formats each platform supports), production (cost class
from the coded rendering and animation classes - the vocabulary's uncalibrated cost classes -
rigid-body physics and realtime networking, else the catalog's estimate), buildability,
audience, risks and confidence (evidence coverage of its cell, weakest tier, unknown facets,
whether any of it is fixture data).

The audience is never defaulted. Player type, intent, skill and age band come from the
corpus's codings or are `unknown` (a market descriptor such as "casual" is not taken for a
player type, and no age band is inferred). Device comes from the corpus, else from the
platforms' mobile share, labelled `hypothesis`, `source: platform`. Session behaviour comes
from measured runs, else from the catalog estimate, labelled `hypothesis`, `source: catalog`.

In a `proven-core-new-axis` opportunity the changed facet is what the opportunity proposes
to test, not something observed of its genre: it is a `hypothesis` (citing where it was seen
elsewhere), it does not count toward evidence coverage, and the handoff names it in
`changed_axis` so design can realise it as the title's intent - and say so.

**Buildability is checked last, and there are two roads.** The capability catalog entry whose
`genre_node` covers the opportunity's node builds it when it names **either** a
`design_archetype` (a hand-written design the design module carries) **or** a `genre_model` -
the `core/reference/genre-models.yaml` family whose model the offline genre seed author
designs a game from (`scripts/wgf_design/seed.py`). An entry that declares both fields null is
what the Factory cannot design yet; an installation's catalog that declares neither field
makes no claim, as before. The rendering must still match the opportunity's dimension.
Otherwise the opportunity is a `capability-gap`, with what is missing. It stays in the report
and in `capability_gaps`; it is never selected and never discarded.

`capability.genre_model` records the family the cell's genre node resolves to - the family
whose `nodes` list that node or its nearest listed ancestor - or `null` when no family lists
it, which is itself a capability gap and is said so in the reason ("No genre family lists this
genre node either"). Catalog 1.3.0 therefore makes eight shapes buildable that were
`unavailable` before - `logic-puzzle-levels`, `precision-platformer`, `flip-arcade`,
`wave-shooter`, `lap-racer`, `tower-defense`, `arena-survivor` and `stand-tycoon`, one per
family - without one relaxed rule. The selection rationale names which road a shape travels
("design archetype `drop-merge`" or "genre model `strategy`").

**One family is not one genre: a family carries one seed, and that seed is one game.** A
family's `seed` block is a complete starting design, so the entry a family builds is the entry
whose concept that seed describes - and the design consistency rules are what hold it to that
(`concept_mechanics_carried`, `design_adds_no_foreign_mechanic`: compared as the mechanic ids
of `core/reference/mechanic-lexicon.yaml`, the design may build no core mechanic the brief and
strategy do not imply, and must build every mechanic its concept names). `block-puzzle`,
`sort-puzzle` and `idle-merge` therefore stay capability gaps even though a family lists their
genre nodes: the puzzle seed is a slide-and-clear colour grid, not a board the player drops
given shapes onto, and the simulation seed is a served-shift tycoon, not a merge idler. Each
says so in its `unavailable` line. A second shape in a family is a second seed, never a second
entry pointed at the first one's design.

**An idea matches a family, not only a catalog shape.** A brief's words are matched against
the entry's genre, subgenre, title, core mechanic and market tags as before, plus its
`genre_node` and - for an entry that names one - its family's label and every genre node that
family covers. "tower defense", "tycoon" and "platformer" therefore find the entry that builds
them. A node id matches whole and is never split into its parts, so a block puzzle is not a
bubble-shooter.

**Identity.** An opportunity's id is a hash of what makes it that proposal - the generator,
the genre node and, per generator, the changed axis and value, the platform, or the
transferred pattern; a catalog shape's id is its entry's - never of the scan that found it.
The same proposal found on another day, or from a bigger corpus, is the same opportunity.

**Selection.** The run carries one opportunity: the first by brief match, then observed
evidence, then corpus-generated before a bare catalog shape, then evidence coverage, then
the shape's screen score, then generator order. A step may carry another with
`with: {select: <opportunity id>}` - how a G1 choice is taken forward, on this scan or a
later one. Only an eligible, buildable opportunity can be carried, and a scan waiting for
evidence carries nothing, pinned or not.

**Brief match.** With a game idea, an opportunity matches the brief only on words that say
what game it is (`analysis.brief_terms`, used by both the screen and `rank`). Generic
gameplay vocabulary - collect, beat, time, stars, levels, unlocks, modes, touch, camera, the
engine's name - is no word of any brief and never matches. Of the rest, one word of the
opportunity's defining vocabulary is a match: its genre lineage (ids, labels, aliases) and
its shape's genre, subgenre, title, market tags and, for a project concept, the brief it was
authored for. Descriptive vocabulary - the shape's mechanic sentence and the cell's facet
labels - matches only on at least two words (`IDEA_MIN_DESCRIPTIVE`). A shared incidental
word is therefore not a match: a marble-roll brief that says "collect gems" is not an
endless runner because the runner's mechanic says "collect pickups", and with
`idea_fallback: wait` the scan waits instead of carrying a different game.

**The backlog.** With `persist_backlog: true` (in `factory.discovery` or the step's
`with:`), every eligible and capability-gap opportunity is written to the backlog as
`discovered`, once: an opportunity already on file is left as it is. Off by default, like
lifecycle sync: a development checkout should not grow instance data on every run. A
`discovered` backlog entry does not exclude itself on the next scan; an entry somebody acted
on (scored, shortlisted, approved, promoted, parked, stale, rejected) excludes the same
opportunity - corpus-generated or catalog shape - with the reason.

## The report

`research-report` 1.2.0 adds, when `research_version: 2`:

| Section | Field |
|---|---|
| scope, sources, evidence | `scope`, `sources`, `claims`, `evidence_summary` (unchanged) |
| corpus | `corpus` (games, teardown/listing/fixture counts, sessions, vocabulary and analysis versions and hashes) |
| genre, gameplay, mechanics, theme, fantasy, art, audience, session/retention, monetization, UX, production | `analyses.<section>`: per facet, games in scope, coded, values and their games |
| competitors | `competitors`: every game, its listings and coded facets |
| market, trends | `market.frames`, `market.cells`, `market.trend` |
| platform | `platforms` (unchanged) |
| cross-game patterns | `patterns`, `benchmarks` |
| opportunities | `opportunities` (every one, full research block) and `selection` |
| capability gaps | `capability_gaps` |
| uncertainty | `gaps`: adds `insufficient-support`, `insufficient-demand-evidence`, `insufficient-history`, `unmapped-vocabulary`, `uncoded-facet`, `capability-gap`, `fixture-evidence` |

`candidates` (the catalog screen) is unchanged, so a reviewer still sees what else was
considered.

## The handoff

`opportunity.research` (1.3.0) is the contract. Strategy copies it into
`title-strategy.research` (1.4.0) as the handoff - theme and setting, player and emotional
fantasy, art (dimension, rendering, tone, palette, camera), gameplay (genre, mechanics,
loop, controls, progression, difficulty, retention hooks), **design constraints**, audience,
competitors, benchmarks, patterns, monetization, production, capability, market, risks,
confidence and every claim id - and decides from it what it has evidence for:

`design_constraints` is the content shape, in the vocabulary the design is actually held to
(`core/reference/genre-models.yaml`): the `family`, what one `unit_kind` is, how `progression`
and the `difficulty_shape` run, the `difficulty_axes`, the `session_band`, the
`retention_hooks`, and the `conventions[]` a player of the genre expects without being told (a
retry that keeps the board, a next button after a level, a best score kept between sessions).
Every value keeps its own tier and claims, and a facet nobody observed stays `unknown` - the
design then falls back to the family's default and says so in `applied`. A convention is
counted, never asserted: a UX, retention, session or progression pattern has to be prevalent
in the cell's coded games before it is one. An opportunity nothing can design, or whose genre
node no family lists, carries no `design_constraints` at all.

| Strategy field | From research | Otherwise |
|---|---|---|
| `concept.control_scheme` | the control comparable games were coded with (via the vocabulary's `control_scheme` map) | the concept's wording |
| `session.target_seconds` | the median measured run length | the catalog estimate or the policy default |
| `audience.type` | the evidence-backed player type | casual, as a recorded assumption |
| `prototype_must_prove` | a first-reward bar from measured games | - |
| `concept.content_model` | `research.design_constraints`: the family, unit kind, progression, difficulty shape and axes research coded for this cell (`source: research`) | the family's own defaults, from `core/reference/genre-models.yaml` (`source: default`) |

Design reads `title-strategy.research` and records its own `applied`:

| Design decision | From research | Otherwise |
|---|---|---|
| archetype | the `design_archetype` research's capability check named; `agent` is refused by the archetype author (research already waits for it); with no design archetype but a `genre_model`, the genre seed author synthesizes the design from the family's own `seed` block | keyword selection on the strategy, among the archetypes of the dimension research states (`art.dimension`); none of that dimension is refused |
| `genre` and `build_spec.content` | the strategy's `concept.content_model` (itself from `research.design_constraints`): the family the design is held to, the unit kind, the progression and difficulty models and the axes | the family the design's own genre node resolves to; with no family at all, nothing is applied and no content check runs |
| visual identity kit | the kit matching most of the supported tone, palette and rendering (`wgf_design/identity.py` `TRAITS`); the title digest only breaks ties | the title digest within the archetype's affinity |
| fantasy | the research fantasy, in its theme and setting | the archetype's fantasy |
| art direction | prefixed with the theme and the matched art direction | the kit alone |
| time to first play | a measured median stricter than the audience default | the audience default |

If an author drops the research, the design step carries it from the strategy anyway.

## What the shipped corpus supports today

`workspace/research` holds 22 snapshots - portal documentation and three puzzle-category
listings, captured 2026-09-23 - and **no teardown records**. On it, V2 builds 16
listing-depth games, genre-and-platform patterns, demand shares for the puzzle subgenres on
Poki and CrazyGames, one portal-difference opportunity (block puzzle, a capability gap) and
the catalog screen; theme, fantasy, art and gameplay are `unknown` and are reported as such
(`uncoded-facet`), trend is `insufficient-history`, and the selection is a puzzle shape the
Factory can build - `logic-puzzle-levels`, from the puzzle genre model. The machinery is real; the corpus is thin. Teardowns and repeated listing
captures are what make it rich, and they are a research activity, not code: no gameplay
observation has been invented to fill it.

## Status

| Capability | Status |
|---|---|
| Game corpus, vocabulary, teardown model, coding tiers | Implemented |
| Support-checked patterns and benchmarks | Implemented |
| Demand / supply / saturation / competition / trend, kept apart | Implemented (trend needs repeated captures; none shipped) |
| Five opportunity generators, capability gaps, selection pin, backlog persistence | Implemented |
| Strategy and design consuming the research, `applied` | Implemented |
| Genre families: `capability.genre_model`, `research.design_constraints`, buildability from a family, idea matching on a family's nodes | Implemented (`core/reference/genre-models.yaml` 1.0.0, catalog 1.3.0) |
| Conventions counted from the corpus | Implemented; the shipped corpus has no teardowns, so no convention reaches the prevalence bar yet |
| Audience model (evidence-backed or unknown) | Implemented |
| Ad-placement patterns (genre/mechanics × triggers) | Implemented |
| Teardown collection procedure (`competitive-teardown.md`, `wgf-corpus.py`) | Implemented; automated browser play is not - a person or an agent plays and writes the record |
| Production cost calibrated from shipped titles | Not implemented: the cost classes are the vocabulary's, unmeasured; one shipped title is not a calibration set |
| Scoring model v2 (saturation, differentiation, audience fit) | Not implemented: needs a new versioned model file and evidence to weight it |
| Deeper combination search, analytics feedback, thumbnail-based visual saturation, cross-portal comparison beyond `portal-difference`, a persistent pattern library across scans | Not implemented (P2) |

## Evidence corrections

The worked example broke its own rules. Superseded, not edited:

- `claim-0a01` (Yandex arcade top 20, 14 one-touch) had no backing snapshot and its excerpt
  described a method. `claim-0a05` restates it as a hypothesis (0.4); `claim-0a01` gained
  only `superseded_by`.
- `claim-0a03` derived only from it; `claim-0a06` restates it as a hypothesis.
- `eval-0b01` marked `technical_risk` and `asset_cost` derived with no evidence and cited
  `claim-0a01`/`claim-0a03`. `eval-0b02` supersedes it: those dimensions are hypotheses at
  half weight, coverage falls to 0.246 - below the 0.60 floor - and its arithmetic is
  stated. `opp-001.latest_evaluation_id` still names `eval-0b01`, because moving the cursor
  would re-pin the opportunity and every artifact downstream of it; the supersession chain
  (`supersedes_evaluation_id`) is the record.

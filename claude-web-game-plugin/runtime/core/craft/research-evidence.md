# Research evidence: supplying what a waiting market scan needs

Serves: `portfolio:market-scan` - the evidence snapshots the discovery step reads, and the
project concept for a brief no catalog shape carries. Role: research.

The discovery step only *reads* evidence; it never browses. When a workflow run's research
step waits for input, the input is the research role's to supply, and then the run is resumed
- the step itself is never edited, and no artifact is written by hand. It waits for one of two
things, and its message says which:

- **no external evidence** - no snapshot was read and no live probe matched. Supply snapshots.
- **the brief matches no concept research can carry** - the person's game idea fits no
  catalog shape. Supply a project concept for it (below). Evidence comes first: a concept
  never stands in for evidence.

## The one rule

**Evidence is fetched, never written.** Every observation quotes a page that was actually
retrieved, at the time it was retrieved. A statement nobody can check against its source is a
hypothesis in disguise, and the step strips the disguise: an observation without a verbatim
excerpt is rejected, and a source dated after the scan is refused. A page that could not be
fetched is not evidence; record nothing for it. A market that the pages do not show is a
finding, not a gap to fill with plausible text.

## Snapshots

One JSON file per retrieved page, in the project's `workspace/research/snapshots/`, named
`<id>.json`:

| Field | Required | Rule |
|---|---|---|
| `id` | yes | `snap-<kebab-case>`, unique, the file name's stem |
| `source_uri` | yes | the URL actually fetched |
| `source_kind` | yes | `portal-listing`, `portal-docs`, `analytics`, `playtest`, `market-report`, `competitor-teardown`, `community`, `internal-history`, `other` |
| `observed_at` | yes | ISO 8601 UTC time of the retrieval - never later than the scan, never backdated |
| `retrieved_via` | by convention | how: `web-fetch`, `interactive-browser`, ... |
| `platform` | when the page is a portal's | the platform id (`core/reference/platforms/<id>.yaml`) |
| `title` | no | the page's title |
| `observations` | yes | a list, one falsifiable statement each (below) |

Each observation:

| Field | Rule |
|---|---|
| `statement` | one checkable sentence about what the page shows |
| `excerpt` | the **verbatim** text of the page the statement rests on |
| `subject` | any of `platform`, `genre`, `mechanic`, `audience`, and `dimension` (an id of `core/reference/dimensions.yaml`) |
| `facts` | optional machine-readable facts; only these keys count, anything else is reported and ignored: `ads.rewarded`, `ads.interstitial`, `ads.banner`, `iap`, `sdk_required`, `mobile_support_expected`, `web_exclusive` (booleans), `max_bundle_mb`, `monthly_players` (numbers), `locales_required`, `review_days` (lists), `category` (`{name, genre, game_count}`), `reference_title` (`{name, genre, list}`) |
| `tags` | optional labels |

Market presence is read from `category` and `reference_title` facts: a category listing in
one of a concept's market tags helps it be found, and a reference title counts only when its
`genre` is the concept's own kind of game. Capture the portal pages that list games of the
brief's kind - a category page, a tag page, a search result - and record each listed title the
page names as a `reference_title` with the genre the page gives it. Capture the platform
requirement pages (ads, bundle size, SDK, locales) a candidate platform's fit depends on.

Snapshots go stale after the scoring model's evidence TTL; a stale source is kept and weighs
less. Re-capture rather than re-date.

## A project concept for an unmatched brief

When the person's brief names a game no catalog shape carries, research waits instead of
substituting the nearest shape. Write the concept the brief describes to the project's
`workspace/research/concepts.yaml`, in the catalog's entry shape:

```yaml
version: 1.0.0
archetypes:
  - id: <kebab-case, not a catalog id>
    brief: "<the run's idea, exactly as the run recorded it>"
    design_archetype: agent     # or a design archetype id that designs it as written
    title: ...
    genre: ...
    subgenre: ...
    market_tags: [...]          # the genres the captured listings use for this kind of game
    core_mechanic: ...          # the brief's game, stated as what the player does
    fantasy: ...
    core_loop: ...
    rendering: 2d | 3d          # as the brief names it
    session_seconds: ...        # every figure below is an estimate; the step records each
    replayability: ...          # one as a hypothesis claim, capped like any catalog figure
    technical_complexity: ...
    asset_complexity: ...
    dev_speed_days: ...
    asset_cost_usd: ...
    bundle_mb: ...
    monetization: {primary: ..., secondary: [...], rationale: ...}
    priors: {...}
```

The concept restates the brief; it does not replace it. Its `core_mechanic` and `core_loop`
describe the game the brief names - the mechanic, the opponent, the goal and the dimension it
states - in the words a design would use, because the design is later held to carry exactly
those mechanics and add none. Where the brief is ambiguous, resolve it from the brief's own
words and say so in `fantasy` or the loop; never trade it for an easier game. `brief` must be
the run's idea verbatim: a concept written for another idea is refused. `design_archetype:
agent` means only an agent design author can design it, and the run must be configured with
one. Its figures are unmeasured; the scan records them as hypotheses and says so.

Then resume the run. The scan screens the concept like any catalog entry, against the same
evidence, the same vetoes and the same platform fit.

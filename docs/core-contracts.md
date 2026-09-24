# Core Contracts

How the Factory knows an artifact is what it says it is, at every boundary of the new-game
pipeline, without anyone having to remember to run ajv.

Three mechanisms, all in `scripts/wgflib/`:

| Mechanism | Where | What it checks |
|---|---|---|
| Schema validation | `jsonschema_lite.py` | The whole draft 2020-12 schema: nested objects, enums, patterns, formats, conditionals, `$ref`s into `core/artifacts/shared/` |
| The contract | `workflow/contracts.py` `ArtifactContracts` | Schema validation, plus JSON representability, `provenance.artifact_type` == the type, and `provenance.content_hash` reproducing |
| Lineage | `workflow/contracts.py` `check_lineage` | `provenance.inputs` pins exactly the versions of the inputs a step consumed |

The engine calls `ArtifactContracts` on every artifact a step produces (the API wires it in);
a problem is a non-retryable `FAILED` and nothing is written. With a validator configured it
also re-checks every input before the step runs, and calls `check_lineage` on every output
that declares `provenance.inputs` (§3). Build commits have a lineage of their own, across
develop, review, sdk, verify and release: §5.

The proof is `scripts/tests/test_core_contracts.py`, the CONTRACTS category of the Core
Acceptance Suite.

---

## 1. The validator — `wgflib/jsonschema_lite.py`

Standard library only. `Validator(schema, registry).iter_errors(instance)` returns
`ValidationError`s with `pointer` (RFC 6901, `""` is the root), `message`, `keyword` and
`schema_path`; `str(error)` is `"<pointer>: <message>"`. Order is deterministic: keywords in a
fixed order, object members in sorted key order.

**It refuses what it does not implement.** The constructor walks every reachable subschema and
raises `SchemaError` on an unknown keyword, an unknown `format`, an unresolvable `$ref`, a
pattern Python cannot compile faithfully, or a `$schema` other than 2020-12. A schema that
starts using `unevaluatedProperties` breaks here, loudly, rather than being silently
under-validated. `test_every_keyword_the_schemas_use_is_implemented` enumerates the keywords
in `core/artifacts/**` programmatically and fails on any the validator would refuse.

| Implemented | |
|---|---|
| Core | `$schema`, `$id`, `$ref` (local pointer, relative to the resource `$id`, or absolute), `$defs` |
| Any | `type` (arrays of types; `1.0` is an integer; `true` is neither integer nor number), `enum`, `const` (JSON equality), `allOf`, `anyOf`, `oneOf`, `not`, `if`/`then`/`else` |
| Object | `properties`, `patternProperties`, `additionalProperties` (bool or schema), `required`, `dependentRequired`, `dependentSchemas`, `propertyNames`, `minProperties`, `maxProperties` |
| Array | `items`, `prefixItems`, `minItems`, `maxItems`, `uniqueItems`, `contains`, `minContains`, `maxContains` |
| String | `minLength`, `maxLength` (code points), `pattern` |
| Number | `minimum`, `maximum`, `exclusiveMinimum`, `exclusiveMaximum`, `multipleOf` (decimal arithmetic) |
| Format (asserted) | `date-time`, `date`, `time`, `email`, `uri`, `uri-reference`, `uuid`, `ipv4`, `hostname` |
| Annotations (ignored) | `title`, `description`, `$comment`, `examples`, `default`, `deprecated`, `readOnly`, `writeOnly`, `content*`, any `x-*` |
| Refused | `unevaluatedProperties`, `unevaluatedItems`, `$dynamicRef`, `$dynamicAnchor`, `$anchor`, `$recursiveRef`, `$vocabulary`, `definitions`, `dependencies`, anything else |

Keywords actually used by `core/artifacts/**` today: `$defs $id $ref $schema
additionalProperties allOf const enum format if items maxItems maximum minItems minLength
minimum not oneOf pattern prefixItems properties propertyNames required then type
uniqueItems` (+ annotations). Only `format: date-time` is used.

### Where it differs from ajv, on purpose

| Case | ajv (ajv-cli@5, ajv-formats@2) | jsonschema_lite |
|---|---|---|
| `date-time` without a UTC offset (`2026-09-03T14:00:00`) | accepted (ajv-formats@2 treats the offset as optional) | **rejected** — RFC 3339 requires it, and a timestamp without one is ambiguous |
| `date-time` offset without a colon or minutes (`+0530`, `+05`) | accepted | rejected (RFC 3339 form is `+05:30`) |
| `pattern` | ECMA-262 with the `u` flag | Python `re` after translation: unescaped `$` → `\Z` (Python's `$` also matches before a trailing newline), `\d`/`\w` → ASCII classes (Python's match Unicode digits/letters), `(?<name>` → `(?P<name>`. `\p{…}`, `\u{…}`, `\c`, `\k` raise `SchemaError`. |
| Error reporting | first error only (no `allErrors`) | every error; `oneOf`/`anyOf` report the closest alternative (the one that failed deepest) and its errors |

`AjvDifferential` runs both on ~1,500 documents — the worked example, every mock output, the
reference YAML, and 40 seeded mutants of each (deletions, type swaps, bad enums, broken
patterns and dates, extra properties, trailing newlines) — and requires identical verdicts.
It skips when `npx` cannot run ajv (offline without a cache) or `WGF_SKIP_AJV` is set. No
mutant exercises the two date-time rows above; they are covered by
`ValidatorSemantics.test_formats_are_asserted`.

## 2. The contract — `ArtifactContracts`

```python
contracts = ArtifactContracts(untyped=definition.untyped_artifacts)
problems = contracts("game-design", content)      # [] when valid
```

In order:

1. **A contract exists** — a schema whose `x-wgf.id` is the type, or the type is listed in the
   workflow's `untyped_artifacts` (then only "non-empty JSON object" is checked).
2. **Content is a JSON object** JSON can represent: no NaN or infinities, no non-string
   keys, no tuples, sets, bytes or other Python objects. Otherwise it cannot be written,
   hashed or read back as the same value, and nothing else is checked.
3. **Provenance integrity** (when the schema requires provenance):
   `/provenance/artifact_type` equals the type; `/provenance/content_hash` reproduces
   (`wgflib.hashing.content_hash`).
4. **The full schema.**

Problems read `"<type>: <json pointer>: <message>"`, e.g.
`game-design: /session/target_seconds: expected number, got string`. At most `MAX_PROBLEMS`
(20) are returned, plus `"... and N more problems"`; the provenance integrity problems are
always kept inside the cap. `contracts.problems(type, content)` returns them uncapped.
`contracts.validator(type)` returns the compiled `Validator` for direct use.

## 3. Lineage — `check_lineage(content, consumed)`

Lineage in the Factory is `provenance.inputs[]`: one
`shared/provenance.schema.json#/$defs/artifactRef` (`artifact_id`, `artifact_type`,
`content_hash`) per artifact this one was derived from. The hash is what makes staleness
detectable.

```python
from wgflib.workflow.contracts import check_lineage
problems = check_lineage(output_content, inputs.refs)     # inside a step, or in the engine
```

`consumed` is a mapping `{type: item}` or an iterable of items, where an item is a workflow
`ArtifactRef` (its `content_hash` is the engine's canonical digest), a provenance-style
reference dict, or the consumed artifact's full content. It reports:

| Problem | Meaning |
|---|---|
| `/provenance/inputs: does not pin consumed <type> (<hash>)` | a consumed input is missing from the lineage |
| `/provenance/inputs/<i>: pins <type> at <h1>, but <h2> was consumed` | the artifact was built from a different version than the step was given |
| `/provenance/inputs/<i>: pins <type> at <h>, which this step did not consume` | a stale extra pin of a consumed type — e.g. copied from a previous run |
| `/provenance/inputs/<i>/artifact_id: …` | right hash, wrong identity |

Pins of types the step did not consume (claims, artifacts carried forward from further
upstream) are left alone: nothing at this boundary can check them. Consumed items with no
content hash (untyped artifacts) are skipped.

**In the engine.** When an `artifact_validator` is configured and an output's
`provenance.inputs` is a list, the engine checks it against the refs the execution actually
consumed (`step_state.consumed`, resolved to `ArtifactRef`s with their content hashes). On
top of `check_lineage` it refuses a pin of a type the step *declares* as an input but was not
given on this visit — an optional input absent from the run (develop's `qa-report` and
`review-report` on its first visit) that the output nevertheless claims to derive from.
Optional inputs are otherwise handled correctly by `check_lineage` as it stands: an absent
input is not consumed, so nothing requires a pin of it; a present one is consumed and must be
pinned at the version given. Any problem is a non-retryable `FAILED` naming the output and
the pin, and nothing is written. Every real module and the mocks pin what they consume;
`scripts/tests/test_core_lineage.py` is the proof.

`test_the_worked_example_lineage_closes` checks that every pin in `workspace/` names an
artifact that is there, at the pinned hash; the mock tests check every run artifact's lineage
against what its producer consumed.

---

## 4. Boundary audit

What crosses each step boundary of `core/workflows/new-game.workflow.yaml`, and what the
consumer actually reads (from the module source, not the schema). Every module pins its
inputs as `{artifact_id: <input provenance.artifact_id>, artifact_type, content_hash:
<ArtifactRef.content_hash>}`, and builds `artifact_id` as
`wgf:<type>:<slug>:<yyyymmdd>-<min(execution,99):02d>` with `status: draft`. Schemas carry no
version of their own: `provenance.schema_version` is what the producer claims, and each
module hardcodes it (column *schema_version written*).

`tech-plan`, `review` and a real `release` step do not exist yet; their rows are the target
boundary (§4.2).

### 4.1 Current boundaries

| # | Producer step → consumer | Artifact (`$id` …/schemas/artifacts/…) | schema_version written | Fields the consumer reads | Lineage | Consumer's error states |
|---|---|---|---|---|---|---|
| 1 | research (`wgf_discovery`) → strategy | `opportunity.schema.json` | 1.0.0 | `id`, `title`, `title_id`, `state`, `concept.{genre,subgenre,core_mechanic,core_loop,fantasy}`, `audience.{device,regions,type}`, `estimates.{dev_speed_days,scope_complexity,asset_cost_usd,session_seconds}`, `candidate_platforms`, `monetization_hypothesis.*`, `risks[].{severity,description,claim_refs}`, `hypothesis`, `claim_refs`, `provenance.artifact_id` (`wgf_strategy/planner.py`, `step.py:59-110`) | opportunity pins the research-report by its own `content_hash` (`wgf_discovery/step.py:407`); research-report is a root (`inputs: []`), its sources recorded as `sources` + `method.corpus_hash` | missing → WAITING_FOR_INPUT; major ≠ 1 → FAILED non-retryable; wrong state / missing concept / no platforms → FAILED non-retryable |
| 1b | research → (G1, scoring) | `research-report.schema.json` | 1.0.0 | not consumed by any workflow step today | root | — |
| 2 | strategy → design, develop | `title-strategy.schema.json` | 1.1.0 | design: `title_id`, `opportunity_id`, `platform_set[].{id,profile_version,role}`, `out_of_scope`, `prototype_must_prove`, `mvp`, `session.{target_seconds,first_session_seconds}`, `audience.{type,player_description}`, `monetization.{placements,class}`, `success_criteria[].{id,when}`, `kill_criteria[].{id,when.left}`, `one_liner`, `why_this_opportunity`; develop: `prototype_must_prove`, `kill_criteria[].id` | pins opportunity; copies `opportunity_id`, `title_id` | design: missing → WAITING; major ≠ 1 → FAILED; platform pin mismatch → BLOCKED; inconsistent → FAILED route `descope` with the artifact |
| 3 | design → init, assets, develop, sdk, verify | `game-design.schema.json` | 1.1.0 | init: `title_id`, `consistency.status` (= pass), `monetization.placements[].platforms`, `platform_constraints_applied[].platform_id`, `fantasy`, `core_loop`; assets: `asset_requirements[]`, `art_direction`, `audio_direction`, `ux.screens`, `scope.{asset_budget,locales}`, `monetization.placements[].kind`; develop: `scope.*`, `session.*`, `ux.*`, `monetization.placements[]`, `fantasy`, `core_loop`, `pillars`, `controls`, `difficulty`, `progression`; sdk: `monetization.placements[]`, `retention.{hooks,targets}`; verify: `controls`, `session.end_condition`, `progression`, `retention.progression_loop`, `monetization.placements[]`, `scope.locales` | pins title-strategy | init: missing → WAITING, bad design → FAILED; **no schema_version check in init or sdk**; assets refuses only a *newer* major |
| 4 | init → assets, develop, sdk, verify | `scaffold-record.schema.json` | 1.0.0 | assets: `game_config.platforms[].{id,role}`; develop: `title_id`, `repository.{name,owner,url}`; sdk: `repository.name`, `game_config.platforms[].id`; verify: `repository.name`, `game_config.platforms` | pins game-design; `idempotency_key` (`wgf-init:<run>:<step>`), `template.commit_sha` (only when created), `outcome` created/reused | develop: missing → WAITING; no checkout → BLOCKED |
| 5 | assets → develop, verify | `asset-manifest.schema.json` | 1.1.0 | develop: `items[].{id,label,type,source,status,license,scope_tier,notes}`; verify: `items[].{id,status}`, `complete` | pins game-design (+ scaffold-record when present) | develop: missing → WAITING |
| 6 | develop → review, sdk, verify, release | `prototype-report.schema.json` | 1.0.0 | sdk: `title_id`, `build_ref.{commit_sha,url}`; verify, release: `build_ref.commit_sha` | pins every consumed ref (incl. a discarded passing qa-report); `build_ref.commit_sha` is the keyed develop commit or HEAD — no HEAD is BLOCKED, never a placeholder | sdk: all inputs optional, no WAITING path; a prototype commit that is not HEAD (or HEAD's base) → BLOCKED |
| 7 | sdk → verify, release | `sdk-report.schema.json` | 1.2.0 | `platforms[].{platform_id,features[].{feature,status}}`, `build_ref.{commit_sha,base_commit_sha,sdk_commits}` | pins every ref; `build_ref.commit_sha` is the commit verified (its own keyed commit, or HEAD), `base_commit_sha` the prototype's; no readable HEAD is BLOCKED, never `"unknown"` | verify: major ≠ 1 → FAILED; lineage broken → `source.upstream-commits` BLOCKED |
| 8 | verify → develop (on `fail`), release | `qa-report.schema.json` (+ `verification-report.schema.json`) | 1.0.0 | develop: `verdict`, `blocking_defects[].{id,severity,summary,repro}`; release (mock): pins only | both pin every loaded input; qa-report also pins the verification-report; `commit.sha`, `release_id`, `build_ref.artifact_hash` | FAIL → FAILED route `fail`; BLOCKED unrouted |
| 9 | release → $end | `release-manifest.schema.json` | 1.2.0 | — | pins every consumed ref (qa-report, verification-report, sdk-report, prototype-report, scaffold-record, review-report); `evidence.commit_lineage`, `evidence.review` | — |

### 4.2 Target boundaries (not built yet)

| Boundary | Artifact | What the consumer will need | Owner |
|---|---|---|---|
| design → **tech-plan** → init | `tech-plan.schema.json` (required: `engine`, `architecture`, `perf_budgets`, `repo_params`, `dev_plan`) | init should read `repo_params` and `engine` instead of re-deriving from game-design; develop should compare `engine` with the repository's `game.config` | Team T |
| verify → **review** | review-report (new schema) | must pin the qa-report and verification-report it judged, by hash | Team D |
| verify → **release** | `release-manifest.schema.json` | from qa-report: `verdict` (= pass), `blocking_defects` (empty), `accepted_defects`, `perf_results[].within_budget`, `platform_checks[]`, `build_ref.{commit_sha,artifact_hash}`, `title_id`, `release_id`. **Not derivable from qa-report alone**: `target_platforms[].{role,profile_version}` (in scaffold-record `game_config.platforms[].profile` or sdk-report), `version`, `changelog`. `release_id` must match `^r[0-9]+$`, which verify's `candidate-<sha12>` does not; `commit_sha` may be `"unknown"` | Team E |

### 4.3 Gaps

Ambiguous or unsafe, in order of risk. None is a schema violation — every artifact the
modules emit under the test suite validates — they are what a valid artifact can still get
wrong.

1. ~~**Lineage is not enforced in the engine.**~~ Closed: the engine calls `check_lineage`
   on every output that declares `provenance.inputs` (§3), and re-checks inputs.
2. **No schema declares its own version.** `provenance.schema_version` is a free semver each
   producer hardcodes (1.0.0 or 1.1.0 above); consumers check only the major, some not at all
   (init, sdk), and assets accepts `0.x`. A consumer cannot know which minor it is reading.
   *Recommendation: an `x-wgf.schema_version` per schema and a contract check that the
   claimed version's major equals it.*
3. **The game repository's location is not in `scaffold-record`.** init records
   `repository.{owner,name,url}`; develop, sdk and verify each rebuild a local path from their
   own config key. Nothing makes them agree. *Team T is extending scaffold-record.*
4. **Placement identity is positional.** sdk derives placement ids from the design's trigger
   order (`wgf_sdk/design.py:101`); reordering `monetization.placements` renames them.
5. **`game-design.build_spec` has no consumer.** Downstream steps read `ux.screens`,
   `asset_requirements` and `monetization.placements`, so the 1.1.0 build spec is not what
   gets built from.
6. ~~**Commit lineage degrades silently.**~~ Closed: develop and sdk return BLOCKED instead
   of a placeholder commit, sdk commits its integration, and verify and release apply one
   commit lineage rule (§5).
7. **Workflow and `x-wgf` disagree on who produces and consumes.** `asset-manifest`'s
   producer is `title:design` but the `assets` step serves `title:prototype`; `game-design`'s
   consumers omit `title:scaffolding`, which the `init` step reads it at; `research-report`
   lists `title:strategy` as a consumer but the strategy step does not take it.
8. **`develop` treats a declared input as optional.** Without `title-strategy` its report's
   kill criteria are silently empty.

---

## 5. Commit lineage

Artifact lineage (§3) says which *versions of artifacts* an artifact was derived from. Commit
lineage says which *commits* the evidence of one build may name, and how they must relate.
It is the reason a real run can release: develop commits, review reads that commit, sdk
commits its integration on top of it, verify and release are about exactly the result.

```
develop   commit P   (Wgf-Develop-Key: <run>:develop:<visit>)   prototype-report.build_ref.commit_sha = P
review    reads P                                               review-report.reviewed_commit = P
sdk       commit S on P (Wgf-Sdk-Key: <run>:sdk:<visit>)        sdk-report.build_ref = {commit_sha: S,
          or no commit (S = P) when nothing changed                 base_commit_sha: P, sdk_commits: [S]}
verify    at HEAD = S                                           verification-report.commit.sha = S
release   at HEAD = S, clean tree, verified bundle              release-manifest.commit_sha = S
```

**The rule.** With `P` the prototype-report's commit, `B` the sdk-report's
`base_commit_sha`, `S` its `commit_sha`, `V` the verified commit (verification-report
`commit.sha`, qa-report `build_ref.commit_sha`) and `H` the checkout's HEAD:

1. `S == V == H`. The SDK evidence, the verification and the release are about one commit.
2. `P == B`. sdk built on the commit develop made — the one review read.
3. `B..S` is exactly the sdk step's commits: `S` descends from `B`
   (`git merge-base --is-ancestor B S`), `git log B..S` is exactly the sdk-report's
   `sdk_commits` (required whenever `B != S`), and each carries a `Wgf-Sdk-Key:` trailer
   whose key starts with this run's id. **A trailer is never what makes a commit sdk's**:
   the key derives from the run id, which every developer command is given, so anyone who
   can commit can forge one. The record is the sdk-report (held by the run, pinned by hash
   downstream), and the sdk step itself decides from a ledger it keeps in the run directory
   (`<run dir>/sdk/<step>.commits.json`), outside the checkout.
4. When the run holds a review-report, it approved exactly `P` (and, when it pins a
   prototype-report, the run's newest one). `request-changes` or `no-verdict` refuses.
   `skipped` (no reviewer configured) does not refuse: the release manifest records
   `evidence.review.status: skipped` and the step's message says the build is UNREVIEWED.
   It is never recorded as approved.
5. No placeholder is a commit: a missing sha, `unknown`, or 40 zeros refuses. develop and
   sdk return `BLOCKED` when they cannot establish a commit, rather than emit one.
6. When git cannot read the history rule 3 needs, the rule does not hold. Nothing is trusted
   on the reports' say-so.

An sdk-report without `base_commit_sha` (schema < 1.2.0) is read as `B == S`: it claims no
commits of its own, so rule 2 becomes `P == S`. Without an sdk-report, `P == V == H`.

Anything else — a human or agent commit between develop's and sdk's (unreviewed code riding
along), sdk evidence about another commit, an sdk commit keyed by another run, an approval of
another commit — is `commit-lineage-mismatch`, with a message naming the commits.

**Where it is enforced.**

| Where | How | Outcome |
|---|---|---|
| `sdk` (`wgf_sdk/commit.py`) | before writing: HEAD is `P` or `P` + commits its ledger records (a forged trailer is foreign); no uncommitted change outside the integration's files, and none to its own files unless this visit already started (then they are reset to HEAD and regenerated, so a hand edit never survives into its commit) | `BLOCKED` |
| `verify` (`source.upstream-commits`) | rules 1–3, 5, 6 with the checkout's git, `V = H` | `BLOCKED`, message starts `commit-lineage-mismatch` |
| `release` (`wgf_release/lineage.py`) | rules 1, 2, 4, 5 from the reports before anything else; then `H`, and rule 3 with the checkout's git | `FAILED` (not retryable), refusal code `commit-lineage-mismatch` / `commit-unknown` / `review-not-approved` |

The rule is implemented once, in `scripts/wgf_verification/lineage.py`
(`lineage_problems`, `review_problems`); verify and release pass it their own
`git(*args) -> (ok, stdout)`. The git-level proof is
`scripts/tests/test_core_lineage.py` (`CommitLineage`).

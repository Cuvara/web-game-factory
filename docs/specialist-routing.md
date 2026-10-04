# Specialist routing

A quality finding becomes role-specific work that the workflow routes, without a person
translating it. This is WS-8 of [quality-gap-audit-2026-10.md](quality-gap-audit-2026-10.md)
(section 4). It is the routing mechanism. WS-7's quality scorecard plugs into it as one more
producer of findings.

## Why

Before workflow 10, every failure that sent a build back went to one generalist develop
visit, whatever the failure was about. Examples: a dark 3D scene (I-18, I-19), a level set
with one element (I-03, I-15), canvas UI the bot could not reach (I-01), a code review
blocker. Each got the same brief, the same developer tried, and the loop limit stopped the
run. What fixed them was a person who read the failure, decided which discipline owned it,
and briefed that discipline by hand (audit section 2.2, "gen"). The routing below makes that
translation data.

## The pieces

| Piece | Where | What |
|---|---|---|
| The finding contract | `core/artifacts/shared/quality-finding.schema.json` | `finding`: id, dimension, severity, source (producer, step, check, viewport, artifact), summary, measured, bar, evidence refs, owner, task (change, acceptance, design field), route, assets. `request`: what a person types at G4. |
| The specialists | `core/roles/roles.yaml` 1.1.0, charter `core/roles/specialists.md` | Each specialist is an implementer with `focus`, `reads` (its craft playbooks in `core/craft/`) and `writes` (its writable scope in the game repository). |
| Ownership and order | `core/reference/specialist-routing.yaml` 1.0.0 | The dimensions, the one owner of each, the visit order, the 2D/3D words, and each producer's table: check id, VQA category, score, state question or listing section, mapped to a dimension. |
| The triage step | `scripts/wgf_triage/`, step `triage` in `new-game` | Normalizes, groups, routes. Writes a `triage-report` (`core/artifacts/triage-report.schema.json`). |
| The specialist visit | `scripts/wgf_develop/specialist.py` | The develop visit routed as `triage.<role>`: the specialist's brief, scope and record. |

### Dimensions and owners

| Dimension | Owner | Route |
|---|---|---|
| content, level-design | `level-designer` | develop |
| progression | `systems-designer` | develop |
| difficulty | `encounter-designer` | develop |
| gameplay, feel | `gameplay` (the generalist; also the default owner) | develop |
| environment-3d, lighting-material | `environment-artist` | develop |
| art-2d | `artist-2d` | develop |
| ui | `ui` | develop |
| audio | `audio-designer` | develop |
| platform | `sdk` | develop |
| store-copy | `copywriter` | listing |

The rows are in visit order: structure, then systems, then the loop's code, then its look
and sound, then platform wiring. Polish applied to a structure that is about to change is
wasted work. Some producer words depend on the design's `engine.dimension`, which is the
only branch:

- "art", "environment" and "composition" mean `art-2d` in 2D and `environment-3d` in 3D.
- "lighting" means `art-2d` in 2D and `lighting-material` in 3D.

No consumer branches on a game, an engine name or a family id.

## How a finding is made

`wgf_triage.findings.normalize(kind, report, routing)` reads one producer's report:

| Producer | Becomes a finding | Route |
|---|---|---|
| playability-report | each required FAIL check (`content.*` to content, `restart.works` to ui, `entities.*` to art, ...) | develop |
| production-quality-report | each required FAIL check (`assets.*` to art, `scene.contrast` to lighting, `ui.*`, `audio.*`) | the check's own (assets or develop) |
| visual-qa-report | every judge finding (blockers, and the majors and minors that travel with them), each failed score, each failed state answer, the look; a failed mean, as each dimension below 4 | the finding's own, or the rubric's for the dimension or question |
| content-sufficiency-report | each typed finding (FAIL and WARNING checks) in its own dimension - content, level-design, difficulty, progression - with its observed value, bar and evidence | develop; `design` for a `design-gap` finding, whose `design_gap` the design step reads from the report |
| review-report | each blocker (gameplay) | develop |
| qa-report | each blocking defect (gameplay; `platform` when it names a platform), each failed suite, else the verdict | develop |
| listing-validation-report | each required FAIL check, by section (`metadata` and `grounding` to store-copy, `platforms` to platform, `screenshots`, `video` and `assets` to art-2d) | listing |
| a G4 decision | each typed finding a person gave (`from_requests`), or else the note, as one generalist finding | the owner's, or `design` / `assets` when the person asks for it |
| quality-scorecard (WS-7) | its findings as they are, with owner and route recomputed from the routing data | the owner's, or `design` |
| quality-report (WS-7, the `quality-gate` step) | each open finding in a dimension the report held below its floor, its quality dimension mapped onto a routing dimension (`producers.quality-report.dimensions`), with observed value, expected threshold and asset ids | the owner's; `design` for a `design-gap` finding, `assets` for an `assets` one |

A finding id is `<producer>:<check>[@<viewport>]`, for example
`visual-qa-report:score:environment` or `playability-report:content.variety@mobile`. It stays
the same across measurements. Acceptance is the producer's own words: "visual-qa judges frames
of the next build and no longer fails `score:environment` (bar: 3)".

## How the triage step routes

Every route that sends a build back goes to `triage`: playability `fail`,
production-quality and visual-qa `develop`, content-sufficiency `develop` and `design-gap`,
review and sdk-review `request-changes`, verify `fail`, and G4 `iterate`. assets also continues to triage, on the first pass and after a
re-entry. The step:

1. **Picks the build.** The build is the newest prototype-report. A gate report produced
   after it (run-local `seq`) measured it. An older gate report measured an earlier build and
   is not read.
2. **Decides fresh or continued.** If the previous triage-report still has `pending` groups
   and no gate has measured anything since, the run is inside a chain of specialist visits on
   one build, and the next pending group is routed. Otherwise the step normalizes the current
   build's failing reports and the G4 decision that sent the build back. It drops findings
   routed `assets` by a report that the assets step has run after, because that work is done.
3. **Groups by owner, in order.** `design` comes first and alone: the other groups are
   `deferred`, and the gates measure the rebuilt game again. Then `assets` (one group), then
   each develop specialist. A group whose label the step's `on:` does not map is `held`, with
   the reason. Example: store copy before the listing exists, which listing-validation routes
   to store-listing after G4.
4. **Routes one group.** The step returns SUCCESS with the group's label: `design`, `assets`,
   or the specialist's role id. The workflow maps each specialist label to `develop`. With
   nothing failed (the first build) the result is a plain SUCCESS. If every finding is held,
   the result is BLOCKED and a person decides.

### Several specialists, one build: sequential visits

One build can have findings for several owners. Example: a visual-qa failure with a dark
scene (the environment artist's) and default buttons (UI's). The owners visit **one at a
time, in order, on the same build, before the gates measure it again**. The specialist visit
returns `next-specialist`, and the next triage continues the queue. The reasons:

- Each visit has one brief, one writable scope and one commit. The scope is enforced per
  commit, so it means something only if a commit is one specialist's.
- Each specialist's visit has its own budget. A specialist that never resolves its findings
  stops the run with its name. It does not spend the other specialists' passes.
- The gates do not run between links of the chain. One measurement covers every
  specialist's work, which is the cost a single generalist visit had. Re-measuring after each
  specialist would multiply the gate runs, the visual-qa judge among them.

Review reads the whole chain: the next specialist's brief carries the first one's
`review_baseline`.

### Loop limits

| Bound | Where | Limit |
|---|---|---|
| How often each gate may send the build back | `triage.max_visits_by_route` | `playability.fail`, `production-quality.develop`, `visual-qa.develop`, `content-sufficiency.develop`, `review.request-changes`, `sdk-review.request-changes`, `verify.fail`, `iterate`: 2 each; `content-sufficiency.design-gap`: 1 |
| How often each specialist may be visited | `develop.max_visits_by_route` | `triage.gameplay`: 16 (it takes review's, sdk-review's and verify's blockers, G4 iterations without typed findings and anything unowned: every sending route's budget, so it is never cut before a gate's own); every other specialist: 4 |
| Asset remakes triage routes | `assets.max_visits_by_route` | `triage.assets`: 2 |
| Scope increases | `design.max_visits_by_route` | `triage.design`: 2 (content-sufficiency's design gaps, and a person's or the scorecard's) |

A specialist chain has no budget on triage. Each link enters develop through a specialist's
limit, and that limit ends the chain. When a limit is reached, the run is BLOCKED with
`blocked_reason` naming it (for example `limit_key: triage.environment-artist`, `from: triage`,
`route: environment-artist`). A person's resume grants that route alone one more pass.

## The specialist visit

See [development-module.md](development-module.md#specialist-visits). In short:

- **The brief.** It opens with *This visit: <label>*, the role's focus, and only the
  selected findings, each with its measurement, bar, evidence, change and acceptance. It
  also lists the role's playbooks and the specialists still to come. The raw gate reports
  are not shown.
- **The scope.** The writable scope is `factory.develop.writable_paths` cut to the role's
  `writes`, and never widened.
- **The record.** The prototype-report's `specialist` block holds the role, the findings,
  the visits still pending, the session count and the session cost.

The developer host does not change. The develop step's `command` developer runs one agent
session per attempt through `wgflib.procs`, with the specialist's brief. Nothing outside the
Factory is involved, and core names no provider or tool.

### The finding lifecycle

Every finding has a status, and the run keeps a ledger of them:

```
detected -> classified -> assigned -> implemented -> verified -> closed
```

Each triage-report carries the whole ledger forward (`lifecycle`,
`quality-finding.schema.json#/$defs/record`), so the newest triage-report is the run's
ledger and a finding survives every visit (`wgf_triage/lifecycle.py`). Each record holds:

- severity, the category (the dimension), the owner and the route;
- the summary, the source, and the evidence refs;
- the affected build: the commit, and the bundle digest when verification built that
  commit;
- the expected threshold and the observed value;
- every transition (`history`) and the verification evidence.

| Status | Set when |
|---|---|
| detected | a producer reports the finding |
| classified | its dimension, owner and route are decided from the routing data |
| assigned | a triage routes its group to the owner |
| implemented | the owner's develop visit lists it (the prototype-report's `specialist` block): the fix's commit and run-local seq |
| verified | the producer that raised it has a report newer than the fix, that report no longer fails its id, and **nothing that passed before fails on a build at or after the fix**. A regression keeps the finding `implemented`, with `verification.verdict: regressed` and the regressions named. |
| closed | verified, and every gate the run holds a report of has measured a build at or after the fix |

A finding never closes on the specialist's word. Only the raising gate's re-measurement
moves it past `implemented`. If the raising gate still fails it, the finding is reopened:
`classified`, with `verification.verdict: still-failing`. A verified or closed finding that a
gate fails again is reopened the same way. A person's G4 finding is re-measured by the next
G4 decision: it is verified unless that decision is `iterate` and names it again.

### What the specialist brief carries

Besides its own findings, every specialist brief carries one copy of each of these
(`specialist.context` in `brief.json`, rendered under *What every specialist works within*):

- **Game brief.** The idea the run started with (game-design `brief`).
- **Design contract.** The game-design artifact and hash it builds against, rendered to
  `docs/GDD.md`, with its build_spec in the brief.
- **Quality budget.** The strategy's tier and content budget
  (`concept.content_model.budget`).
- **Quality floor.** `core/reference/quality-benchmark.yaml` at the run's tier, with its
  presentation bars.
- **Acceptance.** Each finding's acceptance, and the tasks' acceptance.
- **Other open findings.** Findings that belong to someone else: listed so the specialist
  does not work on them or make them worse.
- **Regression constraints.** Every gate that passed the current build must still pass the
  next one, and every verified or closed finding must stay fixed.

### What was resolved, per visit

`triage-report.ledger` has one entry per specialist develop visit. The entry is taken from
the prototype-report's `specialist` block the first time a triage sees that visit. For each
finding, the newest report of the producer that raised it, produced after the visit's build,
decides the status:

- **resolved**: that report no longer fails the finding's id.
- **unresolved**: that report fails the same id again.
- **unmeasured**: no report of that producer is newer than the visit yet.

A person's finding is measured at the next G4: it is resolved unless that decision is
`iterate` and names the same finding again. A chain that passes every gate reaches G4
without another triage. Its last visit's record is then in the prototype-report that G4
reads.

## G4 iterate with typed findings

```bash
cat > findings.json <<'EOF'
[{"dimension": "environment-3d", "severity": "blocker",
  "summary": "the courses float in an empty black void",
  "task": {"change": "dress each course: sky, distant islands, props on the path",
           "acceptance": ["visual-qa scores environment 4 or more"]}},
 {"dimension": "content", "severity": "blocker", "route": "design",
  "summary": "one world of six corridors",
  "task": {"change": "three worlds of four courses, each with a new obstacle kind",
           "acceptance": ["12 units in public/content/units.json"],
           "design_field": "build_spec.content"}}]
EOF
bin/wgf decide <run-id> iterate --note "not a release yet" --findings findings.json
```

`wgf decide` validates the file against `quality-finding.schema.json#/$defs/request`. It
stores the file in the run directory under its content hash and names it in the decision's
note (`findings: findings/<hash>.json sha256:<digest>`). The decision-record carries the note
as its `rationale`. The triage step reads the file back and refuses a file that no longer
hashes to the note's digest: the run stops BLOCKED. A person may ask for `design` (a scope or
content increase, I-06) or `assets` (an asset made again). For any other finding, the owner's
route applies. Without `--findings`, the note is one generalist finding, as the iterate note
was before.

### The design route

Triage's `design` re-enters the design step with the triage-report. The selected findings
become blocking design gaps at their `task.design_field`, or at `build_spec.content` for
content and level design, and the agent author repairs them like a developer's gaps
(`wgf_design.step.triage_gaps`). As with `design-gap`, tech-plan, G3 and the greybox run
again on the repaired design.

## What is not done

- **Store copy.** Copy findings are normalized and owned by `copywriter` (route `listing`).
  The listing loop (`listing-validation` → `store-listing`) is unchanged, and the
  store-listing step does not yet brief its writer as the copywriter with the findings.
  WS-9 makes the copywriter the default writer.
- **The scorecard.** WS-7's `quality-scorecard` is accepted by `normalize` as a producer.
  Wiring it in means adding it to triage's inputs in the workflow and to
  `wgf_triage.step.GATE_REPORTS`.
- **Greybox.** The greybox loop (`greybox-playability` → `greybox`) is not triaged. The
  greybox is the loop's skeleton, before any specialist work applies.
- **Live evidence.** No live run has exercised the routing. The evidence is the unit and
  mock-workflow tests (`scripts/tests/test_triage.py`).

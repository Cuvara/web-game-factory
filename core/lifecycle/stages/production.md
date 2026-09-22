# Production

**Machine** title · **State** `production` · **Kind** AI-assisted · **Role** gameplay
**Contributors** ui, asset, sdk, game-designer, release
**Inputs** `tech-plan`, `game-design`, `prototype-report` · **Outputs** `asset-manifest` (updated)

Implement the approved plan to content-complete.

## Plan-driven means plan-driven

Agents may discover implementation detail freely — that is the work. What they may not do
casually is redefine:

- product scope
- monetization
- platform strategy
- core gameplay
- architecture

Those change through an explicit process, because without one the development plan stops
describing what is being built within about a day, and then nothing approved at G3 means
anything.

### Change process

```
Change request  →  Impact analysis  →  Approval  →  Development plan update
```

- **Change request** — what, why, and which artifact it contradicts.
- **Impact analysis** — effect on timebox, asset cost, platform compliance, and the
  consistency rules. A scope change that breaks a design consistency rule is a design
  change and goes back to `design`.
- **Approval** — recorded as a `decision-record`. Small, in-tier changes can be approved by
  the owning role; anything touching the five items above needs the portfolio owner.
- **Update** — amend `tech-plan.dev_plan` and, where relevant, `game-design`. The plan is
  the artifact; an undocumented change is a drift, not a decision.

## Agent QA vs independent QA

Inside production the loop is: implement → test → fix → repeat. That is **agent QA**, and
it is necessary but not sufficient.

> An agent saying **"ready"** is not the same event as QA saying **"approved."**

Independent QA runs in the release sub-machine against a built candidate, by a different
role, with the authority to fail a build its author believes is finished. Collapsing the
two removes the only external check on agent output.

## CI is continuous here

`ci_green` is a guard on several transitions, not a stage. Lint, typecheck, unit and
integration tests run on every push throughout production. The heavier verify suite runs
once, at the release candidate gate.

## Exit

`content_complete` (content manifest complete **and** asset manifest complete) and
`ci_green` → `releasing`.

`CONTENT COMPLETE` is a guard rather than a state deliberately: it is a property of two
manifests, and a state that only ever means "those two booleans are true" adds a transition
and no information.

Overrunning the timebox beyond tolerance routes to `abandoned` (human decision). A title
that has consumed twice its budget is telling you something the estimate did not.

## Failure modes

- **Scope creep dressed as polish.** The change process exists to make additions visible.
- **Deferring platform work.** SDK, localization and store metadata are production work,
  not release work. Leaving them to the end produces a release blocked on tasks nobody
  scheduled.
- **Letting the plan go stale.** If the tasks no longer match the code, the plan has
  stopped being a contract and G5 has nothing to check against.

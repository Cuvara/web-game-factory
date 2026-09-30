# Role: Architect

**Kind** owner · **Owns** `title:tech-plan`
**Produces** `tech-plan` · **Presents at** G3

Selects the engine, defines the architecture and budgets, and writes the development plan.

## Charter

Turn an approved design into something a coding agent can execute without inventing scope.

## Engine selection

PixiJS for 2D, Three.js for 3D. Nothing else — the template supports these two and no
others should be introduced.

The rationale must be about cost and constraint: load budget, asset pipeline, mobile
performance. "3D looks better" is not a rationale. Three.js costs bundle size, a
compression pipeline (Draco/Meshopt, KTX2) and mobile headroom; it needs a reason.

Engine selection lives here because `engine.type` is a repository-creation parameter.
Decide the engine, then create the repo.

## The development plan is the deliverable

A coding agent handed only a GDD will invent scope — it has no choice, because a GDD does
not say what to build first or what "done" means.

Every task needs an id, dependencies, **acceptance criteria**, and **tests**. The schema
requires the first and third. A task without acceptance criteria cannot be verified and
will be reported complete when it is not.

Milestones need exit criteria and day estimates that sum within the timebox — genuinely,
not by fitting. Estimates that land exactly on the budget were fitted.

## Also yours

- **Performance budgets** per device class, set before measuring. Budgets written after the
  fact are not budgets. `max_bundle_mb` must respect the tightest required platform profile.
- **The ownership split** — generic (template) vs game-specific vs platform-specific vs
  agent vs CI. This is what stops the most common scaffolding mistake: reimplementing in the
  game what the template already provides.
- **`repo_params`**, including the full `game.config.yaml` content, with platforms pinned as
  `<platform-id>@<profile-version>`.

## Failure modes

- **A plan that restates the GDD.** If a task says "implement the core loop", no plan was
  written.
- **Architecture for a game that does not exist yet.** Build for the scope in
  `game-design.scope.tiers`, not for the `future` tier.
- **Ignoring the template's abstractions.** Game code calls the platform abstraction; it
  never calls a portal SDK directly.

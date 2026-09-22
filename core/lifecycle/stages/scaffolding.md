# Scaffolding

**Machine** title · **State** `scaffolding` · **Kind** automatic · **Role** release
**Inputs** `tech-plan` · **Outputs** none

Create the game repository from the template. Transient and mechanical; it is a state
rather than a transition action only because it can fail.

## The rule

**The new game repository MUST originate from `web-game-template`.** Never create a blank
repository and reconstruct the template by hand. The template carries the platform
abstraction, analytics abstraction, build infrastructure, test layout and six CI/CD
pipelines; a hand-rebuilt approximation of it silently loses whichever of those the
rebuilder forgot.

```
web-game-factory  →  tech-plan.repo_params  →  gh CLI  →  web-game-template  →  new game repo
```

## Procedure

1. Create the repository from the template using the `gh` CLI, at the ref named in
   `repo_params.template_ref`.
2. Write `game.config.yaml` verbatim from `repo_params.game_config`. Platforms are written
   as pinned entries — `{id, profile, role}` — not bare strings, so the build stays
   reproducible against the compliance rules in force.
3. Render `game-design` to `docs/GDD.md` and `tech-plan` to `docs/tech-plan.md` in the game
   repo, so the coding agent has them locally.
4. Confirm CI is green on the untouched scaffold. A red pipeline before any game code
   exists is a template problem, and finding it now costs nothing.

## Exit

- `repo_created` and `ci_green` → `prototype`
- failure → back to `tech-plan`

## Note on authorization

Creating repositories and pushing code are outward-facing actions. During architecture or
scaffolding work, do not create real external repositories unless explicitly instructed.
This procedure describes what happens when a title is genuinely being produced.

## Failure modes

- **Drifting from the template.** If the template lacks something the plan needs, fix the
  template rather than patching the game — otherwise every future title inherits the gap.
- **Writing `game.config.yaml` by hand.** It comes from `repo_params`, which was reviewed
  at G3. Hand-editing it detaches the running game from the approved plan.

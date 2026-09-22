# /wgf-publish (Web Game Factory)

**Transition** `release: approved -> validating -> submitting -> live`
**Role** `release`
**Gate** `G6` — see `core/lifecycle/gates.yaml` for its required artifacts, predicates and approvers.

Authorize publication, validate per platform, and prepare submissions.

## Procedure

1. Read `core/lifecycle/` for the machine that owns this transition, and the
   `procedure` file named on the source state.
2. Read the `x-wgf` block of every artifact schema this transition produces or consumes.
3. Check the transition's guards before acting. A guard that cannot be evaluated is a
   blocker to report, not one to assume.
4. Follow `codex-web-game-plugin/agents/release.md`.
5. Record the outcome: artifacts at their `repo_path`, and the title's `state.json`.

Commands map to transitions rather than to stages, so this file stays correct as long as
the machine does.

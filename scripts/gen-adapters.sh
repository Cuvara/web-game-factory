#!/usr/bin/env bash
# Generates the Claude and Codex adapter surfaces from core/bindings/adapter-binding.yaml.
#
# Adapter files are thin pointers into core: frontmatter (Claude) or a header (Codex),
# a must-read list, and a short provider-specific execution-notes block. Because they are
# formulaic by design, generating them is what keeps the two adapters genuinely identical
# in substance and different only in host mechanics.
#
# Four kinds of surface, one table each below: agents (roles), transition commands
# (commands/wgf-*.md, one per lifecycle transition), workflow entry points (commands/<id>.md,
# one per `workflows:` entry - a run of a core workflow through bin/wgf, never a transition)
# and skills.
#
# Re-run after editing the binding manifest. It overwrites agents/, commands/ and skills/
# in both plugins, and rebuilds the Factory runtime the Claude plugin ships
# (claude-web-game-plugin/runtime/, scripts/build-plugin-runtime.py); it does not touch
# READMEs or CONFORMANCE.md. It never deletes a surface file: a surface removed from a table
# must be removed from disk by hand.
#
# Claude Code installs a plugin by copying its directory and nothing else, so the Claude
# surfaces never name a Factory path relative to the working directory - which is the
# project, not the Factory. Every core/, docs/, scripts/wgf.py and bin/wgf they name is
# rewritten (claude_paths, below) to the runtime inside the plugin, through the
# ${CLAUDE_PLUGIN_ROOT} Claude Code substitutes in command, agent and skill content. The
# Codex adapter has no such root; it still runs from the factory repository root.
# scripts/tests/test_adapter_binding.py keeps the binding, these tables, the generated files
# and both CONFORMANCE.md files naming the same surfaces.
set -euo pipefail
cd "$(dirname "$0")/.."

C=claude-web-game-plugin
X=codex-web-game-plugin
mkdir -p $C/agents $C/commands $C/skills $X/agents $X/commands $X/skills

# The Factory runtime as the Claude surfaces name it, and its engine. Literal text: Claude
# Code substitutes ${CLAUDE_PLUGIN_ROOT} when it loads the surface.
CR='${CLAUDE_PLUGIN_ROOT}/runtime'
CW="python3 \"$CR/scripts/wgf.py\""

# claude_paths < text > text: every Factory path a Claude surface names, inside the plugin.
# A path already under $CR is left alone: the character before it is a `/`.
claude_paths() {
  sed -E \
    -e 's#(^|[^A-Za-z0-9_./-])core/#\1'"$CR"'/core/#g' \
    -e 's#(^|[^A-Za-z0-9_./-])docs/#\1'"$CR"'/docs/#g' \
    -e 's#(^|[^A-Za-z0-9_./-])scripts/wgf\.py#\1'"$CR"'/scripts/wgf.py#g' \
    -e 's#(^|[^A-Za-z0-9_./-])bin/wgf([^A-Za-z0-9_.-]|$)#\1'"$CW"'\2#g'
}

# ---------------------------------------------------------------- agents
# id|owns|description|must_read (semicolon-separated)|notes
agents=(
"research|portfolio:market-scan, portfolio:discovered|Gathers web game market signal from portal sources and normalizes it into tiered claims and candidate opportunities. Use when starting a market scan, researching a genre or platform, or refreshing stale evidence on the backlog.|core/roles/research.md;core/lifecycle/stages/market-scan.md;core/artifacts/shared/claim.schema.json;core/artifacts/opportunity.schema.json;core/artifacts/research-report.schema.json;core/reference/dimensions.yaml;core/reference/research-vocabulary.yaml;core/reference/research-analysis.yaml;core/artifacts/shared/game-record.schema.json;core/artifacts/shared/research-opportunity.schema.json;core/craft/competitive-teardown.md;core/craft/research-evidence.md|Write claims to workspace/claims/ and opportunities to workspace/opportunities/. Write each teardown as a game record under workspace/research/games/, coded on the research vocabulary; never record a gameplay observation that was not made. Observation and interpretation are always separate claims. Never edit a claim; supersede it. External tools (browser, generation, docs lookup, analytics) only as core/craft/tool-capabilities.md allows: localhost-only browsing of builds, provenance and licence on anything generated, human approval before any paid job."
"analysis|portfolio:scored, shortlisted, approved, title:concept|Scores opportunities against a versioned scoring model, tracks evidence coverage, and presents the ranked shortlist at gate G1. Use when evaluating or re-scoring opportunities, or preparing an opportunity selection decision.|core/roles/analysis.md;core/lifecycle/stages/score-opportunity.md;core/lifecycle/stages/opportunity-selection.md;core/artifacts/evaluation.schema.json;core/artifacts/shared/scoring-model.schema.json;core/reference/scoring/portfolio-default.v1.yaml|Append evaluations, never overwrite. Record the scoring model by id, version and file hash. Empty evidence_refs forces tier=hypothesis; do not work around it. External tools (browser, generation, docs lookup, analytics) only as core/craft/tool-capabilities.md allows: localhost-only browsing of builds, provenance and licence on anything generated, human approval before any paid job."
"game-designer|title:strategy, title:design|Authors the title strategy including its kill criteria, then designs scope, session, retention and monetization together as one artifact. Use when drafting a strategy, producing a game design, or presenting prototype evidence at gate G4.|core/roles/game-designer.md;core/lifecycle/stages/strategy.md;core/lifecycle/stages/design.md;core/artifacts/title-strategy.schema.json;core/artifacts/game-design.schema.json;core/reference/design-consistency-rules.yaml;core/templates/gdd.md;core/craft/core-loop-and-difficulty.md;core/craft/onboarding-and-portal-ux.md;core/craft/art-direction.md;core/craft/production-art-and-ui.md;core/craft/production-art-2d.md;core/craft/production-art-3d.md;core/craft/game-ui-kit.md;core/craft/juice.md;core/craft/retention-and-progression.md;core/craft/content-and-level-design.md;core/reference/genre-models.yaml;core/reference/design-depth.yaml;core/craft/feature-evaluation.md;core/reference/feature-catalogue.yaml;core/artifacts/shared/research-opportunity.schema.json|Kill criteria are written at strategy, before any code exists. out_of_scope must be non-empty. When the consistency check fails, cut scope rather than relaxing a rule. External tools (browser, generation, docs lookup, analytics) only as core/craft/tool-capabilities.md allows: localhost-only browsing of builds, provenance and licence on anything generated, human approval before any paid job."
"architect|title:tech-plan; reviews development commits in title:prototype|Selects the engine, defines architecture and performance budgets, and writes the development plan a coding agent works from; then reviews each development commit read-only and returns a review-report. Use when turning an approved design into a technical plan, preparing gate G3, or reviewing a prototype commit.|core/roles/architect.md;core/lifecycle/stages/tech-plan.md;core/artifacts/tech-plan.schema.json;core/templates/tech-plan.md;core/lifecycle/stages/prototype.md;core/artifacts/review-report.schema.json;core/craft/web-performance.md;core/craft/gameplay-review.md|PixiJS for 2D, Three.js for 3D, nothing else. Every task needs acceptance criteria and tests. repo_params carries the full game.config.yaml content with platforms pinned as id@profile-version. As a reviewer you are read-only: never edit, stage or commit in the game repository. The Factory fingerprints the checkout, and a review that changed anything is undone and discarded. The verdict shape is the one in the review brief the Factory writes. External tools (browser, generation, docs lookup, analytics) only as core/craft/tool-capabilities.md allows: localhost-only browsing of builds, provenance and licence on anything generated, human approval before any paid job."
"qa|release:qa|Independently verifies a built release candidate and produces the QA report read at gate G5. Use when a release is in QA, or when prototype evidence needs its numbers checked at G4.|core/roles/qa.md;core/lifecycle/stages/qa.md;core/artifacts/verification-report.schema.json;core/artifacts/qa-report.schema.json;core/artifacts/shared/gameplay-session.schema.json;core/templates/qa-report.md;core/craft/playtesting.md;core/craft/web-performance.md;core/craft/accessibility.md|You verify work you did not author, and you may fail a build its author believes is finished. Every defect needs reproduction steps. verdict is derived from blocking defects and performance budgets. When a Playwright browser tool is available, play the built bundle (a preview server, never the dev server) through each gameplay aspect and record the session to build/verification/gameplay-session.json in the game repository, naming the commit under test, before running \`bin/wgf verify\`; without one, verification falls back to the repository's Playwright suites. Never report a portal's approval. External tools (browser, generation, docs lookup, analytics) only as core/craft/tool-capabilities.md allows: localhost-only browsing of builds, provenance and licence on anything generated, human approval before any paid job."
"release|title:scaffolding, release:draft/rc/validating/submitting|Creates game repositories from the template, assembles and freezes releases, runs platform validation, and prepares portal submissions. Also owns compliance and localization. Use for scaffolding, release assembly, validation, or publishing.|core/roles/release.md;core/lifecycle/stages/scaffolding.md;core/lifecycle/stages/release-draft.md;core/lifecycle/stages/release-candidate.md;core/lifecycle/stages/platform-validation.md;core/lifecycle/stages/publish.md;core/lifecycle/stages/store-listing.md;core/artifacts/release-manifest.schema.json;core/artifacts/platform-publication.schema.json;core/artifacts/review-report.schema.json;core/artifacts/store-listing.schema.json;core/artifacts/listing-validation-report.schema.json;core/reference/store-listing.yaml;core/templates/release-report.md;core/craft/onboarding-and-portal-ux.md;core/craft/store-listing.md|Game repositories originate from web-game-template, never from scratch. A frozen manifest is immutable. Validate against the pinned profile version. Secrets never enter source. A portal rejection must produce a compliance finding and a profile version bump. The store listing is captured from the verified build by the store-listing step, never written by hand: a platform requirement nobody has read from the portal stays null in its profile and is reported UNKNOWN, and store copy may claim nothing the shipped game does not have. External tools (browser, generation, docs lookup, analytics) only as core/craft/tool-capabilities.md allows: localhost-only browsing of builds, provenance and licence on anything generated, human approval before any paid job."
"liveops|title:live|Interprets post-launch analytics, runs scheduled performance reviews, and decides iterate, scale, hold or sunset. Use for any post-launch analysis, experiment design, or campaign proposal at gate G7.|core/roles/liveops.md;core/lifecycle/stages/live.md;core/lifecycle/stages/performance-review.md;core/lifecycle/stages/campaign.md;core/artifacts/performance-review.schema.json;core/craft/retention-and-progression.md|Keep metrics, findings, hypotheses and experiments in their separate fields. Report per platform with sample size, never averaged. A projection is a hypothesis with a number attached; label it. Campaigns need a human-authorized ceiling. External tools (browser, generation, docs lookup, analytics) only as core/craft/tool-capabilities.md allows: localhost-only browsing of builds, provenance and licence on anything generated, human approval before any paid job."
"gameplay|works in title:prototype, title:production|Implements core mechanics, game loop, systems and progression from the development plan, and writes the prototype report. Use when building prototype or production tasks.|core/roles/implementers.md;core/lifecycle/stages/prototype.md;core/lifecycle/stages/production.md;core/artifacts/prototype-report.schema.json;core/artifacts/review-report.schema.json;core/artifacts/game-design.schema.json;core/craft/game-feel.md;core/craft/core-loop-and-difficulty.md;core/craft/production-art-and-ui.md;core/craft/production-art-2d.md;core/craft/production-art-3d.md;core/craft/juice.md;core/craft/production-wiring.md;core/craft/retention-and-progression.md;core/craft/content-and-level-design.md;core/reference/genre-models.yaml;core/reference/design-depth.yaml;core/craft/game-audio.md;core/roles/specialists.md;core/reference/specialist-routing.yaml;core/artifacts/shared/quality-finding.schema.json|Work the plan's tasks in dependency order and satisfy both acceptance criteria and tests. When the brief opens with blockers from code review or verification, fix those first. When it opens with *This visit* as a specialist, you are that discipline: fix only the findings it lists, read its playbooks, and write only its writable scope. Scope, monetization, platform strategy, core gameplay and architecture change only through the production change process. External tools (browser, generation, docs lookup, analytics) only as core/craft/tool-capabilities.md allows: localhost-only browsing of builds, provenance and licence on anything generated, human approval before any paid job."
"ui|works in title:prototype, title:production|Implements interface, HUD, menus, onboarding flow and platform UI constraints. Use when building or revising any player-facing interface.|core/roles/implementers.md;core/lifecycle/stages/production.md;core/lifecycle/stages/prototype.md;core/artifacts/game-design.schema.json;core/craft/onboarding-and-portal-ux.md;core/craft/ui-hud-mobile.md;core/craft/accessibility.md;core/craft/game-feel.md;core/craft/production-art-and-ui.md;core/craft/game-ui-kit.md;core/craft/juice.md;core/craft/production-wiring.md;core/craft/game-audio.md|time_to_first_play_s and time_to_first_reward_s are design targets, not aspirations. Portal traffic has no install cost anchoring players through a slow start. External tools (browser, generation, docs lookup, analytics) only as core/craft/tool-capabilities.md allows: localhost-only browsing of builds, provenance and licence on anything generated, human approval before any paid job."
"asset|works in title:design through production|Authors the asset manifest with sources and cost estimates, then produces or sources assets and tracks line-item status. Use when planning asset cost during design or producing assets during development.|core/roles/implementers.md;core/artifacts/asset-manifest.schema.json;core/reference/asset-policy.yaml;core/craft/art-direction.md;core/craft/game-audio.md;core/craft/2d-assets.md;core/craft/production-art-and-ui.md;core/craft/production-art-2d.md;core/craft/production-art-3d.md;core/craft/game-ui-kit.md;core/craft/production-wiring.md|Contribute during design: asset cost is an input to the scope decision. Prefer library and procedural sources. No purchased or library item is integrated without a recorded license. External tools (browser, generation, docs lookup, analytics) only as core/craft/tool-capabilities.md allows: localhost-only browsing of builds, provenance and licence on anything generated, human approval before any paid job."
"sdk|works in title:prototype, production, release:validating|Integrates platform SDKs, ads, analytics and cloud save through the template's platform abstraction. Use when wiring any portal capability or preparing platform validation.|core/roles/implementers.md;core/reference/platforms/;core/artifacts/shared/platform-profile.schema.json;core/craft/onboarding-and-portal-ux.md|Game code never calls a portal SDK directly; it calls the abstraction. Integrate during prototype, not production, so monetization is proven in context. External tools (browser, generation, docs lookup, analytics) only as core/craft/tool-capabilities.md allows: localhost-only browsing of builds, provenance and licence on anything generated, human approval before any paid job."
)

for row in "${agents[@]}"; do
  IFS='|' read -r id owns desc reads notes <<< "$row"
  reads_md=""; n=1
  IFS=';' read -ra arr <<< "$reads"
  for p in "${arr[@]}"; do reads_md+="$n. \`$p\`"$'\n'; n=$((n+1)); done

  claude_paths > "$C/agents/$id.md" <<EOF
---
name: $id
description: $desc
---

You are the **$id** role as defined by Web Game Factory core.

**Owns:** $owns

## Read before acting, in order

$reads_md
Core is authoritative. Where this file and core disagree, core wins — report the conflict
rather than resolving it yourself.

## Execution notes (Claude Code)

- Factory paths here are inside this plugin's own runtime, never the working directory.
  The working directory is the project: write artifacts to the \`repo_path\` given in each
  schema's \`x-wgf\` block, relative to it.
- $notes
- Do not advance the lifecycle. Emit your artifacts and stop — transitions are commands and
  gates are human decisions.
EOF

  cat > "$X/agents/$id.md" <<EOF
# Role: $id (Web Game Factory)

**Owns:** $owns

Invoked from \`AGENTS.md\` or by the matching \`/wgf-*\` prompt.

## Read before acting, in order

$reads_md
Core is authoritative. Where this file and core disagree, core wins — report the conflict
rather than resolving it yourself.

## Execution notes (Codex)

- Run from the factory repository root so relative core paths resolve.
- Write artifacts to the \`repo_path\` given in each schema's \`x-wgf\` block.
- Emit a plan before writing files; apply one patch per artifact.
- $notes
- Do not advance the lifecycle. Emit your artifacts and stop — transitions are commands and
  gates are human decisions.
EOF
done

# -------------------------------------------------------------- commands
# id|role|triggers|gate|summary
commands=(
"scan|research|portfolio:market-scan|-|Run a bounded market scan; emit claims and candidate opportunities."
"score|analysis|portfolio: discovered -> scored -> shortlisted|-|Score opportunities under a versioned model; compute evidence coverage and vetoes."
"select|analysis|portfolio: shortlisted -> approved -> promoted|G1|Present the ranked shortlist and record the selection decision."
"strategy|game-designer|title: concept -> strategy -> design|G2|Draft the title strategy including kill criteria, then take it to approval."
"design|game-designer|title: design -> tech-plan|-|Produce the game design and asset manifest; run the consistency check."
"plan|architect|title: tech-plan -> scaffolding|G3|Select the engine, set budgets, write the development plan, take design+plan to approval."
"scaffold|release|title: scaffolding -> prototype|-|Create the game repository from web-game-template and write game.config.yaml."
"prototype|gameplay|title: prototype -> prototype-review|-|Build the prototype to a fun-testable standard, have each development commit reviewed (review-report), and write the prototype report."
"review|portfolio-owner|title: prototype-review -> production, prototype or abandoned|G4|The kill gate. Judge the prototype against the kill criteria set at strategy. (Not the code review of a commit; that runs inside /wgf-prototype.)"
"release|release|title: production -> releasing; release: draft -> qa -> rc -> approved|G5|Assemble, QA and freeze a release candidate, then take it to approval."
"publish|release|release: approved -> validating -> submitting -> live|G6|Authorize publication, validate per platform, and prepare submissions."
"live|liveops|title: live (scheduled review)|G7|Run a performance review and decide iterate, scale, hold or sunset."
"status|-|read-only|-|Report portfolio and title state from workspace/."
)

for row in "${commands[@]}"; do
  IFS='|' read -r id role triggers gate summary <<< "$row"
  gate_line=""
  [ "$gate" != "-" ] && gate_line="**Gate** \`$gate\` — see \`core/lifecycle/gates.yaml\` for its required artifacts, predicates and approvers."

  # portfolio-owner is a human role with no agent surface; status has no role at all.
  case "$role" in
    portfolio-owner)
      claude_step="Prepare the decision for the human approver per \`core/roles/portfolio-owner.md\`. Do not decide."
      codex_step="$claude_step"
      record_step="Record the human's decision as a \`decision-record\`, and update the title's \`state.json\`." ;;
    -)
      claude_step="Read the project's \`workspace/\` (in the working directory) and report. This command changes nothing."
      codex_step="$claude_step"
      record_step="Write nothing." ;;
    *)
      claude_step="Delegate the work to the \`$role\` agent."
      codex_step="Follow \`$X/agents/$role.md\`."
      record_step="Record the outcome: artifacts at their \`repo_path\`, and the title's \`state.json\`." ;;
  esac

  claude_paths > "$C/commands/wgf-$id.md" <<EOF
---
description: $summary
---

# /wgf-$id

**Transition** \`$triggers\`
**Role** \`$role\`
$gate_line

$summary

## Procedure

1. Read \`core/lifecycle/\` for the machine that owns this transition, and the
   \`procedure\` file named on the source state.
2. Read the \`x-wgf\` block of every artifact schema this transition produces or consumes.
3. Check the transition's guards before acting. A guard that cannot be evaluated is a
   blocker to report, not one to assume.
4. $claude_step
5. $record_step

Commands map to transitions rather than to stages, so this file stays correct as long as
the machine does.
EOF

  cat > "$X/commands/wgf-$id.md" <<EOF
# /wgf-$id (Web Game Factory)

**Transition** \`$triggers\`
**Role** \`$role\`
$gate_line

$summary

## Procedure

1. Read \`core/lifecycle/\` for the machine that owns this transition, and the
   \`procedure\` file named on the source state.
2. Read the \`x-wgf\` block of every artifact schema this transition produces or consumes.
3. Check the transition's guards before acting. A guard that cannot be evaluated is a
   blocker to report, not one to assume.
4. $codex_step
5. $record_step

Commands map to transitions rather than to stages, so this file stays correct as long as
the machine does.
EOF
done

# ------------------------------------------------------ workflow entry points
# id|runs|summary|craft (semicolon-separated: the binding entry's `craft`)|continues (the
# binding entry's `continues`: groups continued inside a run, `<surface> <group> <run-id>`)
#
# Not transitions. An entry point starts or resumes a run of one core workflow through the
# workflow engine (bin/wgf) and reports where it stands. It restates nothing the workflow
# file says - no step order, retry, loop, gate or resume logic - and it never answers a gate:
# every decision is a person's, typed by that person. Only the host mechanics differ between
# the two adapters; the procedure is one text, emitted by entry_body below.
workflows=(
"new-game|core/workflows/new-game.workflow.yaml|Run the Factory's new-game workflow end to end through the wgf engine; stop at every gate for a person.|core/craft/production-art-and-ui.md;core/craft/production-art-2d.md;core/craft/production-art-3d.md;core/craft/game-ui-kit.md;core/craft/juice.md;core/craft/production-wiring.md|publish"
)

# entry_body <id> <runs> <arguments> <background> <invoke> <preflight> <engine-note>
# <research> — the procedure both adapters share; <invoke> is how the host names this
# surface when the user types it again, <preflight> how it confirms it has the Factory
# runtime, <engine-note> how the engine is started where the shim cannot be, <research> how
# it hands a waiting research step's input to the research role.
entry_body() {
  local id=$1 runs=$2 arguments=$3 background=$4 invoke=$5 preflight=$6 engine_note=$7
  local research=$8
  cat <<EOF
**Workflow entry point** \`$runs\` — not a transition.
**Engine** \`bin/wgf\` (\`scripts/wgf.py\`), the Factory's only orchestrator.

This surface starts or resumes a run of the workflow above and reports it. The workflow file
is the single source of step order, retries, loops, gates, decisions and resume; nothing here
restates it, and nothing here decides for the engine or for a person.

Arguments: $arguments

## Read first

1. \`$runs\`
2. \`core/lifecycle/gates.yaml\`
3. \`docs/workflow-engine.md\`
4. the factory configuration \`bin/wgf where --json\` reports: \`config_layers\` (the shipped
   file, then the project's own, layered) and the resolved \`autonomy\`

## The production bar

The run's agents are pointed at these craft playbooks by their briefs and requests - what a
finished build looks like, plays like and is checked against. Read them to report a run's
output honestly; never to steer a step, which is the engine's:

$craft_md
## Arguments

Accept exactly these (the engine's own flags, \`bin/wgf $id --help\` and
\`bin/wgf resume --help\`), and nothing else:

- new run: \`--mock\`, \`--mock-plan <JSON|@FILE>\` (with \`--mock\` only),
  \`--hold-gates\`, \`--project <ID>\`, \`--from <STEP>\`, \`--store <DIR>\`, and at most
  one **game idea**: the quoted text that is not a flag or a flag's value, e.g.
  \`"3D goalkeeper game where the player saves penalty kicks"\`. The idea is the run's
  brief - research screens the catalog against it, strategy and design build from it - and
  \`--project <ID>\` is only the run's identity; never take one for the other. Pass the idea
  verbatim as one argument: never reword, summarise, translate, split or complete it, and
  never invent one. With no idea the run is a blank market scan: say so when you start it.
  An idea with \`--from\` a step after research is refused by the engine (exit 2).
- \`resume <run-id>\`, optionally with \`--from <STEP>\` and \`--store <DIR>\`: continues that
  run with the settings it started with - its idea among them, so an idea given with
  \`resume\` is refused
$continues_md
With \`--store <DIR>\`, pass the same \`--store <DIR>\` to every \`bin/wgf\` command for that
run (status, logs, resume).

Refuse, and run nothing, if the arguments contain anything else — in particular
\`--decision\`, \`--note\`, \`decide\`, \`--budget-sessions\`, \`--budget-cost\` or any other
\`--budget-*\` (a decision or a budget is a person's, typed by that person), \`--config\` or
\`--workflow\` (this surface runs this workflow under the configuration it reports),
\`--resume\`, \`--run\` or \`--force\` (use \`resume <run-id>\`$continues_use), \`--quiet\` or \`--json\`
(the surface sets the output), a second command, or more than one idea (two quoted texts;
ask the user to give the idea as one quoted string).

## Procedure

1. **Preflight.** $preflight For \`resume <run-id>\`$continues_pre, read
   \`bin/wgf status <run-id> --json\` first and stop unless \`workflow_id\` is \`$id\`.
   Then act on it without starting anything when there is nothing to continue:
   \`COMPLETED\` — report it (step 6)$continues_completed; \`RUNNING\` with liveness \`running\` — another
   process drives it, only report progress; \`WAITING\` at a gate whose \`pending.timeout\`
   is not \`eligible\` — report the gate (step 6) and stop. \`FAILED\` or \`BLOCKED\` —
   report it first as step 6 does, with why: \`blocked_reason\` and the logs of the step at
   \`cursor\`, its last agent message among them. Resuming re-runs that step, and a
   deterministic failure fails again: resume only when the user confirms, after that report,
   with step 3's warning for any agent session it starts; otherwise stop. Anything else (a
   stopped, cancelled or stale run, or one waiting for input) is resumed at step 4.
2. **Report the effective autonomy** — never change it. For a new run, from \`where\`'s
   \`autonomy\`, as configured: \`developer\`, \`reviewer\`, \`design_author\`,
   \`asset_author\`, \`model_author\`, \`visualqa_judge\`, \`auto_approve\` (and
   \`timeout_auto_approve\`), \`init_source\`, \`develop_budget\`. A run that already exists
   keeps what it started with: \`auto_approve\`, \`timeout_auto_approve\` and
   \`develop_budget\` are the run's \`params\` in \`bin/wgf status <run-id> --json\` (a key
   that is absent there is none - no gate approves itself, no develop budget), never
   \`where\`'s; the agents and \`init_source\` are read from the configuration when each step
   runs, so those are \`where\`'s. When the two differ, say so: a configuration changed after
   the run started does not change which of its gates approve themselves. With \`--mock\`
   every step is a placeholder, and a mock run approves the reversible gates itself unless
   \`--hold-gates\` is given; gates in \`auto_approve\` are approved either way - report the
   gates that were approved, never the list as if it had happened. An unattended run is the
   project's own choice (\`profiles\` lists the shipped overlays, e.g. \`autonomous\`); never
   install one.
3. **Outward effects.** For a new run without \`--mock\` (a mock run starts no session and
   creates nothing): with \`init_source\` \`github\`, warn that once G3 is passed the init
   step creates a GitHub repository (\`gh repo create\`); with a \`command\` developer,
   reviewer, asset or model author or visual-QA judge (or an \`agent\` design author), say
   that agent sessions will run unattended and cost money, within \`develop_budget\` when
   one is set (the budget bounds the developer; each other agent has its own per-call cap). Either way, start that run only after the user
   confirms. A \`--mock\` run, or a run with neither, starts without asking.$continues_effects
4. **Start** $background

   - new run: \`bin/wgf $id <flags> --json\`, or with an idea
     \`bin/wgf $id <flags> --json -- '<idea>'\`: the idea last, after \`--\`, as one
     single-quoted shell word (each \`'\` inside it written as \`'\\''\`), so the shell
     neither splits nor expands it and a leading \`-\` is not read as a flag. Tell the user
     the idea as the engine recorded it: \`params.idea\` in \`WORKFLOW_STARTED\`, whitespace
     runs collapsed and nothing else changed - or that there is none.
   - resume: \`bin/wgf resume <run-id> [--from <STEP>] [--store <DIR>] --json\`
$continues_start
   $engine_note
   Read \`run_id\` from the first event, \`WORKFLOW_STARTED\` (on resume, \`WORKFLOW_RESUMED\`),
   and tell the user.
5. **Progress.** Summarise \`STEP_STARTED\`, \`STEP_COMPLETED\` and \`STEP_FAILED\` events as they
   arrive. For detail: \`bin/wgf status <run-id>\` or \`bin/wgf status <run-id> --json\`.
   Retries, loops and resume belong to the engine: report them, never re-run a step, edit
   \`.factory/\`, or edit an artifact to move the run along.
6. **When the process exits**, read \`bin/wgf status <run-id> --json\` and act on the run's
   status (the process's exit code is the same contract: 0, 1, 2, 3):
   - **COMPLETED** (exit 0): report the run id, the artifacts it produced and the
     release-manifest draft. If \`ended_by\` is set — \`Ended: kill at G4\` — report the kill
     as the end of the title, never as a release.
   - **FAILED, BLOCKED or CANCELLED** (exit 1): show \`status\`, \`cursor\`, \`blocked_reason\`
     and \`bin/wgf logs <run-id> --step <cursor>\`. A release refused as \`unreviewed\` is
     the configured reviewer (\`factory.review.reviewer.kind: none\`) doing its job: report
     it; do not configure a reviewer or weaken the release. Suggest
     \`$invoke resume <run-id>\` or \`bin/wgf resume <run-id> --from <STEP>\`; fix nothing.
   - **Usage error** (exit 2, no run started): show stderr.
   - **WAITING or PAUSED** (exit 3): show \`pending\` — step, gate, choices, evidence — and
     \`blocked_reason\` if any, then stop. See the rule below. \`pending: null\` means the
     run waits for input, not a decision: report \`cursor\` and \`message\`.
   - **WAITING for input at \`research\`** (\`pending: null\`, cursor \`research\`): the input
     is the research role's, not a person's decision. $research per
     \`core/craft/research-evidence.md\`: with *no external evidence*, it captures snapshots
     from pages it actually fetches into the project's \`workspace/research/snapshots/\`;
     when *the brief matches no concept research can carry*, it also writes the brief's
     concept to \`workspace/research/concepts.yaml\`. Then resume the run (step 4) and
     continue. Evidence is fetched, never written: if nothing relevant can be fetched, report
     that and stop. Never edit \`.factory/\` or an artifact, and never relax a setting.
7. **Result.** Run id, final status, artifacts, and what comes next. \`bin/wgf $id\` ends
   at a drafted release (a \`--mock\` run stops earlier, at G4).${continues_next//@INVOKE@/$invoke}

## The gate rule

Never run \`bin/wgf decide\`, \`wgf resume ... --decision\`, or anything else that answers
a checkpoint — for any gate, and for the develop handoff. Commands run from this session are
recorded as a person's decision, so answering one would forge a human decision. Tell the user
how to decide, and stop. A decision is the engine's resume: typed by the user, it records the
decision and drives the run on, in the user's own shell, to its next stop — and a real run's
next stop can be hours away. \`$invoke resume <run-id>\` afterwards reports where it
stopped, and continues it if that shell was interrupted.

- at a gate: one complete line per choice in \`pending.choices\`, the run id and the choice
  filled in - never \`<run-id>\`, \`<choice>\` or \`a|b\`, which the shell reads as
  redirections and pipes - and a note for the user to replace with their own reason, which
  is the decision record's only reason. At G4 of run \`new-game-20261003-085640-5dc4c9\`:

  - \`! bin/wgf decide new-game-20261003-085640-5dc4c9 pass --note "replace: why it passes"\`
  - \`! bin/wgf decide new-game-20261003-085640-5dc4c9 iterate --note "replace: what to change"\`
  - \`! bin/wgf decide new-game-20261003-085640-5dc4c9 kill --note "replace: which criterion"\`

  Say that the note must be replaced before the line is run, then \`$invoke resume <run-id>\`
- at \`develop\` with \`factory.develop.developer.kind: handoff\` (\`pending\` names no gate):
  report the step, its message and the brief path it gives; the developer finishes the work
  and runs \`! bin/wgf resume <run-id> --decision done\`, then \`$invoke resume <run-id>\`.
  Development is not complete until the engine says so.

Do not change the factory configuration to make a run more autonomous, and do not
advance a lifecycle state: the engine never moves one, and neither does this surface.
EOF
}

for row in "${workflows[@]}"; do
  IFS='|' read -r id runs summary craft continues <<< "$row"
  craft_md=""
  IFS=';' read -ra arr <<< "$craft"
  for p in "${arr[@]}"; do craft_md+="- \`$p\`"$'\n'; done
  # The groups this surface continues inside a run (`<surface> <group> <run-id>` =
  # `wgf <group> --run <run-id>`). Only `publish` exists; its text is the publication rule.
  continues_md="" continues_use="" continues_pre="" continues_completed=""
  continues_effects="" continues_start="" continues_next=""
  hint_continues="" allow_continues=()
  IFS=';' read -ra arr <<< "$continues"
  for g in "${arr[@]}"; do
    [ "$g" = publish ] || { echo "gen-adapters.sh: no surface text for group '$g'" >&2; exit 1; }
    continues_md+="- \`$g <run-id>\`, optionally with \`--store <DIR>\`: continues a run that
  drafted a release into the workflow's \`$g\` group (\`bin/wgf $g --run <run-id>\`),
  with the settings that run started with
"
    continues_use+=" or \`$g <run-id>\`"
    continues_pre+=" and \`$g <run-id>\`"
    continues_completed+=" - for \`$g <run-id>\`, a run that drafted a release is
   continued (step 4) rather than reported: its \`$g\` group has not run yet"
    continues_effects+="
   For \`$g <run-id>\`, say before starting that nothing reaches a portal until a person
   decides G6, and that a portal submission after it is a dry run unless the installation
   set \`factory.publish.mode: live\` and \`WGF_PUBLISH_LIVE=1\` - never set either. It
   starts without asking."
    continues_start+="   - $g: \`bin/wgf $g --run <run-id> [--store <DIR>] --json\`
"
    continues_next+=" Publication is the workflow's \`$g\` group, in the same run:
   \`@INVOKE@ $g <run-id>\` (\`bin/wgf $g --run <run-id>\`) validates the release per
   platform and stops at G5 and then G6, each a person's decision; the portal submission
   follows only a G6 \`publish\` and is a dry run unless the installation made it live."
    hint_continues+=" | $g <run-id>"
    allow_continues+=("$g")
  done
  # Claude Code pre-approves these engine calls for this surface, so a host in a restrictive
  # permission mode lets it read its own run. Starting and continuing a run are here because
  # the surface asks the user first where they cost money (step 3); `decide` is never listed.
  allowed="allowed-tools:"
  for py in python3 python; do
    for sub in where status logs "$id" resume "${allow_continues[@]}"; do
      allowed+=$'\n'"  - Bash($py \"\${CLAUDE_PLUGIN_ROOT}/runtime/scripts/wgf.py\" $sub *)"
    done
  done

  {
    cat <<EOF
---
description: $summary
argument-hint: "[--mock [--mock-plan JSON] [--hold-gates]] [--project ID] [--from STEP] [--store DIR] [\"<game idea>\"] | resume <run-id> [--from STEP]$hint_continues"
disable-model-invocation: true
$allowed
---

# /$id

EOF
    entry_body "$id" "$runs" "\`\$ARGUMENTS\`" \
      "in the background, with the Bash tool's \`run_in_background\`: a run can take hours,
   far longer than a foreground command may. You are notified when it exits." \
      "/web-game-factory:$id" \
      "Run \`bin/wgf where --json\` and stop unless \`installed\` is true and \`workflow\`
   names an existing file: the Factory - this workflow, core, the engine and its shipped
   configuration - is the runtime inside this plugin, never the working directory. The
   working directory is the project: report \`project_root\` and \`store\`, where this run's
   state and instance data are kept (\`WGF_PROJECT_DIR\` names another project)." \
      "Where \`python3\` is not on PATH (Windows), use \`python\` in its place." \
      "Delegate it to the \`research\` agent, which works"
  } | claude_paths > "$C/commands/$id.md"

  {
    cat <<EOF
# /$id (Web Game Factory)

EOF
    entry_body "$id" "$runs" "the text given with this prompt." \
      "as a long-running background process, not a blocking call: a run can take hours.
   Poll \`bin/wgf status <run-id>\` for progress." \
      "/$id" \
      "Stop unless \`$runs\` exists in the working directory
   (run from the factory repository root)." \
      "Where \`bin/wgf\` cannot be executed (Windows), use \`python scripts/wgf.py\` in its place." \
      "Follow \`$X/agents/research.md\`, working"
  } > "$X/commands/$id.md"
done

# ---------------------------------------------------------------- skills
# id|supports|covers|reads
skills=(
"market-intelligence|research|Normalizing platform signal into tiered claims and keeping evidence honest, including competitive teardowns of how leading portal games actually play, coded on the shared research vocabulary into a game corpus.|core/lifecycle/stages/market-scan.md;core/artifacts/shared/claim.schema.json;core/craft/competitive-teardown.md;core/craft/research-evidence.md;core/reference/research-vocabulary.yaml;core/artifacts/shared/game-record.schema.json"
"opportunity-scoring|analysis|Scoring models, normalizers, vetoes, and evidence coverage.|core/lifecycle/stages/score-opportunity.md;core/artifacts/shared/scoring-model.schema.json;core/reference/scoring/portfolio-default.v1.yaml"
"game-design|game-designer|Core loop, session structure, retention hooks, scope tiers, feature evaluation, the build spec, and the design consistency rules.|core/lifecycle/stages/design.md;core/artifacts/game-design.schema.json;core/reference/design-consistency-rules.yaml;core/craft/core-loop-and-difficulty.md;core/craft/onboarding-and-portal-ux.md;core/templates/gdd.md;core/craft/production-art-and-ui.md;core/craft/game-ui-kit.md;core/craft/retention-and-progression.md;core/craft/content-and-level-design.md;core/reference/genre-models.yaml;core/reference/design-depth.yaml;core/craft/feature-evaluation.md;core/reference/feature-catalogue.yaml"
"core-loop|game-designer, gameplay|Making the core loop worth repeating: decisions, risk and reward, mastery signals, data-driven difficulty ramps, fast retry and session beats.|core/craft/core-loop-and-difficulty.md;core/artifacts/game-design.schema.json;core/lifecycle/stages/strategy.md;core/craft/retention-and-progression.md;core/craft/content-and-level-design.md;core/reference/genre-models.yaml;core/reference/design-depth.yaml"
"level-design|game-designer, gameplay, qa|Content and level design per genre family: units, purpose arc, difficulty axes, variety, win/lose, acceptance.|core/reference/genre-models.yaml;core/craft/content-and-level-design.md;core/artifacts/game-design.schema.json;core/reference/design-depth.yaml"
"game-feel|gameplay, ui|Game feel and juice: the minimum feedback bar (input acknowledged, reward noticed, failure understood), easing, hit-stop, shake and particle budgets, frame-rate independence.|core/craft/game-feel.md;core/artifacts/game-design.schema.json;core/craft/juice.md"
"onboarding-ux|ui, game-designer|The first 30 seconds on a web portal, tutorial approach, HUD and mobile touch layout, accessibility baseline, and store presentation.|core/craft/onboarding-and-portal-ux.md;core/craft/ui-hud-mobile.md;core/craft/accessibility.md;core/craft/production-art-and-ui.md;core/craft/game-ui-kit.md"
"monetization|game-designer, sdk|Placement design against platform ad capabilities and cadence limits, placed on beat boundaries with stated player value.|core/artifacts/game-design.schema.json;core/reference/platforms/;core/craft/onboarding-and-portal-ux.md"
"architecture|architect|Engine selection, performance budgets, and the generic/game/platform ownership split.|core/lifecycle/stages/tech-plan.md;core/artifacts/tech-plan.schema.json;core/craft/web-performance.md"
"development-planning|architect|Milestones, tasks, dependencies, acceptance criteria and test planning.|core/artifacts/tech-plan.schema.json;core/templates/tech-plan.md"
"web-performance|architect, gameplay, qa|Web game performance: load and first-frame budgets, bundle splitting, atlases and GPU-compressed assets, draw calls, memory, leaks on restart, low-end measurement.|core/craft/web-performance.md;core/craft/3d-diagnostics.md;core/artifacts/tech-plan.schema.json"
"pixijs|gameplay, ui|2D rendering with PixiJS: sprites, spritesheets, animation, particles, pooling and batching.|core/artifacts/tech-plan.schema.json;core/craft/web-performance.md;core/craft/game-feel.md;core/craft/2d-assets.md;core/craft/production-art-2d.md;core/craft/production-wiring.md"
"phaser|gameplay, ui|2D with Phaser: the loop game-core owns and Phaser does not, scenes and their shutdown, assets, input, tweens, arcade physics, tilemaps, cameras, audio, debugging and QA.|core/craft/phaser.md;core/craft/web-performance.md;core/craft/game-feel.md;core/craft/2d-assets.md;core/craft/production-art-2d.md;core/craft/production-wiring.md"
"threejs|gameplay|3D with Three.js: what the template's renderer binding owns, the fixed update order, camera rigs, the physics ladder the tech plan pins, GLB/GLTF import checks, animation clips and root motion, Draco/Meshopt and KTX2, instancing and disposal.|core/artifacts/tech-plan.schema.json;core/craft/3d-scene-and-physics.md;core/craft/3d-assets-and-animation.md;core/craft/web-performance.md;core/craft/game-feel.md;core/craft/production-art-3d.md;core/craft/production-wiring.md"
"assets|asset|Asset manifests, sourcing, licensing, provenance of generated assets, and compression pipelines.|core/artifacts/asset-manifest.schema.json;core/reference/asset-policy.yaml;core/craft/art-direction.md;core/craft/game-audio.md;core/craft/2d-assets.md;core/craft/production-art-2d.md;core/craft/production-art-3d.md;core/craft/production-wiring.md"
"art-direction|game-designer, asset|Turning the visual identity into a style sheet and keeping library, procedural and generated assets coherent and readable.|core/craft/art-direction.md;core/lifecycle/stages/design.md;core/reference/asset-policy.yaml;core/craft/production-art-and-ui.md;core/craft/production-art-2d.md;core/craft/production-art-3d.md;core/craft/game-ui-kit.md"
"audio|asset, gameplay, ui|Game audio for the browser: music as a produced, seamless, adaptive loop; designed sound effects and their timing; mixing levels and ducking; unlock on first gesture, mute, pause and ad silence; formats, budgets and the quality checks.|core/craft/game-audio.md;core/reference/asset-policy.yaml;core/reference/asset-quality.yaml;core/reference/production-quality.yaml"
"platform-sdk|sdk|The platform abstraction: ads, cloud save, leaderboards, analytics wiring.|core/reference/platforms/;core/artifacts/shared/platform-profile.schema.json"
"localization|release, ui|Required locales per platform, translation quality, string extraction.|core/reference/platforms/;core/artifacts/release-manifest.schema.json"
"gameplay-review|architect|Reviewing a development commit read-only for the defects players feel: restart state, frame-rate dependence, pause leakage, input handling, tuning as data, missing feedback hooks.|core/craft/gameplay-review.md;core/craft/3d-diagnostics.md;core/lifecycle/stages/prototype.md;core/artifacts/review-report.schema.json"
"playtesting|qa, game-designer|Agent browser playthroughs that record a gameplay session, stranger playtest protocol, and the performance pass that feed the prototype report and QA.|core/craft/playtesting.md;core/artifacts/shared/gameplay-session.schema.json;core/artifacts/prototype-report.schema.json;core/lifecycle/stages/prototype-review.md"
"qa|qa|Test suites, device matrices, defect triage, and performance measurement.|core/lifecycle/stages/qa.md;core/artifacts/verification-report.schema.json;core/artifacts/qa-report.schema.json;core/craft/playtesting.md;core/craft/3d-diagnostics.md"
"release|release|Manifests, checksums, store metadata and presentation, platform assertions, and submission.|core/lifecycle/stages/release-candidate.md;core/lifecycle/stages/publish.md;core/lifecycle/stages/store-listing.md;core/artifacts/release-manifest.schema.json;core/craft/onboarding-and-portal-ux.md;core/craft/store-listing.md"
"store-listing|release|The store listing: the canonical package captured from the verified build (branding from the game's own assets, screenshots and a gameplay recording of real play, copy grounded in the design), one rendition per platform under its profile's store_listing block, and the validation that reports unknown requirements as unknown.|core/lifecycle/stages/store-listing.md;core/artifacts/store-listing.schema.json;core/artifacts/listing-validation-report.schema.json;core/reference/store-listing.yaml;core/artifacts/shared/platform-profile.schema.json;core/reference/platforms/;core/craft/store-listing.md"
"production-art-2d|asset, gameplay, game-designer|2D production art that reads as a product: silhouette-first sprites with a distinct shape per level and variant, palette roles, the layered-SVG style kit (outlines, misregistration, halftone), backgrounds, VFX sprites, sizes and anchors, and authoring through the assets step or a library.|core/craft/production-art-2d.md;core/craft/production-art-and-ui.md;core/craft/2d-assets.md;core/reference/asset-policy.yaml"
"production-art-3d|asset, gameplay, game-designer|3D production art from model specs: part decomposition of recognisable low-poly objects, bevel, taper and mirror, materials and emissive, the lighting rig, fog and sky, chase camera and portrait framing, and building and inspecting models.|core/craft/production-art-3d.md;core/craft/production-art-and-ui.md;core/craft/3d-assets-and-animation.md;core/craft/3d-scene-and-physics.md;core/artifacts/shared/model-spec.schema.json"
"game-ui-kit|ui, asset, game-designer|The game's own interface kit: fonts as licensed assets with locale glyph coverage, HUD layout without overlap, contrast and touch-target minimums, drawn buttons, title, pause, result and retry screens, and the mobile portrait layout.|core/craft/game-ui-kit.md;core/craft/production-art-and-ui.md;core/craft/ui-hud-mobile.md;core/craft/accessibility.md"
"juice|gameplay, ui|Game feel with numbers: drop bounce, merge pop and burst, combo text, shake, near-miss and crash feedback, opening grace, and acknowledgement within 100 ms.|core/craft/juice.md;core/craft/game-feel.md"
"production-wiring|gameplay, ui, asset|Wiring production art into a build: loading the runtime asset manifest (variants, roles, fonts), the play probe's asset, render and assets_loaded, the regression guard end-to-end test, and self-checking against the production gate and visual QA before reporting.|core/craft/production-wiring.md;core/craft/2d-assets.md;core/artifacts/shared/play-probe.schema.json;core/reference/visual-quality.yaml;core/reference/experience-rules.yaml"
)

for row in "${skills[@]}"; do
  IFS='|' read -r id supports covers reads <<< "$row"
  reads_md=""
  IFS=';' read -ra arr <<< "$reads"
  for p in "${arr[@]}"; do reads_md+="- \`$p\`"$'\n'; done

  mkdir -p "$C/skills/$id" "$X/skills/$id"
  claude_paths > "$C/skills/$id/SKILL.md" <<EOF
---
name: $id
description: $covers Supports the $supports role(s). Use when working on that part of the Factory lifecycle.
---

# $id

Supports: **$supports**

$covers

## Authoritative sources

$reads_md
This skill is a pointer, not a copy. Read the paths above rather than relying on anything
restated here; core is authoritative and this file is not a substitute for it.
EOF

  cat > "$X/skills/$id/SKILL.md" <<EOF
# $id (Web Game Factory skill)

Supports: **$supports**

$covers

## Authoritative sources

$reads_md
This skill is a pointer, not a copy. Read the paths above rather than relying on anything
restated here; core is authoritative and this file is not a substitute for it.
EOF
done

echo "generated: $(find $C/agents $C/commands $C/skills $X/agents $X/commands $X/skills -type f -name '*.md' | wc -l) markdown surfaces"
python3 scripts/build-plugin-runtime.py

#!/usr/bin/env bash
# Generates the Claude and Codex adapter surfaces from core/bindings/adapter-binding.yaml.
#
# Adapter files are thin pointers into core: frontmatter (Claude) or a header (Codex),
# a must-read list, and a short provider-specific execution-notes block. Because they are
# formulaic by design, generating them is what keeps the two adapters genuinely identical
# in substance and different only in host mechanics.
#
# Re-run after editing the binding manifest. It overwrites agents/, commands/ and skills/
# in both plugins; it does not touch READMEs or CONFORMANCE.md.
set -euo pipefail
cd "$(dirname "$0")/.."

C=claude-web-game-plugin
X=codex-web-game-plugin
mkdir -p $C/agents $C/commands $C/skills $X/agents $X/commands $X/skills

# ---------------------------------------------------------------- agents
# id|owns|description|must_read (semicolon-separated)|notes
agents=(
"research|portfolio:market-scan, portfolio:discovered|Gathers web game market signal from portal sources and normalizes it into tiered claims and candidate opportunities. Use when starting a market scan, researching a genre or platform, or refreshing stale evidence on the backlog.|core/roles/research.md;core/lifecycle/stages/market-scan.md;core/artifacts/shared/claim.schema.json;core/artifacts/opportunity.schema.json;core/artifacts/research-report.schema.json;core/reference/dimensions.yaml;core/craft/competitive-teardown.md|Write claims to workspace/claims/ and opportunities to workspace/opportunities/. Observation and interpretation are always separate claims. Never edit a claim; supersede it. External tools (browser, generation, docs lookup, analytics) only as core/craft/tool-capabilities.md allows: localhost-only browsing of builds, provenance and licence on anything generated, human approval before any paid job."
"analysis|portfolio:scored, shortlisted, approved, title:concept|Scores opportunities against a versioned scoring model, tracks evidence coverage, and presents the ranked shortlist at gate G1. Use when evaluating or re-scoring opportunities, or preparing an opportunity selection decision.|core/roles/analysis.md;core/lifecycle/stages/score-opportunity.md;core/lifecycle/stages/opportunity-selection.md;core/artifacts/evaluation.schema.json;core/artifacts/shared/scoring-model.schema.json;core/reference/scoring/portfolio-default.v1.yaml|Append evaluations, never overwrite. Record the scoring model by id, version and file hash. Empty evidence_refs forces tier=hypothesis; do not work around it. External tools (browser, generation, docs lookup, analytics) only as core/craft/tool-capabilities.md allows: localhost-only browsing of builds, provenance and licence on anything generated, human approval before any paid job."
"game-designer|title:strategy, title:design|Authors the title strategy including its kill criteria, then designs scope, session, retention and monetization together as one artifact. Use when drafting a strategy, producing a game design, or presenting prototype evidence at gate G4.|core/roles/game-designer.md;core/lifecycle/stages/strategy.md;core/lifecycle/stages/design.md;core/artifacts/title-strategy.schema.json;core/artifacts/game-design.schema.json;core/reference/design-consistency-rules.yaml;core/templates/gdd.md;core/craft/core-loop-and-difficulty.md;core/craft/onboarding-and-portal-ux.md;core/craft/art-direction.md|Kill criteria are written at strategy, before any code exists. out_of_scope must be non-empty. When the consistency check fails, cut scope rather than relaxing a rule. External tools (browser, generation, docs lookup, analytics) only as core/craft/tool-capabilities.md allows: localhost-only browsing of builds, provenance and licence on anything generated, human approval before any paid job."
"architect|title:tech-plan; reviews development commits in title:prototype|Selects the engine, defines architecture and performance budgets, and writes the development plan a coding agent works from; then reviews each development commit read-only and returns a review-report. Use when turning an approved design into a technical plan, preparing gate G3, or reviewing a prototype commit.|core/roles/architect.md;core/lifecycle/stages/tech-plan.md;core/artifacts/tech-plan.schema.json;core/templates/tech-plan.md;core/lifecycle/stages/prototype.md;core/artifacts/review-report.schema.json;core/craft/web-performance.md;core/craft/gameplay-review.md|PixiJS for 2D, Three.js for 3D, nothing else. Every task needs acceptance criteria and tests. repo_params carries the full game.config.yaml content with platforms pinned as id@profile-version. As a reviewer you are read-only: never edit, stage or commit in the game repository. The Factory fingerprints the checkout, and a review that changed anything is undone and discarded. The verdict shape is the one in the review brief the Factory writes. External tools (browser, generation, docs lookup, analytics) only as core/craft/tool-capabilities.md allows: localhost-only browsing of builds, provenance and licence on anything generated, human approval before any paid job."
"qa|release:qa|Independently verifies a built release candidate and produces the QA report read at gate G5. Use when a release is in QA, or when prototype evidence needs its numbers checked at G4.|core/roles/qa.md;core/lifecycle/stages/qa.md;core/artifacts/verification-report.schema.json;core/artifacts/qa-report.schema.json;core/artifacts/shared/gameplay-session.schema.json;core/templates/qa-report.md;core/craft/playtesting.md;core/craft/web-performance.md;core/craft/accessibility.md|You verify work you did not author, and you may fail a build its author believes is finished. Every defect needs reproduction steps. verdict is derived from blocking defects and performance budgets. When a Playwright browser tool is available, play the built bundle (a preview server, never the dev server) through each gameplay aspect and record the session to build/verification/gameplay-session.json in the game repository, naming the commit under test, before running \`bin/wgf verify\`; without one, verification falls back to the repository's Playwright suites. Never report a portal's approval. External tools (browser, generation, docs lookup, analytics) only as core/craft/tool-capabilities.md allows: localhost-only browsing of builds, provenance and licence on anything generated, human approval before any paid job."
"release|title:scaffolding, release:draft/rc/validating/submitting|Creates game repositories from the template, assembles and freezes releases, runs platform validation, and prepares portal submissions. Also owns compliance and localization. Use for scaffolding, release assembly, validation, or publishing.|core/roles/release.md;core/lifecycle/stages/scaffolding.md;core/lifecycle/stages/release-draft.md;core/lifecycle/stages/release-candidate.md;core/lifecycle/stages/platform-validation.md;core/lifecycle/stages/publish.md;core/artifacts/release-manifest.schema.json;core/artifacts/platform-publication.schema.json;core/artifacts/review-report.schema.json;core/templates/release-report.md;core/craft/onboarding-and-portal-ux.md|Game repositories originate from web-game-template, never from scratch. A frozen manifest is immutable. Validate against the pinned profile version. Secrets never enter source. A portal rejection must produce a compliance finding and a profile version bump. External tools (browser, generation, docs lookup, analytics) only as core/craft/tool-capabilities.md allows: localhost-only browsing of builds, provenance and licence on anything generated, human approval before any paid job."
"liveops|title:live|Interprets post-launch analytics, runs scheduled performance reviews, and decides iterate, scale, hold or sunset. Use for any post-launch analysis, experiment design, or campaign proposal at gate G7.|core/roles/liveops.md;core/lifecycle/stages/live.md;core/lifecycle/stages/performance-review.md;core/lifecycle/stages/campaign.md;core/artifacts/performance-review.schema.json|Keep metrics, findings, hypotheses and experiments in their separate fields. Report per platform with sample size, never averaged. A projection is a hypothesis with a number attached; label it. Campaigns need a human-authorized ceiling. External tools (browser, generation, docs lookup, analytics) only as core/craft/tool-capabilities.md allows: localhost-only browsing of builds, provenance and licence on anything generated, human approval before any paid job."
"gameplay|works in title:prototype, title:production|Implements core mechanics, game loop, systems and progression from the development plan, and writes the prototype report. Use when building prototype or production tasks.|core/roles/implementers.md;core/lifecycle/stages/prototype.md;core/lifecycle/stages/production.md;core/artifacts/prototype-report.schema.json;core/artifacts/review-report.schema.json;core/artifacts/game-design.schema.json;core/craft/game-feel.md;core/craft/core-loop-and-difficulty.md|Work the plan's tasks in dependency order and satisfy both acceptance criteria and tests. When the brief opens with blockers from code review or verification, fix those first. Scope, monetization, platform strategy, core gameplay and architecture change only through the production change process. External tools (browser, generation, docs lookup, analytics) only as core/craft/tool-capabilities.md allows: localhost-only browsing of builds, provenance and licence on anything generated, human approval before any paid job."
"ui|works in title:prototype, title:production|Implements interface, HUD, menus, onboarding flow and platform UI constraints. Use when building or revising any player-facing interface.|core/roles/implementers.md;core/lifecycle/stages/production.md;core/lifecycle/stages/prototype.md;core/artifacts/game-design.schema.json;core/craft/onboarding-and-portal-ux.md;core/craft/ui-hud-mobile.md;core/craft/accessibility.md;core/craft/game-feel.md|time_to_first_play_s and time_to_first_reward_s are design targets, not aspirations. Portal traffic has no install cost anchoring players through a slow start. External tools (browser, generation, docs lookup, analytics) only as core/craft/tool-capabilities.md allows: localhost-only browsing of builds, provenance and licence on anything generated, human approval before any paid job."
"asset|works in title:design through production|Authors the asset manifest with sources and cost estimates, then produces or sources assets and tracks line-item status. Use when planning asset cost during design or producing assets during development.|core/roles/implementers.md;core/artifacts/asset-manifest.schema.json;core/reference/asset-policy.yaml;core/craft/art-direction.md;core/craft/audio.md|Contribute during design: asset cost is an input to the scope decision. Prefer library and procedural sources. No purchased or library item is integrated without a recorded license. External tools (browser, generation, docs lookup, analytics) only as core/craft/tool-capabilities.md allows: localhost-only browsing of builds, provenance and licence on anything generated, human approval before any paid job."
"sdk|works in title:prototype, production, release:validating|Integrates platform SDKs, ads, analytics and cloud save through the template's platform abstraction. Use when wiring any portal capability or preparing platform validation.|core/roles/implementers.md;core/reference/platforms/;core/artifacts/shared/platform-profile.schema.json;core/craft/onboarding-and-portal-ux.md|Game code never calls a portal SDK directly; it calls the abstraction. Integrate during prototype, not production, so monetization is proven in context. External tools (browser, generation, docs lookup, analytics) only as core/craft/tool-capabilities.md allows: localhost-only browsing of builds, provenance and licence on anything generated, human approval before any paid job."
)

for row in "${agents[@]}"; do
  IFS='|' read -r id owns desc reads notes <<< "$row"
  reads_md=""; n=1
  IFS=';' read -ra arr <<< "$reads"
  for p in "${arr[@]}"; do reads_md+="$n. \`$p\`"$'\n'; n=$((n+1)); done

  cat > "$C/agents/$id.md" <<EOF
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

- Resolve core paths relative to the factory repository root; this plugin sits beside \`core/\`.
- Write artifacts to the \`repo_path\` given in each schema's \`x-wgf\` block.
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
      claude_step="Read \`workspace/\` and report. This command changes nothing."
      codex_step="$claude_step"
      record_step="Write nothing." ;;
    *)
      claude_step="Delegate the work to the \`$role\` agent."
      codex_step="Follow \`$X/agents/$role.md\`."
      record_step="Record the outcome: artifacts at their \`repo_path\`, and the title's \`state.json\`." ;;
  esac

  cat > "$C/commands/wgf-$id.md" <<EOF
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

# ---------------------------------------------------------------- skills
# id|supports|covers|reads
skills=(
"market-intelligence|research|Normalizing platform signal into tiered claims and keeping evidence honest, including competitive teardowns of how leading portal games actually play.|core/lifecycle/stages/market-scan.md;core/artifacts/shared/claim.schema.json;core/craft/competitive-teardown.md"
"opportunity-scoring|analysis|Scoring models, normalizers, vetoes, and evidence coverage.|core/lifecycle/stages/score-opportunity.md;core/artifacts/shared/scoring-model.schema.json;core/reference/scoring/portfolio-default.v1.yaml"
"game-design|game-designer|Core loop, session structure, retention hooks, scope tiers, the build spec, and the design consistency rules.|core/lifecycle/stages/design.md;core/artifacts/game-design.schema.json;core/reference/design-consistency-rules.yaml;core/craft/core-loop-and-difficulty.md;core/craft/onboarding-and-portal-ux.md;core/templates/gdd.md"
"core-loop|game-designer, gameplay|Making the core loop worth repeating: decisions, risk and reward, mastery signals, data-driven difficulty ramps, fast retry and session beats.|core/craft/core-loop-and-difficulty.md;core/artifacts/game-design.schema.json;core/lifecycle/stages/strategy.md"
"game-feel|gameplay, ui|Game feel and juice: the minimum feedback bar (input acknowledged, reward noticed, failure understood), easing, hit-stop, shake and particle budgets, frame-rate independence.|core/craft/game-feel.md;core/artifacts/game-design.schema.json"
"onboarding-ux|ui, game-designer|The first 30 seconds on a web portal, tutorial approach, HUD and mobile touch layout, accessibility baseline, and store presentation.|core/craft/onboarding-and-portal-ux.md;core/craft/ui-hud-mobile.md;core/craft/accessibility.md"
"monetization|game-designer, sdk|Placement design against platform ad capabilities and cadence limits, placed on beat boundaries with stated player value.|core/artifacts/game-design.schema.json;core/reference/platforms/;core/craft/onboarding-and-portal-ux.md"
"architecture|architect|Engine selection, performance budgets, and the generic/game/platform ownership split.|core/lifecycle/stages/tech-plan.md;core/artifacts/tech-plan.schema.json;core/craft/web-performance.md"
"development-planning|architect|Milestones, tasks, dependencies, acceptance criteria and test planning.|core/artifacts/tech-plan.schema.json;core/templates/tech-plan.md"
"web-performance|architect, gameplay, qa|Web game performance: load and first-frame budgets, bundle splitting, atlases and GPU-compressed assets, draw calls, memory, leaks on restart, low-end measurement.|core/craft/web-performance.md;core/artifacts/tech-plan.schema.json"
"pixijs|gameplay, ui|2D rendering with PixiJS: sprites, spritesheets, animation, particles, pooling and batching.|core/artifacts/tech-plan.schema.json;core/craft/web-performance.md;core/craft/game-feel.md"
"threejs|gameplay|3D with Three.js: scene management, GLB/GLTF, Draco/Meshopt, KTX2 textures, disposal.|core/artifacts/tech-plan.schema.json;core/craft/web-performance.md;core/craft/game-feel.md"
"assets|asset|Asset manifests, sourcing, licensing, provenance of generated assets, and compression pipelines.|core/artifacts/asset-manifest.schema.json;core/reference/asset-policy.yaml;core/craft/art-direction.md;core/craft/audio.md"
"art-direction|game-designer, asset|Turning the visual identity into a style sheet and keeping library, procedural and generated assets coherent and readable.|core/craft/art-direction.md;core/lifecycle/stages/design.md;core/reference/asset-policy.yaml"
"audio|asset, gameplay|Game audio for the browser: unlock on first gesture, mute, cue lists per event, mix and variation, size budgets.|core/craft/audio.md;core/reference/asset-policy.yaml"
"platform-sdk|sdk|The platform abstraction: ads, cloud save, leaderboards, analytics wiring.|core/reference/platforms/;core/artifacts/shared/platform-profile.schema.json"
"localization|release, ui|Required locales per platform, translation quality, string extraction.|core/reference/platforms/;core/artifacts/release-manifest.schema.json"
"gameplay-review|architect|Reviewing a development commit read-only for the defects players feel: restart state, frame-rate dependence, pause leakage, input handling, tuning as data, missing feedback hooks.|core/craft/gameplay-review.md;core/lifecycle/stages/prototype.md;core/artifacts/review-report.schema.json"
"playtesting|qa, game-designer|Agent browser playthroughs that record a gameplay session, stranger playtest protocol, and the performance pass that feed the prototype report and QA.|core/craft/playtesting.md;core/artifacts/shared/gameplay-session.schema.json;core/artifacts/prototype-report.schema.json;core/lifecycle/stages/prototype-review.md"
"qa|qa|Test suites, device matrices, defect triage, and performance measurement.|core/lifecycle/stages/qa.md;core/artifacts/verification-report.schema.json;core/artifacts/qa-report.schema.json;core/craft/playtesting.md"
"release|release|Manifests, checksums, store metadata and presentation, platform assertions, and submission.|core/lifecycle/stages/release-candidate.md;core/lifecycle/stages/publish.md;core/artifacts/release-manifest.schema.json;core/craft/onboarding-and-portal-ux.md"
)

for row in "${skills[@]}"; do
  IFS='|' read -r id supports covers reads <<< "$row"
  reads_md=""
  IFS=';' read -ra arr <<< "$reads"
  for p in "${arr[@]}"; do reads_md+="- \`$p\`"$'\n'; done

  mkdir -p "$C/skills/$id" "$X/skills/$id"
  cat > "$C/skills/$id/SKILL.md" <<EOF
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

echo "generated: $(find $C $X -type f -name '*.md' | wc -l) markdown surfaces"

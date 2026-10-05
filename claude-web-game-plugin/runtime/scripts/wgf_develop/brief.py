"""The development brief: what the developer is asked to build, derived from the artifacts.

The brief is the whole interface between the Factory and whoever writes the game - a person,
or an agent host driven by the `command` developer. It is written into the game repository
as `docs/development/brief.md` (to read) and `brief.json` (to check against), so the
repository records what each commit was asked to satisfy.

It restates no schema. It selects from the game design what an implementer needs, applies
the template's rules to it, and states the two contracts the developer owes back: the
integration seam the SDK module wires, and the development report this module checks.

Two selections are carried rather than summarised, because they are what the design and the
plan exist to hand over: the design's `build_spec` (the tiers the run builds - mechanics with
their rules and tuning, states, screens, HUD, tutorial, rewards and failure with their
feedback, session beats, audio cues, responsive behaviour, visual identity), and the approved
tech plan's milestones and tasks of the phases the run builds, each with its acceptance
criteria.

What the run builds is the approved tech plan's `dev_plan.build_scope` (tech-plan 1.1.0, from
the run's quality tier): the MVP and the prototype phase at `mvp`; at `release` also the
post-mvp tier and the production phase - every feature and content unit the release ships,
since in `new-game` nothing is built after G4. A run without a tech plan, or with a tech-plan
1.0.0, builds the MVP, as before.
"""

import json
import os

from wgflib import gameseam, paths, quality_bar
from wgflib import template_contract as contract
from wgflib.yamllite import load_file

from wgf_verification.checks.gameplay import ASPECTS, required_aspects_for

from . import content as content_contract
from . import specialist as specialist_section
from .content import CONTENT_PATH, TEST_PATH
from .scope import DEFAULT_WRITABLE

__all__ = ["REQUIRED_SYSTEMS", "INTEGRATION_CONTRACT", "REPORT_PATH", "BRIEF_DIR",
           "build_brief", "render_markdown", "PROTECTED_PATHS", "STRUCTURAL_PATHS",
           "TEMPLATE_SOURCE", "ENGINE_DIRS", "select_build_spec", "select_dev_plan",
           "select_production_art", "select_content", "shell_contract", "build_scope"]

BRIEF_DIR = "docs/development"
REPORT_PATH = f"{BRIEF_DIR}/report.json"

# Every system a playable MVP needs, whatever the genre. The developer reports each as
# done/partial/missing in the development report; a build with any not `done` is not a
# playable build, and the checks refuse it.
REQUIRED_SYSTEMS = (
    ("boot", "Boot sequence kept in the template's order: platform init, loading progress, "
             "signal ready, start. Replace BootScene; do not reorder main.ts."),
    ("game-state", "One explicit state model for the session (e.g. title -> playing -> "
                   "game-over), engine-agnostic, in src/game/, unit-tested."),
    ("scenes", "Scenes implementing @wgf/game-core's Scene, switched through "
               "Game.changeScene; each publishes its id to #hud[data-scene]."),
    ("input", "Keyboard, mouse and touch mapped to game actions in src/input/, so rules "
              "never read raw DOM events. Input stops while the game is paused."),
    ("core-loop", "The design's core loop, advanced by the fixed-timestep update(), never by "
                  "requestAnimationFrame or setTimeout."),
    ("mechanics", "Every mechanic the MVP tier names, as pure rules code with unit tests."),
    ("content", "Every MVP unit of the content table exists in public/content/units.json "
                "under its design id with the design's objective, mechanics and difficulty "
                "values, is loaded at boot, and is reachable in play in design order (the "
                "probe's content.unit_id). A unit you could not build is `cut` or `partial` "
                "in report.json content_units, with a design_gaps entry when the design does "
                "not say enough to build it."),
    ("win-lose", "The experience contract's win (unless the genre is endless) and lose are "
                 "reachable from play; each unit's own success and failure end it in "
                 "won/lost or advance it (content.progress: a value that RISES to its target - gems 2 of 3, goal reached 0 of 1 - never a count that falls; moves or time left are metrics)."),
    ("difficulty-curve", "Each axis in the design's difficulty.axes is a data value per unit "
                         "read from units.json (authored) or a function of time (parametric), "
                         "exposed in the probe as metrics.difficulty.<axis>."),
    ("mastery", "The mastery block's signals are shown on the result screen and persisted "
                "through the seam."),
    ("progression", "The design's progression and difficulty ramp, persisted through the "
                    "integration seam's save/load: after a page reload the probe reports the "
                    "same content.unit_index and metrics.best before any input. Every "
                    "progression step that gates content is enforced in play and stated in "
                    "public/content/units.json `unlocks` ({id, opens, after, condition}: a "
                    "unit or group the file carries) - the gates are counted there."),
    ("ui", "Menus and screens the design lists (ux.screens), readable on a phone held in "
           "one hand."),
    ("hud", "In-run HUD: score and whatever else the loop needs the player to see."),
    ("tutorial", "The design's onboarding (ux.onboarding) - first play within "
                 "session.time_to_first_play_s, no wall of text."),
    ("game-over", "An end-of-run screen stating the result and the best result."),
    ("restart", "Restart from game over in one action, without reloading the page."),
    ("asset-loading", "Assets from the asset manifest loaded before play with loading "
                      "progress reported; procedural items generated in code."),
    ("responsive-layout", "Correct at any size and orientation, from 360x640 portrait to "
                          "desktop; resize is handled, nothing is cropped off-screen."),
    ("audio-hooks", "An audio service in src/audio/ that plays the design's build_spec.audio "
                    "cues from the runtime asset manifest (types music and sfx) on their "
                    "triggers: music from the first input, crossfaded between states and "
                    "ducked under stings; nothing before the first input; silent while "
                    "paused, muted (the player's toggle or the platform's) and during ads."),
    ("play-probe", "window.__wgf__.play.snapshot(), exactly as the Play probe section below "
                   "specifies: state, the experience contract's metrics, on-screen entities "
                   "with their drawn bounds, the inputs available now, and - only with "
                   "wgf-probe=1 in the URL - the oracle. Read-only."),
)

# Systems a greybox cannot finish, because what they serve arrives in production: assets and
# sound do not exist yet, and progression's persistence is not what a greybox proves. In the
# greybox phase they may be reported `partial` or `deferred`; production finishes them.
# Requiring `done` of them made an honest greybox fail conformance and a dishonest one pass.
GREYBOX_DEFERRABLE = ("progression", "asset-loading", "audio-hooks")

# What the playability step reads from the running build (core/artifacts/shared/).
PLAY_PROBE_SCHEMA = os.path.join(paths.ARTIFACTS, "shared", "play-probe.schema.json")
# The entity roles a player must be able to read: the visual gate's, and the ones production
# draws from assets (core/reference/visual-quality.yaml `entities.readable_roles`).
READABLE_ROLES = tuple((load_file(os.path.join(paths.REFERENCE, "visual-quality.yaml"))
                        .get("entities") or {}).get("readable_roles") or ())
# Where the bar for a finished game's art and UI is described.
PRODUCTION_CRAFT = "core/craft/production-art-and-ui.md"
AUDIO_CRAFT = "core/craft/game-audio.md"
# The playbooks distilled from the reference games, by what they serve: the art of the
# engine's dimension, then the UI kit, the feel and the wiring every production build needs.
PRODUCTION_ART_CRAFT = {"pixijs": "core/craft/production-art-2d.md",
                        "phaserjs": "core/craft/production-art-2d.md",
                        "threejs": "core/craft/production-art-3d.md"}
PRODUCTION_CRAFT_SHARED = ("core/craft/game-ui-kit.md", "core/craft/juice.md",
                           "core/craft/production-wiring.md")


def production_craft(engine):
    """The craft playbook paths a production build of `engine` is pointed at, in order."""
    art = PRODUCTION_ART_CRAFT.get(engine)
    return [PRODUCTION_CRAFT] + ([art] if art else []) + list(PRODUCTION_CRAFT_SHARED)


def factory_path(relative):
    """An absolute path to a Factory file. The developer's working directory is the game
    checkout: a path relative to the Factory names nothing it can open."""
    return os.path.join(paths.ROOT, *relative.split("/"))


# The developer's eyes: frames of the built game (tools/look.mjs), run with the checkout's
# own Playwright. Absolute, for the same reason as factory_path.
LOOK_TOOL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tools", "look.mjs")
LOOK_OUT_ROOT = "/tmp/wgf-look"

# Where an unattended developer's throwaway files go: inside a writable path, since its file
# tools write nowhere else, and removable by the `git clean -f -- tests/*` its argv allows.
SCRATCH = "tests/scratch-*"

# What a developer reaches for and the host refuses, by what it was for (live runs,
# 2026-10-03). Each is named in the brief only while the argv does not admit it.
SHELL_HABITS = ("cd", "sed", "python3", "netstat", "curl", "rm", "mv")


def _rules(value):
    """Permission rules from one --allowedTools / --disallowedTools value: comma- or
    space-separated, a comma or space inside `Tool(...)` belonging to the rule."""
    rules, current, depth = [], "", 0
    for char in str(value):
        if char in ", " and depth == 0:
            if current:
                rules.append(current)
            current = ""
            continue
        depth += {"(": 1, ")": -1}.get(char, 0)
        current += char
    if current:
        rules.append(current)
    return rules


def shell_contract(developer):
    """What an unattended developer's shell admits, read from its own argv: the `Bash(...)`
    rules after --allowedTools and --disallowedTools. None for a developer that is not a
    configured command (a person is not refused by a permission rule).

    The live runs of 2026-10-03: sessions under `--permission-mode dontAsk` sent compound
    commands (`git status && netstat ...`, `pnpm lint | tail`), `sed -i`, `python3` and
    `cd`, were refused, and four of them stopped and asked for a shell nobody could grant.
    The brief states the contract from the argv that enforces it, so the two cannot differ.
    """
    developer = developer or {}
    if developer.get("kind") != "command":
        return None
    argv = [str(part) for part in developer.get("argv") or []]
    found = {"--allowedTools": [], "--disallowedTools": []}
    flag = None
    for part in argv:
        name, _, inline = part.partition("=")
        if name in found:
            flag = name
            if inline:
                found[flag].extend(_rules(inline))
                flag = None
            continue
        if flag and not part.startswith("-"):  # the flag is variadic, as the host's is
            found[flag].extend(_rules(part))
            continue
        flag = None
    return {"allowed": _bash(found["--allowedTools"]),
            "denied": _bash(found["--disallowedTools"])}


def _bash(rules):
    return [r[len("Bash("):-1] for r in rules if r.startswith("Bash(") and r.endswith(")")]


def craft_guides(engine):
    """Every craft playbook in the Factory a developer of `engine` may read: the production
    ones first, then the rest of core/craft/, absolute."""
    first = production_craft(engine) + [AUDIO_CRAFT]
    rest = []
    craft_dir = os.path.join(paths.CORE, "craft")
    if os.path.isdir(craft_dir):
        for name in sorted(os.listdir(craft_dir)):
            rel = f"core/craft/{name}"
            if name.endswith(".md") and rel not in first and not _other_engine_art(rel, engine):
                rest.append(rel)
    return [factory_path(p) for p in first + rest]


def _other_engine_art(rel, engine):
    mine = PRODUCTION_ART_CRAFT.get(engine)
    return rel in PRODUCTION_ART_CRAFT.values() and rel != mine

# Paths a game may not edit. packages/ is the template's (fix the template instead);
# game.config.yaml is written from the approved tech plan; the pipelines and release tooling
# are shared infrastructure whose behaviour gates depend on. package.json names the scripts
# every later check runs (`pnpm run test` is whatever its `test` says) and tsconfig.json what
# the typecheck covers: a build that rewrote either could pass develop, sdk and verify
# without being checked at all.
PROTECTED_PATHS = ("packages", contract.GAME_CONFIG, ".github", "scripts",
                   contract.PLATFORM_PROFILES_DIR, contract.PLAYWRIGHT_CONFIG, "vite.config.ts",
                   contract.VITEST_WORKSPACE, "eslint.config.js", "tsconfig.base.json",
                   "pnpm-workspace.yaml", contract.PACKAGE_JSON, "tsconfig.json",
                   contract.PNPM_LOCK)

# Template source inside the writable src/: shipped by the template and imported by the game
# and by the Factory's own seam wiring (src/platform/integration.ts imports ./bind.js and
# ../core/config.js). Not the game's to edit, delete or recreate. The brief states it so a
# developer fixing a review blocker knows where its files end; conformance does not compare
# these (PROTECTED_PATHS and the seam are what it enforces).
TEMPLATE_SOURCE = (
    ("src/core/", "configuration, the game config, i18n and the verify probe"),
    ("src/platform/bind.ts", "the template's platform binding; the Factory's seam wiring "
                             "imports it"),
    ("src/rendering/create-renderer.ts", "the engine selector"),
    ("src/types/", "the template's type declarations"),
)

# Protected paths conformance compares by content rather than refusing any change to: a
# dependency may be added to package.json (factory.develop.allowed_package_changes), and the
# lockfile then follows it (checks.package_findings).
STRUCTURAL_PATHS = (contract.PACKAGE_JSON, contract.PNPM_LOCK)

# src/rendering/<engine>, per engine the template contract knows.
ENGINE_DIRS = {engine: contract.rendering_dir(engine).rstrip("/") for engine in contract.ENGINES}


def framework_package(engine):
    """The npm name of an engine's renderer package, packages/<name>/ in the template."""
    return "@wgf/" + contract.renderer_package(engine).rstrip("/").rsplit("/", 1)[-1]


# The upstream library each engine's game code imports (not a template name).
ENGINE_LIBRARIES = {"pixijs": "pixi.js", "phaserjs": "phaser", "threejs": "three"}

INTEGRATION_CONTRACT = """\
// src/game/integration.ts - the seam the integration (SDK) module wires. Game code calls
// these; it never calls a Platform method or a portal SDK directly.
import type { EventProperties } from "@wgf/analytics-sdk";

export interface GameIntegration {
  /** Gameplay started or resumed / stopped (menus, game over, pause). */
  gameplayStart(): void;
  gameplayStop(): void;
  /** Whether a rewarded placement can be offered right now. Hide the offer when false. */
  canOfferRewarded(placement: string): boolean;
  /** Resolves true only when the reward must be granted. Never grant on anything else. */
  rewarded(placement: string): Promise<boolean>;
  /** A natural break. Resolves when play may continue, whether or not an ad showed. */
  interstitial(placement: string): Promise<void>;
  /** One analytics vocabulary; where it lands is wiring, not game code. */
  track(event: string, properties?: EventProperties): void;
  /** Persistence. Backed by cloud saves where the platform has them. */
  load(key: string): Promise<string | null>;
  save(key: string, value: string): Promise<void>;
}
"""

REPORT_CONTRACT = {
    "engine": "pixijs | phaserjs | threejs",
    "systems": {name: "done | partial | missing" for name, _ in REQUIRED_SYSTEMS},
    "mvp": [{"item": "<exactly as listed in the brief>", "status": "built | partial | cut | "
             "deferred", "notes": "..."}],
    "placements": [{"id": "<placement id passed to the seam>", "kind": "rewarded | "
                    "interstitial | banner", "trigger": "<the design's trigger>"}],
    "integration_status": {"platform_sdk": "working | partial | not-started",
                           "monetization": "...", "analytics": "...", "persistence": "..."},
    "assets": [{"id": "<asset-manifest item id>", "status": "integrated | placeholder | cut"}],
    "content_units": [{"id": "<a content unit id from the brief's table>",
                       "status": "built | partial | cut", "notes": "..."}],
    "design_gaps": [{"field": "<path into the game-design, e.g. "
                              "build_spec.content.units[l-03].success>",
                     "question": "<what you needed to know, as the designer can answer it>",
                     "assumed": "<what you built instead, or null>",
                     "severity": "blocking | minor"}],
    "scope_deltas": [{"item": "...", "direction": "added | cut | deferred", "reason": "..."}],
    "known_issues": ["..."],
    # Only for a change the review's gate-gaming pre-check would flag that the player does
    # experience (docs/review-module.md#gate-gaming-pre-check); omit otherwise.
    "measurement_changes": [{"flag": "unread-content-field | play-area-change | "
                                     "probe-path-change | sprite-size-without-collider",
                             "where": "<file, or file#key>",
                             "evidence": [{"file": "<repository path>", "line": 1}],
                             "player_effect": "<what the player sees or does differently>"}],
    "how_to_play": "One or two sentences a reviewer reads before opening the build.",
}

# build_spec sections the brief carries, in reading order. Two are left out on purpose:
# `sdk_touchpoints` belong to the sdk step (ground rule 4: no platform SDK work here), and
# `assets` are delivered through the asset manifest, which the brief lists on its own.
BUILD_SPEC_SECTIONS = (
    # First: what a first-time player must be able to tell, and how fast. The rest of the
    # spec is how; this is what the build is measured against from outside. Then the content
    # the player meets, because that is what the rest of the spec exists to serve.
    ("experience", "Player experience contract"),
    ("content", "Content units"),
    ("mechanics", "Mechanics"), ("controls", "Controls"), ("player_goals", "Player goals"),
    ("game_states", "Game states"), ("screens", "Screens"), ("hud", "HUD"),
    ("menus", "Menus"), ("tutorial", "Tutorial"), ("rewards", "Rewards"),
    ("failure", "Failure and retry"), ("progression", "Progression"),
    ("difficulty", "Difficulty"), ("mastery", "Mastery"), ("session_flow", "Session flow"),
    ("monetization_touchpoints", "Monetization touchpoints"), ("audio", "Audio"),
    ("responsive", "Responsive"), ("visual_identity", "Visual identity"),
    # Last, and no longer dropped: what brings a player back. The design has carried it
    # since 1.7.0 and no brief did.
    ("depth", "Depth (reason to return)"),
)
# Sections the brief gives a section of their own, with the table, the axes and the data-file
# contract the generic renderer cannot express. The build-spec listing points at them instead
# of repeating every unit twice in one document.
SPEC_SECTIONS_RENDERED_ABOVE = {"content": "Content units", "mastery": "Mastery"}
BUILD_TIERS = (None, "mvp")
DEV_PLAN_PHASES = (None, "prototype")


def build_scope(tech_plan):
    """{"quality_tier", "tiers", "phases"} the run builds, from the approved tech plan's
    `dev_plan.build_scope`; the MVP (BUILD_TIERS, DEV_PLAN_PHASES) without one."""
    scope = (((tech_plan or {}).get("dev_plan") or {}).get("build_scope") or {})
    tiers = content_contract.built_tiers(tech_plan)
    phases = scope.get("plan_phases") if isinstance(scope, dict) else None
    phases = ((None,) + tuple(str(p) for p in phases)
              if isinstance(phases, list) and phases else DEV_PLAN_PHASES)
    return {"quality_tier": (scope.get("quality_tier") if isinstance(scope, dict) else None)
            or "mvp", "tiers": tiers, "phases": phases}

# Host skills the brief recommends, by area. The `web-game-factory:` names are this Factory's
# own plugin (claude-web-game-plugin), pointers into core/craft/; a host that loads the plugin
# (the opt-in self-playtest developer passes --plugin-dir) has them. The generic ones are for
# any host. The other engine's area is never recommended.
PLUGIN = "web-game-factory"
DEFAULT_SKILLS = {
    "pixijs": [f"{PLUGIN}:pixijs", f"{PLUGIN}:production-art-2d",
               "the official PixiJS skills"],
    "phaserjs": [f"{PLUGIN}:phaser", f"{PLUGIN}:production-art-2d", "the Phaser Game Agent skill, for Phaser API knowledge "
                 "and its reusable games and blocks - read them, never let them write this "
                 "repository: they target their own project layout, not the template's"],
    "threejs": [f"{PLUGIN}:threejs", f"{PLUGIN}:production-art-3d",
                "a Three.js game-development skill"],
    "ui": [f"{PLUGIN}:onboarding-ux", f"{PLUGIN}:game-ui-kit",
           "a frontend-design skill, for menus, HUD and screens"],
    "craft": [f"{PLUGIN}:game-feel", f"{PLUGIN}:juice", f"{PLUGIN}:core-loop",
              f"{PLUGIN}:web-performance", f"{PLUGIN}:audio", f"{PLUGIN}:production-wiring"],
}


# Engine-specific ground truth, for the engine whose template surface does not carry it.
# `packages/three-framework` is a WebGL renderer, one scene and one camera: a 3D game writes
# its whole runtime - loaders, camera rigs, animation, disposal - itself, while a 2D game
# gets a complete 2D surface from its binding. Each line points at a craft playbook rather
# than restating it; the physics line is not here because it is quoted from the tech plan.
ENGINE_NOTES = {
    "phaserjs": [
        "**The loop is not Phaser's.** `PhaserRenderer` (`@wgf/phaser-framework`) boots "
        "`Phaser.Game`, stops its `TimeStep` immediately and steps Phaser once per drawn "
        "frame from `render()`. `@wgf/game-core` owns the fixed simulation step, pause by "
        "reason and the scene the game is in. Never call `game.loop.start()` or `game.step()` "
        "yourself: two loops make the simulation and the drawing disagree about elapsed time, "
        "and the bug only shows under load.",
        "**What goes where.** Gameplay that must be deterministic - scoring, spawn timers, "
        "difficulty ramps - lives in game-core's fixed `update(stepMs)`. Phaser scene "
        "`update(time, delta)` is presentation: input state, tweens, animation. Multiply by "
        "`delta`, never by a constant per frame.",
        "**Pause is game-core's.** `Game.pause(reason)` stops calling `render()`, which stops "
        "stepping Phaser, which stops tweens, physics and animations together. Do not add a "
        "second pause flag inside a scene.",
        "**Scenes leak on restart unless you release them.** On `shutdown`, clear timers "
        "(`this.time.removeAllEvents()`), tweens (`this.tweens.killAll()`), the input "
        "handlers the scene added, and anything it put on the registry or on `game.events`. "
        "Play, die and restart ten times and watch the frame rate and the heap stay flat.",
        "**Prove the canvas renders.** A Phaser build with no scene added draws a blank "
        "canvas, still boots and still advances `#hud[data-steps]`, so the browser test has "
        "to say otherwise - see Tests below.",
    ],
    "threejs": [
        "**What the template already gives you.** `ThreeRenderer` (`@wgf/three-framework`) "
        "owns the WebGL renderer, the scene, the perspective camera, the pixel-ratio cap, "
        "resize, render and destroy. Import it. Never construct a second renderer, and never "
        "raise the pixel-ratio cap - it is what keeps a phone's native ratio inside the frame "
        "budget. Everything else is yours: loaders, camera rig, entities, animation, "
        "disposal, diagnostics.",
        "**One update order, written in one place**: input intents, then the fixed-step "
        "simulation behind a clamped accumulator, then game state and collisions, then VFX, "
        "camera and UI, then render. Transforms reach meshes in exactly one system - two "
        "writers is how a mesh and its collider drift apart over a session.",
        "**Models and clips.** Load GLB/glTF only from the asset paths listed below. Decoder "
        "files for compressed meshes and textures are bundle payload, so configure them once "
        "and count them. After import, check scale against world units, pivot, orientation, "
        "material count and clip names before wiring anything; simulate against a collision "
        "proxy, never the visual mesh. A loader failure is an error you surface, never a "
        "swallowed rejection - that is how a build boots happily and renders nothing.",
        "**Restart releases everything** it created: geometries, materials, textures, render "
        "targets, animation mixers, physics bodies, listeners. Heap after ten restarts should "
        "look like heap after one.",
        "**Prove the canvas renders.** A 3D build that draws nothing still boots, still "
        "advances `#hud[data-steps]` and still passes every other check, so the browser test "
        "has to say otherwise - see Tests below.",
    ],
}
# The physics line when the run holds no tech plan. The default the tech plan itself writes.
PHYSICS_FALLBACK = ("No tech plan in this run, so no physics library is planned: use custom "
                    "collision and overlap tests in `src/game/`. If the MVP genuinely needs "
                    "a simulation, say so in `known_issues` - adding one is a superseding "
                    "tech plan at G3, not this step's decision.")


def _physics_note(tech_plan):
    """The tech plan's `architecture.physics`, verbatim, with the rule that goes with it."""
    planned = ((tech_plan or {}).get("architecture") or {}).get("physics")
    if not isinstance(planned, str) or not planned.strip():
        return PHYSICS_FALLBACK
    return (planned.strip() + " That is the approved plan: add a physics package only if the "
            "line above names one, and then only that one.")


def _pin(artifact_type, content, ref):
    provenance = (content or {}).get("provenance") or {}
    return {
        "artifact_type": artifact_type,
        "artifact_id": provenance.get("artifact_id"),
        "content_hash": getattr(ref, "content_hash", None) or provenance.get("content_hash"),
    }


def _label(item):
    return item.get("id") or item.get("label") or item.get("name") or "?"


def _mvp_only(value, dropped, path, tiers=BUILD_TIERS):
    """`value` without the entries tiered past `tiers` (the MVP by default), at any depth.
    Each dropped entry is named in `dropped` by its path (e.g. `menus/title-menu/items/
    Settings (post-mvp)`), so the brief can say it is left out on purpose rather than
    forgotten."""
    if isinstance(value, dict):
        return {k: _mvp_only(v, dropped, f"{path}/{k}", tiers) for k, v in value.items()}
    if isinstance(value, list):
        kept = []
        for item in value:
            if not isinstance(item, dict):
                kept.append(item)
            elif item.get("tier") not in tiers:
                dropped.append(f"{path}/{_label(item)} ({item['tier']})")
            else:
                kept.append(_mvp_only(item, dropped, f"{path}/{_label(item)}", tiers))
        return kept
    return value


def select_build_spec(design, tiers=BUILD_TIERS):
    """The design's build_spec as the developer builds it: the tiers built (the MVP by
    default), in reading order."""
    spec = (design or {}).get("build_spec")
    if not isinstance(spec, dict):
        return None
    dropped = []
    sections = {key: _mvp_only(spec[key], dropped, key, tiers)
                for key, _ in BUILD_SPEC_SECTIONS if key in spec}
    return {"sections": sections, "not_now": dropped,
            "omitted": [k for k in ("sdk_touchpoints", "assets") if k in spec]}


def select_content(design, tiers=BUILD_TIERS):
    """The content the build owes - the units of `tiers`, the MVP by default - as the
    developer builds it (see content.py).

    `applies` is the content contract: an authored design with at least one unit of `tiers`
    owes `public/content/units.json` holding exactly those units. A parametric or procedural
    design states the same table - the units it commits to - but generates the rest from
    `generation.parameters`, so there is no list to compare a file against and no file is
    owed."""
    spec = (design or {}).get("build_spec") or {}
    content = spec.get("content") if isinstance(spec.get("content"), dict) else {}
    axes = [a for a in (spec.get("difficulty") or {}).get("axes") or [] if isinstance(a, dict)]
    return {
        "applies": content_contract.applies(design, tiers),
        "unit_kind": content.get("unit_kind"),
        "generation": content.get("generation") or None,
        "units": content_contract.expected_units(design, tiers),
        # Units of a later tier: named so the developer knows they exist and does not build
        # them, the way the build spec's `not_now` works.
        "later": [u.get("id") for u in content.get("units") or []
                  if isinstance(u, dict) and u.get("tier") not in tiers],
        "axes": axes,
        "file": CONTENT_PATH,
        "test": TEST_PATH,
    }


def select_production_art(design, assets=None, tiers=BUILD_TIERS):
    """The design's production art (game-design 1.6.0) as the developer draws it.

    Each MVP asset requirement in the design's `build_spec.assets` with its role, dimension
    and readability, and the runtime asset id that draws it - the requirement's own id, which
    is the asset-manifest item's and `public/assets/assets.json`'s key. `delivered` says
    whether the asset manifest holds that item (None when there is no manifest yet)."""
    spec = (design or {}).get("build_spec")
    if not isinstance(spec, dict):
        return None
    look = spec.get("visual_identity") or {}
    manifest = {item.get("id") for item in (assets or {}).get("items") or []
                if item.get("status") != "cut"} if assets else None
    requirements = [
        {"id": a.get("id"), "type": a.get("type"), "role": a.get("role"),
         "dimension": a.get("dimension"), "readability": a.get("readability"),
         "description": a.get("description"), "spec": a.get("spec"),
         "runtime_asset": a.get("id"),
         "delivered": (a.get("id") in manifest) if manifest is not None else None}
        for a in spec.get("assets") or [] if a.get("tier") in tiers
    ]
    sounds = [
        {"id": a.get("id"), "type": a.get("type"), "loop": bool(a.get("loop")),
         "trigger": a.get("trigger"), "description": a.get("description"),
         "runtime_asset": a.get("id"),
         "delivered": (a.get("id") in manifest) if manifest is not None else None}
        for a in spec.get("audio") or [] if isinstance(a, dict) and a.get("tier") in tiers
    ]
    if not requirements and not look:
        return None
    primitive = look.get("primitive_style")
    return {
        "assets": requirements,
        "audio": sounds,
        # The play probe's roles a player must read (core/reference/visual-quality.yaml).
        "readable_roles": list(READABLE_ROLES),
        "primitive_style": dict(primitive) if isinstance(primitive, dict) else None,
        "ui": look.get("ui"),
        "palette": {p.get("token"): p.get("hex") for p in look.get("palette") or []},
        "typography": look.get("typography"),
        "result_screens": [
            {"id": sc.get("id"), "state": sc.get("state"),
             "actions": [a.get("label") for a in sc.get("actions") or []]}
            for sc in spec.get("screens") or []
            if sc.get("tier") in tiers and sc.get("id") in ("result", "level-complete")
        ],
    }


def _dependency_order(tasks):
    """Tasks in dependency order, stable otherwise. A dependency outside the list (a task of
    another phase) does not hold a task back; a cycle keeps the plan's own order."""
    ids = {t.get("id") for t in tasks}
    placed, ordered, pending = set(), [], list(tasks)
    while pending:
        ready = [t for t in pending
                 if all(d in placed or d not in ids for d in t.get("dependencies") or [])]
        if not ready:
            ordered.extend(pending)
            break
        for task in ready:
            ordered.append(task)
            placed.add(task.get("id"))
        pending = [t for t in pending if t not in ready]
    return ordered


def select_dev_plan(tech_plan):
    """The approved plan's milestones and tasks of the phases the run builds before G4
    (`dev_plan.build_scope.plan_phases`: the prototype phase at `mvp`, prototype and
    production at `release`). Hardening (platform tasks, the verify suite) belongs to later
    steps."""
    plan = (tech_plan or {}).get("dev_plan")
    if not isinstance(plan, dict):
        return None
    phases = build_scope(tech_plan)["phases"]
    milestones = [m for m in plan.get("milestones") or [] if m.get("phase") in phases]
    in_scope = {m.get("id") for m in milestones}
    tasks = [
        {k: t[k] for k in ("id", "title", "milestone", "description", "dependencies",
                           "acceptance_criteria", "tests", "assets") if t.get(k)}
        for t in plan.get("tasks") or []
        if t.get("milestone") in in_scope and t.get("phase") in phases
    ]
    return {
        "milestones": [{k: m[k] for k in ("id", "label", "exit_criteria") if m.get(k)}
                       for m in milestones],
        "tasks": _dependency_order(tasks),
        "later": sorted({t.get("id") for t in plan.get("tasks") or []}
                        - {t["id"] for t in tasks} - {None}),
    }


def existing_floor(design):
    """The brief's `existing_content`: what the adopted repository already ships, counted at
    its commit (game-design existing_content - or the probe floor develop resolved into it),
    or None when the run adopted nothing."""
    floor = (design or {}).get("existing_content")
    if not isinstance(floor, dict):
        return None
    source = floor.get("source") or {}
    unmeasured = floor.get("status") == "unmeasured"
    rule = ("This repository already ships a game. Improve it; never rebuild it: no "
            "commit may ship fewer units, groups, climax units or elements than the "
            "floor, and no shipped unit, asset file or feature is deleted or "
            "replaced by a primitive unless a finding in this brief asks for "
            "exactly that change.")
    if unmeasured or source.get("method") == "probe":
        rule += (" Its content lives in source code, not in a content data file: until a "
                 "content data file counts it, no commit may delete a shipped source file "
                 "of a content module (the files whose path names its levels, worlds, "
                 "courses, stages or content).")
    return {"commit": source.get("commit"),
            "path": source.get("path"),
            "method": source.get("method") or "content-data",
            "status": "unmeasured" if unmeasured else "measured",
            "floor": {q: floor[q] for q in ("units", "groups", "climax_units", "elements")
                      if isinstance(floor.get(q), int)},
            "unit_ids": list(floor.get("unit_ids") or []),
            "rule": rule}


def build_brief(*, title_id, engine, iteration, key, baseline, design, assets, scaffold,
                strategy=None, qa=None, previous_checks=None, refs=None, skills=None,
                review=None, mobile_test=True, tech_plan=None, self_playtest=False,
                writable_paths=None, package_changes=None, loop=None, sessions=None,
                playability=None, frames_root=None, phase=None, greybox_commit=None,
                production=None, visual_qa=None, sufficiency=None,
                review_baseline=None, developer=None, specialist=None):
    """The brief as data. `render_markdown` turns it into the document a developer reads."""
    refs = refs or {}
    writable_paths = list(DEFAULT_WRITABLE if writable_paths is None else writable_paths)
    package_changes = package_changes or {}
    tiers = (design.get("scope") or {}).get("tiers") or {}
    monetization = design.get("monetization") or {}
    placements = [
        {"kind": p.get("kind"), "trigger": p.get("trigger"),
         "player_value": p.get("player_value")}
        for p in monetization.get("placements") or []
        if p.get("kind") != "iap"
    ]
    # Each item's delivered files, as the manifest records them: paths relative to the game
    # repository root (public/assets/... when the assets step wrote into the checkout), so
    # the developer loads exactly those files and the development commit carries them.
    asset_items = [
        dict({k: item.get(k) for k in ("id", "label", "type", "source", "status", "license",
                                       "scope_tier", "notes") if item.get(k) is not None},
             **({"files": [f["path"] for f in item.get("files") or []
                           if isinstance(f, dict) and isinstance(f.get("path"), str)]}
                if item.get("files") else {}))
        for item in (assets or {}).get("items") or []
        if item.get("status") != "cut" and item.get("scope_tier") in (None, "mvp", "prototype")
    ]
    defects = []
    for defect in (qa or {}).get("blocking_defects") or []:
        defects.append({k: defect.get(k) for k in ("id", "severity", "summary", "repro")
                        if defect.get(k)})
    # A review that requested changes to the commit this visit starts from: its blockers
    # are the first thing to fix. The step decides whether a review applies; this only
    # carries what it was given.
    review_blockers = [
        {k: blocker.get(k) for k in ("id", "file", "line", "summary", "severity")
         if blocker.get(k) is not None}
        for blocker in (review or {}).get("blockers") or []
    ]
    # A playability-report that failed the commit this visit starts from: what the bot saw,
    # per failed check, with the frames that show it (absolute paths under frames_root, the
    # run's directory, which the report's frame paths are relative to).
    frame_paths = {(f.get("project"), f.get("id")): f.get("path")
                   for f in (playability or {}).get("frames") or []}
    playability_failures = [
        {"check": c.get("id"), "project": c.get("project"), "summary": c.get("summary"),
         "expected": c.get("expected"),
         "frames": [os.path.join(frames_root, frame_paths[(c.get("project"), f)])
                    if frames_root and frame_paths.get((c.get("project"), f)) else f
                    for f in c.get("frames") or []]}
        for c in (playability or {}).get("checks") or []
        if c.get("required") and c.get("status") == "FAIL"
    ]
    # The production gates' failures of the commit this visit starts from: each failed
    # production-quality check (with the route it took: an `assets` failure was rebuilt by
    # the assets step before this visit, and its integration is this visit's) and the frames
    # it measured, resolved through the playability-report it judged; and visual QA's
    # failures - blocker findings, low scores with the judge's reasons, per-state answers
    # with its comments and frames, the look with its reason - and its major findings.
    production_failures = [
        {"check": c.get("id"), "project": c.get("project"), "route": c.get("route"),
         "summary": c.get("summary"), "expected": c.get("expected"),
         "measured": c.get("measured"),
         "assets": c.get("assets") or None,
         "frames": [os.path.join(frames_root, frame_paths[(c.get("project"), f)])
                    if frames_root and frame_paths.get((c.get("project"), f)) else f
                    for f in c.get("frames") or []] or None}
        for c in (production or {}).get("checks") or []
        if c.get("required") and c.get("status") == "FAIL"
    ]
    visual_qa_failures = _visual_qa_failures(visual_qa, frames_root)
    # The content-sufficiency step's findings on the commit this visit starts from that the
    # build owes (route `develop`): the design meets its tier's bar, the build does not.
    sufficiency_failures = [
        {k: f.get(k) for k in ("check", "severity", "owner", "summary", "observed", "bar")
         if f.get(k) is not None}
        for f in (sufficiency or {}).get("findings") or []
        if isinstance(f, dict) and f.get("route") == "develop" and f.get("severity") != "minor"
    ]
    failures = [
        {"check": c.get("id"), "summary": c.get("summary"), "output_tail": c.get("output_tail")}
        for c in (previous_checks or {}).get("checks") or []
        # A skip the run's tier held against the build is not passed either: its finding
        # names what was missing.
        if c.get("status") == "failed" or c.get("blocking")
    ]
    host_skills = dict(DEFAULT_SKILLS)
    host_skills.update(skills or {})

    session = design.get("session") or {}
    ux = design.get("ux") or {}
    scope_block = design.get("scope") or {}
    scope = build_scope(tech_plan)
    builds_production = "post-mvp" in scope["tiers"]
    return {
        "format": 1,
        "title_id": title_id,
        "iteration": iteration,
        "idempotency_key": key,
        "baseline_commit": baseline,
        # Where review's change starts (step._review_baseline): the baseline, or - after a
        # greybox, which nobody reviewed - where the greybox started.
        "review_baseline": review_baseline or baseline,
        "engine": engine,
        "engine_dir": ENGINE_DIRS[engine],
        # What this engine needs said that the template does not carry, plus the physics
        # approach the tech plan approved at G3. None for an engine whose binding is a
        # complete surface, so nothing about the 2D brief changes.
        "engine_notes": ({"notes": list(ENGINE_NOTES[engine]),
                          "physics": _physics_note(tech_plan)}
                         if engine in ENGINE_NOTES else None),
        "inputs": [
            _pin(t, c, refs.get(t))
            for t, c in (("game-design", design), ("asset-manifest", assets),
                         ("scaffold-record", scaffold), ("title-strategy", strategy),
                         ("tech-plan", tech_plan), ("qa-report", qa),
                         ("review-report", review), ("playability-report", playability),
                         ("production-quality-report", production),
                         ("visual-qa-report", visual_qa),
                         ("content-sufficiency-report", sufficiency))
            if c
        ],
        "design": {
            "fantasy": design.get("fantasy"),
            "core_loop": design.get("core_loop"),
            "pillars": design.get("pillars") or [],
            "controls": design.get("controls"),
            "difficulty": design.get("difficulty"),
            "progression": design.get("progression"),
            "progression_terminal": (design.get("scope") or {}).get("progression_terminal"),
            "session": {k: session.get(k) for k in (
                "time_to_first_play_s", "time_to_first_reward_s", "target_seconds",
                "structure", "end_condition") if session.get(k) is not None},
            "onboarding": ux.get("onboarding"),
            "screens": ux.get("screens") or [],
            "accessibility": ux.get("accessibility"),
            "art_direction": design.get("art_direction"),
            "audio_direction": design.get("audio_direction"),
            "locales": scope_block.get("locales") or [],
            # What the design says the game is made of, in its own words: the count and the
            # name. The content table is the same thing, unit by unit.
            "scope_content_units": scope_block.get("content_units"),
            "content_unit_kind": scope_block.get("content_unit_kind"),
        },
        # The family of core/reference/genre-models.yaml the design is held to: the unit
        # kinds, axes and win/loss shapes that fit it. None before game-design 1.9.0.
        "genre": design.get("genre") if isinstance(design.get("genre"), dict) else None,
        # What the run builds before G4 (the tech plan's dev_plan.build_scope): its quality
        # tier, and whether the post-mvp tier is part of this build.
        "build_scope": {"quality_tier": scope["quality_tier"],
                        "design_tiers": [t for t in scope["tiers"] if t],
                        "plan_phases": [p for p in scope["phases"] if p]},
        # Every unit of content the build owes, and whether a data file is owed with it.
        "content": select_content(design, scope["tiers"]),
        "mvp": list(tiers.get("mvp") or []),
        "prototype_tier": list(tiers.get("prototype") or []),
        # The production tier, when the run's quality tier builds it before G4.
        "release_scope": list(tiers.get("production") or []) if builds_production else [],
        "not_now": (([] if builds_production else list(tiers.get("production") or []))
                    + list(tiers.get("future") or [])),
        "out_of_scope": [o.get("item") for o in tiers.get("out_of_scope") or []],
        "must_prove": list((strategy or {}).get("prototype_must_prove") or []),
        # What the design and the approved plan hand over in detail; None when the design
        # carries no build_spec (an older schema) or the run holds no tech plan.
        "build_spec": select_build_spec(design, scope["tiers"]),
        "dev_plan": select_dev_plan(tech_plan),
        "placements": placements,
        "assets": asset_items,
        # The runtime asset manifest the assets step wrote (public/assets/assets.json): what
        # game code loads assets through. None when the manifest records none.
        "runtime_assets": ((assets or {}).get("runtime_manifest") or {}).get("path"),
        "required_systems": [{"id": n, "acceptance": a} for n, a in REQUIRED_SYSTEMS],
        "protected_paths": list(PROTECTED_PATHS),
        # Inside the writable paths but not the developer's: the template's own source and
        # the Factory's seam. Guidance for the developer (the seam is also enforced).
        "template_source": [{"path": p, "why": why} for p, why in TEMPLATE_SOURCE],
        "factory_owned": [gameseam.CONTRACT_PATH, gameseam.WIRING_PATH],
        # Written whole by the sdk step on every run: enforced by conformance
        # (seam.sdk_owned_findings), stated here so a developer never puts work in them.
        "sdk_owned": list(gameseam.SDK_OWNED_PATHS),
        # What the development commit may contain (scope.py), and how package.json may
        # change (checks.package_findings). Anything else fails the step.
        "writable_paths": list(writable_paths),
        "package_changes": {k: list(v) for k, v in package_changes.items() if v},
        "qa_defects": defects,
        # greybox | production | None (one develop phase, as before workflow 4).
        "phase": phase,
        # The adopted repository's shipped content (game-design existing_content): the floor
        # no commit may drop below, and the rule that the game is improved, never rebuilt.
        # None when the run adopted nothing.
        "existing_content": existing_floor(design),
        # What the design says the finished game looks like: each MVP asset requirement's
        # role and readability with the runtime asset id that draws it, the UI spec, and
        # whether the art direction is geometric on purpose. None for a design without it.
        "production_art": select_production_art(design, assets, scope["tiers"]),
        "greybox_commit": greybox_commit,
        "playability_failures": playability_failures,
        "production_failures": production_failures,
        "visual_qa_failures": visual_qa_failures,
        "sufficiency_failures": sufficiency_failures,
        "sufficiency_commit": (sufficiency or {}).get("commit") if sufficiency_failures else None,
        "gated_commit": ((production if production_failures else None)
                         or (visual_qa if visual_qa_failures else None) or {}).get("commit"),
        "played_commit": (playability or {}).get("commit") if playability_failures else None,
        "review_blockers": review_blockers,
        "reviewed_commit": (review or {}).get("reviewed_commit") if review_blockers else None,
        "previous_failures": failures,
        # Which route brought the work back here, and what that route has left of its
        # visit budget (the engine's max_visits_by_route); None on a first visit.
        "loop": dict(loop) if loop else None,
        # The run's developer budget before this visit (wgf_develop.budget summary); None
        # when the run has none.
        "sessions": dict(sessions) if sessions else None,
        # Every area but another engine's: a configured area is recommended, not dropped.
        "skills": {k: list(v) for k, v in host_skills.items()
                   if v and not (k in ENGINE_DIRS and k != engine)},
        "report_path": REPORT_PATH,
        # A handoff visit's report must name this visit (its `visit` field), or conformance
        # fails it: nothing else rewrites report.json between handoff visits, and review read
        # an earlier visit's report as this one's (the Sky Marble run, 2026-10-04). None for
        # a command developer, whose report is checked as it always was.
        "report_visit": key if (developer or {}).get("kind") == "handoff" else None,
        "self_playtest": bool(self_playtest),
        # The unattended developer's shell: the Bash rules its argv allows and denies
        # (shell_contract); None for a handoff developer.
        "shell": shell_contract(developer),
        # How the developer sees what it built, and what "finished" looks like: the frame
        # tool, where its frames go (outside the checkout), and the installation's quality
        # bar for this engine's dimension (wgflib.quality_bar).
        "look": {"tool": LOOK_TOOL,
                 "out": f"{LOOK_OUT_ROOT}/" + "".join(
                     c if c.isalnum() or c in "._-" else "-" for c in str(key)),
                 "quality_bar": quality_bar.frames(
                     "3d" if engine == "threejs" else "2d"),
                 "qualities": quality_bar.qualities()},
        # A specialist visit reads its own playbooks (roles.yaml `reads`), not the full list.
        "craft_guides": ([factory_path(p) for p in specialist["playbooks"]] if specialist
                         else craft_guides(engine)),
        # The specialist this visit is briefed as (wgf_develop.specialist): its focus, the
        # findings it owns with their acceptance, its writable scope; None otherwise.
        "specialist": (dict(specialist, writable_paths=list(writable_paths))
                       if specialist else None),
        # What verification will demand browser evidence for (wgf_verification computes the
        # same set from the same design): the developer is told up front, instead of
        # learning it from a failed verification and a loop back here.
        "verification_aspects": {
            "vocabulary": list(ASPECTS),
            "required": [a for a in ASPECTS if a in required_aspects_for(design, mobile_test)],
        },
    }


def _inline(value):
    if isinstance(value, dict):
        return "; ".join(f"{k}: {_inline(v)}" for k, v in value.items()
                         if k != "tier" and v not in (None, "", [], {}))
    if isinstance(value, list):
        return " / ".join(_inline(v) for v in value)
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value)


def _spec_lines(value):
    """One build_spec section as markdown bullets: every field, nothing summarised."""
    lines = []
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                key = next((k for k in ("id", "name", "beat") if item.get(k)), None)
                label = item[key] if key else ""
                rest = {k: v for k, v in item.items() if k not in (key, "id", "tier")}
                lines.append(f"- **{label}**: {_inline(rest)}" if label
                             else f"- {_inline(rest)}")
            else:
                lines.append(f"- {_inline(item)}")
    elif isinstance(value, dict):
        for key, sub in value.items():
            if sub in (None, "", [], {}):
                continue
            if isinstance(sub, list) and sub and all(isinstance(x, dict) for x in sub):
                lines.append(f"- **{key}:**")
                lines.extend(f"  - {_inline(x)}" for x in sub)
            else:
                lines.append(f"- **{key}:** {_inline(sub)}")
    else:
        lines.append(f"- {_inline(value)}")
    return lines


def _package_rule(changes):
    """The one exception to package.json being protected, as the installation allows it."""
    verbs = {"add": "add", "change": "change the version of", "remove": "remove"}
    allowed = [f"{' or '.join(verbs[c] for c in kinds if c in verbs)} a `{field}` entry"
               for field, kinds in (changes or {}).items() if kinds]
    if not allowed:
        return ""
    return (" The one exception: you may " + "; ".join(allowed) + " in `package.json` - a "
            "registry version range, never a path, URL or protocol - and update "
            "`pnpm-lock.yaml` to match. Nothing else in either file may change: not "
            "`scripts`, not any other field.")


def _production_art_section(art, engine=None):
    """The production phase's art and UI contract, from the design's build_spec."""
    out = []
    add = out.append
    readable = art.get("readable_roles") or []
    primitive = art.get("primitive_style")
    add("## Production art and UI\n")
    add("What separates this build from the greybox: every thing a player reads is drawn by "
        "the asset the design names for it, and the interface is styled from the design's UI "
        "spec. The build is held to it from outside - the play probe's entities and the files "
        "the page fetched, measured screens, and a visual judge reading the frames. The craft "
        "behind it, distilled from the reference games and read before you draw or wire "
        "anything, is in the Factory: "
        + ", ".join(f"`{factory_path(path)}`" for path in production_craft(engine)) + ".\n")
    add("### Assets, by what they are to the player\n")
    add("Draw each with the runtime asset of that id (`public/assets/assets.json`), replacing "
        "the greybox primitive that stood for its role. The readability line is what the "
        "visual judge checks the drawn result against.\n")
    for a in art.get("assets") or []:
        role = a.get("role") or "unstated role"
        where = "" if a.get("delivered") is not False else " - not in the asset manifest yet"
        add(f"- **{a.get('id')}** ({role}, {a.get('dimension') or '?'}, {a.get('type')}): "
            f"draw with runtime asset `{a.get('runtime_asset')}`{where}."
            + (f" Readable as: {a['readability']}" if a.get("readability") else ""))
    add("")
    add("### The play probe in production\n")
    add("Every probe entity reports `asset` - the runtime asset id drawing it, or null - and "
        "`render`: `asset` (drawn from a manifest asset), `composite` (several assets "
        "together), `text`, or `primitive` (an engine box, sphere, capsule, plain rectangle "
        "or circle). `assets_loaded` lists every runtime asset id the game has loaded. "
        "Report what is drawn, never what should be: the production gate compares the probe "
        "with the files the page actually fetched.")
    if primitive:
        add(f"\nThe design's art direction is geometric on purpose "
            f"(visual_identity.primitive_style: {primitive.get('reason')}): readable entities "
            "may be drawn as primitives, styled from the palette, and reported "
            "`render: \"primitive\"`. The visual judge still reads them.\n")
    else:
        add("\n**No readable entity is drawn as a primitive.** An entity of role "
            + ", ".join(f"`{r}`" for r in readable)
            + " reports `render: \"asset\"` or `\"composite\"` with its `asset` set; a "
              "cube, sphere or flat rectangle standing for a character is a placeholder, and "
              "the production gate refuses it. A primitive may remain only where nothing a "
              "player reads is drawn (a floor plane under a textured surface, a hit box).\n")
    sounds = art.get("audio") or []
    if sounds:
        add("### Sound\n")
        add("Play each cue from the runtime asset of its id (`public/assets/assets.json`, type "
            "`music` or `sfx`; its `audio` block says whether it loops and how long it is), "
            "on its trigger. Load sound after the game is interactive, start nothing before "
            "the first input, and fall silent while paused, muted - the player's toggle or "
            "the platform's (`onAudioMutedChange`) - and during ads. Crossfade music between "
            "states and duck it under stings; keep music 6-10 dB under the effects. The play "
            "probe reports `audio`: `music` (the id playing), `playing`, and `level` - the RMS "
            "of the master output read from an AnalyserNode after every gain, so it is about "
            "0 when muted. The production gate hears the game through it (`audio.plays`). "
            f"The craft is `{factory_path(AUDIO_CRAFT)}` in the Factory.\n")
        for a in sounds:
            where = "" if a.get("delivered") is not False else " - not in the asset manifest yet"
            add(f"- **{a.get('id')}** ({a.get('type')}{', loops' if a.get('loop') else ''}): "
                f"{a.get('description') or ''} - plays on: {a.get('trigger') or 'unstated'}"
                f"{where}.")
        add("")
    ui = art.get("ui") or {}
    palette = art.get("palette") or {}
    typography = art.get("typography") or {}

    def token(name):
        return f"`{name}` ({palette[name]})" if name in palette else f"`{name}`"

    add("### The interface\n")
    if ui:
        fonts = ui.get("font_px") or {}
        button = ui.get("button") or {}
        if typography:
            add(f"- **Faces:** display {typography.get('display')}, body "
                f"{typography.get('body')}"
                + (f", numerals {typography['numeric']}" if typography.get("numeric") else "")
                + ".")
        fonts_assets = [a for a in art.get("assets") or []
                        if a.get("role") == "font" or a.get("type") == "font"]
        for font in fonts_assets:
            add(f"- **Fonts are production assets** (`{font['runtime_asset']}`). "
                + (f"{font['spec']} " if font.get("spec") else "")
                + "Declare each face with `@font-face` from its runtime asset url, await "
                  "`document.fonts.load` for every face before the first UI frame, and set "
                  "every button, HUD and result-screen element in it. The production gate "
                  "checks that `document.fonts.check` is true for each family and that the "
                  "computed `font-family` of buttons and HUD resolves to the bundled face; a "
                  "system fallback on screen fails it.")
        if fonts:
            add("- **Sizes (CSS px at the phone layout):** "
                + ", ".join(f"{k} {v}" for k, v in fonts.items()) + ". Nothing smaller.")
        if ui.get("min_target_px"):
            add(f"- **Touch targets:** every interactive element at least "
                f"{ui['min_target_px']} x {ui['min_target_px']} CSS px on a phone, none "
                "overlapping another or the HUD.")
        if button:
            add("- **Buttons:** fill " + token(button.get("fill")) + ", text "
                + token(button.get("text"))
                + (f", corner radius {button['radius_px']} px" if button.get("radius_px")
                   is not None else "")
                + (f". {button['style']}" if button.get("style") else "")
                + ". Idle, pressed and disabled states; no browser-default button survives.")
        if ui.get("surface"):
            add(f"- **Panels and result cards:** surface {token(ui['surface'])}.")
    else:
        add("- The design states no UI spec: style buttons and panels from the visual "
            "identity's palette and faces; never ship browser defaults.")
    results = art.get("result_screens") or []
    for screen in results:
        actions = ", ".join(a for a in screen.get("actions") or [] if a)
        add(f"- **Result screen `{screen['id']}`** (state `{screen.get('state')}`): the "
            f"outcome, the score against the best, and {actions or 'its actions'} - the "
            "retry the primary button, in the thumb zone, back in play within the "
            "experience contract's retry budget.")
    if not results:
        add("- **Result screens:** win and lose each end on a screen with the outcome, the "
            "score against the best, and Retry as the primary button.")
    add("- **Layout:** HUD inside the safe area, primary actions in the lower third on a "
        "phone, nothing interactive within 16 CSS px of an edge; the same screens re-flow, "
        "never crop, on desktop.")
    add("")
    return "\n".join(out)


def _md_cell(value):
    if value in (None, "", [], {}):
        return "-"
    return _inline(value).replace("|", "\\|").replace("\n", " ")


def _md_table(header, rows):
    out = ["| " + " | ".join(str(head) for head in header) + " |",
           "|" + "---|" * len(header)]
    out += ["| " + " | ".join(_md_cell(cell) for cell in row) + " |" for row in rows]
    return "\n".join(out)


# What a family's `qa` parameters oblige the BUILD to do (the rest parametrise the judge).
_QA_OBLIGATIONS = {
    "reset_in_unit": "A reset or retry input is offered DURING play (the probe lists it as an "
                     "input named reset, retry or restart) and returns the current unit to its "
                     "start state - progress, moves and board - without leaving the unit.",
    "checkpoint": "A loss inside a unit returns the player to the unit's last checkpoint with "
                  "the unit's progress kept (content.progress), not to the unit's start.",
    "resource_metric": "The probe reports metrics.{value}, the resource whose fall ends play; "
                       "bad play must drive it down.",
    "time_target_axis": "Each unit's parameters carry its time target, and a unit succeeds "
                        "only inside it (metrics.time <= the target).",
    "failure_state": "A loss is reachable in every unit that states a failure: bad play ends "
                     "in `lost`, with a retry.",
}


def _qa_obligations(family):
    """The obligations a family's `qa` block puts on the build, in the brief's words."""
    if not family:
        return []
    try:
        models = load_file(os.path.join(paths.REFERENCE, "genre-models.yaml"))
    except (OSError, ValueError):
        return []
    qa = ((models.get("families") or {}).get(family) or {}).get("qa") or {}
    lines = []
    for key, text in _QA_OBLIGATIONS.items():
        value = qa.get(key)
        if value is True or (value and not isinstance(value, bool)):
            lines.append(text.replace("{value}", str(value)))
    return lines


def _content_section(brief):
    """The content the build owes: the genre it is held to, every unit built in order with its
    acceptance, the axes difficulty is stated on, what mastery means, and - when the content
    contract applies - the data file the units live in.

    This is what stops a build of the first level being reported as the game. The units are
    the design's, by its ids and in its order; none of it is the developer's to invent."""
    content = brief.get("content") or {}
    genre = brief.get("genre") or {}
    units = content.get("units") or []
    generation = content.get("generation") or {}
    mode = generation.get("mode")
    kind = content.get("unit_kind") or "unit"
    spec_sections = (brief.get("build_spec") or {}).get("sections") or {}
    out = []
    add = out.append

    if genre:
        add("## Genre\n")
        add(f"**{genre.get('family') or '?'}**"
            + (f" (node: {genre['node']})" if genre.get("node") else "")
            + (f" - session profile `{genre['session_profile']}`"
               if genre.get("session_profile") else "")
            + (f", {genre['ending']}" if genre.get("ending") else "")
            + ". The unit kinds, difficulty axes, win and loss shapes and variety bars this "
              "family is held to are `core/reference/genre-models.yaml` in the Factory.\n")
        obligations = _qa_obligations(genre.get("family"))
        if obligations:
            add("The playability bot holds a build of this family to these, from the family's "
                "`qa` block - build them, they are checked from outside:\n")
            for line in obligations:
                add(f"- {line}\n")
            add("\n")

    if not units and not generation:
        return "\n".join(out)

    add("## Content units (build exactly these, in this order)\n")
    add(f"What the player meets, unit by unit; one unit is one **{kind}**. Build every row "
        "below, in this order, with the objective, mechanics and difficulty values the design "
        "gives. A build that carries the first unit and calls the rest more of the same is a "
        "build of a smaller game than the one reviewed. Where the design does not say enough "
        "to build a unit, make the smallest assumption, record it in the report's "
        "`design_gaps` with the field it concerns, and mark the unit `partial` - never invent "
        "a unit, a mechanic or a difficulty value.\n")
    if mode:
        add(f"Generation: **{mode}**"
            + (" - " + _inline(generation.get("parameters"))
               if generation.get("parameters") else "")
            + (f" (about {generation['expected_units']} units a session)"
               if generation.get("expected_units") else "") + ".\n")
    header, rows = content_contract.table_rows(units, content.get("axes"))
    add(_md_table(header, rows) + "\n")
    for unit in units:
        acceptance = unit.get("acceptance") or []
        variation = unit.get("variation_from_previous") or []
        if not (acceptance or variation or unit.get("start_state") or unit.get("end_state")):
            continue
        add(f"**{unit.get('id')}** ({kind} {unit.get('index')})"
            + (f" - starts from: {unit['start_state']}" if unit.get("start_state") else "")
            + (f"; ends: {unit['end_state']}" if unit.get("end_state") else "") + "\n")
        for line in acceptance:
            add(f"- {line}")
        if variation:
            add("- Differs from the previous unit in: " + ", ".join(variation)
                + " - a unit that changes only a number is not another unit.")
        add("")
    if content.get("later"):
        add("Not now: " + ", ".join(f"`{uid}`" for uid in content["later"] if uid)
            + " belong to a later tier. Do not build them.\n")

    axes = content.get("axes") or []
    if axes:
        add("## Difficulty axes\n")
        add("Every unit's difficulty is a value on each of these, and on nothing else. Expose "
            "the value in force now through the play probe as `metrics[\"difficulty.<id>\"]`, "
            "so the bot can see difficulty move.\n")
        for axis in axes:
            bounds = list(axis.get("range") or []) + [None, None]
            add(f"- **{axis.get('id')}** ({bounds[0]}..{bounds[1]}): "
                + (axis.get("description") or "the design states no description.")
                + (" Relief is allowed on it." if axis.get("relief_allowed") else ""))
        add("")

    mastery = spec_sections.get("mastery") or {}
    if mastery:
        add("## Mastery\n")
        add(f"What getting better means here (`{mastery.get('model')}`): "
            f"{mastery.get('statement')}\n")
        signals = [signal for signal in mastery.get("signals") or []]
        if signals:
            add("Show it: " + ", ".join(f"`{signal}`" for signal in signals)
                + " are HUD metrics, shown again on the result screen and persisted through "
                  "the integration seam so the next session starts from them.\n")

    add("### The units are data, not code\n")
    if content.get("applies"):
        add(f"Write every unit above into `{content.get('file')}` and load it at boot: the "
            f"game reads its content from that file, and nothing in `src/` hard-codes a unit. "
            f"`{content.get('test')}` is the unit test over it. The develop checks compare the "
            f"file with the design unit by unit and field by field - a missing unit, a changed "
            f"objective, group, structure, elements or objective kind, a difficulty value "
            f"further from the design than the genre's tolerance, or a mechanic parameter "
            f"missing from `tuning` each fails the step. Every row of the table is owed, the "
            f"later tiers' rows included when this run builds them: a build that ships a "
            f"subset fails.\n")
    else:
        add(f"`{content.get('file')}` and `{content.get('test')}` are optional for a "
            f"{mode or 'generated'} design: the units are generated from the parameters, so "
            f"there is no list to compare a file with. Keep every tuning value - the "
            f"generation parameters, and each mechanic's `parameters` - as data in one module "
            f"all the same, so a playtest changes a number and not the code.\n")
    design_pin = next((pin for pin in brief.get("inputs") or []
                       if pin.get("artifact_type") == "game-design"), {})
    add("```json\n" + json.dumps({
        "schema": content_contract.SCHEMA,
        "design": {"artifact_id": design_pin.get("id")
                   or "<the game-design artifact id pinned above>",
                   "content_hash": design_pin.get("content_hash")
                   or "<the game-design's full content hash>"},
        "genre": genre or {"family": "<the design's genre.family>"},
        "unit_kind": kind,
        "generation": generation or {"mode": "authored"},
        "units": [{"id": "<unit id>", "index": 1, "tier": "mvp",
                   **{field: (["<element id>"] if field == "elements"
                              else f"<the design's {field}>")
                      for field in content_contract.UNIT_FIELDS
                      if any(u.get(field) for u in units)},
                   "objective": "<as the table says>", "mechanics": ["<mechanic id>"],
                   "introduces": ["<mechanic id>"], "difficulty": {"<axis id>": 0.1},
                   "expected_duration_s": 45, "success": "<as the table says>",
                   "failure": "<as the table says>"}],
        "tuning": {"<mechanic id>": {"<parameter>": 0}},
    }, indent=2) + "\n```\n")
    return "\n".join(out)


def _bullets(items, empty="- (none)"):
    lines = [f"- {item}" for item in items if item]
    return "\n".join(lines) if lines else empty


def _ownership_section(brief):
    """Where the developer's files end. The writable paths say what the Factory commits;
    inside them sit the template's own source and the Factory's seam, which are not the
    developer's. A developer fixing review blockers otherwise "fixes" a missing or broken
    template file by writing it (the live loop did, v2.0.0)."""
    lines = ["## Which files are yours\n"]
    template_source = brief.get("template_source") or []
    factory_owned = brief.get("factory_owned") or []
    sdk_owned = brief.get("sdk_owned") or []
    writable = brief.get("writable_paths") or []
    if writable:
        lines.append("- **Yours:** " + ", ".join(f"`{p}`" for p in writable)
                     + (" - except the files below." if template_source or factory_owned
                        or sdk_owned else "."))
    if template_source:
        lines.append("- **The template's source - import it, never edit, delete or "
                     "recreate it:** "
                     + "; ".join(f"`{e['path']}` ({e['why']})" for e in template_source)
                     + ".")
    if factory_owned:
        lines.append("- **The Factory's integration seam - never edit it:** "
                     + ", ".join(f"`{p}`" for p in factory_owned)
                     + ". The checks compare both byte for byte.")
    if sdk_owned:
        lines.append("- **The Factory's sdk step - never create, edit or delete them:** "
                     + ", ".join(f"`{p}`" for p in sdk_owned)
                     + ". The sdk step writes each one whole every time it runs, so anything "
                     "you put in them is erased - a test you add there is deleted. Your own "
                     "code and tests go in files of your own (another name under "
                     "`tests/unit/`, for example), even when a review blocker points at one "
                     "of these files. The checks compare them with the commit this visit "
                     "started from.")
    content = brief.get("content") or {}
    if content.get("units") or content.get("generation"):
        if content.get("applies"):
            lines.append(f"- **The content contract's files, yours to write:** "
                         f"`{content['file']}` (every content unit of the table as data) and "
                         f"`{content['test']}` (the unit test over it). The develop checks "
                         f"read both: the data file is compared with the design unit by unit, "
                         f"and a build that hard-codes its units instead fails the step.")
        else:
            lines.append(f"- **The content contract's files:** `{content['file']}` and "
                         f"`{content['test']}` are yours, and optional for a parametric "
                         f"design - the units are generated, so there is no list to compare. "
                         f"Tuning still lives in data either way.")
    lines.append("- **`src/main.ts`** is yours to wire the game into, but it is the template's "
                 "boot sequence: keep its order (the `boot` system, and the integration seam "
                 "section below).")
    lines.append("- **Template-owned project files** (ground rule 3) are never yours; the "
                 "checks fail the step on any change to them.")
    if brief.get("shell") is not None:
        # An unattended session's file tools write only inside the checkout: $TMPDIR is
        # refused (live runs, 2026-10-03), so scratch has one place, and is removed.
        lines.append(f"- **Scratch files are `{SCRATCH}` only.** A throwaway script, probe "
                     "or experiment goes there (your file tools cannot write outside the "
                     "checkout), and you delete it before you write the report (*Your shell*, "
                     "above). Never in the repository root or any path above: one file left "
                     "outside the paths that are yours, even an untracked one, makes the "
                     "develop step refuse the whole commit.")
    else:
        lines.append("- **Scratch files never go in the checkout.** A throwaway script, probe "
                     "or experiment goes under `$TMPDIR` (or `/tmp`), never in the repository "
                     "root or any path above: one file left outside the paths that are yours, "
                     "even an untracked one, makes the develop step refuse the whole commit.")
    lines.append("- If something you need is missing from, or wrong in, a file that is not "
                 "yours, do not create or patch it: build what you can, and say what is "
                 "missing in the report's `known_issues`.\n")
    return "\n".join(lines)


def _visual_qa_failures(report, frames_root=None):
    """[{id, route, summary, frame, frames}] for each entry of a FAIL visual-qa-report's
    `failed` - a finding (its summary and frame), a dimension below the bar (with the judge's
    reason), a per-state answer (with the judge's comment on that state and its frames), the
    look (with its reason) - then each `major` finding that did not fail the build on its own
    (a real defect the judge saw: fix it too)."""
    if not report:
        return []
    findings = {f.get("id"): f for f in report.get("findings") or []}

    def where(path):
        return os.path.join(frames_root, path) if frames_root and path else path

    frames = {f.get("id"): f.get("path") for f in report.get("frames") or []}
    scores = report.get("scores") or {}
    reasons = report.get("score_reasons") or {}
    bar = (report.get("rubric") or {}).get("pass_bar")
    states = {(s.get("viewport"), s.get("state")): s for s in report.get("states") or []
              if isinstance(s, dict)}
    out = []
    for entry in report.get("failed") or []:
        kind, _, name = str(entry).partition(":")
        item = {"id": str(entry), "route": None, "summary": str(entry), "frame": None}
        if kind == "finding" and name in findings:
            finding = findings[name]
            frame = finding.get("frame")
            item.update(route=finding.get("route"),
                        summary=f"({finding.get('severity')}, {finding.get('category')}) "
                                f"{finding.get('summary')}",
                        frame=where(frames.get(frame)) or frame)
        elif kind == "score":
            item["summary"] = (f"`{name}` scored {scores.get(name)} of 5, below the rubric's "
                               f"bar{' of ' + str(bar) if bar is not None else ''}"
                               + (f". The judge: {reasons[name]}" if reasons.get(name)
                                  else ""))
        elif kind == "state":
            pair, _, question = name.rpartition(":")
            viewport, _, state = pair.partition("/")
            judged = states.get((viewport, state)) or {}
            item["summary"] = (f"on {viewport} {state}: the answer to `{question}` fails the "
                               "state"
                               + (f". The judge saw: {judged['comment']}"
                                  if judged.get("comment") else ""))
            shown = [where(frames.get(k)) or k for k in judged.get("frames") or []]
            if shown:
                item["frames"] = shown
        elif kind == "look":
            look = report.get("look") or {}
            item["summary"] = ("the build looks like a developer prototype, not a finished "
                               "game"
                               + (f". The judge: {look['reason']}" if look.get("reason")
                                  else ""))
        out.append(item)
    failed = {str(e) for e in report.get("failed") or []}
    for finding in report.get("findings") or []:
        if finding.get("severity") != "major" or f"finding:{finding.get('id')}" in failed:
            continue
        frame = finding.get("frame")
        out.append({"id": f"finding:{finding.get('id')}", "route": finding.get("route"),
                    "summary": f"(major, {finding.get('category')}; did not fail the build "
                               f"on its own) {finding.get('summary')}",
                    "frame": where(frames.get(frame)) or frame})
    return out


def _admits(allowed, program):
    """Whether a Bash rule in `allowed` admits some invocation of `program`."""
    return any(rule == program or rule.startswith(program + " ") for rule in allowed)


def _shell_section(shell):
    """The unattended developer's shell contract. A refused command is the host doing its
    job, not the end of the session: say so, say what is allowed, and say what to use
    instead - the Factory, not the developer, runs the checks of record and commits."""
    allowed, denied = shell.get("allowed") or [], shell.get("denied") or []
    out = []
    add = out.append
    add("## Your shell\n")
    add("Nobody watches this session and nobody can answer a question. The agent host "
        "refuses, without asking, every command its rules do not allow (\"denied ... don't "
        "ask mode\"). **A refused command is never a reason to stop.** It means: do the same "
        "thing another way, from the list below, and carry on. Ending the session to ask for "
        "a shell, a permission or a free port loses the whole attempt, because nobody reads "
        "the question.\n")
    if allowed:
        add("- **Allowed commands:** " + ", ".join(f"`{r}`" for r in allowed) + ". "
            + ("`pnpm <script>` runs the repository's scripts; `pnpm exec <tool>` runs a "
               "tool the checkout installed (`vitest`, `playwright`, `prettier`, `tsc`, and "
               "`node <file>`). " if _admits(allowed, "pnpm") else "")
            + "Nothing else runs.")
    else:
        add("- **Allowed commands:** none. Use the Read, Glob, Grep, Edit and Write tools.")
    if denied:
        add("- **Refused even when they look allowed:** "
            + ", ".join(f"`{r}`" for r in denied) + ".")
    habits = [p for p in SHELL_HABITS if not _admits(allowed, p)]
    add("- **One command per Bash call.** Every program on a command line must be allowed: "
        "`&&`, `;`, `||`, `&`, a subshell, a heredoc, or a pipe into a program that is not "
        "allowed refuses the whole line, even when its first command alone would run."
        + (" Not allowed here: " + ", ".join(f"`{p}`" for p in habits) + "." if habits
           else "")
        + " You are already in the checkout: use paths relative to it, never `cd`.")
    add("- **Read, list and search files** with the Read, Glob and Grep tools rather than "
        "the shell. **Change files** only with the Edit and Write tools, which write inside "
        "the checkout - never with the shell (`sed -i`, `python`, `node -e`, `cat >`, a "
        "redirect, `mv`, `cp`).")
    if _admits(allowed, "git clean"):
        add("- **Delete a file you created** with `git clean -f -- <path>`, one path per "
            "call, under the paths its rule names. To rename one, Write the new file and "
            "`git clean` the old one.")
    add(f"- **Scratch scripts** go in `{SCRATCH}` and nowhere else; run one with "
        "`pnpm exec node <path>`, and delete it before you write the report.")
    add("- **Processes and ports** (`netstat`, `kill`, `curl`) are out of reach. If a server "
        "will not start or a port is held, record it in the report's `known_issues` and "
        "finish everything else.")
    add("- **A refused file edit** inside the checkout: read the file again and retry with "
        "the path relative to the checkout.")
    add("- **The Factory runs the checks after you, and commits.** When your session ends it "
        "runs every check itself, fails the step on any that fails, and commits what passes. "
        "Run the checks you can; if one cannot run here, finish the work, say why in "
        "`known_issues`, and still write the report. A report with an honest gap is "
        "worth an attempt; a session that stopped early is not.\n")
    return "\n".join(out)


def _see_your_build(brief, look):
    """The section that gives the developer eyes: build, capture frames, open them, compare
    them with the quality bar, fix, repeat - from the first playable wiring on."""
    out = []
    add = out.append
    tool, where = look["tool"], look["out"]
    add("## See your build\n")
    add("You cannot judge a game you have not looked at, and nobody else will look at it "
        "before the gates do. The order of work is therefore:\n")
    add("1. **Make it draw first.** Before writing more than a handful of modules, wire "
        "`src/main.ts` to your game's scene so the core loop renders and takes input - "
        "the template's boot scene draws nothing. A build that has drawn nothing after "
        "your first hour of work is the most expensive failure there is.")
    add(f"2. **Look.** `pnpm build`, then `pnpm exec node {tool} --out {where}/<n>` "
        "(a new `<n>` each time: 1, 2, 3 ...). It serves `dist/` itself, plays the first "
        "seconds on a desktop (1280x720) and a phone (390x844) viewport, and writes "
        "`desktop-1-title.png`, `desktop-2-play.png`, `desktop-3-play-later.png`, the same "
        "for `mobile-`, and `look.json` (page errors, failed asset requests, the play "
        "probe's snapshots). Pass `--actions` to script other input, e.g. "
        "`--actions click:0.5x0.7,wait:500,key:ArrowLeft`. Feel is motion: "
        "`--burst <actions>` performs one more input during play and saves six frames 80 ms "
        "apart (`desktop-burst-0..5.png`) - what a player sees in the half second after "
        "acting. If those six frames are identical apart from a number, the action has no "
        "feedback yet (the craft's juice guide says what it needs).")
    add("3. **Open every frame** with your file-reading tool - they are images - and judge "
        "them as a player would, against the design's visual identity and the quality bar "
        "below: is the player obvious within a second? is the objective on screen? does "
        "anything look like a default (browser button, system font, flat grey, a cube "
        "standing for a character, an empty dark void)? does the phone frame fit? did the "
        "play frames change after input?")
    if brief.get("shell") is not None:
        add(f"   Need a probe of your own? Write it as `{SCRATCH}`, run it with "
            "`pnpm exec node <path>` (or `pnpm exec vitest run <path>` for a test), and "
            "delete it with `git clean -f -- <path>` before the report. A new file outside "
            "the writable paths is moved out of the checkout and costs the attempt.")
    else:
        add("   Need a probe of your own? Write scratch scripts under /tmp, never in the "
            "checkout. A new file outside the writable paths is moved out of the checkout "
            "and costs the attempt; one you created inside them and no longer want, delete "
            "with `git clean -f -- <path>` (src/, tests/ and public/ only).")
    add("4. **Fix and look again**, after every change a player would see. Look one last "
        "time before you write the report, and say in `known_issues` what the last frames "
        "still show that falls short of the bar.\n")
    bar = look.get("quality_bar") or []
    if bar:
        add("### The quality bar\n")
        add("Frames of finished games this installation holds its games to. Open them before "
            "you start and again before you finish. They set the **level of finish** - "
            "composition, hierarchy, density, one visual language - never the style: this "
            "game's look comes from its own design.\n")
        for frame in bar:
            add(f"- `{frame['path']}` ({frame.get('state')}): {frame.get('shows')}")
        add("")
    qualities = look.get("qualities") or []
    if qualities:
        add("What every frame of a finished game has:\n")
        for quality in qualities:
            add(f"- {quality}")
        add("")
    if brief.get("phase") == "greybox" and not brief.get("existing_content"):
        add("In this greybox phase the bar applies to composition, framing, hierarchy and "
            "readability - primitives and flat palette colours are expected, an unframed or "
            "empty scene is not.\n")
    return "\n".join(out) + "\n"


def render_markdown(brief):
    d = brief["design"]
    engine = brief["engine"]
    others = [e for e in contract.ENGINES if e != engine] or [engine]
    engine_pkg = ENGINE_LIBRARIES.get(engine, engine)
    framework = framework_package(engine)
    session = d.get("session") or {}
    out = []
    add = out.append

    add(f"# Development brief: {brief['title_id']} (iteration {brief['iteration']})\n")
    add("Written by the Factory's development module. This file is regenerated for every "
        "development visit; do not edit it. What you build is checked against "
        "`brief.json` beside it.\n")
    add(f"- Key: `{brief['idempotency_key']}`")
    add(f"- Started from commit: `{brief['baseline_commit'] or 'none'}`")
    for pin in brief["inputs"]:
        add(f"- Input: `{pin['artifact_type']}` {pin['artifact_id']} "
            f"({(pin['content_hash'] or '')[:19]})")
    add("")
    if brief.get("specialist"):
        out.extend(specialist_section.render(brief["specialist"]))

    add("## Goal\n")
    add("A genuinely playable game: a stranger opens the build, understands it without help, "
        "plays a full session, loses or finishes, and plays again. Build the MVP below and "
        "nothing past it.\n")

    adopted = brief.get("existing_content")
    if adopted:
        floor = adopted.get("floor") or {}
        add("## Adopted game: improve, never rebuild\n")
        at = str(adopted.get("commit") or "")[:12]
        counts = ", ".join(f"{n} {q.replace('_', ' ')}" for q, n in floor.items())
        if adopted.get("status") == "unmeasured":
            shipped = (f"This repository already ships a game at `{at}`, with no "
                       f"`{adopted.get('path')}`: its content lives in source code and has "
                       "not been counted yet (the shipped build is counted through the play "
                       "probe). Whatever it ships is the floor. ")
        elif adopted.get("method") == "probe":
            shipped = (f"This repository already ships a game: its build at `{at}`, played "
                       f"through the play probe, reached {counts}. That is the floor. ")
        else:
            shipped = (f"This repository already ships a game: `{adopted.get('path')}` at "
                       f"`{at}` holds {counts}. That is the floor. ")
        add(shipped + adopted["rule"] + " Units the design adds go beside "
            "the shipped ones; a shipped unit the design renames keeps its content. The "
            "commit is refused when the content data counts below the floor or a shipped "
            "asset file is gone.\n")
    if brief.get("phase") == "greybox" and adopted:
        add("## Phase: greybox (adopted game)\n")
        add("The greybox proves the loop plays and reads before assets are made. This game "
            "already has its production art, sound and content, so the greybox is applied to "
            "the build as it is - never by stripping it to primitives: keep every sprite, "
            "model, sound and content unit it ships. Add only what the experience contract "
            "asks and the build lacks (the play probe, the objective on screen, onboarding "
            "and its grace, the HUD, every action's acknowledgement), and fix what the "
            "playability failures below name. Report each probe entity with the `render` "
            "and `asset` it really has.\n")
    elif brief.get("phase") == "greybox":
        add("## Phase: greybox\n")
        add("This build proves the game before any asset exists. Build the whole MVP loop, "
            "playable end to end - start, the core loop, the objective, losing (and winning), "
            "retry - with primitive shapes, flat colours from the design's palette and plain "
            "text. No asset files: the asset manifest is made only after this build passes. "
            "Implement now what a first-time player needs to read the game: the play probe "
            "(*Play probe*, below), the objective on screen, the onboarding and its grace, "
            "the HUD and every action's acknowledgement. Light and frame the scene so what "
            "matters is plainly visible.\n")
        add("Primitives are expected here: report every probe entity with `render: "
            "\"primitive\"` (`\"text\"` for text) and `asset: null`, and `assets_loaded` as "
            "`[]`. Give each entity the role the design's asset requirements name (the "
            "*Production art and UI* the next phase draws), so the production build replaces "
            "the primitive standing for each role without renaming anything.\n")
        add("Structure is not art: the greybox builds every MVP content unit above, all of "
            "them, with primitives, so the bot can traverse them. A greybox that builds only "
            "the first unit fails `content.units_reachable`.\n")
        add("When you finish, the build is played from outside on a desktop and a mobile "
            "viewport and held to the experience contract; a build that fails comes back "
            "here with what was seen. Assets and polish come in the next phase, on top of "
            "this loop.\n")
    elif brief.get("phase") == "production":
        add("## Phase: production\n")
        add("The greybox"
            + (f" at `{brief['greybox_commit'][:12]}`" if brief.get("greybox_commit") else "")
            + " was played from outside and passed: the loop is playable and readable. This "
            "phase integrates the assets below and finishes the MVP on top of it. Keep every "
            "playability check passing - an asset that hides the player, darkens the scene or "
            "drops the objective from the screen is a regression - because the build is "
            "played again before review.\n")
        add("Every content unit stays reachable and in the design's order: integrate the "
            "assets per unit, and do not quietly drop a unit to make an asset fit. The "
            "content data file is not re-authored here - the units are the same units.\n")

    if brief.get("shell") is not None:
        add(_shell_section(brief["shell"]))

    look = brief.get("look")
    if look:
        add(_see_your_build(brief, look))

    add("## Ground rules\n")
    add(f"1. **Engine: `{engine}`**, from `game.config.yaml`. 2D is PixiJS or Phaser, 3D is "
        f"Three.js; the tech plan chose this one. Do not add another engine, a physics engine "
        f"that brings its own renderer, or "
        + " or ".join(f"`{e}`" for e in others) + ".")
    add(f"2. `{engine_pkg}` and `{framework}` are imported only under "
        f"`{brief['engine_dir']}/` (and by `src/rendering/create-renderer.ts`). Rules, state "
        f"and progression live in `src/game/` and never touch the engine. That includes "
        f"`src/main.ts`: it gets its renderer from `createRenderer`, and it no longer imports "
        f"or starts the template's `BootScene` - your first scene replaces it. The develop "
        f"checks fail the build on either.")
    add("3. The template is the infrastructure source of truth. Do not edit: "
        + ", ".join(f"`{p}`" for p in brief["protected_paths"])
        + ". If the template lacks something, stop and say so in `known_issues`; do not "
          "patch around it." + _package_rule(brief.get("package_changes")))
    if brief.get("writable_paths"):
        add("   **Write only under** "
            + ", ".join(f"`{p}`" for p in brief["writable_paths"])
            + ". The Factory commits exactly those (and `package.json`/`pnpm-lock.yaml` as "
              "above); any other file left in the tree - a hidden directory such as editor, "
              "CI or agent-host settings, an instruction file, a stray script - fails the "
              "step and is not committed.")
    add("4. **No platform SDK work.** Never import or reference a portal SDK, and never "
        "call `createPlatform`. Ads, analytics and saves go through the integration seam "
        "below, which the Factory provides and wires. The integration module replaces the "
        "wiring, not your calls.")
    add("5. Pause is by reason. Ads use `withAdBreak`; audio and input stop while "
        "`game.paused`. Never grant a reward unless `rewarded()` resolved true.")
    add("6. Keep the verify probe and the HUD contract: `#hud[data-ready]`, "
        "`#hud[data-scene]` (the active scene id) and `#hud[data-steps]` (incrementing "
        "while play runs). The release pipeline reads them.")
    add("7. Every player-facing string comes from `public/locales/<locale>.json` via "
        "`src/core/i18n.ts`, never from code. Locales in the design: "
        + (", ".join(d["locales"]) or "en") + ". Ship the ones the MVP needs; report any "
        "a later tier owns as deferred.")
    add("8. TypeScript strict as configured; `import type` for types; comments explain why. "
        "Match the template's style.")
    add("")

    notes = brief.get("engine_notes")
    if notes:
        add(f"## Engine notes ({engine})\n")
        add("What this engine needs that the template does not provide for you. None of it "
            "replaces the ground rules above.\n")
        for note in notes.get("notes") or []:
            add(f"- {note}")
        if notes.get("physics"):
            add(f"- **Physics.** {notes['physics']}")
        add("")

    add("## Required systems\n")
    if brief.get("phase") == "greybox":
        add("Report each in `systems` as done, partial or missing. Anything but done fails the "
            "checks - except "
            + ", ".join(f"**{n}**" for n in GREYBOX_DEFERRABLE)
            + ", which serve assets, sound and persistence that arrive in production: in "
              "this phase report them `partial` or `deferred` honestly and spend the time on "
              "the loop, its readability and its feel.\n")
    else:
        add("Report each in `systems` as done, partial or missing. Anything but done fails "
            "the checks.\n")
    for system in brief["required_systems"]:
        add(f"- **{system['id']}** - {system['acceptance']}")
    add("")

    add("## Play probe (how the build is judged)\n")
    add("The build is played from outside, not judged by its own tests: a bot drives it with "
        "real pointer and key input, reads a snapshot before and after every input, and "
        "renders frames to check a first-time player can see and follow it - the objective "
        "on screen, no failure before the first success, every action visibly acknowledged, "
        "a reachable win (or best) and loss, a restart, and the player, threats and goals "
        "drawn large enough to read. Install `window.__wgf__.play = { snapshot() }` once "
        "`window.__wgf__` exists, returning exactly this shape. Metric names are the "
        "experience contract's (`build_spec.experience`, `hud[].metric`). Entity bounds are "
        "where each thing is drawn now, in CSS px of the viewport (project 3D positions "
        "through the camera). `oracle` is computed only when the page URL carries "
        "`wgf-probe=1`; without it the field is absent, and nothing else changes. The probe "
        "never changes the game, and the game never reads it.\n")
    add("A build with content units reports `content` - `{unit_id, unit_index, unit_count, "
        "unit_kind, objective, progress}`, the unit's own id from the table below - and one "
        "`metrics[\"difficulty.<axis>\"]` per axis the design declares. That is how the bot "
        "tells one unit from the next and sees difficulty actually move; a build that reports "
        "one unit forever is a build of one unit.\n")
    with open(PLAY_PROBE_SCHEMA, encoding="utf-8") as handle:
        add("```json\n" + handle.read().rstrip() + "\n```\n")

    add("## MVP (build exactly this)\n")
    add(_bullets(brief["mvp"]))
    if brief["prototype_tier"]:
        add("\nThe prototype tier, which the MVP must at least cover:\n")
        add(_bullets(brief["prototype_tier"]))
    if brief.get("release_scope"):
        tier = (brief.get("build_scope") or {}).get("quality_tier") or "release"
        add(f"\nThe {tier} scope, built in this run too (quality tier `{tier}`: nothing is "
            f"built after prototype review, so what the release ships is built now):\n")
        add(_bullets(brief["release_scope"]))
    add("\nNot now (later tiers - do not build):\n")
    add(_bullets(brief["not_now"]))
    add("\nOut of scope:\n")
    add(_bullets(brief["out_of_scope"]))
    if brief["must_prove"]:
        add("\nThe prototype exists to answer these; make each observable in play:\n")
        add(_bullets(brief["must_prove"]))
    add("")

    add("## Design\n")
    add("The whole design is in `docs/GDD.md`, rendered from the game-design artifact (the "
        "Factory regenerates it every visit; do not edit it). The essentials:\n")
    for label, key in (("Fantasy", "fantasy"), ("Core loop", "core_loop"),
                       ("Controls", "controls"), ("Difficulty", "difficulty"),
                       ("Progression", "progression"),
                       ("Progression ends", "progression_terminal"),
                       ("Onboarding / tutorial", "onboarding"),
                       ("Accessibility", "accessibility"), ("Art", "art_direction"),
                       ("Audio", "audio_direction")):
        if d.get(key):
            add(f"- **{label}:** {d[key]}")
    if d["pillars"]:
        add("- **Pillars:** " + "; ".join(d["pillars"]))
    if d["screens"]:
        add("- **Screens:** " + "; ".join(d["screens"]))
    for key, label in (("time_to_first_play_s", "First play within (s)"),
                       ("time_to_first_reward_s", "First reward within (s)"),
                       ("target_seconds", "Target session (s)"),
                       ("structure", "Session structure"),
                       ("end_condition", "Session ends")):
        if key in session:
            add(f"- **{label}:** {session[key]}")
    add("")

    content_section = _content_section(brief)
    if content_section:
        add(content_section)

    spec = brief.get("build_spec")
    if spec and spec.get("sections"):
        add("## Build spec (MVP tier)\n")
        add("The design's `build_spec`, which is what the design exists to hand you: build "
            "these exactly. Rules are testable statements - unit-test them. `parameters` and "
            "difficulty values are starting tuning: keep them as data in `src/game/` (one "
            "tuning module), never as literals in logic, so a playtest can change them. Every "
            "reward, failure and HUD `feedback` is part of the MVP, not polish: a mechanic "
            "the player cannot read cannot be judged. The same data is in `brief.json` under "
            "`build_spec`.\n")
        for key, label in BUILD_SPEC_SECTIONS:
            if key not in spec["sections"]:
                continue
            add(f"### {label}\n")
            if key in SPEC_SECTIONS_RENDERED_ABOVE:
                add(f"See *{SPEC_SECTIONS_RENDERED_ABOVE[key]}* above - the same data, with "
                    f"the table and the contract that go with it. It is in `brief.json` under "
                    f"`build_spec.sections.{key}` and `content`.\n")
                continue
            add("\n".join(_spec_lines(spec["sections"][key])) or "- (none)")
            add("")
        if spec.get("not_now"):
            add("Left out on purpose (a later tier - do not build):\n")
            add(_bullets(spec["not_now"]))
            add("")
        why = {"sdk_touchpoints": "`sdk_touchpoints` (the integration step wires them; call "
                                  "only the seam)",
               "assets": "`assets` (the asset manifest below is what is delivered)"}
        if spec.get("omitted"):
            add("Not in this brief: " + " and ".join(why[k] for k in spec["omitted"]) + ".\n")

    plan = brief.get("dev_plan")
    if plan and plan.get("tasks"):
        add("## Development plan (approved at G3)\n")
        add("The tech plan's prototype milestones. Work the tasks in the order below (it "
            "respects their dependencies); a task is done when every acceptance criterion "
            "holds and its tests exist, not when the code runs. Name the task ids in "
            "`scope_deltas` for anything you could not finish.\n")
        for milestone in plan.get("milestones") or []:
            add(f"- **{milestone.get('id')}** {milestone.get('label', '')}"
                + (" - exit: " + "; ".join(milestone["exit_criteria"])
                   if milestone.get("exit_criteria") else ""))
        add("")
        for task in plan["tasks"]:
            add(f"### {task['id']}: {task.get('title', '')}\n")
            if task.get("description"):
                add(task["description"] + "\n")
            if task.get("dependencies"):
                add("- After: " + ", ".join(f"`{d}`" for d in task["dependencies"]))
            add("- Acceptance:")
            add("\n".join(f"  - {c}" for c in task.get("acceptance_criteria") or []))
            if task.get("tests"):
                add("- Tests: " + ", ".join(f"`{t}`" for t in task["tests"]))
            if task.get("assets"):
                add("- Assets: " + ", ".join(f"`{a}`" for a in task["assets"]))
            add("")
        if plan.get("later"):
            add("Tasks of later milestones (not this build): " + ", ".join(
                f"`{t}`" for t in plan["later"]) + "\n")

    add("## Monetization placements\n")
    if brief["placements"]:
        add("Call the seam at exactly these moments, with a stable placement id you list in "
            "the report. Offer rewarded only where the design says, and only when "
            "`canOfferRewarded` is true.\n")
        for p in brief["placements"]:
            value = f" Player gets: {p['player_value']}" if p.get("player_value") else ""
            add(f"- **{p['kind']}** - {p['trigger']}.{value}")
    else:
        add("- None. Do not add any.")
    add("")

    add("## Assets\n")
    if brief["assets"]:
        add("From the asset manifest. `procedural` items are generated in code. Anything not "
            "yet delivered gets a clearly-marked placeholder loaded through the same path, "
            "reported as `placeholder`. Never ship an item without its recorded license.\n")
        if brief.get("runtime_assets"):
            add(f"Load every asset through the runtime asset manifest `{brief['runtime_assets']}`"
                " - fetch it once at boot, resolve each asset by its id, and never write an "
                "asset path in source. Each entry has a `url` relative to the manifest (or an "
                "`atlas` and `frame`: load `atlases[<atlas>]` once, then draw the frame), its "
                "pixel `width`/`height`, `scale` (display at pixel size / scale), and for a "
                "spritesheet its `data` atlas, `frames` and `animations` (frames, fps, loop). "
                "Placeholders (`placeholder: true`) load through the same path, so replacing "
                "one needs no code change. Do not edit the manifest or the files it lists; "
                "they belong to the assets step.\n")
        elif any(a.get("files") for a in brief["assets"]):
            add("Delivered files are listed by their path in this repository; load them from "
                "there (they are already in the checkout, and the development commit includes "
                "them).\n")
        for a in brief["assets"]:
            extra = ", ".join(f"{k}: {a[k]}" for k in ("type", "source", "status", "license")
                              if a.get(k))
            add(f"- `{a['id']}` {a.get('label', '')} ({extra})")
            for path in a.get("files") or []:
                add(f"  - `{path}`")
    elif brief.get("phase") == "greybox" and brief.get("existing_content"):
        add("- None made in this phase; keep every asset the adopted game already ships "
            "(see *Adopted game*).")
    elif brief.get("phase") == "greybox":
        add("- None in this phase: draw everything with primitives (see *Phase: greybox*).")
    else:
        add("- The manifest lists nothing for this tier.")
    add("")

    if brief.get("phase") == "production" and brief.get("production_art"):
        add(_production_art_section(brief["production_art"], brief.get("engine")))

    add(_ownership_section(brief))
    add("## Integration seam (provided by the Factory - do not write or edit it)\n")
    add("Two files are already in the repository and belong to the Factory: "
        "`src/game/integration.ts` (the `GameIntegration` interface below) and "
        "`src/platform/integration.ts` (its wiring). Do not change either; the checks compare "
        "them byte for byte, and the integration module later replaces the wiring file as a "
        "whole.\n")
    add("- In `src/main.ts`, import `createGamePlatform` and `createGameIntegration` from "
        "`./platform/integration.js`. Get the platform with `const platform = await "
        "createGamePlatform();` where the template called `createPlatform(...)` and "
        "`initialize()` - keep the template's boot order around it (loading progress, "
        "`signalReady`, `game.start()`, `bindPlatform` and its first-input gameplay start).")
    add("- Get the seam with `createGameIntegration(game, platform, { audio })` once the "
        "`Game` exists, `audio` being your audio service's `{ mute(), unmute() }` so ads and "
        "portal pauses silence it. Pass the seam to the game.")
    add("- Game code calls only the seam: nothing in `src/` outside `src/platform/` calls "
        "`createPlatform`, `showRewarded` or `showInterstitial`.\n")
    add("```ts\n" + INTEGRATION_CONTRACT + "```\n")

    add("## Tests\n")
    add("- Unit tests (Vitest, `tests/unit/`) for the rules: state transitions, scoring, "
        "progression, difficulty, restart. Logic is tested without an engine or a DOM.")
    add("- Extend `tests/e2e/smoke.spec.ts` (Playwright, desktop and mobile) so it plays: "
        "boot, start a run through real input, reach game over, restart - with no page "
        "errors. Keep the existing boot assertions.")
    if brief.get("engine_notes"):
        add("- **The canvas must be shown to render.** In the `@boot` test, during active "
            "play rather than on the title screen, assert that the canvas pixels are neither "
            "blank nor a single flat colour, and log the renderer's own counters (draw calls, "
            "triangles, geometries, textures) so the run has the numbers. Zero draw calls "
            "with a healthy loop is the defect this catches.")
    aspects = brief.get("verification_aspects") or {}
    if aspects.get("required"):
        add("- **Verification evidence.** Verification counts a gameplay aspect as proven only "
            "by a passing Playwright test tagged with it in its title, e.g. "
            "`test(\"a run reaches game over and restarts @game-over @restart\", ...)`. This "
            "build must prove: " + " ".join(f"`@{a}`" for a in aspects["required"])
            + ". (Vocabulary: " + " ".join(f"`@{a}`" for a in aspects["vocabulary"])
            + ".) `@pause-resume`: pausing - the pause control, or the tab going hidden - "
            "stops `#hud[data-steps]`, and resuming advances it again. `@progression`: the "
            "difficulty or level advances in play.")
    add("- All of `pnpm typecheck`, `pnpm lint`, `pnpm test`, `pnpm build` and "
        "`pnpm test:e2e` must pass. Format only the files you created or changed: "
        "`pnpm exec prettier --write <those files>`. Never run `pnpm format:write` or "
        "`prettier --write .`: they rewrite the template's own files outside the paths you "
        "may write, and the develop step then refuses the whole commit.")
    add("")

    if brief.get("self_playtest"):
        add("## Playtest your build\n")
        add("This developer has a browser tool. Once the checks pass, play the game the way "
            "a first-time player would, before you write the report:\n")
        add("1. `pnpm build`, then serve the bundle with `pnpm preview --port 4173 "
            "--strictPort` - the built game, never the dev server - and open "
            "`http://localhost:4173`. Stay on localhost: the browser is limited to it, and "
            "no portal SDK is contacted.")
        add("2. Play through every aspect the verification section above requires. For "
            "each, check the minimum feedback bar: every input acknowledged at once, every "
            "reward noticed (motion and sound), every failure understood before any overlay "
            "covers it, HUD values that animate when they change.")
        add("3. Check the first thirty seconds against the design's session targets: first "
            "play and first reward within their times, one tap to play, no wall of text.")
        add("4. Fix what you find, rerun the checks, and stop the preview server.")
        add("5. Record what you saw and fixed in the report's `known_issues` or "
            "`scope_deltas`. This is your own check, not evidence: verification plays the "
            "build independently.\n")

    loop = brief.get("loop")
    if loop:
        add("## Why this is another iteration\n")
        route_budget = loop.get("route_budget") or {}
        line = f"The run came back to development through `{loop['entered_by']}`"
        if route_budget.get("limit"):
            line += (f": pass {route_budget.get('used')} of {route_budget.get('limit')} this "
                     f"route allows before the run stops for a person "
                     f"({route_budget.get('remaining')} left after this one)")
        add(line + ".")
        decision = loop.get("decision")
        if brief.get("specialist"):
            add(f"The triage step routed this build's findings by the discipline that owns "
                f"them, and this visit is the {brief['specialist']['label']}'s: what to "
                f"change is *Your findings* (*This visit*, above), each with how it is "
                f"accepted.")
        elif decision:
            who = decision.get("decided_by") or "unknown"
            if decision.get("note"):
                add(f"The decision at `{decision['step']}` was `{decision['decision']}` "
                    f"({who}), with this reason:\n")
                add("\n".join("> " + part for part in str(decision["note"]).splitlines()))
                add("")
                add("Change what that reason asks for, and only that. If it asks for evidence "
                    "no code change can supply (a playtest, a device measurement), say so in "
                    "`known_issues` rather than changing the game to look busy.")
            else:
                add(f"The decision at `{decision['step']}` was `{decision['decision']}` "
                    f"({who}) and recorded no reason: nothing says what to change. Do not "
                    f"guess - re-check the build against this brief, fix only what you can "
                    f"show is wrong, and say in `known_issues` that no reason was given.")
        elif brief.get("qa_defects") or brief.get("review_blockers") or \
                brief.get("previous_failures") or brief.get("playability_failures") or \
                brief.get("production_failures") or brief.get("visual_qa_failures") or \
                brief.get("sufficiency_failures"):
            add("Fix what sent it back first (below); a pass that does not fix it is one "
                "fewer left.")
        else:
            add("No decision, defect or blocker was recorded for this route: re-check the "
                "build against this brief and say in `known_issues` what you found.")
        add("")
    sessions = brief.get("sessions")
    if loop and sessions and sessions.get("max_sessions") is not None:
        used, limit = sessions.get("sessions", 0), sessions["max_sessions"]
        add(f"Developer budget: {used} of {limit} sessions used before this visit, "
            f"{max(limit - used, 0)} left (each attempt is one session; at the limit the run "
            f"stops for a person).\n")

    if brief["qa_defects"]:
        add("## Fix first: blocking defects from verification\n")
        for defect in brief["qa_defects"]:
            add(f"- `{defect.get('id')}` ({defect.get('severity')}): {defect.get('summary')}"
                + (f" Repro: {defect['repro']}" if defect.get("repro") else ""))
        add("")

    if brief.get("playability_failures"):
        add("## Fix first: what the build did when it was played\n")
        add(f"The playability step built `{(brief.get('played_commit') or '')[:12]}` and "
            "played it from outside, as a first-time player's device would: a bot reading "
            "the play probe (*Play probe*, above) and acting only through real pointer, touch "
            "and key input, on a desktop and a mobile viewport. These checks failed. Each is "
            "measured against the experience contract or core/reference/visual-quality.yaml, "
            "and the next build is played the same way: fix what the player sees, not the "
            "probe's report of it. A probe that misreports the game is itself a defect. "
            "Where a frame is named, look at it.\n")
        for failure in brief["playability_failures"]:
            line = f"- `{failure['check']}` ({failure.get('project')}): {failure.get('summary')}"
            if failure.get("expected") is not None:
                line += f" Expected: {_inline(failure['expected'])}."
            if failure.get("frames"):
                line += " Frames: " + ", ".join(f"`{f}`" for f in failure["frames"])
            add(line)
        add("")

    if brief.get("production_failures"):
        add("## Fix first: what the production gate measured\n")
        add(f"The production-quality step judged `{(brief.get('gated_commit') or '')[:12]}` "
            "from the same play: every required asset delivered, fetched, drawn and visible, "
            "no readable entity a primitive, the DOM UI at its measured bars "
            "(core/reference/production-quality.yaml). These checks failed. One routed "
            "`assets` named an asset the assets step has now made again: use it as "
            "`public/assets/assets.json` lists it. The rest are the game's own use of its "
            "assets and its UI. Where a frame is named, open it: it is what was measured.\n")
        for failure in brief["production_failures"]:
            line = (f"- `{failure['check']}`"
                    + (f" ({failure['project']})" if failure.get("project") else "")
                    + f" [{failure.get('route')}]: {failure.get('summary')}")
            if failure.get("assets"):
                line += " Assets: " + ", ".join(f"`{a}`" for a in failure["assets"])
            if failure.get("expected") is not None:
                line += f" Expected: {_inline(failure['expected'])}."
            if failure.get("measured") is not None:
                measured = _inline(failure["measured"])
                line += f" Measured: {measured[:600] + ' ...' if len(measured) > 600 else measured}."
            if failure.get("frames"):
                line += " Frames: " + ", ".join(f"`{f}`" for f in failure["frames"])
            add(line)
        add("")

    if brief.get("visual_qa_failures"):
        add("## Fix first: what visual QA saw\n")
        add(f"A judge read the frames of `{(brief.get('gated_commit') or '')[:12]}` against "
            "core/reference/visual-qa-rubric.yaml and the design's visual identity, and the "
            "build failed. The next build is judged the same way, from frames of the running "
            "game: change what is on screen. Where a frame is named, open it and find what "
            "the judge describes; a score's or the look's reason is the judge's own words. "
            "`major` findings did not fail the build on their own, but they are defects the "
            "judge saw: fix them in the same pass.\n")
        for failure in brief["visual_qa_failures"]:
            add(f"- `{failure['id']}` [{failure.get('route') or '-'}]: {failure['summary']}"
                + (" Frame: `" + failure["frame"] + "`" if failure.get("frame") else "")
                + (" Frames: " + ", ".join(f"`{f}`" for f in failure["frames"])
                   if failure.get("frames") else ""))
        add("")

    if brief.get("sufficiency_failures"):
        add("## Fix first: what the content audit counted on the build\n")
        add(f"The content-sufficiency step counted the content of "
            f"`{(brief.get('sufficiency_commit') or '')[:12]}` - its "
            "`public/content/units.json` and what the play probe showed in every unit, played "
            "in order and entered through the unit link (`?wgf-probe=1&wgf-unit=<unit id>`) - "
            "against the bars of the design's quality tier "
            "(core/reference/quality-benchmark.yaml). The design meets these bars and the "
            "build does not: build what the design states, unit by unit. Never invent a unit, "
            "an element or a number the design does not state; where the design is silent, "
            "record the gap in `design_gaps`. Every entity of a content role carries its "
            "`kind` while a unit is in play.\n")
        for failure in brief["sufficiency_failures"]:
            line = (f"- `{failure.get('check')}` ({failure.get('severity')}): "
                    f"{failure.get('summary')}")
            if failure.get("bar") is not None:
                line += f" Bar: {_inline(failure['bar'])}."
            add(line)
        add("")

    if brief.get("review_blockers"):
        add("## Fix first: blockers from code review\n")
        add(f"An independent review of `{(brief.get('reviewed_commit') or '')[:12]}` "
            "requested changes. Fix every blocker below; the next review checks each one "
            "again, and a blocker that is still there sends the build back here. Fix them in "
            "the files that are yours (*Which files are yours*, above): where a blocker could "
            "only be fixed in a file that is not, leave that file as it is and say so, with "
            "the blocker's id, in `known_issues`.\n")
        for blocker in brief["review_blockers"]:
            where = blocker.get("file") or "(whole build)"
            if blocker.get("file") and blocker.get("line"):
                where += f":{blocker['line']}"
            add(f"- `{blocker.get('id')}` ({blocker.get('severity')}) {where}: "
                f"{blocker.get('summary')}")
        add("")

    if brief["previous_failures"]:
        add("## Fix first: checks that failed on the previous attempt\n")
        for failure in brief["previous_failures"]:
            add(f"### {failure['check']}\n\n{failure.get('summary') or ''}\n")
            if failure.get("output_tail"):
                add("```\n" + failure["output_tail"][-2500:] + "\n```\n")

    if brief.get("craft_guides"):
        add("## Craft guides\n")
        add("The Factory's craft playbooks - game feel and juice, the core loop, onboarding, "
            "the UI kit, production art, production wiring, performance, audio. They are "
            "outside this repository: open them by these absolute paths. Read the first "
            "four before you build anything a player sees.\n")
        for path in brief["craft_guides"]:
            add(f"- `{path}`")
        add("")

    if brief["skills"]:
        add("## Host skills\n")
        add("If your host offers these, use them - but where one assumes a project layout, "
            f"the template wins. `{PLUGIN}:` skills come from this Factory's own plugin, "
            "which points at its craft playbooks (game feel and juice, core loop, onboarding "
            "and the UI kit, production art, production wiring, performance, audio):\n")
        for area, names in brief["skills"].items():
            add(f"- {area}: " + ", ".join(names))
        add("")

    add("## Report back\n")
    add(f"Write `{brief['report_path']}` when you are done. The module reads it, checks it "
        "against the build, and turns it into the prototype report. Be honest: a partial "
        "system reported as done fails review later, at a higher price.\n")
    add("```json\n" + json.dumps(REPORT_CONTRACT, indent=2) + "\n```")
    if brief.get("report_visit"):
        add(f"\n**This visit's report.** Rewrite the whole report for what the checkout holds "
            f"now, and set `\"visit\": \"{brief['report_visit']}\"` in it. A report left from "
            f"an earlier visit is what review would read as this one's; a report without this "
            f"visit's key fails the conformance check.")
    add("\n`mvp` has one entry per MVP item above, verbatim. `placements` covers every "
        "placement above.")
    content = brief.get("content") or {}
    if content.get("units"):
        add(f"\n`content_units` has one entry per unit of the content table above, by its "
            f"design id: `built` means it meets every acceptance line, `partial` means it is "
            f"there and does not (say what is missing in `notes`), `cut` means it is not "
            f"there. A `cut` unit needs a `design_gaps` entry naming it, or the step fails.")
    add("\n`design_gaps` is where the design was silent, contradictory or impossible to "
        "build from: the `field` it concerns, the `question` a designer can answer, what you "
        "`assumed` instead (or null when the gap stopped the work), and whether it is "
        "`blocking` or `minor`. A gap you report costs one design visit - the run goes back "
        "to design, the design is repaired, and the build continues from it. A gap you paper "
        "over fails review, later and at a higher price. Reporting none when there were none "
        "is the right answer; inventing a value and saying nothing is not.")
    return "\n".join(out) + "\n"

"""The development brief: what the developer is asked to build, derived from the artifacts.

The brief is the whole interface between the Factory and whoever writes the game - a person,
or an agent host driven by the `command` developer. It is written into the game repository
as `docs/development/brief.md` (to read) and `brief.json` (to check against), so the
repository records what each commit was asked to satisfy.

It restates no schema. It selects from the game design what an implementer needs, applies
the template's rules to it, and states the two contracts the developer owes back: the
integration seam the SDK module wires, and the development report this module checks.
"""

import json

from wgflib import template_contract as contract

from wgf_verification.checks.gameplay import ASPECTS, required_aspects_for

from .scope import DEFAULT_WRITABLE

__all__ = ["REQUIRED_SYSTEMS", "INTEGRATION_CONTRACT", "REPORT_PATH", "BRIEF_DIR",
           "build_brief", "render_markdown", "PROTECTED_PATHS", "STRUCTURAL_PATHS",
           "ENGINE_DIRS"]

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
    ("progression", "The design's progression and difficulty ramp, persisted through the "
                    "integration seam's save/load."),
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
    ("audio-hooks", "A small audio service in src/audio/ with named cues the game triggers; "
                    "muted by default until first input, silenced while paused (ads)."),
)

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
ENGINE_LIBRARIES = {"pixijs": "pixi.js", "threejs": "three"}

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
    "engine": "pixijs | threejs",
    "systems": {name: "done | partial | missing" for name, _ in REQUIRED_SYSTEMS},
    "mvp": [{"item": "<exactly as listed in the brief>", "status": "built | partial | cut | "
             "deferred", "notes": "..."}],
    "placements": [{"id": "<placement id passed to the seam>", "kind": "rewarded | "
                    "interstitial | banner", "trigger": "<the design's trigger>"}],
    "integration_status": {"platform_sdk": "working | partial | not-started",
                           "monetization": "...", "analytics": "...", "persistence": "..."},
    "assets": [{"id": "<asset-manifest item id>", "status": "integrated | placeholder | cut"}],
    "scope_deltas": [{"item": "...", "direction": "added | cut | deferred", "reason": "..."}],
    "known_issues": ["..."],
    "how_to_play": "One or two sentences a reviewer reads before opening the build.",
}

DEFAULT_SKILLS = {
    "pixijs": ["the official PixiJS skills"],
    "threejs": ["a Three.js game-development skill"],
    "ui": ["a frontend-design skill, for menus, HUD and screens"],
}


def _pin(artifact_type, content, ref):
    provenance = (content or {}).get("provenance") or {}
    return {
        "artifact_type": artifact_type,
        "artifact_id": provenance.get("artifact_id"),
        "content_hash": getattr(ref, "content_hash", None) or provenance.get("content_hash"),
    }


def build_brief(*, title_id, engine, iteration, key, baseline, design, assets, scaffold,
                strategy=None, qa=None, previous_checks=None, refs=None, skills=None,
                review=None, mobile_test=True, writable_paths=None, package_changes=None):
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
    failures = [
        {"check": c.get("id"), "summary": c.get("summary"), "output_tail": c.get("output_tail")}
        for c in (previous_checks or {}).get("checks") or []
        if c.get("status") == "failed"
    ]
    host_skills = dict(DEFAULT_SKILLS)
    host_skills.update(skills or {})

    session = design.get("session") or {}
    ux = design.get("ux") or {}
    return {
        "format": 1,
        "title_id": title_id,
        "iteration": iteration,
        "idempotency_key": key,
        "baseline_commit": baseline,
        "engine": engine,
        "engine_dir": ENGINE_DIRS[engine],
        "inputs": [
            _pin(t, c, refs.get(t))
            for t, c in (("game-design", design), ("asset-manifest", assets),
                         ("scaffold-record", scaffold), ("title-strategy", strategy),
                         ("qa-report", qa), ("review-report", review))
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
            "locales": (design.get("scope") or {}).get("locales") or [],
        },
        "mvp": list(tiers.get("mvp") or []),
        "prototype_tier": list(tiers.get("prototype") or []),
        "not_now": list(tiers.get("production") or []) + list(tiers.get("future") or []),
        "out_of_scope": [o.get("item") for o in tiers.get("out_of_scope") or []],
        "must_prove": list((strategy or {}).get("prototype_must_prove") or []),
        "placements": placements,
        "assets": asset_items,
        "required_systems": [{"id": n, "acceptance": a} for n, a in REQUIRED_SYSTEMS],
        "protected_paths": list(PROTECTED_PATHS),
        # What the development commit may contain (scope.py), and how package.json may
        # change (checks.package_findings). Anything else fails the step.
        "writable_paths": list(writable_paths),
        "package_changes": {k: list(v) for k, v in package_changes.items() if v},
        "qa_defects": defects,
        "review_blockers": review_blockers,
        "reviewed_commit": (review or {}).get("reviewed_commit") if review_blockers else None,
        "previous_failures": failures,
        "skills": {k: host_skills[k] for k in ("ui", engine) if k in host_skills},
        "report_path": REPORT_PATH,
        # What verification will demand browser evidence for (wgf_verification computes the
        # same set from the same design): the developer is told up front, instead of
        # learning it from a failed verification and a loop back here.
        "verification_aspects": {
            "vocabulary": list(ASPECTS),
            "required": [a for a in ASPECTS if a in required_aspects_for(design, mobile_test)],
        },
    }


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


def _bullets(items, empty="- (none)"):
    lines = [f"- {item}" for item in items if item]
    return "\n".join(lines) if lines else empty


def render_markdown(brief):
    d = brief["design"]
    engine = brief["engine"]
    other = next((e for e in contract.ENGINES if e != engine), engine)
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

    add("## Goal\n")
    add("A genuinely playable game: a stranger opens the build, understands it without help, "
        "plays a full session, loses or finishes, and plays again. Build the MVP below and "
        "nothing past it.\n")

    add("## Ground rules\n")
    add(f"1. **Engine: `{engine}`**, from `game.config.yaml`. 2D is PixiJS, 3D is Three.js. "
        f"Do not add another engine, a physics engine that brings its own renderer, or "
        f"`{other}`.")
    add(f"2. `{engine_pkg}` and `{framework}` are imported only under "
        f"`{brief['engine_dir']}/` (and by `src/rendering/create-renderer.ts`). Rules, state "
        f"and progression live in `src/game/` and never touch the engine.")
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

    add("## Required systems\n")
    add("Report each in `systems` as done, partial or missing. Anything but done fails the "
        "checks.\n")
    for system in brief["required_systems"]:
        add(f"- **{system['id']}** - {system['acceptance']}")
    add("")

    add("## MVP (build exactly this)\n")
    add(_bullets(brief["mvp"]))
    if brief["prototype_tier"]:
        add("\nThe prototype tier, which the MVP must at least cover:\n")
        add(_bullets(brief["prototype_tier"]))
    add("\nNot now (production/future tiers - do not build):\n")
    add(_bullets(brief["not_now"]))
    add("\nOut of scope:\n")
    add(_bullets(brief["out_of_scope"]))
    if brief["must_prove"]:
        add("\nThe prototype exists to answer these; make each observable in play:\n")
        add(_bullets(brief["must_prove"]))
    add("")

    add("## Design\n")
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
        if any(a.get("files") for a in brief["assets"]):
            add("Delivered files are listed by their path in this repository; load them from "
                "there (they are already in the checkout, and the development commit includes "
                "them).\n")
        for a in brief["assets"]:
            extra = ", ".join(f"{k}: {a[k]}" for k in ("type", "source", "status", "license")
                              if a.get(k))
            add(f"- `{a['id']}` {a.get('label', '')} ({extra})")
            for path in a.get("files") or []:
                add(f"  - `{path}`")
    else:
        add("- The manifest lists nothing for this tier.")
    add("")

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
        "`pnpm test:e2e` must pass. Run `pnpm format:write` before you finish.")
    add("")

    if brief["qa_defects"]:
        add("## Fix first: blocking defects from verification\n")
        for defect in brief["qa_defects"]:
            add(f"- `{defect.get('id')}` ({defect.get('severity')}): {defect.get('summary')}"
                + (f" Repro: {defect['repro']}" if defect.get("repro") else ""))
        add("")

    if brief.get("review_blockers"):
        add("## Fix first: blockers from code review\n")
        add(f"An independent review of `{(brief.get('reviewed_commit') or '')[:12]}` "
            "requested changes. Fix every blocker below; the next review checks each one "
            "again, and a blocker that is still there sends the build back here.\n")
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

    if brief["skills"]:
        add("## Host skills\n")
        add("If your host offers these, use them - but where one assumes a project layout, "
            "the template wins:\n")
        for area, names in brief["skills"].items():
            add(f"- {area}: " + ", ".join(names))
        add("")

    add("## Report back\n")
    add(f"Write `{brief['report_path']}` when you are done. The module reads it, checks it "
        "against the build, and turns it into the prototype report. Be honest: a partial "
        "system reported as done fails review later, at a higher price.\n")
    add("```json\n" + json.dumps(REPORT_CONTRACT, indent=2) + "\n```")
    add("\n`mvp` has one entry per MVP item above, verbatim. `placements` covers every "
        "placement above.")
    return "\n".join(out) + "\n"

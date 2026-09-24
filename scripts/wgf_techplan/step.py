"""The `tech-plan` step: game-design + title-strategy in, tech-plan out.

No side effect outside the run. Re-executing with the same inputs, settings and clock gives
the same content hash, which is the whole of its idempotency story.

Outcomes, per docs/workflow-module-contract.md §7:

    no game-design or no title-strategy in the run         WAITING_FOR_INPUT
    factory.techplan invalid                               BLOCKED
    pinned platform profile missing or moved               BLOCKED - re-pin in a superseding
                                                           strategy
    design not planable (consistency not pass, title       FAILED, not retryable
    mismatch, no engine, engine/dimension contradiction)
    otherwise                                              SUCCESS - including a plan that
                                                           does not fit the timebox: that is
                                                           G3's call (plan_fits_timebox), not
                                                           a reason to fit the estimates
"""

import datetime
import os

from wgflib import paths
from wgflib.hashing import content_hash
from wgflib.workflow import ArtifactOutput, StepResult, WorkflowStep
from wgflib.yamllite import YamlError, load_file

from .devplan import Estimates, build_dev_plan
from .selection import (DIMENSION_FOR_ENGINE, EngineError, PlatformError, pin_platforms,
                        select_engine, tightest_bundle_mb)

__all__ = ["TechPlanStep", "TechPlanSettings", "SettingsError", "SCHEMA_VERSION", "ROLE"]

SCHEMA_VERSION = "1.0.0"
ROLE = "architect"  # core/roles/roles.yaml: architect owns title:tech-plan
READS_MAJOR = "1"
AD_KINDS = ("interstitial", "rewarded", "banner")
# The template's own package names for each engine: the one piece of template knowledge the
# architecture text needs, and a mapping, not a behaviour.
ENGINE_PACKAGE = {"pixijs": "@wgf/pixi-framework", "threejs": "@wgf/three-framework"}
DEFAULT_BUILD = {"command": "pnpm build", "output": "dist"}
DEFAULT_DEVICE_CLASSES = [
    {"id": "mobile-mid", "description": "Mid-range phone, portal webview", "target_fps": 60},
    {"id": "desktop", "description": "Desktop browser", "target_fps": 60},
]


class SettingsError(ValueError):
    """factory.techplan in workspace/config/factory.yaml is wrong."""


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _portfolio_tolerance():
    try:
        document = load_file(os.path.join(paths.CONFIG, "portfolio.yaml")) or {}
    except (OSError, YamlError):
        return 1.5
    value = document.get("overrun_tolerance", 1.5)
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else 1.5


class TechPlanSettings:
    """`factory.techplan`, every key optional."""

    def __init__(self, estimates, device_classes, build, template_ref, overrun_tolerance):
        self.estimates = estimates
        self.device_classes = device_classes
        self.build = build
        self.template_ref = template_ref
        self.overrun_tolerance = overrun_tolerance

    @classmethod
    def from_config(cls, config):
        config = config or {}
        section = config.get("techplan") or {}
        if not isinstance(section, dict):
            raise SettingsError("factory.techplan must be a mapping")
        try:
            estimates = Estimates(section.get("estimates"))
        except ValueError as exc:
            raise SettingsError(str(exc))

        devices = section.get("device_classes") or DEFAULT_DEVICE_CLASSES
        allowed = {"id", "description", "target_fps", "max_memory_mb",
                   "max_time_to_interactive_s"}
        if not isinstance(devices, list) or not all(
                isinstance(d, dict) and isinstance(d.get("id"), str)
                and isinstance(d.get("target_fps"), (int, float)) and set(d) <= allowed
                for d in devices):
            raise SettingsError("factory.techplan.device_classes must be a list of "
                                "{id, target_fps, description?, max_memory_mb?, "
                                "max_time_to_interactive_s?}")

        build = dict(DEFAULT_BUILD)
        build.update(section.get("build") or {})
        if set(build) - {"command", "output"} or not all(isinstance(v, str) for v in build.values()):
            raise SettingsError("factory.techplan.build takes command and output, both strings")

        template_ref = section.get("template_ref")
        if template_ref is None:
            init = config.get("init") or {}
            name = init.get("template") or os.path.basename(
                os.path.normpath(init.get("template_path") or "web-game-template"))
            template_ref = f"{name}@{init.get('template_ref') or 'main'}"
        if not isinstance(template_ref, str) or "@" not in template_ref:
            raise SettingsError("factory.techplan.template_ref must look like "
                                "<template>@<ref>, e.g. my-org/web-game-template@main")

        tolerance = section.get("overrun_tolerance", _portfolio_tolerance())
        if not isinstance(tolerance, (int, float)) or isinstance(tolerance, bool) or tolerance <= 0:
            raise SettingsError("factory.techplan.overrun_tolerance must be a number > 0")
        return cls(estimates, [dict(d) for d in devices], build, template_ref, tolerance)


def _title_name(title_id):
    """The display name bootstrap would derive from the repository name."""
    return " ".join(part[:1].upper() + part[1:] for part in title_id.split("-") if part)


class TechPlanStep(WorkflowStep):
    type = "tech-plan"

    # Seams for tests; a real run uses core/.
    clock = staticmethod(utc_now)
    platforms_dir = None
    asset_kinds = None

    def execute(self, inputs, context):
        missing = [t for t in ("game-design", "title-strategy") if t in inputs.missing]
        if missing:
            return StepResult.waiting_for_input(
                f"tech-plan needs {' and '.join(missing)}; run strategy and design first")
        for artifact_type in ("game-design", "title-strategy"):
            version = inputs.refs[artifact_type].schema_version or "1"
            if version.split(".")[0] != READS_MAJOR:
                return StepResult.failed(f"{artifact_type} schema {version} is not readable by "
                                         f"this module (reads {READS_MAJOR}.x)", retryable=False)
        design = inputs.load("game-design")
        strategy = inputs.load("title-strategy")

        title_id = design.get("title_id")
        if not title_id or title_id != strategy.get("title_id"):
            return StepResult.failed(
                f"game-design is for {title_id!r} but title-strategy is for "
                f"{strategy.get('title_id')!r}", retryable=False)
        if context.project_id and context.project_id != title_id:
            return StepResult.failed(f"game-design is for {title_id!r} but this run is for "
                                     f"project {context.project_id!r}", retryable=False)
        status = (design.get("consistency") or {}).get("status")
        if status != "pass":
            return StepResult.failed(f"game-design consistency is {status!r}, not 'pass': it "
                                     "has not legitimately left title:design", retryable=False)

        try:
            settings = TechPlanSettings.from_config(context.config)
        except SettingsError as exc:
            return StepResult.blocked(str(exc))
        try:
            engine, rationale, engine_source = select_engine(design, self.asset_kinds)
        except EngineError as exc:
            return StepResult.failed(str(exc), retryable=False)
        try:
            platforms = pin_platforms(strategy, self.platforms_dir)
        except PlatformError as exc:
            return StepResult.blocked(str(exc))

        now = self.clock()
        plan = self._plan(design, strategy, title_id, engine, rationale, platforms, settings)
        artifact = self._with_provenance(plan, inputs, title_id, now, context)

        total = plan["dev_plan"]["est_days"]
        budget = strategy.get("timebox_days")
        allowed = budget * settings.overrun_tolerance if isinstance(budget, (int, float)) else None
        fits = None if allowed is None else total <= allowed
        metadata = {"engine": engine, "engine_source": engine_source,
                    "platforms": [p.pin for p in platforms], "est_days": total,
                    "timebox_days": budget, "fits_timebox": fits}
        metadata = {k: v for k, v in metadata.items() if v is not None}
        if fits is False:
            context.logger.warning("plan exceeds the timebox; G3 decides", est_days=total,
                                   allowed_days=allowed)
        context.logger.info("tech plan composed", engine=engine, engine_source=engine_source,
                            platforms=[p.pin for p in platforms], est_days=total)
        return StepResult.success(
            [ArtifactOutput("tech-plan", artifact, metadata=metadata)],
            message=f"{engine}, {len(platforms)} platform(s), {total} estimated days"
                    + ("" if fits is None else f" vs {allowed:g} allowed"))

    # -- composition --------------------------------------------------------------------

    def _plan(self, design, strategy, title_id, engine, rationale, platforms, settings):
        placements = (design.get("monetization") or {}).get("placements") or []
        kinds = [p.get("kind") for p in placements if isinstance(p, dict)]
        ad_kinds = [k for k in AD_KINDS if k in kinds]
        iap = "iap" in kinds

        devices = [dict(d) for d in settings.device_classes]
        first_play = (design.get("session") or {}).get("time_to_first_play_s")
        if isinstance(first_play, (int, float)):
            for device in devices:
                device.setdefault("max_time_to_interactive_s", first_play)
        perf = {"device_classes": devices}
        bundle = tightest_bundle_mb(platforms)
        if bundle is not None:
            perf["max_bundle_mb"] = bundle

        game_config = {
            "game": {"id": title_id, "name": _title_name(title_id), "version": "0.1.0"},
            "engine": {"type": engine},
            "platforms": [p.entry() for p in platforms],
            "build": dict(settings.build),
            "monetization": {"ad_kinds": ad_kinds, "iap": iap},
            "verification": {"smoke_test": True, "performance_test": True, "mobile_test": True},
            "publishing": {"enabled": False},
        }
        package = ENGINE_PACKAGE[engine]
        dimension = DIMENSION_FOR_ENGINE[engine]
        architecture = {
            "rendering": f"{engine} ({dimension}) through the template's renderer seam "
                         f"(createRenderer, {package}); the other engine is never loaded.",
            "game_core": "Template packages/game-core: loop, scenes, events, pause. Game "
                         "states and mechanics from the design's build_spec live in src/.",
            "state": "Game state machine from build_spec.game_states, in src/; persistence "
                     "through the platform storage abstraction.",
            "input": "build_spec.controls mapped onto the template's input handling.",
            "ui": "Screens, HUD and menus from build_spec, rendered with the selected engine.",
            "audio": "Template audio slot; content per the design's audio direction.",
            "assets": "The asset-manifest under public/assets/; the bundle stays within "
                      + (f"{bundle:g} MB." if bundle is not None else "the profiles' limits."),
            "platform_sdk": "@wgf/platform-sdk only; the adapter is chosen from "
                            "game.config.yaml platforms, never by game code.",
            "analytics": "@wgf/analytics-sdk event vocabulary.",
            "persistence": "platform storage (cloud where the profile allows, local otherwise).",
            "networking": None,
        }
        ownership = {
            "generic": ["packages/* (game-core, platform-sdk, analytics-sdk, renderers)",
                        "build, test and release tooling", "CI pipelines"],
            "game_specific": ["src/: mechanics, states, screens, content"],
            "platform_specific": [f"{p.pin} via its adapter and config/platforms/"
                                  for p in platforms],
            "agent_responsibility": ["dev_plan tasks, against their acceptance criteria"],
            "ci_responsibility": ["ci_green (ci.yml)", "verify_suite_green (verify.yml)"],
        }
        dev_plan = build_dev_plan(design, engine, platforms, settings.estimates)

        risks = []
        budget = strategy.get("timebox_days")
        allowed = budget * settings.overrun_tolerance if isinstance(budget, (int, float)) else None
        if allowed is not None and dev_plan["est_days"] > allowed:
            risks.append({"description": f"The plan estimates {dev_plan['est_days']:g} days "
                                         f"against {allowed:g} allowed ({budget} x "
                                         f"{settings.overrun_tolerance:g}).",
                          "severity": "high",
                          "mitigation": "Cut mvp scope in a superseding design, or reject at G3."})
        if bundle is not None:
            risks.append({"description": f"The tightest required bundle limit is {bundle:g} MB.",
                          "severity": "medium" if bundle <= 50 else "low",
                          "mitigation": "Assets are budgeted against max_bundle_mb and the "
                                        "verify suite measures the package."})
        for question in design.get("open_questions") or []:
            risks.append({"description": f"Open question: {question}", "severity": "low",
                          "mitigation": "Answered, or carried, by the prototype-report."})

        release = []
        for platform in platforms:
            for assertion in platform.blocking_assertions():
                release.append(f"{platform.pin}: {assertion}")

        return {
            "title_id": title_id,
            "engine": {"type": engine, "rationale": rationale},
            "architecture": architecture,
            "ownership": ownership,
            "perf_budgets": perf,
            "repo_params": {"repo_name": title_id, "template_ref": settings.template_ref,
                            "visibility": "private", "game_config": game_config},
            "dev_plan": dev_plan,
            "technical_risks": risks,
            "sdk_integration": {
                "platform_sdks": [p.id for p in platforms],
                "note": "Game code calls the template's platform abstraction, never a portal "
                        "SDK directly.",
            },
            "release_requirements": release,
        }

    def _with_provenance(self, plan, inputs, title_id, now, context):
        pinned = []
        opportunity = None
        for artifact_type in ("game-design", "title-strategy"):
            ref = inputs.refs[artifact_type]
            content = inputs.load(artifact_type)
            source = content.get("provenance") or {}
            opportunity = opportunity or content.get("opportunity_id") or source.get("opportunity_id")
            if source.get("artifact_id") and ref.content_hash:
                pinned.append({"artifact_id": source["artifact_id"],
                               "artifact_type": artifact_type,
                               "content_hash": ref.content_hash})
        provenance = {
            "artifact_id": f"wgf:tech-plan:{title_id}:{now[:10].replace('-', '')}-"
                           f"{min(context.execution, 99):02d}",
            "artifact_type": "tech-plan",
            "schema_version": SCHEMA_VERSION,
            "title_id": title_id,
            "produced_by": {"role": ROLE, "actor": "automation"},
            "produced_at": now,
            "inputs": pinned,
            "content_hash": "",
            "status": "draft",
        }
        if opportunity:
            provenance["opportunity_id"] = opportunity
        artifact = {"provenance": provenance}
        artifact.update(plan)
        artifact["provenance"]["content_hash"] = content_hash(artifact)
        return artifact


def register(registry):
    registry.register(TechPlanStep.type, TechPlanStep)
    return registry

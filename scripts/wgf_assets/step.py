"""The `assets` workflow step: a game design in, an asset manifest out.

    inputs   game-design (required), scaffold-record (optional: the target platforms, whose
             bundle-size limits the delivered files are checked against)
    outputs  asset-manifest

Settings come from `factory.assets` in workspace/config/factory.yaml, overridden by the
step's `with:` block:

    root           where the game repository checkout is; files go under public/assets/.
                   Default: .factory/assets/<title>, relative to the working directory.
    libraries      directories holding an index.json of reusable assets. Default: none.
    placeholders   {enabled: true, backends: [2d-assets-mcp, procedural], <backend>: {...}}
    optimize       lossless in-place optimization of files the step writes. Default: true.
    dimension      2d or 3d, when the design does not make it evident.
    fail_on        issue codes that fail the step (with the manifest still persisted as
                   evidence). Default: none - a manifest with issues is the honest output.
    strict         shorthand for failing on every error-severity issue.

Outcomes: SUCCESS with the manifest; WAITING_FOR_INPUT without a game-design; FAILED, not
retryable, for a design whose asset requirements are malformed or a game-design of a major
schema version this step cannot read; FAILED, not retryable, carrying the manifest, when an
issue named in fail_on (or any error, when strict) is present.
"""

import copy
import datetime
import os
import re

from wgflib import paths, provenance
from wgflib.workflow import ArtifactOutput, StepResult, WorkflowStep
from wgflib.yamllite import YamlError, load_file

from .library import open_libraries
from .pipeline import AssetPipeline, AssetStore
from .placeholders import build_backends
from .policy import PolicyError, load_policy
from .requirements import RequirementError, inspect, slugify

__all__ = ["AssetsStep", "MANIFEST_SCHEMA_VERSION", "resolve_settings"]

MANIFEST_SCHEMA_VERSION = provenance.version_of("asset-manifest")
READABLE_DESIGN_MAJOR = 1
DEFAULT_BACKENDS = ["2d-assets-mcp", "procedural"]


def _config_section(config, name):
    if hasattr(config, "section"):
        return config.section(name)
    return dict((config or {}).get(name) or {})


def resolve_settings(context):
    """factory.assets, with the step's `with:` block laid over it."""
    settings = copy.deepcopy(_config_section(context.config, "assets"))
    for key, value in (context.params or {}).items():
        if key == "placeholders" and isinstance(value, dict):
            merged = dict(settings.get("placeholders") or {})
            merged.update(value)
            settings["placeholders"] = merged
        else:
            settings[key] = value
    placeholders = dict(settings.get("placeholders") or {})
    placeholders.setdefault("enabled", True)
    placeholders.setdefault("backends", list(DEFAULT_BACKENDS))
    settings["placeholders"] = placeholders
    settings.setdefault("optimize", True)
    settings.setdefault("libraries", [])
    settings.setdefault("fail_on", [])
    return settings


def _bundle_limits(scaffold):
    """[(platform id, role, max MB)] for the scaffold's platforms that set a limit."""
    limits = []
    platforms = ((scaffold or {}).get("game_config") or {}).get("platforms") or []
    for platform in platforms:
        pid = platform.get("id") or ""
        if not re.match(r"^[a-z][a-z0-9-]*$", pid):
            continue
        path = os.path.join(paths.PLATFORMS, f"{pid}.yaml")
        try:
            profile = load_file(path) if os.path.exists(path) else {}
        except YamlError:
            continue
        limit = ((profile or {}).get("requirements") or {}).get("max_bundle_mb")
        if isinstance(limit, (int, float)) and limit > 0:
            limits.append((pid, platform.get("role") or "optional", limit))
    return limits


class AssetsStep(WorkflowStep):
    type = "assets"
    role = "asset"

    @staticmethod
    def clock():
        return datetime.datetime.now(datetime.timezone.utc)

    def execute(self, inputs, context):
        if "game-design" not in inputs:
            return StepResult.waiting_for_input("the assets step needs a game-design")
        ref = inputs.refs["game-design"]
        major = str(ref.schema_version or "1").split(".")[0]
        if major.isdigit() and int(major) > READABLE_DESIGN_MAJOR:
            return StepResult.failed(
                f"game-design schema {ref.schema_version} is newer than this step reads "
                f"({READABLE_DESIGN_MAJOR}.x)", retryable=False)
        design = inputs.load("game-design")
        scaffold = inputs.load("scaffold-record") if "scaffold-record" in inputs else None

        settings = resolve_settings(context)
        try:
            policy = load_policy(settings.get("policy"))
            requirements, dimension = inspect(design, policy, dimension=settings.get("dimension"))
        except (PolicyError, RequirementError) as exc:
            return StepResult.failed(f"asset requirements: {exc}", retryable=False)

        title_id = design.get("title_id") or context.project_id or "title"
        slug = slugify(title_id, "title")
        root = settings.get("root") or os.path.join(".factory", "assets", slug)
        store = AssetStore(os.path.abspath(root))
        libraries, library_problems = open_libraries(settings["libraries"])
        for problem in library_problems:
            context.logger.warning("asset library unavailable", problem=problem)

        placeholders = settings["placeholders"]
        backends = build_backends(placeholders.get("backends"), placeholders)
        pipeline = AssetPipeline(policy, store, backends, libraries, logger=context.logger,
                                 placeholders=bool(placeholders.get("enabled")),
                                 optimize=bool(settings.get("optimize")))
        context.logger.info("asset pipeline", requirements=len(requirements),
                            dimension=dimension, root=store.root,
                            derived=bool(requirements and requirements[0].derived))
        result = pipeline.run(requirements)

        manifest = self._manifest(design, scaffold, inputs, context, policy, result, title_id,
                                  slug)
        issues = manifest.get("issues") or []
        counts = {status: sum(1 for i in manifest["items"] if i["status"] == status)
                  for status in ("planned", "sourced", "in-progress", "delivered")}
        metadata = {
            "items": len(manifest["items"]),
            "placeholders": sum(1 for i in manifest["items"] if i.get("placeholder")),
            "production_ready": sum(1 for i in manifest["items"] if i.get("production_ready")),
            "errors": sum(1 for i in issues if i["severity"] == "error"),
            "warnings": sum(1 for i in issues if i["severity"] == "warning"),
            "writes": dict(store.writes),
            **{f"status_{k.replace('-', '_')}": v for k, v in counts.items() if v},
        }
        artifact = ArtifactOutput("asset-manifest", manifest, metadata=metadata)

        blocking = self._blocking(settings, issues)
        if blocking:
            return StepResult("FAILED", artifacts=[artifact], retryable=False,
                              error=f"asset manifest has blocking issues: "
                                    f"{', '.join(sorted({i['code'] for i in blocking}))}")
        return StepResult.success(
            [artifact],
            message=f"{metadata['items']} assets: {metadata['production_ready']} "
                    f"production-ready, {metadata['placeholders']} placeholders, "
                    f"{metadata['errors']} errors")

    @staticmethod
    def _blocking(settings, issues):
        fail_on = set(settings.get("fail_on") or [])
        strict = bool(settings.get("strict"))
        return [i for i in issues
                if i["code"] in fail_on or (strict and i["severity"] == "error")]

    def _manifest(self, design, scaffold, inputs, context, policy, result, title_id, slug):
        items = result.items
        issues = list(result.issues)

        budget = (design.get("scope") or {}).get("asset_budget")
        total_cost = round(sum(i["est_cost"] for i in items if i["status"] != "cut"), 2)
        total_hours = round(sum(i["est_hours"] for i in items if i["status"] != "cut"), 2)
        if isinstance(budget, (int, float)) and total_cost > budget:
            issues.append({"code": "over-budget", "severity": "warning",
                           "message": f"estimated asset cost {total_cost} exceeds the design's "
                                      f"asset_budget {budget}"})

        for pid, role, limit in _bundle_limits(scaffold):
            if result.bytes_total > limit * 1024 * 1024:
                issues.append({
                    "code": "over-bundle-size",
                    "severity": "error" if role == "required" else "warning",
                    "message": f"delivered assets are {result.bytes_total} bytes; {pid} "
                               f"allows {limit} MB for the whole bundle"})

        dimensions = {i.get("dimension") for i in items}
        types = {i["type"] for i in items}
        spec = policy.pipeline
        pipeline = {}
        if "2d" in dimensions and spec.get("two_d"):
            pipeline["2d"] = spec["two_d"]
        if "3d" in dimensions:
            if spec.get("three_d"):
                pipeline["3d"] = spec["three_d"]
            pipeline["texture_compression"] = list(spec.get("texture_compression") or [])
            pipeline["mesh_compression"] = list(spec.get("mesh_compression") or [])
        if types & {"sfx", "music"}:
            pipeline["audio_format"] = list(spec.get("audio_format") or [])

        now = self.clock().astimezone(datetime.timezone.utc).replace(microsecond=0)
        produced_at = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        manifest = {
            "provenance": provenance.build(
                "asset-manifest",
                artifact_id=provenance.artifact_id("asset-manifest", slug, produced_at,
                                                   context.execution),
                produced_by=provenance.producer(self.role),
                produced_at=produced_at,
                inputs=provenance.pin_inputs(inputs),
                schema_version=MANIFEST_SCHEMA_VERSION,
                opportunity_id=(design.get("provenance") or {}).get("opportunity_id") or None,
                title_id=title_id),
            "title_id": title_id,
            "items": items,
            "pipeline": pipeline,
            "total_est_cost": total_cost,
            "total_est_hours": total_hours,
            "budget": budget if isinstance(budget, (int, float)) else None,
            "complete": bool(items) and all(i["status"] in ("integrated", "cut") for i in items),
            "policy": policy.pin(),
            "issues": issues,
            "generation": {"backends": result.backends},
        }
        return provenance.seal(manifest)

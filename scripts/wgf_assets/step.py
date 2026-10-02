"""The `assets` workflow step: a game design in, an asset manifest out.

    inputs   game-design (required), scaffold-record (optional: the target platforms, whose
             bundle-size limits the delivered files are checked against),
             production-quality-report and visual-qa-report (optional: on re-entry, the
             report that routed the run back to `assets`; only the items it names are
             rebuilt, and its findings reach the author)
    outputs  asset-manifest

The work list is the design's build_spec.assets (requirements.py): role, dimension,
description, readability, count and spec, with the palette of build_spec.visual_identity.
Each requirement is supplied, in order, by a library (library.json), the 2D author (an SVG,
author.py), the 3D model author (wgf_assets.model_author, when installed), or a placeholder
- and every delivered file is judged (quality.py, core/reference/asset-quality.yaml).

Settings come from `factory.assets` in workspace/config/factory.yaml, overridden by the
step's `with:` block:

    root           where the game repository checkout is; files go under public/assets/.
                   Default: the run's game repository checkout, found as every step finds
                   it (wgflib.checkout: with: repo_dir, WGF_GAME_REPO, the scaffold-record's
                   local_path, factory.checkouts + its name), so the files land in
                   <checkout>/public/assets/ where develop builds and commits them. Without a
                   scaffold-record, or when that checkout does not exist:
                   .factory/assets/<title> under the Factory root - git-ignored scratch.
                   Relative paths resolve against the Factory root, never the working
                   directory.
    libraries      directories holding an index.json of reusable assets and/or a
                   library.json mapping requirement ids and roles to licensed files.
                   Relative paths resolve against the project directory. Default: none.
    author         {kind: none | command, argv, svg_from, timeout_seconds,
                   idle_timeout_seconds, repair_rounds}: who draws a 2D requirement as SVG
                   (author.py). Default: none - no author, so what no library supplies is
                   a placeholder.
    placeholders   {enabled: true, backends: [2d-assets-mcp, procedural], <backend>: {...}}.
                   `blender` is put first automatically when a requirement carries a
                   buildable `model` spec; its settings block is `placeholders.blender`.
    optimize       lossless in-place optimization of files the step writes. Default: true.
    runtime_manifest  write public/assets/assets.json, the runtime asset manifest game code
                   loads from. Default: true.
    prune          remove placeholders and packed atlases the step wrote before that nothing
                   references now. Default: true.
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

from wgflib import checkout, paths, provenance
from wgflib.workflow import ArtifactOutput, StepResult, WorkflowStep
from wgflib.yamllite import YamlError, load_file

from . import modelspec
from .blender import BACKEND_ID as BLENDER
from .author import AuthorError, build_author
from .library import open_libraries
from .pipeline import AssetPipeline, AssetStore
from .placeholders import build_backends
from .policy import PolicyError, load_policy
from .quality import load_bars
from .requirements import RequirementError, inspect, slugify

try:  # the 3D model author is optional: absent, 3D requirements fall back to placeholders
    from . import model_author as _model_author
except ImportError:
    _model_author = None

__all__ = ["AssetsStep", "MANIFEST_SCHEMA_VERSION", "resolve_settings"]

MANIFEST_SCHEMA_VERSION = provenance.version_of("asset-manifest")
READABLE_DESIGN_MAJOR = 1
DEFAULT_BACKENDS = ["2d-assets-mcp", "procedural"]
# Reports that can route a run back to this step, and so name what to rebuild.
REENTRY_REPORTS = ("production-quality-report", "visual-qa-report")


def _config_section(config, name):
    if hasattr(config, "section"):
        return config.section(name)
    return dict((config or {}).get(name) or {})


def resolve_settings(context):
    """factory.assets, with the step's `with:` block laid over it."""
    settings = copy.deepcopy(_config_section(context.config, "assets"))
    for key, value in (context.params or {}).items():
        if key in ("placeholders", "author", "model_author") and isinstance(value, dict):
            merged = dict(settings.get(key) or {})
            merged.update(value)
            settings[key] = merged
        else:
            settings[key] = value
    placeholders = dict(settings.get("placeholders") or {})
    placeholders.setdefault("enabled", True)
    placeholders.setdefault("backends", list(DEFAULT_BACKENDS))
    settings["placeholders"] = placeholders
    settings.setdefault("optimize", True)
    settings.setdefault("runtime_manifest", True)
    settings.setdefault("prune", True)
    settings.setdefault("libraries", [])
    settings.setdefault("fail_on", [])
    settings["author"] = dict(settings.get("author") or {})
    # The 3D model author (model_author.py): `{kind: command, argv, ...}`, or none. Only a
    # configured one is asked; unconfigured, 3D requirements go to the next backend
    # (a design's own model spec built by Blender, then placeholders) without a warning.
    settings["model_author"] = dict(settings.get("model_author") or {})
    return settings


def _id_words(text):
    return set(re.findall(r"[a-z][a-z0-9-]*", (text or "").lower()))


def rebuild_list(reports, requirements):
    """{requirement id: [finding]} named by re-entry reports whose routes include `assets`:
    a production-quality check that failed with route assets (its `assets`, else the ids
    its summary names), a visual-qa finding with route assets (the ids its id or summary
    names). A variant id (`tile-2`) names its requirement (`tile`)."""
    ids = {r.id for r in requirements}
    variants = {v: r.id for r in requirements for v in r.variant_ids()}

    def resolve(names):
        out = set()
        for name in names:
            if name in ids:
                out.add(name)
            elif name in variants:
                out.add(variants[name])
        return out

    found = {}
    for kind, report in reports:
        if "assets" not in (report.get("routes") or []):
            continue
        if kind == "production-quality-report":
            for check in report.get("checks") or []:
                if check.get("route") != "assets" or check.get("status") == "PASS":
                    continue
                named = resolve(check.get("assets") or []) or resolve(
                    _id_words(check.get("summary")))
                for rid in sorted(named):
                    found.setdefault(rid, []).append(
                        f"{check.get('id')}: {check.get('summary')}")
        else:
            for finding in report.get("findings") or []:
                if finding.get("route") != "assets":
                    continue
                named = resolve(_id_words(finding.get("id")) | _id_words(finding.get("summary")))
                for rid in sorted(named):
                    found.setdefault(rid, []).append(
                        f"{finding.get('severity')} {finding.get('category')}: "
                        f"{finding.get('summary')}")
    return found


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
        # Writing into the game repository takes the checkout's lock (wgflib.checkout).
        with checkout.StepLease(context) as lease:
            return self._execute(inputs, context, lease)

    def _asset_root(self, settings, scaffold, slug, context):
        """(root, in the checkout?): where the asset files go - see the module docstring."""
        if settings.get("root"):
            root = checkout.resolve(settings["root"])
            in_checkout = False
            if scaffold is not None:
                try:
                    repo, _source = checkout.locate(context.config, scaffold, "assets",
                                                    context.params or {})
                    in_checkout = os.path.realpath(repo) == os.path.realpath(root)
                except checkout.CheckoutError:
                    pass
            return root, in_checkout
        if scaffold is not None:
            try:
                repo, source = checkout.locate(context.config, scaffold, "assets",
                                               context.params or {}, logger=context.logger)
            except checkout.CheckoutError as exc:
                context.logger.warning("no game repository checkout for the assets",
                                       problem=str(exc))
            else:
                if os.path.isdir(repo):
                    return repo, True
                context.logger.warning(
                    "the game repository is not checked out; assets go to scratch",
                    checkout=repo, source=source)
        return os.path.join(paths.PROJECT, ".factory", "assets", slug), False

    def _execute(self, inputs, context, lease):
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
        try:
            author = build_author(settings["author"], context.config)
        except AuthorError as exc:
            return StepResult.failed(f"asset author: {exc}", retryable=False)
        reports = [(kind, inputs.load(kind)) for kind in REENTRY_REPORTS if kind in inputs]
        rebuild = rebuild_list(reports, requirements)
        if reports:
            context.logger.info("re-entry: rebuilding what the reports name",
                                reports=[k for k, _ in reports], items=sorted(rebuild))
        identity = (design.get("build_spec") or {}).get("visual_identity") \
            if isinstance(design.get("build_spec"), dict) else None

        title_id = design.get("title_id") or context.project_id or "title"
        slug = slugify(title_id, "title")
        root, in_checkout = self._asset_root(settings, scaffold, slug, context)
        if in_checkout:
            try:
                lease.take(root)
            except checkout.CheckoutLocked as exc:
                return StepResult.blocked(str(exc))
        store = AssetStore(root)
        libraries, library_problems = open_libraries(settings["libraries"], base=paths.PROJECT)
        for problem in library_problems:
            context.logger.warning("asset library unavailable", problem=problem)

        placeholders = settings["placeholders"]
        order = list(placeholders.get("backends") or [])
        if BLENDER not in order and any(modelspec.buildable(r.model) for r in requirements):
            # A design that describes its models asked for them to be built: Blender goes
            # first for those (it supports nothing else), whether or not it is installed -
            # the manifest then says why each one was not built.
            order.insert(0, BLENDER)
        backends = build_backends(order, placeholders)
        pipeline = AssetPipeline(policy, store, backends, libraries, logger=context.logger,
                                 placeholders=bool(placeholders.get("enabled")),
                                 optimize=bool(settings.get("optimize")),
                                 runtime_manifest=bool(settings.get("runtime_manifest")),
                                 prune=bool(settings.get("prune")), title_id=title_id,
                                 author=author, identity=identity, bars=load_bars(),
                                 model_author=(getattr(_model_author, "produce_model", None)
                                               if settings["model_author"].get("kind")
                                               not in (None, "none") else None),
                                 rebuild=rebuild, settings=settings, context=context,
                                 work_dir=self._work_dir(context, slug),
                                 locales=(design.get("scope") or {}).get("locales") or ())
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
            "quality_failed": sum(1 for i in manifest["items"]
                                  if (i.get("quality") or {}).get("verdict") == "fail"),
            "rebuilt": len(rebuild),
            "production_ready": sum(1 for i in manifest["items"] if i.get("production_ready")),
            "errors": sum(1 for i in issues if i["severity"] == "error"),
            "warnings": sum(1 for i in issues if i["severity"] == "warning"),
            "writes": dict(store.writes, **({"removed": len(store.removed)}
                                            if store.removed else {})),
            "atlases": len(manifest.get("atlases") or []),
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
    def _work_dir(context, slug):
        """Where author requests, logs and rejected files go: the run's directory, else
        git-ignored scratch under the project."""
        run_dir = getattr(context, "run_dir", None)
        if run_dir:
            return os.path.join(run_dir, "assets",
                                f"{getattr(context, 'visit', 1)}-{getattr(context, 'attempt', 1)}")
        return os.path.join(paths.PROJECT, ".factory", "assets-work", slug)

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
            "atlases": result.atlases or None,
            "runtime_manifest": result.runtime_manifest,
            "issues": issues,
            "generation": {"backends": result.backends},
        }
        return provenance.seal({k: v for k, v in manifest.items() if v is not None
                                or k == "budget"})

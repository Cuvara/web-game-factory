"""The `design` step: title-strategy in, game-design out.

    title-strategy ──► author draft ──► finalize ──► buildability ──► consistency ──► game-design
                        (creative)      (platforms,    (MVP buildable    (exit guard)
                                         tiers)         without guessing)

The step has no side effect outside the run: it reads core/ and its input, and returns one
artifact. Re-executing it with the same input and clock produces the same content hash, which
is its whole idempotency story.

Outcomes, per docs/workflow-module-contract.md §7:

    no title-strategy in the run               WAITING_FOR_INPUT
    strategy schema major version unknown      FAILED, not retryable
    pinned platform profile missing or moved   BLOCKED - re-pin in a superseding strategy
    author cannot write a design               FAILED, not retryable
    MVP not buildable (dangling references)    FAILED, not retryable, nothing persisted
    a blocking consistency rule breached       FAILED, route `descope`, not retryable, with the
                                               game-design persisted as evidence - cut scope;
                                               never relax the rule
    otherwise                                  SUCCESS
"""

import datetime

from wgflib.hashing import content_hash
from wgflib.workflow import ArtifactOutput, StepResult, WorkflowStep

from . import consistency
from .authors import AUTHORS, AuthorError, resolve_author
from .compose import buildability, finalize
from .platforms import PlatformError, load_platforms

__all__ = ["DesignStep", "SCHEMA_VERSION", "ROLE"]

SCHEMA_VERSION = "1.1.0"
ROLE = "game-designer"
READS_STRATEGY_MAJOR = "1"
DEFAULT_AUTHOR = "archetype"


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class DesignStep(WorkflowStep):
    type = "design"

    # Seams for tests; a real run uses core/.
    clock = staticmethod(utc_now)
    platforms_dir = None
    rules = None

    def execute(self, inputs, context):
        if "title-strategy" in inputs.missing:
            return StepResult.waiting_for_input("design needs a title-strategy; run `strategy` first")

        ref = inputs.refs["title-strategy"]
        major = (ref.schema_version or "1").split(".")[0]
        if major != READS_STRATEGY_MAJOR:
            return StepResult.failed(
                f"title-strategy schema {ref.schema_version} is not readable by this module "
                f"(reads {READS_STRATEGY_MAJOR}.x)", retryable=False)
        strategy = inputs.load("title-strategy")
        title_id = strategy.get("title_id") or context.project_id
        if not title_id:
            return StepResult.failed("title-strategy has no title_id and the run has no project id",
                                     retryable=False)

        try:
            platforms = load_platforms(strategy, self.platforms_dir)
        except PlatformError as exc:
            return StepResult.blocked(str(exc))

        author_name = (self.params.get("author")
                       or ((context.config or {}).get("design") or {}).get("author")
                       or DEFAULT_AUTHOR)
        brief = {"title_id": title_id, "strategy": strategy, "platforms": platforms,
                 "params": dict(self.params),
                 # For authors that run something (the `agent` author): where this
                 # attempt's files go, and the installation's configuration.
                 "config": context.config or {},
                 "run_dir": getattr(context, "run_dir", None),
                 "visit": getattr(context, "visit", 1),
                 "attempt": getattr(context, "attempt", 1)}
        try:
            author = resolve_author(author_name)
            draft = author.draft(brief)
        except AuthorError as exc:
            return StepResult.failed(f"design author {author_name!r}: {exc}", retryable=False)

        design = finalize(draft, platforms, title_id)
        problems = buildability(design)
        if problems:
            context.logger.error("design is not buildable", problems=problems)
            return StepResult.failed(
                f"design is not buildable without guessing ({len(problems)} problem(s)): "
                + "; ".join(problems[:5]), retryable=False)

        now = self.clock()
        block, blocking, warnings = consistency.evaluate(design, strategy, platforms, now, self.rules)
        design["consistency"] = block
        artifact = self._with_provenance(design, strategy, ref, title_id, now, context,
                                         getattr(author, "actor", "automation"))

        engine = design["engine"]["type"]
        mvp = sum(1 for f in design["features"] if f["tier"] == "mvp")
        metadata = {"author": author_name, "engine": engine, "consistency": block["status"],
                    "mvp_features": mvp, "warnings": warnings or None}
        metadata = {k: v for k, v in metadata.items() if v is not None}
        output = ArtifactOutput("game-design", artifact, metadata=metadata)
        context.logger.info("design composed", engine=engine, mvp_features=mvp,
                            consistency=block["status"], breached=blocking or None, warnings=warnings or None)

        if blocking:
            return StepResult("FAILED", route="descope", retryable=False, artifacts=[output],
                              error=f"design consistency failed on {', '.join(blocking)}: cut scope, "
                                    "do not relax the rules")
        return StepResult.success(
            [output], message=f"{engine} design, {mvp} mvp features, consistency {block['status']}"
                              + (f", {len(warnings)} warning(s) for G3" if warnings else ""))

    def _with_provenance(self, design, strategy, ref, title_id, now, context, actor):
        source = strategy.get("provenance") or {}
        provenance = {
            "artifact_id": f"wgf:game-design:{title_id}:{now[:10].replace('-', '')}-"
                           f"{min(context.execution, 99):02d}",
            "artifact_type": "game-design",
            "schema_version": SCHEMA_VERSION,
            "title_id": title_id,
            "produced_by": {"role": ROLE, "actor": actor},
            "produced_at": now,
            "inputs": [],
            "content_hash": "",
            "status": "draft",
        }
        if strategy.get("opportunity_id"):
            provenance["opportunity_id"] = strategy["opportunity_id"]
        if source.get("artifact_id") and ref.content_hash:
            provenance["inputs"].append({"artifact_id": source["artifact_id"],
                                         "artifact_type": "title-strategy",
                                         "content_hash": ref.content_hash})
        artifact = {"provenance": provenance}
        artifact.update(design)
        artifact["provenance"]["content_hash"] = content_hash(artifact)
        return artifact


def register(registry):
    registry.register(DesignStep.type, DesignStep)
    return registry


assert DEFAULT_AUTHOR in AUTHORS

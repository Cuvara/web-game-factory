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
    experience contract does not hold          FAILED, not retryable, nothing persisted
    production art or UI not stated            FAILED, not retryable, nothing persisted
                                               (presentation.py: a role, readability or
                                               UI token missing)
    no depth stated (no meta loop, goal ladder,  FAILED, not retryable, nothing persisted
    content schedule, first session or return    (depth.py, core/reference/design-depth.yaml;
    hooks; an MVP entry the MVP does not build)  checked only when no blocking rule breached)
    a blocking consistency rule breached       FAILED, route `descope`, not retryable, with the
                                               game-design persisted as evidence - cut scope;
                                               never relax the rule. An author that repairs its
                                               draft is shown the breaches and asked again
                                               first (consistency.breach_problems)
    otherwise                                  SUCCESS
"""

import datetime
import re

from wgflib import provenance
from wgflib.workflow import ArtifactOutput, StepResult, WorkflowStep
from wgflib.workflow.contracts import ArtifactContracts

from . import consistency, depth, experience, presentation
from .authors import AUTHORS, AuthorError, resolve_author
from .compose import buildability, finalize
from .platforms import PlatformError, load_platforms

__all__ = ["DesignStep", "SCHEMA_VERSION", "ROLE"]

SCHEMA_VERSION = provenance.version_of("game-design")
ROLE = "game-designer"
READS_STRATEGY_MAJOR = "1"
DEFAULT_AUTHOR = "archetype"
# How often an author that can repair its draft (the `agent` author) is shown what made the
# composed design invalid - the game-design schema, the buildability check, and the blocking
# consistency breaches - and asked again, before the step fails. Each round is one more
# author session.
MAX_REPAIR_ROUNDS = 2


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _brief_dimension(brief):
    """'3d' or '2d' when the brief names exactly one."""
    words = set(re.findall(r"[a-z0-9][a-z0-9-]*", brief.lower()))
    named = {d for d, w in (("3d", {"3d", "three-dimensional"}), ("2d", {"2d", "two-dimensional"}))
             if words & w}
    return named.pop() if len(named) == 1 else None


class DesignStep(WorkflowStep):
    type = "design"

    # Seams for tests; a real run uses core/.
    clock = staticmethod(utc_now)
    platforms_dir = None
    rules = None
    experience_rules = None
    depth_rules = None

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
        except AuthorError as exc:
            return StepResult.failed(f"design author {author_name!r}: {exc}", retryable=False)
        contracts = ArtifactContracts()
        for repair_round in range(MAX_REPAIR_ROUNDS + 1):
            try:
                draft = author.draft(brief)
            except AuthorError as exc:
                return StepResult.failed(f"design author {author_name!r}: {exc}",
                                         retryable=False)
            outcome = self._compose(draft, platforms, title_id, strategy, ref, context, author,
                                    contracts)
            problems = outcome["problems"]
            if not problems:
                break
            if not getattr(author, "repairs", False) or repair_round == MAX_REPAIR_ROUNDS:
                after = f" after {repair_round} repair round(s)" if repair_round else ""
                if outcome["consistency"]:
                    # The design is valid and persisted; it is the scope that is wrong.
                    break
                if outcome["unbuildable"]:
                    context.logger.error("design is not buildable", problems=problems,
                                         repair_rounds=repair_round)
                    return StepResult.failed(
                        f"design is not buildable without guessing{after} "
                        f"({len(problems)} problem(s)): " + "; ".join(problems[:5]),
                        retryable=False)
                if outcome["experience"]:
                    context.logger.error("the design's experience contract does not hold",
                                         problems=problems, repair_rounds=repair_round)
                    return StepResult.failed(
                        f"the design's experience contract does not hold{after} "
                        f"({len(problems)} problem(s)): " + "; ".join(problems[:6]),
                        retryable=False)
                if outcome["presentation"]:
                    context.logger.error("the design does not state its production art and UI",
                                         problems=problems, repair_rounds=repair_round)
                    return StepResult.failed(
                        f"the design does not state its production art and UI{after} "
                        f"({len(problems)} problem(s)): " + "; ".join(problems[:6]),
                        retryable=False)
                if outcome["depth"]:
                    context.logger.error("the design does not state its depth",
                                         problems=problems, repair_rounds=repair_round)
                    return StepResult.failed(
                        f"the design does not state why a player comes back{after} "
                        f"({len(problems)} problem(s)): " + "; ".join(problems[:6]),
                        retryable=False)
                context.logger.error("design is not a valid game-design", problems=problems[:20],
                                     repair_rounds=repair_round)
                return StepResult.failed(
                    f"design is not a valid game-design{after} ({len(problems)} problem(s)): "
                    + "; ".join(problems[:6]), retryable=False)
            context.logger.warning("design draft is invalid; asking the author to repair it",
                                   problems=problems[:20], repair_round=repair_round + 1)
            brief = dict(brief, repair={"round": repair_round + 1, "problems": problems[:60],
                                        "previous_draft": draft})
        design, artifact, block, blocking, warnings = (
            outcome["design"], outcome["artifact"], outcome["block"], outcome["blocking"],
            outcome["warnings"])

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

    def _compose(self, draft, platforms, title_id, strategy, ref, context, author, contracts):
        """The draft finalized into the game-design artifact, and what makes it invalid: the
        buildability check, then - only when that passes - the artifact's own schema."""
        design = finalize(draft, platforms, title_id)
        carried = strategy.get("research")
        if isinstance(carried, dict) and carried.get("research_version") == 2 and \
                not isinstance(design.get("research"), dict):
            # Whatever the author wrote, the research the design rests on is not dropped.
            design["research"] = dict(carried, applied=[{
                "field": "research", "source": "default",
                "detail": f"carried from the strategy; the {getattr(author, 'name', 'design')!r} "
                          f"author recorded no research-based decisions"}])
        if strategy.get("brief"):
            # The person's idea, carried from the strategy: the design is derived from it,
            # whatever the author wrote.
            design["brief"] = strategy["brief"]
            named = _brief_dimension(strategy["brief"])
            built = (design.get("engine") or {}).get("dimension")
            if named and built and named != built:
                design.setdefault("open_questions", []).append(
                    f"The brief names {named}; this design is {built}, the dimension of the "
                    f"buildable concept research selected. Realising the brief in {named} is "
                    f"a design change: an agent author, or a new concept, not this draft.")
        outcome = {"design": design, "artifact": None, "block": None, "blocking": None,
                   "warnings": None, "problems": [], "unbuildable": False,
                   "experience": False, "presentation": False, "depth": False,
                   "consistency": False}
        problems = buildability(design)
        if problems:
            outcome.update(problems=problems, unbuildable=True)
            return outcome
        # What a first-time player must be able to tell: held by reference and number.
        problems = experience.check(design, strategy, self.experience_rules)
        if problems:
            outcome.update(problems=problems, experience=True)
            return outcome
        # What the finished game looks like: production art per readable role, and the UI.
        problems = presentation.check(design, self.experience_rules)
        if problems:
            outcome.update(problems=problems, presentation=True)
            return outcome
        now = self.clock()
        block, blocking, warnings = consistency.evaluate(design, strategy, platforms, now,
                                                         self.rules)
        if not blocking:
            # Why a player comes back: a design that must cut scope first is not asked yet.
            problems = depth.check(design, self.depth_rules)
            if problems:
                outcome.update(problems=problems, depth=True)
                return outcome
        design["consistency"] = block
        artifact = self._with_provenance(design, strategy, ref, title_id, now, context,
                                         getattr(author, "actor", "automation"))
        problems = list(contracts("game-design", artifact))
        outcome.update(artifact=artifact, block=block, blocking=blocking, warnings=warnings,
                       problems=problems)
        if blocking and not problems:
            # A schema-valid design that breaches a blocking rule: show the author what it
            # breached and ask again. Only when the rounds run out does the step descope.
            outcome.update(problems=consistency.breach_problems(block, blocking, self.rules),
                           consistency=True)
        return outcome

    def _with_provenance(self, design, strategy, ref, title_id, now, context, actor):
        pinned = provenance.pin("title-strategy", strategy, ref.content_hash)
        record = provenance.build(
            "game-design",
            artifact_id=provenance.artifact_id("game-design", title_id, now, context.execution),
            produced_by=provenance.producer(ROLE, actor),
            produced_at=now,
            inputs=[pinned] if pinned else [],
            schema_version=SCHEMA_VERSION,
            opportunity_id=strategy.get("opportunity_id") or None,
            title_id=title_id)
        artifact = {"provenance": record}
        artifact.update(design)
        return provenance.seal(artifact)


def register(registry):
    registry.register(DesignStep.type, DesignStep)
    return registry


assert DEFAULT_AUTHOR in AUTHORS

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
    the content is not stated (no units, a     FAILED, not retryable, nothing persisted
    unit kind, curve or ending the genre       (content.py, core/reference/genre-models.yaml;
    family refuses, mastery unstated)          checked only when no blocking rule breached)
    a blocking consistency rule breached       FAILED, route `descope`, not retryable, with the
                                               game-design persisted as evidence - cut scope;
                                               never relax the rule. An author that repairs its
                                               draft is shown the breaches and asked again
                                               first (consistency.breach_problems)
    otherwise                                  SUCCESS
"""

import copy
import datetime
import json
import os
import re

from wgflib import provenance
from wgflib.workflow import ArtifactOutput, StepResult, WorkflowStep
from wgflib.workflow.contracts import ArtifactContracts

from . import consistency, content, depth, experience, presentation
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
MAX_REPAIR_ROUNDS = 3
# Where a visit's last rejected draft and its problems are kept between executions
# (`<run_dir>/design/<visit>-last-draft.json`): a resumed step continues the repair from it
# instead of asking the author for a new game.
LAST_DRAFT = "{visit}-last-draft.json"


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
    content_models = None

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
        # Re-entered through `design-gap`: the prototype-report names what the design did not
        # decide, and the draft starts from the design those gaps were found in (this step's
        # own previous output), so the design is repaired, never replaced.
        gaps = []
        if "prototype-report" in inputs.refs:
            report = inputs.load("prototype-report")
            gaps = [g for g in report.get("design_gaps") or [] if isinstance(g, dict)]
        if gaps:
            previous = self._previous_design(context)
            if previous is None:
                return StepResult.failed(
                    "a prototype-report names design gaps but this run holds no earlier "
                    "game-design to repair", retryable=False)
            brief["gaps"] = gaps
            brief["previous_design"] = previous
        try:
            author = resolve_author(author_name)
        except AuthorError as exc:
            return StepResult.failed(f"design author {author_name!r}: {exc}", retryable=False)
        contracts = ArtifactContracts()
        self._inputs = inputs
        # A resumed execution of this visit continues the repair of the last rejected draft
        # (an author that repairs is not asked for a new game and billed for it again).
        last = self._last_draft(context) if getattr(author, "repairs", False) else None
        accepted = None
        if last and not last["problems"]:
            # The step accepted this draft and something after it (the engine's lineage
            # check, a dead driver) lost it: compose it again, no author session.
            accepted = last["draft"]
            context.logger.info("design composes the draft the step last accepted")
        elif last:
            brief = dict(brief, repair={"round": 0, "problems": last["problems"][:60],
                                        "previous_draft": last["draft"]})
            context.logger.info("design resumes the repair of the last rejected draft",
                                problems=last["problems"][:20])
        for repair_round in range(MAX_REPAIR_ROUNDS + 1):
            try:
                draft = accepted if accepted is not None else author.draft(brief)
                accepted = None
            except AuthorError as exc:
                return StepResult.failed(f"design author {author_name!r}: {exc}",
                                         retryable=False)
            outcome = self._compose(draft, platforms, title_id, strategy, ref, context, author,
                                    contracts)
            problems = outcome["problems"]
            if (not problems and outcome["consistency_problems"]
                    and getattr(author, "repairs", False)
                    and repair_round < MAX_REPAIR_ROUNDS):
                # A blocking consistency breach is repairable by an author that repairs:
                # it is asked to carry the concept or drop the foreign mechanic before the
                # breach becomes a descope.
                problems = outcome["consistency_problems"]
            if not problems:
                if outcome["consistency_problems"] and getattr(author, "repairs", False):
                    # Descoped after its rounds: the draft is kept, so a resume continues.
                    self._keep_last_draft(context, draft, outcome["consistency_problems"])
                break
            if getattr(author, "repairs", False):
                self._keep_last_draft(context, draft, problems)
            if not getattr(author, "repairs", False) or repair_round == MAX_REPAIR_ROUNDS:
                after = f" after {repair_round} repair round(s)" if repair_round else ""
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
                if outcome["content"]:
                    context.logger.error("the design does not specify its content",
                                         problems=problems, repair_rounds=repair_round)
                    return StepResult.failed(
                        f"the design does not specify its content{after} "
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
        if getattr(author, "repairs", False):
            self._keep_last_draft(context, outcome["draft"], [])
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
        outcome = {"draft": copy.deepcopy(draft), "design": design, "artifact": None,
                   "block": None, "blocking": None,
                   "warnings": None, "problems": [], "unbuildable": False,
                   "experience": False, "presentation": False, "depth": False,
                   "content": False, "consistency_problems": []}
        problems = buildability(design)
        if problems:
            outcome.update(problems=problems, unbuildable=True)
            return outcome
        # Every check the draft is held to runs, and every problem is collected, so an author
        # that repairs is asked once for everything rather than once per check per round.
        # What a first-time player must be able to tell: held by reference and number.
        found = experience.check(design, strategy, self.experience_rules)
        if found:
            outcome.update(experience=True)
            problems += found
        # What the finished game looks like: production art per readable role, and the UI.
        found = presentation.check(design, self.experience_rules)
        if found:
            outcome.update(presentation=True)
            problems += found
        now = self.clock()
        block, blocking, warnings = consistency.evaluate(design, strategy, platforms, now,
                                                         self.rules)
        if blocking:
            # A breached blocking rule is `descope` for an author that cannot repair; one
            # that can is told which rule it breached, what was measured against what
            # (consistency.breach_problems) and - for the two concept rules - what the
            # concept view found, first. A breach was the one invalid-design class the
            # author was never shown, so a design whose only fault was three assets too
            # many died at `descope` with the fix one round away.
            ruleset = self.rules or consistency.load_rules()
            concept = consistency.concept_view(
                design, strategy, ruleset.get("concept_terms") or {},
                tuple(ruleset.get("detail_terms") or ()))
            notes = {
                "concept_mechanics_carried":
                    f"The strategy's concept names {concept.get('uncarried')} and the "
                    "design's core loop, MVP features and MVP controls do not.",
                "design_adds_no_foreign_mechanic":
                    f"The design's own text names {concept.get('foreign')}, which the "
                    "strategy nowhere does - remove it, or say it in the strategy's words.",
            }
            for rule_id in blocking:
                stated = consistency.breach_problems(block, [rule_id], ruleset) or [
                    f"consistency {rule_id} is breached. "
                    "Cut scope to hold the rule; never relax the rule."]
                note = notes.get(rule_id)
                outcome["consistency_problems"] += [
                    f"{problem} {note}" if note else problem for problem in stated]
        else:
            # Why a player comes back: a design that must cut scope first is not asked yet.
            found = depth.check(design, self.depth_rules)
            if found:
                outcome.update(depth=True)
                problems += found
            # What the player actually plays: every unit, held to its genre family's bars.
            models = self.content_models or content.load_models()
            found, results = content.check(design, strategy, models)
            if found:
                outcome.update(content=True)
                problems += found
            else:
                block["rule_results"] = list(block["rule_results"]) + results
                family, _why = content.resolve_family(strategy, design, models)
                if family:
                    block["content_model"] = content.content_model_record(models, family)
        if problems:
            outcome.update(problems=problems)
            return outcome
        design["consistency"] = block
        artifact = self._with_provenance(design, strategy, ref, title_id, now, context,
                                         getattr(author, "actor", "automation"),
                                         inputs=self._inputs)
        outcome.update(artifact=artifact, block=block, blocking=blocking, warnings=warnings,
                       problems=list(contracts("game-design", artifact)))
        return outcome

    @staticmethod
    def _last_draft_path(context):
        run_dir = getattr(context, "run_dir", None)
        if not run_dir:
            return None
        return os.path.join(run_dir, "design",
                            LAST_DRAFT.format(visit=getattr(context, "visit", 1)))

    def _last_draft(self, context):
        path = self._last_draft_path(context)
        if not path or not os.path.exists(path):
            return None
        try:
            with open(path, encoding="utf-8") as handle:
                kept = json.load(handle)
        except (OSError, ValueError):
            return None
        if (isinstance(kept, dict) and isinstance(kept.get("draft"), dict)
                and isinstance(kept.get("problems"), list)):
            return kept
        return None

    def _keep_last_draft(self, context, draft, problems):
        path = self._last_draft_path(context)
        if not path:
            return
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as handle:
                json.dump({"problems": list(problems), "draft": draft}, handle)
        except (OSError, TypeError, ValueError):
            pass

    def _drop_last_draft(self, context):
        path = self._last_draft_path(context)
        if path and os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass

    @staticmethod
    def _previous_design(context):
        """The game-design this step produced last, read from the run directory; None when
        there is none (or it cannot be read)."""
        run_dir = getattr(context, "run_dir", None)
        for ref in getattr(context, "previous_outputs", None) or []:
            if getattr(ref, "type", None) != "game-design" or not run_dir:
                continue
            path = os.path.join(run_dir, ref.location)
            try:
                with open(path, encoding="utf-8") as handle:
                    loaded = json.load(handle)
            except (OSError, ValueError):
                return None
            return loaded if isinstance(loaded, dict) else None
        return None

    def _with_provenance(self, design, strategy, ref, title_id, now, context, actor,
                         inputs=None):
        # Every input this execution consumed is pinned - the strategy, and the
        # prototype-report a design-gap return carries - or the engine refuses the lineage.
        pins = provenance.pin_inputs(inputs) if inputs is not None else []
        if not any(p.get("artifact_type") == "title-strategy" for p in pins):
            pinned = provenance.pin("title-strategy", strategy, ref.content_hash)
            if pinned:
                pins.insert(0, pinned)
        record = provenance.build(
            "game-design",
            artifact_id=provenance.artifact_id("game-design", title_id, now, context.execution),
            produced_by=provenance.producer(ROLE, actor),
            produced_at=now,
            inputs=pins,
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

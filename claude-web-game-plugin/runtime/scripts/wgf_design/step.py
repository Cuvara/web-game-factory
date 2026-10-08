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
    the run's previous game-design unreadable  FAILED, not retryable (a revising author only:
                                               it changed on disk after the run recorded it)
    MVP not buildable (dangling references)    FAILED, not retryable, nothing persisted
    experience contract does not hold          FAILED, not retryable, nothing persisted
    production art or UI not stated            FAILED, not retryable, nothing persisted
                                               (presentation.py: a role, readability or
                                               UI token missing)
    a feature the brief, strategy or genre     FAILED, not retryable, nothing persisted
    family names is not evaluated, or an       (features.py, core/reference/
    evaluation contradicts its tier or the     feature-catalogue.yaml: include, later or
    platforms                                  cut, each with a reason)
    no depth stated (no meta loop, goal ladder,  FAILED, not retryable, nothing persisted
    content schedule, first session or return    (depth.py, core/reference/design-depth.yaml;
    hooks; an MVP entry the MVP does not build)  checked only when no blocking rule breached)
    the content is not stated (no units, a     FAILED, not retryable, nothing persisted
    unit kind, curve or ending the genre       (content.py, core/reference/genre-models.yaml;
    family refuses, mastery unstated)          checked only when no blocking rule breached)
    the adopted repository's content data      FAILED, not retryable (existing.py: shipped at
    cannot be counted                          its HEAD commit but not a JSON object)
    a blocking consistency rule breached       FAILED, route `descope`, not retryable, with the
                                               game-design persisted as evidence - cut scope;
                                               never relax the rule. An author that repairs its
                                               draft is shown the breaches and asked again
                                               first (consistency.breach_problems)
    otherwise                                  SUCCESS

On an adopted repository every visit measures the existing-content floor again, at the
commit the checkout ships (existing.py); when it ships units the run's last design does not
plan, the visit is an adoption: the author starts from the shipped units (brief['adoption']),
and the last design's gaps are not repaired.

Re-entered in a new visit of the same run, an author that revises (the `agent` author) starts
from the run's previous game-design, not from scratch, and is told what changed in the strategy
since that design (revision.py). The design it produces records the one it revises in
`provenance.supersedes` and the artifact metadata's `revises` (that design's version). This is
not the resume of a visit: a resumed execution of the same visit continues the repair of its
own last draft (LAST_DRAFT), whose base is the same revision. A design-gap return keeps its own
base (the design the gaps were found in) and is not a revision. A resumed gap visit continues
the repair of its last rejected draft too: that draft already answers the gaps, so the agent is
shown its validation problems first, and "unchanged" is judged against the base - the game-design
the build was made against - never against the resumed draft (agent.py).
"""

import copy
import datetime
import json
import os
import re

from wgflib import provenance
from wgflib.workflow import ArtifactOutput, StepResult, WorkflowStep
from wgflib.workflow import references as pinned_references
from wgflib.yamllite import load as load_yaml
from wgflib.workflow.contracts import ArtifactContracts

from . import commitments, consistency, content, depth, existing, experience, presentation
from . import features as feature_check
from . import knowledge as design_knowledge
from .authors import AUTHORS, AuthorError, resolve_author
from .compose import buildability, finalize
from .platforms import PlatformError, load_platforms
from .revision import RevisionError, previous_design

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


def triage_gaps(triage):
    """The design gaps a triage-report's selected `design` findings stand for: each one's
    design field (`task.design_field`, else build_spec.content for content and level
    design, else the dimension), the question - what the finding asks to change and how it
    is accepted - and blocking, since the build cannot be made to pass it until the design
    states it."""
    selected = (triage or {}).get("selected") or {}
    if selected.get("route") != "design":
        return []
    by_id = {f.get("id"): f for f in (triage or {}).get("findings") or []
             if isinstance(f, dict)}
    gaps = []
    for fid in selected.get("findings") or []:
        finding = by_id.get(fid)
        # content-sufficiency's own design gaps are read from its report (_sufficiency_gaps).
        if not finding or (finding.get("source") or {}).get("producer") \
                == "content-sufficiency-report":
            continue
        task = finding.get("task") or {}
        field = task.get("design_field") or (
            "build_spec.content" if finding.get("dimension") in ("content", "level-design")
            else str(finding.get("dimension") or "build_spec"))
        acceptance = "; ".join(task.get("acceptance") or [])
        gaps.append({"field": field,
                     "question": (f"{finding.get('summary')} - {task.get('change')}"
                                  + (f" (accepted when: {acceptance})" if acceptance else "")),
                     "assumed": None, "severity": "blocking", "finding": fid,
                     **_measured(finding.get("measured"), finding.get("bar"))})
    return gaps


def _measured(observed, bar):
    """What a finding observed against which bar, for the gap it stands for: the agent
    repairing it reads both (wgf_design/agent.py). Only what the finding stated."""
    return {key: value for key, value in (("observed", observed), ("bar", bar))
            if value is not None}


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
    feature_catalogue = None
    # Builds the git reader of the adopted checkout (existing.read_floor); None: the hardened
    # git of the develop module.
    floor_git = None

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
        # The consistency rules as the run pinned them (the live file for a run that pinned
        # none): a design is never held to a rule added to the Factory after its run started.
        try:
            self._run_rules = self.rules or self.pinned_rules(context)
        except (pinned_references.PinError, ValueError) as exc:
            return StepResult.blocked(f"the design consistency rules this run started under "
                                      f"cannot be read ({exc}): no design is judged against "
                                      "rules edited after the start")

        # The existing-content floor: what an adopted repository already ships. Measured on
        # every visit at the commit the checkout ships (HEAD less this run's own commits): a
        # re-entered design keeps its earlier floor while that commit is the same - the run's
        # own build in progress never re-floors it - and takes the content a person moved the
        # checkout to, recording the floor it replaces (existing.reconcile).
        try:
            self._floor, shipped_units = self._existing_floor(context, title_id)
        except ValueError as exc:
            return StepResult.failed(f"the adopted repository's content cannot be counted: "
                                     f"{exc}", retryable=False)
        # An adoption: the checkout ships units the run's last design does not plan (a first
        # design, or a person moved the checkout). The author starts from the shipped units,
        # and the design is not a repair of the last one - its gaps were found in a game of
        # other content.
        adoption = self._adoption(context, self._floor, shipped_units)

        author_name = (self.params.get("author")
                       or ((context.config or {}).get("design") or {}).get("author")
                       or DEFAULT_AUTHOR)
        brief = {"title_id": title_id, "strategy": strategy, "platforms": platforms,
                 "params": dict(self.params),
                 # For authors that run something (the `agent` author): where this
                 # attempt's files go, and the installation's configuration.
                 "config": context.config or {},
                 "run_dir": getattr(context, "run_dir", None),
                 # The run's params: where its pinned knowledge is (wgf_design/knowledge.py).
                 "environment": getattr(context, "environment", None) or {},
                 "visit": getattr(context, "visit", 1),
                 "attempt": getattr(context, "attempt", 1)}
        if self._floor:
            brief["existing_content"] = self._floor
        if adoption:
            brief["adoption"] = adoption
        # Re-entered through `design-gap`: the prototype-report names what the design did not
        # decide, and the draft starts from the design those gaps were found in (this step's
        # own previous output), so the design is repaired, never replaced.
        gaps = []
        if "prototype-report" in inputs.refs:
            report = inputs.load("prototype-report")
            gaps = [g for g in report.get("design_gaps") or [] if isinstance(g, dict)]
        # Re-entered through triage's `design` (docs/specialist-routing.md): the quality
        # findings it selected ask for a scope or content increase the design must state
        # first. They are repaired like gaps - at their field, on the design they were found
        # in - and the triage-report is pinned as an input like the prototype-report.
        entered = getattr(context, "entered_by", None) or ""
        if entered.rpartition(".")[2] == "design" and "triage-report" in inputs.refs:
            gaps = gaps + triage_gaps(inputs.load("triage-report"))
        # Re-entered through `design-gap` from content-sufficiency: the built content fell
        # short of the quality tier's bars where the design itself is short of them. Its
        # findings carry the gaps - only from a report on the design this run holds now (a
        # report on a design since repaired is answered already).
        if "content-sufficiency-report" in inputs.refs:
            gaps += self._sufficiency_gaps(inputs.load("content-sufficiency-report"), context)
        if gaps and adoption and self._previous_design(context) is not None:
            context.logger.warning(
                "design adopts the checkout's content: the design gaps found in the last "
                "design are not repaired - it planned other units than the checkout ships "
                "(missing ids, or the same ids as other units)",
                gaps=len(gaps), missing_unit_ids=adoption["missing"][:20],
                rewritten_unit_ids=adoption["rewritten"][:20])
            gaps = []
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
        revision = None
        if getattr(author, "revises", False) and not gaps:
            # A re-entry revises the design the run already holds; a first design has none.
            try:
                revision = previous_design(context, strategy)
            except RevisionError as exc:
                return StepResult.failed(f"design author {author_name!r}: {exc}",
                                         retryable=False)
            if revision:
                brief["revision"] = revision
                delta = revision["strategy_delta"]
                context.logger.info("revising the run's game-design",
                                    revises_version=revision["version"],
                                    strategy_changes=len(delta["changes"]),
                                    strategy_found=delta["found"])
        contracts = ArtifactContracts()
        self._inputs = inputs
        # A resumed execution of this visit continues the repair of the last rejected draft
        # (an author that repairs is not asked for a new game and billed for it again).
        last = self._last_draft(context) if getattr(author, "repairs", False) else None
        if last and adoption and not existing.shipped_ids(self._floor) <= {
                str(u.get("id")) for u in commitments.planned_units(last["draft"])}:
            # A draft of other content than the checkout ships: not this visit's to continue.
            context.logger.info("design starts over: the last draft drops units the adopted "
                                "checkout ships")
            last = None
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
                                    contracts, revision)
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
                if outcome["features"]:
                    context.logger.error("the design does not account for its features",
                                         problems=problems, repair_rounds=repair_round)
                    return StepResult.failed(
                        f"the design does not account for the features the brief, strategy "
                        f"or genre family names{after} ({len(problems)} problem(s)): "
                        + "; ".join(problems[:6]), retryable=False)
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
                    "mvp_features": mvp, "warnings": warnings or None,
                    "revises": revision["version"] if revision else None}
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
                              + (f", revises v{revision['version']}" if revision else "")
                              + (f", {len(warnings)} warning(s) for G3" if warnings else ""))

    @staticmethod
    def given_knowledge(author, design, strategy, context):
        """The Factory knowledge the author of this draft was GIVEN (its request's
        `knowledge`, recorded by the author as `given_knowledge`; None when it could not be
        read) - what the draft's decision trace is held against. An author that records none
        (a built-in author, which writes no trace; a draft composed again without an author
        session) is held against the knowledge resolved now over the design's own family."""
        if hasattr(author, "given_knowledge"):
            return author.given_knowledge
        return design_knowledge.provisional(
            (design.get("genre") or {}).get("family"), strategy,
            getattr(context, "environment", None) or {}, getattr(context, "run_dir", None))

    @staticmethod
    def pinned_rules(context):
        """core/reference/design-consistency-rules.yaml as the run pinned it, else live."""
        text, _digest, _pinned = pinned_references.read(
            consistency.RULES_FILE, getattr(context, "environment", None),
            getattr(context, "run_dir", None))
        return load_yaml(text)

    def _compose(self, draft, platforms, title_id, strategy, ref, context, author, contracts,
                 revision=None):
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
        # Written by the step, never by an author: what the adopted repository ships.
        design.pop("existing_content", None)
        if getattr(self, "_floor", None):
            design["existing_content"] = copy.deepcopy(self._floor)
        outcome = {"draft": copy.deepcopy(draft), "design": design, "artifact": None,
                   "block": None, "blocking": None,
                   "warnings": None, "problems": [], "unbuildable": False,
                   "experience": False, "presentation": False, "depth": False,
                   "content": False, "features": False, "consistency_problems": []}
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
        # What the brief, the strategy and the genre name beyond the core game: each feature
        # included, deferred or cut with a reason - none dropped silently, none added blindly.
        catalogue = self.feature_catalogue or feature_check.load_catalogue()
        found, feature_results = feature_check.check(design, strategy, platforms, catalogue)
        if found:
            outcome.update(features=True)
            problems += found
        now = self.clock()
        # The Factory knowledge an author of this game is given (the run's pinned knowledge,
        # resolved over the design's family and the strategy's platforms): what the design's
        # decision trace is held against (consistency knowledge.trace_matches_design).
        given = self.given_knowledge(author, design, strategy, context)
        ruleset = getattr(self, "_run_rules", None) or self.rules
        block, blocking, warnings = consistency.evaluate(design, strategy, platforms, now,
                                                         ruleset, knowledge=given)
        if blocking:
            # A breached blocking rule is `descope` for an author that cannot repair; one
            # that can is told which rule it breached, what was measured against what
            # (consistency.breach_problems) and - for the two concept rules - what the
            # concept view found, first. A breach was the one invalid-design class the
            # author was never shown, so a design whose only fault was three assets too
            # many died at `descope` with the fix one round away.
            ruleset = ruleset or consistency.load_rules()
            lexicon = consistency.load_lexicon(ruleset)
            concept = consistency.concept_view(design, strategy, lexicon)
            realizing = {pid: (entry or {}).get("realized_by") or []
                         for pid, entry in (lexicon.get("pillars") or {}).items()}
            notes = {
                "concept_mechanics_carried":
                    f"The strategy's concept names the mechanics {concept.get('uncarried')} "
                    "and no MVP mechanic or MVP control of the design builds them.",
                "design_adds_no_foreign_mechanic":
                    f"The design builds the mechanics {concept.get('foreign')} as core "
                    "mechanics, and neither the brief nor the strategy implies them. Remove "
                    "each one with the content units and controls that use it; renaming it "
                    "does not change what it is, and a new mechanic is a strategy change for "
                    "G2.",
                "pillar_realized_by_mechanic":
                    "The pillars " + ", ".join(
                        f"{pid} (realized by one of {', '.join(realizing.get(pid, []))})"
                        for pid in concept.get("pillars_unrealized") or [])
                    + " are asked for and no MVP mechanic a content unit uses realizes them. "
                    "Build the mechanic into the units; restating the pillar realizes nothing.",
                "brief_commitments_met":
                    "The brief (or the strategy G2 approved) states these counts, structure "
                    "and modes; plan at least each one in build_spec.content (units not tiered "
                    "optional, their `group` and `purpose: climax`) and include each mode in "
                    "features[]. Cutting what the brief asked for is a brief change, for a "
                    "person.",
                "existing_content_floor_kept":
                    "The repository this run adopts already ships this content "
                    "(game-design.existing_content). Plan at least as much: keep its units, "
                    "groups, climax units and elements, and add to them.",
                "content.introductions_one_at_a_time":
                    "After the opening unit, a unit debuts at most one element, mechanic or "
                    "introduction no earlier unit named. Give each extra new element a unit "
                    "of its own before the unit that combines it with another new one.",
                "knowledge.trace_matches_design":
                    "The design's knowledge_applied says something the design does not do. "
                    "Make the design follow each rule it claims applied (its checks are "
                    "named), or record the rule as not applied with why; name only rules, "
                    "revisions, units and checks the request gave.",
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
        # After consistency's own results and the content results: the feature evaluation.
        block["rule_results"] = list(block["rule_results"]) + feature_results
        block["feature_catalogue"] = feature_check.catalogue_record(catalogue)
        design["consistency"] = block
        artifact = self._with_provenance(design, strategy, ref, title_id, now, context,
                                         getattr(author, "actor", "automation"),
                                         inputs=self._inputs,
                                         supersedes=(revision or {}).get("artifact_id"))
        outcome.update(artifact=artifact, block=block, blocking=blocking, warnings=warnings,
                       problems=list(contracts("game-design", artifact)))
        return outcome

    def _existing_floor(self, context, title_id):
        """(game-design.existing_content for this run or None, the shipped units it was
        counted on). Measured again on every visit; the floor the run's last design recorded
        stands while the checkout ships the same commit (existing.reconcile). ValueError: the
        adopted repository ships content data that cannot be counted."""
        previous = self._previous_design(context) or {}
        kept = previous.get("existing_content")
        kept = kept if isinstance(kept, dict) else None
        floor, note, units = existing.read_adoption(
            context.config, title_id, git=self.floor_git,
            run_id=getattr(context, "run_id", None))
        if floor is not None or "adopt" not in note:
            context.logger.info("existing-content floor", floor=note)
        if kept is not None and not existing.measured(kept):
            # Recorded unmeasured (the checkout ships no content data file): the shipped
            # build has been played since, and its probe floor is the run's - never the
            # content data file the run's own build may have gained, and never lost to an
            # unmeasured floor at another commit (existing.reconcile).
            probed = existing.run_probe_floor(getattr(context, "run_dir", None), kept)
            if probed is not None:
                context.logger.info("existing-content floor", floor=probed.get("reason"))
                kept = probed
        chosen = existing.reconcile(kept, floor)
        self._floor_moved = existing.moved(kept, chosen)
        if isinstance(chosen, dict) and chosen.get("supersedes"):
            gone = chosen["supersedes"]
            context.logger.warning(
                "existing-content floor moved: the adopted checkout ships other content than "
                "the run's last design recorded",
                was=str(gone.get("commit") or "")[:12], was_units=gone.get("unit_ids")[:20],
                now=str((chosen.get("source") or {}).get("commit") or "")[:12],
                now_units=(chosen.get("unit_ids") or [])[:20])
        # The shipped units describe the floor chosen when it is the floor read now.
        same = (floor is not None and chosen is not None and existing.measured(floor)
                and existing.shipped_ids(chosen) == existing.shipped_ids(floor))
        return chosen, (units if same else [])

    def _adoption(self, context, floor, units):
        """brief['adoption'] when the adopted checkout ships units the run's last design does
        not plan (or there is no last design), or - the floor moved to another commit (a
        person changed the shipped content) - units the last design plans under the same ids
        but as other units (existing.rewritten): the shipped units, in the design's unit
        shape, are the starting units. None otherwise."""
        shipped = existing.shipped_ids(floor)
        if not shipped or not units:
            return None
        previous = self._previous_design(context)
        planned_units = commitments.planned_units(previous) if previous else []
        planned = {str(u.get("id")) for u in planned_units}
        missing = sorted(shipped - planned)
        changed = []
        if previous is not None and getattr(self, "_floor_moved", False):
            changed, _kept = existing.rewritten(units, planned_units)
        if previous is not None and not missing and not changed:
            return None
        source = (floor or {}).get("source") or {}
        return {"commit": source.get("commit"), "path": source.get("path"),
                "unit_ids": list(floor.get("unit_ids") or []),
                "units": existing.adoption_units(units),
                "derived": existing.adoption_derived(units),
                "shipped_units": units,
                "missing": missing,
                "rewritten": changed,
                "supersedes": floor.get("supersedes")}

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

    @classmethod
    def _sufficiency_gaps(cls, report, context):
        """The design gaps of a failing content-sufficiency-report routed `design-gap`, in
        prototype-report design_gaps shape - when it judged the design this run holds now."""
        if not isinstance(report, dict) or report.get("verdict") != "FAIL" \
                or "design-gap" not in (report.get("routes") or []):
            return []
        previous = cls._previous_design(context) or {}
        current = (previous.get("provenance") or {}).get("content_hash")
        judged = next((p.get("content_hash") for p in
                       (report.get("provenance") or {}).get("inputs") or []
                       if isinstance(p, dict) and p.get("artifact_type") == "game-design"),
                      None)
        if not current or judged != current:
            return []
        return [dict(f["design_gap"], finding=f.get("id"),
                     **_measured(f.get("observed"), f.get("bar")))
                for f in report.get("findings") or []
                if isinstance(f, dict) and f.get("route") == "design-gap"
                and isinstance(f.get("design_gap"), dict)]

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
                         inputs=None, supersedes=None):
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
            title_id=title_id,
            supersedes=supersedes)
        artifact = {"provenance": record}
        artifact.update(design)
        return provenance.seal(artifact)


def register(registry):
    registry.register(DesignStep.type, DesignStep)
    return registry


assert DEFAULT_AUTHOR in AUTHORS

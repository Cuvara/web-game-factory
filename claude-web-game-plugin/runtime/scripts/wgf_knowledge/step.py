"""The `knowledge` step: the Factory's knowledge that applies to this title, as the run's contract.

    game-design, title-strategy
      -> the run's facets (resolve.facets_from: genre family, rendering dimension, targeted
         platforms, the quality tier the run started with)
      -> the knowledge the run pinned when it started (core/reference/lessons.yaml,
         core/reference/check-tiers.yaml and every file they are read with - the check
         sources, the scope vocabularies, the platform profiles), never the live files
      -> the versions the run recorded at start (params.quality.knowledge) checked against
         the pinned copies, and the knowledge validated (wgf_quality.registry, runtime mode)
      -> the exceptions a person granted the run (`wgf resume --except`, exceptions.py)
      -> resolve.resolve: the rules that apply and why, the ones that do not and why not,
         the validating steps the blocking and required rules need, the regression suite
      -> knowledge-contract (core/artifacts/knowledge-contract.schema.json)

    SUCCESS   the contract is made                                                   SUCCESS
    BLOCKED   the run did not pin its knowledge, a pinned copy was edited, the recorded
              versions are not the pinned ones, the knowledge breaks its own rules, the
              run's workflow or facets cannot be read, or a blocking or required rule's
              check is produced by no step of the run's workflow: the run stops before
              anything is planned or built on knowledge it cannot state, and a person looks

A run started before the knowledge model (no `params.quality.knowledge`, quality policy rule
8) was never held to a contract: reached by resuming it under a newer definition, this step
makes the contract it can from what the run holds - the pinned files where it pinned them -
marked `advisory` with every problem that would have stopped a new run listed. It is
BLOCKED only when no contract can be made at all: no lessons or check tiers can be read.
Its compliance is advisory only.

The run's workflow is not pinned: the validators are named from the definition file as it
reads now, whose version and digest the contract records (`versions.workflow`).

It reads data and writes one artifact: no process, no network, no checkout.
"""

import datetime
import json
import os

from wgflib import paths, provenance
from wgflib.workflow import ArtifactOutput, StepResult, WorkflowStep
from wgflib.workflow import references as pinned_references
from wgflib.yamllite import load as load_yaml

from . import model, resolve as resolver, versions

__all__ = ["KnowledgeStep", "KnowledgeUnavailable", "RunKnowledge", "load_run_knowledge",
           "run_workflow", "advisory_run", "PINNED_ROOT"]

ARTIFACT = "knowledge-contract"
ROLE = "architect"
PINNED_ROOT = pinned_references.DIRECTORY
PLATFORMS_DIR = "core/reference/platforms/"
# Read with the lessons and the check tiers: the scope vocabularies (model.vocabulary) and
# the versions a contract records (versions.FILES).
WITH = ("core/reference/genre-models.yaml", "core/reference/quality-benchmark.yaml",
        "core/reference/quality-floor.yaml", "core/reference/quality-policy.yaml")
# A check id that classification reads from code (`defined_in`) is validated by the
# Factory's own integrity check; the code is not pinned, so a run never re-checks it.
_CODE_PROBLEM = "appears nowhere in"


class KnowledgeUnavailable(Exception):
    """The run's knowledge cannot be read as the run pinned it."""


def _utc(value=None):
    parsed = model.parse_time(value) if value else None
    return parsed or datetime.datetime.now(datetime.timezone.utc)


def advisory_run(environment):
    """True for a run started before the knowledge model: it recorded no knowledge versions
    (params.quality.knowledge), so it was never held to a contract."""
    from wgflib.workflow import quality
    return quality.knowledge_of(environment) is None


class RunKnowledge:
    """The knowledge one run is held to, as it pinned it.

    `lessons`, `tiers`: the parsed files. `checks`: wgf_quality.registry.classify() over the
    pinned tiers, read from `root`. `read(relpath) -> bytes`: the run's pinned copy (the
    live file only for a file an advisory run did not pin). `pinned`: every file came from
    the run's pins. `problems`: classification problems (code literals excepted)."""

    def __init__(self, lessons, tiers, checks, root, read, pinned, problems, unpinned=()):
        self.lessons = lessons
        self.tiers = tiers
        self.checks = checks
        self.root = root
        self.read = read
        self.pinned = pinned
        self.problems = problems
        self.unpinned = list(unpinned)


def _reader(environment, run_dir):
    def read(relpath):
        try:
            text, _digest, _pinned = pinned_references.read(relpath, environment, run_dir)
        except pinned_references.PinError as exc:
            raise OSError(str(exc))
        return text.encode("utf-8")
    return read


def _needed(tiers, platforms=()):
    files = [versions.FILES["lessons"], versions.FILES["check_tiers"]] + list(WITH)
    for source in ((tiers or {}).get("sources") or {}).values():
        if isinstance(source, dict) and source.get("file") and source["file"] not in files:
            files.append(source["file"])
    files += [f"{PLATFORMS_DIR}{p}.yaml" for p in platforms or ()]
    return files


def load_run_knowledge(environment, run_dir, platforms=(), strict=True):
    """RunKnowledge for a run. `strict` (a run that recorded its knowledge): every file the
    knowledge is read with must be pinned by the run, and every pinned copy must be the
    bytes it recorded - else KnowledgeUnavailable, never a fall back to the live tree.
    Not strict (an advisory run): the pinned copy where the run pinned one, the live file
    otherwise. `platforms`: the targeted platforms, whose profiles must be pinned too."""
    from wgf_quality import registry
    environment = environment if isinstance(environment, dict) else {}
    pins = environment.get(pinned_references.PARAM) or {}
    pins = pins if isinstance(pins, dict) else {}
    read = _reader(environment, run_dir)
    try:
        lessons = load_yaml(read(versions.FILES["lessons"]).decode("utf-8"))
        tiers = load_yaml(read(versions.FILES["check_tiers"]).decode("utf-8"))
    except (OSError, ValueError, UnicodeDecodeError) as exc:
        raise KnowledgeUnavailable(f"the run's knowledge cannot be read ({exc})")
    needed = _needed(tiers, platforms)
    unpinned = [f for f in needed if f not in pins]
    if strict and unpinned:
        raise KnowledgeUnavailable(
            f"the run did not pin {', '.join(unpinned)}: its contract would be resolved from "
            "live files, which an edit made since it started changes. The workflow pins its "
            "knowledge (`pinned_references`); start a new run of it")
    for relpath in needed:
        if relpath in pins:
            try:
                read(relpath)  # refuses a copy that is not the bytes the run recorded
            except OSError as exc:
                raise KnowledgeUnavailable(str(exc))
    pinned = not unpinned and bool(run_dir)
    root = os.path.join(run_dir, PINNED_ROOT) if pinned else paths.ROOT

    def reader(relpath):
        return load_yaml(read(relpath).decode("utf-8"))
    checks, problems = registry.classify(tiers, root, reader=reader)
    problems = [p for p in problems if _CODE_PROBLEM not in p]
    return RunKnowledge(lessons, tiers, checks, root, read, pinned, problems, unpinned)


def run_workflow(context):
    """(the run's workflow as a mapping, its file's digest): the file the run recorded it was
    started from, else its id in core/workflows/ - as that file reads NOW. A run does not
    pin its workflow; the digest (and the version against the one the run started under) is
    recorded in the contract so a reader sees which definition named the validators.
    (None, None) when neither can be read."""
    from wgflib.workflow.definition import WORKFLOWS, find_definition
    from wgflib.yamllite import load as load_yaml
    workflow_id = getattr(context, "workflow_id", None)
    candidates = []
    run_dir = getattr(context, "run_dir", None)
    if run_dir:
        # The file the run was started from first: a run of a workflow given by path is
        # driven by that file, though one of the same id ships in core/workflows/.
        try:
            with open(os.path.join(run_dir, "state.json"), encoding="utf-8") as handle:
                source = (json.load(handle) or {}).get("workflow_source")
        except (OSError, ValueError, AttributeError):
            source = None
        if source:
            candidates.append(source if os.path.isabs(source)
                              else os.path.join(paths.ROOT, source))
    if workflow_id:
        try:
            candidates.append(find_definition(workflow_id, (WORKFLOWS,)))
        except FileNotFoundError:
            pass
    for path in candidates:
        try:
            with open(path, "rb") as handle:
                data = handle.read()
            workflow = (load_yaml(data.decode("utf-8")) or {}).get("workflow")
        except Exception:  # noqa: BLE001 - an unreadable candidate is tried no further
            continue
        if isinstance(workflow, dict) and (not workflow_id
                                           or workflow.get("id") == workflow_id):
            return workflow, pinned_references.digest(data)
    return None, None


def _fallback_versions(knowledge, workflow, digest, factory):
    """The least a contract's `versions` holds - lessons and check tiers by version and
    digest, the Factory, the workflow - for an advisory run whose other files cannot be
    read. Raises KnowledgeUnavailable when even these cannot."""
    out = {"factory": factory}
    for key in ("lessons", "check_tiers"):
        try:
            data = knowledge.read(versions.FILES[key])
        except OSError as exc:
            raise KnowledgeUnavailable(str(exc))
        version = model.version_of(knowledge.lessons if key == "lessons" else knowledge.tiers)
        if version is None:
            raise KnowledgeUnavailable(f"{versions.FILES[key]} has no version")
        out[key] = {"version": version, "sha256": pinned_references.digest(data)}
    out["workflow"] = _workflow_version(workflow, digest)
    return out


def _workflow_version(workflow, digest):
    if not isinstance(workflow, dict):
        return None
    entry = {"id": workflow.get("id"), "version": workflow.get("version")}
    if digest:
        entry["sha256"] = digest
    return entry


def _normalize_advisory(body):
    """A contract an advisory run resolves from knowledge older than the model (lessons
    1.x: no category or lifecycle): the fields filled as the model would derive them, so
    the contract is still one schema."""
    for rule in body.get("rules") or ():
        if not rule.get("category"):
            rule["category"] = "uncategorized"
        if rule.get("lifecycle") not in ("candidate", "active", "validated", "deprecated"):
            rule["lifecycle"] = "candidate" if rule.get("status") == "gap" else "active"
        if not rule.get("why_applicable"):
            rule["why_applicable"] = ["no scope declared: applies"]
    return body


class KnowledgeStep(WorkflowStep):
    type = "knowledge"

    def execute(self, inputs, context):
        if "game-design" not in inputs:
            return StepResult.waiting_for_input(
                "knowledge needs the run's game-design: the rules that apply are resolved "
                "from the title's genre family, rendering and platforms")
        from wgflib.workflow import quality
        from . import exceptions

        design = inputs.load("game-design")
        strategy = inputs.load("title-strategy") if "title-strategy" in inputs else None
        environment = getattr(context, "environment", None) or {}
        environment = environment if isinstance(environment, dict) else {}
        run_dir = getattr(context, "run_dir", None)
        title_id = (design or {}).get("title_id") or (strategy or {}).get("title_id")
        advisory = advisory_run(environment)
        now = _utc(getattr(context, "now", None))
        tier = quality.run_tier(environment)
        # What blocks a run held to its knowledge; for an advisory run (started before
        # rule 8), what the contract says it could not hold - never a stop.
        notes = []

        def stop(reason):
            if advisory:
                notes.append(reason)
                return None
            context.logger.warning("knowledge blocked", reason=reason)
            return StepResult.blocked(
                f"knowledge: {reason}. The run stops here: nothing is planned or built "
                "without the contract of the knowledge it is held to.")

        try:
            run_facets = resolver.facets_from(design, strategy, tier)
        except ValueError as exc:
            # The design or strategy states a facet the resolver cannot read: never guessed.
            blocked = stop(f"the run's facets cannot be read ({exc})")
            if blocked:
                return blocked
            run_facets = resolver.facets(tier=tier if isinstance(tier, str) else None)

        try:
            knowledge = load_run_knowledge(environment, run_dir, run_facets["platforms"],
                                           strict=not advisory)
        except KnowledgeUnavailable as exc:
            # No knowledge to resolve: no contract can be made at all, advisory or not.
            context.logger.warning("knowledge blocked", reason=str(exc))
            return StepResult.blocked(f"knowledge: no contract can be made: {exc}")

        if knowledge.unpinned:
            # Only an advisory run gets here with files it did not pin (a run held to its
            # knowledge is refused above): said, never a stop.
            notes.append(f"the run did not pin {', '.join(knowledge.unpinned)}: read from "
                         "the live files")
        recorded = quality.knowledge_of(environment) or {}
        for name, key in (("lessons", "lessons"), ("check-tiers", "check_tiers")):
            data = knowledge.lessons if key == "lessons" else knowledge.tiers
            found = f"{name}@{model.version_of(data)}"
            if name in recorded and recorded[name] != found:
                blocked = stop(f"the run recorded {recorded[name]} when it started, but its "
                               f"pinned {versions.FILES[key]} is {found}")
                if blocked:
                    return blocked

        if not advisory:
            from wgf_quality import registry
            found = list(knowledge.problems)
            found += registry.lesson_problems(knowledge.lessons, knowledge.checks,
                                              knowledge.root, None, runtime=True)
            if found:
                blocked = stop("the run's knowledge breaks its own rules - "
                               + "; ".join(found[:5])
                               + (f" (and {len(found) - 5} more)" if len(found) > 5 else ""))
                if blocked:
                    return blocked

        workflow, workflow_digest = run_workflow(context)
        if workflow is None:
            blocked = stop(f"the run's workflow {getattr(context, 'workflow_id', None)!r} "
                           "cannot be read, so the steps that validate its rules cannot be "
                           "named")
            if blocked:
                return blocked
        else:
            started = getattr(context, "workflow_version", None)
            if started is not None and str(workflow.get("version")) != str(started):
                # Resumed under a newer definition: the validators are the ones the engine
                # drives the run with now. Said, with the digest recorded; not a stop.
                notes.append(f"validators named by {workflow.get('id')} "
                             f"v{workflow.get('version')}; the run started under v{started}")

        granted = exceptions.granted(context.read_events(),
                                     exceptions.issued_nonces(run_dir))
        try:
            vocabulary = model.vocabulary(knowledge.root)
        except model.KnowledgeError as exc:
            blocked = stop(f"the scope vocabularies cannot be read ({exc})")
            if blocked:
                return blocked
            vocabulary = None
        taken = (environment.get(quality.PARAM) or {}).get("factory")
        factory = ({"version": taken.get("version"), "commit": taken.get("commit")}
                   if isinstance(taken, dict) else versions.factory())
        try:
            found_versions = versions.collect(read=knowledge.read, root=knowledge.root,
                                              workflow=workflow,
                                              platforms=run_facets["platforms"],
                                              pins=resolver.platform_pins(strategy))
            found_versions["factory"] = factory
            found_versions["workflow"] = _workflow_version(workflow, workflow_digest)
        except (model.KnowledgeError, OSError, ValueError) as exc:
            blocked = stop(f"the versions the run is held to cannot be recorded ({exc})")
            if blocked:
                return blocked
            try:
                found_versions = _fallback_versions(knowledge, workflow, workflow_digest,
                                                    factory)
            except KnowledgeUnavailable as why:
                return StepResult.blocked(f"knowledge: no contract can be made: {why}")
        body = resolver.resolve(knowledge.lessons, knowledge.checks, knowledge.tiers,
                                run_facets, workflow=workflow, exceptions=granted, now=now,
                                versions=found_versions, vocabulary=vocabulary)
        body["exceptions_refused"] = (list(body.get("exceptions_refused") or [])
                                      + exceptions.from_config(getattr(context, "config", None)))
        missing = body.get("missing_validators") or []
        if missing:
            blocked = stop("no step of the run's workflow validates " + "; ".join(
                f"{m.get('rule')} {m.get('check') or ''} ({m.get('why') or 'reported in '}"
                f"{'' if m.get('why') else m.get('producer') or 'no artifact'})"
                for m in missing))
            if blocked:
                return blocked
            body["missing_validators"] = []
        if advisory:
            _normalize_advisory(body)

        contract = {
            "provenance": provenance.build(
                ARTIFACT,
                artifact_id=provenance.artifact_id(ARTIFACT, title_id or "untitled",
                                                   now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                                                   getattr(context, "execution", 1) or 1),
                produced_by=provenance.producer(ROLE),
                produced_at=now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                inputs=provenance.pin_inputs(inputs), title_id=title_id),
            "title_id": title_id,
            "versions": found_versions,
        }
        contract.update(body)
        # The design's decision trace, as the design step judged it (K5): whether the run's
        # design recorded one, the rules it claims applied, and the claims its own checks
        # contradicted. A claim never satisfies a rule; the quality gate shows it beside
        # what the checks measured.
        from wgf_design import knowledge as design_knowledge
        contract["trace"] = design_knowledge.trace_summary(design, (design or {})
                                                           .get("consistency"))
        if advisory:
            contract["advisory"] = {
                "reason": "a run started before the knowledge model (no "
                          "params.quality.knowledge): its compliance is reported, never "
                          "enforced",
                "problems": [n for n in notes if n]}
        counts = body["counts"]
        summary = (f"knowledge: {counts['blocking']} blocking, {counts['required']} required, "
                   f"{counts['recommended']} recommended, {counts['experimental']} "
                   f"experimental, {counts['not_applicable']} not applicable; validators "
                   f"{', '.join(body['required_validators']) or 'none'}; "
                   f"{len(body['exceptions'])} exception(s)")
        if advisory:
            summary += ("; ADVISORY - a run started before the knowledge model: its "
                        "compliance is reported, never enforced")
        if notes:
            summary += " (" + "; ".join(notes) + ")"
        refused = body["exceptions_refused"]
        if refused:
            summary += f"; {len(refused)} exception(s) refused"
        context.logger.info("knowledge contract", counts=counts, advisory=advisory,
                            pinned=knowledge.pinned)
        output = ArtifactOutput(ARTIFACT, provenance.seal(contract),
                                metadata={"advisory": advisory, "counts": counts})
        return StepResult.success([output], message=summary)

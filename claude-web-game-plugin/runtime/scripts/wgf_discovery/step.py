"""The `research` step: a market scan that ends in a research report, an opportunity space
and the one opportunity the run carries.

    evidence -> claims -> platform summaries -> screened catalog candidates  (analysis.py)
             -> game corpus -> market cells -> patterns and benchmarks       (corpus.py,
             -> opportunity space -> capability check -> selection           market.py,
                                                                             patterns.py,
                                                                             opportunities.py)

The question it answers is "what kind of web game should the factory build next?". Research
V2 (docs/research-v2.md): it codes every game it knows of on the shared research vocabulary,
counts patterns across them, keeps demand, supply, saturation and trend apart, and proposes
several opportunities from the corpus and the capability catalog; the best-ranked buildable
one is carried forward, and every other one stays in the report (and, with
`persist_backlog`, in the backlog). An opportunity the Factory cannot build is kept as a
capability gap.

A game idea is optional. Without one (`wgf new-game`) the scan is blank: every opportunity,
ranked on evidence alone. With one (`wgf new-game "3D goalkeeper game ..."`) the run
carries it as `params.idea` - the context's `environment["idea"]`, canonical, corroborated on
every resume - and the scan is anchored to it: the report's `scope.brief` records it, the
default question asks which shape carries it, candidates are ranked by their match to it
first (analysis.idea_match, opportunities.rank), and the opportunity carries it verbatim as `brief`, for
strategy and design to build from. The screen and its vetoes are unchanged, and nothing is
invented: a selection that holds none of the brief's words records an `idea-unmatched` gap.
"Holds the brief's words" means analysis.brief_terms: generic gameplay vocabulary never
counts, a word of the shape's genre or names counts alone, and its mechanic sentence or
facet labels count only two words or more - one incidental word is not a match.

When no eligible candidate holds any of the brief's words, `idea_fallback` decides. `wait`
(the default) selects nothing: the report keeps every candidate, records the
`idea-unmatched` gap naming the nearest eligible shape as information only, and the step
waits for input - a concept for the brief in the concepts file, or `idea_fallback: nearest`.
`nearest` carries the brief to the nearest eligible shape and says so in the gap.

The concepts file (`<corpus>/concepts.yaml` unless `concepts` names another) is how a
project gives research a concept the catalog lacks. It has the catalog's shape -
`{version, archetypes: [...]}` - and every entry the catalog's required keys, plus `brief`,
exactly the run's canonical idea (an entry for another brief is refused), and
`design_archetype`, the design archetype id that designs it or `agent` (only the agent
design author can). Entries join the catalog for that run only; an id the catalog already
uses is refused. Each one carries an extra hypothesis claim saying it was authored for the
brief, is not a catalog shape and its figures are unmeasured; its estimates stay hypotheses
like every catalog estimate. The file is read only when the run has an idea: a blank scan
is unchanged by it. When it exists, its hash joins the catalog's in the report id and it is
recorded as the `concepts` collector; without it, the report is what it always was.

Settings, each optional, in increasing precedence: DEFAULTS below, `factory.discovery` in
workspace/config/factory.yaml, then the step's `with:` block in the workflow file.

    corpus          directory holding snapshots/, games/ (teardown records) and probes.yaml
                    (workspace/research)
    platforms       platform ids to scope the scan to    (every profile except generic-web)
    genres          genre slugs; archetypes are kept if any market tag matches   (all)
    live            fetch probes.yaml pages during the run; also WGF_RESEARCH_LIVE=1  (off)
    require_external_evidence
                    wait for input when no external source was read   (true)
    idea_fallback   wait | nearest: with an idea no eligible candidate matches   (wait)
    concepts        the project's concepts file   (<corpus>/concepts.yaml)
    max_candidates  how many screened candidates the report keeps   (8)
    scoring_model   file stem under core/reference/scoring/   (portfolio-default.v1)
    as_of           ISO timestamp the scan is "as of"; default now   (for reproducible runs)
    question        the scan's scope question, recorded in the report
    vocabulary      research vocabulary file   (core/reference/research-vocabulary.yaml)
    analysis        analysis configuration   (core/reference/research-analysis.yaml)
    select          an opportunity id from the scan to carry instead of the ranked first
    persist_backlog write every proposed opportunity to the backlog as `discovered`  (off)

Outcomes (docs/workflow-module-contract.md §7):

    SUCCESS            research-report + opportunity
    WAITING_FOR_INPUT  no external evidence at all - the report is still emitted, and says so;
                       or (idea_fallback: wait) the idea matches no eligible candidate;
                       or the selected concept needs the agent design author
                       (`design_archetype: agent`) and `factory.design.author` is not agent
    BLOCKED            evidence read, but no candidate survived screening - report emitted
    FAILED, permanent  a malformed snapshot, game record, probe file, catalog, concepts file,
                       vocabulary or scope; a `select` naming no eligible opportunity
    FAILED, retryable  live fetching was the only evidence source and every fetch failed

Side effects: none outside the run unless `persist_backlog` is on. The step reads core/ and
workspace/, and - only when `live` is on - the network. By default it writes nothing but the
artifacts it returns, so re-executing it under the same idempotency key cannot duplicate
anything; given the same corpus and `as_of` it produces byte-identical artifacts. With
`persist_backlog` it also writes each proposed opportunity to the backlog, once: ids are
stable across scans, and a file already there is left as it is.
"""

import copy
import glob
import hashlib
import json
import os
import re
from datetime import datetime, timezone

from wgflib import paths, provenance
from wgflib.workflow import ArtifactOutput, StepResult, WorkflowStep
from wgflib.workflow.api import canonical_idea
from wgflib.workflow.model import StepOutcome
from wgflib.yamllite import YamlError, load_file

from . import analysis, opportunities as opportunity_space
from .corpus import Corpus, load_records
from .market import analyse_market
from .patterns import extract_benchmarks, extract_patterns, facet_summaries
from .vocabulary import AnalysisConfig, Vocabulary, VocabularyError
from .evidence import (
    EvidenceError,
    Gap,
    LiveCollector,
    ReferenceCollector,
    SnapshotCollector,
    format_time,
    parse_time,
)

__all__ = ["ResearchStep", "DEFAULTS", "CATALOG"]

CATALOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "archetypes.yaml")
CONTROL_PLATFORMS = ("generic-web",)
CONCEPTS_FILE = "concepts.yaml"
# A concept design_archetype naming no catalog archetype: only the agent design author can
# design it, and research waits rather than hand it to another author (F09).
AGENT_ONLY = "agent"
IDEA_FALLBACKS = ("wait", "nearest")
REQUIRED = ("id", "title", "genre", "subgenre", "core_mechanic", "fantasy", "core_loop",
            "session_seconds", "replayability", "technical_complexity", "asset_complexity",
            "dev_speed_days", "asset_cost_usd", "bundle_mb", "monetization")
_KEBAB = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")
# The dimensions an entry's `priors` may guess (analysis.py reads exactly these), each a number
# in [0, 1]. Anything else is refused: a prior the screen cannot read would be dropped
# silently, and a note in its place would become a claim's text.
PRIOR_KEYS = ("monetization_fit", "retention_potential", "session_quality", "technical_risk",
              "performance_risk", "iterability")


def _priors_problem(entry):
    """Why an entry's `priors` cannot be read, or None. Absent priors are allowed."""
    priors = entry.get("priors")
    if priors is None:
        return None
    if not isinstance(priors, dict):
        return "priors must be a mapping of " + ", ".join(PRIOR_KEYS) + " to numbers in [0, 1]"
    unknown = sorted(k for k in priors if k not in PRIOR_KEYS)
    if unknown:
        return (f"priors has {', '.join(map(repr, unknown))}; only "
                + ", ".join(PRIOR_KEYS) + " are priors")
    bad = sorted(k for k, v in priors.items()
                 if isinstance(v, bool) or not isinstance(v, (int, float)) or not 0 <= v <= 1)
    if bad:
        return f"priors {', '.join(bad)} must be numbers in [0, 1]"
    return None

DEFAULTS = {
    "corpus": os.path.join("workspace", "research"),
    "platforms": None,
    "genres": None,
    "live": False,
    "require_external_evidence": True,
    "idea_fallback": "wait",
    "concepts": None,
    "max_candidates": 8,
    "scoring_model": "portfolio-default.v1",
    "as_of": None,
    "question": None,
    "catalog": CATALOG,
    "backlog": paths.OPPORTUNITIES,
    "vocabulary": None,
    "analysis": None,
    "select": None,
    "persist_backlog": False,
}


class ResearchError(ValueError):
    """The scan's own configuration is wrong. Not retryable."""


def _file_hash(path):
    with open(path, "rb") as handle:
        return "sha256:" + hashlib.sha256(handle.read()).hexdigest()


def _resolve(path):
    return path if os.path.isabs(path) else os.path.join(paths.PROJECT, path)


def _shown(path):
    """Relative to the project when it is inside it, else as given."""
    try:
        shown = os.path.relpath(path, paths.PROJECT)
    except ValueError:  # another drive
        return path
    return path if shown.startswith(os.pardir) else shown


class ResearchStep(WorkflowStep):
    type = "research"
    role = "research"

    def __init__(self, definition, fetcher=None, clock=None):
        super().__init__(definition)
        # Seams for tests: a fetcher replaces the network, a clock replaces now(). Register
        # `lambda d: ResearchStep(d, fetcher=...)` to use them through the engine.
        self.fetcher = fetcher
        self.clock = clock

    # -- entry point ----------------------------------------------------------------------

    def execute(self, inputs, context):
        try:
            settings = self.settings(context)
            as_of = self._as_of(settings)
            return self._scan(settings, as_of, context)
        except (EvidenceError, ResearchError, YamlError, VocabularyError,
                analysis.SupportError) as exc:
            context.logger.error("research input refused", error=str(exc))
            return StepResult.failed(str(exc), retryable=False)

    def settings(self, context):
        merged = dict(DEFAULTS)
        merged.update((context.config or {}).get("discovery") or {})
        merged.update(self.params or {})
        if os.environ.get("WGF_RESEARCH_LIVE") == "1":
            merged["live"] = True
        return merged

    def _as_of(self, settings):
        if settings.get("as_of"):
            try:
                return parse_time(str(settings["as_of"]))
            except ValueError:
                raise ResearchError(f"as_of {settings['as_of']!r} is not an ISO timestamp")
        now = self.clock() if self.clock else datetime.now(timezone.utc)
        return now.replace(microsecond=0)

    # -- the scan -------------------------------------------------------------------------

    @staticmethod
    def idea(context):
        """The run's game idea (canonical, from `wgf new-game "..."`), or None."""
        idea = (getattr(context, "environment", None) or {}).get("idea")
        return idea if isinstance(idea, str) and idea else None

    def _scan(self, settings, as_of, context):
        idea = self.idea(context)
        fallback = settings.get("idea_fallback")
        if fallback not in IDEA_FALLBACKS:
            raise ResearchError(f"idea_fallback {fallback!r} is not one of "
                                f"{', '.join(IDEA_FALLBACKS)}")
        as_of_text = format_time(as_of)
        stamp = lambda value=None: as_of_text if value is None else format_time(value)  # noqa: E731
        gaps = []

        model_path = os.path.join(paths.SCORING, f"{settings['scoring_model']}.yaml")
        if not os.path.exists(model_path):
            raise ResearchError(f"no scoring model {settings['scoring_model']!r}")
        model = load_file(model_path)
        ttl = float(model.get("evidence_ttl_days") or 45)

        reference = ReferenceCollector(paths.PLATFORMS)
        available = reference.profiles()
        scope = settings.get("platforms") or sorted(
            pid for pid in available if pid not in CONTROL_PLATFORMS)
        unknown = [pid for pid in scope if pid not in available]
        if unknown:
            raise ResearchError(f"no platform profile for {', '.join(unknown)}")
        profiles = {pid: available[pid] for pid in scope}

        corpus = _resolve(settings["corpus"])
        concepts_path, concepts = (self._concepts(settings, corpus, idea) if idea
                                   else (None, []))
        archetypes = self._archetypes(settings, concepts)
        collectors = [{"id": reference.id, "kind": reference.kind, "status": "used",
                       "detail": f"{len(profiles)} platform profiles"}]

        snapshots = SnapshotCollector(os.path.join(corpus, "snapshots"))
        found = snapshots.collect(as_of, ttl, gaps)
        status, detail = snapshots.status()
        collectors.append({
            "id": snapshots.id, "kind": snapshots.kind,
            "status": status or ("used" if found else "empty"),
            "detail": detail or f"{len(found)} snapshot sources",
        })

        live_sources, live_failed = [], False
        live = LiveCollector(os.path.join(corpus, "probes.yaml"), fetcher=self.fetcher,
                             clock=self.clock)
        if settings.get("live"):
            live_sources, probe_count, failures = live.collect(gaps)
            live_failed = probe_count > 0 and failures == probe_count
            collectors.append({
                "id": live.id, "kind": live.kind,
                "status": "unavailable" if live_failed else ("used" if live_sources else "empty"),
                "detail": f"{probe_count} probes, {len(live_sources)} matched, {failures} "
                          f"fetch failures",
            })
        else:
            collectors.append({"id": live.id, "kind": live.kind, "status": "disabled",
                               "detail": "enable with live: true or WGF_RESEARCH_LIVE=1"})

        if idea and os.path.exists(concepts_path):
            # Only when there is one to read: a scan without the file reports as it always did.
            collectors.append({
                "id": "concepts", "kind": "reference",
                "status": "used" if concepts else "empty",
                "detail": f"{len(concepts)} concepts authored for the brief in "
                          f"{_shown(concepts_path)}"})

        sources = [s for s in found + live_sources if s.observations]
        if live_failed and not sources and settings.get("require_external_evidence"):
            return StepResult.failed("every live probe fetch failed and no snapshot evidence "
                                     "exists; retrying may reach the network")
        if not sources:
            gaps.append(Gap("no-external-evidence",
                            "no external source was read: every platform fact below rests on "
                            "the factory's own profiles and every product figure on catalog "
                            "estimates"))

        backlog = self._backlog(settings)
        vocabulary = Vocabulary(_resolve(settings["vocabulary"]) if settings.get("vocabulary")
                                else None)
        config = AnalysisConfig(_resolve(settings["analysis"]) if settings.get("analysis")
                                else None)
        config.check_against(vocabulary)
        self._vocab = vocabulary
        records = load_records(os.path.join(corpus, "games"))
        corpus_hash = self._corpus_hash(sources, profiles, records)
        key_parts = [corpus_hash, as_of_text[:10], scope, settings.get("genres"),
                     _file_hash(settings["catalog"]), vocabulary.file_hash, config.file_hash]
        if idea and os.path.exists(concepts_path):
            key_parts.append({"concepts": _file_hash(concepts_path)})
        if idea:
            # Only with one: a blank scan keeps the report id it always had.
            key_parts.append({"idea": idea})
        if settings.get("select"):
            key_parts.append({"select": settings["select"]})
        report_key = hashlib.sha256(json.dumps(
            key_parts, sort_keys=True).encode()).hexdigest()[:10]
        report_id = f"rr-{report_key}"

        book = analysis.ClaimBook(stamp())
        state = {}
        claims, platforms, candidates, selection, analysis_gaps = analysis.analyse(
            sources=sources, profiles=profiles, archetypes=archetypes, model=model,
            backlog=backlog, as_of_text=stamp, report_key=report_key,
            max_candidates=int(settings.get("max_candidates") or 8), idea=idea,
            idea_fallback=fallback, book=book, state=state)
        for kind, description, platform in analysis_gaps:
            gaps.append(Gap(kind, description, platform=platform))
        # The brief matched no eligible candidate, and the scan will not substitute one.
        unmatched = (selection is None and bool(idea) and fallback == "wait"
                     and any(c["status"] != "excluded" for c in candidates))

        v2 = self._research_v2(book=book, state=state, vocabulary=vocabulary, config=config,
                               backlog=backlog,
                               records=records, as_of=as_of, ttl=ttl,
                               report_key=report_key, scope=scope, idea=idea)
        gaps.extend(v2["gaps"])
        if sources or not settings.get("require_external_evidence"):
            # With no evidence the scan waits (below) and carries nothing: no pin applies.
            chosen_before = selection and selection["opportunity_id"]
            selection = self._select(settings, v2, candidates, selection, state, idea)
            if selection and selection["opportunity_id"] != chosen_before:
                carried = next(c for c in state["candidates"]
                               if c["id"] == selection["candidate_id"])
                if carried not in candidates:
                    candidates.append(carried)      # the report always shows its shape
                if idea:
                    gaps[:] = [g for g in gaps if g.kind != "idea-unmatched"]
                    gaps.extend(self._brief_gaps(v2, selection, idea))
        unmatched = (selection is None and bool(idea) and fallback == "wait"
                     and any(b["status"] == "eligible" for b in v2["opportunities"]))
        claims = [book.claims[cid] for cid in sorted(book.closure(
            set(state["referenced"]) | v2["referenced"]))]

        report = self._report(
            report_id=report_id, settings=settings, scope=scope, as_of_text=as_of_text,
            model=model, model_path=model_path, ttl=ttl, collectors=collectors,
            corpus_hash=corpus_hash, sources=sources, profiles=profiles, claims=claims,
            platforms=platforms, candidates=candidates, selection=selection, gaps=gaps,
            context=context, idea=idea, v2=v2,
            unselected=("No eligible candidate matches the brief, and idea_fallback is wait: "
                        "nothing was selected." if unmatched else None))
        metadata = {
            "sources": report["evidence_summary"]["sources"],
            "claims": len(claims),
            "candidates": len(candidates),
            "selected": selection["candidate_id"] if selection else None,
        }
        report_out = ArtifactOutput("research-report", report, metadata=metadata)
        context.logger.info("research scan complete", report=report_id, **metadata)

        if not sources and settings.get("require_external_evidence"):
            return StepResult(
                StepOutcome.WAITING_FOR_INPUT, artifacts=[report_out],
                message=(f"no external evidence: add snapshots under "
                         f"{_shown(os.path.join(corpus, 'snapshots'))} "
                         f"or enable live probes, then resume"))
        if unmatched:
            return StepResult(
                StepOutcome.WAITING_FOR_INPUT, artifacts=[report_out],
                message=(f"the brief matches no concept research can carry; add a concept "
                         f"for it to {_shown(concepts_path)} "
                         f"(core/lifecycle/stages/market-scan.md), or set "
                         f"discovery.idea_fallback: nearest, then resume"))
        if selection is None:
            return StepResult(StepOutcome.BLOCKED, artifacts=[report_out],
                              message="no candidate survived screening; see the report's "
                                      "exclusion reasons")

        block = next(b for b in v2["opportunities"]
                     if b["opportunity_id"] == selection["opportunity_id"])
        author = self._design_author(context)
        if (block.get("capability") or {}).get("design_archetype") == AGENT_ONLY and \
                author != AGENT_ONLY:
            # Known now, not after strategy and a person's G2: the archetype author cannot
            # design a concept outside the catalog, and must not swap in another game.
            message = (f"the selected concept {selection['candidate_id']!r} needs the agent "
                       f"design author (design_archetype: agent), and factory.design.author "
                       f"is {author!r}: set `design: {{author: agent}}` with a "
                       f"`design.agent` host in workspace/config/factory.yaml (or copy the "
                       f"autonomous profile: docs/autonomous-runs.md), then resume")
            context.logger.warning("research selection needs the agent design author",
                                   candidate=selection["candidate_id"], author=author)
            return StepResult(StepOutcome.WAITING_FOR_INPUT, artifacts=[report_out],
                              message=message)
        opportunity = self._opportunity(block, report, profiles, context, as_of_text, idea,
                                        selected=block["opportunity_id"])
        persisted = []
        if settings.get("persist_backlog"):
            persisted = self._persist(settings, v2, report, profiles, context, as_of_text,
                                      idea, opportunity)
            context.logger.info("opportunities persisted to the backlog",
                                written=len(persisted))
        counts = v2["counts"]
        return StepResult.success(
            [report_out, ArtifactOutput("opportunity", opportunity,
                                        metadata={"opportunity_id": opportunity["id"],
                                                  "report": report_id,
                                                  "origin": block["origin"]})],
            message=f"selected {opportunity['id']} ({block['origin']}, built as "
                    f"{selection['candidate_id']}) from {counts['opportunities']} opportunities "
                    f"({counts['eligible']} buildable, {counts['capability-gap']} capability "
                    f"gaps) over {len(candidates)} catalog candidates"
                    + (f"; {len(persisted)} written to the backlog" if persisted else ""))

    @staticmethod
    def _design_author(context):
        """The design author this run's configuration names (`factory.design.author`), as
        the design step resolves it when its `with:` block names none."""
        return ((context.config or {}).get("design") or {}).get("author") or "archetype"

    # -- inputs ---------------------------------------------------------------------------

    def _archetypes(self, settings, concepts=()):
        document = load_file(_resolve(settings["catalog"])) or {}
        archetypes = document.get("archetypes") or []
        for archetype in archetypes:
            missing = [k for k in REQUIRED if k not in archetype]
            if missing:
                raise ResearchError(f"archetype {archetype.get('id')!r} lacks "
                                    f"{', '.join(missing)}")
            problem = _priors_problem(archetype)
            if problem:
                raise ResearchError(f"archetype {archetype.get('id')!r}: {problem}")
        catalog_ids = {a["id"] for a in archetypes}
        for concept in concepts:
            if concept["id"] in catalog_ids:
                raise ResearchError(f"{concept['_concepts_file']}: concept {concept['id']!r} "
                                    f"uses an id the catalog already has")
        genres = settings.get("genres")
        if genres:
            archetypes = [a for a in archetypes
                          if set(a.get("market_tags") or []) & set(genres)
                          or a["genre"] in genres]
        # A concept authored for the brief is always screened, whatever the genre scope.
        archetypes = list(archetypes) + list(concepts)
        if not archetypes:
            raise ResearchError("no archetype matches the scan's genre scope")
        return archetypes

    def _concepts(self, settings, corpus, idea):
        """(path, entries) of the project's concepts file; entries [] when there is none."""
        configured = settings.get("concepts")
        path = _resolve(configured) if configured else os.path.join(corpus, CONCEPTS_FILE)
        if not os.path.exists(path):
            if configured:
                raise ResearchError(f"no concepts file {configured!r}")
            return path, []
        shown = _shown(path)
        document = load_file(path)
        if (not isinstance(document, dict) or "version" not in document
                or not isinstance(document.get("archetypes"), list)):
            raise ResearchError(f"{shown}: a concepts file is {{version, archetypes: [...]}}")
        brief = canonical_idea(idea)
        entries, seen = [], set()
        for entry in document["archetypes"]:
            if not isinstance(entry, dict):
                raise ResearchError(f"{shown}: every concept is a mapping")
            missing = [k for k in REQUIRED + ("brief", "design_archetype") if k not in entry]
            if missing:
                raise ResearchError(f"{shown}: concept {entry.get('id')!r} lacks "
                                    f"{', '.join(missing)}")
            problem = _priors_problem(entry)
            if problem:
                raise ResearchError(f"{shown}: concept {entry['id']!r}: {problem}")
            if entry["brief"] != brief:
                raise ResearchError(f"{shown}: concept {entry['id']!r} was authored for "
                                    f"another brief ({entry['brief']!r}); the file holds "
                                    f"concepts for this run's brief only ({brief!r})")
            design = entry["design_archetype"]
            if not isinstance(design, str) or not _KEBAB.match(design):
                raise ResearchError(f"{shown}: concept {entry['id']!r} needs a design_archetype: "
                                    f"a design archetype id, or agent")
            if entry["id"] in seen:
                raise ResearchError(f"{shown}: concept {entry['id']!r} appears twice")
            seen.add(entry["id"])
            entries.append(dict(entry, _concepts_file=shown))
        return path, entries

    def _backlog(self, settings):
        backlog = []
        for path in sorted(glob.glob(os.path.join(_resolve(settings["backlog"]), "*",
                                                  "opportunity.json"))):
            with open(path, encoding="utf-8") as handle:
                try:
                    backlog.append(json.load(handle))
                except json.JSONDecodeError:
                    continue
        return backlog

    @staticmethod
    def _corpus_hash(sources, profiles, records=()):
        parts = sorted([f"{s.id}:{s.digest}" for s in sources]
                       + [f"profile:{pid}:{p['_digest']}" for pid, p in profiles.items()]
                       + [f"game:{record['id']}:{digest}" for _n, record, digest in records])
        return "sha256:" + hashlib.sha256("\n".join(parts).encode()).hexdigest()

    # -- outputs --------------------------------------------------------------------------

    def _provenance(self, artifact_type, scope_slug, as_of_text, context, inputs=(),
                    opportunity_id=None):
        return provenance.build(
            artifact_type,
            artifact_id=provenance.artifact_id(artifact_type, scope_slug, as_of_text,
                                               max(context.execution, 1)),
            produced_by=provenance.producer(self.role),
            produced_at=as_of_text,
            inputs=inputs,
            opportunity_id=opportunity_id or None,
            title_id=context.project_id or None)

    def _report(self, *, report_id, settings, scope, as_of_text, model, model_path, ttl,
                collectors, corpus_hash, sources, profiles, claims, platforms, candidates,
                selection, gaps, context, idea=None, unselected=None, v2=None):
        tiers = {"observed": 0, "derived": 0, "hypothesis": 0}
        for claim in claims:
            tiers[claim["tier"]] += 1
        profile_sources = []
        for pid, profile in sorted(profiles.items()):
            profile_sources.append({
                "id": f"profile-{pid}",
                "source_uri": profile.get("_path") or f"core/reference/platforms/{pid}.yaml",
                "source_kind": "other",
                "title": f"{profile.get('name', pid)} platform profile "
                         f"{profile.get('version', '?')} ({profile.get('status', 'unverified')})",
                "platform": pid,
                "observed_at": as_of_text,
                "collector": "platform-profiles",
                "fresh": True,
                "observations": 0,
            })
        external = [s.to_dict() for s in sources]
        question = settings.get("question") or (
            f"Is this game idea worth building for {', '.join(scope)}, and which proven web "
            f"game shape carries it best, balancing monetization fit, development speed, "
            f"technical and asset cost, platform compatibility, replayability, retention and "
            f"verification risk: \"{idea}\"?" if idea else
            f"Which kind of web game should the factory build next for "
            f"{', '.join(scope)}, balancing monetization fit, development speed, technical "
            f"and asset cost, platform compatibility, replayability, retention and "
            f"verification risk?")
        report_candidates = []
        for candidate in candidates:
            public = {k: v for k, v in candidate.items() if not k.startswith("_")}
            report_candidates.append(copy.deepcopy(public))
        scope_block = {"question": question, "platforms": list(scope), "as_of": as_of_text}
        if settings.get("genres"):
            scope_block["genres"] = list(settings["genres"])
        if idea:
            scope_block["brief"] = idea
        report = {
            "provenance": self._provenance("research-report", report_id, as_of_text, context),
            "id": report_id,
            "scope": scope_block,
            "method": {
                "scoring_model": {"id": str(model.get("id")), "version": str(model.get("version")),
                                  "file_hash": _file_hash(model_path)},
                "evidence_ttl_days": ttl,
                "collectors": collectors,
                "corpus_hash": corpus_hash,
            },
            "sources": profile_sources + external,
            "claims": claims,
            "platforms": platforms,
            "candidates": report_candidates,
            "selection": selection or {
                "candidate_id": "none",
                "opportunity_id": "opp-none",
                "rationale": unselected or "No candidate survived screening.",
                "runner_up": None,
            },
            "evidence_summary": {
                "sources": len(profile_sources) + len(external),
                "external_sources": len(external),
                "stale_sources": sum(1 for s in sources if not s.fresh),
                "claims_by_tier": tiers,
                "evidence_coverage": round((tiers["observed"] + tiers["derived"])
                                           / len(claims), 4) if claims else 0.0,
                "revenue": "Not estimated. No source in this scan attributes revenue to a "
                           "genre or title, and play counts measure traffic, not revenue.",
            },
            "gaps": [g.to_dict() for g in gaps],
        }
        if v2 is not None:
            selected = (selection or {}).get("opportunity_id")
            report.update({
                "research_version": 2,
                "corpus": v2["corpus"],
                "analyses": v2["analyses"],
                "competitors": v2["competitors"],
                "market": v2["market"],
                "patterns": v2["patterns"],
                "benchmarks": v2["benchmarks"],
                "opportunities": [_public(b, selected) for b in v2["opportunities"]],
                "capability_gaps": v2["capability_gaps"],
            })
        return provenance.seal(report)

    # -- Research V2 ----------------------------------------------------------------------

    def _research_v2(self, *, book, state, vocabulary, config, records, as_of, ttl,
                     report_key, scope, idea, backlog=()):
        """Corpus -> market cells -> patterns and benchmarks -> the opportunity space."""
        corpus = Corpus(vocabulary, config, book)
        corpus.add_records(records, as_of, ttl)
        corpus.add_listings(state["observations"])
        corpus.finish()
        frames, cells, trend, market_gaps = analyse_market(corpus, scope, book)
        patterns, pattern_gaps = extract_patterns(corpus, cells, book)
        benchmarks = extract_benchmarks(corpus, book)
        space = opportunity_space.Space(
            corpus=corpus, cells=cells, patterns=patterns, benchmarks=benchmarks,
            candidates=state["candidates"], views=state["views"], book=book,
            report_key=report_key, scope=scope, backlog=backlog)
        blocks, refused = opportunity_space.generate(space)
        ranked = opportunity_space.rank(space, blocks, idea)
        gaps = list(corpus.gaps) + list(market_gaps) + list(pattern_gaps)
        for summary in refused:
            gaps.append(Gap("insufficient-demand-evidence",
                            f"not proposed - its basis rests on no observation: {summary}"))
        capability_gaps = []
        for block in blocks:
            if block["status"] != "capability-gap":
                continue
            capability_gaps.append({
                "opportunity_id": block["opportunity_id"],
                "genre": block["_node"],
                "catalog_entry": block["capability"].get("catalog_entry"),
                "missing": list(block["capability"]["missing"]),
                "reason": block["capability"]["reason"],
                "evidence_backed": block["basis"]["evidence_backed"],
                "claim_refs": list(block["basis"]["claim_refs"]),
            })
            if block["origin"] != "capability-screen":
                gaps.append(Gap("capability-gap",
                                f"{block['opportunity_id']} ({block['origin']}, "
                                f"{block['_node']}): {block['capability']['reason']}"))
        referenced = set()
        games = [g.to_dict() for g in corpus.sorted_games()]
        for game in games:
            referenced.update(game["claim_refs"])
            for facet in game["facets"].values():
                referenced.update(facet["claim_refs"])
        for frame in frames:
            referenced.update(frame["claim_refs"])
        for cell in cells.values():
            for part in (cell.demand, cell.supply, cell.saturation, cell.competition,
                         cell.trend):
                referenced.update(part.get("claim_refs") or [])
        referenced.update(p["claim"] for p in patterns)
        referenced.update(b["claim"] for b in benchmarks)
        for block in blocks:
            referenced.update(block["claim_refs"])
            referenced.update(block["basis"]["claim_refs"])
            referenced.add(block["basis"]["thesis"])
        counts = {"opportunities": len(blocks),
                  "eligible": sum(1 for b in blocks if b["status"] == "eligible"),
                  "capability-gap": len(capability_gaps)}
        return {
            "corpus": corpus.describe(),
            "analyses": facet_summaries(corpus, cells),
            "competitors": games,
            "market": {"frames": frames,
                       "cells": [cells[k].to_dict() for k in sorted(cells)],
                       "trend": trend},
            "patterns": patterns,
            "benchmarks": benchmarks,
            "opportunities": blocks,
            "ranked": ranked,
            "capability_gaps": capability_gaps,
            "gaps": gaps,
            "referenced": referenced,
            "counts": counts,
        }

    def _select(self, settings, v2, candidates, selection, state, idea):
        """The run carries one opportunity; research proposed several. The ranked first is
        carried unless the step pins another (`select: <opportunity id>` - how a G1 choice
        or a person re-runs research on a different opportunity)."""
        ranked = v2["ranked"]
        pinned = settings.get("select")
        if idea and settings.get("idea_fallback") == "wait" and not pinned:
            # The brief is the person's question: with `wait`, only an opportunity that holds
            # some of its words may answer it, never the nearest substitute.
            ranked = [b for b in ranked if (b.get("brief_match") or {}).get("terms")]
        if pinned:
            chosen = next((b for b in v2["opportunities"]
                           if pinned in (b["opportunity_id"], (b.get("_candidate") or {}).get(
                               "id") if b["origin"] == "capability-screen" else None)), None)
            if chosen is None:
                raise ResearchError(f"select: no opportunity {pinned!r} in this scan")
            if chosen["status"] != "eligible":
                raise ResearchError(f"select: {pinned} is {chosen['status']}"
                                    + (f" ({chosen.get('exclusion_reason')})"
                                       if chosen.get("exclusion_reason") else "")
                                    + "; only a buildable, eligible opportunity can be carried")
        elif ranked:
            chosen = ranked[0]
        else:
            return None
        candidate = chosen["_candidate"]
        if selection and selection["candidate_id"] == candidate["id"] and \
                selection["opportunity_id"] == chosen["opportunity_id"]:
            return selection
        for c in state["candidates"]:
            if c["status"] == "selected":
                c["status"] = "considered"
        candidate["status"] = "selected"
        runner = next((b for b in ranked if b is not chosen), None)
        counts = v2["counts"]
        runner_candidate = (runner or {}).get("_candidate") or {}
        rationale = (
            ("Pinned by the step (`select`). " if pinned else "")
            + f"Research V2: {chosen['origin']} opportunity {chosen['opportunity_id']} - "
            f"{chosen['summary']} Built on the catalog shape {candidate['id']} (design "
            f"archetype {candidate['_archetype'].get('design_archetype')}, screen "
            f"{candidate['screen']['score']:.2f}); "
            f"{'resting on observed evidence' if chosen['basis']['evidence_backed'] else 'resting on estimates only'}. "
            f"{counts['opportunities']} opportunities proposed: {counts['eligible']} buildable, "
            f"{counts['capability-gap']} capability gaps. Revenue was not estimated."
            + (f" Runner-up: {runner['opportunity_id']} ({runner['origin']})." if runner else ""))
        # runner_up names a candidate, as it always has; the rationale names the opportunity.
        return {"candidate_id": candidate["id"], "opportunity_id": chosen["opportunity_id"],
                "rationale": rationale,
                "runner_up": runner_candidate.get("id")}

    @staticmethod
    def _brief_gaps(v2, selection, idea):
        """`idea-unmatched` for the opportunity actually carried, when it is not the
        catalog screen's pick."""
        block = next(b for b in v2["opportunities"]
                     if b["opportunity_id"] == selection["opportunity_id"])
        match = block.get("brief_match") or {"terms": [], "dimension": False}
        out = []
        if not match["terms"]:
            wanted = analysis.idea_terms(idea)
            out.append(Gap("idea-unmatched",
                           f"no opportunity's vocabulary matches the brief"
                           + (f" ({', '.join(wanted)})" if wanted else "")
                           + f"; carried {block['opportunity_id']} ({block['origin']}) by "
                             f"evidence. The brief is carried verbatim to strategy and design"))
        named = analysis.idea_dimension(idea)
        if named and not match["dimension"]:
            out.append(Gap("idea-unmatched",
                           f"the brief names {named}; the carried opportunity "
                           f"{block['opportunity_id']} does not render in it. The brief is "
                           f"carried verbatim to design, which chooses the dimension"))
        return out

    def _persist(self, settings, v2, report, profiles, context, as_of_text, idea, carried):
        """Write every proposed opportunity - buildable or a capability gap - to the backlog
        as `discovered`. Idempotent: an opportunity already on file is left as it is (the
        backlog is append-only; a later state belongs to whoever moved it)."""
        backlog = _resolve(settings["backlog"])
        written = []
        for block in v2["opportunities"]:
            if block["status"] not in ("eligible", "capability-gap"):
                continue
            if block["opportunity_id"] == carried["id"]:
                artifact = carried
            else:
                artifact = self._opportunity(block, report, profiles, context, as_of_text,
                                             idea)
            directory = os.path.join(backlog, artifact["id"])
            path = os.path.join(directory, "opportunity.json")
            if os.path.exists(path):
                continue
            os.makedirs(directory, exist_ok=True)
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump(artifact, handle, indent=2, ensure_ascii=False, sort_keys=False)
                handle.write("\n")
            os.replace(tmp, path)
            written.append(path)
        return written

    def _opportunity(self, block, report, profiles, context, as_of_text, idea=None,
                     selected=None):
        """The opportunity artifact for one research block: the v1 fields strategy has always
        read, filled from the buildable shape where research has nothing, plus the full
        `research` block."""
        vocabulary_cell = block["cell"]
        candidate = block.get("_candidate")
        archetype = candidate["_archetype"] if candidate else None
        node = block["_node"]
        public = _public(block, selected)
        corpus_born = block["origin"] != "capability-screen"
        fits = {f["platform"]: f for f in (candidate or {}).get("platform_fit") or []}
        platforms = list(block["_platforms"]) or (list(candidate["_viable"]) if candidate
                                                  else [])
        if not platforms:
            platforms = sorted({c["platform"] for c in block["market"]})[:1] or \
                list(report["scope"]["platforms"][:1])

        def text(facet):
            fv = vocabulary_cell.get(facet) or {}
            return fv.get("label") if fv.get("tier") != "unknown" and fv.get("label") else None

        fantasy = None
        player = vocabulary_cell.get("player_fantasy") or {}
        emotional = vocabulary_cell.get("emotional_fantasy") or {}
        if player.get("tier") not in (None, "unknown"):
            fantasy = player["label"].split(" (")[0]
            if emotional.get("tier") not in (None, "unknown"):
                fantasy += f" - {emotional['label'].split(' (')[0].lower()}"
        theme = text("theme")
        if archetype:
            genre = archetype["genre"]
            subgenre = node if corpus_born else archetype["subgenre"]
            core_mechanic = archetype["core_mechanic"]
            core_loop = archetype["core_loop"]
            fantasy = fantasy or archetype["fantasy"]
        else:
            genre = vocabulary_cell["family"]["value"]
            subgenre = node
            core_mechanic = text("mechanics") or "not yet researched: no teardown codes its mechanics"
            core_loop = text("gameplay_steps") or "not yet researched: no teardown codes its loop"
            fantasy = fantasy or "not yet researched: no teardown codes its fantasy"
        concept = {"genre": genre, "subgenre": subgenre, "core_mechanic": core_mechanic,
                   "fantasy": fantasy, "core_loop": core_loop}
        names = [c["name"] for c in block["competitors"]][:6]
        if not names and candidate:
            names = list(candidate["concept"].get("reference_titles") or [])
        concept["reference_titles"] = names

        title = archetype["title"] if (archetype and not corpus_born) else \
            vocabulary_cell["genre"]["label"]
        axis = block.get("changed_axis")
        if axis:
            title += f" - {vocabulary_cell[axis['facet']]['label']}"
        elif theme and corpus_born:
            title += f" - {theme.split(' (')[0]}"

        audience = {}
        player_type = block["audience"]["player_type"]
        if player_type["tier"] != "unknown":
            entry = self._vocab.entry("audience_type", player_type["value"])
            if entry.get("strategy_type"):
                audience["type"] = entry["strategy_type"]
        device = block["audience"]["device"]
        if device["tier"] != "unknown":
            audience["device"] = device["value"]
        regions = sorted({r for pid in platforms if pid in profiles
                          for r in ((profiles[pid].get("audience") or {})
                                    .get("primary_regions") or [])})
        audience["regions"] = regions

        risks = [{"description": r["description"], "severity": r["severity"],
                  "claim_refs": list(r.get("claim_refs") or [])} for r in block["risks"]]
        for pid in platforms:
            fit = fits.get(pid)
            if not fit:
                continue
            for concern in [c for c in fit.get("concerns") or [] if "exclusivity" not in c][:2]:
                risks.append({"description": f"{pid}: {concern}",
                              "severity": "medium" if "locali" in concern else "low",
                              "claim_refs": list(fit["claim_refs"])})
        exclusive = [pid for pid in platforms if any(
            "exclusivity" in c for c in (fits.get(pid) or {}).get("concerns") or [])]
        if exclusive:
            risks.append({
                "description": f"{', '.join(exclusive)} requires web exclusivity, so the "
                               f"candidate platforms cannot all be used for the same build; "
                               f"choosing is a strategy decision",
                "severity": "high",
                "claim_refs": sorted({c for pid in exclusive for c in fits[pid]["claim_refs"]}),
            })
        claim_refs = set(block["claim_refs"])
        if candidate and not corpus_born:
            claim_refs.update(candidate["claim_refs"])
        for risk in risks:
            claim_refs.update(risk["claim_refs"])
        opportunity = {
            "provenance": self._provenance(
                "opportunity", block["opportunity_id"], as_of_text, context,
                inputs=[{"artifact_id": report["provenance"]["artifact_id"],
                         "artifact_type": "research-report",
                         "content_hash": report["provenance"]["content_hash"]}],
                opportunity_id=block["opportunity_id"]),
            "id": block["opportunity_id"],
            "title": title,
            "state": "discovered",
            "concept": concept,
            "hypothesis": block["basis"]["thesis"],
            "audience": audience,
            "candidate_platforms": platforms,
        }
        if candidate:
            opportunity["monetization_hypothesis"] = copy.deepcopy(
                candidate["profile"]["monetization"])
            opportunity["estimates"] = {
                "dev_speed_days": archetype["dev_speed_days"],
                "scope_complexity": archetype["technical_complexity"],
                "asset_cost_usd": archetype["asset_cost_usd"],
                "session_seconds": archetype["session_seconds"],
            }
        elif block["monetization"].get("primary"):
            opportunity["monetization_hypothesis"] = {"primary": block["monetization"]["primary"]}
        opportunity.update({
            "claim_refs": sorted(claim_refs),
            "risks": risks,
            "research": public,
            "latest_evaluation_id": None,
            "title_id": None,
        })
        if idea:
            opportunity["brief"] = idea
        return provenance.seal(opportunity)



def _public(block, selected=None):
    """A research block without its internal keys; status `selected` for the carried one."""
    out = {k: copy.deepcopy(v) for k, v in block.items() if not k.startswith("_")}
    if selected and out["opportunity_id"] == selected:
        out["status"] = "selected"
    return out

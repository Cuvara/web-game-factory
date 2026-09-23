"""The `research` step: a bounded market scan that ends in a research report and one opportunity.

    evidence  ->  claims  ->  platform summaries  ->  screened candidates  ->  selection
    (evidence.py)          (analysis.py)                                      (here)

The question it answers is "what kind of web game should the factory build next?", not "is
this idea any good?": it screens every archetype in the catalog against what the target
portals allow and what the evidence shows, and carries the best-balanced one forward. It
never asks for, or needs, a game idea as input.

Settings, each optional, in increasing precedence: DEFAULTS below, `factory.discovery` in
workspace/config/factory.yaml, then the step's `with:` block in the workflow file.

    corpus          directory holding snapshots/ and probes.yaml   (workspace/research)
    platforms       platform ids to scope the scan to    (every profile except generic-web)
    genres          genre slugs; archetypes are kept if any market tag matches   (all)
    live            fetch probes.yaml pages during the run; also WGF_RESEARCH_LIVE=1  (off)
    require_external_evidence
                    wait for input when no external source was read   (true)
    max_candidates  how many screened candidates the report keeps   (8)
    scoring_model   file stem under core/reference/scoring/   (portfolio-default.v1)
    as_of           ISO timestamp the scan is "as of"; default now   (for reproducible runs)
    question        the scan's scope question, recorded in the report

Outcomes (docs/workflow-module-contract.md §7):

    SUCCESS            research-report + opportunity
    WAITING_FOR_INPUT  no external evidence at all - the report is still emitted, and says so
    BLOCKED            evidence read, but no candidate survived screening - report emitted
    FAILED, permanent  a malformed snapshot, probe file, catalog or scope
    FAILED, retryable  live fetching was the only evidence source and every fetch failed

Side effects: none outside the run. The step reads core/ and workspace/, and - only when
`live` is on - the network. It writes nothing but the artifacts it returns, so re-executing
it under the same idempotency key cannot duplicate anything; given the same corpus and
`as_of` it produces byte-identical artifacts.
"""

import copy
import glob
import hashlib
import json
import os
from datetime import datetime, timezone

from wgflib import paths
from wgflib.hashing import content_hash
from wgflib.workflow import ArtifactOutput, StepResult, WorkflowStep
from wgflib.workflow.model import StepOutcome
from wgflib.yamllite import YamlError, load_file

from . import analysis
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

SCHEMA_VERSION = "1.0.0"
CATALOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "archetypes.yaml")
CONTROL_PLATFORMS = ("generic-web",)

DEFAULTS = {
    "corpus": os.path.join("workspace", "research"),
    "platforms": None,
    "genres": None,
    "live": False,
    "require_external_evidence": True,
    "max_candidates": 8,
    "scoring_model": "portfolio-default.v1",
    "as_of": None,
    "question": None,
    "catalog": CATALOG,
    "backlog": paths.OPPORTUNITIES,
}


class ResearchError(ValueError):
    """The scan's own configuration is wrong. Not retryable."""


def _file_hash(path):
    with open(path, "rb") as handle:
        return "sha256:" + hashlib.sha256(handle.read()).hexdigest()


def _resolve(path):
    return path if os.path.isabs(path) else os.path.join(paths.ROOT, path)


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
        except (EvidenceError, ResearchError, YamlError) as exc:
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

    def _scan(self, settings, as_of, context):
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

        archetypes = self._archetypes(settings)
        corpus = _resolve(settings["corpus"])
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
        corpus_hash = self._corpus_hash(sources, profiles)
        report_key = hashlib.sha256(json.dumps(
            [corpus_hash, as_of_text[:10], scope, settings.get("genres"),
             _file_hash(settings["catalog"])], sort_keys=True).encode()).hexdigest()[:10]
        report_id = f"rr-{report_key}"

        claims, platforms, candidates, selection, analysis_gaps = analysis.analyse(
            sources=sources, profiles=profiles, archetypes=archetypes, model=model,
            backlog=backlog, as_of_text=stamp, report_key=report_key,
            max_candidates=int(settings.get("max_candidates") or 8))
        for kind, description, platform in analysis_gaps:
            gaps.append(Gap(kind, description, platform=platform))

        report = self._report(
            report_id=report_id, settings=settings, scope=scope, as_of_text=as_of_text,
            model=model, model_path=model_path, ttl=ttl, collectors=collectors,
            corpus_hash=corpus_hash, sources=sources, profiles=profiles, claims=claims,
            platforms=platforms, candidates=candidates, selection=selection, gaps=gaps,
            context=context)
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
                         f"{os.path.relpath(os.path.join(corpus, 'snapshots'), paths.ROOT)} "
                         f"or enable live probes, then resume"))
        if selection is None:
            return StepResult(StepOutcome.BLOCKED, artifacts=[report_out],
                              message="no candidate survived screening; see the report's "
                                      "exclusion reasons")

        chosen = next(c for c in candidates if c["id"] == selection["candidate_id"])
        opportunity = self._opportunity(chosen, report, profiles, context, as_of_text)
        return StepResult.success(
            [report_out, ArtifactOutput("opportunity", opportunity,
                                        metadata={"opportunity_id": opportunity["id"],
                                                  "report": report_id})],
            message=f"selected {chosen['id']} ({opportunity['id']}) from {len(candidates)} "
                    f"candidates")

    # -- inputs ---------------------------------------------------------------------------

    def _archetypes(self, settings):
        document = load_file(_resolve(settings["catalog"])) or {}
        archetypes = document.get("archetypes") or []
        required = ("id", "title", "genre", "subgenre", "core_mechanic", "fantasy",
                    "core_loop", "session_seconds", "replayability", "technical_complexity",
                    "asset_complexity", "dev_speed_days", "asset_cost_usd", "bundle_mb",
                    "monetization")
        for archetype in archetypes:
            missing = [k for k in required if k not in archetype]
            if missing:
                raise ResearchError(f"archetype {archetype.get('id')!r} lacks "
                                    f"{', '.join(missing)}")
        genres = settings.get("genres")
        if genres:
            archetypes = [a for a in archetypes
                          if set(a.get("market_tags") or []) & set(genres)
                          or a["genre"] in genres]
        if not archetypes:
            raise ResearchError("no archetype matches the scan's genre scope")
        return archetypes

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
    def _corpus_hash(sources, profiles):
        parts = sorted([f"{s.id}:{s.digest}" for s in sources]
                       + [f"profile:{pid}:{p['_digest']}" for pid, p in profiles.items()])
        return "sha256:" + hashlib.sha256("\n".join(parts).encode()).hexdigest()

    # -- outputs --------------------------------------------------------------------------

    def _provenance(self, artifact_type, scope_slug, as_of_text, context, inputs=(),
                    opportunity_id=None):
        provenance = {
            "artifact_id": f"wgf:{artifact_type}:{scope_slug}:"
                           f"{as_of_text[:10].replace('-', '')}-"
                           f"{min(max(context.execution, 1), 99):02d}",
            "artifact_type": artifact_type,
            "schema_version": SCHEMA_VERSION,
            "produced_by": {"role": self.role, "actor": "automation"},
            "produced_at": as_of_text,
            "inputs": list(inputs),
            "content_hash": "",
            "status": "draft",
        }
        if opportunity_id:
            provenance["opportunity_id"] = opportunity_id
        if context.project_id:
            provenance["title_id"] = context.project_id
        return provenance

    def _report(self, *, report_id, settings, scope, as_of_text, model, model_path, ttl,
                collectors, corpus_hash, sources, profiles, claims, platforms, candidates,
                selection, gaps, context):
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
                "rationale": "No candidate survived screening.",
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
        report["provenance"]["content_hash"] = content_hash(report)
        return report

    def _opportunity(self, chosen, report, profiles, context, as_of_text):
        archetype = chosen["_archetype"]
        viable = chosen["_viable"]
        fits = {f["platform"]: f for f in chosen["platform_fit"]}
        regions = sorted({r for pid in viable
                          for r in ((profiles[pid].get("audience") or {})
                                    .get("primary_regions") or [])})
        estimate_refs = next((d["claim_refs"] for d in chosen["dimensions"]
                              if d["dimension"] == "dev_speed_days"), [])
        risks = [{"description": r["description"], "severity": r["severity"],
                  "claim_refs": list(estimate_refs)}
                 for r in archetype.get("risks") or []]
        for pid in viable:
            for concern in [c for c in fits[pid].get("concerns") or []
                            if "exclusivity" not in c][:2]:
                risks.append({"description": f"{pid}: {concern}",
                              "severity": "medium" if "locali" in concern else "low",
                              "claim_refs": list(fits[pid]["claim_refs"])})
        exclusive = [pid for pid in viable if any(
            "exclusivity" in c for c in fits[pid].get("concerns") or [])]
        if exclusive:
            risks.append({
                "description": f"{', '.join(exclusive)} requires web exclusivity, so the "
                               f"candidate platforms cannot all be used for the same build; "
                               f"choosing is a strategy decision",
                "severity": "high",
                "claim_refs": sorted({c for pid in exclusive for c in fits[pid]["claim_refs"]}),
            })
        opportunity = {
            "provenance": self._provenance(
                "opportunity", chosen["opportunity_id"], as_of_text, context,
                inputs=[{"artifact_id": report["provenance"]["artifact_id"],
                         "artifact_type": "research-report",
                         "content_hash": report["provenance"]["content_hash"]}],
                opportunity_id=chosen["opportunity_id"]),
            "id": chosen["opportunity_id"],
            "title": archetype["title"],
            "state": "discovered",
            "concept": copy.deepcopy(chosen["concept"]),
            "hypothesis": chosen["_thesis"],
            "audience": {
                "type": "casual",
                "device": "both" if archetype.get("mobile_ready") else "desktop",
                "regions": regions,
            },
            "candidate_platforms": list(viable),
            "monetization_hypothesis": copy.deepcopy(chosen["profile"]["monetization"]),
            "estimates": {
                "dev_speed_days": archetype["dev_speed_days"],
                "scope_complexity": archetype["technical_complexity"],
                "asset_cost_usd": archetype["asset_cost_usd"],
                "session_seconds": archetype["session_seconds"],
            },
            "claim_refs": list(chosen["claim_refs"]),
            "risks": risks,
            "latest_evaluation_id": None,
            "title_id": None,
        }
        opportunity["provenance"]["content_hash"] = content_hash(opportunity)
        return opportunity

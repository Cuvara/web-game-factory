"""The discovery module: `wgf research`, from evidence to a research report and an opportunity.

Deterministic and offline. The corpus is scripts/tests/fixtures/discovery - invented,
labelled FIXTURE, every URI under fixtures.invalid - and the one live collector is handed a
fake fetcher. Nothing here touches the network, a portal or an AI provider.

What is covered, following docs/workflow-module-contract.md §11:

  Unit          the step's execute() with a fake context
  Evidence      tiers, excerpts, staleness, future dates, discrepancies, unknown facts
  Screening     vetoes, backlog deduplication, market-signal precedence, unscored revenue
  Failure paths every StepResult the step can return
  Idempotency   same corpus + as_of -> byte-identical artifacts, and no side effects
  Contract      the real engine and the real CLI, with the module named in config
  Schema        ajv, opt-in with WGF_AJV=1 (it needs npx and, the first time, a download)

Run from the repository root:

    python -m unittest discover scripts/tests
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, HERE)

import wgf_discovery  # noqa: E402
from wgf_discovery import evidence  # noqa: E402
from wgf_discovery.step import ResearchStep  # noqa: E402
from wgflib.hashing import content_hash  # noqa: E402
from wgflib.workflow.api import RunRequest, WorkflowAPI  # noqa: E402
from wgflib.workflow.config import FactoryConfig  # noqa: E402
from wgflib.workflow.contracts import ArtifactContracts  # noqa: E402
from wgflib.workflow.model import RunStatus, StepOutcome  # noqa: E402

FIXTURES = os.path.join(HERE, "fixtures", "discovery")
CORPUS = os.path.join(FIXTURES, "corpus")
BACKLOG = os.path.join(FIXTURES, "backlog")
AS_OF = "2026-09-23T00:00:00Z"
WORKFLOW_PACKAGE = os.path.join(SCRIPTS, "wgflib", "workflow")
YANDEX_PAGE = ("<html><head><title>FIXTURE Yandex SDK</title></head><body><p>To show a "
               "rewarded ad call ysdk.adv.showRewardedVideo() and pause the game.</p>"
               "<script>var ignored = 'thisTextIsNotOnThePage';</script></body></html>")


class FakeLogger:
    def __init__(self):
        self.records = []

    def _log(self, level, message, **fields):
        self.records.append((level, message, fields))

    def debug(self, message, **fields):
        self._log("debug", message, **fields)

    def info(self, message, **fields):
        self._log("info", message, **fields)

    def warning(self, message, **fields):
        self._log("warning", message, **fields)

    def error(self, message, **fields):
        self._log("error", message, **fields)


def fake_context(config=None, execution=1, project_id=None):
    return types.SimpleNamespace(
        config=config or {}, execution=execution, attempt=1, visit=1,
        project_id=project_id, run_id="run-test", current_step="research",
        idempotency_key="run-test:research:1", logger=FakeLogger(), mock=False,
        environment={}, previous_outputs=[], decision=None)


def definition(**params):
    base = {"corpus": CORPUS, "backlog": BACKLOG, "as_of": AS_OF}
    base.update(params)
    return types.SimpleNamespace(id="research", type="research", params=base,
                                 outputs=["research-report", "opportunity"], inputs=[])


def fake_fetcher(pages):
    calls = []

    def fetch(url):
        calls.append(url)
        if url not in pages:
            raise evidence.FetchError(f"{url}: unreachable (fake)")
        return pages[url]

    fetch.calls = calls
    return fetch


def run_step(fetcher=None, context=None, **params):
    step = ResearchStep(definition(**params), fetcher=fetcher,
                        clock=lambda: datetime(2026, 9, 23, tzinfo=timezone.utc))
    return step.execute(types.SimpleNamespace(refs={}, missing=[]), context or fake_context())


def artifacts(result):
    return {a.type: a.content for a in result.artifacts}


class Scratch(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.mkdtemp(prefix="wgf-discovery-")
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)

    def corpus(self, snapshots=(), probes=None, base=CORPUS):
        """A copy of the fixture corpus, plus extra snapshot documents."""
        target = os.path.join(self.scratch, "corpus")
        if base:
            shutil.copytree(base, target)
        else:
            os.makedirs(os.path.join(target, "snapshots"))
        for doc in snapshots:
            name = doc["id"] if isinstance(doc, dict) else doc[0]
            body = json.dumps(doc) if isinstance(doc, dict) else doc[1]
            with open(os.path.join(target, "snapshots", f"{name}.json"), "w",
                      encoding="utf-8") as handle:
                handle.write(body)
        if probes is not None:
            with open(os.path.join(target, "probes.yaml"), "w", encoding="utf-8") as handle:
                handle.write(probes)
        return target


# -- the successful scan --------------------------------------------------------------------


class ResearchReport(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = run_step()
        cls.out = artifacts(cls.result)
        cls.report = cls.out["research-report"]
        cls.opportunity = cls.out["opportunity"]
        cls.claims = {c["id"]: c for c in cls.report["claims"]}

    def test_succeeds_with_a_report_and_an_opportunity(self):
        self.assertEqual(self.result.outcome, StepOutcome.SUCCESS, self.result.error)
        self.assertEqual([a.type for a in self.result.artifacts],
                         ["research-report", "opportunity"])

    def test_both_artifacts_pass_the_engine_contract_check(self):
        contracts = ArtifactContracts()
        for artifact_type, content in self.out.items():
            self.assertEqual(contracts(artifact_type, content), [], artifact_type)
            self.assertEqual(content["provenance"]["content_hash"], content_hash(content))

    def test_the_opportunity_pins_the_report_it_came_from(self):
        pinned = self.opportunity["provenance"]["inputs"]
        self.assertEqual(pinned, [{
            "artifact_id": self.report["provenance"]["artifact_id"],
            "artifact_type": "research-report",
            "content_hash": self.report["provenance"]["content_hash"],
        }])
        self.assertEqual(self.opportunity["id"], self.report["selection"]["opportunity_id"])
        self.assertEqual(self.opportunity["state"], "discovered")

    def test_every_claim_obeys_its_tier(self):
        for claim in self.report["claims"]:
            with self.subTest(claim["id"]):
                self.assertRegex(claim["id"], r"^claim-[0-9a-z]{4,}$")
                if claim["tier"] == "observed":
                    self.assertTrue(claim["evidence"])
                    for item in claim["evidence"]:
                        self.assertTrue(item["source_uri"])
                        self.assertTrue(item["excerpt"])
                elif claim["tier"] == "derived":
                    self.assertTrue(claim["parents"])
                else:
                    self.assertLessEqual(claim["confidence"], 0.6)
                for parent in claim["parents"]:
                    self.assertIn(parent, self.claims, "a parent is missing from the report")

    def test_every_claim_reference_resolves_inside_the_report(self):
        refs = set(self.opportunity["claim_refs"]) | {self.opportunity["hypothesis"]}
        for risk in self.opportunity["risks"]:
            refs |= set(risk.get("claim_refs") or [])
        for platform in self.report["platforms"]:
            refs |= set(platform["claim_refs"])
        for candidate in self.report["candidates"]:
            refs |= set(candidate["claim_refs"]) | set(candidate["market_signal"]["claim_refs"])
            for fit in candidate["platform_fit"]:
                refs |= set(fit["claim_refs"])
            for dim in candidate["dimensions"]:
                refs |= set(dim["claim_refs"])
        self.assertEqual(sorted(refs - set(self.claims)), [])

    def test_every_external_observation_is_an_observed_claim_with_its_excerpt(self):
        observed = [c for c in self.report["claims"] if c["tier"] == "observed"
                    and c["evidence"][0]["source_uri"].startswith("https://fixtures.invalid")]
        excerpts = {c["evidence"][0]["excerpt"] for c in observed}
        self.assertIn("FIXTURE: initial download size must be at most 50MB.", excerpts)
        # Eight of the nine fixture observations: the excerpt-less one is refused. The one
        # with an unknown fact key stays an observation; only the fact is dropped.
        self.assertEqual(len(observed), 8)
        self.assertNotIn("FIXTURE: an observation with no excerpt must be refused.",
                         {c["statement"] for c in self.report["claims"]})

    def test_unverified_profiles_are_hypotheses_and_observations_replace_them(self):
        profile_claims = [c for c in self.report["claims"] if "platform-profile" in c["tags"]]
        self.assertEqual({c["subject"]["platform"] for c in profile_claims},
                         {"crazygames", "gamevui", "poki", "yandex"})
        for claim in profile_claims:
            self.assertEqual(claim["tier"], "hypothesis")
        poki = next(c for c in profile_claims if c["subject"]["platform"] == "poki")
        self.assertNotIn("in-app purchases", poki["statement"],
                         "a fact a source observed must not also rest on the profile")

    def test_a_source_contradicting_a_profile_is_a_discrepancy(self):
        crazy = next(p for p in self.report["platforms"] if p["platform"] == "crazygames")
        self.assertEqual(crazy["constraints"]["max_bundle_mb"], 50)
        self.assertIn("max_bundle_mb: source says 50, profile crazygames@1.0.0 says 250",
                      crazy["discrepancies"])
        self.assertIn("profile-discrepancy", {g["kind"] for g in self.report["gaps"]})

    def test_unknown_facts_and_missing_excerpts_are_reported_not_dropped(self):
        rejected = [g["description"] for g in self.report["gaps"]
                    if g["kind"] == "rejected-observation"]
        self.assertTrue(any("no verbatim excerpt" in d for d in rejected))
        self.assertTrue(any("'currency'" in d for d in rejected))

    def test_platform_summaries_cover_monetization_sdk_and_verification(self):
        platforms = {p["platform"]: p for p in self.report["platforms"]}
        self.assertEqual(sorted(platforms), ["crazygames", "gamevui", "poki", "yandex"])
        self.assertFalse(platforms["poki"]["monetization"]["iap"])
        self.assertFalse(platforms["gamevui"]["monetization"]["rewarded"])
        self.assertTrue(platforms["poki"]["constraints"]["web_exclusive"])
        for platform in platforms.values():
            self.assertIn(platform["sdk_complexity"], ("low", "medium", "high"))
            self.assertIn(platform["verification_risk"], ("low", "medium", "high"))

    def test_revenue_is_never_estimated(self):
        for candidate in self.report["candidates"]:
            revenue = next(d for d in candidate["dimensions"]
                           if d["dimension"] == "revenue_potential")
            self.assertIsNone(revenue["value"])
            self.assertIn("revenue", revenue["reason"])
        self.assertIn("Not estimated", self.report["evidence_summary"]["revenue"])

    def test_the_scan_widens_the_field_before_narrowing_it(self):
        candidates = self.report["candidates"]
        considered = [c for c in candidates if c["status"] != "excluded"]
        self.assertGreaterEqual(len(considered), 4)
        self.assertLessEqual(len(considered), 8)
        self.assertEqual([c["id"] for c in candidates if c["status"] == "selected"],
                         [self.report["selection"]["candidate_id"]])

    def test_candidates_balance_production_and_platform_dimensions(self):
        dims = {d["dimension"] for d in self.report["candidates"][0]["dimensions"]}
        for wanted in ("platform_fit", "dev_speed_days", "technical_risk", "asset_cost",
                       "replayability", "session_quality", "retention_potential",
                       "monetization_fit", "scope_complexity", "distribution_potential"):
            self.assertIn(wanted, dims)
        profile = self.report["candidates"][0]["profile"]
        for key in ("session_seconds", "replayability", "technical_complexity",
                    "asset_complexity", "mobile_ready", "monetization"):
            self.assertIn(key, profile)

    def test_a_backlog_duplicate_is_excluded_with_its_reason(self):
        physics = next(c for c in self.report["candidates"] if c["id"] == "physics-puzzle")
        self.assertEqual(physics["status"], "excluded", "exclusions survive the cap")
        self.assertEqual(physics["backlog_match"],
                         {"opportunity_id": "opp-900", "state": "rejected"})
        result = artifacts(run_step(genres=["physics"]))["research-report"]
        self.assertEqual(result["candidates"][0]["exclusion_reason"],
                         "duplicate of opp-900 (rejected) in the backlog")

    def test_observed_market_presence_outranks_estimates(self):
        selected = next(c for c in self.report["candidates"] if c["status"] == "selected")
        self.assertTrue(selected["market_signal"]["observed"])
        self.assertIn(selected["id"], ("block-puzzle", "sort-puzzle"))
        self.assertIn("Fixture", " ".join(selected["concept"]["reference_titles"]))

    def test_web_exclusivity_becomes_an_opportunity_risk(self):
        self.assertIn("poki", self.opportunity["candidate_platforms"])
        self.assertTrue(any("web exclusivity" in r["description"] and r["severity"] == "high"
                            for r in self.opportunity["risks"]))


# -- evidence rules -------------------------------------------------------------------------


class EvidenceRules(Scratch):
    def test_a_stale_source_is_kept_marked_and_down_weighted(self):
        stale = {
            "id": "snap-fx-stale", "source_uri": "https://fixtures.invalid/old",
            "source_kind": "portal-docs", "observed_at": "2025-01-01T00:00:00Z",
            "platform": "yandex",
            "observations": [{"statement": "FIXTURE: an old but real observation.",
                              "excerpt": "FIXTURE: old text", "subject": {"platform": "yandex"}}],
        }
        report = artifacts(run_step(corpus=self.corpus([stale])))["research-report"]
        source = next(s for s in report["sources"] if s["id"] == "snap-fx-stale")
        self.assertFalse(source["fresh"])
        claim = next(c for c in report["claims"] if c["statement"].startswith("FIXTURE: an old"))
        self.assertEqual(claim["confidence"], 0.6)
        self.assertEqual(report["evidence_summary"]["stale_sources"], 1)

    def test_a_source_dated_after_the_scan_is_refused(self):
        future = {
            "id": "snap-fx-future", "source_uri": "https://fixtures.invalid/future",
            "source_kind": "portal-docs", "observed_at": "2027-01-01T00:00:00Z",
            "observations": [{"statement": "FIXTURE: from the future.", "excerpt": "FIXTURE"}],
        }
        report = artifacts(run_step(corpus=self.corpus([future])))["research-report"]
        self.assertNotIn("snap-fx-future", {s["id"] for s in report["sources"]})
        self.assertTrue(any(g.get("source_id") == "snap-fx-future" for g in report["gaps"]))

    def test_every_shipped_snapshot_is_well_formed_and_excerpted(self):
        gaps = []
        directory = os.path.join(ROOT, "workspace", "research", "snapshots")
        sources = evidence.SnapshotCollector(directory).collect(
            datetime(2026, 9, 23, tzinfo=timezone.utc), 3650, gaps)
        for source in sources:
            self.assertTrue(source.source_uri.startswith("https://"), source.id)
            for obs in source.observations:
                self.assertTrue(obs.excerpt, source.id)
        self.assertEqual([g.description for g in gaps
                          if "no verbatim excerpt" in g.description], [])


# -- live probes ----------------------------------------------------------------------------


class LiveProbes(Scratch):
    def test_a_match_is_an_observation_quoting_the_page_and_a_miss_is_a_gap(self):
        fetch = fake_fetcher({"https://fixtures.invalid/yandex/sdk-adv": YANDEX_PAGE})
        report = artifacts(run_step(fetcher=fetch, live=True))["research-report"]
        self.assertEqual(fetch.calls, ["https://fixtures.invalid/yandex/sdk-adv"],
                         "one fetch per page, however many probes read it")
        live = [c for c in report["claims"] if "live-probes" in c["tags"]]
        self.assertEqual(len(live), 1)
        self.assertIn("showRewardedVideo", live[0]["evidence"][0]["excerpt"])
        self.assertEqual(live[0]["tier"], "observed")
        misses = [g for g in report["gaps"] if g["kind"] == "probe-miss"]
        self.assertEqual(len(misses), 1, "script text is stripped before matching")
        collector = next(c for c in report["method"]["collectors"] if c["id"] == "live-probes")
        self.assertEqual(collector["status"], "used")

    def test_live_is_off_by_default_and_never_fetches(self):
        fetch = fake_fetcher({})
        report = artifacts(run_step(fetcher=fetch))["research-report"]
        self.assertEqual(fetch.calls, [])
        collector = next(c for c in report["method"]["collectors"] if c["id"] == "live-probes")
        self.assertEqual(collector["status"], "disabled")

    def test_every_fetch_failing_with_no_other_evidence_is_retryable(self):
        with open(os.path.join(CORPUS, "probes.yaml"), encoding="utf-8") as handle:
            corpus = self.corpus(base=None, probes=handle.read())
        result = run_step(fetcher=fake_fetcher({}), corpus=corpus, live=True)
        self.assertEqual(result.outcome, StepOutcome.FAILED)
        self.assertTrue(result.retryable)

    def test_fetch_failures_beside_snapshot_evidence_are_gaps(self):
        result = run_step(fetcher=fake_fetcher({}), live=True)
        self.assertEqual(result.outcome, StepOutcome.SUCCESS)
        report = artifacts(result)["research-report"]
        self.assertIn("collector-failure", {g["kind"] for g in report["gaps"]})

    def test_the_real_fetcher_refuses_plain_http(self):
        with self.assertRaises(evidence.FetchError):
            evidence.UrllibFetcher()("http://fixtures.invalid/")


# -- failure paths --------------------------------------------------------------------------


class FailurePaths(Scratch):
    def test_no_external_evidence_waits_for_input_and_still_reports(self):
        result = run_step(corpus=self.corpus(base=None))
        self.assertEqual(result.outcome, StepOutcome.WAITING_FOR_INPUT)
        self.assertIn("snapshots", result.message)
        out = artifacts(result)
        self.assertEqual(list(out), ["research-report"])
        report = out["research-report"]
        self.assertEqual(report["evidence_summary"]["claims_by_tier"]["observed"], 0)
        self.assertIn("no-external-evidence", {g["kind"] for g in report["gaps"]})

    def test_without_the_evidence_requirement_it_proceeds_on_hypotheses(self):
        result = run_step(corpus=self.corpus(base=None), require_external_evidence=False)
        self.assertEqual(result.outcome, StepOutcome.SUCCESS)
        report = artifacts(result)["research-report"]
        self.assertEqual(report["evidence_summary"]["external_sources"], 0)

    def test_a_malformed_snapshot_fails_permanently(self):
        corpus = self.corpus([("snap-fx-broken", "{not json")])
        result = run_step(corpus=corpus)
        self.assertEqual(result.outcome, StepOutcome.FAILED)
        self.assertFalse(result.retryable)
        self.assertIn("snap-fx-broken.json", result.error)

    def test_a_snapshot_without_identity_fails_permanently(self):
        corpus = self.corpus([("snap-fx-anon", json.dumps({"id": "Not An Id"}))])
        result = run_step(corpus=corpus)
        self.assertFalse(result.retryable)
        self.assertIn("snap-", result.error)

    def test_an_unknown_platform_fails_permanently(self):
        result = run_step(platforms=["atlantis"])
        self.assertEqual(result.outcome, StepOutcome.FAILED)
        self.assertFalse(result.retryable)
        self.assertIn("atlantis", result.error)

    def test_no_viable_candidate_blocks_with_the_report(self):
        # GameVui carries no rewarded ads, and every puzzle archetype leads with them.
        result = run_step(platforms=["gamevui"], genres=["sorting", "block-puzzle"])
        self.assertEqual(result.outcome, StepOutcome.BLOCKED)
        report = artifacts(result)["research-report"]
        self.assertEqual({c["status"] for c in report["candidates"]}, {"excluded"})
        self.assertEqual(report["selection"]["candidate_id"], "none")

    def test_a_veto_excludes_a_candidate(self):
        catalog = os.path.join(tempfile.mkdtemp(dir=self.scratch), "catalog.yaml")
        with open(wgf_discovery.step.CATALOG, encoding="utf-8") as handle:
            text = handle.read()
        with open(catalog, "w", encoding="utf-8") as handle:
            handle.write(text.replace("dev_speed_days: 7\n", "dev_speed_days: 30\n", 1))
        report = artifacts(run_step(catalog=catalog))["research-report"]
        block = next(c for c in report["candidates"] if c["id"] == "block-puzzle")
        self.assertEqual(block["status"], "excluded")
        self.assertEqual(block["exclusion_reason"], "veto fired: over_timebox")
        timebox = next(v for v in block["screen"]["vetoes"] if v["criterion_id"] == "over_timebox")
        self.assertEqual((timebox["breached"], timebox["measured"]), (True, 30))

    def test_a_bad_as_of_fails_permanently(self):
        result = run_step(as_of="yesterday")
        self.assertFalse(result.retryable)


# -- idempotency ----------------------------------------------------------------------------


class Idempotency(unittest.TestCase):
    def test_same_corpus_and_as_of_give_identical_artifacts(self):
        first = artifacts(run_step())
        second = artifacts(run_step())
        self.assertEqual(json.dumps(first, sort_keys=True), json.dumps(second, sort_keys=True))

    def test_the_scan_writes_nothing(self):
        before = snapshot_tree(os.path.join(ROOT, "workspace"))
        run_step()
        self.assertEqual(snapshot_tree(os.path.join(ROOT, "workspace")), before)

    def test_a_retry_changes_only_the_artifact_sequence(self):
        first = artifacts(run_step(context=fake_context(execution=1)))["research-report"]
        second = artifacts(run_step(context=fake_context(execution=2)))["research-report"]
        self.assertTrue(first["provenance"]["artifact_id"].endswith("-01"))
        self.assertTrue(second["provenance"]["artifact_id"].endswith("-02"))
        strip = lambda r: {k: v for k, v in r.items() if k != "provenance"}  # noqa: E731
        self.assertEqual(strip(first), strip(second))


def snapshot_tree(root):
    found = {}
    for directory, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for name in files:
            path = os.path.join(directory, name)
            with open(path, "rb") as handle:
                found[os.path.relpath(path, root)] = handle.read()
    return found


# -- through the engine and the CLI ---------------------------------------------------------


class EngineContract(Scratch):
    def config(self):
        return {"steps": {"modules": ["wgf_discovery"]}, "storage": {"fsync": False},
                "discovery": {"corpus": CORPUS, "backlog": BACKLOG, "as_of": AS_OF}}

    def test_wgf_research_runs_the_module_through_the_real_engine(self):
        from test_workflow_contracts import tree_digest

        engine_before = tree_digest(WORKFLOW_PACKAGE)
        api = WorkflowAPI(config=FactoryConfig(self.config()),
                          store_dir=os.path.join(self.scratch, "store"))
        state = api.run(RunRequest(scope="research"))
        self.assertEqual(state.status, RunStatus.COMPLETED, state.message)
        stored = {}
        for artifact_type in ("research-report", "opportunity"):
            ref = state.latest_artifact(artifact_type)
            stored[artifact_type] = api.store.read_artifact(state.run_id, ref)
            self.assertEqual(ref.content_hash,
                             stored[artifact_type]["provenance"]["content_hash"])
            self.assertEqual(ref.produced_by, "research")
        self.assertEqual(state.latest_artifact("research-report").metadata["selected"],
                         stored["research-report"]["selection"]["candidate_id"])
        self.assertEqual(tree_digest(WORKFLOW_PACKAGE), engine_before)

    def test_mock_still_replaces_the_module(self):
        api = WorkflowAPI(config=FactoryConfig(self.config()),
                          store_dir=os.path.join(self.scratch, "store"))
        state = api.run(RunRequest(mock=True))
        self.assertEqual(state.status, RunStatus.COMPLETED)
        report = api.store.read_artifact(state.run_id, state.latest_artifact("research-report"))
        self.assertEqual(report["id"], "rr-mock")

    def test_the_kernel_does_not_know_the_module(self):
        for name in os.listdir(WORKFLOW_PACKAGE):
            if name.endswith(".py"):
                with open(os.path.join(WORKFLOW_PACKAGE, name), encoding="utf-8") as handle:
                    self.assertNotIn("wgf_discovery", handle.read(), name)


class Cli(Scratch):
    def wgf(self, *args, config):
        path = os.path.join(self.scratch, "factory.yaml")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(config)
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        env.pop("WGF_RESEARCH_LIVE", None)
        return subprocess.run(
            [sys.executable, os.path.join(SCRIPTS, "wgf.py"), *args,
             "--store", os.path.join(self.scratch, "store"), "--config", path],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8", env=env)

    CONFIG = (
        "factory:\n"
        "  storage:\n    fsync: false\n"
        "  steps:\n    modules: [wgf_discovery]\n"
        "  discovery:\n"
        f"    corpus: {CORPUS}\n"
        f"    backlog: {BACKLOG}\n"
        f"    as_of: '{AS_OF}'\n"
    )

    def test_wgf_research(self):
        done = self.wgf("research", config=self.CONFIG)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("Workflow completed successfully.", done.stdout)

    def test_wgf_new_game_mock(self):
        done = self.wgf("new-game", "--mock", config=self.CONFIG)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("Workflow completed successfully.", done.stdout)

    def test_wgf_research_waits_when_there_is_no_evidence(self):
        empty = os.path.join(self.scratch, "empty")
        os.makedirs(os.path.join(empty, "snapshots"))
        done = self.wgf("research", config=self.CONFIG.replace(CORPUS, empty))
        self.assertEqual(done.returncode, 3, done.stdout + done.stderr)


# -- full schema validation, opt-in ---------------------------------------------------------


@unittest.skipUnless(os.environ.get("WGF_AJV") == "1" and shutil.which("npx"),
                     "set WGF_AJV=1 to validate with ajv (needs npx; downloads ajv once)")
class AjvSchema(Scratch):
    def validate(self, schema, content):
        path = os.path.join(self.scratch, f"{schema}.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(content, handle)
        done = subprocess.run(
            ["npx", "--yes", "-p", "ajv-cli@5", "-p", "ajv-formats@2", "ajv", "validate",
             "-s", f"core/artifacts/{schema}.schema.json",
             "-r", "core/artifacts/shared/*.schema.json", "-c", "ajv-formats",
             "--spec=draft2020", "--strict=false", "-d", path],
            cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)

    def test_emitted_artifacts_validate(self):
        out = artifacts(run_step(fetcher=fake_fetcher(
            {"https://fixtures.invalid/yandex/sdk-adv": YANDEX_PAGE}), live=True))
        self.validate("research-report", out["research-report"])
        self.validate("opportunity", out["opportunity"])

    def test_waiting_and_blocked_reports_validate(self):
        self.validate("research-report",
                      artifacts(run_step(corpus=self.corpus(base=None)))["research-report"])
        self.validate("research-report", artifacts(run_step(
            platforms=["gamevui"], genres=["sorting"]))["research-report"])


if __name__ == "__main__":
    unittest.main()

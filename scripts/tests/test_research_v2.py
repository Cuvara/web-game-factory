"""Research V2: a game corpus, counted patterns, market cells and an opportunity space.

    Vocabularies   the shared codes and the analysis thresholds load, validate and resolve
    Support        a counting claim states numerator, denominator, members and frame, or it
                   is refused - by the ClaimBook and by the claim schema
    Corpus         teardown records and listings become games; an interpretation is a
                   derived claim, never an observation; broken records fail the scan
    Market         demand, supply, saturation, competition and trend kept apart, each with
                   its count; supply without observed demand is not an opportunity
    Patterns       cross-game patterns and benchmarks, with members and exceptions
    Opportunities  several per scan, from five generators; nothing without an observation;
                   unbuildable ones kept as capability gaps; a pin; the backlog
    Handoff        the real engine: research -> strategy -> G2 -> design -> tech plan, and
                   theme, fantasy, art and provenance survive every step
    Corrections    the worked example's invalid evidence superseded, never edited

Deterministic and offline. The V2 corpus (scripts/tests/fixtures/research-v2) is FIXTURE
data: invented, under fixtures.invalid, every record marked `fixture: true`.

    python -m unittest scripts.tests.test_research_v2
"""

import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, HERE)

from test_discovery import FakeLogger, fake_context  # noqa: E402
from wgf_design import identity  # noqa: E402
from wgf_design.step import DesignStep  # noqa: E402
from wgf_discovery import opportunities as opportunity_space  # noqa: E402
from wgf_discovery.analysis import ClaimBook, SupportError, check_support  # noqa: E402
from wgf_discovery.corpus import Corpus, game_id_for, load_records  # noqa: E402
from wgf_discovery.evidence import EvidenceError, parse_time  # noqa: E402
from wgf_discovery.step import ResearchStep  # noqa: E402
from wgf_discovery.vocabulary import AnalysisConfig, Vocabulary, VocabularyError  # noqa: E402
from wgf_strategy import plan_strategy  # noqa: E402
from wgf_strategy.profiles import load_profiles, load_vocabulary  # noqa: E402
from wgflib import paths  # noqa: E402
from wgflib.hashing import content_hash  # noqa: E402
from wgflib.jsonschema_lite import Registry, Validator  # noqa: E402
from wgflib.workflow.contracts import ArtifactContracts  # noqa: E402
from wgflib.workflow.model import StepOutcome  # noqa: E402

V2 = os.path.join(HERE, "fixtures", "research-v2")
SHIPPED = os.path.join(ROOT, "workspace", "research")
AS_OF = "2026-09-23T00:00:00Z"
ENGINE = os.path.join(SCRIPTS, "wgf.py")
CONTRACTS = ArtifactContracts()


def scan(corpus=V2, platforms=("poki", "crazygames"), context=None, **params):
    base = {"corpus": corpus, "backlog": os.path.join(tempfile.gettempdir(),
                                                      "wgf-v2-no-backlog"),
            "as_of": AS_OF}
    if platforms:
        base["platforms"] = list(platforms)
    base.update(params)
    definition = types.SimpleNamespace(id="research", type="research", params=base,
                                       outputs=["research-report", "opportunity"], inputs=[])
    step = ResearchStep(definition)
    return step.execute(types.SimpleNamespace(refs={}, missing=[]), context or fake_context())


def outputs(result):
    return {a.type: a.content for a in result.artifacts}


def claim_validator():
    with open(os.path.join(paths.ARTIFACTS, "shared", "claim.schema.json"),
              encoding="utf-8") as handle:
        schema = json.load(handle)
    return Validator(schema, Registry().add_directory(paths.ARTIFACTS))


class FixtureScan(unittest.TestCase):
    """One scan of the V2 fixture corpus, shared by the read-only tests."""

    @classmethod
    def setUpClass(cls):
        cls.result = scan()
        cls.artifacts = outputs(cls.result)
        cls.report = cls.artifacts.get("research-report")
        cls.opportunity = cls.artifacts.get("opportunity")
        cls.claims = {c["id"]: c for c in (cls.report or {}).get("claims") or []}

    def cell(self, cell_id):
        return next(c for c in self.report["market"]["cells"] if c["cell"] == cell_id)

    def pattern(self, pattern_id):
        return next(p for p in self.report["patterns"] if p["id"] == pattern_id)


# -- vocabularies --------------------------------------------------------------------------


class Vocabularies(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.vocabulary = Vocabulary()
        cls.config = AnalysisConfig()

    def test_shipped_vocabulary_and_analysis_validate_and_agree(self):
        self.config.check_against(self.vocabulary)
        self.assertRegex(self.vocabulary.version, r"^\d+\.\d+\.\d+$")
        self.assertTrue(self.vocabulary.file_hash.startswith("sha256:"))

    def test_the_genre_system_covers_every_family_research_must_understand(self):
        genres = self.vocabulary.genres
        for family in ("puzzle", "arcade", "idle", "simulation", "strategy", "physics",
                       "shooter", "sports", "racing", "card", "word", "platformer", "action"):
            self.assertIn(family, genres)
            self.assertNotIn("parent", genres[family], family)
        for node, parent in (("match", "puzzle"), ("match-3", "match"),
                             ("merge-puzzle", "puzzle"), ("idle-merge", "idle"),
                             ("runner", "arcade"), ("tower-defense", "strategy"),
                             ("physics-puzzle", "puzzle"), ("word-search", "word")):
            self.assertEqual(genres[node]["parent"], parent, node)
        # Hyper-casual and casual are market descriptors, not genre branches.
        self.assertEqual(set(self.vocabulary.descriptors), {"hyper-casual", "casual", "midcore"})
        self.assertNotIn("casual", genres)

    def test_the_tree_resolves_portal_tags_in_any_locale(self):
        v = self.vocabulary
        self.assertEqual(v.lineage("match-3"), ["match-3", "match", "puzzle"])
        self.assertEqual(v.family("lane-runner"), "arcade")
        self.assertEqual(v.genre_for("Match 3"), None)
        self.assertEqual(v.genre_for("match3"), "match-3")
        self.assertEqual(v.genre_for("Головоломки"), "puzzle")
        self.assertEqual(v.genre_for("sorting"), "sort-puzzle")
        self.assertTrue(v.is_within("tile-match", "puzzle"))
        self.assertFalse(v.is_within("puzzle", "tile-match"))

    def test_every_facet_names_its_values_and_codings_are_checked(self):
        v = self.vocabulary
        for facet in ("genre", "mechanics", "gameplay_steps", "controls", "theme",
                      "player_fantasy", "emotional_fantasy", "art_rendering", "art_tone",
                      "audience_type", "intent", "run_seconds", "progression",
                      "difficulty_shape", "retention_hooks", "ad_triggers", "tutorial",
                      "physics_engine", "networking", "unique_assets"):
            self.assertIsNotNone(v.facet(facet), facet)
        self.assertIsNone(v.check("theme", "zombies"))
        self.assertIn("not in vocabulary", v.check("theme", "werewolves"))
        self.assertIn("list", v.check("mechanics", "swap-match"))
        self.assertIn("number", v.check("run_seconds", "long"))
        self.assertIn("unknown facet", v.check("vibes", "good"))

    def test_a_malformed_vocabulary_is_refused(self):
        scratch = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, scratch)
        with open(self.vocabulary.path, encoding="utf-8") as handle:
            text = handle.read()
        path = os.path.join(scratch, "v.yaml")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text.replace("parent: puzzle, aliases: [matching", "parent: nowhere, aliases: [matching", 1))
        with self.assertRaises(VocabularyError):
            Vocabulary(path)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text.replace("version: 1.0.0", "version: one"))
        with self.assertRaises(VocabularyError):
            Vocabulary(path)

    def test_lists_are_read_as_popularity_editorial_or_category(self):
        kind = self.config.list_kind
        self.assertEqual(kind("category:puzzle most-popular"), "popularity")
        self.assertEqual(kind("category:puzzle merge-puzzles-top"), "popularity")
        self.assertEqual(kind("category:puzzle editorial"), "editorial")
        self.assertEqual(kind("category:puzzles"), "category")
        self.assertEqual(kind("anything", "popularity"), "popularity")
        self.assertEqual(kind("category:stopwatch"), "category")


# -- support: no share without a denominator -----------------------------------------------


class Support(unittest.TestCase):
    GOOD = {"numerator": 2, "denominator": 3, "members": ["a", "b"], "exceptions": ["c"],
            "frame": "games coded x"}

    def test_a_valid_count_passes(self):
        self.assertEqual(check_support(self.GOOD)["denominator"], 3)

    def test_a_derived_statistic_without_a_denominator_is_refused(self):
        for broken in ({"numerator": 1, "members": ["a"], "frame": "f"},
                       dict(self.GOOD, denominator=0),
                       dict(self.GOOD, denominator=None),
                       dict(self.GOOD, denominator=True),
                       dict(self.GOOD, numerator=4),
                       dict(self.GOOD, members=["a"]),
                       dict(self.GOOD, exceptions=["a"]),
                       dict(self.GOOD, exceptions=["c", "d"]),
                       dict(self.GOOD, frame=" ")):
            with self.assertRaises(SupportError, msg=broken):
                check_support(broken)

    def test_the_claim_book_refuses_a_pattern_without_a_count(self):
        book = ClaimBook("2026-09-23T00:00:00Z")
        parent = book.hypothesis("p", "A parent claim for the test.", {})
        with self.assertRaises(ValueError):
            book.derived("k", "3 of 4 games do it.", [parent], {}, tags=["pattern"])
        cid = book.derived("k", "2 of 3 games do it.", [parent], {}, tags=["pattern"],
                           support=self.GOOD)
        self.assertEqual(book.claims[cid]["support"]["numerator"], 2)

    def test_the_claim_schema_enforces_the_same_rule(self):
        validator = claim_validator()
        base = {"id": "claim-aaaa", "statement": "2 of 3 games do it.", "tier": "derived",
                "confidence": 0.5, "asserted_at": AS_OF, "parents": ["claim-bbbb"],
                "tags": ["pattern"]}
        self.assertTrue(list(validator.iter_errors(base)), "pattern without support")
        self.assertFalse(list(validator.iter_errors(dict(base, support=self.GOOD))))
        hypothesis = dict(base, tier="hypothesis", parents=[], tags=[], support=self.GOOD)
        self.assertTrue(list(validator.iter_errors(hypothesis)), "a hypothesis counts nothing")
        observed = dict(base, tier="observed", parents=[], tags=[], evidence=[])
        self.assertTrue(list(validator.iter_errors(observed)), "observed without evidence")
        high = dict(base, tier="hypothesis", parents=[], tags=[], confidence=0.9)
        self.assertTrue(list(validator.iter_errors(high)), "hypothesis above 0.6")


# -- the corpus ----------------------------------------------------------------------------


class CorpusRecords(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.mkdtemp(prefix="wgf-v2-corpus-")
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)
        self.vocabulary, self.config = Vocabulary(), AnalysisConfig()

    def record(self, name="game-fx-candy-swap"):
        with open(os.path.join(V2, "games", f"{name}.json"), encoding="utf-8") as handle:
            return json.load(handle)

    def write(self, record, name=None):
        games = os.path.join(self.scratch, "games")
        os.makedirs(games, exist_ok=True)
        path = os.path.join(games, f"{name or record['id']}.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(record, handle)
        return games

    def build(self, records):
        book = ClaimBook(AS_OF)
        corpus = Corpus(self.vocabulary, self.config, book)
        corpus.add_records(records, parse_time(AS_OF), 45)
        corpus.finish()
        return corpus, book

    def test_every_shipped_fixture_record_is_a_valid_game_record(self):
        records = load_records(os.path.join(V2, "games"))
        self.assertEqual(len(records), 6)
        for _name, record, _digest in records:
            self.assertTrue(record["fixture"], record["id"])
            for session in record["sessions"]:
                self.assertIn("fixtures.invalid", session["source_uri"])

    def test_observed_codings_are_observations_and_interpretations_are_derived(self):
        corpus, book = self.build(load_records(os.path.join(V2, "games")))
        game = corpus.games["game-fx-candy-swap"]
        self.assertEqual(game.depth, "teardown")
        run = book.claims[game.facets["run_seconds"]["claim_refs"][0]]
        self.assertEqual(run["tier"], "observed")
        evidence = run["evidence"][0]
        self.assertEqual(evidence["method"], "played")
        self.assertEqual(evidence["session_id"], "ts-fx-candy-swap-a")
        self.assertIn("capture_uri", evidence)
        theme = book.claims[game.facets["theme"]["claim_refs"][0]]
        self.assertEqual(theme["tier"], "derived")
        self.assertEqual(game.facets["theme"]["tier"], "derived")
        session = book.claims[theme["parents"][0]]
        self.assertEqual((session["tier"], "session" in session["tags"]), ("observed", True))
        self.assertIn("fixture", theme["tags"])
        self.assertTrue(any(g.kind == "fixture-evidence" for g in corpus.gaps))

    def test_a_coding_outside_the_vocabulary_is_a_gap_not_a_count(self):
        record = self.record()
        record["observations"].append({"session": "ts-fx-candy-swap-a", "facet": "theme",
                                       "value": "werewolves", "coding": "interpreted",
                                       "excerpt": "FIXTURE: werewolves"})
        record["observations"] = [o for o in record["observations"] if o["facet"] != "theme"
                                  or o["value"] == "werewolves"]
        corpus, _book = self.build(load_records(self.write(record)))
        self.assertNotIn("theme", corpus.games["game-fx-candy-swap"].facets)
        self.assertTrue(any(g.kind == "unmapped-vocabulary" and "werewolves" in g.description
                            for g in corpus.gaps))

    def test_a_session_dated_after_the_scan_is_refused(self):
        record = self.record()
        record["sessions"][0]["observed_at"] = "2027-01-01T00:00:00Z"
        corpus, _book = self.build(load_records(self.write(record)))
        self.assertEqual(corpus.games["game-fx-candy-swap"].facets, {})
        self.assertTrue(any(g.kind == "rejected-observation" for g in corpus.gaps))

    def test_a_broken_record_fails_the_scan_permanently(self):
        record = self.record()
        del record["sessions"][0]["viewport"]          # a played session must name it
        with self.assertRaises(EvidenceError):
            load_records(self.write(record))
        shutil.rmtree(os.path.join(self.scratch, "games"))
        with self.assertRaises(EvidenceError):
            load_records(self.write(self.record(), name="game-another-name"))
        shutil.rmtree(os.path.join(self.scratch, "games"))
        games = self.write(self.record())
        with open(os.path.join(games, "game-broken.json"), "w") as handle:
            handle.write("{not json")
        with self.assertRaises(EvidenceError):
            load_records(games)

    def test_a_broken_record_makes_the_step_fail_without_retry(self):
        record = self.record()
        record["observations"][0]["coding"] = "guessed"
        self.write(record)
        result = scan(corpus=self.scratch)
        self.assertEqual(result.outcome, StepOutcome.FAILED)
        self.assertFalse(result.retryable)

    def test_game_ids_are_stable_and_never_collide_on_another_script(self):
        self.assertEqual(game_id_for("FX Candy Swap"), "game-fx-candy-swap")
        self.assertEqual(game_id_for("FX Candy Swap"), game_id_for("  fx candy  swap "))
        a, b = game_id_for("Сортировка Болтомания"), game_id_for("Маджонг: Супер Соедини")
        self.assertNotEqual(a, b)
        self.assertRegex(a, r"^game-[a-z0-9][a-z0-9-]*$")


class CorpusInReport(FixtureScan):
    def test_the_corpus_joins_listings_and_teardowns(self):
        corpus = self.report["corpus"]
        self.assertEqual((corpus["games"], corpus["teardown_games"], corpus["listing_games"],
                          corpus["fixture_games"]), (9, 6, 3, 9))
        games = {g["id"]: g for g in self.report["competitors"]}
        candy = games["game-fx-candy-swap"]
        self.assertEqual(candy["depth"], "teardown")
        self.assertIn("poki", candy["platforms"])
        self.assertTrue(any(entry["list_kind"] == "popularity" for entry in candy["listings"]))
        self.assertEqual(candy["facets"]["genre"]["value"], "match-3")
        self.assertEqual(candy["facets"]["genre"]["tier"], "observed")
        self.assertEqual(games["game-fx-logic-grid"]["depth"], "listing")

    def test_every_domain_has_a_view_over_the_same_corpus(self):
        analyses = self.report["analyses"]
        for section in ("genre", "gameplay", "mechanics", "theme", "fantasy", "art",
                        "audience", "session_retention", "monetization", "ux", "production"):
            self.assertIn(section, analyses)
        theme = next(f for f in analyses["theme"] if f["facet"] == "theme")
        self.assertEqual((theme["games_in_scope"], theme["coded"]), (6, 6))
        run = next(f for f in analyses["session_retention"] if f["facet"] == "run_seconds")
        self.assertEqual(run["benchmark"]["n"], 6)


# -- market --------------------------------------------------------------------------------


class Market(FixtureScan):
    def test_demand_is_a_share_of_popularity_lists_with_its_count(self):
        demand = self.cell("match-3@poki")["demand"]
        self.assertEqual((demand["numerator"], demand["denominator"], demand["share"]),
                         (3, 5, 0.6))
        self.assertIn("2026-09-20", demand["frame"])
        claim = self.claims[demand["claim_refs"][0]]
        self.assertEqual(claim["tier"], "derived")
        self.assertEqual(claim["support"]["numerator"], 3)
        self.assertEqual(len(claim["support"]["exceptions"]), 2)

    def test_supply_and_saturation_are_separate_and_need_both_sides(self):
        cell = self.cell("match-3@poki")
        self.assertEqual((cell["supply"]["numerator"], cell["supply"]["denominator"]),
                         (30, 300))
        self.assertEqual(cell["saturation"]["status"], "under-supplied")
        self.assertAlmostEqual(cell["saturation"]["ratio"], 6.0)
        balanced = self.cell("merge-puzzle@poki")["saturation"]
        self.assertEqual(balanced["status"], "balanced")
        no_supply = self.cell("lane-runner@crazygames")["saturation"]
        self.assertEqual(no_supply["status"], "unknown")

    def test_low_supply_without_demand_is_not_an_opportunity(self):
        sort = self.cell("sort-puzzle@poki")
        self.assertEqual(sort["demand"]["numerator"], 0)
        self.assertEqual(sort["saturation"]["status"], "insufficient-demand-evidence")
        self.assertTrue(any(g["kind"] == "insufficient-demand-evidence" and "sort-puzzle" in
                            g["description"] for g in self.report["gaps"]))
        for opportunity in self.report["opportunities"]:
            if opportunity["origin"] != "capability-screen":
                self.assertNotEqual(opportunity["cell"]["genre"]["value"], "sort-puzzle")

    def test_competition_names_titles_and_is_not_a_score(self):
        competition = self.cell("lane-runner@crazygames")["competition"]
        self.assertEqual((competition["numerator"], competition["denominator"]), (2, 3))

    def test_a_trend_needs_the_same_list_on_two_dates(self):
        trend = self.cell("match-3@poki")["trend"]
        self.assertEqual(trend["status"], "derived")
        self.assertIn("2026-09-01 vs 2026-09-20", trend["frame"])
        self.assertIn("earlier share 0.5", trend["frame"])
        self.assertEqual(self.report["market"]["trend"]["status"], "available")
        self.assertEqual(self.cell("lane-runner@crazygames")["trend"]["status"],
                         "insufficient-history")

    def test_editorial_lists_are_not_demand(self):
        shipped = outputs(scan(corpus=SHIPPED, platforms=None))["research-report"]
        editorial = [f for f in shipped["market"]["frames"] if f["list_kind"] == "editorial"]
        self.assertTrue(editorial)
        for cell in shipped["market"]["cells"]:
            for frame in editorial:
                self.assertNotIn(frame["list"], cell["demand"].get("frame", ""))

    def test_a_subgenre_list_never_shares_a_denominator_with_its_family(self):
        shipped = outputs(scan(corpus=SHIPPED, platforms=None))["research-report"]
        merge = next(c for c in shipped["market"]["cells"] if c["cell"] == "merge-puzzle@poki")
        self.assertNotIn("merge-puzzles-top", merge["demand"]["frame"])
        self.assertEqual(shipped["market"]["trend"]["status"], "insufficient-history")
        self.assertTrue(any(g["kind"] == "insufficient-history" for g in shipped["gaps"]))


# -- patterns ------------------------------------------------------------------------------


class Patterns(FixtureScan):
    def test_every_pattern_states_its_count_members_and_exceptions(self):
        self.assertGreater(len(self.report["patterns"]), 20)
        for pattern in self.report["patterns"]:
            claim = self.claims[pattern["claim"]]
            support = claim["support"]
            self.assertEqual(claim["tier"], "derived")
            self.assertIn("pattern", claim["tags"])
            self.assertEqual(support["numerator"], len(pattern["members"]))
            self.assertEqual(support["denominator"],
                             len(pattern["members"]) + len(pattern["exceptions"]))
            self.assertEqual(pattern["numerator"], support["numerator"])
            self.assertTrue(support["frame"])
            self.assertIn("not a cause", pattern["statement"])

    def test_a_pattern_counts_only_games_coded_on_the_question(self):
        swap = self.pattern("pat-genre-gameplay-puzzle-swap-match")
        self.assertEqual((swap["numerator"], swap["denominator"]), (3, 4))
        self.assertEqual(swap["exceptions"], ["game-fx-cozy-merge"])
        cute = self.pattern("pat-theme-tone-food-cute")
        self.assertEqual(cute["unknown"], [])
        tone = self.pattern("pat-genre-gameplay-match-3-swap-match")
        self.assertEqual(tone["denominator"], 3)
        art = [p for p in self.report["patterns"] if p["pair"] == "theme-tone"]
        self.assertTrue(art)

    def test_cross_dimensional_pairs_are_analysed(self):
        pairs = {p["pair"] for p in self.report["patterns"]}
        for pair in ("genre-gameplay", "theme-tone", "theme-art", "genre-audience",
                     "gameplay-session", "gameplay-retention", "gameplay-monetization",
                     "genre-monetization", "genre-platform", "genre-loop",
                     "genre-saturation"):
            self.assertIn(pair, pairs)
        daily = self.pattern("pat-gameplay-retention-lane-switch-daily-challenge")
        self.assertEqual((daily["numerator"], daily["denominator"]), (2, 2))

    def test_a_broader_genre_holding_the_same_games_is_not_restated(self):
        ids = {p["id"] for p in self.report["patterns"]}
        self.assertIn("pat-genre-gameplay-match-3-swap-match", ids)
        self.assertNotIn("pat-genre-gameplay-match-swap-match", ids)

    def test_benchmarks_summarise_measured_facets_with_their_games(self):
        bench = next(b for b in self.report["benchmarks"]
                     if b["genre"] == "match-3" and b["facet"] == "run_seconds")
        self.assertEqual((bench["median"], bench["min"], bench["max"], bench["n"]),
                         (210, 180, 240, 3))
        self.assertEqual(self.claims[bench["claim"]]["support"]["numerator"], 3)


# -- opportunities -------------------------------------------------------------------------


class Opportunities(FixtureScan):
    def test_the_scan_succeeds_and_both_artifacts_validate(self):
        self.assertEqual(self.result.outcome, StepOutcome.SUCCESS, self.result.error)
        self.assertEqual(CONTRACTS("research-report", self.report), [])
        self.assertEqual(CONTRACTS("opportunity", self.opportunity), [])
        self.assertEqual(self.report["research_version"], 2)

    def test_research_outputs_many_opportunities_from_several_generators(self):
        origins = {o["origin"] for o in self.report["opportunities"]}
        self.assertGreaterEqual(len(self.report["opportunities"]), 10)
        for origin in ("proven-core-new-axis", "supply-gap", "pattern-transfer",
                       "capability-screen"):
            self.assertIn(origin, origins)
        eligible = [o for o in self.report["opportunities"]
                    if o["status"] in ("eligible", "selected")]
        self.assertGreaterEqual(len(eligible), 3)
        self.assertEqual(sum(o["status"] == "selected" for o in self.report["opportunities"]), 1)

    def test_every_generated_opportunity_rests_on_an_observation(self):
        for o in self.report["opportunities"]:
            if o["origin"] == "capability-screen":
                continue
            self.assertTrue(o["basis"]["evidence_backed"], o["summary"])
            closure, stack = set(), list(o["basis"]["claim_refs"])
            while stack:
                cid = stack.pop()
                if cid not in closure:
                    closure.add(cid)
                    stack.extend(self.claims[cid]["parents"])
            self.assertTrue(any(self.claims[c]["tier"] == "observed" for c in closure))

    def test_a_thesis_is_a_hypothesis_and_never_an_observation(self):
        for o in self.report["opportunities"]:
            thesis = self.claims[o["basis"]["thesis"]]
            self.assertEqual(thesis["tier"], "hypothesis")
            self.assertLessEqual(thesis["confidence"], 0.6)
        for claim in self.claims.values():
            if claim["tier"] == "hypothesis":
                self.assertLessEqual(claim["confidence"], 0.6)
            if "effect" in claim["tags"]:
                self.assertEqual(claim["tier"], "hypothesis")

    def test_a_proven_core_changes_one_axis_to_one_absent_from_it(self):
        core = [o for o in self.report["opportunities"]
                if o["origin"] == "proven-core-new-axis"
                and o["cell"]["genre"]["value"] == "match-3"]
        self.assertTrue(core)
        for o in core:
            axis = o["changed_axis"]
            self.assertNotIn(axis["to"], axis["from"])
            absent = self.claims[axis["claim_refs"][0]]
            self.assertEqual(absent["support"]["numerator"], 0)
            self.assertEqual(absent["support"]["denominator"], 3)
            self.assertEqual(o["cell"][axis["facet"]]["value"], axis["to"])

    def test_an_unbuildable_opportunity_is_a_capability_gap_not_discarded(self):
        block = next(o for o in self.report["opportunities"]
                     if o["origin"] == "supply-gap"
                     and o["cell"]["genre"]["value"] == "block-puzzle")
        self.assertEqual(block["status"], "capability-gap")
        self.assertFalse(block["capability"]["buildable"])
        self.assertTrue(block["capability"]["missing"])
        self.assertTrue(block["basis"]["evidence_backed"])
        gaps = {g["opportunity_id"]: g for g in self.report["capability_gaps"]}
        self.assertIn(block["opportunity_id"], gaps)
        self.assertEqual(gaps[block["opportunity_id"]]["catalog_entry"], "block-puzzle")

    def test_nothing_unbuildable_or_excluded_is_ever_selected(self):
        selected = next(o for o in self.report["opportunities"] if o["status"] == "selected")
        self.assertTrue(selected["capability"]["buildable"])
        self.assertEqual(self.opportunity["id"], selected["opportunity_id"])
        self.assertEqual(self.report["selection"]["opportunity_id"], selected["opportunity_id"])

    def test_the_carried_opportunity_holds_the_research(self):
        research = self.opportunity["research"]
        self.assertEqual(research["status"], "selected")
        self.assertNotEqual(research["origin"], "capability-screen")
        # Ranked first among the buildable: corpus-generated, then evidence coverage.
        eligible = [o for o in self.report["opportunities"]
                    if o["status"] == "eligible" and o["origin"] != "capability-screen"]
        for other in eligible:
            self.assertGreaterEqual(research["confidence"]["evidence_coverage"],
                                    other["confidence"]["evidence_coverage"])
        self.assertEqual(self.opportunity["hypothesis"], research["basis"]["thesis"])
        for cid in self.opportunity["claim_refs"] + research["claim_refs"]:
            self.assertIn(cid, self.claims)
        self.assertTrue(set(research["basis"]["claim_refs"]) <= set(self.opportunity["claim_refs"]))
        self.assertTrue(research["competitors"])
        self.assertTrue(research["benchmarks"])
        self.assertTrue(research["confidence"]["fixture_evidence"])

    def test_the_audience_is_evidence_backed_or_unknown_never_assumed(self):
        audience = self.opportunity["research"]["audience"]
        self.assertEqual(audience["player_type"]["value"], "casual")
        self.assertEqual(audience["player_type"]["tier"], "derived")
        self.assertEqual(audience["age_band"]["tier"], "unknown")
        self.assertIsNone(audience["age_band"]["value"])
        self.assertEqual(audience["intent"]["tier"], "unknown")
        self.assertEqual(self.opportunity["audience"]["type"], "casual")
        shipped = outputs(scan(corpus=SHIPPED, platforms=None))["opportunity"]
        self.assertNotIn("type", shipped["audience"])
        self.assertEqual(shipped["research"]["audience"]["player_type"]["tier"], "unknown")

    def test_every_claim_reference_in_the_report_resolves(self):
        refs = set()

        def walk(value):
            if isinstance(value, dict):
                for key, item in value.items():
                    if key in ("claim_refs", "evidence_refs") and isinstance(item, list):
                        refs.update(item)
                    elif key in ("claim", "thesis", "effect_hypothesis") and \
                            isinstance(item, str) and item.startswith("claim-"):
                        refs.add(item)
                    else:
                        walk(item)
            elif isinstance(value, list):
                for item in value:
                    walk(item)
        for section in ("competitors", "market", "patterns", "benchmarks", "opportunities",
                        "capability_gaps", "platforms", "candidates"):
            walk(self.report[section])
        self.assertEqual(sorted(refs - set(self.claims)), [])

    def test_a_proposal_resting_on_no_observation_is_refused(self):
        space = types.SimpleNamespace()
        book = ClaimBook(AS_OF)
        guess = book.hypothesis("guess", "Sort puzzles might be under-served somewhere.", {})

        def fake(_space):
            return [dict(origin="supply-gap", node="sort-puzzle", platforms=["poki"],
                         basis=[guess], summary="FIXTURE: a guess with no observation.",
                         _sort=(0,))]
        vocabulary, config = Vocabulary(), AnalysisConfig()
        corpus = Corpus(vocabulary, config, book)
        space = opportunity_space.Space(corpus=corpus, cells={}, patterns=[], benchmarks=[],
                                        candidates=[], views={}, book=book,
                                        report_key="0000000000", scope=["poki"])
        with mock.patch.dict(opportunity_space.GENERATORS, {"supply-gap": fake}):
            blocks, refused = opportunity_space.generate(space)
        self.assertEqual(blocks, [])
        self.assertEqual(refused, ["FIXTURE: a guess with no observation."])

    def test_the_same_corpus_gives_byte_identical_artifacts(self):
        again = outputs(scan())
        self.assertEqual(content_hash(again["research-report"]),
                         content_hash(self.report))
        self.assertEqual(again["opportunity"], self.opportunity)


class Selection(unittest.TestCase):
    def test_a_step_can_carry_another_opportunity_from_the_space(self):
        first = outputs(scan())["research-report"]
        other = next(o for o in first["opportunities"]
                     if o["status"] == "eligible" and o["origin"] == "proven-core-new-axis")
        pinned = outputs(scan(select=other["opportunity_id"]))
        self.assertEqual(pinned["opportunity"]["id"], other["opportunity_id"])
        self.assertTrue(pinned["research-report"]["selection"]["rationale"].startswith(
            "Pinned by the step"))
        # The proposed axis is a hypothesis; design realises it as the title's intent.
        research = pinned["opportunity"]["research"]
        axis = research["changed_axis"]
        self.assertEqual(research["cell"][axis["facet"]]["tier"], "hypothesis")
        body = plan_strategy(pinned["opportunity"], load_profiles(), "fx-pinned", None,
                             load_vocabulary())
        self.assertEqual(body["research"]["changed_axis"], axis)

    def test_a_pin_survives_a_later_scan(self):
        first = outputs(scan())["research-report"]
        other = next(o for o in first["opportunities"] if o["status"] == "eligible")
        later = outputs(scan(as_of="2026-09-30T00:00:00Z", select=other["opportunity_id"]))
        self.assertNotEqual(later["research-report"]["id"], first["id"])
        self.assertEqual(later["opportunity"]["id"], other["opportunity_id"])

    def test_a_pin_never_overrides_waiting_for_evidence(self):
        scratch = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, scratch)
        os.makedirs(os.path.join(scratch, "snapshots"))
        result = scan(corpus=scratch, select="opp-00000000")
        self.assertEqual(result.outcome, StepOutcome.WAITING_FOR_INPUT)

    def test_pinning_an_unbuildable_or_unknown_opportunity_fails(self):
        first = outputs(scan())["research-report"]
        gap = next(o for o in first["opportunities"] if o["status"] == "capability-gap")
        for pin in (gap["opportunity_id"], "opp-doesnotexist"):
            result = scan(select=pin)
            self.assertEqual(result.outcome, StepOutcome.FAILED)
            self.assertFalse(result.retryable)

    def test_a_brief_still_ranks_first(self):
        report = outputs(scan(context=_with_idea("an endless runner with zombies")))
        self.assertIn("runner", report["opportunity"]["concept"]["subgenre"])

    def test_a_brief_sharing_one_incidental_word_waits(self):
        # "collect gems, beat the par time for stars" names no genre: it is not a runner.
        result = scan(context=_with_idea(
            "A 3D marble-roll game: tilt a marble across sky-island courses, ramps and "
            "bumpers; collect gems, beat the par time for stars"))
        self.assertEqual(result.outcome, StepOutcome.WAITING_FOR_INPUT, result.message)
        self.assertNotIn("opportunity", outputs(result))

    def test_a_brief_nothing_matches_waits_unless_the_nearest_is_asked_for(self):
        idea = _with_idea("goalkeeper penalty shootout")
        waiting = scan(context=idea)
        self.assertEqual(waiting.outcome, StepOutcome.WAITING_FOR_INPUT)
        self.assertNotIn("opportunity", outputs(waiting))
        nearest = scan(context=_with_idea("goalkeeper penalty shootout"),
                       idea_fallback="nearest")
        self.assertEqual(nearest.outcome, StepOutcome.SUCCESS)
        gaps = outputs(nearest)["research-report"]["gaps"]
        self.assertTrue(any(g["kind"] == "idea-unmatched" for g in gaps))

    def test_the_shipped_corpus_still_selects_the_same_shape(self):
        report = outputs(scan(corpus=SHIPPED, platforms=None))["research-report"]
        self.assertEqual(report["selection"]["candidate_id"], "match-3")
        origins = {o["origin"] for o in report["opportunities"]}
        self.assertIn("portal-difference", origins)
        portal = next(o for o in report["opportunities"] if o["origin"] == "portal-difference")
        self.assertEqual(portal["status"], "capability-gap")


def _with_idea(idea):
    context = fake_context()
    context.environment = {"idea": idea}
    return context


class Backlog(unittest.TestCase):
    def setUp(self):
        self.backlog = tempfile.mkdtemp(prefix="wgf-v2-backlog-")
        self.addCleanup(shutil.rmtree, self.backlog, ignore_errors=True)

    def test_an_opportunity_somebody_acted_on_is_not_proposed_again(self):
        first = outputs(scan(backlog=self.backlog))["research-report"]
        target = next(o for o in first["opportunities"]
                      if o["status"] == "eligible" and o["origin"] != "capability-screen")
        os.makedirs(os.path.join(self.backlog, target["opportunity_id"]))
        with open(os.path.join(self.backlog, target["opportunity_id"], "opportunity.json"),
                  "w", encoding="utf-8") as handle:
            json.dump({"id": target["opportunity_id"], "state": "rejected", "concept": {}},
                      handle)
        again = outputs(scan(backlog=self.backlog))["research-report"]
        block = next(o for o in again["opportunities"]
                     if o["opportunity_id"] == target["opportunity_id"])
        self.assertEqual(block["status"], "excluded")
        self.assertIn("rejected", block["exclusion_reason"])

    def test_nothing_is_written_unless_asked(self):
        scan(backlog=self.backlog)
        self.assertEqual(os.listdir(self.backlog), [])

    def test_every_proposed_opportunity_is_persisted_once(self):
        result = scan(backlog=self.backlog, persist_backlog=True)
        report = outputs(result)["research-report"]
        kept = {o["opportunity_id"] for o in report["opportunities"]
                if o["status"] in ("selected", "eligible", "capability-gap")}
        self.assertEqual(set(os.listdir(self.backlog)), kept)
        for oid in kept:
            with open(os.path.join(self.backlog, oid, "opportunity.json"),
                      encoding="utf-8") as handle:
                artifact = json.load(handle)
            self.assertEqual(CONTRACTS("opportunity", artifact), [], oid)
            self.assertEqual(artifact["state"], "discovered")
            self.assertIn(artifact["research"]["status"],
                          ("selected", "eligible", "capability-gap"))
        stamps = {oid: os.stat(os.path.join(self.backlog, oid, "opportunity.json")).st_mtime_ns
                  for oid in kept}
        again = scan(backlog=self.backlog, persist_backlog=True)
        self.assertEqual(again.outcome, StepOutcome.SUCCESS)
        self.assertEqual(outputs(again)["opportunity"]["id"],
                         outputs(result)["opportunity"]["id"])
        for oid, stamp in stamps.items():
            self.assertEqual(os.stat(os.path.join(self.backlog, oid,
                                                  "opportunity.json")).st_mtime_ns, stamp)
        # A later scan proposes the same opportunities under the same ids: no duplicates.
        later = scan(backlog=self.backlog, persist_backlog=True, as_of="2026-09-30T00:00:00Z")
        self.assertEqual(later.outcome, StepOutcome.SUCCESS)
        self.assertEqual(set(os.listdir(self.backlog)), kept)


# -- the handoff: research -> strategy -> design ------------------------------------------


class Handoff(unittest.TestCase):
    """The real engine, offline: research on the V2 fixture corpus, then `plan --run`."""

    @classmethod
    def setUpClass(cls):
        cls.project = tempfile.mkdtemp(prefix="wgf-v2-handoff-")
        cls.addClassCleanup(shutil.rmtree, cls.project, ignore_errors=True)
        os.makedirs(os.path.join(cls.project, "workspace", "config"))
        with open(os.path.join(cls.project, "workspace", "config", "factory.yaml"), "w",
                  encoding="utf-8") as handle:
            handle.write("factory:\n  checkpoints:\n    auto_approve: [G2, G3]\n"
                         f"  discovery:\n    corpus: {json.dumps(V2)}\n"
                         f"    as_of: \"{AS_OF}\"\n    platforms: [poki, crazygames]\n"
                         f"    backlog: {json.dumps(os.path.join(cls.project, 'none'))}\n")
        env = {k: v for k, v in os.environ.items() if not k.startswith("WGF_")}
        env["WGF_PROJECT_DIR"] = cls.project

        def wgf(*argv):
            return subprocess.run([sys.executable, ENGINE, *argv], cwd=cls.project, env=env,
                                  capture_output=True, text=True, timeout=600)
        research = wgf("research", "--json")
        assert research.returncode == 0, research.stderr[-2000:]
        cls.run_id = json.loads(research.stdout.splitlines()[0])["run_id"]
        cls.plan = wgf("plan", "--run", cls.run_id)
        cls.run_dir = os.path.join(cls.project, ".factory", "workflows", cls.run_id)

    def artifact(self, kind):
        directory = os.path.join(self.run_dir, "artifacts", kind)
        with open(os.path.join(directory, sorted(os.listdir(directory))[-1]),
                  encoding="utf-8") as handle:
            return json.load(handle)

    def test_the_run_reaches_the_tech_plan(self):
        self.assertEqual(self.plan.returncode, 0, self.plan.stdout[-2000:] + self.plan.stderr[-2000:])
        for kind in ("research-report", "opportunity", "title-strategy", "game-design",
                     "tech-plan"):
            self.assertEqual(CONTRACTS(kind, self.artifact(kind)), [], kind)

    def test_provenance_chains_from_design_back_to_the_report(self):
        report, opp = self.artifact("research-report"), self.artifact("opportunity")
        strategy, design = self.artifact("title-strategy"), self.artifact("game-design")
        self.assertEqual(opp["provenance"]["inputs"][0]["content_hash"],
                         report["provenance"]["content_hash"])
        self.assertEqual(strategy["provenance"]["inputs"][0]["content_hash"],
                         opp["provenance"]["content_hash"])
        self.assertEqual(design["provenance"]["inputs"][0]["content_hash"],
                         strategy["provenance"]["content_hash"])
        claims = {c["id"] for c in report["claims"]}
        for artifact in (strategy, design):
            self.assertEqual(artifact["research"]["report_id"], report["id"])
            self.assertEqual(artifact["research"]["opportunity_id"], opp["id"])
            self.assertEqual(set(artifact["research"]["claim_refs"]),
                             set(opp["research"]["claim_refs"]))
            self.assertTrue(set(artifact["research"]["claim_refs"]) <= claims)

    def test_theme_fantasy_art_and_gameplay_survive_strategy(self):
        opp, strategy = self.artifact("opportunity"), self.artifact("title-strategy")
        research, cell = strategy["research"], opp["research"]["cell"]
        self.assertEqual(research["theme"]["theme"], cell["theme"])
        self.assertEqual(research["fantasy"]["player"], cell["player_fantasy"])
        self.assertEqual(research["art"]["tone"], cell["art_tone"])
        self.assertEqual(research["gameplay"]["mechanics"], cell["mechanics"])
        self.assertEqual(research["competitors"], opp["research"]["competitors"])
        applied = {a["field"]: a for a in research["applied"]}
        self.assertEqual(applied["concept.control_scheme"]["source"], "research")
        self.assertEqual(strategy["concept"]["control_scheme"], "drag")
        self.assertEqual(applied["session.target_seconds"]["source"], "research")
        self.assertEqual(strategy["session"]["target_seconds"], 210)
        self.assertEqual(applied["audience.type"]["source"], "research")

    def test_design_derives_from_the_research_not_from_the_title_hash(self):
        strategy, design = self.artifact("title-strategy"), self.artifact("game-design")
        research = design["research"]
        applied = {a["field"]: a for a in research["applied"]}
        self.assertEqual(applied["archetype"]["source"], "research")
        self.assertEqual(applied["art_direction"]["source"], "research")
        self.assertEqual(applied["fantasy"]["source"], "research")
        self.assertEqual(applied["theme"]["source"], "research")
        self.assertIn(strategy["research"]["fantasy"]["statement"], design["fantasy"])
        theme = strategy["research"]["theme"]["theme"]["label"].split(" (")[0]
        self.assertIn(theme, design["art_direction"])
        kit = design["build_spec"]["visual_identity"]
        tone = strategy["research"]["art"]["tone"]["value"]
        kit_id = next(k for k, v in identity.KITS.items() if v["concept"] == kit["concept"])
        self.assertIn(tone, identity.TRAITS[kit_id]["tone"])
        self.assertEqual(research["theme"], strategy["research"]["theme"])


def design_from(opportunity, title_id="fx-title", params=None):
    """plan_strategy then the design step, offline, on one opportunity."""
    body = plan_strategy(opportunity, load_profiles(), title_id, None, load_vocabulary())
    strategy = dict(body, provenance={"artifact_id": f"wgf:title-strategy:{title_id}:1",
                                      "artifact_type": "title-strategy",
                                      "schema_version": "1.3.0", "inputs": [],
                                      "produced_by": {"role": "game-designer",
                                                      "actor": "automation"},
                                      "produced_at": AS_OF, "status": "draft"})

    class Inputs:
        missing = []
        refs = {"title-strategy": types.SimpleNamespace(schema_version="1.3.0",
                                                        content_hash=None)}

        def __contains__(self, kind):
            return kind == "title-strategy"

        def load(self, kind):
            return copy.deepcopy(strategy)
    step = DesignStep(types.SimpleNamespace(id="design", type="design", params=params or {},
                                            inputs=["title-strategy"],
                                            outputs=["game-design"]))
    context = types.SimpleNamespace(config={}, project_id=title_id, execution=1,
                                    logger=FakeLogger())
    return body, step.execute(Inputs(), context)


class ProposedAxis(unittest.TestCase):
    def test_design_realises_a_proposed_theme_and_says_it_is_a_proposal(self):
        first = outputs(scan())["research-report"]
        themed = next(o for o in first["opportunities"]
                      if o["status"] == "eligible" and o["origin"] == "proven-core-new-axis"
                      and o["changed_axis"]["facet"] == "theme"
                      and o["cell"]["genre"]["value"] == "match-3")
        opportunity = outputs(scan(select=themed["opportunity_id"]))["opportunity"]
        strategy, result = design_from(opportunity)
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
        design = result.artifacts[0].content
        self.assertEqual(CONTRACTS("game-design", design), [])
        applied = {a["field"]: a for a in design["research"]["applied"]}
        self.assertIn("proposed theme", applied["theme"]["detail"])
        label = themed["cell"]["theme"]["label"]
        self.assertIn(label, design["art_direction"])
        device = {a["field"]: a for a in strategy["research"]["applied"]}["audience.device"]
        self.assertIn(device["source"], ("research", "default"))


class DesignFallbacks(unittest.TestCase):
    def test_without_research_art_the_digest_decides_and_says_so(self):
        kit, basis, matched = identity.pick("demo", ["paper-diorama", "riso-arcade"])
        self.assertEqual((basis, matched), ("title-digest", []))
        kit2, basis2, matched2 = identity.pick("demo", ["paper-diorama", "riso-arcade"],
                                               art={"tone": "dark", "palette": "dark-glow"})
        self.assertEqual(basis2, "research")
        self.assertIn("tone=dark", matched2)
        # The title id never overrides what research supports.
        for title in ("a", "b", "c", "d", "e"):
            chosen = identity.pick(title, ["paper-diorama"], art={"tone": "neon"})[0]
            self.assertIn("neon", identity.TRAITS[chosen]["tone"])

    def test_a_pre_v2_opportunity_plans_and_designs_as_before(self):
        with open(os.path.join(paths.OPPORTUNITIES, "opp-001", "opportunity.json"),
                  encoding="utf-8") as handle:
            opp = json.load(handle)
        body = plan_strategy(opp, load_profiles(), "neon-drift", None, load_vocabulary())
        self.assertNotIn("research", body)

    def test_an_author_that_drops_the_research_cannot_lose_it(self):
        report = outputs(scan())
        body = plan_strategy(report["opportunity"], load_profiles(), "fx-title", None,
                             load_vocabulary())
        strategy = dict(body, provenance={"artifact_id": "wgf:title-strategy:fx-title:1",
                                          "artifact_type": "title-strategy",
                                          "schema_version": "1.3.0", "inputs": [],
                                          "produced_by": {"role": "game-designer",
                                                          "actor": "automation"},
                                          "produced_at": AS_OF, "status": "draft"})
        from wgf_design import authors

        class Forgetful(authors.ArchetypeAuthor):
            name = "forgetful"

            def draft(self, brief):
                out = super().draft(brief)
                out.pop("research", None)
                return out
        authors.register_author("forgetful", Forgetful)
        self.addCleanup(authors.AUTHORS.pop, "forgetful", None)

        class Inputs:
            missing = []
            refs = {"title-strategy": types.SimpleNamespace(schema_version="1.3.0",
                                                            content_hash=None)}

            def __contains__(self, kind):
                return kind == "title-strategy"

            def load(self, kind):
                return copy.deepcopy(strategy)
        step = DesignStep(types.SimpleNamespace(id="design", type="design",
                                                params={"author": "forgetful"},
                                                inputs=["title-strategy"],
                                                outputs=["game-design"]))
        context = types.SimpleNamespace(config={}, project_id="fx-title", execution=1,
                                        logger=FakeLogger())
        result = step.execute(Inputs(), context)
        design = result.artifacts[0].content
        self.assertEqual(design["research"]["claim_refs"], body["research"]["claim_refs"])
        self.assertEqual(design["research"]["applied"][0]["source"], "default")


# -- the collection procedure and the shipped corpus --------------------------------------


class CorpusTool(unittest.TestCase):
    CLI = os.path.join(SCRIPTS, "wgf-corpus.py")

    def run_cli(self, *argv):
        return subprocess.run([sys.executable, self.CLI, *argv], capture_output=True,
                              text=True, timeout=120)

    def test_validate_reads_a_corpus_the_way_the_step_does(self):
        ok = self.run_cli("validate", V2, "--json")
        self.assertEqual(ok.returncode, 0, ok.stderr)
        summary = json.loads(ok.stdout)
        self.assertEqual(summary["records"], 6)
        self.assertEqual(len(summary["fixture_records"]), 6)
        self.assertEqual(summary["coded"]["theme"], 6)
        scratch = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, scratch)
        os.makedirs(os.path.join(scratch, "games"))
        with open(os.path.join(V2, "games", "game-fx-city-run.json"), encoding="utf-8") as handle:
            record = json.load(handle)
        record["observations"][0]["value"] = "not-a-genre"
        with open(os.path.join(scratch, "games", "game-fx-city-run.json"), "w") as handle:
            json.dump(record, handle)
        bad = self.run_cli("validate", scratch)
        self.assertEqual(bad.returncode, 1)
        self.assertIn("not-a-genre", bad.stdout)

    def test_a_template_is_not_evidence_until_someone_fills_it_in(self):
        out = self.run_cli("template", "game-new-one", "--name", "New One",
                           "--platform", "poki")
        self.assertEqual(out.returncode, 0, out.stderr)
        record = json.loads(out.stdout)
        self.assertEqual(record["observations"], [])
        scratch = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, scratch)
        os.makedirs(os.path.join(scratch, "games"))
        with open(os.path.join(scratch, "games", "game-new-one.json"), "w") as handle:
            json.dump(record, handle)
        with self.assertRaises(EvidenceError):           # placeholder timestamp
            load_records(os.path.join(scratch, "games"))

    def test_facets_lists_the_codes(self):
        out = self.run_cli("facets", "art_tone")
        self.assertEqual(out.returncode, 0)
        self.assertIn("cute", out.stdout)
        self.assertEqual(self.run_cli("facets", "nope").returncode, 2)


class ShippedCorpus(unittest.TestCase):
    def test_no_fixture_data_is_shipped_as_evidence(self):
        games = os.path.join(SHIPPED, "games")
        for _name, record, _digest in load_records(games):
            self.assertFalse(record.get("fixture"), record["id"])
            for session in record["sessions"]:
                self.assertNotIn("fixtures.invalid", session["source_uri"])
        for name in os.listdir(os.path.join(SHIPPED, "snapshots")):
            with open(os.path.join(SHIPPED, "snapshots", name), encoding="utf-8") as handle:
                text = handle.read()
            self.assertNotIn("fixtures.invalid", text, name)
            self.assertNotIn("FIXTURE", text, name)

    def test_a_listing_only_corpus_says_how_little_it_knows(self):
        report = outputs(scan(corpus=SHIPPED, platforms=None))["research-report"]
        self.assertEqual(report["corpus"]["teardown_games"], 0)
        self.assertTrue(any(g["kind"] == "uncoded-facet" for g in report["gaps"]))
        carried = next(o for o in report["opportunities"] if o["status"] == "selected")
        for facet in ("theme", "player_fantasy", "art_tone"):
            self.assertEqual(carried["cell"][facet]["tier"], "unknown", facet)


# -- the worked example's evidence, corrected -------------------------------------------------


class Corrections(unittest.TestCase):
    def claim(self, cid):
        with open(os.path.join(ROOT, "workspace", "claims", f"{cid}.json"),
                  encoding="utf-8") as handle:
            return json.load(handle)

    def evaluation(self, eid):
        with open(os.path.join(paths.OPPORTUNITIES, "opp-001", "evaluations", f"{eid}.json"),
                  encoding="utf-8") as handle:
            return json.load(handle)

    def test_invalid_claims_are_superseded_not_rewritten(self):
        old = self.claim("claim-0a01")
        self.assertEqual(old["superseded_by"], "claim-0a05")
        self.assertEqual(old["tier"], "observed")              # history kept as it was
        self.assertTrue(old["statement"].startswith("Of the top 20 titles"))
        new = self.claim("claim-0a05")
        self.assertEqual(new["tier"], "hypothesis")
        self.assertLessEqual(new["confidence"], 0.6)
        self.assertIn("invalidated", new["tags"])
        self.assertIn(old["statement"], new["statement"])
        self.assertEqual(self.claim("claim-0a03")["superseded_by"], "claim-0a06")
        self.assertEqual(self.claim("claim-0a06")["parents"], ["claim-0a05"])
        validator = claim_validator()
        for cid in ("claim-0a01", "claim-0a03", "claim-0a05", "claim-0a06"):
            self.assertEqual(list(validator.iter_errors(self.claim(cid))), [], cid)

    def test_the_invalid_evaluation_is_superseded_and_cites_no_superseded_claim(self):
        old, new = self.evaluation("eval-0b01"), self.evaluation("eval-0b02")
        self.assertEqual(old["provenance"]["content_hash"], content_hash(old))
        self.assertEqual(new["supersedes_evaluation_id"], "eval-0b01")
        self.assertEqual(CONTRACTS("evaluation", new), [])
        superseded = {"claim-0a01", "claim-0a03"}
        for dimension in new["dimensions"]:
            self.assertFalse(superseded & set(dimension["evidence_refs"]), dimension["id"])
            if not dimension["evidence_refs"]:
                self.assertEqual(dimension["tier"], "hypothesis", dimension["id"])
        weights = sum(d["weight"] for d in new["dimensions"])
        self.assertAlmostEqual(new["aggregate"], round(sum(
            d["weight"] * d["normalized"] for d in new["dimensions"]) / weights, 3))
        self.assertLess(new["evidence_coverage"], 0.6)


if __name__ == "__main__":
    unittest.main()

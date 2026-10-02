"""The design module (scripts/wgf_design): title-strategy in, game-design out.

Covers what docs/workflow-module-contract.md §11 asks of every module - unit, contract
through the real engine, schema (ajv, when it is cached locally), every failure path the step
can produce, and idempotency - plus what is specific to design: platform profiles read as
binding, scope tiers derived from features, the MVP buildable without guessing, and the
consistency rules as the exit guard.

Deterministic and offline. Run from the repository root:

    python -m unittest discover scripts/tests
"""

import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
sys.path.insert(0, SCRIPTS)

from wgflib.hashing import content_hash  # noqa: E402
from wgflib.workflow.api import RunRequest, WorkflowAPI  # noqa: E402
from wgflib.workflow.config import FactoryConfig  # noqa: E402
from wgflib.workflow.contracts import ArtifactContracts  # noqa: E402
from wgflib.workflow.model import ArtifactRef, RunStatus, StepOutcome, StepStatus  # noqa: E402
from wgf_design import archetypes, authors, compose, consistency, content, identity  # noqa: E402
from wgf_design.platforms import load_platforms  # noqa: E402
from wgf_design.step import SCHEMA_VERSION, DesignStep  # noqa: E402

STRATEGY_PATH = os.path.join(ROOT, "workspace", "titles", "neon-drift", "title-strategy.json")
NOW = "2026-09-23T10:00:00Z"


def load_strategy():
    with open(STRATEGY_PATH, encoding="utf-8") as handle:
        return json.load(handle)


def rehash(artifact):
    artifact["provenance"]["content_hash"] = ""
    artifact["provenance"]["content_hash"] = content_hash(artifact)
    return artifact


class FakeInputs:
    """`extra` is the other artifacts a visit has - the `prototype-report` a `design-gap`
    route brings back, keyed by type."""

    def __init__(self, strategy, schema_version="1.0.0", extra=None):
        self.strategy = strategy
        self.extra = dict(extra or {})
        self.missing = [] if strategy is not None else ["title-strategy"]
        self.refs = {} if strategy is None else {"title-strategy": ArtifactRef(
            id="title-strategy", type="title-strategy", version=1, location="mem", checksum="-",
            content_hash=strategy["provenance"]["content_hash"], schema_version=schema_version)}
        for artifact_type in self.extra:
            self.refs[artifact_type] = ArtifactRef(
                id=artifact_type, type=artifact_type, version=1, location="mem", checksum="-")

    def __contains__(self, artifact_type):
        return artifact_type in self.refs

    def load(self, artifact_type):
        if artifact_type in self.extra:
            return copy.deepcopy(self.extra[artifact_type])
        return copy.deepcopy(self.strategy)


class FakeLogger:
    def __init__(self):
        self.records = []

    def __getattr__(self, level):
        return lambda message, **fields: self.records.append((level, message, fields))


class FakeContext:
    def __init__(self, config=None, execution=1, run_dir=None, previous_outputs=None,
                 visit=1):
        self.config = config or {}
        self.project_id = "demo"
        self.execution = execution
        self.logger = FakeLogger()
        self.run_dir = run_dir
        self.visit, self.attempt = visit, 1
        # What this step produced on an earlier visit (wgflib.workflow.model.ArtifactRef),
        # which is where DesignStep._previous_design reads the design to repair.
        self.previous_outputs = list(previous_outputs or [])


class FakeDefinition:
    def __init__(self, params=None):
        self.id = "design"
        self.type = "design"
        self.params = params or {}
        self.inputs = ["title-strategy"]
        self.outputs = ["game-design"]


class FixedClockStep(DesignStep):
    clock = staticmethod(lambda: NOW)


def run_step(strategy, params=None, config=None, schema_version="1.0.0", step_class=FixedClockStep,
             inputs=None, context=None):
    step = step_class(FakeDefinition(params))
    return step.execute(inputs or FakeInputs(strategy, schema_version),
                        context or FakeContext(config))


def variant(**changes):
    strategy = load_strategy()
    for key, value in changes.items():
        strategy[key] = value
    return rehash(strategy)


class DesignFromWorkedExample(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = run_step(load_strategy())
        cls.design = cls.result.artifacts[0].content

    def test_succeeds_with_one_game_design(self):
        self.assertEqual(self.result.outcome, StepOutcome.SUCCESS, self.result.error)
        self.assertEqual([a.type for a in self.result.artifacts], ["game-design"])

    def test_passes_the_engine_structural_contract(self):
        self.assertEqual(ArtifactContracts()("game-design", self.design), [])

    def test_provenance_pins_the_strategy_and_reproduces(self):
        provenance = self.design["provenance"]
        self.assertEqual(provenance["schema_version"], SCHEMA_VERSION)
        self.assertEqual(provenance["artifact_id"], "wgf:game-design:neon-drift:20260923-01")
        self.assertEqual(provenance["produced_by"], {"role": "game-designer", "actor": "automation"})
        self.assertEqual(provenance["inputs"], [{
            "artifact_id": "wgf:title-strategy:neon-drift:20260901-01",
            "artifact_type": "title-strategy",
            "content_hash": load_strategy()["provenance"]["content_hash"]}])
        self.assertEqual(provenance["content_hash"], content_hash(self.design))

    def test_engine_is_recorded_with_a_rationale(self):
        engine = self.design["engine"]
        self.assertEqual((engine["type"], engine["dimension"]), ("pixijs", "2d"))
        self.assertTrue(engine["rationale"].strip())

    def test_scope_tiers_are_derived_from_features(self):
        tiers = self.design["scope"]["tiers"]
        by_tier = {t: [f["name"] for f in self.design["features"] if f["tier"] == t]
                   for t in ("mvp", "post-mvp", "optional")}
        self.assertEqual(tiers["mvp"], by_tier["mvp"])
        self.assertEqual(tiers["prototype"], by_tier["mvp"])
        self.assertEqual(tiers["production"], by_tier["post-mvp"])
        self.assertEqual(tiers["future"], by_tier["optional"])
        self.assertTrue(by_tier["mvp"] and by_tier["post-mvp"] and by_tier["optional"])

    def test_every_mvp_feature_has_acceptance_criteria(self):
        for feature in self.design["features"]:
            if feature["tier"] == "mvp":
                self.assertTrue(feature.get("acceptance"), feature["id"])

    def test_every_strategy_mvp_item_is_carried(self):
        text = json.dumps(self.design["features"])
        for item in load_strategy()["mvp"]:
            self.assertIn(item, text)

    def test_strategy_exclusions_are_honoured(self):
        out = [o["item"] for o in self.design["scope"]["tiers"]["out_of_scope"]]
        self.assertIn("Level editor", out)
        names = " ".join(f["name"].lower() for f in self.design["features"])
        self.assertNotIn("skin", names)       # "Character or skin customization"
        self.assertNotIn("daily", names)      # "Any metagame or daily-quest layer"
        self.assertNotIn("daily_quest", self.design["retention"]["hooks"])
        actions = self.design["build_spec"]["controls"]["actions"]
        # "Desktop-specific control scheme" is out of scope, so nothing is bound to keys.
        self.assertTrue(all(a["keyboard"].startswith("Not bound") for a in actions))

    def test_mvp_is_buildable(self):
        self.assertEqual(compose.buildability(self.design), [])

    def test_monetization_is_what_the_strategy_approved(self):
        kinds = [p["kind"] for p in self.design["monetization"]["placements"]]
        self.assertEqual(kinds, ["rewarded", "interstitial"])
        touchpoints = {t["kind"]: t for t in self.design["build_spec"]["monetization_touchpoints"]}
        self.assertEqual(touchpoints["rewarded"]["tier"], "mvp")
        # One build for Yandex (60 s) and CrazyGames (180 s): the tighter interval wins.
        self.assertEqual(touchpoints["interstitial"]["cooldown_s"], 180)
        self.assertEqual(self.design["build_spec"]["failure"]["continue_offer"], "rewarded-continue")

    def test_platform_profiles_were_read(self):
        applied = self.design["platform_constraints_applied"]
        self.assertEqual({c["platform_id"] for c in applied}, {"yandex", "crazygames"})
        self.assertFalse([c for c in applied if c["how_addressed"].startswith("NOT addressed")])
        self.assertEqual(self.design["scope"]["locales"], ["ru", "en"])
        capabilities = {t["capability"] for t in self.design["build_spec"]["sdk_touchpoints"]}
        for needed in ("init", "loading-progress", "loading-complete", "gameplay-start", "gameplay-stop",
                       "pause-audio", "resume-audio", "ad-rewarded", "ad-interstitial", "cloud-save"):
            self.assertIn(needed, capabilities)

    def test_kill_criteria_metrics_are_instrumented(self):
        telemetry = next(f for f in self.design["features"] if f["id"] == "telemetry")
        text = " ".join(telemetry["acceptance"])
        for criterion in load_strategy()["kill_criteria"]:
            self.assertIn(criterion["when"]["left"], text)

    def test_consistency_passes_and_warnings_are_left_for_g3(self):
        block = self.design["consistency"]
        self.assertEqual(block["status"], "pass")
        self.assertEqual(block["ruleset_version"], consistency.load_rules()["version"])
        # One result per consistency rule, and - the design names a genre family - one per
        # content rule beside them (content.py, core/reference/genre-models.yaml).
        self.assertEqual(len(block["rule_results"]),
                         len(consistency.load_rules()["rules"]) + len(content.RULES))
        self.assertEqual(block["content_model"],
                         {"id": self.design["genre"]["family"],
                          "version": str(content.load_models()["version"])})
        self.assertIs(block["warnings_acknowledged"], False)

    def test_visual_identity_is_deliberate(self):
        look = self.design["build_spec"]["visual_identity"]
        # A kit's display face, or - ru is in scope here - the alternate that sets Cyrillic.
        faces = {k["typography"]["display"].split(" (")[0] for k in identity.KITS.values()}
        self.assertIn(look["typography"]["display"].split(" (")[0],
                      faces | set(identity.ALTERNATES.values()))
        self.assertTrue(any("Inter" in a for a in look["avoid"]))

    def test_prototype_questions_are_open_questions(self):
        for question in load_strategy()["prototype_must_prove"]:
            self.assertIn(question, self.design["open_questions"])


def coherent(archetype_id, **changes):
    """The worked-example strategy restated so its concept IS the archetype's game: the concept
    names the archetype's loop and its MVP mechanics, as a strategy for that game would."""
    a = archetypes.ARCHETYPES[archetype_id]
    mechanics = " ".join(m["description"] for m in a["mechanics"] if m["tier"] == "mvp")
    concept = {"genre": "arcade", "core_mechanic": mechanics, "core_loop": a["core_loop"]}
    return variant(one_liner=f"A {a['label'].lower()} game: {a['core_loop']}", concept=concept, **changes)


class Choices(unittest.TestCase):
    def test_a_3d_strategy_gets_threejs(self):
        strategy = variant(one_liner="A 3D drift racing arena where you steer through lit gates against the clock.",
                           concept={"genre": "racing", "core_mechanic": "steer a craft through lit gates; each gate adds time to the clock",
                                    "core_loop": "steer to the lit gate, pass it for time, the course tightens, the clock runs out, retry"})
        result = run_step(strategy)
        design = result.artifacts[0].content
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
        self.assertEqual((design["engine"]["type"], design["engine"]["dimension"]), ("threejs", "3d"))
        self.assertEqual(design["build_spec"]["responsive"]["orientation"], "landscape")
        self.assertIn("model", {a["type"] for a in design["build_spec"]["assets"]})

    def test_the_step_can_pin_archetype_engine_and_identity(self):
        result = run_step(coherent("merge-puzzle"), params={"archetype": "merge-puzzle", "identity": "lacquer-brass"})
        design = result.artifacts[0].content
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
        self.assertIn("level-complete", {s["id"] for s in design["build_spec"]["game_states"]})
        self.assertEqual(design["build_spec"]["visual_identity"]["palette"][0]["token"], "lacquer")
        pinned = run_step(load_strategy(), params={"engine": "threejs"}).artifacts[0].content
        self.assertEqual(pinned["engine"]["type"], "threejs")

    def test_a_pinned_archetype_that_is_not_the_strategys_game_is_refused(self):
        # Regression: a pin (or a keyword match) is not allowed to turn the approved game into
        # another. The worked example is a lane-switching runner; a swap-to-match grid is not it.
        result = run_step(load_strategy(), params={"archetype": "merge-puzzle"})
        self.assertEqual(result.outcome, StepOutcome.FAILED)
        self.assertIn("concept_mechanics_carried", result.error)
        self.assertIn("design_adds_no_foreign_mechanic", result.error)

    def test_every_archetype_yields_a_buildable_passing_design(self):
        for archetype_id in archetypes.ARCHETYPES:
            with self.subTest(archetype=archetype_id):
                result = run_step(coherent(archetype_id), params={"archetype": archetype_id})
                self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
                self.assertEqual(compose.buildability(result.artifacts[0].content), [])

    def test_each_archetype_is_selected_for_its_own_game(self):
        for archetype_id in archetypes.ARCHETYPES:
            with self.subTest(archetype=archetype_id):
                self.assertEqual(archetypes.select(coherent(archetype_id))[0], archetype_id)

    def test_archetype_selection_follows_the_strategy_words(self):
        self.assertEqual(archetypes.select(load_strategy())[0], "lane-runner")
        self.assertEqual(archetypes.select({"one_liner": "Merge tiles on a grid"})[0], "merge-puzzle")
        self.assertEqual(archetypes.select({"one_liner": "Something new"})[0], archetypes.FALLBACK)

    def test_a_drop_merge_concept_gets_a_drop_merge_design_not_a_swap_puzzle(self):
        # Regression for the 2026-09-26 live run: a "merge" genre word picked the swap-and-match
        # grid for a drop-into-a-column strategy, and the design passed its own checks.
        strategy = variant(
            one_liner="A merge game where the player drops numbered pieces onto a seven-column track.",
            concept={"genre": "puzzle", "subgenre": "merge",
                     "core_mechanic": "drop numbered tower pieces onto a seven-column track; equal neighbours merge into the next level and the merge cascades",
                     "core_loop": "pick a column, drop the piece, chain merges for points, the next piece ramps up, the board fills, retry for a higher score"})
        self.assertEqual(archetypes.select(strategy)[0], "drop-merge")
        result = run_step(strategy)
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
        design = result.artifacts[0].content
        breached = [r["criterion_id"] for r in design["consistency"]["rule_results"] if r["breached"]]
        self.assertEqual(breached, [])
        names = {f["name"] for f in design["features"] if f["tier"] == "mvp"}
        self.assertTrue({"Seven-column track", "Drop a piece", "Merge and cascade"} <= names, names)
        self.assertNotIn("swap", " ".join(a["action"].lower() for a in design["build_spec"]["controls"]["actions"]))

    def test_a_wall_dodging_concept_gets_a_dodge_design_not_a_gate_clock(self):
        strategy = variant(
            one_liner="A driving game where the player steers a neon craft between walls that rush toward it.",
            concept={"genre": "arcade", "subgenre": "driving",
                     "core_mechanic": "drive a neon craft down a 3d arena and steer between walls that rush toward it",
                     "core_loop": "drive into the arena, steer between the walls, score climbs with every wall cleared, the arena speeds up, crash, drive again"})
        self.assertEqual(archetypes.select(strategy)[0], "arena-dodge")
        result = run_step(strategy)
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
        design = result.artifacts[0].content
        self.assertEqual(design["engine"]["type"], "threejs")
        self.assertNotIn("clock", design["core_loop"].lower())


class StrategyMvpFolding(unittest.TestCase):
    def test_a_one_word_mvp_item_a_feature_covers_is_folded_not_duplicated(self):
        # Regression: "Localization: en, ru" shares one significant word with the Localization
        # feature and became a second Localization feature - and a second plan task.
        strategy = coherent("drop-merge", mvp=["Localization: en, ru"])
        design = run_step(strategy, params={"archetype": "drop-merge"}).artifacts[0].content
        names = [f["name"] for f in design["features"]]
        self.assertEqual([n for n in names if n.startswith("Localization")], ["Localization"])
        localization = next(f for f in design["features"] if f["name"] == "Localization")
        self.assertIn("Strategy MVP: Localization: en, ru.", localization["acceptance"])


class ConceptFidelity(unittest.TestCase):
    """design-consistency-rules concept_mechanics_carried / design_adds_no_foreign_mechanic."""

    TERMS = consistency.load_rules()["concept_terms"]

    def view(self, design, strategy):
        return consistency.concept_view(design, strategy, self.TERMS)

    def test_a_mechanic_the_strategy_names_must_be_in_the_designs_own_text(self):
        strategy = {"one_liner": "drop pieces into a column"}
        design = {"core_loop": "swap two pieces", "features": [
            {"id": "strategy-drop", "tier": "mvp", "name": "drop pieces into a column", "description": "x"},
            {"id": "swap", "tier": "mvp", "name": "Swap", "description": "swap two",
             "acceptance": ["Strategy MVP: drop pieces into a column."]}]}
        view = self.view(design, strategy)
        # Folded-in strategy text is not the design carrying the mechanic.
        self.assertEqual(view["uncarried"], ["column", "drop"])
        self.assertEqual(view["foreign"], ["swap"])

    def test_a_faithful_design_carries_everything_and_adds_nothing(self):
        strategy = {"one_liner": "drop pieces into a column; equal neighbours merge"}
        design = {"core_loop": "drop into a column, neighbours merge", "features": [],
                  "build_spec": {"controls": {"actions": [{"tier": "mvp", "action": "Drop", "touch": "Tap a column"}]}}}
        view = self.view(design, strategy)
        self.assertEqual((view["uncarried"], view["foreign"]), ([], []))

    def test_words_are_matched_whole(self):
        # "gateway" is not a gate; "seven-column" is a column.
        found = consistency._terms_in("a gateway to a seven-column track", self.TERMS)
        self.assertEqual(found, {"column"})


    def test_identity_is_stable_per_title(self):
        first = identity.choose("neon-drift", ["neon-night", "riso-arcade"])[0]
        self.assertEqual(first, identity.choose("neon-drift", ["neon-night", "riso-arcade"])[0])

    def test_a_placement_a_required_platform_lacks_is_cut_not_designed(self):
        strategy = variant(platform_set=[{"id": "gamevui", "profile_version": "1.0.0", "role": "required"}])
        result = run_step(strategy)
        design = result.artifacts[0].content
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
        self.assertEqual([p["kind"] for p in design["monetization"]["placements"]], ["interstitial"])
        self.assertIn("rewarded placement", [o["item"] for o in design["scope"]["tiers"]["out_of_scope"]])
        self.assertNotIn("continue_offer", design["build_spec"]["failure"])
        self.assertIn("vi", design["scope"]["locales"])


class FailurePaths(unittest.TestCase):
    def test_no_strategy_waits_for_input(self):
        self.assertEqual(run_step(None).outcome, StepOutcome.WAITING_FOR_INPUT)

    def test_an_unreadable_strategy_major_fails_for_good(self):
        result = run_step(load_strategy(), schema_version="2.0.0")
        self.assertEqual((result.outcome, result.retryable), (StepOutcome.FAILED, False))

    def test_a_moved_platform_profile_blocks(self):
        strategy = load_strategy()
        strategy["platform_set"][0]["profile_version"] = "9.9.9"
        result = run_step(rehash(strategy))
        self.assertEqual(result.outcome, StepOutcome.BLOCKED)
        self.assertIn("yandex@9.9.9", result.message or result.error)

    def test_an_unknown_author_or_archetype_fails_for_good(self):
        for params, config in (({"author": "nobody"}, None), ({}, {"design": {"author": "nobody"}}),
                               ({"archetype": "nope"}, None), ({"engine": "unity"}, None)):
            with self.subTest(params=params, config=config):
                result = run_step(load_strategy(), params=params, config=config)
                self.assertEqual((result.outcome, result.retryable), (StepOutcome.FAILED, False))
                self.assertEqual(result.artifacts, [])

    def test_an_unbuildable_draft_fails_and_persists_nothing(self):
        class DanglingAuthor(authors.ArchetypeAuthor):
            def draft(self, brief):
                draft = super().draft(brief)
                draft["build_spec"]["screens"][0]["state"] = "nowhere"
                draft["build_spec"]["game_states"][0]["exits"][0]["to"] = "limbo"
                return draft

        authors.register_author("dangling", DanglingAuthor)
        self.addCleanup(authors.AUTHORS.pop, "dangling", None)
        result = run_step(load_strategy(), params={"author": "dangling"})
        self.assertEqual((result.outcome, result.retryable), (StepOutcome.FAILED, False))
        self.assertIn("not buildable", result.error)
        self.assertIn("limbo", result.error)
        self.assertEqual(result.artifacts, [])

    def test_a_blocking_rule_routes_descope_with_the_design_as_evidence(self):
        # 40-second sessions against Yandex's 60-second interstitial interval.
        strategy = variant(session={"target_seconds": 40, "first_session_seconds": 40})
        result = run_step(strategy)
        self.assertEqual((result.outcome, result.route, result.retryable),
                         (StepOutcome.FAILED, "descope", False))
        design = result.artifacts[0].content
        self.assertEqual(design["consistency"]["status"], "fail")
        breached = [r["criterion_id"] for r in design["consistency"]["rule_results"] if r["breached"]]
        self.assertIn("interstitial_interval_fits_session", breached)
        self.assertEqual(ArtifactContracts()("game-design", design), [])

    def test_every_repairable_problem_is_collected_in_one_round(self):
        # The experience, presentation, depth and content checks all run on every draft, and
        # every problem goes into one repair request: an author that repairs is not asked once
        # per check per round, which spent the rounds before the content check was reached.
        class Collecting(authors.ArchetypeAuthor):
            repairs = True
            rounds = []

            def draft(self, brief):
                Collecting.rounds.append(list((brief.get("repair") or {}).get("problems") or []))
                draft = super().draft(brief)
                if not brief.get("repair"):
                    # Two classes of problem at once: the onboarding teaches nothing, and the
                    # content's objectives all read the same.
                    draft["build_spec"]["experience"]["onboarding"]["teaches"] = []
                    for unit in draft["build_spec"]["content"]["units"]:
                        unit["objective"] = "Survive the segment as it comes"
                return draft

        Collecting.rounds = []
        authors.register_author("collecting", Collecting)
        self.addCleanup(authors.AUTHORS.pop, "collecting", None)
        result = run_step(load_strategy(), params={"author": "collecting"})
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
        self.assertEqual(len(Collecting.rounds), 2)
        first = " ".join(Collecting.rounds[1])
        self.assertIn("onboarding", first)
        self.assertIn("[content.objectives_vary]", first)

    def test_a_blocking_consistency_breach_is_repaired_before_it_descopes(self):
        # An author that repairs is told which rule the draft breaches and what the concept
        # view found, and gets its rounds; only a draft still breaching after them descopes.
        class Foreign(authors.ArchetypeAuthor):
            repairs = True
            rounds = []

            def draft(self, brief):
                Foreign.rounds.append(list((brief.get("repair") or {}).get("problems") or []))
                draft = super().draft(brief)
                if not brief.get("repair"):
                    draft["core_loop"] += " Shoot the gate to open it."
                return draft

        Foreign.rounds = []
        authors.register_author("foreign", Foreign)
        self.addCleanup(authors.AUTHORS.pop, "foreign", None)
        result = run_step(load_strategy(), params={"author": "foreign"})
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
        self.assertEqual(len(Foreign.rounds), 2)
        self.assertIn("design_adds_no_foreign_mechanic", " ".join(Foreign.rounds[1]))
        self.assertIn("shoot", " ".join(Foreign.rounds[1]))

    def test_a_breach_the_author_keeps_still_descopes(self):
        class Stubborn(authors.ArchetypeAuthor):
            repairs = True

            def draft(self, brief):
                draft = super().draft(brief)
                draft["core_loop"] += " Shoot the gate to open it."
                return draft

        authors.register_author("stubborn", Stubborn)
        self.addCleanup(authors.AUTHORS.pop, "stubborn", None)
        result = run_step(load_strategy(), params={"author": "stubborn"})
        self.assertEqual((result.outcome, result.route, result.retryable),
                         (StepOutcome.FAILED, "descope", False))
        self.assertEqual(len(result.artifacts), 1)

    def test_a_detail_term_is_never_foreign(self):
        # Walls, crashes and locks are details most games have: a penguin that stops at a
        # wall and a door with a lock have not changed what the game is. They still count
        # when the strategy's concept names them and the design drops them.
        class Walled(authors.ArchetypeAuthor):
            def draft(self, brief):
                draft = super().draft(brief)
                draft["core_loop"] += " The piece stops at a wall; a locked door opens with a key."
                return draft

        authors.register_author("walled", Walled)
        self.addCleanup(authors.AUTHORS.pop, "walled", None)
        result = run_step(load_strategy(), params={"author": "walled"})
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
        rules = consistency.load_rules()
        self.assertEqual(sorted(rules["detail_terms"]), ["crash", "exit", "lock", "wall"])
        for term in rules["detail_terms"]:
            self.assertIn(term, rules["concept_terms"])

    def test_an_author_exception_is_left_to_the_runtime_as_retryable(self):
        class Flaky(authors.DesignAuthor):
            def draft(self, brief):
                raise ConnectionError("agent host unreachable")

        authors.register_author("flaky", Flaky)
        self.addCleanup(authors.AUTHORS.pop, "flaky", None)
        with self.assertRaises(ConnectionError):
            run_step(load_strategy(), params={"author": "flaky"})


class Idempotency(unittest.TestCase):
    def test_same_input_same_clock_same_artifact(self):
        first = run_step(load_strategy()).artifacts[0].content
        second = run_step(load_strategy()).artifacts[0].content
        self.assertEqual(first, second)
        self.assertEqual(first["provenance"]["content_hash"], second["provenance"]["content_hash"])


class ConsistencyRules(unittest.TestCase):
    def setUp(self):
        self.strategy = load_strategy()
        self.platforms = load_platforms(self.strategy)
        self.design = copy.deepcopy(run_step(self.strategy).artifacts[0].content)

    def results(self, design=None, platforms=None):
        block, blocking, _ = consistency.evaluate(design or self.design, self.strategy,
                                                  platforms or self.platforms, NOW)
        return {r["criterion_id"]: r for r in block["rule_results"]}, blocking

    def test_a_platform_offering_more_than_the_design_uses_is_not_a_breach(self):
        results, _ = self.results()
        self.assertFalse(results["monetization_supported_by_platform"]["breached"])

    def test_a_designed_placement_a_required_platform_lacks_is_a_breach(self):
        self.design["monetization"]["placements"].append({"kind": "iap", "trigger": "Shop"})
        crazygames = load_platforms({"platform_set": [
            {"id": "crazygames", "profile_version": "1.0.0", "role": "required"}]})
        results, blocking = self.results(platforms=crazygames)
        self.assertTrue(results["monetization_supported_by_platform"]["breached"])
        self.assertIn("monetization_supported_by_platform", blocking)

    def test_iap_counts_as_offered_where_the_platform_sells(self):
        self.design["monetization"]["placements"].append({"kind": "iap", "trigger": "Shop"})
        results, _ = self.results()   # Yandex: capabilities.iap true
        self.assertFalse(results["monetization_supported_by_platform"]["breached"])

    def test_a_platform_without_the_value_makes_a_rule_inapplicable(self):
        generic = load_platforms({"platform_set": [
            {"id": "generic-web", "profile_version": "1.0.0", "role": "required"}]})
        results, _ = self.results(platforms=generic)
        rule = results["interstitial_interval_fits_session"]
        self.assertFalse(rule["breached"])
        self.assertIn("not applicable", rule["note"])

    def test_an_unevaluable_rule_is_recorded_as_breached(self):
        del self.design["session"]["target_seconds"]
        results, blocking = self.results()
        self.assertTrue(results["scope_fits_session_count"]["breached"])
        self.assertIn("could not be evaluated", results["scope_fits_session_count"]["note"])
        self.assertIn("scope_fits_session_count", blocking)


CONTRACT_WORKFLOW = """
workflow:
  id: design-contract
  version: 1
  steps:
    - id: strategy
      type: test.strategy-seed
      outputs: [title-strategy]
    - id: design
      type: design
      inputs: [title-strategy]
      outputs: [game-design]
"""

SEED_MODULE = '''
import json
from wgflib.workflow import ArtifactOutput, StepResult, WorkflowStep

PATH = {path!r}


class SeedStep(WorkflowStep):
    type = "test.strategy-seed"

    def execute(self, inputs, context):
        with open(PATH, encoding="utf-8") as handle:
            return StepResult.success([ArtifactOutput("title-strategy", json.load(handle))])


def register(registry):
    registry.register(SeedStep.type, SeedStep)
'''


class ThroughTheEngine(unittest.TestCase):
    """The module plugs into the real engine from configuration, like any other module."""

    def setUp(self):
        self.scratch = tempfile.mkdtemp(prefix="wgf-design-")
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)
        modules = os.path.join(self.scratch, "modules")
        os.makedirs(modules)
        with open(os.path.join(modules, "wgf_test_seed.py"), "w", encoding="utf-8") as handle:
            handle.write(SEED_MODULE.format(path=STRATEGY_PATH))
        sys.path.insert(0, modules)
        self.addCleanup(sys.path.remove, modules)
        self.addCleanup(sys.modules.pop, "wgf_test_seed", None)
        self.workflow = os.path.join(self.scratch, "design-contract.workflow.yaml")
        with open(self.workflow, "w", encoding="utf-8") as handle:
            handle.write(textwrap.dedent(CONTRACT_WORKFLOW))

    def api(self, workflow=None):
        config = FactoryConfig({"steps": {"modules": ["wgf_test_seed", "wgf_design"]},
                                "storage": {"fsync": False}})
        return WorkflowAPI(config=config, store_dir=os.path.join(self.scratch, "store"),
                           workflow=workflow or self.workflow)

    def test_the_design_step_runs_and_its_artifact_is_persisted(self):
        api = self.api()
        state = api.run(RunRequest(project_id="neon-drift"))
        self.assertEqual(state.status, RunStatus.COMPLETED, state.steps["design"].error)
        stored = api.store.load(state.run_id)
        ref = stored.latest_artifact("game-design")
        self.assertEqual((ref.type, ref.version, ref.produced_by, ref.schema_version),
                         ("game-design", 1, "design", SCHEMA_VERSION))
        self.assertEqual(ref.metadata["engine"], "pixijs")
        self.assertEqual(ref.metadata["consistency"], "pass")
        design = api.store.read_artifact(state.run_id, ref)
        self.assertEqual(design["provenance"]["content_hash"], ref.content_hash)
        self.assertEqual(stored.steps["design"].consumed, ["title-strategy@v1"])
        self.assertEqual(stored.steps["design"].status, StepStatus.SUCCESS)

    def test_the_shipped_workflow_design_step_waits_without_a_strategy(self):
        api = self.api(workflow=os.path.join(ROOT, "core", "workflows", "new-game.workflow.yaml"))
        state = api.run(RunRequest(scope="design"))
        self.assertEqual(state.status, RunStatus.WAITING)


class ScriptedGapAgent(authors.DesignAuthor):
    """Stands in for the agent author: records the brief it was given and answers the gap at
    the field it names, starting from the design the gaps were found in."""

    name = "scripted-gap-agent"
    actor = "ai"
    seen = None

    def draft(self, brief):
        ScriptedGapAgent.seen = {"gaps": copy.deepcopy(brief.get("gaps")),
                                 "previous_design": copy.deepcopy(brief.get("previous_design"))}
        previous = brief["previous_design"]
        draft = {key: value for key, value in copy.deepcopy(previous).items()
                 if key not in ("provenance", "consistency")}
        unit = next(u for u in draft["build_spec"]["content"]["units"]
                    if u["id"] == "seg-two-rows")
        unit["parameters"]["row_gap_s"] = 0.75
        return draft


class DesignGapsReenterTheStep(unittest.TestCase):
    """Re-entered through `design-gap` (core/workflows/new-game.workflow.yaml): the
    prototype-report names what the design did not decide, and the step hands the author both
    the gaps and the design they were found in - its own previous output - so the design is
    repaired, never replaced. A deterministic author refuses: it cannot answer a question
    about a design it did not write.
    """

    GAP = {"field": "build_spec.content.units[seg-two-rows].parameters",
           "question": "What row gap does the two-obstacle segment spawn at?",
           "assumed": None, "severity": "blocking"}

    def setUp(self):
        self.scratch = tempfile.mkdtemp(prefix="wgf-design-gaps-")
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)
        self.strategy = load_strategy()
        first = run_step(self.strategy)
        self.assertEqual(first.outcome, StepOutcome.SUCCESS, first.error)
        self.design = first.artifacts[0].content
        # Where the run keeps it: ArtifactRef.location is relative to the run directory.
        self.location = os.path.join("artifacts", "game-design", "v1.json")
        path = os.path.join(self.scratch, self.location)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(self.design, handle)
        self.ref = ArtifactRef(id="game-design", type="game-design", version=1,
                               location=self.location, checksum="-",
                               content_hash=self.design["provenance"]["content_hash"],
                               schema_version=SCHEMA_VERSION)

    def second_visit(self, author=None, gaps=(GAP,)):
        report = {"design_gaps": [copy.deepcopy(g) for g in gaps]}
        return run_step(
            self.strategy, params={"author": author} if author else None,
            inputs=FakeInputs(self.strategy, extra={"prototype-report": report}),
            context=FakeContext(run_dir=self.scratch, previous_outputs=[self.ref], visit=2))

    def test_the_archetype_author_refuses_to_answer_design_gaps(self):
        result = self.second_visit()
        self.assertEqual((result.outcome, result.retryable), (StepOutcome.FAILED, False))
        self.assertIn(authors.GAPS_NEED_AGENT, result.error)
        self.assertEqual(result.artifacts, [])

    def test_a_prototype_report_with_no_gaps_is_designed_as_any_other_visit(self):
        result = self.second_visit(gaps=())
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
        self.assertEqual(result.artifacts[0].metadata["author"], "archetype")

    def test_an_agent_author_gets_the_gaps_and_the_design_they_were_found_in(self):
        ScriptedGapAgent.seen = None
        authors.register_author(ScriptedGapAgent.name, ScriptedGapAgent)
        try:
            result = self.second_visit(author=ScriptedGapAgent.name)
        finally:
            authors.AUTHORS.pop(ScriptedGapAgent.name, None)
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
        self.assertEqual(ScriptedGapAgent.seen["gaps"], [self.GAP])
        self.assertEqual(ScriptedGapAgent.seen["previous_design"], self.design)
        repaired = result.artifacts[0].content
        unit = next(u for u in repaired["build_spec"]["content"]["units"]
                    if u["id"] == "seg-two-rows")
        self.assertEqual(unit["parameters"]["row_gap_s"], 0.75)
        # The same game, specified further: nothing else moved, and the step re-derived the
        # provenance and the consistency block itself.
        self.assertEqual(repaired["core_loop"], self.design["core_loop"])
        self.assertEqual([u["id"] for u in repaired["build_spec"]["content"]["units"]],
                         [u["id"] for u in self.design["build_spec"]["content"]["units"]])
        self.assertEqual(repaired["consistency"]["status"], "pass")
        self.assertEqual(repaired["provenance"]["produced_by"]["actor"], "ai")

    def test_gaps_with_no_earlier_design_in_the_run_fail_the_step(self):
        result = run_step(
            self.strategy,
            inputs=FakeInputs(self.strategy,
                              extra={"prototype-report": {"design_gaps": [dict(self.GAP)]}}),
            context=FakeContext(run_dir=self.scratch, previous_outputs=[], visit=2))
        self.assertEqual((result.outcome, result.retryable), (StepOutcome.FAILED, False))
        self.assertIn("no earlier game-design to repair", result.error)


@unittest.skipUnless(shutil.which("npx"), "npx is not on PATH")
class Schema(unittest.TestCase):
    """Full JSON Schema validation. Offline: skipped when ajv is not in the npm cache."""

    def test_emitted_designs_validate_with_ajv(self):
        scratch = tempfile.mkdtemp(prefix="wgf-design-ajv-")
        self.addCleanup(shutil.rmtree, scratch, ignore_errors=True)
        files = []
        for archetype_id in archetypes.ARCHETYPES:
            path = os.path.join(scratch, f"{archetype_id}.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(run_step(load_strategy(), params={"archetype": archetype_id}).artifacts[0].content,
                          handle)
            files.append(path)
        command = ["npx", "--yes", "-p", "ajv-cli@5", "-p", "ajv-formats@2", "ajv", "validate",
                   "-s", "core/artifacts/game-design.schema.json",
                   "-r", "core/artifacts/shared/*.schema.json",
                   "-c", "ajv-formats", "--spec=draft2020", "--strict=false"]
        for path in files:
            command += ["-d", path]
        env = dict(os.environ, npm_config_offline="true")
        try:
            done = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
        except subprocess.TimeoutExpired:
            self.skipTest("ajv did not start in time")
        output = done.stdout + done.stderr
        if done.returncode != 0 and ("ENOTCACHED" in output or "could not determine executable" in output):
            self.skipTest("ajv-cli is not in the local npm cache")
        self.assertEqual(done.returncode, 0, output)


if __name__ == "__main__":
    unittest.main()

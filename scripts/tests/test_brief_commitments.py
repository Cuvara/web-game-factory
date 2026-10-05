"""A design honours the brief's stated counts, and never plans below what an adopted game
already ships.

The 2D real-game loop (2026-10-04): the brief asked for "4 themed worlds of hand-designed
levels ... boss levels, and an endless mode"; the release-tier design came out with 3 groups
and 12 units and passed every design rule, G3 and init - and the checkout it adopted already
shipped 32 units in 4 worlds with 4 bosses. These tests hold:

  * core/reference/brief-commitments.yaml + wgf_design/commitments.py: the exact brief yields
    groups >= 4, climax units and the endless mode as commitments; a release design with 3
    groups (or the mode cut) breaches the blocking rule brief_commitments_met with the
    brief's words; the strategy's release budget never commits fewer groups than the brief;
  * wgf_design/existing.py: an adopted fixture checkout with 32 units is the design's floor,
    recorded with its commit; a smaller design breaches existing_content_floor_kept;
  * content-sufficiency `content.regression` and the quality gate: a build that deletes units
    the adopted repository shipped is a QUALITY REGRESSION.

Deterministic and offline (a local git repository in a temporary directory). Run from the
repository root:

    python -m unittest scripts.tests.test_brief_commitments
"""

import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, HERE)

from test_content_sufficiency import data_of, design_of, survey_of, varied_units  # noqa: E402
from test_design_features import BRICKS  # noqa: E402
from test_design_module import run_step, variant  # noqa: E402
import test_quality_gate as quality_gate_tests  # noqa: E402
from test_strategy import PROFILES, opportunity, research_block  # noqa: E402
from wgf_design import commitments, consistency, existing  # noqa: E402
from wgf_design.platforms import load_platforms  # noqa: E402
from wgf_strategy import plan_strategy  # noqa: E402
from wgf_sufficiency import audit as auditing  # noqa: E402
from wgflib.workflow.contracts import ArtifactContracts  # noqa: E402
from wgflib.workflow.model import StepOutcome  # noqa: E402

NOW = "2026-10-05T00:00:00Z"


def adopted_content(worlds=4, per_world=8, drop=()):
    """The adopted 2D checkout's content data file, in its real shape: no `group` or
    `purpose` field, ids `w<world>-l<level>`, the last level of each world a boss."""
    units = []
    for w in range(1, worlds + 1):
        for n in range(1, per_world + 1):
            uid = f"w{w}-l{n}"
            if uid in drop:
                continue
            objective = ("Wear down the boss: break its shell and hit the core"
                         if n == per_world else f"Break every brick of level {n}")
            units.append({"id": uid, "index": len(units) + 1, "tier": "mvp",
                          "objective": objective, "mechanics": ["paddle-drag", "bricks"],
                          "layout": {"rows": [f"{w}{n}" * 3]}})
    return {"schema": "wgf-content/1", "generation": {"mode": "authored"}, "units": units}


def git(cwd, *args):
    subprocess.run(["git", "-c", "user.name=Test", "-c", "user.email=test@example.com",
                    "-c", "core.autocrlf=false", *args], cwd=cwd, check=True,
                   capture_output=True)


def with_groups(design, groups, per_group=4, endless="include"):
    """`design` re-planned at the release tier: `groups` groups of `per_group` units, each
    closed by a climax unit, and the endless-mode feature at `endless`."""
    design = copy.deepcopy(design)
    content = design["build_spec"]["content"]
    template = content["units"][0]
    units = []
    for g in range(1, groups + 1):
        for n in range(1, per_group + 1):
            unit = copy.deepcopy(template)
            unit.update(id=f"g{g}-u{n}", index=len(units) + 1, tier="mvp", group=f"g{g}",
                        purpose="climax" if n == per_group else "test")
            units.append(unit)
    content.update(units=units, quality_tier="release")
    for feature in design["features"]:
        if feature.get("catalogue") == "endless-mode":
            feature["evaluation"]["decision"] = endless
            feature["tier"] = "post-mvp" if endless == "include" else "optional"
    return design


def rule(block, rule_id):
    return next(r for r in block["rule_results"] if r["criterion_id"] == rule_id)


class TheBriefsCounts(unittest.TestCase):
    def test_the_2d_brief_commits_four_groups_climax_units_and_the_endless_mode(self):
        stated = {(c["quantity"], c["per_group"]): c
                  for c in commitments.of_strategy({"brief": BRICKS})}
        self.assertEqual(stated[("groups", False)]["minimum"], 4)
        self.assertEqual(stated[("groups", False)]["words"], "4 themed worlds")
        self.assertEqual(stated[("climax", False)]["minimum"], 2)  # "boss levels"
        self.assertEqual(commitments.modes(BRICKS, consistency_catalogue()),
                         {"endless-mode": "endless mode"})

    def test_counts_per_group_and_ceilings(self):
        found = commitments.stated(
            "32 hand-built levels in 4 worlds of 8, each world ending in a boss level; "
            "up to 5 stages; 3 balls per level; two bosses per chapter", "brief")
        got = {(c["quantity"], c["per_group"], c["minimum"]) for c in found}
        self.assertEqual(got, {("units", False, 32), ("groups", False, 4),
                               ("units", True, 8), ("climax", True, 1), ("climax", True, 2)})

    def test_the_strategy_states_counts_too_never_its_out_of_scope(self):
        strategy = {"brief": "a brick breaker", "mvp": ["32 levels in 4 worlds"],
                    "out_of_scope": ["6 worlds"]}
        stated = {c["quantity"]: c for c in commitments.of_strategy(strategy)}
        self.assertEqual(stated["groups"]["minimum"], 4)
        self.assertEqual(stated["groups"]["source"], "strategy mvp")
        self.assertEqual(stated["units"]["minimum"], 32)


def consistency_catalogue():
    from wgf_design.features import load_catalogue
    return load_catalogue()


class ADesignBelowTheBrief(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.strategy = variant(brief=BRICKS)
        result = run_step(cls.strategy)
        assert result.outcome == StepOutcome.SUCCESS, result.error
        cls.design = result.artifacts[0].content
        cls.platforms = load_platforms(cls.strategy)

    def evaluate(self, design):
        block, blocking, _warnings = consistency.evaluate(design, self.strategy,
                                                          self.platforms, NOW)
        return block, blocking

    def test_three_groups_for_a_four_world_brief_fail(self):
        block, blocking = self.evaluate(with_groups(self.design, 3))
        self.assertIn("brief_commitments_met", blocking)
        measured = rule(block, "brief_commitments_met")["measured"]
        self.assertTrue(any(m.startswith('groups >= 4 ("4 themed worlds", brief): the design '
                                         'plans 3') for m in measured), measured)

    def test_four_groups_with_the_endless_mode_included_hold(self):
        block, blocking = self.evaluate(with_groups(self.design, 4))
        self.assertNotIn("brief_commitments_met", blocking)
        self.assertIn("4 themed worlds", rule(block, "brief_commitments_met")["note"])

    def test_cutting_the_endless_mode_the_brief_asked_for_fails(self):
        block, blocking = self.evaluate(with_groups(self.design, 4, endless="cut"))
        self.assertIn("brief_commitments_met", blocking)
        self.assertTrue(any("endless-mode" in m for m in
                            rule(block, "brief_commitments_met")["measured"]))

    def test_below_the_release_tier_the_counts_are_reported_not_breached(self):
        # The fixture strategy states no tier: the built-in author's prototype passed, and the
        # rule's note names what the release still owes.
        note = rule(self.design["consistency"], "brief_commitments_met")["note"]
        self.assertIn("owed by the release", note)
        self.assertIn("groups >= 4", note)


class TheStrategyBudget(unittest.TestCase):
    def test_the_release_budget_never_commits_fewer_groups_than_the_brief(self):
        opp = opportunity(research=research_block(genre="endless-runner", family="arcade"))
        opp["brief"] = BRICKS
        budget = plan_strategy(opp, PROFILES, "neon-drift", None,
                               quality_tier="release")["concept"]["content_model"]["budget"]
        self.assertEqual(budget["groups"]["count"], 4)
        self.assertGreaterEqual(budget["units"], 4 * budget["groups"]["min_units_per_group"])
        groups = next(b for b in budget["basis"] if b["quantity"] == "groups")
        self.assertEqual((groups["brief"], groups["value"]), (4, 4))


class AnAdoptedCheckout(unittest.TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp(prefix="wgf-adopt-")
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)
        self.strategy = variant()
        self.title = self.strategy["title_id"]
        self.checkout = os.path.join(self.base, self.title)
        os.makedirs(os.path.join(self.checkout, "public", "content"))
        with open(os.path.join(self.checkout, "public", "content", "units.json"), "w",
                  encoding="utf-8", newline="\n") as handle:
            json.dump(adopted_content(), handle)
        git(self.checkout, "init", "-q")
        git(self.checkout, "add", "-A")
        git(self.checkout, "commit", "-q", "-m", "the shipped game")
        self.head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.checkout,
                                   capture_output=True, text=True, check=True).stdout.strip()
        self.config = {"checkouts": self.base, "init": {"adopt_existing": True}}

    def test_the_floor_is_what_the_checkout_ships_at_its_commit(self):
        floor, note = existing.read_floor(self.config, self.title)
        self.assertEqual((floor["units"], floor["groups"], floor["climax_units"]), (32, 4, 4))
        self.assertEqual(floor["source"]["commit"], self.head)
        self.assertEqual(floor["source"]["path"], "public/content/units.json")
        self.assertIn("unit id prefix", floor["measured_by"]["groups"])
        self.assertIn("32 unit(s)", note)

    def test_an_uncommitted_edit_is_not_the_floor(self):
        with open(os.path.join(self.checkout, "public", "content", "units.json"), "w",
                  encoding="utf-8") as handle:
            json.dump(adopted_content(worlds=1), handle)
        floor, _note = existing.read_floor(self.config, self.title)
        self.assertEqual(floor["units"], 32)

    def test_no_adoption_no_floor(self):
        floor, note = existing.read_floor({"checkouts": self.base}, self.title)
        self.assertIsNone(floor)
        self.assertIn("adopt_existing", note)

    def test_a_design_planning_fewer_units_than_the_checkout_ships_fails(self):
        result = run_step(self.strategy, config=self.config)
        self.assertEqual(result.outcome, StepOutcome.FAILED)
        self.assertEqual(result.route, "descope")
        self.assertIn("existing_content_floor_kept", result.error)
        design = result.artifacts[0].content
        self.assertEqual(design["existing_content"]["source"]["commit"], self.head)
        self.assertEqual(ArtifactContracts()("game-design", design), [])
        measured = rule(design["consistency"], "existing_content_floor_kept")["measured"]
        planned = len(design["build_spec"]["content"]["units"])
        self.assertLess(planned, 32)
        self.assertTrue(any(m.startswith(f"units: the design plans {planned}, the adopted "
                                         f"checkout ships 32") for m in measured), measured)

    def test_an_author_cannot_write_its_own_floor(self):
        result = run_step(self.strategy, config={"checkouts": self.base})
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
        self.assertNotIn("existing_content", result.artifacts[0].content)


class ABuildBelowTheFloor(unittest.TestCase):
    def setUp(self):
        shipped = adopted_content()
        self.floor = dict(existing.measure(shipped["units"]),
                          source={"path": "public/content/units.json", "commit": "a" * 40})
        self.floor.pop("measured_by")
        self.units = varied_units()
        self.design = design_of(self.units)
        self.design["existing_content"] = self.floor

    def test_a_build_that_deletes_shipped_units_is_a_regression(self):
        data = adopted_content(drop=("w4-l7", "w4-l8"))
        check = auditing.regression_check(self.design, data)
        self.assertEqual(check["status"], "FAIL")
        self.assertTrue(check["required"])
        self.assertIn("QUALITY REGRESSION", check["summary"])
        self.assertIn("w4-l8", check["measured"]["missing_unit_ids"])
        self.assertEqual(check["measured"]["climax_units"], 3)

    def test_the_whole_shipped_content_holds(self):
        check = auditing.regression_check(self.design, adopted_content())
        self.assertEqual(check["status"], "PASS")

    def test_no_floor_no_check(self):
        result = auditing.audit(design_of(self.units), None, data_of(self.units),
                                survey_of(self.units))
        self.assertNotIn("content.regression", [c["id"] for c in result["checks"]])

    def test_the_audit_reports_the_regression_as_a_blocking_finding(self):
        result = auditing.audit(self.design, None, data_of(self.units), survey_of(self.units))
        check = next(c for c in result["checks"] if c["id"] == "content.regression")
        self.assertEqual(check["status"], "FAIL")
        self.assertIn("units: the build ships 16, 32 shipped", check["summary"])
        finding = next(f for f in result["findings"] if f["check"] == "content.regression")
        # The design itself plans 16 of the 32: the design must grow first.
        self.assertEqual((finding["severity"], finding["route"]), ("blocker", "design-gap"))
        self.assertIn("design_gap", finding)

    def test_a_build_short_of_a_design_that_keeps_the_floor_goes_to_develop(self):
        design = design_of(self.units)
        design["existing_content"] = {"units": 16, "unit_ids": [u["id"] for u in self.units],
                                      "source": {
            "path": "public/content/units.json", "commit": "b" * 40}}
        dropped = data_of(self.units, drop=(self.units[-1]["id"],))
        check = auditing.regression_check(design, dropped)
        self.assertEqual((check["status"], check["route"]), ("FAIL", "develop"))
        self.assertIn(self.units[-1]["id"], check["measured"]["missing_unit_ids"])


class TheQualityGate(unittest.TestCase):
    setUp = quality_gate_tests.Gate.setUp
    run_step = quality_gate_tests.Gate.run_step

    def test_a_content_regression_fails_the_gate(self):
        floor = dict(existing.measure(adopted_content()["units"]),
                     source={"path": "public/content/units.json", "commit": "a" * 40})
        design = {"existing_content": floor}
        check = auditing.regression_check(design, adopted_content(worlds=3))
        docs = quality_gate_tests.release_build()
        report = docs["content-sufficiency-report"]
        report["checks"].append(check)
        report.update(verdict="FAIL", failed=["content.regression"], routes=["develop"])
        result = self.run_step(docs)
        self.assertEqual(result.outcome, StepOutcome.FAILED)
        self.assertIn("QUALITY REGRESSION", result.error)
        self.assertIn("content", result.artifacts[0].content["failed"])



# -- the adopted game in develop: improved, never rebuilt -------------------------------------

import test_develop_module as develop_tests  # noqa: E402
from wgf_develop import brief as develop_briefs  # noqa: E402


class AnAdoptedGameIsImprovedNotRebuilt(develop_tests.DevelopCase):
    """Live evidence (2026-10-04): after init adopted the shipped checkouts, the greybox
    developer rewrote them to the new design - the 2D game's content cut from 32 units to 12.
    The first greybox visit on an adopted game plays the build as it is; every brief states
    the floor; a commit below it is refused."""

    def setUp(self):
        super().setUp()
        content = os.path.join(self.repo, "public", "content")
        os.makedirs(content)
        with open(os.path.join(content, "units.json"), "w", encoding="utf-8",
                  newline="\n") as handle:
            json.dump(adopted_content(), handle)
        os.makedirs(os.path.join(self.repo, "public", "assets"))
        with open(os.path.join(self.repo, "public", "assets", "boss.png"), "wb") as handle:
            handle.write(b"\x89PNG shipped art")
        self.git("add", "-A")
        self.git(*develop_tests.IDENTITY, "commit", "-q", "-m", "the shipped game")
        self.shipped = self.git("rev-parse", "HEAD").strip()
        design = develop_tests.fixture("game-design")
        floor = dict(existing.measure(adopted_content()["units"]),
                     source={"path": "public/content/units.json", "commit": self.shipped})
        floor.pop("measured_by")
        design["existing_content"] = floor
        self.design = design

    def inputs(self, greybox=False):
        types = (("game-design", "scaffold-record", "title-strategy") if greybox else
                 ("game-design", "asset-manifest", "scaffold-record", "title-strategy"))
        return develop_tests.inputs_for(types=types, overrides={"game-design": self.design})

    def step(self, runner, phase):
        step = develop_tests.step_with(runner)
        step.definition.params = {"phase": phase}
        return step

    def brief(self):
        with open(os.path.join(self.repo, develop_briefs.BRIEF_DIR, "brief.json"),
                  encoding="utf-8") as handle:
            data = json.load(handle)
        with open(os.path.join(self.repo, develop_briefs.BRIEF_DIR, "brief.md"),
                  encoding="utf-8") as handle:
            return data, handle.read()

    def test_the_first_greybox_visit_plays_the_adopted_build_as_it_is(self):
        runner = develop_tests.FakeRunner(on_develop=develop_tests.write_game)
        result = self.step(runner, "greybox").execute(
            self.inputs(greybox=True), develop_tests.context(self.command_config()))
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
        self.assertEqual(runner.developer_calls(), [])
        report = result.artifacts[0].content
        self.assertEqual(report["build_ref"]["commit_sha"], self.shipped)
        self.assertTrue(result.artifacts[0].metadata["conformance"])
        self.assertEqual(ArtifactContracts()("prototype-report", report), [])
        # Nothing written, nothing committed: the adopted tree is as it shipped.
        self.assertEqual(self.git("rev-parse", "HEAD").strip(), self.shipped)
        self.assertEqual(self.git("status", "--porcelain"), "")

    def test_a_greybox_brief_on_an_adopted_game_keeps_its_art_and_states_the_floor(self):
        # The adopted build does not pass its checks as it is: a developer improves it.
        runner = develop_tests.FakeRunner(fail=("build",))
        result = self.step(runner, "greybox").execute(
            self.inputs(greybox=True), develop_tests.context(self.config()))
        self.assertEqual(result.outcome, StepOutcome.WAITING_FOR_HUMAN, result.error)
        data, text = self.brief()
        self.assertEqual(data["existing_content"]["floor"],
                         {"units": 32, "groups": 4, "climax_units": 4})
        self.assertEqual(data["existing_content"]["commit"], self.shipped)
        self.assertIn("## Adopted game: improve, never rebuild", text)
        self.assertIn("## Phase: greybox (adopted game)", text)
        self.assertNotIn("No asset files", text)
        self.assertNotIn("draw everything with primitives", text)

    def test_a_commit_that_cuts_the_shipped_units_is_refused(self):
        def rebuild(cwd):
            develop_tests.write_game(cwd, extra={
                "public/content/units.json": json.dumps(adopted_content(worlds=2,
                                                                        per_world=6))})
        runner = develop_tests.FakeRunner(on_develop=rebuild)
        result = self.step(runner, "production").execute(
            self.inputs(), develop_tests.context(self.command_config()))
        self.assertEqual(result.outcome, StepOutcome.FAILED)
        self.assertTrue(result.retryable)
        self.assertIn("QUALITY REGRESSION", result.error)
        self.assertIn("units: the build ships 12, 32 shipped", result.error)
        self.assertEqual(self.git("rev-parse", "HEAD").strip(), self.shipped)
        with open(os.path.join(self.repo, develop_briefs.BRIEF_DIR, "checks.json"),
                  encoding="utf-8") as handle:
            recorded = {c["id"]: c for c in json.load(handle)["checks"]}
        self.assertEqual(recorded["existing-content"]["status"], "failed")

    def test_a_commit_that_deletes_a_shipped_asset_is_refused(self):
        runner = develop_tests.FakeRunner(on_develop=lambda cwd: develop_tests.write_game(
            cwd, extra={"public/assets/boss.png": None}))
        result = self.step(runner, "production").execute(
            self.inputs(), develop_tests.context(self.command_config()))
        self.assertEqual(result.outcome, StepOutcome.FAILED)
        self.assertIn("public/assets/boss.png", result.error)

    def test_a_commit_that_adds_to_the_shipped_game_is_committed(self):
        def improve(cwd):
            content = adopted_content()
            content["units"].append(dict(content["units"][0], id="w5-l1", index=33))
            develop_tests.write_game(cwd, extra={
                "public/content/units.json": json.dumps(content)})
        runner = develop_tests.FakeRunner(on_develop=improve)
        result = self.step(runner, "production").execute(
            self.inputs(), develop_tests.context(self.command_config()))
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
        self.assertNotEqual(self.git("rev-parse", "HEAD").strip(), self.shipped)


if __name__ == "__main__":
    unittest.main()

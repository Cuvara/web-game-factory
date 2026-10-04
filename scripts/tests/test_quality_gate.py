"""The quality gate (scripts/wgf_quality): one build, every quality dimension, held to the floor.

The reports here are built the way the producing steps write them, about one build - a
development commit and the sdk commit verified on top of it. A build that holds every
dimension at the release tier is a `release`; each way the gate exists to catch a build that
is not falls short of it (docs/quality-gap-audit-2026-10.md, WS-7):

  * Mobile-40: every other dimension high, the UI broken on the mobile viewport (40% of its
    layout checks)                                       not-release, route develop
  * evidence about another build (a stale report)        BLOCKED, never scored
  * a run at tier mvp                                    `development`, never release
  * a family the floor does not list                     the nearest ancestor's contract and
                                                         the universal floor, never nothing
  * a dimension that held on the previous build and is below its floor on this one
                                                         QUALITY REGRESSION, the drop recorded
  * a finding that passes again on the build it was raised on
                                                         stays open; closed only on a newer build
  * a mid-run edit of the benchmark                      does not apply to the run that pinned it
  * release                                              refuses a build without a passing
                                                         quality-report of exactly that build

    python -m unittest scripts.tests.test_quality_gate
"""

import copy
import os
import shutil
import sys
import tempfile
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
sys.path.insert(0, SCRIPTS)

from wgf_quality import scoring  # noqa: E402
from wgf_quality.step import QualityGateStep, load_contract  # noqa: E402
from wgf_release import lineage  # noqa: E402
from wgflib import gate_evidence, paths  # noqa: E402
from wgflib.workflow import references  # noqa: E402
from wgflib.workflow.contracts import ArtifactContracts  # noqa: E402
from wgflib.workflow.definition import load_definition  # noqa: E402
from wgflib.workflow.model import StepOutcome  # noqa: E402

DEV = "d" * 40
SHIP = "e" * 40
NEWER_DEV = "a" * 40
NEWER_SHIP = "b" * 40
DIGEST = "sha256:" + "1" * 64
VIEWPORTS = ("desktop", "mobile")
UI_CHECKS = ("ui.text", "ui.targets", "ui.overlap", "ui.styled", "ui.states")
CONTENT_CHECKS = ("content.units_shipped", "content.units_reachable", "content.elements",
                  "content.combinations", "content.structure", "content.objectives",
                  "content.groups", "content.difficulty", "content.climax",
                  "content.progression", "content.playtime", "content.drift",
                  "content.entity_kinds")
PLAY_CHECKS = ("probe.present", "start.playable", "start.objective", "win.reachable",
               "lose.reachable", "restart.works", "act.acknowledged", "idle.grace",
               "page.errors", "progression.persists", "content.variety",
               "content.win_lose_per_unit", "difficulty.axes_progress", "frames.readable")


def _check(check_id, status="PASS", project=None, required=True, **extra):
    check = {"id": check_id, "status": status, "required": required,
             "summary": f"{check_id} {status}"}
    if project:
        check["project"] = project
    check.update(extra)
    return check


def release_build(dev=DEV, ship=SHIP, tier="release", family="arcade", node=None):
    """{artifact type: content} for a build that holds every dimension at `tier`."""
    design = {"title_id": "demo", "genre": {"family": family},
              "build_spec": {"content": {"quality_tier": tier}}}
    if node:
        design["genre"]["node"] = node
    play = {"title_id": "demo", "commit": dev, "verdict": "PASS", "skipped_checks": [],
            "checks": [_check(c, project=p) for c in PLAY_CHECKS for p in VIEWPORTS]}
    production = {"title_id": "demo", "commit": dev, "verdict": "PASS", "failed": [],
                  "routes": [],
                  "checks": ([_check(c, project=p) for c in UI_CHECKS for p in VIEWPORTS]
                             + [_check(c) for c in ("assets.present", "assets.runtime",
                                                    "assets.loaded", "assets.used",
                                                    "scene.no_primitives", "scene.contrast",
                                                    "audio.plays")])}
    visual = {"title_id": "demo", "commit": dev, "verdict": "PASS", "findings": [],
              "scores": {"art_completeness": 4, "character_readability": 5, "environment": 4,
                         "ui_polish": 4, "typography": 4, "composition": 4, "consistency": 4,
                         "no_debug": 5}}
    sufficiency = {"title_id": "demo", "commit": dev, "verdict": "PASS", "quality_tier": tier,
                   "checks": [_check(c) for c in CONTENT_CHECKS], "findings": [],
                   "skipped_checks": []}
    qa = {"title_id": "demo", "build_ref": {"commit_sha": ship}, "verdict": "pass",
          "blocking_defects": [],
          "perf_results": [{"device_class": "mid-range-mobile", "fps": 60, "within_budget": True}]}
    verification = {"title_id": "demo", "commit": {"sha": ship, "dirty": False},
                    "build_artifact": {"status": "built", "content_hash": DIGEST},
                    "verdict": "PASS",
                    "platform_readiness": [{"platform_id": "yandex", "role": "required",
                                            "readiness": "ready"}]}
    prototype = {"title_id": "demo", "build_ref": {"commit_sha": dev}}
    sdk = {"title_id": "demo", "build_ref": {"commit_sha": ship, "base_commit_sha": dev},
           "platforms": [{"platform_id": "yandex", "status": "working"}]}
    review = {"title_id": "demo", "reviewed_commit": ship, "verdict": "approve", "blockers": []}
    assets = {"title_id": "demo",
              "items": ([{"id": f"sfx-{i}", "type": "sfx", "status": "delivered"}
                         for i in range(8)]
                        + [{"id": "theme", "type": "music", "status": "delivered"}])}
    return {"game-design": design, "playability-report": play,
            "production-quality-report": production, "visual-qa-report": visual,
            "content-sufficiency-report": sufficiency, "qa-report": qa,
            "verification-report": verification, "prototype-report": prototype,
            "sdk-report": sdk, "review-report": review, "asset-manifest": assets}


def mobile_40(docs):
    """The UI broken on mobile: 2 of its 5 layout checks pass (40%)."""
    production = docs["production-quality-report"]
    for check in production["checks"]:
        if check.get("project") == "mobile" and check["id"] in ("ui.targets", "ui.overlap",
                                                                "ui.states"):
            check["status"] = "FAIL"
    return docs


class _Log:
    def __getattr__(self, name):
        return lambda *a, **k: None


class Gate(unittest.TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp(prefix="wgf-quality-")
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)

    def run_step(self, docs, previous=None, environment=None):
        class Inputs:
            refs = {k: types.SimpleNamespace(content_hash=None) for k in docs}

            def __contains__(self, k):
                return k in docs

            def load(self, k):
                return docs[k]

        outputs = []
        if previous is not None:
            import json
            path = os.path.join(self.base, "previous-quality.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(previous, handle)
            outputs = [types.SimpleNamespace(type="quality-report",
                                             location="previous-quality.json")]
        context = types.SimpleNamespace(config={}, run_dir=self.base, logger=_Log(), visit=1,
                                        attempt=1, execution=1, previous_outputs=outputs,
                                        environment=environment or {})
        result = QualityGateStep(types.SimpleNamespace(params={}, id="quality-gate")).execute(
            Inputs(), context)
        for artifact in result.artifacts:
            self.assertEqual(ArtifactContracts()("quality-report", artifact.content), [])
        return result

    @staticmethod
    def dimension(report, dim_id):
        return next(d for d in report["dimensions"] if d["id"] == dim_id)

    # -- the passing release-quality fixture ------------------------------------------------

    def test_a_build_holding_every_floor_at_release_is_a_release(self):
        result = self.run_step(release_build())
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
        report = result.artifacts[0].content
        self.assertEqual(report["verdict"], "PASS")
        self.assertEqual(report["release_decision"]["decision"], "release")
        self.assertEqual(report["failed"], [])
        self.assertEqual(report["build"], {"commit": SHIP, "development_commit": DEV,
                                           "digest": DIGEST})
        self.assertEqual(report["quality_tier"], "release")
        # The store is measured once its listing exists: deferred, never passed.
        self.assertEqual(self.dimension(report, "store")["status"], "DEFERRED")
        self.assertEqual(report["deferred"], ["store"])
        for dim in report["dimensions"]:
            if dim["id"] != "store":
                self.assertEqual(dim["status"], "PASS", dim)
        self.assertEqual(report["contract"]["genre"], "arcade")
        self.assertEqual(report["contract"]["resolved_by"], "family")
        self.assertTrue(all(e["status"] == "current" for e in report["evidence"]))
        self.assertEqual(report["benchmark"]["floor"]["path"], "core/reference/quality-floor.yaml")
        self.assertFalse(report["benchmark"]["pinned"])  # no run pinned it: the live file

    # -- Mobile-40 ---------------------------------------------------------------------------

    def test_mobile_40_one_dimension_below_its_floor_is_not_a_release(self):
        result = self.run_step(mobile_40(release_build()))
        self.assertEqual(result.outcome, StepOutcome.FAILED)
        self.assertEqual(result.route, "develop")
        self.assertFalse(result.retryable)
        self.assertIn("QUALITY REGRESSION", result.error)
        report = result.artifacts[0].content
        self.assertEqual(report["verdict"], "FAIL")
        self.assertEqual(report["release_decision"]["decision"], "not-release")
        self.assertIn("ui", report["failed"])
        ui = self.dimension(report, "ui")
        self.assertEqual(ui["status"], "BELOW_FLOOR")
        self.assertTrue(ui["regression"])
        self.assertIn("floor.ui_layout", ui["blockers_failed"])
        layout = next(c for c in report["criteria"] if c["id"] == "floor.ui_layout")
        self.assertEqual(layout["observed"]["by_viewport"], {"desktop": 1.0, "mobile": 0.4})
        self.assertEqual(layout["score"], 40.0)
        # Every other dimension holds - and no average carries ui past its floor.
        for dim in report["dimensions"]:
            if dim["id"] not in ("ui", "polish", "store"):
                self.assertEqual(dim["status"], "PASS", dim)
        self.assertGreater(report["overall_score"], 75)
        finding = next(f for f in report["findings"] if f["criterion"] == "floor.ui_layout")
        self.assertEqual((finding["dimension"], finding["severity"], finding["owner"],
                          finding["route"], finding["status"]),
                         ("ui", "blocker", "ui", "develop", "open"))
        self.assertEqual(finding["build"], {"commit": SHIP, "digest": DIGEST})
        self.assertEqual(finding["expected"]["minimum"], 1.0)

    def test_a_high_average_never_lifts_a_dimension_scored_below_its_floor(self):
        spec, _record = load_contract()
        docs = release_build()
        # Score only: no blocker in play, the dimension's mean is below its floor.
        spec = copy.deepcopy(spec)
        spec["dimensions"] = {"ui": dict(spec["dimensions"]["ui"])}
        criteria = [("universal", {"id": "x.ui", "dimension": "ui", "metric": "m",
                                   "evaluate": {"kind": "checks",
                                                "report": "production-quality-report",
                                                "checks": ["ui.*"], "projects": ["mobile"]},
                                   "minimum": 0.1, "severity": {"release": "warning"},
                                   "owner": "ui", "route": "develop"})]
        mobile_40(docs)
        result = scoring.score(spec, criteria, docs, {}, "release",
                               scoring.build_identity(docs))
        ui = result["dimensions"][0]
        self.assertEqual((ui["score"], ui["status"]), (40.0, "BELOW_FLOOR"))
        self.assertEqual(result["release_decision"]["decision"], "not-release")

    # -- stale evidence ----------------------------------------------------------------------

    def test_evidence_from_another_build_blocks_the_report(self):
        docs = release_build()
        docs["visual-qa-report"]["commit"] = NEWER_DEV
        result = self.run_step(docs)
        self.assertEqual(result.outcome, StepOutcome.BLOCKED)
        report = result.artifacts[0].content
        self.assertEqual(report["verdict"], "BLOCKED")
        self.assertEqual(report["release_decision"]["decision"], "not-release")
        stale = [e for e in report["evidence"] if e["status"] == "stale"]
        self.assertEqual([e["artifact_type"] for e in stale], ["visual-qa-report"])
        self.assertIn("another build", report["blocked_reason"])
        self.assertEqual(report["dimensions"], [])  # nothing scored on another build's report

    def test_a_review_of_the_development_commit_is_stale_for_the_shipped_one(self):
        docs = release_build()
        docs["review-report"]["reviewed_commit"] = DEV
        result = self.run_step(docs)
        self.assertEqual(result.outcome, StepOutcome.BLOCKED)

    # -- tier mvp ----------------------------------------------------------------------------

    def test_a_tier_mvp_run_is_development_never_release(self):
        result = self.run_step(release_build(tier="mvp"))
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
        report = result.artifacts[0].content
        self.assertEqual(report["quality_tier"], "mvp")
        self.assertEqual(report["release_decision"]["decision"], "development")
        self.assertIn("never a release", " ".join(report["release_decision"]["reasons"]))

    def test_a_run_with_no_tier_is_held_as_mvp(self):
        docs = release_build()
        del docs["game-design"]["build_spec"]
        report = self.run_step(docs).artifacts[0].content
        self.assertIsNone(report["quality_tier"])
        self.assertEqual(report["release_decision"]["decision"], "development")

    def test_at_tier_mvp_only_blockers_hold_a_dimension_below_its_floor(self):
        # Release-tier shortfalls are findings at mvp, never a floor: a development build.
        docs = release_build(tier="mvp")
        for check in docs["content-sufficiency-report"]["checks"]:
            if check["id"] in ("content.elements", "content.combinations", "content.structure"):
                check.update(status="FAIL", required=False)
        result = self.run_step(docs)
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
        report = result.artifacts[0].content
        variety = self.dimension(report, "variety")
        self.assertEqual(variety["status"], "PASS")
        self.assertLess(variety["score"], 75)
        self.assertIsNone(variety["min_score"])
        self.assertIn("quality:floor.variety",
                      [f["id"] for f in report["findings"] if f["severity"] == "minor"])

    def test_a_tier_mvp_build_below_a_universal_blocker_still_fails(self):
        docs = release_build(tier="mvp")
        docs["qa-report"]["blocking_defects"] = [{"id": "D-1"}]
        result = self.run_step(docs)
        self.assertEqual(result.outcome, StepOutcome.FAILED)
        report = result.artifacts[0].content
        self.assertEqual(report["failed"], ["technical"])
        self.assertEqual(report["release_decision"]["decision"], "development")

    # -- unknown family ----------------------------------------------------------------------

    def test_an_unknown_family_falls_back_to_the_universal_floor(self):
        spec, _record = load_contract()
        design = {"genre": {"family": "rhythm"}}
        criteria, summary = scoring.derive(spec, design, family_of_node=lambda n: iter(()))
        self.assertEqual((summary["genre"], summary["resolved_by"]), (None, "none"))
        self.assertEqual(len(criteria), len(spec["floor"]["universal"]))
        self.assertTrue(all(layer == "universal" for layer, _c in criteria))
        # And through the step: the universal floor holds, so the build is scored, not refused.
        docs = release_build(family="rhythm")
        report = self.run_step(docs).artifacts[0].content
        self.assertEqual(report["contract"]["genre"], None)
        self.assertEqual(report["release_decision"]["decision"], "release")

    def test_an_unknown_family_takes_its_nearest_ancestors_contract(self):
        spec, _record = load_contract()
        design = {"genre": {"family": "rhythm", "node": "beat-runner"}}
        ancestry = {"beat-runner": [("rhythm", "rhythm-game"), ("arcade", "arcade")]}
        criteria, summary = scoring.derive(spec, design,
                                           family_of_node=lambda n: iter(ancestry[n]))
        self.assertEqual((summary["genre"], summary["resolved_by"], summary["via_node"]),
                         ("arcade", "ancestor", "arcade"))
        genre = [c["id"] for layer, c in criteria if layer == "genre"]
        self.assertEqual(genre, [c["id"] for c in spec["floor"]["genres"]["arcade"]["criteria"]])

    def test_a_real_genre_node_resolves_through_the_research_vocabulary(self):
        from wgf_quality.step import _family_of_node
        walk = _family_of_node()
        self.assertIsNotNone(walk)
        spec, _record = load_contract()
        # endless-runner's ancestors are owned by a family the floor lists.
        criteria, summary = scoring.derive(spec, {"genre": {"family": "rhythm",
                                                            "node": "endless-runner"}},
                                           family_of_node=walk)
        self.assertEqual(summary["resolved_by"], "ancestor")
        self.assertIn(summary["genre"], spec["floor"]["genres"])

    def test_every_family_of_the_genre_models_has_a_contract(self):
        from wgflib import genre_models
        spec, _record = load_contract()
        families = set((genre_models.load().get("families") or {}))
        self.assertEqual(families - set(spec["floor"]["genres"]), set())

    def test_a_3d_game_is_held_to_the_3d_contract(self):
        spec, _record = load_contract()
        criteria, summary = scoring.derive(spec, {"genre": {"family": "racing"}}, render="3d")
        render = [c["id"] for layer, c in criteria if layer == "render"]
        self.assertIn("render.environment", render)
        self.assertEqual(summary["render"], "3d")
        docs = release_build(family="racing")
        docs["visual-qa-report"]["scores"]["environment"] = 2
        result = scoring.score(spec, criteria, docs, {}, "release", scoring.build_identity(docs))
        self.assertIn("visual", result["failed"])
        self.assertEqual(result["routes"], ["assets"])

    # -- regression and the finding lifecycle -----------------------------------------------

    def test_a_dimension_that_fell_below_its_floor_is_a_detected_regression(self):
        before = self.run_step(release_build()).artifacts[0].content
        after = self.run_step(mobile_40(release_build(dev=NEWER_DEV, ship=NEWER_SHIP)),
                              previous=before).artifacts[0].content
        self.assertIn("ui", after["regression"]["below_floor"])
        self.assertIn("floor.ui_layout", after["regression"]["regressed_criteria"])
        dropped = {d["dimension"]: d for d in after["regression"]["dropped"]}
        self.assertEqual(dropped["ui"]["from"], 100.0)
        self.assertLess(dropped["ui"]["to"], 100.0)
        finding = next(f for f in after["findings"] if f["criterion"] == "floor.ui_layout")
        self.assertTrue(finding["regressed"])
        self.assertEqual(after["regression"]["previous"]["commit"], SHIP)

    def test_a_finding_closes_only_on_a_newer_build(self):
        failing = self.run_step(mobile_40(release_build())).artifacts[0].content
        # The same build, its report rewritten to pass: no re-measurement of a newer build.
        same = self.run_step(release_build(), previous=failing)
        self.assertEqual(same.outcome, StepOutcome.FAILED)
        report = same.artifacts[0].content
        finding = next(f for f in report["findings"] if f["criterion"] == "floor.ui_layout")
        self.assertEqual(finding["status"], "open")
        self.assertIn("ui", report["failed"])
        self.assertIn("newer build", self.dimension(report, "ui")["reason"])
        # A newer build measured at the minimum closes it.
        newer = self.run_step(release_build(dev=NEWER_DEV, ship=NEWER_SHIP), previous=failing)
        self.assertEqual(newer.outcome, StepOutcome.SUCCESS, newer.error)
        closed = next(f for f in newer.artifacts[0].content["findings"]
                      if f["criterion"] == "floor.ui_layout")
        self.assertEqual(closed["status"], "closed")
        self.assertEqual(closed["closed_on"], {"commit": NEWER_SHIP, "digest": DIGEST})
        self.assertEqual(closed["first_seen"], SHIP)

    # -- release-tier bars no producer holds a build to -------------------------------------

    def test_a_visual_mean_below_the_release_bar_fails_though_visual_qa_passed(self):
        docs = release_build()
        docs["visual-qa-report"]["scores"] = {k: 3 for k in docs["visual-qa-report"]["scores"]}
        docs["visual-qa-report"]["scores"]["no_debug"] = 5
        result = self.run_step(docs)
        self.assertEqual(result.outcome, StepOutcome.FAILED)
        report = result.artifacts[0].content
        mean = next(c for c in report["criteria"] if c["id"] == "floor.visual_mean")
        self.assertEqual(mean["expected"]["minimum"], 4.0)  # quality-benchmark, not the rubric
        self.assertEqual(result.route, "assets")

    def test_audio_below_the_benchmark_routes_to_assets_naming_nothing_unmeasured(self):
        docs = release_build()
        docs["asset-manifest"]["items"] = docs["asset-manifest"]["items"][:3]
        result = self.run_step(docs)
        self.assertEqual(result.outcome, StepOutcome.FAILED)
        self.assertEqual(result.route, "assets")
        self.assertEqual(result.artifacts[0].content["failed"], ["audio"])

    def test_a_report_with_nothing_to_measure_is_unmeasured_never_a_pass(self):
        docs = release_build()
        del docs["asset-manifest"]
        report = self.run_step(docs).artifacts[0].content
        music = next(c for c in report["criteria"] if c["id"] == "floor.music")
        self.assertEqual(music["status"], "UNMEASURED")
        self.assertIn("audio", report["failed"])

    def test_missing_producer_reports_wait_for_input(self):
        docs = release_build()
        del docs["content-sufficiency-report"]
        result = self.run_step(docs)
        self.assertEqual(result.outcome, StepOutcome.WAITING_FOR_INPUT)


class Contract(unittest.TestCase):
    def test_the_shipped_contract_resolves_every_bar_at_every_tier(self):
        spec, record = load_contract()
        self.assertEqual(record["floor"]["version"], spec["floor"]["version"])
        criteria = [c for c in spec["floor"]["universal"]]
        for entry in spec["floor"]["genres"].values():
            criteria += entry["criteria"]
        for entry in spec["floor"]["dimensions_contracts"].values():
            criteria += entry["criteria"]
        for criterion in criteria:
            for tier in criterion["severity"]:
                for key in ("minimum", "maximum"):
                    if key in criterion:
                        value = scoring._bar(criterion[key], tier, spec["references"])
                        self.assertTrue(value is None or isinstance(value, (int, float)),
                                        (criterion["id"], tier, value))

    def test_release_bars_are_the_benchmarks_never_lower(self):
        spec, _record = load_contract()
        bench = spec["references"]["quality-benchmark"]["presentation"]["visual_qa"]
        by_id = {c["id"]: c for c in spec["floor"]["universal"]}
        refs = spec["references"]
        self.assertEqual(scoring._bar(by_id["floor.visual_mean"]["minimum"], "release", refs),
                         bench["min_mean"]["release"])
        self.assertEqual(scoring._bar(by_id["floor.visual_major_findings"]["maximum"],
                                      "release", refs), bench["max_major_findings"]["release"])

    def test_a_malformed_contract_is_refused(self):
        with self.assertRaises(scoring.ContractError):
            scoring.contract({"version": "1", "dimensions": {"ui": {}},
                              "universal": [{"id": "x", "dimension": "nope"}]}, {}, {})

    def test_every_criterion_names_a_known_evidence_report(self):
        spec, _record = load_contract()
        known = set(spec["floor"]["build_evidence"]) | {"asset-manifest"}
        for criterion in spec["floor"]["universal"]:
            self.assertIn(criterion["evaluate"]["report"], known, criterion["id"])


class Pinning(unittest.TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp(prefix="wgf-pin-")
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)

    def test_the_workflow_pins_the_quality_contract(self):
        definition = load_definition(os.path.join(paths.ROOT, "core", "workflows",
                                                  "new-game.workflow.yaml"))
        self.assertEqual(definition.pinned_references,
                         ["core/reference/quality-floor.yaml",
                          "core/reference/quality-benchmark.yaml",
                          "core/reference/visual-qa-rubric.yaml"])

    def test_a_mid_run_benchmark_edit_does_not_apply_to_the_run(self):
        root = os.path.join(self.base, "factory")
        run_dir = os.path.join(self.base, "run")
        os.makedirs(os.path.join(root, "core", "reference"))
        path = os.path.join(root, "core", "reference", "bench.yaml")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("version: 1.0.0\nbar: 4\n")
        relpath = "core/reference/bench.yaml"
        pins = references.pin(references.collect([relpath], root=root), run_dir)
        environment = {references.PARAM: pins}
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("version: 1.0.1\nbar: 1\n")  # lowered mid-run
        text, digest, pinned = references.read(relpath, environment, run_dir, root=root)
        self.assertTrue(pinned)
        self.assertIn("bar: 4", text)
        self.assertEqual(digest, pins[relpath])
        # A run that pinned nothing reads the live file, and says so.
        text, _digest, pinned = references.read(relpath, {}, run_dir, root=root)
        self.assertFalse(pinned)
        self.assertIn("bar: 1", text)

    def test_an_edited_pinned_copy_is_refused(self):
        root = os.path.join(self.base, "factory")
        run_dir = os.path.join(self.base, "run")
        os.makedirs(os.path.join(root, "core"))
        with open(os.path.join(root, "core", "b.yaml"), "w", encoding="utf-8") as handle:
            handle.write("bar: 4\n")
        pins = references.pin(references.collect(["core/b.yaml"], root=root), run_dir)
        with open(os.path.join(run_dir, references.DIRECTORY, "core", "b.yaml"), "w",
                  encoding="utf-8") as handle:
            handle.write("bar: 0\n")
        with self.assertRaises(references.PinError):
            references.read("core/b.yaml", {references.PARAM: pins}, run_dir, root=root)

    def test_the_step_blocks_on_a_tampered_pin(self):
        run_dir = os.path.join(self.base, "run")
        pins = references.pin(references.collect(["core/reference/quality-floor.yaml"]),
                              run_dir)
        with open(os.path.join(run_dir, references.DIRECTORY, "core", "reference",
                               "quality-floor.yaml"), "a", encoding="utf-8") as handle:
            handle.write("\n# lowered\n")
        gate = Gate("test_a_build_holding_every_floor_at_release_is_a_release")
        gate.base = run_dir
        result = gate.run_step(release_build(), environment={references.PARAM: pins})
        self.assertEqual(result.outcome, StepOutcome.BLOCKED)
        self.assertIn("edited after the start", result.message)

    def test_the_step_records_the_pinned_contract(self):
        run_dir = os.path.join(self.base, "run")
        relpaths = ["core/reference/quality-floor.yaml", "core/reference/quality-benchmark.yaml",
                    "core/reference/visual-qa-rubric.yaml"]
        pins = references.pin(references.collect(relpaths), run_dir)
        gate = Gate("test_a_build_holding_every_floor_at_release_is_a_release")
        gate.base = run_dir
        report = gate.run_step(release_build(),
                               environment={references.PARAM: pins}).artifacts[0].content
        self.assertTrue(report["benchmark"]["pinned"])
        self.assertEqual(report["benchmark"]["floor"]["sha256"],
                         pins["core/reference/quality-floor.yaml"])


class Release(unittest.TestCase):
    """release ships only a build its quality-report passed (wgf_release/lineage.py)."""

    def report(self, **overrides):
        docs = release_build()
        gate = Gate("test_a_build_holding_every_floor_at_release_is_a_release")
        gate.base = tempfile.mkdtemp(prefix="wgf-quality-release-")
        self.addCleanup(shutil.rmtree, gate.base, ignore_errors=True)
        report = gate.run_step(docs).artifacts[0].content
        report.update(overrides)
        loaded = {"quality-report": report, **docs}
        return loaded

    @staticmethod
    def codes(refusals):
        return [r.code for r in refusals]

    def test_no_quality_report_blocks_release(self):
        refusals = lineage.quality_refusals({}, release_build())
        self.assertEqual(self.codes(refusals), ["no-quality-report"])
        self.assertEqual(refusals[0].kind, lineage.BLOCKED)
        self.assertEqual(lineage.quality_refusals({}, release_build(), required=False), [])

    def test_a_passing_report_of_this_build_clears_it(self):
        self.assertEqual(lineage.quality_refusals({}, self.report()), [])

    def test_a_failed_report_is_refused(self):
        loaded = self.report(verdict="FAIL", failed=["ui"],
                             release_decision={"decision": "not-release", "reasons": ["ui"]})
        self.assertEqual(self.codes(lineage.quality_refusals({}, loaded)),
                         ["quality-not-passed", "quality-not-release"])

    def test_a_report_of_another_build_is_refused(self):
        loaded = self.report()
        loaded["quality-report"]["build"] = dict(loaded["quality-report"]["build"],
                                                 commit=NEWER_SHIP)
        self.assertEqual(self.codes(lineage.quality_refusals({}, loaded)),
                         ["quality-commit-mismatch"])

    def test_a_development_build_is_drafted_and_recorded_as_such(self):
        loaded = self.report(release_decision={"decision": "development", "reasons": []},
                             quality_tier="mvp")
        self.assertEqual(lineage.quality_refusals({}, loaded), [])
        refs = {"quality-report": types.SimpleNamespace(content_hash="sha256:" + "7" * 64)}
        recorded = lineage.quality_evidence(refs, loaded)
        self.assertEqual((recorded["decision"], recorded["quality_tier"], recorded["verdict"]),
                         ("development", "mvp", "PASS"))

    def test_a_report_predating_the_newest_reports_is_stale(self):
        loaded = self.report()
        refs = {"visual-qa-report": types.SimpleNamespace(content_hash="sha256:" + "9" * 64)}
        self.assertEqual(self.codes(lineage.quality_refusals(refs, loaded)),
                         ["stale-quality-report"])
        # Every report the gate scored, not only the ones release ships on.
        for artifact_type in ("playability-report", "content-sufficiency-report",
                              "review-report", "sdk-report"):
            refs = {artifact_type: types.SimpleNamespace(content_hash="sha256:" + "8" * 64)}
            self.assertEqual(self.codes(lineage.quality_refusals(refs, loaded)),
                             ["stale-quality-report"], artifact_type)


class GateEvidence(unittest.TestCase):
    def test_g4_shows_the_scorecard(self):
        gate = Gate("test_a_build_holding_every_floor_at_release_is_a_release")
        gate.base = tempfile.mkdtemp(prefix="wgf-quality-g4-")
        self.addCleanup(shutil.rmtree, gate.base, ignore_errors=True)
        report = gate.run_step(mobile_40(release_build())).artifacts[0].content
        evidence = gate_evidence.summarize({"quality-report": report})
        self.assertEqual(evidence["quality"][0]["decision"], "not-release")
        lines = "\n".join(gate_evidence.render(evidence))
        self.assertIn("quality (quality-report): verdict FAIL, decision not-release", lines)
        self.assertIn("BELOW_FLOOR", lines)
        self.assertIn("quality:floor.ui_layout", lines)


if __name__ == "__main__":
    unittest.main()

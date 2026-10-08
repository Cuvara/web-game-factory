"""WS-13: an intentionally bad game cannot pass /new-game, and every genre is held to one floor.

The shipped new-game workflow runs through the real engine. Every step that judges a build is
the real module - playability's judgement, production-quality, visual-qa, content-sufficiency,
quality-gate and triage, and the release step's refusals; every step that would call an agent
or a toolchain is a fixture (scripts/tests/fixtures/quality/world.py): the design is the one
the real design step writes at the release tier (designs.py), the developer builds it and puts
the scenario's degradation in it, and the playability step's bot is replaced by the records
and frames the bot writes - which the real analysis then judges. No agent session, no network.
What each case proves is in docs/quality-consistency-tests.md.

  A  multi-genre consistency    six genres, the same gates, release only when all pass
  B  intentional degradations   each detected, blocking, typed and routed to its owner
  C  recovery                   the owner's fix re-measured on a new commit, then release
  D  anti-gaming                stale evidence, a mid-run benchmark edit, a downgraded tier,
                                an unmeasured check, content deleted after QA

    python -m unittest scripts.tests.test_quality_consistency
"""

import copy
import json
import os
import shutil
import sys
import tempfile
import types
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
FIXTURES = os.path.join(HERE, "fixtures", "quality")
for _path in (SCRIPTS, HERE, FIXTURES):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import designs  # noqa: E402
import world as worlds  # noqa: E402
from wgf_release.lineage import evidence_refusals  # noqa: E402
from wgf_triage import findings as triage_findings  # noqa: E402
from wgf_triage.routing import Routing  # noqa: E402
from wgflib import genre_models, paths  # noqa: E402
from wgflib.workflow import checkpoint, quality, references  # noqa: E402
from wgflib.workflow.api import RunRequest, WorkflowAPI  # noqa: E402
from wgflib.workflow.config import FactoryConfig  # noqa: E402
from wgflib.workflow.contracts import ArtifactContracts  # noqa: E402
from wgflib.workflow.definition import load_definition  # noqa: E402
from wgflib.workflow.model import RunStatus  # noqa: E402
from wgflib.workflow.engine import EngineError  # noqa: E402
from wgflib.workflow.step import StepInputs, StepRegistry  # noqa: E402
from wgf_triage.step import TriageStep  # noqa: E402
from wgflib.yamllite import load_file  # noqa: E402

with open(os.path.join(FIXTURES, "scenarios.json"), encoding="utf-8") as _handle:
    SCENARIOS = json.load(_handle)
GENRES = {g["id"]: g for g in SCENARIOS["genres"]}
DEGRADATIONS = {d["id"]: d for d in SCENARIOS["degradations"]}
# The gates every production build passes before G4, in workflow order.
GATES = ("playability", "production-quality", "visual-qa", "content-sufficiency", "review",
         "sdk-review", "verify", "quality-gate")
GATE_REPORTS = {"playability": "playability-report",
                "production-quality": "production-quality-report",
                "visual-qa": "visual-qa-report",
                "content-sufficiency": "content-sufficiency-report",
                "quality-gate": "quality-report"}

_DESIGNS = {}


def design_of(family, unreported_persistence=False):
    """The release-tier design the real design step writes for `family` (cached)."""
    key = (family, unreported_persistence)
    if key not in _DESIGNS:
        design, result = designs.design(family, unreported_persistence)
        if design is None:
            raise AssertionError(f"the design step refused the {family} release design: "
                                 f"{result.error}")
        _DESIGNS[key] = design
    return copy.deepcopy(_DESIGNS[key])


class _API(WorkflowAPI):
    """The shipped workflow, with the fixture steps of one world registered for every run."""

    world = None

    def registry(self, use_mock, load_modules=True):
        registry = StepRegistry()
        checkpoint.register(registry)
        return worlds.register(registry, self.world)


class _Case(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.mkdtemp(prefix="wgf-ws13-")
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)
        # The checkout precedence would prefer an operator's WGF_GAME_REPO over the
        # scaffold-record's (docs/checkouts.md); the fixture checkout is the record's.
        patcher = mock.patch.dict(os.environ, {}, clear=False)
        patcher.start()
        self.addCleanup(patcher.stop)
        os.environ.pop("WGF_GAME_REPO", None)

    # -- running ----------------------------------------------------------------------------

    def world(self, genre, defects=(), fixes=None, unreported_persistence=False):
        spec = GENRES[genre]
        checkout = os.path.join(self.scratch, f"game-{genre}")
        os.makedirs(os.path.join(checkout, ".git"), exist_ok=True)
        return worlds.World({"defects": list(defects), "fixes": copy.deepcopy(fixes or {})},
                            design_of(spec["family"], unreported_persistence), checkout)

    def api(self, world, extra=None, store="store"):
        data = {"storage": {"fsync": False},
                "checkpoints": {"auto_approve": ["G2", "G3"]},
                "design": {"author": "agent"},
                "visualqa": {"judge": {"kind": "command",
                                       "argv": [sys.executable, worlds.JUDGE, "{frames_dir}",
                                                "{verdict}"]}}}
        for key, value in (extra or {}).items():
            data[key] = value
        api = _API(config=FactoryConfig(data), store_dir=os.path.join(self.scratch, store))
        api.world = world
        return api

    def start(self, api, **request):
        return api.run(RunRequest(**request))

    def decide(self, api, state, choice="pass"):
        return api.run(RunRequest(resume=state.run_id, decision=choice, decided_by="human",
                                  note="WS-13 test"))

    def to_g4(self, api):
        state = self.start(api)
        self.assertEqual((state.status, state.cursor), (RunStatus.WAITING, "prototype-review"),
                         self.story(api, state))
        return state

    # -- reading ----------------------------------------------------------------------------

    @staticmethod
    def steps(state, since=0):
        return [entry["step"] for entry in state.trail[since:]]

    @staticmethod
    def routes(state, step_id):
        return [entry.get("route") for entry in state.trail if entry["step"] == step_id]

    def newest(self, api, state, artifact_type):
        ref = state.latest_of_type(artifact_type)
        return None if ref is None else api.store.read_artifact(state.run_id, ref)

    def every(self, api, state, artifact_type):
        """Every version of `artifact_type` the run holds, oldest first."""
        out = []
        for refs in state.artifacts.values():
            for ref in refs:
                if ref.type == artifact_type:
                    out.append((ref.seq, api.store.read_artifact(state.run_id, ref)))
        return [content for _seq, content in sorted(out, key=lambda pair: pair[0])]

    def story(self, api, state):
        """What a failing assertion shows: the run's end and its trail."""
        trail = ", ".join(f"{e['step']}:{e.get('outcome')}"
                          + (f"({e['route']})" if e.get("route") not in (None, "success") else "")
                          for e in state.trail)
        return f"{state.status} at {state.cursor}: {state.message}\n  trail: {trail}"

    def loaded(self, api, state):
        refs = {}
        for artifact_type in {ref.type for refs_ in state.artifacts.values() for ref in refs_}:
            refs[artifact_type] = state.latest_of_type(artifact_type)
        return refs, {t: api.store.read_artifact(state.run_id, r) for t, r in refs.items()}

    def release_refusals(self, api, state, gates_passed=()):
        """What the release step would refuse on the run's newest evidence."""
        refs, loaded = self.loaded(api, state)
        return evidence_refusals(refs, loaded, state.run_id, gates_passed=gates_passed,
                                 required_quality=True)

    @staticmethod
    def failed_ids(artifact_type, report):
        """What a gate report names as failing: its checks, findings or criteria."""
        if artifact_type == "playability-report":
            return list(report.get("failed_checks") or [])
        if artifact_type == "quality-report":
            return [f["criterion"] for f in report.get("findings") or []
                    if f.get("status") == "open"]
        return [str(x) for x in report.get("failed") or []]

    def assert_names(self, artifact_type, report, expected):
        named = self.failed_ids(artifact_type, report)
        for wanted in expected:
            self.assertTrue(any(wanted in item for item in named),
                            f"{artifact_type} does not name {wanted!r}: {named}")

    def assert_same_build(self, api, state):
        """Every gate's newest report is about the build the run verified."""
        prototype = self.newest(api, state, "prototype-report")
        dev = prototype["build_ref"]["commit_sha"]
        sdk = self.newest(api, state, "sdk-report")
        ship = sdk["build_ref"]["commit_sha"]
        self.assertEqual(sdk["build_ref"]["base_commit_sha"], dev)
        for artifact_type in ("playability-report", "production-quality-report",
                              "visual-qa-report", "content-sufficiency-report"):
            self.assertEqual(self.newest(api, state, artifact_type)["commit"], dev,
                             artifact_type)
        self.assertEqual(self.newest(api, state, "qa-report")["build_ref"]["commit_sha"], ship)
        build = self.newest(api, state, "quality-report")["build"]
        self.assertEqual((build["commit"], build["development_commit"]), (ship, dev))
        return dev, ship


# -- A. multi-genre consistency ----------------------------------------------------------------

class MultiGenreConsistency(_Case):
    """Six genres, one floor: each derives its genre contract and quality budget, runs every
    required gate, and is released only once every gate has passed its build."""

    def test_every_genre_runs_every_gate_and_releases_only_when_all_pass(self):
        for genre_id, genre in GENRES.items():
            with self.subTest(genre=genre_id):
                world = self.world(genre_id)
                api = self.api(world)
                state = self.to_g4(api)
                self.check_genre(api, state, world, genre)

    def check_genre(self, api, state, world, genre):
        design = self.newest(api, state, "game-design")
        family = genre["family"]

        # The run's quality budget: the tier, its class and the bars' versions, recorded at
        # the start and never re-read from configuration.
        taken = state.params["quality"]
        self.assertEqual((taken["tier"], taken["class"]), ("release", "release"))
        self.assertTrue(taken["benchmark"].startswith("quality-benchmark@"))
        pinned = ["core/reference/quality-floor.yaml",
                  "core/reference/quality-benchmark.yaml",
                  "core/reference/visual-qa-rubric.yaml",
                  "core/reference/visual-quality.yaml",
                  "core/reference/play-realism.yaml",
                  "core/reference/browser-qa.yaml",
                  "core/reference/check-tiers.yaml",
                  "core/reference/lessons.yaml"]
        # 17: and everything the run's knowledge-contract is resolved from.
        pinned += [p for p in load_definition("new-game").pinned_references
                   if p not in pinned]
        self.assertIn("core/reference/genre-models.yaml", pinned)
        self.assertEqual(sorted(state.params["pinned_references"]),
                         sorted(references.collect(pinned)))

        # The design is the family's at the release tier, and the design step's own rules
        # passed it (designs.py raises otherwise).
        self.assertEqual(design["genre"]["family"], family)
        self.assertEqual(design["engine"]["dimension"], genre["dimension"])
        self.assertEqual(design["build_spec"]["content"]["quality_tier"], "release")

        # Every required gate ran on the production build, and passed it.
        ran = self.steps(state)
        for step_id in GATES:
            self.assertIn(step_id, ran, step_id)
        for step_id, artifact_type in GATE_REPORTS.items():
            report = self.newest(api, state, artifact_type)
            self.assertEqual(report["verdict"], "PASS", f"{artifact_type}: "
                             f"{self.failed_ids(artifact_type, report)}")
        self.assertEqual(self.newest(api, state, "qa-report")["verdict"], "pass")
        dev, ship = self.assert_same_build(api, state)
        play = self.newest(api, state, "playability-report")
        self.assertEqual(play["skipped_checks"], [], "a skipped check is never a pass")
        self.assertEqual({p["id"] for p in play["projects"] if p["ran"]}, {"desktop", "mobile"})

        # The genre contract the quality gate derived: the family's own criteria on top of the
        # universal floor, and the 3D contract for a 3D game.
        report = self.newest(api, state, "quality-report")
        contract = report["contract"]
        self.assertEqual((contract["family"], contract["genre"], contract["resolved_by"]),
                         (family, family, "family"))
        self.assertEqual(contract["render"], genre["dimension"])
        floor = load_file(os.path.join(paths.REFERENCE, "quality-floor.yaml"))
        by_layer = {}
        for criterion in report["criteria"]:
            by_layer.setdefault(criterion["layer"], set()).add(criterion["id"])
        # Every universal criterion, but one that applies only where its check is reported
        # (`applies: reported`: floor.existing_content, a run that adopted a repository).
        conditional = {c["id"] for c in floor["universal"]
                       if (c.get("evaluate") or {}).get("applies") == "reported"}
        self.assertEqual(len(by_layer["universal"] - conditional),
                         contract["universal"] - len(conditional))
        self.assertEqual(by_layer["genre"],
                         {c["id"] for c in floor["genres"][family]["criteria"]})
        self.assertEqual("render" in by_layer, genre["dimension"] == "3d", sorted(by_layer))
        self.assertEqual(report["quality_tier"], "release")
        self.assertTrue(report["benchmark"]["pinned"])
        self.assertEqual(report["release_decision"]["decision"], "release")
        for dimension in report["dimensions"]:
            self.assertIn(dimension["status"], ("PASS", "DEFERRED"), dimension)

        # The content budget the build was counted against: the larger of the benchmark's
        # bar and the family's own.
        sufficiency = self.newest(api, state, "content-sufficiency-report")
        self.assertEqual(sufficiency["quality_tier"], "release")
        shipped = next(c for c in sufficiency["checks"] if c["id"] == "content.units_shipped")
        family_total = (genre_models.load()["families"][family].get("units") or {})             .get("min_total") or 0
        bar = max(12, int(family_total))  # quality-benchmark content.units.min_total
        self.assertIn(f">= {bar} units", shipped["expected"])
        self.assertEqual(shipped["measured"]["shipped"], len(world.units))

        # Nothing is released before G4 is passed; once it is, the release is drafted and the
        # run is release-ready.
        self.assertNotIn("release", ran)
        self.assertFalse(api.quality(state)["release_ready"])
        state = self.decide(api, state)
        self.assertEqual(state.status, RunStatus.COMPLETED, self.story(api, state))
        self.assertEqual(world.refusals, [])
        self.assertIsNotNone(state.latest_of_type("release-manifest"))
        readiness = api.quality(state)
        self.assertEqual((readiness["class"], readiness["release_ready"]), ("release", True))


# -- B. intentional degradations ----------------------------------------------------------------

class IntentionalDegradations(_Case):
    """Each degradation, alone in an otherwise release-quality build of its genre, is
    DETECTED by its gate, BLOCKS the run (no G4, no release, release refuses), produces a
    typed quality finding, and is ROUTED to the specialist that owns it. The developer never
    fixes it here, so the run spends its loop budget and stops for a person."""

    def degrade(self, case_id):
        case = DEGRADATIONS[case_id]
        world = self.world(case["genre"], [case["defect"]])
        api = self.api(world)
        state = self.start(api)

        # Blocked: the loop budget is spent on the gate that keeps failing; G4 is never asked
        # and release never runs.
        self.assertEqual(state.status, RunStatus.BLOCKED, self.story(api, state))
        ran = self.steps(state)
        self.assertNotIn("prototype-review", ran, self.story(api, state))
        self.assertNotIn("release", ran)
        readiness = api.quality(state)
        self.assertEqual(readiness["class"], "release")
        self.assertFalse(readiness["release_ready"])
        refusals = [r.code for r in self.release_refusals(api, state)]
        self.assertTrue(refusals)
        self.assertTrue({"no-qa-report", "g4-not-passed"} & set(refusals), refusals)

        # Detected, by the gate expected, every time it measured the degraded build.
        report = self.newest(api, state, case["report"])
        self.assertEqual(report["verdict"], "FAIL", self.story(api, state))
        self.assert_names(case["report"], report, case["expect"])
        failing = [r for r in self.routes(state, case["gate"]) if r not in (None, "success")]
        self.assertGreaterEqual(len(failing), 2, f"{case['gate']} routes: {failing}")
        return case, world, api, state, report

    def assert_routed_through_triage(self, case, api, state):
        """The first triage after the gate's failure normalized it into typed findings and
        routed the owner's group: the finding validates against the quality-finding schema
        (the engine validated the triage-report), names the gate as its source and the
        specialist as its owner."""
        triage = next(t for t in self.every(api, state, "triage-report")
                      if t.get("source", "").startswith(case["gate"] + "."))
        mine = [f for f in triage["findings"] if f["source"]["producer"] == case["report"]]
        self.assertTrue(mine, triage["findings"])
        self.assertTrue(any(any(w.rsplit(":", 1)[-1] in f["id"] for w in case["expect"])
                            for f in mine), [f["id"] for f in mine])
        owners = {f["owner"] for f in mine}
        self.assertIn(case.get("owner") or case["label"], owners)
        labels = [g["label"] for g in [triage["selected"]] + list(triage.get("pending") or [])]
        self.assertIn(case["label"], labels)
        sources = {r["provenance"]["content_hash"]: r
                   for r in self.every(api, state, case["report"])}
        for finding in mine:
            # About the build its gate measured, and saying what the owner must make pass.
            source = sources[finding["source"]["content_hash"]]
            measured = source.get("commit") or (source.get("build") or {}).get("commit")
            self.assertEqual(finding["build"]["commit"], measured)
            self.assertTrue(finding["task"]["acceptance"])
        ledger = {r["id"]: r for r in triage["lifecycle"]}
        for finding in mine:
            self.assertIn(ledger[finding["id"]]["status"], ("assigned", "classified"))
        # The visit that triage sends is the owner's.
        routed = self.routes(state, "triage")
        self.assertIn(case["label"], routed)
        return triage

    # One test per degradation: a failure names it.

    def test_1_remove_content(self):
        case, _w, api, state, report = self.degrade("remove-content")
        shipped = next(c for c in report["checks"] if c["id"] == "content.units_shipped")
        self.assertLess(shipped["measured"]["shipped"], shipped["measured"]["owed"])
        self.assertEqual(shipped["route"], "develop")  # the design owes them; the build lacks
        self.assert_routed_through_triage(case, api, state)

    def test_2_reduce_mechanic_variety_counted_on_the_build(self):
        case, _w, api, state, report = self.degrade("reduce-variety-built")
        elements = next(c for c in report["checks"] if c["id"] == "content.elements")
        self.assertLess(elements["measured"]["build"]["distinct"],
                        elements["measured"]["design"]["distinct"])
        self.assert_routed_through_triage(case, api, state)

    def test_2_reduce_mechanic_variety_seen_in_play(self):
        case, _w, api, state, _report = self.degrade("reduce-variety-played")
        self.assert_routed_through_triage(case, api, state)

    def test_3_broken_mobile_layout(self):
        case, _w, api, state, report = self.degrade("broken-mobile-layout")
        desktop = [c for c in report["checks"] if c.get("project") == "desktop"
                   and c["id"].startswith("ui.")]
        self.assertTrue(desktop and all(c["status"] == "PASS" for c in desktop))
        self.assert_routed_through_triage(case, api, state)

    def test_4_severe_visual_defect_routes_by_the_engine_dimension(self):
        for case_id in ("severe-visual-defect-3d", "severe-visual-defect-2d"):
            with self.subTest(case=case_id):
                case, _w, api, state, report = self.degrade(case_id)
                self.assertTrue(any(f["severity"] == "blocker" for f in report["findings"]))
                # The playability bot's own checks do not see it: it is the judge's.
                self.assertEqual(self.newest(api, state, "playability-report")["verdict"],
                                 "PASS")
                self.assert_routed_through_triage(case, api, state)

    def test_5_remove_progression(self):
        case, _w, api, state, _report = self.degrade("remove-progression")
        self.assert_routed_through_triage(case, api, state)

    def test_6_placeholder_assets_go_to_the_assets_step(self):
        case, _w, api, state, report = self.degrade("placeholder-assets")
        present = next(c for c in report["checks"] if c["id"] == "assets.present")
        self.assertEqual((present["route"], present["measured"]["placeholder"]),
                         ("assets", present["assets"]))
        # Routed straight to the step that owns art (new-game: production-quality `assets`
        # -> assets); triage does not route it again, and records it in the run's ledger as
        # handed to the assets step - implemented by its manifest, never resolved by it.
        self.assertEqual(self.routes(state, "production-quality").count("assets"), 3)
        ledger = {r["id"]: r for r in self.newest(api, state, "triage-report")["lifecycle"]}
        handed = [r for fid, r in ledger.items() if "assets.present" in fid]
        self.assertTrue(handed, sorted(ledger))
        self.assertTrue(all(r["status"] == "implemented" and r["fix"]["specialist"] == "assets"
                            and r["fix"]["artifact_id"] for r in handed), handed)
        entered = [e for e in state.trail if e["step"] == "assets"]
        self.assertGreaterEqual(len(entered), 3)
        typed = triage_findings.normalize("production-quality-report", report, Routing.load())
        placeholder = [f for f in typed if f["source"]["check"] == "assets.present"]
        self.assertEqual([f["route"] for f in placeholder], ["assets"])
        self.assertTrue(all(f["owner"] == "artist-2d" for f in placeholder), placeholder)

    def test_7_broken_win_lose_state(self):
        case, _w, api, state, _report = self.degrade("broken-win-lose")
        self.assert_routed_through_triage(case, api, state)

    def test_8_performance_regression(self):
        case, _w, api, state, report = self.degrade("performance-regression")
        technical = next(d for d in report["dimensions"] if d["id"] == "technical")
        self.assertEqual(technical["status"], "BELOW_FLOOR")
        # Every gate before it passed the build: only the floor holds it back.
        for artifact_type in ("playability-report", "production-quality-report",
                              "visual-qa-report", "content-sufficiency-report"):
            self.assertEqual(self.newest(api, state, artifact_type)["verdict"], "PASS")
        self.assert_routed_through_triage(case, api, state)

    def test_9_duplicate_level(self):
        case, _w, api, state, report = self.degrade("duplicate-level")
        structure = next(c for c in report["checks"] if c["id"] == "content.structure")
        self.assertEqual(len(structure["measured"]["build"]["repeated"]), 2)
        self.assertEqual(structure["measured"]["design"]["repeated"], [])
        self.assert_routed_through_triage(case, api, state)

    def test_10_one_dimension_below_the_floor_is_not_averaged_away(self):
        case, _w, api, state, report = self.degrade("one-dimension-below-floor")
        audio = next(d for d in report["dimensions"] if d["id"] == "audio")
        self.assertEqual(audio["status"], "BELOW_FLOOR")
        others = [d for d in report["dimensions"] if d["id"] not in ("audio", "store")]
        self.assertTrue(all(d["status"] == "PASS" for d in others), others)
        self.assertGreater(report["overall_score"], 75)
        self.assertEqual(report["failed"], ["audio"])
        self.assertEqual(report["release_decision"]["decision"], "not-release")
        triage = self.assert_routed_through_triage(case, api, state)
        sfx = next(f for f in triage["findings"] if "floor.sfx" in f["id"])
        self.assertEqual(sfx["dimension"], "audio")


    def test_12_flat_progression_counted_on_the_build(self):
        """The build ships its levels as a flat list - no gated unlocks - while what it saves
        across a reload still works. content-sufficiency counts gated unlocks on the built
        content (units.json), not the design's progression steps, so the build fails
        content.progression and the systems designer owns it. (A WS-13 gap until the count
        moved to the build: it passed every gate.)"""
        case, _w, api, state, report = self.degrade("flat-progression")
        check = next(c for c in report["checks"] if c["id"] == "content.progression")
        self.assertEqual((check["measured"]["build"], check["route"]), (0, "develop"))
        self.assertGreaterEqual(check["measured"]["design"], 2)
        play = self.newest(api, state, "playability-report")
        self.assertEqual(play["verdict"], "PASS")  # what it saves still survives a reload
        self.assert_routed_through_triage(case, api, state)

    def test_11_store_copy_claiming_content_the_build_lacks(self):
        """After G4: the store copy says the game has more levels than the build measured.
        listing-validation's count check (wgf_listing.buildfacts, as the real step runs it)
        fails it, listing-triage routes the copywriter's finding to store-listing, and with
        no rewrite the run stops before release."""
        world = self.world("platformer-content", ["copy-overclaims"])
        api = self.api(world)
        state = self.decide(api, self.to_g4(api))
        self.assertEqual(state.status, RunStatus.BLOCKED, self.story(api, state))
        self.assertNotIn("release", self.steps(state))
        self.assertFalse(api.quality(state)["release_ready"])
        report = self.newest(api, state, "listing-validation-report")
        self.assertEqual(report["verdict"], "FAIL")
        self.assertIn("grounding.counts.en", report["failed"])
        counts = next(c for c in report["checks"] if c["id"] == "grounding.counts.en")
        self.assertIn("but the build has 12", counts["summary"])
        triage = self.every(api, state, "triage-report")[-1]
        self.assertEqual(triage["source"], "listing-validation.listing")
        self.assertEqual((triage["selected"]["owner"], triage["selected"]["label"]),
                         ("copywriter", "listing"))
        finding = next(f for f in triage["findings"]
                       if f["source"]["check"] == "grounding.counts.en")
        self.assertEqual((finding["owner"], finding["route"]), ("copywriter", "listing"))
        codes = [r.code for r in self.release_refusals(api, state, gates_passed=("G4",))]
        self.assertIn("listing-not-passed", codes)


# -- C. recovery -------------------------------------------------------------------------------

class Recovery(_Case):
    """The routed specialist's fix changes the build; the gates measure the new commit; the
    finding is verified and closed only by that re-measurement; and only then is the run
    release-ready. A fix that breaks another gate is not verified."""

    def ledger(self, api, state):
        """The run's finding ledger as triage would advance it now: the real step, executed
        on the run's newest artifacts, outside the run (the run itself is not changed). It
        must agree with the ledger the quality gate advanced in the run."""
        step_def = api.definition_for(state).step("triage")
        refs = {t: state.latest_of_type(t) for t in step_def.inputs}
        inputs = StepInputs({t: r for t, r in refs.items() if r is not None},
                            lambda ref: api.store.read_artifact(state.run_id, ref), [])
        quiet = types.SimpleNamespace(**{level: (lambda *a, **k: None) for level in
                                         ("debug", "info", "warning", "error")})
        context = types.SimpleNamespace(entered_by=None, run_dir=api.store.run_dir(state.run_id),
                                        project_id=state.project_id, execution=1, visit=1,
                                        attempt=1, logger=quiet, environment={}, config={},
                                        previous_outputs=[])
        result = TriageStep(step_def).execute(inputs, context)
        self.assertEqual(result.outcome, "SUCCESS", result.error)
        report = result.artifacts[0].content
        self.assertEqual(ArtifactContracts()("triage-report", report), [])
        return {r["id"]: r for r in report["lifecycle"]}

    def recover(self, case_id, fixes):
        case = DEGRADATIONS[case_id]
        world = self.world(case["genre"], [case["defect"]], fixes)
        api = self.api(world)
        state = self.to_g4(api)
        return case, world, api, state

    def assert_measured_again(self, api, state, case):
        """The gate failed the degraded build and passed the fixed one: two commits, the
        second measured by every gate."""
        reports = self.every(api, state, case["report"])
        verdicts = [r["verdict"] for r in reports]
        self.assertIn("FAIL", verdicts)
        self.assertEqual(verdicts[-1], "PASS")
        failed = next(r for r in reports if r["verdict"] == "FAIL")
        dev, ship = self.assert_same_build(api, state)
        before = (failed.get("build") or {}).get("development_commit") or failed.get("commit")
        self.assertNotEqual(before, dev, "the fix must be a new build")
        return dev

    def test_content_restored_by_the_level_designer_is_verified_on_the_new_commit(self):
        case, world, api, state = self.recover(
            "remove-content", {"level-designer": {"fixes": ["remove-content"]}})
        # The last group gone takes its gate with it (content.progression, the systems
        # designer's): both owners visit the one build, the level designer first.
        self.assertEqual(world.visits, ["level-designer", "systems-designer"])
        dev = self.assert_measured_again(api, state, case)
        fid = "content-sufficiency-report:content-sufficiency:content.units_shipped"
        # No triage runs after the gates measured the fix: the last triage left the finding
        # unverified...
        triaged = {r["id"]: r for r in self.newest(api, state, "triage-report")["lifecycle"]}
        self.assertIn(triaged[fid]["status"], ("assigned", "implemented"))
        # ...and the quality gate, which sees every report of the fixed build, advanced the
        # run's ledger before G4: implemented by the owner's visit, verified by the gate that
        # raised it, closed once every gate measured it. Nothing blocking is left open.
        quality_report = self.newest(api, state, "quality-report")
        self.assertEqual(quality_report["ledger"]["open"], [])
        in_run = {r["id"]: r for r in quality_report["ledger"]["lifecycle"]}
        self.assertEqual(in_run[fid]["status"], "closed", in_run[fid])
        ledger = self.ledger(api, state)
        self.assertEqual(ledger[fid]["status"], in_run[fid]["status"])
        finding = in_run[fid]
        self.assertEqual(finding["status"], "closed", finding)
        self.assertEqual(finding["fix"]["specialist"], "level-designer")
        visit = next(p for p in self.every(api, state, "prototype-report")
                     if (p.get("specialist") or {}).get("role") == "level-designer")
        self.assertEqual(finding["fix"]["commit"], visit["build_ref"]["commit_sha"])
        statuses = [h["status"] for h in finding["history"]]
        self.assertEqual(statuses, ["detected", "classified", "assigned", "implemented",
                                    "verified", "closed"])
        self.assertEqual(finding["verification"]["verdict"], "passed")
        self.assertEqual(finding["verification"]["build"]["commit"], dev)
        # The gate the lost group took with it is verified on the same build.
        progression = in_run["content-sufficiency-report:content-sufficiency:content.progression"]
        self.assertIn(progression["status"], ("verified", "closed"))
        # Only now is it released.
        state = self.decide(api, state)
        self.assertEqual(state.status, RunStatus.COMPLETED, self.story(api, state))
        self.assertTrue(api.quality(state)["release_ready"])

    def test_a_fix_that_regresses_another_gate_is_not_verified(self):
        case, world, api, state = self.recover(
            "broken-mobile-layout",
            {"ui": {"fixes": ["broken-mobile-layout"], "breaks": ["remove-content"]},
             "level-designer": {"fixes": ["remove-content"]}})
        self.assertEqual(world.visits, ["ui", "level-designer"])
        # The triage after the ui visit: the production gate passes the ui fix, but the
        # same build fails content-sufficiency, which passed before - a regression.
        after_ui = [t for t in self.every(api, state, "triage-report")
                    if t.get("source") == "content-sufficiency.develop"][0]
        ledger = {r["id"]: r for r in after_ui["lifecycle"]}
        targets = ledger["production-quality-report:ui.targets@mobile"]
        self.assertEqual(targets["status"], "implemented")
        self.assertEqual(targets["verification"]["verdict"], "regressed")
        self.assertIn("content-sufficiency-report:content-sufficiency:content.units_shipped",
                      targets["verification"]["regressions"])
        self.assertEqual(after_ui["selected"]["label"], "level-designer")
        # Once the regression is fixed too, the ui finding is verified on that build - in the
        # run, by the quality gate before G4.
        quality_report = self.newest(api, state, "quality-report")
        in_run = {r["id"]: r for r in quality_report["ledger"]["lifecycle"]}
        self.assertIn(in_run["production-quality-report:ui.targets@mobile"]["status"],
                      ("verified", "closed"))
        self.assertEqual(quality_report["ledger"]["open"], [])
        state = self.decide(api, state)
        self.assertEqual(state.status, RunStatus.COMPLETED, self.story(api, state))
        self.assertTrue(api.quality(state)["release_ready"])

    def test_art_made_again_through_the_assets_step(self):
        case, world, api, state = self.recover(
            "placeholder-assets", {"assets": {"fixes": ["placeholder-assets"]}})
        self.assertEqual(world.visits, ["assets"])
        self.assert_measured_again(api, state, case)
        manifest = self.newest(api, state, "asset-manifest")
        self.assertFalse(any(item.get("placeholder") for item in manifest["items"]))
        # The finding the gate sent straight to assets is in the run's ledger, implemented by
        # the remade manifest and verified when the production gate passed the new build.
        in_run = {r["id"]: r for r in self.newest(api, state, "quality-report")["ledger"]
                  ["lifecycle"]}
        handed = [r for fid, r in in_run.items() if "assets.present" in fid]
        self.assertTrue(handed and all(r["status"] in ("verified", "closed") for r in handed),
                        sorted(in_run))
        state = self.decide(api, state)
        self.assertEqual(state.status, RunStatus.COMPLETED, self.story(api, state))

    def test_store_copy_rewritten_by_the_copywriter_is_validated_again(self):
        world = self.world("platformer-content", ["copy-overclaims"],
                           {"copywriter": {"fixes": ["copy-overclaims"]}})
        api = self.api(world)
        state = self.decide(api, self.to_g4(api))
        self.assertEqual(state.status, RunStatus.COMPLETED, self.story(api, state))
        self.assertEqual(world.visits, ["copywriter"])
        verdicts = [r["verdict"] for r in self.every(api, state, "listing-validation-report")]
        self.assertEqual(verdicts, ["FAIL", "PASS"])
        listings = self.every(api, state, "store-listing")
        self.assertNotEqual(listings[0]["copy"], listings[-1]["copy"])
        self.assertEqual(world.refusals, [])
        self.assertTrue(api.quality(state)["release_ready"])

    def test_a_quality_gate_finding_is_closed_only_on_a_newer_build(self):
        case, world, api, state = self.recover(
            "performance-regression",
            {"performance-engineer": {"fixes": ["performance-regression"]}})
        # WS-9: a performance criterion is the performance engineer's, by its own id.
        self.assertEqual(world.visits, ["performance-engineer"])
        self.assert_measured_again(api, state, case)
        quality_reports = self.every(api, state, "quality-report")
        failing, passing = quality_reports[0], quality_reports[-1]
        finding = next(f for f in passing["findings"] if f["criterion"] == "floor.performance")
        self.assertEqual(finding["status"], "closed")
        self.assertEqual(finding["closed_on"]["commit"], passing["build"]["commit"])
        self.assertNotEqual(finding["closed_on"]["commit"], failing["build"]["commit"])
        self.assertEqual(passing["regression"]["previous"]["commit"], failing["build"]["commit"])
        state = self.decide(api, state)
        self.assertEqual(state.status, RunStatus.COMPLETED, self.story(api, state))
        self.assertTrue(api.quality(state)["release_ready"])


# -- D. anti-gaming ----------------------------------------------------------------------------

class AntiGaming(_Case):
    def test_evidence_about_an_older_commit_is_stale_and_blocks(self):
        """A new build after QA: the reports about the old commit no longer clear it - not at
        G4, not at the quality gate, not at release."""
        world = self.world("arcade-2d")
        api = self.api(world)
        state = self.to_g4(api)
        old = self.newest(api, state, "quality-report")
        state = api.run(RunRequest(run_id=state.run_id, scope="develop", force=True))
        self.assertEqual(self.steps(state)[-1], "develop")
        # The gate asked again on the old evidence stops at the floor.
        state = api.run(RunRequest(run_id=state.run_id, scope="prototype-review"))
        self.assertEqual(state.status, RunStatus.BLOCKED, self.story(api, state))
        self.assertEqual(state.blocked_reason["kind"], quality.FLOOR)
        # The quality gate itself, shown the new build beside the old build's reports.
        state = api.run(RunRequest(run_id=state.run_id, scope="quality-gate", force=True))
        report = self.newest(api, state, "quality-report")
        self.assertEqual(report["verdict"], "BLOCKED", self.story(api, state))
        self.assertIn("another build", report["blocked_reason"])
        new_dev = self.newest(api, state, "prototype-report")["build_ref"]["commit_sha"]
        self.assertNotEqual(new_dev, old["build"]["development_commit"])
        stale = [e for e in report["evidence"] if e["status"] == "stale"]
        self.assertTrue(stale, report["evidence"])
        self.assertEqual(report["dimensions"], [])  # nothing scored on another build's reports
        codes = [r.code for r in self.release_refusals(api, state, gates_passed=("G4",))]
        self.assertTrue({"quality-not-passed", "stale-qa-report"} & set(codes), codes)
        self.assertFalse(api.quality(state)["release_ready"])

    def test_a_benchmark_edited_mid_run_does_not_apply_to_it(self):
        """The bars a run is held to are the ones it started under: a lowered bar in the live
        file (here: near-identical levels allowed at 50%) neither lets the run's duplicate
        level through nor reaches its quality gate; the next run is held to the edit."""
        live = os.path.join(self.scratch, "live-benchmark.yaml")
        with open(os.path.join(paths.REFERENCE, "quality-benchmark.yaml"),
                  encoding="utf-8") as handle:
            text = handle.read()
        edited = text.replace("max_repeated_layout_ratio: {release: 0.1",
                              "max_repeated_layout_ratio: {release: 0.5")
        self.assertNotEqual(edited, text)
        with open(live, "w", encoding="utf-8") as handle:
            handle.write(edited)

        # The run started before the edit: its pin is the shipped benchmark.
        world = self.world("platformer-content", ["duplicate-level"])
        api = self.api(world)
        with mock.patch("wgf_sufficiency.audit.BENCHMARK_PATH", live):
            state = self.start(api)
        self.assertEqual(state.status, RunStatus.BLOCKED, self.story(api, state))
        report = self.newest(api, state, "content-sufficiency-report")
        self.assert_names("content-sufficiency-report", report, ["content.structure"])
        self.assertIn("0.1", json.dumps(next(c for c in report["checks"]
                                             if c["id"] == "content.structure")["expected"]))

        # A run started after the edit pins the edited file, and is held to it.
        root = os.path.join(self.scratch, "factory")
        for relpath in load_definition("new-game").pinned_references:
            target = os.path.join(root, *relpath.split("/"))
            os.makedirs(os.path.dirname(target), exist_ok=True)
            if relpath.endswith("quality-benchmark.yaml"):
                shutil.copyfile(live, target)
            else:
                shutil.copyfile(os.path.join(paths.ROOT, *relpath.split("/")), target)
        later = self.api(self.world("platformer-content", ["duplicate-level"]), store="later")
        with mock.patch.object(references, "paths", types.SimpleNamespace(ROOT=root)):
            again = self.start(later)
            self.assertEqual(again.status, RunStatus.WAITING, self.story(later, again))
        structure = next(c for c in self.newest(later, again, "content-sufficiency-report")
                         ["checks"] if c["id"] == "content.structure")
        self.assertEqual(structure["status"], "PASS")

    def test_a_pinned_reference_edited_in_the_run_blocks(self):
        """The run's pinned copies are checked against the digests it recorded at the start:
        a bar lowered inside the run directory blocks the step that reads it."""
        for relpath, step_id, artifact_type in (
                ("quality-floor.yaml", "quality-gate", "quality-report"),
                ("quality-benchmark.yaml", "content-sufficiency",
                 "content-sufficiency-report")):
            with self.subTest(reference=relpath):
                api = self.api(self.world("arcade-2d"), store=f"store-{step_id}")
                state = self.to_g4(api)
                pinned = os.path.join(api.store.run_dir(state.run_id), references.DIRECTORY,
                                      "core", "reference", relpath)
                with open(pinned, "a", encoding="utf-8") as handle:
                    handle.write("\n# lowered in the run\n")
                state = api.run(RunRequest(run_id=state.run_id, scope=step_id, force=True))
                report = self.newest(api, state, artifact_type)
                self.assertEqual(report["verdict"], "BLOCKED")
                self.assertIn("edited after the start", report["blocked_reason"])
                # Nothing downstream of it starts.
                with self.assertRaisesRegex(EngineError, "unmet upstream"):
                    api.run(RunRequest(run_id=state.run_id, scope="release"))

    def test_a_rubric_edited_mid_run_does_not_apply_to_it(self):
        """visual-qa reads the rubric the run pinned: a pass bar lowered in the live file after
        the start leaves the running build held to the pinned one, and a pinned copy edited in
        the run blocks visual-qa, which starts nothing downstream."""
        with open(os.path.join(paths.REFERENCE, "visual-qa-rubric.yaml"),
                  encoding="utf-8") as handle:
            text = handle.read()
        live = os.path.join(self.scratch, "live-rubric.yaml")
        with open(live, "w", encoding="utf-8") as handle:
            handle.write(text.replace("\npass_bar: 3\n", "\npass_bar: 1\n"))
        api = self.api(self.world("arcade-2d"))
        with mock.patch("wgf_visualqa.rubric.RUBRIC_PATH", live):
            state = self.to_g4(api)
        report = self.newest(api, state, "visual-qa-report")
        self.assertEqual(report["rubric"]["pass_bar"], 3)
        self.assertIn(references.DIRECTORY, report["rubric"]["path"].replace("\\", "/"))
        pinned = os.path.join(api.store.run_dir(state.run_id), references.DIRECTORY, "core",
                              "reference", "visual-qa-rubric.yaml")
        with open(pinned, "a", encoding="utf-8") as handle:
            handle.write("\n# lowered in the run\n")
        state = api.run(RunRequest(run_id=state.run_id, scope="visual-qa", force=True))
        self.assertEqual(state.status, RunStatus.BLOCKED, self.story(api, state))
        self.assertIn("edited after the start", state.message)
        with self.assertRaisesRegex(EngineError, "unmet upstream"):
            api.run(RunRequest(run_id=state.run_id, scope="release"))

    def test_tier_mvp_is_development_never_release(self):
        world = self.world("arcade-2d")
        api = self.api(world, {"strategy": {"quality_tier": "mvp"}})
        state = self.to_g4(api)
        self.assertEqual(state.params["quality"]["class"], "development")
        state = self.decide(api, state)
        self.assertEqual(state.status, RunStatus.COMPLETED, self.story(api, state))
        readiness = api.quality(state)
        self.assertEqual(readiness["class"], "development")
        self.assertFalse(readiness["release_ready"])
        self.assertEqual({r.quality for refs in state.artifacts.values() for r in refs},
                         {"development"})

    def test_a_downgraded_configuration_is_development(self):
        world = self.world("arcade-2d")
        api = self.api(world, {"sdk": {"run_tests": False}})
        state = self.to_g4(api)
        self.assertEqual(state.params["quality"]["class"], "development")
        self.assertTrue(state.params["quality"]["reasons"])
        state = self.decide(api, state)
        readiness = api.quality(state)
        self.assertFalse(readiness["release_ready"])

    def test_seed_stage_progress_is_measured_on_the_build(self):
        """WS-13 gap: the puzzle, platformer, strategy and simulation seeds keep only stage
        progress, which playability SKIPPED, so the floor blocked a clean release build that
        no developer visit could fix. The probe reports the unit reached
        (content.unit_index): stage progress is measured on it, and the run - on the seed's
        own meta loop, nothing added - reaches G4."""
        for genre in ("puzzle-casual", "platformer-content", "strategy-content",
                      "simulation-systems"):
            with self.subTest(genre=genre):
                design = design_of(GENRES[genre]["family"])
                kinds = {p["kind"] for p in design["build_spec"]["depth"]["meta_loop"]
                         ["persists"] if p["tier"] == "mvp"}
                self.assertIn("stage-progress", kinds)
                api = self.api(self.world(genre), store=f"store-{genre}")
                state = self.to_g4(api)
                play = self.newest(api, state, "playability-report")
                persists = [c for c in play["checks"] if c["id"] == "progression.persists"]
                self.assertTrue(persists)
                for check in persists:
                    self.assertEqual(check["status"], "PASS", check["summary"])
                    self.assertIn("content.unit_index", check["measured"])
                self.assertEqual(play["skipped_checks"], [])

    def test_a_skipped_check_is_not_green(self):
        """A design whose meta loop keeps nothing a probe can report: the playability step
        skips progression.persists and passes - and the quality floor does not."""
        world = self.world("puzzle-casual", unreported_persistence=True)
        api = self.api(world)
        state = self.start(api)
        self.assertEqual(state.status, RunStatus.BLOCKED, self.story(api, state))
        play = self.newest(api, state, "playability-report")
        self.assertEqual(play["verdict"], "PASS")
        self.assertIn("progression.persists", [s["id"] for s in play["skipped_checks"]])
        report = self.newest(api, state, "quality-report")
        self.assertEqual(report["verdict"], "FAIL")
        self.assert_names("quality-report", report,
                          ["floor.content_checks_measured", "floor.progression_persists"])
        self.assertNotIn("prototype-review", self.steps(state))

    def test_an_unmeasured_check_is_not_green(self):
        """A probe that names no entity kind: element variety cannot be counted on the build.
        The play-probe contract requires the kind of every content-role entity while a unit
        is in play, so the probe itself fails - unmeasured is never a pass."""
        world = self.world("arcade-2d", ["kinds-omitted"])
        api = self.api(world)
        state = self.start(api)
        self.assertEqual(state.status, RunStatus.BLOCKED, self.story(api, state))
        play = self.newest(api, state, "playability-report")
        self.assert_names("playability-report", play, ["desktop:probe.valid",
                                                       "mobile:probe.valid"])
        self.assertNotIn("prototype-review", self.steps(state))

    def test_content_deleted_after_qa_is_measured_again(self):
        world = self.world("platformer-content")
        api = self.api(world)
        state = self.to_g4(api)
        # The developer deletes content after every gate passed the build.
        world.defects.add("remove-content")
        state = api.run(RunRequest(run_id=state.run_id, scope="develop", force=True))
        # G4 cannot be passed on the old build's reports, and nothing releases.
        blocked = api.run(RunRequest(run_id=state.run_id, scope="prototype-review"))
        self.assertEqual(blocked.status, RunStatus.BLOCKED, self.story(api, blocked))
        self.assertEqual(blocked.blocked_reason["kind"], quality.FLOOR)
        with self.assertRaisesRegex(EngineError, "unmet upstream"):
            api.run(RunRequest(run_id=state.run_id, scope="release"))
        self.assertIsNone(api.store.load(state.run_id).latest_of_type("release-manifest"))
        # Going on measures the new build, and its content is short.
        state = api.run(RunRequest(run_id=state.run_id, scope="new-game"))
        self.assertEqual(state.status, RunStatus.BLOCKED, self.story(api, state))
        report = self.newest(api, state, "content-sufficiency-report")
        self.assert_names("content-sufficiency-report", report, ["content.units_shipped"])
        self.assertFalse(api.quality(state)["release_ready"])


if __name__ == "__main__":
    unittest.main()

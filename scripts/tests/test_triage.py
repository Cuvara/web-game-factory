"""Specialist routing (WS-8): failures become quality findings, routed to the owner.

The triage step (scripts/wgf_triage) normalizes the current build's failing reports - and a
person's typed findings at G4 - into quality findings (core/artifacts/shared/
quality-finding.schema.json), groups them by the specialist that owns each dimension
(core/reference/specialist-routing.yaml) and routes one group per visit. These tests hold:

  * every producer normalizes: playability, production-quality, visual-qa, review,
    verification, listing-validation, G4's typed findings;
  * the audit's cases route to the right specialist (docs/quality-gap-audit-2026-10.md
    section 2.2): a visual-qa environment finding to the environment artist (I-18/I-19), a
    content shortfall to the level designer (I-03/I-15), canvas UI a player cannot reach to
    UI (I-01), an audio finding to audio, store copy to the copywriter (I-23), a scope
    increase to design (I-06);
  * the develop brief of a specialist visit carries only the findings it owns, its craft
    playbooks and its writable scope;
  * the loop limits stop a specialist that never resolves its findings with a truthful
    BLOCKED, named;
  * the ledger records what the gates measured of each specialist visit.

    python -m unittest scripts.tests.test_triage
"""

import hashlib
import json
import os
import shutil
import sys
import tempfile
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
for _path in (SCRIPTS, HERE):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from wgf_develop import brief as briefs  # noqa: E402
from wgf_develop import specialist as specialists  # noqa: E402
from wgf_triage import Routing, from_requests, normalize  # noqa: E402
from wgf_triage.step import TriageStep, validate_requests  # noqa: E402
from wgflib import paths  # noqa: E402
from wgflib.workflow.api import RunRequest, WorkflowAPI  # noqa: E402
from wgflib.workflow.config import FactoryConfig  # noqa: E402
from wgflib.workflow.contracts import ArtifactContracts  # noqa: E402
from wgflib.workflow.definition import load_definition  # noqa: E402
from wgflib.workflow.model import RunStatus  # noqa: E402
from wgflib.yamllite import load_file  # noqa: E402

COMMIT = "c" * 40
ROUTING = Routing.load()
RUBRIC = load_file(os.path.join(paths.REFERENCE, "visual-qa-rubric.yaml"))
DESIGN_3D = {"title_id": "demo", "engine": {"dimension": "3d", "type": "threejs"}}
DESIGN_2D = {"title_id": "demo", "engine": {"dimension": "2d", "type": "pixijs"}}


def playability(*checks, verdict="FAIL"):
    return {"title_id": "demo", "commit": COMMIT, "verdict": verdict,
            "provenance": {"artifact_id": "playability-report-demo-1"},
            "frames": [{"project": "mobile", "id": "f1", "path": "playability/1-1/f1.png"}],
            "checks": [dict({"project": "mobile", "status": "FAIL", "required": True,
                             "summary": f"{cid} failed"}, id=cid, **extra)
                       for cid, extra in checks]}


def visual_qa(*, findings=(), failed=(), scores=None, states=(), verdict="FAIL"):
    return {"title_id": "demo", "commit": COMMIT, "verdict": verdict,
            "rubric": {"version": "1.2.0", "sha256": "x", "pass_bar": 3},
            "scores": scores or {}, "score_reasons": {"environment": "an empty grey plane"},
            "findings": list(findings), "failed": list(failed), "states": list(states),
            "routes": ["develop"]}


class Ref:
    def __init__(self, kind, seq):
        self.id, self.type, self.seq, self.content_hash = f"{kind}-v{seq}", kind, seq, None


class Inputs:
    def __init__(self, docs, seqs=None):
        self.docs = docs
        self.refs = {k: Ref(k, (seqs or {}).get(k, 10)) for k in docs}

    def __contains__(self, k):
        return k in self.docs

    def load(self, k):
        return self.docs[k]


class Log:
    def __init__(self):
        self.lines = []

    def __getattr__(self, name):
        return lambda *a, **k: self.lines.append((name, a, k))


ON = load_definition("new-game").step("triage").on


def run_triage(docs, seqs=None, entered="visual-qa.develop", run_dir=None, on=ON):
    context = types.SimpleNamespace(entered_by=entered, run_dir=run_dir, logger=Log(),
                                    execution=1, visit=1, project_id="demo")
    step = TriageStep(types.SimpleNamespace(id="triage", params={}, on=dict(on)))
    result = step.execute(Inputs(docs, seqs), context)
    for artifact in result.artifacts:
        problems = ArtifactContracts()("triage-report", artifact.content)
        assert problems == [], problems
    return result


class Normalization(unittest.TestCase):
    """Each producer's failures become findings with the right dimension, owner and route."""

    def by_id(self, findings):
        return {f["id"]: f for f in findings}

    def test_a_content_shortfall_goes_to_the_level_designer(self):
        found = normalize("playability-report", playability(
            ("content.variety", {"expected": {"min_dimensions_changed": 2},
                                 "measured": {"changed": 0}, "frames": ["f1"]})), ROUTING)
        finding = found[0]
        self.assertEqual(finding["id"], "playability-report:content.variety@mobile")
        self.assertEqual((finding["dimension"], finding["owner"], finding["route"]),
                         ("content", "level-designer", "develop"))
        self.assertEqual(finding["bar"], {"min_dimensions_changed": 2})
        self.assertIn("playability/1-1/f1.png", finding["evidence_refs"])
        self.assertIn("playability plays the next build", finding["task"]["acceptance"][0])

    def test_content_sufficiency_findings_route_to_level_design_or_design(self):
        report = {"verdict": "FAIL", "routes": ["develop", "design-gap"], "findings": [
            {"id": "content.elements_distinct", "check": "content.elements_distinct",
             "dimension": "content", "severity": "blocker", "summary": "5 elements, bar 8",
             "observed": 5, "bar": 8, "owner": "level-design", "route": "develop",
             "evidence": ["public/content/units.json"]},
            {"id": "content.units_total", "check": "content.units_total",
             "dimension": "level-design", "severity": "blocker",
             "summary": "the design states 6 units; the tier asks 12", "observed": 6,
             "bar": 12, "owner": "game-design", "route": "design-gap",
             "design_gap": {"field": "build_spec.content.units", "question": "Which 6 more?",
                            "assumed": None, "severity": "blocking"}},
            {"id": "content.difficulty_new_skills", "check": "content.difficulty_new_skills",
             "dimension": "difficulty", "severity": "minor", "summary": "late units only scale",
             "owner": "level-design", "route": "develop"}]}
        found = self.by_id(normalize("content-sufficiency-report", report, ROUTING))
        built = found["content-sufficiency-report:content.elements_distinct"]
        self.assertEqual((built["owner"], built["route"], built["measured"], built["bar"]),
                         ("level-designer", "develop", 5, 8))
        gap = found["content-sufficiency-report:content.units_total"]
        self.assertEqual((gap["owner"], gap["route"], gap["task"]["design_field"]),
                         ("level-designer", "design", "build_spec.content.units"))
        self.assertEqual(found["content-sufficiency-report:content.difficulty_new_skills"]
                         ["owner"], "encounter-designer")
        # Through triage: the design gap goes to design first and alone.
        result = run_triage({"game-design": DESIGN_2D,
                             "prototype-report": {"title_id": "demo", "iteration": 2,
                                                  "build_ref": {"commit_sha": COMMIT}},
                             "content-sufficiency-report": report},
                            seqs={"prototype-report": 5, "content-sufficiency-report": 9},
                            entered="content-sufficiency.design-gap")
        content = result.artifacts[0].content
        self.assertEqual(result.route, "design")
        self.assertEqual([g["label"] for g in content["deferred"]],
                         ["level-designer", "encounter-designer"])

    def test_canvas_ui_a_player_cannot_reach_goes_to_ui(self):
        found = normalize("playability-report", playability(("restart.works", {})), ROUTING)
        self.assertEqual(found[0]["owner"], "ui")

    def test_a_production_art_failure_is_the_artist_of_the_designs_dimension(self):
        report = {"verdict": "FAIL", "checks": [
            {"id": "assets.used", "project": "desktop", "status": "FAIL", "required": True,
             "summary": "player drawn from no asset", "route": "develop"},
            {"id": "audio.plays", "status": "FAIL", "required": True,
             "summary": "no cue played", "route": "develop"},
            {"id": "ui.targets", "status": "PASS", "required": True, "summary": "ok",
             "route": "develop"}]}
        three = self.by_id(normalize("production-quality-report", report, ROUTING,
                                     dimension_3d=True))
        two = self.by_id(normalize("production-quality-report", report, ROUTING))
        self.assertEqual(three["production-quality-report:assets.used@desktop"]["owner"],
                         "environment-artist")
        self.assertEqual(two["production-quality-report:assets.used@desktop"]["owner"],
                         "artist-2d")
        self.assertEqual(two["production-quality-report:audio.plays"]["owner"],
                         "audio-designer")
        self.assertEqual(len(two), 2)  # a passing check is no finding

    def test_a_visual_qa_environment_finding_goes_to_the_environment_artist(self):
        report = visual_qa(
            scores={"environment": 2, "ui_polish": 4},
            failed=["score:environment", "state:mobile/gameplay:lighting_materials_coherent"],
            states=[{"state": "gameplay", "viewport": "mobile", "captured": True,
                     "frames": ["vqa/f.png"], "answers": {"lighting_materials_coherent": False},
                     "comment": "black ground bar"}])
        found = self.by_id(normalize("visual-qa-report", report, ROUTING, dimension_3d=True,
                                     rubric=RUBRIC))
        env = found["visual-qa-report:score:environment"]
        self.assertEqual((env["dimension"], env["owner"]), ("environment-3d", "environment-artist"))
        self.assertEqual(env["route"], "assets")  # the rubric's route for the dimension
        self.assertEqual((env["measured"], env["bar"]), (2, 3))
        light = found["visual-qa-report:state:gameplay:lighting_materials_coherent@mobile"]
        self.assertEqual((light["dimension"], light["owner"], light["route"]),
                         ("lighting-material", "environment-artist", "develop"))
        self.assertEqual(light["evidence_refs"][0], "vqa/f.png")

    def test_visual_qa_majors_travel_with_the_failure(self):
        report = visual_qa(findings=[
            {"id": "default-buttons", "severity": "blocker", "category": "ui", "frame": None,
             "summary": "grey bevelled buttons", "route": "develop"},
            {"id": "hud-crowded", "severity": "major", "category": "ui", "frame": "x.png",
             "summary": "HUD overlaps the play", "route": "develop"}],
            failed=["finding:default-buttons"])
        found = self.by_id(normalize("visual-qa-report", report, ROUTING, rubric=RUBRIC))
        self.assertEqual(found["visual-qa-report:finding:hud-crowded"]["severity"], "major")
        self.assertEqual({f["owner"] for f in found.values()}, {"ui"})

    def test_review_and_verification_blockers_are_the_generalists(self):
        review = {"verdict": "request-changes", "blockers": [
            {"id": "B1", "file": "src/game/loop.ts", "line": 4, "summary": "dt ignored",
             "severity": "blocker"}]}
        qa = {"verdict": "fail", "suites": [{"name": "e2e", "passed": 3, "failed": 1}],
              "blocking_defects": [
                  {"id": "D1", "severity": "critical", "summary": "no restart", "repro": "x"},
                  {"id": "D2", "severity": "major", "summary": "ad not muted", "repro": "y",
                   "platform_id": "yandex"}]}
        r = normalize("review-report", review, ROUTING)[0]
        self.assertEqual((r["owner"], r["route"]), ("gameplay", "develop"))
        self.assertIn("src/game/loop.ts", r["evidence_refs"])
        q = self.by_id(normalize("qa-report", qa, ROUTING))
        self.assertEqual(q["qa-report:d1"]["owner"], "gameplay")
        self.assertEqual(q["qa-report:d2"]["owner"], "sdk")
        self.assertEqual(q["qa-report:suite:e2e"]["bar"], {"failed": 0})

    def test_a_copy_finding_goes_to_the_copywriter(self):
        report = {"verdict": "FAIL", "checks": [
            {"id": "grounding.copy", "section": "grounding", "status": "FAIL", "required": True,
             "summary": "copy says six courses; the build ships twelve", "locale": "en"},
            {"id": "screenshots.count", "section": "screenshots", "status": "FAIL",
             "required": True, "summary": "two screenshots"}]}
        found = self.by_id(normalize("listing-validation-report", report, ROUTING))
        copy = found["listing-validation-report:grounding.copy@en"]
        self.assertEqual((copy["dimension"], copy["owner"], copy["route"]),
                         ("store-copy", "copywriter", "listing"))
        self.assertEqual(found["listing-validation-report:screenshots.count"]["owner"],
                         "artist-2d")

    def test_g4_typed_findings_route_like_a_gates(self):
        requests = [
            {"dimension": "audio", "severity": "major", "summary": "no music",
             "task": {"change": "add a looping track", "acceptance": ["music plays"]}},
            {"id": "more-worlds", "dimension": "content", "severity": "blocker",
             "summary": "one world of six corridors", "route": "design",
             "task": {"change": "three worlds of four courses", "acceptance": ["12 units"],
                      "design_field": "build_spec.content"}}]
        self.assertEqual(validate_requests(requests), [])
        found = from_requests(requests, ROUTING)
        self.assertEqual((found[0]["owner"], found[0]["route"]), ("audio-designer", "develop"))
        self.assertEqual((found[1]["id"], found[1]["owner"], found[1]["route"]),
                         ("decision-record:more-worlds", "level-designer", "design"))
        self.assertTrue(validate_requests([{"dimension": "vibes", "severity": "major",
                                            "summary": "x", "task": {"change": "y",
                                                                     "acceptance": ["z"]}}]))


class RoutingData(unittest.TestCase):

    def test_every_dimension_has_exactly_one_owner_with_a_charter_and_playbooks(self):
        self.assertEqual(ROUTING.problems(), [])
        with open(os.path.join(paths.ARTIFACTS, "shared", "quality-finding.schema.json"),
                  encoding="utf-8") as handle:
            schema = json.load(handle)
        self.assertEqual(list(ROUTING.dimensions), schema["$defs"]["dimension"]["enum"])
        roles = load_file(os.path.join(paths.CORE, "roles", "roles.yaml"))["roles"]
        for role in ROUTING.order:
            self.assertEqual(roles[role]["kind"], "implementer", role)
            self.assertTrue(roles[role].get("reads"), role)

    def test_every_develop_specialist_is_routed_by_the_workflow_and_budgeted(self):
        definition = load_definition("new-game")
        triage, develop = definition.step("triage"), definition.step("develop")
        for spec in ROUTING.specialists:
            if spec["route"] == "develop":
                self.assertEqual(triage.on.get(spec["role"]), "develop", spec["role"])
                self.assertIn(f"triage.{spec['role']}", develop.max_visits_by_route)
            else:
                self.assertNotIn(spec["role"], triage.on)
        self.assertEqual(develop.on.get("next-specialist"), "triage")
        self.assertEqual((triage.on["design"], triage.on["assets"]), ("design", "assets"))
        # Every gate's failure goes through triage; none straight to develop.
        for step in definition.steps:
            if step.id in ("triage", "develop", "greybox", "greybox-playability"):
                continue
            self.assertNotIn("develop", step.on.values(), step.id)
        self.assertEqual(definition.step("prototype-review").on["iterate"], "triage")
        # develop's own limit is never the one a loop meets first.
        self.assertGreaterEqual(develop.max_visits,
                                1 + sum(develop.max_visits_by_route.values()))

    def test_groups_are_in_visit_order_one_design_or_assets_group(self):
        mk = lambda fid, dim, route=None: {  # noqa: E731
            "id": fid, "dimension": dim, "severity": "major", "owner": ROUTING.owner(dim),
            "route": route or ROUTING.route_of(ROUTING.owner(dim))}
        groups = ROUTING.groups([mk("a", "ui"), mk("b", "environment-3d"), mk("c", "content"),
                                 mk("d", "art-2d", "assets"), mk("e", "content", "design"),
                                 mk("f", "store-copy")])
        self.assertEqual([g["label"] for g in groups],
                         ["design", "assets", "level-designer", "environment-artist", "ui",
                          "listing"])
        ui = groups[4]
        self.assertIn("core/craft/game-ui-kit.md", ui["playbooks"])
        self.assertIn("index.html", ui["writable_paths"])


class TriageStepRouting(unittest.TestCase):

    def setUp(self):
        self.run_dir = tempfile.mkdtemp(prefix="wgf-triage-")
        self.addCleanup(shutil.rmtree, self.run_dir, ignore_errors=True)

    def proto(self, specialist=None, iteration=2):
        body = {"title_id": "demo", "iteration": iteration,
                "provenance": {"artifact_id": f"prototype-report-demo-{iteration}"},
                "build_ref": {"commit_sha": COMMIT}}
        if specialist:
            body["specialist"] = specialist
        return body

    def vqa_two_owners(self):
        return visual_qa(
            scores={"environment": 4, "ui_polish": 2},
            findings=[{"id": "dark-ground", "severity": "blocker", "category": "readability",
                       "frame": None, "summary": "black ground bar", "route": "develop"}],
            failed=["finding:dark-ground", "score:ui_polish"])

    def test_the_first_build_continues_to_develop_with_nothing_to_route(self):
        result = run_triage({"game-design": DESIGN_3D}, entered="assets.success")
        self.assertEqual((result.outcome, result.route), ("SUCCESS", None))
        self.assertEqual(result.artifacts[0].content["verdict"], "clear")

    def test_one_build_two_specialists_visit_in_order(self):
        docs = {"game-design": DESIGN_3D, "prototype-report": self.proto(),
                "visual-qa-report": self.vqa_two_owners()}
        result = run_triage(docs, seqs={"prototype-report": 5, "visual-qa-report": 8})
        report = result.artifacts[0].content
        self.assertEqual((result.outcome, result.route), ("SUCCESS", "environment-artist"))
        self.assertEqual(report["selected"]["findings"],
                         ["visual-qa-report:finding:dark-ground"])
        self.assertEqual([g["label"] for g in report["pending"]], ["ui"])
        # develop returns next-specialist; no gate has measured since: the next group.
        docs["triage-report"] = report
        result = run_triage(docs, seqs={"prototype-report": 11, "visual-qa-report": 8,
                                        "triage-report": 9},
                            entered="develop.next-specialist")
        report = result.artifacts[0].content
        self.assertEqual((result.route, report["mode"]), ("ui", "continued"))
        self.assertEqual(report["selected"]["findings"], ["visual-qa-report:score:ui_polish"])
        self.assertEqual(report["pending"], [])
        self.assertEqual(report["source"], "visual-qa.develop")

    def test_a_report_of_an_earlier_build_says_nothing(self):
        docs = {"game-design": DESIGN_2D, "prototype-report": self.proto(),
                "visual-qa-report": self.vqa_two_owners(),
                "playability-report": playability(("restart.works", {}))}
        result = run_triage(docs, seqs={"playability-report": 3, "prototype-report": 5,
                                        "visual-qa-report": 8})
        owners = {f["owner"] for f in result.artifacts[0].content["findings"]}
        self.assertNotIn("ui", {f["owner"] for f in result.artifacts[0].content["findings"]
                                if f["source"]["producer"] == "playability-report"})
        self.assertEqual(owners, {"artist-2d", "ui"})

    def test_findings_held_by_every_route_stop_for_a_person(self):
        docs = {"game-design": DESIGN_2D, "prototype-report": self.proto(),
                "listing-validation-report": {"verdict": "FAIL", "checks": [
                    {"id": "grounding.copy", "section": "grounding", "status": "FAIL",
                     "required": True, "summary": "six courses"}]}}
        result = run_triage(docs, seqs={"prototype-report": 5, "listing-validation-report": 8},
                            entered="verify.fail")
        self.assertEqual(result.outcome, "BLOCKED")
        report = result.artifacts[0].content
        self.assertEqual(report["verdict"], "held")
        self.assertIn("store-listing after G4", report["held"][0]["reason"])

    def g4(self, requests, tamper=False):
        raw = json.dumps(requests).encode("utf-8")
        digest = hashlib.sha256(raw).hexdigest()
        os.makedirs(os.path.join(self.run_dir, "findings"))
        with open(os.path.join(self.run_dir, "findings", "f.json"), "wb") as handle:
            handle.write(raw + (b" " if tamper else b""))
        return {"decision": "iterate", "gate_id": "G4",
                "provenance": {"artifact_id": "decision-record-demo-1"},
                "rationale": f"the world is empty\nfindings: findings/f.json sha256:{digest}"}

    def test_g4_iterate_routes_typed_findings_to_their_owners(self):
        decision = self.g4([
            {"dimension": "audio", "severity": "major", "summary": "silent",
             "task": {"change": "add music", "acceptance": ["music plays"]}},
            {"dimension": "environment-3d", "severity": "blocker", "summary": "empty world",
             "task": {"change": "dress the world", "acceptance": ["props on every course"]}}])
        docs = {"game-design": DESIGN_3D, "prototype-report": self.proto(),
                "decision-record": decision}
        result = run_triage(docs, seqs={"prototype-report": 5, "decision-record": 9},
                            entered="prototype-review.iterate", run_dir=self.run_dir)
        report = result.artifacts[0].content
        self.assertEqual(result.route, "environment-artist")
        self.assertEqual([g["label"] for g in report["pending"]], ["audio-designer"])

    def test_g4_findings_altered_after_the_decision_are_refused(self):
        decision = self.g4([{"dimension": "audio", "severity": "major", "summary": "silent",
                             "task": {"change": "m", "acceptance": ["n"]}}], tamper=True)
        result = run_triage({"game-design": DESIGN_3D, "prototype-report": self.proto(),
                             "decision-record": decision},
                            seqs={"prototype-report": 5, "decision-record": 9},
                            entered="prototype-review.iterate", run_dir=self.run_dir)
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertIn("changed after the decision", result.message)

    def test_g4_iterate_without_findings_is_the_generalists_with_the_note(self):
        result = run_triage({"game-design": DESIGN_2D, "prototype-report": self.proto(),
                             "decision-record": {"decision": "iterate", "rationale": "dull"}},
                            seqs={"prototype-report": 5, "decision-record": 9},
                            entered="prototype-review.iterate", run_dir=self.run_dir)
        report = result.artifacts[0].content
        self.assertEqual(result.route, "gameplay")
        self.assertEqual(report["findings"][0]["task"]["change"], "dull")

    def test_a_scope_increase_goes_to_design_first_and_alone(self):
        decision = self.g4([
            {"dimension": "content", "severity": "blocker", "summary": "one world",
             "route": "design", "task": {"change": "three worlds", "acceptance": ["12 units"]}},
            {"dimension": "ui", "severity": "minor", "summary": "small font",
             "task": {"change": "bigger", "acceptance": ["16px"]}}])
        result = run_triage({"game-design": DESIGN_2D, "prototype-report": self.proto(),
                             "decision-record": decision},
                            seqs={"prototype-report": 5, "decision-record": 9},
                            entered="prototype-review.iterate", run_dir=self.run_dir)
        report = result.artifacts[0].content
        self.assertEqual(result.route, "design")
        self.assertEqual([g["label"] for g in report["deferred"]], ["ui"])
        self.assertEqual(report["pending"], [])
        from wgf_design.step import triage_gaps
        gaps = triage_gaps(report)
        self.assertEqual((gaps[0]["field"], gaps[0]["severity"]),
                         ("build_spec.content", "blocking"))

    def test_assets_work_already_done_is_not_routed_again(self):
        report = visual_qa(findings=[
            {"id": "flat-player", "severity": "blocker", "category": "assets", "frame": None,
             "summary": "player is a cube", "route": "assets"},
            {"id": "buttons", "severity": "blocker", "category": "ui", "frame": None,
             "summary": "default buttons", "route": "develop"}],
            failed=["finding:flat-player", "finding:buttons"])
        result = run_triage({"game-design": DESIGN_2D, "prototype-report": self.proto(),
                             "visual-qa-report": report, "asset-manifest": {"items": []}},
                            seqs={"prototype-report": 5, "visual-qa-report": 8,
                                  "asset-manifest": 9}, entered="assets.success")
        content = result.artifacts[0].content
        self.assertEqual(result.route, "ui")
        self.assertEqual([f["id"] for f in content["findings"]],
                         ["visual-qa-report:finding:buttons"])

    def test_a_g4_asset_remake_goes_to_assets_once_then_on_to_develop(self):
        decision = self.g4([
            {"dimension": "art-2d", "severity": "major", "summary": "the player is a blob",
             "route": "assets", "assets": ["player"],
             "task": {"change": "a sprite with a silhouette", "acceptance": ["reads as a fox"]}},
            {"dimension": "ui", "severity": "minor", "summary": "small font",
             "task": {"change": "bigger", "acceptance": ["16px"]}}])
        docs = {"game-design": DESIGN_2D, "prototype-report": self.proto(),
                "decision-record": decision, "asset-manifest": {"items": []}}
        seqs = {"asset-manifest": 3, "prototype-report": 5, "decision-record": 9}
        result = run_triage(docs, seqs=seqs, entered="prototype-review.iterate",
                            run_dir=self.run_dir)
        first = result.artifacts[0].content
        self.assertEqual(result.route, "assets")
        self.assertEqual([g["label"] for g in first["pending"]], ["ui"])
        # assets made it again and continues to triage: the UI visit, never assets again.
        docs["triage-report"] = first
        result = run_triage(docs, seqs=dict(seqs, **{"triage-report": 10, "asset-manifest": 11}),
                            entered="assets.success", run_dir=self.run_dir)
        self.assertEqual(result.route, "ui")
        # and the assets step reads that triage-report's selected findings as its feedback
        from wgf_assets import feedback
        selected = feedback._select([("visual-qa-report", visual_qa(verdict="PASS")),
                                     ("triage-report", first)], "triage.assets")
        self.assertEqual([kind for kind, _ in selected], ["triage-report"])
        self.assertEqual(feedback._select([("triage-report", first)], "visual-qa.assets"), [])

    def test_the_ledger_records_what_the_gate_measured_of_a_specialist_visit(self):
        visit = {"role": "environment-artist", "sessions": 1, "cost_usd": 4.5,
                 "findings": ["visual-qa-report:finding:dark-ground",
                              "visual-qa-report:score:environment"]}
        # The gate measured the specialist's build: dark-ground is gone, environment is not.
        report = visual_qa(scores={"environment": 2}, failed=["score:environment"])
        result = run_triage({"game-design": DESIGN_3D, "prototype-report": self.proto(visit),
                             "visual-qa-report": report},
                            seqs={"prototype-report": 12, "visual-qa-report": 15})
        entry = result.artifacts[0].content["ledger"][0]
        self.assertEqual(entry["specialist"], "environment-artist")
        self.assertEqual(entry["resolved"], ["visual-qa-report:finding:dark-ground"])
        self.assertEqual(entry["unresolved"], ["visual-qa-report:score:environment"])
        self.assertEqual((entry["cost_usd"], entry["sessions"]), (4.5, 1))


class FindingLifecycle(unittest.TestCase):
    """detected -> classified -> assigned -> implemented -> verified -> closed, carried from
    each triage-report to the next; verified or closed only on the raising gate's
    re-measurement, never on the specialist's word, and never past a regression."""

    DARK = "visual-qa-report:finding:dark-ground"
    UI = "visual-qa-report:score:ui_polish"

    def proto(self, commit, seq_iteration, specialist=None):
        body = {"title_id": "demo", "iteration": seq_iteration,
                "provenance": {"artifact_id": f"prototype-report-demo-{seq_iteration}"},
                "build_ref": {"commit_sha": commit}}
        if specialist:
            body["specialist"] = specialist
        return body

    def vqa(self, commit, dark=True, ui=True):
        findings = [{"id": "dark-ground", "severity": "blocker", "category": "readability",
                     "frame": None, "summary": "black ground bar", "route": "develop"}] \
            if dark else []
        failed = (["finding:dark-ground"] if dark else []) + (["score:ui_polish"] if ui else [])
        report = visual_qa(scores={"environment": 4, "ui_polish": 2 if ui else 4},
                           findings=findings, failed=failed,
                           verdict="FAIL" if failed else "PASS")
        report["commit"] = commit
        report["provenance"] = {"artifact_id": f"visual-qa-report-{commit[:4]}"}
        return report

    def records(self, result):
        return {r["id"]: r for r in result.artifacts[0].content["lifecycle"]}

    def chain(self):
        """Triage #1 (fresh), the environment artist's visit, triage #2 (continued), the UI
        visit: returns the docs and seqs as the gates are about to measure build C."""
        a, b, c = "a" * 40, "b" * 40, "c" * 40
        docs = {"game-design": DESIGN_3D, "prototype-report": self.proto(a, 1),
                "visual-qa-report": self.vqa(a)}
        seqs = {"prototype-report": 5, "visual-qa-report": 8}
        first = run_triage(docs, seqs=seqs)
        records = self.records(first)
        self.assertEqual(records[self.DARK]["status"], "assigned")
        self.assertEqual(records[self.UI]["status"], "classified")
        self.assertEqual([h["status"] for h in records[self.DARK]["history"]],
                         ["detected", "classified", "assigned"])
        self.assertEqual(records[self.DARK]["build"]["commit"], a)
        docs.update({"triage-report": first.artifacts[0].content,
                     "prototype-report": self.proto(b, 2, {"role": "environment-artist",
                                                           "findings": [self.DARK]})})
        seqs.update({"triage-report": 9, "prototype-report": 11})
        second = run_triage(docs, seqs=seqs, entered="develop.next-specialist")
        records = self.records(second)
        self.assertEqual(records[self.DARK]["status"], "implemented")
        self.assertEqual(records[self.DARK]["fix"]["commit"], b)
        self.assertEqual(records[self.UI]["status"], "assigned")
        docs.update({"triage-report": second.artifacts[0].content,
                     "prototype-report": self.proto(c, 3, {"role": "ui",
                                                           "findings": [self.UI]})})
        seqs.update({"triage-report": 12, "prototype-report": 13})
        return docs, seqs, c

    def test_a_fix_the_gate_re_measured_clean_is_verified_then_closed(self):
        docs, seqs, c = self.chain()
        # visual-qa measures build C: both gone. verify then fails on something new? No -
        # review asks for a change it raised before the fix (an older id), not a regression.
        docs["visual-qa-report"] = self.vqa(c, dark=False, ui=False)
        docs["review-report"] = {"verdict": "request-changes", "reviewed_commit": c,
                                 "blockers": [{"id": "B1", "file": None, "summary": "x",
                                               "severity": "blocker"}]}
        docs["triage-report"]["lifecycle"].append({
            "id": "review-report:b1", "dimension": "gameplay", "severity": "blocker",
            "owner": "gameplay", "route": "develop", "status": "classified", "summary": "x",
            "source": {"producer": "review-report", "check": "B1"},
            "build": {"commit": "a" * 40, "digest": None}, "evidence_refs": [],
            "history": [], "verification": None, "fix": None, "detected_seq": 7})
        seqs.update({"visual-qa-report": 16, "review-report": 17})
        result = run_triage(docs, seqs=seqs, entered="review.request-changes")
        records = self.records(result)
        dark, ui = records[self.DARK], records[self.UI]
        self.assertEqual(ui["status"], "closed")
        self.assertEqual(ui["verification"]["verdict"], "passed")
        self.assertEqual(ui["verification"]["build"]["commit"], c)
        self.assertEqual(dark["status"], "closed")
        self.assertEqual([h["status"] for h in dark["history"]],
                         ["detected", "classified", "assigned", "implemented", "verified",
                          "closed"])

    def test_a_fix_that_regresses_another_gate_is_not_verified(self):
        docs, seqs, c = self.chain()
        docs["visual-qa-report"] = self.vqa(c, dark=False, ui=True)
        docs["qa-report"] = {"verdict": "fail", "build_ref": {"commit_sha": c}, "suites": [],
                             "blocking_defects": [{"id": "D9", "severity": "critical",
                                                   "summary": "crash on restart",
                                                   "repro": "lose, retry"}]}
        docs["verification-report"] = {"commit": {"sha": c},
                                       "build_artifact": {"status": "built",
                                                          "content_hash": "sha256:" + "d" * 64}}
        seqs.update({"visual-qa-report": 16, "qa-report": 20, "verification-report": 19})
        result = run_triage(docs, seqs=seqs, entered="verify.fail")
        records = self.records(result)
        dark = records[self.DARK]
        self.assertEqual(dark["status"], "implemented")
        self.assertEqual(dark["verification"]["verdict"], "regressed")
        self.assertIn("qa-report:d9", dark["verification"]["regressions"])
        # The UI fix did not take: the gate still fails it, so it is open again.
        ui = records[self.UI]
        # (pending behind the generalist, who owns the new defect and visits first)
        self.assertEqual((ui["status"], ui["verification"]["verdict"]),
                         ("classified", "still-failing"))
        self.assertIn("reopened", ui["history"][-1]["note"])
        self.assertEqual(result.route, "gameplay")
        # The new failure is in the ledger, measured on build C with its digest.
        new = records["qa-report:d9"]
        self.assertEqual(new["build"], {"commit": c, "digest": "sha256:" + "d" * 64})
        self.assertEqual(new["status"], "assigned")  # the generalist visits it now

    def test_a_human_finding_is_verified_by_the_next_g4(self):
        records = {"decision-record:g4-1": {
            "id": "decision-record:g4-1", "dimension": "audio", "severity": "major",
            "owner": "audio-designer", "route": "develop", "status": "implemented",
            "summary": "silent", "source": {"producer": "decision-record", "check": "g4-1"},
            "build": {"commit": "a" * 40, "digest": None}, "evidence_refs": [],
            "history": [], "verification": None, "detected_seq": 9,
            "fix": {"specialist": "audio-designer", "commit": "b" * 40,
                    "prototype_report": "p", "seq": 11}}}
        from wgf_triage import lifecycle
        out = lifecycle.advance(list(records.values()), at="t", current=[], failing={},
                                seqs={}, reports={}, proto=None, proto_seq=11,
                                decision={"decision": "pass", "provenance": {}},
                                decision_seq=20, human_ids=set(), selected=None,
                                triage_id="tr", routing_version="1.0.0",
                                build_of=lambda k: {"commit": None, "digest": None})
        self.assertEqual(out[0]["status"], "closed")  # no gate report to wait for
        self.assertEqual(out[0]["verification"]["verdict"], "passed")


class SpecialistBrief(unittest.TestCase):
    """A specialist visit's brief: only the findings it owns, its playbooks, its scope."""

    def setUp(self):
        docs = {"game-design": DESIGN_3D,
                "prototype-report": {"title_id": "demo", "iteration": 2,
                                     "build_ref": {"commit_sha": COMMIT}},
                "visual-qa-report": visual_qa(
                    scores={"environment": 4, "ui_polish": 2},
                    findings=[{"id": "dark-ground", "severity": "blocker",
                               "category": "readability", "frame": None,
                               "summary": "black ground bar", "route": "develop"}],
                    failed=["finding:dark-ground", "score:ui_polish"])}
        self.triage = run_triage(docs, seqs={"prototype-report": 5,
                                             "visual-qa-report": 8}).artifacts[0].content

    def resolve(self, entered="triage.environment-artist"):
        context = types.SimpleNamespace(entered_by=entered, run_dir=None)
        return specialists.resolve(context, Inputs({"triage-report": self.triage}),
                                   "production")

    def test_the_brief_carries_only_owned_findings_and_the_specialists_playbooks(self):
        spec, problem = self.resolve()
        self.assertIsNone(problem)
        self.assertEqual(spec["role"], "environment-artist")
        self.assertEqual([f["id"] for f in spec["findings"]],
                         ["visual-qa-report:finding:dark-ground"])
        spec["writable_paths"] = specialists.narrow(list(briefs.DEFAULT_WRITABLE),
                                                    spec["writes"])
        text = "\n".join(specialists.render(spec))
        self.assertIn("visual-qa-report:finding:dark-ground", text)
        owned = text.split("### Your findings")[1].split("### Your craft playbooks")[0]
        self.assertNotIn("ui_polish", owned)
        # Every specialist brief carries the same context: brief, contract, budget, floor,
        # acceptance, the other open findings (read-only) and the regression constraints.
        for needle in ("**Design contract:**", "**Quality floor:**",
                       "core/reference/quality-benchmark.yaml", "**Acceptance:**",
                       "**Regression constraints:**", "a fix that makes another gate fail is "
                       "not verified"):
            self.assertIn(needle, text)
        others = text.split("**Other open findings**")[1].split("\n")[0]
        self.assertIn("visual-qa-report:score:ui_polish", others)
        self.assertIn("production-art-3d.md", text)
        self.assertNotIn("game-ui-kit.md", text)
        self.assertIn("Environment and lighting artist", text)
        self.assertIn("`ui`", text)  # who comes next, so it leaves their findings alone

    def test_writable_scope_is_cut_to_the_specialist_never_widened(self):
        self.assertEqual(specialists.narrow(["src/", "tests/", "public/", "docs/development/",
                                             "index.html"],
                                            ["public/content/", "src/", "tests/",
                                             "docs/development/"]),
                         ["src/", "tests/", "public/content/", "docs/development/"])
        self.assertEqual(specialists.narrow(["src/game/"], ["src/", "public/"]), ["src/game/"])
        self.assertEqual(specialists.narrow(["src/"], []), [])

    def test_an_entry_the_triage_report_does_not_route_is_refused(self):
        spec, problem = self.resolve("triage.ui")
        self.assertIsNone(spec)
        self.assertIn("cannot be established", problem)

    def test_a_first_pass_is_no_specialist_visit(self):
        self.assertEqual(self.resolve("triage.success"), (None, None))


import test_develop_module as dev  # noqa: E402  (its git checkout and mock developer)


class SpecialistVisitThroughDevelop(dev.DevelopCase):
    """The real develop step, a mock developer: entered as `triage.<role>`, the visit is
    that specialist's - brief, scope, record - and hands on to the next specialist."""

    def triage_report(self):
        docs = {"game-design": DESIGN_3D,
                "prototype-report": {"title_id": "demo", "iteration": 1,
                                     "build_ref": {"commit_sha": COMMIT}},
                "visual-qa-report": visual_qa(
                    scores={"environment": 4, "ui_polish": 2},
                    findings=[{"id": "dark-ground", "severity": "blocker",
                               "category": "readability", "frame": None,
                               "summary": "black ground bar", "route": "develop"}],
                    failed=["finding:dark-ground", "score:ui_polish"])}
        report = run_triage(docs, seqs={"prototype-report": 5,
                                        "visual-qa-report": 8}).artifacts[0].content
        report["provenance"] = dict(report["provenance"], schema_version="1.0.0")
        return report

    def run_visit(self, on_develop=dev.write_game):
        ctx = dev.context(self.command_config(), key="run-1:develop:2", visit=2)
        ctx.entered_by = "triage.environment-artist"
        ctx.current_step = "develop"
        ctx.visit_budget = {"step": {"limit": 51, "used": 2, "remaining": 49},
                            "route": {"route": "triage.environment-artist",
                                      "limit_key": "triage.environment-artist",
                                      "limit": 4, "used": 1, "remaining": 3}}
        inputs = dev.inputs_for(overrides={"triage-report": self.triage_report()})
        return dev.step_with(dev.FakeRunner(on_develop=on_develop)).execute(inputs, ctx)

    def test_the_visit_is_the_specialists_and_hands_on_to_the_next(self):
        result = self.run_visit()
        self.assertEqual((result.outcome, result.route), ("SUCCESS", "next-specialist"),
                         result.error)
        with open(os.path.join(self.repo, briefs.BRIEF_DIR, "brief.md"),
                  encoding="utf-8") as handle:
            text = handle.read()
        self.assertIn("## This visit: Environment and lighting artist (3D)", text)
        self.assertIn("visual-qa-report:finding:dark-ground", text)
        owned = text.split("### Your findings")[1].split("### Your craft playbooks")[0]
        self.assertNotIn("visual-qa-report:score:ui_polish", owned)
        self.assertIn("**Game brief:**", text)
        self.assertIn("production-art-3d.md", text)
        self.assertNotIn("game-ui-kit.md", text)  # the full craft list is not handed over
        with open(os.path.join(self.repo, briefs.BRIEF_DIR, "brief.json"),
                  encoding="utf-8") as handle:
            brief = json.load(handle)
        self.assertNotIn("index.html", brief["writable_paths"])
        self.assertEqual(brief["loop"]["entered_by"], "visual-qa.develop")
        record = result.artifacts[0].content["specialist"]
        self.assertEqual((record["role"], record["findings"], record["pending"]),
                         ("environment-artist", ["visual-qa-report:finding:dark-ground"],
                          ["ui"]))
        self.assertEqual(record["sessions"], 1)
        self.assertEqual(ArtifactContracts()("prototype-report",
                                             result.artifacts[0].content), [])

    def test_a_change_outside_the_specialists_scope_is_not_committed(self):
        # index.html is a developer's to write, but not the environment artist's.
        with open(os.path.join(self.repo, "index.html"), "w", encoding="utf-8") as handle:
            handle.write("<html></html>")
        self.git("add", "index.html")
        self.git(*dev.IDENTITY, "commit", "-q", "-m", "page")
        result = self.run_visit(on_develop=lambda cwd: dev.write_game(
            cwd, {"index.html": "<html>changed by the environment artist</html>"}))
        self.assertEqual(result.outcome, "FAILED")
        self.assertIn("index.html", result.error)


class SpecialistLoopLimits(unittest.TestCase):
    """A specialist that never resolves what it owns stops the run for a person, named -
    the shipped workflow, mock steps, in process."""

    def setUp(self):
        self.scratch = tempfile.mkdtemp(prefix="wgf-triage-loop-")
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)

    def test_an_endless_specialist_chain_blocks_at_that_specialists_limit(self):
        api = WorkflowAPI(config=FactoryConfig({"storage": {"fsync": False}}),
                          store_dir=os.path.join(self.scratch, "store"))
        # triage: first pass clear, then the environment artist forever; develop: always
        # another specialist pending.
        plan = {"triage": ["success"] + ["environment-artist"] * 20,
                "develop": ["success"] + ["next-specialist"] * 20,
                "visual-qa": ["develop"]}
        state = api.run(RunRequest(mock=True, mock_plan=plan))
        self.assertEqual((state.status, state.cursor), (RunStatus.BLOCKED, "develop"),
                         state.message)
        reason = state.blocked_reason
        self.assertEqual((reason["kind"], reason["scope"], reason["from"], reason["route"],
                          reason["limit_key"], reason["limit"]),
                         ("loop-limit", "route", "triage", "environment-artist",
                          "triage.environment-artist", 4))
        self.assertEqual(state.steps["develop"].route_visits["triage.environment-artist"], 4)


if __name__ == "__main__":
    unittest.main()

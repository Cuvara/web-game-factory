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

    def test_a_browser_qa_defect_goes_to_the_owner_of_its_check(self):
        # Verify writes a defect `vr-<check, mangled>`; the routing data's
        # verification_checks table names the check, and its viewport is the project.
        qa = {"verdict": "fail", "blocking_defects": [
            {"id": "vr-browser-context-menu-mobile", "severity": "blocker",
             "summary": "context menu opened", "repro": "x"},
            {"id": "vr-browser-audio-hidden", "severity": "blocker",
             "summary": "sound while hidden", "repro": "x"},
            {"id": "vr-browser-ui-covers-play-tablet", "severity": "blocker",
             "summary": "card over the ball", "repro": "x"},
            {"id": "vr-browser-frame-stability", "severity": "critical",
             "summary": "p95 41 ms", "repro": "x"},
            {"id": "vr-browser-win-desktop-wide", "severity": "blocker",
             "summary": "no win", "repro": "x"},
            {"id": "vr-browser-run", "severity": "critical", "summary": "spec did not run",
             "repro": "x"},
            {"id": "vr-build", "severity": "blocker", "summary": "build failed", "repro": "x"}]}
        found = self.by_id(normalize("qa-report", qa, ROUTING))
        owners = {k: (v["owner"], v["source"]["check"], v["source"]["project"])
                  for k, v in found.items()}
        self.assertEqual(owners["qa-report:browser.context-menu@mobile"],
                         ("browser-qa", "browser.context-menu", "mobile"))
        self.assertEqual(owners["qa-report:browser.audio-hidden"][0], "audio-designer")
        self.assertEqual(owners["qa-report:browser.ui-covers-play@tablet"][0], "ui")
        self.assertEqual(owners["qa-report:browser.frame-stability"][0],
                         "performance-engineer")
        self.assertEqual(owners["qa-report:browser.win@desktop-wide"][0], "gameplay")
        self.assertEqual(owners["qa-report:browser.run"][0], "browser-qa")
        self.assertEqual(owners["qa-report:vr-build"][0], "gameplay")

    def test_play_realism_failures_go_to_their_owners(self):
        report = playability(("physics.undrawn_collision", {}), ("naive.setbacks", {}),
                             ("naive.pace", {}), ("naive.alignment", {}),
                             ("level.clearance", {}), ("runtime.console_errors", {}),
                             ("runtime.webgl_context", {}))
        owners = {f["source"]["check"]: f["owner"]
                  for f in normalize("playability-report", report, ROUTING)}
        self.assertEqual(owners, {
            "physics.undrawn_collision": "gameplay", "naive.setbacks": "encounter-designer",
            "naive.pace": "level-designer", "naive.alignment": "gameplay",
            "level.clearance": "level-designer", "runtime.console_errors": "browser-qa",
            "runtime.webgl_context": "performance-engineer"})

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

    def chain(self, measured=None):
        """Triage #1 (fresh), the environment artist's visit, triage #2 (continued), the UI
        visit: returns the docs and seqs as the gates are about to measure build C.
        `measured` ({type: (report, seq)}) are further gates' reports of build A."""
        a, b, c = "a" * 40, "b" * 40, "c" * 40
        docs = {"game-design": DESIGN_3D, "prototype-report": self.proto(a, 1),
                "visual-qa-report": self.vqa(a)}
        seqs = {"prototype-report": 5, "visual-qa-report": 8}
        for kind, (report, seq) in (measured or {}).items():
            docs[kind], seqs[kind] = report, seq
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
        # verification measured build A and passed it: the defect on C is a regression.
        passed = {"verdict": "pass", "build_ref": {"commit_sha": "a" * 40}, "suites": [],
                  "blocking_defects": [],
                  "provenance": {"artifact_id": "qa-report-demo-1"}}
        docs, seqs, c = self.chain(measured={"qa-report": (passed, 7)})
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

    def test_a_gate_measuring_for_the_first_time_after_a_fix_is_not_its_regression(self):
        """The real 2D/3D runs (K6 retro): production-quality ran for the first time after a
        fix, failed something, and the fix - passed by its own gate six times - was never
        verified. A producer that had not measured before the fix raises a new finding."""
        docs, seqs, c = self.chain()
        docs["visual-qa-report"] = self.vqa(c, dark=False, ui=False)
        docs["qa-report"] = {"verdict": "fail", "build_ref": {"commit_sha": c}, "suites": [],
                             "blocking_defects": [{"id": "D9", "severity": "critical",
                                                   "summary": "crash on restart",
                                                   "repro": "lose, retry"}]}
        seqs.update({"visual-qa-report": 16, "qa-report": 20})
        result = run_triage(docs, seqs=seqs, entered="verify.fail")
        records = self.records(result)
        dark = records[self.DARK]
        self.assertIn(dark["status"], ("verified", "closed"))
        self.assertEqual(dark["verification"]["regressions"], [])
        self.assertNotIn("qa-report", dark["baseline"])
        self.assertIn("visual-qa-report", dark["baseline"])
        self.assertEqual(records["qa-report:d9"]["status"], "assigned")  # a new finding

    def production(self, commit, verdict="FAIL"):
        return {"title_id": "demo", "commit": commit, "verdict": verdict,
                "provenance": {"artifact_id": f"production-quality-report-{commit[:4]}"},
                "checks": [{"id": "assets.present", "status": verdict, "required": True,
                            "summary": "placeholders: player", "route": "assets"}]}

    def test_a_finding_a_gate_sent_straight_to_assets_is_in_the_ledger(self):
        """WS-13: production-quality's `assets` route goes to the assets step, not through
        triage; the triage after it used to drop the finding as handed over, so the ledger
        never held it. Now it is recorded, implemented by the remade manifest, and verified
        when the gate passes the next build."""
        a, b = "a" * 40, "b" * 40
        fid = "production-quality-report:assets.present"
        docs = {"game-design": DESIGN_2D, "prototype-report": self.proto(a, 1),
                "production-quality-report": self.production(a),
                "asset-manifest": {"provenance": {"artifact_id": "asset-manifest-demo-2"}}}
        seqs = {"prototype-report": 5, "production-quality-report": 8, "asset-manifest": 9}
        first = run_triage(docs, seqs=seqs, entered="assets.success")
        self.assertIsNone(first.route)  # nothing routed again: develop integrates the art
        record = self.records(first)[fid]
        self.assertEqual([h["status"] for h in record["history"]],
                         ["detected", "classified", "assigned", "implemented"])
        self.assertEqual((record["fix"]["specialist"], record["fix"]["artifact_id"]),
                         ("assets", "asset-manifest-demo-2"))
        # The gate passes the build develop made with the new art: verified, then closed.
        docs.update({"triage-report": first.artifacts[0].content,
                     "prototype-report": self.proto(b, 2),
                     "production-quality-report": self.production(b, "PASS"),
                     "visual-qa-report": self.vqa(b, dark=False, ui=False)})
        seqs.update({"triage-report": 10, "prototype-report": 11,
                     "production-quality-report": 13, "visual-qa-report": 14})
        second = run_triage(docs, seqs=seqs, entered="visual-qa.develop")
        record = self.records(second)[fid]
        self.assertEqual(record["status"], "closed")
        self.assertEqual(record["verification"]["build"]["commit"], b)

    def test_a_finding_its_gate_passes_with_no_recorded_fix_is_verified(self):
        """A group still pending, or fixed by another visit's change: the raising gate's
        measurement of a newer build verifies it, and the history says no fix was recorded.
        Without a newer measurement it stays open."""
        from wgf_triage import lifecycle
        record = {"id": self.UI, "dimension": "ui", "severity": "major", "owner": "ui",
                  "route": "develop", "status": "assigned", "summary": "ui",
                  "source": {"producer": "visual-qa-report", "check": "score:ui_polish"},
                  "build": {"commit": "a" * 40, "digest": None}, "evidence_refs": [],
                  "history": [], "verification": None, "fix": None, "detected_seq": 8}

        def advance(seq):
            return lifecycle.advance(
                [dict(record)], at="t", current=[], failing={"visual-qa-report": set()},
                seqs={"visual-qa-report": seq}, reports={}, proto=None, proto_seq=5,
                decision=None, decision_seq=-1, human_ids=set(), selected=None,
                triage_id="tr", routing_version="1.3.0",
                build_of=lambda k: {"commit": "b" * 40, "digest": None})[0]
        self.assertEqual(advance(8)["status"], "assigned")  # the same report: not re-measured
        out = advance(12)
        self.assertEqual(out["status"], "closed")
        self.assertIsNone(out["fix"])
        self.assertIn("no fix was recorded", out["history"][0]["note"])
        self.assertEqual(lifecycle.unresolved([dict(record)], ("major",)), [record])
        self.assertEqual(lifecycle.unresolved([out], ("major",)), [])

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


class SplitByRoute(unittest.TestCase):
    """A check whose failing items have different owners is one finding per route
    (specialist-routing.yaml `split`): production-quality's assets.runtime fails one asset at
    `exists` (the assets step's) and another at `visible` (the game's code). Before the
    split the whole check routed `assets`, an assets pass dropped it as handled, and the
    develop part reached no specialist (the live 2D run, PQ v1-v3, triage v10-v12)."""

    ASSETS = "production-quality-report:assets.runtime/assets"
    DEVELOP = "production-quality-report:assets.runtime/develop"

    @staticmethod
    def runtime(commit, failures, verdict=None):
        """A production-quality-report whose assets.runtime fails `failures` {asset: link},
        routed as checks.py routes it: `assets` when any fails at `exists`."""
        measured = {a: {"exists": link != "exists", "role": "player", "failed_at": link}
                    for a, link in failures.items()}
        measured["paddle"] = {"exists": True, "role": "player", "failed_at": None}
        failing = bool(failures)
        status = verdict or ("FAIL" if failing else "PASS")
        return {"title_id": "demo", "commit": commit, "verdict": status,
                "provenance": {"artifact_id": f"production-quality-report-{commit[:4]}"},
                "checks": [{"id": "assets.runtime", "status": status, "required": True,
                            "summary": "; ".join(f"{a}: fails at {f}"
                                                 for a, f in sorted(failures.items())),
                            "route": "assets" if "exists" in failures.values() else "develop",
                            "measured": measured, "expected": "exists -> ... -> visible",
                            "assets": sorted(failures)},
                           {"id": "ui.targets", "status": "PASS", "required": True,
                            "summary": "ok", "route": "develop"}]}

    def test_a_mixed_check_is_one_finding_per_route_with_only_its_assets(self):
        report = self.runtime("a" * 40, {"ball": "visible", "brick": "exists",
                                         "capsule": "rendered"})
        found = {f["id"]: f for f in normalize("production-quality-report", report, ROUTING)}
        self.assertEqual(sorted(found), [self.ASSETS, self.DEVELOP])
        assets, develop = found[self.ASSETS], found[self.DEVELOP]
        self.assertEqual((assets["route"], assets["assets"]), ("assets", ["brick"]))
        self.assertEqual((develop["route"], develop["assets"]), ("develop", ["ball", "capsule"]))
        self.assertEqual(develop["owner"], "artist-2d")
        # The check id and the failed_at semantics are the report's, unchanged.
        for finding in (assets, develop):
            self.assertEqual(finding["source"]["check"], "assets.runtime")
        self.assertEqual(develop["measured"]["ball"]["failed_at"], "visible")
        self.assertEqual(sorted(develop["measured"]), ["ball", "capsule"])
        self.assertIn("ball: fails at visible", develop["summary"])
        self.assertNotIn("brick", develop["summary"])

    def test_single_route_and_unsplit_checks_keep_their_ids(self):
        only_develop = self.runtime("a" * 40, {"ball": "visible"})
        found = normalize("production-quality-report", only_develop, ROUTING)
        # A split check is always suffixed: the same id on every measurement of its items.
        self.assertEqual([f["id"] for f in found], [self.DEVELOP])
        report = {"verdict": "FAIL", "checks": [
            {"id": "assets.present", "status": "FAIL", "required": True,
             "summary": "placeholders: player", "route": "assets", "assets": ["player"],
             "measured": {"missing": [], "placeholder": ["player"]}},
            {"id": "assets.loaded", "status": "FAIL", "required": True,
             "summary": "never fetched: player", "route": "develop", "assets": ["player"]}]}
        found = {f["id"]: f for f in normalize("production-quality-report", report, ROUTING)}
        self.assertEqual(sorted(found), ["production-quality-report:assets.loaded",
                                         "production-quality-report:assets.present"])
        self.assertEqual(found["production-quality-report:assets.present"]["route"], "assets")
        # A failed split check with nothing per item to split stays one finding.
        empty = {"verdict": "FAIL", "checks": [
            {"id": "assets.runtime", "status": "FAIL", "required": True, "route": "develop",
             "summary": "no required asset in the design or manifest", "measured": {}}]}
        self.assertEqual([f["id"] for f in normalize("production-quality-report", empty,
                                                     ROUTING)],
                         ["production-quality-report:assets.runtime"])

    def test_the_rule_agrees_with_the_checks_whole_route(self):
        """checks.py routes assets.runtime `assets` iff an asset fails at `exists`; the
        split rule must give `assets` to exactly those assets, `develop` to the rest."""
        from wgf_production.checks import CHAIN
        rule = ROUTING.producer("production-quality-report")["split"]["assets.runtime"]
        routes = {link: rule["routes"].get(link, rule["default"]) for link in CHAIN}
        self.assertEqual({link for link, r in routes.items() if r == "assets"}, {"exists"})
        self.assertEqual({r for link, r in routes.items() if link != "exists"}, {"develop"})

    def test_an_assets_pass_leaves_the_develop_part_routed_to_its_owner(self):
        a = "a" * 40
        docs = {"game-design": DESIGN_2D,
                "prototype-report": {"title_id": "demo", "iteration": 1,
                                     "provenance": {"artifact_id": "prototype-report-demo-1"},
                                     "build_ref": {"commit_sha": a}},
                "production-quality-report": self.runtime(a, {"ball": "visible",
                                                              "brick": "exists",
                                                              "capsule": "rendered"}),
                "asset-manifest": {"provenance": {"artifact_id": "asset-manifest-demo-2"}}}
        seqs = {"prototype-report": 5, "production-quality-report": 8, "asset-manifest": 9}
        result = run_triage(docs, seqs=seqs, entered="assets.success")
        content = result.artifacts[0].content
        self.assertEqual(result.route, "artist-2d")
        self.assertEqual(content["selected"]["findings"], [self.DEVELOP])
        records = {r["id"]: r for r in content["lifecycle"]}
        # The assets part is in the ledger as made again by the assets pass.
        self.assertEqual(records[self.ASSETS]["status"], "implemented")
        self.assertEqual(records[self.ASSETS]["fix"]["specialist"], "assets")
        self.assertEqual(records[self.DEVELOP]["status"], "assigned")

    def test_a_split_finding_closes_only_when_its_own_items_measure_clean(self):
        a, b, c = "a" * 40, "b" * 40, "c" * 40
        proto = lambda commit, n, spec=None: dict(  # noqa: E731
            {"title_id": "demo", "iteration": n,
             "provenance": {"artifact_id": f"prototype-report-demo-{n}"},
             "build_ref": {"commit_sha": commit}}, **({"specialist": spec} if spec else {}))
        docs = {"game-design": DESIGN_2D, "prototype-report": proto(a, 1),
                "production-quality-report": self.runtime(a, {"ball": "visible",
                                                              "brick": "exists"}),
                "asset-manifest": {"provenance": {"artifact_id": "asset-manifest-demo-2"}}}
        seqs = {"prototype-report": 5, "production-quality-report": 8, "asset-manifest": 9}
        first = run_triage(docs, seqs=seqs, entered="assets.success")
        # The 2D artist's visit builds a change for the develop part.
        docs.update({"triage-report": first.artifacts[0].content,
                     "prototype-report": proto(b, 2, {"role": "artist-2d",
                                                      "findings": [self.DEVELOP]})})
        seqs.update({"triage-report": 10, "prototype-report": 11})
        # Re-measured on build B: brick now exists; ball is still not visible.
        docs["production-quality-report"] = self.runtime(b, {"ball": "visible"})
        seqs["production-quality-report"] = 13
        second = run_triage(docs, seqs=seqs, entered="production-quality.develop")
        records = {r["id"]: r for r in second.artifacts[0].content["lifecycle"]}
        self.assertIn(records[self.ASSETS]["status"], ("verified", "closed"))
        self.assertEqual(records[self.DEVELOP]["status"], "assigned")  # reopened, routed
        self.assertEqual(records[self.DEVELOP]["verification"]["verdict"], "still-failing")
        self.assertEqual(second.route, "artist-2d")
        # The next visit fixes it, and the gate measures build C clean: verified.
        docs.update({"triage-report": second.artifacts[0].content,
                     "prototype-report": proto(c, 3, {"role": "artist-2d",
                                                      "findings": [self.DEVELOP]})})
        seqs.update({"triage-report": 14, "prototype-report": 15})
        docs["production-quality-report"] = self.runtime(c, {})
        seqs["production-quality-report"] = 17
        third = run_triage(docs, seqs=seqs, entered="visual-qa.develop")
        records = {r["id"]: r for r in third.artifacts[0].content["lifecycle"]}
        self.assertIn(records[self.DEVELOP]["status"], ("verified", "closed"))
        self.assertEqual(records[self.DEVELOP]["verification"]["verdict"], "passed")

    def blocked_after(self, after_failures, part=None):
        """A split finding detected on A, re-measured by a production-quality report on B
        whose verdict is BLOCKED (another required check stale), so its findings are never
        normalized - `failing` is empty. Returns (state, record) of the `part` finding."""
        from wgf_triage import lifecycle, measurement
        part = part or self.DEVELOP
        before = self.runtime("a" * 40, {"ball": "visible", "brick": "exists"})
        before["provenance"]["content_hash"] = "sha256:" + "1" * 64
        after = self.runtime("b" * 40, after_failures)
        after["verdict"] = "BLOCKED"  # the report, not the check: assets.runtime still FAILs
        after["provenance"]["content_hash"] = "sha256:" + "2" * 64
        found = normalize("production-quality-report", before, ROUTING)
        for f in found:
            f["build"] = {"commit": "a" * 40, "digest": None}
        records = lifecycle.advance(
            [], at="t", current=found,
            failing={"production-quality-report": {f["id"] for f in found}},
            seqs={"production-quality-report": 8},
            reports={"production-quality-report": before}, proto=None, proto_seq=5,
            decision=None, decision_seq=-1, human_ids=set(), selected=None, triage_id="t1",
            routing_version="x", build_of=lambda k: {"commit": "a" * 40, "digest": None})
        out = lifecycle.advance(
            records, at="t", current=[], failing={"production-quality-report": set()},
            seqs={"production-quality-report": 12},
            reports={"production-quality-report": after}, proto=None, proto_seq=5,
            decision=None, decision_seq=-1, human_ids=set(), selected=None, triage_id="t2",
            routing_version="x", build_of=lambda k: {"commit": "b" * 40, "digest": None})
        source = next(f for f in found if f["id"] == part)["source"]
        return (measurement.state("production-quality-report", after, part, source, set()),
                next(r for r in out if r["id"] == part))

    def test_a_split_part_still_failing_in_a_blocked_report_is_not_verified(self):
        """Review r1 finding 1: a split finding's check still FAILs its item (ball@visible)
        in a BLOCKED production-quality report. The report's findings are never normalized,
        so `failing` is empty - the part must still read `fail`, never verified."""
        state, record = self.blocked_after({"ball": "visible"})
        self.assertEqual(state, "fail")
        self.assertNotIn(record["status"], ("verified", "closed"))
        self.assertNotIn("verified", [h["status"] for h in record["history"]])

    def test_a_split_part_no_longer_failing_in_a_blocked_report_still_passes(self):
        """The other part (brick@exists) measured clean in the same BLOCKED report: its own
        items no longer fail, so it reads `pass` - only the failing part is held."""
        state, _record = self.blocked_after({"ball": "visible"}, part=self.ASSETS)
        self.assertEqual(state, "pass")

    def test_a_split_check_failing_with_no_part_to_split_is_unmeasured(self):
        """The whole check FAILs in a BLOCKED report but names no failing item: which part
        it fails cannot be established - unmeasured, never a pass."""
        from wgf_triage import measurement
        after = self.runtime("b" * 40, {})
        after["verdict"] = "BLOCKED"
        after["checks"][0]["status"] = "FAIL"
        source = {"check": "assets.runtime", "project": None}
        self.assertEqual(measurement.state("production-quality-report", after, self.DEVELOP,
                                           source, set()), "unmeasured")



def _proto(commit, iteration, specialist=None):
    body = {"title_id": "demo", "iteration": iteration,
            "provenance": {"artifact_id": f"prototype-report-demo-{iteration}"},
            "build_ref": {"commit_sha": commit}}
    if specialist:
        body["specialist"] = specialist
    return body


class ScenarioVerification(unittest.TestCase):
    """K6.2: a repair is verified only when the SAME check on the SAME project was measured
    FAIL on one commit and PASS on a newer one by the same producer - with both measurements
    and the scenario each was played in kept in the ledger. Nothing that hides the check
    verifies it: left unmeasured, removed from the report, made not applicable, passed only
    on another viewport, or passed by playing the same commit again.

    The playability reports here are made by the step's own path (analysis.judge, the
    scenarios, _finish; test_playability.played_report) from FIXTURE bot records, except
    test_real_recorded_naive_play, which judges REAL bot records."""

    DESKTOP = "playability-report:restart.works@desktop"
    MOBILE = "playability-report:restart.works@mobile"

    def setUp(self):
        import test_playability as tp
        self.tp = tp
        self.run = tempfile.mkdtemp(prefix="wgf-k6-scenario-")
        self.addCleanup(shutil.rmtree, self.run, ignore_errors=True)
        self.visit = 0

    # -- reports ---------------------------------------------------------------------------

    def report(self, commit, records=None, **kw):
        self.visit += 1
        return self.tp.played_report(self.run, commit, records=records, visit=self.visit, **kw)

    def dead(self, project=None):
        """The restart is pressed and play never comes back (the K6.1 `restart-dead`)."""
        records = self.tp.well_played()
        records["lose"]["restart"] = {"clicked": "input:retry", "playingMs": None,
                                      "metrics": None}
        return records

    def fixed(self, project=None):
        return self.tp.well_played()

    # -- the ledger, through the triage step -----------------------------------------------

    def loop(self, before, after, commits=("a" * 40, "b" * 40), extra=None):
        """Triage #1 on `before` (built from commits[0]); the owner's visit builds commits[1]
        for every finding it was assigned; triage #2 on `after`. Returns triage #2's ledger."""
        a, b = commits
        docs = {"game-design": DESIGN_2D, "prototype-report": _proto(a, 1),
                "playability-report": before}
        seqs = {"prototype-report": 5, "playability-report": 8}
        first = run_triage(docs, seqs=seqs, entered="playability.fail")
        ledger = {r["id"]: r for r in first.artifacts[0].content["lifecycle"]}
        assigned = sorted(i for i, r in ledger.items() if r["status"] == "assigned")
        self.assertIn(self.DESKTOP, assigned)
        owner = ledger[self.DESKTOP]["owner"]
        docs.update({"triage-report": first.artifacts[0].content,
                     "prototype-report": _proto(b, 2, {"role": owner, "findings": assigned}),
                     "playability-report": after})
        docs.update(extra or {})
        seqs.update({"triage-report": 9, "prototype-report": 11, "playability-report": 13})
        seqs.update({k: 14 for k in (extra or {})})
        second = run_triage(docs, seqs=seqs, entered="playability.success")
        self.docs, self.seqs, self.second = docs, seqs, second.artifacts[0].content
        return {r["id"]: r for r in second.artifacts[0].content["lifecycle"]}

    def test_the_restart_dead_fixture_fails_only_restart_works(self):
        report = self.report("a" * 40, self.dead())
        self.assertEqual(report["verdict"], "FAIL")
        self.assertEqual(report["failed_checks"], ["desktop:restart.works",
                                                   "mobile:restart.works"])
        self.assertEqual(self.report("b" * 40, self.fixed())["verdict"], "PASS")

    def test_fail_then_pass_of_the_same_scenario_is_verified_with_both_measurements(self):
        a, b = "a" * 40, "b" * 40
        ledger = self.loop(self.report(a, self.dead()), self.report(b, self.fixed()))
        record = ledger[self.DESKTOP]
        self.assertIn(record["status"], ("verified", "closed"))
        self.assertIn("verified", [h["status"] for h in record["history"]])
        ver = record["verification"]
        self.assertEqual(ver["verdict"], "passed")
        before, after = ver["before"], ver["after"]
        self.assertEqual((before["commit"], before["status"]), (a, "FAIL"))
        self.assertEqual((after["commit"], after["status"]), (b, "PASS"))
        for measured in (before, after):
            self.assertEqual(measured["check"], "restart.works")
            self.assertEqual(measured["project"], "desktop")
            self.assertEqual(measured["scenario"]["id"], "restart.works@desktop")
            self.assertEqual(measured["scenario"]["bot_version"], self.tp.BOT_A)
            self.assertEqual(measured["scenario"]["viewport"], {"width": 1280, "height": 720})
            self.assertEqual(measured["scenario"]["policy"], {"lose": "anti-oracle"})
            self.assertEqual([f["id"] for f in measured["frames"]], ["end-lost"])
            self.assertTrue(measured["frames"][0]["sha256"].startswith("sha256:"))
        # Two visits, two frames: the before and after are each the frame of their own play.
        self.assertNotEqual(before["frames"][0]["path"], after["frames"][0]["path"])
        self.assertEqual(ver["comparison"], {
            "same_scenario": True, "differences": [],
            "note": "the same scenario, bot and settings measured the failure and the pass"})
        self.assertEqual(ledger[self.MOBILE]["verification"]["verdict"], "passed")

    def test_a_newer_bot_still_verifies_and_says_the_comparison_is_weaker(self):
        newer = "sha256:" + "b2" * 32
        ledger = self.loop(self.report("a" * 40, self.dead()),
                           self.report("b" * 40, self.fixed(), bot=newer))
        ver = ledger[self.DESKTOP]["verification"]
        self.assertEqual(ver["verdict"], "passed")
        self.assertEqual((ver["before"]["scenario"]["bot_version"],
                          ver["after"]["scenario"]["bot_version"]), (self.tp.BOT_A, newer))
        self.assertFalse(ver["comparison"]["same_scenario"])
        self.assertIn("bot version differs", ver["comparison"]["differences"])
        self.assertIn("a weaker comparison", ver["comparison"]["note"])
        self.assertIn("weaker comparison", ledger[self.DESKTOP]["history"][-2]["note"]
                      + ledger[self.DESKTOP]["history"][-1]["note"])

    def test_the_run_ledger_reopens_a_done_finding_its_newest_report_fails_again(self):
        """The quality gate and release advance the ledger with no triage of their own
        (ledger.remeasure). A finding closed earlier whose raising producer's newest report
        fails it again is reopened there too, never left closed beside the failing report
        (found by replaying the real 2D run's ledger: two content findings stayed closed while
        its last playability report failed them, K6 counterfactual)."""
        from types import SimpleNamespace
        from wgf_triage import ledger as ledgers
        a, b, c = "a" * 40, "b" * 40, "c" * 40
        ledger = self.loop(self.report(a, self.dead()), self.report(b, self.fixed()))
        self.assertIn(ledger[self.DESKTOP]["status"], ("verified", "closed"))
        docs = dict(self.docs, **{"triage-report": self.second,
                                  "playability-report": self.report(c, self.dead())})
        seqs = dict(self.seqs, **{"triage-report": 15, "playability-report": 20})
        refs = {k: SimpleNamespace(seq=seqs.get(k, 1)) for k in docs}
        records = {r["id"]: r for r in ledgers.remeasure(
            refs, docs.get, at="2026-10-09T00:00:00Z", by="quality-gate")}
        record = records[self.DESKTOP]
        self.assertEqual(record["status"], "classified", record["history"][-1])
        self.assertIn("reopened", record["history"][-1]["note"])
        self.assertEqual(record["history"][-1]["build"], c)
        self.assertIsNone(record.get("fix"))
        # Reopened once: a later triage of the same report observes it, no second event.
        events = [h for h in record["history"] if h["status"] == "classified"]
        self.assertEqual(len(events), 1 + sum(1 for h in ledger[self.DESKTOP]["history"]
                                              if h["status"] == "classified"))

    def test_a_replay_of_the_reopening_build_does_not_verify_it(self):
        """Review r1 finding 2: detected on A, verified on B, then the run ledger (no
        findings of its own: current=[]) reopens it on C. A re-play of C that passes is the
        same build, not a repair: held `same-build`, and the record's `before` names the
        failure on C that reopened it - never the stale failure on A."""
        from wgf_triage import lifecycle
        a, b, c = "a" * 40, "b" * 40, "c" * 40

        def adv(previous, report, seq, commit, current=()):
            failing = {f["id"] for f in normalize("playability-report", report, ROUTING)} \
                if report["verdict"] == "FAIL" else set()
            return {r["id"]: r for r in lifecycle.advance(
                list(previous), at="t", current=list(current),
                failing={"playability-report": failing}, seqs={"playability-report": seq},
                reports={"playability-report": report}, proto=None, proto_seq=5,
                decision=None, decision_seq=-1, human_ids=set(), selected=None,
                triage_id=f"t{seq}", routing_version="x",
                build_of=lambda k: {"commit": commit, "digest": None})}.values()

        first = self.report(a, self.dead())
        found = normalize("playability-report", first, ROUTING)
        for f in found:
            f["build"] = {"commit": a, "digest": None}
        ledger = adv([], first, 8, a, found)
        ledger = adv(ledger, self.report(b, self.fixed()), 12, b)
        record = next(r for r in ledger if r["id"] == self.DESKTOP)
        self.assertIn(record["status"], ("verified", "closed"))
        ledger = adv(ledger, self.report(c, self.dead()), 20, c)
        record = next(r for r in ledger if r["id"] == self.DESKTOP)
        self.assertEqual(record["status"], "classified")
        self.assertEqual(record["failed_measurement"]["commit"], c)
        self.assertEqual(record["failed_measurement"]["status"], "FAIL")
        self.assertEqual(record["failed_measurement"]["seq"], 20)
        self.assertEqual(record["build"]["commit"], c)
        ledger = adv(ledger, self.report(c, self.fixed()), 22, c)
        record = next(r for r in ledger if r["id"] == self.DESKTOP)
        self.assertEqual(record["status"], "classified", record["history"][-1])
        self.assertEqual(record["verification"]["verdict"], "same-build")
        self.assertEqual(record["verification"]["before"]["commit"], c)

    def test_the_run_ledger_keeps_a_done_finding_its_newest_report_still_passes(self):
        from types import SimpleNamespace
        from wgf_triage import ledger as ledgers
        a, b, c = "a" * 40, "b" * 40, "c" * 40
        self.loop(self.report(a, self.dead()), self.report(b, self.fixed()))
        docs = dict(self.docs, **{"triage-report": self.second,
                                  "playability-report": self.report(c, self.fixed())})
        seqs = dict(self.seqs, **{"triage-report": 15, "playability-report": 20})
        refs = {k: SimpleNamespace(seq=seqs.get(k, 1)) for k in docs}
        records = {r["id"]: r for r in ledgers.remeasure(
            refs, docs.get, at="2026-10-09T00:00:00Z", by="quality-gate")}
        self.assertIn(records[self.DESKTOP]["status"], ("verified", "closed"))

    def held(self, record, verdict):
        self.assertEqual(record["status"], "implemented", record["history"][-1])
        self.assertEqual(record["verification"]["verdict"], verdict)
        self.assertNotIn("verified", [h["status"] for h in record["history"]])
        self.assertIn("not verified", record["history"][-1]["note"])

    def test_a_repair_that_leaves_the_check_unmeasured_is_not_verified(self):
        """(a) The re-play's host was degraded: restart.works was not measured."""
        def degraded(project):
            records = self.fixed()
            records["lose"].update(self.tp.attempts(self.tp.DEGRADED))
            return records
        after = self.report("b" * 40, degraded)
        check = next(c for c in after["checks"]
                     if c["id"] == "restart.works" and c["project"] == "desktop")
        # A required check read on a degraded host is BLOCKED, and so is the report - whose
        # findings are never normalized, so its silence used to verify the finding.
        self.assertEqual((after["verdict"], check["status"]), ("BLOCKED", "BLOCKED"))
        self.assertEqual(check["measured"]["unmeasured"], "environment-degraded")
        ledger = self.loop(self.report("a" * 40, self.dead()), after)
        self.held(ledger[self.DESKTOP], "unmeasured")
        self.assertEqual(ledger[self.DESKTOP]["verification"]["after"]["status"], "BLOCKED")

    def test_a_repair_that_removes_the_check_from_the_report_is_not_verified(self):
        """(b) The next report does not list restart.works at all (a stand-in for a bot or
        analysis that stopped measuring it): reported as missing, never as fixed."""
        after = self.report("b" * 40, self.dead(),
                            change=lambda checks: [c for c in checks
                                                   if c["id"] != "restart.works"])
        self.assertEqual(after["verdict"], "PASS")
        ledger = self.loop(self.report("a" * 40, self.dead()), after)
        record = ledger[self.DESKTOP]
        self.held(record, "missing")
        self.assertIn("no longer reports restart.works@desktop", record["history"][-1]["note"])
        self.assertIsNone(record["verification"]["after"]["status"])

    def test_a_repair_that_makes_the_check_not_applicable_is_not_verified(self):
        """(c) The game stops offering a loss (the genre family's failure_state is false):
        lose.reachable is SKIPPED and restart.works is BLOCKED with no loss to retry from."""
        def lossless(project):
            records = self.fixed()
            records["lose"].update(reached=None, restart=None)
            return records
        qa = {"genre": {"failure_state": False}}
        after = self.report("b" * 40, lossless, qa=qa)
        statuses = {c["id"]: c["status"] for c in after["checks"] if c["project"] == "desktop"}
        self.assertEqual((statuses["lose.reachable"], statuses["restart.works"]),
                         ("SKIPPED", "BLOCKED"))
        ledger = self.loop(self.report("a" * 40, self.dead()), after)
        self.held(ledger[self.DESKTOP], "unmeasured")

    def test_a_not_applicable_lose_check_does_not_verify_its_finding(self):
        """(c) for the check that becomes SKIPPED itself: lose.reachable failed, and the
        repair declares there is no loss."""
        def unlosable(project):
            records = self.fixed()
            records["lose"].update(reached=None, restart=None)
            return records
        before = self.report("a" * 40, unlosable)
        after = self.report("b" * 40, unlosable, qa={"genre": {"failure_state": False}})
        fid = "playability-report:lose.reachable@desktop"
        a, b = "a" * 40, "b" * 40
        docs = {"game-design": DESIGN_2D, "prototype-report": _proto(a, 1),
                "playability-report": before}
        seqs = {"prototype-report": 5, "playability-report": 8}
        first = run_triage(docs, seqs=seqs, entered="playability.fail")
        ledger = {r["id"]: r for r in first.artifacts[0].content["lifecycle"]}
        docs.update({"triage-report": first.artifacts[0].content,
                     "prototype-report": _proto(b, 2, {"role": ledger[fid]["owner"],
                                                       "findings": [fid]}),
                     "playability-report": after})
        seqs.update({"triage-report": 9, "prototype-report": 11, "playability-report": 13})
        second = run_triage(docs, seqs=seqs, entered="playability.success")
        record = {r["id"]: r for r in second.artifacts[0].content["lifecycle"]}[fid]
        self.held(record, "unmeasured")
        self.assertEqual(record["verification"]["after"]["status"], "SKIPPED")

    def test_a_pass_on_another_viewport_only_is_not_verified(self):
        """(d) The re-play ran on desktop only: desktop is verified, mobile's finding is
        missing from the report and stays open."""
        after = self.report("b" * 40, self.fixed(), played=("desktop",))
        ledger = self.loop(self.report("a" * 40, self.dead()), after)
        self.assertEqual(ledger[self.DESKTOP]["verification"]["verdict"], "passed")
        self.held(ledger[self.MOBILE], "missing")
        self.assertIn("restart.works@mobile", ledger[self.MOBILE]["history"][-1]["note"])

    def test_a_pass_measured_on_the_commit_that_failed_is_not_a_repair(self):
        a = "a" * 40
        ledger = self.loop(self.report(a, self.dead()), self.report(a, self.fixed()),
                           commits=(a, a))
        self.held(ledger[self.DESKTOP], "same-build")

    def test_a_repair_that_breaks_a_passing_check_is_regressed(self):
        """Existing behaviour, held with scenarios: the restart is fixed, but play is now
        lost with no input (idle.grace passed before) - not verified, the regression named,
        and both measurements kept."""
        def broke(project):
            records = self.fixed()
            records["first-session"]["lostAtMs"] = 2700
            return records
        ledger = self.loop(self.report("a" * 40, self.dead()), self.report("b" * 40, broke))
        record = ledger[self.DESKTOP]
        self.assertEqual(record["status"], "implemented")
        self.assertEqual(record["verification"]["verdict"], "regressed")
        self.assertIn("playability-report:idle.grace@desktop",
                      record["verification"]["regressions"])
        self.assertEqual(record["verification"]["after"]["status"], "PASS")
        self.assertEqual(record["verification"]["before"]["status"], "FAIL")

    def test_a_check_failing_in_a_blocked_report_still_fails(self):
        """A BLOCKED report's findings are never normalized: its FAIL check used to read as
        'not failing' and verify the finding."""
        from wgf_triage import lifecycle
        before = self.report("a" * 40, self.dead())
        after = self.report("b" * 40, self.dead())
        after["verdict"] = "BLOCKED"  # (a host problem elsewhere in the same play)
        finding = next(f for f in normalize("playability-report", before, ROUTING)
                       if f["id"] == self.DESKTOP)
        finding["build"] = {"commit": "a" * 40, "digest": None}
        records = lifecycle.advance(
            [], at="t", current=[finding], failing={"playability-report": {self.DESKTOP}},
            seqs={"playability-report": 8}, reports={"playability-report": before},
            proto=None, proto_seq=5, decision=None, decision_seq=-1, human_ids=set(),
            selected=None, triage_id="t1", routing_version="x",
            build_of=lambda k: {"commit": "a" * 40, "digest": None})
        out = lifecycle.advance(
            records, at="t", current=[], failing={"playability-report": set()},
            seqs={"playability-report": 12}, reports={"playability-report": after},
            proto=None, proto_seq=5, decision=None, decision_seq=-1, human_ids=set(),
            selected=None, triage_id="t2", routing_version="x",
            build_of=lambda k: {"commit": "b" * 40, "digest": None})
        record = next(r for r in out if r["id"] == self.DESKTOP)
        self.assertEqual(record["status"], "classified")
        self.assertIsNone(record["verification"])

    def no_fix(self, after, after_commit="b" * 40):
        """The no-fix path: detected on a, never routed, re-measured on `after`."""
        from wgf_triage import lifecycle
        before = self.report("a" * 40, self.dead())
        found = [f for f in normalize("playability-report", before, ROUTING)]
        for f in found:
            f["build"] = {"commit": "a" * 40, "digest": None}
        records = lifecycle.advance(
            [], at="t", current=found, failing={"playability-report": {f["id"] for f in found}},
            seqs={"playability-report": 8}, reports={"playability-report": before},
            proto=None, proto_seq=5, decision=None, decision_seq=-1, human_ids=set(),
            selected=None, triage_id="t1", routing_version="x",
            build_of=lambda k: {"commit": "a" * 40, "digest": None})
        failing = {f["id"] for f in normalize("playability-report", after, ROUTING)} \
            if after["verdict"] == "FAIL" else set()
        out = lifecycle.advance(
            records, at="t", current=[], failing={"playability-report": failing},
            seqs={"playability-report": 12}, reports={"playability-report": after},
            proto=None, proto_seq=5, decision=None, decision_seq=-1, human_ids=set(),
            selected=None, triage_id="t2", routing_version="x",
            build_of=lambda k: {"commit": after_commit, "digest": None})
        return {r["id"]: r for r in out}

    def test_the_rule_holds_with_no_recorded_fix_too(self):
        verified = self.no_fix(self.report("b" * 40, self.fixed()))[self.DESKTOP]
        self.assertEqual(verified["status"], "closed")
        self.assertEqual(verified["verification"]["before"]["commit"], "a" * 40)
        self.assertEqual(verified["verification"]["after"]["commit"], "b" * 40)
        removed = self.no_fix(self.report("b" * 40, self.dead(), change=lambda checks: [
            c for c in checks if c["id"] != "restart.works"]))[self.DESKTOP]
        self.assertEqual((removed["status"], removed["verification"]["verdict"]),
                         ("classified", "missing"))
        mobile_only = self.no_fix(self.report("b" * 40, self.fixed(), played=("mobile",)))
        self.assertEqual(mobile_only[self.DESKTOP]["verification"]["verdict"], "missing")
        self.assertEqual(mobile_only[self.MOBILE]["status"], "closed")
        replayed = self.no_fix(self.report("a" * 40, self.fixed()),
                               after_commit="a" * 40)[self.DESKTOP]
        self.assertEqual(replayed["verification"]["verdict"], "same-build")

    def test_a_held_verdict_is_noted_once_per_report(self):
        from wgf_triage import lifecycle
        after = self.report("b" * 40, self.dead(), change=lambda checks: [
            c for c in checks if c["id"] != "restart.works"])
        first = self.no_fix(after)
        again = lifecycle.advance(
            list(first.values()), at="t", current=[], failing={"playability-report": set()},
            seqs={"playability-report": 12}, reports={"playability-report": after},
            proto=None, proto_seq=5, decision=None, decision_seq=-1, human_ids=set(),
            selected=None, triage_id="t3", routing_version="x",
            build_of=lambda k: {"commit": "b" * 40, "digest": None})
        record = next(r for r in again if r["id"] == self.DESKTOP)
        self.assertEqual(len(record["history"]), len(first[self.DESKTOP]["history"]))

    def test_a_check_measured_passing_before_the_fix_that_fails_after_is_a_regression(self):
        """The baseline: idle.grace passed on A (when the restart finding was assigned) and
        fails on B - a regression. page.errors, not listed on A at all, failing on B is a new
        finding, not a regression."""
        def broke(project):
            records = self.fixed()
            records["first-session"]["lostAtMs"] = 2700
            return records
        before = self.report("a" * 40, self.dead(), change=lambda checks: [
            c for c in checks if c["id"] != "page.errors"])
        def errors(project):
            records = self.fixed()
            records["win"]["errors"] = ["TypeError: x is undefined"]
            return records
        ledger = self.loop(before, self.report("b" * 40, errors))
        record = ledger[self.DESKTOP]
        self.assertIn("playability-report:idle.grace@desktop",
                      record["baseline"]["playability-report"]["passing"])
        self.assertNotIn("playability-report:page.errors@desktop",
                         record["baseline"]["playability-report"]["passing"])
        self.assertEqual(record["verification"]["verdict"], "passed")
        self.assertEqual(ledger["playability-report:page.errors@desktop"]["status"],
                         "assigned")
        regressed = self.loop(self.report("a" * 40, self.dead()), self.report("b" * 40, broke))
        self.assertEqual(regressed[self.DESKTOP]["verification"]["regressions"],
                         ["playability-report:idle.grace@desktop",
                          "playability-report:idle.grace@mobile"])

    def test_history_names_each_report_by_hash_and_seq(self):
        """Two playability reports share one artifact id (greybox and develop): the history
        says which was which."""
        before = self.report("a" * 40, self.dead(), execution=1)
        after = self.report("b" * 40, self.fixed(), execution=1)
        self.assertEqual(before["provenance"]["artifact_id"], after["provenance"]["artifact_id"])
        record = self.loop(before, after)[self.DESKTOP]
        detected = record["history"][0]
        verified = next(h for h in record["history"] if h["status"] == "verified")
        self.assertEqual(detected["by"], verified["by"])
        self.assertEqual(detected["content_hash"], before["provenance"]["content_hash"])
        self.assertEqual(verified["content_hash"], after["provenance"]["content_hash"])
        self.assertEqual((detected["seq"], verified["seq"]), (8, 13))
        ver = record["verification"]
        self.assertEqual((ver["before"]["content_hash"], ver["after"]["content_hash"]),
                         (before["provenance"]["content_hash"],
                          after["provenance"]["content_hash"]))
        self.assertEqual((ver["before"]["seq"], ver["after"]["seq"]), (8, 13))

    def test_samples_count_the_passes_after_verification(self):
        """One pass is a single sample; each later report passing the same check adds one;
        a later report that does not measure it adds none."""
        from wgf_triage import lifecycle
        ledger = self.loop(self.report("a" * 40, self.dead()), self.report("b" * 40, self.fixed()))
        record = ledger[self.DESKTOP]
        self.assertEqual([x["seq"] for x in record["verification"]["samples"]], [13])

        def again(records, report, seq):
            return {r["id"]: r for r in lifecycle.advance(
                list(records.values()), at="t", current=[],
                failing={"playability-report": set()}, seqs={"playability-report": seq},
                reports={"playability-report": report}, proto=None, proto_seq=11,
                decision=None, decision_seq=-1, human_ids=set(), selected=None,
                triage_id="t", routing_version="x",
                build_of=lambda k: {"commit": report["commit"], "digest": None})}
        ledger = again(ledger, self.report("b" * 40, self.fixed()), 15)
        ledger = again(ledger, self.report("c" * 40, self.dead(), change=lambda checks: [
            c for c in checks if c["id"] != "restart.works"]), 17)
        ledger = again(ledger, self.report("c" * 40, self.fixed()), 19)
        self.assertEqual([x["seq"] for x in ledger[self.DESKTOP]["verification"]["samples"]],
                         [13, 15, 19])
        self.assertEqual(ledger[self.DESKTOP]["status"], "closed")

    def test_measurement_states(self):
        from wgf_triage import measurement
        fid = "playability-report:restart.works@desktop"
        src = {"check": "restart.works", "project": "desktop"}

        def report(**check):
            return {"checks": [dict({"id": "restart.works", "project": "desktop",
                                     "required": True, "summary": "x"}, **check)]}
        for status, expected in (("PASS", "pass"), ("FAIL", "fail"), ("BLOCKED", "unmeasured"),
                                 ("SKIPPED", "unmeasured"), ("WARNING", "unmeasured")):
            self.assertEqual(measurement.state("playability-report", report(status=status),
                                               fid, src, set()), expected, status)
        # A pass with nothing measured is not a pass; a held FAIL with nothing measured fails.
        self.assertEqual(measurement.state(
            "playability-report", report(status="PASS", measured={"unmeasured": "x"}), fid, src,
            set()), "unmeasured")
        self.assertEqual(measurement.state(
            "playability-report", report(status="FAIL", measured={"unmeasured": "x"}), fid, src,
            {fid}), "fail")
        self.assertEqual(measurement.state(
            "playability-report", report(status="PASS", project="mobile"), fid, src, set()),
            "missing")

    def test_other_producers_keep_their_rule(self):
        """visual-qa lists no checks with a status: its rule is unchanged - the newest report
        not failing the id (FindingLifecycle holds it in full)."""
        from wgf_triage import measurement
        self.assertIsNone(measurement.state("visual-qa-report", {}, "x", {}, set()))
        self.assertEqual(measurement.CHECKED, ("playability-report",
                                               "production-quality-report",
                                               "listing-validation-report"))

    def test_real_recorded_naive_play(self):
        """REAL bot records (scripts/tests/fixtures/real/play-realism, this bot's naive test
        on the 3D game's builds, 2026-10-07): 1c6b099, the regressed head, FAILs naive.pace;
        c340631, the r1-forward repair of it, PASSes. Through the scenarios and the ledger the
        repair is verified on the same scenario, with the real runs' policies listed."""
        import test_play_realism as tpr
        from wgf_playability import analysis, realism
        from wgf_playability import scenario as scenarios
        from wgf_playability.step import PlayabilityStep
        reports = {}
        for visit, commit in enumerate(("1c6b099", "c340631"), 1):
            record = tpr.real(f"naive-bot-3d-{commit}.json")["record"]
            units = [{"id": u["id"], "parameters": u.get("parameters") or {}}
                     for u in tpr.real(f"content-3d-{commit}.json")["units"]]
            out = os.path.join(self.run, "playability", f"{visit}-1", "out")
            os.makedirs(os.path.join(out, "desktop"))
            with open(os.path.join(out, "desktop", "naive.json"), "w", encoding="utf-8") as h:
                json.dump(record, h)
            with open(os.path.join(out, "settings.json"), "w", encoding="utf-8") as h:
                json.dump({}, h)  # the real settings were not kept: nothing is claimed of them
            rules = load_file(os.path.join(paths.REFERENCE, "visual-quality.yaml"))
            checks = analysis._environment(
                realism.judge({"naive": record}, tpr.D3, tpr.RULES, "desktop", tpr.RELEASE,
                              units),
                {"naive": record}, rules.get("environment") or {}, {})
            projects = [{"id": "desktop", "viewport": {"width": 1280, "height": 720},
                         "ran": True}]
            handed, sha = scenarios.settings_of(out)
            bot = {"version": self.tp.BOT_A, "settings_sha256": sha}
            checks, found = scenarios.build(checks, projects, [], {"desktop": {"naive": record}},
                                            out, self.run, bot=bot, settings=handed)
            full = commit.ljust(40, "0")
            report = PlayabilityStep(types.SimpleNamespace(params={}))._finish(
                types.SimpleNamespace(logger=Log(), execution=visit),
                types.SimpleNamespace(refs={}), "demo", full, checks, [], {}, None, projects,
                os.path.relpath(out, self.run).replace(os.sep, "/"), bot=bot,
                scenarios=found).artifacts[0].content
            self.assertEqual(ArtifactContracts()("playability-report", report), [])
            reports[commit] = report
        fid = "playability-report:naive.pace@desktop"
        self.assertIn("desktop:naive.pace", reports["1c6b099"]["failed_checks"])
        pace = next(s for s in reports["1c6b099"]["scenarios"] if s["id"] == "naive.pace@desktop")
        # The runs as the real record lists them: each policy, unit, inputs and time.
        self.assertEqual(pace["policy"]["recordings"], {"naive": "naive"})
        self.assertEqual({a["action"] for a in pace["actions"]}, {"steady", "jitter"})
        first = pace["actions"][0]
        self.assertEqual((first["action"], first["phase"], first["count"], first["at_ms"]),
                         ("steady", "meadow-roll", 17, 6829))
        self.assertFalse(pace["actions_complete"])
        a, b = "1c6b099".ljust(40, "0"), "c340631".ljust(40, "0")
        docs = {"game-design": DESIGN_3D, "prototype-report": _proto(a, 1),
                "playability-report": reports["1c6b099"]}
        seqs = {"prototype-report": 5, "playability-report": 8}
        first = run_triage(docs, seqs=seqs, entered="playability.fail")
        ledger = {r["id"]: r for r in first.artifacts[0].content["lifecycle"]}
        docs.update({"triage-report": first.artifacts[0].content,
                     "prototype-report": _proto(b, 2, {"role": ledger[fid]["owner"],
                                                       "findings": [fid]}),
                     "playability-report": reports["c340631"]})
        seqs.update({"triage-report": 9, "prototype-report": 11, "playability-report": 13})
        second = run_triage(docs, seqs=seqs, entered="playability.success")
        record = {r["id"]: r for r in second.artifacts[0].content["lifecycle"]}[fid]
        ver = record["verification"]
        self.assertEqual(ver["verdict"], "passed")
        self.assertEqual((ver["before"]["commit"], ver["after"]["commit"]), (a, b))
        self.assertEqual((ver["before"]["status"], ver["after"]["status"]), ("FAIL", "PASS"))
        self.assertTrue(ver["comparison"]["same_scenario"], ver["comparison"])


class BaselineAcrossReports(unittest.TestCase):
    """Review r1 finding 6: a record's regression baseline is what the gates had MEASURED,
    check by check - not only what the newest report says. When the newest report of a
    producer is BLOCKED (its check unmeasured), a pass the ledger recorded earlier still
    counts: a fix that then breaks that check is a regression, not a verified repair."""

    PQ = "production-quality-report"
    LOADED = "production-quality-report:assets.loaded"
    MIX = "production-quality-report:audio.mix"
    TARGETS = "production-quality-report:ui.targets"

    @staticmethod
    def report(commit, seq, verdict, **statuses):
        return {"title_id": "demo", "commit": commit, "verdict": verdict,
                "provenance": {"artifact_id": f"production-quality-report-{seq}",
                               "content_hash": "sha256:" + f"{seq:02d}" * 32},
                "checks": [{"id": cid.replace("_", "."), "status": st, "required": True,
                            "summary": cid, "route": "develop"}
                           for cid, st in statuses.items()]}

    def advance(self, previous, report, seq, commit, *, current=(), selected=None, proto=None,
                proto_seq=-1):
        from wgf_triage import lifecycle
        failing = {f["id"] for f in normalize(self.PQ, report, ROUTING)} \
            if report["verdict"] == "FAIL" else set()
        found = list(current)
        for f in found:
            f["build"] = {"commit": commit, "digest": None}
        return lifecycle.advance(
            previous, at="t", current=found, failing={self.PQ: failing}, seqs={self.PQ: seq},
            reports={self.PQ: report}, proto=proto, proto_seq=proto_seq, decision=None,
            decision_seq=-1, human_ids=set(),
            selected={"findings": selected, "owner": "gameplay", "label": "develop"}
            if selected else None, triage_id=f"t{seq}", routing_version="x",
            build_of=lambda k: {"commit": commit, "digest": None})

    def test_a_pass_before_a_blocked_report_is_still_in_the_baseline(self):
        a, b, c = "a" * 40, "b" * 40, "c" * 40
        first = self.report(a, 8, "FAIL", assets_loaded="FAIL", ui_targets="PASS",
                            audio_mix="FAIL")
        ledger = self.advance([], first, 8, a, current=normalize(self.PQ, first, ROUTING),
                              selected=[self.LOADED])
        records = {r["id"]: r for r in ledger}
        self.assertIn(self.TARGETS, records[self.LOADED]["baseline"][self.PQ]["passing"])
        # The visit fixes assets.loaded on B; production-quality re-measures B BLOCKED (a
        # stale input), ui.targets unmeasured. The next triage assigns audio.mix.
        blocked = self.report(b, 12, "BLOCKED", assets_loaded="PASS", ui_targets="BLOCKED",
                              audio_mix="FAIL")
        ledger = self.advance(ledger, blocked, 12, b, selected=[self.MIX],
                              proto=_proto(b, 2, {"role": "gameplay",
                                                  "findings": [self.LOADED]}), proto_seq=11)
        records = {r["id"]: r for r in ledger}
        self.assertIn(records[self.LOADED]["status"], ("verified", "closed"))
        self.assertEqual(records[self.MIX]["status"], "assigned")
        self.assertIn(self.TARGETS, records[self.MIX]["baseline"][self.PQ]["passing"])
        # The audio fix on C breaks ui.targets, which passed on A: a regression of it.
        broken = self.report(c, 16, "FAIL", assets_loaded="PASS", ui_targets="FAIL",
                             audio_mix="PASS")
        ledger = self.advance(ledger, broken, 16, c, current=normalize(self.PQ, broken, ROUTING),
                              proto=_proto(c, 3, {"role": "gameplay", "findings": [self.MIX]}),
                              proto_seq=15)
        record = {r["id"]: r for r in ledger}[self.MIX]
        self.assertEqual(record["status"], "implemented", record["history"][-1])
        self.assertEqual(record["verification"]["verdict"], "regressed")
        self.assertEqual(record["verification"]["regressions"], [self.TARGETS])

    def test_a_check_failing_since_the_earlier_pass_is_not_carried(self):
        """The newer measurement wins: a check that passed on A and FAILED on B (a finding
        the ledger recorded) is not a pass of the baseline taken on a BLOCKED C."""
        a, b, c = "a" * 40, "b" * 40, "c" * 40
        first = self.report(a, 8, "FAIL", assets_loaded="FAIL", ui_targets="PASS",
                            audio_mix="PASS")
        ledger = self.advance([], first, 8, a, current=normalize(self.PQ, first, ROUTING),
                              selected=[self.LOADED])
        second = self.report(b, 12, "FAIL", assets_loaded="FAIL", ui_targets="FAIL",
                             audio_mix="PASS")
        ledger = self.advance(ledger, second, 12, b, current=normalize(self.PQ, second,
                                                                       ROUTING))
        blocked = self.report(c, 16, "BLOCKED", assets_loaded="FAIL", ui_targets="BLOCKED",
                              audio_mix="PASS")
        ledger = self.advance(ledger, blocked, 16, c, selected=[self.TARGETS])
        record = {r["id"]: r for r in ledger}[self.TARGETS]
        self.assertEqual(record["status"], "assigned")
        self.assertNotIn(self.TARGETS, record["baseline"][self.PQ]["passing"])
        self.assertIn("production-quality-report:audio.mix",
                      record["baseline"][self.PQ]["passing"])


REAL_TRIAGE_V12 = os.path.join(HERE, "fixtures", "real", "triage-hygiene", "triage-v12-3d.json.gz")
NOTED_OFF_ROUTING = None


def _routing_without_noted(tmp):
    """The shipped routing data with `ledger.noted_on_pass` removed: the ledger as it was
    before passing reports' findings were recorded (the control the fix is compared with)."""
    with open(os.path.join(paths.REFERENCE, "specialist-routing.yaml"), encoding="utf-8") as h:
        text = h.read()
    head, sep, tail = text.partition("  noted_on_pass:\n")
    assert sep, "specialist-routing.yaml has no ledger.noted_on_pass"
    rest = tail.split("\n")
    while rest and rest[0].startswith("    "):
        rest.pop(0)
    path = os.path.join(tmp, "specialist-routing.yaml")
    with open(path, "w", encoding="utf-8", newline="\n") as h:
        h.write(head + "\n".join(rest))
    return path


class _RealInputs:
    """The real inputs of one triage, each with its real run-local seq and content hash."""

    def __init__(self, entries):
        self.docs = {k: v["content"] for k, v in entries.items()}
        self.refs = {k: types.SimpleNamespace(id=v["content"]["provenance"]["artifact_id"],
                                              type=k, seq=v["seq"],
                                              content_hash=v["content_hash"])
                     for k, v in entries.items()}

    def __contains__(self, k):
        return k in self.docs

    def load(self, k):
        return self.docs[k]


class PassingReportFindings(unittest.TestCase):
    """K7 #4 (retro H12): a report that PASSES can still name blocker or major findings of
    its own. The 3D run's visual-qa v3 passed the build with two MAJOR findings (the
    objective banner covers the goal; the marble loses contrast on dusk worlds), and the
    triage that read it (triage-report v12) recorded neither: only failing reports were
    normalized. specialist-routing 1.7.0 `ledger.noted_on_pass`: they are recorded in the
    ledger as `noted` - detected and classified to their owner, never routed, never holding
    the build (the producer passed it: no gate verdict or release decision changes)."""

    BANNER = "visual-qa-report:finding:banner-covers-goal"
    CONTRAST = "visual-qa-report:finding:marble-low-contrast-storm"
    STUDS = "visual-qa-report:finding:marble-beads-read-as-studs"

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="wgf-noted-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    @staticmethod
    def bundle():
        import gzip
        with gzip.open(REAL_TRIAGE_V12, "rb") as handle:
            return json.loads(handle.read().decode("utf-8"))

    def replay(self, bundle, routing_path=None):
        """Triage v12 of the real 3D run again, on its real inputs, at a fixed clock."""
        context = types.SimpleNamespace(entered_by=bundle["real_triage_v12"]["entered_by"],
                                        run_dir=self.tmp, logger=Log(), execution=12,
                                        visit=12, project_id="sky-marble")
        step = TriageStep(types.SimpleNamespace(id="triage", params={}, on=dict(ON)))
        step.clock = staticmethod(lambda: "2026-10-05T14:19:18Z")
        if routing_path:
            step.routing_path = routing_path
        result = step.execute(_RealInputs(bundle["inputs"]), context)
        for artifact in result.artifacts:
            self.assertEqual(ArtifactContracts()("triage-report", artifact.content), [])
        return result

    def test_the_real_passing_visual_qa_majors_are_recorded_noted_never_routed(self):
        """REAL: visual-qa-report v3 of the 3D run (verdict PASS, 3f394e2) replayed through
        the triage that read it (v12, entered by content-sufficiency.develop)."""
        bundle = self.bundle()
        vqa = bundle["inputs"]["visual-qa-report"]["content"]
        self.assertEqual(vqa["verdict"], "PASS")
        self.assertEqual(vqa["provenance"]["artifact_id"],
                         "wgf:visual-qa-report:sky-marble:20261005-03")
        real = bundle["real_triage_v12"]
        # what the run recorded: neither major anywhere in its ledger
        self.assertNotIn(self.BANNER, real["lifecycle_ids"])
        self.assertNotIn(self.CONTRAST, real["lifecycle_ids"])

        result = self.replay(bundle)
        report = result.artifacts[0].content
        # the route and what is routed are the run's own
        self.assertEqual(result.route, real["selected"]["label"])
        self.assertEqual(report["verdict"], real["verdict"])
        self.assertEqual([f["id"] for f in report["findings"]],
                         [f["id"] for f in real["findings"]])
        records = {r["id"]: r for r in report["lifecycle"]}
        for fid, word in ((self.BANNER, "composition"), (self.CONTRAST, "lighting")):
            owner = ROUTING.owner(ROUTING.resolve_word(word, "3d"))
            record = records.get(fid)
            self.assertIsNotNone(record, f"{fid} is not in the ledger")
            self.assertEqual(record["severity"], "major")
            self.assertEqual(record["status"], "classified")
            self.assertEqual(record["owner"], owner)
            self.assertEqual(record["noted"]["verdict"], "PASS")
            self.assertEqual(record["noted"]["artifact_id"],
                             "wgf:visual-qa-report:sky-marble:20261005-03")
            self.assertEqual(record["noted"]["seq"], 72)
            self.assertEqual(record["build"]["commit"], vqa["commit"])
            self.assertEqual([h["status"] for h in record["history"]][:2],
                             ["detected", "classified"])
            self.assertNotIn(fid, {f for g in report["groups"] for f in g["findings"]})
        # a minor finding of a passing report is not recorded (minors never hold a build)
        self.assertNotIn(self.STUDS, records)
        self.assertEqual(sorted(n["finding"] for n in report["noted"]),
                         sorted([self.BANNER, self.CONTRAST]))

    def test_noted_on_pass_names_known_producers_and_severities(self):
        self.assertEqual(ROUTING.problems(), [])
        data = json.loads(json.dumps(ROUTING.data))
        data["ledger"]["noted_on_pass"] = {"no-such-report": ["major"],
                                           "visual-qa-report": ["fatal"]}
        problems = Routing(data, {"roles": ROUTING.roles}).problems()
        self.assertTrue(any("no-such-report" in p for p in problems), problems)
        self.assertTrue(any("'fatal'" in p for p in problems), problems)

    def test_the_real_replay_changes_no_gate_outcome(self):
        """REAL: with and without `noted_on_pass`, the same route, groups and held findings,
        the same ledger apart from the noted records, and the same blocking set - what the
        quality gate is BLOCKED on and release refuses."""
        from wgf_triage import ledger as ledgers
        bundle = self.bundle()
        on = self.replay(bundle).artifacts[0].content
        off_routing = _routing_without_noted(self.tmp)
        off_result = self.replay(bundle, routing_path=off_routing)
        off = off_result.artifacts[0].content
        for key in ("verdict", "selected", "groups", "pending", "deferred", "held", "findings",
                    "ledger"):
            self.assertEqual(on[key], off[key], key)
        noted = {r["id"] for r in on["lifecycle"] if r.get("noted")}
        self.assertEqual(noted, {self.BANNER, self.CONTRAST})
        self.assertEqual([r for r in on["lifecycle"] if r["id"] not in noted],
                         off["lifecycle"])
        self.assertNotIn("noted", off)
        self.assertEqual(
            [r["id"] for r in ledgers.blocking(on["lifecycle"], ROUTING)],
            [r["id"] for r in ledgers.blocking(off["lifecycle"], ROUTING)])

    # -- the noted record's lifecycle (FIXTURE reports) ------------------------------------

    def vqa(self, commit, seq, *, banner=True, verdict="PASS", blocker=False):
        findings = ([{"id": "banner-covers-goal", "severity": "major",
                      "category": "composition", "frame": None, "route": "develop",
                      "summary": "the objective banner covers the goal"}] if banner else [])
        if blocker:
            findings.append({"id": "black-ground", "severity": "blocker",
                             "category": "readability", "frame": None, "route": "develop",
                             "summary": "the ground renders black"})
        report = visual_qa(scores={"environment": 4}, findings=findings,
                           failed=["finding:black-ground"] if blocker else [],
                           verdict=verdict)
        report["commit"] = commit
        report["provenance"] = {"artifact_id": f"visual-qa-report-{seq}",
                                "content_hash": "sha256:" + f"{seq:02d}" * 32}
        return report

    @staticmethod
    def proto(commit, iteration, specialist=None):
        body = {"title_id": "demo", "iteration": iteration,
                "provenance": {"artifact_id": f"prototype-report-demo-{iteration}"},
                "build_ref": {"commit_sha": commit}}
        if specialist:
            body["specialist"] = specialist
        return body

    @staticmethod
    def records(result):
        return {r["id"]: r for r in result.artifacts[0].content["lifecycle"]}

    def test_a_noted_finding_stays_open_while_listed_and_is_verified_when_gone(self):
        a, b, c = "a" * 40, "b" * 40, "c" * 40
        docs = {"game-design": DESIGN_3D, "prototype-report": self.proto(a, 1),
                "visual-qa-report": self.vqa(a, 8)}
        seqs = {"prototype-report": 5, "visual-qa-report": 8}
        first = run_triage(docs, seqs=seqs, entered=None)
        self.assertIsNone(first.route)  # nothing failed: the first pass is unchanged
        record = self.records(first)[self.BANNER]
        self.assertEqual((record["status"], record["noted"]["seq"]), ("classified", 8))
        self.assertEqual(first.artifacts[0].content["verdict"], "clear")
        # the next build, the judge still lists it on a passing report: not verified
        docs.update({"triage-report": first.artifacts[0].content,
                     "prototype-report": self.proto(b, 2),
                     "visual-qa-report": self.vqa(b, 14)})
        seqs.update({"triage-report": 9, "prototype-report": 11, "visual-qa-report": 14})
        second = run_triage(docs, seqs=seqs, entered=None)
        record = self.records(second)[self.BANNER]
        self.assertEqual(record["status"], "classified")
        self.assertEqual(record["noted"]["seq"], 14)
        self.assertEqual(record["build"]["commit"], b)
        self.assertIn("listed again", record["history"][-1]["note"])
        # never verified while the judge still lists it: no `verified` (or `closed`) entry,
        # no passing verification (review r2 F3)
        self.assertEqual([h for h in record["history"] if h["status"] in ("verified",
                                                                         "closed")], [])
        self.assertIsNone(record["verification"])
        # a newer build the judge no longer lists it on: verified, with no fix recorded
        docs.update({"triage-report": second.artifacts[0].content,
                     "prototype-report": self.proto(c, 3),
                     "visual-qa-report": self.vqa(c, 18, banner=False)})
        seqs.update({"triage-report": 15, "prototype-report": 16, "visual-qa-report": 18})
        third = run_triage(docs, seqs=seqs, entered=None)
        record = self.records(third)[self.BANNER]
        self.assertIn(record["status"], ("verified", "closed"))
        self.assertEqual(record["verification"]["seq"], 18)

    def test_a_failing_report_raising_it_makes_it_an_ordinary_routed_finding(self):
        a, b = "a" * 40, "b" * 40
        docs = {"game-design": DESIGN_3D, "prototype-report": self.proto(a, 1),
                "visual-qa-report": self.vqa(a, 8)}
        seqs = {"prototype-report": 5, "visual-qa-report": 8}
        first = run_triage(docs, seqs=seqs, entered=None)
        docs.update({"triage-report": first.artifacts[0].content,
                     "prototype-report": self.proto(b, 2),
                     "visual-qa-report": self.vqa(b, 14, verdict="FAIL", blocker=True)})
        seqs.update({"triage-report": 9, "prototype-report": 11, "visual-qa-report": 14})
        second = run_triage(docs, seqs=seqs)
        record = self.records(second)[self.BANNER]
        self.assertNotIn("noted", record)
        self.assertEqual(record["status"], "assigned")
        self.assertIn(self.BANNER, second.artifacts[0].content["selected"]["findings"])
        self.assertTrue(any("failing report" in str(h.get("note")) for h in record["history"]))

    def test_the_quality_gate_holds_a_noted_record_still_listed_and_is_not_blocked_by_it(self):
        from wgf_triage import ledger as ledgers
        a, b = "a" * 40, "b" * 40
        docs = {"game-design": DESIGN_3D, "prototype-report": self.proto(a, 1),
                "visual-qa-report": self.vqa(a, 8)}
        seqs = {"prototype-report": 5, "visual-qa-report": 8}
        first = run_triage(docs, seqs=seqs, entered=None)
        docs.update({"triage-report": first.artifacts[0].content,
                     "prototype-report": self.proto(b, 2),
                     "visual-qa-report": self.vqa(b, 14)})
        seqs.update({"triage-report": 9, "prototype-report": 11, "visual-qa-report": 14})
        inputs = Inputs(docs, seqs)
        lifecycle = ledgers.remeasure(inputs.refs, inputs.load, at="2026-10-10T00:00:00Z",
                                      by="quality-report-x", routing=ROUTING)
        record = {r["id"]: r for r in lifecycle}[self.BANNER]
        self.assertEqual(record["status"], "classified")
        self.assertTrue(record.get("noted"))
        self.assertEqual(ledgers.blocking(lifecycle, ROUTING), [])

    def test_an_ordinary_finding_listed_by_a_passing_report_keeps_its_status_and_is_noted(self):
        """A major the judge raised on a FAIL report, listed again on the next PASS report:
        its status is what it was without this rule (no verdict changes); its history
        says the passing report still listed it."""
        a, b = "a" * 40, "b" * 40
        docs = {"game-design": DESIGN_3D, "prototype-report": self.proto(a, 1),
                "visual-qa-report": self.vqa(a, 8, verdict="FAIL", blocker=True)}
        seqs = {"prototype-report": 5, "visual-qa-report": 8}
        first = run_triage(docs, seqs=seqs)
        docs.update({"triage-report": first.artifacts[0].content,
                     "prototype-report": self.proto(b, 2),
                     "visual-qa-report": self.vqa(b, 14)})
        seqs.update({"triage-report": 9, "prototype-report": 11, "visual-qa-report": 14})
        on = self.records(run_triage(docs, seqs=seqs, entered=None))[self.BANNER]
        step_off = _routing_without_noted(self.tmp)
        context = types.SimpleNamespace(entered_by=None, run_dir=None, logger=Log(),
                                        execution=1, visit=1, project_id="demo")
        step = TriageStep(types.SimpleNamespace(id="triage", params={}, on=dict(ON)))
        step.routing_path = step_off
        off = {r["id"]: r for r in step.execute(Inputs(docs, seqs), context)
               .artifacts[0].content["lifecycle"]}[self.BANNER]
        self.assertNotIn("noted", on)
        self.assertEqual(on["status"], off["status"])
        self.assertTrue(any("passing" in str(h.get("note")) for h in on["history"]))
        # what its history says of its status is true (review r1 minor 3): the passing
        # report verified it in this same advance, so "unchanged" would be false
        listed = [h for h in on["history"] if str(h.get("note") or "").startswith(
            "listed by a passing")]
        self.assertEqual(len(listed), 1)
        self.assertNotIn("unchanged", listed[0]["note"])
        self.assertIn(on["status"], listed[0]["note"])

    # -- review r1: the quality gate / release path, and evidence strength (FIXTURE) -------

    def noted_then(self, *later):
        """A noted record (visual-qa PASS at seq 8 lists the banner), then each of `later`
        - (vqa report, seq, "triage" | "remeasure") - advancing the ledger in turn. Returns
        every ledger, newest last."""
        from wgf_triage import ledger as ledgers
        a = "a" * 40
        docs = {"game-design": DESIGN_3D, "prototype-report": self.proto(a, 1),
                "visual-qa-report": self.vqa(a, 8)}
        seqs = {"prototype-report": 5, "visual-qa-report": 8}
        ledgers_seen = [run_triage(docs, seqs=seqs, entered=None).artifacts[0].content]
        for report, seq, how in later:
            docs.update({"triage-report": {"lifecycle": ledgers_seen[-1][-1]}
                         if isinstance(ledgers_seen[-1], list) else ledgers_seen[-1],
                         "visual-qa-report": report})
            seqs.update({"triage-report": seq - 1, "visual-qa-report": seq})
            if how == "triage":
                content = run_triage(docs, seqs=seqs).artifacts[0].content
                ledgers_seen.append(content)
            else:
                inputs = Inputs(docs, seqs)
                lifecycle = ledgers.remeasure(inputs.refs, inputs.load,
                                              at="2026-10-12T00:00:00Z",
                                              by=f"quality-report-{seq}", routing=ROUTING)
                ledgers_seen.append({"lifecycle": lifecycle, "provenance": {}})
        return ledgers_seen

    def banner(self, ledger):
        return {r["id"]: r for r in ledger["lifecycle"]}[self.BANNER]

    def test_r1_1_a_failing_report_read_by_the_quality_gate_unnotes_an_open_noted_record(self):
        """A failing visual-qa raises the open noted banner; the quality gate (current=[])
        advances the ledger before any triage: the record holds the build."""
        from wgf_triage import ledger as ledgers
        last = self.noted_then((self.vqa("b" * 40, 14, verdict="FAIL", blocker=True), 14,
                                "remeasure"))[-1]
        record = self.banner(last)
        self.assertNotIn("noted", record)
        self.assertIn(self.BANNER, [r["id"] for r in ledgers.blocking(last["lifecycle"],
                                                                      ROUTING)])

    def test_r1_1_a_failing_report_read_by_the_quality_gate_reopens_a_done_noted_record(self):
        from wgf_triage import ledger as ledgers
        steps = self.noted_then(
            (self.vqa("b" * 40, 14, banner=False), 14, "triage"),
            (self.vqa("c" * 40, 18, verdict="FAIL", blocker=True), 18, "remeasure"))
        self.assertIn(self.banner(steps[1])["status"], ("verified", "closed"))
        record = self.banner(steps[-1])
        self.assertNotIn("noted", record)
        self.assertEqual(record["status"], "classified")
        self.assertIn(self.BANNER, [r["id"] for r in ledgers.blocking(steps[-1]["lifecycle"],
                                                                      ROUTING)])

    def test_r1_2_a_noted_detection_is_never_a_measured_failure(self):
        """K6.4: what a PASSING report named is not a FAIL measurement - not in the
        ledger's outcomes, not as the `before` of a verification of judge silence."""
        from wgf_knowledge import strength
        steps = self.noted_then((self.vqa("b" * 40, 14, banner=False), 14, "triage"),
                                (self.vqa("c" * 40, 18), 18, "triage"))
        verified = self.banner(steps[1])
        snap = strength.snapshot(verified)
        self.assertEqual([o["verdict"] for o in snap["outcomes"]], ["PASS"])
        self.assertIsNone(snap["before"])
        found = strength.derive([{"basis": "measured", "run": "r", "report_hash": "x",
                                  "finding": self.BANNER, "commit": "a" * 40,
                                  "remeasurement": snap}])
        self.assertEqual(found["strength"], "hypothesis")
        self.assertEqual({r["rule"] for r in found["refused"]}, {"no-repair"})
        # listed again by a PASSING report after its verification: still no failure
        again = strength.snapshot(self.banner(steps[2]))
        self.assertNotIn("FAIL", [o["verdict"] for o in again["outcomes"]])

    def test_r1_2_the_failing_report_that_raises_a_noted_record_is_its_failure(self):
        """Promoted by a failing report (commit b, seq 14), fixed (c), verified (seq 18):
        the FAIL->PASS pair is b -> c, never the passing report's commit a."""
        from wgf_knowledge import strength
        b, c = "b" * 40, "c" * 40
        steps = self.noted_then((self.vqa(b, 14, verdict="FAIL", blocker=True), 14, "triage"))
        promoted = self.banner(steps[-1])
        self.assertEqual(promoted["status"], "assigned")
        owner = promoted["owner"]
        from wgf_triage import ledger as ledgers
        docs = {"game-design": DESIGN_3D, "triage-report": steps[-1],
                "prototype-report": self.proto(c, 3, {"role": owner,
                                                      "findings": [self.BANNER]}),
                "visual-qa-report": self.vqa(c, 18, banner=False)}
        seqs = {"triage-report": 15, "prototype-report": 16, "visual-qa-report": 18}
        inputs = Inputs(docs, seqs)
        lifecycle = ledgers.remeasure(inputs.refs, inputs.load, at="2026-10-12T00:00:00Z",
                                      by="quality-report-19", routing=ROUTING)
        record = {r["id"]: r for r in lifecycle}[self.BANNER]
        self.assertIn(record["status"], ("verified", "closed"))
        snap = strength.snapshot(record)
        self.assertEqual([(o["verdict"], o["commit"]) for o in snap["outcomes"]],
                         [("FAIL", b), ("PASS", c)])
        self.assertEqual((snap["before"]["commit"], snap["before"]["status"],
                          snap["before"]["seq"]), (b, "FAIL", 14))

    def test_r1_2_the_ledger_records_the_raising_report_not_the_noted_listing_as_a_failure(self):
        """The ledger's own memory of each check (lifecycle._recorded, which baselines and
        regressions read) holds what the reports measured: nothing failed while the banner
        was only noted; the failing report that raised it did, at its seq."""
        from wgf_triage import lifecycle
        steps = self.noted_then((self.vqa("b" * 40, 14, verdict="FAIL", blocker=True), 14,
                                 "triage"))
        key = self.BANNER
        self.assertNotIn(key, lifecycle._recorded(steps[0]["lifecycle"],
                                                  "visual-qa-report", None))
        self.assertEqual(lifecycle._recorded(steps[-1]["lifecycle"], "visual-qa-report",
                                             None).get(key), (14, "FAIL"))

    def ordinary_then_passes(self, listed):
        """The banner raised by a FAILING visual-qa (b, seq 14), then three PASSING reports
        (c, d, e), each listing it at major or not (`listed`, one flag per report, or one
        for all). The newest ledger."""
        flags = listed if isinstance(listed, tuple) else (listed,) * 3
        docs = {"game-design": DESIGN_3D, "prototype-report": self.proto("b" * 40, 1),
                "visual-qa-report": self.vqa("b" * 40, 14, verdict="FAIL", blocker=True)}
        seqs = {"prototype-report": 13, "visual-qa-report": 14}
        ledger = run_triage(docs, seqs=seqs).artifacts[0].content
        for i, (c, s) in enumerate((("c", 18), ("d", 22), ("e", 26))):
            docs.update({"triage-report": ledger, "prototype-report": self.proto(c * 40, i + 2),
                         "visual-qa-report": self.vqa(c * 40, s, banner=flags[i])})
            seqs.update({"triage-report": s - 2, "prototype-report": s - 1,
                         "visual-qa-report": s})
            ledger = run_triage(docs, seqs=seqs, entered=None).artifacts[0].content
        return ledger

    def test_r2_f1_a_pass_that_still_lists_the_finding_is_no_repair(self):
        """Review r2 F1 (pre-existing on 29d22de, the reviewer's p_base.py): an ordinary
        finding still listed at major by the passing reports after it is verified, and
        closed, by them - its ledger status is the producer's verdict's (no gate changes),
        but K6.4 strength refuses each such pass: the judge still saw the defect."""
        from wgf_knowledge import strength
        record = self.banner(self.ordinary_then_passes(listed=True))
        self.assertIn(record["status"], ("verified", "closed"))  # the gate outcome stands
        snap = strength.snapshot(record)
        snap["class"] = "ai-judged"
        self.assertTrue(snap["after"]["listed"])
        self.assertTrue(all(s.get("listed") for s in snap["samples"]))
        found = strength.derive([{"basis": "measured", "run": "r", "report_hash": "x",
                                  "finding": self.BANNER, "commit": "b" * 40,
                                  "remeasurement": snap}])
        self.assertEqual(found["strength"], "hypothesis")
        self.assertEqual({r["rule"] for r in found["refused"]}, {"no-repair"})
        self.assertIn("still lists it", found["refused"][0]["reason"])
        # verified by a pass that no longer lists it (c), then listed again by the next
        # passing reports (d, e): those samples are refused, so it is not reproduced
        later = strength.snapshot(self.banner(self.ordinary_then_passes(
            listed=(False, True, True))))
        later["class"] = "ai-judged"
        self.assertNotIn("listed", later["after"])
        found = strength.derive([{"basis": "measured", "run": "r", "report_hash": "x",
                                  "finding": self.BANNER, "commit": "b" * 40,
                                  "remeasurement": later}])
        self.assertEqual(found["strength"], "single-run")
        self.assertEqual([r["rule"] for r in found["refused"]], ["no-repair", "no-repair"])
        # the control: the same passes, no longer listing it, reproduce the repair
        control = strength.snapshot(self.banner(self.ordinary_then_passes(listed=False)))
        control["class"] = "ai-judged"
        self.assertNotIn("listed", control["after"])
        self.assertEqual(strength.derive([{"basis": "measured", "run": "r",
                                           "report_hash": "x", "finding": self.BANNER,
                                           "commit": "b" * 40,
                                           "remeasurement": control}])["strength"],
                         "reproduced")

    def test_r2_f2_a_checked_producer_raised_from_noted_keeps_the_failing_measurement(self):
        """Review r2 F2 (latent: only visual-qa is noted_on_pass today, and it lists no
        checks). With a FIXTURE routing that notes playability's own findings on a pass, a
        noted record carries the PASSING report's measurement of its check; raised by a
        failing report on the quality gate's path (current=[]), the failure kept is the
        failing report's - the `before` K6.4 measures a repair against."""
        from wgf_knowledge import strength
        from wgf_triage import ledger as ledgers, lifecycle
        data = json.loads(json.dumps(ROUTING.data))
        data["ledger"]["noted_on_pass"]["playability-report"] = ["blocker", "major"]
        routing = Routing(data, {"roles": ROUTING.roles})
        self.assertEqual(routing.problems(), [])
        a, b = "a" * 40, "b" * 40

        def report(commit, seq, verdict):
            body = playability(("core.loop", {}), verdict=verdict)
            body["commit"] = commit
            body["provenance"] = {"artifact_id": f"playability-report-{seq}",
                                  "content_hash": "sha256:" + f"{seq:02d}" * 32}
            return body

        def advance(previous, body, seq, failing, noted):
            return lifecycle.advance(
                previous, at="2026-10-12T00:00:00Z", current=[],
                failing={"playability-report": failing}, seqs={"playability-report": seq},
                reports={"playability-report": body}, proto=None, proto_seq=None,
                decision=None, decision_seq=-1, human_ids=set(), selected=None,
                triage_id=f"t-{seq}", routing_version=routing.version,
                build_of=lambda kind: {"commit": body["commit"], "digest": None},
                routing=routing, noted=noted)

        passing = report(a, 8, "PASS")
        noted = ledgers.noted_reports({"playability-report": passing}, {}, routing,
                                      dimension_3d=False, commit=a, verification=None)
        fid = noted["playability-report"][0]["id"]
        first = advance([], passing, 8, set(), noted)
        self.assertTrue(first[0].get("noted"))
        self.assertEqual(first[0]["failed_measurement"]["commit"], a)
        raised = advance(first, report(b, 14, "FAIL"), 14, {fid}, {})[0]
        self.assertNotIn("noted", raised)
        kept = raised["failed_measurement"]
        self.assertEqual((kept["commit"], kept["seq"], kept["status"],
                          kept["artifact_id"]), (b, 14, "FAIL", "playability-report-14"))
        self.assertEqual(strength.snapshot(raised)["before"]["commit"], b)

    def test_r1_2_a_verified_noted_record_raised_again_by_a_failing_report_is_unstable(self):
        """Noted (a), gone from the judge (b: verified), raised by a failing report (c),
        fixed and verified (d): the pass on b and the failure on c are a flip, and K6.4's
        `unstable` cap holds - on the triage path and on the quality gate's."""
        from wgf_knowledge import strength
        from wgf_triage import ledger as ledgers
        for how in ("triage", "remeasure"):
            with self.subTest(path=how):
                steps = self.noted_then(
                    (self.vqa("b" * 40, 14, banner=False), 14, "triage"),
                    (self.vqa("c" * 40, 18, verdict="FAIL", blocker=True), 18, how))
                owner = self.banner(steps[-1])["owner"]
                docs = {"game-design": DESIGN_3D, "triage-report": steps[-1],
                        "prototype-report": self.proto("d" * 40, 4, {
                            "role": owner, "findings": [self.BANNER]}),
                        "visual-qa-report": self.vqa("d" * 40, 22, banner=False)}
                if how == "remeasure":  # the next triage assigns it, then the fix
                    first = run_triage({**docs, "prototype-report": self.proto("c" * 40, 3),
                                        "visual-qa-report": self.vqa(
                                            "c" * 40, 18, verdict="FAIL", blocker=True)},
                                       seqs={"triage-report": 19, "prototype-report": 17,
                                             "visual-qa-report": 18})
                    docs["triage-report"] = first.artifacts[0].content
                seqs = {"triage-report": 20, "prototype-report": 21, "visual-qa-report": 22}
                inputs = Inputs(docs, seqs)
                lifecycle = ledgers.remeasure(inputs.refs, inputs.load,
                                              at="2026-10-12T00:00:00Z",
                                              by="quality-report-23", routing=ROUTING)
                record = {r["id"]: r for r in lifecycle}[self.BANNER]
                self.assertIn(record["status"], ("verified", "closed"))
                snap = strength.snapshot(record)
                self.assertEqual([o["verdict"] for o in snap["outcomes"]],
                                 ["PASS", "FAIL", "PASS"])
                self.assertIsNotNone(strength._unstable(snap))


if __name__ == "__main__":
    unittest.main()

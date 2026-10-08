"""Specialist roles and the knowledge write-back rule (WS-9).

Four specialists join the routing data - an art director, a performance engineer, browser QA
and publishing compliance - each owning one dimension, and a specialist visit that finds a
systemic issue leaves it behind as a lesson candidate that reaches the person at G4. These
tests hold:

  * every new role is an implementer with a charter, playbooks that exist and exactly one
    dimension; the quality-finding schema enumerates the dimensions the routing data does;
  * failures reach them: a page error while played (browser QA), an inconsistent look (the
    art director), a device class over its performance budget (the performance engineer,
    though the quality gate scores it under `technical`), a platform requirement the listing
    misses (publishing compliance, on the listing route);
  * the developer's `lesson_candidates` are kept to the schema's shape on the
    prototype-report, carried forward by triage, and surfaced by the quality gate;
  * a specialist's brief asks for them and names the lesson a finding is already guarded by.

    python -m unittest scripts.tests.test_specialist_knowledge
"""

import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
for _path in (SCRIPTS, HERE):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import test_triage as tt  # noqa: E402
from wgf_develop import report as develop_report  # noqa: E402
from wgf_develop import specialist as specialists  # noqa: E402
from wgf_quality.step import lesson_candidates  # noqa: E402
from wgf_triage import Routing, normalize  # noqa: E402
from wgflib import paths  # noqa: E402
from wgflib.yamllite import load_file  # noqa: E402

ROUTING = Routing.load()
NEW = {"art-director": "art-direction", "performance-engineer": "performance",
       "browser-qa": "browser", "publishing-compliance": "compliance"}


class Roles(unittest.TestCase):
    def test_every_new_specialist_owns_one_dimension_with_a_charter(self):
        roles = load_file(os.path.join(paths.CORE, "roles", "roles.yaml"))["roles"]
        self.assertEqual(ROUTING.problems(), [])
        for role, dimension in NEW.items():
            self.assertEqual(roles[role]["kind"], "implementer", role)
            self.assertEqual(roles[role]["charter"], "specialists.md", role)
            self.assertEqual(ROUTING.owner(dimension), role)
        with open(os.path.join(paths.ARTIFACTS, "shared", "quality-finding.schema.json"),
                  encoding="utf-8") as handle:
            schema = json.load(handle)
        self.assertEqual(list(ROUTING.dimensions), schema["$defs"]["dimension"]["enum"])
        with open(os.path.join(paths.CORE, "roles", "specialists.md"), encoding="utf-8") as handle:
            charter = handle.read()
        for role in NEW:
            self.assertIn(f"`{role}`", charter)

    def test_publishing_compliance_works_on_the_listing(self):
        self.assertEqual(ROUTING.route_of("publishing-compliance"), "listing")
        for role in ("art-director", "performance-engineer", "browser-qa"):
            self.assertEqual(ROUTING.route_of(role), "develop")


class Routed(unittest.TestCase):
    def owners(self, kind, report, dimension_3d=False):
        return {f["source"]["check"]: f for f in normalize(kind, report, ROUTING,
                                                           dimension_3d=dimension_3d)}

    def test_a_page_error_goes_to_browser_qa(self):
        found = self.owners("playability-report", tt.playability(("page.errors", {})))
        finding = next(iter(found.values()))
        self.assertEqual((finding["dimension"], finding["owner"]), ("browser", "browser-qa"))

    def test_an_inconsistent_look_goes_to_the_art_director(self):
        report = tt.visual_qa(scores={"consistency": 2}, failed=["score:consistency"])
        found = normalize("visual-qa-report", report, ROUTING, rubric=tt.RUBRIC)
        owners = {f["owner"] for f in found}
        self.assertIn("art-director", owners)

    def test_a_performance_criterion_goes_to_the_performance_engineer(self):
        report = {"title_id": "demo", "failed": ["technical"], "findings": [
            {"id": "quality:floor.performance", "criterion": "floor.performance",
             "dimension": "technical", "severity": "blocker", "status": "open",
             "route": "develop", "summary": "a device class over budget", "evidence": []},
            {"id": "quality:floor.qa_pass", "criterion": "floor.qa_pass",
             "dimension": "technical", "severity": "blocker", "status": "open",
             "route": "develop", "summary": "qa failed", "evidence": []}]}
        found = {f["source"]["check"]: f for f in normalize("quality-report", report, ROUTING)}
        self.assertEqual(found["floor.performance"]["owner"], "performance-engineer")
        self.assertEqual(found["floor.qa_pass"]["owner"], "gameplay")

    def test_a_platform_requirement_the_listing_misses_goes_to_compliance(self):
        report = {"verdict": "FAIL", "checks": [
            {"id": "platform.screenshots_count", "section": "platforms", "status": "FAIL",
             "required": True, "summary": "too few portrait screenshots",
             "platform_id": "yandex"}]}
        finding = normalize("listing-validation-report", report, ROUTING)[0]
        self.assertEqual((finding["owner"], finding["route"]), ("publishing-compliance", "listing"))


class WriteBack(unittest.TestCase):
    CANDIDATE = {"summary": "A collider resize is never re-checked against the gaps levels rely on",
                 "root_cause": "no clearance lint after a physics change",
                 "proposed_check": "content-sufficiency:content.structure",
                 "finding": "playability-report:content.units_reachable@desktop",
                 "noise": "dropped"}

    def test_the_developer_report_is_kept_to_the_schema_shape(self):
        kept = develop_report.lesson_candidates(
            {"lesson_candidates": [self.CANDIDATE, {"summary": "  "}, "not a mapping"]},
            role="level-designer")
        self.assertEqual(len(kept), 1)
        self.assertNotIn("noise", kept[0])
        self.assertEqual(kept[0]["role"], "level-designer")
        self.assertEqual(develop_report.lesson_candidates({}), [])

    def test_triage_carries_them_forward_for_g4(self):
        candidate = develop_report.lesson_candidates({"lesson_candidates": [self.CANDIDATE]},
                                                     role="level-designer")
        proto = {"title_id": "demo", "iteration": 3,
                 "provenance": {"artifact_id": "prototype-report-demo-3"},
                 "build_ref": {"commit_sha": tt.COMMIT},
                 "specialist": {"role": "level-designer", "findings": [],
                                "lesson_candidates": candidate}}
        docs = {"game-design": tt.DESIGN_2D, "prototype-report": proto,
                "playability-report": tt.playability(("content.units_reachable", {}))}
        result = tt.run_triage(docs, seqs={"prototype-report": 5, "playability-report": 8},
                               entered="playability.fail")
        report = result.artifacts[0].content   # schema-checked by run_triage
        self.assertEqual([c["summary"] for c in report["lesson_candidates"]],
                         [self.CANDIDATE["summary"]])
        guarded = [f for f in report["findings"] if f.get("guarded_by")]
        self.assertEqual(guarded[0]["guarded_by"][0]["lesson"], "L5")
        # The next triage keeps them, once.
        docs["triage-report"] = report
        again = tt.run_triage(docs, seqs={"prototype-report": 5, "playability-report": 12,
                                          "triage-report": 9}, entered="playability.fail")
        self.assertEqual(len(again.artifacts[0].content["lesson_candidates"]), 1)

    def test_the_quality_gate_surfaces_them_once(self):
        candidate = dict(self.CANDIDATE)
        candidate.pop("noise")
        loaded = {"prototype-report": {"specialist": {"role": "ui",
                                                      "lesson_candidates": [candidate]}},
                  "triage-report": {"lesson_candidates": [dict(candidate, role="ui")]}}
        found = lesson_candidates(loaded)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["role"], "ui")

    def test_the_brief_asks_for_them_and_names_a_known_lesson(self):
        spec = {"role": "level-designer", "label": "Level designer", "focus": "Content.",
                "source": "playability.fail", "pending": [], "playbooks": [],
                "findings": [{"id": "playability-report:content.units_reachable@desktop",
                              "severity": "blocker", "dimension": "progression",
                              "summary": "late", "source": {"producer": "playability-report"},
                              "task": {"change": "x", "acceptance": ["y"]},
                              "guarded_by": [{"lesson": "L5", "status": "enforced",
                                              "check": "playability:content.units_reachable"}]}],
                "context": {}, "writable_paths": ["src/"]}
        text = "\n".join(specialists.render(spec))
        self.assertIn("### Leave what you learned", text)
        self.assertIn("lesson_candidates", text)
        self.assertIn("Known lesson L5", text)


if __name__ == "__main__":
    unittest.main()

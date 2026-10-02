#!/usr/bin/env python3
"""wgflib.gate_evidence: what a waiting checkpoint's inputs say, shown to the person
deciding it. The 2.1.2 production run's G4 printed only `pass|iterate|kill`; every kill
criterion was unmeasured and nothing said so."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from wgflib import gate_evidence  # noqa: E402

PROTOTYPE = {  # the shape wgf_develop.report writes before anything is measured
    "kill_criteria_eval": [
        {"criterion_id": "playable_build", "measured": True, "breached": False},
        {"criterion_id": "control_not_understood", "measured": None, "breached": False,
         "note": "NOT MEASURED."},
        {"criterion_id": "no_retry_pull", "measured": None, "breached": False},
    ],
    "playtest_sessions": [{"observer": "automation:develop", "player_context": "internal"}],
}
VERIFICATION = {"verdict": "PASS", "evidence_status": "PASS_MOCK"}


class Summarize(unittest.TestCase):
    def test_unmeasured_criteria_are_named_as_such(self):
        evidence = gate_evidence.summarize({"prototype-report": PROTOTYPE})
        statuses = {c["criterion_id"]: c["status"] for c in evidence["criteria"]}
        self.assertEqual(statuses, {"playable_build": "not breached",
                                    "control_not_understood": "unmeasured",
                                    "no_retry_pull": "unmeasured"})
        self.assertEqual(evidence["unmeasured"], ["control_not_understood", "no_retry_pull"])

    def test_a_breach_wins_over_a_missing_measurement(self):
        evidence = gate_evidence.summarize({"prototype-report": {"kill_criteria_eval": [
            {"criterion_id": "c", "measured": None, "breached": True}]}})
        self.assertEqual(evidence["criteria"][0]["status"], "breached")

    def test_playtests_and_report_statuses(self):
        evidence = gate_evidence.summarize({"prototype-report": PROTOTYPE,
                                            "verification-report": VERIFICATION,
                                            "title-strategy": {"timebox_days": 7}})
        self.assertEqual(evidence["playtests"][0]["by_player_context"], {"internal": 1})
        self.assertEqual(evidence["reports"], [{"artifact": "verification-report",
                                                "verdict": "PASS",
                                                "evidence_status": "PASS_MOCK"}])

    def test_inputs_with_none_of_the_fields_give_nothing(self):
        self.assertIsNone(gate_evidence.summarize({"title-strategy": {"timebox_days": 7}}))
        self.assertIsNone(gate_evidence.summarize({}))
        self.assertEqual(gate_evidence.render(None), [])


DESIGN = {  # what the design step records after checking its content against the genre model
    "consistency": {
        "status": "pass", "evaluated_at": "2026-10-01T00:00:00Z", "ruleset_version": "1.3.0",
        "content_model": {"id": "genre-models", "version": "1.0.0"},
        "rule_results": [
            {"criterion_id": "content.block_present", "breached": False, "measured": True},
            {"criterion_id": "content.unit_count_mvp", "breached": False, "measured": 4},
            {"criterion_id": "content.variety_between_units", "breached": True, "measured": 0.25,
             "note": "waves 2 and 3 change only a number"},
            {"criterion_id": "session_supports_monetization", "breached": False, "measured": True},
        ]},
}

PLAYED = {  # the playability report: what the bot could measure, and what it could not
    "commit": "a" * 40, "verdict": "FAIL",
    "checks": [
        {"id": "content.units_reachable", "project": "desktop", "status": "PASS",
         "required": True, "summary": "units [1, 2, 3] were played in the design's order"},
        {"id": "content.units_reachable", "project": "mobile", "status": "PASS",
         "required": True, "summary": "units [1, 2, 3] were played in the design's order"},
        {"id": "difficulty.axes_progress", "project": "desktop", "status": "FAIL",
         "required": True, "summary": "speed: ended at 0.3, started at 0.3"},
        {"id": "start.objective", "project": "desktop", "status": "PASS", "required": True,
         "summary": "not a content check"},
    ],
    "skipped_checks": [{"id": "content.variety",
                        "reason": "content is generated (parametric)"}],
}

REVIEW = {"verdict": "request-changes", "reviewed_commit": "a" * 40,
          "blockers": [{"id": "invented-wave", "severity": "blocker", "file": "src/game/waves.ts",
                        "summary": "wave 3 is an invented unit, not the designed w-03, and no "
                                   "design_gaps entry reports it"},
                       {"id": "frame-rate", "severity": "major", "file": "src/game/step.ts",
                        "summary": "movement scales per frame"}]}


class ContentEvidence(unittest.TestCase):
    def test_g3_shows_the_content_rules(self):
        evidence = gate_evidence.summarize({"game-design": DESIGN})
        self.assertEqual(evidence["content"][0]["rules"], 3)
        self.assertEqual(evidence["content"][0]["breached"], ["content.variety_between_units"])
        self.assertEqual(evidence["content"][0]["model"], "genre-models@1.0.0")
        text = "\n".join(gate_evidence.render(evidence))
        self.assertIn("content: 3 rules, 1 breached; model genre-models@1.0.0", text)
        self.assertIn("content.variety_between_units: waves 2 and 3 change only a number", text)

    def test_g4_shows_coverage_gaps_and_content_checks(self):
        prototype = dict(PROTOTYPE,
                         content_coverage={"designed": 4, "built": 2, "partial": 1, "cut": 1,
                                           "units": [{"id": "w-01", "status": "built"}]},
                         design_gaps=[{"field": "build_spec.content.units[w-03].success",
                                       "question": "What ends the wave?", "assumed": None,
                                       "severity": "blocking"}])
        evidence = gate_evidence.summarize({"prototype-report": prototype,
                                            "playability-report": PLAYED,
                                            "review-report": REVIEW})
        self.assertEqual(evidence["coverage"][0]["built"], 2)
        self.assertEqual(evidence["gaps"][0]["severity"], "blocking")
        played = {c["id"]: c["status"] for c in evidence["played"][0]["checks"]}
        self.assertEqual(played, {"content.units_reachable": "PASS",
                                  "difficulty.axes_progress": "FAIL"})
        self.assertEqual(evidence["played"][0]["skipped"],
                         [{"id": "content.variety", "reason": "content is generated (parametric)"}])
        self.assertEqual(evidence["reviews"][0]["fidelity"], ["invented-wave"])

        text = "\n".join(gate_evidence.render(evidence))
        self.assertIn("content coverage (prototype-report): 2 of 4 designed units built, "
                      "1 partial, 1 cut", text)
        self.assertIn("design gaps: 1 (1 blocking)", text)
        self.assertIn("nothing was built", text)
        self.assertIn("difficulty.axes_progress", text)
        self.assertIn("not measured: content is generated (parametric)", text)
        self.assertIn("! 1 content check(s) measured nothing: a skip is not a pass.", text)
        self.assertIn("review-report: verdict request-changes, 2 blocker(s); design fidelity: "
                      "invented-wave", text)
        # A check that is not about the content contract is not pulled in.
        self.assertNotIn("start.objective", text)

    def test_a_worst_status_wins_across_viewports(self):
        played = {"checks": [
            {"id": "depth.session_length", "project": "desktop", "status": "PASS",
             "required": True, "summary": "150000 ms"},
            {"id": "depth.session_length", "project": "mobile", "status": "FAIL",
             "required": True, "summary": "30000 ms"}]}
        evidence = gate_evidence.summarize({"playability-report": played})
        self.assertEqual(evidence["played"][0]["checks"][0]["status"], "FAIL")
        self.assertIn("30000 ms", evidence["played"][0]["checks"][0]["summary"])


class Render(unittest.TestCase):
    def test_the_table_says_unmeasured_is_not_evidence(self):
        text = "\n".join(gate_evidence.render(gate_evidence.summarize({
            "prototype-report": PROTOTYPE, "verification-report": VERIFICATION})))
        self.assertIn("control_not_understood", text)
        self.assertIn("unmeasured", text)
        self.assertIn("! 2 of 3 criteria unmeasured: `breached: false` on them is not "
                      "evidence.", text)
        self.assertIn("playtest sessions (prototype-report): 1 (internal 1)", text)
        self.assertIn("verification-report: verdict PASS, evidence PASS_MOCK", text)


if __name__ == "__main__":
    unittest.main()

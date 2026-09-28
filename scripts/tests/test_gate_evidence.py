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

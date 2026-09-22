"""The state machine runner: what it allows, and more importantly what it refuses.

Until this existed, `state.json` was updated by hand as the last step of a command's
procedure. That made the machines' edge lists advisory — a title could be moved anywhere by
anyone who edited the file, and the guards were a reading exercise. These tests are mostly
about refusal, because refusal is the part that was missing.

Everything runs against a temporary workspace. The worked example is never written to.

Run from the web-game-factory repository root:

    python -m unittest discover scripts/tests
"""

import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)

sys.path.insert(0, SCRIPTS)

from wgflib import paths  # noqa: E402
from wgflib.guards import GuardContext  # noqa: E402
from wgflib.hashing import content_hash  # noqa: E402
from wgflib.machine import load_machine  # noqa: E402
from wgflib.workspace import load_portfolio_config, load_title  # noqa: E402

runner = __import__("importlib").machinery.SourceFileLoader(
    "wgf_state", os.path.join(SCRIPTS, "wgf-state.py")
).load_module()


def strategy_artifact(title_id="scratch", timebox=12):
    artifact = {
        "provenance": {
            "artifact_id": f"wgf:title-strategy:{title_id}:20260901-01",
            "artifact_type": "title-strategy",
            "schema_version": "1.0.0",
            "produced_by": {"role": "game-designer", "actor": "ai"},
            "produced_at": "2026-09-01T10:00:00Z",
            "inputs": [],
            "content_hash": "",
            "status": "final",
        },
        "title_id": title_id,
        "timebox_days": timebox,
        "platform_set": [{"id": "yandex", "role": "required"}],
        "max_prototype_iterations": 2,
        "kill_criteria": [
            {
                "id": "too_slow",
                "when": {"left": "latency_ms", "op": "gt", "right": 60},
                "rationale": "Beat matching stops being fair past 60ms.",
            }
        ],
    }
    artifact["provenance"]["content_hash"] = content_hash(artifact)
    return artifact


def decision_record(gate="G2", transition="strategy -> design", mode="human", **extra):
    record = {
        "provenance": {
            "artifact_id": "wgf:decision-record:scratch:20260902-01",
            "artifact_type": "decision-record",
            "schema_version": "1.0.0",
            "produced_by": {"role": "portfolio-owner", "actor": "human"},
            "produced_at": "2026-09-02T09:00:00Z",
            "inputs": [],
            "content_hash": "",
            "status": "final",
        },
        "gate_id": gate,
        "machine": "title",
        "transition": transition,
        "subject": [],
        "decision": "approve",
        "decided_by": {"role": "portfolio-owner", "identifier": "test", "mode": mode},
        "decided_at": "2026-09-02T09:00:00Z",
        "rationale": "Test fixture.",
    }
    record.update(extra)
    record["provenance"]["content_hash"] = content_hash(record)
    return record


class RunnerCase(unittest.TestCase):
    """A scratch workspace with one title, positioned wherever the test needs it."""

    state_id = "strategy"
    title_id = "scratch"

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="wgf-state-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

        self.original_titles = paths.TITLES
        paths.TITLES = os.path.join(self.tmp, "titles")
        self.addCleanup(setattr, paths, "TITLES", self.original_titles)

        self.directory = os.path.join(paths.TITLES, self.title_id)
        os.makedirs(os.path.join(self.directory, "decisions"))

        self.write("title-strategy.json", strategy_artifact(self.title_id))
        self.write("state.json", {
            "title_id": self.title_id,
            "machine": "title",
            "machine_version": "1.0.0",
            "current_state": self.state_id,
            "entered_current_state_at": "2026-09-01T10:00:00Z",
            "history": [{"state": self.state_id, "entered_at": "2026-09-01T10:00:00Z"}],
            "artifacts": {"title-strategy": "title-strategy.json"},
        })

    def write(self, name, payload):
        path = os.path.join(self.directory, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
        return path

    def run_advance(self, **kwargs):
        entity = load_title(self.title_id)
        machine = load_machine("title")
        context = GuardContext(entity, config=load_portfolio_config())
        transition = runner.choose_transition(
            machine, entity.state["current_state"], kwargs["event"], kwargs.get("to"), context
        )
        problems = runner.check_guards(transition, context)
        if problems:
            raise runner.Refused("; ".join(problems))
        if transition.gate:
            runner.check_decision_record(entity, transition, kwargs.get("decision_record"))
        return runner.advance(
            entity, machine, transition,
            kwargs.get("decision_record"), kwargs.get("outcome_note"),
            kwargs.get("timestamp", "2026-09-02T09:00:00Z"),
        )


class RefusesIllegalEdges(RunnerCase):
    def test_event_the_state_does_not_have(self):
        with self.assertRaises(Exception) as caught:
            self.run_advance(event="publish")
        self.assertIn("no transition", str(caught.exception))

    def test_event_that_leads_two_ways_needs_disambiguating(self):
        # portfolio:scored has `rank` to both shortlisted and rejected. The title machine's
        # equivalent here is approve/reject, which differ by event, so assert the mechanism
        # directly rather than inventing a state.
        machine = load_machine("portfolio")
        targets = {t.target for t in machine.transition("scored", "rank")}
        self.assertEqual({"shortlisted", "rejected"}, targets)


class RefusesUnsatisfiedGuards(RunnerCase):
    def test_guard_that_is_red(self):
        artifact = strategy_artifact(self.title_id)
        artifact["kill_criteria"] = []
        artifact["provenance"]["content_hash"] = content_hash(artifact)
        self.write("title-strategy.json", artifact)

        with self.assertRaises(runner.Refused) as caught:
            self.run_advance(event="approve", decision_record="decisions/g2.json")
        self.assertIn("kill_criteria_defined", str(caught.exception))

    def test_guard_that_is_unknown_blocks_too(self):
        # An UNKNOWN guard must not read as a pass. Removing the artifact makes both G2
        # guards unevaluable rather than false.
        os.remove(os.path.join(self.directory, "title-strategy.json"))
        with self.assertRaises(runner.Refused) as caught:
            self.run_advance(event="approve", decision_record="decisions/g2.json")
        self.assertIn("UNKNOWN", str(caught.exception))


class RefusesBadDecisionRecords(RunnerCase):
    def test_gated_edge_without_a_record(self):
        with self.assertRaises(runner.Refused) as caught:
            self.run_advance(event="approve")
        self.assertIn("--decision-record", str(caught.exception))

    def test_record_for_the_wrong_gate(self):
        self.write("decisions/g2.json", decision_record(gate="G3"))
        with self.assertRaises(runner.Refused) as caught:
            self.run_advance(event="approve", decision_record="decisions/g2.json")
        self.assertIn("records gate G3", str(caught.exception))

    def test_record_for_the_wrong_transition(self):
        self.write("decisions/g2.json", decision_record(transition="tech-plan -> scaffolding"))
        with self.assertRaises(runner.Refused) as caught:
            self.run_advance(event="approve", decision_record="decisions/g2.json")
        self.assertIn("authorizes", str(caught.exception))

    def test_record_pinning_content_that_has_since_changed(self):
        with open(os.path.join(self.directory, "title-strategy.json"), encoding="utf-8") as fh:
            artifact = json.load(fh)
        record = decision_record(subject=[{
            "artifact_id": artifact["provenance"]["artifact_id"],
            "artifact_type": "title-strategy",
            "content_hash": "sha256:" + "0" * 64,
        }])
        self.write("decisions/g2.json", record)
        with self.assertRaises(runner.Refused) as caught:
            self.run_advance(event="approve", decision_record="decisions/g2.json")
        self.assertIn("since changed", str(caught.exception))


class RefusesAutomatedIrreversibleGates(RunnerCase):
    state_id = "prototype-review"

    def setUp(self):
        super().setUp()
        report = {
            "provenance": {
                "artifact_id": f"wgf:prototype-report:{self.title_id}:20260915-01",
                "artifact_type": "prototype-report",
                "schema_version": "1.0.0",
                "produced_by": {"role": "gameplay", "actor": "ai"},
                "produced_at": "2026-09-15T16:00:00Z",
                "inputs": [],
                "content_hash": "",
                "status": "final",
            },
            "title_id": self.title_id,
            "kill_criteria_eval": [
                {"criterion_id": "too_slow", "measured": 40, "breached": False}
            ],
        }
        report["provenance"]["content_hash"] = content_hash(report)
        self.write("prototype-report.json", report)

    def test_g4_refuses_a_non_human_decision(self):
        self.write("decisions/g4.json", decision_record(
            gate="G4", transition="prototype-review -> production", mode="auto-approved"
        ))
        with self.assertRaises(runner.Refused) as caught:
            self.run_advance(event="pass", decision_record="decisions/g4.json")
        self.assertIn("never auto-approves", str(caught.exception))

    def test_g4_accepts_a_human_decision(self):
        self.write("decisions/g4.json", decision_record(
            gate="G4", transition="prototype-review -> production", mode="human"
        ))
        updated = self.run_advance(event="pass", decision_record="decisions/g4.json")
        self.assertEqual("production", updated["current_state"])
        self.assertEqual("G4", updated["history"][-2]["gate"])
        self.assertEqual("decisions/g4.json", updated["history"][-2]["decision_record"])


class WritesHistoryCorrectly(RunnerCase):
    def setUp(self):
        super().setUp()
        self.write("decisions/g2.json", decision_record())

    def test_advance_closes_the_old_entry_and_opens_a_new_one(self):
        updated = self.run_advance(
            event="approve", decision_record="decisions/g2.json",
            timestamp="2026-09-02T09:00:00Z",
        )
        self.assertEqual("design", updated["current_state"])
        self.assertEqual("2026-09-02T09:00:00Z", updated["entered_current_state_at"])
        self.assertFalse(updated["terminal"])

        closed, opened = updated["history"][-2], updated["history"][-1]
        self.assertEqual("2026-09-02T09:00:00Z", closed["exited_at"])
        self.assertEqual("approve", closed["event"])
        self.assertEqual("design", opened["state"])
        self.assertNotIn("exited_at", opened)

    def test_terminal_state_requires_an_outcome(self):
        self.write("decisions/reject.json", decision_record(
            transition="strategy -> abandoned", decision="reject"
        ))
        with self.assertRaises(runner.Refused) as caught:
            self.run_advance(event="reject", decision_record="decisions/reject.json")
        self.assertIn("--outcome-note", str(caught.exception))

    def test_terminal_state_records_elapsed_days(self):
        self.write("decisions/reject.json", decision_record(
            transition="strategy -> abandoned", decision="reject"
        ))
        updated = self.run_advance(
            event="reject", decision_record="decisions/reject.json",
            outcome_note="Strategy rejected at G2.", timestamp="2026-09-08T09:00:00Z",
        )
        self.assertTrue(updated["terminal"])
        # Whole days, truncated: 2026-09-01T10:00 to 2026-09-08T09:00 is six full days.
        # neon-drift's recorded 17 is the same arithmetic.
        self.assertEqual(6, updated["outcome"]["elapsed_days"])
        self.assertIn("rejected", updated["outcome"]["note"])

    def test_revisiting_a_state_records_the_iteration(self):
        entity = load_title(self.title_id)
        entity.state["history"].append(
            {"state": "design", "entered_at": "2026-09-02T09:00:00Z"}
        )
        entity.state["current_state"] = "design"
        machine = load_machine("title")
        transition = machine.transition("design", "descope")[0]
        updated = runner.advance(
            entity, machine, transition, None, None, "2026-09-03T09:00:00Z"
        )
        self.assertEqual(2, updated["history"][-1]["iteration"])


if __name__ == "__main__":
    unittest.main()

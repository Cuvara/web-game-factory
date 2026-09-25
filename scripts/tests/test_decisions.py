"""Every gate a workflow decides emits a decision-record; the lifecycle bridge; evidence guards.

  * The checkpoints of `new-game` (G2, G3, G4) emit a schema-valid decision-record with
    every decided outcome - approve, reject, pass, iterate, kill, a timeout approval -
    pinning exactly what they consumed. Nothing is emitted while a checkpoint waits.
  * wgflib/lifecycle_bridge.py, off by default: with factory.lifecycle.sync it appends each
    record to a title's decisions/ and moves the title's cursor by wgf-state.py's rules; a
    refused move is a warning, never the run's outcome. Everything here uses a temporary
    titles directory - workspace/titles/neon-drift is never touched.
  * ci_green, verify_suite_green and playable_build answer from a run's qa-report and
    verification-report; PASS_MOCK is never a pass.

Set WGF_AJV=1 to also validate the emitted records with ajv (needs npx).

    python -m unittest scripts.tests.test_decisions
"""

import datetime
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
sys.path.insert(0, SCRIPTS)

from wgflib import guards, lifecycle_bridge, paths  # noqa: E402
from wgflib.guards import GuardContext, RunEvidence, evaluate_guard  # noqa: E402
from wgflib.hashing import content_hash  # noqa: E402
from wgflib.workflow import checkpoint, decisions  # noqa: E402
from wgflib.workflow.api import RunRequest, WorkflowAPI  # noqa: E402
from wgflib.workflow.config import ConfigError, FactoryConfig  # noqa: E402
from wgflib.workflow.contracts import ArtifactContracts  # noqa: E402
from wgflib.workflow.engine import EngineError  # noqa: E402
from wgflib.workflow.events import Events  # noqa: E402
from wgflib.workflow.model import RunStatus, StepStatus  # noqa: E402
from wgflib.workspace import Entity  # noqa: E402

CONTRACTS = ArtifactContracts()
GATE_STEPS = {"strategy-review": "G2", "tech-plan-review": "G3", "prototype-review": "G4"}


class FrozenClock:
    def __init__(self, start="2026-03-01T00:00:00.000Z"):
        self.now = datetime.datetime.fromisoformat(start.replace("Z", "+00:00"))

    def __call__(self):
        return checkpoint.stamp(self.now)

    def advance(self, seconds):
        self.now += datetime.timedelta(seconds=seconds)


def tree_digest(root):
    found = {}
    for path in sorted(glob.glob(os.path.join(root, "**", "*"), recursive=True)):
        if os.path.isfile(path):
            with open(path, "rb") as handle:
                found[os.path.relpath(path, root)] = handle.read()
    return found


class _Runs(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.mkdtemp(prefix="wgf-decisions-")
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)
        self.store_dir = os.path.join(self.scratch, "store")

    def api(self, clock=None, **sections):
        data = {"storage": {"fsync": False}}
        data.update(sections)
        return WorkflowAPI(config=FactoryConfig(data), store_dir=self.store_dir, clock=clock)

    def start(self, api=None, **request):
        api = api or self.api()
        return api, api.run(RunRequest(mock=True, **request))

    def decide(self, api, state, decision, decided_by="human", note=None):
        return api.run(RunRequest(resume=state.run_id, decision=decision,
                                  decided_by=decided_by, note=note))

    def records(self, api, state, step_id):
        """Every version of the checkpoint's decision-record, oldest first."""
        refs = state.artifacts.get(decisions.output_name(step_id)) or []
        return [api.store.read_artifact(state.run_id, ref) for ref in refs]

    def assert_valid(self, record):
        self.assertEqual(CONTRACTS("decision-record", record), [])

    def assert_pins_what_was_consumed(self, state, step_id, record):
        consumed = []
        for name in state.steps[step_id].consumed:
            artifact_id, _, version = name.rpartition("@v")
            ref = state.artifacts[artifact_id][int(version) - 1]
            consumed.append((ref.type, ref.content_hash))
        pinned = [(pin["artifact_type"], pin["content_hash"])
                  for pin in record["provenance"]["inputs"]]
        self.assertEqual(sorted(pinned), sorted(consumed))
        subject = [(pin["artifact_type"], pin["content_hash"]) for pin in record["subject"]]
        self.assertEqual(sorted(subject), sorted(consumed))  # the gate's required_artifacts


# -- the vocabulary ---------------------------------------------------------------------

class Vocabulary(unittest.TestCase):
    def test_one_table_maps_workflow_choices_onto_the_schema(self):
        schema = CONTRACTS.schemas["decision-record"]
        allowed = set(schema["properties"]["decision"]["enum"])
        self.assertEqual({d for d, _ in decisions.CHOICES.values()} - allowed, set())
        self.assertEqual(decisions.vocabulary("approve"), ("approved", "approve"))
        self.assertEqual(decisions.vocabulary("reject"), ("rejected", "reject"))
        self.assertEqual(decisions.vocabulary("pass"), ("pass", "pass"))
        self.assertEqual(decisions.vocabulary("iterate"), ("iterate", "iterate"))
        self.assertEqual(decisions.vocabulary("kill"), ("abandon", "abandon"))
        with self.assertRaises(decisions.DecisionRecordError):
            decisions.vocabulary("rework")

    def test_mode_is_human_only_for_a_person(self):
        self.assertEqual(decisions.mode_of("human"), "human")
        self.assertEqual(decisions.mode_of("automation"), "auto-approved")
        self.assertEqual(decisions.mode_of("automation", "timeout"), "auto-approved")
        self.assertEqual(decisions.mode_of("human", "timeout"), "auto-approved")
        self.assertEqual(decisions.mode_of("someone-else"), "auto-approved")

    def test_transitions_come_from_the_machine(self):
        self.assertEqual(decisions.transition_for("G2", "approve"),
                         ("title", "strategy -> design"))
        self.assertEqual(decisions.transition_for("G2", "reject"),
                         ("title", "strategy -> abandoned"))
        self.assertEqual(decisions.transition_for("G3", "reject"),
                         ("title", "tech-plan -> design"))
        self.assertEqual(decisions.transition_for("G4", "pass"),
                         ("title", "prototype-review -> production"))
        self.assertEqual(decisions.transition_for("G4", "iterate"),
                         ("title", "prototype-review -> prototype"))
        self.assertEqual(decisions.transition_for("G4", "abandon"),
                         ("title", "prototype-review -> abandoned"))
        with self.assertRaises(decisions.DecisionRecordError):
            decisions.transition_for("G2", "iterate")

    def test_the_shipped_checkpoints_declare_the_record(self):
        from wgflib.workflow.definition import load_definition
        definition = load_definition("new-game")
        for step_id, gate in GATE_STEPS.items():
            step = definition.step(step_id)
            self.assertEqual(step.params.get("gate"), gate)
            self.assertIn("decision-record", step.outputs)


# -- records from a run -----------------------------------------------------------------

class RecordsFromTheMockRun(_Runs):
    def test_g2_g3_auto_and_g4_pass_emit_three_valid_records(self):
        api, state = self.start()
        self.assertEqual((state.status, state.cursor), (RunStatus.WAITING, "prototype-review"))
        # Waiting emits nothing.
        self.assertEqual(self.records(api, state, "prototype-review"), [])
        state = self.decide(api, state, "pass", note="The loop holds.")
        self.assertEqual(state.status, RunStatus.COMPLETED)

        found = {step_id: self.records(api, state, step_id) for step_id in GATE_STEPS}
        for step_id, gate in GATE_STEPS.items():
            with self.subTest(step=step_id):
                (record,) = found[step_id]
                self.assert_valid(record)
                self.assertEqual(record["gate_id"], gate)
                self.assertEqual(record["machine"], "title")
                self.assert_pins_what_was_consumed(state, step_id, record)
                self.assertEqual(record["provenance"]["status"], "final")
                self.assertTrue(record["provenance"]["artifact_id"].startswith(
                    f"wgf:decision-record:mock-title-{gate.lower()}:"))
        g2, g3, g4 = (found[s][0] for s in GATE_STEPS)
        for record in (g2, g3):
            self.assertEqual(record["decision"], "approved")
            self.assertEqual(record["decided_by"]["mode"], "auto-approved")
            self.assertEqual(record["decided_by"]["role"], "portfolio-owner")
        self.assertEqual(g2["transition"], "strategy -> design")
        self.assertEqual(g3["transition"], "tech-plan -> scaffolding")
        self.assertEqual(g4["decision"], "pass")
        self.assertEqual(g4["transition"], "prototype-review -> production")
        self.assertEqual(g4["decided_by"], {"role": "portfolio-owner", "mode": "human",
                                            "identifier": "human"})
        self.assertEqual(g4["rationale"], "The loop holds.")
        self.assertEqual(g4["decided_at"], state.decisions["prototype-review"]["decided_at"])
        self.assertEqual(len({r["provenance"]["artifact_id"] for r in (g2, g3, g4)}), 3)

    def test_human_g2_and_g3(self):
        api, state = self.start(hold_gates=True)
        self.assertEqual(state.cursor, "strategy-review")
        self.assertEqual(self.records(api, state, "strategy-review"), [])
        state = self.decide(api, state, "approve")
        self.assertEqual(state.cursor, "tech-plan-review")
        state = self.decide(api, state, "approve", note="Fits the timebox.")
        self.assertEqual(state.cursor, "prototype-review")
        for step_id in ("strategy-review", "tech-plan-review"):
            (record,) = self.records(api, state, step_id)
            self.assert_valid(record)
            self.assertEqual(record["decided_by"]["mode"], "human")
            self.assertEqual(record["decision"], "approved")
            self.assert_pins_what_was_consumed(state, step_id, record)
        (g3,) = self.records(api, state, "tech-plan-review")
        self.assertEqual(g3["rationale"], "Fits the timebox.")

    def test_kill_records_abandon(self):
        api, state = self.start()
        state = self.decide(api, state, "kill", note="Latency breaches the bet.")
        self.assertEqual(state.status, RunStatus.COMPLETED)
        self.assertEqual(state.exit["route"], "kill")
        (record,) = self.records(api, state, "prototype-review")
        self.assert_valid(record)
        self.assertEqual(record["decision"], "abandon")
        self.assertEqual(record["transition"], "prototype-review -> abandoned")
        self.assertEqual(record["decided_by"]["mode"], "human")
        self.assert_pins_what_was_consumed(state, "prototype-review", record)
        # Persisted and named by the step, though the outcome was BLOCKED.
        self.assertEqual(state.steps["prototype-review"].status, StepStatus.BLOCKED)
        self.assertEqual(state.steps["prototype-review"].outputs,
                         [f"{decisions.output_name('prototype-review')}@v1"])

    def test_reject_records_rejected(self):
        api, state = self.start(hold_gates=True)
        state = self.decide(api, state, "reject", note="Kill criteria too vague.")
        self.assertEqual(state.status, RunStatus.BLOCKED)
        (record,) = self.records(api, state, "strategy-review")
        self.assert_valid(record)
        self.assertEqual(record["decision"], "rejected")
        self.assertEqual(record["transition"], "strategy -> abandoned")
        self.assert_pins_what_was_consumed(state, "strategy-review", record)

    def test_iterate_records_and_the_next_visit_records_again(self):
        api, state = self.start()
        state = self.decide(api, state, "iterate", note="Tighten the input window.")
        # develop -> ... -> verify ran again, and G4 asks again.
        self.assertEqual((state.status, state.cursor), (RunStatus.WAITING, "prototype-review"))
        (first,) = self.records(api, state, "prototype-review")
        self.assert_valid(first)
        self.assertEqual(first["decision"], "iterate")
        self.assertEqual(first["transition"], "prototype-review -> prototype")
        consumed_first = {p["artifact_type"]: p["content_hash"]
                          for p in first["subject"]}
        state = self.decide(api, state, "pass")
        first_again, second = self.records(api, state, "prototype-review")
        self.assertEqual(first_again, first)  # versions are never rewritten
        self.assert_valid(second)
        self.assertEqual(second["decision"], "pass")
        self.assert_pins_what_was_consumed(state, "prototype-review", second)
        self.assertNotEqual(first["provenance"]["artifact_id"],
                            second["provenance"]["artifact_id"])
        consumed_second = {p["artifact_type"]: p["content_hash"] for p in second["subject"]}
        # The second decision is about the new build's evidence.
        self.assertNotEqual(consumed_first["prototype-report"],
                            consumed_second["prototype-report"])

    def test_automation_at_g4_is_refused_and_records_nothing(self):
        api, state = self.start()
        state = self.decide(api, state, "pass", decided_by="automation")
        self.assertEqual((state.status, state.cursor), (RunStatus.WAITING, "prototype-review"))
        self.assertEqual(self.records(api, state, "prototype-review"), [])

    def test_timeout_approval_records_auto_approved(self):
        clock = FrozenClock()
        api = self.api(clock=clock, checkpoints={"timeout_auto_approve": {"G2": "10m"}})
        _, state = self.start(api, hold_gates=True)
        self.assertEqual(state.cursor, "strategy-review")
        clock.advance(599)
        state = api.run(RunRequest(resume=state.run_id))
        self.assertEqual(self.records(api, state, "strategy-review"), [])
        clock.advance(1)
        state = api.run(RunRequest(resume=state.run_id))
        self.assertEqual(state.decisions["strategy-review"]["mode"], "timeout")
        (record,) = self.records(api, state, "strategy-review")
        self.assert_valid(record)
        self.assertEqual(record["decision"], "approved")
        self.assertEqual(record["decided_by"], {"role": "portfolio-owner",
                                                "mode": "auto-approved",
                                                "identifier": "automation"})
        self.assertEqual(record["decided_at"], "2026-03-01T00:10:00.000Z")
        self.assertIn("approved on timeout", record["rationale"])
        self.assert_pins_what_was_consumed(state, "strategy-review", record)

    def test_a_choice_with_no_record_meaning_fails_the_checkpoint(self):
        path = os.path.join(self.scratch, "odd.workflow.yaml")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("""workflow:
  id: odd
  version: 1
  start: strategy
  steps:
    - id: strategy
      type: strategy
      stage: title:strategy
      outputs: [title-strategy]
    - id: review
      type: human-checkpoint
      stage: title:strategy
      inputs: [title-strategy]
      outputs: [decision-record]
      with:
        gate: G2
        choices: [approve, rework]
""")
        api = WorkflowAPI(config=FactoryConfig({"storage": {"fsync": False}}),
                          store_dir=self.store_dir, workflow=path)
        state = api.run(RunRequest(mock=True, hold_gates=True))
        self.assertEqual(state.cursor, "review")
        state = self.decide(api, state, "rework")
        self.assertEqual(state.status, RunStatus.FAILED)
        self.assertIn("cannot be recorded as a decision-record", state.steps["review"].error)
        self.assertEqual(self.records(api, state, "review"), [])


@unittest.skipUnless(os.environ.get("WGF_AJV") == "1" and shutil.which("npx"),
                     "set WGF_AJV=1 to validate with ajv (needs npx; may download ajv-cli)")
class Ajv(_Runs):
    def test_every_emitted_record_validates_with_ajv(self):
        api, state = self.start()
        state = self.decide(api, state, "iterate")
        state = self.decide(api, state, "kill")
        paths_ = []
        for step_id in GATE_STEPS:
            for index, record in enumerate(self.records(api, state, step_id)):
                path = os.path.join(self.scratch, f"{step_id}-{index}.json")
                with open(path, "w", encoding="utf-8") as handle:
                    json.dump(record, handle)
                paths_.append(path)
        self.assertEqual(len(paths_), 4)
        for path in paths_:
            completed = subprocess.run(
                ["npx", "--yes", "-p", "ajv-cli@5", "-p", "ajv-formats@2", "ajv", "validate",
                 "-s", "core/artifacts/decision-record.schema.json",
                 "-r", "core/artifacts/shared/*.schema.json", "-c", "ajv-formats",
                 "--spec=draft2020", "--strict=false", "-d", path],
                cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)


# -- the lifecycle bridge ---------------------------------------------------------------

def title_state(current, history=None):
    history = history or [{"state": current, "entered_at": "2026-02-01T00:00:00Z"}]
    return {"title_id": "bridge-title", "opportunity_id": "opp-bridge", "machine": "title",
            "machine_version": "1.0.0", "current_state": current, "terminal": False,
            "entered_current_state_at": history[-1]["entered_at"], "history": history,
            "artifacts": {}}


class _Bridge(_Runs):
    TITLE = "bridge-title"

    def setUp(self):
        super().setUp()
        self.titles = os.path.join(self.scratch, "titles")
        self.directory = os.path.join(self.titles, self.TITLE)
        os.makedirs(self.directory)
        self.write_cursor("strategy")

    def write_cursor(self, current, history=None):
        with open(os.path.join(self.directory, "state.json"), "w", encoding="utf-8") as handle:
            json.dump(title_state(current, history), handle, indent=2)

    def cursor(self):
        with open(os.path.join(self.directory, "state.json"), encoding="utf-8") as handle:
            return json.load(handle)

    def decision_files(self):
        return sorted(glob.glob(os.path.join(self.directory, "decisions", "*.json")))

    def sync_api(self, sync=True, clock=None, **sections):
        """A real (not --mock) run of the placeholder steps: they are registered as the
        installation's step modules, so the run's params carry no `mock`."""
        sections.setdefault("steps", {"modules": ["wgflib.workflow.mock"]})
        return self.api(clock=clock, lifecycle={"sync": sync, "titles_directory": self.titles},
                        **sections)

    def run_real(self, api, **request):
        return api.run(RunRequest(project_id=self.TITLE, **request))

    def bridge_logs(self, api, state):
        return [e for e in api.store.read_events(state.run_id)
                if e["event"] == Events.STEP_LOG and (e.get("data") or {}).get("bridge")]


class Bridge(_Bridge):
    def test_off_by_default_nothing_is_written(self):
        before = tree_digest(self.titles)
        api = self.api(steps={"modules": ["wgflib.workflow.mock"]},
                       lifecycle={"titles_directory": self.titles})
        state = self.run_real(api)
        self.assertEqual(state.cursor, "strategy-review")
        state = self.decide(api, state, "approve")
        self.assertNotIn("lifecycle_sync", state.params)
        self.assertEqual(tree_digest(self.titles), before)
        self.assertEqual(self.bridge_logs(api, state), [])

    def test_on_it_appends_the_record_and_moves_the_cursor(self):
        api = self.sync_api()
        state = self.run_real(api)
        self.assertIs(state.params["lifecycle_sync"], True)
        self.assertEqual(self.decision_files(), [])  # waiting: nothing to sync
        state = self.decide(api, state, "approve", note="Committed.")
        self.assertEqual(state.cursor, "tech-plan-review")

        (path,) = self.decision_files()
        with open(path, encoding="utf-8") as handle:
            written = json.load(handle)
        (record,) = self.records(api, state, "strategy-review")
        self.assertEqual(written, record)
        self.assertRegex(os.path.basename(path), r"^G2-\d{8}T\d{9}Z-01\.json$")
        cursor = self.cursor()
        self.assertEqual(cursor["current_state"], "design")
        self.assertEqual(cursor["history"][0]["event"], "approve")
        self.assertEqual(cursor["history"][0]["gate"], "G2")
        self.assertEqual(cursor["history"][0]["decision_record"],
                         "decisions/" + os.path.basename(path))
        (log,) = self.bridge_logs(api, state)
        self.assertEqual(log["level"], "info")
        self.assertIn("strategy -> design through G2", log["message"])

    def test_a_cursor_elsewhere_warns_and_the_run_carries_on(self):
        api = self.sync_api()
        state = self.run_real(api)
        state = self.decide(api, state, "approve")  # G2 moves strategy -> design
        # G3 decides tech-plan -> scaffolding, but the cursor is at design: nothing moved
        # it through `plan`, which is wgf-state.py's to take.
        state = self.decide(api, state, "approve")
        self.assertEqual(state.cursor, "prototype-review")
        self.assertEqual(self.cursor()["current_state"], "design")
        self.assertEqual(len(self.decision_files()), 2)  # recorded, not followed
        warning = self.bridge_logs(api, state)[-1]
        self.assertEqual(warning["level"], "warning")
        self.assertIn("the cursor is at title:design", warning["message"])

    def test_a_failed_guard_warns_and_does_not_fail_the_run(self):
        api = self.sync_api()
        state = self.run_real(api)
        state = self.decide(api, state, "approve")
        state = self.decide(api, state, "approve")
        self.assertEqual(state.cursor, "prototype-review")
        self.write_cursor("prototype-review")
        before = self.cursor()
        # The placeholder prototype-report breaches a kill criterion, so the machine's
        # kill_criteria_not_breached guard refuses `pass` - but the person decided pass,
        # and the run proceeds on that.
        state = self.decide(api, state, "pass")
        self.assertEqual(state.status, RunStatus.COMPLETED)
        self.assertEqual(self.cursor(), before)
        warning = self.bridge_logs(api, state)[-1]
        self.assertEqual(warning["level"], "warning")
        self.assertIn("kill_criteria_not_breached", warning["message"])
        self.assertEqual(len(self.decision_files()), 3)

    def test_kill_moves_the_cursor_to_abandoned_with_the_rationale(self):
        api = self.sync_api()
        state = self.run_real(api)
        state = self.decide(api, state, "approve")
        state = self.decide(api, state, "approve")
        self.write_cursor("prototype-review")
        state = self.decide(api, state, "kill", note="The bet is lost on its own terms.")
        self.assertEqual(state.status, RunStatus.COMPLETED)
        cursor = self.cursor()
        self.assertEqual(cursor["current_state"], "abandoned")
        self.assertTrue(cursor["terminal"])
        self.assertEqual(cursor["outcome"]["note"], "The bet is lost on its own terms.")
        self.assertEqual(cursor["history"][-2]["gate"], "G4")

    def test_no_cursor_no_writes(self):
        shutil.rmtree(self.directory)
        api = self.sync_api()
        state = self.run_real(api)
        state = self.decide(api, state, "approve")
        self.assertFalse(os.path.exists(self.directory))
        (log,) = self.bridge_logs(api, state)
        self.assertIn("has no lifecycle cursor", log["message"])

    def test_a_mock_run_never_syncs(self):
        before = tree_digest(self.titles)
        api = self.api(lifecycle={"sync": True, "titles_directory": self.titles})
        state = api.run(RunRequest(mock=True, project_id=self.TITLE, hold_gates=True))
        state = self.decide(api, state, "approve")
        self.assertEqual(tree_digest(self.titles), before)
        (log,) = self.bridge_logs(api, state)
        self.assertEqual(log["level"], "warning")
        self.assertIn("mock run", log["message"])

    def test_the_decision_directory_is_append_only(self):
        api = self.sync_api()
        state = self.run_real(api)
        state = self.decide(api, state, "approve")
        (record,) = self.records(api, state, "strategy-review")
        (first,) = self.decision_files()
        with open(first, "rb") as handle:
            original = handle.read()
        bridge = lifecycle_bridge.LifecycleBridge(api.store, self.titles)
        result = bridge.sync(record, self.TITLE)
        self.assertEqual(result.level, "warning")  # already at design: not moved again
        files = self.decision_files()
        self.assertEqual(len(files), 2)
        self.assertTrue(files[1].endswith("-02.json"))
        with open(first, "rb") as handle:
            self.assertEqual(handle.read(), original)

    def test_a_title_id_that_is_not_one_directory_is_refused(self):
        bridge = lifecycle_bridge.LifecycleBridge(None, self.titles)
        result = bridge.sync({"gate_id": "G2"}, "../escape")
        self.assertEqual(result.level, "warning")
        self.assertFalse(os.path.exists(os.path.join(self.scratch, "escape")))

    def test_sync_edited_into_state_json_is_refused(self):
        api = self.api(steps={"modules": ["wgflib.workflow.mock"]},
                       lifecycle={"titles_directory": self.titles})
        state = self.run_real(api)
        edited = api.store.load(state.run_id)
        edited.params["lifecycle_sync"] = True
        api.store.save(edited)
        with self.assertRaisesRegex(EngineError, "lifecycle_sync"):
            self.decide(api, state, "approve")
        self.assertEqual(self.decision_files(), [])

    def test_sync_removed_from_state_json_is_refused(self):
        api = self.sync_api()
        state = self.run_real(api)
        edited = api.store.load(state.run_id)
        del edited.params["lifecycle_sync"]
        api.store.save(edited)
        with self.assertRaisesRegex(EngineError, "lifecycle_sync"):
            self.decide(api, state, "approve")

    def test_a_malformed_sync_value_is_refused(self):
        api = self.sync_api()
        state = self.run_real(api)
        edited = api.store.load(state.run_id)
        edited.params["lifecycle_sync"] = "yes"
        api.store.save(edited)
        with self.assertRaisesRegex(EngineError, "lifecycle_sync"):
            self.decide(api, state, "approve")

    def test_the_config_value_must_be_a_boolean(self):
        for value in ("yes", 1, [True]):
            with self.subTest(value=value):
                with self.assertRaises(ConfigError):
                    self.api(lifecycle={"sync": value}).run(RunRequest(mock=True))

    def test_the_worked_example_is_never_the_default_target_of_a_test(self):
        # Guard for this file: every bridge here writes under a temporary directory.
        self.assertNotEqual(os.path.realpath(self.titles), os.path.realpath(paths.TITLES))


# -- guards from engine evidence --------------------------------------------------------

def qa(verdict="pass", evidence_status="PASS", failed=0):
    report = {"title_id": "bridge-title", "verdict": verdict,
              "suites": [{"name": "lint", "passed": 1, "failed": 0},
                         {"name": "unit", "passed": 9, "failed": failed}],
              "blocking_defects": []}
    if evidence_status is not None:
        report["evidence_status"] = evidence_status
    return report


def verification(verdict="PASS", evidence_status="PASS", built="built",
                 gameplay=("PASS", "PASS")):
    checks = [{"id": "gameplay.loop", "category": "gameplay", "required": True,
               "status": gameplay[0], "evidence_status": gameplay[1]}] if gameplay else []
    report = {"title_id": "bridge-title", "verdict": verdict,
              "build_artifact": {"status": built}, "checks": checks, "failed_checks": []}
    if evidence_status is not None:
        report["evidence_status"] = evidence_status
    return report


class EvidenceGuards(unittest.TestCase):
    def verdict(self, name, evidence):
        entity = Entity("bridge-title", tempfile.gettempdir(), title_state("prototype"))
        return evaluate_guard(name, GuardContext(entity, evidence=evidence))

    def test_no_evidence_stays_unknown(self):
        for name in ("verify_suite_green", "ci_green", "playable_build"):
            with self.subTest(name=name):
                self.assertIsNone(self.verdict(name, None).value)
                self.assertIsNone(self.verdict(name, RunEvidence("r")).value)

    def test_a_pass_on_pass_evidence_is_green(self):
        evidence = RunEvidence("r", qa(), verification())
        self.assertIs(self.verdict("verify_suite_green", evidence).value, True)
        self.assertIs(self.verdict("ci_green", evidence).value, True)
        self.assertIs(self.verdict("playable_build", evidence).value, True)

    def test_pass_mock_is_never_a_pass(self):
        evidence = RunEvidence("r", qa(evidence_status="PASS_MOCK"),
                               verification(evidence_status="PASS_MOCK"))
        verdict = self.verdict("verify_suite_green", evidence)
        self.assertIsNone(verdict.value)
        self.assertEqual(verdict.measurements["evidence_status"], "PASS_MOCK")
        # Either report resting on a stand-in is enough to withhold the pass.
        mixed = RunEvidence("r", qa(), verification(evidence_status="PASS_MOCK"))
        self.assertIsNone(self.verdict("verify_suite_green", mixed).value)
        mocked_play = RunEvidence("r", qa(), verification(gameplay=("PASS", "PASS_MOCK")))
        self.assertIsNone(self.verdict("playable_build", mocked_play).value)

    def test_unrecorded_evidence_status_is_not_a_pass(self):
        evidence = RunEvidence("r", qa(evidence_status=None), verification())
        self.assertIsNone(self.verdict("verify_suite_green", evidence).value)

    def test_failures_are_red(self):
        self.assertIs(self.verdict("verify_suite_green",
                                   RunEvidence("r", qa(verdict="fail", evidence_status="FAIL"),
                                               verification())).value, False)
        self.assertIs(self.verdict("verify_suite_green",
                                   RunEvidence("r", qa(), verification(verdict="FAIL"))).value,
                      False)
        self.assertIs(self.verdict("ci_green", RunEvidence("r", qa(failed=2))).value, False)
        self.assertIs(self.verdict("playable_build",
                                   RunEvidence("r", None, verification(built="not-built"))
                                   ).value, False)
        self.assertIs(self.verdict("playable_build",
                                   RunEvidence("r", None, verification(gameplay=("FAIL", "FAIL")))
                                   ).value, False)

    def test_a_blocked_verification_is_unknown(self):
        evidence = RunEvidence("r", qa(), verification(verdict="BLOCKED"))
        self.assertIsNone(self.verdict("verify_suite_green", evidence).value)
        self.assertIsNone(self.verdict("playable_build",
                                       RunEvidence("r", None, verification(gameplay=()))).value)

    def test_a_mock_run_answers_nothing(self):
        evidence = RunEvidence("r", qa(), verification(), mock=True)
        for name in ("verify_suite_green", "ci_green", "playable_build"):
            with self.subTest(name=name):
                self.assertIsNone(self.verdict(name, evidence).value)


class EvidenceFromTheRunStore(_Bridge):
    def test_find_takes_the_newest_run_of_the_title(self):
        clock = FrozenClock()
        api = self.api(clock=clock, steps={"modules": ["wgflib.workflow.mock"]},
                       checkpoints={"auto_approve": ["G2", "G3"]})
        self.assertIsNone(RunEvidence.find(self.TITLE, self.store_dir))
        older = self.run_real(api)
        clock.advance(60)
        newer = self.run_real(api)
        self.assertEqual((older.cursor, newer.cursor), ("prototype-review", "prototype-review"))
        found = RunEvidence.find(self.TITLE, self.store_dir)
        self.assertEqual(found.run_id, newer.run_id)
        self.assertFalse(found.mock)
        self.assertEqual(found.qa["title_id"], self.TITLE)
        self.assertIsNotNone(found.verification)
        # The placeholder qa-report records no evidence_status: not established, not a pass.
        entity = Entity(self.TITLE, self.directory, title_state("prototype"))
        verdict = evaluate_guard("verify_suite_green", GuardContext(entity, evidence=found))
        self.assertIsNone(verdict.value)
        self.assertIsNone(RunEvidence.find("another-title", self.store_dir))

    def test_a_mock_run_is_found_and_marked_mock(self):
        api = self.api()
        api.run(RunRequest(mock=True, project_id=self.TITLE))
        found = RunEvidence.find(self.TITLE, self.store_dir)
        self.assertTrue(found.mock)


if __name__ == "__main__":
    unittest.main()

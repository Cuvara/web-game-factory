"""No bypass (WS-9): every gate runs, an old run says which did not, and no judge is the author.

core/reference/quality-policy.yaml rules 6 and 7, scripts/wgflib/workflow/quality.py
`missing_gates`, the G4 checkpoint and the quality gate. These tests hold:

  * MISSING GATES. A run whose workflow lacks a gate the Factory now requires (a run started
    under an older definition, or a workflow from elsewhere) is never silently passed: the
    gate is named to G4 - in the prompt a person answers and in the decision-record - G4 is
    never decided automatically for it, the run is development, and the quality-report
    names it and is never a release. The shipped workflow lacks nothing.
  * SMALL GAMES. No tier and no shipped configuration profile removes a required step: the
    tier changes a run's class and bars, never the steps it runs; a tier-mvp run executes
    every required step before G4 like a release run; no step of new-game carries a
    condition that could skip it.
  * INDEPENDENT REVIEW. Every path an implementer's change (develop, sdk) can take to G4 or
    release passes every judge the policy lists for it - steps that do not share its brief
    and cannot write its checkout - so the implementer is never its only judge; a workflow
    edit that opens a path around one fails check-integrity.

    python -m unittest scripts.tests.test_no_bypass
"""

import os
import re
import sys
import tempfile
import shutil
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
for _path in (SCRIPTS, HERE):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import test_quality_inheritance as inheritance  # noqa: E402
from wgf_quality import registry  # noqa: E402
from wgflib import paths  # noqa: E402
from wgflib.workflow import quality  # noqa: E402
from wgflib.workflow.api import RunRequest  # noqa: E402
from wgflib.workflow.definition import load_definition  # noqa: E402
from wgflib.workflow.model import RunStatus  # noqa: E402
from wgflib.yamllite import load_file  # noqa: E402

SHIPPED = os.path.join(ROOT, "core", "workflows", "new-game.workflow.yaml")
POLICY = quality.load_policy()
# The policy file as written: the engine's reader keeps only the lists it enforces.
POLICY_FILE = load_file(os.path.join(ROOT, "core", "reference", "quality-policy.yaml"))


def without_steps(text, *step_ids):
    """The workflow text with each step's block and the route budgets keyed by it removed:
    a definition from before the step existed."""
    for step_id in step_ids:
        text = re.sub(r"(?ms)^    - id: " + re.escape(step_id) + r"\n.*?(?=^    - id: |\Z)",
                      "", text)
        text = re.sub(r"(?m)^        " + re.escape(step_id) + r"\.[a-z-]+: \d+\n", "", text)
    return text


def older_workflow(folder, *step_ids):
    with open(SHIPPED, encoding="utf-8") as handle:
        text = without_steps(handle.read(), *step_ids)
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "new-game.workflow.yaml")
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    return path


class MissingGates(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.mkdtemp(prefix="wgf-nobypass-")
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)
        self.shipped = load_definition("new-game")
        self.held = quality.effective({}, POLICY)

    def test_the_shipped_workflow_lacks_no_gate(self):
        self.assertEqual(quality.lacking(self.shipped, self.held), [])
        for step in self.shipped.steps:
            self.assertEqual(quality.missing_gates(self.shipped, self.held, step,
                                                   self.shipped), [], step.id)

    def test_an_older_workflow_names_the_gates_it_lacks_before_g4(self):
        old = load_definition(older_workflow(self.scratch, "content-sufficiency"))
        g4 = old.step("prototype-review")
        missing = quality.missing_gates(old, self.held, g4, self.shipped)
        self.assertEqual(missing, [{"step": "content-sufficiency", "stage": "title:prototype",
                                    "type": "content-sufficiency"}])
        # The quality gate, a required step itself, is told too.
        self.assertEqual([g["step"] for g in quality.missing_gates(
            old, self.held, old.step("quality-gate"), self.shipped)], ["content-sufficiency"])
        # A step the floor does not hold, and that is not required, is told nothing.
        self.assertEqual(quality.missing_gates(old, self.held, old.step("assets"),
                                               self.shipped), [])

    def test_a_gate_after_this_step_is_not_named_here(self):
        old = load_definition(older_workflow(self.scratch, "listing-validation"))
        self.assertEqual(quality.missing_gates(old, self.held, old.step("prototype-review"),
                                               self.shipped), [])
        self.assertEqual([g["step"] for g in quality.missing_gates(
            old, self.held, old.step("release"), self.shipped)], ["listing-validation"])

    def test_without_the_shipped_definition_every_lacking_gate_is_named(self):
        old = load_definition(older_workflow(self.scratch, "content-sufficiency"))
        self.assertEqual([g["step"] for g in quality.missing_gates(
            old, self.held, old.step("prototype-review"))], ["content-sufficiency"])


class MissingGatesAtG4(inheritance._Case):
    """An old run reaches G4: the person is told, the record says so, nothing decides it
    automatically, and the run is development."""

    def to_g4_on(self, *step_ids):
        path = older_workflow(os.path.join(self.scratch, "flows"), *step_ids)
        api = self.api(workflow=path)
        state = api.run(RunRequest())
        self.assertEqual((state.status, state.cursor), (RunStatus.WAITING, "prototype-review"),
                         state.message)
        return api, state

    def test_g4_names_the_missing_gate_and_the_run_is_development(self):
        api, state = self.to_g4_on("content-sufficiency")
        message = state.steps["prototype-review"].message or state.message
        self.assertIn("MISSING GATES", message)
        self.assertIn("content-sufficiency", message)
        report = api.quality(state)
        self.assertEqual(report["class"], "development")
        self.assertTrue(any("lacks required step(s) content-sufficiency" in r
                            for r in report["reasons"]), report["reasons"])
        self.assertFalse(report["release_ready"])

    def test_a_reversible_gate_is_not_approved_automatically_either(self):
        import types
        from wgflib.workflow.checkpoint import HumanCheckpointStep, required_artifacts

        wanted = required_artifacts("G2")

        class Inputs:
            refs = {t: types.SimpleNamespace(content_hash="sha256:" + "0" * 64) for t in wanted}

            def __contains__(self, k):
                return k in self.refs

            def load(self, k):
                return {}

        class Log:
            def __getattr__(self, name):
                return lambda *a, **k: None

        step = HumanCheckpointStep(types.SimpleNamespace(
            id="strategy-review", params={"gate": "G2", "choices": ["approve", "reject"]},
            outputs=()))
        context = types.SimpleNamespace(
            decision=None, environment={"auto_approve": ["G2"]}, logger=Log(),
            missing_gates=[{"step": "content-sufficiency"}], waiting_since=None, now=None)
        result = step.execute(Inputs(), context)
        self.assertEqual(result.outcome, "WAITING_FOR_HUMAN")
        self.assertIn("MISSING GATES", result.message)
        # The same gate with nothing missing approves itself, as the run allows.
        context.missing_gates = []
        self.assertEqual(step.execute(Inputs(), context).outcome, "SUCCESS")
        # An automatic decision on it is held for a person too.
        context.missing_gates = [{"step": "content-sufficiency"}]
        context.decision = {"decision": "approve", "decided_by": "automation"}
        result = step.execute(Inputs(), context)
        self.assertEqual(result.outcome, "WAITING_FOR_HUMAN")

    def test_resumed_under_the_shipped_definition_the_floor_stops_it(self):
        # A resume reads the workflow by id: the Factory's current definition, which has
        # the gate. A person's pass does not carry the build past it: the floor holds G4
        # until the gate passed this run, and names it.
        api, state = self.to_g4_on("content-sufficiency")
        state = api.run(RunRequest(resume=state.run_id, decision="pass", decided_by="human",
                                   note="looked at it"))
        self.assertEqual((state.status, state.cursor), (RunStatus.BLOCKED, "prototype-review"))
        self.assertIn("content-sufficiency has not passed", state.message)

    def test_a_persons_decision_is_recorded_with_the_missing_gates(self):
        import types
        from unittest import mock as umock
        from wgflib.workflow.checkpoint import HumanCheckpointStep, required_artifacts

        wanted = required_artifacts("G4")

        class Inputs:
            refs = {t: types.SimpleNamespace(content_hash="sha256:" + "0" * 64) for t in wanted}

            def __contains__(self, k):
                return k in self.refs

            def load(self, k):
                return {}

        class Log:
            def __getattr__(self, name):
                return lambda *a, **k: None

        step = HumanCheckpointStep(types.SimpleNamespace(
            id="prototype-review",
            params={"gate": "G4", "choices": ["pass", "iterate", "kill"]}, outputs=()))
        context = types.SimpleNamespace(
            decision={"decision": "pass", "decided_by": "human", "note": "looked at it"},
            environment={}, logger=Log(), now="2026-10-07T00:00:00.000Z",
            missing_gates=[{"step": "content-sufficiency"}], waiting_since=None)
        seen = {}

        def record(self_, gate, choice, inputs, context, **kwargs):
            seen.update(kwargs, gate=gate, choice=choice)
            return [], None

        with umock.patch.object(HumanCheckpointStep, "_record", record):
            result = step.execute(Inputs(), context)
        self.assertEqual((result.outcome, result.route), ("SUCCESS", "pass"))
        self.assertTrue(seen["note"].startswith("looked at it - MISSING GATES"))
        self.assertIn("content-sufficiency", seen["note"])


class SmallGamesSkipNothing(inheritance._Case):
    def test_every_required_step_is_in_new_game(self):
        definition = load_definition("new-game")
        for step_id in POLICY["required_steps"]:
            self.assertTrue(definition.has_step(step_id), step_id)
        self.assertEqual(POLICY["pending"], [])
        scope = definition.resolve_scope(None)
        for step_id in POLICY["required_steps"]:
            self.assertIn(step_id, scope)

    def test_no_step_carries_a_condition_that_could_skip_it(self):
        workflow = load_file(SHIPPED)["workflow"]
        for step in workflow["steps"]:
            for key in ("when", "if", "unless", "skip", "skip_if", "condition", "optional",
                        "tiers", "only_tiers"):
                self.assertNotIn(key, step, step["id"])

    def test_no_tier_or_profile_removes_a_required_step(self):
        definition = load_definition("new-game")
        profiles = [{}]
        folder = os.path.join(ROOT, "workspace", "config", "profiles")
        for name in sorted(os.listdir(folder)):
            if name.endswith(".yaml"):
                profiles.append((load_file(os.path.join(folder, name)) or {}).get("factory")
                                or {})
        for profile in profiles:
            for tier in POLICY["tier"]["classes"]:
                config = dict(profile)
                config["strategy"] = dict(config.get("strategy") or {}, quality_tier=tier)
                taken = quality.snapshot(POLICY, config, definition)
                self.assertEqual(taken["required_steps"], POLICY["required_steps"])
                self.assertFalse(any("lacks required step" in r
                                     for r in taken.get("reasons") or []), (tier, taken))

    def test_a_tier_mvp_run_runs_every_required_step_before_g4(self):
        api, state = self.to_g4(self.api({"strategy": {"quality_tier": "mvp"}}))
        self.assertEqual(state.params["quality"]["class"], "development")
        executed = set(self.executed(state))
        definition = load_definition("new-game")
        before = definition.step_ids[:definition.step_ids.index("prototype-review")]
        for step_id in POLICY["required_steps"]:
            if step_id in before:
                self.assertIn(step_id, executed, step_id)


class IndependentReview(unittest.TestCase):
    def setUp(self):
        self.workflow = load_file(SHIPPED)["workflow"]

    def test_the_shipped_workflow_judges_every_change_independently(self):
        self.assertEqual(registry.independent_review_problems(self.workflow, POLICY_FILE), [])
        rule = POLICY_FILE["independent_review"]
        self.assertEqual(set(rule["implementers"]), {"develop", "sdk"})
        self.assertIn("review", rule["implementers"]["develop"])
        self.assertIn("quality-gate", rule["implementers"]["sdk"])

    def test_a_route_around_a_judge_fails(self):
        import copy
        workflow = copy.deepcopy(self.workflow)
        develop = next(s for s in workflow["steps"] if s["id"] == "develop")
        develop.setdefault("on", {})["shortcut"] = "verify"
        problems = registry.independent_review_problems(workflow, POLICY_FILE)
        judged = {re.search(r"without a (\S+) step", p).group(1) for p in problems}
        # playability, production-quality, visual-qa, content-sufficiency and review are
        # stepped over; verify and the quality gate still stand after the shortcut.
        self.assertEqual(judged, {"playability", "production-quality", "visual-qa",
                                  "content-sufficiency", "review"})

    def test_a_workflow_without_the_code_review_fails(self):
        import copy
        workflow = copy.deepcopy(self.workflow)
        workflow["steps"] = [s for s in workflow["steps"] if s.get("type") != "review"]
        problems = registry.independent_review_problems(workflow, POLICY_FILE)
        self.assertTrue(any("no step of judge type 'review'" in p for p in problems))

    def test_every_judge_is_another_step_type_than_its_implementer(self):
        for kind, judges in POLICY_FILE["independent_review"]["implementers"].items():
            self.assertNotIn(kind, judges)

    def test_the_reviewer_cannot_write_the_checkout(self):
        # The review step's developer runs read-only (docs/review-module.md): its module
        # states it, and its role writes nothing.
        with open(os.path.join(SCRIPTS, "wgf_review", "step.py"), encoding="utf-8") as handle:
            self.assertIn("what the reviewer may not change is the checkout it reviews",
                          handle.read().lower())

    def test_check_integrity_holds_it(self):
        self.assertEqual(registry.problems(ROOT), [])


if __name__ == "__main__":
    unittest.main()

"""K5 GAP B: a run's pinned rule files, on the production path - fail closed, never silently.

The design step and content-sufficiency read the rule files a run pinned when it started
(wgflib.workflow.references: the copy under the run directory's `references/`, checked
against the digest the run recorded in its params `pinned_references`, which the engine
corroborates against WORKFLOW_STARTED; wgf_design.step.DesignStep.pinned_rules,
wgf_sufficiency.step.run_rules). These tests drive the real steps on a real run directory:

  * a valid pin is accepted - and it is the pinned copy that judges, not the live file;
  * a pinned file that is gone BLOCKS the step, naming the file;
  * a pinned copy edited after the start (any byte - another version substituted, the live
    newer file copied over it) BLOCKS the step, naming the file and both digests;
  * the recorded digest itself cannot be swapped to match a substituted copy: the engine
    refuses to drive a run whose params differ from the ones it started with;
  * a blocked step never yields a satisfied rule: compliance reads L29's check UNMEASURED
    and the release blocked.

The documented limit: a run that pinned NOTHING (every run started before K2 on
2026-10-08) is judged by the live files - there is no pin to hold it to - and that is
asserted here too, so it cannot change unseen.

    python -m unittest scripts.tests.test_knowledge_pins
"""

import json
import os
import shutil
import sys
import tempfile
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
for _path in (SCRIPTS, HERE, os.path.join(HERE, "fixtures", "transfer")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import prelesson  # noqa: E402
import test_content_sufficiency as cs  # noqa: E402
import test_design_module as design_tests  # noqa: E402
import test_knowledge_run as runs  # noqa: E402
from wgf_quality import compliance, registry  # noqa: E402
from wgflib.workflow import references  # noqa: E402
from wgflib.workflow.api import RunRequest  # noqa: E402
from wgflib.workflow.engine import EngineError  # noqa: E402
from wgflib.workflow.model import StepOutcome  # noqa: E402

DESIGN_RULES = "core/reference/design-consistency-rules.yaml"
CONTENT_RULES = "core/reference/content-sufficiency.yaml"
BENCHMARK = "core/reference/quality-benchmark.yaml"
CHECK = "content.introductions_one_at_a_time"


def live(relpath):
    with open(os.path.join(ROOT, *relpath.split("/")), encoding="utf-8") as handle:
        return handle.read()


def l29_contract():
    """A contract holding L29 by its build check, as the knowledge step writes it."""
    return {"rules": [{"id": "L29", "title": "t", "level": "blocking",
                       "category": "level_design", "checks": [
                           {"check": f"content-sufficiency:{CHECK}", "tier": "hard",
                            "producer": "content-sufficiency-report",
                            "steps": ["content-sufficiency"]},
                           {"check": f"design-consistency:{CHECK}", "tier": "hard",
                            "producer": "game-design", "steps": ["design"]}]}],
            "facets": {"tier": "release"}}


class _Run:
    """A run directory with pinned rule files, as the engine writes it at start."""

    def setUp(self):
        self.base = tempfile.mkdtemp(prefix="wgf-k5-pins-")
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)

    def pin(self, files):
        """{relpath: text} pinned in the run directory; the run's environment."""
        pins = references.pin({k: v.encode("utf-8") for k, v in files.items()}, self.base)
        return {references.PARAM: pins}

    def pinned_path(self, relpath):
        return os.path.join(self.base, references.DIRECTORY, *relpath.split("/"))


# ------------------------------------------------------------------------------ design step


class DesignStepPins(_Run, unittest.TestCase):
    def run_design(self, environment):
        context = design_tests.FakeContext(run_dir=self.base)
        context.environment = environment
        return design_tests.run_step(design_tests.load_strategy(), context=context)

    def test_a_valid_pin_is_accepted_and_is_what_judges(self):
        current = [l for l in live(DESIGN_RULES).splitlines() if l.startswith("version:")][0]
        pinned = live(DESIGN_RULES).replace(current.split()[0] + " " + current.split()[1],
                                            "version: 2.3.9", 1)
        self.assertNotEqual(pinned, live(DESIGN_RULES))
        result = self.run_design(self.pin({DESIGN_RULES: pinned}))
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
        self.assertEqual(result.artifacts[0].content["consistency"]["ruleset_version"], "2.3.9")

    def test_the_pinned_rules_are_the_runs_not_the_live_files(self):
        """Pinned before L29: the design is never judged by the rule added since."""
        before = prelesson.filtered(DESIGN_RULES, live(DESIGN_RULES).encode()).decode()
        result = self.run_design(self.pin({DESIGN_RULES: before}))
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
        judged = [r["criterion_id"] for r in
                  result.artifacts[0].content["consistency"]["rule_results"]]
        self.assertNotIn(CHECK, judged)
        unpinned = self.run_design({})
        self.assertIn(CHECK, [r["criterion_id"] for r in
                              unpinned.artifacts[0].content["consistency"]["rule_results"]])

    def test_a_missing_pinned_file_blocks_naming_it(self):
        environment = self.pin({DESIGN_RULES: live(DESIGN_RULES)})
        os.remove(self.pinned_path(DESIGN_RULES))
        result = self.run_design(environment)
        self.assertEqual(result.outcome, StepOutcome.BLOCKED)
        self.assertIn(f"the run's pinned copy of {DESIGN_RULES} cannot be read", result.message)
        self.assertFalse(result.artifacts)

    def test_a_pinned_copy_edited_or_substituted_blocks(self):
        older = prelesson.filtered(DESIGN_RULES, live(DESIGN_RULES).encode()).decode()
        for name, substitute in (("edited", older + "\n# loosened in the run\n"),
                                 ("the live newer file copied over it", live(DESIGN_RULES))):
            with self.subTest(name):
                environment = self.pin({DESIGN_RULES: older})
                with open(self.pinned_path(DESIGN_RULES), "w", encoding="utf-8",
                          newline="\n") as handle:
                    handle.write(substitute)
                result = self.run_design(environment)
                self.assertEqual(result.outcome, StepOutcome.BLOCKED)
                self.assertIn(f"the run's pinned copy of {DESIGN_RULES} is sha256:",
                              result.message)
                self.assertIn("edited after the start", result.message)
                self.assertIn(environment[references.PARAM][DESIGN_RULES], result.message)

    def test_a_run_that_pinned_nothing_is_judged_by_the_live_file(self):
        """The documented limit: no pin, nothing to hold it to - the live rules judge."""
        result = self.run_design({})
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
        version = [l for l in live(DESIGN_RULES).splitlines() if l.startswith("version:")][0]
        self.assertEqual(result.artifacts[0].content["consistency"]["ruleset_version"],
                         version.split()[1])


# ------------------------------------------------------------------- content-sufficiency


class ContentSufficiencyPins(_Run, unittest.TestCase):
    write = cs.Step.write
    run_step = cs.Step.run_step
    docs = cs.Step.docs

    def build(self):
        units = cs.varied_units()
        records_dir = self.write(cs.survey_of(units), cs.data_of(units))
        return self.docs(cs.design_of(units), records_dir)

    def check(self, result):
        return next((c for c in result.artifacts[0].content["checks"] if c["id"] == CHECK),
                    None)

    def test_a_valid_pin_is_accepted_and_is_what_judges(self):
        docs = self.build()
        result = self.run_step(docs, self.pin({CONTENT_RULES: live(CONTENT_RULES)}))
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.message)
        self.assertEqual(self.check(result)["status"], "PASS")
        # pinned before L29's build check: the check is not run - the pin judges
        before = prelesson.filtered(CONTENT_RULES, live(CONTENT_RULES).encode()).decode()
        shutil.rmtree(os.path.join(self.base, references.DIRECTORY))
        result = self.run_step(docs, self.pin({CONTENT_RULES: before}))
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.message)
        self.assertIsNone(self.check(result))

    def test_a_missing_pinned_file_blocks_naming_it(self):
        docs = self.build()
        environment = self.pin({CONTENT_RULES: live(CONTENT_RULES)})
        os.remove(self.pinned_path(CONTENT_RULES))
        result = self.run_step(docs, environment)
        self.assertEqual(result.outcome, StepOutcome.BLOCKED)
        reason = result.artifacts[0].content["blocked_reason"]
        self.assertIn(f"the run's pinned copy of {CONTENT_RULES} cannot be read", reason)
        self.assertEqual(result.artifacts[0].content["verdict"], "BLOCKED")

    def test_a_pinned_copy_edited_or_substituted_blocks(self):
        docs = self.build()
        older = prelesson.filtered(CONTENT_RULES, live(CONTENT_RULES).encode()).decode()
        for name, substitute in (("edited", older + "\n# loosened in the run\n"),
                                 ("the live newer file copied over it", live(CONTENT_RULES))):
            with self.subTest(name):
                shutil.rmtree(os.path.join(self.base, references.DIRECTORY),
                              ignore_errors=True)
                environment = self.pin({CONTENT_RULES: older})
                with open(self.pinned_path(CONTENT_RULES), "w", encoding="utf-8",
                          newline="\n") as handle:
                    handle.write(substitute)
                result = self.run_step(docs, environment)
                self.assertEqual(result.outcome, StepOutcome.BLOCKED)
                reason = result.artifacts[0].content["blocked_reason"]
                self.assertIn(f"the run's pinned copy of {CONTENT_RULES} is sha256:", reason)
                self.assertIn("edited after the start", reason)

    def test_the_pinned_benchmark_fails_closed_too(self):
        """content-sufficiency's other pinned file, quality-benchmark.yaml: gone or edited,
        the step BLOCKS naming it."""
        docs = self.build()
        environment = self.pin({BENCHMARK: live(BENCHMARK)})
        os.remove(self.pinned_path(BENCHMARK))
        result = self.run_step(docs, environment)
        self.assertEqual(result.outcome, StepOutcome.BLOCKED)
        self.assertIn(f"the run's pinned copy of {BENCHMARK} cannot be read",
                      result.artifacts[0].content["blocked_reason"])
        environment = self.pin({BENCHMARK: live(BENCHMARK)})
        with open(self.pinned_path(BENCHMARK), "a", encoding="utf-8", newline="\n") as handle:
            handle.write("\n# lowered in the run\n")
        result = self.run_step(docs, environment)
        self.assertEqual(result.outcome, StepOutcome.BLOCKED)
        self.assertIn("edited after the start", result.artifacts[0].content["blocked_reason"])

    def test_a_blocked_step_never_satisfies_a_rule(self):
        """Compliance on the blocked report: L29's build check UNMEASURED, its rule blocking,
        the release held - never SATISFIED."""
        docs = self.build()
        environment = self.pin({CONTENT_RULES: live(CONTENT_RULES)})
        os.remove(self.pinned_path(CONTENT_RULES))
        blocked = self.run_step(docs, environment).artifacts[0].content
        tiers = registry.load(ROOT)["tiers"]
        design = dict(docs["game-design"], consistency={
            "rule_results": [{"criterion_id": CHECK, "breached": False}]})
        section = compliance.evaluate(l29_contract(), tiers, {
            "content-sufficiency-report": blocked, "game-design": design}, tier="release",
            lessons=registry.load(ROOT)["lessons"])
        rule = section["rules"][0]
        statuses = {c["check"]: c["status"] for c in rule["checks"]}
        self.assertEqual(statuses[f"content-sufficiency:{CHECK}"], "UNMEASURED")
        self.assertEqual((rule["status"], section["verdict"]), ("UNMEASURED", "RELEASE_BLOCKED"))
        # and no design at all (a blocked design step writes none): UNMEASURED too
        section = compliance.evaluate(l29_contract(), tiers, {}, tier="release",
                                      lessons=registry.load(ROOT)["lessons"])
        self.assertEqual(section["rules"][0]["status"], "UNMEASURED")
        self.assertEqual(section["verdict"], "RELEASE_BLOCKED")


# ---------------------------------------------------------------------------- the engine


class RecordedDigest(runs._Case):
    """The digest a pin is checked against is the run's own record: a run whose params were
    edited so a substituted copy would match is refused by the engine before any step runs."""

    def test_a_digest_swapped_to_match_a_substituted_copy_is_refused(self):
        api = self.api()
        state = api.run(RunRequest(hold_gates=True))
        run_dir = api.store.run_dir(state.run_id)
        pinned = os.path.join(run_dir, references.DIRECTORY, *DESIGN_RULES.split("/"))
        substitute = prelesson.filtered(DESIGN_RULES, live(DESIGN_RULES).encode())
        with open(pinned, "wb") as handle:
            handle.write(substitute)
        path = os.path.join(run_dir, "state.json")
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        data["params"][references.PARAM][DESIGN_RULES] = references.digest(substitute)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(data, handle)
        with self.assertRaisesRegex(EngineError, r"params\.pinned_references"):
            api.run(RunRequest(resume=state.run_id, decision="approve", decided_by="human"))

    def test_pins_claimed_by_a_run_with_no_recorded_params_are_refused(self):
        """The legacy path: a run whose event log records no params at all can claim no pins
        - `pinned_references` is a guarded param, so pins nothing corroborates are refused
        rather than trusted (wgflib.workflow.integrity GUARDED_PARAMS)."""
        from wgflib.workflow import integrity
        self.assertIn(references.PARAM, integrity.GUARDED_PARAMS)
        state = types.SimpleNamespace(params={references.PARAM: {
            DESIGN_RULES: "sha256:" + "0" * 64}})
        problems = integrity.params_problems(state, [])
        self.assertTrue(problems)
        self.assertIn(references.PARAM, problems[0])
        # without the claim, the legacy run is accepted as it is
        self.assertEqual(integrity.params_problems(types.SimpleNamespace(params={}), []), [])


if __name__ == "__main__":
    unittest.main()

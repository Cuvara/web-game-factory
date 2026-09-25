"""The workflow definition format: what parses, what is refused, and how commands slice it.

A definition that parses must be runnable - every target resolves, every group names real
steps, every retry policy is well-formed - because the engine trusts it completely. These
tests are mostly about what the parser refuses, for the same reason test_state.py is mostly
about what the state runner refuses.

Run from the web-game-factory repository root:

    python -m unittest discover scripts/tests
"""

import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from wgflib.workflow.definition import (  # noqa: E402
    END,
    DefinitionError,
    RetryPolicy,
    load_definition,
    parse_definition,
)
from wgflib.yamllite import load  # noqa: E402

FIXTURES = os.path.join(HERE, "fixtures", "workflows")


def parse(text, **kwargs):
    return parse_definition(load(text), "<test>", **kwargs)


MINIMAL = """
workflow:
  id: tiny
  version: 1
  steps:
    - id: a
      type: alpha
    - id: b
      type: beta
"""


class ParsesValidDefinitions(unittest.TestCase):
    def test_minimal(self):
        definition = parse(MINIMAL)
        self.assertEqual(definition.step_ids, ["a", "b"])
        self.assertEqual(definition.start, "a")
        self.assertEqual(definition.success_target(definition.step("a")), "b")
        self.assertEqual(definition.success_target(definition.step("b")), END)

    def test_the_shipped_new_game_workflow(self):
        definition = load_definition("new-game")
        self.assertEqual(
            definition.step_ids,
            ["research", "strategy", "strategy-review", "design", "tech-plan",
             "tech-plan-review", "init", "assets", "develop", "review", "sdk", "verify",
             "prototype-review", "release"],
        )
        self.assertEqual(definition.step("verify").on, {"fail": "develop"})
        g4 = definition.step("prototype-review")
        self.assertEqual((g4.type, g4.params["gate"], g4.params["choices"]),
                         ("human-checkpoint", "G4", ["pass", "iterate", "kill"]))
        self.assertEqual(g4.on, {"iterate": "develop", "kill": "$end"})
        self.assertEqual(g4.inputs, ["qa-report", "verification-report", "prototype-report",
                                     "title-strategy", "game-design"])
        self.assertEqual(definition.step("design").on, {"descope": "$fail"})
        self.assertEqual(definition.resolve_scope("plan"),
                         ["strategy", "strategy-review", "design", "tech-plan",
                          "tech-plan-review"])

    def test_every_fixture_workflow(self):
        for name in os.listdir(FIXTURES):
            with self.subTest(name):
                load_definition(os.path.join(FIXTURES, name))

    def test_step_retry_overrides_workflow_default_which_overrides_config(self):
        definition = parse("""
workflow:
  id: tiny
  version: 1
  defaults:
    retry: {backoff: fixed, delay_seconds: 5}
  steps:
    - id: a
      type: alpha
      retry: {max_attempts: 7}
    - id: b
      type: beta
""", base_retry=RetryPolicy(max_attempts=3, backoff="exponential", delay_seconds=1))
        a, b = definition.step("a").retry, definition.step("b").retry
        self.assertEqual((a.max_attempts, a.backoff, a.delay_seconds), (7, "fixed", 5))
        self.assertEqual((b.max_attempts, b.backoff, b.delay_seconds), (3, "fixed", 5))


class Scopes(unittest.TestCase):
    def setUp(self):
        self.definition = load_definition("new-game")

    def test_workflow_id_is_every_step(self):
        self.assertEqual(self.definition.resolve_scope("new-game"), self.definition.step_ids)
        self.assertEqual(self.definition.resolve_scope(None), self.definition.step_ids)

    def test_a_step_is_itself(self):
        self.assertEqual(self.definition.resolve_scope("verify"), ["verify"])

    def test_unknown_name_is_refused_with_the_known_ones(self):
        with self.assertRaises(KeyError) as caught:
            self.definition.resolve_scope("publish")
        self.assertIn("verify", str(caught.exception))

    def test_every_required_command_exists(self):
        commands = self.definition.commands()
        for name in ("research", "plan", "init", "assets", "develop", "verify", "release",
                     "new-game"):
            self.assertIn(name, commands)


class RefusesBrokenDefinitions(unittest.TestCase):
    def assertRefused(self, text, fragment):
        with self.assertRaises(DefinitionError) as caught:
            parse(text)
        self.assertIn(fragment, str(caught.exception))

    def test_target_that_is_not_a_step(self):
        self.assertRefused(MINIMAL.replace("type: beta", "type: beta\n      on: {fail: nowhere}"),
                           "'nowhere' is not a step id")

    def test_duplicate_step_id(self):
        self.assertRefused(MINIMAL.replace("id: b", "id: a"), "duplicate id")

    def test_group_naming_an_unknown_step(self):
        self.assertRefused(MINIMAL + "  groups:\n    g: [a, zzz]\n", "unknown step 'zzz'")

    def test_group_colliding_with_a_step(self):
        self.assertRefused(MINIMAL + "  groups:\n    a: [b]\n", "collides")

    def test_bad_retry(self):
        self.assertRefused(
            MINIMAL.replace("type: alpha", "type: alpha\n      retry: {max_attempts: 0}"),
            "max_attempts must be an integer >= 1")
        self.assertRefused(
            MINIMAL.replace("type: alpha", "type: alpha\n      retry: {backoff: random}"),
            "retry.backoff")

    def test_unqualified_stage(self):
        self.assertRefused(MINIMAL.replace("type: alpha", "type: alpha\n      stage: design"),
                           "must be qualified")

    def test_start_that_is_not_a_step(self):
        self.assertRefused(MINIMAL.replace("version: 1", "version: 1\n  start: zzz"),
                           "workflow.start")

    def test_missing_type(self):
        self.assertRefused(MINIMAL.replace("      type: beta\n", ""), "type must be")

    def test_every_problem_is_reported_at_once(self):
        with self.assertRaises(DefinitionError) as caught:
            parse(MINIMAL.replace("id: b", "id: a").replace("  version: 1\n", ""))
        self.assertGreaterEqual(len(caught.exception.problems), 2)

    def test_filename_must_equal_workflow_id(self):
        with tempfile.TemporaryDirectory() as scratch:
            path = os.path.join(scratch, "other.workflow.yaml")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(MINIMAL)
            with self.assertRaises(DefinitionError) as caught:
                load_definition(path)
            self.assertIn("filename stem", str(caught.exception))


class RetryPolicyDelays(unittest.TestCase):
    def test_exponential_doubles_from_the_first_retry_and_caps(self):
        policy = RetryPolicy(max_attempts=6, backoff="exponential", delay_seconds=1,
                             max_delay_seconds=5)
        self.assertEqual([policy.delay_before(n) for n in range(1, 7)],
                         [0.0, 1.0, 2.0, 4.0, 5.0, 5.0])

    def test_fixed_and_none(self):
        self.assertEqual(RetryPolicy(3, "fixed", 2).delay_before(3), 2.0)
        self.assertEqual(RetryPolicy(3, "none", 2).delay_before(3), 0.0)


if __name__ == "__main__":
    unittest.main()

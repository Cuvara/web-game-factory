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
             "tech-plan-review", "init", "greybox", "greybox-playability", "assets", "triage", "develop",
             "playability", "production-quality", "visual-qa", "content-sufficiency", "review", "sdk",
             "sdk-review", "verify", "prototype-review", "store-listing", "listing-validation",
             "release", "listing-triage", "platform-validate", "release-review", "publish-review",
             "submit"],
        )
        # The store listing is made after G4 passes and before release ships it; a failed
        # validation goes back to the listing step through listing-triage (its findings, the
        # copywriter's among them), and release reads both.
        self.assertEqual(definition.step("listing-validation").on, {"listing": "listing-triage"})
        self.assertEqual(definition.step("listing-triage").on, {"listing": "store-listing"})
        self.assertEqual(definition.success_target(definition.step("listing-validation")), "release")
        self.assertEqual(definition.success_target(definition.step("listing-triage")), "store-listing")
        self.assertEqual(definition.step("store-listing").params.get("required_gates"), ["G4"])
        self.assertTrue({"store-listing", "listing-validation-report"}
                        <= set(definition.step("release").inputs))
        # `wgf new-game` ends at release; the publication tail is the `publish` group, run in
        # the drafting run by `wgf publish --run <id>`.
        self.assertEqual(definition.success_target(definition.step("release")), END)
        self.assertEqual(definition.resolve_scope("publish"),
                         ["platform-validate", "release-review", "publish-review", "submit"])
        for step_id, gate, choices in (("release-review", "G5", ["approve", "reject"]),
                                       ("publish-review", "G6", ["publish", "reject"])):
            checkpoint = definition.step(step_id)
            self.assertEqual((checkpoint.type, checkpoint.params["gate"],
                              checkpoint.params["choices"], checkpoint.on),
                             ("human-checkpoint", gate, choices, {"reject": "$end"}), step_id)
        publish = definition.step("submit")
        self.assertEqual(publish.retry.max_attempts, 1)  # the irreversible submit: once
        self.assertEqual(publish.inputs, ["release-manifest", "platform-publication",
                                          "decision-record", "scaffold-record"])
        self.assertEqual(definition.step("verify").on, {"fail": "triage"})
        # The production gates route by what failed: an asset to assets, the game to develop
        # - through triage, which routes it to the specialist that owns it.
        for step_id in ("production-quality", "visual-qa"):
            self.assertEqual(definition.step(step_id).on,
                             {"assets": "assets", "develop": "triage"})
        # Release reads both gates' reports and refuses unless they passed (wgf_release).
        self.assertTrue({"production-quality-report", "visual-qa-report"}
                        <= set(definition.step("release").inputs))
        for step_id in ("assets", "develop"):
            self.assertTrue({"production-quality-report", "visual-qa-report"}
                            <= set(definition.step(step_id).inputs), step_id)
        # A build that cannot be played from outside goes back to develop before review.
        self.assertEqual(definition.step("playability").on, {"fail": "triage"})
        # The commit that ships (sdk's) is reviewed like develop's, and a request for
        # changes goes back to develop - never on to verify.
        for step_id in ("review", "sdk-review"):
            self.assertEqual(definition.step(step_id).type, "review")
            self.assertEqual(definition.step(step_id).on, {"request-changes": "triage"})
            self.assertEqual(definition.step(step_id).outputs, ["review-report"])
        sdk_review = definition.step("sdk-review")
        self.assertEqual(sdk_review.params.get("subject"), "sdk-report")
        # qa-report: an open verify failure is shown to the reviewer (wgf_review.report).
        self.assertEqual(set(sdk_review.inputs), {"sdk-report", "prototype-report",
                                                  "game-design", "scaffold-record",
                                                  "qa-report"})
        self.assertNotIn("subject", definition.step("review").params)
        self.assertEqual(definition.step("release").params.get("required_gates"), ["G4"])
        g4 = definition.step("prototype-review")
        self.assertEqual((g4.type, g4.params["gate"], g4.params["choices"]),
                         ("human-checkpoint", "G4", ["pass", "iterate", "kill"]))
        self.assertEqual(g4.on, {"iterate": "triage", "kill": "$end"})
        self.assertEqual(g4.inputs, ["qa-report", "verification-report", "prototype-report",
                                     "title-strategy", "game-design", "playability-report",
                                     "review-report"])
        self.assertEqual(definition.step("design").on, {"descope": "$fail"})
        self.assertEqual(definition.resolve_scope("plan"),
                         ["strategy", "strategy-review", "design", "tech-plan",
                          "tech-plan-review"])

    def test_every_shipped_release_requires_the_irreversible_gates_before_it(self):
        # The release step cannot see its workflow; the workflow tells it which gates to
        # require (`with: required_gates`, default [G4]). A shipped workflow may not leave
        # out an irreversible gate it checkpoints before release.
        from wgf_release.lineage import DEFAULT_REQUIRED_GATES
        from wgflib.workflow.checkpoint import irreversible_gates
        from wgflib.workflow.definition import WORKFLOWS
        irreversible = set(irreversible_gates())
        for name in sorted(os.listdir(WORKFLOWS)):
            if not name.endswith(".workflow.yaml"):
                continue
            definition = load_definition(os.path.join(WORKFLOWS, name))
            gates = []
            for step in definition.steps:
                gate = (step.params or {}).get("gate")
                if step.type == "human-checkpoint" and gate in irreversible:
                    gates.append(gate)
                if step.type == "release":
                    required = step.params.get("required_gates", list(DEFAULT_REQUIRED_GATES))
                    with self.subTest(workflow=name, step=step.id):
                        self.assertEqual(set(gates) - set(required), set())

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
            self.definition.resolve_scope("deploy")
        self.assertIn("verify", str(caught.exception))

    def test_every_required_command_exists(self):
        commands = self.definition.commands()
        for name in ("research", "plan", "init", "assets", "develop", "verify", "release",
                     "publish", "new-game"):
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


ROUTED = """
workflow:
  id: routed
  version: 1
  steps:
    - id: develop
      type: develop
      max_visits_by_route: LIMITS
    - id: verify
      type: verify
      on:
        fail: develop
"""


class RouteScopedVisitLimits(unittest.TestCase):
    def test_a_route_into_the_step_parses(self):
        step = parse(ROUTED.replace("LIMITS", "{fail: 2}")).step("develop")
        self.assertEqual(step.max_visits_by_route, {"fail": 2})
        self.assertEqual(parse(MINIMAL).step("a").max_visits_by_route, {})

    def test_success_counts_as_a_route_into_the_step_after(self):
        text = ROUTED.replace("max_visits_by_route: LIMITS", "").replace(
            "      type: verify\n", "      type: verify\n      max_visits_by_route: "
                                     "{success: 1}\n")
        self.assertEqual(parse(text).step("verify").max_visits_by_route, {"success": 1})

    def test_a_route_qualified_by_its_source_step_parses(self):
        step = parse(ROUTED.replace("LIMITS", "{verify.fail: 2}")).step("develop")
        self.assertEqual(step.max_visits_by_route, {"verify.fail": 2})

    def test_a_route_that_does_not_enter_the_step_is_refused(self):
        for limits, needle in (("{request-changes: 2}", "no route into it"),
                               ("{success: 2}", "no route into it"),
                               ("{develop.fail: 2}", "no route into it"),
                               ("{nowhere.fail: 2}", "no route into it"),
                               ("{verify.success: 2}", "no route into it"),
                               ("{fail: 0}", "integer >= 1"),
                               ("{fail: true}", "integer >= 1"),
                               ("{fail: 1.5}", "integer >= 1"),
                               ("[fail]", "must be a mapping")):
            with self.assertRaises(DefinitionError, msg=limits) as caught:
                parse(ROUTED.replace("LIMITS", limits))
            self.assertIn(needle, str(caught.exception), limits)

    def test_the_shipped_new_game_bounds_each_loop_into_develop(self):
        definition = load_definition("new-game")
        develop = definition.step("develop")
        # Each reviewer's requests for changes, and each step's failures, are bounded
        # separately - on triage, which every route sending the build back goes through
        # (workflow 10, docs/specialist-routing.md).
        triage = definition.step("triage")
        self.assertEqual(triage.max_visits_by_route,
                         {"playability.fail": 2, "production-quality.develop": 2,
                          "visual-qa.develop": 2, "content-sufficiency.develop": 2,
                          "content-sufficiency.design-gap": 1, "review.request-changes": 2,
                          "sdk-review.request-changes": 2, "verify.fail": 2, "iterate": 2})
        # What triage routes on to develop is bounded per specialist.
        self.assertEqual(develop.max_visits_by_route["triage.gameplay"], 16)
        self.assertEqual({k for k, v in develop.max_visits_by_route.items() if v == 4},
                         {"triage.level-designer", "triage.systems-designer",
                          "triage.encounter-designer", "triage.environment-artist",
                          "triage.artist-2d", "triage.ui", "triage.audio-designer",
                          "triage.sdk"})
        # The production gates' asset failures are bounded on assets, which continues to
        # develop: each pass through assets enters develop once more.
        assets = definition.step("assets")
        self.assertEqual(assets.max_visits_by_route,
                         {"production-quality.assets": 2, "visual-qa.assets": 2,
                          "triage.assets": 2})
        self.assertEqual(assets.max_visits, 1 + sum(assets.max_visits_by_route.values()))
        # develop's own limit never cuts a loop short of its route budget (its own, and the
        # passes through assets), and every step of the loop after develop is visited at
        # most once per develop visit.
        # A design repair (route `design-gap`, bounded on design) re-enters develop once more
        # per pass, from either source.
        design = definition.step("design")
        self.assertEqual(design.max_visits_by_route,
                         {"greybox.design-gap": 1, "develop.design-gap": 1,
                          "triage.design": 2})
        self.assertEqual(design.max_visits, 1 + sum(design.max_visits_by_route.values()))
        self.assertEqual(develop.max_visits, 1 + sum(develop.max_visits_by_route.values())
                         + sum(assets.max_visits_by_route.values())
                         + sum(design.max_visits_by_route.values()))
        greybox = definition.step("greybox")
        self.assertEqual(greybox.max_visits, 1 + sum(greybox.max_visits_by_route.values())
                         + sum(design.max_visits_by_route.values()))
        for step_id in ("playability", "production-quality", "visual-qa", "content-sufficiency", "review", "sdk",
                        "sdk-review", "verify", "prototype-review", "store-listing",
                        "listing-validation"):
            self.assertGreaterEqual(definition.step(step_id).max_visits, develop.max_visits,
                                    step_id)


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

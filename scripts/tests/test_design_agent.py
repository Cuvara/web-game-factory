"""The `agent` design author (scripts/wgf_design/agent.py), F4.

An agent host improves the archetype's draft; the design module then applies exactly the
checks it applies to any author. The host here is a scripted stand-in (a Python script run
through wgflib.procs), so the tests are deterministic and offline.

    python -m unittest discover scripts/tests
"""

import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

import test_design_module as design_tests  # noqa: E402
from wgf_design import AgentAuthor, AgentRunFailed  # noqa: E402
from wgf_design.agent import BUILD_SPEC_KEYS, REQUIRED_KEYS, check_shape  # noqa: E402
from wgflib.workflow.model import StepOutcome  # noqa: E402

# The stand-in host. argv: <mode> <request> <draft>. It reads the request, edits the
# starting draft as the mode says, and writes it (or prints it, or misbehaves).
HOST = r'''
import json, os, sys, time
mode, request_path, draft_path = sys.argv[1:4]
if mode == "env":
    # What the host was given: where the tests look for a leaked secret.
    with open(os.path.join(os.path.dirname(draft_path), "env.json"), "w") as handle:
        json.dump(sorted(os.environ), handle)
    mode = "improve"
with open(request_path, encoding="utf-8") as handle:
    request = json.load(handle)
draft = request["starting_draft"]
if mode == "improve" or mode == "stdout":
    draft["fantasy"] = "Improved by the agent: " + draft["fantasy"]
    draft["build_spec"]["failure"]["feedback"] = "Agent-tuned hit-stop, shake and a low thud."
elif mode == "unbuildable":
    # A dangling state exit: exactly what buildability exists to catch.
    draft["build_spec"]["game_states"][0]["exits"][0]["to"] = "nowhere"
elif mode == "missing":
    del draft["build_spec"]["hud"]
elif mode == "garbage":
    open(draft_path, "w").write("this is not json")
    sys.exit(0)
elif mode == "fail":
    print("host crashed", file=sys.stderr)
    sys.exit(3)
elif mode == "hang":
    time.sleep(30)
elif mode == "nothing":
    sys.exit(0)
if mode == "stdout":
    print("Here is the design.\n```json\n" + json.dumps(draft) + "\n```")
else:
    with open(draft_path, "w", encoding="utf-8") as handle:
        json.dump(draft, handle)
'''


class AgentCase(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.mkdtemp(prefix="wgf-design-agent-")
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)
        self.host = os.path.join(self.scratch, "host.py")
        with open(self.host, "w", encoding="utf-8") as handle:
            handle.write(HOST)

    def config(self, mode, **agent):
        settings = {"argv": [sys.executable, self.host, mode, "{request}", "{draft}"],
                    "timeout_seconds": 60, "idle_timeout_seconds": None}
        settings.update(agent)
        return {"design": {"author": "agent", "agent": settings}}

    def run_design(self, config):
        context = design_tests.FakeContext(config)
        context.run_dir = os.path.join(self.scratch, "run")
        context.visit, context.attempt = 1, 1
        step = design_tests.FixedClockStep(design_tests.FakeDefinition())
        return step.execute(design_tests.FakeInputs(design_tests.load_strategy()), context)


class AnAgentImprovesTheDraft(AgentCase):
    def test_the_improved_draft_becomes_the_design(self):
        result = self.run_design(self.config("improve"))
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
        design = result.artifacts[0].content
        self.assertTrue(design["fantasy"].startswith("Improved by the agent: "))
        self.assertEqual(design["build_spec"]["failure"]["feedback"],
                         "Agent-tuned hit-stop, shake and a low thud.")
        self.assertEqual(design["provenance"]["produced_by"]["actor"], "ai")
        self.assertEqual(result.artifacts[0].metadata["author"], "agent")
        # The module still did everything after the draft.
        self.assertEqual(design["consistency"]["status"], "pass")
        self.assertTrue(design["build_spec"]["sdk_touchpoints"])

    def test_the_request_carries_the_strategy_platforms_and_a_starting_draft(self):
        self.run_design(self.config("improve"))
        with open(os.path.join(self.scratch, "run", "design", "1-1.request.json")) as handle:
            request = json.load(handle)
        self.assertEqual(request["title_id"], design_tests.load_strategy()["title_id"])
        strategy_platforms = {p["id"] for p in design_tests.load_strategy()["platform_set"]}
        self.assertEqual({p["id"] for p in request["platforms"]}, strategy_platforms)
        self.assertTrue(all(p["profile"] for p in request["platforms"]))
        self.assertTrue(set(REQUIRED_KEYS) <= set(request["starting_draft"]))
        self.assertEqual(request["required_keys"], list(REQUIRED_KEYS))

    def test_a_read_only_host_can_print_the_draft(self):
        result = self.run_design(self.config("stdout", draft_from="stdout"))
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
        self.assertTrue(result.artifacts[0].content["fantasy"].startswith("Improved"))


class TheModuleStillJudges(AgentCase):
    def test_an_unbuildable_draft_fails_exactly_as_any_author_would(self):
        result = self.run_design(self.config("unbuildable"))
        self.assertEqual((result.outcome, result.retryable), (StepOutcome.FAILED, False))
        self.assertIn("not buildable", result.error)
        self.assertEqual(result.artifacts, [])

    def test_a_draft_missing_a_section_is_refused_before_finalize(self):
        result = self.run_design(self.config("missing"))
        self.assertEqual((result.outcome, result.retryable), (StepOutcome.FAILED, False))
        self.assertIn("build_spec is missing 'hud'", result.error)

    def test_a_draft_that_is_not_json_is_refused(self):
        result = self.run_design(self.config("garbage"))
        self.assertEqual((result.outcome, result.retryable), (StepOutcome.FAILED, False))
        self.assertIn("not readable JSON", result.error)

    def test_no_draft_at_all_is_refused(self):
        result = self.run_design(self.config("nothing"))
        self.assertEqual((result.outcome, result.retryable), (StepOutcome.FAILED, False))
        self.assertIn("wrote no draft", result.error)

    def test_the_shape_check_names_every_problem(self):
        self.assertEqual(check_shape([]), ["the draft is not a JSON object"])
        problems = check_shape({"build_spec": {}, "scope": [], "engine": "pixijs",
                                "features": {}})
        self.assertIn("missing 'fantasy'", problems)
        self.assertIn(f"build_spec is missing {BUILD_SPEC_KEYS[0]!r}", problems)
        for needle in ("scope is not an object", "engine is not an object",
                       "features is not a list"):
            self.assertIn(needle, problems)


class HostFailures(AgentCase):
    def test_a_failing_host_is_retryable(self):
        # Raised out of the step: the engine's runtime retries it like any transient failure.
        with self.assertRaises(AgentRunFailed) as caught:
            self.run_design(self.config("fail"))
        self.assertIn("exit 3", str(caught.exception))

    def test_a_hung_host_is_stopped_and_retryable(self):
        with self.assertRaises(AgentRunFailed) as caught:
            self.run_design(self.config("hang", timeout_seconds=1))
        self.assertIn("timeout", str(caught.exception))

    def test_an_unconfigured_agent_is_refused(self):
        for agent in ({"argv": []}, {"argv": "claude -p"}, {"argv": ["x"], "draft_from": "fd"},
                      {"argv": ["x", "{repo}"]}, {"argv": ["x", '{"inline": 1}']}):
            result = self.run_design({"design": {"author": "agent", "agent": agent}})
            self.assertEqual((result.outcome, result.retryable), (StepOutcome.FAILED, False))

    def test_the_host_gets_the_allowlisted_agent_environment(self):
        # As the developer and the reviewer: a Factory secret is not the host's to read,
        # and only factory.agents.env_passthrough adds to the allowlist.
        from unittest import mock
        planted = {"WGF_TEST_SECRET_TOKEN": "s3cret", "GH_TOKEN": "gh", "HOST_CRED": "c"}
        with mock.patch.dict(os.environ, planted):
            config = self.config("env")
            config["agents"] = {"env_passthrough": ["HOST_CRED"]}
            result = self.run_design(config)
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
        with open(os.path.join(self.scratch, "run", "design", "env.json")) as handle:
            names = set(json.load(handle))
        self.assertIn("HOST_CRED", names)
        self.assertFalse({"WGF_TEST_SECRET_TOKEN", "GH_TOKEN"} & names)

    def test_the_default_author_is_still_the_archetype(self):
        result = self.run_design({})
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
        self.assertEqual(result.artifacts[0].metadata["author"], "archetype")
        self.assertEqual(result.artifacts[0].content["provenance"]["produced_by"]["actor"],
                         "automation")
        self.assertEqual(AgentAuthor.actor, "ai")


if __name__ == "__main__":
    unittest.main()

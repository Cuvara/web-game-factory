"""wgflib.agent_output: one reader for what an agent session printed - text, a json result
object, or stream-json - and the cost record every agent step keeps (P0-05)."""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from wgflib import agent_output  # noqa: E402
from wgf_review.verdict import from_output  # noqa: E402

VERDICT = {"verdict": "approve", "commit": "abc", "blockers": [], "notes": "ok"}
REPLY = "Reviewed.\n```json\n" + json.dumps(VERDICT) + "\n```"


def envelope(reply=REPLY, cost=0.42, **extra):
    record = {"type": "result", "subtype": "success", "is_error": False, "result": reply,
              "total_cost_usd": cost, "num_turns": 4, "duration_ms": 900}
    record.update(extra)
    return record


class Logger:
    def __init__(self):
        self.calls = []

    def info(self, message, **fields):
        self.calls.append((message, fields))


class Read(unittest.TestCase):
    def test_plain_text_is_returned_byte_for_byte_with_no_usage(self):
        out = agent_output.read(REPLY)
        self.assertEqual(out.text, REPLY)
        self.assertIsNone(out.usage)
        self.assertFalse(out.structured)
        self.assertIsNone(out.cost)

    def test_a_json_result_object_is_unwrapped_and_its_cost_read(self):
        out = agent_output.read(json.dumps(envelope()))
        self.assertEqual(out.text, REPLY)
        self.assertTrue(out.structured)
        self.assertEqual(out.cost, 0.42)
        self.assertEqual((out.usage["num_turns"], out.usage["duration_ms"]), (4, 900))

    def test_the_unwrapped_reply_gives_the_same_verdict_as_plain_text(self):
        # The consumers parse "the last JSON object printed": the envelope must not be it.
        self.assertEqual(from_output(agent_output.read(json.dumps(envelope())).text),
                         from_output(REPLY))
        self.assertEqual(json.loads(from_output(agent_output.read(
            json.dumps(envelope())).text)), VERDICT)

    def test_stream_json_takes_the_last_result_line(self):
        lines = [json.dumps({"type": "system", "subtype": "init"}),
                 json.dumps({"type": "assistant", "message": {"content": "working"}}),
                 json.dumps(envelope(cost=1.5))]
        out = agent_output.read("\n".join(lines) + "\n")
        self.assertEqual((out.text, out.cost, out.structured), (REPLY, 1.5, True))

    def test_a_line_printed_before_the_result_object_does_not_hide_it(self):
        # Found by the end-to-end review test: a wrapper printed a progress line first.
        out = agent_output.read("reviewing abc\n" + json.dumps(envelope()) + "\n")
        self.assertEqual((out.text, out.cost, out.structured), (REPLY, 0.42, True))

    def test_a_verdict_printed_as_plain_json_is_not_mistaken_for_an_envelope(self):
        # A text-mode reviewer may print only its verdict object: that is the reply.
        text = json.dumps(VERDICT)
        out = agent_output.read(text)
        self.assertEqual((out.text, out.usage, out.structured), (text, None, False))

    def test_an_envelope_without_a_string_reply_keeps_the_printed_text(self):
        text = json.dumps(envelope(reply=None))
        out = agent_output.read(text)
        self.assertEqual(out.text, text)
        self.assertTrue(out.structured)
        self.assertEqual(out.cost, 0.42)

    def test_a_cost_that_is_not_a_non_negative_finite_number_is_unknown(self):
        for bad in (-1, float("nan"), True, "0.5", None):
            with self.subTest(cost=bad):
                record = envelope()
                record["total_cost_usd"] = bad
                # json.dumps writes NaN as the bare token NaN, which json.loads reads back.
                self.assertIsNone(agent_output.read(json.dumps(record)).cost)

    def test_none_and_empty_output(self):
        for value in (None, "", "   \n"):
            with self.subTest(value=value):
                out = agent_output.read(value)
                self.assertIsNone(out.usage)
                self.assertFalse(out.structured)

    def test_models_and_errors_are_kept(self):
        out = agent_output.read(json.dumps(envelope(modelUsage={"m-b": {}, "m-a": {}},
                                                    is_error=True)))
        self.assertEqual(out.usage["models"], ["m-a", "m-b"])
        self.assertTrue(out.usage["is_error"])


class Note(unittest.TestCase):
    def test_a_known_cost_is_recorded_as_one_agent_cost_event(self):
        logger = Logger()
        cost = agent_output.note(logger, "reviewer", agent_output.read(json.dumps(envelope())),
                                 commit="abc")
        self.assertEqual(cost, 0.42)
        (message, fields), = logger.calls
        self.assertEqual(message, "agent session cost")
        self.assertEqual((fields["budget"], fields["role"], fields["cost"], fields["known"],
                          fields["structured"], fields["commit"]),
                         ("agent-cost", "reviewer", 0.42, True, True, "abc"))

    def test_text_output_is_recorded_as_a_session_with_an_unknown_cost(self):
        logger = Logger()
        self.assertIsNone(agent_output.note(logger, "copywriter", agent_output.read("hi")))
        (message, fields), = logger.calls
        self.assertEqual(message, "agent session cost unknown")
        self.assertEqual((fields["cost"], fields["known"], fields["structured"]),
                         (None, False, False))

    def test_no_logger_records_nothing(self):
        self.assertIsNone(agent_output.note(None, "reviewer",
                                            agent_output.read(json.dumps(envelope()))))


def step_log(**data):
    return {"event": "STEP_LOG", "data": data}


class Summarize(unittest.TestCase):
    def test_roles_sessions_and_costs_with_nothing_counted_twice(self):
        events = [
            step_log(budget="developer-session", session=1),
            step_log(budget="developer-cost", session=1, cost=3.5),
            step_log(budget="developer-session", session=2),
            step_log(budget="developer-cost", session=2, cost=None),
            step_log(budget="agent-cost", role="reviewer", cost=0.25, known=True),
            step_log(budget="agent-cost", role="reviewer", cost=None, known=False),
            step_log(budget="agent-cost", role="design-author", cost=2.0, known=True),
            {"event": "STEP_STARTED", "data": {"budget": "agent-cost", "cost": 99}},
            step_log(message_only=True),
        ]
        summary = agent_output.summarize(events)
        self.assertEqual(summary["by_role"]["developer"],
                         {"sessions": 2, "cost": 3.5, "unknown": 1})
        self.assertEqual(summary["by_role"]["reviewer"],
                         {"sessions": 2, "cost": 0.25, "unknown": 1})
        self.assertEqual(summary["by_role"]["design-author"],
                         {"sessions": 1, "cost": 2.0, "unknown": 0})
        self.assertEqual((summary["sessions"], summary["total_cost"],
                          summary["unknown_cost_sessions"]), (5, 5.75, 2))

    def test_a_negative_refund_lowers_nothing(self):
        summary = agent_output.summarize([
            step_log(budget="agent-cost", role="judge", cost=1.0),
            step_log(budget="agent-cost", role="judge", cost=-5.0),
        ])
        self.assertEqual(summary["by_role"]["judge"], {"sessions": 2, "cost": 1.0, "unknown": 1})
        self.assertEqual(summary["total_cost"], 1.0)

    def test_an_empty_log(self):
        self.assertEqual(agent_output.summarize([]),
                         {"total_cost": 0.0, "sessions": 0, "unknown_cost_sessions": 0,
                          "by_role": {}})


class EveryAgentSiteReadsThroughIt(unittest.TestCase):
    """Each module that runs a paid agent parses its reply through agent_output.read and
    records the session through agent_output.note, so switching a host to json output never
    breaks a consumer and never leaves a session unmetered."""

    SITES = ("wgf_review/step.py", "wgf_visualqa/judge.py", "wgf_leveldesign/judge.py",
             "wgf_assets/model_judge.py", "wgf_assets/model_author.py", "wgf_assets/author.py",
             "wgf_assets/set_author.py", "wgf_listing/copywriter.py", "wgf_design/agent.py")

    def test_each_site(self):
        root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
        for site in self.SITES:
            with self.subTest(site=site):
                with open(os.path.join(root, site), encoding="utf-8") as handle:
                    source = handle.read()
                self.assertIn("agent_output.read(result.stdout)", source)
                self.assertIn("agent_output.note(", source)
                # The raw stdout is no longer parsed for a reply anywhere in the module.
                for parser in ("from_output(result.stdout)", "last_svg(result.stdout",
                               "_last_json_object(result.stdout"):
                    self.assertNotIn(parser, source)


if __name__ == "__main__":
    unittest.main()

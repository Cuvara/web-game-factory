"""K2: a knowledge exception is a person's act on one run - explicit, expiring and visible.

`wgf resume <run> --except RULE --reason TEXT --expires DATE [--scope KEY=VALUE]` (or
`--except FILE.json`), scripts/wgf_knowledge/exceptions.py through scripts/wgflib/workflow/
api.py: recorded as the operator event KNOWLEDGE_EXCEPTION_GRANTED with the resume's nonce,
like a budget raise. These tests hold:

  * VALID. A person's exception for an applicable rule is recorded - stamped `approved_by`
    (the person who ran the command, by name; mode human) and `created_at` now by the grant
    itself - and listed in the run's next knowledge-contract.
  * REFUSED. No reason or one too short, no expiry or one past the policy's window, a
    created_at in the future, a rule that does not apply, a platform the run does not target
    or a viewport its checks are not judged on: nothing is recorded, and why is said.
  * UNAUTHORIZED. A command inside a step's process tree (automation) cannot grant one; a
    mode written in the record is never trusted; a line appended to the event log is no
    one's act; no configuration grants one (factory.knowledge.exceptions is reported refused).
  * EXPIRED. An exception expired at the moment the contract is made is refused, never
    honoured.
  * OLD RUNS. A run started before the knowledge model holds no contract to except from.

    python -m unittest scripts.tests.test_knowledge_exceptions
"""

import datetime
import json
import os
import sys
import tempfile
import unittest
from unittest import mock as patch

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
for _path in (SCRIPTS, HERE):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import test_knowledge_run as run_tests  # noqa: E402
import wgf  # noqa: E402
from wgf_knowledge import exceptions  # noqa: E402
from wgflib.workflow import quality  # noqa: E402
from wgflib.workflow.api import RunRequest  # noqa: E402
from wgflib.workflow.engine import EngineError  # noqa: E402
from wgflib.workflow.model import RunStatus  # noqa: E402

STEP = run_tests.STEP
REASON = "The steel gaps are threaded by the oracle only; accepted for this soft launch."


def _request(rule_ids, reason, expires, scope=(), approver="cuong"):
    """exceptions.request with a named approver: a test never depends on the login name."""
    return exceptions.request(rule_ids, reason, expires, scope, approver)


def _utc(days=0):
    return (datetime.datetime.now(datetime.timezone.utc)
            + datetime.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


class _Case(run_tests._Case):
    def grant(self, api, run_id, records, decided_by="human"):
        return api.run(RunRequest(resume=run_id, exceptions=records, decided_by=decided_by))

    def granted_events(self, api, run_id):
        return [e for e in api.store.read_events(run_id) if e["event"] == exceptions.EVENT]

    def assertRefused(self, api, state, records, expected, decided_by="human"):
        with self.assertRaisesRegex(EngineError, expected):
            self.grant(api, state.run_id, records, decided_by)
        self.assertEqual(self.granted_events(api, state.run_id), [])

    def remake(self, api, run_id, **kwargs):
        state = api.run(RunRequest(resume=run_id, from_step=STEP, decided_by="human"))
        self.assertEqual(state.status, RunStatus.WAITING, state.message)
        return state


class Valid(_Case):
    def test_a_persons_exception_is_recorded_and_listed_in_contract(self):
        api, state = self.to_g4()
        records = _request(["L23"], REASON, _utc(10)[:10], ["platform=yandex"],
                           approver="Cuong N")
        # A mode written in the request is never trusted.
        records[0]["approved_by"]["mode"] = "automation"
        state = self.grant(api, state.run_id, records)
        events = self.granted_events(api, state.run_id)
        self.assertEqual(len(events), 1)
        data = events[0]["data"]
        self.assertEqual(data["decided_by"], "human")
        self.assertTrue(data.get("resume_nonce"))
        record = data["exception"]
        # The approver is the person, by name; the mode is stamped by the grant.
        self.assertEqual(record["approved_by"], {"identifier": "Cuong N", "mode": "human"})
        self.assertEqual(set(data), {"exception", "decided_by", "decided_at", "resume_nonce"})
        self.assertEqual(record["rule_id"], "L23")
        self.assertEqual(record["scope"], {"platforms": ["yandex"]})
        self.assertTrue(record["expires_at"].endswith("T23:59:59Z"))
        self.assertEqual(exceptions.granted(api.store.read_events(state.run_id)), [record])
        # Honoured by the next contract the run makes: listed, never a satisfied rule.
        state = self.remake(api, state.run_id)
        contract = self.contract(api, state)
        self.assertEqual(contract["exceptions"], [record])
        self.assertIn("L23", {r["id"] for r in contract["rules"]})

    def test_an_exception_from_a_file(self):
        api, state = self.to_g4()
        path = os.path.join(self.scratch, "except.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump([{"rule_id": "L23", "reason": REASON, "scope": {},
                        "expires_at": _utc(5),
                        "approved_by": {"identifier": "someone-else",
                                        "mode": "automation"}}], handle)
        # The file says nothing about who approved it: the person running the command does.
        self.grant(api, state.run_id, exceptions.requests_from_file(path, "cuong"))
        data = self.granted_events(api, state.run_id)[0]["data"]
        self.assertEqual(data["exception"]["approved_by"], {"identifier": "cuong",
                                                            "mode": "human"})

    def test_an_exception_names_a_person_never_a_placeholder(self):
        for name in ("human", "Person", "automation", "not a handle!"):
            with self.assertRaisesRegex(exceptions.ExceptionRefused, "approver"):
                exceptions.request(["L23"], REASON, _utc(5)[:10], (), name)
        for name in ("", "  ", None):
            self.assertIsNotNone(exceptions.approver_problem(name))
        with patch.patch.object(exceptions.getpass, "getuser", side_effect=OSError("none")):
            with self.assertRaisesRegex(exceptions.ExceptionRefused, "names no approver"):
                exceptions.request(["L23"], REASON, _utc(5)[:10])
        with patch.patch.object(exceptions.getpass, "getuser", return_value="root"):
            with self.assertRaisesRegex(exceptions.ExceptionRefused, "names no one"):
                exceptions.request(["L23"], REASON, _utc(5)[:10])
        with patch.patch.object(exceptions.getpass, "getuser", return_value="duycu"):
            self.assertEqual(exceptions.request(["L23"], REASON, _utc(5)[:10])[0]
                             ["approved_by"], {"identifier": "duycu"})
        # A request that reaches the grant with a placeholder is refused there too.
        api, state = self.to_g4()
        records = _request(["L23"], REASON, _utc(5)[:10])
        records[0]["approved_by"]["identifier"] = "human"
        self.assertRefused(api, state, records, "names no one")


class Refused(_Case):
    def setUp(self):
        super().setUp()
        self.run_api, self.state = self.to_g4()

    def refused(self, records, expected, decided_by="human"):
        self.assertRefused(self.run_api, self.state, records, expected, decided_by)

    def test_an_exception_without_reason_is_refused(self):
        self.refused(_request(["L23"], None, _utc(5)[:10]), "reason")

    def test_an_exception_with_a_short_reason_is_refused(self):
        self.refused(_request(["L23"], "too short", _utc(5)[:10]), "20 characters")

    def test_an_exception_without_expiry_is_refused(self):
        with self.assertRaisesRegex(exceptions.ExceptionRefused, "expires"):
            _request(["L23"], REASON, None)
        self.refused([{"rule_id": "L23", "reason": REASON, "scope": {}}], "expires_at")

    def test_an_exception_past_the_policy_window_is_refused(self):
        self.refused(_request(["L23"], REASON, _utc(90)[:10]), "at most 30 days")

    def test_an_exception_created_in_the_future_is_refused(self):
        records = _request(["L23"], REASON, _utc(5)[:10])
        records[0]["created_at"] = _utc(3)
        self.refused(records, "in the future")

    def test_an_exception_for_a_rule_that_never_blocks_is_refused(self):
        experimental = next(r["id"] for r in self.contract(self.run_api, self.state)["rules"]
                            if r["level"] == "experimental")
        self.refused(_request([experimental], REASON, _utc(5)[:10]),
                     "only blocking or required")

    def test_an_exception_for_a_rule_that_does_not_apply_is_refused(self):
        self.refused(_request(["L6"], REASON, _utc(5)[:10]),
                     "never in a run's contract|does not apply")

    def test_an_exception_for_an_untargeted_platform_or_unknown_viewport_is_refused(self):
        self.refused(_request(["L23"], REASON, _utc(5)[:10], ["platform=poki"]),
                     "scope.platforms poki are not targeted by this run")
        self.refused(_request(["L23"], REASON, _utc(5)[:10], ["viewport=watch"]),
                     "scope.viewports watch are not viewports")

    def test_one_bad_record_refuses_them_all(self):
        records = (_request(["L23"], REASON, _utc(5)[:10])
                   + _request(["L23"], "short", _utc(5)[:10]))
        self.refused(records, "exception 2")


class Unauthorized(_Case):
    def test_automation_cannot_grant_an_exception(self):
        api, state = self.to_g4()
        records = _request(["L23"], REASON, _utc(5)[:10])
        self.assertRefused(api, state, records, "automation", decided_by="automation")
        # From inside a step's process tree, the CLI decides `automation` by itself.
        with patch.patch.dict(os.environ, {"WGF_PROC_TAG": "a-step"}):
            self.assertRefused(api, state, records, "automation", decided_by=None)

    def test_an_appended_event_line_is_no_ones_act(self):
        record = {"rule_id": "L23", "approved_by": {"identifier": "cuong", "mode": "human"}}
        events = [{"event": exceptions.EVENT, "data": {
            "exception": record, "decided_by": "human", "resume_nonce": "n1"}}]
        self.assertEqual(exceptions.granted(events), [])
        events.append({"event": exceptions.RESUMED_EVENT, "data": {"resume_nonce": "n1"}})
        self.assertEqual(exceptions.granted(events), [record])
        # A record that names no person, or not as a person, is no one's act.
        for approved in ({"identifier": "human", "mode": "human"},
                         {"identifier": "cuong", "mode": "automation"}, {}):
            events[0]["data"]["exception"] = dict(record, approved_by=approved)
            self.assertEqual(exceptions.granted(events), [])
        events[0]["data"]["exception"] = record
        events[0]["data"].pop("decided_by")
        self.assertEqual(exceptions.granted(events), [])
        events[0]["data"]["exception"] = record
        events[0]["data"]["decided_by"] = "automation"
        self.assertEqual(exceptions.granted(events), [])

    def test_the_grant_itself_refuses_automation(self):
        with self.assertRaisesRegex(exceptions.ExceptionRefused, "unauthorized"):
            exceptions.grant(None, None, [{"rule_id": "L23"}], "automation")

    def test_no_configuration_grants_an_exception(self):
        configured = {"rule_id": "L23", "reason": REASON, "scope": {},
                      "approved_by": {"identifier": "ops", "mode": "human"},
                      "created_at": _utc(0), "expires_at": _utc(5)}
        api, state = self.to_g4(self.api({"knowledge": {"exceptions": [configured]}}))
        contract = self.contract(api, state)
        self.assertEqual(contract["exceptions"], [])
        refused = contract["exceptions_refused"]
        self.assertEqual(len(refused), 1)
        self.assertEqual(refused[0]["exception"], configured)
        self.assertIn("never configuration", refused[0]["problems"][0])

    def test_an_exception_is_granted_only_on_resume(self):
        api, state = self.to_g4()
        with self.assertRaisesRegex(EngineError, "with resume"):
            api.run(RunRequest(run_id=state.run_id, exceptions=[{"rule_id": "L23"}]))
        self.assertEqual(self.granted_events(api, state.run_id), [])


class Expired(_Case):
    def test_an_exception_expired_when_the_contract_is_made_is_refused(self):
        api, state = self.to_g4()
        self.grant(api, state.run_id, _request(["L23"], REASON, _utc(2)))
        # The contract is made again three days later, by the engine's clock.
        later = (datetime.datetime.now(datetime.timezone.utc)
                 + datetime.timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        api = self.api(clock=lambda: later)
        state = self.remake(api, state.run_id)
        contract = self.contract(api, state)
        self.assertEqual(contract["exceptions"], [])
        self.assertTrue(any("expired" in p for r in contract["exceptions_refused"]
                            for p in r["problems"]))


class OldRuns(_Case):
    def test_a_run_before_the_knowledge_model_has_nothing_to_except(self):
        policy = dict(quality.load_policy(), knowledge=[])
        with patch.patch.object(quality, "load_policy", return_value=policy):
            api, state = self.to_g4()
        self.assertNotIn("knowledge", state.params["quality"])
        self.assertRefused(api, state, _request(["L23"], REASON, _utc(5)[:10]),
                           "advisory only")


class CommandLine(unittest.TestCase):
    def parse(self, *argv):
        commands = wgf._commands([])
        return wgf.build_parser(commands).parse_args(["resume", "run-1", *argv])

    def test_resume_except_builds_the_request(self):
        args = self.parse("--except", "L23", "--reason", REASON, "--expires", "2026-10-20",
                          "--scope", "platform=yandex,crazygames", "--scope", "viewport=mobile",
                          "--approved-by", "cuong")
        records = wgf._exception_requests(args)
        self.assertEqual(records, [{
            "rule_id": "L23", "reason": REASON, "expires_at": "2026-10-20T23:59:59Z",
            "scope": {"platforms": ["yandex", "crazygames"], "viewports": ["mobile"]},
            "approved_by": {"identifier": "cuong"}}])

    def test_except_flags_without_except_are_a_usage_error(self):
        with self.assertRaises(wgf.UsageError):
            wgf._exception_requests(self.parse("--reason", REASON))

    def test_a_bad_scope_or_expiry_is_a_usage_error(self):
        with self.assertRaises(wgf.UsageError):
            wgf._exception_requests(self.parse("--except", "L23", "--reason", REASON,
                                               "--expires", "soon"))
        with self.assertRaises(wgf.UsageError):
            wgf._exception_requests(self.parse("--except", "L23", "--reason", REASON,
                                               "--expires", "2026-10-20", "--scope", "x=y"))

    def test_except_is_a_file_only_by_its_name(self):
        # `--except L23` is the rule even when a file named L23 sits in the working
        # directory; a value ending .json, or a path, is a file.
        with tempfile.TemporaryDirectory() as folder:
            with open(os.path.join(folder, "L23"), "w", encoding="utf-8") as handle:
                handle.write("{}")
            cwd = os.getcwd()
            os.chdir(folder)
            try:
                records = wgf._exception_requests(self.parse(
                    "--except", "L23", "--reason", REASON, "--expires", "2026-10-20",
                    "--approved-by", "cuong"))
            finally:
                os.chdir(cwd)
        self.assertEqual(records[0]["rule_id"], "L23")
        with self.assertRaisesRegex(wgf.UsageError, "No such file|cannot find"):
            wgf._exception_requests(self.parse("--except", "dir/none", "--approved-by", "cuong"))

    def test_no_except_is_no_request(self):
        self.assertEqual(wgf._exception_requests(self.parse()), [])


if __name__ == "__main__":
    unittest.main()

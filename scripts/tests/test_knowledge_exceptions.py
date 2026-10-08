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


def _issued(events):
    """What the engine would have kept for `events`: each nonce's operator events, digested
    (wgflib.workflow.engine.operator_digest)."""
    from wgflib.workflow.engine import operator_digest
    acts = {}
    for event in events:
        data = event.get("data") or {}
        nonce = data.get("resume_nonce")
        if nonce and event.get("event") != exceptions.RESUMED_EVENT:
            acts.setdefault(nonce, []).append((event.get("event"), data))
    return {nonce: operator_digest(found) for nonce, found in acts.items()}


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
        self.assertEqual(exceptions.granted(api.store.read_events(state.run_id),
                                            exceptions.issued_nonces(
                                                api.store.run_dir(state.run_id))), [record])
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
        self.assertEqual(exceptions.granted(events, _issued(events)), [])
        events.append({"event": exceptions.RESUMED_EVENT, "data": {"resume_nonce": "n1"}})
        issued = _issued(events)
        self.assertEqual(exceptions.granted(events, issued), [record])
        # Fail closed: without what the engine issued, nothing is honoured.
        self.assertEqual(exceptions.granted(events), [])
        self.assertEqual(exceptions.granted(events, {}), [])
        self.assertEqual(exceptions.issued_nonces(None), {})
        # A record that names no person, or not as a person, is no one's act.
        for approved in ({"identifier": "human", "mode": "human"},
                         {"identifier": "cuong", "mode": "automation"}, {}):
            events[0]["data"]["exception"] = dict(record, approved_by=approved)
            self.assertEqual(exceptions.granted(events, _issued(events)), [])
        events[0]["data"]["exception"] = record
        events[0]["data"].pop("decided_by")
        self.assertEqual(exceptions.granted(events, _issued(events)), [])
        events[0]["data"]["exception"] = record
        events[0]["data"]["decided_by"] = "automation"
        self.assertEqual(exceptions.granted(events, _issued(events)), [])

    def _forge(self, run_dir, nonce):
        forged = _request(["L23"], REASON, _utc(5)[:10])[0]
        forged.update(approved_by={"identifier": "mallory", "mode": "human"},
                      created_at=_utc(0))
        with open(os.path.join(run_dir, "events.jsonl"), "a", encoding="utf-8") as handle:
            for line in ({"event": exceptions.EVENT, "data": {
                    "exception": forged, "decided_by": "human", "resume_nonce": nonce}},
                    {"event": exceptions.RESUMED_EVENT, "data": {"resume_nonce": nonce}}):
                handle.write(json.dumps(line) + "\n")

    def test_a_forged_pair_with_a_made_up_nonce_is_no_ones_act(self):
        # A real grant: its nonce, and the digest of what its resume recorded, are kept.
        api, state = self.to_g4()
        self.grant(api, state.run_id, _request(["L23"], REASON, _utc(5)[:10]))
        run_dir = api.store.run_dir(state.run_id)
        issued = exceptions.issued_nonces(run_dir)
        real = self.granted_events(api, state.run_id)[0]["data"]["resume_nonce"]
        self.assertEqual(list(issued), [real])
        self.assertTrue(issued[real].startswith("sha256:"))
        self._forge(run_dir, "f0rged")
        events = api.store.read_events(state.run_id)
        found = exceptions.recorded(events, issued)
        self.assertEqual([why is None for _, why in found], [True, False])
        self.assertIn("not one the engine issued", found[1][1])
        # The contract the run makes next lists the real one only.
        state = self.remake(api, state.run_id)
        self.assertEqual([e["approved_by"]["identifier"]
                          for e in self.contract(api, state)["exceptions"]], ["cuong"])

    def test_a_forged_pair_reusing_an_issued_nonce_is_no_ones_act(self):
        # The nonce is copied from events.jsonl: issued, but used once - the copy makes a
        # second WORKFLOW_RESUMED and changes what the nonce's resume recorded.
        api, state = self.to_g4()
        self.grant(api, state.run_id, _request(["L23"], REASON, _utc(5)[:10]))
        run_dir = api.store.run_dir(state.run_id)
        real = self.granted_events(api, state.run_id)[0]["data"]["resume_nonce"]
        self._forge(run_dir, real)
        events = api.store.read_events(state.run_id)
        found = exceptions.recorded(events, exceptions.issued_nonces(run_dir))
        self.assertEqual([why is None for _, why in found], [False, False])
        self.assertTrue(all("2 WORKFLOW_RESUMED" in why for _, why in found), found)
        # A grant line edited in place (one resume line, a changed record) is caught by the
        # digest.
        lines = [json.loads(l) for l in open(os.path.join(run_dir, "events.jsonl"),
                                             encoding="utf-8")][:-2]
        edited = [dict(e) for e in lines]
        for event in edited:
            if event.get("event") == exceptions.EVENT:
                event["data"] = dict(event["data"], exception=dict(
                    event["data"]["exception"], rule_id="L26"))
        found = exceptions.recorded(edited, exceptions.issued_nonces(run_dir))
        self.assertIn("digest differs", found[0][1])

    def test_genuine_grants_are_honoured_across_resumes(self):
        api, state = self.to_g4()
        self.grant(api, state.run_id, _request(["L23"], REASON, _utc(5)[:10]))
        state = self.grant(api, state.run_id, _request(["L26"], REASON, _utc(6)[:10],
                                                       approver="Cuong N"))
        run_dir = api.store.run_dir(state.run_id)
        issued = exceptions.issued_nonces(run_dir)
        self.assertEqual(len(issued), 2)
        found = exceptions.granted(api.store.read_events(state.run_id), issued)
        self.assertEqual([(r["rule_id"], r["approved_by"]["identifier"]) for r in found],
                         [("L23", "cuong"), ("L26", "Cuong N")])

    def test_a_state_from_before_the_digests_honours_nothing(self):
        api, state = self.to_g4()
        self.grant(api, state.run_id, _request(["L23"], REASON, _utc(5)[:10]))
        run_dir = api.store.run_dir(state.run_id)
        path = os.path.join(run_dir, "state.json")
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        data["resume_nonces"] = list(data["resume_nonces"])  # e81a941's list
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(data, handle)
        found = exceptions.recorded(api.store.read_events(state.run_id),
                                    exceptions.issued_nonces(run_dir))
        self.assertIn("before the engine kept the digest", found[0][1])

    def test_only_a_human_decider_is_a_person(self):
        record = {"rule_id": "L23", "approved_by": {"identifier": "cuong", "mode": "human"}}
        for who in ("cuong", "Human", "auto-approved", ""):
            events = [{"event": exceptions.EVENT, "data": {
                "exception": record, "decided_by": who, "resume_nonce": "n1"}},
                {"event": exceptions.RESUMED_EVENT, "data": {"resume_nonce": "n1"}}]
            self.assertEqual(exceptions.granted(events, _issued(events)), [], who)

    def test_a_role_or_a_program_is_not_an_approver(self):
        for name in ("the human", "an agent", "claude", "Claude Code", "gpt-5", "the bot",
                     "CI runner", "my reviewer", "42", "codex", "team", "cli",
                     "the reviewer", "release team", "QA lead"):
            self.assertIsNotNone(exceptions.approver_problem(name), name)
        # A name with a person's word in it passes: the check refuses placeholders, it does
        # not verify identity.
        for name in ("cuong", "Cuong N", "duycu", "j.smith@studio", "alice the reviewer"):
            self.assertIsNone(exceptions.approver_problem(name), name)

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


class TakesEffect(_Case):
    def test_a_grant_at_g4_is_listed_by_the_next_quality_gate(self):
        api, state = self.to_g4()
        state = self.grant(api, state.run_id, _request(["L23"], REASON, _utc(5)[:10]))
        report = api.store.read_artifact(state.run_id, state.latest_of_type("quality-report"))
        self.assertEqual(report["compliance"]["exceptions"], [])  # judged before the grant
        state = api.run(RunRequest(resume=state.run_id, from_step="quality-gate",
                                   decided_by="human"))
        report = api.store.read_artifact(state.run_id, state.latest_of_type("quality-report"))
        listed = report["compliance"]["exceptions"]
        self.assertEqual([(e["rule_id"], e["approved_by"]["identifier"]) for e in listed],
                         [("L23", "cuong")])
        self.assertEqual(listed[0]["status"], "honoured")
        # The placeholder gate applies it: L23 EXCEPTED, counted so, never blocking.
        section = report["compliance"]
        l23 = next(r for r in section["rules"] if r["id"] == "L23")
        self.assertEqual((l23["status"], l23.get("measured_status")), ("EXCEPTED", "UNMEASURED"))
        self.assertEqual(section["counts"]["total"]["excepted"], 1)
        self.assertNotIn("L23", section["blocking"])

    def test_the_command_says_when_a_grant_takes_effect(self):
        text = wgf.exception_hint("run-1", ["L23"])
        self.assertIn("wgf resume run-1 --from quality-gate", text)
        self.assertIn("--from knowledge-contract", text)
        self.assertIn("read by this resume's quality-gate",
                      wgf.exception_hint("run-1", ["L23"], "quality-gate"))

    def test_the_contract_command_lists_honoured_exceptions(self):
        import contextlib
        import io
        from wgf_knowledge import cli
        body = {"facets": {}, "counts": {}, "rules": [], "not_applicable": [],
                "required_validators": [], "regression_suite": [],
                "exceptions": [{"rule_id": "L23", "reason": REASON, "expires_at": "2026-11-01",
                                "approved_by": {"identifier": "cuong", "mode": "human"}}]}
        with contextlib.redirect_stdout(io.StringIO()) as out:
            cli._render(body)
        self.assertIn("excepted     L23 by cuong until 2026-11-01: " + REASON, out.getvalue())


class GateLines(unittest.TestCase):
    def test_g3_lines_carry_reason_and_recommended_and_g4_lines_no_empty_checks(self):
        from wgflib import gate_evidence
        contract = {"rules": [{"id": "L1", "level": "recommended"}], "required_validators": [],
                    "counts": {"blocking": 0, "required": 0, "recommended": 1,
                               "experimental": 0, "not_applicable": 0},
                    "exceptions": [{"rule_id": "L23", "reason": REASON,
                                    "approved_by": {"identifier": "cuong", "mode": "human"},
                                    "expires_at": "2026-11-01"}]}
        text = "\n".join(gate_evidence.render(gate_evidence.summarize(
            {"knowledge-contract": contract})))
        self.assertIn("1 recommended", text)
        self.assertIn("recommended (reported, never blocking): L1", text)
        self.assertIn("by cuong, until 2026-11-01): " + REASON[:40], text)
        lines = gate_evidence._compliance_lines({
            "verdict": "RELEASE_BLOCKED", "mode": "enforcing", "versions": {},
            "failing": [{"id": "L23", "level": "required", "status": "UNMEASURED",
                         "blocks": True, "checks": []}]})
        self.assertTrue(any(line.rstrip().endswith("UNMEASURED") for line in lines), lines)


class AdvancedPast(unittest.TestCase):
    """A resume that finds its last step already succeeded ends the run by advancing past it
    - and still records the person's acts passed with it (Core v1: never dropped)."""

    def test_operator_events_are_recorded_when_the_run_ends_on_resume(self):
        import test_workflow_engine as harness
        from wgflib.workflow.model import StepStatus
        case = harness.EngineCase()
        case.setUp()
        self.addCleanup(case.doCleanups)
        engine = case.engine(harness.LINEAR)
        run = engine.start()
        self.assertEqual(run.status, RunStatus.COMPLETED)
        state = case.store.load(run.run_id)
        # The driver died after recording c's success, before moving the cursor on.
        state.status, state.cursor, state.exit = RunStatus.RUNNING, "c", None
        state.step("c").status = StepStatus.SUCCESS
        case.store.save(state)
        ended = engine.resume(run.run_id, operator_events=[("TEST_OPERATOR_ACT", {"x": 1})])
        self.assertIn(ended.status, RunStatus.TERMINAL)
        events = case.store.read_events(run.run_id)
        acts = [e for e in events if e["event"] == "TEST_OPERATOR_ACT"]
        self.assertEqual(len(acts), 1)
        nonce = acts[0]["data"]["resume_nonce"]
        self.assertEqual(list(case.store.load(run.run_id).resume_nonces), [nonce])
        resumed = [e for e in events if e["event"] == exceptions.RESUMED_EVENT]
        self.assertEqual(resumed[-1]["data"].get("resume_nonce"), nonce)


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

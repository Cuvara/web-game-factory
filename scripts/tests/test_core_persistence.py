"""Core v1 acceptance: the run store survives interrupted writes, torn logs, racing lock
takers and hostile identifiers - and a run interrupted anywhere resumes consistently.

Part of the WORKFLOW category of the Core Acceptance Suite (`wgf test-core`). Interruptions
are simulated by making os.replace / fsync / a save raise at the worst moment, or by writing
the truncated files a crash would leave.

Run from the web-game-factory repository root:

    python3 -m unittest discover scripts/tests
"""

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
for _path in (SCRIPTS, HERE):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import wgf  # noqa: E402
from test_workflow_engine import CHECKPOINT, LINEAR, EngineCase  # noqa: E402
from wgflib.workflow import store as store_module  # noqa: E402
from wgflib.workflow.definition import DefinitionError, parse_definition  # noqa: E402
from wgflib.workflow.engine import EngineError  # noqa: E402
from wgflib.workflow.events import Events  # noqa: E402
from wgflib.workflow.model import (  # noqa: E402
    ArtifactOutput,
    RunStatus,
    StepResult,
    StepStatus,
)
from wgflib.workflow.store import RunLocked, RunStore, StoreError  # noqa: E402
from wgflib.yamllite import load  # noqa: E402

DEAD_PID = 999999999


class Crash(BaseException):
    """A simulated process death: not an Exception, so nothing in the engine catches it."""


def read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


class AtomicWrites(EngineCase):
    def test_an_artifact_write_interrupted_before_the_rename_leaves_the_old_file(self):
        run = self.engine(LINEAR).start(scope="a")
        ref = run.latest_artifact("art-a")
        path = os.path.join(self.store.run_dir(run.run_id), *ref.location.split("/"))
        before = read(path)
        with mock.patch.object(store_module.os, "replace", side_effect=OSError("disk gone")):
            with self.assertRaises(OSError):
                self.store.write_artifact(run.run_id, "art-a", 1, {"half": "written"})
        self.assertEqual(read(path), before)
        self.assertFalse(os.path.exists(path + ".tmp"))
        self.assertEqual(self.store.read_artifact(run.run_id, ref), {"from": "a", "visit": 1})

    def test_an_fsync_failure_midway_leaves_the_previous_state(self):
        store = RunStore(self.scratch, fsync=True)
        run = self.engine(LINEAR).start(scope="a")
        state = store.load(run.run_id)
        previous = state.message
        state.message = "never persisted"
        with mock.patch.object(store_module.os, "fsync", side_effect=OSError("I/O error")):
            with self.assertRaises(OSError):
                store.save(state)
        self.assertEqual(store.load(run.run_id).message, previous)
        self.assertFalse(os.path.exists(os.path.join(store.run_dir(run.run_id),
                                                     "state.json.tmp")))

    def test_latest_and_requests_are_written_atomically(self):
        run = self.engine(LINEAR).start(scope="a")
        with mock.patch.object(store_module.os, "replace", side_effect=OSError("no")):
            with self.assertRaises(OSError):
                self.store.mark_latest("run-999")
            with self.assertRaises(OSError):
                self.store.request(run.run_id, "cancel")
        self.assertEqual(self.store.latest().run_id, run.run_id)
        self.assertFalse(self.store.requested(run.run_id, "cancel"))


class UnreadableState(EngineCase):
    def state_path(self, run_id):
        return os.path.join(self.store.run_dir(run_id), "state.json")

    def test_a_truncated_state_file_is_a_clear_store_error(self):
        run = self.engine(LINEAR).start(scope="a")
        path = self.state_path(run.run_id)
        text = read(path)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text[: len(text) // 2])
        with self.assertRaises(StoreError) as caught:
            self.store.load(run.run_id)
        self.assertIn("unreadable state.json", str(caught.exception))
        self.assertNotIn(".tmp", str(caught.exception))

    def test_a_leftover_temp_file_is_named(self):
        run = self.engine(LINEAR).start(scope="a")
        path = self.state_path(run.run_id)
        text = read(path)
        with open(path + ".tmp", "w", encoding="utf-8") as handle:
            handle.write(text)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("")
        with self.assertRaises(StoreError) as caught:
            self.store.load(run.run_id)
        self.assertIn("state.json.tmp", str(caught.exception))

    def test_non_object_state_and_missing_fields_are_store_errors(self):
        run = self.engine(LINEAR).start(scope="a")
        for content in ("[1, 2]", '{"format": 1}', "\x00\x00"):
            with self.subTest(content):
                with open(self.state_path(run.run_id), "w", encoding="utf-8") as handle:
                    handle.write(content)
                with self.assertRaises(StoreError):
                    self.store.load(run.run_id)

    def test_an_unreadable_run_is_reported_by_runs_not_hidden(self):
        engine = self.engine(LINEAR)
        good = engine.start(scope="a")
        bad = engine.start(scope="a")
        with open(self.state_path(bad.run_id), "w", encoding="utf-8") as handle:
            handle.write("{")
        problems = []
        self.assertEqual([s.run_id for s in self.store.list_runs(problems)], [good.run_id])
        self.assertEqual([p[0] for p in problems], [bad.run_id])


class TornEventLog(EngineCase):
    def events_path(self, run_id):
        return os.path.join(self.store.run_dir(run_id), "events.jsonl")

    def tear(self, run_id):
        with open(self.events_path(run_id), "a", encoding="utf-8") as handle:
            handle.write('{"event": "STEP_COMPL')  # the crash happened mid-append

    def test_a_partial_last_line_is_skipped_and_reported(self):
        run = self.engine(LINEAR).start()
        count = len(self.store.read_events(run.run_id))
        self.tear(run.run_id)
        problems = []
        events = self.store.read_events(run.run_id, problems)
        self.assertEqual(len(events), count)
        self.assertEqual(len(problems), 1)
        self.assertIn("partial last line", problems[0][1])

    def test_the_next_append_starts_on_a_fresh_line(self):
        self.script.set("b", StepResult.blocked("stop"))
        engine = self.engine(LINEAR)
        run = engine.start()
        count = len(self.store.read_events(run.run_id))
        self.tear(run.run_id)
        engine.resume(run.run_id)
        problems = []
        events = self.store.read_events(run.run_id, problems)
        self.assertEqual(len(problems), 1)
        self.assertIn("bad line", problems[0][1])  # no longer last, still one bad line
        self.assertGreater(len(events), count)
        self.assertEqual(events[count]["event"], Events.WORKFLOW_RESUMED)

    def test_logs_and_status_keep_working_on_a_torn_log(self):
        scratch = tempfile.mkdtemp(prefix="wgf-torn-")
        self.addCleanup(shutil.rmtree, scratch, ignore_errors=True)
        store_dir, config = os.path.join(scratch, "store"), os.path.join(scratch, "f.yaml")
        with open(config, "w", encoding="utf-8") as handle:
            handle.write("factory:\n  storage:\n    fsync: false\n")

        def run(*args):
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = wgf.main([*args, "--store", store_dir, "--config", config])
            return code, out.getvalue(), err.getvalue()

        self.assertEqual(run("research", "--mock", "--quiet")[0], 0)
        run_id = RunStore(store_dir).latest().run_id
        with open(os.path.join(store_dir, "workflows", run_id, "events.jsonl"), "a") as handle:
            handle.write('{"event": "WORKFLOW_COMP')
        for args in (("logs",), ("logs", "--json"), ("status",), ("runs",)):
            with self.subTest(args):
                code, out, err = run(*args)
                self.assertEqual(code, 0, err)
                if args[0] == "logs":
                    self.assertIn("WORKFLOW_COMPLETED", out)
                    self.assertIn("partial last line", err)
        code, out, _ = run("logs", "--json")
        for line in out.splitlines():
            json.loads(line)

    def test_duplicate_events_do_not_change_state(self):
        self.script.set("b", StepResult.blocked("stop"))
        engine = self.engine(LINEAR)
        run = engine.start()
        before = self.store.load(run.run_id).to_dict()
        path = self.events_path(run.run_id)
        lines = read(path)
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(lines)  # every event, twice
        self.assertEqual(self.store.load(run.run_id).to_dict(), before)
        self.assertEqual(len(self.store.read_events(run.run_id)), 2 * len(lines.splitlines()))
        self.assertEqual(engine.resume(run.run_id).status, RunStatus.COMPLETED)
        self.assertEqual(self.store.load(run.run_id).steps["a"].executions, 1)
        self.assertEqual(self.store.load(run.run_id).steps["b"].executions, 2)


class CrashBetweenArtifactAndState(EngineCase):
    """The worst moment: the artifact file is written, the state recording it is not."""

    def crash_after_write(self, engine, times=1):
        real_write, real_save = self.store.write_artifact, self.store.save
        armed = {"left": times, "written": False}

        def write(*args, **kwargs):
            result = real_write(*args, **kwargs)
            armed["written"] = True
            return result

        def save(state):
            if armed["written"] and armed["left"]:
                armed["left"] -= 1
                armed["written"] = False
                raise Crash("killed between the artifact write and the state save")
            return real_save(state)

        self.store.write_artifact, self.store.save = write, save
        return lambda: setattr(self.store, "save", real_save)

    def test_resume_rewrites_the_orphan_under_the_same_version_and_records_it_once(self):
        engine = self.engine(LINEAR)
        self.script.set("a", StepResult.success([ArtifactOutput("art-a", {"try": 1})]))
        disarm = self.crash_after_write(engine)
        with self.assertRaises(Crash):
            engine.start()
        disarm()

        on_disk = self.store.load("run-1")
        self.assertEqual(on_disk.status, RunStatus.RUNNING)          # a crashed run
        self.assertEqual(on_disk.steps["a"].status, StepStatus.RUNNING)
        self.assertEqual(on_disk.artifacts, {})                      # nothing recorded
        orphan = os.path.join(self.store.run_dir("run-1"), "artifacts", "art-a", "v1.json")
        self.assertTrue(os.path.exists(orphan))
        logged = [e["event"] for e in self.store.read_events("run-1")]
        self.assertNotIn(Events.ARTIFACT_CREATED, logged)            # log agrees with state

        self.script.set("a", StepResult.success([ArtifactOutput("art-a", {"try": 2})]))
        state = self.engine(LINEAR).resume("run-1")
        self.assertEqual(state.status, RunStatus.COMPLETED)
        versions = state.artifacts["art-a"]
        self.assertEqual([r.version for r in versions], [1])         # deterministic numbering
        self.assertEqual(self.store.read_artifact("run-1", versions[0]), {"try": 2})
        events = self.store.read_events("run-1")
        created = [e for e in events if e["event"] == Events.ARTIFACT_CREATED
                   and e["data"]["id"] == "art-a"]
        self.assertEqual(len(created), 1)
        self.assertEqual(created[0]["data"]["checksum"], versions[0].checksum)
        warnings = [e for e in events if e["event"] == Events.STEP_LOG
                    and "unrecorded artifact" in e.get("message", "")]
        self.assertEqual(len(warnings), 1)

    def test_a_persist_failure_on_the_second_output_records_neither_and_retries(self):
        text = LINEAR.replace("      outputs: [art-a]\n", "      outputs: [art-a, art-x]\n")
        engine = self.engine(text)
        self.script.set("a", *[StepResult.success([ArtifactOutput("art-a", {"n": 1}),
                                                   ArtifactOutput("art-x", {"n": 2})])] * 2)
        real_write, calls = self.store.write_artifact, []

        def write(run_id, artifact_id, version, content):
            calls.append(artifact_id)
            if len(calls) == 2:
                raise OSError("No space left on device")
            return real_write(run_id, artifact_id, version, content)

        self.store.write_artifact = write
        state = engine.start()
        self.assertEqual(state.status, RunStatus.COMPLETED)
        self.assertEqual(state.steps["a"].executions, 2)
        failed = [e for e in self.events if e["event"] == Events.STEP_FAILED]
        self.assertIn("could not persist artifacts", failed[0]["error"])
        self.assertEqual({k: [r.version for r in v] for k, v in state.artifacts.items()},
                         {"art-a": [1], "art-x": [1], "art-b": [1], "art-c": [1]})
        for versions in state.artifacts.values():
            self.store.read_artifact(state.run_id, versions[-1])  # every checksum holds

    def test_a_crash_while_a_step_runs_resumes_that_step_only(self):
        engine = self.engine(LINEAR)

        def b(inputs, context):
            raise Crash("power cut inside b")

        self.script.set("b", b)
        with self.assertRaises(Crash):
            engine.start()
        self.script.calls.clear()
        state = self.engine(LINEAR).resume("run-1")
        self.assertEqual(state.status, RunStatus.COMPLETED)
        self.assertEqual(self.script.executed(), ["b", "c"])
        self.assertEqual(state.steps["a"].executions, 1)


class LockTakeover(EngineCase):
    def lock(self, run_id):
        return os.path.join(self.store.run_dir(run_id), "lock")

    def run_id(self):
        return self.engine(LINEAR).start(scope="a").run_id

    def live_other_process(self):
        process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        self.addCleanup(process.wait)
        self.addCleanup(process.kill)
        return process.pid

    def test_a_stale_lock_is_not_removed_once_someone_else_took_it(self):
        run_id = self.run_id()
        live = self.live_other_process()
        # We judged the lock stale; before our guarded re-check, a live process took it.
        with open(self.lock(run_id), "w") as handle:
            handle.write(f"{live}\n")
        self.store._break_stale_lock(self.lock(run_id))
        self.assertEqual(read(self.lock(run_id)).strip(), str(live))
        with self.assertRaises(RunLocked):
            self.store.acquire(run_id)

    def test_a_takeover_in_progress_elsewhere_is_left_alone(self):
        run_id = self.run_id()
        live = self.live_other_process()
        with open(self.lock(run_id), "w") as handle:
            handle.write(f"{DEAD_PID}\n")
        with open(self.lock(run_id) + ".takeover", "w") as handle:
            handle.write(f"{live}\n")
        self.store._break_stale_lock(self.lock(run_id))
        self.assertTrue(os.path.exists(self.lock(run_id)))  # the other taker decides

    def test_a_guard_left_by_a_dead_taker_is_cleared(self):
        run_id = self.run_id()
        for name in ("lock", "lock.takeover"):
            with open(os.path.join(self.store.run_dir(run_id), name), "w") as handle:
                handle.write(f"{DEAD_PID}\n")
        self.store.acquire(run_id)
        self.assertEqual(read(self.lock(run_id)).strip(), str(os.getpid()))
        self.assertFalse(os.path.exists(self.lock(run_id) + ".takeover"))
        self.store.release(run_id)

    def test_an_empty_lock_is_in_progress_until_it_is_old(self):
        run_id = self.run_id()
        open(self.lock(run_id), "w").close()
        with mock.patch.object(store_module, "LOCK_GRACE_SECONDS", 0.3):
            began = time.monotonic()
            self.store.acquire(run_id)  # waits out the grace, then takes it over
            self.assertGreaterEqual(time.monotonic() - began, 0.2)
        self.store.release(run_id)
        open(self.lock(run_id), "w").close()
        old = time.time() - 60
        os.utime(self.lock(run_id), (old, old))
        self.store.acquire(run_id)  # a crashed creator: at once
        self.store.release(run_id)

    def test_release_never_removes_another_owners_lock(self):
        run_id = self.run_id()
        live = self.live_other_process()
        with open(self.lock(run_id), "w") as handle:
            handle.write(f"{live}\n")
        self.store.release(run_id)
        self.assertTrue(os.path.exists(self.lock(run_id)))

    def test_a_lock_naming_this_process_but_not_held_is_stale(self):
        run_id = self.run_id()
        with open(self.lock(run_id), "w") as handle:
            handle.write(f"{os.getpid()}\n")  # left by an earlier engine in this process
        self.assertFalse(self.store.is_held(run_id))
        self.store.acquire(run_id)
        self.assertTrue(self.store.is_held(run_id))
        with self.assertRaises(RunLocked):
            self.store.acquire(run_id)  # not reentrant, even for this process
        self.store.release(run_id)
        self.assertFalse(os.path.exists(self.lock(run_id)))

    def test_requests_to_a_run_another_process_drives_do_not_touch_its_state(self):
        self.script.set("b", StepResult.blocked("stop"))
        engine = self.engine(LINEAR)
        run = engine.start()
        state = self.store.load(run.run_id)
        state.status = RunStatus.RUNNING
        self.store.save(state)
        with open(self.lock(run.run_id), "w") as handle:
            handle.write(f"{self.live_other_process()}\n")
        engine.request_cancel(run.run_id)
        engine.request_cancel(run.run_id)  # idempotent
        engine.request_pause(run.run_id)
        self.assertEqual(self.store.load(run.run_id).status, RunStatus.RUNNING)
        self.assertTrue(self.store.requested(run.run_id, "cancel"))
        self.assertTrue(self.store.requested(run.run_id, "pause"))

    RACER = textwrap.dedent("""
        import sys, time
        sys.path.insert(0, {scripts!r})
        from wgflib.workflow.store import RunStore, RunLocked
        store = RunStore({directory!r}, fsync=False)
        while time.time() < {start}:
            time.sleep(0.001)
        try:
            store.acquire({run_id!r})
        except RunLocked:
            print("refused")
        else:
            print("got")
            sys.stdout.flush()
            time.sleep(1.5)
            store.release({run_id!r})
    """)

    def test_racing_takers_of_one_stale_lock_end_with_exactly_one_owner(self):
        run_id = self.run_id()
        with open(self.lock(run_id), "w") as handle:
            handle.write(f"{DEAD_PID}\n")
        source = self.RACER.format(scripts=SCRIPTS, directory=self.scratch, run_id=run_id,
                                   start=time.time() + 1.5)
        racers = [subprocess.Popen([sys.executable, "-c", source], stdout=subprocess.PIPE,
                                   text=True) for _ in range(6)]
        results = [racer.communicate(timeout=60)[0].strip() for racer in racers]
        self.assertEqual(sorted(results).count("got"), 1, results)
        self.assertEqual(sorted(results).count("refused"), 5, results)


class HostileIdentifiers(EngineCase):
    BAD_IDS = ["../x", "a/b", "a\\b", "..", "a..b", "run\n", "run\x00x", "", ".hidden",
               "x" * 200, "a b"]

    def test_run_ids_are_refused_before_they_touch_a_path(self):
        for run_id in self.BAD_IDS + [None, 7]:
            with self.subTest(repr(run_id)):
                with self.assertRaises(StoreError):
                    self.store.run_dir(run_id)
                with self.assertRaises(StoreError):
                    self.store.load(run_id)
        self.assertFalse(os.path.exists(os.path.join(os.path.dirname(self.scratch), "x")))

    def test_artifact_ids_are_refused(self):
        run = self.engine(LINEAR).start(scope="a")
        for artifact_id in ["../x", "art\n", "Art", "art/x", "art\x00", "", "-art"]:
            with self.subTest(repr(artifact_id)):
                with self.assertRaises(StoreError):
                    self.store.write_artifact(run.run_id, artifact_id, 1, {"x": 1})

    def test_a_step_output_named_with_a_newline_fails_the_step(self):
        self.script.set("a", StepResult.success([ArtifactOutput("art-a", {"x": 1},
                                                                name="art-a\n")]))
        state = self.engine(LINEAR).start()
        self.assertEqual(state.status, RunStatus.FAILED)
        self.assertIn("not kebab-case", state.steps["a"].error)

    def test_a_tampered_artifact_location_cannot_leave_the_run(self):
        self.script.set("c", StepResult.blocked("stop"))
        engine = self.engine(LINEAR)
        run = engine.start()
        path = os.path.join(self.store.run_dir(run.run_id), "state.json")
        data = json.loads(read(path))
        data["artifacts"]["art-b"][0]["location"] = "../../../../etc/passwd"
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(data, handle)
        with self.assertRaises(StoreError):
            self.store.read_artifact(run.run_id, self.store.load(run.run_id)
                                     .latest_artifact("art-b"))
        # Refused before anything runs (wgflib/workflow/integrity.py), not just at the read.
        with self.assertRaisesRegex(EngineError, "art-b v1: location"):
            engine.resume(run.run_id)
        self.assertEqual(self.store.load(run.run_id).status, RunStatus.BLOCKED)
        self.assertEqual(self.script.executed().count("c"), 1)

    def test_a_hostile_latest_pointer_is_ignored(self):
        run = self.engine(LINEAR).start(scope="a")
        with open(os.path.join(self.store.workflows, "LATEST"), "w") as handle:
            handle.write("../../etc\n")
        self.assertEqual(self.store.latest().run_id, run.run_id)
        with self.assertRaises(StoreError):
            self.store.mark_latest("../x")

    def test_decisions_that_are_not_plain_labels_are_refused_before_anything_changes(self):
        engine = self.engine(CHECKPOINT.replace("GATE", "G2"))
        run = engine.start()
        before = self.store.load(run.run_id).to_dict()
        for decision in ["approve\n", "app rove", "a\x00", "../approve", "", "x" * 65, None,
                         7]:
            with self.subTest(repr(decision)):
                with self.assertRaises(EngineError):
                    engine.resume(run.run_id, decision=decision if decision is not None
                                  else 0)
        with self.assertRaises(EngineError):
            engine.resume(run.run_id, decision="approve", note="bad\x00note")
        with self.assertRaises(EngineError):
            engine.resume(run.run_id, decision="approve", decided_by="human\nroot")
        self.assertEqual(self.store.load(run.run_id).to_dict(), before)
        self.assertFalse(self.store.is_held(run.run_id))
        self.assertEqual(engine.resume(run.run_id, decision="approve",
                                       note="multi\nline is fine").status,
                         RunStatus.COMPLETED)

    def test_request_kinds_are_a_closed_set(self):
        run = self.engine(LINEAR).start(scope="a")
        with self.assertRaises(StoreError):
            self.store.request(run.run_id, "../state.json")


class DefinitionRefusals(unittest.TestCase):
    BASE = """
workflow:
  id: tiny
  version: 1
  steps:
    - id: a
      type: alpha
    - id: b
      type: beta
"""

    def refused(self, text, fragment):
        with self.assertRaises(DefinitionError) as caught:
            parse_definition(load(text), "<test>")
        self.assertIn(fragment, str(caught.exception))

    def test_unknown_route_target(self):
        self.refused(self.BASE.replace("type: beta", "type: beta\n      on: {fail: nowhere}"),
                     "'nowhere' is not a step id")
        self.refused(self.BASE.replace("type: beta", "type: beta\n      next: ghost"),
                     "'ghost' is not a step id")

    def test_duplicate_step_id(self):
        self.refused(self.BASE.replace("id: b", "id: a"), "duplicate id")

    def test_malformed_shapes_are_definition_errors_not_crashes(self):
        cases = {
            "type: beta\n      on: {fail: [a]}": "is not a step id",
            "type: beta\n      on: sideways": "on must be a mapping",
            "type: beta\n      with: [1, 2]": "with must be a mapping",
            "type: beta\n      retry: [1]": "retry must be a mapping",
            "type: beta\n      max_visits: true": "max_visits",
        }
        for replacement, fragment in cases.items():
            with self.subTest(replacement):
                self.refused(self.BASE.replace("type: beta", replacement), fragment)
        self.refused(self.BASE.replace("  version: 1\n", "  version: 1\n  defaults: [x]\n"),
                     "defaults must be a mapping")
        self.refused(self.BASE.replace("  version: 1\n", "  version: 1\n  start: [a]\n"),
                     "workflow.start")

    def test_identifiers_with_a_trailing_newline_are_refused(self):
        document = load(self.BASE)
        document["workflow"]["steps"][1]["id"] = "b\n"
        with self.assertRaises(DefinitionError):
            parse_definition(document, "<test>")
        document = load(self.BASE)
        document["workflow"]["steps"][1]["type"] = "beta\n"
        with self.assertRaises(DefinitionError):
            parse_definition(document, "<test>")


if __name__ == "__main__":
    unittest.main()

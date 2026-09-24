"""Core Acceptance Suite - PROCESS CLEANUP.

Real processes, no mocks. Every test starts a tree through wgflib.procs, makes it misbehave
the way a real toolchain does - a dev server left running, a detached webServer, a child that
ignores SIGTERM, a flood of output, a cancel from another thread - and then proves nothing
survived, two ways: no process still carries the tree's tag (`procs.tagged_pids`), and every
pid the tree reported is gone (`procs.pid_alive`).

The tag check needs /proc (Linux); elsewhere it is vacuous and the pid check carries the test.
Tests that need a descendant to detach itself need /proc to find it, and skip without it.

    WGF_LIVE_PROCESS_TEST=1   also run the web-game-template's Playwright smoke through
                              procs.run and check no vite / preview server outlives it
                              (needs ../web-game-template/node_modules; slow, not offline).

Run from the web-game-factory repository root:

    python -m unittest scripts.tests.test_core_process   (or discover scripts/tests)
"""

import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
sys.path.insert(0, SCRIPTS)

from wgflib import procs  # noqa: E402
from wgflib.workflow.definition import parse_definition  # noqa: E402
from wgflib.workflow.engine import WorkflowEngine  # noqa: E402
from wgflib.workflow.events import Events  # noqa: E402
from wgflib.workflow.model import RunStatus, StepResult  # noqa: E402
from wgflib.workflow.step import StepRegistry, WorkflowStep  # noqa: E402
from wgflib.workflow.store import RunStore  # noqa: E402
from wgflib.yamllite import load  # noqa: E402

TREE = os.path.join(HERE, "fixtures", "proc_tree.py")
HAVE_PROC = os.path.isdir("/proc")
POSIX = os.name == "posix"
GRACE = 1.0  # seconds between SIGTERM and SIGKILL in these tests


def wait_for(predicate, timeout=10.0, interval=0.02):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(interval)
    return predicate()


def roles(pidfile):
    """{"c": pid, "g": pid, ...} from a proc_tree.py pidfile."""
    try:
        with open(pidfile, encoding="utf-8") as handle:
            lines = handle.read().split("\n")
    except FileNotFoundError:
        return {}
    found = {}
    for line in lines:
        role, _, value = line.partition(" ")
        if role and value.strip().isdigit():
            found[role] = int(value)
    return found


@unittest.skipUnless(POSIX, "process groups and signals are POSIX")
class ProcessCase(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.mkdtemp(prefix="wgf-procs-")
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)
        self.pidfile = os.path.join(self.scratch, "pids")
        self.began = time.monotonic()

    def tree(self, action, *flags):
        return [sys.executable, TREE, "child", self.pidfile, ",".join(flags), action]

    def when_ready(self, *wanted):
        """A should_stop that turns True once every role in `wanted` has reported."""
        return lambda: all(role in roles(self.pidfile) for role in wanted)

    def assertNoSurvivors(self, tag, pids):
        pids = [p for p in pids if p]
        self.assertTrue(pids, "the tree reported no pids; the test proves nothing")
        # Reparented descendants are reaped by init asynchronously; allow a moment.
        wait_for(lambda: not procs.tagged_pids(tag)
                 and not any(procs.pid_alive(p) for p in pids), timeout=3.0)
        self.assertEqual(procs.tagged_pids(tag), [], "a tagged process survived")
        for pid in pids:
            self.assertFalse(procs.pid_alive(pid), f"pid {pid} survived")
        self.assertNotIn(tag, procs.live_groups())

    def assertPrompt(self, limit):
        took = time.monotonic() - self.began
        self.assertLess(took, limit, f"took {took:.1f}s")


class EndsOnItsOwn(ProcessCase):
    def test_success_with_a_lingering_background_grandchild(self):
        result = procs.run(self.tree("exit0"), timeout=30, grace_seconds=GRACE)
        pids = roles(self.pidfile)
        self.assertTrue(result.ok, result.tail())
        self.assertEqual(result.returncode, 0)
        # The grandchild held the stdout pipe; the call still returned, and killed it.
        self.assertIn(pids["g"], result.killed)
        self.assertNoSurvivors(result.tag, [pids["c"], pids["g"]])
        self.assertPrompt(10)

    def test_failure_with_a_grandchild(self):
        result = procs.run(self.tree("exit3"), timeout=30, grace_seconds=GRACE)
        pids = roles(self.pidfile)
        self.assertFalse(result.ok)
        self.assertEqual(result.returncode, 3)
        self.assertEqual(result.status, "exited")
        self.assertNoSurvivors(result.tag, [pids["c"], pids["g"]])
        self.assertPrompt(10)

    def test_a_missing_executable_is_an_error_not_an_exception(self):
        result = procs.run(["wgf-no-such-executable-anywhere"], timeout=5)
        self.assertEqual(result.status, "not-started")
        self.assertIsInstance(result.exception, FileNotFoundError)
        self.assertFalse(result.ok)


class IsEnded(ProcessCase):
    def test_timeout(self):
        result = procs.run(self.tree("sleep"), timeout=1.5, grace_seconds=GRACE)
        pids = roles(self.pidfile)
        self.assertTrue(result.timed_out)
        self.assertEqual(result.status, "timeout")
        self.assertNoSurvivors(result.tag, [pids["c"], pids["g"]])
        self.assertPrompt(8)

    def test_idle_timeout(self):
        result = procs.run(self.tree("quiet"), timeout=30, idle_timeout=1.0,
                           grace_seconds=GRACE)
        pids = roles(self.pidfile)
        self.assertTrue(result.idle_timed_out)
        self.assertFalse(result.timed_out)
        self.assertIn("started", result.stdout)
        self.assertNoSurvivors(result.tag, [pids["c"], pids["g"]])
        self.assertPrompt(10)

    def test_cancellation_via_should_stop(self):
        events = []
        result = procs.run(self.tree("sleep"), timeout=30, grace_seconds=GRACE,
                           should_stop=self.when_ready("c", "g"),
                           on_event=lambda kind, **data: events.append(kind))
        pids = roles(self.pidfile)
        self.assertTrue(result.cancelled)
        self.assertEqual(result.status, "cancelled")
        self.assertEqual(events[0], "spawned")
        self.assertIn("cancelled", events)
        self.assertEqual(events[-1], "exited")
        self.assertNoSurvivors(result.tag, [pids["c"], pids["g"]])
        self.assertPrompt(10)

    def test_sigterm_ignored_escalates_to_sigkill(self):
        result = procs.run(self.tree("ignore-term", "ignore-term"), timeout=30,
                           grace_seconds=GRACE, should_stop=self.when_ready("c", "g"))
        pids = roles(self.pidfile)
        self.assertTrue(result.cancelled)
        self.assertEqual(result.returncode, -signal.SIGKILL)
        self.assertNoSurvivors(result.tag, [pids["c"], pids["g"]])
        self.assertPrompt(10)

    def test_keyboard_interrupt_mid_wait(self):
        if threading.current_thread() is not threading.main_thread():
            self.skipTest("SIGINT is delivered to the main thread")
        previous = signal.signal(signal.SIGINT, signal.default_int_handler)
        self.addCleanup(signal.signal, signal.SIGINT, previous)
        tags = []

        def interrupt_when_ready():
            if wait_for(lambda: {"c", "g"} <= set(roles(self.pidfile)), timeout=10):
                tags.extend(procs.live_groups())
                os.kill(os.getpid(), signal.SIGINT)

        threading.Thread(target=interrupt_when_ready, daemon=True).start()
        with self.assertRaises(KeyboardInterrupt):
            procs.run(self.tree("sleep"), timeout=30, grace_seconds=GRACE)
        pids = roles(self.pidfile)
        self.assertTrue(tags)
        for tag in tags:
            self.assertNoSurvivors(tag, [pids["c"], pids["g"]])
        self.assertPrompt(10)


class EscapesTheGroup(ProcessCase):
    @unittest.skipUnless(HAVE_PROC, "a detached descendant is found through /proc")
    def test_descendant_that_setsids_itself(self):
        # Playwright starts its webServer detached: a session and group of its own, which a
        # process-group kill never reaches. The tag in its environment does.
        result = procs.run(self.tree("exit0", "setsid"), timeout=30, grace_seconds=GRACE)
        pids = roles(self.pidfile)
        self.assertTrue(result.ok, result.tail())
        self.assertIn(pids["g"], result.killed)
        self.assertNoSurvivors(result.tag, [pids["c"], pids["g"]])
        self.assertPrompt(10)

    @unittest.skipUnless(HAVE_PROC, "a detached descendant is found through /proc")
    def test_detached_descendant_is_found_on_timeout_too(self):
        result = procs.run(self.tree("sleep", "setsid", "ignore-term"), timeout=1.5,
                           grace_seconds=GRACE)
        pids = roles(self.pidfile)
        self.assertTrue(result.timed_out)
        self.assertNoSurvivors(result.tag, [pids["c"], pids["g"]])
        self.assertPrompt(10)

    def _node_server(self, detached):
        node = shutil.which("node")
        if node is None:
            self.skipTest("node is not installed")
        if detached and not HAVE_PROC:
            self.skipTest("a detached descendant is found through /proc")
        # `vite` under `pnpm`: a node process that starts a node http server and leaves it
        # running (detached, as Playwright's webServer is, when `detached`).
        server = ("const http=require('http');const fs=require('fs');"
                  "const s=http.createServer((q,r)=>r.end('ok'));"
                  "s.listen(0,'127.0.0.1',()=>{fs.appendFileSync(process.argv[1],"
                  "'port '+s.address().port+'\\ng '+process.pid+'\\n');});")
        parent = ("const {spawn}=require('child_process');const fs=require('fs');"
                  "const f=process.argv[1];"
                  f"spawn(process.execPath,['-e',{server!r},f],"
                  f"{{detached:{'true' if detached else 'false'},stdio:'inherit'}});"
                  "fs.appendFileSync(f,'c '+process.pid+'\\n');"
                  "const t=setInterval(()=>{if(fs.readFileSync(f,'utf8').includes('port ')){"
                  "clearInterval(t);process.exit(0);}},20);")
        result = procs.run([node, "-e", parent, self.pidfile], timeout=30,
                           grace_seconds=GRACE)
        pids = roles(self.pidfile)
        self.assertTrue(result.ok, result.tail())
        self.assertIn("port", pids)
        self.assertNoSurvivors(result.tag, [pids["c"], pids["g"]])
        with self.assertRaises(OSError, msg="the server port still accepts connections"):
            socket.create_connection(("127.0.0.1", pids["port"]), timeout=1).close()
        self.assertPrompt(15)

    def test_node_child_that_leaves_a_node_http_server(self):
        self._node_server(detached=False)

    def test_node_child_that_leaves_a_detached_node_http_server(self):
        self._node_server(detached=True)


class Output(ProcessCase):
    def test_more_than_ten_megabytes_does_not_deadlock_and_is_bounded(self):
        # 6 MB on stderr, then 12 MB on stdout, then 2 MB with no newline at all: with either
        # pipe undrained this blocks forever; kept whole it is 20 MB in memory.
        code = ("import sys\n"
                "sys.stderr.write(('e'*99+'\\n')*60000); sys.stderr.flush()\n"
                "sys.stdout.write(('o'*99+'\\n')*120000)\n"
                "sys.stdout.write('x'*2000000); sys.stdout.write('\\nEND\\n')\n")
        lines = []
        result = procs.run([sys.executable, "-c", code], timeout=60,
                           on_output=lambda stream, line: lines.append(len(line)))
        self.assertTrue(result.ok, result.tail())
        limit = procs._TAIL_LIMIT + procs._CHUNK
        self.assertLessEqual(len(result.stdout), limit)
        self.assertLessEqual(len(result.stderr), limit)
        self.assertTrue(result.stdout.endswith("END\n"))
        self.assertGreater(result.truncated, 10_000_000)
        # every newline-terminated line was seen; the long one arrived in bounded pieces
        self.assertGreaterEqual(len(lines), 180_000)
        self.assertLessEqual(max(lines), procs._LINE_LIMIT + procs._CHUNK)
        self.assertPrompt(20)

    def test_stdin_input_and_merged_streams(self):
        code = "import sys; d=sys.stdin.read(); print(d.upper()); print('err', file=sys.stderr)"
        result = procs.run([sys.executable, "-c", code], input="hello", timeout=10,
                           stderr_to_stdout=True)
        self.assertTrue(result.ok)
        self.assertIn("HELLO", result.stdout)
        self.assertIn("err", result.stdout)
        self.assertEqual(result.stderr, "")

    def test_log_path_receives_every_line_and_a_bad_one_is_not_fatal(self):
        log = os.path.join(self.scratch, "logs", "step.log")
        code = "import sys; print('out-line'); print('err-line', file=sys.stderr)"
        result = procs.run([sys.executable, "-c", code], timeout=10, log_path=log)
        self.assertTrue(result.ok)
        with open(log, encoding="utf-8") as handle:
            text = handle.read()
        self.assertIn("[stdout] out-line", text)
        self.assertIn("[stderr] err-line", text)
        open(self.pidfile, "w").close()  # a file where the log's directory would go
        bad = procs.run([sys.executable, "-c", "print(1)"], timeout=10,
                        log_path=os.path.join(self.pidfile, "is", "a", "file"))
        self.assertTrue(bad.ok)


class LongLived(ProcessCase):
    def test_owned_process_close_takes_the_tree_down(self):
        owned = procs.spawn(self.tree("sleep"), stdin=subprocess.PIPE,
                            stdout=subprocess.DEVNULL)
        self.assertIn(owned.tag, procs.live_groups())
        self.assertTrue(wait_for(lambda: {"c", "g"} <= set(roles(self.pidfile))))
        pids = roles(self.pidfile)
        if HAVE_PROC:
            self.assertEqual(set(owned.tree()), {pids["c"], pids["g"]})
        owned.close(grace_seconds=GRACE, wait_seconds=0.2)
        owned.close()  # twice is harmless
        self.assertNoSurvivors(owned.tag, [pids["c"], pids["g"]])

    def _script(self, body):
        path = os.path.join(self.scratch, "owner.py")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(f"import sys\nsys.path.insert(0, {SCRIPTS!r})\n"
                         "from wgflib import procs\n" + body)
        return path

    def test_interpreter_exit_takes_spawned_trees_down(self):
        # A long-lived child (an MCP stdio server) its owner forgot to close.
        owner = self._script(
            f"procs.spawn({self.tree('sleep')!r})\n"
            "import time\n"
            f"from os.path import exists\n"
            f"while 'g ' not in (open({self.pidfile!r}).read() if exists({self.pidfile!r}) "
            "else ''):\n    time.sleep(0.02)\n"
            "time.sleep(0.2)\n")
        result = procs.run([sys.executable, owner], timeout=30, grace_seconds=GRACE)
        pids = roles(self.pidfile)
        self.assertTrue(result.ok, result.tail())
        self.assertNoSurvivors(result.tag, [pids["c"], pids["g"]])

    def test_sigterm_to_the_owner_cleans_up_with_install_signal_cleanup(self):
        # `kill <wgf pid>`: the children are in sessions of their own and never see it.
        owner = self._script(
            "procs.install_signal_cleanup()\n"
            f"procs.run({self.tree('sleep')!r}, grace_seconds={GRACE})\n")
        owned = procs.spawn([sys.executable, owner], stdout=subprocess.DEVNULL)
        self.addCleanup(owned.close, GRACE, 0)
        self.assertTrue(wait_for(lambda: {"c", "g"} <= set(roles(self.pidfile))))
        pids = roles(self.pidfile)
        if HAVE_PROC:
            # The nested owner re-tagged its tree; the lineage keeps it findable from here.
            self.assertTrue({pids["c"], pids["g"]} <= set(procs.tagged_pids(owned.tag)))
        os.kill(owned.pid, signal.SIGTERM)
        owned.process.wait(timeout=10)
        self.assertEqual(owned.process.returncode, 128 + signal.SIGTERM)
        for pid in (pids["c"], pids["g"]):
            wait_for(lambda: not procs.pid_alive(pid), 3)
            self.assertFalse(procs.pid_alive(pid), f"pid {pid} survived its owner's SIGTERM")

    def _mcp_launcher(self, mode):
        # `npx some-mcp-server`: a launcher that leaves a helper behind, then becomes the
        # stdio server itself.
        fake = os.path.join(HERE, "fixtures", "assets", "fake_mcp_server.py")
        code = (f"import os, subprocess, sys, time\n"
                f"subprocess.Popen([sys.executable, {TREE!r}, 'grand', {self.pidfile!r}, ''],"
                f" stdout=subprocess.DEVNULL)\n"
                f"while 'g ' not in (open({self.pidfile!r}).read() "
                f"if os.path.exists({self.pidfile!r}) else ''):\n    time.sleep(0.01)\n"
                f"os.execv(sys.executable, [sys.executable, {fake!r}, {mode!r}])\n")
        return [sys.executable, "-c", code]

    def test_mcp_client_close_ends_the_server_tree(self):
        from wgf_assets.mcp import McpClient

        client = McpClient(self._mcp_launcher("ok"), timeout=10).start()
        owned = client._owned
        server = owned.pid
        client.close()
        self.assertNoSurvivors(owned.tag, [server, roles(self.pidfile)["g"]])

    def test_mcp_client_that_fails_to_start_leaves_nothing(self):
        from wgf_assets.mcp import McpClient, McpError

        tags = []
        real_spawn = procs.spawn

        def spy(*args, **kwargs):
            owned = real_spawn(*args, **kwargs)
            tags.append((owned.tag, owned.pid))
            return owned

        with mock.patch.object(procs, "spawn", spy), self.assertRaises(McpError):
            McpClient(self._mcp_launcher("exit"), timeout=10).start()
        (tag, server), = tags
        self.assertNoSurvivors(tag, [server, roles(self.pidfile)["g"]])

    def test_install_signal_cleanup_refuses_off_the_main_thread(self):
        box = []
        thread = threading.Thread(target=lambda: box.append(procs.install_signal_cleanup()))
        thread.start()
        thread.join()
        self.assertEqual(box, [[]])


# -- the engine -----------------------------------------------------------------------------

ONE_STEP = """
workflow:
  id: procs
  version: 1
  defaults:
    retry: {max_attempts: 1}
  steps:
    - id: work
      type: work
"""


class InsideAWorkflowStep(ProcessCase):
    """A module's runner calls procs.run knowing nothing about workflows; procs.bound (set by
    the engine around every execution) ties the child to the step anyway."""

    def engine(self, argv, returned):
        store = RunStore(os.path.join(self.scratch, "store"), fsync=False)
        events = []

        class Work(WorkflowStep):
            def execute(self, inputs, context):
                result = procs.run(argv, timeout=30, grace_seconds=GRACE)
                returned.append((time.monotonic(), result))
                if result.ok:
                    return StepResult.success()
                return StepResult.failed(f"child {result.status}", retryable=False)

        registry = StepRegistry()
        registry.register("work", Work)
        engine = WorkflowEngine(parse_definition(load(ONE_STEP), "<test>"), registry, store,
                                run_id_factory=lambda _: "run-1",
                                subscribers=[events.append])
        engine.PROGRESS_SAVE_SECONDS = 0.0  # save and emit every heartbeat in this test
        return engine, store, events

    def drive(self, engine):
        box = {}

        def target():
            try:
                box["state"] = engine.start()
            except BaseException as exc:  # pragma: no cover - surfaced below
                box["error"] = exc

        thread = threading.Thread(target=target, daemon=True)
        thread.start()
        return thread, box

    def test_heartbeat_and_liveness_reach_the_step_state(self):
        returned = []
        argv = [sys.executable, "-c", "import time; time.sleep(1.5)"]
        with mock.patch.dict(os.environ, {procs.HEARTBEAT_ENV: "0.1"}):
            engine, store, events = self.engine(argv, returned)
            thread, box = self.drive(engine)

            def running_state():
                try:
                    step = store.load("run-1").steps.get("work")
                except Exception:
                    return None
                return step if step is not None and step.pid else None

            live = wait_for(running_state, timeout=5)
            self.assertIsNotNone(live, "the step never recorded its child's pid")
            self.assertTrue(live.last_activity_at)
            self.assertIn(live.last_event, ("spawned", "heartbeat"))
            thread.join(15)
        self.assertNotIn("error", box, box.get("error"))
        self.assertEqual(box["state"].status, RunStatus.COMPLETED)
        progress = [e for e in events if e["event"] == Events.STEP_PROGRESS]
        kinds = [e["data"]["kind"] for e in progress]
        self.assertIn("spawned", kinds)
        self.assertGreaterEqual(kinds.count("heartbeat"), 3, kinds)
        self.assertEqual(kinds[-1], "exited")
        beat = next(e for e in progress if e["data"]["kind"] == "heartbeat")
        self.assertEqual(beat["step_id"], "work")
        self.assertEqual(beat["data"]["pid"], live.pid)
        self.assertIsNone(box["state"].steps["work"].pid)  # nothing running any more

    def test_cancel_from_another_thread_ends_the_tree_and_the_step(self):
        returned = []
        engine, store, events = self.engine(self.tree("sleep"), returned)
        thread, box = self.drive(engine)
        self.assertTrue(wait_for(lambda: {"c", "g"} <= set(roles(self.pidfile))))
        pids = roles(self.pidfile)
        asked = time.monotonic()
        engine.request_cancel("run-1")
        thread.join(15)
        self.assertFalse(thread.is_alive(), "the run did not return after a cancel")
        self.assertNotIn("error", box, box.get("error"))
        self.assertTrue(returned, "the step never returned")
        ended, result = returned[0]
        self.assertTrue(result.cancelled)
        self.assertLess(ended - asked, GRACE + 3, "the step did not return promptly")
        self.assertNoSurvivors(result.tag, [pids["c"], pids["g"]])
        kinds = [e["data"]["kind"] for e in events if e["event"] == Events.STEP_PROGRESS]
        self.assertIn("cancelled", kinds)
        # The engine honours the cancel request once the step returns: no retry, CANCELLED.
        self.assertEqual(box["state"].status, RunStatus.CANCELLED)


# -- live: the template's own toolchain ---------------------------------------------------

def _pinned_template():
    # Only the opt-in live test reads the template; do not clone or install otherwise.
    if os.environ.get("WGF_LIVE_PROCESS_TEST") != "1":
        return ""
    sys.path.insert(0, HERE)
    import pinned_template
    return pinned_template.with_dependencies()[0] or ""


TEMPLATE = _pinned_template()


def _server_pids():
    """Pids of node / browser processes running vite, a preview server or Playwright."""
    found = set()
    if not HAVE_PROC:
        return found
    for name in os.listdir("/proc"):
        if not name.isdigit():
            continue
        argv = (procs._read(os.path.join("/proc", name, "cmdline")) or b"").split(b"\0")
        program = os.path.basename(argv[0]).decode("utf-8", "replace")
        text = b" ".join(argv).decode("utf-8", "replace")
        if (program in ("node", "chrome", "headless_shell") or "chrom" in program) and (
                "vite" in text or "playwright" in text or "preview" in text):
            found.add(int(name))
    return found


def _link_modules(source, target):
    """Mirror one node_modules directory as symlinks. A workspace link (into the checkout,
    outside any node_modules) points at the copy's package instead, so the copy builds its
    own packages; everything else points at the checkout's installed files."""
    os.makedirs(target)
    for name in os.listdir(source):
        here = os.path.join(source, name)
        if name.startswith("@") and os.path.isdir(here) and not os.path.islink(here):
            _link_modules(here, os.path.join(target, name))
            continue
        real = os.path.realpath(here)
        inside = os.path.relpath(real, TEMPLATE)
        if os.path.islink(here) and not inside.startswith("..") and \
                "node_modules" not in inside.split(os.sep):
            os.symlink(os.path.join(_COPY["root"], inside),
                       os.path.join(target, name))
        else:
            os.symlink(here, os.path.join(target, name))


_COPY = {}


def _copy_template(target):
    """The template without its build outputs, node_modules mirrored as symlinks: the smoke
    writes dist/ and test-results/ into the copy, never into the sibling checkout."""
    skip = {"node_modules", ".git", "dist", "test-results", "playwright-report"}

    def ignore(directory, names):
        top = os.path.abspath(directory) == TEMPLATE
        return [n for n in names if n in skip or (top and n in ("build", "release"))]

    shutil.copytree(TEMPLATE, target, ignore=ignore, symlinks=True)
    _COPY["root"] = target
    for here, dirs, _files in os.walk(TEMPLATE):
        if "node_modules" in dirs:
            relative = os.path.relpath(os.path.join(here, "node_modules"), TEMPLATE)
            _link_modules(os.path.join(here, "node_modules"), os.path.join(target, relative))
        dirs[:] = [d for d in dirs if d not in skip]


@unittest.skipUnless(os.environ.get("WGF_LIVE_PROCESS_TEST") == "1",
                     "set WGF_LIVE_PROCESS_TEST=1 to run the template's Playwright smoke")
@unittest.skipUnless(HAVE_PROC, "counts servers through /proc")
class LiveTemplateSmoke(unittest.TestCase):
    game = None

    @classmethod
    def setUpClass(cls):
        if not os.path.isdir(os.path.join(TEMPLATE, "node_modules")):
            raise unittest.SkipTest(f"{TEMPLATE}/node_modules is missing; run pnpm install")
        cls.work = tempfile.mkdtemp(prefix="wgf-live-")
        cls.game = os.path.join(cls.work, "game")
        _copy_template(cls.game)
        cls.env = dict(os.environ, CI="1")
        build = procs.run(["pnpm", "build"], cwd=cls.game, timeout=600, env=cls.env)
        if not build.ok:
            shutil.rmtree(cls.work, ignore_errors=True)
            raise AssertionError(f"pnpm build failed:\n{build.tail(30)}")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.work, ignore_errors=True)

    def test_cancel_while_the_preview_server_is_up_leaves_nothing(self):
        # The case that orphaned a server in a real run: the step ends (here: cancelled)
        # while Playwright's detached webServer is serving.
        before = _server_pids()
        seen = {}

        def server_up():
            new = _server_pids() - before
            if any(b"preview" in (procs._read(f"/proc/{p}/cmdline") or b"") for p in new):
                seen["pids"] = sorted(new)
                return True
            return False

        result = procs.run(["pnpm", "exec", "playwright", "test", "--project", "desktop"],
                           cwd=self.game, timeout=600, env=self.env, grace_seconds=5,
                           should_stop=server_up)
        print(f"\n[live-cancel] status={result.status} rc={result.returncode} "
              f"duration={result.duration_s:.1f}s servers={seen.get('pids')} "
              f"killed={result.killed}", file=sys.stderr)
        self.assertTrue(result.cancelled, result.tail(20))
        self.assertEqual(procs.tagged_pids(result.tag), [])
        for pid in seen["pids"]:
            wait_for(lambda: not procs.pid_alive(pid), 5)
            self.assertFalse(procs.pid_alive(pid), f"server pid {pid} survived")
        clean = wait_for(lambda: not (_server_pids() - before), timeout=5)
        self.assertTrue(clean, f"new vite/playwright processes: {_server_pids() - before}")

    def test_playwright_smoke_leaves_no_server_behind(self):
        game, env = self.game, self.env
        before = _server_pids()
        result = procs.run(["pnpm", "exec", "playwright", "test", "--project", "desktop"],
                           cwd=game, timeout=600, env=env, grace_seconds=5)
        print(f"\n[live] status={result.status} rc={result.returncode} "
              f"duration={result.duration_s:.1f}s killed={result.killed}\n"
              f"{result.tail(15)}", file=sys.stderr)
        self.assertEqual(procs.tagged_pids(result.tag), [])
        clean = wait_for(lambda: not (_server_pids() - before), timeout=5)
        self.assertTrue(clean, f"new vite/playwright processes: {_server_pids() - before}")


class EveryChildGoesThroughProcs(unittest.TestCase):
    """The rule the orphaned Vite server taught: a step module never starts a process
    itself. Only wgflib/procs.py may call subprocess; everything else calls procs.run or
    procs.spawn, which own the tree."""

    FORBIDDEN = ("subprocess.run(", "subprocess.Popen(", "subprocess.call(",
                 "subprocess.check_call(", "subprocess.check_output(", "os.system(",
                 "os.popen(", "os.spawn", "os.exec", "shell=True")

    def test_no_module_outside_procs_starts_a_process(self):
        offenders = []
        for root, dirs, files in os.walk(SCRIPTS):
            dirs[:] = [d for d in dirs if d not in ("tests", "__pycache__")]
            for name in files:
                if not name.endswith(".py"):
                    continue
                path = os.path.join(root, name)
                if os.path.relpath(path, SCRIPTS) == os.path.join("wgflib", "procs.py"):
                    continue
                with open(path, encoding="utf-8") as handle:
                    for number, line in enumerate(handle, 1):
                        code = line.split("#", 1)[0]
                        if any(token in code for token in self.FORBIDDEN):
                            offenders.append(f"{os.path.relpath(path, SCRIPTS)}:{number}: "
                                             f"{line.strip()}")
        self.assertEqual(offenders, [], "start child processes through wgflib.procs")


class SubreaperLeavesOtherChildrenAlone(unittest.TestCase):
    @unittest.skipUnless(sys.platform.startswith("linux"), "PR_SET_CHILD_SUBREAPER is Linux")
    def test_a_child_started_outside_procs_keeps_its_exit_status(self):
        # Reaping it would make its owner's wait() see ECHILD and report 0 - a false success.
        self.assertTrue(procs.install_subreaper())
        self.addCleanup(procs.install_subreaper, False)
        child = subprocess.Popen([sys.executable, "-c",
                                  "import sys, time; time.sleep(1.5); sys.exit(3)"])
        self.assertTrue(procs.run(["true"], timeout=10).ok)
        self.assertEqual(child.wait(timeout=10), 3)


if __name__ == "__main__":
    unittest.main()

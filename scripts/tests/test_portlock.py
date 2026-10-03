"""wgflib.portlock: the machine-wide lock on the template's fixed preview ports.

    python -m unittest scripts/tests/test_portlock.py

Two processes contend for one port (the second waits, then proceeds); a killed holder frees
it; a bounded wait ends in an error naming the holder; nesting and inheritance never
deadlock; wgflib.procs.run takes the lock for exactly the commands that bind a fixed port,
reports the wait as progress and honours cancellation; and every step runner that runs the
template's port-binding scripts reaches it. No test binds a port: the lock is a file in a
temporary directory, and the port number is only its name.
"""

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
sys.path.insert(0, SCRIPTS)

sys.path.insert(0, HERE)

import pinned_template  # noqa: E402
from wgflib import portlock, procs  # noqa: E402
from wgflib import template_contract as contract  # noqa: E402

PORT = 4173

HOLDER = textwrap.dedent("""
    import sys, time
    sys.path.insert(0, {scripts!r})
    from wgflib import portlock
    with portlock.hold({port}, command="holder-under-test", run="run-x", directory={dir!r}):
        print("held", flush=True)
        time.sleep({seconds})
""")


class LockDir(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="wgf-portlock-")
        self.children = []
        env = mock.patch.dict(os.environ, {portlock.LOCK_DIR_ENV: self.dir})
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop(portlock.HELD_ENV, None)

    def tearDown(self):
        for child in self.children:
            if child.poll() is None:
                child.kill()
            child.wait(timeout=10)
            child.stdout.close()

    def start_holder(self, seconds):
        env = dict(os.environ)
        env.pop(portlock.HELD_ENV, None)
        child = subprocess.Popen(
            [sys.executable, "-c", HOLDER.format(scripts=SCRIPTS, port=PORT, dir=self.dir,
                                                 seconds=seconds)],
            stdout=subprocess.PIPE, text=True, env=env)
        self.children.append(child)
        self.assertEqual(child.stdout.readline().strip(), "held")
        return child


class TwoProcesses(LockDir):
    def test_the_second_waits_then_proceeds(self):
        self.start_holder(2)
        reports = []
        began = time.monotonic()
        with portlock.hold(PORT, directory=self.dir, timeout=30, report_seconds=0.2,
                           on_wait=lambda waited, who: reports.append(who)) as waited:
            self.assertGreater(time.monotonic() - began, 1.0)
            self.assertGreater(waited, 1.0)
            self.assertEqual(portlock.holder(PORT, self.dir)["pid"], os.getpid())
        self.assertTrue(reports)
        self.assertEqual(reports[0].get("command"), "holder-under-test")
        self.assertEqual(reports[0].get("run"), "run-x")

    def test_a_killed_holder_frees_the_port(self):
        child = self.start_holder(120)
        child.kill()
        child.wait(timeout=10)
        began = time.monotonic()
        with portlock.hold(PORT, directory=self.dir, timeout=20):
            pass
        self.assertLess(time.monotonic() - began, 10)

    def test_a_bounded_wait_names_the_holder(self):
        child = self.start_holder(120)
        with self.assertRaises(portlock.PortBusy) as caught:
            with portlock.hold(PORT, directory=self.dir, timeout=0.6, poll_seconds=0.1):
                self.fail("acquired a held port")
        message = str(caught.exception)
        self.assertIn(f"pid {child.pid}", message)
        self.assertIn("holder-under-test", message)
        self.assertIn("run run-x", message)
        self.assertIn(portlock.TIMEOUT_ENV, message)

    def test_should_stop_ends_the_wait(self):
        self.start_holder(120)
        with self.assertRaises(portlock.PortWaitCancelled):
            with portlock.hold(PORT, directory=self.dir, timeout=30, poll_seconds=0.05,
                               should_stop=lambda: True):
                self.fail("acquired a held port")


class OneProcess(LockDir):
    def test_nested_holds_in_one_thread_do_not_deadlock(self):
        with portlock.hold(PORT, directory=self.dir, timeout=1):
            with portlock.hold(PORT, directory=self.dir, timeout=1) as waited:
                self.assertEqual(waited, 0.0)
            self.assertEqual(portlock.held_ports(), str(PORT))
        self.assertEqual(portlock.held_ports(), "")

    def test_a_descendant_inherits_the_hold(self):
        with portlock.hold(PORT, directory=self.dir, timeout=5):
            env = procs._child_env(None, "t")
            self.assertEqual(env[portlock.HELD_ENV], str(PORT))
            code = ("import sys; sys.path.insert(0, %r); from wgflib import portlock\n"
                    "with portlock.hold(%d, directory=%r, timeout=0.5): print('ok')"
                    % (SCRIPTS, PORT, self.dir))
            done = subprocess.run([sys.executable, "-c", code], env=env, text=True,
                                  capture_output=True, timeout=30)
            self.assertEqual(done.stdout.strip(), "ok", done.stderr)
        self.assertNotIn(portlock.HELD_ENV, procs._child_env(None, "t"))


class PortsFor(unittest.TestCase):
    def test_the_template_scripts_and_configs_that_bind_a_fixed_port(self):
        cases = {
            ("pnpm", "run", "test:e2e", "--workers=1"): (4173,),
            ("pnpm", "test:e2e"): (4173,),
            ("C:/bin/pnpm.CMD", "run", "test:verify"): (4173,),
            ("npm", "run", "test:e2e", "--", "--reporter=json"): (4173,),
            ("pnpm", "run", "test:sdk:browser"): (4176,),
            ("pnpm", "exec", "playwright", "test", "--project", "desktop"): (4173,),
            ("npx", "playwright", "test", "-c", "playwright.sdk.config.ts"): (4176,),
            ("pnpm", "exec", "playwright", "test", "--config=playwright.config.ts"): (4173,),
            ("pnpm", "run", "test"): (),
            ("pnpm", "run", "build"): (),
            ("pnpm", "exec", "playwright", "test", "-c", "playwright.wgf-play.config.ts"): (),
            ("pnpm", "exec", "playwright", "open", "https://example.test"): (),
            ("git", "status"): (),
            (): (),
        }
        for argv, ports in cases.items():
            with self.subTest(argv=argv):
                self.assertEqual(portlock.ports_for(argv), ports)

    def test_the_pinned_template_still_hardcodes_those_ports(self):
        root, reason = pinned_template.checkout()
        if root is None:
            self.skipTest(reason)
        for config, port in portlock.CONFIG_PORTS.items():
            with open(os.path.join(root, config), encoding="utf-8") as handle:
                self.assertIn(f"const PORT = {port};", handle.read(), config)
        with open(os.path.join(root, contract.PACKAGE_JSON), encoding="utf-8") as handle:
            scripts = json.load(handle)["scripts"]
        for script, config in portlock.SCRIPT_CONFIGS.items():
            uses = scripts[script]
            self.assertIn("playwright test", uses, script)
            if config != contract.PLAYWRIGHT_CONFIG:
                self.assertIn(config, uses, script)


class ProcsRun(LockDir):
    """procs.run holds the lock around exactly the commands that bind a port."""

    def child(self, code):
        return [sys.executable, "-c", code]

    def test_waiting_is_reported_then_the_command_runs(self):
        self.start_holder(2)
        events = []
        done = procs.run(self.child("print('ran')"), ports=(PORT,), heartbeat_seconds=0.2,
                         on_event=lambda kind, **data: events.append((kind, data)))
        self.assertTrue(done.ok, done.tail())
        self.assertIn("ran", done.stdout)
        kinds = [kind for kind, _ in events]
        self.assertIn("port-wait", kinds)
        self.assertIn("port-acquired", kinds)
        self.assertLess(kinds.index("port-acquired"), kinds.index("spawned"))
        wait = next(data for kind, data in events if kind == "port-wait")
        self.assertIn("holder-under-test", wait["holder"])

    def test_a_wait_past_the_bound_is_an_error_naming_the_holder(self):
        child = self.start_holder(120)
        with mock.patch.dict(os.environ, {portlock.TIMEOUT_ENV: "0.5"}):
            done = procs.run(self.child("print('ran')"), ports=(PORT,))
        self.assertFalse(done.ok)
        self.assertEqual(done.status, "not-started")
        self.assertIn(f"pid {child.pid}", done.error)
        self.assertIsInstance(done.exception, portlock.PortBusy)

    def test_cancelling_the_step_ends_the_wait(self):
        self.start_holder(120)
        done = procs.run(self.child("print('ran')"), ports=(PORT,), should_stop=lambda: True)
        self.assertTrue(done.cancelled)
        self.assertEqual(done.stdout, "")

    def test_the_port_is_held_while_the_child_runs_and_inherited_by_it(self):
        code = "import os; print(os.environ.get(%r, ''))" % portlock.HELD_ENV
        done = procs.run(self.child(code), ports=(PORT,))
        self.assertEqual(done.stdout.strip(), str(PORT))
        self.assertEqual(portlock.held_ports(), "")

    def test_ports_default_to_ports_for_and_an_empty_tuple_opts_out(self):
        seen = []

        def fake(argv, *rest):
            seen.append(portlock.held_ports())
            return procs.ProcessResult(argv, returncode=0)

        with mock.patch.object(procs, "_run", fake):
            procs.run(["pnpm", "run", "test:e2e"])
            procs.run(["pnpm", "run", "test:e2e"], ports=())
            procs.run(["pnpm", "run", "lint"])
        self.assertEqual(seen, [str(PORT), "", ""])


class StepsTakeTheLock(LockDir):
    """Every step runner that runs a port-binding template script holds the port for it.

    procs._run is replaced, so nothing is spawned: what is checked is that each runner's
    command reaches procs.run with the port held."""

    def setUp(self):
        super().setUp()
        self.seen = []

        def fake(argv, *rest):
            self.seen.append((tuple(argv), portlock.held_ports()))
            return procs.ProcessResult(argv, returncode=0, stdout="{}")

        patch = mock.patch.object(procs, "_run", fake)
        patch.start()
        self.addCleanup(patch.stop)

    def held_for(self, script):
        return [held for argv, held in self.seen if script in argv]

    def test_develop_smoke_check(self):
        from wgf_develop.checks import TOOLCHAIN
        from wgf_develop.repository import Runner
        argv, _ = TOOLCHAIN["smoke"]
        Runner().run([*argv, "--workers=1"], cwd=self.dir)
        Runner().run(TOOLCHAIN["unit"][0], cwd=self.dir)
        self.assertEqual(self.held_for(contract.SCRIPT_TEST_E2E), [str(PORT)])
        self.assertEqual(self.held_for(contract.SCRIPT_TEST), [""])

    def test_verification_gameplay_and_runtime_facts(self):
        from wgf_verification.runner import CommandRunner
        runner = CommandRunner(env={})
        runner.run(["pnpm", "run", contract.SCRIPT_TEST_E2E, "--reporter=json"], self.dir)
        runner.run(["pnpm", "run", contract.SCRIPT_TEST_VERIFY], self.dir)
        self.assertEqual(self.held_for(contract.SCRIPT_TEST_E2E), [str(PORT)])
        self.assertEqual(self.held_for(contract.SCRIPT_TEST_VERIFY), [str(PORT)])

    def test_sdk_browser_smoke(self):
        from wgf_sdk import evidence
        argv = list(evidence.COMMANDS["browser"])
        procs.run(argv, cwd=self.dir)
        self.assertEqual(self.held_for(contract.SCRIPT_SDK_BROWSER), ["4176"])

    def test_golden_browser_suites(self):
        procs.run(["pnpm", "exec", "playwright", "test", "--project", "desktop", "--project",
                   "mobile"], cwd=self.dir)
        procs.run(["pnpm", "exec", "playwright", "test", "-c", "playwright.golden.config.ts"],
                  cwd=self.dir)
        self.assertEqual([held for _, held in self.seen], [str(PORT), ""])


if __name__ == "__main__":
    unittest.main()

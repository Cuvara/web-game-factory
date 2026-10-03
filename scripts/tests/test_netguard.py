"""wgflib.netguard: the refusing proxy the develop smoke check and the golden runs put in
front of every non-local HTTP(S) request.

Real sockets on 127.0.0.1 only - nothing here leaves the machine. What is pinned: every
request, a plain GET or a CONNECT tunnel, is answered 403 at once (a proxy that does not
answer makes Chromium retry and a portal SDK loader wait out its deadline) and recorded;
the proxy listens on loopback only; and sandbox_env points every proxy variable at it while
keeping localhost direct, so a preview server is still reached.

    python -m unittest scripts/tests/test_netguard.py
"""

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from wgflib import netguard  # noqa: E402
from wgflib.netguard import NO_PROXY, PROXY_VARS, RefusingProxy, sandbox_env  # noqa: E402

TIMEOUT = 5


def exchange(port, request):
    """Send `request` to the proxy and read its whole answer (it closes the connection)."""
    with socket.create_connection(("127.0.0.1", port), timeout=TIMEOUT) as conn:
        conn.sendall(request)
        answer = b""
        while True:
            chunk = conn.recv(4096)
            if not chunk:
                return answer
            answer += chunk


class Proxy(unittest.TestCase):
    def setUp(self):
        self.proxy = RefusingProxy().start()
        self.addCleanup(self.proxy.stop)

    def serving(self):
        """Wait until the accept loop is up. stop() before the thread reaches it closes the
        socket under it (a noisy EBADF in the thread, not a failure); every test that stops
        the proxy lets it serve one request first."""
        exchange(self.proxy.port, b"GET http://ready.example/ HTTP/1.1\r\n\r\n")
        del self.proxy.attempts[:]

    def test_it_listens_on_loopback_only(self):
        self.serving()
        self.assertEqual(self.proxy._server.getsockname()[0], "127.0.0.1")
        self.assertEqual(self.proxy.url, f"http://127.0.0.1:{self.proxy.port}")
        self.assertGreater(self.proxy.port, 0)

    def test_a_plain_get_is_refused_with_403_and_recorded(self):
        answer = exchange(self.proxy.port, b"GET http://sdk.portal.example/sdk.js HTTP/1.1\r\n"
                                           b"Host: sdk.portal.example\r\n\r\n")
        self.assertTrue(answer.startswith(b"HTTP/1.1 403 Forbidden\r\n"), answer)
        self.assertIn(b"Content-Length: 0\r\n", answer)
        self.assertIn(b"Connection: close\r\n", answer)
        self.assertEqual(self.proxy.attempts,
                         ["GET http://sdk.portal.example/sdk.js HTTP/1.1"])

    def test_a_connect_tunnel_is_refused_with_403_and_recorded(self):
        answer = exchange(self.proxy.port, b"CONNECT ads.portal.example:443 HTTP/1.1\r\n"
                                           b"Host: ads.portal.example:443\r\n\r\n")
        self.assertTrue(answer.startswith(b"HTTP/1.1 403 Forbidden\r\n"), answer)
        self.assertEqual(self.proxy.attempts, ["CONNECT ads.portal.example:443 HTTP/1.1"])

    def test_the_summary_counts_every_attempt_and_names_each_target_once(self):
        for _ in range(2):
            exchange(self.proxy.port, b"CONNECT ads.portal.example:443 HTTP/1.1\r\n\r\n")
        exchange(self.proxy.port, b"GET http://cdn.portal.example/a.js HTTP/1.1\r\n\r\n")
        summary = self.proxy.summary()
        self.assertEqual(summary["refused_requests"], 3)
        self.assertEqual(summary["targets"],
                         ["CONNECT ads.portal.example:443",
                          "GET http://cdn.portal.example/a.js"])
        # Since MV-4 the summary also says whether a browser was routed here at all.
        self.assertEqual(summary["enforced"], netguard.enforced())

    def test_a_request_line_split_across_packets_is_read_whole(self):
        with socket.create_connection(("127.0.0.1", self.proxy.port), timeout=TIMEOUT) as conn:
            conn.sendall(b"GET http://split.example/")
            conn.sendall(b"x HTTP/1.1\r\n\r\n")
            self.assertTrue(conn.recv(64).startswith(b"HTTP/1.1 403"))
        self.assertEqual(self.proxy.attempts, ["GET http://split.example/x HTTP/1.1"])

    def test_a_long_request_line_is_recorded_truncated(self):
        target = "http://long.example/" + "a" * 1000
        exchange(self.proxy.port, f"GET {target} HTTP/1.1\r\n\r\n".encode())
        self.assertEqual(len(self.proxy.attempts[0]), 300)

    def test_a_connection_that_sends_nothing_is_not_an_attempt(self):
        socket.create_connection(("127.0.0.1", self.proxy.port), timeout=TIMEOUT).close()
        # A real request afterwards is still answered: one bad client does not stop it.
        exchange(self.proxy.port, b"GET http://after.example/ HTTP/1.1\r\n\r\n")
        self.assertEqual(self.proxy.attempts, ["GET http://after.example/ HTTP/1.1"])

    def test_stop_closes_the_port(self):
        self.serving()
        port = self.proxy.port
        self.proxy.stop()
        self.assertFalse(self.proxy._thread.is_alive())
        with self.assertRaises(OSError):
            socket.create_connection(("127.0.0.1", port), timeout=TIMEOUT).close()


class SandboxEnv(unittest.TestCase):
    def test_every_proxy_variable_points_at_the_proxy_and_localhost_stays_direct(self):
        env = sandbox_env("http://127.0.0.1:9")
        self.assertEqual(set(PROXY_VARS), {"http_proxy", "https_proxy", "HTTP_PROXY",
                                           "HTTPS_PROXY", "all_proxy", "ALL_PROXY"})
        for name in PROXY_VARS:
            self.assertEqual(env[name], "http://127.0.0.1:9", name)
        self.assertEqual(env["no_proxy"], NO_PROXY)
        self.assertEqual(env["NO_PROXY"], NO_PROXY)
        self.assertEqual(NO_PROXY.split(","), ["localhost", "127.0.0.1", "::1"])
        self.assertEqual(set(env), set(PROXY_VARS) | {"no_proxy", "NO_PROXY",
                                                      netguard.BROWSER_PROXY_VAR})

    def test_the_browser_is_given_the_proxy_itself(self):
        """Chromium ignores the variables off Linux; the Factory's own launches and the
        wrapped game config read this one and pass it as Playwright's `proxy`."""
        env = sandbox_env("http://127.0.0.1:9")
        self.assertEqual(env["WGF_BROWSER_PROXY"], "http://127.0.0.1:9")
        self.assertEqual(netguard.BROWSER_BYPASS.split(","), ["localhost", "127.0.0.1", "[::1]"])

    def test_the_module_exports_what_its_users_import(self):
        self.assertEqual(set(netguard.__all__),
                         {"RefusingProxy", "sandbox_env", "enforced", "NO_PROXY",
                          "PROXY_VARS", "BROWSER_PROXY_VAR", "BROWSER_BYPASS",
                          "wraps_game_config", "guarded_playwright_config"})


class Enforcement(unittest.TestCase):
    """A guard that quietly does not guard is worse than none: every summary says whether a
    browser was routed through the proxy at all. Chromium reads the proxy environment on Linux
    and takes the system configuration everywhere else (found by MV-4 on Windows, where the
    develop step's smoke check reached a portal's real CDN with the guard reporting nothing)."""

    def test_enforcement_follows_the_platform(self):
        self.assertEqual(netguard.enforced(), sys.platform.startswith("linux"))

    def test_the_summary_says_whether_it_was_enforced(self):
        proxy = netguard.RefusingProxy().start()
        self.addCleanup(proxy.stop)
        summary = proxy.summary()
        self.assertEqual(summary["enforced"], netguard.enforced())
        self.assertEqual(summary["platform"], sys.platform)
        self.assertEqual(summary["refused_requests"], 0)
        if netguard.enforced():
            self.assertNotIn("not_enforced_reason", summary)
        else:
            self.assertIn("not_enforced_reason", summary)

    def test_a_browser_handed_the_proxy_is_enforced_on_every_platform(self):
        self.assertTrue(netguard.enforced(explicit=True))
        proxy = netguard.RefusingProxy().start()
        self.addCleanup(proxy.stop)
        summary = proxy.summary(explicit=True)
        self.assertTrue(summary["enforced"])
        self.assertNotIn("not_enforced_reason", summary)

    def test_the_game_config_is_wrapped_exactly_where_chromium_ignores_the_variables(self):
        self.assertEqual(netguard.wraps_game_config(), not sys.platform.startswith("linux"))

    def test_zero_refusals_is_not_read_as_isolation_where_it_is_not_enforced(self):
        """The number that matters is not the count: it is whether the count means anything."""
        proxy = netguard.RefusingProxy().start()
        self.addCleanup(proxy.stop)
        summary = proxy.summary()
        self.assertFalse(summary["refused_requests"])
        self.assertIs(summary["enforced"], netguard.enforced())


# A game config in the template's shape: relative testDir per project, a relative outputDir,
# a reporter with a relative folder, a webServer with no cwd. An .mjs here so plain Node can
# import it; Playwright imports the real playwright.config.ts the same way.
GAME_CONFIG = """\
export default {
  outputDir: "test-results/template",
  reporter: [["list"], ["html", { open: "never", outputFolder: "report/html" }]],
  use: { baseURL: "http://localhost:4173", trace: "on-first-retry" },
  projects: [
    { name: "desktop", testDir: "tests/e2e", use: { viewport: { width: 1280, height: 720 } } },
    { name: "verify", testDir: "tests/verify", use: {} },
    { name: "plain" },
  ],
  webServer: { command: "pnpm preview --port 4173 --strictPort", port: 4173,
               reuseExistingServer: false },
};
"""

# Prints the wrapped config as Node resolves it.
PRINT = """\
const { pathToFileURL } = await import("node:url");
const config = (await import(pathToFileURL(process.argv[1]).href)).default;
console.log(JSON.stringify(config));
"""


class GuardedPlaywrightConfig(unittest.TestCase):
    """The wrapper `-c` points a game suite at where Chromium ignores the proxy variables:
    the game config unchanged, the proxy in every `use`, every path absolute."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="wgf-netguard-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.checkout = os.path.join(self.tmp, "game")
        os.makedirs(self.checkout)
        self.config = os.path.join(self.checkout, "playwright.config.mjs")
        with open(self.config, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(GAME_CONFIG)
        self.scratch = os.path.join(self.tmp, "scratch")

    def wrap(self):
        return netguard.guarded_playwright_config(self.checkout, self.scratch,
                                                  "playwright.config.mjs")

    def resolved(self, wrapper, proxy="http://127.0.0.1:9"):
        node = shutil.which("node")
        if not node:
            self.skipTest("node is not installed")
        env = dict(os.environ)
        env.pop(netguard.BROWSER_PROXY_VAR, None)
        if proxy:
            env[netguard.BROWSER_PROXY_VAR] = proxy
        out = subprocess.run([node, "--input-type=module", "-e", PRINT, wrapper],
                             capture_output=True, text=True, env=env, timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr)
        return json.loads(out.stdout)

    def test_it_is_written_outside_the_checkout_and_the_game_config_is_untouched(self):
        with open(self.config, "rb") as handle:
            before = handle.read()
        wrapper = self.wrap()
        self.assertTrue(os.path.isfile(wrapper))
        self.assertEqual(os.path.dirname(wrapper), os.path.abspath(self.scratch))
        self.assertEqual(os.listdir(self.checkout), ["playwright.config.mjs"])
        with open(self.config, "rb") as handle:
            self.assertEqual(handle.read(), before)
        with open(wrapper, encoding="utf-8") as handle:
            text = handle.read()
        self.assertIn("file:///", text)
        self.assertIn("WGF_BROWSER_PROXY", text)

    def test_the_browser_gets_the_proxy_and_every_path_is_absolute(self):
        config = self.resolved(self.wrap())
        root = os.path.abspath(self.checkout)

        def same(path, *parts):
            self.assertEqual(os.path.normcase(os.path.normpath(path)),
                             os.path.normcase(os.path.normpath(os.path.join(root, *parts))))

        proxy = {"server": "http://127.0.0.1:9", "bypass": "localhost,127.0.0.1,[::1]"}
        self.assertEqual(config["use"]["proxy"], proxy)
        self.assertEqual(config["use"]["baseURL"], "http://localhost:4173")   # kept
        for project in config["projects"]:
            self.assertEqual(project["use"]["proxy"], proxy, project["name"])
        self.assertEqual(config["projects"][0]["use"]["viewport"], {"width": 1280, "height": 720})
        same(config["testDir"])
        same(config["outputDir"], "test-results", "template")
        same(config["projects"][0]["testDir"], "tests", "e2e")
        same(config["projects"][1]["testDir"], "tests", "verify")
        self.assertNotIn("testDir", config["projects"][2])    # inherits the absolute top level
        same(config["webServer"]["cwd"])
        self.assertEqual(config["webServer"]["command"], "pnpm preview --port 4173 --strictPort")
        same(config["reporter"][1][1]["outputFolder"], "report", "html")
        self.assertEqual(config["reporter"][0], ["list"])

    def test_without_the_variable_the_config_is_the_games_own(self):
        config = self.resolved(self.wrap(), proxy=None)
        self.assertNotIn("proxy", config["use"])
        self.assertNotIn("proxy", config["projects"][0]["use"])


if __name__ == "__main__":
    unittest.main()

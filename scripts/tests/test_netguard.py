"""wgflib.netguard: the refusing proxy the develop smoke check and the golden runs put in
front of every non-local HTTP(S) request.

Real sockets on 127.0.0.1 only - nothing here leaves the machine. What is pinned: every
request, a plain GET or a CONNECT tunnel, is answered 403 at once (a proxy that does not
answer makes Chromium retry and a portal SDK loader wait out its deadline) and recorded;
the proxy listens on loopback only; and sandbox_env points every proxy variable at it while
keeping localhost direct, so a preview server is still reached.

    python -m unittest scripts/tests/test_netguard.py
"""

import os
import socket
import sys
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
        self.assertEqual(self.proxy.summary(), {
            "refused_requests": 3,
            "targets": ["CONNECT ads.portal.example:443", "GET http://cdn.portal.example/a.js"]})

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
        self.assertEqual(set(env), set(PROXY_VARS) | {"no_proxy", "NO_PROXY"})

    def test_the_module_exports_what_its_users_import(self):
        self.assertEqual(set(netguard.__all__),
                         {"RefusingProxy", "sandbox_env", "NO_PROXY", "PROXY_VARS"})


if __name__ == "__main__":
    unittest.main()

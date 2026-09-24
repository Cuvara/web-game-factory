"""The golden run's network guard: a local proxy that refuses every request, and remembers it.

A build for a portal loads that portal's SDK from its CDN, so every browser test in the
pipeline would fetch it - and a golden run must never contact a portal. The harness points
HTTP(S) proxy variables at this proxy for the whole run (children inherit them; Chromium on
Linux, git and pnpm honour them) with `no_proxy` = localhost, so the preview servers are
still reached directly.

Every request - a plain `GET http://...` or a `CONNECT host:443` tunnel - is answered at
once with `403 Forbidden` and recorded. Answering, rather than pointing the variables at a
closed port, matters: Chromium retries a proxy it cannot connect to, and a portal SDK loader
that waits out its init deadline turns into a 5 s time-to-interactive that fails the
profile's performance assertion - a finding about the harness, not the game. A refusal fails
the script load immediately, which is what an ad blocker or an offline player does.

This is a guard, not a sandbox: a process that ignores proxy variables is not stopped.
"""

import socket
import threading

__all__ = ["RefusingProxy"]


class RefusingProxy:
    def __init__(self):
        self.attempts = []
        self._lock = threading.Lock()
        self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server.bind(("127.0.0.1", 0))
        self._server.listen(64)
        self.port = self._server.getsockname()[1]
        self.url = f"http://127.0.0.1:{self.port}"
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, name="golden-netguard",
                                        daemon=True)

    def start(self):
        self._thread.start()
        return self

    def _serve(self):
        self._server.settimeout(0.2)
        while not self._stop.is_set():
            try:
                conn, _ = self._server.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            threading.Thread(target=self._refuse, args=(conn,), daemon=True).start()

    def _refuse(self, conn):
        try:
            conn.settimeout(5)
            data = b""
            while b"\r\n" not in data and len(data) < 8192:
                chunk = conn.recv(1024)
                if not chunk:
                    break
                data += chunk
            line = data.split(b"\r\n", 1)[0].decode("latin-1", "replace")
            if line:
                with self._lock:
                    self.attempts.append(line[:300])
            conn.sendall(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n"
                         b"Connection: close\r\n\r\n")
        except OSError:
            pass
        finally:
            try:
                conn.close()
            except OSError:
                pass

    def stop(self):
        self._stop.set()
        try:
            self._server.close()
        except OSError:
            pass
        self._thread.join(timeout=2)

    def summary(self):
        """{"attempts": n, "targets": sorted unique request targets}."""
        with self._lock:
            lines = list(self.attempts)
        targets = sorted({" ".join(line.split(" ")[:2]) for line in lines})
        return {"refused_requests": len(lines), "targets": targets}

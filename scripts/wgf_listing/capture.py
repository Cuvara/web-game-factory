"""Running the capture: serve the verified bundle, drive it, read back what was seen.

    BundleServer     a local static server for the bundle directory (plus one scratch
                     directory under /__wgf-listing__/ for the branding page), bound to
                     127.0.0.1 on a free port, with the MIME types a Vite build needs - the
                     Factory's own, so no package manager and no preview server is involved
    run_capture()    the Node capture script (capture.mjs) in the game checkout's directory,
                     through wgflib.procs with the allowlisted game environment and the
                     refusing network proxy (wgflib.netguard), which capture.mjs also hands
                     the browser itself, so it holds on every platform (the listing records
                     whether it did), given one job file; returns capture.json

The checkout is never written to: the script resolves Playwright from the checkout's
node_modules, and every output lands under the run directory.
"""

import http.server
import json
import os
import posixpath
import socket
import threading
import urllib.parse

from wgflib import agentenv, procs
from wgflib.netguard import RefusingProxy, enforced, sandbox_env

__all__ = ["BundleServer", "run_capture", "SCRIPT", "EXTRA_PREFIX", "CaptureFailure"]

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "capture.mjs")
EXTRA_PREFIX = "/__wgf-listing__/"
_NO_BROWSER = ("Executable doesn't exist", "browserType.launch", "playwright install")
MIME = {
    ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8", ".map": "application/json",
    ".wasm": "application/wasm", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".webp": "image/webp", ".gif": "image/gif", ".svg": "image/svg+xml", ".ico": "image/x-icon",
    ".woff": "font/woff", ".woff2": "font/woff2", ".ttf": "font/ttf", ".otf": "font/otf",
    ".mp3": "audio/mpeg", ".ogg": "audio/ogg", ".wav": "audio/wav", ".m4a": "audio/mp4",
    ".webm": "video/webm", ".mp4": "video/mp4", ".glb": "model/gltf-binary",
    ".gltf": "model/gltf+json", ".ktx2": "image/ktx2", ".txt": "text/plain; charset=utf-8",
    ".webmanifest": "application/manifest+json", ".xml": "application/xml",
}


class CaptureFailure(Exception):
    """The capture could not run here (`blocked`: the environment) or broke (`failed`)."""

    def __init__(self, kind, message):
        super().__init__(message)
        self.kind = kind


class _Handler(http.server.BaseHTTPRequestHandler):
    server_version = "wgf-listing/1"
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):  # quiet
        pass

    def do_HEAD(self):
        self._serve(head=True)

    def do_GET(self):
        self._serve()

    def _resolve(self):
        raw = urllib.parse.urlsplit(self.path).path
        decoded = urllib.parse.unquote(raw)
        if decoded.startswith(EXTRA_PREFIX) and self.server.extra_dir:
            root, rel = self.server.extra_dir, decoded[len(EXTRA_PREFIX):]
        else:
            root, rel = self.server.root, decoded.lstrip("/")
        rel = posixpath.normpath("/" + rel).lstrip("/")
        if rel in ("", "."):
            rel = "index.html"
        full = os.path.normpath(os.path.join(root, *rel.split("/")))
        if os.path.commonpath([os.path.abspath(root), os.path.abspath(full)]) != os.path.abspath(root):
            return None
        if os.path.isdir(full):
            full = os.path.join(full, "index.html")
        return full if os.path.isfile(full) else None

    def _serve(self, head=False):
        full = self._resolve()
        if full is None:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        with open(full, "rb") as handle:
            data = handle.read()
        self.send_response(200)
        self.send_header("Content-Type", MIME.get(os.path.splitext(full)[1].lower(),
                                                  "application/octet-stream"))
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        if not head:
            self.wfile.write(data)


class BundleServer:
    """`with BundleServer(dist, extra_dir) as server: server.url` - the bundle at /, the
    scratch directory at /__wgf-listing__/."""

    def __init__(self, root, extra_dir=None):
        self.root = os.path.abspath(root)
        self.extra_dir = os.path.abspath(extra_dir) if extra_dir else None
        self._server = None
        self._thread = None
        self.port = None

    @property
    def url(self):
        return f"http://127.0.0.1:{self.port}"

    def start(self):
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        server.daemon_threads = True
        server.root, server.extra_dir = self.root, self.extra_dir
        self.port = server.server_address[1]
        self._server = server
        self._thread = threading.Thread(target=server.serve_forever, name="wgf-listing-server",
                                        daemon=True)
        self._thread.start()
        return self

    def stop(self):
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()
        return False


def _free_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def run_capture(job, *, checkout, node="node", timeout=900, config=None, hooks=None,
                log_path=None, script=SCRIPT):
    """Write `job` (a dict; `out` is where the script writes) to disk, run the script in
    `checkout`, and return the parsed capture.json. Raises CaptureFailure."""
    out = job["out"]
    os.makedirs(out, exist_ok=True)
    job_path = os.path.join(out, "job.json")
    with open(job_path, "w", encoding="utf-8") as handle:
        json.dump(job, handle, indent=1)
    env = agentenv.scrubbed(agentenv.game_passthrough(config or {}))
    guard = RefusingProxy().start()
    env.update(sandbox_env(guard.url))
    try:
        result = procs.run([node, script, job_path], cwd=checkout, env=env, timeout=timeout,
                           log_path=log_path, stderr_to_stdout=True, **(hooks or {}))
    finally:
        guard.stop()
    report_path = os.path.join(out, "capture.json")
    report = None
    if os.path.isfile(report_path):
        try:
            with open(report_path, encoding="utf-8") as handle:
                report = json.load(handle)
        except (OSError, ValueError):
            report = None
    if result.error is not None:
        raise CaptureFailure("blocked", f"{node} could not be started: {result.error}. The "
                                        "capture needs Node and the game's own Playwright.")
    if report is not None and isinstance(report.get("error"), str):
        raise CaptureFailure("blocked", f"the capture cannot run in {checkout}: {report['error']}")
    output = result.stdout or ""
    if any(marker in (output or "") for marker in _NO_BROWSER):
        raise CaptureFailure("blocked", "no browser to capture the build in here "
                                        "(playwright install chromium)")
    if result.timed_out or result.idle_timed_out:
        raise CaptureFailure("failed", f"the capture {result.status} after {timeout:.0f}s; its "
                                       "process tree was ended")
    if result.cancelled:
        raise CaptureFailure("blocked", "the capture was cancelled")
    if report is None:
        raise CaptureFailure("failed", f"the capture wrote no capture.json (exit "
                                       f"{result.returncode}): {result.tail(8)}")
    # capture.mjs hands the browser the proxy itself when it was given one (`proxied`).
    explicit = report.get("proxied") is True
    report["network_guard"] = "enforced" if enforced(explicit) else "set-not-enforced"
    report["refused_requests"] = (guard.summary(explicit=explicit) if hasattr(guard, "summary")
                                  else None)
    report["exit_code"] = result.returncode
    return report

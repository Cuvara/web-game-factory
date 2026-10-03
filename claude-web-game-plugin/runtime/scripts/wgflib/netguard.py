"""A local HTTP(S) proxy that refuses every request, and remembers it.

A build for a portal loads that portal's SDK from its CDN, so a browser test of a game would
fetch it: real traffic to a portal from a development build, and a result that depends on
the portal's CDN - on a machine with network, web-game-template's own "makes no insecure
requests" smoke fails on a build whose portal SDK pulls an http:// ad bridge. Tests
therefore run with HTTP(S) proxy variables pointing at this proxy (children inherit them;
Chromium on Linux, git and pnpm honour them) and `no_proxy` = localhost, so preview servers
are still reached directly. Used by the develop step's smoke check and by the golden runs.

Every request - a plain `GET http://...` or a `CONNECT host:443` tunnel - is answered at
once with `403 Forbidden` and recorded. Answering, rather than pointing the variables at a
closed port, matters: Chromium retries a proxy it cannot connect to, and a portal SDK loader
that waits out its init deadline turns into a 5 s time-to-interactive that fails the
profile's performance assertion - a finding about the harness, not the game. A refusal fails
the script load immediately, which is what an ad blocker or an offline player does.

This is a guard, not a sandbox: a process that ignores proxy variables is not stopped. Chromium
is one of those processes everywhere but Linux: on Windows and macOS it takes its proxy from the
system configuration and ignores the environment entirely. MV-4 found a develop-step smoke
check on Windows loading a portal's real SDK from its CDN and failing on the http:// ad bridge
it pulled in, with the guard reporting nothing refused.

So the browser is also handed the proxy itself, which Chromium honours on every platform:
  * `sandbox_env` sets `WGF_BROWSER_PROXY` (BROWSER_PROXY_VAR) beside the usual variables, and
    every Playwright launch the Factory writes - the playability bot's config, the store-listing
    capture - passes it as Playwright's `proxy` option, bypassing only loopback;
  * the game's own suites (`test:e2e`, `test:verify`, run on the repository's
    playwright.config.ts) cannot be edited - the config is the template's, a protected path - so
    where Chromium ignores the environment they run with `-c` on a generated wrapper
    (`guarded_playwright_config`): the game's config, imported unchanged, with that `proxy` added
    to its `use` and every relative path made absolute against the checkout. Nothing is written
    to the checkout. On Linux the suites keep running on their own config, under the variables.

`enforced(explicit)` says whether a browser was routed through the proxy, and every summary
carries the answer, because a guard that quietly does not guard is worse than none.
"""

import json
import os
import pathlib
import socket
import sys
import threading

__all__ = ["RefusingProxy", "sandbox_env", "enforced", "NO_PROXY", "PROXY_VARS",
           "BROWSER_PROXY_VAR", "BROWSER_BYPASS", "wraps_game_config",
           "guarded_playwright_config"]


def enforced(explicit=False):
    """Whether a browser started with `sandbox_env` actually routes through the proxy.

    `explicit`: the browser was handed the proxy itself (Playwright's `proxy` launch or `use`
    option, from BROWSER_PROXY_VAR), which Chromium honours on every platform. Otherwise only
    where Chromium reads the proxy environment variables, which is Linux. Elsewhere the
    variables are set and ignored: git and pnpm still honour them, the browser does not."""
    return bool(explicit) or sys.platform.startswith("linux")


def wraps_game_config():
    """Whether a game's own Playwright suite needs `guarded_playwright_config` to be guarded:
    wherever Chromium ignores the proxy environment (everywhere but Linux)."""
    return not sys.platform.startswith("linux")


NOT_ENFORCED_REASON = ("Chromium takes its proxy from the system configuration on this "
                       "platform and ignores the environment, so browser traffic was not "
                       "routed through the refusing proxy: what a browser did or did not "
                       "reach is not established by this summary")

NO_PROXY = "localhost,127.0.0.1,::1"
PROXY_VARS = ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "all_proxy",
              "ALL_PROXY")
# The proxy as the browser itself is given it: Playwright's `proxy: {server, bypass}`.
BROWSER_PROXY_VAR = "WGF_BROWSER_PROXY"
# Chromium's bypass-list syntax: an IPv6 literal is bracketed.
BROWSER_BYPASS = "localhost,127.0.0.1,[::1]"


def sandbox_env(proxy_url):
    """Environment variables that send every non-local HTTP(S) request to `proxy_url`."""
    env = {name: proxy_url for name in PROXY_VARS}
    env.update({"no_proxy": NO_PROXY, "NO_PROXY": NO_PROXY, BROWSER_PROXY_VAR: proxy_url})
    return env


# The wrapper: the game's config, imported unchanged, with the proxy in `use` (top level and
# every project's) and every path Playwright resolves against the config's own directory made
# absolute against the checkout - the wrapper lives outside it.
_WRAPPER = """\
// Generated by the Factory (wgflib.netguard.guarded_playwright_config); not part of any game.
// Runs the game's own Playwright config with the Factory's refusing proxy handed to the
// browser, because Chromium on this platform ignores the proxy environment variables.
import path from "node:path";
import base from {config_url};

const root = {root};
const server = process.env[{var}];
const proxy = server ? {{ server, bypass: {bypass} }} : undefined;
const abs = (p) => (typeof p === "string" ? path.resolve(root, p) : p);
const absAll = (p) => (Array.isArray(p) ? p.map(abs) : abs(p));
const withProxy = (use) => (proxy ? {{ ...(use ?? {{}}), proxy }} : use);
const REPORTER_PATHS = ["outputFolder", "outputFile", "outputDir"];
const reporter = (r) =>
  Array.isArray(r)
    ? r.map((entry) => {{
        if (!Array.isArray(entry) || typeof entry[1] !== "object" || entry[1] === null) return entry;
        const options = {{ ...entry[1] }};
        for (const key of REPORTER_PATHS) if (typeof options[key] === "string") options[key] = abs(options[key]);
        return [entry[0], options];
      }})
    : r;
const webServer = (w) => (w == null ? w : {{ ...w, cwd: abs(w.cwd ?? ".") }});
const project = (p) => ({{
  ...p,
  ...(p.testDir != null ? {{ testDir: abs(p.testDir) }} : {{}}),
  ...(p.outputDir != null ? {{ outputDir: abs(p.outputDir) }} : {{}}),
  ...(p.snapshotDir != null ? {{ snapshotDir: abs(p.snapshotDir) }} : {{}}),
  use: withProxy(p.use),
}});

const config = {{
  ...base,
  testDir: abs(base.testDir ?? "."),
  outputDir: abs(base.outputDir ?? "test-results"),
  use: withProxy(base.use),
}};
if (base.snapshotDir != null) config.snapshotDir = abs(base.snapshotDir);
if (base.globalSetup != null) config.globalSetup = absAll(base.globalSetup);
if (base.globalTeardown != null) config.globalTeardown = absAll(base.globalTeardown);
if (base.tsconfig != null) config.tsconfig = abs(base.tsconfig);
if (base.reporter != null) config.reporter = reporter(base.reporter);
if (base.projects != null) config.projects = base.projects.map(project);
if (base.webServer != null)
  config.webServer = Array.isArray(base.webServer) ? base.webServer.map(webServer) : webServer(base.webServer);

export default config;
"""


def guarded_playwright_config(checkout, directory, config="playwright.config.ts"):
    """Write the wrapper for `<checkout>/<config>` into `directory` (outside the checkout)
    and return its path, for `playwright test -c <path>`. The game's config is read, never
    written; the wrapper hands the browser BROWSER_PROXY_VAR's proxy when it is set."""
    root = os.path.abspath(checkout)
    target = os.path.join(root, config)
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(os.path.abspath(directory), "wgf-guarded.playwright.config.mjs")
    text = _WRAPPER.format(config_url=json.dumps(pathlib.Path(target).as_uri()),
                           root=json.dumps(root.replace(os.sep, "/")),
                           var=json.dumps(BROWSER_PROXY_VAR),
                           bypass=json.dumps(BROWSER_BYPASS))
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    return path


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
        self._thread = threading.Thread(target=self._serve, name="wgf-netguard",
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

    def summary(self, explicit=False):
        """What the proxy refused, and whether a browser was routed through it at all.

        `enforced` is the second half on purpose: zero refused requests means "nothing tried"
        where the guard holds, and "nothing was routed here" where it does not. `explicit`:
        the browser was handed the proxy itself (see `enforced`)."""
        with self._lock:
            lines = list(self.attempts)
        targets = sorted({" ".join(line.split(" ")[:2]) for line in lines})
        result = {"refused_requests": len(lines), "targets": targets,
                  "enforced": enforced(explicit), "platform": sys.platform}
        if not enforced(explicit):
            result["not_enforced_reason"] = NOT_ENFORCED_REASON
        return result

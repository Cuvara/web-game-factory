"""An optional placeholder backend that asks a 2D asset MCP server for images.

Rapid, better-looking placeholders when a 2D asset generator is installed as an MCP server;
nothing at all when it is not. The pipeline never depends on it: when the command is not
configured, not on PATH, fails to start, times out, errors, or returns something that is not
an image, the backend reports why and the next backend (ultimately `procedural`) is used.

Configured in workspace/config/factory.yaml:

    factory:
      assets:
        placeholders:
          backends: [2d-assets-mcp, procedural]
          2d-assets-mcp:
            command: [npx, -y, 2d-assets-mcp]    # how to start the server (stdio)
            tool: generate_sprite                # the tool that returns an image
            arguments: {style: flat}             # merged into every call
            license: CC0-1.0                     # what the server's terms grant, if known
            timeout_seconds: 60

`license` matters: without it the images are recorded as `license_status: unknown`. They are
still usable as placeholders - a placeholder is never production-ready anyway - but nothing
the server made can be promoted to a production asset until someone records its terms.

The client speaks the MCP stdio transport (newline-delimited JSON-RPC 2.0): initialize,
notifications/initialized, tools/call. Standard library only.
"""

import base64
import json
import os
import queue
import shutil
import subprocess
import threading

from wgflib import procs

from .formats import sniff
from .placeholders import BackendError, Generated, GeneratedFile, PlaceholderBackend

__all__ = ["McpClient", "McpError", "McpPlaceholderBackend", "BACKEND_ID"]

BACKEND_ID = "2d-assets-mcp"
PROTOCOL_VERSION = "2025-06-18"
IMAGE_FORMATS = ("png", "webp", "svg")


class McpError(RuntimeError):
    pass


class McpClient:
    """A minimal MCP client over a child process's stdin/stdout."""

    def __init__(self, command, *, timeout=60.0, env=None):
        self.command = list(command)
        self.timeout = float(timeout)
        self.env = env
        self._process = None
        self._lines = queue.Queue()
        self._next_id = 0

    def __enter__(self):
        return self.start() if self._process is None else self

    def __exit__(self, *exc):
        self.close()
        return False

    def start(self):
        # An owned process (wgflib.procs): its own session, tagged, and taken down tree and
        # all by close(), by an exception in start(), or at interpreter exit - an `npx`
        # launcher's node server never outlives the client.
        try:
            self._owned = procs.spawn(
                self.command, env=self.env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, text=True, encoding="utf-8", bufsize=1)
        except (OSError, ValueError) as exc:
            raise McpError(f"could not start {self.command[0]!r}: {exc}")
        self._process = self._owned.process
        self._reader = threading.Thread(target=self._pump, daemon=True)
        self._reader.start()
        try:
            self.request("initialize", {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "wgf-assets", "version": "1"},
            })
            self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        except BaseException:
            self.close()
            raise
        return self

    def _pump(self):
        try:
            for line in self._process.stdout:
                self._lines.put(line)
        except (OSError, ValueError):
            pass
        finally:
            self._lines.put(None)

    def _send(self, message):
        try:
            self._process.stdin.write(json.dumps(message) + "\n")
            self._process.stdin.flush()
        except (OSError, ValueError) as exc:
            raise McpError(f"server closed its input: {exc}")

    def request(self, method, params):
        self._next_id += 1
        request_id = self._next_id
        self._send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        while True:
            try:
                line = self._lines.get(timeout=self.timeout)
            except queue.Empty:
                raise McpError(f"{method}: no response within {self.timeout:g}s")
            if line is None:
                raise McpError(f"{method}: server exited")
            try:
                message = json.loads(line)
            except ValueError:
                continue  # a server that logs to stdout; skip what is not JSON-RPC
            if not isinstance(message, dict) or message.get("id") != request_id:
                continue  # a notification, or a response to something else
            if "error" in message:
                error = message["error"] or {}
                raise McpError(f"{method}: {error.get('message') or error}")
            return message.get("result") or {}

    def call_tool(self, name, arguments):
        result = self.request("tools/call", {"name": name, "arguments": arguments})
        if result.get("isError"):
            text = " ".join(c.get("text", "") for c in result.get("content") or []
                            if isinstance(c, dict))
            raise McpError(f"tool {name!r} failed: {text.strip() or 'no detail'}")
        return result

    def close(self):
        """Close the server's input, give it 5s to exit, then terminate its whole tree."""
        if self._process is None:
            return
        process, self._process = self._process, None
        try:
            self._owned.close(grace_seconds=5.0, close_streams=False)
        finally:
            reader = getattr(self, "_reader", None)
            if reader is not None:
                reader.join(timeout=5)
            try:
                process.stdout.close()
            except (OSError, ValueError):
                pass


def _image_bytes(result):
    """The first image in a tools/call result: an image content block, an embedded resource
    blob, or text that is JSON naming `data_base64` or a readable `path`."""
    for block in result.get("content") or []:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "image" and block.get("data"):
            return base64.b64decode(block["data"])
        resource = block.get("resource") if block.get("type") == "resource" else None
        if isinstance(resource, dict) and resource.get("blob"):
            return base64.b64decode(resource["blob"])
        if block.get("type") == "text":
            try:
                payload = json.loads(block.get("text") or "")
            except ValueError:
                continue
            if isinstance(payload, dict) and payload.get("data_base64"):
                return base64.b64decode(payload["data_base64"])
            if isinstance(payload, dict) and payload.get("path") and os.path.isfile(
                    payload["path"]):
                with open(payload["path"], "rb") as handle:
                    return handle.read()
    structured = result.get("structuredContent")
    if isinstance(structured, dict) and structured.get("data_base64"):
        return base64.b64decode(structured["data_base64"])
    return None


class McpPlaceholderBackend(PlaceholderBackend):
    id = BACKEND_ID
    kinds = {"sprite", "background", "ui", "icon", "vfx", "texture"}

    def __init__(self, settings, client_factory=McpClient):
        self.settings = settings
        self.command = settings.get("command")
        if isinstance(self.command, str):
            self.command = self.command.split()
        self.tool = settings.get("tool")
        self.license = settings.get("license")
        self.extra = dict(settings.get("arguments") or {})
        self.timeout = float(settings.get("timeout_seconds") or 60)
        self._client_factory = client_factory
        self._client = None

    def probe(self):
        if not self.command:
            return False, "not configured (factory.assets.placeholders.2d-assets-mcp.command)"
        if not self.tool:
            return False, "not configured (factory.assets.placeholders.2d-assets-mcp.tool)"
        if shutil.which(self.command[0]) is None and not os.path.isfile(self.command[0]):
            return False, f"{self.command[0]!r} is not on PATH"
        try:
            self._client = self._client_factory(self.command, timeout=self.timeout).start()
        except McpError as exc:
            self._client = None
            return False, str(exc)
        return True, None

    def generate(self, req):
        if self._client is None:
            raise BackendError("not started")
        width, height = req.size()
        arguments = {
            "prompt": f"{req.label or req.id}: flat placeholder {req.kind} for a web game",
            "kind": req.kind,
            "width": width,
            "height": height,
            "format": "png",
            "seed": sum(req.id.encode()),
        }
        arguments.update(self.extra)
        try:
            data = _image_bytes(self._client.call_tool(self.tool, arguments))
        except McpError as exc:
            raise BackendError(str(exc))
        found = sniff(data) if data else None
        if found is None or found.format not in IMAGE_FORMATS:
            raise BackendError("the server returned no PNG, WebP or SVG image")
        return Generated([GeneratedFile(found.format, data)], generator=self.id,
                         license=self.license)

    def close(self):
        if self._client is not None:
            self._client.close()
            self._client = None

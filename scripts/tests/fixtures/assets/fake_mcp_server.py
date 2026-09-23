"""A stand-in 2D asset MCP server for the assets tests: stdio, newline-delimited JSON-RPC.

    python fake_mcp_server.py <mode> [log-file]

    ok        tools/call returns a PNG image content block sized to the request
    resource  the PNG arrives as an embedded resource blob instead
    error     tools/call returns isError
    garbage   tools/call returns an "image" that is not one
    exit      exits before answering initialize

Every tools/call's arguments are appended to the log file, when one is given, so a test can
see what the backend asked for. Standard library only; no network.
"""

import base64
import json
import struct
import sys
import zlib


def png(width, height):
    row = b"\x00" + b"\x20\xa0\x60\xff" * width
    body = zlib.compress(row * height, 9)

    def chunk(kind, data):
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", body) + chunk(b"IEND", b""))


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "ok"
    log = sys.argv[2] if len(sys.argv) > 2 else None
    if mode == "exit":
        return 3
    for line in sys.stdin:
        message = json.loads(line)
        if "id" not in message:
            continue  # notifications/initialized
        method, params = message.get("method"), message.get("params") or {}
        if method == "initialize":
            result = {"protocolVersion": params.get("protocolVersion"),
                      "capabilities": {"tools": {}},
                      "serverInfo": {"name": "fake-2d-assets", "version": "0"}}
        elif method == "tools/call":
            arguments = params.get("arguments") or {}
            if log:
                with open(log, "a", encoding="utf-8") as handle:
                    handle.write(json.dumps({"tool": params.get("name"), **arguments}) + "\n")
            # Chatter a real server might emit: a log line and an unrelated notification.
            print("server log: generating", flush=True)
            print(json.dumps({"jsonrpc": "2.0", "method": "notifications/progress",
                              "params": {"progress": 1}}), flush=True)
            data = base64.b64encode(png(int(arguments.get("width") or 8),
                                        int(arguments.get("height") or 8))).decode()
            if mode == "error":
                result = {"isError": True, "content": [{"type": "text", "text": "quota"}]}
            elif mode == "garbage":
                result = {"content": [{"type": "image", "mimeType": "image/png",
                                       "data": base64.b64encode(b"nope").decode()}]}
            elif mode == "resource":
                result = {"content": [{"type": "resource", "resource": {
                    "uri": "asset://x", "mimeType": "image/png", "blob": data}}]}
            else:
                result = {"content": [{"type": "image", "mimeType": "image/png", "data": data}]}
        else:
            print(json.dumps({"jsonrpc": "2.0", "id": message["id"],
                              "error": {"code": -32601, "message": "no such method"}}),
                  flush=True)
            continue
        print(json.dumps({"jsonrpc": "2.0", "id": message["id"], "result": result}), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

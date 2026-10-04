#!/usr/bin/env python3
"""The fixture portal: a developer console the publish module's tests publish to, so no real
portal is ever contacted by a test. Standard library only; one process, in-memory state.

    python portal.py --port 0            prints `PORT <n>` once listening, serves until killed

Pages (the fixture adapter's selector map, scripts/wgf_publish/adapters/fixture.py):

    GET  /login                    form#login (a person logs in; the automation never does)
    POST /login                    sets the session cookie, redirects to /console
    GET  /console                  #dashboard, a table of drafts: tr.draft[data-id] with the
                                   draft's name in the row
    GET  /console/new              input[name=name], input[type=file], button#upload
    POST /console/upload           creates the draft (status Created); redirects to its page
    GET  /console/draft/<id>       #draft-id, #status, the listing form, button#save, #saved
                                   after a save, button#submit. The listing form has
                                   input[name=title], one textarea[name="short_description[<l>]"]
                                   and textarea[name="description[<l>]"] per locale <l> of
                                   PORTAL_LOCALES (default en,ru), textarea[name=controls],
                                   input[name=tags], input[name=categories]
    POST /console/draft/<id>/save
    POST /console/draft/<id>/submit  status -> "Waiting for moderation"; a second submit of
                                   a submitted draft is refused (409) and counted
    GET  /state.json               the whole state, for a test's assertions

Behaviour is set per run with PORTAL_MODE (comma-separated), so a test can make the portal
misbehave the way a real one does:

    captcha        /console shows #captcha instead of the dashboard
    two-factor     /console shows #two-factor
    expired        every session cookie is rejected: /console redirects to /login
    upload-fail    POST /console/upload answers 500 with #upload-error
    ambiguous      a submitted draft's status reads "Processing" (a word no profile maps)
    slow-upload    the upload answers after PORTAL_DELAY seconds (default 3)
    missing-field  the listing form has no description field for the last locale

The session cookie the storage state must carry: `session=fixture-session-token-0001`.
"""

import argparse
import email.parser
import email.policy
import html
import io
import json
import os
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SESSION = "fixture-session-token-0001"
MODES = set(filter(None, os.environ.get("PORTAL_MODE", "").split(",")))
DELAY = float(os.environ.get("PORTAL_DELAY", "3"))
LOCALES = [l for l in os.environ.get("PORTAL_LOCALES", "en,ru").split(",") if l]

STATE = {"drafts": [], "next_id": 1, "double_submits": 0, "uploads": 0, "logins": 0}
LOCK = threading.Lock()


def page(title, body):
    return (f"<!doctype html><html><head><meta charset='utf-8'><title>{html.escape(title)}"
            f"</title></head><body>{body}</body></html>").encode("utf-8")


def listing_names():
    """The listing form's field names, in page order."""
    names = ["title"]
    for locale in LOCALES:
        names.append(f"short_description[{locale}]")
        if not ("missing-field" in MODES and locale == LOCALES[-1]):
            names.append(f"description[{locale}]")
    return names + ["controls", "tags", "categories"]


def listing_form(draft):
    values = draft.get("listing") or {}
    out = []
    for name in listing_names():
        value = html.escape(values.get(name) or "")
        attr = html.escape(name)
        if name.startswith(("short_description", "description", "controls")):
            out.append(f"<label>{attr}<textarea name=\"{attr}\">{value}</textarea></label>")
        else:
            out.append(f"<label>{attr}<input name=\"{attr}\" value=\"{value}\"></label>")
    return "".join(out)


def draft_by_id(draft_id):
    for draft in STATE["drafts"]:
        if draft["id"] == draft_id:
            return draft
    return None


class Handler(BaseHTTPRequestHandler):
    server_version = "FixturePortal/1.0"

    def log_message(self, *args):  # quiet
        pass

    # -- helpers ---------------------------------------------------------------------------

    def _send(self, code, body, content_type="text/html; charset=utf-8", headers=()):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for name, value in headers:
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def _redirect(self, location, headers=()):
        self.send_response(303)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        for name, value in headers:
            self.send_header(name, value)
        self.end_headers()

    def _session_ok(self):
        if "expired" in MODES:
            return False
        cookie = self.headers.get("Cookie") or ""
        return f"session={SESSION}" in cookie.replace(" ", "")

    def _form(self):
        length = int(self.headers.get("Content-Length") or 0)
        content_type = self.headers.get("Content-Type") or ""
        if content_type.startswith("multipart/form-data"):
            raw = self.rfile.read(length)
            message = email.parser.BytesParser(policy=email.policy.HTTP).parsebytes(
                b"Content-Type: " + content_type.encode("latin-1") + b"\r\n\r\n" + raw)
            out = {}
            for part in message.iter_parts():
                name = part.get_param("name", header="content-disposition")
                if not name:
                    continue
                filename = part.get_filename()
                payload = part.get_payload(decode=True) or b""
                if filename:
                    out[name] = {"filename": filename, "size": len(payload)}
                else:
                    out[name] = payload.decode("utf-8", "replace")
            return out
        raw = self.rfile.read(length).decode("utf-8")
        return {k: v[0] for k, v in urllib.parse.parse_qs(raw).items()}

    # -- routes ----------------------------------------------------------------------------

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path == "/state.json":
            with LOCK:
                body = json.dumps(STATE).encode("utf-8")
            return self._send(200, body, "application/json")
        if path in ("/", "/login"):
            return self._send(200, page("Login", "<h1>Developer portal</h1><form id='login' "
                                                 "method='post' action='/login'><input name='user'>"
                                                 "<input name='password' type='password'>"
                                                 "<button>Log in</button></form>"))
        if not path.startswith("/console"):
            return self._send(404, page("Not found", "<p>no such page</p>"))
        if not self._session_ok():
            return self._redirect("/login")
        if "captcha" in MODES:
            return self._send(200, page("Check", "<div id='captcha'>Are you human?</div>"))
        if "two-factor" in MODES:
            return self._send(200, page("Check", "<form id='two-factor'><input "
                                                 "autocomplete='one-time-code'></form>"))
        if path == "/console":
            with LOCK:
                rows = "".join(
                    f"<tr class='draft' data-id='{html.escape(d['id'])}'><td>{html.escape(d['name'])}"
                    f"</td><td>{html.escape(d['status'])}</td></tr>" for d in STATE["drafts"])
            return self._send(200, page("Console", f"<div id='dashboard'><h1>My games</h1>"
                                                   f"<a href='/console/new'>New</a><table>{rows}"
                                                   f"</table></div>"))
        if path == "/console/new":
            return self._send(200, page("New draft", "<div id='dashboard'><form method='post' "
                                                     "action='/console/upload' enctype='multipart/form-data'>"
                                                     "<input name='name'><input type='file' name='archive'>"
                                                     "<button id='upload' type='submit'>Upload</button>"
                                                     "</form></div>"))
        if path.startswith("/console/draft/"):
            draft_id = path.rsplit("/", 1)[-1]
            with LOCK:
                draft = draft_by_id(draft_id)
            if draft is None:
                return self._send(404, page("Not found", "<p>no such draft</p>"))
            status = draft["status"]
            if "ambiguous" in MODES and draft.get("submitted"):
                status = "Processing"
            saved = "<span id='saved'>Saved</span>" if draft.get("saved") else ""
            return self._send(200, page("Draft", (
                f"<div id='dashboard'><h1>Draft</h1><span id='draft-id'>{html.escape(draft['id'])}</span>"
                f"<p>Status: <span id='status'>{html.escape(status)}</span></p>"
                f"<form method='post' action='/console/draft/{html.escape(draft['id'])}/save'>"
                f"{listing_form(draft)}"
                f"<button id='save' type='submit'>Save</button></form>{saved}"
                f"<form method='post' action='/console/draft/{html.escape(draft['id'])}/submit'>"
                f"<button id='submit' type='submit'>Submit for moderation</button></form></div>")))
        return self._send(404, page("Not found", "<p>no such page</p>"))

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        if path == "/login":
            self._form()
            with LOCK:
                STATE["logins"] += 1
            return self._redirect("/console", [("Set-Cookie", f"session={SESSION}; Path=/")])
        if not self._session_ok():
            return self._redirect("/login")
        if path == "/console/upload":
            form = self._form()
            if "slow-upload" in MODES:
                time.sleep(DELAY)
            if "upload-fail" in MODES:
                return self._send(500, page("Error", "<div id='dashboard'><p id='upload-error'>"
                                                     "Upload failed: storage unavailable</p></div>"))
            archive = form.get("archive") or {}
            with LOCK:
                draft_id = f"d{STATE['next_id']:04d}"
                STATE["next_id"] += 1
                STATE["uploads"] += 1
                STATE["drafts"].append({"id": draft_id, "name": str(form.get("name") or ""),
                                        "status": "Created", "archive": archive.get("filename"),
                                        "size": archive.get("size"), "submitted": False})
            return self._redirect(f"/console/draft/{draft_id}")
        if path.startswith("/console/draft/") and path.endswith("/save"):
            draft_id = path.split("/")[3]
            form = self._form()
            with LOCK:
                draft = draft_by_id(draft_id)
                if draft is None:
                    return self._send(404, page("Not found", "<p>no such draft</p>"))
                draft["listing"] = {name: str(form[name]).replace("\r\n", "\n")
                                    for name in listing_names() if name in form}
                draft["saved"] = True
            return self._redirect(f"/console/draft/{draft_id}")
        if path.startswith("/console/draft/") and path.endswith("/submit"):
            draft_id = path.split("/")[3]
            with LOCK:
                draft = draft_by_id(draft_id)
                if draft is None:
                    return self._send(404, page("Not found", "<p>no such draft</p>"))
                if draft["submitted"]:
                    STATE["double_submits"] += 1
                    return self._send(409, page("Conflict", "<p id='status'>Already submitted</p>"))
                draft["submitted"] = True
                draft["status"] = "Waiting for moderation"
            return self._redirect(f"/console/draft/{draft_id}")
        return self._send(404, page("Not found", "<p>no such page</p>"))


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args(argv)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    sys.stdout.write(f"PORT {server.server_address[1]}\n")
    sys.stdout.flush()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""The fixture portal: a developer console the publish module's tests publish to, so no real
portal is ever contacted by a test. Standard library only; one process, in-memory state.

    python portal.py --port 0            prints `PORT <n>` once listening, serves until killed

It is driven ENTIRELY by a publication-profile flow (scripts/tests/fixtures/publish/
publication/generic-web.yaml): the markup below is what that profile's ladders name.

    GET  /login                    form#login (a person logs in; the automation never does)
    POST /login                    sets the session cookie, redirects to /console
    GET  /console                  #dashboard, the games list: tr.game[data-id] with
                                   td.title and td.status
    GET  /console/new              label "Name" + input[name=name], button "Create game"
    POST /console/create           creates a game (status Draft); redirects to its page - in
                                   mode ids-on-create to /console/game/<id>/created, the one
                                   page that shows the Game ID and App ID the portal issued
    GET  /console/game/<id>        #game-id, #status, the build form (label "Archive", file
                                   input accept=.zip, button "Upload build"), #uploaded once a
                                   build is on the game, the listing form (label "Title";
                                   one "Description (<locale>)" per PORTAL_LOCALES, default
                                   en,ru; media inputs "Icon" accept image/png, "Cover"
                                   accept image/png,image/jpeg, "Screenshots" accept image/png
                                   multiple), button "Save", #saved after a save,
                                   #declared when the declarations are made, button "Submit
                                   for moderation"
    POST /console/game/<id>/upload the build; #upload-error and 500 in mode upload-fail
    POST /console/game/<id>/save   the listing fields and media files
    POST /console/game/<id>/request  status -> "Waiting for moderation"; a second request is
                                   refused (409) and counted
    POST /challenge                the person answers the CAPTCHA or the second factor
    GET  /state.json               the whole state, for a test's assertions

Pages for the read-only console observer (scripts/wgf_publish/observe.py), beside them:

    GET  /console/observe          a listing form of every field kind (prefilled values, a
                                   file input, a select, limits, a pattern), a status table
                                   and badge, and the signed-in account's email
    POST /console/observe/save     counted; the observer must never cause one
    GET  /observe/state.json       {"saves": n, "views": n}

Behaviour is set per run with PORTAL_MODE (comma-separated):

    open            the console needs no login (as if the person had just logged in)
    sso             the login is on another origin (an identity provider): /console redirects
                    to http://localhost:<port>/login, which hands a ticket back to
                    http://127.0.0.1:<port>/sso
    captcha         a CAPTCHA (#captcha) on every console page until a person answers it
    captcha-midflow the CAPTCHA only on a game's pages and /console/new: after login, mid-flow
    two-factor-midflow  a one-time code (#two-factor) asked the same way
    ids-on-create   Y8-style: a Game ID and an App ID are issued on create, shown once
    upload-fail     POST .../upload answers 500 with #upload-error
    undeclared      the declarations (#declared) are not made
    drift-title     the Title field is renamed ("Game name", name=game_name): a reversible
                    intent's ladder matches nothing
    drift-submit    the request button reads "Send to moderation" (#send): the irreversible
                    intent's ladder matches nothing
    drift-save      the save button reads "Save and publish" (#save-publish): draft.save's ladder
                    matches nothing, and the name is deny vocabulary
    overlay         a tour dialog ("Welcome tour") hides the listing form until its "Got it"
                    is clicked; it also holds a "Delete game" button that does nothing
    ambiguous       a requested game's status reads "Processing" (a word no profile maps)
    slow-upload     the upload answers after PORTAL_DELAY seconds (default 3)

PORTAL_SEED is a JSON list of games the account already holds:
[{"id", "title", "status", "build"?}] - a duplicate by title, a pending review, a draft.
"""

import argparse
import email.parser
import email.policy
import html
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

STATE = {"games": [], "next_id": 1, "creates": 0, "uploads": 0, "saves": 0, "requests": 0,
         "double_requests": 0, "logins": 0, "challenges": 0}
for seeded in json.loads(os.environ.get("PORTAL_SEED") or "[]"):
    STATE["games"].append({"id": seeded["id"], "title": seeded["title"],
                           "status": seeded.get("status", "Draft"), "build": seeded.get("build"),
                           "listing": {}, "media": {}, "saved": False,
                           "requested": seeded.get("status") == "Waiting for moderation"})
OBSERVE = {"saves": 0, "views": 0}
OBSERVE_PAGE = (
    "<div id='dashboard'><header>Signed in as <span class='account'>dev.person@example.com"
    "</span></header><h1>Game settings</h1><h2>Listing</h2>"
    "<form method='post' action='/console/observe/save' aria-label='Listing'>"
    "<label for='title'>Game title</label><input id='title' name='title' required "
    "maxlength='60' value='Prefilled Title Value' data-testid='game-title'>"
    "<label for='desc'>Description</label><textarea id='desc' name='description' "
    "minlength='20'>Prefilled description text</textarea>"
    "<label for='cat'>Category</label><select id='cat' name='category'>"
    "<option>Arcade</option><option selected>Puzzle</option><option>Racing</option></select>"
    "<h2>Build</h2><label for='zip'>Game archive</label><input id='zip' type='file' "
    "name='archive' accept='.zip,application/zip'>"
    "<label for='shots'>Screenshots</label><input id='shots' type='file' name='shots' "
    "accept='image/png,image/jpeg' multiple>"
    "<input name='slug' placeholder='my-game' pattern='[a-z0-9-]+' value='prefilled-slug-value'>"
    "<label for='contact'>Support email</label><input id='contact' type='email' "
    "name='contact' value='support.person@example.com'>"
    "<button type='submit' data-testid='save-draft'>Save draft</button></form>"
    "<a href='/console?tab=games&amp;token=abcdef0123456789'>My games</a>"
    "<table><tr><th>Build</th><th>Status</th></tr><tr><td>1.0.0</td><td>In review</td></tr>"
    "</table><span class='status-badge'>Draft</span></div>")
LOCK = threading.Lock()
esc = html.escape


def page(title, body):
    return (f"<!doctype html><html><head><meta charset='utf-8'><title>{esc(title)}"
            f"</title></head><body>{body}</body></html>").encode("utf-8")


def game_by_id(game_id):
    for game in STATE["games"]:
        if game["id"] == game_id:
            return game
    return None


def title_field(game):
    value = esc((game.get("listing") or {}).get("title") or "")
    if "drift-title" in MODES:
        return (f"<label for='game_name'>Game name</label><input id='game_name' name='game_name' "
                f"value=\"{value}\">")
    return f"<label for='title'>Title</label><input id='title' name='title' value=\"{value}\">"


def game_page(game, issued=False):
    gid = esc(game["id"])
    status = game["status"]
    if "ambiguous" in MODES and game.get("requested"):
        status = "Processing"
    listing = game.get("listing") or {}
    parts = [f"<div id='dashboard'><h1>{esc(game['title'])}</h1>",
             f"<p>Game <span id='game-id'>{gid}</span></p>",
             f"<p>Status: <span id='status'>{esc(status)}</span></p>"]
    if issued:
        parts.append(f"<section id='issued'><label for='issued-game-id'>Game ID</label>"
                     f"<input id='issued-game-id' readonly value='{gid}'>"
                     f"<label for='issued-app-id'>App ID</label>"
                     f"<input id='issued-app-id' readonly value='{esc(game.get('app_id') or '')}'>"
                     f"</section>")
    parts.append(f"<form method='post' action='/console/game/{gid}/upload' "
                 f"enctype='multipart/form-data'><label for='archive'>Archive</label>"
                 f"<input id='archive' type='file' name='archive' accept='.zip'>"
                 f"<button id='upload' type='submit'>Upload build</button></form>")
    if game.get("build"):
        parts.append(f"<p id='uploaded'>Build uploaded: {esc(game['build']['filename'])}</p>")
    fields = [title_field(game)]
    for locale in LOCALES:
        value = esc(listing.get(f"description[{locale}]") or "")
        fields.append(f"<label for='description-{locale}'>Description ({locale})</label>"
                      f"<textarea id='description-{locale}' name='description[{locale}]'>"
                      f"{value}</textarea>")
    fields.append("<label for='icon'>Icon</label><input id='icon' type='file' name='icon' "
                  "accept='image/png'>")
    fields.append("<label for='cover'>Cover</label><input id='cover' type='file' name='cover' "
                  "accept='image/png,image/jpeg'>")
    fields.append("<label for='screenshots'>Screenshots</label><input id='screenshots' "
                  "type='file' name='screenshots' accept='image/png' multiple>")
    save, save_id = ("Save and publish", "save-publish") if "drift-save" in MODES else ("Save", "save")
    hidden = " style='display:none'" if "overlay" in MODES else ""
    if "overlay" in MODES:
        parts.append("<div id='tour' role='dialog' aria-label='Welcome tour'><p>Welcome to the "
                     "new console.</p><button type='button' onclick=\"document.getElementById("
                     "'tour').remove();document.getElementById('listing').style.display='block'"
                     "\">Got it</button><button type='button'>Delete game</button></div>")
    parts.append(f"<form id='listing' method='post' action='/console/game/{gid}/save' "
                 f"enctype='multipart/form-data'{hidden}>{''.join(fields)}"
                 f"<button id='{save_id}' type='submit'>{save}</button></form>")
    if game.get("saved"):
        parts.append("<span id='saved'>Saved</span>")
    if "undeclared" in MODES:
        parts.append("<p>Declarations: <label><input type='checkbox' name='own'> I own this "
                     "game</label></p>")
    else:
        parts.append("<span id='declared'>Declarations complete</span>")
    if "drift-submit" in MODES:
        button = "<button id='send' type='submit'>Send to moderation</button>"
    else:
        button = "<button id='submit' type='submit'>Submit for moderation</button>"
    parts.append(f"<form method='post' action='/console/game/{gid}/request'>{button}</form></div>")
    return page(game["title"], "".join(parts))


class Handler(BaseHTTPRequestHandler):
    server_version = "FixturePortal/2.0"

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

    def _cookies(self):
        return (self.headers.get("Cookie") or "").replace(" ", "")

    def _session_ok(self):
        return "open" in MODES or f"session={SESSION}" in self._cookies()

    def _challenge(self, path):
        """The challenge this console page shows before anything else, or None."""
        if "challenge=done" in self._cookies():
            return None
        mid = path.startswith("/console/game/") or path == "/console/new"
        if "captcha" in MODES or ("captcha-midflow" in MODES and mid):
            return page("Check", "<div id='captcha'><p>Are you human?</p><form method='post' "
                                 "action='/challenge'><input type='hidden' name='next' "
                                 f"value='{esc(path)}'><button type='submit'>I am human"
                                 "</button></form></div>")
        if "two-factor-midflow" in MODES and mid:
            return page("Check", "<form id='two-factor' method='post' action='/challenge'>"
                                 "<label for='code'>Code</label><input id='code' name='code' "
                                 "autocomplete='one-time-code'><input type='hidden' name='next' "
                                 f"value='{esc(path)}'><button type='submit'>Verify</button>"
                                 "</form>")
        return None

    def _form(self):
        """{name: str | {"filename", "size"} | [file, ...]} - repeated file fields are lists."""
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
                if filename is not None:
                    item = {"filename": filename, "size": len(payload)}
                    if not filename and not payload:
                        continue  # an empty file input
                    out.setdefault(name, []).append(item)
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
        if path == "/observe/state.json":
            with LOCK:
                body = json.dumps(OBSERVE).encode("utf-8")
            return self._send(200, body, "application/json")
        if path in ("/", "/login"):
            return self._send(200, page("Login", "<h1>Developer portal</h1><form id='login' "
                                                 "method='post' action='/login'><input name='user'>"
                                                 "<input name='password' type='password'>"
                                                 "<button>Log in</button></form>"))
        if not path.startswith("/console") and not (path == "/sso" and "sso" in MODES):
            return self._send(404, page("Not found", "<p>no such page</p>"))
        if path == "/sso" and "sso" in MODES:
            ticket = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).get("ticket")
            if ticket == ["fixture-ticket"]:
                return self._redirect("/console", [("Set-Cookie", f"session={SESSION}; Path=/")])
            return self._send(403, page("Refused", "<p>bad ticket</p>"))
        if not self._session_ok():
            if "sso" in MODES:
                return self._redirect(f"http://localhost:{self.server.server_address[1]}/login")
            return self._redirect("/login")
        challenge = self._challenge(path)
        if challenge is not None:
            return self._send(200, challenge)
        if path == "/console":
            with LOCK:
                rows = "".join(
                    f"<tr class='game' data-id='{esc(g['id'])}'><td class='title'>{esc(g['title'])}"
                    f"</td><td class='status'>{esc(g['status'])}</td></tr>" for g in STATE["games"])
            return self._send(200, page("Console", f"<div id='dashboard'><h1>My games</h1>"
                                                   f"<a href='/console/new'>New game</a><table>"
                                                   f"<tr><th>Title</th><th>Status</th></tr>{rows}"
                                                   f"</table></div>"))
        if path == "/console/new":
            return self._send(200, page("New game", "<div id='dashboard'><form method='post' "
                                                    "action='/console/create'><label for='name'>"
                                                    "Name</label><input id='name' name='name'>"
                                                    "<button id='create' type='submit'>Create "
                                                    "game</button></form></div>"))
        if path.startswith("/console/game/"):
            parts = path.split("/")
            with LOCK:
                game = game_by_id(parts[3]) if len(parts) > 3 else None
            if game is None:
                return self._send(404, page("Not found", "<p>no such game</p>"))
            issued = len(parts) > 4 and parts[4] == "created" and "ids-on-create" in MODES
            return self._send(200, game_page(game, issued=issued))
        if path == "/console/observe":
            with LOCK:
                OBSERVE["views"] += 1
            return self._send(200, page("Game settings", OBSERVE_PAGE))
        return self._send(404, page("Not found", "<p>no such page</p>"))

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        if path == "/login":
            self._form()
            with LOCK:
                STATE["logins"] += 1
            if "sso" in MODES:
                port = self.server.server_address[1]
                return self._redirect(f"http://127.0.0.1:{port}/sso?ticket=fixture-ticket")
            return self._redirect("/console", [("Set-Cookie", f"session={SESSION}; Path=/")])
        if not self._session_ok():
            return self._redirect("/login")
        if path == "/challenge":
            form = self._form()
            with LOCK:
                STATE["challenges"] += 1
            target = str(form.get("next") or "/console")
            return self._redirect(target if target.startswith("/console") else "/console",
                                  [("Set-Cookie", "challenge=done; Path=/")])
        if path == "/console/create":
            form = self._form()
            with LOCK:
                game_id = f"g{STATE['next_id']:04d}"
                STATE["next_id"] += 1
                STATE["creates"] += 1
                game = {"id": game_id, "title": str(form.get("name") or ""), "status": "Draft",
                        "build": None, "listing": {}, "media": {}, "saved": False,
                        "requested": False}
                if "ids-on-create" in MODES:
                    game["app_id"] = f"app-{STATE['next_id'] + 4000}"
                STATE["games"].append(game)
            suffix = "/created" if "ids-on-create" in MODES else ""
            return self._redirect(f"/console/game/{game_id}{suffix}")
        if path.startswith("/console/game/"):
            parts = path.split("/")
            action = parts[4] if len(parts) > 4 else ""
            with LOCK:
                game = game_by_id(parts[3])
            if game is None:
                return self._send(404, page("Not found", "<p>no such game</p>"))
            gid = game["id"]
            if action == "upload":
                form = self._form()
                if "slow-upload" in MODES:
                    time.sleep(DELAY)
                if "upload-fail" in MODES:
                    return self._send(500, page("Error", "<div id='dashboard'><p id='upload-error'>"
                                                         "Upload failed: storage unavailable</p></div>"))
                archive = (form.get("archive") or [{}])[0]
                with LOCK:
                    STATE["uploads"] += 1
                    game["build"] = {"filename": archive.get("filename"), "size": archive.get("size")}
                return self._redirect(f"/console/game/{gid}")
            if action == "save":
                form = self._form()
                with LOCK:
                    STATE["saves"] += 1
                    game["listing"] = {k: str(v).replace("\r\n", "\n") for k, v in form.items()
                                       if isinstance(v, str)}
                    game["media"] = {k: [f["filename"] for f in v] for k, v in form.items()
                                     if isinstance(v, list)}
                    game["saved"] = True
                return self._redirect(f"/console/game/{gid}")
            if action == "request":
                self._form()
                with LOCK:
                    if game["requested"]:
                        STATE["double_requests"] += 1
                        return self._send(409, page("Conflict", "<p id='status'>Already requested</p>"))
                    STATE["requests"] += 1
                    game["requested"] = True
                    game["status"] = "Waiting for moderation"
                return self._redirect(f"/console/game/{gid}")
        if path == "/console/observe/save":
            self._form()
            with LOCK:
                OBSERVE["saves"] += 1
            return self._redirect("/console/observe")
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

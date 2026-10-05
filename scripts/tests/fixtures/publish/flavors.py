"""Portal flavors of the fixture portal (portal.py, PORTAL_FLAVOR=<id>): one developer console
per publishing target, each laid out as that portal's publication profile
(core/reference/publication/<id>.yaml) describes it - its documented labels and its
hypotheses - and behaving as that portal is documented to behave. A FIXTURE, not the portal:
it is what lets the portal's adapter be FIXTURE_VALIDATED through the real executor; nothing
here was observed on a live console.

The markup a profile does NOT describe (its `unknowns`: the session markers, the games list,
where the status and the game id are shown, how a person's declaration shows as done) is the
same for every flavor, and the test overlays the matching locators on the profile:

    #dashboard                       the logged-in console
    tr.game[data-id] td.title        the games list on /console
    #game-id, #status                a game's id and its status word
    [data-human='<intent id>']       a declaration a person made (absent in mode `undeclared`)
    #upload-error                    an upload the portal refused (mode `upload-fail`)

What each flavor adds (its own profile's flow, and its own behaviour):

    yandex            "Add app" creates a draft (status Created); one "Description and
                      Promotion" tab per locale (role tab named by the locale code); Archive,
                      Icon, Cover, Screenshots, Save; "Submit for moderation" -> Waiting for
                      moderation, refused (409) while one runs and while the account has 2
                      new games waiting; a Published game shows "Create draft" (the live
                      version stays); a Verified game shows "Publish" - counted, a person's
    crazygames        "Submit a game" -> the form (Game name, Create); Game zip (or Game files
                      in mode `files-upload`), Description, Controls, the three covers, Save draft, a QA
                      tool link; "Submit for QA" -> In review; "Request Full Launch" -
                      counted, never the automation's
    y8                no Studio (mode `no-studio`): the console shows "Create your Studio" and
                      no My Games link; "Create Your Game" (Game Name, Create) issues a Game ID
                      and an App ID, shown once; tabs Basic Info and Feedback (the review
                      feedback); Game file, Description, Instructions, Thumbnail, Save;
                      "Submit for Reviews" -> Pending
    gamedistribution  no create: the person made the game (PORTAL_SEED, id = its Game ID);
                      Zip file, Title, Description, Instructions, Thumbnail 512x512, Save; no
                      request button the profile names (the person's: "Request activation")
    gamepix           "Add new game" (Game name, Create); Game file, Description, Icon, Cover,
                      Save; no request button the profile names

POST /test/game {"id", "status"?, "feedback"?, "live"?} sets what the portal (or a person in
it) did meanwhile - a moderation's outcome, a person's own click. Tests only.
"""

import html

esc = html.escape

TABS_JS = ("<script>function wgfTab(group,name){document.querySelectorAll('[data-group='+group"
           "+']').forEach(function(p){p.style.display=p.dataset.name===name?'block':'none';});}"
           "</script>")


def file_input(label, name, accept=None, multiple=False):
    attrs = (f" accept='{accept}'" if accept else "") + (" multiple" if multiple else "")
    return (f"<label for='{name}'>{esc(label)}</label><input id='{name}' type='file' "
            f"name='{name}'{attrs}>")


def text_input(label, name, value="", area=False):
    if area:
        return (f"<label for='{name}'>{esc(label)}</label><textarea id='{name}' name='{name}'>"
                f"{esc(value)}</textarea>")
    return (f"<label for='{name}'>{esc(label)}</label><input id='{name}' name='{name}' "
            f"value=\"{esc(value)}\">")


def tabs(group, names, panels, shown):
    """Tabs a person (and the flow) switches with a click; one panel visible at a time."""
    buttons = "".join(f"<button type='button' role='tab' onclick=\"wgfTab('{group}','{n}')\">"
                      f"{esc(n)}</button>" for n in names)
    body = "".join(f"<div data-group='{group}' data-name='{n}' role='tabpanel' "
                   f"style='display:{'block' if n == shown else 'none'}'>{panels[n]}</div>"
                   for n in names)
    return f"<div role='tablist'>{buttons}</div>{body}"


class Flavor:
    """What every flavor shares: the games list, a game's id, status and declarations."""
    id = None
    HUMAN = ()
    CREATED_STATUS = "Draft"
    SUBMITTED = None
    issues_ids = False

    def __init__(self, state, modes, locales):
        self.state, self.modes, self.locales = state, modes, locales

    # pages
    def list_extra(self):
        return ""

    def list_page(self, games):
        rows = "".join(f"<tr class='game' data-id='{esc(g['id'])}'><td class='title'>"
                       f"{esc(g['title'])}</td><td class='status'>{esc(g['status'])}</td></tr>"
                       for g in games)
        return (f"<div id='dashboard'><h1>Games</h1>{self.list_extra()}<table><tr><th>Title"
                f"</th><th>Status</th></tr>{rows}</table></div>")

    def new_page(self):
        return None

    def head(self, game, issued=False):
        gid = esc(game["id"])
        parts = [f"<h1>{esc(game['title'])}</h1><p>Game <span id='game-id'>{gid}</span></p>",
                 f"<p>Status: <span id='status'>{esc(game['status'])}</span></p>"]
        if issued:
            parts.append(f"<section id='issued'><label for='issued-game-id'>Game ID</label>"
                         f"<input id='issued-game-id' readonly value='{gid}'>"
                         f"<label for='issued-app-id'>App ID</label><input id='issued-app-id' "
                         f"readonly value='{esc(game.get('app_id') or '')}'></section>")
        return "".join(parts)

    def declarations(self):
        if "undeclared" in self.modes:
            return "<p>Declarations: not made</p>"
        return "".join(f"<span data-human='{esc(h)}'>done</span>" for h in self.HUMAN)

    def body(self, game):  # pragma: no cover - per flavor
        raise NotImplementedError

    def game_page(self, game, issued=False):
        return (f"<div id='dashboard'>{TABS_JS}{self.head(game, issued)}{self.body(game)}"
                f"{self.declarations()}</div>")

    def form(self, game, inner, button):
        extra = "<span id='saved'>Saved</span>" if game.get("saved") else ""
        return (f"<form method='post' action='/console/game/{esc(game['id'])}/save' "
                f"enctype='multipart/form-data'>{inner}<button type='submit'>{esc(button)}"
                f"</button></form>{extra}")

    def button(self, game, action, label):
        return (f"<form method='post' action='/console/game/{esc(game['id'])}/{action}'>"
                f"<button type='submit'>{esc(label)}</button></form>")

    # actions
    def save(self, game, form):
        """The submission form: the build (any file field named in BUILD), fields, media."""
        build = None
        for name in self.BUILD:
            files = form.get(name)
            if isinstance(files, list) and files:
                build = {"filename": files[0]["filename"] if len(files) == 1 else None,
                         "files": [f["filename"] for f in files], "field": name}
        if build:
            self.state["uploads"] += 1
            game["build"] = build
        self.state["saves"] += 1
        game["listing"].update({k: str(v).replace("\r\n", "\n") for k, v in form.items()
                                if isinstance(v, str)})
        game["media"].update({k: [f["filename"] for f in v] for k, v in form.items()
                              if isinstance(v, list) and k not in self.BUILD})
        game["saved"] = True
        title = self.saved_title(game)
        if title:
            game["title"] = title

    def saved_title(self, game):
        return None

    def request(self, game):
        """(code, None) or (409, reason): the irreversible request."""
        if game.get("requested") and game["status"] == self.SUBMITTED:
            self.state["double_requests"] += 1
            return 409, "a review is already running"
        self.state["requests"] += 1
        game["requested"] = True
        game["status"] = self.SUBMITTED
        return 303, None

    def other(self, game, action):
        return None


class Yandex(Flavor):
    id = "yandex"
    HUMAN = ("declare.contract", "declare.age_rating", "declare.categories",
             "declare.postpone_publication", "declare.ai_descriptions",
             "declare.developer_comment")
    CREATED_STATUS = "Created"
    SUBMITTED = "Waiting for moderation"
    BUILD = ("archive",)
    LIMIT = 2

    def list_extra(self):
        return ("<form method='post' action='/console/create'><button type='submit'>Add app"
                "</button></form>")

    def create_title(self, form):
        return ""  # the app is named by its per-language Title, saved later

    def body(self, game):
        parts = []
        if game["status"] == "Published" and not game.get("draft"):
            parts.append(self.button(game, "draft", "Create draft"))
            return "".join(parts)
        if game["status"] == "Verified":
            parts.append(self.button(game, "publish", "Publish"))
        listing = game.get("listing") or {}
        panels = {}
        for loc in self.locales:
            panels[loc] = (text_input("Title", f"title[{loc}]", listing.get(f"title[{loc}]", ""))
                           + text_input("Description", f"description[{loc}]",
                                        listing.get(f"description[{loc}]", ""), area=True)
                           + text_input("How to play", f"how_to_play[{loc}]",
                                        listing.get(f"how_to_play[{loc}]", ""), area=True))
        inner = (file_input("Archive", "archive", ".zip")
                 + "<h2>Description and Promotion</h2>"
                 + tabs("lang", self.locales, panels, self.locales[0])
                 + file_input("Icon", "icon", "image/png")
                 + file_input("Cover", "cover", "image/png,image/jpeg")
                 + file_input("Screenshots", "screenshots", "image/png", multiple=True))
        parts.append(self.form(game, inner, "Save"))
        parts.append(self.button(game, "request", "Submit for moderation"))
        return "".join(parts)

    def saved_title(self, game):
        return game["listing"].get(f"title[{self.locales[0]}]")

    def request(self, game):
        if game["status"] == self.SUBMITTED:
            self.state["double_requests"] += 1
            return 409, "one moderation at a time"
        if not game.get("live"):
            waiting = [g for g in self.state["games"] if g is not game and not g.get("live")
                       and g["status"] == self.SUBMITTED]
            if len(waiting) >= self.LIMIT:
                self.state["limit_refusals"] += 1
                return 409, "at most 2 new-game requests per account"
        return super().request(game)

    def other(self, game, action):
        if action == "draft" and game["status"] == "Published":
            self.state["draft_creates"] += 1
            game.update(draft=True, status=self.CREATED_STATUS, requested=False, saved=False)
            return True
        if action == "publish":
            self.state["publish_clicks"] += 1  # a person's click; never the automation's
            game.update(status="Published", live=True)
            return True
        return None


class CrazyGames(Flavor):
    id = "crazygames"
    HUMAN = ("declare.terms", "declare.exclusivity", "declare.warranties", "declare.payout",
             "declare.launch_options")
    SUBMITTED = "In review"
    BUILD = ("zip", "files")

    def list_extra(self):
        return "<a href='/console/new'>Submit a game</a>"

    def new_page(self):
        return ("<div id='dashboard'><form method='post' action='/console/create'>"
                + text_input("Game name", "name") + "<button type='submit'>Create</button>"
                "</form></div>")

    def body(self, game):
        listing = game.get("listing") or {}
        build = (file_input("Game files", "files", multiple=True) if "files-upload" in self.modes
                 else file_input("Game zip", "zip", ".zip"))
        inner = (build + text_input("Description", "description", listing.get("description", ""),
                                    area=True)
                 + text_input("Controls", "controls", listing.get("controls", ""), area=True)
                 + file_input("Landscape cover", "cover", "image/png,image/jpeg")
                 + file_input("Portrait cover", "cover_portrait", "image/png,image/jpeg")
                 + file_input("Square cover", "cover_square", "image/png,image/jpeg"))
        return (self.form(game, inner, "Save draft")
                + f"<a href='/console/game/{esc(game['id'])}/qa'>QA tool</a>"
                + self.button(game, "request", "Submit for QA")
                + self.button(game, "fulllaunch", "Request Full Launch"))

    def other(self, game, action):
        if action == "fulllaunch":
            self.state["full_launch_clicks"] += 1  # CrazyGames' decision; never clicked
            return True
        return None


class Y8(Flavor):
    id = "y8"
    HUMAN = ("declare.studio", "declare.payout")
    SUBMITTED = "Pending"
    BUILD = ("build",)
    issues_ids = True

    def list_page(self, games):
        if "no-studio" in self.modes:
            return ("<div id='dashboard'><h1>Welcome</h1><a href='/console/studio'>Create your "
                    "Studio</a></div>")
        return super().list_page(games)

    def list_extra(self):
        return "<a href='/console'>My Games</a> <a href='/console/new'>Create Your Game</a>"

    def new_page(self):
        return ("<div id='dashboard'><form method='post' action='/console/create'>"
                + text_input("Game Name", "name") + "<button type='submit'>Create</button>"
                "</form></div>")

    def body(self, game):
        listing = game.get("listing") or {}
        basic = (text_input("Description", "description", listing.get("description", ""),
                            area=True)
                 + text_input("Instructions", "instructions", listing.get("instructions", ""),
                              area=True)
                 + file_input("Thumbnail", "thumbnail", "image/png,image/jpeg"))
        feedback = (f"<div role='region' aria-label='Feedback'>"
                    f"{esc(game.get('feedback') or 'No feedback yet')}</div>")
        inner = (file_input("Game file", "build", ".zip")
                 + tabs("game", ["Basic Info", "Feedback"],
                        {"Basic Info": basic, "Feedback": feedback}, "Basic Info"))
        return self.form(game, inner, "Save") + self.button(game, "request", "Submit for Reviews")


class GameDistribution(Flavor):
    id = "gamedistribution"
    HUMAN = ("declare.preroll", "declare.rewarded-flag", "declare.age-group")
    SUBMITTED = "Pending"
    BUILD = ("zip",)

    def body(self, game):
        listing = game.get("listing") or {}
        inner = (file_input("Zip file", "zip", ".zip")
                 + text_input("Title", "title", listing.get("title", game["title"]))
                 + text_input("Description", "description", listing.get("description", ""),
                              area=True)
                 + text_input("Instructions", "instructions", listing.get("instructions", ""),
                              area=True)
                 + file_input("Thumbnail 512x512", "thumb512", "image/png,image/jpeg"))
        return self.form(game, inner, "Save") + self.button(game, "activation",
                                                            "Request activation")

    def other(self, game, action):
        if action == "activation":  # the panel's designated button: a person's click
            return self.request(game)[0] == 303
        return None


class GamePix(Flavor):
    id = "gamepix"
    HUMAN = ("declare.distribution", "declare.child-directed", "declare.ai", "declare.testkit")
    SUBMITTED = "In review"
    BUILD = ("game",)

    def list_extra(self):
        return ("<form method='get' action='/console/new'><button type='submit'>Add new game"
                "</button></form>")

    def new_page(self):
        return ("<div id='dashboard'><form method='post' action='/console/create'>"
                + text_input("Game name", "name") + "<button type='submit'>Create</button>"
                "</form></div>")

    def body(self, game):
        listing = game.get("listing") or {}
        inner = (file_input("Game file", "game", ".zip")
                 + text_input("Description", "description", listing.get("description", ""),
                              area=True)
                 + file_input("Icon", "icon", "image/png")
                 + file_input("Cover", "cover", "image/png,image/jpeg"))
        return self.form(game, inner, "Save")


FLAVORS = {f.id: f for f in (Yandex, CrazyGames, Y8, GameDistribution, GamePix)}

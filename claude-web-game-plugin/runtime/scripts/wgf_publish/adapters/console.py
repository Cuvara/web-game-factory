"""ConsoleAdapter: a portal with no API, driven through its developer console by the
profile-driven intent runner (browser/console.spec.ts, run by wgf_publish.browser).

No selector lives in code. The publication profile (core/reference/publication/<id>.yaml,
2.1.0) holds the console flow as intents; this adapter resolves every value an intent names
from the job - the shipped campaign (wgf_publish.campaign: the listing's copy per locale,
the platform rendition's media files), the package, the game identity - substitutes
`<locale>` in per-locale intents, and hands the runner a flow it executes without deciding anything. The runner's result is mapped here into
the common outcome vocabulary and the interface fields of `Publication`.

The visit:

    session        a person logs in, live, in the headed window (WAITING_FOR_HUMAN_LOGIN,
                   relayed as step progress); a login timeout or a closed window is
                   AUTH_REQUIRED, never a failure
    find_game      recorded id > config ids > idempotency key > exact title; an unrecorded
                   match stops (duplicate-candidate)
    status_gate    a pending review stops (review-pending): nothing uploads over it
    create_game    only when nothing matched; ids the portal issues on create that the build
                   lacks stop before any upload (IDS_ISSUED)
    upload_build .. save_draft
                   live (and the fixture's dry run); a real portal's dry run stops before
                   the first change and says what it would do (DRY_RUN)
    request_review only in a later visit whose job carries `submit_confirmed` (a person's
                   `wgf decide <run> submit`): once, profile locator only
    verify         the status text, mapped through the profile's `status` lists

A live upload visit ends UPLOAD_COMPLETE (WAITING_FOR_HUMAN_SUBMIT_CONFIRMATION): the build
is on the draft, saved, and nothing irreversible happened. Fields only a person may fill
(the profile's `human` intents) are reported, never acted on: HUMAN_REQUIRED (`declaration`
or `legal`) until the page shows them done.

Every action and waiting period is a line of `<run scratch>/actions.jsonl`, scrubbed with
wgflib.redact after the run; its run-relative path is `Publication.actions_log`.

Bounded adaptive mode (wgf_publish/adaptive.py): when the profile says `adaptive: allowed`,
the installation sets `factory.publish.adaptive: true` and a resolver agent is configured,
the flow carries an `adaptive` block and a Responder thread answers the runner's drift
requests while the browser runs. The runner checks every proposal itself before acting. A
visit in which an adaptive action ran is `automation-console-adaptive`; its `drift.json`
(scrubbed, with proposed profile patches) is evidence, and never changes a profile.
"""

import hashlib
import json
import os
import re

from wgflib import publication as pub
from wgflib import redact

from .. import adaptive, campaign, outcomes
from .. import identity as ids
from ..browser import BrowserExecutor
from ..evidence import Evidence, file_sha256, relative_to_run
from .base import Publication, PublicationAdapter, utc_now

__all__ = ["ConsoleAdapter", "DEFAULT_TIMEOUTS", "LOGIN_TIMEOUT_S", "resolve_value",
           "job_campaign"]

DEFAULT_TIMEOUTS = {"action": 5000, "navigation": 60000, "upload": 900000}
LOGIN_TIMEOUT_S = 900
ACTIONS_LOG = "actions.jsonl"
STATE_FILE = "browser-state.json"

# Where a listing field's text is in the shipped listing's localeCopy (wgf_publish.campaign).
TEXT_FIELDS = campaign.TEXT_FIELDS
# Values that are public listing copy: logged as they are. Everything else only by hash.
PUBLIC = re.compile(r"^(listing\.(title|text|tags|categories)|identity\.title)")
LEGAL = re.compile(r"terms|legal|tax|payout|payment|contract|agreement|pricing|identity|bank",
                   re.I)
_HANDOFF_KEYS = ("at", "url", "reason", "kind", "phase", "action", "resume", "resolved_at",
                 "outcome")


def _sha(text):
    return "sha256:" + hashlib.sha256(str(text).encode("utf-8")).hexdigest()


def _text(value):
    if isinstance(value, list):
        value = ", ".join(str(v).strip() for v in value if str(v).strip())
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        value = str(value)
    return value.strip() if isinstance(value, str) and value.strip() else None


def _unique(items):
    out = []
    for item in items:
        if item is not None and str(item) not in out:
            out.append(str(item))
    return out


def _substitute(value, locale):
    """`<locale>` replaced in every string of a ladder, an expect block, a url."""
    if locale is None:
        return value
    if isinstance(value, str):
        return value.replace("<locale>", locale)
    if isinstance(value, list):
        return [_substitute(v, locale) for v in value]
    if isinstance(value, dict):
        return {k: _substitute(v, locale) for k, v in value.items()}
    return value


def job_identity(job):
    """What names the game: the job's `identity` (the step's: registry and config ids), the
    title from the shipped listing or the store metadata, the idempotency key."""
    given = dict(getattr(job, "identity", None) or {})
    title = given.get("title")
    if not title:
        for copy in (job.listing or {}).values():
            title = _text((copy or {}).get("title"))
            if title:
                break
    title = title or _text((job.metadata or {}).get("title"))
    return {
        "title": title,
        "portal_game_id": given.get("portal_game_id") or given.get("registry")
        or given.get("external_game_id"),
        "config_game_id": given.get("config_game_id") or given.get("game_id"),
        "config_app_id": given.get("config_app_id") or given.get("app_id"),
        "key": job.idempotency_key,
    }


def job_campaign(job):
    """The campaign the job's release shipped for its platform (wgf_publish.campaign), read
    once; None when the release shipped no store listing."""
    if not getattr(job, "_campaign_read", False):
        if getattr(job, "campaign", None) is None:
            job.campaign = campaign.load(getattr(job, "release_dir", None),
                                         getattr(job, "platform_id", None))
        job._campaign_read = True
    return getattr(job, "campaign", None)


def resolve_value(path, job, locale=None, primary=None):
    """("text", str) | ("files", [abs path]) | (None, None): the value an intent's path
    names, from the job only. Nothing is invented: a missing value is None. Every
    `listing.` path resolves in the shipped campaign (wgf_publish.campaign): its texts per
    locale, the platform rendition's files before the canonical package's."""
    path = _substitute(path, locale)
    parts = path.split(".")
    root = parts[0]
    if path == "package.file":
        return ("files", [job.package_path]) if job.package_path else (None, None)
    if root == "identity":
        ident = job_identity(job)
        key = {"title": "title", "key": "key", "game_id": "config_game_id",
               "app_id": "config_app_id"}.get(parts[1] if len(parts) > 1 else "", None)
        value = _text(ident.get(key)) if key else None
        return ("text", value) if value else (None, None)
    if root == "manifest" and len(parts) == 3 and parts[1] == "package":
        value = _text((job.package or {}).get(parts[2]))
        return ("text", value) if value else (None, None)
    if root != "listing" or len(parts) < 2:
        return None, None
    kind, value = campaign.resolve(job_campaign(job), path, locale, primary,
                                   texts=job.listing or None)
    if kind == "text":
        return kind, redact.scrub_text(value)
    if kind == "files":
        return kind, value
    if parts[1] == "media":
        return None, None
    metadata = job.metadata or {}
    field = parts[-1]
    if field == "title" and _text(metadata.get("title")):
        return "text", _text(metadata["title"])
    if field in ("description", "long_description"):
        where = parts[2] if parts[1] == "text" and len(parts) == 4 else (primary or locale)
        value = _text((metadata.get("descriptions") or {}).get(where))
        if value:
            return "text", redact.scrub_text(value)
    return None, None


class ConsoleAdapter(PublicationAdapter):
    method = "console"
    # A dry run on a real portal stops before its first change; only the fixture portal's
    # dry run creates and uploads (to a draft nothing ever submits).
    dry_run_uploads = False

    # -- the console -----------------------------------------------------------------------

    def base_url(self, job):
        """The console's base url: the installation's override, else the profile's."""
        return (getattr(job, "console_url", None) or self.settings.get("console_url")
                or (self.submission.get("console") or {}).get("url"))

    def console_url(self, job):
        """Where the visit opens. The base url, unless a subclass knows better."""
        return self.base_url(job)

    def allowed_origins(self, job):
        """The origins the browser may reach: the profile's, plus the console url's own."""
        from urllib.parse import urlsplit
        origins = []
        for url in (list((self.submission.get("console") or {}).get("allowed_origins") or [])
                    + [self.base_url(job), self.console_url(job)]):
            parts = urlsplit(str(url or ""))
            if not parts.scheme or not parts.netloc:
                continue
            origin = f"{parts.scheme}://{parts.netloc}"
            if origin not in origins:
                origins.append(origin)
        return origins

    def timeouts(self, job):
        out = dict(DEFAULT_TIMEOUTS)
        upload_s = (self.submission.get("console") or {}).get("upload_timeout_s")
        if isinstance(upload_s, int):
            out["upload"] = upload_s * 1000
        out.update({k: int(v) for k, v in (job.timeouts or {}).items() if k in out})
        return out

    def login_timeout_s(self, job):
        """factory.publish.login_timeout_s as the step hands it (job.login_timeout_s), else
        the platform's setting, else 900."""
        for value in (getattr(job, "login_timeout_s", None), self.settings.get("login_timeout_s"),
                      (job.timeouts or {}).get("login_s")):
            if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
                return value
        return LOGIN_TIMEOUT_S

    def browser_mode(self, job):
        """(headless, test_human): headed, with a person, for every real portal."""
        return False, None

    # -- the flow ----------------------------------------------------------------------------

    def locales(self, job):
        """Required locales (the platform profile's) first, then every other the listing has."""
        platform = job.platform_profile or {}
        required = _unique(list((platform.get("store_listing") or {}).get("locales") or [])
                           + list((platform.get("metadata_requirements") or {}).get(
                               "descriptions_locales") or [])
                           + list((platform.get("requirements") or {}).get("locales_required")
                                  or []))
        metadata = job.metadata or {}
        found = _unique(required + list(job.listing or {})
                        + list(metadata.get("locales_included") or [])
                        + list(metadata.get("descriptions") or {}))
        return found or ["en"]

    def intents(self, job):
        """(intents, problems, unfilled): the profile's flow with every value resolved and
        every per-locale intent expanded. A non-optional intent whose value the job does not
        hold is a problem (nothing is contacted); an optional one is left out and named."""
        status = self.submission.get("status") or {}
        locales = self.locales(job)
        primary = locales[0]
        out, problems, unfilled = [], [], []
        for intent in self.submission.get("flow") or []:
            targets = locales if intent.get("per_locale") else [None]
            for locale in targets:
                resolved = self._resolve_intent(intent, job, locale, primary, status)
                if isinstance(resolved, str):
                    key = f"{intent.get('id')}:{locale}" if locale else intent.get("id")
                    if intent.get("optional"):
                        unfilled.append(key)
                    else:
                        problems.append(f"intent {key}: {resolved}")
                    continue
                out.append(resolved)
        return out, _unique(problems), unfilled

    def _resolve_intent(self, intent, job, locale, primary, status):
        """The intent as the runner takes it, or a reason (str) it cannot be run."""
        item = {k: _substitute(intent[k], locale) for k in
                ("id", "phase", "class", "action", "target", "url", "note", "optional", "multiple",
                 "names", "page")
                if k in intent}
        item["locale"] = locale
        path = intent.get("value")
        if path:
            kind, value = resolve_value(path, job, locale, primary)
            if kind is None:
                return f"the job holds no {_substitute(path, locale)}"
            if kind == "files":
                missing = [p for p in value if not os.path.isfile(p)]
                if missing:
                    return f"{_substitute(path, locale)} names a file that is not on disk"
                item["files"] = [{"path": os.path.abspath(p).replace(os.sep, "/"),
                                  "name": os.path.basename(p), "sha256": file_sha256(p)}
                                 for p in value]
                item["value_sha256"] = item["files"][0]["sha256"] if len(value) == 1 else \
                    _sha("|".join(f["sha256"] for f in item["files"]))
            else:
                item["value"] = value
                item["value_sha256"] = _sha(value)
                item["value_public"] = bool(PUBLIC.match(path))
        expect = dict(intent.get("expect") or {})
        if expect:
            if "value_equals" in expect:
                kind, value = resolve_value(expect["value_equals"], job, locale, primary)
                if kind != "text":
                    return f"the job holds no {_substitute(expect['value_equals'], locale)} to check"
                expect["value_equals"] = value
            if "status_in" in expect:
                expect["status_in"] = [str(w) for w in status.get(expect["status_in"]) or []]
            if "visible" in expect:
                expect["visible"] = _substitute(expect["visible"], locale)
            item["expect"] = expect
        return item

    def adaptive_settings(self, job):
        """The installation's adaptive settings for this visit (wgf_publish/adaptive.py)."""
        settings = getattr(job, "_adaptive_settings", None)
        if settings is None:
            settings = adaptive.settings_for(job, self.settings)
            job._adaptive_settings = settings
        return settings

    def adaptive_flow(self, job, scratch):
        """The flow's `adaptive` block: enabled only when the profile allows it, the
        installation enabled it and a resolver is configured; the budget the smallest of the
        design's, the profile's and the installation's; the deny vocabulary the shared one
        plus the profile's."""
        settings = self.adaptive_settings(job)
        reasons = []
        if self.submission.get("adaptive") != "allowed":
            reasons.append(f"the publication profile says adaptive: "
                           f"{self.submission.get('adaptive') or 'forbidden'}")
        if not settings.available:
            reasons.append(settings.unavailable_reason())
        limits = adaptive.bounds(self.submission.get("adaptive_bounds"), settings.bounds)

        def where(name):
            return os.path.join(scratch, name).replace(os.sep, "/")
        return {
            "enabled": not reasons,
            "unavailable": "; ".join(reasons) or None,
            "request_path": where(adaptive.REQUEST),
            "response_path": where(adaptive.RESPONSE),
            "drift_path": where(adaptive.DRIFT),
            "response_timeout_ms": int((settings.timeout_s + 30) * 1000),
            **limits,
            "dismissable": [str(n) for n in self.submission.get("dismissable") or []],
            "deny": list(pub.deny_vocabulary(self.profile)),
        }

    def flow(self, job, scratch):
        intents = self.intents(job)[0]
        identity = self.submission.get("identity") or {}
        session = self.submission.get("session") or {}
        status = self.submission.get("status") or {}
        ident = job_identity(job)
        sources = {"registry": ident["portal_game_id"], "config:game_id": ident["config_game_id"],
                   "config:app_id": ident["config_app_id"], "idempotency-key": ident["key"],
                   "title": ident["title"]}
        candidates = [{"source": s, "id": str(sources[s])}
                      for s in identity.get("portal_id_from") or [] if sources.get(s)]
        headless, test_human = self.browser_mode(job)
        # live: the build may be uploaded and the draft saved (job.live; a Job without it
        # says so through submit). track: read the status, change nothing.
        live = bool(getattr(job, "live", job.submit))
        track = bool(getattr(job, "track", False))
        confirmed = bool(live and job.submit and getattr(job, "submit_confirmed", False)
                         and not track)
        # An id the step says the portal has not issued yet is not the build's, whatever the
        # config holds: the visit creates (or finds) the game and stops IDS_ISSUED.
        pending_ids = set(getattr(job, "required_ids", None) or [])
        uploads = [f for i in intents if i.get("phase") == "upload_build" for f in i.get("files") or []]
        return {
            "portal": self.platform_id,
            "step": "submit",
            "console_url": self.console_url(job),
            "allowed_origins": self.allowed_origins(job),
            "out_dir": scratch.replace(os.sep, "/"),
            "actions_log": os.path.join(scratch, ACTIONS_LOG).replace(os.sep, "/"),
            "state_file": os.path.join(scratch, STATE_FILE).replace(os.sep, "/"),
            "headless": bool(headless),
            "test_human": test_human.replace(os.sep, "/") if (headless and test_human) else None,
            "login_timeout_ms": int(self.login_timeout_s(job) * 1000),
            "poll_ms": int(self.settings.get("poll_ms") or 1000),
            "mode": "live" if live and not track else "dry-run",
            "changes_allowed": bool((live or self.dry_run_uploads) and not track),
            "submit_confirmed": confirmed,
            "allow_create": bool(getattr(job, "allow_create", True)) and not track,
            "session": {k: session[k] for k in ("logged_in", "login", "captcha", "two_factor",
                                                "anti_bot", "authenticated_url") if session.get(k)},
            "identity": {**{k: identity[k] for k in ("list_url", "game_url", "row", "row_title",
                                                     "row_id", "page_id") if identity.get(k)},
                         "issued_on_create": [dict(e, read=e.get("read") or []) for e in
                                              ids.issued_entries({"submission": self.submission})],
                         "pending_ids": sorted(pending_ids),
                         "candidates": candidates,
                         "build_ids": {k: str(v) for k, v in (
                             ("external_game_id", ident["config_game_id"]),
                             ("app_id", ident["config_app_id"])) if v and k not in pending_ids},
                         "title": ident["title"]},
            "status": {"read": status.get("read"), "error": status.get("error"),
                       **{k: [str(w) for w in status.get(k) or []] for k in (
                           "states", "submitted_states", "pending_states", "live_states",
                           "approved_states", "rejected_states")}},
            "intents": intents,
            "plan": {"package": job.package.get("filename"),
                     "package_sha256": uploads[0]["sha256"] if uploads else None,
                     "fields": [i["id"] + (f":{i['locale']}" if i.get("locale") else "")
                                for i in intents if i.get("phase") == "fill_metadata"],
                     "media": [f["name"] for i in intents if i.get("phase") == "upload_media"
                               for f in i.get("files") or []]},
            "timeouts": self.timeouts(job),
            "adaptive": self.adaptive_flow(job, scratch),
        }

    # -- the visit ---------------------------------------------------------------------------

    def prepare(self, job):
        problems = []
        if not self.base_url(job):
            problems.append("the publication profile names no console url")
        if not job.package_path or not os.path.isfile(job.package_path):
            problems.append(f"the package {job.package.get('filename')} is not on disk")
        limit = (self.submission.get("constraints") or {}).get("upload_max_mb")
        size = job.package.get("size_mb")
        if limit is not None and isinstance(size, (int, float)) and size > limit:
            problems.append(f"{size} MB exceeds the console's {limit} MB upload limit")
        kind = (self.submission.get("credential") or {}).get("kind")
        if kind not in (None, "human-login", "none"):
            problems.append(f"credential.kind {kind}: a console is reached through a person's "
                            f"live login (human-login); no session is ever loaded")
        if not self.submission.get("flow"):
            problems.append("the publication profile has no console flow")
        problems.extend(self.intents(job)[1])
        return problems

    def publish(self, job):
        problems = self.prepare(job)
        if problems:
            return Publication(outcomes.BLOCKED, f"{self.platform_id}: " + "; ".join(problems),
                               evidence=[Evidence("observation", p, phase="prepare")
                                         for p in problems],
                               measurement_class="automation-check")
        scratch = job.scratch_dir
        os.makedirs(scratch, exist_ok=True)
        log = os.path.join(scratch, ACTIONS_LOG)
        for stale in (log, os.path.join(scratch, adaptive.DRIFT)):
            if os.path.exists(stale):
                os.remove(stale)  # one visit, one log
        flow = self.flow(job, scratch)
        headless, _ = self.browser_mode(job)
        timeouts = flow["timeouts"]
        adapt = flow["adaptive"]
        adaptive_ms = ((adapt["max_per_visit"] + 1) * (adapt["response_timeout_ms"]
                                                       + timeouts["navigation"])
                       if adapt["enabled"] else 0)
        budget = (flow["login_timeout_ms"] * 4 + timeouts["upload"] + timeouts["navigation"] * 40
                  + adaptive_ms) // 1000
        executor = BrowserExecutor(job.checkout, job.release_dir, job.env, job.hooks,
                                   run_process=job.run_process, timeout_s=budget + 120,
                                   headless=headless, on_state=self._relay(job))
        console_log = os.path.join(scratch, "logs", "console.log")
        os.makedirs(os.path.dirname(console_log), exist_ok=True)
        intents, _, unfilled = self.intents(job)
        noted = [Evidence("observation", f"flow for the console: {len(intents)} intent(s); mode "
                                         f"{flow['mode']}"
                                         + ("; submit confirmed by a person" if flow["submit_confirmed"] else "")
                                         + (f"; left out, no value and optional: {', '.join(unfilled)}"
                                            if unfilled else ""),
                          phase="prepare", data={"intents": [i["id"] for i in intents],
                                                 "unfilled": unfilled})]
        if adapt["enabled"]:
            noted.append(Evidence("observation",
                                  f"bounded adaptive mode on: at most {adapt['max_per_intent']} "
                                  f"resolution(s) per intent and {adapt['max_per_visit']} per "
                                  f"visit, every proposal checked by the executor before it acts",
                                  phase="prepare"))
        try:
            if adapt["enabled"]:
                resolver = self.adaptive_settings(job).resolver
                if isinstance(resolver, adaptive.CommandResolver) and not resolver.hooks:
                    resolver.hooks = {k: v for k, v in (job.hooks or {}).items()
                                      if k in ("on_event", "should_stop")}
                with adaptive.Responder(resolver, scratch, logger=job.logger):
                    run = executor.execute(flow, log_path=console_log)
            else:
                run = executor.execute(flow, log_path=console_log)
            publication = self._interpret(job, run, flow)
            publication.evidence[:0] = noted
            return publication
        finally:
            executor.cleanup()

    def _relay(self, job):
        """Each browser state change, as it happens: to the step's progress (`wgf status`
        shows it) and its log. Scrubbed; urls are origin + path already."""
        hooks = job.hooks or {}

        def on_state(state):
            name = str(state.get("state") or "STATE")
            fields = {k: state.get(k) for k in ("portal", "step", "url", "reason", "phase",
                                                "action", "resume", "at", "outcome")
                      if state.get(k) is not None}
            if state.get("kind"):
                # `kind` is the progress callback's own first argument: named apart.
                fields["challenge"] = state["kind"]
            if job.logger is not None:
                try:
                    job.logger.info(f"publish browser: {name}", **fields)
                except Exception:
                    pass
            on_event = hooks.get("on_event")
            if on_event is not None:
                try:
                    on_event(name, **fields)
                except Exception:
                    pass
        return on_state

    # -- mapping the runner's result ---------------------------------------------------------

    def _actions(self, job, scratch):
        """Scrub actions.jsonl in place (wgflib.redact, every line) and return (lines,
        run-relative path) - or ([], None) when the visit wrote none."""
        path = os.path.join(scratch, ACTIONS_LOG)
        if not os.path.isfile(path):
            return [], None
        lines = []
        with open(path, encoding="utf-8") as handle:
            for raw in handle:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    lines.append(redact.scrub(json.loads(raw)))
                except ValueError:
                    continue
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            for line in lines:
                handle.write(json.dumps(line, ensure_ascii=False) + "\n")
        return lines, relative_to_run(path, job.run_dir)

    def _interpret(self, job, run, flow):
        pid = self.platform_id
        evidence = [Evidence.of_process("playwright console run", run.process, phase="run")]
        if run.refused:
            evidence.append(Evidence("observation",
                                     f"{len(run.refused)} request(s) to other origins refused "
                                     f"at the browser", phase="run",
                                     data={"refused": sorted(set(run.refused))[:20]}))
        if run.unavailable:
            return Publication(outcomes.BLOCKED,
                               f"{pid}: no browser to drive the console with here "
                               f"(playwright install chromium)", evidence=evidence,
                               measurement_class="automation-check")
        res = run.result or {}
        lines, actions_log = self._actions(job, flow["out_dir"])
        drift = adaptive.finish_drift(flow["out_dir"], self.profile)
        if drift is not None:
            evidence.append(Evidence.file(
                f"drift.json: {len(drift.get('entries') or [])} adaptive exchange(s) - proposed "
                f"profile changes a person reviews (wgf-publish.py drift-review), never applied",
                os.path.join(flow["out_dir"], adaptive.DRIFT), job.run_dir, phase="run"))
        acted = [l for l in lines if l.get("adaptive") is True and l.get("acted") is True]
        measurement = "automation-console-adaptive" if acted else "automation-console"
        if actions_log:
            evidence.append(Evidence.file(f"actions.jsonl: {len(lines)} action(s) and waiting "
                                          f"period(s)", os.path.join(flow["out_dir"], ACTIONS_LOG),
                                          job.run_dir, phase="run"))
        for line in lines:
            shot = ((line.get("screenshots") or {}).get("post") or {})
            if shot.get("path") and os.path.isfile(shot["path"]):
                evidence.append(Evidence.screenshot(
                    f"{line.get('phase')}: {line.get('intent') or line.get('action')}",
                    shot["path"], job.run_dir, phase=line.get("phase")))
        handoffs = [{k: h.get(k) for k in _HANDOFF_KEYS if k in h}
                    for h in redact.scrub(res.get("login_handoffs") or [])]
        for handoff in handoffs:
            evidence.append(Evidence("observation",
                                     f"waited for a person to log in ({handoff.get('reason')}) at "
                                     f"{handoff.get('url')}: {handoff.get('outcome') or 'open'}",
                                     phase=handoff.get("phase") or "session", data=handoff))
        status_text = res.get("status_text") or res.get("status_before")
        if status_text:
            evidence.append(Evidence.console_text("status text", status_text, phase="verify"))
        found = res.get("found_game")
        game_id = res.get("game_id") or (found or {}).get("id") or None
        common = dict(
            draft_id=game_id, found_existing=bool(found) and (found or {}).get("source") != "title",
            evidence=evidence, found_game=found, created_ids=res.get("created_ids") or {},
            uploaded=bool(res.get("uploaded")), saved=bool(res.get("saved")),
            status_text=status_text, login_handoffs=handoffs, actions_log=actions_log,
            phase_reached=res.get("phase_reached"), measurement_class=measurement)
        if not res:
            tail = run.process.tail(8) if hasattr(run.process, "tail") else ""
            return Publication(outcomes.RETRYABLE_FAILURE,
                               f"{pid}: the console run produced no result "
                               f"({getattr(run.process, 'status', '?')}): {tail}", **common)
        outcome = res.get("outcome")
        stop = res.get("stop") or {}
        code = stop.get("code")
        reason = stop.get("reason") or ""
        where = stop.get("phase") or res.get("phase_reached") or "?"
        waiting = "wgf decide <run-id> done|abandon"

        def human(outcome_, reason_, message, resume=waiting):
            return Publication(outcome_, f"{pid}: {message}", human_reason=reason_,
                               resume_with=resume, **common)

        if outcome in ("login_timeout", "login_abandoned"):
            why = {"captcha": "captcha", "two-factor": "two-factor", "anti-bot": "anti-bot"}.get(
                code, "login")
            return human(outcomes.AUTH_REQUIRED, why,
                         f"{where}: {reason}: nobody logged in in the window the step opened; "
                         f"`wgf resume <run-id>` opens it again for a person to log in",
                         resume="wgf resume <run-id>")
        if outcome == "drift":
            if stop.get("class") == "irreversible":
                proposal = (stop.get("suggestion") or {}).get("proposal") or {}
                hint = (f"; the resolver suggests "
                        f"{json.dumps(redact.scrub(proposal), ensure_ascii=False)} - a "
                        f"suggestion only, never acted on (drift.json)" if proposal else "")
                return human(outcomes.UNKNOWN, "drift-irreversible",
                             f"{where}: drift on the irreversible intent {stop.get('intent')}: "
                             f"{reason}; it is never resolved adaptively - a person corrects the "
                             f"profile or requests review by hand{hint}")
            detail = stop.get("adaptive") or {}
            why = (f"; adaptive mode: {detail.get('reason')}"
                   if detail.get("reason") and not detail.get("used") else "")
            return human(outcomes.UNKNOWN, "ambiguous-portal-state",
                         f"{where}: drift on {stop.get('intent')}: {reason}; the console no "
                         f"longer matches the profile (resolution: {stop.get('resolution')})"
                         f"{why}")
        if outcome == "stopped":
            if code == "dry-run":
                return Publication(outcomes.DRY_RUN, f"{pid}: dry run: {reason}; would upload "
                                   f"{flow['plan'].get('package')} ({flow['plan'].get('package_sha256')}), "
                                   f"fill {len(flow['plan'].get('fields') or [])} field(s), upload "
                                   f"{len(flow['plan'].get('media') or [])} media file(s); nothing "
                                   f"changed on the portal", **common)
            if code == "ids-issued":
                return Publication(outcomes.IDS_ISSUED, f"{pid}: {reason}", **common)
            if code == "portal-error":
                return Publication(outcomes.PLATFORM_ERROR, f"{pid}: {where}: {reason}", **common)
            if code == "invalid-media":
                return Publication(outcomes.INVALID_METADATA, f"{pid}: {where}: {reason}", **common)
            if code in ("manual-create", "manual-upload", "manual-request"):
                return human(outcomes.HUMAN_REQUIRED, "manual-submission", f"{where}: {reason}")
            if code in ("duplicate-candidate", "review-pending"):
                return human(outcomes.UNKNOWN, code, f"{where}: {reason}")
            if code == "action-failed" and not res.get("request_attempted"):
                return Publication(outcomes.RETRYABLE_FAILURE, f"{pid}: {where}: {reason}", **common)
            return human(outcomes.UNKNOWN, "ambiguous-portal-state", f"{where}: {reason}")
        if outcome != "completed":
            if res.get("request_attempted"):
                return human(outcomes.UNKNOWN, "ambiguous-portal-state",
                             f"{where}: the run ended ({reason or outcome}) after the review "
                             f"request was attempted: a person reads the portal")
            return Publication(outcomes.RETRYABLE_FAILURE,
                               f"{pid}: {where}: the console run ended: {reason or outcome}",
                               **common)
        pending = [h for h in res.get("human_fields") or [] if not h.get("done")]
        pending_text = "; ".join(f"{h.get('id')} ({h.get('note') or 'a person does it'}"
                                 + (f", {h['url']}" if h.get("url") else "") + ")"
                                 for h in pending)
        if flow["mode"] != "live":
            return Publication(outcomes.DRY_RUN,
                               f"{pid}: dry run: game {game_id or '(none)'} "
                               f"{'found' if common['found_existing'] else 'prepared'}, build "
                               f"{'uploaded' if res.get('uploaded') else 'not uploaded'}, draft "
                               f"{'saved' if res.get('saved') else 'not saved'}, status "
                               f"{status_text!r}; nothing submitted"
                               + (f"; a person must still: {pending_text}" if pending else ""),
                               **common)
        if pending:
            legal = any(LEGAL.search(f"{h.get('id')} {h.get('note') or ''}") for h in pending)
            return human(outcomes.HUMAN_REQUIRED, "legal" if legal else "declaration",
                         f"a person must complete in the console: {pending_text}; then "
                         f"`wgf decide <run-id> done` (nothing is requested before)")
        verified_state = {"observed": status_text or "(no status text)", "at": utc_now(),
                          "source": "console status text (profile status.read)"}
        if flow["submit_confirmed"]:
            observed = self._classify(status_text or "", self.submission.get("status") or {})
            clicked = bool(res.get("requested"))
            if observed == "rejected":
                return Publication(outcomes.REJECTED,
                                   f"{pid}: the console shows {status_text!r}: rejected; a person "
                                   f"records the compliance finding",
                                   verified_state=verified_state, **common)
            if observed in ("live", "approved"):
                return Publication(outcomes.VERIFIED,
                                   f"{pid}: the console shows {status_text!r} for game {game_id}",
                                   state="live" if observed == "live" else "submitted",
                                   verified_state=verified_state, submitted=clicked, **common)
            if observed == "submitted":
                return Publication(outcomes.SUBMITTED,
                                   f"{pid}: review "
                                   f"{'requested once' if clicked else 'already requested'}; the "
                                   f"console shows {status_text!r} for game {game_id}",
                                   state="submitted", verified_state=verified_state,
                                   submitted=clicked, **common)
            return human(outcomes.UNKNOWN, "ambiguous-portal-state",
                         f"the console shows {status_text!r}, which the publication profile "
                         f"does not map"
                         + (" after the review request" if clicked else "")
                         + "; a person reads the portal before anything else happens")
        no_save = not any(i.get("phase") == "save_draft" for i in flow["intents"])
        if res.get("uploaded") and (res.get("saved") or no_save):
            return Publication(outcomes.UPLOAD_COMPLETE,
                               f"{pid}: the build {flow['plan'].get('package')} is on game "
                               f"{game_id} and the draft is saved (status {status_text!r}); "
                               f"nothing was submitted. A person reads the draft and decides: "
                               f"`wgf decide <run-id> submit|hold|abandon`",
                               human_reason="submit-confirmation",
                               resume_with="wgf decide <run-id> submit|hold|abandon",
                               verified_state=verified_state, **common)
        return human(outcomes.UNKNOWN, "ambiguous-portal-state",
                     f"the visit ended without a saved draft holding the build (uploaded "
                     f"{bool(res.get('uploaded'))}, saved {bool(res.get('saved'))})")

    @staticmethod
    def _classify(status_text, status):
        text = status_text.strip().casefold()
        for kind in ("rejected", "live", "approved", "submitted"):
            for word in status.get(f"{kind}_states") or []:
                if str(word).strip().casefold() == text:
                    return kind
        return None

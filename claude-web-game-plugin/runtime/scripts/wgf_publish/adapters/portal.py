"""PortalAdapter: what the five portal adapters (yandex, crazygames, y8, gamedistribution,
gamepix) share - the hooks, never the behaviour.

Each portal adapter is a ConsoleAdapter (the profile-driven intent runner does every click)
with its own:

    STATUS      the portal's status words (its profile's `status.states`) -> the portal
                registry's status (wgf_publish.registry.STATUSES); a test checks the two
                agree word for word, so a corrected profile shows up as a failing test
    HANDOFFS    each `human` intent of its profile -> (human_required reason, what the
                person does): the portal's own handoff rules
    refuse()    checks of the job before the console is contacted (a prerequisite, an SDK,
                a cooldown, a moderation already running): a Publication, or None
    adjust()    the portal's reading of what the run observed, after the generic mapping:
                status words that mean something only here (Verified, Basic Launch), a
                review's feedback, a rejection's cooldown

Nothing here is a selector or a portal word: those are profile data. The tables live in each
adapter module, one per portal; none is shared (test_publish_portals checks it).

Tests only: `factory.publish.platforms.<id>.test_headless` (with `test_human`) runs the
browser headless with the test's stand-in for the person - and is honoured ONLY when the
console url is the loopback fixture portal. A real portal is always headed, with a person.
"""

import datetime
import json
import os
from urllib.parse import urlsplit

from .. import outcomes
from ..evidence import Evidence
from .base import Publication
from .console import ACTIONS_LOG, ConsoleAdapter

__all__ = ["PortalAdapter", "rejections", "next_allowed", "parse_time", "iso"]

LOOPBACK = ("127.0.0.1", "localhost", "::1")


def iso(moment):
    return moment.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_time(text):
    """A registry timestamp (YYYY-MM-DDTHH:MM:SSZ) as an aware datetime, or None."""
    try:
        return datetime.datetime.strptime(str(text), "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=datetime.timezone.utc)
    except (TypeError, ValueError):
        return None


def _merge(*lists):
    out = []
    for items in lists:
        for item in items or ():
            if item not in out:
                out.append(item)
    return out


def rejections(entry):
    """How many times the registry saw the game go REJECTED."""
    return sum(1 for item in (entry or {}).get("history") or ()
               if item.get("to") == "REJECTED" and item.get("from") != "REJECTED")


def next_allowed(schedule, count, at):
    """When the `count`-th rejection (1-based) lets a new request be made, under `schedule`
    (hours after the 1st, 2nd, ... rejection; the last repeats)."""
    if count < 1 or not schedule:
        return at
    hours = schedule[min(count, len(schedule)) - 1]
    return at + datetime.timedelta(hours=hours)


class PortalAdapter(ConsoleAdapter):
    # Overridden per portal; empty here on purpose so no portal inherits another's.
    STATUS = {}
    HANDOFFS = {}

    # -- tests only --------------------------------------------------------------------------

    def browser_mode(self, job):
        url = self.base_url(job) or ""
        host = urlsplit(str(url)).hostname or ""
        if self.settings.get("test_headless") and host in LOOPBACK:
            return True, self.settings.get("test_human")
        return False, None

    # -- the hooks ---------------------------------------------------------------------------

    def refuse(self, job):  # pragma: no cover - overridden
        return None

    def adjust(self, publication, job, result, flow):
        return publication

    def flow(self, job, scratch):
        flow = super().flow(job, scratch)
        if flow.get("submit_confirmed"):
            # A game the portal shows rejected is never requested again by a confirmed visit:
            # its rejected words count as "already requested" for the runner, so it clicks
            # nothing, and verify reads the rejection back (REJECTED).
            status = flow["status"]
            status["approved_states"] = _merge(status.get("approved_states"),
                                               status.get("rejected_states"))
        return flow

    def publish(self, job):
        refused = self.refuse(job)
        if refused is not None:
            return refused
        return super().publish(job)

    def _interpret(self, job, run, flow):
        publication = super()._interpret(job, run, flow)
        return self.adjust(publication, job, run.result or {}, flow)

    # -- helpers -----------------------------------------------------------------------------

    def registry_status_for(self, status_text):
        """The registry status the portal's own words establish, or None (not mapped)."""
        text = str(status_text or "").strip().casefold()
        for word, status in self.STATUS.items():
            if word.casefold() == text:
                return status
        return None

    def stop(self, outcome, message, *, reason=None, resume=None, phase="prepare", data=None,
             registry=None):
        """A Publication made before (or instead of) contacting the console."""
        return Publication(
            outcome, f"{self.platform_id}: {message}", human_reason=reason,
            resume_with=resume or ("wgf decide <run-id> done|abandon" if reason else None),
            evidence=[Evidence("observation", message, phase=phase, data=data or {})],
            measurement_class="automation-check", registry=registry)

    def handoff_text(self, ids):
        """What the person does, for each pending human intent id, from HANDOFFS."""
        out = []
        for iid in ids:
            reason, what = self.HANDOFFS.get(iid, (None, None))
            if what:
                out.append(f"{iid}: {what}")
        return out

    def read_lines(self, job, publication, intent):
        """The `read` values the runner logged for `intent` in this visit's actions.jsonl."""
        if not publication.actions_log or not job.run_dir:
            return []
        path = os.path.join(job.run_dir, *publication.actions_log.split("/"))
        if not os.path.isfile(path):
            path = os.path.join(job.scratch_dir, ACTIONS_LOG)
        if not os.path.isfile(path):
            return []
        out = []
        with open(path, encoding="utf-8") as handle:
            for raw in handle:
                try:
                    line = json.loads(raw)
                except ValueError:
                    continue
                if line.get("intent") == intent and line.get("read"):
                    out.append(str(line["read"]))
        return out

    def hand_off(self, publication, result, where):
        """A visit that stopped for a person's fields: say what the person does there, from
        HANDOFFS, and the reason - legal when any of them is, else declaration."""
        pending = self.pending_human(result)
        todo = self.handoff_text(pending)
        if todo:
            publication.message += f"; {where}: " + "; ".join(todo)
        reasons = {self.HANDOFFS.get(i, (None, None))[0] for i in pending}
        if "legal" in reasons:
            publication.human_reason = "legal"
        elif "declaration" in reasons:
            publication.human_reason = "declaration"
        return pending

    @staticmethod
    def pending_human(result):
        return [h.get("id") for h in result.get("human_fields") or [] if not h.get("done")]

    def cooldown(self, job, schedule, label):
        """A Publication refusing a confirmed request inside the portal's resubmission
        cooldown (recorded by an earlier visit in the registry entry's other_ids), or None."""
        entry = job.registry_entry or {}
        if job.submit_confirmed and (entry.get("status") or job.registry_status) == "REJECTED":
            # A rejected game is requested again only after a new upload (REJECTED -> DRAFT):
            # the confirmed visit would otherwise click the request over the rejection.
            return self.stop(outcomes.HUMAN_REQUIRED,
                             f"{label} rejected this game and no build was uploaded since: a "
                             f"new upload (and a person's submit) comes before any new "
                             f"request; nothing re-requests a review automatically",
                             reason="platform-rejection")
        until = parse_time((entry.get("other_ids") or {}).get("next_request_after"))
        now = datetime.datetime.now(datetime.timezone.utc)
        if not job.submit_confirmed or until is None or until <= now:
            return None
        return self.stop(outcomes.HUMAN_REQUIRED,
                         f"the last rejection started {label}'s resubmission cooldown: no "
                         f"review is requested before {iso(until)} (rejection "
                         f"{rejections(entry)}); nothing re-requests it automatically - a "
                         f"person decides again after that time",
                         reason="platform-rejection")

    def rejected_registry(self, job, schedule, label):
        """The registry fields a newly observed rejection records: the count and the next
        time a request may be made, under the portal's cooldown schedule."""
        entry = job.registry_entry or {}
        count = rejections(entry) + (0 if (entry.get("status") == "REJECTED") else 1)
        now = datetime.datetime.now(datetime.timezone.utc)
        until = next_allowed(schedule, count, now)
        return {"status": "REJECTED",
                "other_ids": {"rejections": str(count), "next_request_after": iso(until)},
                "note": f"{label}: rejection {count}; the next request no earlier than "
                        f"{iso(until)}; never re-requested automatically"}

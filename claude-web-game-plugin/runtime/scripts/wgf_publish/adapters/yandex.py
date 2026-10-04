"""Yandex Games Console: the profile-driven console adapter with Yandex's own rules.

Every locator, url and status word is data in core/reference/publication/yandex.yaml, each a
documented label or a HYPOTHESIS until a person has observed the console (`wgf-publish.py
observe yandex`); the profile says `status: unverified` and `automation_terms: unverified`,
so the publish step stops HUMAN_REQUIRED before this adapter is reached on a real install.
FIXTURE_VALIDATED only: scripts/tests/test_publish_portals.py runs it through the real
executor against the fixture portal's `yandex` flavor. Nothing here is verified on the live
console.

Status vocabulary (profile `status.states` -> portal registry status):

    Created                  DRAFT           a draft (a new app, or a draft over a live one)
    Waiting for moderation   PENDING_REVIEW  the submitted word; one moderation at a time
    Verified                 VERIFIED        moderation passed with "Postpone publication":
                                             NOT live. Publishing it is a person's
                                             irreversible click - HUMAN_REQUIRED, never a click
    Published                PUBLISHED       live
    Rejected                 REJECTED        the rejection cooldown starts (below)

Review handling:

  * one moderation per game at a time: a game Waiting for moderation is never uploaded over
    (the runner's status_gate, review-pending) and a confirmed visit never requests again;
  * at most `constraints.max_new_game_requests` (2) new-game requests per account: a
    confirmed request for a game never published is refused (review-pending) while the
    portal registries of this project already hold that many new Yandex games waiting.
    UNVERIFIED: requests made outside this Factory are invisible to the count;
  * an update of a live game goes through "Create draft" (`draft.create`, optional: absent
    on a new app); the live version stays up during the review;
  * a rejection starts the cooldown - 24 h, then 2, 4, 8 and 16 days (the profile's
    `constraints.resubmission_cooldown`; COOLDOWN_HOURS below, kept equal by a test). The
    next allowed time is recorded in the registry entry's other_ids.next_request_after; a
    confirmed request before it is refused. Nothing re-requests a review automatically.

Human handoffs (HANDOFFS): the contract (licensing or YAN, payout), the age rating, the
categories and tags, Postpone publication, the AI-descriptions switch and the Developer's
comment are a person's in the console; the per-language "Description and Promotion" tabs are
per-locale intents (`tab.language`, `field.*` with `per_locale`).
"""

import os

from wgflib import paths

from .. import outcomes
from .. import registry as portal_registry
from .portal import PortalAdapter

__all__ = ["YandexAdapter"]


class YandexAdapter(PortalAdapter):
    STATUS = {
        "Created": "DRAFT",
        "Waiting for moderation": "PENDING_REVIEW",
        "Verified": "VERIFIED",
        "Published": "PUBLISHED",
        "Rejected": "REJECTED",
    }
    # Hours after the 1st, 2nd, ... rejection (24 h doubling to 16 days; the last repeats).
    COOLDOWN_HOURS = (24, 48, 96, 192, 384)
    HANDOFFS = {
        "declare.contract": ("legal", "sign the contract (licensing model or YAN) and enter "
                                      "the payout details in the console"),
        "declare.age_rating": ("declaration", "choose the age rating; the developer alone is "
                                              "liable for it (Terms 1.6, REQ 2.7)"),
        "declare.categories": ("declaration", "choose up to 2 categories and up to 20 tags"),
        "declare.postpone_publication": ("declaration", "switch on Postpone publication, so a "
                                                        "passed moderation lands in Verified"),
        "declare.ai_descriptions": ("declaration", "decide the \"I want to enable AI "
                                                   "descriptions\" switch (on by default)"),
        "declare.developer_comment": ("declaration", "write the Developer's comment to "
                                                     "moderators, or leave it empty"),
    }

    # -- the flow ----------------------------------------------------------------------------

    def intents(self, job):
        """The profile's flow, with the per-locale metadata intents run language by language:
        each language's tab (`tab.language`) is opened, then its fields filled, before the
        next language's - the console shows one "Description and Promotion" tab at a time."""
        intents, problems, unfilled = super().intents(job)
        order = self.locales(job)
        slots = [i for i, item in enumerate(intents)
                 if item.get("phase") == "fill_metadata" and item.get("locale")]
        ranked = sorted(slots, key=lambda i: (order.index(intents[i]["locale"])
                                              if intents[i]["locale"] in order else len(order), i))
        reordered = list(intents)
        for slot, source in zip(slots, ranked):
            reordered[slot] = intents[source]
        return reordered, problems, unfilled

    # -- before the console ------------------------------------------------------------------

    def refuse(self, job):
        cooling = self.cooldown(job, self.COOLDOWN_HOURS, "Yandex")
        if cooling is not None:
            return cooling
        limit = (self.submission.get("constraints") or {}).get("max_new_game_requests")
        if not job.submit_confirmed or not limit or self._published_before(job.registry_entry) \
                or job.registry_status == "PENDING_REVIEW":
            return None
        waiting = self.open_new_game_requests(job)
        if len(waiting) >= int(limit):
            return self.stop(outcomes.UNKNOWN,
                             f"{len(waiting)} new game(s) of this account already wait for "
                             f"moderation ({', '.join(waiting)}); Yandex takes at most "
                             f"{limit} new-game requests per account: nothing is requested "
                             f"until one is decided",
                             reason="review-pending", data={"waiting": waiting})
        return None

    @staticmethod
    def _published_before(entry):
        entry = entry or {}
        return entry.get("status") in ("PUBLISHED", "VERIFIED") or any(
            item.get("to") in ("PUBLISHED", "VERIFIED") for item in entry.get("history") or ())

    def open_new_game_requests(self, job):
        """The other Yandex games this project's portal registries record as waiting for
        their first moderation: `<title>:<game id>`."""
        titles = self.settings.get("titles_dir") or paths.TITLES
        own = (job.identity or {}).get("portal_game_id") or (job.registry_entry or {}).get(
            "external_game_id")
        out = []
        try:
            names = sorted(os.listdir(titles))
        except OSError:
            return out
        for title in names:
            try:
                entry = portal_registry.load(title, titles).get(self.platform_id)
            except (portal_registry.RegistryError, OSError, ValueError):
                continue
            if not entry or entry.get("status") != "PENDING_REVIEW" \
                    or self._published_before(entry):
                continue
            if own and entry.get("external_game_id") == own:
                continue
            out.append(f"{title}:{entry.get('external_game_id') or '?'}")
        return out

    # -- after the run -----------------------------------------------------------------------

    def adjust(self, publication, job, result, flow):
        word = publication.status_text
        status = self.registry_status_for(word)
        pid = self.platform_id
        if publication.human_reason == "review-pending":
            publication.message += ("; Yandex runs one moderation per game at a time - "
                                    "nothing is uploaded over it or requested again")
            return publication
        if status == "VERIFIED" and publication.outcome in (
                outcomes.VERIFIED, outcomes.SUBMITTED, outcomes.DRY_RUN, outcomes.UNKNOWN):
            # Passed moderation, held by Postpone publication. Publishing is a person's
            # irreversible click; the visit never makes it.
            publication.outcome = outcomes.HUMAN_REQUIRED
            publication.human_reason = "manual-submission"
            publication.resume_with = "wgf decide <run-id> done --note published (or abandon)"
            publication.state = "submitted"
            publication.registry = {"status": "VERIFIED",
                                    "note": "Verified: moderation passed, publication postponed"}
            publication.message = (f"{pid}: the console shows {word!r}: moderation passed and "
                                   f"publication is postponed. Publish is a person's "
                                   f"irreversible click in the console - nothing here clicks "
                                   f"it; then `wgf decide <run-id> done`")
            return publication
        if publication.outcome == outcomes.REJECTED or (job.track and status == "REJECTED"):
            publication.registry = self.rejected_registry(job, self.COOLDOWN_HOURS, "Yandex")
            publication.message += (f"; cooldown: no new request before "
                                    f"{publication.registry['other_ids']['next_request_after']}"
                                    f" (24 h doubling to 16 days); never re-requested "
                                    f"automatically")
            return publication
        if job.track and status in ("PUBLISHED", "PENDING_REVIEW"):
            publication.registry = {"status": status}
        if publication.outcome == outcomes.HUMAN_REQUIRED:
            self.hand_off(publication, result, "in the console")
        if publication.outcome == outcomes.UPLOAD_COMPLETE and \
                self.registry_status_for(result.get("status_before")) == "PUBLISHED":
            publication.message += ("; a new draft over the live game (Create draft): the "
                                    "live version stays up during the review")
        return publication

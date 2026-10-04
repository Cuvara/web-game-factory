"""Y8 (account.y8.com, the Studio): the profile-driven console adapter with Y8's own rules.

Every locator, url and status word is data in core/reference/publication/y8.yaml, each a
documented label or a HYPOTHESIS until a person has observed the console (`wgf-publish.py
observe y8`); the profile says `status: unverified` and `automation_terms: unverified`, so
the publish step stops HUMAN_REQUIRED before this adapter is reached on a real install.
FIXTURE_VALIDATED only (the fixture portal's `y8` flavor, scripts/tests/
test_publish_portals.py); nothing here is verified on the live console.

Order (create-before-build, wired by the step):

    1. the Studio comes first - a person's: logo, name (4-32 chars, unique, PERMANENT once
       published), About, links, the terms checkbox. The flow's `studio.check` reads the
       Studio's mark on the console; a console without it stops HUMAN_REQUIRED (legal) before
       anything is created
    2. create the game - its name only; the portal issues the Game ID and the App ID
       (identity.issued_on_create): the visit stops IDS_ISSUED, nothing uploaded
    3. the sdk step writes the ids into game.config.yaml, the build is made again, verified,
       released, validated, G6 again
    4. upload the build under My Games, fill the Basic Info tab, save: UPLOAD_COMPLETE
    5. a person's `submit`: "Submit for Reviews", once

Status vocabulary (profile `status.states` -> portal registry status):

    Draft      DRAFT           a created game, not submitted
    Pending    PENDING_REVIEW  the submitted word
    Approved   PUBLISHED       live
    Rejected   REJECTED        the resubmission cooldown starts (below)

Review handling: Y8's feedback is in the game's Feedback tab; the flow reads it on every
visit (`feedback.read`, at read_status) and it is recorded as status evidence, and quoted
with a rejection. Resubmission cooldowns - 0, 6 h, 12 h, 24 h, 2 days, then 5 days (the
profile's `constraints.resubmission_cooldown`; COOLDOWN_HOURS, kept equal by a test): the
next allowed time goes into the registry entry's other_ids.next_request_after and a
confirmed request before it is refused. Nothing re-requests a review automatically.
UNVERIFIED: the exemption above 10 M plays is not modeled.

Human handoffs (HANDOFFS): the Studio, and the payout (YMP or AFP).
"""

from .. import outcomes
from ..evidence import Evidence
from .portal import PortalAdapter

__all__ = ["Y8Adapter"]

STUDIO_CHECK = "studio.check"
FEEDBACK = "feedback.read"


class Y8Adapter(PortalAdapter):
    STATUS = {
        "Draft": "DRAFT",
        "Pending": "PENDING_REVIEW",
        "Approved": "PUBLISHED",
        "Rejected": "REJECTED",
    }
    # Hours after the 1st, 2nd, ... rejection: 0, 6 h, 12 h, 24 h, 2 days, then 5 days.
    COOLDOWN_HOURS = (0, 6, 12, 24, 48, 120)
    HANDOFFS = {
        "declare.studio": ("legal", "create the Studio: logo, name (4-32 chars, unique, "
                                    "permanent once published), About, links, the terms "
                                    "checkbox"),
        "declare.payout": ("legal", "choose YMP (50% share, PayPal or bank, tax details) or "
                                    "AFP via Google"),
    }

    def refuse(self, job):
        return self.cooldown(job, self.COOLDOWN_HOURS, "Y8")

    def adjust(self, publication, job, result, flow):
        pid = self.platform_id
        stop = result.get("stop") or {}
        if stop.get("intent") == STUDIO_CHECK and publication.outcome == outcomes.UNKNOWN:
            publication.outcome = outcomes.HUMAN_REQUIRED
            publication.human_reason = "legal"
            publication.resume_with = "wgf decide <run-id> done (after creating the Studio)"
            publication.message = (f"{pid}: the console shows no Studio: a person creates it "
                                   f"first - {self.HANDOFFS['declare.studio'][1]}; nothing was "
                                   f"created")
            return publication
        feedback = self.read_lines(job, publication, FEEDBACK)
        if feedback:
            publication.evidence.append(Evidence.console_text("Feedback tab", feedback[-1],
                                                              phase="status_gate"))
        if publication.outcome == outcomes.IDS_ISSUED:
            publication.message += ("; the sdk step writes the Game ID and the App ID into "
                                    "game.config.yaml (WGF_Y8_GAME_ID, WGF_Y8_APP_ID) and the "
                                    "build is made again before any upload")
            return publication
        word = publication.status_text
        status = self.registry_status_for(word)
        if publication.outcome == outcomes.REJECTED or (job.track and status == "REJECTED"):
            publication.registry = self.rejected_registry(job, self.COOLDOWN_HOURS, "Y8")
            publication.message += (f"; feedback: {feedback[-1]!r}" if feedback else
                                    "; no feedback was read") + (
                f"; next request no earlier than "
                f"{publication.registry['other_ids']['next_request_after']}; never "
                f"re-requested automatically")
            return publication
        if job.track and status in ("PUBLISHED", "PENDING_REVIEW"):
            publication.registry = {"status": status}
        if publication.outcome == outcomes.HUMAN_REQUIRED:
            self.hand_off(publication, result, "in the Studio")
        return publication

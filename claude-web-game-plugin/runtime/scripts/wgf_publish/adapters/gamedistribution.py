"""GameDistribution (developer.gamedistribution.com): the profile-driven console adapter with
GameDistribution's own rules.

Every locator, url and status word is data in core/reference/publication/gamedistribution.yaml,
each a documented fact or a HYPOTHESIS until a person has observed the panel; the profile
says `status: unverified` and `automation_terms: unverified`, so the publish step stops
HUMAN_REQUIRED before this adapter is reached on a real install. FIXTURE_VALIDATED only (the
fixture portal's `gamedistribution` flavor, scripts/tests/test_publish_portals.py); nothing
here is verified on the live panel.

Prerequisites: the profile's `prerequisites` (the developer account with its company, the
developer terms, and - self-hosted only - GameDistribution's written consent) are a person's.
Any a person has not recorded in factory.publish.platforms.gamedistribution.
prerequisites_confirmed stops the visit HUMAN_REQUIRED (legal) before the panel is contacted.
The game.config.yaml entry is not read here, so a `when`-limited prerequisite applies too:
an unknown is never read as satisfied.

Game ID: the panel's Game ID ("game hash") must be in the build (the SDK reads it). Whether
the panel issues it on creating the game, before any upload, is not stated - so this adapter
does NOT create games: a person creates the game in the panel and enters its Game ID in
game.config.yaml (platforms[gamedistribution].game_id); the build is made with it. A job
whose build carries no Game ID stops HUMAN_REQUIRED before the panel is contacted, and the
visit finds the game by that id (identity `config:game_id`), never by creating one.

Status vocabulary (profile `status.states` -> portal registry status):

    Draft     DRAFT
    Pending   PENDING_REVIEW  the submitted word: review and QA
    Live      PUBLISHED       "activated"
    Rejected  REJECTED        returned with feedback

Review handling: publication is requested with "the designated button within your control
panel", whose label is not public - the profile has no request_review intent, so a confirmed
visit stops HUMAN_REQUIRED (a person clicks it) and a later visit (or `--track`) reads
Pending. No cooldown is documented.

Human handoffs (HANDOFFS): watching the pre-roll once from the upload view (activates the
SDK, up to two weeks), the rewarded-ads flag, the age groups.
"""

from wgflib import publication as pub

from .. import outcomes
from .portal import PortalAdapter

__all__ = ["GameDistributionAdapter"]


class GameDistributionAdapter(PortalAdapter):
    STATUS = {
        "Draft": "DRAFT",
        "Pending": "PENDING_REVIEW",
        "Live": "PUBLISHED",
        "Rejected": "REJECTED",
    }
    HANDOFFS = {
        "declare.preroll": ("declaration", "open the game in its iframe from the upload view "
                                           "and watch the pre-roll once (activates the SDK)"),
        "declare.rewarded-flag": ("declaration", "set the rewarded-ads flag when the game "
                                                 "uses rewarded ads"),
        "declare.age-group": ("declaration", "select the age groups, and \"kids friendly\" or "
                                             "\"no blood\" where they apply"),
    }

    def refuse(self, job):
        unmet = pub.unmet_prerequisites(self.profile, self.settings, None)
        if unmet:
            what = "; ".join(f"{item.get('id')}: {str(item.get('note') or '').strip()}"
                             for item in unmet)
            return self.stop(outcomes.HUMAN_REQUIRED,
                             f"prerequisites a person has not recorded "
                             f"(factory.publish.platforms.{self.platform_id}."
                             f"prerequisites_confirmed): {what}",
                             reason=unmet[0].get("reason") or "legal",
                             data={"unmet": [item.get("id") for item in unmet]})
        if not (job.identity or {}).get("config_game_id"):
            return self.stop(outcomes.HUMAN_REQUIRED,
                             "the build carries no GameDistribution Game ID: a person creates "
                             "the game in the developer panel, enters its Game ID in "
                             "game.config.yaml (platforms[gamedistribution].game_id), and the "
                             "build is made again - the SDK needs it before any upload",
                             reason="manual-submission")
        return self.cooldown(job, (), "GameDistribution")

    def adjust(self, publication, job, result, flow):
        pid = self.platform_id
        stop = result.get("stop") or {}
        status = self.registry_status_for(publication.status_text)
        if stop.get("code") == "manual-request":
            publication.message = (f"{pid}: the build is on the game and the panel holds it; "
                                   f"publication is requested with the panel's designated "
                                   f"button (its label is not public): a person clicks it, "
                                   f"then `wgf decide <run-id> done` - a later visit reads "
                                   f"Pending")
            return publication
        if stop.get("code") == "manual-create":
            publication.message = (f"{pid}: the panel lists no game with the build's Game ID: "
                                   f"a person creates it and records the id; nothing is "
                                   f"created here")
            return publication
        if publication.outcome == outcomes.REJECTED or (job.track and status == "REJECTED"):
            publication.registry = {"status": "REJECTED"}
        elif job.track and status in ("PUBLISHED", "PENDING_REVIEW"):
            publication.registry = {"status": status}
        if status == "PUBLISHED":
            publication.message += "; activated on GameDistribution"
        if publication.outcome == outcomes.HUMAN_REQUIRED:
            self.hand_off(publication, result, "in the panel")
        return publication

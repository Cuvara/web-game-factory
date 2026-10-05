"""GamePix (my.gamepix.com, the GamePix Dashboard): the profile-driven console adapter with
GamePix's own rules.

NOT A TARGET YET. The pinned template has no GamePix SDK adapter, so no build the Factory
makes today carries the GamePix SDK, and GamePix's terms take only a game that calls it
(core/reference/platforms/gamepix.yaml, `gamepix_sdk_present`). This adapter refuses BLOCKED
before the dashboard is contacted unless the package's build carries the SDK - the
manifest package's `platform_sdk` is `gamepix`, or the archive references gamepix.sdk.js.
The refusal names the human action: HUMAN_ACTION_REQUIRED - a template release carrying the
GamePix SDK adapter, and the Factory's template pin moved to it.

Every locator, url and status word is data in core/reference/publication/gamepix.yaml, each a
documented fact or a HYPOTHESIS (the public pages name no dashboard control); the profile
says `status: unverified` and `automation_terms: unverified`, so the publish step stops
HUMAN_REQUIRED before this adapter is reached on a real install. FIXTURE_VALIDATED only (the
fixture portal's `gamepix` flavor, scripts/tests/test_publish_portals.py, with an archive
that carries the SDK); nothing here is verified on the live dashboard.

Status vocabulary (profile `status.states`, every word a hypothesis -> registry status):

    Draft        DRAFT
    In review    PENDING_REVIEW  the submitted word (a hypothesis)
    Published    PUBLISHED
    Rejected     REJECTED

Review handling: the dashboard's submit control is not public - the profile has no
request_review intent, so a confirmed visit stops HUMAN_REQUIRED and a person submits. No
cooldown is documented.

Human handoffs (HANDOFFS): "Allow Distribution" or exclusivity on gamepix.com (a commercial
choice), the child-directed declaration (COPPA, on every upload and update), the AI
declarations - whether the game incorporates an AI System, and every submitted asset or text
made or materially altered with generative AI (content_policy `disclose`, 4.10: disclosed
only from a person's statement, never inferred) - and the testkit run.
"""

import zipfile

from .. import outcomes
from .portal import PortalAdapter

__all__ = ["GamePixAdapter"]

SDK_MARK = b"gamepix.sdk.js"


class GamePixAdapter(PortalAdapter):
    STATUS = {
        "Draft": "DRAFT",
        "In review": "PENDING_REVIEW",
        "Published": "PUBLISHED",
        "Rejected": "REJECTED",
    }
    HANDOFFS = {
        "declare.distribution": ("legal", "choose \"Allow Distribution\" (third-party sites "
                                          "too) or not (exclusive to gamepix.com)"),
        "declare.child-directed": ("declaration", "declare whether the game is child-directed "
                                                  "under COPPA (when uncertain: it is)"),
        "declare.ai": ("declaration", "declare any AI System in the game, and every asset or "
                                      "text made or materially altered with generative AI "
                                      "(4.10)"),
        "declare.testkit": ("declaration", "validate the integration with the testkit"),
    }

    def carries_sdk(self, job):
        """(True|False, how it was established)."""
        if str((job.package or {}).get("platform_sdk") or "") == "gamepix":
            return True, "the manifest package's platform_sdk is gamepix"
        try:
            with zipfile.ZipFile(job.package_path) as archive:
                for name in archive.namelist():
                    if name.lower().endswith((".html", ".htm", ".js")) and \
                            SDK_MARK in archive.read(name).lower():
                        return True, f"{name} references gamepix.sdk.js"
        except (OSError, zipfile.BadZipFile, KeyError, TypeError):
            return False, "the package could not be read"
        return False, "no file of the package references gamepix.sdk.js"

    def refuse(self, job):
        carries, how = self.carries_sdk(job)
        if not carries:
            return self.stop(outcomes.BLOCKED,
                             f"the build does not carry the GamePix SDK ({how}); the pinned "
                             f"template has no GamePix SDK adapter. HUMAN_ACTION_REQUIRED: a "
                             f"template release carrying it, and the Factory's template pin "
                             f"(workspace/config/template.lock.json) moved to that release",
                             data={"human_action_required": "template release + pin"})
        return self.cooldown(job, (), "GamePix")

    def adjust(self, publication, job, result, flow):
        pid = self.platform_id
        stop = result.get("stop") or {}
        status = self.registry_status_for(publication.status_text)
        if stop.get("code") == "manual-request":
            publication.message = (f"{pid}: the build is on the dashboard and saved; its "
                                   f"submit control is not public: a person submits it, then "
                                   f"`wgf decide <run-id> done`")
            return publication
        if publication.outcome == outcomes.REJECTED or (job.track and status == "REJECTED"):
            publication.registry = {"status": "REJECTED"}
        elif job.track and status in ("PUBLISHED", "PENDING_REVIEW"):
            publication.registry = {"status": status}
        if publication.outcome == outcomes.HUMAN_REQUIRED:
            pending = self.hand_off(publication, result, "on the dashboard")
            if "declare.ai" in pending:
                publication.message += ("; GamePix asks generated content to be DISCLOSED: "
                                        "a person states it, nothing is inferred")
        return publication

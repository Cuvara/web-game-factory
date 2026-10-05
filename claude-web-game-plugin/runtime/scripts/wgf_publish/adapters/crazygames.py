"""CrazyGames Developer Portal: the profile-driven console adapter with CrazyGames' own rules.

Every locator, url and status word is data in core/reference/publication/crazygames.yaml,
each a documented label or a HYPOTHESIS until a person has observed the console
(`wgf-publish.py observe crazygames`); the profile says `status: unverified` and
`automation_terms: unverified`, so the publish step stops HUMAN_REQUIRED before this adapter
is reached on a real install. FIXTURE_VALIDATED only (the fixture portal's `crazygames`
flavor, scripts/tests/test_publish_portals.py); nothing here is verified on the live console.

Status vocabulary (profile `status.states` -> portal registry status):

    Draft          DRAFT           the submission form, saved
    In review      PENDING_REVIEW  the submitted word: initial QA (bugs, quality, English,
                                   originality, PEGI 12)
    Basic Launch   PUBLISHED       live, monetization off, 7-21 days of measurement
    Full Launch    PUBLISHED       live and paid - CrazyGames' decision alone
    Rejected       REJECTED

Review handling: "Submit a game" opens the submission form and the QA tool; the request
(`review.request`) is made once, on a person's confirmed `submit`. Basic Launch is reported
as live with what it means; Full Launch is CrazyGames' decision and is NEVER a click - a
profile whose flow names "Full Launch" is refused before the console is contacted. An update
of a live game is "processed the same working day" (documented): reported, not relied on.

Upload shape: whether the portal takes the build as one zip or as its files is UNKNOWN. The
profile models both (`upload.zip`, `upload.files`, each optional); this adapter hands
`upload.files` the package's files, unpacked, and a visit that found neither widget is
UNKNOWN - never read as uploaded.

Human handoffs (HANDOFFS): the Developer Portal terms, exclusivity, the warranties, payout
and tax, and the launch options (the Progress Save toggle, orientation) are a person's.
"""

import os
import zipfile

from .. import outcomes
from ..evidence import file_sha256
from .portal import PortalAdapter

__all__ = ["CrazyGamesAdapter"]

UPLOAD_ZIP, UPLOAD_FILES = "upload.zip", "upload.files"


class CrazyGamesAdapter(PortalAdapter):
    STATUS = {
        "Draft": "DRAFT",
        "In review": "PENDING_REVIEW",
        "Basic Launch": "PUBLISHED",
        "Full Launch": "PUBLISHED",
        "Rejected": "REJECTED",
    }
    # CrazyGames' decisions, never a click: no intent may name them.
    NEVER_CLICKED = ("full launch",)
    HANDOFFS = {
        "declare.terms": ("legal", "read and accept the Developer Portal Terms (18.08.2025)"),
        "declare.exclusivity": ("legal", "choose exclusivity or not (Terms 3.1, 5.5): a "
                                         "commercial choice"),
        "declare.warranties": ("declaration", "give the accuracy and IP ownership warranties "
                                              "(Terms 7.1)"),
        "declare.payout": ("legal", "enter the payout and tax details"),
        "declare.launch_options": ("declaration", "set the Progress Save toggle and the "
                                                  "orientation; Full Launch is CrazyGames' "
                                                  "decision"),
    }

    def refuse(self, job):
        for intent in self.submission.get("flow") or []:
            words = " ".join(str(v) for rung in intent.get("target") or [] for v in rung.values())
            words += " " + " ".join(intent.get("names") or [])
            if any(w in words.casefold() for w in self.NEVER_CLICKED):
                return self.stop(outcomes.BLOCKED,
                                 f"the profile's intent {intent.get('id')} names Full Launch, "
                                 f"which is CrazyGames' decision and never a click")
        return self.cooldown(job, (), "CrazyGames")

    def intents(self, job):
        """The profile's flow; `upload.files` gets the package's files, unpacked."""
        intents, problems, unfilled = super().intents(job)
        for item in intents:
            if item.get("id") == UPLOAD_FILES and item.get("files"):
                files = self._unpacked(job)
                item["files"] = files
                item["multiple"] = True
        return intents, problems, unfilled

    @staticmethod
    def _unpacked(job):
        target = os.path.join(job.scratch_dir, "package-files")
        out = []
        try:
            with zipfile.ZipFile(job.package_path) as archive:
                for name in sorted(archive.namelist()):
                    if name.endswith("/") or ".." in name.split("/"):
                        continue
                    path = os.path.join(target, *name.split("/"))
                    os.makedirs(os.path.dirname(path), exist_ok=True)
                    with archive.open(name) as src, open(path, "wb") as dst:
                        dst.write(src.read())
                    out.append({"path": os.path.abspath(path).replace(os.sep, "/"),
                                "name": name, "sha256": file_sha256(path)})
        except (OSError, zipfile.BadZipFile):
            return []
        return out

    def adjust(self, publication, job, result, flow):
        word = publication.status_text
        status = self.registry_status_for(word)
        absent = set(result.get("absent") or ())
        if publication.uploaded and {UPLOAD_ZIP, UPLOAD_FILES} <= absent:
            publication.outcome = outcomes.UNKNOWN
            publication.human_reason = "ambiguous-portal-state"
            publication.resume_with = "wgf decide <run-id> done|abandon"
            publication.message = (f"{self.platform_id}: the console showed neither a zip nor "
                                   f"a files upload widget: the build is NOT on the portal; a "
                                   f"person records which one it takes in the profile")
            publication.uploaded = False
            return publication
        if publication.outcome == outcomes.UPLOAD_COMPLETE:
            shape = "files" if UPLOAD_ZIP in absent else "zip"
            publication.message += f"; uploaded as {shape}"
        if word and word.strip().casefold() == "basic launch":
            publication.message += ("; Basic Launch: live with monetization off for 7-21 days. "
                                    "Full Launch is CrazyGames' decision - nothing requests or "
                                    "clicks it")
        if publication.outcome == outcomes.SUBMITTED and self._live_before(job.registry_entry):
            publication.message += "; an update of a live game: processed the same working day"
        if publication.outcome == outcomes.REJECTED or (job.track and status == "REJECTED"):
            publication.registry = {"status": "REJECTED"}
        elif job.track and status in ("PUBLISHED", "PENDING_REVIEW"):
            publication.registry = {"status": status}
        if publication.outcome == outcomes.HUMAN_REQUIRED:
            self.hand_off(publication, result, "in the portal")
        return publication

    @staticmethod
    def _live_before(entry):
        return any(item.get("to") == "PUBLISHED" for item in (entry or {}).get("history") or ())

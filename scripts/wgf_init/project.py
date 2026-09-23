"""Project metadata: what a game-design says about the repository that will hold the game.

Pure data, no side effects. The design decides the repository's name (its title id) and
description; everything the repository *contains* comes from web-game-template, and
`game.config.yaml` comes from `tech_plan.repo_params`, reviewed at G3 - never from here.
"""

import re

__all__ = ["DesignError", "ProjectMetadata", "REPO_NAME"]

# A title id is kebab-case (CLAUDE.md), which is also a valid GitHub repository name.
TITLE_ID = re.compile(r"^[a-z][a-z0-9-]*$")
# core/artifacts/scaffold-record.schema.json#/properties/repository/properties/name
REPO_NAME = re.compile(r"^[A-Za-z0-9._-]+$")
# GitHub rejects longer repository descriptions.
DESCRIPTION_LIMIT = 350


class DesignError(ValueError):
    """The game-design cannot be scaffolded. Retrying will not change that."""


def _first_sentence(text):
    text = " ".join((text or "").split())
    match = re.match(r"^(.+?[.!?])(\s|$)", text)
    return match.group(1) if match else text


class ProjectMetadata:
    """The repository-level facts derived from one game-design."""

    def __init__(self, title_id, repo_name, summary, design_platforms):
        self.title_id = title_id
        self.repo_name = repo_name
        self.summary = summary
        self.design_platforms = design_platforms

    @classmethod
    def from_design(cls, design, project_id=None):
        if not isinstance(design, dict):
            raise DesignError("game-design is not a JSON object")

        title_id = design.get("title_id")
        if not isinstance(title_id, str) or not TITLE_ID.match(title_id):
            raise DesignError(f"game-design title_id {title_id!r} is not a kebab-case id")
        if project_id and project_id != title_id:
            raise DesignError(
                f"game-design is for {title_id!r} but this run is for project {project_id!r}"
            )

        # G3 sits between design and scaffolding, and a failing consistency result is the
        # design's exit guard. Scaffolding one would build a repository for a design that
        # never legitimately left title:design.
        consistency = design.get("consistency") or {}
        if consistency.get("status") != "pass":
            raise DesignError(
                f"game-design consistency is {consistency.get('status')!r}, not 'pass'"
            )

        platforms = []
        for placement in (design.get("monetization") or {}).get("placements") or []:
            platforms.extend(placement.get("platforms") or [])
        for applied in design.get("platform_constraints_applied") or []:
            platforms.append(applied.get("platform_id"))
        design_platforms = sorted({p for p in platforms if isinstance(p, str) and p})

        summary = _first_sentence(design.get("fantasy")) or _first_sentence(
            design.get("core_loop"))
        return cls(title_id, title_id, summary, design_platforms)

    def description(self, marker):
        """The repository description: a summary, then the idempotency marker, which must
        survive truncation because it is how a later execution recognises the repository."""
        suffix = f" [{marker}]"
        room = DESCRIPTION_LIMIT - len(suffix)
        text = f"{self.title_id}: {self.summary}" if self.summary else self.title_id
        if len(text) > room:
            text = text[: room - 1].rstrip() + "…"
        return text + suffix
